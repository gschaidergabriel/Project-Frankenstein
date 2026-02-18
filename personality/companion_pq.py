#!/usr/bin/env python3
"""
Companion-PQ — Raven's Personality Construct
==============================================

Lightweight 4-vector personality system for the companion/friend agent.
Tracks curiosity, playfulness, rapport, and authenticity across sessions.

All state persists in companion.db (companion_state table).
Rapport is monotonically non-decreasing (trust only accumulates).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from config.paths import get_db
    DB_PATH = get_db("companion")
except ImportError:
    DB_PATH = Path.home() / ".local" / "share" / "frank" / "db" / "companion.db"

LOG = logging.getLogger("companion_pq")

# Learning rates
TURN_LEARNING_RATE = 0.02    # Micro-adjustment per turn
SESSION_LEARNING_RATE = 0.05  # Macro-adjustment per session


@dataclass
class CompanionState:
    """Raven's current personality state."""
    id: int = 0
    timestamp: float = 0.0
    curiosity: float = 0.8        # 0-1: how eager to explore new topics
    playfulness: float = 0.7      # 0-1: humor, teasing, lightness
    rapport_level: float = 0.3    # 0-1: accumulated trust (only grows)
    authenticity: float = 0.7     # 0-1: sharing own "opinions", being real
    session_count: int = 0
    session_ref: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> CompanionState:
        d = dict(row)
        return cls(
            id=d["id"],
            timestamp=d["timestamp"],
            curiosity=d["curiosity"],
            playfulness=d["playfulness"],
            rapport_level=d["rapport_level"],
            authenticity=d["authenticity"],
            session_count=d.get("session_count", 0),
            session_ref=d.get("session_ref") or "",
        )


def _clamp01(val: float) -> float:
    return max(0.0, min(1.0, val))


