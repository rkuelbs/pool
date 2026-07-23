const SENSOR_ORDER = [
  "pump_output_psi",
  "filter_output_psi",
  "return_psi",
  "bubbler_psi",
  "booster_psi",
  "raw_orp",
  "orp_temp",
  "raw_ph",
  "raw_ph_voltage",
  "temp",
  "cpu_temp",
  "cpu_load_percent",
  "cpu_fan_rpm",
  "tank_level",
];

const SENSOR_LABELS = {
  pump_output_psi: "Pump output",
  filter_output_psi: "Filter output",
  return_psi: "Return",
  bubbler_psi: "Bubbler",
  booster_psi: "Booster",
  pump_flow_gpm: "Pump flow",
  pump_dynamic_head_psi: "Pump dynamic head",
  return_flow_gpm: "Return flow",
  bubbler_flow_gpm: "Bubbler flow",
  booster_flow_gpm: "Booster flow",
  filter_restriction_metric: "Filter restriction",
  filter_restriction_percent: "Filter restriction %",
  calcium_saturation_index: "CSI",
  lab_ph: "pH (tested)",
  lab_free_chlorine: "Free Chlorine (tested)",
  lab_alkalinity: "Alkalinity (tested)",
  lab_calcium_hardness: "Calcium Hardness (tested)",
  lab_cya: "CYA (tested)",
  lab_tds: "TDS (tested)",
  lab_salt: "Salt (tested)",
  lab_borates: "Borates (tested)",
  chemical_sodium_hypochlorite: "Sodium Hypochlorite Added",
  chemical_muriatic_acid: "Muriatic Acid Added",
  weather_temperature_2m: "Weather Temp",
  weather_relative_humidity_2m: "Weather RH",
  weather_dew_point_2m: "Weather Dew Point",
  weather_apparent_temperature: "Weather Feels Like",
  weather_precipitation: "Weather Precip",
  weather_rain: "Weather Rain",
  weather_showers: "Weather Showers",
  weather_weather_code: "Weather Code",
  weather_cloud_cover: "Weather Cloud Cover",
  weather_wind_speed_10m: "Weather Wind Speed",
  weather_wind_direction_10m: "Weather Wind Direction",
  weather_wind_gusts_10m: "Weather Wind Gusts",
  weather_shortwave_radiation: "Weather Shortwave Rad",
  weather_direct_radiation: "Weather Direct Rad",
  weather_diffuse_radiation: "Weather Diffuse Rad",
  weather_uv_index: "Weather UV Index",
  weather_surface_pressure: "Weather Surface Pressure",
  weather_et0_fao_evapotranspiration: "Weather ET0",
  weather_soil_temperature_0cm: "Weather Soil Temp",
  raw_orp: "ORP",
  orp_temp: "ORP temp",
  raw_ph: "pH",
  raw_ph_voltage: "pH Vraw",
  temp: "Water temp",
  cpu_temp: "CPU temp",
  cpu_load_percent: "CPU load",
  cpu_fan_rpm: "CPU fan",
  tank_level: "Tank level",
};

const HISTORY_SENSOR_ORDER = [
  ...SENSOR_ORDER,
  "calcium_saturation_index",
  "pump_flow_gpm",
  "pump_dynamic_head_psi",
  "return_flow_gpm",
  "bubbler_flow_gpm",
  "booster_flow_gpm",
  "filter_restriction_metric",
  "filter_restriction_percent",
  "lab_ph",
  "lab_free_chlorine",
  "lab_alkalinity",
  "lab_calcium_hardness",
  "lab_cya",
  "lab_tds",
  "lab_salt",
  "lab_borates",
  "chemical_sodium_hypochlorite",
  "chemical_muriatic_acid",
  "weather_temperature_2m",
  "weather_relative_humidity_2m",
  "weather_dew_point_2m",
  "weather_apparent_temperature",
  "weather_precipitation",
  "weather_rain",
  "weather_showers",
  "weather_weather_code",
  "weather_cloud_cover",
  "weather_wind_speed_10m",
  "weather_wind_direction_10m",
  "weather_wind_gusts_10m",
  "weather_shortwave_radiation",
  "weather_direct_radiation",
  "weather_diffuse_radiation",
  "weather_uv_index",
  "weather_surface_pressure",
  "weather_et0_fao_evapotranspiration",
  "weather_soil_temperature_0cm",
];

const LIVE_SENSOR_ORDER = [...SENSOR_ORDER, "calcium_saturation_index"];

const ACQ_REDUCERS = ["last", "mean", "median", "trimmed_mean"];
const ANALOG_SENSOR_OPTIONS = [
  "pump_output_psi",
  "filter_output_psi",
  "return_psi",
  "bubbler_psi",
  "booster_psi",
  "raw_ph",
];

const ACTUATOR_ORDER = [
  "pump_motor",
  "pump_motor_speed",
  "booster_pump",
  "chlorine_dosing_pump",
];

const SENSOR_STATUS_CLASSES = [
  "status-normal",
  "status-caution",
  "status-alarm",
  "status-invalid",
  "status-unknown",
];

const SENSOR_STATUS_PRIORITY = {
  unknown: 0,
  normal: 1,
  caution: 2,
  alarm: 3,
  invalid: 4,
};

const RUNTIME_STAGES = [
  "windows_simulation",
  "open_loop_timer",
  "sensor_logging",
  "safety_monitor",
  "closed_loop_control",
];

const FEATURE_LAYERS = [
  "pump_timer",
  "acquisition",
  "logging",
  "safety_enforcement",
  "mqtt_bridge",
  "chlorination",
  "closed_loop_control",
];

const SVG_NS = "http://www.w3.org/2000/svg";
const PAGE_MODE = document.body.dataset.page || "live";
const LIVE_MODE_STORAGE_KEY = "poolctl.live_mode";
const HISTORY_SERIES_COLORS = [
  "#1680f2",
  "#1f9d55",
  "#fb9e33",
  "#d64545",
  "#7d5be0",
  "#008f8c",
  "#9a6f2f",
  "#b23aa6",
];
const HISTORY_AXIS_SPAN_RATIO_THRESHOLD = 5.0;
const HISTORY_AXIS_CENTER_SPREAD_FACTOR = 2.0;
const HISTORY_AXIS_EPSILON = 1e-6;

let historyLoading = false;
let lastHistoryLoadedAt = 0;
let lastHistoryKey = "";
let timerConfigLoading = false;
let timerConfigSaving = false;
let faultLoading = false;
let lastFaultLoadedAt = 0;
let runtimeConfigLoading = false;
let safetyConfigLoading = false;
let acquisitionConfigLoading = false;
let loggingConfigLoading = false;
let analogConfigLoading = false;
let chlorinationConfigLoading = false;
let chlorinationQuickSaving = false;
let timerOverrideBusy = false;
let healthLoading = false;
let lastHealthLoadedAt = 0;
let topStatusLoading = false;
let lastTopStatusLoadedAt = 0;
let labTestLoading = false;
let chemicalAdditionLoading = false;
let liveMode = "schematic";
let latestLivePayload = null;
let configAutoRefreshPaused = false;
let configDraftDirty = false;
let pumpPrimeThresholds = {
  lowPrimeMinPsi: 1.0,
  highPrimeMinPsi: 5.0,
};

async function loadLive() {
  const response = await fetch("/api/live", { cache: "no-store" });
  const payload = await parseApiResponse(response, "live API failed");
  latestLivePayload = payload;
  render(payload);
}

async function sendCommand(actuatorId, state) {
  setControlsDisabled(true);
  setCommandStatus(`Sending ${actuatorId} ${state}...`);

  try {
    const response = await fetch("/api/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        actuator_id: actuatorId,
        state,
      }),
    });
    const payload = await parseApiResponse(response, "command failed");

    if (payload.applied) {
      setCommandStatus(`Applied ${actuatorId} ${state}`);
    } else {
      setCommandStatus(payload.rejection_reason || `Rejected ${actuatorId} ${state}`);
    }

    await loadLive();
  } catch (error) {
    setCommandStatus(error.message);
  } finally {
    setControlsDisabled(false);
  }
}

async function setTimerOverride(payload) {
  if (timerOverrideBusy) {
    return;
  }
  timerOverrideBusy = true;
  setControlsDisabled(true);
  setCommandStatus("Updating timer override...");
  try {
    const response = await fetch("/api/timer/override", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await parseApiResponse(response, "timer override update failed");
    setCommandStatus(timerOverrideMessage(result.override));
    await loadLive();
  } catch (error) {
    setCommandStatus(error.message);
  } finally {
    setControlsDisabled(false);
    timerOverrideBusy = false;
  }
}

async function saveQuickChlorinationDose(inputId) {
  if (chlorinationQuickSaving) {
    return;
  }
  const input = document.getElementById(inputId);
  if (!input) {
    return;
  }
  const dailyDoseOz = Number(input.value);
  if (!Number.isFinite(dailyDoseOz) || dailyDoseOz < 0) {
    setChlorinationQuickStatus("Dose must be 0 or greater");
    return;
  }

  chlorinationQuickSaving = true;
  setChlorinationQuickStatus("Saving dose...");
  try {
    const currentResponse = await fetch("/api/config/chlorination", { cache: "no-store" });
    const current = await parseApiResponse(currentResponse, "chlorination config load failed");
    const response = await fetch("/api/config/chlorination", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enabled: current.enabled !== false,
        daily_dose_oz: dailyDoseOz,
        pump_output_oz_per_min: Number(current.pump_output_oz_per_min || 1.0),
        no_dose_last_minutes: Number(current.no_dose_last_minutes || 10.0),
        max_duty_cycle: Number(current.max_duty_cycle || 0.5),
        cycle_on_seconds: Number(current.cycle_on_seconds || 60.0),
      }),
    });
    const payload = await parseApiResponse(response, "chlorination dose save failed");
    setChlorinationQuickStatus(payload.applied_live ? "Dose saved" : "Dose saved; restart required");
    await loadLive();
  } catch (error) {
    setChlorinationQuickStatus(error.message);
  } finally {
    chlorinationQuickSaving = false;
  }
}

function setChlorinationQuickStatus(message) {
  [
    "chlorinationStatus",
    "mobileChlorinationStatus",
  ].forEach((id) => {
    const node = document.getElementById(id);
    if (node) {
      node.textContent = message;
    }
  });
}

async function sendLatchedLiveControl(actuatorId, state) {
  const payload = latchedLiveControlPayload(actuatorId, state);
  if (!payload) {
    await sendCommand(actuatorId, state);
    return;
  }
  await setTimerOverride(payload);
}

function latchedLiveControlPayload(actuatorId, state) {
  const actuators = latestLivePayload && latestLivePayload.actuators ? latestLivePayload.actuators : {};
  const pumpState = actuatorState(actuators, "pump_motor", "off");
  const speedState = pumpSpeedState(actuators);
  const boosterState = actuatorState(actuators, "booster_pump", "off");
  const base = {
    until_next_schedule: true,
    reason: `manual live control: ${actuatorId} ${state}`,
  };

  if (actuatorId === "pump_motor" && state === "off") {
    return {
      ...base,
      mode: "force_off",
      pump_speed: speedState,
      booster: "off",
    };
  }

  if (actuatorId === "pump_motor" && state === "on") {
    return {
      ...base,
      mode: "force_on",
      pump_speed: speedState,
      booster: boosterState,
    };
  }

  if (actuatorId === "pump_motor_speed" && (state === "low" || state === "high")) {
    return {
      ...base,
      mode: "force_on",
      pump_speed: state,
      booster: pumpState === "on" ? boosterState : "off",
    };
  }

  if (actuatorId === "booster_pump" && state === "on") {
    return {
      ...base,
      mode: "force_on",
      pump_speed: pumpState === "on" ? speedState : "high",
      booster: "on",
    };
  }

  if (actuatorId === "booster_pump" && state === "off") {
    if (pumpState === "on") {
      return {
        ...base,
        mode: "force_on",
        pump_speed: speedState,
        booster: "off",
      };
    }
    return {
      ...base,
      mode: "force_off",
      pump_speed: speedState,
      booster: "off",
    };
  }

  return null;
}

function actuatorState(actuators, actuatorId, fallback) {
  const actuator = actuators ? actuators[actuatorId] : null;
  const state = actuator ? String(actuator.state || "") : "";
  return state || fallback;
}

function pumpSpeedState(actuators) {
  const state = actuatorState(actuators, "pump_motor_speed", "low");
  return state === "high" ? "high" : "low";
}

function timerOverrideMessage(override) {
  if (!override || !override.active) {
    return "Schedule mode";
  }
  if (override.until) {
    return `Override active until ${new Date(override.until).toLocaleString()}`;
  }
  return "Override active until resumed";
}

function setControlsDisabled(disabled) {
  document.querySelectorAll("[data-command]").forEach((button) => {
    button.disabled = disabled;
  });
}

function render(payload) {
  renderTopStatus(payload);
  renderAnalogLiveVoltages(payload.sensors || {});
  renderConfigDebugInfo(payload);
  renderFreezeStatus(payload.safety);
  renderCsiStatus(payload.sensors || {});
  renderChlorinationStatus(payload.chlorination);
  renderTimerOverride(payload.timer_override);
  renderEvents(payload.tick);
  if (PAGE_MODE !== "live") {
    return;
  }
  renderDiagramSensors(payload.sensors);
  renderFlowPlaceholders(payload.flows || {});
  renderComponentStates(payload.actuators || {}, payload.sensors || {}, payload.flows || {});
  renderMobileLive(payload.sensors || {}, payload.actuators || {}, payload.flows || {});
  renderSensorList(payload.sensors);
  renderActuatorList(payload.actuators);
}

function renderTopStatus(payload) {
  document.getElementById("runtimeLine").textContent =
    `${payload.runtime.stage} / ${payload.runtime.driver_profile}`;
  document.getElementById("updatedAt").textContent = new Date(payload.observed_at).toLocaleString();
  const restartButton = document.getElementById("configRestartService");
  if (restartButton) {
    const isPi = payload.runtime && payload.runtime.driver_profile === "raspberry_pi";
    restartButton.disabled = !isPi;
  }

  renderSafetyBadge(payload.safety);
  renderCpuTempBadge(payload.runtime, payload.sensors || {});
  renderCpuLoadLine(payload.runtime, payload.sensors || {});
  renderCpuFanLine(payload.runtime, payload.sensors || {});
}

