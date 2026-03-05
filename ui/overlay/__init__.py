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

    # File logging for overlay (crash diagnosis)
    try:
        from config.logging_config import setup_file_logging
        setup_file_logging("overlay")
    except Exception:
        pass

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

    try:
        from overlay.app import ChatOverlay
        app = ChatOverlay()
        app.mainloop()
    except Exception as exc:
        import traceback
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"FRANK OVERLAY CRASH: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        # Also write to crash log file for diagnosis
        try:
            from pathlib import Path as _CrashPath
            _crash_dir = _CrashPath.home() / ".local" / "share" / "frank" / "logs"
            _crash_dir.mkdir(parents=True, exist_ok=True)
            with open(_crash_dir / "overlay_crash.log", "a") as f:
                import datetime
                f.write(f"\n{'='*60}\n")
                f.write(f"CRASH at {datetime.datetime.now().isoformat()}\n")
                f.write(f"{type(exc).__name__}: {exc}\n")
                traceback.print_exc(file=f)
                f.write(f"{'='*60}\n")
        except Exception:
            pass
        sys.exit(1)
