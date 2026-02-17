#!/usr/bin/env python3
"""
Test Executor - Autonomous UI testing with Claude.

Orchestrates the testing process, using Claude to decide actions
and analyze results.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .claude_client import ClaudeClient
from .overlay_controller import OverlayController

LOG = logging.getLogger("ui_tester.executor")

# Results directory
try:
    from config.paths import UI_DIR as _UI_DIR
except ImportError:
    _UI_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = _UI_DIR / "ui_tester" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class TestResult:
    """Results from a test session."""
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_minutes: int = 5
    actions_performed: List[Dict[str, Any]] = field(default_factory=list)
    issues_found: List[str] = field(default_factory=list)
    observations: List[str] = field(default_factory=list)
    screenshots: List[Path] = field(default_factory=list)
    design_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_minutes": self.duration_minutes,
            "actions_count": len(self.actions_performed),
            "issues_count": len(self.issues_found),
            "issues": self.issues_found,
            "observations": self.observations,
            "screenshots": [str(p) for p in self.screenshots],
            "design_notes": self.design_notes,
        }


class TestExecutor:
    """Executes autonomous UI tests using Claude."""

    def __init__(self, duration_minutes: int = 5, progress_callback=None):
        self.duration_minutes = duration_minutes
        self.progress_callback = progress_callback
        self.claude = ClaudeClient()
        self.controller = OverlayController()
        self.result = TestResult(
            start_time=datetime.now(),
            duration_minutes=duration_minutes
        )
        self._running = False
        self._stop_requested = False

    def _report_progress(self, message: str, progress: float):
        """Report progress to callback if set."""
        LOG.info(f"[{progress:.0%}] {message}")
        if self.progress_callback:
            self.progress_callback(message, progress)

    def _ensure_overlay_running(self) -> bool:
        """Ensure chat_overlay is running and visible. Start it if needed."""
        import subprocess
        import os

        self._report_progress("Prüfe Chat-Overlay...", 0.02)

        # Check if chat_overlay is running
        try:
            result = subprocess.run(
                ["pgrep", "-f", "chat_overlay.py"],
                capture_output=True,
                text=True,
                timeout=5
            )
            is_running = bool(result.stdout.strip())
        except Exception:
            is_running = False

        if not is_running:
            # Start chat_overlay
            self._report_progress("Starte Chat-Overlay...", 0.03)
            try:
                overlay_path = _UI_DIR / "chat_overlay.py"
                if overlay_path.exists():
                    subprocess.Popen(
                        ["python3", str(overlay_path)],
                        env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    # Wait for it to start
                    time.sleep(3)
                    self._report_progress("Chat-Overlay gestartet!", 0.04)
                else:
                    self._report_progress("chat_overlay.py nicht gefunden!", 0.04)
                    return False
            except Exception as e:
                LOG.error(f"Failed to start overlay: {e}")
                return False
        else:
            self._report_progress("Chat-Overlay läuft bereits", 0.03)

        # Bring to front / unminimize using wmctrl
        try:
            # Find the overlay window
            result = subprocess.run(
                ["wmctrl", "-l"],
                capture_output=True,
                text=True,
                timeout=5
            )
            for line in result.stdout.strip().split("\n"):
                if any(x in line.lower() for x in ["frank", "chat", "overlay"]):
                    window_id = line.split()[0]
                    # Activate (unminimize + focus)
                    subprocess.run(
                        ["wmctrl", "-i", "-a", window_id],
                        timeout=5
                    )
                    self._report_progress("Chat-Overlay aktiviert!", 0.04)
                    time.sleep(0.5)
                    break
        except Exception as e:
            LOG.debug(f"wmctrl not available or failed: {e}")

        return True

    def run(self) -> TestResult:
        """Run the autonomous test session."""
        self._running = True
        self._stop_requested = False
        start_time = time.time()
        end_time = start_time + (self.duration_minutes * 60)

        self._report_progress("Test gestartet...", 0.0)

        # BULLETPROOF: Ensure overlay is running and visible
        if not self._ensure_overlay_running():
            self.result.issues_found.append("Chat-Overlay konnte nicht gestartet werden!")
            self._report_progress("FEHLER: Overlay Start fehlgeschlagen", 1.0)
            self.result.end_time = datetime.now()
            return self.result

        # Initial screenshot and analysis
        self._report_progress("Initiale Analyse...", 0.05)
        screenshot = self.controller.take_screenshot("initial")
        self.result.screenshots.append(screenshot)

        # Focus the overlay
        if not self.controller.focus_overlay():
            self.result.issues_found.append("Overlay-Fenster nicht gefunden!")
            self._report_progress("FEHLER: Overlay nicht gefunden", 1.0)
            self.result.end_time = datetime.now()
            return self.result

        action_count = 0
        previous_actions = []

        while time.time() < end_time and not self._stop_requested:
            remaining = end_time - time.time()
            progress = 1.0 - (remaining / (self.duration_minutes * 60))

            self._report_progress(
                f"Aktion {action_count + 1} - {remaining/60:.1f} min übrig",
                progress
            )

            # Take screenshot
            screenshot = self.controller.take_screenshot(f"action_{action_count}")
            self.result.screenshots.append(screenshot)

            # Ask Claude for next action
            test_context = {
                "remaining_time": f"{remaining/60:.1f} Minuten",
                "actions_so_far": action_count,
                "issues_found": len(self.result.issues_found),
            }

            action = self.claude.get_test_action(
                screenshot,
                test_context,
                previous_actions
            )

            # Record action
            action["timestamp"] = datetime.now().isoformat()
            self.result.actions_performed.append(action)
            previous_actions.append(f"{action['action']}: {action.get('reason', '')[:50]}")

            # Record observations and issues
            if "observations" in action:
                self.result.observations.extend(action["observations"])
            if "issues_found" in action:
                self.result.issues_found.extend(action["issues_found"])

            # Execute action
            self._execute_action(action)

            action_count += 1

            # Brief pause between actions
            time.sleep(0.5)

            # Check if Claude says we're done
            if action.get("action") == "done":
                self._report_progress("Test abgeschlossen (Claude)", progress)
                break

        # Final screenshot
        final_screenshot = self.controller.take_screenshot("final")
        self.result.screenshots.append(final_screenshot)

        self.result.end_time = datetime.now()
        self._running = False

        # Save results
        self._save_results()

        self._report_progress("Test beendet!", 1.0)
        return self.result

    def _execute_action(self, action: Dict[str, Any]) -> bool:
        """Execute a test action."""
        action_type = action.get("action", "")
        params = action.get("params", {})

        try:
            if action_type == "type":
                text = params.get("text", "Test")
                self.controller.type_text(text)
                time.sleep(0.3)
                self.controller.press_key("enter")
                time.sleep(1.5)  # Wait for response

            elif action_type == "click":
                x = params.get("x", 0)
                y = params.get("y", 0)
                self.controller.click(x, y)

            elif action_type == "drag":
                self.controller.drag(
                    params.get("from_x", 0),
                    params.get("from_y", 0),
                    params.get("to_x", 100),
                    params.get("to_y", 100)
                )

            elif action_type == "resize":
                edge = params.get("edge", "corner")
                delta_x = params.get("delta_x", 50)
                delta_y = params.get("delta_y", 50)
                self.controller.resize_overlay(edge, delta_x, delta_y)

            elif action_type == "scroll":
                direction = params.get("direction", "down")
                amount = params.get("amount", 3)
                self.controller.scroll(direction, amount)

            elif action_type == "screenshot":
                # Already taken above
                pass

            elif action_type == "ingest":
                file_type = params.get("file_type", "text")
                test_file = self.controller.create_test_file(file_type)
                self.controller.ingest_file(test_file)
                time.sleep(2)  # Wait for processing

            elif action_type == "wait":
                seconds = params.get("seconds", 2)
                time.sleep(seconds)

            elif action_type == "done":
                pass

            else:
                LOG.warning(f"Unknown action type: {action_type}")
                return False

            return True

        except Exception as e:
            LOG.error(f"Action failed: {e}")
            self.result.issues_found.append(f"Aktion fehlgeschlagen: {action_type} - {e}")
            return False

    def _save_results(self):
        """Save test results to file."""
        timestamp = self.result.start_time.strftime("%Y%m%d_%H%M%S")
        results_file = RESULTS_DIR / f"test_results_{timestamp}.json"

        with open(results_file, "w", encoding="utf-8") as f:
            json.dump(self.result.to_dict(), f, indent=2, ensure_ascii=False)

        LOG.info(f"Results saved to: {results_file}")

    def stop(self):
        """Request test stop."""
        self._stop_requested = True

    def is_running(self) -> bool:
        """Check if test is running."""
        return self._running


def get_latest_results() -> Optional[TestResult]:
    """Load the most recent test results."""
    results_files = sorted(RESULTS_DIR.glob("test_results_*.json"), reverse=True)
    if not results_files:
        return None

    with open(results_files[0], "r", encoding="utf-8") as f:
        data = json.load(f)

    result = TestResult(
        start_time=datetime.fromisoformat(data["start_time"]),
        end_time=datetime.fromisoformat(data["end_time"]) if data.get("end_time") else None,
        duration_minutes=data.get("duration_minutes", 5),
        issues_found=data.get("issues", []),
        observations=data.get("observations", []),
        screenshots=[Path(p) for p in data.get("screenshots", [])],
    )
    return result


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    def progress(msg, pct):
        print(f"[{pct:.0%}] {msg}")

    print("=== Test Executor Demo ===")
    print("Starting 1-minute test...")

    executor = TestExecutor(duration_minutes=1, progress_callback=progress)
    result = executor.run()

    print(f"\nResults:")
    print(f"  Actions: {len(result.actions_performed)}")
    print(f"  Issues: {len(result.issues_found)}")
    print(f"  Screenshots: {len(result.screenshots)}")

    for issue in result.issues_found:
        print(f"  - {issue}")
