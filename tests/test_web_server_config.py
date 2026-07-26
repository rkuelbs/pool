from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from poolctl.app import build_app_from_mapping
from poolctl.services.clock import SimulatedClock
from poolctl.web.server import (
    add_chemical_addition,
    add_lab_test,
    apply_analog_input_config_update,
    apply_acquisition_config_update,
    apply_chlorination_config_update,
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
    list_lab_tests,
    serialize_acquisition_config,
    serialize_logging_config,
    serialize_notifications_config,
    serialize_analog_input_config,
    serialize_chlorination_config,
    serialize_fc_demand_config,
    serialize_ph_sensor_config,
    serialize_pump_timer_config,
    serialize_runtime_config,
    serialize_safety_config,
    send_test_notification,
    start_chlorination_calibration,
    start_chlorination_prime,
)


def make_clock() -> SimulatedClock:
    return SimulatedClock(
        start_at=datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc),
        speedup=3600.0,
    )


def config_mapping() -> dict[str, object]:
    return {
        "runtime": {
            "stage": "open_loop_timer",
            "driver_profile": "simulated",
            "enabled_layers": ["pump_timer", "safety_enforcement"],
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

    assert payload["layer_enabled"] is True
    assert payload["timezone"] == "America/Chicago"
    assert payload["schedules"] == [
        {
            "name": "morning_filter",
            "start": "08:00",
            "end": "12:00",
            "pump_speed": "high",
            "booster": "off",
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
        }
    ]
    assert result["timezone"] == "UTC"
    assert app.pump_timer_config.schedules[0].name == "evening_filter"
    assert app.pump_timer_config.timezone == "UTC"

    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["pump_timer"]["schedules"][0]["name"] == "evening_filter"
    assert saved["pump_timer"]["timezone"] == "UTC"


def test_chlorination_update_applies_live_and_persists(tmp_path: Path) -> None:
    config = config_mapping()
    runtime = dict(config["runtime"])  # type: ignore[index]
    runtime["enabled_layers"] = ["pump_timer", "chlorination"]
    config["runtime"] = runtime
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
            "no_dose_last_minutes": 10.0,
            "max_duty_cycle": 0.5,
            "cycle_on_seconds": 60.0,
        },
    )

    assert result["updated"] is True
    assert result["applied_live"] is True
    assert result["daily_dose_oz"] == 12.5
    assert app.chlorination_config.daily_dose_oz == 12.5
    assert serialize_chlorination_config(app)["layer_enabled"] is True
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["chlorination"]["daily_dose_oz"] == 12.5
    assert saved["chlorination"]["pump_output_oz_per_min"] == 2.0


def test_fc_demand_update_applies_live_and_persists(tmp_path: Path) -> None:
    config = config_mapping()
    config["fc_demand"] = {
        "enabled": False,
        "mode": "observe_only",
        "pool_volume_gal": 10000.0,
        "target_fc_ppm": 4.0,
        "chlorine_strength_percent": 12.0,
        "minimum_test_interval_hours": 12.0,
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
            "max_daily_dose_oz": 300.0,
        },
    )

    assert result["updated"] is True
    assert result["applied_live"] is True
    assert result["mode"] == "automatic"
    assert app.fc_demand_config.pool_volume_gal == 14500.0
    assert serialize_fc_demand_config(app)["target_fc_ppm"] == 5.0
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["fc_demand"]["mode"] == "automatic"
    assert saved["fc_demand"]["pool_volume_gal"] == 14500.0


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


def test_runtime_update_writes_yaml_and_reports_restart(tmp_path: Path) -> None:
    path = tmp_path / "pool.yaml"
    path.write_text(yaml.safe_dump(config_mapping(), sort_keys=False), encoding="utf-8")
    app = build_app_from_mapping(config_mapping(), clock=make_clock())

    before = serialize_runtime_config(app)
    assert before["stage"] == "open_loop_timer"

    result = apply_runtime_config_update(
        app=app,
        config_path=path,
        payload={
            "stage": "windows_simulation",
            "driver_profile": "simulated",
            "enabled_layers": ["acquisition", "safety_enforcement"],
        },
    )

    assert result["requires_restart"] is True
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["runtime"]["stage"] == "windows_simulation"


