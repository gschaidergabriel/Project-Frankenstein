#!/usr/bin/env python3
"""
Overlay Controller - Controls the Frank Chat Overlay for testing.

Uses PyAutoGUI and wmctrl to interact with the overlay window.
"""

import logging
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

LOG = logging.getLogger("ui_tester.controller")

# Screenshot directory
try:
    from config.paths import UI_DIR as _UI_DIR
except ImportError:
    _UI_DIR = Path(__file__).resolve().parent.parent
SCREENSHOTS_DIR = _UI_DIR / "ui_tester" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class WindowInfo:
    """Information about a window."""
    window_id: str
    x: int
    y: int
    width: int
    height: int
    title: str


class OverlayController:
    """Controls the Frank Chat Overlay for automated testing."""

    def __init__(self):
        self.overlay_window: Optional[WindowInfo] = None
        self._screenshot_counter = 0

        # Import PyAutoGUI
        try:
            import pyautogui
            pyautogui.FAILSAFE = False  # Disable failsafe for testing
            pyautogui.PAUSE = 0.1  # Small pause between actions
            self.pyautogui = pyautogui
        except ImportError:
            LOG.error("PyAutoGUI not installed!")
            self.pyautogui = None

    def find_overlay_window(self) -> Optional[WindowInfo]:
        """Find the Frank Chat Overlay window."""
        try:
            result = subprocess.run(
                ["wmctrl", "-l", "-G"],
                capture_output=True,
                text=True,
                timeout=5
            )

            for line in result.stdout.strip().split("\n"):
                # Format: window_id desktop x y width height hostname title
                parts = line.split(None, 7)
                if len(parts) >= 8:
                    title = parts[7].lower()
                    if "frank" in title or "chat" in title or "overlay" in title:
                        self.overlay_window = WindowInfo(
                            window_id=parts[0],
                            x=int(parts[2]),
                            y=int(parts[3]),
                            width=int(parts[4]),
                            height=int(parts[5]),
                            title=parts[7]
                        )
                        LOG.info(f"Found overlay: {self.overlay_window}")
                        return self.overlay_window

            LOG.warning("Overlay window not found")
            return None

        except subprocess.TimeoutExpired:
            LOG.error("wmctrl timed out")
            return None
        except Exception as e:
            LOG.error(f"Error finding window: {e}")
            return None

    def focus_overlay(self) -> bool:
        """Bring the overlay window to focus."""
        if not self.overlay_window:
            self.find_overlay_window()

        if not self.overlay_window:
            return False

        try:
            subprocess.run(
                ["wmctrl", "-i", "-a", self.overlay_window.window_id],
                timeout=5
            )
            time.sleep(0.2)
            return True
        except Exception as e:
            LOG.error(f"Failed to focus overlay: {e}")
            return False

    def take_screenshot(self, name: Optional[str] = None) -> Path:
        """Take a screenshot of the screen."""
        self._screenshot_counter += 1
        timestamp = int(time.time())

        if name:
            filename = f"{timestamp}_{name}.png"
        else:
            filename = f"{timestamp}_{self._screenshot_counter:04d}.png"

        screenshot_path = SCREENSHOTS_DIR / filename

        try:
            # Use scrot for screenshot
            subprocess.run(
                ["scrot", str(screenshot_path)],
                timeout=10,
                env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
            )
            LOG.debug(f"Screenshot saved: {screenshot_path}")
            return screenshot_path
        except Exception as e:
            LOG.error(f"Screenshot failed: {e}")
            # Fallback to PyAutoGUI
            if self.pyautogui:
                screenshot = self.pyautogui.screenshot()
                screenshot.save(str(screenshot_path))
                return screenshot_path
            raise

    def take_overlay_screenshot(self, name: Optional[str] = None) -> Path:
        """Take a screenshot of just the overlay window."""
        if not self.overlay_window:
            self.find_overlay_window()

        if not self.overlay_window:
            return self.take_screenshot(name)

        self._screenshot_counter += 1
        timestamp = int(time.time())

        if name:
            filename = f"{timestamp}_overlay_{name}.png"
        else:
            filename = f"{timestamp}_overlay_{self._screenshot_counter:04d}.png"

        screenshot_path = SCREENSHOTS_DIR / filename

        try:
            # Use scrot with window geometry (x1,y1,x2,y2 format)
            w = self.overlay_window
            display = os.environ.get("DISPLAY", ":0")
            subprocess.run(
                ["scrot", "-a", f"{w.x},{w.y},{w.x + w.width},{w.y + w.height}", str(screenshot_path)],
                timeout=10,
                capture_output=True,
                env={**os.environ, "DISPLAY": display}
            )
            return screenshot_path
        except Exception as e:
            LOG.warning(f"Window screenshot failed, falling back to full: {e}")
            return self.take_screenshot(name)

    def click(self, x: int, y: int) -> bool:
        """Click at absolute screen coordinates."""
        if not self.pyautogui:
            return False

        try:
            self.pyautogui.click(x, y)
            LOG.debug(f"Clicked at ({x}, {y})")
            return True
        except Exception as e:
            LOG.error(f"Click failed: {e}")
            return False

    def click_overlay(self, rel_x: int, rel_y: int) -> bool:
        """Click at coordinates relative to overlay window."""
        if not self.overlay_window:
            self.find_overlay_window()

        if not self.overlay_window:
            return False

        abs_x = self.overlay_window.x + rel_x
        abs_y = self.overlay_window.y + rel_y
        return self.click(abs_x, abs_y)

    def type_text(self, text: str, interval: float = 0.02) -> bool:
        """Type text using keyboard."""
        if not self.pyautogui:
            return False

        try:
            # Use xdotool for better Unicode support
            subprocess.run(
                ["xdotool", "type", "--clearmodifiers", text],
                timeout=30,
                env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
            )
            LOG.debug(f"Typed: {text[:50]}...")
            return True
        except Exception as e:
            LOG.warning(f"xdotool failed, trying pyautogui: {e}")
            try:
                self.pyautogui.write(text, interval=interval)
                return True
            except Exception as e2:
                LOG.error(f"Type failed: {e2}")
                return False

    def press_key(self, key: str) -> bool:
        """Press a key (e.g., 'enter', 'tab', 'escape')."""
        if not self.pyautogui:
            return False

        try:
            self.pyautogui.press(key)
            LOG.debug(f"Pressed key: {key}")
            return True
        except Exception as e:
            LOG.error(f"Key press failed: {e}")
            return False

    def hotkey(self, *keys) -> bool:
        """Press a hotkey combination (e.g., 'ctrl', 'v')."""
        if not self.pyautogui:
            return False

        try:
            self.pyautogui.hotkey(*keys)
            LOG.debug(f"Hotkey: {'+'.join(keys)}")
            return True
        except Exception as e:
            LOG.error(f"Hotkey failed: {e}")
            return False

    def drag(self, from_x: int, from_y: int, to_x: int, to_y: int, duration: float = 0.5) -> bool:
        """Drag from one position to another."""
        if not self.pyautogui:
            return False

        try:
            self.pyautogui.moveTo(from_x, from_y)
            time.sleep(0.1)
            self.pyautogui.drag(to_x - from_x, to_y - from_y, duration=duration)
            LOG.debug(f"Dragged from ({from_x}, {from_y}) to ({to_x}, {to_y})")
            return True
        except Exception as e:
            LOG.error(f"Drag failed: {e}")
            return False

    def drag_overlay(self, delta_x: int, delta_y: int) -> bool:
        """Drag the overlay window by offset."""
        if not self.overlay_window:
            self.find_overlay_window()

        if not self.overlay_window:
            return False

        # Click on titlebar (top of window)
        from_x = self.overlay_window.x + self.overlay_window.width // 2
        from_y = self.overlay_window.y + 15  # Titlebar area

        return self.drag(from_x, from_y, from_x + delta_x, from_y + delta_y)

    def resize_overlay(self, edge: str, delta_x: int, delta_y: int) -> bool:
        """Resize the overlay by dragging an edge."""
        if not self.overlay_window:
            self.find_overlay_window()

        if not self.overlay_window:
            return False

        w = self.overlay_window

        # Determine edge position
        if edge == "right":
            from_x = w.x + w.width - 5
            from_y = w.y + w.height // 2
        elif edge == "bottom":
            from_x = w.x + w.width // 2
            from_y = w.y + w.height - 5
        elif edge == "corner":
            from_x = w.x + w.width - 5
            from_y = w.y + w.height - 5
        else:
            return False

        return self.drag(from_x, from_y, from_x + delta_x, from_y + delta_y)

    def scroll(self, direction: str, amount: int = 3) -> bool:
        """Scroll up or down."""
        if not self.pyautogui:
            return False

        try:
            clicks = amount if direction == "up" else -amount
            self.pyautogui.scroll(clicks)
            LOG.debug(f"Scrolled {direction} by {amount}")
            return True
        except Exception as e:
            LOG.error(f"Scroll failed: {e}")
            return False

    def create_test_file(self, file_type: str) -> Path:
        """Create a test file for ingest testing."""
        test_dir = Path(tempfile.gettempdir()) / "ui_tester"
        test_dir.mkdir(exist_ok=True)

        if file_type == "text":
            path = test_dir / "test_document.txt"
            path.write_text("Dies ist ein Test-Dokument für Frank.\n\nZeile 2.\nZeile 3 mit Sonderzeichen: äöü ß €")
            return path

        elif file_type == "python":
            path = test_dir / "test_script.py"
            path.write_text('''#!/usr/bin/env python3
"""Test Python script for Frank ingest."""

def hello():
    print("Hallo von Frank!")

if __name__ == "__main__":
    hello()
''')
            return path

        elif file_type == "json":
            path = test_dir / "test_config.json"
            path.write_text('{\n  "name": "Test",\n  "value": 42,\n  "active": true\n}')
            return path

        else:
            # Default: simple text
            path = test_dir / f"test_{file_type}.txt"
            path.write_text(f"Test file of type: {file_type}")
            return path

    def ingest_file(self, file_path: Path) -> bool:
        """Simulate file drag & drop to overlay."""
        if not self.overlay_window:
            self.find_overlay_window()

        if not self.overlay_window:
            return False

        # Use xdotool to simulate file drop
        # This is a simplified version - real D&D is complex
        try:
            # Focus overlay
            self.focus_overlay()
            time.sleep(0.2)

            # Type the file path in the chat input
            # (as a workaround for actual drag & drop)
            input_y = self.overlay_window.y + self.overlay_window.height - 50
            input_x = self.overlay_window.x + self.overlay_window.width // 2
            self.click(input_x, input_y)
            time.sleep(0.1)

            # Type command to read file
            self.type_text(f"lies {file_path}")
            time.sleep(0.1)
            self.press_key("enter")

            LOG.info(f"Ingested file: {file_path}")
            return True

        except Exception as e:
            LOG.error(f"Ingest failed: {e}")
            return False

    def get_overlay_geometry(self) -> Optional[Tuple[int, int, int, int]]:
        """Get current overlay geometry (x, y, width, height)."""
        self.find_overlay_window()
        if self.overlay_window:
            return (
                self.overlay_window.x,
                self.overlay_window.y,
                self.overlay_window.width,
                self.overlay_window.height
            )
        return None

    def wait(self, seconds: float):
        """Wait for specified duration."""
        time.sleep(seconds)


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    controller = OverlayController()

    print("=== Overlay Controller Test ===")

    # Find window
    window = controller.find_overlay_window()
    if window:
        print(f"Found: {window}")

        # Take screenshot
        screenshot = controller.take_screenshot("test")
        print(f"Screenshot: {screenshot}")
    else:
        print("Overlay not found - is Frank running?")
