#!/usr/bin/env python3
"""
Frank AI - UI Test CLI Runner (Extended)
=========================================
Kommandozeilen-Version mit allen Features inkl. Headless-Modus.

Beispiele:
    # Alle Tests, 5 Minuten
    python3 cli_runner.py --duration 5

    # Headless-Modus für CI/CD
    python3 cli_runner.py --headless --duration 10

    # Visual Regression Test
    python3 cli_runner.py --regression --baseline-update

    # Design-Analyse mit konkreten Vorschlägen
    python3 cli_runner.py --design --concrete

    # Responsive Tests
    python3 cli_runner.py --responsive
"""

import argparse
import os
import subprocess
import sys
import time
import json
from datetime import datetime
from pathlib import Path

# Import test modules
from test_engine import UITestEngine
from test_cases import get_all_test_cases

BASE_DIR = Path(__file__).parent
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
REPORTS_DIR = BASE_DIR / "reports"
BASELINE_DIR = BASE_DIR / "baseline"


def setup_headless():
    """Startet Xvfb für Headless-Modus."""
    display = os.environ.get("DISPLAY")

    if display:
        return display, None  # Bereits ein Display vorhanden

    # Prüfe ob Xvfb verfügbar
    try:
        subprocess.run(["which", "Xvfb"], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        print("ERROR: Xvfb nicht installiert. Installiere mit: sudo apt install xvfb")
        sys.exit(1)

    # Starte Xvfb
    display_num = 99
    xvfb_cmd = ["Xvfb", f":{display_num}", "-screen", "0", "1920x1080x24"]

    try:
        xvfb_process = subprocess.Popen(
            xvfb_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(1)  # Warten auf Start

        os.environ["DISPLAY"] = f":{display_num}"
        print(f"Xvfb gestartet auf Display :{display_num}")

        return f":{display_num}", xvfb_process

    except Exception as e:
        print(f"ERROR: Konnte Xvfb nicht starten: {e}")
        sys.exit(1)


def cleanup_headless(xvfb_process):
    """Beendet Xvfb."""
    if xvfb_process:
        xvfb_process.terminate()
        xvfb_process.wait()
        print("Xvfb beendet")


def run_tests(args, log):
    """Führt normale Tests aus."""
    # Parse test list
    if args.tests == "all":
        test_ids = ["all"]
    else:
        test_ids = [t.strip() for t in args.tests.split(",")]

    engine = UITestEngine(
        screenshots_dir=SCREENSHOTS_DIR,
        save_screenshots=not args.no_screenshots,
        ocr_enabled=not args.no_ocr,
        log_callback=log
    )

    start_time = time.time()
    end_time = start_time + (args.duration * 60)
    iteration = 0

    try:
        while time.time() < end_time:
            iteration += 1
            remaining = max(0, int((end_time - time.time()) / 60))
            log(f"--- Iteration {iteration} (noch {remaining} min) ---")

            results = engine.run_tests(test_ids)

            for test_id, result in results.items():
                if result["passed"]:
                    log(f"  ✓ {test_id}: PASSED", "OK")
                else:
                    log(f"  ✗ {test_id}: FAILED - {result.get('error', 'Unknown')}", "ERROR")

            time.sleep(args.interval)

    except KeyboardInterrupt:
        log("\nTests durch Benutzer abgebrochen", "WARN")

    return engine.generate_report()


def run_regression(args, log):
    """Führt Visual Regression Tests aus."""
    try:
        from visual_regression import VisualRegressionTester
    except ImportError:
        log("Visual Regression Modul nicht verfügbar", "ERROR")
        return {"error": "module_not_found"}

    engine = UITestEngine(
        screenshots_dir=SCREENSHOTS_DIR,
        save_screenshots=True,
        ocr_enabled=False,
        log_callback=log
    )

    tester = VisualRegressionTester(
        baseline_dir=BASELINE_DIR,
        output_dir=SCREENSHOTS_DIR,
        threshold=args.threshold
    )

    log("=== Visual Regression Tests ===")

    # Capture current state
    img = engine.capture_window("Frank")
    if not img:
        img = engine.take_screenshot()

    if not img:
        log("Konnte keinen Screenshot erstellen", "ERROR")
        return {"error": "capture_failed"}

    test_name = args.regression_name or "chat_overlay"

    if args.baseline_update:
        path = tester.save_baseline(test_name, img)
        log(f"Baseline aktualisiert: {path}", "OK")
        return {"baseline_updated": path}

    # Compare with baseline
    result = tester.compare(test_name, img, create_baseline_if_missing=True)

    if result.passed:
        log(f"✓ Regression Test bestanden - Ähnlichkeit: {result.similarity}%", "OK")
    else:
        log(f"✗ Regression Test fehlgeschlagen!", "ERROR")
        log(f"  Ähnlichkeit: {result.similarity}%", "ERROR")
        log(f"  Unterschiede: {result.diff_pixels} Pixel ({result.diff_percentage}%)", "ERROR")
        log(f"  Diff-Bild: {result.diff_path}", "INFO")

    return tester.generate_report()


def run_design_analysis(args, log):
    """Führt Design-Analyse aus."""
    try:
        from design_analyzer import DesignAnalyzer
        from concrete_suggestions import ConcreteSuggestionGenerator
    except ImportError as e:
        log(f"Design Module nicht verfügbar: {e}", "ERROR")
        return {"error": "module_not_found"}

    engine = UITestEngine(
        screenshots_dir=SCREENSHOTS_DIR,
        save_screenshots=True,
        ocr_enabled=False,
        log_callback=log
    )

    log("=== Design-Analyse ===")

    img = engine.capture_window("Frank")
    if not img:
        img = engine.take_screenshot()

    if not img:
        log("Konnte keinen Screenshot erstellen", "ERROR")
        return {"error": "capture_failed"}

    analyzer = DesignAnalyzer(REPORTS_DIR)
    report = analyzer.analyze_image(img)

    log(f"Gesamt-Score: {report.overall_score}/100",
        "OK" if report.overall_score >= 70 else "WARN")
    log(f"Kontrast: {report.contrast_score:.0f}/100")
    log(f"Layout: {report.layout_score:.0f}/100")
    log(f"Farbharmonie: {report.color_harmony}")

    # Konkrete Vorschläge generieren
    if args.concrete:
        generator = ConcreteSuggestionGenerator()
        suggestions = generator.generate_from_design_report(report)

        log(f"\n=== Konkrete Verbesserungsvorschläge ({len(suggestions)}) ===")

        for s in suggestions:
            severity_icon = {"critical": "🔴", "major": "🟠", "minor": "🟡"}.get(s.severity, "🔵")
            log(f"{severity_icon} {s.title}")
            log(f"   Aktuell: {s.current_value}")
            log(f"   Empfohlen: {s.suggested_value}")
            if s.css_fix:
                log(f"   CSS: {s.css_fix[:60]}...")

        # Markdown speichern
        md_path = REPORTS_DIR / f"suggestions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        with open(md_path, "w") as f:
            f.write(generator.format_as_markdown())
        log(f"\nVorschläge gespeichert: {md_path}", "OK")

    # HTML Report
    html_path = analyzer.generate_html_report(report, img)
    log(f"HTML Report: {html_path}", "OK")

    return {
        "overall_score": report.overall_score,
        "contrast_score": report.contrast_score,
        "layout_score": report.layout_score,
        "color_harmony": report.color_harmony,
        "wcag_compliant": report.wcag_compliant
    }


def run_responsive_tests(args, log):
    """Führt Responsive Design Tests aus."""
    try:
        from visual_regression import ResponsiveDesignTester
    except ImportError:
        log("Responsive Test Modul nicht verfügbar", "ERROR")
        return {"error": "module_not_found"}

    engine = UITestEngine(
        screenshots_dir=SCREENSHOTS_DIR,
        save_screenshots=True,
        ocr_enabled=False,
        log_callback=log
    )

    log("=== Responsive Design Tests ===")

    # Finde Window
    window = engine.find_window("Frank")
    if not window:
        log("Chat Overlay nicht gefunden", "ERROR")
        return {"error": "window_not_found"}

    tester = ResponsiveDesignTester(SCREENSHOTS_DIR / "responsive")

    # Capture function
    def capture():
        return engine.capture_window("Frank")

    # Welche Größen testen
    if args.responsive_sizes:
        sizes = [s.strip() for s in args.responsive_sizes.split(",")]
    else:
        sizes = ["mobile", "tablet", "laptop", "desktop"]

    log(f"Teste Größen: {', '.join(sizes)}")

    results = tester.test_common_sizes(window["wid"], capture, sizes)

    for r in results:
        if "error" in r:
            log(f"  ✗ {r['name']}: {r['error']}", "ERROR")
        elif r.get("size_match"):
            log(f"  ✓ {r['name']}: {r['actual_size'][0]}x{r['actual_size'][1]}", "OK")
        else:
            log(f"  ⚠ {r['name']}: Größe weicht ab", "WARN")

    return tester.generate_report()


def run_heatmap_analysis(args, log):
    """Führt Heatmap-Analyse aus."""
    try:
        from heatmap_analyzer import HeatmapAnalyzer
    except ImportError:
        log("Heatmap Modul nicht verfügbar", "ERROR")
        return {"error": "module_not_found"}

    engine = UITestEngine(
        screenshots_dir=SCREENSHOTS_DIR,
        save_screenshots=True,
        ocr_enabled=False,
        log_callback=log
    )

    log("=== Heatmap-Analyse ===")

    window = engine.find_window("Frank")
    if not window:
        log("Chat Overlay nicht gefunden", "ERROR")
        return {"error": "window_not_found"}

    analyzer = HeatmapAnalyzer(SCREENSHOTS_DIR / "heatmaps")

    # Simuliere User-Session
    log(f"Simuliere {args.heatmap_duration}s Benutzer-Session...")

    region = (window["x"], window["y"], window["w"], window["h"])
    analyzer.simulate_user_session(region, args.heatmap_duration)

    # Base image für Overlay
    base_img = engine.capture_window("Frank")
    if base_img:
        paths = analyzer.save_heatmaps(base_img, "overlay")
        log(f"Klick-Heatmap: {paths['click_heatmap']}", "OK")
        log(f"Fokus-Heatmap: {paths['focus_heatmap']}", "OK")

    report = analyzer.generate_report()

    log("\n=== Hotspots ===")
    for h in report.get("hotspots", [])[:5]:
        log(f"  #{h['rank']}: ({h['x']}, {h['y']}) - {h['clicks']} Klicks")

    log("\n=== Empfehlungen ===")
    for rec in report.get("recommendations", []):
        log(f"  → {rec}")

    return report


def main():
    parser = argparse.ArgumentParser(
        description="Frank AI UI Test Runner (CLI) - Extended",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modi:
  Standard:    Normale UI-Tests über Zeit
  --regression: Visual Regression Tests
  --design:    Design-Analyse
  --responsive: Responsive Design Tests
  --heatmap:   Heatmap-Analyse

Beispiele:
  %(prog)s --duration 5
  %(prog)s --headless --duration 10 --no-ocr
  %(prog)s --regression --baseline-update
  %(prog)s --design --concrete
  %(prog)s --responsive --responsive-sizes mobile,tablet
        """
    )

    # Allgemeine Optionen
    parser.add_argument("--duration", "-d", type=int, default=15,
                       help="Testdauer in Minuten (default: 15)")
    parser.add_argument("--interval", "-i", type=int, default=30,
                       help="Intervall zwischen Tests in Sekunden (default: 30)")
    parser.add_argument("--tests", "-t", type=str, default="all",
                       help="Komma-separierte Liste von Tests oder 'all'")
    parser.add_argument("--no-ocr", action="store_true",
                       help="OCR deaktivieren")
    parser.add_argument("--no-screenshots", action="store_true",
                       help="Screenshots nicht speichern")
    parser.add_argument("--list", action="store_true",
                       help="Verfügbare Tests auflisten")

    # Headless
    parser.add_argument("--headless", action="store_true",
                       help="Headless-Modus (startet Xvfb automatisch)")

    # Visual Regression
    parser.add_argument("--regression", action="store_true",
                       help="Visual Regression Test ausführen")
    parser.add_argument("--baseline-update", action="store_true",
                       help="Baseline aktualisieren statt vergleichen")
    parser.add_argument("--regression-name", type=str, default="chat_overlay",
                       help="Name für Regression Test (default: chat_overlay)")
    parser.add_argument("--threshold", type=float, default=0.1,
                       help="Max. erlaubte Differenz in %% (default: 0.1)")

    # Design-Analyse
    parser.add_argument("--design", action="store_true",
                       help="Design-Analyse ausführen")
    parser.add_argument("--concrete", action="store_true",
                       help="Konkrete Verbesserungsvorschläge generieren")

    # Responsive
    parser.add_argument("--responsive", action="store_true",
                       help="Responsive Design Tests ausführen")
    parser.add_argument("--responsive-sizes", type=str,
                       help="Komma-separierte Liste: mobile,tablet,laptop,desktop")

    # Heatmap
    parser.add_argument("--heatmap", action="store_true",
                       help="Heatmap-Analyse ausführen")
    parser.add_argument("--heatmap-duration", type=int, default=30,
                       help="Dauer der Heatmap-Simulation in Sekunden")

    args = parser.parse_args()

    # Liste Tests
    if args.list:
        print("\nVerfügbare Tests:")
        print("-" * 60)
        for test_id, info in get_all_test_cases().items():
            print(f"  {test_id}")
            print(f"    {info['name']} - {info['description']}")
        print()
        return

    # Setup directories
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)

    # Headless setup
    xvfb_process = None
    if args.headless:
        display, xvfb_process = setup_headless()

    # Logging
    def log(msg, level="INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        colors = {
            "INFO": "\033[94m", "OK": "\033[92m",
            "WARN": "\033[93m", "ERROR": "\033[91m"
        }
        reset = "\033[0m"
        color = colors.get(level, "")
        print(f"[{timestamp}] {color}[{level}]{reset} {msg}")

    # Header
    print("=" * 60)
    print("  Frank AI - UI Test Runner (CLI) v2.0")
    print("=" * 60)

    if args.headless:
        print(f"  Modus:      Headless (Display {os.environ.get('DISPLAY', 'N/A')})")

    try:
        # Welcher Modus?
        if args.regression:
            report = run_regression(args, log)
        elif args.design:
            report = run_design_analysis(args, log)
        elif args.responsive:
            report = run_responsive_tests(args, log)
        elif args.heatmap:
            report = run_heatmap_analysis(args, log)
        else:
            print(f"  Dauer:      {args.duration} Minuten")
            print(f"  Intervall:  {args.interval} Sekunden")
            print(f"  Tests:      {args.tests}")
            print("=" * 60)
            print()
            report = run_tests(args, log)

        # Report speichern
        report_file = REPORTS_DIR / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, "w") as f:
            json.dump(report, f, indent=2, default=str)

        print()
        print("=" * 60)
        print(f"  Report: {report_file}")
        print("=" * 60)

        # Exit code
        if "error" in report:
            sys.exit(1)
        elif "failed" in report and report["failed"] > 0:
            sys.exit(1)
        else:
            sys.exit(0)

    finally:
        cleanup_headless(xvfb_process)


if __name__ == "__main__":
    main()
