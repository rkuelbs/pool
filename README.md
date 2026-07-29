# poolctl

`poolctl` is a Python pool automation controller being built for a Raspberry Pi 5.
It is designed to be developed on Windows with simulated hardware and deployed
later to Raspberry Pi OS with Modbus sensors and relays.

The project is intentionally layered:

- Domain models define stable actuator, sensor, command, and measurement types.
- Drivers isolate simulated hardware, Modbus relay hardware, and Modbus sensors.
- Services implement acquisition, logging, timers, safety, flow estimation,
  chlorination, weather logging, MQTT, and derived chemistry metrics.
- The web server owns the live dashboard, history charts, config forms, and the
  dedicated runtime tick loop.

## Current Capabilities

- Windows simulation using a correlated simulated pool plant.
- Raspberry Pi Modbus relay control through a Waveshare 8-channel RTU relay.
- Raspberry Pi Modbus analog input support for pressure channels.
- DFRobot Modbus ORP and pH sensor support, including probe temperatures.
- Pump timer scheduling with manual dashboard overrides.
- Open-loop chlorine dosing on relay 7. On Raspberry Pi hardware, dosing ON
  pulses use the Waveshare relay module's timed flash command by default so the
  module turns the relay off even if the Pi process dies mid-pulse.
- Optional FC-demand estimator based on manual FC tests and logged chlorine
  delivery/additions. ORP and pH are not used by this estimator.
- Safety enforcement layer with configurable pressure gates and lockouts.
- Freeze protection with hysteresis and minimum runtime.
- Sensor acquisition with per-group read/log rates, optional burst
  oversampling, and rolling boxcar filters.
- SQLite logging for measurements, weather, test results, and chemical additions.
- Live web GUI, mobile-friendly live list view, config forms, schedule editor,
  test result entry, chemical addition entry, and history charts.
- Raspberry Pi CPU temperature, CPU load, and CPU fan RPM live display and
  logging.
- Hourly Open-Meteo weather observation logging plus a 48-hour in-memory forecast.
- MQTT telemetry and selected input support when enabled.
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
  config.py               Runtime stage, layer, and live view config models.
  domain/models.py        Stable domain identifiers and data models.
  drivers/                Simulated and Raspberry Pi hardware drivers.
  services/               Acquisition, timer, safety, logging, weather, etc.
  tools/                  Modbus bring-up and configuration helpers.
  web/                    HTTP server and static dashboard assets.
tests/                    Unit and integration-style tests.
```

## Python Versions

The project supports Python `>=3.11,<3.14`.

- Windows development has been run with Python 3.13.
- Raspberry Pi OS Bookworm currently commonly ships Python 3.11.2, which is
  supported by the codebase.

## Windows Development Setup

From a PowerShell terminal in the repo root:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,mqtt]"
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
`pump_timer.schedules` list replaces the tracked schedule list as a whole.

Use this local file for values that change on the actual pool:

- pump timer schedules
- `allow_dosing` choices per schedule window
- daily chlorine dose
- dosing pump calibration rate
- FC-demand target, pool volume, and operating mode
- site-specific paths or hardware settings if they differ from the tracked base

`configs/pi-local.yaml` is ignored by git. `configs/pi-local.example.yaml` is a
tracked template you can copy on the Pi:

```bash
cp configs/pi-local.example.yaml configs/pi-local.yaml
```

The dashboard Config and Schedule forms save to the local override when the
server is started with `--local-config`. This lets `git pull` update
`configs/pi-prod.yaml` without conflicting with daily schedule and dosing edits
made on the Pi.

Important sections:

- `runtime`: stage, driver profile, enabled feature layers, enabled actuators,
  enabled sensor groups.
- `pump_timer`: local timezone, daily pump/booster schedule windows, and whether
  each window is eligible for chlorine dosing.
- `chlorination`: open-loop liquid chlorine dose settings.
- `fc_demand`: optional free-chlorine demand estimator settings.
- `safety`: pressure interlocks, lockout thresholds, freeze protection.
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
- `flow_estimation`: pump/branch flow constants and filter restriction limits.
- `live_view`: dashboard display limits.
- `weather`: Open-Meteo location, units, and polling settings.
- `mqtt`: MQTT connection, topics, and permission switches.
- `notifications`: push notification provider settings. Pushover secrets should
  live in environment variables, not YAML.

Schedule `start` and `end` values should be quoted strings:

```yaml
pump_timer:
  timezone: America/Chicago
  schedules:
  - name: morning_filter
    start: '08:00'
    end: '12:00'
    pump_speed: low
    booster: 'off'
    allow_dosing: true
