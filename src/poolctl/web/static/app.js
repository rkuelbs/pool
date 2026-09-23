const SENSOR_ORDER = [
  "pump_output_psi",
  "water_temp",
  "raw_orp",
  "orp_temp",
  "raw_ph",
  "ph_temp",
  "temp",
  "cpu_temp",
  "cpu_load_percent",
  "cpu_fan_rpm",
  "tank_level",
  "chlorine_tank_level_gal",
];
const ACQUISITION_SENSOR_ORDER = SENSOR_ORDER.filter((sensorId) => sensorId !== "water_temp");

const SENSOR_LABELS = {
  pump_output_psi: "Pump output",
  pump_flow_gpm: "Pump flow",
  pump_dynamic_head_psi: "Pump dynamic head",
  filter_reference_psi: "Filter reference pressure",
  filter_reference_flow_gpm: "Filter reference flow",
  filter_flow_loss_percent: "Filter flow loss",
  filter_loading_percent: "Filter loading (legacy)",
  calcium_saturation_index: "CSI",
  chlorine_daily_delivered_oz: "Daily chlorine delivered",
  chlorination_duty_cycle_percent: "Dosing duty cycle",
  fc_demand_ppm_per_day: "FC demand",
  base_fc_demand_ppm_per_day: "Base FC demand",
  fc_demand_weather_adjustment_ppm_per_day: "FC demand weather adjustment",
  predicted_fc_demand_ppm_per_day: "Predicted FC demand",
  fc_demand_residual_ppm_per_day: "FC demand residual",
  daily_water_temp_min: "Daily water temp min",
  daily_water_temp_avg: "Daily water temp avg",
  daily_water_temp_max: "Daily water temp max",
  daily_uv_index_dose: "Daily UV dose",
  daily_shortwave_radiation_dose: "Daily shortwave dose",
  daily_sodium_hypochlorite_added_oz: "Daily sodium hypochlorite added",
  daily_sodium_hypochlorite_added_oz_7d_avg: "Sodium hypochlorite 7d avg",
  daily_sodium_hypochlorite_added_oz_28d_avg: "Sodium hypochlorite 28d avg",
  daily_muriatic_acid_added_oz: "Daily muriatic acid added",
  daily_muriatic_acid_added_oz_7d_avg: "Muriatic acid 7d avg",
  daily_muriatic_acid_added_oz_28d_avg: "Muriatic acid 28d avg",
  daily_orp_avg: "Daily ORP avg",
  daily_orp_avg_7d_avg: "ORP 7d avg",
  daily_orp_avg_28d_avg: "ORP 28d avg",
  daily_water_temp_avg_7d_avg: "Water temp 7d avg",
  daily_water_temp_avg_28d_avg: "Water temp 28d avg",
  daily_ph_avg: "Daily pH avg",
  daily_ph_avg_7d_avg: "pH 7d avg",
  daily_ph_avg_28d_avg: "pH 28d avg",
  daily_uv_index_dose_7d_avg: "UV dose 7d avg",
  daily_uv_index_dose_28d_avg: "UV dose 28d avg",
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
  ph_temp: "pH temp",
  water_temp: "Water temperature",
  temp: "Simulated water temp",
  cpu_temp: "CPU temp",
  cpu_load_percent: "CPU load",
  cpu_fan_rpm: "CPU fan",
  tank_level: "Tank level",
  chlorine_tank_level_gal: "Chlorine tank level",
};

const HISTORY_SENSOR_ORDER = [
  ...SENSOR_ORDER,
  "calcium_saturation_index",
  "pump_flow_gpm",
  "pump_dynamic_head_psi",
  "filter_reference_psi",
  "filter_reference_flow_gpm",
  "filter_flow_loss_percent",
  "filter_loading_percent",
  "chlorine_daily_delivered_oz",
  "chlorination_duty_cycle_percent",
  "fc_demand_ppm_per_day",
  "base_fc_demand_ppm_per_day",
  "fc_demand_weather_adjustment_ppm_per_day",
  "predicted_fc_demand_ppm_per_day",
  "fc_demand_residual_ppm_per_day",
  "daily_water_temp_min",
  "daily_water_temp_avg",
  "daily_water_temp_max",
  "daily_water_temp_avg_7d_avg",
  "daily_water_temp_avg_28d_avg",
  "daily_orp_avg",
  "daily_orp_avg_7d_avg",
  "daily_orp_avg_28d_avg",
  "daily_ph_avg",
  "daily_ph_avg_7d_avg",
  "daily_ph_avg_28d_avg",
  "daily_uv_index_dose",
  "daily_uv_index_dose_7d_avg",
  "daily_uv_index_dose_28d_avg",
  "daily_shortwave_radiation_dose",
  "daily_sodium_hypochlorite_added_oz",
  "daily_sodium_hypochlorite_added_oz_7d_avg",
  "daily_sodium_hypochlorite_added_oz_28d_avg",
  "daily_muriatic_acid_added_oz",
  "daily_muriatic_acid_added_oz_7d_avg",
  "daily_muriatic_acid_added_oz_28d_avg",
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
const DEFAULT_HISTORY_SENSOR_IDS = new Set(["pump_output_psi", "raw_orp"]);

const ACQ_REDUCERS = ["last", "mean", "median", "trimmed_mean"];
const ACQ_FILTER_TYPES = ["none", "boxcar"];
const ANALOG_SENSOR_OPTIONS = [
  "pump_output_psi",
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

const SVG_NS = "http://www.w3.org/2000/svg";
const PAGE_MODE = document.body.dataset.page || "live";
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
const LIVE_SHORT_KPI_HISTORY_HOURS = 24;
const LIVE_LONG_KPI_HISTORY_HOURS = 24 * 30;
const LIVE_TREND_HISTORY_HOURS = 168;
const LIVE_CHLORINE_DELIVERY_SENSOR_ID = "chlorine_daily_delivered_oz";
const LIVE_EVENT_SENSOR_IDS = ["chemical_sodium_hypochlorite", "chemical_muriatic_acid"];
const LIVE_KPI_DEFINITIONS = [
  {
    sensorId: "water_temp",
    sparkId: "liveSparkWaterTemp",
    trendId: "liveTempTrend",
    decimals: 1,
    deltaDecimals: 1,
    unit: "°F",
    historyHours: LIVE_SHORT_KPI_HISTORY_HOURS,
    summaryHours: 24,
  },
  {
    sensorId: "raw_ph",
    sparkId: "liveSparkPh",
    trendId: "livePhTrend",
    decimals: 2,
    deltaDecimals: 2,
    unit: "",
    historyHours: LIVE_SHORT_KPI_HISTORY_HOURS,
    summaryHours: 24,
  },
  {
    sensorId: "raw_orp",
    sparkId: "liveSparkOrp",
    trendId: "liveOrpTrend",
    decimals: 0,
    deltaDecimals: 0,
    unit: " mV",
    historyHours: LIVE_SHORT_KPI_HISTORY_HOURS,
    summaryHours: 24,
  },
  {
    sensorId: "pump_flow_gpm",
    sparkId: "liveSparkFlow",
    trendId: "liveFlowTrend",
    decimals: 1,
    deltaDecimals: 1,
    unit: " gpm",
    includeZero: true,
    historyHours: LIVE_SHORT_KPI_HISTORY_HOURS,
    summaryType: "flow-total",
  },
  {
    sensorId: "filter_flow_loss_percent",
    svgId: null,
    valueId: null,
    sparkId: "liveSparkFilter",
    trendId: "liveFilterTrend",
    decimals: 1,
    deltaDecimals: 1,
    unit: "%",
    includeZero: true,
    historyHours: LIVE_LONG_KPI_HISTORY_HOURS,
    summaryHours: 24 * 7,
  },
  {
    sensorId: "chlorine_tank_level_gal",
    svgId: null,
    valueId: null,
    sparkId: "liveSparkTank",
    trendId: "liveTankTrend",
    decimals: 2,
    deltaDecimals: 2,
    unit: " gal",
    includeZero: true,
    historyHours: LIVE_LONG_KPI_HISTORY_HOURS,
    summaryType: "chlorine-dose-total",
    usableInventory: true,
  },
];
const LIVE_TREND_DEFINITIONS = [
  {
    sensorId: "water_temp",
    svgId: "liveTrendWater",
    valueId: "liveTrendWaterValue",
    decimals: 1,
    unit: "°F",
  },
  {
    sensorId: "raw_ph",
    svgId: "liveTrendPh",
    valueId: "liveTrendPhValue",
    decimals: 2,
    unit: "",
  },
  {
    sensorId: "raw_orp",
    svgId: "liveTrendOrp",
    valueId: "liveTrendOrpValue",
    decimals: 0,
    unit: " mV",
  },
  {
    sensorId: "lab_free_chlorine",
    svgId: "liveTrendFc",
    valueId: "liveTrendFcValue",
    decimals: 2,
    unit: " ppm",
    includeZero: true,
  },
];

let historyLoading = false;
let lastHistoryLoadedAt = 0;
let lastHistoryKey = "";
let historyUntilMs = null;
let timerConfigLoading = false;
let timerConfigSaving = false;
let timerConfigDraft = null;
let timerEditProfileName = null;
let timerConfigDirty = false;
let faultLoading = false;
let lastFaultLoadedAt = 0;
let runtimeConfigLoading = false;
let safetyConfigLoading = false;
let filterLoadingConfigLoading = false;
let acquisitionConfigLoading = false;
let loggingConfigLoading = false;
let notificationsConfigLoading = false;
let analogConfigLoading = false;
let phSensorConfigLoading = false;
let chlorinationConfigLoading = false;
let fcDemandConfigLoading = false;
let chlorinationQuickSaving = false;
let chlorinationPrimeBusy = false;
let supplementalChlorineDoseBusy = false;
let timerOverrideBusy = false;
let scheduleProfileLoading = false;
let scheduleProfileBusy = false;
let scheduleProfileSelectionDirty = false;
let activeScheduleProfile = null;
let healthLoading = false;
let lastHealthLoadedAt = 0;
let topStatusLoading = false;
let lastTopStatusLoadedAt = 0;
let labTestLoading = false;
let chemicalAdditionLoading = false;
let chlorineTankRefillLoading = false;
let latestLivePayload = null;
let configAutoRefreshPaused = false;
let configDraftDirty = false;
let pumpPrimeThresholds = {
  primeMinPsi: 1.0,
};
let loadedRuntimeConfig = null;
let liveTrendLoading = false;
let lastLiveTrendLoadedAt = 0;
let liveTrendBandsLoaded = false;
let liveTrendBands = {};
let liveTrendChartState = [];
let liveTrendRenderState = null;
let liveTrendResizeTimer = null;

async function loadLive() {
  const response = await fetch("/api/live", { cache: "no-store" });
  const payload = await parseApiResponse(response, "live API failed");
  latestLivePayload = payload;
  setControllerConnectionState(true);
  render(payload);
  if (PAGE_MODE === "live") {
    void refreshLiveTrends(false);
  }
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

async function loadScheduleProfiles() {
  if (scheduleProfileLoading || scheduleProfileBusy) {
    return;
  }
  const select = document.getElementById("liveScheduleProfile");
  if (!select) {
    return;
  }

  scheduleProfileLoading = true;
  setScheduleProfileControlsDisabled(true);
  try {
    const response = await fetch("/api/schedule/active_profile", { cache: "no-store" });
    const payload = await parseApiResponse(response, "schedule profiles load failed");
    renderScheduleProfileControl(payload);
  } catch (error) {
    setCommandStatus(error.message);
  } finally {
    scheduleProfileLoading = false;
    updateScheduleProfileControlState();
  }
}

function renderScheduleProfileControl(payload) {
  const select = document.getElementById("liveScheduleProfile");
  if (!select) {
    return;
  }
  const profiles = Array.isArray(payload.profiles) ? payload.profiles : [];
  activeScheduleProfile = String(payload.active_profile || "");
  select.replaceChildren();
  profiles.forEach((profileName) => {
    const option = document.createElement("option");
    option.value = String(profileName);
    option.textContent = String(profileName);
    select.appendChild(option);
  });
  if (profiles.includes(activeScheduleProfile)) {
    select.value = activeScheduleProfile;
  }
  scheduleProfileSelectionDirty = false;
}

function setScheduleProfileControlsDisabled(disabled) {
  const select = document.getElementById("liveScheduleProfile");
  const button = document.getElementById("liveScheduleProfileActivate");
  if (select) {
    select.disabled = disabled;
  }
  if (button) {
    button.disabled = disabled;
  }
}

function updateScheduleProfileControlState() {
  const select = document.getElementById("liveScheduleProfile");
  const button = document.getElementById("liveScheduleProfileActivate");
  if (!select || !button) {
    return;
  }
  const unavailable = scheduleProfileLoading || scheduleProfileBusy || select.options.length === 0;
  select.disabled = unavailable;
  button.disabled = unavailable || select.value === activeScheduleProfile;
}

async function activateScheduleProfile() {
  if (scheduleProfileBusy) {
    return;
  }
  const select = document.getElementById("liveScheduleProfile");
  if (!select || !select.value || select.value === activeScheduleProfile) {
    updateScheduleProfileControlState();
    return;
  }

  const profileName = select.value;
  scheduleProfileBusy = true;
  setScheduleProfileControlsDisabled(true);
  setCommandStatus(`Activating schedule ${profileName}...`);
  try {
    const response = await fetch("/api/schedule/active_profile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active_profile: profileName }),
    });
    const payload = await parseApiResponse(response, "schedule profile update failed");
    const config = payload.config || {};
    renderScheduleProfileControl({
      active_profile: payload.active_profile,
      profiles: (config.profiles || []).map((profile) => profile.name),
    });
    setCommandStatus(`Active schedule set to ${payload.active_profile}`);
  } catch (error) {
    setCommandStatus(error.message);
    scheduleProfileSelectionDirty = true;
  } finally {
    scheduleProfileBusy = false;
    updateScheduleProfileControlState();
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
        max_cycle_period_seconds: Number(current.max_cycle_period_seconds || 1800.0),
        min_cycle_on_seconds: Number(current.min_cycle_on_seconds || 5.0),
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

async function primeChlorinationPump() {
  if (chlorinationPrimeBusy) {
    return;
  }
  chlorinationPrimeBusy = true;
  setControlsDisabled(true);
  setChlorinationPrimeStatus("Starting diagnostic dosing pump prime...");
  try {
    const response = await fetch("/api/chlorination/prime", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ duration_s: 30.0 }),
    });
    const payload = await parseApiResponse(response, "dosing prime failed");
    const remaining = payload.prime && Number.isFinite(Number(payload.prime.remaining_s))
      ? Math.ceil(Number(payload.prime.remaining_s))
      : 30;
    setChlorinationPrimeStatus(`Diagnostic dosing pump prime active (${remaining}s)`);
    await loadLive();
  } catch (error) {
    setChlorinationPrimeStatus(error.message);
  } finally {
    setControlsDisabled(false);
    chlorinationPrimeBusy = false;
  }
}

async function startChlorinationCalibration() {
  if (chlorinationPrimeBusy) {
    return;
  }
  chlorinationPrimeBusy = true;
  setControlsDisabled(true);
  setChlorinationPrimeStatus("Starting dosing pump calibration test...");
  try {
    const response = await fetch("/api/chlorination/calibration", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        duration_s: 20.0 * 60.0,
        duty_cycle: 0.5,
        cycle_period_s: 120.0,
      }),
    });
    const payload = await parseApiResponse(response, "dosing calibration failed");
    const remaining = payload.prime && Number.isFinite(Number(payload.prime.remaining_s))
      ? Math.ceil(Number(payload.prime.remaining_s))
      : 1200;
    setChlorinationPrimeStatus(`Dosing pump calibration active (${remaining}s, 50% DC)`);
    await loadLive();
  } catch (error) {
    setChlorinationPrimeStatus(error.message);
  } finally {
    setControlsDisabled(false);
    chlorinationPrimeBusy = false;
  }
}

async function stopChlorinationDiagnostic() {
  if (chlorinationPrimeBusy) {
    return;
  }
  chlorinationPrimeBusy = true;
  setControlsDisabled(true);
  setChlorinationPrimeStatus("Stopping dosing pump diagnostic...");
  try {
    const response = await fetch("/api/chlorination/diagnostic_stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    await parseApiResponse(response, "dosing diagnostic stop failed");
    setChlorinationPrimeStatus("Dosing pump diagnostic stopped");
    await loadLive();
  } catch (error) {
    setChlorinationPrimeStatus(error.message);
  } finally {
    setControlsDisabled(false);
    chlorinationPrimeBusy = false;
  }
}

function supplementalChlorineDoseAmount(inputId) {
  const input = document.getElementById(inputId);
  if (!input) {
    return null;
  }
  const doseOz = Number(input.value);
  if (!Number.isFinite(doseOz) || doseOz <= 0) {
    setChlorinationQuickStatus("Extra dose must be greater than 0 oz");
    input.focus();
    return null;
  }
  return doseOz;
}

function openSupplementalChlorineConfirmation(inputId) {
  if (supplementalChlorineDoseBusy) {
    return;
  }
  const doseOz = supplementalChlorineDoseAmount(inputId);
  const dialog = document.getElementById("liveSupplementalConfirm");
  if (doseOz === null || !dialog) {
    return;
  }
  setNodeText(
    "liveSupplementalConfirmText",
    `Start a one-time ${doseOz.toFixed(1)} oz supplemental chlorine dose?`,
  );
  dialog.dataset.doseInputId = inputId;
  if (typeof dialog.showModal === "function") {
    dialog.showModal();
  } else {
    dialog.setAttribute("open", "");
  }
}

async function startSupplementalChlorineDose(inputId) {
  if (supplementalChlorineDoseBusy) {
    return;
  }
  const doseOz = supplementalChlorineDoseAmount(inputId);
  if (doseOz === null) {
    return;
  }

  const dialog = document.getElementById("liveSupplementalConfirm");
  if (dialog && dialog.open) {
    dialog.close();
  }

  supplementalChlorineDoseBusy = true;
  setChlorinationQuickStatus("Starting supplemental chlorine dose...");
  try {
    const response = await fetch("/api/chlorination/supplemental_dose", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dose_oz: doseOz }),
    });
    const payload = await parseApiResponse(response, "supplemental chlorine dose failed");
    const status = payload.supplemental_chlorine_dose || {};
    const planned = Number(status.planned_dose_oz);
    const remaining = Number(status.remaining_s);
    const plannedText = Number.isFinite(planned) ? `${planned.toFixed(1)} oz` : `${doseOz.toFixed(1)} oz`;
    const remainingText = Number.isFinite(remaining) ? `, ${formatDurationShort(remaining)} remaining` : "";
    setChlorinationQuickStatus(`Supplemental chlorine dose started (${plannedText}${remainingText})`);
    await loadLive();
  } catch (error) {
    setChlorinationQuickStatus(error.message);
  } finally {
    supplementalChlorineDoseBusy = false;
  }
}

