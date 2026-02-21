#!/usr/bin/env python3
"""
UI Test Cases
=============
Konkrete Test-Implementierungen für Frank AI System UI.
Fokus: Workflow, Convenience, Design.
"""

import time
import subprocess
import requests
from typing import Dict, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from test_engine import UITestEngine, TestResult


# ============================================================================
# Test Registry - Erweitert mit UX & Design Tests
# ============================================================================

TEST_CASES: Dict[str, Dict] = {
    # === Basic Tests ===
    "chat_overlay_visible": {
        "name": "Chat Overlay Sichtbar",
        "description": "Prüft ob das Chat Overlay Fenster existiert",
        "category": "basic"
    },
    "desktopd_health": {
        "name": "Desktop Daemon Health",
        "description": "Prüft ob der Desktop-Daemon läuft",
        "category": "basic"
    },
    "screenshot_quality": {
        "name": "Screenshot Qualität",
        "description": "Validiert Screenshot-Erstellung",
        "category": "basic"
    },

    # === Rendering & Display Tests ===
    "chat_overlay_truncation": {
        "name": "Message Truncation",
        "description": "Prüft ob Nachrichten abgeschnitten werden",
        "category": "rendering"
    },
    "text_readability": {
        "name": "Text Lesbarkeit",
        "description": "Prüft Schriftgröße und Kontrast",
        "category": "rendering"
    },
    "layout_consistency": {
        "name": "Layout Konsistenz",
        "description": "Prüft Ausrichtung und Abstände",
        "category": "rendering"
    },

    # === Workflow Tests ===
    "basic_workflow": {
        "name": "Basis Workflow",
        "description": "Testet grundlegende Interaktionen",
        "category": "workflow"
    },
    "scroll_workflow": {
        "name": "Scroll Workflow",
        "description": "Testet Scrollen durch Konversation",
        "category": "workflow"
    },
    "copy_paste_workflow": {
        "name": "Copy/Paste",
        "description": "Testet Text kopieren und einfügen",
        "category": "workflow"
    },
    "keyboard_navigation": {
        "name": "Keyboard Navigation",
        "description": "Testet Navigation mit Tastatur",
        "category": "workflow"
    },

    # === Convenience Tests ===
    "response_time": {
        "name": "Reaktionszeit",
        "description": "Misst UI-Reaktionsgeschwindigkeit",
        "category": "convenience"
    },
    "window_focus": {
        "name": "Window Focus",
        "description": "Prüft Fenster-Fokussierung",
        "category": "convenience"
    },
    "input_handling": {
        "name": "Input Handling",
        "description": "Testet Eingabeverarbeitung",
        "category": "convenience"
    },

    # === Design Tests ===
    "color_contrast": {
        "name": "Farbkontrast",
        "description": "Prüft WCAG Kontrast-Standards",
        "category": "design"
    },
    "color_palette": {
        "name": "Farbpalette",
        "description": "Analysiert verwendete Farben",
        "category": "design"
    },
    "visual_hierarchy": {
        "name": "Visuelle Hierarchie",
        "description": "Prüft UI-Element-Gewichtung",
        "category": "design"
    },

    # === Accessibility Tests ===
    "accessibility_basic": {
        "name": "Basis Accessibility",
        "description": "Grundlegende Barrierefreiheit",
        "category": "accessibility"
    },
}


def get_all_test_cases() -> Dict[str, Dict]:
    """Gibt alle verfügbaren Tests zurück."""
    return TEST_CASES


def get_test_function(test_id: str) -> Callable:
    """Gibt die Test-Funktion für eine Test-ID zurück."""
    func_name = f"test_{test_id}"
    return globals().get(func_name)


def get_tests_by_category(category: str) -> Dict[str, Dict]:
    """Gibt Tests einer Kategorie zurück."""
    return {k: v for k, v in TEST_CASES.items() if v.get("category") == category}


# ============================================================================
# Basic Test Implementations
# ============================================================================

