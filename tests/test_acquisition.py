"""
Tests for sensor acquisition policies.

These tests show how readings, logging cadence, pump-flow validity, oversampling,
and rolling filters are expected to behave.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from poolctl.domain.models import (
    ActuatorId,
    ActuatorState,
    Measurement,
    Quality,
    SensorId,
)
from poolctl.services.acquisition import (
    AcquisitionConfig,
    AcquisitionGroupConfig,
    AcquisitionService,
    FilterType,
    MeasurementFilterConfig,
    OversamplingConfig,
    Reducer,
    load_acquisition_config,
)
from poolctl.services.clock import SimulatedClock


class FakeSensor:
    def __init__(
        self,
        *,
        name: str,
        sensor_id: SensorId,
        clock: SimulatedClock,
        values: list[float],
        unit: str = "psi",
        fail_on_reads: set[int] | None = None,
    ) -> None:
        self.name = name
        self.sensor_id = sensor_id
        self._clock = clock
        self._values = values
        self._unit = unit
        self._fail_on_reads = fail_on_reads if fail_on_reads is not None else set()
        self.read_count = 0

    async def read(self) -> Measurement:
        self.read_count += 1

        if self.read_count in self._fail_on_reads:
            raise RuntimeError(f"{self.name} read failed")

        value_index = min(self.read_count - 1, len(self._values) - 1)

        return Measurement(
            sensor_id=self.sensor_id,
            observed_at=self._clock.now(),
            value=self._values[value_index],
            unit=self.unit,
            quality=Quality.GOOD,
            metadata={"driver": self.name},
        )

    @property
    def unit(self) -> str:
        return self._unit


class FakeMultiSensor:
    def __init__(
        self,
        *,
        name: str,
        clock: SimulatedClock,
        sensor_ids: tuple[SensorId, ...] | None,
        values: dict[SensorId, float],
        unit: str = "psi",
    ) -> None:
        self.name = name
        self._clock = clock
        self._values = values
        self._unit = unit
        self.read_count = 0
        if sensor_ids is not None:
            self.sensor_ids = sensor_ids

    async def read_all(self) -> list[Measurement]:
        self.read_count += 1
        return [
            Measurement(
                sensor_id=sensor_id,
                observed_at=self._clock.now(),
                value=value,
                unit=self._unit,
                quality=Quality.GOOD,
                metadata={"driver": self.name},
            )
            for sensor_id, value in self._values.items()
        ]


def make_clock() -> SimulatedClock:
    return SimulatedClock(
        start_at=datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc),
    )


def no_actuator_states() -> dict[ActuatorId, ActuatorState]:
    return {}


def no_state_started_at() -> dict[ActuatorId, datetime]:
    return {}


def test_load_acquisition_config_from_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "pool.yaml"
    config_path.write_text(
        """
acquisition:
  groups:
    pressures:
      sensor_ids:
        - pump_output_psi
        - raw_orp
      read_interval_s: 0.5
      log_interval_s: 30
      requires_pump_flow: false
      oversample:
        sample_count: 3
        sample_interval_s: 0.1
        reducer: median
      filter:
        type: boxcar
        window_samples: 2
        min_samples: 1