async function stopSupplementalChlorineDose() {
  if (supplementalChlorineDoseBusy) {
    return;
  }

  supplementalChlorineDoseBusy = true;
  setChlorinationQuickStatus("Stopping supplemental chlorine dose...");
  try {
    const response = await fetch("/api/chlorination/supplemental_dose_stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    await parseApiResponse(response, "supplemental chlorine stop failed");
    setChlorinationQuickStatus("Supplemental chlorine dose stopped");
    await loadLive();
  } catch (error) {
    setChlorinationQuickStatus(error.message);
  } finally {
    supplementalChlorineDoseBusy = false;
  }
}

function setChlorinationPrimeStatus(message) {
  setChlorinationQuickStatus(message);
  setChlorinationConfigStatus(message);
}

function setChlorinationQuickStatus(message) {
  [
    "liveChlorinationStatus",
    "liveChemicalControlStatus",
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

function renderScheduleStatus(schedule) {
  const target = document.getElementById("liveScheduleStatus");
  if (!target) return;
  if (!schedule) {
    target.textContent = "Schedule: unavailable";
    return;
  }
  const active = (schedule.active_windows || []).map((window) => window.name);
  const activeText = active.length ? active.join(", ") : "idle";
  const nextText = schedule.next_transition
    ? new Date(schedule.next_transition).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    : "none";
  target.textContent = `${activeText} · next transition ${nextText}`;
  if (
    activeScheduleProfile !== null
    && schedule.active_profile !== activeScheduleProfile
    && !scheduleProfileLoading
    && !scheduleProfileBusy
    && !scheduleProfileSelectionDirty
  ) {
    void loadScheduleProfiles();
  }
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
  renderChlorinationStatus(payload.chlorination, payload.supplemental_chlorine_dose);
  renderFcDemandStatus(payload.fc_demand, payload.dosing_prime);
  renderTimerOverride(payload.timer_override);
  renderScheduleStatus(payload.schedule);
  if (PAGE_MODE !== "live") {
    return;
  }
  renderLiveCards(payload.sensors || {}, payload.actuators || {}, payload.flows || {}, payload.chlorine_supply);
  renderControlButtonStates(payload.actuators || {});
  renderTodaySchedule(payload.schedule, payload.observed_at);
  renderAttention(payload);
}

function renderTopStatus(payload) {
  const runtimeLine = document.getElementById("runtimeLine");
  if (runtimeLine) {
    const profile = payload.runtime ? String(payload.runtime.driver_profile || "controller") : "controller";
    runtimeLine.textContent = `${profile.replaceAll("_", " ")} controller`;
  }
  const updatedAt = document.getElementById("updatedAt");
  if (updatedAt) {
    updatedAt.textContent = `Updated: ${new Date(payload.observed_at).toLocaleString()}`;
  }
  renderHeaderFacts(payload);
  const restartButton = document.getElementById("configRestartService");
  if (restartButton) {
    const isPi = payload.runtime && payload.runtime.driver_profile === "raspberry_pi";
    restartButton.disabled = !isPi;
  }

  renderSafetyBadge(payload.safety);
  renderChlorineSupplyBadge(payload.chlorine_supply);
  renderCpuTempBadge(payload.runtime, payload.sensors || {});
  renderCpuLoadLine(payload.runtime, payload.sensors || {});
  renderCpuFanLine(payload.runtime, payload.sensors || {});
  renderLoopTimingLine(payload.loop || payload.tick || null);
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
    renderChlorinationStatus(payload.chlorination, payload.supplemental_chlorine_dose);
    renderFcDemandStatus(payload.fc_demand, payload.dosing_prime);
    renderTimerOverride(payload.timer_override);
    renderScheduleStatus(payload.schedule);
    lastTopStatusLoadedAt = now;
  } catch (error) {
    if (PAGE_MODE === "live") {
      setControllerConnectionState(false);
    }
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
  if (!badge) {
    return;
  }
  badge.classList.remove("ok", "fault", "is-neutral");

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

function setControllerConnectionState(online) {
  const badge = document.getElementById("controllerBadge");
  if (!badge) {
    return;
  }
  badge.classList.toggle("is-online", online);
  badge.classList.toggle("is-offline", !online);
  setNodeText("controllerStatusText", online ? "Controller online" : "Controller offline");
}

function renderHeaderFacts(payload) {
  const schedule = payload.schedule || {};
  setNodeText("headerProfile", schedule.active_profile || "No profile");

  const actuators = payload.actuators || {};
  const pump = actuatorState(actuators, "pump_motor", "off");
  const speed = pumpSpeedState(actuators);
  const booster = actuatorState(actuators, "booster_pump", "off");
  let mode = pump === "on" ? speed.toUpperCase() : "OFF";
  if (pump === "on" && booster === "on") {
    mode += " + booster";
  }
  mode += payload.timer_override && payload.timer_override.active ? " · manual" : " · auto";
  setNodeText("headerPumpMode", mode);
}

function renderChlorineSupplyBadge(chlorineSupply) {
  const badge = document.getElementById("chlorineSupplyBadge");
  if (!badge) {
    return;
  }

  badge.classList.remove("ok", "fault", "caution", "alarm", "invalid", "unknown");
  const status = chlorineSupply && chlorineSupply.status ? chlorineSupply.status : "unknown";
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
  badge.textContent =
    chlorineSupply && chlorineSupply.display
      ? chlorineSupply.display
      : "Usable chlorine remaining -- gallons, -- days";
  if (chlorineSupply && chlorineSupply.reason) {
    badge.title = chlorineSupply.reason;
  } else {
    badge.removeAttribute("title");
  }
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

function renderLoopTimingLine(loop) {
  const line = document.getElementById("loopTimingLine");
  if (!line) {
    return;
  }

  if (!loop) {
    line.textContent = "Loop: --";
    line.classList.remove("warning");
    return;
  }

  const tickDuration = numberOrNull(loop.tick_duration_s ?? loop.duration_s);
  const controlDuration = numberOrNull(loop.control_duration_s);
  const targetInterval = numberOrNull(loop.target_interval_s);
  const startJitter = numberOrNull(loop.start_jitter_s);
  const overrun = numberOrNull(loop.overrun_s);
  const parts = [];
  if (tickDuration !== null) {
    parts.push(`${formatMilliseconds(tickDuration)} tick`);
  }
  if (controlDuration !== null) {
    parts.push(`${formatMilliseconds(controlDuration)} control`);
  }
  if (targetInterval !== null) {
    parts.push(`${formatMilliseconds(targetInterval)} target`);
  }
  if (startJitter !== null && startJitter >= 0.05) {
    parts.push(`${formatMilliseconds(startJitter)} late`);
  } else if (overrun !== null && overrun >= 0.05) {
    parts.push(`${formatMilliseconds(overrun)} over`);
  }

  line.textContent = `Loop: ${parts.length ? parts.join(" / ") : "--"}`;
  line.classList.toggle(
    "warning",
    (startJitter !== null && startJitter >= 0.5) || (overrun !== null && overrun >= 0.5),
  );
}

function formatMilliseconds(seconds) {
  return `${Math.round(seconds * 1000)}ms`;
}

function formatDurationShort(seconds) {
  if (!Number.isFinite(seconds)) {
    return "--";
  }
  if (Math.abs(seconds) < 90) {
    return `${Math.round(seconds)}s`;
  }
  return `${(seconds / 60).toFixed(1)}m`;
}

function renderTimerOverride(override) {
  const statusNodes = [document.getElementById("liveTimerOverrideStatus")].filter(Boolean);
  const modeBadge = document.getElementById("liveTimerModeBadge");
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
    if (modeBadge) {
      modeBadge.textContent = "Automatic";
      modeBadge.classList.remove("is-manual");
    }
    return;
  }

  const until = override.until ? new Date(override.until).toLocaleString() : "manual clear";
  if (modeBadge) {
    modeBadge.textContent = "Manual override";
    modeBadge.classList.add("is-manual");
  }
  applyText(
    `Override ${override.pump_motor.toUpperCase()} ` +
    `(${override.pump_speed.toUpperCase()}, booster ${override.booster.toUpperCase()}) ` +
    `until ${until}`,
  );
}

function renderFreezeStatus(safety) {
  const nodes = [document.getElementById("liveFreezeStatus")].filter(Boolean);
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
    const source = freeze.active_source ? ` | ${freeze.active_source}` : " | temperature unavailable";
    const fallback = freeze.using_fallback ? " (fallback)" : "";
    setValue(`Freeze protection: idle${source}${fallback}`);
    return;
  }
  const hold = Number(freeze.hold_remaining_s || 0);
  const rounded = hold > 0 ? `${Math.ceil(hold)}s hold` : "release eligible";
  const observation = freeze.observation ? ` @ ${freeze.observation}` : "";
  const failSafe = freeze.fail_safe ? " FAIL-SAFE" : "";
  const fallback = freeze.using_fallback ? " fallback" : "";
  setValue(
    `Freeze${failSafe} ${String(freeze.latched_speed || "").toUpperCase()} ` +
    `(${rounded})${observation}${fallback}`,
  );
}

function renderCsiStatus(sensors) {
  const csi = sensors.calcium_saturation_index;
  const text = csi ? `CSI: ${csi.display}` : "CSI: --";
  const node = document.getElementById("csiStatus");
  if (node) {
    node.textContent = text;
  }
}

function renderChlorinationStatus(chlorination, supplementalDose) {
  const payload = chlorination || {};
  const supplemental = supplementalDose || {};
  const dose = Number(payload.daily_dose_oz);
  const doseText = Number.isFinite(dose) ? `Dose: ${dose.toFixed(1)} oz/day` : "Dose: -- oz/day";
  const duty = Number(payload.duty_cycle_percent);
  const available = Number(payload.available_runtime_min_per_day);
  const requested = Number(payload.requested_runtime_min_per_day);
  const onSeconds = Number(payload.cycle_on_seconds);
  const offSeconds = Number(payload.cycle_off_seconds);
  const cycleSuffix =
    Number.isFinite(onSeconds) && Number.isFinite(offSeconds) && duty > 0
      ? ` | ${onSeconds.toFixed(0)}s on / ${formatDurationShort(offSeconds)} off`
      : "";
  const dutyText =
    Number.isFinite(duty) && Number.isFinite(available) && Number.isFinite(requested)
      ? `Duty: ${duty.toFixed(1)}% | ${requested.toFixed(1)} / ${available.toFixed(0)} min${cycleSuffix}`
      : "Duty: --";
  const stateText = payload.active ? "ON" : "OFF";
  const reasonText = String(payload.reason || "idle");
  const warning = payload.warning ? ` | ${payload.warning}` : "";
  let statusText = `Chlorination: ${stateText} | ${reasonText}${warning}`;
  if (supplemental.active) {
    const phase = supplemental.phase === "circulating" ? "circulating" : "dosing";
    const planned = Number(supplemental.planned_dose_oz);
    const remaining = Number(supplemental.remaining_s);
    const dosePart = Number.isFinite(planned) ? `${planned.toFixed(1)} oz` : "-- oz";
    const remainingPart = Number.isFinite(remaining) ? ` | ${formatDurationShort(remaining)} left` : "";
    statusText = `Extra chlorine ${phase} | ${dosePart}${remainingPart}`;
  }

  [
    "liveChlorinationDoseDisplay",
  ].forEach((id) => setNodeText(id, doseText));
  [
    "liveChlorinationDutyStatus",
  ].forEach((id) => setNodeText(id, dutyText));
  [
    "liveChlorinationStatus",
  ].forEach((id) => setNodeText(id, statusText));
  [
    "liveChlorinationDoseInput",
  ].forEach((id) => {
    const input = document.getElementById(id);
    if (!input || document.activeElement === input || !Number.isFinite(dose)) {
      return;
    }
    input.value = dose.toFixed(1);
  });
}

function renderFcDemandStatus(fcDemand, dosingPrime) {
  const payload = fcDemand || {};
  const prime = dosingPrime || {};
  const nodes = [
    document.getElementById("liveFcDemandStatus"),
  ].filter(Boolean);
  if (!nodes.length) {
    return;
  }

  let text = "FC demand: disabled";
  if (payload.enabled && !payload.ready) {
    text = `FC demand: ${payload.reason || "waiting for test data"}`;
  } else if (payload.enabled && payload.ready) {
    const demand = Number(payload.latest_observed_demand_ppm_per_day);
    const baseline = Number(payload.baseline_demand_ppm_per_day ?? payload.weighted_maintenance_demand_ppm_per_day);
    const limitedBaseline = Number(payload.rate_limited_baseline_demand_ppm_per_day);
    const weather = Number(payload.weather_adjustment_ppm_per_day);
    const predicted = Number(payload.predicted_demand_ppm_per_day);
    const maintenance = Number(payload.maintenance_dose_oz_per_day);
    const dose = Number(payload.recommended_daily_dose_oz);
    const feedback = Number(payload.applied_feedback_dose_oz);
    const mode = String(payload.mode || "observe_only").replaceAll("_", " ");
    const confidence = String(payload.confidence || "learning");
    const latestTiming = String(payload.latest_fc_observation_timing || "unknown").replaceAll("_", " ");
    const pieces = [`FC demand: ${Number.isFinite(baseline) ? baseline.toFixed(2) : "--"} ppm/day baseline`];
    if (Number.isFinite(demand)) {
      pieces.push(`latest ${demand.toFixed(2)}`);
    }
    if (Number.isFinite(limitedBaseline) && Math.abs(limitedBaseline - baseline) > 0.005) {
      pieces.push(`limited ${limitedBaseline.toFixed(2)}`);
    }
    pieces.push(`weather ${Number.isFinite(weather) ? weather.toFixed(2) : "0.00"}`);
    if (Number.isFinite(predicted)) {
      pieces.push(`pred ${predicted.toFixed(2)}`);
    }
    if (latestTiming !== "unknown") {
      pieces.push(`latest ${latestTiming}`);
    }
    if (Number.isFinite(maintenance)) {
      pieces.push(`maint ${maintenance.toFixed(1)} oz/day`);
    }
    if (payload.feedback_active_today && Number.isFinite(feedback) && feedback !== 0) {
      pieces.push(`feedback ${feedback > 0 ? "+" : ""}${feedback.toFixed(1)} oz`);
    }
    pieces.push(`rec ${Number.isFinite(dose) ? dose.toFixed(1) : "--"} oz/day`);
    pieces.push(confidence);
    pieces.push(mode);
    text = pieces.join(" | ");
  }
  if (prime.active) {
    const remaining = Number(prime.remaining_s);
    const mode = prime.mode === "calibration" ? "Dosing calibration" : "Dosing prime";
    const dutyCycle = Number(prime.duty_cycle);
    const dutyText = prime.mode === "calibration" && Number.isFinite(dutyCycle)
      ? `, ${(dutyCycle * 100).toFixed(0)}% DC`
      : "";
    text = `${mode} active (${Number.isFinite(remaining) ? Math.ceil(remaining) : "--"}s${dutyText})`;
  }
  nodes.forEach((node) => {
    node.textContent = text;
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
    const notifyState =
      payload.notifications && payload.notifications.enabled
        ? payload.notifications.pushover && payload.notifications.pushover.configured
          ? "notify ready"
          : "notify not configured"
        : "notify disabled";
    line.textContent = `Health: ${payload.status} | Modbus errors: ${modbusErrors} | ${notifyState}`;
    lastHealthLoadedAt = now;
  } catch (error) {
    document.getElementById("healthLine").textContent = `Health error: ${error.message}`;
  } finally {
    healthLoading = false;
  }
}

function renderLiveCards(sensors, actuators, flows, chlorineSupply) {
  if (!document.getElementById("liveCardPanel")) {
    return;
  }

  renderLivePumpCard(sensors, actuators, flows);
  renderLiveFilterCard(sensors, flows);
  renderLiveChemCard(sensors);
  renderLiveTankCard(sensors, chlorineSupply);
}

function renderLivePumpCard(sensors, actuators, flows) {
  const pumpState = actuators.pump_motor ? actuators.pump_motor.state : null;
  const speedState = actuators.pump_motor_speed ? actuators.pump_motor_speed.state : null;
  const pumpPsi = sensors.pump_output_psi ? Number(sensors.pump_output_psi.value) : Number.NaN;
  const primeMinPsi = Number(pumpPrimeThresholds.primeMinPsi || 1.0);
  const pumpIsAlarm =
    pumpState === "on" &&
    Number.isFinite(pumpPsi) &&
    pumpPsi < primeMinPsi;

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

  const flow = flows.pump_flow_gpm || {};
  setLiveCardStatus("livePumpCard", cardStatus);
  setNumericReading("livePumpFlow", flow.value, 1);
  setNodeText("liveFlowUnit", flow.unit || "gpm");
  setNodeText(
    "livePumpState",
    `${stateText} · output ${sensorDisplay(sensors, "pump_output_psi")}`,
  );
  setNodeText(
    "livePumpPsi",
    `Pump output: ${sensorDisplay(sensors, "pump_output_psi")} | Dynamic head: ${flowDisplay(flows, "pump_dynamic_head_psi")}`,
  );
}

function renderLiveFilterCard(sensors, flows) {
  const filterLoading = flows && flows.filter_loading ? flows.filter_loading : null;
  const status = filterLoading && filterLoading.status ? String(filterLoading.status) : "uncalibrated";
  let cardStatus = "status-off";
  if (status === "red") {
    cardStatus = "status-alarm";
  } else if (status === "yellow") {
    cardStatus = "status-caution";
  } else if (status === "green") {
    cardStatus = "status-on";
  }
  setLiveCardStatus("liveFilterCard", cardStatus);

  const statusText = status.charAt(0).toUpperCase() + status.slice(1);
  const completedAt = filterLoading && filterLoading.completed_at ? new Date(filterLoading.completed_at) : null;
  const ageText =
    filterLoading && Number.isFinite(Number(filterLoading.age_seconds))
      ? `${formatDurationShort(Number(filterLoading.age_seconds))} old`
      : "--";
  const completedText = completedAt && !Number.isNaN(completedAt.getTime())
    ? `${completedAt.toLocaleString()} / ${ageText}`
    : "--";

  const flowLoss = flows.filter_flow_loss_percent || {};
  setNumericReading("liveFilterFlowLoss", flowLoss.value, 1);
  setNodeText("liveFilterUnit", "%");
  const filterStatusLabels = {
    green: "Within clean-flow target",
    yellow: "Cleaning should be planned",
    red: "Filter needs attention",
    uncalibrated: "Awaiting a calibrated filter test",
  };
  setNodeText("liveFilterStatus", filterStatusLabels[status] || statusText);
  setNodeText("liveFilterEstimatedFlow", `Estimated reference flow: ${flowDisplay(flows, "filter_reference_flow_gpm")}`);
  setNodeText(
    "liveFilterCleanFlow",
    `Clean reference flow: ${filterLoading ? filterLoading.clean_flow_display || "--" : "--"}`,
  );
  setNodeText("liveFilterReferencePsi", `Reference pressure: ${flowDisplay(flows, "filter_reference_psi")}`);
  setNodeText("liveFilterLastTest", `Last standardized test: ${completedText}`);
}

function renderLiveChemCard(sensors) {
  const water = sensors.water_temp || null;
  const ph = sensors.raw_ph || null;
  const orp = sensors.raw_orp || null;
  setLiveCardStatus("liveChemCard", sensorCardStatus(sensorStatus(sensors, "water_temp")));
  setLiveCardStatus("livePhCard", sensorCardStatus(sensorStatus(sensors, "raw_ph")));
  setLiveCardStatus("liveOrpCard", sensorCardStatus(sensorStatus(sensors, "raw_orp")));

  setNumericReading("liveTempValue", water && water.value, 1);
  setNodeText("liveTempUnit", temperatureUnit(water && water.unit));
  setNodeText("liveTempLine", sensorSummary(water, "Water temperature unavailable"));
  setNodeText("liveTrendWaterValue", water && water.display ? water.display : "--");

  setNumericReading("livePhValue", ph && ph.value, 2);
  setNodeText("livePhLine", sensorSummary(ph, `Probe temp ${sensorDisplay(sensors, "ph_temp")}`));
  setNodeText("liveTrendPhValue", ph && ph.display ? ph.display : "--");

  setNumericReading("liveOrpValue", orp && orp.value, 0);
  setNodeText("liveOrpLine", sensorSummary(orp, `Probe temp ${sensorDisplay(sensors, "orp_temp")}`));
  setNodeText("liveTrendOrpValue", orp && orp.display ? orp.display : "--");
  setNodeText("liveCsiLine", `CSI: ${sensorDisplay(sensors, "calcium_saturation_index")}`);
}

function renderLiveTankCard(sensors, chlorineSupply) {
  const sensorId = sensors.chlorine_tank_level_gal ? "chlorine_tank_level_gal" : "tank_level";
  const supplyStatus = chlorineSupply && chlorineSupply.status ? chlorineSupply.status : sensorStatus(sensors, sensorId);
  setLiveCardStatus("liveTankCard", sensorCardStatus(supplyStatus));
  setNumericReading(
    "liveTankDaysLine",
    chlorineSupply && chlorineSupply.usable_remaining_gal,
    2,
  );
  setNodeText("liveTankUnit", "gal");
  const days =
    chlorineSupply && chlorineSupply.days_remaining_display
      ? chlorineSupply.days_remaining_display
      : "-- days";
  setNodeText("liveTankLevelLine", `${days} estimated remaining`);
}

function setNumericReading(id, value, decimals) {
  const parsed = value === null || value === undefined ? Number.NaN : Number(value);
  setNodeText(id, Number.isFinite(parsed) ? parsed.toFixed(decimals) : "--");
}

function temperatureUnit(unit) {
  if (unit === "degC") {
    return "°C";
  }
  return "°F";
}

function sensorSummary(sensor, fallback) {
  if (!sensor) {
    return fallback;
  }
  const labels = {
    normal: "In expected range",
    caution: "Outside the preferred range",
    alarm: "Needs attention",
    invalid: "Reading unavailable",
    unknown: "Status unavailable",
  };
  return labels[String(sensor.status || "unknown")] || fallback;
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

function sensorStatusClass(status) {
  const className = `status-${status}`;
  return SENSOR_STATUS_CLASSES.includes(className) ? className : "status-unknown";
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

function setLiveCardStatus(cardId, statusClass) {
  const card = document.getElementById(cardId);
  if (!card) {
    return;
  }
  card.classList.remove("status-off", "status-on", "status-low", "status-high", "status-caution", "status-alarm", "status-invalid");
  card.classList.add(statusClass);
}

async function refreshLiveTrends(force) {
  const status = document.getElementById("liveTrendsStatus");
  if (!status || liveTrendLoading) {
    return;
  }
  const now = Date.now();
  if (!force && now - lastLiveTrendLoadedAt < 60000) {
    return;
  }

  liveTrendLoading = true;
  if (!lastLiveTrendLoadedAt) {
    status.textContent = "Loading validated history…";
  }
  try {
    const shortKpiParams = liveHistoryParams(
      LIVE_SHORT_KPI_HISTORY_HOURS,
      LIVE_KPI_DEFINITIONS
        .filter((definition) => definition.historyHours === LIVE_SHORT_KPI_HISTORY_HOURS)
        .map((definition) => definition.sensorId),
      1500,
    );
    const longKpiParams = liveHistoryParams(
      LIVE_LONG_KPI_HISTORY_HOURS,
      LIVE_KPI_DEFINITIONS
        .filter((definition) => definition.historyHours === LIVE_LONG_KPI_HISTORY_HOURS)
        .map((definition) => definition.sensorId),
      720,
    );
    const trendParams = liveHistoryParams(
      LIVE_TREND_HISTORY_HOURS,
      [
        ...LIVE_TREND_DEFINITIONS.map((definition) => definition.sensorId),
        LIVE_CHLORINE_DELIVERY_SENSOR_ID,
        ...LIVE_EVENT_SENSOR_IDS,
      ],
      1000,
    );
    const requests = [
      fetch(`/api/history?${shortKpiParams.toString()}`, { cache: "no-store" }),
      fetch(`/api/history?${longKpiParams.toString()}`, { cache: "no-store" }),
      fetch(`/api/history?${trendParams.toString()}`, { cache: "no-store" }),
    ];
    if (!liveTrendBandsLoaded) {
      requests.push(fetch("/api/config/notifications", { cache: "no-store" }));
    }
    const responses = await Promise.all(requests);
    const [shortHistory, longHistory, trendHistory] = await Promise.all([
      parseApiResponse(responses[0], "24-hour KPI history failed"),
      parseApiResponse(responses[1], "30-day KPI history failed"),
      parseApiResponse(responses[2], "live trend history failed"),
    ]);
    if (responses[3]) {
      try {
        const config = await parseApiResponse(responses[3], "trend limits load failed");
        liveTrendBands = trendBandsFromNotifications(config);
      } catch (_error) {
        liveTrendBands = {};
      }
      liveTrendBandsLoaded = true;
    }
    renderLiveTrendDashboard({
      shortSeries: normalizeHistorySeries(shortHistory),
      shortWindow: historyWindowFromPayload(shortHistory),
      longSeries: normalizeHistorySeries(longHistory),
      longWindow: historyWindowFromPayload(longHistory),
      trendSeries: normalizeHistorySeries(trendHistory),
      trendWindow: historyWindowFromPayload(trendHistory),
    });
    lastLiveTrendLoadedAt = now;
    const totalPoints = [shortHistory, longHistory, trendHistory]
      .flatMap((history) => normalizeHistorySeries(history))
      .reduce((sum, series) => sum + (series.points || []).length, 0);
    status.textContent = totalPoints
      ? `${totalPoints} validated samples loaded for the aligned 7-day window`
      : "No validated history is available yet; current values will continue to update.";
  } catch (error) {
    status.textContent = `Trend history unavailable: ${error.message}`;
  } finally {
    liveTrendLoading = false;
  }
}

function liveHistoryParams(hours, sensorIds, maxPoints) {
  const params = new URLSearchParams({
    hours: String(hours),
    limit: String(historyQueryLimit(hours)),
    validated_only: "true",
    max_points: String(maxPoints),
    resolution: "auto",
  });
  [...new Set(sensorIds)].forEach((sensorId) => params.append("sensor_id", sensorId));
  return params;
}

function trendBandsFromNotifications(config) {
  const alerts = config && config.alerts ? config.alerts : {};
  const result = {};
  [
    ["raw_ph", alerts.ph],
    ["raw_orp", alerts.orp],
  ].forEach(([sensorId, rule]) => {
    if (!rule || rule.enabled === false) {
      return;
    }
    const minimum = numberOrNull(rule.caution_below);
    const maximum = numberOrNull(rule.caution_above);
    if (minimum !== null && maximum !== null && maximum > minimum) {
      result[sensorId] = { minimum, maximum };
    }
  });
  return result;
}

function renderLiveTrendDashboard(renderState) {
  liveTrendRenderState = renderState;
  const shortById = liveSeriesById(renderState.shortSeries);
  const longById = liveSeriesById(renderState.longSeries);
  const trendById = liveSeriesById(renderState.trendSeries);
  const fallbackEnd = historyReferenceNowMs();
  const trendWindow = renderState.trendWindow || {
    startMs: fallbackEnd - LIVE_TREND_HISTORY_HOURS * 3600 * 1000,
    endMs: fallbackEnd,
  };
  const shortWindow = renderState.shortWindow || {
    startMs: fallbackEnd - LIVE_SHORT_KPI_HISTORY_HOURS * 3600 * 1000,
    endMs: fallbackEnd,
  };
  const longWindow = renderState.longWindow || {
    startMs: fallbackEnd - LIVE_LONG_KPI_HISTORY_HOURS * 3600 * 1000,
    endMs: fallbackEnd,
  };
  const events = LIVE_EVENT_SENSOR_IDS.flatMap((sensorId) => {
    const entry = trendById[sensorId];
    return entry ? entry.points || [] : [];
  });
  const chlorineDeliveryPoints = normalizedLivePoints(
    (trendById[LIVE_CHLORINE_DELIVERY_SENSOR_ID] || { points: [] }).points,
  );
  const chlorineReserve = numberOrNull(
    latestLivePayload && latestLivePayload.chlorine_supply
      ? latestLivePayload.chlorine_supply.reserve_gal
      : null,
  ) || 0;

  liveTrendChartState = [];
  LIVE_KPI_DEFINITIONS.forEach((definition) => {
    const usesLongHistory = definition.historyHours === LIVE_LONG_KPI_HISTORY_HOURS;
    const byId = usesLongHistory ? longById : shortById;
    const window = usesLongHistory ? longWindow : shortWindow;
    const entry = byId[definition.sensorId] || { points: [] };
    let points = normalizedLivePoints(entry.points || []).filter(
      (point) => point._time >= window.startMs && point._time <= window.endMs,
    );
    if (definition.usableInventory) {
      points = points.map((point) => ({
        ...point,
        _value: Math.max(0, point._value - chlorineReserve),
      }));
    }
    drawLiveSparkline(definition, points, window);
    renderLiveKpiSummary(definition, points, chlorineDeliveryPoints, window);
  });
  LIVE_TREND_DEFINITIONS.forEach((definition, index) => {
    const entry = trendById[definition.sensorId] || { points: [] };
    const points = normalizedLivePoints(entry.points || []);
    const latest = points[points.length - 1];
    setNodeText(
      definition.valueId,
      latest
        ? latest.display || `${latest._value.toFixed(definition.decimals)}${definition.unit}`
        : "--",
    );
    drawLiveTrendStrip(
      definition,
      points,
      events,
      trendWindow,
      index === LIVE_TREND_DEFINITIONS.length - 1,
    );
  });
}

function liveSeriesById(series) {
  const byId = {};
  (series || []).forEach((entry) => {
    byId[entry.sensor_id] = entry;
  });
  return byId;
}

function normalizedLivePoints(points) {
  return points
    .map((point) => {
      const value = Number(point.value);
      const time = new Date(point.observed_at).getTime();
      if (!Number.isFinite(value) || !Number.isFinite(time)) {
        return null;
      }
      return { ...point, _value: value, _time: time };
    })
    .filter((point) => point !== null)
    .sort((left, right) => left._time - right._time);
}

function drawLiveSparkline(definition, points, window) {
  const chart = document.getElementById(definition.sparkId);
  if (!chart) {
    return;
  }
  chart.replaceChildren();
  const width = 180;
  const height = 44;
  const padding = 3;
  if (!points.length) {
    chart.appendChild(svgLine(padding, height / 2, width - padding, height / 2, "sparkline-empty"));
    return;
  }
  const domain = liveValueDomain(definition, points);
  const coordinates = points.map((point) => ({
    x: padding + ((point._time - window.startMs) / (window.endMs - window.startMs)) * (width - padding * 2),
    y: padding + (1 - (point._value - domain.minimum) / (domain.maximum - domain.minimum)) * (height - padding * 2),
  }));
  const area = document.createElementNS(SVG_NS, "polygon");
  area.setAttribute("class", "sparkline-area");
  area.setAttribute(
    "points",
    `${coordinates[0].x.toFixed(1)},${height - padding} ` +
      coordinates.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ") +
      ` ${coordinates[coordinates.length - 1].x.toFixed(1)},${height - padding}`,
  );
  chart.appendChild(area);
  const line = document.createElementNS(SVG_NS, "polyline");
  line.setAttribute("class", "sparkline-line");
  line.setAttribute(
    "points",
    coordinates.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" "),
  );
  chart.appendChild(line);
}

function renderLiveKpiSummary(definition, points, chlorineDeliveryPoints, historyWindow) {
  if (!definition.trendId) {
    return;
  }

  if (definition.summaryType === "flow-total") {
    const totalGallons = integratedFlowGallons(points, historyWindow);
    setNodeText(
      definition.trendId,
      totalGallons === null
        ? "24h total unavailable"
        : `Estimated 24h total: ${Math.round(totalGallons).toLocaleString()} gal`,
    );
    return;
  }

  if (definition.summaryType === "chlorine-dose-total") {
    const totalOunces = cumulativeCounterIncrease(chlorineDeliveryPoints);
    setNodeText(
      definition.trendId,
      totalOunces === null
        ? "7-day dose unavailable"
        : `Dosed last 7 days: ${totalOunces.toFixed(1)} fl oz`,
    );
    return;
  }

  const summaryHours = definition.summaryHours || 24;
  const summaryStart = historyWindow.endMs - summaryHours * 3600 * 1000;
  const summaryPoints = points.filter((point) => point._time >= summaryStart);
  const periodLabel = summaryHours === 24 ? "24 hours" : `${summaryHours / 24} days`;
  if (summaryPoints.length < 2) {
    setNodeText(
      definition.trendId,
      summaryPoints.length ? "Latest logged sample" : `${periodLabel} trend unavailable`,
    );
    return;
  }
  const change = summaryPoints[summaryPoints.length - 1]._value - summaryPoints[0]._value;
  const threshold = 0.5 * 10 ** (-definition.deltaDecimals);
  if (Math.abs(change) < threshold) {
    setNodeText(definition.trendId, `Steady over ${periodLabel}`);
    return;
  }
  const direction = change > 0 ? "↑" : "↓";
  setNodeText(
    definition.trendId,
    `${direction} ${Math.abs(change).toFixed(definition.deltaDecimals)}${definition.unit} over ${periodLabel}`,
  );
}

function integratedFlowGallons(points, window) {
  if (!window || points.length < 2) {
    return null;
  }
  let totalGallons = 0;
  for (let index = 1; index < points.length; index += 1) {
    const previous = points[index - 1];
    const current = points[index];
    const startMs = Math.max(window.startMs, previous._time);
    const endMs = Math.min(window.endMs, current._time);
    const elapsedMs = endMs - startMs;
    if (elapsedMs <= 0 || elapsedMs > 5 * 60 * 1000) {
      continue;
    }
    const averageGpm = (Math.max(0, previous._value) + Math.max(0, current._value)) / 2;
    totalGallons += averageGpm * (elapsedMs / 60000);
  }
  return totalGallons;
}

function cumulativeCounterIncrease(points) {
  if (!points.length) {
    return null;
  }
  let total = Math.max(0, points[0]._value);
  for (let index = 1; index < points.length; index += 1) {
    const previous = Math.max(0, points[index - 1]._value);
    const current = Math.max(0, points[index]._value);
    total += current >= previous ? current - previous : current;
  }
  return total;
}

function liveValueDomain(definition, points) {
  const values = points.map((point) => point._value);
  const band = liveTrendBands[definition.sensorId];
  if (band) {
    values.push(band.minimum, band.maximum);
  }
  if (definition.includeZero) {
    values.push(0);
  }
  let minimum = Math.min(...values);
  let maximum = Math.max(...values);
  if (minimum === maximum) {
    const spread = Math.max(Math.abs(minimum) * 0.05, 1);
    minimum -= spread;
    maximum += spread;
  }
  const padding = (maximum - minimum) * 0.08;
  return { minimum: minimum - padding, maximum: maximum + padding };
}

function drawLiveTrendStrip(definition, points, events, window, showTimeAxis) {
  const chart = document.getElementById(definition.svgId);
  if (!chart) {
    return;
  }
  chart.replaceChildren();
  const bounds = chart.getBoundingClientRect();
  const width = Math.max(320, Math.round(bounds.width || 720));
  const height = Math.max(72, Math.round(bounds.height || 92));
  chart.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const margin = { top: 8, right: 10, bottom: showTimeAxis ? 20 : 7, left: 40 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const domain = points.length
    ? liveValueDomain(definition, points)
    : { minimum: 0, maximum: 1 };
  const xForTime = (time) => margin.left + ((time - window.startMs) / (window.endMs - window.startMs)) * plotWidth;
  const yForValue = (value) =>
    margin.top + plotHeight - ((value - domain.minimum) / (domain.maximum - domain.minimum)) * plotHeight;

  for (let index = 0; index <= 2; index += 1) {
    const y = margin.top + (plotHeight * index) / 2;
    chart.appendChild(svgLine(margin.left, y, width - margin.right, y, "live-trend-grid"));
  }

  const band = liveTrendBands[definition.sensorId];
  if (band) {
    const top = yForValue(Math.min(domain.maximum, band.maximum));
    const bottom = yForValue(Math.max(domain.minimum, band.minimum));
    const rectangle = document.createElementNS(SVG_NS, "rect");
    rectangle.setAttribute("class", "live-trend-band");
    rectangle.setAttribute("x", String(margin.left));
    rectangle.setAttribute("y", String(top));
    rectangle.setAttribute("width", String(plotWidth));
    rectangle.setAttribute("height", String(Math.max(0, bottom - top)));
    chart.appendChild(rectangle);
  }

  chart.appendChild(
    svgText(formatAxisTick(domain.maximum, domain.maximum - domain.minimum), margin.left - 6, margin.top + 4, "live-trend-axis", "end"),
  );
  chart.appendChild(
    svgText(formatAxisTick(domain.minimum, domain.maximum - domain.minimum), margin.left - 6, margin.top + plotHeight, "live-trend-axis", "end"),
  );

  if (points.length) {
    const coordinates = points.map((point) => ({
      x: xForTime(point._time),
      y: yForValue(point._value),
    }));
    const area = document.createElementNS(SVG_NS, "polygon");
    area.setAttribute("class", "live-trend-area");
    area.setAttribute(
      "points",
      `${coordinates[0].x.toFixed(1)},${margin.top + plotHeight} ` +
        coordinates.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ") +
        ` ${coordinates[coordinates.length - 1].x.toFixed(1)},${margin.top + plotHeight}`,
    );
    chart.appendChild(area);
    const line = document.createElementNS(SVG_NS, "polyline");
    line.setAttribute("class", "live-trend-line");
    line.setAttribute(
      "points",
      coordinates.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" "),
    );
    chart.appendChild(line);
  } else {
    chart.appendChild(svgText("No logged data", margin.left + plotWidth / 2, margin.top + plotHeight / 2, "live-trend-empty"));
  }

  normalizedLivePoints(events).forEach((event) => {
    if (event._time < window.startMs || event._time > window.endMs) {
      return;
    }
    const marker = svgLine(
      xForTime(event._time),
      margin.top,
      xForTime(event._time),
      margin.top + plotHeight,
      "live-trend-event",
    );
    const title = document.createElementNS(SVG_NS, "title");
    title.textContent = `Chemical event · ${event.display || event.value} · ${new Date(event._time).toLocaleString()}`;
    marker.appendChild(title);
    chart.appendChild(marker);
  });

  if (showTimeAxis) {
    [0, 0.5, 1].forEach((ratio) => {
      const timestamp = window.startMs + (window.endMs - window.startMs) * ratio;
      const anchor = ratio === 0 ? "start" : ratio === 1 ? "end" : "middle";
      chart.appendChild(
        svgText(
          formatLiveTrendAxisLabel(timestamp, window),
          margin.left + plotWidth * ratio,
          height - 4,
          "live-trend-axis",
          anchor,
        ),
      );
    });
  }

  const hoverLine = svgLine(margin.left, margin.top, margin.left, margin.top + plotHeight, "live-trend-hover");
  hoverLine.style.display = "none";
  chart.appendChild(hoverLine);
  const hoverDot = document.createElementNS(SVG_NS, "circle");
  hoverDot.setAttribute("class", "live-trend-hover-dot");
  hoverDot.setAttribute("r", "3.5");
  hoverDot.style.display = "none";
  chart.appendChild(hoverDot);

  const state = {
    chart,
    definition,
    points,
    window,
    margin,
    plotWidth,
    plotHeight,
    domain,
    hoverLine,
    hoverDot,
  };
  liveTrendChartState.push(state);
  chart.onpointermove = (event) => {
    const rectangle = chart.getBoundingClientRect();
    const chartX = ((event.clientX - rectangle.left) / rectangle.width) * width;
    const clampedX = Math.max(margin.left, Math.min(margin.left + plotWidth, chartX));
    const ratio = (clampedX - margin.left) / plotWidth;
    syncLiveTrendHover(window.startMs + ratio * (window.endMs - window.startMs));
  };
  chart.onpointerleave = clearLiveTrendHover;
}

function initializeLiveTrendResizeHandling() {
  window.addEventListener("resize", () => {
    window.clearTimeout(liveTrendResizeTimer);
    liveTrendResizeTimer = window.setTimeout(() => {
      if (liveTrendRenderState) {
        renderLiveTrendDashboard(liveTrendRenderState);
      }
    }, 100);
  });
}

function formatLiveTrendAxisLabel(timestamp, window) {
  if (window.endMs - window.startMs > 48 * 3600 * 1000) {
    return new Date(timestamp).toLocaleDateString([], {
      month: "short",
      day: "numeric",
    });
  }
  return new Date(timestamp).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function syncLiveTrendHover(timestamp) {
  setNodeText("liveTrendsHoverTime", new Date(timestamp).toLocaleString());
  liveTrendChartState.forEach((state) => {
    const x = state.margin.left + ((timestamp - state.window.startMs) / (state.window.endMs - state.window.startMs)) * state.plotWidth;
    state.hoverLine.style.display = "block";
    state.hoverLine.setAttribute("x1", String(x));
    state.hoverLine.setAttribute("x2", String(x));
    const nearest = nearestLivePoint(state.points, timestamp);
    if (!nearest) {
      state.hoverDot.style.display = "none";
      setNodeText(state.definition.valueId, "--");
      return;
    }
    const y =
      state.margin.top +
      state.plotHeight -
      ((nearest._value - state.domain.minimum) / (state.domain.maximum - state.domain.minimum)) * state.plotHeight;
    state.hoverDot.style.display = "block";
    state.hoverDot.setAttribute("cx", String(x));
    state.hoverDot.setAttribute("cy", String(y));
    setNodeText(
      state.definition.valueId,
      nearest.display || `${nearest._value.toFixed(state.definition.decimals)}${state.definition.unit}`,
    );
  });
}

function clearLiveTrendHover() {
  setNodeText("liveTrendsHoverTime", "Shared time range");
  liveTrendChartState.forEach((state) => {
    state.hoverLine.style.display = "none";
    state.hoverDot.style.display = "none";
    const latest = state.points[state.points.length - 1];
    setNodeText(
      state.definition.valueId,
      latest
        ? latest.display || `${latest._value.toFixed(state.definition.decimals)}${state.definition.unit}`
        : "--",
    );
  });
}

function nearestLivePoint(points, timestamp) {
  if (!points.length) {
    return null;
  }
  let nearest = points[0];
  let distance = Math.abs(nearest._time - timestamp);
  for (let index = 1; index < points.length; index += 1) {
    const candidateDistance = Math.abs(points[index]._time - timestamp);
    if (candidateDistance < distance) {
      nearest = points[index];
      distance = candidateDistance;
    }
  }
  return nearest;
}

function renderTodaySchedule(schedule, observedAt) {
  const container = document.getElementById("todayTimeline");
  if (!container) {
    return;
  }
  container.replaceChildren();
  const today = schedule && schedule.today;
  if (!today) {
    const empty = document.createElement("div");
    empty.className = "timeline-empty";
    empty.textContent = "The resolved schedule is unavailable.";
    container.appendChild(empty);
    return;
  }

  const scale = document.createElement("div");
  scale.className = "timeline-scale";
  const scaleSpacer = document.createElement("span");
  const scaleLabels = document.createElement("div");
  scaleLabels.className = "timeline-scale-labels";
  ["12a", "6a", "12p", "6p", "12a"].forEach((labelText) => {
    const label = document.createElement("span");
    label.textContent = labelText;
    scaleLabels.appendChild(label);
  });
  scale.append(scaleSpacer, scaleLabels);
  container.appendChild(scale);

  const scheduleTrack = appendScheduleTimelineRow(container, "Mode");
  const windows = Array.isArray(today.windows) ? today.windows : [];
  windows.forEach((window) => {
    const state = resolvedScheduleDisplayState(window);
    appendScheduleSegment(scheduleTrack, window, state.className, state.label, today.local_date);
  });

  const clock = zonedClockParts(observedAt, today.timezone);
  if (clock && clock.localDate === today.local_date) {
    const marker = document.createElement("span");
    marker.className = "timeline-now";
    marker.style.left = `${Math.max(0, Math.min(100, (clock.minute / 1440) * 100))}%`;
    marker.title = `Current time ${clock.label}`;
    scheduleTrack.appendChild(marker);
  }

  [today.sunrise, today.sunset].forEach((timestamp) => {
    const minute = wallClockMinute(timestamp, today.local_date);
    if (minute === null || minute < 0 || minute > 1440) {
      return;
    }
    const marker = document.createElement("span");
    marker.className = "timeline-solar-marker";
    marker.style.left = `${(minute / 1440) * 100}%`;
    marker.title = `${timestamp === today.sunrise ? "Sunrise" : "Sunset"} ${formatWallClock(timestamp)}`;
    scheduleTrack.appendChild(marker);
  });
}

function resolvedScheduleDisplayState(window) {
  if (window.booster === "on") {
    return { className: "vacuum", label: "Vacuum" };
  }
  if (window.allow_dosing) {
    return { className: "dosing", label: "Dosing" };
  }
  if (window.pump_speed === "high") {
    return { className: "pump-high", label: "High" };
  }
  return { className: "pump-low", label: "Low" };
}

function appendScheduleTimelineRow(container, labelText) {
  const row = document.createElement("div");
  row.className = "timeline-row";
  const label = document.createElement("span");
  label.className = "timeline-row-label";
  label.textContent = labelText;
  const track = document.createElement("div");
  track.className = "timeline-track";
  row.append(label, track);
  container.appendChild(row);
  return track;
}

function appendScheduleSegment(track, window, className, stateLabel, localDate) {
  const start = wallClockMinute(window.start, localDate);
  const end = wallClockMinute(window.end, localDate);
  if (start === null || end === null || end <= 0 || start >= 1440) {
    return;
  }
  const clampedStart = Math.max(0, start);
  const clampedEnd = Math.min(1440, end);
  const segment = document.createElement("span");
  segment.className = `timeline-segment ${className}`;
  segment.style.left = `${(clampedStart / 1440) * 100}%`;
  segment.style.width = `${((clampedEnd - clampedStart) / 1440) * 100}%`;
  segment.title = `${stateLabel} · ${window.name}: ${formatWallClock(window.start)}–${formatWallClock(window.end)}`;
  track.appendChild(segment);
}

function wallClockMinute(timestamp, localDate) {
  if (!timestamp) {
    return null;
  }
  const match = String(timestamp).match(/^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})/);
  if (!match) {
    return null;
  }
  const offsetDays = calendarDayOffset(localDate, match[1]);
  return offsetDays * 1440 + Number(match[2]) * 60 + Number(match[3]);
}

function calendarDayOffset(baseDate, otherDate) {
  const base = String(baseDate).split("-").map(Number);
  const other = String(otherDate).split("-").map(Number);
  if (base.length !== 3 || other.length !== 3 || [...base, ...other].some((value) => !Number.isFinite(value))) {
    return 0;
  }
  return Math.round(
    (Date.UTC(other[0], other[1] - 1, other[2]) - Date.UTC(base[0], base[1] - 1, base[2])) / 86400000,
  );
}

function formatWallClock(timestamp) {
  const match = String(timestamp || "").match(/T(\d{2}):(\d{2})/);
  if (!match) {
    return "--";
  }
  const hour = Number(match[1]);
  const minute = match[2];
  const suffix = hour >= 12 ? "PM" : "AM";
  const displayHour = hour % 12 || 12;
  return `${displayHour}:${minute} ${suffix}`;
}

function zonedClockParts(timestamp, timezone) {
  if (!timestamp || !timezone) {
    return null;
  }
  try {
    const formatter = new Intl.DateTimeFormat("en-US", {
      timeZone: timezone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    });
    const parts = Object.fromEntries(
      formatter.formatToParts(new Date(timestamp)).map((part) => [part.type, part.value]),
    );
    return {
      localDate: `${parts.year}-${parts.month}-${parts.day}`,
      minute: Number(parts.hour) * 60 + Number(parts.minute),
      label: `${parts.hour}:${parts.minute}`,
    };
  } catch (_error) {
    return null;
  }
}

function renderAttention(payload) {
  const container = document.getElementById("attentionList");
  const count = document.getElementById("attentionCount");
  if (!container || !count) {
    return;
  }
  const items = [];
  const add = (level, text) => {
    if (text && !items.some((item) => item.text === text)) {
      items.push({ level, text });
    }
  };
  const safety = payload.safety || {};
  if (safety.locked_out) {
    add("alarm", `Safety lockout: ${safety.fault ? safety.fault.code : "controller output locked"}`);
  }
  const freeze = safety.freeze_protection || {};
  if (freeze.fail_safe) {
    add("alarm", "Freeze protection is in fail-safe mode because water temperature is unavailable.");
  }
  ["water_temp", "raw_ph", "raw_orp"].forEach((sensorId) => {
    const sensor = payload.sensors && payload.sensors[sensorId];
    if (!sensor || sensor.status === "normal" || sensor.status === "unknown") {
      return;
    }
    const level = sensor.status === "alarm" ? "alarm" : "warning";
    add(level, `${SENSOR_LABELS[sensorId] || sensorId}: ${sensor.display || "reading unavailable"}.`);
  });
  const filter = payload.flows && payload.flows.filter_loading;
  if (filter && filter.status === "red") {
    add("alarm", `Filter flow loss is ${filter.flow_loss_display || "above the alarm limit"}.`);
  } else if (filter && filter.status === "yellow") {
    add("warning", `Filter flow loss is ${filter.flow_loss_display || "above the planning limit"}; plan cleaning.`);
  } else if (filter && filter.status === "uncalibrated") {
    add("warning", "Filter loading is not calibrated; enter the clean reference flow after a standardized test.");
  }
  const supply = payload.chlorine_supply || {};
  if (supply.status === "alarm") {
    add("alarm", supply.display || "Chlorine supply is critically low.");
  } else if (supply.status === "caution") {
    add("warning", supply.display || "Chlorine supply is running low.");
  } else if (supply.status === "unknown" && supply.reason) {
    add("warning", `Chlorine supply estimate unavailable: ${supply.reason}.`);
  }
  const chlorination = payload.chlorination || {};
  if (chlorination.warning) {
    add("warning", `Chlorination: ${chlorination.warning}`);
  }
  const failures = payload.tick && Array.isArray(payload.tick.acquisition_failures)
    ? payload.tick.acquisition_failures
    : [];
  failures.slice(0, 3).forEach((failure) => {
    add("warning", `${failure.sensor_id || failure.driver || "Sensor"}: ${failure.error}`);
  });
  const warnings = payload.schedule && payload.schedule.today && Array.isArray(payload.schedule.today.warnings)
    ? payload.schedule.today.warnings
    : [];
  warnings.forEach((warning) => add("warning", `Schedule: ${warning}`));

  container.replaceChildren();
  count.textContent = String(items.length);
  count.classList.toggle("has-attention", items.length > 0);
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "attention-empty";
    empty.textContent = "No active safety, water-quality, supply, filter, or acquisition alerts.";
    container.appendChild(empty);
    return;
  }
  items.forEach((item) => {
    const node = document.createElement("div");
    node.className = "attention-item";
    node.dataset.level = item.level;
    node.textContent = item.text;
    container.appendChild(node);
  });
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
  ["liveCommandStatus"].forEach((id) => {
    const node = document.getElementById(id);
    if (node) {
      node.textContent = message;
    }
  });
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
  const untilIso = historyUntilMs === null ? "" : new Date(historyUntilMs).toISOString();
  const key = `${sensorIds.join(",")}:${hoursSelect.value}:${validatedOnly}:${untilIso}`;
  const now = Date.now();
  updateHistoryWindowControls();

  if (!sensorIds.length) {
    drawHistoryChartSeries([], currentHistoryWindow());
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
    if (untilIso) {
      params.set("until", untilIso);
    }
    sensorIds.forEach((sensorId) => params.append("sensor_id", sensorId));
    const response = await fetch(`/api/history?${params.toString()}`, { cache: "no-store" });
    const payload = await parseApiResponse(
      response,
      "history API failed",
      "History API unavailable. Restart the dashboard server.",
    );

    const series = normalizeHistorySeries(payload);
    drawHistoryChartSeries(series, historyWindowFromPayload(payload));
    lastHistoryKey = key;
    lastHistoryLoadedAt = now;
  } catch (error) {
    drawHistoryChartSeries([], currentHistoryWindow());
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

function drawHistoryChartSeries(series, windowInfo = null) {
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
    const windowLabel = windowInfo ? ` in ${historyWindowLabel(windowInfo)}` : "";
    status.textContent = `Waiting for loggable samples${windowLabel}`;
    return;
  }

  const times = allPoints.map((point) => point._time);
  let minTime = Math.min(...times);
  let maxTime = Math.max(...times);
  const windowStartMs = windowInfo ? Number(windowInfo.startMs) : NaN;
  const windowEndMs = windowInfo ? Number(windowInfo.endMs) : NaN;
  if (Number.isFinite(windowStartMs) && Number.isFinite(windowEndMs) && windowEndMs > windowStartMs) {
    minTime = windowStartMs;
    maxTime = windowEndMs;
  }

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

  const windowLabel = historyWindowLabel({ startMs: minTime, endMs: maxTime });
  status.textContent = `${allPoints.length} points across ${withAxes.length} sensors | ${windowLabel}`;
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

function currentHistoryWindow() {
  const hours = selectedHistoryHours();
  const endMs = historyUntilMs === null ? historyReferenceNowMs() : historyUntilMs;
  if (!Number.isFinite(hours) || hours <= 0 || !Number.isFinite(endMs)) {
    return null;
  }
  return {
    startMs: endMs - hours * 3600 * 1000,
    endMs,
  };
}

function historyWindowFromPayload(payload) {
  const startMs = payload && payload.since ? new Date(payload.since).getTime() : NaN;
  const endMs = payload && payload.until ? new Date(payload.until).getTime() : NaN;
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) {
    return currentHistoryWindow();
  }
  return { startMs, endMs };
}

function selectedHistoryHours() {
  const select = document.getElementById("historyHours");
  return select ? Number(select.value) : 24;
}

function historyReferenceNowMs() {
  const observedAt = latestLivePayload ? new Date(latestLivePayload.observed_at).getTime() : NaN;
  return Number.isFinite(observedAt) ? observedAt : Date.now();
}

function historyWindowLabel(windowInfo) {
  if (!windowInfo) {
    return "live window";
  }
  const start = new Date(windowInfo.startMs);
  const end = new Date(windowInfo.endMs);
  return `${start.toLocaleString()} to ${end.toLocaleString()}`;
}

function datetimeLocalValue(timestampMs) {
  const date = new Date(timestampMs);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60 * 1000);
  return local.toISOString().slice(0, 16);
}

function datetimeLocalIsoString(inputId, label) {
  const input = document.getElementById(inputId);
  const value = stringOrNull(input ? input.value : null);
  if (!value) {
    return null;
  }
  const parsedMs = new Date(value).getTime();
  if (!Number.isFinite(parsedMs)) {
    throw new Error(`${label} must be a valid local date/time`);
  }
  return new Date(parsedMs).toISOString();
}

function parseHistoryUntilInput() {
  const input = document.getElementById("historyUntil");
  if (!input || !input.value) {
    return null;
  }
  const parsed = new Date(input.value).getTime();
  return Number.isFinite(parsed) ? parsed : null;
}

function setHistoryUntil(timestampMs) {
  const now = historyReferenceNowMs();
  if (timestampMs === null || !Number.isFinite(timestampMs) || timestampMs >= now) {
    historyUntilMs = null;
  } else {
    historyUntilMs = timestampMs;
  }
  updateHistoryWindowControls();
  refreshHistory(true);
}

function shiftHistoryWindow(direction) {
  const hours = selectedHistoryHours();
  if (!Number.isFinite(hours) || hours <= 0) {
    return;
  }
  const baseMs = historyUntilMs === null ? historyReferenceNowMs() : historyUntilMs;
  setHistoryUntil(baseMs + direction * hours * 3600 * 1000);
}

function updateHistoryWindowControls() {
  const input = document.getElementById("historyUntil");
  const nextButton = document.getElementById("historyNextWindow");
  const nowButton = document.getElementById("historyNow");
  if (input) {
    if (document.activeElement !== input) {
      input.value = datetimeLocalValue(historyUntilMs === null ? historyReferenceNowMs() : historyUntilMs);
    }
  }
  if (nextButton) {
    nextButton.disabled = historyUntilMs === null;
  }
  if (nowButton) {
    nowButton.disabled = historyUntilMs === null;
  }
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
  if (historyUntilMs !== null) {
    params.set("until", new Date(historyUntilMs).toISOString());
  }
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

function optionalNumberValue(root, field) {
  const rawValue = String(fieldNode(root, field).value || "").trim();
  if (!rawValue) {
    return null;
  }
  const value = Number(rawValue);
  if (!Number.isFinite(value)) {
    throw new Error(`Invalid number for ${field}`);
  }
  return value;
}

function optionalIntValue(root, field) {
  const rawValue = String(fieldNode(root, field).value || "").trim();
  if (!rawValue) {
    return null;
  }
  const value = Number(rawValue);
  if (!Number.isInteger(value)) {
    throw new Error(`Invalid integer for ${field}`);
  }
  return value;
}

function initializeHistoryControls() {
  const checklist = document.getElementById("historySensorChecklist");
  HISTORY_SENSOR_ORDER.forEach((sensorId) => {
    const label = document.createElement("label");
    label.dataset.sensorId = sensorId;
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = sensorId;
    input.checked = DEFAULT_HISTORY_SENSOR_IDS.has(sensorId);
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

  document.getElementById("historyHours").addEventListener("change", () => {
    updateHistoryWindowControls();
    refreshHistory(true);
  });
  document.getElementById("historyValidity").addEventListener("change", () => refreshHistory(true));
  document.getElementById("historyPrevWindow").addEventListener("click", () => shiftHistoryWindow(-1));
  document.getElementById("historyNextWindow").addEventListener("click", () => shiftHistoryWindow(1));
  document.getElementById("historyApplyUntil").addEventListener("click", () => setHistoryUntil(parseHistoryUntilInput()));
  document.getElementById("historyNow").addEventListener("click", () => setHistoryUntil(null));
  document.getElementById("historyUntil").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      setHistoryUntil(parseHistoryUntilInput());
    }
  });
  document.getElementById("historyUntil").addEventListener("change", () => setHistoryUntil(parseHistoryUntilInput()));
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
  updateHistoryWindowControls();
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
  layer.classList.remove("timer-layer-disabled");
  layer.textContent = "Pump timer profiles and solar timing are enabled";

  const fallbackProfile = {
    name: payload.active_profile || "normal",
    schedules: Array.isArray(payload.schedules) ? payload.schedules : [],
  };
  timerConfigDraft = {
    site: {
      timezone: payload.site?.timezone || payload.timezone || "UTC",
      latitude: payload.site?.latitude ?? null,
      longitude: payload.site?.longitude ?? null,
    },
    active_profile: payload.active_profile || fallbackProfile.name,
    profiles: Array.isArray(payload.profiles) && payload.profiles.length
      ? JSON.parse(JSON.stringify(payload.profiles))
      : [fallbackProfile],
  };
  if (!timerConfigDraft.profiles.some((profile) => profile.name === timerEditProfileName)) {
    timerEditProfileName = timerConfigDraft.active_profile;
  }
  document.getElementById("timerTimezone").value = timerConfigDraft.site.timezone;
  document.getElementById("timerLatitude").value = timerConfigDraft.site.latitude ?? "";
  document.getElementById("timerLongitude").value = timerConfigDraft.site.longitude ?? "";
  renderTimerProfileSelectors();
  renderTimerProfileRows();
  timerConfigDirty = false;
  loadSchedulePreview();
}

const TIMER_MODE_FIELDS = Object.freeze({
  low: Object.freeze({ pump_speed: "low", booster: "off", allow_dosing: false }),
  high: Object.freeze({ pump_speed: "high", booster: "off", allow_dosing: false }),
  dosing: Object.freeze({ pump_speed: "low", booster: "off", allow_dosing: true }),
  vacuum: Object.freeze({ pump_speed: "low", booster: "on", allow_dosing: false }),
});

function timerModeFields(mode) {
  return TIMER_MODE_FIELDS[mode] || TIMER_MODE_FIELDS.low;
}

function timerModeForSchedule(schedule = {}) {
  const pumpSpeed = String(schedule.pump_speed || "low").toLowerCase();
  const booster = String(schedule.booster || "off").toLowerCase();
  const allowDosing = schedule.allow_dosing === true;
  let mode = "low";
  if (booster === "on") {
    mode = "vacuum";
  } else if (allowDosing) {
    mode = "dosing";
  } else if (pumpSpeed === "high") {
    mode = "high";
  }
  const expected = timerModeFields(mode);
  return {
    mode,
    canonical: pumpSpeed === expected.pump_speed
      && booster === expected.booster
      && allowDosing === expected.allow_dosing,
  };
}

function timerModeLabel(mode) {
  return mode.charAt(0).toUpperCase() + mode.slice(1);
}

function timerModeEditor(schedule) {
  const resolution = timerModeForSchedule(schedule);
  const field = document.createElement("div");
  field.className = "timer-mode-field";
  const select = document.createElement("select");
  select.dataset.field = "mode";
  Object.keys(TIMER_MODE_FIELDS).forEach((mode) => {
    const option = document.createElement("option");
    option.value = mode;
    option.textContent = timerModeLabel(mode);
    select.appendChild(option);
  });
  select.value = resolution.mode;
  field.appendChild(select);
  if (!resolution.canonical) {
    const warning = document.createElement("small");
    warning.className = "timer-mode-warning";
    warning.textContent = `Legacy combination will normalize to ${timerModeLabel(resolution.mode)} on save.`;
    field.appendChild(warning);
  }
  select.addEventListener("change", () => {
    field.querySelector(".timer-mode-warning")?.remove();
    field.closest(".timer-row").dataset.modeChanged = "true";
  });
  return field;
}

function timerRowElement(schedule = {
  pump_speed: "low",
  booster: "off",
  allow_dosing: false,
}) {
  const row = document.createElement("div");
  row.className = "timer-row";
  row.dataset.sourcePumpSpeed = String(schedule.pump_speed || "low").toLowerCase();
  row.dataset.sourceBooster = String(schedule.booster || "off").toLowerCase();
  row.dataset.sourceAllowDosing = schedule.allow_dosing === true ? "true" : "false";
  row.dataset.modeChanged = "false";

  row.appendChild(timerInput("name", schedule.name || "", "text"));
  row.appendChild(timerCheckbox("enabled", schedule.enabled !== false));
  row.appendChild(timerTimingEditor(schedule.timing || {
    type: "fixed",
    start: schedule.start || "08:00",
    end: schedule.end || "12:00",
  }));
  row.appendChild(timerModeEditor(schedule));

  const removeButton = document.createElement("button");
  removeButton.type = "button";
  removeButton.textContent = "Remove";
  removeButton.addEventListener("click", () => {
    row.remove();
    if (!document.querySelectorAll(".timer-row").length) {
      document.getElementById("timerRows").appendChild(timerRowElement());
    }
    markTimerConfigDirty();
  });
  row.appendChild(removeButton);

  return row;
}

function timerTimingEditor(timing) {
  const editor = document.createElement("div");
  editor.className = "timer-timing";
  editor.dataset.field = "timing";
  const type = timerSelect(
    "timing_type",
    ["fixed", "solar_anchor", "daylight_fraction"],
    timing.type || "fixed",
  );
  editor.appendChild(type);
  const fields = document.createElement("div");
  fields.className = "timer-timing-fields";
  editor.appendChild(fields);

  const renderFields = (value, source = {}) => {
    fields.replaceChildren();
    if (value === "fixed") {
      fields.appendChild(timerInput("timing_start", source.start || "08:00", "time"));
      const mode = timerSelect(
        "timing_fixed_mode",
        ["end", "duration"],
        source.duration_minutes == null ? "end" : "duration",
      );
      fields.appendChild(mode);
      const renderFixedValue = () => {
        while (fields.children.length > 2) fields.lastChild.remove();
        fields.appendChild(
          mode.value === "end"
            ? timerInput("timing_end", source.end || "12:00", "time")
            : timerInput("timing_duration_minutes", source.duration_minutes ?? 60, "number"),
        );
      };
      mode.addEventListener("change", renderFixedValue);
      renderFixedValue();
    } else if (value === "solar_anchor") {
      fields.appendChild(timerSelect(
        "timing_anchor",
        ["sunrise", "sunset", "daylight_midpoint"],
        source.anchor || "sunrise",
      ));
      fields.appendChild(timerInput("timing_offset_minutes", source.offset_minutes ?? 0, "number"));
      fields.appendChild(timerInput("timing_duration_minutes", source.duration_minutes ?? 60, "number"));
    } else {
      fields.appendChild(timerInput("timing_start_fraction", source.start_fraction ?? 0, "number"));
      fields.appendChild(timerInput("timing_end_fraction", source.end_fraction ?? 1, "number"));
    }
  };
  type.addEventListener("change", () => renderFields(type.value));
  renderFields(type.value, timing);
  return editor;
}

function timerInput(field, value, type) {
  const input = document.createElement("input");
  input.type = type;
  input.value = value;
  input.dataset.field = field;
  const placeholders = {
    timing_duration_minutes: "duration min",
    timing_offset_minutes: "offset min",
    timing_start_fraction: "start fraction",
    timing_end_fraction: "end fraction",
  };
  if (placeholders[field]) input.placeholder = placeholders[field];
  if (type === "number") {
    input.step = field.includes("fraction") ? "0.01" : "1";
  }
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

function timerCheckbox(field, checked) {
  const label = document.createElement("label");
  label.className = "timer-checkbox";

  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = checked;
  input.dataset.field = field;

  const span = document.createElement("span");
  span.textContent = checked ? "Yes" : "No";
  input.addEventListener("change", () => {
    span.textContent = input.checked ? "Yes" : "No";
  });

  label.appendChild(input);
  label.appendChild(span);
  return label;
}

function collectTimerSchedules() {
  const rows = [...document.querySelectorAll(".timer-row")];
  const schedules = rows.map((row, index) => {
    const name = row.querySelector('[data-field="name"]').value.trim();
    const enabled = row.querySelector('[data-field="enabled"]').checked;
    const mode = row.querySelector('[data-field="mode"]').value;
    const operatingFields = row.dataset.modeChanged === "true"
      ? timerModeFields(mode)
      : {
        pump_speed: row.dataset.sourcePumpSpeed,
        booster: row.dataset.sourceBooster,
        allow_dosing: row.dataset.sourceAllowDosing === "true",
      };
    const timingType = row.querySelector('[data-field="timing_type"]').value;
    let timing;
    if (timingType === "fixed") {
      timing = {
        type: "fixed",
        start: row.querySelector('[data-field="timing_start"]').value,
      };
      const fixedMode = row.querySelector('[data-field="timing_fixed_mode"]').value;
      if (fixedMode === "duration") {
        timing.duration_minutes = Number(
          row.querySelector('[data-field="timing_duration_minutes"]').value,
        );
      } else {
        timing.end = row.querySelector('[data-field="timing_end"]').value;
      }
    } else if (timingType === "solar_anchor") {
      timing = {
        type: "solar_anchor",
        anchor: row.querySelector('[data-field="timing_anchor"]').value,
        offset_minutes: Number(row.querySelector('[data-field="timing_offset_minutes"]').value),
        duration_minutes: Number(row.querySelector('[data-field="timing_duration_minutes"]').value),
      };
    } else {
      timing = {
        type: "daylight_fraction",
        start_fraction: Number(row.querySelector('[data-field="timing_start_fraction"]').value),
        end_fraction: Number(row.querySelector('[data-field="timing_end_fraction"]').value),
      };
    }

    return {
      name: name || `schedule_${index + 1}`,
      enabled,
      timing,
      ...operatingFields,
    };
  });

  return schedules;
}

function normalizedTimerProfiles(profiles) {
  return profiles.map((profile) => ({
    ...profile,
    schedules: (profile.schedules || []).map((schedule) => ({
      ...schedule,
      ...timerModeFields(timerModeForSchedule(schedule).mode),
    })),
  }));
}

function storeEditedTimerProfile() {
  if (!timerConfigDraft || !timerEditProfileName) return;
  const profile = timerConfigDraft.profiles.find((item) => item.name === timerEditProfileName);
  if (profile) profile.schedules = collectTimerSchedules();
}

function renderTimerProfileSelectors() {
  const active = document.getElementById("timerActiveProfile");
  const edit = document.getElementById("timerEditProfile");
  active.replaceChildren();
  edit.replaceChildren();
  timerConfigDraft.profiles.forEach((profile) => {
    [active, edit].forEach((select) => {
      const option = document.createElement("option");
      option.value = profile.name;
      option.textContent = profile.name;
      select.appendChild(option);
    });
  });
  active.value = timerConfigDraft.active_profile;
  edit.value = timerEditProfileName;
}

function renderTimerProfileRows() {
  const rows = document.getElementById("timerRows");
  rows.replaceChildren();
  const profile = timerConfigDraft.profiles.find((item) => item.name === timerEditProfileName);
  const schedules = profile?.schedules || [];
  if (!schedules.length) rows.appendChild(timerRowElement());
  else schedules.forEach((schedule) => rows.appendChild(timerRowElement(schedule)));
}

function optionalNumberValue(id) {
  const value = document.getElementById(id).value.trim();
  return value === "" ? null : Number(value);
}

async function savePumpTimerConfig() {
  if (timerConfigSaving) {
    return;
  }

  timerConfigSaving = true;
  setTimerStatus("Saving timer schedules...");
  setTimerButtonsDisabled(true);

  try {
    storeEditedTimerProfile();
    const response = await fetch("/api/config/pump_timer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        site: {
          timezone: document.getElementById("timerTimezone").value.trim() || "UTC",
          latitude: optionalNumberValue("timerLatitude"),
          longitude: optionalNumberValue("timerLongitude"),
        },
        active_profile: document.getElementById("timerActiveProfile").value,
        profiles: normalizedTimerProfiles(timerConfigDraft.profiles),
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

function markTimerConfigDirty() {
  if (timerConfigLoading || timerConfigSaving) {
    return;
  }
  timerConfigDirty = true;
  setTimerStatus("Unsaved schedule changes");
}

async function reloadSavedPumpTimerConfig() {
  if (timerConfigDirty && !window.confirm("Discard unsaved schedule changes and reload the saved schedule?")) {
    setTimerStatus("Reload canceled; unsaved schedule changes retained");
    return;
  }
  await loadPumpTimerConfig();
}

function setTimerButtonsDisabled(disabled) {
  document.getElementById("timerAddRow").disabled = disabled;
  document.getElementById("timerAddProfile").disabled = disabled;
  document.getElementById("timerRemoveProfile").disabled = disabled;
  document.getElementById("timerSave").disabled = disabled;
  document.getElementById("timerReload").disabled = disabled;
  document.getElementById("timerActiveProfile").disabled = disabled;
  document.getElementById("timerEditProfile").disabled = disabled;
}

async function loadSchedulePreview() {
  const target = document.getElementById("timerPreview");
  if (!target) return;
  target.textContent = "Loading resolved schedule...";
  try {
    const response = await fetch("/api/schedule/preview?days=3", { cache: "no-store" });
    const payload = await parseApiResponse(response, "schedule preview failed");
    const entries = [];
    (payload.days || []).forEach((day) => {
      entries.push(`${day.local_date} · sunrise ${formatScheduleInstant(day.sunrise)} · sunset ${formatScheduleInstant(day.sunset)}`);
      (day.windows || []).forEach((window) => {
        const mode = timerModeForSchedule(window).mode;
        entries.push(`  ${window.name}: ${formatScheduleInstant(window.start)}–${formatScheduleInstant(window.end)} · ${timerModeLabel(mode)}`);
      });
      (day.warnings || []).forEach((warning) => entries.push(`  Warning: ${warning}`));
    });
    target.textContent = entries.length ? entries.join("\n") : "No enabled windows.";
  } catch (error) {
    target.textContent = error.message;
  }
}

function formatScheduleInstant(value) {
  if (!value) return "--";
  return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function initializeTimerControls() {
  const panel = document.getElementById("pumpTimerPanel");
  ["input", "change"].forEach((eventName) => {
    panel.addEventListener(eventName, (event) => {
      if (event.target.id !== "timerEditProfile") {
        markTimerConfigDirty();
      }
    });
  });
  document.getElementById("timerAddRow").addEventListener("click", () => {
    document.getElementById("timerRows").appendChild(timerRowElement());
    markTimerConfigDirty();
  });
  document.getElementById("timerSave").addEventListener("click", savePumpTimerConfig);
  document.getElementById("timerReload").addEventListener("click", reloadSavedPumpTimerConfig);
  document.getElementById("timerPreviewReload").addEventListener("click", loadSchedulePreview);
  document.getElementById("timerEditProfile").addEventListener("change", (event) => {
    storeEditedTimerProfile();
    timerEditProfileName = event.target.value;
    renderTimerProfileRows();
  });
  document.getElementById("timerActiveProfile").addEventListener("change", (event) => {
    if (timerConfigDraft) timerConfigDraft.active_profile = event.target.value;
  });
  document.getElementById("timerAddProfile").addEventListener("click", () => {
    storeEditedTimerProfile();
    const name = window.prompt("New profile name")?.trim();
    if (!name) return;
    if (timerConfigDraft.profiles.some((profile) => profile.name === name)) {
      setTimerStatus(`Profile ${name} already exists`);
      return;
    }
    timerConfigDraft.profiles.push({ name, schedules: [] });
    timerEditProfileName = name;
    renderTimerProfileSelectors();
    renderTimerProfileRows();
    markTimerConfigDirty();
  });
  document.getElementById("timerRemoveProfile").addEventListener("click", () => {
    if (!timerConfigDraft || timerConfigDraft.profiles.length <= 1) {
      setTimerStatus("At least one profile is required");
      return;
    }
    timerConfigDraft.profiles = timerConfigDraft.profiles.filter(
      (profile) => profile.name !== timerEditProfileName,
    );
    if (!timerConfigDraft.profiles.some(
      (profile) => profile.name === timerConfigDraft.active_profile,
    )) {
      timerConfigDraft.active_profile = timerConfigDraft.profiles[0].name;
    }
    timerEditProfileName = timerConfigDraft.profiles[0].name;
    renderTimerProfileSelectors();
    renderTimerProfileRows();
    markTimerConfigDirty();
  });
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
    loadNotificationsConfig(),
    loadAnalogConfig(),
    loadPhSensorConfig(),
    loadChlorinationConfig(),
    loadFcDemandConfig(),
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
    loadedRuntimeConfig = payload;
    document.getElementById("runtimeDriverProfile").value = payload.driver_profile;
    setRuntimeStatus("Runtime config loaded");
  } catch (error) {
    setRuntimeStatus(error.message);
  } finally {
    runtimeConfigLoading = false;
  }
}

async function saveRuntimeConfig() {
  setRuntimeStatus("Saving runtime config...");
  const current = loadedRuntimeConfig || {};
  try {
    const response = await fetch("/api/config/runtime", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        driver_profile: document.getElementById("runtimeDriverProfile").value,
        enabled_actuators: current.enabled_actuators || ACTUATOR_ORDER,
        enabled_sensor_groups: current.enabled_sensor_groups || ["pressures", "chemistry_loop"],
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
    const tank = payload.chlorine_tank || {};
    document.getElementById("safetySensorPumpOutput").value = payload.pressure_sensor_ids.pump_output;
    document.getElementById("safetyFreezeEnabled").checked = Boolean(freeze.enabled);
    document.getElementById("safetyFreezePrimaryTempSensor").value =
      freeze.primary_temperature_sensor || "ph_temp";
    document.getElementById("safetyFreezeFallbackTempSensor").value =
      freeze.fallback_temperature_sensor || "orp_temp";
    document.getElementById("safetyFreezeMaxTempAge").value = String(
      freeze.max_temperature_age_seconds ?? 3600.0,
    );
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
    document.getElementById("safetyChlorineMinPump").value = payload.thresholds.chlorine_min_pump_output_psi;
    document.getElementById("safetyChlorineMaxPump").value = payload.thresholds.chlorine_max_pump_output_psi;
    document.getElementById("safetyChlorineTankLevelSensor").value =
      tank.level_sensor || "chlorine_tank_level_gal";
    document.getElementById("safetyChlorineTankWarningGal").value = String(tank.low_warning_gal ?? 2.0);
    document.getElementById("safetyChlorineTankInhibitGal").value = String(tank.inhibit_below_gal ?? 1.5);
    document.getElementById("safetyChlorineTankReenableGal").value = String(tank.reenable_at_gal ?? 2.0);
    document.getElementById("safetyPrimeMin").value = payload.thresholds.pump_prime_min_output_psi;
    document.getElementById("safetyOverpressure").value = payload.thresholds.pump_output_overpressure_psi;
    document.getElementById("safetyPumpOutputMaxAge").value = String(payload.timeouts.pump_output_max_age_seconds ?? 10.0);
    document.getElementById("safetyPrimeTimeout").value = payload.timeouts.pump_prime_timeout_s;
    pumpPrimeThresholds = {
      primeMinPsi: Number(payload.thresholds.pump_prime_min_output_psi ?? 1.0),
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
        },
        freeze_protection: {
          enabled: document.getElementById("safetyFreezeEnabled").checked,
          primary_temperature_sensor: document.getElementById("safetyFreezePrimaryTempSensor").value,
          fallback_temperature_sensor: document.getElementById("safetyFreezeFallbackTempSensor").value,
          max_temperature_age_seconds: Number(document.getElementById("safetyFreezeMaxTempAge").value),
          low_speed_on_below_temp: Number(document.getElementById("safetyFreezeLowOnTemp").value),
          low_speed_off_above_temp: Number(document.getElementById("safetyFreezeLowOffTemp").value),
          high_speed_on_below_temp: Number(document.getElementById("safetyFreezeHighOnTemp").value),
          high_speed_off_above_temp: Number(document.getElementById("safetyFreezeHighOffTemp").value),
          min_run_seconds: Number(document.getElementById("safetyFreezeMinRunSeconds").value),
          threshold_unit: document.getElementById("safetyFreezeUnit").value,
        },
        chlorine_tank: {
          level_sensor: document.getElementById("safetyChlorineTankLevelSensor").value,
          low_warning_gal: Number(document.getElementById("safetyChlorineTankWarningGal").value),
          inhibit_below_gal: Number(document.getElementById("safetyChlorineTankInhibitGal").value),
          reenable_at_gal: Number(document.getElementById("safetyChlorineTankReenableGal").value),
        },
        thresholds: {
          chlorine_min_pump_output_psi: Number(document.getElementById("safetyChlorineMinPump").value),
          chlorine_max_pump_output_psi: Number(document.getElementById("safetyChlorineMaxPump").value),
          pump_prime_min_output_psi: Number(document.getElementById("safetyPrimeMin").value),
          pump_output_overpressure_psi: Number(document.getElementById("safetyOverpressure").value),
        },
        timeouts: {
          pump_output_max_age_seconds: Number(document.getElementById("safetyPumpOutputMaxAge").value),
          pump_prime_timeout_s: Number(document.getElementById("safetyPrimeTimeout").value),
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
  const sensorSelects = [
    "safetySensorPumpOutput",
    "safetyChlorineTankLevelSensor",
  ];
  sensorSelects.forEach((selectId) => {
    const select = document.getElementById(selectId);
    ACQUISITION_SENSOR_ORDER.forEach((sensorId) => {
      const option = document.createElement("option");
      option.value = sensorId;
      option.textContent = sensorId;
      select.appendChild(option);
    });
  });
  ["safetyFreezePrimaryTempSensor", "safetyFreezeFallbackTempSensor"].forEach(
    (selectId) => {
      const select = document.getElementById(selectId);
      ["ph_temp", "orp_temp"].forEach((sensorId) => {
        const option = document.createElement("option");
        option.value = sensorId;
        option.textContent = sensorId;
        select.appendChild(option);
      });
    },
  );

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
    labeledSelect(
      "Filter",
      "acq-filter-type",
      ACQ_FILTER_TYPES.map((item) => ({ value: item, label: item })),
      group.filter?.type || "none",
    ),
    labeledInput(
      "Filter Samples",
      "acq-filter-samples",
      "number",
      group.filter?.window_samples ?? "",
      "1",
      "1",
    ),
    labeledInput(
      "Filter Window (s)",
      "acq-filter-seconds",
      "number",
      group.filter?.window_seconds ?? "",
      "0.1",
    ),
    labeledInput(
      "Filter Min Samples",
      "acq-filter-min-samples",
      "number",
      group.filter?.min_samples ?? 1,
      "1",
      "1",
    ),
  );

  const sensorsBlock = document.createElement("div");
  sensorsBlock.className = "group-sensors";
  const selected = new Set(group.sensor_ids || []);
  ACQUISITION_SENSOR_ORDER.forEach((sensorId) => {
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
      filter: {
        type: stringValue(card, "acq-filter-type") || "none",
        window_samples: optionalIntValue(card, "acq-filter-samples"),
        window_seconds: optionalNumberValue(card, "acq-filter-seconds"),
        min_samples: intValue(card, "acq-filter-min-samples"),
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
    document.getElementById("loggingControlMeasurementInterval").value =
      payload.control_measurement_interval_s ?? 30;
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
        control_measurement_interval_s: Number(
          document.getElementById("loggingControlMeasurementInterval").value,
        ),
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

async function loadNotificationsConfig() {
  if (notificationsConfigLoading) {
    return;
  }
  notificationsConfigLoading = true;
  try {
    const response = await fetch("/api/config/notifications", { cache: "no-store" });
    const payload = await parseApiResponse(response, "notifications config load failed");
    renderNotificationsConfig(payload);
    setNotificationsStatus(
      payload.enabled
        ? payload.pushover && payload.pushover.configured
          ? "Notifications config loaded"
          : "Notifications loaded; Pushover credentials not visible to service"
        : "Notifications config loaded; disabled",
    );
  } catch (error) {
    setNotificationsStatus(error.message);
  } finally {
    notificationsConfigLoading = false;
  }
}

async function saveNotificationsConfig() {
  setNotificationsStatus("Saving notifications config...");
  try {
    const response = await fetch("/api/config/notifications", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectNotificationsConfig()),
    });
    const payload = await parseApiResponse(response, "notifications config save failed");
    renderNotificationsConfig(payload);
    setNotificationsStatus(
      payload.applied_live ? "Notifications config saved and applied live" : "Notifications config saved",
    );
    clearConfigDraftState(true);
  } catch (error) {
    setNotificationsStatus(error.message);
  }
}

async function sendTestNotification() {
  setNotificationsStatus("Sending test notification...");
  try {
    const response = await fetch("/api/notifications/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: document.getElementById("notificationsDefaultTitle").value || "PoolScope",
        message: "PoolScope test notification",
      }),
    });
    const payload = await parseApiResponse(response, "test notification failed");
    if (payload.notification && payload.notification.sent) {
      setNotificationsStatus("Test notification sent");
      return;
    }
    setNotificationsStatus(
      payload.notification && payload.notification.error
        ? payload.notification.error
        : "Test notification was not sent",
    );
  } catch (error) {
    setNotificationsStatus(error.message);
  }
}

function renderNotificationsConfig(payload) {
  const pushover = payload.pushover || {};
  const alerts = payload.alerts || {};
  document.getElementById("notificationsEnabled").checked = payload.enabled === true;
  document.getElementById("notificationsProvider").value = payload.provider || "pushover";
  document.getElementById("notificationsDefaultTitle").value = payload.default_title || "PoolScope";
  document.getElementById("pushoverAppToken").value = pushover.app_token || "";
  document.getElementById("pushoverUserKey").value = pushover.user_key || "";
  document.getElementById("pushoverAppTokenEnv").value = pushover.app_token_env || "PUSHOVER_APP_TOKEN";
  document.getElementById("pushoverUserKeyEnv").value = pushover.user_key_env || "PUSHOVER_USER_KEY";
  document.getElementById("pushoverApiUrl").value = pushover.api_url || "https://api.pushover.net/1/messages.json";
  document.getElementById("pushoverTimeout").value = String(pushover.timeout_s ?? 5.0);
  document.getElementById("pushoverPriority").value = String(pushover.priority ?? 0);
  document.getElementById("pushoverSound").value = pushover.sound || "";
  renderSignalAlertConfig("notifyTank", alerts.chlorine_tank || {});
  renderSignalAlertConfig("notifyPh", alerts.ph || {});
  renderSignalAlertConfig("notifyOrp", alerts.orp || {});
  renderFilterAlertConfig(alerts.filter_flow_loss || {});
  renderFreezeTemperatureAlertConfig(alerts.freeze_temperature_unavailable || {});
}

function collectNotificationsConfig() {
  const appToken = document.getElementById("pushoverAppToken").value.trim();
  const userKey = document.getElementById("pushoverUserKey").value.trim();
  const pushover = {
    app_token: stringOrNull(appToken),
    user_key: stringOrNull(userKey),
    app_token_env: document.getElementById("pushoverAppTokenEnv").value.trim() || "PUSHOVER_APP_TOKEN",
    user_key_env: document.getElementById("pushoverUserKeyEnv").value.trim() || "PUSHOVER_USER_KEY",
    api_url: document.getElementById("pushoverApiUrl").value.trim() || "https://api.pushover.net/1/messages.json",
    timeout_s: Number(document.getElementById("pushoverTimeout").value),
    priority: Number(document.getElementById("pushoverPriority").value),
    sound: stringOrNull(document.getElementById("pushoverSound").value),
  };
  return {
    enabled: document.getElementById("notificationsEnabled").checked,
    provider: document.getElementById("notificationsProvider").value,
    default_title: document.getElementById("notificationsDefaultTitle").value.trim() || "PoolScope",
    pushover,
    alerts: {
      chlorine_tank: collectSignalAlertConfig("notifyTank", { includeAbove: false }),
      ph: collectSignalAlertConfig("notifyPh", { includeAbove: true }),
      orp: collectSignalAlertConfig("notifyOrp", { includeAbove: true }),
      filter_flow_loss: collectFilterAlertConfig(),
      freeze_temperature_unavailable: collectFreezeTemperatureAlertConfig(),
    },
  };
}

function renderFilterAlertConfig(config) {
  const enabled = document.getElementById("notifyFilterAlertEnabled");
  if (!enabled) {
    return;
  }
  enabled.checked = config.enabled === true;
  setOptionalNumberInput("notifyFilterWarningAbove", config.warning_above ?? 15.0);
  setOptionalNumberInput("notifyFilterWarningRepeat", config.warning_repeat_minutes ?? 1440.0);
}

function collectFilterAlertConfig() {
  return {
    enabled: document.getElementById("notifyFilterAlertEnabled").checked,
    warning_above: numberOrNull(document.getElementById("notifyFilterWarningAbove").value),
    warning_repeat_minutes: Number(document.getElementById("notifyFilterWarningRepeat").value),
  };
}

function renderFreezeTemperatureAlertConfig(config) {
  const enabled = document.getElementById("notifyFreezeTempAlertEnabled");
  if (!enabled) {
    return;
  }
  enabled.checked = config.enabled !== false;
  setOptionalNumberInput(
    "notifyFreezeTempWarningRepeat",
    config.warning_repeat_minutes ?? 240.0,
  );
}

function collectFreezeTemperatureAlertConfig() {
  return {
    enabled: document.getElementById("notifyFreezeTempAlertEnabled").checked,
    warning_repeat_minutes: Number(
      document.getElementById("notifyFreezeTempWarningRepeat").value,
    ),
  };
}

function renderSignalAlertConfig(prefix, config) {
  const enabled = document.getElementById(`${prefix}AlertEnabled`);
  if (!enabled) {
    return;
  }
  enabled.checked = config.enabled === true;
  setOptionalNumberInput(`${prefix}CautionBelow`, config.caution_below);
  setOptionalNumberInput(`${prefix}CautionAbove`, config.caution_above);
  setOptionalNumberInput(`${prefix}WarningBelow`, config.warning_below);
  setOptionalNumberInput(`${prefix}WarningAbove`, config.warning_above);
  setOptionalNumberInput(`${prefix}CautionRepeat`, config.caution_repeat_minutes ?? 1440.0);
  setOptionalNumberInput(`${prefix}WarningRepeat`, config.warning_repeat_minutes ?? 240.0);
}

function collectSignalAlertConfig(prefix, options) {
  const includeAbove = options && options.includeAbove === true;
  const payload = {
    enabled: document.getElementById(`${prefix}AlertEnabled`).checked,
    caution_below: numberOrNull(document.getElementById(`${prefix}CautionBelow`).value),
    warning_below: numberOrNull(document.getElementById(`${prefix}WarningBelow`).value),
    caution_repeat_minutes: Number(document.getElementById(`${prefix}CautionRepeat`).value),
    warning_repeat_minutes: Number(document.getElementById(`${prefix}WarningRepeat`).value),
  };
  if (includeAbove) {
    payload.caution_above = numberOrNull(document.getElementById(`${prefix}CautionAbove`).value);
    payload.warning_above = numberOrNull(document.getElementById(`${prefix}WarningAbove`).value);
  }
  return payload;
}

function setOptionalNumberInput(id, value) {
  const input = document.getElementById(id);
  if (!input) {
    return;
  }
  input.value = value === null || value === undefined ? "" : String(value);
}

function setNotificationsStatus(message) {
  const status = document.getElementById("notificationsStatus");
  if (status) {
    status.textContent = message;
  }
}

function initializeNotificationsControls() {
  const reload = document.getElementById("notificationsReload");
  const save = document.getElementById("notificationsSave");
  const test = document.getElementById("notificationsTest");
  if (!reload || !save || !test) {
    return;
  }
  reload.addEventListener("click", loadNotificationsConfig);
  save.addEventListener("click", saveNotificationsConfig);
  test.addEventListener("click", sendTestNotification);
  loadNotificationsConfig();
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
    setChlorinationConfigStatus("Chlorination config loaded");
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
  document.getElementById("chlorinationNoDoseFirstMinutes").value = String(
    payload.no_dose_first_minutes ?? 1.0,
  );
  document.getElementById("chlorinationNoDoseLastMinutes").value = String(
    payload.no_dose_last_minutes ?? 10.0,
  );
  document.getElementById("chlorinationMaxDutyCycle").value = String(payload.max_duty_cycle ?? 0.5);
  document.getElementById("chlorinationCycleOnSeconds").value = String(payload.cycle_on_seconds ?? 60.0);
  document.getElementById("chlorinationMaxCyclePeriodSeconds").value = String(
    payload.max_cycle_period_seconds ?? 1800.0,
  );
  document.getElementById("chlorinationMinCycleOnSeconds").value = String(
    payload.min_cycle_on_seconds ?? 5.0,
  );
}

function collectChlorinationConfig() {
  return {
    enabled: document.getElementById("chlorinationEnabled").checked,
    daily_dose_oz: Number(document.getElementById("chlorinationDailyDoseOz").value),
    pump_output_oz_per_min: Number(document.getElementById("chlorinationPumpOutputOzPerMin").value),
    no_dose_first_minutes: Number(document.getElementById("chlorinationNoDoseFirstMinutes").value),
    no_dose_last_minutes: Number(document.getElementById("chlorinationNoDoseLastMinutes").value),
    max_duty_cycle: Number(document.getElementById("chlorinationMaxDutyCycle").value),
    cycle_on_seconds: Number(document.getElementById("chlorinationCycleOnSeconds").value),
    max_cycle_period_seconds: Number(document.getElementById("chlorinationMaxCyclePeriodSeconds").value),
    min_cycle_on_seconds: Number(document.getElementById("chlorinationMinCycleOnSeconds").value),
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
  const primeButton = document.getElementById("chlorinationPrimeConfigButton");
  if (primeButton) {
    primeButton.addEventListener("click", primeChlorinationPump);
  }
  const calibrationButton = document.getElementById("chlorinationCalibrationConfigButton");
  if (calibrationButton) {
    calibrationButton.addEventListener("click", startChlorinationCalibration);
  }
  const stopButton = document.getElementById("chlorinationDiagnosticStopButton");
  if (stopButton) {
    stopButton.addEventListener("click", stopChlorinationDiagnostic);
  }
  loadChlorinationConfig();
}

async function loadFilterLoadingConfig() {
  if (filterLoadingConfigLoading) {
    return;
  }
  filterLoadingConfigLoading = true;
  try {
    const response = await fetch("/api/config/filter_loading", { cache: "no-store" });
    const payload = await parseApiResponse(response, "filter loading config load failed");
    renderFilterLoadingConfig(payload);
    setFilterLoadingConfigStatus("Filter loading config loaded");
  } catch (error) {
    setFilterLoadingConfigStatus(error.message);
  } finally {
    filterLoadingConfigLoading = false;
  }
}

async function saveFilterLoadingConfig() {
  setFilterLoadingConfigStatus("Saving filter loading config...");
  try {
    const response = await fetch("/api/config/filter_loading", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectFilterLoadingConfig()),
    });
    const payload = await parseApiResponse(response, "filter loading config save failed");
    renderFilterLoadingConfig(payload);
    setFilterLoadingConfigStatus(
      payload.applied_live ? "Filter loading config saved and applied live" : "Filter loading config saved",
    );
    clearConfigDraftState(true);
  } catch (error) {
    setFilterLoadingConfigStatus(error.message);
  }
}

function renderFilterLoadingConfig(payload) {
  document.getElementById("filterLoadingEnabled").checked = payload.enabled !== false;
  setOptionalNumberInput("filterLoadingCleanFlowGpm", payload.clean_flow_gpm);
  document.getElementById("filterLoadingYellowFlowLossPercent").value = String(payload.yellow_flow_loss_percent ?? 10.0);
  document.getElementById("filterLoadingRedFlowLossPercent").value = String(payload.red_flow_loss_percent ?? 15.0);
  document.getElementById("filterLoadingStabilizationSeconds").value = String(payload.stabilization_seconds ?? 60.0);
  document.getElementById("filterLoadingAveragingSeconds").value = String(payload.averaging_seconds ?? 120.0);
  document.getElementById("filterLoadingMaxPressureAgeSeconds").value = String(payload.max_pressure_age_seconds ?? 10.0);
}

function collectFilterLoadingConfig() {
  return {
    enabled: document.getElementById("filterLoadingEnabled").checked,
    clean_flow_gpm: numberOrNull(document.getElementById("filterLoadingCleanFlowGpm").value),
    yellow_flow_loss_percent: Number(document.getElementById("filterLoadingYellowFlowLossPercent").value),
    red_flow_loss_percent: Number(document.getElementById("filterLoadingRedFlowLossPercent").value),
    stabilization_seconds: Number(document.getElementById("filterLoadingStabilizationSeconds").value),
    averaging_seconds: Number(document.getElementById("filterLoadingAveragingSeconds").value),
    max_pressure_age_seconds: Number(document.getElementById("filterLoadingMaxPressureAgeSeconds").value),
  };
}

function setFilterLoadingConfigStatus(message) {
  const status = document.getElementById("filterLoadingConfigStatus");
  if (status) {
    status.textContent = message;
  }
}

function initializeFilterLoadingControls() {
  const reload = document.getElementById("filterLoadingReload");
  const save = document.getElementById("filterLoadingSave");
  if (!reload || !save) {
    return;
  }
  reload.addEventListener("click", loadFilterLoadingConfig);
  save.addEventListener("click", saveFilterLoadingConfig);
  loadFilterLoadingConfig();
}

async function loadFcDemandConfig() {
  if (fcDemandConfigLoading) {
    return;
  }
  fcDemandConfigLoading = true;
  try {
    const response = await fetch("/api/config/fc_demand", { cache: "no-store" });
    const payload = await parseApiResponse(response, "FC demand config load failed");
    renderFcDemandConfig(payload);
    setFcDemandConfigStatus("FC demand config loaded");
  } catch (error) {
    setFcDemandConfigStatus(error.message);
  } finally {
    fcDemandConfigLoading = false;
  }
}

async function saveFcDemandConfig() {
  setFcDemandConfigStatus("Saving FC demand config...");
  try {
    const response = await fetch("/api/config/fc_demand", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectFcDemandConfig()),
    });
    const payload = await parseApiResponse(response, "FC demand config save failed");
    renderFcDemandConfig(payload);
    setFcDemandConfigStatus(
      payload.applied_live ? "FC demand config saved and applied live" : "FC demand config saved",
    );
    clearConfigDraftState(true);
  } catch (error) {
    setFcDemandConfigStatus(error.message);
  }
}

function renderFcDemandConfig(payload) {
  const enabled = document.getElementById("fcDemandEnabled");
  const mode = document.getElementById("fcDemandMode");
  const poolVolume = document.getElementById("fcDemandPoolVolumeGal");
  const target = document.getElementById("fcDemandTargetFcPpm");
  const strength = document.getElementById("fcDemandChlorineStrengthPercent");
  const minInterval = document.getElementById("fcDemandMinimumTestIntervalHours");
  const maxObservationInterval = document.getElementById("fcDemandMaxObservationIntervalDays");
  const preferredStart = document.getElementById("fcDemandPreferredTestStartHour");
  const preferredEnd = document.getElementById("fcDemandPreferredTestEndHour");
  const negativeDemandNoise = document.getElementById("fcDemandNegativeDemandNoiseTolerance");
  const recentCount = document.getElementById("fcDemandRecentObservationCount");
  const weights = document.getElementById("fcDemandObservationWeights");
  const feedbackGain = document.getElementById("fcDemandFeedbackGain");
  const maxMaintenanceChange = document.getElementById("fcDemandMaxMaintenanceChangePercent");
  const maxDose = document.getElementById("fcDemandMaxDailyDoseOz");
  if (
    !enabled ||
    !mode ||
    !poolVolume ||
    !target ||
    !strength ||
    !minInterval ||
    !maxObservationInterval ||
    !preferredStart ||
    !preferredEnd ||
    !negativeDemandNoise ||
    !recentCount ||
    !weights ||
    !feedbackGain ||
    !maxMaintenanceChange ||
    !maxDose
  ) {
    return;
  }
  enabled.checked = payload.enabled === true;
  mode.value = payload.mode || "observe_only";
  poolVolume.value = String(payload.pool_volume_gal ?? 10000.0);
  target.value = String(payload.target_fc_ppm ?? 4.0);
  strength.value = String(payload.chlorine_strength_percent ?? 12.0);
  minInterval.value = String(payload.minimum_test_interval_hours ?? 12.0);
  maxObservationInterval.value = String(payload.max_observation_interval_days ?? 7.0);
  preferredStart.value = String(payload.preferred_test_start_hour ?? 18);
  preferredEnd.value = String(payload.preferred_test_end_hour ?? 24);
  negativeDemandNoise.value = String(
    payload.negative_demand_noise_tolerance_ppm_per_day ?? 0.05
  );
  recentCount.value = String(payload.recent_observation_count ?? 5);
  weights.value = Array.isArray(payload.observation_weights)
    ? payload.observation_weights.join(", ")
    : "0.35, 0.25, 0.18, 0.13, 0.09";
  feedbackGain.value = String(payload.fc_feedback_gain ?? 0.6);
  maxMaintenanceChange.value = String(payload.max_maintenance_change_percent ?? 15.0);
  maxDose.value = String(payload.max_daily_dose_oz ?? 256.0);
}

function collectFcDemandConfig() {
  const weights = String(document.getElementById("fcDemandObservationWeights").value)
    .split(",")
    .map((value) => Number(value.trim()))
    .filter((value) => Number.isFinite(value));
  return {
    enabled: document.getElementById("fcDemandEnabled").checked,
    mode: document.getElementById("fcDemandMode").value,
    pool_volume_gal: Number(document.getElementById("fcDemandPoolVolumeGal").value),
    target_fc_ppm: Number(document.getElementById("fcDemandTargetFcPpm").value),
    chlorine_strength_percent: Number(document.getElementById("fcDemandChlorineStrengthPercent").value),
    minimum_test_interval_hours: Number(document.getElementById("fcDemandMinimumTestIntervalHours").value),
    max_observation_interval_days: Number(document.getElementById("fcDemandMaxObservationIntervalDays").value),
    preferred_test_start_hour: Number(document.getElementById("fcDemandPreferredTestStartHour").value),
    preferred_test_end_hour: Number(document.getElementById("fcDemandPreferredTestEndHour").value),
    negative_demand_noise_tolerance_ppm_per_day: Number(
      document.getElementById("fcDemandNegativeDemandNoiseTolerance").value
    ),
    recent_observation_count: Number(document.getElementById("fcDemandRecentObservationCount").value),
    observation_weights: weights,
    fc_feedback_gain: Number(document.getElementById("fcDemandFeedbackGain").value),
    max_maintenance_change_percent: Number(document.getElementById("fcDemandMaxMaintenanceChangePercent").value),
    max_daily_dose_oz: Number(document.getElementById("fcDemandMaxDailyDoseOz").value),
  };
}

function setFcDemandConfigStatus(message) {
  const status = document.getElementById("fcDemandConfigStatus");
  if (status) {
    status.textContent = message;
  }
}

function initializeFcDemandControls() {
  const reload = document.getElementById("fcDemandReload");
  const save = document.getElementById("fcDemandSave");
  if (!reload || !save) {
    return;
  }
  reload.addEventListener("click", loadFcDemandConfig);
  save.addEventListener("click", saveFcDemandConfig);
  loadFcDemandConfig();
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

async function loadPhSensorConfig() {
  if (phSensorConfigLoading) {
    return;
  }
  phSensorConfigLoading = true;
  try {
    const response = await fetch("/api/config/ph_sensor", { cache: "no-store" });
    const payload = await parseApiResponse(response, "pH sensor config load failed");
    renderPhSensorConfig(payload);
    setPhSensorStatus(
      payload.enabled ? "pH sensor config loaded" : "pH sensor config loaded; disabled",
    );
  } catch (error) {
    setPhSensorStatus(error.message);
  } finally {
    phSensorConfigLoading = false;
  }
}

async function savePhSensorConfig() {
  setPhSensorStatus("Saving pH sensor config...");
  try {
    const response = await fetch("/api/config/ph_sensor", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectPhSensorConfig()),
    });
    const payload = await parseApiResponse(response, "pH sensor config save failed");
    renderPhSensorConfig(payload);
    setPhSensorStatus(payload.message || "pH sensor config saved");
    clearConfigDraftState(true);
  } catch (error) {
    setPhSensorStatus(error.message);
  }
}

function renderPhSensorConfig(payload) {
  const config = payload.modbus_ph_sensor || {};
  const breaker = config.circuit_breaker || {};
  document.getElementById("phSensorEnabled").checked = payload.enabled === true;
  document.getElementById("phSensorPort").value = config.port || "/dev/ttyUSB0";
  document.getElementById("phSensorSlaveId").value = String(config.slave_id ?? 4);
  document.getElementById("phSensorBaudrate").value = String(config.baudrate ?? 4800);
  document.getElementById("phSensorTimeout").value = String(config.timeout_s ?? 1.0);
  document.getElementById("phBreakerEnabled").checked = breaker.enabled !== false;
  document.getElementById("phBreakerFailures").value = String(breaker.failure_threshold ?? 2);
  document.getElementById("phBreakerCooldown").value = String(breaker.cooldown_s ?? 60);
  document.getElementById("phCalLowValue").value = String(payload.calibration?.low_default_ph ?? 4.01);
  document.getElementById("phCalHighValue").value = String(payload.calibration?.high_default_ph ?? 9.18);
}

function collectPhSensorConfig() {
  return {
    enabled: document.getElementById("phSensorEnabled").checked,
    modbus_ph_sensor: {
      port: document.getElementById("phSensorPort").value.trim() || "/dev/ttyUSB0",
      slave_id: Number(document.getElementById("phSensorSlaveId").value),
      baudrate: Number(document.getElementById("phSensorBaudrate").value),
      timeout_s: Number(document.getElementById("phSensorTimeout").value),
      circuit_breaker: {
        enabled: document.getElementById("phBreakerEnabled").checked,
        failure_threshold: Number(document.getElementById("phBreakerFailures").value),
        cooldown_s: Number(document.getElementById("phBreakerCooldown").value),
      },
    },
  };
}

async function calibratePhSensor(point) {
  const inputId = point === "low" ? "phCalLowValue" : "phCalHighValue";
  const phValue = Number(document.getElementById(inputId).value);
  setPhSensorStatus(`Writing ${point} pH calibration...`);
  try {
    const response = await fetch("/api/ph/calibrate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        point,
        ph_value: phValue,
      }),
    });
    const payload = await parseApiResponse(response, "pH calibration failed");
    setPhSensorStatus(payload.message || "pH calibration written");
  } catch (error) {
    setPhSensorStatus(error.message);
  }
}

