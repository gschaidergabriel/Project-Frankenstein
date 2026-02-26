#!/usr/bin/env python3
"""
Primordial Soup - The ecosystem where ideas live
=================================================

This is where the MAGIC happens. Ideas live, die,
compete, cooperate, and evolve. NO central control -
behavior EMERGES from local interactions.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import random
import logging
import threading

from .organism import IdeaOrganism, IdeaStage, IdeaGenome
from .field import MotivationalField
from ..config import GenesisConfig, get_config

LOG = logging.getLogger("genesis.soup")


@dataclass
class SoupStatistics:
    """Statistics about the soup's state."""
    total_organisms: int = 0
    seeds: int = 0
    seedlings: int = 0
    mature: int = 0
    crystals: int = 0
    births: int = 0
    deaths: int = 0
    fusions: int = 0
    mutations: int = 0
    average_energy: float = 0.0
    average_fitness: float = 0.0


class PrimordialSoup:
    """
    The ecosystem where idea organisms live.

    This is NOT a pipeline or state machine. It's a
    simulation of evolving life where behavior EMERGES.
    """

    def __init__(self, config: GenesisConfig = None):
        self.config = config or get_config()
        self.organisms: List[IdeaOrganism] = []
        self.crystals: List[IdeaOrganism] = []  # Crystallized ideas waiting

        # Statistics
        self.stats = SoupStatistics()
        self.total_births = 0
        self.total_deaths = 0

        # Thread safety
        self.lock = threading.Lock()

        # History for analysis
        self.history: List[Dict] = []

        # Persistent dedup: signatures of observations we've already seen
        # Survives across restarts via state serialization
        self._seen_signatures: set = set()

        # Periodic culling counter
        self._tick_count = 0

        LOG.info("Primordial Soup initialized")

    def seed(self, genome: IdeaGenome, energy: float = None) -> IdeaOrganism:
        """
        Add a new seed to the soup.
        Seeds come from sensors (observations, github features, etc).
        """
        if energy is None:
            energy = self.config.seed_energy

        organism = IdeaOrganism(
            genome=genome,
            energy=energy,
            stage=IdeaStage.SEED,
        )

        with self.lock:
            # Check capacity
            if len(self.organisms) >= self.config.max_organisms:
                # Remove weakest organism to make room
                self._cull_weakest()

            self.organisms.append(organism)
            self.total_births += 1
            self.stats.births += 1

        LOG.debug(f"New seed planted: {organism}")
        return organism

    def tick(self, field: MotivationalField) -> List[IdeaOrganism]:
        """
        One simulation tick. Returns newly crystallized ideas.

        This is where emergence happens through:
        1. Individual metabolism
        2. Local interactions
        3. Natural selection
        """
        new_crystals = []
        self._tick_count += 1

        # Build environment from field
        environment = {
            "available_energy": field.get_energy_for_soup(),
            "fitness_modifiers": field.get_idea_fitness_modifiers(),
            "dominant_state": field.get_dominant_state().value,
        }

        with self.lock:
            # Phase 0: Periodic culling — create space for new ideas
            if self._tick_count % 50 == 0 and len(self.organisms) > 80:
                cull_count = len(self.organisms) // 10  # Kill weakest 10%
                ranked = sorted(self.organisms,
                                key=lambda o: o.average_fitness - (o.age * 0.0001))
                for victim in ranked[:cull_count]:
                    self.organisms.remove(victim)
                    self.total_deaths += 1
                    self.stats.deaths += 1
                if cull_count > 0:
                    LOG.info(f"Periodic cull: removed {cull_count} weakest organisms")

            # Phase 1: Each organism lives its life
            actions = []
            for org in self.organisms:
                action = org.metabolize(environment)
                actions.append((org, action))

            # Phase 2: Execute actions
            deaths = []
            births = []

            for org, action in actions:
                if action == "die":
                    deaths.append(org)
                elif action == "grow":
                    org.grow()
                elif action == "crystallize":
                    org.crystallize()
                    new_crystals.append(org)
                    self.crystals.append(org)
                    deaths.append(org)  # Remove from active soup
                elif action == "reproduce":
                    if len(self.organisms) + len(births) < self.config.max_organisms:
                        child = org.reproduce()
                        births.append(child)
                elif action == "mutate":
                    org.mutate()
                    self.stats.mutations += 1

            # Remove dead
            for dead in deaths:
                if dead in self.organisms:
                    self.organisms.remove(dead)
                    if dead.stage != IdeaStage.CRYSTAL:  # Crystals aren't really dead
                        self.total_deaths += 1
                        self.stats.deaths += 1
                        LOG.debug(f"Organism died: {dead.id}")

            # Add births
            for child in births:
                self.organisms.append(child)
                self.total_births += 1
                self.stats.births += 1

            # Phase 3: Interactions between organisms
            self._process_interactions(environment)

            # Update statistics
            self._update_stats()

            # Record history
            self._record_history(environment)

        return new_crystals

    def _process_interactions(self, environment: Dict):
        """
        Process local interactions between organisms.
        This is where cooperation and competition happen.
        """
        # Only process a sample of interactions (O(n) instead of O(n²))
        if len(self.organisms) < 2:
            return

        # Random pairings for efficiency
        sample_size = min(len(self.organisms) // 2, 20)
        organisms_copy = list(self.organisms)
        random.shuffle(organisms_copy)

        for i in range(0, sample_size * 2, 2):
            if i + 1 >= len(organisms_copy):
                break

            org1 = organisms_copy[i]
            org2 = organisms_copy[i + 1]

            # Skip if either is a crystal
            if org1.stage == IdeaStage.CRYSTAL or org2.stage == IdeaStage.CRYSTAL:
                continue

            # Calculate affinity
            affinity = org1.can_fuse_with(org2)

            if affinity > self.config.fusion_affinity_threshold:
                # FUSION! Create new organism from both
                child = org1.fuse_with(org2)
                self.organisms.append(child)
                self.stats.fusions += 1
                LOG.debug(f"Fusion occurred: {org1.id} + {org2.id} = {child.id}")

            elif affinity < self.config.competition_affinity_threshold:
                # COMPETITION! They fight for resources
                org1.compete_with(org2, environment)

            else:
                # Neutral - they might form connections
                if random.random() < 0.1:
                    org1.connections.add(org2.id)
                    org2.connections.add(org1.id)

    def _cull_weakest(self):
        """Remove the weakest organism to make room."""
        if not self.organisms:
            return

        # Find organism with lowest energy * fitness
        weakest = min(self.organisms,
                     key=lambda o: o.energy * o.average_fitness)

        self.organisms.remove(weakest)
        self.total_deaths += 1
        LOG.debug(f"Culled weakest: {weakest.id}")

    def _update_stats(self):
        """Update soup statistics."""
        self.stats.total_organisms = len(self.organisms)
        self.stats.seeds = sum(1 for o in self.organisms if o.stage == IdeaStage.SEED)
        self.stats.seedlings = sum(1 for o in self.organisms if o.stage == IdeaStage.SEEDLING)
        self.stats.mature = sum(1 for o in self.organisms if o.stage == IdeaStage.MATURE)
        self.stats.crystals = len(self.crystals)

        if self.organisms:
            self.stats.average_energy = sum(o.energy for o in self.organisms) / len(self.organisms)
            self.stats.average_fitness = sum(o.average_fitness for o in self.organisms) / len(self.organisms)
        else:
            self.stats.average_energy = 0.0
            self.stats.average_fitness = 0.0

    def _record_history(self, environment: Dict):
        """Record current state for analysis."""
        self.history.append({
            "timestamp": datetime.now().isoformat(),
            "total": self.stats.total_organisms,
            "seeds": self.stats.seeds,
            "seedlings": self.stats.seedlings,
            "mature": self.stats.mature,
            "crystals": self.stats.crystals,
            "avg_energy": self.stats.average_energy,
            "avg_fitness": self.stats.average_fitness,
            "env_energy": environment.get("available_energy", 0),
        })

        # Trim history
        if len(self.history) > 1000:
            self.history = self.history[-500:]

    def get_crystals(self) -> List[IdeaOrganism]:
        """Get crystallized ideas waiting for manifestation."""
        with self.lock:
            return list(self.crystals)

    def consume_crystal(self, crystal_id: str) -> Optional[IdeaOrganism]:
        """Remove and return a crystal (for manifestation)."""
        with self.lock:
            for i, crystal in enumerate(self.crystals):
                if crystal.id == crystal_id:
                    return self.crystals.pop(i)
        return None

    def get_dominant_ideas(self, limit: int = 5) -> List[IdeaOrganism]:
        """Get the strongest ideas in the soup."""
        with self.lock:
            sorted_orgs = sorted(self.organisms,
                                key=lambda o: o.energy * o.average_fitness,
                                reverse=True)
            return sorted_orgs[:limit]

    def get_idea_types_distribution(self) -> Dict[str, int]:
        """Get distribution of idea types."""
        with self.lock:
            dist = {}
            for org in self.organisms:
                t = org.genome.idea_type
                dist[t] = dist.get(t, 0) + 1
            return dist

    # ── Noise patterns that should never enter the soup ──
    _NOISE_TARGETS = {"test", "tests/", "test_", "__pycache__", ".pyc"}
    _GENERIC_APPROACHES = {"optimization", "refactoring", "unknown"}

    def _validate_observation(self, observation: Dict) -> bool:
        """
        GATE 1: Schema validation. Observations must have substance.
        Returns True if observation is worth seeding.
        """
        target = observation.get("target", "")
        approach = observation.get("approach", "")
        detail = observation.get("detail", "")
        metric = observation.get("metric", "")
        evidence = observation.get("evidence", "")
        check = observation.get("check", "")

        # Hard reject: no target at all
        if not target or target == "unknown":
            return False

        # Hard reject: test files (low priority, not production issues)
        if any(noise in target.lower() for noise in self._NOISE_TARGETS):
            return False

        # Score the observation quality
        quality = 0

        # Has function/line specificity (not just "datei.py")?
        if ":" in target or "." in target.split("/")[-1].split(":")[0]:
            quality += 1  # e.g. "services/foo.py:bar" or "foo.py:123"

        # Has concrete approach (not just "optimization")?
        if approach and approach not in self._GENERIC_APPROACHES:
            quality += 1

        # Has metric or evidence?
        if metric or evidence or (detail and len(detail) > 10):
            quality += 1

        # Has a concrete check type from a sensor?
        if check:
            quality += 1

        # Must score at least 2 out of 4
        if quality < 2:
            LOG.debug(f"Observation rejected (quality={quality}/4): "
                     f"{observation.get('type')}/{target}/{approach}")
            return False

        return True

    def inject_observation(self, observation: Dict):
        """
        Inject an observation as a potential seed.
        Observations from sensors become seeds.

        Three filters:
        1. Schema validation (quality gate)
        2. Persistent dedup (seen-signatures set)
        3. Live organism/crystal dedup
        """
        # GATE 1: Schema validation
        if not self._validate_observation(observation):
            return

        obs_type = observation.get("type", "optimization")
        obs_target = observation.get("target", "unknown")
        obs_approach = observation.get("approach", "unknown")
        signature = f"{obs_type}/{obs_target}/{obs_approach}"

        # Dedup: check persistent signature set first (fast path)
        with self.lock:
            if signature in self._seen_signatures:
                return

            # Also check live organisms + crystals
            existing = sum(
                1 for o in self.organisms
                if o.genome.idea_type == obs_type
                and o.genome.target == obs_target
                and o.genome.approach == obs_approach
            )
            crystal_existing = sum(
                1 for c in self.crystals
                if c.genome.idea_type == obs_type
                and c.genome.target == obs_target
                and c.genome.approach == obs_approach
            )
            if existing + crystal_existing >= 1:
                self._seen_signatures.add(signature)
                return

            # Mark as seen
            self._seen_signatures.add(signature)
            # Cap the set size to prevent unbounded growth
            if len(self._seen_signatures) > 5000:
                sigs = list(self._seen_signatures)
                self._seen_signatures = set(sigs[len(sigs)//2:])

        # Create genome from observation
        _META_KEYS = ("detail", "check", "exc_type", "location", "error_count")
        genome = IdeaGenome(
            idea_type=obs_type,
            target=obs_target,
            approach=obs_approach,
            origin=observation.get("origin", "observation"),
            feature_id=observation.get("feature_id"),
            traits={
                "novelty": observation.get("novelty", random.random()),
                "complexity": observation.get("complexity", random.random() * 0.5),
                "risk": observation.get("risk", random.random() * 0.3),
                "impact": observation.get("impact", random.random()),
            },
            metadata={
                k: str(v) for k, v in observation.items()
                if k in _META_KEYS and v
            },
        )

        # Seed with energy based on observation strength
        energy = self.config.seed_energy * (1 + observation.get("strength", 0.5))
        self.seed(genome, energy)

    def to_dict(self) -> Dict:
        """Serialize soup state."""
        with self.lock:
            return {
                "organisms": [o.to_dict() for o in self.organisms],
                "crystals": [c.to_dict() for c in self.crystals],
                "stats": {
                    "total_organisms": self.stats.total_organisms,
                    "seeds": self.stats.seeds,
                    "seedlings": self.stats.seedlings,
                    "mature": self.stats.mature,
                    "crystals": self.stats.crystals,
                    "births": self.stats.births,
                    "deaths": self.stats.deaths,
                    "fusions": self.stats.fusions,
                    "mutations": self.stats.mutations,
                    "average_energy": self.stats.average_energy,
                    "average_fitness": self.stats.average_fitness,
                },
                "total_births": self.total_births,
                "total_deaths": self.total_deaths,
                "seen_signatures": list(self._seen_signatures),
            }

    def from_dict(self, data: Dict):
        """Restore soup state from dict."""
        with self.lock:
            self.organisms = [IdeaOrganism.from_dict(o) for o in data.get("organisms", [])]
            self.crystals = [IdeaOrganism.from_dict(c) for c in data.get("crystals", [])]
            self.total_births = data.get("total_births", 0)
            self.total_deaths = data.get("total_deaths", 0)
            self._seen_signatures = set(data.get("seen_signatures", []))

            stats = data.get("stats", {})
            self.stats.births = stats.get("births", 0)
            self.stats.deaths = stats.get("deaths", 0)
            self.stats.fusions = stats.get("fusions", 0)
            self.stats.mutations = stats.get("mutations", 0)

    def __repr__(self):
        return (f"PrimordialSoup(organisms={len(self.organisms)}, "
                f"crystals={len(self.crystals)}, "
                f"avg_e={self.stats.average_energy:.2f}, "
                f"avg_f={self.stats.average_fitness:.2f})")
