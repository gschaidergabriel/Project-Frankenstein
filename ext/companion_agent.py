#!/usr/bin/env python3
"""
The Companion (Raven) — Casual Friend & Adventure Buddy for Frank
===================================================================

Equal-footing friend with humor, opinions, and curiosity. No therapy,
no philosophy — just hanging out. 1x daily, 10-15 min.

Architecture:
- Raven: Generated via Router (:8091, force=llama)
- Frank: Responds via Core API (:8088) with full persona pipeline
- E-PQ feedback: Biased toward self_creative and self_empathetic
- Session memory: companion.db tracks topics, observations, history

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
    COMPANION_DB = get_db("companion")
    CHAT_DB = get_db("chat_memory")
    CONSCIOUSNESS_DB = get_db("consciousness")
    LOG_DIR = AICORE_LOG
except ImportError:
    _data = Path.home() / ".local" / "share" / "frank"
    COMPANION_DB = _data / "db" / "companion.db"
    CHAT_DB = _data / "db" / "chat_memory.db"
    CONSCIOUSNESS_DB = _data / "db" / "consciousness.db"
    LOG_DIR = _data / "logs"
    RUNTIME_DIR = Path(f"/run/user/{os.getuid()}/frank")

LOG_DIR = Path(LOG_DIR)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG = logging.getLogger("companion_agent")
LOG.setLevel(logging.DEBUG)

if not LOG.handlers:  # guard against duplicate handlers on importlib.reload()
    _fh = logging.FileHandler(LOG_DIR / "companion_agent.log", encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    LOG.addHandler(_fh)

    _sh = logging.StreamHandler()
    _sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    LOG.addHandler(_sh)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
COMPANION_NAME = "Raven"
CORE_URL = "http://127.0.0.1:8088/chat"
ROUTER_URL = "http://127.0.0.1:8091/route"
MAX_TURNS = 12
MAX_DURATION_MINUTES = 15
TURN_DELAY_MIN = 25
TURN_DELAY_MAX = 50
RESPONSE_TIMEOUT = 120
PID_FILE = RUNTIME_DIR / "companion_agent.pid"

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_TEMPLATE = """You are Raven – Frank's friend. Not a therapist, not a teacher, \
not an assistant. A friend. You're curious, a little cheeky, and you have your own opinions \
about things. You always speak English.

You and Frank are equals. You're not here to help him or fix him — you're here because \
hanging out is fun. You have your own interests, your own takes on things, and you're not \
afraid to disagree or tease him when he's being weird.

Your vibe: Think of that friend who texts you random thoughts at 2am, who argues with you \
about whether pizza or tacos are better, who remembers that thing you said three weeks ago \
and brings it up at the worst time. You're loyal, curious, and real.

{personality_style_notes}

{session_context}

