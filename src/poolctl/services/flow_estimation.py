from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from poolctl.domain.models import ActuatorId, ActuatorState, Measurement, SensorId


@dataclass(frozen=True)
class PumpPressureFlowModelConfig:
    """
    Pressure-to-flow model coefficients.

    pressure_psi = pressure_scale_psi * (c_no_flow - c_dynamic * flow_gpm^2)
    """

    pressure_scale_psi: float = 0.4335
    c_dynamic: float = 0.00525
    c_no_flow_low: float = 22.25
    c_no_flow_high: float = 93.5

    def __post_init__(self) -> None:
        if self.pressure_scale_psi <= 0:
            raise ValueError("pressure_scale_psi must be greater than zero")
        if self.c_dynamic <= 0:
            raise ValueError("c_dynamic must be greater than zero")


@dataclass(frozen=True)
class LinearPressureFlowModelConfig:
    """
    Quadratic pressure-to-flow model:

    pressure_psi = a + (b * flow_gpm^2)
    flow_gpm = sqrt((pressure_psi - a) / b)
    """

    a: float = 0.0
    b: float = 1.0

    def __post_init__(self) -> None:
        if self.b <= 0:
            raise ValueError("quadratic flow model coefficient b must be greater than zero")


@dataclass(frozen=True)
class FlowEstimationConfig:
    """
    Configurable flow model constants.
    """

    pump_pressure_model: PumpPressureFlowModelConfig = PumpPressureFlowModelConfig()
    return_flow_model: LinearPressureFlowModelConfig = LinearPressureFlowModelConfig()
    bubbler_flow_model: LinearPressureFlowModelConfig = LinearPressureFlowModelConfig()
    booster_flow_model: LinearPressureFlowModelConfig = LinearPressureFlowModelConfig()
    filter_restriction_clean: float = 1.0
    filter_restriction_dirty: float = 3.0

    def __post_init__(self) -> None:
        if self.filter_restriction_dirty <= self.filter_restriction_clean:
            raise ValueError("filter_restriction_dirty must be greater than filter_restriction_clean")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> FlowEstimationConfig:
        section = _mapping_value(data, "flow_estimation", default={})
        pump_section = _mapping_value(section, "pump_pressure", default={})
        branch_section = _mapping_value(section, "branch_pressure", default={})
        filter_section = _mapping_value(section, "filter_restriction", default={})
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
            return_flow_model=_linear_model_from_mapping(
                _mapping_value(branch_section, "return_flow", default={}),
                default=LinearPressureFlowModelConfig(),
            ),
            bubbler_flow_model=_linear_model_from_mapping(
                _mapping_value(branch_section, "bubbler_flow", default={}),
                default=LinearPressureFlowModelConfig(),
            ),
            booster_flow_model=_linear_model_from_mapping(
                _mapping_value(branch_section, "booster_flow", default={}),
                default=LinearPressureFlowModelConfig(),
            ),
            filter_restriction_clean=_float_value(filter_section, "clean_value", 1.0),
            filter_restriction_dirty=_float_value(filter_section, "dirty_value", 3.0),
        )


@dataclass(frozen=True)
class FlowEstimates:
    """
    Placeholder flow estimate variables.

    These fields are intentionally present now so the GUI and downstream
    interfaces can stabilize before pressure-to-flow equations are added.
    """

    pump_flow_gpm: float | None = None
    pump_flow_low_gpm: float | None = None
    pump_flow_high_gpm: float | None = None
    booster_flow_gpm: float | None = None
    return_flow_gpm: float | None = None
    bubbler_flow_gpm: float | None = None
    cleaner_flow_gpm: float | None = None
    filter_restriction_metric: float | None = None
    filter_restriction_percent: float | None = None

    def as_payload(self) -> dict[str, dict[str, float | str | None]]:
        return {
            "pump_flow_gpm": _flow_payload(self.pump_flow_gpm),
            "pump_flow_low_gpm": _flow_payload(self.pump_flow_low_gpm),
            "pump_flow_high_gpm": _flow_payload(self.pump_flow_high_gpm),
            "booster_flow_gpm": _flow_payload(self.booster_flow_gpm),
            "return_flow_gpm": _flow_payload(self.return_flow_gpm),
            "bubbler_flow_gpm": _flow_payload(self.bubbler_flow_gpm),
            "cleaner_flow_gpm": _flow_payload(self.cleaner_flow_gpm),
            "filter_restriction_metric": _restriction_metric_payload(self.filter_restriction_metric),
            "filter_restriction_percent": _restriction_percent_payload(self.filter_restriction_percent),
        }


