#!/usr/bin/env python3
"""
Invariants Configuration - The Fundamental Constants
=====================================================

These constants define the "physics" of Frank's cognitive space.
They are NOT parameters to be tuned - they are the rules of existence.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional
import json
import logging

LOG = logging.getLogger("invariants.config")

# Database paths (separate from Frank's knowledge)
try:
    from config.paths import INVARIANTS_DIR, get_db as _inv_get_db
    TITAN_PRIMARY_DB = _inv_get_db("titan")
except ImportError:
    INVARIANTS_DIR = Path.home() / ".local" / "share" / "frank" / "invariants"
    TITAN_PRIMARY_DB = Path.home() / ".local" / "share" / "frank" / "db" / "titan.db"
INVARIANTS_DB = INVARIANTS_DIR / "invariants.db"
TITAN_SHADOW_DB = INVARIANTS_DIR / "titan_shadow.db"
TITAN_VALIDATOR_DB = INVARIANTS_DIR / "titan_validator.db"
STATE_FILE = INVARIANTS_DIR / "invariants_state.json"
QUARANTINE_DIR = INVARIANTS_DIR / "quarantine"


@dataclass
class InvariantsConfig:
    """
    Configuration for the Invariants Engine.

    These are the fundamental constants of Frank's existence.
    """

    # =========================================================================
    # INVARIANT 1: ENERGY CONSERVATION
    # =========================================================================
    # Total knowledge energy is CONSTANT
    # E(W) = confidence(W) * connections(W) * age_factor(W)

    # The universal energy constant (initialized on first measurement)
    energy_constant: float = 0.0  # Set dynamically on first run

    # Energy calculation weights
    confidence_weight: float = 1.0
    connections_weight: float = 0.5
    age_factor_base: float = 0.99  # Decay per day

    # Tolerance for energy conservation (floating point margin)
    energy_tolerance: float = 0.001  # 0.1% tolerance

    # =========================================================================
    # INVARIANT 2: ENTROPY BOUND
    # =========================================================================
    # S = -sum(p(W) * log(p(W)) * contradiction_factor(W))
    # S <= S_MAX (hard ceiling)

    # Maximum allowed entropy (chaos bound)
    entropy_max: float = 100.0

    # Thresholds for consolidation modes
    entropy_soft_threshold: float = 0.7   # 70% of max -> soft consolidation
    entropy_hard_threshold: float = 0.9   # 90% of max -> hard consolidation

    # Contradiction factor scaling
    contradiction_penalty: float = 2.0

    # =========================================================================
    # INVARIANT 3: GODEL PROTECTION
    # =========================================================================
    # Invariants exist OUTSIDE Frank's knowledge space
    # He cannot see, modify, or reason about them

    # The invariants daemon runs as separate process
    # No API exposed to Frank's modules
    # Manifests only as "transaction rejected"

    # Process isolation
    separate_process: bool = True
    no_external_api: bool = True

    # =========================================================================
    # INVARIANT 4: CORE KERNEL (K_core)
    # =========================================================================
    # There always exists a non-empty, contradiction-free subset K_core

    # Minimum core size (always at least N elements)
    min_core_size: int = 10

    # Core protection threshold (protect when entropy above this)
    core_protection_entropy: float = 0.5

    # Core selection criteria weights
    core_energy_weight: float = 0.4
    core_connections_weight: float = 0.3
    core_consistency_weight: float = 0.2
    core_age_weight: float = 0.1

    # =========================================================================
    # TRIPLE REALITY REDUNDANCY
    # =========================================================================
    # Three parallel realities for convergence detection

    # Convergence threshold (epsilon)
    convergence_epsilon: float = 0.05  # 5% divergence tolerance

    # Maximum divergence attempts before quarantine
    max_divergence_attempts: int = 3

    # Rollback cooldown (seconds)
    rollback_cooldown: int = 60

    # Shadow sync interval (seconds)
    shadow_sync_interval: int = 30

    # Random seeds for parallel realities
    seed_primary: int = 42
    seed_shadow: int = 137
    seed_validator: int = 2718

    # =========================================================================
    # AUTONOMOUS SELF-HEALING
    # =========================================================================

    # Check interval (seconds)
    check_interval: float = 5.0

    # Soft consolidation parameters
    soft_consolidation_rate: float = 0.1  # Resolve 10% of conflicts per cycle

    # Hard consolidation parameters
    hard_consolidation_timeout: int = 300  # 5 minutes max
    pause_inputs_during_hard: bool = True

    # =========================================================================
    # QUARANTINE DIMENSION
    # =========================================================================

    # Maximum quarantine age (days) before permanent deletion
    quarantine_max_age_days: int = 30

    # Quarantine review interval (hours)
    quarantine_review_interval: int = 24

    # Maximum quarantine size (items)
    quarantine_max_size: int = 1000

    # =========================================================================
    # MONITORING & LOGGING
    # =========================================================================

    # Log level for invariants (separate from Frank's logs)
    log_level: str = "INFO"

    # Metrics collection interval (seconds)
    metrics_interval: float = 10.0

    # State persistence interval (seconds)
    state_save_interval: int = 60

    # =========================================================================
    # DATABASE PATHS
    # =========================================================================

    invariants_db: Path = field(default_factory=lambda: INVARIANTS_DB)
    titan_primary: Path = field(default_factory=lambda: TITAN_PRIMARY_DB)
    titan_shadow: Path = field(default_factory=lambda: TITAN_SHADOW_DB)
    titan_validator: Path = field(default_factory=lambda: TITAN_VALIDATOR_DB)
    state_file: Path = field(default_factory=lambda: STATE_FILE)
    quarantine_dir: Path = field(default_factory=lambda: QUARANTINE_DIR)

    def __post_init__(self):
        """Ensure directories exist."""
        INVARIANTS_DIR.mkdir(parents=True, exist_ok=True)
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> Dict:
        """Serialize config to dict."""
        return {
            "energy_constant": self.energy_constant,
            "energy_tolerance": self.energy_tolerance,
            "entropy_max": self.entropy_max,
            "entropy_soft_threshold": self.entropy_soft_threshold,
            "entropy_hard_threshold": self.entropy_hard_threshold,
            "min_core_size": self.min_core_size,
            "convergence_epsilon": self.convergence_epsilon,
            "max_divergence_attempts": self.max_divergence_attempts,
            "check_interval": self.check_interval,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "InvariantsConfig":
        """Create config from dict."""
        config = cls()
        for key, value in data.items():
            if hasattr(config, key):
                setattr(config, key, value)
        return config

    def save(self, path: Path = None):
        """Save config to file."""
        path = path or (INVARIANTS_DIR / "config.json")
        path.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: Path = None) -> "InvariantsConfig":
        """Load config from file."""
        path = path or (INVARIANTS_DIR / "config.json")
        if path.exists():
            data = json.loads(path.read_text())
            return cls.from_dict(data)
        return cls()


# Global config instance
_config: Optional[InvariantsConfig] = None


def get_config() -> InvariantsConfig:
    """Get or create the global config instance."""
    global _config
    if _config is None:
        _config = InvariantsConfig.load()
    return _config


def reset_config():
    """Reset config to defaults."""
    global _config
    _config = InvariantsConfig()