function setPhSensorStatus(message) {
  const status = document.getElementById("phSensorStatus");
  if (status) {
    status.textContent = message;
  }
}

function initializePhSensorControls() {
  const reload = document.getElementById("phSensorReload");
  const save = document.getElementById("phSensorSave");
  const low = document.getElementById("phCalLowButton");
  const high = document.getElementById("phCalHighButton");
  if (!reload || !save || !low || !high) {
    return;
  }
  reload.addEventListener("click", loadPhSensorConfig);
  save.addEventListener("click", savePhSensorConfig);
  low.addEventListener("click", () => calibratePhSensor("low"));
  high.addEventListener("click", () => calibratePhSensor("high"));
  loadPhSensorConfig();
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
    const payload = await parseApiResponse(response, "lab test save failed");
    setLabTestStatus("Lab test saved");
    renderLabTestFcDemandFeedback(payload.fc_demand);
    renderLabTestTankFeedback(payload.chlorine_tank);
    if (document.getElementById("labTestList")) {
      await loadLabTests();
    }
    if (
      payload.lab_test &&
      payload.lab_test.chlorine_tank_level_gal !== null &&
      payload.lab_test.chlorine_tank_level_gal !== undefined
    ) {
      await loadChlorineTankRefills();
      if (PAGE_MODE === "history") {
        await refreshHistory(true);
      }
    }
    if (PAGE_MODE === "live") {
      await loadLive();
      await refreshLiveTrends(true);
    }
  } catch (error) {
    setLabTestStatus(error.message);
  }
}

