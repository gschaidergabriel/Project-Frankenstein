#!/usr/bin/env python3
"""
Companion Scheduler — Idle-gated entry point for Raven sessions.
==================================================================

Called by systemd timer 1x/day (18:00 ± 30min jitter).
Runs gate checks before launching a session. If any gate fails, exits silently.

Gates:
1. PID lock not held (no concurrent companion session)
2. No Dr. Hibbert session running (prevent overlap)
3. No Kairos session running (prevent overlap)
4. xprintidle >= 300s (5 min idle)
5. Last user-Frank chat >= 300s ago
6. Not gaming
7. GPU load < 50%
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

# Path setup
_AICORE_ROOT = Path(__file__).resolve().parent.parent
if str(_AICORE_ROOT) not in sys.path:
    sys.path.insert(0, str(_AICORE_ROOT))

try:
    from config.paths import get_db, AICORE_LOG, RUNTIME_DIR
    CHAT_DB = get_db("chat_memory")
    LOG_DIR = AICORE_LOG
except ImportError:
    _data = Path.home() / ".local" / "share" / "frank"
    CHAT_DB = _data / "db" / "chat_memory.db"
    LOG_DIR = _data / "logs"
    RUNTIME_DIR = Path(f"/run/user/{os.getuid()}/frank")

LOG_DIR = Path(LOG_DIR)
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "companion_scheduler.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
LOG = logging.getLogger("companion_scheduler")

# Gate thresholds
IDLE_MIN_S = 300
CHAT_SILENCE_S = 300
GPU_MAX_LOAD = 0.50
PID_FILE = RUNTIME_DIR / "companion_agent.pid"
THERAPIST_PID_FILE = RUNTIME_DIR / "therapist_agent.pid"
MIRROR_PID_FILE = RUNTIME_DIR / "mirror_agent.pid"
ATLAS_PID_FILE = RUNTIME_DIR / "atlas_agent.pid"
MUSE_PID_FILE = RUNTIME_DIR / "muse_agent.pid"


def _check_pid_lock() -> bool:
    """Return True if NO companion session is running."""
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
            LOG.info("Gate FAIL: PID lock held by %d", pid)
            return False
        except (ProcessLookupError, ValueError):
            PID_FILE.unlink(missing_ok=True)
    return True


def _check_no_other_agents() -> bool:
    """Return True if NO other agent session is running (prevent overlap)."""
    for name, pid_file in [("Dr. Hibbert", THERAPIST_PID_FILE),
                            ("Kairos", MIRROR_PID_FILE),
                            ("Atlas", ATLAS_PID_FILE),
                            ("Echo", MUSE_PID_FILE)]:
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                os.kill(pid, 0)
                LOG.info("Gate FAIL: %s session running (PID %d)", name, pid)
                return False
            except (ProcessLookupError, ValueError):
                pass
    return True


def _check_idle() -> bool:
    """Return True if user idle >= IDLE_MIN_S."""
    try:
        result = subprocess.run(
            ["xprintidle"],
            capture_output=True, text=True, timeout=2,
            env={**os.environ, "DISPLAY": ":0"},
        )
        if result.returncode == 0:
            idle_s = int(result.stdout.strip()) / 1000.0
            if idle_s < IDLE_MIN_S:
                LOG.info("Gate FAIL: User active (idle=%.0fs < %ds)", idle_s, IDLE_MIN_S)
                return False
            return True
    except Exception as e:
        LOG.warning("xprintidle failed: %s (assuming idle)", e)
    return True


def _check_chat_silence() -> bool:
    """Return True if last user chat >= CHAT_SILENCE_S ago."""
    try:
        conn = sqlite3.connect(str(CHAT_DB), timeout=5)
        row = conn.execute(
            "SELECT MAX(timestamp) as last_ts FROM messages WHERE is_user = 1"
        ).fetchone()
        conn.close()
        if row and row[0]:
            silence = time.time() - row[0]
            if silence < CHAT_SILENCE_S:
                LOG.info("Gate FAIL: Recent chat (%.0fs < %ds ago)", silence, CHAT_SILENCE_S)
                return False
    except Exception as e:
        LOG.warning("Chat silence check failed: %s (allowing)", e)
    return True


def _check_not_gaming() -> bool:
    """Return True if NOT gaming."""
    try:
        try:
            from config.paths import get_temp
            state_file = get_temp("gaming_mode_state.json")
        except ImportError:
            state_file = Path("/tmp/frank/gaming_mode_state.json")
        if state_file.exists():
            data = json.loads(state_file.read_text())
            if data.get("active", False):
                LOG.info("Gate FAIL: Gaming mode active")
                return False
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["pgrep", "-f", "steamapps/common"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0 and result.stdout.strip():
            LOG.info("Gate FAIL: Steam game running")
            return False
    except Exception:
        pass

    return True


def _check_gpu_load() -> bool:
    """Return True if GPU load < GPU_MAX_LOAD."""
    try:
        drm = Path("/sys/class/drm")
        for card in drm.glob("card*"):
            device = card / "device"
            vendor = device / "vendor"
            if vendor.exists() and vendor.read_text().strip() == "0x1002":
                busy = (device / "gpu_busy_percent").read_text().strip()
                load = float(busy) / 100.0
                if load >= GPU_MAX_LOAD:
                    LOG.info("Gate FAIL: GPU load %.0f%% >= %.0f%%",
                             load * 100, GPU_MAX_LOAD * 100)
                    return False
                return True
    except Exception as e:
        LOG.warning("GPU load check failed: %s (allowing)", e)
    return True


def main():
    LOG.info("Companion scheduler triggered.")

    gates = [
        ("pid_lock", _check_pid_lock),
        ("no_other_agents", _check_no_other_agents),
        ("idle", _check_idle),
        ("chat_silence", _check_chat_silence),
        ("not_gaming", _check_not_gaming),
        ("gpu_load", _check_gpu_load),
    ]

    for name, check in gates:
        if not check():
            LOG.info("Scheduler exit: gate '%s' failed.", name)
            sys.exit(0)

    LOG.info("All gates passed. Starting Raven session...")

    from ext.companion_agent import run
    run()


if __name__ == "__main__":
    main()
