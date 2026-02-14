#!/usr/bin/env python3
"""
Invariants Database Schema
==========================

Database schema for tracking invariant state, violations,
quarantine, and convergence history.

This database is SEPARATE from Frank's knowledge databases.
Frank cannot access or query this database.
"""

import sqlite3
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from .config import INVARIANTS_DB, get_config

LOG = logging.getLogger("invariants.db")

SCHEMA = """
-- Invariant state tracking
CREATE TABLE IF NOT EXISTS invariant_state (
    id INTEGER PRIMARY KEY,
    invariant_name TEXT UNIQUE NOT NULL,
    current_value REAL NOT NULL,
    threshold REAL,
    last_check TEXT NOT NULL,
    status TEXT DEFAULT 'normal',  -- normal, warning, critical, violated
    violation_count INTEGER DEFAULT 0
);

-- Energy conservation tracking
CREATE TABLE IF NOT EXISTS energy_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    total_energy REAL NOT NULL,
    expected_energy REAL NOT NULL,
    delta REAL NOT NULL,
    transaction_type TEXT,  -- write, delete, update
    transaction_id TEXT,
    rolled_back INTEGER DEFAULT 0
);

-- Entropy measurements
CREATE TABLE IF NOT EXISTS entropy_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    entropy_value REAL NOT NULL,
    entropy_max REAL NOT NULL,
    ratio REAL NOT NULL,
    consolidation_triggered INTEGER DEFAULT 0,
    consolidation_type TEXT  -- soft, hard, none
);

-- Core kernel tracking (K_core)
CREATE TABLE IF NOT EXISTS core_kernel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    knowledge_id TEXT UNIQUE NOT NULL,
    added_at TEXT NOT NULL,
    energy REAL NOT NULL,
    connections INTEGER NOT NULL,
    consistency_score REAL NOT NULL,
    protected INTEGER DEFAULT 1
);

-- Quarantine dimension
CREATE TABLE IF NOT EXISTS quarantine (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    knowledge_id TEXT NOT NULL,
    original_data TEXT NOT NULL,  -- JSON serialized
    quarantine_reason TEXT NOT NULL,
    quarantined_at TEXT NOT NULL,
    divergence_count INTEGER DEFAULT 1,
    region_id TEXT,  -- Identifies unstable region
    reviewed INTEGER DEFAULT 0,
    review_result TEXT  -- keep_quarantined, restore, delete
);

-- Reality divergence tracking
CREATE TABLE IF NOT EXISTS divergence_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    region_id TEXT NOT NULL,
    primary_hash TEXT NOT NULL,
    shadow_hash TEXT NOT NULL,
    distance REAL NOT NULL,
    divergence_count INTEGER DEFAULT 1,
    resolution TEXT,  -- rollback, quarantine, resolved
    resolved_at TEXT
);

-- Convergence checkpoints
CREATE TABLE IF NOT EXISTS convergence_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    checkpoint_name TEXT NOT NULL,
    primary_state_hash TEXT NOT NULL,
    shadow_state_hash TEXT NOT NULL,
    validator_state_hash TEXT NOT NULL,
    is_stable INTEGER DEFAULT 1,
    knowledge_count INTEGER
);

-- Self-healing actions
CREATE TABLE IF NOT EXISTS healing_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    action_type TEXT NOT NULL,  -- rollback, consolidation, quarantine, core_protect
    trigger_reason TEXT NOT NULL,
    affected_items INTEGER,
    success INTEGER DEFAULT 1,
    details TEXT  -- JSON
);

-- Metrics history (for monitoring)
CREATE TABLE IF NOT EXISTS metrics_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    total_energy REAL,
    entropy REAL,
    core_size INTEGER,
    quarantine_size INTEGER,
    divergence_distance REAL,
    organisms_count INTEGER,
    crystals_count INTEGER
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_energy_timestamp ON energy_ledger(timestamp);
CREATE INDEX IF NOT EXISTS idx_entropy_timestamp ON entropy_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_quarantine_region ON quarantine(region_id);
CREATE INDEX IF NOT EXISTS idx_divergence_region ON divergence_events(region_id);
CREATE INDEX IF NOT EXISTS idx_checkpoint_stable ON convergence_checkpoints(is_stable);
"""


