#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Encrypted Password Store for Frank.

AES-128-CBC + HMAC-SHA256 via Fernet.
Master password → PBKDF2 (600k iterations) → Fernet key.
Salt stored in DB _meta table, session key in memory only.

Database: /home/ai-core-node/aicore/database/passwords.db
"""

import base64
import hashlib
import logging
import os
import secrets
import sqlite3
import string
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

LOG = logging.getLogger("password_store")

try:
    from config.paths import get_db
    _DB_PATH = get_db("passwords")
except ImportError:
    _DB_PATH = Path.home() / ".local" / "share" / "frank" / "db" / "passwords.db"
_PBKDF2_ITERATIONS = 600_000

# Session state — NEVER persisted to disk
_session_fernet: Optional[Fernet] = None


# ── Database ──────────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS passwords (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            username   TEXT NOT NULL,
            password   TEXT NOT NULL,
            url        TEXT DEFAULT '',
            notes      TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def _derive_key(master_password: str, salt: bytes) -> bytes:
    """Derive a Fernet-compatible key from master password + salt."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(master_password.encode("utf-8")))


def _key_check_hash(key: bytes) -> str:
    """SHA-256 hash of the derived key for verification."""
    return hashlib.sha256(key).hexdigest()


# ── Encryption helpers ────────────────────────────────────────────────

def _encrypt(plaintext: str) -> str:
    """Encrypt a string with the session Fernet key."""
    if _session_fernet is None:
        raise RuntimeError("Store is locked")
    return _session_fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def _decrypt(ciphertext: str) -> str:
    """Decrypt a string with the session Fernet key."""
    if _session_fernet is None:
        raise RuntimeError("Store is locked")
    return _session_fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")


# ── Public API ────────────────────────────────────────────────────────

def is_initialized() -> bool:
    """Check if the password store has been set up with a master password."""
    if not _DB_PATH.exists():
        return False
    try:
        db = _get_db()
        row = db.execute("SELECT value FROM _meta WHERE key='salt'").fetchone()
        db.close()
        return row is not None
    except Exception:
        return False


def init_store(master_password: str) -> Dict[str, Any]:
    """Initialize the store with a new master password (first-time setup)."""
    if not master_password or len(master_password) < 4:
        return {"ok": False, "error": "Master password must be at least 4 characters"}

    if is_initialized():
        return {"ok": False, "error": "Store is already initialized. Use unlock()."}

    global _session_fernet

    salt = os.urandom(16)
    key = _derive_key(master_password, salt)
    check = _key_check_hash(key)

    db = _get_db()
    db.execute("INSERT INTO _meta (key, value) VALUES ('salt', ?)",
               (base64.b64encode(salt).decode("ascii"),))
    db.execute("INSERT INTO _meta (key, value) VALUES ('key_check', ?)", (check,))
    db.commit()
    db.close()

    _session_fernet = Fernet(key)
    LOG.info("Password store initialized")
    return {"ok": True}


def unlock(master_password: str) -> Dict[str, Any]:
    """Unlock the store with the master password."""
    global _session_fernet

    if not is_initialized():
        return {"ok": False, "error": "Store not initialized"}

    db = _get_db()
    salt_row = db.execute("SELECT value FROM _meta WHERE key='salt'").fetchone()
    check_row = db.execute("SELECT value FROM _meta WHERE key='key_check'").fetchone()
    db.close()

    if not salt_row or not check_row:
        return {"ok": False, "error": "Store metadata corrupted"}

    salt = base64.b64decode(salt_row["value"])
    key = _derive_key(master_password, salt)
    check = _key_check_hash(key)

    if check != check_row["value"]:
        return {"ok": False, "error": "Wrong master password"}

    _session_fernet = Fernet(key)
    LOG.info("Password store unlocked")
    return {"ok": True}


def is_unlocked() -> bool:
    """Check if the store is currently unlocked."""
    return _session_fernet is not None


def lock() -> Dict[str, Any]:
    """Lock the store — clear session key from memory."""
    global _session_fernet
    _session_fernet = None
    LOG.info("Password store locked")
    return {"ok": True}


