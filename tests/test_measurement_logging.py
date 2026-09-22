"""
Tests for SQLite measurement and event logging.

This file verifies raw history, rollups, lab tests, chemical additions, weather,
and chlorine delivery persistence.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from poolctl.domain.models import (
    ChemicalAddition,
    ChemicalType,
    ChlorineTankRefill,
    LabTest,
    Measurement,
    Quality,
    SensorId,
)
from poolctl.services.measurement_logging import (
    MeasurementLogger,
    MeasurementLoggingConfig,
)
from poolctl.services.pump_timer import PumpTimerConfig, ScheduleService
from poolctl.services.weather import WeatherObservation


def test_measurement_logging_config_parses_control_measurement_interval() -> None:
    config = MeasurementLoggingConfig.from_mapping(
        {
            "logging": {
                "database_path": "data/test.sqlite3",
                "control_measurement_interval_s": 15.0,
            }
        }
    )

    assert config.database_path == Path("data/test.sqlite3")
    assert config.control_measurement_interval_s == 15.0


def test_measurement_logger_persists_and_queries_history(tmp_path: Path) -> None:
    logger = MeasurementLogger(
        MeasurementLoggingConfig(database_path=tmp_path / "measurements.sqlite3")
    )
    now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    old = Measurement(
        sensor_id=SensorId.PUMP_OUTPUT_PSI,
        observed_at=now - timedelta(hours=2),
        value=8.0,
        unit="psi",
        quality=Quality.GOOD,
        metadata={"driver": "test"},
    )
    recent = Measurement(
        sensor_id=SensorId.PUMP_OUTPUT_PSI,
        observed_at=now,
        value=10.0,
        unit="psi",
        quality=Quality.GOOD,
        metadata={"driver": "test"},
    )

    assert logger.log_measurements((old, recent)) == 2

    records = logger.history(
        sensor_id=SensorId.PUMP_OUTPUT_PSI,
        since=now - timedelta(hours=1),
        limit=10,
    )

    assert len(records) == 1
    assert records[0].measurement_id == recent.id
    assert records[0].value == 10.0
    assert records[0].metadata == {"driver": "test"}


def test_measurement_logger_records_schema_version(tmp_path: Path) -> None:
    database_path = tmp_path / "measurements.sqlite3"
    logger = MeasurementLogger(MeasurementLoggingConfig(database_path=database_path))

    assert logger.schema_version() == 2
    with sqlite3.connect(database_path) as connection:
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        metadata_version = connection.execute(
            "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
        ).fetchone()[0]

    assert user_version == 2
    assert metadata_version == "2"


def test_measurement_logger_persists_resolved_schedule_snapshot(tmp_path: Path) -> None:
    logger = MeasurementLogger(
        MeasurementLoggingConfig(database_path=tmp_path / "measurements.sqlite3")
    )
    config = PumpTimerConfig.from_mapping(
        {
            "site": {"timezone": "UTC"},
            "pump_timer": {
                "schedules": [
                    {
                        "name": "filter",
                        "start": "08:00",
                        "end": "12:00",
                    }
                ]
            },
        }
    )
    service = ScheduleService(config)
    resolved_at = datetime(2026, 5, 21, 0, 0, tzinfo=timezone.utc)
    resolution = service.day(resolved_at.date())

    assert logger.log_schedule_resolution(
        resolution,
        resolved_at=resolved_at,
        trigger="startup",
        config_digest=service.config_digest,
    ) == 1
    assert logger.log_schedule_resolution(
        resolution,
        resolved_at=resolved_at,
        trigger="startup",
        config_digest=service.config_digest,
    ) == 0

    history = logger.schedule_resolution_history()
    assert len(history) == 1
    assert history[0].trigger == "startup"
    assert history[0].resolution["windows"][0]["name"] == "filter"


def test_measurement_logger_ignores_duplicate_measurement_ids(tmp_path: Path) -> None:
    logger = MeasurementLogger(
        MeasurementLoggingConfig(database_path=tmp_path / "measurements.sqlite3")
    )
    measurement = Measurement(
        sensor_id=SensorId.PUMP_OUTPUT_PSI,
        value=5.0,
        unit="psi",
    )

    assert logger.log_measurements((measurement,)) == 1
    assert logger.log_measurements((measurement,)) == 0
    assert len(logger.history(sensor_id=SensorId.PUMP_OUTPUT_PSI)) == 1


def test_measurement_logger_history_can_filter_by_quality(tmp_path: Path) -> None:
    logger = MeasurementLogger(
        MeasurementLoggingConfig(database_path=tmp_path / "measurements.sqlite3")
    )
    now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    good = Measurement(
        sensor_id=SensorId.RAW_ORP,
        observed_at=now,
        value=700.0,
        unit="mV",
        quality=Quality.GOOD,
    )
    suspect = Measurement(
        sensor_id=SensorId.RAW_ORP,
        observed_at=now + timedelta(seconds=1),
        value=699.0,
        unit="mV",
        quality=Quality.SUSPECT,
    )
    logger.log_measurements((good, suspect))

    all_records = logger.history(sensor_id=SensorId.RAW_ORP, limit=10)
    good_only = logger.history(
        sensor_id=SensorId.RAW_ORP,
        limit=10,
        qualities=(Quality.GOOD,),
    )

    assert len(all_records) == 2
    assert len(good_only) == 1
    assert good_only[0].quality == Quality.GOOD


def test_measurement_logger_summarizes_measurement_values(tmp_path: Path) -> None:
    logger = MeasurementLogger(
        MeasurementLoggingConfig(database_path=tmp_path / "measurements.sqlite3")
    )
    start = datetime(2026, 5, 22, 0, 0, tzinfo=timezone.utc)
    samples = (
        Measurement(
            sensor_id=SensorId.ORP_TEMP,
            observed_at=start + timedelta(hours=1),
            value=70.0,
            unit="degF",
            quality=Quality.GOOD,
        ),
        Measurement(
            sensor_id=SensorId.ORP_TEMP,
            observed_at=start + timedelta(hours=12),
            value=82.0,
            unit="degF",
            quality=Quality.GOOD,
        ),
        Measurement(
            sensor_id=SensorId.ORP_TEMP,
            observed_at=start + timedelta(hours=23),
            value=74.0,
            unit="degF",
            quality=Quality.GOOD,
        ),
        Measurement(
            sensor_id=SensorId.ORP_TEMP,
            observed_at=start + timedelta(hours=6),
            value=65.0,
            unit="degF",
            quality=Quality.SUSPECT,
        ),
    )
    logger.log_measurements(samples)

    summary = logger.measurement_value_summary(
        sensor_id=SensorId.ORP_TEMP,
        since=start,
        until=start + timedelta(days=1),
    )

    assert summary is not None
    assert summary.count == 3
    assert summary.min_value == 70.0
    assert summary.max_value == 82.0
    assert round(summary.avg_value, 3) == 75.333
    assert summary.sum_value == 226.0
    assert summary.unit == "degF"


def test_measurement_logger_persists_lab_tests(tmp_path: Path) -> None:
    logger = MeasurementLogger(
        MeasurementLoggingConfig(database_path=tmp_path / "measurements.sqlite3")
    )
    now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    test = LabTest(
        sampled_at=now,
        ph=7.45,
        free_chlorine=3.2,
        alkalinity=95.0,
        tds=1200.0,
        chlorine_tank_level_gal=8.5,
        notes="weekly strip + drop test",
    )
    logger.log_lab_test(test)
    records = logger.lab_test_history(limit=10)

    assert len(records) == 1
    assert records[0].id == test.id
    assert records[0].ph == 7.45
    assert records[0].free_chlorine == 3.2
    assert records[0].tds == 1200.0
    assert records[0].chlorine_tank_level_gal == 8.5
    assert records[0].notes == "weekly strip + drop test"


def test_measurement_logger_persists_and_queries_chemical_additions(tmp_path: Path) -> None:
    logger = MeasurementLogger(
        MeasurementLoggingConfig(database_path=tmp_path / "measurements.sqlite3")
    )
    now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    addition = ChemicalAddition(
        added_at=now,
        chemical=ChemicalType.SODIUM_HYPOCHLORITE,
        amount=64.0,
        unit="fl_oz",
        amount_fl_oz=64.0,
        strength_percent=12.0,
        notes="manual dose",
    )

    logger.log_chemical_addition(addition)
    records = logger.chemical_addition_history(limit=10)
    points = logger.chemical_addition_value_history(
        chemical=ChemicalType.SODIUM_HYPOCHLORITE,
        since=now - timedelta(hours=1),
        until=now + timedelta(hours=1),
        limit=10,
    )

    assert len(records) == 1
    assert records[0].id == addition.id
    assert records[0].chemical == ChemicalType.SODIUM_HYPOCHLORITE
    assert records[0].amount_fl_oz == 64.0
    assert records[0].strength_percent == 12.0
    assert len(points) == 1
    assert points[0][1] == 64.0


def test_measurement_logger_summarizes_chlorine_delivery(tmp_path: Path) -> None:
    logger = MeasurementLogger(
        MeasurementLoggingConfig(database_path=tmp_path / "measurements.sqlite3")
    )
    now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)

    assert logger.log_chlorine_delivery(
        observed_at=now,
        runtime_seconds=30.0,
        delivered_oz=0.5,
        metadata={"source": "test"},
    ) == 1
    assert logger.log_chlorine_delivery(
        observed_at=now + timedelta(minutes=10),
        runtime_seconds=60.0,
        delivered_oz=1.0,
    ) == 1

    summary = logger.chlorine_delivery_summary(
        since=now - timedelta(minutes=1),
        until=now + timedelta(minutes=1),
    )
    total = logger.chlorine_delivery_summary(
        since=now - timedelta(minutes=1),
        until=now + timedelta(minutes=20),
    )

    assert summary.runtime_seconds == 30.0
    assert summary.delivered_oz == 0.5
    assert total.runtime_seconds == 90.0
    assert total.delivered_oz == 1.5


def test_measurement_logger_returns_chlorine_delivery_history(
    tmp_path: Path,
) -> None:
    logger = MeasurementLogger(
        MeasurementLoggingConfig(database_path=tmp_path / "measurements.sqlite3")
    )
    now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    logger.log_chlorine_delivery(
        observed_at=now,
        runtime_seconds=30.0,
        delivered_oz=0.5,
        metadata={"source": "scheduled"},
    )
    logger.log_chlorine_delivery(
        observed_at=now + timedelta(minutes=10),
        runtime_seconds=60.0,
        delivered_oz=1.0,
        metadata={"source": "supplemental"},
    )

    records = logger.chlorine_delivery_history(
        since=now - timedelta(minutes=1),
        until=now + timedelta(minutes=20),
    )

    assert [record.observed_at for record in records] == [
        now,
        now + timedelta(minutes=10),
    ]
    assert [record.delivered_oz for record in records] == [0.5, 1.0]
    assert records[1].metadata == {"source": "supplemental"}


def test_measurement_logger_persists_and_summarizes_chlorine_tank_refills(
    tmp_path: Path,
) -> None:
    logger = MeasurementLogger(
        MeasurementLoggingConfig(database_path=tmp_path / "measurements.sqlite3")
    )
    now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    refill = ChlorineTankRefill(
        added_at=now,
        amount_gal=2.5,
        notes="two jugs",
    )

    logger.log_chlorine_tank_refill(refill)
    records = logger.chlorine_tank_refill_history(
        since=now - timedelta(hours=1),
        until=now + timedelta(hours=1),
        limit=10,
    )
    summary = logger.chlorine_tank_refill_summary(
        since=now - timedelta(hours=1),
        until=now + timedelta(hours=1),
    )

    assert len(records) == 1
    assert records[0].id == refill.id
    assert records[0].amount_gal == 2.5
    assert records[0].notes == "two jugs"
    assert summary.amount_gal == 2.5
    assert summary.count == 1


def test_measurement_logger_latest_lab_values_uses_latest_non_null_per_field(
    tmp_path: Path,
) -> None:
    logger = MeasurementLogger(
        MeasurementLoggingConfig(database_path=tmp_path / "measurements.sqlite3")
    )
    now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    logger.log_lab_test(LabTest(sampled_at=now - timedelta(days=2), alkalinity=90.0))
    logger.log_lab_test(LabTest(sampled_at=now - timedelta(days=1), calcium_hardness=250.0))
    logger.log_lab_test(LabTest(sampled_at=now, tds=1400.0, chlorine_tank_level_gal=7.25))

    values = logger.latest_lab_values(
        fields=("alkalinity", "calcium_hardness", "tds", "chlorine_tank_level_gal")
    )

    assert values["alkalinity"] == 90.0
    assert values["calcium_hardness"] == 250.0
    assert values["tds"] == 1400.0
    assert values["chlorine_tank_level_gal"] == 7.25


def test_measurement_logger_lab_value_history_returns_time_ordered_non_null_points(
    tmp_path: Path,
) -> None:
    logger = MeasurementLogger(
        MeasurementLoggingConfig(database_path=tmp_path / "measurements.sqlite3")
    )
    now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    logger.log_lab_test(LabTest(sampled_at=now - timedelta(hours=2), free_chlorine=2.1))
    logger.log_lab_test(LabTest(sampled_at=now - timedelta(hours=1), free_chlorine=None))
    logger.log_lab_test(LabTest(sampled_at=now, free_chlorine=3.3))

    points = logger.lab_value_history(
        field="free_chlorine",
        since=now - timedelta(hours=3),
        until=now + timedelta(minutes=1),
        limit=10,
    )

    assert len(points) == 2
    assert points[0][1] == 2.1
    assert points[1][1] == 3.3


def test_measurement_logger_rollup_history_uses_bucket_aggregation(tmp_path: Path) -> None:
    logger = MeasurementLogger(
        MeasurementLoggingConfig(database_path=tmp_path / "measurements.sqlite3")
    )
    start = datetime(2026, 5, 22, 0, 0, tzinfo=timezone.utc)
    samples = tuple(
        Measurement(
            sensor_id=SensorId.PUMP_OUTPUT_PSI,
            observed_at=start + timedelta(minutes=index),
            value=float(index % 10),
            unit="psi",
            quality=Quality.GOOD,
        )
        for index in range(120)
    )
    logger.log_measurements(samples)

    records = logger.history_with_rollup(
        sensor_id=SensorId.PUMP_OUTPUT_PSI,
        since=start,
        until=start + timedelta(hours=2),
        limit=1000,
        qualities=(Quality.GOOD,),
        bucket_seconds=3600,
        max_points=100,
    )

    assert len(records) == 2
    assert records[0].metadata["aggregation"] == "avg"
    assert records[0].metadata["bucket_seconds"] == 3600
    assert records[0].metadata["sample_count"] == 60


def test_measurement_logger_history_with_rollup_respects_max_points(tmp_path: Path) -> None:
    logger = MeasurementLogger(
        MeasurementLoggingConfig(database_path=tmp_path / "measurements.sqlite3")
    )
    start = datetime(2026, 5, 22, 0, 0, tzinfo=timezone.utc)
    samples = tuple(
        Measurement(
            sensor_id=SensorId.PUMP_OUTPUT_PSI,
            observed_at=start + timedelta(minutes=index),
            value=float(index),
            unit="psi",
            quality=Quality.GOOD,
        )
        for index in range(720)
    )
    logger.log_measurements(samples)

    records = logger.history_with_rollup(
        sensor_id=SensorId.PUMP_OUTPUT_PSI,
        since=start,
        until=start + timedelta(hours=12),
        limit=2000,
        qualities=(Quality.GOOD,),
        bucket_seconds=60,
        max_points=120,
    )

    assert len(records) <= 120


def test_measurement_logger_raw_history_downsample_preserves_recent_points(
    tmp_path: Path,
) -> None:
    logger = MeasurementLogger(
        MeasurementLoggingConfig(database_path=tmp_path / "measurements.sqlite3")
    )
    start = datetime(2026, 5, 22, 0, 0, tzinfo=timezone.utc)
    samples = tuple(
        Measurement(
            sensor_id=SensorId.CPU_TEMP,
            observed_at=start + timedelta(seconds=30 * index),
            value=50.0 + float(index) * 0.01,
            unit="degC",
            quality=Quality.GOOD,
        )
        for index in range(2880)
    )
    logger.log_measurements(samples)

    records = logger.history_with_rollup(
        sensor_id=SensorId.CPU_TEMP,
        since=start,
        until=start + timedelta(days=1),
        limit=5000,
        qualities=(Quality.GOOD,),
        bucket_seconds=None,
        max_points=1800,
    )

    assert len(records) <= 1800
    assert records[0].observed_at == samples[0].observed_at
    assert records[-1].observed_at == samples[-1].observed_at


def test_measurement_logger_persists_and_queries_weather_history(tmp_path: Path) -> None:
    logger = MeasurementLogger(
        MeasurementLoggingConfig(database_path=tmp_path / "measurements.sqlite3")
    )
    now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    older = WeatherObservation(
        observed_at=now - timedelta(hours=1),
        source="open-meteo",
        latitude=29.75,
        longitude=-95.35,
        values={"temperature_2m": 82.5, "cloud_cover": 40.0, "uv_index": 6.0, "precipitation": 0.0},
        units_by_field={"temperature_2m": "degF"},
    )
    recent = WeatherObservation(
        observed_at=now,
        source="open-meteo",
        latitude=29.75,
        longitude=-95.35,
        values={"temperature_2m": 84.0, "cloud_cover": 30.0, "uv_index": 7.0, "precipitation": 0.02},
        units_by_field={"temperature_2m": "degF"},
    )
    logger.log_weather_observation(older)
    logger.log_weather_observation(recent)

    temp_points = logger.weather_history(
        field="temperature_2m",
        since=now - timedelta(hours=2),
        until=now + timedelta(minutes=1),
        limit=10,
    )
    uv_points = logger.weather_history(
        field="uv_index",
        since=now - timedelta(hours=2),
        until=now + timedelta(minutes=1),
        limit=10,
    )

    assert len(temp_points) == 2
    assert temp_points[0][1] == 82.5
    assert temp_points[1][1] == 84.0
    assert len(uv_points) == 2
    assert uv_points[1][1] == 7.0

    uv_summary = logger.weather_value_summary(
        field="uv_index",
        since=now - timedelta(hours=2),
        until=now + timedelta(minutes=1),
    )

    assert uv_summary is not None
    assert uv_summary.count == 2
    assert uv_summary.min_value == 6.0
    assert uv_summary.max_value == 7.0
    assert uv_summary.avg_value == 6.5
    assert uv_summary.sum_value == 13.0
