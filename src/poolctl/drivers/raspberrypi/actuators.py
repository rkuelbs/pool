"""
Raspberry Pi actuator drivers backed by the Waveshare relay module.

Each domain actuator command is translated into a small set of relay coil
writes. The mapping is configurable because wiring can change without requiring
changes to scheduler, safety, or chlorination logic.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from poolctl.domain.models import (
    ActuatorCommand,
    ActuatorId,
    ActuatorState,
    ActuatorStateSample,
)
from poolctl.drivers.base import ActuatorError
from poolctl.drivers.modbus.relay_board import (
    ModbusRelayBoard,
    ModbusRelayBoardConfig,
    PymodbusRtuRelayTransport,
    build_modbus_relay_board,
)
from poolctl.drivers.modbus.rtu_bus import ModbusRtuBusRegistry, SharedModbusRtuBus
from poolctl.services.clock import Clock


@dataclass(frozen=True)
class RelayActuatorConfig:
    """
    Relay mapping for pool actuators.
    """

    relays: Mapping[ActuatorId, int]
    pump_speed_low_relay_on: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> RelayActuatorConfig:
        modbus_data = _mapping_value(data, "modbus_relay", default={})
        relay_data = _mapping_value(modbus_data, "relays", default={})
        speed_data = _mapping_value(modbus_data, "pump_speed_relay", default={})

        return cls(
            relays={
                ActuatorId.PUMP_MOTOR: _relay_number_value(
                    relay_data,
                    "pump_motor",
                    1,
                ),
                ActuatorId.PUMP_MOTOR_SPEED: _relay_number_value(
                    relay_data,
                    "pump_motor_speed",
                    2,
                ),
                ActuatorId.BOOSTER_PUMP: _relay_number_value(
                    relay_data,
                    "booster_pump",
                    3,
                ),
                ActuatorId.CHLORINE_DOSING_PUMP: _relay_number_value(
                    relay_data,
                    "chlorine_dosing_pump",
                    6,
                ),
            },
            pump_speed_low_relay_on=_pump_speed_low_relay_on(speed_data),
        )


class ModbusRelayActuator:
    """
    ActuatorDriver implementation backed by one Modbus relay.
    """

    def __init__(
        self,
        *,
        name: str,
        actuator_id: ActuatorId,
        board: ModbusRelayBoard,
        relay_number: int,
        state_to_relay_on: Mapping[ActuatorState, bool],
        relay_on_to_state: Mapping[bool, ActuatorState],
        clock: Clock,
        stop_state: ActuatorState,
    ) -> None:
        if stop_state not in state_to_relay_on:
            raise ValueError("stop_state must be valid for this actuator")

        self.name = name
        self.actuator_id = actuator_id
        self._board = board
        self._relay_number = relay_number
        self._state_to_relay_on = dict(state_to_relay_on)
        self._relay_on_to_state = dict(relay_on_to_state)
        self._clock = clock
        self._stop_state = stop_state

    async def apply(self, command: ActuatorCommand) -> ActuatorStateSample:
        # Drivers are intentionally narrow: one driver controls one domain
        # actuator. Rejecting other actuator IDs catches wiring/config mistakes.
        if command.actuator_id != self.actuator_id:
            raise ActuatorError(
                f"{self.name} cannot apply command for {command.actuator_id.value}"
            )

        if command.state not in self._state_to_relay_on:
            allowed = ", ".join(
                state.value
                for state in sorted(
                    self._state_to_relay_on,
                    key=lambda state: state.value,
                )
            )
            raise ActuatorError(
                f"{self.name} does not accept state {command.state.value}; "
                f"allowed states: {allowed}"
            )

        # Domain states are ON/OFF/LOW/HIGH. The mapping decides whether that
        # means the physical relay coil is energized for this wiring setup.
        relay_on = self._state_to_relay_on[command.state]
        await self._board.set_relay(self._relay_number, relay_on)

        return self._state_sample(
            state=command.state,
            source_command_id=command.id,
            relay_on=relay_on,
        )

    async def read_state(self) -> ActuatorStateSample:
        relay_on = await self._board.read_relay(self._relay_number)

        # Convert hardware coil state back into the domain state shown in the
        # dashboard and used by safety logic.
        state = self._relay_on_to_state[relay_on]

        return self._state_sample(
            state=state,
            source_command_id=None,
            relay_on=relay_on,
        )

    async def stop(self) -> ActuatorStateSample:
        relay_on = self._state_to_relay_on[self._stop_state]
        await self._board.set_relay(self._relay_number, relay_on)

        return self._state_sample(
            state=self._stop_state,
            source_command_id=None,
            relay_on=relay_on,
        )

    def _state_sample(
        self,
        *,
        state: ActuatorState,
        source_command_id: str | None,
        relay_on: bool,
    ) -> ActuatorStateSample:
        return ActuatorStateSample(
            actuator_id=self.actuator_id,
            observed_at=self._clock.now(),
            state=state,
            source_command_id=source_command_id,
            metadata={
                "driver": self.name,
                "relay_number": self._relay_number,
                "relay_on": relay_on,
            },
        )


def build_modbus_relay_actuators(
    *,
    board: ModbusRelayBoard,
    config: RelayActuatorConfig,
    clock: Clock,
) -> list[ModbusRelayActuator]:
    on_off_states = {
        ActuatorState.ON: True,
        ActuatorState.OFF: False,
    }
    on_off_reverse = {
        True: ActuatorState.ON,
        False: ActuatorState.OFF,
    }

    speed_states = {
        ActuatorState.LOW: config.pump_speed_low_relay_on,
        ActuatorState.HIGH: not config.pump_speed_low_relay_on,
    }

    # Your current wiring uses relay OFF = high speed and relay ON = low speed.
    # Keeping this configurable lets the relay logic match real wiring without
    # changing scheduler/safety code.
    speed_reverse = {
        config.pump_speed_low_relay_on: ActuatorState.LOW,
        not config.pump_speed_low_relay_on: ActuatorState.HIGH,
    }

    return [
        ModbusRelayActuator(
            name="modbus_pump_motor",
            actuator_id=ActuatorId.PUMP_MOTOR,
            board=board,
            relay_number=config.relays[ActuatorId.PUMP_MOTOR],
            state_to_relay_on=on_off_states,
            relay_on_to_state=on_off_reverse,
            clock=clock,
            stop_state=ActuatorState.OFF,
        ),
        ModbusRelayActuator(
            name="modbus_pump_motor_speed",
            actuator_id=ActuatorId.PUMP_MOTOR_SPEED,
            board=board,
            relay_number=config.relays[ActuatorId.PUMP_MOTOR_SPEED],
            state_to_relay_on=speed_states,
            relay_on_to_state=speed_reverse,
            clock=clock,
            stop_state=ActuatorState.LOW,
        ),
        ModbusRelayActuator(
            name="modbus_booster_pump",
            actuator_id=ActuatorId.BOOSTER_PUMP,
            board=board,
            relay_number=config.relays[ActuatorId.BOOSTER_PUMP],
            state_to_relay_on=on_off_states,
            relay_on_to_state=on_off_reverse,
            clock=clock,
            stop_state=ActuatorState.OFF,
        ),
        ModbusRelayActuator(
            name="modbus_chlorine_dosing_pump",
            actuator_id=ActuatorId.CHLORINE_DOSING_PUMP,
            board=board,
            relay_number=config.relays[ActuatorId.CHLORINE_DOSING_PUMP],
            state_to_relay_on=on_off_states,
            relay_on_to_state=on_off_reverse,
            clock=clock,
            stop_state=ActuatorState.OFF,
        ),
    ]


def build_raspberrypi_actuators_from_mapping(
    data: Mapping[str, Any],
    *,
    clock: Clock,
    bus: SharedModbusRtuBus | None = None,
    bus_registry: ModbusRtuBusRegistry | None = None,
) -> list[ModbusRelayActuator]:
    relay_board_config = ModbusRelayBoardConfig.from_mapping(data)
    relay_actuator_config = RelayActuatorConfig.from_mapping(data)
    selected_bus = bus
    if selected_bus is None and bus_registry is not None:
        selected_bus = bus_registry.bus_for(
            port=relay_board_config.port,
            baudrate=relay_board_config.baudrate,
            timeout_s=relay_board_config.timeout_s,
        )
    board = (
        ModbusRelayBoard(
            name="waveshare_modbus_relay",
            transport=PymodbusRtuRelayTransport(relay_board_config, bus=selected_bus),
            relay_count=8,
        )
        if selected_bus is not None
        else build_modbus_relay_board(relay_board_config)
    )

    return build_modbus_relay_actuators(
        board=board,
        config=relay_actuator_config,
        clock=clock,
    )


def _mapping_value(
    data: Mapping[str, Any],
    key: str,
    *,
    default: Mapping[str, Any],
) -> Mapping[str, Any]:
    value = data.get(key, default)

    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be a mapping")

    return value


def _relay_number_value(
    data: Mapping[str, Any],
    key: str,
    default: int,
) -> int:
    value = data.get(key, default)

    if not isinstance(value, int):
        raise ValueError(f"{key} must be a relay number")

    if not 1 <= value <= 8:
        raise ValueError(f"{key} must be between relay 1 and relay 8")

    return value


def _pump_speed_low_relay_on(data: Mapping[str, Any]) -> bool:
    low_state = _relay_state_value(data, "low_state", "on")
    high_state = _relay_state_value(data, "high_state", "off")

    if low_state == high_state:
        raise ValueError("pump speed low_state and high_state must be different")

    return low_state


def _relay_state_value(data: Mapping[str, Any], key: str, default: str) -> bool:
    value = data.get(key, default)

    if isinstance(value, bool):
        return value

    if not isinstance(value, str):
        raise ValueError(f"{key} must be on or off")

    if value == "on":
        return True

    if value == "off":
        return False

    raise ValueError(f"{key} must be on or off")
