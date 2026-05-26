from __future__ import annotations

from datetime import timedelta
from typing import Any

from poolctl.app import PoolControllerApp, TimerOverrideState
from poolctl.config import LiveViewConfig
from poolctl.domain.models import ActuatorId, Measurement, Quality, SensorId


SENSOR_LABELS = {
    SensorId.PUMP_OUTPUT_PSI: "Pump output",
    SensorId.FILTER_OUTPUT_PSI: "Filter output",
    SensorId.RETURN_PSI: "Return",
    SensorId.BUBBLER_PSI: "Bubbler",
    SensorId.BOOSTER_PSI: "Booster",
    SensorId.PUMP_FLOW_GPM: "Pump flow",
    SensorId.FILTER_RESTRICTION_METRIC: "Filter restriction",
    SensorId.FILTER_RESTRICTION_PERCENT: "Filter restriction %",
    SensorId.RAW_ORP: "ORP",
    SensorId.ORP_TEMP: "ORP temp",
    SensorId.RAW_PH: "pH",
    SensorId.RAW_PH_VOLTAGE: "pH Vraw",
    SensorId.TEMP: "Water temp",
    SensorId.TANK_LEVEL: "Tank level",
}

ACTUATOR_LABELS = {
    ActuatorId.PUMP_MOTOR: "Pump",
    ActuatorId.PUMP_MOTOR_SPEED: "Pump speed",
    ActuatorId.BOOSTER_PUMP: "Booster",
    ActuatorId.CHLORINE_DOSING_PUMP: "Dosing pump",
}


async def build_live_snapshot(app: PoolControllerApp) -> dict[str, Any]:
    """
    Advance the runtime one tick and serialize live state for the web UI.
    """
    tick = await app.tick()
    latest_measurements = app.acquisition_service.latest_measurements if app.acquisition_service else {}
    return {
        "observed_at": tick.observed_at.isoformat(),
        "runtime": {
            "stage": app.runtime_config.stage.value,
            "driver_profile": app.runtime_config.driver_profile.value,
            "enabled_layers": sorted(layer.value for layer in app.runtime_config.enabled_layers),
        },
        "sensors": {
            sensor_id.value: measurement_payload(
                sensor_id,
                measurement,
                app.live_view_config,
            )
            for sensor_id, measurement in latest_measurements.items()
        },
        "actuators": {
            actuator_id.value: {
                "label": ACTUATOR_LABELS.get(actuator_id, actuator_id.value),
                "state": state.value,
            }
            for actuator_id, state in app.router.actuator_states.items()
        },
        "flows": tick.flow_estimates.as_payload(),
        "safety": safety_payload(app),
        "timer_override": timer_override_payload(
            app.active_timer_override() or app.active_sample_timer_override()
        ),
        "timer_override_audit": list(app.override_audit),
        "tick": {
            "acquired_groups": list(tick.acquisition.group_names),
            "measurement_count": len(tick.measurements),
            "loggable_measurement_count": len(tick.loggable_measurements),
            "logged_measurement_count": tick.logged_measurement_count,
            "logged_lab_test_count": tick.logged_lab_test_count,
            "mqtt_result_count": len(tick.mqtt_results),
            "acquisition_failures": [
                {
                    "driver": failure.driver_name,
                    "sensor_id": failure.sensor_id.value if failure.sensor_id else None,
                    "error": failure.error,
                    "observed_at": failure.observed_at.isoformat(),
                }
                for failure in tick.acquisition.failures
            ],
            "timer_results": [
                {
                    "command_id": result.command_id,
                    "accepted": result.accepted,
                    "applied": result.applied,
                    "rejection_reason": result.rejection_reason,
                }
                for result in tick.timer_results
            ],
            "safety_results": [
                {
                    "command_id": result.command_id,
                    "accepted": result.accepted,
                    "applied": result.applied,
                    "rejection_reason": result.rejection_reason,
                    "metadata": result.metadata,
                }
                for result in tick.safety_results
            ],
            "mqtt_results": [
                {
                    "command_id": result.command_id,
                    "accepted": result.accepted,
                    "applied": result.applied,
                    "rejection_reason": result.rejection_reason,
                    "metadata": result.metadata,
                }
                for result in tick.mqtt_results
            ],
        },
    }


def build_history_payload(
    app: PoolControllerApp,
    *,
    sensor_id: SensorId,
    hours: float,
    limit: int,
    validated_only: bool = True,
    resolution: str = "auto",
    max_points: int = 1500,
) -> dict[str, Any]:
    """
    Serialize logged measurement history for one sensor.
    """
    if hours <= 0:
        raise ValueError("hours must be greater than 0")

    if limit < 1:
        raise ValueError("limit must be at least 1")

    if app.measurement_logger is None:
        return {
            "sensor_id": sensor_id.value,
            "points": [],
        }

    now = app.clock.now()
    since = now - timedelta(hours=hours)
    bucket_seconds = history_bucket_seconds(hours=hours, resolution=resolution, validated_only=validated_only)
    records = app.measurement_logger.history_with_rollup(
        sensor_id=sensor_id,
        since=since,
        until=now,
        limit=limit,
        qualities=(Quality.GOOD,) if validated_only else None,
        bucket_seconds=bucket_seconds,
        max_points=max_points,
    )

    return {
        "sensor_id": sensor_id.value,
        "points": [
            measurement_payload(
                record.sensor_id,
                record.to_measurement(),
                app.live_view_config,
            )
            for record in records
        ],
    }


