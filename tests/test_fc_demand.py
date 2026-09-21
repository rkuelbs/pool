"""
Tests for the adaptive free-chlorine demand controller.

These tests document the Phase 1 FC mass balance, recent weighted maintenance
demand, one-day FC-test feedback, and observe/recommend/automatic mode
boundaries.
"""

from __future__ import annotations

from datetime import datetime, timezone

from poolctl.domain.models import ChemicalAddition, ChemicalType, ControlMode, LabTest
from poolctl.services.chlorination import ChlorinationConfig
from poolctl.services.fc_demand import (
    ChlorineDeliveryPoint,
    FcDemandConfig,
    FcObservationTiming,
    FcTestPoint,
    estimate_fc_demand_plan,
    fc_observations_from_lab_tests,
    fc_ppm_from_fl_oz,
    fl_oz_for_fc_ppm,
    manual_dpd_fc_observations,
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
            FcTestPoint(sampled_at=at(10, 20), free_chlorine=20.0),
            FcTestPoint(sampled_at=at(11, 20), free_chlorine=19.0),
            FcTestPoint(sampled_at=at(12, 20), free_chlorine=17.0),
            FcTestPoint(sampled_at=at(13, 20), free_chlorine=14.0),
            FcTestPoint(sampled_at=at(14, 20), free_chlorine=10.0),
            FcTestPoint(sampled_at=at(15, 20), free_chlorine=5.0),
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
            FcTestPoint(sampled_at=at(10, 20), free_chlorine=10.0),
            FcTestPoint(sampled_at=at(11, 20), free_chlorine=9.0),
            FcTestPoint(sampled_at=at(12, 20), free_chlorine=7.0),
        ),
    )

    assert tuple(round(weight, 4) for weight in plan.status.effective_normalized_weights) == (
        0.5833,
        0.4167,
    )
    assert round(plan.status.weighted_maintenance_demand_ppm_per_day or 0.0, 3) == 1.583


def test_baseline_weather_and_predicted_demand_fields_are_phase_1_terms() -> None:
    plan = estimate_fc_demand_plan(
        config=FcDemandConfig(
            enabled=True,
            mode=ControlMode.RECOMMEND,
            max_maintenance_change_percent=1000.0,
        ),
        now=at(23, 12),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(),
        fc_tests=(
            FcTestPoint(sampled_at=at(20, 20), free_chlorine=5.0),
            FcTestPoint(sampled_at=at(21, 20), free_chlorine=4.0),
            FcTestPoint(sampled_at=at(22, 20), free_chlorine=2.0),
        ),
    )

    assert plan.status.ready is True
    assert round(plan.status.baseline_demand_ppm_per_day or 0.0, 3) == 1.583
    assert plan.status.baseline_demand_ppm_per_day == (
        plan.status.weighted_maintenance_demand_ppm_per_day
    )
    assert plan.status.weather_adjustment_ppm_per_day == 0.0
    assert plan.status.predicted_demand_ppm_per_day == (
        plan.status.baseline_demand_ppm_per_day
    )
    assert plan.status.rate_limited_baseline_demand_ppm_per_day == (
        plan.status.baseline_demand_ppm_per_day
    )

    payload = plan.status.as_payload()
    assert payload["baseline_demand_ppm_per_day"] == (
        plan.status.baseline_demand_ppm_per_day
    )
    assert payload["weather_adjustment_ppm_per_day"] == 0.0
    assert payload["predicted_demand_ppm_per_day"] == (
        payload["baseline_demand_ppm_per_day"]
    )


def test_manual_dpd_tests_normalize_to_high_confidence_fc_observations() -> None:
    config = FcDemandConfig(enabled=True)
    lab_tests = (
        LabTest(sampled_at=at(20, 20), free_chlorine=4.0),
        LabTest(sampled_at=at(21, 14), free_chlorine=3.5),
        LabTest(sampled_at=at(21, 20), free_chlorine=3.0),
    )

    observations = fc_observations_from_lab_tests(
        config=config,
        lab_tests=lab_tests,
        timezone_name="UTC",
    )
    legacy_observations = manual_dpd_fc_observations(
        config=config,
        fc_tests=(
            FcTestPoint(sampled_at=at(20, 20), free_chlorine=4.0),
            FcTestPoint(sampled_at=at(21, 14), free_chlorine=3.5),
            FcTestPoint(sampled_at=at(21, 20), free_chlorine=3.0),
        ),
        timezone_name="UTC",
    )

    assert [observation.source.value for observation in observations] == [
        "manual_dpd",
        "manual_dpd",
        "manual_dpd",
    ]
    assert [observation.confidence for observation in observations] == [1.0, 1.0, 1.0]
    assert [observation.quality for observation in observations] == ["high", "high", "high"]
    assert [observation.timing for observation in observations] == [
        FcObservationTiming.REFERENCE,
        FcObservationTiming.AD_HOC,
        FcObservationTiming.REFERENCE,
    ]
    assert [(item.sampled_at, item.free_chlorine, item.timing) for item in observations] == [
        (item.sampled_at, item.free_chlorine, item.timing)
        for item in legacy_observations
    ]

    normalized_plan = estimate_fc_demand_plan(
        config=config,
        now=at(22, 1),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(),
        fc_observations=observations,
    )
    legacy_plan = estimate_fc_demand_plan(
        config=config,
        now=at(22, 1),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(),
        fc_tests=(
            FcTestPoint(sampled_at=at(20, 20), free_chlorine=4.0),
            FcTestPoint(sampled_at=at(21, 14), free_chlorine=3.5),
            FcTestPoint(sampled_at=at(21, 20), free_chlorine=3.0),
        ),
    )
    assert normalized_plan.status.daily_demand_ppm == legacy_plan.status.daily_demand_ppm
    assert normalized_plan.status.feedback_dose_oz == legacy_plan.status.feedback_dose_oz


