#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Frank Neural Monitor - Live Log Display for Mini-HDMI

Automatically detects the mini-HDMI display (eM713A, 1024x600) on any
HDMI port and shows Frank's internal logs in real time.

Black background, neon-green text (#00FF00)

Features:
- Auto-detection via EDID (Model: eM713A) or resolution (1024x600)
- Hotplug detection (plug in display -> logs start)
- Aggregates all Frank subsystems
- Fullscreen on the mini display

Database: <AICORE_BASE>/database/
"""

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('Pango', '1.0')

from gi.repository import Gtk, Gdk, GLib, Pango
import fcntl
import json
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple

# =============================================================================
# Singleton Lock (prevent multiple instances)
# =============================================================================

try:
    from config.paths import get_temp as _fnm_get_temp
    LOCK_FILE = str(_fnm_get_temp("neural_monitor.lock"))
except ImportError:
    import tempfile as _fnm_tempfile
    LOCK_FILE = str(Path(_fnm_tempfile.gettempdir()) / "frank" / "neural_monitor.lock")
_lock_fd = None

def _is_pid_running(pid: int) -> bool:
    """Check if a process with given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False

def acquire_singleton_lock() -> bool:
    """Acquire exclusive lock - returns False if another instance is running."""
    global _lock_fd

    # Check for stale lock first
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, 'r') as f:
                old_pid = int(f.read().strip())
                if not _is_pid_running(old_pid):
                    LOG.info(f"Removing stale lock from dead process {old_pid}")
                    os.unlink(LOCK_FILE)
        except (ValueError, IOError, OSError):
            # Can't read PID, try to remove stale lock
            try:
                os.unlink(LOCK_FILE)
            except OSError:
                pass

    try:
        _lock_fd = open(LOCK_FILE, 'w')
        fcntl.flock(_lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_fd.write(str(os.getpid()))
        _lock_fd.flush()
        return True
    except (IOError, OSError):
        if _lock_fd:
            try:
                _lock_fd.close()
            except OSError:
                pass
            _lock_fd = None
        return False

def release_singleton_lock():
    """Release the singleton lock."""
    global _lock_fd
    if _lock_fd:
        try:
            fcntl.flock(_lock_fd.fileno(), fcntl.LOCK_UN)
            _lock_fd.close()
        except OSError:
            pass
        try:
            os.unlink(LOCK_FILE)
        except OSError:
            pass
        _lock_fd = None


# =============================================================================
# Systemd Watchdog Support
# =============================================================================

def sd_notify_watchdog():
    """Send watchdog ping to systemd (keeps service alive)."""
    notify_socket = os.environ.get("NOTIFY_SOCKET")
    if not notify_socket:
        return  # Not running under systemd

    try:
        if notify_socket.startswith("@"):
            notify_socket = "\0" + notify_socket[1:]

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.connect(notify_socket)
        sock.sendall(b"WATCHDOG=1")
        sock.close()
    except Exception:
        pass  # Ignore errors - watchdog is optional


def sd_notify_ready():
    """Notify systemd that service is ready."""
    notify_socket = os.environ.get("NOTIFY_SOCKET")
    if not notify_socket:
        return

    try:
        if notify_socket.startswith("@"):
            notify_socket = "\0" + notify_socket[1:]

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.connect(notify_socket)
        sock.sendall(b"READY=1")
        sock.close()
    except Exception:
        pass

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s"
)
LOG = logging.getLogger("neural_monitor")

# =============================================================================
# Constants
# =============================================================================

# Mini-Display identification (EDID-based)
MINI_DISPLAY_IDENTIFIERS = [
    "eM713A",           # Model name from EDID
    "1024x600",         # Native resolution
]

# Minimum resolution for mini-display detection
MINI_DISPLAY_MAX_WIDTH = 1100
MINI_DISPLAY_MAX_HEIGHT = 700

