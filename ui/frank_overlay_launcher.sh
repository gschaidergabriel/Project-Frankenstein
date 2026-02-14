#!/bin/bash
# Frank Overlay Launcher - Fallback starter
# Only starts the overlay if it's not already running

OVERLAY_SCRIPT="/home/ai-core-node/aicore/opt/aicore/ui/chat_overlay.py"
LOG_FILE="/tmp/overlay.log"

# Check if overlay is already running
if pgrep -f "python3 chat_overlay.py" > /dev/null 2>&1; then
    # Overlay is running - try to bring window to focus
    wmctrl -a "Frank" 2>/dev/null || xdotool search --name "Frank" windowactivate 2>/dev/null
    notify-send "Frank" "Overlay läuft bereits!" -i /home/ai-core-node/.local/share/icons/hicolor/48x48/apps/frank-overlay.svg 2>/dev/null
    exit 0
fi

# Overlay not running - start it
cd /home/ai-core-node/aicore/opt/aicore/ui
nohup python3 chat_overlay.py >> "$LOG_FILE" 2>&1 &

# Wait a moment and verify it started
sleep 2
if pgrep -f "python3 chat_overlay.py" > /dev/null 2>&1; then
    notify-send "Frank" "Overlay gestartet!" -i /home/ai-core-node/.local/share/icons/hicolor/48x48/apps/frank-overlay.svg 2>/dev/null
else
    notify-send "Frank" "Fehler beim Starten des Overlays!" -i /home/ai-core-node/.local/share/icons/hicolor/48x48/apps/frank-overlay.svg 2>/dev/null
fi
