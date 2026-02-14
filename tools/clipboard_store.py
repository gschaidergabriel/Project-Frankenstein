#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clipboard_store.py -- Persistent clipboard history for Frank.

SQLite-backed, max 50 entries, auto-prune oldest.
Duplicate detection via SHA-256 hash (re-surfaces existing entry).
Simple LIKE search (no FTS5 needed for 50 entries).

Database: /home/ai-core-node/aicore/database/clipboard_history.db
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

LOG = logging.getLogger("clipboard_store")

try:
    from config.paths import get_db
    _DB_PATH = get_db("clipboard_history")
except ImportError:
    _DB_PATH = Path("/home/ai-core-node/aicore/database/clipboard_history.db")
_MAX_ENTRIES = 50
_MAX_CONTENT_LENGTH = 10_000
_PREVIEW_LENGTH = 100


def _get_db() -> sqlite3.Connection:
    """Get a database connection, creating tables if needed."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clipboard_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            preview TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            content_hash TEXT NOT NULL UNIQUE
        )
    """)
    conn.commit()
    return conn


def _make_preview(content: str) -> str:
    """Create a short preview: first N chars, newlines → spaces."""
    preview = content.replace("\n", " ").replace("\r", " ").strip()
    if len(preview) > _PREVIEW_LENGTH:
        preview = preview[:_PREVIEW_LENGTH] + "..."
    return preview


def _compute_hash(content: str) -> str:
    """SHA-256 hash of content for deduplication."""
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()


def add_entry(content: str) -> Dict[str, Any]:
    """Add a clipboard entry. Dedup: if hash exists, update timestamp."""
    if not content or not content.strip():
        return {"ok": False, "error": "Leerer Inhalt"}

    content = content[:_MAX_CONTENT_LENGTH]
    content_hash = _compute_hash(content)
    preview = _make_preview(content)
    now = datetime.now().isoformat()

    try:
        conn = _get_db()

        # Check for duplicate
        existing = conn.execute(
            "SELECT id FROM clipboard_entries WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()

        if existing:
            # Re-surface: update timestamp
            conn.execute(
                "UPDATE clipboard_entries SET timestamp = ? WHERE id = ?",
                (now, existing["id"]),
            )
            conn.commit()
            conn.close()
            return {"ok": True, "id": existing["id"], "duplicate": True}

        # Insert new entry
        cur = conn.execute(
            "INSERT INTO clipboard_entries (content, preview, timestamp, content_hash) VALUES (?, ?, ?, ?)",
            (content, preview, now, content_hash),
        )
        new_id = cur.lastrowid

        # Auto-prune: keep only _MAX_ENTRIES
        count = conn.execute("SELECT COUNT(*) FROM clipboard_entries").fetchone()[0]
        if count > _MAX_ENTRIES:
            conn.execute("""
                DELETE FROM clipboard_entries WHERE id IN (
                    SELECT id FROM clipboard_entries ORDER BY timestamp ASC LIMIT ?
                )
            """, (count - _MAX_ENTRIES,))

        conn.commit()
        conn.close()
        return {"ok": True, "id": new_id}

    except Exception as e:
        LOG.error(f"clipboard add_entry error: {e}")
        return {"ok": False, "error": str(e)}


def list_entries(limit: int = 20) -> Dict[str, Any]:
    """List recent clipboard entries, newest first."""
    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT id, preview, timestamp, length(content) as size FROM clipboard_entries ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()

        entries = [
            {"id": r["id"], "preview": r["preview"], "timestamp": r["timestamp"], "size": r["size"]}
            for r in rows
        ]
        return {"ok": True, "entries": entries, "count": len(entries)}

    except Exception as e:
        LOG.error(f"clipboard list_entries error: {e}")
        return {"ok": False, "error": str(e)}


def search_entries(query: str) -> Dict[str, Any]:
    """Search clipboard history by content (LIKE match)."""
    if not query or not query.strip():
        return list_entries(limit=20)

    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT id, preview, timestamp, length(content) as size FROM clipboard_entries WHERE content LIKE ? ORDER BY timestamp DESC LIMIT 20",
            (f"%{query}%",),
        ).fetchall()
        conn.close()

        entries = [
            {"id": r["id"], "preview": r["preview"], "timestamp": r["timestamp"], "size": r["size"]}
            for r in rows
        ]
        return {"ok": True, "entries": entries, "count": len(entries), "query": query}

    except Exception as e:
        LOG.error(f"clipboard search_entries error: {e}")
        return {"ok": False, "error": str(e)}