def build_history_series_payload(
    app: PoolControllerApp,
    *,
    sensor_ids: tuple[SensorId, ...],
    hours: float,
    limit: int,
    validated_only: bool = True,
    resolution: str = "auto",
    max_points: int = 1500,
) -> dict[str, Any]:
    if not sensor_ids:
        raise ValueError("at least one sensor_id is required")

    if hours <= 0:
        raise ValueError("hours must be greater than 0")

    if limit < 1:
        raise ValueError("limit must be at least 1")

    if app.measurement_logger is None:
        return {
            "sensor_ids": [sensor_id.value for sensor_id in sensor_ids],
            "series": [],
        }

    now = app.clock.now()
    since = now - timedelta(hours=hours)
    bucket_seconds = history_bucket_seconds(hours=hours, resolution=resolution, validated_only=validated_only)
    series = []
    for sensor_id in sensor_ids:
        records = app.measurement_logger.history_with_rollup(
            sensor_id=sensor_id,
            since=since,
            until=now,
            limit=limit,
            qualities=(Quality.GOOD,) if validated_only else None,
            bucket_seconds=bucket_seconds,
            max_points=max_points,
        )
        series.append(
            {
                "sensor_id": sensor_id.value,
                "label": SENSOR_LABELS.get(sensor_id, sensor_id.value),
                "bucket_seconds": bucket_seconds,
                "points": [
                    measurement_payload(
                        record.sensor_id,
                        record.to_measurement(),
                        app.live_view_config,
                    )
                    for record in records
                ],
            }
        )

    return {
        "sensor_ids": [sensor_id.value for sensor_id in sensor_ids],
        "validated_only": validated_only,
        "bucket_seconds": bucket_seconds,
        "series": series,
    }


def history_bucket_seconds(
    *,
    hours: float,
    resolution: str,
    validated_only: bool,
) -> int | None:
    if resolution == "raw":
        return None
    if resolution in {"1m", "minutely"}:
        return 60
    if resolution in {"1h", "hourly"}:
        return 3600
    if resolution in {"1d", "daily"}:
        return 86400

    if not validated_only:
        return None
    if hours <= 48:
        return None
    if hours <= 24 * 14:
        return 60
    if hours <= 24 * 90:
        return 3600
    return 86400


def measurement_payload(
    sensor_id: SensorId,
    measurement: Measurement,
    live_view_config: LiveViewConfig,
) -> dict[str, Any]:
    status = measurement_status(sensor_id, measurement, live_view_config)

    return {
        "sensor_id": sensor_id.value,
        "label": SENSOR_LABELS.get(sensor_id, sensor_id.value),
        "value": measurement.value,
        "unit": measurement.unit,
        "display": format_measurement(measurement),
        "quality": measurement.quality.value,
        "status": status,
        "status_label": SENSOR_STATUS_LABELS[status],
        "limits": sensor_limits_payload(sensor_id, live_view_config),
        "kind": measurement.kind.value,
        "observed_at": measurement.observed_at.isoformat(),
        "metadata": measurement.metadata,
    }


SENSOR_STATUS_LABELS = {
    "normal": "Normal",
    "caution": "Caution",
    "alarm": "Alarm",
    "invalid": "Invalid",
    "unknown": "No limits",
}


def measurement_status(
    sensor_id: SensorId,
    measurement: Measurement,
    live_view_config: LiveViewConfig,
) -> str:
    if measurement.quality != Quality.GOOD:
        return "invalid"

    limits = live_view_config.sensor_limits.get(sensor_id)
    if limits is None:
        return "unknown"

    if measurement.value < limits.caution_min or measurement.value > limits.caution_max:
        return "alarm"

    if measurement.value < limits.normal_min or measurement.value > limits.normal_max:
        return "caution"

    return "normal"


def sensor_limits_payload(
    sensor_id: SensorId,
    live_view_config: LiveViewConfig,
) -> dict[str, float] | None:
    limits = live_view_config.sensor_limits.get(sensor_id)
    if limits is None:
        return None

    return {
        "caution_min": limits.caution_min,
        "normal_min": limits.normal_min,
        "normal_max": limits.normal_max,
        "caution_max": limits.caution_max,
    }


def format_measurement(measurement: Measurement) -> str:
    value = measurement.value

    if measurement.unit == "psi":
        return f"{value:.1f} psi"

    if measurement.unit == "percent":
        return f"{value:.0f}%"

    if measurement.unit == "pH":
        return f"{value:.2f}"

    if measurement.unit == "mV":
        return f"{value:.0f} mV"

    if measurement.unit == "gpm":
        return f"{value:.1f} gpm"

    if measurement.unit == "restriction_index":
        return f"{value:.2f} R"

    if measurement.unit in {"degF", "degC"}:
        return f"{value:.1f} {measurement.unit}"

    if measurement.unit == "V":
        return f"{value:.3f} V"

    return f"{value:g} {measurement.unit}"


def safety_payload(app: PoolControllerApp) -> dict[str, Any]:
    fault = app.router.safety_gate.active_fault
    freeze = app.router.safety_gate.freeze_status(app.clock.now())

    if fault is None:
        return {
            "locked_out": False,
            "fault": None,
            "freeze_protection": freeze,
        }

    return {
        "locked_out": True,
        "fault": {
            "code": fault.code,
            "severity": fault.severity.value,
            "message": fault.message,
            "raised_at": fault.raised_at.isoformat(),
        },
        "freeze_protection": freeze,
    }


def timer_override_payload(state: TimerOverrideState | None) -> dict[str, Any]:
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
