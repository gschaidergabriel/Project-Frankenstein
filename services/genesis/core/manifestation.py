#!/usr/bin/env python3
"""
Manifestation Gate - Where ideas become proposals
================================================

This is NOT a decision maker. It only checks if
conditions for manifestation are met. When they are,
manifestation HAPPENS - it's not "decided".
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
import logging

from .organism import IdeaOrganism, IdeaStage
from .field import MotivationalField, EmotionState
from .soup import PrimordialSoup
from ..config import GenesisConfig, get_config

# Lazy import to avoid circular dependency
_FeedbackSync = None

LOG = logging.getLogger("genesis.manifestation")


@dataclass
class Crystal:
    """
    A crystallized idea ready for manifestation.
    Contains all information needed to present to user.
    """
    id: str
    organism: IdeaOrganism

    # Manifestation readiness
    resonance: float = 0.0
    readiness: float = 0.0

    # Proposal details (generated when ready)
    title: str = ""
    description: str = ""
    approach: str = ""
    risk_assessment: str = ""
    expected_benefit: str = ""

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    source_info: Dict = field(default_factory=dict)

    def to_proposal_dict(self) -> Dict:
        """Convert to proposal format for F.A.S. popup."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "approach": self.approach,
            "risk_assessment": self.risk_assessment,
            "expected_benefit": self.expected_benefit,
            "resonance": self.resonance,
            "genome": {
                "type": self.organism.genome.idea_type,
                "target": self.organism.genome.target,
                "origin": self.organism.genome.origin,
                "feature_id": self.organism.genome.feature_id,
            },
            "energy": self.organism.energy,
            "fitness": self.organism.average_fitness,
            "age": self.organism.age,
            "source": self.source_info,
            "created_at": self.created_at.isoformat(),
        }


