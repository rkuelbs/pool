"""
Shared schedule parsing helpers.

Small value objects in this module keep time-of-day and weekday handling
consistent across the pump timer, chlorination windows, and web configuration
forms.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, order=True)
class TimeOfDay:
    """
    Wall-clock time without a date.

    The app interprets this against the Clock's current datetime. On the Pi
    that should eventually be local site time; tests and simulations can choose
    whatever timezone their Clock uses.
    """

    hour: int
    minute: int = 0
    second: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.hour <= 23:
            raise ValueError("hour must be between 0 and 23")

        if not 0 <= self.minute <= 59:
            raise ValueError("minute must be between 0 and 59")

        if not 0 <= self.second <= 59:
            raise ValueError("second must be between 0 and 59")

    @classmethod
    def parse(cls, value: str) -> TimeOfDay:
        parts = value.split(":")

        if len(parts) not in (2, 3):
            raise ValueError("time must be HH:MM or HH:MM:SS")

        try:
            hour = int(parts[0])
            minute = int(parts[1])
            second = int(parts[2]) if len(parts) == 3 else 0
        except ValueError as error:
            raise ValueError("time parts must be integers") from error

        return cls(hour=hour, minute=minute, second=second)

    @classmethod
    def from_datetime(cls, value: datetime) -> TimeOfDay:
        return cls(hour=value.hour, minute=value.minute, second=value.second)


@dataclass(frozen=True)
class DailyTimeWindow:
    """
    Daily schedule window.

    Windows can cross midnight. If start and end are equal, the window is
    treated as all day.
    """

    name: str
    start: TimeOfDay
    end: TimeOfDay

    def contains(self, when: datetime) -> bool:
        current = TimeOfDay.from_datetime(when)

        if self.start == self.end:
            return True

        if self.start < self.end:
            return self.start <= current < self.end

        return current >= self.start or current < self.end
