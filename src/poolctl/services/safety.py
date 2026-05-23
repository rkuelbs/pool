from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from poolctl.domain.models import (
    ActuatorCommand,
    ActuatorId,
    ActuatorState,
    CommandSource,
    Measurement,
    Quality,
    SensorId,
)


class SafetySeverity(str, Enum):
    """
    Severity for safety faults that place the system into lockout.
    """

    WARNING = "warning"
    ERROR = "error"


class FreezeProtectionSource(str, Enum):
    TEMP = "temp"
    PH_TEMP = "ph_temp"
    BOTH = "both"


class TemperatureUnit(str, Enum):
    DEG_F = "degF"
    DEG_C = "degC"


@dataclass(frozen=True)
class PressureSensorConfig:
    """
    Sensor IDs used by safety rules that depend on pressure readings.

    Keeping these configurable lets the Pi deployment map safety logic to the
    actual pressure transducer channels without changing controller code.
    """

    pump_output: SensorId = SensorId.PUMP_OUTPUT_PSI
    return_line: SensorId = SensorId.RETURN_PSI
    booster: SensorId = SensorId.BOOSTER_PSI


@dataclass(frozen=True)
class FreezeProtectionConfig:
    """
    Freeze protection settings.

    The freeze gate uses raw temperature measurements (quality is ignored) so
    it can still protect plumbing while chemistry-loop validity is false.
    """

    enabled: bool = False
    source: FreezeProtectionSource = FreezeProtectionSource.TEMP
    temp_sensor: SensorId = SensorId.TEMP
    ph_temp_sensor: SensorId = SensorId.ORP_TEMP
    low_speed_on_below_temp: float = 35.0
    low_speed_off_above_temp: float = 37.0
    high_speed_on_below_temp: float = 33.0
    high_speed_off_above_temp: float = 34.0
    min_run_seconds: float = 600.0
    threshold_unit: TemperatureUnit = TemperatureUnit.DEG_F

    def __post_init__(self) -> None:
        if self.high_speed_on_below_temp > self.low_speed_on_below_temp:
            raise ValueError(
                "freeze high_speed_on_below_temp must be less than or equal to low_speed_on_below_temp"
            )
        if self.high_speed_off_above_temp > self.low_speed_off_above_temp:
            raise ValueError(
                "freeze high_speed_off_above_temp must be less than or equal to low_speed_off_above_temp"
            )
        if self.low_speed_on_below_temp > self.low_speed_off_above_temp:
            raise ValueError(
                "freeze low_speed_on_below_temp must be less than or equal to low_speed_off_above_temp"
            )
        if self.high_speed_on_below_temp > self.high_speed_off_above_temp:
            raise ValueError(
                "freeze high_speed_on_below_temp must be less than or equal to high_speed_off_above_temp"
            )
        if self.min_run_seconds < 0:
            raise ValueError("freeze min_run_seconds must be >= 0")


