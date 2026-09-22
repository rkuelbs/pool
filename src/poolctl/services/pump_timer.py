"""Pump schedule configuration, solar resolution, and actuator evaluation."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol, TypeAlias
from zoneinfo import ZoneInfo

import yaml  # type: ignore[import-untyped]

from poolctl.config import SiteConfig
from poolctl.domain.models import (
    ActuatorCommand,
    ActuatorId,
    ActuatorState,
    CommandSource,
)
from poolctl.services.schedule import DailyTimeWindow, TimeOfDay


@dataclass(frozen=True)
class FixedTiming:
    start: TimeOfDay
    end: TimeOfDay | None = None
    duration_minutes: float | None = None
    type: str = "fixed"

    def __post_init__(self) -> None:
        if (self.end is None) == (self.duration_minutes is None):
            raise ValueError("fixed timing requires exactly one of end or duration_minutes")
        if self.duration_minutes is not None and self.duration_minutes <= 0:
            raise ValueError("fixed duration_minutes must be greater than zero")


@dataclass(frozen=True)
class SolarAnchorTiming:
    anchor: str
    duration_minutes: float
    offset_minutes: float = 0.0
    type: str = "solar_anchor"

    def __post_init__(self) -> None:
        if self.anchor not in {"sunrise", "sunset", "daylight_midpoint"}:
            raise ValueError("solar anchor must be sunrise, sunset, or daylight_midpoint")
        if not math.isfinite(self.offset_minutes):
            raise ValueError("solar offset_minutes must be finite")
        if not math.isfinite(self.duration_minutes) or self.duration_minutes <= 0:
            raise ValueError("solar duration_minutes must be finite and greater than zero")


@dataclass(frozen=True)
class DaylightFractionTiming:
    start_fraction: float
    end_fraction: float
    type: str = "daylight_fraction"

    def __post_init__(self) -> None:
        if not math.isfinite(self.start_fraction) or not math.isfinite(self.end_fraction):
            raise ValueError("daylight fractions must be finite")
        if self.end_fraction <= self.start_fraction:
            raise ValueError("daylight end_fraction must be greater than start_fraction")


ScheduleTiming: TypeAlias = FixedTiming | SolarAnchorTiming | DaylightFractionTiming


@dataclass(frozen=True)
class PumpTimerSchedule:
    """One pump schedule event, using either legacy or typed timing."""

    name: str
    window: DailyTimeWindow | None = None
    pump_speed: ActuatorState = ActuatorState.LOW
    booster_state: ActuatorState = ActuatorState.OFF
    allow_dosing: bool = True
    enabled: bool = True
    timing: ScheduleTiming | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("pump timer schedule name cannot be empty")
        if self.pump_speed not in (ActuatorState.LOW, ActuatorState.HIGH):
            raise ValueError("pump_speed must be low or high")
        if self.booster_state not in (ActuatorState.ON, ActuatorState.OFF):
            raise ValueError("booster_state must be on or off")
        if not isinstance(self.allow_dosing, bool):
            raise ValueError("allow_dosing must be true or false")
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be true or false")
        if self.window is None and self.timing is None:
            raise ValueError("pump timer schedule requires timing")
        if self.window is not None and self.timing is not None:
            legacy = FixedTiming(start=self.window.start, end=self.window.end)
            if self.timing != legacy:
                raise ValueError("schedule window and timing disagree")
        if self.timing is None:
            assert self.window is not None
            object.__setattr__(
                self,
                "timing",
                FixedTiming(start=self.window.start, end=self.window.end),
            )
        if self.window is None and isinstance(self.timing, FixedTiming) and self.timing.end is not None:
            object.__setattr__(
                self,
                "window",
                DailyTimeWindow(name=self.name, start=self.timing.start, end=self.timing.end),
            )

    def is_active(self, now: datetime) -> bool:
        return bool(self.enabled and self.window is not None and self.window.contains(now))


@dataclass(frozen=True)
class ScheduleProfile:
    name: str
    schedules: tuple[PumpTimerSchedule, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("schedule profile name cannot be empty")
        names = [schedule.name for schedule in self.schedules]
        if len(names) != len(set(names)):
            raise ValueError(f"schedule names must be unique in profile {self.name}")


@dataclass(frozen=True)
class PumpTimerConfig:
    """Named pump schedule profiles and their canonical site configuration."""

    schedules: tuple[PumpTimerSchedule, ...] = ()
    timezone: str = "UTC"
    profiles: tuple[ScheduleProfile, ...] = ()
    active_profile: str = "normal"
    site: SiteConfig | None = None

    def __post_init__(self) -> None:
        site = self.site or SiteConfig(timezone=self.timezone)
        profiles = self.profiles or (
            ScheduleProfile(name=self.active_profile, schedules=self.schedules),
        )
        profile_names = [profile.name for profile in profiles]
        if len(profile_names) != len(set(profile_names)):
            raise ValueError("schedule profile names must be unique")
        active = next(
            (profile for profile in profiles if profile.name == self.active_profile),
            None,
        )
        if active is None:
            raise ValueError(f"active schedule profile does not exist: {self.active_profile}")
        if any(
            schedule.enabled and not isinstance(schedule.timing, FixedTiming)
            for profile in profiles
            for schedule in profile.schedules
        ) and not site.has_location:
            raise ValueError(
                "site.latitude and site.longitude are required for enabled solar schedules"
            )
        object.__setattr__(self, "site", site)
        object.__setattr__(self, "timezone", site.timezone)
        object.__setattr__(self, "profiles", profiles)
        object.__setattr__(self, "schedules", active.schedules)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> PumpTimerConfig:
        timer_data = _mapping_value(data, "pump_timer", default={})
        site = SiteConfig.from_mapping(data)
        profiles_data = timer_data.get("profiles")
        active_profile = _string_with_default(timer_data, "active_profile", "normal")

        if profiles_data is None:
            schedules_data = timer_data.get("schedules", [])
            if not isinstance(schedules_data, list):
                raise ValueError("pump_timer.schedules must be a list")
            schedules = tuple(_schedule_from_mapping(item) for item in schedules_data)
            return cls(
                schedules=schedules,
                timezone=site.timezone,
                active_profile="normal",
                site=site,
            )

        if not isinstance(profiles_data, list):
            raise ValueError("pump_timer.profiles must be a list")
        profiles = tuple(_profile_from_mapping(item) for item in profiles_data)
        return cls(
            timezone=site.timezone,
            profiles=profiles,
            active_profile=active_profile,
            site=site,
        )

    def profile(self, name: str | None = None) -> ScheduleProfile:
        selected = self.active_profile if name is None else name
        for profile in self.profiles:
            if profile.name == selected:
                return profile
        raise ValueError(f"schedule profile does not exist: {selected}")

    def with_active_profile(self, name: str) -> PumpTimerConfig:
        self.profile(name)
        return replace(self, active_profile=name)


@dataclass(frozen=True)
class PumpTimerOverride:
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
class ResolvedScheduleWindow:
    source_date: date
    profile_name: str
    event_name: str
    start: datetime
    end: datetime
    pump_speed: ActuatorState
    booster_state: ActuatorState
    allow_dosing: bool

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("resolved schedule datetimes must be timezone-aware")
        if _as_utc(self.end) <= _as_utc(self.start):
            raise ValueError("resolved schedule end must be after start")

    @property
    def duration_seconds(self) -> float:
        return (_as_utc(self.end) - _as_utc(self.start)).total_seconds()

    def contains(self, when: datetime) -> bool:
        instant = _as_utc(when)
        return _as_utc(self.start) <= instant < _as_utc(self.end)

    def overlaps(self, start: datetime, end: datetime) -> bool:
        return _as_utc(self.start) < _as_utc(end) and _as_utc(self.end) > _as_utc(start)

    def as_payload(self) -> dict[str, Any]:
        return {
            "source_date": self.source_date.isoformat(),
            "profile": self.profile_name,
            "name": self.event_name,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "duration_minutes": self.duration_seconds / 60.0,
            "pump_speed": self.pump_speed.value,
            "booster": self.booster_state.value,
            "allow_dosing": self.allow_dosing,
        }


@dataclass(frozen=True)
class ResolvedScheduleDay:
    local_date: date
    timezone: str
    profile_name: str
    latitude: float | None
    longitude: float | None
    location_source: str
    sunrise: datetime | None
    sunset: datetime | None
    windows: tuple[ResolvedScheduleWindow, ...]
    warnings: tuple[str, ...] = ()

    @property
    def daylight_seconds(self) -> float | None:
        if self.sunrise is None or self.sunset is None:
            return None
        return (_as_utc(self.sunset) - _as_utc(self.sunrise)).total_seconds()

    def as_payload(self) -> dict[str, Any]:
        return {
            "local_date": self.local_date.isoformat(),
            "timezone": self.timezone,
            "profile": self.profile_name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "location_source": self.location_source,
            "sunrise": self.sunrise.isoformat() if self.sunrise is not None else None,
            "sunset": self.sunset.isoformat() if self.sunset is not None else None,
            "daylight_seconds": self.daylight_seconds,
            "windows": [window.as_payload() for window in self.windows],
            "warnings": list(self.warnings),
        }


class AstronomyProvider(Protocol):
    def sunrise_sunset(self, *, day: date, site: SiteConfig) -> tuple[datetime, datetime]: ...


class AstralAstronomyProvider:
    """Offline sunrise/sunset provider backed by Astral."""

    def sunrise_sunset(self, *, day: date, site: SiteConfig) -> tuple[datetime, datetime]:
        if not site.has_location:
            raise ValueError("site coordinates are unavailable")
        from astral import Observer  # type: ignore[import-untyped]
        from astral.sun import sunrise, sunset  # type: ignore[import-untyped]

        assert site.latitude is not None
        assert site.longitude is not None
        observer = Observer(latitude=site.latitude, longitude=site.longitude)
        zone = ZoneInfo(site.timezone)
        return (
            sunrise(observer, date=day, tzinfo=zone),
            sunset(observer, date=day, tzinfo=zone),
        )


class ScheduleResolver:
    def __init__(self, astronomy: AstronomyProvider | None = None) -> None:
        self._astronomy = astronomy or AstralAstronomyProvider()

    def resolve_day(self, config: PumpTimerConfig, day: date) -> ResolvedScheduleDay:
        site = config.site
        assert site is not None
        zone = ZoneInfo(site.timezone)
        day_start = datetime(day.year, day.month, day.day, tzinfo=zone)
        tomorrow = day + timedelta(days=1)
        day_end = datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=zone)
        solar_cache: dict[date, tuple[datetime, datetime] | Exception] = {}
        warnings: list[str] = []

        def solar_times(source_day: date) -> tuple[datetime, datetime]:
            cached = solar_cache.get(source_day)
            if isinstance(cached, Exception):
                raise cached
            if cached is not None:
                return cached
            try:
                calculated = self._astronomy.sunrise_sunset(day=source_day, site=site)
            except Exception as error:
                solar_cache[source_day] = error
                raise
            solar_cache[source_day] = calculated
            return calculated

        sunrise_value: datetime | None = None
        sunset_value: datetime | None = None
        if site.has_location:
            try:
                sunrise_value, sunset_value = solar_times(day)
            except Exception as error:
                warnings.append(f"astronomy unavailable for {day.isoformat()}: {error}")

        windows: list[ResolvedScheduleWindow] = []
        profile = config.profile()
        for source_offset in range(-2, 3):
            source_day = day + timedelta(days=source_offset)
            for event in profile.schedules:
                if not event.enabled:
                    continue
                try:
                    window = self._resolve_event(
                        event,
                        source_day=source_day,
                        profile_name=profile.name,
                        zone=zone,
                        solar_times=solar_times,
                    )
                except Exception as error:
                    warning = (
                        f"{profile.name}/{event.name} unavailable for "
                        f"{source_day.isoformat()}: {error}"
                    )
                    if warning not in warnings:
                        warnings.append(warning)
                    continue
                if window.overlaps(day_start, day_end):
                    windows.append(window)

        windows.sort(key=lambda item: (_as_utc(item.start), _as_utc(item.end), item.event_name))
        return ResolvedScheduleDay(
            local_date=day,
            timezone=site.timezone,
            profile_name=profile.name,
            latitude=site.latitude,
            longitude=site.longitude,
            location_source=site.location_source,
            sunrise=sunrise_value,
            sunset=sunset_value,
            windows=tuple(windows),
            warnings=tuple(warnings),
        )

    def _resolve_event(
        self,
        event: PumpTimerSchedule,
        *,
        source_day: date,
        profile_name: str,
        zone: ZoneInfo,
        solar_times: Callable[[date], tuple[datetime, datetime]],
    ) -> ResolvedScheduleWindow:
        timing = event.timing
        assert timing is not None
        if isinstance(timing, FixedTiming):
            start = _localize_fixed(source_day, timing.start, zone)
            if timing.duration_minutes is not None:
                end = (
                    _as_utc(start) + timedelta(minutes=timing.duration_minutes)
                ).astimezone(zone)
            else:
                assert timing.end is not None
                end_day = source_day
                if timing.end <= timing.start:
                    end_day += timedelta(days=1)
                end = _localize_fixed(end_day, timing.end, zone)
        else:
            sunrise_value, sunset_value = solar_times(source_day)
            sunrise_utc = _as_utc(sunrise_value)
            sunset_utc = _as_utc(sunset_value)
            daylight = sunset_utc - sunrise_utc
            if daylight.total_seconds() <= 0:
                raise ValueError("sunset must be after sunrise")
            if isinstance(timing, DaylightFractionTiming):
                start = (sunrise_utc + daylight * timing.start_fraction).astimezone(zone)
                end = (sunrise_utc + daylight * timing.end_fraction).astimezone(zone)
            else:
                anchor = (
                    sunrise_utc
                    if timing.anchor == "sunrise"
                    else sunset_utc
                    if timing.anchor == "sunset"
                    else sunrise_utc + daylight / 2
                )
                start_utc = anchor + timedelta(minutes=timing.offset_minutes)
                start = start_utc.astimezone(zone)
                end = (
                    start_utc + timedelta(minutes=timing.duration_minutes)
                ).astimezone(zone)

        return ResolvedScheduleWindow(
            source_date=source_day,
            profile_name=profile_name,
            event_name=event.name,
            start=start,
            end=end,
            pump_speed=event.pump_speed,
            booster_state=event.booster_state,
            allow_dosing=event.allow_dosing,
        )


class ScheduleService:
    """Caches resolved days shared by pump control, dosing, and preview."""

    def __init__(
        self,
        config: PumpTimerConfig,
        *,
        resolver: ScheduleResolver | None = None,
    ) -> None:
        self.config = config
        self._resolver = resolver or ScheduleResolver()
        self._days: dict[date, ResolvedScheduleDay] = {}
        self.config_digest = hashlib.sha256(repr(config).encode("utf-8")).hexdigest()

    def prime(self, now: datetime, *, horizon_days: int = 7) -> None:
        local_day = now.astimezone(ZoneInfo(self.config.timezone)).date()
        for offset in range(-1, horizon_days + 1):
            self.day(local_day + timedelta(days=offset))

    def refresh_horizon(self, now: datetime, *, horizon_days: int = 7) -> None:
        self.prime(now, horizon_days=horizon_days)
        local_day = now.astimezone(ZoneInfo(self.config.timezone)).date()
        oldest = local_day - timedelta(days=2)
        newest = local_day + timedelta(days=horizon_days + 1)
        self._days = {
            key: value
            for key, value in self._days.items()
            if oldest <= key <= newest
        }

    def day(self, day: date) -> ResolvedScheduleDay:
        resolved = self._days.get(day)
        if resolved is None:
            resolved = self._resolver.resolve_day(self.config, day)
            self._days[day] = resolved
        return resolved

    def active_windows(self, now: datetime) -> tuple[ResolvedScheduleWindow, ...]:
        local_now = now.astimezone(ZoneInfo(self.config.timezone))
        return tuple(
            window
            for window in self.day(local_now.date()).windows
            if window.contains(now)
        )

    def preview(self, start_day: date, *, days: int = 3) -> tuple[ResolvedScheduleDay, ...]:
        if days < 1 or days > 31:
            raise ValueError("preview days must be between 1 and 31")
        return tuple(self.day(start_day + timedelta(days=offset)) for offset in range(days))

    def next_transition_after(self, now: datetime) -> datetime | None:
        zone = ZoneInfo(self.config.timezone)
        local_day = now.astimezone(zone).date()
        current = _desired_states(self.active_windows(now))
        candidates: list[datetime] = []
        for offset in range(4):
            for window in self.day(local_day + timedelta(days=offset)).windows:
                candidates.extend((window.start, window.end))
        unique = sorted(
            {_as_utc(value) for value in candidates if _as_utc(value) > _as_utc(now)}
        )
        for candidate_utc in unique:
            candidate_local = candidate_utc.astimezone(zone)
            if _desired_states(self.active_windows(candidate_local)) == current:
                continue
            if now.tzinfo is None:
                return candidate_utc.replace(tzinfo=None)
            return candidate_utc.astimezone(now.tzinfo)
        return None


@dataclass(frozen=True)
class PumpTimerEvaluation:
    active_schedule_names: tuple[str, ...]
    desired_states: Mapping[ActuatorId, ActuatorState]
    commands: tuple[ActuatorCommand, ...]


class PumpTimer:
    """Generates simple actuator commands from a shared resolved schedule."""

    def __init__(
        self,
        config: PumpTimerConfig,
        *,
        schedule_service: ScheduleService | None = None,
    ) -> None:
        self._config = config
        self._service = schedule_service or ScheduleService(config)

    @property
    def service(self) -> ScheduleService:
        return self._service

    def prime(self, now: datetime) -> None:
        self._service.prime(now)

    def refresh_horizon(self, now: datetime) -> None:
        self._service.refresh_horizon(now)

    def evaluate(
        self,
        *,
        now: datetime,
        actuator_states: Mapping[ActuatorId, ActuatorState],
        override: PumpTimerOverride | None = None,
    ) -> PumpTimerEvaluation:
        if override is not None:
            active_windows: tuple[ResolvedScheduleWindow, ...] = ()
            desired_states = _desired_states_for_override(override)
            reason_override = override.reason
        else:
            active_windows = self._service.active_windows(now)
            desired_states = _desired_states(active_windows)
            reason_override = None
        active_names = tuple(dict.fromkeys(window.event_name for window in active_windows))
        return PumpTimerEvaluation(
            active_schedule_names=active_names,
            desired_states=desired_states,
            commands=tuple(
                self._commands_for_desired_states(
                    now=now,
                    desired_states=desired_states,
                    actuator_states=actuator_states,
                    active_schedule_names=active_names,
                    reason_override=reason_override,
                )
            ),
        )

    def next_transition_after(self, now: datetime) -> datetime | None:
        return self._service.next_transition_after(now)

    def _commands_for_desired_states(
        self,
        *,
        now: datetime,
        desired_states: Mapping[ActuatorId, ActuatorState],
        actuator_states: Mapping[ActuatorId, ActuatorState],
        active_schedule_names: tuple[str, ...],
        reason_override: str | None,
    ) -> list[ActuatorCommand]:
        commands: list[ActuatorCommand] = []
        for actuator_id in _command_order(desired_states):
            desired_state = desired_states[actuator_id]
            if actuator_states.get(actuator_id) == desired_state:
                continue
            commands.append(
                ActuatorCommand(
                    actuator_id=actuator_id,
                    created_at=now,
                    state=desired_state,
                    requested_by=CommandSource.TIMER,
                    reason=_reason(
                        active_schedule_names,
                        actuator_id,
                        desired_state,
                        reason_override=reason_override,
                    ),
                    metadata={
                        "timer_active_profile": self._config.active_profile,
                        "timer_active_schedules": list(active_schedule_names),
                        "timer_override": reason_override,
                    },
                )
            )
        return commands


def load_pump_timer_config(path: str | Path) -> PumpTimerConfig:
    with Path(path).open("r", encoding="utf-8") as config_file:
        data = yaml.safe_load(config_file) or {}
    if not isinstance(data, Mapping):
        raise ValueError("pump timer config file must contain a mapping")
    return PumpTimerConfig.from_mapping(data)


def schedule_timing_payload(timing: ScheduleTiming) -> dict[str, Any]:
    if isinstance(timing, FixedTiming):
        payload: dict[str, Any] = {"type": "fixed", "start": _format_time(timing.start)}
        if timing.end is not None:
            payload["end"] = _format_time(timing.end)
        else:
            payload["duration_minutes"] = timing.duration_minutes
        return payload
    if isinstance(timing, SolarAnchorTiming):
        return {
            "type": "solar_anchor",
            "anchor": timing.anchor,
            "offset_minutes": timing.offset_minutes,
            "duration_minutes": timing.duration_minutes,
        }
    return {
        "type": "daylight_fraction",
        "start_fraction": timing.start_fraction,
        "end_fraction": timing.end_fraction,
    }


def _profile_from_mapping(data: object) -> ScheduleProfile:
    if not isinstance(data, Mapping):
        raise ValueError("pump timer profile must be a mapping")
    name = _string_value(data, "name")
    schedules_data = data.get("schedules", [])
    if not isinstance(schedules_data, list):
        raise ValueError("profile schedules must be a list")
    return ScheduleProfile(
        name=name,
        schedules=tuple(_schedule_from_mapping(item) for item in schedules_data),
    )


def _schedule_from_mapping(data: object) -> PumpTimerSchedule:
    if not isinstance(data, Mapping):
        raise ValueError("pump timer schedule must be a mapping")
    name = _string_value(data, "name")
    raw_timing = data.get("timing")
    if raw_timing is None:
        timing: ScheduleTiming = FixedTiming(
            start=TimeOfDay.parse(_string_value(data, "start")),
            end=TimeOfDay.parse(_string_value(data, "end")),
        )
    else:
        timing = _timing_from_mapping(raw_timing)
    return PumpTimerSchedule(
        name=name,
        timing=timing,
        pump_speed=_pump_speed_value(data.get("pump_speed", ActuatorState.LOW.value)),
        booster_state=_booster_state_value(data.get("booster", ActuatorState.OFF.value)),
        allow_dosing=_bool_value(data.get("allow_dosing", True), "allow_dosing"),
        enabled=_bool_value(data.get("enabled", True), "enabled"),
    )


def _timing_from_mapping(data: object) -> ScheduleTiming:
    if not isinstance(data, Mapping):
        raise ValueError("schedule timing must be a mapping")
    timing_type = _string_value(data, "type")
    if timing_type == "fixed":
        start = TimeOfDay.parse(_string_value(data, "start"))
        has_end = "end" in data
        has_duration = "duration_minutes" in data
        if has_end == has_duration:
            raise ValueError("fixed timing requires exactly one of end or duration_minutes")
        return FixedTiming(
            start=start,
            end=TimeOfDay.parse(_string_value(data, "end")) if has_end else None,
            duration_minutes=(
                _finite_float(data.get("duration_minutes"), "duration_minutes")
                if has_duration
                else None
            ),
        )
    if timing_type == "solar_anchor":
        return SolarAnchorTiming(
            anchor=_string_value(data, "anchor"),
            offset_minutes=_finite_float(data.get("offset_minutes", 0.0), "offset_minutes"),
            duration_minutes=_finite_float(data.get("duration_minutes"), "duration_minutes"),
        )
    if timing_type == "daylight_fraction":
        return DaylightFractionTiming(
            start_fraction=_finite_float(data.get("start_fraction"), "start_fraction"),
            end_fraction=_finite_float(data.get("end_fraction"), "end_fraction"),
        )
    raise ValueError(f"unsupported schedule timing type: {timing_type}")


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


def _finite_float(value: object, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{key} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{key} must be finite")
    return result


def _bool_value(value: object, key: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false")
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


def _desired_states_for_override(override: PumpTimerOverride) -> dict[ActuatorId, ActuatorState]:
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
    active_windows: tuple[ResolvedScheduleWindow, ...],
) -> dict[ActuatorId, ActuatorState]:
    if not active_windows:
        return {
            ActuatorId.BOOSTER_PUMP: ActuatorState.OFF,
            ActuatorId.PUMP_MOTOR: ActuatorState.OFF,
            ActuatorId.PUMP_MOTOR_SPEED: ActuatorState.LOW,
        }
    return {
        ActuatorId.PUMP_MOTOR: ActuatorState.ON,
        ActuatorId.PUMP_MOTOR_SPEED: (
            ActuatorState.HIGH
            if any(window.pump_speed == ActuatorState.HIGH for window in active_windows)
            else ActuatorState.LOW
        ),
        ActuatorId.BOOSTER_PUMP: (
            ActuatorState.ON
            if any(window.booster_state == ActuatorState.ON for window in active_windows)
            else ActuatorState.OFF
        ),
    }


def _command_order(desired_states: Mapping[ActuatorId, ActuatorState]) -> tuple[ActuatorId, ...]:
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
    active_names: tuple[str, ...],
    actuator_id: ActuatorId,
    desired_state: ActuatorState,
    *,
    reason_override: str | None,
) -> str:
    if reason_override is not None:
        return (
            f"pump timer manual override ({reason_override}): "
            f"set {actuator_id.value} {desired_state.value}"
        )
    if not active_names:
        return f"pump timer outside scheduled window: set {actuator_id.value} {desired_state.value}"
    return (
        f"pump timer active schedule {', '.join(active_names)}: "
        f"set {actuator_id.value} {desired_state.value}"
    )


def _localize_fixed(day: date, value: TimeOfDay, zone: ZoneInfo) -> datetime:
    naive = datetime(day.year, day.month, day.day, value.hour, value.minute, value.second)
    candidate = naive
    for _ in range(4 * 60 * 60 + 1):
        valid: list[datetime] = []
        seen_instants: set[datetime] = set()
        for fold in (0, 1):
            aware = candidate.replace(tzinfo=zone, fold=fold)
            instant = _as_utc(aware)
            round_trip = instant.astimezone(zone).replace(tzinfo=None)
            if round_trip == candidate and instant not in seen_instants:
                valid.append(aware)
                seen_instants.add(instant)
        if valid:
            return min(valid, key=_as_utc)
        candidate += timedelta(seconds=1)
    raise ValueError(f"could not resolve local time {naive.isoformat()} in {zone.key}")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc)


def _format_time(value: TimeOfDay) -> str:
    if value.second:
        return f"{value.hour:02d}:{value.minute:02d}:{value.second:02d}"
    return f"{value.hour:02d}:{value.minute:02d}"
