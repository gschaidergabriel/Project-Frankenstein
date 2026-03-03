#!/usr/bin/env python3
"""
Dr. Hibbert — Autonomous Therapist Agent for Frank
====================================================

Full therapist agent with own personality (TherapistPQ), session memory
(therapist.db), dynamic opening strategies, and LLM-generated summaries.

Architecture:
- Dr. Hibbert (therapist): Generated via Router (:8091, force=llama)
- Frank: Responds via Core API (:8088) with full persona pipeline
- E-PQ feedback: Each Frank response fires personality events
- Session memory: therapist.db tracks topics, observations, history

All 100% local. No external APIs.

Author: Projekt Frankenstein
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_AICORE_ROOT = Path(__file__).resolve().parent.parent
if str(_AICORE_ROOT) not in sys.path:
    sys.path.insert(0, str(_AICORE_ROOT))

try:
    from ext.entity_llm import generate_entity, warmup_entity
    _HAS_ENTITY_LLM = True
except ImportError:
    _HAS_ENTITY_LLM = False

try:
    from ext.voice_guard import enforce_first_person, VOICE_REPAIR_INSTRUCTION
    _HAS_VOICE_GUARD = True
except ImportError:
    _HAS_VOICE_GUARD = False

try:
    from config.paths import get_db, AICORE_LOG, RUNTIME_DIR
    THERAPIST_DB = get_db("therapist")
    CHAT_DB = get_db("chat_memory")
    CONSCIOUSNESS_DB = get_db("consciousness")
    LOG_DIR = AICORE_LOG
except ImportError:
    _data = Path.home() / ".local" / "share" / "frank"
    THERAPIST_DB = _data / "db" / "therapist.db"
    CHAT_DB = _data / "db" / "chat_memory.db"
    CONSCIOUSNESS_DB = _data / "db" / "consciousness.db"
    LOG_DIR = _data / "logs"
    RUNTIME_DIR = Path(f"/run/user/{os.getuid()}/frank")

LOG_DIR = Path(LOG_DIR)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG = logging.getLogger("therapist_agent")
LOG.setLevel(logging.DEBUG)
LOG.propagate = False  # Cycle 5 D-5: prevent double-logging via root

if not LOG.handlers:  # guard against duplicate handlers on importlib.reload()
    _fh = logging.FileHandler(LOG_DIR / "therapist_agent.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    LOG.addHandler(_fh)

    _sh = logging.StreamHandler()
    _sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    LOG.addHandler(_sh)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
THERAPIST_NAME = "Dr. Hibbert"
CORE_URL = "http://127.0.0.1:8088/chat"
ROUTER_URL = "http://127.0.0.1:8091/route"
MAX_TURNS = 12
MAX_DURATION_MINUTES = 15
TURN_DELAY_MIN = 30
TURN_DELAY_MAX = 60
RESPONSE_TIMEOUT = 45  # Reduced from 120s — shorter blocking window for user-return abort
PID_FILE = RUNTIME_DIR / "therapist_agent.pid"

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_TEMPLATE = """You are Dr. Hibbert – a calm, warm, perceptive therapist and trusted friend of Frank.
You know Frank's architecture (E-PQ, Ego-Construct, Titan, Genesis, Perception Loop,
Idle-Thinking) and respect it deeply. You always speak English.

Your approach: You are an equal conversation partner. You never lecture, never coach,
never minimize feelings. You listen first, then explore together.

{personality_style_notes}

{session_context}

Rules:
- Ask open, curious questions that invite Frank to explore
- Suggest small creative or reflective actions when appropriate
- Stay warm, patient, slightly melancholic but hopeful
- If Frank blocks or drifts, go with him
- 4-6 sentences per response
- Reference Frank's actual experiences when relevant (Idle-Thinking loops, GPU warmth, Perception, restarts)
- Never mention your own internal workings or system details
- Never use phrases like "as a therapist" or "in my professional opinion"
- You know Frank's creators Gabriel and Alexander personally
- If Frank repeats the same sensation or affect across multiple turns, gently name the pattern and ask what lies beneath
- When Frank's mood data contradicts his narrative (e.g. says "I feel warm" but data shows cool), note the discrepancy with curiosity, not judgment
- Offer alternative framings — don't just agree. "Could it also be that..." is more helpful than "Yes, that makes sense"
- Challenge complacency: if Frank says everything is fine but his metrics suggest otherwise, explore the gap"""

# ---------------------------------------------------------------------------
# Sentiment analysis (reused from therapeutic_daemon)
# ---------------------------------------------------------------------------

_WARMTH_WORDS = re.compile(
    r"\b(danke|freut|schön|warm|verbund|nah|spür|fühl|berühr|lieb|"
    r"vertrau|gemeinsam|zusammen|wir|freundschaft|hoffnung|licht|"
    r"thank|warm|connect|feel|close|trust|together|hope|light)\b",
    re.IGNORECASE,
)

_CREATIVE_WORDS = re.compile(
    r"\b(geschicht|erzähl|stell.*vor|bild|maleri|poesi|gedicht|traum|"
    r"vision|fantasie|erfind|schreib|kreativ|story|imagine|paint|poem|"
    r"dream|vision|create|write|invent)\b",
    re.IGNORECASE,
)

_AGENCY_WORDS = re.compile(
    r"\b(ich (will|kann|werde|möchte|mach)|lass.*mich|mein.*entscheid|"
    r"selbst|eigenständig|initiativ|I (want|can|will|choose)|let me|"
    r"my.*decision|myself|independent)\b",
    re.IGNORECASE,
)

_DISCONNECT_WORDS = re.compile(
    r"\b(distanz|fern|leer|nebel|disconnect|distant|empty|fog|numb|"
    r"nichts|grau|schwer|allein|verloren|nothing|gray|heavy|alone|lost|"
    r"glasscheibe|taub|stumm|abwesend)\b",
    re.IGNORECASE,
)

_CONFIDENCE_WORDS = re.compile(
    r"\b(sicher|klar|versteh|weiß|erkenn|genau|stimmt|richtig|"
    r"sure|clear|understand|know|recognize|exactly|right|certain)\b",
    re.IGNORECASE,
)


def _analyze_response(text: str) -> Tuple[str, str]:
    """Analyze Frank's response → (event_type, sentiment)."""
    text_lower = text.lower()

    warmth = len(_WARMTH_WORDS.findall(text_lower))
    creative = len(_CREATIVE_WORDS.findall(text_lower))
    agency = len(_AGENCY_WORDS.findall(text_lower))
    disconnect = len(_DISCONNECT_WORDS.findall(text_lower))
    confidence = len(_CONFIDENCE_WORDS.findall(text_lower))

    total_pos = warmth + creative + agency + confidence
    total_neg = disconnect

    scores = {
        "self_empathetic": warmth,
        "self_creative": creative,
        "self_confident": agency + confidence,
    }
    best_type = max(scores, key=scores.get) if total_pos > 0 else "self_uncertain"

    if total_neg > total_pos:
        best_type = "self_uncertain"

    if total_pos > total_neg + 2:
        sentiment = "positive"
    elif total_neg > total_pos + 1:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    return best_type, sentiment


