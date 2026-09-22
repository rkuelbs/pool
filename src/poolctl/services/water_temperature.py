"""Canonical pool water-temperature selection and source metadata."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from poolctl.domain.models import Measurement, MeasurementKind, Quality, SensorId
from poolctl.services.measurement_quality import usable_numeric_measurement_value


_TEMPERATURE_UNITS = frozenset(("degF", "degC"))
_AVAILABLE_QUALITIES = (Quality.GOOD, Quality.SUSPECT)


@dataclass(frozen=True)
class WaterTemperatureConfig:
    """Source order and freshness limit for the canonical water temperature."""

    primary_sensor: SensorId = SensorId.PH_TEMP
    fallback_sensor: SensorId = SensorId.ORP_TEMP
    max_age_seconds: float = 3600.0

    def __post_init__(self) -> None:
        if self.primary_sensor == self.fallback_sensor:
            raise ValueError("water-temperature primary and fallback sensors must differ")
        if self.max_age_seconds < 0:
            raise ValueError("water-temperature max_age_seconds must be >= 0")


@dataclass(frozen=True)
class WaterTemperatureSourceStatus:
    sensor_id: SensorId
    available: bool
    age_seconds: float | None
    reason: str | None

    def as_payload(self) -> dict[str, Any]:
        return {
            "sensor_id": self.sensor_id.value,
            "available": self.available,
            "stale_or_unavailable": not self.available,
            "age_seconds": self.age_seconds,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class WaterTemperatureSelection:
    config: WaterTemperatureConfig
    measurement: Measurement | None
    active_source: SensorId | None
    active_value: float | None
    active_unit: str | None
    active_age_seconds: float | None
    primary: WaterTemperatureSourceStatus
    fallback: WaterTemperatureSourceStatus

    @property
    def available(self) -> bool:
        return self.measurement is not None

    @property
    def using_fallback(self) -> bool:
        return self.active_source == self.config.fallback_sensor

    def canonical_measurement(self) -> Measurement | None:
        source = self.measurement
        if source is None or self.active_source is None:
            return None
        return Measurement(
            id=f"water_temp:{source.id}",
            sensor_id=SensorId.WATER_TEMP,
            observed_at=source.observed_at,
            kind=MeasurementKind.ESTIMATED,
            value=source.value,
            unit=source.unit,
            quality=source.quality,
            source_measurement_ids=[source.id],
            metadata={
                "active_source": self.active_source.value,
                "age_seconds": self.active_age_seconds,
                "using_fallback": self.using_fallback,
            },
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "configured_primary_source": self.config.primary_sensor.value,
            "configured_fallback_source": self.config.fallback_sensor.value,
            "max_age_seconds": self.config.max_age_seconds,
            "active_source": self.active_source.value if self.active_source else None,
            "active_temperature": self.active_value,
            "active_unit": self.active_unit,
            "temperature_age_seconds": self.active_age_seconds,
            "using_fallback": self.using_fallback,
            "primary": self.primary.as_payload(),
            "fallback": self.fallback.as_payload(),
        }


def select_water_temperature(
    measurements: Mapping[SensorId, Measurement],
    *,
    now: datetime,
    config: WaterTemperatureConfig = WaterTemperatureConfig(),
) -> WaterTemperatureSelection:
    """Select fresh PH temperature first, then fresh ORP temperature."""
    primary_measurement = measurements.get(config.primary_sensor)
    fallback_measurement = measurements.get(config.fallback_sensor)
    primary = _source_status(
        primary_measurement,
        sensor_id=config.primary_sensor,
        now=now,
        max_age_seconds=config.max_age_seconds,
    )
    fallback = _source_status(
        fallback_measurement,
        sensor_id=config.fallback_sensor,
        now=now,
        max_age_seconds=config.max_age_seconds,
    )

    selected: Measurement | None = None
    selected_status: WaterTemperatureSourceStatus | None = None
    if primary.available:
        selected = primary_measurement
        selected_status = primary
    elif fallback.available:
        selected = fallback_measurement
        selected_status = fallback

    return WaterTemperatureSelection(
        config=config,
        measurement=selected,
        active_source=selected.sensor_id if selected is not None else None,
        active_value=float(selected.value) if selected is not None else None,
        active_unit=selected.unit if selected is not None else None,
        active_age_seconds=(selected_status.age_seconds if selected_status is not None else None),
        primary=primary,
        fallback=fallback,
    )


def _source_status(
    measurement: Measurement | None,
    *,
    sensor_id: SensorId,
    now: datetime,
    max_age_seconds: float,
) -> WaterTemperatureSourceStatus:
    if measurement is None:
        return WaterTemperatureSourceStatus(sensor_id, False, None, "missing")
    age_seconds = max(0.0, (now - measurement.observed_at).total_seconds())
    if measurement.unit not in _TEMPERATURE_UNITS:
        return WaterTemperatureSourceStatus(sensor_id, False, age_seconds, "invalid unit")
    if measurement.quality not in _AVAILABLE_QUALITIES:
        return WaterTemperatureSourceStatus(
            sensor_id,
            False,
            age_seconds,
            f"quality {measurement.quality.value}",
        )
    value = usable_numeric_measurement_value(
        measurement,
        now=now,
        max_age_seconds=max_age_seconds,
        acceptable_qualities=_AVAILABLE_QUALITIES,
    )
    if value is None:
        reason = "stale" if age_seconds > max_age_seconds else "non-finite value"
        return WaterTemperatureSourceStatus(sensor_id, False, age_seconds, reason)
    return WaterTemperatureSourceStatus(sensor_id, True, age_seconds, None)
