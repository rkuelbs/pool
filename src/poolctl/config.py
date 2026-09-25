"""
Parse high-level runtime and GUI configuration.

Most other modules use small service-specific config dataclasses. This module
keeps deployment facts and configuration shared across service boundaries:
pool/site identity, monitoring limits, the active driver family, physical
outputs, and acquisition groups.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml  # type: ignore[import-untyped]

from poolctl.domain.models import ActuatorId, SensorId

EnumT = TypeVar("EnumT", bound=Enum)


class DriverProfile(str, Enum):
    """
    Which concrete driver family should be used by the app builder.
    """

    SIMULATED = "simulated"
    RASPBERRY_PI = "raspberry_pi"


@dataclass(frozen=True)
class SiteConfig:
    """Canonical site timezone and optional geographic coordinates."""

    timezone: str = "UTC"
    latitude: float | None = None
    longitude: float | None = None
    location_source: str = "site"

    def __post_init__(self) -> None:
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"invalid timezone: {self.timezone}") from error
        if self.latitude is not None and not -90.0 <= self.latitude <= 90.0:
            raise ValueError("site.latitude must be between -90 and 90")
        if self.longitude is not None and not -180.0 <= self.longitude <= 180.0:
            raise ValueError("site.longitude must be between -180 and 180")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("site.latitude and site.longitude must be configured together")

    @property
    def has_location(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> SiteConfig:
        raw_site = data.get("site", {})
        if not isinstance(raw_site, Mapping):
            raise ValueError("site must be a mapping")
        raw_timer = data.get("pump_timer", {})
        if not isinstance(raw_timer, Mapping):
            raise ValueError("pump_timer must be a mapping")
        raw_weather = data.get("weather", {})
        if not isinstance(raw_weather, Mapping):
            raise ValueError("weather must be a mapping")

        timezone_name = raw_site.get(
            "timezone",
            raw_timer.get("timezone", "UTC"),
        )
        if not isinstance(timezone_name, str):
            raise ValueError("site.timezone must be a string")

        latitude = _optional_number(raw_site.get("latitude"), "site.latitude")
        longitude = _optional_number(raw_site.get("longitude"), "site.longitude")
        source = "site"
        if latitude is None and longitude is None:
            latitude = _optional_number(
                raw_weather.get("latitude"),
                "weather.latitude",
            )
            longitude = _optional_number(
                raw_weather.get("longitude"),
                "weather.longitude",
            )
            source = "weather_legacy" if latitude is not None or longitude is not None else "site"

        return cls(
            timezone=timezone_name,
            latitude=latitude,
            longitude=longitude,
            location_source=source,
        )


@dataclass(frozen=True)
class PoolConfig:
    """Canonical pool identity and physical volume."""

    name: str = "Home Pool"
    volume_gal: float = 10000.0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("pool.name must not be blank")
        if self.volume_gal <= 0:
            raise ValueError("pool.volume_gal must be > 0")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> PoolConfig:
        pool_data = _mapping_value(data, "pool", default={})
        raw_name = pool_data.get("name", cls.name)
        if not isinstance(raw_name, str):
            raise ValueError("pool.name must be a string")
        return cls(
            name=raw_name.strip(),
            volume_gal=_float_value(pool_data, "volume_gal", cls.volume_gal),
        )


DEFAULT_SENSOR_GROUPS = frozenset(
    {
        "pressures",
        "chemistry_loop",
        "chemical_tank",
    }
)


@dataclass(frozen=True)
class RuntimeConfig:
    """
    Runtime hardware profile for a deployment.

    Service-specific enabled flags still live in their own config sections.
    Safety is always wired by the app builder and is not a feature switch.
    """

    driver_profile: DriverProfile
    enabled_actuators: frozenset[ActuatorId]
    enabled_sensor_groups: frozenset[str]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> RuntimeConfig:
        runtime_data = _mapping_value(data, "runtime", default=data)
        driver_profile = _enum_value(
            DriverProfile,
            runtime_data,
            "driver_profile",
            DriverProfile.SIMULATED,
        )

        return cls(
            driver_profile=driver_profile,
            enabled_actuators=_actuator_ids_value(
                runtime_data,
            ),
            enabled_sensor_groups=_sensor_groups_value(
                runtime_data,
            ),
        )

    def actuator_enabled(self, actuator_id: ActuatorId) -> bool:
        return actuator_id in self.enabled_actuators

    def sensor_group_enabled(self, group_name: str) -> bool:
        return group_name in self.enabled_sensor_groups


@dataclass(frozen=True)
class MonitoringLimit:
    """Canonical normal/caution/alarm boundaries for one measurement."""

    alarm_below: float | None = None
    caution_below: float | None = None
    caution_above: float | None = None
    alarm_above: float | None = None

    def __post_init__(self) -> None:
        ordered = tuple(
            value
            for value in (
                self.alarm_below,
                self.caution_below,
                self.caution_above,
                self.alarm_above,
            )
            if value is not None
        )
        if not ordered:
            raise ValueError("monitoring limits must define at least one boundary")
        if any(left > right for left, right in zip(ordered, ordered[1:], strict=False)):
            raise ValueError(
                "monitoring limits must satisfy alarm_below <= caution_below "
                "<= caution_above <= alarm_above for configured boundaries"
            )

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> MonitoringLimit:
        return cls(
            alarm_below=_optional_float_value(data, "alarm_below"),
            caution_below=_optional_float_value(data, "caution_below"),
            caution_above=_optional_float_value(data, "caution_above"),
            alarm_above=_optional_float_value(data, "alarm_above"),
        )

    def as_mapping(self, *, include_missing: bool = False) -> dict[str, float | None]:
        values = {
            "alarm_below": self.alarm_below,
            "caution_below": self.caution_below,
            "caution_above": self.caution_above,
            "alarm_above": self.alarm_above,
        }
        if include_missing:
            return values
        return {key: value for key, value in values.items() if value is not None}


def default_monitoring_limits() -> dict[SensorId, MonitoringLimit]:
    """Defaults matching PoolScope's established primary status bands."""
    return {
        SensorId.RAW_PH: MonitoringLimit(6.8, 7.2, 7.8, 8.2),
        SensorId.RAW_ORP: MonitoringLimit(400.0, 600.0, 800.0, 900.0),
        SensorId.CALCIUM_SATURATION_INDEX: MonitoringLimit(-0.6, -0.3, 0.3, 0.6),
        SensorId.FILTER_FLOW_LOSS_PERCENT: MonitoringLimit(
            caution_above=10.0,
            alarm_above=15.0,
        ),
        SensorId.CHLORINE_TANK_DAYS_REMAINING: MonitoringLimit(
            alarm_below=3.0,
            caution_below=7.0,
        ),
        SensorId.CPU_TEMP: MonitoringLimit(caution_above=70.0, alarm_above=80.0),
    }


