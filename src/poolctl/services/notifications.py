"""
Notification service for alerts such as pH or safety warnings.

The first implementation targets Pushover, but the rest of the controller only
uses NotificationMessage objects so other notification providers can be added
without changing safety or chemistry logic.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from poolctl.domain.models import Measurement, Quality, SensorId


class NotificationProvider(str, Enum):
    PUSHOVER = "pushover"


class NotificationAlertSeverity(str, Enum):
    CAUTION = "caution"
    WARNING = "warning"


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
        app_token_env = _string_value(data, "app_token_env", cls.app_token_env)
        user_key_env = _string_value(data, "user_key_env", cls.user_key_env)
        app_token = _optional_string_value(data, "app_token")
        user_key = _optional_string_value(data, "user_key")
        if _looks_like_pushover_secret(app_token_env):
            app_token = app_token or app_token_env
            app_token_env = cls.app_token_env
        if _looks_like_pushover_secret(user_key_env):
            user_key = user_key or user_key_env
            user_key_env = cls.user_key_env
        return cls(
            app_token_env=app_token_env,
            user_key_env=user_key_env,
            app_token=app_token,
            user_key=user_key,
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
            "app_token_configured": bool(self.app_token),
            "user_key_configured": bool(self.user_key),
        }


@dataclass(frozen=True)
class SignalNotificationConfig:
    enabled: bool = False
    caution_below: float | None = None
    caution_above: float | None = None
    warning_below: float | None = None
    warning_above: float | None = None
    caution_repeat_minutes: float = 1440.0
    warning_repeat_minutes: float = 240.0

    def __post_init__(self) -> None:
        if self.caution_repeat_minutes <= 0:
            raise ValueError("caution_repeat_minutes must be > 0")
        if self.warning_repeat_minutes <= 0:
            raise ValueError("warning_repeat_minutes must be > 0")
        if (
            self.caution_below is not None
            and self.warning_below is not None
            and self.warning_below > self.caution_below
        ):
            raise ValueError("warning_below must be <= caution_below")
        if (
            self.caution_above is not None
            and self.warning_above is not None
            and self.warning_above < self.caution_above
        ):
            raise ValueError("warning_above must be >= caution_above")
        if self.enabled and not any(
            threshold is not None
            for threshold in (
                self.caution_below,
                self.caution_above,
                self.warning_below,
                self.warning_above,
            )
        ):
            raise ValueError("enabled notification alert must define at least one threshold")

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any],
        *,
        default: SignalNotificationConfig,
    ) -> SignalNotificationConfig:
        return cls(
            enabled=_bool_value(data, "enabled", default.enabled),
            caution_below=_optional_float_value(data, "caution_below", default.caution_below),
            caution_above=_optional_float_value(data, "caution_above", default.caution_above),
            warning_below=_optional_float_value(data, "warning_below", default.warning_below),
            warning_above=_optional_float_value(data, "warning_above", default.warning_above),
            caution_repeat_minutes=_float_value(
                data,
                "caution_repeat_minutes",
                default.caution_repeat_minutes,
            ),
            warning_repeat_minutes=_float_value(
                data,
                "warning_repeat_minutes",
                default.warning_repeat_minutes,
            ),
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "caution_below": self.caution_below,
            "caution_above": self.caution_above,
            "warning_below": self.warning_below,
            "warning_above": self.warning_above,
            "caution_repeat_minutes": self.caution_repeat_minutes,
            "warning_repeat_minutes": self.warning_repeat_minutes,
        }


@dataclass(frozen=True)
class NotificationAlertConfig:
    chlorine_tank: SignalNotificationConfig = field(
        default_factory=lambda: SignalNotificationConfig(
            caution_below=7.0,
            warning_below=3.0,
        )
    )
    ph: SignalNotificationConfig = field(
        default_factory=lambda: SignalNotificationConfig(
            caution_below=7.2,
            caution_above=7.8,
            warning_below=6.8,
            warning_above=8.2,
        )
    )
    orp: SignalNotificationConfig = field(
        default_factory=lambda: SignalNotificationConfig(
            caution_below=600.0,
            caution_above=800.0,
            warning_below=400.0,
            warning_above=900.0,
        )
    )

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> NotificationAlertConfig:
        defaults = cls()
        return cls(
            chlorine_tank=SignalNotificationConfig.from_mapping(
                _mapping_value(data, "chlorine_tank", default={}),
                default=defaults.chlorine_tank,
            ),
            ph=SignalNotificationConfig.from_mapping(
                _mapping_value(data, "ph", default={}),
                default=defaults.ph,
            ),
            orp=SignalNotificationConfig.from_mapping(
                _mapping_value(data, "orp", default={}),
                default=defaults.orp,
            ),
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "chlorine_tank": self.chlorine_tank.as_payload(),
            "ph": self.ph.as_payload(),
            "orp": self.orp.as_payload(),
        }


@dataclass(frozen=True)
class NotificationsConfig:
    enabled: bool = False
    provider: NotificationProvider = NotificationProvider.PUSHOVER
    default_title: str = "poolctl"
    pushover: PushoverConfig = field(default_factory=PushoverConfig)
    alerts: NotificationAlertConfig = field(default_factory=NotificationAlertConfig)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> NotificationsConfig:
        notifications_data = _mapping_value(data, "notifications", default={})
        pushover_data = _mapping_value(notifications_data, "pushover", default={})
        alerts_data = _mapping_value(notifications_data, "alerts", default={})
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
            alerts=NotificationAlertConfig.from_mapping(alerts_data),
        )


@dataclass(frozen=True)
class NotificationMessage:
    title: str
    message: str
    priority: int | None = None


@dataclass(frozen=True)
class NotificationAlert:
    sensor_id: SensorId
    signal_key: str
    label: str
    severity: NotificationAlertSeverity
    direction: str
    value: float
    unit: str
    threshold: float
    repeat_minutes: float
    context: Mapping[str, Any] = field(default_factory=dict)

    @property
    def throttle_key(self) -> str:
        return f"{self.signal_key}:{self.severity.value}"

    def message(self) -> str:
        value = _display_value(self.value, self.unit)
        threshold = _display_value(self.threshold, self.unit)
        relation = "below" if self.direction == "below" else "above"
        if self.signal_key == "chlorine_tank" and self.unit == "days":
            gallons = _optional_float(self.context.get("remaining_gal"))
            gallons_text = (
                f" ({_display_value(gallons, 'gal')})"
                if gallons is not None
                else ""
            )
            return (
                f"{self.label} {self.severity.value}: {value} remaining"
                f"{gallons_text} is {relation} the {self.severity.value} "
                f"threshold ({threshold})"
            )
        return (
            f"{self.label} {self.severity.value}: {value} is {relation} "
            f"the {self.severity.value} threshold ({threshold})"
        )


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
            "alerts": self.config.alerts.as_payload(),
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
        except Exception as exc:
            return NotificationResult(
                sent=False,
                provider=NotificationProvider.PUSHOVER,
                error=str(exc),
            )

        parsed = _json_body(body)
        pushover_status = parsed.get("status") if parsed is not None else None
        sent = 200 <= status_code < 300 and pushover_status == 1
        send_error = None
        if not sent:
            errors = parsed.get("errors") if parsed is not None else None
            send_error = ", ".join(str(item) for item in errors) if isinstance(errors, list) else body

        return NotificationResult(
            sent=sent,
            provider=NotificationProvider.PUSHOVER,
            status_code=status_code,
            error=send_error,
            response=parsed,
        )


def evaluate_notification_alerts(
    *,
    config: NotificationAlertConfig,
    measurements: Mapping[SensorId, Measurement],
    now: datetime,
    last_sent_at: Mapping[str, datetime],
) -> tuple[NotificationAlert, ...]:
    alerts: list[NotificationAlert] = []
    specs = (
        (
            "chlorine_tank",
            "Chlorine tank supply",
            SensorId.CHLORINE_TANK_DAYS_REMAINING,
            config.chlorine_tank,
        ),
        ("ph", "pH", SensorId.RAW_PH, config.ph),
        ("orp", "ORP", SensorId.RAW_ORP, config.orp),
    )
    for signal_key, label, sensor_id, signal_config in specs:
        measurement = measurements.get(sensor_id)
        if measurement is None or measurement.quality != Quality.GOOD:
            continue
        alert = active_notification_alert(
            signal_key=signal_key,
            label=label,
            sensor_id=sensor_id,
            measurement=measurement,
            config=signal_config,
        )
        if alert is None:
            continue
        last_sent = last_sent_at.get(alert.throttle_key)
        if last_sent is None or now - last_sent >= timedelta(minutes=alert.repeat_minutes):
            alerts.append(alert)
    return tuple(alerts)


def active_notification_alert(
    *,
    signal_key: str,
    label: str,
    sensor_id: SensorId,
    measurement: Measurement,
    config: SignalNotificationConfig,
) -> NotificationAlert | None:
    if not config.enabled:
        return None

    value = float(measurement.value)
    if config.warning_below is not None and value <= config.warning_below:
        return _notification_alert(
            signal_key=signal_key,
            label=label,
            sensor_id=sensor_id,
            measurement=measurement,
            severity=NotificationAlertSeverity.WARNING,
            direction="below",
            threshold=config.warning_below,
            repeat_minutes=config.warning_repeat_minutes,
        )
    if config.warning_above is not None and value >= config.warning_above:
        return _notification_alert(
            signal_key=signal_key,
            label=label,
            sensor_id=sensor_id,
            measurement=measurement,
            severity=NotificationAlertSeverity.WARNING,
            direction="above",
            threshold=config.warning_above,
            repeat_minutes=config.warning_repeat_minutes,
        )
    if config.caution_below is not None and value <= config.caution_below:
        return _notification_alert(
            signal_key=signal_key,
            label=label,
            sensor_id=sensor_id,
            measurement=measurement,
            severity=NotificationAlertSeverity.CAUTION,
            direction="below",
            threshold=config.caution_below,
            repeat_minutes=config.caution_repeat_minutes,
        )
    if config.caution_above is not None and value >= config.caution_above:
        return _notification_alert(
            signal_key=signal_key,
            label=label,
            sensor_id=sensor_id,
            measurement=measurement,
            severity=NotificationAlertSeverity.CAUTION,
            direction="above",
            threshold=config.caution_above,
            repeat_minutes=config.caution_repeat_minutes,
        )
    return None


def _notification_alert(
    *,
    signal_key: str,
    label: str,
    sensor_id: SensorId,
    measurement: Measurement,
    severity: NotificationAlertSeverity,
    direction: str,
    threshold: float,
    repeat_minutes: float,
) -> NotificationAlert:
    return NotificationAlert(
        sensor_id=sensor_id,
        signal_key=signal_key,
        label=label,
        severity=severity,
        direction=direction,
        value=float(measurement.value),
        unit=measurement.unit,
        threshold=threshold,
        repeat_minutes=repeat_minutes,
        context=dict(measurement.metadata),
    )


def _display_value(value: float, unit: str) -> str:
    if unit == "pH":
        return f"{value:.2f}"
    if unit == "mV":
        return f"{value:.0f} mV"
    if unit == "gal":
        return f"{value:.2f} gal"
    if unit == "days":
        return f"{value:.1f} days"
    return f"{value:g} {unit}"


def _optional_float(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


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


def _looks_like_pushover_secret(value: str) -> bool:
    return (
        re.fullmatch(r"[A-Za-z0-9]{30}", value) is not None
        and any(character.islower() for character in value)
        and any(character.isdigit() for character in value)
    )


def _float_value(data: Mapping[str, Any], key: str, default: float) -> float:
    value = data.get(key, default)
    if isinstance(value, int | float):
        return float(value)
    raise ValueError(f"{key} must be a number")


def _optional_float_value(
    data: Mapping[str, Any],
    key: str,
    default: float | None,
) -> float | None:
    value = data.get(key, default)
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    raise ValueError(f"{key} must be a number or null")


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
