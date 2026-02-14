#!/usr/bin/env python3
"""
Concrete Suggestions Generator
==============================
Generiert konkrete, actionable Verbesserungsvorschläge statt generischer Tipps.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
from pathlib import Path

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


@dataclass
class ConcreteSuggestion:
    """Eine konkrete Verbesserungsempfehlung."""
    category: str  # "contrast", "color", "layout", "typography", "spacing"
    severity: str  # "critical", "major", "minor", "info"
    title: str
    description: str
    current_value: str
    suggested_value: str
    css_fix: Optional[str] = None
    affected_area: Optional[Tuple[int, int, int, int]] = None  # x1, y1, x2, y2
    wcag_reference: Optional[str] = None


class ConcreteSuggestionGenerator:
    """Generiert konkrete Verbesserungsvorschläge."""

    # WCAG Kontrast-Anforderungen
    WCAG_AA_NORMAL = 4.5
    WCAG_AA_LARGE = 3.0
    WCAG_AAA_NORMAL = 7.0
    WCAG_AAA_LARGE = 4.5

    # Catppuccin Mocha Farbpalette (empfohlen)
    RECOMMENDED_COLORS = {
        "background": {
            "base": "#1e1e2e",
            "surface": "#313244",
            "overlay": "#45475a"
        },
        "text": {
            "primary": "#cdd6f4",
            "secondary": "#a6adc8",
            "muted": "#6c7086"
        },
        "accent": {
            "blue": "#89b4fa",
            "green": "#a6e3a1",
            "red": "#f38ba8",
            "yellow": "#f9e2af",
            "purple": "#cba6f7"
        }
    }

    def __init__(self):
        self.suggestions: List[ConcreteSuggestion] = []

    def analyze_contrast(self, fg_color: Tuple[int, int, int],
                        bg_color: Tuple[int, int, int],
                        current_ratio: float,
                        is_large_text: bool = False) -> Optional[ConcreteSuggestion]:
        """Analysiert Kontrast und gibt konkrete Empfehlung."""

        required_ratio = self.WCAG_AA_LARGE if is_large_text else self.WCAG_AA_NORMAL
        optimal_ratio = self.WCAG_AAA_LARGE if is_large_text else self.WCAG_AAA_NORMAL

        if current_ratio >= optimal_ratio:
            return None  # Alles gut

        fg_hex = "#{:02x}{:02x}{:02x}".format(*fg_color)
        bg_hex = "#{:02x}{:02x}{:02x}".format(*bg_color)

        # Konkreten Verbesserungsvorschlag berechnen
        if current_ratio < required_ratio:
            severity = "critical"
            # Kontrast verbessern (je nach Hintergrund heller oder dunkler)
            suggested_fg = self._adjust_for_contrast(fg_color, bg_color, 0.3)
            suggested_hex = "#{:02x}{:02x}{:02x}".format(*suggested_fg)
            new_ratio = self._calculate_contrast(suggested_fg, bg_color)

            return ConcreteSuggestion(
                category="contrast",
                severity=severity,
                title="Kritischer Kontrast-Mangel",
                description=f"Text/Hintergrund-Kontrast {current_ratio:.2f}:1 ist unter WCAG AA ({required_ratio}:1)",
                current_value=f"{fg_hex} auf {bg_hex} = {current_ratio:.2f}:1",
                suggested_value=f"{suggested_hex} auf {bg_hex} = {new_ratio:.2f}:1",
                css_fix=f"color: {suggested_hex}; /* vorher: {fg_hex} */",
                wcag_reference="WCAG 2.1 SC 1.4.3 (Contrast Minimum)"
            )
        elif current_ratio < optimal_ratio:
            severity = "minor"
            suggested_fg = self._adjust_for_contrast(fg_color, bg_color, 0.15)
            suggested_hex = "#{:02x}{:02x}{:02x}".format(*suggested_fg)
            new_ratio = self._calculate_contrast(suggested_fg, bg_color)

            return ConcreteSuggestion(
                category="contrast",
                severity=severity,
                title="Kontrast verbessern",
                description=f"Kontrast {current_ratio:.2f}:1 erfüllt AA, aber nicht AAA ({optimal_ratio}:1)",
                current_value=f"{fg_hex} auf {bg_hex}",
                suggested_value=f"{suggested_hex} auf {bg_hex} = {new_ratio:.2f}:1",
                css_fix=f"color: {suggested_hex};",
                wcag_reference="WCAG 2.1 SC 1.4.6 (Contrast Enhanced)"
            )

    def analyze_color_harmony(self, colors: List[Tuple[int, int, int]],
                             harmony_type: str) -> List[ConcreteSuggestion]:
        """Analysiert Farbharmonie und gibt konkrete Empfehlungen."""
        suggestions = []

        if harmony_type == "mixed":
            # Finde dominante Farbe und schlage harmonische Palette vor
            if colors:
                dominant = colors[0]
                h, s, l = self._rgb_to_hsl(dominant)

                # Analogous Palette vorschlagen
                analogous = [
                    self._hsl_to_rgb((h - 30) % 360, s, l),
                    dominant,
                    self._hsl_to_rgb((h + 30) % 360, s, l),
                ]

                suggestions.append(ConcreteSuggestion(
                    category="color",
                    severity="minor",
                    title="Inkonsistente Farbpalette",
                    description="Die verwendeten Farben folgen keinem harmonischen Schema",
                    current_value=f"{len(colors)} verschiedene Farbtöne ohne klares Schema",
                    suggested_value="Analogous Palette: " + ", ".join(
                        "#{:02x}{:02x}{:02x}".format(*c) for c in analogous
                    ),
                    css_fix=f"/* Empfohlene Primärfarben:\n"
                           f"   --color-primary: #{analogous[1][0]:02x}{analogous[1][1]:02x}{analogous[1][2]:02x};\n"
                           f"   --color-secondary: #{analogous[0][0]:02x}{analogous[0][1]:02x}{analogous[0][2]:02x};\n"
                           f"   --color-tertiary: #{analogous[2][0]:02x}{analogous[2][1]:02x}{analogous[2][2]:02x};\n"
                           f"*/"
                ))

        return suggestions

    def analyze_spacing(self, spacing_values: List[int]) -> List[ConcreteSuggestion]:
        """Analysiert Abstände und empfiehlt konsistentes Spacing."""
        suggestions = []

        if not spacing_values:
            return suggestions

        # Finde inkonsistente Abstände
        unique_spacings = set(spacing_values)
        if len(unique_spacings) > 5:
            # Zu viele verschiedene Abstände
            # 8-Punkt-Grid empfehlen
            base = 8
            suggested_grid = [base * i for i in [1, 2, 3, 4, 6, 8]]

            suggestions.append(ConcreteSuggestion(
                category="spacing",
                severity="minor",
                title="Inkonsistentes Spacing",
                description=f"{len(unique_spacings)} verschiedene Abstandswerte gefunden",
                current_value=f"Werte: {sorted(unique_spacings)[:10]}...",
                suggested_value=f"8-Punkt-Grid: {suggested_grid}",
                css_fix=f"/* Spacing System:\n"
                       f"   --space-1: 8px;\n"
                       f"   --space-2: 16px;\n"
                       f"   --space-3: 24px;\n"
                       f"   --space-4: 32px;\n"
                       f"   --space-6: 48px;\n"
                       f"   --space-8: 64px;\n"
                       f"*/"
            ))

        return suggestions

    def analyze_typography(self, font_sizes: List[int]) -> List[ConcreteSuggestion]:
        """Analysiert Schriftgrößen und empfiehlt Type Scale."""
        suggestions = []

        if not font_sizes:
            return suggestions

        min_size = min(font_sizes)
        if min_size < 14:
            suggestions.append(ConcreteSuggestion(
                category="typography",
                severity="major",
                title="Zu kleine Schrift",
                description=f"Kleinste Schriftgröße {min_size}px ist unter dem Minimum (14px)",
                current_value=f"font-size: {min_size}px",
                suggested_value="font-size: 14px (Minimum) oder 16px (empfohlen)",
                css_fix=f"font-size: max(14px, {min_size}px);",
                wcag_reference="WCAG 2.1 SC 1.4.4 (Resize Text)"
            ))

        # Type Scale empfehlen
        if len(set(font_sizes)) > 6:
            suggestions.append(ConcreteSuggestion(
                category="typography",
                severity="minor",
                title="Zu viele Schriftgrößen",
                description=f"{len(set(font_sizes))} verschiedene Größen gefunden",
                current_value=f"Größen: {sorted(set(font_sizes))}",
                suggested_value="Major Third Type Scale (1.25): 12, 14, 16, 20, 25, 31, 39px",
                css_fix=f"/* Type Scale (1.25 ratio):\n"
                       f"   --text-xs: 12px;\n"
                       f"   --text-sm: 14px;\n"
                       f"   --text-base: 16px;\n"
                       f"   --text-lg: 20px;\n"
                       f"   --text-xl: 25px;\n"
                       f"   --text-2xl: 31px;\n"
                       f"   --text-3xl: 39px;\n"
                       f"*/"
            ))

        return suggestions

    def analyze_layout(self, layout_score: float,
                      alignment_issues: List[str]) -> List[ConcreteSuggestion]:
        """Analysiert Layout und gibt konkrete Empfehlungen."""
        suggestions = []

        if layout_score < 60:
            suggestions.append(ConcreteSuggestion(
                category="layout",
                severity="major",
                title="Layout-Inkonsistenz",
                description=f"Layout-Score {layout_score:.0f}/100 zeigt Ausrichtungsprobleme",
                current_value=f"Score: {layout_score:.0f}, Issues: {len(alignment_issues)}",
                suggested_value="Grid-System mit 12 Spalten verwenden",
                css_fix=f"/* Grid System:\n"
                       f"   display: grid;\n"
                       f"   grid-template-columns: repeat(12, 1fr);\n"
                       f"   gap: 16px;\n"
                       f"*/"
            ))

        if alignment_issues:
            for issue in alignment_issues[:3]:
                suggestions.append(ConcreteSuggestion(
                    category="layout",
                    severity="minor",
                    title="Ausrichtungsproblem",
                    description=issue,
                    current_value="Uneinheitliche Ausrichtung",
                    suggested_value="Konsistente Margins/Paddings verwenden"
                ))

        return suggestions

    def analyze_accessibility(self, issues: List[str]) -> List[ConcreteSuggestion]:
        """Konvertiert Accessibility-Issues in konkrete Empfehlungen."""
        suggestions = []

        for issue in issues:
            if "Kontrast" in issue:
                suggestions.append(ConcreteSuggestion(
                    category="accessibility",
                    severity="critical",
                    title="Accessibility: Kontrast",
                    description=issue,
                    current_value="Unter WCAG Standard",
                    suggested_value="Mindestens 4.5:1 für normalen Text, 3:1 für großen Text",
                    wcag_reference="WCAG 2.1 SC 1.4.3 (Contrast Minimum)"
                ))
            elif "Hierarchie" in issue:
                suggestions.append(ConcreteSuggestion(
                    category="accessibility",
                    severity="minor",
                    title="Accessibility: Visuelle Hierarchie",
                    description=issue,
                    current_value="Schwache Unterscheidung",
                    suggested_value="Größere Unterschiede in Farbe/Größe zwischen Elementen"
                ))

        return suggestions

    def generate_from_design_report(self, report) -> List[ConcreteSuggestion]:
        """
        Generiert konkrete Vorschläge aus einem DesignReport.

        Args:
            report: DesignReport Objekt
        """
        self.suggestions = []

        # Kontrast analysieren
        for contrast in report.contrast_issues:
            # Parse colors from hex
            fg_hex = contrast.foreground.lstrip('#')
            bg_hex = contrast.background.lstrip('#')
            fg = tuple(int(fg_hex[i:i+2], 16) for i in (0, 2, 4))
            bg = tuple(int(bg_hex[i:i+2], 16) for i in (0, 2, 4))

            suggestion = self.analyze_contrast(fg, bg, contrast.ratio)
            if suggestion:
                self.suggestions.append(suggestion)

        # Farbharmonie
        colors = [(c.rgb[0], c.rgb[1], c.rgb[2]) for c in report.dominant_colors[:5]]
        self.suggestions.extend(
            self.analyze_color_harmony(colors, report.color_harmony)
        )

        # Layout
        self.suggestions.extend(
            self.analyze_layout(report.layout_score, report.alignment_issues)
        )

        # Accessibility
        self.suggestions.extend(
            self.analyze_accessibility(report.accessibility_issues)
        )

        return self.suggestions

    def format_as_css(self) -> str:
        """Formatiert alle Vorschläge als CSS-Kommentare."""
        if not self.suggestions:
            return "/* Keine Verbesserungsvorschläge */"

        css_parts = ["/* ===== UI Verbesserungsvorschläge ===== */\n"]

        for s in self.suggestions:
            css_parts.append(f"\n/* [{s.severity.upper()}] {s.title}")
            css_parts.append(f"   {s.description}")
            if s.wcag_reference:
                css_parts.append(f"   Referenz: {s.wcag_reference}")
            css_parts.append(f"*/")
            if s.css_fix:
                css_parts.append(s.css_fix)
            css_parts.append("")

        return "\n".join(css_parts)

    def format_as_markdown(self) -> str:
        """Formatiert alle Vorschläge als Markdown."""
        if not self.suggestions:
            return "Keine Verbesserungsvorschläge."

        severity_emoji = {
            "critical": "🔴",
            "major": "🟠",
            "minor": "🟡",
            "info": "🔵"
        }

        md_parts = ["# UI Verbesserungsvorschläge\n"]

        # Gruppieren nach Kategorie
        by_category = {}
        for s in self.suggestions:
            if s.category not in by_category:
                by_category[s.category] = []
            by_category[s.category].append(s)

        for category, items in by_category.items():
            md_parts.append(f"\n## {category.title()}\n")

            for s in items:
                emoji = severity_emoji.get(s.severity, "⚪")
                md_parts.append(f"### {emoji} {s.title}\n")
                md_parts.append(f"{s.description}\n")
                md_parts.append(f"- **Aktuell:** {s.current_value}")
                md_parts.append(f"- **Empfohlen:** {s.suggested_value}")
                if s.css_fix:
                    md_parts.append(f"\n```css\n{s.css_fix}\n```\n")
                if s.wcag_reference:
                    md_parts.append(f"*Referenz: {s.wcag_reference}*\n")

        return "\n".join(md_parts)

    # Hilfsfunktionen
    def _lighten_color(self, rgb: Tuple[int, int, int], amount: float) -> Tuple[int, int, int]:
        """Hellt Farbe auf."""
        r, g, b = rgb
        r = min(255, int(r + (255 - r) * amount))
        g = min(255, int(g + (255 - g) * amount))
        b = min(255, int(b + (255 - b) * amount))
        return (r, g, b)

    def _darken_color(self, rgb: Tuple[int, int, int], amount: float) -> Tuple[int, int, int]:
        """Dunkelt Farbe ab."""
        r, g, b = rgb
        r = max(0, int(r * (1 - amount)))
        g = max(0, int(g * (1 - amount)))
        b = max(0, int(b * (1 - amount)))
        return (r, g, b)

    def _adjust_for_contrast(self, fg: Tuple[int, int, int],
                             bg: Tuple[int, int, int],
                             amount: float) -> Tuple[int, int, int]:
        """Passt Vordergrundfarbe an, um Kontrast zu verbessern."""
        # Berechne Luminanz des Hintergrunds
        bg_luminance = sum(bg) / (3 * 255)  # Vereinfachte Luminanz 0-1

        # Bei hellem Hintergrund: dunkler machen, bei dunklem: heller
        if bg_luminance > 0.5:
            return self._darken_color(fg, amount)
        else:
            return self._lighten_color(fg, amount)

    def _calculate_contrast(self, fg: Tuple[int, int, int],
                           bg: Tuple[int, int, int]) -> float:
        """Berechnet Kontrastverhältnis."""
        def luminance(rgb):
            r, g, b = [x / 255.0 for x in rgb]
            r = r / 12.92 if r <= 0.03928 else ((r + 0.055) / 1.055) ** 2.4
            g = g / 12.92 if g <= 0.03928 else ((g + 0.055) / 1.055) ** 2.4
            b = b / 12.92 if b <= 0.03928 else ((b + 0.055) / 1.055) ** 2.4
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        l1 = luminance(fg)
        l2 = luminance(bg)
        lighter = max(l1, l2)
        darker = min(l1, l2)
        return (lighter + 0.05) / (darker + 0.05)

    def _rgb_to_hsl(self, rgb: Tuple[int, int, int]) -> Tuple[float, float, float]:
        """Konvertiert RGB zu HSL."""
        import colorsys
        r, g, b = [x / 255.0 for x in rgb]
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        return (h * 360, s * 100, l * 100)

    def _hsl_to_rgb(self, h: float, s: float, l: float) -> Tuple[int, int, int]:
        """Konvertiert HSL zu RGB."""
        import colorsys
        h, s, l = h / 360, s / 100, l / 100
        r, g, b = colorsys.hls_to_rgb(h, l, s)
        return (int(r * 255), int(g * 255), int(b * 255))
