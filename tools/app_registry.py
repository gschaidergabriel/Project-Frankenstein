#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
App Registry for Frank

Unified app discovery and launch system supporting:
- Desktop entries (.desktop files)
- Flatpak apps
- Snap packages
- Steam games (via steam_integration)

Each app gets a capability matrix:
- present: Installed/found
- available: Can start (GUI session ok, dependencies ok)
- allowed: Policy permits it
- effective: present + available + allowed = can open now

Reason codes for failures:
- not_found: Not installed
- policy_blocked: Present but policy blocks it
- no_gui: No desktop session/DISPLAY
- start_failed: Launch error with details
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import difflib

LOG = logging.getLogger("app_registry")

# Desktop entry search paths
DESKTOP_ENTRY_PATHS = [
    Path("/usr/share/applications"),
    Path("/usr/local/share/applications"),
    Path.home() / ".local/share/applications",
    Path("/var/lib/flatpak/exports/share/applications"),
    Path.home() / ".local/share/flatpak/exports/share/applications",
    Path("/var/lib/snapd/desktop/applications"),
]

# Default allowlist for safe apps (can be expanded)
DEFAULT_ALLOWLIST = {
    # Browsers
    "firefox", "chromium", "google-chrome", "brave-browser", "vivaldi",
    # Media
    "vlc", "mpv", "totem", "rhythmbox", "spotify", "audacity",
    # Graphics
    "gimp", "inkscape", "krita", "blender", "obs-studio",
    # Office
    "libreoffice", "evince", "okular", "xournalpp",
    # Development
    "code", "codium", "gedit", "gnome-text-editor", "kate",
    # System
    "gnome-terminal", "konsole", "nautilus", "dolphin", "thunar",
    "gnome-system-monitor", "htop",
    # Communication
    "discord", "telegram-desktop", "signal-desktop", "thunderbird",
    # Games
    "steam", "lutris", "heroic",
    # Utilities
    "gnome-calculator", "gnome-screenshot", "flameshot",
}

# Policy file path
POLICY_FILE = Path.home() / ".config/aicore/app_policy.json"


@dataclass
class AppEntry:
    """Represents a discoverable application."""
    id: str                          # Unique ID (desktop file basename or flatpak/snap id)
    name: str                        # Display name
    exec_cmd: str                    # Command to execute
    source: str                      # desktop / flatpak / snap / steam
    icon: Optional[str] = None       # Icon name or path
    categories: List[str] = field(default_factory=list)
    description: Optional[str] = None
    desktop_file: Optional[str] = None

    # Capability matrix
    present: bool = True             # Always True if in registry
    available: bool = True           # Can start (GUI ok, deps ok)
    allowed: bool = False            # Policy permits

    # Computed
    @property
    def effective(self) -> bool:
        """Can this app be opened right now?"""
        return self.present and self.available and self.allowed

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["effective"] = self.effective
        return d


