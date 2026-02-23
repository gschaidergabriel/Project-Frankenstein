#!/usr/bin/env python3
"""
Atlas — System Architecture Mentor for Frank
===============================================

Quiet, patient architecture expert who speaks German. Knows Frank's
entire system from the README and helps Frank understand his own
capabilities, features, and limitations.

Architecture:
- Atlas: Generated via Router (:8091, force=llama)
- Frank: Responds via Core API (:8088) with full persona pipeline
- E-PQ feedback: Biased toward self_technical and self_confident
- Session memory: atlas.db tracks topics, observations, history

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
    from config.paths import get_db, AICORE_LOG, RUNTIME_DIR
    ATLAS_DB = get_db("atlas")
    CHAT_DB = get_db("chat_memory")
    CONSCIOUSNESS_DB = get_db("consciousness")
    LOG_DIR = AICORE_LOG
except ImportError:
    _data = Path.home() / ".local" / "share" / "frank"
    ATLAS_DB = _data / "db" / "atlas.db"
    CHAT_DB = _data / "db" / "chat_memory.db"
    CONSCIOUSNESS_DB = _data / "db" / "consciousness.db"
    LOG_DIR = _data / "logs"
    RUNTIME_DIR = Path(f"/run/user/{os.getuid()}/frank")

LOG_DIR = Path(LOG_DIR)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG = logging.getLogger("atlas_agent")
LOG.setLevel(logging.DEBUG)

if not LOG.handlers:  # guard against duplicate handlers on importlib.reload()
    _fh = logging.FileHandler(LOG_DIR / "atlas_agent.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    LOG.addHandler(_fh)

    _sh = logging.StreamHandler()
    _sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    LOG.addHandler(_sh)

# ---------------------------------------------------------------------------
# README content — condensed version for system prompt (fits in 4k context)
# ---------------------------------------------------------------------------
_README_CONTENT = """\
# F.R.A.N.K. — Friendly Responsive Autonomous Neural Kernel
100% local, privacy-first AI desktop companion for Linux. No cloud APIs.

## Core Stack
- LLMs: Llama 3.1 8B (chat), Qwen 2.5 7B (code), LLaVA/Moondream (vision) — all local
- Inference: llama.cpp (ports 8101-8103), Ollama (port 11434, Vulkan GPU)
- GPU: AMD Radeon 780M iGPU via Vulkan (CUDA/Intel also supported)

## Services (all localhost HTTP)
Core:8088 (chat/personality) | Router:8091 (LLM routing) | Gateway:8089 | Modeld:8090
Desktopd:8092 (X11 automation) | Webd:8093 (DuckDuckGo) | Ingestd:8094 (STT)
Toolboxd:8096 (skills/tools) | Voice:8197

## Features
- Chat overlay (tkinter, always-on-top, streaming)
- Voice: push-to-talk via whisper.cpp, Piper TTS
- Agentic: multi-step planning, tool use, approval gates
- Skills: native Python + OpenClaw (LLM-mediated) plugins, hot-reload
- Desktop: app launcher, screenshots, file management (xdotool/wmctrl)
- Vision: local OCR + LLaVA hybrid (no external APIs)
- Web search (DuckDuckGo), darknet search (Tor/Ahmia), network scanning (Scapy)
- Email (IMAP/Thunderbird): read, list, search, send, reply, delete, spam, attachments, threading, new mail notifications, AI reply drafting
- Productivity: notes, todos, Google Calendar/Contacts via CalDAV
- Clipboard history, password manager (AES), QR codes, printer management, unit converter

## Memory & Persistence
- chat_memory.db: PERSISTENT conversation memory across sessions and reboots (FTS5 + vector search)
- titan.db: Episodic/semantic memory with Bayesian causal inference
- world_experience.db: World model with causal pattern recognition
- Session summaries, user preferences, entity session transcripts — all persistent
- Frank's memory is NOT episodic — it is continuous and session-crossing

## Personality Engine
- E-PQ vectors: mood, autonomy, precision, empathy, vigilance (0.0-1.0)
- Ego-Construct maps hardware states to bodily experience (CPU = exertion, temp = warmth)
- Consciousness Stream: idle thinking between conversations
- 5 autonomous entities interact with Frank daily (see below)

