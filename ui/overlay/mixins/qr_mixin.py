"""QR Code mixin -- scan from screen/camera/file, generate QR codes.

Workers run on IO thread, image display via _ui_call() on main thread.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from overlay.constants import LOG

try:
    from config.paths import TOOLS_DIR as _TOOLS_DIR
except ImportError:
    _TOOLS_DIR = Path("/home/ai-core-node/aicore/opt/aicore/tools")
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


# URL detection for scan results
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


class QrMixin:
    """QR Code: scan (screen/camera/file) + generate."""

    # ── Scan from screenshot ──────────────────────────────────────

    def _do_qr_scan_screen_worker(self, **_kw):
        """Take screenshot and scan for QR codes."""
        self._ui_call(lambda: self._add_message(
            "Frank", "Scanning screen for QR codes...", is_system=True,
        ))

        try:
            from qr_tool import scan_from_screenshot
            results, path = scan_from_screenshot()
        except Exception as e:
            LOG.error(f"QR screen scan error: {e}")
            self._ui_call(lambda: self._add_message(
                "Frank", f"QR scan failed: {e}", is_system=True,
            ))
            return

        if not results:
            self._ui_call(lambda: self._add_message(
                "Frank", "No QR code found on screen.", is_system=True,
            ))
            return

        self._show_qr_results(results)

    # ── Scan from camera ──────────────────────────────────────────

    def _do_qr_scan_camera_worker(self, **_kw):
        """Grab webcam frame and scan for QR codes."""
        self._ui_call(lambda: self._add_message(
            "Frank", "Scanning camera for QR codes (5 seconds)...", is_system=True,
        ))

        try:
            from qr_tool import scan_from_camera
            results = scan_from_camera(timeout_sec=5.0)
        except Exception as e:
            LOG.error(f"QR camera scan error: {e}")
            self._ui_call(lambda: self._add_message(
                "Frank", f"Camera scan failed: {e}", is_system=True,
            ))
            return

        if not results:
            self._ui_call(lambda: self._add_message(
                "Frank",
                "No QR code detected via camera. Hold the QR code closer to the camera.",
                is_system=True,
            ))
            return

        self._show_qr_results(results)

    # ── Scan from file ────────────────────────────────────────────

    def _do_qr_scan_file_worker(self, path: str = "", **_kw):
        """Scan QR code from an image file."""
        if not path:
            self._ui_call(lambda: self._add_message(
                "Frank", "No file path specified.", is_system=True,
            ))
            return

        self._ui_call(lambda p=path: self._add_message(
            "Frank", f"Scanning QR code in {p}...", is_system=True,
        ))

        try:
            from qr_tool import scan_from_file
            results = scan_from_file(path)
        except Exception as e:
            LOG.error(f"QR file scan error: {e}")
            self._ui_call(lambda: self._add_message(
                "Frank", f"QR scan failed: {e}", is_system=True,
            ))
            return

        if not results:
            self._ui_call(lambda: self._add_message(
                "Frank", "No QR code found in file.", is_system=True,
            ))
            return

        self._show_qr_results(results)

    # ── Generate QR code ──────────────────────────────────────────

    def _do_qr_generate_worker(self, data: str = "", **_kw):
        """Generate a QR code and display it in chat."""
        if not data:
            self._ui_call(lambda: self._add_message(
                "Frank", "No content specified for encoding.", is_system=True,
            ))
            return

        try:
            from qr_tool import generate_to_file
            path = generate_to_file(data, size=300)
        except Exception as e:
            LOG.error(f"QR generate error: {e}")
            self._ui_call(lambda: self._add_message(
                "Frank", f"QR generation failed: {e}", is_system=True,
            ))
            return

        if not path:
            self._ui_call(lambda: self._add_message(
                "Frank", "Could not create QR code.", is_system=True,
            ))
            return

        # Show QR code image in chat
        def _show():
            try:
                self._add_image(path, caption=f"QR: {data[:60]}", is_user=False)
            except Exception as e:
                LOG.warning(f"QR image display failed: {e}")
                self._add_message("Frank", f"QR-Code: {path}", is_system=True)

        self._ui_call(_show)

    # ── Helper: display scan results ──────────────────────────────

    def _show_qr_results(self, results: list):
        """Display QR scan results in chat."""
        def _display():
            if len(results) == 1:
                self._add_message("Frank", results[0])
            else:
                lines = [f"{len(results)} QR codes found:"]
                for r in results:
                    lines.append(r)
                self._add_message("Frank", "\n".join(lines))

        self._ui_call(_display)
