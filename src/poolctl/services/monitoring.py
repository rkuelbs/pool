"""Shared measurement status classification for dashboards and alerts."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from poolctl.config import MonitoringLimit
from poolctl.domain.models import Measurement, Quality


class StatusLevel(str, Enum):
    NORMAL = "normal"
    CAUTION = "caution"
    ALARM = "alarm"
    INVALID = "invalid"
    UNKNOWN = "unknown"


class BoundaryDirection(str, Enum):
    BELOW = "below"
    ABOVE = "above"


@dataclass(frozen=True)
class StatusEvaluation:
    level: StatusLevel
    direction: BoundaryDirection | None = None
    threshold: float | None = None


def classify_value(
    value: float | int | None,
    limits: MonitoringLimit | None,
    *,
    valid: bool = True,
) -> StatusEvaluation:
    """Classify one value with inclusive caution and alarm boundaries."""
    if value is None or limits is None:
        return StatusEvaluation(StatusLevel.UNKNOWN)
    numeric_value = float(value)
    if not valid or not math.isfinite(numeric_value):
        return StatusEvaluation(StatusLevel.INVALID)

    if limits.alarm_below is not None and numeric_value <= limits.alarm_below:
        return StatusEvaluation(
            StatusLevel.ALARM,
            BoundaryDirection.BELOW,
            limits.alarm_below,
        )
    if limits.alarm_above is not None and numeric_value >= limits.alarm_above:
        return StatusEvaluation(
            StatusLevel.ALARM,
            BoundaryDirection.ABOVE,
            limits.alarm_above,
        )
    if limits.caution_below is not None and numeric_value <= limits.caution_below:
        return StatusEvaluation(
            StatusLevel.CAUTION,
            BoundaryDirection.BELOW,
            limits.caution_below,
        )
    if limits.caution_above is not None and numeric_value >= limits.caution_above:
        return StatusEvaluation(
            StatusLevel.CAUTION,
            BoundaryDirection.ABOVE,
            limits.caution_above,
        )
    return StatusEvaluation(StatusLevel.NORMAL)


def classify_measurement(
    measurement: Measurement | None,
    limits: MonitoringLimit | None,
) -> StatusEvaluation:
    if measurement is None:
        return StatusEvaluation(StatusLevel.UNKNOWN)
    try:
        value = float(measurement.value)
    except (TypeError, ValueError):
        return StatusEvaluation(StatusLevel.INVALID)
    return classify_value(
        value,
        limits,
        valid=measurement.quality == Quality.GOOD,
    )
