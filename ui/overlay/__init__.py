"""AI Core Chat Overlay — modularized package.

Usage:
    from overlay import ChatOverlay, main
    main()
"""

from __future__ import annotations

import sys

from overlay.constants import _check_singleton


def main():
    """Entry point — singleton check, then launch overlay."""
    if not _check_singleton():
        print("ERROR: Frank Overlay is already running!", file=sys.stderr)
        print("Kill existing instance first: pkill -f chat_overlay.py", file=sys.stderr)
        sys.exit(1)

    from overlay.app import ChatOverlay
    app = ChatOverlay()
    app.mainloop()