# Colors (neon green on black)
BG_COLOR = "#000000"
FG_COLOR = "#00FF00"
FG_COLOR_DIM = "#007700"
FG_COLOR_WARN = "#FFFF00"
FG_COLOR_ERROR = "#FF3333"
FG_COLOR_INFO = "#00FFFF"

# Resolve temp directory for log files
try:
    from config.paths import TEMP_DIR as _fnm_temp_dir
except ImportError:
    import tempfile as _fnm_tmpmod
    _fnm_temp_dir = Path(_fnm_tmpmod.gettempdir()) / "frank"

# Log sources
LOG_SOURCES = {
    # Main journal: ALL Frank/AI Core Services
    "journal": {
        "cmd": ["journalctl", "--user", "-f", "-n", "0", "--no-pager",
                "-u", "frank*", "-u", "uolg*",
                "-u", "aicore-core*", "-u", "aicore-router*",
                "-u", "aicore-desktopd*",
                "-u", "aicore-modeld*", "-u", "aicore-llama*",
                "-u", "aicore-qwen*"],
        "prefix": "[CORE]",
        "color": FG_COLOR,
    },
    # UOLG log gateway
    "uolg": {
        "file": str(_fnm_temp_dir / "uolg" / "uolg.log"),
        "prefix": "[UOLG]",
        "color": FG_COLOR_INFO,
    },
    # Network Sentinel
    "sentinel": {
        "file": str(_fnm_temp_dir / "sentinel.log"),
        "prefix": "[NET]",
        "color": FG_COLOR_WARN,
    },
    # Voice Daemon File Log (in addition to journal)
    "voice": {
        "file": str(_fnm_temp_dir / "voice.log"),
        "prefix": "[VOICE]",
        "color": "#FF00FF",  # Magenta for voice
    },
    # UI Overlay Chat
    "overlay": {
        "file": str(_fnm_temp_dir / "overlay.log"),
        "prefix": "[CHAT]",
        "color": "#00FFFF",  # Cyan for chat
    },
}

# UI
FONT_FAMILY = "JetBrains Mono, Fira Code, Consolas, monospace"
FONT_SIZE = 9
MAX_LINES = 500
UPDATE_INTERVAL_MS = 100

# Polling
DISPLAY_CHECK_INTERVAL_SEC = 3


# =============================================================================
# Display Detection
# =============================================================================

def get_connected_displays() -> List[Dict]:
    """Get list of all connected displays via xrandr."""
    displays = []
    try:
        result = subprocess.run(
            ["xrandr", "--query"],
            capture_output=True, text=True, timeout=5
        )

        current_display = None
        for line in result.stdout.split("\n"):
            # Display line: "HDMI-A-1 connected 1024x600+1920+0 ..."
            match = re.match(
                r'^(\S+)\s+connected\s+(?:primary\s+)?(\d+)x(\d+)\+(\d+)\+(\d+)',
                line
            )
            if match:
                current_display = {
                    "name": match.group(1),
                    "width": int(match.group(2)),
                    "height": int(match.group(3)),
                    "x": int(match.group(4)),
                    "y": int(match.group(5)),
                    "modes": [],
                }
                displays.append(current_display)
            elif current_display and line.startswith("   "):
                # Resolution lines
                mode_match = re.match(r'^\s+(\d+)x(\d+)', line)
                if mode_match:
                    current_display["modes"].append(
                        (int(mode_match.group(1)), int(mode_match.group(2)))
                    )
    except Exception as e:
        LOG.error(f"xrandr error: {e}")

    return displays


def get_display_edid(display_name: str) -> str:
    """Get EDID data for a display."""
    try:
        result = subprocess.run(
            ["xrandr", "--verbose"],
            capture_output=True, text=True, timeout=5
        )

        in_display = False
        edid_lines = []

        for line in result.stdout.split("\n"):
            if line.startswith(display_name):
                in_display = True
            elif in_display:
                if line.startswith("\t\t") and not ":" in line:
                    edid_lines.append(line.strip())
                elif not line.startswith("\t"):
                    break

        return "".join(edid_lines)
    except Exception:
        return ""


