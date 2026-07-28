from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]

from poolctl.config_files import load_config_with_overrides, merge_config_mappings


def test_merge_config_mappings_recurses_mappings_and_replaces_lists() -> None:
    merged = merge_config_mappings(
        {
            "runtime": {
                "stage": "open_loop_timer",
                "enabled_layers": ["pump_timer"],
            },
            "pump_timer": {
                "timezone": "America/Chicago",
                "schedules": [{"name": "base"}],
            },
        },
        {
            "runtime": {"stage": "sensor_logging"},
            "pump_timer": {"schedules": [{"name": "local"}]},
        },
    )

    assert merged["runtime"]["stage"] == "sensor_logging"
    assert merged["runtime"]["enabled_layers"] == ["pump_timer"]
    assert merged["pump_timer"]["timezone"] == "America/Chicago"
    assert merged["pump_timer"]["schedules"] == [{"name": "local"}]


def test_load_config_with_overrides_allows_missing_local_file(tmp_path: Path) -> None:
    base_path = tmp_path / "base.yaml"
    local_path = tmp_path / "local.yaml"
    base_path.write_text(yaml.safe_dump({"runtime": {"stage": "base"}}), encoding="utf-8")

    data = load_config_with_overrides(base_path, local_path=local_path)

    assert data["runtime"]["stage"] == "base"


def test_load_config_with_overrides_merges_local_file(tmp_path: Path) -> None:
    base_path = tmp_path / "base.yaml"
    local_path = tmp_path / "local.yaml"
    base_path.write_text(
        yaml.safe_dump(
            {
                "runtime": {
                    "stage": "open_loop_timer",
                    "driver_profile": "raspberry_pi",
                },
                "chlorination": {
                    "enabled": True,
                    "daily_dose_oz": 10.0,
                    "pump_output_oz_per_min": 1.0,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    local_path.write_text(
        yaml.safe_dump({"chlorination": {"daily_dose_oz": 18.0}}, sort_keys=False),
        encoding="utf-8",
    )

    data = load_config_with_overrides(base_path, local_path=local_path)

    assert data["runtime"]["driver_profile"] == "raspberry_pi"
    assert data["chlorination"]["enabled"] is True
    assert data["chlorination"]["daily_dose_oz"] == 18.0