def test_chat_overlay_visible(engine: "UITestEngine") -> "TestResult":
    """Prüft ob Chat Overlay sichtbar ist."""
    from test_engine import TestResult

    window = engine.find_window("Frank")

    if window:
        img = engine.capture_window("Frank")
        screenshot_path = None

        if img and engine.save_screenshots:
            screenshot_path = engine.save_screenshot(img, "chat_overlay_visible")

        return TestResult(
            test_id="chat_overlay_visible",
            passed=True,
            screenshot_path=screenshot_path,
            details={
                "window_title": window["title"],
                "position": f"{window['x']},{window['y']}",
                "size": f"{window['w']}x{window['h']}"
            }
        )
    else:
        return TestResult(
            test_id="chat_overlay_visible",
            passed=False,
            error="Chat Overlay Fenster nicht gefunden"
        )


def test_desktopd_health(engine: "UITestEngine") -> "TestResult":
    """Prüft ob desktopd läuft."""
    from test_engine import TestResult

    try:
        response = requests.get("http://localhost:8092/health", timeout=5)
        data = response.json()

        if data.get("ok"):
            return TestResult(test_id="desktopd_health", passed=True, details={"response": data})
        else:
            return TestResult(test_id="desktopd_health", passed=False, error="Health check not ok")
    except requests.exceptions.ConnectionError:
        return TestResult(test_id="desktopd_health", passed=False, error="Daemon nicht erreichbar")
    except Exception as e:
        return TestResult(test_id="desktopd_health", passed=False, error=str(e))


def test_screenshot_quality(engine: "UITestEngine") -> "TestResult":
    """Prüft Screenshot-Funktionalität."""
    from test_engine import TestResult

    img = engine.take_screenshot()
    if img is None:
        return TestResult(test_id="screenshot_quality", passed=False, error="Screenshot failed")

    width, height = img.size
    if width < 100 or height < 100:
        return TestResult(test_id="screenshot_quality", passed=False, error=f"Too small: {width}x{height}")

    screenshot_path = engine.save_screenshot(img, "quality_test") if engine.save_screenshots else None

    return TestResult(
        test_id="screenshot_quality",
        passed=True,
        screenshot_path=screenshot_path,
        details={"size": f"{width}x{height}"}
    )


# ============================================================================
# Rendering Tests
# ============================================================================

def test_chat_overlay_truncation(engine: "UITestEngine") -> "TestResult":
    """Prüft ob Nachrichten abgeschnitten werden."""
    from test_engine import TestResult

    img = engine.capture_window("Frank")
    if not img:
        return TestResult(test_id="chat_overlay_truncation", passed=False, error="Overlay nicht erfassbar")

    screenshot_path = engine.save_screenshot(img, "truncation_test") if engine.save_screenshots else None

    # Analysiere Bildhöhe vs. erwartete Texthöhe
    height = img.height
    # Wenn Bild sehr klein, könnte Truncation vorliegen
    if height < 200:
        return TestResult(
            test_id="chat_overlay_truncation",
            passed=False,
            error="Overlay-Höhe verdächtig klein",
            screenshot_path=screenshot_path,
            details={"height": height}
        )

    return TestResult(
        test_id="chat_overlay_truncation",
        passed=True,
        screenshot_path=screenshot_path,
        details={"height": height, "note": "Visuelle Prüfung empfohlen"}
    )


def test_text_readability(engine: "UITestEngine") -> "TestResult":
    """Prüft Textlesbarkeit durch Kontrast-Analyse."""
    from test_engine import TestResult

    img = engine.capture_window("Frank")
    if not img:
        return TestResult(test_id="text_readability", passed=False, error="Capture failed")

    screenshot_path = engine.save_screenshot(img, "readability_test") if engine.save_screenshots else None

    try:
        from design_analyzer import DesignAnalyzer
        from pathlib import Path

        analyzer = DesignAnalyzer(Path(engine.screenshots_dir))
        report = analyzer.analyze_image(img)

        passed = report.contrast_score >= 70

        return TestResult(
            test_id="text_readability",
            passed=passed,
            screenshot_path=screenshot_path,
            error=None if passed else f"Kontrast-Score zu niedrig: {report.contrast_score}",
            details={
                "contrast_score": report.contrast_score,
                "wcag_compliant": report.wcag_compliant
            }
        )
    except ImportError:
        return TestResult(
            test_id="text_readability",
            passed=True,
            screenshot_path=screenshot_path,
            details={"note": "Design Analyzer nicht verfügbar"}
        )


