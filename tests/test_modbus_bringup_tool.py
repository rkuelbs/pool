"""
Tests for the general Modbus bringup CLI helper.

The bringup tool is used before full poolctl deployment, so these tests verify
its scan/read/write/pulse command behavior without real hardware.
"""

from __future__ import annotations

import pytest

from poolctl.tools.modbus_bringup import _analog_check, _ph_check, _relay_check, _scan_slaves


class FakeBus:
    def __init__(self) -> None:
        self.coils_by_slave: dict[int, dict[int, bool]] = {}
        self.input_regs_by_slave: dict[int, tuple[int, ...]] = {}
        self.holding_regs_by_slave: dict[int, tuple[int, ...]] = {}
        self.writes: list[tuple[int, int, bool]] = []

    async def read_coils(
        self,
        *,
        slave_id: int,
        start_address: int,
        count: int,
    ) -> tuple[bool, ...]:
        if slave_id not in self.coils_by_slave:
            raise RuntimeError("no response")
        coil_map = self.coils_by_slave[slave_id]
        return tuple(coil_map.get(start_address + index, False) for index in range(count))

    async def write_coil(
        self,
        *,
        slave_id: int,
        coil_address: int,
        value: bool,
    ) -> None:
        if slave_id not in self.coils_by_slave:
            raise RuntimeError("no response")
        self.coils_by_slave[slave_id][coil_address] = value
        self.writes.append((slave_id, coil_address, value))

    async def read_input_registers(
        self,
        *,
        slave_id: int,
        start_address: int,
        count: int,
    ) -> tuple[int, ...]:
        del start_address
        if slave_id not in self.input_regs_by_slave:
            raise RuntimeError("no response")
        return self.input_regs_by_slave[slave_id][:count]

    async def read_holding_registers(
        self,
        *,
        slave_id: int,
        start_address: int,
        count: int,
    ) -> tuple[int, ...]:
        del start_address
        if slave_id not in self.holding_regs_by_slave:
            raise RuntimeError("no response")
        return self.holding_regs_by_slave[slave_id][:count]


@pytest.mark.asyncio
async def test_scan_slaves_finds_responsive_ids() -> None:
    bus = FakeBus()
    bus.coils_by_slave[1] = {0: False}
    bus.input_regs_by_slave[4] = (1200,)

    found = await _scan_slaves(bus=bus, min_id=1, max_id=5, probe="both")

    assert found == [1, 4]


@pytest.mark.asyncio
async def test_relay_check_reads_and_pulses_relay() -> None:
    bus = FakeBus()
    bus.coils_by_slave[1] = {0: False, 1: True, 2: False}

    result = await _relay_check(
        bus=bus,
        slave_id=1,
        relay_count=3,
        toggle_relay=2,
        toggle_seconds=0.001,
    )

    assert result.ok is True
    assert len(bus.writes) == 2
    assert bus.writes[0] == (1, 1, False)
    assert bus.writes[1] == (1, 1, True)


@pytest.mark.asyncio
async def test_analog_check_reads_input_registers() -> None:
    bus = FakeBus()
    bus.input_regs_by_slave[4] = (1000, 2500, 3000)

    result = await _analog_check(
        bus=bus,
        slave_id=4,
        channel_count=3,
        raw_to_volts_scale=0.001,
        raw_to_volts_offset=0.0,
    )

    assert result.ok is True
    assert "read 3 analog channels successfully" in result.message


@pytest.mark.asyncio
async def test_ph_check_reads_ph_and_temperature_registers() -> None:
    bus = FakeBus()
    bus.holding_regs_by_slave[4] = (0x0316, 0x0109)

    result = await _ph_check(bus=bus, slave_id=4)

    assert result.ok is True
    assert "read pH and pH temperature successfully" in result.message
