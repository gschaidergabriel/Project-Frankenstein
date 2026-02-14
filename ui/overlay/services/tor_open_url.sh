#!/bin/bash
# Open a URL in Tor Browser — xdotool + clipboard for running instance.
URL="$1"
[ -z "$URL" ] && exit 1

export DISPLAY="${DISPLAY:-:0}"
TB_DIR="/home/ai-core-node/.local/share/torbrowser/tbb/x86_64/tor-browser/Browser"

# Check if Tor Browser window exists
TB_WID=$(xdotool search --name "Tor Browser" 2>/dev/null | head -1)

if [ -n "$TB_WID" ]; then
    # Put URL in X clipboard via Python/tkinter (no xclip needed)
    python3 -c "
import sys, tkinter as tk
r = tk.Tk(); r.withdraw()
r.clipboard_clear()
r.clipboard_append(sys.argv[1])
r.update()
r.destroy()
" "$URL" 2>/dev/null

    # Open new tab and paste URL
    xdotool windowactivate --sync "$TB_WID"
    sleep 0.3
    xdotool key --window "$TB_WID" ctrl+t
    sleep 0.5
    xdotool key --window "$TB_WID" ctrl+l
    sleep 0.2
    xdotool key --window "$TB_WID" ctrl+v
    sleep 0.2
    xdotool key --window "$TB_WID" Return
else
    # Tor Browser not running — full launch
    cd "$TB_DIR" || exit 1
    exec ./start-tor-browser "$URL"
fi
