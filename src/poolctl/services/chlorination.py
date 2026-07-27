"""
Open-loop liquid chlorine dosing controller.

The controller converts a target ounces-per-day value into a duty cycle inside
the pump schedule. It deliberately treats diagnostic prime/calibration runs as
separate from normal chlorination so FC estimates are not distorted by tests.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from poolctl.domain.models import (
    ActuatorCommand,
    ActuatorId,
    ActuatorState,
    CommandSource,
)
from poolctl.services.pump_timer import PumpTimerConfig
from poolctl.services.schedule import TimeOfDay


@dataclass(frozen=True)
class ChlorinationConfig:
    """
    Open-loop liquid chlorine dosing settings.

    The controller computes a daily duty cycle from an ounce/day target and the
    configured dosing pump output. It deliberately does not track makeup dosing;
    a changed setpoint is used only for future controller evaluations.
    """

    enabled: bool = True
    daily_dose_oz: float = 0.0
    pump_output_oz_per_min: float = 1.0
    no_dose_last_minutes: float = 10.0
    max_duty_cycle: float = 0.5
    cycle_on_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.daily_dose_oz < 0:
            raise ValueError("chlorination.daily_dose_oz must be >= 0")
        if self.pump_output_oz_per_min <= 0:
            raise ValueError("chlorination.pump_output_oz_per_min must be > 0")
        if self.no_dose_last_minutes < 0:
            raise ValueError("chlorination.no_dose_last_minutes must be >= 0")
        if not 0 < self.max_duty_cycle <= 1:
            raise ValueError("chlorination.max_duty_cycle must be > 0 and <= 1")
        if self.cycle_on_seconds <= 0:
            raise ValueError("chlorination.cycle_on_seconds must be > 0")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ChlorinationConfig:
        config_data = _mapping_value(data, "chlorination", default={})
        return cls(
            enabled=_bool_value(config_data, "enabled", cls.enabled),
            daily_dose_oz=_float_value(config_data, "daily_dose_oz", cls.daily_dose_oz),
            pump_output_oz_per_min=_float_value(
                config_data,
                "pump_output_oz_per_min",
                cls.pump_output_oz_per_min,
            ),
            no_dose_last_minutes=_float_value(
                config_data,
                "no_dose_last_minutes",
                cls.no_dose_last_minutes,
            ),
            max_duty_cycle=_float_value(
                config_data,
                "max_duty_cycle",
                cls.max_duty_cycle,
            ),
            cycle_on_seconds=_float_value(
                config_data,
                "cycle_on_seconds",
                cls.cycle_on_seconds,
            ),
        )


@dataclass(frozen=True)
class DosingWindow:
    """
    One local-time window where open-loop dosing is allowed.
    """

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError("dosing window end must be after start")

    @property
    def duration_seconds(self) -> float:
        return (self.end - self.start).total_seconds()

    def contains(self, when: datetime) -> bool:
        return self.start <= when < self.end


@dataclass(frozen=True)
class ChlorinationStatus:
    enabled: bool
    layer_enabled: bool
    desired_state: ActuatorState
    active: bool
    reason: str
    daily_dose_oz: float
    base_daily_dose_oz: float
    pump_output_oz_per_min: float
    requested_runtime_min_per_day: float
    available_runtime_min_per_day: float
    duty_cycle: float
    max_duty_cycle: float
    duty_cycle_limited: bool
    cycle_on_seconds: float
    cycle_period_seconds: float | None
    no_dose_last_minutes: float
    eligible_window_active: bool
    duty_cycle_window_active: bool
    warning: str | None = None
    dose_adjustment_source: str | None = None
    dose_adjustment_reason: str | None = None
    delay_eligible_minutes: float = 0.0
    next_eligible_start: datetime | None = None
    current_window_end: datetime | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "layer_enabled": self.layer_enabled,
            "desired_state": self.desired_state.value,
            "active": self.active,
            "reason": self.reason,
            "daily_dose_oz": self.daily_dose_oz,
            "base_daily_dose_oz": self.base_daily_dose_oz,
            "pump_output_oz_per_min": self.pump_output_oz_per_min,
            "requested_runtime_min_per_day": self.requested_runtime_min_per_day,
            "available_runtime_min_per_day": self.available_runtime_min_per_day,
            "duty_cycle": self.duty_cycle,
            "duty_cycle_percent": self.duty_cycle * 100.0,
            "max_duty_cycle": self.max_duty_cycle,
            "duty_cycle_limited": self.duty_cycle_limited,
            "cycle_on_seconds": self.cycle_on_seconds,
            "cycle_period_seconds": self.cycle_period_seconds,
            "no_dose_last_minutes": self.no_dose_last_minutes,
            "eligible_window_active": self.eligible_window_active,
            "duty_cycle_window_active": self.duty_cycle_window_active,
            "warning": self.warning,
            "dose_adjustment_source": self.dose_adjustment_source,
            "dose_adjustment_reason": self.dose_adjustment_reason,
            "delay_eligible_minutes": self.delay_eligible_minutes,
            "next_eligible_start": (
                self.next_eligible_start.isoformat()
                if self.next_eligible_start is not None
                else None
            ),
            "current_window_end": (
                self.current_window_end.isoformat()
                if self.current_window_end is not None
                else None
            ),
        }


@dataclass(frozen=True)
class ChlorinationPlanAdjustment:
    """
    Optional day-specific adjustment applied before duty-cycle evaluation.

    This is used by higher-level estimators to change the effective daily dose
    or delay the start of eligible dosing time without changing the persisted
    open-loop chlorination setpoint.
    """

    daily_dose_oz: float | None = None
    delay_eligible_seconds: float = 0.0
    source: str = "controller_adjustment"
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.daily_dose_oz is not None and self.daily_dose_oz < 0:
            raise ValueError("daily_dose_oz adjustment must be >= 0")
        if self.delay_eligible_seconds < 0:
            raise ValueError("delay_eligible_seconds must be >= 0")


@dataclass(frozen=True)
class ChlorinationEvaluation:
    status: ChlorinationStatus
    commands: tuple[ActuatorCommand, ...]


class ChlorinationController:
    """
    Computes relay commands for open-loop liquid chlorine dosing.
    """

    def __init__(self, config: ChlorinationConfig) -> None:
        self.config = config

    def evaluate(
        self,
        *,
        now: datetime,
        pump_timer_config: PumpTimerConfig,
        actuator_states: Mapping[ActuatorId, ActuatorState],
        layer_enabled: bool = True,
        plan_adjustment: ChlorinationPlanAdjustment | None = None,
    ) -> ChlorinationEvaluation:
        timezone = ZoneInfo(pump_timer_config.timezone)
        local_now = now.astimezone(timezone)

        # Users schedule pool equipment by local clock time, so the controller
        # converts once here and keeps all dosing-window math in local time.
        windows = valid_dosing_windows_for_day(
            pump_timer_config,
            local_now.date(),
            no_dose_last_minutes=self.config.no_dose_last_minutes,
        )
        available_runtime_min = sum(window.duration_seconds for window in windows) / 60.0

        # Start with the configured open-loop daily dose. FC demand estimation
        # may override today's effective dose or delay today's start, but those
        # planner changes are not written back into the YAML setpoint.
        effective_daily_dose_oz = self.config.daily_dose_oz
        dose_adjustment_source = None
        dose_adjustment_reason = None
        delay_eligible_seconds = 0.0
        if plan_adjustment is not None:
            dose_adjustment_source = plan_adjustment.source
            dose_adjustment_reason = plan_adjustment.reason
            delay_eligible_seconds = plan_adjustment.delay_eligible_seconds
            if plan_adjustment.daily_dose_oz is not None:
                effective_daily_dose_oz = plan_adjustment.daily_dose_oz

        # Convert fluid ounces into dosing pump runtime, then divide that runtime
        # by the available schedule minutes to get the fraction of eligible time
        # where the relay should be ON.
        requested_runtime_min = effective_daily_dose_oz / self.config.pump_output_oz_per_min
        raw_duty_cycle = (
            requested_runtime_min / available_runtime_min
            if available_runtime_min > 0
            else 0.0
        )
        duty_cycle_limited = raw_duty_cycle > self.config.max_duty_cycle
        duty_cycle = min(raw_duty_cycle, self.config.max_duty_cycle)

        # Example: with a 60 s ON pulse and 25% duty cycle, the complete period
        # is 240 s, which means 60 s ON followed by 180 s OFF.
        cycle_period_seconds = (
            self.config.cycle_on_seconds / duty_cycle
            if duty_cycle > 0
            else None
        )
        current_window = _current_window(windows, local_now)
        next_eligible_start = _next_eligible_start(
            pump_timer_config,
            local_now,
            no_dose_last_minutes=self.config.no_dose_last_minutes,
        )
        desired_state = ActuatorState.OFF
        reason = "dosing idle"
        warning = (
            "requested dose exceeds the configured maximum dosing duty cycle"
            if duty_cycle_limited
            else None
        )
        duty_cycle_window_active = False

        if not layer_enabled:
            reason = "chlorination layer disabled"
        elif not self.config.enabled:
            reason = "chlorination disabled"
        elif effective_daily_dose_oz <= 0:
            reason = "daily dose is zero"
        elif available_runtime_min <= 0:
            reason = "no valid dosing time in pump schedule"
            warning = "no valid dosing time in pump schedule"
        elif actuator_states.get(ActuatorId.PUMP_MOTOR) != ActuatorState.ON:
            reason = "pump motor is not on"
        elif current_window is None:
            reason = "outside valid dosing window"
        elif cycle_period_seconds is None:
            reason = "dosing duty cycle is zero"
        else:
            # Duty-cycle position is measured in eligible dosing time, not raw
            # wall-clock time. If there are multiple pump windows in a day, the
            # ON/OFF pattern resumes where the previous valid window stopped.
            elapsed_eligible_seconds = _elapsed_eligible_seconds(windows, local_now)
            if delay_eligible_seconds > 0 and elapsed_eligible_seconds < delay_eligible_seconds:
                delay_min = delay_eligible_seconds / 60.0
                reason = f"dosing delayed by {delay_min:.1f} eligible min"
            else:
                adjusted_elapsed_seconds = max(
                    0.0,
                    elapsed_eligible_seconds - delay_eligible_seconds,
                )
                cycle_position = adjusted_elapsed_seconds % cycle_period_seconds
                duty_cycle_window_active = True
                # The background runtime must tick faster than this boundary
                # changes. A slow tick turns the relay off late and physically
                # delivers more chlorine than the model records.
                if cycle_position < self.config.cycle_on_seconds:
                    desired_state = ActuatorState.ON
                    reason = "open-loop chlorination duty cycle on interval"
                else:
                    reason = "open-loop chlorination duty cycle off interval"

        status = ChlorinationStatus(
            enabled=self.config.enabled,
            layer_enabled=layer_enabled,
            desired_state=desired_state,
            active=desired_state == ActuatorState.ON,
            reason=reason,
            daily_dose_oz=effective_daily_dose_oz,
            base_daily_dose_oz=self.config.daily_dose_oz,
            pump_output_oz_per_min=self.config.pump_output_oz_per_min,
            requested_runtime_min_per_day=requested_runtime_min,
            available_runtime_min_per_day=available_runtime_min,
            duty_cycle=duty_cycle,
            max_duty_cycle=self.config.max_duty_cycle,
            duty_cycle_limited=duty_cycle_limited,
            cycle_on_seconds=self.config.cycle_on_seconds,
            cycle_period_seconds=cycle_period_seconds,
            no_dose_last_minutes=self.config.no_dose_last_minutes,
            eligible_window_active=current_window is not None,
            duty_cycle_window_active=duty_cycle_window_active,
            warning=warning,
            dose_adjustment_source=dose_adjustment_source,
            dose_adjustment_reason=dose_adjustment_reason,
            delay_eligible_minutes=delay_eligible_seconds / 60.0,
            next_eligible_start=next_eligible_start,
            current_window_end=current_window.end if current_window is not None else None,
        )

        current_state = actuator_states.get(ActuatorId.CHLORINE_DOSING_PUMP, ActuatorState.OFF)
        commands: tuple[ActuatorCommand, ...] = ()
        if current_state != desired_state:
            # Only command actual relay transitions. Re-sending ON every tick is
            # unnecessary Modbus traffic and can make timing harder to reason
            # about when the bus is shared with sensors.
            commands = (
                ActuatorCommand(
                    actuator_id=ActuatorId.CHLORINE_DOSING_PUMP,
                    created_at=now,
                    state=desired_state,
                    requested_by=CommandSource.CONTROLLER,
                    reason=reason,
                    metadata={
                        "controller": "open_loop_chlorination",
                        "daily_dose_oz": effective_daily_dose_oz,
                        "base_daily_dose_oz": self.config.daily_dose_oz,
                        "pump_output_oz_per_min": self.config.pump_output_oz_per_min,
                        "available_runtime_min_per_day": available_runtime_min,
                        "requested_runtime_min_per_day": requested_runtime_min,
                        "duty_cycle": duty_cycle,
                        "duty_cycle_limited": duty_cycle_limited,
                        "dose_adjustment_source": dose_adjustment_source,
                        "dose_adjustment_reason": dose_adjustment_reason,
                        "delay_eligible_seconds": delay_eligible_seconds,
                    },
                ),
            )

        return ChlorinationEvaluation(status=status, commands=commands)


def valid_dosing_windows_for_day(
    config: PumpTimerConfig,
    day: date,
    *,
    no_dose_last_minutes: float,
) -> tuple[DosingWindow, ...]:
    """
    Return local-time valid dosing windows that overlap one calendar day.
    """
    timezone = ZoneInfo(config.timezone)
    day_start = datetime(
        day.year,
        day.month,
        day.day,
        tzinfo=timezone,
    )
    day_end = day_start + timedelta(days=1)
    raw_intervals = _raw_schedule_intervals(config, day)
    merged_intervals = _merge_intervals(raw_intervals)
    trim = timedelta(minutes=no_dose_last_minutes)
    windows: list[DosingWindow] = []

    for raw_start, raw_end in merged_intervals:
        # Remove the end of each pump run so the dosing pump stops while the
        # filter pump still has time to circulate treated water.
        valid_end = raw_end - trim
        if valid_end <= raw_start:
            continue
        clipped_start = max(raw_start, day_start)
        clipped_end = min(valid_end, day_end)
        if clipped_end > clipped_start:
            windows.append(DosingWindow(start=clipped_start, end=clipped_end))

    return tuple(windows)


def _raw_schedule_intervals(
    config: PumpTimerConfig,
    day: date,
) -> tuple[tuple[datetime, datetime], ...]:
    timezone = ZoneInfo(config.timezone)
    intervals: list[tuple[datetime, datetime]] = []

    # Look at yesterday, today, and tomorrow because a pump window may cross
    # midnight. A window that starts yesterday evening can still overlap today's
    # dosing window after midnight.
    for day_offset in (-1, 0, 1):
        schedule_day = day + timedelta(days=day_offset)
        for schedule in config.schedules:
            start = _datetime_for_time_of_day(schedule_day, schedule.window.start, timezone)
            if schedule.window.start == schedule.window.end:
                end = start + timedelta(days=1)
            else:
                end = _datetime_for_time_of_day(schedule_day, schedule.window.end, timezone)
                if end <= start:
                    end += timedelta(days=1)
            intervals.append((start, end))

    return tuple(intervals)


def _merge_intervals(
    intervals: tuple[tuple[datetime, datetime], ...],
) -> tuple[tuple[datetime, datetime], ...]:
    if not intervals:
        return ()

    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(intervals, key=lambda item: item[0]):
        if end <= start:
            continue
        if not merged:
            merged.append((start, end))
            continue
        previous_start, previous_end = merged[-1]
        if start <= previous_end:
            # Overlapping or touching pump windows should produce one continuous
            # dosing window; otherwise the duty cycle could reset in the middle
            # of what is physically one pump run.
            merged[-1] = (previous_start, max(previous_end, end))
            continue
        merged.append((start, end))

    return tuple(merged)


def _datetime_for_time_of_day(
    day: date,
    value: TimeOfDay,
    timezone: ZoneInfo,
) -> datetime:
    return datetime(
        day.year,
        day.month,
        day.day,
        value.hour,
        value.minute,
        value.second,
        tzinfo=timezone,
    )


def _current_window(
    windows: tuple[DosingWindow, ...],
    local_now: datetime,
) -> DosingWindow | None:
    for window in windows:
        if window.contains(local_now):
            return window
    return None


def _next_eligible_start(
    config: PumpTimerConfig,
    local_now: datetime,
    *,
    no_dose_last_minutes: float,
) -> datetime | None:
    for day_offset in range(3):
        day = local_now.date() + timedelta(days=day_offset)
        for window in valid_dosing_windows_for_day(
            config,
            day,
            no_dose_last_minutes=no_dose_last_minutes,
        ):
            if local_now < window.start:
                return window.start
            if window.contains(local_now):
                return local_now

    return None


def _elapsed_eligible_seconds(
    windows: tuple[DosingWindow, ...],
    local_now: datetime,
) -> float:
    # Add all completed valid windows, plus the elapsed portion of the current
    # one. The result is the dosing controller's local "clock" for the day.
    elapsed = 0.0
    for window in windows:
        if local_now >= window.end:
            elapsed += window.duration_seconds
            continue
        if window.contains(local_now):
            elapsed += (local_now - window.start).total_seconds()
        break
    return max(0.0, elapsed)


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


def _float_value(data: Mapping[str, Any], key: str, default: float) -> float:
    value = data.get(key, default)
    if not isinstance(value, int | float):
        raise ValueError(f"{key} must be a number")
    return float(value)


def _bool_value(data: Mapping[str, Any], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false")
    return value
