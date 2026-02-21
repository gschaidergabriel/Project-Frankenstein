#!/bin/bash
# F.A.S. Popup Launcher
# Startet das Feature Approval System Popup manuell

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$SCRIPT_DIR"

# Aktiviere Python-Umgebung falls vorhanden
VENV_DIR="${AICORE_BASE:-$HOME/aicore}/venv"
if [ -f "$VENV_DIR/bin/activate" ]; then
    source "$VENV_DIR/bin/activate"
fi

# Starte F.A.S. Popup im manuellen Modus
exec python3 -m ui.fas_popup.main_window --manual "$@"
