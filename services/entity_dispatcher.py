#!/usr/bin/env python3
"""
Entity Session Dispatcher — Idle-driven scheduler for all Frank entities.
=========================================================================

Replaces individual systemd timers with a single persistent service that:
- Polls for idle opportunities every 60 s
- Manages daily session quotas per entity (no stacking across days)
- Runs ONE session at a time (serial, no collision)
- Distinguishes user_returned (doesn't count) from completed sessions
- Weighted round-robin selection: entities with 0 sessions get priority

Entities:
  therapist  (Dr. Hibbert)   — 3 sessions/day
  mirror     (Kairos)        — 1 session/day
  atlas      (Atlas)         — 1 session/day
  muse       (Echo)          — 1 session/day

Usage:
  systemctl --user start aicore-entities.service
"""

from __future__ import annotations

import datetime
import importlib
import json
import logging
import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

# ── Path setup ──────────────────────────────────────────────────────────
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

LOG = logging.getLogger("entity_dispatcher")
LOG.setLevel(logging.INFO)
LOG.propagate = False  # Cycle 5 D-5: prevent double-logging via root propagation
if not LOG.handlers:
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    _fh = logging.FileHandler(LOG_DIR / "entity_dispatcher.log", encoding="utf-8")
    _fh.setFormatter(_fmt)
    LOG.addHandler(_fh)
    _sh = logging.StreamHandler()
    _sh.setFormatter(_fmt)
    LOG.addHandler(_sh)


def _entity_notify(action: str, detail: str = "") -> None:
    """Fire-and-forget overlay notification."""
    try:
        from services.autonomous_notify import notify_autonomous
        notify_autonomous(action, detail, category="entity",
                          source="entity_dispatcher")
    except Exception:
        pass


# ── Configuration ───────────────────────────────────────────────────────

DAILY_QUOTAS: dict[str, int] = {
    "therapist": 6,
    "mirror":    1,
    "atlas":     1,
    "muse":      1,
}

ENTITY_MODULES: dict[str, str] = {
    "therapist": "ext.therapist_agent",
    "mirror":    "ext.mirror_agent",
    "atlas":     "ext.atlas_agent",
    "muse":      "ext.muse_agent",
}

ENTITY_DISPLAY: dict[str, str] = {
    "therapist": "Dr. Hibbert",
    "mirror":    "Kairos",
    "atlas":     "Atlas",
    "muse":      "Echo",
}

PID_FILES: dict[str, Path] = {
    "therapist": RUNTIME_DIR / "therapist_agent.pid",
    "mirror":    RUNTIME_DIR / "mirror_agent.pid",
    "atlas":     RUNTIME_DIR / "atlas_agent.pid",
    "muse":      RUNTIME_DIR / "muse_agent.pid",
}

POLL_INTERVAL      = 600   # 10 min between idle checks
COOLDOWN_COMPLETED = 300   # 5 min after a completed session
COOLDOWN_RETURNED  = 600   # 10 min after user_returned
IDLE_THRESHOLD     = 300   # 5 min idle required before starting
CHAT_SILENCE_S     = 300   # 5 min since last user chat
GPU_MAX_LOAD       = 0.50  # 50% GPU threshold

QUOTA_FILE = RUNTIME_DIR / "entity_quotas.json"
THERAPY_REQUEST_FILE = RUNTIME_DIR / "therapy_request.json"

# Exit reasons that count as "session completed"
COMPLETED_REASONS = frozenset({
    "time_limit", "max_turns",
    "sustained_positive", "creative_flow",
    "sustained_evasion", "sustained_flatness",
    "error",
})

# Graceful shutdown flag
_shutdown = False


def _handle_signal(signum, _frame):
    global _shutdown
    LOG.info("Received signal %d, shutting down...", signum)
    _shutdown = True


def _shutdown_sleep(seconds: float):
    """Sleep in 5s chunks, checking _shutdown between chunks."""
    remaining = seconds
    while remaining > 0 and not _shutdown:
        time.sleep(min(5.0, remaining))
        remaining -= 5.0


# ── Quota Management ───────────────────────────────────────────────────

