#!/usr/bin/env bash
set -euo pipefail

LABEL="${YANTRIKDB_DASHBOARD_LAUNCHD_LABEL:-io.yantrikdb.dashboard.local}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
rm -f "$PLIST"

echo "Uninstalled $LABEL"
