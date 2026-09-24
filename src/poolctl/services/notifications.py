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

from poolctl.config import MonitoringConfig, MonitoringLimit
from poolctl.domain.models import Measurement, SensorId
from poolctl.services.monitoring import StatusLevel, classify_measurement


class NotificationProvider(str, Enum):
    PUSHOVER = "pushover"


class NotificationAlertSeverity(str, Enum):
    CAUTION = "caution"
    ALARM = "alarm"


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
class NotificationRuleConfig:
    enabled: bool = False
    notify_caution: bool = True
    notify_alarm: bool = True
    caution_repeat_minutes: float = 1440.0
    alarm_repeat_minutes: float = 240.0

    def __post_init__(self) -> None:
        if self.caution_repeat_minutes <= 0:
            raise ValueError("caution_repeat_minutes must be > 0")
        if self.alarm_repeat_minutes <= 0:
            raise ValueError("alarm_repeat_minutes must be > 0")

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any],
        *,
        default: NotificationRuleConfig,
    ) -> NotificationRuleConfig:
        supported = {
            "enabled",
            "notify_caution",
            "notify_alarm",
            "caution_repeat_minutes",
            "alarm_repeat_minutes",
        }
        unknown = set(data) - supported
        if unknown:
            raise ValueError(
                "notification rules do not own measurement thresholds or unsupported fields: "
                + ", ".join(sorted(str(item) for item in unknown))
            )
        return cls(
            enabled=_bool_value(data, "enabled", default.enabled),
            notify_caution=_bool_value(
                data,
                "notify_caution",
                default.notify_caution,
            ),
            notify_alarm=_bool_value(data, "notify_alarm", default.notify_alarm),
            caution_repeat_minutes=_float_value(
                data,
                "caution_repeat_minutes",
                default.caution_repeat_minutes,
            ),
            alarm_repeat_minutes=_float_value(
                data,
                "alarm_repeat_minutes",
                default.alarm_repeat_minutes,
            ),
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "notify_caution": self.notify_caution,
            "notify_alarm": self.notify_alarm,
            "caution_repeat_minutes": self.caution_repeat_minutes,
            "alarm_repeat_minutes": self.alarm_repeat_minutes,
        }


NUMERIC_NOTIFICATION_SIGNALS = (
    SensorId.CHLORINE_TANK_DAYS_REMAINING,
    SensorId.RAW_PH,
    SensorId.RAW_ORP,
    SensorId.FILTER_FLOW_LOSS_PERCENT,
)
FREEZE_TEMPERATURE_UNAVAILABLE_RULE = "freeze_temperature_unavailable"


def default_notification_rules() -> dict[str, NotificationRuleConfig]:
    return {
        SensorId.CHLORINE_TANK_DAYS_REMAINING.value: NotificationRuleConfig(),
        SensorId.RAW_PH.value: NotificationRuleConfig(),
        SensorId.RAW_ORP.value: NotificationRuleConfig(),
        SensorId.FILTER_FLOW_LOSS_PERCENT.value: NotificationRuleConfig(
            notify_caution=False,
            alarm_repeat_minutes=1440.0,
        ),
        FREEZE_TEMPERATURE_UNAVAILABLE_RULE: NotificationRuleConfig(
            enabled=True,
            notify_caution=False,
        ),
    }