def test_daytime_ad_hoc_tests_do_not_replace_reference_demand_interval() -> None:
    plan = estimate_fc_demand_plan(
        config=FcDemandConfig(enabled=True, mode=ControlMode.RECOMMEND),
        now=at(23, 1),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(),
        fc_tests=(
            FcTestPoint(sampled_at=at(20, 22), free_chlorine=4.0),
            FcTestPoint(sampled_at=at(21, 10), free_chlorine=3.8),
            FcTestPoint(sampled_at=at(21, 14), free_chlorine=3.6),
            FcTestPoint(sampled_at=at(21, 22), free_chlorine=3.0),
        ),
    )

    assert plan.status.ready is True
    assert plan.status.observation_count == 1
    assert plan.status.previous_sampled_at == at(20, 22)
    assert plan.status.current_sampled_at == at(21, 22)
    assert round(plan.status.daily_demand_ppm or 0.0, 3) == 1.0
    assert plan.status.latest_fc_is_reference is True
    assert plan.status.latest_reference_fc_sampled_at == at(21, 22)


def test_multiple_daytime_tests_do_not_crowd_out_nightly_references() -> None:
    plan = estimate_fc_demand_plan(
        config=FcDemandConfig(
            enabled=True,
            mode=ControlMode.RECOMMEND,
            max_maintenance_change_percent=1000.0,
        ),
        now=at(17, 12),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(),
        fc_tests=(
            FcTestPoint(sampled_at=at(10, 20), free_chlorine=20.0),
            FcTestPoint(sampled_at=at(11, 10), free_chlorine=19.8),
            FcTestPoint(sampled_at=at(11, 14), free_chlorine=19.5),
            FcTestPoint(sampled_at=at(11, 20), free_chlorine=19.0),
            FcTestPoint(sampled_at=at(12, 10), free_chlorine=18.5),
            FcTestPoint(sampled_at=at(12, 14), free_chlorine=18.0),
            FcTestPoint(sampled_at=at(12, 20), free_chlorine=17.0),
            FcTestPoint(sampled_at=at(13, 20), free_chlorine=14.0),
            FcTestPoint(sampled_at=at(14, 20), free_chlorine=10.0),
            FcTestPoint(sampled_at=at(15, 20), free_chlorine=5.0),
        ),
    )

    assert plan.status.observation_count == 5
    assert [
        (observation.start_sampled_at, observation.end_sampled_at)
        for observation in reversed(plan.status.observations_used)
    ] == [
        (at(10, 20), at(11, 20)),
        (at(11, 20), at(12, 20)),
        (at(12, 20), at(13, 20)),
        (at(13, 20), at(14, 20)),
        (at(14, 20), at(15, 20)),
    ]


def test_default_reference_window_classifies_19_as_reference_and_14_as_ad_hoc() -> None:
    config = FcDemandConfig(enabled=True)
    observations = manual_dpd_fc_observations(
        config=config,
        fc_tests=(
            FcTestPoint(sampled_at=at(20, 19), free_chlorine=4.0),
            FcTestPoint(sampled_at=at(21, 14), free_chlorine=3.5),
            FcTestPoint(sampled_at=at(21, 19), free_chlorine=3.0),
        ),
        timezone_name="UTC",
    )

    assert [observation.timing for observation in observations] == [
        FcObservationTiming.REFERENCE,
        FcObservationTiming.AD_HOC,
        FcObservationTiming.REFERENCE,
    ]

    plan = estimate_fc_demand_plan(
        config=config,
        now=at(22, 1),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(),
        fc_observations=observations,
    )
    assert plan.status.ready is True
    assert plan.status.previous_sampled_at == at(20, 19)
    assert plan.status.current_sampled_at == at(21, 19)


