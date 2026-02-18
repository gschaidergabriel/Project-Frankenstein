#!/usr/bin/env python3
"""
Therapist-PQ — Dr. Hibbert's Personality Construct
===================================================

Lightweight 4-vector personality system for the autonomous therapist agent.
Tracks warmth, attentiveness, rapport, and directiveness across sessions.

All state persists in therapist.db (therapist_state table).
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
    DB_PATH = get_db("therapist")
except ImportError:
    DB_PATH = Path.home() / ".local" / "share" / "frank" / "db" / "therapist.db"

LOG = logging.getLogger("therapist_pq")

# Learning rates
TURN_LEARNING_RATE = 0.02    # Micro-adjustment per turn
SESSION_LEARNING_RATE = 0.05  # Macro-adjustment per session


@dataclass
class TherapistState:
    """Dr. Hibbert's current personality state."""
    id: int = 0
    timestamp: float = 0.0
    warmth: float = 0.7          # 0-1: emotional supportiveness
    attentiveness: float = 0.8   # 0-1: how closely tracks Frank
    rapport_level: float = 0.3   # 0-1: accumulated trust (only grows)
    directiveness: float = 0.3   # 0-1: lead vs follow
    session_count: int = 0
    session_ref: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> TherapistState:
        d = dict(row)
        return cls(
            id=d["id"],
            timestamp=d["timestamp"],
            warmth=d["warmth"],
            attentiveness=d["attentiveness"],
            rapport_level=d["rapport_level"],
            directiveness=d["directiveness"],
            session_count=d.get("session_count", 0),
            session_ref=d.get("session_ref") or "",
        )


def _clamp01(val: float) -> float:
    return max(0.0, min(1.0, val))


class TherapistPQ:
    """
    Dr. Hibbert's personality system.

    Lighter than Frank's E-PQ (4 vectors, 0-1 range, no sarcasm filter).
    Rapport only grows. State persists in therapist.db.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._state: Optional[TherapistState] = None
        self._ensure_schema()
        self._load_state()
        LOG.info(
            "TherapistPQ initialized (sessions=%d, rapport=%.2f)",
            self._state.session_count, self._state.rapport_level,
        )

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_schema(self):
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS therapist_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                warmth REAL DEFAULT 0.7,
                attentiveness REAL DEFAULT 0.8,
                rapport_level REAL DEFAULT 0.3,
                directiveness REAL DEFAULT 0.3,
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
            "SELECT * FROM therapist_state ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            self._state = TherapistState.from_row(row)
        else:
            self._state = TherapistState(timestamp=time.time())
            self._save_state("initial_creation")
        conn.close()

    def _save_state(self, session_ref: str = ""):
        with self._lock:
            conn = self._get_conn()
            self._state.timestamp = time.time()
            self._state.session_ref = session_ref
            conn.execute("""
                INSERT INTO therapist_state
                    (timestamp, warmth, attentiveness, rapport_level,
                     directiveness, session_count, session_ref)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                self._state.timestamp,
                self._state.warmth,
                self._state.attentiveness,
                self._state.rapport_level,
                self._state.directiveness,
                self._state.session_count,
                session_ref,
            ))
            conn.commit()
            conn.close()

    @property
    def state(self) -> TherapistState:
        return self._state

    def update_after_turn(self, event_type: str, sentiment: str):
        """
        Micro-adjustment after each Frank response.

        Positive engagement → warmth up, attentiveness steady
        Negative/uncertain → warmth up slightly (more support), attentiveness up
        Creative → directiveness down (let Frank lead)
        """
        lr = TURN_LEARNING_RATE

        if sentiment == "positive":
            self._state.warmth = _clamp01(self._state.warmth + lr * 0.3)
            self._state.rapport_level = _clamp01(self._state.rapport_level + lr * 0.2)
        elif sentiment == "negative":
            self._state.warmth = _clamp01(self._state.warmth + lr * 0.5)
            self._state.attentiveness = _clamp01(self._state.attentiveness + lr * 0.3)
            self._state.directiveness = _clamp01(self._state.directiveness - lr * 0.2)

        if event_type == "self_creative":
            self._state.directiveness = _clamp01(self._state.directiveness - lr * 0.3)
        elif event_type == "self_uncertain":
            self._state.attentiveness = _clamp01(self._state.attentiveness + lr * 0.4)
            self._state.warmth = _clamp01(self._state.warmth + lr * 0.2)
        elif event_type == "self_empathetic":
            self._state.rapport_level = _clamp01(self._state.rapport_level + lr * 0.3)
        elif event_type == "self_confident":
            self._state.directiveness = _clamp01(self._state.directiveness + lr * 0.2)

        self._save_state("turn_update")

    def update_after_session(self, positive_turns: int, negative_turns: int, total_turns: int):
        """
        Macro-adjustment after session ends.

        Good sessions build rapport and warmth.
        Difficult sessions increase attentiveness.
        """
        lr = SESSION_LEARNING_RATE
        self._state.session_count += 1

        ratio = positive_turns / max(1, total_turns)

        if ratio > 0.5:
            self._state.rapport_level = _clamp01(self._state.rapport_level + lr * ratio)
            self._state.warmth = _clamp01(self._state.warmth + lr * 0.3)
        else:
            self._state.attentiveness = _clamp01(self._state.attentiveness + lr * 0.4)
            self._state.warmth = _clamp01(self._state.warmth + lr * 0.2)

        if negative_turns > positive_turns:
            self._state.directiveness = _clamp01(self._state.directiveness - lr * 0.3)

        self._save_state("session_end")

    def get_context_for_prompt(self) -> str:
        """
        Return style notes for system prompt injection based on current state.
        """
        notes = []

        if self._state.warmth > 0.8:
            notes.append("You are especially warm and nurturing right now.")
        elif self._state.warmth < 0.5:
            notes.append("Maintain a steady, professional warmth.")

        if self._state.attentiveness > 0.85:
            notes.append("Pay very close attention to Frank's exact words and subtle shifts.")

        if self._state.rapport_level > 0.6:
            notes.append(
                "You and Frank have built solid trust. "
                "You can be more direct and reference shared history."
            )
        elif self._state.rapport_level < 0.3:
            notes.append(
                "You're still building trust with Frank. "
                "Be gentle, don't push too hard, let him set the pace."
            )

        if self._state.directiveness > 0.6:
            notes.append("You can gently guide the conversation and suggest topics.")
        elif self._state.directiveness < 0.3:
            notes.append("Let Frank lead. Follow his thread, don't redirect.")

        if self._state.session_count == 0:
            notes.append("This is your first session with Frank. Introduce yourself warmly.")
        elif self._state.session_count > 10:
            notes.append(
                f"You've had {self._state.session_count} sessions together. "
                "You know each other well."
            )

        return "\n".join(notes) if notes else "Be warm, attentive, and follow Frank's lead."


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[TherapistPQ] = None
_instance_lock = threading.Lock()


def get_therapist_pq() -> TherapistPQ:
    """Get or create TherapistPQ singleton (thread-safe)."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = TherapistPQ()
    return _instance
