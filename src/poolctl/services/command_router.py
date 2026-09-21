"""
Route actuator commands through safety and driver state tracking.

The router is the single place services use to command outputs. It applies the
safety gate, sends commands to drivers, remembers the latest actuator states,
and gives the GUI a consistent view of what the controller last requested.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from poolctl.domain.models import (
    ACTUATOR_AUTO_OFF_AT_METADATA,
    ACTUATOR_ON_PULSE_SECONDS_METADATA,
    ActuatorCommand,
    ActuatorCommandResult,
    ActuatorId,
    ActuatorState,
    ActuatorStateSample,
    CommandSource,
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
        command_safety_enabled: bool | None = None,
        chlorine_tank_safety_enabled: bool | None = None,
    ) -> None:
        self._drivers: dict[ActuatorId, ActuatorDriver] = {}
        for driver in drivers:
            if driver.actuator_id in self._drivers:
                raise ValueError(f"duplicate actuator driver: {driver.actuator_id.value}")

            self._drivers[driver.actuator_id] = driver

        self._safety_gate = safety_gate
        self._clock = clock
        self._safety_enabled = safety_enabled
        self._command_safety_enabled = (
            safety_enabled if command_safety_enabled is None else command_safety_enabled
        )
        self._chlorine_tank_safety_enabled = (
            self._command_safety_enabled
            if chlorine_tank_safety_enabled is None
            else chlorine_tank_safety_enabled
        )
        self._state_samples: dict[ActuatorId, ActuatorStateSample] = {}
        self._state_started_at: dict[ActuatorId, datetime] = {}

    @property
    def safety_gate(self) -> SafetyGate:
        return self._safety_gate

    @property
    def actuator_states(self) -> dict[ActuatorId, ActuatorState]:
        self._expire_auto_off_states()
        return {
            actuator_id: sample.state for actuator_id, sample in self._state_samples.items()
        }

    @property
    def actuator_state_samples(self) -> dict[ActuatorId, ActuatorStateSample]:
        self._expire_auto_off_states()
        return dict(self._state_samples)

    @property
    def state_started_at(self) -> dict[ActuatorId, datetime]:
        self._expire_auto_off_states()
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

        if not bypass_safety and (
            self._command_safety_enabled
            or self._chlorine_tank_command_check_enabled(command)
        ):
            # Safety checks use the router's current actuator-state view plus the
            # freshest measurements supplied by the caller.
            snapshot = self._snapshot(measurements, now=now)
            decision = (
                self._safety_gate.check_command(command, snapshot)
                if self._command_safety_enabled
                else self._safety_gate.check_chlorine_tank_dosing(snapshot)
            )

            if not decision.accepted:
                return self._result(
                    command,
                    accepted=False,
                    applied=False,
                    decided_at=now,
                    rejection_reason=decision.rejection_reason,
                    metadata=decision.metadata,
                )

        # bypass_safety is reserved for tightly scoped diagnostics such as a
        # dosing-pump calibration run. The metadata makes that visible in logs.
        metadata = {"safety_bypassed": True} if bypass_safety else None
        return await self._apply_driver_command(
            command,
            decided_at=now,
            metadata=metadata,
        )

    async def enforce_chlorine_tank_safety(
        self,
        *,
        measurements: Iterable[Measurement],
        suppressed_action_reason_codes: Iterable[str] = (),
    ) -> list[ActuatorCommandResult]:
        if not self._chlorine_tank_safety_enabled:
            return []

        await self._ensure_state_loaded()
        now = self._clock.now()
        snapshot = self._snapshot(measurements, now=now)
        action = self._safety_gate.chlorine_tank_action(snapshot)
        if action is None:
            return []

        if action.reason_code in set(suppressed_action_reason_codes):
            return []

        return [await self._apply_safety_action(action, decided_at=now)]

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

        # evaluate() returns system-generated actuator commands such as "shut
        # booster off" or "force pump high for freeze protection."
        actions = self._safety_gate.evaluate(snapshot)
        suppressed = set(suppressed_action_reason_codes)

        results: list[ActuatorCommandResult] = []
        for action in actions:
            if action.reason_code in suppressed:
                continue
            results.append(await self._apply_safety_action(action, decided_at=now))

        return results

    async def refresh_states(self) -> dict[ActuatorId, ActuatorStateSample]:
        self._expire_auto_off_states()
        for driver in self._drivers.values():
            self._record_state(await driver.read_state())

        return dict(self._state_samples)

    async def stop_all(self, *, reason: str) -> list[ActuatorCommandResult]:
        await self._ensure_state_loaded()
        results: list[ActuatorCommandResult] = []
        for actuator_id in _safe_stop_order(self._drivers):
            state = _safe_stop_state(actuator_id)
            if state is None:
                continue

            results.append(
                await self._apply_driver_command(
                    ActuatorCommand(
                        actuator_id=actuator_id,
                        created_at=self._clock.now(),
                        state=state,
                        requested_by=CommandSource.SYSTEM,
                        reason=reason,
                        metadata={"controller": "safe_stop_all"},
                    ),
                    decided_at=self._clock.now(),
                    metadata={"safe_stop": True},
                )
            )

        return results

    async def reconcile_states(self, *, reason: str) -> list[ActuatorCommandResult]:
        await self._ensure_state_loaded()
        desired_samples = self.actuator_state_samples
        results: list[ActuatorCommandResult] = []

        for actuator_id, driver in self._drivers.items():
            desired_sample = desired_samples.get(actuator_id)
            if desired_sample is None:
                continue

            try:
                actual_sample = await driver.read_state()
            except ActuatorError as error:
                results.append(
                    self._result(
                        ActuatorCommand(
                            actuator_id=actuator_id,
                            created_at=self._clock.now(),
                            state=desired_sample.state,
                            requested_by=CommandSource.SYSTEM,
                            reason=reason,
                            metadata={"controller": "relay_reconciliation"},
                        ),
                        accepted=True,
                        applied=False,
                        decided_at=self._clock.now(),
                        rejection_reason=f"state reconciliation read failed: {error}",
                        metadata={
                            "relay_reconciliation": True,
                            "desired_state": desired_sample.state.value,
                        },
                    )
                )
                continue

            if actual_sample.state == desired_sample.state:
                continue

            metadata = _reconciliation_command_metadata(
                desired_sample,
                now=self._clock.now(),
            )
            if metadata is None:
                continue

            results.append(
                await self._apply_driver_command(
                    ActuatorCommand(
                        actuator_id=actuator_id,
                        created_at=self._clock.now(),
                        state=desired_sample.state,
                        requested_by=CommandSource.SYSTEM,
                        reason=reason,
                        metadata=metadata,
                    ),
                    decided_at=self._clock.now(),
                    metadata={
                        "relay_reconciliation": True,
                        "actual_state": actual_sample.state.value,
                        "desired_state": desired_sample.state.value,
                    },
                )
            )

        return results

    async def ensure_states_loaded(self) -> dict[ActuatorId, ActuatorStateSample]:
        await self._ensure_state_loaded()
        return dict(self._state_samples)

    def clear_safety_fault(self) -> None:
        self._safety_gate.clear_fault()

    async def _ensure_state_loaded(self) -> None:
        self._expire_auto_off_states()
        for actuator_id, driver in self._drivers.items():
            if actuator_id in self._state_samples:
                continue

            # Lazy-load hardware state the first time it is needed. This avoids
            # assuming relay defaults before the Pi reads the board.
            self._record_state(await driver.read_state())

        self._expire_auto_off_states()

    def _chlorine_tank_command_check_enabled(self, command: ActuatorCommand) -> bool:
        return (
            self._chlorine_tank_safety_enabled
            and command.actuator_id == ActuatorId.CHLORINE_DOSING_PUMP
            and command.state == ActuatorState.ON
        )

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
                **action.command.metadata,
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

        # Update local state only after the driver reports success. If Modbus
        # fails, the router keeps its prior state view and returns applied=False.
        self._record_state(sample)
        result_metadata.update(
            {
                key: sample.metadata[key]
                for key in (
                    "timed_flash_on",
                    ACTUATOR_AUTO_OFF_AT_METADATA,
                    ACTUATOR_ON_PULSE_SECONDS_METADATA,
                    "requested_pulse_seconds",
                    "pulse_ticks_100ms",
                    "flash_address",
                )
                if key in sample.metadata
            }
        )

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
            # Track when each state began; safety rules use these timestamps for
            # booster low-pressure grace periods and pump prime timeouts.
            self._state_started_at[sample.actuator_id] = sample.observed_at

    def _expire_auto_off_states(self) -> None:
        now = self._clock.now()
        for actuator_id, sample in list(self._state_samples.items()):
            if sample.state != ActuatorState.ON:
                continue

            auto_off_at = _metadata_datetime(
                sample.metadata.get(ACTUATOR_AUTO_OFF_AT_METADATA)
            )
            if auto_off_at is None or auto_off_at > now:
                continue

            self._record_state(
                ActuatorStateSample(
                    actuator_id=actuator_id,
                    observed_at=auto_off_at,
                    state=ActuatorState.OFF,
                    source_command_id=sample.source_command_id,
                    metadata={
                        **sample.metadata,
                        "auto_off_expired": True,
                        "auto_off_previous_state": sample.state.value,
                    },
                )
            )

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


def _metadata_datetime(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    return None


def _safe_stop_order(drivers: dict[ActuatorId, ActuatorDriver]) -> tuple[ActuatorId, ...]:
    preferred_order = (
        ActuatorId.CHLORINE_DOSING_PUMP,
        ActuatorId.BOOSTER_PUMP,
        ActuatorId.PUMP_MOTOR,
        ActuatorId.PUMP_MOTOR_SPEED,
    )
    return tuple(actuator_id for actuator_id in preferred_order if actuator_id in drivers)


def _safe_stop_state(actuator_id: ActuatorId) -> ActuatorState | None:
    if actuator_id == ActuatorId.PUMP_MOTOR_SPEED:
        return ActuatorState.LOW

    if actuator_id in (
        ActuatorId.PUMP_MOTOR,
        ActuatorId.BOOSTER_PUMP,
        ActuatorId.CHLORINE_DOSING_PUMP,
    ):
        return ActuatorState.OFF

    return None


def _reconciliation_command_metadata(
    desired_sample: ActuatorStateSample,
    *,
    now: datetime,
) -> dict[str, Any] | None:
    metadata: dict[str, Any] = {
        "controller": "relay_reconciliation",
        "source_command_id": desired_sample.source_command_id,
    }

    auto_off_at = _metadata_datetime(
        desired_sample.metadata.get(ACTUATOR_AUTO_OFF_AT_METADATA)
    )
    if desired_sample.actuator_id == ActuatorId.CHLORINE_DOSING_PUMP:
        if desired_sample.state == ActuatorState.OFF:
            return metadata

        if auto_off_at is None or auto_off_at <= now:
            return None

        metadata[ACTUATOR_AUTO_OFF_AT_METADATA] = auto_off_at.isoformat()
        metadata[ACTUATOR_ON_PULSE_SECONDS_METADATA] = (
            auto_off_at - now
        ).total_seconds()

    return metadata
