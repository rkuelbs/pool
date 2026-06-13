from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from poolctl.domain.models import (
    ChemicalAddition,
    ChemicalType,
    LabTest,
    Measurement,
    MeasurementKind,
    Quality,
    SensorId,
)
from poolctl.services.weather import WEATHER_FIELDS, WeatherObservation

ROLLUP_BUCKET_SECONDS = (60, 3600, 86400)


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


@dataclass(frozen=True)
class MeasurementRollupRecord:
    sensor_id: SensorId
    observed_at: datetime
    value: float
    unit: str
    min_value: float
    max_value: float
    sample_count: int
    bucket_seconds: int

    def to_measurement_record(self) -> MeasurementRecord:
        return MeasurementRecord(
            measurement_id=(
                f"rollup:{self.sensor_id.value}:{self.bucket_seconds}:{self.observed_at.isoformat()}"
            ),
            sensor_id=self.sensor_id,
            observed_at=self.observed_at,
            kind=MeasurementKind.ESTIMATED,
            value=self.value,
            unit=self.unit,
            quality=Quality.GOOD,
            metadata={
                "aggregation": "avg",
                "bucket_seconds": self.bucket_seconds,
                "sample_count": self.sample_count,
                "min_value": self.min_value,
                "max_value": self.max_value,
            },
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

        inserted_count = 0
        with self._connect() as connection:
            for measurement in measurements:
                cursor = connection.execute(
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
                    (
                        measurement.id,
                        measurement.sensor_id.value,
                        measurement.observed_at.isoformat(),
                        measurement.kind.value,
                        measurement.value,
                        measurement.unit,
                        measurement.quality.value,
                        json.dumps(measurement.metadata, sort_keys=True),
                    ),
                )
                if int(cursor.rowcount) > 0:
                    inserted_count += 1
                    self._upsert_rollups(connection, measurement)
        return inserted_count

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

    def history_with_rollup(
        self,
        *,
        sensor_id: SensorId,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
        qualities: tuple[Quality, ...] | None = None,
        bucket_seconds: int | None = None,
        max_points: int | None = None,
    ) -> tuple[MeasurementRecord, ...]:
        if bucket_seconds is None:
            records = self.history(
                sensor_id=sensor_id,
                since=since,
                until=until,
                limit=limit,
                qualities=qualities,
            )
            return _downsample_records(records, max_points=max_points)

        if bucket_seconds not in ROLLUP_BUCKET_SECONDS:
            raise ValueError("unsupported bucket_seconds")
        if qualities not in (None, (Quality.GOOD,)):
            records = self.history(
                sensor_id=sensor_id,
                since=since,
                until=until,
                limit=limit,
                qualities=qualities,
            )
            return _downsample_records(records, max_points=max_points)

        clauses = [
            "sensor_id = ?",
            "bucket_seconds = ?",
        ]
        parameters: list[str | int] = [sensor_id.value, bucket_seconds]
        if since is not None:
            clauses.append("bucket_start >= ?")
            parameters.append(_bucket_start_iso(since, bucket_seconds))
        if until is not None:
            clauses.append("bucket_start <= ?")
            parameters.append(_bucket_start_iso(until, bucket_seconds))
        parameters.append(limit)
        where_clause = " AND ".join(clauses)

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    sensor_id,
                    bucket_start,
                    avg_value,
                    min_value,
                    max_value,
                    sample_count,
                    unit,
                    bucket_seconds
                FROM measurement_rollups
                WHERE {where_clause}
                ORDER BY bucket_start ASC
                LIMIT ?
                """,
                parameters,
            ).fetchall()

        records = tuple(
            _rollup_from_row(row).to_measurement_record()
            for row in rows
        )
        return _downsample_records(records, max_points=max_points)

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
                    tds,
                    salt,
                    borates,
                    water_temp,
                    notes,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    test.tds,
                    test.salt,
                    test.borates,
                    test.water_temp,
                    test.notes,
                    json.dumps(test.metadata, sort_keys=True),
                ),
            )
        return test.id

    def log_chemical_addition(self, addition: ChemicalAddition) -> str:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO chemical_additions (
                    id,
                    added_at,
                    entered_at,
                    chemical,
                    amount,
                    unit,
                    amount_fl_oz,
                    strength_percent,
                    notes,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    addition.id,
                    addition.added_at.isoformat(),
                    addition.entered_at.isoformat(),
                    addition.chemical.value,
                    addition.amount,
                    addition.unit,
                    addition.amount_fl_oz,
                    addition.strength_percent,
                    addition.notes,
                    json.dumps(addition.metadata, sort_keys=True),
                ),
            )
        return addition.id

    def latest_lab_values(
        self,
        *,
        fields: tuple[str, ...],
    ) -> dict[str, float]:
        """
        Return latest non-null lab value for each requested field.
        """
        if not fields:
            return {}

        allowed = {
            "ph",
            "free_chlorine",
            "combined_chlorine",
            "total_chlorine",
            "alkalinity",
            "cya",
            "calcium_hardness",
            "tds",
            "salt",
            "borates",
            "water_temp",
        }
        for field in fields:
            if field not in allowed:
                raise ValueError(f"unsupported lab field: {field}")

        latest: dict[str, float] = {}
        with self._connect() as connection:
            for field in fields:
                row = connection.execute(
                    f"""
                    SELECT {field}
                    FROM lab_tests
                    WHERE {field} IS NOT NULL
                    ORDER BY sampled_at DESC, entered_at DESC
                    LIMIT 1
                    """
                ).fetchone()
                if row is None:
                    continue
                value = _optional_float(row[field])
                if value is not None:
                    latest[field] = value
        return latest

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
                    tds,
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

    def lab_value_history(
        self,
        *,
        field: str,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> tuple[tuple[datetime, float], ...]:
        if limit < 1:
            raise ValueError("limit must be at least 1")

        allowed = {
            "ph",
            "free_chlorine",
            "alkalinity",
            "calcium_hardness",
            "cya",
            "tds",
            "salt",
            "borates",
        }
        if field not in allowed:
            raise ValueError(f"unsupported lab field: {field}")

        clauses = [f"{field} IS NOT NULL"]
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
                SELECT sampled_at, {field} AS value
                FROM lab_tests
                WHERE {where_clause}
                ORDER BY sampled_at DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()

        descending = tuple(
            (
                _parse_datetime(str(row["sampled_at"])),
                float(row["value"]),
            )
            for row in rows
            if row["value"] is not None
        )
        return tuple(reversed(descending))

    def chemical_addition_history(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> tuple[ChemicalAddition, ...]:
        if limit < 1:
            raise ValueError("limit must be at least 1")

        clauses = ["1=1"]
        parameters: list[str | int] = []
        if since is not None:
            clauses.append("added_at >= ?")
            parameters.append(since.isoformat())
        if until is not None:
            clauses.append("added_at <= ?")
            parameters.append(until.isoformat())
        parameters.append(limit)
        where_clause = " AND ".join(clauses)

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    id,
                    added_at,
                    entered_at,
                    chemical,
                    amount,
                    unit,
                    amount_fl_oz,
                    strength_percent,
                    notes,
                    metadata_json
                FROM chemical_additions
                WHERE {where_clause}
                ORDER BY added_at DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        additions = tuple(_chemical_addition_from_row(row) for row in rows)
        return tuple(reversed(additions))

    def chemical_addition_value_history(
        self,
        *,
        chemical: ChemicalType | str,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> tuple[tuple[datetime, float], ...]:
        if limit < 1:
            raise ValueError("limit must be at least 1")

        chemical_id = ChemicalType(chemical).value
        clauses = ["chemical = ?"]
        parameters: list[str | int] = [chemical_id]
        if since is not None:
            clauses.append("added_at >= ?")
            parameters.append(since.isoformat())
        if until is not None:
            clauses.append("added_at <= ?")
            parameters.append(until.isoformat())
        parameters.append(limit)
        where_clause = " AND ".join(clauses)

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT added_at, amount_fl_oz AS value
                FROM chemical_additions
                WHERE {where_clause}
                ORDER BY added_at DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()

        descending = tuple(
            (
                _parse_datetime(str(row["added_at"])),
                float(row["value"]),
            )
            for row in rows
            if row["value"] is not None
        )
        return tuple(reversed(descending))

    def log_weather_observation(self, observation: WeatherObservation) -> int:
        columns = (
            "timestamp",
            "source",
            "latitude",
            "longitude",
            *WEATHER_FIELDS,
        )
        placeholders = ", ".join("?" for _ in columns)
        values: list[Any] = [
            observation.observed_at.isoformat(),
            observation.source,
            observation.latitude,
            observation.longitude,
        ]
        values.extend(observation.values.get(field) for field in WEATHER_FIELDS)

        with self._connect() as connection:
            connection.execute(
                f"""
                INSERT OR REPLACE INTO weather_observations (
                    {", ".join(columns)}
                )
                VALUES ({placeholders})
                """,
                values,
            )
        return 1

    def weather_history(
        self,
        *,
        field: str,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> tuple[tuple[datetime, float], ...]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if field not in WEATHER_FIELDS:
            raise ValueError(f"unsupported weather field: {field}")

        clauses = [f"{field} IS NOT NULL"]
        parameters: list[str | int] = []
        if since is not None:
            clauses.append("timestamp >= ?")
            parameters.append(since.isoformat())
        if until is not None:
            clauses.append("timestamp <= ?")
            parameters.append(until.isoformat())
        parameters.append(limit)
        where_clause = " AND ".join(clauses)

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT timestamp, {field} AS value
                FROM weather_observations
                WHERE {where_clause}
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()

        descending = tuple(
            (
                _parse_datetime(str(row["timestamp"])),
                float(row["value"]),
            )
            for row in rows
            if row["value"] is not None
        )
        return tuple(reversed(descending))

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
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
                    tds REAL,
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
            self._ensure_column(connection, "lab_tests", "tds", "REAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chemical_additions (
                    id TEXT PRIMARY KEY,
                    added_at TEXT NOT NULL,
                    entered_at TEXT NOT NULL,
                    chemical TEXT NOT NULL,
                    amount REAL NOT NULL,
                    unit TEXT NOT NULL,
                    amount_fl_oz REAL NOT NULL,
                    strength_percent REAL NOT NULL,
                    notes TEXT,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chemical_additions_added
                ON chemical_additions (added_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chemical_additions_chemical_time
                ON chemical_additions (chemical, added_at)
                """
            )
            weather_columns = "\n".join(
                f"                    {field} REAL,"
                for field in WEATHER_FIELDS
            )
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS weather_observations (
                    timestamp TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
{weather_columns.rstrip(",")}
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_weather_observations_time
                ON weather_observations (timestamp)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS measurement_rollups (
                    sensor_id TEXT NOT NULL,
                    bucket_seconds INTEGER NOT NULL,
                    bucket_start TEXT NOT NULL,
                    sample_count INTEGER NOT NULL,
                    sum_value REAL NOT NULL,
                    min_value REAL NOT NULL,
                    max_value REAL NOT NULL,
                    avg_value REAL NOT NULL,
                    unit TEXT NOT NULL,
                    PRIMARY KEY (sensor_id, bucket_seconds, bucket_start)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rollups_sensor_bucket_time
                ON measurement_rollups (sensor_id, bucket_seconds, bucket_start)
                """
            )

    def _upsert_rollups(
        self,
        connection: sqlite3.Connection,
        measurement: Measurement,
    ) -> None:
        if measurement.quality != Quality.GOOD:
            return

        value = float(measurement.value)
        for bucket_seconds in ROLLUP_BUCKET_SECONDS:
            bucket_start = _bucket_start_iso(measurement.observed_at, bucket_seconds)
            connection.execute(
                """
                INSERT INTO measurement_rollups (
                    sensor_id,
                    bucket_seconds,
                    bucket_start,
                    sample_count,
                    sum_value,
                    min_value,
                    max_value,
                    avg_value,
                    unit
                )
                VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
                ON CONFLICT(sensor_id, bucket_seconds, bucket_start) DO UPDATE SET
                    sample_count = measurement_rollups.sample_count + 1,
                    sum_value = measurement_rollups.sum_value + excluded.sum_value,
                    min_value = MIN(measurement_rollups.min_value, excluded.min_value),
                    max_value = MAX(measurement_rollups.max_value, excluded.max_value),
                    avg_value = (measurement_rollups.sum_value + excluded.sum_value) /
                        (measurement_rollups.sample_count + 1),
                    unit = excluded.unit
                """,
                (
                    measurement.sensor_id.value,
                    bucket_seconds,
                    bucket_start,
                    value,
                    value,
                    value,
                    value,
                    measurement.unit,
                ),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_column(
        self,
        connection: sqlite3.Connection,
        table: str,
        column: str,
        column_sql: str,
    ) -> None:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
        names = {str(row["name"]) for row in rows}
        if column in names:
            return
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_sql}")


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


def _rollup_from_row(row: sqlite3.Row) -> MeasurementRollupRecord:
    return MeasurementRollupRecord(
        sensor_id=SensorId(str(row["sensor_id"])),
        observed_at=_parse_datetime(str(row["bucket_start"])),
        value=float(row["avg_value"]),
        min_value=float(row["min_value"]),
        max_value=float(row["max_value"]),
        sample_count=int(row["sample_count"]),
        unit=str(row["unit"]),
        bucket_seconds=int(row["bucket_seconds"]),
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
        tds=_optional_float(row["tds"]),
        salt=_optional_float(row["salt"]),
        borates=_optional_float(row["borates"]),
        water_temp=_optional_float(row["water_temp"]),
        notes=str(row["notes"]) if row["notes"] is not None else None,
        metadata=_metadata_from_json(str(row["metadata_json"])),
    )


def _chemical_addition_from_row(row: sqlite3.Row) -> ChemicalAddition:
    return ChemicalAddition(
        id=str(row["id"]),
        added_at=_parse_datetime(str(row["added_at"])),
        entered_at=_parse_datetime(str(row["entered_at"])),
        chemical=ChemicalType(str(row["chemical"])),
        amount=float(row["amount"]),
        unit=str(row["unit"]),
        amount_fl_oz=float(row["amount_fl_oz"]),
        strength_percent=float(row["strength_percent"]),
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


def _bucket_start_iso(observed_at: datetime, bucket_seconds: int) -> str:
    utc_time = observed_at.astimezone(timezone.utc)
    epoch_s = int(utc_time.timestamp())
    bucket_epoch = epoch_s - (epoch_s % bucket_seconds)
    return datetime.fromtimestamp(bucket_epoch, tz=timezone.utc).isoformat()


def _downsample_records(
    records: tuple[MeasurementRecord, ...],
    *,
    max_points: int | None,
) -> tuple[MeasurementRecord, ...]:
    if max_points is None or max_points < 1 or len(records) <= max_points:
        return records

    stride = max(1, math.ceil(len(records) / max_points))
    sampled = records[::stride]
    if sampled[-1].measurement_id != records[-1].measurement_id:
        sampled = (*sampled, records[-1])
    if len(sampled) > max_points:
        sampled = (*sampled[: max_points - 1], records[-1])
    return tuple(sampled)


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
