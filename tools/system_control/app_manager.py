#!/usr/bin/env python3
"""
App Manager - Close Applications Gracefully

Features:
- Close apps without confirmation (graceful close)
- Preserves auto-save functionality of apps
- Works with Snaps, Flatpaks, and native apps
- Supports common apps: Discord, Blender, Firefox, etc.

Author: Frank AI System
"""

import logging
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

LOG = logging.getLogger("system_control.app_manager")


@dataclass
class RunningApp:
    """Represents a running application."""
    pid: int
    name: str
    command: str
    window_title: str = ""
    is_snap: bool = False
    is_flatpak: bool = False

    def to_dict(self) -> dict:
        return {
            "pid": self.pid,
            "name": self.name,
            "command": self.command,
            "window_title": self.window_title,
            "is_snap": self.is_snap,
            "is_flatpak": self.is_flatpak
        }


class AppManager:
    """Manages running applications."""

    # Common app name mappings (what user says -> process names)
    APP_ALIASES = {
        "discord": ["discord", "Discord"],
        "blender": ["blender", "Blender"],
        "firefox": ["firefox", "firefox-esr", "Firefox"],
        "chrome": ["chrome", "google-chrome", "chromium", "Google Chrome"],
        "spotify": ["spotify", "Spotify"],
        "vscode": ["code", "Code", "visual-studio-code"],
        "vs code": ["code", "Code", "visual-studio-code"],
        "steam": ["steam", "Steam"],
        "gimp": ["gimp", "GIMP", "gimp-2.10"],
        "inkscape": ["inkscape", "Inkscape"],
        "vlc": ["vlc", "VLC"],
        "obs": ["obs", "obs-studio", "OBS"],
        "slack": ["slack", "Slack"],
        "telegram": ["telegram", "telegram-desktop", "Telegram"],
        "signal": ["signal", "signal-desktop", "Signal"],
        "thunderbird": ["thunderbird", "Thunderbird"],
        "libreoffice": ["soffice", "libreoffice", "LibreOffice"],
        "word": ["soffice", "libreoffice"],
        "excel": ["soffice", "libreoffice"],
        "nautilus": ["nautilus", "org.gnome.Nautilus"],
        "dateimanager": ["nautilus", "thunar", "dolphin", "nemo"],
        "terminal": ["gnome-terminal", "konsole", "xfce4-terminal", "alacritty", "kitty"],
        "editor": ["gedit", "kate", "xed", "pluma"],
    }

    def __init__(self):
        pass

    def get_running_apps(self) -> List[RunningApp]:
        """Get list of running GUI applications."""
        apps = []

        try:
            # Use wmctrl to get windows
            result = subprocess.run(
                ["wmctrl", "-l", "-p"],
                capture_output=True,
                text=True,
                timeout=5
            )

            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue

                parts = line.split(None, 4)
                if len(parts) >= 5:
                    window_id = parts[0]
                    desktop = parts[1]
                    pid = int(parts[2]) if parts[2].isdigit() else 0
                    hostname = parts[3]
                    title = parts[4] if len(parts) > 4 else ""

                    if pid > 0:
                        # Get process name
                        try:
                            cmd_result = subprocess.run(
                                ["ps", "-p", str(pid), "-o", "comm="],
                                capture_output=True,
                                text=True,
                                timeout=2
                            )
                            name = cmd_result.stdout.strip()

                            # Check if snap/flatpak
                            cmdline_result = subprocess.run(
                                ["ps", "-p", str(pid), "-o", "args="],
                                capture_output=True,
                                text=True,
                                timeout=2
                            )
                            cmdline = cmdline_result.stdout.strip()
                            is_snap = "/snap/" in cmdline
                            is_flatpak = "/flatpak/" in cmdline or "flatpak" in cmdline

                            app = RunningApp(
                                pid=pid,
                                name=name,
                                command=cmdline,
                                window_title=title,
                                is_snap=is_snap,
                                is_flatpak=is_flatpak
                            )
                            apps.append(app)

                        except Exception:
                            pass

        except FileNotFoundError:
            LOG.warning("wmctrl not available")
        except Exception as e:
            LOG.error(f"Failed to get running apps: {e}")

        # Remove duplicates (same PID)
        seen_pids = set()
        unique_apps = []
        for app in apps:
            if app.pid not in seen_pids:
                seen_pids.add(app.pid)
                unique_apps.append(app)

        return unique_apps

    def find_app_by_name(self, name: str) -> List[RunningApp]:
        """Find running apps matching a name."""
        name_lower = name.lower()

        # Check aliases
        search_names = self.APP_ALIASES.get(name_lower, [name_lower, name])

        running = self.get_running_apps()
        matches = []

        for app in running:
            app_name_lower = app.name.lower()
            title_lower = app.window_title.lower()

            for search in search_names:
                search_lower = search.lower()
                if (search_lower in app_name_lower or
                    search_lower in title_lower or
                    search_lower in app.command.lower()):
                    matches.append(app)
                    break

        return matches

    def close_app(self, app_name: str) -> Tuple[bool, str]:
        """
        Close an application gracefully (NO confirmation needed).

        Uses SIGTERM to allow the app to save and close properly.
        Does NOT use SIGKILL to preserve auto-save functionality.

        Args:
            app_name: Name of the app to close

        Returns:
            (success, message)
        """
        apps = self.find_app_by_name(app_name)

        if not apps:
            return False, f"Keine laufende App namens '{app_name}' gefunden."

        closed_count = 0
        errors = []

        for app in apps:
            try:
                # Try graceful close via wmctrl first (sends WM_DELETE_WINDOW)
                result = subprocess.run(
                    ["wmctrl", "-c", app.window_title],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                if result.returncode != 0:
                    # Fallback: send SIGTERM (graceful termination)
                    kill_result = subprocess.run(
                        ["kill", "-TERM", str(app.pid)],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if kill_result.returncode != 0:
                        errors.append(f"{app.name}: kill fehlgeschlagen")
                        continue

                closed_count += 1
                LOG.info(f"Closed app: {app.name} (PID {app.pid})")

            except Exception as e:
                errors.append(f"{app.name}: {e}")
                LOG.error(f"Failed to close {app.name}: {e}")

        if closed_count > 0:
            if errors:
                return True, f"{closed_count} App(s) geschlossen, {len(errors)} Fehler."
            return True, f"{app_name} geschlossen."

        return False, f"Konnte {app_name} nicht schließen: {', '.join(errors)}"

    def close_app_by_pid(self, pid: int) -> Tuple[bool, str]:
        """Close app by PID (graceful)."""
        try:
            # Send SIGTERM for graceful close
            result = subprocess.run(
                ["kill", "-TERM", str(pid)],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return True, f"App (PID {pid}) geschlossen."
            else:
                return False, f"Konnte PID {pid} nicht beenden: {result.stderr}"
        except Exception as e:
            return False, f"Fehler: {e}"

    def list_running_apps(self) -> str:
        """Format list of running apps."""
        apps = self.get_running_apps()

        if not apps:
            return "Keine GUI-Anwendungen gefunden."

        lines = ["LAUFENDE ANWENDUNGEN:", "=" * 40, ""]

        # Group by name
        by_name: Dict[str, List[RunningApp]] = {}
        for app in apps:
            name = app.name
            if name not in by_name:
                by_name[name] = []
            by_name[name].append(app)

        for name, app_list in sorted(by_name.items()):
            if len(app_list) == 1:
                app = app_list[0]
                title = app.window_title[:40] + "..." if len(app.window_title) > 40 else app.window_title
                snap_flag = " [Snap]" if app.is_snap else ""
                flat_flag = " [Flatpak]" if app.is_flatpak else ""
                lines.append(f"  {name}{snap_flag}{flat_flag}")
                if title:
                    lines.append(f"    '{title}'")
            else:
                lines.append(f"  {name} ({len(app_list)} Fenster)")

        lines.append("")
        lines.append("Sage z.B. 'Schließ Discord' oder 'Beende Blender'")

        return "\n".join(lines)


# Singleton
_manager: Optional[AppManager] = None


def get_manager() -> AppManager:
    """Get singleton manager."""
    global _manager
    if _manager is None:
        _manager = AppManager()
    return _manager


# Public API - NO confirmation needed

def get_running_apps() -> List[Dict[str, Any]]:
    """Get list of running apps."""
    return [app.to_dict() for app in get_manager().get_running_apps()]


def close_app(app_name: str) -> Tuple[bool, str]:
    """Close an app gracefully (no confirmation)."""
    return get_manager().close_app(app_name)


def close_app_by_pid(pid: int) -> Tuple[bool, str]:
    """Close app by PID (no confirmation)."""
    return get_manager().close_app_by_pid(pid)


def list_running_apps() -> str:
    """Get formatted list of running apps."""
    return get_manager().list_running_apps()


def find_app(name: str) -> List[Dict[str, Any]]:
    """Find apps by name."""
    return [app.to_dict() for app in get_manager().find_app_by_name(name)]


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    print("=== App Manager Test ===")

    manager = get_manager()

    print("\n--- Running Apps ---")
    print(manager.list_running_apps())
