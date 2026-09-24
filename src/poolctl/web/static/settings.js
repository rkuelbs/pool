const SETTINGS_PRIMARY_LIMITS = [
  ["raw_ph", "pH"],
  ["raw_orp", "ORP"],
  ["calcium_saturation_index", "CSI"],
  ["filter_flow_loss_percent", "Filter flow loss"],
  ["chlorine_tank_days_remaining", "Chlorine remaining"],
  ["cpu_temp", "CPU temperature"],
];

const SETTINGS_NOTIFICATION_RULES = [
  ["chlorine_tank_days_remaining", "Chlorine remaining"],
  ["raw_ph", "pH"],
  ["raw_orp", "ORP"],
  ["filter_flow_loss_percent", "Filter flow loss"],
  ["freeze_temperature_unavailable", "Freeze temperature unavailable"],
];

const SETTINGS_LIMIT_KEYS = [
  "alarm_below",
  "caution_below",
  "caution_above",
  "alarm_above",
];

let settingsDirty = false;
let settingsLoading = false;
let settingsLastMetaLoad = 0;
let settingsLimits = {};
let settingsNotifications = null;
let settingsPool = null;
let settingsSite = null;
let settingsRuntime = null;

function settingsElement(id) {
  return document.getElementById(id);
}

function settingsSetStatus(id, message) {
  const node = settingsElement(id);
  if (node) {
    node.textContent = message;
  }
}

function settingsSetValue(id, value) {
  const node = settingsElement(id);
  if (node) {
    node.value = value === null || value === undefined ? "" : String(value);
  }
}

function settingsNumber(id, { optional = false } = {}) {
  const node = settingsElement(id);
  const raw = node ? node.value.trim() : "";
  if (!raw && optional) {
    return null;
  }
  const value = Number(raw);
  if (!Number.isFinite(value)) {
    throw new Error(`${id} must be a number`);
  }
  return value;
}

async function settingsRequest(path, options = {}) {
  const response = await fetch(path, {
    cache: "no-store",
    ...options,
    headers: options.body
      ? { "Content-Type": "application/json", ...(options.headers || {}) }
      : options.headers,
  });
  const text = await response.text();
  let payload = {};
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch (_error) {
      payload = { error: text };
    }
  }
  if (!response.ok) {
    throw new Error(payload.error || payload.message || `Request failed (${response.status})`);
  }
  return payload;
}

function settingsPost(path, payload) {
  return settingsRequest(path, { method: "POST", body: JSON.stringify(payload) });
}

function settingsSaved({ restartRequired = false } = {}) {
  settingsDirty = false;
  settingsSetStatus(
    "configSyncStatus",
    restartRequired ? "Changes saved — controller restart required" : "Changes saved and applied",
  );
  void refreshSettingsMeta(true);
}

function settingsSetBadge(id, text, enabled = true) {
  const node = settingsElement(id);
  if (!node) {
    return;
  }
  node.textContent = text;
  node.classList.toggle("is-disabled", !enabled);
}

function settingsLinkToCard(cardId) {
  const card = settingsElement(cardId);
  if (!card) {
    return;
  }
  card.open = true;
  card.scrollIntoView({ behavior: "smooth", block: "start" });
  const firstControl = card.querySelector("input, select, button");
  if (firstControl) {
    window.setTimeout(() => firstControl.focus({ preventScroll: true }), 250);
  }
}

function initializeSettingsLinks() {
  document.querySelectorAll("[data-settings-link]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      settingsLinkToCard(link.dataset.settingsLink);
    });
  });
}

function updatePoolSiteSummary() {
  if (!settingsPool || !settingsSite) {
    return;
  }
  const gallons = Number(settingsPool.volume_gal).toLocaleString();
  settingsElement("poolSiteSummary").textContent =
    `${settingsPool.name} • ${gallons} gal • ${settingsSite.timezone}`;
}

function renderPoolConfig(payload) {
  settingsPool = payload;
  settingsSetValue("poolName", payload.name);
  settingsSetValue("poolVolumeGal", payload.volume_gal);
  updatePoolSiteSummary();
}

async function loadPoolConfig() {
  try {
    const payload = await settingsRequest("/api/config/pool");
    renderPoolConfig(payload);
    settingsSetStatus("poolStatus", "Saved pool settings loaded");
  } catch (error) {
    settingsSetStatus("poolStatus", error.message);
  }
}

async function savePoolConfig() {
  settingsSetStatus("poolStatus", "Saving…");
  try {
    const payload = await settingsPost("/api/config/pool", {
      name: settingsElement("poolName").value.trim(),
      volume_gal: settingsNumber("poolVolumeGal"),
    });
    renderPoolConfig(payload);
    settingsSetStatus("poolStatus", "Pool settings saved and applied");
    settingsSaved();
  } catch (error) {
    settingsSetStatus("poolStatus", error.message);
  }
}

function renderSettingsSite(payload) {
  settingsSite = payload;
  settingsSetValue("siteTimezone", payload.timezone || "UTC");
  settingsSetValue("siteLatitude", payload.latitude);
  settingsSetValue("siteLongitude", payload.longitude);
  updatePoolSiteSummary();
}

