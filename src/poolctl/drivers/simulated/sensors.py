"""
Sensor drivers that read from the simulated plant.

The service layer receives normal Measurement objects, so it cannot tell whether
these readings came from the simulator or from real Raspberry Pi hardware.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from poolctl.domain.models import (
    Measurement,
    MeasurementKind,
    Quality,
    SensorId,
)
from poolctl.drivers.simulated.plant import SimulatedPlant


class SimulatedSensor:
    """
    Generic simulated single-value sensor.

    This class is useful for sensors that produce one Measurement per read.

    It reads a value from the shared SimulatedPlant and wraps it in your
    domain Measurement model.
    """

    def __init__(
        self,
        *,
        name: str,
        sensor_id: SensorId,
        unit: str,
        read_value: Callable[[], float],
        observed_at: Callable[[], datetime] | None = None,
        kind: MeasurementKind = MeasurementKind.RAW,
        decimal_places: int = 2,
    ) -> None:
        self.name = name
        self.sensor_id = sensor_id
        self.unit = unit
        self.read_value = read_value
        self.observed_at = observed_at
        self.kind = kind
        self.decimal_places = decimal_places

    async def read(self) -> Measurement:
        value = self.read_value()

        if self.observed_at is not None:
            return Measurement(
                sensor_id=self.sensor_id,
                observed_at=self.observed_at(),
                kind=self.kind,
                value=round(value, self.decimal_places),
                unit=self.unit,
                quality=Quality.GOOD,
                metadata={"driver": self.name},
            )

        return Measurement(
            sensor_id=self.sensor_id,
            kind=self.kind,
            value=round(value, self.decimal_places),
            unit=self.unit,
            quality=Quality.GOOD,
            metadata={"driver": self.name},
        )


def build_default_simulated_sensors(plant: SimulatedPlant) -> list[SimulatedSensor]:
    """
    Build the default set of simulated sensors for your current pool system.

    These sensors are all tied to the same SimulatedPlant instance, which means
    their values are correlated.

    Example:
      - when simulated pump is off, pressure sensors read near zero
      - when simulated pump is high speed, pressure sensors read higher
      - pH/ORP probe temperatures follow water temperature
    """
    return [
        SimulatedSensor(
            name="simulated_pump_output_psi",
            sensor_id=SensorId.PUMP_OUTPUT_PSI,
            unit="psi",
            read_value=lambda: plant.pressure_psi("pump_output_psi"),
            observed_at=plant.clock.now,
            decimal_places=2,
        ),
        SimulatedSensor(
            name="simulated_filter_output_psi",
            sensor_id=SensorId.FILTER_OUTPUT_PSI,
            unit="psi",
            read_value=lambda: plant.pressure_psi("filter_output_psi"),
            observed_at=plant.clock.now,
            decimal_places=2,
        ),
        SimulatedSensor(
            name="simulated_return_psi",
            sensor_id=SensorId.RETURN_PSI,
            unit="psi",
            read_value=lambda: plant.pressure_psi("return_psi"),
            observed_at=plant.clock.now,
            decimal_places=2,
        ),
        SimulatedSensor(
            name="simulated_bubbler_psi",
            sensor_id=SensorId.BUBBLER_PSI,
            unit="psi",
            read_value=lambda: plant.pressure_psi("bubbler_psi"),
            observed_at=plant.clock.now,
            decimal_places=2,
        ),
        SimulatedSensor(
            name="simulated_booster_psi",
            sensor_id=SensorId.BOOSTER_PSI,
            unit="psi",
            read_value=lambda: plant.pressure_psi("booster_psi"),
            observed_at=plant.clock.now,
            decimal_places=2,
        ),
        SimulatedSensor(
            name="simulated_raw_orp",
            sensor_id=SensorId.RAW_ORP,
            unit="mV",
            read_value=plant.raw_orp_mv,
            observed_at=plant.clock.now,
            decimal_places=1,
        ),
        SimulatedSensor(
            name="simulated_orp_temp",
            sensor_id=SensorId.ORP_TEMP,
            unit="degF",
            read_value=plant.orp_probe_temp_f,
            observed_at=plant.clock.now,
            decimal_places=2,
        ),
        SimulatedSensor(
            name="simulated_raw_ph",
            sensor_id=SensorId.RAW_PH,
            unit="pH",
            read_value=plant.raw_ph,
            observed_at=plant.clock.now,
            decimal_places=2,
        ),
        SimulatedSensor(
            name="simulated_ph_temp",
            sensor_id=SensorId.PH_TEMP,
            unit="degF",
            read_value=plant.ph_probe_temp_f,
            observed_at=plant.clock.now,
            decimal_places=2,
        ),
        SimulatedSensor(
            name="simulated_raw_ph_voltage",
            sensor_id=SensorId.RAW_PH_VOLTAGE,
            unit="V",
            read_value=plant.raw_ph_voltage,
            observed_at=plant.clock.now,
            decimal_places=3,
        ),
        SimulatedSensor(
            name="simulated_temp",
            sensor_id=SensorId.TEMP,
            unit="degF",
            read_value=plant.measured_water_temp_f,
            observed_at=plant.clock.now,
            decimal_places=2,
        ),
        SimulatedSensor(
            name="simulated_tank_level",
            sensor_id=SensorId.TANK_LEVEL,
            unit="percent",
            read_value=plant.tank_level,
            observed_at=plant.clock.now,
            decimal_places=1,
        ),
    ]
