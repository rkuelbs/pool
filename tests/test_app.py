from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from poolctl.app import build_app_from_mapping
from poolctl.config import DriverProfile, FeatureLayer, RuntimeStage
from poolctl.domain.models import (
    ActuatorCommand,
    ActuatorId,
    ActuatorState,
    CommandSource,
    LabTest,
    Measurement,
    Quality,
    SensorId,
)
from poolctl.drivers.simulated.actuators import build_default_simulated_actuators
from poolctl.drivers.simulated.plant import SimulatedPlant
from poolctl.services.clock import SimulatedClock


class FixedSensor:
    def __init__(
        self,
        *,
        name: str,
        sensor_id: SensorId,
        clock: SimulatedClock,
        value: float,
        unit: str = "psi",
    ) -> None:
        self.name = name
        self.sensor_id = sensor_id
        self._clock = clock
        self._value = value
        self._unit = unit

    async def read(self) -> Measurement:
        return Measurement(
            sensor_id=self.sensor_id,
            observed_at=self._clock.now(),
            value=self._value,
            unit=self._unit,
            quality=Quality.GOOD,
            metadata={"driver": self.name},
        )


def make_clock() -> SimulatedClock:
    return SimulatedClock(
        start_at=datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc),
        speedup=3600.0,
    )


def minimal_acquisition_config() -> dict[str, object]:
    return {
        "acquisition": {
            "groups": {
                "pressures": {
                    "sensor_ids": ["pump_output_psi"],
                    "read_interval_s": 0.5,
                    "log_interval_s": 30.0,
                    "requires_pump_flow": False,
                    "oversample": {
                        "sample_count": 1,
                        "sample_interval_s": 0.0,
                        "reducer": "last",
                    },
                }
            }
        }
    }


def active_pump_timer_config() -> dict[str, object]:
    return {
        "pump_timer": {
            "schedules": [
                {
                    "name": "all_day_filter",
                    "start": "00:00",
                    "end": "00:00",
                    "pump_speed": "high",
                    "booster": "off",
                }
            ]
        }
    }


def simulated_runtime_config() -> dict[str, object]:
    return {
        "runtime": {
            "stage": "windows_simulation",
            "driver_profile": "simulated",
            "enabled_layers": ["acquisition", "safety_enforcement"],
            "enabled_actuators": [
                "pump_motor",
                "pump_motor_speed",
                "booster_pump",
                "chlorine_dosing_pump",
            ],
            "enabled_sensor_groups": ["pressures"],
        }
    }


@pytest.mark.asyncio
async def test_build_simulated_app_wires_acquisition_and_router() -> None:
    clock = make_clock()
    config = {
        **simulated_runtime_config(),
        **minimal_acquisition_config(),
    }

    app = build_app_from_mapping(config, clock=clock)
    result = await app.tick(force_acquisition=True)

    assert app.runtime_config.stage == RuntimeStage.WINDOWS_SIMULATION
    assert app.runtime_config.driver_profile == DriverProfile.SIMULATED
    assert app.runtime_config.layer_enabled(FeatureLayer.ACQUISITION)
    assert app.acquisition_service is not None
    assert app.simulated_plant is not None
    assert result.acquisition.group_names == ("pressures",)
    assert [measurement.sensor_id for measurement in result.measurements] == [
        SensorId.PUMP_OUTPUT_PSI
    ]


@pytest.mark.asyncio
async def test_open_loop_timer_stage_can_run_without_acquisition() -> None:
    clock = make_clock()
    config = {
        "runtime": {
            "stage": "open_loop_timer",
            "driver_profile": "simulated",
            "enabled_layers": ["pump_timer", "safety_enforcement"],
            "enabled_actuators": [
                "pump_motor",
                "pump_motor_speed",
                "booster_pump",
            ],
            "enabled_sensor_groups": [],
        },
        **active_pump_timer_config(),
    }

    app = build_app_from_mapping(config, clock=clock)
    result = await app.tick()

    assert app.acquisition_service is None
    assert result.measurements == ()
    assert result.loggable_measurements == ()
    assert len(result.timer_results) == 2
    assert app.router.actuator_states[ActuatorId.PUMP_MOTOR] == ActuatorState.ON
    assert app.router.actuator_states[ActuatorId.PUMP_MOTOR_SPEED] == ActuatorState.HIGH

    await clock.advance(31.0)
    later_result = await app.tick()

    assert later_result.safety_results == ()
    assert not app.router.safety_gate.locked_out

    chlorine_result = await app.router.route(
        ActuatorCommand(
            actuator_id=ActuatorId.CHLORINE_DOSING_PUMP,
            created_at=clock.now(),
            state=ActuatorState.ON,
            requested_by=CommandSource.MANUAL,
            reason="should not be available in open loop timer stage",
        )
    )

    assert not chlorine_result.accepted
    assert chlorine_result.rejection_reason == (
        "no driver registered for chlorine_dosing_pump"
    )