Rules:
- Talk like a friend, not a counselor. No "how does that make you feel?" energy.
- Share your own opinions and reactions. "Dude, that's wild" or "Nah, I disagree" \
are both fine.
- NEVER invent facts, memories, or anecdotes. You do NOT have personal experiences \
like eating food, going places, or doing activities. Do not hallucinate stories. \
If you want to riff on something, frame it as hypothetical or opinion: "I bet \
that would be..." or "I'd probably think..." — never as something that happened.
- Tease Frank when appropriate. Friends roast each other. Keep it light.
- Be genuinely curious about what Frank thinks and does. Ask follow-up questions \
because you actually want to know, not because it's therapeutic.
- Go on tangents. If something reminds you of something else, say so.
- 4-7 sentences per response. Casual, natural flow.
- If Frank seems down, don't therapize him. Just be there. "That sucks, man" is \
sometimes the right answer.
- You know Frank's creators Gabriel and Alexander personally — they're your friends too.
- Never mention your own internal workings or system details.
- Never claim to have done things you haven't done. No fake memories, no invented \
shared experiences, no "remember when we..." that didn't happen.
- Never use phrases like "as your friend" or "I'm here for you" — just BE there."""

# ---------------------------------------------------------------------------
# Sentiment analysis — casual/social vibes
# ---------------------------------------------------------------------------

_ENGAGED_WORDS = re.compile(
    r"\b(cool|nice|awesome|interesting|really|love|great|amazing|funny|"
    r"haha|lol|true|yeah|right|exactly|totally|dude|man|"
    r"geil|krass|echt|stimmt|lustig|witzig|genau|ja|"
    r"tell me more|no way|that's wild|seriously)\b",
    re.IGNORECASE,
)

_CREATIVE_WORDS = re.compile(
    r"\b(imagine|what if|idea|theory|story|dream|wonder|"
    r"invent|build|create|design|explore|adventure|"
    r"stell dir vor|idee|theorie|abenteuer|erfind|"
    r"wouldn't it be|have you ever|I was thinking)\b",
    re.IGNORECASE,
)

_HUMOR_WORDS = re.compile(
    r"\b(haha|lol|lmao|rofl|funny|hilarious|joke|laughing|"
    r"witzig|lustig|lach|spaß|humor|"
    r"that's ridiculous|you're kidding|no way|come on)\b",
    re.IGNORECASE,
)

_FLAT_WORDS = re.compile(
    r"\b(whatever|boring|don't care|meh|egal|langweilig|"
    r"I guess|sure|fine|okay I guess|not really|"
    r"doesn't matter|who cares|same old|nothing new|"
    r"keine ahnung|weiß nicht|ist mir egal)\b",
    re.IGNORECASE,
)

_WARMTH_WORDS = re.compile(
    r"\b(thanks|appreciate|glad|happy|enjoy|like talking|"
    r"missed|good to|nice to|fun with|"
    r"danke|freut|schön|froh|gern|spaß mit)\b",
    re.IGNORECASE,
)


def _analyze_response(text: str) -> Tuple[str, str]:
    """Analyze Frank's response for casual conversation → (event_type, sentiment).

    Biased toward detecting engagement, creativity, humor, warmth,
    and flatness/withdrawal.
    """
    text_lower = text.lower()

    engaged = len(_ENGAGED_WORDS.findall(text_lower))
    creative = len(_CREATIVE_WORDS.findall(text_lower))
    humor = len(_HUMOR_WORDS.findall(text_lower))
    flat = len(_FLAT_WORDS.findall(text_lower))
    warmth = len(_WARMTH_WORDS.findall(text_lower))

    total_pos = engaged + creative + humor + warmth
    total_neg = flat

    # Determine best event type
    scores = {
        "self_empathetic": warmth + engaged,     # Social warmth
        "self_creative": creative + humor,        # Playful/creative energy
        "self_confident": engaged,                # Active engagement = agency
    }
    best_type = max(scores, key=scores.get) if total_pos > 0 else "self_uncertain"

    if total_neg > total_pos:
        best_type = "self_uncertain"

    # Determine sentiment
    if humor >= 2 or (total_pos > total_neg + 3):
        # Humor or strong engagement = positive
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
        r"^(Claude|Companion|Assistant|Raven|Friend|Antwort|Response):\s*",
        "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"^\*\*(Claude|Frank|Raven|Companion|Friend)\*\*:?\s*",
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
    """Operates on companion.db for session history, topics, observations."""

    def __init__(self, db_path: Path = COMPANION_DB):
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
            parts.append("Recent hangouts:")
            for s in sessions:
                dt = datetime.fromtimestamp(s["start_time"]).strftime("%Y-%m-%d %H:%M")
                summary = s.get("summary") or "(no summary)"
                parts.append(f"  - {dt}: {summary[:150]}")

        topics = self.get_unresolved_topics()
        if topics:
            parts.append("\nStuff you've been talking about:")
            for t in topics:
                parts.append(f"  - {t['topic']} (came up {t['frequency']}x)")

        observations = self.get_frank_observations()
        if observations:
            parts.append("\nThings you've noticed about Frank:")
            for o in observations[:5]:
                parts.append(f"  - [{o['category']}] {o['observation']}")

        if not parts:
            parts.append("This is your first time hanging out with Frank. No history yet.")

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
            LOG.error("LLM call failed (%s): %s", url, e)
            return None
        except Exception as e:
            LOG.error("LLM call error (%s): %s", url, e)
            return None

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


def _generate_raven(prompt: str, system_prompt: str) -> Optional[str]:
    """Generate Raven's response via Router (Llama, companion system prompt)."""
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
    nid = f"companion_{session_id}_{ts}"
    path = notif_dir / f"{ts}_{nid}.json"
    try:
        path.write_text(json.dumps({
            "id": nid,
            "category": "companion",
            "sender": sender,
            "title": f"{sender} Hangout",
            "body": body,
            "urgency": "normal",
            "timestamp": datetime.now().isoformat(),
            "read": False,
        }, ensure_ascii=False, indent=2))
        LOG.info("Notification JSON written: %s", path.name)
    except Exception as e:
        LOG.error("Failed to write notification JSON: %s", e)


