"""
Tests for notification configuration and dispatch behavior.

Notifications are currently used for alerting integrations such as Pushover,
and tests keep disabled/configured cases predictable.
"""

from __future__ import annotations

from collections.abc import Mapping

from poolctl.services.notifications import (
    NotificationMessage,
    NotificationService,
    NotificationsConfig,
)


def test_notifications_config_defaults_to_disabled_pushover() -> None:
    config = NotificationsConfig.from_mapping({})

    assert config.enabled is False
    assert config.provider.value == "pushover"
    assert config.pushover.app_token_env == "PUSHOVER_APP_TOKEN"
    assert config.pushover.user_key_env == "PUSHOVER_USER_KEY"


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
