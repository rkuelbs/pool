from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from glob import glob
from pathlib import Path
from typing import Any, Literal

from poolctl.domain.models import (
    Measurement,
    MeasurementKind,
    Quality,
    SensorId,
)
from poolctl.drivers.base import MultiSensorDriver, SensorDriver, SensorReadError
from poolctl.drivers.modbus.registers import (
    ModbusRegisterDeviceConfig,
    ModbusRegisterTransport,
    PymodbusRtuRegisterTransport,
    signed_16,
)
from poolctl.drivers.modbus.rtu_bus import (
    ModbusRtuBusConfig,
    ModbusRtuBusRegistry,
    SharedModbusRtuBus,
)
from poolctl.drivers.raspberrypi.analog_inputs import (
    build_waveshare_analog_driver_from_mapping,
)
from poolctl.services.clock import Clock


@dataclass(frozen=True)
class DFRobotSensorCircuitBreakerConfig:
    """
    Failure backoff for optional DFRobot RS485 chemistry probes.

    Once a probe has repeated Modbus failures, the driver temporarily skips
    reads so a missing ORP or pH sensor cannot delay the rest of the control
    loop on every acquisition cycle.
    """

    enabled: bool = True
    failure_threshold: int = 2
    cooldown_s: float = 60.0

    def __post_init__(self) -> None:
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if self.cooldown_s <= 0:
            raise ValueError("cooldown_s must be greater than zero")

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any],
    ) -> DFRobotSensorCircuitBreakerConfig:
        return cls(
            enabled=_bool_value(data, "enabled", True),
            failure_threshold=_int_value(data, "failure_threshold", 2),
            cooldown_s=_float_value(data, "cooldown_s", 60.0),
        )


class DFRobotSensorCircuitBreaker:
    """
    Mutable runtime state for one chemistry probe circuit breaker.
    """

    def __init__(
        self,
        *,
        config: DFRobotSensorCircuitBreakerConfig,
        clock: Clock,
        sensor_name: str,
    ) -> None:
        self._config = config
        self._clock = clock
        self._sensor_name = sensor_name
        self._consecutive_failures = 0
        self._open_until: datetime | None = None

    def assert_can_attempt(self) -> None:
        if not self._config.enabled:
            return

        now = self._clock.now()
        if self._open_until is None:
            return

        if now >= self._open_until:
            self._open_until = None
            return

        raise SensorReadError(
            f"{self._sensor_name} circuit breaker open until "
            f"{self._open_until.isoformat()} after "
            f"{self._consecutive_failures} consecutive failures"
        )

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._open_until = None

    def record_failure(self) -> None:
        if not self._config.enabled:
            return

        self._consecutive_failures += 1
        if self._consecutive_failures >= self._config.failure_threshold:
            self._open_until = self._clock.now() + timedelta(
                seconds=self._config.cooldown_s
            )


@dataclass(frozen=True)
class DFRobotWaterQualitySensorConfig:
    """
    Config for the DFRobot RS485 water-quality sensors.
    """

    ph: ModbusRegisterDeviceConfig
    orp: ModbusRegisterDeviceConfig
    ph_circuit_breaker: DFRobotSensorCircuitBreakerConfig = field(
        default_factory=DFRobotSensorCircuitBreakerConfig
    )
    orp_circuit_breaker: DFRobotSensorCircuitBreakerConfig = field(
        default_factory=DFRobotSensorCircuitBreakerConfig
    )

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any],
    ) -> DFRobotWaterQualitySensorConfig:
        ph_section = _mapping_value(data, "modbus_ph_sensor", default={})
        orp_section = _mapping_value(data, "modbus_orp_sensor", default={})
        return cls(
            ph=ModbusRegisterDeviceConfig.from_mapping(
                data,
                "modbus_ph_sensor",
                default_slave_id=4,
            ),
            orp=ModbusRegisterDeviceConfig.from_mapping(
                data,
                "modbus_orp_sensor",
                default_slave_id=3,
            ),
            ph_circuit_breaker=DFRobotSensorCircuitBreakerConfig.from_mapping(
                _mapping_value(ph_section, "circuit_breaker", default={})
            ),
            orp_circuit_breaker=DFRobotSensorCircuitBreakerConfig.from_mapping(
                _mapping_value(orp_section, "circuit_breaker", default={})
            ),
        )