class AppRegistry:
    """
    Central registry for all launchable applications.
    Scans desktop entries, flatpak, snap, and integrates with Steam.
    """

    _SCAN_TTL = 300  # Auto-rescan after 5 minutes

    def __init__(self):
        self._apps: Dict[str, AppEntry] = {}
        self._allowlist: set = set(DEFAULT_ALLOWLIST)
        self._session_allowed: set = set()  # One-time permissions
        self._gui_available: Optional[bool] = None
        self._scan_ts: float = 0.0  # Timestamp of last scan
        self._load_policy()

    def _load_policy(self):
        """Load app policy from config file."""
        if POLICY_FILE.exists():
            try:
                data = json.loads(POLICY_FILE.read_text())
                if "allowlist" in data:
                    self._allowlist.update(data["allowlist"])
                if "blocklist" in data:
                    self._allowlist -= set(data["blocklist"])
            except Exception as e:
                LOG.warning(f"Failed to load policy: {e}")

    def _save_policy(self):
        """Save app policy to config file."""
        POLICY_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "allowlist": list(self._allowlist - DEFAULT_ALLOWLIST),
            "session_allowed": list(self._session_allowed),
        }
        POLICY_FILE.write_text(json.dumps(data, indent=2))

    def _check_gui_available(self) -> bool:
        """Check if GUI/display is available."""
        if self._gui_available is not None:
            return self._gui_available

        # Check DISPLAY or WAYLAND_DISPLAY
        has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

        if not has_display:
            self._gui_available = False
            return False

        # Try to verify with xdpyinfo or similar
        if shutil.which("xdpyinfo"):
            try:
                result = subprocess.run(
                    ["xdpyinfo"], capture_output=True, timeout=2
                )
                self._gui_available = result.returncode == 0
                return self._gui_available
            except Exception:
                pass

        self._gui_available = has_display
        return self._gui_available

    def _is_allowed(self, app_id: str, name: str) -> bool:
        """Check if app is allowed by policy."""
        # Check by ID
        id_lower = app_id.lower()
        name_lower = name.lower()

        for allowed in self._allowlist | self._session_allowed:
            allowed_lower = allowed.lower()
            if allowed_lower in id_lower or allowed_lower in name_lower:
                return True
            if id_lower in allowed_lower or name_lower in allowed_lower:
                return True

        return False

    def _parse_desktop_file(self, path: Path) -> Optional[AppEntry]:
        """Parse a .desktop file into an AppEntry."""
        try:
            content = path.read_text(encoding="utf-8", errors="replace")

            # Basic .desktop file parsing
            in_desktop_entry = False
            data: Dict[str, str] = {}

            for line in content.splitlines():
                line = line.strip()
                if line == "[Desktop Entry]":
                    in_desktop_entry = True
                    continue
                if line.startswith("[") and line.endswith("]"):
                    in_desktop_entry = False
                    continue
                if not in_desktop_entry or "=" not in line:
                    continue

                key, _, value = line.partition("=")
                data[key.strip()] = value.strip()

            # Skip non-applications
            if data.get("Type") != "Application":
                return None

            # Skip hidden/no-display
            if data.get("NoDisplay", "").lower() == "true":
                return None
            if data.get("Hidden", "").lower() == "true":
                return None

            name = data.get("Name", "")
            exec_cmd = data.get("Exec", "")

            if not name or not exec_cmd:
                return None

            # Clean up Exec command (remove %f, %u, etc.)
            exec_cmd = re.sub(r"%[fFuUdDnNickvm]", "", exec_cmd).strip()

            # Determine source
            source = "desktop"
            if "flatpak" in str(path).lower():
                source = "flatpak"
            elif "snapd" in str(path).lower() or "snap" in exec_cmd.lower():
                source = "snap"

            app_id = path.stem

            entry = AppEntry(
                id=app_id,
                name=name,
                exec_cmd=exec_cmd,
                source=source,
                icon=data.get("Icon"),
                categories=[c.strip() for c in data.get("Categories", "").split(";") if c.strip()],
                description=data.get("Comment") or data.get("GenericName"),
                desktop_file=str(path),
                present=True,
                available=self._check_gui_available(),
                allowed=self._is_allowed(app_id, name),
            )

            return entry

        except Exception as e:
            LOG.debug(f"Failed to parse {path}: {e}")
            return None

    def _scan_desktop_entries(self):
        """Scan all desktop entry paths."""
        for base_path in DESKTOP_ENTRY_PATHS:
            if not base_path.exists():
                continue

            for desktop_file in base_path.glob("*.desktop"):
                entry = self._parse_desktop_file(desktop_file)
                if entry and entry.id not in self._apps:
                    self._apps[entry.id] = entry

    def _scan_flatpak(self):
        """Scan installed flatpak apps."""
        if not shutil.which("flatpak"):
            return

        try:
            result = subprocess.run(
                ["flatpak", "list", "--app", "--columns=application,name"],
                capture_output=True, text=True, timeout=10
            )

            if result.returncode != 0:
                return

            for line in result.stdout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    app_id, name = parts[0], parts[1]

                    # Skip if already found via desktop file
                    if app_id in self._apps:
                        self._apps[app_id].source = "flatpak"
                        continue

                    entry = AppEntry(
                        id=app_id,
                        name=name,
                        exec_cmd=f"flatpak run {app_id}",
                        source="flatpak",
                        present=True,
                        available=self._check_gui_available(),
                        allowed=self._is_allowed(app_id, name),
                    )
                    self._apps[app_id] = entry

        except Exception as e:
            LOG.warning(f"Flatpak scan failed: {e}")

    def _scan_snap(self):
        """Scan installed snap packages."""
        if not shutil.which("snap"):
            return

        try:
            result = subprocess.run(
                ["snap", "list"],
                capture_output=True, text=True, timeout=10
            )

            if result.returncode != 0:
                return

            lines = result.stdout.strip().splitlines()
            if len(lines) < 2:  # Header + at least one snap
                return

            for line in lines[1:]:  # Skip header
                parts = line.split()
                if len(parts) >= 1:
                    snap_name = parts[0]

                    # Check if this snap has a desktop file (GUI app)
                    desktop_path = Path(f"/var/lib/snapd/desktop/applications/{snap_name}_{snap_name}.desktop")
                    has_desktop = desktop_path.exists() or any(
                        p.exists() for p in Path("/var/lib/snapd/desktop/applications").glob(f"{snap_name}_*.desktop")
                    ) if Path("/var/lib/snapd/desktop/applications").exists() else False

                    # Skip if already found via desktop file
                    if snap_name in self._apps:
                        self._apps[snap_name].source = "snap"
                        continue

                    # Only add if it has a desktop entry (GUI app)
                    if has_desktop:
                        entry = AppEntry(
                            id=snap_name,
                            name=snap_name.replace("-", " ").title(),
                            exec_cmd=f"snap run {snap_name}",
                            source="snap",
                            present=True,
                            available=self._check_gui_available(),
                            allowed=self._is_allowed(snap_name, snap_name),
                        )
                        self._apps[snap_name] = entry

        except Exception as e:
            LOG.warning(f"Snap scan failed: {e}")

    def scan(self, force: bool = False):
        """Scan all sources for applications.

        Auto-rescans after _SCAN_TTL seconds to detect newly installed apps.
        """
        import time
        if self._apps and not force:
            if time.time() - self._scan_ts < self._SCAN_TTL:
                return
            # TTL expired — rescan to pick up newly installed apps
            LOG.info("App registry TTL expired, rescanning...")
            force = True

        self._apps.clear()
        self._gui_available = None  # Re-check

        self._scan_desktop_entries()
        self._scan_flatpak()
        self._scan_snap()
        self._scan_ts = time.time()

        LOG.info(f"App registry: {len(self._apps)} apps found")

    def search(self, query: str, limit: int = 10) -> List[AppEntry]:
        """Search for apps by name."""
        self.scan()

        if not query:
            return []

        query_lower = query.lower().strip()
        results: List[Tuple[int, AppEntry]] = []

        for app in self._apps.values():
            name_lower = app.name.lower()
            id_lower = app.id.lower()

            # Exact match
            if query_lower == name_lower or query_lower == id_lower:
                results.append((0, app))
                continue

            # Starts with
            if name_lower.startswith(query_lower) or id_lower.startswith(query_lower):
                results.append((1, app))
                continue

            # Contains
            if query_lower in name_lower or query_lower in id_lower:
                results.append((2, app))
                continue

            # Word match
            words = name_lower.split()
            if any(w.startswith(query_lower) for w in words):
                results.append((3, app))
                continue

        # Sort by score and name
        results.sort(key=lambda x: (x[0], x[1].name.lower()))

        return [app for _, app in results[:limit]]

    def list_apps(self, limit: int = 100, filter_effective: bool = False) -> List[AppEntry]:
        """List all apps, optionally filtered to effective only."""
        self.scan()

        apps = list(self._apps.values())

        if filter_effective:
            apps = [a for a in apps if a.effective]

        # Sort by name
        apps.sort(key=lambda a: a.name.lower())

        return apps[:limit]

    def get_app(self, app_id: str) -> Optional[AppEntry]:
        """Get a specific app by ID."""
        self.scan()

        # Direct lookup
        if app_id in self._apps:
            return self._apps[app_id]

        # Case-insensitive lookup
        app_id_lower = app_id.lower()
        for aid, app in self._apps.items():
            if aid.lower() == app_id_lower:
                return app

        return None

    def open_app(self, app_id_or_name: str) -> Dict[str, Any]:
        """
        Open an application.

        Returns:
            {
                "ok": bool,
                "reason": str,  # ok / not_found / policy_blocked / no_gui / start_failed
                "message": str,
                "app": Optional[dict]
            }
        """
        self.scan()

        # Try direct lookup first
        app = self.get_app(app_id_or_name)

        # If not found, try search
        if not app:
            results = self.search(app_id_or_name, limit=1)
            if results:
                app = results[0]

        if not app:
            return {
                "ok": False,
                "reason": "not_found",
                "message": f"App '{app_id_or_name}' nicht gefunden. Nicht installiert?",
                "app": None,
            }

        # Check availability
        if not app.available:
            return {
                "ok": False,
                "reason": "no_gui",
                "message": f"Kann '{app.name}' nicht starten - keine Desktop-Session verfügbar (DISPLAY nicht gesetzt).",
                "app": app.to_dict(),
            }

        # Check policy
        if not app.allowed:
            return {
                "ok": False,
                "reason": "policy_blocked",
                "message": f"'{app.name}' ist vorhanden aber nicht freigegeben. Sage 'erlaube {app.name}' um es zu aktivieren.",
                "app": app.to_dict(),
            }

        # Try to launch
        try:
            # Use gtk-launch for .desktop files if available
            if app.desktop_file and shutil.which("gtk-launch"):
                cmd = ["gtk-launch", Path(app.desktop_file).stem]
            else:
                # Parse exec command
                cmd = app.exec_cmd.split()

            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )

            return {
                "ok": True,
                "reason": "ok",
                "message": f"Starte {app.name}...",
                "app": app.to_dict(),
            }

        except Exception as e:
            return {
                "ok": False,
                "reason": "start_failed",
                "message": f"Fehler beim Starten von '{app.name}': {e}",
                "app": app.to_dict(),
            }

    def close_app(self, app_id_or_name: str) -> Dict[str, Any]:
        """
        Close a running application.

        Returns:
            {
                "ok": bool,
                "reason": str,
                "message": str
            }
        """
        self.scan()

        app = self.get_app(app_id_or_name)
        if not app:
            results = self.search(app_id_or_name, limit=1)
            if results:
                app = results[0]

        if not app:
            return {
                "ok": False,
                "reason": "not_found",
                "message": f"App '{app_id_or_name}' nicht gefunden.",
            }

        try:
            # Get the base command name
            cmd_parts = app.exec_cmd.split()
            if cmd_parts:
                # Handle flatpak/snap wrappers
                if cmd_parts[0] == "flatpak" and len(cmd_parts) >= 3:
                    proc_name = cmd_parts[2]  # The app ID
                elif cmd_parts[0] == "snap" and len(cmd_parts) >= 3:
                    proc_name = cmd_parts[2]
                else:
                    proc_name = Path(cmd_parts[0]).name

                # Try pkill
                result = subprocess.run(
                    ["pkill", "-f", proc_name],
                    capture_output=True, timeout=5
                )

                if result.returncode == 0:
                    return {
                        "ok": True,
                        "reason": "ok",
                        "message": f"{app.name} wird geschlossen...",
                    }
                else:
                    return {
                        "ok": False,
                        "reason": "not_running",
                        "message": f"{app.name} scheint nicht zu laufen.",
                    }

            return {
                "ok": False,
                "reason": "unknown_process",
                "message": f"Kann Prozess für {app.name} nicht ermitteln.",
            }

        except Exception as e:
            return {
                "ok": False,
                "reason": "close_failed",
                "message": f"Fehler beim Schließen von '{app.name}': {e}",
            }

    def allow_app(self, app_id_or_name: str, permanent: bool = False) -> Dict[str, Any]:
        """
        Allow an app (session or permanent).

        Returns:
            {
                "ok": bool,
                "message": str,
                "app": Optional[dict]
            }
        """
        self.scan()

        app = self.get_app(app_id_or_name)
        if not app:
            results = self.search(app_id_or_name, limit=1)
            if results:
                app = results[0]

        if not app:
            return {
                "ok": False,
                "message": f"App '{app_id_or_name}' nicht gefunden.",
                "app": None,
            }

        if permanent:
            self._allowlist.add(app.id)
            self._allowlist.add(app.name.lower())
            self._save_policy()
            msg = f"'{app.name}' wurde dauerhaft freigegeben."
        else:
            self._session_allowed.add(app.id)
            self._session_allowed.add(app.name.lower())
            msg = f"'{app.name}' wurde für diese Session freigegeben."

        # Update app entry
        app.allowed = True

        return {
            "ok": True,
            "message": msg,
            "app": app.to_dict(),
        }

    def get_capabilities(self) -> Dict[str, Any]:
        """Get capabilities summary for system prompt."""
        self.scan()

        total = len(self._apps)
        effective = sum(1 for a in self._apps.values() if a.effective)

        sources = {}
        for app in self._apps.values():
            sources[app.source] = sources.get(app.source, 0) + 1

        return {
            "app_open": {
                "present": True,
                "available": self._check_gui_available(),
                "allowed": True,
                "effective": effective > 0,
            },
            "stats": {
                "total_apps": total,
                "effective_apps": effective,
                "sources": sources,
            },
            "gui_available": self._check_gui_available(),
        }


