#!/usr/bin/env python3
"""
ADI Configuration - Adaptive Display Intelligence settings.

Hierarchical configuration with sensible defaults and user overrides.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict

LOG = logging.getLogger("adi.config")

# Default configuration
ADI_CONFIG = {
    # Popup settings
    "popup_width": 800,
    "popup_height": 700,
    "popup_min_width": 600,
    "popup_min_height": 500,

    # Sound settings
    "sound_enabled": True,
    "sound_volume": 0.6,

    # LLM settings for chat
    "llm_url": "http://127.0.0.1:8101/v1/chat/completions",
    "llm_model": "llama-3.1-8b",
    "llm_timeout": 240,     # RLM reasons before answering
    "llm_max_tokens": 800,

    # Preview settings
    "preview_width": 52,
    "preview_height": 20,

    # Layout defaults
    "default_frank_position": "left",  # "left" or "right"
    "default_opacity": 0.95,
    "min_frank_width": 300,
    "min_frank_height": 400,
    "margin": 10,
    "panel_height": 40,  # GNOME panel

    # Font size ranges
    "font_size_min": 10,
    "font_size_max": 20,
    "font_size_default": 14,

    # Paths
    "profiles_dir": None,   # resolved at runtime by get_config()
    "sounds_dir": None,     # resolved at runtime by get_config()

    # Behavior
    "auto_show_on_new_monitor": True,
    "remember_proposals": True,
    "max_proposals_history": 20,

    # Debug
    "debug_mode": False,
}

# User config file location
USER_CONFIG_PATH = Path.home() / ".config/frank/adi_config.json"


def get_config() -> Dict[str, Any]:
    """
    Get merged configuration (defaults + user overrides).

    Returns:
        Dict with all configuration values.
    """
    config = ADI_CONFIG.copy()

    # Resolve None paths from config.paths
    if config.get("profiles_dir") is None:
        try:
            from config.paths import ADI_PROFILES_DIR
            config["profiles_dir"] = str(ADI_PROFILES_DIR)
        except ImportError:
            config["profiles_dir"] = str(Path.home() / ".local/share/frank/adi_profiles")
    if config.get("sounds_dir") is None:
        try:
            from config.paths import UI_DIR
            config["sounds_dir"] = str(UI_DIR / "adi_popup" / "sounds")
        except ImportError:
            config["sounds_dir"] = str(Path(__file__).resolve().parents[1] / "ui" / "adi_popup" / "sounds")

    # Try to load user overrides
    if USER_CONFIG_PATH.exists():
        try:
            with open(USER_CONFIG_PATH, 'r') as f:
                user_config = json.load(f)
                config.update(user_config)
                LOG.debug(f"Loaded user config from {USER_CONFIG_PATH}")
        except json.JSONDecodeError as e:
            LOG.warning(f"Invalid JSON in user config: {e}")
        except Exception as e:
            LOG.warning(f"Failed to load user config: {e}")

    return config


def save_user_config(overrides: Dict[str, Any]) -> bool:
    """
    Save user configuration overrides.

    Args:
        overrides: Dict of config values to override

    Returns:
        True on success.
    """
    try:
        USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

        # Load existing overrides
        existing = {}
        if USER_CONFIG_PATH.exists():
            with open(USER_CONFIG_PATH, 'r') as f:
                existing = json.load(f)

        # Merge
        existing.update(overrides)

        # Save
        with open(USER_CONFIG_PATH, 'w') as f:
            json.dump(existing, f, indent=2)

        LOG.info(f"Saved user config to {USER_CONFIG_PATH}")
        return True

    except Exception as e:
        LOG.error(f"Failed to save user config: {e}")
        return False


def reset_user_config() -> bool:
    """Reset user configuration to defaults."""
    if USER_CONFIG_PATH.exists():
        try:
            USER_CONFIG_PATH.unlink()
            LOG.info("Reset user config to defaults")
            return True
        except Exception as e:
            LOG.error(f"Failed to reset user config: {e}")
            return False
    return True


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    config = get_config()
    print("=== ADI Configuration ===")
    for key, value in sorted(config.items()):
        print(f"  {key}: {value}")
