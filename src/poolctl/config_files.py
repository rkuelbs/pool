"""YAML config loading, merging, and saving helpers."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


def load_config_mapping(path: str | Path) -> dict[str, Any]:
    """Load and normalize one YAML config file as a mapping."""
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as config_file:
        data = yaml.safe_load(config_file) or {}

    if not isinstance(data, dict):
        raise ValueError(f"config file must contain a mapping: {config_path}")

    return normalize_config_mapping(data)


def load_config_with_overrides(
    path: str | Path,
    *,
    local_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Load the tracked base config and merge an optional local override on top.

    Nested mappings merge recursively. Lists and scalar values replace the base
    value as a whole, which keeps sections such as schedule lists unambiguous.
    """
    base = load_config_mapping(path)
    if local_path is None:
        return base

    override_path = Path(local_path)
    if not override_path.exists():
        return base

    override = load_config_mapping(override_path)
    return merge_config_mappings(base, override)


def load_writable_config_mapping(
    path: str | Path,
    *,
    local_path: str | Path | None = None,
) -> dict[str, Any]:
    """Load the YAML file that GUI config edits should write to."""
    if local_path is None:
        return load_config_mapping(path)

    override_path = Path(local_path)
    if not override_path.exists():
        return {}
    return load_config_mapping(override_path)


def save_config_mapping(path: str | Path, data: Mapping[str, Any]) -> None:
    """Write a canonical YAML mapping, creating its parent when needed."""
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as config_file:
        yaml.safe_dump(normalize_config_mapping(data), config_file, sort_keys=False)


def config_write_path(
    config_path: str | Path,
    *,
    local_path: str | Path | None = None,
) -> Path:
    """Return the file that should receive persistent GUI config changes."""
    return Path(local_path) if local_path is not None else Path(config_path)


def merge_config_mappings(
    base: Mapping[str, Any],
    override: Mapping[str, Any],
) -> dict[str, Any]:
    """Recursively merge override values onto base values."""
    merged: dict[str, Any] = deepcopy(dict(base))
    for key, override_value in override.items():
        base_value = merged.get(key)
        if isinstance(base_value, Mapping) and isinstance(override_value, Mapping):
            merged[key] = merge_config_mappings(base_value, override_value)
        else:
            merged[key] = deepcopy(override_value)
    return merged


def normalize_config_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
    """
    Promote deprecated keys to their canonical owners within one config layer.

    Base and local files are normalized independently before merging. This is
    important: a legacy value in a local override must still beat a canonical
    value in the tracked base config. Canonical keys win over legacy keys in
    the same file; conflicting legacy duplicates fail rather than silently
    changing an operational value.
    """
    normalized = deepcopy(dict(data))

    _promote_legacy_value(
        normalized,
        ("pool", "volume_gal"),
        (("fc_demand", "pool_volume_gal"),),
    )
    _promote_legacy_value(
        normalized,
        ("chlorination", "chlorine_strength_percent"),
        (("fc_demand", "chlorine_strength_percent"),),
    )

    legacy_boundary_paths: dict[tuple[str, ...], list[tuple[str, ...]]] = {}
    live_limits = _path_value(normalized, ("live_view", "sensor_limits"))
    if live_limits is not _MISSING:
        if not isinstance(live_limits, Mapping):
            raise ValueError("live_view.sensor_limits must be a mapping")
        for raw_sensor_id, raw_limit in tuple(live_limits.items()):
            if not isinstance(raw_sensor_id, str) or not isinstance(raw_limit, Mapping):
                raise ValueError(
                    "live_view.sensor_limits entries must be sensor-id mappings"
                )
            boundary_map = {
                "caution_min": "alarm_below",
                "normal_min": "caution_below",
                "normal_max": "caution_above",
                "caution_max": "alarm_above",
            }
            for legacy_key, canonical_key in boundary_map.items():
                canonical_path = (
                    "monitoring",
                    "limits",
                    raw_sensor_id,
                    canonical_key,
                )
                legacy_boundary_paths.setdefault(canonical_path, []).append(
                    ("live_view", "sensor_limits", raw_sensor_id, legacy_key)
                )

    notification_signal_map = {
        "ph": "raw_ph",
        "orp": "raw_orp",
        "chlorine_tank": "chlorine_tank_days_remaining",
        "filter_flow_loss": "filter_flow_loss_percent",
    }
    notification_boundary_map = {
        "warning_below": "alarm_below",
        "caution_below": "caution_below",
        "caution_above": "caution_above",
        "warning_above": "alarm_above",
    }
    for legacy_signal, sensor_id in notification_signal_map.items():
        for legacy_key, canonical_key in notification_boundary_map.items():
            legacy_paths: list[tuple[str, ...]] = [
                ("notifications", "alerts", legacy_signal, legacy_key)
            ]
            if sensor_id == "filter_flow_loss_percent" and canonical_key == "caution_above":
                legacy_paths.append(("filter_loading", "yellow_flow_loss_percent"))
            if sensor_id == "filter_flow_loss_percent" and canonical_key == "alarm_above":
                legacy_paths.append(("filter_loading", "red_flow_loss_percent"))
            canonical_path = ("monitoring", "limits", sensor_id, canonical_key)
            legacy_boundary_paths.setdefault(canonical_path, []).extend(legacy_paths)

    for promoted_path, legacy_paths in legacy_boundary_paths.items():
        _promote_legacy_value(normalized, promoted_path, tuple(legacy_paths))

    _migrate_notification_rules(normalized, notification_signal_map)
    _remove_path(normalized, ("live_view", "sensor_limits"))
    _remove_path(normalized, ("notifications", "alerts"))
    return normalized


