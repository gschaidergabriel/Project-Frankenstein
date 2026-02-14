#!/bin/bash
# E-WISH Popup Launcher
# Usage: ./ewish_launcher.sh [--test] [--wish-id ID]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AICORE_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

export DISPLAY="${DISPLAY:-:0}"
export PYTHONPATH="$AICORE_ROOT:$PYTHONPATH"

cd "$AICORE_ROOT"

exec python3 -u "$SCRIPT_DIR/main_window.py" "$@"