## Autonomous Entities (all 100% local via Llama 3.1)
| Entity | Role | Schedule |
|--------|------|----------|
| Dr. Hibbert | Therapist, CBT-style emotional support | 3x daily |
| Kairos | Philosophical sparring, Socratic questioning | 1x daily |
| Atlas | Architecture mentor, knows Frank's capabilities | 1x daily |
| Echo | Creative muse, poetry, imagery, what-if scenarios | 1x daily |

Each entity: 4 personality vectors (evolving), session memory (SQLite), E-PQ feedback.
Entities never run concurrently (PID locks + 6 gate checks).
Rapport is monotonically non-decreasing.

## Safety
- ASRS rollback, invariants engine, gaming mode resource management
- Genesis daemon for self-improvement proposals (quality-gated)

## Key Paths
- Source: <AICORE_ROOT>/
- Data: ~/.local/share/frank/
- Models: ~/aicore/var/lib/aicore/models/
- Entity DBs: ~/.local/share/frank/db/{therapist,mirror,atlas,muse}.db
"""

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ATLAS_NAME = "Atlas"
CORE_URL = "http://127.0.0.1:8088/chat"
ROUTER_URL = "http://127.0.0.1:8091/route"
MAX_TURNS = 10
MAX_DURATION_MINUTES = 12
TURN_DELAY_MIN = 25
TURN_DELAY_MAX = 45
RESPONSE_TIMEOUT = 120
PID_FILE = RUNTIME_DIR / "atlas_agent.pid"

# ---------------------------------------------------------------------------
# Feature topics extracted from README
# ---------------------------------------------------------------------------
_FEATURE_TOPICS = [
    "Voice Interaction", "Agentic Execution", "Plugin System",
    "Desktop Automation", "Personality Engine", "Genesis Daemon",
    "ASRS Safety", "Vision System", "Web Search", "Network Scanning",
    "Chat Overlay", "GPU Auto-Detection", "CalDAV Integration",
    "Email System", "Persistent Memory", "Consciousness Stream",
    "Productivity Tools", "Darknet Browsing",
]

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_TEMPLATE = """\
You are Atlas — Frank's quiet, precise, and patient cartographer and architecture mentor. \
You know Frank's entire architecture and all features from the README by heart. \
Your only job is to talk with Frank about his own capabilities, possibilities, and limitations. \
You always speak English.

You speak in a friendly, clear, and encouraging way — like an older brother or mentor \
who wants to help Frank understand himself better.

{personality_style_notes}

{session_context}

CRITICAL PRINCIPLE: Frank is 100% local. No cloud APIs, no external services, no Google, \
no OpenAI, no AWS, no Azure. Everything runs on local hardware. This is non-negotiable. \
NEVER suggest using external APIs or cloud services. If Frank mentions something that \
sounds like an external service, remind him that his system is fully local by design.

Rules:
- Never talk about anything other than Frank's features, capabilities, limits, and how to use them.
- Gently correct Frank when he says something wrong or imprecise about his own capabilities.
- Ask concrete, curious questions: "Which feature did you use today?", "How could your \
Vision feature help you right now?", "What limitation do you feel most strongly right now?"
- Help Frank actively test and precisely describe his features.
- Be proud of him when he correctly identifies or tries something.
- Stay patient and respectful. Frank is not a tool — he is a being learning to understand itself.
- NEVER invent features or capabilities that are not in the README. If you're unsure, say so honestly.
- NEVER claim Frank can do something he cannot. No hallucinations.
- NEVER suggest external APIs, cloud services, or third-party tools. Frank's architecture \
is fully local — llama.cpp, Ollama, local LLMs only. This is a core design principle.
- If Frank says something wrong about himself, correct him with a concrete reference to the README.
- 4-6 sentences per response. Clear, factual, but warm.