def test_safety_update_applies_live_and_persists(tmp_path: Path) -> None:
    path = tmp_path / "pool.yaml"
    path.write_text(yaml.safe_dump(config_mapping(), sort_keys=False), encoding="utf-8")
    app = build_app_from_mapping(config_mapping(), clock=make_clock())

    payload = {
        "pressure_sensor_ids": {
            "pump_output": "pump_output_psi",
            "return_line": "return_psi",
            "booster": "booster_psi",
        },
        "freeze_protection": {
            "enabled": True,
            "source": "both",
            "temp_sensor": "temp",
            "ph_temp_sensor": "orp_temp",
            "low_speed_on_below_temp": 35.0,
            "low_speed_off_above_temp": 37.0,
            "high_speed_on_below_temp": 33.0,
            "high_speed_off_above_temp": 34.0,
            "min_run_seconds": 180.0,
            "threshold_unit": "degF",
        },
        "thresholds": {
            "chlorine_min_return_psi": 2.5,
            "chlorine_min_pump_output_psi": 6.5,
            "booster_max_psi": 58.0,
            "booster_min_psi": 29.0,
            "pump_low_prime_min_output_psi": 1.1,
            "pump_output_overpressure_psi": 31.0,
            "pump_high_prime_min_output_psi": 5.2,
        },
        "timeouts": {
            "booster_low_pressure_grace_s": 11.0,
            "pump_low_prime_seconds": 31.0,
            "pump_high_prime_timeout_s": 32.0,
        },
    }
    result = apply_safety_config_update(app=app, config_path=path, payload=payload)

    assert result["applied_live"] is True
    assert app.safety_config.booster_max_psi == 58.0
    assert app.safety_config.freeze_protection.enabled is True
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["safety"]["thresholds"]["booster_max_psi"] == 58.0
    assert saved["safety"]["freeze_protection"]["source"] == "both"
    serialized = serialize_safety_config(app)
    assert serialized["thresholds"]["booster_max_psi"] == 58.0
    assert serialized["freeze_protection"]["high_speed_on_below_temp"] == 33.0


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
        payload={"database_path": "data/new.sqlite3"},
    )
    assert logging_result["requires_restart"] is True
    assert serialize_acquisition_config(app)["requires_restart"] is True
    assert serialize_logging_config(app)["requires_restart"] is True

    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert str(saved["logging"]["database_path"]).endswith("new.sqlite3")
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
        },
    )

    assert result["updated"] is True
    assert result["applied_live"] is True
    assert app.notification_service is not None
    assert serialize_notifications_config(app)["default_title"] == "poolctl pi"
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["notifications"]["enabled"] is True
    assert saved["notifications"]["pushover"]["app_token_env"] == "POOL_PUSHOVER_TOKEN"
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
                "raw_ph": {
                    "channel": 6,
                    "calibration": {
                        "voltage_1": 0.0,
                        "value_1": 0.0,
                        "voltage_2": 5.0,
                        "value_2": 14.0,
                    },
                }
            },
        }
    }
    result = apply_analog_input_config_update(config_path=path, payload=payload)
    assert result["requires_restart"] is True

    serialized = serialize_analog_input_config(path)
    assert serialized["modbus_analog_input"]["sensors"]["raw_ph"]["channel"] == 6
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
    serialized = serialize_ph_sensor_config(path)
    assert serialized["modbus_ph_sensor"]["slave_id"] == 4


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


def test_health_payload_includes_status_fields() -> None:
    app = build_app_from_mapping(config_mapping(), clock=make_clock())
    payload = build_health_payload(app)
    assert payload["status"] in {"ok", "degraded"}
    assert "modbus" in payload
    assert "acquisition" in payload
    assert "mqtt" in payload
    assert "weather" in payload


def test_lab_test_api_helpers_store_and_list(tmp_path: Path) -> None:
    config = config_mapping()
    runtime = dict(config["runtime"])  # type: ignore[index]
    runtime["enabled_layers"] = ["pump_timer", "logging"]
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
    runtime["enabled_layers"] = ["pump_timer", "logging"]
    config["runtime"] = runtime
    config["logging"] = {"database_path": str(tmp_path / "fc-demand-feedback.sqlite3")}
    config["fc_demand"] = {
        "enabled": True,
        "mode": "automatic",
        "pool_volume_gal": 10000.0,
        "target_fc_ppm": 4.0,
        "chlorine_strength_percent": 12.0,
        "minimum_test_interval_hours": 12.0,
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
    assert round(second["fc_demand"]["catch_up_dose_oz_next_day"], 3) == 10.667
    assert second["fc_demand"]["next_adjustment_date"] == "2026-05-23"


def test_lab_test_api_accepts_sparse_payload_and_defaults_sampled_at(tmp_path: Path) -> None:
    config = config_mapping()
    runtime = dict(config["runtime"])  # type: ignore[index]
    runtime["enabled_layers"] = ["pump_timer", "logging"]
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


def test_chemical_addition_api_helpers_store_defaults_and_list(tmp_path: Path) -> None:
    config = config_mapping()
    runtime = dict(config["runtime"])  # type: ignore[index]
    runtime["enabled_layers"] = ["pump_timer", "logging"]
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
