# poolctl

`poolctl` is a Python pool automation controller being built for a Raspberry Pi 5.
It is designed to be developed on Windows with simulated hardware and deployed
to Raspberry Pi OS 64-bit Bookworm with Modbus sensors and relays.

The project is intentionally layered:

- Domain models define stable actuator, sensor, command, and measurement types.
- Drivers isolate simulated hardware, Modbus relay hardware, and Modbus sensors.
- Services implement acquisition, logging, timers, safety, flow estimation,
  chlorination, weather logging, notifications, and derived chemistry metrics.
- The web server owns the live dashboard, history charts, config forms, and the
  dedicated runtime tick loop.

## Current Capabilities

- Windows simulation using a correlated simulated pool plant.
- Raspberry Pi Modbus relay control through a Waveshare 8-channel RTU relay.
- Raspberry Pi Modbus analog input support for pressure channels.
- DFRobot Modbus ORP and pH sensor support, including probe temperatures.
- Named pump schedule profiles with fixed-clock, sunrise/sunset anchor, and
  daylight-fraction timing plus manual dashboard overrides.
- Open-loop chlorine dosing on relay 7. On Raspberry Pi hardware, dosing ON
  pulses use the Waveshare relay module's timed flash command by default so the
  module turns the relay off even if the Pi process dies mid-pulse.
- Optional FC-demand controller based on manual FC tests and logged chlorine
  delivery/additions. ORP and pH are not used by this controller.
- Always-present SafetyGate with configurable pump-output pressure gates,
  chlorine tank hysteresis, freeze protection, and lockouts.
- Freeze protection with hysteresis and minimum runtime.
- Sensor acquisition with per-group read/log rates, optional burst
  oversampling, and rolling boxcar filters.
- Standardized filter-loading estimates based on qualifying high-speed
  pump-output pressure tests.
- SQLite logging for measurements, weather, test results, chemical additions,
  and notification edge/cooldown state.
- Live web GUI, mobile-friendly live list view, config forms, schedule editor,
  test result entry, chemical addition entry, and history charts.
- Raspberry Pi CPU temperature, CPU load, and CPU fan RPM live display and
  logging.
- Hourly Open-Meteo weather observation logging plus a 48-hour in-memory forecast.
- Optional Pushover notification provider with a dashboard test button.
- Systemd deployment with automatic restart and SQLite backup timer.
- Repo-level `AGENTS.md` guidance for future Codex agents.

## Repository Layout

```text
configs/
  windows-dev.yaml        Windows simulation profile.
  pi-prod.yaml            Raspberry Pi production profile.
deploy/systemd/
  install-pi-services.sh  Installer for poolctl and backup systemd units.
  *.tmpl                  Service and backup script templates.
src/poolctl/
  app.py                  Runtime composition and continuous tick logic.
  config.py               Runtime hardware profile and live view config models.
  domain/models.py        Stable domain identifiers and data models.
  drivers/                Simulated and Raspberry Pi hardware drivers.
  services/               Acquisition, timer, safety, logging, weather, etc.
  tools/                  Modbus bring-up and configuration helpers.
  web/                    HTTP server and static dashboard assets.
tests/                    Unit and integration-style tests.
```

## Python Versions

The project supports Python `>=3.11,<3.14`.

- The production Raspberry Pi 5 target is Raspberry Pi OS 64-bit Bookworm with
  Python 3.11.2.
- Windows development uses Python 3.13.
- Source syntax, standard-library use, linting, and type checking use Python
  3.11 as the compatibility baseline.

## Windows Development Setup

From a PowerShell terminal in the repo root:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

The Raspberry Pi hardware extras are not needed on Windows. Install
`.[raspberrypi]` only on the Pi.

## Run the Windows Simulator and GUI

Start the dashboard with the simulated hardware profile:

```powershell
.\.venv\Scripts\Activate.ps1
python -m poolctl.web.server --config configs/windows-dev.yaml --host 127.0.0.1 --port 8000 --sim-speedup 60 --tick-interval-s 0.25
```

Open:

```text
http://127.0.0.1:8000
```

Notes:

- `--sim-speedup 60` means one real second advances the simulated clock by
  about one simulated minute.
- `--tick-interval-s 0.25` runs the runtime control loop four times per real
  second.
- The runtime loop keeps acquisition, timers, dosing, logging, and safety moving
  even when the browser is closed. Weather polling runs in a separate background
  worker so slow HTTP requests cannot delay relay decisions.
- Each tick evaluates timer state and time-critical chlorine relay transitions
  before potentially slower sensor acquisition. Acquisition then refreshes due
  measurements, after which derived values and SafetyGate enforcement use the
  latest available readings. On supported Pi relays, timed flash independently
  ends each normal dosing pulse even if process scheduling is delayed.
- Stop the process with `Ctrl+C`.

After installing the editable package, the console entry point is also valid:

```powershell
poolctl --config configs/windows-dev.yaml --host 127.0.0.1 --port 8000 --sim-speedup 60
```

## Tests and Lint