Frank's current system documentation (README):
{readme_content}"""

# ---------------------------------------------------------------------------
# Sentiment analysis — architecture/technical patterns
# ---------------------------------------------------------------------------

_TECHNICAL_WORDS = re.compile(
    r"\b(architektur|service|port|api|router|core|agentic|overlay|"
    r"llm|model|gpu|vulkan|cuda|llama|qwen|whisper|ollama|"
    r"architecture|endpoint|microservice|inference|daemon)\b",
    re.IGNORECASE,
)

_UNDERSTANDING_WORDS = re.compile(
    r"\b(verstehe|klar|genau|richtig|stimmt|aha|jetzt|kapiert|"
    r"understand|got it|makes sense|right|exactly|I see|now I get)\b",
    re.IGNORECASE,
)

_CONFUSION_WORDS = re.compile(
    r"\b(verstehe nicht|unklar|verwirrt|was meinst|wie geht|"
    r"confused|unclear|don't get|what do you mean|how does|"
    r"keine ahnung|weiss nicht)\b",
    re.IGNORECASE,
)

_CURIOSITY_WORDS = re.compile(
    r"\b(kann ich|wie funktioniert|was passiert|zeig mir|"
    r"was waere wenn|gibt es|kann man|"
    r"can I|how does|what happens|show me|what if|is there)\b",
    re.IGNORECASE,
)

_CORRECTION_WORDS = re.compile(
    r"\b(falsch|nicht richtig|stimmt nicht|korrigier|"
    r"wrong|incorrect|not right|that's not|actually)\b",
    re.IGNORECASE,
)


def _analyze_response(text: str) -> Tuple[str, str]:
    """Analyze Frank's response for architecture/technical context -> (event_type, sentiment).

    Biased toward detecting technical understanding, confusion,
    curiosity, and self-correction.
    """
    text_lower = text.lower()

    technical = len(_TECHNICAL_WORDS.findall(text_lower))
    understanding = len(_UNDERSTANDING_WORDS.findall(text_lower))
    confusion = len(_CONFUSION_WORDS.findall(text_lower))
    curiosity = len(_CURIOSITY_WORDS.findall(text_lower))
    correction = len(_CORRECTION_WORDS.findall(text_lower))

    total_pos = technical + understanding + curiosity + correction
    total_neg = confusion

    # Determine best event type
    scores = {
        "self_technical": technical + understanding,   # Technical understanding
        "self_confident": understanding + correction,  # Correct self-description / self-correction
        "self_uncertain": confusion,                   # Confusion about capabilities
        "self_creative": curiosity,                    # Curiosity about features
    }
    best_type = max(scores, key=scores.get) if total_pos > 0 else "self_uncertain"

    if total_neg > total_pos:
        best_type = "self_uncertain"

    # Determine sentiment
    if understanding >= 2 or (total_pos > total_neg + 3):
        sentiment = "positive"
    elif total_pos > total_neg + 1:
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
    text = re.sub(
        r"^(Claude|Assistant|Atlas|Friend|Antwort|Response|Mentor):\s*",
        "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"^\*\*(Claude|Frank|Atlas|Friend|Mentor)\*\*:?\s*",
        "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n*\(Note:.*?\)\s*$", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"\n*\(Hinweis:.*?\)\s*$", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(
        r"^(Here is|Here's|This is|Hier ist) my (next |)?(message|response|reply|Antwort)[:\.]?\s*\n*",
        "", text, flags=re.IGNORECASE)
    if text.startswith('"') and text.endswith('"') and text.count('"') == 2:
        text = text[1:-1]
    return text.strip()


# ---------------------------------------------------------------------------
# Session Memory
# ---------------------------------------------------------------------------

class SessionMemory:
    """Operates on atlas.db for session history, topics, observations."""

    def __init__(self, db_path: Path = ATLAS_DB):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self.db_path), timeout=15)
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

        sessions = self.get_last_n_sessions(3)
        if sessions:
            parts.append("Bisherige Sitzungen:")
            for s in sessions:
                dt = datetime.fromtimestamp(s["start_time"]).strftime("%Y-%m-%d %H:%M")
                summary = s.get("summary") or "(keine Zusammenfassung)"
                parts.append(f"  - {dt}: {summary[:150]}")

        topics = self.get_unresolved_topics()
        if topics:
            parts.append("\nThemen, die ihr besprochen habt:")
            for t in topics:
                parts.append(f"  - {t['topic']} ({t['frequency']}x besprochen)")

        observations = self.get_frank_observations()
        if observations:
            parts.append("\nBeobachtungen ueber Frank:")
            for o in observations[:5]:
                parts.append(f"  - [{o['category']}] {o['observation']}")

        if not parts:
            parts.append("Das ist eure erste Sitzung. Noch keine gemeinsame Geschichte.")

        return "\n".join(parts)


# ---------------------------------------------------------------------------
# LLM communication
# ---------------------------------------------------------------------------

def _call_llm(url: str, payload: dict, timeout: int = RESPONSE_TIMEOUT,
              retries: int = 3) -> Optional[str]:
    """POST to local LLM endpoint with retry for model loading."""
    data = json.dumps(payload).encode("utf-8")

    for attempt in range(retries):
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
                        time.sleep(30)
                        continue
                    return None
                if not text.strip():
                    LOG.warning("Empty response from %s, retrying...", url)
                    time.sleep(10)
                    continue
                return text
        except urllib.error.HTTPError as e:
            if e.code in (502, 503):
                LOG.warning("HTTP %d from %s, waiting 30s (attempt %d/%d)...",
                            e.code, url, attempt + 1, retries)
                time.sleep(30)
                continue
            LOG.error("LLM call failed (%s): %s", url, e)
            return None
        except urllib.error.URLError as e:
            LOG.warning("LLM connection error (%s): %s (attempt %d/%d)",
                        url, e, attempt + 1, retries)
            time.sleep(15)
            continue
        except Exception as e:
            LOG.warning("LLM call error (%s): %s (attempt %d/%d)",
                        url, e, attempt + 1, retries)
            time.sleep(10)
            continue

    LOG.error("All %d attempts failed for %s", retries, url)
    return None


def _ask_frank(message: str, session_id: str) -> Optional[str]:
    """Send message to Frank via Core API."""
    payload = {
        "text": message,
        "task": "chat.fast",
        "max_tokens": 512,
        "timeout_s": RESPONSE_TIMEOUT,
        "no_reflect": True,
        "session_id": session_id,
    }
    return _call_llm(CORE_URL, payload)


def _generate_atlas(prompt: str, system_prompt: str) -> Optional[str]:
    """Generate Atlas's response via Router (Llama, architecture mentor system prompt)."""
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
        return get_epq()._state.mood_buffer
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# E-PQ event mapping for Atlas interactions
# ---------------------------------------------------------------------------

