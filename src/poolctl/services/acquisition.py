from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from statistics import mean, median
from typing import Any

import yaml  # type: ignore[import-untyped]

from poolctl.domain.models import (
    ActuatorId,
    ActuatorState,
    Measurement,
    Quality,
    SensorId,
)
from poolctl.drivers.base import MultiSensorDriver, SensorDriver
from poolctl.services.clock import Clock


class Reducer(str, Enum):
    """
    How oversampled sensor values are reduced to one published Measurement.
    """

    LAST = "last"
    MEAN = "mean"
    MEDIAN = "median"
    TRIMMED_MEAN = "trimmed_mean"


class FilterType(str, Enum):
    """
    Continuous filtering applied across acquisition polls.
    """

    NONE = "none"
    BOXCAR = "boxcar"


@dataclass(frozen=True)
class OversamplingConfig:
    """
    Burst-sampling settings for one acquisition group.
    """

    sample_count: int = 1
    sample_interval_s: float = 0.0
    reducer: Reducer = Reducer.LAST

    def __post_init__(self) -> None:
        if self.sample_count < 1:
            raise ValueError("sample_count must be at least 1")

        if self.sample_interval_s < 0:
            raise ValueError("sample_interval_s cannot be negative")


@dataclass(frozen=True)
class MeasurementFilterConfig:
    """
    Rolling filter settings for one acquisition group.

    Burst oversampling reduces several immediate samples into one reading.
    This filter smooths readings across normal acquisition polls so the control
    loop is not blocked by long sensor-sampling bursts.
    """

    filter_type: FilterType = FilterType.NONE
    window_samples: int | None = None
    window_seconds: float | None = None
    min_samples: int = 1

    def __post_init__(self) -> None:
        if self.min_samples < 1:
            raise ValueError("min_samples must be at least 1")

        if self.window_samples is not None and self.window_samples < 1:
            raise ValueError("window_samples must be at least 1 when set")

        if self.window_seconds is not None and self.window_seconds <= 0:
            raise ValueError("window_seconds must be greater than zero when set")

        if (
            self.filter_type == FilterType.BOXCAR
            and self.window_samples is None
            and self.window_seconds is None
        ):
            raise ValueError("boxcar filter requires window_samples or window_seconds")

        if (
            self.window_samples is not None
            and self.min_samples > self.window_samples
        ):
            raise ValueError("min_samples cannot exceed window_samples")


@dataclass(frozen=True)
class AcquisitionGroupConfig:
    """
    Read/log policy for a related group of sensors.
    """

    name: str
    sensor_ids: tuple[SensorId, ...]
    read_interval_s: float
    log_interval_s: float
    requires_pump_flow: bool = False
    min_pump_on_seconds: float = 0.0
    required_pump_speed: ActuatorState | None = None
    oversampling: OversamplingConfig = field(default_factory=OversamplingConfig)
    filtering: MeasurementFilterConfig = field(default_factory=MeasurementFilterConfig)

    def __post_init__(self) -> None:
        if not self.sensor_ids:
            raise ValueError("sensor_ids cannot be empty")

        if self.read_interval_s < 0:
            raise ValueError("read_interval_s cannot be negative")

        if self.log_interval_s < 0:
            raise ValueError("log_interval_s cannot be negative")

        if self.min_pump_on_seconds < 0:
            raise ValueError("min_pump_on_seconds cannot be negative")

        if self.required_pump_speed not in (None, ActuatorState.LOW, ActuatorState.HIGH):
            raise ValueError("required_pump_speed must be low, high, or omitted")


@dataclass(frozen=True)
class AcquisitionConfig:
    """
    Full acquisition configuration.
    """

    groups: tuple[AcquisitionGroupConfig, ...]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> AcquisitionConfig:
        acquisition_data = _mapping_value(data, "acquisition", default=data)
        groups_data = _mapping_value(acquisition_data, "groups", default={})
        groups: list[AcquisitionGroupConfig] = []

        for group_name, raw_group_data in groups_data.items():
            if not isinstance(group_name, str):
                raise ValueError("acquisition group names must be strings")

            if not isinstance(raw_group_data, Mapping):
                raise ValueError(f"acquisition group {group_name} must be a mapping")

            groups.append(_group_from_mapping(group_name, raw_group_data))

        return cls(groups=tuple(groups))


