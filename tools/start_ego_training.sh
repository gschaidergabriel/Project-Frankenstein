#!/bin/bash
# Start EGO-CONSTRUCT Training Daemon

cd /home/ai-core-node/aicore/opt/aicore
export PYTHONPATH=/home/ai-core-node/aicore/opt/aicore

LOG_DIR="/home/ai-core-node/aicore/logs/ego_training"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/training_session_$(date +%Y%m%d_%H%M%S).log"

echo "Starting EGO-CONSTRUCT Training..."
echo "Log: $LOG_FILE"
echo "Duration: 2 hours"
echo ""

/home/ai-core-node/aicore/venv/bin/python -u -m tools.ego_training_daemon 2>&1 | tee "$LOG_FILE"