Run the full test suite:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest
```

Run Ruff:

```powershell
python -m ruff check src tests
```

Run strict type checking:

```powershell
python -m mypy src
```

GitHub Actions runs the full test, lint, and type-check suite on both Python
3.11 and Python 3.13.

Useful focused runs:

```powershell
python -m pytest tests\test_chlorination.py
python -m pytest tests\test_web_live.py tests\test_web_server_config.py
```

## Configuration Overview

The active config controls the deployment. The two main tracked base configs are:

- `configs/windows-dev.yaml`
- `configs/pi-prod.yaml`

The Raspberry Pi service can also load an ignored local override file:

- `configs/pi-local.yaml`

At runtime, `pi-local.yaml` is merged on top of `pi-prod.yaml`. Nested mappings
merge recursively, while lists replace the base list. That means a local
`pump_timer.profiles` list replaces the tracked profile list as a whole.

Use this local file for values that change on the actual pool:

- shared site timezone/coordinates and pump timer profiles
- `allow_dosing` choices per schedule window
- daily chlorine dose
- dosing pump calibration rate
- pool name and volume
- chlorine strength, dosing-pump calibration, and daily dose
- FC-demand target and operating mode
- real site latitude/longitude (tracked configs use the neutral `45.0, -90.0`
  demonstration location and keep weather disabled)
- measured clean-filter `clean_flow_gpm` (`Qclean`)
- site-specific paths or hardware settings if they differ from the tracked base

`configs/pi-local.yaml` is ignored by git. `configs/pi-local.example.yaml` is a
minimal, comments-only template you can copy on the Pi. Copying it as-is adds no
overrides:

```bash
cp configs/pi-local.example.yaml configs/pi-local.yaml
```

Tracked production and development configs intentionally keep `site.latitude`
and `site.longitude` null and weather disabled so the public repository contains
no site location. Solar schedules and enabled weather both use this shared site
block. Enabling either feature without both coordinates is a configuration
error; leaving weather disabled skips it cleanly without creating observations
for a fake location.

The dashboard Settings and Schedule forms save to the local override when the
server is started with `--local-config`. Site timezone and coordinates are
maintained under **Pool & Site** on the Settings page; the Schedule page saves
only profile definitions. This lets `git pull` update `configs/pi-prod.yaml`
without conflicting with daily schedule and dosing edits made on the Pi.
`GET /api/config/site` reads the effective canonical site block and
`POST /api/config/site` validates, persists, and applies it to schedule
resolution and weather polling without a restart.

Important sections:

- `runtime`: driver profile, installed actuators, and enabled acquisition
  sensor groups.
- `pool`: canonical pool name and volume.
- `site`: canonical local timezone and coordinates shared by schedules and weather.
- `pump_timer`: named profiles, active profile, typed schedule timing,
  pump/booster state, and chlorine-dosing eligibility.
- `chlorination`: open-loop liquid chlorine dose settings, pump calibration,
  and canonical sodium-hypochlorite concentration.
- `fc_demand`: optional free-chlorine demand estimator settings.
- `safety`: pump-output pressure interlocks, tank hysteresis, lockout
  thresholds, and freeze protection.
- `acquisition`: sensor groups, read intervals, log intervals, validation rules,
  optional burst oversampling, rolling filters, chemistry refresh runs.
- `logging`: SQLite database path and controller-state snapshot interval.
- `modbus_relay`: relay board serial settings, Modbus slave ID, relay mapping.
  `dosing_uses_flash` defaults to `true` so chlorine dosing ON commands are
  sent as Waveshare timed flash pulses instead of latched relay ON writes.
  `startup_safe_off` commands safe actuator states once at boot, and
  `reconciliation_interval_s` periodically reads relay states and corrects
  mismatches.
- `modbus_analog_input`: analog board serial settings, channel mappings, 2-point
  calibration.
- `modbus_orp_sensor`: ORP sensor serial settings.
- `modbus_ph_sensor`: pH sensor serial settings.
- `flow_estimation`: pump-output-pressure flow constants.
- `filter_loading`: standardized high-speed pump-output pressure test
  calibration and timing.
- `monitoring.limits`: canonical user-visible normal/caution/alarm boundaries
  shared by dashboard KPIs, history bands, filter/tank status, and notification
  evaluation.
- `display.live_kpi_charts`: per-card Live chart windows, canonical display
  units, and automatic or fixed y-axis bounds. These settings affect display
  queries only, not sampling, retention, control, or safety.
- `weather`: Open-Meteo enablement, units, and polling settings; location comes
  from `site`.
- `notifications`: push notification provider settings and optional state rules
  for usable chlorine tank days remaining, pH, ORP, filter flow loss, and total
  freeze-temperature loss, plus edge-triggered freeze activation and debounced
  high CPU temperature. Generic measurement thresholds are not stored here;
  the CPU rule owns its explicitly Celsius system-telemetry threshold.
  Pushover keys can be entered on the Settings page or supplied through
  environment variables.

### Settings organization and ownership

`/settings` is the canonical configuration UI; `/config` redirects there for
older bookmarks. The page uses collapsible, responsive cards organized around
pool-owner concepts:

- Pool Settings: Pool & Site, Status Ranges, Chlorination, Free Chlorine
  Control, Filter & Flow, Notifications, and Display & Dashboard.
- Advanced: Safety & Freeze, Sensors & Calibration, Acquisition & Logging, and
  Hardware & Runtime.

Collapsed cards summarize their important effective values. Expanded cards span
the available grid width, related values owned elsewhere are shown read-only
with a link to their canonical card, and hardware/acquisition changes are
clearly marked as requiring a controller restart. Saving does not restart the
service automatically.

PoolScope follows a one-value-one-owner rule. In particular, pool volume belongs
to `pool.volume_gal`, chlorine concentration belongs to
`chlorination.chlorine_strength_percent`, FC controller tuning belongs to
`fc_demand`, visible status boundaries belong to `monitoring.limits`, and
notification cadence/severity selection belongs to `notifications.rules`.
Safety interlocks remain under `safety` even where a number resembles a visible
status limit: an interlock changes equipment behavior, while a monitoring limit
only classifies and reports state.

The shared threshold classifier emits `normal`, `caution`, `alarm`, `invalid`,
or `unknown`. Alarm boundaries take precedence over caution boundaries, and
configured boundaries are inclusive. One-sided limits are valid. Missing
measurements are unknown; non-finite or explicitly bad measurements are
invalid. Dashboard KPI colors, history status bands, filter/tank indicators,
and notification evaluation all consume this same classification. Live
measurement availability is separate: circulation-dependent measurements can
be `pump_off`, `settling`, `stale`, or `sensor_failure`. A valid measurement
without an alert threshold, such as water temperature by default, is still a
current usable reading; it does not need to be mislabeled as `Normal` merely to
avoid an unknown threshold state.

Existing installations migrate during configuration normalization without
changing their configured numeric values. Settings saves are applied from the
newly reloaded, merged base-plus-local effective configuration, so the value
shown after a save is the same value used by the runtime. Legacy
`fc_demand.pool_volume_gal`
and `fc_demand.chlorine_strength_percent`, `live_view.sensor_limits`,
notification `alerts` thresholds, and filter yellow/red flow-loss fields may
still be read when the canonical value is absent. A canonical value in the
same layer wins; a local legacy override can still supersede a tracked base
value during migration. Conflicting legacy threshold copies are rejected
instead of silently choosing one. Newly saved/generated configuration contains
only `pool`, `chlorination`, `monitoring.limits`, and threshold-free
`notifications.rules` ownership.

Ranges use explicit directional names and may be two-sided or one-sided:

```yaml
monitoring:
  limits:
    raw_ph:
      alarm_below: 6.8
      caution_below: 7.2
      caution_above: 7.8
      alarm_above: 8.2
    filter_flow_loss_percent:
      caution_above: 10.0
      alarm_above: 15.0
    chlorine_tank_days_remaining:
      alarm_below: 3.0
      caution_below: 7.0
```

The canonical schedule schema uses one active profile and typed timing. Fixed
clock values should be quoted strings:

```yaml
site:
  timezone: America/Chicago
  latitude: 41.88
  longitude: -87.63
pump_timer:
  active_profile: normal
  profiles:
  - name: normal
    schedules:
    - name: morning_circulation
      enabled: true
      timing:
        type: fixed
        start: '08:00'
        end: '12:00'
      pump_speed: low
      booster: 'off'
      allow_dosing: true
    - name: daylight_filter
      enabled: true
      timing:
        type: daylight_fraction
        start_fraction: 0.25
        end_fraction: 0.75
      pump_speed: low
      booster: 'off'
      allow_dosing: true
    - name: sunset_cleanup
      enabled: true
      timing:
        type: solar_anchor
        anchor: sunset
        offset_minutes: -30
        duration_minutes: 60
      pump_speed: high
      booster: 'off'
      allow_dosing: false
```

`fixed` accepts either `end` or `duration_minutes`. `solar_anchor` accepts
`sunrise`, `sunset`, or `daylight_midpoint`, an offset, and a duration.
`daylight_fraction` places both boundaries along the sunrise-to-sunset interval;
fractions may be outside `0..1` when a run intentionally begins before sunrise
or ends after sunset. Solar calculations are local and offline through Astral.

Legacy `pump_timer.timezone` plus `pump_timer.schedules` remains readable as an
implicit `normal` profile, but dashboard saves write the canonical schema.
During a daylight-saving spring gap, a nonexistent fixed time moves to the first
valid local instant; an ambiguous fall-back time uses the first occurrence.
Resolved comparisons and durations use UTC instants.

`allow_dosing` defaults to `true` for older config files. A true window grants
dosing while active; an overlapping false window does not veto that grant.
Any active booster window still excludes dosing for the overlapping segment.
Set `allow_dosing: false` on night, vacuum, or skimming-only windows where the
pump should run but chlorine should not be injected.

The Schedule page presents each window as one operating mode while continuing
to save the existing controller fields and API schema:

- **Low** saves low pump speed, booster off, and dosing disallowed.
- **High** saves high pump speed, booster off, and dosing disallowed.
- **Dosing** saves low pump speed, booster off, and dosing allowed.
- **Vacuum** saves low pump speed, booster on, and dosing disallowed.

**Dosing** is an eligibility window, not a direct dosing-pump command. The
chlorination controller still decides pulse timing and routes every command
through the existing safety interlocks. Legacy combinations remain readable;
the editor resolves booster-on as Vacuum first, then dosing-allowed as Dosing,
then high speed as High, and otherwise Low. A noncanonical legacy row displays
a warning and is normalized to the selected mode only when schedules are saved.
The underlying YAML, API, overlap rules, and controller schedule model are not
changed by this UI translation.

The Schedule page uses an editor-first workspace. **Profile Selection** chooses
the profile to view or edit and provides add/remove actions; it also shows the
currently active profile as read-only context. The active profile and the final
remaining profile cannot be removed. **Profile Editor** names the selected
profile, presents each operating window as an individually labeled card, and
keeps save/reload feedback visible with the editor. The three-day resolved
preview shows the last saved configuration, including sunrise/sunset, resolved
window times, operating modes, and resolution warnings. Unsaved editor changes
do not appear in that preview until they are saved.

Use named profiles for seasonal operating plans, such as daylight-oriented
summer circulation/dosing, fall vacuum windows, and pre-sunrise winter
filtration. The Schedule page creates and edits profiles. On the Live page,
choose a profile under **Active schedule** and press **Activate** to persist it
as `pump_timer.active_profile` and apply it on the next controller tick without
a restart. Profile selection does not cancel a manual, chemistry-refresh,
supplemental-dose, or diagnostic override; the selected profile takes control
when that override ends or the operator resumes scheduled operation.

Winter schedule overlap can reduce the *additional* runtime caused by freeze
protection, but it does not replace or weaken freeze safety. Freeze protection
continues to start or extend circulation independently whenever its configured
temperature thresholds require it.

## Runtime Architecture

The web server/API is the intended remote interface. There is no separate
message bus or staged runtime mode. The app builder always wires the scheduler,
acquisition, logging, SafetyGate, chlorination controller, FC-demand estimator,
weather service, and notification service from the active config.
Browser navigation or refresh can abandon an in-flight response; expected
broken-pipe, aborted-connection, and reset-connection errors are closed quietly,
while unrelated request-handler failures continue to surface normally.

`runtime.enabled_actuators` describes which outputs are physically installed.
`runtime.enabled_sensor_groups` selects acquisition groups from the YAML. Service
behavior is controlled by each service's own `enabled` or calibration fields.
SafetyGate itself is not optional.

Tick sequencing is intentionally control-first: actuator state is refreshed,
the pump timer and chlorination boundary decisions run, and only then does due
acquisition run. Derived calculations and SafetyGate enforcement follow using
the latest available measurement set. This avoids stretching a chlorine ON
pulse while waiting for an optional Modbus probe. Waveshare timed flash is the
primary independent pulse-end protection; the later redundant OFF remains a
secondary confirmation.

The current hydraulic safety instrumentation is `pump_output_psi`. Return,
booster, bubbler, and filter-output pressure channels are not part of the active
architecture.

## Acquisition and Filtering

Each acquisition group has independent read and log timing. The controller can
read safety-critical sensors frequently while logging them less often:

```yaml
acquisition:
  groups:
    pressures:
      read_interval_s: 1
      log_interval_s: 60
