"""
Clock abstractions for real time and accelerated simulation time.

Services depend on this small interface instead of calling datetime.now()
directly. That makes controller behavior deterministic in tests and allows the
simulator to run faster than wall-clock time.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Protocol


class Clock(Protocol):
    """
    Clock interface used by services that care about time.

    Production code can use RealClock.
    Deterministic tests can use SimulatedClock; shared live simulations should
    use AcceleratedClock.
    """

    def now(self) -> datetime:
        """
        Return the current application time.
        """
        ...

    async def sleep(self, seconds: float) -> None:
        """
        Sleep according to this clock's time behavior.
        """
        ...


class RealClock:
    """
    Normal wall-clock time.

    Use this on the actual Raspberry Pi when controlling the real pool.
    """

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class SimulatedClock:
    """
    Manual deterministic clock for tests.

    `sleep()` advances this clock by the requested simulated duration after an
    optional scaled real delay. Concurrent sleepers each advance the shared
    manual time, so this class is not intended as the clock for a live runtime
    with multiple independently sleeping tasks. Use AcceleratedClock for that
    case.

    Example:
        speedup = 3600.0 means sleep(3600) waits about one real second before
        advancing the manual clock by one simulated hour.

    Tests can call advance() to move time instantly without waiting.
    """

    def __init__(
        self,
        *,
        start_at: datetime,
        speedup: float = 1.0,
    ) -> None:
        if start_at.tzinfo is None:
            raise ValueError("start_at must be timezone-aware")

        if speedup <= 0:
            raise ValueError("speedup must be greater than zero")

        self._current_time = start_at
        self._speedup = speedup
        self._lock = asyncio.Lock()

    def now(self) -> datetime:
        return self._current_time

    async def sleep(self, seconds: float) -> None:
        """
        Advance simulated time while only waiting the scaled real-time amount.

        For example:
            speedup = 3600
            sleep(3600 simulated seconds) waits 1 real second.
        """
        if seconds < 0:
            raise ValueError("sleep seconds cannot be negative")

        real_sleep_s = seconds / self._speedup

        if real_sleep_s > 0:
            await asyncio.sleep(real_sleep_s)

        async with self._lock:
            self._current_time += timedelta(seconds=seconds)

    async def advance(self, seconds: float) -> None:
        """
        Advance simulated time instantly, without waiting.

        This is useful for unit tests where you want deterministic behavior
        without even a short real-time delay.
        """
        if seconds < 0:
            raise ValueError("advance seconds cannot be negative")

        async with self._lock:
            self._current_time += timedelta(seconds=seconds)


class AcceleratedClock:
    """
    Wall-clock-backed accelerated clock for live simulations.

    Unlike SimulatedClock, time advances continuously as real time passes. This
    is useful for a browser dashboard where polling should show simulated pool
    behavior progressing without a separate scheduler calling advance().
    """

    def __init__(
        self,
        *,
        start_at: datetime,
        speedup: float = 1.0,
    ) -> None:
        if start_at.tzinfo is None:
            raise ValueError("start_at must be timezone-aware")

        if speedup <= 0:
            raise ValueError("speedup must be greater than zero")

        self._start_at = start_at
        self._speedup = speedup
        self._real_start_s = time.monotonic()

    def now(self) -> datetime:
        real_elapsed_s = time.monotonic() - self._real_start_s
        return self._start_at + timedelta(seconds=real_elapsed_s * self._speedup)

    async def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("sleep seconds cannot be negative")

        await asyncio.sleep(seconds / self._speedup)
