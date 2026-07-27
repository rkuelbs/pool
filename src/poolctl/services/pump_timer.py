"""
Pump schedule evaluation and manual override handling.

The timer converts configured local-time run windows into desired pump state.
Manual overrides latch until the next scheduled transition so the live GUI can
temporarily force on/off/high/low without permanently editing the schedule.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml  # type: ignore[import-untyped]

from poolctl.domain.models import (
    ActuatorCommand,
    ActuatorId,
    ActuatorState,
    CommandSource,
)
from poolctl.services.schedule import DailyTimeWindow, TimeOfDay


@dataclass(frozen=True)
class PumpTimerSchedule:
    """
    One daily open-loop pump schedule window.
    """

    name: str
    window: DailyTimeWindow
    pump_speed: ActuatorState = ActuatorState.LOW
    booster_state: ActuatorState = ActuatorState.OFF

    def __post_init__(self) -> None:
        if self.pump_speed not in (ActuatorState.LOW, ActuatorState.HIGH):
            raise ValueError("pump_speed must be low or high")

        if self.booster_state not in (ActuatorState.ON, ActuatorState.OFF):
            raise ValueError("booster_state must be on or off")

    def is_active(self, now: datetime) -> bool:
        return self.window.contains(now)


@dataclass(frozen=True)
class PumpTimerConfig:
    """
    Open-loop pump timer configuration.
    """

    schedules: tuple[PumpTimerSchedule, ...] = ()
    timezone: str = "UTC"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> PumpTimerConfig:
        timer_data = _mapping_value(data, "pump_timer", default={})
        schedules_data = timer_data.get("schedules", [])

        if not isinstance(schedules_data, list):
            raise ValueError("pump_timer.schedules must be a list")

        timezone_name = _string_with_default(timer_data, "timezone", "UTC")
        _validate_timezone(timezone_name)

        return cls(
            schedules=tuple(
                _schedule_from_mapping(schedule_data)
                for schedule_data in schedules_data
            ),
            timezone=timezone_name,
        )


@dataclass(frozen=True)
class PumpTimerOverride:
    """
    Temporary manual override for timer output decisions.
    """

    pump_motor: ActuatorState
    pump_speed: ActuatorState = ActuatorState.HIGH
    booster_state: ActuatorState = ActuatorState.OFF
    reason: str = "manual override"

    def __post_init__(self) -> None:
        if self.pump_motor not in (ActuatorState.ON, ActuatorState.OFF):
            raise ValueError("override pump_motor must be on or off")
        if self.pump_speed not in (ActuatorState.LOW, ActuatorState.HIGH):
            raise ValueError("override pump_speed must be low or high")
        if self.booster_state not in (ActuatorState.ON, ActuatorState.OFF):
            raise ValueError("override booster_state must be on or off")


@dataclass(frozen=True)
class PumpTimerEvaluation:
    """
    Desired state and commands from one timer evaluation.
    """

    active_schedule_names: tuple[str, ...]
    desired_states: Mapping[ActuatorId, ActuatorState]
    commands: tuple[ActuatorCommand, ...]


class PumpTimer:
    """
    Generates simple ON/OFF and LOW/HIGH commands from daily schedules.
    """

    def __init__(self, config: PumpTimerConfig) -> None:
        self._config = config
        self._timezone = ZoneInfo(config.timezone)

    def evaluate(
        self,
        *,
        now: datetime,
        actuator_states: Mapping[ActuatorId, ActuatorState],
        override: PumpTimerOverride | None = None,
    ) -> PumpTimerEvaluation:
        schedule_now = now.astimezone(self._timezone)

        if override is not None:
            active_schedules: list[PumpTimerSchedule] = []
            desired_states = self._desired_states_for_override(override)
            reason_override = override.reason
        else:
            active_schedules = [
                schedule
                for schedule in self._config.schedules
                if schedule.is_active(schedule_now)
            ]
            desired_states = self._desired_states(active_schedules)
            reason_override = None

        return PumpTimerEvaluation(
            active_schedule_names=tuple(schedule.name for schedule in active_schedules),
            desired_states=desired_states,
            commands=tuple(
                self._commands_for_desired_states(
                    now=now,
                    desired_states=desired_states,
                    actuator_states=actuator_states,
                    active_schedule_names=tuple(
                        schedule.name for schedule in active_schedules
                    ),
                    reason_override=reason_override,
                )
            ),
        )

    def next_transition_after(self, now: datetime) -> datetime | None:
        """
        Return the next time the schedule's desired output state changes.

        The returned datetime uses the same timezone awareness as ``now``.
        """
        schedule_now = now.astimezone(self._timezone)
        current_desired = self._desired_states_for_time(schedule_now)

        for candidate in self._future_schedule_boundaries(schedule_now):
            candidate_desired = self._desired_states_for_time(candidate)
            if candidate_desired == current_desired:
                continue

            if now.tzinfo is None:
                return candidate.replace(tzinfo=None)
            return candidate.astimezone(now.tzinfo)

        return None

    def _desired_states_for_override(
        self,
        override: PumpTimerOverride,
    ) -> dict[ActuatorId, ActuatorState]:
        if override.pump_motor == ActuatorState.OFF:
            return {
                ActuatorId.BOOSTER_PUMP: ActuatorState.OFF,
                ActuatorId.PUMP_MOTOR: ActuatorState.OFF,
                ActuatorId.PUMP_MOTOR_SPEED: override.pump_speed,
            }

        return {
            ActuatorId.PUMP_MOTOR: ActuatorState.ON,
            ActuatorId.PUMP_MOTOR_SPEED: override.pump_speed,
            ActuatorId.BOOSTER_PUMP: override.booster_state,
        }

    def _desired_states(
        self,
        active_schedules: list[PumpTimerSchedule],
    ) -> dict[ActuatorId, ActuatorState]:
        if not active_schedules:
            return {
                ActuatorId.BOOSTER_PUMP: ActuatorState.OFF,
                ActuatorId.PUMP_MOTOR: ActuatorState.OFF,
                ActuatorId.PUMP_MOTOR_SPEED: ActuatorState.LOW,
            }

        pump_speed = (
            ActuatorState.HIGH
            if any(schedule.pump_speed == ActuatorState.HIGH for schedule in active_schedules)
            else ActuatorState.LOW
        )
        booster_state = (
            ActuatorState.ON
            if any(
                schedule.booster_state == ActuatorState.ON
                for schedule in active_schedules
            )
            else ActuatorState.OFF
        )

        return {
            ActuatorId.PUMP_MOTOR: ActuatorState.ON,
            ActuatorId.PUMP_MOTOR_SPEED: pump_speed,
            ActuatorId.BOOSTER_PUMP: booster_state,
        }

    def _desired_states_for_time(self, schedule_now: datetime) -> dict[ActuatorId, ActuatorState]:
        active_schedules = [
            schedule
            for schedule in self._config.schedules
            if schedule.is_active(schedule_now)
        ]
        return self._desired_states(active_schedules)

    def _future_schedule_boundaries(self, schedule_now: datetime) -> tuple[datetime, ...]:
        candidates: list[datetime] = []
        today = schedule_now.date()

        for day_offset in range(3):
            day = today + timedelta(days=day_offset)
            for schedule in self._config.schedules:
                if schedule.window.start == schedule.window.end:
                    continue
                candidates.append(_datetime_for_time_of_day(schedule_now, day, schedule.window.start))
                candidates.append(_datetime_for_time_of_day(schedule_now, day, schedule.window.end))

        future_candidates = sorted(candidate for candidate in candidates if candidate > schedule_now)
        unique_candidates: list[datetime] = []
        seen: set[str] = set()
        for candidate in future_candidates:
            key = candidate.isoformat()
            if key in seen:
                continue
            seen.add(key)
            unique_candidates.append(candidate)

        return tuple(unique_candidates)

    def _commands_for_desired_states(
        self,
        *,
        now: datetime,
        desired_states: Mapping[ActuatorId, ActuatorState],
        actuator_states: Mapping[ActuatorId, ActuatorState],
        active_schedule_names: tuple[str, ...],
        reason_override: str | None = None,
    ) -> list[ActuatorCommand]:
        command_order = self._command_order(desired_states)
        commands: list[ActuatorCommand] = []

        for actuator_id in command_order:
            desired_state = desired_states[actuator_id]
            if actuator_states.get(actuator_id) == desired_state:
                continue

            commands.append(
                ActuatorCommand(
                    actuator_id=actuator_id,
                    created_at=now,
                    state=desired_state,
                    requested_by=CommandSource.TIMER,
                    reason=self._reason(
                        active_schedule_names,
                        actuator_id,
                        desired_state,
                        reason_override=reason_override,
                    ),
                    metadata={
                        "timer_active_schedules": list(active_schedule_names),
                        "timer_override": reason_override,
                    },
                )
            )

        return commands

    def _command_order(
        self,
        desired_states: Mapping[ActuatorId, ActuatorState],
    ) -> tuple[ActuatorId, ...]:
        if desired_states[ActuatorId.PUMP_MOTOR] == ActuatorState.OFF:
            return (
                ActuatorId.BOOSTER_PUMP,
                ActuatorId.PUMP_MOTOR,
                ActuatorId.PUMP_MOTOR_SPEED,
            )

        return (
            ActuatorId.PUMP_MOTOR,
            ActuatorId.PUMP_MOTOR_SPEED,
            ActuatorId.BOOSTER_PUMP,
        )

    def _reason(
        self,
        active_schedule_names: tuple[str, ...],
        actuator_id: ActuatorId,
        desired_state: ActuatorState,
        reason_override: str | None = None,
    ) -> str:
        if reason_override is not None:
            return (
                f"pump timer manual override ({reason_override}): "
                f"set {actuator_id.value} {desired_state.value}"
            )

        if not active_schedule_names:
            return f"pump timer outside scheduled window: set {actuator_id.value} {desired_state.value}"

        schedules = ", ".join(active_schedule_names)
        return (
            f"pump timer active schedule {schedules}: "
            f"set {actuator_id.value} {desired_state.value}"
        )


def load_pump_timer_config(path: str | Path) -> PumpTimerConfig:
    with Path(path).open("r", encoding="utf-8") as config_file:
        data = yaml.safe_load(config_file) or {}

    if not isinstance(data, Mapping):
        raise ValueError("pump timer config file must contain a mapping")

    return PumpTimerConfig.from_mapping(data)


def _schedule_from_mapping(data: object) -> PumpTimerSchedule:
    if not isinstance(data, Mapping):
        raise ValueError("pump timer schedule must be a mapping")

    name = _string_value(data, "name")
    start = TimeOfDay.parse(_string_value(data, "start"))
    end = TimeOfDay.parse(_string_value(data, "end"))

    return PumpTimerSchedule(
        name=name,
        window=DailyTimeWindow(name=name, start=start, end=end),
        pump_speed=_pump_speed_value(data.get("pump_speed", ActuatorState.LOW.value)),
        booster_state=_booster_state_value(data.get("booster", ActuatorState.OFF.value)),
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


def _string_value(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)

    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")

    return value


def _string_with_default(data: Mapping[str, Any], key: str, default: str) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _pump_speed_value(value: object) -> ActuatorState:
    if not isinstance(value, str):
        raise ValueError("pump_speed must be low or high")

    state = ActuatorState(value)
    if state not in (ActuatorState.LOW, ActuatorState.HIGH):
        raise ValueError("pump_speed must be low or high")

    return state


def _booster_state_value(value: object) -> ActuatorState:
    if isinstance(value, bool):
        return ActuatorState.ON if value else ActuatorState.OFF

    if not isinstance(value, str):
        raise ValueError("booster must be on or off")

    state = ActuatorState(value)
    if state not in (ActuatorState.ON, ActuatorState.OFF):
        raise ValueError("booster must be on or off")

    return state


def _validate_timezone(value: str) -> None:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"invalid timezone: {value}") from error


def _datetime_for_time_of_day(
    template: datetime,
    day: date,
    time_of_day: TimeOfDay,
) -> datetime:
    return template.replace(
        year=day.year,
        month=day.month,
        day=day.day,
        hour=time_of_day.hour,
        minute=time_of_day.minute,
        second=time_of_day.second,
        microsecond=0,
    )
