"""
Build and run the pool controller application.

This module is the composition root for the project. It reads configuration,
chooses simulated or Raspberry Pi drivers, wires the services together, and
executes one controller "tick" at a time. A tick is one pass through timer
control, chlorination, acquisition, safety, logging, and notifications.
"""

from __future__ import annotations

import math
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from poolctl.config import DriverProfile, LiveViewConfig, RuntimeConfig
from poolctl.config_files import load_config_with_overrides
from poolctl.domain.models import (
    ACTUATOR_AUTO_OFF_AT_METADATA,
    ACTUATOR_ON_PULSE_SECONDS_METADATA,
    ActuatorCommandResult,
    ActuatorCommand,
    ActuatorId,
    ActuatorState,
    ActuatorStateSample,
    ChemicalAddition,
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
    ChlorineDeliveryPoint,
    FcDemandConfig,
    FcDemandPlan,
    FcDemandStatus,
    estimate_fc_demand_plan,
    fc_observations_from_lab_tests,
    fc_ppm_from_fl_oz,
)
from poolctl.services.measurement_logging import (
    MeasurementLogger,
    MeasurementLoggingConfig,
    ValueSummary,
)
from poolctl.services.flow_estimation import (
    FilterLoadingEstimator,
    FilterLoadingConfig,
    FlowEstimates,
    FlowEstimationConfig,
    estimate_flows,
)
from poolctl.services.notifications import (
    NotificationMessage,
    NotificationResult,
    NotificationService,
    NotificationsConfig,
    evaluate_notification_alerts,
)
from poolctl.services.pump_timer import PumpTimer, PumpTimerConfig
from poolctl.services.pump_timer import PumpTimerOverride
from poolctl.services.pulse_timing import quantize_relay_flash_seconds
from poolctl.services.saturation_index import (
    CalciumSaturationIndexConfig,
    estimate_calcium_saturation_index,
)
from poolctl.services.safety import (
    SafetyConfig,
    SafetyGate,
)
from poolctl.services.weather import WeatherConfig, WeatherPollResult, WeatherService
from poolctl.services.water_temperature import select_water_temperature


FLUID_OUNCES_PER_GALLON = 128.0
DEFAULT_CHLORINE_TANK_FORECAST_RESERVE_GAL = 2.0
DAILY_ENVIRONMENT_SUMMARY_INTERVAL_S = 3600.0
CHLORINATION_CONTROL_SENSOR_IDS = frozenset(
    {
        SensorId.CHLORINATION_DUTY_CYCLE_PERCENT,
        SensorId.CHLORINE_DAILY_DELIVERED_OZ,
    }
)
DAILY_MOVING_AVERAGE_WINDOWS = (7, 28)
DAILY_MOVING_AVERAGE_SENSOR_IDS = {
    SensorId.DAILY_SODIUM_HYPOCHLORITE_ADDED_OZ: {
        7: SensorId.DAILY_SODIUM_HYPOCHLORITE_ADDED_OZ_7D_AVG,
        28: SensorId.DAILY_SODIUM_HYPOCHLORITE_ADDED_OZ_28D_AVG,
    },
    SensorId.DAILY_MURIATIC_ACID_ADDED_OZ: {
        7: SensorId.DAILY_MURIATIC_ACID_ADDED_OZ_7D_AVG,
        28: SensorId.DAILY_MURIATIC_ACID_ADDED_OZ_28D_AVG,
    },
    SensorId.DAILY_ORP_AVG: {
        7: SensorId.DAILY_ORP_AVG_7D_AVG,
        28: SensorId.DAILY_ORP_AVG_28D_AVG,
    },
    SensorId.DAILY_WATER_TEMP_AVG: {
        7: SensorId.DAILY_WATER_TEMP_AVG_7D_AVG,
        28: SensorId.DAILY_WATER_TEMP_AVG_28D_AVG,
    },
    SensorId.DAILY_PH_AVG: {
        7: SensorId.DAILY_PH_AVG_7D_AVG,
        28: SensorId.DAILY_PH_AVG_28D_AVG,
    },
    SensorId.DAILY_UV_INDEX_DOSE: {
        7: SensorId.DAILY_UV_INDEX_DOSE_7D_AVG,
        28: SensorId.DAILY_UV_INDEX_DOSE_28D_AVG,
    },
}


def usable_chlorine_gallons(
    tank_level_gal: float,
    *,
    reserve_gal: float = DEFAULT_CHLORINE_TANK_FORECAST_RESERVE_GAL,
) -> float:
    return max(0.0, float(tank_level_gal) - reserve_gal)


def chlorine_supply_daily_dose_oz(
    *,
    chlorination_status: ChlorinationStatus | None,
    fc_demand_status: FcDemandStatus | None,
    fallback_daily_dose_oz: float,
) -> float:
    maintenance_dose = (
        fc_demand_status.maintenance_dose_oz_per_day
        if fc_demand_status is not None
        else None
    )
    if maintenance_dose is not None and math.isfinite(maintenance_dose):
        return float(maintenance_dose)

    if chlorination_status is not None:
        return float(chlorination_status.daily_dose_oz)

    return float(fallback_daily_dose_oz)


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
    logged_measurement_count: int = 0
    logged_lab_test_count: int = 0
    flow_estimates: FlowEstimates = FlowEstimates()
    water_temperature_measurement: Measurement | None = None
    csi_measurement: Measurement | None = None
    weather_result: WeatherPollResult = field(default_factory=WeatherPollResult)
    fc_demand_status: FcDemandStatus | None = None
    logged_chlorine_delivery_count: int = 0
    notification_results: tuple[NotificationResult, ...] = ()
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
class SupplementalChlorineDoseState:
    """
    Runtime state for a one-shot extra liquid-chlorine dose.
    """

    requested_dose_oz: float
    planned_dose_oz: float
    requested_at: datetime
    dosing_started_at: datetime | None
    completed_dosing_at: datetime | None
    current_pulse_started_at: datetime | None
    accepted_pulse_count: int
    pump_runtime_s: float
    pulse_seconds: float
    pulse_count: int
    duty_cycle: float
    cycle_period_s: float
    no_dose_last_seconds: float
    min_cycle_on_seconds: float
    min_cycle_on_seconds_overridden: bool
    last_reason: str | None = None

    def is_active(self, now: datetime) -> bool:
        if self.completed_dosing_at is None:
            return True
        return now < self.circulate_until

    def phase(self, now: datetime) -> str:
        if self.completed_dosing_at is not None:
            if now < self.circulate_until:
                return "circulating"
            return "complete"
        if self.dosing_started_at is None:
            return "preparing"
        return "dosing"

    def desired_state(self, now: datetime) -> ActuatorState:
        if self.completed_dosing_at is not None:
            return ActuatorState.OFF
        if self.dosing_started_at is None:
            return ActuatorState.ON
        if self._current_pulse_active(now):
            return ActuatorState.ON
        if self.accepted_pulse_count >= self.pulse_count:
            return ActuatorState.OFF
        if self.current_pulse_started_at is None:
            return ActuatorState.ON
        elapsed_since_pulse_s = max(
            0.0,
            (now - self.current_pulse_started_at).total_seconds(),
        )
        return ActuatorState.ON if elapsed_since_pulse_s >= self.cycle_period_s else ActuatorState.OFF

    @property
    def estimated_completion_at(self) -> datetime | None:
        if self.completed_dosing_at is not None:
            return self.completed_dosing_at
        if self.dosing_started_at is None:
            return None
        return self.dosing_started_at + timedelta(seconds=self.cycle_period_s * self.pulse_count)

    @property
    def circulate_until(self) -> datetime:
        if self.completed_dosing_at is None:
            return self.requested_at + timedelta(days=3650)
        return self.completed_dosing_at + timedelta(seconds=self.no_dose_last_seconds)

    @property
    def committed_runtime_s(self) -> float:
        return self.accepted_pulse_count * self.pulse_seconds

    @property
    def remaining_pump_runtime_s(self) -> float:
        return max(0.0, self.pump_runtime_s - self.committed_runtime_s)

    def pulse_index(self, now: datetime) -> int | None:
        if self.completed_dosing_at is not None:
            return None
        if self._current_pulse_active(now):
            return max(0, self.accepted_pulse_count - 1)
        if self.desired_state(now) != ActuatorState.ON:
            return None
        if self.accepted_pulse_count >= self.pulse_count:
            return None
        return self.accepted_pulse_count

    def cycle_position_seconds(self, now: datetime) -> float | None:
        if self.current_pulse_started_at is None:
            return None
        return max(0.0, (now - self.current_pulse_started_at).total_seconds())

    def on_pulse_seconds(self, now: datetime) -> float | None:
        if self.desired_state(now) != ActuatorState.ON:
            return None

        if not self._current_pulse_active(now):
            return self.pulse_seconds

        cycle_position_s = self.cycle_position_seconds(now)
        assert cycle_position_s is not None
        remaining_pulse_s = self.pulse_seconds - cycle_position_s
        remaining_s = min(remaining_pulse_s, self.remaining_pump_runtime_s)
        if remaining_s <= 0:
            return None

        return quantize_relay_flash_seconds(remaining_s)

    def _current_pulse_active(self, now: datetime) -> bool:
        if self.current_pulse_started_at is None:
            return False
        elapsed_s = max(0.0, (now - self.current_pulse_started_at).total_seconds())
        return elapsed_s < self.pulse_seconds


