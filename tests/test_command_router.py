"""
Tests for routing actuator commands through drivers and safety checks.

The command router is the boundary between controller decisions and hardware,
so these tests verify accepted, rejected, and safety-generated commands.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from poolctl.domain.models import (
    ActuatorCommand,
    ActuatorId,
    ActuatorState,
    CommandSource,
    Measurement,
    Quality,
    SensorId,
)
from poolctl.drivers.simulated.actuators import build_default_simulated_actuators
from poolctl.drivers.simulated.plant import SimulatedPlant
from poolctl.services.clock import SimulatedClock
from poolctl.services.command_router import CommandRouter
from poolctl.services.safety import SafetyConfig, SafetyGate, SafetySeverity


def make_clock() -> SimulatedClock:
    return SimulatedClock(
        start_at=datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc),
    )


def make_router(
    safety_gate: SafetyGate | None = None,
) -> tuple[SimulatedClock, SimulatedPlant, CommandRouter]:
    clock = make_clock()
    plant = SimulatedPlant(clock=clock)
    router = CommandRouter(
        drivers=build_default_simulated_actuators(plant),
        safety_gate=(
            safety_gate
            if safety_gate is not None
            else SafetyGate(chlorine_pump_stabilization_seconds=0.0)
        ),
        clock=clock,
    )

    return clock, plant, router


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


def pressure(clock: SimulatedClock, sensor_id: SensorId, value: float) -> Measurement:
    return Measurement(
        sensor_id=sensor_id,
        observed_at=clock.now(),
        value=value,
        unit="psi",
        quality=Quality.GOOD,
    )


def chlorine_tank_level(clock: SimulatedClock, value: float) -> Measurement:
    return Measurement(
        sensor_id=SensorId.CHLORINE_TANK_LEVEL_GAL,
        observed_at=clock.now(),
        value=value,
        unit="gal",
        quality=Quality.GOOD,
    )


def temperature(
    clock: SimulatedClock,
    value: float,
    *,
    sensor_id: SensorId = SensorId.TEMP,
    unit: str = "degF",
    quality: Quality = Quality.GOOD,
) -> Measurement:
    return Measurement(
        sensor_id=sensor_id,
        observed_at=clock.now(),
        value=value,
        unit=unit,
        quality=quality,
    )


def required_chlorine_pressures(clock: SimulatedClock) -> list[Measurement]:
    return [
        pressure(clock, SensorId.PUMP_OUTPUT_PSI, 3.2),
        chlorine_tank_level(clock, 5.0),
    ]


async def start_pump_high(clock: SimulatedClock, router: CommandRouter) -> None:
    await router.route(command(clock, ActuatorId.PUMP_MOTOR, ActuatorState.ON))
    await router.route(command(clock, ActuatorId.PUMP_MOTOR_SPEED, ActuatorState.HIGH))


@pytest.mark.asyncio
async def test_chlorine_output_requires_pump_and_pressure_window() -> None:
    clock, _, router = make_router()

    await router.route(command(clock, ActuatorId.PUMP_MOTOR, ActuatorState.ON))

    low_pump_result = await router.route(
        command(clock, ActuatorId.CHLORINE_DOSING_PUMP, ActuatorState.ON),
        measurements=[
            pressure(clock, SensorId.PUMP_OUTPUT_PSI, 2.9),
            chlorine_tank_level(clock, 5.0),
        ],
    )

    assert not low_pump_result.accepted
    assert low_pump_result.rejection_reason == (
        "chlorine output requires pump output pressure >= 3 psi"
    )

    high_pump_result = await router.route(
        command(clock, ActuatorId.CHLORINE_DOSING_PUMP, ActuatorState.ON),
        measurements=[
            pressure(clock, SensorId.PUMP_OUTPUT_PSI, 3.6),
            chlorine_tank_level(clock, 5.0),
        ],
    )

    assert not high_pump_result.accepted
    assert high_pump_result.rejection_reason == (
        "chlorine output requires pump output pressure <= 3.5 psi"
    )

    accepted_result = await router.route(
        command(clock, ActuatorId.CHLORINE_DOSING_PUMP, ActuatorState.ON),
        measurements=required_chlorine_pressures(clock),
    )

    assert accepted_result.accepted
    assert accepted_result.applied
    assert router.actuator_states[ActuatorId.CHLORINE_DOSING_PUMP] == ActuatorState.ON


@pytest.mark.asyncio
async def test_chlorine_tank_hysteresis_blocks_and_reenables_dosing() -> None:
    clock, _, router = make_router()
    await router.route(command(clock, ActuatorId.PUMP_MOTOR, ActuatorState.ON))

    inhibited = await router.route(
        command(clock, ActuatorId.CHLORINE_DOSING_PUMP, ActuatorState.ON),
        measurements=[
            pressure(clock, SensorId.PUMP_OUTPUT_PSI, 3.2),
            chlorine_tank_level(clock, 1.5),
        ],
    )
    still_inhibited = await router.route(
        command(clock, ActuatorId.CHLORINE_DOSING_PUMP, ActuatorState.ON),
        measurements=[
            pressure(clock, SensorId.PUMP_OUTPUT_PSI, 3.2),
            chlorine_tank_level(clock, 1.8),
        ],
    )
    reenabled = await router.route(
        command(clock, ActuatorId.CHLORINE_DOSING_PUMP, ActuatorState.ON),
        measurements=[
            pressure(clock, SensorId.PUMP_OUTPUT_PSI, 3.2),
            chlorine_tank_level(clock, 2.0),
        ],
    )

    assert not inhibited.accepted
    assert inhibited.metadata["chlorine_tank"]["dosing_inhibited"] is True
    assert inhibited.metadata["chlorine_tank"]["low_warning_active"] is True
    assert inhibited.metadata["chlorine_tank"]["reenable_threshold_gal"] == 2.0
    assert not still_inhibited.accepted
    assert "refill required" in (still_inhibited.rejection_reason or "")
    assert reenabled.accepted
    assert reenabled.applied


@pytest.mark.asyncio
async def test_active_chlorine_dose_stops_when_tank_inhibits() -> None:
    clock, _, router = make_router()
    await router.route(command(clock, ActuatorId.PUMP_MOTOR, ActuatorState.ON))
    await router.route(
        command(clock, ActuatorId.CHLORINE_DOSING_PUMP, ActuatorState.ON),
        measurements=required_chlorine_pressures(clock),
    )

    results = await router.enforce_safety(
        measurements=[
            pressure(clock, SensorId.PUMP_OUTPUT_PSI, 3.2),
            chlorine_tank_level(clock, 1.4),
        ]
    )

    assert len(results) == 1
    assert results[0].metadata["safety_action"] == "chlorine_interlock_lost"
    assert results[0].metadata["chlorine_tank"]["dosing_inhibited"] is True
    assert router.actuator_states[ActuatorId.CHLORINE_DOSING_PUMP] == ActuatorState.OFF


@pytest.mark.asyncio
async def test_route_can_bypass_safety_for_diagnostic_command() -> None:
    clock, _, router = make_router()

    result = await router.route(
        command(clock, ActuatorId.CHLORINE_DOSING_PUMP, ActuatorState.ON),
        bypass_safety=True,
    )

    assert result.accepted
    assert result.applied
    assert result.metadata["safety_bypassed"] is True
    assert router.actuator_states[ActuatorId.CHLORINE_DOSING_PUMP] == ActuatorState.ON


@pytest.mark.asyncio
async def test_enforce_safety_can_suppress_selected_action_reason() -> None:
    clock, _, router = make_router()

    await router.route(
        command(clock, ActuatorId.CHLORINE_DOSING_PUMP, ActuatorState.ON),
        bypass_safety=True,
    )
    results = await router.enforce_safety(
        measurements=[],
        suppressed_action_reason_codes=("chlorine_interlock_lost",),
    )

    assert results == []
    assert router.actuator_states[ActuatorId.CHLORINE_DOSING_PUMP] == ActuatorState.ON

    overpressure_results = await router.enforce_safety(
        measurements=[pressure(clock, SensorId.PUMP_OUTPUT_PSI, 31.0)],
        suppressed_action_reason_codes=("chlorine_interlock_lost",),
    )

    assert len(overpressure_results) == 4
    assert overpressure_results[0].metadata["safety_action"] == "pump_output_overpressure"
    assert router.actuator_states[ActuatorId.CHLORINE_DOSING_PUMP] == ActuatorState.OFF


@pytest.mark.asyncio
async def test_booster_pump_requires_pump_motor_on() -> None:
    clock, _, router = make_router()

    rejected_result = await router.route(
        command(clock, ActuatorId.BOOSTER_PUMP, ActuatorState.ON)
    )

    assert not rejected_result.accepted
    assert rejected_result.rejection_reason == (
        "booster pump cannot turn on unless pump motor is on"
    )

    await router.route(command(clock, ActuatorId.PUMP_MOTOR, ActuatorState.ON))
    accepted_result = await router.route(
        command(clock, ActuatorId.BOOSTER_PUMP, ActuatorState.ON)
    )

    assert accepted_result.accepted
    assert accepted_result.applied
    assert router.actuator_states[ActuatorId.BOOSTER_PUMP] == ActuatorState.ON


@pytest.mark.asyncio
async def test_pump_output_overpressure_shuts_down_and_locks_out_until_clear() -> None:
    clock, _, router = make_router()

    await start_pump_high(clock, router)
    await router.route(command(clock, ActuatorId.BOOSTER_PUMP, ActuatorState.ON))
    await router.route(
        command(clock, ActuatorId.CHLORINE_DOSING_PUMP, ActuatorState.ON),
        measurements=required_chlorine_pressures(clock),
    )

    results = await router.enforce_safety(
        measurements=[
            pressure(clock, SensorId.PUMP_OUTPUT_PSI, 31.0),
            chlorine_tank_level(clock, 5.0),
        ]
    )

    assert len(results) == 4
    assert router.safety_gate.locked_out
    assert router.safety_gate.active_fault is not None
    assert router.safety_gate.active_fault.code == "pump_output_overpressure"
    assert router.safety_gate.active_fault.severity == SafetySeverity.ERROR
    assert router.actuator_states[ActuatorId.CHLORINE_DOSING_PUMP] == ActuatorState.OFF
    assert router.actuator_states[ActuatorId.BOOSTER_PUMP] == ActuatorState.OFF
    assert router.actuator_states[ActuatorId.PUMP_MOTOR] == ActuatorState.OFF
    assert router.actuator_states[ActuatorId.PUMP_MOTOR_SPEED] == ActuatorState.LOW

    locked_out_result = await router.route(
        command(clock, ActuatorId.PUMP_MOTOR, ActuatorState.ON)
    )

    assert not locked_out_result.accepted
    assert locked_out_result.metadata["fault_code"] == "pump_output_overpressure"

    router.clear_safety_fault()
    accepted_result = await router.route(
        command(clock, ActuatorId.PUMP_MOTOR, ActuatorState.ON)
    )

    assert accepted_result.accepted
    assert accepted_result.applied


@pytest.mark.asyncio
async def test_chlorine_tank_hysteresis_survives_live_config_update() -> None:
    clock, _, router = make_router()
    await start_pump_high(clock, router)

    inhibited = await router.route(
        command(clock, ActuatorId.CHLORINE_DOSING_PUMP, ActuatorState.ON),
        measurements=[
            pressure(clock, SensorId.PUMP_OUTPUT_PSI, 3.2),
            chlorine_tank_level(clock, 1.4),
        ],
    )
    assert not inhibited.accepted
    assert "dosing inhibit threshold" in str(inhibited.rejection_reason)

    still_inhibited = await router.route(
        command(clock, ActuatorId.CHLORINE_DOSING_PUMP, ActuatorState.ON),
        measurements=[
            pressure(clock, SensorId.PUMP_OUTPUT_PSI, 3.2),
            chlorine_tank_level(clock, 1.7),
        ],
    )
    assert not still_inhibited.accepted
    assert "refill required" in str(still_inhibited.rejection_reason)

    router.safety_gate.apply_config(
        SafetyConfig(
            chlorine_min_pump_output_psi=3.0,
            chlorine_max_pump_output_psi=4.0,
        )
    )
    after_config_edit = await router.route(
        command(clock, ActuatorId.CHLORINE_DOSING_PUMP, ActuatorState.ON),
        measurements=[
            pressure(clock, SensorId.PUMP_OUTPUT_PSI, 3.2),
            chlorine_tank_level(clock, 1.7),
        ],
    )

    assert not after_config_edit.accepted
    assert "refill required" in str(after_config_edit.rejection_reason)


@pytest.mark.asyncio
async def test_pump_high_without_prime_pressure_locks_out_as_warning() -> None:
    clock, _, router = make_router()

    await start_pump_high(clock, router)
    await router.enforce_safety(
        measurements=[pressure(clock, SensorId.PUMP_OUTPUT_PSI, 0.0)]
    )
    await clock.advance(31.0)

    results = await router.enforce_safety(
        measurements=[pressure(clock, SensorId.PUMP_OUTPUT_PSI, 0.0)]
    )

    assert len(results) == 4
    assert router.safety_gate.locked_out
    assert router.safety_gate.active_fault is not None
    assert router.safety_gate.active_fault.code == "loss_of_prime"
    assert router.safety_gate.active_fault.severity == SafetySeverity.WARNING
    assert router.actuator_states[ActuatorId.PUMP_MOTOR] == ActuatorState.OFF
    assert router.actuator_states[ActuatorId.PUMP_MOTOR_SPEED] == ActuatorState.LOW


@pytest.mark.asyncio
async def test_pump_prime_timeout_treats_stale_pressure_as_unavailable() -> None:
    safety_gate = SafetyGate(
        SafetyConfig(
            pump_output_max_age_seconds=10.0,
            pump_prime_timeout_s=30.0,
        ),
        chlorine_pump_stabilization_seconds=0.0,
    )
    clock, _, router = make_router(safety_gate)
    await start_pump_high(clock, router)
    fresh_pressure = pressure(clock, SensorId.PUMP_OUTPUT_PSI, 5.0)

    assert await router.enforce_safety(measurements=[fresh_pressure]) == []

    await clock.advance(11.0)
    first_stale = await router.enforce_safety(measurements=[fresh_pressure])
    assert first_stale == []
    assert not router.safety_gate.locked_out

    await clock.advance(31.0)
    stale_timeout = await router.enforce_safety(measurements=[fresh_pressure])

    assert len(stale_timeout) == 4
    assert router.safety_gate.active_fault is not None
    assert router.safety_gate.active_fault.code == "loss_of_prime"


@pytest.mark.asyncio
async def test_freeze_protection_turns_on_pump_and_sets_low_speed() -> None:
    freeze_config = SafetyConfig.from_mapping(
        {
            "freeze_protection": {
                "enabled": True,
                "source": "temp",
                "temp_sensor": "temp",
                "low_speed_on_below_temp": 35.0,
                "low_speed_off_above_temp": 37.0,
                "high_speed_on_below_temp": 33.0,
                "high_speed_off_above_temp": 34.0,
                "min_run_seconds": 0.0,
                "threshold_unit": "degF",
            }
        }
    )
    clock, _, router = make_router(SafetyGate(freeze_config))

    results = await router.enforce_safety(measurements=[temperature(clock, 34.5)])

    assert len(results) == 1
    assert results[0].metadata["safety_action"] == "freeze_protection_low"
    assert router.actuator_states[ActuatorId.PUMP_MOTOR] == ActuatorState.ON
    assert router.actuator_states[ActuatorId.PUMP_MOTOR_SPEED] == ActuatorState.LOW


@pytest.mark.asyncio
async def test_freeze_protection_escalates_to_high_speed_and_uses_raw_quality() -> None:
    freeze_config = SafetyConfig.from_mapping(
        {
            "freeze_protection": {
                "enabled": True,
                "source": "both",
                "temp_sensor": "temp",
                "ph_temp_sensor": "orp_temp",
                "low_speed_on_below_temp": 35.0,
                "low_speed_off_above_temp": 37.0,
                "high_speed_on_below_temp": 33.0,
                "high_speed_off_above_temp": 34.0,
                "min_run_seconds": 0.0,
                "threshold_unit": "degF",
            }
        }
    )
    clock, _, router = make_router(SafetyGate(freeze_config))

    await router.route(command(clock, ActuatorId.PUMP_MOTOR, ActuatorState.ON))
    await router.route(command(clock, ActuatorId.PUMP_MOTOR_SPEED, ActuatorState.LOW))

    results = await router.enforce_safety(
        measurements=[
            temperature(clock, 36.0, sensor_id=SensorId.TEMP),
            temperature(
                clock,
                32.5,
                sensor_id=SensorId.ORP_TEMP,
                quality=Quality.SUSPECT,
            ),
        ]
    )

    assert len(results) == 1
    assert results[0].metadata["safety_action"] == "freeze_protection_high"
    assert router.actuator_states[ActuatorId.PUMP_MOTOR] == ActuatorState.ON
    assert router.actuator_states[ActuatorId.PUMP_MOTOR_SPEED] == ActuatorState.HIGH


@pytest.mark.asyncio
async def test_freeze_hysteresis_and_minimum_runtime_latch() -> None:
    freeze_config = SafetyConfig.from_mapping(
        {
            "freeze_protection": {
                "enabled": True,
                "source": "temp",
                "temp_sensor": "temp",
                "low_speed_on_below_temp": 35.0,
                "low_speed_off_above_temp": 37.0,
                "high_speed_on_below_temp": 33.0,
                "high_speed_off_above_temp": 34.0,
                "min_run_seconds": 60.0,
                "threshold_unit": "degF",
            }
        }
    )
    clock, _, router = make_router(SafetyGate(freeze_config))

    first = await router.enforce_safety(measurements=[temperature(clock, 32.8)])
    assert len(first) >= 1
    assert router.actuator_states[ActuatorId.PUMP_MOTOR] == ActuatorState.ON
    assert router.actuator_states[ActuatorId.PUMP_MOTOR_SPEED] == ActuatorState.HIGH

    await clock.advance(30.0)
    held = await router.enforce_safety(
        measurements=[
            temperature(clock, 38.0),
            pressure(clock, SensorId.PUMP_OUTPUT_PSI, 5.0),
        ]
    )
    assert held == []
    assert router.actuator_states[ActuatorId.PUMP_MOTOR_SPEED] == ActuatorState.HIGH

    await clock.advance(31.0)
    step_down = await router.enforce_safety(
        measurements=[
            temperature(clock, 34.5),
            pressure(clock, SensorId.PUMP_OUTPUT_PSI, 5.0),
        ]
    )
    assert len(step_down) == 1
    assert step_down[0].metadata["safety_action"] == "freeze_protection_low"
    assert router.actuator_states[ActuatorId.PUMP_MOTOR_SPEED] == ActuatorState.LOW

    mid_band = await router.enforce_safety(measurements=[temperature(clock, 36.5)])
    assert mid_band == []
    assert router.actuator_states[ActuatorId.PUMP_MOTOR_SPEED] == ActuatorState.LOW

    release = await router.enforce_safety(measurements=[temperature(clock, 37.2)])
    assert release == []
    freeze_state = router.safety_gate.freeze_status(clock.now())
    assert freeze_state["active"] is False
