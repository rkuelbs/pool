"""YAML config loading, merging, and saving helpers."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


def load_config_mapping(path: str | Path) -> dict[str, Any]:
    """Load one YAML config file as a mapping."""
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as config_file:
        data = yaml.safe_load(config_file) or {}

    if not isinstance(data, dict):
        raise ValueError(f"config file must contain a mapping: {config_path}")

    return data


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
    """Write a YAML mapping, creating the parent directory if needed."""
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as config_file:
        yaml.safe_dump(dict(data), config_file, sort_keys=False)


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
