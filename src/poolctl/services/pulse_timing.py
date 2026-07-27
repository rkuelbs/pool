"""
Shared actuator pulse timing helpers.

The Waveshare relay module's timed flash command uses 100 ms increments. These
helpers keep controller metadata, relay commands, and delivery accounting aligned
to that same granularity.
"""

from __future__ import annotations


FLASH_PULSE_GRANULARITY_S = 0.1
FLASH_PULSE_MAX_TICKS = 0x7FFF
FLASH_PULSE_MAX_SECONDS = FLASH_PULSE_MAX_TICKS * FLASH_PULSE_GRANULARITY_S


def relay_flash_ticks(duration_s: float) -> int:
    """
    Convert seconds to the Waveshare relay module's 100 ms tick count.
    """
    if duration_s <= 0:
        raise ValueError("flash relay duration must be greater than zero")

    ticks = max(1, int(round(duration_s / FLASH_PULSE_GRANULARITY_S)))
    if ticks > FLASH_PULSE_MAX_TICKS:
        raise ValueError(
            f"flash relay duration cannot exceed {FLASH_PULSE_MAX_SECONDS:.1f} seconds"
        )

    return ticks


def quantize_relay_flash_seconds(duration_s: float) -> float:
    """
    Return the actual module-timed pulse length for a requested duration.
    """
    return round(relay_flash_ticks(duration_s) * FLASH_PULSE_GRANULARITY_S, 1)
