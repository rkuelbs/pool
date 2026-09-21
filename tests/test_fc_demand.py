"""
Tests for the adaptive free-chlorine demand controller.

These tests document the Phase 1 FC mass balance, recent weighted maintenance
demand, one-day FC-test feedback, and observe/recommend/automatic mode
boundaries.
"""

from __future__ import annotations

from datetime import datetime, timezone

from poolctl.domain.models import ChemicalAddition, ChemicalType, ControlMode
from poolctl.services.chlorination import ChlorinationConfig
from poolctl.services.fc_demand import (
    ChlorineDeliveryPoint,
    FcDemandConfig,
    FcTestPoint,
    estimate_fc_demand_plan,
    fc_ppm_from_fl_oz,
    fl_oz_for_fc_ppm,
)
from poolctl.services.pump_timer import PumpTimerConfig, PumpTimerSchedule
from poolctl.services.schedule import DailyTimeWindow, TimeOfDay


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 5, day, hour, minute, tzinfo=timezone.utc)


def timer_config() -> PumpTimerConfig:
    return PumpTimerConfig(
        timezone="UTC",
        schedules=(
            PumpTimerSchedule(
                name="daily",
                window=DailyTimeWindow(
                    name="daily",
                    start=TimeOfDay.parse("00:00"),
                    end=TimeOfDay.parse("07:10"),
                ),
            ),
        ),
    )


def test_fc_dose_conversion_round_trips_for_liquid_chlorine() -> None:
    dose_oz = fl_oz_for_fc_ppm(
        1.0,
        strength_percent=12.0,
        pool_volume_gal=10000.0,
    )

    assert round(dose_oz, 3) == 10.667
    assert round(
        fc_ppm_from_fl_oz(
            dose_oz,
            strength_percent=12.0,
            pool_volume_gal=10000.0,
        ),
        3,
    ) == 1.0


def test_consecutive_nightly_tests_create_daily_observations() -> None:
    plan = estimate_fc_demand_plan(
        config=FcDemandConfig(enabled=True, mode=ControlMode.RECOMMEND),
        now=at(23, 12),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(),
        fc_tests=(
            FcTestPoint(sampled_at=at(20, 20), free_chlorine=4.0),
            FcTestPoint(sampled_at=at(21, 20), free_chlorine=3.5),
            FcTestPoint(sampled_at=at(22, 20), free_chlorine=3.0),
        ),
    )

    assert plan.status.ready is True
    assert plan.status.observation_count == 2
    assert round(plan.status.latest_observed_demand_ppm_per_day or 0.0, 3) == 0.5
    assert plan.status.previous_sampled_at == at(21, 20)
    assert plan.status.current_sampled_at == at(22, 20)
    assert [round(obs.demand_ppm_per_day, 3) for obs in plan.status.observations_used] == [
        0.5,
        0.5,
    ]


def test_five_observations_use_requested_newest_to_oldest_weights() -> None:
    config = FcDemandConfig(
        enabled=True,
        mode=ControlMode.RECOMMEND,
        max_maintenance_change_percent=1000.0,
    )

    plan = estimate_fc_demand_plan(
        config=config,
        now=at(17, 12),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(),
        fc_tests=(
            FcTestPoint(sampled_at=at(10, 12), free_chlorine=20.0),
            FcTestPoint(sampled_at=at(11, 12), free_chlorine=19.0),
            FcTestPoint(sampled_at=at(12, 12), free_chlorine=17.0),
            FcTestPoint(sampled_at=at(13, 12), free_chlorine=14.0),
            FcTestPoint(sampled_at=at(14, 12), free_chlorine=10.0),
            FcTestPoint(sampled_at=at(15, 12), free_chlorine=5.0),
        ),
    )

    assert plan.status.effective_normalized_weights == config.observation_weights
    assert [round(obs.demand_ppm_per_day, 3) for obs in plan.status.observations_used] == [
        5.0,
        4.0,
        3.0,
        2.0,
        1.0,
    ]
    assert round(plan.status.weighted_maintenance_demand_ppm_per_day or 0.0, 3) == 3.64


