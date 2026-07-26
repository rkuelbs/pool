from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from poolctl.domain.models import (
    ActuatorCommand,
    ActuatorCommandResult,
    ActuatorId,
    ActuatorState,
    ActuatorStateSample,
    Measurement,
)
from poolctl.drivers.base import ActuatorDriver, ActuatorError
from poolctl.services.clock import Clock
from poolctl.services.safety import (
    SafetyAction,
    SafetyGate,
    SafetySnapshot,
    latest_measurements_by_sensor,
)


class CommandRouter:
    """
    Routes actuator commands through safety policy and concrete drivers.

    The router owns the current actuator-state view used by the safety gate.
    Hardware access remains isolated behind ActuatorDriver implementations.
    """

    def __init__(
        self,
        *,
        drivers: Iterable[ActuatorDriver],
        safety_gate: SafetyGate,
        clock: Clock,
        safety_enabled: bool = True,
    ) -> None:
        self._drivers: dict[ActuatorId, ActuatorDriver] = {}
        for driver in drivers:
            if driver.actuator_id in self._drivers:
                raise ValueError(f"duplicate actuator driver: {driver.actuator_id.value}")

            self._drivers[driver.actuator_id] = driver

        self._safety_gate = safety_gate
        self._clock = clock
        self._safety_enabled = safety_enabled
        self._state_samples: dict[ActuatorId, ActuatorStateSample] = {}
        self._state_started_at: dict[ActuatorId, datetime] = {}

    @property
    def safety_gate(self) -> SafetyGate:
        return self._safety_gate

    @property
    def actuator_states(self) -> dict[ActuatorId, ActuatorState]:
        return {
            actuator_id: sample.state for actuator_id, sample in self._state_samples.items()
        }

    @property
    def state_started_at(self) -> dict[ActuatorId, datetime]:
        return dict(self._state_started_at)

    async def route(
        self,
        command: ActuatorCommand,
        *,
        measurements: Iterable[Measurement] = (),
        bypass_safety: bool = False,
    ) -> ActuatorCommandResult:
        await self._ensure_state_loaded()
        now = self._clock.now()

        if command.actuator_id not in self._drivers:
            return self._result(
                command,
                accepted=False,
                applied=False,
                decided_at=now,
                rejection_reason=f"no driver registered for {command.actuator_id.value}",
            )

        if command.expires_at is not None and command.expires_at <= now:
            return self._result(
                command,
                accepted=False,
                applied=False,
                decided_at=now,
                rejection_reason="command is expired",
            )

        if self._safety_enabled and not bypass_safety:
            snapshot = self._snapshot(measurements, now=now)
            decision = self._safety_gate.check_command(command, snapshot)

            if not decision.accepted:
                return self._result(
                    command,
                    accepted=False,
                    applied=False,
                    decided_at=now,
                    rejection_reason=decision.rejection_reason,
                    metadata=decision.metadata,
                )

        metadata = {"safety_bypassed": True} if bypass_safety else None
        return await self._apply_driver_command(
            command,
            decided_at=now,
            metadata=metadata,
        )

    async def enforce_safety(
        self,
        *,
        measurements: Iterable[Measurement],
        suppressed_action_reason_codes: Iterable[str] = (),
    ) -> list[ActuatorCommandResult]:
        if not self._safety_enabled:
            return []

        await self._ensure_state_loaded()
        now = self._clock.now()
        snapshot = self._snapshot(measurements, now=now)
        actions = self._safety_gate.evaluate(snapshot)
        suppressed = set(suppressed_action_reason_codes)

        results: list[ActuatorCommandResult] = []
        for action in actions:
            if action.reason_code in suppressed:
                continue
            results.append(await self._apply_safety_action(action, decided_at=now))

        return results

    async def refresh_states(self) -> dict[ActuatorId, ActuatorStateSample]:
        for driver in self._drivers.values():
            self._record_state(await driver.read_state())

        return dict(self._state_samples)

    def clear_safety_fault(self) -> None:
        self._safety_gate.clear_fault()

    async def _ensure_state_loaded(self) -> None:
        for actuator_id, driver in self._drivers.items():
            if actuator_id in self._state_samples:
                continue

            self._record_state(await driver.read_state())

    def _snapshot(
        self,
        measurements: Iterable[Measurement],
        *,
        now: datetime,
    ) -> SafetySnapshot:
        return SafetySnapshot(
            now=now,
            actuator_states=self.actuator_states,
            state_started_at=dict(self._state_started_at),
            measurements=latest_measurements_by_sensor(measurements),
        )

    async def _apply_safety_action(
        self,
        action: SafetyAction,
        *,
        decided_at: datetime,
    ) -> ActuatorCommandResult:
        result = await self._apply_driver_command(
            action.command,
            decided_at=decided_at,
            metadata={
                "safety_action": action.reason_code,
                "fault_code": action.fault.code if action.fault is not None else None,
                "severity": action.fault.severity.value if action.fault is not None else None,
            },
        )

        return result

    async def _apply_driver_command(
        self,
        command: ActuatorCommand,
        *,
        decided_at: datetime,
        metadata: dict[str, Any] | None = None,
    ) -> ActuatorCommandResult:
        if command.actuator_id not in self._drivers:
            return self._result(
                command,
                accepted=True,
                applied=False,
                decided_at=decided_at,
                rejection_reason=f"no driver registered for {command.actuator_id.value}",
                metadata=metadata,
            )

        driver = self._drivers[command.actuator_id]
        result_metadata = dict(metadata) if metadata is not None else {}
        result_metadata["driver"] = driver.name

        try:
            sample = await driver.apply(command)
        except ActuatorError as error:
            return self._result(
                command,
                accepted=True,
                applied=False,
                decided_at=decided_at,
                rejection_reason=str(error),
                metadata=result_metadata,
            )

        self._record_state(sample)

        return self._result(
            command,
            accepted=True,
            applied=True,
            decided_at=decided_at,
            metadata=result_metadata,
        )

    def _record_state(self, sample: ActuatorStateSample) -> None:
        current = self._state_samples.get(sample.actuator_id)
        self._state_samples[sample.actuator_id] = sample

        if current is None or current.state != sample.state:
            self._state_started_at[sample.actuator_id] = sample.observed_at

    def _result(
        self,
        command: ActuatorCommand,
        *,
        accepted: bool,
        applied: bool,
        decided_at: datetime,
        rejection_reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ActuatorCommandResult:
        clean_metadata = {
            key: value
            for key, value in (metadata if metadata is not None else {}).items()
            if value is not None
        }

        return ActuatorCommandResult(
            command_id=command.id,
            accepted=accepted,
            applied=applied,
            decided_at=decided_at,
            rejection_reason=rejection_reason,
            metadata=clean_metadata,
        )