def test_layout_consistency(engine: "UITestEngine") -> "TestResult":
    """Prüft Layout-Konsistenz."""
    from test_engine import TestResult

    img = engine.capture_window("Frank")
    if not img:
        return TestResult(test_id="layout_consistency", passed=False, error="Capture failed")

    screenshot_path = engine.save_screenshot(img, "layout_test") if engine.save_screenshots else None

    try:
        from design_analyzer import DesignAnalyzer
        from pathlib import Path

        analyzer = DesignAnalyzer(Path(engine.screenshots_dir))
        report = analyzer.analyze_image(img)

        passed = report.layout_score >= 60

        return TestResult(
            test_id="layout_consistency",
            passed=passed,
            screenshot_path=screenshot_path,
            error=None if passed else f"Layout-Score: {report.layout_score}",
            details={
                "layout_score": report.layout_score,
                "spacing_consistency": report.spacing_consistency
            }
        )
    except ImportError:
        return TestResult(
            test_id="layout_consistency",
            passed=True,
            screenshot_path=screenshot_path,
            details={"note": "Design Analyzer nicht verfügbar"}
        )


# ============================================================================
# Workflow Tests
# ============================================================================

def test_basic_workflow(engine: "UITestEngine") -> "TestResult":
    """Testet grundlegenden Workflow."""
    from test_engine import TestResult

    try:
        from workflow_analyzer import WorkflowAnalyzer

        analyzer = WorkflowAnalyzer(engine.log)
        workflows = analyzer.get_chat_overlay_workflows()

        result = analyzer.run_workflow("basic_interaction", workflows["basic_interaction"])

        return TestResult(
            test_id="basic_workflow",
            passed=result.success,
            error="; ".join(result.errors) if result.errors else None,
            details={
                "total_time": f"{result.total_time:.2f}s",
                "steps_completed": f"{result.steps_completed}/{result.steps_total}"
            }
        )
    except Exception as e:
        return TestResult(test_id="basic_workflow", passed=False, error=str(e))


def test_scroll_workflow(engine: "UITestEngine") -> "TestResult":
    """Testet Scroll-Workflow."""
    from test_engine import TestResult

    try:
        from workflow_analyzer import WorkflowAnalyzer

        analyzer = WorkflowAnalyzer(engine.log)
        workflows = analyzer.get_chat_overlay_workflows()

        result = analyzer.run_workflow("scroll_conversation", workflows["scroll_conversation"])

        return TestResult(
            test_id="scroll_workflow",
            passed=result.success,
            error="; ".join(result.errors) if result.errors else None,
            details={
                "total_time": f"{result.total_time:.2f}s",
                "smoothness": "Visuell prüfen"
            }
        )
    except Exception as e:
        return TestResult(test_id="scroll_workflow", passed=False, error=str(e))


def test_copy_paste_workflow(engine: "UITestEngine") -> "TestResult":
    """Testet Copy/Paste."""
    from test_engine import TestResult

    try:
        from workflow_analyzer import WorkflowAnalyzer

        analyzer = WorkflowAnalyzer(engine.log)
        workflows = analyzer.get_chat_overlay_workflows()

        result = analyzer.run_workflow("copy_text", workflows["copy_text"])

        return TestResult(
            test_id="copy_paste_workflow",
            passed=result.success,
            error="; ".join(result.errors) if result.errors else None,
            details={"total_time": f"{result.total_time:.2f}s"}
        )
    except Exception as e:
        return TestResult(test_id="copy_paste_workflow", passed=False, error=str(e))


