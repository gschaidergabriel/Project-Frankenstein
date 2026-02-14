#!/bin/bash
# Start Frank Writer

cd /home/ai-core-node/aicore/opt/aicore/writer

# Set environment — use system Python (gi/GTK4 not in venv)
export DISPLAY=:0
export GDK_BACKEND=x11
export PYTHONPATH=/home/ai-core-node/aicore/opt/aicore:/home/ai-core-node/aicore/venv/lib/python3.12/site-packages

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
