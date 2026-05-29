from __future__ import annotations

import math

import pytest

from poolctl.domain.models import ActuatorId, ActuatorState, Measurement, SensorId
from poolctl.services.flow_estimation import FlowEstimationConfig, estimate_flows


def _pressure(value: float) -> Measurement:
    return Measurement(
        sensor_id=SensorId.PUMP_OUTPUT_PSI,
        value=value,
        unit="psi",
    )


def _sensor_pressure(sensor_id: SensorId, value: float) -> Measurement:
    return Measurement(
        sensor_id=sensor_id,
        value=value,
        unit="psi",
    )


def test_flow_estimation_returns_zero_when_pump_is_off() -> None:
    estimates = estimate_flows(
        measurements={
            SensorId.PUMP_OUTPUT_PSI: _pressure(12.0),
            SensorId.FILTER_OUTPUT_PSI: Measurement(
                sensor_id=SensorId.FILTER_OUTPUT_PSI,
                value=10.0,
                unit="psi",
            ),
        },
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
    assert payload["return_flow_gpm"]["value"] == 0.0
    assert payload["bubbler_flow_gpm"]["value"] == 0.0
    assert payload["booster_flow_gpm"]["value"] == 0.0
    assert payload["filter_restriction_metric"]["value"] is None
    assert payload["filter_restriction_percent"]["value"] is None


def test_flow_estimation_uses_high_speed_pressure_model() -> None:
    pressure = 10.0
    estimates = estimate_flows(
        measurements={SensorId.PUMP_OUTPUT_PSI: _pressure(pressure)},
        actuator_states={
            ActuatorId.PUMP_MOTOR: ActuatorState.ON,
            ActuatorId.PUMP_MOTOR_SPEED: ActuatorState.HIGH,
        },
    )

    expected = math.sqrt((93.5 - (pressure / 0.4335)) / 0.00525)
    assert estimates.pump_flow_gpm is not None
    assert abs(estimates.pump_flow_gpm - expected) < 1e-9
    assert estimates.pump_flow_high_gpm == estimates.pump_flow_gpm
    assert estimates.pump_flow_low_gpm is None


def test_flow_estimation_uses_low_speed_pressure_model() -> None:
    pressure = 5.0
    estimates = estimate_flows(
        measurements={SensorId.PUMP_OUTPUT_PSI: _pressure(pressure)},
        actuator_states={
            ActuatorId.PUMP_MOTOR: ActuatorState.ON,
            ActuatorId.PUMP_MOTOR_SPEED: ActuatorState.LOW,
        },
    )

    expected = math.sqrt((22.25 - (pressure / 0.4335)) / 0.00525)
    assert estimates.pump_flow_gpm is not None
    assert abs(estimates.pump_flow_gpm - expected) < 1e-9
    assert estimates.pump_flow_low_gpm == estimates.pump_flow_gpm
    assert estimates.pump_flow_high_gpm is None


def test_flow_estimation_clamps_negative_term_to_zero() -> None:
    estimates = estimate_flows(
        measurements={SensorId.PUMP_OUTPUT_PSI: _pressure(60.0)},
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
        measurements={SensorId.PUMP_OUTPUT_PSI: _pressure(0.5)},
        actuator_states={
            ActuatorId.PUMP_MOTOR: ActuatorState.ON,
            ActuatorId.PUMP_MOTOR_SPEED: ActuatorState.HIGH,
        },
        config=config,
    )

    expected = math.sqrt((20.0 - (0.5 / 0.05)) / 0.01)
    assert estimates.pump_flow_gpm is not None
    assert abs(estimates.pump_flow_gpm - expected) < 1e-9


def test_flow_estimation_branch_flows_use_configured_quadratic_models() -> None:
    config = FlowEstimationConfig.from_mapping(
        {
            "flow_estimation": {
                "branch_pressure": {
                    "return_flow": {"a": 1.0, "b": 0.5},
                    "bubbler_flow": {"a": 0.5, "b": 0.25},
                    "booster_flow": {"a": 2.0, "b": 1.0},
                }
            }
        }
    )
    estimates = estimate_flows(
        measurements={
            SensorId.PUMP_OUTPUT_PSI: _pressure(10.0),
            SensorId.RETURN_PSI: _sensor_pressure(SensorId.RETURN_PSI, 11.0),
            SensorId.BUBBLER_PSI: _sensor_pressure(SensorId.BUBBLER_PSI, 5.5),
            SensorId.BOOSTER_PSI: _sensor_pressure(SensorId.BOOSTER_PSI, 12.0),
        },
        actuator_states={
            ActuatorId.PUMP_MOTOR: ActuatorState.ON,
            ActuatorId.PUMP_MOTOR_SPEED: ActuatorState.HIGH,
        },
        config=config,
    )

    assert estimates.return_flow_gpm is not None
    assert estimates.bubbler_flow_gpm is not None
    assert estimates.booster_flow_gpm is not None
    assert abs(estimates.return_flow_gpm - math.sqrt(20.0)) < 1e-9
    assert abs(estimates.bubbler_flow_gpm - math.sqrt(20.0)) < 1e-9
    assert abs(estimates.booster_flow_gpm - math.sqrt(10.0)) < 1e-9


def test_filter_restriction_metric_and_percent_are_computed_when_flow_positive() -> None:
    pressure = 10.0
    estimates = estimate_flows(
        measurements={
            SensorId.PUMP_OUTPUT_PSI: _pressure(pressure),
            SensorId.FILTER_OUTPUT_PSI: Measurement(
                sensor_id=SensorId.FILTER_OUTPUT_PSI,
                value=8.0,
                unit="psi",
            ),
        },
        actuator_states={
            ActuatorId.PUMP_MOTOR: ActuatorState.ON,
            ActuatorId.PUMP_MOTOR_SPEED: ActuatorState.HIGH,
        },
        config=FlowEstimationConfig.from_mapping(
            {
                "flow_estimation": {
                    "filter_restriction": {
                        "clean_value": 1.0,
                        "dirty_value": 3.0,
                    }
                }
            }
        ),
    )

    assert estimates.pump_flow_gpm is not None
    expected_metric = 10000.0 * (10.0 - 8.0) / (estimates.pump_flow_gpm ** 2)
    assert estimates.filter_restriction_metric is not None
    assert abs(estimates.filter_restriction_metric - expected_metric) < 1e-9
    assert estimates.filter_restriction_percent is not None
    assert 0.0 <= estimates.filter_restriction_percent <= 100.0


def test_filter_restriction_percent_scales_from_clean_to_dirty() -> None:
    estimates = estimate_flows(
        measurements={
            SensorId.PUMP_OUTPUT_PSI: _pressure(10.0),
            SensorId.FILTER_OUTPUT_PSI: Measurement(
                sensor_id=SensorId.FILTER_OUTPUT_PSI,
                value=7.32,
                unit="psi",
            ),
        },
        actuator_states={
            ActuatorId.PUMP_MOTOR: ActuatorState.ON,
            ActuatorId.PUMP_MOTOR_SPEED: ActuatorState.HIGH,
        },
        config=FlowEstimationConfig.from_mapping(
            {
                "flow_estimation": {
                    "filter_restriction": {
                        "clean_value": 1.0,
                        "dirty_value": 3.0,
                    }
                }
            }
        ),
    )

    assert estimates.filter_restriction_metric is not None
    assert abs(estimates.filter_restriction_metric - 2.0) < 0.1
    assert estimates.filter_restriction_percent is not None
    assert abs(estimates.filter_restriction_percent - 50.0) < 3.0


def test_filter_restriction_config_requires_dirty_greater_than_clean() -> None:
    with pytest.raises(ValueError):
        FlowEstimationConfig.from_mapping(
            {
                "flow_estimation": {
                    "filter_restriction": {
                        "clean_value": 2.0,
                        "dirty_value": 2.0,
                    }
                }
            }
        )


def test_flow_estimation_quadratic_model_rejects_nonpositive_b() -> None:
    with pytest.raises(ValueError):
        FlowEstimationConfig.from_mapping(
            {
                "flow_estimation": {
                    "branch_pressure": {
                        "return_flow": {"a": 0.0, "b": 0.0},
                    }
                }
            }
        )
    with pytest.raises(ValueError):
        FlowEstimationConfig.from_mapping(
            {
                "flow_estimation": {
                    "branch_pressure": {
                        "return_flow": {"a": 0.0, "b": -1.0},
                    }
                }
            }
        )
