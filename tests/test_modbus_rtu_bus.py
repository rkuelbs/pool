"""
Tests for the shared async Modbus RTU bus wrapper.

These tests protect pymodbus compatibility, request serialization, retries, and
connection reuse behavior.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from poolctl.drivers.modbus import rtu_bus
from poolctl.drivers.modbus.rtu_bus import (
    ModbusRtuBusConfig,
    ModbusRtuBusRegistry,
    SharedModbusRtuBus,
)


def test_bus_registry_reuses_bus_for_same_link() -> None:
    registry = ModbusRtuBusRegistry()
    first = registry.bus_for(port="/dev/ttyUSB0", baudrate=9600, timeout_s=1.0)
    second = registry.bus_for(port="/dev/ttyUSB0", baudrate=9600, timeout_s=1.0)
    third = registry.bus_for(port="/dev/ttyUSB1", baudrate=9600, timeout_s=1.0)

    assert first is second
    assert first is not third


def test_raw_write_request_supports_modern_device_id_constructor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ModernPdu:
        def __init__(self, *, dev_id: int) -> None:
            self.initial_device_id = dev_id

    monkeypatch.setattr(
        rtu_bus,
        "_load_pymodbus_attribute",
        lambda *args, **kwargs: ModernPdu,
    )

    request = rtu_bus._raw_write_single_coil_request(
        slave_id=7,
        coil_address=0x0206,
        value=300,
    )

    assert isinstance(request, ModernPdu)
    assert request.initial_device_id == 7
    assert request.dev_id == 7
    assert request.slave_id == 7
    assert request.unit_id == 7
    assert request.slave == 7
    assert request.address == 0x0206
    assert request.value == 300
    assert request.function_code == 0x05
    assert request.rtu_frame_size == 8
    assert request.encode() == bytes.fromhex("0206012c")
    assert request.get_response_pdu_size() == 5


def test_raw_write_request_supports_legacy_slave_constructor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class LegacyPdu:
        def __init__(self, *, slave: int) -> None:
            self.initial_slave_id = slave

    monkeypatch.setattr(
        rtu_bus,
        "_load_pymodbus_attribute",
        lambda *args, **kwargs: LegacyPdu,
    )

    request = rtu_bus._raw_write_single_coil_request(
        slave_id=3,
        coil_address=4,
        value=5,
    )

    assert isinstance(request, LegacyPdu)
    assert request.initial_slave_id == 3
    assert request.slave == 3
    assert request.encode() == bytes.fromhex("00040005")


def test_raw_write_request_uses_installed_pymodbus() -> None:
    pytest.importorskip("pymodbus")

    request = rtu_bus._raw_write_single_coil_request(
        slave_id=7,
        coil_address=0x0206,
        value=300,
    )

    assert request.dev_id == 7
    assert request.encode() == bytes.fromhex("0206012c")


@pytest.mark.asyncio
async def test_connected_client_is_loaded_lazily_and_reused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_clients: list[FakeClient] = []

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.connected = False
            self.connect_calls = 0
            created_clients.append(self)

        async def connect(self) -> bool:
            self.connect_calls += 1
            self.connected = True
            return True

    def load_attribute(module_name: str, attribute_name: str, *, purpose: str) -> Any:
        assert module_name == "pymodbus.client"
        assert attribute_name == "AsyncModbusSerialClient"
        assert purpose == "Raspberry Pi Modbus drivers"
        return FakeClient

    monkeypatch.setattr(rtu_bus, "_load_pymodbus_attribute", load_attribute)
    bus = SharedModbusRtuBus(
        ModbusRtuBusConfig(
            port="/dev/ttyUSB0",
            baudrate=9600,
            timeout_s=1.5,
        )
    )

    first = await bus._connected_client()
    second = await bus._connected_client()

    assert first is second
    assert created_clients == [first]
    assert first.connect_calls == 1
    assert first.kwargs == {
        "port": "/dev/ttyUSB0",
        "baudrate": 9600,
        "timeout": 1.5,
        "bytesize": 8,
        "parity": "N",
        "stopbits": 1,
    }


def test_pymodbus_loader_reports_missing_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_module(module_name: str) -> Any:
        raise ImportError(module_name)

    monkeypatch.setitem(rtu_bus.__dict__, "import_module", missing_module)

    with pytest.raises(RuntimeError, match="pymodbus is required for relay tests"):
        rtu_bus._load_pymodbus_attribute(
            "pymodbus.pdu",
            "ModbusPDU",
            purpose="relay tests",
        )


def test_pymodbus_loader_reports_missing_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        rtu_bus.__dict__,
        "import_module",
        lambda module_name: SimpleNamespace(),
    )

    with pytest.raises(
        RuntimeError,
        match=r"installed pymodbus does not provide pymodbus\.pdu\.ModbusPDU",
    ):
        rtu_bus._load_pymodbus_attribute(
            "pymodbus.pdu",
            "ModbusPDU",
            purpose="relay tests",
        )