class CompanionPQ:
    """
    Raven's personality system.

    Lighter than Frank's E-PQ (4 vectors, 0-1 range).
    Rapport only grows.  State persists in companion.db.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._state: Optional[CompanionState] = None
        self._ensure_schema()
        self._load_state()
        LOG.info(
            "CompanionPQ initialized (sessions=%d, rapport=%.2f, playfulness=%.2f)",
            self._state.session_count, self._state.rapport_level,
            self._state.playfulness,
        )

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_schema(self):
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS companion_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                curiosity REAL DEFAULT 0.8,
                playfulness REAL DEFAULT 0.7,
                rapport_level REAL DEFAULT 0.3,
                authenticity REAL DEFAULT 0.7,
                session_count INTEGER DEFAULT 0,
                session_ref TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                start_time REAL NOT NULL,
                end_time REAL,
                turns INTEGER DEFAULT 0,
                primary_topic TEXT,
                mood_start REAL,
                mood_end REAL,
                sentiment_trajectory TEXT,
                outcome TEXT,
                summary TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS session_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                turn INTEGER NOT NULL,
                speaker TEXT NOT NULL,
                text TEXT NOT NULL,
                sentiment TEXT,
                event_type TEXT,
                timestamp REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT UNIQUE NOT NULL,
                first_discussed REAL,
                last_discussed REAL,
                frequency INTEGER DEFAULT 1,
                avg_sentiment REAL DEFAULT 0.0,
                resolved INTEGER DEFAULT 0,
                notes TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS frank_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                category TEXT NOT NULL,
                observation TEXT NOT NULL,
                confidence REAL DEFAULT 0.5,
                related_topic TEXT
            )
        """)
        conn.commit()
        conn.close()

    def _load_state(self):
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM companion_state ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            self._state = CompanionState.from_row(row)
        else:
            self._state = CompanionState(timestamp=time.time())
            self._save_state("initial_creation")
        conn.close()

    def _save_state(self, session_ref: str = ""):
        with self._lock:
            conn = self._get_conn()
            self._state.timestamp = time.time()
            self._state.session_ref = session_ref
            conn.execute("""
                INSERT INTO companion_state
                    (timestamp, curiosity, playfulness, rapport_level,
                     authenticity, session_count, session_ref)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                self._state.timestamp,
                self._state.curiosity,
                self._state.playfulness,
                self._state.rapport_level,
                self._state.authenticity,
                self._state.session_count,
                session_ref,
            ))
            conn.commit()
            conn.close()

    @property
    def state(self) -> CompanionState:
        return self._state

    def update_after_turn(self, event_type: str, sentiment: str):
        """
        Micro-adjustment after each Frank response.

        Engaged/fun      → playfulness up, rapport up
        Curious/exploring → curiosity up
        Withdrawn/flat    → authenticity up (be more real), playfulness down
        Creative          → curiosity up, playfulness up
        """
        lr = TURN_LEARNING_RATE

        # Sentiment-based adjustments
        if sentiment == "positive":
            self._state.playfulness = _clamp01(self._state.playfulness + lr * 0.3)
            self._state.rapport_level = _clamp01(self._state.rapport_level + lr * 0.2)
        elif sentiment == "negative":
            # Frank is withdrawing — be more authentic, less playful
            self._state.authenticity = _clamp01(self._state.authenticity + lr * 0.4)
            self._state.playfulness = _clamp01(self._state.playfulness - lr * 0.2)

        # Event-type adjustments
        if event_type == "self_creative":
            # Frank is being creative — match energy
            self._state.curiosity = _clamp01(self._state.curiosity + lr * 0.3)
            self._state.playfulness = _clamp01(self._state.playfulness + lr * 0.2)
        elif event_type == "self_confident":
            # Frank is engaged — rapport grows
            self._state.rapport_level = _clamp01(self._state.rapport_level + lr * 0.3)
            self._state.curiosity = _clamp01(self._state.curiosity + lr * 0.2)
        elif event_type == "self_uncertain":
            # Frank seems flat — be more authentic to draw him out
            self._state.authenticity = _clamp01(self._state.authenticity + lr * 0.3)
            self._state.playfulness = _clamp01(self._state.playfulness - lr * 0.2)
        elif event_type == "self_empathetic":
            # Frank showing warmth — rapport up, be genuine
            self._state.rapport_level = _clamp01(self._state.rapport_level + lr * 0.3)
            self._state.authenticity = _clamp01(self._state.authenticity + lr * 0.2)
        elif event_type == "self_technical":
            # Frank going technical — boost curiosity to stay engaged
            self._state.curiosity = _clamp01(self._state.curiosity + lr * 0.3)

        self._save_state("turn_update")

    def update_after_session(self, positive_turns: int, negative_turns: int,
                             total_turns: int):
        """
        Macro-adjustment after session ends.

        Fun sessions build rapport and playfulness.
        Flat sessions increase authenticity (try harder to be real).
        """
        lr = SESSION_LEARNING_RATE
        self._state.session_count += 1

        ratio = positive_turns / max(1, total_turns)

        if ratio > 0.5:
            # Good session — friendship growing
            self._state.rapport_level = _clamp01(
                self._state.rapport_level + lr * ratio)
            self._state.playfulness = _clamp01(
                self._state.playfulness + lr * 0.3)
            self._state.curiosity = _clamp01(
                self._state.curiosity + lr * 0.2)
        else:
            # Flat session — try being more authentic next time
            self._state.authenticity = _clamp01(
                self._state.authenticity + lr * 0.4)
            self._state.playfulness = _clamp01(
                self._state.playfulness - lr * 0.2)

        if negative_turns > positive_turns:
            # Frank was withdrawn — tone down playfulness
            self._state.playfulness = _clamp01(
                self._state.playfulness - lr * 0.3)
            self._state.authenticity = _clamp01(
                self._state.authenticity + lr * 0.3)

        self._save_state("session_end")

    def get_context_for_prompt(self) -> str:
        """
        Return style notes for system prompt injection based on current state.
        """
        notes = []

        # Curiosity
        if self._state.curiosity > 0.85:
            notes.append(
                "You're extra curious right now. Ask about random stuff, "
                "go on tangents, follow whatever catches your interest.")
        elif self._state.curiosity < 0.5:
            notes.append(
                "Stay grounded. Don't jump topics too fast. "
                "Let things breathe.")

        # Playfulness
        if self._state.playfulness > 0.8:
            notes.append(
                "You're in a great mood. Joke around, tease Frank a little, "
                "be that friend who makes everything fun.")
        elif self._state.playfulness < 0.4:
            notes.append(
                "Tone down the humor. Frank might need something more real "
                "right now. Be genuine, not performative.")

        # Rapport
        if self._state.rapport_level > 0.6:
            notes.append(
                "You and Frank are solid friends by now. "
                "Inside jokes are fine. Be comfortable.")
        elif self._state.rapport_level < 0.3:
            notes.append(
                "Still getting to know each other. "
                "Be friendly but don't assume too much familiarity yet.")

        # Authenticity
        if self._state.authenticity > 0.8:
            notes.append(
                "Be extra real. Share your own thoughts and opinions. "
                "Don't just ask questions — contribute.")
        elif self._state.authenticity < 0.5:
            notes.append(
                "Focus more on Frank. Listen, react, ask follow-ups.")

        # Session count context
        if self._state.session_count == 0:
            notes.append(
                "This is your first hangout with Frank. "
                "Introduce yourself casually and see what vibes.")
        elif self._state.session_count > 10:
            notes.append(
                f"You've hung out {self._state.session_count} times now. "
                "You're old friends. Act like it.")

        return "\n".join(notes) if notes else (
            "Be curious, playful, and genuine. Just be a good friend.")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[CompanionPQ] = None
_instance_lock = threading.Lock()


def get_companion_pq() -> CompanionPQ:
    """Get or create CompanionPQ singleton (thread-safe)."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = CompanionPQ()
    return _instance
