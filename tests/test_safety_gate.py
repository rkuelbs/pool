"""
Tests for safety interlocks and lockouts.

This file documents the pressure, booster, chlorination, prime, overpressure,
loss-of-prime, and freeze-protection safety rules.
"""

from __future__ import annotations

from pathlib import Path

from poolctl.domain.models import SensorId
from poolctl.services.safety import SafetyConfig, load_safety_config


def test_load_safety_config_from_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "pool.yaml"
    config_path.write_text(
        """
safety:
  pressure_sensor_ids:
    pump_output: filter_output_psi
    return_line: bubbler_psi
    booster: return_psi
  freeze_protection:
    enabled: true
    source: both
    temp_sensor: temp
    ph_temp_sensor: orp_temp
    low_speed_on_below_temp: 35
    low_speed_off_above_temp: 37
    high_speed_on_below_temp: 33
    high_speed_off_above_temp: 34
    min_run_seconds: 120
    threshold_unit: degF
  chlorine_tank:
    level_sensor: chlorine_tank_level_gal
    low_warning_gal: 2.25
    inhibit_below_gal: 1.25
    reenable_at_gal: 2.5
  thresholds:
    chlorine_min_return_psi: 3.5
    chlorine_min_pump_output_psi: 7.5
    chlorine_max_pump_output_psi: 8.5
    chlorine_requires_high_speed: false
    booster_max_psi: 62
    booster_min_psi: 28
    pump_low_prime_min_output_psi: 0.8
    pump_output_overpressure_psi: 32
    pump_high_prime_min_output_psi: 5.5
  timeouts:
    booster_low_pressure_grace_s: 12
    pump_low_prime_seconds: 25
    pump_high_prime_timeout_s: 35
""",
        encoding="utf-8",
    )

    config = load_safety_config(config_path)

    assert config.pressure_sensors.pump_output == SensorId.FILTER_OUTPUT_PSI
    assert config.pressure_sensors.return_line == SensorId.BUBBLER_PSI
    assert config.pressure_sensors.booster == SensorId.RETURN_PSI
    assert config.freeze_protection.enabled is True
    assert config.freeze_protection.source.value == "both"
    assert config.freeze_protection.temp_sensor == SensorId.TEMP
    assert config.freeze_protection.ph_temp_sensor == SensorId.ORP_TEMP
    assert config.freeze_protection.low_speed_on_below_temp == 35.0
    assert config.freeze_protection.low_speed_off_above_temp == 37.0
    assert config.freeze_protection.high_speed_on_below_temp == 33.0
    assert config.freeze_protection.high_speed_off_above_temp == 34.0
    assert config.freeze_protection.min_run_seconds == 120.0
    assert config.freeze_protection.threshold_unit.value == "degF"
    assert config.chlorine_tank.level_sensor == SensorId.CHLORINE_TANK_LEVEL_GAL
    assert config.chlorine_tank.low_warning_gal == 2.25
    assert config.chlorine_tank.inhibit_below_gal == 1.25
    assert config.chlorine_tank.reenable_at_gal == 2.5
    assert config.chlorine_min_return_psi == 3.5
    assert config.chlorine_min_pump_output_psi == 7.5
    assert config.chlorine_max_pump_output_psi == 8.5
    assert config.chlorine_requires_high_speed is False
    assert config.booster_max_psi == 62.0
    assert config.booster_min_psi == 28.0
    assert config.booster_low_pressure_grace_s == 12.0
    assert config.pump_low_prime_min_output_psi == 0.8
    assert config.pump_low_prime_seconds == 25.0
    assert config.pump_output_overpressure_psi == 32.0
    assert config.pump_high_prime_min_output_psi == 5.5
    assert config.pump_high_prime_timeout_s == 35.0


def test_safety_config_accepts_top_level_safety_mapping() -> None:
    config = SafetyConfig.from_mapping(
        {
            "pressure_sensor_ids": {
                "pump_output": "pump_output_psi",
                "return_line": "return_psi",
                "booster": "booster_psi",
            },
            "thresholds": {
                "chlorine_min_return_psi": 2.5,
            },
        }
    )

    assert config.pressure_sensors.pump_output == SensorId.PUMP_OUTPUT_PSI
    assert config.pressure_sensors.return_line == SensorId.RETURN_PSI
    assert config.pressure_sensors.booster == SensorId.BOOSTER_PSI
    assert config.freeze_protection.enabled is False
    assert config.chlorine_min_return_psi == 2.5
    assert config.chlorine_min_pump_output_psi == 3.0
    assert config.chlorine_max_pump_output_psi == 3.5
    assert config.chlorine_requires_high_speed is False


def test_freeze_ph_temp_default_uses_ph_temp_sensor() -> None:
    config = SafetyConfig()

    assert config.freeze_protection.ph_temp_sensor == SensorId.PH_TEMP


def test_freeze_config_accepts_legacy_on_threshold_keys() -> None:
    config = SafetyConfig.from_mapping(
        {
            "freeze_protection": {
                "enabled": True,
                "low_speed_below_temp": 36.0,
                "high_speed_below_temp": 34.0,
            }
        }
    )

    assert config.freeze_protection.enabled is True
    assert config.freeze_protection.low_speed_on_below_temp == 36.0
    assert config.freeze_protection.high_speed_on_below_temp == 34.0
