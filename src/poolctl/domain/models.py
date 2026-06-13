from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    """
    Return the current time in UTC.

    Using UTC internally avoids confusion later when storing data,
    comparing timestamps, syncing with cloud services, or dealing with
    daylight saving time changes.
    """
    return datetime.now(timezone.utc)


class SensorId(str, Enum):
    """
    Official list of sensor identifiers used throughout the system.

    These names should be stable because they will be used by:
      - sensor drivers
      - database records
      - dashboards
      - estimator logic
      - controller logic
      - MQTT topics later
    """

    PUMP_OUTPUT_PSI = "pump_output_psi"
    FILTER_OUTPUT_PSI = "filter_output_psi"
    RETURN_PSI = "return_psi"
    BUBBLER_PSI = "bubbler_psi"
    BOOSTER_PSI = "booster_psi"
    PUMP_FLOW_GPM = "pump_flow_gpm"
    PUMP_DYNAMIC_HEAD_PSI = "pump_dynamic_head_psi"
    RETURN_FLOW_GPM = "return_flow_gpm"
    BUBBLER_FLOW_GPM = "bubbler_flow_gpm"
    BOOSTER_FLOW_GPM = "booster_flow_gpm"
    FILTER_RESTRICTION_METRIC = "filter_restriction_metric"
    FILTER_RESTRICTION_PERCENT = "filter_restriction_percent"
    CALCIUM_SATURATION_INDEX = "calcium_saturation_index"

    RAW_ORP = "raw_orp"
    ORP_TEMP = "orp_temp"

    RAW_PH = "raw_ph"
    RAW_PH_VOLTAGE = "raw_ph_voltage"

    TEMP = "temp"
    CPU_TEMP = "cpu_temp"
    CPU_LOAD_PERCENT = "cpu_load_percent"
    CPU_FAN_RPM = "cpu_fan_rpm"
    TANK_LEVEL = "tank_level"


class ActuatorId(str, Enum):
    """
    Official list of actuator/output identifiers used throughout the system.
    """

    PUMP_MOTOR = "pump_motor"
    PUMP_MOTOR_SPEED = "pump_motor_speed"
    BOOSTER_PUMP = "booster_pump"
    CHLORINE_DOSING_PUMP = "chlorine_dosing_pump"


class Quality(str, Enum):
    """
    Indicates whether a measurement should be trusted.

    This is useful now for logging and dashboards, and later for making sure
    the controller does not act on bad or stale sensor data.
    """

    GOOD = "good"
    SUSPECT = "suspect"
    BAD = "bad"
    MISSING = "missing"


class MeasurementKind(str, Enum):
    """
    Describes the meaning of a measurement.

    RAW:
        Direct or near-direct value from a sensor.
        Example: raw pH voltage, raw ORP mV, pressure transducer voltage.

    CALIBRATED:
        Sensor value converted using a calibration model.
        Example: calibrated pH derived from raw_ph.

    ESTIMATED:
        Value inferred from multiple inputs.
        Example: estimated free chlorine from ORP, pH, temperature, and tests.

    MANUAL:
        Value entered by the user.
        Example: weekly drop-test free chlorine result.
    """

    RAW = "raw"
    CALIBRATED = "calibrated"
    ESTIMATED = "estimated"
    MANUAL = "manual"


class ActuatorState(str, Enum):
    """
    Simple actuator command states.

    Most outputs are simply ON/OFF.

    Pump speed is intentionally represented as LOW/HIGH rather than an
    arbitrary percentage or duration command for this first version.
    """

    ON = "on"
    OFF = "off"
    LOW = "low"
    HIGH = "high"


class CommandSource(str, Enum):
    """
    Identifies where an actuator command came from.

    This is useful for debugging, auditing, safety checks, and future logic.
    """

    TIMER = "timer"
    LOCAL_GUI = "local_gui"
    REMOTE_GUI = "remote_gui"
    MQTT = "mqtt"
    CONTROLLER = "controller"
    MANUAL = "manual"
    SYSTEM = "system"


