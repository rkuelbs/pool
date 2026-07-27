"""
Tests for shared relay pulse quantization.
"""

from __future__ import annotations

import pytest

from poolctl.services.pulse_timing import (
    relay_flash_ticks,
    quantize_relay_flash_seconds,
)


def test_relay_flash_ticks_use_100ms_quantization() -> None:
    assert relay_flash_ticks(30.04) == 300
    assert relay_flash_ticks(30.06) == 301
    assert quantize_relay_flash_seconds(30.04) == 30.0
    assert quantize_relay_flash_seconds(30.06) == 30.1


def test_relay_flash_ticks_reject_invalid_durations() -> None:
    with pytest.raises(ValueError):
        relay_flash_ticks(0.0)

    with pytest.raises(ValueError):
        relay_flash_ticks(3276.8)
