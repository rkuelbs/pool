"""
Low-level Waveshare Modbus RTU relay board support.

This module knows how to read and write relay coils on the 8-channel relay
module. The rest of the controller maps pump, booster, and dosing commands onto
these relay numbers in Raspberry Pi actuator drivers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from poolctl.drivers.base import ActuatorError
from poolctl.drivers.modbus.rtu_bus import SharedModbusRtuBus


class ModbusRelayTransport(Protocol):
    """
    Minimal async transport needed by the relay board abstraction.
    """

    async def write_single_coil(self, *, coil_address: int, value: bool) -> None:
        """
        Write one Modbus coil.
        """
        ...

    async def read_coils(self, *, start_address: int, count: int) -> tuple[bool, ...]:
        """
        Read one or more Modbus coils.
        """
        ...


@dataclass(frozen=True)
class ModbusRelayBoardConfig:
    """
    Serial and Modbus settings for the Waveshare relay board.
    """

    port: str = "/dev/ttyUSB0"
    slave_id: int = 1
    baudrate: int = 9600
    timeout_s: float = 1.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ModbusRelayBoardConfig:
        modbus_data = _mapping_value(data, "modbus_relay", default={})

        return cls(
            port=_string_value(modbus_data, "port", cls.port),
            slave_id=_int_value(modbus_data, "slave_id", cls.slave_id),
            baudrate=_int_value(modbus_data, "baudrate", cls.baudrate),
            timeout_s=_float_value(modbus_data, "timeout_s", cls.timeout_s),
        )


class ModbusRelayBoard:
    """
    Waveshare Modbus RTU relay board abstraction.

    Public relay numbers are one-based because the board labels relays 1-8.
    Modbus coil addresses are zero-based, so relay 1 maps to coil 0.
    """

    def __init__(
        self,
        *,
        name: str,
        transport: ModbusRelayTransport,
        relay_count: int = 8,
    ) -> None:
        if relay_count < 1:
            raise ValueError("relay_count must be at least 1")

        self.name = name
        self._transport = transport
        self._relay_count = relay_count

    async def set_relay(self, relay_number: int, on: bool) -> None:
        self._validate_relay_number(relay_number)
        await self._transport.write_single_coil(
            coil_address=relay_number - 1,
            value=on,
        )

    async def read_relay(self, relay_number: int) -> bool:
        self._validate_relay_number(relay_number)
        values = await self._transport.read_coils(
            start_address=relay_number - 1,
            count=1,
        )

        if len(values) != 1:
            raise ActuatorError(
                f"{self.name} expected one coil value for relay {relay_number}, got {len(values)}"
            )

        return values[0]

    def _validate_relay_number(self, relay_number: int) -> None:
        if not 1 <= relay_number <= self._relay_count:
            raise ValueError(
                f"relay_number must be between 1 and {self._relay_count}; got {relay_number}"
            )


class PymodbusRtuRelayTransport:
    """
    Pymodbus-backed RTU transport.

    Importing pymodbus is delayed until the first operation so Windows tests and
    simulated development do not require Raspberry Pi serial dependencies.
    """

    def __init__(
        self,
        config: ModbusRelayBoardConfig,
        *,
        bus: SharedModbusRtuBus | None = None,
    ) -> None:
        self._config = config
        self._bus = bus

    async def write_single_coil(self, *, coil_address: int, value: bool) -> None:
        try:
            await self._shared_bus().write_coil(
                slave_id=self._config.slave_id,
                coil_address=coil_address,
                value=value,
            )
        except Exception as error:
            raise ActuatorError(str(error)) from error

    async def read_coils(self, *, start_address: int, count: int) -> tuple[bool, ...]:
        try:
            return await self._shared_bus().read_coils(
                slave_id=self._config.slave_id,
                start_address=start_address,
                count=count,
            )
        except Exception as error:
            raise ActuatorError(str(error)) from error

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


def build_modbus_relay_board(config: ModbusRelayBoardConfig) -> ModbusRelayBoard:
    return ModbusRelayBoard(
        name="waveshare_modbus_relay",
        transport=PymodbusRtuRelayTransport(config),
        relay_count=8,
    )


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
