"""
MQTT bridge for publishing data and receiving limited remote inputs.

MQTT support lets another dashboard observe poolctl state and send selected
commands or test results. It is kept as a service so the controller can run with
or without MQTT enabled.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from poolctl.services.clock import Clock


@dataclass(frozen=True)
class MqttBridgeConfig:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 1883
    keepalive_s: int = 30
    client_id: str = "poolctl"
    username: str | None = None
    password: str | None = None
    topic_prefix: str = "poolctl"
    command_topic: str = "command/set"
    lab_test_topic: str = "lab_test/add"
    publish_live_topic: str = "telemetry/live"
    publish_health_topic: str = "telemetry/health"
    qos: int = 0
    retain: bool = False
    publish_live: bool = True
    publish_health: bool = True
    allow_remote_commands: bool = False
    allow_remote_lab_tests: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> MqttBridgeConfig:
        raw = data.get("mqtt", {})
        if not isinstance(raw, Mapping):
            raise ValueError("mqtt must be a mapping")

        username = raw.get("username")
        password = raw.get("password")
        if username is not None and not isinstance(username, str):
            raise ValueError("mqtt.username must be a string")
        if password is not None and not isinstance(password, str):
            raise ValueError("mqtt.password must be a string")

        return cls(
            enabled=_bool(raw, "enabled", cls.enabled),
            host=_string(raw, "host", cls.host),
            port=_int(raw, "port", cls.port),
            keepalive_s=_int(raw, "keepalive_s", cls.keepalive_s),
            client_id=_string(raw, "client_id", cls.client_id),
            username=username,
            password=password,
            topic_prefix=_string(raw, "topic_prefix", cls.topic_prefix),
            command_topic=_string(raw, "command_topic", cls.command_topic),
            lab_test_topic=_string(raw, "lab_test_topic", cls.lab_test_topic),
            publish_live_topic=_string(raw, "publish_live_topic", cls.publish_live_topic),
            publish_health_topic=_string(raw, "publish_health_topic", cls.publish_health_topic),
            qos=_int(raw, "qos", cls.qos),
            retain=_bool(raw, "retain", cls.retain),
            publish_live=_bool(raw, "publish_live", cls.publish_live),
            publish_health=_bool(raw, "publish_health", cls.publish_health),
            allow_remote_commands=_bool(
                raw,
                "allow_remote_commands",
                cls.allow_remote_commands,
            ),
            allow_remote_lab_tests=_bool(
                raw,
                "allow_remote_lab_tests",
                cls.allow_remote_lab_tests,
            ),
        )


@dataclass(frozen=True)
class MqttInboundPacket:
    topic: str
    payload: str
    observed_at: datetime


class MqttBridge:
    """
    Optional MQTT bridge for telemetry publish + limited remote input.

    It starts only when enabled in config and when `paho-mqtt` is available.
    """

    def __init__(self, config: MqttBridgeConfig, *, clock: Clock) -> None:
        self.config = config
        self._clock = clock
        self._queue: deque[MqttInboundPacket] = deque(maxlen=1000)
        self._connected = False
        self._available = False
        self._last_error: str | None = None
        self._client: Any | None = None

        if not config.enabled:
            return

        try:
            import paho.mqtt.client as mqtt_client  # type: ignore[import-not-found]
        except Exception as error:  # pragma: no cover - depends on local optional deps
            self._last_error = f"paho-mqtt not available: {error}"
            return

        self._available = True
        client = mqtt_client.Client(client_id=config.client_id)
        if config.username:
            client.username_pw_set(config.username, config.password)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        self._client = client
        try:
            client.connect_async(config.host, config.port, config.keepalive_s)
            client.loop_start()
        except Exception as error:  # pragma: no cover - broker connectivity
            self._last_error = str(error)

    def close(self) -> None:
        if self._client is None:
            return
        try:  # pragma: no cover - depends on optional lib
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass

    def status_payload(self) -> dict[str, Any]:
        return {
            "enabled": self.config.enabled,
            "available": self._available,
            "connected": self._connected,
            "queued_count": len(self._queue),
            "last_error": self._last_error,
            "topic_prefix": self.config.topic_prefix,
            "allow_remote_commands": self.config.allow_remote_commands,
            "allow_remote_lab_tests": self.config.allow_remote_lab_tests,
        }

    def publish_live(self, payload: dict[str, Any]) -> bool:
        if not self.config.publish_live:
            return False
        return self.publish(self.config.publish_live_topic, payload)

    def publish_health(self, payload: dict[str, Any]) -> bool:
        if not self.config.publish_health:
            return False
        return self.publish(self.config.publish_health_topic, payload)

    def publish(self, topic_suffix: str, payload: dict[str, Any]) -> bool:
        if self._client is None or not self._connected:
            return False
        try:  # pragma: no cover - depends on optional lib/broker
            self._client.publish(
                self._topic(topic_suffix),
                json.dumps(payload, separators=(",", ":"), default=str),
                qos=self.config.qos,
                retain=self.config.retain,
            )
            return True
        except Exception as error:
            self._last_error = str(error)
            return False

    def drain_inputs(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        commands: list[dict[str, Any]] = []
        lab_tests: list[dict[str, Any]] = []
        while self._queue:
            packet = self._queue.popleft()
            payload = _parse_payload(packet.payload)
            if payload is None:
                continue

            if (
                self.config.allow_remote_commands
                and packet.topic == self._topic(self.config.command_topic)
            ):
                commands.append(payload)
                continue

            if (
                self.config.allow_remote_lab_tests
                and packet.topic == self._topic(self.config.lab_test_topic)
            ):
                lab_tests.append(payload)
                continue

        return commands, lab_tests

    def _topic(self, topic_suffix: str) -> str:
        prefix = self.config.topic_prefix.strip("/")
        suffix = topic_suffix.strip("/")
        return f"{prefix}/{suffix}"

    def _on_connect(self, _client: Any, _userdata: Any, _flags: Any, rc: int) -> None:
        self._connected = rc == 0
        if rc != 0:
            self._last_error = f"MQTT connect failed rc={rc}"
            return

        if self._client is None:
            return
        try:  # pragma: no cover - depends on optional lib
            if self.config.allow_remote_commands:
                self._client.subscribe(self._topic(self.config.command_topic), qos=self.config.qos)
            if self.config.allow_remote_lab_tests:
                self._client.subscribe(self._topic(self.config.lab_test_topic), qos=self.config.qos)
        except Exception as error:
            self._last_error = str(error)

    def _on_disconnect(self, _client: Any, _userdata: Any, _rc: int) -> None:
        self._connected = False

    def _on_message(self, _client: Any, _userdata: Any, msg: Any) -> None:
        try:
            payload = msg.payload.decode("utf-8")
        except Exception:
            payload = ""
        self._queue.append(
            MqttInboundPacket(
                topic=str(msg.topic),
                payload=payload,
                observed_at=self._clock.now(),
            )
        )


def _parse_payload(raw: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _string(data: Mapping[str, Any], key: str, default: str) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"mqtt.{key} must be a string")
    return value


def _int(data: Mapping[str, Any], key: str, default: int) -> int:
    value = data.get(key, default)
    if not isinstance(value, int):
        raise ValueError(f"mqtt.{key} must be an integer")
    return value


def _bool(data: Mapping[str, Any], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"mqtt.{key} must be true or false")
    return value
