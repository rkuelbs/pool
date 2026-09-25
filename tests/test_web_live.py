"""
Tests for live dashboard snapshot generation.

The web UI consumes JSON-friendly dictionaries, so these tests verify display
values, colors, status flags, history data, and live controls.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from poolctl.app import build_app_from_mapping
from poolctl.config import MonitoringConfig
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
from poolctl.drivers.base import SensorReadError
from poolctl.services.clock import SimulatedClock
from poolctl.services.pump_timer import PumpTimerOverride
from poolctl.services.weather import WeatherObservation
from poolctl.web.live import (
    build_history_payload,
    build_history_series_payload,
    build_live_snapshot,
    chlorine_supply_payload,
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
        "pool": {
            "name": "Test Pool",
            "volume_gal": 12000.0,
        },
        "runtime": {
            "driver_profile": "simulated",
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
            }
        },
    }


def logging_live_config(database_path: str) -> dict[str, object]:
    config = live_config()
    config["logging"] = {"database_path": database_path}
    return config


def control_config() -> dict[str, object]:
    return {
        "runtime": {
            "driver_profile": "simulated",
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


class FailAfterFirstSensor(FixedSensor):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._read_count = 0

    async def read(self) -> Measurement:
        self._read_count += 1
        if self._read_count > 1:
            raise SensorReadError("probe timeout")
        return await super().read()


@pytest.mark.asyncio
async def test_build_live_snapshot_includes_runtime_sensors_and_actuators() -> None:
    clock = make_clock()
    pressure = FixedSensor(
        name="pressure",
        sensor_id=SensorId.PUMP_OUTPUT_PSI,
        clock=clock,
        value=5.0,
        unit="psi",
    )
    app = build_app_from_mapping(
        live_config(),
        clock=clock,
        sensor_drivers=[pressure],
    )

    snapshot = await build_live_snapshot(app)

    assert snapshot["pool"]["name"] == "Test Pool"
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
    assert snapshot["chlorination"]["daily_dose_oz"] == 0.0
    assert snapshot["chlorination"]["active"] is False
    assert snapshot["supplemental_chlorine_dose"]["active"] is False
    assert snapshot["flows"]["pump_flow_gpm"]["display"] == "0.0 gpm"
    assert snapshot["flows"]["pump_dynamic_head_psi"]["display"] == "0.0 psi"
    assert snapshot["flows"]["pump_flow_low_gpm"]["display"] == "0.0 gpm"
    assert snapshot["flows"]["pump_flow_high_gpm"]["display"] == "-- gpm"
    assert snapshot["flows"]["filter_reference_psi"]["display"] == "-- psi"
    assert snapshot["flows"]["filter_reference_flow_gpm"]["display"] == "-- gpm"
    assert snapshot["flows"]["filter_flow_loss_percent"]["display"] == "--"
    assert snapshot["tick"]["duration_s"] >= 0.0
    assert snapshot["tick"]["control_duration_s"] >= 0.0


@pytest.mark.asyncio
async def test_live_schedule_includes_trimmed_dosing_windows() -> None:
    config = control_config()
    config["site"] = {"timezone": "UTC"}
    config["pump_timer"] = {
        "active_profile": "normal",
        "profiles": [
            {
                "name": "normal",
                "schedules": [
                    {
                        "name": "daytime_dosing",
                        "timing": {
                            "type": "fixed",
                            "start": "08:00",
                            "end": "12:00",
                        },
                        "pump_speed": "low",
                        "booster": "off",
                        "allow_dosing": True,
                    }
                ],
            }
        ],
    }
    config["chlorination"] = {
        "no_dose_first_minutes": 10.0,
        "no_dose_last_minutes": 10.0,
    }
    app = build_app_from_mapping(config, clock=make_clock())

    snapshot = await build_live_snapshot(app)

    assert snapshot["schedule"]["today"]["windows"][0]["start"] == (
        "2026-05-21T08:00:00+00:00"
    )
    assert snapshot["schedule"]["today"]["windows"][0]["end"] == (
        "2026-05-21T12:00:00+00:00"
    )
    assert snapshot["schedule"]["today"]["dosing_windows"] == [
        {
            "start": "2026-05-21T08:10:00+00:00",
            "end": "2026-05-21T11:50:00+00:00",
        }
    ]


@pytest.mark.asyncio
async def test_build_live_snapshot_reuses_latest_measurements_when_group_not_due() -> None:
    app = build_app_from_mapping(live_config(), clock=make_clock())

    first = await build_live_snapshot(app)
    second = await build_live_snapshot(app)

    assert first["tick"]["measurement_count"] == 1
    assert second["tick"]["measurement_count"] == 0
    assert SensorId.PUMP_OUTPUT_PSI.value in second["sensors"]


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
    delivered_history = build_history_payload(
        app,
        sensor_id=SensorId.CHLORINE_DAILY_DELIVERED_OZ,
        hours=24.0,
        limit=10,
    )
    daily_chlorine_history = build_history_payload(
        app,
        sensor_id=SensorId.DAILY_SODIUM_HYPOCHLORITE_ADDED_OZ,
        hours=24.0,
        limit=10,
    )
    daily_chlorine_7d_history = build_history_payload(
        app,
        sensor_id=SensorId.DAILY_SODIUM_HYPOCHLORITE_ADDED_OZ_7D_AVG,
        hours=24.0,
        limit=10,
    )
    daily_acid_history = build_history_payload(
        app,
        sensor_id=SensorId.DAILY_MURIATIC_ACID_ADDED_OZ,
        hours=24.0,
        limit=10,
    )

    assert snapshot["tick"]["logged_measurement_count"] == 10
    assert len(history["points"]) == 1
    assert history["points"][0]["sensor_id"] == SensorId.PUMP_OUTPUT_PSI.value
    assert len(flow_history["points"]) == 1
    assert flow_history["points"][0]["sensor_id"] == SensorId.PUMP_FLOW_GPM.value
    assert len(dynamic_head_history["points"]) == 1
    assert dynamic_head_history["points"][0]["sensor_id"] == SensorId.PUMP_DYNAMIC_HEAD_PSI.value
    assert delivered_history["points"][0]["value"] == 0.0
    assert delivered_history["points"][0]["metadata"]["snapshot_boundary"] == "reset"
    assert daily_chlorine_history["points"][0]["value"] == 0.0
    assert daily_chlorine_7d_history["points"][0]["value"] == 0.0
    assert daily_acid_history["points"][0]["value"] == 0.0


@pytest.mark.asyncio
async def test_build_live_snapshot_includes_csi_when_inputs_are_available(
    tmp_path: Path,
) -> None:
    clock = make_clock()
    config = {
        "runtime": {
            "driver_profile": "simulated",
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
                    "sensor_ids": ["ph_temp", "raw_ph"],
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
            FixedSensor(
                name="temp_sensor",
                sensor_id=SensorId.PH_TEMP,
                clock=clock,
                value=84.0,
                unit="degF",
            ),
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
async def test_live_snapshot_uses_canonical_ph_then_orp_water_temperature() -> None:
    clock = make_clock()
    config = {
        "runtime": {
            "driver_profile": "simulated",
            "enabled_actuators": [],
            "enabled_sensor_groups": ["chemistry_loop"],
        },
        "acquisition": {
            "groups": {
                "chemistry_loop": {
                    "sensor_ids": ["ph_temp", "orp_temp"],
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
    }
    ph = FixedSensor(
        name="ph_temp",
        sensor_id=SensorId.PH_TEMP,
        clock=clock,
        value=82.0,
        unit="degF",
    )
    orp = FixedSensor(
        name="orp_temp",
        sensor_id=SensorId.ORP_TEMP,
        clock=clock,
        value=81.0,
        unit="degF",
    )
    app = build_app_from_mapping(config, clock=clock, sensor_drivers=[ph, orp])

    snapshot = await build_live_snapshot(app)

    water = snapshot["sensors"][SensorId.WATER_TEMP.value]
    assert water["value"] == 82.0
    assert water["metadata"]["active_source"] == SensorId.PH_TEMP.value
    assert water["availability"]["state"] == "current"
    assert water["threshold"] == {
        "configured": False,
        "state": None,
        "label": "Not configured",
    }

    acquisition = config["acquisition"]
    assert isinstance(acquisition, dict)
    groups = acquisition["groups"]
    assert isinstance(groups, dict)
    chemistry = groups["chemistry_loop"]
    assert isinstance(chemistry, dict)
    chemistry["sensor_ids"] = ["orp_temp"]
    fallback_app = build_app_from_mapping(config, clock=clock, sensor_drivers=[orp])
    fallback_snapshot = await build_live_snapshot(fallback_app)
    fallback = fallback_snapshot["sensors"][SensorId.WATER_TEMP.value]
    assert fallback["value"] == 81.0
    assert fallback["metadata"]["active_source"] == SensorId.ORP_TEMP.value

    runtime = config["runtime"]
    assert isinstance(runtime, dict)
    runtime["enabled_sensor_groups"] = []
    unavailable_app = build_app_from_mapping(config, clock=clock, sensor_drivers=[])
    unavailable = (await build_live_snapshot(unavailable_app))["sensors"]["water_temp"]
    assert unavailable["value"] is None
    assert unavailable["availability"]["state"] == "unavailable"


@pytest.mark.asyncio
async def test_circulation_dependent_kpi_distinguishes_off_settling_and_history(
    tmp_path: Path,
) -> None:
    clock = make_clock()
    config = {
        "runtime": {
            "driver_profile": "simulated",
            "enabled_actuators": ["pump_motor", "pump_motor_speed"],
            "enabled_sensor_groups": ["chemistry_loop"],
        },
        "logging": {"database_path": str(tmp_path / "availability.sqlite3")},
        "safety": {"timeouts": {"pump_prime_timeout_s": 600}},
        "acquisition": {
            "groups": {
                "chemistry_loop": {
                    "sensor_ids": ["raw_ph"],
                    "read_interval_s": 1,
                    "log_interval_s": 1,
                    "requires_pump_flow": True,
                    "min_pump_on_seconds": 60,
                }
            }
        },
    }
    sensor = FixedSensor(
        name="ph",
        sensor_id=SensorId.RAW_PH,
        clock=clock,
        value=7.5,
        unit="pH",
    )
    app = build_app_from_mapping(config, clock=clock, sensor_drivers=[sensor])

    off = await build_live_snapshot(app)
    assert off["sensors"]["raw_ph"]["availability"]["state"] == "pump_off"

    app.set_timer_override(
        PumpTimerOverride(
            pump_motor=ActuatorState.ON,
            pump_speed=ActuatorState.LOW,
        ),
        duration_s=600,
    )
    await clock.advance(1)
    settling = await build_live_snapshot(app)
    assert settling["sensors"]["raw_ph"]["availability"]["state"] == "settling"

    await clock.advance(60)
    current = await build_live_snapshot(app)
    assert current["sensors"]["raw_ph"]["availability"]["state"] == "current"

    app.set_timer_override(
        PumpTimerOverride(
            pump_motor=ActuatorState.OFF,
            pump_speed=ActuatorState.LOW,
        ),
        duration_s=600,
    )
    await clock.advance(1)
    historical = await build_live_snapshot(app)
    ph = historical["sensors"]["raw_ph"]
    assert ph["availability"]["state"] == "pump_off"
    assert ph["last_valid"]["value"] == 7.5
    assert ph["threshold"]["state"] is None


@pytest.mark.asyncio
async def test_stale_retained_reading_keeps_sensor_failure_visible(tmp_path: Path) -> None:
    clock = make_clock()
    config = {
        "runtime": {
            "driver_profile": "simulated",
            "enabled_actuators": [],
            "enabled_sensor_groups": ["chemistry_loop"],
        },
        "logging": {"database_path": str(tmp_path / "stale.sqlite3")},
        "acquisition": {
            "groups": {
                "chemistry_loop": {
                    "sensor_ids": ["raw_orp"],
                    "read_interval_s": 1,
                    "log_interval_s": 1,
                    "requires_pump_flow": False,
                }
            }
        },
    }
    sensor = FailAfterFirstSensor(
        name="orp",
        sensor_id=SensorId.RAW_ORP,
        clock=clock,
        value=720,
        unit="mV",
    )
    app = build_app_from_mapping(config, clock=clock, sensor_drivers=[sensor])
    first = await build_live_snapshot(app)
    assert first["sensors"]["raw_orp"]["availability"]["state"] == "current"

    await clock.advance(16)
    second = await build_live_snapshot(app)
    orp = second["sensors"]["raw_orp"]
    assert orp["availability"]["state"] == "stale"
    assert orp["fault"]["message"] == "probe timeout"
    assert orp["threshold"]["state"] is None


@pytest.mark.asyncio
async def test_build_live_snapshot_includes_chlorine_tank_estimate(
    tmp_path: Path,
) -> None:
    clock = make_clock()
    config = logging_live_config(str(tmp_path / "tank.sqlite3"))
    config["chlorination"] = {"daily_dose_oz": 64.0}
    app = build_app_from_mapping(
        config,
        clock=clock,
    )
    assert app.measurement_logger is not None
    now = clock.now()
    app.measurement_logger.log_lab_test(
        LabTest(
            sampled_at=now - timedelta(hours=1),
            chlorine_tank_level_gal=10.0,
        )
    )
    app.measurement_logger.log_chlorine_delivery(
        observed_at=now - timedelta(minutes=30),
        runtime_seconds=60.0,
        delivered_oz=64.0,
    )

    snapshot = await build_live_snapshot(app)
    tank = snapshot["sensors"][SensorId.CHLORINE_TANK_LEVEL_GAL.value]

    assert tank["label"] == "Chlorine tank level"
    assert tank["value"] == 9.5
    assert tank["display"] == "9.50 gal"
    assert snapshot["chlorine_supply"]["tank_level_gal"] == 9.5
    assert snapshot["chlorine_supply"]["remaining_gal"] == 7.5
    assert snapshot["chlorine_supply"]["usable_remaining_gal"] == 7.5
    assert snapshot["chlorine_supply"]["reserve_gal"] == 2.0
    assert snapshot["chlorine_supply"]["days_remaining"] == 15.0
    assert snapshot["chlorine_supply"]["status"] == "normal"
    assert snapshot["chlorine_supply"]["display"] == (
        "Usable chlorine remaining 7.50 gallons, 15.0 days"
    )


@pytest.mark.parametrize(
    ("daily_dose_oz", "expected_days", "expected_status"),
    [
        (128.0, 6.0, "caution"),
        (256.0, 3.0, "alarm"),
        (512.0, 1.5, "alarm"),
        (0.0, None, "unknown"),
    ],
)
def test_chlorine_supply_payload_calculates_days_and_status(
    daily_dose_oz: float,
    expected_days: float | None,
    expected_status: str,
) -> None:
    payload = chlorine_supply_payload(
        tank_measurement=Measurement(
            sensor_id=SensorId.CHLORINE_TANK_LEVEL_GAL,
            observed_at=make_clock().now(),
            value=8.0,
            unit="gal",
            quality=Quality.GOOD,
        ),
        daily_dose_oz=daily_dose_oz,
        monitoring_config=MonitoringConfig.from_mapping({}),
    )

    assert payload["days_remaining"] == expected_days
    assert payload["status"] == expected_status


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
            Measurement(
                sensor_id=SensorId.CHLORINE_TANK_LEVEL_GAL,
                value=9.5,
                unit="gal",
            )
        )
        == "9.50 gal"
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
    assert (
        format_measurement(
            Measurement(
                sensor_id=SensorId.DAILY_SODIUM_HYPOCHLORITE_ADDED_OZ,
                value=12.25,
                unit="fl oz",
            )
        )
        == "12.2 fl oz"
    )


def test_measurement_status_uses_canonical_monitoring_limits() -> None:
    config = MonitoringConfig.from_mapping(
        {
            "monitoring": {
                "limits": {
                    "pump_output_psi": {
                        "alarm_below": 1.0,
                        "caution_below": 6.0,
                        "caution_above": 25.0,
                        "alarm_above": 30.0,
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


def test_live_dashboard_preserves_control_hooks_and_product_sections() -> None:
    static_dir = Path(__file__).parents[1] / "src" / "poolctl" / "web" / "static"
    markup = (static_dir / "live.html").read_text(encoding="utf-8")
    history_markup = (static_dir / "history.html").read_text(encoding="utf-8")
    script = (static_dir / "app.js").read_text(encoding="utf-8")
    styles = (static_dir / "styles.css").read_text(encoding="utf-8")
    element_ids = re.findall(r'\bid="([^"]+)"', markup)

    assert len(element_ids) == len(set(element_ids))
    assert {
        "controllerBadge",
        "liveCardPanel",
        "liveControlsCard",
        "liveTrendCharts",
        "todayTimeline",
        "attentionList",
        "liveScheduleProfile",
        "liveOverrideResumeSchedule",
        "liveSupplementalChlorineDoseStart",
        "liveSupplementalConfirm",
        "liveSupplementalConfirmStart",
        "chemicalAdditionSave",
        "labTestSave",
        "labFreeChlorine",
        "labCombinedChlorine",
        "labTotalChlorine",
        "labAlkalinity",
        "labCya",
        "labCalciumHardness",
        "labTds",
        "labSalt",
        "labBorates",
        "labWaterTemp",
        "labChlorineTankLevelGal",
        "chlorineTankRefillSave",
        "chlorineTankRefillAmountGal",
        "liveTrendFc",
    }.issubset(element_ids)
    assert markup.count('class="kpi-card"') == 6
    assert 'data-command="pump_motor:on"' in markup
    assert 'data-command="pump_motor:off"' in markup
    assert 'data-command="pump_motor_speed:low"' in markup
    assert 'data-command="pump_motor_speed:high"' in markup
    assert 'data-command="booster_pump:on"' in markup
    assert 'data-command="booster_pump:off"' in markup
    assert "Quick actions" not in markup
    assert "Run high for 1 hour" not in markup
    assert "Common task" not in markup
    assert 'id="liveOverridePumpOnHour"' not in markup
    assert "schedule-window-chip" not in markup
    assert 'id="todaySolar"' not in markup
    assert 'data-live-trend="lab_free_chlorine"' in markup
    assert 'id="liveTrendsStatus" class="sr-only"' in markup
    assert '<option value="muriatic_acid" selected>' in markup
    assert 'id="chemicalAdditionSave"' not in history_markup
    assert 'id="chlorineTankRefillSave"' not in history_markup
    assert 'id="labTestSave"' not in history_markup
    assert 'const HISTORY_CATEGORY_ORDER = [' in script
    assert '"filter_loading_percent",' not in script
    assert '<h2 id="todayHeading">Schedule</h2>' in markup
    assert markup.index('class="dashboard-card today-card"') < markup.index('id="liveCardPanel"')
    assert markup.index('id="liveScheduleProfile"') > markup.index('id="liveControlsCard"')
    assert 'aria-label="Filter flow loss, last 30 days"' in markup
    assert 'aria-label="Usable chlorine supply, past 7 days"' in markup
    assert "openSupplementalChlorineConfirmation(inputId)" in script
    assert 'fetch("/api/live"' in script
    assert 'const poolName = payload.pool ? String(payload.pool.name || "").trim() : "";' in script
    assert 'runtimeLine.textContent = poolName || `${profile.replaceAll("_", " ")} controller`;' in script
    assert "const kpiGroups = new Map();" in script
    assert "const LIVE_SHORT_KPI_HISTORY_HOURS = 24;" in script
    assert "const LIVE_LONG_KPI_HISTORY_HOURS = 24 * 30;" in script
    assert "const LIVE_TREND_HISTORY_HOURS = 168;" in script
    assert 'const LIVE_CHLORINE_DELIVERY_SENSOR_ID = "chlorine_daily_delivered_oz";' in script
    assert 'sensorId: "lab_free_chlorine"' in script
    assert "integratedFlowGallons(points, historyWindow)" in script
    assert "cumulativeCounterIncrease(chlorineDeliveryPoints)" in script
    assert "(totalOunces / 128).toFixed(2)" in script
    assert "percentage points over" in script
    assert "definition.historyHours = hours" in script
    assert "sparkline-clipped-label" in script
    assert "fcLinePointsWithBoundary" in script
    assert "actualMarkers" in script
    assert 'chart.getBoundingClientRect()' in script
    assert "const dosingWindows = Array.isArray(today.dosing_windows)" in script
    assert 'appendScheduleSegment(scheduleTrack, window, "dosing", "Dosing"' in script
    assert 'return { className: "vacuum", label: "Vacuum" };' in script
    assert ".live-dashboard > .today-card" in styles
    assert ".live-dashboard > .kpi-grid" in styles
    assert ".timeline-segment.vacuum" in styles
    segment_rule = re.search(r"\.timeline-segment \{([^}]*)\}", styles)
    low_rule = re.search(r"\.timeline-segment\.pump-low \{([^}]*)\}", styles)
    dosing_rule = re.search(r"\.timeline-segment\.dosing \{([^}]*)\}", styles)
    assert segment_rule is not None
    assert low_rule is not None
    assert dosing_rule is not None
    assert "bottom: 4px;" in segment_rule.group(1)
    assert "top: 4px;" in segment_rule.group(1)
    assert "background: #2f8fc0;" in low_rule.group(1)
    assert "background: #2f9b54;" in dosing_rule.group(1)
    assert "bottom:" not in dosing_rule.group(1)
    assert "top:" not in dosing_rule.group(1)


def test_web_pages_use_poolscope_branding_and_live_logo() -> None:
    static_dir = Path(__file__).parents[1] / "src" / "poolctl" / "web" / "static"
    page_titles = {
        "live.html": "PoolScope Live",
        "history.html": "PoolScope History",
        "schedule.html": "PoolScope Schedule",
        "settings.html": "PoolScope Settings",
    }

    product_headers = []
    for page_name, title in page_titles.items():
        markup = (static_dir / page_name).read_text(encoding="utf-8")
        assert f"<title>{title}</title>" in markup
        assert "<h1>PoolScope</h1>" in markup
        assert "<h1>poolctl</h1>" not in markup
        assert '<link rel="icon" type="image/png" href="/poolscope.png">' in markup
        assert '<link rel="apple-touch-icon" href="/poolscope.png">' in markup
        assert '<img class="brand-mark" src="/poolscope.png" alt="">' in markup
        assert 'class="topbar product-header"' in markup
        assert 'id="controllerBadge" class="status-pill is-offline"' in markup
        assert 'id="safetyBadge" class="status-pill is-neutral"' in markup
        assert 'id="headerProfile"' in markup
        assert 'id="headerPumpMode"' in markup
        header = re.search(
            r'<header class="topbar product-header">.*?</header>',
            markup,
            re.DOTALL,
        )
        assert header is not None
        product_headers.append(header.group(0))

    assert len(set(product_headers)) == 1

    live_markup = (static_dir / "live.html").read_text(encoding="utf-8")
    schedule_markup = (static_dir / "schedule.html").read_text(encoding="utf-8")
    styles = (static_dir / "styles.css").read_text(encoding="utf-8")
    settings_script = (static_dir / "settings.js").read_text(encoding="utf-8")
    logo = static_dir / "poolscope.png"

    assert 'class="shell product-shell live-shell"' in live_markup
    assert 'class="shell product-shell schedule-shell"' in schedule_markup
    assert ".brand-mark::before" not in styles
    assert logo.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert 'message: "PoolScope Settings test notification"' in settings_script
    assert 'settingsElement("notificationsDefaultTitle").value.trim() || "PoolScope"' in settings_script


def test_settings_page_uses_collapsible_consumer_tiles_and_canonical_ranges() -> None:
    static_dir = Path(__file__).parents[1] / "src" / "poolctl" / "web" / "static"
    markup = (static_dir / "settings.html").read_text(encoding="utf-8")
    script = (static_dir / "settings.js").read_text(encoding="utf-8")
    app_script = (static_dir / "app.js").read_text(encoding="utf-8")
    styles = (static_dir / "styles.css").read_text(encoding="utf-8")

    card_ids = [
        "pool-site",
        "status-ranges",
        "chlorination",
        "free-chlorine-control",
        "filter-flow",
        "notifications",
        "safety-freeze",
        "sensors-calibration",
        "acquisition-logging",
        "display-dashboard",
        "hardware-runtime",
    ]
    positions = [markup.index(f'id="{card_id}"') for card_id in card_ids]
    assert positions == sorted(positions)
    assert markup.count('class="settings-card"') == 11
    assert markup.count("<details") >= 10
    assert 'id="chlorineSupplyBadge"' not in markup
    assert 'id="safetyBadge"' in markup
    assert 'id="controllerBadge"' in markup
    assert 'id="headerProfile"' in markup
    assert 'id="headerPumpMode"' in markup
    assert markup.index('id="restartBadge"') > markup.index("</header>")
    assert 'id="monitoringPrimaryRows"' in markup
    assert "These ranges control status colors throughout PoolScope" in markup
    assert 'data-settings-link="status-ranges"' in markup
    assert ".settings-card[open]" in styles
    assert "grid-column: 1 / -1;" in styles
    assert "monitoring.limits" not in markup
    assert 'settingsRequest("/api/config/monitoring")' in script
    assert "caution_below" in script
    assert "warning_below" not in script
    assert 'fetch("/api/config/monitoring"' in app_script
    settings_init = script[script.index("function initializeSettingsPage()") :]
    assert settings_init.index("void reloadAllSettings();") < settings_init.index(
        '["safety", initializeSafetyControls]'
    )
    assert "Promise.allSettled" in script
    assert "initializeSettingsControlGroup" in script
    assert "async function requestServiceRestart()" in script
    assert 'settingsPost("/api/system/restart", {})' in script
    assert ".status-pill.hidden" in styles
    settings_page_rule = re.search(r"\.settings-page \{([^}]*)\}", styles)
    settings_heading_rule = re.search(r"\.settings-heading \{([^}]*)\}", styles)
    assert settings_page_rule is not None
    assert settings_heading_rule is not None
    assert "padding: 0 0 var(--space-6);" in settings_page_rule.group(1)
    assert "margin: 0 0 var(--space-6);" in settings_heading_rule.group(1)

    health_source = app_script[
        app_script.index("async function refreshHealth") : app_script.index(
            "function renderLiveCards"
        )
    ]
    assert health_source.index('document.getElementById("healthLine")') < health_source.index(
        'fetch("/api/health"'
    )
    assert "if (!line)" in health_source
    assert 'document.getElementById("healthLine").textContent' not in health_source


def test_history_chart_uses_rendered_width_for_drawing_hover_and_resize() -> None:
    static_dir = Path(__file__).parents[1] / "src" / "poolctl" / "web" / "static"
    script = (static_dir / "app.js").read_text(encoding="utf-8")
    styles = (static_dir / "styles.css").read_text(encoding="utf-8")

    draw_source = script[
        script.index("function drawHistoryChartSeries") : script.index(
            "function appendHistorySeriesTrace"
        )
    ]
    hover_source = script[
        script.index("function installHistoryHover") : script.index(
            "function nearestPoint"
        )
    ]

    assert "const bounds = chart.getBoundingClientRect();" in draw_source
    assert "const width = Math.max(320, Math.round(bounds.width || 720));" in draw_source
    assert 'chart.setAttribute("viewBox", `0 0 ${width} ${height}`);' in draw_source
    assert "historyChartRenderState = { series, windowInfo };" in draw_source
    assert "* axis.width;" in hover_source
    assert "* 720;" not in hover_source
    assert "function initializeHistoryChartResizeHandling()" in hover_source
    assert "drawHistoryChartSeries(historyChartRenderState.series" in hover_source
    assert "initializeHistoryChartResizeHandling();" in script
    history_chart_rule = re.search(r"\.history-chart \{([^}]*)\}", styles)
    assert history_chart_rule is not None
    assert "width: 100%;" in history_chart_rule.group(1)


def test_schedule_editor_uses_operating_modes_and_preserves_drafts() -> None:
    static_dir = Path(__file__).parents[1] / "src" / "poolctl" / "web" / "static"
    script = (static_dir / "app.js").read_text(encoding="utf-8")
    styles = (static_dir / "styles.css").read_text(encoding="utf-8")
    schedule_markup = (static_dir / "schedule.html").read_text(encoding="utf-8")

    for page_name in ("live.html", "history.html", "schedule.html"):
        markup = (static_dir / page_name).read_text(encoding="utf-8")
        assert "<span>Mode</span>" in markup
        assert "<span>Pump Speed</span>" not in markup
        assert "<span>Booster</span>" not in markup
        assert "<span>Dosing</span>" not in markup
        assert 'id="timerReload" type="button">Reload Saved</button>' in markup

    assert 'id="pumpTimerPanel"' in schedule_markup
    assert 'low: Object.freeze({ pump_speed: "low", booster: "off", allow_dosing: false })' in script
    assert 'high: Object.freeze({ pump_speed: "high", booster: "off", allow_dosing: false })' in script
    assert 'dosing: Object.freeze({ pump_speed: "low", booster: "off", allow_dosing: true })' in script
    assert 'vacuum: Object.freeze({ pump_speed: "low", booster: "on", allow_dosing: false })' in script
    assert "Legacy combination will normalize to" in script
    assert "Discard unsaved schedule changes and reload the saved schedule?" in script
    assert "profiles: normalizedTimerProfiles(timerConfigDraft.profiles)" in script
    assert 'class="schedule-workspace"' in schedule_markup
    assert 'class="dashboard-card schedule-settings-card schedule-profile-card"' in schedule_markup
    assert 'class="dashboard-card schedule-editor-card"' in schedule_markup
    assert 'class="dashboard-card schedule-preview-card"' in schedule_markup
    assert ">Profile Selection</h2>" in schedule_markup
    assert 'id="timerCurrentActiveProfile"' in schedule_markup
    assert 'id="timerEditProfileLabel"' in schedule_markup
    assert ">Profile Editor</h2>" in schedule_markup
    assert 'id="timerTimezone"' not in schedule_markup
    assert 'id="timerLatitude"' not in schedule_markup
    assert 'id="timerLongitude"' not in schedule_markup
    assert 'id="timerSaveStatus" class="schedule-save-status" role="status" aria-live="polite"' in schedule_markup
    assert 'id="timerPreview" class="schedule-preview-list" role="status" aria-live="polite"' in schedule_markup
    assert 'label.textContent = "Operating mode";' in script
    assert '"Schedule name",\n    timerInput("name"' in script
    assert 'fixed: "Fixed times"' in script
    assert 'solar_anchor: "Solar anchor"' in script
    assert 'daylight_fraction: "Daylight fraction"' in script
    assert "function renderSchedulePreview(target, days)" in script
    assert 'card.className = "schedule-preview-day";' in script
    assert 'badge.className = `schedule-mode-badge is-${mode}`;' in script
    assert 'target.classList.add("is-error");' in script

    top_status_source = script[
        script.index("async function refreshTopStatus") : script.index("function renderSafetyBadge")
    ]
    assert "setControllerConnectionState(true);" in top_status_source
    assert "setControllerConnectionState(false);" in top_status_source

    poll_source = script[script.index("async function poll()") : script.index(
        'document.querySelectorAll("[data-command]")'
    )]
    assert "loadPumpTimerConfig" not in poll_source
    save_source = script[
        script.index("async function savePumpTimerConfig()") : script.index(
            "function setTimerStatus"
        )
    ]
    assert "profiles: normalizedTimerProfiles(timerConfigDraft.profiles)" in save_source
    assert "active_profile" not in save_source
    assert "site:" not in save_source
    assert "The active profile cannot be removed" in script
    assert ".schedule-workspace" in styles
    assert 'grid-template-columns: minmax(0, 2fr) minmax(330px, 0.82fr);' in styles
    assert '.schedule-page .timer-row[data-mode="dosing"]::before' in styles
    assert "@media (max-width: 680px)" in styles


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


def test_fc_history_includes_valid_preceding_context_without_fabricating_tests(
    tmp_path: Path,
) -> None:
    clock = make_clock()
    app = build_app_from_mapping(
        logging_live_config(str(tmp_path / "fc-context.sqlite3")),
        clock=clock,
    )
    assert app.measurement_logger is not None
    boundary = clock.now() - timedelta(hours=24)
    before = LabTest(sampled_at=boundary - timedelta(hours=4), free_chlorine=4.0)
    inside = LabTest(sampled_at=boundary + timedelta(hours=4), free_chlorine=2.0)
    app.measurement_logger.log_lab_test(before)
    app.measurement_logger.log_lab_test(inside)

    payload = build_history_series_payload(
        app,
        sensor_ids=("lab_free_chlorine",),
        hours=24,
        limit=100,
        until=clock.now(),
    )

    series = payload["series"][0]
    assert [point["value"] for point in series["points"]] == [2.0]
    assert series["context_before"]["value"] == 4.0
    assert series["context_before"]["context_only"] is True
    assert series["actual_markers"] is True


def test_fc_history_does_not_bridge_explicitly_invalid_preceding_test(
    tmp_path: Path,
) -> None:
    clock = make_clock()
    app = build_app_from_mapping(
        logging_live_config(str(tmp_path / "fc-gap.sqlite3")),
        clock=clock,
    )
    assert app.measurement_logger is not None
    boundary = clock.now() - timedelta(hours=24)
    app.measurement_logger.log_lab_test(
        LabTest(
            sampled_at=boundary - timedelta(hours=4),
            free_chlorine=4.0,
            metadata={"free_chlorine_valid": False},
        )
    )
    app.measurement_logger.log_lab_test(
        LabTest(sampled_at=boundary + timedelta(hours=4), free_chlorine=2.0)
    )

    payload = build_history_series_payload(
        app,
        sensor_ids=("lab_free_chlorine",),
        hours=24,
        limit=100,
        until=clock.now(),
    )

    assert payload["series"][0]["context_before"] is None


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
                sensor_id=SensorId.FILTER_REFERENCE_PSI,
                observed_at=now,
                value=9.5,
                unit="psi",
                quality=Quality.GOOD,
            ),
        )
    )

    payload = build_history_series_payload(
        app,
        sensor_ids=("pump_output_psi", "filter_reference_psi"),
        hours=24.0,
        limit=100,
        validated_only=True,
    )

    by_id = {series["sensor_id"]: series for series in payload["series"]}
    assert by_id["pump_output_psi"]["points"][0]["value"] == 12.0
    assert by_id["filter_reference_psi"]["points"][0]["value"] == 9.5


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
