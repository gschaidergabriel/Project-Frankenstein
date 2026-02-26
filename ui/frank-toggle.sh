#!/bin/bash
# Toggle Frank overlay visibility.
# Usage: bind this to a keyboard shortcut (e.g. Super+F)
FRANK_TMP="${FRANK_TEMP_DIR:-/tmp/frank}"
mkdir -p "$FRANK_TMP"
touch "$FRANK_TMP/overlay_show"
