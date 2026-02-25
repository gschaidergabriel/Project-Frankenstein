#!/usr/bin/env python3
"""
Screenshot Region Selector for Frank.

Global hotkey (Ctrl+Shift+F) activates a fullscreen overlay.
User drags to select a region. On release, the region is:
1. Captured as PNG
2. Analyzed by the adaptive vision pipeline
3. Sent to Frank's chat via core API

Can also be run standalone: python3 screenshot_region_selector.py

Runs as background daemon listening for the hotkey.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

LOG = logging.getLogger("region_selector")

# ═══════════════════════════════════════════════════════════
#  REGION SELECTOR (PyQt5 Overlay)
# ═══════════════════════════════════════════════════════════

def _run_selector_gui(callback: Callable[[str], None]):
    """Launch the region selector GUI. Blocks until selection is done."""
    from PyQt5.QtWidgets import QApplication, QWidget
    from PyQt5.QtCore import Qt, QRect, QPoint
    from PyQt5.QtGui import QPainter, QPen, QColor, QPixmap

    class RegionSelector(QWidget):
        def __init__(self, pixmap: QPixmap, cb: Callable[[str], None]):
            super().__init__()
            self._pixmap = pixmap
            self._callback = cb
            self._origin = QPoint()
            self._current = QPoint()
            self._selecting = False

            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
            self.setGeometry(0, 0, pixmap.width(), pixmap.height())
            self.setCursor(Qt.CursorShape.CrossCursor)
            self.showFullScreen()

        def paintEvent(self, event):
            p = QPainter(self)
            p.drawPixmap(0, 0, self._pixmap)

            if self._selecting and self._origin != self._current:
                rect = QRect(self._origin, self._current).normalized()
                # Dim everything
                p.fillRect(self.rect(), QColor(0, 0, 0, 120))
                # Show selected region
                p.drawPixmap(rect, self._pixmap, rect)
                # Neon border
                p.setPen(QPen(QColor(0, 255, 200), 2))
                p.drawRect(rect)
                # Size label
                p.setPen(QColor(0, 255, 200))
                p.drawText(rect.x(), rect.y() - 5, f"{rect.width()}x{rect.height()}")
            elif not self._selecting:
                p.fillRect(self.rect(), QColor(0, 0, 0, 60))
                p.setPen(QColor(0, 255, 200))
                font = p.font()
                font.setPointSize(16)
                p.setFont(font)
                p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                           "Bereich markieren — ESC zum Abbrechen")
            p.end()

        def mousePressEvent(self, event):
            if event.button() == Qt.MouseButton.LeftButton:
                self._origin = event.pos()
                self._current = event.pos()
                self._selecting = True
                self.update()

        def mouseMoveEvent(self, event):
            if self._selecting:
                self._current = event.pos()
                self.update()

        def mouseReleaseEvent(self, event):
            if event.button() == Qt.MouseButton.LeftButton and self._selecting:
                self._selecting = False
                rect = QRect(self._origin, event.pos()).normalized()
                if rect.width() < 10 or rect.height() < 10:
                    self.close()
                    return
                # Crop and save
                cropped = self._pixmap.copy(rect)
                out = Path(f"/tmp/frank_region_{int(time.time())}.png")
                cropped.save(str(out), "PNG")
                LOG.info("Region: %dx%d → %s", rect.width(), rect.height(), out)
                self.close()
                self._callback(str(out))

        def keyPressEvent(self, event):
            if event.key() == Qt.Key.Key_Escape:
                self.close()

    # Take screenshot first (before overlay appears)
    tmp = f"/tmp/frank_region_bg_{int(time.time())}.png"
    env = {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
    for cmd in [
        ["gnome-screenshot", "-f", tmp],
        ["import", "-window", "root", tmp],
        ["scrot", tmp],
        ["maim", tmp],
    ]:
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=5, env=env)
            if r.returncode == 0 and Path(tmp).exists():
                break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    else:
        LOG.error("Could not take screenshot")
        return

    app = QApplication.instance()
    own_app = False
    if app is None:
        app = QApplication(sys.argv)
        own_app = True

    pixmap = QPixmap(tmp)
    if pixmap.isNull():
        LOG.error("Invalid screenshot")
        return

    selector = RegionSelector(pixmap, callback)
    selector.show()

    if own_app:
        app.exec()

    # Cleanup background screenshot
    try:
        Path(tmp).unlink(missing_ok=True)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
#  ANALYSIS + CHAT INTEGRATION
# ═══════════════════════════════════════════════════════════

CORE_URL = os.environ.get("AICORE_CORE_URL", "http://127.0.0.1:8088")


def _analyze_and_send(image_path: str):
    """Analyze the region screenshot and send result to Frank's chat."""
    LOG.info("Analyzing region: %s", image_path)

    # Stage 1: Adaptive vision pipeline
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from tools.frank_adaptive_vision import FrankVisionService
    except ImportError:
        try:
            from frank_adaptive_vision import FrankVisionService
        except ImportError:
            LOG.error("Vision pipeline not available")
            return

    vision = FrankVisionService.get_instance()
    result = vision.process(image_path, "Was siehst du in diesem Bereich?")

    summary = result.final_summary
    LOG.info("Analysis: %s (%.0fms, escalated=%s)", summary[:100], result.total_ms, result.escalated)

    # Stage 2: Send to Frank via core /chat
    prompt = (
        f"Der User hat einen Bereich auf dem Bildschirm markiert.\n\n"
        f"Bildanalyse des markierten Bereichs:\n{summary}\n\n"
        f"Beschreibe kurz was du siehst und frage was du damit machen kannst. "
        f"Sei spezifisch. Biete konkrete Aktionen an die du ausführen könntest."
    )

    try:
        payload = json.dumps({
            "text": prompt,
            "max_tokens": 400,
            "timeout_s": 60,
            "task": "chat.fast",
        }).encode()
        req = urllib.request.Request(
            f"{CORE_URL}/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            if data.get("ok"):
                LOG.info("Frank responded: %s", (data.get("text") or "")[:100])
            else:
                LOG.warning("Frank response not ok: %s", data)
    except Exception as e:
        LOG.error("Failed to send to Frank: %s", e)

    # Cleanup region screenshot
    try:
        Path(image_path).unlink(missing_ok=True)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
#  GLOBAL HOTKEY DAEMON (xdotool-based)
# ═══════════════════════════════════════════════════════════

HOTKEY = os.environ.get("FRANK_REGION_HOTKEY", "ctrl+shift+f")
LOCK_FILE = Path("/tmp/frank_region_selector.lock")


def _hotkey_daemon():
    """Listen for global hotkey using xbindkeys-style approach via subprocess."""
    LOG.info("Region Selector Hotkey Daemon started (hotkey: %s)", HOTKEY)

    # Use xdotool to detect key combo via polling
    # Alternative: use subprocess to call xdotool getactivewindow on key event
    # Best approach: xbindkeys config or dbus

    # We use a simple approach: bind via xdotool key listener
    # Actually, the cleanest is to register with the DE's keybinding system
    # For now: use subprocess with xbindkeys

    import tempfile

    # Write xbindkeys config
    xbind_conf = tempfile.NamedTemporaryFile(
        mode='w', suffix='.xbindkeysrc', delete=False, prefix='frank_region_'
    )
    xbind_conf.write(f'"{sys.executable} {__file__} --trigger"\n')
    xbind_conf.write(f'  control+shift + f\n')
    xbind_conf.close()

    LOG.info("Trying xbindkeys with config: %s", xbind_conf.name)

    try:
        # Check if xbindkeys is available
        subprocess.run(["which", "xbindkeys"], capture_output=True, check=True)

        env = {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
        proc = subprocess.Popen(
            ["xbindkeys", "-f", xbind_conf.name, "-n"],
            env=env,
        )
        LOG.info("xbindkeys running (PID %d)", proc.pid)
        proc.wait()
    except FileNotFoundError:
        LOG.warning("xbindkeys not found, trying gsettings custom keybinding")
        _register_gsettings_keybinding()
    except subprocess.CalledProcessError:
        LOG.warning("xbindkeys not available")
        _register_gsettings_keybinding()
    finally:
        try:
            Path(xbind_conf.name).unlink(missing_ok=True)
        except Exception:
            pass


def _register_gsettings_keybinding():
    """Register hotkey via GNOME custom keybinding as fallback."""
    try:
        cmd = f"{sys.executable} {__file__} --trigger"
        # Check existing custom keybindings
        result = subprocess.run(
            ["gsettings", "get", "org.gnome.settings-daemon.plugins.media-keys",
             "custom-keybindings"],
            capture_output=True, text=True
        )
        LOG.info("Registering GNOME custom keybinding: Ctrl+Shift+F → %s", cmd)

        base = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
        kb_path = f"{base}/frank-region/"

        subprocess.run([
            "gsettings", "set",
            f"org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:{kb_path}",
            "name", "Frank Region Capture"
        ], check=False)
        subprocess.run([
            "gsettings", "set",
            f"org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:{kb_path}",
            "command", cmd
        ], check=False)
        subprocess.run([
            "gsettings", "set",
            f"org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:{kb_path}",
            "binding", "<Control><Shift>f"
        ], check=False)

        # Add to list of custom keybindings
        existing = result.stdout.strip()
        if kb_path not in existing:
            if existing == "@as []" or existing == "[]":
                new_list = f"['{kb_path}']"
            else:
                new_list = existing.rstrip("]") + f", '{kb_path}']"
            subprocess.run([
                "gsettings", "set",
                "org.gnome.settings-daemon.plugins.media-keys",
                "custom-keybindings", new_list
            ], check=False)

        LOG.info("GNOME keybinding registered: Ctrl+Shift+F")
    except Exception as e:
        LOG.error("Failed to register keybinding: %s", e)
        LOG.info("Manual setup: assign 'python3 %s --trigger' to Ctrl+Shift+F in Settings → Keyboard", __file__)


# ═══════════════════════════════════════════════════════════
#  ENTRY POINTS
# ═══════════════════════════════════════════════════════════

def trigger_capture():
    """Called by hotkey — opens selector and sends result to Frank."""
    # Prevent double-trigger
    if LOCK_FILE.exists():
        age = time.time() - LOCK_FILE.stat().st_mtime
        if age < 5:
            LOG.info("Region selector already active (lock age %.1fs)", age)
            return
    LOCK_FILE.touch()

    try:
        _run_selector_gui(callback=_analyze_and_send)
    finally:
        LOCK_FILE.unlink(missing_ok=True)


def start_daemon():
    """Start the hotkey daemon (blocks)."""
    _hotkey_daemon()


# ═══════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s"
    )

    if "--trigger" in sys.argv:
        # Called by hotkey — open selector
        trigger_capture()
    elif "--daemon" in sys.argv:
        # Run as persistent hotkey listener
        start_daemon()
    elif "--register" in sys.argv:
        # Just register the keybinding
        _register_gsettings_keybinding()
    else:
        # Default: open selector directly (for testing)
        trigger_capture()