async function refreshTopStatus(force) {
  const now = Date.now();
  if (topStatusLoading) {
    return;
  }
  if (!force && now - lastTopStatusLoadedAt < 3000) {
    return;
  }
  topStatusLoading = true;
  try {
    const response = await fetch("/api/live", { cache: "no-store" });
    const payload = await parseApiResponse(response, "live API failed");
    latestLivePayload = payload;
    renderTopStatus(payload);
    renderAnalogLiveVoltages(payload.sensors || {});
    renderConfigDebugInfo(payload);
    renderFreezeStatus(payload.safety);
    renderCsiStatus(payload.sensors || {});
    renderChlorinationStatus(payload.chlorination);
    renderTimerOverride(payload.timer_override);
    lastTopStatusLoadedAt = now;
  } catch (error) {
    const badge = document.getElementById("safetyBadge");
    if (badge) {
      badge.classList.remove("ok");
      badge.classList.add("fault");
      badge.textContent = "Dashboard error";
    }
  } finally {
    topStatusLoading = false;
  }
}

function renderSafetyBadge(safety) {
  const badge = document.getElementById("safetyBadge");
  badge.classList.remove("ok", "fault");

  if (safety.locked_out) {
    badge.classList.add("fault");
    badge.textContent = `LOCKOUT: ${safety.fault.code}`;
    return;
  }

  badge.classList.add("ok");
  if (safety.freeze_protection && safety.freeze_protection.active) {
    badge.textContent = `Safety OK | Freeze ${String(safety.freeze_protection.latched_speed || "").toUpperCase()}`;
    return;
  }
  badge.textContent = "Safety OK";
}

function renderCpuTempBadge(runtime, sensors) {
  const badge = document.getElementById("cpuTempBadge");
  if (!badge) {
    return;
  }

  const isRaspberryPi = runtime && runtime.driver_profile === "raspberry_pi";
  const cpuTemp = sensors ? sensors.cpu_temp : null;
  if (!isRaspberryPi || !cpuTemp) {
    badge.classList.add("hidden");
    return;
  }

  badge.classList.remove("hidden", "ok", "fault", "caution", "alarm", "invalid", "unknown");
  const status = cpuTemp.status || "unknown";
  if (status === "normal") {
    badge.classList.add("ok");
  } else if (status === "caution") {
    badge.classList.add("caution");
  } else if (status === "alarm") {
    badge.classList.add("alarm");
  } else if (status === "invalid") {
    badge.classList.add("invalid");
  } else {
    badge.classList.add("unknown");
  }
  badge.textContent = `CPU Temp: ${cpuTemp.display || "--"}`;
}

function renderCpuFanLine(runtime, sensors) {
  const line = document.getElementById("cpuFanLine");
  if (!line) {
    return;
  }

  const isRaspberryPi = runtime && runtime.driver_profile === "raspberry_pi";
  if (!isRaspberryPi) {
    line.classList.add("hidden");
    return;
  }

  const cpuFan = sensors ? sensors.cpu_fan_rpm : null;
  line.classList.remove("hidden");
  line.textContent = `CPU Fan: ${cpuFan && cpuFan.display ? cpuFan.display : "--"}`;
}

function renderCpuLoadLine(runtime, sensors) {
  const line = document.getElementById("cpuLoadLine");
  if (!line) {
    return;
  }

  const isRaspberryPi = runtime && runtime.driver_profile === "raspberry_pi";
  if (!isRaspberryPi) {
    line.classList.add("hidden");
    return;
  }

  const cpuLoad = sensors ? sensors.cpu_load_percent : null;
  line.classList.remove("hidden");
  line.textContent = `CPU Load: ${cpuLoad && cpuLoad.display ? cpuLoad.display : "--"}`;
}

function renderTimerOverride(override) {
  const statusNodes = [document.getElementById("timerOverrideStatus"), document.getElementById("mobileTimerOverrideStatus")].filter(Boolean);
  if (!statusNodes.length) {
    return;
  }

  const applyText = (value) => {
    statusNodes.forEach((node) => {
      node.textContent = value;
    });
  };

  if (!override || !override.active) {
    applyText("Schedule mode");
    return;
  }

  const until = override.until ? new Date(override.until).toLocaleString() : "manual clear";
  applyText(
    `Override ${override.pump_motor.toUpperCase()} ` +
    `(${override.pump_speed.toUpperCase()}, booster ${override.booster.toUpperCase()}) ` +
    `until ${until}`,
  );
}

function renderFreezeStatus(safety) {
  const nodes = [document.getElementById("freezeStatus"), document.getElementById("mobileFreezeStatus")].filter(Boolean);
  if (!nodes.length) {
    return;
  }
  const setValue = (value) => {
    nodes.forEach((node) => {
      node.textContent = value;
    });
  };
  const freeze = safety && safety.freeze_protection;
  if (!freeze || !freeze.enabled) {
    setValue("Freeze protection: disabled");
    return;
  }
  if (!freeze.active) {
    setValue("Freeze protection: idle");
    return;
  }
  const hold = Number(freeze.hold_remaining_s || 0);
  const rounded = hold > 0 ? `${Math.ceil(hold)}s hold` : "release eligible";
  const observation = freeze.observation ? ` @ ${freeze.observation}` : "";
  setValue(`Freeze ${String(freeze.latched_speed || "").toUpperCase()} (${rounded})${observation}`);
}

function renderCsiStatus(sensors) {
  const csi = sensors.calcium_saturation_index;
  const text = csi ? `CSI: ${csi.display}` : "CSI: --";
  const node = document.getElementById("csiStatus");
  if (node) {
    node.textContent = text;
  }
}

function renderChlorinationStatus(chlorination) {
  const payload = chlorination || {};
  const dose = Number(payload.daily_dose_oz);
  const doseText = Number.isFinite(dose) ? `Dose: ${dose.toFixed(1)} oz/day` : "Dose: -- oz/day";
  const duty = Number(payload.duty_cycle_percent);
  const available = Number(payload.available_runtime_min_per_day);
  const requested = Number(payload.requested_runtime_min_per_day);
  const dutyText =
    Number.isFinite(duty) && Number.isFinite(available) && Number.isFinite(requested)
      ? `Duty: ${duty.toFixed(1)}% | ${requested.toFixed(1)} / ${available.toFixed(0)} min`
      : "Duty: --";
  const stateText = payload.active ? "ON" : "OFF";
  const layerText = payload.layer_enabled === false ? "layer off" : String(payload.reason || "idle");
  const warning = payload.warning ? ` | ${payload.warning}` : "";
  const statusText = `Chlorination: ${stateText} | ${layerText}${warning}`;

  [
    "chlorinationDoseDisplay",
    "mobileChlorinationDoseDisplay",
  ].forEach((id) => setNodeText(id, doseText));
  [
    "chlorinationDutyStatus",
    "mobileChlorinationDutyStatus",
  ].forEach((id) => setNodeText(id, dutyText));
  [
    "chlorinationStatus",
    "mobileChlorinationStatus",
  ].forEach((id) => setNodeText(id, statusText));
  [
    "chlorinationDoseInput",
    "mobileChlorinationDoseInput",
  ].forEach((id) => {
    const input = document.getElementById(id);
    if (!input || document.activeElement === input || !Number.isFinite(dose)) {
      return;
    }
    input.value = dose.toFixed(1);
  });
}

function renderAnalogLiveVoltages(sensors) {
  const container = document.getElementById("analogLiveVoltages");
  if (!container) {
    return;
  }
  container.replaceChildren();

  const rows = [];
  Object.entries(sensors || {}).forEach(([sensorId, sensor]) => {
    if (!sensor) {
      return;
    }
    if (sensorId === "raw_ph_voltage" && sensor.value !== null && sensor.value !== undefined) {
      rows.push({
        key: sensorId,
        label: SENSOR_LABELS[sensorId] || sensorId,
        channel: sensor.metadata && sensor.metadata.channel ? sensor.metadata.channel : null,
        volts: Number(sensor.value),
        display: sensor.display || `${sensor.value} V`,
      });
      return;
    }
    const metadata = sensor.metadata || {};
    if (!Object.prototype.hasOwnProperty.call(metadata, "raw_voltage")) {
      return;
    }
    const volts = Number(metadata.raw_voltage);
    if (!Number.isFinite(volts)) {
      return;
    }
    rows.push({
      key: sensorId,
      label: SENSOR_LABELS[sensorId] || sensorId,
      channel: metadata.channel || null,
      volts,
      display: `${volts.toFixed(4)} V`,
    });
  });

  if (!rows.length) {
    const empty = document.createElement("div");
    empty.className = "state-row";
    empty.innerHTML = '<span class="state-name">No analog voltage data yet</span><span class="state-value">--</span>';
    container.appendChild(empty);
    return;
  }

  rows
    .sort((left, right) => left.key.localeCompare(right.key))
    .forEach((row) => {
      const line = document.createElement("div");
      line.className = "state-row";
      const channelText = row.channel ? ` (CH${row.channel})` : "";
      line.innerHTML =
        `<span class="state-name">${row.label}${channelText}</span>` +
        `<span class="state-value">${row.display}</span>`;
      container.appendChild(line);
    });
}

function renderConfigDebugInfo(payload) {
  const status = document.getElementById("configSyncStatus");
  if (!status || PAGE_MODE !== "config") {
    return;
  }
  const observedAt = payload && payload.observed_at ? new Date(payload.observed_at).toLocaleTimeString() : "--";
  const mode = configAutoRefreshPaused ? "paused" : "active";
  const dirty = configDraftDirty ? "unsaved edits" : "clean";
  status.textContent = `Config refresh ${mode} | Draft ${dirty} | Live ${observedAt}`;
}

async function refreshHealth(force) {
  const now = Date.now();
  if (healthLoading) {
    return;
  }
  if (!force && now - lastHealthLoadedAt < 10000) {
    return;
  }
  healthLoading = true;
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    const payload = await parseApiResponse(response, "health API failed");
    const line = document.getElementById("healthLine");
    const modbusErrors = Object.values((payload.modbus && payload.modbus.ports) || {}).reduce(
      (sum, item) => sum + Number(item.error_count || 0),
      0,
    );
    const mqttState =
      payload.mqtt && payload.mqtt.enabled
        ? payload.mqtt.connected
          ? "mqtt connected"
          : "mqtt disconnected"
        : "mqtt disabled";
    line.textContent = `Health: ${payload.status} | Modbus errors: ${modbusErrors} | ${mqttState}`;
    lastHealthLoadedAt = now;
  } catch (error) {
    document.getElementById("healthLine").textContent = `Health error: ${error.message}`;
  } finally {
    healthLoading = false;
  }
}

function renderDiagramSensors(sensors) {
  document.querySelectorAll(".sensor").forEach((box) => {
    box.classList.remove(...SENSOR_STATUS_CLASSES);
    box.dataset.statusPriority = "-1";
    box.removeAttribute("title");
  });

  document.querySelectorAll("[data-sensor]").forEach((node) => {
    const sensor = sensors[node.dataset.sensor];
    node.textContent = sensor ? sensor.display : "--";
    node.classList.toggle("quality-suspect", sensor && sensor.quality !== "good");
    applySensorBoxStatus(node.closest(".sensor"), sensor);
  });
}

function renderFlowPlaceholders(flows) {
  document.querySelectorAll("[data-flow]").forEach((node) => {
    const key = node.dataset.flow;
    const flow = flows[key];
    node.textContent = flow && flow.display ? flow.display : "-- gpm";
  });
}

function renderComponentStates(actuators, sensors, flows) {
  const components = document.querySelectorAll("[data-component]");
  components.forEach((component) => {
    component.classList.remove(
      "status-off",
      "status-on",
      "status-low",
      "status-high",
      "status-caution",
      "status-alarm",
    );
    const actuatorId = component.dataset.component;
    if (!actuatorId) {
      return;
    }
    if (actuatorId === "pump_motor") {
      const pumpState = actuators.pump_motor ? actuators.pump_motor.state : null;
      const speedState = actuators.pump_motor_speed ? actuators.pump_motor_speed.state : null;
      const pumpPsi = sensors.pump_output_psi ? Number(sensors.pump_output_psi.value) : null;
      const lowPrimeMinPsi = Number(pumpPrimeThresholds.lowPrimeMinPsi || 1.0);
      const highPrimeMinPsi = Number(pumpPrimeThresholds.highPrimeMinPsi || 5.0);
      const pumpIsAlarm =
        pumpState === "on" &&
        Number.isFinite(pumpPsi) &&
        ((speedState === "low" && pumpPsi < lowPrimeMinPsi) ||
          (speedState === "high" && pumpPsi < highPrimeMinPsi));
      if (pumpState !== "on") {
        component.classList.add("status-off");
      } else if (pumpIsAlarm) {
        component.classList.add("status-alarm");
      } else if (speedState === "low") {
        component.classList.add("status-low");
      } else if (speedState === "high") {
        component.classList.add("status-high");
      } else {
        component.classList.add("status-on");
      }
      return;
    }

    const actuator = actuators[actuatorId];
    if (!actuator || actuator.state !== "on") {
      component.classList.add("status-off");
      return;
    }
    component.classList.add("status-on");
  });
  renderFilterComponent(flows);
  renderControlButtonStates(actuators);
}

function renderFilterComponent(flows) {
  const block = document.getElementById("filterBlock");
  if (!block) {
    return;
  }

  block.classList.remove(
    "status-off",
    "status-on",
    "status-low",
    "status-high",
    "status-caution",
    "status-alarm",
  );

  const pumpFlowPayload = flows ? flows.pump_flow_gpm : null;
  const pumpFlow = pumpFlowPayload ? Number(pumpFlowPayload.value) : Number.NaN;
  if (!Number.isFinite(pumpFlow) || pumpFlow <= 0) {
    block.classList.add("status-off");
    return;
  }

  const payload = flows ? flows.filter_restriction_percent : null;
  const percent = payload ? Number(payload.value) : Number.NaN;
  if (!Number.isFinite(percent)) {
    block.classList.add("status-off");
    return;
  }

  if (percent > 80) {
    block.classList.add("status-alarm");
    return;
  }
  if (percent >= 50) {
    block.classList.add("status-caution");
    return;
  }
  block.classList.add("status-on");
}