class Measurement(BaseModel):
    """
    Represents one measured value from the pool system.

    This model is used for both raw and processed readings. For example:

      raw_ph:
        sensor_id = SensorId.RAW_PH
        kind = MeasurementKind.RAW
        value = 1.842
        unit = "V"

      calibrated pH later:
        sensor_id = SensorId.RAW_PH
        kind = MeasurementKind.CALIBRATED
        value = 7.42
        unit = "pH"
        source_measurement_ids = ["..."]

    In the first stage, most chemical sensors should be stored as RAW so
    calibration and estimation can improve later without destroying the
    original data.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))

    sensor_id: SensorId
    observed_at: datetime = Field(default_factory=utc_now)

    kind: MeasurementKind = MeasurementKind.RAW

    value: float
    unit: str

    quality: Quality = Quality.GOOD

    # Optional links for future calibration/estimation.
    calibration_id: str | None = None
    source_measurement_ids: list[str] = Field(default_factory=list)

    # Flexible metadata for driver-specific details.
    # Examples:
    #   {"driver": "simulated_raw_ph"}
    #   {"adc_channel": 0, "voltage": 1.842}
    #   {"i2c_address": "0x63"}
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActuatorCommand(BaseModel):
    """
    Represents a request to place an actuator into a simple state.

    This intentionally does NOT include a duration field.

    The scheduler/controller is responsible for deciding when to send ON/OFF
    or LOW/HIGH commands. Later, total runtime and duty cycle can be calculated
    from the command history or actuator state history.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))

    actuator_id: ActuatorId
    created_at: datetime = Field(default_factory=utc_now)

    state: ActuatorState

    requested_by: CommandSource
    reason: str

    # Optional expiration timestamp.
    # This is useful later for remote commands so old commands cannot be replayed.
    expires_at: datetime | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)


class ActuatorCommandResult(BaseModel):
    """
    Records what happened after an actuator command was submitted.

    The command router and safety gate will produce this result.

    Example:
      accepted = False
      applied = False
      rejection_reason = "chlorine dosing pump cannot turn on unless pump is running"
    """

    command_id: str

    accepted: bool
    applied: bool

    decided_at: datetime = Field(default_factory=utc_now)

    rejection_reason: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)


class ActuatorStateSample(BaseModel):
    """
    Represents the observed or believed state of an actuator at a point in time.

    This is separate from ActuatorCommand because a command is only a request.
    The actual state is what the system believes happened after applying the
    command.

    Later this can be used to compute:
      - pump runtime over the last 24 hours
      - chlorine pump duty cycle
      - booster pump runtime
      - pump speed state history
    """

    id: str = Field(default_factory=lambda: str(uuid4()))

    actuator_id: ActuatorId
    observed_at: datetime = Field(default_factory=utc_now)

    state: ActuatorState

    source_command_id: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)


class LabTest(BaseModel):
    """
    Represents manually entered chemical test results.

    This is not needed on day one, but defining it early gives the future
    estimator a clean place to receive weekly test data.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))

    sampled_at: datetime
    entered_at: datetime = Field(default_factory=utc_now)

    ph: float | None = None
    free_chlorine: float | None = None
    combined_chlorine: float | None = None
    total_chlorine: float | None = None
    alkalinity: float | None = None
    cya: float | None = None
    calcium_hardness: float | None = None
    tds: float | None = None
    salt: float | None = None
    borates: float | None = None
    water_temp: float | None = None

    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChemicalType(str, Enum):
    """
    Chemicals that can be manually added and logged.
    """

    MURIATIC_ACID = "muriatic_acid"
    SODIUM_HYPOCHLORITE = "sodium_hypochlorite"


class ChemicalAddition(BaseModel):
    """
    Represents a manually logged chemical addition event.

    The original amount and unit are preserved for display, while
    amount_fl_oz gives estimators and charts a normalized quantity.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))

    added_at: datetime
    entered_at: datetime = Field(default_factory=utc_now)

    chemical: ChemicalType
    amount: float = Field(gt=0)
    unit: str = "fl_oz"
    amount_fl_oz: float = Field(gt=0)
    strength_percent: float = Field(gt=0)

    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EstimatedState(BaseModel):
    """
    Represents a future estimated pool state.

    This is where the estimator can later publish things like:
      - calibrated pH
      - estimated free chlorine
      - sensor drift
      - estimated chlorine demand
    """

    id: str = Field(default_factory=lambda: str(uuid4()))

    variable: str
    estimated_at: datetime = Field(default_factory=utc_now)

    value: float
    unit: str

    uncertainty: float | None = None

    method_version: str
    input_measurement_ids: list[str] = Field(default_factory=list)
    input_lab_test_ids: list[str] = Field(default_factory=list)

    metadata: dict[str, Any] = Field(default_factory=dict)


class ControlMode(str, Enum):
    """
    Future operating modes for controller-generated decisions.
    """

    OBSERVE_ONLY = "observe_only"
    RECOMMEND = "recommend"
    APPROVE_REQUIRED = "approve_required"
    AUTOMATIC = "automatic"


class ControlPlan(BaseModel):
    """
    Represents a future controller plan.

    The predictive controller should generate a plan, not directly control
    hardware. Any recommended actuator command still has to pass through the
    command router and safety gate.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))

    generated_at: datetime = Field(default_factory=utc_now)

    mode: ControlMode = ControlMode.OBSERVE_ONLY
    horizon_hours: float

    recommended_commands: list[ActuatorCommand] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)

    metadata: dict[str, Any] = Field(default_factory=dict)
