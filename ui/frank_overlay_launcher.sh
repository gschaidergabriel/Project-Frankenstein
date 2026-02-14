#!/bin/bash
# Frank Overlay Launcher - Fallback starter
# Only starts the overlay if it's not already running

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AICORE_DIR="$(dirname "$SCRIPT_DIR")"
OVERLAY_SCRIPT="$SCRIPT_DIR/chat_overlay.py"
VENV_PYTHON="$(dirname "$AICORE_DIR")/venv/bin/python3"
ICON="$AICORE_DIR/assets/icons/frank-overlay.svg"
LOG_FILE="/tmp/overlay.log"

# Use venv python if available, else system python
PYTHON="$VENV_PYTHON"
[ -x "$PYTHON" ] || PYTHON=python3

# Check if overlay is already running
if pgrep -f "python3.*chat_overlay.py" > /dev/null 2>&1; then
    wmctrl -a "Frank" 2>/dev/null || xdotool search --name "Frank" windowactivate 2>/dev/null
    notify-send "Frank" "Overlay is already running!" -i "$ICON" 2>/dev/null
    exit 0
fi

# Overlay not running - start it
cd "$SCRIPT_DIR"
nohup "$PYTHON" chat_overlay.py >> "$LOG_FILE" 2>&1 &

# Wait a moment and verify it started
sleep 2
if pgrep -f "python3.*chat_overlay.py" > /dev/null 2>&1; then
    notify-send "Frank" "Overlay started!" -i "$ICON" 2>/dev/null
else
    notify-send "Frank" "Error starting the overlay!" -i "$ICON" 2>/dev/null
fi
