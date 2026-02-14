#!/usr/bin/env python3
"""
Emergent Analyzer
Finds correlations between proposals from different sources.
"""

import math
import re
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Set, Tuple
import logging

from intelligence.unified_proposal import UnifiedProposal, Correlation, SourceType

LOG = logging.getLogger("fih")


class EmergentAnalyzer:
    """
    Analyzes proposals for emergent patterns and correlations.
    When multiple sources suggest the same thing, signal is amplified.
    """

    # Keywords for topic extraction
    TOPIC_KEYWORDS = {
        "logging": ["log", "logger", "logging", "trace", "debug"],
        "caching": ["cache", "redis", "memcache", "memoize"],
        "api": ["api", "rest", "endpoint", "client", "wrapper"],
        "async": ["async", "await", "concurrent", "parallel", "queue"],
        "database": ["database", "db", "sql", "query", "orm"],
        "security": ["auth", "security", "token", "encrypt", "credential"],
        "performance": ["performance", "speed", "optimize", "fast", "slow"],
        "testing": ["test", "unittest", "pytest", "mock"],
        "config": ["config", "setting", "environment", "env"],
        "file": ["file", "path", "directory", "io"],
        "network": ["http", "socket", "request", "download", "fetch"],
        "parsing": ["parse", "json", "xml", "yaml", "format"],
        "error": ["error", "exception", "retry", "fallback", "handle"],
        "rate_limit": ["rate", "limit", "throttle", "quota"],
    }

    def __init__(self):
        pass

    def find_correlations(self, proposals: List[UnifiedProposal]) -> List[Correlation]:
        """
        Find correlations between proposals from different sources.
        Returns list of Correlation objects.
        """
        correlations = []

        # Group proposals by topic
        topic_proposals = self._group_by_topic(proposals)

        for topic, related_proposals in topic_proposals.items():
            if len(related_proposals) < 2:
                continue

            # Check if different sources agree
            sources = set(p.source_type for p in related_proposals)

            if len(sources) >= 2:
                # Multiple sources agree - create correlation
                correlation = self._create_correlation(topic, related_proposals)
                correlations.append(correlation)

                # Update proposals with correlation info
                for proposal in related_proposals:
                    if topic not in proposal.correlations:
                        proposal.correlations.append(topic)

                LOG.info(f"Found correlation: '{topic}' from {len(sources)} sources")

        return correlations

    def _group_by_topic(self, proposals: List[UnifiedProposal]) -> Dict[str, List[UnifiedProposal]]:
        """Group proposals by detected topics."""
        topic_groups = defaultdict(list)

        for proposal in proposals:
            topics = self._extract_topics(proposal)
            for topic in topics:
                topic_groups[topic].append(proposal)

        return dict(topic_groups)

    def _extract_topics(self, proposal: UnifiedProposal) -> Set[str]:
        """Extract topics from a proposal."""
        text = f"{proposal.name} {proposal.description} {proposal.problem_statement}".lower()
        topics = set()

        for topic, keywords in self.TOPIC_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text:
                    topics.add(topic)
                    break

        return topics

    def _create_correlation(self, topic: str, proposals: List[UnifiedProposal]) -> Correlation:
        """Create a Correlation object from related proposals."""
        # Calculate combined confidence (probability union)
        confidences = [p.confidence_score for p in proposals]
        combined_confidence = 1 - math.prod(1 - c for c in confidences)

        # Get unique sources
        sources = list(set(p.source_type for p in proposals))
        proposal_ids = [p.id for p in proposals]

        # Generate message
        message = self._generate_correlation_message(topic, proposals, sources)

        # Determine recommended action
        action = self._determine_action(proposals, combined_confidence)

        return Correlation(
            topic=topic,
            proposal_ids=proposal_ids,
            source_types=sources,
            combined_confidence=round(combined_confidence, 3),
            message=message,
            recommended_action=action,
        )

    def _generate_correlation_message(
        self, topic: str, proposals: List[UnifiedProposal], sources: List[str]
    ) -> str:
        """Generate a human-readable correlation message."""
        source_names = {
            SourceType.GITHUB.value: "GitHub",
            SourceType.TRAINING.value: "Training",
            SourceType.USER_FEEDBACK.value: "User",
            SourceType.SELF_ANALYSIS.value: "Self-Analysis",
            SourceType.PERFORMANCE.value: "Performance Monitor",
            SourceType.EXTERNAL.value: "External Tools",
        }

        source_str = " + ".join(source_names.get(s, s) for s in sources)
        names = [p.name for p in proposals[:3]]

        return f"Multiple sources ({source_str}) suggest improving '{topic}': {', '.join(names)}"

    def _determine_action(self, proposals: List[UnifiedProposal], confidence: float) -> str:
        """Determine recommended action based on proposals."""
        # Check if user requested something
        has_user_request = any(
            p.source_type == SourceType.USER_FEEDBACK.value for p in proposals
        )

        # Check if it's a bugfix
        has_bugfix = any(p.category == "bugfix" for p in proposals)

        # Check urgency
        has_critical = any(p.urgency == "critical" for p in proposals)

        if has_user_request:
            return "HIGH PRIORITY: User + System agree on this improvement"
        elif has_bugfix and confidence >= 0.8:
            return "CRITICAL: Multiple sources identified a bug to fix"
        elif has_critical:
            return "URGENT: Critical issue identified by multiple sources"
        elif confidence >= 0.9:
            return "STRONG SIGNAL: High confidence from multiple sources"
        else:
            return "CORRELATED: Multiple sources suggest this improvement"

    def analyze_for_predictions(self, proposals: List[UnifiedProposal]) -> List[Dict]:
        """
        Analyze proposals to predict future user needs.
        """
        predictions = []

        # Group by topic and look for patterns
        topic_proposals = self._group_by_topic(proposals)

        for topic, related in topic_proposals.items():
            if len(related) >= 3:
                # Strong pattern - user likely needs this
                avg_confidence = sum(p.confidence_score for p in related) / len(related)

                if avg_confidence >= 0.7:
                    predictions.append({
                        "what": f"Improvement in '{topic}' area",
                        "why": f"{len(related)} proposals suggest this is important",
                        "confidence": avg_confidence,
                        "related_ids": [p.id for p in related],
                    })

        return predictions

    def boost_correlated_priorities(
        self, proposals: List[UnifiedProposal], correlations: List[Correlation]
    ) -> List[UnifiedProposal]:
        """
        Boost priority scores for correlated proposals.
        """
        # Build map of proposal_id -> correlations
        correlation_map = defaultdict(list)
        for corr in correlations:
            for pid in corr.proposal_ids:
                correlation_map[pid].append(corr)

        # Boost priorities
        for proposal in proposals:
            if proposal.id in correlation_map:
                # Apply boost based on correlation strength
                corrs = correlation_map[proposal.id]
                max_confidence = max(c.combined_confidence for c in corrs)

                # Boost factor: 1.0 to 1.5 based on correlation confidence
                boost = 1.0 + (max_confidence * 0.5)
                proposal.priority_score = min(1.0, proposal.priority_score * boost)

        return proposals