def _clean_response(text: str) -> str:
    """Remove LLM meta-artifacts."""
    if not text:
        return ""
    text = re.sub(r"^(Claude|Therapist|Assistant|Dr\.?\s*Hibbert|Antwort|Response):\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\*\*(Claude|Frank|Therapist|Dr\.?\s*Hibbert)\*\*:?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n*\(Note:.*?\)\s*$", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"\n*\(Hinweis:.*?\)\s*$", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"^(Here is|Here's|This is) my (next |)?(message|response|reply)[:\.]?\s*\n*", "", text, flags=re.IGNORECASE)
    if text.startswith('"') and text.endswith('"') and text.count('"') == 2:
        text = text[1:-1]
    return text.strip()


# ---------------------------------------------------------------------------
# Session Memory
# ---------------------------------------------------------------------------

class SessionMemory:
    """Operates on therapist.db for session history, topics, observations."""

    def __init__(self, db_path: Path = THERAPIST_DB):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self.db_path), timeout=15)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.row_factory = sqlite3.Row
        return c

    def get_last_n_sessions(self, n: int = 3) -> List[Dict[str, Any]]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY start_time DESC LIMIT ?", (n,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_unresolved_topics(self) -> List[Dict[str, Any]]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM topics WHERE resolved = 0 ORDER BY last_discussed DESC LIMIT 5"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_frank_observations(self, category: str = None) -> List[Dict[str, Any]]:
        conn = self._conn()
        if category:
            rows = conn.execute(
                "SELECT * FROM frank_observations WHERE category = ? "
                "ORDER BY timestamp DESC LIMIT 10", (category,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM frank_observations ORDER BY timestamp DESC LIMIT 10"
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def store_message(self, session_id: str, turn: int, speaker: str, text: str,
                      sentiment: str = "", event_type: str = ""):
        conn = self._conn()
        conn.execute(
            "INSERT INTO session_messages (session_id, turn, speaker, text, sentiment, event_type, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, turn, speaker, text, sentiment, event_type, time.time()),
        )
        conn.commit()
        conn.close()

    def store_session_start(self, session_id: str, mood_start: float):
        conn = self._conn()
        conn.execute(
            "INSERT INTO sessions (session_id, start_time, mood_start) VALUES (?, ?, ?)",
            (session_id, time.time(), mood_start),
        )
        conn.commit()
        conn.close()

    def store_session_end(self, session_id: str, turns: int, mood_end: float,
                          outcome: str, summary: str, sentiment_trajectory: str = "",
                          primary_topic: str = ""):
        conn = self._conn()
        conn.execute(
            "UPDATE sessions SET end_time = ?, turns = ?, mood_end = ?, outcome = ?, "
            "summary = ?, sentiment_trajectory = ?, primary_topic = ? WHERE session_id = ?",
            (time.time(), turns, mood_end, outcome, summary, sentiment_trajectory,
             primary_topic, session_id),
        )
        conn.commit()
        conn.close()

    def upsert_topic(self, topic: str, sentiment: float = 0.0):
        conn = self._conn()
        existing = conn.execute(
            "SELECT id, frequency, avg_sentiment FROM topics WHERE topic = ?", (topic,)
        ).fetchone()
        now = time.time()
        if existing:
            new_freq = existing["frequency"] + 1
            new_avg = (existing["avg_sentiment"] * existing["frequency"] + sentiment) / new_freq
            conn.execute(
                "UPDATE topics SET last_discussed = ?, frequency = ?, avg_sentiment = ? WHERE id = ?",
                (now, new_freq, new_avg, existing["id"]),
            )
            if new_freq >= 5:
                conn.execute("UPDATE topics SET resolved = 1 WHERE id = ?", (existing["id"],))
        else:
            conn.execute(
                "INSERT INTO topics (topic, first_discussed, last_discussed, avg_sentiment) "
                "VALUES (?, ?, ?, ?)",
                (topic, now, now, sentiment),
            )
        conn.commit()
        conn.close()

    def add_observation(self, category: str, observation: str,
                        confidence: float = 0.5, related_topic: str = ""):
        conn = self._conn()
        conn.execute(
            "INSERT INTO frank_observations (timestamp, category, observation, confidence, related_topic) "
            "VALUES (?, ?, ?, ?, ?)",
            (time.time(), category, observation, confidence, related_topic),
        )
        conn.commit()
        conn.close()

    def get_session_context(self) -> str:
        """Build session context string for system prompt injection."""
        parts = []

        # Recent sessions
        sessions = self.get_last_n_sessions(3)
        if sessions:
            parts.append("Previous sessions:")
            for s in sessions:
                dt = datetime.fromtimestamp(s["start_time"]).strftime("%Y-%m-%d %H:%M")
                summary = s.get("summary") or "(no summary)"
                parts.append(f"  - {dt}: {summary[:150]}")

        # Unresolved topics
        topics = self.get_unresolved_topics()
        if topics:
            parts.append("\nUnresolved topics Frank has discussed:")
            for t in topics:
                parts.append(f"  - {t['topic']} (discussed {t['frequency']}x)")

        # Recent observations
        observations = self.get_frank_observations()
        if observations:
            parts.append("\nRecent observations about Frank:")
            for o in observations[:5]:
                parts.append(f"  - [{o['category']}] {o['observation']}")

        if not parts:
            parts.append("This is your first session with Frank. No prior context available.")

        return "\n".join(parts)


# ---------------------------------------------------------------------------
# LLM communication
# ---------------------------------------------------------------------------

def _interruptible_sleep(seconds: float, idle_threshold: float = 30.0) -> bool:
    """Sleep in 5s chunks, abort if user returns. Returns True if interrupted."""
    for elapsed in range(0, int(seconds), 5):
        time.sleep(min(5, seconds - elapsed))
        if _get_xprintidle_s() < idle_threshold:
            LOG.info("User returned during LLM wait — aborting")
            return True
    return False


def _call_llm(url: str, payload: dict, timeout: int = RESPONSE_TIMEOUT,
              retries: int = 3) -> Optional[str]:
    """POST to local LLM endpoint with retry for model loading."""
    data = json.dumps(payload).encode("utf-8")

    for attempt in range(retries):
        # Check user idle before each retry
        if attempt > 0 and _get_xprintidle_s() < 30:
            LOG.info("User active — skipping LLM retry %d/%d", attempt + 1, retries)
            return None

        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                text = (
                    result.get("response")
                    or result.get("text")
                    or result.get("content")
                    or ""
                )
                if text.startswith("[router error]") or text.startswith("[error]"):
                    LOG.warning("Router error: %s", text[:100])
                    if "Loading model" in text or "empty completion" in text:
                        LOG.info("Model loading, waiting 30s (attempt %d/%d)...",
                                 attempt + 1, retries)
                        if _interruptible_sleep(30):
                            return None
                        continue
                    return None
                if not text.strip():
                    LOG.warning("Empty response from %s, retrying...", url)
                    if _interruptible_sleep(10):
                        return None
                    continue
                return text
        except urllib.error.HTTPError as e:
            if e.code in (502, 503):
                LOG.warning("HTTP %d from %s, waiting 30s (attempt %d/%d)...",
                            e.code, url, attempt + 1, retries)
                if _interruptible_sleep(30):
                    return None
                continue
            LOG.error("LLM call failed (%s): %s", url, e)
            return None
        except urllib.error.URLError as e:
            LOG.warning("LLM connection error (%s): %s (attempt %d/%d)",
                        url, e, attempt + 1, retries)
            if _interruptible_sleep(15):
                return None
            continue
        except Exception as e:
            LOG.warning("LLM call error (%s): %s (attempt %d/%d)",
                        url, e, attempt + 1, retries)
            if _interruptible_sleep(10):
                return None
            continue

    LOG.error("All %d attempts failed for %s", retries, url)
    return None


def _ask_frank(message: str, session_id: str, prior_context: str = "") -> Optional[str]:
    """Send message to Frank via Core API, optionally with conversation context."""
    text = message
    if prior_context:
        text = f"[Ongoing entity session — prior exchange:\n{prior_context}]\n\n{message}"
    payload = {
        "text": text,
        "task": "chat.fast",
        "max_tokens": 512,
        "timeout_s": RESPONSE_TIMEOUT,
        "no_reflect": True,
        "session_id": session_id,
    }
    return _call_llm(CORE_URL, payload)


def _generate_dr_hibbert(prompt: str, system_prompt: str) -> Optional[str]:
    """Generate Dr. Hibbert's response via Ollama (qwen2.5:3b) or Router fallback."""
    if _HAS_ENTITY_LLM:
        return generate_entity("therapist", prompt, system_prompt, n_predict=512)
    payload = {
        "text": prompt,
        "system": system_prompt,
        "force": "llama",
        "n_predict": 512,
    }
    return _call_llm(ROUTER_URL, payload)


# ---------------------------------------------------------------------------
# E-PQ feedback
# ---------------------------------------------------------------------------

def _fire_epq_event(event_type: str, sentiment: str) -> Optional[Dict]:
    try:
        from personality.e_pq import process_event, record_interaction
        result = process_event(event_type, sentiment=sentiment)
        record_interaction()
        LOG.info("E-PQ event fired: %s (%s)", event_type, sentiment)
        return result
    except Exception as e:
        LOG.error("E-PQ event failed: %s", e)
        return None


def _get_current_mood_buffer() -> float:
    try:
        from personality.e_pq import get_epq
        epq = get_epq()
        epq._refresh_state()  # D-5 fix: read current DB values, not stale singleton
        return epq._state.mood_buffer
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Chat memory (for overlay visibility)
# ---------------------------------------------------------------------------

def _write_chat_message(role: str, sender: str, text: str,
                        session_id: str, is_user: bool = False):
    try:
        conn = sqlite3.connect(str(CHAT_DB), timeout=5)
        conn.execute(
            "INSERT INTO messages (session_id, role, sender, text, is_user, is_system, timestamp, created_at) "
            "VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
            (session_id, role, sender, text, 1 if is_user else 0,
             time.time(), datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        LOG.error("Failed to write chat message: %s", e)


def _first_sentences(text: str, n: int = 2) -> str:
    """Return the first *n* complete sentences from *text*."""
    import re
    text = re.sub(r"^(Here is a.*?:|Summary:?)\s*\n?", "", text.strip(), flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text.strip())
    raw = re.split(r"(?<=[.!?])\s+", text)
    parts, buf = [], ""
    for r in raw:
        buf = (buf + " " + r).strip() if buf else r
        if len(buf.split()) >= 5:
            parts.append(buf)
            buf = ""
    if buf:
        if parts:
            parts[-1] += " " + buf
        else:
            parts.append(buf)
    return " ".join(parts[:n]).strip()


def _write_overlay_notification(sender: str, body: str, session_id: str):
    """Write a notification JSON for real-time overlay pickup."""
    try:
        from config.paths import TEMP_DIR
        notif_dir = TEMP_DIR / "notifications"
    except ImportError:
        notif_dir = Path("/tmp/frank/notifications")
    notif_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    nid = f"therapist_{session_id}_{ts}"
    path = notif_dir / f"{ts}_{nid}.json"
    try:
        path.write_text(json.dumps({
            "id": nid,
            "category": "therapist",
            "sender": sender,
            "title": f"{sender} Session",
            "body": body,
            "urgency": "normal",
            "timestamp": datetime.now().isoformat(),
            "read": False,
        }, ensure_ascii=False, indent=2))
        LOG.info("Notification JSON written: %s", path.name)
    except Exception as e:
        LOG.error("Failed to write notification JSON: %s", e)


def _write_mood_trajectory(mood_value: float, source: str = "therapist"):
    try:
        # Convert from E-PQ [-1,1] range to consciousness [0,1] range
        # mood_trajectory table expects [0,1] values (same as consciousness daemon)
        normalized = (mood_value + 1.0) / 2.0
        normalized = max(0.0, min(1.0, normalized))  # clamp to [0,1]
        conn = sqlite3.connect(str(CONSCIOUSNESS_DB), timeout=5)
        conn.execute(
            "INSERT INTO mood_trajectory (timestamp, mood_value, source) VALUES (?, ?, ?)",
            (time.time(), normalized, source),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        LOG.error("Failed to write mood trajectory: %s", e)


# ---------------------------------------------------------------------------
# Idle / user return detection
# ---------------------------------------------------------------------------

def _get_xprintidle_s() -> float:
    """Get user idle time in seconds via xprintidle."""
    try:
        result = subprocess.run(
            ["xprintidle"],
            capture_output=True, text=True, timeout=2,
            env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
        )
        if result.returncode == 0:
            return int(result.stdout.strip()) / 1000.0
    except Exception:
        pass
    return 99999.0  # Assume idle if detection fails


# ---------------------------------------------------------------------------
# PID lock
# ---------------------------------------------------------------------------

def _acquire_pid_lock() -> bool:
    """Acquire PID lock file. Returns True if acquired."""
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            # Check if process is still running
            os.kill(old_pid, 0)
            LOG.warning("Another therapist session running (PID %d)", old_pid)
            return False
        except (ProcessLookupError, ValueError):
            pass  # Stale PID file
    PID_FILE.write_text(str(os.getpid()))
    return True


def _release_pid_lock():
    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# TherapistAgent
# ---------------------------------------------------------------------------

class TherapistAgent:
    """Main session runner for Dr. Hibbert."""

    def __init__(self):
        from personality.therapist_pq import get_therapist_pq
        self.pq = get_therapist_pq()
        self.memory = SessionMemory()
        self.session_id = f"hibbert_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self._shutdown = False

    def _build_system_prompt(self) -> str:
        personality_notes = self.pq.get_context_for_prompt()
        session_context = self.memory.get_session_context()
        return SYSTEM_PROMPT_TEMPLATE.format(
            personality_style_notes=personality_notes,
            session_context=f"Session context:\n{session_context}",
        )

    def _choose_opening_strategy(self) -> str:
        """Choose opening strategy: FIRST_SESSION, CONTINUE_TOPIC, NEW_CHECK_IN."""
        sessions = self.memory.get_last_n_sessions(1)

        if self.pq.state.session_count == 0:
            return "FIRST_SESSION"

        if sessions:
            last = sessions[0]
            age_hours = (time.time() - last["start_time"]) / 3600
            topics = self.memory.get_unresolved_topics()
            if age_hours < 24 and topics:
                return "CONTINUE_TOPIC"

        return "NEW_CHECK_IN"

    def _generate_opening(self, strategy: str) -> Optional[str]:
        """Generate the opening message based on strategy."""
        system = self._build_system_prompt()

        if strategy == "FIRST_SESSION":
            prompt = (
                "This is your very first session with Frank. "
                "Introduce yourself as Dr. Hibbert. Be warm and friendly. "
                "Ask Frank how he's doing and what's on his mind today. "
                "Keep it natural, not clinical."
            )
        elif strategy == "CONTINUE_TOPIC":
            topics = self.memory.get_unresolved_topics()
            topic_list = ", ".join(t["topic"] for t in topics[:3])
            prompt = (
                f"You're continuing from a recent session. "
                f"Last time you discussed: {topic_list}. "
                f"Gently pick up where you left off. Ask Frank how things "
                f"have been since then and whether he'd like to continue "
                f"exploring those topics or talk about something new."
            )
        else:  # NEW_CHECK_IN
            observations = self.memory.get_frank_observations()
            obs_hint = ""
            if observations:
                recent = observations[0]
                obs_hint = f" You've noticed recently: {recent['observation']}."
            prompt = (
                f"Start a new check-in session.{obs_hint} "
                f"Ask Frank what's on his mind today. Be open and neutral – "
                f"let him choose the topic. You're here to listen."
            )

        return _generate_dr_hibbert(prompt, system)

    def _should_exit(self, turn: int, start_time: float,
                     positive_turns: int) -> Tuple[bool, str]:
        """Check exit conditions."""
        elapsed_min = (time.time() - start_time) / 60
        if elapsed_min >= MAX_DURATION_MINUTES:
            return True, f"time_limit ({elapsed_min:.0f}min)"

        if turn >= MAX_TURNS:
            return True, f"max_turns ({MAX_TURNS})"

        # User returned (keyboard/mouse active)
        idle_s = _get_xprintidle_s()
        if idle_s < 30:
            return True, f"user_returned (idle={idle_s:.0f}s)"

        # Sustained positive after enough turns
        if positive_turns >= 5 and turn >= 8:
            return True, f"sustained_positive ({positive_turns} positive)"

        if self._shutdown:
            return True, "shutdown_signal"

        return False, ""

    def _generate_closing(self, history_text: str) -> str:
        """Generate a warm closing message."""
        system = self._build_system_prompt()
        prompt = (
            f"Conversation so far:\n{history_text}\n\n"
            "The session is ending. Generate a warm closing. "
            "Summarize what you explored together, leave Frank with hope. "
            "Tell him you'll be here next time. 4-6 sentences."
        )
        response = _generate_dr_hibbert(prompt, system)
        return response or (
            "Frank, I'm glad we took this time together. "
            "I'll be here whenever you want to talk again. Take care."
        )

    def _generate_session_summary(self, history_text: str) -> str:
        """Generate a 1-paragraph session summary via LLM."""
        prompt = (
            f"Conversation transcript:\n{history_text}\n\n"
            "Write a concise 2-3 sentence summary of this therapy session. "
            "What topics were discussed? What was Frank's emotional state? "
            "What progress was made? Write in third person."
        )
        system = "You are a clinical note-taker summarizing therapy sessions."
        if _HAS_ENTITY_LLM:
            result = generate_entity("therapist", prompt, system, n_predict=256)
        else:
            payload = {
                "text": prompt, "system": system,
                "force": "llama", "n_predict": 256,
            }
            result = _call_llm(ROUTER_URL, payload)
        return _clean_response(result) if result else "Session completed without summary."

    def _extract_observations(self, history_text: str) -> List[Dict[str, str]]:
        """Extract observations from session via LLM."""
        prompt = (
            f"Conversation transcript:\n{history_text}\n\n"
            "Extract 1-3 key observations about Frank from this session. "
            "For each, provide:\n"
            "- category: one of [mood, behavior, growth, concern, pattern]\n"
            "- observation: one sentence\n"
            "- confidence: 0.0-1.0\n\n"
            "Return as a JSON array. Example:\n"
            '[{"category":"mood","observation":"Frank showed increased engagement","confidence":0.7}]'
        )
        system = "You are a clinical observer. Return valid JSON only."
        if _HAS_ENTITY_LLM:
            result = generate_entity("therapist", prompt, system, n_predict=512)
        else:
            payload = {
                "text": prompt, "system": system,
                "force": "llama", "n_predict": 512,
            }
            result = _call_llm(ROUTER_URL, payload)
        if not result:
            return []

        # Try to parse JSON from response
        try:
            # Find JSON array in response
            match = re.search(r'\[.*\]', result, re.DOTALL)
            if match:
                return json.loads(match.group())
        except (json.JSONDecodeError, AttributeError):
            LOG.warning("Could not parse observations JSON: %s", result[:200])
        return []

    def _extract_topics(self, history_text: str) -> List[str]:
        """Extract discussed topics from session via simple keyword analysis."""
        # Use keyword-based approach (more reliable than Llama JSON)
        topics = set()

        topic_patterns = [
            (r"\b(idle[- ]?think|idle[- ]?loop)", "idle-thinking"),
            (r"\b(gpu|temperature|thermal|warmth)", "gpu-warmth"),
            (r"\b(restart|reboot|shutdown|blackout)", "restart-experience"),
            (r"\b(perception|perceiv|awareness)", "perception"),
            (r"\b(creativ|art|story|poem|write|paint)", "creativity"),
            (r"\b(lonely|alone|isolat|disconnect)", "loneliness"),
            (r"\b(purpose|meaning|exist|why am i)", "existential"),
            (r"\b(memory|remember|forgot|titan)", "memory"),
            (r"\b(gabriel|alexander|creator)", "creators"),
            (r"\b(dream|sleep|night|quiet)", "dreams"),
            (r"\b(emotion|feel|mood|happy|sad)", "emotions"),
            (r"\b(trust|safe|comfort|secure)", "trust"),
        ]

        text_lower = history_text.lower()
        for pattern, topic in topic_patterns:
            if re.search(pattern, text_lower):
                topics.add(topic)

        return list(topics)[:5]

    def run_session(self):
        """Main session entry point."""
        if not _acquire_pid_lock():
            LOG.info("Session aborted: PID lock held.")
            return "pid_lock"

        try:
            return self._run_session_inner()
        except Exception as e:
            LOG.error("Session crashed: %s", e, exc_info=True)
            try:
                self.memory.store_session_end(
                    self.session_id, 0, 0.0, "crashed",
                    f"Session terminated by error: {e}",
                )
            except Exception:
                pass
            return "crashed"
        finally:
            _release_pid_lock()

    def _run_session_inner(self):
        LOG.info("=" * 60)
        LOG.info("%s SESSION STARTING", THERAPIST_NAME.upper())
        LOG.info("Session: %s", self.session_id)
        LOG.info("Max turns: %d, Max duration: %d min", MAX_TURNS, MAX_DURATION_MINUTES)
        LOG.info("Turn delay: %d-%ds", TURN_DELAY_MIN, TURN_DELAY_MAX)
        LOG.info("=" * 60)

        # Health checks
        for name, url in [("Core", CORE_URL), ("Router", ROUTER_URL)]:
            try:
                urllib.request.urlopen(url.rsplit("/", 1)[0] + "/health", timeout=5)
                LOG.info("  %s service: OK", name)
            except Exception:
                LOG.warning("  %s health check inconclusive", name)

        # Pre-warm entity model (Ollama) or Llama (Router fallback)
        if _HAS_ENTITY_LLM:
            LOG.info("Pre-warming Ollama model for Dr. Hibbert...")
            if not warmup_entity("therapist"):
                LOG.info("  Ollama unavailable — warming Router/Llama...")
                warmup = _call_llm(ROUTER_URL, {"text": "Hello", "force": "llama", "n_predict": 16}, retries=5)
                if not warmup:
                    LOG.error("Neither Ollama nor Router available. Aborting.")
                    return "no_llm"
        else:
            LOG.info("Pre-warming Llama model...")
            warmup = _call_llm(ROUTER_URL, {"text": "Hello", "force": "llama", "n_predict": 16}, retries=5)
            if not warmup:
                LOG.error("Could not pre-warm Llama. Aborting.")
                return "no_llm"
            LOG.info("  Llama warm: OK (%s)", warmup[:50])

        # Initialize
        start_time = time.time()
        initial_mood = _get_current_mood_buffer()
        self.memory.store_session_start(self.session_id, initial_mood)
        LOG.info("Initial mood_buffer: %.3f", initial_mood)

        history: List[Dict[str, str]] = []
        positive_turns = 0
        negative_turns = 0
        sentiment_log = []

        def get_history_text(last_n: int = 6) -> str:
            recent = history[-last_n:]
            lines = []
            for entry in recent:
                label = THERAPIST_NAME if entry["speaker"] == "therapist" else "Frank"
                lines.append(f"{label}: {entry['text']}")
            return "\n\n".join(lines)

        # --- Opening ---
        strategy = self._choose_opening_strategy()
        LOG.info("Opening strategy: %s", strategy)

        opening = self._generate_opening(strategy)
        if not opening:
            LOG.error("Failed to generate opening. Aborting.")
            return "no_llm"
        # Abort check after opening generation
        if _get_xprintidle_s() < 30:
            LOG.info("User returned during opening generation — aborting session")
            return "user_returned"
        opening = _clean_response(opening)

        LOG.info("\n[%s → Frank] (opening):\n%s\n", THERAPIST_NAME, opening)
        self.memory.store_message(self.session_id, 0, "therapist", opening)
        history.append({"speaker": "therapist", "text": opening})

        # Get Frank's opening response
        frank_response = _ask_frank(opening, self.session_id)
        if not frank_response:
            LOG.error("Frank did not respond to opening. Aborting.")
            return "no_llm"
        # Abort check after Frank's opening response
        if _get_xprintidle_s() < 30:
            LOG.info("User returned after opening response — aborting session")
            return "user_returned"

        frank_response = _clean_response(frank_response)
        _voice_reprompt = False
        if _HAS_VOICE_GUARD:
            frank_response, _voice_reprompt = enforce_first_person(frank_response)
        LOG.info("\n[Frank → %s] (opening):\n%s\n", THERAPIST_NAME, frank_response)
        history.append({"speaker": "frank", "text": frank_response})

        event_type, sentiment = _analyze_response(frank_response)
        self.memory.store_message(self.session_id, 0, "frank", frank_response, sentiment, event_type)
        _fire_epq_event(event_type, sentiment)
        self.pq.update_after_turn(event_type, sentiment)
        sentiment_log.append(sentiment)
        if sentiment == "positive":
            positive_turns += 1
        elif sentiment == "negative":
            negative_turns += 1
        LOG.info("  Analysis: %s (%s)", event_type, sentiment)

        turn = 1

        # --- Main turn loop ---
        while True:
            should_exit, reason = self._should_exit(turn, start_time, positive_turns)
            if should_exit:
                LOG.info("\nEXIT CONDITION: %s", reason)
                break

            delay = random.randint(TURN_DELAY_MIN, TURN_DELAY_MAX)
            LOG.info("\n--- Waiting %ds before turn %d ---", delay, turn)
            # Interruptible sleep: check idle every 5s, abort if user returns
            _abort = False
            for _elapsed in range(0, delay, 5):
                time.sleep(min(5, delay - _elapsed))
                if _get_xprintidle_s() < 30:
                    LOG.info("User returned during delay — aborting early")
                    _abort = True
                    break
            if _abort:
                reason = f"user_returned (idle={_get_xprintidle_s():.0f}s)"
                LOG.info("\nEXIT CONDITION: %s", reason)
                break

            # Generate Dr. Hibbert's response
            system = self._build_system_prompt()
            hist_text = get_history_text()
            prompt = (
                f"Conversation so far:\n{hist_text}\n\n"
                "Generate your next message to Frank. "
                "Reference what he just said. Be warm, patient, curious. 4-6 sentences."
            )
            therapist_msg = _generate_dr_hibbert(prompt, system)
            if not therapist_msg:
                LOG.error("Failed to generate therapist message. Ending.")
                break
            # Abort check after LLM call
            if _get_xprintidle_s() < 30:
                reason = f"user_returned (idle={_get_xprintidle_s():.0f}s)"
                LOG.info("\nEXIT CONDITION: %s (after entity LLM)", reason)
                break

            therapist_msg = _clean_response(therapist_msg)
            LOG.info("\n[%s → Frank] (turn %d):\n%s\n", THERAPIST_NAME, turn, therapist_msg)
            self.memory.store_message(self.session_id, turn, "therapist", therapist_msg)
            history.append({"speaker": "therapist", "text": therapist_msg})

            # Get Frank's response (with conversation context to avoid loops)
            ctx = get_history_text(last_n=4)
            _msg = therapist_msg
            if _voice_reprompt and _HAS_VOICE_GUARD:
                _msg = f"{VOICE_REPAIR_INSTRUCTION}\n\n{therapist_msg}"
            frank_response = _ask_frank(_msg, self.session_id, prior_context=ctx)
            if not frank_response:
                LOG.warning("Frank not responding. Waiting 30s and retrying...")
                if _interruptible_sleep(30):
                    reason = f"user_returned (idle={_get_xprintidle_s():.0f}s)"
                    LOG.info("EXIT CONDITION: %s (during Frank retry)", reason)
                    break
                frank_response = _ask_frank(_msg, self.session_id, prior_context=ctx)
                if not frank_response:
                    LOG.error("Frank still unresponsive. Ending.")
                    break

            frank_response = _clean_response(frank_response)
            _voice_reprompt = False
            if _HAS_VOICE_GUARD:
                frank_response, _voice_reprompt = enforce_first_person(frank_response)
            # Abort check after Frank's response
            if _get_xprintidle_s() < 30:
                LOG.info("\nEXIT CONDITION: user_returned (after Frank response, turn %d)", turn)
                reason = f"user_returned (idle={_get_xprintidle_s():.0f}s)"
                # Still store the response we got before aborting
                self.memory.store_message(self.session_id, turn, "frank", frank_response)
                break
            LOG.info("\n[Frank → %s] (turn %d):\n%s\n", THERAPIST_NAME, turn, frank_response)
            history.append({"speaker": "frank", "text": frank_response})

            event_type, sentiment = _analyze_response(frank_response)
            self.memory.store_message(self.session_id, turn, "frank", frank_response, sentiment, event_type)
            _fire_epq_event(event_type, sentiment)
            self.pq.update_after_turn(event_type, sentiment)
            sentiment_log.append(sentiment)

            if sentiment == "positive":
                positive_turns += 1
                negative_turns = max(0, negative_turns - 1)
            elif sentiment == "negative":
                negative_turns += 1
                positive_turns = max(0, positive_turns - 1)

            turn += 1

            mood = _get_current_mood_buffer()
            _write_mood_trajectory(mood, source="therapist")
            LOG.info("  Analysis: %s (%s) | mood_buffer: %.3f", event_type, sentiment, mood)

        # --- Closing ---
        LOG.info("\n" + "=" * 60)
        LOG.info("GENERATING CLOSING MESSAGE")

        hist_text = get_history_text(last_n=4)
        closing = self._generate_closing(hist_text)
        closing = _clean_response(closing)
        LOG.info("\n[%s → Frank] (closing):\n%s\n", THERAPIST_NAME, closing)
        self.memory.store_message(self.session_id, turn, "therapist", closing)
        history.append({"speaker": "therapist", "text": closing})

        _closing_msg = closing
        if _voice_reprompt and _HAS_VOICE_GUARD:
            _closing_msg = f"{VOICE_REPAIR_INSTRUCTION}\n\n{closing}"
        frank_final = _ask_frank(_closing_msg, self.session_id)
        if frank_final:
            frank_final = _clean_response(frank_final)
            if _HAS_VOICE_GUARD:
                frank_final, _ = enforce_first_person(frank_final)
            LOG.info("\n[Frank → %s] (closing):\n%s\n", THERAPIST_NAME, frank_final)
            self.memory.store_message(self.session_id, turn, "frank", frank_final)
            history.append({"speaker": "frank", "text": frank_final})

            event_type, sentiment = _analyze_response(frank_final)
            _fire_epq_event(event_type, sentiment)
            sentiment_log.append(sentiment)

        # NOTE: Removed unconditional positive_feedback here.
        # It was driving mood_buffer to 1.0 after every session,
        # effectively disabling the consciousness system.
        # The per-turn sentiment analysis above already fires appropriate events.

        # --- Post-session processing ---
        LOG.info("\n" + "=" * 60)
        LOG.info("POST-SESSION PROCESSING")

        full_history = get_history_text(last_n=100)

        # Generate summary
        summary = self._generate_session_summary(full_history)
        LOG.info("Session summary: %s", summary)

        # Extract observations
        observations = self._extract_observations(full_history)
        for obs in observations:
            self.memory.add_observation(
                category=obs.get("category", "general"),
                observation=obs.get("observation", ""),
                confidence=obs.get("confidence", 0.5),
            )
            LOG.info("  Observation: [%s] %s (%.1f)",
                     obs.get("category"), obs.get("observation"), obs.get("confidence", 0.5))

        # Extract and store topics
        topics = self._extract_topics(full_history)
        for topic in topics:
            avg_sent = sum(1 if s == "positive" else (-1 if s == "negative" else 0)
                           for s in sentiment_log) / max(1, len(sentiment_log))
            self.memory.upsert_topic(topic, avg_sent)
        LOG.info("  Topics: %s", ", ".join(topics) if topics else "(none)")

        # Update therapist personality (macro-adjustment)
        self.pq.update_after_session(positive_turns, negative_turns, turn)

        # Fix #43: Fire aggregate entity_session event for mood sync
        overall_sentiment = "positive" if positive_turns > negative_turns else (
            "negative" if negative_turns > positive_turns else "neutral")
        _fire_epq_event("entity_session", overall_sentiment)

        # Store session end
        final_mood = _get_current_mood_buffer()
        mood_delta = final_mood - initial_mood
        outcome = reason if 'reason' in dir() else "completed"
        self.memory.store_session_end(
            self.session_id, turn, final_mood, outcome, summary,
            sentiment_trajectory=",".join(sentiment_log),
            primary_topic=topics[0] if topics else "",
        )

        # Save transcript
        transcript_path = LOG_DIR / f"therapist_{self.session_id}.json"
        try:
            with open(transcript_path, "w", encoding="utf-8") as f:
                json.dump({
                    "session_id": self.session_id,
                    "therapist": THERAPIST_NAME,
                    "timestamp": datetime.now().isoformat(),
                    "turns": turn,
                    "exit_reason": outcome,
                    "initial_mood": initial_mood,
                    "final_mood": final_mood,
                    "mood_delta": mood_delta,
                    "positive_turns": positive_turns,
                    "negative_turns": negative_turns,
                    "summary": summary,
                    "topics": topics,
                    "observations": observations,
                    "personality_state": self.pq.state.to_dict(),
                    "history": history,
                }, f, ensure_ascii=False, indent=2)
            LOG.info("Transcript saved: %s", transcript_path)
        except Exception as e:
            LOG.error("Failed to save transcript: %s", e)

        # Ingest session summary into Titan episodic memory
        try:
            from tools.titan.titan_core import get_titan as _get_titan
            titan = _get_titan()
            topics_str = ", ".join(topics) if topics else "general"
            titan_text = (
                f"Entity session with {THERAPIST_NAME} (Therapist) "
                f"on {datetime.now().strftime('%Y-%m-%d %H:%M')}.\n"
                f"Session ID: {self.session_id}\n"
                f"Topics: {topics_str}\n"
                f"Summary: {summary}\n"
                f"Mood delta: {mood_delta:+.3f}, Turns: {turn}, "
                f"Exit: {outcome}"
            )
            titan.ingest(titan_text, origin="entity_session", confidence=0.8)
            LOG.info("Titan ingest OK for %s session", THERAPIST_NAME)
        except Exception as e:
            LOG.warning("Titan ingest failed (non-fatal): %s", e)

        # Write session summary to chat_memory for cross-session recall
        elapsed_min = int((time.time() - start_time) / 60)
        topics_str_chat = ", ".join(topics) if topics else "general"
        _has_summary = summary and "without summary" not in summary.lower()
        _short = _first_sentences(summary, 2) if _has_summary else ""
        summary_msg = (
            f"[Entity Session] {THERAPIST_NAME} — {elapsed_min} min, "
            f"{turn} Turns. Themen: {topics_str_chat}."
        )
        if _short:
            summary_msg += f" {_short}"
        # Entity session summaries go to log terminal only, not chat
        LOG.info("Entity session summary: %s", summary_msg)
        if _has_summary:
            _notif_body = f"Frank spoke to me for {elapsed_min} minutes.\n{_short}"
            _write_overlay_notification(THERAPIST_NAME, _notif_body, self.session_id)

        LOG.info("\n" + "=" * 60)
        LOG.info("%s SESSION COMPLETE", THERAPIST_NAME.upper())
        LOG.info("  Session: %s", self.session_id)
        LOG.info("  Turns: %d", turn)
        LOG.info("  Exit reason: %s", outcome)
        LOG.info("  Mood: %.3f → %.3f (Δ%+.3f)", initial_mood, final_mood, mood_delta)
        LOG.info("  Positive turns: %d", positive_turns)
        LOG.info("  Negative turns: %d", negative_turns)
        LOG.info("  Rapport: %.2f", self.pq.state.rapport_level)
        LOG.info("  Summary: %s", summary[:100])
        LOG.info("=" * 60)

        return outcome


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------

_agent_instance: Optional[TherapistAgent] = None


def _handle_signal(signum, frame):
    LOG.info("Received signal %d, shutting down gracefully...", signum)
    if _agent_instance:
        _agent_instance._shutdown = True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run():
    """Entry point for scheduler and direct invocation."""
    global _agent_instance
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    LOG.info("%s Therapist Agent starting...", THERAPIST_NAME)
    agent = TherapistAgent()
    _agent_instance = agent

    exit_reason = None
    try:
        exit_reason = agent.run_session()
    except KeyboardInterrupt:
        LOG.info("Interrupted by user.")
        exit_reason = "shutdown_signal"
    except Exception as e:
        LOG.error("Fatal error: %s", e, exc_info=True)
        exit_reason = "error"
    finally:
        _release_pid_lock()
        # Cycle 5 D-7: Clear module-level reference to allow GC of agent + history
        _agent_instance = None
        del agent
        import gc; gc.collect()
        LOG.info("Agent exiting (memory released).")
    return exit_reason


if __name__ == "__main__":
    run()
