"""
Tests for open-loop chlorination schedule and duty-cycle behavior.

These cases protect dosing-window trimming, max duty-cycle limiting, FC-demand
adjustments, and ON/OFF relay timing decisions.
"""

from __future__ import annotations

from datetime import datetime, timezone

from poolctl.domain.models import (
    ACTUATOR_AUTO_OFF_AT_METADATA,
    ACTUATOR_ON_PULSE_SECONDS_METADATA,
    ActuatorId,
    ActuatorState,
    CommandSource,
)
from poolctl.services.chlorination import (
    ChlorinationConfig,
    ChlorinationController,
    ChlorinationPlanAdjustment,
    valid_dosing_windows_for_day,
)
from poolctl.services.pump_timer import PumpTimerConfig, PumpTimerSchedule
from poolctl.services.schedule import DailyTimeWindow, TimeOfDay


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 5, 21, hour, minute, second, tzinfo=timezone.utc)


def schedule(
    *,
    name: str = "filter",
    start: str = "08:00",
    end: str = "10:00",
    pump_speed: ActuatorState = ActuatorState.LOW,
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
        allow_dosing=allow_dosing,
    )


def timer_config(*schedules: PumpTimerSchedule) -> PumpTimerConfig:
    return PumpTimerConfig(timezone="UTC", schedules=schedules)


def dosing_actuator_states(
    *,
    dosing_pump: ActuatorState,
    pump_motor: ActuatorState = ActuatorState.ON,
    pump_speed: ActuatorState = ActuatorState.LOW,
    booster: ActuatorState = ActuatorState.OFF,
) -> dict[ActuatorId, ActuatorState]:
    return {
        ActuatorId.PUMP_MOTOR: pump_motor,
        ActuatorId.PUMP_MOTOR_SPEED: pump_speed,
        ActuatorId.BOOSTER_PUMP: booster,
        ActuatorId.CHLORINE_DOSING_PUMP: dosing_pump,
    }


def test_valid_dosing_windows_trim_last_minutes_of_merged_run() -> None:
    config = timer_config(
        schedule(name="first", start="08:00", end="10:00"),
        schedule(name="second", start="10:00", end="12:00"),
    )

    windows = valid_dosing_windows_for_day(
        config,
        at(0).date(),
        no_dose_last_minutes=10.0,
    )

    assert len(windows) == 1
    assert windows[0].start == at(8)
    assert windows[0].end == at(11, 50)
    assert windows[0].duration_seconds == 230.0 * 60.0


def test_valid_dosing_windows_ignore_schedules_that_disallow_dosing() -> None:
    config = timer_config(
        schedule(name="night_clean", start="20:00", end="23:00", allow_dosing=False),
    )

    windows = valid_dosing_windows_for_day(
        config,
        at(0).date(),
        no_dose_last_minutes=10.0,
    )

    assert windows == ()


def test_non_dosing_overlap_does_not_extend_allowed_dosing_window() -> None:
    config = timer_config(
        schedule(name="day_filter", start="08:00", end="10:00", allow_dosing=True),
        schedule(name="cleaner", start="09:00", end="12:00", allow_dosing=False),
    )

    windows = valid_dosing_windows_for_day(
        config,
        at(0).date(),
        no_dose_last_minutes=10.0,
    )

    assert len(windows) == 1
    assert windows[0].start == at(8)
    assert windows[0].end == at(9, 50)
    assert windows[0].duration_seconds == 110.0 * 60.0


def test_valid_dosing_windows_handle_overnight_schedules_without_midnight_trim() -> None:
    config = timer_config(schedule(name="night", start="22:00", end="02:00"))

    windows = valid_dosing_windows_for_day(
        config,
        at(0).date(),
        no_dose_last_minutes=10.0,
    )

    assert [window.start for window in windows] == [at(0), at(22)]
    assert [window.end for window in windows] == [
        at(1, 50),
        datetime(2026, 5, 22, 0, 0, tzinfo=timezone.utc),
    ]


def test_controller_turns_dosing_on_for_first_minute_of_duty_cycle() -> None:
    controller = ChlorinationController(
        ChlorinationConfig(
            daily_dose_oz=4.0,
            pump_output_oz_per_min=1.0,
            cycle_on_seconds=60.0,
        )
    )

    evaluation = controller.evaluate(
        now=at(8),
        pump_timer_config=timer_config(schedule()),
        actuator_states=dosing_actuator_states(dosing_pump=ActuatorState.OFF),
        layer_enabled=True,
    )

    assert evaluation.status.available_runtime_min_per_day == 110.0
    assert round(evaluation.status.duty_cycle, 4) == 0.0364
    assert round(evaluation.status.cycle_period_seconds or 0.0, 1) == 1650.0
    assert evaluation.status.active is True
    assert evaluation.status.duty_cycle_window_active is True
    assert len(evaluation.commands) == 1
    assert evaluation.commands[0].actuator_id == ActuatorId.CHLORINE_DOSING_PUMP
    assert evaluation.commands[0].state == ActuatorState.ON
    assert evaluation.commands[0].requested_by == CommandSource.CONTROLLER
    assert evaluation.commands[0].metadata[ACTUATOR_ON_PULSE_SECONDS_METADATA] == 60.0
    assert evaluation.commands[0].metadata[ACTUATOR_AUTO_OFF_AT_METADATA] == (
        at(8, 1).isoformat()
    )


