#!/usr/bin/env python3
"""
UI Test Engine
==============
Kernlogik für Screenshot-basierte UI-Tests.
"""

import subprocess
import time
import os
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Callable, Optional, Any
from dataclasses import dataclass, field

# Screenshot & Image
try:
    import mss
    from PIL import Image, ImageChops, ImageDraw, ImageFont
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False

# OCR
try:
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# PyAutoGUI für Interaktion
try:
    import pyautogui
    pyautogui.FAILSAFE = False  # Disable failsafe für autonome Tests
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False


@dataclass
class TestResult:
    """Ergebnis eines einzelnen Tests."""
    test_id: str
    passed: bool
    error: Optional[str] = None
    screenshot_path: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now())


class UITestEngine:
    """Engine für UI-Tests mit Screenshot-Vergleich."""

    def __init__(
        self,
        screenshots_dir: Path,
        save_screenshots: bool = True,
        ocr_enabled: bool = True,
        log_callback: Optional[Callable] = None
    ):
        self.screenshots_dir = Path(screenshots_dir)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        self.save_screenshots = save_screenshots
        self.ocr_enabled = ocr_enabled and OCR_AVAILABLE
        self.log_callback = log_callback or print

        self.results: List[TestResult] = []
        self.running = True

        # Check dependencies
        if not MSS_AVAILABLE:
            self.log("WARN: mss nicht verfügbar - Screenshots deaktiviert", "WARN")
        if not OCR_AVAILABLE and ocr_enabled:
            self.log("WARN: pytesseract nicht verfügbar - OCR deaktiviert", "WARN")
        if not PYAUTOGUI_AVAILABLE:
            self.log("WARN: pyautogui nicht verfügbar - Interaktion deaktiviert", "WARN")

    def log(self, message: str, level: str = "INFO"):
        """Logging."""
        if self.log_callback:
            self.log_callback(message, level)

    def stop(self):
        """Stoppt die Engine."""
        self.running = False

    def take_screenshot(self, region: tuple = None) -> Optional[Image.Image]:
        """Macht einen Screenshot."""
        if not MSS_AVAILABLE:
            return None

        try:
            with mss.mss() as sct:
                if region:
                    monitor = {"left": region[0], "top": region[1],
                              "width": region[2], "height": region[3]}
                else:
                    monitor = sct.monitors[1]  # Primary monitor

                shot = sct.grab(monitor)
                return Image.frombytes("RGB", shot.size, shot.rgb)
        except Exception as e:
            self.log(f"Screenshot fehlgeschlagen: {e}", "ERROR")
            return None

    def save_screenshot(self, img: Image.Image, name: str) -> str:
        """Speichert Screenshot."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{name}_{timestamp}.png"
        path = self.screenshots_dir / filename
        img.save(path)
        return str(path)

    def extract_text(self, img: Image.Image) -> str:
        """Extrahiert Text aus Bild via OCR."""
        if not self.ocr_enabled:
            return ""

        try:
            # Bild für OCR vorbereiten (Kontrast erhöhen)
            text = pytesseract.image_to_string(img, lang="deu+eng")
            return text.strip()
        except Exception as e:
            self.log(f"OCR fehlgeschlagen: {e}", "WARN")
            return ""

    def compare_images(self, img1: Image.Image, img2: Image.Image, threshold: float = 5.0) -> tuple:
        """
        Vergleicht zwei Bilder.
        Gibt (sind_ähnlich, differenz_score) zurück.
        """
        if img1.size != img2.size:
            img2 = img2.resize(img1.size)

        # Bug-Fix: Absicherung gegen leere Bilder
        pixel_count = img1.size[0] * img1.size[1]
        if pixel_count == 0:
            return False, float('inf')

        diff = ImageChops.difference(img1, img2)
        h = diff.histogram()

        # Root Mean Square - korrigierte Berechnung für RGB
        # Histogram hat 768 Werte (256 pro Kanal R, G, B)
        sq = sum((idx % 256) ** 2 * value for idx, value in enumerate(h))
        # Teile durch Anzahl Pixel * 3 Kanäle für korrekten Durchschnitt
        rms = (sq / float(pixel_count * 3)) ** 0.5

        return rms < threshold, rms

    def find_window(self, title_pattern: str) -> Optional[Dict]:
        """Findet Fenster anhand des Titels."""
        try:
            result = subprocess.run(
                ["wmctrl", "-lpG"],
                capture_output=True, text=True, timeout=5
            )

            for line in result.stdout.splitlines():
                parts = line.split(None, 8)
                if len(parts) >= 9:
                    wid, desk, pid, x, y, w, h, host, title = parts
                    if title_pattern.lower() in title.lower():
                        return {
                            "wid": wid,
                            "pid": int(pid),
                            "x": int(x), "y": int(y),
                            "w": int(w), "h": int(h),
                            "title": title
                        }
        except Exception as e:
            self.log(f"Fenstersuche fehlgeschlagen: {e}", "WARN")

        return None

    def capture_window(self, title_pattern: str) -> Optional[Image.Image]:
        """Macht Screenshot eines spezifischen Fensters."""
        window = self.find_window(title_pattern)
        if not window:
            return None

        # Bug-Fix: Negative Koordinaten bei Multi-Monitor abfangen
        x = max(0, window["x"])
        y = max(0, window["y"])
        w = window["w"]
        h = window["h"]

        # Breite/Höhe anpassen wenn Fenster teilweise außerhalb liegt
        if window["x"] < 0:
            w = w + window["x"]  # Reduziere Breite
        if window["y"] < 0:
            h = h + window["y"]  # Reduziere Höhe

        if w <= 0 or h <= 0:
            self.log(f"Fenster außerhalb des sichtbaren Bereichs: {title_pattern}", "WARN")
            return None

        region = (x, y, w, h)
        return self.take_screenshot(region)

    def click_at(self, x: int, y: int, button: str = "left"):
        """Klickt an Position."""
        if not PYAUTOGUI_AVAILABLE:
            return False

        try:
            pyautogui.click(x, y, button=button)
            return True
        except Exception as e:
            self.log(f"Klick fehlgeschlagen: {e}", "WARN")
            return False

    def type_text(self, text: str, interval: float = 0.05):
        """Tippt Text."""
        if not PYAUTOGUI_AVAILABLE:
            return False

        try:
            pyautogui.write(text, interval=interval)
            return True
        except Exception as e:
            self.log(f"Tippen fehlgeschlagen: {e}", "WARN")
            return False

    def press_key(self, key: str):
        """Drückt Taste."""
        if not PYAUTOGUI_AVAILABLE:
            return False

        try:
            pyautogui.press(key)
            return True
        except Exception as e:
            self.log(f"Tastendruck fehlgeschlagen: {e}", "WARN")
            return False

    def hotkey(self, *keys):
        """Drückt Tastenkombination."""
        if not PYAUTOGUI_AVAILABLE:
            return False

        try:
            pyautogui.hotkey(*keys)
            return True
        except Exception as e:
            self.log(f"Hotkey fehlgeschlagen: {e}", "WARN")
            return False

    def run_tests(self, test_ids: List[str]) -> Dict[str, Dict]:
        """Führt ausgewählte Tests aus."""
        from test_cases import get_all_test_cases, get_test_function

        all_tests = get_all_test_cases()
        results = {}

        if "all" in test_ids:
            test_ids = list(all_tests.keys())

        for test_id in test_ids:
            if not self.running:
                break

            if test_id not in all_tests:
                results[test_id] = {"passed": False, "error": "Test nicht gefunden"}
                continue

            test_func = get_test_function(test_id)
            if not test_func:
                results[test_id] = {"passed": False, "error": "Test-Funktion nicht gefunden"}
                continue

            try:
                result = test_func(self)
                self.results.append(result)
                results[test_id] = {
                    "passed": result.passed,
                    "error": result.error,
                    "details": result.details,
                    "screenshot": result.screenshot_path
                }
            except Exception as e:
                results[test_id] = {"passed": False, "error": str(e)}
                self.results.append(TestResult(
                    test_id=test_id,
                    passed=False,
                    error=str(e)
                ))

        return results

    def generate_report(self) -> Dict:
        """Generiert Abschlussbericht."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed

        # Gruppiere nach Test-ID
        by_test = {}
        for r in self.results:
            if r.test_id not in by_test:
                by_test[r.test_id] = {"passed": 0, "failed": 0, "errors": []}

            if r.passed:
                by_test[r.test_id]["passed"] += 1
            else:
                by_test[r.test_id]["failed"] += 1
                if r.error:
                    by_test[r.test_id]["errors"].append(r.error)

        return {
            "generated_at": datetime.now().isoformat(),
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "success_rate": f"{(passed/total*100):.1f}%" if total > 0 else "N/A",
            "by_test": by_test,
            "screenshots_dir": str(self.screenshots_dir)
        }