function renderMobileLive(sensors, actuators, flows) {
  if (!document.getElementById("mobileLivePanel")) {
    return;
  }

  renderMobilePumpCard(sensors, actuators, flows);
  renderMobileFilterCard(sensors, flows);
  renderMobileBranchesCard(sensors, flows);
  renderMobileChemCard(sensors);
  renderMobileTankCard(sensors);
}

function renderMobilePumpCard(sensors, actuators, flows) {
  const pumpState = actuators.pump_motor ? actuators.pump_motor.state : null;
  const speedState = actuators.pump_motor_speed ? actuators.pump_motor_speed.state : null;
  const pumpPsi = sensors.pump_output_psi ? Number(sensors.pump_output_psi.value) : Number.NaN;
  const lowPrimeMinPsi = Number(pumpPrimeThresholds.lowPrimeMinPsi || 1.0);
  const highPrimeMinPsi = Number(pumpPrimeThresholds.highPrimeMinPsi || 5.0);
  const pumpIsAlarm =
    pumpState === "on" &&
    Number.isFinite(pumpPsi) &&
    ((speedState === "low" && pumpPsi < lowPrimeMinPsi) || (speedState === "high" && pumpPsi < highPrimeMinPsi));

  let cardStatus = "status-off";
  let stateText = "OFF";
  if (pumpState === "on" && pumpIsAlarm) {
    cardStatus = "status-alarm";
    stateText = speedState === "low" ? "LOW | LOW PSI" : "HIGH | LOW PSI";
  } else if (pumpState === "on" && speedState === "low") {
    cardStatus = "status-low";
    stateText = "LOW";
  } else if (pumpState === "on" && speedState === "high") {
    cardStatus = "status-high";
    stateText = "HIGH";
  } else if (pumpState === "on") {
    cardStatus = "status-on";
    stateText = "ON";
  }

  setMobileCardStatus("mobilePumpCard", cardStatus);
  setNodeText("mobilePumpState", `State: ${stateText}`);
  setNodeText(
    "mobilePumpPsi",
    `Output: ${sensorDisplay(sensors, "pump_output_psi")} | Head: ${flowDisplay(flows, "pump_dynamic_head_psi")}`,
  );
  setNodeText("mobilePumpFlow", `Flow: ${flowDisplay(flows, "pump_flow_gpm")}`);
}

function renderMobileFilterCard(sensors, flows) {
  const pumpFlowPayload = flows ? flows.pump_flow_gpm : null;
  const pumpFlow = pumpFlowPayload ? Number(pumpFlowPayload.value) : Number.NaN;
  const restrictionPayload = flows ? flows.filter_restriction_percent : null;
  const restrictionPercent = restrictionPayload ? Number(restrictionPayload.value) : Number.NaN;

  let cardStatus = "status-off";
  if (Number.isFinite(pumpFlow) && pumpFlow > 0 && Number.isFinite(restrictionPercent)) {
    if (restrictionPercent > 80) {
      cardStatus = "status-alarm";
    } else if (restrictionPercent >= 50) {
      cardStatus = "status-caution";
    } else {
      cardStatus = "status-on";
    }
  }
  setMobileCardStatus("mobileFilterCard", cardStatus);

  const pumpOutput = sensors.pump_output_psi ? Number(sensors.pump_output_psi.value) : Number.NaN;
  const filterOutput = sensors.filter_output_psi ? Number(sensors.filter_output_psi.value) : Number.NaN;
  const deltaText =
    Number.isFinite(pumpOutput) && Number.isFinite(filterOutput)
      ? `${(pumpOutput - filterOutput).toFixed(2)} psi`
      : "--";

  setNodeText("mobileFilterRestrictionPct", `Restriction: ${flowDisplay(flows, "filter_restriction_percent")}`);
  setNodeText("mobileFilterRestrictionMetric", `R: ${flowDisplay(flows, "filter_restriction_metric")}`);
  setNodeText("mobileFilterDeltaPsi", `Delta PSI: ${deltaText}`);
}

function renderMobileBranchesCard(sensors, flows) {
  const returnStatus = sensorStatus(sensors, "return_psi");
  const bubblerStatus = sensorStatus(sensors, "bubbler_psi");
  const boosterStatus = sensorStatus(sensors, "booster_psi");
  setMobileCardStatus("mobileBranchesCard", worstSensorCardStatus([returnStatus, bubblerStatus, boosterStatus]));

  setNodeText(
    "mobileReturnLine",
    `Return: ${sensorDisplay(sensors, "return_psi")} | ${flowDisplay(flows, "return_flow_gpm")}`,
  );
  setNodeText(
    "mobileBubblerLine",
    `Bubbler: ${sensorDisplay(sensors, "bubbler_psi")} | ${flowDisplay(flows, "bubbler_flow_gpm")}`,
  );
  setNodeText(
    "mobileBoosterLine",
    `Booster: ${sensorDisplay(sensors, "booster_psi")} | ${flowDisplay(flows, "booster_flow_gpm")}`,
  );
}

function renderMobileChemCard(sensors) {
  const tempStatus = sensorStatus(sensors, "temp");
  const phStatus = sensorStatus(sensors, "raw_ph");
  const orpStatus = sensorStatus(sensors, "raw_orp");
  const csiStatus = sensorStatus(sensors, "calcium_saturation_index");
  setMobileCardStatus("mobileChemCard", worstSensorCardStatus([tempStatus, phStatus, orpStatus, csiStatus]));

  setNodeText("mobileTempLine", `Temp: ${sensorDisplay(sensors, "temp")}`);
  setNodeText(
    "mobilePhLine",
    `pH: ${sensorDisplay(sensors, "raw_ph")} | Vraw: ${sensorDisplay(sensors, "raw_ph_voltage")}`,
  );
  setNodeText(
    "mobileOrpLine",
    `ORP: ${sensorDisplay(sensors, "raw_orp")} | Temp: ${sensorDisplay(sensors, "orp_temp")}`,
  );
  setNodeText("mobileCsiLine", `CSI: ${sensorDisplay(sensors, "calcium_saturation_index")}`);
}

function renderMobileTankCard(sensors) {
  setMobileCardStatus("mobileTankCard", sensorCardStatus(sensorStatus(sensors, "tank_level")));
  setNodeText("mobileTankLevelLine", `Level: ${sensorDisplay(sensors, "tank_level")}`);
}

function setNodeText(id, value) {
  const node = document.getElementById(id);
  if (!node) {
    return;
  }
  node.textContent = value;
}

function sensorDisplay(sensors, sensorId) {
  const payload = sensors[sensorId];
  return payload && payload.display ? payload.display : "--";
}

function flowDisplay(flows, flowId) {
  const payload = flows[flowId];
  return payload && payload.display ? payload.display : "--";
}

function sensorStatus(sensors, sensorId) {
  const payload = sensors[sensorId];
  return payload && payload.status ? payload.status : "unknown";
}

function worstSensorCardStatus(statuses) {
  let best = "unknown";
  let bestPriority = -1;
  statuses.forEach((status) => {
    const priority = SENSOR_STATUS_PRIORITY[status] ?? 0;
    if (priority > bestPriority) {
      best = status;
      bestPriority = priority;
    }
  });
  return sensorCardStatus(best);
}

function sensorCardStatus(status) {
  if (status === "alarm") {
    return "status-alarm";
  }
  if (status === "caution") {
    return "status-caution";
  }
  if (status === "invalid") {
    return "status-invalid";
  }
  if (status === "normal") {
    return "status-on";
  }
  return "status-off";
}

function setMobileCardStatus(cardId, statusClass) {
  const card = document.getElementById(cardId);
  if (!card) {
    return;
  }
  card.classList.remove("status-off", "status-on", "status-low", "status-high", "status-caution", "status-alarm", "status-invalid");
  card.classList.add(statusClass);
}

function renderControlButtonStates(actuators) {
  const nodes = document.querySelectorAll("[data-command]");
  nodes.forEach((node) => {
    node.classList.remove("is-active");
    const token = node.dataset.command;
    if (!token || token.indexOf(":") < 0) {
      return;
    }
    const parts = token.split(":");
    const actuatorId = parts[0];
    const requestedState = parts[1];
    const currentState = actuators[actuatorId] ? String(actuators[actuatorId].state) : "";
    if (currentState === requestedState) {
      node.classList.add("is-active");
    }
  });
}

function setCommandStatus(message) {
  ["commandStatus", "mobileCommandStatus"].forEach((id) => {
    const node = document.getElementById(id);
    if (node) {
      node.textContent = message;
    }
  });
}

function renderSensorList(sensors) {
  const list = document.getElementById("sensorList");
  list.innerHTML = "";

  LIVE_SENSOR_ORDER.forEach((sensorId) => {
    const sensor = sensors[sensorId];
    if (!sensor) {
      return;
    }
    list.appendChild(row(sensor.label, sensor.display, sensor.quality, sensor.status));
  });
}

function renderActuatorList(actuators) {
  const list = document.getElementById("actuatorList");
  list.innerHTML = "";

  ACTUATOR_ORDER.forEach((actuatorId) => {
    const actuator = actuators[actuatorId];
    if (!actuator) {
      return;
    }
    list.appendChild(row(actuator.label, actuator.state.toUpperCase()));
  });
}

function renderEvents(tick) {
  const events = document.getElementById("eventList");
  const lines = [];

  if (tick.acquired_groups.length) {
    lines.push(`Acquired: ${tick.acquired_groups.join(", ")}`);
  }

  if (tick.loggable_measurement_count) {
    lines.push(`Loggable measurements: ${tick.loggable_measurement_count}`);
  }

  if (tick.logged_measurement_count) {
    lines.push(`Logged measurements: ${tick.logged_measurement_count}`);
  }
  if (tick.logged_lab_test_count) {
    lines.push(`Logged lab tests: ${tick.logged_lab_test_count}`);
  }
  if (tick.logged_weather_count) {
    lines.push(`Logged weather rows: ${tick.logged_weather_count}`);
  }
  if (tick.weather_poll_error) {
    lines.push(`Weather poll error: ${tick.weather_poll_error}`);
  }
  if (tick.mqtt_result_count) {
    lines.push(`MQTT commands processed: ${tick.mqtt_result_count}`);
  }

  tick.acquisition_failures.forEach((failure) => {
    lines.push(`${failure.driver}: ${failure.error}`);
  });

  tick.safety_results.forEach((result) => {
    if (result.applied && result.metadata.safety_action) {
      lines.push(`Safety action: ${result.metadata.safety_action}`);
    }
  });

  (tick.chlorination_results || []).forEach((result) => {
    if (result.applied) {
      lines.push("Chlorination command applied");
      return;
    }
    if (result.rejection_reason) {
      lines.push(`Chlorination command rejected: ${result.rejection_reason}`);
    }
  });

  (tick.mqtt_results || []).forEach((result) => {
    const summary = result.applied ? "applied" : (result.rejection_reason || "rejected");
    lines.push(`MQTT command: ${summary}`);
  });

  events.textContent = lines.length ? lines.join("\n") : "No new events";
}

function row(name, value, quality, status) {
  const item = document.createElement("div");
  item.className = "state-row";
  if (status) {
    item.classList.add(`status-${status}`);
  }

  const label = document.createElement("span");
  label.className = "state-name";
  label.textContent = name;

  const display = document.createElement("span");
  display.className = "state-value";
  if (quality && quality !== "good") {
    display.classList.add("quality-suspect");
  }
  display.textContent = value;

  item.append(label, display);
  return item;
}

function applySensorBoxStatus(box, sensor) {
  if (!box || !sensor) {
    return;
  }

  const status = sensor.status || "unknown";
  const nextPriority = SENSOR_STATUS_PRIORITY[status] ?? 0;
  const currentPriority = Number(box.dataset.statusPriority ?? "-1");

  if (nextPriority < currentPriority) {
    return;
  }

  box.classList.remove(...SENSOR_STATUS_CLASSES);
  box.classList.add(`status-${status}`);
  box.dataset.statusPriority = String(nextPriority);
  box.title = `${sensor.label}: ${sensor.status_label}`;
}

async function refreshHistory(force) {
  const hoursSelect = document.getElementById("historyHours");
  const validitySelect = document.getElementById("historyValidity");
  const status = document.getElementById("historyStatus");
  if (!hoursSelect || !validitySelect || !status) {
    return;
  }
  updateHistoryChecklistAppearance();
  const sensorIds = selectedHistorySensorIds();
  const validatedOnly = validitySelect.value !== "all";
  const key = `${sensorIds.join(",")}:${hoursSelect.value}:${validatedOnly}`;
  const now = Date.now();

  if (!sensorIds.length) {
    drawHistoryChartSeries([]);
    status.textContent = "Select one or more sensors";
    return;
  }

  if (historyLoading) {
    return;
  }

  if (!force && key === lastHistoryKey && now - lastHistoryLoadedAt < 10000) {
    return;
  }

  historyLoading = true;
  status.textContent = "Loading history...";

  try {
    const hours = Number(hoursSelect.value);
    const params = new URLSearchParams({
      hours: hoursSelect.value,
      limit: String(historyQueryLimit(hours)),
      validated_only: validatedOnly ? "true" : "false",
      max_points: "1800",
      resolution: "auto",
    });
    sensorIds.forEach((sensorId) => params.append("sensor_id", sensorId));
    const response = await fetch(`/api/history?${params.toString()}`, { cache: "no-store" });
    const payload = await parseApiResponse(
      response,
      "history API failed",
      "History API unavailable. Restart the dashboard server.",
    );

    const series = normalizeHistorySeries(payload);
    drawHistoryChartSeries(series);
    lastHistoryKey = key;
    lastHistoryLoadedAt = now;
  } catch (error) {
    drawHistoryChartSeries([]);
    status.textContent = error.message;
  } finally {
    historyLoading = false;
  }
}