```

`oversample` is still supported, but it is intended only for short immediate
bursts. Long bursts block the runtime loop, so the normal configs use one raw
read per acquisition cycle:

```yaml
      oversample:
        sample_count: 1
        sample_interval_s: 0
        reducer: last
```

Rolling `filter` settings smooth values across normal acquisition polls without
holding up actuator timing:

```yaml
      filter:
        type: boxcar
        window_samples: 2
        window_seconds: null
        min_samples: 1
```

The production Pi pressure group reads every 1 second and uses a 5-sample
boxcar (`window_samples: 5`, `min_samples: 1`). Windows simulation reads every
0.5 seconds and uses a 2-sample boxcar. SafetyGate intentionally uses the
filtered, calibrated `pump_output_psi`; the modest smoothing delay is accepted
because the configured pressure limits are deliberately conservative relative
to the plumbing damage concern and intended pump hydraulic envelope. Exact
reaction time is not guaranteed solely by filter length because scheduling and
device-read timing also apply. The chemistry group reads less often and uses a
60-second boxcar. Pump-flow-qualified chemistry readings that are invalid
because the pump is off or not yet stirred are not logged and do not enter the
rolling filter.

Normal live flow and dynamic-head estimates require the same fresh, finite,
GOOD pump-output pressure semantics used by SafetyGate. If pressure is stale,
bad, or unavailable, derived hydraulic flow is unavailable rather than shown as
a normal estimate.

## Canonical Water Temperature and Freeze Protection

`water_temp` is the single derived pool-water-temperature metric used by the
primary Live display, CSI, daily water-temperature summaries, and future
weather/FC feature history. It selects fresh `ph_temp` first and falls back to
fresh `orp_temp`; both raw probe-temperature signals remain visible and logged
for diagnostics. The generic `temp` signal remains available to simulation but
is not the production Water Temperature card input.

Live availability follows that selected source independently of monitoring
threshold configuration. A fresh valid primary or fallback value displays as a
current reading even when `monitoring.limits.water_temp` is absent. When no
source is usable, the payload reports whether the reason is pump-off
inactivity, circulation settling, stale data, or a sensor failure and may show
the last valid value and timestamp as historical context. Historical context is
display-only and is never accepted as a current control, dosing, notification,
or safety prerequisite. A known sensor fault remains visible even while the
pump is off.

Freeze protection uses the same selection and freshness semantics. The default
`max_temperature_age_seconds: 3600` matches the intentionally slow/off-cycle
chemistry refresh cadence. Status exposes the configured primary/fallback,
active source and age, each source's availability, and fallback/fail-safe use.
If neither source is usable, freeze protection latches LOW as a fail-safe (or
keeps its already latched speed) and cannot clear until a trustworthy warm
reading satisfies the normal hysteresis and minimum-run rules. The existing
notification service can repeat a throttled Pushover warning for this condition.

## Dashboard Pages

The web dashboard is branded **PoolScope**. Internal Python packages, console
commands, configuration keys, and systemd services retain the `poolctl` name.
Live, History, Schedule, and Settings share the same responsive product header,
configured pool name, controller/safety indicators, active schedule, pump mode,
and navigation.

- Live: responsive consumer-style operating dashboard with controller/safety,
  active-profile, and pump-mode status in the header; the controller-resolved
  Schedule timeline above six primary KPI cards for water temperature, pH, ORP,
  estimated flow, filter flow loss, and usable chlorine inventory; aligned
  seven-day trend strips for water temperature, pH, ORP, and tested free
  chlorine; collapsible chemical-addition, tank-refill, chlorination, and
  complete water-test entry panels; a collapsed equipment Controls panel for
  pump, booster, and active-profile commands; and an exception-first attention
  list. Historical KPI values use the compact `Last reading HH:MM ago` label;
  known sensor faults remain identified separately. Tank refills record the
  amount added separately from the resulting estimated tank level, validate
  against the optional configured capacity, and use an idempotency token to
  prevent a repeated browser submission. Supplemental chlorine
  requires a review/confirmation step before the existing command is sent.
  Detailed hydraulics, chlorination/FC-demand, CPU, health, and runtime-loop
  information remains available in the collapsed engineering status section.
- History: a viewing-only measurement/weather/test-result/chemical-addition
  workspace with selectable series grouped into collapsible Chemistry, Manual
  tests, Pump and hydraulics, Weather, and System diagnostics categories;
  hover readouts, automatic rollup resolution, past-window navigation,
  calendar/time jump, CSV export, and single-axis or multi-axis scaling
  depending on selected signal ranges. Selected series remain named in a
  collapsed category summary. Raw supported diagnostics remain available, but
  the obsolete analog pH-voltage selector is not offered. Existing historical
  data is not deleted. Operational water-test and chemical-addition entry stays
  on Live, with tank refill entry under Live -> Chemicals.
- Schedule: profile selection and editing, fixed/solar/daylight timing, a
  four-mode operating selector, and a three-day resolved preview. Profile
  activation remains on Live. The editor loads saved configuration once instead
  of replacing in-progress edits during status polling; **Reload Saved**
  explicitly discards a draft after confirmation.
- Settings: collapsible consumer-oriented tiles for Pool & Site, Status Ranges,
  Chlorination, Free Chlorine Control, Filter & Flow, Notifications, Display &
  Dashboard, Safety & Freeze, Sensors & Calibration, Acquisition & Logging, and
  Hardware & Runtime.

Some config changes apply live. Others write YAML and require restart because
drivers or long-lived services must be rebuilt.

The Live page continues to poll `GET /api/live` for current state and commands
the existing timer, actuator, profile, chlorination-config, and supplemental-dose
endpoints; the browser does not bypass controller safety routing. The existing
`GET /api/history` API supplies validated data for the configured chart windows.
Defaults are 24 hours for Flow, 30 days for Filter Loss, and 7 days for Chlorine
Supply. The selected window is printed beside each chart's x-axis, and useful
date/time ticks remain visible. The Flow card integrates its logged GPM samples
over its selected window. The Filter card compares the oldest and newest valid
samples in its selected window and labels the result as a percentage-point
change; it reports insufficient history instead of inventing a baseline. The
Chlorine Supply card charts usable gallons (estimated tank level minus the
configured forecast reserve) and summarizes exactly seven days of logged
dosing delivery in US gallons, converting stored fluid ounces at 128 fl oz per
US gallon. No separate UI storage is used for these summaries. Fixed y-axis
bounds show a clipping warning if actual values lie outside the configured
range. Chemical-addition event markers remain available on the aligned strips,
and configured pH/ORP alert ranges from `GET /api/config/monitoring` provide
subtle chart bands. The Schedule
timeline uses `schedule.today` from the live payload, including already-resolved
windows and sunrise/sunset, rather than reimplementing schedule or astronomy
calculations in JavaScript. The payload also includes the controller-resolved
valid dosing intervals after the configured no-dose lead-in and final
circulation periods. The timeline displays those intervals as full-height green
bars over the blue low-speed windows, with their narrower horizontal span
leaving the non-dosing circulation visible at each end. Booster/vacuum windows
are purple, and high-speed circulation is dark blue.

## History and Rollups

The logger stores raw measurement rows and maintains 1-minute, 1-hour, and
1-day rollups for continuous measurements. The History page requests `auto`
resolution based on the selected window length:

- Up to 48 hours: raw logged points.
- More than 48 hours through 14 days: 1-minute rollups.
- More than 14 days through 90 days: 1-hour rollups.
- More than 90 days: 1-day rollups.

Selecting `Raw + validated` disables rollups and shows raw logged rows for the
selected range. The chart uses one y-axis when selected traces have similar
ranges and centers; otherwise it gives traces separate color-matched axes.
Lab tests and chemical additions are plotted as point/event series rather than
continuous sensor streams.

For `FC (tested)` only, the history API also returns the most recent valid real
test before the requested start as context. When a valid first test exists
inside the window and neither record declares an intentional/invalid gap, the
browser interpolates the line to the left chart boundary and clips it there.
Only real tests receive markers and tooltips. The boundary value is never saved
or used by FC control, and no line is extrapolated without the supporting pair.

Most physical sensors are already logged at their acquisition group's
`log_interval_s`. Some controller-state values, such as `Dosing duty cycle` and
`Daily chlorine delivered`, are produced every runtime tick for live status but
are persisted using `logging.control_measurement_interval_s` plus immediate
samples when the dosing state or duty plan changes. Completed chlorine delivery
is stored as one event row per completed dosing segment. The cumulative
daily-delivered graph logs boundary snapshots for each normal dose: the current
total at the start of the dosing segment, then the new total after the completed
segment is recorded. It also logs a zero-value reset at each local midnight.
That gives history charts flat lines between pulses and a slope only during the
actual dosing runtime, with a visible reset before the first dose of the day.
Daily water/weather/chemical summary generation and daily moving-average rows
are checked hourly. These rules keep long history windows useful with the
0.25 s control loop instead of filling the database with duplicate-style status
rows.

The range selector controls the window length, not necessarily how far back the
database query can go. Use `Prev` and `Next` to move that same high-resolution
window through history, or set the `Ending` date/time and press `Jump` to view a
specific past day. `Now` returns the chart to the live rolling window. CSV export
uses the same selected window shown on the chart.

SQLite databases include an explicit schema version marker in both
`PRAGMA user_version` and a `schema_metadata` row. Current schema version is
`2`; existing additive column checks are still retained for compatibility with
older local databases.

The database also stores one resolved schedule snapshot per local date, profile,
and config digest. Snapshots include the site inputs, sunrise/sunset, resolved
windows, warnings, and whether resolution followed startup, a config/profile
change, or a day rollover. `GET /api/schedule/history` exposes this audit trail;
`GET /api/schedule/preview?days=3` returns current/future resolution without
changing outputs, and `POST /api/schedule/active_profile` switches profiles.

Water-test and chemical-addition entry times use local date/time pickers. Leaving
the time blank records the event at the controller's current time. A selected
browser-local time is converted to an offset-aware timestamp before logging; API
payloads that provide a timestamp without an offset are interpreted in the
configured pump-timer timezone.

## Open-loop Chlorination

Liquid chlorine dosing is implemented by the chlorination controller. On
Raspberry Pi hardware, the chlorine dosing pump is mapped to relay 7 by
default.

On the Waveshare Modbus relay module, normal pump and booster outputs use
latched relay writes. The chlorine dosing relay uses the module's flash-on
command by default. Each normal or diagnostic dosing ON segment is sent with the
remaining intended ON time in 100 ms relay-module units. The module then turns
the relay off by itself. Software still sends a normal OFF command when dosing is
cancelled early by safety, the dashboard stop button, or another explicit state
change. Poolctl also sends a redundant OFF confirmation after an expected
flash-pulse auto-off. That confirmation is not used for timing accuracy; it is a
secondary check after the module-timed pulse should already be off.

All dosing pulse commands are quantized to the relay module's 100 ms timing
resolution before they are sent and before delivery accounting records runtime.
This keeps duty-cycle math, expected auto-off timestamps, and logged chlorine
delivery aligned with the hardware timer.

This is a safety improvement over a latched dosing ON write: if the Pi process
crashes during a 30-60 second dosing pulse, the relay module should finish that
pulse and release the relay rather than leaving the pump on indefinitely. It is
not a substitute for a hardware watchdog, flow switch, or upstream fail-open
enable relay because relay contacts or firmware can still fail.

The controller:

1. Uses the same persisted/cached resolved windows as pump control.
2. Treats `allow_dosing: true` as a grant and excludes any segment where the
   effective overlapping schedule energizes the booster.
3. Merges overlapping or adjacent eligible windows while applying first/last
   no-dose buffers relative to continuous pump circulation.

Hard safety lockout remains the highest output authority. Freeze circulation
then takes priority over supplemental-dose, manual, sampling, and profile
outputs. When a schedule/profile transition would turn circulation off or turn
the booster on while chlorine is running, poolctl accounts for the elapsed dose
and commands chlorine OFF before issuing the timer transition.
3. Removes the first `no_dose_first_minutes` from each continuous pump run so
   pump output pressure and flow can stabilize.
4. Removes the final `no_dose_last_minutes` before the end of the full
   continuous pump run, not before each dosing-eligible sub-window.
5. Computes total valid daily dosing minutes.
6. Converts `daily_dose_oz` to dosing pump minutes using
   `pump_output_oz_per_min`.
7. Computes duty cycle as requested minutes divided by available minutes.
8. Caps duty cycle at `max_duty_cycle`.
9. Computes an effective ON/OFF pulse schedule for that duty cycle.

Normal scheduled dosing will only energize the dosing pump when the main pump
has continuously run for `no_dose_first_minutes`, the booster pump is off, the
latest good pump-output pressure is inside the configured chlorine dosing
pressure window, and SafetyGate allows the estimated true chlorine tank level.
Tank safety uses hysteresis: the dashboard warns at `low_warning_gal` (default
2.0 gal), normal dosing is inhibited at or below `inhibit_below_gal` (default
1.5 gal), and dosing is not re-enabled until the estimate reaches
`reenable_at_gal` (default 2.0 gal). The Pi profile defaults the pressure
window to 3.0-3.5 psi so the interlock verifies the pump is actually running at
the expected low-speed head pressure instead of trusting only the commanded
speed bit. A missing pressure or tank estimate is treated as not eligible for
normal dosing. Diagnostic prime/calibration runs remain a separate explicit
bypass path and do not count toward delivered chlorine totals.

This allows the same pump timer to run the pool at night for skimming or
vacuuming while keeping the day's chlorine dose in morning and daytime windows
before evening FC tests.

An adjacent `allow_dosing: false` window still provides circulation. For
example, if dosing is allowed through 14:00 and the pump continues through
15:00 with dosing disabled, a 10-minute final exclusion does not also remove
13:50-14:00; the circulation run itself ends at 15:00.

Pulse timing is configured with three values:

- `cycle_on_seconds`: nominal ON pulse used at normal duty cycles.
- `max_cycle_period_seconds`: longest desired full ON+OFF cycle before the
  controller starts shortening the ON pulse.
- `min_cycle_on_seconds`: shortest reliable ON pulse. If the requested duty
  cycle is so low that `duty_cycle * max_cycle_period_seconds` is below this
  value, the controller keeps the minimum ON pulse and allows the cycle period
  to grow again so total dose remains accurate.

With the default `cycle_on_seconds: 60.0` and
`max_cycle_period_seconds: 1800.0`, the controller uses 60-second ON pulses down
to about 3.33% duty cycle. Below that, it uses a 30-minute cycle and reduces ON
time. At extremely low duty cycle, it preserves the configured minimum ON time
instead of commanding unreliable tiny pulses.

Changing `daily_dose_oz` from the dashboard applies the new duty cycle going
forward. The controller does not try to make up for earlier parts of the day.
When a chlorine tank level test has been entered, the dashboard estimates
remaining tank gallons from that baseline minus logged dosing delivery plus any
recorded tank refills. This estimator is the authoritative inventory source for
the supply tile, refill workflow, alerts, and chlorine interlock; there is no
analog tank-sensor selection in this workflow. Tank level tests, refills,
`low_warning_gal`, `inhibit_below_gal`, `reenable_at_gal`, optional
`capacity_gal`, and `forecast_reserve_gal` are all US gallons. A legacy
`level_sensor` key remains readable but is ignored and is removed on the next
Safety settings save. Unknown/uninitialized inventory fails the dosing
interlock closed instead of fabricating a sensor value or disabling protection.

Supply forecasting separately subtracts `forecast_reserve_gal` (2 gallons by
default) to calculate usable gallons and estimated days remaining; that
forecast reserve is not the dosing inhibit threshold. The top status strip
displays `Usable chlorine remaining X gallons, Y days`, where usable gallons
subtract the reserve from the true estimated level. Days are computed from the
FC-demand maintenance dose when one is available; otherwise they use the
current chlorination daily dose. Their normal/caution/alarm colors use the
day-valued canonical `monitoring.limits.chlorine_tank_days_remaining`
boundaries. Gallon interlocks and day-based forecast alerts are deliberately
independent and explicitly labeled. If consumption is zero or unavailable,
the UI says the days estimate is unavailable rather than presenting a
misleading value. If tank capacity has not yet been configured, refill entry is
allowed with a warning so existing installations retain their workflow; after
capacity is set, a refill that would put the estimate above capacity is
rejected.
The Chlorination Settings card has diagnostic dosing-pump buttons:

- `Prime Dosing Pump 30s`: runs the dosing pump continuously for 30 seconds.
- `Calibrate Dosing Pump 20m`: runs the dosing pump at 50% duty cycle for 20
  minutes, using 60 seconds ON and 60 seconds OFF. Put the delivery line in a
  graduated cylinder, then manually compute and update `pump_output_oz_per_min`.
- `Stop Dosing Test`: stops either diagnostic run early.

These diagnostic commands bypass the normal chlorinator interlock so they can be
used with the filter pump off and the dosing line disconnected. Diagnostic
runtime is excluded from logged chlorine delivery, daily chlorine totals, and
FC-demand estimator addition math. The bypass is intentionally narrow; hard
safety faults such as overpressure still remain part of the runtime safety
loop.

The Live page Quick Controls also has an `Add Chlorine` action for a one-time
supplemental sodium-hypochlorite dose. Enter the extra fluid ounces to add; the
runtime forces the filter pump on at low speed, keeps the booster off, doses at
the configured `max_duty_cycle`, then keeps the pump running for
`no_dose_last_minutes` after the final dosing pulse. Supplemental dosing uses
the same pump-output-pressure/booster-off/tank safety inhibit/re-enable
interlocks as scheduled
normal dosing. This is normal pool dosing, not a diagnostic run: it does not
bypass safety, and delivered runtime is included in logged chlorine delivery,
daily sodium-hypochlorite totals, and FC-demand addition math.
Supplemental dose planning distributes total dosing runtime into equal pulses
instead of leaving a short final remainder; for example, a 70-second dosing
runtime with `cycle_on_seconds: 60.0` becomes two 35-second pulses. Because this
is a one-shot operator action rather than a low-duty-cycle all-day schedule, it
may use a pulse shorter than `min_cycle_on_seconds`; the relay pulse is still
quantized to 100 ms and the quantized runtime is what gets logged. If a
supplemental dose overlaps a normal scheduled pump run or dosing pulse, the
supplemental run temporarily owns the pump at low speed, records any already
delivered scheduled chlorine up to the handoff, and then resumes the schedule
after post-dose circulation completes. `Stop Extra Dose` cancels the remaining
supplemental run and logs any partial chlorine already injected.

Supplemental status calls pulse time `committed_runtime_s` as soon as a timed
hardware pulse is accepted and uses `estimated_completion_at` for its nominal
completion prediction. Actual delivered runtime remains the elapsed/applied
actuator accounting recorded by the chlorine delivery logger.

The History page can graph chlorination control signals:

- `Daily chlorine delivered`: cumulative fluid ounces delivered since local
  midnight using the configured pump timer timezone. This is a graph snapshot of
  the persistent chlorine delivery event table, not the source of dose
  accounting. Normal dosing logs one snapshot at segment start with the current
  total and one at segment end with the updated total. A zero-value reset
  snapshot is logged at local midnight.
- `Dosing duty cycle`: the current duty cycle during valid dosing time. This is
  logged across the full eligible window, including duty-cycle OFF portions.
  Like daily delivered chlorine, it uses
  `logging.control_measurement_interval_s` plus immediate samples on dosing
  state/duty-plan changes.
- `Daily sodium hypochlorite added`: completed-day total fluid ounces from
  automated dosing plus manually logged sodium hypochlorite additions. Metadata
  keeps the automated/manual split and the FC-ppm equivalent.
- `Daily muriatic acid added`: completed-day total fluid ounces from manually
  logged muriatic acid additions.
- `Sodium hypochlorite 7d/28d avg` and `Muriatic acid 7d/28d avg`: moving
  averages of the completed-day chemical totals. Early history uses the
  available completed-day rows until a full window has accumulated.
- `FC demand`: estimated free-chlorine consumption in ppm/day from the latest
  valid consecutive FC-test observation, logged once per distinct observation.
- `Base FC demand`: recent weighted maintenance-demand estimate from the latest
  usable observations. This is the Phase 1 feed-forward demand estimate.
- `FC demand weather adjustment`: Phase 1 weather modifier in ppm/day. It is
  intentionally logged as `0.0` today so Phase 2 can add forecast weather and
  water-temperature effects without changing the learned baseline field.
- `Predicted FC demand` and `FC demand residual`: final predicted demand
  (`baseline + weather adjustment`) and actual-minus-predicted error. Phase 1
  uses only the weighted FC-test/addition history, with no pH, ORP, UV, weather,
  or temperature modifier.
- `Daily ORP avg`, `Daily water temp min/avg/max`, and `Daily pH avg`: daily
  summaries from `raw_orp`, canonical `water_temp`, and `raw_ph`. Canonical
  water temperature uses fresh `ph_temp` with `orp_temp` fallback. The minimum
  is logged because it may better represent pool water than daytime plumbing
  warmed by sun.
- `ORP 7d/28d avg`, `Water temp 7d/28d avg`, `pH 7d/28d avg`, and
  `UV dose 7d/28d avg`: moving averages of the completed-day summary rows for
  seasonal demand tracking.
- `Daily UV dose` and `Daily shortwave dose`: previous-day sums from the
  Open-Meteo hourly weather history, for later correlation with FC demand.

Example:

```yaml
runtime:
  driver_profile: raspberry_pi
  enabled_actuators:
  - pump_motor
  - pump_motor_speed
  - booster_pump
  - chlorine_dosing_pump
  enabled_sensor_groups:
  - pressures
  - chemistry_loop
  - chemical_tank

