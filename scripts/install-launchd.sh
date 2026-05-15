#!/usr/bin/env bash
set -euo pipefail

LABEL="${YANTRIKDB_DASHBOARD_LAUNCHD_LABEL:-io.yantrikdb.dashboard.local}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${YANTRIKDB_DASHBOARD_PYTHON:-${PYTHON:-python3}}"
HOST="${YANTRIKDB_DASHBOARD_HOST:-0.0.0.0}"
PORT="${YANTRIKDB_DASHBOARD_PORT:-8767}"
DB_PATH="${YANTRIKDB_DB_PATH:-$HOME/.hermes/yantrikdb-memory.db}"
BASE_NAMESPACE="${YANTRIKDB_NAMESPACE:-hermes}"
DASHBOARD_NAMESPACE="${YANTRIKDB_DASHBOARD_NAMESPACE:-${BASE_NAMESPACE}:hermes:default}"
LOG_DIR="${YANTRIKDB_DASHBOARD_LOG_DIR:-$APP_DIR/.run}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1 && [ ! -x "$PYTHON_BIN" ]; then
  echo "Python not found or not executable: $PYTHON_BIN" >&2
  echo "Set YANTRIKDB_DASHBOARD_PYTHON=/absolute/path/to/python" >&2
  exit 1
fi

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>

  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>$APP_DIR/app.py</string>
  </array>

  <key>WorkingDirectory</key>
  <string>$APP_DIR</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>YANTRIKDB_DASHBOARD_HOST</key>
    <string>$HOST</string>
    <key>YANTRIKDB_DASHBOARD_PORT</key>
    <string>$PORT</string>
    <key>YANTRIKDB_DB_PATH</key>
    <string>$DB_PATH</string>
    <key>YANTRIKDB_NAMESPACE</key>
    <string>$BASE_NAMESPACE</string>
    <key>YANTRIKDB_DASHBOARD_NAMESPACE</key>
    <string>$DASHBOARD_NAMESPACE</string>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
  </dict>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>

  <key>ThrottleInterval</key>
  <integer>5</integer>

  <key>StandardOutPath</key>
  <string>$LOG_DIR/launchd.out.log</string>

  <key>StandardErrorPath</key>
  <string>$LOG_DIR/launchd.err.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

echo "Installed $LABEL"
echo "Plist: $PLIST"
echo "Logs: $LOG_DIR/launchd.out.log $LOG_DIR/launchd.err.log"
echo "URL: http://$HOST:$PORT"
