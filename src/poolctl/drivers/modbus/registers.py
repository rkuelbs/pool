from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from poolctl.drivers.base import SensorReadError
from poolctl.drivers.modbus.rtu_bus import SharedModbusRtuBus


class ModbusRegisterTransport(Protocol):
    """
    Minimal async transport for Modbus register-based sensors.
    """

    async def read_holding_registers(
        self,
        *,
        start_address: int,
        count: int,
    ) -> tuple[int, ...]:
        """
        Read holding registers using function code 0x03.
        """
        ...

    async def read_input_registers(
        self,
        *,
        start_address: int,
        count: int,
    ) -> tuple[int, ...]:
        """
        Read input registers using function code 0x04.
        """
        ...

    async def write_holding_register(
        self,
        *,
        register_address: int,
        value: int,
    ) -> None:
        """
        Write one holding register using function code 0x06.
        """
        ...


@dataclass(frozen=True)
class ModbusRegisterDeviceConfig:
    """
    Serial and Modbus address settings for one register-based device.
    """

    port: str = "/dev/ttyUSB0"
    slave_id: int = 1
    baudrate: int = 9600
    timeout_s: float = 1.0

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any],
        section: str,
        *,
        default_slave_id: int,
    ) -> ModbusRegisterDeviceConfig:
        device_data = _mapping_value(data, section, default={})

        return cls(
            port=_string_value(device_data, "port", cls.port),
            slave_id=_int_value(device_data, "slave_id", default_slave_id),
            baudrate=_int_value(device_data, "baudrate", cls.baudrate),
            timeout_s=_float_value(device_data, "timeout_s", cls.timeout_s),
        )


class PymodbusRtuRegisterTransport:
    """
    Pymodbus-backed RTU register transport.
    """

    def __init__(
        self,
        config: ModbusRegisterDeviceConfig,
        *,
        bus: SharedModbusRtuBus | None = None,
    ) -> None:
        self._config = config
        self._bus = bus

    async def read_holding_registers(
        self,
        *,
        start_address: int,
        count: int,
    ) -> tuple[int, ...]:
        try:
            return await self._shared_bus().read_holding_registers(
                slave_id=self._config.slave_id,
                start_address=start_address,
                count=count,
            )
        except Exception as error:
            raise SensorReadError(str(error)) from error

    async def read_input_registers(
        self,
        *,
        start_address: int,
        count: int,
    ) -> tuple[int, ...]:
        try:
            return await self._shared_bus().read_input_registers(
                slave_id=self._config.slave_id,
                start_address=start_address,
                count=count,
            )
        except Exception as error:
            raise SensorReadError(str(error)) from error

    async def write_holding_register(
        self,
        *,
        register_address: int,
        value: int,
    ) -> None:
        try:
            await self._shared_bus().write_holding_register(
                slave_id=self._config.slave_id,
                register_address=register_address,
                value=value,
            )
        except Exception as error:
            raise SensorReadError(str(error)) from error

    async def close(self) -> None:
        if self._bus is None:
            return
        await self._bus.close()

    def _shared_bus(self) -> SharedModbusRtuBus:
        if self._bus is None:
            from poolctl.drivers.modbus.rtu_bus import ModbusRtuBusConfig, SharedModbusRtuBus

            self._bus = SharedModbusRtuBus(
                ModbusRtuBusConfig(
                    port=self._config.port,
                    baudrate=self._config.baudrate,
                    timeout_s=self._config.timeout_s,
                )
            )
        return self._bus


def signed_16(value: int) -> int:
    value &= 0xFFFF
    if value >= 0x8000:
        return value - 0x10000

    return value


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
