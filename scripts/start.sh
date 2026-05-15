#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PY="${YANTRIKDB_DASHBOARD_PYTHON:-${PYTHON:-python3}}"
exec "$PY" "$APP_DIR/app.py"
