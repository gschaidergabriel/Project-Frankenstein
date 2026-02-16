#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI Core Chat Overlay — thin entry point.

The full implementation lives in the ``overlay`` package.
This file stays here for backward compatibility with systemd, scripts, and gaming_mode.
"""
import sys, os
from pathlib import Path

# ── Startup gate: gaming mode ──────────────────────────────────────────
# Verify gaming daemon is ACTUALLY running + game detected.
# Stale lock files are auto-removed instead of blocking forever.
_gaming_lock = Path("/tmp/frank_gaming_lock")
if _gaming_lock.exists():
    import subprocess as _sp
    try:
        _r = _sp.run(["systemctl", "--user", "is-active", "aicore-gaming-mode.service"],
                     capture_output=True, text=True, timeout=5)
        _daemon_active = _r.stdout.strip() == "active"
    except Exception:
        _daemon_active = False

    if _daemon_active:
        try:
            _g = _sp.run(["pgrep", "-f", "SteamLaunch AppId|reaper SteamLaunch"],
                         capture_output=True, text=True, timeout=5)
            _game_running = _g.returncode == 0
        except Exception:
            _game_running = False

        if _game_running:
            print("[Frank] Gaming mode active (daemon running + game detected) - refusing to start",
                  file=sys.stderr)
            sys.exit(0)

    # Lock file is stale — gaming daemon not active or no game running. Remove it.
    print("[Frank] Stale gaming lock file detected — removing and starting normally", file=sys.stderr)
    try:
        _gaming_lock.unlink(missing_ok=True)
    except Exception:
        pass

# ── Clear stale user_closed signal ──────────────────────────────────────
# If we got here, we ARE supposed to start. Remove any leftover signal
# from previous crashes, gaming mode exits, or writer sessions.
_user_closed = Path("/tmp/frank_user_closed")
if _user_closed.exists():
    print("[Frank] Clearing stale user_closed signal — overlay is starting", file=sys.stderr)
    try:
        _user_closed.unlink(missing_ok=True)
    except Exception:
        pass

# Add ui directory for overlay package
sys.path.insert(0, os.path.dirname(__file__))

# Add opt/aicore for agentic module
try:
    from config.paths import AICORE_ROOT as _opt_aicore
    _opt_aicore = str(_opt_aicore)
except ImportError:
    _opt_aicore = str(Path(__file__).resolve().parents[1])  # ui/ -> opt/aicore
if _opt_aicore not in sys.path:
    sys.path.insert(0, _opt_aicore)

from overlay import main
main()
