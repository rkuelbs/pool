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
    assert config.pushover.app_token_env == "PUSHOVER_APP_TOKEN"
    assert config.pushover.user_key_env == "PUSHOVER_USER_KEY"
    assert config.alerts.ph.warning_above == 8.2
    assert config.alerts.orp.caution_below == 600.0


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
