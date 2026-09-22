"""
Open-Meteo weather download and forecast cache.

Observed hourly weather is logged to SQLite for history charts. Forecast data is
kept in memory and refreshed periodically so future chemistry prediction logic
can use it without treating forecasts as historical measurements.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from poolctl.config import SiteConfig


WEATHER_FIELDS: tuple[str, ...] = (
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "apparent_temperature",
    "precipitation",
    "rain",
    "showers",
    "weather_code",
    "cloud_cover",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
    "uv_index",
    "surface_pressure",
    "et0_fao_evapotranspiration",
    "soil_temperature_0cm",
)


@dataclass(frozen=True)
class WeatherConfig:
    enabled: bool = False
    latitude: float | None = None
    longitude: float | None = None
    poll_interval_s: float = 3600.0
    past_hours: int = 2
    forecast_hours: int = 48
    request_timeout_s: float = 15.0
    endpoint: str = "https://api.open-meteo.com/v1/forecast"
    source: str = "open-meteo"
    temperature_unit: str = "fahrenheit"
    wind_speed_unit: str = "mph"
    precipitation_unit: str = "inch"

    def __post_init__(self) -> None:
        if self.poll_interval_s <= 0:
            raise ValueError("weather.poll_interval_s must be greater than zero")
        if self.request_timeout_s <= 0:
            raise ValueError("weather.request_timeout_s must be greater than zero")
        if self.past_hours < 1:
            raise ValueError("weather.past_hours must be at least 1")
        if self.forecast_hours < 1:
            raise ValueError("weather.forecast_hours must be at least 1")
        if self.enabled and (self.latitude is None or self.longitude is None):
            raise ValueError("weather.latitude and weather.longitude are required when weather is enabled")
        if self.temperature_unit not in {"celsius", "fahrenheit"}:
            raise ValueError("weather.temperature_unit must be celsius or fahrenheit")
        if self.wind_speed_unit not in {"kmh", "ms", "mph", "kn"}:
            raise ValueError("weather.wind_speed_unit must be one of kmh, ms, mph, kn")
        if self.precipitation_unit not in {"mm", "inch"}:
            raise ValueError("weather.precipitation_unit must be mm or inch")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> WeatherConfig:
        raw = data.get("weather", {})
        if not isinstance(raw, Mapping):
            raise ValueError("weather must be a mapping")

        site = SiteConfig.from_mapping(data)

        enabled = _bool(raw, "enabled", cls.enabled)
        latitude = site.latitude
        longitude = site.longitude
        poll_interval_s = _float(raw, "poll_interval_s", cls.poll_interval_s)
        past_hours = _int(raw, "past_hours", cls.past_hours)
        forecast_hours = _int(raw, "forecast_hours", cls.forecast_hours)
        request_timeout_s = _float(raw, "request_timeout_s", cls.request_timeout_s)
        endpoint = _string(raw, "endpoint", cls.endpoint)
        source = _string(raw, "source", cls.source)
        temperature_unit = _string(raw, "temperature_unit", cls.temperature_unit)
        wind_speed_unit = _string(raw, "wind_speed_unit", cls.wind_speed_unit)
        precipitation_unit = _string(raw, "precipitation_unit", cls.precipitation_unit)
        return cls(
            enabled=enabled,
            latitude=latitude,
            longitude=longitude,
            poll_interval_s=poll_interval_s,
            past_hours=past_hours,
            forecast_hours=forecast_hours,
            request_timeout_s=request_timeout_s,
            endpoint=endpoint,
            source=source,
            temperature_unit=temperature_unit,
            wind_speed_unit=wind_speed_unit,
            precipitation_unit=precipitation_unit,
        )


@dataclass(frozen=True)
class WeatherObservation:
    observed_at: datetime
    source: str
    latitude: float
    longitude: float
    values: dict[str, float | None]
    units_by_field: dict[str, str]


@dataclass(frozen=True)
class WeatherForecastSnapshot:
    generated_at: datetime
    source: str
    latitude: float
    longitude: float
    times: tuple[datetime, ...]
    values_by_field: dict[str, tuple[float | None, ...]]
    units_by_field: dict[str, str]


@dataclass(frozen=True)
class WeatherPollResult:
    attempted: bool = False
    updated: bool = False
    logged_count: int = 0
    error: str | None = None
    observed_at: datetime | None = None


@dataclass(frozen=True)
class _WeatherFetchResult:
    observation: WeatherObservation
    forecast: WeatherForecastSnapshot


class WeatherService:
    def __init__(
        self,
        config: WeatherConfig,
        *,
        fetch_json: Callable[[str, float], Mapping[str, Any]] | None = None,
    ) -> None:
        self.config = config
        self._fetch_json = fetch_json or _default_fetch_json
        self._next_poll_at: datetime | None = None
        self._latest_observation: WeatherObservation | None = None
        self._latest_forecast: WeatherForecastSnapshot | None = None
        self._last_error: str | None = None
        self._last_poll_attempt_at: datetime | None = None
        self._last_success_at: datetime | None = None

    @property
    def latest_observation(self) -> WeatherObservation | None:
        return self._latest_observation

    @property
    def latest_forecast(self) -> WeatherForecastSnapshot | None:
        return self._latest_forecast

    def latest_unit(self, field: str) -> str | None:
        if self._latest_forecast is None:
            return None
        return self._latest_forecast.units_by_field.get(field)

    def status_payload(self) -> dict[str, Any]:
        return {
            "enabled": self.config.enabled,
            "source": self.config.source,
            "latitude": self.config.latitude,
            "longitude": self.config.longitude,
            "poll_interval_s": self.config.poll_interval_s,
            "last_poll_attempt_at": (
                self._last_poll_attempt_at.isoformat()
                if self._last_poll_attempt_at is not None
                else None
            ),
            "last_success_at": (
                self._last_success_at.isoformat()
                if self._last_success_at is not None
                else None
            ),
            "last_error": self._last_error,
            "forecast_point_count": (
                len(self._latest_forecast.times)
                if self._latest_forecast is not None
                else 0
            ),
        }

    def poll_due(
        self,
        *,
        now: datetime,
        log_observation: Callable[[WeatherObservation], int] | None,
    ) -> WeatherPollResult:
        if not self.config.enabled:
            return WeatherPollResult()
        if self._next_poll_at is not None and now < self._next_poll_at:
            return WeatherPollResult()

        self._last_poll_attempt_at = now
        try:
            fetched = self._fetch(now=now)
            self._latest_observation = fetched.observation
            self._latest_forecast = fetched.forecast
            self._last_error = None
            self._last_success_at = now
            logged_count = (
                log_observation(fetched.observation)
                if log_observation is not None
                else 0
            )
            self._next_poll_at = now + timedelta(seconds=self.config.poll_interval_s)
            return WeatherPollResult(
                attempted=True,
                updated=True,
                logged_count=logged_count,
                observed_at=fetched.observation.observed_at,
            )
        except Exception as error:
            self._last_error = str(error)
            self._next_poll_at = now + timedelta(seconds=min(self.config.poll_interval_s, 300.0))
            return WeatherPollResult(
                attempted=True,
                updated=False,
                logged_count=0,
                error=str(error),
            )

    def _fetch(self, *, now: datetime) -> _WeatherFetchResult:
        if self.config.latitude is None or self.config.longitude is None:
            raise ValueError("weather latitude/longitude not configured")

        params = {
            "latitude": f"{self.config.latitude:.6f}",
            "longitude": f"{self.config.longitude:.6f}",
            "hourly": ",".join(WEATHER_FIELDS),
            "timezone": "UTC",
            "forecast_hours": str(self.config.forecast_hours),
            "past_hours": str(self.config.past_hours),
            "temperature_unit": self.config.temperature_unit,
            "wind_speed_unit": self.config.wind_speed_unit,
            "precipitation_unit": self.config.precipitation_unit,
        }
        url = f"{self.config.endpoint}?{urlencode(params)}"
        payload = self._fetch_json(url, self.config.request_timeout_s)
        return _parse_open_meteo_payload(
            payload,
            now=now,
            source=self.config.source,
            latitude=self.config.latitude,
            longitude=self.config.longitude,
            forecast_hours=self.config.forecast_hours,
        )


def _parse_open_meteo_payload(
    payload: Mapping[str, Any],
    *,
    now: datetime,
    source: str,
    latitude: float,
    longitude: float,
    forecast_hours: int,
) -> _WeatherFetchResult:
    hourly = payload.get("hourly")
    if not isinstance(hourly, Mapping):
        raise ValueError("open-meteo response missing hourly data")

    hourly_units = payload.get("hourly_units")
    units_by_field = (
        {
            field: _normalize_unit(raw_unit)
            for field, raw_unit in hourly_units.items()
            if isinstance(field, str) and isinstance(raw_unit, str)
        }
        if isinstance(hourly_units, Mapping)
        else {}
    )

    raw_times = hourly.get("time")
    if not isinstance(raw_times, list) or not raw_times:
        raise ValueError("open-meteo response missing hourly time values")
    times = tuple(_parse_utc_timestamp(str(item)) for item in raw_times)

    field_values: dict[str, tuple[float | None, ...]] = {}
    for field in WEATHER_FIELDS:
        raw_values = hourly.get(field)
        if not isinstance(raw_values, list):
            raise ValueError(f"open-meteo response missing hourly field {field}")
        values = tuple(
            _float_or_none(raw_values[index]) if index < len(raw_values) else None
            for index in range(len(times))
        )
        field_values[field] = values

    observed_index = _latest_observed_index(times, now)
    if observed_index < 0:
        observed_index = 0

    observed_values = {
        field: values[observed_index] if observed_index < len(values) else None
        for field, values in field_values.items()
    }
    observation = WeatherObservation(
        observed_at=times[observed_index],
        source=source,
        latitude=latitude,
        longitude=longitude,
        values=observed_values,
        units_by_field=units_by_field,
    )

    forecast_start = min(len(times), observed_index + 1)
    forecast_end = min(len(times), forecast_start + forecast_hours)
    forecast_times = times[forecast_start:forecast_end]
    forecast_values = {
        field: values[forecast_start:forecast_end]
        for field, values in field_values.items()
    }
    forecast = WeatherForecastSnapshot(
        generated_at=now,
        source=source,
        latitude=latitude,
        longitude=longitude,
        times=forecast_times,
        values_by_field=forecast_values,
        units_by_field=units_by_field,
    )
    return _WeatherFetchResult(observation=observation, forecast=forecast)


def _latest_observed_index(times: tuple[datetime, ...], now: datetime) -> int:
    latest = -1
    for index, value in enumerate(times):
        if value <= now:
            latest = index
            continue
        break
    return latest


def _parse_utc_timestamp(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _normalize_unit(unit: str) -> str:
    normalized = unit.strip()
    if normalized == "°C":
        return "degC"
    if normalized == "°F":
        return "degF"
    return normalized


def _default_fetch_json(url: str, timeout_s: float) -> Mapping[str, Any]:
    with urlopen(url, timeout=timeout_s) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("weather response must be a JSON object")
    if payload.get("error") is True:
        reason = payload.get("reason")
        raise ValueError(str(reason) if reason is not None else "weather API returned error")
    return payload


def _string(data: Mapping[str, Any], key: str, default: str) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"weather.{key} must be a string")
    return value


def _bool(data: Mapping[str, Any], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"weather.{key} must be true or false")
    return value


def _float(data: Mapping[str, Any], key: str, default: float) -> float:
    value = data.get(key, default)
    if not isinstance(value, int | float):
        raise ValueError(f"weather.{key} must be a number")
    return float(value)


def _int(data: Mapping[str, Any], key: str, default: int) -> int:
    value = data.get(key, default)
    if not isinstance(value, int):
        raise ValueError(f"weather.{key} must be an integer")
    return value


def _optional_float(data: Mapping[str, Any], key: str) -> float | None:
    if key not in data or data.get(key) is None:
        return None
    value = data.get(key)
    if not isinstance(value, int | float):
        raise ValueError(f"weather.{key} must be a number")
    return float(value)
