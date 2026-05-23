from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from poolctl.domain.models import LabTest, Measurement, MeasurementKind, Quality, SensorId


@dataclass(frozen=True)
class MeasurementLoggingConfig:
    """
    Persistence settings for measurement history.
    """

    database_path: Path = Path("data/poolctl.sqlite3")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> MeasurementLoggingConfig:
        logging_data = _mapping_value(data, "logging", default={})
        raw_database_path = logging_data.get("database_path", cls.database_path)

        if not isinstance(raw_database_path, str | Path):
            raise ValueError("logging.database_path must be a path string")

        return cls(database_path=Path(raw_database_path))


@dataclass(frozen=True)
class MeasurementRecord:
    """
    One persisted measurement row.
    """

    measurement_id: str
    sensor_id: SensorId
    observed_at: datetime
    kind: MeasurementKind
    value: float
    unit: str
    quality: Quality
    metadata: dict[str, Any]

    def to_measurement(self) -> Measurement:
        return Measurement(
            id=self.measurement_id,
            sensor_id=self.sensor_id,
            observed_at=self.observed_at,
            kind=self.kind,
            value=self.value,
            unit=self.unit,
            quality=self.quality,
            metadata=self.metadata,
        )


class MeasurementLogger:
    """
    SQLite-backed store for loggable measurement history.
    """

    def __init__(self, config: MeasurementLoggingConfig) -> None:
        self._database_path = config.database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def log_measurements(self, measurements: tuple[Measurement, ...]) -> int:
        if not measurements:
            return 0

        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR IGNORE INTO measurements (
                    id,
                    sensor_id,
                    observed_at,
                    kind,
                    value,
                    unit,
                    quality,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        measurement.id,
                        measurement.sensor_id.value,
                        measurement.observed_at.isoformat(),
                        measurement.kind.value,
                        measurement.value,
                        measurement.unit,
                        measurement.quality.value,
                        json.dumps(measurement.metadata, sort_keys=True),
                    )
                    for measurement in measurements
                ],
            )
            return int(connection.total_changes)

    def history(
        self,
        *,
        sensor_id: SensorId,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
        qualities: tuple[Quality, ...] | None = None,
    ) -> tuple[MeasurementRecord, ...]:
        if limit < 1:
            raise ValueError("limit must be at least 1")

        clauses = ["sensor_id = ?"]
        parameters: list[str | int] = [sensor_id.value]

        if since is not None:
            clauses.append("observed_at >= ?")
            parameters.append(since.isoformat())

        if until is not None:
            clauses.append("observed_at <= ?")
            parameters.append(until.isoformat())

        if qualities:
            placeholders = ", ".join("?" for _ in qualities)
            clauses.append(f"quality IN ({placeholders})")
            parameters.extend(quality.value for quality in qualities)

        parameters.append(limit)
        where_clause = " AND ".join(clauses)

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    id,
                    sensor_id,
                    observed_at,
                    kind,
                    value,
                    unit,
                    quality,
                    metadata_json
                FROM measurements
                WHERE {where_clause}
                ORDER BY observed_at DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()

        records = tuple(_record_from_row(row) for row in rows)
        return tuple(reversed(records))

    def log_lab_test(self, test: LabTest) -> str:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO lab_tests (
                    id,
                    sampled_at,
                    entered_at,
                    ph,
                    free_chlorine,
                    combined_chlorine,
                    total_chlorine,
                    alkalinity,
                    cya,
                    calcium_hardness,
                    salt,
                    borates,
                    water_temp,
                    notes,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    test.id,
                    test.sampled_at.isoformat(),
                    test.entered_at.isoformat(),
                    test.ph,
                    test.free_chlorine,
                    test.combined_chlorine,
                    test.total_chlorine,
                    test.alkalinity,
                    test.cya,
                    test.calcium_hardness,
                    test.salt,
                    test.borates,
                    test.water_temp,
                    test.notes,
                    json.dumps(test.metadata, sort_keys=True),
                ),
            )
        return test.id

    def lab_test_history(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> tuple[LabTest, ...]:
        if limit < 1:
            raise ValueError("limit must be at least 1")

        clauses = ["1=1"]
        parameters: list[str | int] = []
        if since is not None:
            clauses.append("sampled_at >= ?")
            parameters.append(since.isoformat())
        if until is not None:
            clauses.append("sampled_at <= ?")
            parameters.append(until.isoformat())
        parameters.append(limit)
        where_clause = " AND ".join(clauses)

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    id,
                    sampled_at,
                    entered_at,
                    ph,
                    free_chlorine,
                    combined_chlorine,
                    total_chlorine,
                    alkalinity,
                    cya,
                    calcium_hardness,
                    salt,
                    borates,
                    water_temp,
                    notes,
                    metadata_json
                FROM lab_tests
                WHERE {where_clause}
                ORDER BY sampled_at DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        tests = tuple(_lab_test_from_row(row) for row in rows)
        return tuple(reversed(tests))

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS measurements (
                    id TEXT PRIMARY KEY,
                    sensor_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    value REAL NOT NULL,
                    unit TEXT NOT NULL,
                    quality TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_measurements_sensor_time
                ON measurements (sensor_id, observed_at)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS lab_tests (
                    id TEXT PRIMARY KEY,
                    sampled_at TEXT NOT NULL,
                    entered_at TEXT NOT NULL,
                    ph REAL,
                    free_chlorine REAL,
                    combined_chlorine REAL,
                    total_chlorine REAL,
                    alkalinity REAL,
                    cya REAL,
                    calcium_hardness REAL,
                    salt REAL,
                    borates REAL,
                    water_temp REAL,
                    notes TEXT,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_lab_tests_sampled
                ON lab_tests (sampled_at)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection


def _record_from_row(row: sqlite3.Row) -> MeasurementRecord:
    return MeasurementRecord(
        measurement_id=str(row["id"]),
        sensor_id=SensorId(str(row["sensor_id"])),
        observed_at=_parse_datetime(str(row["observed_at"])),
        kind=MeasurementKind(str(row["kind"])),
        value=float(row["value"]),
        unit=str(row["unit"]),
        quality=Quality(str(row["quality"])),
        metadata=_metadata_from_json(str(row["metadata_json"])),
    )


def _lab_test_from_row(row: sqlite3.Row) -> LabTest:
    return LabTest(
        id=str(row["id"]),
        sampled_at=_parse_datetime(str(row["sampled_at"])),
        entered_at=_parse_datetime(str(row["entered_at"])),
        ph=_optional_float(row["ph"]),
        free_chlorine=_optional_float(row["free_chlorine"]),
        combined_chlorine=_optional_float(row["combined_chlorine"]),
        total_chlorine=_optional_float(row["total_chlorine"]),
        alkalinity=_optional_float(row["alkalinity"]),
        cya=_optional_float(row["cya"]),
        calcium_hardness=_optional_float(row["calcium_hardness"]),
        salt=_optional_float(row["salt"]),
        borates=_optional_float(row["borates"]),
        water_temp=_optional_float(row["water_temp"]),
        notes=str(row["notes"]) if row["notes"] is not None else None,
        metadata=_metadata_from_json(str(row["metadata_json"])),
    )


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)

    return parsed


def _metadata_from_json(value: str) -> dict[str, Any]:
    metadata = json.loads(value)
    if not isinstance(metadata, dict):
        return {}

    return metadata


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _mapping_value(
    data: Mapping[str, Any],
    key: str,
    *,
    default: Mapping[str, Any],
) -> Mapping[str, Any]:
    value = data.get(key, default)

    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be a mapping")

    return value
