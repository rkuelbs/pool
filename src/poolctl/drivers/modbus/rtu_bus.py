from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModbusRtuBusConfig:
    """
    Shared RTU bus config for one serial link.
    """

    port: str
    baudrate: int
    timeout_s: float
    retries: int = 1
    retry_backoff_s: float = 0.05


@dataclass(frozen=True)
class ModbusRtuBusStats:
    request_count: int = 0
    error_count: int = 0
    retry_count: int = 0
    last_error: str | None = None


class SharedModbusRtuBus:
    """
    Shared async Modbus RTU client with request serialization and retry.
    """

    def __init__(self, config: ModbusRtuBusConfig) -> None:
        self._config = config
        self._client: Any | None = None
        self._lock = asyncio.Lock()
        self._stats = ModbusRtuBusStats()

    @property
    def port(self) -> str:
        return self._config.port

    @property
    def stats(self) -> ModbusRtuBusStats:
        return self._stats

    async def write_coil(self, *, slave_id: int, coil_address: int, value: bool) -> None:
        async def _call(client: Any) -> Any:
            return await client.write_coil(coil_address, value, slave=slave_id)

        response = await self._request("write_coil", _call)
        _raise_for_modbus_error(response, "write coil")

    async def read_coils(
        self,
        *,
        slave_id: int,
        start_address: int,
        count: int,
    ) -> tuple[bool, ...]:
        async def _call(client: Any) -> Any:
            return await client.read_coils(start_address, count=count, slave=slave_id)

        response = await self._request("read_coils", _call)
        _raise_for_modbus_error(response, "read coils")

        bits = getattr(response, "bits", None)
        if not isinstance(bits, list):
            raise RuntimeError("read coils response did not include bits")

        return tuple(bool(value) for value in bits[:count])

    async def read_holding_registers(
        self,
        *,
        slave_id: int,
        start_address: int,
        count: int,
    ) -> tuple[int, ...]:
        async def _call(client: Any) -> Any:
            return await client.read_holding_registers(
                start_address,
                count=count,
                slave=slave_id,
            )

        response = await self._request("read_holding_registers", _call)
        _raise_for_modbus_error(response, "read holding registers")

        registers = getattr(response, "registers", None)
        if not isinstance(registers, list):
            raise RuntimeError("read holding registers response did not include registers")

        if len(registers) < count:
            raise RuntimeError(f"expected {count} registers, got {len(registers)}")

        return tuple(int(value) & 0xFFFF for value in registers[:count])

    async def write_holding_register(
        self,
        *,
        slave_id: int,
        register_address: int,
        value: int,
    ) -> None:
        async def _call(client: Any) -> Any:
            return await client.write_register(register_address, value, slave=slave_id)

        response = await self._request("write_holding_register", _call)
        _raise_for_modbus_error(response, "write holding register")

    async def read_input_registers(
        self,
        *,
        slave_id: int,
        start_address: int,
        count: int,
    ) -> tuple[int, ...]:
        async def _call(client: Any) -> Any:
            return await client.read_input_registers(
                start_address,
                count=count,
                slave=slave_id,
            )

        response = await self._request("read_input_registers", _call)
        _raise_for_modbus_error(response, "read input registers")

        registers = getattr(response, "registers", None)
        if not isinstance(registers, list):
            raise RuntimeError("read input registers response did not include registers")

        if len(registers) < count:
            raise RuntimeError(f"expected {count} registers, got {len(registers)}")

        return tuple(int(value) & 0xFFFF for value in registers[:count])

    async def close(self) -> None:
        if self._client is None:
            return

        close_result = self._client.close()
        if hasattr(close_result, "__await__"):
            await close_result
        self._client = None

    async def _request(
        self,
        operation: str,
        call: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        async with self._lock:
            last_error: Exception | None = None
            max_attempts = max(1, self._config.retries + 1)

            for attempt in range(max_attempts):
                self._stats = ModbusRtuBusStats(
                    request_count=self._stats.request_count + 1,
                    error_count=self._stats.error_count,
                    retry_count=self._stats.retry_count,
                    last_error=self._stats.last_error,
                )
                try:
                    client = await self._connected_client()
                    return await call(client)
                except Exception as error:
                    last_error = error
                    self._stats = ModbusRtuBusStats(
                        request_count=self._stats.request_count,
                        error_count=self._stats.error_count + 1,
                        retry_count=self._stats.retry_count + (1 if attempt < max_attempts - 1 else 0),
                        last_error=f"{operation}: {error}",
                    )
                    await self._reset_client()
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(self._config.retry_backoff_s * (attempt + 1))

            if last_error is None:
                raise RuntimeError(f"modbus request failed: {operation}")

            raise RuntimeError(f"modbus request failed: {operation}: {last_error}") from last_error

    async def _connected_client(self) -> Any:
        if self._client is None:
            try:
                from pymodbus.client import AsyncModbusSerialClient  # type: ignore[import-not-found]
            except ImportError as error:
                raise RuntimeError("pymodbus is required for Raspberry Pi Modbus drivers") from error

            self._client = AsyncModbusSerialClient(
                port=self._config.port,
                baudrate=self._config.baudrate,
                timeout=self._config.timeout_s,
                bytesize=8,
                parity="N",
                stopbits=1,
            )

        connected = await self._client.connect()
        if not connected:
            raise RuntimeError(f"could not connect to Modbus RTU bus on {self._config.port}")

        return self._client

    async def _reset_client(self) -> None:
        if self._client is None:
            return
        close_result = self._client.close()
        if hasattr(close_result, "__await__"):
            await close_result
        self._client = None


class ModbusRtuBusRegistry:
    """
    Reuse one SharedModbusRtuBus per serial link settings.
    """

    def __init__(self) -> None:
        self._buses: dict[tuple[str, int, float], SharedModbusRtuBus] = {}

    def bus_for(
        self,
        *,
        port: str,
        baudrate: int,
        timeout_s: float,
        retries: int = 1,
        retry_backoff_s: float = 0.05,
    ) -> SharedModbusRtuBus:
        key = (port, baudrate, timeout_s)
        if key not in self._buses:
            self._buses[key] = SharedModbusRtuBus(
                ModbusRtuBusConfig(
                    port=port,
                    baudrate=baudrate,
                    timeout_s=timeout_s,
                    retries=retries,
                    retry_backoff_s=retry_backoff_s,
                )
            )
        return self._buses[key]

    def stats(self) -> dict[str, ModbusRtuBusStats]:
        result: dict[str, ModbusRtuBusStats] = {}
        for key, bus in self._buses.items():
            port, baudrate, timeout_s = key
            result[f"{port}|{baudrate}|{timeout_s:g}"] = bus.stats
        return result

    async def close_all(self) -> None:
        for bus in self._buses.values():
            await bus.close()


def _raise_for_modbus_error(response: Any, operation: str) -> None:
    is_error = getattr(response, "isError", None)
    if callable(is_error) and is_error():
        raise RuntimeError(f"Modbus error during {operation}: {response}")
