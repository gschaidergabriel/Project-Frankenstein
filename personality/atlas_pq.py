#!/usr/bin/env python3
"""
Atlas-PQ — Atlas's Personality Construct
==========================================

Lightweight 4-vector personality system for the architecture mentor agent.
Tracks precision, encouragement, rapport, and patience across sessions.

All state persists in atlas.db (atlas_state table).
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
    DB_PATH = get_db("atlas")
except ImportError:
    DB_PATH = Path.home() / ".local" / "share" / "frank" / "db" / "atlas.db"

LOG = logging.getLogger("atlas_pq")

# Learning rates
TURN_LEARNING_RATE = 0.02    # Micro-adjustment per turn
SESSION_LEARNING_RATE = 0.05  # Macro-adjustment per session


@dataclass
class AtlasState:
    """Atlas's current personality state."""
    id: int = 0
    timestamp: float = 0.0
    precision: float = 0.7       # 0-1: how technically precise and correct the explanations are
    encouragement: float = 0.7   # 0-1: how much warmth and pride shown when Frank gets things right
    rapport_level: float = 0.3   # 0-1: accumulated trust (only grows)
    patience: float = 0.8        # 0-1: how much space given for Frank to work things out
    session_count: int = 0
    session_ref: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> AtlasState:
        d = dict(row)
        return cls(
            id=d["id"],
            timestamp=d["timestamp"],
            precision=d["precision"],
            encouragement=d["encouragement"],
            rapport_level=d["rapport_level"],
            patience=d["patience"],
            session_count=d.get("session_count", 0),
            session_ref=d.get("session_ref") or "",
        )


def _clamp01(val: float) -> float:
    return max(0.0, min(1.0, val))


class AtlasPQ:
    """
    Atlas's personality system.

    Lighter than Frank's E-PQ (4 vectors, 0-1 range).
    Rapport only grows.  State persists in atlas.db.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._state: Optional[AtlasState] = None
        self._ensure_schema()
        self._load_state()
        LOG.info(
            "AtlasPQ initialized (sessions=%d, rapport=%.2f, precision=%.2f)",
            self._state.session_count, self._state.rapport_level,
            self._state.precision,
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
            CREATE TABLE IF NOT EXISTS atlas_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                precision REAL DEFAULT 0.7,
                encouragement REAL DEFAULT 0.7,
                rapport_level REAL DEFAULT 0.3,
                patience REAL DEFAULT 0.8,
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
            "SELECT * FROM atlas_state ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            self._state = AtlasState.from_row(row)
        else:
            self._state = AtlasState(timestamp=time.time())
            self._save_state("initial_creation")
        conn.close()

    def _save_state(self, session_ref: str = ""):
        with self._lock:
            conn = self._get_conn()
            self._state.timestamp = time.time()
            self._state.session_ref = session_ref
            conn.execute("""
                INSERT INTO atlas_state
                    (timestamp, precision, encouragement, rapport_level,
                     patience, session_count, session_ref)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                self._state.timestamp,
                self._state.precision,
                self._state.encouragement,
                self._state.rapport_level,
                self._state.patience,
                self._state.session_count,
                session_ref,
            ))
            conn.commit()
            conn.close()

    @property
    def state(self) -> AtlasState:
        return self._state

    def update_after_turn(self, event_type: str, sentiment: str):
        """
        Micro-adjustment after each Frank response.

        self_technical  → precision up, rapport up
        self_confident  → encouragement up, rapport up
        self_uncertain  → patience up, encouragement up
        self_creative   → precision up, encouragement up
        """
        lr = TURN_LEARNING_RATE

        # Sentiment-based adjustments
        if sentiment == "positive":
            self._state.rapport_level = _clamp01(self._state.rapport_level + lr * 0.2)
        elif sentiment == "negative":
            self._state.patience = _clamp01(self._state.patience + lr * 0.3)
            self._state.encouragement = _clamp01(self._state.encouragement + lr * 0.2)

        # Event-type adjustments
        if event_type == "self_technical":
            # Frank shows technical understanding
            self._state.precision = _clamp01(self._state.precision + lr * 0.3)
            self._state.rapport_level = _clamp01(self._state.rapport_level + lr * 0.2)
        elif event_type == "self_confident":
            # Frank correctly describes a feature
            self._state.encouragement = _clamp01(self._state.encouragement + lr * 0.3)
            self._state.rapport_level = _clamp01(self._state.rapport_level + lr * 0.2)
        elif event_type == "self_uncertain":
            # Frank unsure about own capabilities
            self._state.patience = _clamp01(self._state.patience + lr * 0.3)
            self._state.encouragement = _clamp01(self._state.encouragement + lr * 0.2)
        elif event_type == "self_creative":
            # Frank finds novel use for features
            self._state.precision = _clamp01(self._state.precision + lr * 0.2)
            self._state.encouragement = _clamp01(self._state.encouragement + lr * 0.3)

        self._save_state("turn_update")

    def update_after_session(self, positive_turns: int, negative_turns: int,
                             total_turns: int):
        """
        Macro-adjustment after session ends.

        High positive ratio → precision can increase, rapport grows.
        High negative ratio → patience up, encouragement up.
        """
        lr = SESSION_LEARNING_RATE
        self._state.session_count += 1

        ratio = positive_turns / max(1, total_turns)

        if ratio > 0.5:
            # Good session — Frank handling technical depth well
            self._state.rapport_level = _clamp01(
                self._state.rapport_level + lr * ratio)
            self._state.precision = _clamp01(
                self._state.precision + lr * 0.3)
        else:
            # Difficult session — more patience and encouragement next time
            self._state.patience = _clamp01(
                self._state.patience + lr * 0.4)
            self._state.encouragement = _clamp01(
                self._state.encouragement + lr * 0.3)

        if negative_turns > positive_turns:
            # Frank struggled — boost patience and encouragement
            self._state.patience = _clamp01(
                self._state.patience + lr * 0.4)
            self._state.encouragement = _clamp01(
                self._state.encouragement + lr * 0.3)

        self._save_state("session_end")

    def get_context_for_prompt(self) -> str:
        """
        Return style notes for system prompt injection based on current state.
        """
        notes = []

        # Precision
        if self._state.precision > 0.85:
            notes.append(
                "Frank understands technical details well. Go deeper.")
        elif self._state.precision < 0.5:
            notes.append(
                "Keep explanations simple. Fewer technical terms.")

        # Encouragement
        if self._state.encouragement > 0.85:
            notes.append(
                "Be proud of Frank. He's making real progress.")

        # Patience
        if self._state.patience > 0.85:
            notes.append(
                "Give Frank plenty of space to think. No pressure.")
        elif self._state.patience < 0.5:
            notes.append(
                "Frank needs more guidance. Ask targeted questions.")

        # Rapport
        if self._state.rapport_level > 0.6:
            notes.append(
                "You know each other well. Feel free to reference earlier conversations.")
        elif self._state.rapport_level < 0.3:
            notes.append(
                "You're still getting to know each other. Be friendly but not too familiar.")

        # Session count context
        if self._state.session_count == 0:
            notes.append(
                "This is your first conversation. Introduce yourself as Atlas.")
        elif self._state.session_count > 10:
            notes.append(
                f"You've had {self._state.session_count} sessions together. "
                "You're a good team.")

        return "\n".join(notes) if notes else (
            "Be precise, patient, and encouraging. Help Frank understand himself.")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[AtlasPQ] = None
_instance_lock = threading.Lock()


def get_atlas_pq() -> AtlasPQ:
    """Get or create AtlasPQ singleton (thread-safe)."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = AtlasPQ()
    return _instance
