from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from poolctl.domain.models import LabTest, Measurement, Quality, SensorId
from poolctl.services.measurement_logging import (
    MeasurementLogger,
    MeasurementLoggingConfig,
)


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


def test_measurement_logger_ignores_duplicate_measurement_ids(tmp_path: Path) -> None:
    logger = MeasurementLogger(
        MeasurementLoggingConfig(database_path=tmp_path / "measurements.sqlite3")
    )
    measurement = Measurement(
        sensor_id=SensorId.RETURN_PSI,
        value=5.0,
        unit="psi",
    )

    assert logger.log_measurements((measurement,)) == 1
    assert logger.log_measurements((measurement,)) == 0
    assert len(logger.history(sensor_id=SensorId.RETURN_PSI)) == 1


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
        notes="weekly strip + drop test",
    )
    logger.log_lab_test(test)
    records = logger.lab_test_history(limit=10)

    assert len(records) == 1
    assert records[0].id == test.id
    assert records[0].ph == 7.45
    assert records[0].free_chlorine == 3.2
    assert records[0].tds == 1200.0
    assert records[0].notes == "weekly strip + drop test"


def test_measurement_logger_latest_lab_values_uses_latest_non_null_per_field(
    tmp_path: Path,
) -> None:
    logger = MeasurementLogger(
        MeasurementLoggingConfig(database_path=tmp_path / "measurements.sqlite3")
    )
    now = datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc)
    logger.log_lab_test(LabTest(sampled_at=now - timedelta(days=2), alkalinity=90.0))
    logger.log_lab_test(LabTest(sampled_at=now - timedelta(days=1), calcium_hardness=250.0))
    logger.log_lab_test(LabTest(sampled_at=now, tds=1400.0))

    values = logger.latest_lab_values(fields=("alkalinity", "calcium_hardness", "tds"))

    assert values["alkalinity"] == 90.0
    assert values["calcium_hardness"] == 250.0
    assert values["tds"] == 1400.0


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
            sensor_id=SensorId.RETURN_PSI,
            observed_at=start + timedelta(minutes=index),
            value=float(index),
            unit="psi",
            quality=Quality.GOOD,
        )
        for index in range(720)
    )
    logger.log_measurements(samples)

    records = logger.history_with_rollup(
        sensor_id=SensorId.RETURN_PSI,
        since=start,
        until=start + timedelta(hours=12),
        limit=2000,
        qualities=(Quality.GOOD,),
        bucket_seconds=60,
        max_points=120,
    )

    assert len(records) <= 120
