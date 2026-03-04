#!/usr/bin/env python3
"""
F.R.A.N.K. Updater — System Tray Icon
══════════════════════════════════════════
AppIndicator3 tray icon with neon green [F] cyberpunk icon.
Silent 6h auto-check with desktop notifications.
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# ── dbus GLib main loop (BEFORE GTK import) ──────────────────────────────────
try:
    from dbus.mainloop.glib import DBusGMainLoop
    DBusGMainLoop(set_as_default=True)
except ImportError:
    pass

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import Gtk, GLib, AyatanaAppIndicator3

# ── Config ───────────────────────────────────────────────────────────────────
STATE_DIR = Path.home() / ".local" / "share" / "frank" / "updater"
CONFIG_FILE = STATE_DIR / "config.json"
LOG_FILE = STATE_DIR / "tray.log"
DEFAULT_REPO = Path.home() / "aicore" / "opt" / "aicore"
CHECK_INTERVAL_H = 6  # hours

# ── Logging ──────────────────────────────────────────────────────────────────
def _log(msg: str):
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def _load_config() -> dict:
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text())
    except Exception:
        pass
    return {"auto_check": True}


def _save_config(cfg: dict):
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    except Exception:
        pass


# ── Icon generation ──────────────────────────────────────────────────────────
def _create_icon() -> Path:
    """Generate neon green [F] cyberpunk tray icon."""
    from PIL import Image, ImageDraw, ImageFont

    icon_dir = STATE_DIR / "icons"
    icon_dir.mkdir(parents=True, exist_ok=True)
    icon_path = icon_dir / "frank-updater-tray.png"

    size = 128
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Cyberpunk box: dark bg with neon green border
    d.rounded_rectangle(
        [4, 4, 124, 124], radius=12,
        fill=(0, 0, 0, 220), outline=(0, 255, 65), width=5
    )

    # Bold "F" in neon green
    font = None
    for font_name in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSansMono-Bold.ttf",
    ]:
        if Path(font_name).exists():
            font = ImageFont.truetype(font_name, 78)
            break
    if font is None:
        try:
            font = ImageFont.truetype("DejaVuSansMono-Bold.ttf", 78)
        except Exception:
            font = ImageFont.load_default()

    d.text((64, 64), "F", fill=(0, 255, 65), font=font, anchor="mm")

    img.save(str(icon_path))
    _log(f"Icon created: {icon_path}")
    return icon_dir


# ── Update check ─────────────────────────────────────────────────────────────
def _silent_check() -> dict:
    """Run silent update check."""
    # Import from sibling module
    updater_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(updater_dir.parent))
    try:
        from updater.frank_updater import check_for_updates
        return check_for_updates(DEFAULT_REPO)
    except ImportError:
        # Fallback: direct git check
        try:
            repo = str(DEFAULT_REPO)
            subprocess.run(
                ["git", "fetch", "origin", "main"],
                capture_output=True, timeout=30, cwd=repo
            )
            local = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=5, cwd=repo
            ).stdout.strip()
            remote = subprocess.run(
                ["git", "rev-parse", "--short", "origin/main"],
                capture_output=True, text=True, timeout=5, cwd=repo
            ).stdout.strip()
            if local != remote:
                return {"available": True, "local": local, "remote": remote, "commits": "?"}
            return {"available": False, "local": local, "remote": remote}
        except Exception as e:
            return {"available": False, "error": str(e)}


def _notify(title: str, body: str):
    """Send desktop notification via notify-send."""
    try:
        subprocess.run(
            ["notify-send", "--icon=system-software-update",
             "--app-name=F.R.A.N.K. Updater", title, body],
            timeout=5
        )
    except Exception:
        pass


# ── Terminal launch ──────────────────────────────────────────────────────────
def _find_terminal() -> list:
    """Find available terminal emulator."""
    terminals = [
        ["gnome-terminal", "--"],
        ["xfce4-terminal", "-e"],
        ["kitty", "--"],
        ["xterm", "-e"],
    ]
    for term in terminals:
        try:
            if subprocess.run(
                ["which", term[0]], capture_output=True
            ).returncode == 0:
                return term
        except Exception:
            continue
    return ["gnome-terminal", "--"]


def _launch_updater():
    """Launch the TUI updater in a terminal window."""
    term = _find_terminal()
    updater_script = Path(__file__).resolve().parent / "frank_updater.py"

    # When running as PyInstaller binary, use the binary itself with --update
    if getattr(sys, '_MEIPASS', None):
        binary = sys.executable
        cmd = term + [binary, "--update"]
    else:
        # Running from source
        python = str(DEFAULT_REPO / "venv" / "bin" / "python3")
        if not Path(python).exists():
            python = "python3"
        cmd = term + [python, str(updater_script)]

    _log(f"Launching updater: {' '.join(cmd)}")
    try:
        subprocess.Popen(cmd, start_new_session=True)
    except Exception as e:
        _log(f"Launch failed: {e}")
        _notify("F.R.A.N.K. Updater", f"Failed to open terminal: {e}")


# ── Tray icon class ──────────────────────────────────────────────────────────

class UpdaterTray:
    def __init__(self):
        self.config = _load_config()
        self._checking = False

        # Create icon
        icon_dir = _create_icon()

        # Setup indicator
        self.indicator = AyatanaAppIndicator3.Indicator.new(
            "frank-updater", "frank-updater-tray",
            AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_icon_theme_path(str(icon_dir))
        self.indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_title("F.R.A.N.K. Updater")

        # Build menu
        self.menu = Gtk.Menu()

        # Check for Updates
        item_check = Gtk.MenuItem(label="Check for Updates")
        item_check.connect("activate", self._on_check)
        self.menu.append(item_check)

        # Update Now
        item_update = Gtk.MenuItem(label="Update Now")
        item_update.connect("activate", self._on_update)
        self.menu.append(item_update)

        self.menu.append(Gtk.SeparatorMenuItem())

        # Auto-Check toggle
        auto_label = "Auto-Check: ON" if self.config.get("auto_check", True) else "Auto-Check: OFF"
        self.item_auto = Gtk.MenuItem(label=auto_label)
        self.item_auto.connect("activate", self._on_toggle_auto)
        self.menu.append(self.item_auto)

        self.menu.append(Gtk.SeparatorMenuItem())

        # Quit
        item_quit = Gtk.MenuItem(label="Quit")
        item_quit.connect("activate", self._on_quit)
        self.menu.append(item_quit)

        self.menu.show_all()
        self.indicator.set_menu(self.menu)

        # Setup auto-check timer (6h = 21600s)
        if self.config.get("auto_check", True):
            GLib.timeout_add_seconds(CHECK_INTERVAL_H * 3600, self._auto_check)

        # Do an initial check 30s after startup
        GLib.timeout_add_seconds(30, self._auto_check)

        # Heartbeat
        GLib.timeout_add_seconds(60, self._heartbeat)

        signal.signal(signal.SIGTERM, lambda *_: Gtk.main_quit())
        _log(f"Tray started (PID {os.getpid()}, auto_check={self.config.get('auto_check', True)})")

    def _on_check(self, _item):
        """Manual update check."""
        if self._checking:
            return
        self._checking = True
        _log("Manual check triggered")

        # Run check in background thread to avoid blocking GTK
        import threading
        def _do_check():
            result = _silent_check()
            GLib.idle_add(self._show_check_result, result)
        threading.Thread(target=_do_check, daemon=True).start()

    def _show_check_result(self, result: dict):
        self._checking = False
        if result.get("error"):
            _notify("F.R.A.N.K. Updater", f"Check failed: {result['error']}")
        elif result.get("available"):
            commits = result.get("commits", "?")
            _notify(
                "F.R.A.N.K. Update Available",
                f"{result['local']} → {result['remote']} ({commits} new commits)\n"
                "Click the tray icon to update."
            )
        else:
            _notify("F.R.A.N.K. Updater", "System is up to date.")
        return False  # Don't repeat

    def _on_update(self, _item):
        """Launch TUI updater."""
        _launch_updater()

    def _on_toggle_auto(self, _item):
        """Toggle auto-check."""
        current = self.config.get("auto_check", True)
        self.config["auto_check"] = not current
        _save_config(self.config)
        label = "Auto-Check: ON" if self.config["auto_check"] else "Auto-Check: OFF"
        self.item_auto.set_label(label)
        _log(f"Auto-check toggled to {self.config['auto_check']}")

        if self.config["auto_check"]:
            GLib.timeout_add_seconds(CHECK_INTERVAL_H * 3600, self._auto_check)

    def _on_quit(self, _item):
        _log("Quit requested")
        Gtk.main_quit()

    def _auto_check(self) -> bool:
        """Periodic silent check. Returns True to keep timer running."""
        if not self.config.get("auto_check", True):
            return False  # Stop timer

        _log("Auto-check running")
        import threading
        def _do_check():
            result = _silent_check()
            if result.get("available"):
                commits = result.get("commits", "?")
                GLib.idle_add(
                    _notify,
                    "F.R.A.N.K. Update Available",
                    f"{result.get('local', '?')} → {result.get('remote', '?')} ({commits} commits)"
                )
            _log(f"Auto-check result: available={result.get('available', False)}")
        threading.Thread(target=_do_check, daemon=True).start()
        return True  # Keep timer running

    def _heartbeat(self) -> bool:
        _log("heartbeat (alive)")
        return True

    def run(self):
        # Truncate old log
        try:
            if LOG_FILE.exists() and LOG_FILE.stat().st_size > 50000:
                LOG_FILE.write_text("")
        except Exception:
            pass
        Gtk.main()
        _log("Gtk.main() exited")


def main():
    tray = UpdaterTray()
    tray.run()


if __name__ == "__main__":
    main()