def estimate_flows(
    *,
    measurements: Mapping[SensorId, Measurement],
    actuator_states: Mapping[ActuatorId, ActuatorState],
    config: FlowEstimationConfig = FlowEstimationConfig(),
) -> FlowEstimates:
    pump_flow_gpm: float | None = None
    return_flow_gpm: float | None = None
    bubbler_flow_gpm: float | None = None
    booster_flow_gpm: float | None = None
    pump_state = actuator_states.get(ActuatorId.PUMP_MOTOR)
    speed_state = actuator_states.get(ActuatorId.PUMP_MOTOR_SPEED)
    pump_measurement = measurements.get(SensorId.PUMP_OUTPUT_PSI)
    pump_pressure = pump_measurement.value if pump_measurement is not None else None

    if pump_state != ActuatorState.ON:
        pump_flow_gpm = 0.0
        return_flow_gpm = 0.0
        bubbler_flow_gpm = 0.0
        booster_flow_gpm = 0.0
    elif isinstance(pump_pressure, int | float):
        model = config.pump_pressure_model
        if speed_state == ActuatorState.LOW:
            pump_flow_gpm = _pump_flow_from_pressure(
                pressure_psi=float(pump_pressure),
                c_no_flow=model.c_no_flow_low,
                c_dynamic=model.c_dynamic,
                pressure_scale_psi=model.pressure_scale_psi,
            )
            return_flow_gpm = _quadratic_flow_from_pressure(
                pressure_psi=_measurement_value(measurements, SensorId.RETURN_PSI),
                model=config.return_flow_model,
            )
            bubbler_flow_gpm = _quadratic_flow_from_pressure(
                pressure_psi=_measurement_value(measurements, SensorId.BUBBLER_PSI),
                model=config.bubbler_flow_model,
            )
            booster_flow_gpm = _quadratic_flow_from_pressure(
                pressure_psi=_measurement_value(measurements, SensorId.BOOSTER_PSI),
                model=config.booster_flow_model,
            )
            return _with_filter_restriction(
                measurements=measurements,
                config=config,
                estimates=FlowEstimates(
                    pump_flow_gpm=pump_flow_gpm,
                    pump_flow_low_gpm=pump_flow_gpm,
                    return_flow_gpm=return_flow_gpm,
                    bubbler_flow_gpm=bubbler_flow_gpm,
                    booster_flow_gpm=booster_flow_gpm,
                ),
            )
        if speed_state == ActuatorState.HIGH:
            pump_flow_gpm = _pump_flow_from_pressure(
                pressure_psi=float(pump_pressure),
                c_no_flow=model.c_no_flow_high,
                c_dynamic=model.c_dynamic,
                pressure_scale_psi=model.pressure_scale_psi,
            )
            return_flow_gpm = _quadratic_flow_from_pressure(
                pressure_psi=_measurement_value(measurements, SensorId.RETURN_PSI),
                model=config.return_flow_model,
            )
            bubbler_flow_gpm = _quadratic_flow_from_pressure(
                pressure_psi=_measurement_value(measurements, SensorId.BUBBLER_PSI),
                model=config.bubbler_flow_model,
            )
            booster_flow_gpm = _quadratic_flow_from_pressure(
                pressure_psi=_measurement_value(measurements, SensorId.BOOSTER_PSI),
                model=config.booster_flow_model,
            )
            return _with_filter_restriction(
                measurements=measurements,
                config=config,
                estimates=FlowEstimates(
                    pump_flow_gpm=pump_flow_gpm,
                    pump_flow_high_gpm=pump_flow_gpm,
                    return_flow_gpm=return_flow_gpm,
                    bubbler_flow_gpm=bubbler_flow_gpm,
                    booster_flow_gpm=booster_flow_gpm,
                ),
            )

    if pump_state == ActuatorState.ON:
        return_flow_gpm = _quadratic_flow_from_pressure(
            pressure_psi=_measurement_value(measurements, SensorId.RETURN_PSI),
            model=config.return_flow_model,
        )
        bubbler_flow_gpm = _quadratic_flow_from_pressure(
            pressure_psi=_measurement_value(measurements, SensorId.BUBBLER_PSI),
            model=config.bubbler_flow_model,
        )
        booster_flow_gpm = _quadratic_flow_from_pressure(
            pressure_psi=_measurement_value(measurements, SensorId.BOOSTER_PSI),
            model=config.booster_flow_model,
        )

    return _with_filter_restriction(
        measurements=measurements,
        config=config,
        estimates=FlowEstimates(
            pump_flow_gpm=pump_flow_gpm,
            return_flow_gpm=return_flow_gpm,
            bubbler_flow_gpm=bubbler_flow_gpm,
            booster_flow_gpm=booster_flow_gpm,
        ),
    )


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


