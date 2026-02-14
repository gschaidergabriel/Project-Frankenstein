#!/usr/bin/env python3
"""
Design Analyzer
===============
Analysiert UI-Design: Farben, Kontrast, Layout, Accessibility.
"""

import colorsys
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from pathlib import Path
from datetime import datetime

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageStat
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False


@dataclass
class ColorInfo:
    """Information über eine Farbe."""
    rgb: Tuple[int, int, int]
    hex: str
    hsl: Tuple[float, float, float]
    frequency: float  # Prozent der Pixel
    name: str = ""


@dataclass
class ContrastResult:
    """Ergebnis einer Kontrast-Prüfung."""
    foreground: str
    background: str
    ratio: float
    wcag_aa_normal: bool  # >= 4.5:1
    wcag_aa_large: bool   # >= 3:1
    wcag_aaa_normal: bool # >= 7:1
    wcag_aaa_large: bool  # >= 4.5:1


@dataclass
class DesignReport:
    """Kompletter Design-Report."""
    timestamp: datetime = field(default_factory=datetime.now)
    screenshot_path: str = ""

    # Farben
    dominant_colors: List[ColorInfo] = field(default_factory=list)
    color_palette: List[str] = field(default_factory=list)
    color_harmony: str = ""  # "monochromatic", "complementary", etc.

    # Kontrast
    contrast_issues: List[ContrastResult] = field(default_factory=list)
    contrast_score: float = 0.0  # 0-100

    # Layout
    layout_score: float = 0.0
    alignment_issues: List[str] = field(default_factory=list)
    spacing_consistency: float = 0.0

    # Accessibility
    wcag_compliant: bool = False
    accessibility_issues: List[str] = field(default_factory=list)

    # Empfehlungen
    recommendations: List[str] = field(default_factory=list)

    # Scores
    overall_score: float = 0.0