""",
        encoding="utf-8",
    )

    config = load_acquisition_config(config_path)

    assert len(config.groups) == 1
    assert config.groups[0].name == "pressures"
    assert config.groups[0].sensor_ids == (
        SensorId.PUMP_OUTPUT_PSI,
        SensorId.RAW_ORP,
    )
    assert config.groups[0].read_interval_s == 0.5
    assert config.groups[0].log_interval_s == 30.0
    assert config.groups[0].oversampling.sample_count == 3
    assert config.groups[0].oversampling.sample_interval_s == 0.1
    assert config.groups[0].oversampling.reducer == Reducer.MEDIAN
    assert config.groups[0].filtering.filter_type == FilterType.BOXCAR
    assert config.groups[0].filtering.window_samples == 2
    assert config.groups[0].filtering.min_samples == 1


@pytest.mark.asyncio
async def test_read_group_oversamples_and_reduces_measurement() -> None:
    clock = make_clock()
    sensor = FakeSensor(
        name="pump_output",
        sensor_id=SensorId.PUMP_OUTPUT_PSI,
        clock=clock,
        values=[1.0, 100.0, 3.0],
    )
    service = AcquisitionService(
        config=AcquisitionConfig(
            groups=(
                AcquisitionGroupConfig(
                    name="pressures",
                    sensor_ids=(SensorId.PUMP_OUTPUT_PSI,),
                    read_interval_s=1.0,
                    log_interval_s=30.0,
                    oversampling=OversamplingConfig(
                        sample_count=3,
                        reducer=Reducer.MEDIAN,
                    ),
                ),
            )
        ),
        clock=clock,
        sensor_drivers=[sensor],
    )

    result = await service.read_group(
        "pressures",
        actuator_states=no_actuator_states(),
        state_started_at=no_state_started_at(),
    )

    assert sensor.read_count == 3
    assert len(result.measurements) == 1
    assert result.measurements[0].value == 3.0
    assert result.measurements[0].metadata["sample_count"] == 3
    assert result.measurements[0].metadata["reducer"] == "median"
    assert result.measurements[0].metadata["raw_min"] == 1.0
    assert result.measurements[0].metadata["raw_max"] == 100.0
    assert result.loggable_measurements == result.measurements


@pytest.mark.asyncio
async def test_read_group_applies_rolling_boxcar_filter() -> None:
    clock = make_clock()
    sensor = FakeSensor(
        name="pump_output",
        sensor_id=SensorId.PUMP_OUTPUT_PSI,
        clock=clock,
        values=[10.0, 12.0, 18.0],
    )
    service = AcquisitionService(
        config=AcquisitionConfig(
            groups=(
                AcquisitionGroupConfig(
                    name="pressures",
                    sensor_ids=(SensorId.PUMP_OUTPUT_PSI,),
                    read_interval_s=1.0,
                    log_interval_s=30.0,
                    filtering=MeasurementFilterConfig(
                        filter_type=FilterType.BOXCAR,
                        window_samples=2,
                    ),
                ),
            )
        ),
        clock=clock,
        sensor_drivers=[sensor],
    )

    first = await service.read_group(
        "pressures",
        actuator_states=no_actuator_states(),
        state_started_at=no_state_started_at(),
    )
    second = await service.read_group(
        "pressures",
        actuator_states=no_actuator_states(),
        state_started_at=no_state_started_at(),
    )
    third = await service.read_group(
        "pressures",
        actuator_states=no_actuator_states(),
        state_started_at=no_state_started_at(),
    )

    assert sensor.read_count == 3
    assert first.measurements[0].value == 10.0
    assert second.measurements[0].value == 11.0
    assert third.measurements[0].value == 15.0
    assert third.measurements[0].metadata["filter"]["sample_count"] == 2
    assert third.measurements[0].metadata["filter"]["raw_latest"] == 18.0
    assert service.latest_raw_measurements[SensorId.PUMP_OUTPUT_PSI].value == 18.0
    assert service.latest_measurements[SensorId.PUMP_OUTPUT_PSI].value == 15.0


@pytest.mark.asyncio
async def test_flow_invalid_measurements_do_not_enter_rolling_filter() -> None:
    clock = make_clock()
    sensor = FakeSensor(
        name="raw_ph",
        sensor_id=SensorId.RAW_PH,
        clock=clock,
        values=[7.4, 99.0, 7.6],
        unit="pH",
    )
    service = AcquisitionService(
        config=AcquisitionConfig(
            groups=(
                AcquisitionGroupConfig(
                    name="chemistry",
                    sensor_ids=(SensorId.RAW_PH,),
                    read_interval_s=5.0,
                    log_interval_s=120.0,
                    requires_pump_flow=True,
                    min_pump_on_seconds=60.0,
                    filtering=MeasurementFilterConfig(
                        filter_type=FilterType.BOXCAR,
                        window_seconds=120.0,
                    ),
                ),
            )
        ),
        clock=clock,
        sensor_drivers=[sensor],
    )

    first = await service.read_group(
        "chemistry",
        actuator_states={ActuatorId.PUMP_MOTOR: ActuatorState.ON},
        state_started_at={
            ActuatorId.PUMP_MOTOR: clock.now() - timedelta(seconds=61),
        },
    )
    second = await service.read_group(
        "chemistry",
        actuator_states={ActuatorId.PUMP_MOTOR: ActuatorState.OFF},
        state_started_at={ActuatorId.PUMP_MOTOR: clock.now()},
    )
    third = await service.read_group(
        "chemistry",
        actuator_states={ActuatorId.PUMP_MOTOR: ActuatorState.ON},
        state_started_at={
            ActuatorId.PUMP_MOTOR: clock.now() - timedelta(seconds=61),
        },
    )

    assert first.measurements[0].value == 7.4
    assert second.measurements[0].quality == Quality.SUSPECT
    assert second.measurements[0].metadata["filter"]["status"] == "skipped"
    assert second.loggable_measurements == ()
    assert third.measurements[0].value == 7.6
    assert third.measurements[0].metadata["filter"]["sample_count"] == 1


@pytest.mark.asyncio
async def test_multi_sensor_drivers_are_skipped_when_their_sensor_ids_are_not_due() -> None:
    clock = make_clock()
    pressure_driver = FakeMultiSensor(
        name="pressure_module",
        clock=clock,
        sensor_ids=(SensorId.PUMP_OUTPUT_PSI, SensorId.RAW_ORP),
        values={SensorId.PUMP_OUTPUT_PSI: 7.0, SensorId.RAW_ORP: 650.0},
    )
    chemistry_driver = FakeMultiSensor(
        name="orp_module",
        clock=clock,
        sensor_ids=(SensorId.RAW_ORP, SensorId.ORP_TEMP),
        values={SensorId.RAW_ORP: 650.0, SensorId.ORP_TEMP: 82.0},
        unit="mV",
    )
    service = AcquisitionService(
        config=AcquisitionConfig(
            groups=(
                AcquisitionGroupConfig(
                    name="pressures",
                    sensor_ids=(SensorId.PUMP_OUTPUT_PSI,),
                    read_interval_s=1.0,
                    log_interval_s=30.0,
                    oversampling=OversamplingConfig(
                        sample_count=3,
                        reducer=Reducer.MEDIAN,
                    ),
                ),
            )
        ),
        clock=clock,
        sensor_drivers=[],
        multi_sensor_drivers=[pressure_driver, chemistry_driver],
    )

    result = await service.read_group(
        "pressures",
        actuator_states=no_actuator_states(),
        state_started_at=no_state_started_at(),
    )

    assert pressure_driver.read_count == 3
    assert chemistry_driver.read_count == 0
    assert [measurement.sensor_id for measurement in result.measurements] == [
        SensorId.PUMP_OUTPUT_PSI,
    ]
    assert result.failures == ()


@pytest.mark.asyncio
async def test_flow_required_measurements_are_suspect_and_not_loggable_until_pump_runs() -> None:
    clock = make_clock()
    sensor = FakeSensor(
        name="raw_ph",
        sensor_id=SensorId.RAW_PH,
        clock=clock,
        values=[1.55, 1.56],
        unit="V",
    )
    service = AcquisitionService(
        config=AcquisitionConfig(
            groups=(
                AcquisitionGroupConfig(
                    name="chemistry",
                    sensor_ids=(SensorId.RAW_PH,),
                    read_interval_s=5.0,
                    log_interval_s=120.0,
                    requires_pump_flow=True,
                    min_pump_on_seconds=60.0,
                ),
            )
        ),
        clock=clock,
        sensor_drivers=[sensor],
    )

    pump_off_result = await service.read_group(
        "chemistry",
        actuator_states={ActuatorId.PUMP_MOTOR: ActuatorState.OFF},
        state_started_at={ActuatorId.PUMP_MOTOR: clock.now()},
    )

    assert pump_off_result.measurements[0].quality == Quality.SUSPECT
    assert pump_off_result.measurements[0].metadata["validity_reason"] == "pump_not_running"
    assert pump_off_result.loggable_measurements == ()
    assert pump_off_result.log_decisions[0].reason == "pump_not_running"

    pump_on_result = await service.read_group(
        "chemistry",
        actuator_states={ActuatorId.PUMP_MOTOR: ActuatorState.ON},
        state_started_at={
            ActuatorId.PUMP_MOTOR: clock.now() - timedelta(seconds=61),
        },
    )

    assert pump_on_result.measurements[0].quality == Quality.GOOD
    assert pump_on_result.measurements[0].metadata["pump_on_seconds"] == 61.0
    assert pump_on_result.loggable_measurements == pump_on_result.measurements


@pytest.mark.asyncio
async def test_poll_due_separates_read_interval_from_log_interval() -> None:
    clock = make_clock()
    sensor = FakeSensor(
        name="pump_output",
        sensor_id=SensorId.PUMP_OUTPUT_PSI,
        clock=clock,
        values=[1.0, 2.0, 3.0],
    )
    service = AcquisitionService(
        config=AcquisitionConfig(
            groups=(
                AcquisitionGroupConfig(
                    name="pressures",
                    sensor_ids=(SensorId.PUMP_OUTPUT_PSI,),
                    read_interval_s=0.5,
                    log_interval_s=30.0,
                ),
            )
        ),
        clock=clock,
        sensor_drivers=[sensor],
    )

    first = await service.poll_due(
        actuator_states=no_actuator_states(),
        state_started_at=no_state_started_at(),
    )
    immediate = await service.poll_due(
        actuator_states=no_actuator_states(),
        state_started_at=no_state_started_at(),
    )

    await clock.advance(0.5)
    second_read = await service.poll_due(
        actuator_states=no_actuator_states(),
        state_started_at=no_state_started_at(),
    )

    await clock.advance(29.5)
    third_read = await service.poll_due(
        actuator_states=no_actuator_states(),
        state_started_at=no_state_started_at(),
    )

    assert first.measurements[0].value == 1.0
    assert first.loggable_measurements == first.measurements
    assert immediate.measurements == ()
    assert second_read.measurements[0].value == 2.0
    assert second_read.loggable_measurements == ()
    assert second_read.log_decisions[0].reason == "log_interval_not_due"
    assert third_read.measurements[0].value == 3.0
    assert third_read.loggable_measurements == third_read.measurements


@pytest.mark.asyncio
async def test_log_interval_does_not_block_when_clock_moves_backwards() -> None:
    clock = make_clock()
    sensor = FakeSensor(
        name="cpu_temp",
        sensor_id=SensorId.CPU_TEMP,
        clock=clock,
        values=[50.0, 51.0],
        unit="degC",
    )
    service = AcquisitionService(
        config=AcquisitionConfig(
            groups=(
                AcquisitionGroupConfig(
                    name="pressures",
                    sensor_ids=(SensorId.CPU_TEMP,),
                    read_interval_s=0.5,
                    log_interval_s=30.0,
                ),
            )
        ),
        clock=clock,
        sensor_drivers=[sensor],
    )

    first = await service.poll_due(
        actuator_states=no_actuator_states(),
        state_started_at=no_state_started_at(),
    )
    assert first.loggable_measurements == first.measurements

    # Simulate system clock being corrected backwards (e.g. NTP step).
    service._last_logged_at[SensorId.CPU_TEMP] = clock.now() + timedelta(hours=8)  # type: ignore[attr-defined]
    await clock.advance(0.5)

    second = await service.poll_due(
        actuator_states=no_actuator_states(),
        state_started_at=no_state_started_at(),
    )
    assert second.measurements[0].value == 51.0
    assert second.loggable_measurements == second.measurements
    assert second.log_decisions[0].reason == "clock_moved_backwards"


@pytest.mark.asyncio
async def test_sensor_failures_do_not_block_other_measurements() -> None:
    clock = make_clock()
    good_sensor = FakeSensor(
        name="orp",
        sensor_id=SensorId.RAW_ORP,
        clock=clock,
        values=[650.0],
    )
    failing_sensor = FakeSensor(
        name="pump_output",
        sensor_id=SensorId.PUMP_OUTPUT_PSI,
        clock=clock,
        values=[7.0],
        fail_on_reads={1},
    )
    service = AcquisitionService(
        config=AcquisitionConfig(
            groups=(
                AcquisitionGroupConfig(
                    name="pressures",
                    sensor_ids=(SensorId.PUMP_OUTPUT_PSI, SensorId.RAW_ORP),
                    read_interval_s=1.0,
                    log_interval_s=30.0,
                ),
            )
        ),
        clock=clock,
        sensor_drivers=[failing_sensor, good_sensor],
    )

    result = await service.read_group(
        "pressures",
        actuator_states=no_actuator_states(),
        state_started_at=no_state_started_at(),
    )

    assert [measurement.sensor_id for measurement in result.measurements] == [
        SensorId.RAW_ORP,
    ]
    assert len(result.failures) == 1
    assert result.failures[0].sensor_id == SensorId.PUMP_OUTPUT_PSI
    assert result.failures[0].driver_name == "pump_output"
