"""
Free-chlorine demand controller.

This service uses manual FC test results and logged chlorine additions to build
observed daily chlorine demand. It deliberately leaves ORP, pH, weather, UV,
and water temperature out of the control law so the first adaptive behavior is
auditable from hand-entered chemistry tests and known chlorine additions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
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


DEFAULT_MAX_OBSERVATION_INTERVAL_DAYS = 7.0
DEFAULT_RECENT_OBSERVATION_COUNT = 5
DEFAULT_OBSERVATION_WEIGHTS = (0.35, 0.25, 0.18, 0.13, 0.09)
DEFAULT_FC_FEEDBACK_GAIN = 0.6
DEFAULT_MAX_MAINTENANCE_CHANGE_PERCENT = 15.0


@dataclass(frozen=True)
class FcDemandConfig:
    """
    Free-chlorine adaptive feed-forward controller settings.

    The controller learns a maintenance dose from observed FC demand, then
    applies a one-day signed FC target correction after a new manual test.
    """

    enabled: bool = False
    mode: ControlMode = ControlMode.OBSERVE_ONLY
    pool_volume_gal: float = 10000.0
    target_fc_ppm: float = 4.0
    chlorine_strength_percent: float = 12.0
    minimum_test_interval_hours: float = 12.0
    max_observation_interval_days: float = DEFAULT_MAX_OBSERVATION_INTERVAL_DAYS
    recent_observation_count: int = DEFAULT_RECENT_OBSERVATION_COUNT
    observation_weights: tuple[float, ...] = field(
        default_factory=lambda: DEFAULT_OBSERVATION_WEIGHTS
    )
    fc_feedback_gain: float = DEFAULT_FC_FEEDBACK_GAIN
    max_maintenance_change_percent: float = DEFAULT_MAX_MAINTENANCE_CHANGE_PERCENT
    max_daily_dose_oz: float = 256.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "observation_weights",
            tuple(float(weight) for weight in self.observation_weights),
        )

        if self.pool_volume_gal <= 0:
            raise ValueError("fc_demand.pool_volume_gal must be > 0")
        if self.target_fc_ppm < 0:
            raise ValueError("fc_demand.target_fc_ppm must be >= 0")
        if self.chlorine_strength_percent <= 0:
            raise ValueError("fc_demand.chlorine_strength_percent must be > 0")
        if self.minimum_test_interval_hours < 0:
            raise ValueError("fc_demand.minimum_test_interval_hours must be >= 0")
        if self.max_observation_interval_days <= 0:
            raise ValueError("fc_demand.max_observation_interval_days must be > 0")
        if self.recent_observation_count < 1:
            raise ValueError("fc_demand.recent_observation_count must be >= 1")
        if not self.observation_weights:
            raise ValueError("fc_demand.observation_weights must not be empty")
        if any(weight <= 0 for weight in self.observation_weights):
            raise ValueError("fc_demand.observation_weights entries must be > 0")
        if len(self.observation_weights) < self.recent_observation_count:
            raise ValueError(
                "fc_demand.observation_weights must contain at least "
                "recent_observation_count entries"
            )
        if self.fc_feedback_gain < 0:
            raise ValueError("fc_demand.fc_feedback_gain must be >= 0")
        if self.max_maintenance_change_percent < 0:
            raise ValueError(
                "fc_demand.max_maintenance_change_percent must be >= 0"
            )
        if self.max_daily_dose_oz < 0:
            raise ValueError("fc_demand.max_daily_dose_oz must be >= 0")

    @property
    def demand_window_days(self) -> float:
        """
        Backward-compatible alias for older status/API callers.
        """

        return self.max_observation_interval_days

    @property
    def max_demand_window_days(self) -> float:
        """
        Backward-compatible alias for older status/API callers.
        """

        return self.max_observation_interval_days

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
            max_observation_interval_days=_legacy_observation_interval_days(
                config_data,
                cls.max_observation_interval_days,
            ),
            recent_observation_count=_int_value(
                config_data,
                "recent_observation_count",
                cls.recent_observation_count,
            ),
            observation_weights=_float_tuple_value(
                config_data,
                "observation_weights",
                DEFAULT_OBSERVATION_WEIGHTS,
            ),
            fc_feedback_gain=_float_value(
                config_data,
                "fc_feedback_gain",
                cls.fc_feedback_gain,
            ),
            max_maintenance_change_percent=_float_value(
                config_data,
                "max_maintenance_change_percent",
                cls.max_maintenance_change_percent,
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
class ChlorineDeliveryPoint:
    observed_at: datetime
    delivered_oz: float


@dataclass(frozen=True)
class FcDemandTestSelection:
    previous: FcTestPoint
    current: FcTestPoint
    elapsed_hours: float
    demand_window_source: str


@dataclass(frozen=True)
class FcDemandObservation:
    start_sampled_at: datetime
    end_sampled_at: datetime
    elapsed_days: float
    start_fc_ppm: float
    end_fc_ppm: float
    automated_chlorine_oz: float
    manual_sodium_hypochlorite_oz: float
    total_added_fc_ppm: float
    consumed_fc_ppm: float
    demand_ppm_per_day: float

    def as_payload(self, *, weight: float | None = None) -> dict[str, Any]:
        payload = {
            "start_sampled_at": self.start_sampled_at.isoformat(),
            "end_sampled_at": self.end_sampled_at.isoformat(),
            "elapsed_days": self.elapsed_days,
            "start_fc_ppm": self.start_fc_ppm,
            "end_fc_ppm": self.end_fc_ppm,
            "automated_chlorine_oz": self.automated_chlorine_oz,
            "manual_sodium_hypochlorite_oz": self.manual_sodium_hypochlorite_oz,
            "total_added_fc_ppm": self.total_added_fc_ppm,
            "consumed_fc_ppm": self.consumed_fc_ppm,
            "demand_ppm_per_day": self.demand_ppm_per_day,
        }
        if weight is not None:
            payload["weight"] = weight
        return payload


@dataclass(frozen=True)
class FcDemandStatus:
    enabled: bool
    mode: ControlMode
    ready: bool
    reason: str
    target_fc_ppm: float
    pool_volume_gal: float
    chlorine_strength_percent: float
    latest_fc_ppm: float | None = None
    latest_fc_sampled_at: datetime | None = None
    latest_fc_age_hours: float | None = None
    latest_fc_age_days: float | None = None
    previous_sampled_at: datetime | None = None
    previous_fc_ppm: float | None = None
    current_sampled_at: datetime | None = None
    current_fc_ppm: float | None = None
    elapsed_days: float | None = None
    demand_window_days: float = DEFAULT_MAX_OBSERVATION_INTERVAL_DAYS
    max_demand_window_days: float = DEFAULT_MAX_OBSERVATION_INTERVAL_DAYS
    max_observation_interval_days: float = DEFAULT_MAX_OBSERVATION_INTERVAL_DAYS
    demand_window_source: str | None = None
    automated_chlorine_oz: float = 0.0
    manual_hypo_oz: float = 0.0
    added_fc_ppm: float | None = None
    consumed_fc_ppm: float | None = None
    daily_demand_ppm: float | None = None
    latest_observed_demand_ppm_per_day: float | None = None
    weighted_maintenance_demand_ppm_per_day: float | None = None
    predicted_demand_ppm_per_day: float | None = None
    observation_count: int = 0
    recent_observation_count: int = DEFAULT_RECENT_OBSERVATION_COUNT
    effective_normalized_weights: tuple[float, ...] = ()
    observations_used: tuple[FcDemandObservation, ...] = ()
    maintenance_dose_oz_per_day: float | None = None
    unlimited_maintenance_dose_oz_per_day: float | None = None
    previous_maintenance_dose_oz_per_day: float | None = None
    maintenance_rate_limited: bool = False
    max_maintenance_change_percent: float = DEFAULT_MAX_MAINTENANCE_CHANGE_PERCENT
    correction_fc_ppm: float | None = None
    feedback_fc_ppm: float | None = None
    feedback_dose_oz: float = 0.0
    applied_feedback_dose_oz: float = 0.0
    feedback_active_today: bool = False
    feedback_control_date: date | None = None
    fc_feedback_gain: float = DEFAULT_FC_FEEDBACK_GAIN
    catch_up_dose_oz_next_day: float = 0.0
    skip_days: float = 0.0
    next_adjustment_date: date | None = None
    recommended_daily_dose_oz: float | None = None
    effective_daily_dose_oz: float | None = None
    final_dose_capped: bool = False
    final_dose_floor_limited: bool = False
    delay_eligible_minutes_today: float = 0.0
    available_dosing_minutes_today: float = 0.0
    applied_automatic: bool = False
    confidence: str = "learning"
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
            "latest_fc_ppm": self.latest_fc_ppm,
            "latest_fc_sampled_at": (
                self.latest_fc_sampled_at.isoformat()
                if self.latest_fc_sampled_at is not None
                else None
            ),
            "latest_fc_age_hours": self.latest_fc_age_hours,
            "latest_fc_age_days": self.latest_fc_age_days,
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
            "demand_window_days": self.demand_window_days,
            "max_demand_window_days": self.max_demand_window_days,
            "max_observation_interval_days": self.max_observation_interval_days,
            "demand_window_source": self.demand_window_source,
            "automated_chlorine_oz": self.automated_chlorine_oz,
            "manual_hypo_oz": self.manual_hypo_oz,
            "added_fc_ppm": self.added_fc_ppm,
            "consumed_fc_ppm": self.consumed_fc_ppm,
            "daily_demand_ppm": self.daily_demand_ppm,
            "latest_observed_demand_ppm_per_day": (
                self.latest_observed_demand_ppm_per_day
            ),
            "weighted_maintenance_demand_ppm_per_day": (
                self.weighted_maintenance_demand_ppm_per_day
            ),
            "predicted_demand_ppm_per_day": self.predicted_demand_ppm_per_day,
            "observation_count": self.observation_count,
            "recent_observation_count": self.recent_observation_count,
            "effective_normalized_weights": list(self.effective_normalized_weights),
            "observations_used": [
                observation.as_payload(weight=weight)
                for observation, weight in zip(
                    self.observations_used,
                    self.effective_normalized_weights,
                    strict=False,
                )
            ],
            "maintenance_dose_oz_per_day": self.maintenance_dose_oz_per_day,
            "unlimited_maintenance_dose_oz_per_day": (
                self.unlimited_maintenance_dose_oz_per_day
            ),
            "previous_maintenance_dose_oz_per_day": (
                self.previous_maintenance_dose_oz_per_day
            ),
            "maintenance_rate_limited": self.maintenance_rate_limited,
            "max_maintenance_change_percent": self.max_maintenance_change_percent,
            "correction_fc_ppm": self.correction_fc_ppm,
            "feedback_fc_ppm": self.feedback_fc_ppm,
            "feedback_dose_oz": self.feedback_dose_oz,
            "applied_feedback_dose_oz": self.applied_feedback_dose_oz,
            "feedback_active_today": self.feedback_active_today,
            "feedback_control_date": (
                self.feedback_control_date.isoformat()
                if self.feedback_control_date is not None
                else None
            ),
            "fc_feedback_gain": self.fc_feedback_gain,
            "catch_up_dose_oz_next_day": self.catch_up_dose_oz_next_day,
            "skip_days": self.skip_days,
            "next_adjustment_date": (
                self.next_adjustment_date.isoformat()
                if self.next_adjustment_date is not None
                else None
            ),
            "recommended_daily_dose_oz": self.recommended_daily_dose_oz,
            "effective_daily_dose_oz": self.effective_daily_dose_oz,
            "final_dose_capped": self.final_dose_capped,
            "final_dose_floor_limited": self.final_dose_floor_limited,
            "delay_eligible_minutes_today": self.delay_eligible_minutes_today,
            "available_dosing_minutes_today": self.available_dosing_minutes_today,
            "applied_automatic": self.applied_automatic,
            "confidence": self.confidence,
            "warning": self.warning,
        }


@dataclass(frozen=True)
class FcDemandPlan:
    status: FcDemandStatus
    adjustment: ChlorinationPlanAdjustment | None = None


@dataclass(frozen=True)
class _MaintenanceEstimate:
    weighted_demand_ppm_per_day: float
    predicted_demand_ppm_per_day: float
    unlimited_dose_oz_per_day: float
    limited_dose_oz_per_day: float
    previous_limited_dose_oz_per_day: float | None
    rate_limited: bool
    observations_used: tuple[FcDemandObservation, ...]
    normalized_weights: tuple[float, ...]


def fc_demand_test_selection(
    config: FcDemandConfig,
    fc_tests: Sequence[FcTestPoint],
) -> FcDemandTestSelection | None:
    """
    Return the latest adjacent FC-test interval that can form an observation.

    This is retained for compatibility with older callers; the controller now
    uses all recent consecutive observations instead of selecting one lookback
    interval.
    """

    clean_tests = _clean_fc_tests(fc_tests)
    for previous, current in reversed(tuple(zip(clean_tests, clean_tests[1:]))):
        elapsed_hours = (current.sampled_at - previous.sampled_at).total_seconds() / 3600.0
        if not _valid_observation_elapsed_hours(elapsed_hours, config=config):
            continue
        return FcDemandTestSelection(
            previous=previous,
            current=current,
            elapsed_hours=elapsed_hours,
            demand_window_source="consecutive_observation",
        )
    return None


def estimate_fc_demand_plan(
    *,
    config: FcDemandConfig,
    now: datetime,
    pump_timer_config: PumpTimerConfig,
    chlorination_config: ChlorinationConfig,
    fc_tests: Sequence[FcTestPoint],
    automated_chlorine_deliveries: Sequence[ChlorineDeliveryPoint] = (),
    sodium_hypochlorite_additions: Sequence[ChemicalAddition] = (),
    automated_chlorine_oz: float | None = None,
) -> FcDemandPlan:
    clean_tests = tuple(
        test
        for test in _clean_fc_tests(fc_tests)
        if test.sampled_at <= now
    )
    if automated_chlorine_oz is not None and not automated_chlorine_deliveries:
        automated_chlorine_deliveries = _legacy_delivery_points(
            clean_tests,
            automated_chlorine_oz,
        )

    latest_test = clean_tests[-1] if clean_tests else None
    available_minutes_today = _available_minutes_for_day(
        pump_timer_config,
        now.astimezone(ZoneInfo(pump_timer_config.timezone)).date(),
        chlorination_config=chlorination_config,
    )

    if not config.enabled:
        return FcDemandPlan(
            status=_base_status(
                config,
                now=now,
                pump_timer_config=pump_timer_config,
                chlorination_config=chlorination_config,
                ready=False,
                reason="FC demand controller disabled",
                latest_test=latest_test,
                available_minutes_today=available_minutes_today,
            )
        )

    observations = fc_demand_observations(
        config=config,
        fc_tests=clean_tests,
        automated_chlorine_deliveries=automated_chlorine_deliveries,
        sodium_hypochlorite_additions=sodium_hypochlorite_additions,
    )
    if not observations:
        reason = (
            "need at least two free chlorine tests"
            if len(clean_tests) < 2
            else (
                "need consecutive FC tests between "
                f"{config.minimum_test_interval_hours:g} hours and "
                f"{config.max_observation_interval_days:g} days apart"
            )
        )
        return FcDemandPlan(
            status=_base_status(
                config,
                now=now,
                pump_timer_config=pump_timer_config,
                chlorination_config=chlorination_config,
                ready=False,
                reason=reason,
                latest_test=latest_test,
                observation_count=0,
                available_minutes_today=available_minutes_today,
            )
        )

    maintenance = _maintenance_estimate(config, observations)
    latest_observation = observations[-1]
    feedback = _feedback_for_latest_test(
        config=config,
        latest_test=latest_test,
        now=now,
        pump_timer_config=pump_timer_config,
    )

    applied_feedback_oz = feedback["dose_oz"] if feedback["active"] else 0.0
    unclamped_recommended = maintenance.limited_dose_oz_per_day + applied_feedback_oz
    recommended = max(0.0, unclamped_recommended)
    floor_limited = recommended != unclamped_recommended
    capped = recommended > config.max_daily_dose_oz
    if capped:
        recommended = config.max_daily_dose_oz

    applied_automatic = config.mode == ControlMode.AUTOMATIC
    effective_daily_dose_oz = (
        recommended
        if applied_automatic
        else chlorination_config.daily_dose_oz
    )
    warnings = _status_warnings(
        maintenance_rate_limited=maintenance.rate_limited,
        final_dose_capped=capped,
        final_dose_floor_limited=floor_limited,
    )
    status = FcDemandStatus(
        enabled=True,
        mode=config.mode,
        ready=True,
        reason="FC demand maintenance estimate ready",
        target_fc_ppm=config.target_fc_ppm,
        pool_volume_gal=config.pool_volume_gal,
        chlorine_strength_percent=config.chlorine_strength_percent,
        latest_fc_ppm=latest_test.free_chlorine if latest_test is not None else None,
        latest_fc_sampled_at=latest_test.sampled_at if latest_test is not None else None,
        latest_fc_age_hours=_latest_test_age_hours(latest_test, now),
        latest_fc_age_days=_latest_test_age_days(latest_test, now),
        previous_sampled_at=latest_observation.start_sampled_at,
        previous_fc_ppm=latest_observation.start_fc_ppm,
        current_sampled_at=latest_observation.end_sampled_at,
        current_fc_ppm=latest_observation.end_fc_ppm,
        elapsed_days=latest_observation.elapsed_days,
        demand_window_days=config.demand_window_days,
        max_demand_window_days=config.max_demand_window_days,
        max_observation_interval_days=config.max_observation_interval_days,
        demand_window_source="consecutive_observation",
        automated_chlorine_oz=latest_observation.automated_chlorine_oz,
        manual_hypo_oz=latest_observation.manual_sodium_hypochlorite_oz,
        added_fc_ppm=latest_observation.total_added_fc_ppm,
        consumed_fc_ppm=latest_observation.consumed_fc_ppm,
        daily_demand_ppm=latest_observation.demand_ppm_per_day,
        latest_observed_demand_ppm_per_day=latest_observation.demand_ppm_per_day,
        weighted_maintenance_demand_ppm_per_day=maintenance.weighted_demand_ppm_per_day,
        predicted_demand_ppm_per_day=maintenance.predicted_demand_ppm_per_day,
        observation_count=len(observations),
        recent_observation_count=config.recent_observation_count,
        effective_normalized_weights=maintenance.normalized_weights,
        observations_used=maintenance.observations_used,
        maintenance_dose_oz_per_day=maintenance.limited_dose_oz_per_day,
        unlimited_maintenance_dose_oz_per_day=maintenance.unlimited_dose_oz_per_day,
        previous_maintenance_dose_oz_per_day=(
            maintenance.previous_limited_dose_oz_per_day
        ),
        maintenance_rate_limited=maintenance.rate_limited,
        max_maintenance_change_percent=config.max_maintenance_change_percent,
        correction_fc_ppm=feedback["fc_ppm"],
        feedback_fc_ppm=feedback["fc_ppm"],
        feedback_dose_oz=feedback["dose_oz"],
        applied_feedback_dose_oz=applied_feedback_oz,
        feedback_active_today=feedback["active"],
        feedback_control_date=feedback["control_date"],
        fc_feedback_gain=config.fc_feedback_gain,
        catch_up_dose_oz_next_day=max(0.0, feedback["dose_oz"]),
        skip_days=0.0,
        next_adjustment_date=feedback["control_date"],
        recommended_daily_dose_oz=recommended,
        effective_daily_dose_oz=effective_daily_dose_oz,
        final_dose_capped=capped,
        final_dose_floor_limited=floor_limited,
        delay_eligible_minutes_today=0.0,
        available_dosing_minutes_today=available_minutes_today,
        applied_automatic=applied_automatic,
        confidence=_confidence_label(len(observations)),
        warning="; ".join(warnings) if warnings else None,
    )

    adjustment = None
    if applied_automatic:
        adjustment = ChlorinationPlanAdjustment(
            daily_dose_oz=recommended,
            source="fc_demand",
            reason=status.reason,
        )

    return FcDemandPlan(status=status, adjustment=adjustment)


def fc_demand_observations(
    *,
    config: FcDemandConfig,
    fc_tests: Sequence[FcTestPoint],
    automated_chlorine_deliveries: Sequence[ChlorineDeliveryPoint],
    sodium_hypochlorite_additions: Sequence[ChemicalAddition],
) -> tuple[FcDemandObservation, ...]:
    clean_tests = _clean_fc_tests(fc_tests)
    observations: list[FcDemandObservation] = []

    for previous, current in zip(clean_tests, clean_tests[1:]):
        elapsed_hours = (current.sampled_at - previous.sampled_at).total_seconds() / 3600.0
        if not _valid_observation_elapsed_hours(elapsed_hours, config=config):
            continue

        elapsed_days = elapsed_hours / 24.0
        automated_oz = _automated_oz_between(
            automated_chlorine_deliveries,
            previous.sampled_at,
            current.sampled_at,
        )
        automated_added_fc = fc_ppm_from_fl_oz(
            automated_oz,
            strength_percent=config.chlorine_strength_percent,
            pool_volume_gal=config.pool_volume_gal,
        )
        manual_additions = _manual_hypo_between(
            sodium_hypochlorite_additions,
            previous.sampled_at,
            current.sampled_at,
        )
        manual_hypo_oz = sum(addition.amount_fl_oz for addition in manual_additions)
        manual_added_fc = sum(
            fc_ppm_from_fl_oz(
                addition.amount_fl_oz,
                strength_percent=addition.strength_percent,
                pool_volume_gal=config.pool_volume_gal,
            )
            for addition in manual_additions
        )
        total_added_fc_ppm = automated_added_fc + manual_added_fc
        consumed_fc_ppm = (
            previous.free_chlorine
            + total_added_fc_ppm
            - current.free_chlorine
        )
        demand_ppm_per_day = max(0.0, consumed_fc_ppm / elapsed_days)
        observations.append(
            FcDemandObservation(
                start_sampled_at=previous.sampled_at,
                end_sampled_at=current.sampled_at,
                elapsed_days=elapsed_days,
                start_fc_ppm=previous.free_chlorine,
                end_fc_ppm=current.free_chlorine,
                automated_chlorine_oz=automated_oz,
                manual_sodium_hypochlorite_oz=manual_hypo_oz,
                total_added_fc_ppm=total_added_fc_ppm,
                consumed_fc_ppm=consumed_fc_ppm,
                demand_ppm_per_day=demand_ppm_per_day,
            )
        )

    return tuple(observations)


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


def _clean_fc_tests(fc_tests: Sequence[FcTestPoint]) -> tuple[FcTestPoint, ...]:
    return tuple(
        sorted(
            (
                FcTestPoint(
                    sampled_at=test.sampled_at,
                    free_chlorine=float(test.free_chlorine),
                )
                for test in fc_tests
                if test.free_chlorine >= 0
            ),
            key=lambda item: item.sampled_at,
        )
    )


def _valid_observation_elapsed_hours(
    elapsed_hours: float,
    *,
    config: FcDemandConfig,
) -> bool:
    if elapsed_hours <= 0:
        return False
    if elapsed_hours < config.minimum_test_interval_hours:
        return False
    elapsed_days = elapsed_hours / 24.0
    return elapsed_days <= config.max_observation_interval_days


def _maintenance_estimate(
    config: FcDemandConfig,
    observations: tuple[FcDemandObservation, ...],
) -> _MaintenanceEstimate:
    previous_limited_dose: float | None = None
    latest_estimate: _MaintenanceEstimate | None = None

    for index in range(1, len(observations) + 1):
        current_observations = observations[:index]
        weighted_demand, observations_used, normalized_weights = _weighted_demand(
            config,
            current_observations,
        )
        unlimited_dose = fl_oz_for_fc_ppm(
            weighted_demand,
            strength_percent=config.chlorine_strength_percent,
            pool_volume_gal=config.pool_volume_gal,
        )
        limited_dose, rate_limited = _rate_limited_maintenance_dose(
            unlimited_dose,
            previous_limited_dose,
            max_change_percent=config.max_maintenance_change_percent,
        )
        predicted_demand = _predicted_demand_before_latest_observation(
            config,
            current_observations,
        )
        latest_estimate = _MaintenanceEstimate(
            weighted_demand_ppm_per_day=weighted_demand,
            predicted_demand_ppm_per_day=predicted_demand,
            unlimited_dose_oz_per_day=unlimited_dose,
            limited_dose_oz_per_day=limited_dose,
            previous_limited_dose_oz_per_day=previous_limited_dose,
            rate_limited=rate_limited,
            observations_used=observations_used,
            normalized_weights=normalized_weights,
        )
        previous_limited_dose = limited_dose

    if latest_estimate is None:
        raise ValueError("at least one FC demand observation is required")
    return latest_estimate


def _weighted_demand(
    config: FcDemandConfig,
    observations: tuple[FcDemandObservation, ...],
) -> tuple[float, tuple[FcDemandObservation, ...], tuple[float, ...]]:
    if not observations:
        raise ValueError("at least one FC demand observation is required")

    used = tuple(
        reversed(observations[-config.recent_observation_count :])
    )
    raw_weights = config.observation_weights[: len(used)]
    weight_sum = sum(raw_weights)
    normalized = tuple(weight / weight_sum for weight in raw_weights)
    demand = sum(
        weight * observation.demand_ppm_per_day
        for observation, weight in zip(used, normalized, strict=True)
    )
    return demand, used, normalized


def _predicted_demand_before_latest_observation(
    config: FcDemandConfig,
    observations: tuple[FcDemandObservation, ...],
) -> float:
    if len(observations) < 2:
        return observations[-1].demand_ppm_per_day

    predicted, _, _ = _weighted_demand(config, observations[:-1])
    return predicted


def _rate_limited_maintenance_dose(
    requested_dose: float,
    previous_dose: float | None,
    *,
    max_change_percent: float,
) -> tuple[float, bool]:
    if previous_dose is None or previous_dose <= 0:
        return requested_dose, False
    if max_change_percent <= 0:
        return previous_dose, requested_dose != previous_dose

    change = max_change_percent / 100.0
    lower = previous_dose * (1.0 - change)
    upper = previous_dose * (1.0 + change)
    limited = min(max(requested_dose, lower), upper)
    return limited, limited != requested_dose


def _feedback_for_latest_test(
    *,
    config: FcDemandConfig,
    latest_test: FcTestPoint | None,
    now: datetime,
    pump_timer_config: PumpTimerConfig,
) -> dict[str, Any]:
    if latest_test is None:
        return {
            "fc_ppm": None,
            "dose_oz": 0.0,
            "active": False,
            "control_date": None,
        }

    timezone = ZoneInfo(pump_timer_config.timezone)
    local_today = now.astimezone(timezone).date()
    control_date = latest_test.sampled_at.astimezone(timezone).date() + timedelta(days=1)
    feedback_fc_ppm = config.fc_feedback_gain * (
        config.target_fc_ppm - latest_test.free_chlorine
    )
    feedback_dose_oz = _signed_fl_oz_for_fc_ppm(
        feedback_fc_ppm,
        strength_percent=config.chlorine_strength_percent,
        pool_volume_gal=config.pool_volume_gal,
    )
    return {
        "fc_ppm": feedback_fc_ppm,
        "dose_oz": feedback_dose_oz,
        "active": local_today == control_date,
        "control_date": control_date,
    }


def _signed_fl_oz_for_fc_ppm(
    fc_ppm: float,
    *,
    strength_percent: float,
    pool_volume_gal: float,
) -> float:
    if fc_ppm >= 0:
        return fl_oz_for_fc_ppm(
            fc_ppm,
            strength_percent=strength_percent,
            pool_volume_gal=pool_volume_gal,
        )
    return -fl_oz_for_fc_ppm(
        abs(fc_ppm),
        strength_percent=strength_percent,
        pool_volume_gal=pool_volume_gal,
    )


def _automated_oz_between(
    deliveries: Sequence[ChlorineDeliveryPoint],
    start: datetime,
    end: datetime,
) -> float:
    return sum(
        max(0.0, delivery.delivered_oz)
        for delivery in deliveries
        if start < delivery.observed_at <= end
    )


def _manual_hypo_between(
    additions: Sequence[ChemicalAddition],
    start: datetime,
    end: datetime,
) -> tuple[ChemicalAddition, ...]:
    return tuple(
        addition
        for addition in additions
        if addition.chemical == ChemicalType.SODIUM_HYPOCHLORITE
        and start < addition.added_at <= end
    )


def _legacy_delivery_points(
    clean_tests: tuple[FcTestPoint, ...],
    automated_chlorine_oz: float,
) -> tuple[ChlorineDeliveryPoint, ...]:
    if len(clean_tests) < 2 or automated_chlorine_oz <= 0:
        return ()
    return (
        ChlorineDeliveryPoint(
            observed_at=clean_tests[-1].sampled_at,
            delivered_oz=automated_chlorine_oz,
        ),
    )


def _base_status(
    config: FcDemandConfig,
    *,
    now: datetime,
    pump_timer_config: PumpTimerConfig,
    chlorination_config: ChlorinationConfig,
    ready: bool,
    reason: str,
    latest_test: FcTestPoint | None = None,
    observation_count: int = 0,
    available_minutes_today: float | None = None,
) -> FcDemandStatus:
    feedback = _feedback_for_latest_test(
        config=config,
        latest_test=latest_test,
        now=now,
        pump_timer_config=pump_timer_config,
    )
    return FcDemandStatus(
        enabled=config.enabled,
        mode=config.mode,
        ready=ready,
        reason=reason,
        target_fc_ppm=config.target_fc_ppm,
        pool_volume_gal=config.pool_volume_gal,
        chlorine_strength_percent=config.chlorine_strength_percent,
        latest_fc_ppm=latest_test.free_chlorine if latest_test is not None else None,
        latest_fc_sampled_at=latest_test.sampled_at if latest_test is not None else None,
        latest_fc_age_hours=_latest_test_age_hours(latest_test, now),
        latest_fc_age_days=_latest_test_age_days(latest_test, now),
        current_sampled_at=latest_test.sampled_at if latest_test is not None else None,
        current_fc_ppm=latest_test.free_chlorine if latest_test is not None else None,
        demand_window_days=config.demand_window_days,
        max_demand_window_days=config.max_demand_window_days,
        max_observation_interval_days=config.max_observation_interval_days,
        recent_observation_count=config.recent_observation_count,
        observation_count=observation_count,
        feedback_fc_ppm=feedback["fc_ppm"],
        correction_fc_ppm=feedback["fc_ppm"],
        feedback_dose_oz=feedback["dose_oz"],
        feedback_active_today=feedback["active"],
        feedback_control_date=feedback["control_date"],
        fc_feedback_gain=config.fc_feedback_gain,
        next_adjustment_date=feedback["control_date"],
        available_dosing_minutes_today=(
            available_minutes_today
            if available_minutes_today is not None
            else _available_minutes_for_day(
                pump_timer_config,
                now.astimezone(ZoneInfo(pump_timer_config.timezone)).date(),
                chlorination_config=chlorination_config,
            )
        ),
        effective_daily_dose_oz=chlorination_config.daily_dose_oz,
        confidence=_confidence_label(observation_count),
    )


def _latest_test_age_hours(
    latest_test: FcTestPoint | None,
    now: datetime,
) -> float | None:
    if latest_test is None:
        return None
    return max(0.0, (now - latest_test.sampled_at).total_seconds() / 3600.0)


def _latest_test_age_days(
    latest_test: FcTestPoint | None,
    now: datetime,
) -> float | None:
    age_hours = _latest_test_age_hours(latest_test, now)
    return None if age_hours is None else age_hours / 24.0


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


def _confidence_label(observation_count: int) -> str:
    if observation_count < 2:
        return "learning"
    if observation_count == 2:
        return "low"
    if observation_count <= 4:
        return "medium"
    return "high"


def _status_warnings(
    *,
    maintenance_rate_limited: bool,
    final_dose_capped: bool,
    final_dose_floor_limited: bool,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if maintenance_rate_limited:
        warnings.append("maintenance dose change limited")
    if final_dose_capped:
        warnings.append("recommended dose capped by fc_demand.max_daily_dose_oz")
    if final_dose_floor_limited:
        warnings.append("recommended dose clamped to zero")
    return tuple(warnings)


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


def _int_value(data: Mapping[str, Any], key: str, default: int) -> int:
    value = data.get(key, default)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    if isinstance(value, int):
        return value
    raise ValueError(f"{key} must be an integer")


def _float_tuple_value(
    data: Mapping[str, Any],
    key: str,
    default: tuple[float, ...],
) -> tuple[float, ...]:
    value = data.get(key, default)
    if not isinstance(value, list | tuple):
        raise ValueError(f"{key} must be a list")
    result: list[float] = []
    for item in value:
        if not isinstance(item, int | float):
            raise ValueError(f"{key} entries must be numbers")
        result.append(float(item))
    return tuple(result)


def _legacy_observation_interval_days(
    data: Mapping[str, Any],
    default: float,
) -> float:
    if "max_observation_interval_days" in data:
        return _float_value(data, "max_observation_interval_days", default)
    if "demand_window_days" in data:
        return _float_value(data, "demand_window_days", default)
    if "max_demand_window_days" in data:
        return _float_value(data, "max_demand_window_days", default)
    return default


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
