#!/usr/bin/env python3
"""
Base Intelligence Source
Abstract base class for all intelligence sources.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Dict, Any, Optional
import logging

from intelligence.unified_proposal import UnifiedProposal, SourceType

LOG = logging.getLogger("fih")


class IntelligenceSource(ABC):
    """
    Abstract base class for intelligence sources.
    All sources (GitHub, Training, User Feedback, etc.) inherit from this.
    """

    # Override in subclass
    source_type: SourceType = SourceType.GITHUB
    confidence_weight: float = 1.0
    name: str = "Unknown Source"
    enabled: bool = True

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.last_scan_time: Optional[datetime] = None
        self.scan_count = 0
        self.proposals_generated = 0

    @abstractmethod
    def scan(self) -> List[UnifiedProposal]:
        """
        Scan for new proposals.
        Returns list of discovered proposals.
        """
        pass

    @abstractmethod
    def get_status(self) -> Dict[str, Any]:
        """
        Get source status.
        Returns status information.
        """
        pass

    def can_scan(self) -> tuple[bool, str]:
        """
        Check if scanning is currently possible.
        Returns (can_scan, reason).
        """
        if not self.enabled:
            return False, f"{self.name} is disabled"
        return True, "OK"

    def apply_confidence_weight(self, proposals: List[UnifiedProposal]) -> List[UnifiedProposal]:
        """Apply source-specific confidence weight to proposals."""
        for proposal in proposals:
            proposal.confidence_score *= self.confidence_weight
            proposal.confidence_score = min(1.0, proposal.confidence_score)
        return proposals

    def record_scan(self, proposals: List[UnifiedProposal]):
        """Record scan statistics."""
        self.last_scan_time = datetime.now()
        self.scan_count += 1
        self.proposals_generated += len(proposals)

    def run_scan(self) -> List[UnifiedProposal]:
        """
        Execute a full scan with logging and statistics.
        """
        can_scan, reason = self.can_scan()
        if not can_scan:
            LOG.info(f"Skipping {self.name}: {reason}")
            return []

        LOG.info(f"Starting scan: {self.name}")

        try:
            proposals = self.scan()
            proposals = self.apply_confidence_weight(proposals)
            self.record_scan(proposals)

            LOG.info(f"Scan complete: {self.name} - {len(proposals)} proposals")
            return proposals

        except Exception as e:
            LOG.error(f"Scan error in {self.name}: {e}")
            return []


class GitHubSource(IntelligenceSource):
    """
    GitHub-based intelligence source.
    Wraps the existing F.A.S. functionality.
    """

    source_type = SourceType.GITHUB
    confidence_weight = 0.9
    name = "GitHub Discovery (F.A.S.)"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self._fas = None

    def _get_fas(self):
        """Lazy load F.A.S. module."""
        if self._fas is None:
            from tools.fas_scavenger import get_fas
            self._fas = get_fas()
        return self._fas

    def scan(self) -> List[UnifiedProposal]:
        """Scan GitHub via F.A.S."""
        fas = self._get_fas()

        # Get ready features from F.A.S.
        features = fas.get_ready_features()

        # Convert to unified proposals
        proposals = []
        for feature in features:
            proposal = UnifiedProposal.from_fas_feature(feature)
            proposal.source_type = self.source_type.value
            proposals.append(proposal)

        return proposals

    def get_status(self) -> Dict[str, Any]:
        """Get F.A.S. status."""
        fas = self._get_fas()
        return fas.get_status()


class TrainingSource(IntelligenceSource):
    """
    Training-based intelligence source.
    Analyzes E-CPMM training logs for improvement opportunities.
    """

    source_type = SourceType.TRAINING
    confidence_weight = 0.85
    name = "Training Insights (E-CPMM)"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        try:
            from config.paths import TRAINING_LOG_DIR
            _default_training_log = str(TRAINING_LOG_DIR)
        except ImportError:
            _default_training_log = "/home/ai-core-node/.local/share/frank/logs/training"
        self.training_log_path = config.get(
            "training_log_path",
            _default_training_log
        )

    def scan(self) -> List[UnifiedProposal]:
        """Analyze training logs for insights."""
        proposals = []

        # TODO: Implement training log analysis
        # - Parse training session logs
        # - Identify repeated failures
        # - Detect missing tools/capabilities
        # - Generate improvement proposals

        return proposals

    def get_status(self) -> Dict[str, Any]:
        """Get training source status."""
        from pathlib import Path
        log_path = Path(self.training_log_path)
        return {
            "source": self.name,
            "log_path": str(log_path),
            "log_exists": log_path.exists(),
            "last_scan": self.last_scan_time.isoformat() if self.last_scan_time else None,
            "scan_count": self.scan_count,
        }


class UserFeedbackSource(IntelligenceSource):
    """
    User feedback intelligence source.
    Collects and analyzes user requests and feedback.
    """

    source_type = SourceType.USER_FEEDBACK
    confidence_weight = 1.0  # User requests have highest weight
    name = "User Feedback"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        try:
            from config.paths import AICORE_DATA
            _default_feedback = str(AICORE_DATA / "user_feedback.json")
        except ImportError:
            _default_feedback = str(Path.home() / ".local/share/frank/user_feedback.json")
        self.feedback_file = config.get(
            "feedback_file",
            _default_feedback
        )

    def scan(self) -> List[UnifiedProposal]:
        """Collect user feedback."""
        proposals = []

        # TODO: Implement user feedback collection
        # - Parse explicit /request commands
        # - Analyze conversation history
        # - Detect implicit wants

        return proposals

    def get_status(self) -> Dict[str, Any]:
        """Get user feedback source status."""
        return {
            "source": self.name,
            "feedback_file": self.feedback_file,
            "last_scan": self.last_scan_time.isoformat() if self.last_scan_time else None,
            "scan_count": self.scan_count,
        }


class SelfAnalysisSource(IntelligenceSource):
    """
    Self-analysis intelligence source.
    Frank analyzes his own code and performance.
    """

    source_type = SourceType.SELF_ANALYSIS
    confidence_weight = 0.7
    name = "Self Analysis"

    def scan(self) -> List[UnifiedProposal]:
        """Perform self-analysis."""
        proposals = []

        # TODO: Implement self-analysis
        # - Code quality checks
        # - Unused code detection
        # - Dependency audits
        # - Security scans

        return proposals

    def get_status(self) -> Dict[str, Any]:
        """Get self-analysis status."""
        return {
            "source": self.name,
            "last_scan": self.last_scan_time.isoformat() if self.last_scan_time else None,
            "scan_count": self.scan_count,
        }


class PerformanceSource(IntelligenceSource):
    """
    Performance monitoring intelligence source.
    Identifies performance bottlenecks and optimization opportunities.
    """

    source_type = SourceType.PERFORMANCE
    confidence_weight = 0.8
    name = "Performance Monitor"

    def scan(self) -> List[UnifiedProposal]:
        """Monitor performance metrics."""
        proposals = []

        # TODO: Implement performance monitoring
        # - Response time tracking
        # - Memory usage analysis
        # - Startup time optimization
        # - Resource efficiency

        return proposals

    def get_status(self) -> Dict[str, Any]:
        """Get performance monitor status."""
        return {
            "source": self.name,
            "last_scan": self.last_scan_time.isoformat() if self.last_scan_time else None,
            "scan_count": self.scan_count,
        }


class ExternalToolsSource(IntelligenceSource):
    """
    External tools intelligence source.
    Discovers useful external tools and integrations.
    """

    source_type = SourceType.EXTERNAL
    confidence_weight = 0.75
    name = "External Tools"

    def scan(self) -> List[UnifiedProposal]:
        """Discover external tools."""
        proposals = []

        # TODO: Implement external tool discovery
        # - MCP server discovery
        # - API catalog search
        # - Community recommendations

        return proposals

    def get_status(self) -> Dict[str, Any]:
        """Get external tools status."""
        return {
            "source": self.name,
            "last_scan": self.last_scan_time.isoformat() if self.last_scan_time else None,
            "scan_count": self.scan_count,
        }
