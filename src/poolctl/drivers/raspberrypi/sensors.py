from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from glob import glob
from pathlib import Path
from typing import Any

from poolctl.domain.models import (
    Measurement,
    MeasurementKind,
    Quality,
    SensorId,
)
from poolctl.drivers.base import MultiSensorDriver, SensorDriver
from poolctl.drivers.modbus.registers import (
    ModbusRegisterDeviceConfig,
    ModbusRegisterTransport,
    PymodbusRtuRegisterTransport,
    signed_16,
)
from poolctl.drivers.modbus.rtu_bus import ModbusRtuBusRegistry, SharedModbusRtuBus
from poolctl.drivers.raspberrypi.analog_inputs import (
    build_waveshare_analog_driver_from_mapping,
)
from poolctl.services.clock import Clock


@dataclass(frozen=True)
class DFRobotWaterQualitySensorConfig:
    """
    Config for the DFRobot RS485 water-quality sensors.
    """

    ph: ModbusRegisterDeviceConfig
    orp: ModbusRegisterDeviceConfig

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any],
    ) -> DFRobotWaterQualitySensorConfig:
        return cls(
            ph=ModbusRegisterDeviceConfig.from_mapping(
                data,
                "modbus_ph_sensor",
                default_slave_id=2,
            ),
            orp=ModbusRegisterDeviceConfig.from_mapping(
                data,
                "modbus_orp_sensor",
                default_slave_id=3,
            ),
        )


class DFRobotPhSensor:
    """
    DFRobot SEN0708 pH sensor.

    Registers:
      - 0x0000: pH value, unsigned, actual pH * 100
    """

    name = "dfrobot_sen0708_ph"

    def __init__(
        self,
        *,
        transport: ModbusRegisterTransport,
        clock: Clock,
        slave_id: int,
    ) -> None:
        self._transport = transport
        self._clock = clock
        self._slave_id = slave_id

    async def read_all(self) -> list[Measurement]:
        ph_register, _temp_register = await self._transport.read_holding_registers(
            start_address=0x0000,
            count=2,
        )
        observed_at = self._clock.now()
        raw_ph = ph_register / 100.0

        return [
            Measurement(
                sensor_id=SensorId.RAW_PH,
                observed_at=observed_at,
                kind=MeasurementKind.RAW,
                value=round(raw_ph, 2),
                unit="pH",
                quality=Quality.GOOD,
                metadata={
                    "driver": self.name,
                    "modbus_slave_id": self._slave_id,
                    "raw_register": ph_register,
                    "register_address": "0x0000",
                },
            ),
        ]


class DFRobotOrpSensor:
    """
    DFRobot SEN0709 ORP + temperature sensor.

    Registers:
      - 0x0000: ORP mV, signed, actual value
      - 0x0001: temperature C, signed, actual temperature * 10

    The sensor reports temperature in C; we normalize to degF for
    consistency with the rest of poolctl temperature signals.
    """

    name = "dfrobot_sen0709_orp"

    def __init__(
        self,
        *,
        transport: ModbusRegisterTransport,
        clock: Clock,
        slave_id: int,
    ) -> None:
        self._transport = transport
        self._clock = clock
        self._slave_id = slave_id

    async def read_all(self) -> list[Measurement]:
        orp_register, temp_register = await self._transport.read_holding_registers(
            start_address=0x0000,
            count=2,
        )
        observed_at = self._clock.now()
        raw_orp_mv = signed_16(orp_register)
        temp_c = signed_16(temp_register) / 10.0
        temp_f = (temp_c * 9.0 / 5.0) + 32.0

        return [
            Measurement(
                sensor_id=SensorId.RAW_ORP,
                observed_at=observed_at,
                kind=MeasurementKind.RAW,
                value=float(raw_orp_mv),
                unit="mV",
                quality=Quality.GOOD,
                metadata={
                    "driver": self.name,
                    "modbus_slave_id": self._slave_id,
                    "raw_register": orp_register,
                    "register_address": "0x0000",
                },
            ),
            Measurement(
                sensor_id=SensorId.ORP_TEMP,
                observed_at=observed_at,
                kind=MeasurementKind.RAW,
                value=round(temp_f, 1),
                unit="degF",
                quality=Quality.GOOD,
                metadata={
                    "driver": self.name,
                    "modbus_slave_id": self._slave_id,
                    "raw_register": temp_register,
                    "register_address": "0x0001",
                    "raw_temp_c": round(temp_c, 1),
                },
            ),
        ]


class RaspberryPiCpuTempSensor:
    """
    Raspberry Pi SoC temperature sensor from Linux thermal sysfs.
    """

    name = "raspberrypi_cpu_temp"
    sensor_id = SensorId.CPU_TEMP

    def __init__(
        self,
        *,
        clock: Clock,
        sensor_file: Path = Path("/sys/class/thermal/thermal_zone0/temp"),
    ) -> None:
        self._clock = clock
        self._sensor_file = sensor_file

    async def read(self) -> Measurement:
        raw_text = self._sensor_file.read_text(encoding="utf-8").strip()
        raw_milli_c = int(raw_text)
        temp_c = raw_milli_c / 1000.0
        return Measurement(
            sensor_id=self.sensor_id,
            observed_at=self._clock.now(),
            kind=MeasurementKind.RAW,
            value=round(temp_c, 1),
            unit="degC",
            quality=Quality.GOOD,
            metadata={
                "driver": self.name,
                "source": str(self._sensor_file),
                "raw_milli_c": raw_milli_c,
            },
        )