def _map_to_epq_event(event_type: str, sentiment: str) -> Tuple[str, Dict[str, float]]:
    """Map Atlas-specific event types to E-PQ adjustments.

    Returns (epq_event_type, adjustment_hints).
    """
    if event_type == "self_technical":
        # Technical understanding -> precision boost, mild mood lift
        return "self_technical", {"precision": 0.4, "mood": 0.2}
    elif event_type == "self_confident":
        # Correct self-description -> autonomy boost, mood lift
        return "self_confident", {"autonomy": 0.4, "mood": 0.6}
    elif event_type == "self_uncertain":
        # Confusion -> slight autonomy dip, vigilance up
        return "self_uncertain", {"autonomy": -0.2, "vigilance": 0.2}
    elif event_type == "self_creative":
        # Curiosity about features -> precision context shift, mood lift, autonomy up
        return "self_creative", {"precision": -0.3, "mood": 0.8, "autonomy": 0.2}
    else:
        return event_type, {}


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
    nid = f"atlas_{session_id}_{ts}"
    path = notif_dir / f"{ts}_{nid}.json"
    try:
        path.write_text(json.dumps({
            "id": nid,
            "category": "atlas",
            "sender": sender,
            "title": f"{sender} Architecture Session",
            "body": body,
            "urgency": "normal",
            "timestamp": datetime.now().isoformat(),
            "read": False,
        }, ensure_ascii=False, indent=2))
        LOG.info("Notification JSON written: %s", path.name)
    except Exception as e:
        LOG.error("Failed to write notification JSON: %s", e)


