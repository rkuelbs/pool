from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from poolctl.config import DriverProfile, FeatureLayer, LiveViewConfig, RuntimeConfig
from poolctl.domain.models import (
    ActuatorCommandResult,
    ActuatorCommand,
    ActuatorId,
    ActuatorState,
    CommandSource,
    LabTest,
    Measurement,
)
from poolctl.drivers.base import ActuatorDriver, MultiSensorDriver, SensorDriver
from poolctl.drivers.modbus.rtu_bus import ModbusRtuBusRegistry
from poolctl.drivers.raspberrypi.actuators import build_raspberrypi_actuators_from_mapping
from poolctl.drivers.raspberrypi.sensors import build_raspberrypi_sensors_from_mapping
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
from poolctl.services.measurement_logging import (
    MeasurementLogger,
    MeasurementLoggingConfig,
)
from poolctl.services.mqtt import MqttBridge, MqttBridgeConfig
from poolctl.services.flow_estimation import FlowEstimationConfig
from poolctl.services.pump_timer import PumpTimer, PumpTimerConfig
from poolctl.services.pump_timer import PumpTimerOverride
from poolctl.services.safety import SafetyConfig, SafetyGate


@dataclass(frozen=True)
class AppTickResult:
    """
    Result from one runtime tick.
    """

    observed_at: datetime
    acquisition: AcquisitionResult
    timer_results: tuple[ActuatorCommandResult, ...]
    safety_results: tuple[ActuatorCommandResult, ...]
    mqtt_results: tuple[ActuatorCommandResult, ...] = ()
    logged_measurement_count: int = 0
    logged_lab_test_count: int = 0

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
    live_view_config: LiveViewConfig
    measurement_logging_config: MeasurementLoggingConfig
    clock: Clock
    router: CommandRouter
    acquisition_service: AcquisitionService | None = None
    pump_timer: PumpTimer | None = None
    measurement_logger: MeasurementLogger | None = None
    simulated_plant: SimulatedPlant | None = None
    timer_override: TimerOverrideState | None = None
    modbus_bus_registry: ModbusRtuBusRegistry | None = None
    chemistry_sampling_refresh: ChemistrySamplingRefreshConfig = ChemistrySamplingRefreshConfig()
    sample_timer_override: TimerOverrideState | None = None
    override_audit: tuple[dict[str, Any], ...] = ()
    mqtt_bridge: MqttBridge | None = None
    flow_estimation_config: FlowEstimationConfig = FlowEstimationConfig()

    async def tick(self, *, force_acquisition: bool = False) -> AppTickResult:
        await self.router.refresh_states()

        acquisition = await self._poll_acquisition(force=force_acquisition)
        mqtt_results, logged_lab_test_count = await self._process_mqtt_inputs(acquisition.measurements)
        logged_measurement_count = self._log_measurements(
            acquisition.loggable_measurements
        )
        self._update_sampling_override()
        timer_results = await self._run_pump_timer()
        safety_results: tuple[ActuatorCommandResult, ...] = ()

        if self.runtime_config.layer_enabled(FeatureLayer.SAFETY_ENFORCEMENT):
            safety_measurements = acquisition.measurements
            if not safety_measurements and self.acquisition_service is not None:
                safety_measurements = tuple(
                    self.acquisition_service.latest_measurements.values()
                )

            safety_results = tuple(
                await self.router.enforce_safety(measurements=safety_measurements)
            )

        self._publish_mqtt(acquisition.measurements)

        return AppTickResult(
            observed_at=self.clock.now(),
            acquisition=acquisition,
            timer_results=timer_results,
            safety_results=safety_results,
            mqtt_results=mqtt_results,
            logged_measurement_count=logged_measurement_count,
            logged_lab_test_count=logged_lab_test_count,
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

    def _log_measurements(self, measurements: tuple[Measurement, ...]) -> int:
        if self.measurement_logger is None:
            return 0

        return self.measurement_logger.log_measurements(measurements)

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


def build_app_from_config(
    path: str | Path,
    *,
    clock: Clock | None = None,
    actuator_drivers: Iterable[ActuatorDriver] | None = None,
    sensor_drivers: Iterable[SensorDriver] | None = None,
    multi_sensor_drivers: Iterable[MultiSensorDriver] = (),
) -> PoolControllerApp:
    config_path = Path(path)

    with config_path.open("r", encoding="utf-8") as config_file:
        data = yaml.safe_load(config_file) or {}

    if not isinstance(data, Mapping):
        raise ValueError("app config file must contain a mapping")

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
    clock: Clock | None = None,
) -> PoolControllerApp:
    return build_app_from_config(path, clock=clock)


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
    live_view_config = LiveViewConfig.from_mapping(data)
    measurement_logging_config = MeasurementLoggingConfig.from_mapping(data)
    flow_estimation_config = FlowEstimationConfig.from_mapping(data)
    chemistry_sampling_refresh = ChemistrySamplingRefreshConfig(
        **_chemistry_sampling_refresh_values(data)
    )
    mqtt_config = MqttBridgeConfig.from_mapping(data)

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
        built_sensor_drivers = _filter_sensor_drivers(
            sensor_drivers if sensor_drivers is not None else (),
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

    measurement_logger: MeasurementLogger | None = None
    if runtime_config.layer_enabled(FeatureLayer.LOGGING):
        measurement_logger = MeasurementLogger(measurement_logging_config)

    mqtt_bridge: MqttBridge | None = None
    if runtime_config.layer_enabled(FeatureLayer.MQTT_BRIDGE) and mqtt_config.enabled:
        mqtt_bridge = MqttBridge(mqtt_config, clock=built_clock)

    return PoolControllerApp(
        runtime_config=runtime_config,
        safety_config=safety_config,
        acquisition_config=acquisition_config,
        pump_timer_config=pump_timer_config,
        live_view_config=live_view_config,
        measurement_logging_config=measurement_logging_config,
        clock=built_clock,
        router=router,
        acquisition_service=acquisition_service,
        pump_timer=pump_timer,
        measurement_logger=measurement_logger,
        simulated_plant=simulated_plant,
        timer_override=None,
        modbus_bus_registry=modbus_bus_registry,
        chemistry_sampling_refresh=chemistry_sampling_refresh,
        sample_timer_override=None,
        mqtt_bridge=mqtt_bridge,
        flow_estimation_config=flow_estimation_config,
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
