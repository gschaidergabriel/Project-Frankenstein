"""
A.D.I. - Adaptive Display Intelligence
Frank's automatic display configuration system.

Detects monitors via EDID, suggests optimal layouts,
and collaboratively configures the desktop with the user.
"""

# Lazy imports to avoid circular dependencies
def get_connected_monitors():
    from .monitor_detector import get_connected_monitors as _get
    return _get()

def get_primary_monitor():
    from .monitor_detector import get_primary_monitor as _get
    return _get()

def is_monitor_known(edid_hash: str) -> bool:
    from .monitor_detector import is_monitor_known as _check
    return _check(edid_hash)

def load_profile(edid_hash: str):
    from .profile_manager import load_profile as _load
    return _load(edid_hash)

def save_profile(profile):
    from .profile_manager import save_profile as _save
    return _save(profile)

def get_profile_path(edid_hash: str):
    from .profile_manager import get_profile_path as _get
    return _get(edid_hash)

def delete_profile(edid_hash: str):
    from .profile_manager import delete_profile as _del
    return _del(edid_hash)

def generate_preview(*args, **kwargs):
    from .layout_preview import generate_preview as _gen
    return _gen(*args, **kwargs)

__all__ = [
    "get_connected_monitors",
    "get_primary_monitor",
    "is_monitor_known",
    "load_profile",
    "save_profile",
    "get_profile_path",
    "delete_profile",
    "generate_preview",
]
