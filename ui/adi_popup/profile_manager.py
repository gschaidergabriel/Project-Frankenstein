#!/usr/bin/env python3
"""
ADI Profile Manager - Hardware profile storage and retrieval.

Manages per-monitor configuration profiles stored as JSON files,
identified by EDID hash for unique hardware matching.
"""

import json
import logging
import os
import fcntl
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

LOG = logging.getLogger("adi.profile_manager")

# Profile storage location
try:
    from config.paths import ADI_PROFILES_DIR
    PROFILES_DIR = ADI_PROFILES_DIR
except ImportError:
    PROFILES_DIR = Path.home() / ".local" / "share" / "frank" / "adi_profiles"


def _ensure_profiles_dir():
    """Ensure the profiles directory exists."""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)


def get_profile_path(edid_hash: str) -> Path:
    """Get the file path for a profile."""
    return PROFILES_DIR / f"{edid_hash}.json"


def load_profile(edid_hash: str) -> Optional[Dict[str, Any]]:
    """
    Load a profile by EDID hash.

    Returns None if profile doesn't exist.
    """
    profile_path = get_profile_path(edid_hash)

    if not profile_path.exists():
        LOG.debug(f"No profile found for {edid_hash}")
        return None

    try:
        with open(profile_path, 'r') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                profile = json.load(f)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        # Update last_used timestamp
        profile.setdefault("meta", {})["last_used"] = datetime.now().isoformat()
        _save_profile_atomic(profile_path, profile)

        LOG.info(f"Loaded profile for {edid_hash}")
        return profile

    except json.JSONDecodeError as e:
        LOG.error(f"Invalid JSON in profile {profile_path}: {e}")
        return None
    except Exception as e:
        LOG.error(f"Failed to load profile {profile_path}: {e}")
        return None


def save_profile(profile: Dict[str, Any]) -> bool:
    """
    Save a profile.

    Profile must contain 'edid_hash' key.
    Returns True on success.
    """
    edid_hash = profile.get("edid_hash")
    if not edid_hash:
        LOG.error("Profile missing edid_hash")
        return False

    _ensure_profiles_dir()
    profile_path = get_profile_path(edid_hash)

    # Update metadata
    profile.setdefault("meta", {})
    if "created" not in profile["meta"]:
        profile["meta"]["created"] = datetime.now().isoformat()
    profile["meta"]["last_modified"] = datetime.now().isoformat()
    profile["meta"]["last_used"] = datetime.now().isoformat()

    return _save_profile_atomic(profile_path, profile)