def is_mini_display(display: Dict) -> bool:
    """Check if a display is the mini-HDMI monitor."""
    # Method 1: Check resolution
    if (display["width"] <= MINI_DISPLAY_MAX_WIDTH and
        display["height"] <= MINI_DISPLAY_MAX_HEIGHT):
        # Check if 1024x600 is among the modes
        for w, h in display.get("modes", []):
            if w == 1024 and h == 600:
                # DEBUG only - daemon logs on first detection
                LOG.debug(f"Mini-display match via resolution: {display['name']}")
                return True

    # Method 2: Check EDID (model name)
    edid = get_display_edid(display["name"])
    for identifier in MINI_DISPLAY_IDENTIFIERS:
        if identifier.lower() in edid.lower():
            LOG.debug(f"Mini-Display Match via EDID ({identifier}): {display['name']}")
            return True

    return False


def find_mini_display() -> Optional[Dict]:
    """Find the mini-HDMI display, regardless of port."""
    displays = get_connected_displays()

    for display in displays:
        if is_mini_display(display):
            return display

    return None


def find_secondary_display() -> Optional[Dict]:
    """
    Find a secondary monitor (not the primary one).
    Prefers mini-HDMI, but accepts any secondary monitor.
    """
    displays = get_connected_displays()

    if len(displays) <= 1:
        return None  # Only one monitor or none

    # Primary monitor is the one at x=0, y=0 (usually)
    # Or the first in the list
    primary_x = 0
    primary_y = 0

    # Prefer mini-display if present
    for display in displays:
        if is_mini_display(display):
            return display

    # Otherwise take any secondary (not at 0,0)
    for display in displays:
        if display["x"] != primary_x or display["y"] != primary_y:
            return display

    # If all are at 0,0 (unlikely), take the second one
    if len(displays) > 1:
        return displays[1]

    return None


def find_primary_display() -> Optional[Dict]:
    """Find the primary monitor."""
    displays = get_connected_displays()
    if not displays:
        return None

    # Primary is at x=0, y=0 or the first one
    for display in displays:
        if display["x"] == 0 and display["y"] == 0:
            return display

    return displays[0]


# =============================================================================
# Log Aggregator
# =============================================================================