def test_controller_turns_dosing_off_after_one_minute_on_interval() -> None:
    controller = ChlorinationController(
        ChlorinationConfig(
            daily_dose_oz=4.0,
            pump_output_oz_per_min=1.0,
            cycle_on_seconds=60.0,
        )
    )

    evaluation = controller.evaluate(
        now=at(8, 1),
        pump_timer_config=timer_config(schedule()),
        actuator_states=dosing_actuator_states(dosing_pump=ActuatorState.ON),
        layer_enabled=True,
    )

    assert evaluation.status.active is False
    assert evaluation.status.duty_cycle_window_active is True
    assert evaluation.status.reason == "open-loop chlorination duty cycle off interval"
    assert len(evaluation.commands) == 1
    assert evaluation.commands[0].state == ActuatorState.OFF


def test_controller_requires_booster_off_for_dosing() -> None:
    controller = ChlorinationController(
        ChlorinationConfig(
            daily_dose_oz=4.0,
            pump_output_oz_per_min=1.0,
            cycle_on_seconds=60.0,
        )
    )

    evaluation = controller.evaluate(
        now=at(8),
        pump_timer_config=timer_config(schedule()),
        actuator_states=dosing_actuator_states(
            dosing_pump=ActuatorState.ON,
            booster=ActuatorState.ON,
        ),
        layer_enabled=True,
    )

    assert evaluation.status.active is False
    assert evaluation.status.reason == "booster pump is on"
    assert evaluation.commands[0].state == ActuatorState.OFF


def test_controller_shortens_on_time_when_low_duty_would_exceed_max_cycle() -> None:
    controller = ChlorinationController(
        ChlorinationConfig(
            daily_dose_oz=2.0,
            pump_output_oz_per_min=1.0,
            cycle_on_seconds=60.0,
            max_cycle_period_seconds=1800.0,
            min_cycle_on_seconds=5.0,
        )
    )

    on_evaluation = controller.evaluate(
        now=at(8, 0, 32),
        pump_timer_config=timer_config(schedule()),
        actuator_states=dosing_actuator_states(dosing_pump=ActuatorState.OFF),
        layer_enabled=True,
    )

    assert round(on_evaluation.status.duty_cycle, 4) == 0.0182
    assert round(on_evaluation.status.cycle_on_seconds, 1) == 32.7
    assert on_evaluation.status.nominal_cycle_on_seconds == 60.0
    assert on_evaluation.status.cycle_period_seconds == 1800.0
    assert round(on_evaluation.status.cycle_off_seconds or 0.0, 1) == 1767.3
    assert on_evaluation.status.cycle_on_seconds_reduced is True
    assert on_evaluation.status.min_cycle_on_seconds_limited is False
    assert on_evaluation.status.active is True

    off_evaluation = controller.evaluate(
        now=at(8, 0, 33),
        pump_timer_config=timer_config(schedule()),
        actuator_states=dosing_actuator_states(dosing_pump=ActuatorState.ON),
        layer_enabled=True,
    )

    assert off_evaluation.status.active is False
    assert off_evaluation.commands[0].state == ActuatorState.OFF


def test_controller_uses_minimum_on_time_for_extremely_low_duty_cycle() -> None:
    controller = ChlorinationController(
        ChlorinationConfig(
            daily_dose_oz=0.22,
            pump_output_oz_per_min=1.0,
            cycle_on_seconds=60.0,
            max_cycle_period_seconds=1800.0,
            min_cycle_on_seconds=5.0,
        )
    )

    on_evaluation = controller.evaluate(
        now=at(8, 0, 4),
        pump_timer_config=timer_config(schedule()),
        actuator_states=dosing_actuator_states(dosing_pump=ActuatorState.OFF),
        layer_enabled=True,
    )

    assert round(on_evaluation.status.duty_cycle, 4) == 0.002
    assert on_evaluation.status.cycle_on_seconds == 5.0
    assert round(on_evaluation.status.cycle_period_seconds or 0.0, 1) == 2500.0
    assert round(on_evaluation.status.cycle_off_seconds or 0.0, 1) == 2495.0
    assert on_evaluation.status.cycle_on_seconds_reduced is True
    assert on_evaluation.status.min_cycle_on_seconds_limited is True
    assert on_evaluation.status.active is True

    off_evaluation = controller.evaluate(
        now=at(8, 0, 6),
        pump_timer_config=timer_config(schedule()),
        actuator_states=dosing_actuator_states(dosing_pump=ActuatorState.ON),
        layer_enabled=True,
    )

    assert off_evaluation.status.active is False
    assert off_evaluation.commands[0].state == ActuatorState.OFF