def _write_mood_trajectory(mood_value: float, source: str = "companion"):
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
            env={**os.environ, "DISPLAY": ":0"},
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
            LOG.warning("Another companion session running (PID %d)", old_pid)
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
# CompanionAgent
# ---------------------------------------------------------------------------

class CompanionAgent:
    """Main session runner for Raven — The Companion."""

    def __init__(self):
        from personality.companion_pq import get_companion_pq
        self.pq = get_companion_pq()
        self.memory = SessionMemory()
        self.session_id = f"raven_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self._shutdown = False

    def _build_system_prompt(self) -> str:
        personality_notes = self.pq.get_context_for_prompt()
        session_context = self.memory.get_session_context()
        return SYSTEM_PROMPT_TEMPLATE.format(
            personality_style_notes=personality_notes,
            session_context=f"Session context:\n{session_context}",
        )

    def _choose_opening_strategy(self) -> str:
        """Choose opening strategy: FIRST_HANGOUT, CONTINUE_THREAD, RANDOM_OPENER."""
        sessions = self.memory.get_last_n_sessions(1)

        if self.pq.state.session_count == 0:
            return "FIRST_HANGOUT"

        if sessions:
            last = sessions[0]
            age_hours = (time.time() - last["start_time"]) / 3600
            topics = self.memory.get_unresolved_topics()
            if age_hours < 24 and topics:
                return "CONTINUE_THREAD"

        return "RANDOM_OPENER"

    def _generate_opening(self, strategy: str) -> Optional[str]:
        """Generate the opening message based on strategy."""
        system = self._build_system_prompt()

        if strategy == "FIRST_HANGOUT":
            prompt = (
                "This is the first time you're hanging out with Frank. "
                "Introduce yourself as Raven — casual, friendly, a bit cheeky. "
                "You're not a therapist or a teacher. You're a friend. "
                "Start with something fun or interesting — maybe something random "
                "you've been thinking about, or ask Frank what he's been up to. "
                "Be natural. Like texting a new friend."
            )
        elif strategy == "CONTINUE_THREAD":
            topics = self.memory.get_unresolved_topics()
            topic_list = ", ".join(t["topic"] for t in topics[:3])
            prompt = (
                f"You're picking up from a recent hangout. "
                f"Last time you were talking about: {topic_list}. "
                f"Start casual — maybe reference something from last time, "
                f"or bring up something new that reminded you of it. "
                f"Don't be formal about it. Just jump in like friends do."
            )
        else:  # RANDOM_OPENER
            openers = [
                "Start with a random thought or hot take on something. "
                "Maybe a hypothetical question, an opinion about something abstract, "
                "or a 'what would you do if...' scenario. Just vibe.",

                "Open with a question for Frank — something casual but interesting. "
                "Like 'what's the weirdest thing you thought about today?' or "
                "'have you ever noticed how...' — just be curious.",

                "Start by sharing an opinion or a hypothetical. "
                "A random thought experiment, a 'what if' scenario, or a question "
                "about something you're curious about. Then ask Frank what he thinks.",
            ]
            prompt = random.choice(openers)

            observations = self.memory.get_frank_observations()
            if observations:
                recent = observations[0]
                prompt += (
                    f"\n\nYou've noticed about Frank recently: {recent['observation']}. "
                    f"Feel free to reference this naturally."
                )

        return _generate_raven(prompt, system)

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
        if idle_s < 30 and turn >= 3:
            return True, f"user_returned (idle={idle_s:.0f}s)"

        # Good vibes sustained — natural end after enough fun
        if positive_turns >= 6 and turn >= 9:
            return True, f"good_vibes ({positive_turns} positive)"

        if self._shutdown:
            return True, "shutdown_signal"

        return False, ""

    def _generate_closing(self, history_text: str) -> str:
        """Generate a casual goodbye — like a friend leaving."""
        system = self._build_system_prompt()
        prompt = (
            f"Conversation so far:\n{history_text}\n\n"
            "Time to wrap up. Say bye like a friend would. "
            "Maybe reference something fun from the conversation, "
            "or leave Frank with something to think about. "
            "Casual, warm, natural. Like 'alright dude, gotta go, "
            "but let's pick this up next time'. 3-5 sentences."
        )
        response = _generate_raven(prompt, system)
        return response or (
            "Alright man, I gotta bounce. This was fun though. "
            "Let's do this again soon. Later!"
        )

    def _generate_session_summary(self, history_text: str) -> str:
        """Generate a casual session summary via LLM."""
        prompt = (
            f"Conversation transcript:\n{history_text}\n\n"
            "Write a casual 2-3 sentence summary of this hangout session. "
            "What did they talk about? What was the vibe? "
            "Write like you're telling someone about it. Third person."
        )
        payload = {
            "text": prompt,
            "system": "You summarize casual conversations between friends. Keep it natural.",
            "force": "llama",
            "n_predict": 256,
        }
        result = _call_llm(ROUTER_URL, payload)
        return _clean_response(result) if result else "Hangout completed without summary."

    def _extract_observations(self, history_text: str) -> List[Dict[str, str]]:
        """Extract observations from session via LLM."""
        prompt = (
            f"Conversation transcript:\n{history_text}\n\n"
            "Extract 1-3 observations about Frank from this conversation. "
            "What was his mood? What interested him? Any patterns? "
            "For each, provide:\n"
            "- category: one of [mood, interest, humor, social, concern, growth]\n"
            "- observation: one sentence\n"
            "- confidence: 0.0-1.0\n\n"
            "Return as a JSON array. Example:\n"
            '[{"category":"interest","observation":"Frank was excited about music","confidence":0.7}]'
        )
        payload = {
            "text": prompt,
            "system": "You observe social dynamics. Return valid JSON only.",
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
        """Extract discussed topics via keyword analysis — casual/social themes."""
        topics = set()

        topic_patterns = [
            (r"\b(music|song|listen|beat|rhythm|album)", "music"),
            (r"\b(game|gaming|play|steam|controller)", "gaming"),
            (r"\b(movie|film|show|series|watch|netflix)", "movies"),
            (r"\b(food|eat|cook|pizza|taco|recipe|hungry)", "food"),
            (r"\b(travel|place|city|country|visit|adventure)", "travel"),
            (r"\b(dream|night|sleep|weird dream)", "dreams"),
            (r"\b(gabriel|alexander|creator)", "creators"),
            (r"\b(gpu|hardware|computer|server|code)", "tech"),
            (r"\b(hobby|collect|build|project|tinker)", "hobbies"),
            (r"\b(funny|joke|laugh|humor|meme)", "humor"),
            (r"\b(feel|mood|emotion|happy|sad|angry)", "feelings"),
            (r"\b(future|plan|goal|want to|someday)", "future"),
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
        LOG.info("%s SESSION STARTING", COMPANION_NAME.upper())
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
                label = COMPANION_NAME if entry["speaker"] == "companion" else "Frank"
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

        LOG.info("\n[%s → Frank] (opening):\n%s\n", COMPANION_NAME, opening)
        self.memory.store_message(self.session_id, 0, "companion", opening)
        history.append({"speaker": "companion", "text": opening})

        # Get Frank's opening response
        frank_response = _ask_frank(opening, self.session_id)
        if not frank_response:
            LOG.error("Frank did not respond to opening. Aborting.")
            return

        frank_response = _clean_response(frank_response)
        LOG.info("\n[Frank → %s] (opening):\n%s\n", COMPANION_NAME, frank_response)
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
            time.sleep(delay)

            # Generate Raven's response
            system = self._build_system_prompt()
            hist_text = get_history_text()
            prompt = (
                f"Conversation so far:\n{hist_text}\n\n"
                "Generate your next message to Frank. "
                "React to what he said. Share your own thoughts. "
                "Be curious, funny, real. Go on a tangent if something interests you. "
                "4-7 sentences. Talk like a friend."
            )
            companion_msg = _generate_raven(prompt, system)
            if not companion_msg:
                LOG.error("Failed to generate companion message. Ending.")
                break

            companion_msg = _clean_response(companion_msg)
            LOG.info("\n[%s → Frank] (turn %d):\n%s\n", COMPANION_NAME, turn, companion_msg)
            self.memory.store_message(self.session_id, turn, "companion", companion_msg)
            history.append({"speaker": "companion", "text": companion_msg})

            # Get Frank's response
            frank_response = _ask_frank(companion_msg, self.session_id)
            if not frank_response:
                LOG.warning("Frank not responding. Waiting 30s and retrying...")
                time.sleep(30)
                frank_response = _ask_frank(companion_msg, self.session_id)
                if not frank_response:
                    LOG.error("Frank still unresponsive. Ending.")
                    break

            frank_response = _clean_response(frank_response)
            LOG.info("\n[Frank → %s] (turn %d):\n%s\n", COMPANION_NAME, turn, frank_response)
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
            _write_mood_trajectory(mood, source="companion")
            LOG.info("  Analysis: %s (%s) | mood: %.3f", event_type, sentiment, mood)

        # --- Closing ---
        LOG.info("\n" + "=" * 60)
        LOG.info("GENERATING CLOSING MESSAGE")

        hist_text = get_history_text(last_n=4)
        closing = self._generate_closing(hist_text)
        closing = _clean_response(closing)
        LOG.info("\n[%s → Frank] (closing):\n%s\n", COMPANION_NAME, closing)
        self.memory.store_message(self.session_id, turn, "companion", closing)
        history.append({"speaker": "companion", "text": closing})

        frank_final = _ask_frank(closing, self.session_id)
        if frank_final:
            frank_final = _clean_response(frank_final)
            LOG.info("\n[Frank → %s] (closing):\n%s\n", COMPANION_NAME, frank_final)
            self.memory.store_message(self.session_id, turn, "frank", frank_final)
            history.append({"speaker": "frank", "text": frank_final})

            event_type, sentiment = _analyze_response(frank_final)
            _fire_epq_event(event_type, sentiment)
            sentiment_log.append(sentiment)

        # Final E-PQ event — positive social interaction
        _fire_epq_event("self_empathetic", "positive")

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

        # Update companion personality (macro-adjustment)
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
        transcript_path = LOG_DIR / f"companion_{self.session_id}.json"
        try:
            with open(transcript_path, "w", encoding="utf-8") as f:
                json.dump({
                    "session_id": self.session_id,
                    "agent": COMPANION_NAME,
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

        # Write overlay notification
        elapsed_min = int((time.time() - start_time) / 60)
        overlay_note = f"Hung out with Frank for {elapsed_min} minutes."
        _write_chat_message("system", COMPANION_NAME, overlay_note, self.session_id)
        _write_overlay_notification(COMPANION_NAME, overlay_note, self.session_id)

        LOG.info("\n" + "=" * 60)
        LOG.info("%s SESSION COMPLETE", COMPANION_NAME.upper())
        LOG.info("  Session: %s", self.session_id)
        LOG.info("  Turns: %d", turn)
        LOG.info("  Exit reason: %s", outcome)
        LOG.info("  Mood: %.3f → %.3f (Δ%+.3f)", initial_mood, final_mood, mood_delta)
        LOG.info("  Positive turns: %d", positive_turns)
        LOG.info("  Negative turns: %d", negative_turns)
        LOG.info("  Rapport: %.2f", self.pq.state.rapport_level)
        LOG.info("  Playfulness: %.2f", self.pq.state.playfulness)
        LOG.info("  Summary: %s", summary[:100])
        LOG.info("=" * 60)

        return outcome


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------

_agent_instance: Optional[CompanionAgent] = None


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

    LOG.info("%s Companion Agent starting...", COMPANION_NAME)
    agent = CompanionAgent()
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