pool:
  name: Home Pool
  volume_gal: 10000.0

modbus_relay:
  dosing_uses_flash: true
  startup_safe_off: true
  reconciliation_interval_s: 30.0
  relays:
    chlorine_dosing_pump: 7

chlorination:
  enabled: true
  daily_dose_oz: 0.0
  pump_output_oz_per_min: 1.0
  chlorine_strength_percent: 12.0
  no_dose_first_minutes: 1.0
  no_dose_last_minutes: 10.0
  max_duty_cycle: 0.5
  cycle_on_seconds: 60.0
  max_cycle_period_seconds: 1800.0
  min_cycle_on_seconds: 5.0

fc_demand:
  enabled: true
  mode: observe_only
  target_fc_ppm: 4.0
  minimum_test_interval_hours: 12.0
  max_observation_interval_days: 7.0
  preferred_test_start_hour: 18
  preferred_test_end_hour: 24
  negative_demand_noise_tolerance_ppm_per_day: 0.05
  recent_observation_count: 5
  observation_weights:
  - 0.35
  - 0.25
  - 0.18
  - 0.13
  - 0.09
  fc_feedback_gain: 0.6
  max_maintenance_change_percent: 15.0
  max_daily_dose_oz: 256.0
```

All normal dosing ON commands pass through SafetyGate. Normal dosing uses the
configured pump-output pressure window for head-pressure qualification:

```yaml
safety:
  freeze_protection:
    enabled: true
    primary_temperature_sensor: ph_temp
    fallback_temperature_sensor: orp_temp
    max_temperature_age_seconds: 3600
  chlorine_tank:
    capacity_gal: null
    low_warning_gal: 2.0
    inhibit_below_gal: 1.5
    reenable_at_gal: 2.0
  thresholds:
    chlorine_min_pump_output_psi: 3.0
    chlorine_max_pump_output_psi: 3.5
    pump_prime_min_output_psi: 1.0
    pump_output_overpressure_psi: 30.0
  timeouts:
    pump_output_max_age_seconds: 10.0
    pump_prime_timeout_s: 30.0