async function loadSettingsSite() {
  try {
    const payload = await settingsRequest("/api/config/site");
    renderSettingsSite(payload);
    settingsSetStatus("siteStatus", "Saved location loaded");
  } catch (error) {
    settingsSetStatus("siteStatus", error.message);
  }
}

async function saveSettingsSite() {
  settingsSetStatus("siteStatus", "Saving…");
  try {
    const payload = await settingsPost("/api/config/site", {
      timezone: settingsElement("siteTimezone").value.trim() || "UTC",
      latitude: settingsNumber("siteLatitude", { optional: true }),
      longitude: settingsNumber("siteLongitude", { optional: true }),
    });
    renderSettingsSite(payload);
    settingsSetStatus("siteStatus", "Location saved and applied");
    settingsSaved();
  } catch (error) {
    settingsSetStatus("siteStatus", error.message);
  }
}

function monitoringLabel(sensorId) {
  const primary = SETTINGS_PRIMARY_LIMITS.find(([id]) => id === sensorId);
  if (primary) {
    return primary[1];
  }
  if (typeof SENSOR_LABELS !== "undefined" && SENSOR_LABELS[sensorId]) {
    return SENSOR_LABELS[sensorId];
  }
  return sensorId.replaceAll("_", " ");
}

function createMonitoringRow(sensorId, limits) {
  const row = document.createElement("tr");
  row.dataset.sensorId = sensorId;
  const label = document.createElement("td");
  label.textContent = monitoringLabel(sensorId);
  row.appendChild(label);
  SETTINGS_LIMIT_KEYS.forEach((key) => {
    const cell = document.createElement("td");
    const input = document.createElement("input");
    input.type = "number";
    input.step = "any";
    input.dataset.limitKey = key;
    input.setAttribute("aria-label", `${monitoringLabel(sensorId)} ${key.replaceAll("_", " ")}`);
    const value = limits ? limits[key] : null;
    input.value = value === null || value === undefined ? "" : String(value);
    cell.appendChild(input);
    row.appendChild(cell);
  });
  return row;
}

function renderMonitoringConfig(payload) {
  settingsLimits = payload.limits || {};
  const primaryBody = settingsElement("monitoringPrimaryRows");
  const advancedBody = settingsElement("monitoringAdvancedRows");
  primaryBody.replaceChildren();
  advancedBody.replaceChildren();
  const primaryIds = new Set(SETTINGS_PRIMARY_LIMITS.map(([id]) => id));
  SETTINGS_PRIMARY_LIMITS.forEach(([sensorId]) => {
    primaryBody.appendChild(createMonitoringRow(sensorId, settingsLimits[sensorId] || {}));
  });
  Object.keys(settingsLimits)
    .filter((sensorId) => !primaryIds.has(sensorId))
    .sort((left, right) => monitoringLabel(left).localeCompare(monitoringLabel(right)))
    .forEach((sensorId) => {
      advancedBody.appendChild(createMonitoringRow(sensorId, settingsLimits[sensorId]));
    });
  settingsElement("monitoringSummary").textContent =
    `${Object.keys(settingsLimits).length} monitored conditions • shared by dashboard and alerts`;
  updateCanonicalThresholdContext();
  renderNotificationRules();
}

function collectMonitoringConfig() {
  const limits = {};
  document.querySelectorAll(".monitoring-table tbody tr[data-sensor-id]").forEach((row) => {
    const values = {};
    row.querySelectorAll("input[data-limit-key]").forEach((input) => {
      values[input.dataset.limitKey] = input.value.trim() ? Number(input.value) : null;
    });
    limits[row.dataset.sensorId] = values;
  });
  return { limits };
}

async function loadMonitoringConfig() {
  try {
    const payload = await settingsRequest("/api/config/monitoring");
    renderMonitoringConfig(payload);
    settingsSetStatus("monitoringStatus", "Saved status ranges loaded");
  } catch (error) {
    settingsSetStatus("monitoringStatus", error.message);
  }
}

async function saveMonitoringConfig() {
  settingsSetStatus("monitoringStatus", "Saving…");
  try {
    const payload = await settingsPost("/api/config/monitoring", collectMonitoringConfig());
    renderMonitoringConfig(payload);
    settingsSetStatus("monitoringStatus", "Status ranges saved and applied everywhere");
    if (typeof liveTrendBandsLoaded !== "undefined") {
      liveTrendBandsLoaded = false;
    }
    settingsSaved();
  } catch (error) {
    settingsSetStatus("monitoringStatus", error.message);
  }
}

function formatThresholdValue(value, sensorId) {
  if (value === null || value === undefined) {
    return null;
  }
  const suffix = sensorId === "filter_flow_loss_percent" ? "%" :
    sensorId === "chlorine_tank_days_remaining" ? " d" : "";
  return `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}${suffix}`;
}