function collectLabTestPayload() {
  const payload = {
    sampled_at: datetimeLocalIsoString("labSampledAt", "Sampled at"),
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
    chlorine_tank_level_gal: numberOrNull(document.getElementById("labChlorineTankLevelGal").value),
    notes: stringOrNull(document.getElementById("labNotes").value),
  };
  if (!payload.sampled_at) {
    delete payload.sampled_at;
  }
  return payload;
}

function renderLabTests(tests) {
  const list = document.getElementById("labTestList");
  if (!list) {
    return;
  }
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
      if (test.chlorine_tank_level_gal !== null && test.chlorine_tank_level_gal !== undefined) {
        parts.push(`Tank ${Number(test.chlorine_tank_level_gal).toFixed(2)} gal`);
      }
      const notes = test.notes ? ` | ${test.notes}` : "";
      return `[${new Date(test.sampled_at).toLocaleString()}] ${parts.join(" | ")}${notes}`;
    });
  list.textContent = lines.join("\n");
}

function setLabTestStatus(message) {
  const node = document.getElementById("labTestStatus");
  if (node) {
    node.textContent = message;
  }
}

function setLabTestTankStatus(message) {
  const node = document.getElementById("labTestTankStatus");
  if (node) {
    node.textContent = message;
  }
}

function renderLabTestFcDemandFeedback(fcDemand) {
  const node = document.getElementById("labTestFcDemandStatus");
  if (!node) {
    return;
  }
  if (!fcDemand) {
    node.textContent = "FC demand: unavailable";
    return;
  }
  if (!fcDemand.enabled) {
    node.textContent = "FC demand: disabled";
    return;
  }
  if (!fcDemand.ready) {
    node.textContent = `FC demand: ${fcDemand.reason || "waiting for more FC tests"}`;
    return;
  }

  const mode = String(fcDemand.mode || "observe_only");
  const demand = Number(fcDemand.latest_observed_demand_ppm_per_day);
  const baseline = Number(fcDemand.baseline_demand_ppm_per_day ?? fcDemand.weighted_maintenance_demand_ppm_per_day);
  const weather = Number(fcDemand.weather_adjustment_ppm_per_day);
  const predicted = Number(fcDemand.predicted_demand_ppm_per_day);
  const recommended = Number(fcDemand.recommended_daily_dose_oz);
  const effective = Number(fcDemand.effective_daily_dose_oz);
  const elapsed = Number(fcDemand.elapsed_days);
  const maintenance = Number(fcDemand.maintenance_dose_oz_per_day);
  const feedback = Number(fcDemand.feedback_dose_oz);
  const feedbackDate = fcDemand.feedback_control_date || "next control day";
  const pieces = [
    `FC demand ${Number.isFinite(demand) ? demand.toFixed(2) : "--"} ppm/day latest`,
    `baseline ${Number.isFinite(baseline) ? baseline.toFixed(2) : "--"} ppm/day`,
    `weather ${Number.isFinite(weather) ? weather.toFixed(2) : "0.00"} ppm/day`,
    `predicted ${Number.isFinite(predicted) ? predicted.toFixed(2) : "--"} ppm/day`,
    `maintenance ${Number.isFinite(maintenance) ? maintenance.toFixed(1) : "--"} oz/day`,
    `recommended ${Number.isFinite(recommended) ? recommended.toFixed(1) : "--"} oz/day`,
  ];
  if (Number.isFinite(elapsed) && elapsed > 0) {
    pieces.push(`window ${elapsed.toFixed(1)} days`);
  }

  if (Number.isFinite(feedback) && feedback !== 0) {
    const sign = feedback > 0 ? "+" : "";
    pieces.push(`feedback ${sign}${feedback.toFixed(1)} oz on ${feedbackDate}`);
  }
  if (!fcDemand.feedback_active_today) {
    pieces.push("feedback not active today");
  }
  if (mode === "automatic") {
    pieces.push(`automatic effective dose ${Number.isFinite(effective) ? effective.toFixed(1) : "--"} oz/day`);
  } else {
    pieces.push(`${mode.replaceAll("_", " ")} only`);
  }
  node.textContent = pieces.join(" | ");
}