@dataclass(frozen=True)
class SafetyConfig:
    """
    Configurable safety thresholds and timers.
    """

    pressure_sensors: PressureSensorConfig = field(default_factory=PressureSensorConfig)
    freeze_protection: FreezeProtectionConfig = field(default_factory=FreezeProtectionConfig)

    chlorine_min_return_psi: float = 2.0
    chlorine_min_pump_output_psi: float = 6.0

    booster_max_psi: float = 60.0
    booster_min_psi: float = 30.0
    booster_low_pressure_grace_s: float = 10.0

    pump_low_prime_min_output_psi: float = 1.0
    pump_low_prime_seconds: float = 30.0

    pump_output_overpressure_psi: float = 30.0
    pump_high_prime_min_output_psi: float = 5.0
    pump_high_prime_timeout_s: float = 30.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> SafetyConfig:
        safety_data = _mapping_value(data, "safety", default=data)
        pressure_data = _mapping_value(safety_data, "pressure_sensor_ids", default={})
        threshold_data = _mapping_value(safety_data, "thresholds", default={})
        timeout_data = _mapping_value(safety_data, "timeouts", default={})
        freeze_data = _mapping_value(safety_data, "freeze_protection", default={})

        pressure_sensors = PressureSensorConfig(
            pump_output=_sensor_id_value(
                pressure_data,
                "pump_output",
                PressureSensorConfig().pump_output,
            ),
            return_line=_sensor_id_value(
                pressure_data,
                "return_line",
                PressureSensorConfig().return_line,
            ),
            booster=_sensor_id_value(
                pressure_data,
                "booster",
                PressureSensorConfig().booster,
            ),
        )

        return cls(
            pressure_sensors=pressure_sensors,
            freeze_protection=FreezeProtectionConfig(
                enabled=_bool_value(
                    freeze_data,
                    "enabled",
                    FreezeProtectionConfig.enabled,
                ),
                source=_freeze_source_value(
                    freeze_data,
                    "source",
                    FreezeProtectionConfig.source,
                ),
                temp_sensor=_sensor_id_value(
                    freeze_data,
                    "temp_sensor",
                    FreezeProtectionConfig().temp_sensor,
                ),
                ph_temp_sensor=_sensor_id_value(
                    freeze_data,
                    "ph_temp_sensor",
                    FreezeProtectionConfig().ph_temp_sensor,
                ),
                low_speed_on_below_temp=_float_alias_value(
                    freeze_data,
                    key="low_speed_on_below_temp",
                    aliases=("low_speed_below_temp",),
                    default=FreezeProtectionConfig.low_speed_on_below_temp,
                ),
                low_speed_off_above_temp=_float_value(
                    freeze_data,
                    "low_speed_off_above_temp",
                    FreezeProtectionConfig.low_speed_off_above_temp,
                ),
                high_speed_on_below_temp=_float_alias_value(
                    freeze_data,
                    key="high_speed_on_below_temp",
                    aliases=("high_speed_below_temp",),
                    default=FreezeProtectionConfig.high_speed_on_below_temp,
                ),
                high_speed_off_above_temp=_float_value(
                    freeze_data,
                    "high_speed_off_above_temp",
                    FreezeProtectionConfig.high_speed_off_above_temp,
                ),
                min_run_seconds=_float_value(
                    freeze_data,
                    "min_run_seconds",
                    FreezeProtectionConfig.min_run_seconds,
                ),
                threshold_unit=_temperature_unit_value(
                    freeze_data,
                    "threshold_unit",
                    FreezeProtectionConfig.threshold_unit,
                ),
            ),
            chlorine_min_return_psi=_float_value(
                threshold_data,
                "chlorine_min_return_psi",
                cls.chlorine_min_return_psi,
            ),
            chlorine_min_pump_output_psi=_float_value(
                threshold_data,
                "chlorine_min_pump_output_psi",
                cls.chlorine_min_pump_output_psi,
            ),
            booster_max_psi=_float_value(
                threshold_data,
                "booster_max_psi",
                cls.booster_max_psi,
            ),
            booster_min_psi=_float_value(
                threshold_data,
                "booster_min_psi",
                cls.booster_min_psi,
            ),
            booster_low_pressure_grace_s=_float_value(
                timeout_data,
                "booster_low_pressure_grace_s",
                cls.booster_low_pressure_grace_s,
            ),
            pump_low_prime_min_output_psi=_float_value(
                threshold_data,
                "pump_low_prime_min_output_psi",
                cls.pump_low_prime_min_output_psi,
            ),
            pump_low_prime_seconds=_float_value(
                timeout_data,
                "pump_low_prime_seconds",
                cls.pump_low_prime_seconds,
            ),
            pump_output_overpressure_psi=_float_value(
                threshold_data,
                "pump_output_overpressure_psi",
                cls.pump_output_overpressure_psi,
            ),
            pump_high_prime_min_output_psi=_float_value(
                threshold_data,
                "pump_high_prime_min_output_psi",
                cls.pump_high_prime_min_output_psi,
            ),
            pump_high_prime_timeout_s=_float_value(
                timeout_data,
                "pump_high_prime_timeout_s",
                cls.pump_high_prime_timeout_s,
            ),
        )


@dataclass(frozen=True)
class SafetyFault:
    """
    Active lockout fault raised by the safety gate.
    """

    code: str
    severity: SafetySeverity
    message: str
    raised_at: datetime