function normalizeHistorySeries(payload) {
  if (Array.isArray(payload.series)) {
    return payload.series;
  }

  if (payload.sensor_id && Array.isArray(payload.points)) {
    return [
      {
        sensor_id: payload.sensor_id,
        label: SENSOR_LABELS[payload.sensor_id] || payload.sensor_id,
        points: payload.points,
      },
    ];
  }

  return [];
}

function drawHistoryChartSeries(series) {
  const chart = document.getElementById("historyChart");
  const status = document.getElementById("historyStatus");
  chart.replaceChildren();
  const colorMap = selectedHistoryColorMap();

  const width = 720;
  const height = 260;
  const axisSpacing = 44;
  const chartSeries = series
    .map((entry, seriesIndex) => {
      const color =
        colorMap[entry.sensor_id] || HISTORY_SERIES_COLORS[seriesIndex % HISTORY_SERIES_COLORS.length];
      const points = (entry.points || [])
        .map((point) => {
          const value = Number(point.value);
          const time = new Date(point.observed_at).getTime();
          if (!Number.isFinite(value) || !Number.isFinite(time)) {
            return null;
          }
          return { ...point, _value: value, _time: time };
        })
        .filter((point) => point !== null);
      return {
        sensor_id: entry.sensor_id,
        label: entry.label || entry.sensor_id,
        color,
        style: entry.style || "line",
        marker: entry.marker || "circle",
        points,
      };
    })
    .filter((entry) => entry.points.length > 0);

  const allPoints = chartSeries.flatMap((entry) => entry.points);
  if (!allPoints.length) {
    chart.appendChild(svgText("No logged measurements yet", width / 2, height / 2, "history-empty"));
    status.textContent = "Waiting for loggable samples";
    return;
  }

  const times = allPoints.map((point) => point._time);
  const minTime = Math.min(...times);
  const maxTime = Math.max(...times);

  // Alternate per-series axes left/right so each trace gets its own fitted scale.
  const leftAxisCount = Math.ceil(chartSeries.length / 2);
  const rightAxisCount = Math.floor(chartSeries.length / 2);
  const margin = {
    top: 18,
    right: 22 + Math.max(0, rightAxisCount) * axisSpacing,
    bottom: 34,
    left: 44 + Math.max(0, leftAxisCount - 1) * axisSpacing,
  };
  const plotWidth = Math.max(140, width - margin.left - margin.right);
  const plotHeight = height - margin.top - margin.bottom;

  const withAxes = chartSeries.map((entry, index) => {
    const side = index % 2 === 0 ? "left" : "right";
    const slot = Math.floor(index / 2);
    const values = entry.points.map((point) => point._value);
    const rawMinValue = Math.min(...values);
    const rawMaxValue = Math.max(...values);
    let minValue = rawMinValue;
    let maxValue = rawMaxValue;
    if (minValue === maxValue) {
      minValue -= 1;
      maxValue += 1;
    }
    const valuePadding = (maxValue - minValue) * 0.08;
    minValue -= valuePadding;
    maxValue += valuePadding;
    const axisX =
      side === "left"
        ? margin.left - slot * axisSpacing
        : width - margin.right + slot * axisSpacing;

    return {
      ...entry,
      axis: {
        side,
        slot,
        axisX,
        rawMinValue,
        rawMaxValue,
        rawRange: rawMaxValue - rawMinValue,
        rawCenter: (rawMaxValue + rawMinValue) / 2,
        minValue,
        maxValue,
        range: maxValue - minValue,
      },
    };
  });

  const axisMode = chooseHistoryAxisMode(withAxes);

  if (axisMode === "single") {
    const singleValues = allPoints.map((point) => point._value);
    let minValue = Math.min(...singleValues);
    let maxValue = Math.max(...singleValues);
    if (minValue === maxValue) {
      minValue -= 1;
      maxValue += 1;
    }
    const valuePadding = (maxValue - minValue) * 0.08;
    minValue -= valuePadding;
    maxValue += valuePadding;

    for (let index = 0; index <= 4; index += 1) {
      const y = margin.top + (plotHeight * index) / 4;
      chart.appendChild(svgLine(margin.left, y, margin.left + plotWidth, y, "history-grid"));

      const labelValue = maxValue - ((maxValue - minValue) * index) / 4;
      chart.appendChild(svgText(labelValue.toFixed(1), margin.left - 8, y + 4, "history-axis-label", "end"));
    }

    withAxes.forEach((entry) => {
      const coordinates = entry.points.map((point) => {
        const x =
          minTime === maxTime
            ? margin.left + plotWidth
            : margin.left + ((point._time - minTime) / (maxTime - minTime)) * plotWidth;
        const y = margin.top + plotHeight - ((point._value - minValue) / (maxValue - minValue)) * plotHeight;
        return { x, y, point };
      });

      appendHistorySeriesTrace(chart, entry, coordinates);
    });
  } else {
    for (let index = 0; index <= 4; index += 1) {
      const y = margin.top + (plotHeight * index) / 4;
      chart.appendChild(svgLine(margin.left, y, margin.left + plotWidth, y, "history-grid"));
    }

    withAxes.forEach((entry) => {
      const { axis } = entry;
      const axisLine = svgLine(axis.axisX, margin.top, axis.axisX, margin.top + plotHeight, "history-grid");
      axisLine.style.stroke = colorWithAlpha(entry.color, 0.55);
      chart.appendChild(axisLine);

      for (let tick = 0; tick <= 4; tick += 1) {
        const ratio = tick / 4;
        const y = margin.top + plotHeight * ratio;
        const value = axis.maxValue - axis.range * ratio;
        const label = svgText(
          formatAxisTick(value, axis.range),
          axis.side === "left" ? axis.axisX - 6 : axis.axisX + 6,
          y + 4,
          "history-axis-label",
          axis.side === "left" ? "end" : "start",
        );
        label.setAttribute("style", `fill:${entry.color}`);
        chart.appendChild(label);
      }

      const unit = entry.points[0].unit || "";
      const axisTitle = svgText(
        unit ? `${entry.label} (${unit})` : entry.label,
        axis.side === "left" ? axis.axisX - 6 : axis.axisX + 6,
        margin.top - 6,
        "history-axis-label",
        axis.side === "left" ? "end" : "start",
      );
      axisTitle.setAttribute("style", `fill:${entry.color};font-weight:700`);
      chart.appendChild(axisTitle);
    });

    withAxes.forEach((entry) => {
      const coordinates = entry.points.map((point) => {
        const x =
          minTime === maxTime
            ? margin.left + plotWidth
            : margin.left + ((point._time - minTime) / (maxTime - minTime)) * plotWidth;
        const y =
          margin.top +
          plotHeight -
          ((point._value - entry.axis.minValue) / (entry.axis.maxValue - entry.axis.minValue)) * plotHeight;
        return { x, y, point };
      });

      appendHistorySeriesTrace(chart, entry, coordinates);
    });
  }

  const xTickCount = 5;
  for (let index = 0; index < xTickCount; index += 1) {
    const ratio = xTickCount === 1 ? 1 : index / (xTickCount - 1);
    const x = margin.left + plotWidth * ratio;
    const timestamp = minTime + (maxTime - minTime) * ratio;
    const date = new Date(timestamp);
    const label =
      maxTime - minTime > 24 * 3600 * 1000
        ? date.toLocaleString([], { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })
        : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

    chart.appendChild(svgLine(x, margin.top + plotHeight, x, margin.top + plotHeight + 4, "history-grid"));
    chart.appendChild(svgText(label, x, height - 10, "history-axis-label", "middle"));
  }

  installHistoryHover(chart, series, {
    minTime,
    maxTime,
    margin,
    plotWidth,
    plotHeight,
  });

  status.textContent = `${allPoints.length} points across ${withAxes.length} sensors`;
}

function appendHistorySeriesTrace(chart, entry, coordinates) {
  if (!coordinates.length) {
    return;
  }

  if (entry.style !== "event" && coordinates.length > 1) {
    const polyline = document.createElementNS(SVG_NS, "polyline");
    polyline.setAttribute("class", "history-line");
    polyline.setAttribute("style", `stroke:${entry.color}`);
    polyline.setAttribute(
      "points",
      coordinates.map((coordinate) => `${coordinate.x.toFixed(1)},${coordinate.y.toFixed(1)}`).join(" "),
    );
    chart.appendChild(polyline);
  }

  if (entry.style === "event") {
    coordinates.forEach((coordinate) => {
      appendHistoryMarker(
        chart,
        coordinate.x,
        coordinate.y,
        entry.color,
        historyPointTitle(entry, coordinate.point),
        entry.marker,
        5.5,
      );
    });
    return;
  }

  const latest = coordinates[coordinates.length - 1];
  appendHistoryMarker(
    chart,
    latest.x,
    latest.y,
    entry.color,
    historyPointTitle(entry, latest.point),
    "circle",
    3.5,
  );
}

function appendHistoryMarker(chart, x, y, color, titleText, marker, size) {
  let node;
  if (marker === "square") {
    node = document.createElementNS(SVG_NS, "rect");
    node.setAttribute("x", String(x - size));
    node.setAttribute("y", String(y - size));
    node.setAttribute("width", String(size * 2));
    node.setAttribute("height", String(size * 2));
    node.setAttribute("rx", "1");
  } else if (marker === "star") {
    node = document.createElementNS(SVG_NS, "polygon");
    node.setAttribute("points", starPoints(x, y, size, size * 0.45));
  } else {
    node = document.createElementNS(SVG_NS, "circle");
    node.setAttribute("cx", String(x));
    node.setAttribute("cy", String(y));
    node.setAttribute("r", String(size));
  }

  node.setAttribute("class", "history-point");
  node.setAttribute("fill", color);
  node.setAttribute("title", titleText);
  const title = document.createElementNS(SVG_NS, "title");
  title.textContent = titleText;
  node.appendChild(title);
  chart.appendChild(node);
}

function starPoints(cx, cy, outerRadius, innerRadius) {
  const points = [];
  for (let index = 0; index < 10; index += 1) {
    const radius = index % 2 === 0 ? outerRadius : innerRadius;
    const angle = -Math.PI / 2 + (index * Math.PI) / 5;
    points.push(`${(cx + Math.cos(angle) * radius).toFixed(1)},${(cy + Math.sin(angle) * radius).toFixed(1)}`);
  }
  return points.join(" ");
}

function historyPointTitle(entry, point) {
  const timestamp = point.observed_at ? new Date(point.observed_at).toLocaleString() : "";
  return timestamp ? `${entry.label}: ${point.display} @ ${timestamp}` : `${entry.label}: ${point.display}`;
}

function formatAxisTick(value, range) {
  const absRange = Math.abs(range);
  if (absRange >= 1000) {
    return value.toFixed(0);
  }
  if (absRange >= 100) {
    return value.toFixed(1);
  }
  if (absRange >= 10) {
    return value.toFixed(2);
  }
  return value.toFixed(3);
}

function chooseHistoryAxisMode(seriesWithAxes) {
  if (!seriesWithAxes || seriesWithAxes.length <= 1) {
    return "single";
  }

  const positiveSpans = seriesWithAxes
    .map((entry) => Number(entry.axis.rawRange))
    .filter((span) => Number.isFinite(span) && span > HISTORY_AXIS_EPSILON);
  if (!positiveSpans.length) {
    return "single";
  }

  const largest = Math.max(...positiveSpans);
  const smallest = Math.min(...positiveSpans);
  if (!Number.isFinite(largest) || !Number.isFinite(smallest) || smallest <= 0) {
    return "multi";
  }

  const spanRatio = largest / smallest;
  const centers = seriesWithAxes
    .map((entry) => Number(entry.axis.rawCenter))
    .filter((center) => Number.isFinite(center));
  if (!centers.length) {
    return spanRatio <= HISTORY_AXIS_SPAN_RATIO_THRESHOLD ? "single" : "multi";
  }
  const centerSpread = Math.max(...centers) - Math.min(...centers);

  const spanSimilar = spanRatio <= HISTORY_AXIS_SPAN_RATIO_THRESHOLD;
  const centerSimilar = centerSpread <= HISTORY_AXIS_CENTER_SPREAD_FACTOR * largest;
  return spanSimilar && centerSimilar ? "single" : "multi";
}

function installHistoryHover(chart, series, axis) {
  const status = document.getElementById("historyStatus");
  const hoverLine = svgLine(axis.margin.left, axis.margin.top, axis.margin.left, axis.margin.top + axis.plotHeight, "history-hover-line");
  hoverLine.style.display = "none";
  chart.appendChild(hoverLine);

  chart.addEventListener("mousemove", (event) => {
    const rect = chart.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * 720;
    if (x < axis.margin.left || x > axis.margin.left + axis.plotWidth) {
      hoverLine.style.display = "none";
      return;
    }

    hoverLine.style.display = "block";
    hoverLine.setAttribute("x1", String(x));
    hoverLine.setAttribute("x2", String(x));

    const ratio = (x - axis.margin.left) / axis.plotWidth;
    const timestamp = axis.minTime + ratio * (axis.maxTime - axis.minTime);
    const nearestRows = series
      .map((entry) => nearestPoint(entry, timestamp))
      .filter((row) => row !== null);
    const lines = nearestRows.map((row) => `${row.label}: ${row.point.display}`);
    status.textContent = `${new Date(timestamp).toLocaleString()} | ${lines.join(" | ")}`;
  });

  chart.addEventListener("mouseleave", () => {
    hoverLine.style.display = "none";
  });
}

function nearestPoint(seriesEntry, timestamp) {
  const points = seriesEntry.points || [];
  if (!points.length) {
    return null;
  }
  let best = points[0];
  let bestDistance = Math.abs(new Date(best.observed_at).getTime() - timestamp);
  for (let index = 1; index < points.length; index += 1) {
    const point = points[index];
    const distance = Math.abs(new Date(point.observed_at).getTime() - timestamp);
    if (distance < bestDistance) {
      best = point;
      bestDistance = distance;
    }
  }
  return { label: seriesEntry.label || seriesEntry.sensor_id, point: best };
}

