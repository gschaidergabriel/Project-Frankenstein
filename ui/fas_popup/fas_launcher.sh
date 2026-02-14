#!/bin/bash
# F.A.S. Popup Launcher
# Startet das Feature Approval System Popup manuell

cd /home/ai-core-node/aicore/opt/aicore

# Aktiviere Python-Umgebung falls vorhanden
if [ -f "/home/ai-core-node/aicore/venv/bin/activate" ]; then
    source /home/ai-core-node/aicore/venv/bin/activate
fi

# Starte F.A.S. Popup im manuellen Modus
exec python3 -m ui.fas_popup.main_window --manual "$@"
