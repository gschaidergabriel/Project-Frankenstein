#!/usr/bin/env python3
"""
Frank AI - One-Click UI Test
============================
Führt alle Tests automatisch aus und generiert detaillierten Markdown-Report.

Verwendung:
    python3 one_click_test.py                    # Standard (5 Min)
    python3 one_click_test.py --quick            # Schnell (1 Min)
    python3 one_click_test.py --thorough         # Gründlich (15 Min)
    python3 one_click_test.py --headless         # CI/CD Modus
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# ESC-Stopp Unterstützung
try:
    from pynput import keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False

_STOP_REQUESTED = False

def _esc_handler(key):
    """ESC drücken stoppt den Test."""
    global _STOP_REQUESTED
    try:
        if key == keyboard.Key.esc:
            _STOP_REQUESTED = True
            print("\n\n⚠️  ESC gedrückt - Test wird abgebrochen...")
            return False
    except Exception:
        pass

# Paths
BASE_DIR = Path(__file__).parent
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
REPORTS_DIR = BASE_DIR / "reports"
BASELINE_DIR = BASE_DIR / "baseline"


class OneClickTester:
    """Führt alle Tests aus und generiert Report."""

    def __init__(self, mode: str = "standard", headless: bool = False):
        self.mode = mode
        self.headless = headless
        self.results = {}
        self.start_time = None
        self.end_time = None

        # Konfiguration je nach Modus
        self.config = {
            "quick": {"duration": 60, "iterations": 1, "interval": 10},
            "standard": {"duration": 300, "iterations": 3, "interval": 30},
            "thorough": {"duration": 900, "iterations": 5, "interval": 60},
            "extended": {"duration": 1800, "iterations": 10, "interval": 90}
        }.get(mode, {"duration": 300, "iterations": 3, "interval": 30})

        # Directories erstellen
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        BASELINE_DIR.mkdir(parents=True, exist_ok=True)

    def log(self, msg: str, level: str = "INFO"):
        """Logging mit Farben."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        colors = {"INFO": "\033[94m", "OK": "\033[92m", "WARN": "\033[93m", "ERROR": "\033[91m"}
        reset = "\033[0m"
        print(f"[{timestamp}] {colors.get(level, '')}{msg}{reset}")

    def run_all(self) -> dict:
        """Führt alle Tests aus."""
        global _STOP_REQUESTED
        _STOP_REQUESTED = False

        self.start_time = datetime.now()
        self.log("=" * 60)
        self.log("  FRANK AI - ONE-CLICK UI TEST")
        self.log(f"  Modus: {self.mode.upper()}")
        self.log(f"  Dauer: ~{self.config['duration'] // 60} Minuten")
        self.log("  [ESC drücken zum Abbrechen]")
        self.log("=" * 60)

        # ESC-Listener starten
        esc_listener = None
        if PYNPUT_AVAILABLE:
            esc_listener = keyboard.Listener(on_press=_esc_handler)
            esc_listener.start()

        try:
            # 1. Basis-Tests
            if not _STOP_REQUESTED:
                self.log("\n[1/6] Basis-Tests...", "INFO")
                self.results["basic_tests"] = self._run_basic_tests()

            # 2. Design-Analyse
            if not _STOP_REQUESTED:
                self.log("\n[2/6] Design-Analyse...", "INFO")
                self.results["design"] = self._run_design_analysis()

            # 3. Workflow-Tests
            if not _STOP_REQUESTED:
                self.log("\n[3/6] Workflow-Tests...", "INFO")
                self.results["workflow"] = self._run_workflow_tests()

            # 4. Visual Regression
            if not _STOP_REQUESTED:
                self.log("\n[4/6] Visual Regression...", "INFO")
                self.results["regression"] = self._run_regression_test()

            # 5. Responsive Tests
            if not _STOP_REQUESTED:
                self.log("\n[5/6] Responsive Tests...", "INFO")
                self.results["responsive"] = self._run_responsive_tests()

            # 6. Heatmap-Analyse (optional bei thorough)
            if not _STOP_REQUESTED and self.mode == "thorough":
                self.log("\n[6/6] Heatmap-Analyse...", "INFO")
                self.results["heatmap"] = self._run_heatmap_analysis()
            else:
                self.results["heatmap"] = {"skipped": True}

            if _STOP_REQUESTED:
                self.log("\n⚠️  Test wurde durch ESC abgebrochen!", "WARN")

        finally:
            # ESC-Listener stoppen
            if esc_listener:
                esc_listener.stop()

        self.end_time = datetime.now()

        # Report generieren (auch bei Abbruch)
        self.log("\n" + "=" * 60)
        self.log("  Report wird generiert...")
        report_path = self._generate_markdown_report()

        self.log(f"\n  ✓ FERTIG!")
        self.log(f"  Report: {report_path}", "OK")
        self.log("=" * 60)

        return self.results

    def _run_basic_tests(self) -> dict:
        """Führt Basis-Tests aus."""
        try:
            from test_engine import UITestEngine
            from test_cases import get_all_test_cases

            engine = UITestEngine(
                screenshots_dir=SCREENSHOTS_DIR,
                save_screenshots=True,
                ocr_enabled=False,
                log_callback=lambda m, l="INFO": self.log(f"  {m}", l)
            )

            results = engine.run_tests(["all"])
            passed = sum(1 for r in results.values() if r.get("passed"))
            failed = len(results) - passed

            self.log(f"  ✓ {passed} bestanden, ✗ {failed} fehlgeschlagen",
                    "OK" if failed == 0 else "WARN")

            return {
                "total": len(results),
                "passed": passed,
                "failed": failed,
                "details": results
            }
        except Exception as e:
            self.log(f"  Fehler: {e}", "ERROR")
            return {"error": str(e)}

    def _run_design_analysis(self) -> dict:
        """Führt Design-Analyse aus."""
        try:
            from test_engine import UITestEngine
            from design_analyzer import DesignAnalyzer
            from concrete_suggestions import ConcreteSuggestionGenerator

            engine = UITestEngine(SCREENSHOTS_DIR, save_screenshots=True, ocr_enabled=False)
            img = engine.capture_window("Frank") or engine.take_screenshot()

            if not img:
                return {"error": "Screenshot fehlgeschlagen"}

            analyzer = DesignAnalyzer(REPORTS_DIR)
            report = analyzer.analyze_image(img)

            # Konkrete Vorschläge
            generator = ConcreteSuggestionGenerator()
            suggestions = generator.generate_from_design_report(report)

            self.log(f"  Score: {report.overall_score}/100",
                    "OK" if report.overall_score >= 70 else "WARN")
            self.log(f"  {len(suggestions)} Verbesserungsvorschläge")

            # HTML Report erstellen
            html_path = analyzer.generate_html_report(report, img)

            return {
                "overall_score": report.overall_score,
                "contrast_score": report.contrast_score,
                "layout_score": report.layout_score,
                "color_harmony": report.color_harmony,
                "wcag_compliant": report.wcag_compliant,
                "colors": report.color_palette[:6],
                "accessibility_issues": report.accessibility_issues,
                "suggestions": [
                    {
                        "severity": s.severity,
                        "title": s.title,
                        "description": s.description,
                        "current": s.current_value,
                        "suggested": s.suggested_value,
                        "css": s.css_fix
                    }
                    for s in suggestions
                ],
                "html_report": str(html_path)
            }
        except Exception as e:
            self.log(f"  Fehler: {e}", "ERROR")
            return {"error": str(e)}

    def _run_workflow_tests(self) -> dict:
        """Führt Workflow-Tests aus."""
        try:
            from workflow_analyzer import WorkflowAnalyzer

            analyzer = WorkflowAnalyzer(lambda m, l="INFO": self.log(f"  {m}", l))
            workflows = analyzer.get_chat_overlay_workflows()

            # Teste alle Workflows
            for name, steps in workflows.items():
                result = analyzer.run_workflow(name, steps)
                status = "✓" if result.success else "✗"
                self.log(f"  {status} {name}: {result.total_time:.2f}s",
                        "OK" if result.success else "WARN")

            metrics = analyzer.calculate_metrics()
            report = analyzer.generate_report()

            self.log(f"  Effizienz: {metrics.workflow_efficiency:.0f}%")

            return {
                "metrics": {
                    "response_time_avg": f"{metrics.response_time_avg:.3f}s",
                    "task_completion_rate": f"{metrics.task_completion_rate:.1f}%",
                    "error_rate": f"{metrics.error_rate:.1f}%",
                    "smoothness": f"{metrics.interaction_smoothness:.1f}/100",
                    "efficiency": f"{metrics.workflow_efficiency:.1f}/100"
                },
                "workflows": report.get("workflows", [])
            }
        except Exception as e:
            self.log(f"  Fehler: {e}", "ERROR")
            return {"error": str(e)}

    def _run_regression_test(self) -> dict:
        """Führt Visual Regression Test aus."""
        try:
            from test_engine import UITestEngine
            from visual_regression import VisualRegressionTester

            engine = UITestEngine(SCREENSHOTS_DIR, save_screenshots=True, ocr_enabled=False)
            tester = VisualRegressionTester(BASELINE_DIR, SCREENSHOTS_DIR, threshold=0.5)

            img = engine.capture_window("Frank") or engine.take_screenshot()
            if not img:
                return {"error": "Screenshot fehlgeschlagen"}

            result = tester.compare("chat_overlay", img, create_baseline_if_missing=True)

            if result.baseline_path and result.diff_pixels == 0:
                self.log("  Baseline erstellt (erster Lauf)", "OK")
            elif result.passed:
                self.log(f"  ✓ Keine Regression ({result.similarity}% gleich)", "OK")
            else:
                self.log(f"  ✗ Regression erkannt! ({result.diff_percentage}% Unterschied)", "ERROR")

            return {
                "passed": result.passed,
                "similarity": result.similarity,
                "diff_pixels": result.diff_pixels,
                "diff_percentage": result.diff_percentage,
                "diff_regions": len(result.diff_regions),
                "diff_image": result.diff_path
            }
        except Exception as e:
            self.log(f"  Fehler: {e}", "ERROR")
            return {"error": str(e)}

    def _run_responsive_tests(self) -> dict:
        """Führt Responsive Tests aus."""
        try:
            from test_engine import UITestEngine
            from visual_regression import ResponsiveDesignTester

            engine = UITestEngine(SCREENSHOTS_DIR, save_screenshots=True, ocr_enabled=False)
            window = engine.find_window("Frank")

            if not window:
                self.log("  Chat Overlay nicht gefunden - überspringe", "WARN")
                return {"skipped": True, "reason": "window_not_found"}

            tester = ResponsiveDesignTester(SCREENSHOTS_DIR / "responsive")

            # Nur wichtigste Größen testen
            sizes = ["mobile", "tablet", "desktop"] if self.mode != "thorough" else None
            results = tester.test_common_sizes(
                window["wid"],
                lambda: engine.capture_window("Frank"),
                sizes
            )

            passed = sum(1 for r in results if r.get("size_match"))
            self.log(f"  {passed}/{len(results)} Größen OK", "OK" if passed == len(results) else "WARN")

            return {
                "tested": len(results),
                "passed": passed,
                "results": results
            }
        except Exception as e:
            self.log(f"  Fehler: {e}", "ERROR")
            return {"error": str(e)}

    def _run_heatmap_analysis(self) -> dict:
        """Führt Heatmap-Analyse aus."""
        try:
            from test_engine import UITestEngine
            from heatmap_analyzer import HeatmapAnalyzer

            engine = UITestEngine(SCREENSHOTS_DIR, save_screenshots=True, ocr_enabled=False)
            window = engine.find_window("Frank")

            if not window:
                return {"skipped": True, "reason": "window_not_found"}

            analyzer = HeatmapAnalyzer(SCREENSHOTS_DIR / "heatmaps")

            # Simulation
            self.log("  Simuliere 30s Benutzer-Interaktion...")
            region = (window["x"], window["y"], window["w"], window["h"])
            analyzer.simulate_user_session(region, 30)

            # Heatmaps generieren
            base_img = engine.capture_window("Frank")
            if base_img:
                paths = analyzer.save_heatmaps(base_img, "analysis")
                self.log(f"  Heatmaps erstellt", "OK")

            report = analyzer.generate_report()
            return report
        except Exception as e:
            self.log(f"  Fehler: {e}", "ERROR")
            return {"error": str(e)}

    def _generate_markdown_report(self) -> str:
        """Generiert detaillierten Markdown-Report."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"ui_test_report_{timestamp}.md"
        filepath = REPORTS_DIR / filename

        duration = (self.end_time - self.start_time).total_seconds()

        lines = []

        # Header
        lines.append("# Frank AI - UI Test Report")
        lines.append("")
        lines.append(f"**Datum:** {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**Modus:** {self.mode.upper()}")
        lines.append(f"**Dauer:** {duration:.0f} Sekunden")
        lines.append("")

        # Zusammenfassung
        lines.append("## Zusammenfassung")
        lines.append("")
        lines.append("| Bereich | Status | Score/Ergebnis |")
        lines.append("|---------|--------|----------------|")

        # Basic Tests
        basic = self.results.get("basic_tests", {})
        if "error" not in basic:
            status = "✅" if basic.get("failed", 0) == 0 else "⚠️"
            lines.append(f"| Basis-Tests | {status} | {basic.get('passed', 0)}/{basic.get('total', 0)} bestanden |")

        # Design
        design = self.results.get("design", {})
        if "error" not in design:
            score = design.get("overall_score", 0)
            status = "✅" if score >= 70 else "⚠️" if score >= 50 else "❌"
            lines.append(f"| Design | {status} | {score}/100 |")

        # Workflow
        workflow = self.results.get("workflow", {})
        if "error" not in workflow:
            metrics = workflow.get("metrics", {})
            eff = metrics.get("efficiency", "N/A")
            # FIX: Sichere Konvertierung mit try/except
            try:
                eff_value = float(str(eff).replace("/100", "").replace("%", ""))
                status = "✅" if eff_value >= 80 else "⚠️"
            except (ValueError, TypeError):
                status = "⚠️"
            lines.append(f"| Workflow | {status} | Effizienz: {eff} |")

        # Regression
        regression = self.results.get("regression", {})
        if "error" not in regression:
            status = "✅" if regression.get("passed") else "❌"
            sim = regression.get("similarity", 0)
            lines.append(f"| Visual Regression | {status} | {sim}% Übereinstimmung |")

        # Responsive
        responsive = self.results.get("responsive", {})
        if not responsive.get("skipped") and "error" not in responsive:
            p = responsive.get("passed", 0)
            t = responsive.get("tested", 0)
            status = "✅" if p == t else "⚠️"
            lines.append(f"| Responsive | {status} | {p}/{t} Größen OK |")

        # Heatmap (nur in thorough mode)
        heatmap = self.results.get("heatmap", {})
        if not heatmap.get("skipped") and "error" not in heatmap:
            stats = heatmap.get("statistics", {})
            dead_zones = stats.get("dead_zones", 0)
            total_clicks = stats.get("total_clicks", 0)
            status = "✅" if dead_zones < 100 and total_clicks > 0 else "⚠️"
            lines.append(f"| Heatmap | {status} | {total_clicks} Klicks, {dead_zones} tote Zonen |")

        lines.append("")

        # Detail: Design
        lines.append("## Design-Analyse")
        lines.append("")

        if "error" not in design:
            lines.append(f"- **Gesamt-Score:** {design.get('overall_score', 'N/A')}/100")
            lines.append(f"- **Kontrast-Score:** {design.get('contrast_score', 'N/A')}/100")
            lines.append(f"- **Layout-Score:** {design.get('layout_score', 'N/A')}/100")
            lines.append(f"- **Farbharmonie:** {design.get('color_harmony', 'N/A')}")
            lines.append(f"- **WCAG-konform:** {'Ja' if design.get('wcag_compliant') else 'Nein'}")
            lines.append("")

            # Farbpalette
            colors = design.get("colors", [])
            if colors:
                lines.append("### Farbpalette")
                lines.append("")
                lines.append("| Farbe | Hex |")
                lines.append("|-------|-----|")
                for c in colors[:6]:
                    lines.append(f"| 🎨 | `{c}` |")
                lines.append("")

            # Accessibility Issues
            issues = design.get("accessibility_issues", [])
            if issues:
                lines.append("### Accessibility-Probleme")
                lines.append("")
                for issue in issues:
                    lines.append(f"- ⚠️ {issue}")
                lines.append("")
        else:
            lines.append(f"❌ Fehler: {design.get('error')}")
            lines.append("")

        # Detail: Verbesserungsvorschläge
        lines.append("## Verbesserungsvorschläge")
        lines.append("")

        suggestions = design.get("suggestions", [])
        if suggestions:
            severity_icons = {"critical": "🔴", "major": "🟠", "minor": "🟡", "info": "🔵"}

            for s in suggestions:
                icon = severity_icons.get(s.get("severity"), "⚪")
                lines.append(f"### {icon} {s.get('title', 'Unbekannt')}")
                lines.append("")
                lines.append(f"{s.get('description', '')}")
                lines.append("")
                lines.append(f"- **Aktuell:** `{s.get('current', 'N/A')}`")
                lines.append(f"- **Empfohlen:** `{s.get('suggested', 'N/A')}`")
                lines.append("")

                css = s.get("css")
                if css:
                    lines.append("```css")
                    lines.append(css)
                    lines.append("```")
                    lines.append("")
        else:
            lines.append("✅ Keine kritischen Verbesserungen erforderlich.")
            lines.append("")

        # Detail: Workflow
        lines.append("## Workflow-Analyse")
        lines.append("")

        if "error" not in workflow:
            metrics = workflow.get("metrics", {})
            lines.append("### UX-Metriken")
            lines.append("")
            lines.append("| Metrik | Wert |")
            lines.append("|--------|------|")
            lines.append(f"| Reaktionszeit (Durchschnitt) | {metrics.get('response_time_avg', 'N/A')} |")
            lines.append(f"| Task Completion Rate | {metrics.get('task_completion_rate', 'N/A')} |")
            lines.append(f"| Fehlerrate | {metrics.get('error_rate', 'N/A')} |")
            lines.append(f"| Interaktions-Smoothness | {metrics.get('smoothness', 'N/A')} |")
            lines.append(f"| Workflow-Effizienz | {metrics.get('efficiency', 'N/A')} |")
            lines.append("")

            # Workflow Details
            wf_list = workflow.get("workflows", [])
            if wf_list:
                lines.append("### Workflow-Ergebnisse")
                lines.append("")
                lines.append("| Workflow | Status | Zeit | Schritte |")
                lines.append("|----------|--------|------|----------|")
                for wf in wf_list:
                    status = "✅" if wf.get("success") else "❌"
                    lines.append(f"| {wf.get('name', 'N/A')} | {status} | {wf.get('time', 'N/A')} | {wf.get('steps', 'N/A')} |")
                lines.append("")
        else:
            lines.append(f"❌ Fehler: {workflow.get('error')}")
            lines.append("")

        # Detail: Visual Regression
        lines.append("## Visual Regression")
        lines.append("")

        if "error" not in regression:
            status = "✅ Bestanden" if regression.get("passed") else "❌ Regression erkannt!"
            lines.append(f"**Status:** {status}")
            lines.append("")
            lines.append(f"- **Übereinstimmung:** {regression.get('similarity', 'N/A')}%")
            lines.append(f"- **Unterschiedliche Pixel:** {regression.get('diff_pixels', 'N/A')}")
            lines.append(f"- **Abweichung:** {regression.get('diff_percentage', 'N/A')}%")
            lines.append(f"- **Betroffene Regionen:** {regression.get('diff_regions', 'N/A')}")

            if regression.get("diff_image"):
                lines.append(f"- **Diff-Bild:** `{regression.get('diff_image')}`")
            lines.append("")
        else:
            lines.append(f"❌ Fehler: {regression.get('error')}")
            lines.append("")

        # Detail: Responsive
        lines.append("## Responsive Design")
        lines.append("")

        if not responsive.get("skipped") and "error" not in responsive:
            results = responsive.get("results", [])
            if results:
                lines.append("| Größe | Angefordert | Tatsächlich | Status |")
                lines.append("|-------|-------------|-------------|--------|")
                for r in results:
                    req = r.get("requested_size", ("?", "?"))
                    act = r.get("actual_size", ("?", "?"))
                    status = "✅" if r.get("size_match") else "⚠️"
                    lines.append(f"| {r.get('name', 'N/A')} | {req[0]}x{req[1]} | {act[0]}x{act[1]} | {status} |")
                lines.append("")
        elif responsive.get("skipped"):
            lines.append(f"⚠️ Übersprungen: {responsive.get('reason', 'N/A')}")
            lines.append("")

        # Detail: Heatmap (wenn vorhanden)
        heatmap = self.results.get("heatmap", {})
        if not heatmap.get("skipped") and "error" not in heatmap:
            lines.append("## Heatmap-Analyse")
            lines.append("")

            stats = heatmap.get("statistics", {})
            if stats:
                lines.append("### Interaktions-Statistiken")
                lines.append("")
                lines.append("| Metrik | Wert |")
                lines.append("|--------|------|")
                lines.append(f"| Gesamt-Events | {stats.get('total_events', 'N/A')} |")
                lines.append(f"| Gesamt-Klicks | {stats.get('total_clicks', 'N/A')} |")
                lines.append(f"| Fokus-Zeit | {stats.get('total_focus_time', 'N/A')} |")
                lines.append(f"| Einzigartige Klick-Bereiche | {stats.get('unique_click_areas', 'N/A')} |")
                lines.append(f"| Tote Zonen | {stats.get('dead_zones', 'N/A')} |")
                lines.append("")

            hotspots = heatmap.get("hotspots", [])
            if hotspots:
                lines.append("### Hotspots (Top 5)")
                lines.append("")
                lines.append("| Rang | Position | Klicks | Fokus-Zeit |")
                lines.append("|------|----------|--------|------------|")
                for hs in hotspots[:5]:
                    lines.append(f"| {hs.get('rank', '?')} | ({hs.get('x', '?')}, {hs.get('y', '?')}) | {hs.get('clicks', 0)} | {hs.get('focus_time', 0):.1f}s |")
                lines.append("")

            recommendations = heatmap.get("recommendations", [])
            if recommendations:
                lines.append("### UX-Empfehlungen aus Heatmap")
                lines.append("")
                for rec in recommendations:
                    lines.append(f"- {rec}")
                lines.append("")

        # Empfehlungen
        lines.append("## Handlungsempfehlungen")
        lines.append("")

        # Prioritäten generieren
        priorities = []

        # Kritische Suggestions
        critical = [s for s in suggestions if s.get("severity") == "critical"]
        if critical:
            for s in critical:
                priorities.append(f"1. **[KRITISCH]** {s.get('title')}: {s.get('suggested', '')[:100]}")

        # Design Score
        if design.get("overall_score", 100) < 70:
            priorities.append("2. **[DESIGN]** Design-Score unter 70 - Kontrast und Layout verbessern")

        # Workflow Failures
        failed_wf = [w for w in workflow.get("workflows", []) if not w.get("success")]
        if failed_wf:
            priorities.append(f"3. **[WORKFLOW]** {len(failed_wf)} Workflows fehlgeschlagen - Interaktionen prüfen")

        # Regression
        if not regression.get("passed", True):
            priorities.append("4. **[REGRESSION]** Visuelle Änderungen erkannt - prüfen ob gewollt")

        if priorities:
            for p in priorities:
                lines.append(f"- {p}")
        else:
            lines.append("✅ Keine kritischen Handlungen erforderlich. UI ist in gutem Zustand.")

        lines.append("")

        # Footer
        lines.append("---")
        lines.append("")
        lines.append(f"*Report generiert am {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} mit Frank AI UI Test v2.0*")

        # Speichern
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        # Auch JSON speichern
        json_path = REPORTS_DIR / f"ui_test_data_{timestamp}.json"
        with open(json_path, "w") as f:
            json.dump(self.results, f, indent=2, default=str)

        return str(filepath)


def main():
    parser = argparse.ArgumentParser(
        description="Frank AI - One-Click UI Test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modi:
  --quick     Schnelltest (~1 Minute)
  --standard  Standard (~5 Minuten) [Default]
  --thorough  Gründlich (~15 Minuten, inkl. Heatmap)
  --extended  Erweitert (~30 Minuten, vollständig)

Beispiel:
  python3 one_click_test.py
  python3 one_click_test.py --quick
  python3 one_click_test.py --extended --headless
        """
    )

    parser.add_argument("--quick", action="store_true", help="Schnelltest (~1 Min)")
    parser.add_argument("--thorough", action="store_true", help="Gründlich (~15 Min)")
    parser.add_argument("--extended", action="store_true", help="Erweitert (~30 Min)")
    parser.add_argument("--headless", action="store_true", help="Headless-Modus (Xvfb)")

    args = parser.parse_args()

    # Modus bestimmen
    if args.quick:
        mode = "quick"
    elif args.thorough:
        mode = "thorough"
    elif args.extended:
        mode = "extended"
    else:
        mode = "standard"

    # Headless Setup
    xvfb_process = None
    if args.headless:
        import subprocess
        try:
            xvfb_process = subprocess.Popen(
                ["Xvfb", ":99", "-screen", "0", "1920x1080x24"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            time.sleep(1)
            os.environ["DISPLAY"] = ":99"
            print("Xvfb gestartet")
        except Exception as e:
            print(f"Xvfb Fehler: {e}")

    try:
        tester = OneClickTester(mode=mode, headless=args.headless)
        tester.run_all()
    finally:
        if xvfb_process:
            xvfb_process.terminate()


if __name__ == "__main__":
    main()