class DesignAnalyzer:
    """Analysiert UI-Design anhand von Screenshots."""

    # Bekannte UI-Farbnamen
    COLOR_NAMES = {
        (30, 30, 46): "Crust (Catppuccin)",
        (17, 17, 27): "Mantle (Catppuccin)",
        (24, 24, 37): "Base (Catppuccin)",
        (49, 50, 68): "Surface0",
        (69, 71, 90): "Surface1",
        (88, 91, 112): "Surface2",
        (166, 227, 161): "Green (Success)",
        (243, 139, 168): "Red (Error)",
        (249, 226, 175): "Yellow (Warning)",
        (137, 180, 250): "Blue (Accent)",
        (203, 166, 247): "Mauve (Purple)",
        (205, 214, 244): "Text",
    }

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def analyze_image(self, img: Image.Image) -> DesignReport:
        """Führt komplette Design-Analyse durch."""
        report = DesignReport()

        # Farb-Analyse
        report.dominant_colors = self._extract_colors(img)
        report.color_palette = [c.hex for c in report.dominant_colors[:6]]
        report.color_harmony = self._analyze_harmony(report.dominant_colors)

        # Kontrast-Analyse
        contrast_results = self._analyze_contrast(report.dominant_colors)
        report.contrast_issues = [r for r in contrast_results if not r.wcag_aa_normal]
        report.contrast_score = self._calculate_contrast_score(contrast_results)

        # Layout-Analyse
        layout_info = self._analyze_layout(img)
        report.layout_score = layout_info["score"]
        report.alignment_issues = layout_info["issues"]
        report.spacing_consistency = layout_info["spacing_consistency"]

        # Accessibility
        report.accessibility_issues = self._check_accessibility(img, report)
        report.wcag_compliant = len(report.accessibility_issues) == 0

        # Empfehlungen generieren
        report.recommendations = self._generate_recommendations(report)

        # Gesamt-Score
        report.overall_score = self._calculate_overall_score(report)

        return report

    def _extract_colors(self, img: Image.Image, num_colors: int = 10) -> List[ColorInfo]:
        """Extrahiert dominante Farben aus dem Bild."""
        # Bild verkleinern für Performance
        small = img.resize((150, 150))

        # Farben zählen
        pixels = list(small.getdata())

        # Ähnliche Farben gruppieren (Quantisierung)
        # FIX: RGBA-Bilder unterstützen (Alpha-Kanal ignorieren)
        quantized = []
        for pixel in pixels:
            # Handle RGB, RGBA, Grayscale and other formats
            if isinstance(pixel, (int, float)):
                # Grayscale als einzelner Wert
                r = g = b = int(pixel)
            elif hasattr(pixel, '__len__'):
                if len(pixel) >= 3:
                    r, g, b = pixel[0], pixel[1], pixel[2]
                elif len(pixel) == 1:
                    r = g = b = pixel[0]  # Grayscale als Tupel
                else:
                    continue
            else:
                continue
            # Auf 32er Schritte runden
            qr = (r // 32) * 32
            qg = (g // 32) * 32
            qb = (b // 32) * 32
            quantized.append((qr, qg, qb))

        # Häufigkeit zählen
        counter = Counter(quantized)
        total = len(quantized)

        # Schutz vor Division durch Null
        if total == 0:
            return []

        colors = []
        for rgb, count in counter.most_common(num_colors):
            freq = count / total * 100
            hex_color = "#{:02x}{:02x}{:02x}".format(*rgb)

            # RGB zu HSL (FIX: korrekte Reihenfolge H, S, L)
            r, g, b = [x / 255.0 for x in rgb]
            h, l, s = colorsys.rgb_to_hls(r, g, b)
            # HSL = (Hue 0-360, Saturation 0-100, Lightness 0-100)
            hsl = (h * 360, s * 100, l * 100)

            # Farbname suchen
            name = self._find_color_name(rgb)

            colors.append(ColorInfo(
                rgb=rgb,
                hex=hex_color,
                hsl=hsl,
                frequency=freq,
                name=name
            ))

        return colors

    def _find_color_name(self, rgb: Tuple[int, int, int]) -> str:
        """Findet den nächsten bekannten Farbnamen."""
        min_dist = float('inf')
        best_name = ""

        for known_rgb, name in self.COLOR_NAMES.items():
            dist = sum((a - b) ** 2 for a, b in zip(rgb, known_rgb))
            if dist < min_dist:
                min_dist = dist
                best_name = name

        # Nur zurückgeben wenn nah genug
        if min_dist < 3000:
            return best_name
        return ""

    def _analyze_harmony(self, colors: List[ColorInfo]) -> str:
        """Analysiert Farbharmonie."""
        if len(colors) < 2:
            return "unknown"

        hues = [c.hsl[0] for c in colors[:5]]

        # Hue-Differenzen berechnen
        diffs = []
        for i in range(len(hues) - 1):
            diff = abs(hues[i] - hues[i + 1])
            if diff > 180:
                diff = 360 - diff
            diffs.append(diff)

        avg_diff = sum(diffs) / len(diffs) if diffs else 0

        if avg_diff < 25:
            return "monochromatic"
        elif avg_diff < 45:
            return "analogous"
        elif 55 < avg_diff < 75:
            return "triadic"
        elif 170 < avg_diff < 190:
            return "complementary"
        else:
            return "mixed"

    def _calculate_luminance(self, rgb: Tuple[int, int, int]) -> float:
        """Berechnet relative Luminanz (WCAG)."""
        r, g, b = [x / 255.0 for x in rgb]

        def adjust(c):
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

        return 0.2126 * adjust(r) + 0.7152 * adjust(g) + 0.0722 * adjust(b)

    def _contrast_ratio(self, rgb1: Tuple[int, int, int], rgb2: Tuple[int, int, int]) -> float:
        """Berechnet Kontrastverhältnis zwischen zwei Farben."""
        l1 = self._calculate_luminance(rgb1)
        l2 = self._calculate_luminance(rgb2)

        lighter = max(l1, l2)
        darker = min(l1, l2)

        return (lighter + 0.05) / (darker + 0.05)

    def _analyze_contrast(self, colors: List[ColorInfo]) -> List[ContrastResult]:
        """Analysiert Kontrast zwischen Farbpaaren."""
        results = []

        # Teste alle Paare (helle vs dunkle Farben)
        dark_colors = [c for c in colors if c.hsl[2] < 50]
        light_colors = [c for c in colors if c.hsl[2] >= 50]

        for dark in dark_colors[:3]:
            for light in light_colors[:3]:
                ratio = self._contrast_ratio(dark.rgb, light.rgb)

                results.append(ContrastResult(
                    foreground=light.hex,
                    background=dark.hex,
                    ratio=round(ratio, 2),
                    wcag_aa_normal=ratio >= 4.5,
                    wcag_aa_large=ratio >= 3.0,
                    wcag_aaa_normal=ratio >= 7.0,
                    wcag_aaa_large=ratio >= 4.5
                ))

        return results

    def _calculate_contrast_score(self, results: List[ContrastResult]) -> float:
        """Berechnet Kontrast-Score (0-100)."""
        if not results:
            return 50.0

        scores = []
        for r in results:
            if r.wcag_aaa_normal:
                scores.append(100)
            elif r.wcag_aa_normal:
                scores.append(75)
            elif r.wcag_aa_large:
                scores.append(50)
            else:
                scores.append(25)

        return sum(scores) / len(scores)

    def _analyze_layout(self, img: Image.Image) -> Dict:
        """Analysiert Layout-Eigenschaften."""
        result = {
            "score": 70.0,
            "issues": [],
            "spacing_consistency": 0.8
        }

        if not CV2_AVAILABLE:
            result["issues"].append("OpenCV nicht verfügbar für Layout-Analyse")
            return result

        # PIL zu OpenCV
        cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)

        # Kanten erkennen
        edges = cv2.Canny(gray, 50, 150)

        # Linien erkennen (für Alignment-Check)
        lines = cv2.HoughLinesP(edges, 1, np.pi/180, 50, minLineLength=50, maxLineGap=10)

        if lines is not None:
            # Horizontale und vertikale Linien zählen
            h_lines = []
            v_lines = []

            for line in lines:
                x1, y1, x2, y2 = line[0]
                angle = abs(math.atan2(y2 - y1, x2 - x1) * 180 / np.pi)

                if angle < 5 or angle > 175:
                    h_lines.append(y1)
                elif 85 < angle < 95:
                    v_lines.append(x1)

            # Spacing-Konsistenz prüfen
            if len(h_lines) > 2:
                h_lines.sort()
                spacings = [h_lines[i+1] - h_lines[i] for i in range(len(h_lines)-1)]
                if spacings:
                    avg_spacing = sum(spacings) / len(spacings)
                    variance = sum((s - avg_spacing) ** 2 for s in spacings) / len(spacings)
                    result["spacing_consistency"] = max(0, 1 - (variance / 1000))

        # Score basierend auf Konsistenz
        result["score"] = 50 + (result["spacing_consistency"] * 50)

        return result

    def _check_accessibility(self, img: Image.Image, report: DesignReport) -> List[str]:
        """Prüft Accessibility-Kriterien."""
        issues = []

        # Kontrast-Probleme
        if report.contrast_score < 75:
            issues.append("Kontrast unter WCAG AA Standard")

        # Zu kleine Farbvielfalt (könnte auf fehlende visuelle Hierarchie hindeuten)
        if len(report.dominant_colors) < 3:
            issues.append("Wenig Farbvielfalt - möglicherweise schwache visuelle Hierarchie")

        # Zu viele Farben
        high_freq_colors = [c for c in report.dominant_colors if c.frequency > 5]
        if len(high_freq_colors) > 8:
            issues.append("Viele dominante Farben - könnte visuell überladen wirken")

        # Prüfe auf sehr helle oder sehr dunkle Bereiche
        for color in report.dominant_colors[:3]:
            if color.hsl[2] > 95:
                issues.append(f"Sehr heller Bereich ({color.hex}) könnte blenden")
            if color.hsl[2] < 5 and color.frequency > 10:
                issues.append(f"Großer sehr dunkler Bereich könnte Details verstecken")

        return issues

    def _generate_recommendations(self, report: DesignReport) -> List[str]:
        """Generiert Verbesserungsvorschläge."""
        recs = []

        # Kontrast
        if report.contrast_score < 75:
            recs.append("Erhöhe den Kontrast zwischen Text und Hintergrund (min. 4.5:1)")

        # Farbharmonie
        if report.color_harmony == "mixed":
            recs.append("Verwende eine konsistentere Farbpalette (z.B. analogous oder complementary)")

        # Spacing
        if report.spacing_consistency < 0.7:
            recs.append("Vereinheitliche Abstände zwischen UI-Elementen")

        # Accessibility
        for issue in report.accessibility_issues:
            if "Kontrast" in issue:
                recs.append("Nutze dunkleren Text oder helleren Hintergrund für bessere Lesbarkeit")

        # Allgemeine Design-Tipps
        if report.layout_score < 60:
            recs.append("Überprüfe die Ausrichtung der UI-Elemente (Grid-System verwenden)")

        if not recs:
            recs.append("Design sieht gut aus! Keine kritischen Verbesserungen nötig.")

        return recs

    def _calculate_overall_score(self, report: DesignReport) -> float:
        """Berechnet Gesamt-Score."""
        weights = {
            "contrast": 0.35,
            "layout": 0.25,
            "accessibility": 0.25,
            "harmony": 0.15
        }

        # Harmony Score
        harmony_scores = {
            "monochromatic": 90,
            "analogous": 95,
            "complementary": 85,
            "triadic": 80,
            "mixed": 60,
            "unknown": 50
        }
        harmony_score = harmony_scores.get(report.color_harmony, 50)

        # Accessibility Score
        acc_score = 100 - (len(report.accessibility_issues) * 15)
        acc_score = max(0, acc_score)

        total = (
            report.contrast_score * weights["contrast"] +
            report.layout_score * weights["layout"] +
            acc_score * weights["accessibility"] +
            harmony_score * weights["harmony"]
        )

        return round(total, 1)

    def create_annotated_image(self, img: Image.Image, report: DesignReport) -> Image.Image:
        """Erstellt annotiertes Bild mit Design-Infos."""
        # Kopie erstellen
        annotated = img.copy()
        draw = ImageDraw.Draw(annotated)

        # Farbpalette am unteren Rand
        palette_height = 60
        palette_y = img.height - palette_height

        # Hintergrund für Palette
        draw.rectangle([0, palette_y, img.width, img.height], fill=(30, 30, 46))

        # Farben zeichnen
        color_width = min(80, img.width // len(report.dominant_colors[:6]))
        for i, color in enumerate(report.dominant_colors[:6]):
            x = i * color_width + 10
            draw.rectangle([x, palette_y + 10, x + color_width - 5, palette_y + 45],
                          fill=color.rgb, outline=(255, 255, 255))

            # Hex-Code
            try:
                draw.text((x + 5, palette_y + 47), color.hex, fill=(205, 214, 244))
            except:
                pass

        # Score in Ecke
        score_text = f"Score: {report.overall_score}/100"
        draw.rectangle([img.width - 120, 5, img.width - 5, 30], fill=(30, 30, 46, 200))
        draw.text((img.width - 115, 8), score_text, fill=(166, 227, 161))

        return annotated

    def compare_designs(self, img1: Image.Image, img2: Image.Image) -> Dict:
        """Vergleicht zwei Design-Versionen."""
        report1 = self.analyze_image(img1)
        report2 = self.analyze_image(img2)

        comparison = {
            "before": {
                "overall_score": report1.overall_score,
                "contrast_score": report1.contrast_score,
                "layout_score": report1.layout_score,
                "color_harmony": report1.color_harmony
            },
            "after": {
                "overall_score": report2.overall_score,
                "contrast_score": report2.contrast_score,
                "layout_score": report2.layout_score,
                "color_harmony": report2.color_harmony
            },
            "improvements": [],
            "regressions": []
        }

        # Vergleiche Scores
        if report2.overall_score > report1.overall_score:
            comparison["improvements"].append(
                f"Gesamt-Score verbessert: {report1.overall_score} → {report2.overall_score}"
            )
        elif report2.overall_score < report1.overall_score:
            comparison["regressions"].append(
                f"Gesamt-Score verschlechtert: {report1.overall_score} → {report2.overall_score}"
            )

        if report2.contrast_score > report1.contrast_score:
            comparison["improvements"].append("Kontrast verbessert")
        elif report2.contrast_score < report1.contrast_score:
            comparison["regressions"].append("Kontrast verschlechtert")

        return comparison

    def generate_html_report(self, report: DesignReport, img: Image.Image) -> str:
        """Generiert HTML-Report."""
        # Screenshot speichern
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        img_path = self.output_dir / f"design_analysis_{timestamp}.png"
        img.save(img_path)

        # Annotiertes Bild
        annotated = self.create_annotated_image(img, report)
        annotated_path = self.output_dir / f"design_annotated_{timestamp}.png"
        annotated.save(annotated_path)

        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Design Analysis Report</title>
    <style>
        body {{
            font-family: 'Segoe UI', sans-serif;
            background: #1e1e2e;
            color: #cdd6f4;
            padding: 20px;
            max-width: 1200px;
            margin: 0 auto;
        }}
        h1, h2 {{ color: #89b4fa; }}
        .score-big {{
            font-size: 48px;
            font-weight: bold;
            color: {'#a6e3a1' if report.overall_score >= 70 else '#f9e2af' if report.overall_score >= 50 else '#f38ba8'};
        }}
        .card {{
            background: #313244;
            border-radius: 12px;
            padding: 20px;
            margin: 15px 0;
        }}
        .color-swatch {{
            display: inline-block;
            width: 60px;
            height: 60px;
            border-radius: 8px;
            margin: 5px;
            border: 2px solid #45475a;
        }}
        .palette {{ display: flex; flex-wrap: wrap; gap: 10px; }}
        .issue {{ color: #f38ba8; }}
        .recommendation {{ color: #a6e3a1; }}
        .metric {{
            display: inline-block;
            padding: 10px 20px;
            background: #45475a;
            border-radius: 8px;
            margin: 5px;
        }}
        img {{ max-width: 100%; border-radius: 8px; }}
    </style>
</head>
<body>
    <h1>Design Analysis Report</h1>
    <p>Erstellt: {report.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</p>

    <div class="card">
        <h2>Gesamt-Score</h2>
        <div class="score-big">{report.overall_score}/100</div>
        <div>
            <span class="metric">Kontrast: {report.contrast_score:.0f}</span>
            <span class="metric">Layout: {report.layout_score:.0f}</span>
            <span class="metric">Harmonie: {report.color_harmony}</span>
        </div>
    </div>

    <div class="card">
        <h2>Farbpalette</h2>
        <div class="palette">
            {''.join(f'<div class="color-swatch" style="background:{c.hex}" title="{c.hex} ({c.frequency:.1f}%)"></div>' for c in report.dominant_colors[:8])}
        </div>
        <p>Farbharmonie: <strong>{report.color_harmony}</strong></p>
    </div>

    <div class="card">
        <h2>Accessibility</h2>
        <p>WCAG Compliant: <strong>{'Ja' if report.wcag_compliant else 'Nein'}</strong></p>
        {''.join(f'<p class="issue">⚠ {issue}</p>' for issue in report.accessibility_issues) or '<p class="recommendation">✓ Keine Probleme gefunden</p>'}
    </div>

    <div class="card">
        <h2>Empfehlungen</h2>
        {''.join(f'<p class="recommendation">→ {rec}</p>' for rec in report.recommendations)}
    </div>

    <div class="card">
        <h2>Screenshot (Annotiert)</h2>
        <img src="{annotated_path.name}" alt="Annotated Screenshot">
    </div>
</body>
</html>"""

        html_path = self.output_dir / f"design_report_{timestamp}.html"
        with open(html_path, "w") as f:
            f.write(html)

        return str(html_path)
