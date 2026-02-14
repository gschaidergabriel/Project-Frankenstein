#!/usr/bin/env python3
"""
Heatmap Analyzer
================
Analysiert und visualisiert Klick- und Fokus-Bereiche.
"""

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Callable

try:
    from PIL import Image, ImageDraw, ImageFilter
    import numpy as np
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False


@dataclass
class InteractionEvent:
    """Ein Interaktions-Event."""
    event_type: str  # "click", "focus", "hover", "scroll"
    x: int
    y: int
    timestamp: datetime = field(default_factory=lambda: datetime.now())
    element_info: Optional[str] = None
    duration: float = 0.0  # Für Focus/Hover


@dataclass
class HeatmapData:
    """Daten für Heatmap-Generierung."""
    width: int
    height: int
    events: List[InteractionEvent] = field(default_factory=list)
    click_counts: Dict[Tuple[int, int], int] = field(default_factory=lambda: defaultdict(int))
    focus_times: Dict[Tuple[int, int], float] = field(default_factory=lambda: defaultdict(float))


class HeatmapAnalyzer:
    """Analysiert und visualisiert UI-Interaktionen."""

    def __init__(self, output_dir: Path, grid_size: int = 20):
        """
        Args:
            output_dir: Ausgabe-Ordner
            grid_size: Größe der Heatmap-Zellen in Pixeln
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.grid_size = grid_size
        self.data: Optional[HeatmapData] = None
        self.recording = False

    def start_recording(self, width: int, height: int):
        """Startet Aufzeichnung von Interaktionen."""
        self.data = HeatmapData(width=width, height=height)
        self.recording = True

    def stop_recording(self):
        """Stoppt Aufzeichnung."""
        self.recording = False

    def record_click(self, x: int, y: int, element_info: str = None):
        """Zeichnet Klick auf."""
        if not self.recording or not self.data:
            return

        event = InteractionEvent(
            event_type="click",
            x=x, y=y,
            element_info=element_info
        )
        self.data.events.append(event)

        # Grid-Position
        gx = x // self.grid_size
        gy = y // self.grid_size
        self.data.click_counts[(gx, gy)] += 1

    def record_focus(self, x: int, y: int, duration: float, element_info: str = None):
        """Zeichnet Fokus/Hover auf."""
        if not self.recording or not self.data:
            return

        event = InteractionEvent(
            event_type="focus",
            x=x, y=y,
            duration=duration,
            element_info=element_info
        )
        self.data.events.append(event)

        gx = x // self.grid_size
        gy = y // self.grid_size
        self.data.focus_times[(gx, gy)] += duration

    def record_scroll(self, x: int, y: int, direction: str):
        """Zeichnet Scroll-Event auf."""
        if not self.recording or not self.data:
            return

        event = InteractionEvent(
            event_type="scroll",
            x=x, y=y,
            element_info=direction
        )
        self.data.events.append(event)

    def simulate_user_session(self, window_region: Tuple[int, int, int, int],
                               duration_seconds: int = 30,
                               click_callback: Callable = None):
        """
        Simuliert eine Benutzer-Session und zeichnet Interaktionen auf.

        Args:
            window_region: (x, y, width, height) des Fensters
            duration_seconds: Dauer der Aufzeichnung
            click_callback: Optionale Callback für simulierte Klicks
        """
        x, y, w, h = window_region
        self.start_recording(w, h)

        # Simuliere typische Interaktionsmuster
        import random

        start_time = time.time()
        while time.time() - start_time < duration_seconds:
            # Zufällige Klicks im Fenster (w-1 und h-1 um Off-by-One zu vermeiden)
            click_x = random.randint(x, x + w - 1)
            click_y = random.randint(y, y + h - 1)

            # Relative Position
            rel_x = click_x - x
            rel_y = click_y - y

            # Klick aufzeichnen
            self.record_click(rel_x, rel_y)

            # Optional: Echten Klick ausführen
            if click_callback:
                click_callback(click_x, click_y)

            # Fokus simulieren
            focus_duration = random.uniform(0.5, 3.0)
            self.record_focus(rel_x, rel_y, focus_duration)

            time.sleep(0.5)

        self.stop_recording()

    def analyze_from_workflow(self, workflow_results: List[Dict]):
        """
        Analysiert Interaktionen aus Workflow-Test-Ergebnissen.

        Args:
            workflow_results: Liste von Workflow-Ergebnissen mit Koordinaten
        """
        for result in workflow_results:
            if "interactions" in result:
                for interaction in result["interactions"]:
                    if interaction.get("type") == "click":
                        self.record_click(
                            interaction["x"],
                            interaction["y"],
                            interaction.get("element")
                        )

    def generate_click_heatmap(self, base_image: Image.Image = None) -> Image.Image:
        """Generiert Klick-Heatmap."""
        if not PIL_AVAILABLE:
            raise ImportError("PIL/Pillow ist nicht installiert")
        if not self.data:
            raise ValueError("Keine Daten vorhanden")

        width = self.data.width
        height = self.data.height

        # Basis-Bild oder transparenter Hintergrund
        if base_image:
            if base_image.size != (width, height):
                base_image = base_image.resize((width, height))
            heatmap = base_image.copy().convert("RGBA")
        else:
            heatmap = Image.new("RGBA", (width, height), (0, 0, 0, 0))

        # Overlay erstellen
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Maximale Klicks finden für Normalisierung
        max_clicks = max(self.data.click_counts.values()) if self.data.click_counts else 1

        # Heatmap zeichnen
        for (gx, gy), count in self.data.click_counts.items():
            x1 = gx * self.grid_size
            y1 = gy * self.grid_size
            x2 = x1 + self.grid_size
            y2 = y1 + self.grid_size

            # Intensität berechnen (0-1)
            intensity = count / max_clicks

            # Farbe: Grün -> Gelb -> Rot
            if intensity < 0.5:
                r = int(255 * (intensity * 2))
                g = 255
            else:
                r = 255
                g = int(255 * (1 - (intensity - 0.5) * 2))

            alpha = int(100 + 155 * intensity)  # 100-255

            draw.rectangle([x1, y1, x2, y2], fill=(r, g, 0, alpha))

        # Overlay mit Basis kombinieren
        heatmap = Image.alpha_composite(heatmap, overlay)

        return heatmap

    def generate_focus_heatmap(self, base_image: Image.Image = None) -> Image.Image:
        """Generiert Fokus-/Aufmerksamkeits-Heatmap."""
        if not PIL_AVAILABLE:
            raise ImportError("PIL/Pillow ist nicht installiert")
        if not self.data:
            raise ValueError("Keine Daten vorhanden")

        width = self.data.width
        height = self.data.height

        if base_image:
            if base_image.size != (width, height):
                base_image = base_image.resize((width, height))
            heatmap = base_image.copy().convert("RGBA")
        else:
            heatmap = Image.new("RGBA", (width, height), (0, 0, 0, 0))

        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        max_time = max(self.data.focus_times.values()) if self.data.focus_times else 1

        for (gx, gy), focus_time in self.data.focus_times.items():
            x1 = gx * self.grid_size
            y1 = gy * self.grid_size
            x2 = x1 + self.grid_size
            y2 = y1 + self.grid_size

            intensity = focus_time / max_time

            # Blau-Töne für Fokus
            b = 255
            r = int(100 * intensity)
            g = int(100 + 100 * (1 - intensity))
            alpha = int(80 + 175 * intensity)

            draw.rectangle([x1, y1, x2, y2], fill=(r, g, b, alpha))

        heatmap = Image.alpha_composite(heatmap, overlay)
        return heatmap

    def get_hotspots(self, top_n: int = 5) -> List[Dict]:
        """Findet die aktivsten Bereiche."""
        if not self.data:
            return []

        # Nach Klicks sortieren
        sorted_clicks = sorted(
            self.data.click_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )[:top_n]

        hotspots = []
        for (gx, gy), count in sorted_clicks:
            x = gx * self.grid_size + self.grid_size // 2
            y = gy * self.grid_size + self.grid_size // 2

            hotspots.append({
                "rank": len(hotspots) + 1,
                "x": x,
                "y": y,
                "grid": (gx, gy),
                "clicks": count,
                "focus_time": self.data.focus_times.get((gx, gy), 0)
            })

        return hotspots

    def get_dead_zones(self, min_expected_clicks: int = 1) -> List[Tuple[int, int]]:
        """Findet Bereiche ohne Interaktion (potenzielle UX-Probleme)."""
        if not self.data:
            return []

        grid_w = self.data.width // self.grid_size
        grid_h = self.data.height // self.grid_size

        dead_zones = []
        for gx in range(grid_w):
            for gy in range(grid_h):
                if (gx, gy) not in self.data.click_counts:
                    dead_zones.append((
                        gx * self.grid_size,
                        gy * self.grid_size
                    ))

        return dead_zones

    def save_heatmaps(self, base_image: Image.Image, prefix: str = "heatmap"):
        """Speichert alle Heatmaps."""
        if not PIL_AVAILABLE:
            raise ImportError("PIL/Pillow ist nicht installiert")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Klick-Heatmap
        click_heatmap = self.generate_click_heatmap(base_image)
        click_path = self.output_dir / f"{prefix}_clicks_{timestamp}.png"
        click_heatmap.save(click_path)

        # Fokus-Heatmap
        focus_heatmap = self.generate_focus_heatmap(base_image)
        focus_path = self.output_dir / f"{prefix}_focus_{timestamp}.png"
        focus_heatmap.save(focus_path)

        return {
            "click_heatmap": str(click_path),
            "focus_heatmap": str(focus_path)
        }

    def generate_report(self) -> Dict:
        """Generiert Analyse-Report."""
        if not self.data:
            return {"error": "Keine Daten"}

        hotspots = self.get_hotspots(10)
        dead_zones = self.get_dead_zones()

        total_clicks = sum(self.data.click_counts.values())
        total_focus_time = sum(self.data.focus_times.values())

        return {
            "timestamp": datetime.now().isoformat(),
            "dimensions": {
                "width": self.data.width,
                "height": self.data.height,
                "grid_size": self.grid_size
            },
            "statistics": {
                "total_events": len(self.data.events),
                "total_clicks": total_clicks,
                "total_focus_time": f"{total_focus_time:.1f}s",
                "unique_click_areas": len(self.data.click_counts),
                "dead_zones": len(dead_zones)
            },
            "hotspots": hotspots,
            "dead_zones_count": len(dead_zones),
            "recommendations": self._generate_recommendations(hotspots, dead_zones)
        }

    def _generate_recommendations(self, hotspots: List[Dict], dead_zones: List) -> List[str]:
        """Generiert UX-Empfehlungen basierend auf Heatmap-Daten."""
        recommendations = []

        if not hotspots:
            recommendations.append("Keine Interaktions-Daten - längere Aufzeichnung empfohlen")
            return recommendations

        # Analyse der Hotspots
        top_hotspot = hotspots[0] if hotspots else None

        if top_hotspot:
            if top_hotspot["y"] > self.data.height * 0.8:
                recommendations.append(
                    f"Häufigste Interaktion im unteren Bereich (y={top_hotspot['y']}) - "
                    "wichtige Elemente nach oben verschieben?"
                )

            if top_hotspot["x"] < self.data.width * 0.2:
                recommendations.append(
                    "Starke Konzentration auf linken Rand - rechte Seite untergenutzt"
                )

        # Dead Zones analysieren
        total_cells = (self.data.width // self.grid_size) * (self.data.height // self.grid_size)
        if len(dead_zones) > total_cells * 0.7:
            recommendations.append(
                "Über 70% der UI-Fläche ungenutzt - Layout überdenken oder UI verkleinern"
            )

        # Klick-Verteilung
        if len(self.data.click_counts) < 3:
            recommendations.append(
                "Klicks konzentrieren sich auf wenige Bereiche - "
                "andere UI-Elemente möglicherweise schwer zu finden"
            )

        if not recommendations:
            recommendations.append("Interaktionsmuster sehen ausgewogen aus")

        return recommendations


def create_interaction_overlay(base_image: Image.Image,
                               click_positions: List[Tuple[int, int]],
                               focus_areas: List[Tuple[int, int, float]] = None) -> Image.Image:
    """
    Erstellt Overlay mit Interaktions-Markierungen.

    Args:
        base_image: Basis-Screenshot
        click_positions: Liste von (x, y) Klick-Positionen
        focus_areas: Liste von (x, y, duration) Fokus-Bereichen
    """
    if not PIL_AVAILABLE:
        raise ImportError("PIL/Pillow ist nicht installiert")
    overlay = base_image.copy().convert("RGBA")
    draw = ImageDraw.Draw(overlay)

    # Klicks als rote Kreise
    for x, y in click_positions:
        draw.ellipse([x-5, y-5, x+5, y+5], fill=(255, 0, 0, 180))

    # Fokus als blaue Bereiche
    if focus_areas:
        for x, y, duration in focus_areas:
            radius = min(30, int(10 + duration * 5))
            alpha = min(200, int(50 + duration * 30))
            draw.ellipse(
                [x-radius, y-radius, x+radius, y+radius],
                fill=(0, 100, 255, alpha)
            )

    return overlay