def modbus_relay_config() -> dict[str, object]:
    return {
        "modbus_relay": {
            "port": "/dev/ttyUSB0",
            "slave_id": 1,
            "baudrate": 9600,
            "timeout_s": 1.0,
            "relays": {
                "pump_motor": 1,
                "pump_motor_speed": 2,
                "booster_pump": 3,
                "chlorine_dosing_pump": 4,
            },
            "pump_speed_relay": {
                "low_state": "on",
                "high_state": "off",
            },
        }
    }


def test_raspberry_pi_profile_can_use_injected_drivers() -> None:
    clock = make_clock()
    plant = SimulatedPlant(clock=clock)
    config = {
        "runtime": {
            "stage": "open_loop_timer",
            "driver_profile": "raspberry_pi",
            "enabled_layers": ["pump_timer", "safety_enforcement"],
            "enabled_actuators": [
                "pump_motor",
                "pump_motor_speed",
                "booster_pump",
            ],
            "enabled_sensor_groups": [],
        }
    }

    app = build_app_from_mapping(
        config,
        clock=clock,
        actuator_drivers=build_default_simulated_actuators(plant),
    )

    assert app.runtime_config.driver_profile == DriverProfile.RASPBERRY_PI
    assert app.simulated_plant is None
    assert app.acquisition_service is None


def test_raspberry_pi_profile_builds_modbus_relay_actuators_from_config() -> None:
    clock = make_clock()
    config = {
        "runtime": {
            "stage": "open_loop_timer",
            "driver_profile": "raspberry_pi",
            "enabled_actuators": [
                "pump_motor",
                "pump_motor_speed",
                "booster_pump",
            ],
            "enabled_sensor_groups": [],
        },
        **modbus_relay_config(),
    }

    app = build_app_from_mapping(config, clock=clock)

    assert app.runtime_config.driver_profile == DriverProfile.RASPBERRY_PI
    assert app.simulated_plant is None
    assert app.acquisition_service is None


def test_raspberry_pi_sensor_logging_stage_builds_modbus_sensor_drivers(
    tmp_path: Path,
) -> None:
    clock = make_clock()
    config = {
        "runtime": {
            "stage": "sensor_logging",
            "driver_profile": "raspberry_pi",
            "enabled_layers": ["pump_timer", "acquisition", "logging"],
            "enabled_actuators": [
                "pump_motor",
                "pump_motor_speed",
                "booster_pump",
            ],
            "enabled_sensor_groups": ["chemistry_loop"],
        },
        "acquisition": {
            "groups": {
                "chemistry_loop": {
                    "sensor_ids": [
                        "raw_orp",
                        "orp_temp",
                        "raw_ph",
                        "raw_ph_voltage",
                    ],
                    "read_interval_s": 5.0,
                    "log_interval_s": 120.0,
                    "requires_pump_flow": True,
                    "min_pump_on_seconds": 60.0,
                }
            }
        },
        "logging": {
            "database_path": str(tmp_path / "measurements.sqlite3"),
        },
        **modbus_relay_config(),
        "modbus_ph_sensor": {
            "port": "/dev/ttyUSB0",
            "slave_id": 2,
            "baudrate": 9600,
            "timeout_s": 1.0,
        },
        "modbus_orp_sensor": {
            "port": "/dev/ttyUSB0",
            "slave_id": 3,
            "baudrate": 9600,
            "timeout_s": 1.0,
        },
    }

    app = build_app_from_mapping(config, clock=clock)

    assert app.runtime_config.driver_profile == DriverProfile.RASPBERRY_PI
    assert app.acquisition_service is not None
    assert app.acquisition_config.groups[0].name == "chemistry_loop"


