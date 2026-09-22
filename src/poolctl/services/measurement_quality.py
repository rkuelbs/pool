"""Shared measurement usability checks for derived calculations."""

from __future__ import annotations

import math
from collections.abc import Collection
from datetime import datetime

from poolctl.domain.models import Measurement, Quality


def usable_numeric_measurement_value(
    measurement: Measurement | None,
    *,
    now: datetime,
    max_age_seconds: float,
    acceptable_qualities: Collection[Quality] = (Quality.GOOD,),
) -> float | None:
    """Return a finite, fresh numeric value, or ``None`` when unusable."""
    if measurement is None or measurement.quality not in acceptable_qualities:
        return None
    if max_age_seconds < 0:
        raise ValueError("max_age_seconds must be >= 0")
    age_s = max(0.0, (now - measurement.observed_at).total_seconds())
    if age_s > max_age_seconds:
        return None
    if not isinstance(measurement.value, int | float):
        return None
    value = float(measurement.value)
    if not math.isfinite(value):
        return None
    return value
