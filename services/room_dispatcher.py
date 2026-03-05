"""Room activity dispatcher — schedules solo room sessions + art generation.

Replaces entity_dispatcher.py.  Polls every 10 minutes, checks 7 gates,
picks a room or art block, runs the session.

Quotas:
  wellness:     3 sessions/day
  philosophy:   2 sessions/day
  art_studio:   2 sessions/day
  architecture: 2 sessions/day
  art_block:    5 paintings/day (separate, CPU-only)
  ─────────────────────────────────
  Total:        9 LLM sessions + 5 paintings per day
"""

from __future__ import annotations

import gc
import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

LOG = logging.getLogger("frank.room_dispatcher")

# ── Configuration ─────────────────────────────────────────────────────
POLL_INTERVAL = 600        # 10 min between idle checks
IDLE_THRESHOLD = 300       # 5 min user idle
CHAT_SILENCE_S = 300       # 5 min since last user message
GPU_MAX_LOAD = 0.50        # 50%
COOLDOWN_COMPLETED = 300   # 5 min after completed session
COOLDOWN_RETURNED = 600    # 10 min after user returned
COOLDOWN_SHORT = 60        # 1 min after lock/no_llm

COMPLETED_REASONS = frozenset({
    "completed", "time_limit", "max_turns", "error",
})

# ── Paths ─────────────────────────────────────────────────────────────
_UID = os.getuid()
RUNTIME_DIR = Path(f"/run/user/{_UID}/frank")
QUOTA_FILE = RUNTIME_DIR / "room_quotas.json"
PID_FILE = RUNTIME_DIR / "room_session.pid"
SILENCE_LOCK = Path("/tmp/frank/silence_active.lock")
GAMING_STATE = Path("/tmp/frank/gaming_mode_state.json")
WELLNESS_REQUEST = RUNTIME_DIR / "wellness_request.json"

CORE_HEALTH = "http://127.0.0.1:8088/health"
ROUTER_HEALTH = "http://127.0.0.1:8091/health"

# ── Globals ───────────────────────────────────────────────────────────
_shutdown = False


def _handle_signal(signum, _frame):
    global _shutdown
    LOG.info("signal %d — shutting down", signum)
    _shutdown = True


# ═══════════════════════════════════════════════════════════════════════
#  Quota Management
# ═══════════════════════════════════════════════════════════════════════

def _load_or_reset_quotas() -> dict:
    """Load quotas from file, reset if date changed."""
    today = date.today().isoformat()
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    if QUOTA_FILE.exists():
        try:
            q = json.loads(QUOTA_FILE.read_text())
            if q.get("date") == today:
                # Ensure all rooms present
                for key in ("wellness", "philosophy", "art_studio", "architecture", "art_block"):
                    q["completed"].setdefault(key, 0)
                    q["last_session"].setdefault(key, 0.0)
                return q
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    q = {
        "date": today,
        "completed": {k: 0 for k in ("wellness", "philosophy", "art_studio", "architecture", "art_block")},
        "last_session": {k: 0.0 for k in ("wellness", "philosophy", "art_studio", "architecture", "art_block")},
    }
    _save_quotas(q)
    return q


def _save_quotas(q: dict):
    QUOTA_FILE.write_text(json.dumps(q, indent=2))


def _get_eligible_rooms(quotas: dict) -> List[str]:
    """Return rooms that still have quota today."""
    from services.room_session import ROOMS
    eligible = []
    for key, cfg in ROOMS.items():
        done = quotas["completed"].get(key, 0)
        if done < cfg["daily_quota"]:
            eligible.append(key)
    return eligible


def _pick_next_room(eligible: List[str], quotas: dict) -> str:
    """Pick the best room: zero-done first, then longest-waiting."""
    # Priority 1: rooms with 0 sessions today
    zero_done = [r for r in eligible if quotas["completed"].get(r, 0) == 0]
    if zero_done:
        zero_done.sort(key=lambda r: quotas["last_session"].get(r, 0.0))
        return zero_done[0]

    # Priority 2: longest wait
    eligible.sort(key=lambda r: quotas["last_session"].get(r, 0.0))
    return eligible[0]


def _is_art_eligible(quotas: dict) -> bool:
    """Check if art generation has budget today."""
    from services.room_session import ART_DAILY_BUDGET
    return quotas["completed"].get("art_block", 0) < ART_DAILY_BUDGET


# ═══════════════════════════════════════════════════════════════════════
#  Gate Checks (7 gates, all must pass)
# ═══════════════════════════════════════════════════════════════════════

def _get_xprintidle_s() -> float:
    try:
        r = subprocess.run(
            ["xprintidle"], capture_output=True, text=True, timeout=2,
            env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
        )
        if r.returncode == 0:
            return int(r.stdout.strip()) / 1000.0
    except Exception:
        pass
    return 999.0


def _check_idle() -> bool:
    idle = _get_xprintidle_s()
    if idle < IDLE_THRESHOLD:
        LOG.debug("gate FAIL: idle=%.0fs < %ds", idle, IDLE_THRESHOLD)
        return False
    return True