def test_daytime_ad_hoc_test_does_not_create_next_day_feedback() -> None:
    plan = estimate_fc_demand_plan(
        config=FcDemandConfig(
            enabled=True,
            mode=ControlMode.AUTOMATIC,
            target_fc_ppm=4.0,
            fc_feedback_gain=0.6,
        ),
        now=at(23, 1),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(),
        fc_tests=(
            FcTestPoint(sampled_at=at(20, 20), free_chlorine=4.0),
            FcTestPoint(sampled_at=at(21, 20), free_chlorine=3.0),
            FcTestPoint(sampled_at=at(22, 14), free_chlorine=2.5),
        ),
    )

    assert plan.status.ready is True
    assert plan.status.latest_fc_observation_timing == FcObservationTiming.AD_HOC
    assert plan.status.latest_fc_is_reference is False
    assert plan.status.latest_reference_fc_sampled_at == at(21, 20)
    assert plan.status.feedback_control_date == at(22, 20).date()
    assert plan.status.feedback_active_today is False
    assert plan.status.applied_feedback_dose_oz == 0.0


def test_evening_reference_test_creates_one_next_day_feedback() -> None:
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
            FcTestPoint(sampled_at=at(20, 20), free_chlorine=4.0),
            FcTestPoint(sampled_at=at(21, 20), free_chlorine=3.0),
        ),
    )

    assert plan.status.latest_fc_observation_timing == FcObservationTiming.REFERENCE
    assert plan.status.feedback_control_date == at(22, 20).date()
    assert plan.status.feedback_active_today is True
    assert round(plan.status.applied_feedback_dose_oz, 3) == 6.4


def test_missing_nightly_tests_still_allow_multi_day_reference_observation() -> None:
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
    assert plan.status.previous_sampled_at == at(20, 20)
    assert plan.status.current_sampled_at == at(23, 20)
    assert plan.status.elapsed_days == 3.0
    assert plan.status.daily_demand_ppm == 1.0


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
            FcTestPoint(sampled_at=at(20, 20), free_chlorine=4.0),
            FcTestPoint(sampled_at=at(21, 20), free_chlorine=3.0),
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
        FcTestPoint(sampled_at=at(20, 20), free_chlorine=4.0),
        FcTestPoint(sampled_at=at(21, 20), free_chlorine=3.0),
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
            FcTestPoint(sampled_at=at(20, 20), free_chlorine=4.0),
            FcTestPoint(sampled_at=at(21, 20), free_chlorine=3.0),
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
            FcTestPoint(sampled_at=at(20, 20), free_chlorine=5.0),
            FcTestPoint(sampled_at=at(21, 20), free_chlorine=5.0),
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
            FcTestPoint(sampled_at=at(20, 20), free_chlorine=3.0),
            FcTestPoint(sampled_at=at(21, 20), free_chlorine=2.0),
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
            FcTestPoint(sampled_at=at(10, 20), free_chlorine=10.0),
            FcTestPoint(sampled_at=at(11, 20), free_chlorine=9.0),
            FcTestPoint(sampled_at=at(12, 20), free_chlorine=7.0),
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
            FcTestPoint(sampled_at=at(20, 20), free_chlorine=4.0),
            FcTestPoint(sampled_at=at(21, 20), free_chlorine=3.0),
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
            FcTestPoint(sampled_at=at(20, 20), free_chlorine=5.0),
            FcTestPoint(sampled_at=at(21, 20), free_chlorine=4.0),
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
            FcTestPoint(sampled_at=at(20, 20), free_chlorine=4.0),
            FcTestPoint(sampled_at=at(21, 20), free_chlorine=4.0),
        ),
        sodium_hypochlorite_additions=(addition,),
    )

    assert round(plan.status.manual_hypo_oz, 3) == 10.0
    assert round(plan.status.added_fc_ppm or 0.0, 3) == 0.938
    assert round(plan.status.daily_demand_ppm or 0.0, 3) == 0.938
    assert plan.adjustment is None


def test_observe_only_and_recommend_do_not_alter_chlorination() -> None:
    fc_tests = (
        FcTestPoint(sampled_at=at(20, 20), free_chlorine=4.0),
        FcTestPoint(sampled_at=at(21, 20), free_chlorine=3.0),
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
            FcTestPoint(sampled_at=at(20, 20), free_chlorine=4.0),
            FcTestPoint(sampled_at=at(21, 20), free_chlorine=3.0),
        ),
    )

    assert plan.adjustment is not None
    assert round(plan.adjustment.daily_dose_oz or 0.0, 3) == 10.667
    assert plan.adjustment.delay_eligible_seconds == 0.0
    assert plan.adjustment.source == "fc_demand"
