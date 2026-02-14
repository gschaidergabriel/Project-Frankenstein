#!/bin/bash
# Start Frank Writer

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AICORE_DIR="$(dirname "$SCRIPT_DIR")"
VENV_SITE="$(dirname "$AICORE_DIR")/venv/lib/python3.12/site-packages"

# Set environment — use system Python (gi/GTK4 not in venv)
export DISPLAY="${DISPLAY:-:0}"
export GDK_BACKEND=x11
export PYTHONPATH="$AICORE_DIR:$VENV_SITE"

cd "$SCRIPT_DIR"

# Tell watchdog NOT to restart overlay while Writer is open
echo '{"reason":"frank-writer active","timestamp":"'"$(date -Iseconds)"'"}' > /tmp/frank_user_closed

# Stop overlay
systemctl --user stop frank-overlay.service 2>/dev/null || true
pkill -f chat_overlay.py 2>/dev/null || true
rm -f /tmp/frank_overlay.lock

# Start writer with system Python (has gi/GTK4 bindings)
/usr/bin/python3 app.py "$@"

# Writer closed — clear watchdog block and restart overlay
rm -f /tmp/frank_user_closed /tmp/frank_overlay.lock
systemctl --user start frank-overlay.service 2>/dev/null || true
