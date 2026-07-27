"""
Tests for the DFRobot Modbus configuration CLI helper.

The tool is used during RS485 bringup, so tests focus on argument parsing and
the register writes produced for address/baud changes.
"""

from __future__ import annotations

import pytest

from poolctl.tools.dfrobot_device_config import _int_auto, _read_address, _read_baudrate


class FakeBus:
    def __init__(self, registers: dict[int, int]) -> None:
        self.registers = registers

    async def read_holding_registers(
        self,
        *,
        slave_id: int,
        start_address: int,
        count: int,
    ) -> tuple[int, ...]:
        del slave_id
        return tuple(self.registers[start_address + index] for index in range(count))


def test_int_auto_parses_decimal_and_hex() -> None:
    assert _int_auto("4") == 4
    assert _int_auto("0x04") == 4


@pytest.mark.asyncio
async def test_read_address_uses_dfrobot_address_register() -> None:
    bus = FakeBus({0x07D0: 0x0004})
    value = await _read_address(bus, 1)

    assert value == 0x04


@pytest.mark.asyncio
async def test_read_baudrate_decodes_dfrobot_baud_code() -> None:
    bus = FakeBus({0x07D1: 0x0001})
    value = await _read_baudrate(bus, 1)

    assert value == 4800
