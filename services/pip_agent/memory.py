"""Pip's conversational memory — SQLite persistence."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Dict, List

LOG = logging.getLogger("pip_agent.memory")


def _get_db_path() -> Path:
    try:
        from config.paths import get_db
        return get_db("pip_agent")
    except (ImportError, KeyError):
        p = Path.home() / ".local" / "share" / "frank" / "db" / "pip_agent.db"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


class PipMemory:
    """SQLite-backed conversational memory and personality persistence."""

    def __init__(self) -> None:
        self._db_path = _get_db_path()
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    ts REAL NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_conv_session
                    ON conversations(session_id);
                CREATE INDEX IF NOT EXISTS idx_conv_ts
                    ON conversations(ts);

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    ts REAL NOT NULL,
                    task_type TEXT NOT NULL,
                    params_json TEXT,
                    result_json TEXT,
                    success INTEGER DEFAULT 0,
                    duration_s REAL
                );

                CREATE TABLE IF NOT EXISTS personality (
                    trait TEXT PRIMARY KEY,
                    value REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
            """)
            conn.commit()
        finally:
            conn.close()
        LOG.info("Memory DB at %s", self._db_path)

    # ---- messages ---------------------------------------------------

    def store_message(self, session_id: str, role: str, content: str) -> None:
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute(
                "INSERT INTO conversations (session_id, ts, role, content) "
                "VALUES (?, ?, ?, ?)",
                (session_id, time.time(), role, content),
            )
            conn.commit()
        finally:
            conn.close()

    def get_recent_messages(self, session_id: str,
                            limit: int = 20) -> List[Dict]:
        conn = sqlite3.connect(str(self._db_path))
        try:
            rows = conn.execute(
                "SELECT role, content, ts FROM conversations "
                "WHERE session_id = ? ORDER BY ts DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
            return [{"role": r[0], "content": r[1], "ts": r[2]}
                    for r in reversed(rows)]
        finally:
            conn.close()

    def get_conversation_history(self, limit: int = 50) -> List[Dict]:
        """Recent messages across all sessions."""
        conn = sqlite3.connect(str(self._db_path))
        try:
            rows = conn.execute(
                "SELECT session_id, role, content, ts "
                "FROM conversations ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                {"session_id": r[0], "role": r[1],
                 "content": r[2], "ts": r[3]}
                for r in reversed(rows)
            ]
        finally:
            conn.close()

    # ---- tasks ------------------------------------------------------

    def store_task(self, session_id: str, task_type: str,
                   params: dict, result: dict,
                   success: bool, duration: float) -> None:
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute(
                "INSERT INTO tasks "
                "(session_id, ts, task_type, params_json, "
                " result_json, success, duration_s) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, time.time(), task_type,
                 json.dumps(params), json.dumps(result),
                 int(success), duration),
            )
            conn.commit()
        finally:
            conn.close()

    # ---- personality ------------------------------------------------

    _DEFAULTS = {
        "helpfulness": 0.9,
        "curiosity": 0.7,
        "precision": 0.8,
        "warmth": 0.6,
        "energy": 0.7,
    }

    def get_personality_traits(self) -> Dict[str, float]:
        conn = sqlite3.connect(str(self._db_path))
        try:
            rows = conn.execute(
                "SELECT trait, value FROM personality"
            ).fetchall()
            if rows:
                return {r[0]: r[1] for r in rows}
            for trait, val in self._DEFAULTS.items():
                conn.execute(
                    "INSERT OR REPLACE INTO personality "
                    "(trait, value, updated_at) VALUES (?, ?, ?)",
                    (trait, val, time.time()),
                )
            conn.commit()
            return dict(self._DEFAULTS)
        finally:
            conn.close()

    def update_trait(self, trait: str, value: float) -> None:
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute(
                "INSERT OR REPLACE INTO personality "
                "(trait, value, updated_at) VALUES (?, ?, ?)",
                (trait, max(0.0, min(1.0, value)), time.time()),
            )
            conn.commit()
        finally:
            conn.close()

    def cleanup_old(self, days: int = 30) -> None:
        cutoff = time.time() - days * 86400
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute("DELETE FROM conversations WHERE ts < ?", (cutoff,))
            conn.execute("DELETE FROM tasks WHERE ts < ?", (cutoff,))
            conn.commit()
        finally:
            conn.close()
