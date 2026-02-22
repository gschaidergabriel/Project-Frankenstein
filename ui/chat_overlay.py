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
try:
    from config.paths import TEMP_FILES as _TEMP_FILES
    _gaming_lock = _TEMP_FILES["gaming_lock"]
except ImportError:
    _gaming_lock = Path("/tmp/frank/gaming_lock")
if _gaming_lock.exists():
    import subprocess as _sp
    try:
        _r = _sp.run(["systemctl", "--user", "is-active", "aicore-gaming-mode.service"],
                     capture_output=True, text=True, timeout=5)
        _daemon_active = _r.stdout.strip() == "active"
    except Exception:
        _daemon_active = False

    if _daemon_active:
        # Check state file for active gaming (covers all game types)
        _game_running = False
        try:
            _state_path = Path("/tmp/gaming_mode_state.json")
            if _state_path.exists():
                import json as _json_gm
                _gm_data = _json_gm.loads(_state_path.read_text())
                _game_running = _gm_data.get("active", False)
        except Exception:
            pass

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
try:
    from config.paths import TEMP_FILES as _TEMP_FILES2
    _user_closed = _TEMP_FILES2["user_closed"]
except ImportError:
    _user_closed = Path("/tmp/frank/user_closed")
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
