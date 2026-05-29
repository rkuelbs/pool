from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from poolctl.app import build_app_from_mapping
from poolctl.services.clock import SimulatedClock
from poolctl.web.server import (
    add_lab_test,
    apply_analog_input_config_update,
    apply_acquisition_config_update,
    apply_logging_config_update,
    apply_pump_timer_config_update,
    apply_runtime_config_update,
    apply_safety_config_update,
    apply_timer_override_update,
    build_health_payload,
    list_lab_tests,
    serialize_acquisition_config,
    serialize_logging_config,
    serialize_analog_input_config,
    serialize_pump_timer_config,
    serialize_runtime_config,
    serialize_safety_config,
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
