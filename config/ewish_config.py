#!/usr/bin/env python3
"""
E-WISH Configuration
Settings for the Emergent Wish Expression System.
"""

from pathlib import Path
from typing import Dict, Any

# Default configuration
DEFAULT_CONFIG: Dict[str, Any] = {
    # Database
    "db_path": None,   # resolved at runtime by get_config()

    # Popup settings
    "popup_width": 700,
    "popup_height": 500,

    # Expression timing
    "min_expression_interval_hours": 4,  # Min hours between wish expressions
    "max_expressions_per_day": 3,        # Max wishes expressed per day

    # Wish thresholds
    "min_intensity_to_express": 0.3,     # Min intensity to show wish
    "max_wish_age_days": 30,             # Max age before wish is abandoned

    # Category-specific decay rates
    "decay_rates": {
        "learning": 0.01,
        "capability": 0.01,
        "social": 0.03,      # Social wishes decay faster
        "curiosity": 0.02,   # Curiosity decays moderately
        "improvement": 0.01,
        "experience": 0.015,
    },

    # Sound
    "sound_enabled": True,
    "sound_volume": 0.6,

    # Generation settings
    "min_weakness_severity": 0.6,    # Min weakness to generate wish
    "min_failures_for_learning": 3,  # Min failures to generate learning wish
    "hours_for_social_wish": 72,     # Hours without interaction for social wish

    # Gaming mode
    "disable_during_gaming": True,   # Don't show during gaming

    # Debug
    "debug_mode": False,
}

# Config file path
try:
    from config.paths import AICORE_DATA
    CONFIG_FILE = AICORE_DATA / "ewish_config.json"
except ImportError:
    CONFIG_FILE = Path.home() / ".local/share/frank/ewish_config.json"

_config: Dict[str, Any] = None


def get_config() -> Dict[str, Any]:
    """Get E-WISH configuration."""
    global _config

    if _config is not None:
        return _config

    _config = DEFAULT_CONFIG.copy()

    # Resolve None paths from config.paths
    if _config.get("db_path") is None:
        try:
            from config.paths import get_db
            _config["db_path"] = str(get_db("e_wish"))
        except ImportError:
            _config["db_path"] = str(Path.home() / ".local/share/frank/db/e_wish.db")

    # Load from file if exists
    if CONFIG_FILE.exists():
        import json
        try:
            with open(CONFIG_FILE, 'r') as f:
                file_config = json.load(f)
                _config.update(file_config)
        except Exception:
            pass

    return _config


def save_config(config: Dict[str, Any] = None):
    """Save configuration to file."""
    import json

    if config is None:
        config = _config or DEFAULT_CONFIG

    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


def reset_config():
    """Reset to default configuration."""
    global _config
    _config = DEFAULT_CONFIG.copy()
    save_config(_config)
    return _config