@dataclass(frozen=True)
class NotificationsConfig:
    enabled: bool = False
    provider: NotificationProvider = NotificationProvider.PUSHOVER
    default_title: str = "PoolScope"
    pushover: PushoverConfig = field(default_factory=PushoverConfig)
    rules: dict[str, NotificationRuleConfig] = field(
        default_factory=default_notification_rules
    )

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> NotificationsConfig:
        notifications_data = _mapping_value(data, "notifications", default={})
        pushover_data = _mapping_value(notifications_data, "pushover", default={})
        rules_data = _mapping_value(notifications_data, "rules", default={})
        defaults = default_notification_rules()
        unknown_rules = set(rules_data) - set(defaults)
        if unknown_rules:
            raise ValueError(
                "notifications.rules contains unsupported rules: "
                + ", ".join(sorted(str(item) for item in unknown_rules))
            )
        rules = {
            key: NotificationRuleConfig.from_mapping(
                _mapping_value(rules_data, key, default={}),
                default=default,
            )
            for key, default in defaults.items()
        }
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
            rules=rules,
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
        if (
            self.signal_key == SensorId.CHLORINE_TANK_DAYS_REMAINING.value
            and self.unit == "days"
        ):
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
        if self.signal_key == SensorId.FILTER_FLOW_LOSS_PERCENT.value:
            age_text = _test_age_text(self.context.get("test_age_seconds"))
            suffix = f" (last hydraulic test: {age_text})" if age_text else ""
            return f"Clean filter soon: standardized flow loss is {value}{suffix}."
        if self.signal_key == FREEZE_TEMPERATURE_UNAVAILABLE_RULE:
            return "Freeze protection temperature unavailable; using fail-safe freeze protection."
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
            "rules": {
                key: rule.as_payload() for key, rule in self.config.rules.items()
            },
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
    config: Mapping[str, NotificationRuleConfig],
    monitoring_config: MonitoringConfig,
    measurements: Mapping[SensorId, Measurement],
    now: datetime,
    last_sent_at: Mapping[str, datetime],
    freeze_status: Mapping[str, Any] | None = None,
) -> tuple[NotificationAlert, ...]:
    alerts: list[NotificationAlert] = []
    specs = (
        ("Chlorine tank supply", SensorId.CHLORINE_TANK_DAYS_REMAINING),
        ("pH", SensorId.RAW_PH),
        ("ORP", SensorId.RAW_ORP),
        ("Filter flow loss", SensorId.FILTER_FLOW_LOSS_PERCENT),
    )
    for label, sensor_id in specs:
        signal_key = sensor_id.value
        signal_config = config[signal_key]
        measurement = measurements.get(sensor_id)
        alert = active_notification_alert(
            signal_key=signal_key,
            label=label,
            sensor_id=sensor_id,
            measurement=measurement,
            config=signal_config,
            limits=monitoring_config.limit_for(sensor_id),
        )
        if alert is None:
            continue
        last_sent = last_sent_at.get(alert.throttle_key)
        if last_sent is None or now - last_sent >= timedelta(minutes=alert.repeat_minutes):
            alerts.append(alert)
    freeze_config = config[FREEZE_TEMPERATURE_UNAVAILABLE_RULE]
    if (
        freeze_config.enabled
        and freeze_config.notify_alarm
        and freeze_status is not None
        and freeze_status.get("fail_safe") is True
    ):
        freeze_alert = NotificationAlert(
            sensor_id=SensorId.WATER_TEMP,
            signal_key="freeze_temperature_unavailable",
            label="Freeze protection temperature",
            severity=NotificationAlertSeverity.ALARM,
            direction="unavailable",
            value=0.0,
            unit="",
            threshold=0.0,
            repeat_minutes=freeze_config.alarm_repeat_minutes,
            context=dict(freeze_status),
        )
        last_sent = last_sent_at.get(freeze_alert.throttle_key)
        if last_sent is None or now - last_sent >= timedelta(
            minutes=freeze_alert.repeat_minutes
        ):
            alerts.append(freeze_alert)
    return tuple(alerts)


def active_notification_alert(
    *,
    signal_key: str,
    label: str,
    sensor_id: SensorId,
    measurement: Measurement | None,
    config: NotificationRuleConfig,
    limits: MonitoringLimit | None,
) -> NotificationAlert | None:
    if not config.enabled:
        return None
    evaluation = classify_measurement(measurement, limits)
    if measurement is None or evaluation.direction is None or evaluation.threshold is None:
        return None
    if evaluation.level == StatusLevel.ALARM and config.notify_alarm:
        severity = NotificationAlertSeverity.ALARM
        repeat_minutes = config.alarm_repeat_minutes
    elif evaluation.level == StatusLevel.CAUTION and config.notify_caution:
        severity = NotificationAlertSeverity.CAUTION
        repeat_minutes = config.caution_repeat_minutes
    else:
        return None
    return _notification_alert(
        signal_key=signal_key,
        label=label,
        sensor_id=sensor_id,
        measurement=measurement,
        severity=severity,
        direction=evaluation.direction.value,
        threshold=evaluation.threshold,
        repeat_minutes=repeat_minutes,
    )


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
    if unit == "percent":
        return f"{value:.1f}%"
    return f"{value:g} {unit}"


def _optional_float(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _test_age_text(value: Any) -> str | None:
    age_seconds = _optional_float(value)
    if age_seconds is None:
        return None
    age_seconds = max(0.0, age_seconds)
    if age_seconds < 3600.0:
        minutes = max(0, round(age_seconds / 60.0))
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    if age_seconds < 48.0 * 3600.0:
        hours = max(1, round(age_seconds / 3600.0))
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = max(1, round(age_seconds / 86400.0))
    return f"{days} day{'s' if days != 1 else ''} ago"


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
