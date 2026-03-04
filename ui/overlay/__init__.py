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

    # Enable faulthandler: dumps Python traceback to stderr on SIGSEGV/SIGFPE/SIGABRT.
    # This is critical for diagnosing C-level crashes in tkinter/Xlib.
    # Also write to a file so the traceback survives even if journald truncates.
    import faulthandler
    faulthandler.enable()
    try:
        from pathlib import Path as _FHPath
        _fh_dir = _FHPath.home() / ".local" / "share" / "frank" / "logs"
        _fh_dir.mkdir(parents=True, exist_ok=True)
        _fh_file = open(_fh_dir / "overlay_segv.log", "a")
        faulthandler.enable(file=_fh_file)
    except Exception:
        pass  # stderr fallback is fine

    from overlay.app import ChatOverlay
    app = ChatOverlay()
    app.mainloop()