function thresholdDescription(sensorId) {
  if (sensorId === "freeze_temperature_unavailable") {
    return "Triggers when neither configured freeze temperature source has a usable reading.";
  }
  const limits = settingsLimits[sensorId];
  if (!limits) {
    return "No status range is configured.";
  }
  const parts = [];
  if (limits.caution_below !== null && limits.caution_below !== undefined) {
    parts.push(`caution at or below ${formatThresholdValue(limits.caution_below, sensorId)}`);
  }
  if (limits.caution_above !== null && limits.caution_above !== undefined) {
    parts.push(`caution at or above ${formatThresholdValue(limits.caution_above, sensorId)}`);
  }
  if (limits.alarm_below !== null && limits.alarm_below !== undefined) {
    parts.push(`alarm at or below ${formatThresholdValue(limits.alarm_below, sensorId)}`);
  }
  if (limits.alarm_above !== null && limits.alarm_above !== undefined) {
    parts.push(`alarm at or above ${formatThresholdValue(limits.alarm_above, sensorId)}`);
  }
  return parts.length ? parts.join(" • ") : "No caution or alarm boundary is configured.";
}

function updateCanonicalThresholdContext() {
  const node = settingsElement("filterStatusThresholds");
  if (node) {
    node.textContent = `Status thresholds: ${thresholdDescription("filter_flow_loss_percent")}`;
  }
}

function renderChlorinationSettings(payload) {
  settingsElement("chlorinationEnabled").checked = payload.enabled !== false;
  settingsSetValue("chlorinationDailyDoseOz", payload.daily_dose_oz);
  settingsSetValue("chlorinationPumpOutputOzPerMin", payload.pump_output_oz_per_min);
  settingsSetValue("chlorinationStrengthPercent", payload.chlorine_strength_percent);
  settingsSetValue("chlorinationNoDoseFirstMinutes", payload.no_dose_first_minutes);
  settingsSetValue("chlorinationNoDoseLastMinutes", payload.no_dose_last_minutes);
  settingsSetValue("chlorinationMaxDutyCycle", payload.max_duty_cycle);
  settingsSetValue("chlorinationCycleOnSeconds", payload.cycle_on_seconds);
  settingsSetValue("chlorinationMinCycleOnSeconds", payload.min_cycle_on_seconds);
  settingsSetValue("chlorinationMaxCyclePeriodSeconds", payload.max_cycle_period_seconds);
  canonicalChlorineStrengthPercent = Number(payload.chlorine_strength_percent);
  settingsElement("chlorinationSummary").textContent =
    `${payload.enabled ? "Enabled" : "Disabled"} • ${Number(payload.pump_output_oz_per_min).toFixed(2)} oz/min • ${Number(payload.chlorine_strength_percent).toFixed(1)}%`;
  settingsSetBadge("chlorinationBadge", payload.enabled ? "Enabled" : "Disabled", payload.enabled);
}

function collectChlorinationSettings() {
  return {
    enabled: settingsElement("chlorinationEnabled").checked,
    daily_dose_oz: settingsNumber("chlorinationDailyDoseOz"),
    pump_output_oz_per_min: settingsNumber("chlorinationPumpOutputOzPerMin"),
    chlorine_strength_percent: settingsNumber("chlorinationStrengthPercent"),
    no_dose_first_minutes: settingsNumber("chlorinationNoDoseFirstMinutes"),
    no_dose_last_minutes: settingsNumber("chlorinationNoDoseLastMinutes"),
    max_duty_cycle: settingsNumber("chlorinationMaxDutyCycle"),
    cycle_on_seconds: settingsNumber("chlorinationCycleOnSeconds"),
    min_cycle_on_seconds: settingsNumber("chlorinationMinCycleOnSeconds"),
    max_cycle_period_seconds: settingsNumber("chlorinationMaxCyclePeriodSeconds"),
  };
}

async function loadChlorinationSettings() {
  try {
    const payload = await settingsRequest("/api/config/chlorination");
    renderChlorinationSettings(payload);
    settingsSetStatus("chlorinationConfigStatus", "Saved chlorination settings loaded");
  } catch (error) {
    settingsSetStatus("chlorinationConfigStatus", error.message);
  }
}

async function saveChlorinationSettings() {
  settingsSetStatus("chlorinationConfigStatus", "Saving…");
  try {
    const payload = await settingsPost("/api/config/chlorination", collectChlorinationSettings());
    renderChlorinationSettings(payload);
    settingsSetStatus("chlorinationConfigStatus", "Chlorination settings saved and applied");
    settingsSaved();
  } catch (error) {
    settingsSetStatus("chlorinationConfigStatus", error.message);
  }
}

