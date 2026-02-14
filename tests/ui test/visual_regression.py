#!/usr/bin/env python3
"""
Visual Regression Testing
=========================
Pixel-basierter Vergleich von UI-Screenshots mit Baseline.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
    import numpy as np
    PIL_AVAILABLE = True
    # Kompatibilität für ältere und neuere Pillow-Versionen
    try:
        LANCZOS = Image.Resampling.LANCZOS
    except AttributeError:
        LANCZOS = Image.LANCZOS
except ImportError:
    PIL_AVAILABLE = False
    LANCZOS = None

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False


@dataclass
class RegressionResult:
    """Ergebnis eines Visual Regression Tests."""
    test_name: str
    passed: bool
    similarity: float  # 0-100%
    diff_pixels: int
    diff_percentage: float
    diff_regions: List[Tuple[int, int, int, int]]  # Rechtecke mit Unterschieden
    baseline_path: Optional[str] = None
    current_path: Optional[str] = None
    diff_path: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now())


class VisualRegressionTester:
    """Visual Regression Testing für UI-Screenshots."""

    def __init__(self, baseline_dir: Path, output_dir: Path, threshold: float = 0.1):
        """
        Args:
            baseline_dir: Ordner mit Baseline-Screenshots
            output_dir: Ordner für Diff-Bilder und Reports
            threshold: Maximal erlaubte Differenz in % (0.1 = 0.1%)
        """
        self.baseline_dir = Path(baseline_dir)
        self.output_dir = Path(output_dir)
        self.threshold = threshold

        self.baseline_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.results: List[RegressionResult] = []

    def save_baseline(self, name: str, img: Image.Image) -> str:
        """Speichert neues Baseline-Bild."""
        path = self.baseline_dir / f"{name}_baseline.png"
        img.save(path)

        # Metadaten speichern
        meta_path = self.baseline_dir / f"{name}_baseline.json"
        meta = {
            "name": name,
            "created": datetime.now().isoformat(),
            "size": list(img.size),
            "hash": self._image_hash(img)
        }
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

        return str(path)

    def get_baseline(self, name: str) -> Optional[Image.Image]:
        """Lädt Baseline-Bild."""
        path = self.baseline_dir / f"{name}_baseline.png"
        if path.exists():
            with Image.open(path) as img:
                return img.copy()  # Kopie erstellen und Datei schließen
        return None

    def has_baseline(self, name: str) -> bool:
        """Prüft ob Baseline existiert."""
        return (self.baseline_dir / f"{name}_baseline.png").exists()

    def _image_hash(self, img: Image.Image) -> str:
        """Erzeugt Hash für Bild."""
        return hashlib.md5(img.tobytes()).hexdigest()

    def compare(self, name: str, current: Image.Image,
                create_baseline_if_missing: bool = True) -> RegressionResult:
        """
        Vergleicht aktuelles Bild mit Baseline.

        Args:
            name: Name des Tests
            current: Aktueller Screenshot
            create_baseline_if_missing: Baseline erstellen wenn nicht vorhanden
        """
        baseline = self.get_baseline(name)

        if baseline is None:
            if create_baseline_if_missing:
                self.save_baseline(name, current)
                return RegressionResult(
                    test_name=name,
                    passed=True,
                    similarity=100.0,
                    diff_pixels=0,
                    diff_percentage=0.0,
                    diff_regions=[],
                    baseline_path=str(self.baseline_dir / f"{name}_baseline.png"),
                    current_path=None,
                    diff_path=None
                )
            else:
                return RegressionResult(
                    test_name=name,
                    passed=False,
                    similarity=0.0,
                    diff_pixels=-1,
                    diff_percentage=100.0,
                    diff_regions=[],
                    baseline_path=None
                )

        # Größen anpassen wenn nötig
        if baseline.size != current.size:
            current = current.resize(baseline.size, LANCZOS)

        # Beide zu RGB konvertieren
        if baseline.mode != "RGB":
            baseline = baseline.convert("RGB")
        if current.mode != "RGB":
            current = current.convert("RGB")

        # Differenz berechnen
        diff = ImageChops.difference(baseline, current)

        # Statistiken
        diff_array = np.array(diff)
        diff_pixels = np.sum(np.any(diff_array > 10, axis=2))  # Pixel mit Differenz > 10
        total_pixels = baseline.size[0] * baseline.size[1]
        diff_percentage = (diff_pixels / total_pixels) * 100

        similarity = 100.0 - diff_percentage

        # Unterschieds-Regionen finden
        diff_regions = self._find_diff_regions(diff)

        # Ergebnis
        passed = diff_percentage <= self.threshold

        # Bilder speichern
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        current_path = self.output_dir / f"{name}_current_{timestamp}.png"
        diff_path = self.output_dir / f"{name}_diff_{timestamp}.png"

        current.save(current_path)

        # Diff-Bild mit markierten Regionen erstellen
        diff_highlighted = self._create_diff_image(baseline, current, diff_regions)
        diff_highlighted.save(diff_path)

        result = RegressionResult(
            test_name=name,
            passed=passed,
            similarity=round(similarity, 2),
            diff_pixels=int(diff_pixels),
            diff_percentage=round(diff_percentage, 4),
            diff_regions=diff_regions,
            baseline_path=str(self.baseline_dir / f"{name}_baseline.png"),
            current_path=str(current_path),
            diff_path=str(diff_path)
        )

        self.results.append(result)
        return result

    def _find_diff_regions(self, diff: Image.Image, min_size: int = 10) -> List[Tuple[int, int, int, int]]:
        """Findet Rechtecke mit Unterschieden."""
        if not CV2_AVAILABLE:
            return []

        # Zu Graustufen und Binär
        gray = np.array(diff.convert("L"))
        _, binary = cv2.threshold(gray, 10, 255, cv2.THRESH_BINARY)

        # Konturen finden
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        regions = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w >= min_size or h >= min_size:
                regions.append((x, y, x + w, y + h))

        return regions

    def _create_diff_image(self, baseline: Image.Image, current: Image.Image,
                           regions: List[Tuple[int, int, int, int]]) -> Image.Image:
        """Erstellt Diff-Bild mit markierten Unterschieden."""
        # Halb-transparentes Overlay
        result = Image.blend(baseline, current, 0.5)
        draw = ImageDraw.Draw(result)

        # Rote Rechtecke um Unterschiede
        for x1, y1, x2, y2 in regions:
            draw.rectangle([x1, y1, x2, y2], outline=(255, 0, 0), width=2)

        return result

    def update_baseline(self, name: str, img: Image.Image) -> str:
        """Aktualisiert Baseline-Bild."""
        # Alte Baseline archivieren
        old_path = self.baseline_dir / f"{name}_baseline.png"
        if old_path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")  # Mikrosekunden für Eindeutigkeit
            archive_path = self.baseline_dir / "archive" / f"{name}_baseline_{timestamp}.png"
            archive_path.parent.mkdir(exist_ok=True)
            # Falls Datei bereits existiert, eindeutigen Namen generieren
            counter = 1
            while archive_path.exists():
                archive_path = self.baseline_dir / "archive" / f"{name}_baseline_{timestamp}_{counter}.png"
                counter += 1
            old_path.rename(archive_path)

        return self.save_baseline(name, img)

    def generate_report(self) -> Dict:
        """Generiert Report über alle Tests."""
        passed = sum(1 for r in self.results if r.passed)
        failed = len(self.results) - passed

        return {
            "timestamp": datetime.now().isoformat(),
            "total_tests": len(self.results),
            "passed": passed,
            "failed": failed,
            "threshold": f"{self.threshold}%",
            "tests": [
                {
                    "name": r.test_name,
                    "passed": r.passed,
                    "similarity": f"{r.similarity}%",
                    "diff_pixels": r.diff_pixels,
                    "diff_percentage": f"{r.diff_percentage}%",
                    "diff_regions": len(r.diff_regions),
                    "diff_image": r.diff_path
                }
                for r in self.results
            ]
        }


class ResponsiveDesignTester:
    """Testet UI bei verschiedenen Fenstergrößen."""

    # Typische Bildschirmgrößen
    COMMON_SIZES = {
        "mobile_small": (320, 568),    # iPhone SE
        "mobile": (375, 667),          # iPhone 8
        "mobile_large": (414, 896),    # iPhone 11
        "tablet": (768, 1024),         # iPad
        "laptop": (1366, 768),         # Laptop
        "desktop": (1920, 1080),       # Full HD
        "desktop_large": (2560, 1440), # QHD
        "ultrawide": (3440, 1440),     # Ultrawide
    }

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results: List[Dict] = []

    def resize_window(self, wid: str, width: int, height: int) -> bool:
        """Ändert Fenstergröße via wmctrl."""
        import subprocess
        try:
            # wmctrl -i -r <wid> -e 0,x,y,width,height
            subprocess.run(
                ["wmctrl", "-i", "-r", wid, "-e", f"0,-1,-1,{width},{height}"],
                timeout=3, check=True
            )
            return True
        except Exception:
            return False

    def test_size(self, name: str, wid: str, width: int, height: int,
                  capture_func) -> Dict:
        """
        Testet UI bei bestimmter Größe.

        Args:
            name: Name der Größe
            wid: Window ID
            width, height: Zielgröße
            capture_func: Funktion zum Screenshot-Machen
        """
        import time

        # Größe ändern
        if not self.resize_window(wid, width, height):
            return {"name": name, "size": (width, height), "error": "resize_failed"}

        time.sleep(0.5)  # Warten auf Resize

        # Screenshot
        img = capture_func()
        if img is None:
            return {"name": name, "size": (width, height), "error": "capture_failed"}

        # Speichern
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.output_dir / f"responsive_{name}_{width}x{height}_{timestamp}.png"
        img.save(path)

        # Analyse
        actual_size = img.size
        size_match = (actual_size[0] >= width * 0.9 and actual_size[1] >= height * 0.9)

        result = {
            "name": name,
            "requested_size": (width, height),
            "actual_size": actual_size,
            "size_match": size_match,
            "screenshot": str(path),
            "timestamp": datetime.now().isoformat()
        }

        self.results.append(result)
        return result

    def test_common_sizes(self, wid: str, capture_func, sizes: List[str] = None) -> List[Dict]:
        """Testet alle oder ausgewählte Standard-Größen."""
        if sizes is None:
            sizes = list(self.COMMON_SIZES.keys())

        results = []
        for name in sizes:
            if name in self.COMMON_SIZES:
                width, height = self.COMMON_SIZES[name]
                result = self.test_size(name, wid, width, height, capture_func)
                results.append(result)

        return results

    def generate_report(self) -> Dict:
        """Generiert Report."""
        return {
            "timestamp": datetime.now().isoformat(),
            "total_tests": len(self.results),
            "tests": self.results,
            "size_matches": sum(1 for r in self.results if r.get("size_match", False)),
            "errors": sum(1 for r in self.results if "error" in r)
        }
