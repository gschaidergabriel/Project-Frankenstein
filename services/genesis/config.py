#!/usr/bin/env python3
"""
SENTIENT GENESIS Configuration
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional
import json
import logging

LOG = logging.getLogger("genesis.config")

# Resolve default paths via config.paths (with fallback)
try:
    from config.paths import get_db as _get_db, get_state as _get_state, AICORE_LOG as _AICORE_LOG, AICORE_ROOT as _AICORE_ROOT
    _DEFAULT_DB_PATH = _get_db("frank")
    _DEFAULT_STATE_PATH = _get_state("genesis_state")
    _DEFAULT_LOG_DIR = _AICORE_LOG / "genesis"
    _DEFAULT_CONFIG_FILE = _AICORE_ROOT / "config" / "genesis_config.json"
except ImportError:
    _DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "frank" / "db" / "frank.db"
    _DEFAULT_STATE_PATH = Path.home() / ".local" / "share" / "frank" / "state" / "genesis_state.json"
    _DEFAULT_LOG_DIR = Path.home() / ".local" / "share" / "frank" / "logs" / "genesis"
    _DEFAULT_CONFIG_FILE = Path(__file__).resolve().parents[2] / "config" / "genesis_config.json"


@dataclass
class GenesisConfig:
    """Configuration for the Genesis system."""

    # === Paths ===
    db_path: Path = field(default_factory=lambda: _DEFAULT_DB_PATH)
    state_path: Path = field(default_factory=lambda: _DEFAULT_STATE_PATH)
    log_dir: Path = field(default_factory=lambda: _DEFAULT_LOG_DIR)

    # === Timing ===
    tick_interval_dormant: float = 30.0      # Seconds between ticks when dormant
    tick_interval_stirring: float = 5.0       # Seconds between ticks when stirring
    tick_interval_awakening: float = 1.0      # Seconds between ticks when awakening
    tick_interval_active: float = 0.5         # Seconds between ticks when active

    # === Thresholds ===
    # Motivational Field
    emotion_decay_rate: float = 0.05          # How fast emotions return to baseline (was 0.01)
    emotion_baseline: float = 0.3             # Neutral emotion level

    # Soup
    max_organisms: int = 100                  # Maximum ideas in the soup
    seed_energy: float = 0.3                  # Starting energy for seeds
    metabolism_cost: float = 0.025            # Energy cost per tick (was 0.02)
    energy_cap: float = 50.0                  # Max energy per organism (prevents hoarding)
    senescence_start: int = 500               # Age (ticks) when senescence begins
    senescence_rate: float = 0.001            # Extra energy cost per tick after senescence
    growth_threshold: float = 0.6             # Energy needed to grow
    reproduction_threshold: float = 0.75      # Energy needed to reproduce (was 0.85)
    crystal_threshold: float = 0.7            # Energy needed to crystallize (was 0.9)
    mutation_rate: float = 0.05               # Chance of mutation per tick
    fusion_affinity_threshold: float = 0.8    # Affinity needed for fusion
    competition_affinity_threshold: float = 0.2  # Below this, ideas compete

    # Manifestation
    manifestation_energy: float = 0.85        # Crystal energy for manifestation
    manifestation_min_age: int = 10           # Minimum age (ticks) for manifestation
    resonance_threshold: float = 0.6          # Minimum resonance for manifestation

    # === State Transitions ===
    stirring_threshold: float = 0.5           # Accumulated activation to start stirring
    awakening_threshold: float = 0.7          # Accumulated activation to awaken
    active_threshold: float = 0.75            # Accumulated activation to become active
    dormant_timeout: int = 300                # Seconds of inactivity before going dormant

    # === Resource Limits ===
    max_cpu_for_awakening: float = 0.3        # Max system CPU to allow awakening
    max_cpu_for_active: float = 0.5           # Max system CPU to allow active state
    user_inactive_threshold: int = 300        # Seconds of user inactivity (5 min)

    # === LLM Integration ===
    llm_api_url: str = "http://127.0.0.1:8088/chat"
    llm_timeout: int = 240   # RLM reasons before answering
    llm_max_tokens: int = 800

    # === Sensors ===
    sensor_interval_system: float = 10.0      # System metrics interval
    sensor_interval_user: float = 5.0         # User activity interval
    sensor_interval_github: float = 3600.0    # GitHub echo interval (1 hour)
    sensor_interval_error: float = 30.0       # Error watching interval
    sensor_interval_news: float = 3600.0      # News echo interval (1 hour)

    # === Coupling Matrix (how emotions influence each other) ===
    emotion_coupling: Dict = field(default_factory=lambda: {
        ("curiosity", "boredom"): -0.3,
        ("curiosity", "drive"): 0.4,
        ("frustration", "drive"): 0.3,
        ("frustration", "satisfaction"): -0.5,
        ("satisfaction", "concern"): -0.4,
        ("boredom", "curiosity"): 0.2,
        ("concern", "drive"): 0.2,
        ("boredom", "drive"): -0.2,
        ("satisfaction", "boredom"): 0.1,
    })

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "db_path": str(self.db_path),
            "state_path": str(self.state_path),
            "log_dir": str(self.log_dir),
            "tick_interval_dormant": self.tick_interval_dormant,
            "tick_interval_stirring": self.tick_interval_stirring,
            "tick_interval_awakening": self.tick_interval_awakening,
            "tick_interval_active": self.tick_interval_active,
            "emotion_decay_rate": self.emotion_decay_rate,
            "emotion_baseline": self.emotion_baseline,
            "max_organisms": self.max_organisms,
            "seed_energy": self.seed_energy,
            "metabolism_cost": self.metabolism_cost,
            "growth_threshold": self.growth_threshold,
            "reproduction_threshold": self.reproduction_threshold,
            "crystal_threshold": self.crystal_threshold,
            "mutation_rate": self.mutation_rate,
            "stirring_threshold": self.stirring_threshold,
            "awakening_threshold": self.awakening_threshold,
            "active_threshold": self.active_threshold,
            "resonance_threshold": self.resonance_threshold,
            "emotion_coupling": {f"{k[0]}->{k[1]}": v for k, v in self.emotion_coupling.items()},
        }


_config: Optional[GenesisConfig] = None


def get_config() -> GenesisConfig:
    """Get or create the global config."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def load_config() -> GenesisConfig:
    """Load config from file or create default."""
    config_file = _DEFAULT_CONFIG_FILE

    if config_file.exists():
        try:
            with open(config_file) as f:
                data = json.load(f)

            # Parse coupling matrix back
            if "emotion_coupling" in data:
                coupling = {}
                for k, v in data["emotion_coupling"].items():
                    parts = k.split("->")
                    if len(parts) == 2:
                        coupling[(parts[0], parts[1])] = v
                data["emotion_coupling"] = coupling

            # Convert paths
            for key in ["db_path", "state_path", "log_dir"]:
                if key in data:
                    data[key] = Path(data[key])

            return GenesisConfig(**{k: v for k, v in data.items()
                                   if k in GenesisConfig.__dataclass_fields__})
        except Exception as e:
            LOG.warning(f"Failed to load config: {e}, using defaults")

    return GenesisConfig()


def save_config(config: GenesisConfig):
    """Save config to file."""
    config_file = _DEFAULT_CONFIG_FILE
    config_file.parent.mkdir(parents=True, exist_ok=True)

    with open(config_file, "w") as f:
        json.dump(config.to_dict(), f, indent=2)
