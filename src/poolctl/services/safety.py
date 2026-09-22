"""
Safety interlocks and lockouts for pool equipment.

The safety gate enforces pressure, booster, chlorinator, priming, and freeze
protection rules before actuator commands reach hardware. Lockout faults remain
active until explicitly cleared so a transient dangerous condition cannot be
ignored by the next scheduler tick.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
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
from poolctl.services.measurement_quality import usable_numeric_measurement_value
from poolctl.services.water_temperature import (
    WaterTemperatureConfig,
    WaterTemperatureSelection,
    select_water_temperature,
)


class SafetySeverity(str, Enum):
    """
    Severity for safety faults that place the system into lockout.
    """

    WARNING = "warning"
    ERROR = "error"


class TemperatureUnit(str, Enum):
    DEG_F = "degF"
    DEG_C = "degC"


@dataclass(frozen=True)
class PressureSensorConfig:
    """
    Sensor IDs used by safety rules that depend on pressure readings.

    Keeping these configurable lets the Pi deployment map safety logic to the
    actual pressure transducer channel without changing controller code.
    """

    pump_output: SensorId = SensorId.PUMP_OUTPUT_PSI


@dataclass(frozen=True)
class FreezeProtectionConfig:
    """
    Freeze protection settings.

    PH probe temperature is preferred, with ORP probe temperature as fallback.
    Fresh GOOD or SUSPECT values are usable; BAD, missing, non-finite, and stale
    readings trigger fail-safe freeze protection when neither source is usable.
    """

    enabled: bool = False
    primary_temperature_sensor: SensorId = SensorId.PH_TEMP
    fallback_temperature_sensor: SensorId = SensorId.ORP_TEMP
    max_temperature_age_seconds: float = 3600.0
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
        if self.max_temperature_age_seconds < 0:
            raise ValueError("freeze max_temperature_age_seconds must be >= 0")
        if self.primary_temperature_sensor == self.fallback_temperature_sensor:
            raise ValueError("freeze primary and fallback temperature sensors must differ")
        allowed_temperature_sensors = {SensorId.PH_TEMP, SensorId.ORP_TEMP}
        if (
            self.primary_temperature_sensor not in allowed_temperature_sensors
            or self.fallback_temperature_sensor not in allowed_temperature_sensors
        ):
            raise ValueError("freeze temperature sensors must be ph_temp or orp_temp")

    @property
    def water_temperature_config(self) -> WaterTemperatureConfig:
        return WaterTemperatureConfig(
            primary_sensor=self.primary_temperature_sensor,
            fallback_sensor=self.fallback_temperature_sensor,
            max_age_seconds=self.max_temperature_age_seconds,
        )


@dataclass(frozen=True)
class ChlorineTankSafetyConfig:
    """
    Safety thresholds for the liquid-chlorine storage tank estimate.

    Hysteresis avoids chattering around the inhibit threshold: once normal
    dosing is inhibited, the tank must recover to the re-enable threshold before
    dosing can resume.
    """

    level_sensor: SensorId = SensorId.CHLORINE_TANK_LEVEL_GAL
    low_warning_gal: float = 2.0
    inhibit_below_gal: float = 1.5
    reenable_at_gal: float = 2.0
    forecast_reserve_gal: float = 2.0

    def __post_init__(self) -> None:
        if self.low_warning_gal < 0:
            raise ValueError("chlorine_tank.low_warning_gal must be >= 0")
        if self.inhibit_below_gal < 0:
            raise ValueError("chlorine_tank.inhibit_below_gal must be >= 0")
        if self.reenable_at_gal < 0:
            raise ValueError("chlorine_tank.reenable_at_gal must be >= 0")
        if self.forecast_reserve_gal < 0:
            raise ValueError("chlorine_tank.forecast_reserve_gal must be >= 0")
        if self.inhibit_below_gal > self.reenable_at_gal:
            raise ValueError(
                "chlorine_tank.inhibit_below_gal must be <= reenable_at_gal"
            )


@dataclass(frozen=True)
class SafetyConfig:
    """
    Configurable safety thresholds and timers.
    """

    pressure_sensors: PressureSensorConfig = field(default_factory=PressureSensorConfig)
    freeze_protection: FreezeProtectionConfig = field(default_factory=FreezeProtectionConfig)
    chlorine_tank: ChlorineTankSafetyConfig = field(default_factory=ChlorineTankSafetyConfig)

    chlorine_min_pump_output_psi: float = 3.0
    chlorine_max_pump_output_psi: float = 3.5

    pump_prime_min_output_psi: float = 1.0
    pump_prime_timeout_s: float = 30.0
    pump_output_max_age_seconds: float = 10.0
    pump_output_overpressure_psi: float = 30.0

    def __post_init__(self) -> None:
        if self.chlorine_min_pump_output_psi < 0:
            raise ValueError("chlorine_min_pump_output_psi must be >= 0")
        if self.chlorine_max_pump_output_psi <= self.chlorine_min_pump_output_psi:
            raise ValueError(
                "chlorine_max_pump_output_psi must be greater than chlorine_min_pump_output_psi"
            )
        if self.pump_prime_min_output_psi < 0:
            raise ValueError("pump_prime_min_output_psi must be >= 0")
        if self.pump_prime_timeout_s < 0:
            raise ValueError("pump_prime_timeout_s must be >= 0")
        if self.pump_output_max_age_seconds < 0:
            raise ValueError("pump_output_max_age_seconds must be >= 0")
        if self.pump_output_overpressure_psi <= 0:
            raise ValueError("pump_output_overpressure_psi must be > 0")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> SafetyConfig:
        safety_data = _mapping_value(data, "safety", default=data)
        pressure_data = _mapping_value(safety_data, "pressure_sensor_ids", default={})
        threshold_data = _mapping_value(safety_data, "thresholds", default={})
        timeout_data = _mapping_value(safety_data, "timeouts", default={})
        freeze_data = _mapping_value(safety_data, "freeze_protection", default={})
        chlorine_tank_data = _mapping_value(safety_data, "chlorine_tank", default={})

        pressure_sensors = PressureSensorConfig(
            pump_output=_sensor_id_value(
                pressure_data,
                "pump_output",
                PressureSensorConfig().pump_output,
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
                primary_temperature_sensor=_sensor_id_value(
                    freeze_data,
                    "primary_temperature_sensor",
                    FreezeProtectionConfig().primary_temperature_sensor,
                ),
                fallback_temperature_sensor=_sensor_id_value(
                    freeze_data,
                    "fallback_temperature_sensor",
                    FreezeProtectionConfig().fallback_temperature_sensor,
                ),
                max_temperature_age_seconds=_float_value(
                    freeze_data,
                    "max_temperature_age_seconds",
                    FreezeProtectionConfig.max_temperature_age_seconds,
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
            chlorine_tank=ChlorineTankSafetyConfig(
                level_sensor=_sensor_id_value(
                    chlorine_tank_data,
                    "level_sensor",
                    ChlorineTankSafetyConfig().level_sensor,
                ),
                low_warning_gal=_float_value(
                    chlorine_tank_data,
                    "low_warning_gal",
                    ChlorineTankSafetyConfig.low_warning_gal,
                ),
                inhibit_below_gal=_float_value(
                    chlorine_tank_data,
                    "inhibit_below_gal",
                    ChlorineTankSafetyConfig.inhibit_below_gal,
                ),
                reenable_at_gal=_float_value(
                    chlorine_tank_data,
                    "reenable_at_gal",
                    ChlorineTankSafetyConfig.reenable_at_gal,
                ),
                forecast_reserve_gal=_float_value(
                    chlorine_tank_data,
                    "forecast_reserve_gal",
                    ChlorineTankSafetyConfig.forecast_reserve_gal,
                ),
            ),
            chlorine_min_pump_output_psi=_float_value(
                threshold_data,
                "chlorine_min_pump_output_psi",
                cls.chlorine_min_pump_output_psi,
            ),
            chlorine_max_pump_output_psi=_float_value(
                threshold_data,
                "chlorine_max_pump_output_psi",
                cls.chlorine_max_pump_output_psi,
            ),
            pump_prime_min_output_psi=_float_value(
                threshold_data,
                "pump_prime_min_output_psi",
                cls.pump_prime_min_output_psi,
            ),
            pump_prime_timeout_s=_float_value(
                timeout_data,
                "pump_prime_timeout_s",
                cls.pump_prime_timeout_s,
            ),
            pump_output_max_age_seconds=_float_value(
                timeout_data,
                "pump_output_max_age_seconds",
                cls.pump_output_max_age_seconds,
            ),
            pump_output_overpressure_psi=_float_value(
                threshold_data,
                "pump_output_overpressure_psi",
                cls.pump_output_overpressure_psi,
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

    def fresh_pressure_psi(
        self,
        sensor_id: SensorId,
        *,
        max_age_seconds: float,
    ) -> float | None:
        return usable_numeric_measurement_value(
            self.measurements.get(sensor_id),
            now=self.now,
            max_age_seconds=max_age_seconds,
        )

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

    def __init__(
        self,
        config: SafetyConfig | None = None,
        *,
        chlorine_pump_stabilization_seconds: float = 60.0,
    ) -> None:
        self.config = config if config is not None else SafetyConfig()
        self.chlorine_pump_stabilization_seconds = max(
            0.0,
            chlorine_pump_stabilization_seconds,
        )
        self.active_fault: SafetyFault | None = None

        # Prime monitoring and freeze protection are latches. A latch lets the
        # gate keep requesting the same safe state across many ticks.
        self._pump_prime_below_started_at: datetime | None = None
        self._freeze_latched_speed: ActuatorState | None = None
        self._freeze_started_at: datetime | None = None
        self._freeze_observation: str | None = None
        self._freeze_fail_safe = False
        self._freeze_fail_safe_reason: str | None = None
        self._water_temperature_selection: WaterTemperatureSelection | None = None
        self._chlorine_tank_hysteresis_inhibited = False
        self._chlorine_tank_status: dict[str, Any] = (
            self._chlorine_tank_status_payload(
                tank_level_gal=None,
                low_warning_active=False,
                dosing_inhibited=True,
                inhibit_reason="chlorine tank level unavailable",
            )
        )

    @property
    def locked_out(self) -> bool:
        return self.active_fault is not None

    def clear_fault(self) -> None:
        self.active_fault = None
        self._pump_prime_below_started_at = None
        self._clear_freeze_state()

    def apply_config(self, config: SafetyConfig) -> None:
        """
        Replace safety settings while preserving active safety latches.
        """
        self.config = config
        self._water_temperature_selection = None

    def set_chlorine_pump_stabilization_seconds(self, value: float) -> None:
        if value < 0:
            raise ValueError("chlorine pump stabilization seconds must be >= 0")
        self.chlorine_pump_stabilization_seconds = float(value)

    def freeze_status(self, now: datetime) -> dict[str, Any]:
        freeze = self.config.freeze_protection
        selection = self._water_temperature_selection or select_water_temperature(
            {},
            now=now,
            config=freeze.water_temperature_config,
        )
        active = self._freeze_latched_speed is not None
        hold_remaining_s = 0.0
        if active and self._freeze_started_at is not None:
            run_for_s = max(0.0, (now - self._freeze_started_at).total_seconds())
            hold_remaining_s = max(0.0, freeze.min_run_seconds - run_for_s)

        selection_payload = selection.as_payload()
        return {
            "enabled": freeze.enabled,
            "active": active,
            "latched_speed": self._freeze_latched_speed.value if self._freeze_latched_speed else None,
            "started_at": self._freeze_started_at.isoformat() if self._freeze_started_at else None,
            "hold_remaining_s": hold_remaining_s,
            "observation": self._freeze_observation,
            **selection_payload,
            "primary_stale_or_unavailable": not selection.primary.available,
            "fallback_stale_or_unavailable": not selection.fallback.available,
            "fail_safe": self._freeze_fail_safe,
            "fail_safe_reason": self._freeze_fail_safe_reason,
            "threshold_unit": freeze.threshold_unit.value,
        }

    def chlorine_tank_status(self) -> dict[str, Any]:
        return dict(self._chlorine_tank_status)

    def check_chlorine_dosing(self, snapshot: SafetySnapshot) -> SafetyDecision:
        """Evaluate the same normal chlorine eligibility policy used by commands."""
        return self._chlorine_conditions_met(snapshot)

    def check_command(
        self,
        command: ActuatorCommand,
        snapshot: SafetySnapshot,
    ) -> SafetyDecision:
        if self.active_fault is not None and command.requested_by != CommandSource.SYSTEM:
            # Human, timer, GUI, and controller commands are rejected while
            # locked out. SYSTEM commands are still allowed so the gate can shut
            # actuators down.
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
            decision = self.check_chlorine_dosing(snapshot)
            if not decision.accepted:
                return decision

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
        self._update_chlorine_tank_status(snapshot)
        pump_output_psi = snapshot.fresh_pressure_psi(
            self.config.pressure_sensors.pump_output,
            max_age_seconds=self.config.pump_output_max_age_seconds,
        )
        freeze_required_speed, freeze_observation = self._freeze_required_speed(snapshot)

        # Update timers/latches before checking lockouts so the current pressure
        # reading participates in prime-timeout decisions.
        self._update_pump_prime_tracking(snapshot, pump_output_psi)

        if (
            pump_output_psi is not None
            and pump_output_psi > self.config.pump_output_overpressure_psi
        ):
            # Overpressure is an immediate hard lockout. All outputs are shut
            # down and future non-system commands are rejected until cleared.
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

        if self._pump_prime_timed_out(snapshot):
            # Loss of prime is a lockout because continuing to run dry can damage
            # the pump. The operator must inspect and clear it explicitly.
            fault = self._raise_fault(
                code="loss_of_prime",
                severity=SafetySeverity.WARNING,
                message=(
                    "pump ran without reaching "
                    f"{self.config.pump_prime_min_output_psi:g} psi output pressure"
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

        return actions

    def _pump_is_on(self, snapshot: SafetySnapshot) -> bool:
        return snapshot.actuator_state(ActuatorId.PUMP_MOTOR) == ActuatorState.ON

    def _pump_speed_is_high(self, snapshot: SafetySnapshot) -> bool:
        return snapshot.actuator_state(ActuatorId.PUMP_MOTOR_SPEED) == ActuatorState.HIGH

    def _chlorine_conditions_met(self, snapshot: SafetySnapshot) -> SafetyDecision:
        if not self._pump_is_on(snapshot):
            return SafetyDecision(
                accepted=False,
                rejection_reason="chlorine output cannot turn on unless pump motor is on",
            )

        pump_on_for_s = max(
            0.0,
            (snapshot.now - snapshot.state_since(ActuatorId.PUMP_MOTOR)).total_seconds(),
        )
        if pump_on_for_s < self.chlorine_pump_stabilization_seconds:
            return SafetyDecision(
                accepted=False,
                rejection_reason=(
                    "chlorine output waiting for pump/pressure stabilization "
                    f"({pump_on_for_s:.1f}s of "
                    f"{self.chlorine_pump_stabilization_seconds:.1f}s)"
                ),
                metadata={
                    "pump_on_for_s": max(0.0, pump_on_for_s),
                    "required_pump_on_s": self.chlorine_pump_stabilization_seconds,
                },
            )

        pump_output_psi = snapshot.fresh_pressure_psi(
            self.config.pressure_sensors.pump_output,
            max_age_seconds=self.config.pump_output_max_age_seconds,
        )
        if pump_output_psi is None:
            return SafetyDecision(
                accepted=False,
                rejection_reason="chlorine output requires a fresh good pump output pressure reading",
            )

        if pump_output_psi < self.config.chlorine_min_pump_output_psi:
            return SafetyDecision(
                accepted=False,
                rejection_reason=(
                    "chlorine output requires pump output pressure "
                    f">= {self.config.chlorine_min_pump_output_psi:g} psi"
                ),
            )

        if pump_output_psi > self.config.chlorine_max_pump_output_psi:
            return SafetyDecision(
                accepted=False,
                rejection_reason=(
                    "chlorine output requires pump output pressure "
                    f"<= {self.config.chlorine_max_pump_output_psi:g} psi"
                ),
            )

        tank_decision = self._chlorine_tank_conditions_met(snapshot)
        if not tank_decision.accepted:
            return tank_decision

        return SafetyDecision(accepted=True)

    def _chlorine_tank_conditions_met(self, snapshot: SafetySnapshot) -> SafetyDecision:
        status = self._update_chlorine_tank_status(snapshot)
        if not status["dosing_inhibited"]:
            return SafetyDecision(accepted=True)

        reason = status["inhibit_reason"] or "chlorine tank dosing inhibited"
        return SafetyDecision(
            accepted=False,
            rejection_reason=reason,
            metadata={"chlorine_tank": status},
        )

    def _update_chlorine_tank_status(self, snapshot: SafetySnapshot) -> dict[str, Any]:
        tank = self.config.chlorine_tank
        measurement = snapshot.raw_measurement(tank.level_sensor)
        tank_level_gal: float | None = None
        if measurement is not None and measurement.quality == Quality.GOOD:
            try:
                tank_level_gal = float(measurement.value)
            except (TypeError, ValueError):
                tank_level_gal = None

        if tank_level_gal is None or not math.isfinite(tank_level_gal):
            status = self._chlorine_tank_status_payload(
                tank_level_gal=None,
                low_warning_active=False,
                dosing_inhibited=True,
                inhibit_reason="chlorine tank level unavailable",
            )
            self._chlorine_tank_status = status
            return status

        tank_level_gal = max(0.0, tank_level_gal)
        if tank_level_gal <= tank.inhibit_below_gal:
            self._chlorine_tank_hysteresis_inhibited = True
        elif (
            self._chlorine_tank_hysteresis_inhibited
            and tank_level_gal >= tank.reenable_at_gal
        ):
            self._chlorine_tank_hysteresis_inhibited = False

        inhibit_reason = None
        if self._chlorine_tank_hysteresis_inhibited:
            if tank_level_gal <= tank.inhibit_below_gal:
                inhibit_reason = (
                    "chlorine tank level "
                    f"<= {tank.inhibit_below_gal:g} gal dosing inhibit threshold"
                )
            else:
                inhibit_reason = (
                    "chlorine tank refill required until level "
                    f">= {tank.reenable_at_gal:g} gal"
                )

        status = self._chlorine_tank_status_payload(
            tank_level_gal=tank_level_gal,
            low_warning_active=tank_level_gal <= tank.low_warning_gal,
            dosing_inhibited=self._chlorine_tank_hysteresis_inhibited,
            inhibit_reason=inhibit_reason,
        )
        self._chlorine_tank_status = status
        return status

    def _chlorine_tank_status_payload(
        self,
        *,
        tank_level_gal: float | None,
        low_warning_active: bool,
        dosing_inhibited: bool,
        inhibit_reason: str | None,
    ) -> dict[str, Any]:
        tank = self.config.chlorine_tank
        return {
            "level_sensor": tank.level_sensor.value,
            "tank_level_gal": (
                round(tank_level_gal, 4) if tank_level_gal is not None else None
            ),
            "available": tank_level_gal is not None,
            "low_warning_active": low_warning_active,
            "dosing_inhibited": dosing_inhibited,
            "inhibit_reason": inhibit_reason,
            "low_warning_threshold_gal": tank.low_warning_gal,
            "inhibit_threshold_gal": tank.inhibit_below_gal,
            "reenable_threshold_gal": tank.reenable_at_gal,
        }

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

        return []

    def _chlorine_actions(self, snapshot: SafetySnapshot) -> list[SafetyAction]:
        if snapshot.actuator_state(ActuatorId.CHLORINE_DOSING_PUMP) != ActuatorState.ON:
            return []

        decision = self._chlorine_conditions_met(snapshot)
        if decision.accepted:
            return []

        return [
            self._action(
                snapshot.now,
                ActuatorId.CHLORINE_DOSING_PUMP,
                ActuatorState.OFF,
                reason_code="chlorine_interlock_lost",
                reason=(
                    decision.rejection_reason
                    if decision.rejection_reason is not None
                    else "chlorine output interlock lost"
                ),
                metadata=decision.metadata,
            )
        ]

    def _freeze_required_speed(
        self,
        snapshot: SafetySnapshot,
    ) -> tuple[ActuatorState | None, str | None]:
        freeze = self.config.freeze_protection
        selection = select_water_temperature(
            snapshot.measurements,
            now=snapshot.now,
            config=freeze.water_temperature_config,
        )
        self._water_temperature_selection = selection
        if not freeze.enabled:
            self._clear_freeze_state()
            return None, None

        if not selection.available:
            self._freeze_fail_safe = True
            self._freeze_fail_safe_reason = (
                "Freeze protection temperature unavailable; using fail-safe freeze protection."
            )
            self._freeze_observation = "temperature unavailable"
            if self._freeze_latched_speed is None:
                self._set_freeze_latch(ActuatorState.LOW, now=snapshot.now)
            return self._freeze_latched_speed, self._freeze_fail_safe_reason

        assert selection.active_value is not None
        assert selection.active_unit is not None
        assert selection.active_source is not None
        source_unit = TemperatureUnit(selection.active_unit)
        observed_temp = _convert_temperature(
            selection.active_value,
            source_unit=source_unit,
            target_unit=freeze.threshold_unit,
        )
        observed_at_text = (
            f"{observed_temp:.1f} {freeze.threshold_unit.value} "
            f"({selection.active_source.value})"
        )
        self._freeze_fail_safe = False
        self._freeze_fail_safe_reason = None
        self._freeze_observation = observed_at_text

        now = snapshot.now
        if self._freeze_latched_speed is None:
            # Enter freeze mode only when crossing the ON thresholds.
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
            # Hysteresis uses separate OFF thresholds and a minimum runtime so
            # the pump does not rapidly cycle around the freeze setpoint.
            if self._freeze_latched_speed == ActuatorState.HIGH:
                if observed_temp >= freeze.low_speed_off_above_temp:
                    self._clear_freeze_state()
                elif observed_temp > freeze.high_speed_off_above_temp:
                    self._set_freeze_latch(ActuatorState.LOW, now=now, preserve_start=True)
            elif self._freeze_latched_speed == ActuatorState.LOW:
                if observed_temp >= freeze.low_speed_off_above_temp:
                    self._clear_freeze_state()

        return self._freeze_latched_speed, observed_at_text

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
            # Set speed before turning the pump on so the motor starts in the
            # required freeze-protection speed.
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

        if pump_speed == ActuatorState.HIGH:
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
        self._freeze_fail_safe = False
        self._freeze_fail_safe_reason = None

    def _update_pump_prime_tracking(
        self,
        snapshot: SafetySnapshot,
        pump_output_psi: float | None,
    ) -> None:
        if not self._pump_is_on(snapshot):
            self._pump_prime_below_started_at = None
            return

        if pump_output_psi is None:
            if self._pump_prime_below_started_at is None:
                self._pump_prime_below_started_at = snapshot.now
            return

        if pump_output_psi >= self.config.pump_prime_min_output_psi:
            self._pump_prime_below_started_at = None
            return

        if self._pump_prime_below_started_at is None:
            self._pump_prime_below_started_at = snapshot.now

    def _pump_prime_timed_out(self, snapshot: SafetySnapshot) -> bool:
        if self._pump_prime_below_started_at is None:
            return False

        low_for_s = (
            snapshot.now - self._pump_prime_below_started_at
        ).total_seconds()

        return low_for_s > self.config.pump_prime_timeout_s

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

        # A lockout supersedes softer latches. Clear them so recovery starts from
        # a known state after the operator clears the fault.
        self._pump_prime_below_started_at = None
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
        metadata: Mapping[str, Any] | None = None,
    ) -> SafetyAction:
        return SafetyAction(
            command=ActuatorCommand(
                actuator_id=actuator_id,
                created_at=now,
                state=state,
                requested_by=CommandSource.SYSTEM,
                reason=reason,
                metadata={"safety_action": reason_code, **dict(metadata or {})},
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
