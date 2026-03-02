#!/usr/bin/env python3
"""
Dream Daemon v1.0
=================

Franks Traumphase — ein budgetierter Reflexionsprozess der Erfahrungen
konsolidiert, neue Hypothesen synthetisiert und Emotionen normalisiert.

Architektur:
- 60-Minuten Tagesbudget (rollierendes 24h-Reset)
- 3 Phasen: Replay (~20min), Synthese (~20min), Konsolidierung (~20min)
- Unterbrechbar: pausiert sofort bei User-Aktivität, setzt exakt fort
- Trigger: 45min idle + 20h seit letztem Traum + CPU < 30% + Budget > 0 (NOT 50% — higher = more permissive!)

Läuft als systemd user service: aicore-dream.service
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import threading
import time
import traceback
import urllib.request
import urllib.error
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

try:
    from config.paths import get_db, AICORE_ROOT as _AICORE_ROOT
    if str(_AICORE_ROOT) not in sys.path:
        sys.path.insert(0, str(_AICORE_ROOT))
except ImportError:
    _AICORE_ROOT = Path(__file__).resolve().parents[1]
    if str(_AICORE_ROOT) not in sys.path:
        sys.path.insert(0, str(_AICORE_ROOT))

try:
    from config.paths import get_db
    DREAM_DB_PATH = get_db("dream")
    CHAT_MEMORY_DB_PATH = get_db("chat_memory")
    CONSCIOUSNESS_DB_PATH = get_db("consciousness")
    WORLD_EXPERIENCE_DB_PATH = get_db("world_experience")
except ImportError:
    _DATA_DIR = Path.home() / ".local" / "share" / "frank"
    _DB_DIR = _DATA_DIR / "db"
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    DREAM_DB_PATH = _DB_DIR / "dream.db"
    CHAT_MEMORY_DB_PATH = _DB_DIR / "chat_memory.db"
    CONSCIOUSNESS_DB_PATH = _DB_DIR / "consciousness.db"
    WORLD_EXPERIENCE_DB_PATH = _DB_DIR / "world_experience.db"

CORE_BASE = os.environ.get("AICORE_CORE_URL", "http://127.0.0.1:8088")
ROUTER_BASE = os.environ.get("AICORE_ROUTER_URL", "http://127.0.0.1:8091")

LOG = logging.getLogger("dream_daemon")


def _dream_notify(action: str, detail: str = "") -> None:
    """Fire-and-forget overlay notification."""
    try:
        from services.autonomous_notify import notify_autonomous
        notify_autonomous(action, detail, category="dream",
                          source="dream_daemon")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Timing & Constants
# ---------------------------------------------------------------------------

DREAM_BUDGET_SEC = 3600             # 60 min total daily budget
IDLE_THRESHOLD_SEC = 45 * 60        # 45 min idle before dreaming
COOLDOWN_BETWEEN_DREAMS_SEC = 20 * 3600  # 20h between complete dreams
BUDGET_RESET_INTERVAL_SEC = 24 * 3600    # 24h rolling budget reset
CPU_LOAD_THRESHOLD = 30.0           # Max CPU load % to start dreaming (Fix #49 was wrong: 50→30)
INTERRUPT_CHECK_INTERVAL_SEC = 30   # Check for user activity every 30s
MAIN_LOOP_TICK_SEC = 60             # Main daemon loop tick

# Phase budget allocation (approximate)
PHASE_BUDGET_SEC = {
    1: 20 * 60,   # Replay: ~20min
    2: 20 * 60,   # Synthesis: ~20min
    3: 20 * 60,   # Consolidation: ~20min
}

# LLM settings
DREAM_LLM_MAX_TOKENS = 800  # RLM needs reasoning room + JSON output
DREAM_LLM_SYSTEM = (
    "Du bist Franks Unterbewusstsein im Traum-Modus. "
    "Du analysierst, verknüpfst und reflektierst frei-assoziativ. "
    "Antworte IMMER nur mit validem JSON, kein anderer Text."
)

# E-PQ homeostasis targets during dreaming
HOMEOSTASIS_TARGETS = {
    "mood_buffer": 0.0,
    "precision_val": 0.5,
    "risk_val": 0.0,
    "empathy_val": 0.7,
    "autonomy_val": 0.3,
    "vigilance_val": 0.1,
}
DREAM_HOMEOSTASIS_RATE = 0.15

# Interaction batch size for replay
REPLAY_BATCH_SIZE = 10
# Max interactions to replay
REPLAY_MAX_INTERACTIONS = 20

# Memory consolidation
MEMORY_DECAY_FACTOR = 0.95
MEMORY_BOOST_AMOUNT = 0.3


# ---------------------------------------------------------------------------
# Database Schema
# ---------------------------------------------------------------------------

_DREAM_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS dream_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT DEFAULT 'idle',
    current_phase INTEGER DEFAULT 0,
    phase_progress TEXT DEFAULT '{}',
    budget_remaining_sec INTEGER DEFAULT 3600,
    budget_reset_at TEXT,
    last_dream_start TEXT,
    last_dream_end TEXT,
    total_dreams INTEGER DEFAULT 0,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS dream_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dream_session_id TEXT,
    phase TEXT,
    content TEXT,
    duration_sec INTEGER,
    timestamp TEXT
);

CREATE TABLE IF NOT EXISTS dream_hypotheses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dream_session_id TEXT,
    hypothesis TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    confidence REAL DEFAULT 0.5,
    created_at TEXT,
    updated_at TEXT
);
"""


# ---------------------------------------------------------------------------
# DreamDaemon
# ---------------------------------------------------------------------------