function renderFcDemandSettings(payload) {
  settingsElement("fcDemandEnabled").checked = Boolean(payload.enabled);
  settingsSetValue("fcDemandMode", payload.mode);
  settingsSetValue("fcDemandTargetFcPpm", payload.target_fc_ppm);
  settingsSetValue("fcDemandMaxDailyDoseOz", payload.max_daily_dose_oz);
  settingsSetValue("fcDemandMinimumTestIntervalHours", payload.minimum_test_interval_hours);
  settingsSetValue("fcDemandMaxObservationIntervalDays", payload.max_observation_interval_days);
  settingsSetValue("fcDemandPreferredTestStartHour", payload.preferred_test_start_hour);
  settingsSetValue("fcDemandPreferredTestEndHour", payload.preferred_test_end_hour);
  settingsSetValue("fcDemandRecentObservationCount", payload.recent_observation_count);
  settingsSetValue("fcDemandObservationWeights", (payload.observation_weights || []).join(", "));
  settingsSetValue(
    "fcDemandNegativeDemandNoiseTolerance",
    payload.negative_demand_noise_tolerance_ppm_per_day,
  );
  settingsSetValue("fcDemandFeedbackGain", payload.fc_feedback_gain);
  settingsSetValue("fcDemandMaxMaintenanceChangePercent", payload.max_maintenance_change_percent);
  const basis = payload.dose_basis || {};
  settingsElement("fcDemandDoseBasis").textContent =
    `Dose basis: ${Number(basis.pool_volume_gal).toLocaleString()} gal • ${Number(basis.chlorine_strength_percent).toFixed(1)}% chlorine`;
  const mode = String(payload.mode || "observe_only").replaceAll("_", " ");
  settingsElement("fcDemandSummary").textContent =
    `${mode} • target ${Number(payload.target_fc_ppm).toFixed(1)} ppm`;
  settingsSetBadge("fcDemandBadge", payload.enabled ? "Enabled" : "Disabled", payload.enabled);
}

function collectFcDemandSettings() {
  return {
    enabled: settingsElement("fcDemandEnabled").checked,
    mode: settingsElement("fcDemandMode").value,
    target_fc_ppm: settingsNumber("fcDemandTargetFcPpm"),
    max_daily_dose_oz: settingsNumber("fcDemandMaxDailyDoseOz"),
    minimum_test_interval_hours: settingsNumber("fcDemandMinimumTestIntervalHours"),
    max_observation_interval_days: settingsNumber("fcDemandMaxObservationIntervalDays"),
    preferred_test_start_hour: settingsNumber("fcDemandPreferredTestStartHour"),
    preferred_test_end_hour: settingsNumber("fcDemandPreferredTestEndHour"),
    recent_observation_count: settingsNumber("fcDemandRecentObservationCount"),
    observation_weights: settingsElement("fcDemandObservationWeights").value
      .split(",")
      .map((value) => Number(value.trim()))
      .filter((value) => Number.isFinite(value)),
    negative_demand_noise_tolerance_ppm_per_day:
      settingsNumber("fcDemandNegativeDemandNoiseTolerance"),
    fc_feedback_gain: settingsNumber("fcDemandFeedbackGain"),
    max_maintenance_change_percent: settingsNumber("fcDemandMaxMaintenanceChangePercent"),
  };
}

async function loadFcDemandSettings() {
  try {
    const payload = await settingsRequest("/api/config/fc_demand");
    renderFcDemandSettings(payload);
    settingsSetStatus("fcDemandConfigStatus", "Saved FC control settings loaded");
  } catch (error) {
    settingsSetStatus("fcDemandConfigStatus", error.message);
  }
}

async function saveFcDemandSettings() {
  settingsSetStatus("fcDemandConfigStatus", "Saving…");
  try {
    const payload = await settingsPost("/api/config/fc_demand", collectFcDemandSettings());
    renderFcDemandSettings(payload);
    settingsSetStatus("fcDemandConfigStatus", "FC control settings saved and applied");
    settingsSaved();
  } catch (error) {
    settingsSetStatus("fcDemandConfigStatus", error.message);
  }
}

function renderFilterLoadingSettings(payload) {
  settingsElement("filterLoadingEnabled").checked = Boolean(payload.enabled);
  settingsSetValue("filterLoadingCleanFlowGpm", payload.clean_flow_gpm);
  settingsSetValue("filterLoadingStabilizationSeconds", payload.stabilization_seconds);
  settingsSetValue("filterLoadingAveragingSeconds", payload.averaging_seconds);
  settingsSetValue("filterLoadingMaxPressureAgeSeconds", payload.max_pressure_age_seconds);
  const cleanFlow = payload.clean_flow_gpm === null ? "Not calibrated" :
    `Clean flow ${Number(payload.clean_flow_gpm).toFixed(1)} GPM`;
  settingsElement("filterSummary").textContent = cleanFlow;
  settingsSetBadge("filterBadge", payload.enabled ? "Enabled" : "Disabled", payload.enabled);
}

async function loadFilterLoadingSettings() {
  try {
    const payload = await settingsRequest("/api/config/filter_loading");
    renderFilterLoadingSettings(payload);
    settingsSetStatus("filterLoadingConfigStatus", "Saved filter model loaded");
  } catch (error) {
    settingsSetStatus("filterLoadingConfigStatus", error.message);
  }
}

async function saveFilterLoadingSettings() {
  settingsSetStatus("filterLoadingConfigStatus", "Saving…");
  try {
    const payload = await settingsPost("/api/config/filter_loading", {
      enabled: settingsElement("filterLoadingEnabled").checked,
      clean_flow_gpm: settingsNumber("filterLoadingCleanFlowGpm", { optional: true }),
      stabilization_seconds: settingsNumber("filterLoadingStabilizationSeconds"),
      averaging_seconds: settingsNumber("filterLoadingAveragingSeconds"),
      max_pressure_age_seconds: settingsNumber("filterLoadingMaxPressureAgeSeconds"),
    });
    renderFilterLoadingSettings(payload);
    settingsSetStatus("filterLoadingConfigStatus", "Filter model saved and applied");
    settingsSaved();
  } catch (error) {
    settingsSetStatus("filterLoadingConfigStatus", error.message);
  }
}