def test_controller_prohibits_dosing_during_final_no_dose_buffer() -> None:
    controller = ChlorinationController(
        ChlorinationConfig(daily_dose_oz=4.0, pump_output_oz_per_min=1.0)
    )

    evaluation = controller.evaluate(
        now=at(9, 55),
        pump_timer_config=timer_config(schedule()),
        actuator_states=dosing_actuator_states(dosing_pump=ActuatorState.ON),
        layer_enabled=True,
    )

    assert evaluation.status.active is False
    assert evaluation.status.reason == "outside valid dosing window"
    assert evaluation.commands[0].state == ActuatorState.OFF


def test_controller_caps_duty_cycle_and_reports_warning() -> None:
    controller = ChlorinationController(
        ChlorinationConfig(daily_dose_oz=100.0, pump_output_oz_per_min=1.0)
    )

    evaluation = controller.evaluate(
        now=at(8),
        pump_timer_config=timer_config(schedule()),
        actuator_states=dosing_actuator_states(dosing_pump=ActuatorState.OFF),
        layer_enabled=True,
    )

    assert evaluation.status.duty_cycle == 0.5
    assert evaluation.status.duty_cycle_limited is True
    assert evaluation.status.warning == "requested dose exceeds the configured maximum dosing duty cycle"


def test_config_rejects_impossible_cycle_timing() -> None:
    try:
        ChlorinationConfig(
            cycle_on_seconds=4.0,
            min_cycle_on_seconds=5.0,
        )
    except ValueError as error:
        assert str(error) == "chlorination.min_cycle_on_seconds must be <= cycle_on_seconds"
    else:
        raise AssertionError("minimum ON time above nominal ON time should be rejected")

    try:
        ChlorinationConfig(
            cycle_on_seconds=60.0,
            max_cycle_period_seconds=30.0,
        )
    except ValueError as error:
        assert str(error) == "chlorination.cycle_on_seconds must be <= max_cycle_period_seconds"
    else:
        raise AssertionError("nominal ON time above max cycle period should be rejected")


def test_controller_keeps_dosing_off_when_layer_disabled() -> None:
    controller = ChlorinationController(
        ChlorinationConfig(daily_dose_oz=4.0, pump_output_oz_per_min=1.0)
    )

    evaluation = controller.evaluate(
        now=at(8),
        pump_timer_config=timer_config(schedule()),
        actuator_states=dosing_actuator_states(dosing_pump=ActuatorState.ON),
        layer_enabled=False,
    )

    assert evaluation.status.active is False
    assert evaluation.status.reason == "chlorination layer disabled"
    assert evaluation.commands[0].state == ActuatorState.OFF


def test_controller_delays_dosing_by_eligible_minutes_without_changing_duty() -> None:
    controller = ChlorinationController(
        ChlorinationConfig(
            daily_dose_oz=4.0,
            pump_output_oz_per_min=1.0,
            no_dose_last_minutes=10.0,
            cycle_on_seconds=60.0,
        )
    )
    config = timer_config(schedule(start="08:00", end="15:10"))

    delayed = controller.evaluate(
        now=at(11, 0),
        pump_timer_config=config,
        actuator_states=dosing_actuator_states(dosing_pump=ActuatorState.ON),
        layer_enabled=True,
        plan_adjustment=ChlorinationPlanAdjustment(
            delay_eligible_seconds=210.0 * 60.0,
            source="fc_demand",
            reason="high FC delay",
        ),
    )

    assert delayed.status.available_runtime_min_per_day == 420.0
    assert round(delayed.status.delay_eligible_minutes, 3) == 210.0
    assert delayed.status.active is False
    assert delayed.status.duty_cycle_window_active is False
    assert delayed.status.reason == "dosing delayed by 210.0 eligible min"
    assert delayed.commands[0].state == ActuatorState.OFF

    resumed = controller.evaluate(
        now=at(11, 30),
        pump_timer_config=config,
        actuator_states=dosing_actuator_states(dosing_pump=ActuatorState.OFF),
        layer_enabled=True,
        plan_adjustment=ChlorinationPlanAdjustment(
            delay_eligible_seconds=210.0 * 60.0,
            source="fc_demand",
            reason="high FC delay",
        ),
    )

    assert round(resumed.status.duty_cycle, 4) == 0.0095
    assert resumed.status.active is True
    assert resumed.status.duty_cycle_window_active is True
    assert resumed.commands[0].state == ActuatorState.ON
