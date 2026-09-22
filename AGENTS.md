# AGENTS.md

Guidance for Codex agents working on `poolctl`.

## Source of Truth

The README files are the source of truth for current project behavior,
operation, deployment, and bring-up:

- `README.md`: architecture, runtime behavior, Windows simulation, Raspberry Pi
  deployment, Modbus bring-up, configuration, dashboard, chlorination, FC
  demand, weather, notifications, and operational notes.
- `deploy/systemd/README.md`: systemd service installation, update flow,
  runtime loop, and database backup behavior.

When code behavior changes, update the relevant README in the same change. Do
not leave documentation stale, especially for Pi deployment, safety behavior,
chlorination behavior, Modbus wiring/configuration, or GUI config semantics.

## Project Shape

Core layout:

```text
configs/
  windows-dev.yaml        Windows simulation profile.
  pi-prod.yaml            Raspberry Pi production profile.
  pi-local.yaml           Ignored Pi-local override when present.
  pi-local.example.yaml   Tracked template for common local overrides.
deploy/systemd/           Pi service and backup installer/templates.
src/poolctl/
  app.py                  Runtime composition and continuous tick orchestration.
  config.py               Runtime hardware profile and live-view config.
  domain/models.py        Stable domain IDs and Measurement/command models.
  drivers/                Hardware/simulation boundaries.
  drivers/modbus/         Shared Modbus RTU bus/register helpers.
  drivers/raspberrypi/    Real Pi relay, analog, ORP, pH, CPU sensors.
  drivers/simulated/      Windows-safe plant, sensors, actuators.
  services/               Acquisition, timer, safety, chlorination, logging,
                           flow estimation, FC demand, weather, notifications.
  tools/                  Modbus bring-up/configuration CLI helpers.
  web/                    HTTP server and static dashboard files.
tests/                    Unit and integration-style tests.
```

Python support is `>=3.13,<3.14`. Current deployments target Raspberry Pi OS
64-bit Trixie with Python 3.13.

## Architectural Rules

- Keep hardware code isolated in drivers. Core logic should depend on driver
  protocols and domain models, not Pi-specific libraries.
- Keep Windows development fully functional with simulated drivers.
- Use `Measurement` models for sensor values. Preserve stable `SensorId` names;
  they are used by logging, GUI, estimators, and configs.
- Keep chemical readings in real engineering units where the system expects
  them. pH is pH units, ORP is mV, temperatures are normalized as documented.
- The active hydraulic pressure input is `pump_output_psi`. Do not add return,
  booster, bubbler, or filter-output pressure dependencies without a deliberate
  hardware change.
- pH is RS485 only. Keep analog pressure support, but do not reintroduce analog
  pH voltage paths.
- Actuators accept only simple states: `ON/OFF` or `LOW/HIGH`. Duration and duty
  decisions belong in scheduler/controller services, not drivers.
- Configurable thresholds belong in YAML and GUI config where appropriate.
- Do not mix hardware behavior into dashboard code. The GUI should call app/API
  functions; drivers should stay behind service boundaries.

## Runtime Loop and Timing

This is a real controller, not only a dashboard. The runtime loop must keep
running even when no browser is open.

Timing-sensitive principles:

- Each tick refreshes actuator state and runs timer/chlorination boundary
  decisions before potentially slower acquisition. Derived calculations and
  SafetyGate enforcement follow using the latest available measurements.
- The control-first order is intentional: optional sensor/Modbus latency must
  not stretch a chlorine ON pulse. Supported Pi relays also use timed flash for
  independent hardware OFF timing, followed by redundant software OFF.
- Avoid blocking the main tick with slow operations.
- Keep weather/network work outside the control-critical path.
- Keep Modbus traffic efficient. Prefer one bulk read per hardware device when
  registers are contiguous.
- Pressure/analog reads should not be delayed by optional chemistry probes.
- ORP and pH drivers have circuit breakers so failed probes do not repeatedly
  consume Modbus timeout time.
- Acquisition smoothing should usually use rolling filters across ticks, not
  long burst oversampling that blocks actuator decisions.

## Chlorine Dosing Is Control-Critical

Treat chlorine dosing timing as high importance. Small timing errors accumulate
into real chemical dose errors.

Rules for chlorination changes:

- Do not add blocking work before dosing pump state evaluation.
- Do not let failed ORP/pH sensors, weather fetches, GUI requests, logging, or
  other nonessential work cause the dosing pump to turn off late.
- Be careful with command routing changes. Late `OFF` commands skew delivered
  chlorine upward.
- On Raspberry Pi hardware, normal dosing ON segments use the Waveshare relay
  module's timed flash command by default. Preserve this behavior unless there
  is a deliberate hardware compatibility reason to disable it, because it limits
  a Pi/process crash during dosing to the active pulse instead of a latched ON
  relay.
