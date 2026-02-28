#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Titan Maintenance Layer - Pruning & Aging

Handles:
1. Time-based confidence decay
2. Orphan node pruning
3. Low-confidence item removal
4. Memory compaction

Pruning rules (from spec):
- degree=0 (orphan nodes)
- protected=false
- confidence<0.2
- age>7 days

Database: <AICORE_BASE>/database/titan.db
"""

import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from .storage import SQLiteStore, VectorStore, KnowledgeGraph, Node

LOG = logging.getLogger("titan.maintenance")


# Pruning thresholds
PRUNE_MIN_CONFIDENCE = 0.2      # Below this, item can be pruned
PRUNE_MIN_AGE_DAYS = 7          # Must be older than this to prune
DECAY_HALF_LIFE_DAYS = 7        # Confidence halves every 7 days

# Compaction settings
MAX_NODES_SOFT = 10000          # Soft limit before aggressive pruning
MAX_NODES_HARD = 50000          # Hard limit, force pruning


@dataclass
class PruneStats:
    """Statistics from a pruning run."""
    nodes_checked: int = 0
    nodes_pruned: int = 0
    edges_pruned: int = 0
    vectors_removed: int = 0
    confidence_updated: int = 0
    duration_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "nodes_checked": self.nodes_checked,
            "nodes_pruned": self.nodes_pruned,
            "edges_pruned": self.edges_pruned,
            "vectors_removed": self.vectors_removed,
            "confidence_updated": self.confidence_updated,
            "duration_ms": self.duration_ms
        }


class MaintenanceEngine:
    """
    Memory maintenance engine.

    Runs periodic maintenance tasks:
    - Decay confidence over time
    - Prune orphan nodes
    - Remove low-confidence items
    - Compact storage
    """

    def __init__(self, sqlite: SQLiteStore, vectors: VectorStore,
                 graph: KnowledgeGraph):
        self.sqlite = sqlite
        self.vectors = vectors
        self.graph = graph
        self._last_maintenance = 0
        self._maintenance_interval = 3600  # 1 hour

    def should_run_maintenance(self) -> bool:
        """Check if maintenance should run."""
        now = time.time()
        return (now - self._last_maintenance) > self._maintenance_interval

    def run_maintenance(self, force: bool = False) -> PruneStats:
        """
        Run full maintenance cycle.

        Steps:
        1. Update confidence decay
        2. Prune orphan nodes
        3. Remove low-confidence items
        4. Compact vectors
        """
        if not force and not self.should_run_maintenance():
            return PruneStats()

        start_time = time.time()
        stats = PruneStats()

        LOG.info("Starting maintenance cycle")

        # 0. Unprotect nodes past their 24h protection window
        self._unprotect_expired_nodes()

        # 1. Update confidence decay
        stats.confidence_updated = self._decay_confidence()

        # 2. Find and prune candidates
        candidates = self._find_prune_candidates()
        stats.nodes_checked = len(candidates)

        # 3. Prune each candidate
        for node_id, reason in candidates:
            if self._prune_node(node_id):
                stats.nodes_pruned += 1
                stats.vectors_removed += 1

        # 4. Save vectors
        self.vectors.save()

        stats.duration_ms = int((time.time() - start_time) * 1000)
        self._last_maintenance = time.time()

        LOG.info(f"Maintenance complete: {stats.nodes_pruned} nodes pruned "
                 f"in {stats.duration_ms}ms")

        return stats

    def _unprotect_expired_nodes(self):
        """Remove protection from nodes past their 24h unprotect_after window."""
        conn = self.sqlite._get_conn()
        now = datetime.now().isoformat()
        import json as _json
        rows = conn.execute("""
            SELECT id, metadata FROM nodes WHERE protected = 1
        """).fetchall()
        unprotected = 0
        for row in rows:
            try:
                meta = _json.loads(row["metadata"] or "{}")
                unprotect_after = meta.get("unprotect_after")
                if unprotect_after and unprotect_after < now:
                    conn.execute("UPDATE nodes SET protected = 0 WHERE id = ?", (row["id"],))
                    unprotected += 1
            except Exception:
                pass
        if unprotected:
            conn.commit()
            LOG.debug(f"Unprotected {unprotected} expired nodes")

    def _decay_confidence(self) -> int:
        """Apply time-based confidence decay to all nodes.

        Fix #30: Use BEGIN IMMEDIATE for upfront write lock.
        Early abort on first lock failure instead of 514 individual errors.
        Proper rollback on failure.
        """
        import json as _json
        conn = self.sqlite._get_conn()
        updated = 0
        now = datetime.now()

        try:
            # Get write lock upfront — fail fast if DB is busy
            conn.execute("BEGIN IMMEDIATE")
        except Exception as e:
            LOG.warning(f"Decay skipped: could not acquire write lock: {e}")
            return 0

        try:
            rows = conn.execute("""
                SELECT id, created_at, metadata FROM nodes
                WHERE protected = 0
            """).fetchall()

            for row in rows:
                try:
                    node_id = row["id"]
                    created_at = row["created_at"]
                    metadata = row["metadata"]

                    if not metadata:
                        continue

                    meta = _json.loads(metadata)
                    base_confidence = meta.get("confidence", 0.5)

                    created = datetime.fromisoformat(created_at)
                    age_days = (now - created).total_seconds() / 86400

                    decay_factor = math.pow(2, -age_days / DECAY_HALF_LIFE_DAYS)
                    new_confidence = base_confidence * decay_factor

                    if abs(new_confidence - base_confidence) > 0.05:
                        meta["effective_confidence"] = new_confidence
                        conn.execute("""
                            UPDATE nodes SET metadata = ?
                            WHERE id = ?
                        """, (_json.dumps(meta), node_id))
                        updated += 1

                except Exception as e:
                    # Fix #30: Early abort — if one update fails with lock,
                    # all subsequent will too. Don't spam 514 warnings.
                    if "locked" in str(e) or "database" in str(e).lower():
                        LOG.warning(f"Decay aborted after {updated} updates: {e}")
                        conn.rollback()
                        return updated
                    LOG.debug(f"Skipping node {row['id']}: {e}")

            conn.commit()
            return updated

        except Exception as e:
            LOG.warning(f"Decay failed, rolling back: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
            return updated

    def _find_prune_candidates(self) -> List[Tuple[str, str]]:
        """
        Find nodes that are candidates for pruning.

        Pruning rules:
        - degree=0 (no edges)
        - protected=false
        - confidence<0.2
        - age>7 days
        """
        conn = self.sqlite._get_conn()
        candidates = []
        now = datetime.now()
        cutoff = now - timedelta(days=PRUNE_MIN_AGE_DAYS)

        # Get all unprotected nodes older than cutoff
        rows = conn.execute("""
            SELECT id, created_at, metadata FROM nodes
            WHERE protected = 0
            AND created_at < ?
        """, (cutoff.isoformat(),)).fetchall()

        for row in rows:
            node_id = row["id"]
            reason = None

            # Check if orphan (no edges)
            degree = self.sqlite.get_node_degree(node_id)
            if degree == 0:
                reason = "orphan"

            # Check confidence
            if not reason:
                try:
                    import json
                    meta = json.loads(row["metadata"] or "{}")
                    effective_conf = meta.get("effective_confidence",
                                              meta.get("confidence", 0.5))
                    if effective_conf < PRUNE_MIN_CONFIDENCE:
                        reason = "low_confidence"
                except Exception:
                    pass

            if reason:
                candidates.append((node_id, reason))

        return candidates

    def _prune_node(self, node_id: str) -> bool:
        """Prune a single node."""
        try:
            # Check if protected (safety check)
            node = self.sqlite.get_node(node_id)
            if not node or node.protected:
                return False

            # Remove from vector store
            self.vectors.remove(node_id)

            # Delete from sqlite (also removes edges and FTS)
            return self.sqlite.delete_node(node_id)

        except Exception as e:
            LOG.error(f"Failed to prune node {node_id}: {e}")
            return False

    def protect_node(self, node_id: str) -> bool:
        """Mark a node as protected from pruning."""
        return self.sqlite.set_protected(node_id, True)

    def unprotect_node(self, node_id: str) -> bool:
        """Remove protection from a node."""
        return self.sqlite.set_protected(node_id, False)

    def force_forget(self, node_id: str) -> bool:
        """
        Force forget a node (even if protected).

        Use with caution!
        """
        try:
            # Unprotect first
            self.sqlite.set_protected(node_id, False)

            # Remove from vector store
            self.vectors.remove(node_id)

            # Delete from sqlite
            conn = self.sqlite._get_conn()
            conn.execute("DELETE FROM edges WHERE src = ? OR dst = ?",
                         (node_id, node_id))
            conn.execute("DELETE FROM memory_fts WHERE node_id = ?",
                         (node_id,))
            conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
            conn.commit()

            return True
        except Exception as e:
            LOG.error(f"Failed to force forget {node_id}: {e}")
            return False

    def compact_if_needed(self) -> PruneStats:
        """
        Run aggressive compaction if over soft limit.
        """
        stats = self.sqlite.get_stats()
        node_count = stats["nodes"]

        if node_count < MAX_NODES_SOFT:
            return PruneStats()

        LOG.warning(f"Node count {node_count} exceeds soft limit, "
                    f"running aggressive compaction")

        # Run maintenance with lower thresholds
        return self._aggressive_prune(node_count)

    def _aggressive_prune(self, current_count: int) -> PruneStats:
        """
        Aggressive pruning when over limits.

        Lowers thresholds progressively.
        """
        stats = PruneStats()
        conn = self.sqlite._get_conn()

        # Calculate how many to remove
        target = MAX_NODES_SOFT * 0.8  # 80% of soft limit
        to_remove = int(current_count - target)

        if to_remove <= 0:
            return stats

        LOG.info(f"Aggressive prune: removing ~{to_remove} nodes")

        # Get oldest, lowest-confidence unprotected nodes
        rows = conn.execute("""
            SELECT id, created_at, metadata FROM nodes
            WHERE protected = 0
            ORDER BY created_at ASC
            LIMIT ?
        """, (to_remove * 2,)).fetchall()  # Get extra for filtering

        pruned = 0
        for row in rows:
            if pruned >= to_remove:
                break

            node_id = row["id"]
            degree = self.sqlite.get_node_degree(node_id)

            # Prefer orphans and low-degree nodes
            if degree <= 2:
                if self._prune_node(node_id):
                    pruned += 1

        stats.nodes_pruned = pruned
        self.vectors.save()

        return stats

    def get_maintenance_status(self) -> dict:
        """Get current maintenance status."""
        stats = self.sqlite.get_stats()
        return {
            "nodes": stats["nodes"],
            "edges": stats["edges"],
            "vectors": self.vectors.get_stats()["vectors"],
            "last_maintenance": self._last_maintenance,
            "next_maintenance": self._last_maintenance + self._maintenance_interval,
            "soft_limit": MAX_NODES_SOFT,
            "hard_limit": MAX_NODES_HARD,
        }


# Singleton instance
_engine: Optional[MaintenanceEngine] = None


def get_maintenance_engine(sqlite: SQLiteStore, vectors: VectorStore,
                            graph: KnowledgeGraph) -> MaintenanceEngine:
    """Get or create maintenance engine."""
    global _engine
    if _engine is None:
        _engine = MaintenanceEngine(sqlite, vectors, graph)
    return _engine
