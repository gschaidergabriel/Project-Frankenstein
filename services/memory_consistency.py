"""
Memory Consistency Daemon — Nightly cross-layer integrity checks.

Runs periodically (integrated into persistence_mixin timer) to ensure
all memory layers are consistent and healthy.

Checks:
  1. Titan orphans (edges without nodes) → auto-delete
  2. Embedding gaps (messages without embeddings) → backfill
  3. Old retrieval metrics → prune (>30 days)
  4. Health report logging
"""

import json
import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path

LOG = logging.getLogger("memory_consistency")


class MemoryConsistencyDaemon:
    """Cross-layer memory integrity checker."""

    def __init__(self):
        self._last_run = 0
        self._interval = 86400  # 24 hours

    def should_run(self) -> bool:
        return (time.time() - self._last_run) > self._interval

    def run_nightly(self) -> dict:
        """Run all consistency checks. Returns health report."""
        start = time.time()
        report = {
            "timestamp": datetime.now().isoformat(),
            "checks": {},
        }

        # 1. Titan orphan check
        report["checks"]["titan_orphans"] = self._check_titan_orphans()

        # 2. Embedding gap check
        report["checks"]["embedding_gaps"] = self._check_embedding_gaps()

        # 3. Prune old metrics
        report["checks"]["metrics_pruned"] = self._prune_old_metrics()

        # 4. DB stats
        report["checks"]["db_stats"] = self._collect_stats()

        report["duration_ms"] = int((time.time() - start) * 1000)
        self._last_run = time.time()

        LOG.info("Consistency check complete: %s", json.dumps(report, indent=2))
        return report

    def _check_titan_orphans(self) -> dict:
        """Find and remove orphaned edges in Titan."""
        result = {"orphaned_edges": 0, "fixed": False}
        try:
            from config.paths import get_db
            titan_db = get_db("titan")
            if not titan_db.exists():
                return result

            conn = sqlite3.connect(str(titan_db), timeout=30)
            # Count orphaned edges
            count = conn.execute("""
                SELECT COUNT(*) FROM edges
                WHERE src NOT IN (SELECT id FROM nodes)
                   OR dst NOT IN (SELECT id FROM nodes)
            """).fetchone()[0]

            if count > 0:
                conn.execute("""
                    DELETE FROM edges
                    WHERE src NOT IN (SELECT id FROM nodes)
                       OR dst NOT IN (SELECT id FROM nodes)
                """)
                conn.commit()
                result["orphaned_edges"] = count
                result["fixed"] = True
                LOG.info("Titan: removed %d orphaned edges", count)

            conn.close()
        except Exception as e:
            result["error"] = str(e)
            LOG.debug("Titan orphan check failed: %s", e)

        return result

    def _check_embedding_gaps(self) -> dict:
        """Check for messages without embeddings and trigger backfill."""
        result = {"missing": 0, "backfilled": 0}
        try:
            from services.chat_memory import ChatMemoryDB
            db = ChatMemoryDB()
            conn = db._conn

            missing = conn.execute("""
                SELECT COUNT(*) FROM messages m
                LEFT JOIN message_embeddings me ON me.message_id = m.id
                WHERE me.message_id IS NULL
                  AND m.is_system = 0
                  AND m.text != '[archived]'
            """).fetchone()[0]

            result["missing"] = missing
            if missing > 0:
                done = db.backfill_embeddings(batch_size=64, max_seconds=30)
                result["backfilled"] = done
                LOG.info("Embedding backfill: %d/%d gaps filled", done, missing)
        except Exception as e:
            result["error"] = str(e)
            LOG.debug("Embedding gap check failed: %s", e)

        return result

    def _prune_old_metrics(self, days: int = 30) -> dict:
        """Delete retrieval metrics older than N days."""
        result = {"pruned": 0}
        try:
            from services.chat_memory import ChatMemoryDB
            db = ChatMemoryDB()
            cutoff = time.time() - (days * 86400)
            with db._lock:
                cur = db._conn.execute(
                    "DELETE FROM retrieval_metrics WHERE timestamp < ?",
                    (cutoff,),
                )
                db._conn.commit()
                result["pruned"] = cur.rowcount
        except Exception as e:
            result["error"] = str(e)

        return result

    def _collect_stats(self) -> dict:
        """Collect cross-layer statistics."""
        stats = {}

        # Chat memory
        try:
            from services.chat_memory import ChatMemoryDB
            db = ChatMemoryDB()
            stats["chat"] = db.get_stats()
            embeddings = db._conn.execute(
                "SELECT COUNT(*) FROM message_embeddings"
            ).fetchone()[0]
            stats["chat"]["embeddings"] = embeddings
            prefs = db._conn.execute(
                "SELECT COUNT(*) FROM user_preferences"
            ).fetchone()[0]
            stats["chat"]["preferences"] = prefs
        except Exception:
            pass

        # Titan
        try:
            from config.paths import get_db
            titan_db = get_db("titan")
            if titan_db.exists():
                conn = sqlite3.connect(str(titan_db), timeout=30)
                stats["titan"] = {
                    "nodes": conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
                    "edges": conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
                }
                conn.close()
        except Exception:
            pass

        return stats


# Singleton
_daemon = None


def get_consistency_daemon() -> MemoryConsistencyDaemon:
    global _daemon
    if _daemon is None:
        _daemon = MemoryConsistencyDaemon()
    return _daemon
