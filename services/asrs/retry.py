#!/usr/bin/env python3
"""
A.S.R.S. Retry Strategy
Suggests and manages alternative integration approaches.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
import logging
import json

from .config import ASRSConfig, get_asrs_config
from .reporter import FailureReport

LOG = logging.getLogger("asrs.retry")


class RetryStrategyType(Enum):
    """Types of retry strategies."""
    CONSERVATIVE = "conservative"  # Reduced parameters
    ISOLATED = "isolated"          # Separate process
    STAGED = "staged"              # Gradual rollout
    LIMITED = "limited"            # Resource limits
    MANUAL = "manual"              # Human review
    MODIFIED = "modified"          # Code modifications needed


@dataclass
class Alternative:
    """An alternative integration approach."""
    strategy: RetryStrategyType
    description: str
    params: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5  # How confident we are this will work
    requires_changes: bool = False
    suggested_changes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "strategy": self.strategy.value,
            "description": self.description,
            "params": self.params,
            "confidence": self.confidence,
            "requires_changes": self.requires_changes,
            "suggested_changes": self.suggested_changes,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Alternative":
        return cls(
            strategy=RetryStrategyType(data["strategy"]),
            description=data["description"],
            params=data.get("params", {}),
            confidence=data.get("confidence", 0.5),
            requires_changes=data.get("requires_changes", False),
            suggested_changes=data.get("suggested_changes", []),
        )


class RetryStrategy:
    """
    Analyzes failures and suggests alternative integration approaches.
    """

    def __init__(self, config: ASRSConfig = None):
        self.config = config or get_asrs_config()

    def suggest_alternatives(self, failure_report: FailureReport) -> List[Alternative]:
        """
        Analyze failure and suggest alternative approaches.

        Args:
            failure_report: The failure report to analyze

        Returns:
            List of Alternative suggestions, sorted by confidence
        """
        alternatives = []
        cause = failure_report.probable_cause.lower()

        # Memory-related failures
        if 'memory' in cause:
            alternatives.extend(self._suggest_memory_alternatives(failure_report))

        # CPU/Loop-related failures
        if 'loop' in cause or 'cpu' in cause:
            alternatives.extend(self._suggest_cpu_alternatives(failure_report))

        # Crash-related failures
        if 'crash' in cause:
            alternatives.extend(self._suggest_crash_alternatives(failure_report))

        # Error-related failures
        if 'error' in cause:
            alternatives.extend(self._suggest_error_alternatives(failure_report))

        # Deadlock-related failures
        if 'deadlock' in cause:
            alternatives.extend(self._suggest_deadlock_alternatives(failure_report))

        # Performance-related failures
        if 'performance' in cause or 'response' in cause:
            alternatives.extend(self._suggest_performance_alternatives(failure_report))

        # Always suggest these as fallbacks
        alternatives.append(Alternative(
            strategy=RetryStrategyType.STAGED,
            description="Gradual rollout: enable for 10% of operations first",
            params={"initial_percentage": 10, "increment": 20, "observation_hours": 24},
            confidence=0.6,
        ))

        alternatives.append(Alternative(
            strategy=RetryStrategyType.MANUAL,
            description="Mark for manual code review before retry",
            params={},
            confidence=0.3,
            requires_changes=True,
            suggested_changes=failure_report.recommended_actions,
        ))

        # Sort by confidence
        alternatives.sort(key=lambda a: a.confidence, reverse=True)

        # Remove duplicates
        seen = set()
        unique = []
        for alt in alternatives:
            key = (alt.strategy, alt.description)
            if key not in seen:
                seen.add(key)
                unique.append(alt)

        return unique[:5]  # Return top 5

    def _suggest_memory_alternatives(self, report: FailureReport) -> List[Alternative]:
        """Suggest alternatives for memory-related failures."""
        alternatives = []

        # Get memory ratio from diff
        memory_ratio = report.baseline_diff.get('memory_ratio', 1)

        # Limited resources
        if memory_ratio > 2:
            limit = max(256, int(512 / memory_ratio))
            alternatives.append(Alternative(
                strategy=RetryStrategyType.LIMITED,
                description=f"Apply strict memory limit ({limit}MB) and batch processing",
                params={
                    "memory_limit_mb": limit,
                    "batch_size": 50,
                    "gc_interval": 100,
                },
                confidence=0.7,
                requires_changes=True,
                suggested_changes=[
                    "Wrap main logic in memory-limited context",
                    "Process data in batches of 50 items",
                    "Call gc.collect() every 100 operations",
                ],
            ))

        # Isolated process
        alternatives.append(Alternative(
            strategy=RetryStrategyType.ISOLATED,
            description="Run in isolated subprocess with memory limit",
            params={
                "subprocess": True,
                "memory_limit_mb": 512,
                "timeout_sec": 300,
            },
            confidence=0.65,
        ))

        # Conservative
        alternatives.append(Alternative(
            strategy=RetryStrategyType.CONSERVATIVE,
            description="Use conservative parameters with frequent checkpoints",
            params={
                "chunk_size": 10,
                "checkpoint_interval": 50,
                "max_items": 1000,
            },
            confidence=0.5,
            requires_changes=True,
            suggested_changes=[
                "Add checkpointing to save progress",
                "Limit maximum items processed",
                "Use generators instead of lists",
            ],
        ))

        return alternatives

    def _suggest_cpu_alternatives(self, report: FailureReport) -> List[Alternative]:
        """Suggest alternatives for CPU-related failures."""
        alternatives = []

        # Timeout guards
        alternatives.append(Alternative(
            strategy=RetryStrategyType.LIMITED,
            description="Add strict timeout and iteration limits",
            params={
                "timeout_sec": 60,
                "max_iterations": 10000,
                "cpu_limit_percent": 80,
            },
            confidence=0.75,
            requires_changes=True,
            suggested_changes=[
                "Add timeout decorator to main function",
                "Add iteration counter with break condition",
                "Add progress callbacks for long operations",
            ],
        ))

        # Isolated with timeout
        alternatives.append(Alternative(
            strategy=RetryStrategyType.ISOLATED,
            description="Run in subprocess with hard timeout",
            params={
                "subprocess": True,
                "timeout_sec": 120,
                "kill_on_timeout": True,
            },
            confidence=0.7,
        ))

        return alternatives

    def _suggest_crash_alternatives(self, report: FailureReport) -> List[Alternative]:
        """Suggest alternatives for crash-related failures."""
        alternatives = []

        # Check if OOM-related
        memory_ratio = report.baseline_diff.get('memory_ratio', 1)
        is_oom = memory_ratio > 1.5

        if is_oom:
            alternatives.append(Alternative(
                strategy=RetryStrategyType.LIMITED,
                description="Apply memory limit to prevent OOM",
                params={
                    "memory_limit_mb": 512,
                    "oom_score_adj": 1000,
                },
                confidence=0.7,
            ))

        # Isolated process for crash containment
        alternatives.append(Alternative(
            strategy=RetryStrategyType.ISOLATED,
            description="Run in isolated process to contain crashes",
            params={
                "subprocess": True,
                "restart_on_crash": False,
                "capture_stderr": True,
            },
            confidence=0.6,
        ))

        # Conservative with error handling
        alternatives.append(Alternative(
            strategy=RetryStrategyType.CONSERVATIVE,
            description="Add comprehensive error handling",
            params={
                "catch_all_exceptions": True,
                "graceful_degradation": True,
            },
            confidence=0.5,
            requires_changes=True,
            suggested_changes=[
                "Wrap all external calls in try/except",
                "Add finally blocks for cleanup",
                "Implement graceful degradation for failures",
            ],
        ))

        return alternatives

    def _suggest_error_alternatives(self, report: FailureReport) -> List[Alternative]:
        """Suggest alternatives for error-related failures."""
        alternatives = []

        # Conservative with validation
        alternatives.append(Alternative(
            strategy=RetryStrategyType.CONSERVATIVE,
            description="Add input validation and defensive checks",
            params={
                "validate_inputs": True,
                "defensive_mode": True,
            },
            confidence=0.6,
            requires_changes=True,
            suggested_changes=[
                "Add input validation for all parameters",
                "Add type checking",
                "Add null/empty checks",
            ],
        ))

        # Staged rollout
        alternatives.append(Alternative(
            strategy=RetryStrategyType.STAGED,
            description="Gradual rollout to identify failure patterns",
            params={
                "initial_percentage": 5,
                "increment": 10,
                "observation_hours": 12,
            },
            confidence=0.55,
        ))

        return alternatives

    def _suggest_deadlock_alternatives(self, report: FailureReport) -> List[Alternative]:
        """Suggest alternatives for deadlock-related failures."""
        alternatives = []

        # Timeout on all operations
        alternatives.append(Alternative(
            strategy=RetryStrategyType.LIMITED,
            description="Add timeout to all blocking operations",
            params={
                "lock_timeout_sec": 5,
                "operation_timeout_sec": 30,
            },
            confidence=0.6,
            requires_changes=True,
            suggested_changes=[
                "Use threading.Lock with timeout",
                "Replace blocking calls with async versions",
                "Add deadlock detection logging",
            ],
        ))

        # Isolated to prevent system impact
        alternatives.append(Alternative(
            strategy=RetryStrategyType.ISOLATED,
            description="Run in isolated process to prevent system deadlock",
            params={
                "subprocess": True,
                "timeout_sec": 60,
            },
            confidence=0.65,
        ))

        return alternatives

    def _suggest_performance_alternatives(self, report: FailureReport) -> List[Alternative]:
        """Suggest alternatives for performance-related failures."""
        alternatives = []

        # Conservative with caching
        alternatives.append(Alternative(
            strategy=RetryStrategyType.CONSERVATIVE,
            description="Enable caching and reduce operation scope",
            params={
                "enable_caching": True,
                "cache_ttl_sec": 300,
                "reduced_scope": True,
            },
            confidence=0.6,
            requires_changes=True,
            suggested_changes=[
                "Add result caching for expensive operations",
                "Reduce data set size",
                "Add early termination conditions",
            ],
        ))

        # Staged
        alternatives.append(Alternative(
            strategy=RetryStrategyType.STAGED,
            description="Gradual rollout with performance monitoring",
            params={
                "initial_percentage": 10,
                "monitor_response_times": True,
                "abort_threshold_ms": 2000,
            },
            confidence=0.55,
        ))

        return alternatives

    def get_strategy_params(self, strategy: RetryStrategyType) -> Dict:
        """Get default parameters for a strategy type."""
        defaults = {
            RetryStrategyType.CONSERVATIVE: {
                "reduced_limits": True,
                "extra_validation": True,
                "verbose_logging": True,
            },
            RetryStrategyType.ISOLATED: {
                "subprocess": True,
                "timeout_sec": 300,
                "memory_limit_mb": 1024,
            },
            RetryStrategyType.STAGED: {
                "initial_percentage": 10,
                "increment": 20,
                "observation_hours": 24,
            },
            RetryStrategyType.LIMITED: {
                "memory_limit_mb": 512,
                "cpu_limit_percent": 80,
                "timeout_sec": 120,
            },
            RetryStrategyType.MANUAL: {
                "requires_approval": True,
            },
            RetryStrategyType.MODIFIED: {
                "requires_code_changes": True,
            },
        }
        return defaults.get(strategy, {})

    def apply_strategy_config(self, feature_id: int, alternative: Alternative) -> Dict:
        """
        Generate configuration for applying a retry strategy.

        Returns dict with configuration to store in database.
        """
        return {
            "feature_id": feature_id,
            "strategy": alternative.strategy.value,
            "params": alternative.params,
            "applied_at": datetime.now().isoformat(),
            "requires_changes": alternative.requires_changes,
            "suggested_changes": alternative.suggested_changes,
        }