_MISSING = object()


def _path_value(data: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return _MISSING
        current = current[key]
    return current


def _set_path(data: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    current = data
    for key in path[:-1]:
        child = current.get(key)
        if child is None:
            child = {}
            current[key] = child
        if not isinstance(child, dict):
            raise ValueError(f"{'.'.join(path[:-1])} must be a mapping")
        current = child
    current[path[-1]] = deepcopy(value)


def _remove_path(data: dict[str, Any], path: tuple[str, ...]) -> None:
    parents: list[tuple[dict[str, Any], str]] = []
    current: Any = data
    for key in path[:-1]:
        if not isinstance(current, dict) or key not in current:
            return
        parents.append((current, key))
        current = current[key]
    if not isinstance(current, dict):
        return
    current.pop(path[-1], None)
    for parent, key in reversed(parents):
        child = parent.get(key)
        if isinstance(child, dict) and not child:
            parent.pop(key)
        else:
            break


def _promote_legacy_value(
    data: dict[str, Any],
    canonical_path: tuple[str, ...],
    legacy_paths: tuple[tuple[str, ...], ...],
) -> None:
    canonical_value = _path_value(data, canonical_path)
    legacy_values = [
        (path, value)
        for path in legacy_paths
        if (value := _path_value(data, path)) is not _MISSING
    ]
    if canonical_value is _MISSING and legacy_values:
        first_path, first_value = legacy_values[0]
        conflicts = [
            path for path, value in legacy_values[1:] if value != first_value
        ]
        if conflicts:
            paths = ", ".join(
                ".".join(path) for path in (first_path, *conflicts)
            )
            raise ValueError(
                f"conflicting legacy values for {'.'.join(canonical_path)}: {paths}"
            )
        _set_path(data, canonical_path, first_value)
    for legacy_path in legacy_paths:
        _remove_path(data, legacy_path)


def _migrate_notification_rules(
    data: dict[str, Any],
    signal_map: Mapping[str, str],
) -> None:
    alerts = _path_value(data, ("notifications", "alerts"))
    if alerts is _MISSING:
        return
    if not isinstance(alerts, Mapping):
        raise ValueError("notifications.alerts must be a mapping")

    for legacy_signal, sensor_id in signal_map.items():
        legacy_rule = alerts.get(legacy_signal)
        if legacy_rule is None:
            continue
        if not isinstance(legacy_rule, Mapping):
            raise ValueError(f"notifications.alerts.{legacy_signal} must be a mapping")
        base_path = ("notifications", "rules", sensor_id)
        field_map = {
            "enabled": "enabled",
            "caution_repeat_minutes": "caution_repeat_minutes",
            "warning_repeat_minutes": "alarm_repeat_minutes",
        }
        for legacy_key, canonical_key in field_map.items():
            value = legacy_rule.get(legacy_key, _MISSING)
            if value is not _MISSING and _path_value(
                data, (*base_path, canonical_key)
            ) is _MISSING:
                _set_path(data, (*base_path, canonical_key), value)

        if _path_value(data, (*base_path, "notify_caution")) is _MISSING:
            has_caution = any(
                legacy_rule.get(key) is not None
                for key in ("caution_below", "caution_above")
            )
            _set_path(data, (*base_path, "notify_caution"), has_caution)
        if _path_value(data, (*base_path, "notify_alarm")) is _MISSING:
            has_alarm = any(
                legacy_rule.get(key) is not None
                for key in ("warning_below", "warning_above")
            )
            _set_path(data, (*base_path, "notify_alarm"), has_alarm)

    freeze_rule = alerts.get("freeze_temperature_unavailable")
    if freeze_rule is not None:
        if not isinstance(freeze_rule, Mapping):
            raise ValueError(
                "notifications.alerts.freeze_temperature_unavailable must be a mapping"
            )
        base_path = ("notifications", "rules", "freeze_temperature_unavailable")
        for legacy_key, canonical_key in (
            ("enabled", "enabled"),
            ("warning_repeat_minutes", "alarm_repeat_minutes"),
        ):
            value = freeze_rule.get(legacy_key, _MISSING)
            if value is not _MISSING and _path_value(
                data, (*base_path, canonical_key)
            ) is _MISSING:
                _set_path(data, (*base_path, canonical_key), value)
        if _path_value(data, (*base_path, "notify_alarm")) is _MISSING:
            _set_path(data, (*base_path, "notify_alarm"), True)
