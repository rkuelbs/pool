"""
Tests for Calcium Saturation Index calculation.

CSI depends on valid live pH/temperature and latest entered chemistry tests, so
these tests cover ready and not-ready calculation paths.
"""

from __future__ import annotations

from datetime import datetime, timezone

from poolctl.domain.models import Measurement, Quality, SensorId
from poolctl.services.saturation_index import (
    CalciumSaturationIndexConfig,
    estimate_calcium_saturation_index,
)


def _measurement(sensor_id: SensorId, value: float, unit: str, quality: Quality = Quality.GOOD) -> Measurement:
    return Measurement(
        sensor_id=sensor_id,
        observed_at=datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc),
        value=value,
        unit=unit,
        quality=quality,
    )


def test_estimate_calcium_saturation_index_returns_none_without_required_inputs() -> None:
    estimate = estimate_calcium_saturation_index(
        measurement_by_sensor={
            SensorId.WATER_TEMP: _measurement(SensorId.WATER_TEMP, 84.0, "degF"),
        },
        lab_values={"alkalinity": 100.0, "calcium_hardness": 300.0, "tds": 1000.0},
    )
    assert estimate is None


def test_estimate_calcium_saturation_index_requires_good_quality_live_measurements() -> None:
    estimate = estimate_calcium_saturation_index(
        measurement_by_sensor={
            SensorId.WATER_TEMP: _measurement(
                SensorId.WATER_TEMP, 84.0, "degF", quality=Quality.SUSPECT
            ),
            SensorId.RAW_PH: _measurement(SensorId.RAW_PH, 7.5, "pH"),
        },
        lab_values={"alkalinity": 100.0, "calcium_hardness": 300.0, "tds": 1000.0},
    )
    assert estimate is None


def test_estimate_calcium_saturation_index_matches_revised_equation_example() -> None:
    estimate = estimate_calcium_saturation_index(
        measurement_by_sensor={
            SensorId.WATER_TEMP: _measurement(SensorId.WATER_TEMP, 84.0, "degF"),
            SensorId.RAW_PH: _measurement(SensorId.RAW_PH, 7.5, "pH"),
        },
        lab_values={"alkalinity": 100.0, "calcium_hardness": 300.0, "tds": 1000.0},
        config=CalciumSaturationIndexConfig(),
    )
    assert estimate is not None
    assert abs(estimate.tc - 0.443) < 0.001
    assert abs(estimate.constant_c + 12.299) < 0.001
    assert abs(estimate.value - 0.1211) < 0.02
