"""
Chat Memory DB — Persistent conversation memory with FTS5 search.

Replaces the 20-message JSON file with a proper SQLite database.
Stores ALL messages with full text, provides semantic search for
smart LLM context building, and tracks sessions with summaries.

Author: Projekt Frankenstein
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

LOG = logging.getLogger("chat_memory")

try:
    from config.paths import get_db
    DB_PATH = get_db("chat_memory")
except ImportError:
    DB_PATH = Path("/home/ai-core-node/aicore/database/chat_memory.db")

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    role        TEXT    NOT NULL,
    sender      TEXT    NOT NULL,
    text        TEXT    NOT NULL,
    is_user     INTEGER NOT NULL DEFAULT 0,
    is_system   INTEGER NOT NULL DEFAULT 0,
    timestamp   REAL    NOT NULL,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_msg_ts ON messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_msg_role ON messages(role);

CREATE TABLE IF NOT EXISTS sessions (
    session_id      TEXT PRIMARY KEY,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    message_count   INTEGER DEFAULT 0,
    summary         TEXT DEFAULT ''
);
"""

# FTS5 and triggers created separately (can't be in multi-statement exec)
_FTS_SCHEMA = [
    """CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
       USING fts5(text, content=messages, content_rowid=id)""",

    """CREATE TRIGGER IF NOT EXISTS msg_fts_ai AFTER INSERT ON messages BEGIN
         INSERT INTO messages_fts(rowid, text) VALUES (new.id, new.text);
       END""",

    """CREATE TRIGGER IF NOT EXISTS msg_fts_ad AFTER DELETE ON messages BEGIN
         INSERT INTO messages_fts(messages_fts, rowid, text)
         VALUES ('delete', old.id, old.text);
       END""",

    """CREATE TRIGGER IF NOT EXISTS msg_fts_au AFTER UPDATE ON messages BEGIN
         INSERT INTO messages_fts(messages_fts, rowid, text)
         VALUES ('delete', old.id, old.text);
         INSERT INTO messages_fts(rowid, text) VALUES (new.id, new.text);
       END""",
]


