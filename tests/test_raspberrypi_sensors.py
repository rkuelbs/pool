from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from poolctl.domain.models import MeasurementKind, Quality, SensorId
from poolctl.drivers.base import MultiSensorDriver
from poolctl.drivers.raspberrypi.sensors import (
    DFRobotOrpSensor,
    calibrate_dfrobot_ph_sensor,
    DFRobotPhSensor,
    RaspberryPiCpuFanRpmSensor,
    RaspberryPiCpuLoadSensor,
    RaspberryPiCpuTempSensor,
    DFRobotWaterQualitySensorConfig,
    build_raspberrypi_sensor_drivers_from_mapping,
    build_raspberrypi_sensors_from_mapping,
    dfrobot_ph_calibration_register_values,
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


class FakeModbusBus:
    def __init__(self) -> None:
        self.writes: list[tuple[int, int, tuple[int, ...]]] = []

    async def write_holding_registers(
        self,
        *,
        slave_id: int,
        start_address: int,
        values: tuple[int, ...],
    ) -> None:
        self.writes.append((slave_id, start_address, values))


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
        slave_id=4,
    )

    measurements = await sensor.read_all()

    assert transport.reads == [(0x0000, 2)]
    assert [measurement.sensor_id for measurement in measurements] == [
        SensorId.RAW_PH,
        SensorId.PH_TEMP,
    ]
    assert measurements[0].value == 7.9
    assert measurements[0].unit == "pH"
    assert measurements[0].kind == MeasurementKind.RAW
    assert measurements[0].quality == Quality.GOOD
    assert measurements[0].metadata["modbus_slave_id"] == 4
    assert measurements[0].metadata["raw_register"] == 0x0316

    assert measurements[1].value == 79.7
    assert measurements[1].unit == "degF"
    assert measurements[1].kind == MeasurementKind.RAW
    assert measurements[1].quality == Quality.GOOD
    assert measurements[1].metadata["modbus_slave_id"] == 4
    assert measurements[1].metadata["raw_register"] == 0x0109
    assert measurements[1].metadata["raw_temp_c"] == 26.5

    assert measurements[0].observed_at == clock.now()
    assert measurements[1].observed_at == clock.now()


@pytest.mark.asyncio
async def test_dfrobot_ph_sensor_reads_signed_temperature_register() -> None:
    clock = make_clock()
    transport = FakeRegisterTransport((0x02BC, 0xFFF6))
    sensor = DFRobotPhSensor(
        transport=transport,
        clock=clock,
        slave_id=4,
    )

    measurements = await sensor.read_all()

    assert measurements[0].value == 7.0
    assert measurements[1].value == 30.2
    assert measurements[1].metadata["raw_temp_c"] == -1.0


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

    assert measurements[1].value == 78.3
    assert measurements[1].unit == "degF"
    assert measurements[1].metadata["raw_temp_c"] == 25.7
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
    assert measurements[1].value == 77.0


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


def test_dfrobot_water_quality_sensor_config_defaults_to_non_conflicting_ph_address() -> None:
    config = DFRobotWaterQualitySensorConfig.from_mapping({})

    assert config.ph.slave_id == 4


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


def test_build_raspberrypi_sensors_from_mapping_includes_enabled_ph_sensor() -> None:
    sensors = build_raspberrypi_sensors_from_mapping(
        {
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
        },
        clock=make_clock(),
    )

    assert len(sensors) == 2
    assert all(isinstance(sensor, MultiSensorDriver) for sensor in sensors)


def test_dfrobot_ph_calibration_register_values_scale_ph() -> None:
    assert dfrobot_ph_calibration_register_values(point="low", ph_value=4.01) == (1, 401)
    assert dfrobot_ph_calibration_register_values(point="high", ph_value=9.18) == (2, 918)


@pytest.mark.asyncio
async def test_calibrate_dfrobot_ph_sensor_writes_two_registers() -> None:
    bus = FakeModbusBus()
    config = DFRobotWaterQualitySensorConfig.from_mapping(
        {
            "modbus_ph_sensor": {
                "port": "/dev/ttyUSB0",
                "slave_id": 4,
                "baudrate": 4800,
                "timeout_s": 1.0,
            }
        }
    ).ph

    result = await calibrate_dfrobot_ph_sensor(
        config=config,
        point="low",
        ph_value=4.01,
        bus=bus,
    )

    assert bus.writes == [(4, 0x0120, (1, 401))]
    assert result.as_payload()["register_address"] == "0x0120"


