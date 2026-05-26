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

    pressure_psi = pressure_scale_psi * (c_no_flow + c_dynamic * flow_gpm^2)
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
class FlowEstimationConfig:
    """
    Configurable flow model constants.
    """

    pump_pressure_model: PumpPressureFlowModelConfig = PumpPressureFlowModelConfig()

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
            )
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

    def as_payload(self) -> dict[str, dict[str, float | str | None]]:
        return {
            "pump_flow_gpm": _flow_payload(self.pump_flow_gpm),
            "pump_flow_low_gpm": _flow_payload(self.pump_flow_low_gpm),
            "pump_flow_high_gpm": _flow_payload(self.pump_flow_high_gpm),
            "booster_flow_gpm": _flow_payload(self.booster_flow_gpm),
            "return_flow_gpm": _flow_payload(self.return_flow_gpm),
            "bubbler_flow_gpm": _flow_payload(self.bubbler_flow_gpm),
            "cleaner_flow_gpm": _flow_payload(self.cleaner_flow_gpm),
        }


def estimate_flows(
    *,
    measurements: Mapping[SensorId, Measurement],
    actuator_states: Mapping[ActuatorId, ActuatorState],
    config: FlowEstimationConfig = FlowEstimationConfig(),
) -> FlowEstimates:
    pump_state = actuator_states.get(ActuatorId.PUMP_MOTOR)
    speed_state = actuator_states.get(ActuatorId.PUMP_MOTOR_SPEED)
    pump_measurement = measurements.get(SensorId.PUMP_OUTPUT_PSI)
    pump_pressure = pump_measurement.value if pump_measurement is not None else None

    if pump_state != ActuatorState.ON:
        return FlowEstimates(pump_flow_gpm=0.0)

    if not isinstance(pump_pressure, int | float):
        return FlowEstimates()

    model = config.pump_pressure_model
    if speed_state == ActuatorState.LOW:
        flow = _pump_flow_from_pressure(
            pressure_psi=float(pump_pressure),
            c_no_flow=model.c_no_flow_low,
            c_dynamic=model.c_dynamic,
            pressure_scale_psi=model.pressure_scale_psi,
        )
        return FlowEstimates(
            pump_flow_gpm=flow,
            pump_flow_low_gpm=flow,
        )

    if speed_state == ActuatorState.HIGH:
        flow = _pump_flow_from_pressure(
            pressure_psi=float(pump_pressure),
            c_no_flow=model.c_no_flow_high,
            c_dynamic=model.c_dynamic,
            pressure_scale_psi=model.pressure_scale_psi,
        )
        return FlowEstimates(
            pump_flow_gpm=flow,
            pump_flow_high_gpm=flow,
        )

    return FlowEstimates()


def _pump_flow_from_pressure(
    *,
    pressure_psi: float,
    c_no_flow: float,
    c_dynamic: float,
    pressure_scale_psi: float,
) -> float:
    term = (pressure_psi / pressure_scale_psi) - c_no_flow
    if term <= 0:
        return 0.0
    return math.sqrt(term / c_dynamic)


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