def load_or_reset_quotas() -> dict:
    """Load quotas from disk; reset if new day or missing."""
    today = datetime.date.today().isoformat()
    try:
        if QUOTA_FILE.exists():
            data = json.loads(QUOTA_FILE.read_text(encoding="utf-8"))
            if data.get("date") == today:
                # Ensure all entities exist (in case new ones added)
                for ent in DAILY_QUOTAS:
                    data["completed"].setdefault(ent, 0)
                return data
    except Exception as e:
        LOG.warning("Failed to read quota file: %s", e)

    # New day or missing/corrupt → fresh quotas
    data = {
        "date": today,
        "completed": {ent: 0 for ent in DAILY_QUOTAS},
        "last_session": {},  # entity → timestamp of last completed session
    }
    save_quotas(data)
    LOG.info("Quotas reset for %s", today)
    return data


def save_quotas(data: dict) -> None:
    """Persist quota state to disk."""
    try:
        QUOTA_FILE.parent.mkdir(parents=True, exist_ok=True)
        QUOTA_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        LOG.error("Failed to save quotas: %s", e)


def get_eligible_entities(quotas: dict) -> list[str]:
    """Return entities that still have remaining quota today."""
    eligible = []
    for ent, max_sessions in DAILY_QUOTAS.items():
        done = quotas["completed"].get(ent, 0)
        if done < max_sessions:
            eligible.append(ent)
    return eligible


def pick_next_entity(eligible: list[str], quotas: dict) -> str:
    """
    Weighted round-robin selection:
    1. Entities with 0 completed sessions today go first
    2. Among those, sort by last_session_time ascending (longest wait first)
    3. If all single-session entities are done, Dr. Hibbert fills remaining slots
    """
    last_sessions = quotas.get("last_session", {})

    # Split into "never run today" vs "partially run"
    zero_done = [e for e in eligible if quotas["completed"].get(e, 0) == 0]
    partial   = [e for e in eligible if e not in zero_done]

    if zero_done:
        # Sort by last session time (oldest first); never-run entities sort first
        zero_done.sort(key=lambda e: last_sessions.get(e, 0))
        return zero_done[0]

    if partial:
        # All entities have had at least one session; pick longest-waiting
        partial.sort(key=lambda e: last_sessions.get(e, 0))
        return partial[0]

    # Should never reach here if eligible is non-empty
    return eligible[0]


# ── Gate Checks ────────────────────────────────────────────────────────

def _check_idle() -> bool:
    """Return True if user idle >= IDLE_THRESHOLD."""
    try:
        result = subprocess.run(
            ["xprintidle"],
            capture_output=True, text=True, timeout=2,
            env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
        )
        if result.returncode == 0:
            idle_s = int(result.stdout.strip()) / 1000.0
            if idle_s < IDLE_THRESHOLD:
                LOG.debug("Gate FAIL: User active (idle=%.0fs < %ds)", idle_s, IDLE_THRESHOLD)
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
                LOG.debug("Gate FAIL: Recent chat (%.0fs < %ds ago)", silence, CHAT_SILENCE_S)
                return False
    except Exception as e:
        LOG.warning("Chat silence check failed: %s (allowing)", e)
    return True


