from __future__ import annotations

from datetime import datetime, timezone

import pytest

from poolctl.domain.models import MeasurementKind, Quality, SensorId
from poolctl.drivers.base import MultiSensorDriver
from poolctl.drivers.raspberrypi.sensors import (
    DFRobotOrpSensor,
    DFRobotPhSensor,
    DFRobotWaterQualitySensorConfig,
    build_raspberrypi_sensors_from_mapping,
)
from poolctl.services.clock import SimulatedClock


class FakeRegisterTransport:
    def __init__(self, registers: tuple[int, ...]) -> None:
        self.registers = registers
        self.reads: list[tuple[int, int]] = []

    async def read_holding_registers(
        self,
        *,
        start_address: int,
        count: int,
    ) -> tuple[int, ...]:
        self.reads.append((start_address, count))
        return self.registers[:count]


def make_clock() -> SimulatedClock:
    return SimulatedClock(
        start_at=datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_dfrobot_ph_sensor_reads_raw_ph() -> None:
    clock = make_clock()
    transport = FakeRegisterTransport((0x0316, 0x0109))
    sensor = DFRobotPhSensor(
        transport=transport,
        clock=clock,
        slave_id=2,
    )

    measurements = await sensor.read_all()

    assert transport.reads == [(0x0000, 2)]
    assert [measurement.sensor_id for measurement in measurements] == [SensorId.RAW_PH]
    assert measurements[0].value == 7.9
    assert measurements[0].unit == "pH"
    assert measurements[0].kind == MeasurementKind.RAW
    assert measurements[0].quality == Quality.GOOD
    assert measurements[0].metadata["modbus_slave_id"] == 2
    assert measurements[0].metadata["raw_register"] == 0x0316

    assert measurements[0].observed_at == clock.now()


@pytest.mark.asyncio
async def test_dfrobot_ph_sensor_ignores_temperature_register() -> None:
    clock = make_clock()
    transport = FakeRegisterTransport((0x02BC, 0xFFF6))
    sensor = DFRobotPhSensor(
        transport=transport,
        clock=clock,
        slave_id=2,
    )

    measurements = await sensor.read_all()

    assert measurements[0].value == 7.0


@pytest.mark.asyncio
async def test_dfrobot_orp_sensor_reads_signed_orp_and_temperature() -> None:
    clock = make_clock()
    transport = FakeRegisterTransport((0x0135, 0x0101))
    sensor = DFRobotOrpSensor(
        transport=transport,
        clock=clock,
        slave_id=3,
    )

    measurements = await sensor.read_all()

    assert transport.reads == [(0x0000, 2)]
    assert [measurement.sensor_id for measurement in measurements] == [
        SensorId.RAW_ORP,
        SensorId.ORP_TEMP,
    ]
    assert measurements[0].value == 309.0
    assert measurements[0].unit == "mV"
    assert measurements[0].kind == MeasurementKind.RAW
    assert measurements[0].quality == Quality.GOOD
    assert measurements[0].metadata["modbus_slave_id"] == 3
    assert measurements[0].metadata["raw_register"] == 0x0135

    assert measurements[1].value == 25.7
    assert measurements[1].unit == "degC"
    assert measurements[1].observed_at == clock.now()


@pytest.mark.asyncio
async def test_dfrobot_orp_sensor_converts_signed_negative_orp() -> None:
    clock = make_clock()
    transport = FakeRegisterTransport((0xFFF0, 0x00FA))
    sensor = DFRobotOrpSensor(
        transport=transport,
        clock=clock,
        slave_id=3,
    )

    measurements = await sensor.read_all()

    assert measurements[0].value == -16.0
    assert measurements[1].value == 25.0


def test_dfrobot_water_quality_sensor_config_uses_configurable_addresses() -> None:
    config = DFRobotWaterQualitySensorConfig.from_mapping(
        {
            "modbus_ph_sensor": {
                "port": "/dev/ttyUSB1",
                "slave_id": 8,
                "baudrate": 4800,
                "timeout_s": 0.5,
            },
            "modbus_orp_sensor": {
                "port": "/dev/ttyUSB2",
                "slave_id": 9,
                "baudrate": 19200,
                "timeout_s": 0.75,
            },
        }
    )

    assert config.ph.port == "/dev/ttyUSB1"
    assert config.ph.slave_id == 8
    assert config.ph.baudrate == 4800
    assert config.ph.timeout_s == 0.5

    assert config.orp.port == "/dev/ttyUSB2"
    assert config.orp.slave_id == 9
    assert config.orp.baudrate == 19200
    assert config.orp.timeout_s == 0.75


def test_build_raspberrypi_sensors_from_mapping_returns_multi_sensor_drivers() -> None:
    sensors = build_raspberrypi_sensors_from_mapping(
        {
            "modbus_orp_sensor": {
                "port": "/dev/ttyUSB0",
                "slave_id": 3,
                "baudrate": 9600,
                "timeout_s": 1.0,
            }
        },
        clock=make_clock(),
    )

    assert len(sensors) == 1
    assert all(isinstance(sensor, MultiSensorDriver) for sensor in sensors)
