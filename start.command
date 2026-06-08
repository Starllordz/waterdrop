#!/usr/bin/env bash
#
# Waterdrop launcher — double-click to start the app.
# Starts the local Python server and opens the UI in a dedicated app window.
#
set -euo pipefail
cd "$(dirname "$0")"

# Start the server in the background and capture its output (to learn the URL).
LOG="$(mktemp -t waterdrop)"
python3 server.py >"$LOG" 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT

# Wait for the server to announce its URL.
URL=""
for _ in $(seq 1 60); do
  URL="$(grep -m1 '^WATERDROP_URL=' "$LOG" 2>/dev/null | cut -d= -f2- || true)"
  [ -n "$URL" ] && break
  # stop early if the server died (e.g. python error)
  kill -0 "$SERVER_PID" 2>/dev/null || { cat "$LOG"; exit 1; }
  sleep 0.1
done
[ -n "$URL" ] || URL="http://127.0.0.1:8765"

# Open in a chromium-based app window if available, else the default browser.
open_app_window() {
  for app in "Google Chrome" "Microsoft Edge" "Brave Browser" "Chromium" "Arc"; do
    if [ -d "/Applications/$app.app" ]; then
      open -na "$app" --args --app="$URL" --new-window >/dev/null 2>&1 && return 0
    fi
  done
  return 1
}
open_app_window || open "$URL"

echo "💧 Waterdrop is running at $URL"
echo "Close this window (or press Ctrl+C) to stop the app."
wait "$SERVER_PID"