@dataclass(frozen=True)
class AcquisitionFailure:
    """
    One driver failure captured during acquisition.
    """

    driver_name: str
    observed_at: datetime
    error: str
    sensor_id: SensorId | None = None


@dataclass(frozen=True)
class MeasurementLogDecision:
    """
    Whether a fresh measurement is eligible for persistence.
    """

    measurement: Measurement
    should_log: bool
    reason: str | None = None


@dataclass(frozen=True)
class AcquisitionResult:
    """
    Measurements and logging decisions from one acquisition pass.
    """

    group_names: tuple[str, ...]
    measurements: tuple[Measurement, ...]
    loggable_measurements: tuple[Measurement, ...]
    log_decisions: tuple[MeasurementLogDecision, ...]
    failures: tuple[AcquisitionFailure, ...]


class AcquisitionService:
    """
    Reads sensors according to configured groups and keeps latest values.

    The service separates fresh readings from log eligibility. Safety code can
    use the latest pressure readings at high rate, while storage can persist a
    slower, flow-qualified subset.
    """

    def __init__(
        self,
        *,
        config: AcquisitionConfig,
        clock: Clock,
        sensor_drivers: Iterable[SensorDriver],
        multi_sensor_drivers: Iterable[MultiSensorDriver] = (),
    ) -> None:
        self._config = config
        self._clock = clock
        self._sensor_drivers: dict[SensorId, SensorDriver] = {}
        for driver in sensor_drivers:
            if driver.sensor_id in self._sensor_drivers:
                raise ValueError(f"duplicate sensor driver: {driver.sensor_id.value}")

            self._sensor_drivers[driver.sensor_id] = driver

        self._multi_sensor_drivers = tuple(multi_sensor_drivers)
        self._latest_measurements: dict[SensorId, Measurement] = {}
        self._latest_raw_measurements: dict[SensorId, Measurement] = {}
        self._filter_buffers: dict[SensorId, list[Measurement]] = {}
        self._last_read_at: dict[str, datetime] = {}
        self._last_logged_at: dict[SensorId, datetime] = {}
        self._groups_by_name = {group.name: group for group in config.groups}

        self._validate_config()

    @property
    def latest_measurements(self) -> dict[SensorId, Measurement]:
        return dict(self._latest_measurements)

    @property
    def latest_raw_measurements(self) -> dict[SensorId, Measurement]:
        return dict(self._latest_raw_measurements)

    async def poll_due(
        self,
        *,
        actuator_states: Mapping[ActuatorId, ActuatorState],
        state_started_at: Mapping[ActuatorId, datetime],
        force: bool = False,
    ) -> AcquisitionResult:
        now = self._clock.now()
        due_groups = [
            group
            for group in self._config.groups
            if force or self._group_is_due(group, now)
        ]

        return await self._read_groups(
            due_groups,
            actuator_states=actuator_states,
            state_started_at=state_started_at,
        )

    async def read_group(
        self,
        group_name: str,
        *,
        actuator_states: Mapping[ActuatorId, ActuatorState],
        state_started_at: Mapping[ActuatorId, datetime],
    ) -> AcquisitionResult:
        if group_name not in self._groups_by_name:
            raise ValueError(f"unknown acquisition group: {group_name}")

        return await self._read_groups(
            [self._groups_by_name[group_name]],
            actuator_states=actuator_states,
            state_started_at=state_started_at,
        )

    async def _read_groups(
        self,
        groups: Iterable[AcquisitionGroupConfig],
        *,
        actuator_states: Mapping[ActuatorId, ActuatorState],
        state_started_at: Mapping[ActuatorId, datetime],
    ) -> AcquisitionResult:
        measurements: list[Measurement] = []
        loggable_measurements: list[Measurement] = []
        log_decisions: list[MeasurementLogDecision] = []
        failures: list[AcquisitionFailure] = []
        group_names: list[str] = []

        for group in groups:
            group_result = await self._read_group_once(
                group,
                actuator_states=actuator_states,
                state_started_at=state_started_at,
            )
            group_names.append(group.name)
            measurements.extend(group_result.measurements)
            loggable_measurements.extend(group_result.loggable_measurements)
            log_decisions.extend(group_result.log_decisions)
            failures.extend(group_result.failures)
            self._last_read_at[group.name] = self._clock.now()

        return AcquisitionResult(
            group_names=tuple(group_names),
            measurements=tuple(measurements),
            loggable_measurements=tuple(loggable_measurements),
            log_decisions=tuple(log_decisions),
            failures=tuple(failures),
        )

    async def _read_group_once(
        self,
        group: AcquisitionGroupConfig,
        *,
        actuator_states: Mapping[ActuatorId, ActuatorState],
        state_started_at: Mapping[ActuatorId, datetime],
    ) -> AcquisitionResult:
        samples_by_sensor: dict[SensorId, list[Measurement]] = {
            sensor_id: [] for sensor_id in group.sensor_ids
        }
        failures: list[AcquisitionFailure] = []

        for sample_index in range(group.oversampling.sample_count):
            sample_measurements, sample_failures = await self._read_sample(group.sensor_ids)

            for measurement in sample_measurements:
                if measurement.sensor_id in samples_by_sensor:
                    samples_by_sensor[measurement.sensor_id].append(measurement)

            failures.extend(sample_failures)

            if sample_index < group.oversampling.sample_count - 1:
                await self._clock.sleep(group.oversampling.sample_interval_s)

        now = self._clock.now()
        measurements: list[Measurement] = []
        for samples in samples_by_sensor.values():
            if not samples:
                continue

            reduced_measurement = self._reduce_measurements(samples, group.oversampling)
            self._latest_raw_measurements[reduced_measurement.sensor_id] = reduced_measurement
            validated_measurement = self._apply_flow_validity(
                reduced_measurement,
                group,
                actuator_states=actuator_states,
                state_started_at=state_started_at,
                now=now,
            )
            measurements.append(
                self._apply_filter(
                    validated_measurement,
                    group.filtering,
                )
            )

        log_decisions = [
            self._log_decision(measurement, group, now=now)
            for measurement in measurements
        ]
        loggable_measurements = [
            decision.measurement
            for decision in log_decisions
            if decision.should_log
        ]

        for measurement in measurements:
            self._latest_measurements[measurement.sensor_id] = measurement

        for measurement in loggable_measurements:
            self._last_logged_at[measurement.sensor_id] = now

        return AcquisitionResult(
            group_names=(group.name,),
            measurements=tuple(measurements),
            loggable_measurements=tuple(loggable_measurements),
            log_decisions=tuple(log_decisions),
            failures=tuple(failures),
        )

    async def _read_sample(
        self,
        sensor_ids: tuple[SensorId, ...],
    ) -> tuple[list[Measurement], list[AcquisitionFailure]]:
        sensor_id_set = set(sensor_ids)
        measurements: list[Measurement] = []
        failures: list[AcquisitionFailure] = []

        for sensor_id in sensor_ids:
            driver = self._sensor_drivers.get(sensor_id)
            if driver is None:
                continue

            try:
                measurements.append(await driver.read())
            except Exception as error:
                failures.append(
                    AcquisitionFailure(
                        driver_name=driver.name,
                        sensor_id=sensor_id,
                        observed_at=self._clock.now(),
                        error=str(error),
                    )
                )

        for multi_driver in self._multi_sensor_drivers:
            driver_sensor_ids = getattr(multi_driver, "sensor_ids", None)
            if driver_sensor_ids is not None and not sensor_id_set.intersection(
                driver_sensor_ids
            ):
                continue

            try:
                for measurement in await multi_driver.read_all():
                    if measurement.sensor_id in sensor_id_set:
                        measurements.append(measurement)
            except Exception as error:
                failures.append(
                    AcquisitionFailure(
                        driver_name=multi_driver.name,
                        sensor_id=None,
                        observed_at=self._clock.now(),
                        error=str(error),
                    )
                )

        missing_sensor_ids = [
            sensor_id
            for sensor_id in sensor_ids
            if sensor_id not in {measurement.sensor_id for measurement in measurements}
            and sensor_id not in self._sensor_drivers
        ]

        for sensor_id in missing_sensor_ids:
            failures.append(
                AcquisitionFailure(
                    driver_name="unregistered",
                    sensor_id=sensor_id,
                    observed_at=self._clock.now(),
                    error=f"no sensor driver registered for {sensor_id.value}",
                )
            )

        return measurements, failures

    def _reduce_measurements(
        self,
        samples: list[Measurement],
        oversampling: OversamplingConfig,
    ) -> Measurement:
        if len(samples) == 1:
            sample = samples[0]
            return sample.model_copy(
                update={
                    "metadata": {
                        **sample.metadata,
                        "sample_count": 1,
                        "reducer": Reducer.LAST.value,
                    }
                }
            )

        values = [sample.value for sample in samples]
        last_sample = samples[-1]
        reduced_value = _reduce_values(values, oversampling.reducer)
        quality = _worst_quality(sample.quality for sample in samples)

        return Measurement(
            sensor_id=last_sample.sensor_id,
            observed_at=last_sample.observed_at,
            kind=last_sample.kind,
            value=round(reduced_value, _decimal_places(values)),
            unit=last_sample.unit,
            quality=quality,
            source_measurement_ids=[sample.id for sample in samples],
            metadata={
                **last_sample.metadata,
                "sample_count": len(samples),
                "sample_interval_s": oversampling.sample_interval_s,
                "reducer": oversampling.reducer.value,
                "raw_min": min(values),
                "raw_max": max(values),
            },
        )

    def _apply_flow_validity(
        self,
        measurement: Measurement,
        group: AcquisitionGroupConfig,
        *,
        actuator_states: Mapping[ActuatorId, ActuatorState],
        state_started_at: Mapping[ActuatorId, datetime],
        now: datetime,
    ) -> Measurement:
        if not group.requires_pump_flow:
            return measurement

        valid, reason, pump_on_seconds = self._flow_is_valid(
            group,
            actuator_states=actuator_states,
            state_started_at=state_started_at,
            now=now,
        )

        if valid:
            return measurement.model_copy(
                update={
                    "metadata": {
                        **measurement.metadata,
                        "requires_pump_flow": True,
                        "pump_on_seconds": pump_on_seconds,
                    }
                }
            )

        return measurement.model_copy(
            update={
                "quality": Quality.SUSPECT,
                "metadata": {
                    **measurement.metadata,
                    "requires_pump_flow": True,
                    "validity_reason": reason,
                    "pump_on_seconds": pump_on_seconds,
                },
            }
        )

    def _flow_is_valid(
        self,
        group: AcquisitionGroupConfig,
        *,
        actuator_states: Mapping[ActuatorId, ActuatorState],
        state_started_at: Mapping[ActuatorId, datetime],
        now: datetime,
    ) -> tuple[bool, str | None, float]:
        if actuator_states.get(ActuatorId.PUMP_MOTOR) != ActuatorState.ON:
            return False, "pump_not_running", 0.0

        if (
            group.required_pump_speed is not None
            and actuator_states.get(ActuatorId.PUMP_MOTOR_SPEED) != group.required_pump_speed
        ):
            return False, "pump_speed_not_valid", self._pump_on_seconds(state_started_at, now)

        pump_on_seconds = self._pump_on_seconds(state_started_at, now)

        if pump_on_seconds < group.min_pump_on_seconds:
            return False, "pump_not_running_long_enough", pump_on_seconds

        return True, None, pump_on_seconds

    def _apply_filter(
        self,
        measurement: Measurement,
        filtering: MeasurementFilterConfig,
    ) -> Measurement:
        if filtering.filter_type == FilterType.NONE:
            self._filter_buffers.pop(measurement.sensor_id, None)
            return measurement

        if filtering.filter_type != FilterType.BOXCAR:
            raise ValueError(f"unknown filter type: {filtering.filter_type.value}")

        if measurement.quality != Quality.GOOD:
            self._filter_buffers.pop(measurement.sensor_id, None)
            return measurement.model_copy(
                update={
                    "metadata": {
                        **measurement.metadata,
                        "filter": {
                            "type": filtering.filter_type.value,
                            "status": "skipped",
                            "reason": f"quality_{measurement.quality.value}",
                            "raw_latest": measurement.value,
                        },
                    }
                }
            )

        buffer = [
            *self._filter_buffers.get(measurement.sensor_id, []),
            measurement,
        ]
        buffer = _trim_filter_buffer(buffer, filtering, measurement.observed_at)
        self._filter_buffers[measurement.sensor_id] = buffer

        filter_metadata = {
            "type": filtering.filter_type.value,
            "status": "filtered",
            "window_samples": filtering.window_samples,
            "window_seconds": filtering.window_seconds,
            "min_samples": filtering.min_samples,
            "sample_count": len(buffer),
            "raw_latest": measurement.value,
        }

        if len(buffer) < filtering.min_samples:
            return measurement.model_copy(
                update={
                    "metadata": {
                        **measurement.metadata,
                        "filter": {
                            **filter_metadata,
                            "status": "warming_up",
                        },
                    }
                }
            )

        values = [sample.value for sample in buffer]
        return measurement.model_copy(
            update={
                "value": round(mean(values), _decimal_places(values)),
                "source_measurement_ids": [sample.id for sample in buffer],
                "metadata": {
                    **measurement.metadata,
                    "filter": {
                        **filter_metadata,
                        "min": min(values),
                        "max": max(values),
                    },
                },
            }
        )

    def _pump_on_seconds(
        self,
        state_started_at: Mapping[ActuatorId, datetime],
        now: datetime,
    ) -> float:
        started_at = state_started_at.get(ActuatorId.PUMP_MOTOR)

        if started_at is None:
            return 0.0

        return max(0.0, (now - started_at).total_seconds())

    def _log_decision(
        self,
        measurement: Measurement,
        group: AcquisitionGroupConfig,
        *,
        now: datetime,
    ) -> MeasurementLogDecision:
        if group.requires_pump_flow and measurement.quality != Quality.GOOD:
            return MeasurementLogDecision(
                measurement=measurement,
                should_log=False,
                reason=str(measurement.metadata.get("validity_reason", "invalid_flow")),
            )

        last_logged_at = self._last_logged_at.get(measurement.sensor_id)
        if last_logged_at is not None:
            elapsed_s = (now - last_logged_at).total_seconds()
            if elapsed_s < 0:
                return MeasurementLogDecision(
                    measurement=measurement,
                    should_log=True,
                    reason="clock_moved_backwards",
                )
            if elapsed_s < group.log_interval_s:
                return MeasurementLogDecision(
                    measurement=measurement,
                    should_log=False,
                    reason="log_interval_not_due",
                )

        return MeasurementLogDecision(measurement=measurement, should_log=True)

    def _group_is_due(self, group: AcquisitionGroupConfig, now: datetime) -> bool:
        last_read_at = self._last_read_at.get(group.name)

        if last_read_at is None:
            return True

        return (now - last_read_at).total_seconds() >= group.read_interval_s

    def _validate_config(self) -> None:
        seen_group_names: set[str] = set()
        seen_sensor_ids: dict[SensorId, str] = {}

        for group in self._config.groups:
            if group.name in seen_group_names:
                raise ValueError(f"duplicate acquisition group: {group.name}")

            seen_group_names.add(group.name)

            for sensor_id in group.sensor_ids:
                if sensor_id in seen_sensor_ids:
                    raise ValueError(
                        f"sensor {sensor_id.value} is configured in both "
                        f"{seen_sensor_ids[sensor_id]} and {group.name}"
                    )

                seen_sensor_ids[sensor_id] = group.name