def test_fewer_than_five_observations_renormalize_weights() -> None:
    plan = estimate_fc_demand_plan(
        config=FcDemandConfig(
            enabled=True,
            mode=ControlMode.RECOMMEND,
            max_maintenance_change_percent=1000.0,
        ),
        now=at(14, 12),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(),
        fc_tests=(
            FcTestPoint(sampled_at=at(10, 12), free_chlorine=10.0),
            FcTestPoint(sampled_at=at(11, 12), free_chlorine=9.0),
            FcTestPoint(sampled_at=at(12, 12), free_chlorine=7.0),
        ),
    )

    assert tuple(round(weight, 4) for weight in plan.status.effective_normalized_weights) == (
        0.5833,
        0.4167,
    )
    assert round(plan.status.weighted_maintenance_demand_ppm_per_day or 0.0, 3) == 1.583


def test_missed_test_interval_creates_valid_average_daily_observation() -> None:
    plan = estimate_fc_demand_plan(
        config=FcDemandConfig(enabled=True, mode=ControlMode.RECOMMEND),
        now=at(24, 12),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(),
        fc_tests=(
            FcTestPoint(sampled_at=at(20, 20), free_chlorine=5.0),
            FcTestPoint(sampled_at=at(23, 20), free_chlorine=2.0),
        ),
    )

    assert plan.status.ready is True
    assert plan.status.observation_count == 1
    assert plan.status.elapsed_days == 3.0
    assert plan.status.daily_demand_ppm == 1.0
    assert plan.status.confidence == "learning"


def test_maintenance_dosing_continues_when_no_new_fc_test_is_entered() -> None:
    plan = estimate_fc_demand_plan(
        config=FcDemandConfig(enabled=True, mode=ControlMode.AUTOMATIC),
        now=at(23, 1),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(daily_dose_oz=5.0),
        fc_tests=(
            FcTestPoint(sampled_at=at(20, 12), free_chlorine=4.0),
            FcTestPoint(sampled_at=at(21, 12), free_chlorine=3.0),
        ),
    )

    assert plan.status.feedback_active_today is False
    assert round(plan.status.maintenance_dose_oz_per_day or 0.0, 3) == 10.667
    assert round(plan.status.recommended_daily_dose_oz or 0.0, 3) == 10.667
    assert plan.adjustment is not None
    assert round(plan.adjustment.daily_dose_oz or 0.0, 3) == 10.667


def test_stale_fc_feedback_is_not_repeated_after_control_day() -> None:
    config = FcDemandConfig(
        enabled=True,
        mode=ControlMode.AUTOMATIC,
        target_fc_ppm=4.0,
        fc_feedback_gain=0.6,
    )
    fc_tests = (
        FcTestPoint(sampled_at=at(20, 12), free_chlorine=4.0),
        FcTestPoint(sampled_at=at(21, 12), free_chlorine=3.0),
    )

    next_day = estimate_fc_demand_plan(
        config=config,
        now=at(22, 1),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(),
        fc_tests=fc_tests,
    )
    later = estimate_fc_demand_plan(
        config=config,
        now=at(23, 1),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(),
        fc_tests=fc_tests,
    )

    assert next_day.status.feedback_active_today is True
    assert round(next_day.status.applied_feedback_dose_oz, 3) == 6.4
    assert later.status.feedback_active_today is False
    assert later.status.applied_feedback_dose_oz == 0.0
    assert round(later.status.recommended_daily_dose_oz or 0.0, 3) == 10.667