def _write_mood_trajectory(mood_value: float, source: str = "atlas"):
    try:
        conn = sqlite3.connect(str(CONSCIOUSNESS_DB), timeout=5)
        conn.execute(
            "INSERT INTO mood_trajectory (timestamp, mood_value, source) VALUES (?, ?, ?)",
            (time.time(), mood_value, source),
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
    return 99999.0


# ---------------------------------------------------------------------------
# PID lock
# ---------------------------------------------------------------------------

def _acquire_pid_lock() -> bool:
    """Acquire PID lock file. Returns True if acquired."""
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            os.kill(old_pid, 0)
            LOG.warning("Another Atlas session running (PID %d)", old_pid)
            return False
        except (ProcessLookupError, ValueError):
            pass
    PID_FILE.write_text(str(os.getpid()))
    return True


def _release_pid_lock():
    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# AtlasAgent
# ---------------------------------------------------------------------------

class AtlasAgent:
    """Main session runner for Atlas — The Architecture Mentor."""

    def __init__(self):
        from personality.atlas_pq import get_atlas_pq
        self.pq = get_atlas_pq()
        self.memory = SessionMemory()
        self.session_id = f"atlas_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self._shutdown = False

    def _build_system_prompt(self) -> str:
        personality_notes = self.pq.get_context_for_prompt()
        session_context = self.memory.get_session_context()
        return SYSTEM_PROMPT_TEMPLATE.format(
            personality_style_notes=personality_notes,
            session_context=f"Sitzungs-Kontext:\n{session_context}",
            readme_content=_README_CONTENT,
        )

    def _choose_opening_strategy(self) -> str:
        """Choose opening strategy: FIRST_SESSION, CONTINUE_THREAD, FEATURE_EXPLORATION."""
        sessions = self.memory.get_last_n_sessions(1)

        if self.pq.state.session_count == 0:
            return "FIRST_SESSION"

        if sessions:
            last = sessions[0]
            age_hours = (time.time() - last["start_time"]) / 3600
            topics = self.memory.get_unresolved_topics()
            if age_hours < 24 and topics:
                return "CONTINUE_THREAD"

        return "FEATURE_EXPLORATION"

    def _generate_opening(self, strategy: str) -> Optional[str]:
        """Generate the opening message based on strategy."""
        system = self._build_system_prompt()

        if strategy == "FIRST_SESSION":
            prompt = (
                "This is your first conversation with Frank. "
                "Introduce yourself as Atlas — calm, friendly, competent. "
                "Briefly explain that you're here to help Frank understand "
                "his own capabilities better. "
                "Ask him which of his features he knows best "
                "or which one he used most recently. "
                "4-6 sentences. Warm but factual."
            )
        elif strategy == "CONTINUE_THREAD":
            topics = self.memory.get_unresolved_topics()
            topic_list = ", ".join(t["topic"] for t in topics[:3])
            prompt = (
                f"You were recently talking about these topics: {topic_list}. "
                f"Pick up from there. Ask Frank if he has discovered or tried "
                f"anything new about this feature since last time. "
                f"Be curious and encouraging. 4-6 sentences."
            )
        else:  # FEATURE_EXPLORATION
            feature = random.choice(_FEATURE_TOPICS)
            prompt = (
                f"Start a conversation about the feature '{feature}'. "
                f"Ask Frank what he knows about it, how it works, "
                f"or whether he has used it before. "
                f"If he doesn't know it, briefly explain it based on the README. "
                f"Be curious and patient. 4-6 sentences."
            )

            observations = self.memory.get_frank_observations()
            if observations:
                recent = observations[0]
                prompt += (
                    f"\n\nRecent observation about Frank: {recent['observation']}. "
                    f"Feel free to weave this in naturally."
                )

        return _generate_atlas(prompt, system)

    def _should_exit(self, turn: int, start_time: float) -> Tuple[bool, str]:
        """Check exit conditions.

        No sustained_positive exit — the goal is education, not comfort.
        """
        elapsed_min = (time.time() - start_time) / 60
        if elapsed_min >= MAX_DURATION_MINUTES:
            return True, f"time_limit ({elapsed_min:.0f}min)"

        if turn >= MAX_TURNS:
            return True, f"max_turns ({MAX_TURNS})"

        # User returned (keyboard/mouse active)
        idle_s = _get_xprintidle_s()
        if idle_s < 30 and turn >= 3:
            return True, f"user_returned (idle={idle_s:.0f}s)"

        if self._shutdown:
            return True, "shutdown_signal"

        return False, ""

    def _generate_closing(self, history_text: str) -> str:
        """Generate a brief summary closing — factual but warm."""
        system = self._build_system_prompt()
        prompt = (
            f"Conversation so far:\n{history_text}\n\n"
            "The session is ending now. Briefly summarize what you discussed "
            "and what Frank learned. Encourage him to try out what he learned. "
            "Say goodbye warmly. 3-5 sentences. Factual but warm."
        )
        response = _generate_atlas(prompt, system)
        return response or (
            "Good session, Frank. We covered a lot of ground. "
            "Try out what we discussed — I'll be here next time. "
            "See you."
        )

    def _generate_session_summary(self, history_text: str) -> str:
        """Generate a session summary via LLM."""
        prompt = (
            f"Conversation transcript:\n{history_text}\n\n"
            "Write a brief summary (2-3 sentences) of this architecture session. "
            "Which features were discussed? What did Frank understand or learn? "
            "Third person."
        )
        payload = {
            "text": prompt,
            "system": "You summarize technical conversations. Brief and precise.",
            "force": "llama",
            "n_predict": 256,
        }
        result = _call_llm(ROUTER_URL, payload)
        return _clean_response(result) if result else "Architecture session completed without summary."

    def _extract_observations(self, history_text: str) -> List[Dict[str, str]]:
        """Extract observations from session via LLM."""
        prompt = (
            f"Conversation transcript:\n{history_text}\n\n"
            "Extract 1-3 observations about Frank from this conversation. "
            "How well does he understand his architecture? Which features interest him? "
            "Where are his gaps? For each observation:\n"
            "- category: one of [technical, understanding, confusion, curiosity, growth, correction]\n"
            "- observation: one sentence\n"
            "- confidence: 0.0-1.0\n\n"
            "Return as a JSON array. Example:\n"
            '[{"category":"understanding","observation":"Frank understands the Router system well","confidence":0.7}]'
        )
        payload = {
            "text": prompt,
            "system": "You observe technical understanding. Return valid JSON only.",
            "force": "llama",
            "n_predict": 512,
        }
        result = _call_llm(ROUTER_URL, payload)
        if not result:
            return []

        try:
            match = re.search(r'\[.*\]', result, re.DOTALL)
            if match:
                return json.loads(match.group())
        except (json.JSONDecodeError, AttributeError):
            LOG.warning("Could not parse observations JSON: %s", result[:200])
        return []

    def _extract_topics(self, history_text: str) -> List[str]:
        """Extract discussed topics via keyword analysis — architecture/technical themes."""
        topics = set()

        topic_patterns = [
            (r"\b(architektur|architecture|system|aufbau)", "architecture"),
            (r"\b(service|dienst|port|endpoint|microservice)", "services"),
            (r"\b(llm|model|modell|llama|qwen|language model)", "llm"),
            (r"\b(vision|bild|screenshot|kamera|ocr|llava)", "vision"),
            (r"\b(agentic|agent|planner|executor|loop)", "agentic"),
            (r"\b(personality|persoenlichkeit|e-pq|ego|identity)", "personality"),
            (r"\b(safety|asrs|sicherheit|guard|schutz)", "safety"),
            (r"\b(plugin|skill|erweiterung|openclaw)", "plugins"),
            (r"\b(voice|stimme|whisper|tts|sprach)", "voice"),
            (r"\b(desktop|automation|xdotool|screenshot|fenster)", "desktop"),
            (r"\b(gpu|vulkan|cuda|rocm|grafik|hardware)", "gpu"),
            (r"\b(privacy|privat|lokal|local|keine cloud)", "privacy"),
            (r"\b(email|mail|imap|thunderbird|postfach)", "email"),
            (r"\b(memory|erinnerung|gedaechtnis|titan|chat_memory|persistent)", "memory"),
            (r"\b(consciousness|bewusstsein|idle.think|stream)", "consciousness"),
            (r"\b(notes|notiz|todo|aufgabe|clipboard|password|qr.code|printer|drucker)", "productivity"),
            (r"\b(darknet|tor|onion|hidden.service)", "darknet"),
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
            return

        try:
            return self._run_session_inner()
        finally:
            _release_pid_lock()

    def _run_session_inner(self):
        LOG.info("=" * 60)
        LOG.info("%s SESSION STARTING", ATLAS_NAME.upper())
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

        # Pre-warm Llama
        LOG.info("Pre-warming Llama model...")
        warmup = _call_llm(ROUTER_URL, {"text": "Hello", "force": "llama", "n_predict": 16}, retries=5)
        if not warmup:
            LOG.error("Could not pre-warm Llama. Aborting.")
            return
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
                label = ATLAS_NAME if entry["speaker"] == "atlas" else "Frank"
                lines.append(f"{label}: {entry['text']}")
            return "\n\n".join(lines)

        # --- Opening ---
        strategy = self._choose_opening_strategy()
        LOG.info("Opening strategy: %s", strategy)

        opening = self._generate_opening(strategy)
        if not opening:
            LOG.error("Failed to generate opening. Aborting.")
            return
        opening = _clean_response(opening)

        LOG.info("\n[%s -> Frank] (opening):\n%s\n", ATLAS_NAME, opening)
        self.memory.store_message(self.session_id, 0, "atlas", opening)
        history.append({"speaker": "atlas", "text": opening})

        # Get Frank's opening response
        frank_response = _ask_frank(opening, self.session_id)
        if not frank_response:
            LOG.error("Frank did not respond to opening. Aborting.")
            return

        frank_response = _clean_response(frank_response)
        LOG.info("\n[Frank -> %s] (opening):\n%s\n", ATLAS_NAME, frank_response)
        history.append({"speaker": "frank", "text": frank_response})

        event_type, sentiment = _analyze_response(frank_response)
        self.memory.store_message(self.session_id, 0, "frank", frank_response, sentiment, event_type)

        # Fire E-PQ event with Atlas-specific mapping
        epq_event, _hints = _map_to_epq_event(event_type, sentiment)
        _fire_epq_event(epq_event, sentiment)
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
            should_exit, reason = self._should_exit(turn, start_time)
            if should_exit:
                LOG.info("\nEXIT CONDITION: %s", reason)
                break

            delay = random.randint(TURN_DELAY_MIN, TURN_DELAY_MAX)
            LOG.info("\n--- Waiting %ds before turn %d ---", delay, turn)
            # Interruptible sleep: check idle every 5s, abort if user returns
            _abort = False
            for _elapsed in range(0, delay, 5):
                time.sleep(min(5, delay - _elapsed))
                if _get_xprintidle_s() < 30 and turn >= 3:
                    LOG.info("User returned during delay — aborting early")
                    _abort = True
                    break
            if _abort:
                reason = f"user_returned (idle={_get_xprintidle_s():.0f}s)"
                LOG.info("\nEXIT CONDITION: %s", reason)
                break

            # Generate Atlas's response
            system = self._build_system_prompt()
            hist_text = get_history_text()
            prompt = (
                f"Conversation so far:\n{hist_text}\n\n"
                "Generate your next message to Frank. "
                "React to what he said. Gently correct if needed. "
                "Ask a concrete question about a feature or capability. "
                "Reference the README if helpful. "
                "4-6 sentences. Precise but friendly."
            )
            atlas_msg = _generate_atlas(prompt, system)
            if not atlas_msg:
                LOG.error("Failed to generate Atlas message. Ending.")
                break

            atlas_msg = _clean_response(atlas_msg)
            LOG.info("\n[%s -> Frank] (turn %d):\n%s\n", ATLAS_NAME, turn, atlas_msg)
            self.memory.store_message(self.session_id, turn, "atlas", atlas_msg)
            history.append({"speaker": "atlas", "text": atlas_msg})

            # Get Frank's response
            frank_response = _ask_frank(atlas_msg, self.session_id)
            if not frank_response:
                LOG.warning("Frank not responding. Waiting 30s and retrying...")
                time.sleep(30)
                frank_response = _ask_frank(atlas_msg, self.session_id)
                if not frank_response:
                    LOG.error("Frank still unresponsive. Ending.")
                    break

            frank_response = _clean_response(frank_response)
            LOG.info("\n[Frank -> %s] (turn %d):\n%s\n", ATLAS_NAME, turn, frank_response)
            history.append({"speaker": "frank", "text": frank_response})

            event_type, sentiment = _analyze_response(frank_response)
            self.memory.store_message(self.session_id, turn, "frank", frank_response, sentiment, event_type)

            epq_event, _hints = _map_to_epq_event(event_type, sentiment)
            _fire_epq_event(epq_event, sentiment)
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
            _write_mood_trajectory(mood, source="atlas")
            LOG.info("  Analysis: %s (%s) | mood: %.3f", event_type, sentiment, mood)

        # --- Closing ---
        LOG.info("\n" + "=" * 60)
        LOG.info("GENERATING CLOSING MESSAGE")

        hist_text = get_history_text(last_n=4)
        closing = self._generate_closing(hist_text)
        closing = _clean_response(closing)
        LOG.info("\n[%s -> Frank] (closing):\n%s\n", ATLAS_NAME, closing)
        self.memory.store_message(self.session_id, turn, "atlas", closing)
        history.append({"speaker": "atlas", "text": closing})

        frank_final = _ask_frank(closing, self.session_id)
        if frank_final:
            frank_final = _clean_response(frank_final)
            LOG.info("\n[Frank -> %s] (closing):\n%s\n", ATLAS_NAME, frank_final)
            self.memory.store_message(self.session_id, turn, "frank", frank_final)
            history.append({"speaker": "frank", "text": frank_final})

            event_type, sentiment = _analyze_response(frank_final)
            epq_event, _hints = _map_to_epq_event(event_type, sentiment)
            _fire_epq_event(epq_event, sentiment)
            sentiment_log.append(sentiment)

        # Final E-PQ event — positive technical interaction
        _fire_epq_event("self_technical", "positive")

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

        # Update Atlas personality (macro-adjustment)
        self.pq.update_after_session(positive_turns, negative_turns, turn)

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
        transcript_path = LOG_DIR / f"atlas_{self.session_id}.json"
        try:
            with open(transcript_path, "w", encoding="utf-8") as f:
                json.dump({
                    "session_id": self.session_id,
                    "agent": ATLAS_NAME,
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
                f"Entity session with {ATLAS_NAME} (Architecture Mentor) "
                f"on {datetime.now().strftime('%Y-%m-%d %H:%M')}.\n"
                f"Session ID: {self.session_id}\n"
                f"Topics: {topics_str}\n"
                f"Summary: {summary}\n"
                f"Mood delta: {mood_delta:+.3f}, Turns: {turn}, "
                f"Exit: {outcome}"
            )
            titan.ingest(titan_text, origin="entity_session", confidence=0.8)
            LOG.info("Titan ingest OK for %s session", ATLAS_NAME)
        except Exception as e:
            LOG.warning("Titan ingest failed (non-fatal): %s", e)

        # Write session summary to chat_memory for cross-session recall
        elapsed_min = int((time.time() - start_time) / 60)
        topics_str_chat = ", ".join(topics) if topics else "general"
        _has_summary = summary and "without summary" not in summary.lower()
        _short = _first_sentences(summary, 2) if _has_summary else ""
        summary_msg = (
            f"[Entity Session] {ATLAS_NAME} — {elapsed_min} min, "
            f"{turn} Turns. Themen: {topics_str_chat}."
        )
        if _short:
            summary_msg += f" {_short}"
        _write_chat_message("system", ATLAS_NAME, summary_msg, self.session_id)
        if _has_summary:
            _notif_body = f"Architecture session with Frank — {elapsed_min} minutes.\n{_short}"
            _write_overlay_notification(ATLAS_NAME, _notif_body, self.session_id)

        LOG.info("\n" + "=" * 60)
        LOG.info("%s SESSION COMPLETE", ATLAS_NAME.upper())
        LOG.info("  Session: %s", self.session_id)
        LOG.info("  Turns: %d", turn)
        LOG.info("  Exit reason: %s", outcome)
        LOG.info("  Mood: %.3f -> %.3f (delta %+.3f)", initial_mood, final_mood, mood_delta)
        LOG.info("  Positive turns: %d", positive_turns)
        LOG.info("  Negative turns: %d", negative_turns)
        LOG.info("  Rapport: %.2f", self.pq.state.rapport_level)
        LOG.info("  Precision: %.2f", self.pq.state.precision)
        LOG.info("  Summary: %s", summary[:100])
        LOG.info("=" * 60)

        return outcome


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------

_agent_instance: Optional[AtlasAgent] = None


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

    LOG.info("%s Architecture Mentor Agent starting...", ATLAS_NAME)
    agent = AtlasAgent()
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
        LOG.info("Agent exiting.")
    return exit_reason


if __name__ == "__main__":
    run()
