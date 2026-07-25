from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

import pytest

from poolctl.domain.models import (
    ActuatorState,
    MeasurementKind,
    Quality,
    SensorId,
)
from poolctl.drivers.base import SensorDriver
from poolctl.drivers.simulated import plant as plant_module
from poolctl.drivers.simulated.plant import SimulatedPlant
from poolctl.drivers.simulated.sensors import (
    SimulatedSensor,
    build_default_simulated_sensors,
)
from poolctl.services.clock import SimulatedClock


def make_plant() -> SimulatedPlant:
    return SimulatedPlant(
        clock=SimulatedClock(
            start_at=datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc),
        )
    )


def sensor_by_id(
    sensors: list[SimulatedSensor],
    sensor_id: SensorId,
) -> SimulatedSensor:
    return next(sensor for sensor in sensors if sensor.sensor_id == sensor_id)


def no_noise(value: float, std_dev: float) -> float:
    return value


def disable_sensor_noise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plant_module, "noisy", no_noise)


def test_default_simulated_sensors_match_sensor_driver_protocol() -> None:
    plant = make_plant()

    sensors = build_default_simulated_sensors(plant)

    assert {sensor.sensor_id for sensor in sensors} == {
        SensorId.PUMP_OUTPUT_PSI,
        SensorId.FILTER_OUTPUT_PSI,
        SensorId.RETURN_PSI,
        SensorId.BUBBLER_PSI,
        SensorId.BOOSTER_PSI,
        SensorId.RAW_ORP,
        SensorId.ORP_TEMP,
        SensorId.RAW_PH,
        SensorId.PH_TEMP,
        SensorId.RAW_PH_VOLTAGE,
        SensorId.TEMP,
        SensorId.TANK_LEVEL,
    }
    assert all(isinstance(sensor, SensorDriver) for sensor in sensors)


@pytest.mark.asyncio
async def test_sensor_read_returns_raw_measurement_using_simulated_clock() -> None:
    plant = make_plant()
    sensor = sensor_by_id(
        build_default_simulated_sensors(plant),
        SensorId.TEMP,
    )

    reading = await sensor.read()

    assert reading.sensor_id == SensorId.TEMP
    assert reading.kind == MeasurementKind.RAW
    assert reading.quality == Quality.GOOD
    assert reading.unit == "degF"
    assert reading.observed_at == plant.clock.now()
    assert reading.metadata == {"driver": "simulated_temp"}


@pytest.mark.asyncio
async def test_pressure_sensor_rises_when_pump_runs_high_speed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disable_sensor_noise(monkeypatch)
    plant = make_plant()
    sensor = sensor_by_id(
        build_default_simulated_sensors(plant),
        SensorId.PUMP_OUTPUT_PSI,
    )

    pump_off = await sensor.read()

    plant.set_pump_motor(ActuatorState.ON)
    plant.set_pump_motor_speed(ActuatorState.HIGH)
    pump_high = await sensor.read()

    assert pump_off.value == 0.25
    assert pump_high.value == 12.0
    assert pump_high.value > pump_off.value


@pytest.mark.asyncio
async def test_booster_pressure_rises_when_booster_turns_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disable_sensor_noise(monkeypatch)
    plant = make_plant()
    sensor = sensor_by_id(
        build_default_simulated_sensors(plant),
        SensorId.BOOSTER_PSI,
    )

    plant.set_pump_motor(ActuatorState.ON)
    plant.set_pump_motor_speed(ActuatorState.HIGH)
    booster_off = await sensor.read()

    plant.set_booster_pump(ActuatorState.ON)
    booster_on = await sensor.read()

    assert booster_off.value == 5.0
    assert booster_on.value == 50.0
    assert booster_on.value > booster_off.value


@pytest.mark.asyncio
async def test_chemical_sensors_publish_raw_readings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disable_sensor_noise(monkeypatch)
    plant = make_plant()
    sensors = build_default_simulated_sensors(plant)

    raw_ph = await sensor_by_id(sensors, SensorId.RAW_PH).read()
    ph_temp = await sensor_by_id(sensors, SensorId.PH_TEMP).read()
    raw_orp = await sensor_by_id(sensors, SensorId.RAW_ORP).read()
    orp_temp = await sensor_by_id(sensors, SensorId.ORP_TEMP).read()

    assert raw_ph.kind == MeasurementKind.RAW
    assert raw_ph.unit == "pH"
    assert raw_ph.value == 7.55

    assert ph_temp.kind == MeasurementKind.RAW
    assert ph_temp.unit == "degF"
    assert ph_temp.value == orp_temp.value

    assert raw_orp.kind == MeasurementKind.RAW
    assert raw_orp.unit == "mV"
    assert raw_orp.value == 675.0


@pytest.mark.asyncio
async def test_chlorine_dosing_raises_orp_and_lowers_tank_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disable_sensor_noise(monkeypatch)
    plant = make_plant()
    sensors = build_default_simulated_sensors(plant)

    raw_orp_sensor = sensor_by_id(sensors, SensorId.RAW_ORP)
    tank_level_sensor = sensor_by_id(sensors, SensorId.TANK_LEVEL)

    initial_orp = await raw_orp_sensor.read()
    initial_tank_level = await tank_level_sensor.read()

    plant.set_chlorine_dosing_pump(ActuatorState.ON)
    await cast(SimulatedClock, plant.clock).advance(7200.0)

    dosed_orp = await raw_orp_sensor.read()
    dosed_tank_level = await tank_level_sensor.read()

    assert initial_orp.value == 675.0
    assert dosed_orp.value > initial_orp.value
    assert initial_tank_level.value == 100.0
    assert dosed_tank_level.value == 96.0