@dataclass(frozen=True)
class SafetySnapshot:
    """
    Current system state as seen by the safety gate.
    """

    now: datetime
    actuator_states: Mapping[ActuatorId, ActuatorState]
    state_started_at: Mapping[ActuatorId, datetime]
    measurements: Mapping[SensorId, Measurement]

    def actuator_state(self, actuator_id: ActuatorId) -> ActuatorState | None:
        return self.actuator_states.get(actuator_id)

    def state_since(self, actuator_id: ActuatorId) -> datetime:
        return self.state_started_at.get(actuator_id, self.now)

    def pressure_psi(self, sensor_id: SensorId) -> float | None:
        measurement = self.measurements.get(sensor_id)

        if measurement is None:
            return None

        if measurement.quality != Quality.GOOD:
            return None

        return measurement.value

    def raw_measurement(self, sensor_id: SensorId) -> Measurement | None:
        return self.measurements.get(sensor_id)


@dataclass(frozen=True)
class SafetyDecision:
    """
    Result of checking an incoming command against current safety policy.
    """

    accepted: bool
    rejection_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SafetyAction:
    """
    System-generated command requested by the safety gate.
    """

    command: ActuatorCommand
    reason_code: str
    fault: SafetyFault | None = None


class SafetyGate:
    """
    Safety policy for pool actuator commands and live interlocks.

    This class does not talk to hardware. It only inspects a SafetySnapshot and
    returns decisions or system commands. The command router applies those
    commands through drivers.
    """

    def __init__(self, config: SafetyConfig | None = None) -> None:
        self.config = config if config is not None else SafetyConfig()
        self.active_fault: SafetyFault | None = None
        self._pump_high_started_at: datetime | None = None
        self._pump_high_observed_pressure: bool = False
        self._pump_high_reached_min_output: bool = False
        self._low_pressure_prime_until: datetime | None = None
        self._freeze_latched_speed: ActuatorState | None = None
        self._freeze_started_at: datetime | None = None
        self._freeze_observation: str | None = None

    @property
    def locked_out(self) -> bool:
        return self.active_fault is not None

    def clear_fault(self) -> None:
        self.active_fault = None
        self._pump_high_started_at = None
        self._pump_high_observed_pressure = False
        self._pump_high_reached_min_output = False
        self._low_pressure_prime_until = None
        self._clear_freeze_state()

    def freeze_status(self, now: datetime) -> dict[str, Any]:
        freeze = self.config.freeze_protection
        active = self._freeze_latched_speed is not None
        hold_remaining_s = 0.0
        if active and self._freeze_started_at is not None:
            run_for_s = max(0.0, (now - self._freeze_started_at).total_seconds())
            hold_remaining_s = max(0.0, freeze.min_run_seconds - run_for_s)

        return {
            "enabled": freeze.enabled,
            "active": active,
            "latched_speed": self._freeze_latched_speed.value if self._freeze_latched_speed else None,
            "started_at": self._freeze_started_at.isoformat() if self._freeze_started_at else None,
            "hold_remaining_s": hold_remaining_s,
            "observation": self._freeze_observation,
            "source": freeze.source.value,
            "threshold_unit": freeze.threshold_unit.value,
        }

    def check_command(
        self,
        command: ActuatorCommand,
        snapshot: SafetySnapshot,
    ) -> SafetyDecision:
        if self.active_fault is not None and command.requested_by != CommandSource.SYSTEM:
            return SafetyDecision(
                accepted=False,
                rejection_reason=f"safety lockout active: {self.active_fault.message}",
                metadata={
                    "fault_code": self.active_fault.code,
                    "severity": self.active_fault.severity.value,
                },
            )

        if (
            command.actuator_id == ActuatorId.CHLORINE_DOSING_PUMP
            and command.state == ActuatorState.ON
        ):
            allowed, reason = self._chlorine_conditions_met(snapshot)
            if not allowed:
                return SafetyDecision(accepted=False, rejection_reason=reason)

        if command.actuator_id == ActuatorId.BOOSTER_PUMP and command.state == ActuatorState.ON:
            if not self._pump_is_on(snapshot):
                return SafetyDecision(
                    accepted=False,
                    rejection_reason="booster pump cannot turn on unless pump motor is on",
                )

        return SafetyDecision(accepted=True)

    def evaluate(self, snapshot: SafetySnapshot) -> list[SafetyAction]:
        if self.active_fault is not None:
            return []

        actions: list[SafetyAction] = []
        pump_output_psi = snapshot.pressure_psi(self.config.pressure_sensors.pump_output)
        freeze_required_speed, freeze_observation = self._freeze_required_speed(snapshot)

        self._update_pump_high_tracking(snapshot, pump_output_psi)

        if (
            pump_output_psi is not None
            and pump_output_psi > self.config.pump_output_overpressure_psi
        ):
            fault = self._raise_fault(
                code="pump_output_overpressure",
                severity=SafetySeverity.ERROR,
                message=(
                    "pump output pressure exceeded "
                    f"{self.config.pump_output_overpressure_psi:g} psi"
                ),
                now=snapshot.now,
            )
            return self._shutdown_all_actions(snapshot.now, fault=fault)

        if self._pump_high_prime_timed_out(snapshot):
            fault = self._raise_fault(
                code="loss_of_prime",
                severity=SafetySeverity.WARNING,
                message=(
                    "pump ran at high speed without reaching "
                    f"{self.config.pump_high_prime_min_output_psi:g} psi output pressure"
                ),
                now=snapshot.now,
            )
            return self._shutdown_all_actions(snapshot.now, fault=fault)

        actions.extend(self._booster_actions(snapshot))
        actions.extend(self._chlorine_actions(snapshot))
        actions.extend(
            self._freeze_actions(
                snapshot,
                freeze_required_speed=freeze_required_speed,
                freeze_observation=freeze_observation,
            )
        )
        actions.extend(
            self._low_speed_prime_actions(
                snapshot,
                pump_output_psi,
                freeze_required_speed=freeze_required_speed,
            )
        )

        return actions

    def _pump_is_on(self, snapshot: SafetySnapshot) -> bool:
        return snapshot.actuator_state(ActuatorId.PUMP_MOTOR) == ActuatorState.ON

    def _pump_speed_is_high(self, snapshot: SafetySnapshot) -> bool:
        return snapshot.actuator_state(ActuatorId.PUMP_MOTOR_SPEED) == ActuatorState.HIGH

    def _pump_speed_is_low(self, snapshot: SafetySnapshot) -> bool:
        return snapshot.actuator_state(ActuatorId.PUMP_MOTOR_SPEED) == ActuatorState.LOW

    def _chlorine_conditions_met(self, snapshot: SafetySnapshot) -> tuple[bool, str | None]:
        if not self._pump_is_on(snapshot):
            return False, "chlorine output cannot turn on unless pump motor is on"

        if not self._pump_speed_is_high(snapshot):
            return False, "chlorine output cannot turn on unless pump speed is high"

        return_psi = snapshot.pressure_psi(self.config.pressure_sensors.return_line)
        if return_psi is None:
            return False, "chlorine output requires a good return pressure reading"

        if return_psi < self.config.chlorine_min_return_psi:
            return (
                False,
                "chlorine output requires return pressure "
                f">= {self.config.chlorine_min_return_psi:g} psi",
            )

        pump_output_psi = snapshot.pressure_psi(self.config.pressure_sensors.pump_output)
        if pump_output_psi is None:
            return False, "chlorine output requires a good pump output pressure reading"

        if pump_output_psi < self.config.chlorine_min_pump_output_psi:
            return (
                False,
                "chlorine output requires pump output pressure "
                f">= {self.config.chlorine_min_pump_output_psi:g} psi",
            )

        return True, None

    def _booster_actions(self, snapshot: SafetySnapshot) -> list[SafetyAction]:
        if snapshot.actuator_state(ActuatorId.BOOSTER_PUMP) != ActuatorState.ON:
            return []

        if not self._pump_is_on(snapshot):
            return [
                self._action(
                    snapshot.now,
                    ActuatorId.BOOSTER_PUMP,
                    ActuatorState.OFF,
                    reason_code="booster_requires_pump",
                    reason="booster pump shut off because pump motor is off",
                )
            ]

        booster_psi = snapshot.pressure_psi(self.config.pressure_sensors.booster)
        if booster_psi is None:
            return []

        if booster_psi > self.config.booster_max_psi:
            return [
                self._action(
                    snapshot.now,
                    ActuatorId.BOOSTER_PUMP,
                    ActuatorState.OFF,
                    reason_code="booster_overpressure",
                    reason=(
                        "booster pump shut off because booster pressure exceeded "
                        f"{self.config.booster_max_psi:g} psi"
                    ),
                )
            ]

        booster_on_for_s = (
            snapshot.now - snapshot.state_since(ActuatorId.BOOSTER_PUMP)
        ).total_seconds()

        if (
            booster_on_for_s > self.config.booster_low_pressure_grace_s
            and booster_psi < self.config.booster_min_psi
        ):
            return [
                self._action(
                    snapshot.now,
                    ActuatorId.BOOSTER_PUMP,
                    ActuatorState.OFF,
                    reason_code="booster_low_pressure_timeout",
                    reason=(
                        "booster pump shut off because booster pressure stayed below "
                        f"{self.config.booster_min_psi:g} psi after startup"
                    ),
                )
            ]

        return []

    def _chlorine_actions(self, snapshot: SafetySnapshot) -> list[SafetyAction]:
        if snapshot.actuator_state(ActuatorId.CHLORINE_DOSING_PUMP) != ActuatorState.ON:
            return []

        allowed, reason = self._chlorine_conditions_met(snapshot)
        if allowed:
            return []

        return [
            self._action(
                snapshot.now,
                ActuatorId.CHLORINE_DOSING_PUMP,
                ActuatorState.OFF,
                reason_code="chlorine_interlock_lost",
                reason=reason if reason is not None else "chlorine output interlock lost",
            )
        ]

    def _low_speed_prime_actions(
        self,
        snapshot: SafetySnapshot,
        pump_output_psi: float | None,
        *,
        freeze_required_speed: ActuatorState | None,
    ) -> list[SafetyAction]:
        if not self._pump_is_on(snapshot):
            self._low_pressure_prime_until = None
            return []

        if (
            self._pump_speed_is_low(snapshot)
            and pump_output_psi is not None
            and pump_output_psi < self.config.pump_low_prime_min_output_psi
        ):
            self._low_pressure_prime_until = snapshot.now + timedelta(
                seconds=self.config.pump_low_prime_seconds
            )
            return [
                self._action(
                    snapshot.now,
                    ActuatorId.PUMP_MOTOR_SPEED,
                    ActuatorState.HIGH,
                    reason_code="pump_low_speed_prime",
                    reason=(
                        "pump speed raised to high for priming because output pressure "
                        f"is below {self.config.pump_low_prime_min_output_psi:g} psi"
                    ),
                )
            ]

        if (
            self._low_pressure_prime_until is not None
            and snapshot.now >= self._low_pressure_prime_until
            and self._pump_speed_is_high(snapshot)
            and freeze_required_speed != ActuatorState.HIGH
        ):
            self._low_pressure_prime_until = None
            return [
                self._action(
                    snapshot.now,
                    ActuatorId.PUMP_MOTOR_SPEED,
                    ActuatorState.LOW,
                    reason_code="pump_low_speed_prime_complete",
                    reason="pump low-speed priming boost completed",
                )
            ]

        return []

    def _freeze_required_speed(
        self,
        snapshot: SafetySnapshot,
    ) -> tuple[ActuatorState | None, str | None]:
        freeze = self.config.freeze_protection
        if not freeze.enabled:
            self._clear_freeze_state()
            return None, None

        observation = self._freeze_observation_text(snapshot)
        if observation is None:
            self._freeze_observation = None
            return self._freeze_latched_speed, None

        observed_temp = observation[0]
        observed_at_text = observation[1]
        self._freeze_observation = observed_at_text

        now = snapshot.now
        if self._freeze_latched_speed is None:
            if observed_temp <= freeze.high_speed_on_below_temp:
                self._set_freeze_latch(ActuatorState.HIGH, now=now)
            elif observed_temp <= freeze.low_speed_on_below_temp:
                self._set_freeze_latch(ActuatorState.LOW, now=now)
            return self._freeze_latched_speed, observed_at_text

        if (
            self._freeze_latched_speed == ActuatorState.LOW
            and observed_temp <= freeze.high_speed_on_below_temp
        ):
            self._set_freeze_latch(ActuatorState.HIGH, now=now)

        if self._freeze_min_run_elapsed(now=now):
            if self._freeze_latched_speed == ActuatorState.HIGH:
                if observed_temp >= freeze.low_speed_off_above_temp:
                    self._clear_freeze_state()
                elif observed_temp > freeze.high_speed_off_above_temp:
                    self._set_freeze_latch(ActuatorState.LOW, now=now, preserve_start=True)
            elif self._freeze_latched_speed == ActuatorState.LOW:
                if observed_temp >= freeze.low_speed_off_above_temp:
                    self._clear_freeze_state()

        return self._freeze_latched_speed, observed_at_text

    def _freeze_observation_text(
        self,
        snapshot: SafetySnapshot,
    ) -> tuple[float, str] | None:
        freeze = self.config.freeze_protection
        candidates: list[tuple[str, float]] = []
        include_temp = freeze.source in (
            FreezeProtectionSource.TEMP,
            FreezeProtectionSource.BOTH,
        )
        include_ph_temp = freeze.source in (
            FreezeProtectionSource.PH_TEMP,
            FreezeProtectionSource.BOTH,
        )

        if include_temp:
            reading = self._freeze_temperature_reading(
                snapshot,
                sensor_id=freeze.temp_sensor,
                target_unit=freeze.threshold_unit,
            )
            if reading is not None:
                candidates.append((freeze.temp_sensor.value, reading))

        if include_ph_temp:
            reading = self._freeze_temperature_reading(
                snapshot,
                sensor_id=freeze.ph_temp_sensor,
                target_unit=freeze.threshold_unit,
            )
            if reading is not None:
                candidates.append((freeze.ph_temp_sensor.value, reading))

        if not candidates:
            return None

        observed_sensor, observed_temp = min(candidates, key=lambda item: item[1])
        observation = f"{observed_temp:.1f} {freeze.threshold_unit.value} ({observed_sensor})"
        return observed_temp, observation

    def _freeze_temperature_reading(
        self,
        snapshot: SafetySnapshot,
        *,
        sensor_id: SensorId,
        target_unit: TemperatureUnit,
    ) -> float | None:
        measurement = snapshot.raw_measurement(sensor_id)
        if measurement is None:
            return None

        if measurement.unit not in {TemperatureUnit.DEG_F.value, TemperatureUnit.DEG_C.value}:
            return None

        source_unit = TemperatureUnit(measurement.unit)
        return _convert_temperature(
            measurement.value,
            source_unit=source_unit,
            target_unit=target_unit,
        )

    def _freeze_actions(
        self,
        snapshot: SafetySnapshot,
        *,
        freeze_required_speed: ActuatorState | None,
        freeze_observation: str | None,
    ) -> list[SafetyAction]:
        if freeze_required_speed is None:
            return []

        reason_code = (
            "freeze_protection_high"
            if freeze_required_speed == ActuatorState.HIGH
            else "freeze_protection_low"
        )
        reason = (
            f"freeze protection forcing pump {freeze_required_speed.value} speed "
            f"({freeze_observation})"
            if freeze_observation is not None
            else f"freeze protection forcing pump {freeze_required_speed.value} speed"
        )

        actions: list[SafetyAction] = []
        pump_on = self._pump_is_on(snapshot)
        pump_speed = snapshot.actuator_state(ActuatorId.PUMP_MOTOR_SPEED)

        if not pump_on:
            if pump_speed != freeze_required_speed:
                actions.append(
                    self._action(
                        snapshot.now,
                        ActuatorId.PUMP_MOTOR_SPEED,
                        freeze_required_speed,
                        reason_code=reason_code,
                        reason=reason,
                    )
                )
            actions.append(
                self._action(
                    snapshot.now,
                    ActuatorId.PUMP_MOTOR,
                    ActuatorState.ON,
                    reason_code=reason_code,
                    reason=reason,
                )
            )
            return actions

        if freeze_required_speed == ActuatorState.HIGH:
            if pump_speed != ActuatorState.HIGH:
                actions.append(
                    self._action(
                        snapshot.now,
                        ActuatorId.PUMP_MOTOR_SPEED,
                        ActuatorState.HIGH,
                        reason_code=reason_code,
                        reason=reason,
                    )
                )
            return actions

        if pump_speed == ActuatorState.HIGH and not self._prime_high_hold_active(snapshot.now):
            actions.append(
                self._action(
                    snapshot.now,
                    ActuatorId.PUMP_MOTOR_SPEED,
                    ActuatorState.LOW,
                    reason_code=reason_code,
                    reason=reason,
                )
            )
            return actions

        if pump_speed not in (ActuatorState.LOW, ActuatorState.HIGH):
            actions.append(
                self._action(
                    snapshot.now,
                    ActuatorId.PUMP_MOTOR_SPEED,
                    ActuatorState.LOW,
                    reason_code=reason_code,
                    reason=reason,
                )
            )

        return actions

    def _prime_high_hold_active(self, now: datetime) -> bool:
        return self._low_pressure_prime_until is not None and now < self._low_pressure_prime_until

    def _freeze_min_run_elapsed(self, *, now: datetime) -> bool:
        if self._freeze_latched_speed is None or self._freeze_started_at is None:
            return True
        run_for_s = max(0.0, (now - self._freeze_started_at).total_seconds())
        return run_for_s >= self.config.freeze_protection.min_run_seconds

    def _set_freeze_latch(
        self,
        speed: ActuatorState,
        *,
        now: datetime,
        preserve_start: bool = False,
    ) -> None:
        if speed not in (ActuatorState.LOW, ActuatorState.HIGH):
            raise ValueError("freeze latch speed must be low or high")
        self._freeze_latched_speed = speed
        if self._freeze_started_at is None or not preserve_start:
            self._freeze_started_at = now

    def _clear_freeze_state(self) -> None:
        self._freeze_latched_speed = None
        self._freeze_started_at = None
        self._freeze_observation = None

    def _update_pump_high_tracking(
        self,
        snapshot: SafetySnapshot,
        pump_output_psi: float | None,
    ) -> None:
        if not (self._pump_is_on(snapshot) and self._pump_speed_is_high(snapshot)):
            self._pump_high_started_at = None
            self._pump_high_observed_pressure = False
            self._pump_high_reached_min_output = False
            return

        high_started_at = max(
            snapshot.state_since(ActuatorId.PUMP_MOTOR),
            snapshot.state_since(ActuatorId.PUMP_MOTOR_SPEED),
        )

        if self._pump_high_started_at != high_started_at:
            self._pump_high_started_at = high_started_at
            self._pump_high_observed_pressure = False
            self._pump_high_reached_min_output = False

        if pump_output_psi is not None:
            self._pump_high_observed_pressure = True

            if pump_output_psi > self.config.pump_high_prime_min_output_psi:
                self._pump_high_reached_min_output = True

    def _pump_high_prime_timed_out(self, snapshot: SafetySnapshot) -> bool:
        if self._pump_high_started_at is None:
            return False

        if not self._pump_high_observed_pressure:
            return False

        if self._pump_high_reached_min_output:
            return False

        high_for_s = (snapshot.now - self._pump_high_started_at).total_seconds()

        return high_for_s > self.config.pump_high_prime_timeout_s

    def _raise_fault(
        self,
        *,
        code: str,
        severity: SafetySeverity,
        message: str,
        now: datetime,
    ) -> SafetyFault:
        fault = SafetyFault(
            code=code,
            severity=severity,
            message=message,
            raised_at=now,
        )
        self.active_fault = fault
        self._low_pressure_prime_until = None
        self._clear_freeze_state()
        return fault

    def _shutdown_all_actions(self, now: datetime, *, fault: SafetyFault) -> list[SafetyAction]:
        return [
            self._action(
                now,
                ActuatorId.CHLORINE_DOSING_PUMP,
                ActuatorState.OFF,
                reason_code=fault.code,
                reason=fault.message,
                fault=fault,
            ),
            self._action(
                now,
                ActuatorId.BOOSTER_PUMP,
                ActuatorState.OFF,
                reason_code=fault.code,
                reason=fault.message,
                fault=fault,
            ),
            self._action(
                now,
                ActuatorId.PUMP_MOTOR,
                ActuatorState.OFF,
                reason_code=fault.code,
                reason=fault.message,
                fault=fault,
            ),
            self._action(
                now,
                ActuatorId.PUMP_MOTOR_SPEED,
                ActuatorState.LOW,
                reason_code=fault.code,
                reason=fault.message,
                fault=fault,
            ),
        ]

    def _action(
        self,
        now: datetime,
        actuator_id: ActuatorId,
        state: ActuatorState,
        *,
        reason_code: str,
        reason: str,
        fault: SafetyFault | None = None,
    ) -> SafetyAction:
        return SafetyAction(
            command=ActuatorCommand(
                actuator_id=actuator_id,
                created_at=now,
                state=state,
                requested_by=CommandSource.SYSTEM,
                reason=reason,
                metadata={"safety_action": reason_code},
            ),
            reason_code=reason_code,
            fault=fault,
        )