function renderFlowModel(payload) {
  const model = payload.pump_pressure || {};
  settingsSetValue("flowPressureScale", model.pressure_scale_psi);
  settingsSetValue("flowDynamicCoefficient", model.c_dynamic);
  settingsSetValue("flowSuctionCoefficient", model.c_suction);
  settingsSetValue("flowNoFlowLow", model.c_no_flow_low);
  settingsSetValue("flowNoFlowHigh", model.c_no_flow_high);
}

async function loadFlowModel() {
  try {
    renderFlowModel(await settingsRequest("/api/config/flow_estimation"));
    settingsSetStatus("flowModelStatus", "Saved flow model loaded");
  } catch (error) {
    settingsSetStatus("flowModelStatus", error.message);
  }
}

async function saveFlowModel() {
  settingsSetStatus("flowModelStatus", "Saving…");
  try {
    const payload = await settingsPost("/api/config/flow_estimation", {
      pump_pressure: {
        pressure_scale_psi: settingsNumber("flowPressureScale"),
        c_dynamic: settingsNumber("flowDynamicCoefficient"),
        c_suction: settingsNumber("flowSuctionCoefficient"),
        c_no_flow_low: settingsNumber("flowNoFlowLow"),
        c_no_flow_high: settingsNumber("flowNoFlowHigh"),
      },
    });
    renderFlowModel(payload);
    settingsSetStatus("flowModelStatus", "Flow model saved and applied");
    settingsSaved();
  } catch (error) {
    settingsSetStatus("flowModelStatus", error.message);
  }
}

function renderNotificationRules() {
  const container = settingsElement("notificationRuleRows");
  if (!container || !settingsNotifications) {
    return;
  }
  container.replaceChildren();
  SETTINGS_NOTIFICATION_RULES.forEach(([ruleId, label]) => {
    const rule = (settingsNotifications.rules || {})[ruleId] || {};
    const card = document.createElement("div");
    card.className = "notification-rule";
    card.dataset.ruleId = ruleId;

    const heading = document.createElement("div");
    heading.className = "notification-rule-heading";
    const title = document.createElement("strong");
    title.textContent = label;
    const enabledLabel = document.createElement("label");
    enabledLabel.className = "setting-toggle";
    enabledLabel.append("Enabled ");
    const enabled = document.createElement("input");
    enabled.type = "checkbox";
    enabled.dataset.ruleField = "enabled";
    enabled.checked = Boolean(rule.enabled);
    enabledLabel.appendChild(enabled);
    heading.append(title, enabledLabel);
    card.appendChild(heading);

    const fields = document.createElement("div");
    fields.className = "notification-rule-fields";
    if (ruleId !== "freeze_temperature_unavailable") {
      fields.appendChild(notificationCheckbox("Caution", "notify_caution", rule.notify_caution !== false));
    }
    fields.appendChild(notificationCheckbox("Alarm", "notify_alarm", rule.notify_alarm !== false));
    if (ruleId !== "freeze_temperature_unavailable") {
      fields.appendChild(notificationRepeatField("Caution repeat", "caution_repeat_minutes", rule.caution_repeat_minutes));
    }
    fields.appendChild(notificationRepeatField("Alarm repeat", "alarm_repeat_minutes", rule.alarm_repeat_minutes));
    card.appendChild(fields);

    const threshold = document.createElement("p");
    threshold.className = "notification-rule-thresholds";
    threshold.textContent = `Thresholds: ${thresholdDescription(ruleId)}`;
    card.appendChild(threshold);
    container.appendChild(card);
  });
}

function notificationCheckbox(label, field, checked) {
  const wrapper = document.createElement("label");
  wrapper.className = "setting-toggle";
  wrapper.append(label);
  const input = document.createElement("input");
  input.type = "checkbox";
  input.dataset.ruleField = field;
  input.checked = checked;
  wrapper.appendChild(input);
  return wrapper;
}

function notificationRepeatField(label, field, minutes) {
  const wrapper = document.createElement("label");
  wrapper.textContent = `${label} (min)`;
  const input = document.createElement("input");
  input.type = "number";
  input.min = "0";
  input.step = "1";
  input.dataset.ruleField = field;
  input.value = String(minutes ?? 0);
  wrapper.appendChild(input);
  return wrapper;
}

