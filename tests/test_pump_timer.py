from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from poolctl.domain.models import ActuatorId, ActuatorState, CommandSource
from poolctl.services.pump_timer import (
    PumpTimer,
    PumpTimerConfig,
    PumpTimerSchedule,
    load_pump_timer_config,
)
from poolctl.services.schedule import DailyTimeWindow, TimeOfDay


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 5, 21, hour, minute, tzinfo=timezone.utc)


def schedule(
    *,
    name: str = "filter",
    start: str = "08:00",
    end: str = "12:00",
    pump_speed: ActuatorState = ActuatorState.HIGH,
    booster_state: ActuatorState = ActuatorState.OFF,
) -> PumpTimerSchedule:
    return PumpTimerSchedule(
        name=name,
        window=DailyTimeWindow(
            name=name,
            start=TimeOfDay.parse(start),
            end=TimeOfDay.parse(end),
        ),
        pump_speed=pump_speed,
        booster_state=booster_state,
    )


def test_daily_window_contains_times_inside_normal_window() -> None:
    window = DailyTimeWindow(
        name="day",
        start=TimeOfDay.parse("08:00"),
        end=TimeOfDay.parse("12:00"),
    )

    assert not window.contains(at(7, 59))
    assert window.contains(at(8, 0))
    assert window.contains(at(11, 59))
    assert not window.contains(at(12, 0))


def test_daily_window_contains_times_inside_overnight_window() -> None:
    window = DailyTimeWindow(
        name="night",
        start=TimeOfDay.parse("22:00"),
        end=TimeOfDay.parse("02:00"),
    )

    assert window.contains(at(23, 0))
    assert window.contains(at(1, 30))
    assert not window.contains(at(12, 0))


def test_active_schedule_turns_pump_on_at_desired_speed() -> None:
    timer = PumpTimer(PumpTimerConfig(schedules=(schedule(),)))

    evaluation = timer.evaluate(now=at(9), actuator_states={})

    assert evaluation.active_schedule_names == ("filter",)
    assert evaluation.desired_states == {
        ActuatorId.PUMP_MOTOR: ActuatorState.ON,
        ActuatorId.PUMP_MOTOR_SPEED: ActuatorState.HIGH,
        ActuatorId.BOOSTER_PUMP: ActuatorState.OFF,
    }
    assert [command.actuator_id for command in evaluation.commands] == [
        ActuatorId.PUMP_MOTOR,
        ActuatorId.PUMP_MOTOR_SPEED,
        ActuatorId.BOOSTER_PUMP,
    ]
    assert all(command.requested_by == CommandSource.TIMER for command in evaluation.commands)


def test_inactive_schedule_turns_booster_off_before_pump() -> None:
    timer = PumpTimer(PumpTimerConfig(schedules=(schedule(),)))

    evaluation = timer.evaluate(
        now=at(13),
        actuator_states={
            ActuatorId.PUMP_MOTOR: ActuatorState.ON,
            ActuatorId.PUMP_MOTOR_SPEED: ActuatorState.HIGH,
            ActuatorId.BOOSTER_PUMP: ActuatorState.ON,
        },
    )

    assert evaluation.active_schedule_names == ()
    assert [command.actuator_id for command in evaluation.commands] == [
        ActuatorId.BOOSTER_PUMP,
        ActuatorId.PUMP_MOTOR,
        ActuatorId.PUMP_MOTOR_SPEED,
    ]
    assert [command.state for command in evaluation.commands] == [
        ActuatorState.OFF,
        ActuatorState.OFF,
        ActuatorState.LOW,
    ]


def test_overlapping_schedules_merge_to_high_speed_and_booster_on() -> None:
    timer = PumpTimer(
        PumpTimerConfig(
            schedules=(
                schedule(
                    name="low_filter",
                    start="08:00",
                    end="12:00",
                    pump_speed=ActuatorState.LOW,
                    booster_state=ActuatorState.OFF,
                ),
                schedule(
                    name="booster",
                    start="09:00",
                    end="10:00",
                    pump_speed=ActuatorState.HIGH,
                    booster_state=ActuatorState.ON,
                ),
            )
        )
    )

    evaluation = timer.evaluate(now=at(9, 30), actuator_states={})

    assert evaluation.active_schedule_names == ("low_filter", "booster")
    assert evaluation.desired_states[ActuatorId.PUMP_MOTOR_SPEED] == ActuatorState.HIGH
    assert evaluation.desired_states[ActuatorId.BOOSTER_PUMP] == ActuatorState.ON


def test_timer_does_not_emit_commands_for_states_already_matching() -> None:
    timer = PumpTimer(PumpTimerConfig(schedules=(schedule(),)))

    evaluation = timer.evaluate(
        now=at(9),
        actuator_states={
            ActuatorId.PUMP_MOTOR: ActuatorState.ON,
            ActuatorId.PUMP_MOTOR_SPEED: ActuatorState.HIGH,
            ActuatorId.BOOSTER_PUMP: ActuatorState.OFF,
        },
    )

    assert evaluation.commands == ()


def test_load_pump_timer_config_from_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "pool.yaml"
    config_path.write_text(
        """
pump_timer:
  timezone: America/Chicago
  schedules:
    - name: morning_filter
      start: "08:00"
      end: "12:00"
      pump_speed: high
      booster: off
""",
        encoding="utf-8",
    )

    config = load_pump_timer_config(config_path)

    assert len(config.schedules) == 1
    assert config.timezone == "America/Chicago"
    assert config.schedules[0].name == "morning_filter"
    assert config.schedules[0].pump_speed == ActuatorState.HIGH
    assert config.schedules[0].booster_state == ActuatorState.OFF


def test_timer_uses_configured_timezone() -> None:
    timer = PumpTimer(
        PumpTimerConfig(
            timezone="America/Chicago",
            schedules=(schedule(start="08:00", end="12:00"),),
        )
    )

    # 14:00 UTC on 2026-05-21 is 09:00 America/Chicago (CDT).
    evaluation = timer.evaluate(now=at(14), actuator_states={})
    assert evaluation.active_schedule_names == ("filter",)
