from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]

from poolctl.config_files import load_config_with_overrides, merge_config_mappings
from poolctl.services.weather import WeatherConfig


def test_merge_config_mappings_recurses_mappings_and_replaces_lists() -> None:
    merged = merge_config_mappings(
        {
            "runtime": {
                "driver_profile": "simulated",
                "enabled_sensor_groups": ["pressures"],
            },
            "pump_timer": {
                "timezone": "America/Chicago",
                "schedules": [{"name": "base"}],
            },
        },
        {
            "runtime": {"enabled_sensor_groups": ["chemistry_loop"]},
            "pump_timer": {"schedules": [{"name": "local"}]},
        },
    )

    assert merged["runtime"]["driver_profile"] == "simulated"
    assert merged["runtime"]["enabled_sensor_groups"] == ["chemistry_loop"]
    assert merged["pump_timer"]["timezone"] == "America/Chicago"
    assert merged["pump_timer"]["schedules"] == [{"name": "local"}]


def test_load_config_with_overrides_allows_missing_local_file(tmp_path: Path) -> None:
    base_path = tmp_path / "base.yaml"
    local_path = tmp_path / "local.yaml"
    base_path.write_text(
        yaml.safe_dump({"runtime": {"driver_profile": "simulated"}}),
        encoding="utf-8",
    )

    data = load_config_with_overrides(base_path, local_path=local_path)

    assert data["runtime"]["driver_profile"] == "simulated"


def test_load_config_with_overrides_merges_local_file(tmp_path: Path) -> None:
    base_path = tmp_path / "base.yaml"
    local_path = tmp_path / "local.yaml"
    base_path.write_text(
        yaml.safe_dump(
            {
                "runtime": {
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


def test_minimal_pi_local_example_and_tracked_configs_parse() -> None:
    repository = Path(__file__).resolve().parents[1]
    local_example = yaml.safe_load(
        (repository / "configs" / "pi-local.example.yaml").read_text(encoding="utf-8")
    )
    pi_prod = yaml.safe_load(
        (repository / "configs" / "pi-prod.yaml").read_text(encoding="utf-8")
    )
    windows_dev = yaml.safe_load(
        (repository / "configs" / "windows-dev.yaml").read_text(encoding="utf-8")
    )

    assert local_example == {}
    for config in (pi_prod, windows_dev):
        assert isinstance(config, dict)
        weather = WeatherConfig.from_mapping(config)
        assert weather.enabled is False
        assert weather.latitude is None
        assert weather.longitude is None
