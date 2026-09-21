"""
Tests for Raspberry Pi relay-backed actuator drivers.

These tests verify domain ON/OFF/LOW/HIGH commands translate into the expected
Waveshare relay coil states.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from poolctl.domain.models import (
    ACTUATOR_AUTO_OFF_AT_METADATA,
    ACTUATOR_ON_PULSE_SECONDS_METADATA,
    ActuatorCommand,
    ActuatorId,
    ActuatorState,
    CommandSource,
)
from poolctl.drivers.base import ActuatorDriver, ActuatorError
from poolctl.drivers.modbus.relay_board import ModbusRelayBoard
from poolctl.drivers.raspberrypi.actuators import (
    RelayActuatorConfig,
    build_modbus_relay_actuators,
)
from poolctl.services.clock import SimulatedClock
from poolctl.services.command_router import CommandRouter
from poolctl.services.safety import SafetyGate


class FakeRelayTransport:
    def __init__(self) -> None:
        self.coils: dict[int, bool] = {}
        self.writes: list[tuple[int, bool]] = []
        self.raw_writes: list[tuple[int, int]] = []

    async def write_single_coil(self, *, coil_address: int, value: bool) -> None:
        self.coils[coil_address] = value
        self.writes.append((coil_address, value))

    async def write_single_coil_raw_value(self, *, coil_address: int, value: int) -> None:
        self.raw_writes.append((coil_address, value))

    async def read_coils(self, *, start_address: int, count: int) -> tuple[bool, ...]:
        return tuple(self.coils.get(start_address + offset, False) for offset in range(count))


def make_clock() -> SimulatedClock:
    return SimulatedClock(
        start_at=datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc),
    )


def make_drivers() -> tuple[FakeRelayTransport, list[ActuatorDriver], SimulatedClock]:
    transport = FakeRelayTransport()
    board = ModbusRelayBoard(name="test_board", transport=transport)
    clock = make_clock()
    drivers: list[ActuatorDriver] = list(
        build_modbus_relay_actuators(
            board=board,
            config=RelayActuatorConfig.from_mapping(
                {
                    "modbus_relay": {
                        "relays": {
                            "pump_motor": 1,
                            "pump_motor_speed": 2,
                            "booster_pump": 3,
                            "chlorine_dosing_pump": 4,
                        },
                        "pump_speed_relay": {
                            "low_state": "on",
                            "high_state": "off",
                        },
                    }
                }
            ),
            clock=clock,
        )
    )

    return transport, drivers, clock


def driver_by_id(
    drivers: list[ActuatorDriver],
    actuator_id: ActuatorId,
) -> ActuatorDriver:
    return next(driver for driver in drivers if driver.actuator_id == actuator_id)


def command(
    clock: SimulatedClock,
    actuator_id: ActuatorId,
    state: ActuatorState,
    *,
    metadata: dict[str, object] | None = None,
) -> ActuatorCommand:
    return ActuatorCommand(
        actuator_id=actuator_id,
        created_at=clock.now(),
        state=state,
        requested_by=CommandSource.MANUAL,
        reason="unit test",
        metadata=metadata or {},
    )


def test_raspberrypi_modbus_actuators_match_protocol() -> None:
    _, drivers, _ = make_drivers()

    assert {driver.actuator_id for driver in drivers} == {
        ActuatorId.PUMP_MOTOR,
        ActuatorId.PUMP_MOTOR_SPEED,
        ActuatorId.BOOSTER_PUMP,
        ActuatorId.CHLORINE_DOSING_PUMP,
    }
    assert all(isinstance(driver, ActuatorDriver) for driver in drivers)


def test_default_relay_mapping_uses_relay_6_for_dosing_pump() -> None:
    config = RelayActuatorConfig.from_mapping({})

    assert config.relays[ActuatorId.CHLORINE_DOSING_PUMP] == 6
    assert config.dosing_uses_flash is True


@pytest.mark.asyncio
async def test_pump_motor_on_writes_relay_1_on() -> None:
    transport, drivers, clock = make_drivers()
    driver = driver_by_id(drivers, ActuatorId.PUMP_MOTOR)

    sample = await driver.apply(
        command(clock, ActuatorId.PUMP_MOTOR, ActuatorState.ON)
    )

    assert transport.writes == [(0, True)]
    assert sample.state == ActuatorState.ON
    assert sample.metadata["relay_number"] == 1
    assert sample.metadata["relay_on"] is True


@pytest.mark.asyncio
async def test_pump_speed_uses_configured_off_high_on_low_polarity() -> None:
    transport, drivers, clock = make_drivers()
    driver = driver_by_id(drivers, ActuatorId.PUMP_MOTOR_SPEED)

    high_sample = await driver.apply(
        command(clock, ActuatorId.PUMP_MOTOR_SPEED, ActuatorState.HIGH)
    )
    low_sample = await driver.apply(
        command(clock, ActuatorId.PUMP_MOTOR_SPEED, ActuatorState.LOW)
    )

    assert transport.writes == [(1, False), (1, True)]
    assert high_sample.metadata["relay_on"] is False
    assert low_sample.metadata["relay_on"] is True


@pytest.mark.asyncio
async def test_dosing_pump_on_uses_timed_flash_relay_command() -> None:
    transport, drivers, clock = make_drivers()
    driver = driver_by_id(drivers, ActuatorId.CHLORINE_DOSING_PUMP)
    auto_off_at = clock.now() + timedelta(seconds=30.0)

    sample = await driver.apply(
        command(
            clock,
            ActuatorId.CHLORINE_DOSING_PUMP,
            ActuatorState.ON,
            metadata={
                ACTUATOR_ON_PULSE_SECONDS_METADATA: 30.0,
                ACTUATOR_AUTO_OFF_AT_METADATA: auto_off_at.isoformat(),
            },
        )
    )

    assert transport.writes == []
    assert transport.raw_writes == [(0x0203, 300)]
    assert sample.state == ActuatorState.ON
    assert sample.metadata["timed_flash_on"] is True
    assert sample.metadata["pulse_ticks_100ms"] == 300
    assert sample.metadata[ACTUATOR_AUTO_OFF_AT_METADATA] == auto_off_at.isoformat()


@pytest.mark.asyncio
async def test_dosing_pump_flash_mode_rejects_on_without_pulse_seconds() -> None:
    _, drivers, clock = make_drivers()
    driver = driver_by_id(drivers, ActuatorId.CHLORINE_DOSING_PUMP)

    with pytest.raises(ActuatorError):
        await driver.apply(
            command(clock, ActuatorId.CHLORINE_DOSING_PUMP, ActuatorState.ON)
        )


@pytest.mark.asyncio
async def test_dosing_pump_off_still_sends_normal_off_command() -> None:
    transport, drivers, clock = make_drivers()
    driver = driver_by_id(drivers, ActuatorId.CHLORINE_DOSING_PUMP)

    sample = await driver.apply(
        command(clock, ActuatorId.CHLORINE_DOSING_PUMP, ActuatorState.OFF)
    )

    assert transport.raw_writes == []
    assert transport.writes == [(3, False)]
    assert sample.state == ActuatorState.OFF


@pytest.mark.asyncio
async def test_command_router_expires_flash_dosing_state_without_off_write() -> None:
    transport, drivers, clock = make_drivers()
    router = CommandRouter(
        drivers=drivers,
        safety_gate=SafetyGate(),
        clock=clock,
    )
    auto_off_at = clock.now() + timedelta(seconds=30.0)

    result = await router.route(
        command(
            clock,
            ActuatorId.CHLORINE_DOSING_PUMP,
            ActuatorState.ON,
            metadata={
                ACTUATOR_ON_PULSE_SECONDS_METADATA: 30.0,
                ACTUATOR_AUTO_OFF_AT_METADATA: auto_off_at.isoformat(),
            },
        ),
        bypass_safety=True,
    )
    await clock.advance(30.1)

    assert result.applied is True
    assert result.metadata["timed_flash_on"] is True
    assert router.actuator_states[ActuatorId.CHLORINE_DOSING_PUMP] == ActuatorState.OFF
    assert transport.raw_writes == [(0x0203, 300)]
    assert transport.writes == []


@pytest.mark.asyncio
async def test_reconciliation_corrects_pump_relay_that_does_not_match_desired_state() -> None:
    transport, drivers, clock = make_drivers()
    router = CommandRouter(
        drivers=drivers,
        safety_gate=SafetyGate(),
        clock=clock,
    )

    await router.route(command(clock, ActuatorId.PUMP_MOTOR, ActuatorState.ON))
    transport.coils[0] = False

    results = await router.reconcile_states(reason="unit test reconcile")

    assert len(results) == 1
    assert results[0].applied is True
    assert results[0].metadata["relay_reconciliation"] is True
    assert results[0].metadata["actual_state"] == ActuatorState.OFF.value
    assert results[0].metadata["desired_state"] == ActuatorState.ON.value
    assert transport.writes == [(0, True), (0, True)]


@pytest.mark.asyncio
async def test_reconciliation_sends_off_when_dosing_relay_is_on_after_auto_off() -> None:
    transport, drivers, clock = make_drivers()
    router = CommandRouter(
        drivers=drivers,
        safety_gate=SafetyGate(),
        clock=clock,
    )
    auto_off_at = clock.now() + timedelta(seconds=30.0)
    await router.route(
        command(
            clock,
            ActuatorId.CHLORINE_DOSING_PUMP,
            ActuatorState.ON,
            metadata={
                ACTUATOR_ON_PULSE_SECONDS_METADATA: 30.0,
                ACTUATOR_AUTO_OFF_AT_METADATA: auto_off_at.isoformat(),
            },
        ),
        bypass_safety=True,
    )
    await clock.advance(30.1)
    assert router.actuator_states[ActuatorId.CHLORINE_DOSING_PUMP] == ActuatorState.OFF
    transport.coils[3] = True

    results = await router.reconcile_states(reason="unit test reconcile")

    assert len(results) == 1
    assert results[0].applied is True
    assert results[0].metadata["relay_reconciliation"] is True
    assert results[0].metadata["actual_state"] == ActuatorState.ON.value
    assert results[0].metadata["desired_state"] == ActuatorState.OFF.value
    assert transport.writes == [(3, False)]


@pytest.mark.asyncio
async def test_read_state_maps_relay_state_back_to_actuator_state() -> None:
    transport, drivers, _ = make_drivers()
    driver = driver_by_id(drivers, ActuatorId.PUMP_MOTOR_SPEED)
    transport.coils[1] = False

    sample = await driver.read_state()

    assert sample.state == ActuatorState.HIGH


@pytest.mark.asyncio
async def test_wrong_actuator_or_state_is_rejected() -> None:
    _, drivers, clock = make_drivers()
    driver = driver_by_id(drivers, ActuatorId.PUMP_MOTOR)

    with pytest.raises(ActuatorError):
        await driver.apply(command(clock, ActuatorId.BOOSTER_PUMP, ActuatorState.ON))

    with pytest.raises(ActuatorError):
        await driver.apply(command(clock, ActuatorId.PUMP_MOTOR, ActuatorState.HIGH))