def load_acquisition_config(path: str | Path) -> AcquisitionConfig:
    with Path(path).open("r", encoding="utf-8") as config_file:
        data = yaml.safe_load(config_file) or {}

    if not isinstance(data, Mapping):
        raise ValueError("acquisition config file must contain a mapping")

    return AcquisitionConfig.from_mapping(data)


def _group_from_mapping(
    group_name: str,
    data: Mapping[str, Any],
) -> AcquisitionGroupConfig:
    oversampling_data = _mapping_value(data, "oversample", default={})
    filter_data = _mapping_value(data, "filter", default={})
    required_pump_speed = _optional_actuator_state(data.get("required_pump_speed"))

    return AcquisitionGroupConfig(
        name=group_name,
        sensor_ids=tuple(
            _sensor_id_value(sensor_id)
            for sensor_id in _string_list_value(data, "sensor_ids")
        ),
        read_interval_s=_float_value(data, "read_interval_s", 1.0),
        log_interval_s=_float_value(data, "log_interval_s", 60.0),
        requires_pump_flow=_bool_value(data, "requires_pump_flow", False),
        min_pump_on_seconds=_float_value(data, "min_pump_on_seconds", 0.0),
        required_pump_speed=required_pump_speed,
        oversampling=OversamplingConfig(
            sample_count=_int_value(oversampling_data, "sample_count", 1),
            sample_interval_s=_float_value(oversampling_data, "sample_interval_s", 0.0),
            reducer=_reducer_value(oversampling_data, "reducer", Reducer.LAST),
        ),
        filtering=MeasurementFilterConfig(
            filter_type=_filter_type_value(filter_data, "type", FilterType.NONE),
            window_samples=_optional_int_value(filter_data, "window_samples"),
            window_seconds=_optional_float_value(filter_data, "window_seconds"),
            min_samples=_int_value(filter_data, "min_samples", 1),
        ),
    )


