#!/usr/bin/env python3
"""
Frank AI - UI Test Launcher
===========================
Startet den intelligenten AI-Test mit Ollama.
"""

import tkinter as tk
import subprocess
import os
import threading
from pathlib import Path

BASE_DIR = Path(__file__).parent
REPORTS_DIR = BASE_DIR / "reports"


class TestLauncher:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Frank AI - UI Test")
        self.root.geometry("400x500")
        self.root.configure(bg="#1e1e2e")
        self.root.resizable(False, False)

        self.running = False
        self.process = None

        self._build_ui()

    def _build_ui(self):
        # Header
        tk.Label(
            self.root, text="🤖 AI UI-Test",
            font=("Ubuntu", 24, "bold"), bg="#1e1e2e", fg="#89b4fa"
        ).pack(pady=15)

        # Beschreibung
        tk.Label(
            self.root,
            text="Intelligenter Test mit Ollama/llava\n\n"
                 "• Testet wie ein Mensch\n"
                 "• Stellt echte Fragen an Frank\n"
                 "• Bewertet Antworten\n"
                 "• Findet Bugs automatisch",
            font=("Ubuntu", 11), bg="#1e1e2e", fg="#cdd6f4", justify="left"
        ).pack(pady=5)

        # Iterationen
        iter_frame = tk.Frame(self.root, bg="#1e1e2e")
        iter_frame.pack(pady=15)
        tk.Label(iter_frame, text="Iterationen:", bg="#1e1e2e", fg="#cdd6f4", font=("Ubuntu", 11)).pack(side="left")
        self.iterations_var = tk.StringVar(value="15")
        tk.Spinbox(iter_frame, from_=5, to=30, textvariable=self.iterations_var, width=5, font=("Ubuntu", 11)).pack(side="left", padx=10)

        # Start Button
        self.start_btn = tk.Button(
            self.root, text="▶  TEST STARTEN",
            command=self._start_test,
            bg="#a6e3a1", fg="#1e1e2e",
            font=("Ubuntu", 14, "bold"),
            width=18, height=2, cursor="hand2", relief="flat"
        )
        self.start_btn.pack(pady=20)

        # Status
        self.status_label = tk.Label(
            self.root, text="[ESC zum Abbrechen während Test]",
            font=("Ubuntu", 10), bg="#1e1e2e", fg="#6c7086"
        )
        self.status_label.pack()

        # Reports Button
        tk.Button(
            self.root, text="📁 Reports öffnen",
            command=lambda: subprocess.Popen(["xdg-open", str(REPORTS_DIR)]),
            bg="#45475a", fg="#cdd6f4", font=("Ubuntu", 10), relief="flat"
        ).pack(pady=10)

    def _start_test(self):
        if self.running:
            return

        self.running = True
        self.start_btn.configure(state="disabled", bg="#45475a", text="⏳ Läuft...")
        self.status_label.configure(text="Test läuft... ESC zum Abbrechen", fg="#f9e2af")

        def run():
            try:
                env = os.environ.copy()
                env["DISPLAY"] = os.environ.get("DISPLAY", ":0")

                # Starte in Terminal damit man sieht was passiert
                self.process = subprocess.Popen(
                    [
                        "gnome-terminal", "--", "bash", "-c",
                        f'cd "{BASE_DIR}" && python3 ai_tester.py -n {self.iterations_var.get()}; echo ""; echo "Drücke Enter zum Schließen..."; read'
                    ],
                    env=env
                )
                self.process.wait()
                self.root.after(0, self._done)
            except Exception as e:
                self.root.after(0, lambda: self._error(str(e)))

        threading.Thread(target=run, daemon=True).start()

    def _done(self):
        self.running = False
        self.process = None
        self.start_btn.configure(state="normal", bg="#a6e3a1", text="▶  TEST STARTEN")
        self.status_label.configure(text="✓ Fertig! Report erstellt.", fg="#a6e3a1")

    def _error(self, msg):
        self.running = False
        self.start_btn.configure(state="normal", bg="#a6e3a1", text="▶  TEST STARTEN")
        self.status_label.configure(text=f"Fehler: {msg[:30]}", fg="#f38ba8")

    def run(self):
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        self.root.mainloop()


if __name__ == "__main__":
    TestLauncher().run()