def get_entry(entry_id: int) -> Dict[str, Any]:
    """Get a single clipboard entry by ID (full content)."""
    try:
        conn = _get_db()
        row = conn.execute(
            "SELECT id, content, preview, timestamp FROM clipboard_entries WHERE id = ?",
            (entry_id,),
        ).fetchone()
        conn.close()

        if not row:
            return {"ok": False, "error": f"Eintrag #{entry_id} nicht gefunden"}

        return {
            "ok": True,
            "entry": {
                "id": row["id"],
                "content": row["content"],
                "preview": row["preview"],
                "timestamp": row["timestamp"],
            },
        }

    except Exception as e:
        LOG.error(f"clipboard get_entry error: {e}")
        return {"ok": False, "error": str(e)}


def delete_entry(entry_id: int) -> Dict[str, Any]:
    """Delete a clipboard entry by ID."""
    try:
        conn = _get_db()
        cur = conn.execute("DELETE FROM clipboard_entries WHERE id = ?", (entry_id,))
        conn.commit()
        conn.close()

        if cur.rowcount == 0:
            return {"ok": False, "error": f"Eintrag #{entry_id} nicht gefunden"}
        return {"ok": True, "deleted_id": entry_id}

    except Exception as e:
        LOG.error(f"clipboard delete_entry error: {e}")
        return {"ok": False, "error": str(e)}


def clear_all() -> Dict[str, Any]:
    """Delete all clipboard history entries."""
    try:
        conn = _get_db()
        cur = conn.execute("DELETE FROM clipboard_entries")
        conn.commit()
        count = cur.rowcount
        conn.close()
        return {"ok": True, "deleted": count}

    except Exception as e:
        LOG.error(f"clipboard clear_all error: {e}")
        return {"ok": False, "error": str(e)}


# ── CLI test ─────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    print("=== Clipboard Store Tests ===")

    # Clean start
    clear_all()
    print("1. Clear: OK")

    # Add entries
    r = add_entry("Hallo Welt")
    assert r["ok"], f"Add failed: {r}"
    id1 = r["id"]
    print(f"2. Add: OK (id={id1})")

    r = add_entry("Python ist toll\nZweite Zeile")
    assert r["ok"]
    id2 = r["id"]
    print(f"3. Add multiline: OK (id={id2})")

    # Duplicate detection
    r = add_entry("Hallo Welt")
    assert r["ok"] and r.get("duplicate"), f"Dedup failed: {r}"
    print("4. Duplicate detection: OK")

    # List
    r = list_entries()
    assert r["ok"] and r["count"] == 2, f"List failed: {r}"
    print(f"5. List: OK ({r['count']} entries)")

    # Search
    r = search_entries("Python")
    assert r["ok"] and r["count"] == 1, f"Search failed: {r}"
    print(f"6. Search 'Python': OK ({r['count']} found)")

    # Get
    r = get_entry(id2)
    assert r["ok"] and "Zweite Zeile" in r["entry"]["content"], f"Get failed: {r}"
    print(f"7. Get entry: OK")

    # Delete
    r = delete_entry(id2)
    assert r["ok"], f"Delete failed: {r}"
    print(f"8. Delete: OK")

    # Verify delete
    r = list_entries()
    assert r["count"] == 1, f"Post-delete count wrong: {r}"
    print(f"9. Post-delete list: OK ({r['count']} entries)")

    # Auto-prune test
    clear_all()
    for i in range(55):
        add_entry(f"Entry number {i}")
    r = list_entries(limit=100)
    assert r["count"] <= _MAX_ENTRIES, f"Prune failed: {r['count']} entries (max {_MAX_ENTRIES})"
    print(f"10. Auto-prune (55 inserts): OK ({r['count']} kept)")

    # Clear
    r = clear_all()
    assert r["ok"]
    print(f"11. Clear all: OK ({r['deleted']} deleted)")

    print("\nAll tests passed!")