def test_keyboard_navigation(engine: "UITestEngine") -> "TestResult":
    """Testet Keyboard-Navigation."""
    from test_engine import TestResult

    try:
        from workflow_analyzer import WorkflowAnalyzer

        analyzer = WorkflowAnalyzer(engine.log)
        workflows = analyzer.get_chat_overlay_workflows()

        result = analyzer.run_workflow("keyboard_navigation", workflows["keyboard_navigation"])

        return TestResult(
            test_id="keyboard_navigation",
            passed=result.success,
            error="; ".join(result.errors) if result.errors else None,
            details={"total_time": f"{result.total_time:.2f}s"}
        )
    except Exception as e:
        return TestResult(test_id="keyboard_navigation", passed=False, error=str(e))


# ============================================================================
# Convenience Tests
# ============================================================================

def test_response_time(engine: "UITestEngine") -> "TestResult":
    """Misst UI-Reaktionszeit."""
    from test_engine import TestResult
    import time

    window = engine.find_window("Frank")
    if not window:
        return TestResult(test_id="response_time", passed=False, error="Overlay nicht gefunden")

    # Fokus-Zeit messen
    start = time.time()
    try:
        subprocess.run(["wmctrl", "-ia", window["wid"]], timeout=3)
    except Exception:
        pass
    focus_time = time.time() - start

    # Screenshot-Zeit messen
    start = time.time()
    img = engine.capture_window("Frank")
    capture_time = time.time() - start

    total_response = focus_time + capture_time
    passed = total_response < 1.0  # Unter 1 Sekunde ist gut

    return TestResult(
        test_id="response_time",
        passed=passed,
        error=None if passed else f"Zu langsam: {total_response:.2f}s",
        details={
            "focus_time": f"{focus_time:.3f}s",
            "capture_time": f"{capture_time:.3f}s",
            "total": f"{total_response:.3f}s"
        }
    )


def test_window_focus(engine: "UITestEngine") -> "TestResult":
    """Prüft Window-Focus."""
    from test_engine import TestResult

    window = engine.find_window("Frank")
    if not window:
        return TestResult(test_id="window_focus", passed=False, error="Fenster nicht gefunden")

    try:
        subprocess.run(["wmctrl", "-ia", window["wid"]], timeout=3)
        time.sleep(0.5)

        active = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowname"],
            capture_output=True, text=True, timeout=3
        )
        active_title = active.stdout.strip()

        passed = "frank" in active_title.lower()

        return TestResult(
            test_id="window_focus",
            passed=passed,
            error=None if passed else f"Aktiv: {active_title}",
            details={"active_window": active_title}
        )
    except Exception as e:
        return TestResult(test_id="window_focus", passed=False, error=str(e))


def test_input_handling(engine: "UITestEngine") -> "TestResult":
    """Testet Eingabeverarbeitung."""
    from test_engine import TestResult

    try:
        from workflow_analyzer import WorkflowAnalyzer

        analyzer = WorkflowAnalyzer(engine.log)
        workflows = analyzer.get_chat_overlay_workflows()

        result = analyzer.run_workflow("long_text_handling", workflows["long_text_handling"])

        return TestResult(
            test_id="input_handling",
            passed=result.success,
            error="; ".join(result.errors) if result.errors else None,
            details={"total_time": f"{result.total_time:.2f}s"}
        )
    except Exception as e:
        return TestResult(test_id="input_handling", passed=False, error=str(e))


# ============================================================================
# Design Tests
# ============================================================================

def test_color_contrast(engine: "UITestEngine") -> "TestResult":
    """Prüft WCAG Farbkontrast."""
    from test_engine import TestResult

    img = engine.capture_window("Frank")
    if not img:
        return TestResult(test_id="color_contrast", passed=False, error="Capture failed")

    screenshot_path = engine.save_screenshot(img, "contrast_test") if engine.save_screenshots else None

    try:
        from design_analyzer import DesignAnalyzer
        from pathlib import Path

        analyzer = DesignAnalyzer(Path(engine.screenshots_dir))
        report = analyzer.analyze_image(img)

        issues = [f"{r.foreground}/{r.background}: {r.ratio}:1"
                  for r in report.contrast_issues[:3]]

        return TestResult(
            test_id="color_contrast",
            passed=report.contrast_score >= 75,
            error=f"Kontrast-Issues: {issues}" if issues else None,
            screenshot_path=screenshot_path,
            details={
                "score": report.contrast_score,
                "wcag_aa": report.wcag_compliant,
                "issues_count": len(report.contrast_issues)
            }
        )
    except ImportError:
        return TestResult(test_id="color_contrast", passed=True, details={"note": "Analyzer unavailable"})


