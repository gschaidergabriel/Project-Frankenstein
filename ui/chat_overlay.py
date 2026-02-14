#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI Core Chat Overlay — thin entry point.

The full implementation lives in the ``overlay`` package.
This file stays here for backward compatibility with systemd, scripts, and gaming_mode.
"""
import sys, os
from pathlib import Path

# Gaming mode lock check - exit immediately if gaming mode is active
_gaming_lock = Path("/tmp/frank_gaming_lock")
if _gaming_lock.exists():
    print("[Frank] Gaming mode active (lock file exists) - refusing to start", file=sys.stderr)
    sys.exit(0)

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