class DreamDaemon:
    """
    Franks Traum-Prozess — budgetiertes Träumen mit Interrupt/Resume.
    """

    def __init__(self, db_path: Path = DREAM_DB_PATH, test_mode: bool = False):
        self.db_path = db_path
        self._test_mode = test_mode
        self._lock = threading.RLock()
        self._running = False
        self._dreaming = False
        self._interrupt_requested = False
        self._threads: List[threading.Thread] = []
        self._dream_session_id: str = ""

        # Phase state
        self._current_phase: int = 0
        self._phase_progress: Dict[str, Any] = {}
        self._replay_results: List[Dict] = []
        self._synthesis_results: Dict[str, Any] = {}

        # Budget tracking
        self._phase_start_time: float = 0.0

        # Init
        self._ensure_schema()
        self._load_state()
        LOG.info("DreamDaemon initialized (db=%s, test_mode=%s)",
                 self.db_path, self._test_mode)

    # ── Database ──────────────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        """Thread-local DB connection."""
        local = getattr(self, '_local', None)
        if local is None:
            self._local = threading.local()
            local = self._local
        conn = getattr(local, 'conn', None)
        if conn is None:
            local.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30.0,
            )
            local.conn.row_factory = sqlite3.Row
            local.conn.execute("PRAGMA journal_mode=WAL")
        return local.conn

    def _ensure_schema(self):
        """Create tables if needed."""
        conn = self._get_conn()
        conn.executescript(_DREAM_SCHEMA)
        conn.commit()

    def _load_state(self):
        """Load current dream state from DB."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM dream_state ORDER BY id DESC LIMIT 1"
        ).fetchone()

        if row:
            self._current_phase = row["current_phase"]
            try:
                self._phase_progress = json.loads(row["phase_progress"] or "{}")
            except (json.JSONDecodeError, TypeError):
                self._phase_progress = {}

            # Check if budget needs reset
            reset_at = row["budget_reset_at"]
            if reset_at:
                try:
                    reset_time = datetime.fromisoformat(reset_at)
                    if datetime.now() >= reset_time:
                        self._reset_budget()
                        return
                except (ValueError, TypeError):
                    pass

            status = row["status"]
            if status == "dreaming":
                # Daemon was killed mid-dream, set to paused
                self._save_state(status="paused")
        else:
            # First run — create initial state
            now = datetime.now().isoformat()
            reset_at = (datetime.now() + timedelta(seconds=BUDGET_RESET_INTERVAL_SEC)).isoformat()
            conn.execute(
                "INSERT INTO dream_state (status, budget_remaining_sec, budget_reset_at, "
                "updated_at) VALUES (?, ?, ?, ?)",
                ("idle", DREAM_BUDGET_SEC, reset_at, now),
            )
            conn.commit()

    def _save_state(self, status: str = None, phase: int = None,
                    progress: Dict = None, budget_sec: int = None,
                    dream_start: str = None, dream_end: str = None,
                    total_dreams_inc: bool = False):
        """Update dream_state in DB."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM dream_state ORDER BY id DESC LIMIT 1"
        ).fetchone()

        if not row:
            return

        new_status = status if status is not None else row["status"]
        new_phase = phase if phase is not None else row["current_phase"]
        new_progress = json.dumps(progress) if progress is not None else row["phase_progress"]
        new_budget = budget_sec if budget_sec is not None else row["budget_remaining_sec"]
        new_start = dream_start if dream_start is not None else row["last_dream_start"]
        new_end = dream_end if dream_end is not None else row["last_dream_end"]
        new_total = (row["total_dreams"] or 0) + (1 if total_dreams_inc else 0)

        conn.execute(
            "UPDATE dream_state SET status=?, current_phase=?, phase_progress=?, "
            "budget_remaining_sec=?, last_dream_start=?, last_dream_end=?, "
            "total_dreams=?, updated_at=? WHERE id=?",
            (new_status, new_phase, new_progress, new_budget,
             new_start, new_end, new_total, datetime.now().isoformat(), row["id"]),
        )
        conn.commit()

    def _get_budget_remaining(self) -> int:
        """Get remaining dream budget in seconds."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT budget_remaining_sec, budget_reset_at FROM dream_state ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return 0

        # Check reset
        reset_at = row["budget_reset_at"]
        if reset_at:
            try:
                if datetime.now() >= datetime.fromisoformat(reset_at):
                    self._reset_budget()
                    return DREAM_BUDGET_SEC
            except (ValueError, TypeError):
                pass

        return row["budget_remaining_sec"] or 0

    def _reset_budget(self):
        """Reset the daily dream budget."""
        conn = self._get_conn()
        reset_at = (datetime.now() + timedelta(seconds=BUDGET_RESET_INTERVAL_SEC)).isoformat()
        row = conn.execute(
            "SELECT id FROM dream_state ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE dream_state SET budget_remaining_sec=?, budget_reset_at=?, "
                "status='idle', current_phase=0, phase_progress='{}', updated_at=? WHERE id=?",
                (DREAM_BUDGET_SEC, reset_at, datetime.now().isoformat(), row["id"]),
            )
            conn.commit()
        LOG.info("Dream budget reset (60 min)")

    def _consume_budget(self, seconds: int):
        """Subtract used seconds from budget."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT id, budget_remaining_sec FROM dream_state ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            new_budget = max(0, (row["budget_remaining_sec"] or 0) - seconds)
            conn.execute(
                "UPDATE dream_state SET budget_remaining_sec=?, updated_at=? WHERE id=?",
                (new_budget, datetime.now().isoformat(), row["id"]),
            )
            conn.commit()

    def _log_dream(self, phase: str, content: Any, duration_sec: int):
        """Write a dream_log entry."""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO dream_log (dream_session_id, phase, content, "
            "duration_sec, timestamp) VALUES (?, ?, ?, ?, ?)",
            (self._dream_session_id, phase, json.dumps(content, ensure_ascii=False),
             duration_sec, datetime.now().isoformat()),
        )
        conn.commit()

    # ── LLM Calls ────────────────────────────────────────────────────

    def _llm_call(self, text: str, max_tokens: int = DREAM_LLM_MAX_TOKENS,
                  system: str = "", retries: int = 2) -> str:
        """Make LLM call via router with retry logic.

        Dream calls are low priority — if the LLM is busy with user requests
        or other services, we wait and retry rather than fail immediately.
        """
        if not system:
            system = DREAM_LLM_SYSTEM
        # Truncate prompt to avoid overwhelming the LLM
        if len(text) > 4000:
            text = text[:4000] + "\n...(gekürzt)"
        # Ensure min tokens (router requires >= 16)
        max_tokens = max(16, max_tokens)
        payload = json.dumps({
            "text": text,
            "n_predict": max_tokens,
            "system": system,
        }).encode()

        for attempt in range(retries + 1):
            if attempt > 0:
                # Wait before retry (exponential backoff: 15s, 30s)
                wait = 15 * (2 ** (attempt - 1))
                LOG.info("LLM retry %d/%d in %ds...", attempt, retries, wait)
                time.sleep(wait)
                # Check if we should abort (interrupt or stop)
                if self._interrupt_requested or not self._running:
                    return ""

            req = urllib.request.Request(
                f"{ROUTER_BASE}/route",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=360.0) as resp:
                    data = json.loads(resp.read().decode())
                    if data.get("ok"):
                        return (data.get("text") or "").strip()
            except Exception as e:
                LOG.warning("LLM call failed (attempt %d/%d): %s",
                            attempt + 1, retries + 1, e)

        return ""

    def _parse_json_response(self, text: str) -> Optional[Dict]:
        """Parse LLM JSON response with fallback for truncated/prefixed output."""
        if not text:
            return None
        text = text.strip()

        # D-9 fix: Strip DeepSeek <think> blocks that leak into content
        # Cycle 5 D-8: Also handle unclosed <think> blocks (truncated responses)
        import re
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        # If <think> is still present without closing tag, strip from <think> to end
        think_pos = text.find("<think>")
        if think_pos >= 0:
            text = text[:think_pos].strip()

        # Remove markdown fences
        if "```" in text:
            lines = text.split("\n")
            json_lines = []
            in_json = False
            for line in lines:
                if line.strip().startswith("```") and not in_json:
                    in_json = True
                    continue
                if line.strip() == "```" and in_json:
                    break
                if in_json:
                    json_lines.append(line)
            if json_lines:
                text = "\n".join(json_lines)

        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Find JSON object in text (skip non-JSON prefix)
        start = text.find("{")
        if start >= 0:
            # Try progressively shorter substrings in case of truncation
            end = text.rfind("}") + 1
            if end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass

            # Try to fix truncated JSON by closing open strings/brackets
            fragment = text[start:]
            # Try various closing suffixes (string might be mid-value)
            open_braces = fragment.count("{") - fragment.count("}")
            open_brackets = fragment.count("[") - fragment.count("]")
            # Check if we're inside a string (odd number of unescaped quotes)
            in_string = fragment.count('"') % 2 == 1
            string_close = '..."' if in_string else ""
            bracket_close = "]" * max(0, open_brackets)
            brace_close = "}" * max(0, open_braces)
            for suffix in [
                string_close + bracket_close + brace_close,
                string_close + "," + bracket_close + brace_close,
                '"' + bracket_close + brace_close,
                '"]' + brace_close,
                '"}',
                bracket_close + brace_close,
            ]:
                if not suffix:
                    continue
                try:
                    return json.loads(fragment + suffix)
                except json.JSONDecodeError:
                    continue

        # Try array
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            try:
                result = json.loads(text[start:end])
                if isinstance(result, list):
                    return {"items": result}
            except json.JSONDecodeError:
                pass

        LOG.warning("Failed to parse JSON from LLM: %.200s", text)
        return None

    # ── Idle / Activity Detection ────────────────────────────────────

    @staticmethod
    def _is_gaming_active() -> bool:
        """Check if gaming mode is active — no dreaming during gaming."""
        try:
            try:
                from config.paths import TEMP_FILES as _dream_tf
                state_file = _dream_tf["gaming_mode_state"]
            except ImportError:
                state_file = Path("/tmp/frank/gaming_mode_state.json")
            if state_file.exists():
                import json as _json
                data = _json.loads(state_file.read_text())
                return data.get("active", False)
        except Exception:
            pass
        return False

    def _get_idle_seconds(self) -> float:
        """Get seconds since last user interaction."""
        if self._test_mode:
            return IDLE_THRESHOLD_SEC + 60  # Always idle in test mode

        # Method 1: Check consciousness daemon's last_chat_ts
        try:
            from services.consciousness_daemon import get_consciousness_daemon
            cd = get_consciousness_daemon()
            with cd._lock:
                last_chat = cd._last_chat_ts
            return time.time() - last_chat
        except Exception:
            pass

        # Method 2: Check chat_memory.db directly
        try:
            conn = sqlite3.connect(str(CHAT_MEMORY_DB_PATH), timeout=5.0)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT MAX(timestamp) as last_ts FROM messages WHERE is_user=1"
            ).fetchone()
            conn.close()
            if row and row["last_ts"]:
                return time.time() - float(row["last_ts"])
        except Exception:
            pass

        return 0.0

    def _check_user_active(self) -> bool:
        """Check if user is currently active (for interrupt detection)."""
        idle = self._get_idle_seconds()
        return idle < 120  # Active if interaction within last 2 minutes

    def _get_cpu_load(self) -> float:
        """Get current CPU load percentage."""
        try:
            with open("/proc/loadavg", "r") as f:
                load_1min = float(f.read().split()[0])
            cpu_count = os.cpu_count() or 1
            return (load_1min / cpu_count) * 100.0
        except Exception:
            return 0.0

    def _get_last_dream_end(self) -> Optional[datetime]:
        """Get timestamp of last completed dream."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT last_dream_end FROM dream_state ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row and row["last_dream_end"]:
            try:
                return datetime.fromisoformat(row["last_dream_end"])
            except (ValueError, TypeError):
                pass
        return None

    def _get_current_status(self) -> str:
        """Get current dream status."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT status FROM dream_state ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row["status"] if row else "idle"

    # ── Trigger Check ────────────────────────────────────────────────

    def _should_start_dreaming(self) -> bool:
        """Check if all trigger conditions are met."""
        # Gaming mode: never dream during gaming
        if self._is_gaming_active():
            return False

        # Don't dream during sanctum or entity sessions (RLM contention)
        from pathlib import Path
        if Path("/tmp/frank/sanctum_active.lock").exists():
            return False

        status = self._get_current_status()

        # If paused, check resume conditions (lower idle threshold)
        if status == "paused":
            idle = self._get_idle_seconds()
            budget = self._get_budget_remaining()
            cpu = self._get_cpu_load()
            if idle > IDLE_THRESHOLD_SEC and budget > 0 and cpu < CPU_LOAD_THRESHOLD:
                LOG.info("Resume conditions met (idle=%.0fs, budget=%ds, cpu=%.1f%%)",
                         idle, budget, cpu)
                return True
            return False

        # Normal trigger: status must be idle
        if status not in ("idle", "completed"):
            return False

        # Check idle time
        idle = self._get_idle_seconds()
        if idle < IDLE_THRESHOLD_SEC:
            return False

        # Check cooldown since last complete dream
        last_end = self._get_last_dream_end()
        if last_end:
            since_last = (datetime.now() - last_end).total_seconds()
            if since_last < COOLDOWN_BETWEEN_DREAMS_SEC:
                return False

        # Check CPU load
        cpu = self._get_cpu_load()
        if cpu > CPU_LOAD_THRESHOLD:
            return False

        # Check budget
        budget = self._get_budget_remaining()
        if budget <= 0:
            return False

        LOG.info("Dream trigger conditions met (idle=%.0fs, cpu=%.1f%%, budget=%ds)",
                 idle, cpu, budget)
        return True

    # ── Interrupt Handling ───────────────────────────────────────────

    def _check_interrupt(self) -> bool:
        """Check if dreaming should be interrupted."""
        if self._interrupt_requested:
            return True
        if self._test_mode:
            return False
        return self._check_user_active()

    def _handle_interrupt(self):
        """Pause the dream, save state, consume budget."""
        LOG.info("Dream interrupted — saving state and pausing")
        elapsed = int(time.time() - self._phase_start_time)
        self._consume_budget(elapsed)
        self._save_state(
            status="paused",
            phase=self._current_phase,
            progress=self._phase_progress,
        )
        self._dreaming = False
        self._interrupt_requested = False

    def request_interrupt(self):
        """External call to interrupt dreaming (e.g. from core API)."""
        self._interrupt_requested = True

    # ── Data Loading ─────────────────────────────────────────────────

    def _load_recent_interactions(self, since_ts: float = None) -> List[Dict]:
        """Load recent chat interactions from chat_memory.db."""
        try:
            conn = sqlite3.connect(str(CHAT_MEMORY_DB_PATH), timeout=10.0)
            conn.row_factory = sqlite3.Row

            if since_ts is None:
                # Since last dream, or last 24h
                last_end = self._get_last_dream_end()
                if last_end:
                    since_ts = last_end.timestamp()
                else:
                    since_ts = time.time() - 86400  # 24h ago

            rows = conn.execute(
                "SELECT id, role, sender, text, timestamp, created_at FROM messages "
                "WHERE timestamp > ? ORDER BY timestamp ASC LIMIT ?",
                (since_ts, REPLAY_MAX_INTERACTIONS),
            ).fetchall()
            conn.close()

            return [dict(r) for r in rows]
        except Exception as e:
            LOG.warning("Failed to load interactions: %s", e)
            return []

    def _load_epq_history(self, since_ts: float) -> List[Dict]:
        """Load E-PQ personality state history."""
        try:
            conn = sqlite3.connect(str(WORLD_EXPERIENCE_DB_PATH), timeout=10.0)
            conn.row_factory = sqlite3.Row
            since_iso = datetime.fromtimestamp(since_ts).isoformat()
            rows = conn.execute(
                "SELECT timestamp, precision_val, risk_val, empathy_val, "
                "autonomy_val, vigilance_val, mood_buffer, event_ref_id "
                "FROM personality_state WHERE timestamp > ? ORDER BY timestamp ASC LIMIT 100",
                (since_iso,),
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            LOG.warning("Failed to load E-PQ history: %s", e)
            return []

    def _load_attention_log(self, since_ts: float) -> List[Dict]:
        """Load attention log entries from consciousness.db."""
        try:
            conn = sqlite3.connect(str(CONSCIOUSNESS_DB_PATH), timeout=10.0)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT timestamp, focus, source, salience FROM attention_log "
                "WHERE timestamp > ? ORDER BY timestamp ASC LIMIT 100",
                (since_ts,),
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            LOG.warning("Failed to load attention log: %s", e)
            return []

    def _load_causal_patterns(self) -> List[Dict]:
        """Load causal patterns from world_experience.db."""
        try:
            conn = sqlite3.connect(str(WORLD_EXPERIENCE_DB_PATH), timeout=10.0)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT cl.relation_type, cl.confidence, cl.observation_count, "
                "e1.name as cause_name, e2.name as effect_name "
                "FROM causal_links cl "
                "JOIN entities e1 ON cl.cause_entity_id = e1.id "
                "JOIN entities e2 ON cl.effect_entity_id = e2.id "
                "WHERE cl.status = 'active' AND cl.confidence > 0.3 "
                "ORDER BY cl.confidence DESC LIMIT 30",
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            LOG.warning("Failed to load causal patterns: %s", e)
            return []

    def _load_existing_hypotheses(self) -> List[Dict]:
        """Load existing dream hypotheses."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, hypothesis, status, confidence, created_at FROM dream_hypotheses "
            "WHERE status = 'active' ORDER BY confidence DESC LIMIT 20",
        ).fetchall()
        return [dict(r) for r in rows]

    def _load_current_epq(self) -> Dict:
        """Load current E-PQ state."""
        try:
            from personality.e_pq import get_epq
            epq = get_epq()
            state = epq.get_state()
            return state.to_dict()
        except Exception as e:
            LOG.warning("Failed to load EPQ: %s", e)
            return {}

    # ── Phase 1: Replay ──────────────────────────────────────────────

    def _run_phase_replay(self):
        """Phase 1: Replay recent interactions and identify patterns."""
        LOG.info("Phase 1: REPLAY starting")
        self._current_phase = 1
        self._phase_start_time = time.time()

        # Load processed IDs from progress (for resume)
        processed_ids = set(self._phase_progress.get("replay_processed_ids", []))
        self._replay_results = self._phase_progress.get("replay_results", [])

        # Determine since_ts
        last_end = self._get_last_dream_end()
        since_ts = last_end.timestamp() if last_end else time.time() - 86400

        # Load data
        interactions = self._load_recent_interactions(since_ts)
        epq_history = self._load_epq_history(since_ts)
        attention_log = self._load_attention_log(since_ts)

        if not interactions:
            LOG.info("No interactions to replay — skipping phase 1")
            self._save_state(phase=1, progress={
                "replay_processed_ids": list(processed_ids),
                "replay_results": self._replay_results,
                "replay_complete": True,
            })
            return

        # Filter out already processed
        remaining = [i for i in interactions if i.get("id") not in processed_ids]

        # Batch and process
        for i in range(0, len(remaining), REPLAY_BATCH_SIZE):
            if self._check_interrupt():
                self._phase_progress = {
                    "replay_processed_ids": list(processed_ids),
                    "replay_results": self._replay_results,
                    "replay_complete": False,
                }
                self._handle_interrupt()
                return

            batch = remaining[i:i + REPLAY_BATCH_SIZE]
            batch_text = "\n".join(
                f"[{m.get('role', '?')}] {m.get('text', '')[:150]}"
                for m in batch
            )

            # Find EPQ entries for this time window
            batch_ts_start = min(m.get("timestamp", 0) for m in batch)
            batch_ts_end = max(m.get("timestamp", 0) for m in batch)
            batch_epq = [e for e in epq_history
                         if batch_ts_start <= self._parse_ts(e.get("timestamp", "")) <= batch_ts_end + 60]
            batch_attention = [a for a in attention_log
                               if batch_ts_start <= a.get("timestamp", 0) <= batch_ts_end + 60]

            epq_text = json.dumps(batch_epq[:5], ensure_ascii=False, default=str)[:500] if batch_epq else "keine"
            attention_text = json.dumps(batch_attention[:5], ensure_ascii=False, default=str)[:500] if batch_attention else "keine"

            prompt = (
                "Analysiere diese Chat-Interaktionen. "
                "Finde Muster, emotionale Auslöser, ungelöste Fragen und Überraschungen.\n\n"
                f"INTERAKTIONEN:\n{batch_text}\n\n"
                f"E-PQ:\n{epq_text}\n\n"
                f"ATTENTION:\n{attention_text}\n\n"
                'Antworte NUR mit JSON: {"patterns": ["..."], "triggers": ["..."], "unresolved": ["..."], "surprises": ["..."]}'
            )

            response = self._llm_call(prompt, max_tokens=200)
            parsed = self._parse_json_response(response)

            if parsed:
                self._replay_results.append(parsed)

            # Track processed IDs
            for m in batch:
                processed_ids.add(m.get("id", 0))

            # Update progress
            self._phase_progress = {
                "replay_processed_ids": list(processed_ids),
                "replay_results": self._replay_results,
                "replay_complete": False,
            }
            self._save_state(phase=1, progress=self._phase_progress)

            # Budget check
            elapsed = time.time() - self._phase_start_time
            budget = self._get_budget_remaining()
            if elapsed >= PHASE_BUDGET_SEC[1] or elapsed >= budget:
                break

        # Phase complete
        self._phase_progress["replay_complete"] = True
        elapsed = int(time.time() - self._phase_start_time)
        self._consume_budget(elapsed)
        self._save_state(phase=1, progress=self._phase_progress)
        self._log_dream("replay", self._replay_results, elapsed)
        LOG.info("Phase 1: REPLAY complete (%d results, %ds)", len(self._replay_results), elapsed)
        _dream_notify("Dream Phase 1", f"Replay complete ({len(self._replay_results)} results, {elapsed}s)")

    # ── Phase 2: Synthesis ───────────────────────────────────────────

    def _run_phase_synthesis(self):
        """Phase 2: Synthesize new hypotheses from replay + existing knowledge."""
        LOG.info("Phase 2: SYNTHESIS starting")
        self._current_phase = 2
        self._phase_start_time = time.time()

        # Check if already done (resume)
        if self._phase_progress.get("synthesis_complete"):
            self._synthesis_results = self._phase_progress.get("synthesis_results", {})
            LOG.info("Phase 2: Already complete (resume)")
            return

        if self._check_interrupt():
            self._handle_interrupt()
            return

        # Load data
        causal_patterns = self._load_causal_patterns()
        existing_hypotheses = self._load_existing_hypotheses()
        current_epq = self._load_current_epq()

        # Load replay results from progress if not in memory
        if not self._replay_results:
            self._replay_results = self._phase_progress.get("replay_results", [])

        replay_text = json.dumps(self._replay_results, ensure_ascii=False, default=str)[:1500]
        patterns_text = json.dumps(causal_patterns[:10], ensure_ascii=False, default=str)[:800]
        hypotheses_text = json.dumps(
            [h.get("hypothesis", "")[:80] for h in existing_hypotheses[:5]],
            ensure_ascii=False
        )[:500]
        epq_text = json.dumps({k: round(v, 2) for k, v in current_epq.items()
                               if k in ("precision_val", "risk_val", "empathy_val",
                                        "autonomy_val", "vigilance_val", "mood_buffer")},
                              ensure_ascii=False) if current_epq else "{}"

        prompt = (
            "Synthetisiere Erkenntnisse aus Replay-Daten und bestehendem Wissen.\n\n"
            f"REPLAY:\n{replay_text}\n\n"
            f"KAUSAL-PATTERNS:\n{patterns_text}\n\n"
            f"HYPOTHESEN:\n{hypotheses_text}\n\n"
            f"E-PQ:\n{epq_text}\n\n"
            "Formuliere neue Hypothesen, Kausal-Links, bewerte bestehende Hypothesen.\n"
            'JSON: {"new_hypotheses": ["..."], "new_causal_links": ["..."], '
            '"hypothesis_updates": [], "deep_patterns": ["..."]}'
        )

        if self._check_interrupt():
            self._handle_interrupt()
            return

        response = self._llm_call(prompt, max_tokens=300)
        self._synthesis_results = self._parse_json_response(response) or {}

        # Store new hypotheses
        if self._synthesis_results.get("new_hypotheses"):
            conn = self._get_conn()
            now = datetime.now().isoformat()
            for hyp in self._synthesis_results["new_hypotheses"]:
                if isinstance(hyp, str) and hyp.strip():
                    conn.execute(
                        "INSERT INTO dream_hypotheses (dream_session_id, hypothesis, "
                        "created_at, updated_at) VALUES (?, ?, ?, ?)",
                        (self._dream_session_id, hyp.strip(), now, now),
                    )
            conn.commit()

        # Update existing hypotheses based on synthesis
        if self._synthesis_results.get("hypothesis_updates"):
            self._apply_hypothesis_updates(self._synthesis_results["hypothesis_updates"])

        # Phase complete
        self._phase_progress["synthesis_results"] = self._synthesis_results
        self._phase_progress["synthesis_complete"] = True
        elapsed = int(time.time() - self._phase_start_time)
        self._consume_budget(elapsed)
        self._save_state(phase=2, progress=self._phase_progress)
        self._log_dream("synthesis", self._synthesis_results, elapsed)
        LOG.info("Phase 2: SYNTHESIS complete (%ds)", elapsed)
        _dream_notify("Dream Phase 2", f"Synthesis complete ({elapsed}s)")

    def _apply_hypothesis_updates(self, updates: List):
        """Apply hypothesis status updates from synthesis."""
        conn = self._get_conn()
        now = datetime.now().isoformat()
        for update in updates:
            if not isinstance(update, dict):
                continue
            hyp_text = update.get("hypothesis", "")
            new_status = update.get("status", "")
            if hyp_text and new_status in ("confirmed", "refuted", "modified"):
                # Find matching hypothesis (fuzzy match on first 50 chars)
                rows = conn.execute(
                    "SELECT id, hypothesis FROM dream_hypotheses WHERE status='active'"
                ).fetchall()
                for row in rows:
                    if hyp_text[:50].lower() in row["hypothesis"].lower():
                        conn.execute(
                            "UPDATE dream_hypotheses SET status=?, updated_at=? WHERE id=?",
                            (new_status, now, row["id"]),
                        )
                        break
        conn.commit()

    # ── Phase 3: Consolidation ───────────────────────────────────────

    def _run_phase_consolidation(self):
        """Phase 3: Write reflections, normalize E-PQ, consolidate memory."""
        LOG.info("Phase 3: CONSOLIDATION starting")
        self._current_phase = 3
        self._phase_start_time = time.time()

        steps_done = self._phase_progress.get("consolidation_steps_done", [])

        # Step 1: Write dream reflections to consciousness.db
        if "reflections" not in steps_done:
            if self._check_interrupt():
                self._handle_interrupt()
                return
            self._write_dream_reflections()
            steps_done.append("reflections")
            self._phase_progress["consolidation_steps_done"] = steps_done
            self._save_state(phase=3, progress=self._phase_progress)

        # Step 2: E-PQ Homeostasis
        if "homeostasis" not in steps_done:
            if self._check_interrupt():
                self._handle_interrupt()
                return
            self._apply_dream_homeostasis()
            steps_done.append("homeostasis")
            self._phase_progress["consolidation_steps_done"] = steps_done
            self._save_state(phase=3, progress=self._phase_progress)

        # Step 3: Memory consolidation (activation boost/decay)
        if "memory" not in steps_done:
            if self._check_interrupt():
                self._handle_interrupt()
                return
            self._consolidate_memories()
            steps_done.append("memory")
            self._phase_progress["consolidation_steps_done"] = steps_done
            self._save_state(phase=3, progress=self._phase_progress)

        # Phase complete
        self._phase_progress["consolidation_complete"] = True
        elapsed = int(time.time() - self._phase_start_time)
        self._consume_budget(elapsed)
        self._save_state(phase=3, progress=self._phase_progress)
        self._log_dream("consolidation", {
            "steps": steps_done,
        }, elapsed)
        LOG.info("Phase 3: CONSOLIDATION complete (%ds)", elapsed)
        _dream_notify("Dream Phase 3", f"Consolidation complete ({elapsed}s)")

    def _write_dream_reflections(self):
        """Write 2-5 dream reflections to consciousness.db."""
        if not self._synthesis_results:
            self._synthesis_results = self._phase_progress.get("synthesis_results", {})

        synthesis_text = json.dumps(self._synthesis_results, ensure_ascii=False, default=str)[:1200]

        prompt = (
            "Formuliere 2-3 kurze Traum-Reflexionen basierend auf diesen Synthese-Ergebnissen. "
            "Assoziativ, bildhaft, wie echte Traumgedanken.\n\n"
            f"SYNTHESE:\n{synthesis_text}\n\n"
            'JSON Array: ["Reflexion 1...", "Reflexion 2..."]'
        )

        response = self._llm_call(prompt, max_tokens=200)
        parsed = self._parse_json_response(response)

        reflections = []
        if parsed:
            if isinstance(parsed, dict) and "items" in parsed:
                reflections = parsed["items"]
            elif isinstance(parsed, dict):
                # Try various keys
                for key in ("reflections", "reflexionen", "items"):
                    if key in parsed and isinstance(parsed[key], list):
                        reflections = parsed[key]
                        break
            elif isinstance(parsed, list):
                reflections = parsed

        if not reflections:
            reflections = ["Traumlose Nacht — zu wenig Material für tiefere Reflexion."]

        # Write to consciousness.db
        try:
            conn = sqlite3.connect(str(CONSCIOUSNESS_DB_PATH), timeout=10.0)
            conn.execute("PRAGMA busy_timeout=10000")
            now = time.time()
            # Read current mood for accurate reflection metadata
            try:
                row = conn.execute(
                    "SELECT mood_value FROM mood_trajectory ORDER BY id DESC LIMIT 1"
                ).fetchone()
                current_mood = row[0] if row else 0.5
            except Exception:
                current_mood = 0.5
            for ref in reflections[:5]:
                if isinstance(ref, str) and ref.strip():
                    conn.execute(
                        "INSERT INTO reflections (timestamp, trigger, content, "
                        "mood_before, mood_after, reflection_depth) VALUES (?, ?, ?, ?, ?, ?)",
                        (now, "dream", ref.strip(), current_mood, current_mood, 2),
                    )
            conn.commit()
            conn.close()
            LOG.info("Wrote %d dream reflections to consciousness.db", min(len(reflections), 5))
        except Exception as e:
            LOG.warning("Failed to write reflections: %s", e)

        # Store reflections in dream log too
        self._phase_progress["dream_reflections"] = reflections[:5]

    def _apply_dream_homeostasis(self):
        """Pull E-PQ vectors toward homeostasis targets."""
        try:
            from personality.e_pq import get_epq
            epq = get_epq()

            with epq._lock:
                state = epq._state
                if state is None:
                    return

                for dim, target in HOMEOSTASIS_TARGETS.items():
                    current = getattr(state, dim, None)
                    if current is not None:
                        new_val = current + (target - current) * DREAM_HOMEOSTASIS_RATE
                        new_val = max(-1.0, min(1.0, new_val))
                        setattr(state, dim, new_val)

                epq._save_state("dream_homeostasis")
            LOG.info("Applied dream homeostasis to E-PQ vectors")
        except Exception as e:
            LOG.warning("Failed to apply homeostasis: %s", e)

    def _consolidate_memories(self):
        """Boost referenced memories, decay old ones."""
        # Get important patterns from replay
        important_topics = set()
        for result in self._replay_results:
            if isinstance(result, dict):
                for pattern in result.get("patterns", []):
                    if isinstance(pattern, str):
                        important_topics.add(pattern[:100])

        # Boost memories referenced in replay (via consciousness.db reflections)
        try:
            conn = sqlite3.connect(str(CONSCIOUSNESS_DB_PATH), timeout=10.0)
            # Boost recent reflections that match replay topics
            recent = conn.execute(
                "SELECT id, content FROM reflections ORDER BY timestamp DESC LIMIT 50"
            ).fetchall()

            boosted = 0
            for ref_row in recent:
                content = ref_row[1] if ref_row[1] else ""
                for topic in important_topics:
                    if topic.lower() in content.lower():
                        # "Boost" by updating mood_after slightly (used as importance signal)
                        conn.execute(
                            "UPDATE reflections SET mood_after = MIN(1.0, mood_after + ?) WHERE id = ?",
                            (MEMORY_BOOST_AMOUNT, ref_row[0]),
                        )
                        boosted += 1
                        break
            conn.commit()
            conn.close()
            LOG.info("Memory consolidation: boosted %d memories", boosted)
        except Exception as e:
            LOG.warning("Memory consolidation failed: %s", e)

        # Fire observation to world experience daemon
        try:
            from tools.world_experience_daemon import get_daemon
            get_daemon().observe(
                cause_name="dream.consolidation",
                effect_name="memory.strengthened",
                cause_type="cognitive",
                effect_type="cognitive",
                relation="triggers",
                evidence=0.3,
            )
        except Exception:
            pass

    # ── Main Dream Loop ──────────────────────────────────────────────

    def _run_dream_session(self):
        """Execute a dream session (may be initial or resumed)."""
        status = self._get_current_status()

        if status == "paused":
            # Resume
            LOG.info("Resuming dream session %s at phase %d",
                     self._dream_session_id or "?", self._current_phase)
            # Reload progress
            conn = self._get_conn()
            row = conn.execute(
                "SELECT phase_progress, current_phase FROM dream_state ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row:
                self._current_phase = row["current_phase"]
                try:
                    self._phase_progress = json.loads(row["phase_progress"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    self._phase_progress = {}
            # Restore replay results from progress
            self._replay_results = self._phase_progress.get("replay_results", [])
            self._synthesis_results = self._phase_progress.get("synthesis_results", {})
            # Recover session ID from dream_log
            log_row = conn.execute(
                "SELECT dream_session_id FROM dream_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if log_row and log_row["dream_session_id"]:
                self._dream_session_id = log_row["dream_session_id"]
            elif not self._dream_session_id:
                self._dream_session_id = str(uuid.uuid4())[:8]
        else:
            # New dream
            self._dream_session_id = str(uuid.uuid4())[:8]
            self._current_phase = 0
            self._phase_progress = {}
            self._replay_results = []
            self._synthesis_results = {}
            LOG.info("Starting new dream session: %s", self._dream_session_id)

        self._dreaming = True
        self._save_state(
            status="dreaming",
            dream_start=datetime.now().isoformat() if status != "paused" else None,
        )

        try:
            # Phase 1: Replay
            if self._current_phase < 1 or (
                self._current_phase == 1 and not self._phase_progress.get("replay_complete")
            ):
                self._run_phase_replay()
                if not self._dreaming:
                    return  # Interrupted

            # Phase 2: Synthesis
            if self._current_phase < 2 or (
                self._current_phase == 2 and not self._phase_progress.get("synthesis_complete")
            ):
                self._run_phase_synthesis()
                if not self._dreaming:
                    return  # Interrupted

            # Phase 3: Consolidation
            if self._current_phase < 3 or (
                self._current_phase == 3 and not self._phase_progress.get("consolidation_complete")
            ):
                self._run_phase_consolidation()
                if not self._dreaming:
                    return  # Interrupted

            # Dream complete!
            self._dreaming = False
            self._save_state(
                status="completed",
                phase=0,
                progress={},
                dream_end=datetime.now().isoformat(),
                total_dreams_inc=True,
            )

            # Write summary to dream_log
            self._log_dream("summary", {
                "session_id": self._dream_session_id,
                "replay_count": len(self._replay_results),
                "new_hypotheses": len(self._synthesis_results.get("new_hypotheses", [])),
                "reflections": self._phase_progress.get("dream_reflections", []),
            }, 0)

            LOG.info("Dream session %s COMPLETE", self._dream_session_id)
            _dream_notify("Dream Complete", f"Session {self._dream_session_id[:8]} finished")

        except Exception as e:
            LOG.error("Dream session failed: %s\n%s", e, traceback.format_exc())
            self._dreaming = False
            elapsed = int(time.time() - self._phase_start_time) if self._phase_start_time else 0
            self._consume_budget(elapsed)
            self._save_state(status="paused", phase=self._current_phase,
                             progress=self._phase_progress)

    # ── Daemon Lifecycle ─────────────────────────────────────────────

    def _main_loop(self):
        """Main daemon loop — check triggers and run dreams."""
        while self._running:
            try:
                if self._should_start_dreaming():
                    self._run_dream_session()
            except Exception as e:
                LOG.error("Main loop error: %s\n%s", e, traceback.format_exc())
            time.sleep(MAIN_LOOP_TICK_SEC)

    def start(self):
        """Start the dream daemon."""
        if self._running:
            return
        self._running = True
        t = threading.Thread(target=self._main_loop, name="dream-main",
                             daemon=True)
        t.start()
        self._threads.append(t)
        LOG.info("DreamDaemon started")

    def stop(self):
        """Stop gracefully."""
        self._running = False
        if self._dreaming:
            self._handle_interrupt()
        for t in self._threads:
            t.join(timeout=10.0)
        LOG.info("DreamDaemon stopped")

    def is_running(self) -> bool:
        return self._running

    def is_dreaming(self) -> bool:
        return self._dreaming

    def get_status(self) -> Dict[str, Any]:
        """Get current dream status for external queries."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM dream_state ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return {"status": "unknown"}

        status = {
            "status": row["status"],
            "current_phase": row["current_phase"],
            "budget_remaining_sec": row["budget_remaining_sec"],
            "budget_remaining_min": (row["budget_remaining_sec"] or 0) // 60,
            "total_dreams": row["total_dreams"],
            "last_dream_start": row["last_dream_start"],
            "last_dream_end": row["last_dream_end"],
            "budget_reset_at": row["budget_reset_at"],
        }

        # Human-readable
        if row["status"] == "dreaming":
            phase_names = {1: "Replay", 2: "Synthese", 3: "Konsolidierung"}
            status["description"] = f"Frank träumt gerade... (Phase: {phase_names.get(row['current_phase'], '?')})"
        elif row["status"] == "paused":
            status["description"] = "Traum pausiert — wartet auf Idle"
        elif row["last_dream_end"]:
            try:
                end = datetime.fromisoformat(row["last_dream_end"])
                ago = datetime.now() - end
                hours_ago = ago.total_seconds() / 3600
                status["description"] = f"Letzter Traum: vor {hours_ago:.1f}h"
            except (ValueError, TypeError):
                status["description"] = "Idle"
        else:
            status["description"] = "Noch nie geträumt"

        return status

    # ── Utility ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_ts(ts) -> float:
        """Parse timestamp (ISO string or float) to float."""
        if isinstance(ts, (int, float)):
            return float(ts)
        if isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts.replace("Z", "")).timestamp()
            except (ValueError, TypeError):
                pass
        return 0.0


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_INSTANCE: Optional[DreamDaemon] = None
_INSTANCE_LOCK = threading.Lock()


