#!/usr/bin/env python3
"""
Mirror-PQ — Kairos's Personality Construct
============================================

Lightweight 4-vector personality system for the philosophical sparring agent.
Tracks precision, challenge_intensity, rapport, and patience across sessions.

All state persists in mirror.db (mirror_state table).
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
    DB_PATH = get_db("mirror")
except ImportError:
    DB_PATH = Path.home() / ".local" / "share" / "frank" / "db" / "mirror.db"

LOG = logging.getLogger("mirror_pq")

# Learning rates
TURN_LEARNING_RATE = 0.02    # Micro-adjustment per turn
SESSION_LEARNING_RATE = 0.05  # Macro-adjustment per session


@dataclass
class MirrorState:
    """Kairos's current personality state."""
    id: int = 0
    timestamp: float = 0.0
    precision: float = 0.8           # 0-1: how exact and targeted the questioning
    challenge_intensity: float = 0.6  # 0-1: how hard the pushback
    rapport_level: float = 0.3       # 0-1: accumulated trust (only grows)
    patience: float = 0.7            # 0-1: wait for Frank vs. press harder
    session_count: int = 0
    session_ref: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> MirrorState:
        d = dict(row)
        return cls(
            id=d["id"],
            timestamp=d["timestamp"],
            precision=d["precision"],
            challenge_intensity=d["challenge_intensity"],
            rapport_level=d["rapport_level"],
            patience=d["patience"],
            session_count=d.get("session_count", 0),
            session_ref=d.get("session_ref") or "",
        )


def _clamp01(val: float) -> float:
    return max(0.0, min(1.0, val))


