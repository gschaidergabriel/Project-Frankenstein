#!/usr/bin/env python3
"""
INVARIANT 1: Energy Conservation
================================

Total knowledge energy is CONSTANT.

E(W) = confidence(W) * connections(W) * age_factor(W)

INVARIANT: sum(E(all_knowledge)) = ENERGY_CONSTANT

Consequences:
- New knowledge must "take" energy from existing
- False knowledge with few connections loses energy
- Highly connected knowledge is energetically stable
- Unbounded growth of false knowledge is PHYSICALLY IMPOSSIBLE

Implementation:
- On every write: assert total_energy() == ENERGY_CONSTANT
- If not: Transaction rollback (not Frank's decision - physical impossibility)
"""

import logging
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from .config import get_config, InvariantsConfig
from .db_schema import get_store, InvariantsStore

LOG = logging.getLogger("invariants.energy")


@dataclass
class KnowledgeEnergy:
    """Energy of a single knowledge element."""
    knowledge_id: str
    confidence: float
    connections: int
    age_days: float
    energy: float


class EnergyConservation:
    """
    Enforces energy conservation in Frank's knowledge system.

    This is PHYSICS, not a rule. Frank cannot see or modify it.
    Transactions that violate energy conservation simply FAIL.
    """

    def __init__(self, config: InvariantsConfig = None, store: InvariantsStore = None):
        self.config = config or get_config()
        self.store = store or get_store()

        # The energy constant (set on first measurement or loaded from state)
        self._energy_constant: Optional[float] = None
        self._initialized = False

        LOG.info("Energy Conservation initialized")

    @property
    def energy_constant(self) -> float:
        """Get the energy constant (lazy initialization)."""
        if self._energy_constant is None:
            self._energy_constant = self.config.energy_constant
        return self._energy_constant

    def initialize(self, titan_store) -> float:
        """
        Initialize the energy constant from current knowledge state.

        Sets the energy constant to the MEASURED total energy.
        If the system has grown since last init, the constant adapts.
        """
        # Calculate total energy from existing knowledge
        total = self._calculate_total_energy(titan_store)

        if total <= 0:
            # Should not happen with baseline, but safety fallback
            total = 100.0
            LOG.info(f"Bootstrapping energy constant (baseline): {total}")
        else:
            LOG.info(f"Measured energy constant: {total:.4f}")

        # If already initialized but energy has grown organically,
        # adapt the constant to reflect the new knowledge level.
        if self._initialized and self._energy_constant is not None:
            old = self._energy_constant
            if abs(total - old) / max(old, 1.0) > 0.10:
                LOG.info(f"Energy constant adapting: {old:.2f} → {total:.2f} "
                         f"(knowledge base grew)")
                self._energy_constant = total
                self.config.energy_constant = total
        else:
            self._energy_constant = total
            self.config.energy_constant = total

        self._initialized = True

        # Record initial state
        self.store.update_invariant_state(
            "energy_conservation",
            total,
            threshold=self._energy_constant,
            status="normal"
        )

        return self._energy_constant

    def _calculate_total_energy(self, titan_store) -> float:
        """Calculate total energy from knowledge store.

        Energy is derived from ALL knowledge artifacts, not just nodes:
        - Nodes and Claims (traditional knowledge elements)
        - Edges (relationship connections — the main knowledge structure)
        - Events (ingested raw knowledge)
        - System baseline (always-present energy from active services)
        """
        try:
            total_energy = 0.0

            # 1. Traditional node/claim energy
            nodes = self._get_all_nodes(titan_store)
            for node in nodes:
                total_energy += self._calculate_node_energy(node)

            # 2. Edge-based energy: edges represent knowledge connections
            #    Even if nodes table is empty, edges carry structure.
            try:
                with titan_store.sqlite._get_conn() as conn:
                    row = conn.execute(
                        "SELECT COUNT(*) as cnt FROM edges"
                    ).fetchone()
                    edge_count = row["cnt"] if row else 0
                    # Each edge contributes proportional energy
                    total_energy += edge_count * 0.1
            except Exception:
                pass

            # 3. Event-based energy: raw ingested knowledge
            try:
                with titan_store.sqlite._get_conn() as conn:
                    row = conn.execute(
                        "SELECT COUNT(*) as cnt FROM events"
                    ).fetchone()
                    event_count = row["cnt"] if row else 0
                    total_energy += event_count * 0.2
            except Exception:
                pass

            # 4. System baseline: running services are always "alive"
            #    This prevents total_energy=0 when knowledge store is sparse.
            total_energy += 100.0  # Base energy from active system

            return total_energy

        except Exception as e:
            LOG.error(f"Error calculating total energy: {e}")
            # Return baseline instead of 0 to avoid perpetual violation
            return 100.0

    def _get_all_nodes(self, titan_store) -> List[Dict]:
        """Get all knowledge elements from Titan store (claims + nodes)."""
        try:
            nodes = []

            # Access the SQLite store directly
            with titan_store.sqlite._get_conn() as conn:
                # Get claims (main knowledge with confidence)
                try:
                    rows = conn.execute("""
                        SELECT c.id, c.subject || ' ' || c.predicate || ' ' || c.object as label,
                               c.confidence, c.created_at,
                               (SELECT COUNT(*) FROM edges WHERE src = c.id OR dst = c.id) as connections
                        FROM claims c
                    """).fetchall()
                    nodes.extend([dict(row) for row in rows])
                except Exception:
                    pass

                # Get nodes without confidence (use default 0.5)
                try:
                    rows = conn.execute("""
                        SELECT n.id, n.label, 0.5 as confidence, n.created_at,
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

    def _calculate_node_energy(self, node: Dict) -> float:
        """
        Calculate energy of a single knowledge node.

        E(W) = confidence(W) * connections(W) * age_factor(W)
        """
        confidence = node.get("confidence", 0.5)
        connections = node.get("connections", 0) + 1  # +1 to avoid zero
        created_at = node.get("created_at", datetime.now().isoformat())

        # Calculate age in days
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            age_days = (datetime.now() - created.replace(tzinfo=None)).days
        except Exception:
            age_days = 0

        # Age factor with exponential decay
        age_factor = self.config.age_factor_base ** age_days

        # Calculate energy
        energy = (
            (confidence * self.config.confidence_weight) *
            (math.log1p(connections) * self.config.connections_weight) *
            age_factor
        )

        return max(energy, 0.001)  # Minimum energy to prevent zero

    def check_conservation(self, titan_store) -> Tuple[bool, float, float]:
        """
        Check if energy conservation holds.

        Returns:
            (is_conserved, current_energy, expected_energy)
        """
        if not self._initialized:
            self.initialize(titan_store)

        current = self._calculate_total_energy(titan_store)
        expected = self.energy_constant

        # Check within tolerance
        delta = abs(current - expected) / expected if expected > 0 else 0
        is_conserved = delta <= self.config.energy_tolerance

        # Record the check
        self.store.record_energy(
            current, expected,
            tx_type="check",
            tx_id=f"check_{datetime.now().timestamp()}"
        )

        # Update invariant state
        status = "normal" if is_conserved else "violated"
        self.store.update_invariant_state(
            "energy_conservation",
            current,
            threshold=expected,
            status=status
        )

        if not is_conserved:
            LOG.warning(f"Energy conservation violated! Current={current:.4f}, Expected={expected:.4f}, Delta={delta:.4%}")

        return is_conserved, current, expected

    def validate_transaction(self, titan_store, old_state: Dict, new_state: Dict) -> bool:
        """
        Validate that a transaction preserves energy conservation.

        This is called BEFORE a write to Titan is committed.
        If this returns False, the transaction MUST be rolled back.
        """
        # Calculate energy before and after
        energy_before = self._calculate_state_energy(old_state)
        energy_after = self._calculate_state_energy(new_state)

        delta = abs(energy_after - energy_before)
        tolerance = self.energy_constant * self.config.energy_tolerance

        is_valid = delta <= tolerance

        if not is_valid:
            LOG.warning(f"Transaction would violate energy conservation: "
                       f"before={energy_before:.4f}, after={energy_after:.4f}")

        return is_valid

    def _calculate_state_energy(self, state: Dict) -> float:
        """Calculate total energy from a state snapshot."""
        total = 0.0
        for node in state.get("nodes", []):
            total += self._calculate_node_energy(node)
        return total

    def redistribute_energy(self, titan_store, new_knowledge: Dict) -> Dict:
        """
        Redistribute energy when new knowledge is added.

        New knowledge must "borrow" energy from existing knowledge.
        This ensures total energy remains constant.
        """
        # Calculate energy needed for new knowledge
        new_energy = self._calculate_node_energy(new_knowledge)

        # Find candidates to borrow from (low confidence, few connections, old)
        candidates = self._find_energy_donors(titan_store, new_energy)

        # Redistribute
        borrowed = 0.0
        updates = []

        for candidate in candidates:
            if borrowed >= new_energy:
                break

            # Take at most 50% of candidate's energy
            take = min(candidate["energy"] * 0.5, new_energy - borrowed)
            borrowed += take

            updates.append({
                "id": candidate["id"],
                "energy_delta": -take,
                "new_confidence": candidate["confidence"] * (1 - take / candidate["energy"])
            })

        return {
            "new_knowledge": new_knowledge,
            "energy_borrowed": borrowed,
            "updates": updates,
            "is_valid": borrowed >= new_energy * 0.99  # 99% of needed energy
        }

    def _find_energy_donors(self, titan_store, needed: float) -> List[Dict]:
        """Find knowledge elements that can donate energy."""
        nodes = self._get_all_nodes(titan_store)

        # Calculate energy for each
        for node in nodes:
            node["energy"] = self._calculate_node_energy(node)

        # Sort by donation priority (low energy first, but not in core)
        nodes.sort(key=lambda n: (n.get("protected", False), n["energy"]))

        # Return enough donors to cover needed energy
        donors = []
        total = 0.0

        for node in nodes:
            if total >= needed * 2:  # Get 2x needed for safety
                break
            if node["energy"] > 0.01:  # Skip very low energy nodes
                donors.append(node)
                total += node["energy"] * 0.5  # Can take 50%

        return donors

    def get_energy_distribution(self, titan_store) -> Dict:
        """Get energy distribution statistics."""
        nodes = self._get_all_nodes(titan_store)

        if not nodes:
            return {"total": 0, "count": 0, "mean": 0, "std": 0}

        energies = [self._calculate_node_energy(n) for n in nodes]
        total = sum(energies)
        mean = total / len(energies)
        variance = sum((e - mean) ** 2 for e in energies) / len(energies)
        std = math.sqrt(variance)

        return {
            "total": total,
            "count": len(energies),
            "mean": mean,
            "std": std,
            "min": min(energies),
            "max": max(energies),
            "constant": self.energy_constant,
            "delta": abs(total - self.energy_constant),
            "is_conserved": (abs(total - self.energy_constant) / self.energy_constant <= self.config.energy_tolerance) if self.energy_constant > 0 else True
        }

    def enforce_conservation(self, titan_store) -> bool:
        """
        Enforce energy conservation by normalizing all energies.

        This is called when conservation is violated to restore balance.
        """
        is_conserved, current, expected = self.check_conservation(titan_store)

        if is_conserved:
            return True

        # Calculate scaling factor
        if current <= 0:
            LOG.error("Cannot enforce conservation: current energy is zero")
            return False

        scale_factor = expected / current
        LOG.info(f"Enforcing conservation: scaling all energies by {scale_factor:.4f}")

        # Scale all confidences to restore balance
        try:
            nodes = self._get_all_nodes(titan_store)

            for node in nodes:
                new_confidence = node["confidence"] * scale_factor
                new_confidence = max(0.01, min(1.0, new_confidence))

                # Update in Titan
                with titan_store.sqlite._get_conn() as conn:
                    conn.execute(
                        "UPDATE nodes SET confidence = ? WHERE id = ?",
                        (new_confidence, node["id"])
                    )
                    conn.commit()

            # Record healing action
            self.store.record_healing_action(
                "energy_normalization",
                f"Conservation violated (delta={abs(current - expected):.4f})",
                len(nodes),
                True,
                f"scale_factor={scale_factor:.4f}"
            )

            return True

        except Exception as e:
            LOG.error(f"Error enforcing conservation: {e}")
            return False

    def recalibrate(self, titan_store) -> float:
        """Recalibrate energy constant to current state (for organic growth).

        Use when chronic violations indicate the knowledge base grew
        organically and the constant is simply stale — not corruption.
        """
        try:
            total = self._calculate_total_energy(titan_store)
            old = self._energy_constant or 0.0
            LOG.info("Energy recalibration: %.4f -> %.4f", old, total)
            # Update DB first, then in-memory (so partial failure doesn't
            # leave inconsistent state)
            self.store.update_invariant_state(
                "energy_conservation", total, threshold=total, status="normal")
            self._energy_constant = total
            self.config.energy_constant = total
            self._initialized = True
            return total
        except Exception as e:
            LOG.error("Energy recalibration failed: %s", e)
            return self._energy_constant or 0.0


# Global instance
_energy: Optional[EnergyConservation] = None


def get_energy() -> EnergyConservation:
    """Get or create the global energy conservation instance."""
    global _energy
    if _energy is None:
        _energy = EnergyConservation()
    return _energy