```

`allow_dosing` defaults to `true` for older config files. Set it to `false` on
night, vacuum, or skimming-only windows where the pump should run but chlorine
should not be injected.

## Feature Layers

Feature layers let the same software move through staged hardware bring-up:

- `pump_timer`: controls pump motor, pump speed, and booster from schedules.
- `acquisition`: reads configured sensors.
- `logging`: writes measurements and events to SQLite.
- `safety_enforcement`: enforces pressure, prime, booster, chlorine, and freeze
  interlocks.
- `chlorination`: runs the open-loop chlorine dosing duty-cycle controller.
- `mqtt_bridge`: publishes telemetry and optionally accepts selected inputs.
- `closed_loop_control`: reserved for later closed-loop control work.

For the Pi dumb-timer phase, `pi-prod.yaml` can run without
`safety_enforcement`. That allows pump and booster operation before pressure
sensors are installed. Add safety only after the required pressure readings are
wired, calibrated, and verified.

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

The Pi pressure group uses a 2-sample boxcar so overpressure safety still reacts
in about two seconds or less. The chemistry group reads less often and uses a
60-second boxcar. Pump-flow-qualified chemistry readings that are invalid
because the pump is off or not yet stirred are not logged and do not enter the
rolling filter.

## Dashboard Pages

- Live: schematic or mobile list view, current sensor/actuator state, quick
  pump controls, chlorination dose target, supplemental chlorine dose action,
  FC-demand status, safety status, CPU temperature/load/fan status on Pi, and
  runtime loop timing.
- History: measurement/weather/test-result/chemical-addition charts with
  selectable series, hover readouts, automatic rollup resolution, past-window
  navigation, calendar/time jump, CSV export, water-test and chemical-addition
  entry, and single-axis or multi-axis scaling depending on selected signal
  ranges.
- Schedule: pump timer schedule editor, including a per-window dosing checkbox
  for excluding cleaning/night runs from liquid chlorine dosing.
- Config: forms for runtime layers, safety, chlorination, FC demand,
  acquisition, logging, analog input calibration/raw voltage display, pH sensor
  enable/calibration, notifications, and diagnostic dosing-pump
  prime/calibration tests.

Some config changes apply live. Others write YAML and require restart because
drivers or long-lived services must be rebuilt.

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

## Open-loop Chlorination

Liquid chlorine dosing is implemented as the `chlorination` layer. On Raspberry
Pi hardware, the chlorine dosing pump is mapped to relay 7 by default.

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

1. Uses only pump timer schedules with `allow_dosing: true`.
2. Merges overlapping or adjacent dosing-allowed pump timer windows.
3. Removes the final `no_dose_last_minutes` from each continuous allowed run.
4. Computes total valid daily dosing minutes.
5. Converts `daily_dose_oz` to dosing pump minutes using
   `pump_output_oz_per_min`.
6. Computes duty cycle as requested minutes divided by available minutes.
7. Caps duty cycle at `max_duty_cycle`.
8. Computes an effective ON/OFF pulse schedule for that duty cycle.

This allows the same pump timer to run the pool at night for skimming or
vacuuming while keeping the day's chlorine dose in morning and daytime windows
before evening FC tests.

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
The Config page has diagnostic dosing-pump buttons:

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
runtime forces the filter pump on at low speed, doses at the configured
`max_duty_cycle`, then keeps the pump running for `no_dose_last_minutes` after
the final dosing pulse. This is normal pool dosing, not a diagnostic run: it
does not bypass safety, and delivered runtime is included in logged chlorine
delivery, daily sodium-hypochlorite totals, and FC-demand addition math.
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

The History page can graph chlorination control signals:

- `Daily chlorine delivered`: cumulative fluid ounces delivered since local
  midnight using the configured pump timer timezone. This is a graph snapshot of
  the persistent chlorine delivery event table, not the source of dose
  accounting. Normal dosing logs one snapshot at segment start with the current
  total and one at segment end with the updated total. A zero-value reset
  snapshot is logged at local midnight.
- `Dosing duty cycle`: the current duty cycle during valid dosing time. This is
  logged across the full eligible window, including duty-cycle OFF portions, but
  not during high-FC holdoff time. Like daily delivered chlorine, it uses
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
  FC test and an earlier test selected near the configured lookback window,
  logged once per distinct estimate.
- `Base FC demand`: exponential moving average of FC demand. This is an
  observe-only baseline for seasonal trend work; it does not change dosing by
  itself.
- `Predicted FC demand` and `FC demand residual`: placeholder prediction and
  actual-minus-predicted error. For now the prediction is just the baseline with
  no pH, ORP, UV, or temperature modifier.
- `Daily ORP avg`, `Daily water temp min/avg/max`, and `Daily pH avg`: daily
  summaries from `raw_orp`, `orp_temp`, and `raw_ph`. The water-temperature
  minimum is logged because it may better represent pool water than daytime
  plumbing warmed by sun.
- `ORP 7d/28d avg`, `Water temp 7d/28d avg`, `pH 7d/28d avg`, and
  `UV dose 7d/28d avg`: moving averages of the completed-day summary rows for
  seasonal demand tracking.
- `Daily UV dose` and `Daily shortwave dose`: previous-day sums from the
  Open-Meteo hourly weather history, for later correlation with FC demand.

Example:

```yaml
runtime:
  enabled_layers:
  - pump_timer
  - logging
  - acquisition
  - chlorination

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
  no_dose_last_minutes: 10.0
  max_duty_cycle: 0.5
  cycle_on_seconds: 60.0
  max_cycle_period_seconds: 1800.0
  min_cycle_on_seconds: 5.0