def add_password(name: str, username: str, password: str,
                 url: str = "", notes: str = "") -> Dict[str, Any]:
    """Add a new password entry (encrypted)."""
    if not is_unlocked():
        return {"ok": False, "error": "Store is locked"}
    if not name or not name.strip():
        return {"ok": False, "error": "Name is required"}
    if not username:
        return {"ok": False, "error": "Username is required"}
    if not password:
        return {"ok": False, "error": "Password is required"}

    now = datetime.now().isoformat(timespec="seconds")
    try:
        db = _get_db()
        cur = db.execute(
            "INSERT INTO passwords (name, username, password, url, notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name.strip(), _encrypt(username), _encrypt(password),
             url.strip(), _encrypt(notes) if notes else "", now, now),
        )
        db.commit()
        entry_id = cur.lastrowid
        db.close()
        return {"ok": True, "id": entry_id}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def list_passwords() -> Dict[str, Any]:
    """List all entries (name + url only, NO credentials)."""
    if not is_unlocked():
        return {"ok": False, "error": "Store is locked"}

    try:
        db = _get_db()
        rows = db.execute(
            "SELECT id, name, url, created_at FROM passwords ORDER BY name"
        ).fetchall()
        db.close()
        entries = [
            {"id": r["id"], "name": r["name"], "url": r["url"],
             "created_at": r["created_at"]}
            for r in rows
        ]
        return {"ok": True, "entries": entries, "count": len(entries)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_password(entry_id: int) -> Dict[str, Any]:
    """Get a single entry with decrypted credentials."""
    if not is_unlocked():
        return {"ok": False, "error": "Store is locked"}

    try:
        db = _get_db()
        row = db.execute("SELECT * FROM passwords WHERE id=?", (entry_id,)).fetchone()
        db.close()
        if not row:
            return {"ok": False, "error": "Entry not found"}

        return {
            "ok": True,
            "entry": {
                "id": row["id"],
                "name": row["name"],
                "username": _decrypt(row["username"]),
                "password": _decrypt(row["password"]),
                "url": row["url"],
                "notes": _decrypt(row["notes"]) if row["notes"] else "",
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        }
    except InvalidToken:
        return {"ok": False, "error": "Decryption failed (wrong key?)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def search_passwords(query: str) -> Dict[str, Any]:
    """Search by name (plaintext). Returns entries WITH decrypted username."""
    if not is_unlocked():
        return {"ok": False, "error": "Store is locked"}

    try:
        db = _get_db()
        rows = db.execute(
            "SELECT id, name, username, url FROM passwords WHERE name LIKE ? ORDER BY name",
            (f"%{query}%",),
        ).fetchall()
        db.close()

        entries = []
        for r in rows:
            try:
                uname = _decrypt(r["username"])
            except Exception:
                uname = "???"
            entries.append({
                "id": r["id"],
                "name": r["name"],
                "username": uname,
                "url": r["url"],
            })
        return {"ok": True, "entries": entries, "count": len(entries)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def update_password(entry_id: int, **fields) -> Dict[str, Any]:
    """Update specific fields of an entry."""
    if not is_unlocked():
        return {"ok": False, "error": "Store is locked"}

    allowed = {"name", "username", "password", "url", "notes"}
    updates = {}
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k in ("username", "password", "notes"):
            updates[k] = _encrypt(v) if v else ""
        else:
            updates[k] = v.strip() if isinstance(v, str) else v

    if not updates:
        return {"ok": False, "error": "No valid fields"}

    updates["updated_at"] = datetime.now().isoformat(timespec="seconds")
    set_clause = ", ".join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [entry_id]

    try:
        db = _get_db()
        cur = db.execute(f"UPDATE passwords SET {set_clause} WHERE id=?", values)
        db.commit()
        db.close()
        if cur.rowcount == 0:
            return {"ok": False, "error": "Entry not found"}
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def delete_password(entry_id: int) -> Dict[str, Any]:
    """Delete a password entry."""
    if not is_unlocked():
        return {"ok": False, "error": "Store is locked"}

    try:
        db = _get_db()
        cur = db.execute("DELETE FROM passwords WHERE id=?", (entry_id,))
        db.commit()
        db.close()
        if cur.rowcount == 0:
            return {"ok": False, "error": "Entry not found"}
        return {"ok": True, "deleted_id": entry_id}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def generate_password(length: int = 16) -> str:
    """Generate a random password."""
    length = max(8, min(64, length))
    alphabet = string.ascii_letters + string.digits + "!@#$%&*+-_="
    # Ensure at least one of each category
    pw = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%&*+-_="),
    ]
    pw += [secrets.choice(alphabet) for _ in range(length - 4)]
    # Shuffle to randomize position of guaranteed chars
    result = list(pw)
    secrets.SystemRandom().shuffle(result)
    return "".join(result)


# ── Standalone Tests ──────────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile
    import shutil

    # Use temp DB for testing
    _test_dir = tempfile.mkdtemp()
    _DB_PATH = Path(_test_dir) / "test_passwords.db"

    print("=== Password Store Tests ===\n")

    # Test 1: Not initialized
    print("1. is_initialized() before init:", not is_initialized(), "✓" if not is_initialized() else "✗")

    # Test 2: Init store
    r = init_store("test-master-pw")
    print("2. init_store():", r.get("ok"), "✓" if r.get("ok") else "✗")
    print("   is_initialized():", is_initialized())
    print("   is_unlocked():", is_unlocked())

    # Test 3: Lock
    lock()
    print("3. lock(): is_unlocked():", not is_unlocked(), "✓" if not is_unlocked() else "✗")

    # Test 4: Wrong password
    r = unlock("wrong_password")
    print("4. unlock(wrong):", not r.get("ok"), "✓" if not r.get("ok") else "✗", f"({r.get('error')})")

    # Test 5: Correct password
    r = unlock("test-master-pw")
    print("5. unlock(correct):", r.get("ok"), "✓" if r.get("ok") else "✗")

    # Test 6: Add entries
    r1 = add_password("TestService1", "testuser1@example.com", "test-pw-001", url="example.com")
    r2 = add_password("TestService2", "testuser2", "test-pw-002", url="example.org", notes="2FA enabled")
    r3 = add_password("TestService3", "testuser3", "test-pw-003", url="example.net")
    print("6. add_password() x3:", all(r.get("ok") for r in [r1, r2, r3]),
          "✓" if all(r.get("ok") for r in [r1, r2, r3]) else "✗")

    # Test 7: List
    r = list_passwords()
    print("7. list_passwords():", r.get("count") == 3, "✓" if r.get("count") == 3 else "✗",
          f"(count={r.get('count')})")
    for e in r.get("entries", []):
        print(f"   - {e['name']} ({e['url']})")

    # Test 8: Get with decryption
    r = get_password(r1["id"])
    e = r.get("entry", {})
    pw_ok = e.get("password") == "test-pw-001" and e.get("username") == "testuser1@example.com"
    print("8. get_password(decrypt):", pw_ok, "✓" if pw_ok else "✗",
          f"(user={e.get('username')}, pw={'***' if e.get('password') else 'FAIL'})")

    # Test 9: Search
    r = search_passwords("Service2")
    print("9. search('Service2'):", r.get("count") == 1, "✓" if r.get("count") == 1 else "✗",
          f"(found: {[e['name'] for e in r.get('entries', [])]})")

    # Test 10: Update
    r = update_password(r2["id"], password="test-pw-002-updated")
    print("10. update_password():", r.get("ok"), "✓" if r.get("ok") else "✗")
    r = get_password(r2["id"])
    upd_ok = r.get("entry", {}).get("password") == "test-pw-002-updated"
    print("    verify updated pw:", upd_ok, "✓" if upd_ok else "✗")

    # Test 11: Delete
    r = delete_password(r3["id"])
    print("11. delete_password():", r.get("ok"), "✓" if r.get("ok") else "✗")
    r = list_passwords()
    print("    remaining:", r.get("count") == 2, "✓" if r.get("count") == 2 else "✗")

    # Test 12: Generate password
    pw = generate_password(16)
    has_upper = any(c.isupper() for c in pw)
    has_lower = any(c.islower() for c in pw)
    has_digit = any(c.isdigit() for c in pw)
    has_special = any(c in "!@#$%&*+-_=" for c in pw)
    gen_ok = len(pw) == 16 and has_upper and has_lower and has_digit and has_special
    print("12. generate_password(16):", gen_ok, "✓" if gen_ok else "✗", f"({pw})")

    # Test 13: Lock and verify operations fail
    lock()
    r = list_passwords()
    print("13. locked operations:", not r.get("ok"), "✓" if not r.get("ok") else "✗",
          f"({r.get('error')})")

    # Test 14: Re-init should fail
    r = init_store("AnotherPassword")
    print("14. re-init blocked:", not r.get("ok"), "✓" if not r.get("ok") else "✗")

    # Cleanup
    shutil.rmtree(_test_dir)
    print("\n=== All tests complete ===")