def _check_chat_silence() -> bool:
    try:
        db_path = Path.home() / ".local" / "share" / "frank" / "db" / "chat_memory.db"
        if not db_path.exists():
            return True
        import sqlite3
        conn = sqlite3.connect(str(db_path), timeout=5)
        row = conn.execute(
            "SELECT MAX(timestamp) FROM messages WHERE role='user'"
        ).fetchone()
        conn.close()
        if row and row[0]:
            elapsed = time.time() - float(row[0])
            if elapsed < CHAT_SILENCE_S:
                LOG.debug("gate FAIL: chat_silence=%.0fs < %ds", elapsed, CHAT_SILENCE_S)
                return False
    except Exception:
        pass
    return True


def _check_not_gaming() -> bool:
    # Primary: JSON state file
    if GAMING_STATE.exists():
        try:
            state = json.loads(GAMING_STATE.read_text())
            if state.get("active", False):
                LOG.debug("gate FAIL: gaming mode active")
                return False
        except Exception:
            pass

    # Fallback: process check
    game_patterns = ["steamapps/common", "OldUnreal/UT", "lutris-wrapper"]
    for pat in game_patterns:
        try:
            r = subprocess.run(
                ["pgrep", "-f", pat], capture_output=True, timeout=3)
            if r.returncode == 0:
                LOG.debug("gate FAIL: game process detected (%s)", pat)
                return False
        except Exception:
            pass
    return True


def _check_gpu_load() -> bool:
    try:
        drm = Path("/sys/class/drm")
        for card in drm.iterdir():
            vendor_path = card / "device" / "vendor"
            busy_path = card / "device" / "gpu_busy_percent"
            if vendor_path.exists() and busy_path.exists():
                vendor = vendor_path.read_text().strip()
                if vendor == "0x1002":  # AMD
                    load = int(busy_path.read_text().strip()) / 100.0
                    if load >= GPU_MAX_LOAD:
                        LOG.debug("gate FAIL: gpu_load=%.0f%% >= %.0f%%",
                                  load * 100, GPU_MAX_LOAD * 100)
                        return False
                    return True
    except Exception:
        pass
    return True


def _check_no_pid_locks() -> bool:
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
            LOG.debug("gate FAIL: session PID %d alive", pid)
            return False
        except (ProcessLookupError, ValueError, OSError):
            PID_FILE.unlink(missing_ok=True)
    return True


def _check_services_healthy() -> bool:
    import urllib.request
    import urllib.error
    for url in (CORE_HEALTH, ROUTER_HEALTH):
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5):
                pass
        except Exception:
            LOG.debug("gate FAIL: service unhealthy %s", url)
            return False
    return True


def _check_not_in_silence() -> bool:
    if SILENCE_LOCK.exists():
        try:
            age = time.time() - SILENCE_LOCK.stat().st_mtime
            if age < 7200:  # 2h max
                LOG.debug("gate FAIL: silence mode active (%.0fs old)", age)
                return False
            SILENCE_LOCK.unlink(missing_ok=True)
        except Exception:
            pass
    return True


def _all_gates_pass() -> bool:
    gates = [
        ("idle", _check_idle),
        ("chat_silence", _check_chat_silence),
        ("not_gaming", _check_not_gaming),
        ("silence_mode", _check_not_in_silence),
        ("gpu_load", _check_gpu_load),
        ("no_pid_locks", _check_no_pid_locks),
        ("services_healthy", _check_services_healthy),
    ]
    for name, check in gates:
        if not check():
            return False
    return True


# ═══════════════════════════════════════════════════════════════════════
#  Emergency Wellness
# ═══════════════════════════════════════════════════════════════════════

def _check_emergency_wellness(eligible: List[str]) -> bool:
    """Check if consciousness daemon requested emergency wellness session."""
    if not WELLNESS_REQUEST.exists():
        return False
    try:
        data = json.loads(WELLNESS_REQUEST.read_text())
        age = time.time() - data.get("timestamp", 0)
        WELLNESS_REQUEST.unlink(missing_ok=True)
        if age > 3600:
            LOG.debug("stale wellness request (%.0fs old)", age)
            return False
        if "wellness" not in eligible:
            LOG.warning("emergency wellness requested but quota exhausted")
            return False
        LOG.warning("EMERGENCY WELLNESS: %s", data.get("reason", "unknown"))
        return True
    except Exception:
        WELLNESS_REQUEST.unlink(missing_ok=True)
        return False


# ═══════════════════════════════════════════════════════════════════════
#  Session Execution
# ═══════════════════════════════════════════════════════════════════════

def _run_room(room_key: str) -> str:
    """Import and run a room session.  Returns exit_reason."""
    from services.room_session import run_room_session
    try:
        exit_reason = run_room_session(room_key)
    except Exception as e:
        LOG.exception("room session crashed: %s", e)
        exit_reason = "error"
    finally:
        gc.collect()
    return exit_reason