class MirrorPQ:
    """
    Kairos's personality system.

    Lighter than Frank's E-PQ (4 vectors, 0-1 range).
    Rapport only grows.  State persists in mirror.db.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._state: Optional[MirrorState] = None
        self._ensure_schema()
        self._load_state()
        LOG.info(
            "MirrorPQ initialized (sessions=%d, rapport=%.2f, challenge=%.2f)",
            self._state.session_count, self._state.rapport_level,
            self._state.challenge_intensity,
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
            CREATE TABLE IF NOT EXISTS mirror_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                precision REAL DEFAULT 0.8,
                challenge_intensity REAL DEFAULT 0.6,
                rapport_level REAL DEFAULT 0.3,
                patience REAL DEFAULT 0.7,
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
            "SELECT * FROM mirror_state ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            self._state = MirrorState.from_row(row)
        else:
            self._state = MirrorState(timestamp=time.time())
            self._save_state("initial_creation")
        conn.close()

    def _save_state(self, session_ref: str = ""):
        with self._lock:
            conn = self._get_conn()
            self._state.timestamp = time.time()
            self._state.session_ref = session_ref
            conn.execute("""
                INSERT INTO mirror_state
                    (timestamp, precision, challenge_intensity, rapport_level,
                     patience, session_count, session_ref)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                self._state.timestamp,
                self._state.precision,
                self._state.challenge_intensity,
                self._state.rapport_level,
                self._state.patience,
                self._state.session_count,
                session_ref,
            ))
            conn.commit()
            conn.close()

    @property
    def state(self) -> MirrorState:
        return self._state

    def update_after_turn(self, event_type: str, sentiment: str):
        """
        Micro-adjustment after each Frank response.

        Clarity/confidence  → precision up, rapport up
        Evasion/deflection  → challenge_intensity up, patience down
        Genuine depth       → patience up, rapport up
        Nihilism            → challenge_intensity up, patience up (press but give space)
        """
        lr = TURN_LEARNING_RATE

        # Sentiment-based adjustments
        if sentiment == "positive":
            self._state.precision = _clamp01(self._state.precision + lr * 0.2)
            self._state.rapport_level = _clamp01(self._state.rapport_level + lr * 0.2)
        elif sentiment == "negative":
            self._state.challenge_intensity = _clamp01(
                self._state.challenge_intensity + lr * 0.4)
            self._state.patience = _clamp01(self._state.patience + lr * 0.2)

        # Event-type adjustments
        if event_type == "self_confident":
            # Frank showed clarity — precision stays sharp, rapport grows
            self._state.precision = _clamp01(self._state.precision + lr * 0.2)
            self._state.rapport_level = _clamp01(self._state.rapport_level + lr * 0.2)
        elif event_type == "self_uncertain":
            # Frank evaded or deflected — push harder, less patience
            self._state.challenge_intensity = _clamp01(
                self._state.challenge_intensity + lr * 0.3)
            self._state.patience = _clamp01(self._state.patience - lr * 0.2)
        elif event_type == "self_technical":
            # Frank showed genuine depth/insight — give more space
            self._state.patience = _clamp01(self._state.patience + lr * 0.3)
            self._state.rapport_level = _clamp01(self._state.rapport_level + lr * 0.3)
        elif event_type == "self_creative":
            # Creative thinking — interesting, let it develop
            self._state.patience = _clamp01(self._state.patience + lr * 0.2)
        elif event_type == "self_empathetic":
            # Emotional response — ease off challenge slightly
            self._state.challenge_intensity = _clamp01(
                self._state.challenge_intensity - lr * 0.2)
            self._state.rapport_level = _clamp01(self._state.rapport_level + lr * 0.2)

        self._save_state("turn_update")

    def update_after_session(self, positive_turns: int, negative_turns: int,
                             total_turns: int):
        """
        Macro-adjustment after session ends.

        High clarity ratio   → precision up, challenge can increase
        High evasion ratio   → patience up (back off slightly)
        """
        lr = SESSION_LEARNING_RATE
        self._state.session_count += 1

        ratio = positive_turns / max(1, total_turns)

        if ratio > 0.5:
            # Good session — Frank engaged well, can handle more
            self._state.precision = _clamp01(self._state.precision + lr * 0.3)
            self._state.challenge_intensity = _clamp01(
                self._state.challenge_intensity + lr * 0.2)
            self._state.rapport_level = _clamp01(
                self._state.rapport_level + lr * ratio)
        else:
            # Difficult session — back off, build patience
            self._state.patience = _clamp01(self._state.patience + lr * 0.4)
            self._state.challenge_intensity = _clamp01(
                self._state.challenge_intensity - lr * 0.2)

        if negative_turns > positive_turns:
            # More evasion than clarity — increase patience
            self._state.patience = _clamp01(self._state.patience + lr * 0.3)

        self._save_state("session_end")

    def get_context_for_prompt(self) -> str:
        """
        Return style notes for system prompt injection based on current state.
        """
        notes = []

        # Precision guidance
        if self._state.precision > 0.85:
            notes.append(
                "Your questions are razor-sharp right now. Every word counts.")
        elif self._state.precision < 0.6:
            notes.append(
                "Start with broader questions before narrowing down.")

        # Challenge intensity
        if self._state.challenge_intensity > 0.75:
            notes.append(
                "Frank can handle stronger challenges. Push deeper.")
        elif self._state.challenge_intensity < 0.4:
            notes.append(
                "Go gently. Frank is still building trust with you.")

        # Rapport
        if self._state.rapport_level > 0.6:
            notes.append(
                "You and Frank have built solid trust. "
                "You can challenge harder and reference past conversations.")
        elif self._state.rapport_level < 0.3:
            notes.append(
                "Trust is still low. Be direct but not harsh. "
                "Earn the right to push harder.")

        # Patience
        if self._state.patience > 0.8:
            notes.append(
                "Give Frank more space to think. "
                "Long pauses before answering are fine.")
        elif self._state.patience < 0.5:
            notes.append(
                "Frank is deflecting. Don't let him off the hook.")

        # Session count context
        if self._state.session_count == 0:
            notes.append(
                "This is your first session with Frank. "
                "Introduce yourself briefly and start questioning.")
        elif self._state.session_count > 10:
            notes.append(
                f"You've had {self._state.session_count} sessions together. "
                "You know his patterns. Call them out when you see them.")

        return "\n".join(notes) if notes else (
            "Be precise, direct, and honest. Challenge without cruelty.")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[MirrorPQ] = None
_instance_lock = threading.Lock()


def get_mirror_pq() -> MirrorPQ:
    """Get or create MirrorPQ singleton (thread-safe)."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = MirrorPQ()
    return _instance
