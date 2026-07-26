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
- Open-loop chlorine dosing on relay 7, with dashboard prime and calibration
  test buttons.
- Optional FC-demand estimator based on manual FC tests and logged chlorine
  delivery/additions. ORP and pH are not used by this estimator.
- Safety enforcement layer with configurable pressure gates and lockouts.
- Freeze protection with hysteresis and minimum runtime.
- Sensor acquisition with per-group read/log rates and oversampling.
- SQLite logging for measurements, weather, test results, and chemical additions.
- Live web GUI, mobile-friendly live list view, config forms, schedule editor,
  test result entry, chemical addition entry, and history charts.
- Hourly Open-Meteo weather observation logging plus a 48-hour in-memory forecast.
- MQTT telemetry and selected input support when enabled.
- Optional Pushover notification provider with a dashboard test button.
- Systemd deployment with automatic restart and SQLite backup timer.

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
python -m poolctl.web.server --config configs/windows-dev.yaml --host 127.0.0.1 --port 8000 --sim-speedup 60 --tick-interval-s 1.0
```

Open:

```text
http://127.0.0.1:8000
```

Notes:

- `--sim-speedup 60` means one real second advances the simulated clock by
  about one simulated minute.
- `--tick-interval-s 1.0` runs the runtime loop once per real second.
- The runtime loop keeps acquisition, timers, dosing, logging, weather, and
  safety moving even when the browser is closed.
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

The active config file controls the deployment. The two main configs are:

- `configs/windows-dev.yaml`
- `configs/pi-prod.yaml`

Important sections:

- `runtime`: stage, driver profile, enabled feature layers, enabled actuators,
  enabled sensor groups.
- `pump_timer`: local timezone and daily pump/booster schedule windows.
- `chlorination`: open-loop liquid chlorine dose settings.
- `fc_demand`: optional free-chlorine demand estimator settings.
- `safety`: pressure interlocks, lockout thresholds, freeze protection.
- `acquisition`: sensor groups, read intervals, log intervals, validation rules,
  oversampling, chemistry refresh runs.
- `logging`: SQLite database path.
- `modbus_relay`: relay board serial settings, Modbus slave ID, relay mapping.
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
```

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

## Dashboard Pages

- Live: schematic or mobile list view, current sensor/actuator state, quick
  pump controls, chlorination dose target, FC-demand status, safety status, CPU
  status on Pi.
- History: measurement/weather/test-result/chemical-addition charts with
  selectable series and auto-scaled axes.
- Schedule: pump timer schedule editor.
- Config: forms for runtime layers, safety, chlorination, FC demand,
  acquisition, logging, analog input calibration, and diagnostic dosing-pump
  prime/calibration tests.

Some config changes apply live. Others write YAML and require restart because
drivers or long-lived services must be rebuilt.

## Open-loop Chlorination

Liquid chlorine dosing is implemented as the `chlorination` layer. On Raspberry
Pi hardware, the chlorine dosing pump is mapped to relay 7 by default.

The controller:

1. Merges overlapping or adjacent pump timer windows.
2. Removes the final `no_dose_last_minutes` from each continuous pump run.
3. Computes total valid daily dosing minutes.
4. Converts `daily_dose_oz` to dosing pump minutes using
   `pump_output_oz_per_min`.
5. Computes duty cycle as requested minutes divided by available minutes.
6. Caps duty cycle at `max_duty_cycle`.
7. Runs fixed `cycle_on_seconds` ON intervals with calculated OFF time.

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

The History page can graph chlorination control signals:

- `Daily chlorine delivered`: cumulative fluid ounces delivered since local
  midnight using the configured pump timer timezone.
- `Dosing duty cycle`: the current duty cycle during valid dosing time. This is
  logged across the full eligible window, including duty-cycle OFF portions, but
  not during high-FC holdoff time.
- `FC demand`: estimated free-chlorine consumption in ppm/day from the latest
  two manual FC tests, logged once per distinct estimate.
- `Base FC demand`: exponential moving average of FC demand. This is an
  observe-only baseline for seasonal trend work; it does not change dosing by
  itself.
- `Predicted FC demand` and `FC demand residual`: placeholder prediction and
  actual-minus-predicted error. For now the prediction is just the baseline with
  no pH, ORP, UV, or temperature modifier.
- `Daily water temp min/avg/max`: daily summaries from the `orp_temp` sensor.
  The minimum is logged because it may better represent pool water than daytime
  plumbing warmed by sun.
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
  relays:
    chlorine_dosing_pump: 7

chlorination:
  enabled: true
  daily_dose_oz: 0.0
  pump_output_oz_per_min: 1.0
  no_dose_last_minutes: 10.0
  max_duty_cycle: 0.5
  cycle_on_seconds: 60.0

fc_demand:
  enabled: true
  mode: observe_only
  pool_volume_gal: 10000.0
  target_fc_ppm: 4.0
  chlorine_strength_percent: 12.0
  minimum_test_interval_hours: 12.0
  max_daily_dose_oz: 256.0
```

If safety enforcement is enabled, dosing ON commands still pass through the
safety gate. For low-speed scheduled dosing, set:

```yaml
safety:
  thresholds:
    chlorine_requires_high_speed: false
```

## FC-Demand Estimator

`fc_demand` estimates daily free-chlorine demand from manual FC tests plus
logged chlorine additions/delivery. It deliberately does not use ORP or pH.
The history page also logs observe-only trend signals for base demand,
predicted demand, residual demand, daily ORP-temperature min/avg/max, UV dose,
and shortwave dose. These provide the data needed to evaluate seasonal
temperature and sunlight modifiers later without changing the current dosing
controller.

The estimator needs at least two manual free-chlorine test results separated by
`minimum_test_interval_hours`. Between those tests, it sums:

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
BACKUP_DB_PATH=/home/pool/projects/pool/data/pi-prod.sqlite3 \
BACKUP_DIR=/var/backups/poolctl \
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
BACKUP_DB_PATH=/home/pool/projects/pool/data/pi-prod.sqlite3 \
BACKUP_DIR=/var/backups/poolctl \
./deploy/systemd/install-pi-services.sh
```

If you intentionally want to discard local Pi edits to a file before pulling:

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

`pi-prod.yaml` keeps the pH sensor disabled until the probe is installed:

```yaml
enable_modbus_ph_sensor: false
modbus_ph_sensor:
  port: /dev/ttyUSB0
  slave_id: 4
  baudrate: 4800
  timeout_s: 1.0
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
  --tick-interval-s 1.0
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