@dataclass(frozen=True)
class ChlorineTankEstimate:
    observed_at: datetime
    level_gal: float
    baseline_sampled_at: datetime
    baseline_level_gal: float
    delivered_oz: float
    delivered_gal: float
    refilled_gal: float
    refill_count: int

    def as_payload(self) -> dict[str, Any]:
        return {
            "observed_at": self.observed_at.isoformat(),
            "level_gal": self.level_gal,
            "baseline_sampled_at": self.baseline_sampled_at.isoformat(),
            "baseline_level_gal": self.baseline_level_gal,
            "delivered_oz_since_baseline": self.delivered_oz,
            "delivered_gal_since_baseline": self.delivered_gal,
            "refilled_gal_since_baseline": self.refilled_gal,
            "refill_count_since_baseline": self.refill_count,
        }


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

    It owns the services that participate in the control loop. Time-critical
    timer and dosing decisions run before acquisition so a slow optional sensor
    cannot delay a chlorine OFF boundary. Acquisition and safety enforcement
    then use the latest available measurements; timed relay flash provides an
    independent hardware pulse-end safeguard on supported Pi relays.
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
    flow_estimation_config: FlowEstimationConfig = FlowEstimationConfig()
    filter_loading_estimator: FilterLoadingEstimator | None = None
    calcium_saturation_index_config: CalciumSaturationIndexConfig = CalciumSaturationIndexConfig()
    weather_config: WeatherConfig = WeatherConfig()
    weather_service: WeatherService | None = None
    notifications_config: NotificationsConfig = field(default_factory=NotificationsConfig)
    notification_service: NotificationService | None = None
    notification_alert_last_sent_at: dict[str, datetime] = field(default_factory=dict)
    relay_safety_config: RelaySafetyConfig = RelaySafetyConfig()
    relay_startup_safe_off_done: bool = False
    relay_last_reconciled_at: datetime | None = None
    chlorine_delivery_checkpoint_at: datetime | None = None
    chlorine_delivery_segment_started_at: datetime | None = None
    chlorine_delivery_segment_ended_at: datetime | None = None
    chlorine_delivery_segment_runtime_s: float = 0.0
    chlorine_delivery_segment_delivered_oz: float = 0.0
    chlorine_delivery_snapshot_points: tuple[tuple[datetime, str], ...] = ()
    chlorine_delivery_reset_logged_local_day: str | None = None
    dosing_prime_until: datetime | None = None
    dosing_prime_started_at: datetime | None = None
    dosing_prime_mode: str = "prime"
    dosing_prime_duty_cycle: float = 1.0
    dosing_prime_cycle_period_s: float = 60.0
    dosing_prime_safety_bypass: bool = True
    dosing_prime_delivery_exclude_started_at: datetime | None = None
    dosing_prime_delivery_exclude_until: datetime | None = None
    supplemental_chlorine_dose: SupplementalChlorineDoseState | None = None
    supplemental_chlorine_last_on_cycle_index: int | None = None
    chlorination_control_last_logged_at: datetime | None = None
    chlorination_control_last_signature: tuple[Any, ...] | None = None
    daily_environment_last_checked_at: datetime | None = None
    fc_demand_last_logged_measurement_id: str | None = None

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
        water_temperature_selection = select_water_temperature(
            latest_measurements,
            now=self.clock.now(),
            config=self.safety_config.freeze_protection.water_temperature_config,
        )
        water_temperature_measurement = (
            water_temperature_selection.canonical_measurement()
        )
        derived_input_measurements = dict(latest_measurements)
        if water_temperature_measurement is not None:
            derived_input_measurements[SensorId.WATER_TEMP] = water_temperature_measurement

        # Flow, filter loading, and CSI are not directly read from sensors;
        # they are derived from the latest measurements and then logged like
        # normal measurements when their source readings are due to be logged.
        filter_loading_update = (
            self.filter_loading_estimator.update(
                now=self.clock.now(),
                measurements=latest_measurements,
                actuator_states=self.router.actuator_states,
            )
            if self.filter_loading_estimator is not None
            else None
        )
        flow_estimates = estimate_flows(
            now=self.clock.now(),
            measurements=latest_measurements,
            actuator_states=self.router.actuator_states,
            max_pressure_age_seconds=self.safety_config.pump_output_max_age_seconds,
            config=self.flow_estimation_config,
            filter_loading=filter_loading_update,
        )
        flow_derived_measurements = _flow_derived_measurements(
            flow_estimates=flow_estimates,
            observed_at=self.clock.now(),
        )
        csi_measurement = self._csi_derived_measurement(derived_input_measurements)
        source_logged_sensor_ids = {measurement.sensor_id for measurement in acquisition.loggable_measurements}
        flow_source_sensor_ids = {
            SensorId.PUMP_OUTPUT_PSI,
        }
        # Derived flow values are stored only when at least one pressure source
        # was already due to be logged, plus the exact tick when a standardized
        # filter-loading test completes.
        should_log_flow_derived = bool(source_logged_sensor_ids & flow_source_sensor_ids) or (
            flow_estimates.filter_loading.completed_this_tick
        )
        should_log_csi = (
            csi_measurement is not None
            and (
                water_temperature_selection.active_source in source_logged_sensor_ids
                or SensorId.RAW_PH in source_logged_sensor_ids
            )
        )
        should_log_water_temperature = (
            water_temperature_measurement is not None
            and water_temperature_selection.active_source in source_logged_sensor_ids
        )
        loggable_measurements = tuple(acquisition.loggable_measurements)
        if should_log_water_temperature and water_temperature_measurement is not None:
            loggable_measurements += (water_temperature_measurement,)
        if should_log_flow_derived:
            loggable_measurements += flow_derived_measurements
        if should_log_csi and csi_measurement is not None:
            loggable_measurements += (csi_measurement,)
        logged_lab_test_count = 0
        logged_measurement_count = self._log_measurements(loggable_measurements)
        daily_summary_measurements = self._daily_environment_measurements(
            observed_at=self.clock.now()
        )
        logged_measurement_count += self._log_measurements(daily_summary_measurements)
        self._queue_due_chlorine_delivery_reset_snapshot(self.clock.now())

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
        logged_measurement_count += self._log_measurements(
            self._loggable_chlorination_control_measurements(
                measurements=control_measurements,
                chlorination_status=chlorination_status,
                observed_at=self.clock.now(),
            )
        )
        safety_results: tuple[ActuatorCommandResult, ...] = ()
        safety_measurements = (
            tuple(self.acquisition_service.latest_measurements.values())
            if self.acquisition_service is not None
            else acquisition.measurements
        )
        safety_measurements = self.safety_measurements(
            safety_measurements,
            observed_at=self.clock.now(),
            source="safety_enforcement",
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

        chlorine_supply_daily_dose = chlorine_supply_daily_dose_oz(
            chlorination_status=chlorination_status,
            fc_demand_status=(
                fc_demand_plan.status if fc_demand_plan is not None else None
            ),
            fallback_daily_dose_oz=self.chlorination_config.daily_dose_oz,
        )
        notification_results = self._run_notification_alerts(
            measurements=self._notification_alert_measurements(
                latest_measurements=derived_input_measurements,
                control_measurements=control_measurements,
                observed_at=self.clock.now(),
                daily_dose_oz=chlorine_supply_daily_dose,
            ),
            freeze_status=self.router.safety_gate.freeze_status(self.clock.now()),
        )

        return AppTickResult(
            observed_at=self.clock.now(),
            acquisition=acquisition,
            timer_results=timer_results,
            safety_results=safety_results,
            startup_safe_off_results=startup_safe_off_results,
            relay_reconciliation_results=relay_reconciliation_results,
            logged_measurement_count=logged_measurement_count,
            logged_lab_test_count=logged_lab_test_count,
            flow_estimates=flow_estimates,
            water_temperature_measurement=water_temperature_measurement,
            csi_measurement=csi_measurement,
            chlorination_results=chlorination_results,
            chlorination_status=chlorination_status,
            fc_demand_status=(
                fc_demand_plan.status if fc_demand_plan is not None else None
            ),
            logged_chlorine_delivery_count=logged_chlorine_delivery_count,
            notification_results=notification_results,
            duration_s=time.perf_counter() - tick_started_s,
            control_duration_s=control_duration_s,
        )

    def apply_pump_timer_config(self, config: PumpTimerConfig) -> None:
        """
        Apply updated pump timer schedules to the running app.
        """
        object.__setattr__(self, "pump_timer_config", config)
        object.__setattr__(self, "pump_timer", PumpTimer(config))

    def apply_chlorination_config(self, config: ChlorinationConfig) -> None:
        """
        Apply updated open-loop chlorination settings to the running app.
        """
        object.__setattr__(self, "chlorination_config", config)
        object.__setattr__(self, "chlorination_controller", ChlorinationController(config))
        self.router.safety_gate.set_chlorine_pump_stabilization_seconds(
            config.no_dose_first_minutes * 60.0
        )

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
        object.__setattr__(self, "notification_alert_last_sent_at", {})
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
        self.router.safety_gate.apply_config(config)

    def apply_filter_loading_config(self, config: FilterLoadingConfig) -> None:
        """
        Apply updated standardized filter-loading settings to the running app.
        """
        flow_config = replace(self.flow_estimation_config, filter_loading=config)
        object.__setattr__(self, "flow_estimation_config", flow_config)
        if self.filter_loading_estimator is None:
            object.__setattr__(
                self,
                "filter_loading_estimator",
                FilterLoadingEstimator(
                    config,
                    pump_pressure_model=flow_config.pump_pressure_model,
                ),
            )
        else:
            self.filter_loading_estimator.apply_config(
                config,
                pump_pressure_model=flow_config.pump_pressure_model,
            )

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

    async def stop_supplemental_chlorine_dose(self) -> dict[str, Any]:
        now = self.clock.now()
        was_active = self.active_supplemental_chlorine_dose() is not None
        logged_delivery_count = self._log_chlorine_delivery_since_last_tick(now)
        object.__setattr__(self, "supplemental_chlorine_dose", None)
        object.__setattr__(self, "supplemental_chlorine_last_on_cycle_index", None)

        result: ActuatorCommandResult | None = None
        if (
            self.router.actuator_states.get(ActuatorId.CHLORINE_DOSING_PUMP)
            == ActuatorState.ON
        ):
            result = await self.router.route(
                ActuatorCommand(
                    actuator_id=ActuatorId.CHLORINE_DOSING_PUMP,
                    created_at=now,
                    state=ActuatorState.OFF,
                    requested_by=CommandSource.LOCAL_GUI,
                    reason="stop supplemental chlorine dose",
                    metadata={"controller": "supplemental_chlorine_dose"},
                )
            )
        logged_delivery_count += self._flush_chlorine_delivery_if_inactive()

        return {
            "stopped": True,
            "was_active": was_active,
            "logged_chlorine_delivery_count": logged_delivery_count,
            "supplemental_chlorine_dose": self.supplemental_chlorine_dose_status(),
            "command": _command_result_payload(result) if result is not None else None,
        }

    def dosing_pump_diagnostic_active(self) -> bool:
        return self.dosing_prime_status()["active"] is True

    def start_supplemental_chlorine_dose(
        self,
        *,
        dose_oz: float,
    ) -> dict[str, Any]:
        if dose_oz <= 0:
            raise ValueError("dose_oz must be > 0")
        if self.pump_timer is None:
            raise ValueError("supplemental chlorine dose requires the pump timer")
        if self.chlorination_controller is None:
            raise ValueError("supplemental chlorine dose requires chlorination")
        if not self.chlorination_config.enabled:
            raise ValueError("chlorination must be enabled for a supplemental dose")
        if self.dosing_pump_diagnostic_active():
            raise ValueError("stop the dosing pump diagnostic before adding a dose")
        if self.active_supplemental_chlorine_dose() is not None:
            raise ValueError("a supplemental chlorine dose is already active")

        now = self.clock.now()
        target_runtime_s = (
            float(dose_oz)
            / self.chlorination_config.pump_output_oz_per_min
            * 60.0
        )
        pulse_count = max(
            1,
            math.ceil(target_runtime_s / self.chlorination_config.cycle_on_seconds),
        )
        pulse_seconds = quantize_relay_flash_seconds(target_runtime_s / pulse_count)

        duty_cycle = self.chlorination_config.max_duty_cycle
        cycle_period_s = pulse_seconds / duty_cycle
        pump_runtime_s = pulse_seconds * pulse_count
        no_dose_last_seconds = self.chlorination_config.no_dose_last_minutes * 60.0
        planned_dose_oz = (
            pump_runtime_s
            / 60.0
            * self.chlorination_config.pump_output_oz_per_min
        )
        state = SupplementalChlorineDoseState(
            requested_dose_oz=float(dose_oz),
            planned_dose_oz=round(planned_dose_oz, 4),
            requested_at=now,
            dosing_started_at=None,
            completed_dosing_at=None,
            current_pulse_started_at=None,
            accepted_pulse_count=0,
            pump_runtime_s=pump_runtime_s,
            pulse_seconds=pulse_seconds,
            pulse_count=pulse_count,
            duty_cycle=duty_cycle,
            cycle_period_s=cycle_period_s,
            no_dose_last_seconds=no_dose_last_seconds,
            min_cycle_on_seconds=self.chlorination_config.min_cycle_on_seconds,
            min_cycle_on_seconds_overridden=(
                pulse_seconds < self.chlorination_config.min_cycle_on_seconds
            ),
        )
        self._log_chlorine_delivery_since_last_tick(now)
        self._flush_chlorine_delivery_segment()
        object.__setattr__(self, "supplemental_chlorine_dose", state)
        object.__setattr__(self, "supplemental_chlorine_last_on_cycle_index", None)
        return self.supplemental_chlorine_dose_status()

    def active_supplemental_chlorine_dose(
        self,
    ) -> SupplementalChlorineDoseState | None:
        state = self.supplemental_chlorine_dose
        if state is None:
            return None
        state = self._advance_supplemental_chlorine_dose_state(
            state,
            now=self.clock.now(),
        )
        if state.is_active(self.clock.now()):
            return state

        object.__setattr__(self, "supplemental_chlorine_dose", None)
        object.__setattr__(self, "supplemental_chlorine_last_on_cycle_index", None)
        return None

    def _advance_supplemental_chlorine_dose_state(
        self,
        state: SupplementalChlorineDoseState,
        *,
        now: datetime,
    ) -> SupplementalChlorineDoseState:
        if (
            state.completed_dosing_at is None
            and state.accepted_pulse_count >= state.pulse_count
            and state.current_pulse_started_at is not None
            and not state._current_pulse_active(now)
        ):
            state = replace(
                state,
                completed_dosing_at=(
                    state.current_pulse_started_at
                    + timedelta(seconds=state.pulse_seconds)
                ),
                last_reason="supplemental chlorine post-dose circulation",
            )
            object.__setattr__(self, "supplemental_chlorine_dose", state)
            object.__setattr__(self, "supplemental_chlorine_last_on_cycle_index", None)
        return state

    def supplemental_chlorine_dose_status(self) -> dict[str, Any]:
        state = self.active_supplemental_chlorine_dose()
        if state is None:
            return {
                "active": False,
                "phase": "idle",
                "desired_state": ActuatorState.OFF.value,
                "requested_dose_oz": 0.0,
                "planned_dose_oz": 0.0,
                "remaining_s": 0.0,
                "dosing_remaining_s": 0.0,
                "circulation_remaining_s": 0.0,
                "duty_cycle": 0.0,
                "pulse_seconds": 0.0,
                "pulse_count": 0,
                "cycle_period_s": 0.0,
                "pump_runtime_s": 0.0,
                "committed_runtime_s": 0.0,
                "remaining_pump_runtime_s": 0.0,
                "no_dose_last_seconds": 0.0,
                "min_cycle_on_seconds": 0.0,
                "min_cycle_on_seconds_overridden": False,
                "reason": None,
                "started_at": None,
                "requested_at": None,
                "dosing_started_at": None,
                "completed_dosing_at": None,
                "estimated_completion_at": None,
                "circulate_until": None,
            }

        now = self.clock.now()
        phase = state.phase(now)
        estimated_completion_at = state.estimated_completion_at
        remaining_s = (
            max(0.0, (state.circulate_until - now).total_seconds())
            if state.completed_dosing_at is not None
            else state.remaining_pump_runtime_s + state.no_dose_last_seconds
        )
        return {
            "active": True,
            "phase": phase,
            "desired_state": state.desired_state(now).value,
            "requested_dose_oz": state.requested_dose_oz,
            "planned_dose_oz": state.planned_dose_oz,
            "remaining_s": remaining_s,
            "dosing_remaining_s": (
                max(0.0, (estimated_completion_at - now).total_seconds())
                if estimated_completion_at is not None and phase == "dosing"
                else state.remaining_pump_runtime_s
            ),
            "circulation_remaining_s": (
                max(0.0, (state.circulate_until - now).total_seconds())
                if phase == "circulating"
                else 0.0
            ),
            "duty_cycle": state.duty_cycle,
            "pulse_seconds": state.pulse_seconds,
            "pulse_count": state.pulse_count,
            "cycle_period_s": state.cycle_period_s,
            "pump_runtime_s": state.pump_runtime_s,
            "committed_runtime_s": state.committed_runtime_s,
            "remaining_pump_runtime_s": state.remaining_pump_runtime_s,
            "no_dose_last_seconds": state.no_dose_last_seconds,
            "min_cycle_on_seconds": state.min_cycle_on_seconds,
            "min_cycle_on_seconds_overridden": (
                state.min_cycle_on_seconds_overridden
            ),
            "reason": state.last_reason,
            "started_at": state.requested_at.isoformat(),
            "requested_at": state.requested_at.isoformat(),
            "dosing_started_at": (
                state.dosing_started_at.isoformat()
                if state.dosing_started_at is not None
                else None
            ),
            "completed_dosing_at": (
                state.completed_dosing_at.isoformat()
                if state.completed_dosing_at is not None
                else None
            ),
            "estimated_completion_at": (
                estimated_completion_at.isoformat()
                if estimated_completion_at is not None
                else None
            ),
            "circulate_until": (
                state.circulate_until.isoformat()
                if state.completed_dosing_at is not None
                else None
            ),
        }

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
            "alerts": self.notifications_config.alerts.as_payload(),
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

    def _notification_alert_measurements(
        self,
        *,
        latest_measurements: Mapping[SensorId, Measurement],
        control_measurements: Iterable[Measurement],
        observed_at: datetime,
        daily_dose_oz: float,
    ) -> dict[SensorId, Measurement]:
        measurements = dict(latest_measurements)
        for measurement in control_measurements:
            measurements[measurement.sensor_id] = measurement

        tank_measurement = self.chlorine_tank_level_measurement(
            observed_at=observed_at,
            source="notification_alert",
        )
        if tank_measurement is not None:
            measurements[tank_measurement.sensor_id] = tank_measurement
            days_measurement = self.chlorine_tank_days_remaining_measurement(
                observed_at=observed_at,
                source="notification_alert",
                daily_dose_oz=daily_dose_oz,
                tank_measurement=tank_measurement,
            )
            if days_measurement is not None:
                measurements[days_measurement.sensor_id] = days_measurement
        filter_result = (
            self.filter_loading_estimator.last_result
            if self.filter_loading_estimator is not None
            else None
        )
        if filter_result is not None and filter_result.raw_flow_loss_percent is not None:
            test_age_seconds = max(
                0.0,
                (observed_at - filter_result.completed_at).total_seconds(),
            )
            measurements[SensorId.FILTER_FLOW_LOSS_PERCENT] = Measurement(
                sensor_id=SensorId.FILTER_FLOW_LOSS_PERCENT,
                observed_at=filter_result.completed_at,
                kind=MeasurementKind.ESTIMATED,
                value=filter_result.raw_flow_loss_percent,
                unit="percent",
                quality=Quality.GOOD,
                metadata={
                    "source": "notification_alert",
                    "reference_psi": filter_result.reference_psi,
                    "estimated_flow_gpm": filter_result.estimated_flow_gpm,
                    "clean_flow_gpm": filter_result.clean_flow_gpm,
                    "last_hydraulic_test_at": filter_result.completed_at.isoformat(),
                    "test_age_seconds": test_age_seconds,
                },
            )
        return measurements

    def _run_notification_alerts(
        self,
        *,
        measurements: Mapping[SensorId, Measurement],
        freeze_status: Mapping[str, Any] | None = None,
    ) -> tuple[NotificationResult, ...]:
        if not self.notifications_config.enabled:
            return ()

        service = self.notification_service
        if service is None:
            service = NotificationService(self.notifications_config)

        now = self.clock.now()
        alerts = evaluate_notification_alerts(
            config=self.notifications_config.alerts,
            measurements=measurements,
            now=now,
            last_sent_at=self.notification_alert_last_sent_at,
            freeze_status=freeze_status,
        )
        if not alerts:
            return ()

        updated_last_sent_at = dict(self.notification_alert_last_sent_at)
        results: list[NotificationResult] = []
        for alert in alerts:
            results.append(
                service.send(
                    NotificationMessage(
                        title=self.notifications_config.default_title,
                        message=alert.message(),
                    )
                )
            )
            updated_last_sent_at[alert.throttle_key] = now

        object.__setattr__(
            self,
            "notification_alert_last_sent_at",
            updated_last_sent_at,
        )
        return tuple(results)

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
        supplemental_dose = self.active_supplemental_chlorine_dose()
        supplemental_override = (
            PumpTimerOverride(
                pump_motor=ActuatorState.ON,
                pump_speed=ActuatorState.LOW,
                booster_state=ActuatorState.OFF,
                reason="supplemental chlorine dose circulation",
            )
            if supplemental_dose is not None
            else None
        )
        manual_override = self.active_timer_override()
        sampling_override = self.active_sample_timer_override()
        selected_override = (
            TimerOverrideState(
                override=supplemental_override,
                set_at=supplemental_dose.requested_at,
                until=supplemental_dose.circulate_until,
                source="supplemental_chlorine_dose",
            )
            if supplemental_dose is not None and supplemental_override is not None
            else manual_override
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
            logged_delivery_count = self._log_chlorine_delivery_since_last_tick(
                self.clock.now()
            )
            logged_delivery_count += self._flush_chlorine_delivery_if_inactive()
            return (), None, logged_delivery_count

        now = self.clock.now()
        # Delivery is accounted for before issuing a new state command. The
        # elapsed interval belongs to the previous actuator state, so this
        # preserves accurate ounces even when a tick turns the pump off.
        logged_delivery_count = self._log_chlorine_delivery_since_last_tick(now)
        safety_measurements = self.safety_measurements(
            measurements,
            observed_at=now,
            source="chlorination_safety",
        )
        evaluation = self.chlorination_controller.evaluate(
            now=now,
            pump_timer_config=self.pump_timer_config,
            actuator_states=self.router.actuator_states,
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
                        measurements=safety_measurements,
                        bypass_safety=bool(prime_status["safety_bypass"]),
                    )
                )
            if not results and desired_state == ActuatorState.OFF:
                confirmation = await self._confirm_expired_dosing_flash_off(now)
                if confirmation is not None:
                    results.append(confirmation)

            logged_delivery_count += self._flush_chlorine_delivery_if_inactive()
            return tuple(results), status, logged_delivery_count

        supplemental_dose = self.active_supplemental_chlorine_dose()
        if supplemental_dose is not None:
            phase = supplemental_dose.phase(now)
            desired_state = supplemental_dose.desired_state(now)
            current_state = self.router.actuator_states.get(
                ActuatorId.CHLORINE_DOSING_PUMP,
                ActuatorState.OFF,
            )
            current_pulse_index = supplemental_dose.pulse_index(now)
            needs_on_pulse_command = (
                desired_state == ActuatorState.ON
                and current_pulse_index is not None
                and self.supplemental_chlorine_last_on_cycle_index
                != current_pulse_index
            )
            reason = (
                "supplemental chlorine preparing for safe circulation"
                if phase == "preparing"
                else "supplemental chlorine post-dose circulation"
                if phase == "circulating"
                else "supplemental chlorine dose active"
            )
            estimated_completion_at = supplemental_dose.estimated_completion_at
            status = replace(
                evaluation.status,
                desired_state=desired_state,
                active=desired_state == ActuatorState.ON,
                reason=reason,
                daily_dose_oz=evaluation.status.daily_dose_oz,
                duty_cycle=supplemental_dose.duty_cycle,
                duty_cycle_window_active=phase == "dosing",
                requested_runtime_min_per_day=(
                    supplemental_dose.pump_runtime_s / 60.0
                ),
                available_runtime_min_per_day=(
                    (supplemental_dose.cycle_period_s * supplemental_dose.pulse_count)
                    / 60.0
                ),
                cycle_on_seconds=supplemental_dose.pulse_seconds,
                nominal_cycle_on_seconds=supplemental_dose.pulse_seconds,
                cycle_period_seconds=supplemental_dose.cycle_period_s,
                cycle_off_seconds=(
                    supplemental_dose.cycle_period_s
                    - supplemental_dose.pulse_seconds
                ),
                no_dose_last_minutes=(
                    supplemental_dose.no_dose_last_seconds / 60.0
                ),
                current_window_end=estimated_completion_at,
            )
            if current_state != desired_state or needs_on_pulse_command:
                pulse_seconds = (
                    supplemental_dose.on_pulse_seconds(now)
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
                        "controller": "supplemental_chlorine_dose",
                        "phase": phase,
                        "requested_dose_oz": supplemental_dose.requested_dose_oz,
                        "planned_dose_oz": supplemental_dose.planned_dose_oz,
                        "duty_cycle": supplemental_dose.duty_cycle,
                        "pulse_seconds": supplemental_dose.pulse_seconds,
                        "pulse_count": supplemental_dose.pulse_count,
                        "accepted_pulse_count": supplemental_dose.accepted_pulse_count,
                        "cycle_period_s": supplemental_dose.cycle_period_s,
                        "min_cycle_on_seconds": (
                            supplemental_dose.min_cycle_on_seconds
                        ),
                        "min_cycle_on_seconds_overridden": (
                            supplemental_dose.min_cycle_on_seconds_overridden
                        ),
                        ACTUATOR_ON_PULSE_SECONDS_METADATA: pulse_seconds,
                        ACTUATOR_AUTO_OFF_AT_METADATA: (
                            (now + timedelta(seconds=pulse_seconds)).isoformat()
                            if pulse_seconds is not None
                            else None
                        ),
                    },
                )
                result = await self.router.route(
                    command,
                    measurements=safety_measurements,
                )
                results.append(result)
                self._queue_chlorine_delivery_start_snapshot(
                    command=command,
                    result=result,
                )
                if not result.accepted and desired_state == ActuatorState.ON:
                    rejection = result.rejection_reason or "chlorine dose rejected by safety"
                    updated_state = replace(
                        supplemental_dose,
                        last_reason=f"supplemental chlorine dose blocked: {rejection}",
                    )
                    object.__setattr__(self, "supplemental_chlorine_dose", updated_state)
                    supplemental_dose = updated_state
                    status = replace(
                        status,
                        desired_state=ActuatorState.OFF,
                        active=False,
                        reason=f"supplemental chlorine dose blocked: {rejection}",
                        duty_cycle_window_active=False,
                    )
                if result.applied and desired_state == ActuatorState.ON:
                    updated_state = replace(
                        supplemental_dose,
                        dosing_started_at=(
                            supplemental_dose.dosing_started_at
                            if supplemental_dose.dosing_started_at is not None
                            else now
                        ),
                        current_pulse_started_at=now,
                        accepted_pulse_count=supplemental_dose.accepted_pulse_count + 1,
                        last_reason="supplemental chlorine dose active",
                    )
                    object.__setattr__(self, "supplemental_chlorine_dose", updated_state)
                    object.__setattr__(
                        self,
                        "supplemental_chlorine_last_on_cycle_index",
                        current_pulse_index,
                    )
                    supplemental_dose = updated_state
                elif result.applied and desired_state == ActuatorState.OFF:
                    object.__setattr__(
                        self,
                        "supplemental_chlorine_last_on_cycle_index",
                        None,
                    )
            if not results and desired_state == ActuatorState.OFF:
                confirmation = await self._confirm_expired_dosing_flash_off(now)
                if confirmation is not None:
                    results.append(confirmation)

            logged_delivery_count += self._flush_chlorine_delivery_if_inactive()
            return tuple(results), status, logged_delivery_count

        for command in evaluation.commands:
            result = await self.router.route(
                command,
                measurements=safety_measurements,
            )
            results.append(result)
            self._queue_chlorine_delivery_start_snapshot(
                command=command,
                result=result,
            )

        status = evaluation.status
        for command, result in zip(evaluation.commands, results, strict=False):
            if (
                command.actuator_id == ActuatorId.CHLORINE_DOSING_PUMP
                and command.state == ActuatorState.ON
                and not result.accepted
            ):
                status = replace(
                    status,
                    desired_state=ActuatorState.OFF,
                    active=False,
                    reason=result.rejection_reason or "chlorine dose rejected by safety",
                    duty_cycle_window_active=False,
                )
                break

        if not results and evaluation.status.desired_state == ActuatorState.OFF:
            confirmation = await self._confirm_expired_dosing_flash_off(now)
            if confirmation is not None:
                results.append(confirmation)

        logged_delivery_count += self._flush_chlorine_delivery_if_inactive()
        return tuple(results), status, logged_delivery_count

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

    def _queue_chlorine_delivery_start_snapshot(
        self,
        *,
        command: ActuatorCommand,
        result: ActuatorCommandResult,
    ) -> None:
        if self.measurement_logger is None:
            return
        if not result.applied:
            return
        if command.actuator_id != ActuatorId.CHLORINE_DOSING_PUMP:
            return
        if command.state != ActuatorState.ON:
            return
        if command.metadata.get("controller") not in {
            "open_loop_chlorination",
            "supplemental_chlorine_dose",
        }:
            return

        self._queue_chlorine_delivery_snapshot(
            observed_at=command.created_at,
            boundary="start",
        )

    def _queue_due_chlorine_delivery_reset_snapshot(self, now: datetime) -> None:
        if self.measurement_logger is None:
            return

        local_day_start = _local_day_start(
            now,
            timezone_name=self.pump_timer_config.timezone,
        )
        local_day = local_day_start.date().isoformat()
        if self.chlorine_delivery_reset_logged_local_day == local_day:
            return

        object.__setattr__(
            self,
            "chlorine_delivery_reset_logged_local_day",
            local_day,
        )
        self._queue_chlorine_delivery_snapshot(
            observed_at=local_day_start.astimezone(timezone.utc),
            boundary="reset",
        )

    def _queue_chlorine_delivery_snapshot(
        self,
        *,
        observed_at: datetime,
        boundary: str,
    ) -> None:
        point = (observed_at, boundary)
        if point in self.chlorine_delivery_snapshot_points:
            return

        object.__setattr__(
            self,
            "chlorine_delivery_snapshot_points",
            (*self.chlorine_delivery_snapshot_points, point),
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
        self._accumulate_chlorine_delivery_segment(
            started_at=previous,
            ended_at=runtime_end,
            runtime_seconds=runtime_seconds,
            delivered_oz=delivered_oz,
        )
        if self._chlorine_delivery_segment_should_flush(
            sample=sample,
            runtime_end=runtime_end,
            now=now,
        ):
            return self._flush_chlorine_delivery_segment()

        return 0

    def _accumulate_chlorine_delivery_segment(
        self,
        *,
        started_at: datetime,
        ended_at: datetime,
        runtime_seconds: float,
        delivered_oz: float,
    ) -> None:
        segment_started_at = self.chlorine_delivery_segment_started_at
        if segment_started_at is None:
            object.__setattr__(self, "chlorine_delivery_segment_started_at", started_at)

        object.__setattr__(self, "chlorine_delivery_segment_ended_at", ended_at)
        object.__setattr__(
            self,
            "chlorine_delivery_segment_runtime_s",
            self.chlorine_delivery_segment_runtime_s + runtime_seconds,
        )
        object.__setattr__(
            self,
            "chlorine_delivery_segment_delivered_oz",
            self.chlorine_delivery_segment_delivered_oz + delivered_oz,
        )

    def _chlorine_delivery_segment_should_flush(
        self,
        *,
        sample: ActuatorStateSample | None,
        runtime_end: datetime,
        now: datetime,
    ) -> bool:
        if sample is None:
            return False
        if sample.state == ActuatorState.OFF:
            return True

        auto_off_at = _metadata_datetime(sample.metadata.get(ACTUATOR_AUTO_OFF_AT_METADATA))
        return auto_off_at is not None and runtime_end >= auto_off_at and now >= auto_off_at

    def _flush_chlorine_delivery_if_inactive(self) -> int:
        state = self.router.actuator_states.get(ActuatorId.CHLORINE_DOSING_PUMP)
        if state == ActuatorState.ON:
            return 0

        return self._flush_chlorine_delivery_segment()

    def _flush_chlorine_delivery_segment(self) -> int:
        if self.measurement_logger is None:
            return 0

        runtime_seconds = self.chlorine_delivery_segment_runtime_s
        delivered_oz = self.chlorine_delivery_segment_delivered_oz
        if runtime_seconds <= 0 or delivered_oz <= 0:
            return 0

        started_at = self.chlorine_delivery_segment_started_at
        ended_at = self.chlorine_delivery_segment_ended_at or self.clock.now()
        object.__setattr__(self, "chlorine_delivery_segment_started_at", None)
        object.__setattr__(self, "chlorine_delivery_segment_ended_at", None)
        object.__setattr__(self, "chlorine_delivery_segment_runtime_s", 0.0)
        object.__setattr__(self, "chlorine_delivery_segment_delivered_oz", 0.0)

        logged_count = self.measurement_logger.log_chlorine_delivery(
            observed_at=ended_at,
            runtime_seconds=runtime_seconds,
            delivered_oz=delivered_oz,
            metadata={
                "source": "runtime_segment",
                "segment_started_at": started_at.isoformat() if started_at else None,
                "segment_ended_at": ended_at.isoformat(),
                "pump_output_oz_per_min": self.chlorination_config.pump_output_oz_per_min,
            },
        )
        if logged_count:
            self._queue_chlorine_delivery_snapshot(
                observed_at=ended_at,
                boundary="end",
            )

        return logged_count

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
                fc_observations=(),
                automated_chlorine_deliveries=(),
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
                    max_observation_interval_days=(
                        self.fc_demand_config.max_observation_interval_days
                    ),
                    recent_observation_count=(
                        self.fc_demand_config.recent_observation_count
                    ),
                )
            )

        lab_tests = self.measurement_logger.lab_test_history(
            limit=200,
            until=now,
        )
        fc_observations = fc_observations_from_lab_tests(
            config=self.fc_demand_config,
            lab_tests=lab_tests,
            timezone_name=self.pump_timer_config.timezone,
        )
        since = fc_observations[0].sampled_at if fc_observations else None
        until = fc_observations[-1].sampled_at if fc_observations else None
        delivery_records = (
            self.measurement_logger.chlorine_delivery_history(
                since=since,
                until=until,
                limit=5000,
            )
            if since is not None and until is not None
            else ()
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
            fc_observations=fc_observations,
            automated_chlorine_deliveries=tuple(
                ChlorineDeliveryPoint(
                    observed_at=record.observed_at,
                    delivered_oz=record.delivered_oz,
                )
                for record in delivery_records
            ),
            sodium_hypochlorite_additions=sodium_hypochlorite_additions,
        )

    def chlorine_tank_estimate(
        self,
        *,
        observed_at: datetime | None = None,
        include_unflushed_delivery: bool = True,
    ) -> ChlorineTankEstimate | None:
        if self.measurement_logger is None:
            return None

        observed_at = self.clock.now() if observed_at is None else observed_at
        baseline = self.measurement_logger.latest_chlorine_tank_level_test(
            until=observed_at,
        )
        if baseline is None or baseline.chlorine_tank_level_gal is None:
            return None

        delivery = self.measurement_logger.chlorine_delivery_summary(
            since=baseline.sampled_at,
            until=observed_at,
        )
        delivered_oz = max(0.0, delivery.delivered_oz)
        if (
            include_unflushed_delivery
            and self.chlorine_delivery_segment_started_at is not None
            and observed_at >= self.chlorine_delivery_segment_started_at
        ):
            delivered_oz += max(0.0, self.chlorine_delivery_segment_delivered_oz)

        refill_summary = self.measurement_logger.chlorine_tank_refill_summary(
            since=baseline.sampled_at,
            until=observed_at,
        )
        delivered_gal = delivered_oz / FLUID_OUNCES_PER_GALLON
        level_gal = baseline.chlorine_tank_level_gal + refill_summary.amount_gal - delivered_gal

        return ChlorineTankEstimate(
            observed_at=observed_at,
            level_gal=round(level_gal, 4),
            baseline_sampled_at=baseline.sampled_at,
            baseline_level_gal=baseline.chlorine_tank_level_gal,
            delivered_oz=round(delivered_oz, 4),
            delivered_gal=round(delivered_gal, 5),
            refilled_gal=round(refill_summary.amount_gal, 4),
            refill_count=refill_summary.count,
        )

    def safety_measurements(
        self,
        measurements: Iterable[Measurement],
        *,
        observed_at: datetime | None = None,
        source: str,
    ) -> tuple[Measurement, ...]:
        observed_at = self.clock.now() if observed_at is None else observed_at
        result = tuple(measurements)
        level_sensor = self.safety_config.chlorine_tank.level_sensor
        if any(measurement.sensor_id == level_sensor for measurement in result):
            return result
        if level_sensor != SensorId.CHLORINE_TANK_LEVEL_GAL:
            return result

        tank_measurement = self.chlorine_tank_level_measurement(
            observed_at=observed_at,
            source=source,
            extra_metadata={
                "safety_low_warning_gal": self.safety_config.chlorine_tank.low_warning_gal,
                "safety_inhibit_below_gal": (
                    self.safety_config.chlorine_tank.inhibit_below_gal
                ),
                "safety_reenable_at_gal": (
                    self.safety_config.chlorine_tank.reenable_at_gal
                ),
            },
        )
        if tank_measurement is None:
            return result
        return (*result, tank_measurement)

    def chlorine_tank_level_measurement(
        self,
        *,
        observed_at: datetime,
        source: str,
        kind: MeasurementKind = MeasurementKind.ESTIMATED,
        extra_metadata: Mapping[str, Any] | None = None,
    ) -> Measurement | None:
        estimate = self.chlorine_tank_estimate(observed_at=observed_at)
        if estimate is None:
            return None

        metadata = {
            "driver": "chlorine_tank_estimator",
            "source": source,
            **estimate.as_payload(),
        }
        if extra_metadata:
            metadata.update(dict(extra_metadata))

        return Measurement(
            id=(
                f"{SensorId.CHLORINE_TANK_LEVEL_GAL.value}:"
                f"{source}:{observed_at.isoformat()}"
            ),
            sensor_id=SensorId.CHLORINE_TANK_LEVEL_GAL,
            observed_at=observed_at,
            kind=kind,
            value=round(estimate.level_gal, 4),
            unit="gal",
            quality=Quality.GOOD,
            metadata=metadata,
        )

    def chlorine_tank_days_remaining_measurement(
        self,
        *,
        observed_at: datetime,
        source: str,
        daily_dose_oz: float,
        tank_measurement: Measurement | None = None,
    ) -> Measurement | None:
        if tank_measurement is None:
            tank_measurement = self.chlorine_tank_level_measurement(
                observed_at=observed_at,
                source=source,
            )
        if tank_measurement is None or tank_measurement.quality != Quality.GOOD:
            return None

        tank_level_gal = max(0.0, float(tank_measurement.value))
        reserve_gal = self.safety_config.chlorine_tank.forecast_reserve_gal
        remaining_gal = usable_chlorine_gallons(
            tank_level_gal,
            reserve_gal=reserve_gal,
        )
        dose = float(daily_dose_oz)
        if (
            not math.isfinite(tank_level_gal)
            or not math.isfinite(remaining_gal)
            or not math.isfinite(dose)
            or dose <= 0
        ):
            return None

        days_remaining = remaining_gal * FLUID_OUNCES_PER_GALLON / dose
        if not math.isfinite(days_remaining):
            return None

        return Measurement(
            id=(
                f"{SensorId.CHLORINE_TANK_DAYS_REMAINING.value}:"
                f"{source}:{observed_at.isoformat()}"
            ),
            sensor_id=SensorId.CHLORINE_TANK_DAYS_REMAINING,
            observed_at=observed_at,
            kind=MeasurementKind.ESTIMATED,
            value=round(days_remaining, 4),
            unit="days",
            quality=Quality.GOOD,
            metadata={
                "driver": "chlorine_tank_estimator",
                "source": source,
                "remaining_gal": round(remaining_gal, 4),
                "tank_level_gal": round(tank_level_gal, 4),
                "reserve_gal": reserve_gal,
                "daily_dose_oz": dose,
                "tank_measurement_id": tank_measurement.id,
            },
        )

    def log_chlorine_tank_level_snapshot(
        self,
        *,
        observed_at: datetime,
        source: str,
        kind: MeasurementKind = MeasurementKind.ESTIMATED,
        extra_metadata: Mapping[str, Any] | None = None,
    ) -> int:
        measurement = self.chlorine_tank_level_measurement(
            observed_at=observed_at,
            source=source,
            kind=kind,
            extra_metadata=extra_metadata,
        )
        if measurement is None:
            return 0

        return self._log_measurements((measurement,))

    def chlorine_tank_injection_audit(self, test: LabTest) -> dict[str, Any] | None:
        if self.measurement_logger is None or test.chlorine_tank_level_gal is None:
            return None

        current_level_gal = test.chlorine_tank_level_gal
        previous = self.measurement_logger.latest_chlorine_tank_level_test(
            before=test.sampled_at,
        )
        if previous is None or previous.chlorine_tank_level_gal is None:
            return {
                "ready": False,
                "reason": "first tank level reading",
                "current_sampled_at": test.sampled_at.isoformat(),
                "current_level_gal": current_level_gal,
            }

        delivery = self.measurement_logger.chlorine_delivery_summary(
            since=previous.sampled_at,
            until=test.sampled_at,
        )
        refill_summary = self.measurement_logger.chlorine_tank_refill_summary(
            since=previous.sampled_at,
            until=test.sampled_at,
        )
        delivered_oz = max(0.0, delivery.delivered_oz)
        delivered_gal = delivered_oz / FLUID_OUNCES_PER_GALLON
        previous_level_gal = previous.chlorine_tank_level_gal
        expected_level_gal = previous_level_gal + refill_summary.amount_gal - delivered_gal
        inferred_injected_gal = previous_level_gal + refill_summary.amount_gal - current_level_gal
        injection_error_gal = inferred_injected_gal - delivered_gal
        injection_error_percent = (
            (injection_error_gal / delivered_gal) * 100.0
            if delivered_gal > 0
            else None
        )

        return {
            "ready": True,
            "previous_sampled_at": previous.sampled_at.isoformat(),
            "current_sampled_at": test.sampled_at.isoformat(),
            "previous_level_gal": round(previous_level_gal, 4),
            "current_level_gal": round(current_level_gal, 4),
            "refilled_gal": round(refill_summary.amount_gal, 4),
            "refill_count": refill_summary.count,
            "delivered_oz": round(delivered_oz, 4),
            "delivered_gal": round(delivered_gal, 5),
            "expected_level_gal": round(expected_level_gal, 4),
            "inferred_injected_gal": round(inferred_injected_gal, 5),
            "injection_error_gal": round(injection_error_gal, 5),
            "injection_error_percent": (
                round(injection_error_percent, 2)
                if injection_error_percent is not None
                else None
            ),
        }

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

        last_checked_at = self.daily_environment_last_checked_at
        if last_checked_at is not None:
            elapsed_s = (observed_at - last_checked_at).total_seconds()
            if 0 <= elapsed_s < DAILY_ENVIRONMENT_SUMMARY_INTERVAL_S:
                return ()

        object.__setattr__(self, "daily_environment_last_checked_at", observed_at)

        local_day, start_utc, end_utc, summary_observed_at = _completed_local_day_window(
            observed_at,
            timezone_name=self.pump_timer_config.timezone,
        )
        measurements: list[Measurement] = []

        orp_summary = self.measurement_logger.measurement_value_summary(
            sensor_id=SensorId.RAW_ORP,
            since=start_utc,
            until=end_utc,
            qualities=(Quality.GOOD,),
        )
        if orp_summary is not None:
            measurements.append(
                _daily_summary_measurement(
                    sensor_id=SensorId.DAILY_ORP_AVG,
                    observed_at=summary_observed_at,
                    local_day=local_day,
                    timezone_name=self.pump_timer_config.timezone,
                    start_utc=start_utc,
                    end_utc=end_utc,
                    summary=orp_summary,
                    aggregation="avg",
                    value=orp_summary.avg_value,
                    unit=orp_summary.unit or "mV",
                    source="raw_orp",
                )
            )

        water_summary = self.measurement_logger.measurement_value_summary(
            sensor_id=SensorId.WATER_TEMP,
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
                        source="water_temp",
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
                        source="water_temp",
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
                        source="water_temp",
                    ),
                )
            )

        ph_summary = self.measurement_logger.measurement_value_summary(
            sensor_id=SensorId.RAW_PH,
            since=start_utc,
            until=end_utc,
            qualities=(Quality.GOOD,),
        )
        if ph_summary is not None:
            measurements.append(
                _daily_summary_measurement(
                    sensor_id=SensorId.DAILY_PH_AVG,
                    observed_at=summary_observed_at,
                    local_day=local_day,
                    timezone_name=self.pump_timer_config.timezone,
                    start_utc=start_utc,
                    end_utc=end_utc,
                    summary=ph_summary,
                    aggregation="avg",
                    value=ph_summary.avg_value,
                    unit=ph_summary.unit or "pH",
                    source="raw_ph",
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

        measurements.append(
            self._daily_sodium_hypochlorite_added_measurement(
                local_day=local_day,
                start_utc=start_utc,
                end_utc=end_utc,
                observed_at=end_utc,
            )
        )
        measurements.append(
            self._daily_muriatic_acid_added_measurement(
                local_day=local_day,
                start_utc=start_utc,
                end_utc=end_utc,
                observed_at=end_utc,
            )
        )
        measurements.extend(
            self._daily_moving_average_measurements(
                source_measurements=tuple(measurements),
                local_day=local_day,
                timezone_name=self.pump_timer_config.timezone,
            )
        )

        return tuple(measurements)

    def _daily_sodium_hypochlorite_added_measurement(
        self,
        *,
        local_day: str,
        start_utc: datetime,
        end_utc: datetime,
        observed_at: datetime,
    ) -> Measurement:
        if self.measurement_logger is None:
            automated_summary = None
            manual_additions: tuple[ChemicalAddition, ...] = ()
        else:
            automated_summary = self.measurement_logger.chlorine_delivery_summary(
                since=start_utc,
                until=end_utc - timedelta(microseconds=1),
            )
            manual_additions = tuple(
                addition
                for addition in self.measurement_logger.chemical_addition_history(
                    since=start_utc,
                    until=end_utc,
                    limit=1000,
                )
                if (
                    addition.chemical == ChemicalType.SODIUM_HYPOCHLORITE
                    and addition.added_at < end_utc
                )
            )

        automated_oz = (
            max(0.0, automated_summary.delivered_oz)
            if automated_summary is not None
            else 0.0
        )
        automated_runtime_seconds = (
            max(0.0, automated_summary.runtime_seconds)
            if automated_summary is not None
            else 0.0
        )
        manual_hypo_oz = sum(addition.amount_fl_oz for addition in manual_additions)
        automated_added_fc_ppm = fc_ppm_from_fl_oz(
            automated_oz,
            strength_percent=self.fc_demand_config.chlorine_strength_percent,
            pool_volume_gal=self.fc_demand_config.pool_volume_gal,
        )
        manual_added_fc_ppm = sum(
            fc_ppm_from_fl_oz(
                addition.amount_fl_oz,
                strength_percent=addition.strength_percent,
                pool_volume_gal=self.fc_demand_config.pool_volume_gal,
            )
            for addition in manual_additions
        )
        total_oz = automated_oz + manual_hypo_oz

        return Measurement(
            id=f"{SensorId.DAILY_SODIUM_HYPOCHLORITE_ADDED_OZ.value}:{local_day}",
            sensor_id=SensorId.DAILY_SODIUM_HYPOCHLORITE_ADDED_OZ,
            observed_at=observed_at,
            kind=MeasurementKind.ESTIMATED,
            value=round(total_oz, 4),
            unit="fl oz",
            quality=Quality.GOOD,
            metadata={
                "driver": "daily_chlorine_summary",
                "source": "chlorine_delivery,chemical_additions",
                "aggregation": "sum",
                "local_day": local_day,
                "timezone": self.pump_timer_config.timezone,
                "interval_start_utc": start_utc.isoformat(),
                "interval_end_utc": end_utc.isoformat(),
                "automated_delivery_oz": automated_oz,
                "automated_runtime_seconds": automated_runtime_seconds,
                "manual_sodium_hypochlorite_oz": manual_hypo_oz,
                "manual_addition_count": len(manual_additions),
                "automated_added_fc_ppm": automated_added_fc_ppm,
                "manual_added_fc_ppm": manual_added_fc_ppm,
                "total_added_fc_ppm": automated_added_fc_ppm + manual_added_fc_ppm,
                "pool_volume_gal": self.fc_demand_config.pool_volume_gal,
                "automated_chlorine_strength_percent": (
                    self.fc_demand_config.chlorine_strength_percent
                ),
            },
        )

    def _daily_muriatic_acid_added_measurement(
        self,
        *,
        local_day: str,
        start_utc: datetime,
        end_utc: datetime,
        observed_at: datetime,
    ) -> Measurement:
        if self.measurement_logger is None:
            additions: tuple[ChemicalAddition, ...] = ()
        else:
            additions = tuple(
                addition
                for addition in self.measurement_logger.chemical_addition_history(
                    since=start_utc,
                    until=end_utc,
                    limit=1000,
                )
                if addition.chemical == ChemicalType.MURIATIC_ACID
                and addition.added_at < end_utc
            )
        total_oz = sum(addition.amount_fl_oz for addition in additions)

        return Measurement(
            id=f"{SensorId.DAILY_MURIATIC_ACID_ADDED_OZ.value}:{local_day}",
            sensor_id=SensorId.DAILY_MURIATIC_ACID_ADDED_OZ,
            observed_at=observed_at,
            kind=MeasurementKind.ESTIMATED,
            value=round(total_oz, 4),
            unit="fl oz",
            quality=Quality.GOOD,
            metadata={
                "driver": "daily_chemical_summary",
                "source": "chemical_additions",
                "aggregation": "sum",
                "local_day": local_day,
                "timezone": self.pump_timer_config.timezone,
                "interval_start_utc": start_utc.isoformat(),
                "interval_end_utc": end_utc.isoformat(),
                "manual_muriatic_acid_oz": total_oz,
                "manual_addition_count": len(additions),
            },
        )

    def _daily_moving_average_measurements(
        self,
        *,
        source_measurements: tuple[Measurement, ...],
        local_day: str,
        timezone_name: str,
    ) -> tuple[Measurement, ...]:
        if self.measurement_logger is None:
            return ()

        current_by_sensor = {
            measurement.sensor_id: measurement
            for measurement in source_measurements
            if measurement.sensor_id in DAILY_MOVING_AVERAGE_SENSOR_IDS
        }
        measurements: list[Measurement] = []
        for source_sensor_id, target_by_window in DAILY_MOVING_AVERAGE_SENSOR_IDS.items():
            current = current_by_sensor.get(source_sensor_id)
            if current is None:
                continue

            for window_days in DAILY_MOVING_AVERAGE_WINDOWS:
                target_sensor_id = target_by_window[window_days]
                since = current.observed_at - timedelta(days=window_days - 1)
                previous_records = self.measurement_logger.history(
                    sensor_id=source_sensor_id,
                    since=since,
                    until=current.observed_at - timedelta(microseconds=1),
                    limit=window_days,
                    qualities=(Quality.GOOD,),
                )
                source_values = [record.value for record in previous_records]
                source_values.append(current.value)
                source_count = len(source_values)
                if source_count <= 0:
                    continue

                avg_value = sum(source_values) / source_count
                measurements.append(
                    Measurement(
                        id=f"{target_sensor_id.value}:{local_day}",
                        sensor_id=target_sensor_id,
                        observed_at=current.observed_at,
                        kind=MeasurementKind.ESTIMATED,
                        value=round(avg_value, 4),
                        unit=current.unit,
                        quality=Quality.GOOD,
                        source_measurement_ids=[
                            *(record.measurement_id for record in previous_records),
                            current.id,
                        ],
                        metadata={
                            "driver": "daily_moving_average_summary",
                            "source": source_sensor_id.value,
                            "aggregation": "moving_avg",
                            "window_days": window_days,
                            "source_sample_count": source_count,
                            "local_day": local_day,
                            "timezone": timezone_name,
                            "window_start": since.isoformat(),
                            "window_end": current.observed_at.isoformat(),
                        },
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
            duty_cycle_quality = Quality.GOOD
            if (
                fc_demand_status is not None
                and fc_demand_status.demand_observation_quality is not None
                and fc_demand_status.demand_observation_quality.value == "suspect"
            ):
                duty_cycle_quality = Quality.SUSPECT

            measurements.append(
                Measurement(
                    sensor_id=SensorId.CHLORINATION_DUTY_CYCLE_PERCENT,
                    observed_at=observed_at,
                    kind=MeasurementKind.ESTIMATED,
                    value=round(chlorination_status.duty_cycle * 100.0, 3),
                    unit="percent",
                    quality=duty_cycle_quality,
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

        if self.chlorine_delivery_snapshot_points and self.measurement_logger is not None:
            snapshot_points = self.chlorine_delivery_snapshot_points
            object.__setattr__(self, "chlorine_delivery_snapshot_points", ())
            for snapshot_observed_at, boundary in snapshot_points:
                local_day_start = _local_day_start(
                    snapshot_observed_at,
                    timezone_name=self.pump_timer_config.timezone,
                ).astimezone(timezone.utc)
                daily_delivery = self.measurement_logger.chlorine_delivery_summary(
                    since=local_day_start,
                    until=snapshot_observed_at,
                )
                measurements.append(
                    Measurement(
                        id=(
                            f"{SensorId.CHLORINE_DAILY_DELIVERED_OZ.value}:"
                            f"{boundary}:{snapshot_observed_at.isoformat()}"
                        ),
                        sensor_id=SensorId.CHLORINE_DAILY_DELIVERED_OZ,
                        observed_at=snapshot_observed_at,
                        kind=MeasurementKind.ESTIMATED,
                        value=round(daily_delivery.delivered_oz, 3),
                        unit="fl oz",
                        quality=Quality.GOOD,
                        metadata={
                            "driver": "chlorination_controller",
                            "source": "chlorine_delivery",
                            "snapshot_boundary": boundary,
                            "local_day_start": local_day_start.isoformat(),
                            "runtime_seconds_today": daily_delivery.runtime_seconds,
                        },
                    )
                )
                tank_measurement = self.chlorine_tank_level_measurement(
                    observed_at=snapshot_observed_at,
                    source=f"chlorine_delivery_{boundary}",
                    extra_metadata={"snapshot_boundary": boundary},
                )
                if tank_measurement is not None:
                    measurements.append(tank_measurement)

        if (
            fc_demand_status is not None
            and fc_demand_status.ready
            and fc_demand_status.daily_demand_ppm is not None
        ):
            fc_demand_measurement_id = _fc_demand_measurement_id(fc_demand_status)
            if fc_demand_measurement_id == self.fc_demand_last_logged_measurement_id:
                return tuple(measurements)

            measurements.append(
                Measurement(
                    id=fc_demand_measurement_id,
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
                        "max_observation_interval_days": (
                            fc_demand_status.max_observation_interval_days
                        ),
                        "recent_observation_count": (
                            fc_demand_status.recent_observation_count
                        ),
                        "observation_count": fc_demand_status.observation_count,
                        "confidence": fc_demand_status.confidence,
                        "added_fc_ppm": fc_demand_status.added_fc_ppm,
                        "consumed_fc_ppm": fc_demand_status.consumed_fc_ppm,
                        "raw_demand_ppm_per_day": (
                            fc_demand_status.raw_demand_ppm_per_day
                        ),
                        "accepted_demand_ppm_per_day": (
                            fc_demand_status.accepted_demand_ppm_per_day
                        ),
                        "demand_observation_quality": (
                            fc_demand_status.demand_observation_quality.value
                            if fc_demand_status.demand_observation_quality
                            is not None
                            else None
                        ),
                        "demand_observation_rejection_reason": (
                            fc_demand_status.demand_observation_rejection_reason
                        ),
                        "latest_observed_demand_ppm_per_day": (
                            fc_demand_status.latest_observed_demand_ppm_per_day
                        ),
                        "baseline_demand_ppm_per_day": (
                            fc_demand_status.baseline_demand_ppm_per_day
                        ),
                        "weighted_maintenance_demand_ppm_per_day": (
                            fc_demand_status.weighted_maintenance_demand_ppm_per_day
                        ),
                        "rate_limited_baseline_demand_ppm_per_day": (
                            fc_demand_status.rate_limited_baseline_demand_ppm_per_day
                        ),
                        "weather_adjustment_ppm_per_day": (
                            fc_demand_status.weather_adjustment_ppm_per_day
                        ),
                        "predicted_demand_ppm_per_day": (
                            fc_demand_status.predicted_demand_ppm_per_day
                        ),
                        "latest_fc_observation_timing": (
                            fc_demand_status.latest_fc_observation_timing.value
                            if fc_demand_status.latest_fc_observation_timing
                            is not None
                            else None
                        ),
                        "latest_reference_fc_sampled_at": (
                            fc_demand_status.latest_reference_fc_sampled_at.isoformat()
                            if fc_demand_status.latest_reference_fc_sampled_at
                            is not None
                            else None
                        ),
                        "preferred_test_start_hour": (
                            fc_demand_status.preferred_test_start_hour
                        ),
                        "preferred_test_end_hour": (
                            fc_demand_status.preferred_test_end_hour
                        ),
                        "maintenance_dose_oz_per_day": (
                            fc_demand_status.maintenance_dose_oz_per_day
                        ),
                        "unlimited_maintenance_dose_oz_per_day": (
                            fc_demand_status.unlimited_maintenance_dose_oz_per_day
                        ),
                        "maintenance_rate_limited": (
                            fc_demand_status.maintenance_rate_limited
                        ),
                        "feedback_fc_ppm": fc_demand_status.feedback_fc_ppm,
                        "feedback_dose_oz": fc_demand_status.feedback_dose_oz,
                        "applied_feedback_dose_oz": (
                            fc_demand_status.applied_feedback_dose_oz
                        ),
                        "feedback_active_today": (
                            fc_demand_status.feedback_active_today
                        ),
                        "recommended_daily_dose_oz": (
                            fc_demand_status.recommended_daily_dose_oz
                        ),
                        "effective_daily_dose_oz": (
                            fc_demand_status.effective_daily_dose_oz
                        ),
                        "final_dose_capped": fc_demand_status.final_dose_capped,
                        "final_dose_floor_limited": (
                            fc_demand_status.final_dose_floor_limited
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
            object.__setattr__(
                self,
                "fc_demand_last_logged_measurement_id",
                fc_demand_measurement_id,
            )

        return tuple(measurements)

    def _loggable_chlorination_control_measurements(
        self,
        *,
        measurements: tuple[Measurement, ...],
        chlorination_status: ChlorinationStatus | None,
        observed_at: datetime,
    ) -> tuple[Measurement, ...]:
        """
        Return controller-state measurements that are due for database logging.

        Chlorination status is still produced every tick for live publication,
        but the history table should not receive one row per 0.25 second control
        loop pass. At that rate the history API's row cap shows only the newest
        slice of a long dosing window. We keep these graph snapshots sparse and
        stable by logging immediately on important state/config changes, then at
        a configured heartbeat while the state remains unchanged.
        """
        duty_cycle_measurements = tuple(
            measurement
            for measurement in measurements
            if measurement.sensor_id == SensorId.CHLORINATION_DUTY_CYCLE_PERCENT
        )
        delivery_measurements = tuple(
            measurement
            for measurement in measurements
            if measurement.sensor_id == SensorId.CHLORINE_DAILY_DELIVERED_OZ
        )
        other_measurements = tuple(
            measurement
            for measurement in measurements
            if measurement.sensor_id not in CHLORINATION_CONTROL_SENSOR_IDS
        )

        if not duty_cycle_measurements:
            return other_measurements + delivery_measurements

        if self._chlorination_control_log_due(
            chlorination_status=chlorination_status,
            observed_at=observed_at,
        ):
            return other_measurements + delivery_measurements + duty_cycle_measurements

        return other_measurements + delivery_measurements

    def _chlorination_control_log_due(
        self,
        *,
        chlorination_status: ChlorinationStatus | None,
        observed_at: datetime,
    ) -> bool:
        interval_s = self.measurement_logging_config.control_measurement_interval_s
        signature = self._chlorination_control_log_signature(chlorination_status)
        last_logged_at = self.chlorination_control_last_logged_at
        last_signature = self.chlorination_control_last_signature
        elapsed_s = (
            None
            if last_logged_at is None
            else (observed_at - last_logged_at).total_seconds()
        )

        due = (
            last_logged_at is None
            or elapsed_s is None
            or elapsed_s < 0
            or elapsed_s >= interval_s
            or signature != last_signature
        )
        if due:
            object.__setattr__(
                self,
                "chlorination_control_last_logged_at",
                observed_at,
            )
            object.__setattr__(
                self,
                "chlorination_control_last_signature",
                signature,
            )

        return due

    def _chlorination_control_log_signature(
        self,
        chlorination_status: ChlorinationStatus | None,
    ) -> tuple[Any, ...]:
        dosing_state = self.router.actuator_states.get(ActuatorId.CHLORINE_DOSING_PUMP)
        dosing_state_value = dosing_state.value if dosing_state is not None else None
        if chlorination_status is None:
            return ("no_status", dosing_state_value)

        return (
            chlorination_status.enabled,
            dosing_state_value,
            chlorination_status.desired_state.value,
            chlorination_status.active,
            chlorination_status.reason,
            round(chlorination_status.daily_dose_oz, 3),
            round(chlorination_status.base_daily_dose_oz, 3),
            round(chlorination_status.duty_cycle, 6),
            chlorination_status.duty_cycle_limited,
            round(chlorination_status.cycle_on_seconds, 3),
            (
                None
                if chlorination_status.cycle_off_seconds is None
                else round(chlorination_status.cycle_off_seconds, 3)
            ),
            (
                None
                if chlorination_status.cycle_period_seconds is None
                else round(chlorination_status.cycle_period_seconds, 3)
            ),
            chlorination_status.eligible_window_active,
            chlorination_status.duty_cycle_window_active,
            chlorination_status.dose_adjustment_source,
            chlorination_status.dose_adjustment_reason,
            round(chlorination_status.delay_eligible_minutes, 3),
        )

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
                "source": "raw_ph,water_temp,lab_tests",
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

    router = CommandRouter(
        drivers=built_actuator_drivers,
        safety_gate=SafetyGate(
            safety_config,
            chlorine_pump_stabilization_seconds=(
                chlorination_config.no_dose_first_minutes * 60.0
            ),
        ),
        clock=built_clock,
    )

    acquisition_service = AcquisitionService(
        config=acquisition_config,
        clock=built_clock,
        sensor_drivers=built_sensor_drivers,
        multi_sensor_drivers=built_multi_sensor_drivers,
    )
    pump_timer = PumpTimer(pump_timer_config)
    chlorination_controller = ChlorinationController(chlorination_config)
    measurement_logger = MeasurementLogger(measurement_logging_config)
    filter_loading_estimator = FilterLoadingEstimator(
        flow_estimation_config.filter_loading,
        pump_pressure_model=flow_estimation_config.pump_pressure_model,
    )

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
        flow_estimation_config=flow_estimation_config,
        filter_loading_estimator=filter_loading_estimator,
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
    raw_demand = (
        f"{status.raw_demand_ppm_per_day:.4f}"
        if status.raw_demand_ppm_per_day is not None
        else "none"
    )
    quality = (
        status.demand_observation_quality.value
        if status.demand_observation_quality is not None
        else "unknown"
    )
    return f"fc_demand_ppm_per_day:{previous}:{current}:{demand}:{raw_demand}:{quality}"


def _fc_demand_trend_measurements(
    *,
    logger: MeasurementLogger | None,
    status: FcDemandStatus,
    observed_at: datetime,
) -> tuple[Measurement, ...]:
    if status.daily_demand_ppm is None:
        return ()

    actual_demand = float(status.daily_demand_ppm)
    base_demand = (
        status.baseline_demand_ppm_per_day
        if status.baseline_demand_ppm_per_day is not None
        else status.weighted_maintenance_demand_ppm_per_day
    )
    if base_demand is None:
        base_demand = actual_demand
    weather_adjustment = status.weather_adjustment_ppm_per_day
    predicted_demand = (
        status.predicted_demand_ppm_per_day
        if status.predicted_demand_ppm_per_day is not None
        else actual_demand
    )
    residual = actual_demand - predicted_demand
    source_measurement_id = _fc_demand_measurement_id(status)
    source_suffix = source_measurement_id.removeprefix("fc_demand_ppm_per_day:")
    quality = (
        Quality.SUSPECT
        if status.demand_observation_quality is not None
        and status.demand_observation_quality.value == "suspect"
        else Quality.GOOD
    )
    metadata = {
        "driver": "fc_demand_trend",
        "source": "fc_demand_ppm_per_day",
        "source_measurement_id": source_measurement_id,
        "actual_fc_demand_ppm_per_day": actual_demand,
        "raw_demand_ppm_per_day": status.raw_demand_ppm_per_day,
        "accepted_demand_ppm_per_day": status.accepted_demand_ppm_per_day,
        "demand_observation_quality": (
            status.demand_observation_quality.value
            if status.demand_observation_quality is not None
            else None
        ),
        "demand_observation_rejection_reason": (
            status.demand_observation_rejection_reason
        ),
        "baseline_demand_ppm_per_day": base_demand,
        "weighted_maintenance_demand_ppm_per_day": base_demand,
        "rate_limited_baseline_demand_ppm_per_day": (
            status.rate_limited_baseline_demand_ppm_per_day
        ),
        "weather_adjustment_ppm_per_day": weather_adjustment,
        "predicted_fc_demand_ppm_per_day": predicted_demand,
        "max_observation_interval_days": status.max_observation_interval_days,
        "recent_observation_count": status.recent_observation_count,
        "observation_count": status.observation_count,
        "effective_normalized_weights": list(status.effective_normalized_weights),
        "modifier_model": "phase_1_weather_adjustment_zero",
        "water_temp_source": SensorId.WATER_TEMP.value,
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
            quality=quality,
            source_measurement_ids=[source_measurement_id],
            metadata={
                **metadata,
                "meaning": "recent weighted baseline FC demand",
            },
        ),
        Measurement(
            id=(
                f"{SensorId.FC_DEMAND_WEATHER_ADJUSTMENT_PPM_PER_DAY.value}:"
                f"{source_suffix}"
            ),
            sensor_id=SensorId.FC_DEMAND_WEATHER_ADJUSTMENT_PPM_PER_DAY,
            observed_at=observed_at,
            kind=MeasurementKind.ESTIMATED,
            value=round(weather_adjustment, 4),
            unit="ppm/day",
            quality=quality,
            source_measurement_ids=[source_measurement_id],
            metadata={
                **metadata,
                "meaning": "Phase 1 weather adjustment, intentionally zero",
            },
        ),
        Measurement(
            id=f"{SensorId.PREDICTED_FC_DEMAND_PPM_PER_DAY.value}:{source_suffix}",
            sensor_id=SensorId.PREDICTED_FC_DEMAND_PPM_PER_DAY,
            observed_at=observed_at,
            kind=MeasurementKind.ESTIMATED,
            value=round(predicted_demand, 4),
            unit="ppm/day",
            quality=quality,
            source_measurement_ids=[source_measurement_id],
            metadata={
                **metadata,
                "meaning": "baseline demand plus weather adjustment",
            },
        ),
        Measurement(
            id=f"{SensorId.FC_DEMAND_RESIDUAL_PPM_PER_DAY.value}:{source_suffix}",
            sensor_id=SensorId.FC_DEMAND_RESIDUAL_PPM_PER_DAY,
            observed_at=observed_at,
            kind=MeasurementKind.ESTIMATED,
            value=round(residual, 4),
            unit="ppm/day",
            quality=quality,
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
    filter_result = flow_estimates.filter_loading.result
    if (
        filter_result is not None
        and flow_estimates.filter_loading.completed_this_tick
    ):
        measurements.append(
            Measurement(
                sensor_id=SensorId.FILTER_REFERENCE_PSI,
                observed_at=filter_result.completed_at,
                kind=MeasurementKind.ESTIMATED,
                value=round(filter_result.reference_psi, 4),
                unit="psi",
                quality=Quality.GOOD,
                metadata={
                    "driver": "filter_loading",
                    "source": "standardized_pump_output_psi",
                    "sample_count": filter_result.sample_count,
                    "averaging_seconds": filter_result.averaging_seconds,
                },
            )
        )
        measurements.append(
            Measurement(
                sensor_id=SensorId.FILTER_REFERENCE_FLOW_GPM,
                observed_at=filter_result.completed_at,
                kind=MeasurementKind.ESTIMATED,
                value=round(filter_result.estimated_flow_gpm, 4),
                unit="gpm",
                quality=Quality.GOOD,
                metadata={
                    "driver": "filter_loading",
                    "source": "filter_reference_psi",
                    "sample_count": filter_result.sample_count,
                    "averaging_seconds": filter_result.averaging_seconds,
                },
            )
        )
        if filter_result.raw_flow_loss_percent is not None:
            measurements.append(
                Measurement(
                    sensor_id=SensorId.FILTER_FLOW_LOSS_PERCENT,
                    observed_at=filter_result.completed_at,
                    kind=MeasurementKind.ESTIMATED,
                    value=round(filter_result.raw_flow_loss_percent, 4),
                    unit="percent",
                    quality=Quality.GOOD,
                    metadata={
                        "driver": "filter_loading",
                        "source": "filter_reference_flow_gpm",
                        "display_flow_loss_percent": filter_result.flow_loss_percent,
                        "clean_flow_gpm": filter_result.clean_flow_gpm,
                        "sample_count": filter_result.sample_count,
                        "averaging_seconds": filter_result.averaging_seconds,
                    },
                )
            )

    return tuple(measurements)
