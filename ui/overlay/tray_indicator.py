#!/usr/bin/env python3
"""Standalone Frank tray icon process.

Creates a system tray icon (AppIndicator3) for the Frank overlay.
Communicates with the overlay via signal file /tmp/frank_tray_toggle.

When the user clicks the menu toggle item, this creates the signal file.
The overlay polls for this file every 300ms.
"""
import os
import signal
import sys
import time
from pathlib import Path

# CRITICAL: Set up dbus GLib main loop BEFORE importing GTK.
# If done after, dbus signals won't be dispatched on the GLib loop.
try:
    from dbus.mainloop.glib import DBusGMainLoop
    DBusGMainLoop(set_as_default=True)
    _DBUS_AVAILABLE = True
except ImportError:
    _DBUS_AVAILABLE = False

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import Gtk, GLib, AyatanaAppIndicator3

SIGNAL = Path("/tmp/frank_tray_toggle")
QUIT_SIGNAL = Path("/tmp/frank_tray_quit")
LOG_FILE = Path("/tmp/frank_tray.log")

# Debounce: prevent multiple signal creations within cooldown period
_last_signal_time = 0.0
_SIGNAL_COOLDOWN = 1.5  # seconds


def _log(msg: str):
    """Append to log file (stdout/stderr not available in subprocess)."""
    try:
        with LOG_FILE.open("a") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def _create_signal():
    """Create the toggle signal file with debounce protection."""
    global _last_signal_time
    now = time.time()
    if now - _last_signal_time < _SIGNAL_COOLDOWN:
        return False  # Debounce: too soon since last signal
    _last_signal_time = now
    try:
        SIGNAL.touch()
        _log("Signal created (debounced)")
        return True
    except Exception as e:
        _log(f"touch() failed: {e}")
    try:
        with open(str(SIGNAL), "w") as f:
            f.write("")
        _log("Signal created via open(w)")
        return True
    except Exception as e:
        _log(f"open(w) failed: {e}")
    return False


signal.signal(signal.SIGTERM, lambda *_: Gtk.main_quit())

# --- Create icon ---
icon_dir = Path("/tmp/frank_icons")
icon_dir.mkdir(exist_ok=True)
icon_path = icon_dir / "frank-tray.png"
if not icon_path.exists():
    from PIL import Image, ImageDraw
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 12, 56, 58], radius=6, fill="#2d8c3c")
    d.rectangle([8, 6, 56, 20], fill="#1a5c28")
    d.rectangle([6, 6, 58, 10], fill="#0a2e14")
    d.ellipse([2, 28, 12, 38], fill="#888888", outline="#555555")
    d.ellipse([52, 28, 62, 38], fill="#888888", outline="#555555")
    d.ellipse([18, 24, 28, 34], fill="#111111")
    d.ellipse([36, 24, 46, 34], fill="#111111")
    d.ellipse([21, 27, 26, 32], fill="#44ff44")
    d.ellipse([39, 27, 44, 32], fill="#44ff44")
    d.line([16, 22, 30, 22], fill="#1a5c28", width=3)
    d.line([34, 22, 48, 22], fill="#1a5c28", width=3)
    d.line([32, 34, 32, 42], fill="#1a5c28", width=2)
    d.line([22, 48, 42, 48], fill="#111111", width=2)
    for sx in range(24, 42, 4):
        d.line([sx, 45, sx, 51], fill="#111111", width=1)
    d.line([26, 14, 38, 14], fill="#444444", width=1)
    for sx in range(28, 38, 3):
        d.line([sx, 12, sx, 16], fill="#444444", width=1)
    img.save(str(icon_path))

# --- Setup indicator ---
indicator = AyatanaAppIndicator3.Indicator.new(
    "frank-overlay", "frank-tray",
    AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS,
)
indicator.set_icon_theme_path("/tmp/frank_icons")
indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
indicator.set_title("F.R.A.N.K.")

# --- Menu ---
menu = Gtk.Menu()


def _on_toggle_activate(_item):
    """Called when 'Frank anzeigen/verstecken' menu item is clicked."""
    _log("GTK activate fired for toggle item")
    GLib.idle_add(_create_signal)


item_toggle = Gtk.MenuItem(label="Frank anzeigen/verstecken")
item_toggle.connect("activate", _on_toggle_activate)
menu.append(item_toggle)

menu.append(Gtk.SeparatorMenuItem())

def _on_quit_activate(_item):
    """Write quit signal for the overlay, then exit tray."""
    _log("Quit requested via tray menu")
    try:
        QUIT_SIGNAL.touch()
        _log("Quit signal written")
    except Exception as e:
        _log(f"Failed to write quit signal: {e}")
    Gtk.main_quit()

item_quit = Gtk.MenuItem(label="Beenden")
item_quit.connect("activate", _on_quit_activate)
menu.append(item_quit)

menu.show_all()
indicator.set_menu(menu)

# Middle-click on icon → toggle (secondary activate)
try:
    indicator.set_secondary_activate_target(item_toggle)
    _log("Secondary activate target set (middle-click)")
except Exception as e:
    _log(f"set_secondary_activate_target failed: {e}")

# --- dbus signal interception (backup path) ---
if _DBUS_AVAILABLE:
    try:
        import dbus
        bus = dbus.SessionBus()

        def _on_item_activation(*args, **kwargs):
            """Backup: catch ItemActivationRequested from dbusmenu registrar."""
            _log(f"dbus ItemActivationRequested: {args}")
            _create_signal()

        bus.add_signal_receiver(
            _on_item_activation,
            signal_name="ItemActivationRequested",
            dbus_interface="com.canonical.dbusmenu",
        )
        _log("dbus ItemActivationRequested receiver registered")
    except Exception as e:
        _log(f"dbus setup failed: {e}")

# --- Heartbeat: log that we're still alive every 60s ---
def _heartbeat():
    _log("heartbeat (alive)")
    return True  # Keep timer running

GLib.timeout_add_seconds(60, _heartbeat)

# Truncate old log on startup
try:
    if LOG_FILE.exists() and LOG_FILE.stat().st_size > 50000:
        LOG_FILE.write_text("")
except Exception:
    pass

_log(f"Tray indicator started (PID {os.getpid()})")
Gtk.main()
_log("Gtk.main() exited")