function selectedHistorySensorIds() {
  return [...document.querySelectorAll('#historySensorChecklist input[type="checkbox"]:checked')].map(
    (input) => input.value,
  );
}

function selectedHistoryColorMap() {
  const selectedIds = selectedHistorySensorIds();
  const colorMap = {};
  selectedIds.forEach((sensorId, index) => {
    colorMap[sensorId] = HISTORY_SERIES_COLORS[index % HISTORY_SERIES_COLORS.length];
  });
  return colorMap;
}

function updateHistoryChecklistAppearance() {
  const colorMap = selectedHistoryColorMap();
  document.querySelectorAll("#historySensorChecklist label").forEach((label) => {
    const sensorId = label.dataset.sensorId;
    if (!sensorId) {
      return;
    }
    const selectedColor = colorMap[sensorId];
    const swatch = label.querySelector(".history-swatch");
    const text = label.querySelector(".history-sensor-text");

    if (selectedColor) {
      label.style.backgroundColor = colorWithAlpha(selectedColor, 0.16);
      label.style.borderColor = colorWithAlpha(selectedColor, 0.45);
      if (text) {
        text.style.color = "#202830";
      }
      if (swatch) {
        swatch.style.backgroundColor = selectedColor;
      }
      return;
    }

    label.style.backgroundColor = "#f2f4f7";
    label.style.borderColor = "var(--line)";
    if (text) {
      text.style.color = "var(--muted)";
    }
    if (swatch) {
      swatch.style.backgroundColor = "#a6b2bf";
    }
  });
}

function colorWithAlpha(hexColor, alpha) {
  const hex = hexColor.replace("#", "");
  const expanded = hex.length === 3 ? hex.split("").map((part) => part + part).join("") : hex;
  const red = Number.parseInt(expanded.slice(0, 2), 16);
  const green = Number.parseInt(expanded.slice(2, 4), 16);
  const blue = Number.parseInt(expanded.slice(4, 6), 16);
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

function exportHistoryCsv() {
  const sensorIds = selectedHistorySensorIds();
  const validatedOnly = document.getElementById("historyValidity").value !== "all";
  if (!sensorIds.length) {
    document.getElementById("historyStatus").textContent = "Select one or more sensors";
    return;
  }
  const params = new URLSearchParams({
    hours: document.getElementById("historyHours").value,
    limit: "2000",
    validated_only: validatedOnly ? "true" : "false",
    resolution: "auto",
    max_points: "2000",
  });
  sensorIds.forEach((sensorId) => params.append("sensor_id", sensorId));
  window.open(`/api/history.csv?${params.toString()}`, "_blank");
}

function historyQueryLimit(hours) {
  if (!Number.isFinite(hours) || hours <= 0) {
    return 3000;
  }
  if (hours <= 24) {
    return 7000;
  }
  if (hours <= 24 * 7) {
    return 14000;
  }
  if (hours <= 24 * 30) {
    return 22000;
  }
  return 50000;
}

function svgLine(x1, y1, x2, y2, className) {
  const line = document.createElementNS(SVG_NS, "line");
  line.setAttribute("class", className);
  line.setAttribute("x1", String(x1));
  line.setAttribute("y1", String(y1));
  line.setAttribute("x2", String(x2));
  line.setAttribute("y2", String(y2));
  return line;
}

function svgText(text, x, y, className, anchor = "middle") {
  const label = document.createElementNS(SVG_NS, "text");
  label.setAttribute("class", className);
  label.setAttribute("x", String(x));
  label.setAttribute("y", String(y));
  label.setAttribute("text-anchor", anchor);
  label.textContent = text;
  return label;
}

async function parseApiResponse(response, fallbackMessage, nonJsonHint = "") {
  const contentType = (response.headers.get("content-type") || "").toLowerCase();

  if (contentType.includes("application/json")) {
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || `${fallbackMessage} (HTTP ${response.status})`);
    }
    return payload;
  }

  const body = (await response.text()).trim();
  const hint = nonJsonHint || "Unexpected response format";
  const preview = body ? ` ${body.slice(0, 80)}` : "";
  throw new Error(`${hint} (HTTP ${response.status}).${preview}`);
}

function labeledInput(labelText, field, type, value, step = "", min = "") {
  const label = document.createElement("label");
  const text = document.createElement("span");
  text.textContent = labelText;
  const input = document.createElement("input");
  input.type = type;
  input.dataset.field = field;
  if (value !== undefined && value !== null) {
    input.value = String(value);
  }
  if (step) {
    input.step = step;
  }
  if (min) {
    input.min = min;
  }
  label.append(text, input);
  return label;
}

function labeledCheckbox(labelText, field, checked) {
  const label = document.createElement("label");
  const text = document.createElement("span");
  text.textContent = labelText;
  const input = document.createElement("input");
  input.type = "checkbox";
  input.dataset.field = field;
  input.checked = Boolean(checked);
  label.append(text, input);
  return label;
}

function labeledSelect(labelText, field, options, selectedValue) {
  const label = document.createElement("label");
  const text = document.createElement("span");
  text.textContent = labelText;
  const select = document.createElement("select");
  select.dataset.field = field;
  options.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.value;
    option.textContent = item.label;
    select.appendChild(option);
  });
  select.value = selectedValue;
  label.append(text, select);
  return label;
}

function fieldNode(root, field) {
  const node = root.querySelector(`[data-field="${field}"]`);
  if (!node) {
    throw new Error(`Missing field: ${field}`);
  }
  return node;
}

function stringValue(root, field) {
  return String(fieldNode(root, field).value || "").trim();
}

function numberValue(root, field) {
  const value = Number(fieldNode(root, field).value);
  if (!Number.isFinite(value)) {
    throw new Error(`Invalid number for ${field}`);
  }
  return value;
}

function intValue(root, field) {
  const value = Number(fieldNode(root, field).value);
  if (!Number.isInteger(value)) {
    throw new Error(`Invalid integer for ${field}`);
  }
  return value;
}

function initializeHistoryControls() {
  const checklist = document.getElementById("historySensorChecklist");
  HISTORY_SENSOR_ORDER.forEach((sensorId, index) => {
    const label = document.createElement("label");
    label.dataset.sensorId = sensorId;
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = sensorId;
    input.checked = index < 2;
    input.addEventListener("change", () => refreshHistory(true));
    const swatch = document.createElement("span");
    swatch.className = "history-swatch";
    swatch.style.backgroundColor = "#a6b2bf";
    const text = document.createElement("span");
    text.className = "history-sensor-text";
    text.textContent = SENSOR_LABELS[sensorId] || sensorId;
    label.append(input, swatch, text);
    checklist.appendChild(label);
  });
  updateHistoryChecklistAppearance();

  document.getElementById("historyHours").addEventListener("change", () => refreshHistory(true));
  document.getElementById("historyValidity").addEventListener("change", () => refreshHistory(true));
  document.getElementById("historySelectAll").addEventListener("click", () => {
    checklist.querySelectorAll('input[type="checkbox"]').forEach((input) => {
      input.checked = true;
    });
    updateHistoryChecklistAppearance();
    refreshHistory(true);
  });
  document.getElementById("historyClearAll").addEventListener("click", () => {
    checklist.querySelectorAll('input[type="checkbox"]').forEach((input) => {
      input.checked = false;
    });
    updateHistoryChecklistAppearance();
    refreshHistory(true);
  });
  document.getElementById("historyExportCsv").addEventListener("click", exportHistoryCsv);
}

async function loadPumpTimerConfig() {
  if (timerConfigLoading) {
    return;
  }

  timerConfigLoading = true;
  setTimerStatus("Loading timer schedules...");
  setTimerButtonsDisabled(true);

  try {
    const response = await fetch("/api/config/pump_timer", { cache: "no-store" });
    const payload = await parseApiResponse(response, "pump timer config load failed");
    renderPumpTimerConfig(payload);
    setTimerStatus("Timer schedules loaded");
  } catch (error) {
    setTimerStatus(error.message);
  } finally {
    timerConfigLoading = false;
    setTimerButtonsDisabled(false);
  }
}

function renderPumpTimerConfig(payload) {
  const layer = document.getElementById("timerLayerStatus");
  layer.classList.toggle("timer-layer-disabled", !payload.layer_enabled);
  layer.textContent = payload.layer_enabled
    ? "Pump timer layer is enabled"
    : "Pump timer layer is disabled in runtime.enabled_layers";

  const rows = document.getElementById("timerRows");
  rows.replaceChildren();
  const timezoneInput = document.getElementById("timerTimezone");
  if (timezoneInput) {
    timezoneInput.value = payload.timezone || "UTC";
  }

  const schedules = Array.isArray(payload.schedules) ? payload.schedules : [];
  if (!schedules.length) {
    rows.appendChild(timerRowElement());
    return;
  }

  schedules.forEach((schedule) => rows.appendChild(timerRowElement(schedule)));
}

function timerRowElement(schedule = {}) {
  const row = document.createElement("div");
  row.className = "timer-row";

  row.appendChild(timerInput("name", schedule.name || "", "text"));
  row.appendChild(timerInput("start", schedule.start || "08:00", "time"));
  row.appendChild(timerInput("end", schedule.end || "12:00", "time"));
  row.appendChild(timerSelect("pump_speed", ["low", "high"], schedule.pump_speed || "low"));
  row.appendChild(timerSelect("booster", ["off", "on"], schedule.booster || "off"));

  const removeButton = document.createElement("button");
  removeButton.type = "button";
  removeButton.textContent = "Remove";
  removeButton.addEventListener("click", () => {
    row.remove();
    if (!document.querySelectorAll(".timer-row").length) {
      document.getElementById("timerRows").appendChild(timerRowElement());
    }
  });
  row.appendChild(removeButton);

  return row;
}

function timerInput(field, value, type) {
  const input = document.createElement("input");
  input.type = type;
  input.value = value;
  input.dataset.field = field;
  if (field === "name") {
    input.placeholder = "morning_filter";
  }
  return input;
}

function timerSelect(field, options, value) {
  const select = document.createElement("select");
  select.dataset.field = field;
  options.forEach((optionValue) => {
    const option = document.createElement("option");
    option.value = optionValue;
    option.textContent = optionValue.toUpperCase();
    select.appendChild(option);
  });
  select.value = value;
  return select;
}

function collectTimerSchedules() {
  const rows = [...document.querySelectorAll(".timer-row")];
  const schedules = rows.map((row, index) => {
    const name = row.querySelector('[data-field="name"]').value.trim();
    const start = row.querySelector('[data-field="start"]').value;
    const end = row.querySelector('[data-field="end"]').value;
    const pumpSpeed = row.querySelector('[data-field="pump_speed"]').value;
    const booster = row.querySelector('[data-field="booster"]').value;

    return {
      name: name || `schedule_${index + 1}`,
      start,
      end,
      pump_speed: pumpSpeed,
      booster,
    };
  });

  return schedules.filter((schedule) => schedule.start && schedule.end);
}

async function savePumpTimerConfig() {
  if (timerConfigSaving) {
    return;
  }

  timerConfigSaving = true;
  setTimerStatus("Saving timer schedules...");
  setTimerButtonsDisabled(true);

  try {
    const response = await fetch("/api/config/pump_timer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        timezone: document.getElementById("timerTimezone").value.trim() || "UTC",
        schedules: collectTimerSchedules(),
      }),
    });
    const payload = await parseApiResponse(response, "pump timer config save failed");
    renderPumpTimerConfig(payload);
    setTimerStatus("Timer schedules saved");
  } catch (error) {
    setTimerStatus(error.message);
  } finally {
    timerConfigSaving = false;
    setTimerButtonsDisabled(false);
  }
}

function setTimerStatus(message) {
  document.getElementById("timerSaveStatus").textContent = message;
}

function setTimerButtonsDisabled(disabled) {
  document.getElementById("timerAddRow").disabled = disabled;
  document.getElementById("timerSave").disabled = disabled;
  document.getElementById("timerReload").disabled = disabled;
}

function initializeTimerControls() {
  document.getElementById("timerAddRow").addEventListener("click", () => {
    document.getElementById("timerRows").appendChild(timerRowElement());
  });
  document.getElementById("timerSave").addEventListener("click", savePumpTimerConfig);
  document.getElementById("timerReload").addEventListener("click", loadPumpTimerConfig);
  loadPumpTimerConfig();
}

function markConfigDraftDirty() {
  if (PAGE_MODE !== "config") {
    return;
  }
  configDraftDirty = true;
  configAutoRefreshPaused = true;
  updateConfigRefreshControls();
}

function clearConfigDraftState(resumeRefresh) {
  configDraftDirty = false;
  if (resumeRefresh) {
    configAutoRefreshPaused = false;
  }
  updateConfigRefreshControls();
}

function updateConfigRefreshControls() {
  const toggle = document.getElementById("configRefreshToggle");
  const status = document.getElementById("configSyncStatus");
  if (!toggle || !status) {
    return;
  }
  toggle.textContent = configAutoRefreshPaused ? "Resume Live Refresh" : "Pause Live Refresh";
  if (configAutoRefreshPaused && configDraftDirty) {
    status.textContent = "Config refresh paused (unsaved edits)";
    return;
  }
  if (configAutoRefreshPaused) {
    status.textContent = "Config refresh paused";
    return;
  }
  status.textContent = "Config refresh active";
}

async function loadAllConfigSections() {
  await Promise.all([
    loadRuntimeConfig(),
    loadSafetyConfig(),
    loadAcquisitionConfig(),
    loadLoggingConfig(),
    loadAnalogConfig(),
    loadChlorinationConfig(),
  ]);
}

async function revertConfigDraft() {
  const status = document.getElementById("configSyncStatus");
  if (status) {
    status.textContent = "Reloading config from disk...";
  }
  await loadAllConfigSections();
  clearConfigDraftState(true);
}

async function toggleConfigRefresh() {
  if (!configAutoRefreshPaused) {
    configAutoRefreshPaused = true;
    updateConfigRefreshControls();
    return;
  }
  if (configDraftDirty) {
    await revertConfigDraft();
    return;
  }
  configAutoRefreshPaused = false;
  updateConfigRefreshControls();
}

