"""
Frank Writer Main Window
GTK4 + Libadwaita Main Application Window
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('GtkSource', '5')
from gi.repository import Gtk, Adw, Gio, GLib, Gdk, GtkSource, Pango

import json
import threading
from pathlib import Path
from typing import Optional
from datetime import datetime

from writer.editor.source_view import WriterSourceView
from writer.editor.document import Document
from writer.editor.find_replace import FindReplaceBar
from writer.sidebar.sidebar_manager import SidebarManager
from writer.ai.bridge import FrankBridge
from writer.preview.popup_window import LivePreviewPopup
from writer.ui.dialogs.export_dialog import ExportDialog
from writer.ui.dialogs.ai_command_dialog import AICommandDialog
from writer.ui.dialogs.preferences_dialog import PreferencesDialog
from writer.ui.dialogs.word_count_dialog import WordCountDialog
from writer.editor.formatting_toolbar import FormattingToolbar
from writer.editor.spell_checker import SpellChecker
from writer.editor.version_history import VersionHistory


class FrankWriterWindow(Adw.ApplicationWindow):
    """Main Frank Writer Window"""

    AUTOSAVE_DIR = Path.home() / ".local" / "share" / "frank" / "writer" / "autosave"
    RECENT_FILES_PATH = Path.home() / ".config" / "frank" / "writer" / "recent_files.json"
    MAX_RECENT = 25

    def __init__(self, application, config, initial_context=None):
        super().__init__(application=application)
        self.config = config
        self.initial_context = initial_context or {}
        self.current_mode = initial_context.get('mode', 'writer')
        self.documents = []
        self.current_document = None
        self.preview_popup = None
        self.frank_bridge = FrankBridge(config.ai)
        self._theme_css_provider = None
        self._zoom_level = 100  # percent
        self._zoom_css_provider = None
        self._autosave_timer_id = None
        self._focus_mode = False
        self._recent_files = self._load_recent_files()
        self._spell_checker = SpellChecker(language=config.save_config.spell_language)
        self._version_history = VersionHistory()
        self._footnote_counter = 0

        self._setup_window()
        self._build_ui()
        self._connect_signals()
        self._apply_theme()
        self._start_autosave()
        self._check_recovery()

        # Create initial document
        GLib.idle_add(self._create_initial_document)

    def _setup_window(self):
        """Setup window properties"""
        self.set_title("Frank Writer")
        self.set_default_size(800, 500)

        # Enable drag and drop for files
        drop_target = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)
        drop_target.connect('drop', self._on_file_dropped)
        self.add_controller(drop_target)

        # Enable drag and drop for text (P3-39)
        text_drop = Gtk.DropTarget.new(str, Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        text_drop.connect('drop', self._on_text_dropped)
        self.add_controller(text_drop)

        # Zoom with Ctrl+Scroll
        scroll_ctrl = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.VERTICAL
        )
        scroll_ctrl.connect('scroll', self._on_scroll)
        self.add_controller(scroll_ctrl)

    def _build_ui(self):
        """Build the main UI"""
        self.header = self._create_header_bar()

        # Content area with sidebar and editor
        self.content_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.content_paned.set_position(260)
        self.content_paned.set_shrink_start_child(True)
        self.content_paned.set_shrink_end_child(True)
        self.content_paned.set_vexpand(True)

        # Adw.ToolbarView: header as top bar, paned as content
        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(self.header)
        toolbar_view.set_content(self.content_paned)
        self.set_content(toolbar_view)

        # Sidebar
        self.sidebar = SidebarManager(
            config=self.config,
            frank_bridge=self.frank_bridge,
            on_action=self._handle_sidebar_action
        )
        self.content_paned.set_start_child(self.sidebar)

        # Editor area
        self.editor_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.content_paned.set_end_child(self.editor_box)

        # Mode toggle bar
        self.mode_bar = self._create_mode_bar()
        self.editor_box.append(self.mode_bar)

        # Formatting toolbar (Writer mode only)
        self.formatting_toolbar = FormattingToolbar(
            get_editor_callback=self._get_current_editor
        )
        self.formatting_toolbar.set_visible(self.current_mode == 'writer')
        self.editor_box.append(self.formatting_toolbar)

        # Find & Replace bar (hidden by default)
        self.find_replace_bar = FindReplaceBar(
            get_editor_callback=self._get_current_editor
        )
        self.editor_box.append(self.find_replace_bar)

        # Editor notebook (for tabs)
        self.editor_notebook = Gtk.Notebook()
        self.editor_notebook.set_scrollable(True)
        self.editor_notebook.set_show_border(False)
        self.editor_notebook.set_vexpand(True)
        self.editor_notebook.set_hexpand(True)
        self.editor_box.append(self.editor_notebook)

        # Status bar
        self.status_bar = self._create_status_bar()
        self.editor_box.append(self.status_bar)

    def _create_header_bar(self) -> Adw.HeaderBar:
        """Create the header bar"""
        header = Adw.HeaderBar()

        # Left side - file operations
        new_btn = Gtk.Button(icon_name="document-new-symbolic")
        new_btn.set_tooltip_text("Neues Dokument (Ctrl+N)")
        new_btn.set_action_name("app.new")
        header.pack_start(new_btn)

        open_btn = Gtk.Button(icon_name="document-open-symbolic")
        open_btn.set_tooltip_text("Öffnen (Ctrl+O)")
        open_btn.set_action_name("app.open")
        header.pack_start(open_btn)

        save_btn = Gtk.Button(icon_name="document-save-symbolic")
        save_btn.set_tooltip_text("Speichern (Ctrl+S)")
        save_btn.set_action_name("app.save")
        header.pack_start(save_btn)

        print_btn = Gtk.Button(icon_name="printer-symbolic")
        print_btn.set_tooltip_text("Drucken (Ctrl+P)")
        print_btn.set_action_name("app.print")
        header.pack_start(print_btn)

        # Title widget
        self.title_widget = Adw.WindowTitle(
            title="Frank Writer",
            subtitle="Neues Dokument"
        )
        header.set_title_widget(self.title_widget)

        # Right side - actions
        export_btn = Gtk.Button(icon_name="document-send-symbolic")
        export_btn.set_tooltip_text("Exportieren (Ctrl+E)")
        export_btn.set_action_name("app.export")
        header.pack_end(export_btn)

        # Menu button
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu_btn.set_tooltip_text("Menü")
        menu_btn.set_menu_model(self._create_app_menu())
        header.pack_end(menu_btn)

        return header

    def _create_mode_bar(self) -> Gtk.Box:
        """Create the mode toggle bar"""
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.set_margin_start(6)
        bar.set_margin_end(6)
        bar.set_margin_top(6)
        bar.set_margin_bottom(6)
        bar.add_css_class("toolbar")

        # Mode toggle buttons
        self.writer_mode_btn = Gtk.ToggleButton(label="Writer")
        self.writer_mode_btn.set_active(self.current_mode == 'writer')
        self.writer_mode_btn.connect('toggled', self._on_mode_toggled, 'writer')
        bar.append(self.writer_mode_btn)

        self.coding_mode_btn = Gtk.ToggleButton(label="Coding")
        self.coding_mode_btn.set_active(self.current_mode == 'coding')
        self.coding_mode_btn.connect('toggled', self._on_mode_toggled, 'coding')
        bar.append(self.coding_mode_btn)

        # Group toggle buttons
        self.coding_mode_btn.set_group(self.writer_mode_btn)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        bar.append(spacer)

        # Zoom controls
        zoom_out_btn = Gtk.Button(icon_name="zoom-out-symbolic")
        zoom_out_btn.set_tooltip_text("Verkleinern (Ctrl+-)")
        zoom_out_btn.connect('clicked', lambda b: self.zoom_out())
        bar.append(zoom_out_btn)

        self.zoom_label = Gtk.Label(label="100%")
        self.zoom_label.set_width_chars(5)
        self.zoom_label.add_css_class("dim-label")
        bar.append(self.zoom_label)

        zoom_in_btn = Gtk.Button(icon_name="zoom-in-symbolic")
        zoom_in_btn.set_tooltip_text("Vergrößern (Ctrl++)")
        zoom_in_btn.connect('clicked', lambda b: self.zoom_in())
        bar.append(zoom_in_btn)

        zoom_reset_btn = Gtk.Button(icon_name="zoom-original-symbolic")
        zoom_reset_btn.set_tooltip_text("Zoom zurücksetzen (Ctrl+0)")
        zoom_reset_btn.connect('clicked', lambda b: self.zoom_reset())
        bar.append(zoom_reset_btn)

        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # Run button (coding mode only)
        self.run_btn = Gtk.Button()
        run_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        run_box.append(Gtk.Image.new_from_icon_name("media-playback-start-symbolic"))
        run_box.append(Gtk.Label(label="Run"))
        self.run_btn.set_child(run_box)
        self.run_btn.add_css_class("suggested-action")
        self.run_btn.set_tooltip_text("Code ausführen (F5)")
        self.run_btn.connect('clicked', lambda b: self.run_code())
        self.run_btn.set_visible(self.current_mode == 'coding')
        bar.append(self.run_btn)

        # AI Command button
        ai_btn = Gtk.Button(icon_name="system-search-symbolic")
        ai_btn.set_tooltip_text("AI-Befehl (Ctrl+K)")
        ai_btn.connect('clicked', lambda b: self.show_ai_command_palette())
        bar.append(ai_btn)

        # Focus mode toggle
        self.focus_btn = Gtk.ToggleButton(icon_name="view-fullscreen-symbolic")
        self.focus_btn.set_tooltip_text("Fokus-Modus")
        self.focus_btn.connect('toggled', self._on_focus_toggled)
        bar.append(self.focus_btn)

        # Settings button
        settings_btn = Gtk.Button(icon_name="emblem-system-symbolic")
        settings_btn.set_tooltip_text("Einstellungen")
        settings_btn.connect('clicked', lambda b: self.show_preferences())
        bar.append(settings_btn)

        return bar

    def _create_status_bar(self) -> Gtk.Box:
        """Create the status bar"""
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bar.set_margin_start(12)
        bar.set_margin_end(12)
        bar.set_margin_top(4)
        bar.set_margin_bottom(4)
        bar.add_css_class("statusbar")

        # Word/Line count (clickable for detail dialog)
        word_count_btn = Gtk.Button()
        word_count_btn.add_css_class("flat")
        self.word_count_label = Gtk.Label(label="0 Wörter")
        self.word_count_label.add_css_class("dim-label")
        word_count_btn.set_child(self.word_count_label)
        word_count_btn.connect('clicked', lambda b: self.show_word_count_dialog())
        bar.append(word_count_btn)

        # Separator
        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # Cursor position
        self.cursor_pos_label = Gtk.Label(label="Zeile 1, Spalte 1")
        self.cursor_pos_label.add_css_class("dim-label")
        bar.append(self.cursor_pos_label)

        # Separator
        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # Language/Schema
        self.language_label = Gtk.Label(label="Text")
        self.language_label.add_css_class("dim-label")
        bar.append(self.language_label)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        bar.append(spacer)

        # Zoom indicator
        self.zoom_status_label = Gtk.Label(label="100%")
        self.zoom_status_label.add_css_class("dim-label")
        bar.append(self.zoom_status_label)

        bar.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # Mode indicator
        self.mode_label = Gtk.Label(label="Writer")
        self.mode_label.add_css_class("dim-label")
        bar.append(self.mode_label)

        # Modified indicator
        self.modified_indicator = Gtk.Label(label="")
        bar.append(self.modified_indicator)

        return bar

    def _create_app_menu(self) -> Gio.Menu:
        """Create application menu"""
        menu = Gio.Menu()

        # File section
        file_section = Gio.Menu()
        file_section.append("Neu", "app.new")
        file_section.append("Öffnen...", "app.open")

        # Recent files submenu
        recent_section = Gio.Menu()
        for path in self._recent_files[:10]:
            name = Path(path).name
            # Use detailed action with target to pass file path
            recent_section.append(name, f"app.open-recent::{path}")
        if self._recent_files:
            file_section.append_submenu("Zuletzt geöffnet", recent_section)

        file_section.append("Speichern", "app.save")
        file_section.append("Speichern unter...", "app.save-as")
        file_section.append("Exportieren...", "app.export")
        file_section.append("Drucken...", "app.print")
        menu.append_section("Datei", file_section)

        # Edit section
        edit_section = Gio.Menu()
        edit_section.append("Suchen...", "app.find")
        edit_section.append("Suchen & Ersetzen...", "app.find-replace")
        edit_section.append("AI-Befehl...", "app.ai-command")
        edit_section.append("Modus wechseln", "app.toggle-mode")
        edit_section.append("Wörter zählen...", "app.word-count")
        menu.append_section("Bearbeiten", edit_section)

        # Insert section
        insert_section = Gio.Menu()
        insert_section.append("Inhaltsverzeichnis", "app.insert-toc")
        insert_section.append("Seitenumbruch", "app.insert-pagebreak")
        insert_section.append("Fußnote", "app.insert-footnote")
        menu.append_section("Einfügen", insert_section)

        # Tools section
        tools_section = Gio.Menu()
        tools_section.append("Versionsverlauf...", "app.version-history")
        tools_section.append("Grammatik prüfen", "app.grammar-check")
        menu.append_section("Werkzeuge", tools_section)

        # View section
        view_section = Gio.Menu()
        view_section.append("Vergrößern", "app.zoom-in")
        view_section.append("Verkleinern", "app.zoom-out")
        view_section.append("Zoom zurücksetzen", "app.zoom-reset")
        view_section.append("Fokus-Modus", "app.focus-mode")
        menu.append_section("Ansicht", view_section)

        # App section
        app_section = Gio.Menu()
        app_section.append("Einstellungen", "app.preferences")
        app_section.append("Über", "app.about")
        app_section.append("Beenden", "app.quit")
        menu.append_section(None, app_section)

        return menu

    def _connect_signals(self):
        """Connect window signals"""
        self.connect('close-request', self._on_close_request)
        self.editor_notebook.connect('switch-page', self._on_page_switched)

    def _apply_theme(self):
        """Apply current theme (removes old provider first to avoid CSS leak)"""
        display = Gdk.Display.get_default()

        # Remove previous provider to prevent CSS rule accumulation
        if self._theme_css_provider is not None:
            Gtk.StyleContext.remove_provider_for_display(
                display, self._theme_css_provider
            )

        self._theme_css_provider = Gtk.CssProvider()
        theme_css = self.config.get_theme_css(self.current_mode)

        if theme_css.exists():
            self._theme_css_provider.load_from_path(str(theme_css))
            Gtk.StyleContext.add_provider_for_display(
                display,
                self._theme_css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def _create_initial_document(self):
        """Create initial document"""
        self.new_document()
        return False

    # ── Document operations ───────────────────────────────

    def new_document(self, schema_type: str = None):
        """Create a new document"""
        doc = Document(schema_type=schema_type)
        self._add_document(doc)

    def open_document(self, path: str):
        """Open a document from path"""
        path = Path(path)
        try:
            doc = Document.from_file(path)
            self._add_document(doc)
            self._add_to_recent(str(path))
        except FileNotFoundError:
            self._show_error(f"Datei nicht gefunden: {path}")
        except PermissionError:
            self._show_error(f"Zugriff verweigert: {path}")
        except Exception as e:
            self._show_error(f"Fehler beim Öffnen: {e}")

    def _add_document(self, doc: Document):
        """Add document to editor"""
        self.documents.append(doc)

        # Create editor view
        editor = WriterSourceView(
            document=doc,
            config=self.config,
            mode=self.current_mode
        )
        editor.connect_signals(
            on_modified=self._on_document_modified,
            on_cursor_moved=self._on_cursor_moved
        )

        # Setup context menu on editor
        self._setup_editor_context_menu(editor)

        # Attach spell checker (Writer mode)
        if self.current_mode == 'writer' and self.config.save_config.spell_check_enabled:
            self._spell_checker.attach(editor)
            self._spell_checker.enable()

        # Create scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_child(editor)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        # Create tab label
        tab_label = self._create_tab_label(doc)

        # Add to notebook
        page_num = self.editor_notebook.append_page(scrolled, tab_label)
        self.editor_notebook.set_current_page(page_num)

        self.current_document = doc
        self.sidebar.set_document(doc)
        self._update_ui()

    def _setup_editor_context_menu(self, editor):
        """Setup right-click context menu on editor."""
        gesture = Gtk.GestureClick.new()
        gesture.set_button(3)  # Right click
        gesture.connect('pressed', self._on_editor_right_click, editor)
        editor.add_controller(gesture)

    def _on_editor_right_click(self, gesture, n_press, x, y, editor):
        """Show context menu on right-click."""
        menu = Gio.Menu()

        edit_section = Gio.Menu()
        edit_section.append("Rückgängig", "app.undo")
        edit_section.append("Wiederholen", "app.redo")
        menu.append_section(None, edit_section)

        clipboard_section = Gio.Menu()
        clipboard_section.append("Ausschneiden", "app.cut")
        clipboard_section.append("Kopieren", "app.copy")
        clipboard_section.append("Einfügen", "app.paste")
        clipboard_section.append("Alles auswählen", "app.select-all")
        menu.append_section(None, clipboard_section)

        find_section = Gio.Menu()
        find_section.append("Suchen...", "app.find")
        find_section.append("Suchen & Ersetzen...", "app.find-replace")
        menu.append_section(None, find_section)

        if self.current_mode == 'writer':
            format_section = Gio.Menu()
            format_section.append("Fett", "app.format-bold")
            format_section.append("Kursiv", "app.format-italic")
            format_section.append("Unterstrichen", "app.format-underline")
            menu.append_section("Format", format_section)

        ai_section = Gio.Menu()
        ai_section.append("AI-Befehl...", "app.ai-command")
        menu.append_section(None, ai_section)

        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(editor)
        rect = Gdk.Rectangle()
        rect.x = int(x)
        rect.y = int(y)
        rect.width = 1
        rect.height = 1
        popover.set_pointing_to(rect)
        popover.popup()

    def _create_tab_label(self, doc: Document) -> Gtk.Box:
        """Create tab label with close button"""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        label = Gtk.Label(label=doc.title)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_max_width_chars(20)
        box.append(label)

        close_btn = Gtk.Button(icon_name="window-close-symbolic")
        close_btn.add_css_class("flat")
        close_btn.add_css_class("circular")
        close_btn.connect('clicked', lambda b: self._close_document(doc))
        box.append(close_btn)

        # Store reference for updates
        doc._tab_label = label

        return box

    def save_document(self):
        """Save current document"""
        if not self.current_document:
            return

        # Auto-snapshot before save (P3-32)
        self._save_version_snapshot(label="Vor Speichern")

        if self.current_document.file_path:
            self.current_document.save()
            self._add_to_recent(str(self.current_document.file_path))
            self._update_ui()
        else:
            self.save_document_as()

    def save_document_as(self):
        """Save document with new name"""
        if not self.current_document:
            return

        dialog = Gtk.FileDialog()
        dialog.set_title("Speichern unter")
        dialog.save(self, None, self._on_save_dialog_response)

    def _on_save_dialog_response(self, dialog, result):
        """Handle save dialog response"""
        try:
            file = dialog.save_finish(result)
            if file:
                path = Path(file.get_path())
                self.current_document.save(path)
                self._add_to_recent(str(path))
                self._update_ui()
        except GLib.Error:
            pass  # Cancelled

    def close_current_document(self):
        """Close current document"""
        if self.current_document:
            self._close_document(self.current_document)

    def _close_document(self, doc: Document):
        """Close a specific document"""
        if doc.is_modified:
            self._ask_save_before_close(doc)
        else:
            self._remove_document(doc)

    def _remove_document(self, doc: Document):
        """Remove document from editor"""
        try:
            idx = self.documents.index(doc)
        except ValueError:
            return
        self.documents.remove(doc)
        self.editor_notebook.remove_page(idx)

        if self.documents:
            self.current_document = self.documents[-1]
        else:
            self.current_document = None
            self.new_document()

        self._update_ui()

    def _ask_save_before_close(self, doc: Document):
        """Ask user to save before closing"""
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Änderungen speichern?",
            body=f"'{doc.title}' hat ungespeicherte Änderungen."
        )
        dialog.add_response("discard", "Verwerfen")
        dialog.add_response("cancel", "Abbrechen")
        dialog.add_response("save", "Speichern")
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.connect('response', self._on_save_dialog_response_close, doc)
        dialog.present()

    def _on_save_dialog_response_close(self, dialog, response, doc):
        """Handle save dialog response for close"""
        if response == "save":
            if doc.file_path:
                doc.save()
                self._remove_document(doc)
            else:
                self._save_then_remove(doc)
        elif response == "discard":
            self._remove_document(doc)

    def _save_then_remove(self, doc: Document):
        """Save As dialog that removes the document only after save succeeds."""
        file_dialog = Gtk.FileDialog()
        file_dialog.set_title("Speichern unter")
        file_dialog.save(self, None, self._on_save_then_remove_response, doc)

    def _on_save_then_remove_response(self, file_dialog, result, doc):
        """Callback: save finished -> now remove the document."""
        try:
            file = file_dialog.save_finish(result)
            if file:
                path = Path(file.get_path())
                doc.save(path)
                self._remove_document(doc)
                self._update_ui()
        except GLib.Error:
            pass  # Cancelled - document stays open

    # ── Mode operations ───────────────────────────────────

    def toggle_mode(self):
        """Toggle between Writer and Coding mode"""
        if self.current_mode == 'writer':
            self.set_mode('coding')
        else:
            self.set_mode('writer')

    def set_mode(self, mode: str):
        """Set current mode"""
        self.current_mode = mode

        if mode == 'writer':
            if not self.writer_mode_btn.get_active():
                self.writer_mode_btn.set_active(True)
        else:
            if not self.coding_mode_btn.get_active():
                self.coding_mode_btn.set_active(True)

        self.run_btn.set_visible(mode == 'coding')
        self.mode_label.set_label(f"{mode.title()}")
        self.formatting_toolbar.set_visible(mode == 'writer')
        self._apply_theme()
        self.sidebar.set_mode(mode)

        for i in range(self.editor_notebook.get_n_pages()):
            page = self.editor_notebook.get_nth_page(i)
            if page is None:
                continue
            editor = page.get_child()
            if editor is not None and isinstance(editor, WriterSourceView):
                editor.set_mode(mode)

    def _on_mode_toggled(self, button, mode):
        if button.get_active():
            self.set_mode(mode)

    # ── Find & Replace ────────────────────────────────────

    def show_find(self):
        """Show find bar (Ctrl+F)"""
        self.find_replace_bar.show_find()

    def show_find_replace(self):
        """Show find & replace bar (Ctrl+H)"""
        self.find_replace_bar.show_find_replace()

    # ── Zoom ──────────────────────────────────────────────

    def zoom_in(self):
        """Zoom in by 10%"""
        self._set_zoom(min(200, self._zoom_level + 10))

    def zoom_out(self):
        """Zoom out by 10%"""
        self._set_zoom(max(50, self._zoom_level - 10))

    def zoom_reset(self):
        """Reset zoom to 100%"""
        self._set_zoom(100)

    def _set_zoom(self, level: int):
        """Apply zoom level via CSS."""
        self._zoom_level = level
        self.zoom_label.set_label(f"{level}%")
        self.zoom_status_label.set_label(f"{level}%")

        # Scale font size
        base_size = self.config.editor.font_size
        scaled = base_size * level / 100.0

        display = Gdk.Display.get_default()
        if self._zoom_css_provider:
            Gtk.StyleContext.remove_provider_for_display(display, self._zoom_css_provider)

        self._zoom_css_provider = Gtk.CssProvider()
        css = f"textview {{ font-size: {scaled:.1f}pt; }} textview text {{ font-size: {scaled:.1f}pt; }}"
        self._zoom_css_provider.load_from_string(css)
        Gtk.StyleContext.add_provider_for_display(
            display, self._zoom_css_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER
        )

    def _on_scroll(self, controller, dx, dy):
        """Handle Ctrl+Scroll for zoom."""
        state = controller.get_current_event_state()
        if state & Gdk.ModifierType.CONTROL_MASK:
            if dy < 0:
                self.zoom_in()
            elif dy > 0:
                self.zoom_out()
            return True
        return False

    # ── Focus Mode ────────────────────────────────────────

    def toggle_focus_mode(self):
        """Toggle focus mode (hide sidebar, toolbar, statusbar)."""
        self._focus_mode = not self._focus_mode
        self.focus_btn.set_active(self._focus_mode)
        self._apply_focus_mode()

    def _on_focus_toggled(self, btn):
        self._focus_mode = btn.get_active()
        self._apply_focus_mode()

    def _apply_focus_mode(self):
        show = not self._focus_mode
        self.sidebar.set_visible(show)
        self.mode_bar.set_visible(show)
        self.formatting_toolbar.set_visible(show and self.current_mode == 'writer')
        self.status_bar.set_visible(show)

    # ── Print ─────────────────────────────────────────────

    def print_document(self):
        """Print current document using GTK print dialog."""
        if not self.current_document:
            return

        print_op = Gtk.PrintOperation()
        print_op.set_n_pages(1)  # Will be calculated in begin-print
        print_op.connect('begin-print', self._on_begin_print)
        print_op.connect('draw-page', self._on_draw_page)
        print_op.set_use_full_page(False)
        print_op.set_unit(Gtk.Unit.POINTS)

        try:
            print_op.run(Gtk.PrintOperationAction.PRINT_DIALOG, self)
        except Exception as e:
            self._show_error(f"Druckfehler: {e}")

    def _on_begin_print(self, operation, context):
        """Calculate number of pages for printing."""
        if not self.current_document:
            return

        width = context.get_width()
        height = context.get_height()

        # Create Pango layout
        layout = context.create_pango_layout()
        layout.set_font_description(Pango.FontDescription.from_string("Serif 11"))
        layout.set_width(int(width * Pango.SCALE))
        layout.set_text(self.current_document.content, -1)

        # Calculate pages
        num_lines = layout.get_line_count()
        line_height = layout.get_pixel_size()[1] / max(num_lines, 1)
        lines_per_page = max(1, int(height / line_height))
        n_pages = max(1, (num_lines + lines_per_page - 1) // lines_per_page)

        operation.set_n_pages(n_pages)
        self._print_layout = layout
        self._print_lines_per_page = lines_per_page

    def _on_draw_page(self, operation, context, page_nr):
        """Draw a single page for printing with header/footer (P3-35)."""
        if not hasattr(self, '_print_layout'):
            return

        cr = context.get_cairo_context()
        layout = self._print_layout
        width = context.get_width()
        height = context.get_height()

        from gi.repository import PangoCairo

        # ── Header ──
        header_layout = context.create_pango_layout()
        header_layout.set_font_description(Pango.FontDescription.from_string("Sans 8"))
        header_layout.set_width(int(width * Pango.SCALE))
        title = self.current_document.title if self.current_document else "Frank Writer"
        header_layout.set_text(title, -1)
        cr.set_source_rgb(0.4, 0.4, 0.4)
        cr.move_to(0, 0)
        PangoCairo.show_layout(cr, header_layout)

        # Header separator line
        header_h = header_layout.get_pixel_size()[1] + 4
        cr.set_line_width(0.5)
        cr.move_to(0, header_h)
        cr.line_to(width, header_h)
        cr.stroke()

        # ── Content ──
        content_y = header_h + 8
        start_line = page_nr * self._print_lines_per_page
        end_line = min(start_line + self._print_lines_per_page, layout.get_line_count())

        cr.set_source_rgb(0, 0, 0)
        y_offset = content_y

        for i in range(start_line, end_line):
            layout_line = layout.get_line_readonly(i)
            if layout_line is None:
                continue
            ink_rect, logical_rect = layout_line.get_pixel_extents()
            cr.move_to(0, y_offset)
            PangoCairo.show_layout_line(cr, layout_line)
            y_offset += logical_rect.height

        # ── Footer ──
        n_pages = operation.get_property("n-pages")
        footer_layout = context.create_pango_layout()
        footer_layout.set_font_description(Pango.FontDescription.from_string("Sans 8"))
        footer_layout.set_width(int(width * Pango.SCALE))
        footer_layout.set_alignment(Pango.Alignment.CENTER)
        footer_layout.set_text(f"Seite {page_nr + 1} von {n_pages}", -1)
        footer_h = footer_layout.get_pixel_size()[1]

        cr.set_source_rgb(0.4, 0.4, 0.4)
        # Footer separator line
        footer_y = height - footer_h - 4
        cr.set_line_width(0.5)
        cr.move_to(0, footer_y)
        cr.line_to(width, footer_y)
        cr.stroke()

        cr.move_to(0, footer_y + 4)
        PangoCairo.show_layout(cr, footer_layout)

    # ── Undo/Redo ─────────────────────────────────────────

    def undo(self):
        editor = self._get_current_editor()
        if editor:
            editor.undo()

    def redo(self):
        editor = self._get_current_editor()
        if editor:
            editor.redo()

    # ── Clipboard ─────────────────────────────────────────

    def cut_selection(self):
        editor = self._get_current_editor()
        if editor:
            clipboard = Gdk.Display.get_default().get_clipboard()
            text = editor.get_selected_text()
            if text:
                clipboard.set(text)
                editor.buffer.delete_selection(True, True)

    def copy_selection(self):
        editor = self._get_current_editor()
        if editor:
            clipboard = Gdk.Display.get_default().get_clipboard()
            text = editor.get_selected_text()
            if text:
                clipboard.set(text)

    def paste_clipboard(self):
        editor = self._get_current_editor()
        if editor:
            clipboard = Gdk.Display.get_default().get_clipboard()
            clipboard.read_text_async(None, self._on_paste_text)

    def _on_paste_text(self, clipboard, result):
        try:
            text = clipboard.read_text_finish(result)
            if text:
                editor = self._get_current_editor()
                if editor:
                    editor.buffer.delete_selection(True, True)
                    editor.buffer.insert_at_cursor(text)
        except Exception:
            pass

    def select_all(self):
        editor = self._get_current_editor()
        if editor:
            start = editor.buffer.get_start_iter()
            end = editor.buffer.get_end_iter()
            editor.buffer.select_range(start, end)

    def _get_current_editor(self):
        """Get the current WriterSourceView"""
        page_num = self.editor_notebook.get_current_page()
        if page_num < 0:
            return None
        page = self.editor_notebook.get_nth_page(page_num)
        if page is None:
            return None
        child = page.get_child()
        if isinstance(child, WriterSourceView):
            return child
        return None

    # ── Code execution ────────────────────────────────────

    def run_code(self):
        if not self.current_document:
            return
        if self.preview_popup is None or not self.preview_popup.is_visible():
            self.preview_popup = LivePreviewPopup(
                parent=self,
                document=self.current_document,
                config=self.config,
                frank_bridge=self.frank_bridge
            )
        self.preview_popup.present()
        self.preview_popup.run_code()

    # ── AI operations ─────────────────────────────────────

    def show_ai_command_palette(self):
        editor = self._get_current_editor()
        selected_text = ""
        if editor:
            selected_text = editor.get_selected_text() or ""

        dialog = AICommandDialog(
            parent=self,
            document=self.current_document,
            frank_bridge=self.frank_bridge,
            mode=self.current_mode,
            selected_text=selected_text
        )
        dialog.present()

    # ── Dialogs ───────────────────────────────────────────

    def show_open_dialog(self):
        dialog = Gtk.FileDialog()
        dialog.set_title("Datei öffnen")
        dialog.open(self, None, self._on_open_dialog_response)

    def _on_open_dialog_response(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file:
                self.open_document(file.get_path())
        except GLib.Error:
            pass

    def show_export_dialog(self):
        if not self.current_document:
            return
        dialog = ExportDialog(
            parent=self,
            document=self.current_document,
            config=self.config
        )
        dialog.present()

    def show_preferences(self):
        """Show preferences dialog"""
        dialog = PreferencesDialog(
            parent=self,
            config=self.config,
            on_apply=self._on_preferences_applied
        )
        dialog.present()

    def _on_preferences_applied(self):
        """Handle preference changes."""
        self._apply_theme()
        self._restart_autosave()

        # Update all editors with new settings
        for i in range(self.editor_notebook.get_n_pages()):
            page = self.editor_notebook.get_nth_page(i)
            if page is None:
                continue
            editor = page.get_child()
            if isinstance(editor, WriterSourceView):
                editor.set_mode(self.current_mode)

    def show_word_count_dialog(self):
        """Show detailed word count dialog."""
        dialog = WordCountDialog(parent=self, document=self.current_document)
        dialog.present()

    # ── Auto-Save & Recovery ──────────────────────────────

    def _start_autosave(self):
        """Start periodic auto-save."""
        self.AUTOSAVE_DIR.mkdir(parents=True, exist_ok=True)
        interval = self.config.save_config.autosave_interval_sec * 1000
        self._autosave_timer_id = GLib.timeout_add(interval, self._do_autosave)

    def _restart_autosave(self):
        """Restart autosave timer with potentially new interval."""
        if self._autosave_timer_id:
            GLib.source_remove(self._autosave_timer_id)
        self._start_autosave()

    def _do_autosave(self):
        """Perform auto-save for all modified documents."""
        if not self.config.save_config.autosave_enabled:
            return True

        for i, doc in enumerate(self.documents):
            if doc.is_modified and doc.content.strip():
                try:
                    name = doc.title if doc.title != "Untitled" else f"untitled_{i}"
                    safe_name = "".join(c if c.isalnum() or c in '-_.' else '_' for c in name)
                    path = self.AUTOSAVE_DIR / f"{safe_name}.autosave"
                    path.write_text(doc.content, encoding='utf-8')

                    # Also save metadata
                    meta_path = self.AUTOSAVE_DIR / f"{safe_name}.meta.json"
                    meta = {
                        'title': doc.title,
                        'original_path': str(doc.file_path) if doc.file_path else None,
                        'timestamp': datetime.now().isoformat(),
                    }
                    meta_path.write_text(json.dumps(meta), encoding='utf-8')
                except Exception:
                    pass  # Silent - autosave should never crash the app

        return True  # Keep timer running

    def _check_recovery(self):
        """Check for autosave recovery files on startup."""
        if not self.AUTOSAVE_DIR.exists():
            return

        autosave_files = list(self.AUTOSAVE_DIR.glob("*.autosave"))
        if not autosave_files:
            return

        # Show recovery dialog
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Wiederherstellung",
            body=f"{len(autosave_files)} automatisch gespeicherte Datei(en) gefunden. Wiederherstellen?"
        )
        dialog.add_response("discard", "Verwerfen")
        dialog.add_response("recover", "Wiederherstellen")
        dialog.set_response_appearance("recover", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect('response', self._on_recovery_response, autosave_files)
        GLib.idle_add(dialog.present)

    def _on_recovery_response(self, dialog, response, autosave_files):
        if response == "recover":
            for af in autosave_files:
                try:
                    content = af.read_text(encoding='utf-8')
                    meta_path = af.with_suffix('.meta.json')
                    title = af.stem
                    original_path = None
                    if meta_path.exists():
                        meta = json.loads(meta_path.read_text())
                        title = meta.get('title', af.stem)
                        original_path = meta.get('original_path')

                    doc = Document(content=content, title=f"[Wiederhergestellt] {title}")
                    if original_path:
                        doc.file_path = Path(original_path)
                    self._add_document(doc)
                except Exception:
                    pass

        # Clean up autosave files
        for af in autosave_files:
            try:
                af.unlink()
                meta = af.with_suffix('.meta.json')
                if meta.exists():
                    meta.unlink()
            except Exception:
                pass

    # ── Recent Files ──────────────────────────────────────

    def _load_recent_files(self) -> list:
        try:
            if self.RECENT_FILES_PATH.exists():
                return json.loads(self.RECENT_FILES_PATH.read_text())[:self.MAX_RECENT]
        except Exception:
            pass
        return []

    def _add_to_recent(self, path: str):
        if path in self._recent_files:
            self._recent_files.remove(path)
        self._recent_files.insert(0, path)
        self._recent_files = self._recent_files[:self.MAX_RECENT]
        try:
            self.RECENT_FILES_PATH.parent.mkdir(parents=True, exist_ok=True)
            self.RECENT_FILES_PATH.write_text(json.dumps(self._recent_files))
        except Exception:
            pass

    # ── Event handlers ────────────────────────────────────

    def _on_document_modified(self, doc: Document):
        self._update_ui()
        # Update formatting toolbar active state
        self._update_toolbar_state()

    def _on_cursor_moved(self, line: int, col: int):
        self.cursor_pos_label.set_label(f"Zeile {line}, Spalte {col}")
        # Update formatting toolbar active state
        self._update_toolbar_state()

    def _update_toolbar_state(self):
        """Update formatting toolbar to reflect active formats at cursor."""
        if self.current_mode != 'writer':
            return
        editor = self._get_current_editor()
        if not editor:
            return
        active_tags = editor.get_format_at_cursor()
        # Highlight active formatting buttons
        for tag_name, btn in [
            ('bold', self.formatting_toolbar.bold_btn),
            ('italic', self.formatting_toolbar.italic_btn),
            ('underline', self.formatting_toolbar.underline_btn),
            ('strikethrough', self.formatting_toolbar.strike_btn),
        ]:
            if tag_name in active_tags:
                if not btn.has_css_class("suggested-action"):
                    btn.add_css_class("suggested-action")
            else:
                btn.remove_css_class("suggested-action")

    def _on_page_switched(self, notebook, page, page_num):
        if page_num >= 0 and page_num < len(self.documents):
            self.current_document = self.documents[page_num]
            self.sidebar.set_document(self.current_document)
            self._update_ui()
        elif self.documents:
            self.current_document = self.documents[-1]
            self.sidebar.set_document(self.current_document)
            self._update_ui()

    def _on_file_dropped(self, target, value, x, y):
        if isinstance(value, Gio.File):
            self.open_document(value.get_path())
            return True
        return False

    def _on_close_request(self, window):
        # Stop autosave
        if self._autosave_timer_id:
            GLib.source_remove(self._autosave_timer_id)

        unsaved = [d for d in self.documents if d.is_modified]
        if unsaved:
            self._ask_save_all_before_quit(unsaved)
            return True
        # Clean autosave on clean exit
        self._clean_autosave()
        return False

    def _clean_autosave(self):
        """Remove autosave files on clean exit."""
        try:
            for f in self.AUTOSAVE_DIR.glob("*.autosave"):
                f.unlink()
            for f in self.AUTOSAVE_DIR.glob("*.meta.json"):
                f.unlink()
        except Exception:
            pass

    def _ask_save_all_before_quit(self, unsaved_docs):
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Änderungen speichern?",
            body=f"{len(unsaved_docs)} Dokument(e) mit ungespeicherten Änderungen."
        )
        dialog.add_response("discard", "Verwerfen")
        dialog.add_response("cancel", "Abbrechen")
        dialog.add_response("save", "Alle speichern")
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect('response', self._on_quit_dialog_response, unsaved_docs)
        dialog.present()

    def _on_quit_dialog_response(self, dialog, response, unsaved_docs):
        if response == "save":
            for doc in unsaved_docs:
                if doc.file_path:
                    doc.save()
            still_unsaved = [d for d in unsaved_docs if not d.file_path and d.is_modified]
            if still_unsaved:
                names = ", ".join(d.title for d in still_unsaved)
                warn = Adw.MessageDialog(
                    transient_for=self,
                    heading="Unbenannte Dokumente",
                    body=f"Nicht gespeichert: {names}. Verwerfen?",
                )
                warn.add_response("cancel", "Abbrechen")
                warn.add_response("discard", "Verwerfen & Beenden")
                warn.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
                warn.connect("response", self._on_untitled_discard_response)
                warn.present()
                return
            for doc in self.documents:
                doc.is_modified = False
            self._clean_autosave()
            self.close()
        elif response == "discard":
            for doc in self.documents:
                doc.is_modified = False
            self._clean_autosave()
            self.close()

    def _on_untitled_discard_response(self, dialog, response):
        if response == "discard":
            for doc in self.documents:
                doc.is_modified = False
            self._clean_autosave()
            self.close()

    def request_close(self):
        self.close()

    # ── Sidebar action handler ────────────────────────────

    def _handle_sidebar_action(self, action: str, data: dict = None):
        data = data or {}

        if action == 'save':
            self.save_document()
        elif action == 'export':
            self.show_export_dialog()
        elif action == 'close':
            self.request_close()
        elif action == 'run':
            self.run_code()
        elif action == 'new':
            self.new_document(data.get('schema'))
        elif action == 'open':
            self.open_document(data.get('path'))
        elif action == 'rewrite':
            self._apply_ai_action('rewrite', data)
        elif action == 'expand':
            self._apply_ai_action('expand', data)
        elif action == 'shorten':
            self._apply_ai_action('shorten', data)
        elif action == 'goto_line':
            line = data.get('line')
            if line is not None:
                editor = self._get_current_editor()
                if editor:
                    editor.goto_line(line + 1)
        elif action == 'insert_toc':
            self._insert_toc()
        elif action == 'insert_pagebreak':
            self._insert_pagebreak()

    # ── TOC Generation (P3-33) ───────────────────────────

    def _insert_toc(self):
        """Generate and insert a Table of Contents from document headings."""
        if not self.current_document:
            return
        editor = self._get_current_editor()
        if not editor:
            return

        outline = self.current_document.get_outline()
        if not outline:
            return

        toc_lines = ["# Inhaltsverzeichnis\n"]
        for item in outline:
            level = item.get('level', 1)
            title = item.get('title', '')
            indent = "  " * (level - 1)
            toc_lines.append(f"{indent}- {title}")
        toc_lines.append("\n---\n")

        toc_text = "\n".join(toc_lines)

        # Insert at beginning of document
        buf = editor.buffer
        buf.begin_user_action()
        start = buf.get_start_iter()
        buf.insert(start, toc_text)
        buf.end_user_action()

    # ── Page Break (P3-36) ───────────────────────────────

    def _insert_pagebreak(self):
        """Insert a page break marker."""
        editor = self._get_current_editor()
        if not editor:
            return
        editor.buffer.insert_at_cursor("\n\n---\n<!-- page-break -->\n\n")

    # ── Footnotes (P3-34) ────────────────────────────────

    def _insert_footnote(self):
        """Insert a markdown footnote reference and definition."""
        editor = self._get_current_editor()
        if not editor:
            return

        # Auto-detect next footnote number from content
        import re
        existing = re.findall(r'\[\^(\d+)\]', self.current_document.content)
        if existing:
            self._footnote_counter = max(int(x) for x in existing)
        self._footnote_counter += 1
        n = self._footnote_counter

        # Insert footnote reference at cursor
        ref_text = f"[^{n}]"

        # Add footnote definition at end of document
        buf = editor.buffer
        buf.begin_user_action()
        buf.insert_at_cursor(ref_text)

        end_iter = buf.get_end_iter()
        definition = f"\n\n[^{n}]: "
        buf.insert(end_iter, definition)
        buf.end_user_action()

        # Move cursor to the footnote definition for editing
        end_iter = buf.get_end_iter()
        buf.place_cursor(end_iter)
        editor.scroll_to_iter(end_iter, 0.2, True, 0.0, 1.0)

    # ── Version History (P3-32) ──────────────────────────

    def show_version_history(self):
        """Show version history dialog."""
        if not self.current_document:
            return

        from writer.ui.dialogs.version_history_dialog import VersionHistoryDialog
        dialog = VersionHistoryDialog(
            parent=self,
            document=self.current_document,
            on_restore=self._on_version_restored
        )
        dialog.present()

    def _on_version_restored(self, content: str):
        """Handle version restore."""
        editor = self._get_current_editor()
        if editor and self.current_document:
            self.current_document.set_content(content)
            editor.buffer.set_text(content)
            self._update_ui()

    def _save_version_snapshot(self, label: str = ""):
        """Save a version snapshot of the current document."""
        if self.current_document and self.current_document.content.strip():
            self._version_history.save_version(
                self.current_document.file_path,
                self.current_document.title,
                self.current_document.content,
                label=label,
            )

    # ── Grammar Check (P3-31) ────────────────────────────

    def grammar_check(self):
        """Run grammar check on current document via AI."""
        if not self.current_document:
            return

        editor = self._get_current_editor()
        text = ""
        if editor:
            text = editor.get_selected_text() or ""
        if not text:
            text = self.current_document.content
        if not text.strip():
            return

        # Show progress
        self.sidebar.chat_panel.add_system_message(
            "Checking grammar..."
        )

        def do_check():
            prompt = (
                "Check the following text for grammar, spelling and style errors. "
                "List each error with line reference and suggested correction. "
                "Answer briefly and in a structured format:\n\n"
                f"{text[:4000]}"
            )
            response = self.frank_bridge.chat(prompt)
            GLib.idle_add(self._show_grammar_result, response)

        thread = threading.Thread(target=do_check, daemon=True)
        thread.start()

    def _show_grammar_result(self, response):
        """Show grammar check results in sidebar chat."""
        from writer.ai.bridge import AIResponse
        if isinstance(response, AIResponse) and response.success and response.content:
            self.sidebar.chat_panel.add_system_message(response.content)
        else:
            error = ""
            if isinstance(response, AIResponse):
                error = response.error or "Keine Antwort"
            self.sidebar.chat_panel.add_system_message(
                f"Grammatikprüfung fehlgeschlagen: {error}"
            )
        return False

    # ── Text Drag-Drop (P3-39) ───────────────────────────

    def _on_text_dropped(self, target, value, x, y):
        """Handle dropped text."""
        if isinstance(value, str) and value.strip():
            editor = self._get_current_editor()
            if editor:
                editor.buffer.insert_at_cursor(value)
                return True
        return False

    def _apply_ai_action(self, action: str, data: dict):
        editor = self._get_current_editor()
        if not editor:
            return

        text = editor.get_selected_text()
        if not text:
            text = self.current_document.content
            if not text.strip():
                return

        def do_ai_call():
            if action == 'rewrite':
                instruction = data.get('instruction')
                response = self.frank_bridge.rewrite_text(text, instruction)
            elif action == 'expand':
                response = self.frank_bridge.expand_text(text)
            elif action == 'shorten':
                response = self.frank_bridge.shorten_text(text)
            elif action == 'custom':
                instruction = data.get('instruction', '')
                response = self.frank_bridge.rewrite_text(text, instruction)
            else:
                return
            GLib.idle_add(self._apply_ai_result, editor, text, response)

        thread = threading.Thread(target=do_ai_call, daemon=True)
        thread.start()

    def _apply_ai_result(self, editor, original_text, response):
        from writer.ai.bridge import AIResponse
        if not isinstance(response, AIResponse) or not response.success:
            return False
        if not response.content.strip():
            return False
        if editor.get_selected_text():
            editor.replace_selection(response.content)
        else:
            self.current_document.set_content(response.content)
            editor.buffer.set_text(response.content)
        return False

    # ── UI updates ────────────────────────────────────────

    def _update_ui(self):
        if self.current_document:
            self.title_widget.set_subtitle(self.current_document.title)

            word_count = self.current_document.word_count
            self.word_count_label.set_label(f"{word_count} Wörter")

            self.language_label.set_label(
                self.current_document.language or "Text"
            )

            if self.current_document.is_modified:
                self.modified_indicator.set_label("● Geändert")
            else:
                self.modified_indicator.set_label("")

            if hasattr(self.current_document, '_tab_label'):
                title = self.current_document.title
                if self.current_document.is_modified:
                    title = "● " + title
                self.current_document._tab_label.set_label(title)

    def _show_error(self, message: str):
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Fehler",
            body=message
        )
        dialog.add_response("ok", "OK")
        dialog.present()
