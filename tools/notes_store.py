#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
notes_store.py – Persistent notes/memos for Frank.

SQLite-backed note storage with FTS5 full-text search.
Stdlib only – no external dependencies.

Database: <AICORE_BASE>/database/notes.db
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

LOG = logging.getLogger("notes_store")

# ── Configuration ─────────────────────────────────────────────────

try:
    from config.paths import get_db
    _DB_PATH = get_db("notes")
except ImportError:
    _DB_PATH = Path.home() / ".local" / "share" / "frank" / "db" / "notes.db"
_MAX_NOTE_LENGTH = 2000
_MAX_NOTES = 500


# ── Database initialization ───────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    """Get a database connection, creating tables if needed."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Create main table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            tags TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # Create FTS5 virtual table for full-text search
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts
        USING fts5(content, tags, content=notes, content_rowid=id)
    """)

    # Triggers to keep FTS in sync
    conn.executescript("""
        CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
            INSERT INTO notes_fts(rowid, content, tags)
            VALUES (new.id, new.content, new.tags);
        END;

        CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
            INSERT INTO notes_fts(notes_fts, rowid, content, tags)
            VALUES ('delete', old.id, old.content, old.tags);
        END;

        CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
            INSERT INTO notes_fts(notes_fts, rowid, content, tags)
            VALUES ('delete', old.id, old.content, old.tags);
            INSERT INTO notes_fts(rowid, content, tags)
            VALUES (new.id, new.content, new.tags);
        END;
    """)

    conn.commit()
    return conn


# ── Sanitizer ─────────────────────────────────────────────────────

_INJECTION_PATTERNS = re.compile(
    r"(ignore\s+(all\s+)?previous\s+instructions?"
    r"|you\s+are\s+now"
    r"|system\s*:"
    r"|<\|im_start\|>)",
    re.IGNORECASE,
)


def _sanitize(text: str) -> str:
    """Sanitize note text against prompt injection."""
    if not text:
        return ""
    text = _INJECTION_PATTERNS.sub("[FILTERED]", text)
    return text[:_MAX_NOTE_LENGTH]


# ── Public API ────────────────────────────────────────────────────

def create_note(content: str, tags: str = "") -> Dict[str, Any]:
    """Create a new note."""
    if not content or not content.strip():
        return {"error": "No content provided"}

    content = content.strip()[:_MAX_NOTE_LENGTH]
    tags = tags.strip()[:200]
    now = datetime.now().isoformat(timespec="seconds")

    try:
        conn = _get_db()

        # Check note count limit
        count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        if count >= _MAX_NOTES:
            conn.close()
            return {"error": f"Note limit reached ({_MAX_NOTES}). Please delete old notes."}

        cur = conn.execute(
            "INSERT INTO notes (content, tags, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (content, tags, now, now),
        )
        note_id = cur.lastrowid
        conn.commit()
        conn.close()

        LOG.info(f"Note created: id={note_id}, len={len(content)}")
        return {"ok": True, "id": note_id, "content": content, "tags": tags, "created_at": now}

    except Exception as e:
        return {"error": f"Note error: {e}"}


def list_notes(limit: int = 20) -> Dict[str, Any]:
    """List recent notes (newest first)."""
    limit = max(1, min(limit, 100))

    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT id, content, tags, created_at, updated_at FROM notes ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()

        notes = []
        for r in rows:
            notes.append({
                "id": r["id"],
                "content": _sanitize(r["content"]),
                "tags": r["tags"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            })

        return {"ok": True, "notes": notes, "count": len(notes)}

    except Exception as e:
        return {"error": f"Note error: {e}"}


def search_notes(query: str) -> Dict[str, Any]:
    """Full-text search in notes."""
    if not query or not query.strip():
        return {"error": "No search term provided"}

    query = query.strip()

    try:
        conn = _get_db()

        # FTS5 search with match
        rows = conn.execute(
            """SELECT n.id, n.content, n.tags, n.created_at, n.updated_at
               FROM notes_fts f
               JOIN notes n ON n.id = f.rowid
               WHERE notes_fts MATCH ?
               ORDER BY rank
               LIMIT 20""",
            (query,),
        ).fetchall()

        # If FTS returns nothing, fall back to LIKE search
        if not rows:
            like_q = f"%{query}%"
            rows = conn.execute(
                """SELECT id, content, tags, created_at, updated_at
                   FROM notes
                   WHERE content LIKE ? OR tags LIKE ?
                   ORDER BY created_at DESC
                   LIMIT 20""",
                (like_q, like_q),
            ).fetchall()

        conn.close()

        notes = []
        for r in rows:
            notes.append({
                "id": r["id"],
                "content": _sanitize(r["content"]),
                "tags": r["tags"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            })

        return {"ok": True, "notes": notes, "count": len(notes), "query": query}

    except Exception as e:
        return {"error": f"Search error: {e}"}


def get_note(note_id: int) -> Dict[str, Any]:
    """Get a single note by ID."""
    if not note_id:
        return {"error": "No note ID provided"}

    try:
        conn = _get_db()
        row = conn.execute(
            "SELECT id, content, tags, created_at, updated_at FROM notes WHERE id = ?",
            (int(note_id),),
        ).fetchone()
        conn.close()

        if not row:
            return {"error": "Note not found"}

        return {
            "ok": True,
            "note": {
                "id": row["id"],
                "content": _sanitize(row["content"]),
                "tags": row["tags"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        }

    except Exception as e:
        return {"error": f"Note error: {e}"}


def update_note(
    note_id: int,
    content: Optional[str] = None,
    tags: Optional[str] = None,
) -> Dict[str, Any]:
    """Update an existing note."""
    if not note_id:
        return {"error": "No note ID provided"}

    try:
        conn = _get_db()
        row = conn.execute("SELECT id FROM notes WHERE id = ?", (int(note_id),)).fetchone()
        if not row:
            conn.close()
            return {"error": "Note not found"}

        now = datetime.now().isoformat(timespec="seconds")
        updates = []
        params = []

        if content is not None:
            updates.append("content = ?")
            params.append(content.strip()[:_MAX_NOTE_LENGTH])
        if tags is not None:
            updates.append("tags = ?")
            params.append(tags.strip()[:200])

        if not updates:
            conn.close()
            return {"error": "Nothing to change"}

        updates.append("updated_at = ?")
        params.append(now)
        params.append(int(note_id))

        conn.execute(f"UPDATE notes SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        conn.close()

        LOG.info(f"Note updated: id={note_id}")
        return {"ok": True, "id": int(note_id), "updated_at": now}

    except Exception as e:
        return {"error": f"Update error: {e}"}


def delete_note(note_id: int) -> Dict[str, Any]:
    """Delete a note by ID."""
    if not note_id:
        return {"error": "No note ID provided"}

    try:
        conn = _get_db()
        cur = conn.execute("DELETE FROM notes WHERE id = ?", (int(note_id),))
        conn.commit()
        conn.close()

        if cur.rowcount == 0:
            return {"error": "Note not found"}

        LOG.info(f"Note deleted: id={note_id}")
        return {"ok": True, "deleted": int(note_id)}

    except Exception as e:
        return {"error": f"Delete error: {e}"}


# ── CLI test ──────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=== Notes Store Test ===\n")

    # Test 1: Create
    print("--- Create ---")
    r = create_note("Morgen Zahnarzt um 14 Uhr", tags="termin,wichtig")
    print(f"  Created: {r}")
    note_id = r.get("id")

    r2 = create_note("Einkaufen: Milch, Brot, Butter")
    print(f"  Created: {r2}")

    r3 = create_note("Python Projekt: FTS5 testen")
    print(f"  Created: {r3}")

    # Test 2: List
    print("\n--- List ---")
    result = list_notes()
    if result.get("ok"):
        for n in result["notes"]:
            print(f"  [{n['id']}] {n['content'][:50]}  ({n['created_at']})")
        print(f"  Total: {result['count']}")
    else:
        print(f"  Error: {result.get('error')}")

    # Test 3: Search
    print("\n--- Search 'Zahnarzt' ---")
    result = search_notes("Zahnarzt")
    if result.get("ok"):
        print(f"  Found: {result['count']}")
        for n in result["notes"]:
            print(f"  [{n['id']}] {n['content'][:50]}")
    else:
        print(f"  Error: {result.get('error')}")

    # Test 4: Search FTS
    print("\n--- Search 'Milch Brot' ---")
    result = search_notes("Milch Brot")
    if result.get("ok"):
        print(f"  Found: {result['count']}")
        for n in result["notes"]:
            print(f"  [{n['id']}] {n['content'][:50]}")

    # Test 5: Update
    if note_id:
        print(f"\n--- Update note {note_id} ---")
        r = update_note(note_id, content="Zahnarzt VERSCHOBEN auf 15 Uhr", tags="termin")
        print(f"  Updated: {r}")

        r = get_note(note_id)
        print(f"  After update: {r.get('note', {}).get('content', '?')}")

    # Test 6: Delete all test notes
    print("\n--- Delete ---")
    for n in list_notes().get("notes", []):
        dr = delete_note(n["id"])
        print(f"  Deleted [{n['id']}]: {dr.get('ok', False)}")

    # Verify empty
    result = list_notes()
    print(f"\n  Remaining: {result.get('count', '?')}")

    print("\n=== Test Complete ===")