fc_demand:
  enabled: true
  mode: observe_only
  pool_volume_gal: 10000.0
  target_fc_ppm: 4.0
  chlorine_strength_percent: 12.0
  minimum_test_interval_hours: 12.0
  demand_window_days: 7.0
  max_demand_window_days: 14.0
  max_daily_dose_oz: 256.0
```

If safety enforcement is enabled, dosing ON commands still pass through the
safety gate. For low-speed scheduled dosing, set:

```yaml
safety:
  thresholds:
    chlorine_requires_high_speed: false
```

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

`fc_demand` estimates daily free-chlorine demand from manual FC tests plus
logged chlorine additions/delivery. It deliberately does not use ORP or pH.
The history page also logs observe-only trend signals for base demand,
predicted demand, residual demand, daily ORP, pH, ORP-temperature min/avg/max,
UV dose, shortwave dose, daily chemical totals, and 7-day/28-day daily moving
averages. These provide the data needed to evaluate seasonal temperature,
sunlight, and chemical-demand modifiers later without changing the current
dosing controller.

The estimator needs at least two manual free-chlorine test results. It uses the
latest FC test as the current value, then selects an earlier test for the mass
balance:

- Ignore tests closer than `minimum_test_interval_hours`.
- Prefer the earliest test at or beyond `demand_window_days` before the latest
  test.
- If there is no test that old, use the oldest eligible test inside the maximum
  window.
- If no eligible prior test is within `max_demand_window_days`, wait for better
  test history instead of estimating from stale conditions.

Between the selected tests, it sums:

- automated dosing pump delivery logged by the runtime loop
- manually logged sodium hypochlorite additions

It converts liquid chlorine ounces to FC ppm using:

```text
FC ppm = (fluid ounces / 128) * strength_percent * (10000 / pool_volume_gal)
```

Then it estimates:

```text
daily demand ppm = max(0, previous FC + added FC - current FC) / elapsed days
maintenance dose oz/day = dose needed to replace daily demand
```

The default `demand_window_days: 7.0` and `max_demand_window_days: 14.0` reduce
single-test noise while still letting weekly weather and sunlight changes move
the estimate. The live status and lab-test feedback show the elapsed days used
for the current estimate.

When FC is below `target_fc_ppm`, the catch-up dose is added only on the day
after the latest FC test. After that day, the dose returns to the estimated
maintenance dose.

When FC is above target, the estimator converts the high FC amount into
`skip_days = high_fc_ppm / daily_demand_ppm`. In automatic mode, it keeps the
normal maintenance duty cycle but delays dosing by that fraction of eligible
schedule time. For example, if the schedule has 420 valid dosing minutes and FC
is high by 0.5 days of demand, dosing starts 210 eligible minutes later.

`mode` controls whether the estimate is applied:

- `observe_only`: calculate and display status only.
- `recommend`: calculate recommendations without applying them.
- `approve_required`: reserved for a future approval workflow.
- `automatic`: pass the effective daily dose and any high-FC delay into the
  chlorination controller.

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
4. Put the secrets on the Pi in `/etc/poolctl/poolctl.env`.
5. Enable notifications in the Config page or YAML.
6. Press `Send Test` on the Config page.

The project keeps secrets out of the repo. `pi-prod.yaml` stores only the names
of the environment variables:

```yaml
notifications:
  enabled: true
  provider: pushover
  default_title: poolctl
  pushover:
    app_token_env: PUSHOVER_APP_TOKEN
    user_key_env: PUSHOVER_USER_KEY
    api_url: https://api.pushover.net/1/messages.json
    timeout_s: 5.0
    priority: 0
    sound: null