def latest_measurements_by_sensor(
    measurements: Iterable[Measurement],
) -> dict[SensorId, Measurement]:
    return {measurement.sensor_id: measurement for measurement in measurements}


def load_safety_config(path: str | Path) -> SafetyConfig:
    with Path(path).open("r", encoding="utf-8") as config_file:
        data = yaml.safe_load(config_file) or {}

    if not isinstance(data, Mapping):
        raise ValueError("safety config file must contain a mapping")

    return SafetyConfig.from_mapping(data)


def _mapping_value(
    data: Mapping[str, Any],
    key: str,
    *,
    default: Mapping[str, Any],
) -> Mapping[str, Any]:
    value = data.get(key, default)

    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be a mapping")

    return value


def _float_value(data: Mapping[str, Any], key: str, default: float) -> float:
    value = data.get(key, default)

    if not isinstance(value, int | float):
        raise ValueError(f"{key} must be a number")

    return float(value)


def _float_alias_value(
    data: Mapping[str, Any],
    *,
    key: str,
    aliases: tuple[str, ...],
    default: float,
) -> float:
    if key in data:
        return _float_value(data, key, default)
    for alias in aliases:
        if alias in data:
            return _float_value(data, alias, default)
    return float(default)


def _bool_value(data: Mapping[str, Any], key: str, default: bool) -> bool:
    value = data.get(key, default)

    if not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false")

    return value