class ChatMemoryDB:
    """SQLite-backed persistent conversation memory with FTS5 search."""

    def __init__(self, db_path: Path = DB_PATH):
        self._path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()
        self._ensure_db()

    # ── Setup ─────────────────────────────────────────────────────

    def _ensure_db(self):
        if self._conn is not None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self._path), timeout=10, check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        cur = self._conn.cursor()
        cur.executescript(_SCHEMA)
        for stmt in _FTS_SCHEMA:
            try:
                cur.execute(stmt)
            except sqlite3.OperationalError:
                pass  # already exists
        self._conn.commit()

    # ── Message Storage ───────────────────────────────────────────

    def store_message(
        self,
        session_id: str,
        role: str,
        sender: str,
        text: str,
        is_user: bool = False,
        is_system: bool = False,
        timestamp: Optional[float] = None,
    ) -> int:
        """Store a message. Returns message ID."""
        ts = timestamp or time.time()
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO messages
                   (session_id, role, sender, text, is_user, is_system, timestamp, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, role, sender, text,
                 int(is_user), int(is_system), ts,
                 datetime.fromtimestamp(ts).isoformat()),
            )
            # Increment session message count
            self._conn.execute(
                """UPDATE sessions SET message_count = message_count + 1
                   WHERE session_id = ?""",
                (session_id,),
            )
            self._conn.commit()
            return cur.lastrowid

    def get_recent_messages(self, limit: int = 50) -> List[dict]:
        """Get the N most recent non-system messages for UI display."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT id, session_id, role, sender, text, is_user,
                          is_system, timestamp, created_at
                   FROM messages
                   WHERE is_system = 0
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        # Return in chronological order
        return [dict(r) for r in reversed(rows)]

    def get_session_messages(self, session_id: str, limit: int = 100) -> List[dict]:
        """Get messages for a specific session."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT id, role, sender, text, is_user, is_system, timestamp
                   FROM messages
                   WHERE session_id = ? AND is_system = 0
                   ORDER BY timestamp ASC
                   LIMIT ?""",
                (session_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Smart Context Building ────────────────────────────────────

    def build_smart_context(
        self,
        query: str,
        recent_count: int = 5,
        max_chars: int = 2000,
    ) -> str:
        """Build LLM context: recent messages + FTS matches + session summaries."""
        parts = []
        budget = max_chars

        # 1) Recent messages (up to 800 chars)
        recent = self._get_recent_context(recent_count)
        if recent:
            lines = []
            chars = 0
            for m in recent:
                role = "User" if m["is_user"] else "Frank"
                text = m["text"]
                if len(text) > 200:
                    text = text[:200] + "..."
                line = f"{role}: {text}"
                if chars + len(line) > 800:
                    break
                lines.append(line)
                chars += len(line) + 1
            if lines:
                block = "[Previous conversation:\n" + "\n".join(lines) + "]"
                parts.append(block)
                budget -= len(block)

        # 2) FTS keyword matches from older messages (up to 600 chars)
        if query and budget > 200:
            relevant = self._search_relevant_history(query, limit=3, exclude_recent=10)
            if relevant:
                lines = []
                chars = 0
                for m in relevant:
                    age = self._format_age(m["timestamp"])
                    role = "User" if m["is_user"] else "Frank"
                    text = m["text"]
                    if len(text) > 150:
                        text = text[:150] + "..."
                    line = f"- [{age}] {role}: {text}"
                    if chars + len(line) > min(600, budget - 100):
                        break
                    lines.append(line)
                    chars += len(line) + 1
                if lines:
                    block = "[Relevant context from previous conversations:\n" + "\n".join(lines) + "]"
                    parts.append(block)
                    budget -= len(block)

        # 3) Session summaries (up to 400 chars)
        if budget > 100:
            summaries = self._get_recent_summaries(limit=3)
            if summaries:
                lines = []
                chars = 0
                for s in summaries:
                    date = s["started_at"][:10] if s.get("started_at") else "?"
                    line = f"- {date}: {s['summary']}"
                    if chars + len(line) > min(400, budget - 20):
                        break
                    lines.append(line)
                    chars += len(line) + 1
                if lines:
                    block = "[Session summaries:\n" + "\n".join(lines) + "]"
                    parts.append(block)

        return "\n".join(parts) + "\n" if parts else ""

    def _get_recent_context(self, count: int = 5) -> List[dict]:
        """Get last N non-system messages."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT role, sender, text, is_user, timestamp
                   FROM messages
                   WHERE is_system = 0
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                (count,),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def _search_relevant_history(
        self, query: str, limit: int = 3, exclude_recent: int = 10,
    ) -> List[dict]:
        """FTS5 search for relevant older messages."""
        # Build FTS query: use significant words only
        words = [w for w in query.split() if len(w) > 2]
        if not words:
            return []
        # OR-join for broader matching — quote each word to prevent FTS5 operator injection
        fts_query = " OR ".join(f'"{w}"' for w in words[:5])

        with self._lock:
            try:
                rows = self._conn.execute(
                    """SELECT m.id, m.role, m.sender, m.text, m.is_user, m.timestamp,
                              rank
                       FROM messages_fts fts
                       JOIN messages m ON m.id = fts.rowid
                       WHERE messages_fts MATCH ?
                         AND m.is_system = 0
                         AND m.id NOT IN (
                           SELECT id FROM messages
                           WHERE is_system = 0
                           ORDER BY timestamp DESC LIMIT ?
                         )
                       ORDER BY rank
                       LIMIT ?""",
                    (fts_query, exclude_recent, limit),
                ).fetchall()
                return [dict(r) for r in rows]
            except sqlite3.OperationalError as e:
                LOG.debug(f"FTS search error: {e}")
                return []

    def _get_recent_summaries(self, limit: int = 3) -> List[dict]:
        """Get recent session summaries."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT session_id, summary, started_at
                   FROM sessions
                   WHERE summary != '' AND summary IS NOT NULL
                   ORDER BY started_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _format_age(ts: float) -> str:
        """Format timestamp as relative age string."""
        delta = time.time() - ts
        if delta < 3600:
            return f"{int(delta / 60)} min ago"
        if delta < 86400:
            return f"{int(delta / 3600)} h ago"
        days = int(delta / 86400)
        return f"{days} day{'s' if days != 1 else ''} ago"

    # ── Session Management ────────────────────────────────────────

    def start_session(self, session_id: str):
        """Record a new session start."""
        with self._lock:
            self._conn.execute(
                """INSERT OR IGNORE INTO sessions (session_id, started_at)
                   VALUES (?, ?)""",
                (session_id, datetime.now().isoformat()),
            )
            self._conn.commit()

    def end_session(self, session_id: str):
        """Mark session as ended."""
        with self._lock:
            self._conn.execute(
                """UPDATE sessions SET ended_at = ?
                   WHERE session_id = ? AND ended_at IS NULL""",
                (datetime.now().isoformat(), session_id),
            )
            self._conn.commit()

    def store_session_summary(self, session_id: str, summary: str):
        """Store a generated session summary."""
        with self._lock:
            self._conn.execute(
                """UPDATE sessions SET summary = ?
                   WHERE session_id = ?""",
                (summary[:500], session_id),
            )
            self._conn.commit()

    def get_session_for_summarization(self) -> Optional[dict]:
        """Get an ended session that needs summarization."""
        with self._lock:
            row = self._conn.execute(
                """SELECT session_id, started_at, ended_at, message_count
                   FROM sessions
                   WHERE ended_at IS NOT NULL
                     AND (summary = '' OR summary IS NULL)
                     AND message_count >= 3
                   ORDER BY ended_at DESC
                   LIMIT 1""",
            ).fetchone()
        return dict(row) if row else None

    # ── Migration ─────────────────────────────────────────────────

    def migrate_from_json(self, json_path: Path, session_id: str) -> int:
        """Import existing chat_history.json. Returns count of imported messages."""
        if not json_path.exists():
            return 0
        try:
            data = json.loads(json_path.read_text())
            if not isinstance(data, list):
                return 0
        except Exception as e:
            LOG.warning(f"JSON migration read error: {e}")
            return 0

        self.start_session(session_id)
        count = 0
        for msg in data:
            text = msg.get("text", "")
            if not text:
                continue
            ts = msg.get("ts", time.time())
            self.store_message(
                session_id=session_id,
                role=msg.get("role", "frank"),
                sender=msg.get("sender", "Frank"),
                text=text,
                is_user=msg.get("is_user", False),
                timestamp=ts,
            )
            count += 1
        self.end_session(session_id)
        LOG.info(f"Migrated {count} messages from JSON to SQLite")
        return count

    # ── Maintenance ───────────────────────────────────────────────

    def cleanup_old_messages(self, retention_days: int = 30) -> int:
        """Archive old message text (keep summaries forever). Returns count."""
        cutoff = time.time() - (retention_days * 86400)
        with self._lock:
            cur = self._conn.execute(
                """UPDATE messages SET text = '[archived]'
                   WHERE timestamp < ?
                     AND text != '[archived]'
                     AND id NOT IN (
                       SELECT id FROM messages ORDER BY timestamp DESC LIMIT 200
                     )""",
                (cutoff,),
            )
            self._conn.commit()
            return cur.rowcount

    def get_stats(self) -> dict:
        """Return message counts, session counts."""
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            sessions = self._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            summaries = self._conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE summary != '' AND summary IS NOT NULL"
            ).fetchone()[0]
        return {
            "total_messages": total,
            "total_sessions": sessions,
            "sessions_with_summary": summaries,
        }

    def close(self):
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


# ── Standalone Self-Test ──────────────────────────────────────────

if __name__ == "__main__":
    import tempfile

    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    test_db = Path(tempfile.mktemp(suffix=".db"))
    print(f"Testing with temp DB: {test_db}")

    db = ChatMemoryDB(db_path=test_db)
    sid = f"test_{uuid.uuid4().hex[:8]}"

    # Start session
    db.start_session(sid)
    print(f"[OK] Session started: {sid}")

    # Store messages
    db.store_message(sid, "user", "Du", "Wie wird das Wetter morgen?", is_user=True)
    db.store_message(sid, "frank", "Frank", "Morgen wird es sonnig bei 18 Grad.", is_user=False)
    db.store_message(sid, "user", "Du", "Und uebermorgen?", is_user=True)
    db.store_message(sid, "frank", "Frank", "Uebermorgen leichter Regen, 14 Grad.", is_user=False)
    db.store_message(sid, "user", "Du", "Danke, erstelle ein todo fuer Regenschirm", is_user=True)
    print(f"[OK] 5 messages stored")

    # Get recent
    recent = db.get_recent_messages(limit=3)
    assert len(recent) == 3, f"Expected 3, got {len(recent)}"
    print(f"[OK] get_recent_messages(3) returned {len(recent)} messages")

    # FTS search
    relevant = db._search_relevant_history("Wetter Regen", limit=5, exclude_recent=0)
    assert len(relevant) > 0, "FTS search should find weather messages"
    print(f"[OK] FTS search 'Wetter Regen' found {len(relevant)} matches")

    # Smart context
    ctx = db.build_smart_context("Wie war das Wetter?", recent_count=3, max_chars=2000)
    assert "Bisheriges Gespraech" in ctx, "Should contain conversation context"
    print(f"[OK] build_smart_context returned {len(ctx)} chars")
    print(f"    Preview: {ctx[:200]}...")

    # Session management
    db.end_session(sid)
    db.store_session_summary(sid, "Wetter-Gespraech: sonnig morgen, Regen uebermorgen.")
    sess = db.get_session_for_summarization()
    assert sess is None, "Should not need summarization (already has summary)"
    print(f"[OK] Session ended and summary stored")

    # Stats
    stats = db.get_stats()
    assert stats["total_messages"] == 5
    assert stats["total_sessions"] == 1
    assert stats["sessions_with_summary"] == 1
    print(f"[OK] Stats: {stats}")

    # Migration test
    json_path = Path(tempfile.mktemp(suffix=".json"))
    json_path.write_text(json.dumps([
        {"role": "user", "sender": "Du", "text": "Hallo Frank", "is_user": True, "ts": time.time() - 3600},
        {"role": "frank", "sender": "Frank", "text": "Hey! Was kann ich tun?", "is_user": False, "ts": time.time() - 3590},
    ]))
    count = db.migrate_from_json(json_path, "legacy_test")
    assert count == 2
    print(f"[OK] Migration from JSON: {count} messages imported")

    # Cleanup
    db.close()
    test_db.unlink(missing_ok=True)
    json_path.unlink(missing_ok=True)

    print("\n=== ALL TESTS PASSED ===")
