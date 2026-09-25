"""Tests for canonical status-driven notification behavior."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from poolctl.app import PoolControllerApp, build_app_from_mapping
from poolctl.config import MonitoringConfig
from poolctl.domain.models import Measurement, Quality, SensorId
from poolctl.services.notifications import (
    CPU_TEMPERATURE_HIGH_RULE,
    FREEZE_PROTECTION_ACTIVE_RULE,
    NotificationAlertSeverity,
    NotificationMessage,
    NotificationService,
    NotificationsConfig,
    evaluate_notification_alerts,
)
from poolctl.services.clock import SimulatedClock


NOW = datetime(2026, 5, 21, 12, tzinfo=timezone.utc)


def notification_config(**rule_overrides: dict[str, object]) -> NotificationsConfig:
    rules: dict[str, dict[str, object]] = {
        "raw_ph": {"enabled": True},
        "raw_orp": {"enabled": True},
        "filter_flow_loss_percent": {"enabled": True},
        "chlorine_tank_days_remaining": {"enabled": True},
        "freeze_temperature_unavailable": {"enabled": True},
    }
    rules.update(rule_overrides)
    return NotificationsConfig.from_mapping(
        {"notifications": {"enabled": True, "rules": rules}}
    )


def measurement(
    sensor_id: SensorId,
    value: float,
    unit: str,
    *,
    quality: Quality = Quality.GOOD,
) -> Measurement:
    return Measurement(
        sensor_id=sensor_id,
        observed_at=NOW,
        value=value,
        unit=unit,
        quality=quality,
    )


def test_notification_config_owns_rules_not_numeric_thresholds() -> None:
    config = notification_config()

    assert config.rules["raw_ph"].enabled is True
    assert config.rules["raw_ph"].caution_repeat_minutes == 1440.0
    payload = config.rules["raw_ph"].as_payload()
    assert set(payload) == {
        "enabled",
        "notify_caution",
        "notify_alarm",
        "caution_repeat_minutes",
        "alarm_repeat_minutes",
    }
    assert not {"caution_below", "alarm_below", "caution_above", "alarm_above"} & set(
        payload
    )


@pytest.mark.parametrize(
    ("value", "severity", "direction", "threshold"),
    [
        (7.2, NotificationAlertSeverity.CAUTION, "below", 7.2),
        (6.8, NotificationAlertSeverity.ALARM, "below", 6.8),
        (7.8, NotificationAlertSeverity.CAUTION, "above", 7.8),
        (8.2, NotificationAlertSeverity.ALARM, "above", 8.2),
    ],
)
def test_notifications_use_canonical_monitoring_boundaries(
    value: float,
    severity: NotificationAlertSeverity,
    direction: str,
    threshold: float,
) -> None:
    config = notification_config()
    alerts = evaluate_notification_alerts(
        config=config.rules,
        monitoring_config=MonitoringConfig.from_mapping({}),
        measurements={
            SensorId.RAW_PH: measurement(SensorId.RAW_PH, value, "pH"),
        },
        now=NOW,
        last_sent_at={},
    )

    alert = next(item for item in alerts if item.sensor_id is SensorId.RAW_PH)
    assert alert.severity is severity
    assert alert.direction == direction
    assert alert.threshold == threshold


def test_notification_severity_selection_and_cooldown_are_rule_owned() -> None:
    config = notification_config(
        raw_ph={
            "enabled": True,
            "notify_caution": False,
            "notify_alarm": True,
            "caution_repeat_minutes": 60,
            "alarm_repeat_minutes": 15,
        }
    )
    monitoring = MonitoringConfig.from_mapping({})
    caution = evaluate_notification_alerts(
        config=config.rules,
        monitoring_config=monitoring,
        measurements={
            SensorId.RAW_PH: measurement(SensorId.RAW_PH, 7.1, "pH"),
        },
        now=NOW,
        last_sent_at={},
    )
    assert not any(item.sensor_id is SensorId.RAW_PH for item in caution)

    alarm_measurements = {
        SensorId.RAW_PH: measurement(SensorId.RAW_PH, 6.7, "pH"),
    }
    first = evaluate_notification_alerts(
        config=config.rules,
        monitoring_config=monitoring,
        measurements=alarm_measurements,
        now=NOW,
        last_sent_at={},
    )
    ph_alert = next(item for item in first if item.sensor_id is SensorId.RAW_PH)
    assert ph_alert.repeat_minutes == 15.0
    suppressed = evaluate_notification_alerts(
        config=config.rules,
        monitoring_config=monitoring,
        measurements=alarm_measurements,
        now=NOW + timedelta(minutes=14),
        last_sent_at={ph_alert.throttle_key: NOW},
    )
    assert not any(item.sensor_id is SensorId.RAW_PH for item in suppressed)


def test_filter_and_tank_notifications_share_one_sided_monitoring_limits() -> None:
    config = notification_config()
    alerts = evaluate_notification_alerts(
        config=config.rules,
        monitoring_config=MonitoringConfig.from_mapping({}),
        measurements={
            SensorId.FILTER_FLOW_LOSS_PERCENT: measurement(
                SensorId.FILTER_FLOW_LOSS_PERCENT, 15.0, "percent"
            ),
            SensorId.CHLORINE_TANK_DAYS_REMAINING: Measurement(
                sensor_id=SensorId.CHLORINE_TANK_DAYS_REMAINING,
                observed_at=NOW,
                value=7.0,
                unit="days",
                metadata={"remaining_gal": 3.5},
            ),
        },
        now=NOW,
        last_sent_at={},
    )

    by_sensor = {alert.sensor_id: alert for alert in alerts}
    assert (
        by_sensor[SensorId.FILTER_FLOW_LOSS_PERCENT].severity
        is NotificationAlertSeverity.ALARM
    )
    assert (
        by_sensor[SensorId.CHLORINE_TANK_DAYS_REMAINING].severity
        is NotificationAlertSeverity.CAUTION
    )


def test_invalid_measurements_do_not_notify() -> None:
    config = notification_config()
    alerts = evaluate_notification_alerts(
        config=config.rules,
        monitoring_config=MonitoringConfig.from_mapping({}),
        measurements={
            SensorId.RAW_ORP: measurement(
                SensorId.RAW_ORP,
                100.0,
                "mV",
                quality=Quality.BAD,
            )
        },
        now=NOW,
        last_sent_at={},
    )
    assert not any(item.sensor_id is SensorId.RAW_ORP for item in alerts)


def test_freeze_fail_safe_remains_a_distinct_operational_condition() -> None:
    config = notification_config()
    alerts = evaluate_notification_alerts(
        config=config.rules,
        monitoring_config=MonitoringConfig.from_mapping({}),
        measurements={},
        now=NOW,
        last_sent_at={},
        freeze_status={"fail_safe": True},
    )
    freeze_alert = next(
        item for item in alerts if item.signal_key == "freeze_temperature_unavailable"
    )
    assert freeze_alert.severity is NotificationAlertSeverity.ALARM
    assert "fail-safe" in freeze_alert.message()


def test_notification_service_disabled_and_configured_delivery() -> None:
    disabled = NotificationService(NotificationsConfig.from_mapping({}))
    result = disabled.send(NotificationMessage(title="PoolScope", message="test"))
    assert result.sent is False
    assert result.error == "notifications disabled"

    requests: list[tuple[str, dict[str, str], float]] = []

    def post_form(
        url: str,
        data: dict[str, str],
        timeout_s: float,
    ) -> tuple[int, str]:
        requests.append((url, data, timeout_s))
        return 200, '{"status": 1, "request": "abc"}'

    configured = NotificationsConfig.from_mapping(
        {
            "notifications": {
                "enabled": True,
                "pushover": {
                    "app_token": "token",
                    "user_key": "user",
                    "priority": 1,
                },
            }
        }
    )
    sent = NotificationService(configured, post_form=post_form).send(
        NotificationMessage(title="PoolScope", message="test")
    )
    assert sent.sent is True
    assert requests[0][1]["token"] == "token"
    assert requests[0][1]["user"] == "user"


def notification_app(tmp_path: Path) -> tuple[PoolControllerApp, list[dict[str, str]]]:
    sent: list[dict[str, str]] = []
    config = {
        "runtime": {
            "driver_profile": "simulated",
            "enabled_actuators": [],
            "enabled_sensor_groups": [],
        },
        "logging": {"database_path": str(tmp_path / "notifications.sqlite3")},
        "notifications": {
            "enabled": True,
            "pushover": {"app_token": "token", "user_key": "user"},
            "rules": {
                FREEZE_PROTECTION_ACTIVE_RULE: {"enabled": True},
                CPU_TEMPERATURE_HIGH_RULE: {
                    "enabled": True,
                    "threshold_deg_c": 75,
                    "hysteresis_deg_c": 5,
                    "debounce_seconds": 60,
                },
            },
        },
    }
    clock = SimulatedClock(start_at=NOW)
    app = build_app_from_mapping(config, clock=clock)

    def post_form(
        _url: str,
        data: dict[str, str],
        _timeout_s: float,
    ) -> tuple[int, str]:
        sent.append(data)
        return 200, '{"status": 1}'

    object.__setattr__(
        app,
        "notification_service",
        NotificationService(app.notifications_config, post_form=post_form),
    )
    return app, sent


def test_freeze_activation_notifies_once_and_persists_edge_state(tmp_path: Path) -> None:
    app, sent = notification_app(tmp_path)
    assert isinstance(app.clock, SimulatedClock)
    service = app.notification_service
    assert service is not None
    inactive = {"active": False, "fail_safe": False}
    active = {
        "active": True,
        "active_temperature": 31.5,
        "active_unit": "degF",
        "active_source": "ph_temp",
        "active_measurement_at": NOW.isoformat(),
        "fail_safe": False,
    }

    assert app._freeze_activation_notification(  # noqa: SLF001
        service=service, freeze_status=inactive, now=NOW
    ) is None
    result = app._freeze_activation_notification(  # noqa: SLF001
        service=service, freeze_status=active, now=NOW
    )
    assert result is not None and result.sent is True
    assert "31.5 degF" in sent[-1]["message"]
    assert "ph_temp" in sent[-1]["message"]
    assert app._freeze_activation_notification(  # noqa: SLF001
        service=service, freeze_status=active, now=NOW + timedelta(minutes=1)
    ) is None

    restarted, restarted_sent = notification_app(tmp_path)
    restarted_service = restarted.notification_service
    assert restarted_service is not None
    assert restarted._freeze_activation_notification(  # noqa: SLF001
        service=restarted_service,
        freeze_status=active,
        now=NOW + timedelta(minutes=2),
    ) is None
    assert restarted_sent == []


def test_freeze_activation_on_first_observation_notifies_once(tmp_path: Path) -> None:
    app, sent = notification_app(tmp_path)
    service = app.notification_service
    assert service is not None
    active = {
        "active": True,
        "active_temperature": None,
        "active_unit": None,
        "active_source": None,
        "active_measurement_at": None,
        "fail_safe": True,
        "fail_safe_reason": "configured temperature sources unavailable",
    }

    result = app._freeze_activation_notification(  # noqa: SLF001
        service=service,
        freeze_status=active,
        now=NOW,
    )

    assert result is not None and result.sent is True
    assert "without a valid temperature" in sent[-1]["message"]
    assert "configured temperature sources unavailable" in sent[-1]["message"]

    restarted, restarted_sent = notification_app(tmp_path)
    restarted_service = restarted.notification_service
    assert restarted_service is not None
    assert restarted._freeze_activation_notification(  # noqa: SLF001
        service=restarted_service,
        freeze_status=active,
        now=NOW + timedelta(minutes=1),
    ) is None
    assert restarted_sent == []


@pytest.mark.asyncio
async def test_cpu_temperature_notification_uses_debounce_and_hysteresis(
    tmp_path: Path,
) -> None:
    app, sent = notification_app(tmp_path)
    assert isinstance(app.clock, SimulatedClock)
    service = app.notification_service
    assert service is not None

    def cpu(value: float) -> Measurement:
        return Measurement(
            sensor_id=SensorId.CPU_TEMP,
            observed_at=app.clock.now(),
            value=value,
            unit="degC",
            quality=Quality.GOOD,
        )

    assert app._cpu_temperature_notification(  # noqa: SLF001
        service=service, measurement=cpu(76), now=app.clock.now()
    ) is None
    await app.clock.advance(59)
    assert app._cpu_temperature_notification(  # noqa: SLF001
        service=service, measurement=cpu(76), now=app.clock.now()
    ) is None
    await app.clock.advance(1)
    result = app._cpu_temperature_notification(  # noqa: SLF001
        service=service, measurement=cpu(76), now=app.clock.now()
    )
    assert result is not None and result.sent is True
    assert len(sent) == 1
    assert "76.0 degC" in sent[0]["message"]

    await app.clock.advance(1)
    assert app._cpu_temperature_notification(  # noqa: SLF001
        service=service, measurement=cpu(72), now=app.clock.now()
    ) is None
    assert app.notification_runtime_state[CPU_TEMPERATURE_HIGH_RULE]["active"] is True
    await app.clock.advance(1)
    assert app._cpu_temperature_notification(  # noqa: SLF001
        service=service, measurement=cpu(70), now=app.clock.now()
    ) is None
    assert app.notification_runtime_state[CPU_TEMPERATURE_HIGH_RULE]["active"] is False


def test_pump_off_chemical_reading_is_not_a_notification_prerequisite(
    tmp_path: Path,
) -> None:
    config = {
        "runtime": {
            "driver_profile": "simulated",
            "enabled_actuators": ["pump_motor"],
            "enabled_sensor_groups": ["chemistry_loop"],
        },
        "logging": {"database_path": str(tmp_path / "pump-off.sqlite3")},
        "acquisition": {
            "groups": {
                "chemistry_loop": {
                    "sensor_ids": ["raw_ph", "raw_orp"],
                    "read_interval_s": 1,
                    "log_interval_s": 1,
                    "requires_pump_flow": True,
                    "min_pump_on_seconds": 60,
                }
            }
        },
    }
    app = build_app_from_mapping(config, clock=SimulatedClock(start_at=NOW))
    measurements = app._notification_alert_measurements(  # noqa: SLF001
        latest_measurements={
            SensorId.RAW_PH: measurement(SensorId.RAW_PH, 6.0, "pH"),
            SensorId.RAW_ORP: measurement(SensorId.RAW_ORP, 100, "mV"),
        },
        control_measurements=(),
        observed_at=NOW,
        daily_dose_oz=32,
    )

    assert SensorId.RAW_PH not in measurements
    assert SensorId.RAW_ORP not in measurements


def test_failed_chemical_read_does_not_reuse_retained_good_value(tmp_path: Path) -> None:
    app, _sent = notification_app(tmp_path)
    retained = measurement(SensorId.RAW_PH, 6.0, "pH")

    measurements = app._notification_alert_measurements(  # noqa: SLF001
        latest_measurements={SensorId.RAW_PH: retained},
        control_measurements=(),
        observed_at=NOW,
        daily_dose_oz=32,
        failed_sensor_ids=frozenset({SensorId.RAW_PH}),
    )

    assert SensorId.RAW_PH not in measurements
