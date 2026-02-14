#!/usr/bin/env python3
"""
UI Tester Start Popup - GTK4 window for test duration selection.

Phase 1: User selects test duration (5, 10, or 15 minutes),
then the popup closes and testing begins.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

# Ensure GTK4 is available
os.environ.setdefault("GDK_BACKEND", "x11")

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib

LOG = logging.getLogger("ui_tester.start_popup")

# Paths
TESTER_DIR = Path(__file__).parent
STYLES_DIR = TESTER_DIR / "styles"
CSS_FILE = STYLES_DIR / "tester_cyberpunk.css"


class StartPopup(Gtk.ApplicationWindow):
    """Start popup for UI Tester - duration selection."""

    def __init__(self, app: Gtk.Application):
        super().__init__(application=app, title="UI TESTER // FRANK")
        self.app = app
        self.selected_duration = None

        self._setup_window()
        self._load_css()
        self._build_ui()

    def _setup_window(self):
        """Configure window properties."""
        self.set_default_size(500, 400)
        self.set_resizable(False)

        # Center on screen
        display = Gdk.Display.get_default()
        if display:
            monitor = display.get_monitors().get_item(0)
            if monitor:
                geometry = monitor.get_geometry()
                self.set_default_size(500, 400)

        # Make it float above other windows
        self.set_decorated(True)

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
            LOG.debug("CSS loaded successfully")
        except Exception as e:
            LOG.error(f"Failed to load CSS: {e}")

    def _build_ui(self):
        """Build the user interface."""
        # Main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        main_box.add_css_class("tester-window")
        self.set_child(main_box)

        # Header
        header = self._create_header()
        main_box.append(header)

        # Content area
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        content.set_margin_top(30)
        content.set_margin_bottom(30)
        content.set_margin_start(30)
        content.set_margin_end(30)
        main_box.append(content)

        # Description
        desc_label = Gtk.Label()
        desc_label.set_markup(
            "<span font='JetBrains Mono 12' foreground='#888899'>"
            "Wähle die Testdauer. Der Test startet automatisch\n"
            "und analysiert das Frank Overlay umfassend."
            "</span>"
        )
        desc_label.set_justify(Gtk.Justification.CENTER)
        content.append(desc_label)

        # Duration buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        button_box.set_halign(Gtk.Align.CENTER)
        button_box.set_margin_top(30)
        content.append(button_box)

        durations = [
            (5, "QUICK"),
            (10, "STANDARD"),
            (15, "THOROUGH"),
        ]

        for minutes, label in durations:
            btn = self._create_duration_button(minutes, label)
            button_box.append(btn)

        # Info text
        info_label = Gtk.Label()
        info_label.set_markup(
            "<span font='JetBrains Mono 10' foreground='#555566'>"
            "ESC zum Abbrechen während des Tests"
            "</span>"
        )
        info_label.set_margin_top(30)
        content.append(info_label)

        # Cancel button
        cancel_btn = Gtk.Button(label="ABBRECHEN")
        cancel_btn.add_css_class("action-button")
        cancel_btn.add_css_class("secondary")
        cancel_btn.set_halign(Gtk.Align.CENTER)
        cancel_btn.set_margin_top(20)
        cancel_btn.connect("clicked", self._on_cancel)
        content.append(cancel_btn)

    def _create_header(self) -> Gtk.Box:
        """Create the header section."""
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        header.add_css_class("tester-header")
        header.set_margin_start(20)
        header.set_margin_end(20)
        header.set_margin_top(16)
        header.set_margin_bottom(16)

        # Title
        title = Gtk.Label()
        title.set_markup(
            "<span font='JetBrains Mono Bold 16' foreground='#FF6B00'>"
            "◉ UI TESTER // AUTONOMOUS"
            "</span>"
        )
        title.add_css_class("tester-title")
        title.set_halign(Gtk.Align.START)
        header.append(title)

        # Subtitle
        subtitle = Gtk.Label()
        subtitle.set_markup(
            "<span font='JetBrains Mono 10' foreground='#888899'>"
            "FRANK OVERLAY TESTING SYSTEM v3.0"
            "</span>"
        )
        subtitle.add_css_class("tester-subtitle")
        subtitle.set_halign(Gtk.Align.START)
        header.append(subtitle)

        return header

    def _create_duration_button(self, minutes: int, label: str) -> Gtk.Button:
        """Create a duration selection button."""
        btn = Gtk.Button()
        btn.add_css_class("duration-button")

        # Button content
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        time_label = Gtk.Label()
        time_label.set_markup(
            f"<span font='JetBrains Mono Bold 24' foreground='#FF6B00'>{minutes}</span>"
        )
        box.append(time_label)

        unit_label = Gtk.Label()
        unit_label.set_markup(
            f"<span font='JetBrains Mono 10' foreground='#888899'>MIN</span>"
        )
        box.append(unit_label)

        desc_label = Gtk.Label()
        desc_label.set_markup(
            f"<span font='JetBrains Mono 9' foreground='#555566'>{label}</span>"
        )
        box.append(desc_label)

        btn.set_child(box)
        btn.connect("clicked", self._on_duration_selected, minutes)

        return btn

    def _on_duration_selected(self, button: Gtk.Button, minutes: int):
        """Handle duration selection."""
        self.selected_duration = minutes
        LOG.info(f"Selected duration: {minutes} minutes")

        # Close popup and start test
        self.close()

        # Start the test in a separate process
        GLib.timeout_add(500, self._start_test, minutes)

    def _start_test(self, minutes: int):
        """Start the test executor."""
        test_script = TESTER_DIR / "run_test.py"

        # Create a simple runner script if it doesn't exist
        if not test_script.exists():
            LOG.info("Test will be started via results_popup.py")

        # Start results popup which will run the test
        subprocess.Popen([
            sys.executable,
            str(TESTER_DIR / "results_popup.py"),
            "--duration", str(minutes)
        ], env={**os.environ, "DISPLAY": ":0"})

        # Quit the start app
        self.app.quit()
        return False

    def _on_cancel(self, button: Gtk.Button):
        """Handle cancel button."""
        self.app.quit()


class StartApp(Gtk.Application):
    """GTK Application for start popup."""

    def __init__(self):
        super().__init__(application_id="com.frank.uitester.start")

    def do_activate(self):
        window = StartPopup(self)
        window.present()


def main():
    """Main entry point."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    app = StartApp()
    app.run(None)


if __name__ == "__main__":
    main()
