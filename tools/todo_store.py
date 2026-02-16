#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
todo_store.py – Persistent todo/task list for Frank.

SQLite-backed task storage with FTS5 full-text search.
Supports status tracking (pending/completed) and optional due dates.
Stdlib only – no external dependencies.

Database: /home/ai-core-node/aicore/database/todos.db
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

LOG = logging.getLogger("todo_store")

# ── Configuration ─────────────────────────────────────────────────

try:
    from config.paths import get_db
    _DB_PATH = get_db("todos")
except ImportError:
    _DB_PATH = Path("/home/ai-core-node/aicore/database/todos.db")
_MAX_TODO_LENGTH = 2000
_MAX_TODOS = 500


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
        CREATE TABLE IF NOT EXISTS todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            due_date TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        )
    """)

    # Create FTS5 virtual table for full-text search
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS todos_fts
        USING fts5(content, content=todos, content_rowid=id)
    """)

    # Triggers to keep FTS in sync
    conn.executescript("""
        CREATE TRIGGER IF NOT EXISTS todos_ai AFTER INSERT ON todos BEGIN
            INSERT INTO todos_fts(rowid, content)
            VALUES (new.id, new.content);
        END;

        CREATE TRIGGER IF NOT EXISTS todos_ad AFTER DELETE ON todos BEGIN
            INSERT INTO todos_fts(todos_fts, rowid, content)
            VALUES ('delete', old.id, old.content);
        END;

        CREATE TRIGGER IF NOT EXISTS todos_au AFTER UPDATE ON todos BEGIN
            INSERT INTO todos_fts(todos_fts, rowid, content)
            VALUES ('delete', old.id, old.content);
            INSERT INTO todos_fts(rowid, content)
            VALUES (new.id, new.content);
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
    """Sanitize todo text against prompt injection."""
    if not text:
        return ""
    text = _INJECTION_PATTERNS.sub("[FILTERED]", text)
    return text[:_MAX_TODO_LENGTH]


# ── Public API ────────────────────────────────────────────────────

def create_todo(content: str, due_date: Optional[str] = None) -> Dict[str, Any]:
    """Create a new todo item."""
    if not content or not content.strip():
        return {"error": "No content provided"}

    content = content.strip()[:_MAX_TODO_LENGTH]
    now = datetime.now().isoformat(timespec="seconds")

    try:
        conn = _get_db()

        # Check todo count limit
        count = conn.execute("SELECT COUNT(*) FROM todos").fetchone()[0]
        if count >= _MAX_TODOS:
            conn.close()
            return {"error": f"Todo limit reached ({_MAX_TODOS}). Please delete old tasks."}

        cur = conn.execute(
            "INSERT INTO todos (content, status, due_date, created_at, updated_at) VALUES (?, 'pending', ?, ?, ?)",
            (content, due_date, now, now),
        )
        todo_id = cur.lastrowid
        conn.commit()
        conn.close()

        LOG.info(f"Todo created: id={todo_id}, due={due_date}")
        return {"ok": True, "id": todo_id, "content": content, "due_date": due_date, "created_at": now}

    except Exception as e:
        return {"error": f"Todo error: {e}"}


def list_todos(status: str = "pending", limit: int = 20) -> Dict[str, Any]:
    """List todos filtered by status (newest first)."""
    limit = max(1, min(limit, 100))
    if status not in ("pending", "completed", "all"):
        status = "pending"

    try:
        conn = _get_db()

        if status == "all":
            rows = conn.execute(
                "SELECT id, content, status, due_date, created_at, updated_at, completed_at "
                "FROM todos ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, content, status, due_date, created_at, updated_at, completed_at "
                "FROM todos WHERE status = ? ORDER BY "
                "CASE WHEN due_date IS NOT NULL THEN due_date ELSE created_at END ASC LIMIT ?",
                (status, limit),
            ).fetchall()

        conn.close()

        todos = []
        for r in rows:
            todos.append({
                "id": r["id"],
                "content": _sanitize(r["content"]),
                "status": r["status"],
                "due_date": r["due_date"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "completed_at": r["completed_at"],
            })

        return {"ok": True, "todos": todos, "count": len(todos)}

    except Exception as e:
        return {"error": f"Todo error: {e}"}


def search_todos(query: str) -> Dict[str, Any]:
    """Full-text search in todos."""
    if not query or not query.strip():
        return {"error": "No search term provided"}

    query = query.strip()

    try:
        conn = _get_db()

        # FTS5 search
        rows = conn.execute(
            """SELECT t.id, t.content, t.status, t.due_date, t.created_at, t.updated_at, t.completed_at
               FROM todos_fts f
               JOIN todos t ON t.id = f.rowid
               WHERE todos_fts MATCH ?
               ORDER BY rank
               LIMIT 20""",
            (query,),
        ).fetchall()

        # Fallback to LIKE
        if not rows:
            like_q = f"%{query}%"
            rows = conn.execute(
                """SELECT id, content, status, due_date, created_at, updated_at, completed_at
                   FROM todos WHERE content LIKE ?
                   ORDER BY created_at DESC LIMIT 20""",
                (like_q,),
            ).fetchall()

        conn.close()

        todos = []
        for r in rows:
            todos.append({
                "id": r["id"],
                "content": _sanitize(r["content"]),
                "status": r["status"],
                "due_date": r["due_date"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "completed_at": r["completed_at"],
            })

        return {"ok": True, "todos": todos, "count": len(todos), "query": query}

    except Exception as e:
        return {"error": f"Search error: {e}"}


def complete_todo(todo_id: int) -> Dict[str, Any]:
    """Mark a todo as completed."""
    if not todo_id:
        return {"error": "No todo ID provided"}

    try:
        conn = _get_db()
        row = conn.execute("SELECT id, content, status FROM todos WHERE id = ?", (int(todo_id),)).fetchone()
        if not row:
            conn.close()
            return {"error": "Task not found"}

        if row["status"] == "completed":
            conn.close()
            return {"ok": True, "id": int(todo_id), "already_completed": True}

        now = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            "UPDATE todos SET status = 'completed', completed_at = ?, updated_at = ? WHERE id = ?",
            (now, now, int(todo_id)),
        )
        conn.commit()
        conn.close()

        LOG.info(f"Todo completed: id={todo_id}")
        return {"ok": True, "id": int(todo_id), "content": row["content"], "completed_at": now}

    except Exception as e:
        return {"error": f"Todo error: {e}"}


def delete_todo(todo_id: int) -> Dict[str, Any]:
    """Delete a todo by ID."""
    if not todo_id:
        return {"error": "No todo ID provided"}

    try:
        conn = _get_db()
        cur = conn.execute("DELETE FROM todos WHERE id = ?", (int(todo_id),))
        conn.commit()
        conn.close()

        if cur.rowcount == 0:
            return {"error": "Task not found"}

        LOG.info(f"Todo deleted: id={todo_id}")
        return {"ok": True, "deleted": int(todo_id)}

    except Exception as e:
        return {"error": f"Delete error: {e}"}


def get_due_todos(within_minutes: int = 15) -> Dict[str, Any]:
    """Get pending todos that are due within the next N minutes."""
    try:
        conn = _get_db()
        now = datetime.now()
        end = now + timedelta(minutes=within_minutes)

        rows = conn.execute(
            """SELECT id, content, status, due_date, created_at
               FROM todos
               WHERE status = 'pending'
                 AND due_date IS NOT NULL
                 AND due_date <= ?
               ORDER BY due_date ASC""",
            (end.isoformat(timespec="seconds"),),
        ).fetchall()
        conn.close()

        todos = []
        for r in rows:
            todos.append({
                "id": r["id"],
                "content": _sanitize(r["content"]),
                "due_date": r["due_date"],
                "created_at": r["created_at"],
            })

        return {"ok": True, "todos": todos, "count": len(todos)}

    except Exception as e:
        return {"error": f"Due check error: {e}"}


# ── CLI test ──────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=== Todo Store Test ===\n")

    # Test 1: Create without due date
    print("--- Create (no date) ---")
    r = create_todo("Einkaufen gehen")
    print(f"  Created: {r}")
    id1 = r.get("id")

    # Test 2: Create with due date
    print("\n--- Create (with date) ---")
    tomorrow = (datetime.now() + timedelta(days=1)).replace(hour=14, minute=0, second=0)
    r2 = create_todo("Zahnarzt Termin", due_date=tomorrow.isoformat(timespec="seconds"))
    print(f"  Created: {r2}")
    id2 = r2.get("id")

    # Test 3: List pending
    print("\n--- List (pending) ---")
    result = list_todos()
    if result.get("ok"):
        for t in result["todos"]:
            due = f" [due: {t['due_date'][:16]}]" if t["due_date"] else ""
            print(f"  [{t['id']}] {t['content'][:50]}{due} ({t['status']})")
        print(f"  Total: {result['count']}")

    # Test 4: Complete
    if id1:
        print(f"\n--- Complete #{id1} ---")
        r = complete_todo(id1)
        print(f"  Result: {r}")

    # Test 5: List pending again (should only show Zahnarzt)
    print("\n--- List (pending after complete) ---")
    result = list_todos(status="pending")
    if result.get("ok"):
        for t in result["todos"]:
            print(f"  [{t['id']}] {t['content'][:50]} ({t['status']})")
        print(f"  Pending: {result['count']}")

    # Test 6: Search
    print("\n--- Search 'Zahnarzt' ---")
    result = search_todos("Zahnarzt")
    if result.get("ok"):
        print(f"  Found: {result['count']}")
        for t in result["todos"]:
            print(f"  [{t['id']}] {t['content'][:50]}")

    # Test 7: Due check
    print("\n--- Due todos (next 24h) ---")
    result = get_due_todos(within_minutes=1440)
    if result.get("ok"):
        print(f"  Due: {result['count']}")
        for t in result["todos"]:
            print(f"  [{t['id']}] {t['content'][:50]} due={t['due_date']}")

    # Test 8: Delete all
    print("\n--- Cleanup ---")
    for t in list_todos(status="all").get("todos", []):
        dr = delete_todo(t["id"])
        print(f"  Deleted [{t['id']}]: {dr.get('ok', False)}")

    result = list_todos(status="all")
    print(f"  Remaining: {result.get('count', '?')}")

    print("\n=== Test Complete ===")
