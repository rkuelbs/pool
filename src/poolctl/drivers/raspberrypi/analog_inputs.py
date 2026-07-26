from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from poolctl.domain.models import Measurement, MeasurementKind, Quality, SensorId
from poolctl.drivers.modbus.registers import (
    ModbusRegisterDeviceConfig,
    ModbusRegisterTransport,
    PymodbusRtuRegisterTransport,
)
from poolctl.drivers.modbus.rtu_bus import SharedModbusRtuBus
from poolctl.services.clock import Clock


SUPPORTED_ANALOG_SENSOR_IDS = {
    SensorId.PUMP_OUTPUT_PSI,
    SensorId.FILTER_OUTPUT_PSI,
    SensorId.RETURN_PSI,
    SensorId.BUBBLER_PSI,
    SensorId.BOOSTER_PSI,
    SensorId.RAW_PH,
}
CHANNEL_MODE_REGISTER_BASE = 0x1000
CHANNEL_COUNT = 8


@dataclass(frozen=True)
class TwoPointCalibration:
    """
    Linear mapping from volts to engineering units.
    """

    voltage_1: float
    value_1: float
    voltage_2: float
    value_2: float

    def __post_init__(self) -> None:
        if self.voltage_1 == self.voltage_2:
            raise ValueError("calibration voltage_1 and voltage_2 must differ")

    def apply(self, volts: float) -> float:
        slope = (self.value_2 - self.value_1) / (self.voltage_2 - self.voltage_1)
        return self.value_1 + (volts - self.voltage_1) * slope


@dataclass(frozen=True)
class AnalogChannelConfig:
    """
    Mapping for one logical sensor from one physical analog channel.
    """

    sensor_id: SensorId
    channel: int
    calibration: TwoPointCalibration

    def __post_init__(self) -> None:
        if self.channel < 1 or self.channel > 8:
            raise ValueError("analog channel must be between 1 and 8")


@dataclass(frozen=True)
class WaveshareAnalogInputConfig:
    """
    Waveshare 8-channel analog Modbus input settings.

    `raw_to_volts_scale` converts raw register values to volts:
      volts = raw_register * raw_to_volts_scale + raw_to_volts_offset

    Common defaults:
      - 0.0005 when module channel mode is 0-5V and registers are reported in mV
      - 0.001 when module channel mode is 0-10V and registers are reported in mV
      - (10.0 / 4095.0) when registers are AD code for a 0-10V range
    """

    device: ModbusRegisterDeviceConfig
    raw_to_volts_scale: float = 0.0005
    raw_to_volts_offset: float = 0.0
    startup_channel_mode: int | None = None
    sensors: tuple[AnalogChannelConfig, ...] = ()

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> WaveshareAnalogInputConfig:
        section = _mapping_value(data, "modbus_analog_input", default={})
        sensor_map = _mapping_value(section, "sensors", default={})

        sensors: list[AnalogChannelConfig] = []
        for raw_sensor_id, raw_sensor_config in sensor_map.items():
            if not isinstance(raw_sensor_id, str):
                raise ValueError("modbus_analog_input.sensors keys must be sensor ids")
            if not isinstance(raw_sensor_config, Mapping):
                raise ValueError(
                    f"modbus_analog_input.sensors.{raw_sensor_id} must be a mapping"
                )

            sensor_id = SensorId(raw_sensor_id)
            if sensor_id not in SUPPORTED_ANALOG_SENSOR_IDS:
                raise ValueError(
                    f"unsupported analog sensor id {sensor_id.value}; "
                    f"supported: {', '.join(sorted(item.value for item in SUPPORTED_ANALOG_SENSOR_IDS))}"
                )

            calibration_data = _mapping_value(
                raw_sensor_config,
                "calibration",
                default={},
            )
            sensors.append(
                AnalogChannelConfig(
                    sensor_id=sensor_id,
                    channel=_required_int_value(raw_sensor_config, "channel"),
                    calibration=TwoPointCalibration(
                        voltage_1=_required_float_value(calibration_data, "voltage_1"),
                        value_1=_required_float_value(calibration_data, "value_1"),
                        voltage_2=_required_float_value(calibration_data, "voltage_2"),
                        value_2=_required_float_value(calibration_data, "value_2"),
                    ),
                )
            )

        return cls(
            device=ModbusRegisterDeviceConfig.from_mapping(
                data,
                "modbus_analog_input",
                default_slave_id=4,
            ),
            raw_to_volts_scale=_float_value(section, "raw_to_volts_scale", 0.0005),
            raw_to_volts_offset=_float_value(section, "raw_to_volts_offset", 0.0),
            startup_channel_mode=_optional_int_value(section, "startup_channel_mode"),
            sensors=tuple(sensors),
        )


