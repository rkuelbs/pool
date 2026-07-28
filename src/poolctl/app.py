"""
Build and run the pool controller application.

This module is the composition root for the project. It reads configuration,
chooses simulated or Raspberry Pi drivers, wires the services together, and
executes one controller "tick" at a time. A tick is one pass through timer
control, chlorination, acquisition, safety, logging, MQTT, and notifications.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from poolctl.config import DriverProfile, FeatureLayer, LiveViewConfig, RuntimeConfig
from poolctl.config_files import load_config_with_overrides
from poolctl.domain.models import (
    ACTUATOR_AUTO_OFF_AT_METADATA,
    ACTUATOR_ON_PULSE_SECONDS_METADATA,
    ActuatorCommandResult,
    ActuatorCommand,
    ActuatorId,
    ActuatorState,
    ActuatorStateSample,
    ChemicalType,
    CommandSource,
    LabTest,
    Measurement,
    MeasurementKind,
    Quality,
    SensorId,
)
from poolctl.drivers.base import ActuatorDriver, MultiSensorDriver, SensorDriver
from poolctl.drivers.modbus.rtu_bus import ModbusRtuBusRegistry
from poolctl.drivers.raspberrypi.actuators import build_raspberrypi_actuators_from_mapping
from poolctl.drivers.raspberrypi.sensors import (
    build_raspberrypi_sensor_drivers_from_mapping,
    build_raspberrypi_sensors_from_mapping,
)
from poolctl.drivers.simulated.actuators import build_default_simulated_actuators
from poolctl.drivers.simulated.plant import SimulatedPlant
from poolctl.drivers.simulated.sensors import build_default_simulated_sensors
from poolctl.services.acquisition import (
    AcquisitionConfig,
    AcquisitionResult,
    AcquisitionService,
)
from poolctl.services.clock import Clock, RealClock, SimulatedClock
from poolctl.services.command_router import CommandRouter
from poolctl.services.chlorination import (
    ChlorinationConfig,
    ChlorinationController,
    ChlorinationPlanAdjustment,
    ChlorinationStatus,
)
from poolctl.services.fc_demand import (
    FcDemandConfig,
    FcDemandPlan,
    FcDemandStatus,
    FcTestPoint,
    estimate_fc_demand_plan,
)
from poolctl.services.measurement_logging import (
    MeasurementLogger,
    MeasurementLoggingConfig,
    ValueSummary,
)
from poolctl.services.flow_estimation import (
    FlowEstimates,
    FlowEstimationConfig,
    estimate_flows,
)
from poolctl.services.mqtt import MqttBridge, MqttBridgeConfig
from poolctl.services.notifications import (
    NotificationMessage,
    NotificationResult,
    NotificationService,
    NotificationsConfig,
)
from poolctl.services.pump_timer import PumpTimer, PumpTimerConfig
from poolctl.services.pump_timer import PumpTimerOverride
from poolctl.services.pulse_timing import quantize_relay_flash_seconds
from poolctl.services.saturation_index import (
    CalciumSaturationIndexConfig,
    estimate_calcium_saturation_index,
)
from poolctl.services.safety import SafetyConfig, SafetyGate
from poolctl.services.weather import WeatherConfig, WeatherPollResult, WeatherService


FC_DEMAND_BASE_EMA_ALPHA = 0.35


@dataclass(frozen=True)
class AppTickResult:
    """
    Result from one runtime tick.
    """

    observed_at: datetime
    acquisition: AcquisitionResult
    timer_results: tuple[ActuatorCommandResult, ...]
    chlorination_results: tuple[ActuatorCommandResult, ...]
    chlorination_status: ChlorinationStatus | None
    safety_results: tuple[ActuatorCommandResult, ...]
    startup_safe_off_results: tuple[ActuatorCommandResult, ...] = ()
    relay_reconciliation_results: tuple[ActuatorCommandResult, ...] = ()
    mqtt_results: tuple[ActuatorCommandResult, ...] = ()
    logged_measurement_count: int = 0
    logged_lab_test_count: int = 0
    flow_estimates: FlowEstimates = FlowEstimates()
    csi_measurement: Measurement | None = None
    weather_result: WeatherPollResult = field(default_factory=WeatherPollResult)
    fc_demand_status: FcDemandStatus | None = None
    logged_chlorine_delivery_count: int = 0
    duration_s: float = 0.0
    control_duration_s: float = 0.0

    @property
    def measurements(self) -> tuple[Measurement, ...]:
        return self.acquisition.measurements

    @property
    def loggable_measurements(self) -> tuple[Measurement, ...]:
        return self.acquisition.loggable_measurements


@dataclass(frozen=True)
class TimerOverrideState:
    """
    Active manual timer override with optional expiration.
    """

    override: PumpTimerOverride
    set_at: datetime
    until: datetime | None = None
    source: str = "manual"

    def is_active(self, now: datetime) -> bool:
        return self.until is None or now < self.until


@dataclass(frozen=True)
class ChemistrySamplingRefreshConfig:
    """
    Periodically run pump flow so chemistry loop sensors can become valid.
    """

    enabled: bool = False
    max_pump_off_s: float = 6 * 3600
    run_duration_s: float = 20 * 60
    pump_speed: ActuatorState = ActuatorState.HIGH

    def __post_init__(self) -> None:
        if self.max_pump_off_s <= 0:
            raise ValueError("max_pump_off_s must be greater than zero")
        if self.run_duration_s <= 0:
            raise ValueError("run_duration_s must be greater than zero")
        if self.pump_speed not in (ActuatorState.LOW, ActuatorState.HIGH):
            raise ValueError("pump_speed must be low or high")


@dataclass(frozen=True)
class RelaySafetyConfig:
    """
    Runtime safety behavior for latching relay outputs.
    """

    startup_safe_off: bool = False
    reconciliation_interval_s: float = 0.0

    def __post_init__(self) -> None:
        if self.reconciliation_interval_s < 0:
            raise ValueError("reconciliation_interval_s cannot be negative")

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any],
        *,
        driver_profile: DriverProfile,
    ) -> RelaySafetyConfig:
        defaults_enabled = driver_profile == DriverProfile.RASPBERRY_PI
        relay_data = data.get("modbus_relay", {})
        if not isinstance(relay_data, Mapping):
            raise ValueError("modbus_relay must be a mapping")

        return cls(
            startup_safe_off=_bool_value(
                relay_data,
                "startup_safe_off",
                defaults_enabled,
            ),
            reconciliation_interval_s=_float_value(
                relay_data,
                "reconciliation_interval_s",
                30.0 if defaults_enabled else 0.0,
            ),
        )


@dataclass(frozen=True)
class PoolControllerApp:
    """
    Composed runtime object for one pool controller deployment.

    It owns the services that participate in the control loop. The first loop
    is deliberately small: refresh actuator state, acquire due measurements,
    and enforce safety on the freshest available measurements.
    """

    runtime_config: RuntimeConfig
    safety_config: SafetyConfig
    acquisition_config: AcquisitionConfig
    pump_timer_config: PumpTimerConfig
    chlorination_config: ChlorinationConfig
    fc_demand_config: FcDemandConfig
    live_view_config: LiveViewConfig
    measurement_logging_config: MeasurementLoggingConfig
    clock: Clock
    router: CommandRouter
    acquisition_service: AcquisitionService | None = None
    pump_timer: PumpTimer | None = None
    chlorination_controller: ChlorinationController | None = None
    measurement_logger: MeasurementLogger | None = None
    simulated_plant: SimulatedPlant | None = None
    timer_override: TimerOverrideState | None = None
    modbus_bus_registry: ModbusRtuBusRegistry | None = None
    chemistry_sampling_refresh: ChemistrySamplingRefreshConfig = ChemistrySamplingRefreshConfig()
    sample_timer_override: TimerOverrideState | None = None
    override_audit: tuple[dict[str, Any], ...] = ()
    mqtt_bridge: MqttBridge | None = None
    flow_estimation_config: FlowEstimationConfig = FlowEstimationConfig()
    calcium_saturation_index_config: CalciumSaturationIndexConfig = CalciumSaturationIndexConfig()
    weather_config: WeatherConfig = WeatherConfig()
    weather_service: WeatherService | None = None
    notifications_config: NotificationsConfig = field(default_factory=NotificationsConfig)
    notification_service: NotificationService | None = None
    relay_safety_config: RelaySafetyConfig = RelaySafetyConfig()
    relay_startup_safe_off_done: bool = False
    relay_last_reconciled_at: datetime | None = None
    chlorine_delivery_checkpoint_at: datetime | None = None
    dosing_prime_until: datetime | None = None
    dosing_prime_started_at: datetime | None = None
    dosing_prime_mode: str = "prime"
    dosing_prime_duty_cycle: float = 1.0
    dosing_prime_cycle_period_s: float = 60.0
    dosing_prime_safety_bypass: bool = True
    dosing_prime_delivery_exclude_started_at: datetime | None = None
    dosing_prime_delivery_exclude_until: datetime | None = None

    async def tick(self, *, force_acquisition: bool = False) -> AppTickResult:
        # Measure the tick with a monotonic clock. This is used for loop timing
        # diagnostics and is separate from the controller Clock, which may be a
        # simulated accelerated clock.
        tick_started_s = time.perf_counter()

        # Load relay/actuator state before making decisions. On real hardware,
        # this lets the app begin with the board's actual state instead of only
        # trusting in-memory defaults.
        await self.router.ensure_states_loaded()
        startup_safe_off_results = tuple(await self._run_startup_safe_off())
        self._update_sampling_override()

        # The pump timer and manual overrides are evaluated first because other
        # features, especially chlorination, depend on whether the pump is on.
        timer_results = await self._run_pump_timer()

        # Chlorination intentionally uses the latest completed acquisition data.
        # It should not wait for slow chemistry/Modbus reads before deciding
        # whether to turn the dosing pump on or off for this tick.
        control_measurements_source = (
            tuple(self.acquisition_service.latest_measurements.values())
            if self.acquisition_service is not None
            else ()
        )

        # The FC demand estimator may adjust today's dose or delay the start of
        # dosing time, but it still feeds the open-loop chlorination controller.
        fc_demand_plan = self.fc_demand_plan(now=self.clock.now())
        (
            chlorination_results,
            chlorination_status,
            logged_chlorine_delivery_count,
        ) = await self._run_chlorination(
            measurements=control_measurements_source,
            plan_adjustment=(
                fc_demand_plan.adjustment if fc_demand_plan is not None else None
            ),
        )

        # `control_duration_s` ends before acquisition. That makes it easier to
        # see whether the time-critical scheduler/dosing decisions are fast even
        # when a sensor read later in the tick is slow.
        control_duration_s = time.perf_counter() - tick_started_s

        # Acquisition runs after the output decisions. This ordering keeps
        # sensor delays from stretching a dosing ON pulse past its intended
        # boundary, which matters for accurate chlorine volume.
        acquisition = await self._poll_acquisition(force=force_acquisition)
        latest_measurements = (
            self.acquisition_service.latest_measurements
            if self.acquisition_service is not None
            else {}
        )

        # Flow, filter restriction, and CSI are not directly read from sensors;
        # they are derived from the latest measurements and then logged like
        # normal measurements when their source readings are due to be logged.
        flow_estimates = estimate_flows(
            measurements=latest_measurements,
            actuator_states=self.router.actuator_states,
            config=self.flow_estimation_config,
        )
        flow_derived_measurements = _flow_derived_measurements(
            flow_estimates=flow_estimates,
            observed_at=self.clock.now(),
        )
        csi_measurement = self._csi_derived_measurement(latest_measurements)
        source_logged_sensor_ids = {measurement.sensor_id for measurement in acquisition.loggable_measurements}
        flow_source_sensor_ids = {
            SensorId.PUMP_OUTPUT_PSI,
            SensorId.FILTER_OUTPUT_PSI,
            SensorId.RETURN_PSI,
            SensorId.BUBBLER_PSI,
            SensorId.BOOSTER_PSI,
        }
        # Derived flow values are stored only when at least one pressure source
        # was already due to be logged. That avoids filling the DB with derived
        # duplicates on every fast control tick.
        should_log_flow_derived = bool(source_logged_sensor_ids & flow_source_sensor_ids)
        should_log_csi = (
            csi_measurement is not None
            and (
                SensorId.TEMP in source_logged_sensor_ids
                or SensorId.RAW_PH in source_logged_sensor_ids
            )
        )
        loggable_measurements = (
            tuple(acquisition.loggable_measurements) + flow_derived_measurements
            if should_log_flow_derived
            else acquisition.loggable_measurements
        )
        if should_log_csi and csi_measurement is not None:
            loggable_measurements = tuple(loggable_measurements) + (csi_measurement,)
        mqtt_results, logged_lab_test_count = await self._process_mqtt_inputs(acquisition.measurements)
        logged_measurement_count = self._log_measurements(loggable_measurements)
        daily_summary_measurements = self._daily_environment_measurements(
            observed_at=self.clock.now()
        )
        logged_measurement_count += self._log_measurements(daily_summary_measurements)

        # These are controller state signals rather than physical sensors. They
        # are logged so history can show duty cycle, daily dose, and FC-demand
        # estimates alongside ORP, temperature, and weather.
        control_measurements = self._chlorination_control_measurements(
            chlorination_status=chlorination_status,
            fc_demand_status=(
                fc_demand_plan.status if fc_demand_plan is not None else None
            ),
            observed_at=self.clock.now(),
        )
        logged_measurement_count += self._log_measurements(control_measurements)
        safety_results: tuple[ActuatorCommandResult, ...] = ()

        if self.runtime_config.layer_enabled(FeatureLayer.SAFETY_ENFORCEMENT):
            safety_measurements = acquisition.measurements
            if not safety_measurements and self.acquisition_service is not None:
                safety_measurements = tuple(
                    self.acquisition_service.latest_measurements.values()
                )

            # Dosing diagnostic modes can run with the filter pump off, so the
            # normal chlorine interlock would constantly fight the diagnostic.
            # Hard lockouts such as overpressure are still honored.
            suppressed_reason_codes = (
                ("chlorine_interlock_lost",)
                if self.dosing_pump_diagnostic_active()
                else ()
            )
            safety_results = tuple(
                await self.router.enforce_safety(
                    measurements=safety_measurements,
                    suppressed_action_reason_codes=suppressed_reason_codes,
                )
            )

        relay_reconciliation_results = tuple(await self._run_relay_reconciliation())

        publish_measurements = acquisition.measurements
        if csi_measurement is not None:
            publish_measurements = publish_measurements + (csi_measurement,)
        publish_measurements = publish_measurements + control_measurements
        self._publish_mqtt(publish_measurements)

        return AppTickResult(
            observed_at=self.clock.now(),
            acquisition=acquisition,
            timer_results=timer_results,
            safety_results=safety_results,
            startup_safe_off_results=startup_safe_off_results,
            relay_reconciliation_results=relay_reconciliation_results,
            mqtt_results=mqtt_results,
            logged_measurement_count=logged_measurement_count,
            logged_lab_test_count=logged_lab_test_count,
            flow_estimates=flow_estimates,
            csi_measurement=csi_measurement,
            chlorination_results=chlorination_results,
            chlorination_status=chlorination_status,
            fc_demand_status=(
                fc_demand_plan.status if fc_demand_plan is not None else None
            ),
            logged_chlorine_delivery_count=logged_chlorine_delivery_count,
            duration_s=time.perf_counter() - tick_started_s,
            control_duration_s=control_duration_s,
        )

    def apply_pump_timer_config(self, config: PumpTimerConfig) -> None:
        """
        Apply updated pump timer schedules to the running app.
        """
        object.__setattr__(self, "pump_timer_config", config)

        if self.runtime_config.layer_enabled(FeatureLayer.PUMP_TIMER):
            object.__setattr__(self, "pump_timer", PumpTimer(config))
            return

        object.__setattr__(self, "pump_timer", None)

    def apply_chlorination_config(self, config: ChlorinationConfig) -> None:
        """
        Apply updated open-loop chlorination settings to the running app.
        """
        object.__setattr__(self, "chlorination_config", config)
        object.__setattr__(self, "chlorination_controller", ChlorinationController(config))

    def apply_fc_demand_config(self, config: FcDemandConfig) -> None:
        """
        Apply updated FC-demand estimator settings to the running app.
        """
        object.__setattr__(self, "fc_demand_config", config)

    def apply_notifications_config(self, config: NotificationsConfig) -> None:
        """
        Apply updated notification settings to the running app.
        """
        object.__setattr__(self, "notifications_config", config)
        object.__setattr__(
            self,
            "notification_service",
            NotificationService(config) if config.enabled else None,
        )

    def apply_safety_config(self, config: SafetyConfig) -> None:
        """
        Apply updated safety thresholds to the running app.
        """
        object.__setattr__(self, "safety_config", config)
        self.router.safety_gate.config = config

    def set_timer_override(
        self,
        override: PumpTimerOverride,
        *,
        duration_s: float | None = None,
        source: str = "manual_gui",
    ) -> TimerOverrideState:
        now = self.clock.now()
        until = None if duration_s is None else now + timedelta(seconds=duration_s)
        state = TimerOverrideState(
            override=override,
            set_at=now,
            until=until,
            source=source,
        )
        object.__setattr__(self, "timer_override", state)
        self._append_override_audit("set_manual", state)
        return state

    def clear_timer_override(self) -> None:
        current = self.timer_override
        object.__setattr__(self, "timer_override", None)
        if current is not None:
            self._append_override_audit("clear_manual", current)

    def start_dosing_pump_prime(
        self,
        *,
        duration_s: float = 30.0,
    ) -> dict[str, Any]:
        return self._start_dosing_pump_diagnostic(
            duration_s=duration_s,
            mode="prime",
            duty_cycle=1.0,
            cycle_period_s=60.0,
        )

    def start_dosing_pump_calibration(
        self,
        *,
        duration_s: float = 20.0 * 60.0,
        duty_cycle: float = 0.5,
        cycle_period_s: float = 120.0,
    ) -> dict[str, Any]:
        return self._start_dosing_pump_diagnostic(
            duration_s=duration_s,
            mode="calibration",
            duty_cycle=duty_cycle,
            cycle_period_s=cycle_period_s,
        )

    async def stop_dosing_pump_diagnostic(self) -> dict[str, Any]:
        now = self.clock.now()
        started_at = self.dosing_prime_started_at
        if started_at is not None:
            object.__setattr__(self, "dosing_prime_delivery_exclude_started_at", started_at)
            object.__setattr__(self, "dosing_prime_delivery_exclude_until", now)

        self._clear_dosing_pump_diagnostic()
        result: ActuatorCommandResult | None = None
        await self.router.refresh_states()
        if self.router.actuator_states.get(ActuatorId.CHLORINE_DOSING_PUMP) == ActuatorState.ON:
            result = await self.router.route(
                ActuatorCommand(
                    actuator_id=ActuatorId.CHLORINE_DOSING_PUMP,
                    created_at=now,
                    state=ActuatorState.OFF,
                    requested_by=CommandSource.LOCAL_GUI,
                    reason="stop dosing pump diagnostic",
                    metadata={"controller": "dosing_pump_diagnostic"},
                ),
                bypass_safety=True,
            )

        return {
            "stopped": True,
            "prime": self.dosing_prime_status(),
            "command": _command_result_payload(result) if result is not None else None,
        }

    def dosing_pump_diagnostic_active(self) -> bool:
        return self.dosing_prime_status()["active"] is True

    def _start_dosing_pump_diagnostic(
        self,
        *,
        duration_s: float,
        mode: str,
        duty_cycle: float,
        cycle_period_s: float,
    ) -> dict[str, Any]:
        if duration_s <= 0:
            raise ValueError("duration_s must be > 0")
        if not 0.0 < duty_cycle <= 1.0:
            raise ValueError("duty_cycle must be > 0 and <= 1")
        if cycle_period_s <= 0:
            raise ValueError("cycle_period_s must be > 0")

        now = self.clock.now()
        until = now + timedelta(seconds=duration_s)
        object.__setattr__(self, "dosing_prime_started_at", now)
        object.__setattr__(self, "dosing_prime_until", until)
        object.__setattr__(self, "dosing_prime_mode", mode)
        object.__setattr__(self, "dosing_prime_duty_cycle", duty_cycle)
        object.__setattr__(self, "dosing_prime_cycle_period_s", cycle_period_s)
        object.__setattr__(self, "dosing_prime_safety_bypass", True)
        object.__setattr__(self, "dosing_prime_delivery_exclude_started_at", now)
        object.__setattr__(self, "dosing_prime_delivery_exclude_until", until)
        return self.dosing_prime_status()

    def dosing_prime_status(self) -> dict[str, Any]:
        now = self.clock.now()
        until = self.dosing_prime_until
        active = until is not None and now < until
        if until is not None and not active:
            self._clear_dosing_pump_diagnostic()
            until = None
        desired_state = self._dosing_pump_diagnostic_desired_state(now) if active else ActuatorState.OFF
        remaining_s = max(0.0, (until - now).total_seconds()) if until is not None else 0.0
        return {
            "active": active,
            "mode": self.dosing_prime_mode if active else None,
            "started_at": (
                self.dosing_prime_started_at.isoformat()
                if self.dosing_prime_started_at is not None
                else None
            ),
            "until": until.isoformat() if until is not None else None,
            "remaining_s": remaining_s,
            "duty_cycle": self.dosing_prime_duty_cycle if active else 0.0,
            "cycle_period_s": self.dosing_prime_cycle_period_s if active else 0.0,
            "desired_state": desired_state.value,
            "safety_bypass": self.dosing_prime_safety_bypass if active else False,
        }

    def _clear_dosing_pump_diagnostic(self) -> None:
        object.__setattr__(self, "dosing_prime_until", None)
        object.__setattr__(self, "dosing_prime_started_at", None)
        object.__setattr__(self, "dosing_prime_mode", "prime")
        object.__setattr__(self, "dosing_prime_duty_cycle", 1.0)
        object.__setattr__(self, "dosing_prime_cycle_period_s", 60.0)
        object.__setattr__(self, "dosing_prime_safety_bypass", True)

    def _dosing_pump_diagnostic_desired_state(self, now: datetime) -> ActuatorState:
        started_at = self.dosing_prime_started_at
        until = self.dosing_prime_until
        if started_at is None or until is None or now >= until:
            return ActuatorState.OFF

        duty_cycle = max(0.0, min(1.0, self.dosing_prime_duty_cycle))
        if duty_cycle >= 1.0:
            return ActuatorState.ON

        cycle_period_s = max(0.001, self.dosing_prime_cycle_period_s)
        on_seconds = cycle_period_s * duty_cycle
        elapsed_s = max(0.0, (now - started_at).total_seconds())
        return (
            ActuatorState.ON
            if elapsed_s % cycle_period_s < on_seconds
            else ActuatorState.OFF
        )

    def _dosing_pump_diagnostic_on_pulse_seconds(self, now: datetime) -> float | None:
        started_at = self.dosing_prime_started_at
        until = self.dosing_prime_until
        if started_at is None or until is None or now >= until:
            return None

        remaining_s = max(0.0, (until - now).total_seconds())
        if remaining_s <= 0:
            return None

        duty_cycle = max(0.0, min(1.0, self.dosing_prime_duty_cycle))
        if duty_cycle >= 1.0:
            return quantize_relay_flash_seconds(remaining_s)

        cycle_period_s = max(0.001, self.dosing_prime_cycle_period_s)
        on_seconds = cycle_period_s * duty_cycle
        elapsed_s = max(0.0, (now - started_at).total_seconds())
        cycle_position = elapsed_s % cycle_period_s
        if cycle_position >= on_seconds:
            return None

        return quantize_relay_flash_seconds(min(remaining_s, on_seconds - cycle_position))

    def notification_status(self) -> dict[str, Any]:
        if self.notification_service is not None:
            return self.notification_service.status_payload()
        return {
            "enabled": self.notifications_config.enabled,
            "provider": self.notifications_config.provider.value,
            "default_title": self.notifications_config.default_title,
            "pushover": self.notifications_config.pushover.as_payload(),
        }

    def send_notification(
        self,
        *,
        message: str,
        title: str | None = None,
        priority: int | None = None,
    ) -> NotificationResult:
        service = self.notification_service
        if service is None:
            service = NotificationService(self.notifications_config)
        return service.send(
            NotificationMessage(
                title=title or self.notifications_config.default_title,
                message=message,
                priority=priority,
            )
        )

    def active_timer_override(self) -> TimerOverrideState | None:
        state = self.timer_override
        if state is None:
            return None

        if state.is_active(self.clock.now()):
            return state

        object.__setattr__(self, "timer_override", None)
        self._append_override_audit("expire_manual", state)
        return None

    def active_sample_timer_override(self) -> TimerOverrideState | None:
        state = self.sample_timer_override
        if state is None:
            return None

        if state.is_active(self.clock.now()):
            return state

        object.__setattr__(self, "sample_timer_override", None)
        self._append_override_audit("expire_sampling", state)
        return None

    def next_pump_timer_transition(self) -> datetime | None:
        if self.pump_timer is None:
            return None

        return self.pump_timer.next_transition_after(self.clock.now())

    async def _run_startup_safe_off(self) -> tuple[ActuatorCommandResult, ...]:
        if self.relay_startup_safe_off_done:
            return ()

        object.__setattr__(self, "relay_startup_safe_off_done", True)
        if not self.relay_safety_config.startup_safe_off:
            return ()

        results = tuple(
            await self.router.stop_all(reason="startup relay safe-off")
        )
        object.__setattr__(self, "relay_last_reconciled_at", self.clock.now())
        return results

    async def _run_relay_reconciliation(self) -> tuple[ActuatorCommandResult, ...]:
        interval_s = self.relay_safety_config.reconciliation_interval_s
        if interval_s <= 0:
            return ()

        now = self.clock.now()
        last = self.relay_last_reconciled_at
        if last is not None and (now - last).total_seconds() < interval_s:
            return ()

        object.__setattr__(self, "relay_last_reconciled_at", now)
        return tuple(
            await self.router.reconcile_states(reason="periodic relay reconciliation")
        )

    async def _poll_acquisition(self, *, force: bool) -> AcquisitionResult:
        if self.acquisition_service is None:
            return empty_acquisition_result()

        return await self.acquisition_service.poll_due(
            actuator_states=self.router.actuator_states,
            state_started_at=self.router.state_started_at,
            force=force,
        )

    async def _run_pump_timer(self) -> tuple[ActuatorCommandResult, ...]:
        if self.pump_timer is None:
            return ()

        now = self.clock.now()
        manual_override = self.active_timer_override()
        sampling_override = self.active_sample_timer_override()
        selected_override = (
            manual_override
            if manual_override is not None
            else sampling_override
        )
        evaluation = self.pump_timer.evaluate(
            now=now,
            actuator_states=self.router.actuator_states,
            override=selected_override.override if selected_override is not None else None,
        )

        results: list[ActuatorCommandResult] = []
        for command in evaluation.commands:
            results.append(await self.router.route(command))

        return tuple(results)

    async def _run_chlorination(
        self,
        *,
        measurements: tuple[Measurement, ...],
        plan_adjustment: ChlorinationPlanAdjustment | None = None,
    ) -> tuple[tuple[ActuatorCommandResult, ...], ChlorinationStatus | None, int]:
        if self.chlorination_controller is None:
            return (), None, self._log_chlorine_delivery_since_last_tick(self.clock.now())

        now = self.clock.now()
        # Delivery is accounted for before issuing a new state command. The
        # elapsed interval belongs to the previous actuator state, so this
        # preserves accurate ounces even when a tick turns the pump off.
        logged_delivery_count = self._log_chlorine_delivery_since_last_tick(now)
        evaluation = self.chlorination_controller.evaluate(
            now=now,
            pump_timer_config=self.pump_timer_config,
            actuator_states=self.router.actuator_states,
            layer_enabled=self.runtime_config.layer_enabled(FeatureLayer.CHLORINATION),
            plan_adjustment=plan_adjustment,
        )

        results: list[ActuatorCommandResult] = []
        prime_status = self.dosing_prime_status()
        if prime_status["active"]:
            # Prime/calibration is intentionally separated from normal dosing:
            # it can bypass the pump-flow interlock, and its runtime is excluded
            # from daily chlorine totals and FC demand math.
            safety_locked_out = self.router.safety_gate.locked_out
            desired_state = (
                ActuatorState.OFF
                if safety_locked_out
                else ActuatorState(str(prime_status["desired_state"]))
            )
            current_state = self.router.actuator_states.get(
                ActuatorId.CHLORINE_DOSING_PUMP,
                ActuatorState.OFF,
            )
            mode = str(prime_status["mode"] or "prime")
            reason = (
                "dosing pump diagnostic blocked by safety lockout"
                if safety_locked_out
                else f"dosing pump {mode} active"
            )
            status = replace(
                evaluation.status,
                desired_state=desired_state,
                active=desired_state == ActuatorState.ON,
                reason=reason,
                duty_cycle=float(prime_status["duty_cycle"]),
                duty_cycle_window_active=False,
            )
            if current_state != desired_state:
                pulse_seconds = (
                    self._dosing_pump_diagnostic_on_pulse_seconds(now)
                    if desired_state == ActuatorState.ON
                    else None
                )
                command = ActuatorCommand(
                    actuator_id=ActuatorId.CHLORINE_DOSING_PUMP,
                    created_at=now,
                    state=desired_state,
                    requested_by=CommandSource.LOCAL_GUI,
                    reason=reason,
                    metadata={
                        "controller": "dosing_pump_diagnostic",
                        "mode": mode,
                        "duty_cycle": prime_status["duty_cycle"],
                        "cycle_period_s": prime_status["cycle_period_s"],
                        "duration_s": max(
                            0.0,
                            (
                                self.dosing_prime_until - now
                            ).total_seconds()
                            if self.dosing_prime_until is not None
                            else 0.0,
                        ),
                        ACTUATOR_ON_PULSE_SECONDS_METADATA: pulse_seconds,
                        ACTUATOR_AUTO_OFF_AT_METADATA: (
                            (now + timedelta(seconds=pulse_seconds)).isoformat()
                            if pulse_seconds is not None
                            else None
                        ),
                    },
                )
                results.append(
                    await self.router.route(
                        command,
                        measurements=measurements,
                        bypass_safety=bool(prime_status["safety_bypass"]),
                    )
                )
            if not results and desired_state == ActuatorState.OFF:
                confirmation = await self._confirm_expired_dosing_flash_off(now)
                if confirmation is not None:
                    results.append(confirmation)

            return tuple(results), status, logged_delivery_count

        for command in evaluation.commands:
            results.append(await self.router.route(command, measurements=measurements))

        if not results and evaluation.status.desired_state == ActuatorState.OFF:
            confirmation = await self._confirm_expired_dosing_flash_off(now)
            if confirmation is not None:
                results.append(confirmation)

        return tuple(results), evaluation.status, logged_delivery_count

    async def _confirm_expired_dosing_flash_off(
        self,
        now: datetime,
    ) -> ActuatorCommandResult | None:
        sample = self.router.actuator_state_samples.get(ActuatorId.CHLORINE_DOSING_PUMP)
        if sample is None:
            return None

        if sample.state != ActuatorState.OFF:
            return None

        if sample.metadata.get("auto_off_expired") is not True:
            return None

        return await self.router.route(
            ActuatorCommand(
                actuator_id=ActuatorId.CHLORINE_DOSING_PUMP,
                created_at=now,
                state=ActuatorState.OFF,
                requested_by=CommandSource.SYSTEM,
                reason="confirm dosing relay off after timed flash",
                metadata={
                    "controller": "dosing_flash_off_confirmation",
                    "source_command_id": sample.source_command_id,
                    ACTUATOR_AUTO_OFF_AT_METADATA: sample.metadata.get(
                        ACTUATOR_AUTO_OFF_AT_METADATA
                    ),
                },
            )
        )

    def _log_chlorine_delivery_since_last_tick(self, now: datetime) -> int:
        previous = self.chlorine_delivery_checkpoint_at
        object.__setattr__(self, "chlorine_delivery_checkpoint_at", now)
        if previous is None or now <= previous:
            return 0
        if self.measurement_logger is None:
            return 0
        sample = self.router.actuator_state_samples.get(ActuatorId.CHLORINE_DOSING_PUMP)
        runtime_end = _chlorine_runtime_end_from_sample(sample, previous=previous, now=now)
        if runtime_end is None:
            return 0
        if self._dosing_prime_delivery_exclusion_overlaps(previous, runtime_end):
            return 0

        # The dosing pump is treated as a fixed-output pump. Runtime seconds are
        # converted to fluid ounces using the configured pump calibration; the
        # FC estimator later converts ounces to ppm using pool volume/strength.
        runtime_seconds = max(0.0, (runtime_end - previous).total_seconds())
        if runtime_seconds <= 0:
            return 0

        delivered_oz = runtime_seconds / 60.0 * self.chlorination_config.pump_output_oz_per_min
        return self.measurement_logger.log_chlorine_delivery(
            observed_at=runtime_end,
            runtime_seconds=runtime_seconds,
            delivered_oz=delivered_oz,
            metadata={
                "source": "runtime_tick",
                "pump_output_oz_per_min": self.chlorination_config.pump_output_oz_per_min,
            },
        )

    def _dosing_prime_delivery_exclusion_overlaps(
        self,
        previous: datetime,
        now: datetime,
    ) -> bool:
        started_at = self.dosing_prime_delivery_exclude_started_at
        until = self.dosing_prime_delivery_exclude_until
        if started_at is None or until is None:
            return False

        if previous >= until:
            object.__setattr__(self, "dosing_prime_delivery_exclude_started_at", None)
            object.__setattr__(self, "dosing_prime_delivery_exclude_until", None)
            return False

        return previous < until and now > started_at

    def fc_demand_plan(self, *, now: datetime | None = None) -> FcDemandPlan | None:
        now = self.clock.now() if now is None else now
        if not self.fc_demand_config.enabled:
            return estimate_fc_demand_plan(
                config=self.fc_demand_config,
                now=now,
                pump_timer_config=self.pump_timer_config,
                chlorination_config=self.chlorination_config,
                fc_tests=(),
                automated_chlorine_oz=0.0,
                sodium_hypochlorite_additions=(),
            )
        if self.measurement_logger is None:
            return FcDemandPlan(
                status=FcDemandStatus(
                    enabled=True,
                    mode=self.fc_demand_config.mode,
                    ready=False,
                    reason="measurement logging is required for FC demand estimation",
                    target_fc_ppm=self.fc_demand_config.target_fc_ppm,
                    pool_volume_gal=self.fc_demand_config.pool_volume_gal,
                    chlorine_strength_percent=(
                        self.fc_demand_config.chlorine_strength_percent
                    ),
                )
            )

        fc_history = self.measurement_logger.lab_value_history(
            field="free_chlorine",
            limit=2,
        )
        fc_tests = tuple(
            FcTestPoint(sampled_at=sampled_at, free_chlorine=value)
            for sampled_at, value in fc_history
        )
        since = fc_tests[0].sampled_at if len(fc_tests) >= 2 else None
        until = fc_tests[-1].sampled_at if len(fc_tests) >= 2 else None
        delivery_summary = self.measurement_logger.chlorine_delivery_summary(
            since=since,
            until=until,
        )
        chemical_additions = (
            self.measurement_logger.chemical_addition_history(
                since=since,
                until=until,
                limit=1000,
            )
            if since is not None and until is not None
            else ()
        )
        sodium_hypochlorite_additions = tuple(
            addition
            for addition in chemical_additions
            if addition.chemical == ChemicalType.SODIUM_HYPOCHLORITE
        )
        return estimate_fc_demand_plan(
            config=self.fc_demand_config,
            now=now,
            pump_timer_config=self.pump_timer_config,
            chlorination_config=self.chlorination_config,
            fc_tests=fc_tests,
            automated_chlorine_oz=delivery_summary.delivered_oz,
            sodium_hypochlorite_additions=sodium_hypochlorite_additions,
        )

    def _log_measurements(self, measurements: tuple[Measurement, ...]) -> int:
        if self.measurement_logger is None:
            return 0

        return self.measurement_logger.log_measurements(measurements)

    def _daily_environment_measurements(
        self,
        *,
        observed_at: datetime,
    ) -> tuple[Measurement, ...]:
        if self.measurement_logger is None:
            return ()

        local_day, start_utc, end_utc, summary_observed_at = _completed_local_day_window(
            observed_at,
            timezone_name=self.pump_timer_config.timezone,
        )
        measurements: list[Measurement] = []

        water_summary = self.measurement_logger.measurement_value_summary(
            sensor_id=SensorId.ORP_TEMP,
            since=start_utc,
            until=end_utc,
            qualities=(Quality.GOOD,),
        )
        if water_summary is not None:
            water_unit = water_summary.unit or "degF"
            measurements.extend(
                (
                    _daily_summary_measurement(
                        sensor_id=SensorId.DAILY_WATER_TEMP_MIN,
                        observed_at=summary_observed_at,
                        local_day=local_day,
                        timezone_name=self.pump_timer_config.timezone,
                        start_utc=start_utc,
                        end_utc=end_utc,
                        summary=water_summary,
                        aggregation="min",
                        value=water_summary.min_value,
                        unit=water_unit,
                        source="orp_temp",
                    ),
                    _daily_summary_measurement(
                        sensor_id=SensorId.DAILY_WATER_TEMP_AVG,
                        observed_at=summary_observed_at,
                        local_day=local_day,
                        timezone_name=self.pump_timer_config.timezone,
                        start_utc=start_utc,
                        end_utc=end_utc,
                        summary=water_summary,
                        aggregation="avg",
                        value=water_summary.avg_value,
                        unit=water_unit,
                        source="orp_temp",
                    ),
                    _daily_summary_measurement(
                        sensor_id=SensorId.DAILY_WATER_TEMP_MAX,
                        observed_at=summary_observed_at,
                        local_day=local_day,
                        timezone_name=self.pump_timer_config.timezone,
                        start_utc=start_utc,
                        end_utc=end_utc,
                        summary=water_summary,
                        aggregation="max",
                        value=water_summary.max_value,
                        unit=water_unit,
                        source="orp_temp",
                    ),
                )
            )

        uv_summary = self.measurement_logger.weather_value_summary(
            field="uv_index",
            since=start_utc,
            until=end_utc,
        )
        if uv_summary is not None:
            measurements.append(
                _daily_summary_measurement(
                    sensor_id=SensorId.DAILY_UV_INDEX_DOSE,
                    observed_at=summary_observed_at,
                    local_day=local_day,
                    timezone_name=self.pump_timer_config.timezone,
                    start_utc=start_utc,
                    end_utc=end_utc,
                    summary=uv_summary,
                    aggregation="sum",
                    value=uv_summary.sum_value,
                    unit="index-hour",
                    source="weather.uv_index",
                )
            )

        shortwave_summary = self.measurement_logger.weather_value_summary(
            field="shortwave_radiation",
            since=start_utc,
            until=end_utc,
        )
        if shortwave_summary is not None:
            measurements.append(
                _daily_summary_measurement(
                    sensor_id=SensorId.DAILY_SHORTWAVE_RADIATION_DOSE,
                    observed_at=summary_observed_at,
                    local_day=local_day,
                    timezone_name=self.pump_timer_config.timezone,
                    start_utc=start_utc,
                    end_utc=end_utc,
                    summary=shortwave_summary,
                    aggregation="sum",
                    value=shortwave_summary.sum_value,
                    unit="Wh/m2",
                    source="weather.shortwave_radiation",
                )
            )

        return tuple(measurements)

    def _chlorination_control_measurements(
        self,
        *,
        chlorination_status: ChlorinationStatus | None,
        fc_demand_status: FcDemandStatus | None,
        observed_at: datetime,
    ) -> tuple[Measurement, ...]:
        measurements: list[Measurement] = []

        if (
            chlorination_status is not None
            and chlorination_status.duty_cycle_window_active
        ):
            measurements.append(
                Measurement(
                    sensor_id=SensorId.CHLORINATION_DUTY_CYCLE_PERCENT,
                    observed_at=observed_at,
                    kind=MeasurementKind.ESTIMATED,
                    value=round(chlorination_status.duty_cycle * 100.0, 3),
                    unit="percent",
                    quality=Quality.GOOD,
                    metadata={
                        "driver": "chlorination_controller",
                        "source": "chlorination_status",
                        "daily_dose_oz": chlorination_status.daily_dose_oz,
                        "base_daily_dose_oz": chlorination_status.base_daily_dose_oz,
                        "available_runtime_min_per_day": (
                            chlorination_status.available_runtime_min_per_day
                        ),
                        "requested_runtime_min_per_day": (
                            chlorination_status.requested_runtime_min_per_day
                        ),
                        "duty_cycle_limited": chlorination_status.duty_cycle_limited,
                        "cycle_on_seconds": chlorination_status.cycle_on_seconds,
                        "cycle_off_seconds": chlorination_status.cycle_off_seconds,
                        "cycle_period_seconds": chlorination_status.cycle_period_seconds,
                        "nominal_cycle_on_seconds": (
                            chlorination_status.nominal_cycle_on_seconds
                        ),
                        "cycle_on_seconds_reduced": (
                            chlorination_status.cycle_on_seconds_reduced
                        ),
                        "min_cycle_on_seconds_limited": (
                            chlorination_status.min_cycle_on_seconds_limited
                        ),
                        "dose_adjustment_source": (
                            chlorination_status.dose_adjustment_source
                        ),
                    },
                )
            )

        if (
            chlorination_status is not None
            and (
                (
                    chlorination_status.enabled
                    and chlorination_status.layer_enabled
                    and chlorination_status.eligible_window_active
                    and chlorination_status.duty_cycle > 0
                )
                or self.router.actuator_states.get(ActuatorId.CHLORINE_DOSING_PUMP)
                == ActuatorState.ON
            )
            and self.measurement_logger is not None
        ):
            local_day_start = _local_day_start(
                observed_at,
                timezone_name=self.pump_timer_config.timezone,
            )
            daily_delivery = self.measurement_logger.chlorine_delivery_summary(
                since=local_day_start,
                until=observed_at,
            )
            measurements.append(
                Measurement(
                    sensor_id=SensorId.CHLORINE_DAILY_DELIVERED_OZ,
                    observed_at=observed_at,
                    kind=MeasurementKind.ESTIMATED,
                    value=round(daily_delivery.delivered_oz, 3),
                    unit="fl oz",
                    quality=Quality.GOOD,
                    metadata={
                        "driver": "chlorination_controller",
                        "source": "chlorine_delivery",
                        "local_day_start": local_day_start.isoformat(),
                        "runtime_seconds_today": daily_delivery.runtime_seconds,
                    },
                )
            )

        if (
            fc_demand_status is not None
            and fc_demand_status.ready
            and fc_demand_status.daily_demand_ppm is not None
        ):
            measurements.append(
                Measurement(
                    id=_fc_demand_measurement_id(fc_demand_status),
                    sensor_id=SensorId.FC_DEMAND_PPM_PER_DAY,
                    observed_at=(
                        fc_demand_status.current_sampled_at
                        if fc_demand_status.current_sampled_at is not None
                        else observed_at
                    ),
                    kind=MeasurementKind.ESTIMATED,
                    value=round(fc_demand_status.daily_demand_ppm, 4),
                    unit="ppm/day",
                    quality=Quality.GOOD,
                    metadata={
                        "driver": "fc_demand_estimator",
                        "source": "lab_tests,chlorine_delivery,chemical_additions",
                        "target_fc_ppm": fc_demand_status.target_fc_ppm,
                        "previous_sampled_at": (
                            fc_demand_status.previous_sampled_at.isoformat()
                            if fc_demand_status.previous_sampled_at is not None
                            else None
                        ),
                        "current_sampled_at": (
                            fc_demand_status.current_sampled_at.isoformat()
                            if fc_demand_status.current_sampled_at is not None
                            else None
                        ),
                        "previous_fc_ppm": fc_demand_status.previous_fc_ppm,
                        "current_fc_ppm": fc_demand_status.current_fc_ppm,
                        "elapsed_days": fc_demand_status.elapsed_days,
                        "added_fc_ppm": fc_demand_status.added_fc_ppm,
                        "consumed_fc_ppm": fc_demand_status.consumed_fc_ppm,
                        "maintenance_dose_oz_per_day": (
                            fc_demand_status.maintenance_dose_oz_per_day
                        ),
                        "recommended_daily_dose_oz": (
                            fc_demand_status.recommended_daily_dose_oz
                        ),
                        "effective_daily_dose_oz": (
                            fc_demand_status.effective_daily_dose_oz
                        ),
                    },
                )
            )
            measurements.extend(
                _fc_demand_trend_measurements(
                    logger=self.measurement_logger,
                    status=fc_demand_status,
                    observed_at=(
                        fc_demand_status.current_sampled_at
                        if fc_demand_status.current_sampled_at is not None
                        else observed_at
                    ),
                )
            )

        return tuple(measurements)

    def poll_weather_due(self) -> WeatherPollResult:
        if self.weather_service is None:
            return WeatherPollResult()
        return self.weather_service.poll_due(
            now=self.clock.now(),
            log_observation=(
                self.measurement_logger.log_weather_observation
                if self.measurement_logger is not None
                else None
            ),
        )

    def _poll_weather(self) -> WeatherPollResult:
        return self.poll_weather_due()

    def _update_sampling_override(self) -> None:
        if not self.chemistry_sampling_refresh.enabled:
            return
        if self.acquisition_service is None:
            return
        if self.pump_timer is None:
            return
        if self.active_timer_override() is not None:
            return
        if self.router.safety_gate.locked_out:
            return

        now = self.clock.now()
        state = self.active_sample_timer_override()
        if state is not None:
            return

        pump_state = self.router.actuator_states.get(ActuatorId.PUMP_MOTOR)
        if pump_state != ActuatorState.OFF:
            return

        pump_off_since = self.router.state_started_at.get(ActuatorId.PUMP_MOTOR, now)
        pump_off_for_s = max(0.0, (now - pump_off_since).total_seconds())
        if pump_off_for_s < self.chemistry_sampling_refresh.max_pump_off_s:
            return

        override = PumpTimerOverride(
            pump_motor=ActuatorState.ON,
            pump_speed=self.chemistry_sampling_refresh.pump_speed,
            booster_state=ActuatorState.OFF,
            reason="auto chemistry refresh run",
        )
        state = TimerOverrideState(
            override=override,
            set_at=now,
            until=now + timedelta(seconds=self.chemistry_sampling_refresh.run_duration_s),
            source="auto_sampling",
        )
        object.__setattr__(self, "sample_timer_override", state)
        self._append_override_audit("set_sampling", state)

    def _append_override_audit(
        self,
        event: str,
        state: TimerOverrideState,
    ) -> None:
        entry = {
            "event": event,
            "at": self.clock.now().isoformat(),
            "source": state.source,
            "reason": state.override.reason,
            "pump_motor": state.override.pump_motor.value,
            "pump_speed": state.override.pump_speed.value,
            "booster": state.override.booster_state.value,
            "until": state.until.isoformat() if state.until is not None else None,
        }
        updated = (*self.override_audit[-99:], entry)
        object.__setattr__(self, "override_audit", updated)

    async def _process_mqtt_inputs(
        self,
        measurements: tuple[Measurement, ...],
    ) -> tuple[tuple[ActuatorCommandResult, ...], int]:
        if self.mqtt_bridge is None:
            return (), 0

        commands, lab_tests = self.mqtt_bridge.drain_inputs()
        results: list[ActuatorCommandResult] = []
        logged_lab_tests = 0

        for payload in commands:
            command = _mqtt_command_payload(payload, now=self.clock.now())
            if command is None:
                continue
            result = await self.router.route(command, measurements=measurements)
            results.append(result)

        if self.measurement_logger is not None:
            for payload in lab_tests:
                test = _mqtt_lab_test_payload(payload, now=self.clock.now())
                if test is None:
                    continue
                self.measurement_logger.log_lab_test(test)
                logged_lab_tests += 1

        return tuple(results), logged_lab_tests

    def _publish_mqtt(self, measurements: tuple[Measurement, ...]) -> None:
        if self.mqtt_bridge is None:
            return

        now = self.clock.now()
        sensors = {
            measurement.sensor_id.value: {
                "value": measurement.value,
                "unit": measurement.unit,
                "quality": measurement.quality.value,
                "observed_at": measurement.observed_at.isoformat(),
            }
            for measurement in measurements
        }
        live_payload = {
            "observed_at": now.isoformat(),
            "runtime_stage": self.runtime_config.stage.value,
            "safety_lockout": self.router.safety_gate.locked_out,
            "actuators": {
                actuator_id.value: state.value
                for actuator_id, state in self.router.actuator_states.items()
            },
            "sensors": sensors,
        }
        self.mqtt_bridge.publish_live(live_payload)
        self.mqtt_bridge.publish_health(
            {
                "observed_at": now.isoformat(),
                "safety_lockout": self.router.safety_gate.locked_out,
                "mqtt": self.mqtt_bridge.status_payload(),
            }
        )

    def _csi_derived_measurement(
        self,
        measurements: Mapping[SensorId, Measurement],
    ) -> Measurement | None:
        if self.measurement_logger is None:
            return None

        lab_values = self.measurement_logger.latest_lab_values(
            fields=("calcium_hardness", "alkalinity", "tds")
        )
        estimate = estimate_calcium_saturation_index(
            measurement_by_sensor=measurements,
            lab_values=lab_values,
            config=self.calcium_saturation_index_config,
        )
        if estimate is None:
            return None

        return Measurement(
            sensor_id=SensorId.CALCIUM_SATURATION_INDEX,
            observed_at=self.clock.now(),
            kind=MeasurementKind.ESTIMATED,
            value=round(estimate.value, 4),
            unit="csi",
            quality=Quality.GOOD,
            metadata={
                "driver": "calcium_saturation_index",
                "source": "raw_ph,temp,lab_tests",
                "temp_sensor_id": self.calcium_saturation_index_config.temp_sensor_id.value,
                "ph_sensor_id": self.calcium_saturation_index_config.ph_sensor_id.value,
                "lab_values": lab_values,
                "tc": round(estimate.tc, 4),
                "constant_c": round(estimate.constant_c, 4),
            },
        )


def build_app_from_config(
    path: str | Path,
    *,
    local_config_path: str | Path | None = None,
    clock: Clock | None = None,
    actuator_drivers: Iterable[ActuatorDriver] | None = None,
    sensor_drivers: Iterable[SensorDriver] | None = None,
    multi_sensor_drivers: Iterable[MultiSensorDriver] = (),
) -> PoolControllerApp:
    data = load_config_with_overrides(path, local_path=local_config_path)

    return build_app_from_mapping(
        data,
        clock=clock,
        actuator_drivers=actuator_drivers,
        sensor_drivers=sensor_drivers,
        multi_sensor_drivers=multi_sensor_drivers,
    )


def build_simulated_app(
    path: str | Path,
    *,
    local_config_path: str | Path | None = None,
    clock: Clock | None = None,
) -> PoolControllerApp:
    return build_app_from_config(path, local_config_path=local_config_path, clock=clock)


def build_app_from_mapping(
    data: Mapping[str, Any],
    *,
    clock: Clock | None = None,
    actuator_drivers: Iterable[ActuatorDriver] | None = None,
    sensor_drivers: Iterable[SensorDriver] | None = None,
    multi_sensor_drivers: Iterable[MultiSensorDriver] = (),
) -> PoolControllerApp:
    runtime_config = RuntimeConfig.from_mapping(data)
    safety_config = SafetyConfig.from_mapping(data)
    acquisition_config = _filter_acquisition_config(
        AcquisitionConfig.from_mapping(data),
        runtime_config.enabled_sensor_groups,
    )
    pump_timer_config = PumpTimerConfig.from_mapping(data)
    chlorination_config = ChlorinationConfig.from_mapping(data)
    fc_demand_config = FcDemandConfig.from_mapping(data)
    live_view_config = LiveViewConfig.from_mapping(data)
    measurement_logging_config = MeasurementLoggingConfig.from_mapping(data)
    relay_safety_config = RelaySafetyConfig.from_mapping(
        data,
        driver_profile=runtime_config.driver_profile,
    )
    flow_estimation_config = FlowEstimationConfig.from_mapping(data)
    calcium_saturation_index_config = CalciumSaturationIndexConfig.from_mapping(data)
    chemistry_sampling_refresh = ChemistrySamplingRefreshConfig(
        **_chemistry_sampling_refresh_values(data)
    )
    mqtt_config = MqttBridgeConfig.from_mapping(data)
    weather_config = WeatherConfig.from_mapping(data)
    notifications_config = NotificationsConfig.from_mapping(data)

    built_clock = clock if clock is not None else _default_clock(runtime_config)
    simulated_plant: SimulatedPlant | None = None
    built_multi_sensor_drivers = tuple(multi_sensor_drivers)
    modbus_bus_registry: ModbusRtuBusRegistry | None = None

    if runtime_config.driver_profile == DriverProfile.SIMULATED:
        simulated_plant = SimulatedPlant(clock=built_clock)
        built_actuator_drivers = _filter_actuator_drivers(
            actuator_drivers
            if actuator_drivers is not None
            else build_default_simulated_actuators(simulated_plant),
            runtime_config.enabled_actuators,
        )
        built_sensor_drivers = _filter_sensor_drivers(
            sensor_drivers
            if sensor_drivers is not None
            else build_default_simulated_sensors(simulated_plant),
            acquisition_config,
        )
    else:
        modbus_bus_registry = ModbusRtuBusRegistry()
        built_actuator_drivers = _filter_actuator_drivers(
            actuator_drivers
            if actuator_drivers is not None
            else build_raspberrypi_actuators_from_mapping(
                data,
                clock=built_clock,
                bus_registry=modbus_bus_registry,
            ),
            runtime_config.enabled_actuators,
        )
        raspberrypi_sensor_drivers = (
            build_raspberrypi_sensor_drivers_from_mapping(data, clock=built_clock)
            if sensor_drivers is None
            else ()
        )
        built_sensor_drivers = _filter_sensor_drivers(
            tuple(sensor_drivers) if sensor_drivers is not None else raspberrypi_sensor_drivers,
            acquisition_config,
        )
        if not built_multi_sensor_drivers:
            built_multi_sensor_drivers = tuple(
                build_raspberrypi_sensors_from_mapping(
                    data,
                    clock=built_clock,
                    bus_registry=modbus_bus_registry,
                )
            )

    safety_enabled = runtime_config.layer_enabled(FeatureLayer.SAFETY_ENFORCEMENT)
    router = CommandRouter(
        drivers=built_actuator_drivers,
        safety_gate=SafetyGate(safety_config),
        clock=built_clock,
        safety_enabled=safety_enabled,
    )

    acquisition_service: AcquisitionService | None = None
    if runtime_config.layer_enabled(FeatureLayer.ACQUISITION):
        acquisition_service = AcquisitionService(
            config=acquisition_config,
            clock=built_clock,
            sensor_drivers=built_sensor_drivers,
            multi_sensor_drivers=built_multi_sensor_drivers,
        )

    pump_timer: PumpTimer | None = None
    if runtime_config.layer_enabled(FeatureLayer.PUMP_TIMER):
        pump_timer = PumpTimer(pump_timer_config)

    chlorination_controller = ChlorinationController(chlorination_config)

    measurement_logger: MeasurementLogger | None = None
    if runtime_config.layer_enabled(FeatureLayer.LOGGING):
        measurement_logger = MeasurementLogger(measurement_logging_config)

    mqtt_bridge: MqttBridge | None = None
    if runtime_config.layer_enabled(FeatureLayer.MQTT_BRIDGE) and mqtt_config.enabled:
        mqtt_bridge = MqttBridge(mqtt_config, clock=built_clock)

    weather_service: WeatherService | None = None
    if weather_config.enabled:
        weather_service = WeatherService(weather_config)

    notification_service: NotificationService | None = None
    if notifications_config.enabled:
        notification_service = NotificationService(notifications_config)

    return PoolControllerApp(
        runtime_config=runtime_config,
        safety_config=safety_config,
        acquisition_config=acquisition_config,
        pump_timer_config=pump_timer_config,
        chlorination_config=chlorination_config,
        fc_demand_config=fc_demand_config,
        live_view_config=live_view_config,
        measurement_logging_config=measurement_logging_config,
        clock=built_clock,
        router=router,
        acquisition_service=acquisition_service,
        pump_timer=pump_timer,
        chlorination_controller=chlorination_controller,
        measurement_logger=measurement_logger,
        simulated_plant=simulated_plant,
        timer_override=None,
        modbus_bus_registry=modbus_bus_registry,
        chemistry_sampling_refresh=chemistry_sampling_refresh,
        sample_timer_override=None,
        mqtt_bridge=mqtt_bridge,
        flow_estimation_config=flow_estimation_config,
        calcium_saturation_index_config=calcium_saturation_index_config,
        weather_config=weather_config,
        weather_service=weather_service,
        notifications_config=notifications_config,
        notification_service=notification_service,
        relay_safety_config=relay_safety_config,
    )


def empty_acquisition_result() -> AcquisitionResult:
    return AcquisitionResult(
        group_names=(),
        measurements=(),
        loggable_measurements=(),
        log_decisions=(),
        failures=(),
    )


def _default_clock(runtime_config: RuntimeConfig) -> Clock:
    if runtime_config.driver_profile == DriverProfile.SIMULATED:
        return SimulatedClock(start_at=datetime.now(timezone.utc))

    return RealClock()


def _filter_acquisition_config(
    acquisition_config: AcquisitionConfig,
    enabled_sensor_groups: frozenset[str],
) -> AcquisitionConfig:
    groups_by_name = {group.name: group for group in acquisition_config.groups}
    missing_groups = enabled_sensor_groups - frozenset(groups_by_name)

    if missing_groups:
        missing = ", ".join(sorted(missing_groups))
        raise ValueError(f"enabled sensor groups are not configured: {missing}")

    return AcquisitionConfig(
        groups=tuple(
            group
            for group in acquisition_config.groups
            if group.name in enabled_sensor_groups
        )
    )


def _filter_actuator_drivers(
    drivers: Iterable[ActuatorDriver],
    enabled_actuators: frozenset[ActuatorId],
) -> tuple[ActuatorDriver, ...]:
    return tuple(
        driver for driver in drivers if driver.actuator_id in enabled_actuators
    )


def _filter_sensor_drivers(
    drivers: Iterable[SensorDriver],
    acquisition_config: AcquisitionConfig,
) -> tuple[SensorDriver, ...]:
    enabled_sensor_ids = {
        sensor_id
        for group in acquisition_config.groups
        for sensor_id in group.sensor_ids
    }

    return tuple(
        driver for driver in drivers if driver.sensor_id in enabled_sensor_ids
    )


def _chemistry_sampling_refresh_values(data: Mapping[str, Any]) -> dict[str, Any]:
    acquisition = data.get("acquisition", {})
    if not isinstance(acquisition, Mapping):
        return {}

    refresh = acquisition.get("chemistry_sampling_refresh", {})
    if not isinstance(refresh, Mapping):
        raise ValueError("acquisition.chemistry_sampling_refresh must be a mapping")

    enabled = refresh.get("enabled", False)
    max_pump_off_s = refresh.get("max_pump_off_s", 6 * 3600)
    run_duration_s = refresh.get("run_duration_s", 20 * 60)
    pump_speed = refresh.get("pump_speed", ActuatorState.HIGH.value)

    if not isinstance(enabled, bool):
        raise ValueError("acquisition.chemistry_sampling_refresh.enabled must be true or false")
    if not isinstance(max_pump_off_s, int | float):
        raise ValueError("acquisition.chemistry_sampling_refresh.max_pump_off_s must be a number")
    if not isinstance(run_duration_s, int | float):
        raise ValueError("acquisition.chemistry_sampling_refresh.run_duration_s must be a number")
    if not isinstance(pump_speed, str):
        raise ValueError("acquisition.chemistry_sampling_refresh.pump_speed must be low or high")

    state = ActuatorState(pump_speed)
    if state not in (ActuatorState.LOW, ActuatorState.HIGH):
        raise ValueError("acquisition.chemistry_sampling_refresh.pump_speed must be low or high")

    return {
        "enabled": enabled,
        "max_pump_off_s": float(max_pump_off_s),
        "run_duration_s": float(run_duration_s),
        "pump_speed": state,
    }


def _bool_value(data: Mapping[str, Any], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false")
    return value


def _float_value(data: Mapping[str, Any], key: str, default: float) -> float:
    value = data.get(key, default)
    if not isinstance(value, int | float):
        raise ValueError(f"{key} must be a number")
    return float(value)


def _mqtt_command_payload(payload: dict[str, Any], *, now: datetime) -> ActuatorCommand | None:
    raw_actuator = payload.get("actuator_id")
    raw_state = payload.get("state")
    reason = payload.get("reason", "mqtt remote command")
    if not isinstance(raw_actuator, str) or not isinstance(raw_state, str):
        return None
    if not isinstance(reason, str):
        reason = "mqtt remote command"

    try:
        actuator_id = ActuatorId(raw_actuator)
        state = ActuatorState(raw_state)
    except ValueError:
        return None

    return ActuatorCommand(
        actuator_id=actuator_id,
        created_at=now,
        state=state,
        requested_by=CommandSource.MQTT,
        reason=reason,
        metadata={"source": "mqtt"},
    )


def _mqtt_lab_test_payload(payload: dict[str, Any], *, now: datetime) -> LabTest | None:
    raw = dict(payload)
    sampled_at = raw.get("sampled_at", now.isoformat())
    if not isinstance(sampled_at, str):
        return None
    raw["sampled_at"] = sampled_at
    raw["entered_at"] = now.isoformat()
    if "metadata" not in raw:
        raw["metadata"] = {"source": "mqtt"}
    try:
        return LabTest.model_validate(raw)
    except Exception:
        return None


def _local_day_start(value: datetime, *, timezone_name: str) -> datetime:
    timezone = ZoneInfo(timezone_name)
    local = value.astimezone(timezone)
    return datetime(local.year, local.month, local.day, tzinfo=timezone)


def _completed_local_day_window(
    value: datetime,
    *,
    timezone_name: str,
) -> tuple[str, datetime, datetime, datetime]:
    local_timezone = ZoneInfo(timezone_name)
    local_now = value.astimezone(local_timezone)
    local_today_start = datetime(
        local_now.year,
        local_now.month,
        local_now.day,
        tzinfo=local_timezone,
    )
    local_start = local_today_start - timedelta(days=1)
    local_end = local_today_start
    observed_at = local_start + timedelta(hours=12)
    return (
        local_start.date().isoformat(),
        local_start.astimezone(timezone.utc),
        local_end.astimezone(timezone.utc),
        observed_at.astimezone(timezone.utc),
    )


def _daily_summary_measurement(
    *,
    sensor_id: SensorId,
    observed_at: datetime,
    local_day: str,
    timezone_name: str,
    start_utc: datetime,
    end_utc: datetime,
    summary: ValueSummary,
    aggregation: str,
    value: float,
    unit: str,
    source: str,
) -> Measurement:
    return Measurement(
        id=f"{sensor_id.value}:{local_day}",
        sensor_id=sensor_id,
        observed_at=observed_at,
        kind=MeasurementKind.ESTIMATED,
        value=round(value, 4),
        unit=unit,
        quality=Quality.GOOD,
        metadata={
            "driver": "daily_environment_summary",
            "source": source,
            "aggregation": aggregation,
            "local_day": local_day,
            "timezone": timezone_name,
            "interval_start_utc": start_utc.isoformat(),
            "interval_end_utc": end_utc.isoformat(),
            "sample_count": summary.count,
            "source_min_value": summary.min_value,
            "source_avg_value": summary.avg_value,
            "source_max_value": summary.max_value,
            "source_sum_value": summary.sum_value,
        },
    )


def _fc_demand_measurement_id(status: FcDemandStatus) -> str:
    previous = (
        status.previous_sampled_at.isoformat()
        if status.previous_sampled_at is not None
        else "none"
    )
    current = (
        status.current_sampled_at.isoformat()
        if status.current_sampled_at is not None
        else "none"
    )
    demand = (
        f"{status.daily_demand_ppm:.4f}"
        if status.daily_demand_ppm is not None
        else "none"
    )
    return f"fc_demand_ppm_per_day:{previous}:{current}:{demand}"


def _fc_demand_trend_measurements(
    *,
    logger: MeasurementLogger | None,
    status: FcDemandStatus,
    observed_at: datetime,
) -> tuple[Measurement, ...]:
    if status.daily_demand_ppm is None:
        return ()

    actual_demand = max(0.0, float(status.daily_demand_ppm))
    previous_base = _previous_base_fc_demand(logger=logger, before=observed_at)
    predicted_demand = previous_base if previous_base is not None else actual_demand
    base_demand = (
        actual_demand
        if previous_base is None
        else (
            FC_DEMAND_BASE_EMA_ALPHA * actual_demand
            + (1.0 - FC_DEMAND_BASE_EMA_ALPHA) * previous_base
        )
    )
    residual = actual_demand - predicted_demand
    source_measurement_id = _fc_demand_measurement_id(status)
    source_suffix = source_measurement_id.removeprefix("fc_demand_ppm_per_day:")
    metadata = {
        "driver": "fc_demand_trend",
        "source": "fc_demand_ppm_per_day",
        "source_measurement_id": source_measurement_id,
        "actual_fc_demand_ppm_per_day": actual_demand,
        "previous_base_fc_demand_ppm_per_day": previous_base,
        "base_ema_alpha": FC_DEMAND_BASE_EMA_ALPHA,
        "modifier_model": "not_configured",
        "water_temp_source": SensorId.ORP_TEMP.value,
        "uv_modifier_ppm_per_day": 0.0,
        "temperature_modifier_ppm_per_day": 0.0,
    }

    return (
        Measurement(
            id=f"{SensorId.BASE_FC_DEMAND_PPM_PER_DAY.value}:{source_suffix}",
            sensor_id=SensorId.BASE_FC_DEMAND_PPM_PER_DAY,
            observed_at=observed_at,
            kind=MeasurementKind.ESTIMATED,
            value=round(base_demand, 4),
            unit="ppm/day",
            quality=Quality.GOOD,
            source_measurement_ids=[source_measurement_id],
            metadata={
                **metadata,
                "meaning": "exponential moving average of FC demand",
            },
        ),
        Measurement(
            id=f"{SensorId.PREDICTED_FC_DEMAND_PPM_PER_DAY.value}:{source_suffix}",
            sensor_id=SensorId.PREDICTED_FC_DEMAND_PPM_PER_DAY,
            observed_at=observed_at,
            kind=MeasurementKind.ESTIMATED,
            value=round(predicted_demand, 4),
            unit="ppm/day",
            quality=Quality.GOOD,
            source_measurement_ids=[source_measurement_id],
            metadata={
                **metadata,
                "meaning": "current baseline prediction with no seasonal modifier",
            },
        ),
        Measurement(
            id=f"{SensorId.FC_DEMAND_RESIDUAL_PPM_PER_DAY.value}:{source_suffix}",
            sensor_id=SensorId.FC_DEMAND_RESIDUAL_PPM_PER_DAY,
            observed_at=observed_at,
            kind=MeasurementKind.ESTIMATED,
            value=round(residual, 4),
            unit="ppm/day",
            quality=Quality.GOOD,
            source_measurement_ids=[source_measurement_id],
            metadata={
                **metadata,
                "meaning": "actual FC demand minus predicted FC demand",
            },
        ),
    )


def _previous_base_fc_demand(
    *,
    logger: MeasurementLogger | None,
    before: datetime,
) -> float | None:
    if logger is None:
        return None

    records = logger.history(
        sensor_id=SensorId.BASE_FC_DEMAND_PPM_PER_DAY,
        until=before - timedelta(microseconds=1),
        limit=1,
        qualities=(Quality.GOOD,),
    )
    if not records:
        return None
    return records[-1].value


def _chlorine_runtime_end_from_sample(
    sample: ActuatorStateSample | None,
    *,
    previous: datetime,
    now: datetime,
) -> datetime | None:
    if sample is None:
        return None

    auto_off_at = _metadata_datetime(sample.metadata.get(ACTUATOR_AUTO_OFF_AT_METADATA))
    if sample.state == ActuatorState.ON:
        runtime_end = min(now, auto_off_at) if auto_off_at is not None else now
        return runtime_end if runtime_end > previous else None

    if (
        sample.state == ActuatorState.OFF
        and sample.metadata.get("auto_off_expired") is True
        and sample.metadata.get("auto_off_previous_state") == ActuatorState.ON.value
        and auto_off_at is not None
        and previous < auto_off_at <= now
    ):
        return auto_off_at

    return None


def _metadata_datetime(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    return None


def _command_result_payload(result: ActuatorCommandResult) -> dict[str, Any]:
    return {
        "command_id": result.command_id,
        "accepted": result.accepted,
        "applied": result.applied,
        "rejection_reason": result.rejection_reason,
        "metadata": result.metadata,
    }


def _flow_derived_measurements(
    *,
    flow_estimates: FlowEstimates,
    observed_at: datetime,
) -> tuple[Measurement, ...]:
    measurements: list[Measurement] = []

    if flow_estimates.pump_flow_gpm is not None:
        measurements.append(
            Measurement(
                sensor_id=SensorId.PUMP_FLOW_GPM,
                observed_at=observed_at,
                kind=MeasurementKind.ESTIMATED,
                value=round(flow_estimates.pump_flow_gpm, 3),
                unit="gpm",
                quality=Quality.GOOD,
                metadata={"driver": "flow_estimation", "source": "pump_output_psi"},
            )
        )
    if flow_estimates.pump_dynamic_head_psi is not None:
        measurements.append(
            Measurement(
                sensor_id=SensorId.PUMP_DYNAMIC_HEAD_PSI,
                observed_at=observed_at,
                kind=MeasurementKind.ESTIMATED,
                value=round(flow_estimates.pump_dynamic_head_psi, 3),
                unit="psi",
                quality=Quality.GOOD,
                metadata={"driver": "flow_estimation", "source": "pump_output_psi+pump_flow_gpm"},
            )
        )
    if flow_estimates.return_flow_gpm is not None:
        measurements.append(
            Measurement(
                sensor_id=SensorId.RETURN_FLOW_GPM,
                observed_at=observed_at,
                kind=MeasurementKind.ESTIMATED,
                value=round(flow_estimates.return_flow_gpm, 3),
                unit="gpm",
                quality=Quality.GOOD,
                metadata={"driver": "flow_estimation", "source": "return_psi"},
            )
        )
    if flow_estimates.bubbler_flow_gpm is not None:
        measurements.append(
            Measurement(
                sensor_id=SensorId.BUBBLER_FLOW_GPM,
                observed_at=observed_at,
                kind=MeasurementKind.ESTIMATED,
                value=round(flow_estimates.bubbler_flow_gpm, 3),
                unit="gpm",
                quality=Quality.GOOD,
                metadata={"driver": "flow_estimation", "source": "bubbler_psi"},
            )
        )
    if flow_estimates.booster_flow_gpm is not None:
        measurements.append(
            Measurement(
                sensor_id=SensorId.BOOSTER_FLOW_GPM,
                observed_at=observed_at,
                kind=MeasurementKind.ESTIMATED,
                value=round(flow_estimates.booster_flow_gpm, 3),
                unit="gpm",
                quality=Quality.GOOD,
                metadata={"driver": "flow_estimation", "source": "booster_psi"},
            )
        )

    if flow_estimates.filter_restriction_metric is not None:
        measurements.append(
            Measurement(
                sensor_id=SensorId.FILTER_RESTRICTION_METRIC,
                observed_at=observed_at,
                kind=MeasurementKind.ESTIMATED,
                value=round(flow_estimates.filter_restriction_metric, 6),
                unit="restriction_index",
                quality=Quality.GOOD,
                metadata={"driver": "flow_estimation", "source": "pump_output_psi-filter_output_psi"},
            )
        )

    if flow_estimates.filter_restriction_percent is not None:
        measurements.append(
            Measurement(
                sensor_id=SensorId.FILTER_RESTRICTION_PERCENT,
                observed_at=observed_at,
                kind=MeasurementKind.ESTIMATED,
                value=round(flow_estimates.filter_restriction_percent, 3),
                unit="percent",
                quality=Quality.GOOD,
                metadata={"driver": "flow_estimation", "source": "filter_restriction_metric"},
            )
        )

    return tuple(measurements)
