"""
Tests for live dashboard snapshot generation.

The web UI consumes JSON-friendly dictionaries, so these tests verify display
values, colors, status flags, history data, and live controls.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import pytest

from poolctl.app import build_app_from_mapping
from poolctl.config import LiveViewConfig
from poolctl.domain.models import (
    ActuatorId,
    ActuatorState,
    ChemicalAddition,
    ChemicalType,
    LabTest,
    Measurement,
    Quality,
    SensorId,
)
from poolctl.services.clock import SimulatedClock
from poolctl.services.weather import WeatherObservation
from poolctl.web.live import (
    build_history_payload,
    build_history_series_payload,
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


class FixedSensor:
    def __init__(
        self,
        *,
        name: str,
        sensor_id: SensorId,
        clock: SimulatedClock,
        value: float,
        unit: str,
    ) -> None:
        self.name = name
        self.sensor_id = sensor_id
        self._clock = clock
        self._value = value
        self._unit = unit

    async def read(self) -> Measurement:
        return Measurement(
            sensor_id=self.sensor_id,
            observed_at=self._clock.now(),
            value=self._value,
            unit=self._unit,
            quality=Quality.GOOD,
            metadata={"driver": self.name},
        )


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
    assert snapshot["chlorination"]["layer_enabled"] is False
    assert snapshot["chlorination"]["daily_dose_oz"] == 0.0
    assert snapshot["chlorination"]["active"] is False
    assert snapshot["flows"]["pump_flow_gpm"]["display"] == "0.0 gpm"
    assert snapshot["flows"]["pump_dynamic_head_psi"]["display"] == "0.0 psi"
    assert snapshot["flows"]["return_flow_gpm"]["value"] == 0.0
    assert snapshot["flows"]["bubbler_flow_gpm"]["value"] == 0.0
    assert snapshot["flows"]["booster_flow_gpm"]["value"] == 0.0
    assert snapshot["flows"]["filter_restriction_metric"]["display"] == "-- R"
    assert snapshot["flows"]["filter_restriction_percent"]["display"] == "--%"
    assert snapshot["tick"]["duration_s"] >= 0.0
    assert snapshot["tick"]["control_duration_s"] >= 0.0


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
    flow_history = build_history_payload(
        app,
        sensor_id=SensorId.PUMP_FLOW_GPM,
        hours=1.0,
        limit=10,
    )
    dynamic_head_history = build_history_payload(
        app,
        sensor_id=SensorId.PUMP_DYNAMIC_HEAD_PSI,
        hours=1.0,
        limit=10,
    )
    return_flow_history = build_history_payload(
        app,
        sensor_id=SensorId.RETURN_FLOW_GPM,
        hours=1.0,
        limit=10,
    )

    assert snapshot["tick"]["logged_measurement_count"] == 8
    assert len(history["points"]) == 1
    assert history["points"][0]["sensor_id"] == SensorId.PUMP_OUTPUT_PSI.value
    assert len(flow_history["points"]) == 1
    assert flow_history["points"][0]["sensor_id"] == SensorId.PUMP_FLOW_GPM.value
    assert len(dynamic_head_history["points"]) == 1
    assert dynamic_head_history["points"][0]["sensor_id"] == SensorId.PUMP_DYNAMIC_HEAD_PSI.value
    assert len(return_flow_history["points"]) == 1
    assert return_flow_history["points"][0]["sensor_id"] == SensorId.RETURN_FLOW_GPM.value


@pytest.mark.asyncio
async def test_build_live_snapshot_includes_csi_when_inputs_are_available(
    tmp_path: Path,
) -> None:
    clock = make_clock()
    config = {
        "runtime": {
            "stage": "sensor_logging",
            "driver_profile": "simulated",
            "enabled_layers": ["acquisition", "logging", "safety_enforcement"],
            "enabled_actuators": [
                "pump_motor",
                "pump_motor_speed",
                "booster_pump",
                "chlorine_dosing_pump",
            ],
            "enabled_sensor_groups": ["chemistry_loop"],
        },
        "acquisition": {
            "groups": {
                "chemistry_loop": {
                    "sensor_ids": ["temp", "raw_ph"],
                    "read_interval_s": 1.0,
                    "log_interval_s": 1.0,
                    "requires_pump_flow": False,
                    "oversample": {
                        "sample_count": 1,
                        "sample_interval_s": 0.0,
                        "reducer": "last",
                    },
                }
            }
        },
        "logging": {"database_path": str(tmp_path / "history.sqlite3")},
        "live_view": {
            "sensor_limits": {
                "calcium_saturation_index": {
                    "caution_min": -0.6,
                    "normal_min": -0.3,
                    "normal_max": 0.3,
                    "caution_max": 0.6,
                }
            }
        },
    }
    app = build_app_from_mapping(
        config,
        clock=clock,
        sensor_drivers=[
            FixedSensor(name="temp_sensor", sensor_id=SensorId.TEMP, clock=clock, value=84.0, unit="degF"),
            FixedSensor(name="ph_sensor", sensor_id=SensorId.RAW_PH, clock=clock, value=7.5, unit="pH"),
        ],
    )
    assert app.measurement_logger is not None
    app.measurement_logger.log_lab_test(LabTest(sampled_at=clock.now(), calcium_hardness=300.0))
    app.measurement_logger.log_lab_test(LabTest(sampled_at=clock.now(), alkalinity=100.0))
    app.measurement_logger.log_lab_test(LabTest(sampled_at=clock.now(), tds=1000.0))

    snapshot = await build_live_snapshot(app)

    csi = snapshot["sensors"][SensorId.CALCIUM_SATURATION_INDEX.value]
    assert csi["label"] == "CSI"
    assert csi["unit"] == "csi"


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
    assert (
        format_measurement(
            Measurement(sensor_id=SensorId.DAILY_UV_INDEX_DOSE, value=31.25, unit="index-hour")
        )
        == "31.2 index-hour"
    )
    assert (
        format_measurement(
            Measurement(
                sensor_id=SensorId.DAILY_SHORTWAVE_RADIATION_DOSE,
                value=6132.4,
                unit="Wh/m2",
            )
        )
        == "6132 Wh/m2"
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


def test_history_payload_can_use_past_until_window(tmp_path: Path) -> None:
    app = build_app_from_mapping(
        logging_live_config(str(tmp_path / "history.sqlite3")),
        clock=make_clock(),
    )
    assert app.measurement_logger is not None
    now = app.clock.now()
    past_until = now - timedelta(days=30)
    past_sample = past_until - timedelta(hours=2)

    app.measurement_logger.log_measurements(
        (
            Measurement(
                sensor_id=SensorId.PUMP_OUTPUT_PSI,
                observed_at=past_sample,
                value=11.0,
                unit="psi",
                quality=Quality.GOOD,
            ),
            Measurement(
                sensor_id=SensorId.PUMP_OUTPUT_PSI,
                observed_at=now,
                value=22.0,
                unit="psi",
                quality=Quality.GOOD,
            ),
        )
    )

    payload = build_history_payload(
        app,
        sensor_id=SensorId.PUMP_OUTPUT_PSI,
        hours=24.0,
        limit=20,
        until=past_until,
    )

    assert payload["since"] == (past_until - timedelta(hours=24)).isoformat()
    assert payload["until"] == past_until.isoformat()
    assert [point["value"] for point in payload["points"]] == [11.0]


def test_history_series_payload_can_include_lab_test_signals(tmp_path: Path) -> None:
    app = build_app_from_mapping(
        logging_live_config(str(tmp_path / "history.sqlite3")),
        clock=make_clock(),
    )
    assert app.measurement_logger is not None
    sampled_at = app.clock.now()
    app.measurement_logger.log_lab_test(
        LabTest(
            sampled_at=sampled_at,
            ph=7.55,
            free_chlorine=3.2,
            alkalinity=95.0,
            calcium_hardness=280.0,
            cya=45.0,
            tds=1000.0,
            salt=3100.0,
            borates=35.0,
        )
    )

    payload = build_history_series_payload(
        app,
        sensor_ids=(
            "lab_ph",
            "lab_free_chlorine",
            "lab_alkalinity",
            "lab_calcium_hardness",
            "lab_cya",
            "lab_tds",
            "lab_salt",
            "lab_borates",
        ),
        hours=24.0,
        limit=100,
        validated_only=True,
    )

    by_id = {series["sensor_id"]: series for series in payload["series"]}
    assert by_id["lab_ph"]["points"][0]["value"] == 7.55
    assert by_id["lab_free_chlorine"]["points"][0]["value"] == 3.2
    assert by_id["lab_alkalinity"]["points"][0]["value"] == 95.0
    assert by_id["lab_calcium_hardness"]["points"][0]["value"] == 280.0
    assert by_id["lab_cya"]["points"][0]["value"] == 45.0
    assert by_id["lab_tds"]["points"][0]["value"] == 1000.0
    assert by_id["lab_salt"]["points"][0]["value"] == 3100.0
    assert by_id["lab_borates"]["points"][0]["value"] == 35.0


def test_history_series_payload_can_include_chemical_addition_events(tmp_path: Path) -> None:
    app = build_app_from_mapping(
        logging_live_config(str(tmp_path / "history.sqlite3")),
        clock=make_clock(),
    )
    assert app.measurement_logger is not None
    added_at = app.clock.now()
    app.measurement_logger.log_chemical_addition(
        ChemicalAddition(
            added_at=added_at,
            chemical=ChemicalType.MURIATIC_ACID,
            amount=1.0,
            unit="gal",
            amount_fl_oz=128.0,
            strength_percent=31.45,
        )
    )

    payload = build_history_series_payload(
        app,
        sensor_ids=("chemical_muriatic_acid",),
        hours=24.0,
        limit=100,
        validated_only=True,
    )

    series = payload["series"][0]
    assert series["sensor_id"] == "chemical_muriatic_acid"
    assert series["style"] == "event"
    assert series["marker"] == "square"
    assert series["points"][0]["value"] == 128.0
    assert series["points"][0]["kind"] == "event"
    assert series["points"][0]["metadata"]["source"] == "chemical_addition"


def test_history_series_payload_accepts_multiple_standard_sensor_id_strings(tmp_path: Path) -> None:
    app = build_app_from_mapping(
        logging_live_config(str(tmp_path / "history.sqlite3")),
        clock=make_clock(),
    )
    assert app.measurement_logger is not None

    now = app.clock.now()
    app.measurement_logger.log_measurements(
        (
            Measurement(
                sensor_id=SensorId.PUMP_OUTPUT_PSI,
                observed_at=now,
                value=12.0,
                unit="psi",
                quality=Quality.GOOD,
            ),
            Measurement(
                sensor_id=SensorId.FILTER_OUTPUT_PSI,
                observed_at=now,
                value=9.5,
                unit="psi",
                quality=Quality.GOOD,
            ),
        )
    )

    payload = build_history_series_payload(
        app,
        sensor_ids=("pump_output_psi", "filter_output_psi"),
        hours=24.0,
        limit=100,
        validated_only=True,
    )

    by_id = {series["sensor_id"]: series for series in payload["series"]}
    assert by_id["pump_output_psi"]["points"][0]["value"] == 12.0
    assert by_id["filter_output_psi"]["points"][0]["value"] == 9.5


def test_history_series_payload_can_include_weather_signals(tmp_path: Path) -> None:
    app = build_app_from_mapping(
        logging_live_config(str(tmp_path / "history.sqlite3")),
        clock=make_clock(),
    )
    assert app.measurement_logger is not None
    observed_at = app.clock.now()
    app.measurement_logger.log_weather_observation(
        WeatherObservation(
            observed_at=observed_at,
            source="open-meteo",
            latitude=29.75,
            longitude=-95.35,
            values={
                "temperature_2m": 83.1,
                "cloud_cover": 45.0,
                "precipitation": 0.03,
                "uv_index": 6.2,
            },
            units_by_field={
                "temperature_2m": "degF",
                "cloud_cover": "%",
                "precipitation": "in",
                "uv_index": "index",
            },
        )
    )

    payload = build_history_series_payload(
        app,
        sensor_ids=(
            "weather_temperature_2m",
            "weather_cloud_cover",
            "weather_precipitation",
            "weather_uv_index",
        ),
        hours=24.0,
        limit=100,
        validated_only=True,
    )

    by_id = {series["sensor_id"]: series for series in payload["series"]}
    assert by_id["weather_temperature_2m"]["points"][0]["value"] == 83.1
    assert by_id["weather_cloud_cover"]["points"][0]["value"] == 45.0
    assert by_id["weather_precipitation"]["points"][0]["value"] == 0.03
    assert by_id["weather_uv_index"]["points"][0]["value"] == 6.2
