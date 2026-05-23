from __future__ import annotations

from datetime import datetime, timezone

from poolctl.services.clock import SimulatedClock
from poolctl.services.mqtt import MqttBridge, MqttBridgeConfig


class DummyMsg:
    def __init__(self, topic: str, payload: str) -> None:
        self.topic = topic
        self.payload = payload.encode("utf-8")


def make_clock() -> SimulatedClock:
    return SimulatedClock(
        start_at=datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc),
    )


def test_mqtt_config_defaults_from_empty_mapping() -> None:
    config = MqttBridgeConfig.from_mapping({})
    assert config.enabled is False
    assert config.topic_prefix == "poolctl"
    assert config.allow_remote_commands is False
    assert config.allow_remote_lab_tests is True


def test_mqtt_bridge_drains_only_allowed_topics() -> None:
    config = MqttBridgeConfig(
        enabled=False,
        topic_prefix="poolctl",
        allow_remote_commands=True,
        allow_remote_lab_tests=True,
    )
    bridge = MqttBridge(config, clock=make_clock())

    bridge._on_message(None, None, DummyMsg("poolctl/command/set", '{"actuator_id":"pump_motor","state":"on"}'))  # type: ignore[arg-type]
    bridge._on_message(None, None, DummyMsg("poolctl/lab_test/add", '{"ph":7.5}'))  # type: ignore[arg-type]
    bridge._on_message(None, None, DummyMsg("poolctl/config/save", '{"x":1}'))  # type: ignore[arg-type]

    commands, lab_tests = bridge.drain_inputs()
    assert len(commands) == 1
    assert commands[0]["actuator_id"] == "pump_motor"
    assert len(lab_tests) == 1
    assert lab_tests[0]["ph"] == 7.5
