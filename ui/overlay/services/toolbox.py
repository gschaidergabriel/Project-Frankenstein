"""Toolbox / filesystem / app-registry / core-awareness helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from overlay.constants import LOG, TOOLBOX_BASE, CORE_BASE, DESKTOP_ACTION_URL, FORBIDDEN_PATH_PREFIXES
from overlay.http_helpers import _http_get_json, _http_post_json


# ---------- Low-level call helpers ----------

def _tools_call(path: str, payload: Dict[str, Any], timeout_s: float = 2.0) -> Optional[Dict[str, Any]]:
    url = CORE_BASE + "/tools" + path
    try:
        return _http_post_json(url, payload, timeout_s=timeout_s)
    except Exception:
        return None


def _toolbox_call(endpoint: str, payload: Dict[str, Any], timeout_s: float = 5.0) -> Optional[Dict[str, Any]]:
    """Call toolbox API directly."""
    url = TOOLBOX_BASE + endpoint
    try:
        return _http_post_json(url, payload, timeout_s=timeout_s)
    except Exception:
        return None


# ---------- Filesystem helpers ----------

def _is_path_forbidden(path: str) -> bool:
    """Check if path is in forbidden directories using proper prefix matching."""
    try:
        resolved = Path(path).expanduser().resolve()
        for forbidden_prefix in FORBIDDEN_PATH_PREFIXES:
            # Check if resolved path starts with forbidden prefix
            if resolved == forbidden_prefix or forbidden_prefix in resolved.parents:
                return True
            # Also check if it's a child of the forbidden path
            try:
                resolved.relative_to(forbidden_prefix)
                return True
            except ValueError:
                pass
        return False
    except Exception:
        return False


def _list_files(path: str = "~", recursive: bool = False, max_entries: int = 100) -> Optional[Dict[str, Any]]:
    """List files in a directory using toolbox API."""
    if _is_path_forbidden(path):
        return {"ok": False, "error": "forbidden", "detail": "Zugriff auf diesen Ordner ist nicht erlaubt."}
    return _toolbox_call("/fs/list", {
        "path": path,
        "recursive": recursive,
        "max_entries": max_entries,
        "include_hidden": False
    }, timeout_s=5.0)


def _read_file_via_toolbox(path: str, max_bytes: int = 100000) -> Optional[Dict[str, Any]]:
    """Read a file using toolbox API."""
    if _is_path_forbidden(path):
        return {"ok": False, "error": "forbidden", "detail": "Zugriff auf diese Datei ist nicht erlaubt."}
    return _toolbox_call("/fs/read", {"path": path, "max_bytes": max_bytes}, timeout_s=5.0)


def _move_file(src: str, dst: str) -> Optional[Dict[str, Any]]:
    """Move/rename a file using toolbox API."""
    if _is_path_forbidden(src) or _is_path_forbidden(dst):
        return {"ok": False, "error": "forbidden", "detail": "Zugriff auf diesen Pfad ist nicht erlaubt."}
    return _toolbox_call("/fs/move", {"src": src, "dst": dst}, timeout_s=5.0)


def _copy_file(src: str, dst: str) -> Optional[Dict[str, Any]]:
    """Copy a file using toolbox API."""
    if _is_path_forbidden(src) or _is_path_forbidden(dst):
        return {"ok": False, "error": "forbidden", "detail": "Zugriff auf diesen Pfad ist nicht erlaubt."}
    return _toolbox_call("/fs/copy", {"src": src, "dst": dst}, timeout_s=5.0)


def _delete_file(path: str) -> Optional[Dict[str, Any]]:
    """Delete a file using toolbox API."""
    if _is_path_forbidden(path):
        return {"ok": False, "error": "forbidden", "detail": "Loeschen in diesem Pfad ist nicht erlaubt."}
    return _toolbox_call("/fs/delete", {"path": path}, timeout_s=5.0)


# ---------- Deep System Info Helpers ----------

def _get_usb_devices() -> Optional[Dict[str, Any]]:
    """Get USB device information from toolbox."""
    return _toolbox_call("/sys/usb", {}, timeout_s=3.0)


def _usb_storage() -> Optional[Dict[str, Any]]:
    """List USB storage devices with mount status."""
    return _toolbox_call("/sys/usb/storage", {}, timeout_s=5.0)


def _usb_mount(device: str) -> Optional[Dict[str, Any]]:
    """Mount a USB storage device."""
    return _toolbox_call("/sys/usb/mount", {"device": device}, timeout_s=15.0)


def _usb_unmount(device: str) -> Optional[Dict[str, Any]]:
    """Unmount a USB storage device."""
    return _toolbox_call("/sys/usb/unmount", {"device": device}, timeout_s=15.0)


def _usb_eject(device: str) -> Optional[Dict[str, Any]]:
    """Safely eject a USB device (unmount + power-off)."""
    return _toolbox_call("/sys/usb/eject", {"device": device}, timeout_s=20.0)


def _get_network_info() -> Optional[Dict[str, Any]]:
    """Get network interface information from toolbox."""
    return _toolbox_call("/sys/network", {}, timeout_s=3.0)


def _get_driver_info() -> Optional[Dict[str, Any]]:
    """Get loaded kernel modules/drivers from toolbox."""
    return _toolbox_call("/sys/drivers", {}, timeout_s=5.0)


def _get_hardware_deep() -> Optional[Dict[str, Any]]:
    """Get deep hardware info (BIOS, cache, GPU) from toolbox."""
    return _toolbox_call("/sys/hardware_deep", {}, timeout_s=5.0)


def _take_screenshot() -> Optional[Dict[str, Any]]:
    """Take a screenshot using toolbox API."""
    return _toolbox_call("/desktop/screenshot", {}, timeout_s=8.0)


# ---------- App Registry Helpers ----------

def _app_search(query: str, limit: int = 10) -> Optional[Dict[str, Any]]:
    """Search for apps via app registry."""
    return _toolbox_call("/app/search", {"query": query, "limit": limit}, timeout_s=5.0)


def _app_open(app_id: str) -> Optional[Dict[str, Any]]:
    """Open an app by its ID."""
    return _toolbox_call("/app/open", {"app": app_id}, timeout_s=10.0)


def _app_close(app_id: str) -> Optional[Dict[str, Any]]:
    """Close an app by its ID."""
    return _toolbox_call("/app/close", {"app": app_id}, timeout_s=5.0)


def _app_allow(app_id: str) -> Optional[Dict[str, Any]]:
    """Allow an app (add to session permissions)."""
    return _toolbox_call("/app/allow", {"app": app_id}, timeout_s=3.0)


def _app_list(effective_only: bool = False, limit: int = 50) -> Optional[Dict[str, Any]]:
    """List apps (all or effective only)."""
    return _toolbox_call("/app/list", {"effective_only": effective_only, "limit": limit}, timeout_s=5.0)


# ---------- Core-Awareness Helpers ----------

def _core_describe() -> Optional[Dict[str, Any]]:
    """Get Frank's self-description from Core-Awareness."""
    return _toolbox_call("/core/describe", {}, timeout_s=5.0)


def _core_summary() -> Optional[Dict[str, Any]]:
    """Get Core-Awareness system summary."""
    return _toolbox_call("/core/summary", {}, timeout_s=3.0)


def _core_module(name: str) -> Optional[Dict[str, Any]]:
    """Get info about a specific module from Core-Awareness."""
    return _toolbox_call("/core/module", {"name": name}, timeout_s=5.0)


def _core_reflect(module_name: str = None) -> Optional[Dict[str, Any]]:
    """Get reflective analysis from Core-Awareness."""
    payload = {"name": module_name} if module_name else {}
    return _toolbox_call("/core/reflect", payload, timeout_s=8.0)


def _core_features() -> Optional[Dict[str, Any]]:
    """Get all features/capabilities from Core-Awareness."""
    return _toolbox_call("/core/features", {}, timeout_s=8.0)


# ---------- Window helpers ----------

def _get_window_ids() -> set:
    """Get set of current window IDs using wmctrl."""
    import subprocess
    try:
        result = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=3)
        if result.returncode == 0:
            ids = set()
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    ids.add(line.split()[0])
            return ids
    except Exception:
        pass
    return set()
