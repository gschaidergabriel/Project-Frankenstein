#!/usr/bin/env python3
"""
Self Model - Frank's understanding of himself
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
import json
from pathlib import Path
import logging

LOG = logging.getLogger("genesis.self_model")


@dataclass
class SelfModel:
    """
    Frank's self-understanding.
    What am I good at? What am I bad at?
    What have I learned?
    """

    # Perceived strengths (0-1)
    strengths: Dict[str, float] = field(default_factory=lambda: {
        "code_analysis": 0.6,
        "pattern_recognition": 0.6,
        "system_optimization": 0.5,
        "error_detection": 0.5,
        "feature_integration": 0.5,
    })

    # Perceived weaknesses (0-1, higher = more weakness)
    weaknesses: Dict[str, float] = field(default_factory=lambda: {
        "ui_design": 0.7,
        "time_estimation": 0.8,
        "complex_refactoring": 0.6,
    })

    # Success history
    successes: List[Dict] = field(default_factory=list)
    failures: List[Dict] = field(default_factory=list)

    # Learned preferences
    preferences: Dict[str, float] = field(default_factory=dict)

    # Insights
    insights: List[str] = field(default_factory=list)

    # Last update
    last_updated: Optional[datetime] = None

    def record_success(self, idea_type: str, target: str, approach: str,
                      details: Dict = None):
        """Record a successful action."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "idea_type": idea_type,
            "target": target,
            "approach": approach,
            "details": details or {},
        }
        self.successes.append(entry)

        # Keep limited history
        if len(self.successes) > 100:
            self.successes = self.successes[-100:]

        # Update strengths based on success
        self._update_from_success(idea_type, target, approach)
        self.last_updated = datetime.now()

        LOG.info(f"Recorded success: {idea_type}/{target}")

    def record_failure(self, idea_type: str, target: str, approach: str,
                      reason: str, details: Dict = None):
        """Record a failed action."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "idea_type": idea_type,
            "target": target,
            "approach": approach,
            "reason": reason,
            "details": details or {},
        }
        self.failures.append(entry)

        # Keep limited history
        if len(self.failures) > 50:
            self.failures = self.failures[-50:]

        # Update weaknesses based on failure
        self._update_from_failure(idea_type, target, approach, reason)
        self.last_updated = datetime.now()

        LOG.info(f"Recorded failure: {idea_type}/{target} - {reason}")

    def _update_from_success(self, idea_type: str, target: str, approach: str):
        """Update self-model based on success."""
        # Strengthen relevant skills
        skill_map = {
            "optimization": "system_optimization",
            "fix": "error_detection",
            "feature": "feature_integration",
            "exploration": "pattern_recognition",
        }

        skill = skill_map.get(idea_type)
        if skill and skill in self.strengths:
            self.strengths[skill] = min(1.0, self.strengths[skill] + 0.05)

        # Reduce weakness if we succeeded in weak area
        if target in self.weaknesses:
            self.weaknesses[target] = max(0.1, self.weaknesses[target] - 0.1)

        # Build preference for successful approaches
        pref_key = f"{idea_type}:{approach}"
        self.preferences[pref_key] = min(1.0, self.preferences.get(pref_key, 0.5) + 0.1)

    def _update_from_failure(self, idea_type: str, target: str,
                            approach: str, reason: str):
        """Update self-model based on failure."""
        # Slightly reduce relevant skills
        skill_map = {
            "optimization": "system_optimization",
            "fix": "error_detection",
            "feature": "feature_integration",
        }

        skill = skill_map.get(idea_type)
        if skill and skill in self.strengths:
            self.strengths[skill] = max(0.2, self.strengths[skill] - 0.02)

        # Increase weakness
        if target in self.weaknesses:
            self.weaknesses[target] = min(1.0, self.weaknesses[target] + 0.05)
        else:
            # Discover new weakness
            self.weaknesses[target] = 0.5

        # Reduce preference for failed approaches
        pref_key = f"{idea_type}:{approach}"
        self.preferences[pref_key] = max(0.0, self.preferences.get(pref_key, 0.5) - 0.15)

    def add_insight(self, insight: str):
        """Add a learned insight."""
        self.insights.append(insight)

        # Keep limited
        if len(self.insights) > 50:
            self.insights = self.insights[-50:]

        LOG.info(f"New insight: {insight[:100]}")

    def get_confidence_for_idea(self, idea_type: str, target: str,
                                approach: str) -> float:
        """
        How confident should Frank be about this type of idea?
        """
        confidence = 0.5  # Base

        # Check strengths
        skill_map = {
            "optimization": "system_optimization",
            "fix": "error_detection",
            "feature": "feature_integration",
            "exploration": "pattern_recognition",
        }
        skill = skill_map.get(idea_type)
        if skill and skill in self.strengths:
            confidence += (self.strengths[skill] - 0.5) * 0.3

        # Check weaknesses
        if target in self.weaknesses:
            confidence -= self.weaknesses[target] * 0.2

        # Check preferences
        pref_key = f"{idea_type}:{approach}"
        if pref_key in self.preferences:
            confidence += (self.preferences[pref_key] - 0.5) * 0.2

        # Check history
        similar_successes = sum(1 for s in self.successes[-20:]
                               if s["idea_type"] == idea_type)
        similar_failures = sum(1 for f in self.failures[-20:]
                              if f["idea_type"] == idea_type)

        if similar_successes + similar_failures > 0:
            success_rate = similar_successes / (similar_successes + similar_failures)
            confidence += (success_rate - 0.5) * 0.2

        return max(0.1, min(1.0, confidence))

    def should_attempt(self, idea_type: str, target: str, approach: str) -> tuple:
        """
        Should Frank attempt this type of idea?
        Returns (should_attempt, reason)
        """
        confidence = self.get_confidence_for_idea(idea_type, target, approach)

        # Check for recent failures of same type
        recent_failures = [f for f in self.failures[-10:]
                         if f["idea_type"] == idea_type and f["target"] == target]

        if len(recent_failures) >= 2:
            return False, f"Recent failures in {idea_type}/{target}"

        if confidence < 0.3:
            return False, f"Low confidence ({confidence:.2f})"

        if target in self.weaknesses and self.weaknesses[target] > 0.8:
            return False, f"Known weakness: {target}"

        return True, f"Confidence: {confidence:.2f}"

    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        return {
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "successes": self.successes[-50:],
            "failures": self.failures[-30:],
            "preferences": self.preferences,
            "insights": self.insights[-20:],
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "SelfModel":
        """Create from dictionary."""
        model = cls(
            strengths=data.get("strengths", {}),
            weaknesses=data.get("weaknesses", {}),
            successes=data.get("successes", []),
            failures=data.get("failures", []),
            preferences=data.get("preferences", {}),
            insights=data.get("insights", []),
        )
        if data.get("last_updated"):
            model.last_updated = datetime.fromisoformat(data["last_updated"])
        return model

    def get_summary(self) -> str:
        """Get a human-readable summary."""
        top_strengths = sorted(self.strengths.items(), key=lambda x: x[1], reverse=True)[:3]
        top_weaknesses = sorted(self.weaknesses.items(), key=lambda x: x[1], reverse=True)[:3]

        summary = "Self-Model Summary:\n"
        summary += f"  Top Strengths: {', '.join(f'{k}({v:.2f})' for k,v in top_strengths)}\n"
        summary += f"  Top Weaknesses: {', '.join(f'{k}({v:.2f})' for k,v in top_weaknesses)}\n"
        summary += f"  Successes: {len(self.successes)}, Failures: {len(self.failures)}\n"
        summary += f"  Insights: {len(self.insights)}\n"

        return summary