```

## Filter Loading

Filter loading is a standardized hydraulic proxy based only on
`pump_output_psi`. It assumes the valve positions are repeatable, the main pump
HIGH state is repeatable, and the booster is OFF. It is not a direct filter
differential-pressure measurement.

Software does not schedule a special test. Create a normal 5-10 minute pump
HIGH, booster-OFF schedule window, or run the same condition manually. When the
system enters main pump ON, speed HIGH, booster OFF, with a fresh GOOD
`pump_output_psi` measurement, the estimator starts a qualifying session. It
ignores the first `filter_loading.stabilization_seconds` (default 60 s), then
collects distinct source pressure observations until their timestamps cover
`averaging_seconds` (default 120 s). Repeated controller ticks holding the same
measurement do not increase `sample_count` or complete a test early. If the
pump stops, leaves HIGH, the booster turns
ON, or pressure becomes stale/bad/unavailable, the in-progress session resets
and samples are not mixed across sessions.

On completion, the averaged standardized PSI is converted to HIGH-speed flow
using the same shared pressure-to-flow hydraulic model used for live flow
estimation. The result remains latched until the next valid standardized test,
even when the pump later drops to LOW/OFF. The authoritative standardized
reference-pressure result is logged in SQLite and restored at controller
startup; flow and loss are recalculated from it using the current hydraulic
model and clean-flow calibration, so a service restart does not blank the Live
KPI.

The only clean-filter calibration is:

```yaml
filter_loading:
  clean_flow_gpm: null
