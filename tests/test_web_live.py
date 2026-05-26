from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import pytest

from poolctl.app import build_app_from_mapping
from poolctl.config import LiveViewConfig
from poolctl.domain.models import ActuatorId, ActuatorState, Measurement, Quality, SensorId
from poolctl.services.clock import SimulatedClock
from poolctl.web.live import (
    build_history_payload,
    build_live_snapshot,
    format_measurement,
    measurement_status,
)
from poolctl.web.server import route_command


def make_clock() -> SimulatedClock:
    return SimulatedClock(
        start_at=datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc),
        speedup=3600.0,
    )


def live_config() -> dict[str, object]:
    return {
        "runtime": {
            "stage": "windows_simulation",
            "driver_profile": "simulated",
            "enabled_layers": ["acquisition", "safety_enforcement"],
            "enabled_actuators": [
                "pump_motor",
                "pump_motor_speed",
                "booster_pump",
                "chlorine_dosing_pump",
            ],
            "enabled_sensor_groups": ["pressures"],
        },
        "acquisition": {
            "groups": {
                "pressures": {
                    "sensor_ids": [
                        "pump_output_psi",
                        "filter_output_psi",
                        "return_psi",
                    ],
                    "read_interval_s": 0.5,
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
        "live_view": {
            "sensor_limits": {
                "pump_output_psi": {
                    "caution_min": 0.0,
                    "normal_min": 0.0,
                    "normal_max": 25.0,
                    "caution_max": 30.0,
                },
                "return_psi": {
                    "caution_min": 0.0,
                    "normal_min": 0.0,
                    "normal_max": 18.0,
                    "caution_max": 25.0,
                },
            }
        },
    }


def logging_live_config(database_path: str) -> dict[str, object]:
    config = live_config()
    runtime = dict(cast(dict[str, Any], config["runtime"]))
    runtime["enabled_layers"] = ["acquisition", "logging", "safety_enforcement"]
    config["runtime"] = runtime
    config["logging"] = {"database_path": database_path}
    return config


def control_config() -> dict[str, object]:
    return {
        "runtime": {
            "stage": "windows_simulation",
            "driver_profile": "simulated",
            "enabled_layers": ["safety_enforcement"],
            "enabled_actuators": [
                "pump_motor",
                "pump_motor_speed",
                "booster_pump",
                "chlorine_dosing_pump",
            ],
            "enabled_sensor_groups": [],
        },
    }


@pytest.mark.asyncio
async def test_build_live_snapshot_includes_runtime_sensors_and_actuators() -> None:
    app = build_app_from_mapping(live_config(), clock=make_clock())

    snapshot = await build_live_snapshot(app)

    assert snapshot["runtime"]["stage"] == "windows_simulation"
    assert snapshot["runtime"]["driver_profile"] == "simulated"
    assert SensorId.PUMP_OUTPUT_PSI.value in snapshot["sensors"]
    assert snapshot["sensors"][SensorId.PUMP_OUTPUT_PSI.value]["unit"] == "psi"
    assert snapshot["sensors"][SensorId.PUMP_OUTPUT_PSI.value]["quality"] == "good"
    assert snapshot["sensors"][SensorId.PUMP_OUTPUT_PSI.value]["status"] == "normal"
    assert "pump_motor" in snapshot["actuators"]
    assert snapshot["safety"]["locked_out"] is False
    assert snapshot["safety"]["fault"] is None
    assert snapshot["safety"]["freeze_protection"]["enabled"] is False
    assert snapshot["safety"]["freeze_protection"]["active"] is False
    assert snapshot["flows"]["pump_flow_gpm"]["display"] == "0.0 gpm"
    assert snapshot["flows"]["booster_flow_gpm"]["value"] is None


@pytest.mark.asyncio
async def test_build_live_snapshot_reuses_latest_measurements_when_group_not_due() -> None:
    app = build_app_from_mapping(live_config(), clock=make_clock())

    first = await build_live_snapshot(app)
    second = await build_live_snapshot(app)

    assert first["tick"]["measurement_count"] == 3
    assert second["tick"]["measurement_count"] == 0
    assert SensorId.RETURN_PSI.value in second["sensors"]


@pytest.mark.asyncio
async def test_build_live_snapshot_logs_loggable_measurements(tmp_path: Path) -> None:
    app = build_app_from_mapping(
        logging_live_config(str(tmp_path / "history.sqlite3")),
        clock=make_clock(),
    )

    snapshot = await build_live_snapshot(app)
    history = build_history_payload(
        app,
        sensor_id=SensorId.PUMP_OUTPUT_PSI,
        hours=1.0,
        limit=10,
    )

    assert snapshot["tick"]["logged_measurement_count"] == 3
    assert len(history["points"]) == 1
    assert history["points"][0]["sensor_id"] == SensorId.PUMP_OUTPUT_PSI.value


@pytest.mark.asyncio
async def test_route_command_applies_dashboard_actuator_command() -> None:
    app = build_app_from_mapping(control_config(), clock=make_clock())

    result = await route_command(
        app,
        {
            "actuator_id": "pump_motor",
            "state": "on",
        },
    )

    assert result["accepted"] is True
    assert result["applied"] is True
    assert app.router.actuator_states[ActuatorId.PUMP_MOTOR] == ActuatorState.ON


@pytest.mark.asyncio
async def test_route_command_rejects_invalid_payload() -> None:
    app = build_app_from_mapping(control_config(), clock=make_clock())

    with pytest.raises(ValueError):
        await route_command(
            app,
            {
                "actuator_id": "pump_motor",
                "state": "banana",
            },
        )


def test_format_measurement_uses_domain_units() -> None:
    assert (
        format_measurement(
            Measurement(sensor_id=SensorId.PUMP_OUTPUT_PSI, value=12.34, unit="psi")
        )
        == "12.3 psi"
    )
    assert (
        format_measurement(Measurement(sensor_id=SensorId.RAW_PH, value=7.892, unit="pH"))
        == "7.89"
    )
    assert (
        format_measurement(Measurement(sensor_id=SensorId.TANK_LEVEL, value=87.4, unit="percent"))
        == "87%"
    )


def test_measurement_status_uses_configured_display_bands() -> None:
    config = LiveViewConfig.from_mapping(
        {
            "live_view": {
                "sensor_limits": {
                    "pump_output_psi": {
                        "caution_min": 1.0,
                        "normal_min": 6.0,
                        "normal_max": 25.0,
                        "caution_max": 30.0,
                    }
                }
            }
        }
    )

    assert (
        measurement_status(
            SensorId.PUMP_OUTPUT_PSI,
            Measurement(sensor_id=SensorId.PUMP_OUTPUT_PSI, value=12.0, unit="psi"),
            config,
        )
        == "normal"
    )
    assert (
        measurement_status(
            SensorId.PUMP_OUTPUT_PSI,
            Measurement(sensor_id=SensorId.PUMP_OUTPUT_PSI, value=3.0, unit="psi"),
            config,
        )
        == "caution"
    )
    assert (
        measurement_status(
            SensorId.PUMP_OUTPUT_PSI,
            Measurement(sensor_id=SensorId.PUMP_OUTPUT_PSI, value=31.0, unit="psi"),
            config,
        )
        == "alarm"
    )
    assert (
        measurement_status(
            SensorId.PUMP_OUTPUT_PSI,
            Measurement(
                sensor_id=SensorId.PUMP_OUTPUT_PSI,
                value=12.0,
                unit="psi",
                quality=Quality.SUSPECT,
            ),
            config,
        )
        == "invalid"
    )


def test_history_payload_can_filter_to_validated_measurements(tmp_path: Path) -> None:
    app = build_app_from_mapping(
        logging_live_config(str(tmp_path / "history.sqlite3")),
        clock=make_clock(),
    )
    assert app.measurement_logger is not None

    app.measurement_logger.log_measurements(
        (
            Measurement(
                sensor_id=SensorId.PUMP_OUTPUT_PSI,
                observed_at=app.clock.now(),
                value=12.0,
                unit="psi",
                quality=Quality.GOOD,
            ),
            Measurement(
                sensor_id=SensorId.PUMP_OUTPUT_PSI,
                observed_at=app.clock.now(),
                value=0.0,
                unit="psi",
                quality=Quality.SUSPECT,
            ),
        )
    )

    validated = build_history_payload(
        app,
        sensor_id=SensorId.PUMP_OUTPUT_PSI,
        hours=1.0,
        limit=20,
        validated_only=True,
    )
    raw = build_history_payload(
        app,
        sensor_id=SensorId.PUMP_OUTPUT_PSI,
        hours=1.0,
        limit=20,
        validated_only=False,
    )

    assert all(point["quality"] == "good" for point in validated["points"])
    assert any(point["quality"] == "suspect" for point in raw["points"])
