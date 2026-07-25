#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

APP_USER="${APP_USER:-$(id -un)}"
APP_GROUP="${APP_GROUP:-$(id -gn)}"
APP_HOME="${APP_HOME:-$(getent passwd "$APP_USER" | cut -d: -f6)}"

if [ -z "${APP_HOME:-}" ]; then
  echo "could not resolve home directory for user: $APP_USER"
  exit 1
fi

PROJECT_DIR="${PROJECT_DIR:-$APP_HOME/projects/pool}"
VENV_DIR="${VENV_DIR:-$PROJECT_DIR/venv}"
CONFIG_PATH="${CONFIG_PATH:-$PROJECT_DIR/configs/pi-prod.yaml}"
WEB_HOST="${WEB_HOST:-0.0.0.0}"
WEB_PORT="${WEB_PORT:-8000}"
TICK_INTERVAL_S="${TICK_INTERVAL_S:-1.0}"
BACKUP_DB_PATH="${BACKUP_DB_PATH:-$PROJECT_DIR/data/pi-prod.sqlite3}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/poolctl}"
BACKUP_KEEP_COUNT="${BACKUP_KEEP_COUNT:-720}"

SUDO="${SUDO:-sudo}"
if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
fi

for path in "$PROJECT_DIR" "$VENV_DIR" "$CONFIG_PATH"; do
  if [ ! -e "$path" ]; then
    echo "required path not found: $path"
    exit 1
  fi
done

if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "python not executable in venv: $VENV_DIR/bin/python"
  exit 1
fi

render_template() {
  local src="$1"
  local dst="$2"
  sed \
    -e "s|__APP_USER__|$APP_USER|g" \
    -e "s|__APP_GROUP__|$APP_GROUP|g" \
    -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    -e "s|__VENV_DIR__|$VENV_DIR|g" \
    -e "s|__CONFIG_PATH__|$CONFIG_PATH|g" \
    -e "s|__WEB_HOST__|$WEB_HOST|g" \
    -e "s|__WEB_PORT__|$WEB_PORT|g" \
    -e "s|__TICK_INTERVAL_S__|$TICK_INTERVAL_S|g" \
    -e "s|__BACKUP_DB_PATH__|$BACKUP_DB_PATH|g" \
    -e "s|__BACKUP_DIR__|$BACKUP_DIR|g" \
    -e "s|__BACKUP_KEEP_COUNT__|$BACKUP_KEEP_COUNT|g" \
    "$src" > "$dst"
}

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

render_template "$SCRIPT_DIR/poolctl.service.tmpl" "$TMP_DIR/poolctl.service"
render_template "$SCRIPT_DIR/poolctl-backup.service.tmpl" "$TMP_DIR/poolctl-backup.service"
render_template "$SCRIPT_DIR/poolctl-backup.sh.tmpl" "$TMP_DIR/poolctl-backup.sh"
cp "$SCRIPT_DIR/poolctl-backup.timer" "$TMP_DIR/poolctl-backup.timer"

echo "Installing systemd units and backup script..."
$SUDO install -m 0644 "$TMP_DIR/poolctl.service" /etc/systemd/system/poolctl.service
$SUDO install -m 0644 "$TMP_DIR/poolctl-backup.service" /etc/systemd/system/poolctl-backup.service
$SUDO install -m 0644 "$TMP_DIR/poolctl-backup.timer" /etc/systemd/system/poolctl-backup.timer
$SUDO install -m 0750 "$TMP_DIR/poolctl-backup.sh" /usr/local/bin/poolctl-backup.sh

echo "Preparing optional environment file..."
$SUDO mkdir -p /etc/poolctl
if [ ! -e /etc/poolctl/poolctl.env ]; then
  cat > "$TMP_DIR/poolctl.env" <<'EOF'
# Optional poolctl runtime secrets.
# Uncomment and fill these to enable Pushover notifications.
# PUSHOVER_APP_TOKEN=
# PUSHOVER_USER_KEY=
EOF
  $SUDO install -m 0600 "$TMP_DIR/poolctl.env" /etc/poolctl/poolctl.env
fi

echo "Creating backup directory..."
$SUDO mkdir -p "$BACKUP_DIR"
$SUDO chown root:root "$BACKUP_DIR"
$SUDO chmod 0750 "$BACKUP_DIR"

echo "Reloading systemd and enabling services..."
$SUDO systemctl daemon-reload
$SUDO systemctl enable --now poolctl.service
$SUDO systemctl enable --now poolctl-backup.timer
$SUDO systemctl disable --now poolctl-ticker.service >/dev/null 2>&1 || true

echo
echo "Installed with:"
echo "  APP_USER=$APP_USER"
echo "  APP_GROUP=$APP_GROUP"
echo "  PROJECT_DIR=$PROJECT_DIR"
echo "  VENV_DIR=$VENV_DIR"
echo "  CONFIG_PATH=$CONFIG_PATH"
echo "  WEB_HOST=$WEB_HOST"
echo "  WEB_PORT=$WEB_PORT"
echo "  TICK_INTERVAL_S=$TICK_INTERVAL_S"
echo "  BACKUP_DB_PATH=$BACKUP_DB_PATH"
echo "  BACKUP_DIR=$BACKUP_DIR"
echo "  BACKUP_KEEP_COUNT=$BACKUP_KEEP_COUNT"
echo
echo "Status:"
echo "  $SUDO systemctl status poolctl.service poolctl-backup.timer"
echo "Logs:"
echo "  journalctl -u poolctl.service -f"
