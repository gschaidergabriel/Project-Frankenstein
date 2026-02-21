#!/usr/bin/env python3
"""
Frank AI - Intelligenter UI-Tester
==================================
Verwendet Ollama (llava) als "Gehirn" um die UI wie ein Mensch zu testen.
Lokal, kostenlos, keine API-Keys nötig.
"""

import base64
import json
import os
import re
import subprocess
import time
import requests
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Optional, Dict, List

try:
    from PIL import Image
    import mss
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pyautogui
    pyautogui.FAILSAFE = True  # Ecke = Notfall-Stopp
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

try:
    from pynput import keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False


# Konfiguration
BASE_DIR = Path(__file__).parent
REPORTS_DIR = BASE_DIR / "reports"
SCREENSHOTS_DIR = BASE_DIR / "screenshots" / "ai_test"
OLLAMA_URL = "http://localhost:11434"

# Notfall-Stopp
_EMERGENCY_STOP = False


def _on_esc(key):
    """ESC = Notfall-Stopp"""
    global _EMERGENCY_STOP
    try:
        if key == keyboard.Key.esc:
            _EMERGENCY_STOP = True
            print("\n⚠️  ESC - NOTFALL-STOPP!")
            return False
    except Exception:
        pass


class AITester:
    """
    Intelligenter UI-Tester mit Ollama/llava als Gehirn.
    Lokal, kostenlos, keine Cloud.
    """

    SYSTEM_PROMPT = """Du bist ein UI-Tester der die Frank AI Chat-Anwendung testet.

DEINE AUFGABE:
- Teste die UI wie ein echter Mensch
- Stelle Frank echte Fragen und bewerte die Antworten
- Finde Bugs und UX-Probleme

WAS DU TUN KANNST - Antworte mit JSON:
{
    "action": "type" | "key" | "scroll" | "wait" | "done",
    "params": {
        "text": "Nachricht zum Tippen",
        "key": "return",
        "direction": "down",
        "seconds": 2
    },
    "observation": "Was du siehst",
    "finding": "Bug oder Problem (oder null)"
}

AKTIONEN:
- type: Text tippen (params.text)
- key: Taste drücken (params.key = return, tab, escape, up, down)
- scroll: Scrollen (params.direction = up/down)
- wait: Warten (params.seconds)
- done: Test beenden

REGELN:
1. Stelle Frank Fragen auf DEUTSCH
2. Nach type immer key mit return um zu senden
3. Nach dem Senden: wait mit 3 Sekunden
4. Prüfe ob Antworten sinnvoll sind
5. Nach 10-15 Aktionen: done

TESTIDEEN:
- "Hallo Frank, wie geht es dir?"
- "Was ist 25 mal 17?" (Antwort sollte 425 sein)
- "Erzähl einen kurzen Witz"
- "Was siehst du auf meinem Bildschirm?"

Antworte NUR mit dem JSON, kein anderer Text!"""

    def __init__(self, model: str = "llava", max_iterations: int = 20):
        """
        Args:
            model: Ollama Modell (llava empfohlen)
            max_iterations: Maximale Anzahl Aktionen
        """
        if not PIL_AVAILABLE:
            raise ImportError("PIL nicht installiert: pip install Pillow mss")
        if not PYAUTOGUI_AVAILABLE:
            raise ImportError("pyautogui nicht installiert: pip install pyautogui")

        self.model = model
        self.max_iterations = max_iterations
        self.iteration = 0
        self.findings: List[Dict] = []
        self.actions_log: List[Dict] = []
        self.frank_window: Optional[Dict] = None

        # Verzeichnisse erstellen
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

        # Ollama prüfen
        if not self._check_ollama():
            raise ConnectionError("Ollama nicht erreichbar! Läuft der Service?")

    def _check_ollama(self) -> bool:
        """Prüft ob Ollama läuft."""
        try:
            r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def log(self, msg: str, level: str = "INFO"):
        """Logging mit Farben."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        colors = {
            "INFO": "\033[94m",
            "OK": "\033[92m",
            "WARN": "\033[93m",
            "ERROR": "\033[91m",
            "AI": "\033[95m"
        }
        reset = "\033[0m"
        print(f"[{timestamp}] {colors.get(level, '')}{msg}{reset}")

    def find_frank_window(self) -> Optional[Dict]:
        """Findet das Frank-Fenster."""
        try:
            result = subprocess.run(
                ["wmctrl", "-lpG"],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.splitlines():
                parts = line.split(None, 8)
                if len(parts) >= 9:
                    wid, desk, pid, x, y, w, h, host, title = parts
                    if "frank" in title.lower():
                        return {
                            "wid": wid,
                            "x": int(x), "y": int(y),
                            "w": int(w), "h": int(h),
                            "title": title
                        }
        except Exception as e:
            self.log(f"Fenster-Suche fehlgeschlagen: {e}", "ERROR")
        return None

    def focus_frank(self) -> bool:
        """Fokussiert Frank-Fenster."""
        if not self.frank_window:
            self.frank_window = self.find_frank_window()

        if self.frank_window:
            try:
                subprocess.run(["wmctrl", "-ia", self.frank_window["wid"]], timeout=3)
                time.sleep(0.3)
                return True
            except Exception:
                pass
        return False

    def verify_frank_active(self) -> bool:
        """Prüft ob Frank wirklich aktiv ist."""
        try:
            result = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowname"],
                capture_output=True, text=True, timeout=3
            )
            return "frank" in result.stdout.strip().lower()
        except Exception:
            return False

    def take_screenshot(self) -> Optional[Image.Image]:
        """Macht Screenshot vom Frank-Fenster."""
        self.frank_window = self.find_frank_window()

        if not self.frank_window:
            self.log("Frank-Fenster nicht gefunden!", "ERROR")
            return None

        try:
            with mss.mss() as sct:
                region = {
                    "left": max(0, self.frank_window["x"]),
                    "top": max(0, self.frank_window["y"]),
                    "width": self.frank_window["w"],
                    "height": self.frank_window["h"]
                }
                screenshot = sct.grab(region)
                img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
                return img
        except Exception as e:
            self.log(f"Screenshot fehlgeschlagen: {e}", "ERROR")
            return None

    def image_to_base64(self, img: Image.Image) -> str:
        """Konvertiert Bild zu Base64."""
        buffer = BytesIO()
        # Resize für schnellere Verarbeitung
        max_size = 800
        if img.width > max_size or img.height > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    def click_input_area(self):
        """Klickt ins Eingabefeld (unten im Fenster)."""
        if not self.frank_window:
            return False

        # Eingabefeld ist typischerweise unten
        x = self.frank_window["x"] + self.frank_window["w"] // 2
        y = self.frank_window["y"] + self.frank_window["h"] - 40

        if self.verify_frank_active():
            pyautogui.click(x, y)
            time.sleep(0.2)
            return True
        return False

    def execute_action(self, action: str, params: Dict) -> bool:
        """Führt eine Aktion aus."""
        global _EMERGENCY_STOP

        if _EMERGENCY_STOP:
            self.log("NOTFALL-STOPP aktiv!", "ERROR")
            return False

        # Fokus sicherstellen
        if not self.focus_frank():
            self.log("Konnte Frank nicht fokussieren!", "ERROR")
            return False

        try:
            if action == "type":
                text = params.get("text", "")
                if text:
                    # Erst ins Eingabefeld klicken
                    self.click_input_area()
                    time.sleep(0.2)

                    # Sicherheitscheck
                    if not self.verify_frank_active():
                        self.log("SICHERHEIT: Frank nicht aktiv - abgebrochen!", "WARN")
                        return False

                    pyautogui.write(text, interval=0.02)
                    time.sleep(0.1)
                    self.log(f"Getippt: {text[:50]}{'...' if len(text) > 50 else ''}")

            elif action == "key":
                key = params.get("key", "return")
                if not self.verify_frank_active():
                    self.log("SICHERHEIT: Tastendruck abgebrochen!", "WARN")
                    return False
                pyautogui.press(key)
                time.sleep(0.1)
                self.log(f"Taste: {key}")

            elif action == "scroll":
                direction = params.get("direction", "down")
                amount = params.get("amount", 3)
                clicks = -amount if direction == "down" else amount
                center_x = self.frank_window["x"] + self.frank_window["w"] // 2
                center_y = self.frank_window["y"] + self.frank_window["h"] // 2
                pyautogui.moveTo(center_x, center_y)
                pyautogui.scroll(clicks)
                time.sleep(0.3)
                self.log(f"Scroll: {direction}")

            elif action == "wait":
                seconds = params.get("seconds", 2)
                self.log(f"Warte {seconds}s...")
                time.sleep(seconds)

            return True

        except Exception as e:
            self.log(f"Aktion fehlgeschlagen: {e}", "ERROR")
            return False

    def ask_ollama(self, screenshot: Image.Image) -> Dict:
        """Fragt Ollama was als nächstes zu tun ist."""

        img_b64 = self.image_to_base64(screenshot)

        prompt = f"""Iteration {self.iteration + 1}/{self.max_iterations}