def _check_not_gaming() -> bool:
    """Return True if NOT gaming."""
    # Primary check: gaming mode state file (covers all game types)
    try:
        try:
            from config.paths import TEMP_FILES
            state_file = TEMP_FILES["gaming_mode_state"]
        except ImportError:
            state_file = Path("/tmp/frank/gaming_mode_state.json")
        if state_file.exists():
            data = json.loads(state_file.read_text())
            if data.get("active", False):
                LOG.debug("Gate FAIL: Gaming mode active (%s)",
                          data.get("game_name", "unknown"))
                return False
    except Exception:
        pass

    # Fallback: check for game processes directly (in case daemon isn't running)
    _game_indicators = ["steamapps/common", "OldUnreal/UT", "lutris-wrapper"]
    for pattern in _game_indicators:
        try:
            result = subprocess.run(
                ["pgrep", "-f", pattern],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0 and result.stdout.strip():
                LOG.debug("Gate FAIL: Game process detected (%s)", pattern)
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
                    LOG.debug("Gate FAIL: GPU load %.0f%% >= %.0f%%",
                              load * 100, GPU_MAX_LOAD * 100)
                    return False
                return True
    except Exception as e:
        LOG.warning("GPU load check failed: %s (allowing)", e)
    return True


def _check_no_pid_locks() -> bool:
    """Return True if no entity PID locks are held (safety net)."""
    for ent, pid_file in PID_FILES.items():
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                os.kill(pid, 0)
                LOG.info("Gate FAIL: %s PID lock held by %d",
                         ENTITY_DISPLAY.get(ent, ent), pid)
                return False
            except (ProcessLookupError, ValueError):
                pid_file.unlink(missing_ok=True)
    return True


def _check_services_healthy() -> bool:
    """Return True if Core (8088) and Router (8091) are responding."""
    import urllib.request
    for name, port in [("Core", 8088), ("Router", 8091)]:
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/health",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=3):
                pass
        except Exception:
            LOG.debug("Gate FAIL: %s (port %d) not responding", name, port)
            return False
    return True


def _check_not_in_silence() -> bool:
    """Return True if consciousness is NOT in silence mode."""
    lock = Path("/tmp/frank/silence_active.lock")
    if lock.exists():
        try:
            import json as _json
            data = _json.loads(lock.read_text())
            # Check if silence has expired
            import time as _time
            elapsed = _time.time() - data.get("start", 0)
            if elapsed < data.get("duration", 1800):
                LOG.debug("Gate FAIL: Silence mode active (%.0fs remaining)",
                          data["duration"] - elapsed)
                return False
            # Expired — clean up stale lock
            lock.unlink()
        except Exception:
            pass
    return True


def all_gates_pass() -> bool:
    """Run all gate checks; return True if all pass."""
    gates = [
        ("idle",             _check_idle),
        ("chat_silence",     _check_chat_silence),
        ("not_gaming",       _check_not_gaming),
        ("silence_mode",     _check_not_in_silence),
        ("gpu_load",         _check_gpu_load),
        ("no_pid_locks",     _check_no_pid_locks),
        ("services_healthy", _check_services_healthy),
    ]
    for name, check in gates:
        if not check():
            return False
    return True


# ── Session Runner ─────────────────────────────────────────────────────

def _eb_get_mood() -> float:
    """Experiential Bridge: get current mood from consciousness.db."""
    try:
        from config.paths import get_db
        cons_db = get_db("consciousness")
        conn = sqlite3.connect(str(cons_db), timeout=2)
        try:
            row = conn.execute(
                "SELECT mood_value FROM mood_trajectory ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else 0.0
        finally:
            conn.close()
    except Exception:
        return 0.0


def _eb_record_entity_experience(entity: str, display: str,
                                  pre_mood: float, pre_ts: float,
                                  exit_reason: str):
    """Experiential Bridge: record entity session as experience.

    Direct SQLite writes — does NOT import ConsciousnessDaemon (cross-process safe).
    """
    try:
        from config.paths import get_db, AICORE_LOG
        post_mood = _eb_get_mood()
        duration_min = max(1, int((time.time() - pre_ts) / 60))
        success = exit_reason not in ("error", "crashed", "timeout")

        # Try to get session summary from entity-specific logs (tail only)
        summary = ""
        try:
            log_file = Path(AICORE_LOG) / f"{entity}_agent.log"
            if log_file.exists() and log_file.stat().st_size > 0:
                # Read only last 2KB instead of entire file
                with open(log_file, "rb") as f:
                    f.seek(max(0, log_file.stat().st_size - 2048))
                    tail = f.read().decode("utf-8", errors="replace")
                for line in tail.strip().split("\n")[-5:]:
                    if "topic" in line.lower() or "summary" in line.lower():
                        summary = line.split("]")[-1].strip()[:200]
                        break
        except Exception:
            pass

        ts = time.time()
        mood_delta = round(post_mood - pre_mood, 3)
        context = summary[:200] if summary else f"Session with {display}"
        metadata_json = json.dumps({
            "exit_reason": exit_reason,
            "mood_delta": mood_delta,
        })

        # 1. Direct activity_log write
        cons_db = str(get_db("consciousness"))
        conn = sqlite3.connect(cons_db, timeout=5)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "INSERT INTO activity_log "
                "(timestamp, activity_type, source, name, success, context, "
                " duration_ms, mood_before, mood_after, epq_snapshot, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ts, "entity_session", entity, display, 1 if success else 0,
                 context, duration_min * 60000, pre_mood, post_mood, "", metadata_json),
            )
            conn.execute(
                "DELETE FROM activity_log WHERE id NOT IN "
                "(SELECT id FROM activity_log ORDER BY id DESC LIMIT 500)"
            )

            # 2. Narrative reflection
            delta = post_mood - pre_mood
            direction = "better" if delta > 0.02 else "worse" if delta < -0.02 else "similar"
            reflection = (
                f"I spoke with {display} for {duration_min} minutes. "
                f"Topics: general reflection. "
                f"I feel {direction} afterwards (mood {delta:+.2f})."
            )
            if summary:
                reflection += f" {summary[:150]}"

            conn.execute(
                "INSERT INTO reflections (timestamp, trigger, content, "
                "mood_before, mood_after, reflection_depth) VALUES (?, ?, ?, ?, ?, ?)",
                (ts, "entity_session", reflection, pre_mood, post_mood, 1),
            )
            conn.execute(
                "INSERT INTO reflections_archive (timestamp, trigger, content, "
                "mood_before, mood_after, reflection_depth) VALUES (?, ?, ?, ?, ?, ?)",
                (ts, "entity_session", reflection, pre_mood, post_mood, 1),
            )
            conn.commit()
        finally:
            conn.close()

        # 3. E-PQ event (lightweight)
        try:
            from personality.e_pq import process_event
            if delta > 0.02:
                process_event("entity_session_positive",
                              data={"entity": display})
            elif delta < -0.02:
                process_event("entity_session_negative",
                              data={"entity": display})
        except Exception:
            pass

        LOG.info("EB entity experience: %s %dmin mood %+.2f (%s)",
                 display, duration_min, delta, exit_reason)
    except Exception as e:
        LOG.warning("EB entity recording failed: %s", e)


