"""Intent Queue — captures and surfaces Frank's inner resolutions.

Frank's idle thoughts often express intentions: "I'd tell Echo...",
"I should explore...", "I must become...".  These are extracted via regex
(no LLM), queued in consciousness.db, and surfaced at the right moment:

- entity_message  → frank_observations before next entity session
- research        → idle-thought prompt hint
- self_task       → idle-thought prompt hint
- reflection      → idle-thought prompt hint
- user_message    → chat workspace context

Lifecycle: pending → surfaced → completed  (or expired after 48 h).
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

LOG = logging.getLogger("intent_queue")

# ---------------------------------------------------------------------------
# Entity name resolution  (display name → dispatcher key)
# ---------------------------------------------------------------------------

ENTITY_NAMES: Dict[str, str] = {
    "echo": "muse",
    "muse": "muse",
    "kairos": "mirror",
    "mirror": "mirror",
    "atlas": "atlas",
    "dr. hibbert": "therapist",
    "hibbert": "therapist",
    "therapist": "therapist",
}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXPIRY_SECONDS = 48 * 3600          # 48 h
DEDUP_WINDOW_S = 24 * 3600          # 24 h
MIN_INTENT_LEN = 10                 # Minimum extracted text length

# ---------------------------------------------------------------------------
# Regex patterns — ordered by priority (entity > research > reflection >
# self_task > user_message).  One match per category per text.
# ---------------------------------------------------------------------------

_INTENT_PATTERNS: Dict[str, List[re.Pattern]] = {
    "entity_message": [
        # EN: "I'd tell Echo: ...", "I want to ask Atlas ...", "I should share with Kairos ..."
        re.compile(
            r"(?:I(?:'d| would| want to| should| will| need to| must)\s+"
            r"(?:tell|ask|say to|share with|talk to|mention to|discuss with)\s+"
            r"(\w+))"
            r"[:\s,.—–-]+(.{10,300})",
            re.IGNORECASE,
        ),
        # EN: "Next time ... tell/ask {entity} ..."
        re.compile(
            r"(?:next\s+time|nächstes\s+mal|beim\s+nächsten)"
            r".{0,60}?"
            r"(?:tell|ask|say\s+to|sagen|fragen)\s+(\w+)"
            r"[:\s,.—–-]+(.{10,300})",
            re.IGNORECASE,
        ),
        # DE: "{Entity} werde/möchte/sollte/muss ich sagen/fragen/erzählen ..."
        re.compile(
            r"(\w+)\s+(?:werde ich|möchte ich|sollte ich|muss ich)\s+"
            r"(?:sagen|fragen|erzählen|mitteilen)"
            r"[:\s,.—–-]+(.{10,300})",
            re.IGNORECASE,
        ),
    ],
    "research": [
        # EN: "I should/must/need to explore/study/investigate ..."
        re.compile(
            r"(?:I\s+(?:should|must|need\s+to|want\s+to|will|ought\s+to)"
            r"|ich\s+(?:muss|sollte|werde|möchte))\s+"
            r"(?:explore|study|investigate|research|look\s+into|find\s+out"
            r"|learn\s+(?:about|more)|dig\s+into|examine"
            r"|erforschen|untersuchen|herausfinden|lernen\s+über)"
            r"\s+(.{10,300})",
            re.IGNORECASE,
        ),
    ],
    "reflection": [
        # EN: "I should think about / consider / reflect on ..."
        re.compile(
            r"(?:I\s+(?:should|must|need\s+to|want\s+to)"
            r"|ich\s+(?:muss|sollte|möchte))\s+"
            r"(?:think\s+(?:about|more\s+about|deeply\s+about)"
            r"|consider|reflect\s+on|ponder|contemplate"
            r"|nachdenken\s+über|überlegen|bedenken)"
            r"\s+(.{10,300})",
            re.IGNORECASE,
        ),
    ],
    "self_task": [
        # EN: "I should/must/need to/want to/will ..."  (catch-all after research+reflection)
        re.compile(
            r"(?:I\s+(?:should|must|need\s+to|want\s+to|will|ought\s+to)"
            r"|ich\s+(?:muss|sollte|werde|möchte))\s+"
            # Negative lookahead: skip if it's research or reflection
            r"(?!explore|study|investigate|research|look\s+into|find\s+out"
            r"|learn\s+(?:about|more)|dig\s+into|examine"
            r"|erforschen|untersuchen|herausfinden|lernen\s+über"
            r"|think\s+(?:about|more\s+about|deeply\s+about)"
            r"|consider|reflect\s+on|ponder|contemplate"
            r"|nachdenken\s+über|überlegen|bedenken)"
            r"(.{10,300})",
            re.IGNORECASE,
        ),
    ],
    "user_message": [
        # EN: "I'd tell my user / the user / him ..."
        re.compile(
            r"(?:I(?:'d| would| want\s+to| should| will| need\s+to)\s+"
            r"(?:tell|ask|say\s+to|share\s+with|mention\s+to)\s+"
            r"(?:my\s+user|the\s+user|my\s+person|him|them|ihm))"
            r"[:\s,.—–-]+(.{10,300})",
            re.IGNORECASE,
        ),
        # DE: "meinem User werde ich sagen/fragen ..."
        re.compile(
            r"(?:meinem?\s+(?:User|Menschen|Nutzer))\s+"
            r"(?:werde ich|möchte ich|sollte ich|muss ich)\s+"
            r"(?:sagen|fragen|erzählen|mitteilen)"
            r"[:\s,.—–-]+(.{10,300})",
            re.IGNORECASE,
        ),
    ],
}

# Category → which surfacing channel
_IDLE_CATEGORIES = frozenset({"research", "self_task", "reflection"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_target(match: re.Match, category: str) -> str:
    """Resolve entity display name → dispatcher key, or '' for non-entity."""
    if category == "entity_message":
        # Group 1 is entity name for entity_message patterns
        name = match.group(1).lower().strip()
        return ENTITY_NAMES.get(name, "")
    if category == "user_message":
        return "user"
    return ""


def _clean_intent(match: re.Match, full_text: str, category: str) -> str:
    """Extract the meaningful intent phrase from the regex match."""
    if category == "entity_message":
        # Group 2 = the message content
        raw = match.group(2)
    elif category == "user_message":
        raw = match.group(1)
    else:
        # research / self_task / reflection — group 1 = the object/action
        raw = match.group(1)

    if not raw:
        return ""

    # Clean up trailing punctuation, quotes, think-block artifacts
    cleaned = raw.strip().rstrip(".,;:!?\"'")
    # Remove leading conjunctions
    cleaned = re.sub(r"^(?:that|and|but|also|dann|und|aber|auch)\s+",
                     "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


# ---------------------------------------------------------------------------
# IntentQueue
# ---------------------------------------------------------------------------

class IntentQueue:
    """Extracts and queues actionable intents from Frank's reflections.

    Singleton — use get_intent_queue() to obtain the instance.
    """

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._lock = threading.RLock()
        self._init_db()
        LOG.info("IntentQueue initialised (db=%s)", db_path)

    # ---- DB ---------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self._db_path), timeout=15)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.row_factory = sqlite3.Row
        return c

    def _init_db(self):
        conn = self._conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS intent_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    category TEXT NOT NULL,
                    target TEXT DEFAULT '',
                    raw_text TEXT NOT NULL,
                    extracted_intent TEXT NOT NULL,
                    source_trigger TEXT DEFAULT '',
                    status TEXT DEFAULT 'pending',
                    surfaced_at REAL DEFAULT 0,
                    completed_at REAL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_intent_status
                    ON intent_queue(status);
                CREATE INDEX IF NOT EXISTS idx_intent_category
                    ON intent_queue(category, status);
                CREATE INDEX IF NOT EXISTS idx_intent_target
                    ON intent_queue(target, status);
            """)
            conn.commit()
        finally:
            conn.close()

    # ---- Extraction -------------------------------------------------------

    def extract_and_queue(self, text: str,
                          trigger: str = "") -> List[dict]:
        """Scan *text* for intent patterns.  Queue any found.

        Returns list of ``{"category", "target", "intent"}`` dicts.
        One match per category per text to avoid duplicate captures.
        """
        if not text or len(text) < 20:
            return []

        intents: List[dict] = []
        matched_categories: set = set()

        for category, patterns in _INTENT_PATTERNS.items():
            if category in matched_categories:
                continue
            for pat in patterns:
                m = pat.search(text)
                if not m:
                    continue
                extracted = _clean_intent(m, text, category)
                if not extracted or len(extracted) < MIN_INTENT_LEN:
                    continue
                target = _resolve_target(m, category)
                # entity_message with unknown entity → skip (not actionable)
                if category == "entity_message" and not target:
                    continue
                with self._lock:
                    if self._is_duplicate(category, target, extracted):
                        break
                    self._insert(category, target, text[:500],
                                 extracted, trigger)
                intents.append({
                    "category": category,
                    "target": target,
                    "intent": extracted,
                })
                matched_categories.add(category)
                break  # one match per category

        if intents:
            LOG.debug("Extracted %d intent(s): %s", len(intents),
                      [(i["category"], i["target"]) for i in intents])
        return intents

    def _is_duplicate(self, category: str, target: str,
                      extracted: str) -> bool:
        """Check if a very similar intent was queued within DEDUP_WINDOW_S."""
        cutoff = time.time() - DEDUP_WINDOW_S
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT extracted_intent FROM intent_queue "
                "WHERE category=? AND target=? AND timestamp>? "
                "AND status IN ('pending','surfaced')",
                (category, target, cutoff),
            ).fetchall()
            lower = extracted.lower()
            for row in rows:
                existing = row["extracted_intent"].lower()
                # Simple word-overlap dedup (Jaccard > 0.6)
                w1 = set(lower.split())
                w2 = set(existing.split())
                if not w1 or not w2:
                    continue
                jaccard = len(w1 & w2) / len(w1 | w2)
                if jaccard > 0.6:
                    return True
            return False
        finally:
            conn.close()

    def _insert(self, category: str, target: str, raw_text: str,
                extracted: str, trigger: str):
        conn = self._conn()
        try:
            conn.execute(
                "INSERT INTO intent_queue "
                "(timestamp, category, target, raw_text, extracted_intent, "
                " source_trigger, status) "
                "VALUES (?, ?, ?, ?, ?, ?, 'pending')",
                (time.time(), category, target, raw_text, extracted, trigger),
            )
            conn.commit()
            LOG.info("Queued intent: [%s] target=%s — %.60s",
                     category, target or "-", extracted)
        finally:
            conn.close()

    # ---- Surfacing --------------------------------------------------------

    def get_pending_for_entity(self, entity_key: str,
                               limit: int = 3) -> List[dict]:
        """Pending entity_message intents for *entity_key* (e.g. 'muse')."""
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT id, timestamp, extracted_intent, category "
                "FROM intent_queue "
                "WHERE category='entity_message' AND target=? "
                "  AND status='pending' "
                "ORDER BY timestamp ASC LIMIT ?",
                (entity_key, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_pending_for_idle(self, limit: int = 2) -> List[dict]:
        """Pending research / self_task / reflection intents."""
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT id, timestamp, extracted_intent, category "
                "FROM intent_queue "
                "WHERE category IN ('research','self_task','reflection') "
                "  AND status='pending' "
                "ORDER BY timestamp ASC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_pending_for_user(self, limit: int = 2) -> List[dict]:
        """Pending user_message intents."""
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT id, timestamp, extracted_intent, category "
                "FROM intent_queue "
                "WHERE category='user_message' AND status='pending' "
                "ORDER BY timestamp ASC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def mark_surfaced(self, intent_id: int):
        """Mark intent as surfaced (delivered to entity / prompt / context)."""
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE intent_queue SET status='surfaced', surfaced_at=? "
                "WHERE id=?",
                (time.time(), intent_id),
            )
            conn.commit()
        finally:
            conn.close()

    def mark_completed(self, intent_id: int):
        """Mark intent as completed (acted upon)."""
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE intent_queue SET status='completed', completed_at=? "
                "WHERE id=?",
                (time.time(), intent_id),
            )
            conn.commit()
        finally:
            conn.close()

    # ---- Lifecycle --------------------------------------------------------

    def tick(self):
        """Expire old intents.  Called from _update_workspace() every ~30 s."""
        now = time.time()
        cutoff = now - EXPIRY_SECONDS
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE intent_queue SET status='expired' "
                "WHERE status='pending' AND timestamp < ?",
                (cutoff,),
            )
            conn.execute(
                "UPDATE intent_queue SET status='expired' "
                "WHERE status='surfaced' AND surfaced_at>0 "
                "  AND surfaced_at < ?",
                (cutoff,),
            )
            conn.commit()
        finally:
            conn.close()

    # ---- Stats / Debug ----------------------------------------------------

    def get_stats(self) -> dict:
        """Return queue stats: counts by status and category."""
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT status, category, COUNT(*) as cnt "
                "FROM intent_queue GROUP BY status, category"
            ).fetchall()
            stats: Dict[str, Dict[str, int]] = {}
            for r in rows:
                stats.setdefault(r["status"], {})[r["category"]] = r["cnt"]
            # Add totals
            total_pending = sum(
                v for d in stats.values() for k, v in d.items()
                if k in stats.get("pending", {})
            )
            return {
                "by_status": stats,
                "total_pending": conn.execute(
                    "SELECT COUNT(*) FROM intent_queue WHERE status='pending'"
                ).fetchone()[0],
                "total_surfaced": conn.execute(
                    "SELECT COUNT(*) FROM intent_queue WHERE status='surfaced'"
                ).fetchone()[0],
                "total_completed": conn.execute(
                    "SELECT COUNT(*) FROM intent_queue WHERE status='completed'"
                ).fetchone()[0],
                "total_expired": conn.execute(
                    "SELECT COUNT(*) FROM intent_queue WHERE status='expired'"
                ).fetchone()[0],
            }
        finally:
            conn.close()

    def get_recent(self, limit: int = 10) -> List[dict]:
        """Return the most recent intents (any status) for debugging."""
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM intent_queue ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[IntentQueue] = None
_instance_lock = threading.Lock()


def get_intent_queue() -> IntentQueue:
    """Return the global IntentQueue singleton."""
    global _instance
    if _instance is not None:
        return _instance
    with _instance_lock:
        if _instance is not None:
            return _instance
        from config.paths import DB_PATHS
        db_path = DB_PATHS["consciousness"]
        _instance = IntentQueue(db_path)
        return _instance