```

After cleaning the filter, run the standardized HIGH/booster-OFF period and use
the completed estimated flow as `clean_flow_gpm` (`Qclean`). Until this value is
entered, tests still complete and show reference PSI, estimated current flow,
timestamp, age, and sample count, but flow loss is unavailable and status is
`unknown`.

When calibrated:

```text
raw flow loss % = 100 * (1 - Qcurrent / Qclean)
```

The raw value is preserved, including small negative values from normal
variation. Dashboard display clamps flow loss to 0-100%. Status is computed in
the shared monitoring service from
`monitoring.limits.filter_flow_loss_percent`: values at or above
`caution_above` are caution, and values at or above `alarm_above` are alarm.
The Filter & Flow card displays those values read-only and links to Status
Ranges for editing.

Completed tests log:

- `filter_reference_psi`: standardized pump discharge pressure.
- `filter_reference_flow_gpm`: standardized estimated HIGH-speed flow.
- `filter_flow_loss_percent`: raw flow loss when `clean_flow_gpm` is calibrated.

There is no dirty-PSI calibration.

On Raspberry Pi profiles, `startup_safe_off` defaults to `true` and
`reconciliation_interval_s` defaults to `30.0`. Startup safe-off uses safe
domain actuator states: dosing OFF, booster OFF, pump motor OFF, and pump speed
LOW. With the current wiring, pump speed LOW energizes relay 2; this is safer
than forcing every physical relay de-energized because an unexpected pump start
would then be low speed instead of high speed. Periodic reconciliation runs
after the time-critical control decisions in a tick. It reads relay state and
sends corrective commands when the physical relay state does not match the
controller's desired state.

## FC-Demand Estimator

`fc_demand` is a discrete daily adaptive feed-forward controller for the
open-loop chlorination target. It learns a maintenance dose from reference
manual DPD FC tests plus logged chlorine additions/delivery, then optionally
adds a one-day signed FC target correction. It deliberately does not use ORP,
pH, weather, UV, air temperature, or water temperature as control inputs in
Phase 1. Those signals are still logged for later analysis.

The low-level `ChlorinationController` remains responsible only for delivering
an ounces-per-day target through eligible dosing windows, duty-cycle timing,
relay flash pulses, safety checks, and delivery logging. FC-demand automatic
mode passes a `ChlorinationPlanAdjustment`; it does not command relays directly.

Manual DPD tests are normalized inside the FC-demand service as high-confidence
FC observations with `source = manual_dpd`. Future lower-confidence or frequent
sources such as WaterGuru or an inline FC sensor can be mapped into the same
observation boundary, but they are not active integrations today.

The controller classifies normalized FC observations using the configured local
control timezone:

- Reference/control test: local sample time is in
  `[preferred_test_start_hour, preferred_test_end_hour)`. Defaults are
  `18:00 <= sample < 24:00`. Reference tests drive maintenance learning and
  one-time next-control-day target feedback.
- Ad-hoc test: local sample time is outside that window. Ad-hoc tests are stored
  and shown in history/status, but Phase 1 treats them as analysis-only. They do
  not displace the recent reference observations and do not trigger normal
  next-day FC feedback. Phase 2 can use them for within-day demand and
  weather/solar modeling.

The controller builds demand observations from consecutive valid reference
free-chlorine tests. For each adjacent reference pair:

- Ignore pairs closer than `minimum_test_interval_hours`.
- Ignore pairs longer than `max_observation_interval_days` (default 7 days).
- Allow missed-test intervals inside that maximum; a 2-7 day gap becomes one
  average ppm/day observation.
- Sum automated dosing pump delivery logged by the runtime loop.
- Sum manually logged sodium-hypochlorite additions.

Diagnostic prime/calibration dosing remains excluded because it is not logged as
normal chlorine delivery. Supplemental `Add Chlorine` doses are normal pool
dosing, so their delivered ounces are included.

Liquid chlorine ounces are converted to FC ppm using:

```text
FC ppm = (fluid ounces / 128) * strength_percent * (10000 / pool_volume_gal)
```

Then it estimates:

```text
consumed FC ppm = previous FC + added FC - current FC
raw demand ppm/day = consumed FC ppm / elapsed days
```

Clearly positive observations are valid. Tiny negative observations within
`negative_demand_noise_tolerance_ppm_per_day` default to a suspect zero-demand
observation so measurement noise is visible in status/history. Materially
negative observations are rejected and excluded from maintenance learning; their
raw value, quality, and rejection reason remain visible in status/debug payloads.

The maintenance demand estimate uses the most recent
`recent_observation_count` accepted observations, default 5. The default
newest-to-oldest weights are `[0.35, 0.25, 0.18, 0.13, 0.09]`. If fewer
observations are available, the leading weights are renormalized. For example,
with two observations the effective weights are `0.35 / (0.35 + 0.25)` and
`0.25 / (0.35 + 0.25)`.

The weighted maintenance demand is the Phase 1
`baseline_demand_ppm_per_day`. The Phase 1
`weather_adjustment_ppm_per_day` is always exactly `0.0`, and
`predicted_demand_ppm_per_day = baseline_demand_ppm_per_day`. This intentionally
keeps weather, UV, air temperature, and water temperature out of the control law
today while preserving a clean Phase 2 hook for forecast modifiers.

The predicted demand is converted to fluid ounces/day using the same pool-volume
and chlorine-strength math. The learned maintenance dose is rate limited by
`max_maintenance_change_percent` (default 15%) from the previously computed
learned target, reconstructed deterministically from FC-test and addition
history. Status also reports the rate-limited baseline equivalent in ppm/day.
`max_daily_dose_oz` is still the final hard cap.

FC target feedback is symmetric and applies only once. When the latest
reference FC test is new, the next local control day applies:

```text
feedback FC ppm = fc_feedback_gain * (target_fc_ppm - latest FC ppm)
recommended dose = maintenance dose + feedback dose
```

The default `fc_feedback_gain` is `0.6`. Positive feedback raises the next-day
dose when FC is below target; negative feedback lowers it when FC is above
target. The final recommendation is clamped to `0 <= dose <= max_daily_dose_oz`.
After that one control day, feedback is no longer applied. If FC tests are
missed for several days, the controller continues the learned open-loop
maintenance dose only.

`mode` controls whether the estimate is applied:

- `observe_only`: calculate and display status only.
- `recommend`: calculate recommendations without applying them.
- `approve_required`: reserved for a future approval workflow.
- `automatic`: pass the effective daily dose into the chlorination controller.

The live status/API reports the latest FC value/time regardless of source or
timing, latest reference FC value/time, whether the latest observation is
reference or ad-hoc, current preferred test window, target FC, latest observed
demand, baseline demand, rate-limited baseline demand, weather adjustment,
predicted demand, maintenance dose, feedback ppm/oz, whether feedback is active
today, recommended/effective dose, observation count, learning confidence, mode,
and capping/rate-limit warnings. Confidence is based on usable reference
observation count: `learning` for fewer than 2, `low` for 2, `medium` for 3-4,
and `high` for 5 or more.

Weather, UV, ORP, pH, and water-temperature summaries continue to be logged for
Phase 2 analysis. The current `Predicted FC demand` history signal means
`baseline + weather_adjustment`, and the Phase 1 weather adjustment is exactly
zero. Phase 2 will evaluate correlations between observed FC demand,
ad-hoc/daytime FC tests, weather, solar radiation, and water-temperature history
before adding modifiers to the control law.

## Pushover Notifications

Notifications are provider-based. The first provider is Pushover. The service
uses Pushover's standard HTTPS message API and sends `token`, `user`, `title`,
`message`, and `priority` form fields to:

```text
https://api.pushover.net/1/messages.json
```

Pushover setup:

1. Create a Pushover account and install the mobile app.
2. Create a Pushover application/API token from your Pushover dashboard.
3. Copy your Pushover user key.
4. Enter the app token and user key on the Settings page, or put them on the Pi
   in `/etc/poolctl/poolctl.env`.
5. Enable notifications on the Settings page or in YAML.
6. Press `Send Test` on the Settings page.

`pi-prod.yaml` stores only the names of the environment variables by default,
but the Settings page can save direct keys to the active writable config:

```yaml
notifications:
  enabled: true
  provider: pushover
  default_title: PoolScope
  pushover:
    app_token: null
    user_key: null
    app_token_env: PUSHOVER_APP_TOKEN
    user_key_env: PUSHOVER_USER_KEY
    api_url: https://api.pushover.net/1/messages.json
    timeout_s: 5.0
    priority: 0
    sound: null
  rules:
    chlorine_tank_days_remaining:
      enabled: true
      notify_caution: true
      notify_alarm: true
      caution_repeat_minutes: 1440.0
      alarm_repeat_minutes: 240.0
    raw_ph:
      enabled: true
      notify_caution: true
      notify_alarm: true
      caution_repeat_minutes: 1440.0
      alarm_repeat_minutes: 240.0
    raw_orp:
      enabled: true
      notify_caution: true
      notify_alarm: true
      caution_repeat_minutes: 1440.0
      alarm_repeat_minutes: 240.0
    filter_flow_loss_percent:
      enabled: false
      notify_caution: false
      notify_alarm: true
      caution_repeat_minutes: 1440.0
      alarm_repeat_minutes: 1440.0
    freeze_temperature_unavailable:
      enabled: true
      notify_caution: false
      notify_alarm: true
      caution_repeat_minutes: 1440.0
      alarm_repeat_minutes: 240.0
    freeze_protection_active:
      enabled: false
      notify_caution: false
      notify_alarm: true
      caution_repeat_minutes: 1440.0
      alarm_repeat_minutes: 240.0
    cpu_temperature_high:
      enabled: false
      notify_caution: false
      notify_alarm: true
      caution_repeat_minutes: 1440.0
      alarm_repeat_minutes: 240.0
      threshold_deg_c: 75.0
      hysteresis_deg_c: 5.0
      debounce_seconds: 60.0
