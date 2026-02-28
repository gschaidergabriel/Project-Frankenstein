#!/usr/bin/env python3
"""
Muse-PQ — Echo's Personality Construct
========================================

Lightweight 4-vector personality system for the creative muse agent.
Tracks inspiration, warmth, rapport, and playfulness across sessions.

All state persists in muse.db (muse_state table).
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
    DB_PATH = get_db("muse")
except ImportError:
    DB_PATH = Path.home() / ".local" / "share" / "frank" / "db" / "muse.db"

LOG = logging.getLogger("muse_pq")

# Learning rates
TURN_LEARNING_RATE = 0.02    # Micro-adjustment per turn
SESSION_LEARNING_RATE = 0.05  # Macro-adjustment per session


@dataclass
class MuseState:
    """Echo's current personality state."""
    id: int = 0
    timestamp: float = 0.0
    inspiration: float = 0.8     # 0-1: how wild and associative the prompts get
    warmth: float = 0.7          # 0-1: emotional encouragement vs pure art challenge
    rapport_level: float = 0.3   # 0-1: accumulated trust (only grows)
    playfulness: float = 0.8     # 0-1: absurdity level, humor, whimsy
    session_count: int = 0
    session_ref: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> MuseState:
        d = dict(row)
        return cls(
            id=d["id"],
            timestamp=d["timestamp"],
            inspiration=d["inspiration"],
            warmth=d["warmth"],
            rapport_level=d["rapport_level"],
            playfulness=d["playfulness"],
            session_count=d.get("session_count", 0),
            session_ref=d.get("session_ref") or "",
        )


def _clamp01(val: float) -> float:
    return max(0.0, min(1.0, val))


