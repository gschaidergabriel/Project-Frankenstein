#!/usr/bin/env python3
"""
INVARIANT 2: Entropy Bound
==========================

System entropy S has a hard upper limit S_MAX.

S = -sum(p(W) * log(p(W)) * contradiction_factor(W))

INVARIANT: S <= S_MAX

Consequences:
- When S -> S_MAX: New conflicts automatically quarantined
- System can NEVER descend into total chaos
- There is ALWAYS a consistent core

Implementation:
- Continuous measurement of S
- S > 0.7 * S_MAX -> Soft Consolidation Mode
- S > 0.9 * S_MAX -> Hard Consolidation Mode
- Not Frank's choice - thermodynamic necessity
"""

import logging
import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from .config import get_config, InvariantsConfig
from .db_schema import get_store, InvariantsStore

LOG = logging.getLogger("invariants.entropy")


class ConsolidationMode(Enum):
    """Consolidation modes based on entropy level."""
    NONE = "none"           # Normal operation
    SOFT = "soft"           # Gentle conflict resolution
    HARD = "hard"           # Aggressive consolidation
    EMERGENCY = "emergency"  # System lockdown


@dataclass
class EntropyMeasurement:
    """Result of an entropy measurement."""
    entropy: float
    entropy_max: float
    ratio: float
    contradiction_count: int
    mode: ConsolidationMode
    details: Dict