```

Most rules are disabled by default even when the provider block exists in the
tracked configs. Rules choose whether caution and/or alarm states notify and
how often each level may repeat; they do not own numeric measurement
thresholds. Those values come from the matching `monitoring.limits` entry and
are shown read-only in Settings for context.

`chlorine_tank_days_remaining` uses usable days remaining, computed from the
estimated true tank gallons minus the forecast reserve and the maintenance
chlorine daily estimate when available. Filter notifications use the latest
standardized flow-loss test and include its age. A clean standardized test
clears the condition. The freeze-temperature-unavailable rule remains a
non-measurement alarm rule because it reports loss of all configured freeze
temperature sources.

`freeze_protection_active` is edge-triggered from SafetyGate's actual freeze
state. It sends once when protection changes from inactive to active, including
the selected temperature, units, source, and measurement timestamp when
available. If fail-safe activation has no valid temperature, the message states
that condition. `cpu_temperature_high` uses the acquired CPU temperature in
degrees Celsius and requires the configured debounce period above
`threshold_deg_c`; it clears only below `threshold_deg_c - hysteresis_deg_c`.
Missing or stale CPU telemetry does not create a high-temperature event.
Notification edge, debounce, and last-send state is stored in SQLite so a
controller restart does not repeat an unchanged activation. These notification
rules never change freeze protection or any other control decision.

Alarm boundaries are evaluated before caution boundaries. Each rule has a
separate caution and alarm repeat interval; the throttle key is signal plus
status level, so a value that moves among ranges does not bypass the matching
cooldown. pH and ORP rules accept only fresh, GOOD readings after circulation
settling; pump-off, settling, stale, and failed readings neither create nor
repeat chemical threshold violations. The dashboard may continue to show the
last valid historical value, but it is never substituted for the current
notification input.

The Settings page has direct `Pushover app token` and `Pushover user key` fields
that round-trip like other config fields. Leave them blank to use
`app_token_env` and `user_key_env` instead.

On the Pi:

```bash
sudo install -d -m 0755 /etc/poolctl
sudo nano /etc/poolctl/poolctl.env
```

Add:

```bash
PUSHOVER_APP_TOKEN=your_app_token_here
PUSHOVER_USER_KEY=your_user_key_here
```

Then restart:

```bash
sudo systemctl restart poolctl.service
```

The systemd service reads `/etc/poolctl/poolctl.env` if it exists. Keep that
file out of Git.

## Raspberry Pi First Install

These commands assume:

- OS: Raspberry Pi OS 64-bit Bookworm
- Python: 3.11.2
- Pi username: `pool`
- Project directory: `/home/pool/projects/pool`
- Virtual environment: `/home/pool/projects/pool/venv`
- Config: `/home/pool/projects/pool/configs/pi-prod.yaml`

Install OS packages:

```bash
sudo apt update
sudo apt install -y git python3-venv python3-pip sqlite3
python3 --version
```

The version check should report Python 3.11.2.

Clone the repository:

```bash
mkdir -p ~/projects
cd ~/projects
git clone <repo-url> pool
cd ~/projects/pool
```

Create and populate the venv:

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[raspberrypi]"
python -m pip check
```

Install the services:

```bash
chmod +x deploy/systemd/install-pi-services.sh
APP_USER=pool \
APP_GROUP=pool \
PROJECT_DIR=/home/pool/projects/pool \
VENV_DIR=/home/pool/projects/pool/venv \
CONFIG_PATH=/home/pool/projects/pool/configs/pi-prod.yaml \
LOCAL_CONFIG_PATH=/home/pool/projects/pool/configs/pi-local.yaml \
WEB_HOST=0.0.0.0 \
WEB_PORT=8000 \
TICK_INTERVAL_S=0.25 \
BACKUP_DB_PATH=/home/pool/projects/pool/data/pi-prod.sqlite3 \
BACKUP_DIR=/var/backups/poolctl \
BACKUP_KEEP_COUNT=720 \
./deploy/systemd/install-pi-services.sh
```

Open the dashboard:

```text
http://<pi-ip-address>:8000
```

If you use a Cloudflare tunnel, point it at the local dashboard port on the Pi,
usually `http://127.0.0.1:8000`.

## Updating the Pi from Git

For a normal update:

```bash
cd /home/pool/projects/pool
git status --short
git pull --ff-only
source venv/bin/activate
python -m pip install -e ".[raspberrypi]"
sudo systemctl restart poolctl.service
```

If deployment scripts or service templates changed, rerun the installer:

```bash
cd /home/pool/projects/pool
APP_USER=pool \
APP_GROUP=pool \
PROJECT_DIR=/home/pool/projects/pool \
VENV_DIR=/home/pool/projects/pool/venv \
CONFIG_PATH=/home/pool/projects/pool/configs/pi-prod.yaml \
LOCAL_CONFIG_PATH=/home/pool/projects/pool/configs/pi-local.yaml \
WEB_HOST=0.0.0.0 \
WEB_PORT=8000 \
TICK_INTERVAL_S=0.25 \
BACKUP_DB_PATH=/home/pool/projects/pool/data/pi-prod.sqlite3 \
BACKUP_DIR=/var/backups/poolctl \
BACKUP_KEEP_COUNT=720 \
./deploy/systemd/install-pi-services.sh
```

For the KPI, threshold, tank-estimator, and notification update documented
above, preserve the live database and `configs/pi-local.yaml`. Make an external
backup, inspect local tracked-file edits before pulling, and use the normal
update path:

```bash
cd /home/pool/projects/pool
if [ -f configs/pi-local.yaml ]; then
  cp configs/pi-local.yaml ~/pi-local.yaml.pre-dashboard-update
fi
sqlite3 data/pi-prod.sqlite3 ".backup '$HOME/pi-prod.pre-dashboard-update.sqlite3'"
git status --short
git pull --ff-only
source venv/bin/activate
python -m pip install -e ".[raspberrypi]"
python -m pip check
sudo systemctl restart poolctl.service
sudo systemctl status poolctl.service --no-pager
```

No dependency, unit-template, or installer change is required for this update,
so do not rerun `install-pi-services.sh` solely for it. On first start the
SQLite schema adds the notification-state table in place; measurement, lab,
chemical-addition, calibration, and refill history remain intact. Config
normalization reads existing legacy threshold fields and the old tank
`level_sensor` field compatibly. The server continues to write Settings changes
to the local override and now reapplies the reloaded merged effective config,
so do not replace that override with the tracked example. After restart, verify
Status Ranges in Settings, optionally enter the physical tank capacity in US
gallons under Safety & Freeze, configure Display & Dashboard chart bounds, and
leave the new freeze-active and high-CPU notification rules disabled until the
desired behavior has been reviewed.

If `git status --short` shows site-specific edits in tracked
`configs/pi-prod.yaml`, copy those values to `configs/pi-local.yaml` before
restoring the tracked file and pulling. A local schedules list replaces the
entire tracked list. Do not use `git reset --hard`; it can destroy production
configuration.