@pytest.mark.asyncio
async def test_raspberrypi_cpu_temp_sensor_reads_sysfs_millidegrees(
    tmp_path: Path,
) -> None:
    clock = make_clock()
    sensor_file = tmp_path / "cpu_temp"
    sensor_file.write_text("51437\n", encoding="utf-8")
    sensor = RaspberryPiCpuTempSensor(clock=clock, sensor_file=sensor_file)

    measurement = await sensor.read()

    assert measurement.sensor_id == SensorId.CPU_TEMP
    assert measurement.value == 51.4
    assert measurement.unit == "degC"
    assert measurement.kind == MeasurementKind.RAW
    assert measurement.quality == Quality.GOOD
    assert measurement.metadata["raw_milli_c"] == 51437


def test_build_raspberrypi_sensor_drivers_from_mapping_allows_cpu_temp_path_override(
    tmp_path: Path,
) -> None:
    clock = make_clock()
    path = tmp_path / "cpu_override"
    load_path = tmp_path / "proc_stat"
    fan_path = tmp_path / "fan" / "fan1_input"
    drivers = build_raspberrypi_sensor_drivers_from_mapping(
        {
            "cpu_temp_sensor": {"path": str(path)},
            "cpu_load_sensor": {"path": str(load_path)},
            "cpu_fan_sensor": {"path_glob": str(fan_path)},
        },
        clock=clock,
    )

    assert len(drivers) == 3
    assert isinstance(drivers[0], RaspberryPiCpuTempSensor)
    assert isinstance(drivers[1], RaspberryPiCpuLoadSensor)
    assert isinstance(drivers[2], RaspberryPiCpuFanRpmSensor)


@pytest.mark.asyncio
async def test_raspberrypi_cpu_fan_rpm_sensor_reads_sysfs_glob(
    tmp_path: Path,
) -> None:
    clock = make_clock()
    fan_file = tmp_path / "cooling_fan" / "hwmon" / "hwmon9" / "fan1_input"
    fan_file.parent.mkdir(parents=True, exist_ok=True)
    fan_file.write_text("2789\n", encoding="utf-8")
    sensor = RaspberryPiCpuFanRpmSensor(
        clock=clock,
        sensor_path_glob=str(tmp_path / "cooling_fan" / "hwmon" / "*" / "fan1_input"),
    )

    measurement = await sensor.read()

    assert measurement.sensor_id == SensorId.CPU_FAN_RPM
    assert measurement.value == 2789.0
    assert measurement.unit == "rpm"
    assert measurement.kind == MeasurementKind.RAW
    assert measurement.quality == Quality.GOOD
    assert measurement.metadata["raw_rpm"] == 2789


@pytest.mark.asyncio
async def test_raspberrypi_cpu_load_sensor_reads_proc_stat(
    tmp_path: Path,
) -> None:
    clock = make_clock()
    stat_file = tmp_path / "proc_stat"
    stat_file.write_text("cpu  100 0 50 850 0 0 0 0 0 0\n", encoding="utf-8")
    sensor = RaspberryPiCpuLoadSensor(clock=clock, stat_file=stat_file, cpu_count=4)

    first = await sensor.read()
    stat_file.write_text("cpu  130 0 70 900 0 0 0 0 0 0\n", encoding="utf-8")
    second = await sensor.read()

    assert first.sensor_id == SensorId.CPU_LOAD_PERCENT
    assert first.value == 0.0
    assert first.unit == "percent"
    assert first.kind == MeasurementKind.RAW
    assert first.quality == Quality.GOOD
    assert first.metadata["raw_total_jiffies"] == 1000
    assert first.metadata["raw_idle_jiffies"] == 850

    assert second.sensor_id == SensorId.CPU_LOAD_PERCENT
    assert second.value == 50.0
    assert second.unit == "percent"
    assert second.metadata["raw_total_jiffies"] == 1100
    assert second.metadata["raw_idle_jiffies"] == 900
