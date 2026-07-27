"""
Tests for register-level Modbus helper classes.

These tests exercise typed register reads/writes and value conversion helpers
without needing an actual serial adapter.
"""

from __future__ import annotations

from poolctl.drivers.modbus.registers import (
    ModbusRegisterDeviceConfig,
    signed_16,
)


def test_signed_16_converts_twos_complement_values() -> None:
    assert signed_16(0x0000) == 0
    assert signed_16(0x0135) == 309
    assert signed_16(0xFFF0) == -16
    assert signed_16(0x8000) == -32768


def test_modbus_register_device_config_uses_configurable_slave_id_and_serial() -> None:
    config = ModbusRegisterDeviceConfig.from_mapping(
        {
            "modbus_ph_sensor": {
                "port": "/dev/ttyUSB1",
                "slave_id": 7,
                "baudrate": 4800,
                "timeout_s": 0.25,
            }
        },
        "modbus_ph_sensor",
        default_slave_id=2,
    )

    assert config.port == "/dev/ttyUSB1"
    assert config.slave_id == 7
    assert config.baudrate == 4800
    assert config.timeout_s == 0.25


def test_modbus_register_device_config_uses_default_slave_id() -> None:
    config = ModbusRegisterDeviceConfig.from_mapping(
        {},
        "modbus_orp_sensor",
        default_slave_id=3,
    )

    assert config.port == "/dev/ttyUSB0"
    assert config.slave_id == 3
    assert config.baudrate == 9600
    assert config.timeout_s == 1.0
