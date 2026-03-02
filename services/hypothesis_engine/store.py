"""
Hypothesis Engine — SQLite persistence layer.

Thread-safe per-call connections, atomic budget checks.
Pattern: services/experiment_lab.py
"""

import logging
import sqlite3
import threading
import time
import uuid
from datetime import date
from typing import Any, Dict, List, Optional

from config.paths import get_db

LOG = logging.getLogger("hypothesis_engine.store")

DB_PATH = get_db("hypothesis_engine")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS hypotheses (
    id          TEXT PRIMARY KEY,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    observation TEXT NOT NULL,
    hypothesis  TEXT NOT NULL,
    prediction  TEXT NOT NULL,
    test_method TEXT DEFAULT 'passive',
    status      TEXT DEFAULT 'active',
    result      TEXT DEFAULT NULL,
    confidence      REAL DEFAULT 0.5,
    confidence_delta REAL DEFAULT NULL,
    domain      TEXT DEFAULT 'self',
    source      TEXT DEFAULT 'idle_thought',
    source_id   TEXT DEFAULT NULL,
    experiment_id       INTEGER DEFAULT NULL,
    experiment_station  TEXT DEFAULT NULL,
    experiment_pending  INTEGER DEFAULT 0,
    parent_id   TEXT DEFAULT NULL,
    child_id    TEXT DEFAULT NULL,
    revision_depth INTEGER DEFAULT 0,
    tested_at   REAL DEFAULT NULL,
    resolved_at REAL DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_h_status ON hypotheses(status);
CREATE INDEX IF NOT EXISTS idx_h_domain ON hypotheses(domain);
CREATE INDEX IF NOT EXISTS idx_h_experiment ON hypotheses(experiment_id);
CREATE INDEX IF NOT EXISTS idx_h_parent ON hypotheses(parent_id);
CREATE INDEX IF NOT EXISTS idx_h_updated ON hypotheses(updated_at);

CREATE TABLE IF NOT EXISTS hypothesis_budget (
    date    TEXT PRIMARY KEY,
    created INTEGER DEFAULT 0,
    tested  INTEGER DEFAULT 0
);
"""

# All columns in hypotheses table for row→dict conversion
_COLUMNS = [
    "id", "created_at", "updated_at", "observation", "hypothesis",
    "prediction", "test_method", "status", "result", "confidence",
    "confidence_delta", "domain", "source", "source_id",
    "experiment_id", "experiment_station", "experiment_pending",
    "parent_id", "child_id", "revision_depth", "tested_at", "resolved_at",
]


class HypothesisStore:
    """Thread-safe SQLite store for hypotheses."""

    def __init__(self):
        self._db_initialized = False
        self._db_lock = threading.Lock()

    # ── DB Access ──

    def _get_conn(self) -> sqlite3.Connection:
        """Per-call fresh connection with lazy init."""
        if not self._db_initialized:
            with self._db_lock:
                if not self._db_initialized:
                    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                    conn = sqlite3.connect(str(DB_PATH), timeout=10)
                    conn.executescript(_SCHEMA)
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.commit()
                    self._db_initialized = True
                    return conn
        return sqlite3.connect(str(DB_PATH), timeout=10)

    @staticmethod
    def _row_to_dict(row) -> dict:
        """Convert a row tuple to dict using column names."""
        return dict(zip(_COLUMNS, row))

    # ── CRUD ──

    def create(self, data: dict) -> Optional[str]:
        """Create a new hypothesis. Returns id (uuid[:8]) or None."""
        h_id = uuid.uuid4().hex[:8]
        now = time.time()
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO hypotheses "
                "(id, created_at, updated_at, observation, hypothesis, prediction, "
                "test_method, domain, source, source_id, experiment_station, "
                "parent_id, revision_depth, confidence) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    h_id, now, now,
                    data.get("observation", "")[:500],
                    data.get("hypothesis", "")[:500],
                    data.get("prediction", "")[:500],
                    data.get("test_method", "passive"),
                    data.get("domain", "self"),
                    data.get("source", "idle_thought"),
                    data.get("source_id"),
                    data.get("experiment_station"),
                    data.get("parent_id"),
                    data.get("revision_depth", 0),
                    data.get("confidence", 0.5),
                ),
            )
            conn.commit()
            return h_id
        except Exception as e:
            LOG.debug("Hypothesis create failed: %s", e)
            return None
        finally:
            conn.close()

    def get(self, hypothesis_id: str) -> Optional[dict]:
        """Fetch a single hypothesis by id."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                f"SELECT {','.join(_COLUMNS)} FROM hypotheses WHERE id = ?",
                (hypothesis_id,),
            ).fetchone()
            return self._row_to_dict(row) if row else None
        except Exception as e:
            LOG.debug("Hypothesis get failed: %s", e)
            return None
        finally:
            conn.close()

    def get_by_status(self, status: str, limit: int = 20) -> List[dict]:
        """Fetch hypotheses by status."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                f"SELECT {','.join(_COLUMNS)} FROM hypotheses "
                "WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        except Exception as e:
            LOG.debug("Hypothesis get_by_status failed: %s", e)
            return []
        finally:
            conn.close()

    def get_by_field(self, field: str, value: Any) -> List[dict]:
        """Fetch hypotheses where field equals value."""
        if field not in _COLUMNS:
            return []
        conn = self._get_conn()
        try:
            rows = conn.execute(
                f"SELECT {','.join(_COLUMNS)} FROM hypotheses "
                f"WHERE {field} = ? ORDER BY updated_at DESC LIMIT 20",
                (value,),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        except Exception as e:
            LOG.debug("Hypothesis get_by_field failed: %s", e)
            return []
        finally:
            conn.close()

    def get_testable_untested(self, limit: int = 3) -> List[dict]:
        """Active hypotheses with experiment test method, not yet pending."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                f"SELECT {','.join(_COLUMNS)} FROM hypotheses "
                "WHERE status = 'active' "
                "AND test_method IN ('experiment', 'both') "
                "AND experiment_pending = 0 "
                "AND experiment_id IS NULL "
                "ORDER BY created_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        except Exception as e:
            LOG.debug("Hypothesis get_testable_untested failed: %s", e)
            return []
        finally:
            conn.close()

    def update(self, hypothesis_id: str, fields: dict) -> bool:
        """Update arbitrary fields on a hypothesis. Always sets updated_at."""
        allowed = set(_COLUMNS) - {"id", "created_at"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        updates["updated_at"] = time.time()

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [hypothesis_id]

        conn = self._get_conn()
        try:
            conn.execute(
                f"UPDATE hypotheses SET {set_clause} WHERE id = ?",
                values,
            )
            conn.commit()
            return True
        except Exception as e:
            LOG.debug("Hypothesis update failed: %s", e)
            return False
        finally:
            conn.close()

    # ── Budget ──

    def check_and_increment_budget(self, budget_type: str, max_count: int) -> bool:
        """Atomically check and increment daily budget. Returns True if allowed."""
        if budget_type not in ("created", "tested"):
            LOG.warning("Invalid budget_type: %s", budget_type)
            return False
        today = date.today().isoformat()
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO hypothesis_budget (date, created, tested) "
                "VALUES (?, 0, 0) ON CONFLICT(date) DO NOTHING",
                (today,),
            )
            cursor = conn.execute(
                f"UPDATE hypothesis_budget SET {budget_type} = {budget_type} + 1 "
                "WHERE date = ? AND " + budget_type + " < ?",
                (today, max_count),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            LOG.debug("Budget check failed: %s", e)
            return True  # fail-open
        finally:
            conn.close()

    def get_budget(self, today: str = None) -> dict:
        """Get current day's budget usage."""
        if today is None:
            today = date.today().isoformat()
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT created, tested FROM hypothesis_budget WHERE date = ?",
                (today,),
            ).fetchone()
            return {"created": row[0], "tested": row[1]} if row else {"created": 0, "tested": 0}
        except Exception:
            return {"created": 0, "tested": 0}
        finally:
            conn.close()

    # ── Stats ──

    def get_stats(self) -> dict:
        """Return counts by status, accuracy, domains."""
        conn = self._get_conn()
        try:
            stats = {}
            # Status counts
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM hypotheses GROUP BY status"
            ).fetchall()
            for status, count in rows:
                stats[f"{status}_count"] = count
            stats["total"] = sum(c for _, c in rows)
            stats["active_count"] = stats.get("active_count", 0)

            # Prediction accuracy (confirmed / (confirmed + refuted))
            confirmed = stats.get("confirmed_count", 0)
            refuted = stats.get("refuted_count", 0)
            total_resolved = confirmed + refuted
            if total_resolved > 0:
                stats["prediction_accuracy"] = confirmed / total_resolved
            else:
                stats["prediction_accuracy"] = None

            # Experiment-tested count
            row = conn.execute(
                "SELECT COUNT(*) FROM hypotheses WHERE experiment_id IS NOT NULL"
            ).fetchone()
            stats["experiment_tested"] = row[0] if row else 0

            # Today's budget
            stats["budget"] = self.get_budget()

            return stats
        except Exception as e:
            LOG.debug("Stats failed: %s", e)
            return {"total": 0, "active_count": 0}
        finally:
            conn.close()

    # ── Cleanup ──

    def archive_old(self, max_age_days: int = 30):
        """Archive active hypotheses older than max_age_days."""
        cutoff = time.time() - (max_age_days * 86400)
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE hypotheses SET status = 'archived', updated_at = ? "
                "WHERE status = 'active' AND created_at < ?",
                (time.time(), cutoff),
            )
            conn.commit()
        except Exception as e:
            LOG.debug("Archive old failed: %s", e)
        finally:
            conn.close()

    def enforce_active_limit(self, max_active: int = 20):
        """Archive oldest active hypotheses if over limit."""
        conn = self._get_conn()
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM hypotheses WHERE status = 'active'"
            ).fetchone()[0]
            if count > max_active:
                excess = count - max_active
                conn.execute(
                    "UPDATE hypotheses SET status = 'archived', updated_at = ? "
                    "WHERE id IN ("
                    "  SELECT id FROM hypotheses WHERE status = 'active' "
                    "  ORDER BY created_at ASC LIMIT ?"
                    ")",
                    (time.time(), excess),
                )
                conn.commit()
        except Exception as e:
            LOG.debug("Enforce active limit failed: %s", e)
        finally:
            conn.close()

    def count_active_by_domain(self, domain: str) -> int:
        """Count active hypotheses in a specific domain."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM hypotheses "
                "WHERE status = 'active' AND domain = ?",
                (domain,),
            ).fetchone()
            return row[0] if row else 0
        except Exception:
            return 0
        finally:
            conn.close()