@pytest.mark.asyncio
async def test_tick_feeds_acquisition_measurements_into_safety_enforcement() -> None:
    clock = make_clock()
    sensor = FixedSensor(
        name="overpressure_sensor",
        sensor_id=SensorId.PUMP_OUTPUT_PSI,
        clock=clock,
        value=31.0,
    )
    config = {
        **simulated_runtime_config(),
        **minimal_acquisition_config(),
    }

    app = build_app_from_mapping(
        config,
        clock=clock,
        sensor_drivers=[sensor],
    )
    result = await app.tick(force_acquisition=True)

    assert len(result.measurements) == 1
    assert app.router.safety_gate.locked_out
    assert app.router.safety_gate.active_fault is not None
    assert app.router.safety_gate.active_fault.code == "pump_output_overpressure"
    assert {safety_result.metadata["safety_action"] for safety_result in result.safety_results} == {
        "pump_output_overpressure"
    }


@pytest.mark.asyncio
async def test_chemistry_sampling_refresh_triggers_pump_run_after_long_off_time() -> None:
    clock = make_clock()
    config = {
        **simulated_runtime_config(),
        **minimal_acquisition_config(),
        "runtime": {
            "stage": "sensor_logging",
            "driver_profile": "simulated",
            "enabled_layers": ["pump_timer", "acquisition", "safety_enforcement"],
            "enabled_actuators": [
                "pump_motor",
                "pump_motor_speed",
                "booster_pump",
                "chlorine_dosing_pump",
            ],
            "enabled_sensor_groups": ["pressures"],
        },
        "pump_timer": {
            "timezone": "UTC",
            "schedules": [],
        },
        "acquisition": {
            **minimal_acquisition_config()["acquisition"],  # type: ignore[index]
            "chemistry_sampling_refresh": {
                "enabled": True,
                "max_pump_off_s": 1.0,
                "run_duration_s": 60.0,
                "pump_speed": "high",
            },
        },
    }

    app = build_app_from_mapping(config, clock=clock)
    await app.tick(force_acquisition=True)
    await clock.advance(2.0)
    second = await app.tick(force_acquisition=True)

    assert any(
        result.applied and app.router.actuator_states.get(ActuatorId.PUMP_MOTOR) == ActuatorState.ON
        for result in second.timer_results
    )
    assert app.active_sample_timer_override() is not None


@pytest.mark.asyncio
async def test_tick_computes_csi_from_valid_live_temp_ph_and_latest_sparse_lab_values(
    tmp_path: Path,
) -> None:
    clock = make_clock()
    temp_sensor = FixedSensor(
        name="temp_sensor",
        sensor_id=SensorId.TEMP,
        clock=clock,
        value=84.0,
        unit="degF",
    )
    ph_sensor = FixedSensor(
        name="ph_sensor",
        sensor_id=SensorId.RAW_PH,
        clock=clock,
        value=7.5,
        unit="pH",
    )
    config = {
        "runtime": {
            "stage": "sensor_logging",
            "driver_profile": "simulated",
            "enabled_layers": ["acquisition", "logging", "safety_enforcement"],
            "enabled_actuators": [
                "pump_motor",
                "pump_motor_speed",
                "booster_pump",
                "chlorine_dosing_pump",
            ],
            "enabled_sensor_groups": ["chemistry_loop"],
        },
        "acquisition": {
            "groups": {
                "chemistry_loop": {
                    "sensor_ids": ["temp", "raw_ph"],
                    "read_interval_s": 1.0,
                    "log_interval_s": 1.0,
                    "requires_pump_flow": False,
                    "oversample": {
                        "sample_count": 1,
                        "sample_interval_s": 0.0,
                        "reducer": "last",
                    },
                }
            }
        },
        "logging": {
            "database_path": str(tmp_path / "measurements.sqlite3"),
        },
    }
    app = build_app_from_mapping(config, clock=clock, sensor_drivers=[temp_sensor, ph_sensor])
    assert app.measurement_logger is not None

    app.measurement_logger.log_lab_test(
        LabTest(sampled_at=clock.now(), alkalinity=100.0)
    )
    app.measurement_logger.log_lab_test(
        LabTest(sampled_at=clock.now(), calcium_hardness=300.0)
    )
    app.measurement_logger.log_lab_test(
        LabTest(sampled_at=clock.now(), tds=1000.0)
    )

    tick = await app.tick(force_acquisition=True)

    assert tick.csi_measurement is not None
    assert tick.csi_measurement.sensor_id == SensorId.CALCIUM_SATURATION_INDEX
    assert abs(tick.csi_measurement.value - 0.1211) < 0.02

    records = app.measurement_logger.history(
        sensor_id=SensorId.CALCIUM_SATURATION_INDEX,
        limit=10,
    )
    assert len(records) == 1