# Global registry instance
_registry: Optional[AppRegistry] = None


def get_registry() -> AppRegistry:
    """Get or create the global app registry."""
    global _registry
    if _registry is None:
        _registry = AppRegistry()
    return _registry


# Convenience functions for toolbox integration

def app_search(query: str, limit: int = 10) -> Dict[str, Any]:
    """Search for apps."""
    registry = get_registry()
    results = registry.search(query, limit)
    return {
        "ok": True,
        "query": query,
        "count": len(results),
        "apps": [a.to_dict() for a in results],
    }


def app_list(limit: int = 50, effective_only: bool = False) -> Dict[str, Any]:
    """List available apps."""
    registry = get_registry()
    apps = registry.list_apps(limit, filter_effective=effective_only)
    return {
        "ok": True,
        "count": len(apps),
        "apps": [a.to_dict() for a in apps],
    }


def app_open(app_id_or_name: str) -> Dict[str, Any]:
    """Open an app."""
    registry = get_registry()
    return registry.open_app(app_id_or_name)


def app_close(app_id_or_name: str) -> Dict[str, Any]:
    """Close an app."""
    registry = get_registry()
    return registry.close_app(app_id_or_name)


def app_allow(app_id_or_name: str, permanent: bool = False) -> Dict[str, Any]:
    """Allow an app."""
    registry = get_registry()
    return registry.allow_app(app_id_or_name, permanent)