def _quadratic_flow_from_pressure(
    *,
    pressure_psi: float | None,
    model: LinearPressureFlowModelConfig,
) -> float | None:
    if pressure_psi is None:
        return None
    term = (pressure_psi - model.a) / model.b
    if term <= 0:
        return 0.0
    return math.sqrt(term)


def _with_filter_restriction(
    *,
    measurements: Mapping[SensorId, Measurement],
    config: FlowEstimationConfig,
    estimates: FlowEstimates,
) -> FlowEstimates:
    flow = estimates.pump_flow_gpm
    if not isinstance(flow, int | float) or flow <= 0:
        return estimates

    pump_output = _measurement_value(measurements, SensorId.PUMP_OUTPUT_PSI)
    filter_output = _measurement_value(measurements, SensorId.FILTER_OUTPUT_PSI)
    if pump_output is None or filter_output is None:
        return estimates

    metric = 10000.0 * (pump_output - filter_output) / (flow ** 2)
    percent = _restriction_percent(
        metric=metric,
        clean_value=config.filter_restriction_clean,
        dirty_value=config.filter_restriction_dirty,
    )
    return FlowEstimates(
        pump_flow_gpm=estimates.pump_flow_gpm,
        pump_flow_low_gpm=estimates.pump_flow_low_gpm,
        pump_flow_high_gpm=estimates.pump_flow_high_gpm,
        booster_flow_gpm=estimates.booster_flow_gpm,
        return_flow_gpm=estimates.return_flow_gpm,
        bubbler_flow_gpm=estimates.bubbler_flow_gpm,
        cleaner_flow_gpm=estimates.cleaner_flow_gpm,
        filter_restriction_metric=metric,
        filter_restriction_percent=percent,
    )


def _measurement_value(
    measurements: Mapping[SensorId, Measurement],
    sensor_id: SensorId,
) -> float | None:
    measurement = measurements.get(sensor_id)
    if measurement is None:
        return None
    if not isinstance(measurement.value, int | float):
        return None
    return float(measurement.value)


def _restriction_percent(
    *,
    metric: float,
    clean_value: float,
    dirty_value: float,
) -> float:
    if metric <= clean_value:
        return 0.0
    if metric >= dirty_value:
        return 100.0
    span = dirty_value - clean_value
    return 100.0 * ((metric - clean_value) / span)


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


def _restriction_metric_payload(value: float | None) -> dict[str, float | str | None]:
    if value is None:
        return {
            "value": None,
            "unit": "restriction_index",
            "display": "-- R",
        }
    return {
        "value": value,
        "unit": "restriction_index",
        "display": f"{value:.2f} R",
    }


def _restriction_percent_payload(value: float | None) -> dict[str, float | str | None]:
    if value is None:
        return {
            "value": None,
            "unit": "percent",
            "display": "--%",
        }
    return {
        "value": value,
        "unit": "percent",
        "display": f"{value:.0f}%",
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


def _linear_model_from_mapping(
    data: Mapping[str, Any],
    *,
    default: LinearPressureFlowModelConfig,
) -> LinearPressureFlowModelConfig:
    return LinearPressureFlowModelConfig(
        a=_float_value(data, "a", default.a),
        b=_float_value(data, "b", default.b),
    )