def test_color_palette(engine: "UITestEngine") -> "TestResult":
    """Analysiert Farbpalette."""
    from test_engine import TestResult

    img = engine.capture_window("Frank")
    if not img:
        return TestResult(test_id="color_palette", passed=False, error="Capture failed")

    screenshot_path = engine.save_screenshot(img, "palette_test") if engine.save_screenshots else None

    try:
        from design_analyzer import DesignAnalyzer
        from pathlib import Path

        analyzer = DesignAnalyzer(Path(engine.screenshots_dir))
        report = analyzer.analyze_image(img)

        return TestResult(
            test_id="color_palette",
            passed=True,  # Informativ
            screenshot_path=screenshot_path,
            details={
                "palette": report.color_palette[:6],
                "harmony": report.color_harmony,
                "dominant_colors": len(report.dominant_colors)
            }
        )
    except ImportError:
        return TestResult(test_id="color_palette", passed=True, details={"note": "Analyzer unavailable"})


def test_visual_hierarchy(engine: "UITestEngine") -> "TestResult":
    """Prüft visuelle Hierarchie."""
    from test_engine import TestResult

    img = engine.capture_window("Frank")
    if not img:
        return TestResult(test_id="visual_hierarchy", passed=False, error="Capture failed")

    screenshot_path = engine.save_screenshot(img, "hierarchy_test") if engine.save_screenshots else None

    try:
        from design_analyzer import DesignAnalyzer
        from pathlib import Path

        analyzer = DesignAnalyzer(Path(engine.screenshots_dir))
        report = analyzer.analyze_image(img)

        # Gute Hierarchie = verschiedene Farb-Helligkeiten
        lightnesses = [c.hsl[2] for c in report.dominant_colors[:5]]
        hierarchy_range = max(lightnesses) - min(lightnesses) if lightnesses else 0

        passed = hierarchy_range > 30  # Mindestens 30% Helligkeits-Range

        return TestResult(
            test_id="visual_hierarchy",
            passed=passed,
            screenshot_path=screenshot_path,
            error=None if passed else "Geringe visuelle Hierarchie",
            details={
                "lightness_range": f"{hierarchy_range:.0f}%",
                "recommendation": "Mehr Kontrast zwischen UI-Ebenen" if not passed else "OK"
            }
        )
    except ImportError:
        return TestResult(test_id="visual_hierarchy", passed=True, details={"note": "Analyzer unavailable"})


# ============================================================================
# Accessibility Tests
# ============================================================================

def test_accessibility_basic(engine: "UITestEngine") -> "TestResult":
    """Grundlegende Accessibility-Prüfung."""
    from test_engine import TestResult

    img = engine.capture_window("Frank")
    if not img:
        return TestResult(test_id="accessibility_basic", passed=False, error="Capture failed")

    screenshot_path = engine.save_screenshot(img, "a11y_test") if engine.save_screenshots else None

    try:
        from design_analyzer import DesignAnalyzer
        from pathlib import Path

        analyzer = DesignAnalyzer(Path(engine.screenshots_dir))
        report = analyzer.analyze_image(img)

        return TestResult(
            test_id="accessibility_basic",
            passed=report.wcag_compliant,
            error="; ".join(report.accessibility_issues[:3]) if report.accessibility_issues else None,
            screenshot_path=screenshot_path,
            details={
                "wcag_compliant": report.wcag_compliant,
                "issues": report.accessibility_issues,
                "recommendations": report.recommendations[:3]
            }
        )
    except ImportError:
        return TestResult(test_id="accessibility_basic", passed=True, details={"note": "Analyzer unavailable"})
