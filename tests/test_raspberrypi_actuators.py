from __future__ import annotations

from datetime import datetime, timezone

import pytest

from poolctl.domain.models import (
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


class FakeRelayTransport:
    def __init__(self) -> None:
        self.coils: dict[int, bool] = {}
        self.writes: list[tuple[int, bool]] = []

    async def write_single_coil(self, *, coil_address: int, value: bool) -> None:
        self.coils[coil_address] = value
        self.writes.append((coil_address, value))

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
) -> ActuatorCommand:
    return ActuatorCommand(
        actuator_id=actuator_id,
        created_at=clock.now(),
        state=state,
        requested_by=CommandSource.MANUAL,
        reason="unit test",
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
