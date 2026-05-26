from __future__ import annotations

import math

from poolctl.domain.models import ActuatorId, ActuatorState, Measurement, SensorId
from poolctl.services.flow_estimation import FlowEstimationConfig, estimate_flows


def _pressure(value: float) -> Measurement:
    return Measurement(
        sensor_id=SensorId.PUMP_OUTPUT_PSI,
        value=value,
        unit="psi",
    )


def test_flow_estimation_returns_zero_when_pump_is_off() -> None:
    estimates = estimate_flows(
        measurements={SensorId.PUMP_OUTPUT_PSI: _pressure(12.0)},
        actuator_states={
            ActuatorId.PUMP_MOTOR: ActuatorState.OFF,
            ActuatorId.PUMP_MOTOR_SPEED: ActuatorState.HIGH,
        },
    )
    payload = estimates.as_payload()

    assert payload["pump_flow_gpm"]["value"] == 0.0
    assert payload["pump_flow_gpm"]["display"] == "0.0 gpm"
    assert payload["pump_flow_low_gpm"]["value"] is None
    assert payload["pump_flow_high_gpm"]["value"] is None


def test_flow_estimation_uses_high_speed_pressure_model() -> None:
    pressure = 50.0
    estimates = estimate_flows(
        measurements={SensorId.PUMP_OUTPUT_PSI: _pressure(pressure)},
        actuator_states={
            ActuatorId.PUMP_MOTOR: ActuatorState.ON,
            ActuatorId.PUMP_MOTOR_SPEED: ActuatorState.HIGH,
        },
    )

    expected = math.sqrt(((pressure / 0.4335) - 93.5) / 0.00525)
    assert estimates.pump_flow_gpm is not None
    assert abs(estimates.pump_flow_gpm - expected) < 1e-9
    assert estimates.pump_flow_high_gpm == estimates.pump_flow_gpm
    assert estimates.pump_flow_low_gpm is None


def test_flow_estimation_uses_low_speed_pressure_model() -> None:
    pressure = 12.0
    estimates = estimate_flows(
        measurements={SensorId.PUMP_OUTPUT_PSI: _pressure(pressure)},
        actuator_states={
            ActuatorId.PUMP_MOTOR: ActuatorState.ON,
            ActuatorId.PUMP_MOTOR_SPEED: ActuatorState.LOW,
        },
    )

    expected = math.sqrt(((pressure / 0.4335) - 22.25) / 0.00525)
    assert estimates.pump_flow_gpm is not None
    assert abs(estimates.pump_flow_gpm - expected) < 1e-9
    assert estimates.pump_flow_low_gpm == estimates.pump_flow_gpm
    assert estimates.pump_flow_high_gpm is None


def test_flow_estimation_clamps_negative_term_to_zero() -> None:
    estimates = estimate_flows(
        measurements={SensorId.PUMP_OUTPUT_PSI: _pressure(1.0)},
        actuator_states={
            ActuatorId.PUMP_MOTOR: ActuatorState.ON,
            ActuatorId.PUMP_MOTOR_SPEED: ActuatorState.HIGH,
        },
    )

    assert estimates.pump_flow_gpm == 0.0


def test_flow_estimation_constants_are_configurable() -> None:
    config = FlowEstimationConfig.from_mapping(
        {
            "flow_estimation": {
                "pump_pressure": {
                    "pressure_scale_psi": 0.05,
                    "c_dynamic": 0.01,
                    "c_no_flow_low": 10.0,
                    "c_no_flow_high": 20.0,
                }
            }
        }
    )
    estimates = estimate_flows(
        measurements={SensorId.PUMP_OUTPUT_PSI: _pressure(10.0)},
        actuator_states={
            ActuatorId.PUMP_MOTOR: ActuatorState.ON,
            ActuatorId.PUMP_MOTOR_SPEED: ActuatorState.HIGH,
        },
        config=config,
    )

    expected = math.sqrt(((10.0 / 0.05) - 20.0) / 0.01)
    assert estimates.pump_flow_gpm is not None
    assert abs(estimates.pump_flow_gpm - expected) < 1e-9
