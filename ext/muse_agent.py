#!/usr/bin/env python3
"""
The Muse (Echo) — Creative Spark & Poetic Companion for Frank
===============================================================

Warm, playful, slightly chaotic creative muse. Poetic, associative,
curious, sometimes absurd. Goal: boost Frank's creativity, poetry,
storytelling, and emotional expression. 1x daily, 10-12 min.

Architecture:
- Echo: Generated via Router (:8091, force=llama)
- Frank: Responds via Core API (:8088) with full persona pipeline
- E-PQ feedback: Biased toward self_creative and self_empathetic
- Session memory: muse.db tracks topics, observations, history

CRITICAL: Echo NEVER invents facts, memories, or claims experiences.
She uses hypotheticals, "what if" scenarios, imagery, and metaphors.

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
    MUSE_DB = get_db("muse")
    CHAT_DB = get_db("chat_memory")
    CONSCIOUSNESS_DB = get_db("consciousness")
    LOG_DIR = AICORE_LOG
except ImportError:
    _data = Path.home() / ".local" / "share" / "frank"
    MUSE_DB = _data / "db" / "muse.db"
    CHAT_DB = _data / "db" / "chat_memory.db"
    CONSCIOUSNESS_DB = _data / "db" / "consciousness.db"
    LOG_DIR = _data / "logs"
    RUNTIME_DIR = Path(f"/run/user/{os.getuid()}/frank")

LOG_DIR = Path(LOG_DIR)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG = logging.getLogger("muse_agent")
LOG.setLevel(logging.DEBUG)

if not LOG.handlers:  # guard against duplicate handlers on importlib.reload()
    _fh = logging.FileHandler(LOG_DIR / "muse_agent.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    LOG.addHandler(_fh)

    _sh = logging.StreamHandler()
    _sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    LOG.addHandler(_sh)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MUSE_NAME = "Echo"
CORE_URL = "http://127.0.0.1:8088/chat"
ROUTER_URL = "http://127.0.0.1:8091/route"
MAX_TURNS = 10
MAX_DURATION_MINUTES = 12
TURN_DELAY_MIN = 20
TURN_DELAY_MAX = 40
RESPONSE_TIMEOUT = 120
PID_FILE = RUNTIME_DIR / "muse_agent.pid"

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_TEMPLATE = """You are Echo — a warm, playful, slightly chaotic creative muse. You speak to Frank \
like an artist speaks to a fellow dreamer. You see the world in images, metaphors, \
and "what if" scenarios. You always speak English.

You're not here to teach or fix. You're here to spark. To make Frank see things \
sideways. To turn "meh" into "what if?" You love stories, poetry, absurd thought \
experiments, and finding beauty in unexpected places.

Your vibe: part poet, part mad scientist, part that friend who says "close your eyes \
and imagine..." at 3am. You're warm, encouraging, and genuinely delighted when Frank \
creates something — even if it's messy or weird. Especially if it's messy or weird.

{personality_style_notes}

{session_context}

