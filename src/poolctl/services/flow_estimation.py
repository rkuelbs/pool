from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from poolctl.domain.models import ActuatorId, ActuatorState, Measurement, SensorId


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
) -> FlowEstimates:
    """
    Flow estimation placeholder.

    Planned equations:
    - pump low/high flow from pump output pressure
    - return/bubbler/cleaner flow from return, bubbler, booster pressures
    """
    _ = measurements
    _ = actuator_states
    return FlowEstimates()


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