def _reduce_values(values: list[float], reducer: Reducer) -> float:
    if reducer == Reducer.LAST:
        return values[-1]

    if reducer == Reducer.MEAN:
        return mean(values)

    if reducer == Reducer.MEDIAN:
        return median(values)

    if reducer == Reducer.TRIMMED_MEAN:
        if len(values) < 3:
            return mean(values)

        trimmed_values = sorted(values)[1:-1]
        return mean(trimmed_values)

    raise ValueError(f"unknown reducer: {reducer.value}")


def _worst_quality(qualities: Iterable[Quality]) -> Quality:
    quality_order = {
        Quality.GOOD: 0,
        Quality.SUSPECT: 1,
        Quality.BAD: 2,
        Quality.MISSING: 3,
    }

    return max(qualities, key=lambda quality: quality_order[quality])


def _trim_filter_buffer(
    buffer: list[Measurement],
    filtering: MeasurementFilterConfig,
    observed_at: datetime,
) -> list[Measurement]:
    if filtering.window_seconds is not None:
        cutoff = observed_at - timedelta(seconds=filtering.window_seconds)
        buffer = [
            measurement
            for measurement in buffer
            if measurement.observed_at >= cutoff
        ]

    if (
        filtering.window_samples is not None
        and len(buffer) > filtering.window_samples
    ):
        buffer = buffer[-filtering.window_samples :]

    return buffer


