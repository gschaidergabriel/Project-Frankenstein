#!/usr/bin/env python3
"""
Idea Organisms - Living ideas in the Primordial Soup
====================================================

Ideas are not static data structures. They are ORGANISMS
that live, compete, mutate, reproduce, and die.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional, Set
from enum import Enum
import random
import uuid
import logging
import copy

LOG = logging.getLogger("genesis.organism")


class IdeaStage(Enum):
    """Life stages of an idea organism."""
    SEED = "seed"           # Just born, fragile
    SEEDLING = "seedling"   # Growing, developing
    MATURE = "mature"       # Fully formed, stable
    CRYSTAL = "crystal"     # Crystallized, ready to manifest


@dataclass
class IdeaGenome:
    """
    The "DNA" of an idea - what kind of idea is it?
    This determines behavior and fitness.
    """
    # What type of improvement?
    idea_type: str = "optimization"  # optimization, feature, fix, exploration

    # What does it target?
    target: str = "unknown"  # response_time, memory, ui, workflow, etc.

    # How does it approach the problem?
    approach: str = "unknown"  # caching, refactoring, new_tool, config_change

    # Where did it originate?
    origin: str = "spontaneous"  # github, observation, user_pattern, spontaneous

    # Feature ID if from GitHub
    feature_id: Optional[int] = None

    # Additional traits
    traits: Dict[str, float] = field(default_factory=lambda: {
        "novelty": random.random(),      # How new/innovative
        "complexity": random.random(),   # How complex to implement
        "risk": random.random() * 0.5,   # Risk level (starts lower)
        "impact": random.random(),       # Potential impact
    })

    # Non-numeric metadata (file paths, detail strings, error context)
    metadata: Dict[str, str] = field(default_factory=dict)

    # Mutation history
    mutations: int = 0

    def mutate(self) -> "IdeaGenome":
        """Create a mutated copy of this genome."""
        new_genome = copy.deepcopy(self)
        new_genome.mutations += 1

        # Random mutation type
        mutation = random.choice(["tweak_trait", "shift_approach", "blend"])

        if mutation == "tweak_trait":
            # Slightly change a trait
            trait = random.choice(list(new_genome.traits.keys()))
            delta = random.gauss(0, 0.1)
            new_genome.traits[trait] = max(0, min(1, new_genome.traits[trait] + delta))

        elif mutation == "shift_approach":
            # Change approach slightly
            approaches = ["caching", "refactoring", "new_tool", "config_change",
                         "parallel", "lazy_load", "precompute"]
            if random.random() < 0.3:
                new_genome.approach = random.choice(approaches)

        elif mutation == "blend":
            # Random trait changes
            for trait in new_genome.traits:
                if random.random() < 0.3:
                    new_genome.traits[trait] = random.random()

        return new_genome

    def crossover(self, other: "IdeaGenome") -> "IdeaGenome":
        """Create offspring by combining two genomes."""
        child = IdeaGenome(
            idea_type=random.choice([self.idea_type, other.idea_type]),
            target=random.choice([self.target, other.target]),
            approach=random.choice([self.approach, other.approach]),
            origin="fusion",
            feature_id=self.feature_id or other.feature_id,
            traits={
                trait: random.choice([self.traits.get(trait, 0.5),
                                     other.traits.get(trait, 0.5)])
                for trait in set(self.traits) | set(other.traits)
            },
            metadata={**self.metadata, **other.metadata},
            mutations=0,
        )
        return child

    def similarity(self, other: "IdeaGenome") -> float:
        """Calculate similarity to another genome (0-1)."""
        score = 0.0
        checks = 0

        # Type match
        if self.idea_type == other.idea_type:
            score += 1
        checks += 1

        # Target match
        if self.target == other.target:
            score += 1
        checks += 1

        # Approach match
        if self.approach == other.approach:
            score += 1
        checks += 1

        # Trait similarity
        for trait in self.traits:
            if trait in other.traits:
                diff = abs(self.traits[trait] - other.traits[trait])
                score += 1 - diff
                checks += 1

        return score / max(checks, 1)


@dataclass
class IdeaOrganism:
    """
    A living idea in the Primordial Soup.

    Ideas are not just data - they have:
    - Energy (life force)
    - Stage (lifecycle)
    - Genome (traits)
    - Connections (relationships)
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    genome: IdeaGenome = field(default_factory=IdeaGenome)

    # Life state
    energy: float = 0.3
    stage: IdeaStage = IdeaStage.SEED
    age: int = 0

    # Relationships
    parent_ids: List[str] = field(default_factory=list)
    child_ids: List[str] = field(default_factory=list)
    connections: Set[str] = field(default_factory=set)

    # History
    created_at: datetime = field(default_factory=datetime.now)
    last_interaction: datetime = field(default_factory=datetime.now)

    # Fitness tracking
    fitness_history: List[float] = field(default_factory=list)
    average_fitness: float = 0.5

    def metabolize(self, environment: Dict) -> str:
        """
        One life cycle tick.
        Returns action: "survive", "grow", "reproduce", "mutate", "die"
        """
        from ..config import get_config
        config = get_config()

        # 1. Existence costs energy
        self.energy -= config.metabolism_cost

        # 2. Gain energy from environment based on fitness
        fitness = self.calculate_fitness(environment)
        self.fitness_history.append(fitness)
        if len(self.fitness_history) > 20:
            self.fitness_history = self.fitness_history[-20:]
        self.average_fitness = sum(self.fitness_history) / len(self.fitness_history)

        energy_gain = fitness * environment.get("available_energy", 0.1)
        self.energy += energy_gain

        # 3. Age
        self.age += 1

        # 4. Determine action
        if self.energy <= 0:
            return "die"

        # Can crystallize if mature and very high energy
        if (self.stage == IdeaStage.MATURE and
            self.energy > config.crystal_threshold and
            self.age > 15 and
            self.average_fitness > 0.6):
            return "crystallize"

        # Can grow if enough energy
        if self.energy > config.growth_threshold and self.can_grow():
            return "grow"

        # Can reproduce if very high energy
        if self.energy > config.reproduction_threshold:
            return "reproduce"

        # Might mutate
        if random.random() < config.mutation_rate:
            return "mutate"

        return "survive"

    def calculate_fitness(self, environment: Dict) -> float:
        """
        Calculate how well this idea fits the current environment.
        This is NATURAL SELECTION!
        """
        fitness = 0.0
        factors = 0

        modifiers = environment.get("fitness_modifiers", {})

        # Novel ideas thrive when curiosity is high
        if "novel_ideas" in modifiers:
            novelty_fit = self.genome.traits.get("novelty", 0.5) * modifiers["novel_ideas"]
            fitness += novelty_fit
            factors += 1

        # Problem-solving ideas thrive when frustration is high
        if "problem_solving" in modifiers and self.genome.idea_type == "fix":
            fitness += modifiers["problem_solving"]
            factors += 1

        # Optimization ideas thrive when concern is high
        if "optimization" in modifiers and self.genome.idea_type == "optimization":
            fitness += modifiers["optimization"]
            factors += 1

        # Exploration ideas thrive when bored
        if "exploration" in modifiers and self.genome.idea_type == "exploration":
            fitness += modifiers["exploration"]
            factors += 1

        # Actionable ideas thrive when drive is high
        if "action_bias" in modifiers:
            impact = self.genome.traits.get("impact", 0.5)
            complexity = self.genome.traits.get("complexity", 0.5)
            actionability = impact * (1 - complexity * 0.5)  # High impact, low complexity
            fitness += actionability * modifiers["action_bias"]
            factors += 1

        # Ideas from GitHub get bonus if they have high confidence
        if self.genome.origin == "github" and self.genome.feature_id:
            fitness += 0.2
            factors += 1

        # Low risk ideas are favored
        risk = self.genome.traits.get("risk", 0.5)
        fitness += (1 - risk) * 0.3
        factors += 1

        # Age penalty for seeds (they must prove themselves quickly)
        if self.stage == IdeaStage.SEED and self.age > 10:
            fitness *= 0.9

        return fitness / max(factors, 1)

    def can_grow(self) -> bool:
        """Check if organism can grow to next stage."""
        if self.stage == IdeaStage.SEED and self.age >= 3:
            return True
        if self.stage == IdeaStage.SEEDLING and self.age >= 8:
            return True
        if self.stage == IdeaStage.MATURE:
            return False  # Mature can only crystallize
        return False

    def grow(self):
        """Grow to the next stage."""
        if self.stage == IdeaStage.SEED:
            self.stage = IdeaStage.SEEDLING
            LOG.debug(f"Organism {self.id} grew to seedling")
        elif self.stage == IdeaStage.SEEDLING:
            self.stage = IdeaStage.MATURE
            LOG.debug(f"Organism {self.id} matured")

    def crystallize(self):
        """Crystallize into final form."""
        self.stage = IdeaStage.CRYSTAL
        LOG.info(f"Organism {self.id} crystallized! Genome: {self.genome.idea_type}/{self.genome.target}")

    def reproduce(self) -> "IdeaOrganism":
        """Create offspring (costs energy)."""
        self.energy *= 0.6  # Reproduction costs

        child_genome = self.genome.mutate()
        child = IdeaOrganism(
            genome=child_genome,
            energy=self.energy * 0.3,
            parent_ids=[self.id],
        )
        self.child_ids.append(child.id)

        LOG.debug(f"Organism {self.id} reproduced → {child.id}")
        return child

    def mutate(self):
        """Mutate in place."""
        self.genome = self.genome.mutate()
        LOG.debug(f"Organism {self.id} mutated")

    def can_fuse_with(self, other: "IdeaOrganism") -> float:
        """
        Calculate affinity for fusion with another organism.
        Returns affinity score (0-1).
        """
        # Similar genomes can fuse
        genome_similarity = self.genome.similarity(other.genome)

        # Both must have enough energy
        if self.energy < 0.3 or other.energy < 0.3:
            return 0.0

        # Cannot fuse with own children/parents
        if other.id in self.child_ids or other.id in self.parent_ids:
            return 0.0

        # Similar but not identical is best for fusion
        # (too similar = no benefit, too different = incompatible)
        optimal_similarity = 0.6
        similarity_score = 1 - abs(genome_similarity - optimal_similarity) / optimal_similarity

        return similarity_score * genome_similarity

    def fuse_with(self, other: "IdeaOrganism") -> "IdeaOrganism":
        """
        Fuse with another organism to create a new one.
        Both parents lose energy.
        """
        # Create child genome through crossover
        child_genome = self.genome.crossover(other.genome)

        # Child gets combined energy (with efficiency loss)
        combined_energy = (self.energy + other.energy) * 0.4

        child = IdeaOrganism(
            genome=child_genome,
            energy=combined_energy,
            parent_ids=[self.id, other.id],
            stage=IdeaStage.SEEDLING,  # Fusion creates more developed offspring
        )

        # Parents lose energy
        self.energy *= 0.5
        other.energy *= 0.5

        self.child_ids.append(child.id)
        other.child_ids.append(child.id)

        LOG.info(f"Fusion: {self.id} + {other.id} → {child.id}")
        return child

    def compete_with(self, other: "IdeaOrganism", environment: Dict):
        """
        Compete with another organism. Winner gains, loser loses.
        """
        my_fitness = self.calculate_fitness(environment)
        other_fitness = other.calculate_fitness(environment)

        if my_fitness > other_fitness:
            # I win
            self.energy += 0.05
            other.energy -= 0.08
        else:
            # They win
            other.energy += 0.05
            self.energy -= 0.08

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "genome": {
                "idea_type": self.genome.idea_type,
                "target": self.genome.target,
                "approach": self.genome.approach,
                "origin": self.genome.origin,
                "feature_id": self.genome.feature_id,
                "traits": self.genome.traits,
                "mutations": self.genome.mutations,
            },
            "energy": self.energy,
            "stage": self.stage.value,
            "age": self.age,
            "parent_ids": self.parent_ids,
            "child_ids": self.child_ids,
            "average_fitness": self.average_fitness,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "IdeaOrganism":
        """Create from dictionary."""
        genome_data = data.get("genome", {})
        genome = IdeaGenome(
            idea_type=genome_data.get("idea_type", "optimization"),
            target=genome_data.get("target", "unknown"),
            approach=genome_data.get("approach", "unknown"),
            origin=genome_data.get("origin", "spontaneous"),
            feature_id=genome_data.get("feature_id"),
            traits=genome_data.get("traits", {}),
            mutations=genome_data.get("mutations", 0),
        )

        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            genome=genome,
            energy=data.get("energy", 0.3),
            stage=IdeaStage(data.get("stage", "seed")),
            age=data.get("age", 0),
            parent_ids=data.get("parent_ids", []),
            child_ids=data.get("child_ids", []),
            average_fitness=data.get("average_fitness", 0.5),
        )

    def __repr__(self):
        return (f"Idea({self.id}, {self.stage.value}, "
                f"e={self.energy:.2f}, f={self.average_fitness:.2f}, "
                f"{self.genome.idea_type}/{self.genome.target})")
