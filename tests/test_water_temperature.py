"""Tests for canonical PH-temperature to ORP-temperature selection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from poolctl.domain.models import Measurement, Quality, SensorId
from poolctl.services.water_temperature import WaterTemperatureConfig, select_water_temperature


NOW = datetime(2026, 5, 21, 12, tzinfo=timezone.utc)


def _temperature(
    sensor_id: SensorId,
    value: float,
    *,
    age_seconds: float = 0.0,
    quality: Quality = Quality.GOOD,
) -> Measurement:
    return Measurement(
        sensor_id=sensor_id,
        observed_at=NOW - timedelta(seconds=age_seconds),
        value=value,
        unit="degF",
        quality=quality,
    )


def test_canonical_water_temperature_prefers_fresh_ph_temperature() -> None:
    selection = select_water_temperature(
        {
            SensorId.PH_TEMP: _temperature(SensorId.PH_TEMP, 82.0),
            SensorId.ORP_TEMP: _temperature(SensorId.ORP_TEMP, 81.0),
        },
        now=NOW,
    )

    assert selection.active_source == SensorId.PH_TEMP
    assert selection.active_value == 82.0
    assert selection.using_fallback is False
    canonical = selection.canonical_measurement()
    assert canonical is not None
    assert canonical.sensor_id == SensorId.WATER_TEMP
    assert canonical.metadata["active_source"] == SensorId.PH_TEMP.value


def test_canonical_water_temperature_falls_back_and_returns_to_ph() -> None:
    config = WaterTemperatureConfig(max_age_seconds=60.0)
    fallback = select_water_temperature(
        {
            SensorId.PH_TEMP: _temperature(SensorId.PH_TEMP, 80.0, age_seconds=61),
            SensorId.ORP_TEMP: _temperature(SensorId.ORP_TEMP, 81.0),
        },
        now=NOW,
        config=config,
    )
    recovered = select_water_temperature(
        {
            SensorId.PH_TEMP: _temperature(SensorId.PH_TEMP, 82.0),
            SensorId.ORP_TEMP: _temperature(SensorId.ORP_TEMP, 81.0),
        },
        now=NOW,
        config=config,
    )

    assert fallback.active_source == SensorId.ORP_TEMP
    assert fallback.using_fallback is True
    assert fallback.primary.reason == "stale"
    assert fallback.primary.age_seconds == 61.0
    assert recovered.active_source == SensorId.PH_TEMP


def test_canonical_water_temperature_is_unavailable_when_both_sources_are_stale() -> None:
    selection = select_water_temperature(
        {
            SensorId.PH_TEMP: _temperature(SensorId.PH_TEMP, 80.0, age_seconds=61),
            SensorId.ORP_TEMP: _temperature(SensorId.ORP_TEMP, 81.0, age_seconds=62),
        },
        now=NOW,
        config=WaterTemperatureConfig(max_age_seconds=60.0),
    )

    assert selection.available is False
    assert selection.canonical_measurement() is None
    assert selection.primary.reason == "stale"
    assert selection.fallback.reason == "stale"
