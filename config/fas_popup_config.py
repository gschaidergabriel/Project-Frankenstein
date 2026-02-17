#!/usr/bin/env python3
"""
F.A.S. Popup System Configuration
"""

FAS_POPUP_CONFIG = {
    # ═══════════════════════════════════════════════════════
    # TRIGGER SETTINGS
    # ═══════════════════════════════════════════════════════
    "min_features_for_auto_popup": 7,
    "min_confidence_score": 0.85,
    "max_popups_per_day": 2,
    "cooldown_hours": 8,
    "feature_expiry_days": 14,

    # ═══════════════════════════════════════════════════════
    # ACTIVITY DETECTION
    # ═══════════════════════════════════════════════════════
    "mouse_idle_threshold_sec": 120,
    "cpu_busy_threshold": 50,
    "require_no_fullscreen": True,
    "require_no_video": True,
    "require_no_presentation": True,
    "preferred_hours": [9, 10, 11, 14, 15, 16, 17],
    "avoid_hours": [0, 1, 2, 3, 4, 5, 6, 22, 23],

    # ═══════════════════════════════════════════════════════
    # UI SETTINGS
    # ═══════════════════════════════════════════════════════
    "popup_width": 900,
    "popup_height": 700,
    "always_on_top": True,
    "center_on_screen": True,
    "theme": "cyberpunk",
    "show_confidence_bars": True,
    "show_use_cases": True,
    "show_personal_relevance": True,

    # ═══════════════════════════════════════════════════════
    # SOUND SETTINGS
    # ═══════════════════════════════════════════════════════
    "sound_enabled": True,
    "sound_volume": 0.6,
    "sound_on_popup": True,
    "sound_on_selection": True,
    "sound_on_integration": True,

    # ═══════════════════════════════════════════════════════
    # KEYBOARD SHORTCUTS
    # ═══════════════════════════════════════════════════════
    "global_hotkey": "super+f",
    "hotkey_enabled": True,

    # ═══════════════════════════════════════════════════════
    # ARCHIVE SETTINGS
    # ═══════════════════════════════════════════════════════
    "archive_max_items": 100,
    "archive_auto_cleanup_days": 90,

    # ═══════════════════════════════════════════════════════
    # POSTPONE SETTINGS
    # ═══════════════════════════════════════════════════════
    "postpone_hours": 8,
    "max_postpones": 3,

    # ═══════════════════════════════════════════════════════
    # PATHS
    # ═══════════════════════════════════════════════════════
    "db_path": None,      # resolved at runtime by get_config()
    "sounds_dir": None,   # resolved at runtime by get_config()
    "popup_state_file": "/tmp/fas_popup_state.json",
    "hotkey_socket": None,   # resolved at runtime by get_config()
}


def get_config():
    """Get configuration with user overrides."""
    import json
    from pathlib import Path

    config = FAS_POPUP_CONFIG.copy()

    # Resolve None paths from config.paths
    if config.get("db_path") is None:
        try:
            from config.paths import get_db
            config["db_path"] = str(get_db("fas_scavenger"))
        except ImportError:
            config["db_path"] = str(Path.home() / ".local/share/frank/db/fas_scavenger.db")
    if config.get("sounds_dir") is None:
        try:
            from config.paths import SOUNDS_DIR
            config["sounds_dir"] = str(SOUNDS_DIR)
        except ImportError:
            config["sounds_dir"] = str(Path(__file__).resolve().parents[1] / "ui" / "sounds")
    if config.get("hotkey_socket") is None:
        try:
            from config.paths import RUNTIME_DIR
            config["hotkey_socket"] = str(RUNTIME_DIR / "fas_hotkey.sock")
        except ImportError:
            import os
            config["hotkey_socket"] = f"/run/user/{os.getuid()}/frank/fas_hotkey.sock"

    # Load user overrides if exists
    user_config = Path.home() / ".config/frank/fas_popup.json"
    if user_config.exists():
        try:
            with open(user_config) as f:
                overrides = json.load(f)
                config.update(overrides)
        except:
            pass

    return config
