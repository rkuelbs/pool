"""
Tests for runtime and live-view configuration parsing.
"""

from __future__ import annotations

from pathlib import Path

from poolctl.config import DriverProfile, RuntimeConfig, load_runtime_config
from poolctl.domain.models import ActuatorId


def test_runtime_config_defaults_to_current_service_wiring() -> None:
    config = RuntimeConfig.from_mapping(
        {
            "runtime": {
                "driver_profile": "raspberry_pi",
            }
        }
    )

    assert config.driver_profile == DriverProfile.RASPBERRY_PI
    assert config.actuator_enabled(ActuatorId.PUMP_MOTOR)
    assert config.actuator_enabled(ActuatorId.CHLORINE_DOSING_PUMP)
    assert config.sensor_group_enabled("pressures")
    assert config.sensor_group_enabled("chemistry_loop")


def test_runtime_config_allows_explicit_actuator_and_group_overrides() -> None:
    config = RuntimeConfig.from_mapping(
        {
            "runtime": {
                "driver_profile": "raspberry_pi",
                "enabled_actuators": [
                    "pump_motor",
                    "pump_motor_speed",
                ],
                "enabled_sensor_groups": [
                    "pressures",
                ],
            }
        }
    )

    assert config.driver_profile == DriverProfile.RASPBERRY_PI
    assert config.actuator_enabled(ActuatorId.PUMP_MOTOR)
    assert not config.actuator_enabled(ActuatorId.BOOSTER_PUMP)
    assert config.sensor_group_enabled("pressures")
    assert not config.sensor_group_enabled("chemistry_loop")


def test_load_runtime_config_from_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "pool.yaml"
    config_path.write_text(
        """
runtime:
  driver_profile: raspberry_pi
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

    assert config.driver_profile == DriverProfile.RASPBERRY_PI
    assert config.actuator_enabled(ActuatorId.BOOSTER_PUMP)
    assert not config.actuator_enabled(ActuatorId.CHLORINE_DOSING_PUMP)
    assert config.sensor_group_enabled("chemistry_loop")
