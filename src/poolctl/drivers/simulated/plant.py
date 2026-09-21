"""
A correlated software model of the pool equipment.

The simulated plant gives sensor readings believable relationships: pressures
rise when pumps run, water temperature follows a daily pattern, chemistry drifts
over time, and chlorine dosing affects ORP and tank level. It is not a physics
model; it is a deterministic-enough test fixture for controller behavior.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime

from poolctl.domain.models import ActuatorState
from poolctl.services.clock import Clock


@dataclass
class SimulatedPlant:
    """
    Simulated model of the pool system.

    This is not intended to be a perfect physics model. It is a practical test
    model that creates believable relationships between values.

    The important behaviors are:

      - pressures rise when the pump is on
      - pressures change when pump speed changes
      - water temperature rises during the day and cools overnight
      - pH and ORP drift slowly over time
      - chlorine dosing affects ORP
      - tank level drops when the chlorine dosing pump is on

    Simulated sensors read from this object.
    Simulated actuators modify this object.
    """

    clock: Clock

    # Actuator-related state.
    pump_motor: ActuatorState = ActuatorState.OFF
    pump_motor_speed: ActuatorState = ActuatorState.LOW
    booster_pump: ActuatorState = ActuatorState.OFF
    chlorine_dosing_pump: ActuatorState = ActuatorState.OFF

    # Environmental values.
    water_temp_f: float = 80.0
    air_temp_low_f: float = 72.0
    air_temp_high_f: float = 96.0

    # Internal simulated chemistry values.
    #
    # These are deliberately internal "true-ish" simulated values.
    simulated_ph: float = 7.55
    simulated_orp_mv: float = 675.0
    true_fc_ppm: float = 4.0

    # Chlorine tank level as percent.
    tank_level_percent: float = 100.0

    # Noise configuration. A seed makes sensor noise reproducible for tests.
    noise_seed: int | None = None
    noise_stddev_scale: float = 1.0
    _rng: random.Random = field(init=False, repr=False)

    # Internal time bookkeeping.
    last_update_at: datetime | None = None

    def __post_init__(self) -> None:
        self._rng = random.Random(self.noise_seed)

    def update(self) -> None:
        """
        Advance the simulated plant state up to the current clock time.

        This method should be called before sensor reads and around actuator
        state changes. It keeps slow-changing values evolving as simulated time
        advances.
        """
        now = self.clock.now()

        if self.last_update_at is None:
            self.last_update_at = now
            return

        elapsed_s = max(0.0, (now - self.last_update_at).total_seconds())

        if elapsed_s <= 0:
            return

        self.last_update_at = now

        elapsed_hours = elapsed_s / 3600.0

        # Slow plant dynamics use elapsed time. If the SimulatedClock runs 60x
        # faster than real time, these values also evolve 60x faster.
        self._update_water_temperature(now, elapsed_hours)
        self._update_chemistry(elapsed_hours)
        self._update_tank_level(elapsed_hours)

    def set_pump_motor(self, state: ActuatorState) -> None:
        """
        Set the simulated pump motor state.

        This helper is intended for simulated actuator drivers.
        """
        self.update()
        self.pump_motor = state
        self.update()

    def set_pump_motor_speed(self, state: ActuatorState) -> None:
        """
        Set the simulated pump motor speed.

        Expected states are LOW or HIGH.
        """
        self.update()
        self.pump_motor_speed = state
        self.update()

    def set_booster_pump(self, state: ActuatorState) -> None:
        """
        Set the simulated booster pump state.
        """
        self.update()
        self.booster_pump = state
        self.update()

    def set_chlorine_dosing_pump(self, state: ActuatorState) -> None:
        """
        Set the simulated chlorine dosing pump state.
        """
        self.update()
        self.chlorine_dosing_pump = state
        self.update()

    def pump_is_on(self) -> bool:
        return self.pump_motor == ActuatorState.ON

    def booster_is_on(self) -> bool:
        return self.booster_pump == ActuatorState.ON

    def pump_speed_factor(self) -> float:
        """
        Return a multiplier for pressure-related simulated values.

        Pump off:
            0.0

        Pump on, low speed:
            0.3

        Pump on, high speed:
            1.0
        """
        if not self.pump_is_on():
            return 0.0

        if self.pump_motor_speed == ActuatorState.HIGH:
            return 1.0

        return 0.3

    def pressure_psi(self, sensor_name: str) -> float:
        """
        Return simulated pressure for one pressure sensor.

        Supported sensor_name values:
            pump_output_psi
        """
        self.update()

        speed = self.pump_speed_factor()

        if speed <= 0.0:
            # Real pressure transducers rarely read exactly zero, so the
            # simulator leaves a small noisy residual pressure with the pump off.
            return max(0.0, self._noisy(0.25, 0.12))

        if sensor_name == "pump_output_psi":
            base = 12.0 * speed
        else:
            base = 0.0

        return max(0.0, self._noisy(base, 0.35))

    def measured_water_temp_f(self) -> float:
        """
        Return simulated main water temperature.
        """
        self.update()
        return self._noisy(self.water_temp_f, 0.15)

    def orp_probe_temp_f(self) -> float:
        """
        Return simulated temperature near the ORP probe.
        """
        self.update()
        return self._noisy(self.water_temp_f, 0.10)

    def ph_probe_temp_f(self) -> float:
        """
        Return simulated temperature near the pH probe.
        """
        self.update()
        return self._noisy(self.water_temp_f, 0.12)

    def raw_ph(self) -> float:
        """
        Return simulated pH in pH units.
        """
        self.update()

        return self._noisy(self.simulated_ph, 0.015)

    def raw_orp_mv(self) -> float:
        """
        Return fake raw ORP sensor millivolts.
        """
        self.update()
        return self._noisy(self.simulated_orp_mv, 4.0)

    def tank_level(self) -> float:
        """
        Return simulated tank level as percent full.
        """
        self.update()
        return clamp(self._noisy(self.tank_level_percent, 0.2), 0.0, 100.0)

    def _update_water_temperature(self, now: datetime, elapsed_hours: float) -> None:
        """
        Move water temperature slowly toward a time-of-day-dependent air temp.

        This creates a believable daily water temperature cycle without trying
        to be a detailed thermal model.
        """
        target_temp = self._ambient_temperature_f(now)

        # Water has thermal mass, so it moves slowly toward ambient.
        response_rate_per_hour = 0.08

        self.water_temp_f += (
            target_temp - self.water_temp_f
        ) * response_rate_per_hour * elapsed_hours

        self.water_temp_f = clamp(self.water_temp_f, 40.0, 105.0)

    def _update_chemistry(self, elapsed_hours: float) -> None:
        """
        Very rough chemistry drift model.

        This is intentionally simple. It only gives the estimator/dashboard
        plausible data during development.
        """
        # pH slowly rises.
        ph_rise_per_hour = 0.002

        # ORP slowly decays when not dosing.
        orp_decay_per_hour = 0.8
        fc_decay_ppm_per_hour = 0.03

        self.simulated_ph += ph_rise_per_hour * elapsed_hours
        self.simulated_orp_mv -= orp_decay_per_hour * elapsed_hours
        self.true_fc_ppm -= fc_decay_ppm_per_hour * elapsed_hours

        if self.chlorine_dosing_pump == ActuatorState.ON:
            # Dosing changes chemistry gradually, so the live/history charts show
            # a slow response rather than an instant step change.
            # Dosing increases ORP and slightly raises simulated pH.
            self.simulated_orp_mv += 25.0 * elapsed_hours
            self.simulated_ph += 0.003 * elapsed_hours
            self.true_fc_ppm += 0.2 * elapsed_hours

        self.simulated_ph = clamp(self.simulated_ph, 6.8, 8.4)
        self.simulated_orp_mv = clamp(self.simulated_orp_mv, 450.0, 850.0)
        self.true_fc_ppm = clamp(self.true_fc_ppm, 0.0, 20.0)

    def _update_tank_level(self, elapsed_hours: float) -> None:
        """
        Decrease chlorine tank level while the chlorine dosing pump is on.
        """
        if self.chlorine_dosing_pump == ActuatorState.ON:
            # This is only a visible simulation cue, not a calibrated tank model.
            tank_drop_percent_per_hour = 2.0
            self.tank_level_percent -= tank_drop_percent_per_hour * elapsed_hours

        self.tank_level_percent = clamp(self.tank_level_percent, 0.0, 100.0)

    def _ambient_temperature_f(self, now: datetime) -> float:
        """
        Approximate outdoor air temperature as a daily sine wave.

        Warmest part of the day is modeled around mid-afternoon.
        """
        hour = now.hour + now.minute / 60.0 + now.second / 3600.0

        average = (self.air_temp_high_f + self.air_temp_low_f) / 2.0
        amplitude = (self.air_temp_high_f - self.air_temp_low_f) / 2.0

        # Shift so the peak occurs around 15:00 local/simulated time.
        radians = 2.0 * math.pi * (hour - 9.0) / 24.0

        return average + amplitude * math.sin(radians)

    def _noisy(self, value: float, std_dev: float) -> float:
        """
        Add small per-plant Gaussian noise to a simulated value.
        """
        return value + self._rng.gauss(0.0, std_dev * self.noise_stddev_scale)


def noisy(value: float, std_dev: float) -> float:
    """
    Add small Gaussian noise to a simulated value.

    Retained for older tests or utility callers. SimulatedPlant methods use a
    per-plant RNG so independent plants do not share global random state.
    """
    return value + random.gauss(0.0, std_dev)


def clamp(value: float, minimum: float, maximum: float) -> float:
    """
    Clamp value between minimum and maximum.
    """
    return max(minimum, min(maximum, value))