def get_dream_daemon() -> DreamDaemon:
    """Get or create the singleton DreamDaemon."""
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = DreamDaemon()
    return _INSTANCE


# ---------------------------------------------------------------------------
# Standalone entry point (systemd service)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    import argparse
    parser = argparse.ArgumentParser(description="DreamDaemon — Franks Traumphase")
    parser.add_argument("--test", action="store_true", help="Test mode (skip idle check)")
    parser.add_argument("--once", action="store_true", help="Run one dream and exit")
    parser.add_argument("--status", action="store_true", help="Show current status and exit")
    args = parser.parse_args()

    if args.status:
        daemon = DreamDaemon()
        status = daemon.get_status()
        print(json.dumps(status, indent=2, ensure_ascii=False))
        sys.exit(0)

    LOG.info("Starting Dream Daemon v1.0...")

    if args.test:
        LOG.info("TEST MODE — idle check disabled")
        daemon = DreamDaemon(test_mode=True)
    else:
        daemon = DreamDaemon()

    if args.once:
        # Run a single dream session
        daemon._running = True
        daemon._run_dream_session()
        LOG.info("Single dream session complete")
        status = daemon.get_status()
        print(json.dumps(status, indent=2, ensure_ascii=False))
        sys.exit(0)

    daemon.start()

    # Notify systemd
    try:
        import sdnotify
        n = sdnotify.SystemdNotifier()
        n.notify("READY=1")
    except ImportError:
        pass

    import signal as _sig

    def _sigterm_handler(signum, frame):
        LOG.info("Received SIGTERM, shutting down gracefully...")
        daemon.stop()
        sys.exit(0)

    _sig.signal(_sig.SIGTERM, _sigterm_handler)

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        LOG.info("Shutting down...")
        daemon.stop()
