"""
HTTP server, API routes, static assets, and background runtime loop.

This module intentionally keeps the deployment simple: a small Python web server
serves the dashboard and owns an AsyncRuntime task that ticks the controller
continuously, even when no browser is connected.
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import csv
import io
import json
import os
import threading
from collections.abc import Coroutine
from datetime import datetime, timedelta, timezone
from enum import Enum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Literal, TypeVar
from urllib.parse import parse_qs, urlparse

from poolctl.app import PoolControllerApp, build_app_from_config
from poolctl.config import DriverProfile, FeatureLayer, RuntimeConfig
from poolctl.domain.models import (
    ActuatorCommand,
    ActuatorId,
    ActuatorState,
    ChemicalAddition,
    ChemicalType,
    CommandSource,
    LabTest,
    Measurement,
    SensorId,
)
from poolctl.drivers.modbus.registers import ModbusRegisterDeviceConfig
from poolctl.drivers.raspberrypi.analog_inputs import WaveshareAnalogInputConfig
from poolctl.drivers.raspberrypi.sensors import (
    DFRobotSensorCircuitBreakerConfig,
    calibrate_dfrobot_ph_sensor,
)
from poolctl.services.acquisition import AcquisitionConfig
from poolctl.services.chlorination import ChlorinationConfig
from poolctl.services.clock import AcceleratedClock, Clock
from poolctl.services.fc_demand import FcDemandConfig
from poolctl.services.measurement_logging import MeasurementLoggingConfig
from poolctl.services.notifications import NotificationsConfig
from poolctl.services.pump_timer import PumpTimerConfig, PumpTimerOverride
from poolctl.services.safety import SafetyConfig
from poolctl.services.weather import WeatherPollResult
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
CHEMICAL_DEFAULT_STRENGTH_PERCENT = {
    ChemicalType.SODIUM_HYPOCHLORITE: 12.0,
    ChemicalType.MURIATIC_ACID: 31.45,
}
CHEMICAL_LABELS = {
    ChemicalType.SODIUM_HYPOCHLORITE: "Sodium Hypochlorite",
    ChemicalType.MURIATIC_ACID: "Muriatic Acid",
}
CHEMICAL_AMOUNT_TO_FL_OZ = {
    "fl_oz": 1.0,
    "fluid_ounce": 1.0,
    "fluid_ounces": 1.0,
    "oz": 1.0,
    "gal": 128.0,
    "gallon": 128.0,
    "gallons": 128.0,
    "ml": 0.0338140227,
    "l": 33.8140227,
    "liter": 33.8140227,
    "liters": 33.8140227,
}


class AsyncRuntime:
    """
    Run all async app calls on one persistent event loop.
    """

    def __init__(self) -> None:
        # The standard-library HTTP server is synchronous, but most poolctl I/O
        # is async. A dedicated event-loop thread lets API handlers submit async
        # work without creating a new loop for every request.
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="poolctl-web-async-loop",
            daemon=True,
        )
        self._app_lock: asyncio.Lock | None = None
        self._tick_future: concurrent.futures.Future[Any] | None = None
        self._weather_future: concurrent.futures.Future[Any] | None = None
        self._state_lock = threading.Lock()
        self._latest_live_payload: dict[str, Any] | None = None
        self._last_tick_error: str | None = None
        self._last_weather_result: dict[str, Any] | None = None
        self._last_weather_error: str | None = None
        self._last_tick_started_s: float | None = None
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)

        # All app mutations are serialized through this lock. That prevents a
        # dashboard command from changing actuators halfway through a background
        # controller tick.
        self._app_lock = asyncio.Lock()
        self._loop.run_forever()

    def run(self, coroutine: Coroutine[Any, Any, Any]) -> Any:
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        return future.result()

    async def _run_serial(self, coroutine: Coroutine[Any, Any, Any]) -> Any:
        if self._app_lock is None:
            raise RuntimeError("async runtime app lock is not initialized")
        async with self._app_lock:
            return await coroutine

    def run_serial(self, coroutine: Coroutine[Any, Any, Any]) -> Any:
        # API handlers use this for commands/config writes that must not overlap
        # the background tick worker.
        future = asyncio.run_coroutine_threadsafe(self._run_serial(coroutine), self._loop)
        return future.result()

    def start_tick_loop(self, app: PoolControllerApp, *, interval_s: float) -> None:
        if interval_s <= 0:
            return
        if self._tick_future is not None:
            return
        self._tick_future = asyncio.run_coroutine_threadsafe(
            self._tick_worker(app=app, interval_s=interval_s),
            self._loop,
        )

    def start_weather_loop(
        self,
        app: PoolControllerApp,
        *,
        check_interval_s: float = 60.0,
    ) -> None:
        if check_interval_s <= 0:
            return
        if app.weather_service is None:
            return
        if self._weather_future is not None:
            return
        self._weather_future = asyncio.run_coroutine_threadsafe(
            self._weather_worker(app=app, check_interval_s=check_interval_s),
            self._loop,
        )

    def latest_live_payload(self) -> dict[str, Any] | None:
        with self._state_lock:
            return dict(self._latest_live_payload) if self._latest_live_payload is not None else None

    async def _tick_worker(self, *, app: PoolControllerApp, interval_s: float) -> None:
        while True:
            started = self._loop.time()
            previous_started = self._last_tick_started_s
            self._last_tick_started_s = started
            try:
                # build_live_snapshot() calls app.tick(), so this worker is the
                # continuously running controller loop. The pool keeps operating
                # even when no browser is open.
                payload = await self._run_serial(build_live_snapshot(app))
                elapsed = self._loop.time() - started

                # Put loop timing in the payload so the dashboard can show when
                # Modbus timeouts or expensive code are threatening 0.25 s ticks.
                payload["loop"] = _loop_timing_payload(
                    target_interval_s=interval_s,
                    started_s=started,
                    previous_started_s=previous_started,
                    elapsed_s=elapsed,
                    tick_payload=payload.get("tick", {}),
                )
                self._merge_weather_status(payload)
                with self._state_lock:
                    # Store the latest payload for normal GET /api/live calls.
                    # Those requests can return quickly without forcing a fresh
                    # controller tick.
                    self._latest_live_payload = payload
                    self._last_tick_error = None
            except asyncio.CancelledError:
                raise
            except Exception as error:
                with self._state_lock:
                    self._last_tick_error = str(error)
            elapsed = self._loop.time() - started
            # Sleep only the remaining part of the interval. If a tick overruns,
            # the next loop starts immediately and the overrun is reported.
            await asyncio.sleep(max(0.0, interval_s - elapsed))

    async def _weather_worker(
        self,
        *,
        app: PoolControllerApp,
        check_interval_s: float,
    ) -> None:
        while True:
            try:
                # Weather uses blocking HTTP. Run it in a thread so an Open-Meteo
                # timeout cannot block the async controller loop.
                result = await asyncio.to_thread(app.poll_weather_due)
                with self._state_lock:
                    self._last_weather_result = _weather_poll_payload(result)
                    self._last_weather_error = result.error
            except asyncio.CancelledError:
                raise
            except Exception as error:
                with self._state_lock:
                    self._last_weather_error = str(error)
            await app.clock.sleep(check_interval_s)

    def _merge_weather_status(self, payload: dict[str, Any]) -> None:
        with self._state_lock:
            weather_result = (
                dict(self._last_weather_result)
                if self._last_weather_result is not None
                else None
            )
            weather_error = self._last_weather_error

        if weather_result is not None:
            payload["weather_poll"] = weather_result
            tick = payload.setdefault("tick", {})
            if weather_result.get("error"):
                tick["weather_poll_error"] = weather_result["error"]
        elif weather_error is not None:
            tick = payload.setdefault("tick", {})
            tick["weather_poll_error"] = weather_error

    def close(self) -> None:
        if self._weather_future is not None:
            self._weather_future.cancel()
            try:
                self._weather_future.result(timeout=2.0)
            except Exception:
                pass
        if self._tick_future is not None:
            self._tick_future.cancel()
            try:
                self._tick_future.result(timeout=2.0)
            except Exception:
                pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2.0)


def _loop_timing_payload(
    *,
    target_interval_s: float,
    started_s: float,
    previous_started_s: float | None,
    elapsed_s: float,
    tick_payload: Any,
) -> dict[str, Any]:
    interval_since_previous_start_s = (
        None if previous_started_s is None else started_s - previous_started_s
    )
    interval_error_s = (
        None
        if interval_since_previous_start_s is None
        else interval_since_previous_start_s - target_interval_s
    )
    control_duration_s = (
        tick_payload.get("control_duration_s")
        if isinstance(tick_payload, dict)
        else None
    )

    return {
        "target_interval_s": target_interval_s,
        "tick_duration_s": elapsed_s,
        "control_duration_s": control_duration_s,
        "interval_since_previous_start_s": interval_since_previous_start_s,
        "interval_error_s": interval_error_s,
        "start_jitter_s": (
            None if interval_error_s is None else max(0.0, interval_error_s)
        ),
        "overrun_s": max(0.0, elapsed_s - target_interval_s),
    }


def _weather_poll_payload(result: WeatherPollResult) -> dict[str, Any]:
    return {
        "attempted": result.attempted,
        "updated": result.updated,
        "logged_count": result.logged_count,
        "error": result.error,
        "observed_at": (
            result.observed_at.isoformat() if result.observed_at is not None else None
        ),
    }


class PoolCtlWebHandler(BaseHTTPRequestHandler):
    app: PoolControllerApp
    config_path: Path
    event_log: list[dict[str, Any]]
    event_ids: set[str]
    async_runtime: AsyncRuntime

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

        if path == "/api/chemical_additions":
            self._serve_chemical_additions()
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

        if path == "/api/config/chlorination":
            self._serve_chlorination_config()
            return

        if path == "/api/config/fc_demand":
            self._serve_fc_demand_config()
            return

        if path == "/api/config/acquisition":
            self._serve_acquisition_config()
            return

        if path == "/api/config/logging":
            self._serve_logging_config()
            return

        if path == "/api/config/notifications":
            self._serve_notifications_config()
            return

        if path == "/api/config/analog_input":
            self._serve_analog_input_config()
            return

        if path == "/api/config/ph_sensor":
            self._serve_ph_sensor_config()
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

        if path == "/api/config/chlorination":
            self._serve_update_chlorination_config()
            return

        if path == "/api/config/fc_demand":
            self._serve_update_fc_demand_config()
            return

        if path == "/api/config/acquisition":
            self._serve_update_acquisition_config()
            return

        if path == "/api/config/logging":
            self._serve_update_logging_config()
            return

        if path == "/api/config/notifications":
            self._serve_update_notifications_config()
            return

        if path == "/api/config/analog_input":
            self._serve_update_analog_input_config()
            return

        if path == "/api/config/ph_sensor":
            self._serve_update_ph_sensor_config()
            return

        if path == "/api/safety/clear_lockout":
            self._serve_clear_safety_lockout()
            return

        if path == "/api/timer/override":
            self._serve_update_timer_override()
            return

        if path == "/api/chlorination/prime":
            self._serve_chlorination_prime()
            return

        if path == "/api/chlorination/calibration":
            self._serve_chlorination_calibration()
            return

        if path == "/api/chlorination/diagnostic_stop":
            self._serve_chlorination_diagnostic_stop()
            return

        if path == "/api/lab_tests":
            self._serve_add_lab_test()
            return

        if path == "/api/chemical_additions":
            self._serve_add_chemical_addition()
            return

        if path == "/api/system/restart":
            self._serve_restart_service()
            return

        if path == "/api/notifications/test":
            self._serve_test_notification()
            return

        if path == "/api/ph/calibrate":
            self._serve_calibrate_ph_sensor()
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
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_live_snapshot(self) -> None:
        try:
            payload = self.async_runtime.latest_live_payload()
            if payload is None:
                payload = self.async_runtime.run_serial(build_live_snapshot(self.app))
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
            until = _datetime_query_value(query, "until", self.app.clock.now())

            if len(sensor_ids) == 1 and sensor_ids[0] not in EXTRA_HISTORY_IDS:
                payload = build_history_payload(
                    self.app,
                    sensor_id=SensorId(sensor_ids[0]),
                    hours=hours,
                    limit=limit,
                    validated_only=validated_only,
                    resolution=resolution,
                    max_points=max_points,
                    until=until,
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
                    until=until,
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
            until = _datetime_query_value(query, "until", self.app.clock.now())
            payload = build_history_series_payload(
                self.app,
                sensor_ids=tuple(sensor_ids),
                hours=hours,
                limit=limit,
                validated_only=validated_only,
                resolution=resolution,
                max_points=max_points,
                until=until,
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

    def _serve_chemical_additions(self) -> None:
        try:
            query = parse_qs(urlparse(self.path).query)
            hours = _float_query_value(query, "hours", 24.0 * 30.0)
            limit = _int_query_value(query, "limit", 200)
            payload = list_chemical_additions(self.app, hours=hours, limit=limit)
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
            result = self.async_runtime.run_serial(route_command(self.app, payload))
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

    def _serve_chlorination_config(self) -> None:
        self._serve_json(serialize_chlorination_config(self.app))

    def _serve_update_chlorination_config(self) -> None:
        try:
            payload = self._read_json_body()
            result = apply_chlorination_config_update(
                app=self.app,
                config_path=self.config_path,
                payload=payload,
            )
        except ValueError as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._serve_json(result)

    def _serve_fc_demand_config(self) -> None:
        self._serve_json(serialize_fc_demand_config(self.app))

    def _serve_update_fc_demand_config(self) -> None:
        try:
            payload = self._read_json_body()
            result = apply_fc_demand_config_update(
                app=self.app,
                config_path=self.config_path,
                payload=payload,
            )
        except ValueError as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._serve_json(result)

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

    def _serve_notifications_config(self) -> None:
        self._serve_json(serialize_notifications_config(self.app))

    def _serve_update_notifications_config(self) -> None:
        try:
            payload = self._read_json_body()
            result = apply_notifications_config_update(
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

    def _serve_ph_sensor_config(self) -> None:
        try:
            payload = serialize_ph_sensor_config(self.config_path)
        except ValueError as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._serve_json(payload)

    def _serve_update_ph_sensor_config(self) -> None:
        try:
            payload = self._read_json_body()
            result = apply_ph_sensor_config_update(
                config_path=self.config_path,
                payload=payload,
            )
        except ValueError as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._serve_json(result)

    def _serve_calibrate_ph_sensor(self) -> None:
        try:
            payload = self._read_json_body()
            result = self.async_runtime.run_serial(
                calibrate_ph_sensor_from_config(
                    app=self.app,
                    config_path=self.config_path,
                    payload=payload,
                )
            )
        except ValueError as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return
        except Exception as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
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

    def _serve_chlorination_prime(self) -> None:
        try:
            payload = self._read_json_body()
            result = start_chlorination_prime(app=self.app, payload=payload)
        except ValueError as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._serve_json(result)

    def _serve_chlorination_calibration(self) -> None:
        try:
            payload = self._read_json_body()
            result = start_chlorination_calibration(app=self.app, payload=payload)
        except ValueError as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._serve_json(result)

    def _serve_chlorination_diagnostic_stop(self) -> None:
        self._discard_request_body()
        result = self.async_runtime.run_serial(
            stop_chlorination_diagnostic(app=self.app)
        )
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

    def _serve_add_chemical_addition(self) -> None:
        try:
            payload = self._read_json_body()
            result = add_chemical_addition(
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

    def _serve_restart_service(self) -> None:
        self._discard_request_body()
        request_process_restart()
        self._serve_json(
            {
                "restarting": True,
                "message": "Restart requested. Service should return in a few seconds.",
            }
        )

    def _serve_test_notification(self) -> None:
        try:
            payload = self._read_json_body()
            result = send_test_notification(app=self.app, payload=payload)
        except ValueError as error:
            self._serve_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
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

    def _discard_request_body(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length > 0:
            self.rfile.read(content_length)

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
    tick_interval_s: float = 0.25,
) -> ThreadingHTTPServer:
    clock = simulation_clock(config_path, speedup=sim_speedup)
    app = build_app_from_config(config_path, clock=clock)
    async_runtime = AsyncRuntime()
    async_runtime.start_tick_loop(app, interval_s=tick_interval_s)
    async_runtime.start_weather_loop(app)

    class BoundPoolCtlWebHandler(PoolCtlWebHandler):
        pass

    BoundPoolCtlWebHandler.app = app
    BoundPoolCtlWebHandler.config_path = Path(config_path)
    BoundPoolCtlWebHandler.event_log = []
    BoundPoolCtlWebHandler.event_ids = set()
    BoundPoolCtlWebHandler.async_runtime = async_runtime
    server = ThreadingHTTPServer((host, port), BoundPoolCtlWebHandler)
    setattr(server, "_poolctl_async_runtime", async_runtime)
    return server


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


def request_process_restart(delay_s: float = 0.4) -> None:
    def _restart() -> None:
        os._exit(0)

    threading.Timer(delay_s, _restart).start()


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


def _bool_payload_value(
    payload: dict[str, Any],
    key: str,
    default: bool,
) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"{key} must be a boolean")


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


def _datetime_query_value(
    query: dict[str, list[str]],
    key: str,
    default: datetime,
) -> datetime:
    values = query.get(key)
    if not values or not values[0].strip():
        return default

    value = values[0].strip()
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{key} must be an ISO timestamp") from error

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


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

    until_next_schedule = _bool_payload_value(payload, "until_next_schedule", False)
    if until_next_schedule:
        next_transition = app.next_pump_timer_transition()
        if next_transition is not None:
            duration_s = max(
                1.0,
                (next_transition - app.clock.now()).total_seconds(),
            )
        elif duration_s is None:
            duration_s = 3600.0

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
    fc_demand_plan = app.fc_demand_plan()
    return {
        "saved": True,
        "lab_test": _lab_test_payload(test),
        "fc_demand": (
            fc_demand_plan.status.as_payload()
            if fc_demand_plan is not None
            else None
        ),
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


def add_chemical_addition(
    *,
    app: PoolControllerApp,
    payload: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    if app.measurement_logger is None:
        raise ValueError("measurement logging is not enabled")

    raw = dict(payload)
    added_at = raw.get("added_at")
    if added_at is None:
        added_at = app.clock.now().isoformat()
    if not isinstance(added_at, str):
        raise ValueError("added_at must be an ISO timestamp string")

    chemical = _chemical_type_from_payload(raw.get("chemical"))
    amount = _positive_float(raw.get("amount"), "amount")
    unit = str(raw.get("unit") or "fl_oz").strip().lower()
    amount_fl_oz = _amount_to_fl_oz(amount, unit)
    strength_percent = raw.get("strength_percent")
    if strength_percent is None or str(strength_percent).strip() == "":
        strength_percent = CHEMICAL_DEFAULT_STRENGTH_PERCENT[chemical]
    strength = _positive_float(strength_percent, "strength_percent")

    metadata = raw.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")

    raw["added_at"] = added_at
    raw["entered_at"] = app.clock.now().isoformat()
    raw["chemical"] = chemical.value
    raw["amount"] = amount
    raw["unit"] = unit
    raw["amount_fl_oz"] = amount_fl_oz
    raw["strength_percent"] = strength
    raw["notes"] = _optional_string(raw.get("notes"))
    raw["metadata"] = {
        **metadata,
        "source": source,
    }
    raw = {key: value for key, value in raw.items() if value is not None}

    try:
        addition = ChemicalAddition.model_validate(raw)
    except Exception as error:
        raise ValueError(f"invalid chemical addition payload: {error}") from error

    app.measurement_logger.log_chemical_addition(addition)
    return {
        "saved": True,
        "chemical_addition": _chemical_addition_payload(addition),
    }


def list_chemical_additions(
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
        return {"chemical_additions": []}

    additions = app.measurement_logger.chemical_addition_history(
        since=app.clock.now() - timedelta(hours=hours),
        limit=limit,
    )
    return {
        "chemical_additions": [
            _chemical_addition_payload(addition)
            for addition in additions
        ],
    }


def _chemical_addition_payload(addition: ChemicalAddition) -> dict[str, Any]:
    return {
        "id": addition.id,
        "added_at": addition.added_at.isoformat(),
        "entered_at": addition.entered_at.isoformat(),
        "chemical": addition.chemical.value,
        "chemical_label": CHEMICAL_LABELS.get(addition.chemical, addition.chemical.value),
        "amount": addition.amount,
        "unit": addition.unit,
        "amount_fl_oz": addition.amount_fl_oz,
        "strength_percent": addition.strength_percent,
        "notes": addition.notes,
        "metadata": addition.metadata,
    }


def _chemical_type_from_payload(value: Any) -> ChemicalType:
    if not isinstance(value, str):
        raise ValueError("chemical must be a string")
    try:
        return ChemicalType(value)
    except ValueError as error:
        raise ValueError(f"unsupported chemical: {value}") from error


def _amount_to_fl_oz(amount: float, unit: str) -> float:
    factor = CHEMICAL_AMOUNT_TO_FL_OZ.get(unit)
    if factor is None:
        raise ValueError(f"unsupported chemical amount unit: {unit}")
    return amount * factor


def _positive_float(value: Any, key: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{key} must be a positive number") from error
    if parsed <= 0:
        raise ValueError(f"{key} must be a positive number")
    return parsed


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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
        "notifications": app.notification_status(),
        "chlorination": serialize_chlorination_config(app),
        "fc_demand": serialize_fc_demand_config(app),
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
                "allow_dosing": schedule.allow_dosing,
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
            "chlorine_requires_high_speed": config.chlorine_requires_high_speed,
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


def serialize_chlorination_config(app: PoolControllerApp) -> dict[str, Any]:
    config = app.chlorination_config
    return {
        "layer_enabled": app.runtime_config.layer_enabled(FeatureLayer.CHLORINATION),
        "enabled": config.enabled,
        "daily_dose_oz": config.daily_dose_oz,
        "pump_output_oz_per_min": config.pump_output_oz_per_min,
        "no_dose_last_minutes": config.no_dose_last_minutes,
        "max_duty_cycle": config.max_duty_cycle,
        "cycle_on_seconds": config.cycle_on_seconds,
        "max_cycle_period_seconds": config.max_cycle_period_seconds,
        "min_cycle_on_seconds": config.min_cycle_on_seconds,
        "applied_live": True,
    }


def apply_chlorination_config_update(
    *,
    app: PoolControllerApp,
    config_path: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    proposed = ChlorinationConfig.from_mapping({"chlorination": payload})

    config_data = _load_config_mapping(config_path)
    config_data["chlorination"] = {
        "enabled": proposed.enabled,
        "daily_dose_oz": proposed.daily_dose_oz,
        "pump_output_oz_per_min": proposed.pump_output_oz_per_min,
        "no_dose_last_minutes": proposed.no_dose_last_minutes,
        "max_duty_cycle": proposed.max_duty_cycle,
        "cycle_on_seconds": proposed.cycle_on_seconds,
        "max_cycle_period_seconds": proposed.max_cycle_period_seconds,
        "min_cycle_on_seconds": proposed.min_cycle_on_seconds,
    }
    _save_config_mapping(config_path, config_data)

    app.apply_chlorination_config(proposed)
    return {
        "updated": True,
        "applied_live": True,
        **serialize_chlorination_config(app),
    }


def serialize_fc_demand_config(app: PoolControllerApp) -> dict[str, Any]:
    config = app.fc_demand_config
    return {
        "enabled": config.enabled,
        "mode": config.mode.value,
        "pool_volume_gal": config.pool_volume_gal,
        "target_fc_ppm": config.target_fc_ppm,
        "chlorine_strength_percent": config.chlorine_strength_percent,
        "minimum_test_interval_hours": config.minimum_test_interval_hours,
        "max_daily_dose_oz": config.max_daily_dose_oz,
        "applied_live": True,
    }


def apply_fc_demand_config_update(
    *,
    app: PoolControllerApp,
    config_path: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    proposed = FcDemandConfig.from_mapping({"fc_demand": payload})

    config_data = _load_config_mapping(config_path)
    config_data["fc_demand"] = {
        "enabled": proposed.enabled,
        "mode": proposed.mode.value,
        "pool_volume_gal": proposed.pool_volume_gal,
        "target_fc_ppm": proposed.target_fc_ppm,
        "chlorine_strength_percent": proposed.chlorine_strength_percent,
        "minimum_test_interval_hours": proposed.minimum_test_interval_hours,
        "max_daily_dose_oz": proposed.max_daily_dose_oz,
    }
    _save_config_mapping(config_path, config_data)

    app.apply_fc_demand_config(proposed)
    return {
        "updated": True,
        "applied_live": True,
        **serialize_fc_demand_config(app),
    }


def start_chlorination_prime(
    *,
    app: PoolControllerApp,
    payload: dict[str, Any],
) -> dict[str, Any]:
    duration_s = payload.get("duration_s", 30.0)
    if not isinstance(duration_s, int | float):
        raise ValueError("duration_s must be a number")

    return {
        "started": True,
        "prime": app.start_dosing_pump_prime(duration_s=float(duration_s)),
    }


def start_chlorination_calibration(
    *,
    app: PoolControllerApp,
    payload: dict[str, Any],
) -> dict[str, Any]:
    duration_s = payload.get("duration_s", 20.0 * 60.0)
    duty_cycle = payload.get("duty_cycle", 0.5)
    cycle_period_s = payload.get("cycle_period_s", 120.0)
    if not isinstance(duration_s, int | float):
        raise ValueError("duration_s must be a number")
    if not isinstance(duty_cycle, int | float):
        raise ValueError("duty_cycle must be a number")
    if not isinstance(cycle_period_s, int | float):
        raise ValueError("cycle_period_s must be a number")

    return {
        "started": True,
        "prime": app.start_dosing_pump_calibration(
            duration_s=float(duration_s),
            duty_cycle=float(duty_cycle),
            cycle_period_s=float(cycle_period_s),
        ),
    }


async def stop_chlorination_diagnostic(
    *,
    app: PoolControllerApp,
) -> dict[str, Any]:
    return await app.stop_dosing_pump_diagnostic()


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
                "filter": {
                    "type": group.filtering.filter_type.value,
                    "window_samples": group.filtering.window_samples,
                    "window_seconds": group.filtering.window_seconds,
                    "min_samples": group.filtering.min_samples,
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


def serialize_notifications_config(app: PoolControllerApp) -> dict[str, Any]:
    config = app.notifications_config
    return {
        "enabled": config.enabled,
        "provider": config.provider.value,
        "default_title": config.default_title,
        "pushover": {
            "app_token_env": config.pushover.app_token_env,
            "user_key_env": config.pushover.user_key_env,
            "api_url": config.pushover.api_url,
            "timeout_s": config.pushover.timeout_s,
            "priority": config.pushover.priority,
            "sound": config.pushover.sound,
            "configured": config.pushover.as_payload()["configured"],
        },
        "applied_live": True,
    }


def apply_notifications_config_update(
    *,
    app: PoolControllerApp,
    config_path: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    proposed = NotificationsConfig.from_mapping({"notifications": payload})

    config_data = _load_config_mapping(config_path)
    config_data["notifications"] = {
        "enabled": proposed.enabled,
        "provider": proposed.provider.value,
        "default_title": proposed.default_title,
        "pushover": {
            "app_token_env": proposed.pushover.app_token_env,
            "user_key_env": proposed.pushover.user_key_env,
            "api_url": proposed.pushover.api_url,
            "timeout_s": proposed.pushover.timeout_s,
            "priority": proposed.pushover.priority,
            "sound": proposed.pushover.sound,
        },
    }
    _save_config_mapping(config_path, config_data)

    app.apply_notifications_config(proposed)
    return {
        "updated": True,
        "applied_live": True,
        **serialize_notifications_config(app),
    }


def send_test_notification(
    *,
    app: PoolControllerApp,
    payload: dict[str, Any],
) -> dict[str, Any]:
    title = payload.get("title", app.notifications_config.default_title)
    message = payload.get("message", "poolctl test notification")
    priority = payload.get("priority")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title must be a non-empty string")
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be a non-empty string")
    if priority is not None and not isinstance(priority, int):
        raise ValueError("priority must be an integer")

    result = app.send_notification(
        title=title.strip(),
        message=message.strip(),
        priority=priority,
    )
    return {
        "notification": result.as_payload(),
        "status": app.notification_status(),
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


def serialize_ph_sensor_config(config_path: Path) -> dict[str, Any]:
    data = _load_config_mapping(config_path)
    enabled = _bool_config_value(data, "enable_modbus_ph_sensor", False)
    raw_sensor_data = data.get("modbus_ph_sensor", {})
    if not isinstance(raw_sensor_data, dict):
        raise ValueError("modbus_ph_sensor must be a mapping in config")
    config = ModbusRegisterDeviceConfig.from_mapping(
        data,
        "modbus_ph_sensor",
        default_slave_id=4,
    )
    breaker = _dfrobot_circuit_breaker_config(raw_sensor_data)

    return {
        "enabled": enabled,
        "modbus_ph_sensor": {
            "port": config.port,
            "slave_id": config.slave_id,
            "baudrate": config.baudrate,
            "timeout_s": config.timeout_s,
            "circuit_breaker": _dfrobot_circuit_breaker_payload(breaker),
        },
        "calibration": {
            "low_default_ph": 4.01,
            "high_default_ph": 9.18,
        },
        "requires_restart": True,
    }


def apply_ph_sensor_config_update(
    *,
    config_path: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    enabled = _bool_payload_value(payload, "enabled", False)
    sensor_data = payload.get("modbus_ph_sensor", {})
    if not isinstance(sensor_data, dict):
        raise ValueError("modbus_ph_sensor must be a mapping")

    config_data = _load_config_mapping(config_path)
    existing_sensor_data = config_data.get("modbus_ph_sensor", {})
    if not isinstance(existing_sensor_data, dict):
        existing_sensor_data = {}
    if "circuit_breaker" not in sensor_data and "circuit_breaker" in existing_sensor_data:
        sensor_data = {
            **sensor_data,
            "circuit_breaker": existing_sensor_data["circuit_breaker"],
        }

    proposed = ModbusRegisterDeviceConfig.from_mapping(
        {"modbus_ph_sensor": sensor_data},
        "modbus_ph_sensor",
        default_slave_id=4,
    )
    breaker = _dfrobot_circuit_breaker_config(sensor_data)

    config_data["enable_modbus_ph_sensor"] = enabled
    config_data["modbus_ph_sensor"] = {
        "port": proposed.port,
        "slave_id": proposed.slave_id,
        "baudrate": proposed.baudrate,
        "timeout_s": proposed.timeout_s,
        "circuit_breaker": _dfrobot_circuit_breaker_payload(breaker),
    }

    runtime = config_data.get("runtime", {})
    if isinstance(runtime, dict) and runtime.get("driver_profile") == DriverProfile.RASPBERRY_PI.value:
        _set_acquisition_ph_sensor_ids(config_data, enabled=enabled)

    _save_config_mapping(config_path, config_data)

    return {
        "updated": True,
        "requires_restart": True,
        "message": (
            "pH sensor config updated on disk. Restart is required to rebuild hardware drivers."
        ),
        **serialize_ph_sensor_config(config_path),
    }


def _dfrobot_circuit_breaker_config(
    sensor_data: dict[str, Any],
) -> DFRobotSensorCircuitBreakerConfig:
    breaker_data = sensor_data.get("circuit_breaker", {})
    if not isinstance(breaker_data, dict):
        raise ValueError("circuit_breaker must be a mapping")
    return DFRobotSensorCircuitBreakerConfig.from_mapping(breaker_data)


def _dfrobot_circuit_breaker_payload(
    config: DFRobotSensorCircuitBreakerConfig,
) -> dict[str, Any]:
    return {
        "enabled": config.enabled,
        "failure_threshold": config.failure_threshold,
        "cooldown_s": config.cooldown_s,
    }


async def calibrate_ph_sensor_from_config(
    *,
    app: PoolControllerApp,
    config_path: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if app.runtime_config.driver_profile != DriverProfile.RASPBERRY_PI:
        raise ValueError("pH calibration requires the raspberry_pi driver profile")

    point_value = payload.get("point")
    if point_value not in {"low", "high"}:
        raise ValueError("point must be low or high")
    point: Literal["low", "high"] = "low" if point_value == "low" else "high"

    ph_value = payload.get("ph_value")
    if not isinstance(ph_value, int | float):
        raise ValueError("ph_value must be a number")

    data = _load_config_mapping(config_path)
    config = ModbusRegisterDeviceConfig.from_mapping(
        data,
        "modbus_ph_sensor",
        default_slave_id=4,
    )
    bus = (
        app.modbus_bus_registry.bus_for(
            port=config.port,
            baudrate=config.baudrate,
            timeout_s=config.timeout_s,
        )
        if app.modbus_bus_registry is not None
        else None
    )
    result = await calibrate_dfrobot_ph_sensor(
        config=config,
        point=point,
        ph_value=float(ph_value),
        bus=bus,
    )

    return {
        "calibrated": True,
        "message": f"pH {point} calibration written at {float(ph_value):.2f} pH.",
        "result": result.as_payload(),
    }


def _set_acquisition_ph_sensor_ids(config_data: dict[str, Any], *, enabled: bool) -> None:
    acquisition = config_data.get("acquisition")
    if not isinstance(acquisition, dict):
        return
    groups = acquisition.get("groups")
    if not isinstance(groups, dict):
        return

    ph_sensor_ids = {SensorId.RAW_PH.value, SensorId.PH_TEMP.value}
    for group_name, group_data in groups.items():
        if not isinstance(group_data, dict):
            continue
        sensor_ids = group_data.get("sensor_ids")
        if not isinstance(sensor_ids, list):
            continue

        updated = [str(sensor_id) for sensor_id in sensor_ids if str(sensor_id) not in ph_sensor_ids]
        if enabled and group_name == "chemistry_loop":
            for sensor_id in (SensorId.RAW_PH.value, SensorId.PH_TEMP.value):
                if sensor_id not in updated:
                    updated.append(sensor_id)
        group_data["sensor_ids"] = updated


def _bool_config_value(data: dict[str, Any], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if isinstance(value, bool):
        return value
    raise ValueError(f"{key} must be true or false")


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
    parser.add_argument(
        "--tick-interval-s",
        type=float,
        default=0.25,
        help="Dedicated runtime loop period in seconds. Set <=0 to disable background loop.",
    )
    args = parser.parse_args()

    server = create_server(
        config_path=args.config,
        host=args.host,
        port=args.port,
        sim_speedup=args.sim_speedup,
        tick_interval_s=args.tick_interval_s,
    )

    print(f"poolctl live dashboard: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        async_runtime = getattr(server, "_poolctl_async_runtime", None)
        if isinstance(async_runtime, AsyncRuntime):
            async_runtime.close()
        server.server_close()


if __name__ == "__main__":
    main()