class RaspberryPiCpuFanRpmSensor:
    """
    Raspberry Pi 5 fan RPM sensor from Linux hwmon sysfs.
    """

    name = "raspberrypi_cpu_fan_rpm"
    sensor_id = SensorId.CPU_FAN_RPM

    def __init__(
        self,
        *,
        clock: Clock,
        sensor_path_glob: str = "/sys/devices/platform/cooling_fan/hwmon/*/fan1_input",
    ) -> None:
        self._clock = clock
        self._sensor_path_glob = sensor_path_glob

    async def read(self) -> Measurement:
        candidates = sorted(glob(self._sensor_path_glob))
        if not candidates:
            raise FileNotFoundError(
                f"fan RPM sensor file not found for glob: {self._sensor_path_glob}"
            )
        sensor_path = Path(candidates[0])
        raw_text = sensor_path.read_text(encoding="utf-8").strip()
        raw_rpm = int(raw_text)
        return Measurement(
            sensor_id=self.sensor_id,
            observed_at=self._clock.now(),
            kind=MeasurementKind.RAW,
            value=float(raw_rpm),
            unit="rpm",
            quality=Quality.GOOD,
            metadata={
                "driver": self.name,
                "source": str(sensor_path),
                "source_glob": self._sensor_path_glob,
                "raw_rpm": raw_rpm,
            },
        )


def build_raspberrypi_sensors_from_mapping(
    data: Mapping[str, Any],
    *,
    clock: Clock,
    bus: SharedModbusRtuBus | None = None,
    bus_registry: ModbusRtuBusRegistry | None = None,
) -> list[MultiSensorDriver]:
    config = DFRobotWaterQualitySensorConfig.from_mapping(data)
    drivers: list[MultiSensorDriver] = []
    ph_bus = bus
    orp_bus = bus
    analog_bus = bus
    if bus is None and bus_registry is not None:
        ph_bus = bus_registry.bus_for(
            port=config.ph.port,
            baudrate=config.ph.baudrate,
            timeout_s=config.ph.timeout_s,
        )
        orp_bus = bus_registry.bus_for(
            port=config.orp.port,
            baudrate=config.orp.baudrate,
            timeout_s=config.orp.timeout_s,
        )
        analog_config = _optional_analog_device_config(data)
        if analog_config is not None:
            analog_bus = bus_registry.bus_for(
                port=analog_config.port,
                baudrate=analog_config.baudrate,
                timeout_s=analog_config.timeout_s,
            )

    if _bool_value(data, "enable_modbus_ph_sensor", False):
        drivers.append(
            DFRobotPhSensor(
                transport=PymodbusRtuRegisterTransport(config.ph, bus=ph_bus),
                clock=clock,
                slave_id=config.ph.slave_id,
            )
        )

    drivers.append(
        DFRobotOrpSensor(
            transport=PymodbusRtuRegisterTransport(config.orp, bus=orp_bus),
            clock=clock,
            slave_id=config.orp.slave_id,
        )
    )

    analog_driver = build_waveshare_analog_driver_from_mapping(
        data,
        clock=clock,
        bus=analog_bus,
    )
    if analog_driver is not None:
        drivers.append(analog_driver)

    return drivers


def _bool_value(data: Mapping[str, Any], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false")
    return value


def _optional_analog_device_config(
    data: Mapping[str, Any],
) -> ModbusRegisterDeviceConfig | None:
    section = data.get("modbus_analog_input")
    if not isinstance(section, Mapping):
        return None
    return ModbusRegisterDeviceConfig.from_mapping(
        data,
        "modbus_analog_input",
        default_slave_id=4,
    )


def build_raspberrypi_sensor_drivers_from_mapping(
    data: Mapping[str, Any],
    *,
    clock: Clock,
) -> list[SensorDriver]:
    cpu_temp_path = _string_value(
        _mapping_value(data, "cpu_temp_sensor", default={}),
        "path",
        "/sys/class/thermal/thermal_zone0/temp",
    )
    cpu_fan_path_glob = _string_value(
        _mapping_value(data, "cpu_fan_sensor", default={}),
        "path_glob",
        "/sys/devices/platform/cooling_fan/hwmon/*/fan1_input",
    )
    return [
        RaspberryPiCpuTempSensor(
            clock=clock,
            sensor_file=Path(cpu_temp_path),
        ),
        RaspberryPiCpuFanRpmSensor(
            clock=clock,
            sensor_path_glob=cpu_fan_path_glob,
        )
    ]


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


def _string_value(data: Mapping[str, Any], key: str, default: str) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value
