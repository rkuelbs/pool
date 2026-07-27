"""
Tests for low-level Modbus relay board behavior.

The relay board driver maps logical relay numbers to Modbus coils, so tests
verify coil addressing and state reads/writes.
"""

from __future__ import annotations

import pytest

from poolctl.drivers.base import ActuatorError
from poolctl.drivers.modbus.relay_board import (
    ModbusRelayBoard,
    ModbusRelayBoardConfig,
)


class FakeRelayTransport:
    def __init__(self, coils: dict[int, bool] | None = None) -> None:
        self.coils = coils if coils is not None else {}
        self.writes: list[tuple[int, bool]] = []
        self.reads: list[tuple[int, int]] = []
        self.read_count_override: int | None = None

    async def write_single_coil(self, *, coil_address: int, value: bool) -> None:
        self.coils[coil_address] = value
        self.writes.append((coil_address, value))

    async def read_coils(self, *, start_address: int, count: int) -> tuple[bool, ...]:
        self.reads.append((start_address, count))

        if self.read_count_override is not None:
            return tuple(False for _ in range(self.read_count_override))

        return tuple(self.coils.get(start_address + offset, False) for offset in range(count))


@pytest.mark.asyncio
async def test_set_relay_maps_one_based_relay_to_zero_based_coil() -> None:
    transport = FakeRelayTransport()
    board = ModbusRelayBoard(name="test_board", transport=transport)

    await board.set_relay(1, True)
    await board.set_relay(4, False)

    assert transport.writes == [(0, True), (3, False)]
    assert transport.coils == {0: True, 3: False}


@pytest.mark.asyncio
async def test_read_relay_maps_one_based_relay_to_zero_based_coil() -> None:
    transport = FakeRelayTransport(coils={2: True})
    board = ModbusRelayBoard(name="test_board", transport=transport)

    relay_on = await board.read_relay(3)

    assert relay_on is True
    assert transport.reads == [(2, 1)]


@pytest.mark.asyncio
async def test_read_relay_rejects_unexpected_response_length() -> None:
    transport = FakeRelayTransport()
    transport.read_count_override = 2
    board = ModbusRelayBoard(name="test_board", transport=transport)

    with pytest.raises(ActuatorError):
        await board.read_relay(1)


def test_modbus_relay_board_config_loads_defaults_and_overrides() -> None:
    config = ModbusRelayBoardConfig.from_mapping(
        {
            "modbus_relay": {
                "port": "/dev/ttyUSB1",
                "slave_id": 2,
                "baudrate": 19200,
                "timeout_s": 0.5,
            }
        }
    )

    assert config.port == "/dev/ttyUSB1"
    assert config.slave_id == 2
    assert config.baudrate == 19200
    assert config.timeout_s == 0.5
