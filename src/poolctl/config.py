"""
Parse high-level runtime and GUI configuration.

Most other modules use small service-specific config dataclasses. This module
keeps only the deployment facts the app builder needs: which driver family to
use, which physical outputs are present, which acquisition groups are active,
and how the live dashboard should present sensors.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

import yaml  # type: ignore[import-untyped]

from poolctl.domain.models import ActuatorId, SensorId

EnumT = TypeVar("EnumT", bound=Enum)


class DriverProfile(str, Enum):
    """
    Which concrete driver family should be used by the app builder.
    """

    SIMULATED = "simulated"
    RASPBERRY_PI = "raspberry_pi"


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
class SensorDisplayLimits:
    """
    Dashboard operating bands for one sensor.

    Values inside normal_min/normal_max are normal. Values between the normal
    band and caution_min/caution_max are caution. Values outside the caution
    band are alarm.
    """

    caution_min: float
    normal_min: float
    normal_max: float
    caution_max: float

    def __post_init__(self) -> None:
        if not (
            self.caution_min <= self.normal_min
            <= self.normal_max
            <= self.caution_max
        ):
            raise ValueError(
                "sensor display limits must satisfy "
                "caution_min <= normal_min <= normal_max <= caution_max"
            )


@dataclass(frozen=True)
class LiveViewConfig:
    """
    Display-only configuration for the live dashboard.
    """

    sensor_limits: dict[SensorId, SensorDisplayLimits]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> LiveViewConfig:
        live_view_data = _mapping_value(data, "live_view", default={})
        limits_data = _mapping_value(live_view_data, "sensor_limits", default={})
        sensor_limits: dict[SensorId, SensorDisplayLimits] = {}

        for raw_sensor_id, raw_limits in limits_data.items():
            if not isinstance(raw_sensor_id, str):
                raise ValueError("live_view sensor limit keys must be strings")

            if not isinstance(raw_limits, Mapping):
                raise ValueError(
                    f"live_view sensor limits for {raw_sensor_id} must be a mapping"
                )

            sensor_limits[SensorId(raw_sensor_id)] = SensorDisplayLimits(
                caution_min=_required_float_value(raw_limits, "caution_min"),
                normal_min=_required_float_value(raw_limits, "normal_min"),
                normal_max=_required_float_value(raw_limits, "normal_max"),
                caution_max=_required_float_value(raw_limits, "caution_max"),
            )

        return cls(sensor_limits=sensor_limits)


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