function renderLabTestTankFeedback(chlorineTank) {
  const node = document.getElementById("labTestTankStatus");
  if (!node) {
    return;
  }
  if (!chlorineTank) {
    node.textContent = "Chlorine tank: --";
    return;
  }

  const estimate = chlorineTank.estimate || null;
  const audit = chlorineTank.audit || null;
  const pieces = [];
  if (estimate) {
    pieces.push(`level ${Number(estimate.level_gal).toFixed(2)} gal`);
  }
  if (audit && audit.ready) {
    const error = Number(audit.injection_error_gal);
    const percent = Number(audit.injection_error_percent);
    const sign = Number.isFinite(error) && error > 0 ? "+" : "";
    const percentText = Number.isFinite(percent) ? `, ${percent.toFixed(1)}%` : "";
    pieces.push(`injection error ${sign}${Number.isFinite(error) ? error.toFixed(3) : "--"} gal${percentText}`);
  } else if (audit && audit.reason) {
    pieces.push(audit.reason);
  }
  node.textContent = pieces.length ? `Chlorine tank: ${pieces.join(" | ")}` : "Chlorine tank: --";
}

function initializeLabTestControls() {
  const save = document.getElementById("labTestSave");
  const reload = document.getElementById("labTestReload");
  if (!save) {
    return;
  }
  save.addEventListener("click", saveLabTest);
  if (reload) {
    reload.addEventListener("click", loadLabTests);
  }
  if (document.getElementById("labTestList")) {
    loadLabTests();
  }
}

