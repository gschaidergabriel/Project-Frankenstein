#!/usr/bin/env python3
"""
Screenshot Region Selector for Frank.

Hotkey activates a fullscreen transparent overlay with crosshair cursor.
User holds left mouse button and drags to select a region.
On release, the selected region is captured, analyzed by the
adaptive vision pipeline, and sent to Frank's chat.

Usage:
    # As standalone (for testing)
    python3 screenshot_region_selector.py

    # From overlay (integrated)
    from tools.screenshot_region_selector import start_region_capture
    start_region_capture(callback=my_callback)
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QRect, QPoint, QTimer
from PyQt5.QtGui import QPainter, QPen, QColor, QCursor, QPixmap

LOG = logging.getLogger("region_selector")


class RegionSelector(QWidget):
    """Fullscreen transparent overlay for region selection."""

    def __init__(self, screenshot_pixmap: QPixmap,
                 callback: Optional[Callable[[str], None]] = None):
        super().__init__()
        self._pixmap = screenshot_pixmap
        self._callback = callback
        self._origin = QPoint()
        self._current = QPoint()
        self._selecting = False
        self._selected_rect: Optional[QRect] = None

        # Fullscreen, frameless, always on top, transparent
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setGeometry(0, 0, screenshot_pixmap.width(), screenshot_pixmap.height())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.showFullScreen()

    def paintEvent(self, event):
        painter = QPainter(self)
        # Draw the screenshot as background
        painter.drawPixmap(0, 0, self._pixmap)

        # Dim the non-selected area
        if self._selecting and self._origin != self._current:
            rect = QRect(self._origin, self._current).normalized()

            # Dark overlay everywhere
            overlay = QColor(0, 0, 0, 120)
            painter.fillRect(self.rect(), overlay)

            # Clear the selected region (show original screenshot)
            painter.drawPixmap(rect, self._pixmap, rect)

            # Draw selection border
            pen = QPen(QColor(0, 255, 200), 2)
            pen.setStyle(Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.drawRect(rect)

            # Size label
            w, h = rect.width(), rect.height()
            label = f"{w}x{h}"
            painter.setPen(QColor(0, 255, 200))
            painter.drawText(rect.x(), rect.y() - 5, label)

        elif not self._selecting and not self._selected_rect:
            # Not yet selecting — light overlay with instructions
            overlay = QColor(0, 0, 0, 60)
            painter.fillRect(self.rect(), overlay)
            painter.setPen(QColor(0, 255, 200))
            font = painter.font()
            font.setPointSize(16)
            painter.setFont(font)
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter,
                "Bereich auswählen — Ziehen zum Markieren, ESC zum Abbrechen"
            )

        painter.end()

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

            # Minimum size check
            if rect.width() < 10 or rect.height() < 10:
                self.close()
                return

            self._selected_rect = rect
            self._capture_region(rect)
            self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()

    def _capture_region(self, rect: QRect):
        """Crop the screenshot to the selected region and trigger analysis."""
        cropped = self._pixmap.copy(rect)
        timestamp = int(time.time())
        out_path = Path(f"/tmp/frank_region_{timestamp}.png")
        cropped.save(str(out_path), "PNG")
        LOG.info("Region captured: %dx%d → %s", rect.width(), rect.height(), out_path)

        if self._callback:
            self._callback(str(out_path))
        else:
            # Standalone mode — analyze and print
            _standalone_analyze(str(out_path))


def _take_full_screenshot() -> Optional[QPixmap]:
    """Take a full desktop screenshot for the overlay background."""
    # Try gnome-screenshot first (most reliable on this system)
    tmp = f"/tmp/frank_region_bg_{int(time.time())}.png"
    for cmd in [
        ["gnome-screenshot", "-f", tmp],
        ["import", "-window", "root", tmp],
        ["scrot", tmp],
        ["maim", tmp],
    ]:
        try:
            import os
            env = {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
            result = subprocess.run(cmd, capture_output=True, timeout=5, env=env)
            if result.returncode == 0 and Path(tmp).exists():
                pixmap = QPixmap(tmp)
                if not pixmap.isNull():
                    return pixmap
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def _standalone_analyze(image_path: str):
    """Analyze region in standalone mode (no overlay integration)."""
    try:
        from tools.frank_adaptive_vision import FrankVisionService
    except ImportError:
        from frank_adaptive_vision import FrankVisionService

    vision = FrankVisionService.get_instance()
    result = vision.process(image_path)

    print(f"\nRegion Analysis ({result.total_ms:.0f}ms):")
    print(f"  {result.final_summary}")
    if result.escalated:
        print(f"  VLM: {result.vlm_description}")
    print(f"  Confidence: {result.escalation_confidence:.0%}")


def start_region_capture(callback: Optional[Callable[[str], None]] = None):
    """
    Start the region capture flow.

    Args:
        callback: Function called with the path to the cropped screenshot.
                  If None, runs in standalone mode with analysis.
    """
    # Check if QApplication exists
    app = QApplication.instance()
    own_app = False
    if app is None:
        app = QApplication(sys.argv)
        own_app = True

    screenshot = _take_full_screenshot()
    if screenshot is None:
        LOG.error("Could not take screenshot for region selector")
        return

    selector = RegionSelector(screenshot, callback=callback)
    selector.show()

    if own_app:
        app.exec()


# ═══════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    start_region_capture()
