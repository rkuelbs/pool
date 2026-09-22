"""
Derived hydraulic calculations.

Pump flow estimates use the pump-output pressure sensor and configured pump
curve constants. Filter loading is a standardized flow-loss proxy: during an
uninterrupted pump-HIGH, booster-OFF test period, the estimator ignores startup
samples, averages fresh pump-output pressure, converts that reference pressure
through the same hydraulic model used for live flow, and latches the completed
result until the next valid test.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from poolctl.domain.models import ActuatorId, ActuatorState, Measurement, Quality, SensorId


@dataclass(frozen=True)
class PumpPressureFlowModelConfig:
    """
    Pressure-to-flow model coefficients.

    pressure_psi = pressure_scale_psi * (c_no_flow - c_dynamic * flow_gpm^2)
    """

    pressure_scale_psi: float = 0.4335
    c_dynamic: float = 0.00525
    c_suction: float = 0.00035
    c_no_flow_low: float = 22.25
    c_no_flow_high: float = 93.5

    def __post_init__(self) -> None:
        if self.pressure_scale_psi <= 0:
            raise ValueError("pressure_scale_psi must be greater than zero")
        if self.c_dynamic <= 0:
            raise ValueError("c_dynamic must be greater than zero")
        if self.c_suction < 0:
            raise ValueError("c_suction must be greater than or equal to zero")


@dataclass(frozen=True)
class FilterLoadingConfig:
    enabled: bool = True
    clean_flow_gpm: float | None = None
    yellow_flow_loss_percent: float = 10.0
    red_flow_loss_percent: float = 15.0
    stabilization_seconds: float = 60.0
    averaging_seconds: float = 120.0
    max_pressure_age_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.clean_flow_gpm is not None and self.clean_flow_gpm <= 0:
            raise ValueError("filter_loading.clean_flow_gpm must be null or > 0")
        if self.yellow_flow_loss_percent < 0:
            raise ValueError("filter_loading.yellow_flow_loss_percent must be >= 0")
        if self.red_flow_loss_percent <= self.yellow_flow_loss_percent:
            raise ValueError(
                "filter_loading.red_flow_loss_percent must be greater than yellow_flow_loss_percent"
            )
        if self.stabilization_seconds < 0:
            raise ValueError("filter_loading.stabilization_seconds must be >= 0")
        if self.averaging_seconds <= 0:
            raise ValueError("filter_loading.averaging_seconds must be > 0")
        if self.max_pressure_age_seconds < 0:
            raise ValueError("filter_loading.max_pressure_age_seconds must be >= 0")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> FilterLoadingConfig:
        section = _mapping_value(data, "filter_loading", default={})
        return cls(
            enabled=_bool_value(section, "enabled", cls.enabled),
            clean_flow_gpm=_optional_float_value(section, "clean_flow_gpm"),
            yellow_flow_loss_percent=_float_value(
                section,
                "yellow_flow_loss_percent",
                cls.yellow_flow_loss_percent,
            ),
            red_flow_loss_percent=_float_value(
                section,
                "red_flow_loss_percent",
                cls.red_flow_loss_percent,
            ),
            stabilization_seconds=_float_value(
                section,
                "stabilization_seconds",
                cls.stabilization_seconds,
            ),
            averaging_seconds=_float_value(
                section,
                "averaging_seconds",
                cls.averaging_seconds,
            ),
            max_pressure_age_seconds=_float_value(
                section,
                "max_pressure_age_seconds",
                cls.max_pressure_age_seconds,
            ),
        )


@dataclass(frozen=True)
class FlowEstimationConfig:
    """
    Configurable flow model constants.
    """

    pump_pressure_model: PumpPressureFlowModelConfig = PumpPressureFlowModelConfig()
    filter_loading: FilterLoadingConfig = FilterLoadingConfig()

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> FlowEstimationConfig:
        section = _mapping_value(data, "flow_estimation", default={})
        pump_section = _mapping_value(section, "pump_pressure", default={})
        return cls(
            pump_pressure_model=PumpPressureFlowModelConfig(
                pressure_scale_psi=_float_value(
                    pump_section,
                    "pressure_scale_psi",
                    PumpPressureFlowModelConfig.pressure_scale_psi,
                ),
                c_dynamic=_float_value(
                    pump_section,
                    "c_dynamic",
                    PumpPressureFlowModelConfig.c_dynamic,
                ),
                c_suction=_float_value(
                    pump_section,
                    "c_suction",
                    PumpPressureFlowModelConfig.c_suction,
                ),
                c_no_flow_low=_float_value(
                    pump_section,
                    "c_no_flow_low",
                    PumpPressureFlowModelConfig.c_no_flow_low,
                ),
                c_no_flow_high=_float_value(
                    pump_section,
                    "c_no_flow_high",
                    PumpPressureFlowModelConfig.c_no_flow_high,
                ),
            ),
            filter_loading=FilterLoadingConfig.from_mapping(data),
        )


@dataclass(frozen=True)
class FilterLoadingResult:
    reference_psi: float
    estimated_flow_gpm: float
    clean_flow_gpm: float | None
    raw_flow_loss_percent: float | None
    flow_loss_percent: float | None
    status: str
    completed_at: datetime
    sample_count: int
    averaging_seconds: float
    yellow_flow_loss_percent: float
    red_flow_loss_percent: float

    @property
    def calibrated(self) -> bool:
        return self.clean_flow_gpm is not None and self.raw_flow_loss_percent is not None

    def as_payload(self, *, now: datetime | None = None) -> dict[str, Any]:
        age_seconds = (
            max(0.0, (now - self.completed_at).total_seconds())
            if now is not None
            else None
        )
        return {
            "available": True,
            "calibrated": self.calibrated,
            "reference_psi": self.reference_psi,
            "filter_reference_psi": self.reference_psi,
            "estimated_flow_gpm": self.estimated_flow_gpm,
            "filter_reference_flow_gpm": self.estimated_flow_gpm,
            "clean_flow_gpm": self.clean_flow_gpm,
            "raw_flow_loss_percent": self.raw_flow_loss_percent,
            "flow_loss_percent": self.flow_loss_percent,
            "filter_flow_loss_percent": self.flow_loss_percent,
            "status": self.status,
            "completed_at": self.completed_at.isoformat(),
            "last_completed_at": self.completed_at.isoformat(),
            "age_seconds": age_seconds,
            "sample_count": self.sample_count,
            "averaging_seconds": self.averaging_seconds,
            "yellow_flow_loss_percent": self.yellow_flow_loss_percent,
            "red_flow_loss_percent": self.red_flow_loss_percent,
            "reference_display": f"{self.reference_psi:.1f} psi",
            "estimated_flow_display": f"{self.estimated_flow_gpm:.1f} gpm",
            "clean_flow_display": (
                f"{self.clean_flow_gpm:.1f} gpm"
                if self.clean_flow_gpm is not None
                else "Not calibrated"
            ),
            "flow_loss_display": (
                f"{self.flow_loss_percent:.1f}%"
                if self.flow_loss_percent is not None
                else "--"
            ),
        }


@dataclass(frozen=True)
class FilterLoadingUpdate:
    result: FilterLoadingResult | None
    completed_this_tick: bool = False
    qualifying: bool = False
    reason: str = "not evaluated"
    qualifying_started_at: datetime | None = None

    def as_payload(self, *, now: datetime | None = None) -> dict[str, Any]:
        result_payload = (
            self.result.as_payload(now=now)
            if self.result is not None
            else {
                "available": False,
                "calibrated": False,
                "reference_psi": None,
                "filter_reference_psi": None,
                "estimated_flow_gpm": None,
                "filter_reference_flow_gpm": None,
                "clean_flow_gpm": None,
                "raw_flow_loss_percent": None,
                "flow_loss_percent": None,
                "filter_flow_loss_percent": None,
                "status": "uncalibrated",
                "completed_at": None,
                "last_completed_at": None,
                "age_seconds": None,
                "sample_count": 0,
                "averaging_seconds": None,
                "yellow_flow_loss_percent": None,
                "red_flow_loss_percent": None,
                "reference_display": "-- psi",
                "estimated_flow_display": "-- gpm",
                "clean_flow_display": "Not calibrated",
                "flow_loss_display": "--",
            }
        )
        return {
            **result_payload,
            "qualifying": self.qualifying,
            "reason": self.reason,
            "completed_this_tick": self.completed_this_tick,
            "qualifying_started_at": (
                self.qualifying_started_at.isoformat()
                if self.qualifying_started_at is not None
                else None
            ),
        }


@dataclass(frozen=True)
class FlowEstimates:
    pump_flow_gpm: float | None = None
    pump_dynamic_head_psi: float | None = None
    pump_flow_low_gpm: float | None = None
    pump_flow_high_gpm: float | None = None
    filter_loading: FilterLoadingUpdate = field(
        default_factory=lambda: FilterLoadingUpdate(result=None)
    )

    def as_payload(self) -> dict[str, dict[str, Any]]:
        return {
            "pump_flow_gpm": _flow_payload(self.pump_flow_gpm),
            "pump_dynamic_head_psi": _pressure_payload(self.pump_dynamic_head_psi),
            "pump_flow_low_gpm": _flow_payload(self.pump_flow_low_gpm),
            "pump_flow_high_gpm": _flow_payload(self.pump_flow_high_gpm),
            "filter_reference_psi": _filter_reference_payload(
                self.filter_loading.result
            ),
            "filter_reference_flow_gpm": _filter_reference_flow_payload(
                self.filter_loading.result
            ),
            "filter_flow_loss_percent": _filter_flow_loss_percent_payload(
                self.filter_loading.result
            ),
            "filter_loading": self.filter_loading.as_payload(),
        }


class FilterLoadingEstimator:
    def __init__(
        self,
        config: FilterLoadingConfig,
        *,
        pump_pressure_model: PumpPressureFlowModelConfig = PumpPressureFlowModelConfig(),
    ) -> None:
        self.config = config
        self.pump_pressure_model = pump_pressure_model
        self._qualifying_started_at: datetime | None = None
        self._samples: list[tuple[datetime, float]] = []
        self._completed_for_session = False
        self._last_result: FilterLoadingResult | None = None

    @property
    def last_result(self) -> FilterLoadingResult | None:
        return self._last_result

    def apply_config(
        self,
        config: FilterLoadingConfig,
        *,
        pump_pressure_model: PumpPressureFlowModelConfig | None = None,
    ) -> None:
        self.config = config
        if pump_pressure_model is not None:
            self.pump_pressure_model = pump_pressure_model
        self._reset_session()
        self._last_result = self._recompute_result(self._last_result)

    def update(
        self,
        *,
        now: datetime,
        measurements: Mapping[SensorId, Measurement],
        actuator_states: Mapping[ActuatorId, ActuatorState],
    ) -> FilterLoadingUpdate:
        if not self.config.enabled:
            self._reset_session()
            return FilterLoadingUpdate(result=self._last_result, reason="disabled")

        measurement = measurements.get(SensorId.PUMP_OUTPUT_PSI)
        pressure = _fresh_good_pressure(
            measurement,
            now=now,
            max_age_seconds=self.config.max_pressure_age_seconds,
        )
        qualifying = (
            actuator_states.get(ActuatorId.PUMP_MOTOR) == ActuatorState.ON
            and actuator_states.get(ActuatorId.PUMP_MOTOR_SPEED) == ActuatorState.HIGH
            and actuator_states.get(ActuatorId.BOOSTER_PUMP, ActuatorState.OFF)
            == ActuatorState.OFF
            and pressure is not None
        )

        if not qualifying:
            reason = _filter_loading_nonqualifying_reason(
                actuator_states=actuator_states,
                pressure=pressure,
            )
            self._reset_session()
            return FilterLoadingUpdate(
                result=self._last_result,
                qualifying=False,
                reason=reason,
            )

        if self._qualifying_started_at is None:
            self._qualifying_started_at = now
            self._samples = []
            self._completed_for_session = False

        assert pressure is not None
        elapsed_s = (now - self._qualifying_started_at).total_seconds()
        if elapsed_s < self.config.stabilization_seconds:
            return FilterLoadingUpdate(
                result=self._last_result,
                qualifying=True,
                reason="stabilizing",
                qualifying_started_at=self._qualifying_started_at,
            )

        self._samples.append((now, pressure))
        cutoff = now.timestamp() - self.config.averaging_seconds
        self._samples = [
            (sampled_at, value)
            for sampled_at, value in self._samples
            if sampled_at.timestamp() >= cutoff
        ]

        if self._completed_for_session:
            return FilterLoadingUpdate(
                result=self._last_result,
                qualifying=True,
                reason="completed for current qualifying session",
                qualifying_started_at=self._qualifying_started_at,
            )

        if not self._has_sufficient_average(now):
            return FilterLoadingUpdate(
                result=self._last_result,
                qualifying=True,
                reason="averaging",
                qualifying_started_at=self._qualifying_started_at,
            )

        reference_psi = sum(value for _, value in self._samples) / len(self._samples)
        result = self._build_result(
            reference_psi=reference_psi,
            completed_at=now,
            sample_count=len(self._samples),
            averaging_seconds=self.config.averaging_seconds,
        )
        self._last_result = result
        self._completed_for_session = True
        return FilterLoadingUpdate(
            result=result,
            completed_this_tick=True,
            qualifying=True,
            reason="completed",
            qualifying_started_at=self._qualifying_started_at,
        )

    def _has_sufficient_average(self, now: datetime) -> bool:
        if not self._samples:
            return False
        first_sampled_at = self._samples[0][0]
        return (now - first_sampled_at).total_seconds() >= self.config.averaging_seconds

    def _build_result(
        self,
        *,
        reference_psi: float,
        completed_at: datetime,
        sample_count: int,
        averaging_seconds: float,
    ) -> FilterLoadingResult:
        estimated_flow_gpm = estimate_pump_flow_from_pressure(
            pressure_psi=reference_psi,
            speed=ActuatorState.HIGH,
            model=self.pump_pressure_model,
        )
        if estimated_flow_gpm is None:
            raise ValueError("filter loading requires a high-speed pump flow estimate")
        raw_flow_loss_percent: float | None = None
        flow_loss_percent: float | None = None
        status = "uncalibrated"
        if self.config.clean_flow_gpm is not None:
            raw_flow_loss_percent = 100.0 * (
                1.0 - (estimated_flow_gpm / self.config.clean_flow_gpm)
            )
            flow_loss_percent = min(max(raw_flow_loss_percent, 0.0), 100.0)
            status = filter_flow_loss_status(
                raw_flow_loss_percent,
                yellow_flow_loss_percent=self.config.yellow_flow_loss_percent,
                red_flow_loss_percent=self.config.red_flow_loss_percent,
            )

        return FilterLoadingResult(
            reference_psi=round(reference_psi, 4),
            estimated_flow_gpm=round(estimated_flow_gpm, 4),
            clean_flow_gpm=(
                round(self.config.clean_flow_gpm, 4)
                if self.config.clean_flow_gpm is not None
                else None
            ),
            raw_flow_loss_percent=(
                round(raw_flow_loss_percent, 4)
                if raw_flow_loss_percent is not None
                else None
            ),
            flow_loss_percent=(
                round(flow_loss_percent, 4)
                if flow_loss_percent is not None
                else None
            ),
            status=status,
            completed_at=completed_at,
            sample_count=sample_count,
            averaging_seconds=averaging_seconds,
            yellow_flow_loss_percent=self.config.yellow_flow_loss_percent,
            red_flow_loss_percent=self.config.red_flow_loss_percent,
        )

    def _recompute_result(
        self,
        result: FilterLoadingResult | None,
    ) -> FilterLoadingResult | None:
        if result is None:
            return None
        return self._build_result(
            reference_psi=result.reference_psi,
            completed_at=result.completed_at,
            sample_count=result.sample_count,
            averaging_seconds=result.averaging_seconds,
        )

    def _reset_session(self) -> None:
        self._qualifying_started_at = None
        self._samples = []
        self._completed_for_session = False


def estimate_flows(
    *,
    measurements: Mapping[SensorId, Measurement],
    actuator_states: Mapping[ActuatorId, ActuatorState],
    config: FlowEstimationConfig = FlowEstimationConfig(),
    filter_loading: FilterLoadingUpdate | None = None,
) -> FlowEstimates:
    pump_flow_gpm: float | None = None
    pump_dynamic_head_psi: float | None = None
    pump_state = actuator_states.get(ActuatorId.PUMP_MOTOR)
    speed_state = actuator_states.get(ActuatorId.PUMP_MOTOR_SPEED)
    pump_pressure = _measurement_value(measurements, SensorId.PUMP_OUTPUT_PSI)

    if pump_state != ActuatorState.ON:
        pump_flow_gpm = 0.0
    elif pump_pressure is not None:
        pump_flow_gpm = estimate_pump_flow_from_pressure(
            pressure_psi=pump_pressure,
            speed=speed_state,
            model=config.pump_pressure_model,
        )

    pump_dynamic_head_psi = _pump_dynamic_head_from_pressure_and_flow(
        pump_output_pressure_psi=pump_pressure,
        flow_gpm=pump_flow_gpm,
        pressure_scale_psi=config.pump_pressure_model.pressure_scale_psi,
        c_suction=config.pump_pressure_model.c_suction,
    )

    return FlowEstimates(
        pump_flow_gpm=pump_flow_gpm,
        pump_dynamic_head_psi=pump_dynamic_head_psi,
        pump_flow_low_gpm=(
            pump_flow_gpm if speed_state == ActuatorState.LOW else None
        ),
        pump_flow_high_gpm=(
            pump_flow_gpm if speed_state == ActuatorState.HIGH else None
        ),
        filter_loading=(
            filter_loading
            if filter_loading is not None
            else FilterLoadingUpdate(result=None, reason="not evaluated")
        ),
    )


def estimate_pump_flow_from_pressure(
    *,
    pressure_psi: float,
    speed: ActuatorState | None,
    model: PumpPressureFlowModelConfig,
) -> float | None:
    if speed == ActuatorState.LOW:
        return _pump_flow_from_pressure(
            pressure_psi=pressure_psi,
            c_no_flow=model.c_no_flow_low,
            c_dynamic=model.c_dynamic,
            pressure_scale_psi=model.pressure_scale_psi,
        )
    if speed == ActuatorState.HIGH:
        return _pump_flow_from_pressure(
            pressure_psi=pressure_psi,
            c_no_flow=model.c_no_flow_high,
            c_dynamic=model.c_dynamic,
            pressure_scale_psi=model.pressure_scale_psi,
        )
    return None


def filter_flow_loss_status(
    raw_flow_loss_percent: float,
    *,
    yellow_flow_loss_percent: float,
    red_flow_loss_percent: float,
) -> str:
    if raw_flow_loss_percent >= red_flow_loss_percent:
        return "red"
    if raw_flow_loss_percent >= yellow_flow_loss_percent:
        return "yellow"
    return "green"


def _pump_flow_from_pressure(
    *,
    pressure_psi: float,
    c_no_flow: float,
    c_dynamic: float,
    pressure_scale_psi: float,
) -> float:
    term = c_no_flow - (pressure_psi / pressure_scale_psi)
    if term <= 0:
        return 0.0
    return math.sqrt(term / c_dynamic)


def _pump_dynamic_head_from_pressure_and_flow(
    *,
    pump_output_pressure_psi: float | None,
    flow_gpm: float | None,
    pressure_scale_psi: float,
    c_suction: float,
) -> float | None:
    if pump_output_pressure_psi is None or flow_gpm is None:
        return None
    if flow_gpm <= 0:
        return 0.0
    return pump_output_pressure_psi + (pressure_scale_psi * c_suction * (flow_gpm**2))


def _fresh_good_pressure(
    measurement: Measurement | None,
    *,
    now: datetime,
    max_age_seconds: float,
) -> float | None:
    if measurement is None:
        return None
    if measurement.quality != Quality.GOOD:
        return None
    age_s = max(0.0, (now - measurement.observed_at).total_seconds())
    if age_s > max_age_seconds:
        return None
    if not isinstance(measurement.value, int | float):
        return None
    value = float(measurement.value)
    if not math.isfinite(value):
        return None
    return value


def _measurement_value(
    measurements: Mapping[SensorId, Measurement],
    sensor_id: SensorId,
) -> float | None:
    measurement = measurements.get(sensor_id)
    if measurement is None:
        return None
    if not isinstance(measurement.value, int | float):
        return None
    value = float(measurement.value)
    if not math.isfinite(value):
        return None
    return value


def _filter_loading_nonqualifying_reason(
    *,
    actuator_states: Mapping[ActuatorId, ActuatorState],
    pressure: float | None,
) -> str:
    if actuator_states.get(ActuatorId.PUMP_MOTOR) != ActuatorState.ON:
        return "pump is off"
    if actuator_states.get(ActuatorId.PUMP_MOTOR_SPEED) != ActuatorState.HIGH:
        return "pump is not high speed"
    if actuator_states.get(ActuatorId.BOOSTER_PUMP, ActuatorState.OFF) != ActuatorState.OFF:
        return "booster pump is on"
    if pressure is None:
        return "fresh pump output pressure unavailable"
    return "not qualifying"


def _flow_payload(value: float | None) -> dict[str, float | str | None]:
    if value is None:
        return {
            "value": None,
            "unit": "gpm",
            "display": "-- gpm",
        }

    return {
        "value": value,
        "unit": "gpm",
        "display": f"{value:.1f} gpm",
    }


def _pressure_payload(value: float | None) -> dict[str, float | str | None]:
    if value is None:
        return {
            "value": None,
            "unit": "psi",
            "display": "-- psi",
        }

    return {
        "value": value,
        "unit": "psi",
        "display": f"{value:.1f} psi",
    }


def _filter_reference_payload(
    result: FilterLoadingResult | None,
) -> dict[str, float | str | None]:
    if result is None:
        return {
            "value": None,
            "unit": "psi",
            "display": "-- psi",
        }
    return {
        "value": result.reference_psi,
        "unit": "psi",
        "display": f"{result.reference_psi:.1f} psi",
    }


def _filter_reference_flow_payload(
    result: FilterLoadingResult | None,
) -> dict[str, float | str | None]:
    if result is None:
        return {
            "value": None,
            "unit": "gpm",
            "display": "-- gpm",
        }
    return {
        "value": result.estimated_flow_gpm,
        "unit": "gpm",
        "display": f"{result.estimated_flow_gpm:.1f} gpm",
    }


def _filter_flow_loss_percent_payload(
    result: FilterLoadingResult | None,
) -> dict[str, float | str | None]:
    if result is None or result.flow_loss_percent is None:
        return {
            "value": None,
            "raw_value": result.raw_flow_loss_percent if result is not None else None,
            "unit": "percent",
            "display": "--",
        }
    return {
        "value": result.flow_loss_percent,
        "raw_value": result.raw_flow_loss_percent,
        "unit": "percent",
        "display": f"{result.flow_loss_percent:.1f}%",
    }


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


def _optional_float_value(data: Mapping[str, Any], key: str) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, int | float):
        raise ValueError(f"{key} must be a number or null")
    return float(value)


def _bool_value(data: Mapping[str, Any], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false")
    return value