async function requestServiceRestart() {
  const status = document.getElementById("configSyncStatus");
  try {
    if (status) {
      status.textContent = "Restart requested...";
    }
    const response = await fetch("/api/system/restart", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const payload = await parseApiResponse(response, "restart request failed");
    if (status) {
      status.textContent = payload.message || "Restart requested";
    }
  } catch (error) {
    if (status) {
      status.textContent = `Restart failed: ${error.message}`;
    }
  }
}

function initializeConfigEditorControls() {
  const toggle = document.getElementById("configRefreshToggle");
  const revert = document.getElementById("configRevert");
  const restart = document.getElementById("configRestartService");
  if (!toggle || !revert || !restart) {
    return;
  }

  toggle.addEventListener("click", () => {
    toggleConfigRefresh().catch((error) => {
      const status = document.getElementById("configSyncStatus");
      if (status) {
        status.textContent = error.message;
      }
    });
  });
  revert.addEventListener("click", () => {
    revertConfigDraft().catch((error) => {
      const status = document.getElementById("configSyncStatus");
      if (status) {
        status.textContent = error.message;
      }
    });
  });
  restart.addEventListener("click", requestServiceRestart);

  document.addEventListener("input", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    if (!target.closest('[data-view-section="config"]')) {
      return;
    }
    markConfigDraftDirty();
  });

  document.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    if (!target.closest('[data-view-section="config"]')) {
      return;
    }
    markConfigDraftDirty();
  });

  updateConfigRefreshControls();
}

async function loadRuntimeConfig() {
  if (runtimeConfigLoading) {
    return;
  }
  runtimeConfigLoading = true;
  try {
    const response = await fetch("/api/config/runtime", { cache: "no-store" });
    const payload = await parseApiResponse(response, "runtime config load failed");
    document.getElementById("runtimeStage").value = payload.stage;
    document.getElementById("runtimeDriverProfile").value = payload.driver_profile;
    FEATURE_LAYERS.forEach((layer) => {
      const box = document.getElementById(`layer-${layer}`);
      if (box) {
        box.checked = payload.enabled_layers.includes(layer);
      }
    });
    setRuntimeStatus("Runtime config loaded");
  } catch (error) {
    setRuntimeStatus(error.message);
  } finally {
    runtimeConfigLoading = false;
  }
}

async function saveRuntimeConfig() {
  const enabledLayers = FEATURE_LAYERS.filter((layer) => document.getElementById(`layer-${layer}`).checked);
  setRuntimeStatus("Saving runtime config...");
  try {
    const response = await fetch("/api/config/runtime", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        stage: document.getElementById("runtimeStage").value,
        driver_profile: document.getElementById("runtimeDriverProfile").value,
        enabled_layers: enabledLayers,
      }),
    });
    const payload = await parseApiResponse(response, "runtime config save failed");
    setRuntimeStatus(payload.message || "Runtime config saved");
    clearConfigDraftState(true);
  } catch (error) {
    setRuntimeStatus(error.message);
  }
}

function setRuntimeStatus(message) {
  document.getElementById("runtimeStatus").textContent = message;
}

function initializeRuntimeControls() {
  const stageSelect = document.getElementById("runtimeStage");
  RUNTIME_STAGES.forEach((stage) => {
    const option = document.createElement("option");
    option.value = stage;
    option.textContent = stage;
    stageSelect.appendChild(option);
  });

  const layers = document.getElementById("runtimeLayers");
  FEATURE_LAYERS.forEach((layer) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.id = `layer-${layer}`;
    label.append(input, document.createTextNode(layer));
    layers.appendChild(label);
  });

  document.getElementById("runtimeReload").addEventListener("click", loadRuntimeConfig);
  document.getElementById("runtimeSave").addEventListener("click", saveRuntimeConfig);
  loadRuntimeConfig();
}

async function loadSafetyConfig() {
  if (safetyConfigLoading) {
    return;
  }
  safetyConfigLoading = true;
  try {
    const response = await fetch("/api/config/safety", { cache: "no-store" });
    const payload = await parseApiResponse(response, "safety config load failed");
    const freeze = payload.freeze_protection || {};
    document.getElementById("safetySensorPumpOutput").value = payload.pressure_sensor_ids.pump_output;
    document.getElementById("safetySensorReturn").value = payload.pressure_sensor_ids.return_line;
    document.getElementById("safetySensorBooster").value = payload.pressure_sensor_ids.booster;
    document.getElementById("safetyFreezeEnabled").checked = Boolean(freeze.enabled);
    document.getElementById("safetyFreezeSource").value = freeze.source || "temp";
    document.getElementById("safetyFreezeTempSensor").value = freeze.temp_sensor || "temp";
    document.getElementById("safetyFreezePhTempSensor").value = freeze.ph_temp_sensor || "orp_temp";
    document.getElementById("safetyFreezeLowOnTemp").value = String(
      freeze.low_speed_on_below_temp ?? freeze.low_speed_below_temp ?? 35.0,
    );
    document.getElementById("safetyFreezeLowOffTemp").value = String(
      freeze.low_speed_off_above_temp ?? 37.0,
    );
    document.getElementById("safetyFreezeHighOnTemp").value = String(
      freeze.high_speed_on_below_temp ?? freeze.high_speed_below_temp ?? 33.0,
    );
    document.getElementById("safetyFreezeHighOffTemp").value = String(
      freeze.high_speed_off_above_temp ?? 34.0,
    );
    document.getElementById("safetyFreezeMinRunSeconds").value = String(
      freeze.min_run_seconds ?? 600.0,
    );
    document.getElementById("safetyFreezeUnit").value = freeze.threshold_unit || "degF";
    document.getElementById("safetyChlorineMinReturn").value = payload.thresholds.chlorine_min_return_psi;
    document.getElementById("safetyChlorineMinPump").value = payload.thresholds.chlorine_min_pump_output_psi;
    document.getElementById("safetyChlorineRequiresHighSpeed").checked =
      payload.thresholds.chlorine_requires_high_speed !== false;
    document.getElementById("safetyBoosterMax").value = payload.thresholds.booster_max_psi;
    document.getElementById("safetyBoosterMin").value = payload.thresholds.booster_min_psi;
    document.getElementById("safetyLowPrimeMin").value = payload.thresholds.pump_low_prime_min_output_psi;
    document.getElementById("safetyOverpressure").value = payload.thresholds.pump_output_overpressure_psi;
    document.getElementById("safetyHighPrimeMin").value = payload.thresholds.pump_high_prime_min_output_psi;
    document.getElementById("safetyBoosterGrace").value = payload.timeouts.booster_low_pressure_grace_s;
    document.getElementById("safetyLowPrimeSec").value = payload.timeouts.pump_low_prime_seconds;
    document.getElementById("safetyHighPrimeTimeout").value = payload.timeouts.pump_high_prime_timeout_s;
    pumpPrimeThresholds = {
      lowPrimeMinPsi: Number(payload.thresholds.pump_low_prime_min_output_psi ?? 1.0),
      highPrimeMinPsi: Number(payload.thresholds.pump_high_prime_min_output_psi ?? 5.0),
    };
    setSafetyStatus("Safety config loaded");
  } catch (error) {
    setSafetyStatus(error.message);
  } finally {
    safetyConfigLoading = false;
  }
}

async function saveSafetyConfig() {
  setSafetyStatus("Saving safety config...");
  try {
    const response = await fetch("/api/config/safety", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pressure_sensor_ids: {
          pump_output: document.getElementById("safetySensorPumpOutput").value,
          return_line: document.getElementById("safetySensorReturn").value,
          booster: document.getElementById("safetySensorBooster").value,
        },
        freeze_protection: {
          enabled: document.getElementById("safetyFreezeEnabled").checked,
          source: document.getElementById("safetyFreezeSource").value,
          temp_sensor: document.getElementById("safetyFreezeTempSensor").value,
          ph_temp_sensor: document.getElementById("safetyFreezePhTempSensor").value,
          low_speed_on_below_temp: Number(document.getElementById("safetyFreezeLowOnTemp").value),
          low_speed_off_above_temp: Number(document.getElementById("safetyFreezeLowOffTemp").value),
          high_speed_on_below_temp: Number(document.getElementById("safetyFreezeHighOnTemp").value),
          high_speed_off_above_temp: Number(document.getElementById("safetyFreezeHighOffTemp").value),
          min_run_seconds: Number(document.getElementById("safetyFreezeMinRunSeconds").value),
          threshold_unit: document.getElementById("safetyFreezeUnit").value,
        },
        thresholds: {
          chlorine_min_return_psi: Number(document.getElementById("safetyChlorineMinReturn").value),
          chlorine_min_pump_output_psi: Number(document.getElementById("safetyChlorineMinPump").value),
          chlorine_requires_high_speed: document.getElementById("safetyChlorineRequiresHighSpeed").checked,
          booster_max_psi: Number(document.getElementById("safetyBoosterMax").value),
          booster_min_psi: Number(document.getElementById("safetyBoosterMin").value),
          pump_low_prime_min_output_psi: Number(document.getElementById("safetyLowPrimeMin").value),
          pump_output_overpressure_psi: Number(document.getElementById("safetyOverpressure").value),
          pump_high_prime_min_output_psi: Number(document.getElementById("safetyHighPrimeMin").value),
        },
        timeouts: {
          booster_low_pressure_grace_s: Number(document.getElementById("safetyBoosterGrace").value),
          pump_low_prime_seconds: Number(document.getElementById("safetyLowPrimeSec").value),
          pump_high_prime_timeout_s: Number(document.getElementById("safetyHighPrimeTimeout").value),
        },
      }),
    });
    const payload = await parseApiResponse(response, "safety config save failed");
    setSafetyStatus(payload.applied_live ? "Safety config saved and applied live" : "Safety config saved");
    clearConfigDraftState(true);
  } catch (error) {
    setSafetyStatus(error.message);
  }
}

async function clearSafetyLockout() {
  setSafetyStatus("Clearing safety lockout...");
  try {
    const response = await fetch("/api/safety/clear_lockout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    await parseApiResponse(response, "clear lockout failed");
    setSafetyStatus("Safety lockout cleared");
  } catch (error) {
    setSafetyStatus(error.message);
  }
}

function setSafetyStatus(message) {
  document.getElementById("safetyStatus").textContent = message;
}

function initializeSafetyControls() {
  const selects = [
    "safetySensorPumpOutput",
    "safetySensorReturn",
    "safetySensorBooster",
    "safetyFreezeTempSensor",
    "safetyFreezePhTempSensor",
  ];
  selects.forEach((selectId) => {
    const select = document.getElementById(selectId);
    SENSOR_ORDER.forEach((sensorId) => {
      const option = document.createElement("option");
      option.value = sensorId;
      option.textContent = sensorId;
      select.appendChild(option);
    });
  });

  document.getElementById("safetyReload").addEventListener("click", loadSafetyConfig);
  document.getElementById("safetySave").addEventListener("click", saveSafetyConfig);
  document.getElementById("safetyClearLockout").addEventListener("click", clearSafetyLockout);
  loadSafetyConfig();
}

async function loadAcquisitionConfig() {
  if (acquisitionConfigLoading) {
    return;
  }
  acquisitionConfigLoading = true;
  try {
    const response = await fetch("/api/config/acquisition", { cache: "no-store" });
    const payload = await parseApiResponse(response, "acquisition config load failed");
    renderAcquisitionGroups(payload.groups || {});
    renderChemistrySamplingRefresh(payload.chemistry_sampling_refresh || {});
    setAcqStatus("Acquisition config loaded");
  } catch (error) {
    setAcqStatus(error.message);
  } finally {
    acquisitionConfigLoading = false;
  }
}

async function saveAcquisitionConfig() {
  setAcqStatus("Saving acquisition config...");
  try {
    const groups = collectAcquisitionGroups();
    const chemistrySamplingRefresh = collectChemistrySamplingRefresh();
    const response = await fetch("/api/config/acquisition", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        groups,
        chemistry_sampling_refresh: chemistrySamplingRefresh,
      }),
    });
    const payload = await parseApiResponse(response, "acquisition config save failed");
    setAcqStatus(payload.message || "Acquisition config saved");
    clearConfigDraftState(true);
  } catch (error) {
    setAcqStatus(error.message);
  }
}

function setAcqStatus(message) {
  document.getElementById("acqStatus").textContent = message;
}

function initializeAcquisitionControls() {
  document.getElementById("acqAddGroup").addEventListener("click", () => {
    document.getElementById("acqGroupRows").appendChild(acquisitionGroupRow());
  });
  document.getElementById("acqReload").addEventListener("click", loadAcquisitionConfig);
  document.getElementById("acqSave").addEventListener("click", saveAcquisitionConfig);
  loadAcquisitionConfig();
}

function renderAcquisitionGroups(groups) {
  const container = document.getElementById("acqGroupRows");
  container.replaceChildren();
  const entries = Object.entries(groups);
  if (!entries.length) {
    container.appendChild(acquisitionGroupRow());
    return;
  }
  entries.forEach(([name, group]) => {
    container.appendChild(acquisitionGroupRow(name, group));
  });
}

