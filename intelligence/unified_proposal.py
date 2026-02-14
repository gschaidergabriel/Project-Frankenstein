#!/usr/bin/env python3
"""
Unified Proposal Schema
Central data structure for all intelligence sources.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Optional, Any
from enum import Enum


class SourceType(Enum):
    """Intelligence source types."""
    GITHUB = "github"
    TRAINING = "training"
    USER_FEEDBACK = "user_feedback"
    SELF_ANALYSIS = "self_analysis"
    PERFORMANCE = "performance"
    EXTERNAL = "external"


class ProposalCategory(Enum):
    """Proposal categories."""
    TOOL = "tool"
    OPTIMIZATION = "optimization"
    BUGFIX = "bugfix"
    FEATURE = "feature"
    INTEGRATION = "integration"
    SECURITY = "security"
    PERFORMANCE = "performance"


class ProposalStatus(Enum):
    """Proposal lifecycle status."""
    DISCOVERED = "discovered"
    ANALYZING = "analyzing"
    TESTING = "testing"
    READY = "ready"
    NOTIFIED = "notified"
    APPROVED = "approved"
    INTEGRATING = "integrating"
    INTEGRATED = "integrated"
    REJECTED = "rejected"
    REJECTED_PERMANENT = "rejected_permanent"
    EXPIRED = "expired"


class Urgency(Enum):
    """Proposal urgency levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Complexity(Enum):
    """Implementation complexity."""
    TRIVIAL = "trivial"
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


class Impact(Enum):
    """Expected impact level."""
    MINOR = "minor"
    MODERATE = "moderate"
    MAJOR = "major"
    TRANSFORMATIVE = "transformative"


@dataclass
class UnifiedProposal:
    """
    A unified improvement proposal from any intelligence source.
    Central data structure for F.I.H.
    """

    # Identity
    id: int = 0
    source_type: str = SourceType.GITHUB.value
    source_id: str = ""  # Original ID from source system

    # Classification
    category: str = ProposalCategory.TOOL.value
    name: str = ""
    description: str = ""

    # Problem & Solution
    problem_statement: str = ""
    proposed_solution: str = ""
    expected_benefit: str = ""

    # Scoring
    confidence_score: float = 0.0
    priority_score: float = 0.0
    urgency: str = Urgency.MEDIUM.value
    user_relevance: float = 0.0

    # Evidence
    evidence: List[str] = field(default_factory=list)
    related_events: List[str] = field(default_factory=list)
    correlations: List[str] = field(default_factory=list)

    # Implementation details
    complexity: str = Complexity.MODERATE.value
    estimated_impact: str = Impact.MODERATE.value
    dependencies: List[str] = field(default_factory=list)

    # Code/Implementation
    code_snippet: str = ""
    full_code: str = ""
    file_path: str = ""
    repo_name: str = ""

    # Testing
    sandbox_tested: bool = False
    sandbox_passed: bool = False
    test_output: str = ""
    test_iterations: int = 0

    # Status & Timeline
    status: str = ProposalStatus.DISCOVERED.value
    created_at: str = ""
    updated_at: str = ""
    notified_at: Optional[str] = None
    approved_at: Optional[str] = None
    integrated_at: Optional[str] = None

    # User interaction
    user_notified: bool = False
    user_approved: bool = False
    user_response: str = ""

    # Integration
    integration_path: str = ""

    # Raw source data
    source_data: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UnifiedProposal":
        """Create from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_fas_feature(cls, feature: Dict[str, Any]) -> "UnifiedProposal":
        """Create from F.A.S. extracted feature."""
        return cls(
            id=feature.get("id", 0),
            source_type=SourceType.GITHUB.value,
            source_id=f"fas_{feature.get('id', 0)}",
            category=feature.get("feature_type", ProposalCategory.TOOL.value),
            name=feature.get("name", "Unknown"),
            description=feature.get("description", ""),
            problem_statement=f"Missing capability: {feature.get('name', '')}",
            proposed_solution=f"Integrate {feature.get('feature_type', 'tool')} from {feature.get('repo_name', '')}",
            expected_benefit=f"New {feature.get('feature_type', 'functionality')} available",
            confidence_score=feature.get("confidence_score", 0.0),
            code_snippet=feature.get("code_snippet", ""),
            full_code=feature.get("full_code", ""),
            file_path=feature.get("file_path", ""),
            repo_name=feature.get("repo_name", ""),
            sandbox_tested=bool(feature.get("sandbox_tested", False)),
            sandbox_passed=bool(feature.get("sandbox_passed", False)),
            test_output=feature.get("test_output", ""),
            test_iterations=feature.get("test_iterations", 0),
            status=feature.get("integration_status", ProposalStatus.DISCOVERED.value),
            created_at=feature.get("created_at", ""),
            user_notified=bool(feature.get("user_notified", False)),
            user_approved=bool(feature.get("user_approved", False)),
            user_response=feature.get("user_response", ""),
            integration_path=feature.get("integration_path", ""),
            source_data=feature,
        )

    def update_priority(self, ranker: "ProposalRanker" = None):
        """Recalculate priority score."""
        if ranker:
            self.priority_score = ranker.calculate_priority(self)
        else:
            # Simple fallback calculation
            self.priority_score = self.confidence_score * 0.5 + self.user_relevance * 0.5
        self.updated_at = datetime.now().isoformat()

    def mark_notified(self):
        """Mark as user notified."""
        self.user_notified = True
        self.notified_at = datetime.now().isoformat()
        self.status = ProposalStatus.NOTIFIED.value
        self.updated_at = datetime.now().isoformat()

    def approve(self, response: str = ""):
        """Approve the proposal."""
        self.user_approved = True
        self.approved_at = datetime.now().isoformat()
        self.user_response = response
        self.status = ProposalStatus.APPROVED.value
        self.updated_at = datetime.now().isoformat()

    def reject(self, permanent: bool = False, response: str = ""):
        """Reject the proposal."""
        self.user_approved = False
        self.user_response = response
        self.status = ProposalStatus.REJECTED_PERMANENT.value if permanent else ProposalStatus.REJECTED.value
        self.updated_at = datetime.now().isoformat()

    def mark_integrated(self, path: str = ""):
        """Mark as integrated."""
        self.integrated_at = datetime.now().isoformat()
        self.integration_path = path
        self.status = ProposalStatus.INTEGRATED.value
        self.updated_at = datetime.now().isoformat()


@dataclass
class Correlation:
    """Represents a correlation between proposals from different sources."""
    id: int = 0
    topic: str = ""
    proposal_ids: List[int] = field(default_factory=list)
    source_types: List[str] = field(default_factory=list)
    combined_confidence: float = 0.0
    message: str = ""
    recommended_action: str = ""
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


@dataclass
class Prediction:
    """A prediction about user needs."""
    what: str = ""
    why: str = ""
    when: str = ""
    confidence: float = 0.0
    related_proposal_ids: List[int] = field(default_factory=list)
    created_at: str = ""
    acted_upon: bool = False

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
