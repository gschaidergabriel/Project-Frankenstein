#!/usr/bin/env python3
"""
Frank AI System - UI Test Runner (Extended)
============================================
Automatisiertes UI-Testing mit:
- Workflow-Analyse
- Design-Analyse
- UX-Metriken
- Vergleichs-Modus

Autor: Frank AI System
Version: 2.0.0
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
import threading
import time
import json
import os
import webbrowser
from datetime import datetime
from pathlib import Path

# Import test modules
from test_engine import UITestEngine
from test_cases import get_all_test_cases, get_tests_by_category

# Pfade
BASE_DIR = Path(__file__).parent
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
REPORTS_DIR = BASE_DIR / "reports"
EXPECTED_DIR = BASE_DIR / "expected"
CONFIG_FILE = BASE_DIR / "config.json"


class UITestRunnerGUI:
    """Hauptfenster für den UI Test Runner."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Frank AI - UI Test Runner v2.0")
        self.root.geometry("900x800")
        self.root.configure(bg="#1e1e2e")

        # State
        self.is_running = False
        self.test_thread = None
        self.engine = None
        self.start_time = None
        self.remaining_seconds = 0
        self.current_mode = "test"  # "test", "design", "workflow", "compare"

        # Load config
        self.config = self._load_config()

        # Build UI
        self._create_styles()
        self._build_ui()

        # Update timer
        self._update_timer()

    def _load_config(self) -> dict:
        """Lädt Konfiguration."""
        default = {
            "duration_minutes": 15,
            "interval_seconds": 30,
            "selected_tests": ["all"],
            "save_screenshots": True,
            "ocr_enabled": True,
            "selected_categories": ["all"]
        }
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    return {**default, **json.load(f)}
            except:
                pass
        return default

    def _save_config(self):
        """Speichert Konfiguration."""
        config = {
            "duration_minutes": self.duration_var.get(),
            "interval_seconds": self.interval_var.get(),
            "selected_categories": self._get_selected_categories(),
            "save_screenshots": self.save_screenshots_var.get(),
            "ocr_enabled": self.ocr_var.get()
        }
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)

    def _create_styles(self):
        """Erstellt Custom Styles."""
        style = ttk.Style()
        style.theme_use("clam")

        bg = "#1e1e2e"
        fg = "#cdd6f4"
        accent = "#89b4fa"
        surface = "#313244"

        style.configure("TFrame", background=bg)
        style.configure("TLabel", background=bg, foreground=fg, font=("Ubuntu", 11))
        style.configure("TButton", font=("Ubuntu", 11))
        style.configure("Header.TLabel", font=("Ubuntu", 18, "bold"), foreground=accent)
        style.configure("Timer.TLabel", font=("Ubuntu Mono", 32, "bold"), foreground="#a6e3a1")
        style.configure("Status.TLabel", font=("Ubuntu", 12), foreground="#f9e2af")
        style.configure("TCheckbutton", background=bg, foreground=fg)
        style.configure("TRadiobutton", background=bg, foreground=fg)
        style.configure("TNotebook", background=bg)
        style.configure("TNotebook.Tab", background=surface, foreground=fg, padding=[15, 5])
        style.configure("TLabelframe", background=bg, foreground=fg)
        style.configure("TLabelframe.Label", background=bg, foreground=accent, font=("Ubuntu", 11, "bold"))

    def _build_ui(self):
        """Baut das UI auf."""
        main = ttk.Frame(self.root, padding=15)
        main.pack(fill="both", expand=True)

        # Header
        header_frame = ttk.Frame(main)
        header_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(header_frame, text="UI Test Runner", style="Header.TLabel").pack(side="left")

        # Mode indicator
        self.mode_label = ttk.Label(header_frame, text="Modus: Test", style="Status.TLabel")
        self.mode_label.pack(side="right")

        # Notebook für Modi
        self.notebook = ttk.Notebook(main)
        self.notebook.pack(fill="both", expand=True, pady=10)

        # Tab 1: Test Mode
        self._build_test_tab()

        # Tab 2: Design Analysis
        self._build_design_tab()

        # Tab 3: Workflow Analysis
        self._build_workflow_tab()

        # Tab 4: Compare Mode
        self._build_compare_tab()

        # Log Frame (global)
        log_frame = ttk.LabelFrame(main, text="Log", padding=10)
        log_frame.pack(fill="both", expand=True, pady=10)

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=8,
            bg="#11111b",
            fg="#cdd6f4",
            font=("Ubuntu Mono", 10),
            insertbackground="#cdd6f4"
        )
        self.log_text.pack(fill="both", expand=True)

        # Bottom buttons
        self._build_bottom_buttons(main)

    def _build_test_tab(self):
        """Baut Test-Tab."""
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="  Tests  ")

        # Timer Display
        timer_frame = ttk.Frame(tab)
        timer_frame.pack(fill="x", pady=10)

        self.timer_label = ttk.Label(timer_frame, text="00:00:00", style="Timer.TLabel")
        self.timer_label.pack()

        self.status_label = ttk.Label(timer_frame, text="Bereit", style="Status.TLabel")
        self.status_label.pack(pady=5)

        # Config Frame
        config_frame = ttk.LabelFrame(tab, text="Konfiguration", padding=15)
        config_frame.pack(fill="x", pady=10)

        # Duration & Interval
        row1 = ttk.Frame(config_frame)
        row1.pack(fill="x", pady=5)

        ttk.Label(row1, text="Testdauer (Min):").pack(side="left")
        self.duration_var = tk.IntVar(value=self.config["duration_minutes"])
        ttk.Spinbox(row1, from_=1, to=480, textvariable=self.duration_var, width=8).pack(side="left", padx=10)

        ttk.Label(row1, text="Intervall (Sek):").pack(side="left", padx=(20, 0))
        self.interval_var = tk.IntVar(value=self.config["interval_seconds"])
        ttk.Spinbox(row1, from_=5, to=300, textvariable=self.interval_var, width=8).pack(side="left", padx=10)

        # Options
        row2 = ttk.Frame(config_frame)
        row2.pack(fill="x", pady=10)

        self.save_screenshots_var = tk.BooleanVar(value=self.config["save_screenshots"])
        ttk.Checkbutton(row2, text="Screenshots speichern", variable=self.save_screenshots_var).pack(side="left", padx=10)

        self.ocr_var = tk.BooleanVar(value=self.config["ocr_enabled"])
        ttk.Checkbutton(row2, text="OCR aktivieren", variable=self.ocr_var).pack(side="left", padx=10)

        # Category Selection
        cat_frame = ttk.LabelFrame(tab, text="Test-Kategorien", padding=10)
        cat_frame.pack(fill="x", pady=10)

        self.category_vars = {}
        categories = [
            ("all", "Alle Tests"),
            ("basic", "Basis-Tests"),
            ("rendering", "Rendering & Display"),
            ("workflow", "Workflow"),
            ("convenience", "Convenience"),
            ("design", "Design"),
            ("accessibility", "Accessibility")
        ]

        for i, (cat_id, cat_name) in enumerate(categories):
            var = tk.BooleanVar(value=cat_id in self.config.get("selected_categories", ["all"]))
            self.category_vars[cat_id] = var
            ttk.Checkbutton(cat_frame, text=cat_name, variable=var).grid(
                row=i // 4, column=i % 4, sticky="w", padx=10, pady=2
            )

        # Start/Stop buttons for Test mode
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill="x", pady=15)

        self.start_btn = tk.Button(
            btn_frame, text="▶ Tests starten", command=self._start_tests,
            bg="#a6e3a1", fg="#1e1e2e", font=("Ubuntu", 12, "bold"), width=18, cursor="hand2"
        )
        self.start_btn.pack(side="left", padx=5)

        self.stop_btn = tk.Button(
            btn_frame, text="⏹ Stoppen", command=self._stop_tests,
            bg="#f38ba8", fg="#1e1e2e", font=("Ubuntu", 12, "bold"), width=12,
            state="disabled", cursor="hand2"
        )
        self.stop_btn.pack(side="left", padx=5)

    def _build_design_tab(self):
        """Baut Design-Analyse Tab."""
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="  Design  ")

        # Info
        ttk.Label(tab, text="Design-Analyse", style="Header.TLabel").pack(pady=10)
        ttk.Label(tab, text="Analysiert Farben, Kontrast, Layout und Accessibility des Chat Overlays.").pack()

        # Options
        opt_frame = ttk.LabelFrame(tab, text="Analyse-Optionen", padding=15)
        opt_frame.pack(fill="x", pady=20)

        self.design_contrast_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_frame, text="Kontrast-Analyse (WCAG)", variable=self.design_contrast_var).pack(anchor="w")

        self.design_palette_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_frame, text="Farbpaletten-Extraktion", variable=self.design_palette_var).pack(anchor="w")

        self.design_layout_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_frame, text="Layout-Analyse", variable=self.design_layout_var).pack(anchor="w")

        self.design_annotate_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_frame, text="Annotiertes Bild erstellen", variable=self.design_annotate_var).pack(anchor="w")

        # Buttons
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(pady=20)

        tk.Button(
            btn_frame, text="🎨 Design analysieren", command=self._run_design_analysis,
            bg="#cba6f7", fg="#1e1e2e", font=("Ubuntu", 12, "bold"), width=20, cursor="hand2"
        ).pack(side="left", padx=10)

        tk.Button(
            btn_frame, text="📊 Report öffnen", command=self._open_design_report,
            bg="#89b4fa", fg="#1e1e2e", font=("Ubuntu", 11), cursor="hand2"
        ).pack(side="left", padx=10)

    def _build_workflow_tab(self):
        """Baut Workflow-Analyse Tab."""
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="  Workflow  ")

        ttk.Label(tab, text="Workflow-Analyse", style="Header.TLabel").pack(pady=10)
        ttk.Label(tab, text="Testet Benutzer-Workflows und misst UX-Metriken.").pack()

        # Workflow Selection
        wf_frame = ttk.LabelFrame(tab, text="Workflows auswählen", padding=15)
        wf_frame.pack(fill="x", pady=20)

        self.workflow_vars = {}
        workflows = [
            ("basic_interaction", "Basis-Interaktion"),
            ("scroll_conversation", "Scrollen"),
            ("copy_text", "Text kopieren"),
            ("keyboard_navigation", "Keyboard-Navigation"),
            ("rapid_interaction", "Schnelle Interaktionen"),
            ("long_text_handling", "Lange Texte"),
        ]

        for i, (wf_id, wf_name) in enumerate(workflows):
            var = tk.BooleanVar(value=True)
            self.workflow_vars[wf_id] = var
            ttk.Checkbutton(wf_frame, text=wf_name, variable=var).grid(
                row=i // 3, column=i % 3, sticky="w", padx=15, pady=3
            )

        # Iterations
        iter_frame = ttk.Frame(tab)
        iter_frame.pack(pady=10)

        ttk.Label(iter_frame, text="Wiederholungen:").pack(side="left")
        self.workflow_iterations_var = tk.IntVar(value=3)
        ttk.Spinbox(iter_frame, from_=1, to=20, textvariable=self.workflow_iterations_var, width=5).pack(side="left", padx=10)

        # Buttons
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(pady=20)

        tk.Button(
            btn_frame, text="🔄 Workflows testen", command=self._run_workflow_analysis,
            bg="#a6e3a1", fg="#1e1e2e", font=("Ubuntu", 12, "bold"), width=20, cursor="hand2"
        ).pack(side="left", padx=10)

    def _build_compare_tab(self):
        """Baut Vergleichs-Tab."""
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="  Vergleich  ")

        ttk.Label(tab, text="Design-Vergleich", style="Header.TLabel").pack(pady=10)
        ttk.Label(tab, text="Vergleicht zwei Design-Versionen (Vorher/Nachher).").pack()

        # Image selection
        sel_frame = ttk.LabelFrame(tab, text="Bilder auswählen", padding=15)
        sel_frame.pack(fill="x", pady=20)

        # Before
        before_frame = ttk.Frame(sel_frame)
        before_frame.pack(fill="x", pady=5)

        ttk.Label(before_frame, text="Vorher:").pack(side="left")
        self.before_path_var = tk.StringVar()
        ttk.Entry(before_frame, textvariable=self.before_path_var, width=50).pack(side="left", padx=10)
        tk.Button(before_frame, text="...", command=lambda: self._browse_image("before")).pack(side="left")

        # After
        after_frame = ttk.Frame(sel_frame)
        after_frame.pack(fill="x", pady=5)

        ttk.Label(after_frame, text="Nachher:").pack(side="left")
        self.after_path_var = tk.StringVar()
        ttk.Entry(after_frame, textvariable=self.after_path_var, width=50).pack(side="left", padx=10)
        tk.Button(after_frame, text="...", command=lambda: self._browse_image("after")).pack(side="left")

        # Or capture live
        ttk.Separator(sel_frame, orient="horizontal").pack(fill="x", pady=15)

        capture_frame = ttk.Frame(sel_frame)
        capture_frame.pack()

        tk.Button(
            capture_frame, text="📸 Vorher erfassen", command=lambda: self._capture_for_compare("before"),
            bg="#f9e2af", fg="#1e1e2e", font=("Ubuntu", 10)
        ).pack(side="left", padx=10)

        tk.Button(
            capture_frame, text="📸 Nachher erfassen", command=lambda: self._capture_for_compare("after"),
            bg="#f9e2af", fg="#1e1e2e", font=("Ubuntu", 10)
        ).pack(side="left", padx=10)

        # Compare button
        tk.Button(
            tab, text="⚖️ Vergleichen", command=self._run_comparison,
            bg="#89b4fa", fg="#1e1e2e", font=("Ubuntu", 12, "bold"), width=20, cursor="hand2"
        ).pack(pady=20)

    def _build_bottom_buttons(self, parent):
        """Baut untere Button-Leiste."""
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill="x", pady=10)

        tk.Button(
            btn_frame, text="📁 Ordner öffnen", command=self._open_folder,
            bg="#45475a", fg="#cdd6f4", font=("Ubuntu", 10), cursor="hand2"
        ).pack(side="left", padx=5)

        tk.Button(
            btn_frame, text="🗑️ Screenshots löschen", command=self._clear_screenshots,
            bg="#45475a", fg="#cdd6f4", font=("Ubuntu", 10), cursor="hand2"
        ).pack(side="left", padx=5)

        tk.Button(
            btn_frame, text="📊 Letzter Report", command=self._show_last_report,
            bg="#45475a", fg="#cdd6f4", font=("Ubuntu", 10), cursor="hand2"
        ).pack(side="right", padx=5)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _get_selected_categories(self) -> list:
        """Gibt ausgewählte Kategorien zurück."""
        all_var = self.category_vars.get("all")
        if all_var is not None and all_var.get():
            return ["all"]
        return [cat for cat, var in self.category_vars.items() if var.get() and cat != "all"]

    def _log(self, message: str, level: str = "INFO"):
        """Schreibt ins Log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        colors = {"INFO": "#89b4fa", "OK": "#a6e3a1", "WARN": "#f9e2af", "ERROR": "#f38ba8"}

        self.log_text.configure(state="normal")

        # Tag konfigurieren bevor wir es verwenden
        self.log_text.tag_configure(level, foreground=colors.get(level, "#cdd6f4"))

        # Position merken fuer Tag-Anwendung
        start_index = self.log_text.index("end-1c")
        self.log_text.insert("end", f"[{timestamp}] [{level}] {message}\n")
        end_index = self.log_text.index("end-1c")

        # Tag anwenden fuer Farbformatierung
        self.log_text.tag_add(level, start_index, end_index)

        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _update_timer(self):
        """Aktualisiert Timer."""
        if self.is_running and self.remaining_seconds > 0:
            h = self.remaining_seconds // 3600
            m = (self.remaining_seconds % 3600) // 60
            s = self.remaining_seconds % 60
            self.timer_label.configure(text=f"{h:02d}:{m:02d}:{s:02d}")
            self.remaining_seconds -= 1
        elif self.is_running and self.remaining_seconds <= 0:
            self._stop_tests()

        self.root.after(1000, self._update_timer)

    def _browse_image(self, which: str):
        """Öffnet Datei-Dialog für Bildauswahl."""
        path = filedialog.askopenfilename(
            initialdir=str(SCREENSHOTS_DIR),
            filetypes=[("Images", "*.png *.jpg *.jpeg")]
        )
        if path:
            if which == "before":
                self.before_path_var.set(path)
            else:
                self.after_path_var.set(path)

    def _capture_for_compare(self, which: str):
        """Erfasst aktuellen Screenshot für Vergleich."""
        try:
            from test_engine import UITestEngine

            engine = UITestEngine(SCREENSHOTS_DIR, save_screenshots=True, ocr_enabled=False)
            img = engine.capture_window("Frank")

            if img:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                path = SCREENSHOTS_DIR / f"compare_{which}_{timestamp}.png"
                img.save(path)

                if which == "before":
                    self.before_path_var.set(str(path))
                else:
                    self.after_path_var.set(str(path))

                self._log(f"Screenshot erfasst: {path.name}", "OK")
            else:
                self._log("Konnte Overlay nicht erfassen", "ERROR")
        except Exception as e:
            self._log(f"Fehler: {e}", "ERROR")

    # =========================================================================
    # Test Mode
    # =========================================================================

    def _start_tests(self):
        """Startet Tests."""
        categories = self._get_selected_categories()
        if not categories:
            messagebox.showwarning("Keine Kategorie", "Bitte mindestens eine Kategorie wählen!")
            return

        self._save_config()
        self.is_running = True
        self.remaining_seconds = self.duration_var.get() * 60

        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_label.configure(text="Tests laufen...")

        self._log("=== Tests gestartet ===", "INFO")

        self.test_thread = threading.Thread(target=self._run_tests, daemon=True)
        self.test_thread.start()

    def _stop_tests(self):
        """Stoppt Tests."""
        # Vermeide doppelte Ausfuehrung
        if not self.is_running and self.start_btn.cget("state") == "normal":
            return

        self.is_running = False
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status_label.configure(text="Gestoppt")
        self.timer_label.configure(text="00:00:00")

        if self.engine:
            self.engine.stop()
            self._log("=== Tests gestoppt ===", "WARN")
            self._generate_test_report()

    def _run_tests(self):
        """Führt Tests aus."""
        try:
            self.engine = UITestEngine(
                screenshots_dir=SCREENSHOTS_DIR,
                save_screenshots=self.save_screenshots_var.get(),
                ocr_enabled=self.ocr_var.get(),
                log_callback=self._log
            )

            categories = self._get_selected_categories()
            interval = self.interval_var.get()

            # Sammle Tests aus Kategorien
            if "all" in categories:
                test_ids = ["all"]
            else:
                test_ids = []
                for cat in categories:
                    tests = get_tests_by_category(cat)
                    test_ids.extend(tests.keys())

            iteration = 0
            while self.is_running:
                iteration += 1
                self.root.after(0, lambda i=iteration: self.status_label.configure(
                    text=f"Iteration {i}..."
                ))

                self._log(f"--- Iteration {iteration} ---")

                results = self.engine.run_tests(test_ids)

                for test_id, result in results.items():
                    if result["passed"]:
                        self._log(f"  ✓ {test_id}", "OK")
                    else:
                        self._log(f"  ✗ {test_id}: {result.get('error', '')[:50]}", "ERROR")

                for _ in range(interval):
                    if not self.is_running:
                        break
                    time.sleep(1)

        except Exception as e:
            self._log(f"Fehler: {e}", "ERROR")
        finally:
            self.root.after(0, self._stop_tests)

    def _generate_test_report(self):
        """Generiert Test-Report."""
        if not self.engine:
            return

        report = self.engine.generate_report()
        report_file = REPORTS_DIR / f"test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        with open(report_file, "w") as f:
            json.dump(report, f, indent=2, default=str)

        self._log(f"Report: {report_file.name}", "INFO")

    # =========================================================================
    # Design Analysis Mode
    # =========================================================================

    def _run_design_analysis(self):
        """Führt Design-Analyse durch."""
        self._log("=== Design-Analyse gestartet ===", "INFO")

        try:
            from test_engine import UITestEngine
            from design_analyzer import DesignAnalyzer

            engine = UITestEngine(SCREENSHOTS_DIR, save_screenshots=True, ocr_enabled=False)
            img = engine.capture_window("Frank")

            if not img:
                self._log("Konnte Overlay nicht erfassen!", "ERROR")
                return

            analyzer = DesignAnalyzer(REPORTS_DIR)
            report = analyzer.analyze_image(img)

            # Log results
            self._log(f"Gesamt-Score: {report.overall_score}/100", "OK" if report.overall_score >= 70 else "WARN")
            self._log(f"Kontrast: {report.contrast_score:.0f}/100")
            self._log(f"Layout: {report.layout_score:.0f}/100")
            self._log(f"Farbharmonie: {report.color_harmony}")

            if report.accessibility_issues:
                for issue in report.accessibility_issues[:3]:
                    self._log(f"  ⚠ {issue}", "WARN")

            for rec in report.recommendations[:3]:
                self._log(f"  → {rec}", "INFO")

            # Generate HTML report
            html_path = analyzer.generate_html_report(report, img)
            self._log(f"HTML Report: {Path(html_path).name}", "OK")

            # Create annotated image
            if self.design_annotate_var.get():
                annotated = analyzer.create_annotated_image(img, report)
                ann_path = SCREENSHOTS_DIR / f"annotated_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                annotated.save(ann_path)
                self._log(f"Annotiert: {ann_path.name}", "OK")

        except ImportError as e:
            self._log(f"Import-Fehler: {e}", "ERROR")
        except Exception as e:
            self._log(f"Fehler: {e}", "ERROR")

    def _open_design_report(self):
        """Öffnet letzten Design-Report."""
        reports = sorted(REPORTS_DIR.glob("design_report_*.html"), reverse=True)
        if reports:
            webbrowser.open(f"file://{reports[0]}")
        else:
            messagebox.showinfo("Kein Report", "Noch keine Design-Reports vorhanden.")

    # =========================================================================
    # Workflow Analysis Mode
    # =========================================================================

    def _run_workflow_analysis(self):
        """Führt Workflow-Analyse durch."""
        selected = [wf for wf, var in self.workflow_vars.items() if var.get()]
        if not selected:
            messagebox.showwarning("Keine Workflows", "Bitte mindestens einen Workflow wählen!")
            return

        iterations = self.workflow_iterations_var.get()
        self._log(f"=== Workflow-Analyse ({iterations}x) ===", "INFO")

        def run():
            try:
                from workflow_analyzer import WorkflowAnalyzer

                analyzer = WorkflowAnalyzer(self._log)
                workflows = analyzer.get_chat_overlay_workflows()

                for i in range(iterations):
                    self._log(f"--- Durchlauf {i+1}/{iterations} ---")

                    for wf_id in selected:
                        if wf_id in workflows:
                            result = analyzer.run_workflow(wf_id, workflows[wf_id])
                            if result.success:
                                self._log(f"  ✓ {wf_id}: {result.total_time:.2f}s", "OK")
                            else:
                                self._log(f"  ✗ {wf_id}: {result.errors[0] if result.errors else 'Failed'}", "ERROR")

                    time.sleep(1)

                # Metrics
                metrics = analyzer.calculate_metrics()
                self._log("=== UX Metriken ===", "INFO")
                self._log(f"  Reaktionszeit (avg): {metrics.response_time_avg:.3f}s")
                self._log(f"  Task Completion: {metrics.task_completion_rate:.1f}%")
                self._log(f"  Smoothness: {metrics.interaction_smoothness:.1f}/100")
                self._log(f"  Effizienz: {metrics.workflow_efficiency:.1f}/100")

                # Save report
                report = analyzer.generate_report()
                report_file = REPORTS_DIR / f"workflow_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                with open(report_file, "w") as f:
                    json.dump(report, f, indent=2)
                self._log(f"Report: {report_file.name}", "OK")

            except Exception as e:
                self._log(f"Fehler: {e}", "ERROR")

        threading.Thread(target=run, daemon=True).start()

    # =========================================================================
    # Compare Mode
    # =========================================================================

    def _run_comparison(self):
        """Vergleicht zwei Design-Versionen."""
        before_path = self.before_path_var.get()
        after_path = self.after_path_var.get()

        if not before_path or not after_path:
            messagebox.showwarning("Fehlende Bilder", "Bitte beide Bilder auswählen!")
            return

        self._log("=== Design-Vergleich ===", "INFO")

        try:
            from PIL import Image
            from design_analyzer import DesignAnalyzer

            img1 = Image.open(before_path)
            img2 = Image.open(after_path)

            analyzer = DesignAnalyzer(REPORTS_DIR)
            comparison = analyzer.compare_designs(img1, img2)

            self._log(f"Vorher Score: {comparison['before']['overall_score']}")
            self._log(f"Nachher Score: {comparison['after']['overall_score']}")

            if comparison['improvements']:
                for imp in comparison['improvements']:
                    self._log(f"  ✓ {imp}", "OK")

            if comparison['regressions']:
                for reg in comparison['regressions']:
                    self._log(f"  ✗ {reg}", "ERROR")

            if not comparison['improvements'] and not comparison['regressions']:
                self._log("  Keine signifikanten Änderungen", "INFO")

        except Exception as e:
            self._log(f"Fehler: {e}", "ERROR")

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def _open_folder(self):
        """Öffnet Test-Ordner."""
        import subprocess
        subprocess.Popen(["xdg-open", str(BASE_DIR)])

    def _clear_screenshots(self):
        """Löscht Screenshots."""
        if messagebox.askyesno("Löschen?", "Alle Screenshots löschen?"):
            import shutil
            shutil.rmtree(SCREENSHOTS_DIR, ignore_errors=True)
            SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
            self._log("Screenshots gelöscht", "OK")

    def _show_last_report(self):
        """Zeigt letzten Report."""
        reports = sorted(REPORTS_DIR.glob("*.json"), reverse=True)
        if not reports:
            messagebox.showinfo("Kein Report", "Noch keine Reports vorhanden.")
            return

        with open(reports[0]) as f:
            report = json.load(f)

        win = tk.Toplevel(self.root)
        win.title(f"Report: {reports[0].name}")
        win.geometry("700x500")
        win.configure(bg="#1e1e2e")

        text = scrolledtext.ScrolledText(win, bg="#11111b", fg="#cdd6f4", font=("Ubuntu Mono", 10))
        text.pack(fill="both", expand=True, padx=10, pady=10)
        text.insert("1.0", json.dumps(report, indent=2, default=str))
        text.configure(state="disabled")

    def run(self):
        """Startet die Anwendung."""
        self.root.mainloop()


def main():
    # Ensure directories exist
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    EXPECTED_DIR.mkdir(parents=True, exist_ok=True)

    app = UITestRunnerGUI()
    app.run()


if __name__ == "__main__":
    main()