function acquisitionGroupRow(name = "", group = {}) {
  const card = document.createElement("div");
  card.className = "config-card";
  card.dataset.group = "true";

  const head = document.createElement("div");
  head.className = "config-card-head";
  const title = document.createElement("strong");
  title.textContent = "Group";
  const remove = document.createElement("button");
  remove.type = "button";
  remove.textContent = "Remove";
  remove.addEventListener("click", () => {
    card.remove();
    if (!document.querySelectorAll('[data-group="true"]').length) {
      document.getElementById("acqGroupRows").appendChild(acquisitionGroupRow());
    }
  });
  head.append(title, remove);

  const grid = document.createElement("div");
  grid.className = "config-grid";
  grid.append(
    labeledInput("Name", "acq-group-name", "text", name || ""),
    labeledInput("Read Interval (s)", "acq-read-interval", "number", group.read_interval_s ?? 1.0, "0.1"),
    labeledInput("Log Interval (s)", "acq-log-interval", "number", group.log_interval_s ?? 60.0, "0.1"),
    labeledCheckbox("Requires Pump Flow", "acq-requires-flow", Boolean(group.requires_pump_flow)),
    labeledInput(
      "Min Pump On (s)",
      "acq-min-pump-on",
      "number",
      group.min_pump_on_seconds ?? 0.0,
      "0.1",
    ),
    labeledSelect(
      "Required Pump Speed",
      "acq-required-speed",
      [
        { value: "", label: "Any" },
        { value: "low", label: "LOW" },
        { value: "high", label: "HIGH" },
      ],
      group.required_pump_speed || "",
    ),
    labeledInput(
      "Oversample Count",
      "acq-sample-count",
      "number",
      group.oversample?.sample_count ?? 1,
      "1",
      "1",
    ),
    labeledInput(
      "Oversample Interval (s)",
      "acq-sample-interval",
      "number",
      group.oversample?.sample_interval_s ?? 0.0,
      "0.1",
    ),
    labeledSelect(
      "Reducer",
      "acq-reducer",
      ACQ_REDUCERS.map((item) => ({ value: item, label: item })),
      group.oversample?.reducer || "last",
    ),
  );

  const sensorsBlock = document.createElement("div");
  sensorsBlock.className = "group-sensors";
  const selected = new Set(group.sensor_ids || []);
  SENSOR_ORDER.forEach((sensorId) => {
    const sensorLabel = document.createElement("label");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.value = sensorId;
    box.dataset.field = "acq-sensor";
    box.checked = selected.has(sensorId);
    const text = document.createElement("span");
    text.textContent = SENSOR_LABELS[sensorId] || sensorId;
    sensorLabel.append(box, text);
    sensorsBlock.appendChild(sensorLabel);
  });

  card.append(head, grid, sensorsBlock);
  return card;
}

function renderChemistrySamplingRefresh(config) {
  document.getElementById("acqRefreshEnabled").checked = Boolean(config.enabled);
  document.getElementById("acqRefreshMaxOff").value = String(config.max_pump_off_s ?? 21600);
  document.getElementById("acqRefreshDuration").value = String(config.run_duration_s ?? 1200);
  document.getElementById("acqRefreshSpeed").value = config.pump_speed || "high";
}

function collectAcquisitionGroups() {
  const cards = [...document.querySelectorAll('[data-group="true"]')];
  const groups = {};
  cards.forEach((card, index) => {
    const nameRaw = card.querySelector('[data-field="acq-group-name"]').value.trim();
    const name = nameRaw || `group_${index + 1}`;
    if (groups[name]) {
      throw new Error(`Duplicate group name: ${name}`);
    }
    const sensorIds = [...card.querySelectorAll('[data-field="acq-sensor"]:checked')].map((box) => box.value);
    if (!sensorIds.length) {
      throw new Error(`Group "${name}" must have at least one sensor`);
    }
    groups[name] = {
      sensor_ids: sensorIds,
      read_interval_s: numberValue(card, "acq-read-interval"),
      log_interval_s: numberValue(card, "acq-log-interval"),
      requires_pump_flow: Boolean(card.querySelector('[data-field="acq-requires-flow"]').checked),
      min_pump_on_seconds: numberValue(card, "acq-min-pump-on"),
      required_pump_speed: stringValue(card, "acq-required-speed") || null,
      oversample: {
        sample_count: intValue(card, "acq-sample-count"),
        sample_interval_s: numberValue(card, "acq-sample-interval"),
        reducer: stringValue(card, "acq-reducer") || "last",
      },
    };
  });
  return groups;
}

function collectChemistrySamplingRefresh() {
  return {
    enabled: document.getElementById("acqRefreshEnabled").checked,
    max_pump_off_s: Number(document.getElementById("acqRefreshMaxOff").value),
    run_duration_s: Number(document.getElementById("acqRefreshDuration").value),
    pump_speed: document.getElementById("acqRefreshSpeed").value,
  };
}

async function loadLoggingConfig() {
  if (loggingConfigLoading) {
    return;
  }
  loggingConfigLoading = true;
  try {
    const response = await fetch("/api/config/logging", { cache: "no-store" });
    const payload = await parseApiResponse(response, "logging config load failed");
    document.getElementById("loggingDatabasePath").value = payload.database_path;
    setLoggingStatus("Logging config loaded");
  } catch (error) {
    setLoggingStatus(error.message);
  } finally {
    loggingConfigLoading = false;
  }
}

async function saveLoggingConfig() {
  setLoggingStatus("Saving logging config...");
  try {
    const response = await fetch("/api/config/logging", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        database_path: document.getElementById("loggingDatabasePath").value.trim(),
      }),
    });
    const payload = await parseApiResponse(response, "logging config save failed");
    setLoggingStatus(payload.message || "Logging config saved");
    clearConfigDraftState(true);
  } catch (error) {
    setLoggingStatus(error.message);
  }
}

function setLoggingStatus(message) {
  document.getElementById("loggingStatus").textContent = message;
}

function initializeLoggingControls() {
  document.getElementById("loggingReload").addEventListener("click", loadLoggingConfig);
  document.getElementById("loggingSave").addEventListener("click", saveLoggingConfig);
  loadLoggingConfig();
}

async function loadChlorinationConfig() {
  if (chlorinationConfigLoading) {
    return;
  }
  chlorinationConfigLoading = true;
  try {
    const response = await fetch("/api/config/chlorination", { cache: "no-store" });
    const payload = await parseApiResponse(response, "chlorination config load failed");
    renderChlorinationConfig(payload);
    setChlorinationConfigStatus(
      payload.layer_enabled
        ? "Chlorination config loaded"
        : "Chlorination config loaded; layer disabled",
    );
  } catch (error) {
    setChlorinationConfigStatus(error.message);
  } finally {
    chlorinationConfigLoading = false;
  }
}

async function saveChlorinationConfig() {
  setChlorinationConfigStatus("Saving chlorination config...");
  try {
    const response = await fetch("/api/config/chlorination", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectChlorinationConfig()),
    });
    const payload = await parseApiResponse(response, "chlorination config save failed");
    renderChlorinationConfig(payload);
    setChlorinationConfigStatus(
      payload.applied_live ? "Chlorination config saved and applied live" : "Chlorination config saved",
    );
    clearConfigDraftState(true);
  } catch (error) {
    setChlorinationConfigStatus(error.message);
  }
}

function renderChlorinationConfig(payload) {
  document.getElementById("chlorinationEnabled").checked = payload.enabled !== false;
  document.getElementById("chlorinationDailyDoseOz").value = String(payload.daily_dose_oz ?? 0.0);
  document.getElementById("chlorinationPumpOutputOzPerMin").value = String(
    payload.pump_output_oz_per_min ?? 1.0,
  );
  document.getElementById("chlorinationNoDoseLastMinutes").value = String(
    payload.no_dose_last_minutes ?? 10.0,
  );
  document.getElementById("chlorinationMaxDutyCycle").value = String(payload.max_duty_cycle ?? 0.5);
  document.getElementById("chlorinationCycleOnSeconds").value = String(payload.cycle_on_seconds ?? 60.0);
}

function collectChlorinationConfig() {
  return {
    enabled: document.getElementById("chlorinationEnabled").checked,
    daily_dose_oz: Number(document.getElementById("chlorinationDailyDoseOz").value),
    pump_output_oz_per_min: Number(document.getElementById("chlorinationPumpOutputOzPerMin").value),
    no_dose_last_minutes: Number(document.getElementById("chlorinationNoDoseLastMinutes").value),
    max_duty_cycle: Number(document.getElementById("chlorinationMaxDutyCycle").value),
    cycle_on_seconds: Number(document.getElementById("chlorinationCycleOnSeconds").value),
  };
}

function setChlorinationConfigStatus(message) {
  const status = document.getElementById("chlorinationConfigStatus");
  if (status) {
    status.textContent = message;
  }
}

function initializeChlorinationControls() {
  document.getElementById("chlorinationReload").addEventListener("click", loadChlorinationConfig);
  document.getElementById("chlorinationSave").addEventListener("click", saveChlorinationConfig);
  loadChlorinationConfig();
}

async function loadAnalogConfig() {
  if (analogConfigLoading) {
    return;
  }
  analogConfigLoading = true;
  try {
    const response = await fetch("/api/config/analog_input", { cache: "no-store" });
    const payload = await parseApiResponse(response, "analog input config load failed");
    renderAnalogConfig(payload.modbus_analog_input || {});
    setAnalogStatus("Analog input config loaded");
  } catch (error) {
    setAnalogStatus(error.message);
  } finally {
    analogConfigLoading = false;
  }
}

async function saveAnalogConfig() {
  setAnalogStatus("Saving analog input config...");
  try {
    const modbusAnalogInput = collectAnalogConfig();
    const response = await fetch("/api/config/analog_input", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        modbus_analog_input: modbusAnalogInput,
      }),
    });
    const payload = await parseApiResponse(response, "analog input config save failed");
    setAnalogStatus(payload.message || "Analog input config saved");
    clearConfigDraftState(true);
  } catch (error) {
    setAnalogStatus(error.message);
  }
}

function setAnalogStatus(message) {
  document.getElementById("analogStatus").textContent = message;
}

function initializeAnalogControls() {
  document.getElementById("analogAddSensor").addEventListener("click", () => {
    document.getElementById("analogSensorRows").appendChild(analogSensorRow());
    markConfigDraftDirty();
  });
  document.getElementById("analogReload").addEventListener("click", loadAnalogConfig);
  document.getElementById("analogSave").addEventListener("click", saveAnalogConfig);
  loadAnalogConfig();
}

function renderAnalogConfig(config) {
  document.getElementById("analogPort").value = config.port || "";
  document.getElementById("analogSlaveId").value = String(config.slave_id ?? 4);
  document.getElementById("analogBaudrate").value = String(config.baudrate ?? 9600);
  document.getElementById("analogTimeout").value = String(config.timeout_s ?? 1.0);
  document.getElementById("analogScale").value = String(config.raw_to_volts_scale ?? 0.0005);
  document.getElementById("analogOffset").value = String(config.raw_to_volts_offset ?? 0.0);
  document.getElementById("analogStartupChannelMode").value = config.startup_channel_mode ?? "";

  const rows = document.getElementById("analogSensorRows");
  rows.replaceChildren();
  const sensors = config.sensors || {};
  const entries = Object.entries(sensors);
  if (!entries.length) {
    rows.appendChild(analogSensorRow());
    return;
  }
  entries.forEach(([sensorId, mapping]) => rows.appendChild(analogSensorRow(sensorId, mapping)));
}

function analogSensorRow(sensorId = "", mapping = {}) {
  const card = document.createElement("div");
  card.className = "config-card";
  card.dataset.analogSensor = "true";

  const head = document.createElement("div");
  head.className = "config-card-head";
  const title = document.createElement("strong");
  title.textContent = "Analog Sensor Mapping";
  const remove = document.createElement("button");
  remove.type = "button";
  remove.textContent = "Remove";
  remove.addEventListener("click", () => {
    card.remove();
    if (!document.querySelectorAll('[data-analog-sensor="true"]').length) {
      document.getElementById("analogSensorRows").appendChild(analogSensorRow());
    }
    markConfigDraftDirty();
  });
  head.append(title, remove);

  const calibration = mapping.calibration || {};
  const grid = document.createElement("div");
  grid.className = "config-grid";
  grid.append(
    labeledSelect(
      "Sensor",
      "analog-sensor-id",
      ANALOG_SENSOR_OPTIONS.map((item) => ({ value: item, label: SENSOR_LABELS[item] || item })),
      sensorId || ANALOG_SENSOR_OPTIONS[0],
    ),
    labeledInput("Channel (1-8)", "analog-channel", "number", mapping.channel ?? 1, "1", "1"),
    labeledInput("V1", "analog-v1", "number", calibration.voltage_1 ?? 0.0, "0.001"),
    labeledInput("Value1", "analog-value1", "number", calibration.value_1 ?? 0.0, "0.001"),
    labeledInput("V2", "analog-v2", "number", calibration.voltage_2 ?? 5.0, "0.001"),
    labeledInput("Value2", "analog-value2", "number", calibration.value_2 ?? 1.0, "0.001"),
  );

  card.append(head, grid);
  return card;
}

function collectAnalogConfig() {
  const sensors = {};
  const rows = [...document.querySelectorAll('[data-analog-sensor="true"]')];
  rows.forEach((row) => {
    const sensorId = stringValue(row, "analog-sensor-id");
    if (!sensorId) {
      return;
    }
    if (sensors[sensorId]) {
      throw new Error(`Duplicate analog sensor mapping: ${sensorId}`);
    }
    sensors[sensorId] = {
      channel: intValue(row, "analog-channel"),
      calibration: {
        voltage_1: numberValue(row, "analog-v1"),
        value_1: numberValue(row, "analog-value1"),
        voltage_2: numberValue(row, "analog-v2"),
        value_2: numberValue(row, "analog-value2"),
      },
    };
  });

  return {
    port: document.getElementById("analogPort").value.trim(),
    slave_id: Number(document.getElementById("analogSlaveId").value),
    baudrate: Number(document.getElementById("analogBaudrate").value),
    timeout_s: Number(document.getElementById("analogTimeout").value),
    raw_to_volts_scale: Number(document.getElementById("analogScale").value),
    raw_to_volts_offset: Number(document.getElementById("analogOffset").value),
    startup_channel_mode: numberOrNull(document.getElementById("analogStartupChannelMode").value),
    sensors,
  };
}

async function loadLabTests() {
  if (labTestLoading) {
    return;
  }
  labTestLoading = true;
  try {
    const response = await fetch("/api/lab_tests?hours=720&limit=100", { cache: "no-store" });
    const payload = await parseApiResponse(response, "lab tests load failed");
    renderLabTests(payload.lab_tests || []);
    setLabTestStatus("Lab tests loaded");
  } catch (error) {
    setLabTestStatus(error.message);
  } finally {
    labTestLoading = false;
  }
}

