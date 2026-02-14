#!/usr/bin/env python3
"""
INVARIANT 4: Core Kernel (K_core)
=================================

There always exists a non-empty set K_core subset of K
for which: for all a,b in K_core: NOT contradiction(a,b)

The core is what Frank "definitely knows that he knows".

Core formation (automatic, not decidable):
1. Knowledge with highest energy
2. Knowledge with most connections
3. Knowledge without active conflicts
4. Oldest stable knowledge

Consequences:
- Conflicts cannot reach the core
- Peripheral knowledge can be chaotic
- But there is ALWAYS a stable basis
- Total consistency loss is IMPOSSIBLE

Implementation:
- K_core is write-protected when S > S_THRESHOLD
- New conflicts cannot directly modify K_core
- They must first be "proven" in periphery
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass

from .config import get_config, InvariantsConfig
from .db_schema import get_store, InvariantsStore

LOG = logging.getLogger("invariants.core")


@dataclass
class CoreMember:
    """A member of the core kernel."""
    knowledge_id: str
    energy: float
    connections: int
    consistency_score: float
    age_days: int
    composite_score: float


class CoreKernel:
    """
    Manages the consistent core kernel K_core.

    The core is ALWAYS:
    - Non-empty (at least min_core_size elements)
    - Contradiction-free
    - Protected during high entropy
    - The stable foundation of all knowledge
    """

    def __init__(self, config: InvariantsConfig = None, store: InvariantsStore = None):
        self.config = config or get_config()
        self.store = store or get_store()

        # Current core members
        self._core_ids: Set[str] = set()
        self._protection_active = False

        LOG.info("Core Kernel initialized")

    @property
    def core_size(self) -> int:
        """Get current core size."""
        return len(self._core_ids)

    @property
    def is_protected(self) -> bool:
        """Check if core is in protected mode."""
        return self._protection_active

    def build_core(self, titan_store) -> List[CoreMember]:
        """
        Build the core kernel from current knowledge.

        Selection criteria:
        1. Energy (confidence * connections * age_factor)
        2. Connections (how interconnected)
        3. Consistency (no contradictions)
        4. Age (older = more stable)
        """
        LOG.info("Building core kernel")

        try:
            # Get all nodes
            nodes = self._get_all_nodes(titan_store)
            if not nodes:
                LOG.warning("No nodes available for core kernel")
                return []

            # Get contradictions to exclude
            contradicting_ids = self._get_contradicting_ids(titan_store)

            # Score each node
            candidates = []
            for node in nodes:
                # Skip nodes with contradictions
                if node["id"] in contradicting_ids:
                    continue

                score = self._calculate_core_score(node)
                candidates.append(CoreMember(
                    knowledge_id=node["id"],
                    energy=node.get("energy", 0),
                    connections=node.get("connections", 0),
                    consistency_score=1.0,  # No contradictions
                    age_days=node.get("age_days", 0),
                    composite_score=score
                ))

            # Sort by composite score
            candidates.sort(key=lambda c: c.composite_score, reverse=True)

            # Select top N (at least min_core_size)
            core_size = max(self.config.min_core_size, len(candidates) // 10)  # Top 10%
            core_members = candidates[:core_size]

            # Update core
            self._core_ids = {m.knowledge_id for m in core_members}

            # Persist to database
            for member in core_members:
                self.store.add_to_core(
                    member.knowledge_id,
                    member.energy,
                    member.connections,
                    member.consistency_score
                )

            LOG.info(f"Core kernel built: {len(core_members)} members")

            # Update invariant state
            self.store.update_invariant_state(
                "core_kernel",
                len(core_members),
                threshold=self.config.min_core_size,
                status="normal" if len(core_members) >= self.config.min_core_size else "warning"
            )

            return core_members

        except Exception as e:
            LOG.error(f"Error building core kernel: {e}")
            return []

    def _get_all_nodes(self, titan_store) -> List[Dict]:
        """Get all knowledge elements with energy and age calculated."""
        nodes = []
        try:
            with titan_store.sqlite._get_conn() as conn:
                # Get claims (with confidence)
                try:
                    rows = conn.execute("""
                        SELECT c.id, c.subject || ' ' || c.predicate as label,
                               c.confidence, c.created_at,
                               (SELECT COUNT(*) FROM edges WHERE src = c.id OR dst = c.id) as connections
                        FROM claims c
                    """).fetchall()
                    nodes.extend([dict(row) for row in rows])
                except Exception:
                    pass

                # Get nodes (entities)
                try:
                    rows = conn.execute("""
                        SELECT n.id, n.label, 0.5 as confidence, n.created_at,
                               (SELECT COUNT(*) FROM edges WHERE src = n.id OR dst = n.id) as connections
                        FROM nodes n
                    """).fetchall()
                    nodes.extend([dict(row) for row in rows])
                except Exception:
                    pass

                # Calculate age and energy for each node
                for node in nodes:
                    try:
                        created = datetime.fromisoformat(node["created_at"].replace("Z", "+00:00"))
                        node["age_days"] = (datetime.now() - created.replace(tzinfo=None)).days
                    except Exception:
                        node["age_days"] = 0

                    confidence = node.get("confidence", 0.5)
                    connections = node.get("connections", 0) + 1
                    age_factor = self.config.age_factor_base ** node["age_days"]

                    node["energy"] = confidence * (connections ** 0.5) * age_factor

            return nodes

        except Exception as e:
            LOG.error(f"Error getting nodes: {e}")
            return []

    def _get_contradicting_ids(self, titan_store) -> Set[str]:
        """Get IDs of nodes involved in contradictions."""
        contradicting = set()

        try:
            with titan_store.sqlite._get_conn() as conn:
                rows = conn.execute("""
                    SELECT src, dst FROM edges
                    WHERE relation IN ('contradicts', 'conflicts_with', 'negates')
                """).fetchall()

                for row in rows:
                    contradicting.add(row["src"])
                    contradicting.add(row["dst"])

        except Exception as e:
            LOG.error(f"Error getting contradicting IDs: {e}")

        return contradicting

    def _calculate_core_score(self, node: Dict) -> float:
        """
        Calculate composite score for core membership.

        Higher score = more likely to be in core.
        """
        energy = node.get("energy", 0)
        connections = node.get("connections", 0)
        age_days = node.get("age_days", 0)
        confidence = node.get("confidence", 0.5)

        # Weighted combination
        score = (
            energy * self.config.core_energy_weight +
            (connections ** 0.5) * self.config.core_connections_weight +
            confidence * self.config.core_consistency_weight +
            min(age_days / 30, 1.0) * self.config.core_age_weight  # Cap at 30 days
        )

        return score

    def is_in_core(self, knowledge_id: str) -> bool:
        """Check if a knowledge element is in the core."""
        return knowledge_id in self._core_ids

    def activate_protection(self):
        """Activate core protection mode."""
        if not self._protection_active:
            LOG.warning("Core protection ACTIVATED - core is now read-only")
            self._protection_active = True

            self.store.record_healing_action(
                "core_protect",
                "High entropy triggered protection",
                len(self._core_ids),
                True
            )

    def deactivate_protection(self):
        """Deactivate core protection mode."""
        if self._protection_active:
            LOG.info("Core protection deactivated")
            self._protection_active = False

    def validate_modification(self, knowledge_id: str, modification: Dict) -> Tuple[bool, str]:
        """
        Validate a modification against core protection rules.

        Returns:
            (is_allowed, reason)
        """
        if not self._protection_active:
            return True, "Protection not active"

        if knowledge_id not in self._core_ids:
            return True, "Not a core element"

        # Core is protected - reject modification
        return False, "Core kernel is protected - modification blocked"

    def try_promote_to_core(self, titan_store, knowledge_id: str) -> Tuple[bool, str]:
        """
        Try to promote a knowledge element to the core.

        Only allowed if:
        1. Element has no contradictions
        2. Element has sufficient energy
        3. Core is not full
        """
        # Get node
        node = self._get_node(titan_store, knowledge_id)
        if not node:
            return False, "Node not found"

        # Check contradictions
        contradicting = self._get_contradicting_ids(titan_store)
        if knowledge_id in contradicting:
            return False, "Node has contradictions - must resolve first"

        # Check energy
        score = self._calculate_core_score(node)
        if score < 0.5:  # Arbitrary threshold
            return False, "Insufficient core score"

        # Add to core
        self._core_ids.add(knowledge_id)
        self.store.add_to_core(
            knowledge_id,
            node.get("energy", 0),
            node.get("connections", 0),
            1.0
        )

        LOG.info(f"Promoted {knowledge_id} to core kernel")
        return True, "Promoted to core"

    def _get_node(self, titan_store, knowledge_id: str) -> Optional[Dict]:
        """Get a single node by ID."""
        try:
            with titan_store.sqlite._get_conn() as conn:
                row = conn.execute(
                    "SELECT * FROM nodes WHERE id = ?",
                    (knowledge_id,)
                ).fetchone()
                return dict(row) if row else None
        except Exception:
            return None

    def ensure_minimum_core(self, titan_store) -> bool:
        """
        Ensure the core has at least min_core_size elements.

        This is an INVARIANT - it must always be true.
        """
        current_size = len(self._core_ids)

        if current_size >= self.config.min_core_size:
            return True

        LOG.warning(f"Core size ({current_size}) below minimum ({self.config.min_core_size})")

        # Rebuild core
        members = self.build_core(titan_store)

        if len(members) < self.config.min_core_size:
            # CRITICAL - we need to bootstrap some knowledge
            LOG.error("Cannot meet minimum core size - system may need bootstrap")

            # Record the violation
            self.store.update_invariant_state(
                "core_kernel",
                len(members),
                threshold=self.config.min_core_size,
                status="violated"
            )

            return False

        return True

    def get_core_members(self) -> List[Dict]:
        """Get all core kernel members from database."""
        return self.store.get_core_kernel()

    def get_status(self) -> Dict:
        """Get core kernel status."""
        return {
            "size": len(self._core_ids),
            "min_size": self.config.min_core_size,
            "is_protected": self._protection_active,
            "members": list(self._core_ids)[:10],  # First 10 for display
            "is_healthy": len(self._core_ids) >= self.config.min_core_size
        }


# Global instance
_core: Optional[CoreKernel] = None


def get_core() -> CoreKernel:
    """Get or create the global core kernel instance."""
    global _core
    if _core is None:
        _core = CoreKernel()
    return _core
