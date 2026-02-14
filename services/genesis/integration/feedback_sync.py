#!/usr/bin/env python3
"""
Feedback Sync - User decisions influence future proposals
"""

from typing import Dict, Optional
import logging

from ..core.manifestation import Crystal
from ..core.organism import IdeaOrganism

LOG = logging.getLogger("genesis.feedback_sync")


class FeedbackSync:
    """
    Tracks user approve/reject/defer decisions and builds
    preference scores that influence ManifestationGate resonance.
    """

    def __init__(self):
        self.type_scores: Dict[str, float] = {}
        self.target_scores: Dict[str, float] = {}
        self.approach_scores: Dict[str, float] = {}
        self.origin_scores: Dict[str, float] = {}
        self.total_approvals: int = 0
        self.total_rejections: int = 0
        self.total_defers: int = 0

    def record_decision(self, crystal: Crystal, decision: str):
        """Record a user decision for a crystal."""
        genome = crystal.organism.genome

        if decision == "approve":
            delta = 0.1
            self.total_approvals += 1
        elif decision == "reject":
            delta = -0.15
            self.total_rejections += 1
        elif decision == "defer":
            delta = -0.02
            self.total_defers += 1
        else:
            return

        self._adjust(self.type_scores, genome.idea_type, delta)
        self._adjust(self.target_scores, genome.target, delta)
        self._adjust(self.approach_scores, genome.approach, delta)
        self._adjust(self.origin_scores, genome.origin, delta)

        LOG.info(
            f"Feedback recorded: {decision} for {genome.idea_type}/{genome.target} "
            f"(totals: {self.total_approvals}A/{self.total_rejections}R/{self.total_defers}D)"
        )

    def get_resonance_modifier(self, organism: IdeaOrganism) -> float:
        """
        Calculate a resonance modifier based on user preferences.
        Returns a factor between 0.5 and 1.5 (default 1.0 if no data).
        """
        genome = organism.genome
        scores = []

        for store, key in [
            (self.type_scores, genome.idea_type),
            (self.target_scores, genome.target),
            (self.approach_scores, genome.approach),
            (self.origin_scores, genome.origin),
        ]:
            if key in store:
                scores.append(store[key])

        if not scores:
            return 1.0

        avg = sum(scores) / len(scores)
        # Map avg (range -1..1) to modifier (range 0.5..1.5)
        return max(0.5, min(1.5, 1.0 + avg))

    def to_dict(self) -> Dict:
        """Serialize state."""
        return {
            "type_scores": self.type_scores,
            "target_scores": self.target_scores,
            "approach_scores": self.approach_scores,
            "origin_scores": self.origin_scores,
            "total_approvals": self.total_approvals,
            "total_rejections": self.total_rejections,
            "total_defers": self.total_defers,
        }

    def from_dict(self, data: Dict):
        """Restore state from dict."""
        self.type_scores = data.get("type_scores", {})
        self.target_scores = data.get("target_scores", {})
        self.approach_scores = data.get("approach_scores", {})
        self.origin_scores = data.get("origin_scores", {})
        self.total_approvals = data.get("total_approvals", 0)
        self.total_rejections = data.get("total_rejections", 0)
        self.total_defers = data.get("total_defers", 0)

    @staticmethod
    def _adjust(store: Dict[str, float], key: str, delta: float):
        """Adjust a score, clamped to [-1.0, 1.0]."""
        current = store.get(key, 0.0)
        store[key] = max(-1.0, min(1.0, current + delta))
