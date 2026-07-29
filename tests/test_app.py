"""
Tests for the composed PoolControllerApp runtime.

This file exercises whole-application behavior: building from config, ticking
services together, logging derived values, weather polling, and MQTT inputs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from poolctl.app import _chlorine_runtime_end_from_sample, build_app_from_mapping
from poolctl.config import DriverProfile, FeatureLayer, RuntimeStage
from poolctl.domain.models import (
    ACTUATOR_AUTO_OFF_AT_METADATA,
    ACTUATOR_ON_PULSE_SECONDS_METADATA,
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
from poolctl.drivers.simulated.actuators import build_default_simulated_actuators
from poolctl.drivers.simulated.plant import SimulatedPlant
from poolctl.services.clock import SimulatedClock
import poolctl.services.weather as weather_service_module


class PulseAwareDosingActuator:
    name = "pulse_aware_dosing"
    actuator_id = ActuatorId.CHLORINE_DOSING_PUMP

    def __init__(self, clock: SimulatedClock) -> None:
        self._clock = clock
        self.state = ActuatorState.OFF
        self.commands: list[ActuatorCommand] = []
        self.last_metadata: dict[str, object] = {}

    async def apply(self, command: ActuatorCommand) -> ActuatorStateSample:
        self.commands.append(command)
        self.state = command.state
        self.last_metadata = {}
        if command.state == ActuatorState.ON:
            auto_off_at = command.metadata.get(ACTUATOR_AUTO_OFF_AT_METADATA)
            self.last_metadata = {
                ACTUATOR_AUTO_OFF_AT_METADATA: auto_off_at,
            }

        return ActuatorStateSample(
            actuator_id=self.actuator_id,
            observed_at=self._clock.now(),
            state=self.state,
            source_command_id=command.id,
            metadata={
                "driver": self.name,
                **self.last_metadata,
            },
        )

    async def read_state(self) -> ActuatorStateSample:
        return ActuatorStateSample(
            actuator_id=self.actuator_id,
            observed_at=self._clock.now(),
            state=self.state,
            metadata={
                "driver": self.name,
                **self.last_metadata,
            },
        )

    async def stop(self) -> ActuatorStateSample:
        self.state = ActuatorState.OFF
        return await self.read_state()


class FixedSensor:
    def __init__(
        self,
        *,
        name: str,
        sensor_id: SensorId,
        clock: SimulatedClock,
        value: float,
        unit: str = "psi",
    ) -> None:
        self.name = name
        self.sensor_id = sensor_id
        self._clock = clock
        self._value = value
        self._unit = unit

    async def read(self) -> Measurement:
        return Measurement(
            sensor_id=self.sensor_id,
            observed_at=self._clock.now(),
            value=self._value,
            unit=self._unit,
            quality=Quality.GOOD,
            metadata={"driver": self.name},
        )


def make_clock() -> SimulatedClock:
    return SimulatedClock(
        start_at=datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc),
        speedup=3600.0,
    )


def minimal_acquisition_config() -> dict[str, object]:
    return {
        "acquisition": {
            "groups": {
                "pressures": {
                    "sensor_ids": ["pump_output_psi"],
                    "read_interval_s": 0.5,
                    "log_interval_s": 30.0,
                    "requires_pump_flow": False,
                    "oversample": {
                        "sample_count": 1,
                        "sample_interval_s": 0.0,
                        "reducer": "last",
                    },
                }
            }
        }
    }


def active_pump_timer_config() -> dict[str, object]:
    return {
        "pump_timer": {
            "schedules": [
                {
                    "name": "all_day_filter",
                    "start": "00:00",
                    "end": "00:00",
                    "pump_speed": "high",
                    "booster": "off",
                }
            ]
        }
    }


def simulated_runtime_config() -> dict[str, object]:
    return {
        "runtime": {
            "stage": "windows_simulation",
            "driver_profile": "simulated",
            "enabled_layers": ["acquisition", "safety_enforcement"],
            "enabled_actuators": [
                "pump_motor",
                "pump_motor_speed",
                "booster_pump",
                "chlorine_dosing_pump",
            ],
            "enabled_sensor_groups": ["pressures"],
        }
    }


@pytest.mark.asyncio
async def test_build_simulated_app_wires_acquisition_and_router() -> None:
    clock = make_clock()
    config = {
        **simulated_runtime_config(),
        **minimal_acquisition_config(),
    }

    app = build_app_from_mapping(config, clock=clock)
    result = await app.tick(force_acquisition=True)

    assert app.runtime_config.stage == RuntimeStage.WINDOWS_SIMULATION
    assert app.runtime_config.driver_profile == DriverProfile.SIMULATED
    assert app.runtime_config.layer_enabled(FeatureLayer.ACQUISITION)
    assert app.acquisition_service is not None
    assert app.simulated_plant is not None
    assert result.acquisition.group_names == ("pressures",)
    assert [measurement.sensor_id for measurement in result.measurements] == [
        SensorId.PUMP_OUTPUT_PSI
    ]


@pytest.mark.asyncio
async def test_open_loop_timer_stage_can_run_without_acquisition() -> None:
    clock = make_clock()
    config = {
        "runtime": {
            "stage": "open_loop_timer",
            "driver_profile": "simulated",
            "enabled_layers": ["pump_timer", "safety_enforcement"],
            "enabled_actuators": [
                "pump_motor",
                "pump_motor_speed",
                "booster_pump",
            ],
            "enabled_sensor_groups": [],
        },
        **active_pump_timer_config(),
    }

    app = build_app_from_mapping(config, clock=clock)
    result = await app.tick()

    assert app.acquisition_service is None
    assert result.measurements == ()
    assert result.loggable_measurements == ()
    assert len(result.timer_results) == 2
    assert app.router.actuator_states[ActuatorId.PUMP_MOTOR] == ActuatorState.ON
    assert app.router.actuator_states[ActuatorId.PUMP_MOTOR_SPEED] == ActuatorState.HIGH

    await clock.advance(31.0)
    later_result = await app.tick()

    assert later_result.safety_results == ()
    assert not app.router.safety_gate.locked_out

    chlorine_result = await app.router.route(
        ActuatorCommand(
            actuator_id=ActuatorId.CHLORINE_DOSING_PUMP,
            created_at=clock.now(),
            state=ActuatorState.ON,
            requested_by=CommandSource.MANUAL,
            reason="should not be available in open loop timer stage",
        )
    )

    assert not chlorine_result.accepted
    assert chlorine_result.rejection_reason == (
        "no driver registered for chlorine_dosing_pump"
    )


@pytest.mark.asyncio
async def test_tick_runs_open_loop_chlorination_after_pump_timer() -> None:
    clock = make_clock()
    config = {
        "runtime": {
            "stage": "open_loop_timer",
            "driver_profile": "simulated",
            "enabled_layers": ["pump_timer", "chlorination"],
            "enabled_actuators": [
                "pump_motor",
                "pump_motor_speed",
                "booster_pump",
                "chlorine_dosing_pump",
            ],
            "enabled_sensor_groups": [],
        },
        "pump_timer": {
            "timezone": "UTC",
            "schedules": [
                {
                    "name": "midday_filter",
                    "start": "12:00",
                    "end": "14:00",
                    "pump_speed": "low",
                    "booster": "off",
                }
            ],
        },
        "chlorination": {
            "enabled": True,
            "daily_dose_oz": 4.0,
            "pump_output_oz_per_min": 1.0,
            "no_dose_last_minutes": 10.0,
            "max_duty_cycle": 0.5,
            "cycle_on_seconds": 60.0,
        },
    }

    app = build_app_from_mapping(config, clock=clock)
    result = await app.tick()

    assert app.router.actuator_states[ActuatorId.PUMP_MOTOR] == ActuatorState.ON
    assert app.router.actuator_states[ActuatorId.PUMP_MOTOR_SPEED] == ActuatorState.LOW
    assert app.router.actuator_states[ActuatorId.CHLORINE_DOSING_PUMP] == ActuatorState.ON
    assert result.chlorination_status is not None
    assert result.chlorination_status.active is True
    assert len(result.chlorination_results) == 1
    assert result.chlorination_results[0].applied is True


@pytest.mark.asyncio
async def test_tick_confirms_dosing_flash_off_after_auto_off_expires() -> None:
    clock = make_clock()
    plant = SimulatedPlant(clock=clock)
    dosing_driver = PulseAwareDosingActuator(clock)
    config = {
        "runtime": {
            "stage": "open_loop_timer",
            "driver_profile": "simulated",
            "enabled_layers": ["pump_timer", "chlorination"],
            "enabled_actuators": [
                "pump_motor",
                "pump_motor_speed",
                "chlorine_dosing_pump",
            ],
            "enabled_sensor_groups": [],
        },
        "pump_timer": {
            "timezone": "UTC",
            "schedules": [
                {
                    "name": "midday_filter",
                    "start": "12:00",
                    "end": "14:00",
                    "pump_speed": "low",
                    "booster": "off",
                }
            ],
        },
        "chlorination": {
            "enabled": True,
            "daily_dose_oz": 4.0,
            "pump_output_oz_per_min": 1.0,
            "no_dose_last_minutes": 10.0,
            "max_duty_cycle": 0.5,
            "cycle_on_seconds": 60.0,
        },
    }
    actuator_drivers = [
        driver
        for driver in build_default_simulated_actuators(plant)
        if driver.actuator_id != ActuatorId.CHLORINE_DOSING_PUMP
    ]
    actuator_drivers.append(dosing_driver)
    app = build_app_from_mapping(config, clock=clock, actuator_drivers=actuator_drivers)

    first = await app.tick()
    await clock.advance(60.1)
    second = await app.tick()

    assert first.chlorination_results[0].metadata["driver"] == dosing_driver.name
    assert dosing_driver.commands[0].state == ActuatorState.ON
    assert dosing_driver.commands[0].metadata[ACTUATOR_ON_PULSE_SECONDS_METADATA] == 60.0
    assert dosing_driver.commands[1].state == ActuatorState.OFF
    assert dosing_driver.commands[1].reason == "confirm dosing relay off after timed flash"
    assert len(second.chlorination_results) == 1
    assert second.chlorination_results[0].applied is True


@pytest.mark.asyncio
async def test_tick_logs_chlorine_delivery_when_dosing_pulse_finishes(
    tmp_path: Path,
) -> None:
    clock = make_clock()
    plant = SimulatedPlant(clock=clock)
    dosing_driver = PulseAwareDosingActuator(clock)
    config = {
        "runtime": {
            "stage": "open_loop_timer",
            "driver_profile": "simulated",
            "enabled_layers": ["pump_timer", "chlorination", "logging"],
            "enabled_actuators": [
                "pump_motor",
                "pump_motor_speed",
                "booster_pump",
                "chlorine_dosing_pump",
            ],
            "enabled_sensor_groups": [],
        },
        "logging": {
            "database_path": str(tmp_path / "chlorine_delivery.sqlite3"),
        },
        "pump_timer": {
            "timezone": "UTC",
            "schedules": [
                {
                    "name": "midday_filter",
                    "start": "12:00",
                    "end": "14:00",
                    "pump_speed": "low",
                    "booster": "off",
                }
            ],
        },
        "chlorination": {
            "enabled": True,
            "daily_dose_oz": 4.0,
            "pump_output_oz_per_min": 1.0,
            "no_dose_last_minutes": 10.0,
            "max_duty_cycle": 0.5,
            "cycle_on_seconds": 60.0,
        },
    }
    actuator_drivers = [
        driver
        for driver in build_default_simulated_actuators(plant)
        if driver.actuator_id != ActuatorId.CHLORINE_DOSING_PUMP
    ]
    actuator_drivers.append(dosing_driver)

    start = clock.now()
    app = build_app_from_mapping(config, clock=clock, actuator_drivers=actuator_drivers)
    first = await app.tick()
    await clock.advance(30.0)
    second = await app.tick()
    await clock.advance(30.1)
    third = await app.tick()

    assert first.logged_chlorine_delivery_count == 0
    assert second.logged_chlorine_delivery_count == 0
    assert third.logged_chlorine_delivery_count == 1
    assert app.measurement_logger is not None
    summary = app.measurement_logger.chlorine_delivery_summary()
    assert round(summary.runtime_seconds, 3) == 60.0
    assert round(summary.delivered_oz, 3) == 1.0
    duty_records = app.measurement_logger.history(
        sensor_id=SensorId.CHLORINATION_DUTY_CYCLE_PERCENT,
        limit=10,
    )
    cumulative_records = app.measurement_logger.history(
        sensor_id=SensorId.CHLORINE_DAILY_DELIVERED_OZ,
        limit=10,
    )

    assert len(duty_records) == 3
    assert round(duty_records[-1].value, 3) == 3.636
    assert duty_records[-1].unit == "percent"
    assert len(cumulative_records) == 3
    assert [record.observed_at for record in cumulative_records] == [
        datetime(2026, 5, 21, tzinfo=timezone.utc),
        start,
        start + timedelta(seconds=60),
    ]
    assert [round(record.value, 3) for record in cumulative_records] == [0.0, 0.0, 1.0]
    assert cumulative_records[-1].unit == "fl oz"
    assert cumulative_records[0].metadata["snapshot_boundary"] == "reset"
    assert cumulative_records[1].metadata["snapshot_boundary"] == "start"
    assert cumulative_records[-1].metadata["snapshot_boundary"] == "end"

    await clock.advance(1589.9)
    fourth = await app.tick()
    assert fourth.logged_chlorine_delivery_count == 0
    cumulative_records = app.measurement_logger.history(
        sensor_id=SensorId.CHLORINE_DAILY_DELIVERED_OZ,
        limit=10,
    )

    assert len(cumulative_records) == 4
    assert cumulative_records[-1].observed_at == start + timedelta(seconds=1650)
    assert round(cumulative_records[-1].value, 3) == 1.0
    assert cumulative_records[-1].metadata["snapshot_boundary"] == "start"


@pytest.mark.asyncio
async def test_chlorination_control_history_is_throttled_between_state_changes(
    tmp_path: Path,
) -> None:
    clock = make_clock()
    plant = SimulatedPlant(clock=clock)
    dosing_driver = PulseAwareDosingActuator(clock)
    config = {
        "runtime": {
            "stage": "open_loop_timer",
            "driver_profile": "simulated",
            "enabled_layers": ["pump_timer", "chlorination", "logging"],
            "enabled_actuators": [
                "pump_motor",
                "pump_motor_speed",
                "booster_pump",
                "chlorine_dosing_pump",
            ],
            "enabled_sensor_groups": [],
        },
        "logging": {
            "database_path": str(tmp_path / "chlorine_control.sqlite3"),
            "control_measurement_interval_s": 30.0,
        },
        "pump_timer": {
            "timezone": "UTC",
            "schedules": [
                {
                    "name": "midday_filter",
                    "start": "12:00",
                    "end": "14:00",
                    "pump_speed": "low",
                    "booster": "off",
                    "allow_dosing": True,
                }
            ],
        },
        "chlorination": {
            "enabled": True,
            "daily_dose_oz": 4.0,
            "pump_output_oz_per_min": 1.0,
            "no_dose_last_minutes": 10.0,
            "max_duty_cycle": 0.5,
            "cycle_on_seconds": 60.0,
        },
    }

    actuator_drivers = [
        driver
        for driver in build_default_simulated_actuators(plant)
        if driver.actuator_id != ActuatorId.CHLORINE_DOSING_PUMP
    ]
    actuator_drivers.append(dosing_driver)
    app = build_app_from_mapping(config, clock=clock, actuator_drivers=actuator_drivers)
    await app.tick()
    await clock.advance(1.0)
    await app.tick()

    assert app.measurement_logger is not None
    assert len(
        app.measurement_logger.history(
            sensor_id=SensorId.CHLORINATION_DUTY_CYCLE_PERCENT,
            limit=10,
        )
    ) == 1
    assert len(
        app.measurement_logger.history(
            sensor_id=SensorId.CHLORINE_DAILY_DELIVERED_OZ,
            limit=10,
        )
    ) == 2

    await clock.advance(29.0)
    await app.tick()

    assert len(
        app.measurement_logger.history(
            sensor_id=SensorId.CHLORINATION_DUTY_CYCLE_PERCENT,
            limit=10,
        )
    ) == 2
    cumulative_records = app.measurement_logger.history(
        sensor_id=SensorId.CHLORINE_DAILY_DELIVERED_OZ,
        limit=10,
    )
    assert len(cumulative_records) == 2
    assert round(cumulative_records[-1].value, 3) == 0.0
    assert cumulative_records[-1].metadata["snapshot_boundary"] == "start"

    await clock.advance(30.1)
    await app.tick()

    cumulative_records = app.measurement_logger.history(
        sensor_id=SensorId.CHLORINE_DAILY_DELIVERED_OZ,
        limit=10,
    )
    assert len(cumulative_records) == 3
    assert round(cumulative_records[-1].value, 3) == 1.0
    assert cumulative_records[-1].metadata["snapshot_boundary"] == "end"


def test_chlorine_delivery_accounting_stops_at_auto_off_time() -> None:
    previous = datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc)
    auto_off_at = previous + timedelta(seconds=30)
    now = previous + timedelta(seconds=45)
    sample = ActuatorStateSample(
        actuator_id=ActuatorId.CHLORINE_DOSING_PUMP,
        observed_at=auto_off_at,
        state=ActuatorState.OFF,
        metadata={
            ACTUATOR_AUTO_OFF_AT_METADATA: auto_off_at.isoformat(),
            "auto_off_expired": True,
            "auto_off_previous_state": ActuatorState.ON.value,
        },
    )

    runtime_end = _chlorine_runtime_end_from_sample(
        sample,
        previous=previous,
        now=now,
    )

    assert runtime_end == auto_off_at


def test_daily_sodium_hypochlorite_summary_totals_automated_and_manual_additions(
    tmp_path: Path,
) -> None:
    clock = make_clock()
    config = {
        "runtime": {
            "stage": "sensor_logging",
            "driver_profile": "simulated",
            "enabled_layers": ["logging"],
            "enabled_actuators": [],
            "enabled_sensor_groups": [],
        },
        "logging": {
            "database_path": str(tmp_path / "daily-chlorine.sqlite3"),
        },
        "pump_timer": {"timezone": "UTC", "schedules": []},
        "fc_demand": {
            "enabled": True,
            "pool_volume_gal": 10000.0,
            "chlorine_strength_percent": 12.0,
        },
    }
    app = build_app_from_mapping(config, clock=clock)
    assert app.measurement_logger is not None
    app.measurement_logger.log_measurements(
        tuple(
            Measurement(
                id=f"{SensorId.DAILY_SODIUM_HYPOCHLORITE_ADDED_OZ.value}:2026-05-{14 + index:02d}",
                sensor_id=SensorId.DAILY_SODIUM_HYPOCHLORITE_ADDED_OZ,
                observed_at=datetime(2026, 5, 15 + index, tzinfo=timezone.utc),
                kind=MeasurementKind.ESTIMATED,
                value=float(index + 1),
                unit="fl oz",
                quality=Quality.GOOD,
            )
            for index in range(6)
        )
        + tuple(
            Measurement(
                id=f"{SensorId.DAILY_MURIATIC_ACID_ADDED_OZ.value}:2026-05-{14 + index:02d}",
                sensor_id=SensorId.DAILY_MURIATIC_ACID_ADDED_OZ,
                observed_at=datetime(2026, 5, 15 + index, tzinfo=timezone.utc),
                kind=MeasurementKind.ESTIMATED,
                value=2.0,
                unit="fl oz",
                quality=Quality.GOOD,
            )
            for index in range(6)
        )
    )
    app.measurement_logger.log_chlorine_delivery(
        observed_at=datetime(2026, 5, 20, 8, tzinfo=timezone.utc),
        runtime_seconds=90.0,
        delivered_oz=1.5,
    )
    app.measurement_logger.log_chemical_addition(
        ChemicalAddition(
            added_at=datetime(2026, 5, 20, 9, tzinfo=timezone.utc),
            chemical=ChemicalType.SODIUM_HYPOCHLORITE,
            amount=10.0,
            unit="fl_oz",
            amount_fl_oz=10.0,
            strength_percent=12.0,
        )
    )
    app.measurement_logger.log_chemical_addition(
        ChemicalAddition(
            added_at=datetime(2026, 5, 20, 10, tzinfo=timezone.utc),
            chemical=ChemicalType.MURIATIC_ACID,
            amount=4.0,
            unit="fl_oz",
            amount_fl_oz=4.0,
            strength_percent=31.45,
        )
    )
    app.measurement_logger.log_chemical_addition(
        ChemicalAddition(
            added_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
            chemical=ChemicalType.SODIUM_HYPOCHLORITE,
            amount=99.0,
            unit="fl_oz",
            amount_fl_oz=99.0,
            strength_percent=12.0,
        )
    )

    measurements = app._daily_environment_measurements(
        observed_at=datetime(2026, 5, 21, 12, tzinfo=timezone.utc),
    )
    daily_chlorine = next(
        measurement
        for measurement in measurements
        if measurement.sensor_id == SensorId.DAILY_SODIUM_HYPOCHLORITE_ADDED_OZ
    )
    daily_acid = next(
        measurement
        for measurement in measurements
        if measurement.sensor_id == SensorId.DAILY_MURIATIC_ACID_ADDED_OZ
    )
    chlorine_7d = next(
        measurement
        for measurement in measurements
        if measurement.sensor_id
        == SensorId.DAILY_SODIUM_HYPOCHLORITE_ADDED_OZ_7D_AVG
    )
    acid_7d = next(
        measurement
        for measurement in measurements
        if measurement.sensor_id == SensorId.DAILY_MURIATIC_ACID_ADDED_OZ_7D_AVG
    )

    assert daily_chlorine.observed_at == datetime(2026, 5, 21, tzinfo=timezone.utc)
    assert daily_chlorine.value == 11.5
    assert daily_chlorine.metadata["automated_delivery_oz"] == 1.5
    assert daily_chlorine.metadata["manual_sodium_hypochlorite_oz"] == 10.0
    assert daily_chlorine.metadata["manual_addition_count"] == 1
    assert daily_acid.value == 4.0
    assert daily_acid.metadata["manual_addition_count"] == 1
    assert chlorine_7d.value == 4.6429
    assert chlorine_7d.metadata["source_sample_count"] == 7
    assert acid_7d.value == 2.2857
    assert acid_7d.metadata["source_sample_count"] == 7


@pytest.mark.asyncio
async def test_tick_logs_fc_demand_estimate_when_ready(tmp_path: Path) -> None:
    clock = make_clock()
    config = {
        "runtime": {
            "stage": "sensor_logging",
            "driver_profile": "simulated",
            "enabled_layers": ["logging"],
            "enabled_actuators": [],
            "enabled_sensor_groups": [],
        },
        "logging": {
            "database_path": str(tmp_path / "fc_demand.sqlite3"),
        },
        "fc_demand": {
            "enabled": True,
            "mode": "observe_only",
            "pool_volume_gal": 10000.0,
            "target_fc_ppm": 4.0,
            "chlorine_strength_percent": 12.0,
            "minimum_test_interval_hours": 12.0,
            "max_daily_dose_oz": 256.0,
        },
    }

    app = build_app_from_mapping(config, clock=clock)
    assert app.measurement_logger is not None
    app.measurement_logger.log_lab_test(
        LabTest(
            sampled_at=datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc),
            free_chlorine=4.0,
        )
    )
    app.measurement_logger.log_lab_test(
        LabTest(
            sampled_at=datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc),
            free_chlorine=3.0,
        )
    )

    first = await app.tick()
    second = await app.tick()
    records = app.measurement_logger.history(
        sensor_id=SensorId.FC_DEMAND_PPM_PER_DAY,
        limit=10,
    )
    base_records = app.measurement_logger.history(
        sensor_id=SensorId.BASE_FC_DEMAND_PPM_PER_DAY,
        limit=10,
    )
    predicted_records = app.measurement_logger.history(
        sensor_id=SensorId.PREDICTED_FC_DEMAND_PPM_PER_DAY,
        limit=10,
    )
    residual_records = app.measurement_logger.history(
        sensor_id=SensorId.FC_DEMAND_RESIDUAL_PPM_PER_DAY,
        limit=10,
    )

    assert first.fc_demand_status is not None
    assert first.fc_demand_status.ready is True
    assert second.fc_demand_status is not None
    assert second.fc_demand_status.ready is True
    assert len(records) == 1
    assert records[0].observed_at == datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc)
    assert records[0].value == 1.0
    assert records[0].unit == "ppm/day"
    assert len(base_records) == 1
    assert base_records[0].value == 1.0
    assert len(predicted_records) == 1
    assert predicted_records[0].value == 1.0
    assert len(residual_records) == 1
    assert residual_records[0].value == 0.0


@pytest.mark.asyncio
async def test_dosing_prime_runs_for_30_seconds_and_then_releases() -> None:
    clock = make_clock()
    config = {
        "runtime": {
            "stage": "open_loop_timer",
            "driver_profile": "simulated",
            "enabled_layers": ["chlorination"],
            "enabled_actuators": ["chlorine_dosing_pump"],
            "enabled_sensor_groups": [],
        },
        "chlorination": {
            "enabled": True,
            "daily_dose_oz": 0.0,
            "pump_output_oz_per_min": 1.0,
            "no_dose_last_minutes": 10.0,
            "max_duty_cycle": 0.5,
            "cycle_on_seconds": 60.0,
        },
    }

    app = build_app_from_mapping(config, clock=clock)
    app.start_dosing_pump_prime(duration_s=30.0)
    first = await app.tick()
    await clock.advance(31.0)
    second = await app.tick()

    assert first.chlorination_status is not None
    assert first.chlorination_status.reason == "dosing pump prime active"
    assert app.router.actuator_states[ActuatorId.CHLORINE_DOSING_PUMP] == ActuatorState.OFF
    assert second.chlorination_status is not None
    assert second.chlorination_status.reason == "daily dose is zero"


@pytest.mark.asyncio
async def test_dosing_calibration_uses_duty_cycle_and_bypasses_interlock(
    tmp_path: Path,
) -> None:
    clock = make_clock()
    config = {
        "runtime": {
            "stage": "open_loop_timer",
            "driver_profile": "simulated",
            "enabled_layers": ["chlorination", "logging", "safety_enforcement"],
            "enabled_actuators": ["chlorine_dosing_pump"],
            "enabled_sensor_groups": [],
        },
        "logging": {
            "database_path": str(tmp_path / "calibration_delivery.sqlite3"),
        },
        "chlorination": {
            "enabled": True,
            "daily_dose_oz": 0.0,
            "pump_output_oz_per_min": 1.0,
            "no_dose_last_minutes": 10.0,
            "max_duty_cycle": 0.5,
            "cycle_on_seconds": 60.0,
        },
    }

    app = build_app_from_mapping(config, clock=clock)
    app.start_dosing_pump_calibration(
        duration_s=120.0,
        duty_cycle=0.5,
        cycle_period_s=60.0,
    )
    first = await app.tick()
    await clock.advance(31.0)
    second = await app.tick()
    await clock.advance(31.0)
    third = await app.tick()

    assert first.chlorination_status is not None
    assert first.chlorination_status.reason == "dosing pump calibration active"
    assert first.chlorination_results[0].metadata["safety_bypassed"] is True
    assert first.safety_results == ()
    assert second.logged_chlorine_delivery_count == 0
    assert second.chlorination_status is not None
    assert second.chlorination_status.active is False
    assert app.router.actuator_states[ActuatorId.CHLORINE_DOSING_PUMP] == ActuatorState.ON
    assert third.chlorination_status is not None
    assert third.chlorination_status.active is True

    assert app.measurement_logger is not None
    delivery_summary = app.measurement_logger.chlorine_delivery_summary()
    assert delivery_summary.runtime_seconds == 0.0
    assert delivery_summary.delivered_oz == 0.0


@pytest.mark.asyncio
async def test_stop_dosing_diagnostic_turns_dosing_pump_off() -> None:
    clock = make_clock()
    config = {
        "runtime": {
            "stage": "open_loop_timer",
            "driver_profile": "simulated",
            "enabled_layers": ["chlorination"],
            "enabled_actuators": ["chlorine_dosing_pump"],
            "enabled_sensor_groups": [],
        },
        "chlorination": {
            "enabled": True,
            "daily_dose_oz": 0.0,
            "pump_output_oz_per_min": 1.0,
            "no_dose_last_minutes": 10.0,
            "max_duty_cycle": 0.5,
            "cycle_on_seconds": 60.0,
        },
    }

    app = build_app_from_mapping(config, clock=clock)
    app.start_dosing_pump_calibration()
    await app.tick()

    result = await app.stop_dosing_pump_diagnostic()

    assert result["stopped"] is True
    assert result["prime"]["active"] is False
    assert result["command"]["applied"] is True
    assert app.router.actuator_states[ActuatorId.CHLORINE_DOSING_PUMP] == ActuatorState.OFF


@pytest.mark.asyncio
async def test_dosing_prime_is_excluded_from_delivery_and_fc_demand(
    tmp_path: Path,
) -> None:
    clock = make_clock()
    config = {
        "runtime": {
            "stage": "open_loop_timer",
            "driver_profile": "simulated",
            "enabled_layers": ["chlorination", "logging"],
            "enabled_actuators": ["chlorine_dosing_pump"],
            "enabled_sensor_groups": [],
        },
        "logging": {
            "database_path": str(tmp_path / "prime_delivery.sqlite3"),
        },
        "chlorination": {
            "enabled": True,
            "daily_dose_oz": 0.0,
            "pump_output_oz_per_min": 1.0,
            "no_dose_last_minutes": 10.0,
            "max_duty_cycle": 0.5,
            "cycle_on_seconds": 60.0,
        },
        "fc_demand": {
            "enabled": True,
            "mode": "observe_only",
            "pool_volume_gal": 10000.0,
            "target_fc_ppm": 4.0,
            "chlorine_strength_percent": 12.0,
            "minimum_test_interval_hours": 12.0,
            "max_daily_dose_oz": 256.0,
        },
    }

    app = build_app_from_mapping(config, clock=clock)
    assert app.measurement_logger is not None
    app.start_dosing_pump_prime(duration_s=30.0)
    first = await app.tick()
    await clock.advance(31.0)
    second = await app.tick()

    delivery_summary = app.measurement_logger.chlorine_delivery_summary()
    assert first.logged_chlorine_delivery_count == 0
    assert second.logged_chlorine_delivery_count == 0
    assert delivery_summary.runtime_seconds == 0.0
    assert delivery_summary.delivered_oz == 0.0

    current_sampled_at = clock.now()
    app.measurement_logger.log_lab_test(
        LabTest(
            sampled_at=current_sampled_at - timedelta(days=1),
            free_chlorine=4.0,
        )
    )
    app.measurement_logger.log_lab_test(
        LabTest(
            sampled_at=current_sampled_at,
            free_chlorine=3.0,
        )
    )

    plan = app.fc_demand_plan(now=current_sampled_at)
    assert plan is not None
    assert plan.status.ready is True
    assert plan.status.added_fc_ppm == 0.0
    assert plan.status.daily_demand_ppm == 1.0


def modbus_relay_config() -> dict[str, object]:
    return {
        "modbus_relay": {
            "port": "/dev/ttyUSB0",
            "slave_id": 1,
            "baudrate": 9600,
            "timeout_s": 1.0,
            "relays": {
                "pump_motor": 1,
                "pump_motor_speed": 2,
                "booster_pump": 3,
                "chlorine_dosing_pump": 4,
            },
            "pump_speed_relay": {
                "low_state": "on",
                "high_state": "off",
            },
        }
    }


def test_raspberry_pi_profile_can_use_injected_drivers() -> None:
    clock = make_clock()
    plant = SimulatedPlant(clock=clock)
    config = {
        "runtime": {
            "stage": "open_loop_timer",
            "driver_profile": "raspberry_pi",
            "enabled_layers": ["pump_timer", "safety_enforcement"],
            "enabled_actuators": [
                "pump_motor",
                "pump_motor_speed",
                "booster_pump",
            ],
            "enabled_sensor_groups": [],
        }
    }

    app = build_app_from_mapping(
        config,
        clock=clock,
        actuator_drivers=build_default_simulated_actuators(plant),
    )

    assert app.runtime_config.driver_profile == DriverProfile.RASPBERRY_PI
    assert app.simulated_plant is None
    assert app.acquisition_service is None


@pytest.mark.asyncio
async def test_raspberry_pi_profile_safe_stops_outputs_on_first_tick() -> None:
    clock = make_clock()
    plant = SimulatedPlant(clock=clock)
    config = {
        "runtime": {
            "stage": "open_loop_timer",
            "driver_profile": "raspberry_pi",
            "enabled_layers": ["pump_timer"],
            "enabled_actuators": [
                "pump_motor",
                "pump_motor_speed",
                "booster_pump",
            ],
            "enabled_sensor_groups": [],
        },
        **active_pump_timer_config(),
    }
    app = build_app_from_mapping(
        config,
        clock=clock,
        actuator_drivers=build_default_simulated_actuators(plant),
    )

    result = await app.tick()
    second = await app.tick()

    assert len(result.startup_safe_off_results) == 3
    assert all(command_result.applied for command_result in result.startup_safe_off_results)
    assert len(result.timer_results) == 2
    assert app.router.actuator_states[ActuatorId.PUMP_MOTOR] == ActuatorState.ON
    assert app.router.actuator_states[ActuatorId.PUMP_MOTOR_SPEED] == ActuatorState.HIGH
    assert second.startup_safe_off_results == ()


def test_poll_weather_due_fetches_weather_and_logs_hourly_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = make_clock()
    config = {
        "runtime": {
            "stage": "sensor_logging",
            "driver_profile": "simulated",
            "enabled_layers": ["logging"],
            "enabled_sensor_groups": [],
        },
        "logging": {
            "database_path": str(tmp_path / "weather.sqlite3"),
        },
        "weather": {
            "enabled": True,
            "latitude": 29.75,
            "longitude": -95.35,
            "poll_interval_s": 3600.0,
            "past_hours": 2,
            "forecast_hours": 48,
        },
    }

    def fake_fetch_json(_url: str, _timeout_s: float) -> dict[str, object]:
        hourly: dict[str, object] = {
            "time": [
                "2026-05-21T10:00",
                "2026-05-21T11:00",
                "2026-05-21T12:00",
                "2026-05-21T13:00",
            ]
        }
        hourly_units: dict[str, str] = {"time": "iso8601"}
        for index, field in enumerate(weather_service_module.WEATHER_FIELDS):
            hourly[field] = [float(index), float(index + 1), float(index + 2), float(index + 3)]
            hourly_units[field] = "°F" if "temperature" in field else "mm"
        hourly_units["cloud_cover"] = "%"
        hourly_units["uv_index"] = "index"
        return {"hourly": hourly, "hourly_units": hourly_units}

    monkeypatch.setattr(weather_service_module, "_default_fetch_json", fake_fetch_json)
    app = build_app_from_mapping(config, clock=clock)
    assert app.measurement_logger is not None

    weather_result = app.poll_weather_due()

    assert weather_result.updated is True
    assert weather_result.logged_count == 1
    assert app.weather_service is not None
    assert app.weather_service.latest_forecast is not None

    points = app.measurement_logger.weather_history(
        field="temperature_2m",
        since=clock.now() - timedelta(hours=4),
        until=clock.now() + timedelta(hours=1),
        limit=10,
    )
    assert len(points) == 1


@pytest.mark.asyncio
async def test_tick_logs_daily_environment_summaries_from_orp_temp_and_weather(
    tmp_path: Path,
) -> None:
    clock = make_clock()
    config = {
        "runtime": {
            "stage": "sensor_logging",
            "driver_profile": "simulated",
            "enabled_layers": ["logging"],
            "enabled_sensor_groups": [],
        },
        "logging": {
            "database_path": str(tmp_path / "daily_environment.sqlite3"),
        },
        "pump_timer": {
            "timezone": "UTC",
            "schedules": [],
        },
    }
    start = datetime(2026, 5, 20, 0, 0, tzinfo=timezone.utc)
    app = build_app_from_mapping(config, clock=clock)
    assert app.measurement_logger is not None
    app.measurement_logger.log_measurements(
        (
            Measurement(
                sensor_id=SensorId.ORP_TEMP,
                observed_at=start + timedelta(hours=1),
                value=70.0,
                unit="degF",
                quality=Quality.GOOD,
            ),
            Measurement(
                sensor_id=SensorId.ORP_TEMP,
                observed_at=start + timedelta(hours=12),
                value=82.0,
                unit="degF",
                quality=Quality.GOOD,
            ),
            Measurement(
                sensor_id=SensorId.ORP_TEMP,
                observed_at=start + timedelta(hours=23),
                value=74.0,
                unit="degF",
                quality=Quality.GOOD,
            ),
            Measurement(
                sensor_id=SensorId.ORP_TEMP,
                observed_at=start + timedelta(hours=6),
                value=65.0,
                unit="degF",
                quality=Quality.SUSPECT,
            ),
        )
    )
    app.measurement_logger.log_weather_observation(
        weather_service_module.WeatherObservation(
            observed_at=start + timedelta(hours=10),
            source="open-meteo",
            latitude=29.75,
            longitude=-95.35,
            values={"uv_index": 1.0, "shortwave_radiation": 100.0},
            units_by_field={"uv_index": "index", "shortwave_radiation": "W/m2"},
        )
    )
    app.measurement_logger.log_weather_observation(
        weather_service_module.WeatherObservation(
            observed_at=start + timedelta(hours=11),
            source="open-meteo",
            latitude=29.75,
            longitude=-95.35,
            values={"uv_index": 3.0, "shortwave_radiation": 300.0},
            units_by_field={"uv_index": "index", "shortwave_radiation": "W/m2"},
        )
    )

    first = await app.tick()
    second = await app.tick()

    assert first.logged_measurement_count == 16
    assert second.logged_measurement_count == 0
    min_records = app.measurement_logger.history(
        sensor_id=SensorId.DAILY_WATER_TEMP_MIN,
        limit=10,
    )
    avg_records = app.measurement_logger.history(
        sensor_id=SensorId.DAILY_WATER_TEMP_AVG,
        limit=10,
    )
    max_records = app.measurement_logger.history(
        sensor_id=SensorId.DAILY_WATER_TEMP_MAX,
        limit=10,
    )
    uv_records = app.measurement_logger.history(
        sensor_id=SensorId.DAILY_UV_INDEX_DOSE,
        limit=10,
    )
    shortwave_records = app.measurement_logger.history(
        sensor_id=SensorId.DAILY_SHORTWAVE_RADIATION_DOSE,
        limit=10,
    )
    daily_chlorine_records = app.measurement_logger.history(
        sensor_id=SensorId.DAILY_SODIUM_HYPOCHLORITE_ADDED_OZ,
        limit=10,
    )
    daily_acid_records = app.measurement_logger.history(
        sensor_id=SensorId.DAILY_MURIATIC_ACID_ADDED_OZ,
        limit=10,
    )
    water_avg_7d_records = app.measurement_logger.history(
        sensor_id=SensorId.DAILY_WATER_TEMP_AVG_7D_AVG,
        limit=10,
    )
    uv_28d_records = app.measurement_logger.history(
        sensor_id=SensorId.DAILY_UV_INDEX_DOSE_28D_AVG,
        limit=10,
    )
    delivered_reset_records = app.measurement_logger.history(
        sensor_id=SensorId.CHLORINE_DAILY_DELIVERED_OZ,
        limit=10,
    )

    assert len(min_records) == 1
    assert min_records[0].observed_at == datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc)
    assert min_records[0].value == 70.0
    assert avg_records[0].value == 75.3333
    assert max_records[0].value == 82.0
    assert uv_records[0].value == 4.0
    assert uv_records[0].unit == "index-hour"
    assert shortwave_records[0].value == 400.0
    assert shortwave_records[0].unit == "Wh/m2"
    assert daily_chlorine_records[0].observed_at == datetime(
        2026,
        5,
        21,
        tzinfo=timezone.utc,
    )
    assert daily_chlorine_records[0].value == 0.0
    assert daily_acid_records[0].value == 0.0
    assert water_avg_7d_records[0].value == 75.3333
    assert water_avg_7d_records[0].metadata["source_sample_count"] == 1
    assert uv_28d_records[0].value == 4.0
    assert uv_28d_records[0].metadata["window_days"] == 28
    assert delivered_reset_records[0].observed_at == datetime(
        2026,
        5,
        21,
        tzinfo=timezone.utc,
    )
    assert delivered_reset_records[0].value == 0.0
    assert delivered_reset_records[0].metadata["snapshot_boundary"] == "reset"


def test_raspberry_pi_profile_builds_modbus_relay_actuators_from_config() -> None:
    clock = make_clock()
    config = {
        "runtime": {
            "stage": "open_loop_timer",
            "driver_profile": "raspberry_pi",
            "enabled_actuators": [
                "pump_motor",
                "pump_motor_speed",
                "booster_pump",
            ],
            "enabled_sensor_groups": [],
        },
        **modbus_relay_config(),
    }

    app = build_app_from_mapping(config, clock=clock)

    assert app.runtime_config.driver_profile == DriverProfile.RASPBERRY_PI
    assert app.simulated_plant is None
    assert app.acquisition_service is None


def test_raspberry_pi_sensor_logging_stage_builds_modbus_sensor_drivers(
    tmp_path: Path,
) -> None:
    clock = make_clock()
    config = {
        "runtime": {
            "stage": "sensor_logging",
            "driver_profile": "raspberry_pi",
            "enabled_layers": ["pump_timer", "acquisition", "logging"],
            "enabled_actuators": [
                "pump_motor",
                "pump_motor_speed",
                "booster_pump",
            ],
            "enabled_sensor_groups": ["chemistry_loop"],
        },
        "acquisition": {
            "groups": {
                "chemistry_loop": {
                    "sensor_ids": [
                        "raw_orp",
                        "orp_temp",
                        "raw_ph",
                        "ph_temp",
                    ],
                    "read_interval_s": 5.0,
                    "log_interval_s": 120.0,
                    "requires_pump_flow": True,
                    "min_pump_on_seconds": 60.0,
                }
            }
        },
        "logging": {
            "database_path": str(tmp_path / "measurements.sqlite3"),
        },
        **modbus_relay_config(),
        "enable_modbus_ph_sensor": True,
        "modbus_ph_sensor": {
            "port": "/dev/ttyUSB0",
            "slave_id": 4,
            "baudrate": 4800,
            "timeout_s": 1.0,
        },
        "modbus_orp_sensor": {
            "port": "/dev/ttyUSB0",
            "slave_id": 1,
            "baudrate": 4800,
            "timeout_s": 1.0,
        },
    }

    app = build_app_from_mapping(config, clock=clock)

    assert app.runtime_config.driver_profile == DriverProfile.RASPBERRY_PI
    assert app.acquisition_service is not None
    assert app.acquisition_config.groups[0].name == "chemistry_loop"


@pytest.mark.asyncio
async def test_tick_feeds_acquisition_measurements_into_safety_enforcement() -> None:
    clock = make_clock()
    sensor = FixedSensor(
        name="overpressure_sensor",
        sensor_id=SensorId.PUMP_OUTPUT_PSI,
        clock=clock,
        value=31.0,
    )
    config = {
        **simulated_runtime_config(),
        **minimal_acquisition_config(),
    }

    app = build_app_from_mapping(
        config,
        clock=clock,
        sensor_drivers=[sensor],
    )
    result = await app.tick(force_acquisition=True)

    assert len(result.measurements) == 1
    assert app.router.safety_gate.locked_out
    assert app.router.safety_gate.active_fault is not None
    assert app.router.safety_gate.active_fault.code == "pump_output_overpressure"
    assert {safety_result.metadata["safety_action"] for safety_result in result.safety_results} == {
        "pump_output_overpressure"
    }


@pytest.mark.asyncio
async def test_chemistry_sampling_refresh_triggers_pump_run_after_long_off_time() -> None:
    clock = make_clock()
    config = {
        **simulated_runtime_config(),
        **minimal_acquisition_config(),
        "runtime": {
            "stage": "sensor_logging",
            "driver_profile": "simulated",
            "enabled_layers": ["pump_timer", "acquisition", "safety_enforcement"],
            "enabled_actuators": [
                "pump_motor",
                "pump_motor_speed",
                "booster_pump",
                "chlorine_dosing_pump",
            ],
            "enabled_sensor_groups": ["pressures"],
        },
        "pump_timer": {
            "timezone": "UTC",
            "schedules": [],
        },
        "acquisition": {
            **minimal_acquisition_config()["acquisition"],  # type: ignore[index]
            "chemistry_sampling_refresh": {
                "enabled": True,
                "max_pump_off_s": 1.0,
                "run_duration_s": 60.0,
                "pump_speed": "high",
            },
        },
    }

    app = build_app_from_mapping(config, clock=clock)
    await app.tick(force_acquisition=True)
    await clock.advance(2.0)
    second = await app.tick(force_acquisition=True)

    assert any(
        result.applied and app.router.actuator_states.get(ActuatorId.PUMP_MOTOR) == ActuatorState.ON
        for result in second.timer_results
    )
    assert app.active_sample_timer_override() is not None


@pytest.mark.asyncio
async def test_tick_computes_csi_from_valid_live_temp_ph_and_latest_sparse_lab_values(
    tmp_path: Path,
) -> None:
    clock = make_clock()
    temp_sensor = FixedSensor(
        name="temp_sensor",
        sensor_id=SensorId.TEMP,
        clock=clock,
        value=84.0,
        unit="degF",
    )
    ph_sensor = FixedSensor(
        name="ph_sensor",
        sensor_id=SensorId.RAW_PH,
        clock=clock,
        value=7.5,
        unit="pH",
    )
    config = {
        "runtime": {
            "stage": "sensor_logging",
            "driver_profile": "simulated",
            "enabled_layers": ["acquisition", "logging", "safety_enforcement"],
            "enabled_actuators": [
                "pump_motor",
                "pump_motor_speed",
                "booster_pump",
                "chlorine_dosing_pump",
            ],
            "enabled_sensor_groups": ["chemistry_loop"],
        },
        "acquisition": {
            "groups": {
                "chemistry_loop": {
                    "sensor_ids": ["temp", "raw_ph"],
                    "read_interval_s": 1.0,
                    "log_interval_s": 1.0,
                    "requires_pump_flow": False,
                    "oversample": {
                        "sample_count": 1,
                        "sample_interval_s": 0.0,
                        "reducer": "last",
                    },
                }
            }
        },
        "logging": {
            "database_path": str(tmp_path / "measurements.sqlite3"),
        },
    }
    app = build_app_from_mapping(config, clock=clock, sensor_drivers=[temp_sensor, ph_sensor])
    assert app.measurement_logger is not None

    app.measurement_logger.log_lab_test(
        LabTest(sampled_at=clock.now(), alkalinity=100.0)
    )
    app.measurement_logger.log_lab_test(
        LabTest(sampled_at=clock.now(), calcium_hardness=300.0)
    )
    app.measurement_logger.log_lab_test(
        LabTest(sampled_at=clock.now(), tds=1000.0)
    )

    tick = await app.tick(force_acquisition=True)

    assert tick.csi_measurement is not None
    assert tick.csi_measurement.sensor_id == SensorId.CALCIUM_SATURATION_INDEX
    assert abs(tick.csi_measurement.value - 0.1211) < 0.02

    records = app.measurement_logger.history(
        sensor_id=SensorId.CALCIUM_SATURATION_INDEX,
        limit=10,
    )
    assert len(records) == 1