class LogAggregator:
    """Aggregates logs from various sources."""

    def __init__(self, callback):
        self.callback = callback
        self._running = False
        self._threads = []
        self._file_positions = {}

    def start(self):
        """Start log collection."""
        if self._running:
            return

        self._running = True

        # Journal thread
        t = threading.Thread(target=self._watch_journal, daemon=True)
        t.start()
        self._threads.append(t)

        # File watcher threads
        for name, config in LOG_SOURCES.items():
            if "file" in config:
                t = threading.Thread(
                    target=self._watch_file,
                    args=(name, config),
                    daemon=True
                )
                t.start()
                self._threads.append(t)

        LOG.info("Log aggregator started")

    def stop(self):
        """Stop log collection."""
        self._running = False
        LOG.info("Log aggregator stopped")

    def _watch_journal(self):
        """Watch systemd journal."""
        config = LOG_SOURCES["journal"]
        proc = None
        try:
            proc = subprocess.Popen(
                config["cmd"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1
            )

            while self._running:
                line = proc.stdout.readline()
                if line:
                    self._emit(config["prefix"], line.strip(), config["color"])
                else:
                    time.sleep(0.1)
        except (IOError, OSError) as e:
            LOG.error(f"Journal watcher error: {e}")
        finally:
            # CRITICAL: proc.wait() after terminate() to avoid zombie
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                except (OSError, ProcessLookupError):
                    pass  # Process already terminated

    def _watch_file(self, name: str, config: Dict):
        """Watch a log file (tail -f style)."""
        filepath = Path(config["file"])

        while self._running:
            try:
                if not filepath.exists():
                    time.sleep(1)
                    continue

                # Initialize position
                if name not in self._file_positions:
                    self._file_positions[name] = filepath.stat().st_size

                current_size = filepath.stat().st_size

                if current_size > self._file_positions[name]:
                    with open(filepath, 'r') as f:
                        f.seek(self._file_positions[name])
                        for line in f:
                            line = line.strip()
                            if line:
                                self._emit(config["prefix"], line, config["color"])
                    self._file_positions[name] = current_size
                elif current_size < self._file_positions[name]:
                    # File was truncated/rotated
                    self._file_positions[name] = 0

                time.sleep(0.2)

            except Exception as e:
                LOG.debug(f"File watcher {name} error: {e}")
                time.sleep(1)

    def _emit(self, prefix: str, message: str, color: str):
        """Send log line to callback."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"{timestamp} {prefix} {message}"

        # Adjust color based on content
        if "ERROR" in message.upper() or "FAIL" in message.upper():
            color = FG_COLOR_ERROR
        elif "WARN" in message.upper():
            color = FG_COLOR_WARN

        GLib.idle_add(self.callback, formatted, color)


# =============================================================================
# Neural Monitor Window
# =============================================================================

class NeuralMonitorWindow(Gtk.Window):
    """Log window for mini-display or as terminal fallback."""

    def __init__(self, display_info: Dict, fallback_mode: bool = False):
        super().__init__(title="Frank Neural Monitor")

        self.display_info = display_info
        self.fallback_mode = fallback_mode
        self.log_buffer = deque(maxlen=MAX_LINES)
        self.aggregator = None

        self._setup_window()
        self._setup_ui()
        self._setup_aggregator()

        # Initial message
        mode_text = "TERMINAL MODE" if fallback_mode else "DEDICATED DISPLAY"
        self._add_log_line(
            f"╔══════════════════════════════════════════════════╗",
            FG_COLOR
        )
        self._add_log_line(
            f"║  FRANK NEURAL MONITOR - Live System Awareness    ║",
            FG_COLOR
        )
        self._add_log_line(
            f"║  Mode: {mode_text:43} ║",
            FG_COLOR_DIM
        )
        self._add_log_line(
            f"║  Display: {display_info['name']:40} ║",
            FG_COLOR_DIM
        )
        self._add_log_line(
            f"╚══════════════════════════════════════════════════╝",
            FG_COLOR
        )
        self._add_log_line("", FG_COLOR)
        self._add_log_line("Initializing log streams...", FG_COLOR_INFO)

    def _setup_window(self):
        """Configure window - fullscreen on mini-display or terminal mode."""
        # Black background via CSS
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
            window, textview, scrolledwindow, textview text {
                background-color: #000000;
                color: #00FF00;
            }
        """)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        if self.fallback_mode:
            # ===== TERMINAL MODE =====
            # Normal window on primary screen: minimizable, resizable, with frame
            self.set_decorated(True)
            self.set_resizable(True)
            self.set_default_size(800, 500)
            self.set_title("◈ Frank Neural Monitor")

            # Centered on primary screen
            self.set_position(Gtk.WindowPosition.CENTER)

            # Normal window behavior
            self.set_keep_above(False)
            self.set_skip_taskbar_hint(False)
            self.set_skip_pager_hint(False)

            LOG.info(f"Window setup: TERMINAL MODE (resizable, on primary)")

        else:
            # ===== DEDICATED DISPLAY MODE =====
            # Use override-redirect to BYPASS window manager completely
            self._target_x = self.display_info["x"]
            self._target_y = self.display_info["y"]
            self._target_w = self.display_info["width"]
            self._target_h = self.display_info["height"]
            self._target_display_name = self.display_info["name"]

            self.set_decorated(False)
            self.set_resizable(False)

            # Use POPUP type hint - this makes the window unmanaged by WM
            self.set_type_hint(Gdk.WindowTypeHint.SPLASHSCREEN)

            self.set_default_size(self._target_w, self._target_h)
            self.set_size_request(self._target_w, self._target_h)

            # Set position before realize
            self.set_gravity(Gdk.Gravity.STATIC)
            self.move(self._target_x, self._target_y)

            self.set_skip_taskbar_hint(True)
            self.set_skip_pager_hint(True)

            # Connect realize signal to set override-redirect and force position
            self.connect("realize", self._on_realize_override_redirect)
            self.connect("map", self._on_map_force_position)

            LOG.info(f"Window setup: OVERRIDE_REDIRECT mode - target {self._target_w}x{self._target_h} at +{self._target_x}+{self._target_y}")

        # Events (both modes)
        self.connect("destroy", self._on_destroy)
        self.connect("key-press-event", self._on_key_press)

    def _setup_ui(self):
        """Create UI elements."""
        # Main container
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(vbox)

        # Scrolled window for logs
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        vbox.pack_start(scroll, True, True, 0)

        # TextView for logs
        self.textview = Gtk.TextView()
        self.textview.set_editable(False)
        self.textview.set_cursor_visible(False)
        self.textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)

        # Font via CSS
        css_font = Gtk.CssProvider()
        css_font.load_from_data(f"""
            textview {{
                font-family: {FONT_FAMILY};
                font-size: {FONT_SIZE}pt;
            }}
        """.encode())
        self.textview.get_style_context().add_provider(
            css_font, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        scroll.add(self.textview)
        self.scroll = scroll

        # Text buffer with tags for colors
        self.buffer = self.textview.get_buffer()

        # Create color tags
        self.tags = {}
        for name, color in [
            ("green", FG_COLOR),
            ("dim", FG_COLOR_DIM),
            ("yellow", FG_COLOR_WARN),
            ("red", FG_COLOR_ERROR),
            ("cyan", FG_COLOR_INFO),
        ]:
            tag = self.buffer.create_tag(name, foreground=color)
            self.tags[color] = tag

    def _setup_aggregator(self):
        """Start log aggregator."""
        self.aggregator = LogAggregator(self._add_log_line)
        self.aggregator.start()

    def _add_log_line(self, text: str, color: str = FG_COLOR):
        """Add a log line."""
        # Get tag for color
        tag = self.tags.get(color, self.tags.get(FG_COLOR))

        # Insert text
        end_iter = self.buffer.get_end_iter()
        if self.buffer.get_char_count() > 0:
            self.buffer.insert(end_iter, "\n")
            end_iter = self.buffer.get_end_iter()

        self.buffer.insert_with_tags(end_iter, text, tag)

        # Auto-scroll to bottom
        GLib.idle_add(self._scroll_to_bottom)

        # Limit buffer
        line_count = self.buffer.get_line_count()
        if line_count > MAX_LINES:
            start = self.buffer.get_start_iter()
            line_end = self.buffer.get_iter_at_line(line_count - MAX_LINES)
            self.buffer.delete(start, line_end)

    def _scroll_to_bottom(self):
        """Scroll to bottom."""
        adj = self.scroll.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())
        return False

    def _on_realize_override_redirect(self, widget):
        """Set override-redirect flag and force position - bypasses window manager."""
        if hasattr(self, '_target_x'):
            gdk_win = self.get_window()
            if gdk_win:
                # Set override-redirect: window manager will NOT manage this window
                gdk_win.set_override_redirect(True)

                # Force exact position and size
                gdk_win.move_resize(self._target_x, self._target_y,
                                    self._target_w, self._target_h)

                LOG.info(f"Realize: override_redirect=True, moved to +{self._target_x}+{self._target_y}")

    def _on_map_force_position(self, widget):
        """Force window position after map (when visible)."""
        if hasattr(self, '_target_x'):
            gdk_win = self.get_window()
            if gdk_win:
                # Ensure override-redirect is still set
                gdk_win.set_override_redirect(True)
                # Force position again
                gdk_win.move_resize(self._target_x, self._target_y,
                                    self._target_w, self._target_h)
                LOG.debug(f"Map: position forced to +{self._target_x}+{self._target_y}")
            # Schedule verification after everything settles
            GLib.timeout_add(200, self._delayed_position_fix)

    def _delayed_position_fix(self):
        """Final position verification after window manager settles."""
        if hasattr(self, '_target_x'):
            # Verify window is on correct monitor
            gdk_win = self.get_window()
            if gdk_win:
                x, y = gdk_win.get_position()
                w = gdk_win.get_width()
                h = gdk_win.get_height()
                LOG.info(f"Window position verified: +{x}+{y} ({w}x{h})")

                # If position is wrong, try to fix via xdotool
                if x != self._target_x or y != self._target_y:
                    LOG.warning(f"Position mismatch! Expected +{self._target_x}+{self._target_y}")
                    self._fix_position_with_xdotool()
        return False  # Don't repeat

    def _fix_position_with_xdotool(self):
        """Last resort: use xdotool to force window position."""
        try:
            import subprocess
            # Get window ID
            gdk_win = self.get_window()
            if gdk_win:
                xid = gdk_win.get_xid()
                LOG.info(f"Using xdotool to move window {xid} to +{self._target_x}+{self._target_y}")
                subprocess.run([
                    "xdotool", "windowmove", "--sync", str(xid),
                    str(self._target_x), str(self._target_y)
                ], timeout=5, check=False)
                subprocess.run([
                    "xdotool", "windowsize", "--sync", str(xid),
                    str(self._target_w), str(self._target_h)
                ], timeout=5, check=False)
        except Exception as e:
            LOG.error(f"xdotool fix failed: {e}")

    def _on_key_press(self, widget, event):
        """Handle key press."""
        # ESC or Q to quit
        if event.keyval in (Gdk.KEY_Escape, Gdk.KEY_q, Gdk.KEY_Q):
            self.close()
            return True
        return False

    def _on_destroy(self, widget):
        """Cleanup on close."""
        if self.aggregator:
            self.aggregator.stop()
        Gtk.main_quit()


