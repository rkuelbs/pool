"""
Tests for real and simulated clock abstractions.

Clock behavior is important because simulations, schedules, and controller
timing should not depend directly on wall-clock calls.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from poolctl.services.clock import AcceleratedClock, SimulatedClock


@pytest.mark.asyncio
async def test_accelerated_clock_advances_faster_than_wall_time() -> None:
    clock = AcceleratedClock(
        start_at=datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc),
        speedup=100.0,
    )

    start = clock.now()
    await clock.sleep(10.0)
    elapsed_s = (clock.now() - start).total_seconds()

    assert elapsed_s >= 10.0


@pytest.mark.asyncio
async def test_simulated_clock_is_manual_and_each_sleep_advances_time() -> None:
    clock = SimulatedClock(
        start_at=datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc),
        speedup=1_000_000.0,
    )

    start = clock.now()
    await asyncio.gather(clock.sleep(10.0), clock.sleep(10.0))

    assert (clock.now() - start).total_seconds() == 20.0