@dataclass(frozen=True)
class MonitoringConfig:
    """Canonical status ranges shared by every status and alert consumer."""

    limits: dict[SensorId, MonitoringLimit]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> MonitoringConfig:
        monitoring_data = _mapping_value(data, "monitoring", default={})
        raw_limits = monitoring_data.get("limits")
        if raw_limits is None:
            return cls(limits=default_monitoring_limits())
        if not isinstance(raw_limits, Mapping):
            raise ValueError("monitoring.limits must be a mapping")

        limits = default_monitoring_limits()
        for raw_sensor_id, raw_limit in raw_limits.items():
            if not isinstance(raw_sensor_id, str):
                raise ValueError("monitoring.limits keys must be sensor ids")
            if not isinstance(raw_limit, Mapping):
                raise ValueError(
                    f"monitoring.limits.{raw_sensor_id} must be a mapping"
                )
            try:
                sensor_id = SensorId(raw_sensor_id)
            except ValueError as error:
                raise ValueError(
                    f"monitoring.limits contains unknown sensor id: {raw_sensor_id}"
                ) from error
            limits[sensor_id] = MonitoringLimit.from_mapping(raw_limit)
        return cls(limits=limits)

    def limit_for(self, sensor_id: SensorId) -> MonitoringLimit | None:
        return self.limits.get(sensor_id)


LIVE_KPI_CHART_UNITS = {
    "chlorine_supply": "gal",
    "flow": "gpm",
    "filter_loss": "percent",
}


@dataclass(frozen=True)
class LiveKpiChartConfig:
    """Display-only settings for one Live KPI chart."""

    window_hours: float
    unit: str
    auto_y: bool = True
    y_min: float | None = None
    y_max: float | None = None

    def __post_init__(self) -> None:
        if not 1.0 <= self.window_hours <= 24.0 * 365.0:
            raise ValueError("chart window_hours must be between 1 and 8760")
        if not self.auto_y and self.y_min is None and self.y_max is None:
            raise ValueError("fixed chart scaling requires y_min or y_max")
        if self.y_min is not None and self.y_max is not None and self.y_min >= self.y_max:
            raise ValueError("chart y_min must be less than y_max")

    def as_mapping(self) -> dict[str, Any]:
        return {
            "window_hours": self.window_hours,
            "auto_y": self.auto_y,
            "y_min": self.y_min,
            "y_max": self.y_max,
            "unit": self.unit,
        }