def test_new_fc_below_target_creates_one_positive_next_day_correction() -> None:
    plan = estimate_fc_demand_plan(
        config=FcDemandConfig(
            enabled=True,
            mode=ControlMode.AUTOMATIC,
            target_fc_ppm=4.0,
            fc_feedback_gain=0.6,
        ),
        now=at(22, 1),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(),
        fc_tests=(
            FcTestPoint(sampled_at=at(20, 12), free_chlorine=4.0),
            FcTestPoint(sampled_at=at(21, 12), free_chlorine=3.0),
        ),
    )

    assert plan.status.feedback_active_today is True
    assert round(plan.status.feedback_fc_ppm or 0.0, 3) == 0.6
    assert round(plan.status.feedback_dose_oz, 3) == 6.4
    assert round(plan.status.recommended_daily_dose_oz or 0.0, 3) == 17.067


def test_new_fc_above_target_creates_one_negative_next_day_correction() -> None:
    plan = estimate_fc_demand_plan(
        config=FcDemandConfig(
            enabled=True,
            mode=ControlMode.AUTOMATIC,
            target_fc_ppm=4.0,
            fc_feedback_gain=0.6,
        ),
        now=at(22, 1),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(),
        fc_tests=(
            FcTestPoint(sampled_at=at(20, 12), free_chlorine=5.0),
            FcTestPoint(sampled_at=at(21, 12), free_chlorine=5.0),
        ),
        automated_chlorine_deliveries=(
            ChlorineDeliveryPoint(
                observed_at=at(21, 8),
                delivered_oz=fl_oz_for_fc_ppm(
                    1.0,
                    strength_percent=12.0,
                    pool_volume_gal=10000.0,
                ),
            ),
        ),
    )

    assert plan.status.feedback_active_today is True
    assert round(plan.status.feedback_fc_ppm or 0.0, 3) == -0.6
    assert round(plan.status.feedback_dose_oz, 3) == -6.4
    assert round(plan.status.recommended_daily_dose_oz or 0.0, 3) == 4.267


def test_feedback_gain_scales_fc_correction() -> None:
    plan = estimate_fc_demand_plan(
        config=FcDemandConfig(
            enabled=True,
            mode=ControlMode.AUTOMATIC,
            target_fc_ppm=4.0,
            fc_feedback_gain=0.25,
        ),
        now=at(22, 1),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(),
        fc_tests=(
            FcTestPoint(sampled_at=at(20, 12), free_chlorine=3.0),
            FcTestPoint(sampled_at=at(21, 12), free_chlorine=2.0),
        ),
    )

    assert plan.status.feedback_fc_ppm == 0.5
    assert round(plan.status.feedback_dose_oz, 3) == 5.333


def test_maintenance_percent_change_limiter_limits_learned_dose() -> None:
    plan = estimate_fc_demand_plan(
        config=FcDemandConfig(
            enabled=True,
            mode=ControlMode.RECOMMEND,
            max_maintenance_change_percent=15.0,
        ),
        now=at(14, 12),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(),
        fc_tests=(
            FcTestPoint(sampled_at=at(10, 12), free_chlorine=10.0),
            FcTestPoint(sampled_at=at(11, 12), free_chlorine=9.0),
            FcTestPoint(sampled_at=at(12, 12), free_chlorine=7.0),
        ),
    )

    assert round(plan.status.unlimited_maintenance_dose_oz_per_day or 0.0, 3) == 16.889
    assert round(plan.status.previous_maintenance_dose_oz_per_day or 0.0, 3) == 10.667
    assert round(plan.status.maintenance_dose_oz_per_day or 0.0, 3) == 12.267
    assert plan.status.maintenance_rate_limited is True


def test_final_max_daily_dose_cap_is_hard_cap() -> None:
    plan = estimate_fc_demand_plan(
        config=FcDemandConfig(
            enabled=True,
            mode=ControlMode.AUTOMATIC,
            target_fc_ppm=6.0,
            fc_feedback_gain=1.0,
            max_daily_dose_oz=12.0,
        ),
        now=at(22, 1),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(),
        fc_tests=(
            FcTestPoint(sampled_at=at(20, 12), free_chlorine=4.0),
            FcTestPoint(sampled_at=at(21, 12), free_chlorine=3.0),
        ),
    )

    assert plan.status.final_dose_capped is True
    assert plan.status.recommended_daily_dose_oz == 12.0
    assert plan.adjustment is not None
    assert plan.adjustment.daily_dose_oz == 12.0