def run_entity_session(entity: str) -> str:
    """
    Import and run a single entity session. Returns exit_reason string.
    """
    module_name = ENTITY_MODULES[entity]
    display = ENTITY_DISPLAY.get(entity, entity)
    LOG.info("Starting %s session...", display)
    _entity_notify(f"{display} Session", "starting")

    # Experiential Bridge: capture pre-state
    pre_mood = _eb_get_mood()
    pre_ts = time.time()

    try:
        mod = importlib.import_module(module_name)
        # Cycle 5 D-7: Removed importlib.reload() — #1 memory leak source.
        # Reload creates duplicate module objects that never get GC'd.
        exit_reason = mod.run()
        if exit_reason is None:
            exit_reason = "unknown"
        LOG.info("%s session ended: %s", display, exit_reason)
        _entity_notify(f"{display} Session", f"ended ({exit_reason})")

        # Experiential Bridge: record entity experience
        try:
            _eb_record_entity_experience(entity, display, pre_mood, pre_ts, exit_reason)
        except Exception:
            pass

        return exit_reason
    except KeyboardInterrupt:
        LOG.info("%s session interrupted (KeyboardInterrupt)", display)
        return "shutdown_signal"
    except Exception as e:
        LOG.error("%s session failed: %s", display, e, exc_info=True)
        try:
            _eb_record_entity_experience(entity, display, pre_mood, pre_ts, "error")
        except Exception:
            pass
        return "error"
    finally:
        # Cycle 5 D-7: Force GC after each entity session to reclaim memory
        import gc
        gc.collect()
        LOG.debug("GC after %s session: collected", display)


# ── Main Loop ──────────────────────────────────────────────────────────

