"""
Tests for notification configuration and dispatch behavior.

Notifications are currently used for alerting integrations such as Pushover,
and tests keep disabled/configured cases predictable.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone

from poolctl.domain.models import Measurement, Quality, SensorId
from poolctl.services.notifications import (
    NotificationMessage,
    NotificationService,
    NotificationsConfig,
    evaluate_notification_alerts,
)


def test_notifications_config_defaults_to_disabled_pushover() -> None:
    config = NotificationsConfig.from_mapping({})

    assert config.enabled is False
    assert config.provider.value == "pushover"
    assert config.default_title == "PoolScope"
    assert config.pushover.app_token_env == "PUSHOVER_APP_TOKEN"
    assert config.pushover.user_key_env == "PUSHOVER_USER_KEY"
    assert config.alerts.chlorine_tank.caution_below == 7.0
    assert config.alerts.chlorine_tank.warning_below == 3.0
    assert config.alerts.ph.warning_above == 8.2
    assert config.alerts.orp.caution_below == 600.0
    assert config.alerts.filter_flow_loss.enabled is False
    assert config.alerts.filter_flow_loss.warning_above == 15.0
    assert config.alerts.filter_flow_loss.warning_repeat_minutes == 1440.0
    assert config.alerts.freeze_temperature_unavailable.enabled is True
    assert config.alerts.freeze_temperature_unavailable.warning_repeat_minutes == 240.0


def test_pushover_config_normalizes_credentials_entered_as_env_names() -> None:
    app_token = "aafss2se7zy9xgfxwq4b44mpnbyezq"
    user_key = "uuckxcf4pw5r71tn6x1hdbafo6279m"

    config = NotificationsConfig.from_mapping(
        {
            "notifications": {
                "enabled": True,
                "pushover": {
                    "app_token_env": app_token,
                    "user_key_env": user_key,
                },
            }
        }
    )

    payload = config.pushover.as_payload()
    assert config.pushover.app_token == app_token
    assert config.pushover.user_key == user_key
    assert config.pushover.app_token_env == "PUSHOVER_APP_TOKEN"
    assert config.pushover.user_key_env == "PUSHOVER_USER_KEY"
    assert payload["configured"] is True
    assert app_token not in str(payload)
    assert user_key not in str(payload)


def test_pushover_send_reports_missing_credentials(monkeypatch) -> None:
    monkeypatch.delenv("PUSHOVER_APP_TOKEN", raising=False)
    monkeypatch.delenv("PUSHOVER_USER_KEY", raising=False)
    config = NotificationsConfig.from_mapping(
        {
            "notifications": {
                "enabled": True,
                "provider": "pushover",
            }
        }
    )
    service = NotificationService(config)

    result = service.send(NotificationMessage(title="poolctl", message="test"))

    assert result.sent is False
    assert "Pushover credentials" in str(result.error)


def test_pushover_send_uses_environment_credentials(monkeypatch) -> None:
    posted: list[tuple[str, Mapping[str, str], float]] = []

    def fake_post_form(
        url: str,
        data: Mapping[str, str],
        timeout_s: float,
    ) -> tuple[int, str]:
        posted.append((url, dict(data), timeout_s))
        return 200, '{"status":1,"request":"abc"}'

    monkeypatch.setenv("PUSHOVER_APP_TOKEN", "token123")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "user456")
    config = NotificationsConfig.from_mapping(
        {
            "notifications": {
                "enabled": True,
                "default_title": "poolctl test",
                "pushover": {
                    "timeout_s": 3.0,
                    "priority": 1,
                    "sound": "pushover",
                },
            }
        }
    )
    service = NotificationService(config, post_form=fake_post_form)

    result = service.send(NotificationMessage(title="title", message="hello"))

    assert result.sent is True
    assert posted
    assert posted[0][0] == "https://api.pushover.net/1/messages.json"
    assert posted[0][1]["token"] == "token123"
    assert posted[0][1]["user"] == "user456"
    assert posted[0][1]["message"] == "hello"
    assert posted[0][1]["priority"] == "1"
    assert posted[0][1]["sound"] == "pushover"
    assert posted[0][2] == 3.0


def test_pushover_send_uses_direct_credentials() -> None:
    posted: list[tuple[str, Mapping[str, str], float]] = []

    def fake_post_form(
        url: str,
        data: Mapping[str, str],
        timeout_s: float,
    ) -> tuple[int, str]:
        posted.append((url, dict(data), timeout_s))
        return 200, '{"status":1,"request":"abc"}'

    config = NotificationsConfig.from_mapping(
        {
            "notifications": {
                "enabled": True,
                "pushover": {
                    "app_token": "direct-token",
                    "user_key": "direct-user",
                },
            }
        }
    )
    service = NotificationService(config, post_form=fake_post_form)

    result = service.send(NotificationMessage(title="title", message="hello"))

    assert result.sent is True
    assert posted[0][1]["token"] == "direct-token"
    assert posted[0][1]["user"] == "direct-user"


def test_pushover_status_reports_configured_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("PUSHOVER_APP_TOKEN", "token123")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "user456")
    config = NotificationsConfig.from_mapping(
        {
            "notifications": {
                "enabled": True,
                "provider": "pushover",
            }
        }
    )

    status = NotificationService(config).status_payload()

    assert status["enabled"] is True
    assert status["pushover"]["configured"] is True


def test_notification_service_does_not_leak_environment_values(monkeypatch) -> None:
    monkeypatch.setenv("PUSHOVER_APP_TOKEN", "secret-token")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "secret-user")
    status = NotificationService(
        NotificationsConfig.from_mapping({"notifications": {"enabled": True}})
    ).status_payload()

    rendered = str(status)
    assert "secret-token" not in rendered
    assert "secret-user" not in rendered


def test_notification_alert_evaluator_applies_warning_and_repeat_throttle() -> None:
    config = NotificationsConfig.from_mapping(
        {
            "notifications": {
                "alerts": {
                    "ph": {
                        "enabled": True,
                        "caution_below": 7.2,
                        "caution_above": 7.8,
                        "warning_below": 6.8,
                        "warning_above": 8.2,
                        "caution_repeat_minutes": 60.0,
                        "warning_repeat_minutes": 15.0,
                    }
                }
            }
        }
    )
    now = datetime(2026, 5, 21, 12, tzinfo=timezone.utc)
    measurements = {
        SensorId.RAW_PH: Measurement(
            sensor_id=SensorId.RAW_PH,
            observed_at=now,
            value=8.35,
            unit="pH",
            quality=Quality.GOOD,
        )
    }

    first = evaluate_notification_alerts(
        config=config.alerts,
        measurements=measurements,
        now=now,
        last_sent_at={},
    )
    throttled = evaluate_notification_alerts(
        config=config.alerts,
        measurements=measurements,
        now=now + timedelta(minutes=10),
        last_sent_at={"ph:warning": now},
    )
    repeated = evaluate_notification_alerts(
        config=config.alerts,
        measurements=measurements,
        now=now + timedelta(minutes=16),
        last_sent_at={"ph:warning": now},
    )

    assert len(first) == 1
    assert first[0].severity.value == "warning"
    assert first[0].direction == "above"
    assert first[0].throttle_key == "ph:warning"
    assert throttled == ()
    assert len(repeated) == 1


def test_notification_alert_evaluator_uses_tank_days_remaining() -> None:
    config = NotificationsConfig.from_mapping(
        {
            "notifications": {
                "alerts": {
                    "chlorine_tank": {
                        "enabled": True,
                        "caution_below": 7.0,
                        "warning_below": 3.0,
                        "caution_repeat_minutes": 60.0,
                        "warning_repeat_minutes": 15.0,
                    }
                }
            }
        }
    )
    now = datetime(2026, 5, 21, 12, tzinfo=timezone.utc)
    measurements = {
        SensorId.CHLORINE_TANK_DAYS_REMAINING: Measurement(
            sensor_id=SensorId.CHLORINE_TANK_DAYS_REMAINING,
            observed_at=now,
            value=2.5,
            unit="days",
            quality=Quality.GOOD,
            metadata={"remaining_gal": 1.25},
        ),
        SensorId.CHLORINE_TANK_LEVEL_GAL: Measurement(
            sensor_id=SensorId.CHLORINE_TANK_LEVEL_GAL,
            observed_at=now,
            value=8.0,
            unit="gal",
            quality=Quality.GOOD,
        ),
    }

    alerts = evaluate_notification_alerts(
        config=config.alerts,
        measurements=measurements,
        now=now,
        last_sent_at={},
    )

    assert len(alerts) == 1
    assert alerts[0].sensor_id == SensorId.CHLORINE_TANK_DAYS_REMAINING
    assert alerts[0].severity.value == "warning"
    assert alerts[0].threshold == 3.0
    assert alerts[0].message() == (
        "Chlorine tank supply warning: 2.5 days remaining (1.25 gal) "
        "is below the warning threshold (3.0 days)"
    )


def test_notification_alert_evaluator_uses_filter_flow_loss_threshold() -> None:
    config = NotificationsConfig.from_mapping(
        {
            "notifications": {
                "alerts": {
                    "filter_flow_loss": {
                        "enabled": True,
                        "warning_above": 15.0,
                        "warning_repeat_minutes": 1440.0,
                    }
                }
            }
        }
    )
    now = datetime(2026, 5, 21, 12, tzinfo=timezone.utc)
    measurements = {
        SensorId.FILTER_FLOW_LOSS_PERCENT: Measurement(
            sensor_id=SensorId.FILTER_FLOW_LOSS_PERCENT,
            observed_at=now,
            value=15.8,
            unit="percent",
            quality=Quality.GOOD,
            metadata={"test_age_seconds": 2 * 86400.0},
        )
    }

    first = evaluate_notification_alerts(
        config=config.alerts,
        measurements=measurements,
        now=now,
        last_sent_at={},
    )
    throttled = evaluate_notification_alerts(
        config=config.alerts,
        measurements=measurements,
        now=now + timedelta(minutes=60),
        last_sent_at={"filter_flow_loss:warning": now},
    )

    assert len(first) == 1
    assert first[0].sensor_id == SensorId.FILTER_FLOW_LOSS_PERCENT
    assert first[0].throttle_key == "filter_flow_loss:warning"
    assert first[0].message() == (
        "Clean filter soon: standardized flow loss is 15.8% "
        "(last hydraulic test: 2 days ago)."
    )
    assert throttled == ()


def test_filter_alert_repeats_for_old_latched_result_and_clean_retest_clears() -> None:
    config = NotificationsConfig.from_mapping(
        {
            "notifications": {
                "alerts": {
                    "filter_flow_loss": {
                        "enabled": True,
                        "warning_above": 15.0,
                        "warning_repeat_minutes": 60.0,
                    }
                }
            }
        }
    )
    now = datetime(2026, 5, 21, 12, tzinfo=timezone.utc)
    old_result = Measurement(
        sensor_id=SensorId.FILTER_FLOW_LOSS_PERCENT,
        observed_at=now - timedelta(days=5),
        value=16.2,
        unit="percent",
        quality=Quality.GOOD,
        metadata={"test_age_seconds": 5 * 86400.0},
    )

    repeated = evaluate_notification_alerts(
        config=config.alerts,
        measurements={SensorId.FILTER_FLOW_LOSS_PERCENT: old_result},
        now=now,
        last_sent_at={"filter_flow_loss:warning": now - timedelta(minutes=61)},
    )
    clean = evaluate_notification_alerts(
        config=config.alerts,
        measurements={
            SensorId.FILTER_FLOW_LOSS_PERCENT: old_result.model_copy(
                update={"observed_at": now, "value": 8.0, "metadata": {"test_age_seconds": 0.0}}
            )
        },
        now=now,
        last_sent_at={},
    )

    assert len(repeated) == 1
    assert "5 days ago" in repeated[0].message()
    assert clean == ()


def test_freeze_temperature_loss_notification_is_throttled() -> None:
    config = NotificationsConfig.from_mapping({})
    now = datetime(2026, 5, 21, 12, tzinfo=timezone.utc)
    freeze_status = {"fail_safe": True}

    first = evaluate_notification_alerts(
        config=config.alerts,
        measurements={},
        now=now,
        last_sent_at={},
        freeze_status=freeze_status,
    )
    throttled = evaluate_notification_alerts(
        config=config.alerts,
        measurements={},
        now=now + timedelta(minutes=30),
        last_sent_at={"freeze_temperature_unavailable:warning": now},
        freeze_status=freeze_status,
    )
    repeated = evaluate_notification_alerts(
        config=config.alerts,
        measurements={},
        now=now + timedelta(minutes=241),
        last_sent_at={"freeze_temperature_unavailable:warning": now},
        freeze_status=freeze_status,
    )

    assert len(first) == 1
    assert first[0].message() == (
        "Freeze protection temperature unavailable; using fail-safe freeze protection."
    )
    assert throttled == ()
    assert len(repeated) == 1


def test_notification_alert_evaluator_throttles_ph_caution_across_directions() -> None:
    config = NotificationsConfig.from_mapping(
        {
            "notifications": {
                "alerts": {
                    "ph": {
                        "enabled": True,
                        "caution_below": 7.2,
                        "caution_above": 7.8,
                        "warning_below": 6.8,
                        "warning_above": 8.2,
                        "caution_repeat_minutes": 60.0,
                        "warning_repeat_minutes": 15.0,
                    }
                }
            }
        }
    )
    now = datetime(2026, 5, 21, 12, tzinfo=timezone.utc)
    high_caution = {
        SensorId.RAW_PH: Measurement(
            sensor_id=SensorId.RAW_PH,
            observed_at=now,
            value=7.9,
            unit="pH",
            quality=Quality.GOOD,
        )
    }
    low_caution = {
        SensorId.RAW_PH: Measurement(
            sensor_id=SensorId.RAW_PH,
            observed_at=now + timedelta(minutes=10),
            value=7.1,
            unit="pH",
            quality=Quality.GOOD,
        )
    }

    first = evaluate_notification_alerts(
        config=config.alerts,
        measurements=high_caution,
        now=now,
        last_sent_at={},
    )
    oscillation = evaluate_notification_alerts(
        config=config.alerts,
        measurements=low_caution,
        now=now + timedelta(minutes=10),
        last_sent_at={"ph:caution": now},
    )

    assert len(first) == 1
    assert first[0].direction == "above"
    assert first[0].throttle_key == "ph:caution"
    assert oscillation == ()