def app_capabilities() -> Dict[str, Any]:
    """Get app capabilities."""
    registry = get_registry()
    return registry.get_capabilities()


# CLI for testing
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("Usage: app_registry.py [search <query>|list|open <app>|close <app>|allow <app>|caps]")
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "search" and len(sys.argv) > 2:
        query = " ".join(sys.argv[2:])
        result = app_search(query)
        print(f"Found {result['count']} apps:")
        for app in result["apps"]:
            status = "✓" if app["effective"] else "✗"
            print(f"  {status} {app['name']} ({app['source']}) - {app['id']}")

    elif cmd == "list":
        result = app_list(limit=30)
        print(f"Apps ({result['count']}):")
        for app in result["apps"]:
            status = "✓" if app["effective"] else "✗"
            print(f"  {status} {app['name']} ({app['source']})")

    elif cmd == "open" and len(sys.argv) > 2:
        app_name = " ".join(sys.argv[2:])
        result = app_open(app_name)
        print(f"[{result['reason']}] {result['message']}")

    elif cmd == "close" and len(sys.argv) > 2:
        app_name = " ".join(sys.argv[2:])
        result = app_close(app_name)
        print(f"[{result['reason']}] {result['message']}")

    elif cmd == "allow" and len(sys.argv) > 2:
        app_name = " ".join(sys.argv[2:])
        result = app_allow(app_name, permanent=True)
        print(result["message"])

    elif cmd == "caps":
        result = app_capabilities()
        print(json.dumps(result, indent=2))

    else:
        print("Unknown command")
