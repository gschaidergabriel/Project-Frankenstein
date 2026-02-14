#!/usr/bin/env python3
"""
Workflow Analyzer
=================
Analysiert Benutzer-Workflows und UX-Metriken.
"""

import time
import subprocess
import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime
from pathlib import Path

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# ESC-Listener für Notfall-Stopp
try:
    from pynput import keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False

# Globaler Stop-Flag
_EMERGENCY_STOP = False

def _on_key_press(key):
    """Callback für Tastendruck - ESC stoppt alles."""
    global _EMERGENCY_STOP
    try:
        if key == keyboard.Key.esc:
            _EMERGENCY_STOP = True
            print("\n⚠️  ESC gedrückt - NOTFALL-STOPP!")
            return False  # Listener beenden
    except:
        pass

def reset_emergency_stop():
    """Setzt den Stop-Flag zurück."""
    global _EMERGENCY_STOP
    _EMERGENCY_STOP = False

def is_emergency_stop():
    """Prüft ob Notfall-Stopp aktiv ist."""
    return _EMERGENCY_STOP


@dataclass
class WorkflowStep:
    """Ein Schritt im Workflow."""
    name: str
    action: str  # "click", "type", "key", "wait", "check"
    target: Any = None
    expected_result: str = ""
    timeout: float = 5.0


@dataclass
class WorkflowResult:
    """Ergebnis eines Workflow-Durchlaufs."""
    workflow_name: str
    success: bool
    total_time: float
    steps_completed: int
    steps_total: int
    step_times: List[float] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    # FIX: Lambda verwenden damit datetime.now() bei jeder Instanz aufgerufen wird
    timestamp: datetime = field(default_factory=lambda: datetime.now())


@dataclass
class UXMetrics:
    """UX-Metriken."""
    response_time_avg: float = 0.0
    response_time_p95: float = 0.0
    task_completion_rate: float = 0.0
    error_rate: float = 0.0
    interaction_smoothness: float = 0.0  # 0-100
    workflow_efficiency: float = 0.0     # 0-100


