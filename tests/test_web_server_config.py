"""
Tests for web server configuration APIs.

These tests cover form-backed GUI updates for schedule, safety, acquisition,
logging, chlorination, FC demand, and other YAML-backed settings.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from poolctl.app import build_app_from_mapping
from poolctl.config_files import load_config_with_overrides
from poolctl.services.clock import SimulatedClock
from poolctl.web.server import (
    add_chemical_addition,
    add_chlorine_tank_refill,
    add_lab_test,
    apply_analog_input_config_update,
    apply_acquisition_config_update,
    apply_active_schedule_profile_update,
    apply_chlorination_config_update,
    apply_filter_loading_config_update,
    apply_fc_demand_config_update,
    apply_logging_config_update,
    apply_notifications_config_update,
    apply_ph_sensor_config_update,
    apply_pump_timer_config_update,
    apply_runtime_config_update,
    apply_safety_config_update,
    apply_timer_override_update,
    build_health_payload,
    list_chemical_additions,
    list_chlorine_tank_refills,
    list_lab_tests,
    serialize_acquisition_config,
    serialize_logging_config,
    serialize_notifications_config,
    serialize_analog_input_config,
    serialize_chlorination_config,
    serialize_fc_demand_config,
    serialize_filter_loading_config,
    serialize_ph_sensor_config,
    serialize_pump_timer_config,
    serialize_runtime_config,
    serialize_safety_config,
    send_test_notification,
    start_chlorination_calibration,
    start_chlorination_prime,
    start_chlorination_supplemental_dose,
)


def make_clock() -> SimulatedClock:
    return SimulatedClock(
        start_at=datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc),
        speedup=3600.0,
    )


def config_mapping() -> dict[str, object]:
    return {
        "runtime": {
            "driver_profile": "simulated",
            "enabled_sensor_groups": [],
        },
        "pump_timer": {
            "timezone": "America/Chicago",
            "schedules": [
                {
                    "name": "morning_filter",
                    "start": "08:00",
                    "end": "12:00",
                    "pump_speed": "high",
                    "booster": "off",
                }
            ]
        },
    }


def test_serialize_pump_timer_config() -> None:
    app = build_app_from_mapping(config_mapping(), clock=make_clock())

    payload = serialize_pump_timer_config(app)

    assert payload["timezone"] == "America/Chicago"
    assert payload["schedules"] == [
        {
            "name": "morning_filter",
            "start": "08:00",
            "end": "12:00",
            "pump_speed": "high",
            "booster": "off",
            "allow_dosing": True,
        }
    ]


def test_apply_pump_timer_update_updates_running_app_and_yaml(tmp_path: Path) -> None:
    path = tmp_path / "pool.yaml"
    path.write_text(yaml.safe_dump(config_mapping(), sort_keys=False), encoding="utf-8")
    app = build_app_from_mapping(config_mapping(), clock=make_clock())

    result = apply_pump_timer_config_update(
        app=app,
        config_path=path,
        payload={
            "timezone": "UTC",
            "schedules": [
                {
                    "name": "evening_filter",
                    "start": "18:00",
                    "end": "21:00",
                    "pump_speed": "low",
                    "booster": "on",
                    "allow_dosing": False,
                }
            ]
        },
    )

    assert result["schedules"] == [
        {
            "name": "evening_filter",
            "start": "18:00",
            "end": "21:00",
            "pump_speed": "low",
            "booster": "on",
            "allow_dosing": False,
        }
    ]
    assert result["timezone"] == "UTC"
    assert app.pump_timer_config.schedules[0].name == "evening_filter"
    assert app.pump_timer_config.schedules[0].allow_dosing is False
    assert app.pump_timer_config.timezone == "UTC"

    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["site"]["timezone"] == "UTC"
    assert saved["pump_timer"]["active_profile"] == "normal"
    saved_schedule = saved["pump_timer"]["profiles"][0]["schedules"][0]
    assert saved_schedule["name"] == "evening_filter"
    assert saved_schedule["allow_dosing"] is False
    assert saved_schedule["timing"] == {
        "type": "fixed",
        "start": "18:00",
        "end": "21:00",
    }


def test_gui_config_update_can_write_local_override_without_touching_base(tmp_path: Path) -> None:
    base_path = tmp_path / "pi-prod.yaml"
    local_path = tmp_path / "pi-local.yaml"
    base_data = config_mapping()
    base_path.write_text(yaml.safe_dump(base_data, sort_keys=False), encoding="utf-8")
    base_before = base_path.read_text(encoding="utf-8")
    app = build_app_from_mapping(base_data, clock=make_clock())

    result = apply_pump_timer_config_update(
        app=app,
        config_path=base_path,
        local_config_path=local_path,
        payload={
            "timezone": "UTC",
            "schedules": [
                {
                    "name": "local_evening",
                    "start": "18:00",
                    "end": "21:00",
                    "pump_speed": "low",
                    "booster": "off",
                    "allow_dosing": True,
                }
            ],
        },
    )

    assert result["timezone"] == "UTC"
    assert base_path.read_text(encoding="utf-8") == base_before
    local_data = yaml.safe_load(local_path.read_text(encoding="utf-8"))
    assert local_data["site"] == {
        "timezone": "UTC",
        "latitude": None,
        "longitude": None,
    }
    assert local_data["pump_timer"]["active_profile"] == "normal"
    local_schedule = local_data["pump_timer"]["profiles"][0]["schedules"][0]
    assert local_schedule["name"] == "local_evening"
    assert local_schedule["allow_dosing"] is True
    effective = load_config_with_overrides(base_path, local_path=local_path)
    assert effective["runtime"] == base_data["runtime"]
    assert effective["pump_timer"]["profiles"][0]["schedules"][0]["name"] == (
        "local_evening"
    )


def test_active_profile_update_applies_live_and_persists(tmp_path: Path) -> None:
    config = {
        **config_mapping(),
        "site": {"timezone": "UTC"},
        "pump_timer": {
            "active_profile": "normal",
            "profiles": [
                {"name": "normal", "schedules": []},
                {"name": "away", "schedules": []},
            ],
        },
    }
    path = tmp_path / "pool.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    app = build_app_from_mapping(config, clock=make_clock())

    result = apply_active_schedule_profile_update(
        app=app,
        config_path=path,
        local_config_path=None,
        payload={"active_profile": "away"},
    )

    assert result["active_profile"] == "away"
    assert app.pump_timer_config.active_profile == "away"
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["pump_timer"]["active_profile"] == "away"


def test_chlorination_update_applies_live_and_persists(tmp_path: Path) -> None:
    config = config_mapping()
    path = tmp_path / "pool.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    app = build_app_from_mapping(config, clock=make_clock())

    result = apply_chlorination_config_update(
        app=app,
        config_path=path,
        payload={
            "enabled": True,
            "daily_dose_oz": 12.5,
            "pump_output_oz_per_min": 2.0,
            "no_dose_first_minutes": 1.25,
            "no_dose_last_minutes": 10.0,
            "max_duty_cycle": 0.5,
            "cycle_on_seconds": 60.0,
            "max_cycle_period_seconds": 1800.0,
            "min_cycle_on_seconds": 5.0,
        },
    )

    assert result["updated"] is True
    assert result["applied_live"] is True
    assert result["daily_dose_oz"] == 12.5
    assert result["max_cycle_period_seconds"] == 1800.0
    assert result["min_cycle_on_seconds"] == 5.0
    assert app.chlorination_config.daily_dose_oz == 12.5
    assert app.chlorination_config.no_dose_first_minutes == 1.25
    assert app.chlorination_config.max_cycle_period_seconds == 1800.0
    assert serialize_chlorination_config(app)["no_dose_first_minutes"] == 1.25
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["chlorination"]["daily_dose_oz"] == 12.5
    assert saved["chlorination"]["pump_output_oz_per_min"] == 2.0
    assert saved["chlorination"]["no_dose_first_minutes"] == 1.25
    assert saved["chlorination"]["max_cycle_period_seconds"] == 1800.0
    assert saved["chlorination"]["min_cycle_on_seconds"] == 5.0


def test_filter_loading_update_applies_live_and_persists(tmp_path: Path) -> None:
    config = config_mapping()
    path = tmp_path / "pool.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    app = build_app_from_mapping(config, clock=make_clock())

    result = apply_filter_loading_config_update(
        app=app,
        config_path=path,
        payload={
            "enabled": True,
            "clean_flow_gpm": None,
            "yellow_flow_loss_percent": 9.0,
            "red_flow_loss_percent": 14.0,
            "stabilization_seconds": 75.0,
            "averaging_seconds": 180.0,
            "max_pressure_age_seconds": 8.0,
        },
    )

    assert result["updated"] is True
    assert result["applied_live"] is True
    assert app.flow_estimation_config.filter_loading.clean_flow_gpm is None
    assert serialize_filter_loading_config(app)["red_flow_loss_percent"] == 14.0
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["filter_loading"]["clean_flow_gpm"] is None
    assert saved["filter_loading"]["yellow_flow_loss_percent"] == 9.0
    assert saved["filter_loading"]["red_flow_loss_percent"] == 14.0
    assert saved["filter_loading"]["averaging_seconds"] == 180.0


def test_fc_demand_update_applies_live_and_persists(tmp_path: Path) -> None:
    config = config_mapping()
    config["fc_demand"] = {
        "enabled": False,
        "mode": "observe_only",
        "pool_volume_gal": 10000.0,
        "target_fc_ppm": 4.0,
        "chlorine_strength_percent": 12.0,
        "minimum_test_interval_hours": 12.0,
        "max_observation_interval_days": 7.0,
        "preferred_test_start_hour": 18,
        "preferred_test_end_hour": 24,
        "negative_demand_noise_tolerance_ppm_per_day": 0.05,
        "recent_observation_count": 5,
        "observation_weights": [0.35, 0.25, 0.18, 0.13, 0.09],
        "fc_feedback_gain": 0.6,
        "max_maintenance_change_percent": 15.0,
        "max_daily_dose_oz": 256.0,
    }
    path = tmp_path / "pool.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    app = build_app_from_mapping(config, clock=make_clock())

    result = apply_fc_demand_config_update(
        app=app,
        config_path=path,
        payload={
            "enabled": True,
            "mode": "automatic",
            "pool_volume_gal": 14500.0,
            "target_fc_ppm": 5.0,
            "chlorine_strength_percent": 12.5,
            "minimum_test_interval_hours": 24.0,
            "max_observation_interval_days": 6.0,
            "preferred_test_start_hour": 19,
            "preferred_test_end_hour": 22,
            "negative_demand_noise_tolerance_ppm_per_day": 0.03,
            "recent_observation_count": 3,
            "observation_weights": [0.5, 0.3, 0.2],
            "fc_feedback_gain": 0.75,
            "max_maintenance_change_percent": 20.0,
            "max_daily_dose_oz": 300.0,
        },
    )

    assert result["updated"] is True
    assert result["applied_live"] is True
    assert result["mode"] == "automatic"
    assert app.fc_demand_config.pool_volume_gal == 14500.0
    assert app.fc_demand_config.max_observation_interval_days == 6.0
    assert app.fc_demand_config.preferred_test_start_hour == 19
    assert app.fc_demand_config.preferred_test_end_hour == 22
    assert app.fc_demand_config.negative_demand_noise_tolerance_ppm_per_day == 0.03
    assert app.fc_demand_config.recent_observation_count == 3
    assert app.fc_demand_config.observation_weights == (0.5, 0.3, 0.2)
    assert serialize_fc_demand_config(app)["target_fc_ppm"] == 5.0
    assert serialize_fc_demand_config(app)["fc_feedback_gain"] == 0.75
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["fc_demand"]["mode"] == "automatic"
    assert saved["fc_demand"]["pool_volume_gal"] == 14500.0
    assert saved["fc_demand"]["max_observation_interval_days"] == 6.0
    assert saved["fc_demand"]["preferred_test_start_hour"] == 19
    assert saved["fc_demand"]["preferred_test_end_hour"] == 22
    assert saved["fc_demand"]["negative_demand_noise_tolerance_ppm_per_day"] == 0.03
    assert saved["fc_demand"]["recent_observation_count"] == 3
    assert saved["fc_demand"]["observation_weights"] == [0.5, 0.3, 0.2]
    assert saved["fc_demand"]["fc_feedback_gain"] == 0.75
    assert saved["fc_demand"]["max_maintenance_change_percent"] == 20.0


def test_start_chlorination_prime_sets_runtime_timer() -> None:
    app = build_app_from_mapping(config_mapping(), clock=make_clock())

    result = start_chlorination_prime(
        app=app,
        payload={"duration_s": 30.0},
    )

    assert result["started"] is True
    assert result["prime"]["active"] is True
    assert result["prime"]["remaining_s"] == 30.0


def test_start_chlorination_calibration_sets_runtime_duty_cycle() -> None:
    app = build_app_from_mapping(config_mapping(), clock=make_clock())

    result = start_chlorination_calibration(
        app=app,
        payload={},
    )

    assert result["started"] is True
    assert result["prime"]["active"] is True
    assert result["prime"]["mode"] == "calibration"
    assert result["prime"]["remaining_s"] == 1200.0
    assert result["prime"]["duty_cycle"] == 0.5
    assert result["prime"]["cycle_period_s"] == 120.0
    assert result["prime"]["safety_bypass"] is True


def test_start_chlorination_supplemental_dose_sets_runtime_plan() -> None:
    config = config_mapping()
    runtime = dict(config["runtime"])
    runtime["enabled_actuators"] = [
        "pump_motor",
        "pump_motor_speed",
        "booster_pump",
        "chlorine_dosing_pump",
    ]
    config["runtime"] = runtime
    config["chlorination"] = {
        "enabled": True,
        "daily_dose_oz": 0.0,
        "pump_output_oz_per_min": 1.0,
        "no_dose_last_minutes": 10.0,
        "max_duty_cycle": 0.5,
        "cycle_on_seconds": 60.0,
        "min_cycle_on_seconds": 5.0,
    }
    app = build_app_from_mapping(config, clock=make_clock())

    result = start_chlorination_supplemental_dose(
        app=app,
        payload={"dose_oz": 1.0},
    )

    status = result["supplemental_chlorine_dose"]
    assert result["started"] is True
    assert status["active"] is True
    assert status["phase"] == "preparing"
    assert status["committed_runtime_s"] == 0.0
    assert status["planned_dose_oz"] == 1.0
    assert status["duty_cycle"] == 0.5
    assert status["pulse_seconds"] == 60.0
    assert status["pulse_count"] == 1


def test_supplemental_chlorine_dose_splits_runtime_into_equal_pulses() -> None:
    config = config_mapping()
    runtime = dict(config["runtime"])
    runtime["enabled_actuators"] = [
        "pump_motor",
        "pump_motor_speed",
        "booster_pump",
        "chlorine_dosing_pump",
    ]
    config["runtime"] = runtime
    config["chlorination"] = {
        "enabled": True,
        "daily_dose_oz": 0.0,
        "pump_output_oz_per_min": 1.0,
        "no_dose_last_minutes": 10.0,
        "max_duty_cycle": 0.5,
        "cycle_on_seconds": 60.0,
        "min_cycle_on_seconds": 5.0,
    }
    app = build_app_from_mapping(config, clock=make_clock())

    result = start_chlorination_supplemental_dose(
        app=app,
        payload={"dose_oz": 70.0 / 60.0},
    )

    status = result["supplemental_chlorine_dose"]
    assert status["pulse_count"] == 2
    assert status["pulse_seconds"] == 35.0
    assert status["planned_dose_oz"] == 1.1667
    assert status["min_cycle_on_seconds_overridden"] is False


def test_supplemental_chlorine_dose_allows_one_off_subminimum_pulse() -> None:
    config = config_mapping()
    runtime = dict(config["runtime"])
    runtime["enabled_actuators"] = [
        "pump_motor",
        "pump_motor_speed",
        "booster_pump",
        "chlorine_dosing_pump",
    ]
    config["runtime"] = runtime
    config["chlorination"] = {
        "enabled": True,
        "daily_dose_oz": 0.0,
        "pump_output_oz_per_min": 1.0,
        "no_dose_last_minutes": 10.0,
        "max_duty_cycle": 0.5,
        "cycle_on_seconds": 60.0,
        "min_cycle_on_seconds": 5.0,
    }
    app = build_app_from_mapping(config, clock=make_clock())

    result = start_chlorination_supplemental_dose(
        app=app,
        payload={"dose_oz": 0.05},
    )

    status = result["supplemental_chlorine_dose"]
    assert status["pulse_count"] == 1
    assert status["pulse_seconds"] == 3.0
    assert status["planned_dose_oz"] == 0.05
    assert status["min_cycle_on_seconds_overridden"] is True


def test_runtime_update_writes_yaml_and_reports_restart(tmp_path: Path) -> None:
    path = tmp_path / "pool.yaml"
    path.write_text(yaml.safe_dump(config_mapping(), sort_keys=False), encoding="utf-8")
    app = build_app_from_mapping(config_mapping(), clock=make_clock())

    before = serialize_runtime_config(app)
    assert before["driver_profile"] == "simulated"
    assert "stage" not in before
    assert "enabled_layers" not in before

    result = apply_runtime_config_update(
        app=app,
        config_path=path,
        payload={
            "driver_profile": "simulated",
            "enabled_actuators": ["pump_motor", "pump_motor_speed"],
            "enabled_sensor_groups": ["pressures"],
        },
    )

    assert result["requires_restart"] is True
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["runtime"]["driver_profile"] == "simulated"
    assert saved["runtime"]["enabled_actuators"] == ["pump_motor", "pump_motor_speed"]
    assert saved["runtime"]["enabled_sensor_groups"] == ["pressures"]
    assert "stage" not in saved["runtime"]
    assert "enabled_layers" not in saved["runtime"]


def test_safety_update_applies_live_and_persists(tmp_path: Path) -> None:
    path = tmp_path / "pool.yaml"
    path.write_text(yaml.safe_dump(config_mapping(), sort_keys=False), encoding="utf-8")
    app = build_app_from_mapping(config_mapping(), clock=make_clock())

    payload = {
        "pressure_sensor_ids": {
            "pump_output": "pump_output_psi",
        },
        "freeze_protection": {
            "enabled": True,
            "primary_temperature_sensor": "ph_temp",
            "fallback_temperature_sensor": "orp_temp",
            "max_temperature_age_seconds": 1800.0,
            "low_speed_on_below_temp": 35.0,
            "low_speed_off_above_temp": 37.0,
            "high_speed_on_below_temp": 33.0,
            "high_speed_off_above_temp": 34.0,
            "min_run_seconds": 180.0,
            "threshold_unit": "degF",
        },
        "chlorine_tank": {
            "level_sensor": "chlorine_tank_level_gal",
            "low_warning_gal": 2.25,
            "inhibit_below_gal": 1.25,
            "reenable_at_gal": 2.5,
        },
        "thresholds": {
            "chlorine_min_pump_output_psi": 3.0,
            "chlorine_max_pump_output_psi": 3.5,
            "pump_prime_min_output_psi": 1.1,
            "pump_output_overpressure_psi": 31.0,
        },
        "timeouts": {
            "pump_output_max_age_seconds": 12.0,
            "pump_prime_timeout_s": 31.0,
        },
    }
    result = apply_safety_config_update(app=app, config_path=path, payload=payload)

    assert result["applied_live"] is True
    assert app.safety_config.pump_prime_min_output_psi == 1.1
    assert app.safety_config.freeze_protection.enabled is True
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["safety"]["thresholds"]["pump_prime_min_output_psi"] == 1.1
    assert saved["safety"]["timeouts"]["pump_output_max_age_seconds"] == 12.0
    assert saved["safety"]["freeze_protection"]["primary_temperature_sensor"] == "ph_temp"
    assert saved["safety"]["freeze_protection"]["fallback_temperature_sensor"] == "orp_temp"
    assert saved["safety"]["freeze_protection"]["max_temperature_age_seconds"] == 1800.0
    assert saved["safety"]["chlorine_tank"]["inhibit_below_gal"] == 1.25
    assert saved["safety"]["chlorine_tank"]["forecast_reserve_gal"] == 2.0
    serialized = serialize_safety_config(app)
    assert serialized["thresholds"]["chlorine_max_pump_output_psi"] == 3.5
    assert serialized["thresholds"]["pump_prime_min_output_psi"] == 1.1
    assert serialized["timeouts"]["pump_output_max_age_seconds"] == 12.0
    assert serialized["freeze_protection"]["high_speed_on_below_temp"] == 33.0
    assert serialized["freeze_protection"]["primary_temperature_sensor"] == "ph_temp"
    assert serialized["chlorine_tank"]["reenable_at_gal"] == 2.5


def test_acquisition_and_logging_updates_write_yaml(tmp_path: Path) -> None:
    path = tmp_path / "pool.yaml"
    path.write_text(yaml.safe_dump(config_mapping(), sort_keys=False), encoding="utf-8")
    app = build_app_from_mapping(config_mapping(), clock=make_clock())

    acq_result = apply_acquisition_config_update(
        app=app,
        config_path=path,
        payload={
            "groups": {
                "pressures": {
                    "sensor_ids": ["pump_output_psi"],
                    "read_interval_s": 1.0,
                    "log_interval_s": 30.0,
                    "requires_pump_flow": False,
                    "oversample": {
                        "sample_count": 1,
                        "sample_interval_s": 0.0,
                        "reducer": "last",
                    },
                    "filter": {
                        "type": "boxcar",
                        "window_samples": 2,
                        "window_seconds": None,
                        "min_samples": 1,
                    },
                }
            }
        },
    )
    assert acq_result["requires_restart"] is True

    logging_result = apply_logging_config_update(
        app=app,
        config_path=path,
        payload={
            "database_path": "data/new.sqlite3",
            "control_measurement_interval_s": 45.0,
        },
    )
    assert logging_result["requires_restart"] is True
    assert serialize_acquisition_config(app)["requires_restart"] is True
    assert serialize_logging_config(app)["requires_restart"] is True

    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert str(saved["logging"]["database_path"]).endswith("new.sqlite3")
    assert saved["logging"]["control_measurement_interval_s"] == 45.0
    assert saved["acquisition"]["groups"]["pressures"]["filter"]["type"] == "boxcar"
    assert saved["acquisition"]["groups"]["pressures"]["filter"]["window_samples"] == 2


def test_notifications_update_applies_live_and_persists(tmp_path: Path) -> None:
    path = tmp_path / "pool.yaml"
    path.write_text(yaml.safe_dump(config_mapping(), sort_keys=False), encoding="utf-8")
    app = build_app_from_mapping(config_mapping(), clock=make_clock())

    result = apply_notifications_config_update(
        app=app,
        config_path=path,
        payload={
            "enabled": True,
            "provider": "pushover",
            "default_title": "poolctl pi",
            "pushover": {
                "app_token_env": "POOL_PUSHOVER_TOKEN",
                "user_key_env": "POOL_PUSHOVER_USER",
                "api_url": "https://api.pushover.net/1/messages.json",
                "timeout_s": 4.0,
                "priority": 1,
                "sound": "bike",
            },
            "alerts": {
                "chlorine_tank": {
                    "enabled": True,
                    "caution_below": 4.0,
                    "warning_below": 1.5,
                    "caution_repeat_minutes": 720.0,
                    "warning_repeat_minutes": 120.0,
                },
                "ph": {
                    "enabled": True,
                    "caution_below": 7.2,
                    "caution_above": 7.8,
                    "warning_below": 6.9,
                    "warning_above": 8.1,
                    "caution_repeat_minutes": 360.0,
                    "warning_repeat_minutes": 60.0,
                },
                "orp": {
                    "enabled": False,
                    "caution_below": 600.0,
                    "caution_above": 800.0,
                    "warning_below": 400.0,
                    "warning_above": 900.0,
                    "caution_repeat_minutes": 1440.0,
                    "warning_repeat_minutes": 240.0,
                },
                "filter_flow_loss": {
                    "enabled": True,
                    "warning_above": 16.0,
                    "warning_repeat_minutes": 1440.0,
                },
                "freeze_temperature_unavailable": {
                    "enabled": True,
                    "warning_repeat_minutes": 180.0,
                },
            },
        },
    )

    assert result["updated"] is True
    assert result["applied_live"] is True
    assert app.notification_service is not None
    assert serialize_notifications_config(app)["default_title"] == "poolctl pi"
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["notifications"]["enabled"] is True
    assert saved["notifications"]["pushover"]["app_token_env"] == "POOL_PUSHOVER_TOKEN"
    assert saved["notifications"]["alerts"]["chlorine_tank"]["warning_below"] == 1.5
    assert saved["notifications"]["alerts"]["ph"]["warning_repeat_minutes"] == 60.0
    assert saved["notifications"]["alerts"]["filter_flow_loss"]["warning_above"] == 16.0
    assert (
        saved["notifications"]["alerts"]["freeze_temperature_unavailable"]
        ["warning_repeat_minutes"]
        == 180.0
    )
    assert "app_token" not in saved["notifications"]["pushover"]
    assert "user_key" not in saved["notifications"]["pushover"]


def test_notifications_update_round_trips_direct_credentials_and_allows_clearing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pool.yaml"
    path.write_text(yaml.safe_dump(config_mapping(), sort_keys=False), encoding="utf-8")
    app = build_app_from_mapping(config_mapping(), clock=make_clock())

    first = apply_notifications_config_update(
        app=app,
        config_path=path,
        payload={
            "enabled": True,
            "provider": "pushover",
            "default_title": "poolctl",
            "pushover": {
                "app_token": "direct-token",
                "user_key": "direct-user",
                "app_token_env": "PUSHOVER_APP_TOKEN",
                "user_key_env": "PUSHOVER_USER_KEY",
                "api_url": "https://api.pushover.net/1/messages.json",
                "timeout_s": 5.0,
                "priority": 0,
                "sound": None,
            },
            "alerts": {
                "chlorine_tank": {
                    "enabled": True,
                    "caution_below": 7.0,
                    "warning_below": 3.0,
                    "caution_repeat_minutes": 1440.0,
                    "warning_repeat_minutes": 240.0,
                }
            },
        },
    )
    cleared = apply_notifications_config_update(
        app=app,
        config_path=path,
        payload={
            "enabled": True,
            "provider": "pushover",
            "default_title": "poolctl",
            "pushover": {
                "app_token": None,
                "user_key": None,
                "app_token_env": "PUSHOVER_APP_TOKEN",
                "user_key_env": "PUSHOVER_USER_KEY",
                "api_url": "https://api.pushover.net/1/messages.json",
                "timeout_s": 5.0,
                "priority": 0,
                "sound": None,
            },
            "alerts": {
                "chlorine_tank": {
                    "enabled": True,
                    "caution_below": 7.0,
                    "warning_below": 3.0,
                    "caution_repeat_minutes": 1440.0,
                    "warning_repeat_minutes": 240.0,
                }
            },
        },
    )

    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert first["pushover"]["configured"] is True
    assert first["pushover"]["app_token_configured"] is True
    assert first["pushover"]["app_token"] == "direct-token"
    assert first["pushover"]["user_key"] == "direct-user"
    assert cleared["pushover"]["configured"] is False
    assert cleared["pushover"]["app_token"] is None
    assert cleared["pushover"]["user_key"] is None
    assert "app_token" not in saved["notifications"]["pushover"]
    assert "user_key" not in saved["notifications"]["pushover"]


def test_send_test_notification_reports_disabled_when_not_enabled() -> None:
    app = build_app_from_mapping(config_mapping(), clock=make_clock())

    result = send_test_notification(
        app=app,
        payload={"title": "poolctl", "message": "test"},
    )

    assert result["notification"]["sent"] is False
    assert result["notification"]["error"] == "notifications disabled"


def test_timer_override_update_sets_and_clears_runtime_override() -> None:
    app = build_app_from_mapping(config_mapping(), clock=make_clock())

    set_result = apply_timer_override_update(
        app=app,
        payload={
            "mode": "force_on",
            "duration_s": 3600,
            "pump_speed": "high",
            "booster": "off",
            "reason": "manual run",
        },
    )
    assert set_result["override"]["active"] is True
    assert app.active_timer_override() is not None

    clear_result = apply_timer_override_update(
        app=app,
        payload={"mode": "auto"},
    )
    assert clear_result["override"]["active"] is False
    assert app.active_timer_override() is None


def test_force_on_override_defaults_to_one_hour() -> None:
    app = build_app_from_mapping(config_mapping(), clock=make_clock())
    result = apply_timer_override_update(
        app=app,
        payload={
            "mode": "force_on",
            "pump_speed": "high",
            "booster": "off",
            "reason": "quick test",
        },
    )
    assert result["override"]["active"] is True
    assert result["override"]["until"] is not None


def test_override_can_expire_at_next_schedule_event() -> None:
    clock = SimulatedClock(
        start_at=datetime(2026, 5, 22, 14, 0, tzinfo=timezone.utc),
        speedup=1.0,
    )
    app = build_app_from_mapping(config_mapping(), clock=clock)
    result = apply_timer_override_update(
        app=app,
        payload={
            "mode": "force_on",
            "pump_speed": "high",
            "booster": "off",
            "reason": "manual high until schedule transition",
            "until_next_schedule": True,
        },
    )

    assert result["override"]["active"] is True
    assert result["override"]["until"] == "2026-05-22T17:00:00+00:00"


def test_analog_input_update_writes_yaml(tmp_path: Path) -> None:
    path = tmp_path / "pool.yaml"
    path.write_text(yaml.safe_dump(config_mapping(), sort_keys=False), encoding="utf-8")

    payload = {
        "modbus_analog_input": {
            "port": "/dev/ttyUSB0",
            "slave_id": 4,
            "baudrate": 9600,
            "timeout_s": 1.0,
            "raw_to_volts_scale": 0.001,
            "raw_to_volts_offset": 0.0,
            "startup_channel_mode": 0,
                "sensors": {
                    "pump_output_psi": {
                        "channel": 1,
                    "calibration": {
                        "voltage_1": 0.0,
                        "value_1": 0.0,
                        "voltage_2": 5.0,
                        "value_2": 30.0,
                    },
                }
            },
        }
    }
    result = apply_analog_input_config_update(config_path=path, payload=payload)
    assert result["requires_restart"] is True

    serialized = serialize_analog_input_config(path)
    assert serialized["modbus_analog_input"]["sensors"]["pump_output_psi"]["channel"] == 1
    assert serialized["modbus_analog_input"]["startup_channel_mode"] == 0


def test_ph_sensor_update_disables_driver_and_removes_acquisition_ids(tmp_path: Path) -> None:
    config = config_mapping()
    runtime = dict(config["runtime"])  # type: ignore[index]
    runtime["driver_profile"] = "raspberry_pi"
    runtime["enabled_sensor_groups"] = ["chemistry_loop"]
    config["runtime"] = runtime
    config["enable_modbus_ph_sensor"] = True
    config["modbus_ph_sensor"] = {
        "port": "/dev/ttyUSB0",
        "slave_id": 4,
        "baudrate": 4800,
        "timeout_s": 1.0,
        "circuit_breaker": {
            "enabled": True,
            "failure_threshold": 3,
            "cooldown_s": 45.0,
        },
    }
    config["acquisition"] = {
        "groups": {
            "chemistry_loop": {
                "sensor_ids": ["raw_orp", "orp_temp", "raw_ph", "ph_temp"],
                "read_interval_s": 5.0,
                "log_interval_s": 60.0,
                "requires_pump_flow": True,
                "min_pump_on_seconds": 60.0,
                "oversample": {
                    "sample_count": 1,
                    "sample_interval_s": 0.0,
                    "reducer": "last",
                },
            }
        }
    }
    path = tmp_path / "pool.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    result = apply_ph_sensor_config_update(
        config_path=path,
        payload={
            "enabled": False,
            "modbus_ph_sensor": {
                "port": "/dev/ttyUSB0",
                "slave_id": 4,
                "baudrate": 4800,
                "timeout_s": 1.0,
            },
        },
    )

    assert result["enabled"] is False
    assert result["requires_restart"] is True
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["enable_modbus_ph_sensor"] is False
    assert saved["acquisition"]["groups"]["chemistry_loop"]["sensor_ids"] == [
        "raw_orp",
        "orp_temp",
    ]
    assert saved["modbus_ph_sensor"]["circuit_breaker"]["failure_threshold"] == 3
    assert saved["modbus_ph_sensor"]["circuit_breaker"]["cooldown_s"] == 45.0
    serialized = serialize_ph_sensor_config(path)
    assert serialized["modbus_ph_sensor"]["slave_id"] == 4
    assert serialized["modbus_ph_sensor"]["circuit_breaker"]["failure_threshold"] == 3


def test_ph_sensor_update_enables_driver_and_adds_acquisition_ids(tmp_path: Path) -> None:
    config = config_mapping()
    runtime = dict(config["runtime"])  # type: ignore[index]
    runtime["driver_profile"] = "raspberry_pi"
    config["runtime"] = runtime
    config["acquisition"] = {
        "groups": {
            "chemistry_loop": {
                "sensor_ids": ["raw_orp", "orp_temp"],
                "read_interval_s": 5.0,
                "log_interval_s": 60.0,
                "requires_pump_flow": True,
                "min_pump_on_seconds": 60.0,
                "oversample": {
                    "sample_count": 1,
                    "sample_interval_s": 0.0,
                    "reducer": "last",
                },
            }
        }
    }
    path = tmp_path / "pool.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    apply_ph_sensor_config_update(
        config_path=path,
        payload={
            "enabled": True,
            "modbus_ph_sensor": {
                "port": "/dev/ttyUSB0",
                "slave_id": 4,
                "baudrate": 4800,
                "timeout_s": 1.0,
                "circuit_breaker": {
                    "enabled": True,
                    "failure_threshold": 4,
                    "cooldown_s": 90.0,
                },
            },
        },
    )

    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["enable_modbus_ph_sensor"] is True
    assert saved["acquisition"]["groups"]["chemistry_loop"]["sensor_ids"] == [
        "raw_orp",
        "orp_temp",
        "raw_ph",
        "ph_temp",
    ]
    assert saved["modbus_ph_sensor"]["circuit_breaker"]["failure_threshold"] == 4
    assert saved["modbus_ph_sensor"]["circuit_breaker"]["cooldown_s"] == 90.0


def test_health_payload_includes_status_fields() -> None:
    app = build_app_from_mapping(config_mapping(), clock=make_clock())
    payload = build_health_payload(app)
    assert payload["status"] in {"ok", "degraded"}
    assert "modbus" in payload
    assert "acquisition" in payload
    assert "mqtt" not in payload
    assert "weather" in payload


def test_lab_test_api_helpers_store_and_list(tmp_path: Path) -> None:
    config = config_mapping()
    runtime = dict(config["runtime"])  # type: ignore[index]
    config["runtime"] = runtime
    config["logging"] = {"database_path": str(tmp_path / "labtests.sqlite3")}
    app = build_app_from_mapping(config, clock=make_clock())

    result = add_lab_test(
        app=app,
        payload={
            "sampled_at": "2026-05-22T12:00:00+00:00",
            "ph": 7.4,
            "free_chlorine": 3.1,
            "notes": "manual entry",
        },
        source="local_gui",
    )
    listed = list_lab_tests(app, hours=24.0 * 30.0, limit=20)

    assert result["saved"] is True
    assert result["lab_test"]["ph"] == 7.4
    assert len(listed["lab_tests"]) == 1
    assert listed["lab_tests"][0]["free_chlorine"] == 3.1


def test_lab_test_api_returns_recalculated_fc_demand_feedback(tmp_path: Path) -> None:
    config = config_mapping()
    runtime = dict(config["runtime"])  # type: ignore[index]
    config["runtime"] = runtime
    config["logging"] = {"database_path": str(tmp_path / "fc-demand-feedback.sqlite3")}
    config["fc_demand"] = {
        "enabled": True,
        "mode": "automatic",
        "pool_volume_gal": 10000.0,
        "target_fc_ppm": 4.0,
        "chlorine_strength_percent": 12.0,
        "minimum_test_interval_hours": 12.0,
        "preferred_test_start_hour": 0,
        "preferred_test_end_hour": 24,
        "max_daily_dose_oz": 256.0,
    }
    app = build_app_from_mapping(config, clock=make_clock())

    first = add_lab_test(
        app=app,
        payload={
            "sampled_at": "2026-05-21T12:00:00+00:00",
            "free_chlorine": 4.0,
        },
        source="local_gui",
    )
    second = add_lab_test(
        app=app,
        payload={
            "sampled_at": "2026-05-22T12:00:00+00:00",
            "free_chlorine": 3.0,
        },
        source="local_gui",
    )

    assert first["fc_demand"]["ready"] is False
    assert second["fc_demand"]["ready"] is True
    assert second["fc_demand"]["mode"] == "automatic"
    assert round(second["fc_demand"]["daily_demand_ppm"], 3) == 1.0
    assert round(second["fc_demand"]["feedback_dose_oz"], 3) == 6.4
    assert second["fc_demand"]["applied_feedback_dose_oz"] == 0.0
    assert second["fc_demand"]["feedback_control_date"] == "2026-05-23"


def test_lab_test_api_accepts_sparse_payload_and_defaults_sampled_at(tmp_path: Path) -> None:
    config = config_mapping()
    runtime = dict(config["runtime"])  # type: ignore[index]
    config["runtime"] = runtime
    config["logging"] = {"database_path": str(tmp_path / "labtests.sqlite3")}
    app = build_app_from_mapping(config, clock=make_clock())

    result = add_lab_test(
        app=app,
        payload={
            "sampled_at": None,
            "tds": 1000.0,
        },
        source="local_gui",
    )
    listed = list_lab_tests(app, hours=24.0 * 30.0, limit=20)

    assert result["saved"] is True
    assert result["lab_test"]["tds"] == 1000.0
    assert listed["lab_tests"][0]["tds"] == 1000.0


def test_event_entry_api_interprets_naive_times_as_local_controller_time(
    tmp_path: Path,
) -> None:
    config = config_mapping()
    runtime = dict(config["runtime"])  # type: ignore[index]
    config["runtime"] = runtime
    config["logging"] = {"database_path": str(tmp_path / "events.sqlite3")}
    app = build_app_from_mapping(config, clock=make_clock())

    lab = add_lab_test(
        app=app,
        payload={
            "sampled_at": "2026-05-22T07:30",
            "free_chlorine": 3.2,
        },
        source="local_gui",
    )
    chemical = add_chemical_addition(
        app=app,
        payload={
            "added_at": "2026-05-22T07:45",
            "chemical": "sodium_hypochlorite",
            "amount": 32.0,
            "unit": "fl_oz",
        },
        source="local_gui",
    )

    assert lab["lab_test"]["sampled_at"] == "2026-05-22T12:30:00+00:00"
    assert chemical["chemical_addition"]["added_at"] == "2026-05-22T12:45:00+00:00"


def test_chemical_addition_api_helpers_store_defaults_and_list(tmp_path: Path) -> None:
    config = config_mapping()
    runtime = dict(config["runtime"])  # type: ignore[index]
    config["runtime"] = runtime
    config["logging"] = {"database_path": str(tmp_path / "chemical.sqlite3")}
    app = build_app_from_mapping(config, clock=make_clock())

    hypo = add_chemical_addition(
        app=app,
        payload={
            "added_at": "2026-05-22T12:00:00+00:00",
            "chemical": "sodium_hypochlorite",
            "amount": 64.0,
            "unit": "fl_oz",
        },
        source="local_gui",
    )
    acid = add_chemical_addition(
        app=app,
        payload={
            "added_at": "2026-05-22T12:30:00+00:00",
            "chemical": "muriatic_acid",
            "amount": 1.0,
            "unit": "gal",
            "notes": "lower pH",
        },
        source="local_gui",
    )
    listed = list_chemical_additions(app, hours=24.0 * 30.0, limit=20)

    assert hypo["saved"] is True
    assert hypo["chemical_addition"]["strength_percent"] == 12.0
    assert hypo["chemical_addition"]["amount_fl_oz"] == 64.0
    assert acid["chemical_addition"]["strength_percent"] == 31.45
    assert acid["chemical_addition"]["amount_fl_oz"] == 128.0
    assert len(listed["chemical_additions"]) == 2
    assert listed["chemical_additions"][1]["chemical"] == "muriatic_acid"


def test_chlorine_tank_refill_and_level_tests_update_estimate_and_audit(
    tmp_path: Path,
) -> None:
    config = config_mapping()
    runtime = dict(config["runtime"])  # type: ignore[index]
    config["runtime"] = runtime
    config["logging"] = {"database_path": str(tmp_path / "tank.sqlite3")}
    app = build_app_from_mapping(config, clock=make_clock())
    assert app.measurement_logger is not None

    first = add_lab_test(
        app=app,
        payload={
            "sampled_at": "2026-05-20T12:00:00+00:00",
            "chlorine_tank_level_gal": 10.0,
        },
        source="local_gui",
    )
    app.measurement_logger.log_chlorine_delivery(
        observed_at=datetime(2026, 5, 21, 12, tzinfo=timezone.utc),
        runtime_seconds=60.0,
        delivered_oz=128.0,
    )
    refill = add_chlorine_tank_refill(
        app=app,
        payload={
            "added_at": "2026-05-21T13:00:00+00:00",
            "amount_gal": 2.0,
            "notes": "two gallons",
        },
        source="local_gui",
    )
    second = add_lab_test(
        app=app,
        payload={
            "sampled_at": "2026-05-22T12:00:00+00:00",
            "chlorine_tank_level_gal": 10.75,
        },
        source="local_gui",
    )
    listed = list_chlorine_tank_refills(app, hours=24.0 * 30.0, limit=20)

    assert first["chlorine_tank"]["audit"]["ready"] is False
    assert first["chlorine_tank"]["estimate"]["level_gal"] == 10.0
    assert refill["chlorine_tank_refill"]["amount_gal"] == 2.0
    assert refill["chlorine_tank"]["estimate"]["level_gal"] == 11.0
    assert second["lab_test"]["chlorine_tank_level_gal"] == 10.75
    assert second["chlorine_tank"]["audit"]["ready"] is True
    assert second["chlorine_tank"]["audit"]["expected_level_gal"] == 11.0
    assert second["chlorine_tank"]["audit"]["injection_error_gal"] == 0.25
    assert second["chlorine_tank"]["audit"]["injection_error_percent"] == 25.0
    assert listed["chlorine_tank_refills"][0]["notes"] == "two gallons"
    assert listed["chlorine_tank"]["estimate"]["level_gal"] == 10.75


def test_history_event_forms_use_local_datetime_inputs() -> None:
    static_dir = Path(__file__).parents[1] / "src" / "poolctl" / "web" / "static"
    history_html = (static_dir / "history.html").read_text(encoding="utf-8")

    assert 'id="labSampledAt" type="datetime-local"' in history_html
    assert 'id="chemicalAddedAt" type="datetime-local"' in history_html
    assert 'id="labChlorineTankLevelGal" type="number"' in history_html
    assert 'id="chlorineTankRefillAmountGal" type="number"' in history_html

    for page_name in ("config.html", "live.html", "schedule.html"):
        html = (static_dir / page_name).read_text(encoding="utf-8")
        assert 'id="labSampledAt" type="datetime-local"' in html
        assert 'id="labChlorineTankLevelGal" type="number"' in html

    config_html = (static_dir / "config.html").read_text(encoding="utf-8")
    assert 'id="pushoverAppToken" type="text"' in config_html
    assert 'id="pushoverUserKey" type="text"' in config_html
    assert "Caution below days" in config_html
    assert "Warning below days" in config_html
