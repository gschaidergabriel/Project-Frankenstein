#!/usr/bin/env python3
"""
F.I.H. - Frank's Intelligence Hub
Central orchestrator for all intelligence sources.
"""

import time
from datetime import datetime
from typing import Dict, List, Optional, Any
import logging

from intelligence.unified_proposal import UnifiedProposal, Correlation, SourceType, ProposalStatus
from intelligence.hub_database import HubDatabase
from intelligence.proposal_ranker import ProposalRanker
from intelligence.emergent_analyzer import EmergentAnalyzer
from intelligence.base_source import (
    IntelligenceSource, GitHubSource, TrainingSource,
    UserFeedbackSource, SelfAnalysisSource, PerformanceSource, ExternalToolsSource
)

LOG = logging.getLogger("fih")


class IntelligenceHub:
    """
    F.I.H. - Frank's Intelligence Hub

    Central hub that:
    - Manages all intelligence sources
    - Collects and unifies proposals
    - Finds emergent correlations
    - Ranks proposals by priority
    - Provides data for the popup UI
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.db = HubDatabase()
        self.ranker = ProposalRanker()
        self.analyzer = EmergentAnalyzer()

        # Initialize sources
        self.sources: Dict[str, IntelligenceSource] = {}
        self._init_sources()

        LOG.info("F.I.H. Intelligence Hub initialized")

    def _init_sources(self):
        """Initialize all intelligence sources."""
        source_classes = [
            GitHubSource,
            TrainingSource,
            UserFeedbackSource,
            SelfAnalysisSource,
            PerformanceSource,
            ExternalToolsSource,
        ]

        for source_class in source_classes:
            try:
                source = source_class(self.config)
                self.sources[source.source_type.value] = source
                LOG.debug(f"Initialized source: {source.name}")
            except Exception as e:
                LOG.error(f"Failed to initialize {source_class.__name__}: {e}")

    def scan_all_sources(self) -> Dict[str, Any]:
        """
        Scan all enabled intelligence sources.
        Returns summary of scan results.
        """
        summary = {
            "timestamp": datetime.now().isoformat(),
            "sources_scanned": 0,
            "total_proposals": 0,
            "new_proposals": 0,
            "correlations_found": 0,
            "errors": [],
        }

        all_proposals = []

        for source_type, source in self.sources.items():
            if not source.enabled:
                continue

            start_time = time.time()
            try:
                proposals = source.run_scan()
                duration_ms = int((time.time() - start_time) * 1000)

                summary["sources_scanned"] += 1
                summary["total_proposals"] += len(proposals)

                # Save proposals to database
                for proposal in proposals:
                    proposal_id = self.db.save_proposal(proposal)
                    proposal.id = proposal_id

                all_proposals.extend(proposals)

                # Log scan
                self.db.log_scan(source_type, len(proposals), duration_ms)

            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                error_msg = f"{source.name}: {str(e)}"
                summary["errors"].append(error_msg)
                LOG.error(error_msg)
                self.db.log_scan(source_type, 0, duration_ms, success=False, error=str(e))

        # Find correlations
        if all_proposals:
            correlations = self.analyzer.find_correlations(all_proposals)
            summary["correlations_found"] = len(correlations)

            for corr in correlations:
                self.db.save_correlation(corr)

            # Boost correlated proposals
            self.analyzer.boost_correlated_priorities(all_proposals, correlations)

        # Rank all proposals
        self.ranker.rank_proposals(all_proposals)

        # Update priorities in database
        for proposal in all_proposals:
            self.db.save_proposal(proposal)

        LOG.info(f"Scan complete: {summary}")
        return summary

    def scan_source(self, source_type: str) -> List[UnifiedProposal]:
        """Scan a specific source."""
        if source_type not in self.sources:
            LOG.warning(f"Unknown source: {source_type}")
            return []

        source = self.sources[source_type]
        proposals = source.run_scan()

        for proposal in proposals:
            proposal_id = self.db.save_proposal(proposal)
            proposal.id = proposal_id

        return proposals

    def get_ready_proposals(self, min_confidence: float = 0.85) -> List[UnifiedProposal]:
        """Get proposals ready for user review."""
        proposals = self.db.get_ready_proposals(min_confidence)
        return self.ranker.rank_proposals(proposals)

    def get_proposals_by_category(self) -> Dict[str, List[UnifiedProposal]]:
        """Get proposals grouped by category for UI display."""
        proposals = self.get_ready_proposals()

        categories = {
            "correlated": [],  # HIGH PRIORITY - multiple sources agree
            "github": [],
            "training": [],
            "user_feedback": [],
            "performance": [],
            "other": [],
        }

        for proposal in proposals:
            # Check if correlated
            if proposal.correlations:
                categories["correlated"].append(proposal)
            elif proposal.source_type == SourceType.GITHUB.value:
                categories["github"].append(proposal)
            elif proposal.source_type == SourceType.TRAINING.value:
                categories["training"].append(proposal)
            elif proposal.source_type == SourceType.USER_FEEDBACK.value:
                categories["user_feedback"].append(proposal)
            elif proposal.source_type == SourceType.PERFORMANCE.value:
                categories["performance"].append(proposal)
            else:
                categories["other"].append(proposal)

        # Remove empty categories
        return {k: v for k, v in categories.items() if v}

    def approve_proposal(self, proposal_id: int, response: str = "") -> bool:
        """Approve a proposal."""
        proposal = self.db.get_proposal(proposal_id)
        if not proposal:
            return False

        proposal.approve(response)
        self.db.save_proposal(proposal)
        self.db.log_user_interaction(proposal_id, "approve", response)
        return True

    def reject_proposal(self, proposal_id: int, permanent: bool = True, response: str = "") -> bool:
        """Reject a proposal."""
        proposal = self.db.get_proposal(proposal_id)
        if not proposal:
            return False

        proposal.reject(permanent, response)
        self.db.save_proposal(proposal)
        self.db.log_user_interaction(proposal_id, "reject_permanent" if permanent else "reject", response)
        return True

    def reactivate_proposal(self, proposal_id: int) -> bool:
        """Reactivate a rejected proposal."""
        proposal = self.db.get_proposal(proposal_id)
        if not proposal:
            return False

        proposal.status = ProposalStatus.READY.value
        proposal.user_approved = False
        proposal.user_notified = False
        self.db.save_proposal(proposal)
        self.db.log_user_interaction(proposal_id, "reactivate")
        return True

    def get_statistics(self) -> Dict[str, Any]:
        """Get hub statistics."""
        stats = self.db.get_statistics()

        # Add source status
        stats["sources"] = {}
        for source_type, source in self.sources.items():
            stats["sources"][source_type] = source.get_status()

        return stats

    def get_queue_status(self) -> Dict[str, Any]:
        """Get queue status for popup trigger logic."""
        ready = self.get_ready_proposals()
        high_conf = [p for p in ready if p.confidence_score >= 0.85]

        return {
            "total_ready": len(ready),
            "high_confidence": len(high_conf),
            "by_source": {
                source_type: len([p for p in ready if p.source_type == source_type])
                for source_type in SourceType
            },
            "correlated_count": len([p for p in ready if p.correlations]),
        }

    def get_proposal_details(self, proposal_id: int) -> Optional[UnifiedProposal]:
        """Get detailed proposal information."""
        return self.db.get_proposal(proposal_id)

    def get_archived(self) -> List[UnifiedProposal]:
        """Get archived/rejected proposals."""
        return self.db.get_archived_proposals()

    def get_correlations_for_proposal(self, proposal_id: int) -> List[str]:
        """Get correlations involving a specific proposal."""
        proposal = self.db.get_proposal(proposal_id)
        if proposal:
            return proposal.correlations
        return []


# Singleton
_hub: Optional[IntelligenceHub] = None


def get_intelligence_hub() -> IntelligenceHub:
    """Get or create Intelligence Hub singleton."""
    global _hub
    if _hub is None:
        _hub = IntelligenceHub()
    return _hub


# CLI
if __name__ == "__main__":
    import argparse
    import json

    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s: %(message)s'
    )

    parser = argparse.ArgumentParser(description="F.I.H. - Frank's Intelligence Hub")
    parser.add_argument("command", choices=["scan", "status", "ready", "stats"],
                        help="Command to execute")
    parser.add_argument("--source", type=str, help="Specific source to scan")

    args = parser.parse_args()
    hub = get_intelligence_hub()

    if args.command == "scan":
        if args.source:
            proposals = hub.scan_source(args.source)
            print(f"Scanned {args.source}: {len(proposals)} proposals")
        else:
            result = hub.scan_all_sources()
            print(json.dumps(result, indent=2))

    elif args.command == "status":
        status = hub.get_queue_status()
        print(json.dumps(status, indent=2))

    elif args.command == "ready":
        proposals = hub.get_ready_proposals()
        print(f"\nReady proposals ({len(proposals)}):\n")
        for p in proposals[:10]:
            corr = " [CORRELATED]" if p.correlations else ""
            print(f"  [{p.source_type}] {p.name} ({p.confidence_score:.0%}){corr}")
            print(f"      Priority: {p.priority_score:.0%}")

    elif args.command == "stats":
        stats = hub.get_statistics()
        print(json.dumps(stats, indent=2, default=str))
