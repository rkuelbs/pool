# poolctl systemd deployment

This folder includes an installer that sets up:

- `poolctl.service` (web server + runtime)
- `poolctl-ticker.service` (drives continuous `tick()` calls even without dashboard open)
- `poolctl-backup.service` + `poolctl-backup.timer` (hourly SQLite backups)

## Install

From repo root on Pi:

```bash
chmod +x deploy/systemd/install-pi-services.sh
./deploy/systemd/install-pi-services.sh
```

## User/path overrides

Defaults are based on current shell user and:
- project dir: `~/projects/pool`
- venv: `~/projects/pool/venv`
- config: `~/projects/pool/configs/pi-prod.yaml`

Override if needed:

```bash
APP_USER=pool \
APP_GROUP=pool \
PROJECT_DIR=/home/pool/projects/pool \
VENV_DIR=/home/pool/projects/pool/venv \
CONFIG_PATH=/home/pool/projects/pool/configs/pi-prod.yaml \
BACKUP_DB_PATH=/home/pool/projects/pool/data/pi-prod.sqlite3 \
BACKUP_DIR=/var/backups/poolctl \
./deploy/systemd/install-pi-services.sh
```

## Check status/logs

```bash
sudo systemctl status poolctl.service poolctl-ticker.service poolctl-backup.timer
journalctl -u poolctl.service -f
```
