# poolctl systemd deployment

This directory contains the Raspberry Pi service installer and systemd unit
templates for running `poolctl` as a 24/7 controller.

The canonical install path is:

```bash
./deploy/systemd/install-pi-services.sh
```

The installer renders templates using environment variables, installs units
under `/etc/systemd/system`, enables the services, and disables the old
external ticker service if it exists.

## Installed Units

- `poolctl.service`
  - Runs `python -m poolctl.web.server`.
  - Serves the dashboard.
  - Runs the dedicated runtime tick loop using `--tick-interval-s`.
  - Restarts automatically after crashes or power-cycle boot.

- `poolctl-backup.service`
  - One-shot SQLite backup job.
  - Uses SQLite `.backup`, source `quick_check`, backup `integrity_check`,
    gzip compression, and SHA-256 sidecar files.

- `poolctl-backup.timer`
  - Runs the backup service hourly.
  - Uses `Persistent=true`, so a missed backup runs after boot.

The web server has a built-in runtime loop. The installer disables any old
`poolctl-ticker.service` unit left on a Pi from a previous deployment, but no
ticker service template is retained in source.

## Expected Pi Layout

The current deployment convention is:

```text
/home/pool/projects/pool/       repository
/home/pool/projects/pool/venv/  Python virtual environment
/home/pool/projects/pool/data/  live SQLite database
/var/backups/poolctl/           timestamped compressed backups
```

The defaults are based on the user running the installer, but the explicit
`pool` values below avoid surprises.

## Runtime Environment File

`poolctl.service` reads `/etc/poolctl/poolctl.env` if it exists. The installer
creates this file with commented Pushover placeholders on first install and
does not overwrite it later. Put runtime secrets there, not in tracked YAML:

```bash
PUSHOVER_APP_TOKEN=your_app_token_here
PUSHOVER_USER_KEY=your_user_key_here
```

## First Install

From the repo root on the Pi:

```bash
# Raspberry Pi OS 64-bit Trixie with Python 3.13 is the intended target.
sudo apt update
sudo apt install -y git python3-venv python3-pip sqlite3

python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[raspberrypi]"

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

`BACKUP_KEEP_COUNT=720` keeps about 30 days of hourly backups.

`LOCAL_CONFIG_PATH` defaults to `configs/pi-local.yaml`. The file is optional
and may be missing on first boot. When present, it is merged on top of
`CONFIG_PATH`; dashboard config edits are saved there so `git pull` can update
the tracked base config without conflicting with schedule or dose changes.

## Reinstall or Update Services

Rerun the installer whenever service templates or backup scripts change:

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

For a code-only update where service templates did not change:

```bash
cd /home/pool/projects/pool
git pull --ff-only
source venv/bin/activate
python -m pip install -e ".[raspberrypi]"
sudo systemctl restart poolctl.service
```

## Status and Logs

```bash
sudo systemctl status poolctl.service
journalctl -u poolctl.service -f
```

Backup timer:

```bash
sudo systemctl status poolctl-backup.timer
sudo systemctl list-timers poolctl-backup.timer
```

Run a backup immediately:

```bash
sudo systemctl start poolctl-backup.service
journalctl -u poolctl-backup.service -n 50
```

List backups:

```bash
ls -lh /var/backups/poolctl
```

## Service Control

Stop the controller before manually using the RS485 bus:

```bash
sudo systemctl stop poolctl.service
```

Start or restart:

```bash
sudo systemctl start poolctl.service
sudo systemctl restart poolctl.service
```

Disable at boot:

```bash
sudo systemctl disable --now poolctl.service
```

Enable at boot:

```bash
sudo systemctl enable --now poolctl.service
```

## Restore Notes

Backups are gzip-compressed SQLite files named like:

```text
poolctl-20260723T180000Z.sqlite3.gz
```

To inspect one without replacing the live database:

```bash
cd /var/backups/poolctl
gzip -dk poolctl-YYYYMMDDTHHMMSSZ.sqlite3.gz
sqlite3 poolctl-YYYYMMDDTHHMMSSZ.sqlite3 "PRAGMA integrity_check;"
```

To restore, stop the service first, copy the verified database over the live
database, fix ownership if needed, then start the service:

```bash
sudo systemctl stop poolctl.service
sudo cp /var/backups/poolctl/poolctl-YYYYMMDDTHHMMSSZ.sqlite3 /home/pool/projects/pool/data/pi-prod.sqlite3
sudo chown pool:pool /home/pool/projects/pool/data/pi-prod.sqlite3
sudo systemctl start poolctl.service
```

## Troubleshooting

If `poolctl.service` will not start:

```bash
journalctl -u poolctl.service -n 100 --no-pager
```

Common causes:

- YAML syntax or unquoted schedule times.
- Missing venv packages after a pull.
- Wrong `CONFIG_PATH`.
- RS485 device busy or not present.
- Wrong Modbus address, baudrate, or serial port.

If the serial port is busy, stop `poolctl.service` and check for other users:

```bash
sudo systemctl stop poolctl.service
sudo fuser -v /dev/ttyUSB0
```

If `ModemManager` is installed and probing the adapter, disable it:

```bash
sudo systemctl disable --now ModemManager
```