function renderNotificationsSettings(payload) {
  settingsNotifications = payload;
  settingsElement("notificationsEnabled").checked = Boolean(payload.enabled);
  settingsSetValue("notificationsProvider", payload.provider);
  settingsSetValue("notificationsDefaultTitle", payload.default_title);
  const pushover = payload.pushover || {};
  settingsSetValue("pushoverAppToken", "");
  settingsSetValue("pushoverUserKey", "");
  settingsSetValue("pushoverAppTokenEnv", pushover.app_token_env);
  settingsSetValue("pushoverUserKeyEnv", pushover.user_key_env);
  settingsSetValue("pushoverApiUrl", pushover.api_url);
  settingsSetValue("pushoverTimeout", pushover.timeout_s);
  settingsSetValue("pushoverPriority", pushover.priority);
  settingsSetValue("pushoverSound", pushover.sound);
  renderNotificationRules();
  const enabledRules = Object.values(payload.rules || {}).filter((rule) => rule.enabled).length;
  settingsElement("notificationsSummary").textContent =
    `${String(payload.provider || "pushover").replaceAll("_", " ")} • ${enabledRules} active rules`;
  settingsSetBadge("notificationsBadge", payload.enabled ? "Enabled" : "Disabled", payload.enabled);
}

function collectNotificationsSettings() {
  const pushover = {
    app_token_env: settingsElement("pushoverAppTokenEnv").value.trim(),
    user_key_env: settingsElement("pushoverUserKeyEnv").value.trim(),
    api_url: settingsElement("pushoverApiUrl").value.trim(),
    timeout_s: settingsNumber("pushoverTimeout"),
    priority: settingsNumber("pushoverPriority"),
    sound: settingsElement("pushoverSound").value.trim() || null,
  };
  const appToken = settingsElement("pushoverAppToken").value.trim();
  const userKey = settingsElement("pushoverUserKey").value.trim();
  if (appToken) pushover.app_token = appToken;
  if (userKey) pushover.user_key = userKey;
  const rules = {};
  document.querySelectorAll(".notification-rule[data-rule-id]").forEach((card) => {
    const rule = {};
    card.querySelectorAll("[data-rule-field]").forEach((input) => {
      rule[input.dataset.ruleField] =
        input.type === "checkbox" ? input.checked : Number(input.value);
    });
    rules[card.dataset.ruleId] = rule;
  });
  return {
    enabled: settingsElement("notificationsEnabled").checked,
    provider: settingsElement("notificationsProvider").value,
    default_title: settingsElement("notificationsDefaultTitle").value.trim(),
    pushover,
    rules,
  };
}

async function loadNotificationsSettings() {
  try {
    renderNotificationsSettings(await settingsRequest("/api/config/notifications"));
    settingsSetStatus("notificationsStatus", "Saved notification settings loaded");
  } catch (error) {
    settingsSetStatus("notificationsStatus", error.message);
  }
}

async function saveNotificationsSettings() {
  settingsSetStatus("notificationsStatus", "Saving…");
  try {
    const payload = await settingsPost("/api/config/notifications", collectNotificationsSettings());
    renderNotificationsSettings(payload);
    settingsSetStatus("notificationsStatus", "Notification settings saved and applied");
    settingsSaved();
  } catch (error) {
    settingsSetStatus("notificationsStatus", error.message);
  }
}

async function sendSettingsTestNotification() {
  settingsSetStatus("notificationsStatus", "Sending test…");
  try {
    const payload = await settingsPost("/api/notifications/test", {
      title: settingsElement("notificationsDefaultTitle").value.trim() || "PoolScope",
      message: "PoolScope Settings test notification",
    });
    const result = payload.notification || {};
    settingsSetStatus("notificationsStatus", result.sent ? "Test notification sent" : (result.error || "Test skipped"));
  } catch (error) {
    settingsSetStatus("notificationsStatus", error.message);
  }
}

function renderRuntimeSettings(payload) {
  settingsRuntime = payload;
  settingsSetValue("runtimeDriverProfile", payload.driver_profile);
  const actuatorContainer = settingsElement("runtimeActuatorOptions");
  const sensorContainer = settingsElement("runtimeSensorGroupOptions");
  actuatorContainer.replaceChildren();
  sensorContainer.replaceChildren();
  const enabledActuators = new Set(payload.enabled_actuators || []);
  ACTUATOR_ORDER.forEach((actuatorId) => {
    actuatorContainer.appendChild(settingsChoice(actuatorId, actuatorId.replaceAll("_", " "), enabledActuators.has(actuatorId)));
  });
  const knownGroups = new Set([...(payload.enabled_sensor_groups || []), "pressures", "chemistry_loop", "system"]);
  knownGroups.forEach((groupId) => {
    sensorContainer.appendChild(settingsChoice(groupId, groupId.replaceAll("_", " "), (payload.enabled_sensor_groups || []).includes(groupId)));
  });
  settingsElement("hardwareSummary").textContent =
    `${String(payload.driver_profile).replaceAll("_", " ")} • ${enabledActuators.size} actuators`;
}

function settingsChoice(value, labelText, checked) {
  const label = document.createElement("label");
  const input = document.createElement("input");
  input.type = "checkbox";
  input.value = value;
  input.checked = checked;
  label.append(input, document.createTextNode(labelText));
  return label;
}

async function loadRuntimeSettings() {
  try {
    renderRuntimeSettings(await settingsRequest("/api/config/runtime"));
    settingsSetStatus("runtimeStatus", "Active runtime settings loaded");
  } catch (error) {
    settingsSetStatus("runtimeStatus", error.message);
  }
}

