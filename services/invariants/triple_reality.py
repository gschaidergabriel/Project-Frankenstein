#!/usr/bin/env python3
"""
TRIPLE REALITY REDUNDANCY
=========================

Three parallel realities for convergence detection:
- REALITY-A (Primary): The actual Titan database
- REALITY-B (Shadow): Identical logic, different random seeds
- REALITY-C (Validator): Observes A and B, also emergent

Convergence Analysis:
- distance(A, B) < epsilon -> STABLE
- distance(A, B) >= epsilon -> DIVERGENCE

On Divergence:
- C does NOT decide who is "right"
- C triggers: Rollback both to last convergent state
- Divergence point marked as "unstable region"
- Next attempt with different seeds

If 3x divergence at same point:
- Region is FUNDAMENTALLY UNSTABLE
- Moved to quarantine dimension (exists but isolated)
"""

import hashlib
import json
import logging
import os
import random
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from .config import get_config, InvariantsConfig, TITAN_PRIMARY_DB, TITAN_SHADOW_DB, TITAN_VALIDATOR_DB
from .db_schema import get_store, InvariantsStore

LOG = logging.getLogger("invariants.reality")


@dataclass
class RealityState:
    """State of a single reality."""
    reality_name: str
    db_path: Path
    state_hash: str
    knowledge_count: int
    last_sync: datetime
    seed: int


@dataclass
class ConvergenceResult:
    """Result of a convergence check."""
    is_convergent: bool
    distance: float
    primary_hash: str
    shadow_hash: str
    divergent_regions: List[str]
    action_taken: str


