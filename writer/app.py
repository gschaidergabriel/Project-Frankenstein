#!/usr/bin/env python3
"""
Frank Writer - AI-Native Document & Code Editor
Main Application Entry Point
"""

import sys
import os
import signal
import argparse
import json
from pathlib import Path

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('GtkSource', '5')
from gi.repository import Gtk, Adw, Gio, GLib

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from writer.main_window import FrankWriterWindow
from writer.mode.controller import ModeController
from writer.config.writer_config import WriterConfig


class FrankWriterApp(Adw.Application):
    """Main Frank Writer Application"""

    def __init__(self, initial_context: dict = None):
        super().__init__(
            application_id="org.frank.writer",
            flags=Gio.ApplicationFlags.HANDLES_OPEN
        )
        self.initial_context = initial_context or {}
        self.config = WriterConfig()
        self.mode_controller = None
        self.window = None

        self.connect('activate', self.on_activate)
        self.connect('open', self.on_open)
        self.connect('shutdown', self.on_shutdown)

    def on_activate(self, app):
        if not self.window:
            self.window = FrankWriterWindow(
                application=self,
                config=self.config,
                initial_context=self.initial_context
            )

        self.window.present()
        self.window.maximize()

        if not self.mode_controller:
            self.mode_controller = ModeController()
            self.mode_controller.notify_writer_opening()

    def on_open(self, app, files, n_files, hint):
        self.on_activate(app)
        for gfile in files:
            path = gfile.get_path()
            if path:
                self.window.open_document(path)

    def on_shutdown(self, app):
        if self.mode_controller:
            self.mode_controller.notify_writer_closed()

    def do_startup(self):
        Adw.Application.do_startup(self)
        self._setup_actions()
        self._setup_shortcuts()

    def _setup_actions(self):
        """Setup all application actions"""
        # Simple actions (no parameter)
        simple_actions = [
            ('new', self.on_new),
            ('open', self.on_open_dialog),
            ('save', self.on_save),
            ('save-as', self.on_save_as),
            ('export', self.on_export),
            ('close', self.on_close_document),
            ('quit', self.on_quit),
            ('print', self.on_print),
            ('toggle-mode', self.on_toggle_mode),
            ('run-code', self.on_run_code),
            ('ai-command', self.on_ai_command),
            ('undo', self.on_undo),
            ('redo', self.on_redo),
            ('cut', self.on_cut),
            ('copy', self.on_copy),
            ('paste', self.on_paste),
            ('select-all', self.on_select_all),
            ('find', self.on_find),
            ('find-replace', self.on_find_replace),
            ('toggle-fullscreen', self.on_toggle_fullscreen),
            ('format-bold', self.on_format_bold),
            ('format-italic', self.on_format_italic),
            ('format-underline', self.on_format_underline),
            ('zoom-in', self.on_zoom_in),
            ('zoom-out', self.on_zoom_out),
            ('zoom-reset', self.on_zoom_reset),
            ('focus-mode', self.on_focus_mode),
            ('word-count', self.on_word_count),
            ('preferences', self.on_preferences),
            ('about', self.on_about),
            ('insert-toc', self.on_insert_toc),
            ('insert-pagebreak', self.on_insert_pagebreak),
            ('insert-footnote', self.on_insert_footnote),
            ('version-history', self.on_version_history),
            ('grammar-check', self.on_grammar_check),
        ]

        for name, callback in simple_actions:
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', callback)
            self.add_action(action)

        # Action with string parameter (open-recent)
        open_recent_action = Gio.SimpleAction.new(
            'open-recent', GLib.VariantType.new('s')
        )
        open_recent_action.connect('activate', self.on_open_recent)
        self.add_action(open_recent_action)

    def _setup_shortcuts(self):
        """Setup all keyboard shortcuts"""
        shortcuts = {
            'app.new': ['<Control>n'],
            'app.open': ['<Control>o'],
            'app.save': ['<Control>s'],
            'app.save-as': ['<Control><Shift>s'],
            'app.export': ['<Control>e'],
            'app.close': ['<Control>w'],
            'app.quit': ['<Control>q'],
            'app.print': ['<Control>p'],
            'app.toggle-mode': ['<Control>m'],
            'app.run-code': ['F5'],
            'app.ai-command': ['<Control>k'],
            'app.undo': ['<Control>z'],
            'app.redo': ['<Control><Shift>z'],
            'app.cut': ['<Control>x'],
            'app.copy': ['<Control>c'],
            'app.paste': ['<Control>v'],
            'app.select-all': ['<Control>a'],
            'app.find': ['<Control>f'],
            'app.find-replace': ['<Control>h'],
            'app.toggle-fullscreen': ['F11'],
            'app.format-bold': ['<Control>b'],
            'app.format-italic': ['<Control>i'],
            'app.format-underline': ['<Control>u'],
            'app.zoom-in': ['<Control>plus', '<Control>equal'],
            'app.zoom-out': ['<Control>minus'],
            'app.zoom-reset': ['<Control>0'],
            'app.focus-mode': ['<Control><Shift>f'],
        }

        for action, accels in shortcuts.items():
            self.set_accels_for_action(action, accels)

    # ── Action handlers ───────────────────────────────────

    def on_new(self, action, param):
        if self.window:
            self.window.new_document()

    def on_open_dialog(self, action, param):
        if self.window:
            self.window.show_open_dialog()

    def on_open_recent(self, action, param):
        if self.window and param:
            path = param.get_string()
            if path:
                self.window.open_document(path)

    def on_save(self, action, param):
        if self.window:
            self.window.save_document()

    def on_save_as(self, action, param):
        if self.window:
            self.window.save_document_as()

    def on_export(self, action, param):
        if self.window:
            self.window.show_export_dialog()

    def on_close_document(self, action, param):
        if self.window:
            self.window.close_current_document()

    def on_quit(self, action, param):
        if self.window:
            self.window.request_close()

    def on_print(self, action, param):
        if self.window:
            self.window.print_document()

    def on_toggle_mode(self, action, param):
        if self.window:
            self.window.toggle_mode()

    def on_run_code(self, action, param):
        if self.window:
            self.window.run_code()

    def on_ai_command(self, action, param):
        if self.window:
            self.window.show_ai_command_palette()

    def on_undo(self, action, param):
        if self.window:
            self.window.undo()

    def on_redo(self, action, param):
        if self.window:
            self.window.redo()

    def on_cut(self, action, param):
        if self.window:
            self.window.cut_selection()

    def on_copy(self, action, param):
        if self.window:
            self.window.copy_selection()

    def on_paste(self, action, param):
        if self.window:
            self.window.paste_clipboard()

    def on_select_all(self, action, param):
        if self.window:
            self.window.select_all()

    def on_find(self, action, param):
        if self.window:
            self.window.show_find()

    def on_find_replace(self, action, param):
        if self.window:
            self.window.show_find_replace()

    def on_toggle_fullscreen(self, action, param):
        if self.window:
            if self.window.is_fullscreen():
                self.window.unfullscreen()
            else:
                self.window.fullscreen()

    def on_format_bold(self, action, param):
        if self.window and self.window.current_mode == 'writer':
            self.window.formatting_toolbar.apply_bold()

    def on_format_italic(self, action, param):
        if self.window and self.window.current_mode == 'writer':
            self.window.formatting_toolbar.apply_italic()

    def on_format_underline(self, action, param):
        if self.window and self.window.current_mode == 'writer':
            self.window.formatting_toolbar.apply_underline()

    def on_zoom_in(self, action, param):
        if self.window:
            self.window.zoom_in()

    def on_zoom_out(self, action, param):
        if self.window:
            self.window.zoom_out()

    def on_zoom_reset(self, action, param):
        if self.window:
            self.window.zoom_reset()

    def on_focus_mode(self, action, param):
        if self.window:
            self.window.toggle_focus_mode()

    def on_word_count(self, action, param):
        if self.window:
            self.window.show_word_count_dialog()

    def on_preferences(self, action, param):
        if self.window:
            self.window.show_preferences()

    def on_insert_toc(self, action, param):
        if self.window:
            self.window._insert_toc()

    def on_insert_pagebreak(self, action, param):
        if self.window:
            self.window._insert_pagebreak()

    def on_insert_footnote(self, action, param):
        if self.window:
            self.window._insert_footnote()

    def on_version_history(self, action, param):
        if self.window:
            self.window.show_version_history()

    def on_grammar_check(self, action, param):
        if self.window:
            self.window.grammar_check()

    def on_about(self, action, param):
        about = Adw.AboutWindow(
            application_name="Frank Writer",
            application_icon="org.frank.writer",
            developer_name="Frank AI System",
            version="2.0.0",
            developers=["Frank AI Core Team"],
            copyright="2026 Frank AI System",
            license_type=Gtk.License.MIT_X11,
            comments="AI-Native Document & Code Editor\n\nLocal. Private. Intelligent.",
            website="https://frank.local",
        )
        about.set_transient_for(self.window)
        about.present()


def parse_args():
    parser = argparse.ArgumentParser(description='Frank Writer')
    parser.add_argument('files', nargs='*', help='Files to open')
    parser.add_argument('--no-fullscreen', action='store_true', default=False)
    parser.add_argument('--context', type=str, default='{}')
    parser.add_argument('--mode', choices=['writer', 'coding'], default='writer')
    return parser.parse_args()


def main():
    args = parse_args()

    try:
        initial_context = json.loads(args.context)
    except json.JSONDecodeError:
        initial_context = {}

    initial_context['fullscreen'] = not args.no_fullscreen
    initial_context['mode'] = args.mode

    app = FrankWriterApp(initial_context=initial_context)

    def on_sigint():
        app.quit()
        return GLib.SOURCE_REMOVE

    GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGINT, on_sigint)

    if args.files:
        app.run([sys.argv[0]] + args.files)
    else:
        app.run(sys.argv[:1])


if __name__ == '__main__':
    main()