```

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

- Pi username: `pool`
- Project directory: `/home/pool/projects/pool`
- Virtual environment: `/home/pool/projects/pool/venv`
- Config: `/home/pool/projects/pool/configs/pi-prod.yaml`

Install OS packages:

```bash
sudo apt update
sudo apt install -y git python3-venv python3-pip sqlite3
```

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
python -m pip install -e ".[raspberrypi,mqtt]"
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
python -m pip install -e ".[raspberrypi,mqtt]"
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

If you still have old local Pi edits in `configs/pi-prod.yaml`, move the local
sections into `configs/pi-local.yaml`, then restore the tracked base file before
pulling:

```bash
git restore configs/pi-prod.yaml
git pull --ff-only
```

Do not run `git reset --hard` unless you are certain there is nothing local you
want to keep.

## Raspberry Pi Services

`deploy/systemd/install-pi-services.sh` installs:

- `poolctl.service`: dashboard plus dedicated runtime loop.
- `poolctl-backup.service`: one-shot SQLite backup job.
- `poolctl-backup.timer`: hourly backup schedule.

The older `poolctl-ticker.service` template is kept only for history and is
disabled by the installer. The current web server has its own dedicated runtime
loop, so no external ticker is required.

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

`pi-prod.yaml` keeps the pH sensor disabled until the probe is installed:

```yaml
enable_modbus_ph_sensor: false
modbus_ph_sensor:
  port: /dev/ttyUSB0
  slave_id: 4
  baudrate: 4800
  timeout_s: 1.0
  circuit_breaker:
    enabled: true
    failure_threshold: 2
    cooldown_s: 60
```

The Config page has a `pH Sensor Config` section. Turning the sensor on or off
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

The same Config page has low-point and high-point pH calibration buttons. Enter
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

## Operational Notes

- Keep `data/` out of Git. The SQLite database is local operational state.
- `git pull` will not overwrite ignored database files such as
  `data/pi-prod.sqlite3`.
- Stop the service before manually using the RS485 port.
- If a Modbus port reports exclusive-lock errors, check for services such as
  `ModemManager` or any running `poolctl` process.
- The Config page can update many values, but driver-level changes usually
  require a service restart.
- The default Pi `pi-prod.yaml` starts with chlorination enabled but
  `daily_dose_oz: 0.0`, so installing the update does not start dosing until a
  nonzero dose is entered.