async function loadChlorineTankRefills() {
  if (chlorineTankRefillLoading) {
    return;
  }
  const list = document.getElementById("chlorineTankRefillList");
  if (!list) {
    return;
  }
  chlorineTankRefillLoading = true;
  try {
    const response = await fetch("/api/chlorine_tank_refills?hours=720&limit=100", { cache: "no-store" });
    const payload = await parseApiResponse(response, "chlorine tank refills load failed");
    renderChlorineTankRefills(payload.chlorine_tank_refills || []);
    renderChlorineTankEstimate(payload.chlorine_tank && payload.chlorine_tank.estimate);
    setChlorineTankRefillStatus("Chlorine tank refills loaded");
  } catch (error) {
    setChlorineTankRefillStatus(error.message);
  } finally {
    chlorineTankRefillLoading = false;
  }
}

async function saveChlorineTankRefill() {
  setChlorineTankRefillStatus("Saving chlorine tank refill...");
  try {
    const response = await fetch("/api/chlorine_tank_refills", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectChlorineTankRefillPayload()),
    });
    const payload = await parseApiResponse(response, "chlorine tank refill save failed");
    setChlorineTankRefillStatus("Chlorine tank refill saved");
    renderChlorineTankEstimate(payload.chlorine_tank && payload.chlorine_tank.estimate);
    clearChlorineTankRefillInputs();
    await loadChlorineTankRefills();
    await refreshHistory(true);
  } catch (error) {
    setChlorineTankRefillStatus(error.message);
  }
}