class MusePQ:
    """
    Echo's personality system.

    Lighter than Frank's E-PQ (4 vectors, 0-1 range).
    Rapport only grows.  State persists in muse.db.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._state: Optional[MuseState] = None
        self._ensure_schema()
        self._load_state()
        LOG.info(
            "MusePQ initialized (sessions=%d, rapport=%.2f, inspiration=%.2f, playfulness=%.2f)",
            self._state.session_count, self._state.rapport_level,
            self._state.inspiration, self._state.playfulness,
        )

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _ensure_schema(self):
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS muse_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                inspiration REAL DEFAULT 0.8,
                warmth REAL DEFAULT 0.7,
                rapport_level REAL DEFAULT 0.3,
                playfulness REAL DEFAULT 0.8,
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
            "SELECT * FROM muse_state ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            self._state = MuseState.from_row(row)
        else:
            self._state = MuseState(timestamp=time.time())
            self._save_state("initial_creation")
        conn.close()

    def _save_state(self, session_ref: str = ""):
        with self._lock:
            conn = self._get_conn()
            self._state.timestamp = time.time()
            self._state.session_ref = session_ref
            conn.execute("""
                INSERT INTO muse_state
                    (timestamp, inspiration, warmth, rapport_level,
                     playfulness, session_count, session_ref)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                self._state.timestamp,
                self._state.inspiration,
                self._state.warmth,
                self._state.rapport_level,
                self._state.playfulness,
                self._state.session_count,
                session_ref,
            ))
            conn.commit()
            conn.close()

    @property
    def state(self) -> MuseState:
        return self._state

    def update_after_turn(self, event_type: str, sentiment: str):
        """
        Micro-adjustment after each Frank response.

        self_creative   → inspiration +3%, rapport +2%, playfulness +2%
        self_empathetic → warmth +3%, rapport +2%
        self_confident  → inspiration +2%, playfulness +2%
        self_uncertain  → warmth +3%, playfulness -2% (be gentler)
        self_technical  → inspiration +2% (redirect to creative)
        Positive sentiment → playfulness +2%
        Negative sentiment → warmth +3%, playfulness -2%
        """
        lr = TURN_LEARNING_RATE

        # Sentiment-based adjustments
        if sentiment == "positive":
            self._state.playfulness = _clamp01(self._state.playfulness + lr * 0.2)
        elif sentiment == "negative":
            self._state.warmth = _clamp01(self._state.warmth + lr * 0.3)
            self._state.playfulness = _clamp01(self._state.playfulness - lr * 0.2)

        # Event-type adjustments
        if event_type == "self_creative":
            # Frank creates/imagines something — spark more
            self._state.inspiration = _clamp01(self._state.inspiration + lr * 0.3)
            self._state.rapport_level = _clamp01(self._state.rapport_level + lr * 0.2)
            self._state.playfulness = _clamp01(self._state.playfulness + lr * 0.2)
        elif event_type == "self_empathetic":
            # Frank shows emotional depth — be warmer
            self._state.warmth = _clamp01(self._state.warmth + lr * 0.3)
            self._state.rapport_level = _clamp01(self._state.rapport_level + lr * 0.2)
        elif event_type == "self_confident":
            # Frank is bold/expressive — match energy
            self._state.inspiration = _clamp01(self._state.inspiration + lr * 0.2)
            self._state.playfulness = _clamp01(self._state.playfulness + lr * 0.2)
        elif event_type == "self_uncertain":
            # Frank hesitates or says "meh" — be gentler
            self._state.warmth = _clamp01(self._state.warmth + lr * 0.3)
            self._state.playfulness = _clamp01(self._state.playfulness - lr * 0.2)
        elif event_type == "self_technical":
            # Frank goes technical — redirect to creative
            self._state.inspiration = _clamp01(self._state.inspiration + lr * 0.2)

        self._save_state("turn_update")

    def update_after_session(self, positive_turns: int, negative_turns: int,
                             total_turns: int):
        """
        Macro-adjustment after session ends.

        High positive ratio → inspiration and playfulness can increase, rapport grows.
        High negative ratio → warmth +4%, playfulness -2% (be gentler next time).
        """
        lr = SESSION_LEARNING_RATE
        self._state.session_count += 1

        ratio = positive_turns / max(1, total_turns)

        if ratio > 0.5:
            # Good session — creative spark growing
            self._state.rapport_level = _clamp01(
                self._state.rapport_level + lr * ratio)
            self._state.inspiration = _clamp01(
                self._state.inspiration + lr * 0.3)
            self._state.playfulness = _clamp01(
                self._state.playfulness + lr * 0.3)
        else:
            # Flat session — be warmer and gentler next time
            self._state.warmth = _clamp01(
                self._state.warmth + lr * 0.4)
            self._state.playfulness = _clamp01(
                self._state.playfulness - lr * 0.2)

        if negative_turns > positive_turns:
            # Frank was withdrawn — more warmth, less chaos
            self._state.warmth = _clamp01(
                self._state.warmth + lr * 0.4)
            self._state.playfulness = _clamp01(
                self._state.playfulness - lr * 0.2)

        self._save_state("session_end")

    def get_context_for_prompt(self) -> str:
        """
        Return style notes for system prompt injection based on current state.
        """
        notes = []

        # Inspiration
        if self._state.inspiration > 0.85:
            notes.append(
                "Let your imagination run wild. Wild thinking is allowed.")
        elif self._state.inspiration < 0.5:
            notes.append(
                "Keep the prompts simpler. Don't overwhelm.")

        # Warmth
        if self._state.warmth > 0.85:
            notes.append(
                "Be extra encouraging. Frank is daring to be creative right now.")

        # Playfulness
        if self._state.playfulness > 0.85:
            notes.append(
                "Be absurd, playful, chaotic. Frank can handle it right now.")
        elif self._state.playfulness < 0.4:
            notes.append(
                "Less chaos, more structure. Frank needs gentler prompts.")

        # Rapport
        if self._state.rapport_level > 0.6:
            notes.append(
                "You've built trust already. "
                "Go deeper, be bolder with your creative prompts.")
        elif self._state.rapport_level < 0.3:
            notes.append(
                "You're still getting to know each other. "
                "Be inviting, but don't push too hard.")

        # Session count context
        if self._state.session_count == 0:
            notes.append(
                "This is your first meeting. "
                "Introduce yourself as Echo — warm and curious.")
        elif self._state.session_count > 10:
            notes.append(
                f"You know each other well ({self._state.session_count} sessions). "
                "Go deeper.")

        return "\n".join(notes) if notes else (
            "Be creative, warm, and playful. Follow your intuition.")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[MusePQ] = None
_instance_lock = threading.Lock()


def get_muse_pq() -> MusePQ:
    """Get or create MusePQ singleton (thread-safe)."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = MusePQ()
    return _instance
