#!/usr/bin/env python3
"""
Motivational Field - The emotional landscape
=============================================

A system of coupled oscillators representing Frank's
emotional state. Emotions influence each other through
coupling relationships.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from enum import Enum
import math
import logging

from ..config import GenesisConfig, get_config

LOG = logging.getLogger("genesis.field")


class EmotionState(Enum):
    """Dominant emotional states that can emerge."""
    CURIOUS_ACTIVE = "curious_active"          # High curiosity + drive
    FRUSTRATED_ACTIVE = "frustrated_active"    # High frustration + drive
    CONTENT_PASSIVE = "content_passive"        # High satisfaction, low drive
    BORED_PASSIVE = "bored_passive"            # High boredom, low drive
    CONCERNED_WATCHFUL = "concerned_watchful"  # High concern, moderate drive
    NEUTRAL = "neutral"                        # No strong emotion


@dataclass
class MotivationalField:
    """
    The emotional field where waves propagate and interfere.

    This is NOT a simple state machine. It's a system of
    coupled differential equations where emotions influence
    each other continuously.
    """

    # The emotion values (0.0 - 1.0)
    curiosity: float = 0.3
    frustration: float = 0.2
    satisfaction: float = 0.5
    boredom: float = 0.3
    concern: float = 0.2
    drive: float = 0.3

    # Configuration
    config: GenesisConfig = field(default_factory=get_config)

    # History for pattern detection
    history: List[Dict] = field(default_factory=list)
    max_history: int = 100

    def apply_wave_contributions(self, contributions: Dict[str, float]):
        """
        Apply wave contributions from the WaveBus.
        This is how sensory input affects the field.
        """
        for emotion, contribution in contributions.items():
            if hasattr(self, emotion):
                current = getattr(self, emotion)
                # Waves add to emotion, but with diminishing returns
                new_value = current + contribution * (1 - current * 0.5)
                setattr(self, emotion, min(1.0, max(0.0, new_value)))

    def evolve(self, dt: float = 1.0):
        """
        Evolve the field over time.

        This implements:
        1. Natural decay towards baseline
        2. Coupling between emotions
        3. Non-linear interactions
        """
        baseline = self.config.emotion_baseline
        decay_rate = self.config.emotion_decay_rate
        coupling = self.config.emotion_coupling

        # Store old values for coupling calculation
        old_values = {
            "curiosity": self.curiosity,
            "frustration": self.frustration,
            "satisfaction": self.satisfaction,
            "boredom": self.boredom,
            "concern": self.concern,
            "drive": self.drive,
        }

        # 1. Natural decay towards baseline
        for emotion in old_values:
            current = old_values[emotion]
            decay = (baseline - current) * decay_rate * dt
            new_value = current + decay
            setattr(self, emotion, new_value)

        # 2. Apply coupling (emotions influence each other)
        coupling_effects: Dict[str, float] = {e: 0.0 for e in old_values}

        for (source, target), strength in coupling.items():
            if source in old_values and target in old_values:
                source_val = old_values[source]
                # Only active if source is above threshold
                if source_val > 0.4:
                    effect = (source_val - 0.4) * strength * dt * 0.1
                    coupling_effects[target] += effect

        # Apply coupling effects
        for emotion, effect in coupling_effects.items():
            current = getattr(self, emotion)
            new_value = current + effect
            setattr(self, emotion, min(1.0, max(0.0, new_value)))

        # 2b. Saturation dampening — prevent convergence at 1.0
        # Quadratic penalty above 0.75: emotions naturally settle at 0.6-0.8
        for emotion in old_values:
            current = getattr(self, emotion)
            if current > 0.75:
                penalty = (current - 0.75) ** 2 * 2.0
                setattr(self, emotion, max(0.0, current - penalty))

        # 3. Non-linear interactions (emergent dynamics)
        self._apply_nonlinear_dynamics()

        # Record history
        self._record_history()

    def _apply_nonlinear_dynamics(self):
        """
        Apply non-linear interactions that create emergent behavior.
        These are soft constraints that create interesting dynamics.
        """
        # Frustration and satisfaction are antagonistic
        if self.frustration > 0.7 and self.satisfaction > 0.5:
            self.satisfaction *= 0.90  # Strong suppression (was 0.95)

        # Extreme boredom can flip to curiosity (looking for stimulation)
        if self.boredom > 0.8:
            self.curiosity += (self.boredom - 0.8) * 0.1
            self.boredom *= 0.93  # Stronger flip (was 0.98)

        # High drive causes exhaustion (was: amplified curiosity — positive feedback!)
        if self.drive > 0.8:
            self.drive *= 0.95  # Exhaustion at hyperdrive

        # Satisfaction is self-limiting (hedonic treadmill)
        if self.satisfaction > 0.8:
            self.satisfaction *= 0.97  # Stronger treadmill (was 0.99)

        # Clamp all values
        for emotion in ["curiosity", "frustration", "satisfaction",
                       "boredom", "concern", "drive"]:
            current = getattr(self, emotion)
            setattr(self, emotion, min(1.0, max(0.0, current)))

    def _record_history(self):
        """Record current state to history."""
        self.history.append({
            "timestamp": datetime.now().isoformat(),
            "curiosity": self.curiosity,
            "frustration": self.frustration,
            "satisfaction": self.satisfaction,
            "boredom": self.boredom,
            "concern": self.concern,
            "drive": self.drive,
            "state": self.get_dominant_state().value,
        })

        # Trim history
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]

    def get_dominant_state(self) -> EmotionState:
        """
        Determine the dominant emotional state.
        This is an EMERGENT property, not a simple max.
        """
        # Calculate composite states
        states = {
            EmotionState.CURIOUS_ACTIVE: self.curiosity * self.drive,
            EmotionState.FRUSTRATED_ACTIVE: self.frustration * self.drive,
            EmotionState.CONTENT_PASSIVE: self.satisfaction * (1 - self.drive),
            EmotionState.BORED_PASSIVE: self.boredom * (1 - self.drive),
            EmotionState.CONCERNED_WATCHFUL: self.concern * (0.5 + self.drive * 0.5),
        }

        # Find dominant
        max_state = max(states, key=states.get)
        max_value = states[max_state]

        # Must be above threshold to be considered dominant
        if max_value < 0.3:
            return EmotionState.NEUTRAL

        return max_state

    def get_activation_level(self) -> float:
        """
        Get overall activation level of the field.
        Used to determine system state (dormant/stirring/etc).
        """
        # Weighted combination of active emotions
        activation = (
            self.curiosity * 0.25 +
            self.drive * 0.25 +
            self.frustration * 0.15 +
            self.concern * 0.15 +
            (1 - self.satisfaction) * 0.1 +  # Low satisfaction increases activation
            (1 - self.boredom) * 0.1  # Low boredom (engaged) increases activation
        )
        return min(1.0, max(0.0, activation))

    def get_energy_for_soup(self) -> float:
        """
        Calculate energy available for the Primordial Soup.
        High activation = more energy for ideas to grow.
        """
        base_energy = 0.08  # Background energy (was 0.1)

        # Active states provide more energy (reduced budgets)
        state = self.get_dominant_state()
        state_bonus = {
            EmotionState.CURIOUS_ACTIVE: 0.30,       # was 0.4
            EmotionState.FRUSTRATED_ACTIVE: 0.22,    # was 0.3
            EmotionState.CONCERNED_WATCHFUL: 0.15,   # was 0.2
            EmotionState.BORED_PASSIVE: 0.10,        # was 0.15
            EmotionState.CONTENT_PASSIVE: 0.05,      # was 0.05
            EmotionState.NEUTRAL: 0.08,              # was 0.1
        }

        return base_energy + state_bonus.get(state, 0.1) * self.get_activation_level()

    def get_idea_fitness_modifiers(self) -> Dict[str, float]:
        """
        Get modifiers that affect which ideas thrive in the soup.
        Different emotional states favor different types of ideas.
        """
        return {
            "novel_ideas": self.curiosity,           # Curious → novel ideas thrive
            "problem_solving": self.frustration,     # Frustrated → problem-solving thrives
            "optimization": self.concern,            # Concerned → optimization thrives
            "exploration": self.boredom,             # Bored → exploration thrives
            "stability": self.satisfaction,          # Satisfied → stability thrives
            "action_bias": self.drive,               # Drive → actionable ideas thrive
        }

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "curiosity": self.curiosity,
            "frustration": self.frustration,
            "satisfaction": self.satisfaction,
            "boredom": self.boredom,
            "concern": self.concern,
            "drive": self.drive,
            "dominant_state": self.get_dominant_state().value,
            "activation": self.get_activation_level(),
        }

    def __repr__(self):
        return (f"MotivationalField(cur={self.curiosity:.2f}, fru={self.frustration:.2f}, "
                f"sat={self.satisfaction:.2f}, bor={self.boredom:.2f}, "
                f"con={self.concern:.2f}, dri={self.drive:.2f}, "
                f"state={self.get_dominant_state().value})")
