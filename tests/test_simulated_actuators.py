"""
Tests for simulated actuator drivers.

Simulated actuators update the SimulatedPlant and let controller behavior be
tested on Windows without real hardware.
"""

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
from poolctl.drivers.simulated.actuators import (
    SimulatedActuator,
    build_default_simulated_actuators,
)
from poolctl.drivers.simulated.plant import SimulatedPlant
from poolctl.services.clock import SimulatedClock


def make_plant() -> SimulatedPlant:
    return SimulatedPlant(
        clock=SimulatedClock(
            start_at=datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc),
        )
    )


def driver_by_id(
    drivers: list[SimulatedActuator],
    actuator_id: ActuatorId,
) -> SimulatedActuator:
    return next(driver for driver in drivers if driver.actuator_id == actuator_id)


def command(
    *,
    actuator_id: ActuatorId,
    state: ActuatorState,
) -> ActuatorCommand:
    return ActuatorCommand(
        actuator_id=actuator_id,
        state=state,
        requested_by=CommandSource.MANUAL,
        reason="unit test",
    )


def test_default_simulated_actuators_match_actuator_driver_protocol() -> None:
    plant = make_plant()

    drivers = build_default_simulated_actuators(plant)

    assert {driver.actuator_id for driver in drivers} == {
        ActuatorId.PUMP_MOTOR,
        ActuatorId.PUMP_MOTOR_SPEED,
        ActuatorId.BOOSTER_PUMP,
        ActuatorId.CHLORINE_DOSING_PUMP,
    }
    assert all(isinstance(driver, ActuatorDriver) for driver in drivers)


@pytest.mark.asyncio
async def test_apply_updates_plant_and_returns_state_sample() -> None:
    plant = make_plant()
    driver = driver_by_id(
        build_default_simulated_actuators(plant),
        ActuatorId.PUMP_MOTOR,
    )
    cmd = command(actuator_id=ActuatorId.PUMP_MOTOR, state=ActuatorState.ON)

    sample = await driver.apply(cmd)

    assert plant.pump_motor == ActuatorState.ON
    assert sample.actuator_id == ActuatorId.PUMP_MOTOR
    assert sample.state == ActuatorState.ON
    assert sample.source_command_id == cmd.id
    assert sample.observed_at == plant.clock.now()
    assert sample.metadata == {"driver": "simulated_pump_motor"}


@pytest.mark.asyncio
async def test_apply_rejects_command_for_different_actuator() -> None:
    plant = make_plant()
    driver = driver_by_id(
        build_default_simulated_actuators(plant),
        ActuatorId.PUMP_MOTOR,
    )
    cmd = command(actuator_id=ActuatorId.BOOSTER_PUMP, state=ActuatorState.ON)

    with pytest.raises(ActuatorError):
        await driver.apply(cmd)

    assert plant.pump_motor == ActuatorState.OFF


@pytest.mark.asyncio
async def test_apply_rejects_unsupported_state_for_actuator() -> None:
    plant = make_plant()
    driver = driver_by_id(
        build_default_simulated_actuators(plant),
        ActuatorId.PUMP_MOTOR_SPEED,
    )
    cmd = command(actuator_id=ActuatorId.PUMP_MOTOR_SPEED, state=ActuatorState.ON)

    with pytest.raises(ActuatorError):
        await driver.apply(cmd)

    assert plant.pump_motor_speed == ActuatorState.LOW


@pytest.mark.asyncio
async def test_stop_uses_configured_inactive_state() -> None:
    plant = make_plant()
    driver = driver_by_id(
        build_default_simulated_actuators(plant),
        ActuatorId.PUMP_MOTOR_SPEED,
    )

    await driver.apply(
        command(actuator_id=ActuatorId.PUMP_MOTOR_SPEED, state=ActuatorState.HIGH)
    )
    sample = await driver.stop()

    assert plant.pump_motor_speed == ActuatorState.LOW
    assert sample.state == ActuatorState.LOW
    assert sample.source_command_id is None


@pytest.mark.asyncio
async def test_read_state_returns_current_plant_state() -> None:
    plant = make_plant()
    driver = driver_by_id(
        build_default_simulated_actuators(plant),
        ActuatorId.CHLORINE_DOSING_PUMP,
    )
    plant.set_chlorine_dosing_pump(ActuatorState.ON)

    sample = await driver.read_state()

    assert sample.actuator_id == ActuatorId.CHLORINE_DOSING_PUMP
    assert sample.state == ActuatorState.ON
    assert sample.source_command_id is None