def _save_profile_atomic(profile_path: Path, profile: Dict[str, Any]) -> bool:
    """Save profile atomically using temp file + rename."""
    _ensure_profiles_dir()
    tmp_path = profile_path.with_suffix('.tmp')

    try:
        with open(tmp_path, 'w') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(profile, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        # Atomic rename
        tmp_path.rename(profile_path)
        LOG.info(f"Saved profile to {profile_path}")
        return True

    except Exception as e:
        LOG.error(f"Failed to save profile {profile_path}: {e}")
        # Clean up temp file
        if tmp_path.exists():
            tmp_path.unlink()
        return False


def delete_profile(edid_hash: str) -> bool:
    """Delete a profile by EDID hash."""
    profile_path = get_profile_path(edid_hash)

    if not profile_path.exists():
        LOG.warning(f"Profile not found for deletion: {edid_hash}")
        return False

    try:
        profile_path.unlink()
        LOG.info(f"Deleted profile {edid_hash}")
        return True
    except Exception as e:
        LOG.error(f"Failed to delete profile {edid_hash}: {e}")
        return False


def list_profiles() -> List[Dict[str, Any]]:
    """List all saved profiles with basic info."""
    _ensure_profiles_dir()
    profiles = []

    for profile_path in PROFILES_DIR.glob("*.json"):
        try:
            with open(profile_path, 'r') as f:
                profile = json.load(f)
                profiles.append({
                    "edid_hash": profile.get("edid_hash", profile_path.stem),
                    "monitor": profile.get("monitor", {}),
                    "created": profile.get("meta", {}).get("created"),
                    "last_used": profile.get("meta", {}).get("last_used"),
                })
        except Exception as e:
            LOG.warning(f"Failed to read profile {profile_path}: {e}")

    return profiles


def create_default_profile(monitor_info) -> Dict[str, Any]:
    """
    Create a default profile for a monitor.

    Args:
        monitor_info: MonitorInfo object from monitor_detector

    Returns:
        Dict with sensible defaults based on monitor specs.
    """
    # Calculate optimal Frank window size based on monitor
    width = monitor_info.width
    height = monitor_info.height

    # Frank window sizing logic
    if width <= 1024:
        # Small monitor (like the mini HDMI)
        frank_width = min(360, int(width * 0.4))
        frank_height = min(600, int(height * 0.85))
        font_size = 12
    elif width <= 1366:
        # Laptop-sized
        frank_width = 380
        frank_height = min(680, int(height * 0.85))
        font_size = 13
    elif width <= 1920:
        # Full HD
        frank_width = 420
        frank_height = 720
        font_size = 14
    else:
        # Large/4K
        frank_width = 480
        frank_height = 800
        font_size = 15

    # Position Frank on the left with margin
    margin = 10
    frank_x = margin
    frank_y = 38  # Below GNOME panel

    # Calculate app zone (right of Frank)
    app_x = frank_x + frank_width + margin
    app_width = width - app_x - margin
    app_height = height - 48 - margin  # Account for taskbar

    return {
        "edid_hash": monitor_info.edid_hash,
        "monitor": {
            "name": monitor_info.name,
            "manufacturer": monitor_info.manufacturer,
            "manufacturer_code": monitor_info.manufacturer_code,
            "model": monitor_info.model,
            "serial": monitor_info.serial,
            "resolution": [monitor_info.width, monitor_info.height],
            "refresh": monitor_info.refresh,
            "dpi": monitor_info.dpi,
            "physical_size_mm": [
                monitor_info.physical_width_mm,
                monitor_info.physical_height_mm
            ],
        },
        "frank_layout": {
            "x": frank_x,
            "y": frank_y,
            "width": frank_width,
            "height": frank_height,
            "font_size": font_size,
            "opacity": 0.95,
            "position": "left",  # "left" or "right"
        },
        "app_zone": {
            "x": app_x,
            "y": 0,
            "width": app_width,
            "height": app_height,
        },
        "proposals_history": [],
        "meta": {
            "created": datetime.now().isoformat(),
            "last_modified": datetime.now().isoformat(),
            "last_used": datetime.now().isoformat(),
            "user_approved": False,
            "auto_generated": True,
        }
    }


def add_proposal_to_history(
    profile: Dict[str, Any],
    source: str,
    config: Dict[str, Any],
    description: str
) -> int:
    """
    Add a configuration proposal to the profile's history.

    Args:
        profile: The profile dict to update
        source: "frank" or "user"
        config: The frank_layout config for this proposal
        description: Human-readable description

    Returns:
        The proposal ID (1-based)
    """
    history = profile.setdefault("proposals_history", [])

    proposal_id = len(history) + 1
    history.append({
        "id": proposal_id,
        "source": source,
        "config": config.copy(),
        "description": description,
        "timestamp": datetime.now().isoformat(),
    })

    return proposal_id


def get_proposal_by_id(profile: Dict[str, Any], proposal_id: int) -> Optional[Dict]:
    """Get a specific proposal from history."""
    history = profile.get("proposals_history", [])

    for proposal in history:
        if proposal.get("id") == proposal_id:
            return proposal

    return None


def get_latest_proposal(profile: Dict[str, Any]) -> Optional[Dict]:
    """Get the most recent proposal."""
    history = profile.get("proposals_history", [])
    return history[-1] if history else None


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    # Import monitor detector for testing
    from monitor_detector import get_primary_monitor

    print("=== Profile Manager Test ===\n")

    monitor = get_primary_monitor()
    print(f"Monitor: {monitor.get_display_name()}")
    print(f"EDID Hash: {monitor.edid_hash}")

    # Create default profile
    profile = create_default_profile(monitor)
    print(f"\nDefault Profile:")
    print(f"  Frank: {profile['frank_layout']['width']}x{profile['frank_layout']['height']}")
    print(f"  Position: {profile['frank_layout']['x']},{profile['frank_layout']['y']}")
    print(f"  Font Size: {profile['frank_layout']['font_size']}")

    # Test save/load
    print("\nSaving profile...")
    save_profile(profile)

    print("Loading profile...")
    loaded = load_profile(monitor.edid_hash)
    print(f"  Loaded: {loaded is not None}")

    # List profiles
    print("\nAll profiles:")
    for p in list_profiles():
        print(f"  - {p['edid_hash']}: {p['monitor'].get('model', 'Unknown')}")
