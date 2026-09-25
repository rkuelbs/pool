"""
Tests for derived hydraulic estimates.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from poolctl.config import MonitoringConfig
from poolctl.domain.models import (
    ActuatorId,
    ActuatorState,
    Measurement,
    Quality,
    SensorId,
)
from poolctl.services.flow_estimation import (
    FilterLoadingConfig,
    FilterLoadingEstimator,
    FlowEstimationConfig,
    PumpPressureFlowModelConfig,
    estimate_pump_flow_from_pressure,
    estimate_flows,
)


def _pressure(value: float, *, observed_at: datetime | None = None) -> Measurement:
    return Measurement(
        sensor_id=SensorId.PUMP_OUTPUT_PSI,
        observed_at=observed_at or datetime(2026, 5, 21, tzinfo=timezone.utc),
        value=value,
        unit="psi",
        quality=Quality.GOOD,
    )


def _states(
    *,
    pump: ActuatorState = ActuatorState.ON,
    speed: ActuatorState = ActuatorState.HIGH,
    booster: ActuatorState = ActuatorState.OFF,
) -> dict[ActuatorId, ActuatorState]:
    return {
        ActuatorId.PUMP_MOTOR: pump,
        ActuatorId.PUMP_MOTOR_SPEED: speed,
        ActuatorId.BOOSTER_PUMP: booster,
    }


FLOW_NOW = datetime(2026, 5, 21, tzinfo=timezone.utc)


def _estimate_flows(**kwargs: object):
    return estimate_flows(
        now=FLOW_NOW,
        max_pressure_age_seconds=10.0,
        **kwargs,  # type: ignore[arg-type]
    )


def test_flow_estimation_returns_zero_when_pump_is_off() -> None:
    estimates = _estimate_flows(
        measurements={SensorId.PUMP_OUTPUT_PSI: _pressure(12.0)},
        actuator_states=_states(pump=ActuatorState.OFF),
    )
    payload = estimates.as_payload()

    assert payload["pump_flow_gpm"]["value"] == 0.0
    assert payload["pump_dynamic_head_psi"]["value"] == 0.0
    assert payload["filter_reference_psi"]["value"] is None
    assert payload["filter_reference_flow_gpm"]["value"] is None
    assert payload["filter_flow_loss_percent"]["value"] is None


def test_flow_estimation_uses_high_speed_pressure_model() -> None:
    pressure = 10.0
    estimates = _estimate_flows(
        measurements={SensorId.PUMP_OUTPUT_PSI: _pressure(pressure)},
        actuator_states=_states(speed=ActuatorState.HIGH),
    )

    expected = math.sqrt((93.5 - (pressure / 0.4335)) / 0.00525)
    expected_head = pressure + (0.4335 * 0.00035 * (expected**2))
    assert estimates.pump_flow_gpm is not None
    assert abs(estimates.pump_flow_gpm - expected) < 1e-9
    assert estimates.pump_dynamic_head_psi is not None
    assert abs(estimates.pump_dynamic_head_psi - expected_head) < 1e-9
    assert estimates.pump_flow_high_gpm == estimates.pump_flow_gpm
    assert estimates.pump_flow_low_gpm is None


def test_flow_estimation_uses_low_speed_pressure_model() -> None:
    pressure = 5.0
    estimates = _estimate_flows(
        measurements={SensorId.PUMP_OUTPUT_PSI: _pressure(pressure)},
        actuator_states=_states(speed=ActuatorState.LOW),
    )

    expected = math.sqrt((22.25 - (pressure / 0.4335)) / 0.00525)
    expected_head = pressure + (0.4335 * 0.00035 * (expected**2))
    assert estimates.pump_flow_gpm is not None
    assert abs(estimates.pump_flow_gpm - expected) < 1e-9
    assert estimates.pump_dynamic_head_psi is not None
    assert abs(estimates.pump_dynamic_head_psi - expected_head) < 1e-9
    assert estimates.pump_flow_low_gpm == estimates.pump_flow_gpm
    assert estimates.pump_flow_high_gpm is None


def test_flow_estimation_clamps_negative_term_to_zero() -> None:
    estimates = _estimate_flows(
        measurements={SensorId.PUMP_OUTPUT_PSI: _pressure(60.0)},
        actuator_states=_states(speed=ActuatorState.HIGH),
    )

    assert estimates.pump_flow_gpm == 0.0


def test_flow_estimation_constants_are_configurable() -> None:
    config = FlowEstimationConfig.from_mapping(
        {
            "flow_estimation": {
                "pump_pressure": {
                    "pressure_scale_psi": 0.05,
                    "c_dynamic": 0.01,
                    "c_suction": 0.02,
                    "c_no_flow_low": 10.0,
                    "c_no_flow_high": 20.0,
                }
            }
        }
    )
    estimates = _estimate_flows(
        measurements={SensorId.PUMP_OUTPUT_PSI: _pressure(0.5)},
        actuator_states=_states(speed=ActuatorState.HIGH),
        config=config,
    )

    expected = math.sqrt((20.0 - (0.5 / 0.05)) / 0.01)
    assert estimates.pump_flow_gpm is not None
    assert abs(estimates.pump_flow_gpm - expected) < 1e-9
    assert estimates.pump_dynamic_head_psi is not None
    assert abs(estimates.pump_dynamic_head_psi - (0.5 + (0.05 * 0.02 * (expected**2)))) < 1e-9


def test_flow_estimation_rejects_negative_c_suction() -> None:
    with pytest.raises(ValueError):
        FlowEstimationConfig.from_mapping(
            {
                "flow_estimation": {
                    "pump_pressure": {
                        "c_suction": -0.001,
                    }
                }
            }
        )


def test_flow_estimation_requires_fresh_good_pressure() -> None:
    fresh = _estimate_flows(
        measurements={SensorId.PUMP_OUTPUT_PSI: _pressure(10.0, observed_at=FLOW_NOW)},
        actuator_states=_states(),
    )
    stale = _estimate_flows(
        measurements={
            SensorId.PUMP_OUTPUT_PSI: _pressure(
                10.0,
                observed_at=FLOW_NOW - timedelta(seconds=11),
            )
        },
        actuator_states=_states(),
    )
    bad_pressure = _pressure(10.0, observed_at=FLOW_NOW).model_copy(
        update={"quality": Quality.BAD}
    )
    bad = _estimate_flows(
        measurements={SensorId.PUMP_OUTPUT_PSI: bad_pressure},
        actuator_states=_states(),
    )

    assert fresh.pump_flow_gpm is not None
    assert stale.pump_flow_gpm is None
    assert stale.pump_dynamic_head_psi is None
    assert bad.pump_flow_gpm is None
    assert bad.pump_dynamic_head_psi is None


def test_filter_loading_ignores_low_speed_and_booster_on() -> None:
    now = datetime(2026, 5, 21, 7, 0, tzinfo=timezone.utc)
    estimator = FilterLoadingEstimator(
        FilterLoadingConfig(stabilization_seconds=0, averaging_seconds=10)
    )

    low = estimator.update(
        now=now,
        measurements={SensorId.PUMP_OUTPUT_PSI: _pressure(18.0, observed_at=now)},
        actuator_states=_states(speed=ActuatorState.LOW),
    )
    booster = estimator.update(
        now=now,
        measurements={SensorId.PUMP_OUTPUT_PSI: _pressure(18.0, observed_at=now)},
        actuator_states=_states(booster=ActuatorState.ON),
    )

    assert low.result is None
    assert low.reason == "pump is not high speed"
    assert booster.result is None
    assert booster.reason == "booster pump is on"


def test_filter_loading_stabilizes_averages_and_latches_result() -> None:
    start = datetime(2026, 5, 21, 7, 0, tzinfo=timezone.utc)
    estimator = FilterLoadingEstimator(
        FilterLoadingConfig(
            clean_flow_gpm=100.0,
            stabilization_seconds=60,
            averaging_seconds=120,
        )
    )

    first = estimator.update(
        now=start,
        measurements={SensorId.PUMP_OUTPUT_PSI: _pressure(15.0, observed_at=start)},
        actuator_states=_states(),
    )
    after_stabilization = estimator.update(
        now=start + timedelta(seconds=60),
        measurements={
            SensorId.PUMP_OUTPUT_PSI: _pressure(
                16.0,
                observed_at=start + timedelta(seconds=60),
            )
        },
        actuator_states=_states(),
    )
    complete = estimator.update(
        now=start + timedelta(seconds=180),
        measurements={
            SensorId.PUMP_OUTPUT_PSI: _pressure(
                18.0,
                observed_at=start + timedelta(seconds=180),
            )
        },
        actuator_states=_states(),
    )
    latched = estimator.update(
        now=start + timedelta(seconds=181),
        measurements={
            SensorId.PUMP_OUTPUT_PSI: _pressure(
                18.0,
                observed_at=start + timedelta(seconds=181),
            )
        },
        actuator_states=_states(speed=ActuatorState.LOW),
    )

    assert first.reason == "stabilizing"
    assert after_stabilization.reason == "averaging"
    assert complete.completed_this_tick is True
    assert complete.result is not None
    assert complete.result.reference_psi == 17.0
    assert complete.result.estimated_flow_gpm == round(
        estimate_pump_flow_from_pressure(
            pressure_psi=17.0,
            speed=ActuatorState.HIGH,
            model=PumpPressureFlowModelConfig(),
        ),
        4,
    )
    assert complete.result.raw_flow_loss_percent is not None
    assert complete.result.flow_loss_percent == max(
        0.0,
        round(complete.result.raw_flow_loss_percent, 4),
    )
    assert latched.result == complete.result
    assert latched.reason == "pump is not high speed"


def test_filter_loading_counts_distinct_source_measurements_not_controller_ticks() -> None:
    start = datetime(2026, 5, 21, 7, 0, tzinfo=timezone.utc)
    estimator = FilterLoadingEstimator(
        FilterLoadingConfig(
            stabilization_seconds=0,
            averaging_seconds=2,
            max_pressure_age_seconds=10,
        )
    )
    same_measurement = _pressure(15.0, observed_at=start)

    first = estimator.update(
        now=start,
        measurements={SensorId.PUMP_OUTPUT_PSI: same_measurement},
        actuator_states=_states(),
    )
    repeated = estimator.update(
        now=start + timedelta(seconds=2),
        measurements={SensorId.PUMP_OUTPUT_PSI: same_measurement},
        actuator_states=_states(),
    )
    second = estimator.update(
        now=start + timedelta(seconds=2),
        measurements={
            SensorId.PUMP_OUTPUT_PSI: _pressure(
                16.0,
                observed_at=start + timedelta(seconds=1),
            )
        },
        actuator_states=_states(),
    )
    complete = estimator.update(
        now=start + timedelta(seconds=2),
        measurements={
            SensorId.PUMP_OUTPUT_PSI: _pressure(
                17.0,
                observed_at=start + timedelta(seconds=2),
            )
        },
        actuator_states=_states(),
    )

    assert first.result is None
    assert repeated.result is None
    assert repeated.reason == "averaging"
    assert second.result is None
    assert complete.completed_this_tick is True
    assert complete.result is not None
    assert complete.result.sample_count == 3
    assert complete.result.averaging_seconds == 2.0
    assert complete.result.completed_at == start + timedelta(seconds=2)


def test_filter_loading_uncalibrated_completes_without_flow_loss() -> None:
    now = datetime(2026, 5, 21, 7, 0, tzinfo=timezone.utc)
    estimator = FilterLoadingEstimator(
        FilterLoadingConfig(
            stabilization_seconds=0,
            averaging_seconds=1,
        )
    )

    estimator.update(
        now=now,
        measurements={SensorId.PUMP_OUTPUT_PSI: _pressure(25.0, observed_at=now)},
        actuator_states=_states(),
    )
    update = estimator.update(
        now=now + timedelta(seconds=1),
        measurements={
            SensorId.PUMP_OUTPUT_PSI: _pressure(
                25.0,
                observed_at=now + timedelta(seconds=1),
            )
        },
        actuator_states=_states(),
    )

    assert update.result is not None
    assert update.result.reference_psi == 25.0
    assert update.result.estimated_flow_gpm is not None
    assert update.result.clean_flow_gpm is None
    assert update.result.raw_flow_loss_percent is None
    assert update.result.flow_loss_percent is None
    assert update.result.as_payload(
        monitoring_config=MonitoringConfig.from_mapping({})
    )["status"] == "unknown"


def test_filter_loading_retains_negative_raw_loss_and_clamps_display() -> None:
    now = datetime(2026, 5, 21, 7, 0, tzinfo=timezone.utc)
    estimator = FilterLoadingEstimator(
        FilterLoadingConfig(
            clean_flow_gpm=50.0,
            stabilization_seconds=0,
            averaging_seconds=1,
        )
    )

    estimator.update(
        now=now,
        measurements={SensorId.PUMP_OUTPUT_PSI: _pressure(10.0, observed_at=now)},
        actuator_states=_states(),
    )
    update = estimator.update(
        now=now + timedelta(seconds=1),
        measurements={
            SensorId.PUMP_OUTPUT_PSI: _pressure(
                10.0,
                observed_at=now + timedelta(seconds=1),
            )
        },
        actuator_states=_states(),
    )

    assert update.result is not None
    assert update.result.raw_flow_loss_percent is not None
    assert update.result.raw_flow_loss_percent < 0.0
    assert update.result.flow_loss_percent == 0.0
    assert update.result.as_payload(
        monitoring_config=MonitoringConfig.from_mapping({})
    )["status"] == "normal"


def test_filter_loading_uses_monitoring_status_and_config_recompute() -> None:
    now = datetime(2026, 5, 21, 7, 0, tzinfo=timezone.utc)
    model = PumpPressureFlowModelConfig()
    reference_flow = estimate_pump_flow_from_pressure(
        pressure_psi=17.0,
        speed=ActuatorState.HIGH,
        model=model,
    )
    assert reference_flow is not None
    estimator = FilterLoadingEstimator(
        FilterLoadingConfig(
            clean_flow_gpm=reference_flow / 0.88,
            stabilization_seconds=0,
            averaging_seconds=1,
        )
    )

    estimator.update(
        now=now,
        measurements={SensorId.PUMP_OUTPUT_PSI: _pressure(17.0, observed_at=now)},
        actuator_states=_states(),
    )
    update = estimator.update(
        now=now + timedelta(seconds=1),
        measurements={
            SensorId.PUMP_OUTPUT_PSI: _pressure(
                17.0,
                observed_at=now + timedelta(seconds=1),
            )
        },
        actuator_states=_states(),
    )

    assert update.result is not None
    monitoring = MonitoringConfig.from_mapping({})
    assert update.result.as_payload(monitoring_config=monitoring)["status"] == "caution"

    estimator.apply_config(
        FilterLoadingConfig(
            clean_flow_gpm=reference_flow / 0.80,
            stabilization_seconds=30,
            averaging_seconds=300,
        )
    )

    recomputed = estimator.last_result
    assert recomputed is not None
    assert recomputed.reference_psi == update.result.reference_psi
    assert recomputed.as_payload(monitoring_config=monitoring)["status"] == "alarm"


def test_filter_loading_restores_persisted_reference_with_current_calibration() -> None:
    completed_at = datetime(2026, 5, 20, 7, 0, tzinfo=timezone.utc)
    estimator = FilterLoadingEstimator(
        FilterLoadingConfig(clean_flow_gpm=100.0),
    )

    restored = estimator.restore_last_result(
        reference_psi=17.0,
        completed_at=completed_at,
        sample_count=7,
        averaging_seconds=120.0,
    )

    assert restored is True
    result = estimator.last_result
    assert result is not None
    assert result.reference_psi == 17.0
    assert result.completed_at == completed_at
    assert result.sample_count == 7
    assert result.averaging_seconds == 120.0
    original_raw_loss = result.raw_flow_loss_percent

    estimator.apply_config(FilterLoadingConfig(clean_flow_gpm=80.0))

    assert estimator.last_result is not None
    assert estimator.last_result.reference_psi == 17.0
    assert estimator.last_result.clean_flow_gpm == 80.0
    assert estimator.last_result.raw_flow_loss_percent != original_raw_loss


@pytest.mark.parametrize(
    ("reference_psi", "sample_count", "averaging_seconds"),
    [
        (float("nan"), 1, 0.0),
        (-1.0, 1, 0.0),
        (17.0, 0, 0.0),
        (17.0, 1, float("inf")),
    ],
)
def test_filter_loading_rejects_invalid_persisted_reference(
    reference_psi: float,
    sample_count: int,
    averaging_seconds: float,
) -> None:
    estimator = FilterLoadingEstimator(FilterLoadingConfig(clean_flow_gpm=100.0))

    restored = estimator.restore_last_result(
        reference_psi=reference_psi,
        completed_at=datetime(2026, 5, 20, 7, 0, tzinfo=timezone.utc),
        sample_count=sample_count,
        averaging_seconds=averaging_seconds,
    )

    assert restored is False
    assert estimator.last_result is None


def test_filter_loading_config_validates_flow_loss_calibration() -> None:
    with pytest.raises(ValueError):
        FilterLoadingConfig(clean_flow_gpm=0.0)