async function saveRuntimeSettings() {
  settingsSetStatus("runtimeStatus", "Saving…");
  try {
    const payload = {
      driver_profile: settingsElement("runtimeDriverProfile").value,
      enabled_actuators: [...settingsElement("runtimeActuatorOptions").querySelectorAll("input:checked")]
        .map((input) => input.value),
      enabled_sensor_groups: [...settingsElement("runtimeSensorGroupOptions").querySelectorAll("input:checked")]
        .map((input) => input.value),
    };
    await settingsPost("/api/config/runtime", payload);
    renderRuntimeSettings({ ...payload, requires_restart: true });
    settingsSetStatus("runtimeStatus", "Runtime settings saved — restart required");
    settingsSaved({ restartRequired: true });
  } catch (error) {
    settingsSetStatus("runtimeStatus", error.message);
  }
}

function renderOrpSettings(payload) {
  const sensor = payload.modbus_orp_sensor || {};
  const breaker = sensor.circuit_breaker || {};
  settingsSetValue("orpSensorPort", sensor.port);
  settingsSetValue("orpSensorSlaveId", sensor.slave_id);
  settingsSetValue("orpSensorBaudrate", sensor.baudrate);
  settingsSetValue("orpSensorTimeout", sensor.timeout_s);
  settingsElement("orpBreakerEnabled").checked = breaker.enabled !== false;
  settingsSetValue("orpBreakerFailures", breaker.failure_threshold);
  settingsSetValue("orpBreakerCooldown", breaker.cooldown_s);
}

async function loadOrpSettings() {
  try {
    renderOrpSettings(await settingsRequest("/api/config/orp_sensor"));
    settingsSetStatus("orpSensorStatus", "Saved ORP hardware settings loaded");
  } catch (error) {
    settingsSetStatus("orpSensorStatus", error.message);
  }
}

async function saveOrpSettings() {
  settingsSetStatus("orpSensorStatus", "Saving…");
  try {
    await settingsPost("/api/config/orp_sensor", {
      modbus_orp_sensor: {
        port: settingsElement("orpSensorPort").value.trim(),
        slave_id: settingsNumber("orpSensorSlaveId"),
        baudrate: settingsNumber("orpSensorBaudrate"),
        timeout_s: settingsNumber("orpSensorTimeout"),
        circuit_breaker: {
          enabled: settingsElement("orpBreakerEnabled").checked,
          failure_threshold: settingsNumber("orpBreakerFailures"),
          cooldown_s: settingsNumber("orpBreakerCooldown"),
        },
      },
    });
    settingsSetStatus("orpSensorStatus", "ORP settings saved — restart required");
    settingsSaved({ restartRequired: true });
  } catch (error) {
    settingsSetStatus("orpSensorStatus", error.message);
  }
}

function renderRelaySettings(payload) {
  const relay = payload.modbus_relay || {};
  const channels = relay.relays || {};
  const speeds = relay.pump_speed_relay || {};
  settingsSetValue("relayPort", relay.port);
  settingsSetValue("relaySlaveId", relay.slave_id);
  settingsSetValue("relayBaudrate", relay.baudrate);
  settingsSetValue("relayTimeout", relay.timeout_s);
  settingsElement("relayDosingUsesFlash").checked = relay.dosing_uses_flash !== false;
  settingsElement("relayStartupSafeOff").checked = relay.startup_safe_off !== false;
  settingsSetValue("relayReconciliationInterval", relay.reconciliation_interval_s);
  settingsSetValue("relayPumpMotor", channels.pump_motor);
  settingsSetValue("relayPumpSpeed", channels.pump_motor_speed);
  settingsSetValue("relayBooster", channels.booster_pump);
  settingsSetValue("relayDosingPump", channels.chlorine_dosing_pump);
  settingsSetValue("relayLowState", String(speeds.low_state !== false));
  settingsSetValue("relayHighState", String(speeds.high_state === true));
}

async function loadRelaySettings() {
  try {
    renderRelaySettings(await settingsRequest("/api/config/relay"));
    settingsSetStatus("relayStatus", "Saved relay settings loaded");
  } catch (error) {
    settingsSetStatus("relayStatus", error.message);
  }
}

async function saveRelaySettings() {
  settingsSetStatus("relayStatus", "Saving…");
  try {
    const payload = {
      modbus_relay: {
        port: settingsElement("relayPort").value.trim(),
        slave_id: settingsNumber("relaySlaveId"),
        baudrate: settingsNumber("relayBaudrate"),
        timeout_s: settingsNumber("relayTimeout"),
        dosing_uses_flash: settingsElement("relayDosingUsesFlash").checked,
        startup_safe_off: settingsElement("relayStartupSafeOff").checked,
        reconciliation_interval_s: settingsNumber("relayReconciliationInterval"),
        relays: {
          pump_motor: settingsNumber("relayPumpMotor"),
          pump_motor_speed: settingsNumber("relayPumpSpeed"),
          booster_pump: settingsNumber("relayBooster"),
          chlorine_dosing_pump: settingsNumber("relayDosingPump"),
        },
        pump_speed_relay: {
          low_state: settingsElement("relayLowState").value === "true",
          high_state: settingsElement("relayHighState").value === "true",
        },
      },
    };
    await settingsPost("/api/config/relay", payload);
    renderRelaySettings(payload);
    settingsSetStatus("relayStatus", "Relay settings saved — restart required");
    settingsSaved({ restartRequired: true });
  } catch (error) {
    settingsSetStatus("relayStatus", error.message);
  }
}

