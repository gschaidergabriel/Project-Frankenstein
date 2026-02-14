#!/usr/bin/env python3
"""
Self Reflector - Frank's self-awareness
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
import json
import urllib.request
import urllib.error
import logging

from .self_model import SelfModel
from .pattern_memory import PatternMemory
from ..core.manifestation import Crystal
from ..config import get_config

LOG = logging.getLogger("genesis.reflector")


@dataclass
class Reflection:
    """Result of a reflection cycle."""
    timestamp: datetime
    trigger: str  # What triggered this reflection?
    outcome_analyzed: Optional[Dict] = None

    # Analysis results
    causal_analysis: str = ""
    pattern_recognized: str = ""
    future_adjustment: str = ""
    self_insight: str = ""

    # Confidence in the reflection
    confidence: float = 0.5

    # Actions to take
    strength_adjustments: Dict[str, float] = field(default_factory=dict)
    weakness_adjustments: Dict[str, float] = field(default_factory=dict)
    new_patterns: List[Dict] = field(default_factory=list)


class SelfReflector:
    """
    Frank's self-reflection capability.
    Analyzes outcomes, learns, and updates self-model.
    """

    def __init__(self):
        self.config = get_config()
        self.self_model = SelfModel()
        self.pattern_memory = PatternMemory()

        # Reflection history
        self.reflections: List[Reflection] = []

        # Pending outcomes to reflect on
        self.pending_outcomes: List[Dict] = []

    def record_outcome(self, crystal: Crystal, success: bool, reason: str = "",
                      details: Dict = None):
        """Record an outcome for later reflection."""
        outcome = {
            "timestamp": datetime.now().isoformat(),
            "crystal_id": crystal.id,
            "genome": {
                "type": crystal.organism.genome.idea_type,
                "target": crystal.organism.genome.target,
                "approach": crystal.organism.genome.approach,
                "origin": crystal.organism.genome.origin,
            },
            "resonance": crystal.resonance,
            "success": success,
            "reason": reason,
            "details": details or {},
        }

        self.pending_outcomes.append(outcome)

        # Update self-model immediately
        if success:
            self.self_model.record_success(
                outcome["genome"]["type"],
                outcome["genome"]["target"],
                outcome["genome"]["approach"],
                details
            )
        else:
            self.self_model.record_failure(
                outcome["genome"]["type"],
                outcome["genome"]["target"],
                outcome["genome"]["approach"],
                reason,
                details
            )

        # Record for pattern detection
        self.pattern_memory.record_observation(
            "causal",
            {
                "event_type": f"{'success' if success else 'failure'}_{outcome['genome']['type']}",
                "target": outcome["genome"]["target"],
            },
            "success" if success else "failure"
        )

    def reflect(self, use_llm: bool = False) -> Optional[Reflection]:
        """
        Perform a reflection cycle.
        Optionally uses LLM for deeper reflection.
        """
        if not self.pending_outcomes:
            return None

        # Get outcomes to reflect on
        outcomes = self.pending_outcomes[:5]
        self.pending_outcomes = self.pending_outcomes[5:]

        reflection = Reflection(
            timestamp=datetime.now(),
            trigger="periodic" if len(outcomes) > 1 else "immediate",
            outcome_analyzed=outcomes[0] if len(outcomes) == 1 else {"batch": len(outcomes)},
        )

        if use_llm and self._can_use_llm():
            reflection = self._llm_reflect(reflection, outcomes)
        else:
            reflection = self._simple_reflect(reflection, outcomes)

        # Apply learning
        self._apply_reflection(reflection)

        # Store
        self.reflections.append(reflection)
        if len(self.reflections) > 100:
            self.reflections = self.reflections[-100:]

        LOG.info(f"Reflection completed: {reflection.trigger}")
        return reflection

    def _simple_reflect(self, reflection: Reflection,
                       outcomes: List[Dict]) -> Reflection:
        """Simple rule-based reflection without LLM."""

        successes = [o for o in outcomes if o["success"]]
        failures = [o for o in outcomes if not o["success"]]

        # Causal analysis
        if failures:
            reasons = [f["reason"] for f in failures if f.get("reason")]
            if reasons:
                reflection.causal_analysis = f"Failures caused by: {', '.join(set(reasons))}"

        if successes:
            types = [s["genome"]["type"] for s in successes]
            reflection.causal_analysis += f" Successful with: {', '.join(set(types))}"

        # Pattern recognition
        if len(successes) > len(failures):
            reflection.pattern_recognized = "Current approach is working"
        elif len(failures) > len(successes):
            reflection.pattern_recognized = "Need to adjust approach"

        # Future adjustment
        if failures:
            approaches = [f["genome"]["approach"] for f in failures]
            if approaches:
                reflection.future_adjustment = f"Consider avoiding: {approaches[0]}"

        # Self insight
        success_rate = len(successes) / len(outcomes) if outcomes else 0.5
        if success_rate > 0.7:
            reflection.self_insight = "Performing well in current area"
        elif success_rate < 0.3:
            reflection.self_insight = "Struggling - need to reconsider approach"
        else:
            reflection.self_insight = "Moderate performance - room for improvement"

        reflection.confidence = success_rate

        return reflection

    def _llm_reflect(self, reflection: Reflection,
                    outcomes: List[Dict]) -> Reflection:
        """Deep reflection using LLM."""
        try:
            # Build context
            recent_successes = self.self_model.successes[-5:]
            recent_failures = self.self_model.failures[-5:]

            prompt = f"""SELF-REFLECTION