class ManifestationGate:
    """
    The gate through which ideas manifest.

    This does NOT decide - it only checks conditions.
    When conditions are right, manifestation occurs.
    """

    def __init__(self, config: GenesisConfig = None, feedback_sync=None):
        self.config = config or get_config()
        self.feedback_sync = feedback_sync

        # Recent manifestations (to prevent spam)
        self.recent_manifestations: List[Dict] = []
        self.cooldown_seconds = 1800  # 30 minutes between manifestations

        # Failure memory (to avoid repeating failures)
        self.failure_memory: List[str] = []  # genome signatures

        LOG.info("Manifestation Gate initialized")

    def check_manifestation(
        self,
        soup: PrimordialSoup,
        field: MotivationalField,
        environment: Dict
    ) -> Optional[Crystal]:
        """
        Check if any crystal is ready to manifest.
        Returns the crystal if conditions are met, None otherwise.
        """
        crystals = soup.get_crystals()
        if not crystals:
            return None

        # Check cooldown
        if self._is_on_cooldown():
            LOG.debug("Manifestation gate on cooldown")
            return None

        # Check environment conditions
        if not self._environment_is_ready(environment):
            LOG.debug("Environment not ready for manifestation")
            return None

        # Check emotional state
        if not self._emotional_state_is_ready(field):
            LOG.debug("Emotional state not ready for manifestation")
            return None

        # Find the best crystal
        best_crystal = None
        best_resonance = 0.0

        for organism in crystals:
            # Skip if similar idea failed recently
            if self._is_similar_to_failure(organism):
                continue

            # Calculate resonance
            resonance = self._calculate_resonance(organism, field, environment)

            if resonance > self.config.resonance_threshold and resonance > best_resonance:
                best_resonance = resonance
                best_crystal = organism

        if best_crystal:
            # Remove from soup
            soup.consume_crystal(best_crystal.id)

            # Create crystal object
            crystal = Crystal(
                id=best_crystal.id,
                organism=best_crystal,
                resonance=best_resonance,
                readiness=self._calculate_readiness(best_crystal, environment),
            )

            # Generate proposal details
            self._generate_proposal_details(crystal)

            # Record manifestation
            self._record_manifestation(crystal)

            LOG.info(f"Crystal manifesting: {crystal.id} (resonance={best_resonance:.2f})")
            return crystal

        return None

    def _is_on_cooldown(self) -> bool:
        """Check if we're in cooldown period."""
        if not self.recent_manifestations:
            return False

        last = self.recent_manifestations[-1]
        elapsed = (datetime.now() - datetime.fromisoformat(last["timestamp"])).seconds
        return elapsed < self.cooldown_seconds

    def _environment_is_ready(self, environment: Dict) -> bool:
        """Check if the environment allows manifestation."""
        # User must not be active
        if environment.get("user_active", True):
            return False

        # System must not be overloaded
        if environment.get("system_load", 0) > self.config.max_cpu_for_active:
            return False

        # Must have been idle for a while
        idle_time = environment.get("user_idle_seconds", 0)
        if idle_time < self.config.user_inactive_threshold:
            return False

        return True

    def _emotional_state_is_ready(self, field: MotivationalField) -> bool:
        """Check if emotional state supports manifestation."""
        state = field.get_dominant_state()

        # Good states for manifestation
        good_states = [
            EmotionState.CURIOUS_ACTIVE,
            EmotionState.BORED_PASSIVE,
            EmotionState.FRUSTRATED_ACTIVE,
        ]

        if state not in good_states:
            return False

        # Activation level must be high enough
        if field.get_activation_level() < 0.4:
            return False

        return True

    def _calculate_resonance(
        self,
        organism: IdeaOrganism,
        field: MotivationalField,
        environment: Dict
    ) -> float:
        """
        Calculate resonance between idea and current conditions.
        High resonance = idea fits the moment.
        """
        factors = []

        # 1. Emotional resonance
        state = field.get_dominant_state()
        genome = organism.genome

        # Curious state resonates with novel ideas
        if state == EmotionState.CURIOUS_ACTIVE:
            factors.append(genome.traits.get("novelty", 0.5))

        # Frustrated state resonates with fixes
        if state == EmotionState.FRUSTRATED_ACTIVE:
            if genome.idea_type == "fix":
                factors.append(0.8)
            else:
                factors.append(0.4)

        # Bored state resonates with exploration
        if state == EmotionState.BORED_PASSIVE:
            if genome.idea_type == "exploration":
                factors.append(0.8)
            else:
                factors.append(genome.traits.get("novelty", 0.5))

        # 2. Fitness resonance (high fitness = good resonance)
        factors.append(organism.average_fitness)

        # 3. Energy resonance (high energy = strong idea)
        factors.append(min(1.0, organism.energy))

        # 4. Age resonance (not too young, not too old)
        optimal_age = 20
        age_factor = 1 - abs(organism.age - optimal_age) / (optimal_age * 2)
        factors.append(max(0, age_factor))

        # 5. Risk resonance (low risk preferred)
        risk = genome.traits.get("risk", 0.5)
        factors.append(1 - risk)

        # 6. Origin bonus (github features get bonus)
        if genome.origin == "github" and genome.feature_id:
            factors.append(0.7)

        # 7. User preference resonance (from feedback loop)
        if self.feedback_sync:
            pref_factor = self.feedback_sync.get_resonance_modifier(organism)
            factors.append(pref_factor)

        # Calculate combined resonance (multiplicative for all factors)
        if not factors:
            return 0.0

        resonance = 1.0
        for f in factors:
            resonance *= f

        # Normalize
        resonance = resonance ** (1 / len(factors))

        # Bonus if ALL factors are good
        if all(f > 0.5 for f in factors):
            resonance *= 1.2

        return min(1.0, resonance)

    def _calculate_readiness(self, organism: IdeaOrganism, environment: Dict) -> float:
        """Calculate how ready the idea is for implementation."""
        readiness = 0.0

        # Energy level
        readiness += organism.energy * 0.3

        # Fitness
        readiness += organism.average_fitness * 0.3

        # Stability (low mutations = stable)
        stability = 1 - (organism.genome.mutations / 10)
        readiness += max(0, stability) * 0.2

        # Age (mature but not ancient)
        if 10 <= organism.age <= 50:
            readiness += 0.2

        return min(1.0, readiness)

    def _is_similar_to_failure(self, organism: IdeaOrganism) -> bool:
        """Check if this idea is similar to a recent failure."""
        signature = f"{organism.genome.idea_type}:{organism.genome.target}:{organism.genome.approach}"
        return signature in self.failure_memory

    def record_failure(self, crystal: Crystal, reason: str):
        """Record a failed manifestation to avoid repeating."""
        organism = crystal.organism
        signature = f"{organism.genome.idea_type}:{organism.genome.target}:{organism.genome.approach}"
        self.failure_memory.append(signature)

        # Limit memory
        if len(self.failure_memory) > 50:
            self.failure_memory = self.failure_memory[-50:]

        LOG.info(f"Recorded failure: {signature} - {reason}")

    def record_success(self, crystal: Crystal):
        """Record a successful manifestation."""
        LOG.info(f"Recorded success: {crystal.id}")
        # Could adjust cooldown or other parameters based on success

    def _generate_proposal_details(self, crystal: Crystal):
        """Generate human-readable proposal details."""
        genome = crystal.organism.genome

        # Title based on type and target
        type_titles = {
            "optimization": "Performance Optimization",
            "feature": "New Feature",
            "fix": "Bugfix",
            "exploration": "Exploration",
            "personality_adjustment": "Personality Evolution",
            "prompt_evolution": "Prompt Template Evolution",
        }
        crystal.title = f"{type_titles.get(genome.idea_type, 'Improvement')}: {genome.target}"

        # Description based on approach
        approach_descriptions = {
            "caching": "Implementing a caching mechanism for acceleration",
            "refactoring": "Code refactoring for better maintainability and performance",
            "new_tool": "Creating a new tool for this task",
            "config_change": "Configuration change for optimization",
            "parallel": "Parallelization for higher throughput",
            "lazy_load": "Lazy loading to reduce initialization time",
            "precompute": "Precomputation of frequently used values",
            "vector_boost": "Boost a personality vector toward a desired direction",
            "vector_dampen": "Dampen an extreme personality vector toward center",
            "prompt_modify": "Modify a prompt template section for better behavior",
        }
        crystal.approach = approach_descriptions.get(genome.approach, genome.approach)

        # Special descriptions for personality/prompt crystals
        if genome.idea_type == "personality_adjustment":
            target_vec = genome.traits.get("target_vector", genome.target)
            amount = genome.traits.get("adjustment_amount", 0.1)
            direction = "boost" if genome.approach == "vector_boost" else "dampen"
            crystal.description = (
                f"Emergent personality evolution: {direction} '{target_vec}' "
                f"vector by {amount:.2f}. "
                f"Reason: {genome.traits.get('reason', 'organic adaptation')}."
            )
        elif genome.idea_type == "prompt_evolution":
            crystal.description = (
                f"Emergent prompt template change for section '{genome.target}'. "
                f"Proposed modification: {genome.traits.get('modification', 'refinement')}."
            )
        else:
            crystal.description = (
                f"Emergent idea for improving '{genome.target}' "
                f"via {crystal.approach.lower()}. "
                f"Origin: {genome.origin}."
            )

        # Risk assessment
        risk = genome.traits.get("risk", 0.5)
        if risk < 0.3:
            crystal.risk_assessment = "Low risk - safe change"
        elif risk < 0.6:
            crystal.risk_assessment = "Medium risk - careful review recommended"
        else:
            crystal.risk_assessment = "Higher risk - extensive testing required"

        # Expected benefit
        impact = genome.traits.get("impact", 0.5)
        if impact > 0.7:
            crystal.expected_benefit = "High expected benefit"
        elif impact > 0.4:
            crystal.expected_benefit = "Moderate expected benefit"
        else:
            crystal.expected_benefit = "Incremental improvement"

        # Source info
        crystal.source_info = {
            "origin": genome.origin,
            "feature_id": genome.feature_id,
            "mutations": genome.mutations,
            "organism_age": crystal.organism.age,
        }

    def _record_manifestation(self, crystal: Crystal):
        """Record a manifestation event."""
        self.recent_manifestations.append({
            "timestamp": datetime.now().isoformat(),
            "crystal_id": crystal.id,
            "resonance": crystal.resonance,
            "genome_type": crystal.organism.genome.idea_type,
            "genome_target": crystal.organism.genome.target,
        })

        # Limit history
        if len(self.recent_manifestations) > 100:
            self.recent_manifestations = self.recent_manifestations[-100:]

    def get_recent_manifestations(self, limit: int = 10) -> List[Dict]:
        """Get recent manifestation history."""
        return self.recent_manifestations[-limit:]
