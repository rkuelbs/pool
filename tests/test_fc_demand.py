from __future__ import annotations

from datetime import datetime, timezone

from poolctl.domain.models import ChemicalAddition, ChemicalType, ControlMode
from poolctl.services.chlorination import ChlorinationConfig
from poolctl.services.fc_demand import (
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


def test_low_fc_catch_up_dose_is_applied_only_on_next_day() -> None:
    config = FcDemandConfig(
        enabled=True,
        mode=ControlMode.AUTOMATIC,
        target_fc_ppm=4.0,
        pool_volume_gal=10000.0,
        chlorine_strength_percent=12.0,
    )

    plan = estimate_fc_demand_plan(
        config=config,
        now=at(22, 1),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(no_dose_last_minutes=10.0),
        fc_tests=(
            FcTestPoint(sampled_at=at(20, 12), free_chlorine=4.0),
            FcTestPoint(sampled_at=at(21, 12), free_chlorine=3.0),
        ),
        automated_chlorine_oz=0.0,
        sodium_hypochlorite_additions=(),
    )

    assert plan.status.ready is True
    assert round(plan.status.maintenance_dose_oz_per_day or 0.0, 3) == 10.667
    assert round(plan.status.catch_up_dose_oz_next_day, 3) == 10.667
    assert round(plan.status.effective_daily_dose_oz or 0.0, 3) == 21.333
    assert plan.adjustment is not None
    assert round(plan.adjustment.daily_dose_oz or 0.0, 3) == 21.333

    later = estimate_fc_demand_plan(
        config=config,
        now=at(23, 1),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(no_dose_last_minutes=10.0),
        fc_tests=(
            FcTestPoint(sampled_at=at(20, 12), free_chlorine=4.0),
            FcTestPoint(sampled_at=at(21, 12), free_chlorine=3.0),
        ),
        automated_chlorine_oz=0.0,
        sodium_hypochlorite_additions=(),
    )

    assert round(later.status.effective_daily_dose_oz or 0.0, 3) == 10.667


def test_high_fc_creates_next_day_eligible_time_delay_without_changing_duty() -> None:
    config = FcDemandConfig(
        enabled=True,
        mode=ControlMode.AUTOMATIC,
        target_fc_ppm=4.0,
        pool_volume_gal=10000.0,
        chlorine_strength_percent=12.0,
    )

    plan = estimate_fc_demand_plan(
        config=config,
        now=at(22, 1),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(no_dose_last_minutes=10.0),
        fc_tests=(
            FcTestPoint(sampled_at=at(20, 12), free_chlorine=4.0),
            FcTestPoint(sampled_at=at(21, 12), free_chlorine=4.5),
        ),
        automated_chlorine_oz=16.0,
        sodium_hypochlorite_additions=(),
    )

    assert plan.status.ready is True
    assert round(plan.status.daily_demand_ppm or 0.0, 3) == 1.0
    assert round(plan.status.skip_days, 3) == 0.5
    assert round(plan.status.available_dosing_minutes_today, 3) == 420.0
    assert round(plan.status.delay_eligible_minutes_today, 3) == 210.0
    assert round(plan.status.effective_daily_dose_oz or 0.0, 3) == 10.667
    assert plan.adjustment is not None
    assert round(plan.adjustment.delay_eligible_seconds, 3) == 12600.0


def test_manual_sodium_hypochlorite_additions_count_toward_fc_added() -> None:
    config = FcDemandConfig(enabled=True, mode=ControlMode.RECOMMEND)
    addition = ChemicalAddition(
        added_at=at(21, 8),
        chemical=ChemicalType.SODIUM_HYPOCHLORITE,
        amount=10.0,
        unit="fl_oz",
        amount_fl_oz=10.0,
        strength_percent=12.0,
    )

    plan = estimate_fc_demand_plan(
        config=config,
        now=at(22, 1),
        pump_timer_config=timer_config(),
        chlorination_config=ChlorinationConfig(no_dose_last_minutes=10.0),
        fc_tests=(
            FcTestPoint(sampled_at=at(20, 12), free_chlorine=4.0),
            FcTestPoint(sampled_at=at(21, 12), free_chlorine=4.0),
        ),
        automated_chlorine_oz=0.0,
        sodium_hypochlorite_additions=(addition,),
    )

    assert round(plan.status.manual_hypo_oz, 3) == 10.0
    assert round(plan.status.added_fc_ppm or 0.0, 3) == 0.938
    assert plan.adjustment is None