## Raspberry Pi Services

`deploy/systemd/install-pi-services.sh` installs:

- `poolctl.service`: dashboard plus dedicated runtime loop.
- `poolctl-backup.service`: one-shot SQLite backup job.
- `poolctl-backup.timer`: hourly backup schedule.

The installer disables any previously installed obsolete `poolctl-ticker.service`
because the web server owns the dedicated runtime loop. The old ticker template
is no longer part of the source tree.

Useful commands:

```bash
sudo systemctl status poolctl.service
sudo systemctl restart poolctl.service
sudo systemctl stop poolctl.service
sudo systemctl start poolctl.service
journalctl -u poolctl.service -f
```

Backup commands:

```bash
sudo systemctl status poolctl-backup.timer
sudo systemctl start poolctl-backup.service
journalctl -u poolctl-backup.service -n 50
ls -lh /var/backups/poolctl
```

Backups are timestamped, compressed, and accompanied by SHA-256 files. The
backup script runs `PRAGMA quick_check` on the source database and
`PRAGMA integrity_check` on the backup before publishing it, so a failed backup
does not overwrite previous good backups.

## Modbus Bring-up

Current intended bus settings:

- Port: `/dev/ttyUSB0` unless changed in config.
- Baud: `4800`.
- Serial format: 8-N-1.
- ORP sensor address: `0x01`.
- Analog input module address: `0x02`.
- Relay module address: `0x03`.
- pH sensor address: `0x04`.

Stop `poolctl.service` before using Modbus tools so the serial port is free:

```bash
sudo systemctl stop poolctl.service
```

Configure a new relay module from factory defaults to address `0x03` at 4800:

```bash
source /home/pool/projects/pool/venv/bin/activate
python -m poolctl.tools.modbus_device_config \
  --port /dev/ttyUSB0 \
  --current-id 0x01 \
  --current-baudrate 9600 \
  --new-id 0x03 \
  --new-baudrate 4800 \
  --new-parity N
```

Configure a new analog input module from factory defaults to address `0x02` at
4800:

```bash
python -m poolctl.tools.modbus_device_config \
  --port /dev/ttyUSB0 \
  --current-id 0x01 \
  --current-baudrate 9600 \
  --new-id 0x02 \
  --new-baudrate 4800 \
  --new-parity N
```

Configure a new DFRobot SEN0708 pH sensor from factory defaults to address
`0x04` at 4800:

```bash
python -m poolctl.tools.dfrobot_device_config \
  --port /dev/ttyUSB0 \
  --current-id 0x01 \
  --current-baudrate 4800 \
  --new-id 0x04 \
  --new-baudrate 4800
```

Only one factory-default address module should be connected while changing
address/baud settings. This matters especially for the ORP and pH sensors,
because both DFRobot probes ship at address `0x01`.

The pH sensor produces:

- `raw_ph`: pH units from register `0x0000`.
- `ph_temp`: probe temperature from register `0x0001`, converted from C to F
  before display and logging.

The DFRobot ORP and pH drivers have a small circuit breaker so a missing or
failing chemistry probe does not repeatedly block the control loop with Modbus
timeouts. By default, two consecutive read failures open the breaker for 60
seconds. While open, acquisition records a fast failure and skips the Modbus
request for that probe. Pressure and analog input reads are not affected.

```yaml
modbus_orp_sensor:
  port: /dev/ttyUSB0
  slave_id: 1
  baudrate: 4800
  timeout_s: 1.0
  circuit_breaker:
    enabled: true
    failure_threshold: 2
    cooldown_s: 60
```

`pi-prod.yaml` enables the RS485 pH sensor and includes `raw_ph` and `ph_temp`
in the chemistry acquisition group:

```yaml
enable_modbus_ph_sensor: true
modbus_ph_sensor:
  port: /dev/ttyUSB0
  slave_id: 4
  baudrate: 4800
  timeout_s: 1.0
  circuit_breaker:
    enabled: true
    failure_threshold: 2
    cooldown_s: 60
acquisition:
  groups:
    chemistry_loop:
      sensor_ids:
      - raw_orp
      - orp_temp
      - raw_ph
      - ph_temp
```

The Sensors & Calibration Settings card has a pH sensor section. Turning the sensor on or off
writes `enable_modbus_ph_sensor` and also adds or removes `raw_ph` and
`ph_temp` from the Pi chemistry acquisition group. Restart the service after
changing this setting so hardware drivers are rebuilt.

Verify the pH sensor after changing its address:

```bash
python -m poolctl.tools.modbus_bringup \
  --port /dev/ttyUSB0 \
  --baudrate 4800 \
  --ph-slave-id 0x04
```

The same Settings card has low-point and high-point pH calibration buttons. Enter
the buffer pH value, then press the matching button while the probe is in that
buffer. The server writes DFRobot's two-register calibration command starting at
register `0x0120`, using `1` for the low point, `2` for the high point, and
`pH * 100` for the calibration value.

Set all analog channels to mode `0` for the non-B 0-5V board:

```bash
python -m poolctl.tools.modbus_analog_mode \
  --port /dev/ttyUSB0 \
  --slave-id 0x02 \
  --baudrate 4800 \
  --set-all 0
```

Scan the bus:

```bash
python -m poolctl.tools.modbus_bringup \
  --port /dev/ttyUSB0 \
  --baudrate 4800 \
  --scan \
  --scan-min-id 1 \
  --scan-max-id 8
```

Read relays and pulse relay 7:

```bash
python -m poolctl.tools.modbus_bringup \
  --port /dev/ttyUSB0 \
  --baudrate 4800 \
  --relay-slave-id 0x03 \
  --toggle-relay 7 \
  --toggle-seconds 2
```

Read analog channels:

```bash
python -m poolctl.tools.modbus_bringup \
  --port /dev/ttyUSB0 \
  --baudrate 4800 \
  --analog-slave-id 0x02 \
  --raw-to-volts-scale 0.001
```

The Waveshare analog input driver reads all 8 contiguous input registers in one
Modbus request, then maps configured channels to logical sensors locally. The
DFRobot pH and ORP drivers each read their two contiguous holding registers
with one request per probe.

Installed console entry points are also available after `pip install -e`:

```bash
poolctl-modbus-bringup --port /dev/ttyUSB0 --baudrate 4800 --scan
poolctl-modbus-device-config --port /dev/ttyUSB0 --current-id 0x01 --current-baudrate 9600 --new-id 0x03 --new-baudrate 4800
poolctl-dfrobot-device-config --port /dev/ttyUSB0 --current-id 0x01 --current-baudrate 4800 --new-id 0x04 --new-baudrate 4800
```

Restart the service after bring-up:

```bash
sudo systemctl start poolctl.service
```

## Running Simulated Mode on the Pi

The Pi can run the Windows-style simulated profile to test the dashboard or a
web tunnel without hardware:

```bash
cd /home/pool/projects/pool
source venv/bin/activate
python -m poolctl.web.server \
  --config configs/windows-dev.yaml \
  --host 0.0.0.0 \
  --port 8000 \
  --sim-speedup 60 \
  --tick-interval-s 0.25
```

Do not run this on the same port while `poolctl.service` is active.

The tracked Windows profile uses the generic `45.0, -90.0` location and
includes canonical examples of all four Schedule-page modes: morning Dosing,
a three-hour Low window ending at sunset, one hour of High beginning at sunset,
and a fixed-time Vacuum window. YAML continues to express those modes through
`pump_speed`, `booster`, and `allow_dosing`; it does not introduce a second
`mode` source of truth. This exercises offline solar resolution and makes the
sunrise, sunset, and solar-relative windows visible without local setup. Change
Pool & Site in Settings to preview the schedule for another location.

For signals shared with the Pi profile, the Windows profile intentionally uses
the same `monitoring.limits` and threshold-free `notifications.rules`.
Windows-only simulated sensors may add their own canonical monitoring entries.

The tracked Pi profile uses the same non-site-specific coordinates so it remains
complete and testable, but an actual installation should override them in
`configs/pi-local.yaml` before using solar-relative schedules or weather.

## Operational Notes

- Keep `data/` out of Git. The SQLite database is local operational state.
- `git pull` will not overwrite ignored database files such as
  `data/pi-prod.sqlite3`.
- Stop the service before manually using the RS485 port.
- If a Modbus port reports exclusive-lock errors, check for services such as
  `ModemManager` or any running `poolctl` process.
- The Settings page can update many values, but driver-level changes usually
  require a service restart.
- The default Pi `pi-prod.yaml` starts with chlorination enabled but
  `daily_dose_oz: 0.0`, so installing the update does not start dosing until a
  nonzero dose is entered.