def _run_art() -> Optional[str]:
    """Run a single art generation block.  Returns file path or None."""
    from services.room_session import run_art_block
    try:
        return run_art_block()
    except Exception as e:
        LOG.exception("art block crashed: %s", e)
        return None
    finally:
        gc.collect()


# ═══════════════════════════════════════════════════════════════════════
#  Notification Helper
# ═══════════════════════════════════════════════════════════════════════

def _notify(action: str, detail: str = "", category: str = "entity"):
    try:
        from services.autonomous_notify import notify_autonomous
        notify_autonomous(action, detail, category=category, source="room_dispatcher")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════
#  Interruptible Sleep
# ═══════════════════════════════════════════════════════════════════════

def _shutdown_sleep(seconds: float):
    """Sleep in 5s chunks, checking _shutdown between chunks."""
    remaining = seconds
    while remaining > 0 and not _shutdown:
        time.sleep(min(5.0, remaining))
        remaining -= 5.0


# ═══════════════════════════════════════════════════════════════════════
#  Main Loop
# ═══════════════════════════════════════════════════════════════════════

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    LOG.info("room dispatcher starting (PID %d, poll=%ds)", os.getpid(), POLL_INTERVAL)

    while not _shutdown:
        # ── Load quotas ──
        quotas = _load_or_reset_quotas()

        # ── Check eligible rooms ──
        eligible = _get_eligible_rooms(quotas)
        art_eligible = _is_art_eligible(quotas)

        if not eligible and not art_eligible:
            LOG.info("all quotas exhausted for today, sleeping until midnight")
            now = time.localtime()
            secs_to_midnight = (24 - now.tm_hour) * 3600 - now.tm_min * 60 - now.tm_sec
            _shutdown_sleep(min(secs_to_midnight + 60, POLL_INTERVAL * 6))
            continue

        # ── Emergency wellness check ──
        emergency = _check_emergency_wellness(eligible)

        # ── Gate checks ──
        if not _all_gates_pass():
            _shutdown_sleep(POLL_INTERVAL)
            continue

        # ── Pick activity ──
        if emergency:
            room_key = "wellness"
            LOG.info("emergency wellness session triggered")
        elif eligible:
            # Art blocks: interleave with room sessions
            # Run art block if: art eligible AND (no rooms eligible OR ~30% chance)
            if art_eligible and (not eligible or (len(eligible) > 0 and time.time() % 10 < 3)):
                # Run art block
                LOG.info("running art block (%d done today)",
                         quotas["completed"].get("art_block", 0))
                path = _run_art()
                if path:
                    quotas["completed"]["art_block"] = quotas["completed"].get("art_block", 0) + 1
                    quotas["last_session"]["art_block"] = time.time()
                    _save_quotas(quotas)
                _shutdown_sleep(COOLDOWN_SHORT)
                continue

            room_key = _pick_next_room(eligible, quotas)
        elif art_eligible:
            LOG.info("only art blocks remaining, running art block")
            path = _run_art()
            if path:
                quotas["completed"]["art_block"] = quotas["completed"].get("art_block", 0) + 1
                quotas["last_session"]["art_block"] = time.time()
                _save_quotas(quotas)
            _shutdown_sleep(COOLDOWN_SHORT)
            continue
        else:
            _shutdown_sleep(POLL_INTERVAL)
            continue

        # ── Run room session ──
        from services.room_session import ROOMS
        display = ROOMS[room_key]["display"]
        LOG.info("starting %s session (%d/%d today)",
                 display,
                 quotas["completed"].get(room_key, 0) + 1,
                 ROOMS[room_key]["daily_quota"])

        exit_reason = _run_room(room_key)

        # ── Update quotas based on exit reason ──
        if exit_reason.startswith("user_returned"):
            LOG.info("session interrupted: %s — cooldown %ds", exit_reason, COOLDOWN_RETURNED)
            _shutdown_sleep(COOLDOWN_RETURNED)

        elif exit_reason.startswith("shutdown"):
            LOG.info("shutdown signal during session")
            break

        elif exit_reason in ("pid_lock", "no_llm", "aborted"):
            LOG.info("session never started: %s — short cooldown", exit_reason)
            _shutdown_sleep(COOLDOWN_SHORT)

        elif exit_reason in COMPLETED_REASONS:
            quotas["completed"][room_key] = quotas["completed"].get(room_key, 0) + 1
            quotas["last_session"][room_key] = time.time()
            _save_quotas(quotas)
            LOG.info("session completed: %s — cooldown %ds", exit_reason, COOLDOWN_COMPLETED)
            _shutdown_sleep(COOLDOWN_COMPLETED)

        else:
            LOG.warning("unknown exit reason: %s — conservative cooldown", exit_reason)
            _shutdown_sleep(COOLDOWN_COMPLETED)

    LOG.info("room dispatcher shutting down gracefully")


if __name__ == "__main__":
    main()