DFROBOT_PH_CALIBRATION_START_REGISTER = 0x0120
DFROBOT_PH_LOW_POINT = 1
DFROBOT_PH_HIGH_POINT = 2


@dataclass(frozen=True)
class DFRobotPhCalibrationResult:
    """
    Result of a DFRobot SEN0708 pH calibration write.
    """

    slave_id: int
    point: Literal["low", "high"]
    ph_value: float
    register_address: int
    register_values: tuple[int, int]

    def as_payload(self) -> dict[str, Any]:
        return {
            "slave_id": self.slave_id,
            "point": self.point,
            "ph_value": self.ph_value,
            "register_address": f"0x{self.register_address:04X}",
            "register_values": list(self.register_values),
        }


class DFRobotPhSensor:
    """
    DFRobot SEN0708 pH sensor.

    Registers:
      - 0x0000: pH value, unsigned, actual pH * 100
      - 0x0001: temperature C, signed, actual temperature * 10

    The sensor reports temperature in C; we normalize to degF for
    consistency with the rest of poolctl temperature signals.
    """

    name = "dfrobot_sen0708_ph"
    sensor_ids = (SensorId.RAW_PH, SensorId.PH_TEMP)

    def __init__(
        self,
        *,
        transport: ModbusRegisterTransport,
        clock: Clock,
        slave_id: int,
        circuit_breaker: DFRobotSensorCircuitBreakerConfig | None = None,
    ) -> None:
        self._transport = transport
        self._clock = clock
        self._slave_id = slave_id
        self._circuit_breaker = DFRobotSensorCircuitBreaker(
            config=(
                circuit_breaker
                if circuit_breaker is not None
                else DFRobotSensorCircuitBreakerConfig()
            ),
            clock=clock,
            sensor_name=self.name,
        )

    async def read_all(self) -> list[Measurement]:
        self._circuit_breaker.assert_can_attempt()
        try:
            ph_register, temp_register = await self._transport.read_holding_registers(
                start_address=0x0000,
                count=2,
            )
        except Exception:
            self._circuit_breaker.record_failure()
            raise
        self._circuit_breaker.record_success()
        observed_at = self._clock.now()
        raw_ph = ph_register / 100.0
        temp_c = signed_16(temp_register) / 10.0
        temp_f = (temp_c * 9.0 / 5.0) + 32.0

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
            Measurement(
                sensor_id=SensorId.PH_TEMP,
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


async def calibrate_dfrobot_ph_sensor(
    *,
    config: ModbusRegisterDeviceConfig,
    point: Literal["low", "high"],
    ph_value: float,
    bus: SharedModbusRtuBus | None = None,
) -> DFRobotPhCalibrationResult:
    register_values = dfrobot_ph_calibration_register_values(
        point=point,
        ph_value=ph_value,
    )
    local_bus = bus is None
    if bus is None:
        active_bus = SharedModbusRtuBus(
            ModbusRtuBusConfig(
                port=config.port,
                baudrate=config.baudrate,
                timeout_s=config.timeout_s,
            )
        )
    else:
        active_bus = bus

    try:
        await active_bus.write_holding_registers(
            slave_id=config.slave_id,
            start_address=DFROBOT_PH_CALIBRATION_START_REGISTER,
            values=register_values,
        )
    finally:
        if local_bus:
            await active_bus.close()

    return DFRobotPhCalibrationResult(
        slave_id=config.slave_id,
        point=point,
        ph_value=ph_value,
        register_address=DFROBOT_PH_CALIBRATION_START_REGISTER,
        register_values=register_values,
    )


def dfrobot_ph_calibration_register_values(
    *,
    point: Literal["low", "high"],
    ph_value: float,
) -> tuple[int, int]:
    if point == "low":
        point_register = DFROBOT_PH_LOW_POINT
    elif point == "high":
        point_register = DFROBOT_PH_HIGH_POINT
    else:
        raise ValueError("point must be low or high")

    if not 0.0 < ph_value <= 14.0:
        raise ValueError("ph_value must be greater than 0 and less than or equal to 14")

    return point_register, int(round(ph_value * 100.0))


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
    sensor_ids = (SensorId.RAW_ORP, SensorId.ORP_TEMP)

    def __init__(
        self,
        *,
        transport: ModbusRegisterTransport,
        clock: Clock,
        slave_id: int,
        circuit_breaker: DFRobotSensorCircuitBreakerConfig | None = None,
    ) -> None:
        self._transport = transport
        self._clock = clock
        self._slave_id = slave_id
        self._circuit_breaker = DFRobotSensorCircuitBreaker(
            config=(
                circuit_breaker
                if circuit_breaker is not None
                else DFRobotSensorCircuitBreakerConfig()
            ),
            clock=clock,
            sensor_name=self.name,
        )

    async def read_all(self) -> list[Measurement]:
        self._circuit_breaker.assert_can_attempt()
        try:
            orp_register, temp_register = await self._transport.read_holding_registers(
                start_address=0x0000,
                count=2,
            )
        except Exception:
            self._circuit_breaker.record_failure()
            raise
        self._circuit_breaker.record_success()
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


class RaspberryPiCpuLoadSensor:
    """
    Raspberry Pi CPU utilization derived from successive /proc/stat samples.
    """

    name = "raspberrypi_cpu_load"
    sensor_id = SensorId.CPU_LOAD_PERCENT

    def __init__(
        self,
        *,
        clock: Clock,
        stat_file: Path = Path("/proc/stat"),
        cpu_count: int | None = None,
    ) -> None:
        self._clock = clock
        self._stat_file = stat_file
        self._cpu_count = max(1, cpu_count or (os.cpu_count() or 1))
        self._previous_total: int | None = None
        self._previous_idle: int | None = None

    async def read(self) -> Measurement:
        raw_text = self._stat_file.read_text(encoding="utf-8")
        total, idle = _parse_proc_stat_cpu_totals(raw_text)

        value = 0.0
        if self._previous_total is not None and self._previous_idle is not None:
            total_delta = total - self._previous_total
            idle_delta = idle - self._previous_idle
            if total_delta > 0:
                busy_delta = max(0, total_delta - idle_delta)
                value = max(0.0, min(100.0, 100.0 * busy_delta / total_delta))

        self._previous_total = total
        self._previous_idle = idle

        return Measurement(
            sensor_id=self.sensor_id,
            observed_at=self._clock.now(),
            kind=MeasurementKind.RAW,
            value=round(value, 1),
            unit="percent",
            quality=Quality.GOOD,
            metadata={
                "driver": self.name,
                "source": str(self._stat_file),
                "cpu_count": self._cpu_count,
                "raw_total_jiffies": total,
                "raw_idle_jiffies": idle,
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
        self._sensor_path_globs = (
            sensor_path_glob,
            "/sys/class/hwmon/hwmon*/fan1_input",
        )

    async def read(self) -> Measurement:
        source_glob: str | None = None
        candidates: list[str] = []
        for candidate_glob in self._sensor_path_globs:
            candidates = sorted(glob(candidate_glob))
            if candidates:
                source_glob = candidate_glob
                break
        if not candidates or source_glob is None:
            raise FileNotFoundError(
                "fan RPM sensor file not found for globs: "
                + ", ".join(self._sensor_path_globs)
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
                "source_glob": source_glob,
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
                circuit_breaker=config.ph_circuit_breaker,
            )
        )

    drivers.append(
        DFRobotOrpSensor(
            transport=PymodbusRtuRegisterTransport(config.orp, bus=orp_bus),
            clock=clock,
            slave_id=config.orp.slave_id,
            circuit_breaker=config.orp_circuit_breaker,
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


def _int_value(data: Mapping[str, Any], key: str, default: int) -> int:
    value = data.get(key, default)
    if not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _float_value(data: Mapping[str, Any], key: str, default: float) -> float:
    value = data.get(key, default)
    if not isinstance(value, int | float):
        raise ValueError(f"{key} must be a number")
    return float(value)


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
    cpu_load_stat_path = _string_value(
        _mapping_value(data, "cpu_load_sensor", default={}),
        "path",
        "/proc/stat",
    )
    return [
        RaspberryPiCpuTempSensor(
            clock=clock,
            sensor_file=Path(cpu_temp_path),
        ),
        RaspberryPiCpuLoadSensor(
            clock=clock,
            stat_file=Path(cpu_load_stat_path),
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


def _parse_proc_stat_cpu_totals(raw_text: str) -> tuple[int, int]:
    for line in raw_text.splitlines():
        if not line.startswith("cpu "):
            continue
        parts = line.split()
        if len(parts) < 5:
            break
        values = [int(part) for part in parts[1:]]
        total = sum(values)
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return total, idle
    raise ValueError("could not parse aggregate cpu totals from /proc/stat")