def test_final_dose_cannot_go_below_zero() -> None:
    plan = estimate_fc_demand_plan(
        config=FcDemandConfig(
            enabled=True,
            mode=ControlMode.AUTOMATIC,
            target_fc_ppm=0.0,
            fc_feedback_gain=1.0,
        ),
        now=at(22, 1),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(),
        fc_tests=(
            FcTestPoint(sampled_at=at(20, 12), free_chlorine=5.0),
            FcTestPoint(sampled_at=at(21, 12), free_chlorine=4.0),
        ),
    )

    assert plan.status.final_dose_floor_limited is True
    assert plan.status.recommended_daily_dose_oz == 0.0
    assert plan.adjustment is not None
    assert plan.adjustment.daily_dose_oz == 0.0


def test_manual_sodium_hypochlorite_additions_count_toward_fc_added() -> None:
    addition = ChemicalAddition(
        added_at=at(21, 8),
        chemical=ChemicalType.SODIUM_HYPOCHLORITE,
        amount=10.0,
        unit="fl_oz",
        amount_fl_oz=10.0,
        strength_percent=12.0,
    )

    plan = estimate_fc_demand_plan(
        config=FcDemandConfig(enabled=True, mode=ControlMode.RECOMMEND),
        now=at(23, 1),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(),
        fc_tests=(
            FcTestPoint(sampled_at=at(20, 12), free_chlorine=4.0),
            FcTestPoint(sampled_at=at(21, 12), free_chlorine=4.0),
        ),
        sodium_hypochlorite_additions=(addition,),
    )

    assert round(plan.status.manual_hypo_oz, 3) == 10.0
    assert round(plan.status.added_fc_ppm or 0.0, 3) == 0.938
    assert round(plan.status.daily_demand_ppm or 0.0, 3) == 0.938
    assert plan.adjustment is None


def test_observe_only_and_recommend_do_not_alter_chlorination() -> None:
    fc_tests = (
        FcTestPoint(sampled_at=at(20, 12), free_chlorine=4.0),
        FcTestPoint(sampled_at=at(21, 12), free_chlorine=3.0),
    )

    observe = estimate_fc_demand_plan(
        config=FcDemandConfig(enabled=True, mode=ControlMode.OBSERVE_ONLY),
        now=at(22, 1),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(daily_dose_oz=8.0),
        fc_tests=fc_tests,
    )
    recommend = estimate_fc_demand_plan(
        config=FcDemandConfig(enabled=True, mode=ControlMode.RECOMMEND),
        now=at(22, 1),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(daily_dose_oz=8.0),
        fc_tests=fc_tests,
    )
    approve_required = estimate_fc_demand_plan(
        config=FcDemandConfig(enabled=True, mode=ControlMode.APPROVE_REQUIRED),
        now=at(22, 1),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(daily_dose_oz=8.0),
        fc_tests=fc_tests,
    )

    assert observe.adjustment is None
    assert observe.status.effective_daily_dose_oz == 8.0
    assert recommend.adjustment is None
    assert recommend.status.effective_daily_dose_oz == 8.0
    assert approve_required.adjustment is None
    assert approve_required.status.effective_daily_dose_oz == 8.0


def test_automatic_produces_chlorination_plan_adjustment() -> None:
    plan = estimate_fc_demand_plan(
        config=FcDemandConfig(enabled=True, mode=ControlMode.AUTOMATIC),
        now=at(23, 1),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(daily_dose_oz=8.0),
        fc_tests=(
            FcTestPoint(sampled_at=at(20, 12), free_chlorine=4.0),
            FcTestPoint(sampled_at=at(21, 12), free_chlorine=3.0),
        ),
    )

    assert plan.adjustment is not None
    assert round(plan.adjustment.daily_dose_oz or 0.0, 3) == 10.667
    assert plan.adjustment.delay_eligible_seconds == 0.0
    assert plan.adjustment.source == "fc_demand"
