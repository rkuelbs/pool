from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from poolctl.domain.models import ActuatorId, SensorId


class DriverProfile(str, Enum):
    """
    Which concrete driver family should be used by the app builder.
    """

    SIMULATED = "simulated"
    RASPBERRY_PI = "raspberry_pi"


class RuntimeStage(str, Enum):
    """
    Coarse deployment stage.

    These stages are intentionally operational. They let the same software move
    from a dumb timer to sensor logging and later closed-loop control without
    changing code paths for every deployment.
    """

    WINDOWS_SIMULATION = "windows_simulation"
    OPEN_LOOP_TIMER = "open_loop_timer"
    SENSOR_LOGGING = "sensor_logging"
    SAFETY_MONITOR = "safety_monitor"
    CLOSED_LOOP_CONTROL = "closed_loop_control"


class FeatureLayer(str, Enum):
    """
    Functional layers that can be enabled as hardware and software mature.
    """

    PUMP_TIMER = "pump_timer"
    ACQUISITION = "acquisition"
    LOGGING = "logging"
    SAFETY_ENFORCEMENT = "safety_enforcement"
    CHLORINATION = "chlorination"
    CLOSED_LOOP_CONTROL = "closed_loop_control"
    MQTT_BRIDGE = "mqtt_bridge"


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
    Runtime feature gates for a deployment.

    Detailed threshold and sampling settings still live in their own safety and
    acquisition config sections. This config controls which pieces the app
    builder should wire into the running system.
    """

    stage: RuntimeStage
    driver_profile: DriverProfile
    enabled_layers: frozenset[FeatureLayer]
    enabled_actuators: frozenset[ActuatorId]
    enabled_sensor_groups: frozenset[str]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> RuntimeConfig:
        runtime_data = _mapping_value(data, "runtime", default=data)
        stage = _enum_value(
            RuntimeStage,
            runtime_data,
            "stage",
            RuntimeStage.WINDOWS_SIMULATION,
        )
        driver_profile = _enum_value(
            DriverProfile,
            runtime_data,
            "driver_profile",
            DriverProfile.SIMULATED,
        )

        return cls(
            stage=stage,
            driver_profile=driver_profile,
            enabled_layers=_feature_layers_value(
                runtime_data,
                stage,
            ),
            enabled_actuators=_actuator_ids_value(
                runtime_data,
                stage,
            ),
            enabled_sensor_groups=_sensor_groups_value(
                runtime_data,
                stage,
            ),
        )

    def layer_enabled(self, layer: FeatureLayer) -> bool:
        return layer in self.enabled_layers

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


def default_layers_for_stage(stage: RuntimeStage) -> frozenset[FeatureLayer]:
    if stage == RuntimeStage.OPEN_LOOP_TIMER:
        return frozenset(
            {
                FeatureLayer.PUMP_TIMER,
                FeatureLayer.SAFETY_ENFORCEMENT,
            }
        )

    if stage == RuntimeStage.SENSOR_LOGGING:
        return frozenset(
            {
                FeatureLayer.PUMP_TIMER,
                FeatureLayer.ACQUISITION,
                FeatureLayer.LOGGING,
            }
        )

    if stage == RuntimeStage.SAFETY_MONITOR:
        return frozenset(
            {
                FeatureLayer.PUMP_TIMER,
                FeatureLayer.ACQUISITION,
                FeatureLayer.LOGGING,
                FeatureLayer.SAFETY_ENFORCEMENT,
            }
        )

    if stage == RuntimeStage.CLOSED_LOOP_CONTROL:
        return frozenset(FeatureLayer)

    return frozenset(
        {
            FeatureLayer.ACQUISITION,
            FeatureLayer.SAFETY_ENFORCEMENT,
        }
    )


def default_actuators_for_stage(stage: RuntimeStage) -> frozenset[ActuatorId]:
    if stage in {
        RuntimeStage.OPEN_LOOP_TIMER,
        RuntimeStage.SENSOR_LOGGING,
        RuntimeStage.SAFETY_MONITOR,
    }:
        return frozenset(
            {
                ActuatorId.PUMP_MOTOR,
                ActuatorId.PUMP_MOTOR_SPEED,
                ActuatorId.BOOSTER_PUMP,
            }
        )

    return frozenset(ActuatorId)


def default_sensor_groups_for_stage(stage: RuntimeStage) -> frozenset[str]:
    if stage == RuntimeStage.OPEN_LOOP_TIMER:
        return frozenset()

    return DEFAULT_SENSOR_GROUPS


def _feature_layers_value(
    data: Mapping[str, Any],
    stage: RuntimeStage,
) -> frozenset[FeatureLayer]:
    if "enabled_layers" not in data:
        return default_layers_for_stage(stage)

    return frozenset(
        _enum_item_value(FeatureLayer, item, "enabled_layers")
        for item in _string_list_value(data, "enabled_layers")
    )


def _actuator_ids_value(
    data: Mapping[str, Any],
    stage: RuntimeStage,
) -> frozenset[ActuatorId]:
    if "enabled_actuators" not in data:
        return default_actuators_for_stage(stage)

    return frozenset(
        _enum_item_value(ActuatorId, item, "enabled_actuators")
        for item in _string_list_value(data, "enabled_actuators")
    )


def _sensor_groups_value(
    data: Mapping[str, Any],
    stage: RuntimeStage,
) -> frozenset[str]:
    if "enabled_sensor_groups" not in data:
        return default_sensor_groups_for_stage(stage)

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


def _enum_value[T: Enum](
    enum_type: type[T],
    data: Mapping[str, Any],
    key: str,
    default: T,
) -> T:
    value = data.get(key, default.value)

    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")

    return enum_type(value)


def _enum_item_value[T: Enum](
    enum_type: type[T],
    value: str,
    source_name: str,
) -> T:
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
