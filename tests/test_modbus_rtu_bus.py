"""
Tests for the shared async Modbus RTU bus wrapper.

These tests protect pymodbus compatibility, request serialization, retries, and
connection reuse behavior.
"""

from __future__ import annotations

from poolctl.drivers.modbus.rtu_bus import ModbusRtuBusRegistry


def test_bus_registry_reuses_bus_for_same_link() -> None:
    registry = ModbusRtuBusRegistry()
    first = registry.bus_for(port="/dev/ttyUSB0", baudrate=9600, timeout_s=1.0)
    second = registry.bus_for(port="/dev/ttyUSB0", baudrate=9600, timeout_s=1.0)
    third = registry.bus_for(port="/dev/ttyUSB1", baudrate=9600, timeout_s=1.0)

    assert first is second
    assert first is not third
