from __future__ import annotations

from datetime import datetime, timezone

from poolctl.domain.models import ActuatorId, ActuatorState, CommandSource
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
) -> PumpTimerSchedule:
    return PumpTimerSchedule(
        name=name,
        window=DailyTimeWindow(
            name=name,
            start=TimeOfDay.parse(start),
            end=TimeOfDay.parse(end),
        ),
        pump_speed=pump_speed,
    )


def timer_config(*schedules: PumpTimerSchedule) -> PumpTimerConfig:
    return PumpTimerConfig(timezone="UTC", schedules=schedules)


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
        actuator_states={
            ActuatorId.PUMP_MOTOR: ActuatorState.ON,
            ActuatorId.CHLORINE_DOSING_PUMP: ActuatorState.OFF,
        },
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
        actuator_states={
            ActuatorId.PUMP_MOTOR: ActuatorState.ON,
            ActuatorId.CHLORINE_DOSING_PUMP: ActuatorState.ON,
        },
        layer_enabled=True,
    )

    assert evaluation.status.active is False
    assert evaluation.status.duty_cycle_window_active is True
    assert evaluation.status.reason == "open-loop chlorination duty cycle off interval"
    assert len(evaluation.commands) == 1
    assert evaluation.commands[0].state == ActuatorState.OFF


def test_controller_prohibits_dosing_during_final_no_dose_buffer() -> None:
    controller = ChlorinationController(
        ChlorinationConfig(daily_dose_oz=4.0, pump_output_oz_per_min=1.0)
    )

    evaluation = controller.evaluate(
        now=at(9, 55),
        pump_timer_config=timer_config(schedule()),
        actuator_states={
            ActuatorId.PUMP_MOTOR: ActuatorState.ON,
            ActuatorId.CHLORINE_DOSING_PUMP: ActuatorState.ON,
        },
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
        actuator_states={
            ActuatorId.PUMP_MOTOR: ActuatorState.ON,
            ActuatorId.CHLORINE_DOSING_PUMP: ActuatorState.OFF,
        },
        layer_enabled=True,
    )

    assert evaluation.status.duty_cycle == 0.5
    assert evaluation.status.duty_cycle_limited is True
    assert evaluation.status.warning == "requested dose exceeds the configured maximum dosing duty cycle"


def test_controller_keeps_dosing_off_when_layer_disabled() -> None:
    controller = ChlorinationController(
        ChlorinationConfig(daily_dose_oz=4.0, pump_output_oz_per_min=1.0)
    )

    evaluation = controller.evaluate(
        now=at(8),
        pump_timer_config=timer_config(schedule()),
        actuator_states={
            ActuatorId.PUMP_MOTOR: ActuatorState.ON,
            ActuatorId.CHLORINE_DOSING_PUMP: ActuatorState.ON,
        },
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
        actuator_states={
            ActuatorId.PUMP_MOTOR: ActuatorState.ON,
            ActuatorId.CHLORINE_DOSING_PUMP: ActuatorState.ON,
        },
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
        actuator_states={
            ActuatorId.PUMP_MOTOR: ActuatorState.ON,
            ActuatorId.CHLORINE_DOSING_PUMP: ActuatorState.OFF,
        },
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