# =============================================================================
# Monitor Daemon
# =============================================================================

class NeuralMonitorDaemon:
    """
    Daemon that waits for mini-display hotplug and
    automatically starts the monitor window.
    """

    def __init__(self):
        self.window = None
        self._running = False
        self._last_display = None

    def run(self):
        """Main loop - periodically checks for display."""
        self._running = True
        self._fallback_mode = False
        LOG.info("Neural Monitor Daemon started")
        LOG.info(f"Searching for secondary monitor...")

        # Notify systemd we're ready
        sd_notify_ready()

        # Initial check - start fallback if no secondary display
        secondary = find_secondary_display()
        if not secondary:
            LOG.warning("No secondary monitor at startup - starting terminal mode on primary screen")
            primary = find_primary_display()
            if primary:
                self._fallback_mode = True
                self._start_window(primary, fallback=True)

        watchdog_counter = 0
        while self._running:
            secondary = find_secondary_display()

            if secondary and not self.window:
                # Secondary monitor found, start dedicated window
                LOG.info(f"Secondary monitor connected: {secondary['name']}")
                self._fallback_mode = False
                self._start_window(secondary, fallback=False)

            elif secondary and self.window and self._fallback_mode:
                # Secondary monitor present, but we're in fallback mode -> switch
                LOG.info(f"Secondary monitor found - switching to dedicated mode")
                GLib.idle_add(self._stop_window)
                time.sleep(0.5)
                self._fallback_mode = False
                self._start_window(secondary, fallback=False)

            elif not secondary and self.window and not self._fallback_mode:
                # Secondary monitor removed -> switch to fallback
                LOG.info("Secondary monitor disconnected - switching to terminal mode")
                GLib.idle_add(self._stop_window)
                time.sleep(0.5)
                primary = find_primary_display()
                if primary:
                    self._fallback_mode = True
                    self._start_window(primary, fallback=True)

            # Send watchdog ping every ~30 seconds
            watchdog_counter += 1
            if watchdog_counter >= 10:
                sd_notify_watchdog()
                watchdog_counter = 0

            time.sleep(DISPLAY_CHECK_INTERVAL_SEC)

    def _start_window(self, display_info: Dict, fallback: bool = False):
        """Start monitor window."""
        def _create():
            self.window = NeuralMonitorWindow(display_info, fallback_mode=fallback)
            self.window.show_all()

        GLib.idle_add(_create)

    def _stop_window(self):
        """Stop monitor window."""
        if self.window:
            self.window.destroy()
            self.window = None

    def stop(self):
        """Stop daemon."""
        self._running = False
        if self.window:
            GLib.idle_add(self._stop_window)


