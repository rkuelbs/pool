"""
Abstract driver interfaces for sensors and actuators.

Services call these protocols instead of concrete hardware classes. That keeps
controller logic testable on Windows and lets Raspberry Pi drivers be swapped in
only at the edge of the application.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from poolctl.domain.models import (
    ActuatorCommand,
    ActuatorId,
    ActuatorStateSample,
    Measurement,
    SensorId,
)


class DriverError(Exception):
    """
    Base exception for driver-related failures.

    Sensor and actuator drivers should raise DriverError, or a subclass of it,
    when something goes wrong at the hardware or driver boundary.
    """


class SensorReadError(DriverError):
    """
    Raised when a sensor driver fails to produce a valid reading.

    Examples:
      - ADC read failure
      - I2C communication failure
      - serial timeout
      - sensor response cannot be parsed
    """


class ActuatorError(DriverError):
    """
    Raised when an actuator driver fails to apply a command or read state.

    Examples:
      - GPIO output failure
      - PWM driver failure
      - relay board communication failure
      - invalid actuator state for this driver
    """


@runtime_checkable
class SensorDriver(Protocol):
    """
    Interface that all sensor drivers must implement.

    A sensor driver may represent:
      - a real Raspberry Pi hardware sensor
      - a simulated sensor on Windows
      - a test/mock sensor
      - a future sensor connected over another interface

    The acquisition service should depend on this protocol, not on specific
    hardware classes.
    """

    name: str
    sensor_id: SensorId

    async def read(self) -> Measurement:
        """
        Read the sensor and return one Measurement.

        The returned Measurement should identify:
          - which sensor produced it
          - when it was observed
          - whether it is raw, calibrated, estimated, or manual
          - the value and unit
          - the quality of the reading

        Drivers should normally return MeasurementKind.RAW for direct hardware
        readings. Calibration and estimation should usually happen in later
        processing stages, not inside the low-level hardware driver.
        """
        ...


@runtime_checkable
class MultiSensorDriver(Protocol):
    """
    Interface for hardware devices that produce multiple measurements at once.

    Example:
      - a pH circuit that reports raw pH signal and temperature
      - an ORP circuit that reports raw ORP and temperature
      - a pressure board with multiple ADC channels

    Use this when a single hardware transaction naturally returns multiple
    sensor values.
    """

    name: str

    async def read_all(self) -> list[Measurement]:
        """
        Read one hardware device and return all measurements it produced.
        """
        ...


@runtime_checkable
class ActuatorDriver(Protocol):
    """
    Interface that all actuator drivers must implement.

    An actuator driver may represent:
      - a relay output
      - a GPIO-controlled pump output
      - a two-speed pump control
      - a simulated actuator on Windows

    The command router should depend on this protocol, not on specific hardware.
    """

    name: str
    actuator_id: ActuatorId

    async def apply(self, command: ActuatorCommand) -> ActuatorStateSample:
        """
        Apply an actuator command and return the resulting actuator state sample.

        This method should not decide high-level safety policy. Safety decisions
        belong in the safety gate / command router before the command reaches
        the driver.

        However, the driver may still reject commands that are physically
        impossible for that actuator.

        Example:
          - pump motor accepts ON/OFF
          - pump speed accepts LOW/HIGH
          - chlorine dosing pump accepts ON/OFF
        """
        ...

    async def read_state(self) -> ActuatorStateSample:
        """
        Return the current known or observed actuator state.

        For simple GPIO relay outputs, this may be the last commanded state.
        For more advanced hardware, this could eventually read feedback from
        the device.
        """
        ...

    async def stop(self) -> ActuatorStateSample:
        """
        Put the actuator into its safest normal inactive state.

        For most outputs, this should mean OFF.

        For pump speed, this may mean LOW or OFF depending on how the actual
        pump speed hardware is wired. The concrete driver will decide.
        """
        ...
