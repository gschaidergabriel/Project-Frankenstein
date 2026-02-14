#!/bin/bash
# Toggle Neural Monitor Service - Start/Stop

SERVICE="frank-neural-monitor.service"

# Check if running
if systemctl --user is-active --quiet "$SERVICE"; then
    # Running - STOP it
    systemctl --user stop "$SERVICE"
    notify-send -i utilities-terminal "Neural Monitor" "Monitor gestoppt" 2>/dev/null
else
    # Not running - START it
    systemctl --user start "$SERVICE"
    notify-send -i utilities-terminal "Neural Monitor" "Monitor gestartet" 2>/dev/null
fi
