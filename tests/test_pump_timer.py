"""
Tests for pump schedules and manual overrides.

These cases document local-time schedule evaluation, override latching, and the
next-scheduled-event behavior used by the live controls.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from poolctl.config import SiteConfig
from poolctl.domain.models import ActuatorId, ActuatorState, CommandSource
from poolctl.services.pump_timer import (
    PumpTimer,
    PumpTimerConfig,
    PumpTimerSchedule,
    DaylightFractionTiming,
    FixedTiming,
    ScheduleProfile,
    ScheduleResolver,
    SolarAnchorTiming,
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
    allow_dosing: bool = True,
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
        allow_dosing=allow_dosing,
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


def test_next_transition_after_returns_next_desired_state_change() -> None:
    timer = PumpTimer(
        PumpTimerConfig(
            schedules=(
                schedule(
                    name="filter",
                    start="08:00",
                    end="10:00",
                    pump_speed=ActuatorState.LOW,
                ),
            )
        )
    )

    assert timer.next_transition_after(at(7)) == at(8)
    assert timer.next_transition_after(at(9)) == at(10)


def test_next_transition_after_handles_overnight_windows() -> None:
    timer = PumpTimer(
        PumpTimerConfig(
            schedules=(
                schedule(
                    name="freeze",
                    start="22:00",
                    end="02:00",
                    pump_speed=ActuatorState.LOW,
                ),
            )
        )
    )

    assert timer.next_transition_after(at(23)) == datetime(2026, 5, 22, 2, 0, tzinfo=timezone.utc)


def test_next_transition_after_returns_none_for_all_day_schedule() -> None:
    timer = PumpTimer(
        PumpTimerConfig(
            schedules=(
                schedule(
                    name="all_day",
                    start="00:00",
                    end="00:00",
                    pump_speed=ActuatorState.LOW,
                ),
            )
        )
    )

    assert timer.next_transition_after(at(12)) is None


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
      allow_dosing: false
""",
        encoding="utf-8",
    )

    config = load_pump_timer_config(config_path)

    assert len(config.schedules) == 1
    assert config.timezone == "America/Chicago"
    assert config.schedules[0].name == "morning_filter"
    assert config.schedules[0].pump_speed == ActuatorState.HIGH
    assert config.schedules[0].booster_state == ActuatorState.OFF
    assert config.schedules[0].allow_dosing is False


def test_pump_timer_schedule_defaults_to_allowing_dosing() -> None:
    config = PumpTimerConfig.from_mapping(
        {
            "pump_timer": {
                "timezone": "UTC",
                "schedules": [
                    {
                        "name": "day_filter",
                        "start": "08:00",
                        "end": "12:00",
                        "pump_speed": "low",
                        "booster": "off",
                    }
                ],
            }
        }
    )

    assert config.schedules[0].allow_dosing is True
    assert config.active_profile == "normal"
    assert config.profiles[0].name == "normal"


def test_pump_timer_rejects_non_boolean_allow_dosing() -> None:
    try:
        PumpTimerConfig.from_mapping(
            {
                "pump_timer": {
                    "timezone": "UTC",
                    "schedules": [
                        {
                            "name": "day_filter",
                            "start": "08:00",
                            "end": "12:00",
                            "allow_dosing": "yes",
                        }
                    ],
                }
            }
        )
    except ValueError as error:
        assert str(error) == "allow_dosing must be true or false"
    else:
        raise AssertionError("non-boolean allow_dosing should be rejected")


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


class FixedAstronomy:
    def sunrise_sunset(
        self,
        *,
        day: date,
        site: SiteConfig,
    ) -> tuple[datetime, datetime]:
        zone = ZoneInfo(site.timezone)
        return (
            datetime(day.year, day.month, day.day, 6, 0, tzinfo=zone),
            datetime(day.year, day.month, day.day, 18, 0, tzinfo=zone),
        )


def solar_config(*schedules: PumpTimerSchedule) -> PumpTimerConfig:
    return PumpTimerConfig(
        site=SiteConfig(
            timezone="America/Chicago",
            latitude=41.88,
            longitude=-87.63,
        ),
        profiles=(ScheduleProfile(name="normal", schedules=tuple(schedules)),),
    )