class WaveshareAnalogInput8ChDriver:
    """
    Multi-sensor driver for Waveshare Modbus RTU Analog Input 8CH.
    """

    name = "waveshare_modbus_analog_input_8ch"

    def __init__(
        self,
        *,
        transport: ModbusRegisterTransport,
        clock: Clock,
        config: WaveshareAnalogInputConfig,
    ) -> None:
        self._transport = transport
        self._clock = clock
        self._config = config
        self._startup_mode_applied = False

    @property
    def sensor_ids(self) -> tuple[SensorId, ...]:
        sensor_ids = [sensor.sensor_id for sensor in self._config.sensors]
        if SensorId.RAW_PH in sensor_ids:
            sensor_ids.append(SensorId.RAW_PH_VOLTAGE)
        return tuple(sensor_ids)

    async def read_all(self) -> list[Measurement]:
        await self._apply_startup_channel_mode()
        registers = await self._transport.read_input_registers(
            start_address=0x0000,
            count=8,
        )
        observed_at = self._clock.now()

        measurements: list[Measurement] = []
        raw_ph_voltage: float | None = None
        raw_ph_metadata: dict[str, Any] | None = None
        slave_id = self._config.device.slave_id

        for sensor in self._config.sensors:
            register_value = registers[sensor.channel - 1]
            voltage = (
                register_value * self._config.raw_to_volts_scale
                + self._config.raw_to_volts_offset
            )
            calibrated_value = sensor.calibration.apply(voltage)

            metadata = {
                "driver": self.name,
                "modbus_slave_id": slave_id,
                "channel": sensor.channel,
                "raw_register": register_value,
                "raw_voltage": round(voltage, 6),
                "calibration": {
                    "voltage_1": sensor.calibration.voltage_1,
                    "value_1": sensor.calibration.value_1,
                    "voltage_2": sensor.calibration.voltage_2,
                    "value_2": sensor.calibration.value_2,
                },
            }

            if sensor.sensor_id == SensorId.RAW_PH:
                unit = "pH"
                rounded_value = round(calibrated_value, 2)
                raw_ph_voltage = voltage
                raw_ph_metadata = metadata
            else:
                unit = "psi"
                rounded_value = round(calibrated_value, 2)

            measurements.append(
                Measurement(
                    sensor_id=sensor.sensor_id,
                    observed_at=observed_at,
                    kind=MeasurementKind.RAW,
                    value=rounded_value,
                    unit=unit,
                    quality=Quality.GOOD,
                    metadata=metadata,
                )
            )

        if raw_ph_voltage is not None:
            measurements.append(
                Measurement(
                    sensor_id=SensorId.RAW_PH_VOLTAGE,
                    observed_at=observed_at,
                    kind=MeasurementKind.RAW,
                    value=round(raw_ph_voltage, 4),
                    unit="V",
                    quality=Quality.GOOD,
                    metadata={
                        **(raw_ph_metadata or {}),
                        "derived_from": SensorId.RAW_PH.value,
                    },
                )
            )

        return measurements

    async def _apply_startup_channel_mode(self) -> None:
        startup_mode = self._config.startup_channel_mode
        if startup_mode is None or self._startup_mode_applied:
            return

        if startup_mode < 0 or startup_mode > 0xFFFF:
            raise ValueError("startup_channel_mode must be between 0 and 65535")

        for channel_index in range(CHANNEL_COUNT):
            await self._transport.write_holding_register(
                register_address=CHANNEL_MODE_REGISTER_BASE + channel_index,
                value=startup_mode,
            )
        self._startup_mode_applied = True


def build_waveshare_analog_driver_from_mapping(
    data: Mapping[str, Any],
    *,
    clock: Clock,
    bus: SharedModbusRtuBus | None = None,
) -> WaveshareAnalogInput8ChDriver | None:
    config = WaveshareAnalogInputConfig.from_mapping(data)
    if not config.sensors:
        return None

    return WaveshareAnalogInput8ChDriver(
        transport=PymodbusRtuRegisterTransport(config.device, bus=bus),
        clock=clock,
        config=config,
    )


def _mapping_value(
    data: Mapping[str, Any],
    key: str,
    *,
    default: Mapping[str, Any],
) -> Mapping[str, Any]:
    value = data.get(key, default)
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be a mapping")
    return value


def _required_int_value(data: Mapping[str, Any], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _required_float_value(data: Mapping[str, Any], key: str) -> float:
    value = data.get(key)
    if not isinstance(value, int | float):
        raise ValueError(f"{key} must be a number")
    return float(value)


def _float_value(data: Mapping[str, Any], key: str, default: float) -> float:
    value = data.get(key, default)
    if not isinstance(value, int | float):
        raise ValueError(f"{key} must be a number")
    return float(value)


def _optional_int_value(data: Mapping[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value