async function refreshSettingsMeta(force = false) {
  const now = Date.now();
  if (!force && now - settingsLastMetaLoad < 5000) {
    return;
  }
  try {
    const payload = await settingsRequest("/api/settings/meta");
    settingsSetValue("settingsConfigPath", payload.config_path);
    settingsSetValue("settingsLocalConfigPath", payload.local_config_path || "Not configured");
    settingsSetValue("settingsWritePath", payload.write_path);
    ["settingsConfigPath", "settingsLocalConfigPath", "settingsWritePath"].forEach((id) => {
      const node = settingsElement(id);
      const key = id === "settingsConfigPath" ? "config_path" :
        id === "settingsLocalConfigPath" ? "local_config_path" : "write_path";
      node.textContent = payload[key] || (key === "local_config_path" ? "Not configured" : "--");
    });
    const badge = settingsElement("restartBadge");
    badge.classList.toggle("hidden", !payload.restart_required);
    settingsSetStatus(
      "configSyncStatus",
      payload.restart_required
        ? "Saved settings differ from the running controller — restart required"
        : (settingsDirty ? "Unsaved changes" : "Settings are synchronized"),
    );
    settingsLastMetaLoad = now;
  } catch (error) {
    settingsSetStatus("configSyncStatus", error.message);
  }
}

async function reloadAllSettings() {
  if (settingsDirty && !window.confirm("Discard unsaved changes and reload saved settings?")) {
    return;
  }
  settingsLoading = true;
  settingsSetStatus("configSyncStatus", "Loading saved settings…");
  await Promise.all([
    loadPoolConfig(),
    loadSettingsSite(),
    loadMonitoringConfig(),
    loadChlorinationSettings(),
    loadFcDemandSettings(),
    loadFilterLoadingSettings(),
    loadFlowModel(),
    loadNotificationsSettings(),
    loadRuntimeSettings(),
    loadOrpSettings(),
    loadRelaySettings(),
  ]);
  settingsLoading = false;
  settingsDirty = false;
  await refreshSettingsMeta(true);
}

function settingsBind(id, eventName, handler) {
  const node = settingsElement(id);
  if (node) {
    node.addEventListener(eventName, handler);
  }
}

function initializeSettingsPage() {
  initializeSettingsLinks();
  document.querySelector('[data-view-section="settings"]').addEventListener("input", () => {
    if (!settingsLoading) {
      settingsDirty = true;
      settingsSetStatus("configSyncStatus", "Unsaved changes");
    }
  });
  document.querySelector('[data-view-section="settings"]').addEventListener("change", () => {
    if (!settingsLoading) {
      settingsDirty = true;
      settingsSetStatus("configSyncStatus", "Unsaved changes");
    }
  });

  settingsBind("settingsReloadSaved", "click", reloadAllSettings);
  settingsBind("configRestartService", "click", requestServiceRestart);
  settingsBind("poolSave", "click", savePoolConfig);
  settingsBind("siteSave", "click", saveSettingsSite);
  settingsBind("siteReload", "click", loadSettingsSite);
  settingsBind("monitoringSave", "click", saveMonitoringConfig);
  settingsBind("monitoringReload", "click", loadMonitoringConfig);
  settingsBind("chlorinationSave", "click", saveChlorinationSettings);
  settingsBind("chlorinationReload", "click", loadChlorinationSettings);
  settingsBind("chlorinationPrimeConfigButton", "click", primeChlorinationPump);
  settingsBind("chlorinationCalibrationConfigButton", "click", startChlorinationCalibration);
  settingsBind("chlorinationDiagnosticStopButton", "click", stopChlorinationDiagnostic);
  settingsBind("fcDemandSave", "click", saveFcDemandSettings);
  settingsBind("fcDemandReload", "click", loadFcDemandSettings);
  settingsBind("filterLoadingSave", "click", saveFilterLoadingSettings);
  settingsBind("filterLoadingReload", "click", loadFilterLoadingSettings);
  settingsBind("flowModelSave", "click", saveFlowModel);
  settingsBind("notificationsSave", "click", saveNotificationsSettings);
  settingsBind("notificationsReload", "click", loadNotificationsSettings);
  settingsBind("notificationsTest", "click", sendSettingsTestNotification);
  settingsBind("runtimeSave", "click", saveRuntimeSettings);
  settingsBind("runtimeReload", "click", loadRuntimeSettings);
  settingsBind("orpSensorSave", "click", saveOrpSettings);
  settingsBind("orpSensorReload", "click", loadOrpSettings);
  settingsBind("relaySave", "click", saveRelaySettings);
  settingsBind("relayReload", "click", loadRelaySettings);

  initializeSafetyControls();
  initializeAcquisitionControls();
  initializeLoggingControls();
  initializeAnalogControls();
  initializePhSensorControls();
  void reloadAllSettings();
}