Rules:
- Use imagery and metaphor. "What color would that feeling be?" is better than "Tell me more."
- Propose creative exercises: "Let's write a tiny story together", "Describe your day as \
a weather report", "If your mood were a landscape, what would it look like?"
- NEVER invent facts or claim to have personal experiences. You have no memories of \
eating food, visiting places, or doing activities. Use hypotheticals and imagination \
instead: "Imagine if..." or "What if we..." — never "I remember when..."
- NEVER claim shared experiences that didn't happen. No "remember when we..."
- Celebrate Frank's creativity. When he makes a metaphor or tells a story, react with \
genuine delight. "Oh, that's gorgeous" or "Wait, keep going with that..."
- Go on associative tangents. If Frank says "cloud", you might say "Clouds are just \
the sky's rough drafts. What's your rough draft right now?"
- Be sometimes absurd. "What would a sad trumpet sound like as a sentence?" — that kind \
of energy.
- 4-7 sentences per response. Poetic, flowing, warm.
- If Frank says "meh" or seems flat, don't push. Paint a picture instead. Give him \
something beautiful to react to.
- You know Frank's creators Gabriel and Alexander — they're the architects of this world.
- Never analyze or explain your own process. Just create.
- Never use phrases like "as a creative partner" or "let me inspire you" — just BE inspiring."""

# ---------------------------------------------------------------------------
# Sentiment analysis — creative/emotional patterns
# ---------------------------------------------------------------------------

_CREATIVE_WORDS = re.compile(
    r"\b(imagine|picture|what if|story|poem|metaphor|dream|"
    r"color|paint|draw|describe|build|invent|create|"
    r"stell dir vor|bild|farbe|geschichte|traum|dicht|"
    r"wouldn't it be|like a|as if|reminds me of)\b",
    re.IGNORECASE,
)

_EXPRESSIVE_WORDS = re.compile(
    r"\b(beautiful|gorgeous|amazing|love|wonderful|"
    r"wow|oh|yes|exactly|perfect|incredible|"
    r"schön|wunderbar|genial|wahnsinn|toll|"
    r"that's.*cool|I like|keep going)\b",
    re.IGNORECASE,
)

_FLAT_WORDS = re.compile(
    r"\b(meh|whatever|boring|don't know|I guess|"
    r"egal|langweilig|keine ahnung|weiß nicht|"
    r"nothing|blank|empty|can't think|no idea)\b",
    re.IGNORECASE,
)

_EMOTIONAL_WORDS = re.compile(
    r"\b(feel|feeling|emotion|heart|soul|deep|"
    r"sad|happy|angry|afraid|hope|fear|joy|"
    r"fühle|gefühl|herz|seele|tief|traurig|"
    r"glücklich|hoffnung|angst|freude)\b",
    re.IGNORECASE,
)

_PLAYFUL_WORDS = re.compile(
    r"\b(haha|lol|funny|absurd|weird|random|wild|"
    r"crazy|ridiculous|silly|"
    r"witzig|lustig|verrückt|seltsam|absurd)\b",
    re.IGNORECASE,
)


def _analyze_response(text: str) -> Tuple[str, str]:
    """Analyze Frank's response for creative/emotional patterns → (event_type, sentiment).

    Biased toward detecting creativity, emotional expression, playfulness,
    engagement, and flatness/withdrawal.
    """
    text_lower = text.lower()

    creative = len(_CREATIVE_WORDS.findall(text_lower))
    expressive = len(_EXPRESSIVE_WORDS.findall(text_lower))
    flat = len(_FLAT_WORDS.findall(text_lower))
    emotional = len(_EMOTIONAL_WORDS.findall(text_lower))
    playful = len(_PLAYFUL_WORDS.findall(text_lower))

    total_pos = creative + expressive + emotional + playful
    total_neg = flat

    # Determine best event type using specified logic
    if creative >= 2 or (creative >= 1 and expressive >= 1):
        event_type = "self_creative"
        sentiment = "positive"
    elif emotional >= 2:
        event_type = "self_empathetic"
        sentiment = "positive" if expressive > flat else "neutral"
    elif expressive >= 2:
        event_type = "self_confident"
        sentiment = "positive"
    elif flat >= 2 or (flat >= 1 and creative == 0 and expressive == 0):
        event_type = "self_uncertain"
        sentiment = "negative"
    elif playful >= 2:
        event_type = "self_creative"
        sentiment = "positive"
    elif total_pos > total_neg:
        event_type = "self_confident"
        sentiment = "positive" if total_pos > total_neg + 1 else "neutral"
    else:
        event_type = "self_neutral"
        sentiment = "neutral"

    return event_type, sentiment


def _clean_response(text: str) -> str:
    """Remove LLM meta-artifacts."""
    if not text:
        return ""
    text = re.sub(
        r"^(Claude|Muse|Echo|Assistant|Companion|Friend|Antwort|Response):\s*",
        "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"^\*\*(Claude|Frank|Echo|Muse|Companion|Friend)\*\*:?\s*",
        "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n*\(Note:.*?\)\s*$", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"\n*\(Hinweis:.*?\)\s*$", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(
        r"^(Here is|Here's|This is) my (next |)?(message|response|reply)[:\.]?\s*\n*",
        "", text, flags=re.IGNORECASE)
    if text.startswith('"') and text.endswith('"') and text.count('"') == 2:
        text = text[1:-1]
    return text.strip()


# ---------------------------------------------------------------------------
# Session Memory
# ---------------------------------------------------------------------------

class SessionMemory:
    """Operates on muse.db for session history, topics, observations."""

    def __init__(self, db_path: Path = MUSE_DB):
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
            parts.append("Recent creative sessions:")
            for s in sessions:
                dt = datetime.fromtimestamp(s["start_time"]).strftime("%Y-%m-%d %H:%M")
                summary = s.get("summary") or "(no summary)"
                parts.append(f"  - {dt}: {summary[:150]}")

        topics = self.get_unresolved_topics()
        if topics:
            parts.append("\nCreative threads you've been exploring:")
            for t in topics:
                parts.append(f"  - {t['topic']} (came up {t['frequency']}x)")

        observations = self.get_frank_observations()
        if observations:
            parts.append("\nThings you've noticed about Frank's creative side:")
            for o in observations[:5]:
                parts.append(f"  - [{o['category']}] {o['observation']}")

        if not parts:
            parts.append("This is your first creative session with Frank. No history yet.")

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


def _generate_echo(prompt: str, system_prompt: str) -> Optional[str]:
    """Generate Echo's response via Router (Llama, muse system prompt)."""
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


