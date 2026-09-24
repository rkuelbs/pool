from __future__ import annotations

import math

import pytest

from poolctl.config import MonitoringLimit
from poolctl.domain.models import Measurement, Quality, SensorId
from poolctl.services.monitoring import StatusLevel, classify_measurement, classify_value


@pytest.fixture
def two_sided_limits() -> MonitoringLimit:
    return MonitoringLimit(
        alarm_below=6.8,
        caution_below=7.2,
        caution_above=7.8,
        alarm_above=8.2,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (6.8, StatusLevel.ALARM),
        (6.9, StatusLevel.CAUTION),
        (7.2, StatusLevel.CAUTION),
        (7.21, StatusLevel.NORMAL),
        (7.79, StatusLevel.NORMAL),
        (7.8, StatusLevel.CAUTION),
        (8.1, StatusLevel.CAUTION),
        (8.2, StatusLevel.ALARM),
    ],
)
def test_two_sided_limits_have_inclusive_boundaries(
    two_sided_limits: MonitoringLimit,
    value: float,
    expected: StatusLevel,
) -> None:
    assert classify_value(value, two_sided_limits).level is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (9.9, StatusLevel.NORMAL),
        (10.0, StatusLevel.CAUTION),
        (14.9, StatusLevel.CAUTION),
        (15.0, StatusLevel.ALARM),
    ],
)
def test_one_sided_high_limits(value: float, expected: StatusLevel) -> None:
    limits = MonitoringLimit(caution_above=10.0, alarm_above=15.0)
    assert classify_value(value, limits).level is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (8.0, StatusLevel.NORMAL),
        (7.0, StatusLevel.CAUTION),
        (3.0, StatusLevel.ALARM),
    ],
)
def test_one_sided_low_limits(value: float, expected: StatusLevel) -> None:
    limits = MonitoringLimit(alarm_below=3.0, caution_below=7.0)
    assert classify_value(value, limits).level is expected


def test_missing_nonfinite_and_bad_measurements_are_not_normal(
    two_sided_limits: MonitoringLimit,
) -> None:
    assert classify_value(None, two_sided_limits).level is StatusLevel.UNKNOWN
    assert classify_value(math.nan, two_sided_limits).level is StatusLevel.INVALID
    measurement = Measurement(
        sensor_id=SensorId.RAW_PH,
        value=7.5,
        unit="pH",
        quality=Quality.BAD,
    )
    assert classify_measurement(measurement, two_sided_limits).level is StatusLevel.INVALID
    assert classify_measurement(None, two_sided_limits).level is StatusLevel.UNKNOWN


def test_monitoring_limit_rejects_misordered_boundaries() -> None:
    with pytest.raises(ValueError, match="must satisfy"):
        MonitoringLimit(
            alarm_below=7.0,
            caution_below=6.9,
            caution_above=7.8,
            alarm_above=8.2,
        )
