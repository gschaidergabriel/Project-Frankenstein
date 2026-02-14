#!/usr/bin/env python3
"""
Proposal Ranker
Intelligent prioritization of proposals based on multiple factors.
"""

import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from intelligence.unified_proposal import (
    UnifiedProposal, SourceType, ProposalCategory,
    Urgency, Impact, Complexity
)


class ProposalRanker:
    """
    Ranks proposals intelligently based on multiple factors.

    Priority Formula:
    priority = (
        confidence * 0.25 +
        user_relevance * 0.30 +
        impact * 0.20 +
        urgency * 0.15 +
        recency * 0.10
    ) * multipliers
    """

    # Weight factors
    WEIGHTS = {
        "confidence": 0.25,
        "user_relevance": 0.30,
        "impact": 0.20,
        "urgency": 0.15,
        "recency": 0.10,
    }

    # Multipliers for special conditions
    MULTIPLIERS = {
        "user_request": 1.5,
        "bugfix": 1.3,
        "training_insight": 1.2,
        "performance_critical": 1.4,
        "correlated": 1.25,
        "security": 1.35,
    }

    # Impact scores
    IMPACT_SCORES = {
        Impact.MINOR.value: 0.25,
        Impact.MODERATE.value: 0.5,
        Impact.MAJOR.value: 0.75,
        Impact.TRANSFORMATIVE.value: 1.0,
    }

    # Urgency scores
    URGENCY_SCORES = {
        Urgency.LOW.value: 0.25,
        Urgency.MEDIUM.value: 0.5,
        Urgency.HIGH.value: 0.75,
        Urgency.CRITICAL.value: 1.0,
    }

    def __init__(self, user_history: List[Dict] = None):
        """
        Initialize ranker with optional user history for relevance calculation.
        """
        self.user_history = user_history or []
        self.user_topics = self._extract_user_topics()

    def _extract_user_topics(self) -> Dict[str, float]:
        """Extract topics user has shown interest in."""
        topics = {}
        for event in self.user_history:
            for topic in event.get("topics", []):
                topics[topic] = topics.get(topic, 0) + 1

        # Normalize
        if topics:
            max_count = max(topics.values())
            topics = {k: v / max_count for k, v in topics.items()}

        return topics

    def calculate_priority(self, proposal: UnifiedProposal) -> float:
        """
        Calculate priority score for a proposal.
        Returns a value between 0.0 and 1.0 (can exceed 1.0 with multipliers).
        """
        # Base scores
        confidence = proposal.confidence_score
        impact = self._score_impact(proposal.estimated_impact)
        urgency = self._score_urgency(proposal.urgency)
        user_relevance = self._calculate_user_relevance(proposal)
        recency = self._calculate_recency(proposal.created_at)

        # Calculate base priority
        priority = (
            confidence * self.WEIGHTS["confidence"] +
            user_relevance * self.WEIGHTS["user_relevance"] +
            impact * self.WEIGHTS["impact"] +
            urgency * self.WEIGHTS["urgency"] +
            recency * self.WEIGHTS["recency"]
        )

        # Apply multipliers
        multiplier = self._calculate_multiplier(proposal)
        priority *= multiplier

        return min(1.0, round(priority, 3))

    def _score_impact(self, impact: str) -> float:
        """Convert impact level to score."""
        return self.IMPACT_SCORES.get(impact, 0.5)

    def _score_urgency(self, urgency: str) -> float:
        """Convert urgency level to score."""
        return self.URGENCY_SCORES.get(urgency, 0.5)

    def _calculate_user_relevance(self, proposal: UnifiedProposal) -> float:
        """
        Calculate how relevant this proposal is to the user.
        """
        # Direct user request = highest relevance
        if proposal.source_type == SourceType.USER_FEEDBACK.value:
            return 1.0

        # Check if user mentioned related topics
        if "user" in " ".join(proposal.evidence).lower():
            return 0.8

        # Training insight that affected user
        if proposal.source_type == SourceType.TRAINING.value:
            return 0.7

        # Check topic match with user history
        proposal_text = f"{proposal.name} {proposal.description}".lower()
        relevance = 0.3  # Base relevance

        for topic, weight in self.user_topics.items():
            if topic.lower() in proposal_text:
                relevance = max(relevance, 0.3 + weight * 0.4)

        return min(1.0, relevance)

    def _calculate_recency(self, created_at: str) -> float:
        """
        Calculate recency score (newer = higher).
        Decays over 1 week.
        """
        if not created_at:
            return 0.5

        try:
            created = datetime.fromisoformat(created_at)
            age_hours = (datetime.now() - created).total_seconds() / 3600
            # Linear decay over 168 hours (1 week)
            recency = max(0, 1 - (age_hours / 168))
            return recency
        except:
            return 0.5

    def _calculate_multiplier(self, proposal: UnifiedProposal) -> float:
        """Calculate combined multiplier based on proposal characteristics."""
        multiplier = 1.0

        # User request multiplier
        if proposal.source_type == SourceType.USER_FEEDBACK.value:
            multiplier *= self.MULTIPLIERS["user_request"]

        # Bugfix multiplier
        if proposal.category == ProposalCategory.BUGFIX.value:
            multiplier *= self.MULTIPLIERS["bugfix"]

        # Training insight multiplier
        if proposal.source_type == SourceType.TRAINING.value:
            multiplier *= self.MULTIPLIERS["training_insight"]

        # Performance critical multiplier
        if (proposal.source_type == SourceType.PERFORMANCE.value and
            proposal.urgency == Urgency.CRITICAL.value):
            multiplier *= self.MULTIPLIERS["performance_critical"]

        # Correlated proposal multiplier
        if proposal.correlations:
            multiplier *= self.MULTIPLIERS["correlated"]

        # Security multiplier
        if proposal.category == ProposalCategory.SECURITY.value:
            multiplier *= self.MULTIPLIERS["security"]

        return multiplier

    def rank_proposals(self, proposals: List[UnifiedProposal]) -> List[UnifiedProposal]:
        """
        Rank a list of proposals by priority.
        Returns sorted list (highest priority first).
        """
        for proposal in proposals:
            proposal.priority_score = self.calculate_priority(proposal)

        return sorted(proposals, key=lambda p: p.priority_score, reverse=True)

    def get_top_proposals(self, proposals: List[UnifiedProposal], n: int = 10) -> List[UnifiedProposal]:
        """Get top N proposals by priority."""
        ranked = self.rank_proposals(proposals)
        return ranked[:n]

    def explain_priority(self, proposal: UnifiedProposal) -> Dict[str, float]:
        """
        Explain the priority calculation for a proposal.
        Returns breakdown of factors.
        """
        confidence = proposal.confidence_score
        impact = self._score_impact(proposal.estimated_impact)
        urgency = self._score_urgency(proposal.urgency)
        user_relevance = self._calculate_user_relevance(proposal)
        recency = self._calculate_recency(proposal.created_at)
        multiplier = self._calculate_multiplier(proposal)

        return {
            "confidence": round(confidence * self.WEIGHTS["confidence"], 3),
            "user_relevance": round(user_relevance * self.WEIGHTS["user_relevance"], 3),
            "impact": round(impact * self.WEIGHTS["impact"], 3),
            "urgency": round(urgency * self.WEIGHTS["urgency"], 3),
            "recency": round(recency * self.WEIGHTS["recency"], 3),
            "multiplier": round(multiplier, 2),
            "final_priority": proposal.priority_score,
        }