- Dosing flash pulses are quantized to 100 ms before command and accounting.
  Preserve that agreement between command metadata, driver writes, and chlorine
  delivery logging.
- Poolctl sends a redundant OFF confirmation after a timed flash pulse expires.
  Do not remove it as "unnecessary"; it is a secondary safety check, while the
  relay module flash timer remains the primary pulse-end mechanism.
- Raspberry Pi relay deployments perform startup safe-stop and periodic relay
  reconciliation. Keep those actions after or outside time-critical dosing
  boundary decisions so slow readbacks cannot delay a dose transition.
- Diagnostic prime/calibration pump runs are not normal dosing and must remain
  excluded from daily chlorine totals and FC-demand calculations.
- Pump timer schedules with `allow_dosing: false` still run equipment but must
  remain excluded from valid dosing windows, daily available dosing minutes, and
  FC-demand high-FC delay calculations.
- The open-loop dosing controller should maintain predictable ON/OFF timing and
  duty cycle across the valid dosing window.
- Low-duty-cycle dosing uses adaptive pulse timing. Preserve dose accuracy when
  touching `cycle_on_seconds`, `max_cycle_period_seconds`, or
  `min_cycle_on_seconds`; do not introduce tiny unreliable pulses or long late
  OFF transitions.
- If a change affects tick frequency, asyncio scheduling, Modbus retries,
  actuator command routing, or chlorination status logging, add focused tests
  around dosing timing and delivery accounting.

Current intended behavior is documented in `README.md`; update it with any
change to chlorination, FC-demand, diagnostic dosing, or relay mapping.

## Safety and Configuration

- Safety thresholds are configurable. Do not hard-code pool-specific pressure
  values in services unless they are defaults that can be overridden.
- SafetyGate is always active. Safety lockouts should fail safe and remain
  cleared only by explicit action.
- Freeze protection uses raw temperature availability as documented.
- Pi `pi-prod.yaml` is a real deployment config. Treat changes carefully and
  keep them deployable.
- Pi deployments can merge ignored `configs/pi-local.yaml` on top of tracked
  `configs/pi-prod.yaml`. Put frequently changed site-specific values such as
  schedules, daily chlorine dose, dosing pump rate, and FC-demand settings in
  the local override. Do not require users to edit `pi-prod.yaml` for daily
  operational changes.
- GUI config saves should write to the configured local override when one is
  active, while reads and runtime builds should use the merged effective config.
- The config GUI must round-trip new YAML fields. If a web form saves a section,
  it must not silently delete fields it does not display.

## Data and Logging

- Do not commit live SQLite databases or generated operational state.
- Preserve logged sensor IDs and units unless there is a deliberate migration.
- Derived signals that are shown in history should be logged consistently.
- Event-like records, such as lab tests and chemical additions, are distinct
  from continuous measurements. Preserve that distinction in history views.
- Database backup behavior is documented under `deploy/systemd/README.md`.

## Testing Expectations

Run focused tests for the changed area, then run the full suite when practical:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src tests
```

Useful focused areas:

- Acquisition/filtering: `tests/test_acquisition.py`
- Chlorination: `tests/test_chlorination.py`
- FC demand: `tests/test_fc_demand.py`
- Safety: `tests/test_safety_gate.py`
- Pi sensors/Modbus: `tests/test_raspberrypi_sensors.py`,
  `tests/test_modbus_*.py`
- Web/API/config: `tests/test_web_live.py`, `tests/test_web_server_config.py`

Add tests for bug fixes. Prefer deterministic tests with `SimulatedClock`.

## Development Practices

- Read existing code before editing. Follow local patterns.
- Keep changes scoped to the requested behavior.
- Use structured parsers/config models rather than ad hoc string handling.
- Maintain Python 3.11 compatibility.
- Use `rg`/fast search tools where available.
- Use `apply_patch` for manual file edits.
- Do not revert unrelated local changes.
- Do not run destructive git commands unless explicitly requested.
- If adding dependencies, update `pyproject.toml` and docs, and keep Pi install
  implications in mind.

## Frontend Practices

- The dashboard is an operational tool, not a marketing page.
- Keep UI dense, readable, and reliable on desktop and mobile.
- Avoid JSON editing in the GUI when a form/checkbox/select is practical.
- Config forms should pause/revert live refresh behavior as established in the
  current UI.
- Preserve top status visibility across Live, History, Schedule, and Config.
- For history charts, keep multi-signal readability in mind.

## Deployment Notes

The Pi service runs the web server plus the dedicated runtime loop. There should
not be a separate ticker service in normal operation. Service installation and
update commands belong in `README.md` and `deploy/systemd/README.md`.

After changes to service templates, installer scripts, dependencies, runtime
entry points, or Pi config, update deployment docs and mention whether the Pi
needs:

- `git pull`
- `python -m pip install -e ".[raspberrypi]"`
- rerunning `deploy/systemd/install-pi-services.sh`
- `sudo systemctl restart poolctl.service`