class InvariantsStore:
    """
    Database interface for invariants tracking.

    This is completely separate from Frank's knowledge stores.
    """

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or INVARIANTS_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize the database schema."""
        with self._get_conn() as conn:
            conn.executescript(SCHEMA)
            conn.commit()
        LOG.info(f"Invariants database initialized at {self.db_path}")

    @contextmanager
    def _get_conn(self):
        """Get a database connection."""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # =========================================================================
    # Invariant State
    # =========================================================================

    def update_invariant_state(self, name: str, value: float,
                                threshold: float = None, status: str = "normal"):
        """Update an invariant's current state."""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO invariant_state (invariant_name, current_value, threshold, last_check, status)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(invariant_name) DO UPDATE SET
                    current_value = excluded.current_value,
                    threshold = COALESCE(excluded.threshold, threshold),
                    last_check = excluded.last_check,
                    status = excluded.status,
                    violation_count = CASE
                        WHEN excluded.status = 'violated' THEN violation_count + 1
                        ELSE violation_count
                    END
            """, (name, value, threshold, datetime.now().isoformat(), status))
            conn.commit()

    def get_invariant_state(self, name: str) -> Optional[Dict]:
        """Get an invariant's current state."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM invariant_state WHERE invariant_name = ?",
                (name,)
            ).fetchone()
            return dict(row) if row else None

    def get_all_invariant_states(self) -> List[Dict]:
        """Get all invariant states."""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM invariant_state").fetchall()
            return [dict(row) for row in rows]

    # =========================================================================
    # Energy Ledger
    # =========================================================================

    def record_energy(self, total: float, expected: float,
                      tx_type: str = None, tx_id: str = None) -> int:
        """Record an energy measurement."""
        delta = total - expected
        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT INTO energy_ledger
                (timestamp, total_energy, expected_energy, delta, transaction_type, transaction_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (datetime.now().isoformat(), total, expected, delta, tx_type, tx_id))
            conn.commit()
            return cursor.lastrowid

    def mark_energy_rollback(self, ledger_id: int):
        """Mark an energy entry as rolled back."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE energy_ledger SET rolled_back = 1 WHERE id = ?",
                (ledger_id,)
            )
            conn.commit()

    def get_energy_history(self, limit: int = 100) -> List[Dict]:
        """Get recent energy history."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM energy_ledger ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    # =========================================================================
    # Entropy
    # =========================================================================

    def record_entropy(self, entropy: float, entropy_max: float,
                       consolidation: str = None) -> int:
        """Record an entropy measurement."""
        ratio = entropy / entropy_max if entropy_max > 0 else 0
        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT INTO entropy_history
                (timestamp, entropy_value, entropy_max, ratio, consolidation_triggered, consolidation_type)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (datetime.now().isoformat(), entropy, entropy_max, ratio,
                  1 if consolidation else 0, consolidation))
            conn.commit()
            return cursor.lastrowid

    def get_entropy_history(self, limit: int = 100) -> List[Dict]:
        """Get recent entropy history."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM entropy_history ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    # =========================================================================
    # Core Kernel
    # =========================================================================

    def add_to_core(self, knowledge_id: str, energy: float,
                    connections: int, consistency: float):
        """Add a knowledge element to the core kernel."""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO core_kernel
                (knowledge_id, added_at, energy, connections, consistency_score, protected)
                VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT(knowledge_id) DO UPDATE SET
                    energy = excluded.energy,
                    connections = excluded.connections,
                    consistency_score = excluded.consistency_score
            """, (knowledge_id, datetime.now().isoformat(), energy, connections, consistency))
            conn.commit()

    def remove_from_core(self, knowledge_id: str):
        """Remove a knowledge element from the core kernel."""
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM core_kernel WHERE knowledge_id = ?",
                (knowledge_id,)
            )
            conn.commit()

    def is_in_core(self, knowledge_id: str) -> bool:
        """Check if a knowledge element is in the core."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM core_kernel WHERE knowledge_id = ?",
                (knowledge_id,)
            ).fetchone()
            return row is not None

    def get_core_kernel(self) -> List[Dict]:
        """Get all core kernel elements."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM core_kernel WHERE protected = 1 ORDER BY energy DESC"
            ).fetchall()
            return [dict(row) for row in rows]

    def get_core_size(self) -> int:
        """Get the size of the core kernel."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as count FROM core_kernel WHERE protected = 1"
            ).fetchone()
            return row["count"] if row else 0

    # =========================================================================
    # Quarantine
    # =========================================================================

    def quarantine_knowledge(self, knowledge_id: str, original_data: str,
                              reason: str, region_id: str = None) -> int:
        """Add a knowledge element to quarantine."""
        with self._get_conn() as conn:
            # Check if already quarantined
            existing = conn.execute(
                "SELECT id, divergence_count FROM quarantine WHERE knowledge_id = ?",
                (knowledge_id,)
            ).fetchone()

            if existing:
                # Increment divergence count
                conn.execute(
                    "UPDATE quarantine SET divergence_count = ?, region_id = ? WHERE id = ?",
                    (existing["divergence_count"] + 1, region_id, existing["id"])
                )
                conn.commit()
                return existing["id"]
            else:
                cursor = conn.execute("""
                    INSERT INTO quarantine
                    (knowledge_id, original_data, quarantine_reason, quarantined_at, region_id)
                    VALUES (?, ?, ?, ?, ?)
                """, (knowledge_id, original_data, reason, datetime.now().isoformat(), region_id))
                conn.commit()
                return cursor.lastrowid

    def get_quarantined(self, region_id: str = None) -> List[Dict]:
        """Get quarantined items, optionally filtered by region."""
        with self._get_conn() as conn:
            if region_id:
                rows = conn.execute(
                    "SELECT * FROM quarantine WHERE region_id = ? ORDER BY quarantined_at DESC",
                    (region_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM quarantine ORDER BY quarantined_at DESC"
                ).fetchall()
            return [dict(row) for row in rows]

    def get_quarantine_size(self) -> int:
        """Get the number of quarantined items."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT COUNT(*) as count FROM quarantine").fetchone()
            return row["count"] if row else 0

    def remove_from_quarantine(self, quarantine_id: int):
        """Remove an item from quarantine."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM quarantine WHERE id = ?", (quarantine_id,))
            conn.commit()

    # =========================================================================
    # Divergence Events
    # =========================================================================

    def record_divergence(self, region_id: str, primary_hash: str,
                          shadow_hash: str, distance: float) -> int:
        """Record a divergence event between realities."""
        with self._get_conn() as conn:
            # Check for existing divergence in this region
            existing = conn.execute(
                "SELECT id, divergence_count FROM divergence_events WHERE region_id = ? AND resolution IS NULL",
                (region_id,)
            ).fetchone()

            if existing:
                conn.execute(
                    "UPDATE divergence_events SET divergence_count = ?, distance = ?, shadow_hash = ? WHERE id = ?",
                    (existing["divergence_count"] + 1, distance, shadow_hash, existing["id"])
                )
                conn.commit()
                return existing["id"]
            else:
                cursor = conn.execute("""
                    INSERT INTO divergence_events
                    (timestamp, region_id, primary_hash, shadow_hash, distance)
                    VALUES (?, ?, ?, ?, ?)
                """, (datetime.now().isoformat(), region_id, primary_hash, shadow_hash, distance))
                conn.commit()
                return cursor.lastrowid

    def resolve_divergence(self, divergence_id: int, resolution: str):
        """Mark a divergence as resolved."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE divergence_events SET resolution = ?, resolved_at = ? WHERE id = ?",
                (resolution, datetime.now().isoformat(), divergence_id)
            )
            conn.commit()

    def get_unresolved_divergences(self) -> List[Dict]:
        """Get all unresolved divergence events."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM divergence_events WHERE resolution IS NULL ORDER BY timestamp DESC"
            ).fetchall()
            return [dict(row) for row in rows]

    def get_divergence_count(self, region_id: str) -> int:
        """Get the divergence count for a region."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT divergence_count FROM divergence_events WHERE region_id = ? ORDER BY id DESC LIMIT 1",
                (region_id,)
            ).fetchone()
            return row["divergence_count"] if row else 0

    # =========================================================================
    # Convergence Checkpoints
    # =========================================================================

    def save_checkpoint(self, name: str, primary_hash: str,
                        shadow_hash: str, validator_hash: str,
                        is_stable: bool, knowledge_count: int):
        """Save a convergence checkpoint."""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO convergence_checkpoints
                (timestamp, checkpoint_name, primary_state_hash, shadow_state_hash,
                 validator_state_hash, is_stable, knowledge_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (datetime.now().isoformat(), name, primary_hash, shadow_hash,
                  validator_hash, 1 if is_stable else 0, knowledge_count))
            conn.commit()

    def get_last_stable_checkpoint(self) -> Optional[Dict]:
        """Get the most recent stable checkpoint."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM convergence_checkpoints WHERE is_stable = 1 ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    # =========================================================================
    # Healing Actions
    # =========================================================================

    def record_healing_action(self, action_type: str, reason: str,
                               affected: int, success: bool, details: str = None):
        """Record a self-healing action."""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO healing_actions
                (timestamp, action_type, trigger_reason, affected_items, success, details)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (datetime.now().isoformat(), action_type, reason, affected,
                  1 if success else 0, details))
            conn.commit()

    def get_healing_history(self, limit: int = 50) -> List[Dict]:
        """Get recent healing actions."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM healing_actions ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    # =========================================================================
    # Metrics
    # =========================================================================

    def record_metrics(self, energy: float, entropy: float, core_size: int,
                       quarantine_size: int, divergence: float,
                       organisms: int = 0, crystals: int = 0):
        """Record system metrics."""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO metrics_history
                (timestamp, total_energy, entropy, core_size, quarantine_size,
                 divergence_distance, organisms_count, crystals_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (datetime.now().isoformat(), energy, entropy, core_size,
                  quarantine_size, divergence, organisms, crystals))
            conn.commit()

            # Cleanup old metrics (keep last 10000)
            conn.execute("""
                DELETE FROM metrics_history WHERE id NOT IN (
                    SELECT id FROM metrics_history ORDER BY id DESC LIMIT 10000
                )
            """)
            conn.commit()

    def get_metrics_history(self, limit: int = 100) -> List[Dict]:
        """Get recent metrics."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM metrics_history ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    def get_stats(self) -> Dict:
        """Get database statistics."""
        with self._get_conn() as conn:
            stats = {}
            for table in ["invariant_state", "energy_ledger", "entropy_history",
                         "core_kernel", "quarantine", "divergence_events",
                         "convergence_checkpoints", "healing_actions"]:
                row = conn.execute(f"SELECT COUNT(*) as count FROM {table}").fetchone()
                stats[table] = row["count"]
            return stats


# Global store instance
_store: Optional[InvariantsStore] = None


def get_store() -> InvariantsStore:
    """Get or create the global store instance."""
    global _store
    if _store is None:
        _store = InvariantsStore()
    return _store
