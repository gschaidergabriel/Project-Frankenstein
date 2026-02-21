#!/bin/bash
# Start EGO-CONSTRUCT Training Daemon

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"
export PYTHONPATH="$SCRIPT_DIR"

LOG_DIR="${AICORE_LOG:-$HOME/.local/share/frank/logs}/ego_training"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/training_session_$(date +%Y%m%d_%H%M%S).log"

echo "Starting EGO-CONSTRUCT Training..."
echo "Log: $LOG_FILE"
echo "Duration: 2 hours"
echo ""

python3 -u -m tools.ego_training_daemon 2>&1 | tee "$LOG_FILE"
