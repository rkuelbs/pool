from __future__ import annotations

from pathlib import Path

from poolctl.config import (
    DriverProfile,
    FeatureLayer,
    RuntimeConfig,
    RuntimeStage,
    default_actuators_for_stage,
    default_layers_for_stage,
    default_sensor_groups_for_stage,
    load_runtime_config,
)
from poolctl.domain.models import ActuatorId


def test_open_loop_timer_defaults_to_pump_and_booster_only() -> None:
    config = RuntimeConfig.from_mapping(
        {
            "runtime": {
                "stage": "open_loop_timer",
                "driver_profile": "raspberry_pi",
            }
        }
    )

    assert config.stage == RuntimeStage.OPEN_LOOP_TIMER
    assert config.driver_profile == DriverProfile.RASPBERRY_PI
    assert config.enabled_layers == {
        FeatureLayer.PUMP_TIMER,
        FeatureLayer.SAFETY_ENFORCEMENT,
    }
    assert config.enabled_actuators == {
        ActuatorId.PUMP_MOTOR,
        ActuatorId.PUMP_MOTOR_SPEED,
        ActuatorId.BOOSTER_PUMP,
    }
    assert not config.actuator_enabled(ActuatorId.CHLORINE_DOSING_PUMP)
    assert config.enabled_sensor_groups == frozenset()


def test_runtime_config_allows_explicit_layer_and_group_overrides() -> None:
    config = RuntimeConfig.from_mapping(
        {
            "stage": "sensor_logging",
            "driver_profile": "raspberry_pi",
            "enabled_layers": [
                "pump_timer",
                "acquisition",
                "logging",
            ],
            "enabled_actuators": [
                "pump_motor",
                "pump_motor_speed",
            ],
            "enabled_sensor_groups": [
                "pressures",
            ],
        }
    )

    assert config.stage == RuntimeStage.SENSOR_LOGGING
    assert config.layer_enabled(FeatureLayer.ACQUISITION)
    assert config.layer_enabled(FeatureLayer.LOGGING)
    assert not config.layer_enabled(FeatureLayer.SAFETY_ENFORCEMENT)
    assert config.actuator_enabled(ActuatorId.PUMP_MOTOR)
    assert not config.actuator_enabled(ActuatorId.BOOSTER_PUMP)
    assert config.sensor_group_enabled("pressures")
    assert not config.sensor_group_enabled("chemistry_loop")


def test_load_runtime_config_from_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "pool.yaml"
    config_path.write_text(
        """
runtime:
  stage: safety_monitor
  driver_profile: raspberry_pi
  enabled_layers:
    - pump_timer
    - acquisition
    - logging
    - safety_enforcement
  enabled_actuators:
    - pump_motor
    - pump_motor_speed
    - booster_pump
  enabled_sensor_groups:
    - pressures
    - chemistry_loop
""",
        encoding="utf-8",
    )

    config = load_runtime_config(config_path)

    assert config.stage == RuntimeStage.SAFETY_MONITOR
    assert config.driver_profile == DriverProfile.RASPBERRY_PI
    assert config.layer_enabled(FeatureLayer.SAFETY_ENFORCEMENT)
    assert config.sensor_group_enabled("chemistry_loop")


def test_stage_default_helpers_document_rollout_path() -> None:
    assert FeatureLayer.PUMP_TIMER in default_layers_for_stage(RuntimeStage.OPEN_LOOP_TIMER)
    assert FeatureLayer.CHLORINATION not in default_layers_for_stage(
        RuntimeStage.SENSOR_LOGGING
    )
    assert ActuatorId.CHLORINE_DOSING_PUMP not in default_actuators_for_stage(
        RuntimeStage.SENSOR_LOGGING
    )
    assert default_sensor_groups_for_stage(RuntimeStage.OPEN_LOOP_TIMER) == frozenset()
    assert "pressures" in default_sensor_groups_for_stage(RuntimeStage.SENSOR_LOGGING)