def _sensor_id_value(
    data: Mapping[str, Any],
    key: str,
    default: SensorId,
) -> SensorId:
    value = data.get(key, default.value)

    if not isinstance(value, str):
        raise ValueError(f"{key} must be a sensor ID string")

    return SensorId(value)


def _freeze_source_value(
    data: Mapping[str, Any],
    key: str,
    default: FreezeProtectionSource,
) -> FreezeProtectionSource:
    value = data.get(key, default.value)

    if not isinstance(value, str):
        raise ValueError(f"{key} must be one of: temp, ph_temp, both")

    return FreezeProtectionSource(value)


def _temperature_unit_value(
    data: Mapping[str, Any],
    key: str,
    default: TemperatureUnit,
) -> TemperatureUnit:
    value = data.get(key, default.value)

    if not isinstance(value, str):
        raise ValueError(f"{key} must be degF or degC")

    return TemperatureUnit(value)


def _convert_temperature(
    value: float,
    *,
    source_unit: TemperatureUnit,
    target_unit: TemperatureUnit,
) -> float:
    if source_unit == target_unit:
        return value

    if source_unit == TemperatureUnit.DEG_C and target_unit == TemperatureUnit.DEG_F:
        return (value * 9.0 / 5.0) + 32.0

    if source_unit == TemperatureUnit.DEG_F and target_unit == TemperatureUnit.DEG_C:
        return (value - 32.0) * 5.0 / 9.0

    raise ValueError(f"unsupported temperature conversion: {source_unit.value}->{target_unit.value}")
