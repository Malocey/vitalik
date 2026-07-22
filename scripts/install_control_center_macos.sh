#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="$(command -v python3)"
TAILSCALE_BIN="$(command -v tailscale)"
PLIST_PATH="$HOME/Library/LaunchAgents/de.vg-delikatessen.control-center.plist"
LOG_DIR="$PROJECT_ROOT/data/logs"

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR" "$PROJECT_ROOT/data/inbox"

ADMIN_LOGIN="$($TAILSCALE_BIN status --json | "$PYTHON_BIN" -c '
import json, sys
d=json.load(sys.stdin)
uid=str(d["Self"]["UserID"])
print(d["User"][uid]["LoginName"])
')"

"$PYTHON_BIN" -m pip install --user -r "$PROJECT_ROOT/requirements.txt"

PLIST_TMP="$(mktemp)"
trap 'rm -f "$PLIST_TMP"' EXIT
sed \
  -e "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" \
  -e "s|__PYTHON_BIN__|$PYTHON_BIN|g" \
  -e "s|__ADMIN_LOGIN__|$ADMIN_LOGIN|g" \
  "$PROJECT_ROOT/config/de.vg-delikatessen.control-center.plist.template" > "$PLIST_TMP"
mv "$PLIST_TMP" "$PLIST_PATH"
trap - EXIT

launchctl bootout "gui/$UID/de.vg-delikatessen.control-center" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST_PATH"
launchctl enable "gui/$UID/de.vg-delikatessen.control-center"
launchctl kickstart -k "gui/$UID/de.vg-delikatessen.control-center"

# Ausschließlich privat im Tailnet veröffentlichen. Funnel wird nicht verwendet.
"$TAILSCALE_BIN" serve --bg 127.0.0.1:8000

echo "Control Center installiert."
echo "Admin: $ADMIN_LOGIN"
echo "Privater Name: https://$(hostname | tr '[:upper:] ' '[:lower:]-').$(tailscale status --json | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["MagicDNSSuffix"])')"