def _decimal_places(values: list[float]) -> int:
    decimal_counts = []

    for value in values:
        text = format(value, "f").rstrip("0")
        if "." not in text:
            decimal_counts.append(0)
            continue

        decimal_counts.append(len(text.rsplit(".", maxsplit=1)[1]))

    return max(decimal_counts, default=3)


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


def _float_value(data: Mapping[str, Any], key: str, default: float) -> float:
    value = data.get(key, default)

    if not isinstance(value, int | float):
        raise ValueError(f"{key} must be a number")

    return float(value)


def _int_value(data: Mapping[str, Any], key: str, default: int) -> int:
    value = data.get(key, default)

    if not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")

    return value


def _optional_int_value(data: Mapping[str, Any], key: str) -> int | None:
    value = data.get(key)

    if value is None:
        return None

    if not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")

    return value


def _bool_value(data: Mapping[str, Any], key: str, default: bool) -> bool:
    value = data.get(key, default)

    if not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false")

    return value


def _optional_float_value(data: Mapping[str, Any], key: str) -> float | None:
    value = data.get(key)

    if value is None:
        return None

    if not isinstance(value, int | float):
        raise ValueError(f"{key} must be a number")

    return float(value)


def _string_list_value(data: Mapping[str, Any], key: str) -> list[str]:
    value = data.get(key)

    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")

    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{key} entries must be strings")

    return value


def _sensor_id_value(value: str) -> SensorId:
    return SensorId(value)


def _optional_actuator_state(value: object) -> ActuatorState | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise ValueError("required_pump_speed must be low, high, or omitted")

    return ActuatorState(value)


def _reducer_value(data: Mapping[str, Any], key: str, default: Reducer) -> Reducer:
    value = data.get(key, default.value)

    if not isinstance(value, str):
        raise ValueError(f"{key} must be a reducer string")

    return Reducer(value)


def _filter_type_value(
    data: Mapping[str, Any],
    key: str,
    default: FilterType,
) -> FilterType:
    value = data.get(key, default.value)

    if not isinstance(value, str):
        raise ValueError(f"{key} must be a filter type string")

    return FilterType(value)
