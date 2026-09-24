"""
Build JSON-friendly snapshots for the web dashboard.

The HTML/JavaScript frontend should not need to understand domain dataclasses,
enum types, or Measurement objects. This module translates current app state
into dictionaries with display strings, colors, status flags, and history data.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from poolctl.app import (
    DEFAULT_CHLORINE_TANK_FORECAST_RESERVE_GAL,
    PoolControllerApp,
    TimerOverrideState,
    chlorine_supply_daily_dose_oz,
    usable_chlorine_gallons,
)
from poolctl.config import MonitoringConfig
from poolctl.domain.models import ActuatorId, ChemicalType, Measurement, Quality, SensorId
from poolctl.services.chlorination import valid_dosing_windows_for_day
from poolctl.services.monitoring import classify_measurement, classify_value


SENSOR_LABELS = {
    SensorId.PUMP_OUTPUT_PSI: "Pump output",
    SensorId.PUMP_FLOW_GPM: "Pump flow",
    SensorId.PUMP_DYNAMIC_HEAD_PSI: "Pump dynamic head",
    SensorId.FILTER_REFERENCE_PSI: "Filter reference pressure",
    SensorId.FILTER_REFERENCE_FLOW_GPM: "Filter reference flow",
    SensorId.FILTER_FLOW_LOSS_PERCENT: "Filter flow loss",
    SensorId.FILTER_LOADING_PERCENT: "Filter loading (legacy)",
    SensorId.CALCIUM_SATURATION_INDEX: "CSI",
    SensorId.CHLORINE_DAILY_DELIVERED_OZ: "Daily chlorine delivered",
    SensorId.CHLORINATION_DUTY_CYCLE_PERCENT: "Dosing duty cycle",
    SensorId.FC_DEMAND_PPM_PER_DAY: "FC demand",
    SensorId.BASE_FC_DEMAND_PPM_PER_DAY: "Base FC demand",
    SensorId.FC_DEMAND_WEATHER_ADJUSTMENT_PPM_PER_DAY: "FC demand weather adjustment",
    SensorId.PREDICTED_FC_DEMAND_PPM_PER_DAY: "Predicted FC demand",
    SensorId.FC_DEMAND_RESIDUAL_PPM_PER_DAY: "FC demand residual",
    SensorId.DAILY_WATER_TEMP_MIN: "Daily water temp min",
    SensorId.DAILY_WATER_TEMP_AVG: "Daily water temp avg",
    SensorId.DAILY_WATER_TEMP_MAX: "Daily water temp max",
    SensorId.DAILY_UV_INDEX_DOSE: "Daily UV dose",
    SensorId.DAILY_SHORTWAVE_RADIATION_DOSE: "Daily shortwave dose",
    SensorId.DAILY_SODIUM_HYPOCHLORITE_ADDED_OZ: "Daily sodium hypochlorite added",
    SensorId.DAILY_SODIUM_HYPOCHLORITE_ADDED_OZ_7D_AVG: "Sodium hypochlorite 7d avg",
    SensorId.DAILY_SODIUM_HYPOCHLORITE_ADDED_OZ_28D_AVG: "Sodium hypochlorite 28d avg",
    SensorId.DAILY_MURIATIC_ACID_ADDED_OZ: "Daily muriatic acid added",
    SensorId.DAILY_MURIATIC_ACID_ADDED_OZ_7D_AVG: "Muriatic acid 7d avg",
    SensorId.DAILY_MURIATIC_ACID_ADDED_OZ_28D_AVG: "Muriatic acid 28d avg",
    SensorId.DAILY_ORP_AVG: "Daily ORP avg",
    SensorId.DAILY_ORP_AVG_7D_AVG: "ORP 7d avg",
    SensorId.DAILY_ORP_AVG_28D_AVG: "ORP 28d avg",
    SensorId.DAILY_WATER_TEMP_AVG_7D_AVG: "Water temp 7d avg",
    SensorId.DAILY_WATER_TEMP_AVG_28D_AVG: "Water temp 28d avg",
    SensorId.DAILY_PH_AVG: "Daily pH avg",
    SensorId.DAILY_PH_AVG_7D_AVG: "pH 7d avg",
    SensorId.DAILY_PH_AVG_28D_AVG: "pH 28d avg",
    SensorId.DAILY_UV_INDEX_DOSE_7D_AVG: "UV dose 7d avg",
    SensorId.DAILY_UV_INDEX_DOSE_28D_AVG: "UV dose 28d avg",
    SensorId.RAW_ORP: "ORP",
    SensorId.ORP_TEMP: "ORP temp",
    SensorId.RAW_PH: "pH",
    SensorId.PH_TEMP: "pH temp",
    SensorId.WATER_TEMP: "Water temperature",
    SensorId.TEMP: "Simulated water temp",
    SensorId.CPU_TEMP: "CPU temp",
    SensorId.CPU_LOAD_PERCENT: "CPU load",
    SensorId.CPU_FAN_RPM: "CPU fan",
    SensorId.TANK_LEVEL: "Tank level",
    SensorId.CHLORINE_TANK_LEVEL_GAL: "Chlorine tank level",
    SensorId.CHLORINE_TANK_DAYS_REMAINING: "Chlorine remaining",
}

LAB_HISTORY_SERIES: dict[str, dict[str, Any]] = {
    "lab_ph": {
        "field": "ph",
        "label": "pH (tested)",
        "unit": "pH",
        "decimals": 2,
        "status_sensor_id": SensorId.RAW_PH,
    },
    "lab_free_chlorine": {
        "field": "free_chlorine",
        "label": "Free Chlorine (tested)",
        "unit": "ppm",
        "decimals": 2,
    },
    "lab_alkalinity": {
        "field": "alkalinity",
        "label": "Alkalinity (tested)",
        "unit": "ppm",
        "decimals": 1,
    },
    "lab_calcium_hardness": {
        "field": "calcium_hardness",
        "label": "Calcium Hardness (tested)",
        "unit": "ppm",
        "decimals": 1,
    },
    "lab_cya": {
        "field": "cya",
        "label": "CYA (tested)",
        "unit": "ppm",
        "decimals": 1,
    },
    "lab_tds": {
        "field": "tds",
        "label": "TDS (tested)",
        "unit": "ppm",
        "decimals": 1,
    },
    "lab_salt": {
        "field": "salt",
        "label": "Salt (tested)",
        "unit": "ppm",
        "decimals": 1,
    },
    "lab_borates": {
        "field": "borates",
        "label": "Borates (tested)",
        "unit": "ppm",
        "decimals": 1,
    },
}
LAB_HISTORY_IDS = frozenset(LAB_HISTORY_SERIES.keys())

CHEMICAL_ADDITION_HISTORY_SERIES: dict[str, dict[str, Any]] = {
    "chemical_sodium_hypochlorite": {
        "chemical": ChemicalType.SODIUM_HYPOCHLORITE,
        "label": "Sodium Hypochlorite Added",
        "unit": "fl oz",
        "decimals": 1,
        "marker": "star",
    },
    "chemical_muriatic_acid": {
        "chemical": ChemicalType.MURIATIC_ACID,
        "label": "Muriatic Acid Added",
        "unit": "fl oz",
        "decimals": 1,
        "marker": "square",
    },
}
CHEMICAL_ADDITION_HISTORY_IDS = frozenset(CHEMICAL_ADDITION_HISTORY_SERIES.keys())

WEATHER_HISTORY_SERIES: dict[str, dict[str, Any]] = {
    "weather_temperature_2m": {"field": "temperature_2m", "label": "Weather Temp", "unit": "degF", "decimals": 1},
    "weather_relative_humidity_2m": {"field": "relative_humidity_2m", "label": "Weather RH", "unit": "%", "decimals": 1},
    "weather_dew_point_2m": {"field": "dew_point_2m", "label": "Weather Dew Point", "unit": "degF", "decimals": 1},
    "weather_apparent_temperature": {"field": "apparent_temperature", "label": "Weather Feels Like", "unit": "degF", "decimals": 1},
    "weather_precipitation": {"field": "precipitation", "label": "Weather Precip", "unit": "in", "decimals": 3},
    "weather_rain": {"field": "rain", "label": "Weather Rain", "unit": "in", "decimals": 3},
    "weather_showers": {"field": "showers", "label": "Weather Showers", "unit": "in", "decimals": 3},
    "weather_weather_code": {"field": "weather_code", "label": "Weather Code", "unit": "code", "decimals": 0},
    "weather_cloud_cover": {"field": "cloud_cover", "label": "Weather Cloud Cover", "unit": "%", "decimals": 1},
    "weather_wind_speed_10m": {"field": "wind_speed_10m", "label": "Weather Wind Speed", "unit": "mph", "decimals": 1},
    "weather_wind_direction_10m": {"field": "wind_direction_10m", "label": "Weather Wind Direction", "unit": "deg", "decimals": 0},
    "weather_wind_gusts_10m": {"field": "wind_gusts_10m", "label": "Weather Wind Gusts", "unit": "mph", "decimals": 1},
    "weather_shortwave_radiation": {"field": "shortwave_radiation", "label": "Weather Shortwave Rad", "unit": "W/m2", "decimals": 1},
    "weather_direct_radiation": {"field": "direct_radiation", "label": "Weather Direct Rad", "unit": "W/m2", "decimals": 1},
    "weather_diffuse_radiation": {"field": "diffuse_radiation", "label": "Weather Diffuse Rad", "unit": "W/m2", "decimals": 1},
    "weather_uv_index": {"field": "uv_index", "label": "Weather UV Index", "unit": "index", "decimals": 1},
    "weather_surface_pressure": {"field": "surface_pressure", "label": "Weather Surface Pressure", "unit": "hPa", "decimals": 1},
    "weather_et0_fao_evapotranspiration": {"field": "et0_fao_evapotranspiration", "label": "Weather ET0", "unit": "in", "decimals": 4},
    "weather_soil_temperature_0cm": {"field": "soil_temperature_0cm", "label": "Weather Soil Temp", "unit": "degF", "decimals": 1},
}
WEATHER_HISTORY_IDS = frozenset(WEATHER_HISTORY_SERIES.keys())
EXTRA_HISTORY_IDS = LAB_HISTORY_IDS | CHEMICAL_ADDITION_HISTORY_IDS | WEATHER_HISTORY_IDS

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
    snapshot_measurements = dict(latest_measurements)
    if tick.water_temperature_measurement is not None:
        snapshot_measurements[SensorId.WATER_TEMP] = tick.water_temperature_measurement
    if tick.csi_measurement is not None:
        snapshot_measurements[tick.csi_measurement.sensor_id] = tick.csi_measurement
    chlorine_tank_measurement = app.chlorine_tank_level_measurement(
        observed_at=tick.observed_at,
        source="live_snapshot",
    )
    if chlorine_tank_measurement is not None:
        snapshot_measurements[chlorine_tank_measurement.sensor_id] = chlorine_tank_measurement
    daily_dose_oz = chlorine_supply_daily_dose_oz(
        chlorination_status=tick.chlorination_status,
        fc_demand_status=tick.fc_demand_status,
        fallback_daily_dose_oz=app.chlorination_config.daily_dose_oz,
    )
    schedule_payload = None
    if app.pump_timer is not None:
        local_now = tick.observed_at.astimezone(
            ZoneInfo(app.pump_timer_config.timezone)
        )
        resolution = app.pump_timer.service.day(local_now.date())
        today_payload = resolution.as_payload()
        today_payload["dosing_windows"] = [
            {
                "start": window.start.isoformat(),
                "end": window.end.isoformat(),
            }
            for window in valid_dosing_windows_for_day(
                app.pump_timer_config,
                local_now.date(),
                no_dose_first_minutes=(
                    app.chlorination_config.no_dose_first_minutes
                ),
                no_dose_last_minutes=(
                    app.chlorination_config.no_dose_last_minutes
                ),
                schedule_service=app.pump_timer.service,
            )
        ]
        schedule_payload = {
            "active_profile": app.pump_timer_config.active_profile,
            "active_windows": [
                window.as_payload()
                for window in app.pump_timer.service.active_windows(tick.observed_at)
            ],
            "next_transition": (
                transition.isoformat()
                if (transition := app.next_pump_timer_transition()) is not None
                else None
            ),
            "today": today_payload,
        }
    return {
        "observed_at": tick.observed_at.isoformat(),
        "runtime": {
            "driver_profile": app.runtime_config.driver_profile.value,
        },
        "sensors": {
            sensor_id.value: measurement_payload(
                sensor_id,
                measurement,
                app.monitoring_config,
            )
            for sensor_id, measurement in snapshot_measurements.items()
        },
        "actuators": {
            actuator_id.value: {
                "label": ACTUATOR_LABELS.get(actuator_id, actuator_id.value),
                "state": state.value,
            }
            for actuator_id, state in app.router.actuator_states.items()
        },
        "flows": tick.flow_estimates.as_payload(
            monitoring_config=app.monitoring_config
        ),
        "chlorination": (
            tick.chlorination_status.as_payload()
            if tick.chlorination_status is not None
            else None
        ),
        "chlorine_supply": chlorine_supply_payload(
            reserve_gal=app.safety_config.chlorine_tank.forecast_reserve_gal,
            safety_status=app.router.safety_gate.chlorine_tank_status(),
            tank_measurement=chlorine_tank_measurement,
            daily_dose_oz=daily_dose_oz,
            monitoring_config=app.monitoring_config,
        ),
        "fc_demand": (
            tick.fc_demand_status.as_payload()
            if tick.fc_demand_status is not None
            else None
        ),
        "dosing_prime": app.dosing_prime_status(),
        "supplemental_chlorine_dose": app.supplemental_chlorine_dose_status(),
        "safety": safety_payload(app),
        "timer_override": timer_override_payload(
            app.active_timer_override() or app.active_sample_timer_override()
        ),
        "timer_override_audit": list(app.override_audit),
        "schedule": schedule_payload,
        "tick": {
            "acquired_groups": list(tick.acquisition.group_names),
            "measurement_count": len(tick.measurements),
            "loggable_measurement_count": len(tick.loggable_measurements),
            "logged_measurement_count": tick.logged_measurement_count,
            "logged_lab_test_count": tick.logged_lab_test_count,
            "logged_chlorine_delivery_count": tick.logged_chlorine_delivery_count,
            "logged_weather_count": tick.weather_result.logged_count,
            "weather_poll_error": tick.weather_result.error,
            "notification_result_count": len(tick.notification_results),
            "duration_s": tick.duration_s,
            "control_duration_s": tick.control_duration_s,
            "chlorination_results": [
                {
                    "command_id": result.command_id,
                    "accepted": result.accepted,
                    "applied": result.applied,
                    "rejection_reason": result.rejection_reason,
                    "metadata": result.metadata,
                }
                for result in tick.chlorination_results
            ],
            "startup_safe_off_results": [
                {
                    "command_id": result.command_id,
                    "accepted": result.accepted,
                    "applied": result.applied,
                    "rejection_reason": result.rejection_reason,
                    "metadata": result.metadata,
                }
                for result in tick.startup_safe_off_results
            ],
            "relay_reconciliation_results": [
                {
                    "command_id": result.command_id,
                    "accepted": result.accepted,
                    "applied": result.applied,
                    "rejection_reason": result.rejection_reason,
                    "metadata": result.metadata,
                }
                for result in tick.relay_reconciliation_results
            ],
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
            "notification_results": [
                result.as_payload()
                for result in tick.notification_results
            ],
        },
    }


def chlorine_supply_payload(
    *,
    tank_measurement: Measurement | None,
    daily_dose_oz: float,
    reserve_gal: float = DEFAULT_CHLORINE_TANK_FORECAST_RESERVE_GAL,
    safety_status: dict[str, Any] | None = None,
    monitoring_config: MonitoringConfig,
) -> dict[str, Any]:
    tank_level_gal = None
    remaining_gal = None
    days_remaining = None
    reason = None

    if tank_measurement is None:
        reason = "enter a chlorine tank level test to estimate remaining supply"
    else:
        tank_level_gal = max(0.0, float(tank_measurement.value))
        if not math.isfinite(tank_level_gal):
            tank_level_gal = None
            reason = "chlorine tank estimate is unavailable"
        else:
            remaining_gal = usable_chlorine_gallons(
                tank_level_gal,
                reserve_gal=reserve_gal,
            )

    dose = float(daily_dose_oz)
    if not math.isfinite(dose) or dose <= 0:
        if reason is None:
            reason = "daily chlorine dose is zero"
    elif remaining_gal is not None:
        days_remaining = remaining_gal * 128.0 / dose

    status = classify_value(
        days_remaining,
        monitoring_config.limit_for(SensorId.CHLORINE_TANK_DAYS_REMAINING),
    ).level.value
    remaining_display = (
        f"{remaining_gal:.2f} gallons"
        if remaining_gal is not None
        else "-- gallons"
    )
    remaining_gal_display = (
        f"{remaining_gal:.2f} gal"
        if remaining_gal is not None
        else "-- gal"
    )
    tank_level_gal_display = (
        f"{tank_level_gal:.2f} gal"
        if tank_level_gal is not None
        else "-- gal"
    )
    days_display = (
        f"{days_remaining:.1f} days"
        if days_remaining is not None
        else "-- days"
    )
    return {
        "available": remaining_gal is not None,
        "tank_level_gal": tank_level_gal,
        "tank_level_gal_display": tank_level_gal_display,
        "remaining_gal": remaining_gal,
        "usable_remaining_gal": remaining_gal,
        "remaining_gal_display": remaining_gal_display,
        "usable_remaining_gal_display": remaining_gal_display,
        "reserve_gal": reserve_gal,
        "safety": safety_status,
        "days_remaining": days_remaining,
        "days_remaining_display": days_display,
        "daily_dose_oz": dose,
        "status": status,
        "status_label": SENSOR_STATUS_LABELS[status],
        "display": f"Usable chlorine remaining {remaining_display}, {days_display}",
        "reason": reason,
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
    until: datetime | None = None,
) -> dict[str, Any]:
    """
    Serialize logged measurement history for one sensor.
    """
    if hours <= 0:
        raise ValueError("hours must be greater than 0")

    if limit < 1:
        raise ValueError("limit must be at least 1")

    window_until = until if until is not None else app.clock.now()
    since = window_until - timedelta(hours=hours)

    if app.measurement_logger is None:
        return {
            "sensor_id": sensor_id.value,
            "hours": hours,
            "since": since.isoformat(),
            "until": window_until.isoformat(),
            "points": [],
        }

    bucket_seconds = history_bucket_seconds(hours=hours, resolution=resolution, validated_only=validated_only)
    records = app.measurement_logger.history_with_rollup(
        sensor_id=sensor_id,
        since=since,
        until=window_until,
        limit=limit,
        qualities=(Quality.GOOD,) if validated_only else None,
        bucket_seconds=bucket_seconds,
        max_points=max_points,
    )

    return {
        "sensor_id": sensor_id.value,
        "hours": hours,
        "since": since.isoformat(),
        "until": window_until.isoformat(),
        "points": [
            measurement_payload(
                record.sensor_id,
                record.to_measurement(),
                app.monitoring_config,
            )
            for record in records
        ],
    }


def build_history_series_payload(
    app: PoolControllerApp,
    *,
    sensor_ids: tuple[str | SensorId, ...],
    hours: float,
    limit: int,
    validated_only: bool = True,
    resolution: str = "auto",
    max_points: int = 1500,
    until: datetime | None = None,
) -> dict[str, Any]:
    if not sensor_ids:
        raise ValueError("at least one sensor_id is required")

    if hours <= 0:
        raise ValueError("hours must be greater than 0")

    if limit < 1:
        raise ValueError("limit must be at least 1")

    window_until = until if until is not None else app.clock.now()
    since = window_until - timedelta(hours=hours)

    if app.measurement_logger is None:
        return {
            "sensor_ids": [sensor_id.value if isinstance(sensor_id, SensorId) else str(sensor_id) for sensor_id in sensor_ids],
            "validated_only": validated_only,
            "bucket_seconds": history_bucket_seconds(hours=hours, resolution=resolution, validated_only=validated_only),
            "hours": hours,
            "since": since.isoformat(),
            "until": window_until.isoformat(),
            "series": [],
        }

    bucket_seconds = history_bucket_seconds(hours=hours, resolution=resolution, validated_only=validated_only)
    series = []
    for sensor_token in sensor_ids:
        sensor_id: SensorId | None = None
        if isinstance(sensor_token, SensorId):
            sensor_id = sensor_token
        else:
            token_value = str(sensor_token)
            if token_value in EXTRA_HISTORY_IDS:
                sensor_id = None
            else:
                try:
                    sensor_id = SensorId(token_value)
                except ValueError as error:
                    raise ValueError(f"invalid sensor_id: {token_value}") from error

        if sensor_id is not None:
            records = app.measurement_logger.history_with_rollup(
                sensor_id=sensor_id,
                since=since,
                until=window_until,
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
                            app.monitoring_config,
                        )
                        for record in records
                    ],
                }
            )
            continue

        token_id = str(sensor_token)
        lab_spec = LAB_HISTORY_SERIES.get(token_id)
        if lab_spec is not None:
            lab_points = app.measurement_logger.lab_value_history(
                field=str(lab_spec["field"]),
                since=since,
                until=window_until,
                limit=limit,
            )
            points = [
                _lab_history_point_payload(
                    sensor_id=token_id,
                    label=str(lab_spec["label"]),
                    observed_at=observed_at,
                    value=value,
                    unit=str(lab_spec["unit"]),
                    decimals=int(lab_spec["decimals"]),
                    monitoring_config=app.monitoring_config,
                    status_sensor_id=lab_spec.get("status_sensor_id"),
                )
                for observed_at, value in lab_points
            ]
            series.append(
                {
                    "sensor_id": token_id,
                    "label": str(lab_spec["label"]),
                    "bucket_seconds": None,
                    "points": points,
                }
            )
            continue

        chemical_spec = CHEMICAL_ADDITION_HISTORY_SERIES.get(token_id)
        if chemical_spec is not None:
            addition_points = app.measurement_logger.chemical_addition_value_history(
                chemical=chemical_spec["chemical"],
                since=since,
                until=window_until,
                limit=limit,
            )
            points = [
                _chemical_addition_history_point_payload(
                    sensor_id=token_id,
                    label=str(chemical_spec["label"]),
                    observed_at=observed_at,
                    value=value,
                    unit=str(chemical_spec["unit"]),
                    decimals=int(chemical_spec["decimals"]),
                )
                for observed_at, value in addition_points
            ]
            series.append(
                {
                    "sensor_id": token_id,
                    "label": str(chemical_spec["label"]),
                    "bucket_seconds": None,
                    "style": "event",
                    "marker": str(chemical_spec["marker"]),
                    "points": points,
                }
            )
            continue

        weather_spec = WEATHER_HISTORY_SERIES.get(token_id)
        if weather_spec is None:
            raise ValueError(f"invalid sensor_id: {token_id}")
        field = str(weather_spec["field"])
        weather_points = app.measurement_logger.weather_history(
            field=field,
            since=since,
            until=window_until,
            limit=limit,
        )
        unit = (
            app.weather_service.latest_unit(field)
            if app.weather_service is not None
            else None
        ) or str(weather_spec["unit"])
        points = [
            _weather_history_point_payload(
                sensor_id=token_id,
                label=str(weather_spec["label"]),
                observed_at=observed_at,
                value=value,
                unit=unit,
                decimals=int(weather_spec["decimals"]),
            )
            for observed_at, value in weather_points
        ]
        series.append(
            {
                "sensor_id": token_id,
                "label": str(weather_spec["label"]),
                "bucket_seconds": None,
                "points": points,
            }
        )

    return {
        "sensor_ids": [sensor_id.value if isinstance(sensor_id, SensorId) else str(sensor_id) for sensor_id in sensor_ids],
        "validated_only": validated_only,
        "bucket_seconds": bucket_seconds,
        "hours": hours,
        "since": since.isoformat(),
        "until": window_until.isoformat(),
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
    monitoring_config: MonitoringConfig,
) -> dict[str, Any]:
    status = measurement_status(sensor_id, measurement, monitoring_config)

    return {
        "sensor_id": sensor_id.value,
        "label": SENSOR_LABELS.get(sensor_id, sensor_id.value),
        "value": measurement.value,
        "unit": measurement.unit,
        "display": format_measurement(measurement),
        "quality": measurement.quality.value,
        "status": status,
        "status_label": SENSOR_STATUS_LABELS[status],
        "limits": sensor_limits_payload(sensor_id, monitoring_config),
        "kind": measurement.kind.value,
        "observed_at": measurement.observed_at.isoformat(),
        "metadata": measurement.metadata,
    }


SENSOR_STATUS_LABELS = {
    "normal": "Normal",
    "caution": "Caution",
    "alarm": "Alarm",
    "invalid": "Invalid",
    "unknown": "Unknown",
}


def measurement_status(
    sensor_id: SensorId,
    measurement: Measurement,
    monitoring_config: MonitoringConfig,
) -> str:
    return classify_measurement(
        measurement,
        monitoring_config.limit_for(sensor_id),
    ).level.value


def sensor_limits_payload(
    sensor_id: SensorId,
    monitoring_config: MonitoringConfig,
) -> dict[str, float | None] | None:
    limits = monitoring_config.limit_for(sensor_id)
    if limits is None:
        return None
    return limits.as_mapping(include_missing=True)


def format_measurement(measurement: Measurement) -> str:
    value = measurement.value

    if measurement.unit == "psi":
        return f"{value:.1f} psi"

    if measurement.unit == "percent":
        return f"{value:.0f}%"

    if measurement.unit == "fl oz":
        return f"{value:.1f} fl oz"

    if measurement.unit == "gal":
        return f"{value:.2f} gal"

    if measurement.unit == "pH":
        return f"{value:.2f}"

    if measurement.unit == "mV":
        return f"{value:.0f} mV"

    if measurement.unit == "gpm":
        return f"{value:.1f} gpm"

    if measurement.unit == "csi":
        return f"{value:.2f}"

    if measurement.unit == "ppm/day":
        return f"{value:.2f} ppm/day"

    if measurement.unit == "index-hour":
        return f"{value:.1f} index-hour"

    if measurement.unit == "Wh/m2":
        return f"{value:.0f} Wh/m2"

    if measurement.unit in {"degF", "degC"}:
        return f"{value:.1f} {measurement.unit}"

    if measurement.unit == "V":
        return f"{value:.3f} V"

    return f"{value:g} {measurement.unit}"


def _lab_history_point_payload(
    *,
    sensor_id: str,
    label: str,
    observed_at: datetime,
    value: float,
    unit: str,
    decimals: int,
    monitoring_config: MonitoringConfig,
    status_sensor_id: SensorId | None = None,
) -> dict[str, Any]:
    display = f"{value:.{decimals}f} {unit}" if unit != "pH" else f"{value:.{decimals}f}"
    status = "unknown"
    status_label = SENSOR_STATUS_LABELS[status]
    limits = None
    if status_sensor_id is not None:
        proxy = Measurement(
            sensor_id=status_sensor_id,
            observed_at=observed_at,
            value=value,
            unit=unit,
            quality=Quality.GOOD,
        )
        status = measurement_status(status_sensor_id, proxy, monitoring_config)
        status_label = SENSOR_STATUS_LABELS[status]
        limits = sensor_limits_payload(status_sensor_id, monitoring_config)
    return {
        "sensor_id": sensor_id,
        "label": label,
        "value": value,
        "unit": unit,
        "display": display,
        "quality": Quality.GOOD.value,
        "status": status,
        "status_label": status_label,
        "limits": limits,
        "kind": "manual",
        "observed_at": observed_at.isoformat(),
        "metadata": {"source": "lab_test"},
    }


def _weather_history_point_payload(
    *,
    sensor_id: str,
    label: str,
    observed_at: datetime,
    value: float,
    unit: str,
    decimals: int,
) -> dict[str, Any]:
    if unit in {"%", "code", "index"}:
        display = f"{value:.{decimals}f} {unit}" if unit != "index" else f"{value:.{decimals}f}"
    elif unit in {"degF", "degC"}:
        display = f"{value:.{decimals}f} {unit}"
    else:
        display = f"{value:.{decimals}f} {unit}"
    return {
        "sensor_id": sensor_id,
        "label": label,
        "value": value,
        "unit": unit,
        "display": display,
        "quality": Quality.GOOD.value,
        "status": "unknown",
        "status_label": SENSOR_STATUS_LABELS["unknown"],
        "limits": None,
        "kind": "raw",
        "observed_at": observed_at.isoformat(),
        "metadata": {"source": "weather"},
    }


def _chemical_addition_history_point_payload(
    *,
    sensor_id: str,
    label: str,
    observed_at: datetime,
    value: float,
    unit: str,
    decimals: int,
) -> dict[str, Any]:
    display = f"{value:.{decimals}f} {unit}"
    return {
        "sensor_id": sensor_id,
        "label": label,
        "value": value,
        "unit": unit,
        "display": display,
        "quality": Quality.GOOD.value,
        "status": "unknown",
        "status_label": SENSOR_STATUS_LABELS["unknown"],
        "limits": None,
        "kind": "event",
        "observed_at": observed_at.isoformat(),
        "metadata": {"source": "chemical_addition"},
    }


def safety_payload(app: PoolControllerApp) -> dict[str, Any]:
    fault = app.router.safety_gate.active_fault
    freeze = app.router.safety_gate.freeze_status(app.clock.now())
    chlorine_tank = app.router.safety_gate.chlorine_tank_status()

    if fault is None:
        return {
            "locked_out": False,
            "fault": None,
            "freeze_protection": freeze,
            "chlorine_tank": chlorine_tank,
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
        "chlorine_tank": chlorine_tank,
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
