from __future__ import annotations

import pytest

from poolctl.tools.modbus_device_config import _int_auto, _read_address, _read_uart


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
    assert _int_auto("3") == 3
    assert _int_auto("0x03") == 3


@pytest.mark.asyncio
async def test_read_address_reads_low_byte() -> None:
    bus = FakeBus({0x4000: 0x0102})
    value = await _read_address(bus, 1)
    assert value == 0x02


@pytest.mark.asyncio
async def test_read_uart_decodes_parity_and_baud() -> None:
    # parity=E => 0x01, baud=4800 => 0x00
    bus = FakeBus({0x2000: 0x0100})
    uart = await _read_uart(bus, 1)
    assert uart.parity == "E"
    assert uart.baudrate == 4800