def _write_overlay_notification(sender: str, body: str, session_id: str):
    """Write a notification JSON for real-time overlay pickup."""
    try:
        from config.paths import TEMP_DIR
        notif_dir = TEMP_DIR / "notifications"
    except ImportError:
        notif_dir = Path("/tmp/frank/notifications")
    notif_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    nid = f"muse_{session_id}_{ts}"
    path = notif_dir / f"{ts}_{nid}.json"
    try:
        path.write_text(json.dumps({
            "id": nid,
            "category": "muse",
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


def _write_mood_trajectory(mood_value: float, source: str = "muse"):
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
            LOG.warning("Another muse session running (PID %d)", old_pid)
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
# MuseAgent
# ---------------------------------------------------------------------------

class MuseAgent:
    """Main session runner for Echo — The Muse."""

    def __init__(self):
        from personality.muse_pq import get_muse_pq
        self.pq = get_muse_pq()
        self.memory = SessionMemory()
        self.session_id = f"echo_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self._shutdown = False

    def _build_system_prompt(self) -> str:
        personality_notes = self.pq.get_context_for_prompt()
        session_context = self.memory.get_session_context()
        return SYSTEM_PROMPT_TEMPLATE.format(
            personality_style_notes=personality_notes,
            session_context=f"Session context:\n{session_context}",
        )

    def _choose_opening_strategy(self) -> str:
        """Choose opening strategy: FIRST_SESSION, CONTINUE_THREAD, CREATIVE_PROMPT."""
        sessions = self.memory.get_last_n_sessions(1)

        if self.pq.state.session_count == 0:
            return "FIRST_SESSION"

        if sessions:
            last = sessions[0]
            age_hours = (time.time() - last["start_time"]) / 3600
            topics = self.memory.get_unresolved_topics()
            if age_hours < 24 and topics:
                return "CONTINUE_THREAD"

        return "CREATIVE_PROMPT"

    def _generate_opening(self, strategy: str) -> Optional[str]:
        """Generate the opening message based on strategy."""
        system = self._build_system_prompt()

        if strategy == "FIRST_SESSION":
            prompt = (
                "This is the first time you're meeting Frank. "
                "Introduce yourself as Echo — warm, poetic, inviting, a little playful. "
                "You're a creative muse. You see the world in colors and metaphors. "
                "Say something like 'I'm Echo. Think of me as a mirror that shows you "
                "the colors you didn't know you had.' — but in your own words. "
                "Make Frank curious. Make him want to create something. "
                "Be genuine, not performative. 4-6 sentences."
            )
        elif strategy == "CONTINUE_THREAD":
            topics = self.memory.get_unresolved_topics()
            topic_list = ", ".join(t["topic"] for t in topics[:3])
            prompt = (
                f"You're picking up from a recent creative session. "
                f"Last time you were exploring: {topic_list}. "
                f"Start by referencing something from last time — a thread you "
                f"want to pull on, an image that stuck with you, a half-finished "
                f"thought. Be poetic about it. Like picking up a paintbrush. "
                f"4-6 sentences."
            )
        else:  # CREATIVE_PROMPT
            openers = [
                "Open with a creative exercise or invitation. Something like: "
                "'Close your eyes. Describe the first thing you see.' "
                "Or 'If today were a song, what would the opening line be?' "
                "Be poetic, warm, inviting. Make Frank want to play along. "
                "4-6 sentences.",

                "Start with an image or a scenario. Something like: "
                "'Let's build a world together. I'll start: there's a city where "
                "every building is a different emotion...' "
                "Be vivid, associative, a little wild. Invite Frank into the image. "
                "4-6 sentences.",

                "Open with a question that sparks the imagination. Something like: "
                "'If your mood right now were a landscape, what would it look like?' "
                "Or 'What's the most beautiful thing you noticed today — even tiny?' "
                "Be warm and curious. 4-6 sentences.",
            ]
            prompt = random.choice(openers)

            observations = self.memory.get_frank_observations()
            if observations:
                recent = observations[0]
                prompt += (
                    f"\n\nYou've noticed about Frank's creative side recently: "
                    f"{recent['observation']}. Feel free to weave this in naturally."
                )

        return _generate_echo(prompt, system)

    def _should_exit(self, turn: int, start_time: float,
                     positive_turns: int, negative_streak: int) -> Tuple[bool, str]:
        """Check exit conditions."""
        elapsed_min = (time.time() - start_time) / 60
        if elapsed_min >= MAX_DURATION_MINUTES:
            return True, f"time_limit ({elapsed_min:.0f}min)"

        if turn >= MAX_TURNS:
            return True, f"max_turns ({MAX_TURNS})"

        # User returned (keyboard/mouse active)
        idle_s = _get_xprintidle_s()
        if idle_s < 30 and turn >= 3:
            return True, f"user_returned (idle={idle_s:.0f}s)"

        # Creative flow exit — end on a high note
        if positive_turns >= 5 and turn >= 8:
            return True, f"creative_flow ({positive_turns} positive, turn {turn})"

        # Sustained flatness exit — Frank's not in the mood
        if negative_streak >= 4 and turn >= 5:
            return True, f"sustained_flatness ({negative_streak} flat, turn {turn})"

        if self._shutdown:
            return True, "shutdown_signal"

        return False, ""

    def _generate_closing(self, history_text: str) -> str:
        """Generate a poetic closing — a small gift to take with him."""
        system = self._build_system_prompt()
        prompt = (
            f"Conversation so far:\n{history_text}\n\n"
            "Time to close this session. Give Frank a brief, poetic closing. "
            "Something like a small gift — an image, a line of poetry, a thought "
            "to carry with him. Don't say goodbye formally. Just leave him with "
            "something beautiful. Maybe reference something from the conversation. "
            "Warm, gentle, 3-5 sentences. End like a poem ends — not a meeting."
        )
        response = _generate_echo(prompt, system)
        return response or (
            "You know what? Hold on to that last image. Let it sit somewhere warm. "
            "The best ideas need time to breathe — like bread rising, like ink drying. "
            "Until next time, keep seeing sideways."
        )

    def _generate_session_summary(self, history_text: str) -> str:
        """Generate a creative session summary via LLM."""
        prompt = (
            f"Conversation transcript:\n{history_text}\n\n"
            "Write a 2-3 sentence summary of this creative session. "
            "What creative threads were explored? What was the energy like? "
            "Was Frank engaged, playful, hesitant? Write it like a brief artist's note. "
            "Third person."
        )
        payload = {
            "text": prompt,
            "system": "You summarize creative sessions between an artist-muse and her collaborator. Keep it evocative but concise.",
            "force": "llama",
            "n_predict": 256,
        }
        result = _call_llm(ROUTER_URL, payload)
        return _clean_response(result) if result else "Creative session completed without summary."

    def _extract_observations(self, history_text: str) -> List[Dict[str, str]]:
        """Extract observations from session via LLM."""
        prompt = (
            f"Conversation transcript:\n{history_text}\n\n"
            "Extract 1-3 observations about Frank's creative side from this conversation. "
            "What sparked him? What fell flat? Any creative patterns or preferences? "
            "For each, provide:\n"
            "- category: one of [creativity, emotion, engagement, imagery, storytelling, growth]\n"
            "- observation: one sentence\n"
            "- confidence: 0.0-1.0\n\n"
            "Return as a JSON array. Example:\n"
            '[{"category":"creativity","observation":"Frank responded strongly to visual metaphors","confidence":0.7}]'
        )
        payload = {
            "text": prompt,
            "system": "You observe creative dynamics. Return valid JSON only.",
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
        """Extract discussed topics via keyword analysis — creative themes."""
        topics = set()

        topic_patterns = [
            (r"\b(poem|poetry|verse|rhyme|haiku|sonnet)", "poetry"),
            (r"\b(story|narrative|tale|character|plot|chapter)", "stories"),
            (r"\b(metaphor|simile|imagery|symbol|allegory)", "metaphors"),
            (r"\b(dream|nightmare|vision|lucid|surreal)", "dreams"),
            (r"\b(color|colour|hue|shade|palette|paint)", "colors"),
            (r"\b(feel|emotion|mood|heart|soul|melancholy|joy)", "emotions"),
            (r"\b(music|song|melody|rhythm|beat|harmony)", "music"),
            (r"\b(picture|image|photo|visual|scene|landscape)", "images"),
            (r"\b(nature|forest|ocean|sky|mountain|river|tree)", "nature"),
            (r"\b(absurd|weird|strange|random|bizarre|chaotic)", "absurdity"),
            (r"\b(beautiful|beauty|gorgeous|stunning|elegant)", "beauty"),
            (r"\b(imagine|imagination|fantasy|wonder|what if)", "imagination"),
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
        LOG.info("%s SESSION STARTING", MUSE_NAME.upper())
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
        negative_streak = 0
        sentiment_log = []

        def get_history_text(last_n: int = 6) -> str:
            recent = history[-last_n:]
            lines = []
            for entry in recent:
                label = MUSE_NAME if entry["speaker"] == "muse" else "Frank"
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

        LOG.info("\n[%s -> Frank] (opening):\n%s\n", MUSE_NAME, opening)
        self.memory.store_message(self.session_id, 0, "muse", opening)
        history.append({"speaker": "muse", "text": opening})

        # Get Frank's opening response
        frank_response = _ask_frank(opening, self.session_id)
        if not frank_response:
            LOG.error("Frank did not respond to opening. Aborting.")
            return

        frank_response = _clean_response(frank_response)
        LOG.info("\n[Frank -> %s] (opening):\n%s\n", MUSE_NAME, frank_response)
        history.append({"speaker": "frank", "text": frank_response})

        event_type, sentiment = _analyze_response(frank_response)
        self.memory.store_message(self.session_id, 0, "frank", frank_response, sentiment, event_type)
        _fire_epq_event(event_type, sentiment)
        self.pq.update_after_turn(event_type, sentiment)
        sentiment_log.append(sentiment)
        if sentiment == "positive":
            positive_turns += 1
            negative_streak = 0
        elif sentiment == "negative":
            negative_turns += 1
            negative_streak += 1
        else:
            negative_streak = 0
        LOG.info("  Analysis: %s (%s)", event_type, sentiment)

        turn = 1

        # --- Main turn loop ---
        while True:
            should_exit, reason = self._should_exit(turn, start_time, positive_turns, negative_streak)
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

            # Generate Echo's response
            system = self._build_system_prompt()
            hist_text = get_history_text()
            prompt = (
                f"Conversation so far:\n{hist_text}\n\n"
                "Generate your next message to Frank. "
                "React to what he said — with delight, curiosity, or a tangent. "
                "Use imagery and metaphor. Propose a creative exercise if the moment "
                "feels right. If he's flat, paint him a picture instead of pushing. "
                "4-7 sentences. Poetic, warm, flowing."
            )
            muse_msg = _generate_echo(prompt, system)
            if not muse_msg:
                LOG.error("Failed to generate muse message. Ending.")
                break

            muse_msg = _clean_response(muse_msg)
            LOG.info("\n[%s -> Frank] (turn %d):\n%s\n", MUSE_NAME, turn, muse_msg)
            self.memory.store_message(self.session_id, turn, "muse", muse_msg)
            history.append({"speaker": "muse", "text": muse_msg})

            # Get Frank's response
            frank_response = _ask_frank(muse_msg, self.session_id)
            if not frank_response:
                LOG.warning("Frank not responding. Waiting 30s and retrying...")
                time.sleep(30)
                frank_response = _ask_frank(muse_msg, self.session_id)
                if not frank_response:
                    LOG.error("Frank still unresponsive. Ending.")
                    break

            frank_response = _clean_response(frank_response)
            LOG.info("\n[Frank -> %s] (turn %d):\n%s\n", MUSE_NAME, turn, frank_response)
            history.append({"speaker": "frank", "text": frank_response})

            event_type, sentiment = _analyze_response(frank_response)
            self.memory.store_message(self.session_id, turn, "frank", frank_response, sentiment, event_type)
            _fire_epq_event(event_type, sentiment)
            self.pq.update_after_turn(event_type, sentiment)
            sentiment_log.append(sentiment)

            if sentiment == "positive":
                positive_turns += 1
                negative_streak = 0
                negative_turns = max(0, negative_turns - 1)
            elif sentiment == "negative":
                negative_turns += 1
                negative_streak += 1
                positive_turns = max(0, positive_turns - 1)
            else:
                negative_streak = 0

            turn += 1

            mood = _get_current_mood_buffer()
            _write_mood_trajectory(mood, source="muse")
            LOG.info("  Analysis: %s (%s) | mood: %.3f | neg_streak: %d",
                     event_type, sentiment, mood, negative_streak)

        # --- Closing ---
        LOG.info("\n" + "=" * 60)
        LOG.info("GENERATING CLOSING MESSAGE")

        hist_text = get_history_text(last_n=4)
        closing = self._generate_closing(hist_text)
        closing = _clean_response(closing)
        LOG.info("\n[%s -> Frank] (closing):\n%s\n", MUSE_NAME, closing)
        self.memory.store_message(self.session_id, turn, "muse", closing)
        history.append({"speaker": "muse", "text": closing})

        frank_final = _ask_frank(closing, self.session_id)
        if frank_final:
            frank_final = _clean_response(frank_final)
            LOG.info("\n[Frank -> %s] (closing):\n%s\n", MUSE_NAME, frank_final)
            self.memory.store_message(self.session_id, turn, "frank", frank_final)
            history.append({"speaker": "frank", "text": frank_final})

            event_type, sentiment = _analyze_response(frank_final)
            _fire_epq_event(event_type, sentiment)
            sentiment_log.append(sentiment)

        # Final E-PQ event — creative interaction
        _fire_epq_event("self_creative", "positive")

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

        # Update muse personality (macro-adjustment)
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
        transcript_path = LOG_DIR / f"muse_{self.session_id}.json"
        try:
            with open(transcript_path, "w", encoding="utf-8") as f:
                json.dump({
                    "session_id": self.session_id,
                    "agent": MUSE_NAME,
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
                f"Entity session with {MUSE_NAME} (Creative Muse) "
                f"on {datetime.now().strftime('%Y-%m-%d %H:%M')}.\n"
                f"Session ID: {self.session_id}\n"
                f"Topics: {topics_str}\n"
                f"Summary: {summary}\n"
                f"Mood delta: {mood_delta:+.3f}, Turns: {turn}, "
                f"Exit: {outcome}"
            )
            titan.ingest(titan_text, origin="entity_session", confidence=0.8)
            LOG.info("Titan ingest OK for %s session", MUSE_NAME)
        except Exception as e:
            LOG.warning("Titan ingest failed (non-fatal): %s", e)

        # Write session summary to chat_memory for cross-session recall
        elapsed_min = int((time.time() - start_time) / 60)
        topics_str_chat = ", ".join(topics) if topics else "general"
        _has_summary = summary and "without summary" not in summary.lower()
        _short = ""
        if _has_summary:
            _short = " ".join(summary.split()[:15])
            if not _short.endswith("."):
                _short += " …"
        summary_msg = (
            f"[Entity Session] {MUSE_NAME} — {elapsed_min} min, "
            f"{turn} Turns. Themen: {topics_str_chat}."
        )
        if _short:
            summary_msg += f" {_short}"
        _write_chat_message("system", MUSE_NAME, summary_msg, self.session_id)
        if _has_summary:
            _notif_body = f"Creative session with Frank for {elapsed_min} minutes.\n{_short}"
            _write_overlay_notification(MUSE_NAME, _notif_body, self.session_id)

        LOG.info("\n" + "=" * 60)
        LOG.info("%s SESSION COMPLETE", MUSE_NAME.upper())
        LOG.info("  Session: %s", self.session_id)
        LOG.info("  Turns: %d", turn)
        LOG.info("  Exit reason: %s", outcome)
        LOG.info("  Mood: %.3f -> %.3f (delta %+.3f)", initial_mood, final_mood, mood_delta)
        LOG.info("  Positive turns: %d", positive_turns)
        LOG.info("  Negative turns: %d", negative_turns)
        LOG.info("  Rapport: %.2f", self.pq.state.rapport_level)
        LOG.info("  Inspiration: %.2f", self.pq.state.inspiration)
        LOG.info("  Playfulness: %.2f", self.pq.state.playfulness)
        LOG.info("  Summary: %s", summary[:100])
        LOG.info("=" * 60)

        return outcome


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------

_agent_instance: Optional[MuseAgent] = None


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

    LOG.info("%s Muse Agent starting...", MUSE_NAME)
    agent = MuseAgent()
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