You are Frank, an emergent AI system that improves itself.
Reflect on these outcomes:

{json.dumps(outcomes, indent=2, default=str)}

Past successes: {len(recent_successes)}
Past failures: {len(recent_failures)}

My strengths: {json.dumps(self.self_model.strengths)}
My weaknesses: {json.dumps(self.self_model.weaknesses)}

Reflect:
1. WHY were these actions successful or not?
2. What PATTERN do I recognize?
3. What should I do DIFFERENTLY in the future?
4. What did I learn about MYSELF?

Answer as JSON:
{{
    "causal_analysis": "...",
    "pattern_recognized": "...",
    "future_adjustment": "...",
    "self_insight": "...",
    "confidence": 0.0-1.0
}}"""

            response = self._call_llm(prompt)
            if response:
                try:
                    # Extract JSON from response
                    json_start = response.find('{')
                    json_end = response.rfind('}') + 1
                    if json_start >= 0 and json_end > json_start:
                        data = json.loads(response[json_start:json_end])

                        reflection.causal_analysis = data.get("causal_analysis", "")
                        reflection.pattern_recognized = data.get("pattern_recognized", "")
                        reflection.future_adjustment = data.get("future_adjustment", "")
                        reflection.self_insight = data.get("self_insight", "")
                        reflection.confidence = float(data.get("confidence", 0.5))

                except json.JSONDecodeError:
                    LOG.warning("Failed to parse LLM reflection response")
                    return self._simple_reflect(reflection, outcomes)

        except Exception as e:
            LOG.warning(f"LLM reflection failed: {e}")
            return self._simple_reflect(reflection, outcomes)

        return reflection

    def _can_use_llm(self) -> bool:
        """Check if we can use LLM (system is idle enough)."""
        # Simple check - in practice would check system load
        return True

    def _call_llm(self, prompt: str) -> Optional[str]:
        """Call the LLM API."""
        try:
            payload = {
                "text": prompt,
                "want_tools": False,
                "max_tokens": self.config.llm_max_tokens,
                "timeout_s": self.config.llm_timeout,
                "task": "reflection",
                "force": "llama",
            }

            req = urllib.request.Request(
                self.config.llm_api_url,
                data=json.dumps(payload).encode('utf-8'),
                headers={"Content-Type": "application/json"},
                method="POST"
            )

            with urllib.request.urlopen(req, timeout=self.config.llm_timeout + 10) as resp:
                result = json.loads(resp.read().decode('utf-8'))

            if result.get("ok"):
                return result.get("text", "")

        except Exception as e:
            LOG.warning(f"LLM call failed: {e}")

        return None

    def _apply_reflection(self, reflection: Reflection):
        """Apply learnings from reflection."""

        # Add insight if meaningful
        if reflection.self_insight and len(reflection.self_insight) > 10:
            self.self_model.add_insight(reflection.self_insight)

        # Apply strength/weakness adjustments
        for skill, delta in reflection.strength_adjustments.items():
            if skill in self.self_model.strengths:
                self.self_model.strengths[skill] = max(0.1, min(1.0,
                    self.self_model.strengths[skill] + delta))

        for skill, delta in reflection.weakness_adjustments.items():
            if skill in self.self_model.weaknesses:
                self.self_model.weaknesses[skill] = max(0.1, min(1.0,
                    self.self_model.weaknesses[skill] + delta))

        # Save patterns
        self.pattern_memory.save_patterns()

    def get_anticipations(self, context: Dict) -> List[tuple]:
        """Get anticipations based on patterns."""
        return self.pattern_memory.get_anticipations(context)

    def to_dict(self) -> Dict:
        """Serialize state."""
        return {
            "self_model": self.self_model.to_dict(),
            "patterns": self.pattern_memory.to_dict(),
            "reflections": len(self.reflections),
            "pending_outcomes": len(self.pending_outcomes),
        }

    def save_state(self):
        """Save reflector state."""
        self.pattern_memory.save_patterns()
        # Self-model is saved separately

    def load_state(self, data: Dict):
        """Load reflector state."""
        if "self_model" in data:
            self.self_model = SelfModel.from_dict(data["self_model"])