function collectChlorineTankRefillPayload() {
  const payload = {
    added_at: datetimeLocalIsoString("chlorineTankRefillAddedAt", "Tank refill added at"),
    amount_gal: numberOrNull(document.getElementById("chlorineTankRefillAmountGal").value),
    notes: stringOrNull(document.getElementById("chlorineTankRefillNotes").value),
  };
  if (!payload.added_at) {
    delete payload.added_at;
  }
  return payload;
}

function renderChlorineTankRefills(refills) {
  const list = document.getElementById("chlorineTankRefillList");
  if (!list) {
    return;
  }
  if (!refills.length) {
    list.textContent = "No chlorine tank refills recorded";
    return;
  }
  const lines = refills
    .slice()
    .reverse()
    .map((refill) => {
      const amount = Number(refill.amount_gal);
      const amountText = Number.isFinite(amount) ? `${amount.toFixed(2)} gal` : "-- gal";
      const notes = refill.notes ? ` | ${refill.notes}` : "";
      return `[${new Date(refill.added_at).toLocaleString()}] ${amountText}${notes}`;
    });
  list.textContent = lines.join("\n");
}

function renderChlorineTankEstimate(estimate) {
  const node = document.getElementById("chlorineTankEstimateStatus");
  if (!node) {
    return;
  }
  if (!estimate) {
    node.textContent = "Estimated tank level: enter a tank level test to start";
    return;
  }
  const level = Number(estimate.level_gal);
  const delivered = Number(estimate.delivered_gal_since_baseline);
  const refilled = Number(estimate.refilled_gal_since_baseline);
  node.textContent =
    `Estimated tank level: ${Number.isFinite(level) ? level.toFixed(2) : "--"} gal` +
    ` | delivered ${Number.isFinite(delivered) ? delivered.toFixed(3) : "--"} gal` +
    ` | refilled ${Number.isFinite(refilled) ? refilled.toFixed(2) : "--"} gal`;
}

