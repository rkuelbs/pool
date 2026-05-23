from __future__ import annotations

from collections.abc import Callable, Iterable

from poolctl.domain.models import (
    ActuatorCommand,
    ActuatorId,
    ActuatorState,
    ActuatorStateSample,
)
from poolctl.drivers.base import ActuatorError
from poolctl.drivers.simulated.plant import SimulatedPlant


class SimulatedActuator:
    """
    Generic simulated actuator driver.

    The driver is intentionally small: it validates that the command is meant
    for this actuator, validates the actuator-specific state set, updates the
    shared SimulatedPlant, and returns an ActuatorStateSample.

    Higher-level policy belongs in a command router or safety gate. For
    example, this class does not decide whether chlorine dosing is safe while
    the pump is off.
    """

    def __init__(
        self,
        *,
        name: str,
        actuator_id: ActuatorId,
        plant: SimulatedPlant,
        allowed_states: Iterable[ActuatorState],
        apply_state: Callable[[ActuatorState], None],
        read_current_state: Callable[[], ActuatorState],
        stop_state: ActuatorState = ActuatorState.OFF,
    ) -> None:
        self.name = name
        self.actuator_id = actuator_id
        self._plant = plant
        self._allowed_states = frozenset(allowed_states)
        self._apply_state = apply_state
        self._read_current_state = read_current_state
        self._stop_state = stop_state

        if stop_state not in self._allowed_states:
            raise ValueError("stop_state must be one of allowed_states")

    async def apply(self, command: ActuatorCommand) -> ActuatorStateSample:
        """
        Apply a command to the simulated plant and report the resulting state.
        """
        if command.actuator_id != self.actuator_id:
            raise ActuatorError(
                f"{self.name} cannot apply command for {command.actuator_id.value}"
            )

        self._validate_state(command.state)
        self._apply_state(command.state)

        return self._state_sample(
            state=self._read_current_state(),
            source_command_id=command.id,
        )

    async def read_state(self) -> ActuatorStateSample:
        """
        Return the current simulated actuator state.
        """
        self._plant.update()

        return self._state_sample(
            state=self._read_current_state(),
            source_command_id=None,
        )

    async def stop(self) -> ActuatorStateSample:
        """
        Put the simulated actuator into its configured inactive state.
        """
        self._apply_state(self._stop_state)

        return self._state_sample(
            state=self._read_current_state(),
            source_command_id=None,
        )

    def _validate_state(self, state: ActuatorState) -> None:
        if state in self._allowed_states:
            return

        allowed = ", ".join(
            allowed_state.value
            for allowed_state in sorted(
                self._allowed_states,
                key=lambda allowed_state: allowed_state.value,
            )
        )

        raise ActuatorError(
            f"{self.name} does not accept state {state.value}; allowed states: {allowed}"
        )

    def _state_sample(
        self,
        *,
        state: ActuatorState,
        source_command_id: str | None,
    ) -> ActuatorStateSample:
        return ActuatorStateSample(
            actuator_id=self.actuator_id,
            observed_at=self._plant.clock.now(),
            state=state,
            source_command_id=source_command_id,
            metadata={"driver": self.name},
        )


def build_default_simulated_actuators(plant: SimulatedPlant) -> list[SimulatedActuator]:
    """
    Build the default simulated actuator set for the current pool system.
    """
    on_off_states = (ActuatorState.ON, ActuatorState.OFF)

    return [
        SimulatedActuator(
            name="simulated_pump_motor",
            actuator_id=ActuatorId.PUMP_MOTOR,
            plant=plant,
            allowed_states=on_off_states,
            apply_state=plant.set_pump_motor,
            read_current_state=lambda: plant.pump_motor,
            stop_state=ActuatorState.OFF,
        ),
        SimulatedActuator(
            name="simulated_pump_motor_speed",
            actuator_id=ActuatorId.PUMP_MOTOR_SPEED,
            plant=plant,
            allowed_states=(ActuatorState.LOW, ActuatorState.HIGH),
            apply_state=plant.set_pump_motor_speed,
            read_current_state=lambda: plant.pump_motor_speed,
            stop_state=ActuatorState.LOW,
        ),
        SimulatedActuator(
            name="simulated_booster_pump",
            actuator_id=ActuatorId.BOOSTER_PUMP,
            plant=plant,
            allowed_states=on_off_states,
            apply_state=plant.set_booster_pump,
            read_current_state=lambda: plant.booster_pump,
            stop_state=ActuatorState.OFF,
        ),
        SimulatedActuator(
            name="simulated_chlorine_dosing_pump",
            actuator_id=ActuatorId.CHLORINE_DOSING_PUMP,
            plant=plant,
            allowed_states=on_off_states,
            apply_state=plant.set_chlorine_dosing_pump,
            read_current_state=lambda: plant.chlorine_dosing_pump,
            stop_state=ActuatorState.OFF,
        ),
    ]
