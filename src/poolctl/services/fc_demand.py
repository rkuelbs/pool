"""
Free-chlorine demand estimator.

This service uses manual FC test results and logged chlorine additions to
estimate how many ounces per day the pool has been consuming. ORP and pH are
left out on purpose so the first closed-loop behavior is understandable and
based on hand-entered chemistry tests.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from poolctl.domain.models import ChemicalAddition, ChemicalType, ControlMode
from poolctl.services.chlorination import (
    ChlorinationConfig,
    ChlorinationPlanAdjustment,
    valid_dosing_windows_for_day,
)
from poolctl.services.pump_timer import PumpTimerConfig


@dataclass(frozen=True)
class FcDemandConfig:
    """
    Free-chlorine demand estimator settings.

    The estimator intentionally uses only manually tested free chlorine and
    known chlorine additions/delivery. ORP and pH are not control inputs here.
    """

    enabled: bool = False
    mode: ControlMode = ControlMode.OBSERVE_ONLY
    pool_volume_gal: float = 10000.0
    target_fc_ppm: float = 4.0
    chlorine_strength_percent: float = 12.0
    minimum_test_interval_hours: float = 12.0
    max_daily_dose_oz: float = 256.0

    def __post_init__(self) -> None:
        if self.pool_volume_gal <= 0:
            raise ValueError("fc_demand.pool_volume_gal must be > 0")
        if self.target_fc_ppm < 0:
            raise ValueError("fc_demand.target_fc_ppm must be >= 0")
        if self.chlorine_strength_percent <= 0:
            raise ValueError("fc_demand.chlorine_strength_percent must be > 0")
        if self.minimum_test_interval_hours < 0:
            raise ValueError("fc_demand.minimum_test_interval_hours must be >= 0")
        if self.max_daily_dose_oz < 0:
            raise ValueError("fc_demand.max_daily_dose_oz must be >= 0")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> FcDemandConfig:
        config_data = _mapping_value(data, "fc_demand", default={})
        return cls(
            enabled=_bool_value(config_data, "enabled", cls.enabled),
            mode=_control_mode_value(config_data, "mode", cls.mode),
            pool_volume_gal=_float_value(
                config_data,
                "pool_volume_gal",
                cls.pool_volume_gal,
            ),
            target_fc_ppm=_float_value(config_data, "target_fc_ppm", cls.target_fc_ppm),
            chlorine_strength_percent=_float_value(
                config_data,
                "chlorine_strength_percent",
                cls.chlorine_strength_percent,
            ),
            minimum_test_interval_hours=_float_value(
                config_data,
                "minimum_test_interval_hours",
                cls.minimum_test_interval_hours,
            ),
            max_daily_dose_oz=_float_value(
                config_data,
                "max_daily_dose_oz",
                cls.max_daily_dose_oz,
            ),
        )


@dataclass(frozen=True)
class FcTestPoint:
    sampled_at: datetime
    free_chlorine: float


@dataclass(frozen=True)
class FcDemandStatus:
    enabled: bool
    mode: ControlMode
    ready: bool
    reason: str
    target_fc_ppm: float
    pool_volume_gal: float
    chlorine_strength_percent: float
    previous_sampled_at: datetime | None = None
    previous_fc_ppm: float | None = None
    current_sampled_at: datetime | None = None
    current_fc_ppm: float | None = None
    elapsed_days: float | None = None
    automated_chlorine_oz: float = 0.0
    manual_hypo_oz: float = 0.0
    added_fc_ppm: float | None = None
    consumed_fc_ppm: float | None = None
    daily_demand_ppm: float | None = None
    maintenance_dose_oz_per_day: float | None = None
    correction_fc_ppm: float | None = None
    catch_up_dose_oz_next_day: float = 0.0
    skip_days: float = 0.0
    next_adjustment_date: date | None = None
    recommended_daily_dose_oz: float | None = None
    effective_daily_dose_oz: float | None = None
    delay_eligible_minutes_today: float = 0.0
    available_dosing_minutes_today: float = 0.0
    applied_automatic: bool = False
    warning: str | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "mode": self.mode.value,
            "ready": self.ready,
            "reason": self.reason,
            "target_fc_ppm": self.target_fc_ppm,
            "pool_volume_gal": self.pool_volume_gal,
            "chlorine_strength_percent": self.chlorine_strength_percent,
            "previous_sampled_at": (
                self.previous_sampled_at.isoformat()
                if self.previous_sampled_at is not None
                else None
            ),
            "previous_fc_ppm": self.previous_fc_ppm,
            "current_sampled_at": (
                self.current_sampled_at.isoformat()
                if self.current_sampled_at is not None
                else None
            ),
            "current_fc_ppm": self.current_fc_ppm,
            "elapsed_days": self.elapsed_days,
            "automated_chlorine_oz": self.automated_chlorine_oz,
            "manual_hypo_oz": self.manual_hypo_oz,
            "added_fc_ppm": self.added_fc_ppm,
            "consumed_fc_ppm": self.consumed_fc_ppm,
            "daily_demand_ppm": self.daily_demand_ppm,
            "maintenance_dose_oz_per_day": self.maintenance_dose_oz_per_day,
            "correction_fc_ppm": self.correction_fc_ppm,
            "catch_up_dose_oz_next_day": self.catch_up_dose_oz_next_day,
            "skip_days": self.skip_days,
            "next_adjustment_date": (
                self.next_adjustment_date.isoformat()
                if self.next_adjustment_date is not None
                else None
            ),
            "recommended_daily_dose_oz": self.recommended_daily_dose_oz,
            "effective_daily_dose_oz": self.effective_daily_dose_oz,
            "delay_eligible_minutes_today": self.delay_eligible_minutes_today,
            "available_dosing_minutes_today": self.available_dosing_minutes_today,
            "applied_automatic": self.applied_automatic,
            "warning": self.warning,
        }


@dataclass(frozen=True)
class FcDemandPlan:
    status: FcDemandStatus
    adjustment: ChlorinationPlanAdjustment | None = None


def estimate_fc_demand_plan(
    *,
    config: FcDemandConfig,
    now: datetime,
    pump_timer_config: PumpTimerConfig,
    chlorination_config: ChlorinationConfig,
    fc_tests: Sequence[FcTestPoint],
    automated_chlorine_oz: float,
    sodium_hypochlorite_additions: Sequence[ChemicalAddition],
) -> FcDemandPlan:
    if not config.enabled:
        return FcDemandPlan(
            status=FcDemandStatus(
                enabled=False,
                mode=config.mode,
                ready=False,
                reason="FC demand estimator disabled",
                target_fc_ppm=config.target_fc_ppm,
                pool_volume_gal=config.pool_volume_gal,
                chlorine_strength_percent=config.chlorine_strength_percent,
            )
        )

    clean_tests = tuple(
        sorted(
            (
                FcTestPoint(sampled_at=test.sampled_at, free_chlorine=float(test.free_chlorine))
                for test in fc_tests
                if test.free_chlorine >= 0
            ),
            key=lambda item: item.sampled_at,
        )
    )
    if len(clean_tests) < 2:
        return FcDemandPlan(
            status=_base_status(
                config,
                ready=False,
                reason="need at least two free chlorine tests",
            )
        )

    previous = clean_tests[-2]
    current = clean_tests[-1]
    elapsed_hours = (current.sampled_at - previous.sampled_at).total_seconds() / 3600.0
    if elapsed_hours <= 0:
        return FcDemandPlan(
            status=_base_status(
                config,
                ready=False,
                reason="latest FC tests are not in chronological order",
                previous=previous,
                current=current,
            )
        )
    if elapsed_hours < config.minimum_test_interval_hours:
        return FcDemandPlan(
            status=_base_status(
                config,
                ready=False,
                reason="FC tests are closer than the configured minimum interval",
                previous=previous,
                current=current,
                elapsed_days=elapsed_hours / 24.0,
            )
        )

    elapsed_days = elapsed_hours / 24.0
    automated_chlorine_oz = max(0.0, automated_chlorine_oz)

    # Convert actual delivered sodium hypochlorite into FC ppm added to the
    # pool. This uses the same strength and pool volume assumptions as the
    # dosing recommendation, so the estimate stays internally consistent.
    automated_added_fc = fc_ppm_from_fl_oz(
        automated_chlorine_oz,
        strength_percent=config.chlorine_strength_percent,
        pool_volume_gal=config.pool_volume_gal,
    )

    # Manual sodium-hypochlorite additions entered on the GUI count too. Acid
    # additions and other chemistry events do not affect FC demand.
    manual_hypo_oz = sum(
        addition.amount_fl_oz
        for addition in sodium_hypochlorite_additions
        if addition.chemical == ChemicalType.SODIUM_HYPOCHLORITE
    )
    manual_added_fc = sum(
        fc_ppm_from_fl_oz(
            addition.amount_fl_oz,
            strength_percent=addition.strength_percent,
            pool_volume_gal=config.pool_volume_gal,
        )
        for addition in sodium_hypochlorite_additions
        if addition.chemical == ChemicalType.SODIUM_HYPOCHLORITE
    )
    added_fc_ppm = automated_added_fc + manual_added_fc

    # Mass balance:
    #   previous FC + FC added - FC consumed = current FC
    # Therefore:
    #   FC consumed = previous FC + FC added - current FC
    consumed_fc_ppm = previous.free_chlorine + added_fc_ppm - current.free_chlorine
    raw_daily_demand_ppm = consumed_fc_ppm / elapsed_days
    daily_demand_ppm = max(0.0, raw_daily_demand_ppm)
    maintenance_dose_oz = fl_oz_for_fc_ppm(
        daily_demand_ppm,
        strength_percent=config.chlorine_strength_percent,
        pool_volume_gal=config.pool_volume_gal,
    )
    warning = None
    if maintenance_dose_oz > config.max_daily_dose_oz:
        maintenance_dose_oz = config.max_daily_dose_oz
        warning = "estimated maintenance dose is capped by fc_demand.max_daily_dose_oz"

    correction_fc_ppm = config.target_fc_ppm - current.free_chlorine
    catch_up_dose_oz = (
        fl_oz_for_fc_ppm(
            correction_fc_ppm,
            strength_percent=config.chlorine_strength_percent,
            pool_volume_gal=config.pool_volume_gal,
        )
        if correction_fc_ppm > 0
        else 0.0
    )

    # If FC is above target, keep the learned daily duty cycle but delay the
    # next day's dosing start by the fraction of a normal day's demand that is
    # already "stored" as excess FC.
    skip_days = (
        abs(correction_fc_ppm) / daily_demand_ppm
        if correction_fc_ppm < 0 and daily_demand_ppm > 0
        else 0.0
    )

    timezone = ZoneInfo(pump_timer_config.timezone)
    local_date = now.astimezone(timezone).date()
    next_adjustment_date = current.sampled_at.astimezone(timezone).date() + timedelta(days=1)
    available_minutes_today = _available_minutes_for_day(
        pump_timer_config,
        local_date,
        chlorination_config=chlorination_config,
    )

    recommended_daily_dose_oz = maintenance_dose_oz
    effective_daily_dose_oz = maintenance_dose_oz
    delay_eligible_minutes_today = 0.0
    if correction_fc_ppm > 0:
        # Low FC is corrected on the next local day by adding one catch-up dose
        # to the learned maintenance dose.
        recommended_daily_dose_oz = maintenance_dose_oz + catch_up_dose_oz
        if local_date == next_adjustment_date:
            effective_daily_dose_oz = recommended_daily_dose_oz
    elif correction_fc_ppm < 0 and skip_days > 0 and local_date >= next_adjustment_date:
        elapsed_adjustment_days = (local_date - next_adjustment_date).days
        remaining_skip_days = max(0.0, skip_days - elapsed_adjustment_days)

        # Delay is expressed in eligible dosing minutes, not clock minutes, so a
        # short pump schedule still delays by the correct fraction of that
        # schedule's normal dosing opportunity.
        delay_eligible_minutes_today = min(1.0, remaining_skip_days) * available_minutes_today

    if effective_daily_dose_oz > config.max_daily_dose_oz:
        effective_daily_dose_oz = config.max_daily_dose_oz
        warning = "effective daily dose is capped by fc_demand.max_daily_dose_oz"

    applied_automatic = config.mode == ControlMode.AUTOMATIC
    status = FcDemandStatus(
        enabled=True,
        mode=config.mode,
        ready=True,
        reason="FC demand estimate ready",
        target_fc_ppm=config.target_fc_ppm,
        pool_volume_gal=config.pool_volume_gal,
        chlorine_strength_percent=config.chlorine_strength_percent,
        previous_sampled_at=previous.sampled_at,
        previous_fc_ppm=previous.free_chlorine,
        current_sampled_at=current.sampled_at,
        current_fc_ppm=current.free_chlorine,
        elapsed_days=elapsed_days,
        automated_chlorine_oz=automated_chlorine_oz,
        manual_hypo_oz=manual_hypo_oz,
        added_fc_ppm=added_fc_ppm,
        consumed_fc_ppm=consumed_fc_ppm,
        daily_demand_ppm=daily_demand_ppm,
        maintenance_dose_oz_per_day=maintenance_dose_oz,
        correction_fc_ppm=correction_fc_ppm,
        catch_up_dose_oz_next_day=catch_up_dose_oz,
        skip_days=skip_days,
        next_adjustment_date=next_adjustment_date,
        recommended_daily_dose_oz=recommended_daily_dose_oz,
        effective_daily_dose_oz=effective_daily_dose_oz,
        delay_eligible_minutes_today=delay_eligible_minutes_today,
        available_dosing_minutes_today=available_minutes_today,
        applied_automatic=applied_automatic,
        warning=warning,
    )

    adjustment = None
    if applied_automatic:
        adjustment = ChlorinationPlanAdjustment(
            daily_dose_oz=effective_daily_dose_oz,
            delay_eligible_seconds=delay_eligible_minutes_today * 60.0,
            source="fc_demand",
            reason=status.reason,
        )

    return FcDemandPlan(status=status, adjustment=adjustment)


def fc_ppm_from_fl_oz(
    amount_fl_oz: float,
    *,
    strength_percent: float,
    pool_volume_gal: float,
) -> float:
    if amount_fl_oz <= 0:
        return 0.0
    if strength_percent <= 0:
        raise ValueError("strength_percent must be > 0")
    if pool_volume_gal <= 0:
        raise ValueError("pool_volume_gal must be > 0")

    # Rule-of-thumb concentration math: 1 gallon of 10% chlorine in 10,000
    # gallons raises FC by about 10 ppm. `amount_fl_oz / 128` converts ounces to
    # gallons, then strength and pool volume scale the result.
    return (amount_fl_oz / 128.0) * strength_percent * (10000.0 / pool_volume_gal)


def fl_oz_for_fc_ppm(
    fc_ppm: float,
    *,
    strength_percent: float,
    pool_volume_gal: float,
) -> float:
    if fc_ppm <= 0:
        return 0.0
    if strength_percent <= 0:
        raise ValueError("strength_percent must be > 0")
    if pool_volume_gal <= 0:
        raise ValueError("pool_volume_gal must be > 0")
    return fc_ppm * 128.0 * (pool_volume_gal / 10000.0) / strength_percent


def _base_status(
    config: FcDemandConfig,
    *,
    ready: bool,
    reason: str,
    previous: FcTestPoint | None = None,
    current: FcTestPoint | None = None,
    elapsed_days: float | None = None,
) -> FcDemandStatus:
    return FcDemandStatus(
        enabled=config.enabled,
        mode=config.mode,
        ready=ready,
        reason=reason,
        target_fc_ppm=config.target_fc_ppm,
        pool_volume_gal=config.pool_volume_gal,
        chlorine_strength_percent=config.chlorine_strength_percent,
        previous_sampled_at=previous.sampled_at if previous is not None else None,
        previous_fc_ppm=previous.free_chlorine if previous is not None else None,
        current_sampled_at=current.sampled_at if current is not None else None,
        current_fc_ppm=current.free_chlorine if current is not None else None,
        elapsed_days=elapsed_days,
    )


def _available_minutes_for_day(
    pump_timer_config: PumpTimerConfig,
    day: date,
    *,
    chlorination_config: ChlorinationConfig,
) -> float:
    return sum(
        window.duration_seconds
        for window in valid_dosing_windows_for_day(
            pump_timer_config,
            day,
            no_dose_last_minutes=chlorination_config.no_dose_last_minutes,
        )
    ) / 60.0


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


def _bool_value(data: Mapping[str, Any], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if isinstance(value, bool):
        return value
    raise ValueError(f"{key} must be true or false")


def _float_value(data: Mapping[str, Any], key: str, default: float) -> float:
    value = data.get(key, default)
    if isinstance(value, int | float):
        return float(value)
    raise ValueError(f"{key} must be a number")


def _control_mode_value(
    data: Mapping[str, Any],
    key: str,
    default: ControlMode,
) -> ControlMode:
    value = data.get(key, default.value)
    if isinstance(value, ControlMode):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return ControlMode(value)
