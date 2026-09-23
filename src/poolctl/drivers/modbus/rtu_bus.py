"""
Shared asynchronous Modbus RTU serial bus.

Several devices can live on the same RS485 adapter, but only one Modbus request
should use the port at a time. This module owns the serial client, serializes
requests with an asyncio lock, and hides pymodbus version differences.
"""

from __future__ import annotations

import asyncio
import inspect
import struct
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from importlib import import_module
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

        # RS485 is a shared half-duplex bus. This lock makes one complete
        # Modbus transaction finish before another sensor or relay command uses
        # the same USB adapter.
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
            return await self._call_with_slave_id(
                client.write_coil,
                coil_address,
                value,
                slave_id=slave_id,
            )

        response = await self._request("write_coil", _call)
        _raise_for_modbus_error(response, "write coil")

    async def write_coil_raw_value(
        self,
        *,
        slave_id: int,
        coil_address: int,
        value: int,
    ) -> None:
        """
        Send Modbus function 05 with a raw 16-bit value.

        Standard Modbus single-coil writes only use 0xFF00 and 0x0000. The
        Waveshare relay module extends function 05 for timed flash commands,
        where the data field is a 100 ms count. Pymodbus' normal write_coil()
        helper intentionally hides that raw value, so this uses a tiny custom
        request PDU while keeping the same shared bus lock and retry behavior.
        """
        if not 0 <= value <= 0xFFFF:
            raise ValueError("raw coil value must fit in 16 bits")

        async def _call(client: Any) -> Any:
            request = _raw_write_single_coil_request(
                slave_id=slave_id,
                coil_address=coil_address,
                value=value,
            )
            return await _execute_custom_request(client, request)

        response = await self._request("write_coil_raw_value", _call)
        _raise_for_modbus_error(response, "write raw coil value")

    async def read_coils(
        self,
        *,
        slave_id: int,
        start_address: int,
        count: int,
    ) -> tuple[bool, ...]:
        async def _call(client: Any) -> Any:
            return await self._call_with_slave_id(
                client.read_coils,
                start_address,
                count=count,
                slave_id=slave_id,
            )

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
            return await self._call_with_slave_id(
                client.read_holding_registers,
                start_address,
                count=count,
                slave_id=slave_id,
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
            return await self._call_with_slave_id(
                client.write_register,
                register_address,
                value,
                slave_id=slave_id,
            )

        response = await self._request("write_holding_register", _call)
        _raise_for_modbus_error(response, "write holding register")

    async def write_holding_registers(
        self,
        *,
        slave_id: int,
        start_address: int,
        values: tuple[int, ...],
    ) -> None:
        async def _call(client: Any) -> Any:
            return await self._call_with_slave_id(
                client.write_registers,
                start_address,
                list(values),
                slave_id=slave_id,
            )

        response = await self._request("write_holding_registers", _call)
        _raise_for_modbus_error(response, "write holding registers")

    async def read_input_registers(
        self,
        *,
        slave_id: int,
        start_address: int,
        count: int,
    ) -> tuple[int, ...]:
        async def _call(client: Any) -> Any:
            return await self._call_with_slave_id(
                client.read_input_registers,
                start_address,
                count=count,
                slave_id=slave_id,
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

    async def _call_with_slave_id(
        self,
        method: Callable[..., Awaitable[Any]],
        *args: Any,
        slave_id: int,
        **kwargs: Any,
    ) -> Any:
        """
        Compatibility shim for pymodbus API differences:
        - older versions use `unit=...`
        - newer versions use `slave=...`
        """
        # Prefer explicit parameter names when discoverable.
        try:
            signature = inspect.signature(method)
            parameter_names = set(signature.parameters)
        except Exception:
            parameter_names = set()

        candidate_keys: list[str] = []
        for key in ("slave", "unit", "device_id"):
            if key in parameter_names:
                candidate_keys.append(key)
        if not candidate_keys:
            # Some pymodbus wrappers hide their real signature. Try the known
            # keyword names in order so the same code works across versions.
            candidate_keys = ["slave", "unit", "device_id"]

        last_type_error: TypeError | None = None
        for key in candidate_keys:
            try:
                return await method(*args, **kwargs, **{key: slave_id})
            except TypeError as error:
                last_type_error = error

        # Final fallback for APIs that require the slave id as positional.
        try:
            return await method(*args, slave_id, **kwargs)
        except TypeError:
            if last_type_error is not None:
                raise last_type_error
            raise

    async def _request(
        self,
        operation: str,
        call: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        async with self._lock:
            last_error: Exception | None = None
            max_attempts = max(1, self._config.retries + 1)

            for attempt in range(max_attempts):
                # Count attempts, not just successful operations. These stats
                # are shown in diagnostics when chasing bus timeouts.
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

                    # A failed serial request can leave the pymodbus client in a
                    # bad state, so close/recreate it before a retry.
                    await self._reset_client()
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(self._config.retry_backoff_s * (attempt + 1))

            if last_error is None:
                raise RuntimeError(f"modbus request failed: {operation}")

            raise RuntimeError(f"modbus request failed: {operation}: {last_error}") from last_error

    async def _connected_client(self) -> Any:
        if self._client is None:
            client_class = _load_pymodbus_attribute(
                "pymodbus.client",
                "AsyncModbusSerialClient",
                purpose="Raspberry Pi Modbus drivers",
            )

            self._client = client_class(
                port=self._config.port,
                baudrate=self._config.baudrate,
                timeout=self._config.timeout_s,
                bytesize=8,
                parity="N",
                stopbits=1,
            )

        # Some pymodbus versions keep the serial port open after the first
        # successful connect(). Re-calling connect() can attempt a second open
        # and fail with "Could not exclusively lock port".
        if bool(getattr(self._client, "connected", False)):
            return self._client

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


def _load_pymodbus_attribute(
    module_name: str,
    attribute_name: str,
    *,
    purpose: str,
) -> Any:
    try:
        module = import_module(module_name)
    except ImportError as error:
        raise RuntimeError(f"pymodbus is required for {purpose}") from error

    try:
        return getattr(module, attribute_name)
    except AttributeError as error:
        raise RuntimeError(
            f"installed pymodbus does not provide {module_name}.{attribute_name}"
        ) from error


def _raw_write_single_coil_request(
    *,
    slave_id: int,
    coil_address: int,
    value: int,
) -> Any:
    base_class = _load_pymodbus_attribute(
        "pymodbus.pdu",
        "ModbusPDU",
        purpose="raw Modbus relay writes",
    )

    class RawWriteSingleCoilRequest(base_class):  # type: ignore[valid-type, misc]
        function_code = 0x05
        rtu_frame_size = 8

        def __init__(self) -> None:
            try:
                super().__init__(dev_id=slave_id)
            except TypeError:
                try:
                    super().__init__(slave=slave_id)
                except TypeError:
                    super().__init__()

            self.address = coil_address
            self.value = value

            # Pymodbus has renamed the unit/slave/device id attribute across
            # major versions. Setting all common spellings keeps the custom PDU
            # usable with the same version range as the rest of poolctl.
            for attribute in ("dev_id", "slave_id", "unit_id", "slave"):
                try:
                    setattr(self, attribute, slave_id)
                except Exception:
                    pass

        def encode(self) -> bytes:
            return struct.pack(">HH", self.address, self.value)

        def decode(self, data: bytes) -> None:
            self.address, self.value = struct.unpack(">HH", data[:4])

        def get_response_pdu_size(self) -> int:
            return 5

    return RawWriteSingleCoilRequest()


async def _execute_custom_request(client: Any, request: Any) -> Any:
    execute = getattr(client, "execute", None)
    if execute is None:
        raise RuntimeError("pymodbus client does not support custom execute()")

    try:
        return await execute(False, request)
    except TypeError as first_error:
        try:
            return await execute(request)
        except TypeError:
            raise first_error