async function saveLabTest() {
  setLabTestStatus("Saving lab test...");
  try {
    const response = await fetch("/api/lab_tests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectLabTestPayload()),
    });
    await parseApiResponse(response, "lab test save failed");
    setLabTestStatus("Lab test saved");
    await loadLabTests();
  } catch (error) {
    setLabTestStatus(error.message);
  }
}

function collectLabTestPayload() {
  const payload = {
    sampled_at: stringOrNull(document.getElementById("labSampledAt").value),
    ph: numberOrNull(document.getElementById("labPh").value),
    free_chlorine: numberOrNull(document.getElementById("labFreeChlorine").value),
    combined_chlorine: numberOrNull(document.getElementById("labCombinedChlorine").value),
    total_chlorine: numberOrNull(document.getElementById("labTotalChlorine").value),
    alkalinity: numberOrNull(document.getElementById("labAlkalinity").value),
    cya: numberOrNull(document.getElementById("labCya").value),
    calcium_hardness: numberOrNull(document.getElementById("labCalciumHardness").value),
    tds: numberOrNull(document.getElementById("labTds").value),
    salt: numberOrNull(document.getElementById("labSalt").value),
    borates: numberOrNull(document.getElementById("labBorates").value),
    water_temp: numberOrNull(document.getElementById("labWaterTemp").value),
    notes: stringOrNull(document.getElementById("labNotes").value),
  };
  if (!payload.sampled_at) {
    delete payload.sampled_at;
  }
  return payload;
}

function renderLabTests(tests) {
  const list = document.getElementById("labTestList");
  if (!tests.length) {
    list.textContent = "No lab tests recorded";
    return;
  }
  const lines = tests
    .slice()
    .reverse()
    .map((test) => {
      const parts = [
        `pH ${formatOptional(test.ph, 2)}`,
        `FC ${formatOptional(test.free_chlorine, 2)}`,
        `TA ${formatOptional(test.alkalinity, 0)}`,
        `CH ${formatOptional(test.calcium_hardness, 0)}`,
        `TDS ${formatOptional(test.tds, 0)}`,
        `CYA ${formatOptional(test.cya, 0)}`,
      ];
      const notes = test.notes ? ` | ${test.notes}` : "";
      return `[${new Date(test.sampled_at).toLocaleString()}] ${parts.join(" | ")}${notes}`;
    });
  list.textContent = lines.join("\n");
}

function setLabTestStatus(message) {
  document.getElementById("labTestStatus").textContent = message;
}

function initializeLabTestControls() {
  document.getElementById("labTestReload").addEventListener("click", loadLabTests);
  document.getElementById("labTestSave").addEventListener("click", saveLabTest);
  loadLabTests();
}

function chemicalDefaultStrengthPercent(chemical) {
  if (chemical === "muriatic_acid") {
    return 31.45;
  }
  return 12.0;
}

async function loadChemicalAdditions() {
  if (chemicalAdditionLoading) {
    return;
  }
  chemicalAdditionLoading = true;
  try {
    const response = await fetch("/api/chemical_additions?hours=720&limit=100", { cache: "no-store" });
    const payload = await parseApiResponse(response, "chemical additions load failed");
    renderChemicalAdditions(payload.chemical_additions || []);
    setChemicalAdditionStatus("Chemical additions loaded");
  } catch (error) {
    setChemicalAdditionStatus(error.message);
  } finally {
    chemicalAdditionLoading = false;
  }
}

async function saveChemicalAddition() {
  setChemicalAdditionStatus("Saving chemical addition...");
  try {
    const response = await fetch("/api/chemical_additions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectChemicalAdditionPayload()),
    });
    await parseApiResponse(response, "chemical addition save failed");
    setChemicalAdditionStatus("Chemical addition saved");
    clearChemicalAdditionInputs();
    await loadChemicalAdditions();
    await refreshHistory(true);
  } catch (error) {
    setChemicalAdditionStatus(error.message);
  }
}

function collectChemicalAdditionPayload() {
  const payload = {
    added_at: stringOrNull(document.getElementById("chemicalAddedAt").value),
    chemical: document.getElementById("chemicalType").value,
    amount: numberOrNull(document.getElementById("chemicalAmount").value),
    unit: document.getElementById("chemicalUnit").value,
    strength_percent: numberOrNull(document.getElementById("chemicalStrength").value),
    notes: stringOrNull(document.getElementById("chemicalNotes").value),
  };
  if (!payload.added_at) {
    delete payload.added_at;
  }
  if (payload.strength_percent === null) {
    delete payload.strength_percent;
  }
  return payload;
}

function renderChemicalAdditions(additions) {
  const list = document.getElementById("chemicalAdditionList");
  if (!additions.length) {
    list.textContent = "No chemical additions recorded";
    return;
  }
  const lines = additions
    .slice()
    .reverse()
    .map((addition) => {
      const label = addition.chemical_label || SENSOR_LABELS[`chemical_${addition.chemical}`] || addition.chemical;
      const amount = formatChemicalAmount(addition);
      const strength = `${Number(addition.strength_percent).toFixed(2)}%`;
      const normalized =
        addition.unit === "fl_oz" ? "" : ` (${Number(addition.amount_fl_oz).toFixed(1)} fl oz)`;
      const notes = addition.notes ? ` | ${addition.notes}` : "";
      return `[${new Date(addition.added_at).toLocaleString()}] ${label} | ${amount}${normalized} | ${strength}${notes}`;
    });
  list.textContent = lines.join("\n");
}

function formatChemicalAmount(addition) {
  const amount = Number(addition.amount);
  const unit = addition.unit || "fl_oz";
  if (!Number.isFinite(amount)) {
    return "--";
  }
  if (unit === "fl_oz") {
    return `${amount.toFixed(1)} fl oz`;
  }
  if (unit === "gal") {
    return `${amount.toFixed(3)} gal`;
  }
  if (unit === "ml") {
    return `${amount.toFixed(0)} mL`;
  }
  if (unit === "l") {
    return `${amount.toFixed(2)} L`;
  }
  return `${amount.toFixed(2)} ${unit}`;
}

function clearChemicalAdditionInputs() {
  document.getElementById("chemicalAddedAt").value = "";
  document.getElementById("chemicalAmount").value = "";
  document.getElementById("chemicalNotes").value = "";
  updateChemicalStrengthDefault();
}

function setChemicalAdditionStatus(message) {
  document.getElementById("chemicalAdditionStatus").textContent = message;
}

function updateChemicalStrengthDefault() {
  const chemical = document.getElementById("chemicalType").value;
  document.getElementById("chemicalStrength").value = String(chemicalDefaultStrengthPercent(chemical));
}

function initializeChemicalAdditionControls() {
  const chemicalType = document.getElementById("chemicalType");
  if (!chemicalType) {
    return;
  }
  chemicalType.addEventListener("change", updateChemicalStrengthDefault);
  document.getElementById("chemicalAdditionReload").addEventListener("click", loadChemicalAdditions);
  document.getElementById("chemicalAdditionSave").addEventListener("click", saveChemicalAddition);
  updateChemicalStrengthDefault();
  loadChemicalAdditions();
}

function numberOrNull(raw) {
  if (raw === null || raw === undefined || String(raw).trim() === "") {
    return null;
  }
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

function stringOrNull(raw) {
  const text = String(raw ?? "").trim();
  return text ? text : null;
}

function formatOptional(value, decimals) {
  if (value === null || value === undefined) {
    return "--";
  }
  return Number(value).toFixed(decimals);
}

async function refreshFaultTimeline(force) {
  const kind = document.getElementById("faultKind").value;
  const limit = document.getElementById("faultLimit").value;
  const now = Date.now();

  if (faultLoading) {
    return;
  }
  if (!force && now - lastFaultLoadedAt < 5000) {
    return;
  }

  faultLoading = true;
  try {
    const params = new URLSearchParams({ kind, limit });
    const response = await fetch(`/api/events?${params.toString()}`, { cache: "no-store" });
    const payload = await parseApiResponse(response, "events API failed");
    renderFaultTimeline(payload.events || []);
    lastFaultLoadedAt = now;
  } catch (error) {
    document.getElementById("faultTimeline").textContent = error.message;
  } finally {
    faultLoading = false;
  }
}

function renderFaultTimeline(events) {
  if (!events.length) {
    document.getElementById("faultTimeline").textContent = "No timeline events";
    return;
  }
  const lines = events.map((event) => {
    return `[${event.observed_at}] ${event.kind}/${event.level}: ${event.message}`;
  });
  document.getElementById("faultTimeline").textContent = lines.join("\n");
}

function initializeFaultTimelineControls() {
  document.getElementById("faultReload").addEventListener("click", () => refreshFaultTimeline(true));
  document.getElementById("faultKind").addEventListener("change", () => refreshFaultTimeline(true));
  document.getElementById("faultLimit").addEventListener("change", () => refreshFaultTimeline(true));
  refreshFaultTimeline(true);
}

function initializeTimerOverrideControls() {
  [
    "overridePumpOnHour",
    "mobileOverridePumpOnHour",
  ].forEach((id) => {
    const node = document.getElementById(id);
    if (!node) {
      return;
    }
    node.addEventListener("click", () =>
      setTimerOverride({
        mode: "force_on",
        duration_s: 3600,
        pump_speed: "high",
        booster: "off",
        reason: "manual pump run 1h",
      }),
    );
  });

  [
    "overridePumpOffManual",
    "mobileOverridePumpOffManual",
  ].forEach((id) => {
    const node = document.getElementById(id);
    if (!node) {
      return;
    }
    node.addEventListener("click", () =>
      setTimerOverride({
        mode: "force_off",
        reason: "manual maintenance off",
      }),
    );
  });

  [
    "overrideResumeSchedule",
    "mobileOverrideResumeSchedule",
  ].forEach((id) => {
    const node = document.getElementById(id);
    if (!node) {
      return;
    }
    node.addEventListener("click", () =>
      setTimerOverride({
        mode: "auto",
      }),
    );
  });
}

function initializeChlorinationQuickControls() {
  [
    ["chlorinationDoseSave", "chlorinationDoseInput"],
    ["mobileChlorinationDoseSave", "mobileChlorinationDoseInput"],
  ].forEach(([buttonId, inputId]) => {
    const button = document.getElementById(buttonId);
    const input = document.getElementById(inputId);
    if (!button || !input) {
      return;
    }
    button.addEventListener("click", () => saveQuickChlorinationDose(inputId));
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        saveQuickChlorinationDose(inputId);
      }
    });
  });
}

function initializeLiveModeControls() {
  const panel = document.getElementById("mobileLivePanel");
  const listButton = document.getElementById("liveModeList");
  const schematicButton = document.getElementById("liveModeSchematic");
  if (!panel || !listButton || !schematicButton) {
    return;
  }

  const storedMode = window.localStorage.getItem(LIVE_MODE_STORAGE_KEY);
  const defaultMode = window.matchMedia("(max-width: 760px)").matches ? "list" : "schematic";
  setLiveMode(storedMode === "list" || storedMode === "schematic" ? storedMode : defaultMode);

  listButton.addEventListener("click", () => setLiveMode("list"));
  schematicButton.addEventListener("click", () => setLiveMode("schematic"));
}

function setLiveMode(mode) {
  liveMode = mode === "list" ? "list" : "schematic";
  document.body.dataset.liveMode = liveMode;
  const listButton = document.getElementById("liveModeList");
  const schematicButton = document.getElementById("liveModeSchematic");
  if (listButton) {
    listButton.classList.toggle("active", liveMode === "list");
    listButton.setAttribute("aria-pressed", liveMode === "list" ? "true" : "false");
  }
  if (schematicButton) {
    schematicButton.classList.toggle("active", liveMode === "schematic");
    schematicButton.setAttribute("aria-pressed", liveMode === "schematic" ? "true" : "false");
  }
  window.localStorage.setItem(LIVE_MODE_STORAGE_KEY, liveMode);
}

async function poll() {
  try {
    if (PAGE_MODE === "live") {
      await loadLive();
      await refreshHealth(false);
    } else if (PAGE_MODE === "history") {
      await refreshTopStatus(false);
      await refreshHistory(false);
      await refreshFaultTimeline(false);
      await loadLabTests();
      await loadChemicalAdditions();
      await refreshHealth(false);
    } else if (PAGE_MODE === "schedule") {
      await refreshTopStatus(false);
      await loadPumpTimerConfig();
      await refreshHealth(false);
    } else if (PAGE_MODE === "config") {
      await refreshTopStatus(false);
      if (!configAutoRefreshPaused) {
        await loadAllConfigSections();
      }
      await refreshHealth(false);
    }
  } catch (error) {
    const badge = document.getElementById("safetyBadge");
    if (badge) {
      badge.classList.remove("ok");
      badge.classList.add("fault");
      badge.textContent = "Dashboard error";
    }
    const events = document.getElementById("eventList");
    if (events) {
      events.textContent = error.message;
    }
  } finally {
    const intervalMs = PAGE_MODE === "live" ? 2000 : 10000;
    setTimeout(poll, intervalMs);
  }
}

document.querySelectorAll("[data-command]").forEach((button) => {
  button.addEventListener("click", () => {
    const [actuatorId, state] = button.dataset.command.split(":");
    sendLatchedLiveControl(actuatorId, state);
  });
});

setActiveNavPage();
initializeForPage();
poll();

function setActiveNavPage() {
  document.querySelectorAll("[data-nav-page]").forEach((node) => {
    node.classList.toggle("active", node.dataset.navPage === PAGE_MODE);
  });
}

function initializeForPage() {
  if (PAGE_MODE === "live") {
    initializeLiveModeControls();
    initializeTimerOverrideControls();
    initializeChlorinationQuickControls();
    return;
  }
  if (PAGE_MODE === "history") {
    initializeHistoryControls();
    initializeFaultTimelineControls();
    initializeLabTestControls();
    initializeChemicalAdditionControls();
    return;
  }
  if (PAGE_MODE === "schedule") {
    initializeTimerControls();
    return;
  }
  if (PAGE_MODE === "config") {
    initializeConfigEditorControls();
    initializeRuntimeControls();
    initializeSafetyControls();
    initializeAcquisitionControls();
    initializeLoggingControls();
    initializeAnalogControls();
    initializeChlorinationControls();
    return;
  }
}
