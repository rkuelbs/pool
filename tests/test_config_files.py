from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import yaml  # type: ignore[import-untyped]
import pytest

from poolctl.config_files import (
    load_config_mapping,
    load_config_with_overrides,
    merge_config_mappings,
    normalize_config_mapping,
    save_config_mapping,
)
from poolctl.services.pump_timer import PumpTimerConfig, ScheduleResolver
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
        assert config["site"]["latitude"] == 45.0
        assert config["site"]["longitude"] == -90.0
        weather = WeatherConfig.from_mapping(config)
        assert weather.enabled is False
        assert weather.latitude == 45.0
        assert weather.longitude == -90.0

    timer_config = PumpTimerConfig.from_mapping(windows_dev)
    resolved = ScheduleResolver().resolve_day(timer_config, date(2026, 6, 1))
    assert resolved.warnings == ()
    assert resolved.sunrise is not None
    assert resolved.sunset is not None
    afternoon_low = next(
        window for window in resolved.windows if window.event_name == "afternoon_low"
    )
    sunset_high = next(
        window for window in resolved.windows if window.event_name == "sunset_high"
    )
    assert afternoon_low.end == resolved.sunset
    assert afternoon_low.start == resolved.sunset - timedelta(hours=3)
    assert sunset_high.start == resolved.sunset
    assert sunset_high.end == resolved.sunset + timedelta(hours=1)

    schedules = windows_dev["pump_timer"]["profiles"][0]["schedules"]
    mode_fields = {
        (
            schedule["pump_speed"],
            schedule["booster"],
            schedule["allow_dosing"],
        )
        for schedule in schedules
    }
    assert mode_fields == {
        ("low", "off", False),
        ("high", "off", False),
        ("low", "off", True),
        ("low", "on", False),
    }

    pi_limits = pi_prod["monitoring"]["limits"]
    windows_limits = windows_dev["monitoring"]["limits"]
    for signal_id, limits in pi_limits.items():
        assert windows_limits[signal_id] == limits
    assert windows_dev["notifications"]["rules"] == pi_prod["notifications"]["rules"]
    canonical_boundaries = {
        "alarm_below",
        "caution_below",
        "caution_above",
        "alarm_above",
    }
    for limits in windows_limits.values():
        assert set(limits) <= canonical_boundaries


def test_legacy_owners_migrate_to_canonical_config_without_value_changes() -> None:
    normalized = normalize_config_mapping(
        {
            "fc_demand": {
                "pool_volume_gal": 16321.0,
                "chlorine_strength_percent": 10.5,
                "target_fc_ppm": 4.5,
            },
            "live_view": {
                "sensor_limits": {
                    "raw_ph": {
                        "caution_min": 6.7,
                        "normal_min": 7.1,
                        "normal_max": 7.9,
                        "caution_max": 8.3,
                    }
                }
            },
            "filter_loading": {
                "yellow_flow_loss_percent": 11.0,
                "red_flow_loss_percent": 17.0,
            },
            "notifications": {
                "alerts": {
                    "chlorine_tank": {
                        "enabled": True,
                        "warning_below": 2.5,
                        "caution_below": 6.5,
                        "warning_repeat_minutes": 30,
                    }
                }
            },
        }
    )

    assert normalized["pool"]["volume_gal"] == 16321.0
    assert normalized["chlorination"]["chlorine_strength_percent"] == 10.5
    assert normalized["fc_demand"] == {"target_fc_ppm": 4.5}
    assert normalized["monitoring"]["limits"]["raw_ph"] == {
        "alarm_below": 6.7,
        "caution_below": 7.1,
        "caution_above": 7.9,
        "alarm_above": 8.3,
    }
    assert normalized["monitoring"]["limits"]["filter_flow_loss_percent"] == {
        "caution_above": 11.0,
        "alarm_above": 17.0,
    }
    assert normalized["monitoring"]["limits"]["chlorine_tank_days_remaining"] == {
        "alarm_below": 2.5,
        "caution_below": 6.5,
    }
    assert normalized["notifications"]["rules"]["chlorine_tank_days_remaining"][
        "enabled"
    ] is True
    assert "alerts" not in normalized["notifications"]
    assert "live_view" not in normalized
    assert "filter_loading" not in normalized


def test_canonical_value_wins_over_legacy_value_in_same_layer() -> None:
    normalized = normalize_config_mapping(
        {
            "pool": {"volume_gal": 12000.0},
            "chlorination": {"chlorine_strength_percent": 12.5},
            "fc_demand": {
                "pool_volume_gal": 9000.0,
                "chlorine_strength_percent": 10.0,
            },
            "monitoring": {
                "limits": {
                    "raw_ph": {
                        "caution_below": 7.25,
                    }
                }
            },
            "live_view": {
                "sensor_limits": {
                    "raw_ph": {
                        "normal_min": 7.1,
                    }
                }
            },
        }
    )

    assert normalized["pool"]["volume_gal"] == 12000.0
    assert normalized["chlorination"]["chlorine_strength_percent"] == 12.5
    assert normalized["monitoring"]["limits"]["raw_ph"]["caution_below"] == 7.25


def test_conflicting_legacy_thresholds_fail_clearly() -> None:
    with pytest.raises(ValueError, match="conflicting legacy values"):
        normalize_config_mapping(
            {
                "filter_loading": {"yellow_flow_loss_percent": 10.0},
                "notifications": {
                    "alerts": {
                        "filter_flow_loss": {"caution_above": 12.0},
                    }
                },
            }
        )


def test_legacy_local_override_beats_base_canonical_value(tmp_path: Path) -> None:
    base_path = tmp_path / "base.yaml"
    local_path = tmp_path / "local.yaml"
    base_path.write_text(
        yaml.safe_dump({"pool": {"volume_gal": 16000.0}}),
        encoding="utf-8",
    )
    local_path.write_text(
        yaml.safe_dump({"fc_demand": {"pool_volume_gal": 17500.0}}),
        encoding="utf-8",
    )

    loaded = load_config_with_overrides(base_path, local_path=local_path)

    assert loaded["pool"]["volume_gal"] == 17500.0
    assert "pool_volume_gal" not in loaded.get("fc_demand", {})


def test_save_serializes_only_canonical_owners(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    save_config_mapping(
        path,
        {
            "fc_demand": {
                "pool_volume_gal": 14500.0,
                "chlorine_strength_percent": 11.0,
            },
            "filter_loading": {
                "yellow_flow_loss_percent": 9.0,
                "red_flow_loss_percent": 14.0,
            },
        },
    )

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["pool"]["volume_gal"] == 14500.0
    assert raw["chlorination"]["chlorine_strength_percent"] == 11.0
    assert "pool_volume_gal" not in raw.get("fc_demand", {})
    assert "chlorine_strength_percent" not in raw.get("fc_demand", {})
    assert "filter_loading" not in raw
    assert load_config_mapping(path) == raw
