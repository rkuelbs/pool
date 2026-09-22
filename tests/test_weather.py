"""
Tests for Open-Meteo weather download and parsing.

Weather observations are logged, while forecast rows are cached in memory for
future predictive chemistry work.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from poolctl.services.weather import WEATHER_FIELDS, WeatherConfig, WeatherObservation, WeatherService


def _sample_payload() -> dict[str, Any]:
    times = [
        "2026-05-22T10:00",
        "2026-05-22T11:00",
        "2026-05-22T12:00",
        "2026-05-22T13:00",
        "2026-05-22T14:00",
    ]
    hourly = {"time": times}
    units = {"time": "iso8601"}
    for index, field in enumerate(WEATHER_FIELDS):
        hourly[field] = [float(index + step) for step in range(len(times))]
        units[field] = "°F" if "temperature" in field else "mm"
    units["uv_index"] = "index"
    units["weather_code"] = "wmo code"
    units["cloud_cover"] = "%"
    return {
        "hourly": hourly,
        "hourly_units": units,
    }


def test_weather_config_requires_lat_lon_when_enabled() -> None:
    with pytest.raises(ValueError):
        WeatherConfig.from_mapping({"weather": {"enabled": True}})


def test_weather_config_uses_canonical_site_coordinates() -> None:
    config = WeatherConfig.from_mapping(
        {
            "site": {
                "timezone": "America/Chicago",
                "latitude": 29.75,
                "longitude": -95.35,
            },
            "weather": {"enabled": True},
        }
    )

    assert config.latitude == 29.75
    assert config.longitude == -95.35


def test_weather_service_polls_and_updates_forecast_and_observation() -> None:
    config = WeatherConfig.from_mapping(
        {
            "weather": {
                "enabled": True,
                "latitude": 29.75,
                "longitude": -95.35,
                "forecast_hours": 48,
                "past_hours": 2,
            }
        }
    )
    payload = _sample_payload()

    def fetch_json(_url: str, _timeout_s: float) -> dict[str, Any]:
        return payload

    logged: list[WeatherObservation] = []

    service = WeatherService(config, fetch_json=fetch_json)
    now = datetime(2026, 5, 22, 12, 30, tzinfo=timezone.utc)
    result = service.poll_due(now=now, log_observation=lambda obs: logged.append(obs) or 1)

    assert result.attempted is True
    assert result.updated is True
    assert result.logged_count == 1
    assert result.error is None
    assert len(logged) == 1
    assert logged[0].observed_at == datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)

    assert service.latest_observation is not None
    assert service.latest_forecast is not None
    assert service.latest_forecast.times[0] == datetime(2026, 5, 22, 13, 0, tzinfo=timezone.utc)
    assert service.latest_unit("temperature_2m") == "degF"