def test_solar_anchor_resolves_offset_and_duration() -> None:
    config = solar_config(
        PumpTimerSchedule(
            name="after_sunrise",
            timing=SolarAnchorTiming(
                anchor="sunrise",
                offset_minutes=30,
                duration_minutes=90,
            ),
        )
    )

    resolved = ScheduleResolver(FixedAstronomy()).resolve_day(config, date(2026, 6, 1))

    assert resolved.sunrise is not None
    assert resolved.windows[0].start.strftime("%H:%M") == "06:30"
    assert resolved.windows[0].end.strftime("%H:%M") == "08:00"


def test_astral_provider_resolves_real_site_without_network() -> None:
    config = solar_config(
        PumpTimerSchedule(
            name="sunrise_run",
            timing=SolarAnchorTiming(anchor="sunrise", duration_minutes=60),
        )
    )

    resolved = ScheduleResolver().resolve_day(config, date(2026, 6, 1))

    assert resolved.warnings == ()
    assert resolved.sunrise is not None
    assert resolved.sunset is not None
    assert resolved.sunrise < resolved.sunset
    assert resolved.windows[0].start == resolved.sunrise


def test_daylight_fraction_uses_elapsed_daylight() -> None:
    config = solar_config(
        PumpTimerSchedule(
            name="middle_half",
            timing=DaylightFractionTiming(start_fraction=0.25, end_fraction=0.75),
        )
    )

    resolved = ScheduleResolver(FixedAstronomy()).resolve_day(config, date(2026, 6, 1))

    assert resolved.windows[0].start.strftime("%H:%M") == "09:00"
    assert resolved.windows[0].end.strftime("%H:%M") == "15:00"


def test_daylight_fraction_supports_before_sunrise_and_after_sunset() -> None:
    config = solar_config(
        PumpTimerSchedule(
            name="extended_daylight",
            timing=DaylightFractionTiming(start_fraction=-0.1, end_fraction=1.1),
        )
    )

    resolved = ScheduleResolver(FixedAstronomy()).resolve_day(config, date(2026, 6, 1))

    assert resolved.windows[0].start.strftime("%H:%M") == "04:48"
    assert resolved.windows[0].end.strftime("%H:%M") == "19:12"


def test_solar_schedule_requires_site_coordinates() -> None:
    try:
        PumpTimerConfig(
            site=SiteConfig(timezone="America/Chicago"),
            schedules=(
                PumpTimerSchedule(
                    name="sunrise",
                    timing=SolarAnchorTiming(anchor="sunrise", duration_minutes=60),
                ),
            ),
        )
    except ValueError as error:
        assert "site.latitude and site.longitude" in str(error)
    else:
        raise AssertionError("solar schedules without coordinates should be rejected")


def test_fixed_time_in_dst_gap_moves_to_first_valid_instant() -> None:
    config = PumpTimerConfig(
        timezone="America/Chicago",
        schedules=(
            PumpTimerSchedule(
                name="gap",
                timing=FixedTiming(
                    start=TimeOfDay.parse("02:30"),
                    duration_minutes=30,
                ),
            ),
        ),
    )

    resolved = ScheduleResolver().resolve_day(config, date(2026, 3, 8))

    assert resolved.windows[0].start.strftime("%H:%M %z") == "03:00 -0500"


def test_ambiguous_fixed_time_uses_first_occurrence() -> None:
    config = PumpTimerConfig(
        timezone="America/Chicago",
        schedules=(
            PumpTimerSchedule(
                name="fold",
                timing=FixedTiming(
                    start=TimeOfDay.parse("01:30"),
                    duration_minutes=30,
                ),
            ),
        ),
    )

    resolved = ScheduleResolver().resolve_day(config, date(2026, 11, 1))

    assert resolved.windows[0].start.strftime("%H:%M %z") == "01:30 -0500"


def test_active_profile_selects_only_that_profiles_events() -> None:
    normal = ScheduleProfile(name="normal", schedules=(schedule(name="normal_run"),))
    away = ScheduleProfile(
        name="away",
        schedules=(schedule(name="away_run", start="10:00", end="11:00"),),
    )
    timer = PumpTimer(
        PumpTimerConfig(profiles=(normal, away), active_profile="away")
    )

    assert timer.evaluate(now=at(9), actuator_states={}).active_schedule_names == ()
    assert timer.evaluate(now=at(10, 30), actuator_states={}).active_schedule_names == (
        "away_run",
    )