def main():
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    LOG.info("Entity Dispatcher starting (PID %d)...", os.getpid())
    LOG.info("Daily quotas: %s", DAILY_QUOTAS)

    while not _shutdown:
        # 1. Load/reset quotas
        quotas = load_or_reset_quotas()

        # 2. Check who's eligible
        eligible = get_eligible_entities(quotas)
        if not eligible:
            LOG.debug("All quotas exhausted for today — sleeping")
            # Sleep until midnight or POLL_INTERVAL, whichever is shorter
            now = datetime.datetime.now()
            midnight = (now + datetime.timedelta(days=1)).replace(
                hour=0, minute=0, second=5, microsecond=0
            )
            secs_to_midnight = (midnight - now).total_seconds()
            _shutdown_sleep(min(secs_to_midnight, POLL_INTERVAL))
            continue

        # 2b. Check for emergency therapy request (spiral detection)
        emergency_therapy = False
        if THERAPY_REQUEST_FILE.exists():
            try:
                req = json.loads(THERAPY_REQUEST_FILE.read_text(encoding="utf-8"))
                req_age = time.time() - req.get("timestamp", 0)
                if req_age < 3600 and "therapist" in eligible:  # Request < 1h old
                    LOG.warning("EMERGENCY THERAPY REQUEST: %s (patterns: %s)",
                                req.get("reason", "unknown"),
                                req.get("patterns", []))
                    _entity_notify("Emergency Therapy",
                                   f"Spiral detected — starting Dr. Hibbert")
                    emergency_therapy = True
                THERAPY_REQUEST_FILE.unlink(missing_ok=True)
            except Exception as e:
                LOG.warning("Failed to read therapy request: %s", e)
                THERAPY_REQUEST_FILE.unlink(missing_ok=True)

        # 2c. Check if Inner Sanctum is active — yield to sanctum
        # H1+H2 fix: Validate lock age to prevent stale lock blocking forever
        _sanctum_lock = Path("/tmp/frank/sanctum_active.lock")
        _sanctum_active = False
        if _sanctum_lock.exists():
            try:
                _lock_data = json.loads(_sanctum_lock.read_text())
                _lock_age = time.time() - _lock_data.get("start", 0)
                if _lock_age < 1800.0:  # 30 min = max duration * 2
                    _sanctum_active = True
                else:
                    LOG.warning("Stale sanctum lock (age=%.0fs) — removing", _lock_age)
                    _sanctum_lock.unlink(missing_ok=True)
            except (json.JSONDecodeError, OSError):
                # Corrupt lock file — remove it
                LOG.warning("Corrupt sanctum lock — removing")
                _sanctum_lock.unlink(missing_ok=True)
        # M7 fix: Emergency therapy overrides sanctum lock
        if _sanctum_active and not emergency_therapy:
            LOG.debug("Sanctum active — deferring entity session")
            _shutdown_sleep(POLL_INTERVAL)
            continue
        elif _sanctum_active and emergency_therapy:
            LOG.warning("EMERGENCY THERAPY: Overriding sanctum lock for spiral recovery")
            _sanctum_lock.unlink(missing_ok=True)

        # 3. Check idle gates
        if not all_gates_pass():
            _shutdown_sleep(POLL_INTERVAL)
            continue

        # 4. Pick next entity (or override with emergency therapy)
        if emergency_therapy and "therapist" in eligible:
            entity = "therapist"
        else:
            entity = pick_next_entity(eligible, quotas)
        display = ENTITY_DISPLAY.get(entity, entity)
        remaining = DAILY_QUOTAS[entity] - quotas["completed"].get(entity, 0)
        LOG.info("Selected %s (%d/%d sessions remaining today)",
                 display, remaining, DAILY_QUOTAS[entity])

        # 5. Run session (blocking)
        exit_reason = run_entity_session(entity)

        # 6. Update quotas based on exit reason
        #    Note: agents may append details like "user_returned (idle=15s)"
        #    so we use startswith() for prefix matching.
        if exit_reason.startswith("user_returned"):
            quotas.setdefault("last_session", {})[entity] = time.time()
            save_quotas(quotas)
            LOG.info("%s interrupted (%s). NOT counting against quota. "
                     "Cooldown %ds.", display, exit_reason, COOLDOWN_RETURNED)
            _shutdown_sleep(COOLDOWN_RETURNED)

        elif exit_reason.startswith("shutdown_signal"):
            LOG.info("Shutdown signal during %s session — exiting.", display)
            break

        elif exit_reason in COMPLETED_REASONS or any(
            exit_reason.startswith(r) for r in COMPLETED_REASONS
        ):
            quotas["completed"][entity] = quotas["completed"].get(entity, 0) + 1
            quotas.setdefault("last_session", {})[entity] = time.time()
            save_quotas(quotas)
            LOG.info("%s session completed (%s). Quota: %d/%d. Cooldown %ds.",
                     display, exit_reason,
                     quotas["completed"][entity], DAILY_QUOTAS[entity],
                     COOLDOWN_COMPLETED)
            _shutdown_sleep(COOLDOWN_COMPLETED)


        else:
            # Unknown reason — treat conservatively, don't count
            LOG.warning("%s exited with unknown reason '%s'. Not counting. "
                        "Cooldown %ds.", display, exit_reason, COOLDOWN_COMPLETED)
            _shutdown_sleep(COOLDOWN_COMPLETED)

    LOG.info("Entity Dispatcher shutting down.")


if __name__ == "__main__":
    main()