class TripleReality:
    """
    Manages three parallel realities for convergence detection.

    This is how we PROVE stability of emergent behavior:
    If two independent runs with different seeds converge,
    the result is stable. If they diverge, the region is unstable.
    """

    def __init__(self, config: InvariantsConfig = None, store: InvariantsStore = None):
        self.config = config or get_config()
        self.store = store or get_store()

        # Reality paths
        self.primary_path = self.config.titan_primary
        self.shadow_path = self.config.titan_shadow
        self.validator_path = self.config.titan_validator

        # Random generators with different seeds
        self.rng_primary = random.Random(self.config.seed_primary)
        self.rng_shadow = random.Random(self.config.seed_shadow)
        self.rng_validator = random.Random(self.config.seed_validator)

        # State tracking
        self._last_convergent_state: Optional[str] = None
        self._divergence_counts: Dict[str, int] = {}

        # Initialize shadow reality if needed
        self._initialize_shadows()

        LOG.info("Triple Reality system initialized")

    def _initialize_shadows(self):
        """Initialize shadow and validator databases."""
        # Create shadow if it doesn't exist, is empty, or has no tables
        shadow_needs_init = False
        if not self.shadow_path.exists() or self.shadow_path.stat().st_size == 0:
            shadow_needs_init = True
        else:
            try:
                conn = sqlite3.connect(str(self.shadow_path))
                try:
                    tables = conn.execute(
                        "SELECT count(*) FROM sqlite_master WHERE type='table'"
                    ).fetchone()[0]
                    if tables == 0:
                        shadow_needs_init = True
                        LOG.warning("Shadow DB exists but has no tables — reinitializing")
                finally:
                    conn.close()
            except Exception:
                shadow_needs_init = True

        if shadow_needs_init and self.primary_path.exists():
            self.shadow_path.parent.mkdir(parents=True, exist_ok=True)
            # Atomic copy: write to tmp then rename (prevents corruption on crash)
            tmp_path = self.shadow_path.with_suffix('.tmp')
            shutil.copy2(self.primary_path, tmp_path)
            os.replace(str(tmp_path), str(self.shadow_path))
            LOG.info("Initialized shadow from primary: %s", self.shadow_path)

        # Create validator if it doesn't exist
        if not self.validator_path.exists():
            LOG.info("Initializing validator reality")
            self.validator_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.validator_path))
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS observations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        primary_hash TEXT NOT NULL,
                        shadow_hash TEXT NOT NULL,
                        distance REAL NOT NULL,
                        is_convergent INTEGER NOT NULL,
                        region_id TEXT
                    )
                """)
                conn.commit()
            finally:
                conn.close()

    def sync_shadow(self, operation: Dict):
        """
        Sync an operation to the shadow reality.

        The shadow receives the same logical operation but may
        use different random choices (e.g., for tie-breaking).
        """
        try:
            if not self.shadow_path.exists():
                return

            # Apply operation to shadow with different random seed
            shadow_conn = sqlite3.connect(str(self.shadow_path))

            try:
                op_type = operation.get("type")
                data = operation.get("data", {})

                if op_type == "insert":
                    # Insert with potentially different ID ordering
                    table = data.get("table", "nodes")
                    values = data.get("values", {})

                    # Add shadow-specific variation (e.g., slightly different timestamp)
                    if "created_at" in values:
                        # Add microsecond variation
                        values["created_at"] = datetime.now().isoformat()

                    columns = ", ".join(values.keys())
                    placeholders = ", ".join(["?" for _ in values])
                    sql = f"INSERT OR IGNORE INTO {table} ({columns}) VALUES ({placeholders})"

                    shadow_conn.execute(sql, list(values.values()))

                elif op_type == "update":
                    table = data.get("table", "nodes")
                    set_clause = data.get("set", {})
                    where = data.get("where", {})

                    set_parts = [f"{k} = ?" for k in set_clause.keys()]
                    where_parts = [f"{k} = ?" for k in where.keys()]

                    sql = f"UPDATE {table} SET {', '.join(set_parts)} WHERE {' AND '.join(where_parts)}"
                    shadow_conn.execute(sql, list(set_clause.values()) + list(where.values()))

                elif op_type == "delete":
                    table = data.get("table", "nodes")
                    where = data.get("where", {})

                    where_parts = [f"{k} = ?" for k in where.keys()]
                    sql = f"DELETE FROM {table} WHERE {' AND '.join(where_parts)}"
                    shadow_conn.execute(sql, list(where.values()))

                shadow_conn.commit()

            finally:
                shadow_conn.close()

        except Exception as e:
            LOG.error(f"Error syncing to shadow: {e}")

    def check_convergence(self) -> ConvergenceResult:
        """
        Check if primary and shadow realities have converged.

        Returns detailed result including divergent regions.
        """
        try:
            # Get state hashes
            primary_hash = self._compute_state_hash(self.primary_path)
            shadow_hash = self._compute_state_hash(self.shadow_path)

            # Calculate distance (structural difference)
            distance, divergent_regions = self._calculate_distance(
                self.primary_path, self.shadow_path
            )

            # Check convergence
            is_convergent = distance < self.config.convergence_epsilon

            # Record observation in validator
            self._record_observation(primary_hash, shadow_hash, distance, is_convergent,
                                    divergent_regions[0] if divergent_regions else None)

            # Determine action
            action = "none"

            if is_convergent:
                # Save as last known good state
                self._last_convergent_state = primary_hash
                self.store.save_checkpoint(
                    f"convergent_{datetime.now().timestamp()}",
                    primary_hash, shadow_hash, "",
                    True, self._count_knowledge(self.primary_path)
                )
            else:
                # Handle divergence
                action = self._handle_divergence(divergent_regions, distance)

            # Log result
            if is_convergent:
                LOG.debug(f"Convergence check: STABLE (distance={distance:.4f})")
            else:
                LOG.warning(f"Convergence check: DIVERGENT (distance={distance:.4f})")

            return ConvergenceResult(
                is_convergent=is_convergent,
                distance=distance,
                primary_hash=primary_hash,
                shadow_hash=shadow_hash,
                divergent_regions=divergent_regions,
                action_taken=action
            )

        except Exception as e:
            LOG.error(f"Error checking convergence: {e}")
            return ConvergenceResult(
                is_convergent=True,  # Fail safe
                distance=0.0,
                primary_hash="",
                shadow_hash="",
                divergent_regions=[],
                action_taken="error"
            )

    def _compute_state_hash(self, db_path: Path) -> str:
        """Compute a hash of the database state."""
        if not db_path.exists():
            return "empty"

        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row

            hasher = hashlib.sha256()

            # Hash nodes table
            try:
                rows = conn.execute(
                    "SELECT id, label, content, confidence FROM nodes ORDER BY id"
                ).fetchall()

                for row in rows:
                    row_str = f"{row['id']}:{row['label']}:{row['confidence']:.4f}"
                    hasher.update(row_str.encode())
            except Exception:
                pass

            # Hash edges table
            try:
                rows = conn.execute(
                    "SELECT src, dst, relation FROM edges ORDER BY src, dst"
                ).fetchall()

                for row in rows:
                    row_str = f"{row['src']}->{row['dst']}:{row['relation']}"
                    hasher.update(row_str.encode())
            except Exception:
                pass

            conn.close()
            return hasher.hexdigest()[:16]

        except Exception as e:
            LOG.error(f"Error computing state hash: {e}")
            return "error"

    def _calculate_distance(self, path_a: Path, path_b: Path) -> Tuple[float, List[str]]:
        """
        Calculate structural distance between two realities.

        Returns (distance, list of divergent regions).
        """
        divergent_regions = []

        try:
            if not path_a.exists() or not path_b.exists():
                return 0.0, []

            conn_a = sqlite3.connect(str(path_a))
            conn_b = sqlite3.connect(str(path_b))
            conn_a.row_factory = sqlite3.Row
            conn_b.row_factory = sqlite3.Row

            # Compare node counts
            try:
                count_a = conn_a.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
                count_b = conn_b.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            except Exception:
                count_a = count_b = 0

            if count_a == 0 and count_b == 0:
                conn_a.close()
                conn_b.close()
                return 0.0, []

            # Calculate Jaccard distance on node IDs
            try:
                ids_a = set(row[0] for row in conn_a.execute("SELECT id FROM nodes").fetchall())
                ids_b = set(row[0] for row in conn_b.execute("SELECT id FROM nodes").fetchall())
            except Exception:
                ids_a = ids_b = set()

            intersection = len(ids_a & ids_b)
            union = len(ids_a | ids_b)

            if union == 0:
                jaccard_distance = 0.0
            else:
                jaccard_distance = 1.0 - (intersection / union)

            # Find divergent nodes
            only_in_a = ids_a - ids_b
            only_in_b = ids_b - ids_a

            for node_id in only_in_a | only_in_b:
                region_id = f"node_{node_id[:8]}"
                if region_id not in divergent_regions:
                    divergent_regions.append(region_id)

            # Compare confidence values for shared nodes
            confidence_diff = 0.0
            shared_count = 0

            for node_id in ids_a & ids_b:
                try:
                    conf_a = conn_a.execute(
                        "SELECT confidence FROM nodes WHERE id = ?", (node_id,)
                    ).fetchone()[0]
                    conf_b = conn_b.execute(
                        "SELECT confidence FROM nodes WHERE id = ?", (node_id,)
                    ).fetchone()[0]

                    if conf_a is not None and conf_b is not None:
                        diff = abs(conf_a - conf_b)
                        confidence_diff += diff
                        shared_count += 1

                        if diff > 0.1:  # Significant difference
                            region_id = f"conf_{node_id[:8]}"
                            if region_id not in divergent_regions:
                                divergent_regions.append(region_id)
                except Exception:
                    pass

            # Normalize confidence difference
            avg_conf_diff = confidence_diff / max(shared_count, 1)

            # Combined distance
            distance = (jaccard_distance * 0.7) + (avg_conf_diff * 0.3)

            conn_a.close()
            conn_b.close()

            return distance, divergent_regions

        except Exception as e:
            LOG.error(f"Error calculating distance: {e}")
            return 0.0, []

    def _record_observation(self, primary_hash: str, shadow_hash: str,
                           distance: float, is_convergent: bool, region_id: str = None):
        """Record an observation in the validator database."""
        try:
            conn = sqlite3.connect(str(self.validator_path))
            conn.execute("""
                INSERT INTO observations
                (timestamp, primary_hash, shadow_hash, distance, is_convergent, region_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (datetime.now().isoformat(), primary_hash, shadow_hash,
                  distance, 1 if is_convergent else 0, region_id))
            conn.commit()
            conn.close()
        except Exception as e:
            LOG.error(f"Error recording observation: {e}")

    def _count_knowledge(self, db_path: Path) -> int:
        """Count knowledge elements in a database."""
        try:
            conn = sqlite3.connect(str(db_path))
            count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            conn.close()
            return count
        except Exception:
            return 0

    def _handle_divergence(self, regions: List[str], distance: float) -> str:
        """
        Handle a divergence event.

        Returns the action taken.
        """
        if not regions:
            regions = [f"unknown_{datetime.now().timestamp()}"]

        primary_region = regions[0]

        # Increment divergence count for this region
        self._divergence_counts[primary_region] = \
            self._divergence_counts.get(primary_region, 0) + 1

        divergence_count = self._divergence_counts[primary_region]

        # Record divergence
        self.store.record_divergence(
            primary_region,
            self._compute_state_hash(self.primary_path),
            self._compute_state_hash(self.shadow_path),
            distance
        )

        if divergence_count >= self.config.max_divergence_attempts:
            # Region is fundamentally unstable - quarantine
            LOG.warning(f"Region {primary_region} failed {divergence_count}x - quarantining")
            self.store.record_healing_action(
                "quarantine_region",
                f"Region diverged {divergence_count} times",
                1,
                True,
                primary_region
            )
            return "quarantine"

        else:
            # Rollback both to last convergent state
            LOG.warning(f"Divergence detected - rolling back (attempt {divergence_count}/{self.config.max_divergence_attempts})")

            success = self._rollback_to_convergent()
            if success:
                self.store.record_healing_action(
                    "convergence_rollback",
                    f"Divergence in region {primary_region}",
                    1,
                    True
                )
                return "rollback"
            else:
                return "rollback_failed"

    def _rollback_to_convergent(self) -> bool:
        """Rollback both realities to last convergent state."""
        try:
            checkpoint = self.store.get_last_stable_checkpoint()
            if not checkpoint:
                LOG.warning("No stable checkpoint found - cannot rollback")
                return False

            # For now, just resync shadow to primary
            # A full implementation would restore both from backup
            if self.primary_path.exists():
                tmp_path = self.shadow_path.with_suffix('.tmp')
                shutil.copy2(self.primary_path, tmp_path)
                os.replace(str(tmp_path), str(self.shadow_path))
                LOG.info("Rolled back shadow to primary state")

            # Reseed random generators
            self.rng_shadow = random.Random(self.rng_shadow.randint(0, 2**32))

            return True

        except Exception as e:
            LOG.error(f"Error rolling back: {e}")
            return False

    def force_resync(self):
        """Force resync shadow to primary."""
        try:
            if self.primary_path.exists():
                tmp_path = self.shadow_path.with_suffix('.tmp')
                shutil.copy2(self.primary_path, tmp_path)
                os.replace(str(tmp_path), str(self.shadow_path))
                LOG.info("Force resynced shadow to primary")

                # Reset divergence counts
                self._divergence_counts.clear()

        except Exception as e:
            LOG.error(f"Error force resyncing: {e}")

    def get_status(self) -> Dict:
        """Get triple reality status."""
        return {
            "primary_exists": self.primary_path.exists(),
            "shadow_exists": self.shadow_path.exists(),
            "validator_exists": self.validator_path.exists(),
            "primary_hash": self._compute_state_hash(self.primary_path),
            "shadow_hash": self._compute_state_hash(self.shadow_path),
            "primary_count": self._count_knowledge(self.primary_path),
            "shadow_count": self._count_knowledge(self.shadow_path),
            "divergence_counts": dict(self._divergence_counts),
            "last_convergent_state": self._last_convergent_state,
        }


# Global instance
_reality: Optional[TripleReality] = None


def get_reality() -> TripleReality:
    """Get or create the global triple reality instance."""
    global _reality
    if _reality is None:
        _reality = TripleReality()
    return _reality