class WorkflowAnalyzer:
    """Analysiert Benutzer-Workflows."""

    def __init__(self, log_callback: Optional[Callable] = None):
        self.log_callback = log_callback or print
        self.results: List[WorkflowResult] = []
        self.metrics_history: List[UXMetrics] = []

    def log(self, msg: str, level: str = "INFO"):
        """Logging."""
        if self.log_callback:
            self.log_callback(msg, level)

    def find_window(self, title_pattern: str) -> Optional[Dict]:
        """Findet Fenster."""
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
                            "wid": wid, "x": int(x), "y": int(y),
                            "w": int(w), "h": int(h), "title": title
                        }
        except Exception as e:
            # FIX: Spezifische Exception statt bare except
            self.log(f"Window search failed: {e}", "WARN")
        return None

    def focus_window(self, wid: str) -> bool:
        """Fokussiert Fenster."""
        try:
            subprocess.run(["wmctrl", "-ia", wid], timeout=3)
            time.sleep(0.3)
            return True
        except Exception as e:
            # FIX: Spezifische Exception statt bare except
            self.log(f"Focus failed: {e}", "WARN")
            return False

    def verify_frank_is_active(self) -> bool:
        """
        SICHERHEIT: Prüft ob Frank WIRKLICH das aktive Fenster ist.
        Verhindert Tippen in falsche Fenster (Terminal, LibreOffice, etc.)
        """
        try:
            result = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowname"],
                capture_output=True, text=True, timeout=3
            )
            active_title = result.stdout.strip().lower()

            # Nur wenn "frank" im Titel ist, ist es sicher
            is_frank = "frank" in active_title

            if not is_frank:
                self.log(f"SICHERHEIT: Aktives Fenster ist '{active_title}' - NICHT Frank!", "WARN")

            return is_frank
        except Exception as e:
            self.log(f"Konnte aktives Fenster nicht prüfen: {e}", "WARN")
            return False  # Im Zweifel: NICHT tippen

    def execute_step(self, step: WorkflowStep, window_focused: bool = False) -> tuple:
        """
        Führt einen Workflow-Schritt aus.
        Returns: (success, time_taken, error_msg)
        """
        start = time.time()
        error = None

        try:
            if step.action == "click":
                # SICHERHEIT: Nur klicken wenn Frank aktiv (außer beim ersten Focus-Versuch)
                if window_focused and not self.verify_frank_is_active():
                    error = "SICHERHEIT: Frank ist nicht aktiv - Klick abgebrochen"
                elif PYAUTOGUI_AVAILABLE and step.target:
                    x, y = step.target
                    pyautogui.click(x, y)
                    time.sleep(0.2)

            elif step.action == "type":
                # SICHERHEIT: Doppelte Prüfung vor dem Tippen!
                # 1. War focus erfolgreich?
                # 2. Ist Frank WIRKLICH das aktive Fenster? (verhindert Tippen in LibreOffice, Terminal, etc.)
                if not window_focused:
                    error = "Abbruch: Fenster wurde nicht fokussiert"
                elif not self.verify_frank_is_active():
                    error = "SICHERHEIT: Frank ist nicht das aktive Fenster - Tippen abgebrochen"
                elif PYAUTOGUI_AVAILABLE and step.target:
                    pyautogui.write(step.target, interval=0.02)
                    time.sleep(0.1)

            elif step.action == "key":
                # SICHERHEIT: Auch Tasten nur wenn Frank aktiv ist!
                # (Ctrl+A in LibreOffice würde alles markieren, etc.)
                if not self.verify_frank_is_active():
                    error = "SICHERHEIT: Frank ist nicht aktiv - Tastendruck abgebrochen"
                elif PYAUTOGUI_AVAILABLE and step.target:
                    if isinstance(step.target, (list, tuple)):
                        pyautogui.hotkey(*step.target)
                    else:
                        pyautogui.press(step.target)
                    time.sleep(0.1)

            elif step.action == "wait":
                time.sleep(step.target if step.target else 1.0)

            elif step.action == "check":
                # Prüft ob Bedingung erfüllt
                if callable(step.target):
                    if not step.target():
                        error = f"Check failed: {step.expected_result}"

            elif step.action == "focus":
                window = self.find_window(step.target)
                if window:
                    self.focus_window(window["wid"])
                else:
                    error = f"Window not found: {step.target}"

            elif step.action == "api":
                # API-Aufruf (z.B. Nachricht senden)
                if REQUESTS_AVAILABLE and step.target:
                    url, payload = step.target
                    requests.post(url, json=payload, timeout=5)

        except Exception as e:
            error = str(e)

        elapsed = time.time() - start
        return error is None, elapsed, error

    def run_workflow(self, name: str, steps: List[WorkflowStep]) -> WorkflowResult:
        """Führt kompletten Workflow aus."""
        global _EMERGENCY_STOP

        result = WorkflowResult(
            workflow_name=name,
            success=True,
            total_time=0,
            steps_completed=0,
            steps_total=len(steps)
        )

        start_time = time.time()
        window_focused = False  # Track ob wir erfolgreich fokussiert haben

        # ESC-Listener starten
        esc_listener = None
        if PYNPUT_AVAILABLE:
            reset_emergency_stop()
            esc_listener = keyboard.Listener(on_press=_on_key_press)
            esc_listener.start()
            self.log("  [ESC drücken zum Abbrechen]", "INFO")

        try:
            for i, step in enumerate(steps):
                # NOTFALL-STOPP prüfen
                if is_emergency_stop():
                    self.log("  ⚠️ NOTFALL-STOPP durch ESC!", "WARN")
                    result.success = False
                    result.errors.append("Abgebrochen durch Benutzer (ESC)")
                    break

                self.log(f"  Step {i+1}/{len(steps)}: {step.name}")

                # Bei focus-Schritt: Status merken
                if step.action == "focus":
                    window = self.find_window(step.target)
                    if window:
                        window_focused = self.focus_window(window["wid"])
                    else:
                        window_focused = False

                success, elapsed, error = self.execute_step(step, window_focused)
                result.step_times.append(elapsed)

                if success:
                    result.steps_completed += 1
                else:
                    result.success = False
                    result.errors.append(f"Step {i+1} ({step.name}): {error}")
                    self.log(f"    ✗ Failed: {error}", "ERROR")

                    # Bei Fehler abbrechen oder weitermachen?
                    if step.timeout == 0:  # Critical step
                        break

        finally:
            # ESC-Listener immer stoppen
            if esc_listener:
                esc_listener.stop()
                reset_emergency_stop()

        result.total_time = time.time() - start_time
        self.results.append(result)

        return result

    def calculate_metrics(self) -> UXMetrics:
        """Berechnet UX-Metriken aus bisherigen Ergebnissen."""
        if not self.results:
            return UXMetrics()

        all_times = []
        for r in self.results:
            all_times.extend(r.step_times)

        completed = sum(r.steps_completed for r in self.results)
        total = sum(r.steps_total for r in self.results)
        errors = sum(len(r.errors) for r in self.results)

        metrics = UXMetrics(
            response_time_avg=statistics.mean(all_times) if all_times else 0,
            response_time_p95=sorted(all_times)[min(int(len(all_times) * 0.95), len(all_times) - 1)] if len(all_times) > 1 else 0,
            task_completion_rate=(completed / total * 100) if total > 0 else 0,
            error_rate=(errors / total * 100) if total > 0 else 0,
            interaction_smoothness=self._calculate_smoothness(),
            workflow_efficiency=self._calculate_efficiency()
        )

        self.metrics_history.append(metrics)
        return metrics

    def _calculate_smoothness(self) -> float:
        """Berechnet wie flüssig die Interaktionen sind."""
        if not self.results:
            return 100.0

        # Basiert auf Varianz der Schritt-Zeiten
        all_times = []
        for r in self.results:
            all_times.extend(r.step_times)

        if len(all_times) < 2:
            return 100.0

        variance = statistics.variance(all_times)
        # Niedrige Varianz = hohe Smoothness
        smoothness = max(0, 100 - (variance * 100))
        return min(100, smoothness)

    def _calculate_efficiency(self) -> float:
        """Berechnet Workflow-Effizienz."""
        if not self.results:
            return 100.0

        # Erfolgreiche Workflows / Gesamte Workflows
        successful = sum(1 for r in self.results if r.success)
        efficiency = (successful / len(self.results)) * 100

        # Bonus für schnelle Completion
        avg_time = statistics.mean(r.total_time for r in self.results)
        if avg_time < 2.0:
            efficiency = min(100, efficiency + 10)

        return efficiency

    # =========================================================================
    # Vordefinierte Workflows für Chat Overlay
    # =========================================================================

    def get_chat_overlay_workflows(self) -> Dict[str, List[WorkflowStep]]:
        """Gibt vordefinierte Chat Overlay Workflows zurück."""

        window = self.find_window("Frank")
        if window:
            center_x = window["x"] + window["w"] // 2
            center_y = window["y"] + window["h"] // 2
            input_y = window["y"] + window["h"] - 50
        else:
            center_x, center_y = 960, 540
            input_y = 1000

        return {
            "basic_interaction": [
                WorkflowStep("Focus Overlay", "focus", "Frank"),
                WorkflowStep("Wait for Focus", "wait", 0.5),
                WorkflowStep("Click Center", "click", (center_x, center_y)),
                WorkflowStep("Verify Active", "check", lambda: self.find_window("Frank") is not None),
            ],

            "send_message": [
                WorkflowStep("Focus Overlay", "focus", "Frank"),
                WorkflowStep("Click Input", "click", (center_x, input_y)),
                WorkflowStep("Type Message", "type", "[UI-Test] Hallo Frank, dies ist ein automatischer Test."),
                WorkflowStep("Send", "key", "return"),
                WorkflowStep("Wait Response", "wait", 2.0),
            ],

            "scroll_conversation": [
                WorkflowStep("Focus Overlay", "focus", "Frank"),
                WorkflowStep("Click Content", "click", (center_x, center_y)),
                WorkflowStep("Scroll Up", "key", "pageup"),
                WorkflowStep("Wait", "wait", 0.3),
                WorkflowStep("Scroll Down", "key", "pagedown"),
                WorkflowStep("Wait", "wait", 0.3),
                WorkflowStep("Scroll Down", "key", "pagedown"),
            ],

            "copy_text": [
                WorkflowStep("Focus Overlay", "focus", "Frank"),
                WorkflowStep("Click Text", "click", (center_x, center_y)),
                WorkflowStep("Select All", "key", ("ctrl", "a")),
                WorkflowStep("Copy", "key", ("ctrl", "c")),
                WorkflowStep("Wait", "wait", 0.3),
            ],

            "keyboard_navigation": [
                WorkflowStep("Focus Overlay", "focus", "Frank"),
                WorkflowStep("Tab", "key", "tab"),
                WorkflowStep("Wait", "wait", 0.2),
                WorkflowStep("Tab", "key", "tab"),
                WorkflowStep("Wait", "wait", 0.2),
                WorkflowStep("Shift+Tab", "key", ("shift", "tab")),
                WorkflowStep("Wait", "wait", 0.2),
                WorkflowStep("Escape", "key", "escape"),
            ],

            "window_management": [
                WorkflowStep("Focus Overlay", "focus", "Frank"),
                WorkflowStep("Wait", "wait", 0.5),
                WorkflowStep("Verify Visible", "check", lambda: self.find_window("Frank") is not None),
            ],

            "rapid_interaction": [
                WorkflowStep("Focus", "focus", "Frank"),
                WorkflowStep("Click 1", "click", (center_x, center_y - 50)),
                WorkflowStep("Click 2", "click", (center_x, center_y)),
                WorkflowStep("Click 3", "click", (center_x, center_y + 50)),
                WorkflowStep("Key 1", "key", "up"),
                WorkflowStep("Key 2", "key", "down"),
                WorkflowStep("Key 3", "key", "up"),
            ],

            "long_text_handling": [
                WorkflowStep("Focus", "focus", "Frank"),
                WorkflowStep("Click Input", "click", (center_x, input_y)),
                WorkflowStep("Type Long", "type", "[UI-Test] Dies ist ein laengerer Testtext um die Eingabe zu pruefen."),
                WorkflowStep("Wait", "wait", 0.5),
                WorkflowStep("Clear", "key", ("ctrl", "a")),
                WorkflowStep("Delete", "key", "delete"),
            ],
        }

    def run_all_workflows(self) -> Dict[str, WorkflowResult]:
        """Führt alle vordefinierten Workflows aus."""
        workflows = self.get_chat_overlay_workflows()
        results = {}

        for name, steps in workflows.items():
            self.log(f"Running workflow: {name}")
            result = self.run_workflow(name, steps)
            results[name] = result

            if result.success:
                self.log(f"  ✓ Completed in {result.total_time:.2f}s", "OK")
            else:
                self.log(f"  ✗ Failed: {result.errors}", "ERROR")

            time.sleep(0.5)  # Pause zwischen Workflows

        return results

    def generate_report(self) -> Dict:
        """Generiert Workflow-Report."""
        metrics = self.calculate_metrics()

        return {
            "timestamp": datetime.now().isoformat(),
            "total_workflows": len(self.results),
            "successful": sum(1 for r in self.results if r.success),
            "failed": sum(1 for r in self.results if not r.success),
            "metrics": {
                "response_time_avg": f"{metrics.response_time_avg:.3f}s",
                "response_time_p95": f"{metrics.response_time_p95:.3f}s",
                "task_completion_rate": f"{metrics.task_completion_rate:.1f}%",
                "error_rate": f"{metrics.error_rate:.1f}%",
                "interaction_smoothness": f"{metrics.interaction_smoothness:.1f}/100",
                "workflow_efficiency": f"{metrics.workflow_efficiency:.1f}/100"
            },
            "workflows": [
                {
                    "name": r.workflow_name,
                    "success": r.success,
                    "time": f"{r.total_time:.2f}s",
                    "steps": f"{r.steps_completed}/{r.steps_total}",
                    "errors": r.errors
                }
                for r in self.results
            ]
        }
