from __future__ import annotations

from poolctl.domain.models import ActuatorId, ActuatorState
from poolctl.services.flow_estimation import estimate_flows


def test_flow_estimation_placeholders_exist() -> None:
    estimates = estimate_flows(
        measurements={},
        actuator_states={
            ActuatorId.PUMP_MOTOR: ActuatorState.OFF,
            ActuatorId.PUMP_MOTOR_SPEED: ActuatorState.LOW,
        },
    )
    payload = estimates.as_payload()

    assert payload["pump_flow_gpm"]["display"] == "-- gpm"
    assert payload["pump_flow_low_gpm"]["value"] is None
    assert payload["pump_flow_high_gpm"]["value"] is None
    assert payload["booster_flow_gpm"]["value"] is None
    assert payload["return_flow_gpm"]["value"] is None
    assert payload["bubbler_flow_gpm"]["value"] is None
    assert payload["cleaner_flow_gpm"]["value"] is None
