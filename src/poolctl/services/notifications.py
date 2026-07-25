from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NotificationProvider(str, Enum):
    PUSHOVER = "pushover"


@dataclass(frozen=True)
class PushoverConfig:
    app_token_env: str = "PUSHOVER_APP_TOKEN"
    user_key_env: str = "PUSHOVER_USER_KEY"
    app_token: str | None = None
    user_key: str | None = None
    api_url: str = "https://api.pushover.net/1/messages.json"
    timeout_s: float = 5.0
    priority: int = 0
    sound: str | None = None

    def __post_init__(self) -> None:
        if not self.app_token_env:
            raise ValueError("notifications.pushover.app_token_env must not be blank")
        if not self.user_key_env:
            raise ValueError("notifications.pushover.user_key_env must not be blank")
        if not self.api_url:
            raise ValueError("notifications.pushover.api_url must not be blank")
        if self.timeout_s <= 0:
            raise ValueError("notifications.pushover.timeout_s must be > 0")
        if not -2 <= self.priority <= 2:
            raise ValueError("notifications.pushover.priority must be between -2 and 2")

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> PushoverConfig:
        return cls(
            app_token_env=_string_value(data, "app_token_env", cls.app_token_env),
            user_key_env=_string_value(data, "user_key_env", cls.user_key_env),
            app_token=_optional_string_value(data, "app_token"),
            user_key=_optional_string_value(data, "user_key"),
            api_url=_string_value(data, "api_url", cls.api_url),
            timeout_s=_float_value(data, "timeout_s", cls.timeout_s),
            priority=_int_value(data, "priority", cls.priority),
            sound=_optional_string_value(data, "sound"),
        )

    def credentials_from_environment(self) -> tuple[str | None, str | None]:
        token = self.app_token or os.environ.get(self.app_token_env)
        user_key = self.user_key or os.environ.get(self.user_key_env)
        return token, user_key

    def as_payload(self) -> dict[str, Any]:
        token, user_key = self.credentials_from_environment()
        return {
            "app_token_env": self.app_token_env,
            "user_key_env": self.user_key_env,
            "api_url": self.api_url,
            "timeout_s": self.timeout_s,
            "priority": self.priority,
            "sound": self.sound,
            "configured": bool(token and user_key),
        }


@dataclass(frozen=True)
class NotificationsConfig:
    enabled: bool = False
    provider: NotificationProvider = NotificationProvider.PUSHOVER
    default_title: str = "poolctl"
    pushover: PushoverConfig = field(default_factory=PushoverConfig)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> NotificationsConfig:
        notifications_data = _mapping_value(data, "notifications", default={})
        pushover_data = _mapping_value(notifications_data, "pushover", default={})
        return cls(
            enabled=_bool_value(notifications_data, "enabled", cls.enabled),
            provider=_provider_value(
                notifications_data,
                "provider",
                cls.provider,
            ),
            default_title=_string_value(
                notifications_data,
                "default_title",
                cls.default_title,
            ),
            pushover=PushoverConfig.from_mapping(pushover_data),
        )


@dataclass(frozen=True)
class NotificationMessage:
    title: str
    message: str
    priority: int | None = None


@dataclass(frozen=True)
class NotificationResult:
    sent: bool
    provider: NotificationProvider
    status_code: int | None = None
    error: str | None = None
    response: dict[str, Any] | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "sent": self.sent,
            "provider": self.provider.value,
            "status_code": self.status_code,
            "error": self.error,
            "response": self.response,
        }


PostForm = Callable[[str, Mapping[str, str], float], tuple[int, str]]


class NotificationService:
    """
    Sends outbound notifications through the configured provider.
    """

    def __init__(
        self,
        config: NotificationsConfig,
        *,
        post_form: PostForm | None = None,
    ) -> None:
        self.config = config
        self._post_form = post_form if post_form is not None else _default_post_form

    def status_payload(self) -> dict[str, Any]:
        payload = {
            "enabled": self.config.enabled,
            "provider": self.config.provider.value,
            "default_title": self.config.default_title,
        }
        if self.config.provider == NotificationProvider.PUSHOVER:
            payload["pushover"] = self.config.pushover.as_payload()
        return payload

    def send(self, message: NotificationMessage) -> NotificationResult:
        if not self.config.enabled:
            return NotificationResult(
                sent=False,
                provider=self.config.provider,
                error="notifications disabled",
            )
        if self.config.provider == NotificationProvider.PUSHOVER:
            return self._send_pushover(message)
        return NotificationResult(
            sent=False,
            provider=self.config.provider,
            error=f"unsupported notification provider: {self.config.provider.value}",
        )

    def _send_pushover(self, message: NotificationMessage) -> NotificationResult:
        token, user_key = self.config.pushover.credentials_from_environment()
        if not token or not user_key:
            return NotificationResult(
                sent=False,
                provider=NotificationProvider.PUSHOVER,
                error=(
                    "Pushover credentials are not configured; set "
                    f"{self.config.pushover.app_token_env} and "
                    f"{self.config.pushover.user_key_env}"
                ),
            )

        priority = (
            self.config.pushover.priority
            if message.priority is None
            else message.priority
        )
        payload = {
            "token": token,
            "user": user_key,
            "title": message.title,
            "message": message.message,
            "priority": str(priority),
        }
        if self.config.pushover.sound:
            payload["sound"] = self.config.pushover.sound

        try:
            status_code, body = self._post_form(
                self.config.pushover.api_url,
                payload,
                self.config.pushover.timeout_s,
            )
        except Exception as error:
            return NotificationResult(
                sent=False,
                provider=NotificationProvider.PUSHOVER,
                error=str(error),
            )

        parsed = _json_body(body)
        pushover_status = parsed.get("status") if parsed is not None else None
        sent = 200 <= status_code < 300 and pushover_status == 1
        error = None
        if not sent:
            errors = parsed.get("errors") if parsed is not None else None
            error = ", ".join(str(item) for item in errors) if isinstance(errors, list) else body

        return NotificationResult(
            sent=sent,
            provider=NotificationProvider.PUSHOVER,
            status_code=status_code,
            error=error,
            response=parsed,
        )


def _default_post_form(
    url: str,
    data: Mapping[str, str],
    timeout_s: float,
) -> tuple[int, str]:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=encoded,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            body = response.read().decode("utf-8", errors="replace")
            return int(response.status), body
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        return int(error.code), body


def _json_body(body: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


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


def _string_value(data: Mapping[str, Any], key: str, default: str) -> str:
    value = data.get(key, default)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ValueError(f"{key} must be a non-empty string")


def _optional_string_value(data: Mapping[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    raise ValueError(f"{key} must be a string")


def _float_value(data: Mapping[str, Any], key: str, default: float) -> float:
    value = data.get(key, default)
    if isinstance(value, int | float):
        return float(value)
    raise ValueError(f"{key} must be a number")


def _int_value(data: Mapping[str, Any], key: str, default: int) -> int:
    value = data.get(key, default)
    if isinstance(value, int):
        return value
    raise ValueError(f"{key} must be an integer")


def _provider_value(
    data: Mapping[str, Any],
    key: str,
    default: NotificationProvider,
) -> NotificationProvider:
    value = data.get(key, default.value)
    if isinstance(value, NotificationProvider):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return NotificationProvider(value)
