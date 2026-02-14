#!/usr/bin/env python3
"""
UI Tester Results Popup - GTK4 window for test results and design collaboration.

Phase 3: Shows test results in a SIDE PANEL (not fullscreen) so the
Frank overlay remains visible for live CSS preview.
"""

import argparse
import logging
import os
import threading
from pathlib import Path
from typing import Dict, List, Optional

os.environ.setdefault("GDK_BACKEND", "x11")

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Pango

LOG = logging.getLogger("ui_tester.results_popup")

# Paths
TESTER_DIR = Path(__file__).parent
STYLES_DIR = TESTER_DIR / "styles"
CSS_FILE = STYLES_DIR / "tester_cyberpunk.css"


class ResultsPopup(Gtk.ApplicationWindow):
    """Results popup with chat for collaborative design - SIDE PANEL style."""

    def __init__(self, app: Gtk.Application, duration: int = 5, test_results: Optional[Dict] = None):
        super().__init__(application=app, title="UI TESTER // DESIGN")
        self.app = app
        self.duration = duration
        self.test_results = test_results
        self.chat_history: List[Dict[str, str]] = []
        self.design_proposer = None
        self.test_executor = None
        self.is_testing = False
        self.is_design_mode = False

        self._setup_window()
        self._load_css()
        self._build_ui()

        # Start test if no results provided
        if not test_results:
            GLib.timeout_add(1000, self._start_test)

    def _setup_window(self):
        """Configure window as RIGHT-SIDE PANEL (not fullscreen!)."""
        display = Gdk.Display.get_default()
        if display:
            monitor = display.get_monitors().get_item(0)
            if monitor:
                geometry = monitor.get_geometry()
                # Side panel: Right 40% of screen
                panel_width = int(geometry.width * 0.4)
                panel_x = geometry.width - panel_width

                self.set_default_size(panel_width, geometry.height)
                # Position on right side
                self.set_decorated(True)

                # Move to right side after show
                GLib.timeout_add(100, self._position_window, panel_x, 0)

    def _position_window(self, x: int, y: int):
        """Position window on right side of screen."""
        try:
            import subprocess
            import shutil

            # Check if wmctrl is available
            if shutil.which("wmctrl"):
                subprocess.run(
                    ["wmctrl", "-r", ":ACTIVE:", "-e", f"0,{x},{y},-1,-1"],
                    timeout=5,
                    capture_output=True
                )
            else:
                # Fallback: just log and continue - window will open in default position
                LOG.debug("wmctrl not available, window position unchanged")
        except Exception as e:
            LOG.debug(f"Could not position window: {e}")
        return False

    def _load_css(self):
        """Load the cyberpunk CSS theme."""
        if not CSS_FILE.exists():
            LOG.warning(f"CSS file not found: {CSS_FILE}")
            return

        css_provider = Gtk.CssProvider()
        try:
            css_provider.load_from_path(str(CSS_FILE))
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(),
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        except Exception as e:
            LOG.error(f"Failed to load CSS: {e}")

    def _build_ui(self):
        """Build the user interface."""
        # Main container - NO dark overlay, just the panel
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        main_box.add_css_class("tester-window")
        self.set_child(main_box)

        # Header
        header = self._create_header()
        main_box.append(header)

        # Content area with scrolling
        content_scroll = Gtk.ScrolledWindow()
        content_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        content_scroll.set_vexpand(True)
        main_box.append(content_scroll)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(16)
        content.set_margin_end(16)
        content_scroll.set_child(content)

        # Progress section (shown during testing)
        self.progress_section = self._create_progress_section()
        content.append(self.progress_section)

        # Results section (shown after testing)
        self.results_section = self._create_results_section()
        self.results_section.set_visible(False)
        content.append(self.results_section)

        # CSS Changes Preview
        self.css_preview_section = self._create_css_preview_section()
        self.css_preview_section.set_visible(False)
        content.append(self.css_preview_section)

        # Chat section
        self.chat_section = self._create_chat_section()
        content.append(self.chat_section)

        # Action buttons
        self.action_buttons = self._create_action_buttons()
        main_box.append(self.action_buttons)

        # Keyboard handler
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

    def _create_header(self) -> Gtk.Box:
        """Create the header section."""
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        header.add_css_class("tester-header")
        header.set_margin_start(16)
        header.set_margin_end(16)
        header.set_margin_top(12)
        header.set_margin_bottom(12)

        # Left: Title
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_box.set_hexpand(True)

        title = Gtk.Label()
        title.set_markup(
            "<span font='JetBrains Mono Bold 14' foreground='#FF6B00'>"
            "◉ UI TESTER // LIVE DESIGN"
            "</span>"
        )
        title.set_halign(Gtk.Align.START)
        title_box.append(title)

        self.status_label = Gtk.Label()
        self.status_label.set_markup(
            "<span font='JetBrains Mono 9' foreground='#888899'>"
            "Overlay bleibt sichtbar für Live-Preview"
            "</span>"
        )
        self.status_label.set_halign(Gtk.Align.START)
        title_box.append(self.status_label)

        header.append(title_box)

        # Right: Close button
        close_btn = Gtk.Button(label="✕")
        close_btn.add_css_class("close-button")
        close_btn.connect("clicked", lambda b: self.app.quit())
        header.append(close_btn)

        return header

    def _create_progress_section(self) -> Gtk.Box:
        """Create the progress section."""
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        section.add_css_class("progress-container")
        section.set_margin_bottom(12)

        # Progress bar
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_fraction(0.0)
        self.progress_bar.add_css_class("progress-bar")
        section.append(self.progress_bar)

        # Progress text
        self.progress_text = Gtk.Label()
        self.progress_text.set_markup(
            "<span font='JetBrains Mono 10' foreground='#FF6B00'>"
            "Starte autonomen Test..."
            "</span>"
        )
        self.progress_text.add_css_class("progress-text")
        self.progress_text.set_halign(Gtk.Align.START)
        section.append(self.progress_text)

        return section

    def _create_results_section(self) -> Gtk.Box:
        """Create the results section."""
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        # Summary stats in a row
        summary_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        summary_box.set_halign(Gtk.Align.CENTER)
        section.append(summary_box)

        self.stats_labels = {}
        for stat_id, stat_name in [("actions", "TESTS"), ("issues", "ISSUES")]:
            stat_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            stat_box.set_halign(Gtk.Align.CENTER)

            value_label = Gtk.Label()
            value_label.set_markup(
                f"<span font='JetBrains Mono Bold 20' foreground='#FF6B00'>0</span>"
            )
            stat_box.append(value_label)
            self.stats_labels[stat_id] = value_label

            name_label = Gtk.Label()
            name_label.set_markup(
                f"<span font='JetBrains Mono 9' foreground='#888899'>{stat_name}</span>"
            )
            stat_box.append(name_label)

            summary_box.append(stat_box)

        # Issues list (compact)
        self.issues_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.issues_list.set_margin_top(8)
        section.append(self.issues_list)

        return section

    def _create_css_preview_section(self) -> Gtk.Box:
        """Create CSS changes preview section."""
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        section.add_css_class("preview-container")

        # Header
        header = Gtk.Label()
        header.set_markup(
            "<span font='JetBrains Mono Bold 10' foreground='#FF6B00'>"
            "CSS ÄNDERUNGEN (LIVE)"
            "</span>"
        )
        header.add_css_class("preview-header")
        header.set_halign(Gtk.Align.START)
        section.append(header)

        # CSS diff preview
        self.css_diff_label = Gtk.Label()
        self.css_diff_label.set_markup(
            "<span font='JetBrains Mono 10' foreground='#888899'>Keine Änderungen</span>"
        )
        self.css_diff_label.set_halign(Gtk.Align.START)
        self.css_diff_label.set_wrap(True)
        self.css_diff_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.css_diff_label.add_css_class("preview-ascii")
        section.append(self.css_diff_label)

        return section

    def _create_chat_section(self) -> Gtk.Box:
        """Create the chat section."""
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        section.add_css_class("chat-container")
        section.set_vexpand(True)

        # Chat header
        chat_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        chat_header.add_css_class("chat-header")
        chat_header.set_margin_start(12)
        chat_header.set_margin_end(12)
        chat_header.set_margin_top(8)
        chat_header.set_margin_bottom(8)

        header_label = Gtk.Label()
        header_label.set_markup(
            "<span font='JetBrains Mono Bold 10' foreground='#FF6B00'>"
            "DESIGN CHAT"
            "</span>"
        )
        chat_header.append(header_label)
        section.append(chat_header)

        # Chat messages area
        chat_scroll = Gtk.ScrolledWindow()
        chat_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        chat_scroll.set_vexpand(True)
        chat_scroll.set_min_content_height(150)
        chat_scroll.add_css_class("chat-messages")

        self.chat_messages = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.chat_messages.set_margin_top(8)
        self.chat_messages.set_margin_bottom(8)
        self.chat_messages.set_margin_start(12)
        self.chat_messages.set_margin_end(12)
        chat_scroll.set_child(self.chat_messages)
        section.append(chat_scroll)

        # Chat input
        input_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        input_box.add_css_class("chat-input-container")
        input_box.set_margin_start(12)
        input_box.set_margin_end(12)
        input_box.set_margin_top(8)
        input_box.set_margin_bottom(12)

        self.chat_input = Gtk.Entry()
        self.chat_input.set_placeholder_text("z.B. 'Mach die Schrift größer'...")
        self.chat_input.add_css_class("chat-input")
        self.chat_input.set_hexpand(True)
        self.chat_input.connect("activate", self._on_chat_send)
        input_box.append(self.chat_input)

        send_btn = Gtk.Button(label="➤")
        send_btn.add_css_class("chat-send-button")
        send_btn.connect("clicked", self._on_chat_send)
        input_box.append(send_btn)

        section.append(input_box)

        return section

    def _create_action_buttons(self) -> Gtk.Box:
        """Create action buttons."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.add_css_class("action-buttons")
        box.set_halign(Gtk.Align.CENTER)
        box.set_margin_top(12)
        box.set_margin_bottom(16)

        # Apply button
        self.apply_btn = Gtk.Button(label="◉ ANWENDEN")
        self.apply_btn.add_css_class("action-button")
        self.apply_btn.add_css_class("primary")
        self.apply_btn.connect("clicked", self._on_apply)
        self.apply_btn.set_sensitive(False)
        box.append(self.apply_btn)

        # Rollback button
        self.rollback_btn = Gtk.Button(label="↩ ZURÜCK")
        self.rollback_btn.add_css_class("action-button")
        self.rollback_btn.add_css_class("secondary")
        self.rollback_btn.connect("clicked", self._on_rollback)
        self.rollback_btn.set_sensitive(False)
        box.append(self.rollback_btn)

        # Close button
        close_btn = Gtk.Button(label="SCHLIEẞEN")
        close_btn.add_css_class("action-button")
        close_btn.add_css_class("secondary")
        close_btn.connect("clicked", lambda b: self.app.quit())
        box.append(close_btn)

        return box

    def _add_chat_message(self, role: str, content: str):
        """Add a message to the chat."""
        msg_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        msg_box.add_css_class("chat-message")
        msg_box.add_css_class(role)
        msg_box.set_margin_bottom(4)

        # Sender label
        sender = Gtk.Label()
        sender_text = "DU" if role == "user" else "CLAUDE"
        color = "#888899" if role == "user" else "#FF6B00"
        sender.set_markup(
            f"<span font='JetBrains Mono 8' foreground='{color}'>{sender_text}</span>"
        )
        sender.add_css_class("sender")
        sender.set_halign(Gtk.Align.START)
        msg_box.append(sender)

        # Content
        content_label = Gtk.Label()
        # Escape markup and limit length
        safe_content = GLib.markup_escape_text(content[:500])
        content_label.set_markup(
            f"<span font='JetBrains Mono 11'>{safe_content}</span>"
        )
        content_label.set_wrap(True)
        content_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        content_label.set_halign(Gtk.Align.START)
        content_label.set_max_width_chars(50)
        msg_box.append(content_label)

        self.chat_messages.append(msg_box)
        self.chat_history.append({"role": role, "content": content})

    def _on_chat_send(self, widget):
        """Handle chat message send."""
        text = self.chat_input.get_text().strip()
        if not text:
            return

        self.chat_input.set_text("")
        self.chat_input.set_sensitive(False)
        self._add_chat_message("user", text)

        # Process with design proposer in background
        threading.Thread(target=self._process_design_request, args=(text,), daemon=True).start()

    def _process_design_request(self, user_message: str):
        """Process design request with Claude and generate CSS."""
        if not self.design_proposer:
            try:
                from .design_proposer import DesignProposer
                self.design_proposer = DesignProposer()
            except Exception as e:
                GLib.idle_add(
                    self._add_chat_message,
                    "assistant",
                    f"Fehler: {e}"
                )
                GLib.idle_add(self.chat_input.set_sensitive, True)
                return

        try:
            # Refine proposal based on user input
            proposal = self.design_proposer.refine_proposal(user_message)

            # Update UI with proposal
            summary = proposal.get("summary", "Änderungen generiert")
            GLib.idle_add(self._add_chat_message, "assistant", summary)

            # Show CSS diff
            diff = self.design_proposer.get_preview_diff()
            GLib.idle_add(self._update_css_preview, diff)

            # Enable apply button
            GLib.idle_add(self._enable_buttons)

        except Exception as e:
            GLib.idle_add(self._add_chat_message, "assistant", f"Fehler: {e}")

        GLib.idle_add(self.chat_input.set_sensitive, True)

    def _update_css_preview(self, diff: str):
        """Update the CSS preview section."""
        self.css_preview_section.set_visible(True)
        safe_diff = GLib.markup_escape_text(diff[:1000])
        self.css_diff_label.set_markup(
            f"<span font='JetBrains Mono 9' foreground='#00ffff'>{safe_diff}</span>"
        )

    def _enable_buttons(self):
        """Enable action buttons."""
        self.apply_btn.set_sensitive(True)
        self.rollback_btn.set_sensitive(True)

    def _on_apply(self, button):
        """Apply color changes (in background thread)."""
        if not self.design_proposer:
            return

        button.set_sensitive(False)
        self._add_chat_message("assistant", "Wende Änderungen an...")

        def apply_background():
            try:
                success, message = self.design_proposer.apply_changes()
                GLib.idle_add(
                    self._add_chat_message,
                    "assistant",
                    f"{'✓' if success else '✗'} {message}"
                )
                if success:
                    GLib.idle_add(self._update_status, "Farben angewendet - schau auf das Overlay!")
            finally:
                GLib.idle_add(button.set_sensitive, True)

        threading.Thread(target=apply_background, daemon=True).start()

    def _on_rollback(self, button):
        """Rollback color changes (in background thread)."""
        if not self.design_proposer:
            return

        button.set_sensitive(False)

        def rollback_background():
            try:
                success, message = self.design_proposer.rollback()
                GLib.idle_add(
                    self._add_chat_message,
                    "assistant",
                    f"{'✓' if success else '✗'} {message}"
                )
            finally:
                GLib.idle_add(button.set_sensitive, True)

        threading.Thread(target=rollback_background, daemon=True).start()

    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Handle key press events."""
        if keyval == Gdk.KEY_Escape:
            if self.is_testing and self.test_executor:
                try:
                    self.test_executor.stop()
                except Exception:
                    pass
                self._update_status("Test abgebrochen")
            else:
                self.app.quit()
            return True
        return False

    def _start_test(self):
        """Start the autonomous test."""
        self.is_testing = True
        self._update_status(f"Teste {self.duration} Minuten...")

        threading.Thread(target=self._run_test, daemon=True).start()
        return False

    def _run_test(self):
        """Run the test in background."""
        try:
            from .test_executor import TestExecutor

            self.test_executor = TestExecutor(
                duration_minutes=self.duration,
                progress_callback=self._on_test_progress
            )
            result = self.test_executor.run()
            self.test_results = result.to_dict()

            GLib.idle_add(self._show_results)

        except Exception as e:
            LOG.error(f"Test failed: {e}")
            GLib.idle_add(self._update_status, f"Test fehlgeschlagen: {e}")

    def _on_test_progress(self, message: str, progress: float):
        """Handle test progress updates."""
        GLib.idle_add(self._update_progress, message, progress)

    def _update_progress(self, message: str, progress: float):
        """Update progress UI."""
        progress = max(0.0, min(1.0, progress))
        self.progress_bar.set_fraction(progress)
        self.progress_text.set_markup(
            f"<span font='JetBrains Mono 10' foreground='#FF6B00'>{message}</span>"
        )

    def _update_status(self, status: str):
        """Update status label."""
        self.status_label.set_markup(
            f"<span font='JetBrains Mono 9' foreground='#888899'>{status}</span>"
        )

    def _show_results(self):
        """Show test results and enter design mode."""
        self.is_testing = False
        self.is_design_mode = True
        self.progress_section.set_visible(False)
        self.results_section.set_visible(True)

        if self.test_results:
            # Update stats
            self.stats_labels["actions"].set_markup(
                f"<span font='JetBrains Mono Bold 20' foreground='#FF6B00'>"
                f"{self.test_results.get('actions_count', 0)}</span>"
            )
            self.stats_labels["issues"].set_markup(
                f"<span font='JetBrains Mono Bold 20' foreground='#ffaa00'>"
                f"{self.test_results.get('issues_count', 0)}</span>"
            )

            # Show top issues
            for issue in self.test_results.get("issues", [])[:3]:
                issue_label = Gtk.Label()
                safe_issue = GLib.markup_escape_text(issue[:80])
                issue_label.set_markup(
                    f"<span font='JetBrains Mono 9' foreground='#ffaa00'>• {safe_issue}</span>"
                )
                issue_label.add_css_class("issue-item")
                issue_label.set_halign(Gtk.Align.START)
                issue_label.set_wrap(True)
                self.issues_list.append(issue_label)

        self._update_status("Design-Modus - Overlay bleibt sichtbar!")

        # Initialize design proposer and generate initial proposal
        threading.Thread(target=self._generate_initial_proposal, daemon=True).start()

    def _generate_initial_proposal(self):
        """Generate initial design proposal based on test results."""
        try:
            from .design_proposer import DesignProposer
            self.design_proposer = DesignProposer()

            issues = self.test_results.get("issues", []) if self.test_results else []
            observations = self.test_results.get("observations", []) if self.test_results else []
            screenshots = [Path(p) for p in self.test_results.get("screenshots", [])] if self.test_results else []

            proposal = self.design_proposer.generate_css_proposal(issues, observations, screenshots)

            summary = proposal.get("summary", "Analyse abgeschlossen")
            GLib.idle_add(
                self._add_chat_message,
                "assistant",
                f"Test abgeschlossen! Basierend auf der Analyse:\n\n{summary}\n\n"
                "Sag mir was du ändern möchtest, z.B.:\n"
                "• 'Mach die Schrift größer'\n"
                "• 'Mehr Kontrast'\n"
                "• 'Stärkerer Glow-Effekt'"
            )

            diff = self.design_proposer.get_preview_diff()
            if diff and diff != "Keine Änderungen":
                GLib.idle_add(self._update_css_preview, diff)
                GLib.idle_add(self._enable_buttons)

        except Exception as e:
            LOG.error(f"Failed to generate proposal: {e}")
            GLib.idle_add(
                self._add_chat_message,
                "assistant",
                f"Bereit für Design-Änderungen. Was möchtest du anpassen?"
            )


class ResultsApp(Gtk.Application):
    """GTK Application for results popup."""

    def __init__(self, duration: int = 5):
        super().__init__(application_id="com.frank.uitester.results")
        self.duration = duration

    def do_activate(self):
        window = ResultsPopup(self, duration=self.duration)
        window.present()


def main():
    """Main entry point."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=5)
    args = parser.parse_args()

    app = ResultsApp(duration=args.duration)
    app.run(None)


if __name__ == "__main__":
    main()
