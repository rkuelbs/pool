from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from poolctl.domain.models import Measurement, Quality, SensorId


@dataclass(frozen=True)
class CalciumSaturationIndexConfig:
    """
    Configuration for CSI (calcium saturation index) estimation.
    """

    enabled: bool = True
    temp_sensor_id: SensorId = SensorId.TEMP
    ph_sensor_id: SensorId = SensorId.RAW_PH

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> CalciumSaturationIndexConfig:
        section = _mapping_value(data, "calcium_saturation_index", default={})
        enabled = _bool_value(section, "enabled", True)
        temp_sensor = _sensor_id_value(section, "temp_sensor_id", SensorId.TEMP)
        ph_sensor = _sensor_id_value(section, "ph_sensor_id", SensorId.RAW_PH)
        return cls(
            enabled=enabled,
            temp_sensor_id=temp_sensor,
            ph_sensor_id=ph_sensor,
        )


@dataclass(frozen=True)
class CalciumSaturationInputs:
    ph: float
    temp_f: float
    calcium_hardness_ppm_caco3: float
    alkalinity_ppm_caco3: float
    tds_ppm: float


@dataclass(frozen=True)
class CalciumSaturationEstimate:
    value: float
    tc: float
    constant_c: float


def estimate_calcium_saturation_index(
    *,
    measurement_by_sensor: Mapping[SensorId, Measurement],
    lab_values: Mapping[str, float],
    config: CalciumSaturationIndexConfig = CalciumSaturationIndexConfig(),
) -> CalciumSaturationEstimate | None:
    if not config.enabled:
        return None

    ph_measurement = measurement_by_sensor.get(config.ph_sensor_id)
    temp_measurement = measurement_by_sensor.get(config.temp_sensor_id)
    if ph_measurement is None or temp_measurement is None:
        return None
    if ph_measurement.quality != Quality.GOOD or temp_measurement.quality != Quality.GOOD:
        return None

    ph = float(ph_measurement.value)
    temp_f = _temperature_to_f(temp_measurement)
    hardness = _positive_value(lab_values.get("calcium_hardness"))
    alkalinity = _positive_value(lab_values.get("alkalinity"))
    tds = _positive_value(lab_values.get("tds"))
    if temp_f is None or hardness is None or alkalinity is None or tds is None:
        return None

    tc = _temperature_correction_f(temp_f)
    constant_c = _constant_c(tds)
    value = ph + math.log10(hardness) + math.log10(alkalinity) + tc + constant_c
    return CalciumSaturationEstimate(value=value, tc=tc, constant_c=constant_c)


def _temperature_to_f(measurement: Measurement) -> float | None:
    if not isinstance(measurement.value, int | float):
        return None

    value = float(measurement.value)
    if measurement.unit == "degF":
        return value
    if measurement.unit == "degC":
        return value * 9.0 / 5.0 + 32.0
    return None


def _temperature_correction_f(temp_f: float) -> float:
    # Revised SI equation temperature correction (Wojtowicz, 1997).
    return -0.25 + (0.00825 * temp_f)


def _constant_c(tds_ppm: float) -> float:
    return -11.30 - (0.333 * math.log10(tds_ppm))


def _positive_value(value: float | int | None) -> float | None:
    if not isinstance(value, int | float):
        return None
    candidate = float(value)
    if candidate <= 0.0:
        return None
    return candidate


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


def _bool_value(data: Mapping[str, Any], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false")
    return value


def _sensor_id_value(data: Mapping[str, Any], key: str, default: SensorId) -> SensorId:
    value = data.get(key, default.value)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a sensor id string")
    return SensorId(value)