# =============================================================================
# Main
# =============================================================================

def main():
    """Main function."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Frank Neural Monitor - Live Log Display for Mini-HDMI"
    )
    parser.add_argument(
        "--daemon", "-d",
        action="store_true",
        help="Daemon mode: Wait for display hotplug"
    )
    parser.add_argument(
        "--once", "-o",
        action="store_true",
        help="One-shot mode: Start immediately if display found"
    )
    parser.add_argument(
        "--force", "-f",
        type=str,
        help="Force display (e.g. HDMI-A-1)"
    )

    args = parser.parse_args()

    # Singleton Lock - prevent multiple instances
    if not acquire_singleton_lock():
        print("Neural Monitor is already running!")
        LOG.warning("Another instance is already running - exiting")
        sys.exit(0)

    # Thread-safe shutdown flag
    _shutdown_requested = threading.Event()

    def _do_shutdown():
        """Perform shutdown in GTK main thread context."""
        LOG.info("Shutdown performed")
        release_singleton_lock()
        Gtk.main_quit()
        return False  # Don't repeat

    # Signal handler - only set flag, no GTK calls!
    def signal_handler(sig, frame):
        LOG.info("Shutdown signal received...")
        _shutdown_requested.set()
        # Schedule shutdown in GTK main thread (thread-safe)
        GLib.idle_add(_do_shutdown)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if args.force:
        # Force specific display
        displays = get_connected_displays()
        display = next((d for d in displays if d["name"] == args.force), None)

        if not display:
            LOG.error(f"Display {args.force} not found")
            LOG.info("Available displays:")
            for d in displays:
                LOG.info(f"  {d['name']} ({d['width']}x{d['height']})")
            sys.exit(1)

        LOG.info(f"Forcing display: {display['name']}")
        window = NeuralMonitorWindow(display)
        window.show_all()
        Gtk.main()

    elif args.daemon:
        # Daemon mode with hotplug detection
        daemon = NeuralMonitorDaemon()

        # GTK in separate thread
        gtk_thread = threading.Thread(target=Gtk.main, daemon=True)
        gtk_thread.start()

        try:
            daemon.run()
        except KeyboardInterrupt:
            daemon.stop()

    else:
        # Default: Check once and start
        secondary = find_secondary_display()

        if not secondary:
            # FALLBACK: No secondary monitor -> terminal mode on primary screen
            LOG.warning("No secondary monitor found - starting in terminal mode")
            primary = find_primary_display()
            if primary:
                LOG.info(f"Using primary screen: {primary['name']}")
                window = NeuralMonitorWindow(primary, fallback_mode=True)
                window.show_all()
                Gtk.main()
            else:
                LOG.error("No displays found!")
                sys.exit(1)
        else:
            LOG.info(f"Secondary monitor found: {secondary['name']}")
            window = NeuralMonitorWindow(secondary, fallback_mode=False)
            window.show_all()
            Gtk.main()


if __name__ == "__main__":
    main()
