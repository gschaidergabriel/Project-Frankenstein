#!/bin/bash
# Toggle Frank Overlay visibility
# Bind this to Super+F or another hotkey in your desktop settings
#
# Usage: ./toggle_overlay.sh [show|hide|toggle]
#   show   - Force show the overlay
#   hide   - Force hide the overlay
#   toggle - Toggle visibility (default)

ACTION="${1:-toggle}"
RESTORE_FILE="/tmp/frank_overlay_show"

show_overlay() {
    # Touch the restore signal file - the overlay will detect this and show itself
    touch "$RESTORE_FILE"

    # Also try xdotool as backup
    WINDOW_ID=$(DISPLAY=:0 xdotool search --name "F.R.A.N.K." 2>/dev/null | head -1)
    if [ -n "$WINDOW_ID" ]; then
        DISPLAY=:0 xdotool windowmap "$WINDOW_ID" 2>/dev/null
        DISPLAY=:0 xdotool windowraise "$WINDOW_ID" 2>/dev/null
        DISPLAY=:0 xdotool windowactivate "$WINDOW_ID" 2>/dev/null
    fi
    echo "Frank overlay shown"
}

hide_overlay() {
    WINDOW_ID=$(DISPLAY=:0 xdotool search --name "F.R.A.N.K." 2>/dev/null | head -1)
    if [ -n "$WINDOW_ID" ]; then
        DISPLAY=:0 xdotool windowunmap "$WINDOW_ID" 2>/dev/null
        echo "Frank overlay hidden"
    else
        echo "Frank overlay not found"
    fi
}

# Check if overlay is running
WINDOW_ID=$(DISPLAY=:0 xdotool search --name "F.R.A.N.K." 2>/dev/null | head -1)

if [ -z "$WINDOW_ID" ]; then
    echo "Frank overlay not running, starting it..."
    systemctl --user start frank-overlay.service
    sleep 2
    show_overlay
    exit 0
fi

case "$ACTION" in
    show)
        show_overlay
        ;;
    hide)
        hide_overlay
        ;;
    toggle)
        # Check if window is mapped (visible)
        MAP_STATE=$(DISPLAY=:0 xwininfo -id "$WINDOW_ID" 2>/dev/null | grep "Map State" | awk '{print $3}')

        if [ "$MAP_STATE" = "IsUnMapped" ] || [ "$MAP_STATE" = "IsUnviewable" ]; then
            show_overlay
        else
            hide_overlay
        fi
        ;;
    *)
        echo "Usage: $0 [show|hide|toggle]"
        exit 1
        ;;
esac