def default_live_kpi_charts() -> dict[str, LiveKpiChartConfig]:
    return {
        "chlorine_supply": LiveKpiChartConfig(window_hours=168.0, unit="gal"),
        "flow": LiveKpiChartConfig(window_hours=24.0, unit="gpm"),
        "filter_loss": LiveKpiChartConfig(window_hours=720.0, unit="percent"),
    }


@dataclass(frozen=True)
class DisplayConfig:
    """Dashboard presentation settings; never used by control or safety logic."""

    live_kpi_charts: dict[str, LiveKpiChartConfig]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> DisplayConfig:
        display_data = _mapping_value(data, "display", default={})
        raw_charts = _mapping_value(display_data, "live_kpi_charts", default={})
        defaults = default_live_kpi_charts()
        unknown = set(raw_charts) - set(defaults)
        if unknown:
            raise ValueError(
                "display.live_kpi_charts contains unsupported charts: "
                + ", ".join(sorted(str(item) for item in unknown))
            )
        charts: dict[str, LiveKpiChartConfig] = {}
        for chart_key, default in defaults.items():
            raw = raw_charts.get(chart_key, {})
            if not isinstance(raw, Mapping):
                raise ValueError(f"display.live_kpi_charts.{chart_key} must be a mapping")
            unit = raw.get("unit", default.unit)
            if unit != LIVE_KPI_CHART_UNITS[chart_key]:
                raise ValueError(
                    f"display.live_kpi_charts.{chart_key}.unit must be "
                    f"{LIVE_KPI_CHART_UNITS[chart_key]}"
                )
            auto_y = raw.get("auto_y", default.auto_y)
            if not isinstance(auto_y, bool):
                raise ValueError(f"display.live_kpi_charts.{chart_key}.auto_y must be true or false")
            charts[chart_key] = LiveKpiChartConfig(
                window_hours=_float_value(raw, "window_hours", default.window_hours),
                auto_y=auto_y,
                y_min=_optional_number(raw.get("y_min"), f"display.live_kpi_charts.{chart_key}.y_min"),
                y_max=_optional_number(raw.get("y_max"), f"display.live_kpi_charts.{chart_key}.y_max"),
                unit=str(unit),
            )
        return cls(live_kpi_charts=charts)

    def as_mapping(self) -> dict[str, Any]:
        return {
            "live_kpi_charts": {
                key: chart.as_mapping() for key, chart in self.live_kpi_charts.items()
            }
        }


def load_runtime_config(path: str | Path) -> RuntimeConfig:
    with Path(path).open("r", encoding="utf-8") as config_file:
        data = yaml.safe_load(config_file) or {}

    if not isinstance(data, Mapping):
        raise ValueError("runtime config file must contain a mapping")

    return RuntimeConfig.from_mapping(data)


def default_actuators() -> frozenset[ActuatorId]:
    return frozenset(ActuatorId)


def default_sensor_groups() -> frozenset[str]:
    return DEFAULT_SENSOR_GROUPS


def _actuator_ids_value(
    data: Mapping[str, Any],
) -> frozenset[ActuatorId]:
    if "enabled_actuators" not in data:
        return default_actuators()

    return frozenset(
        _enum_item_value(ActuatorId, item, "enabled_actuators")
        for item in _string_list_value(data, "enabled_actuators")
    )


def _sensor_groups_value(
    data: Mapping[str, Any],
) -> frozenset[str]:
    if "enabled_sensor_groups" not in data:
        return default_sensor_groups()

    return frozenset(_string_list_value(data, "enabled_sensor_groups"))


def _mapping_value(
    data: Mapping[str, Any],
    key: str,
    *,
    default: Mapping[str, Any],
) -> Mapping[str, Any]:
    value = data.get(key, default)

    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be a mapping")

    return value


def _enum_value(
    enum_type: type[EnumT],
    data: Mapping[str, Any],
    key: str,
    default: EnumT,
) -> EnumT:
    value = data.get(key, default.value)

    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")

    return enum_type(value)


def _enum_item_value(
    enum_type: type[EnumT],
    value: str,
    source_name: str,
) -> EnumT:
    try:
        return enum_type(value)
    except ValueError as error:
        raise ValueError(f"invalid value in {source_name}: {value}") from error


def _string_list_value(data: Mapping[str, Any], key: str) -> list[str]:
    value = data.get(key)

    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")

    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{key} entries must be strings")

    return value


def _required_float_value(data: Mapping[str, Any], key: str) -> float:
    value = data.get(key)

    if not isinstance(value, int | float):
        raise ValueError(f"{key} must be a number")

    return float(value)


def _float_value(data: Mapping[str, Any], key: str, default: float) -> float:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{key} must be a number")
    return float(value)


def _optional_float_value(data: Mapping[str, Any], key: str) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{key} must be a number or null")
    return float(value)


def _optional_number(value: object, key: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{key} must be a number or null")
    return float(value)