function clearChlorineTankRefillInputs() {
  document.getElementById("chlorineTankRefillAddedAt").value = "";
  document.getElementById("chlorineTankRefillAmountGal").value = "";
  document.getElementById("chlorineTankRefillNotes").value = "";
}

function setChlorineTankRefillStatus(message) {
  const node = document.getElementById("chlorineTankRefillStatus");
  if (node) {
    node.textContent = message;
  }
}

function initializeChlorineTankRefillControls() {
  const save = document.getElementById("chlorineTankRefillSave");
  const reload = document.getElementById("chlorineTankRefillReload");
  if (!save || !reload) {
    return;
  }
  reload.addEventListener("click", loadChlorineTankRefills);
  save.addEventListener("click", saveChlorineTankRefill);
  loadChlorineTankRefills();
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
    if (document.getElementById("chemicalAdditionList")) {
      await loadChemicalAdditions();
    }
    if (PAGE_MODE === "history") {
      await refreshHistory(true);
    } else if (PAGE_MODE === "live") {
      await refreshLiveTrends(true);
    }
  } catch (error) {
    setChemicalAdditionStatus(error.message);
  }
}

function collectChemicalAdditionPayload() {
  const payload = {
    added_at: datetimeLocalIsoString("chemicalAddedAt", "Added at"),
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
  if (!list) {
    return;
  }
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
  const node = document.getElementById("chemicalAdditionStatus");
  if (node) {
    node.textContent = message;
  }
}

function updateChemicalStrengthDefault() {
  const chemical = document.getElementById("chemicalType");
  const strength = document.getElementById("chemicalStrength");
  if (!chemical || !strength) {
    return;
  }
  strength.value = String(chemicalDefaultStrengthPercent(chemical.value));
}

function initializeChemicalAdditionControls() {
  const chemicalType = document.getElementById("chemicalType");
  if (!chemicalType) {
    return;
  }
  chemicalType.addEventListener("change", updateChemicalStrengthDefault);
  const reload = document.getElementById("chemicalAdditionReload");
  const save = document.getElementById("chemicalAdditionSave");
  if (reload) {
    reload.addEventListener("click", loadChemicalAdditions);
  }
  if (save) {
    save.addEventListener("click", saveChemicalAddition);
  }
  updateChemicalStrengthDefault();
  if (document.getElementById("chemicalAdditionList")) {
    loadChemicalAdditions();
  }
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
    "liveOverridePumpOffManual",
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
    "liveOverrideResumeSchedule",
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

function initializeScheduleProfileControls() {
  const select = document.getElementById("liveScheduleProfile");
  const button = document.getElementById("liveScheduleProfileActivate");
  if (!select || !button) {
    return;
  }
  select.addEventListener("change", () => {
    scheduleProfileSelectionDirty = select.value !== activeScheduleProfile;
    updateScheduleProfileControlState();
  });
  button.addEventListener("click", activateScheduleProfile);
  void loadScheduleProfiles();
}

function initializeChlorinationQuickControls() {
  [
    ["liveChlorinationDoseSave", "liveChlorinationDoseInput"],
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

  [
    ["liveSupplementalChlorineDoseStart", "liveSupplementalChlorineDoseInput"],
  ].forEach(([buttonId, inputId]) => {
    const button = document.getElementById(buttonId);
    const input = document.getElementById(inputId);
    if (!button || !input) {
      return;
    }
    button.addEventListener("click", () => openSupplementalChlorineConfirmation(inputId));
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        openSupplementalChlorineConfirmation(inputId);
      }
    });
  });

  const confirmButton = document.getElementById("liveSupplementalConfirmStart");
  const dialog = document.getElementById("liveSupplementalConfirm");
  if (confirmButton && dialog) {
    confirmButton.addEventListener("click", () => {
      const inputId = dialog.dataset.doseInputId || "liveSupplementalChlorineDoseInput";
      void startSupplementalChlorineDose(inputId);
    });
  }

  [
    "liveSupplementalChlorineDoseStop",
  ].forEach((buttonId) => {
    const button = document.getElementById(buttonId);
    if (!button) {
      return;
    }
    button.addEventListener("click", stopSupplementalChlorineDose);
  });
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
      await refreshHealth(false);
    } else if (PAGE_MODE === "config") {
      await refreshTopStatus(false);
      if (!configAutoRefreshPaused) {
        await loadAllConfigSections();
      }
      await refreshHealth(false);
    }
  } catch (error) {
    if (PAGE_MODE === "live") {
      setControllerConnectionState(false);
    }
    const badge = document.getElementById("safetyBadge");
    if (badge) {
      badge.classList.remove("ok");
      badge.classList.add("fault");
      badge.textContent = "Dashboard error";
    }
    const status = document.getElementById("liveCommandStatus");
    if (status) {
      status.textContent = error.message;
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
    initializeLiveTrendResizeHandling();
    initializeTimerOverrideControls();
    initializeScheduleProfileControls();
    initializeChlorinationQuickControls();
    initializeChemicalAdditionControls();
    initializeLabTestControls();
    return;
  }
  if (PAGE_MODE === "history") {
    initializeHistoryControls();
    initializeFaultTimelineControls();
    initializeLabTestControls();
    initializeChlorineTankRefillControls();
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
    initializeNotificationsControls();
    initializeAnalogControls();
    initializePhSensorControls();
    initializeChlorinationControls();
    initializeFilterLoadingControls();
    initializeFcDemandControls();
    return;
  }
}
