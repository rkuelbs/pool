from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
from datetime import datetime, timedelta, timezone
from enum import Enum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import parse_qs, urlparse

from poolctl.app import PoolControllerApp, build_app_from_config
from poolctl.config import DriverProfile, FeatureLayer, RuntimeConfig
from poolctl.domain.models import (
    ActuatorCommand,
    ActuatorId,
    ActuatorState,
    CommandSource,
    LabTest,
    Measurement,
    SensorId,
)
from poolctl.drivers.raspberrypi.analog_inputs import WaveshareAnalogInputConfig
from poolctl.services.acquisition import AcquisitionConfig
from poolctl.services.clock import AcceleratedClock, Clock
from poolctl.services.measurement_logging import MeasurementLoggingConfig
from poolctl.services.pump_timer import PumpTimerConfig, PumpTimerOverride
from poolctl.services.safety import SafetyConfig
from poolctl.web.live import (
    EXTRA_HISTORY_IDS,
    build_history_payload,
    build_history_series_payload,
    build_live_snapshot,
)

import yaml  # type: ignore[import-untyped]


STATIC_DIR = Path(__file__).with_name("static")
MAX_EVENT_COUNT = 500
EnumT = TypeVar("EnumT", bound=Enum)


class PoolCtlWebHandler(BaseHTTPRequestHandler):
    app: PoolControllerApp
    config_path: Path
    event_log: list[dict[str, Any]]
    event_ids: set[str]

    def do_GET(self) -> None:
        path = urlparse(self.path).path

        if path in {"/", "/live"}:
            self._serve_file(STATIC_DIR / "live.html", "text/html; charset=utf-8")
            return

        if path == "/history":
            self._serve_file(STATIC_DIR / "history.html", "text/html; charset=utf-8")
            return

        if path == "/schedule":
            self._serve_file(STATIC_DIR / "schedule.html", "text/html; charset=utf-8")
            return

        if path == "/config":
            self._serve_file(STATIC_DIR / "config.html", "text/html; charset=utf-8")
            return

        if path == "/app.js":
            self._serve_file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")
            return

        if path == "/styles.css":
            self._serve_file(STATIC_DIR / "styles.css", "text/css; charset=utf-8")
            return

        if path == "/api/live":
            self._serve_live_snapshot()
            return

        if path == "/api/history":
            self._serve_history()
            return

        if path == "/api/history.csv":
            self._serve_history_csv()
            return

        if path == "/api/timer/override":
            self._serve_timer_override()
            return

        if path == "/api/health":
            self._serve_health()
            return

        if path == "/api/events":
            self._serve_events()
            return

        if path == "/api/lab_tests":
            self._serve_lab_tests()
            return

        if path == "/api/config/runtime":
            self._serve_runtime_config()
            return

        if path == "/api/config/pump_timer":
            self._serve_pump_timer_config()
            return

        if path == "/api/config/safety":
            self._serve_safety_config()
            return

        if path == "/api/config/acquisition":
            self._serve_acquisition_config()
            return

        if path == "/api/config/logging":
            self._serve_logging_config()
            return

        if path == "/api/config/analog_input":
            self._serve_analog_input_config()
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        path = urlparse(self.path).path

        if path == "/api/command":
            self._serve_command_result()
            return

        if path == "/api/config/runtime":
            self._serve_update_runtime_config()
            return

        if path == "/api/config/pump_timer":
            self._serve_update_pump_timer_config()
            return

        if path == "/api/config/safety":
            self._serve_update_safety_config()
            return

        if path == "/api/config/acquisition":
            self._serve_update_acquisition_config()
            return

        if path == "/api/config/logging":
            self._serve_update_logging_config()
            return

        if path == "/api/config/analog_input":
            self._serve_update_analog_input_config()
            return

        if path == "/api/safety/clear_lockout":
            self._serve_clear_safety_lockout()
            return

        if path == "/api/timer/override":
            self._serve_update_timer_override()
            return

        if path == "/api/lab_tests":
            self._serve_add_lab_test()
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _serve_file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        content = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_live_snapshot(self) -> None:
        try:
            payload = asyncio.run(build_live_snapshot(self.app))
            self._record_live_events(payload)
        except Exception as error:
            self._serve_json(
                {
                    "error": str(error),
                },
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return

        self._serve_json(payload)

    def _serve_history(self) -> None:
        try:
            query = parse_qs(urlparse(self.path).query)
            sensor_ids = _sensor_ids_query_value(query)
            hours = _float_query_value(query, "hours", 24.0)
            limit = _int_query_value(query, "limit", 1000)
            validated_only = _bool_query_value(query, "validated_only", True)
            resolution = _string_query_value(query, "resolution", "auto")
            max_points = _int_query_value(query, "max_points", 1500)

            if len(sensor_ids) == 1 and sensor_ids[0] not in EXTRA_HISTORY_IDS:
                payload = build_history_payload(
                    self.app,
                    sensor_id=SensorId(sensor_ids[0]),
                    hours=hours,
                    limit=limit,
                    validated_only=validated_only,
                    resolution=resolution,
                    max_points=max_points,
                )
            else:
                payload = build_history_series_payload(
                    self.app,
                    sensor_ids=tuple(sensor_ids),
                    hours=hours,
                    limit=limit,
                    validated_only=validated_only,
                    resolution=resolution,
                    max_points=max_points,
                )
        except ValueError as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return
        except Exception as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._serve_json(payload)

    def _serve_history_csv(self) -> None:
        try:
            query = parse_qs(urlparse(self.path).query)
            sensor_ids = _sensor_ids_query_value(query)
            hours = _float_query_value(query, "hours", 24.0)
            limit = _int_query_value(query, "limit", 1000)
            validated_only = _bool_query_value(query, "validated_only", True)
            resolution = _string_query_value(query, "resolution", "auto")
            max_points = _int_query_value(query, "max_points", 1500)
            payload = build_history_series_payload(
                self.app,
                sensor_ids=tuple(sensor_ids),
                hours=hours,
                limit=limit,
                validated_only=validated_only,
                resolution=resolution,
                max_points=max_points,
            )
            csv_content = _history_csv_content(payload)
        except ValueError as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return
        except Exception as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        content = csv_content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Disposition", 'attachment; filename="poolctl-history.csv"')
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_events(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        limit = max(1, _int_query_value(query, "limit", 100))
        event_kind = _string_query_value(query, "kind", "all")

        events = self.event_log
        if event_kind != "all":
            events = [event for event in events if event.get("kind") == event_kind]

        self._serve_json({"events": events[-limit:]})

    def _serve_lab_tests(self) -> None:
        try:
            query = parse_qs(urlparse(self.path).query)
            hours = _float_query_value(query, "hours", 24.0 * 30.0)
            limit = _int_query_value(query, "limit", 200)
            payload = list_lab_tests(self.app, hours=hours, limit=limit)
        except ValueError as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return
        except Exception as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self._serve_json(payload)

    def _serve_timer_override(self) -> None:
        self._serve_json(
            {
                "override": serialize_timer_override(self.app),
                "audit": list(self.app.override_audit),
            }
        )

    def _serve_health(self) -> None:
        self._serve_json(build_health_payload(self.app))

    def _serve_command_result(self) -> None:
        try:
            payload = self._read_json_body()
            result = asyncio.run(route_command(self.app, payload))
            self._record_command_event(payload, result)
        except ValueError as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return
        except Exception as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._serve_json(result)

    def _serve_runtime_config(self) -> None:
        self._serve_json(serialize_runtime_config(self.app))

    def _serve_update_runtime_config(self) -> None:
        try:
            payload = self._read_json_body()
            result = apply_runtime_config_update(
                app=self.app,
                config_path=self.config_path,
                payload=payload,
            )
        except ValueError as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._serve_json(result)

    def _serve_pump_timer_config(self) -> None:
        self._serve_json(serialize_pump_timer_config(self.app))

    def _serve_update_pump_timer_config(self) -> None:
        try:
            payload = self._read_json_body()
            result = apply_pump_timer_config_update(
                app=self.app,
                config_path=self.config_path,
                payload=payload,
            )
        except ValueError as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._serve_json(result)

    def _serve_safety_config(self) -> None:
        self._serve_json(serialize_safety_config(self.app))

    def _serve_update_safety_config(self) -> None:
        try:
            payload = self._read_json_body()
            result = apply_safety_config_update(
                app=self.app,
                config_path=self.config_path,
                payload=payload,
            )
        except ValueError as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._serve_json(result)

    def _serve_clear_safety_lockout(self) -> None:
        self.app.router.clear_safety_fault()
        self._append_event(
            {
                "id": f"lockout_clear:{self.app.clock.now().isoformat()}",
                "kind": "lockout",
                "level": "info",
                "message": "Safety lockout cleared from GUI",
                "observed_at": self.app.clock.now().isoformat(),
            }
        )
        self._serve_json({"cleared": True})

    def _serve_acquisition_config(self) -> None:
        self._serve_json(serialize_acquisition_config(self.app))

    def _serve_update_acquisition_config(self) -> None:
        try:
            payload = self._read_json_body()
            result = apply_acquisition_config_update(
                app=self.app,
                config_path=self.config_path,
                payload=payload,
            )
        except ValueError as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._serve_json(result)

    def _serve_logging_config(self) -> None:
        self._serve_json(serialize_logging_config(self.app))

    def _serve_update_logging_config(self) -> None:
        try:
            payload = self._read_json_body()
            result = apply_logging_config_update(
                app=self.app,
                config_path=self.config_path,
                payload=payload,
            )
        except ValueError as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._serve_json(result)

    def _serve_analog_input_config(self) -> None:
        self._serve_json(serialize_analog_input_config(self.config_path))

    def _serve_update_analog_input_config(self) -> None:
        try:
            payload = self._read_json_body()
            result = apply_analog_input_config_update(
                config_path=self.config_path,
                payload=payload,
            )
        except ValueError as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._serve_json(result)

    def _serve_update_timer_override(self) -> None:
        try:
            payload = self._read_json_body()
            result = apply_timer_override_update(app=self.app, payload=payload)
        except ValueError as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._serve_json(result)

    def _serve_add_lab_test(self) -> None:
        try:
            payload = self._read_json_body()
            result = add_lab_test(
                app=self.app,
                payload=payload,
                source="local_gui",
            )
        except ValueError as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return
        except Exception as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self._serve_json(result)

    def _record_live_events(self, payload: dict[str, Any]) -> None:
        observed_at = str(payload.get("observed_at", self.app.clock.now().isoformat()))
        for failure in payload.get("tick", {}).get("acquisition_failures", []):
            event_id = f"acq:{failure.get('observed_at')}:{failure.get('driver')}:{failure.get('sensor_id')}"
            self._append_event(
                {
                    "id": event_id,
                    "kind": "acquisition",
                    "level": "warning",
                    "message": f"{failure.get('driver')}: {failure.get('error')}",
                    "sensor_id": failure.get("sensor_id"),
                    "observed_at": failure.get("observed_at", observed_at),
                }
            )

        for result in payload.get("tick", {}).get("safety_results", []):
            reason = result.get("metadata", {}).get("safety_action")
            if not reason:
                continue
            event_id = f"safety:{result.get('command_id')}:{reason}"
            self._append_event(
                {
                    "id": event_id,
                    "kind": "safety",
                    "level": "error",
                    "message": f"Safety action {reason}",
                    "observed_at": observed_at,
                }
            )

        safety_fault = payload.get("safety", {}).get("fault")
        if safety_fault is not None:
            self._append_event(
                {
                    "id": f"fault:{safety_fault.get('code')}:{safety_fault.get('raised_at')}",
                    "kind": "lockout",
                    "level": safety_fault.get("severity", "error"),
                    "message": safety_fault.get("message"),
                    "observed_at": safety_fault.get("raised_at", observed_at),
                }
            )

    def _record_command_event(
        self,
        command_payload: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        if result.get("accepted") and result.get("applied"):
            return

        actuator_id = command_payload.get("actuator_id", "unknown")
        state = command_payload.get("state", "unknown")
        reason = result.get("rejection_reason") or "command not applied"
        self._append_event(
            {
                "id": f"command:{result.get('command_id')}",
                "kind": "command",
                "level": "warning",
                "message": f"{actuator_id} {state}: {reason}",
                "observed_at": self.app.clock.now().isoformat(),
            }
        )

    def _append_event(self, event: dict[str, Any]) -> None:
        event_id = str(event.get("id", ""))
        if event_id and event_id in self.event_ids:
            return

        if event_id:
            self.event_ids.add(event_id)

        self.event_log.append(event)
        if len(self.event_log) <= MAX_EVENT_COUNT:
            return

        overflow = len(self.event_log) - MAX_EVENT_COUNT
        removed = self.event_log[:overflow]
        self.event_log[:] = self.event_log[overflow:]
        for old_event in removed:
            old_id = str(old_event.get("id", ""))
            if old_id:
                self.event_ids.discard(old_id)

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            raise ValueError("request body is required")

        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError("request body must be valid JSON") from error

        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")

        return payload

    def _serve_json(
        self,
        payload: dict[str, Any],
        *,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        content = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def create_server(
    *,
    config_path: str | Path,
    host: str,
    port: int,
    sim_speedup: float | None = None,
) -> ThreadingHTTPServer:
    clock = simulation_clock(config_path, speedup=sim_speedup)
    app = build_app_from_config(config_path, clock=clock)

    class BoundPoolCtlWebHandler(PoolCtlWebHandler):
        pass

    BoundPoolCtlWebHandler.app = app
    BoundPoolCtlWebHandler.config_path = Path(config_path)
    BoundPoolCtlWebHandler.event_log = []
    BoundPoolCtlWebHandler.event_ids = set()
    return ThreadingHTTPServer((host, port), BoundPoolCtlWebHandler)


async def route_command(app: PoolControllerApp, payload: dict[str, Any]) -> dict[str, Any]:
    actuator_id = _enum_payload_value(ActuatorId, payload, "actuator_id")
    state = _enum_payload_value(ActuatorState, payload, "state")

    command = ActuatorCommand(
        actuator_id=actuator_id,
        created_at=app.clock.now(),
        state=state,
        requested_by=CommandSource.LOCAL_GUI,
        reason="live dashboard control",
    )

    measurements: tuple[Measurement, ...] = ()
    if app.acquisition_service is not None:
        measurements = tuple(app.acquisition_service.latest_measurements.values())

    result = await app.router.route(command, measurements=measurements)

    return {
        "command_id": result.command_id,
        "accepted": result.accepted,
        "applied": result.applied,
        "rejection_reason": result.rejection_reason,
        "metadata": result.metadata,
    }


def simulation_clock(path: str | Path, *, speedup: float | None) -> Clock | None:
    if speedup is None:
        return None

    data = _load_config_mapping(path)
    runtime_config = RuntimeConfig.from_mapping(data)
    if runtime_config.driver_profile != DriverProfile.SIMULATED:
        return None

    return AcceleratedClock(
        start_at=datetime.now(timezone.utc),
        speedup=speedup,
    )


def _load_config_mapping(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as config_file:
        data = yaml.safe_load(config_file) or {}

    if not isinstance(data, dict):
        raise ValueError("config file must contain a mapping")

    return data


def _save_config_mapping(path: str | Path, data: dict[str, Any]) -> None:
    with Path(path).open("w", encoding="utf-8") as config_file:
        yaml.safe_dump(data, config_file, sort_keys=False)


def _enum_payload_value(
    enum_type: type[EnumT],
    payload: dict[str, Any],
    key: str,
) -> EnumT:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")

    try:
        return enum_type(value)  # type: ignore[call-arg]
    except ValueError as error:
        raise ValueError(f"invalid {key}: {value}") from error


def _enum_payload_optional(
    enum_type: type[EnumT],
    payload: dict[str, Any],
    key: str,
    default: EnumT,
) -> EnumT:
    value = payload.get(key, default.value)  # type: ignore[attr-defined]
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    try:
        return enum_type(value)  # type: ignore[call-arg]
    except ValueError as error:
        raise ValueError(f"invalid {key}: {value}") from error


def _sensor_ids_query_value(query: dict[str, list[str]]) -> list[str]:
    values = query.get("sensor_id", [])
    if not values:
        raise ValueError("sensor_id query parameter is required")

    sensor_ids: list[str] = []
    for value in values:
        if "," in value:
            parts = [part.strip() for part in value.split(",") if part.strip()]
        else:
            parts = [value]

        for part in parts:
            if part in EXTRA_HISTORY_IDS:
                sensor_ids.append(part)
                continue
            try:
                sensor_ids.append(SensorId(part).value)
            except ValueError as error:
                raise ValueError(f"invalid sensor_id: {part}") from error

    return sensor_ids


def _float_query_value(
    query: dict[str, list[str]],
    key: str,
    default: float,
) -> float:
    values = query.get(key)
    if not values:
        return default

    try:
        return float(values[0])
    except ValueError as error:
        raise ValueError(f"{key} must be a number") from error


def _int_query_value(
    query: dict[str, list[str]],
    key: str,
    default: int,
) -> int:
    values = query.get(key)
    if not values:
        return default

    try:
        return int(values[0])
    except ValueError as error:
        raise ValueError(f"{key} must be an integer") from error


def _string_query_value(
    query: dict[str, list[str]],
    key: str,
    default: str,
) -> str:
    values = query.get(key)
    if not values:
        return default

    return values[0]


def _bool_query_value(
    query: dict[str, list[str]],
    key: str,
    default: bool,
) -> bool:
    values = query.get(key)
    if not values:
        return default

    value = values[0].strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False

    raise ValueError(f"{key} must be a boolean")


def _history_csv_content(payload: dict[str, Any]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["observed_at", "sensor_id", "label", "value", "unit", "quality", "status"])

    for series in payload.get("series", []):
        sensor_id = series.get("sensor_id")
        for point in series.get("points", []):
            writer.writerow(
                [
                    point.get("observed_at"),
                    sensor_id,
                    point.get("label"),
                    point.get("value"),
                    point.get("unit"),
                    point.get("quality"),
                    point.get("status"),
                ]
            )

    return output.getvalue()


def serialize_timer_override(app: PoolControllerApp) -> dict[str, Any]:
    state = app.active_timer_override() or app.active_sample_timer_override()
    if state is None:
        return {"active": False}

    return {
        "active": True,
        "set_at": state.set_at.isoformat(),
        "until": state.until.isoformat() if state.until is not None else None,
        "pump_motor": state.override.pump_motor.value,
        "pump_speed": state.override.pump_speed.value,
        "booster": state.override.booster_state.value,
        "reason": state.override.reason,
        "source": state.source,
    }


def apply_timer_override_update(
    *,
    app: PoolControllerApp,
    payload: dict[str, Any],
) -> dict[str, Any]:
    mode = payload.get("mode")
    if not isinstance(mode, str):
        raise ValueError("mode must be auto, force_on, or force_off")

    if mode == "auto":
        app.clear_timer_override()
        return {"updated": True, "override": serialize_timer_override(app)}

    if mode not in {"force_on", "force_off"}:
        raise ValueError("mode must be auto, force_on, or force_off")

    raw_duration = payload.get("duration_s")
    duration_s: float | None = None
    if raw_duration is not None:
        if not isinstance(raw_duration, int | float):
            raise ValueError("duration_s must be a number")
        duration_s = float(raw_duration)
        if duration_s <= 0:
            raise ValueError("duration_s must be greater than zero")

    if mode == "force_on" and duration_s is None:
        duration_s = 3600.0

    reason = payload.get("reason", "manual dashboard override")
    if not isinstance(reason, str):
        raise ValueError("reason must be a string")

    override = PumpTimerOverride(
        pump_motor=ActuatorState.ON if mode == "force_on" else ActuatorState.OFF,
        pump_speed=_enum_payload_optional(
            ActuatorState,
            payload,
            "pump_speed",
            ActuatorState.HIGH,
        ),
        booster_state=_enum_payload_optional(
            ActuatorState,
            payload,
            "booster",
            ActuatorState.OFF,
        ),
        reason=reason,
    )
    app.set_timer_override(override, duration_s=duration_s, source="manual_gui")
    return {"updated": True, "override": serialize_timer_override(app)}


def add_lab_test(
    *,
    app: PoolControllerApp,
    payload: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    if app.measurement_logger is None:
        raise ValueError("measurement logging is not enabled")

    raw = dict(payload)
    sampled_at = raw.get("sampled_at")
    if sampled_at is None:
        sampled_at = app.clock.now().isoformat()
    if not isinstance(sampled_at, str):
        raise ValueError("sampled_at must be an ISO timestamp string")
    raw["sampled_at"] = sampled_at
    raw["entered_at"] = app.clock.now().isoformat()
    raw = {key: value for key, value in raw.items() if value is not None}
    metadata = raw.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    raw["metadata"] = {
        **metadata,
        "source": source,
    }

    try:
        test = LabTest.model_validate(raw)
    except Exception as error:
        raise ValueError(f"invalid lab test payload: {error}") from error

    app.measurement_logger.log_lab_test(test)
    return {
        "saved": True,
        "lab_test": _lab_test_payload(test),
    }


def list_lab_tests(
    app: PoolControllerApp,
    *,
    hours: float,
    limit: int,
) -> dict[str, Any]:
    if hours <= 0:
        raise ValueError("hours must be greater than 0")
    if limit < 1:
        raise ValueError("limit must be at least 1")

    if app.measurement_logger is None:
        return {"lab_tests": []}

    tests = app.measurement_logger.lab_test_history(
        since=app.clock.now() - timedelta(hours=hours),
        limit=limit,
    )
    return {
        "lab_tests": [_lab_test_payload(test) for test in tests],
    }


def _lab_test_payload(test: LabTest) -> dict[str, Any]:
    return {
        "id": test.id,
        "sampled_at": test.sampled_at.isoformat(),
        "entered_at": test.entered_at.isoformat(),
        "ph": test.ph,
        "free_chlorine": test.free_chlorine,
        "combined_chlorine": test.combined_chlorine,
        "total_chlorine": test.total_chlorine,
        "alkalinity": test.alkalinity,
        "cya": test.cya,
        "calcium_hardness": test.calcium_hardness,
        "tds": test.tds,
        "salt": test.salt,
        "borates": test.borates,
        "water_temp": test.water_temp,
        "notes": test.notes,
        "metadata": test.metadata,
    }


def build_health_payload(app: PoolControllerApp) -> dict[str, Any]:
    now = app.clock.now()
    latest = (
        app.acquisition_service.latest_measurements
        if app.acquisition_service is not None
        else {}
    )
    freshness = {
        sensor_id.value: max(0.0, (now - measurement.observed_at).total_seconds())
        for sensor_id, measurement in latest.items()
    }
    modbus_stats = {}
    if app.modbus_bus_registry is not None:
        for port, stats in app.modbus_bus_registry.stats().items():
            modbus_stats[port] = {
                "request_count": stats.request_count,
                "error_count": stats.error_count,
                "retry_count": stats.retry_count,
                "last_error": stats.last_error,
            }

    return {
        "observed_at": now.isoformat(),
        "status": "degraded" if app.router.safety_gate.locked_out else "ok",
        "safety_lockout": app.router.safety_gate.locked_out,
        "active_layers": sorted(layer.value for layer in app.runtime_config.enabled_layers),
        "timer_override": serialize_timer_override(app),
        "acquisition": {
            "sensor_count": len(latest),
            "freshness_seconds": freshness,
        },
        "modbus": {
            "bus_count": len(modbus_stats),
            "ports": modbus_stats,
        },
        "mqtt": (
            app.mqtt_bridge.status_payload()
            if app.mqtt_bridge is not None
            else {"enabled": False, "connected": False}
        ),
        "weather": (
            app.weather_service.status_payload()
            if app.weather_service is not None
            else {"enabled": False}
        ),
    }


def serialize_runtime_config(app: PoolControllerApp) -> dict[str, Any]:
    runtime = app.runtime_config
    return {
        "stage": runtime.stage.value,
        "driver_profile": runtime.driver_profile.value,
        "enabled_layers": sorted(layer.value for layer in runtime.enabled_layers),
        "requires_restart": True,
    }


def apply_runtime_config_update(
    *,
    app: PoolControllerApp,
    config_path: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    stage = payload.get("stage")
    driver_profile = payload.get("driver_profile")
    enabled_layers = payload.get("enabled_layers")

    if not isinstance(stage, str):
        raise ValueError("stage must be a string")
    if not isinstance(driver_profile, str):
        raise ValueError("driver_profile must be a string")
    if not isinstance(enabled_layers, list) or not all(
        isinstance(item, str) for item in enabled_layers
    ):
        raise ValueError("enabled_layers must be a list of strings")

    config_data = _load_config_mapping(config_path)
    runtime_data = config_data.setdefault("runtime", {})
    if not isinstance(runtime_data, dict):
        raise ValueError("runtime must be a mapping in config")

    runtime_data["stage"] = stage
    runtime_data["driver_profile"] = driver_profile
    runtime_data["enabled_layers"] = enabled_layers
    _save_config_mapping(config_path, config_data)

    return {
        "updated": True,
        "requires_restart": True,
        "message": "Runtime config updated on disk. Restart is required to apply layer wiring changes.",
    }


def serialize_pump_timer_config(app: PoolControllerApp) -> dict[str, Any]:
    return {
        "layer_enabled": app.runtime_config.layer_enabled(FeatureLayer.PUMP_TIMER),
        "timezone": app.pump_timer_config.timezone,
        "schedules": [
            {
                "name": schedule.name,
                "start": _format_time(schedule.window.start.hour, schedule.window.start.minute),
                "end": _format_time(schedule.window.end.hour, schedule.window.end.minute),
                "pump_speed": schedule.pump_speed.value,
                "booster": schedule.booster_state.value,
            }
            for schedule in app.pump_timer_config.schedules
        ],
    }


def apply_pump_timer_config_update(
    *,
    app: PoolControllerApp,
    config_path: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    schedules_data = payload.get("schedules")
    if not isinstance(schedules_data, list):
        raise ValueError("schedules must be a list")
    timezone_name = payload.get("timezone", app.pump_timer_config.timezone)
    if not isinstance(timezone_name, str):
        raise ValueError("timezone must be a string")

    proposed_config = PumpTimerConfig.from_mapping(
        {
            "pump_timer": {
                "timezone": timezone_name,
                "schedules": schedules_data,
            }
        }
    )
    config_data = _load_config_mapping(config_path)
    pump_timer_data = config_data.setdefault("pump_timer", {})
    if not isinstance(pump_timer_data, dict):
        raise ValueError("pump_timer must be a mapping in config")

    pump_timer_data["timezone"] = timezone_name
    pump_timer_data["schedules"] = schedules_data
    _save_config_mapping(config_path, config_data)

    app.apply_pump_timer_config(proposed_config)
    return serialize_pump_timer_config(app)


def serialize_safety_config(app: PoolControllerApp) -> dict[str, Any]:
    config = app.safety_config
    return {
        "pressure_sensor_ids": {
            "pump_output": config.pressure_sensors.pump_output.value,
            "return_line": config.pressure_sensors.return_line.value,
            "booster": config.pressure_sensors.booster.value,
        },
        "freeze_protection": {
            "enabled": config.freeze_protection.enabled,
            "source": config.freeze_protection.source.value,
            "temp_sensor": config.freeze_protection.temp_sensor.value,
            "ph_temp_sensor": config.freeze_protection.ph_temp_sensor.value,
            "low_speed_on_below_temp": config.freeze_protection.low_speed_on_below_temp,
            "low_speed_off_above_temp": config.freeze_protection.low_speed_off_above_temp,
            "high_speed_on_below_temp": config.freeze_protection.high_speed_on_below_temp,
            "high_speed_off_above_temp": config.freeze_protection.high_speed_off_above_temp,
            "min_run_seconds": config.freeze_protection.min_run_seconds,
            "threshold_unit": config.freeze_protection.threshold_unit.value,
        },
        "thresholds": {
            "chlorine_min_return_psi": config.chlorine_min_return_psi,
            "chlorine_min_pump_output_psi": config.chlorine_min_pump_output_psi,
            "booster_max_psi": config.booster_max_psi,
            "booster_min_psi": config.booster_min_psi,
            "pump_low_prime_min_output_psi": config.pump_low_prime_min_output_psi,
            "pump_output_overpressure_psi": config.pump_output_overpressure_psi,
            "pump_high_prime_min_output_psi": config.pump_high_prime_min_output_psi,
        },
        "timeouts": {
            "booster_low_pressure_grace_s": config.booster_low_pressure_grace_s,
            "pump_low_prime_seconds": config.pump_low_prime_seconds,
            "pump_high_prime_timeout_s": config.pump_high_prime_timeout_s,
        },
    }


def apply_safety_config_update(
    *,
    app: PoolControllerApp,
    config_path: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    safety_data = {
        "safety": {
            "pressure_sensor_ids": payload.get("pressure_sensor_ids", {}),
            "freeze_protection": payload.get("freeze_protection", {}),
            "thresholds": payload.get("thresholds", {}),
            "timeouts": payload.get("timeouts", {}),
        }
    }
    proposed = SafetyConfig.from_mapping(safety_data)

    config_data = _load_config_mapping(config_path)
    config_data["safety"] = {
        "pressure_sensor_ids": payload.get("pressure_sensor_ids", {}),
        "freeze_protection": payload.get("freeze_protection", {}),
        "thresholds": payload.get("thresholds", {}),
        "timeouts": payload.get("timeouts", {}),
    }
    _save_config_mapping(config_path, config_data)

    app.apply_safety_config(proposed)
    return {
        "updated": True,
        "applied_live": True,
        **serialize_safety_config(app),
    }


def serialize_acquisition_config(app: PoolControllerApp) -> dict[str, Any]:
    return {
        "groups": {
            group.name: {
                "sensor_ids": [sensor_id.value for sensor_id in group.sensor_ids],
                "read_interval_s": group.read_interval_s,
                "log_interval_s": group.log_interval_s,
                "requires_pump_flow": group.requires_pump_flow,
                "min_pump_on_seconds": group.min_pump_on_seconds,
                "required_pump_speed": (
                    group.required_pump_speed.value if group.required_pump_speed else None
                ),
                "oversample": {
                    "sample_count": group.oversampling.sample_count,
                    "sample_interval_s": group.oversampling.sample_interval_s,
                    "reducer": group.oversampling.reducer.value,
                },
            }
            for group in app.acquisition_config.groups
        },
        "chemistry_sampling_refresh": {
            "enabled": app.chemistry_sampling_refresh.enabled,
            "max_pump_off_s": app.chemistry_sampling_refresh.max_pump_off_s,
            "run_duration_s": app.chemistry_sampling_refresh.run_duration_s,
            "pump_speed": app.chemistry_sampling_refresh.pump_speed.value,
        },
        "requires_restart": True,
    }


def apply_acquisition_config_update(
    *,
    app: PoolControllerApp,
    config_path: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    groups = payload.get("groups")
    if not isinstance(groups, dict):
        raise ValueError("groups must be a mapping")
    chemistry_sampling_refresh = payload.get("chemistry_sampling_refresh", {})
    if not isinstance(chemistry_sampling_refresh, dict):
        raise ValueError("chemistry_sampling_refresh must be a mapping")

    acquisition_data = {
        "acquisition": {
            "groups": groups,
            "chemistry_sampling_refresh": chemistry_sampling_refresh,
        }
    }
    AcquisitionConfig.from_mapping(acquisition_data)
    # Validate refresh fields through app config parser shape.
    from poolctl.app import _chemistry_sampling_refresh_values

    _chemistry_sampling_refresh_values(acquisition_data)

    config_data = _load_config_mapping(config_path)
    config_data["acquisition"] = {
        "groups": groups,
        "chemistry_sampling_refresh": chemistry_sampling_refresh,
    }
    _save_config_mapping(config_path, config_data)

    return {
        "updated": True,
        "requires_restart": True,
        "message": "Acquisition config updated on disk. Restart is required to rebuild acquisition drivers.",
    }


def serialize_logging_config(app: PoolControllerApp) -> dict[str, Any]:
    return {
        "database_path": str(app.measurement_logging_config.database_path),
        "layer_enabled": app.runtime_config.layer_enabled(FeatureLayer.LOGGING),
        "requires_restart": True,
    }


def apply_logging_config_update(
    *,
    app: PoolControllerApp,
    config_path: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    database_path = payload.get("database_path")
    if not isinstance(database_path, str):
        raise ValueError("database_path must be a string")

    proposed = MeasurementLoggingConfig.from_mapping(
        {
            "logging": {
                "database_path": database_path,
            }
        }
    )

    config_data = _load_config_mapping(config_path)
    config_data["logging"] = {"database_path": str(proposed.database_path)}
    _save_config_mapping(config_path, config_data)

    return {
        "updated": True,
        "requires_restart": True,
        "message": "Logging database path updated on disk. Restart is required to reopen logger.",
    }


def serialize_analog_input_config(config_path: Path) -> dict[str, Any]:
    data = _load_config_mapping(config_path)
    analog_data = data.get("modbus_analog_input", {})
    if not isinstance(analog_data, dict):
        raise ValueError("modbus_analog_input must be a mapping in config")

    return {
        "modbus_analog_input": analog_data,
        "requires_restart": True,
    }


def apply_analog_input_config_update(
    *,
    config_path: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    analog_data = payload.get("modbus_analog_input")
    if not isinstance(analog_data, dict):
        raise ValueError("modbus_analog_input must be a mapping")

    WaveshareAnalogInputConfig.from_mapping({"modbus_analog_input": analog_data})

    config_data = _load_config_mapping(config_path)
    config_data["modbus_analog_input"] = analog_data
    _save_config_mapping(config_path, config_data)

    return {
        "updated": True,
        "requires_restart": True,
        "message": "Analog input config updated on disk. Restart is required to rebuild hardware drivers.",
    }


def _format_time(hour: int, minute: int) -> str:
    return f"{hour:02}:{minute:02}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the poolctl live web dashboard.")
    parser.add_argument("--config", default="configs/windows-dev.yaml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--sim-speedup",
        type=float,
        default=None,
        help="Use an accelerated clock for simulated configs, e.g. 60 means 1 real second = 1 simulated minute.",
    )
    args = parser.parse_args()

    server = create_server(
        config_path=args.config,
        host=args.host,
        port=args.port,
        sim_speedup=args.sim_speedup,
    )

    print(f"poolctl live dashboard: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
