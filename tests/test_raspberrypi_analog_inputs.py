from __future__ import annotations

from datetime import datetime, timezone

import pytest

from poolctl.domain.models import SensorId
from poolctl.drivers.raspberrypi.analog_inputs import (
    WaveshareAnalogInput8ChDriver,
    WaveshareAnalogInputConfig,
    build_waveshare_analog_driver_from_mapping,
)
from poolctl.services.clock import SimulatedClock


class FakeAnalogTransport:
    def __init__(self, registers: tuple[int, ...]) -> None:
        self.registers = registers
        self.reads: list[tuple[int, int]] = []

    async def read_input_registers(
        self,
        *,
        start_address: int,
        count: int,
    ) -> tuple[int, ...]:
        self.reads.append((start_address, count))
        return self.registers[:count]


def make_clock() -> SimulatedClock:
    return SimulatedClock(
        start_at=datetime(2026, 5, 22, 12, 0, tzinfo=timezone.utc),
    )


def analog_mapping() -> dict[str, object]:
    return {
        "modbus_analog_input": {
            "port": "/dev/ttyUSB0",
            "slave_id": 4,
            "baudrate": 9600,
            "timeout_s": 1.0,
            "raw_to_volts_scale": 0.001,
            "sensors": {
                "pump_output_psi": {
                    "channel": 1,
                    "calibration": {
                        "voltage_1": 0.0,
                        "value_1": 0.0,
                        "voltage_2": 5.0,
                        "value_2": 30.0,
                    },
                },
                "raw_ph": {
                    "channel": 2,
                    "calibration": {
                        "voltage_1": 0.0,
                        "value_1": 0.0,
                        "voltage_2": 5.0,
                        "value_2": 14.0,
                    },
                },
            },
        }
    }


def test_waveshare_analog_config_parses_channels_and_calibration() -> None:
    config = WaveshareAnalogInputConfig.from_mapping(analog_mapping())

    assert config.device.slave_id == 4
    assert len(config.sensors) == 2
    assert config.sensors[0].sensor_id == SensorId.PUMP_OUTPUT_PSI
    assert config.sensors[1].sensor_id == SensorId.RAW_PH


@pytest.mark.asyncio
async def test_waveshare_analog_driver_emits_calibrated_measurements() -> None:
    config = WaveshareAnalogInputConfig.from_mapping(analog_mapping())
    transport = FakeAnalogTransport((2500, 2800, 0, 0, 0, 0, 0, 0))
    driver = WaveshareAnalogInput8ChDriver(
        transport=transport,
        clock=make_clock(),
        config=config,
    )

    measurements = await driver.read_all()

    assert transport.reads == [(0x0000, 8)]
    by_sensor = {measurement.sensor_id: measurement for measurement in measurements}

    assert by_sensor[SensorId.PUMP_OUTPUT_PSI].value == 15.0
    assert by_sensor[SensorId.PUMP_OUTPUT_PSI].unit == "psi"
    assert by_sensor[SensorId.RAW_PH].value == 7.84
    assert by_sensor[SensorId.RAW_PH].unit == "pH"
    assert by_sensor[SensorId.RAW_PH_VOLTAGE].value == 2.8
    assert by_sensor[SensorId.RAW_PH_VOLTAGE].unit == "V"


def test_build_waveshare_analog_driver_returns_none_without_sensor_map() -> None:
    assert build_waveshare_analog_driver_from_mapping({}, clock=make_clock()) is None