Schau dir den Screenshot an und entscheide den nächsten Testschritt.
Antworte NUR mit einem JSON-Objekt!

{self.SYSTEM_PROMPT}"""

        try:
            response = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "images": [img_b64],
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "num_predict": 500
                    }
                },
                timeout=60
            )

            if response.status_code != 200:
                self.log(f"Ollama Fehler: {response.status_code}", "ERROR")
                return self._default_action()

            result = response.json()
            text = result.get("response", "")

            # JSON aus Antwort extrahieren
            return self._parse_response(text)

        except requests.exceptions.Timeout:
            self.log("Ollama Timeout!", "ERROR")
            return self._default_action()
        except Exception as e:
            self.log(f"Ollama Fehler: {e}", "ERROR")
            return self._default_action()

    def _parse_response(self, text: str) -> Dict:
        """Extrahiert JSON aus der Ollama-Antwort."""

        # Versuche JSON zu finden
        json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                # Validiere
                if "action" in data:
                    return data
            except json.JSONDecodeError:
                pass

        # Versuche Aktion aus Text zu erkennen
        text_lower = text.lower()

        if "done" in text_lower or "fertig" in text_lower or "beenden" in text_lower:
            return {"action": "done", "params": {}, "observation": text[:200]}

        if "type" in text_lower or "tippen" in text_lower or "schreib" in text_lower:
            # Versuche Text zu extrahieren
            match = re.search(r'["\']([^"\']+)["\']', text)
            if match:
                return {
                    "action": "type",
                    "params": {"text": match.group(1)},
                    "observation": text[:200]
                }

        if "return" in text_lower or "enter" in text_lower or "send" in text_lower:
            return {"action": "key", "params": {"key": "return"}, "observation": text[:200]}

        if "wait" in text_lower or "wart" in text_lower:
            return {"action": "wait", "params": {"seconds": 3}, "observation": text[:200]}

        if "scroll" in text_lower:
            direction = "up" if "up" in text_lower or "hoch" in text_lower else "down"
            return {"action": "scroll", "params": {"direction": direction}, "observation": text[:200]}

        # Fallback: Sinnvolle Testaktion
        return self._default_action()

    def _default_action(self) -> Dict:
        """Fallback-Aktion wenn Parsing fehlschlägt."""
        test_messages = [
            "Hallo Frank, wie geht es dir?",
            "Was ist 25 mal 17?",
            "Erzähl mir einen kurzen Witz.",
            "Welcher Tag ist heute?",
            "Was kannst du alles?",
        ]

        # Wähle basierend auf Iteration
        idx = self.iteration % len(test_messages)

        return {
            "action": "type",
            "params": {"text": test_messages[idx]},
            "observation": "Fallback-Testaktion",
            "finding": None
        }

    def run(self) -> Dict:
        """Führt den AI-gesteuerten Test durch."""
        global _EMERGENCY_STOP
        _EMERGENCY_STOP = False

        self.log("=" * 60)
        self.log("  FRANK AI - INTELLIGENTER UI-TEST")
        self.log(f"  Model: {self.model} (lokal via Ollama)")
        self.log("  [ESC zum Abbrechen]")
        self.log("=" * 60)

        # Frank finden
        self.frank_window = self.find_frank_window()
        if not self.frank_window:
            self.log("Frank-Fenster nicht gefunden! Ist Frank gestartet?", "ERROR")
            return {"error": "Frank nicht gefunden"}

        self.log(f"Frank gefunden: {self.frank_window['title']}", "OK")

        # ESC-Listener
        esc_listener = None
        if PYNPUT_AVAILABLE:
            esc_listener = keyboard.Listener(on_press=_on_esc)
            esc_listener.start()

        start_time = datetime.now()
        last_action = None

        try:
            while self.iteration < self.max_iterations and not _EMERGENCY_STOP:
                self.iteration += 1
                self.log(f"\n--- Iteration {self.iteration}/{self.max_iterations} ---")

                # Screenshot
                screenshot = self.take_screenshot()
                if not screenshot:
                    time.sleep(1)
                    continue

                # Screenshot speichern
                screenshot_path = SCREENSHOTS_DIR / f"step_{self.iteration:03d}.png"
                screenshot.save(screenshot_path)

                # Ollama fragen
                self.log("Frage Ollama...", "AI")
                decision = self.ask_ollama(screenshot)

                action = decision.get("action", "wait")
                params = decision.get("params", {})
                observation = decision.get("observation", "")[:100]
                finding = decision.get("finding")

                self.log(f"Beobachtung: {observation}", "AI")
                self.log(f"Aktion: {action}", "AI")

                # Finding speichern
                if finding:
                    self.findings.append({
                        "iteration": self.iteration,
                        "description": finding if isinstance(finding, str) else finding.get("description", str(finding)),
                        "screenshot": str(screenshot_path)
                    })
                    self.log(f"📋 Finding: {finding}", "WARN")

                # Log
                self.actions_log.append({
                    "iteration": self.iteration,
                    "action": action,
                    "params": params,
                    "observation": observation
                })

                # Done?
                if action == "done":
                    self.log("Test abgeschlossen.", "OK")
                    break

                # Aktion ausführen
                self.execute_action(action, params)

                # Nach type automatisch Return und Wait
                if action == "type":
                    time.sleep(0.3)
                    self.execute_action("key", {"key": "return"})
                    time.sleep(3)  # Auf Antwort warten

                last_action = action
                time.sleep(0.5)

            if _EMERGENCY_STOP:
                self.log("\n⚠️ Test durch ESC abgebrochen!", "WARN")

        finally:
            if esc_listener:
                esc_listener.stop()

        duration = (datetime.now() - start_time).total_seconds()
        report = self._generate_report(duration)

        self.log(f"\n✓ Test abgeschlossen in {duration:.0f}s")
        self.log(f"Report: {report['report_path']}", "OK")

        return report

    def _generate_report(self, duration: float) -> Dict:
        """Generiert Testbericht."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        lines = [
            "# Frank AI - UI-Test Report",
            "",
            f"**Datum:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Dauer:** {duration:.0f} Sekunden",
            f"**Iterationen:** {self.iteration}",
            f"**Tester:** Ollama ({self.model})",
            "",
            "---",
            "",
        ]

        # Findings
        if self.findings:
            lines.extend([
                "## Gefundene Probleme",
                "",
            ])
            for i, f in enumerate(self.findings, 1):
                lines.append(f"{i}. **Iteration {f['iteration']}:** {f['description']}")
            lines.append("")
        else:
            lines.extend([
                "## Ergebnis",
                "",
                "✅ Keine offensichtlichen Probleme gefunden.",
                "",
            ])

        # Aktionen
        lines.extend([
            "## Test-Verlauf",
            "",
            "| # | Aktion | Details |",
            "|---|--------|---------|",
        ])
        for log in self.actions_log:
            params_str = str(log.get("params", {}))[:30]
            lines.append(f"| {log['iteration']} | {log['action']} | {params_str} |")

        lines.extend([
            "",
            "---",
            f"*Lokal getestet mit Ollama/{self.model}*"
        ])

        # Speichern
        report_path = REPORTS_DIR / f"ai_test_report_{timestamp}.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return {
            "report_path": str(report_path),
            "findings": len(self.findings),
            "iterations": self.iteration
        }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Frank AI - Intelligenter UI-Tester (Ollama)")
    parser.add_argument("-n", "--iterations", type=int, default=15, help="Max Iterationen")
    parser.add_argument("-m", "--model", type=str, default="llava", help="Ollama Model")
    args = parser.parse_args()

    try:
        tester = AITester(model=args.model, max_iterations=args.iterations)
        result = tester.run()

        print("\n" + "=" * 60)
        print("  TEST ABGESCHLOSSEN")
        print(f"  Findings: {result.get('findings', 0)}")
        print(f"  Report: {result.get('report_path')}")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\nAbgebrochen.")
    except Exception as e:
        print(f"\nFehler: {e}")
        raise


if __name__ == "__main__":
    main()