class EntropyBound:
    """
    Enforces the entropy bound on Frank's knowledge system.

    Chaos has a ceiling. This is PHYSICS, not a rule.
    When entropy approaches the limit, consolidation is FORCED.
    """

    def __init__(self, config: InvariantsConfig = None, store: InvariantsStore = None):
        self.config = config or get_config()
        self.store = store or get_store()

        # Current consolidation mode
        self._mode = ConsolidationMode.NONE
        self._last_measurement: Optional[EntropyMeasurement] = None

        # Consolidation state
        self._consolidation_start: Optional[datetime] = None
        self._conflicts_resolved = 0

        LOG.info("Entropy Bound initialized")

    @property
    def current_mode(self) -> ConsolidationMode:
        """Get current consolidation mode."""
        return self._mode

    @property
    def entropy_max(self) -> float:
        """Get the entropy ceiling."""
        return self.config.entropy_max

    def measure_entropy(self, titan_store) -> EntropyMeasurement:
        """
        Measure current system entropy.

        S = -sum(p(W) * log(p(W)) * contradiction_factor(W))
        """
        try:
            nodes = self._get_knowledge_nodes(titan_store)
            contradictions = self._find_contradictions(titan_store, nodes)

            # Calculate entropy
            if not nodes:
                entropy = 0.0
            else:
                entropy = self._calculate_entropy(nodes, contradictions)

            # Determine mode
            ratio = entropy / self.entropy_max if self.entropy_max > 0 else 0
            mode = self._determine_mode(ratio)

            measurement = EntropyMeasurement(
                entropy=entropy,
                entropy_max=self.entropy_max,
                ratio=ratio,
                contradiction_count=len(contradictions),
                mode=mode,
                details={
                    "nodes": len(nodes),
                    "contradictions": len(contradictions),
                    "soft_threshold": self.config.entropy_soft_threshold,
                    "hard_threshold": self.config.entropy_hard_threshold,
                }
            )

            self._last_measurement = measurement
            self._mode = mode

            # Record measurement
            consolidation = mode.value if mode != ConsolidationMode.NONE else None
            self.store.record_entropy(entropy, self.entropy_max, consolidation)

            # Update invariant state
            status = "normal" if ratio < self.config.entropy_soft_threshold else \
                     "warning" if ratio < self.config.entropy_hard_threshold else "critical"
            self.store.update_invariant_state(
                "entropy_bound",
                entropy,
                threshold=self.entropy_max,
                status=status
            )

            if mode != ConsolidationMode.NONE:
                LOG.warning(f"Entropy at {ratio:.1%} of max - {mode.value} consolidation triggered")

            return measurement

        except Exception as e:
            LOG.error(f"Error measuring entropy: {e}")
            return EntropyMeasurement(
                entropy=0, entropy_max=self.entropy_max, ratio=0,
                contradiction_count=0, mode=ConsolidationMode.NONE, details={}
            )

    def _get_knowledge_nodes(self, titan_store) -> List[Dict]:
        """Get all knowledge elements from Titan (claims + nodes)."""
        nodes = []
        try:
            with titan_store.sqlite._get_conn() as conn:
                # Get claims (main knowledge with confidence)
                try:
                    rows = conn.execute("""
                        SELECT c.id, c.subject || ' ' || c.predicate || ' ' || c.object as label,
                               c.confidence, 'claim' as node_type,
                               (SELECT COUNT(*) FROM edges WHERE src = c.id OR dst = c.id) as connections
                        FROM claims c
                    """).fetchall()
                    nodes.extend([dict(row) for row in rows])
                except Exception:
                    pass

                # Get nodes (entities)
                try:
                    rows = conn.execute("""
                        SELECT n.id, n.label, 0.5 as confidence, n.type as node_type,
                               (SELECT COUNT(*) FROM edges WHERE src = n.id OR dst = n.id) as connections
                        FROM nodes n
                    """).fetchall()
                    nodes.extend([dict(row) for row in rows])
                except Exception:
                    pass

            return nodes
        except Exception as e:
            LOG.error(f"Error getting nodes: {e}")
            return []

    def _find_contradictions(self, titan_store, nodes: List[Dict]) -> List[Dict]:
        """
        Find contradictions in the knowledge base.

        A contradiction is when two claims contradict each other.
        """
        contradictions = []

        try:
            with titan_store.sqlite._get_conn() as conn:
                # Look for edges with "contradicts" relation
                rows = conn.execute("""
                    SELECT e.src, e.dst, e.relation
                    FROM edges e
                    WHERE e.relation IN ('contradicts', 'conflicts_with', 'negates')
                """).fetchall()

                for row in rows:
                    contradictions.append(dict(row))

                # Also look for nodes with low consistency (implicit contradictions)
                for node in nodes:
                    if node.get("confidence", 1.0) < 0.3:
                        # Low confidence might indicate contradiction
                        contradictions.append({
                            "id": f"implicit_{node['id']}",
                            "type": "implicit",
                            "node_id": node["id"],
                            "confidence": node.get("confidence", 0)
                        })

        except Exception as e:
            LOG.error(f"Error finding contradictions: {e}")

        return contradictions

    def _calculate_entropy(self, nodes: List[Dict], contradictions: List[Dict]) -> float:
        """
        Calculate Shannon entropy with contradiction penalty.

        S = -sum(p(W) * log(p(W)) * contradiction_factor(W))
        """
        if not nodes:
            return 0.0

        # Calculate probability distribution based on confidence
        total_confidence = sum(n.get("confidence", 0.5) for n in nodes)
        if total_confidence <= 0:
            total_confidence = len(nodes) * 0.5

        # Build contradiction map
        contradiction_nodes = set()
        for c in contradictions:
            if "src" in c:
                contradiction_nodes.add(c["src"])
                contradiction_nodes.add(c["dst"])
            elif "node_id" in c:
                contradiction_nodes.add(c["node_id"])

        # Calculate entropy
        entropy = 0.0

        for node in nodes:
            confidence = node.get("confidence", 0.5)
            p = confidence / total_confidence

            if p > 0:
                # Base entropy term
                base_entropy = -p * math.log2(p)

                # Contradiction penalty
                if node["id"] in contradiction_nodes:
                    contradiction_factor = self.config.contradiction_penalty
                else:
                    contradiction_factor = 1.0

                entropy += base_entropy * contradiction_factor

        return entropy

    def _determine_mode(self, ratio: float) -> ConsolidationMode:
        """Determine consolidation mode based on entropy ratio."""
        if ratio >= 1.0:
            return ConsolidationMode.EMERGENCY
        elif ratio >= self.config.entropy_hard_threshold:
            return ConsolidationMode.HARD
        elif ratio >= self.config.entropy_soft_threshold:
            return ConsolidationMode.SOFT
        else:
            return ConsolidationMode.NONE

    def soft_consolidation(self, titan_store) -> int:
        """
        Perform soft consolidation.

        - Resolve weak conflicts
        - Increase energy flow to stable core
        - Gently prune low-confidence contradictions
        """
        if self._mode not in [ConsolidationMode.SOFT, ConsolidationMode.HARD]:
            return 0

        LOG.info("Starting soft consolidation")
        resolved = 0

        try:
            nodes = self._get_knowledge_nodes(titan_store)
            contradictions = self._find_contradictions(titan_store, nodes)

            # Resolve weak contradictions (low confidence on one side)
            for contradiction in contradictions:
                if contradiction.get("type") == "implicit":
                    # Implicit contradiction - reduce confidence further
                    node_id = contradiction.get("node_id")
                    self._reduce_confidence(titan_store, node_id, 0.8)
                    resolved += 1
                elif "src" in contradiction:
                    # Explicit contradiction - resolve in favor of higher confidence
                    resolved += self._resolve_contradiction(titan_store, contradiction, nodes)

                # Stop after resolving a fraction per cycle
                if resolved >= len(contradictions) * self.config.soft_consolidation_rate:
                    break

            self._conflicts_resolved += resolved

            # Record healing action
            if resolved > 0:
                self.store.record_healing_action(
                    "soft_consolidation",
                    f"Entropy at {self._last_measurement.ratio:.1%}",
                    resolved,
                    True
                )

            LOG.info(f"Soft consolidation resolved {resolved} conflicts")

        except Exception as e:
            LOG.error(f"Error in soft consolidation: {e}")

        return resolved

    def hard_consolidation(self, titan_store, quarantine) -> Tuple[int, int]:
        """
        Perform hard consolidation.

        - Pause new inputs
        - Resolve ALL conflicts
        - Quarantine unresolvable conflicts
        """
        if self._mode not in [ConsolidationMode.HARD, ConsolidationMode.EMERGENCY]:
            return 0, 0

        LOG.warning("Starting HARD consolidation - inputs paused")
        self._consolidation_start = datetime.now()

        resolved = 0
        quarantined = 0

        try:
            nodes = self._get_knowledge_nodes(titan_store)
            contradictions = self._find_contradictions(titan_store, nodes)

            for contradiction in contradictions:
                try:
                    if contradiction.get("type") == "implicit":
                        # Low confidence nodes - quarantine if very low
                        node_id = contradiction.get("node_id")
                        confidence = contradiction.get("confidence", 0)

                        if confidence < 0.1:
                            # Quarantine
                            node = next((n for n in nodes if n["id"] == node_id), None)
                            if node:
                                quarantine.quarantine_item(
                                    node_id,
                                    str(node),
                                    "hard_consolidation_low_confidence"
                                )
                                quarantined += 1
                        else:
                            # Just reduce confidence
                            self._reduce_confidence(titan_store, node_id, 0.5)
                            resolved += 1

                    elif "src" in contradiction:
                        # Try to resolve
                        if self._resolve_contradiction(titan_store, contradiction, nodes):
                            resolved += 1
                        else:
                            # Quarantine both nodes
                            for node_id in [contradiction["src"], contradiction["dst"]]:
                                node = next((n for n in nodes if n["id"] == node_id), None)
                                if node:
                                    quarantine.quarantine_item(
                                        node_id,
                                        str(node),
                                        "hard_consolidation_unresolvable"
                                    )
                                    quarantined += 1

                except Exception as e:
                    LOG.warning(f"Error resolving contradiction: {e}")

            # Record healing action
            self.store.record_healing_action(
                "hard_consolidation",
                f"Entropy critical at {self._last_measurement.ratio:.1%}",
                resolved + quarantined,
                True,
                f"resolved={resolved}, quarantined={quarantined}"
            )

            LOG.warning(f"Hard consolidation complete: {resolved} resolved, {quarantined} quarantined")

        except Exception as e:
            LOG.error(f"Error in hard consolidation: {e}")

        return resolved, quarantined

    def _resolve_contradiction(self, titan_store, contradiction: Dict, nodes: List[Dict]) -> bool:
        """
        Resolve a contradiction by favoring higher confidence side.
        """
        src = contradiction.get("src")
        dst = contradiction.get("dst")

        source = next((n for n in nodes if n["id"] == src), None)
        target = next((n for n in nodes if n["id"] == dst), None)

        if not source or not target:
            return False

        source_confidence = source.get("confidence", 0.5)
        target_confidence = target.get("confidence", 0.5)

        # Reduce confidence of the loser
        if source_confidence > target_confidence:
            loser_id = dst
            reduction = 0.5 * (source_confidence / (target_confidence + 0.01))
        else:
            loser_id = src
            reduction = 0.5 * (target_confidence / (source_confidence + 0.01))

        reduction = min(reduction, 0.9)  # Cap reduction
        self._reduce_confidence(titan_store, loser_id, 1 - reduction)

        return True

    def _reduce_confidence(self, titan_store, node_id: str, factor: float):
        """Reduce confidence of a node by a factor."""
        try:
            with titan_store.sqlite._get_conn() as conn:
                conn.execute(
                    "UPDATE nodes SET confidence = confidence * ? WHERE id = ?",
                    (factor, node_id)
                )
                conn.commit()
        except Exception as e:
            LOG.error(f"Error reducing confidence: {e}")

    def check_bound(self, titan_store) -> Tuple[bool, float]:
        """
        Check if entropy is within bounds.

        Returns:
            (is_within_bound, current_ratio)
        """
        measurement = self.measure_entropy(titan_store)
        is_within = measurement.ratio <= 1.0

        if not is_within:
            LOG.error(f"ENTROPY BOUND VIOLATED: {measurement.ratio:.1%} > 100%")

        return is_within, measurement.ratio

    def is_inputs_paused(self) -> bool:
        """Check if inputs should be paused (hard consolidation)."""
        if self._mode not in [ConsolidationMode.HARD, ConsolidationMode.EMERGENCY]:
            return False

        if self._consolidation_start is None:
            return False

        # Check timeout
        elapsed = (datetime.now() - self._consolidation_start).seconds
        if elapsed > self.config.hard_consolidation_timeout:
            LOG.warning("Hard consolidation timeout - resuming inputs")
            return False

        return self.config.pause_inputs_during_hard

    def get_status(self) -> Dict:
        """Get entropy status."""
        return {
            "mode": self._mode.value,
            "last_measurement": {
                "entropy": self._last_measurement.entropy if self._last_measurement else 0,
                "ratio": self._last_measurement.ratio if self._last_measurement else 0,
                "contradictions": self._last_measurement.contradiction_count if self._last_measurement else 0,
            } if self._last_measurement else None,
            "entropy_max": self.entropy_max,
            "conflicts_resolved": self._conflicts_resolved,
            "inputs_paused": self.is_inputs_paused(),
        }


# Global instance
_entropy: Optional[EntropyBound] = None


def get_entropy() -> EntropyBound:
    """Get or create the global entropy bound instance."""
    global _entropy
    if _entropy is None:
        _entropy = EntropyBound()
    return _entropy
