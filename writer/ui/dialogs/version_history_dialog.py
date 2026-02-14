"""
Version History Dialog for Frank Writer
Shows version snapshots with diff preview and restore capability.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Pango

from typing import Callable, Optional
from pathlib import Path

from writer.editor.version_history import VersionHistory, VersionEntry


class VersionHistoryDialog(Adw.Window):
    """Dialog showing version history for a document."""

    def __init__(self, parent, document, on_restore: Callable):
        super().__init__(
            title="Versionsverlauf",
            default_width=700,
            default_height=500,
            transient_for=parent,
            modal=True,
        )
        self.document = document
        self.on_restore = on_restore
        self.history = VersionHistory()
        self._versions = []

        self._build_ui()
        self._load_versions()

    def _build_ui(self):
        # Header bar
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)

        # Save snapshot button
        save_btn = Gtk.Button(label="Snapshot speichern")
        save_btn.add_css_class("suggested-action")
        save_btn.connect('clicked', self._on_save_snapshot)
        header.pack_start(save_btn)

        # Main layout
        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(250)

        # Left: version list
        list_box_scroll = Gtk.ScrolledWindow()
        list_box_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        list_box_scroll.set_size_request(200, -1)

        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list_box.add_css_class("boxed-list")
        self.list_box.connect('row-selected', self._on_version_selected)
        list_box_scroll.set_child(self.list_box)

        paned.set_start_child(list_box_scroll)

        # Right: preview
        preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        preview_box.set_margin_start(6)
        preview_box.set_margin_end(6)
        preview_box.set_margin_top(6)
        preview_box.set_margin_bottom(6)

        # Info bar
        self.info_label = Gtk.Label(label="Version auswählen...")
        self.info_label.set_halign(Gtk.Align.START)
        self.info_label.add_css_class("dim-label")
        preview_box.append(self.info_label)

        # Preview text
        preview_scroll = Gtk.ScrolledWindow()
        preview_scroll.set_vexpand(True)

        self.preview_view = Gtk.TextView()
        self.preview_view.set_editable(False)
        self.preview_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.preview_view.set_monospace(True)
        self.preview_view.set_left_margin(8)
        self.preview_view.set_top_margin(8)
        preview_scroll.set_child(self.preview_view)
        preview_box.append(preview_scroll)

        # Restore button
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_box.set_halign(Gtk.Align.END)

        self.restore_btn = Gtk.Button(label="Wiederherstellen")
        self.restore_btn.add_css_class("destructive-action")
        self.restore_btn.set_sensitive(False)
        self.restore_btn.connect('clicked', self._on_restore)
        btn_box.append(self.restore_btn)

        preview_box.append(btn_box)

        paned.set_end_child(preview_box)

        toolbar_view.set_content(paned)
        self.set_content(toolbar_view)

    def _load_versions(self):
        self._versions = self.history.list_versions(
            self.document.file_path, self.document.title
        )

        # Clear list
        while True:
            row = self.list_box.get_row_at_index(0)
            if row is None:
                break
            self.list_box.remove(row)

        if not self._versions:
            empty_label = Gtk.Label(label="Noch keine Versionen gespeichert.")
            empty_label.add_css_class("dim-label")
            empty_label.set_margin_top(20)
            row = Gtk.ListBoxRow()
            row.set_activatable(False)
            row.set_child(empty_label)
            self.list_box.append(row)
            return

        for entry in self._versions:
            row = self._create_version_row(entry)
            self.list_box.append(row)

    def _create_version_row(self, entry: VersionEntry) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row._version_entry = entry

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(6)
        box.set_margin_bottom(6)

        # Time
        time_label = Gtk.Label(label=entry.display_time)
        time_label.set_halign(Gtk.Align.START)
        time_label.add_css_class("heading")
        box.append(time_label)

        # Label or word count
        subtitle = entry.label if entry.label else f"{entry.word_count} Wörter"
        sub_label = Gtk.Label(label=subtitle)
        sub_label.set_halign(Gtk.Align.START)
        sub_label.add_css_class("dim-label")
        box.append(sub_label)

        row.set_child(box)
        return row

    def _on_version_selected(self, list_box, row):
        if row is None or not hasattr(row, '_version_entry'):
            self.restore_btn.set_sensitive(False)
            return

        entry = row._version_entry
        content = self.history.get_version_content(
            self.document.file_path, self.document.title, entry.version_id
        )

        if content is not None:
            self.preview_view.get_buffer().set_text(content)
            self.info_label.set_label(
                f"{entry.display_time} — {entry.word_count} Wörter"
            )
            self.restore_btn.set_sensitive(True)
        else:
            self.preview_view.get_buffer().set_text("Version nicht gefunden.")
            self.restore_btn.set_sensitive(False)

    def _on_save_snapshot(self, btn):
        """Save current content as a new version."""
        self.history.save_version(
            self.document.file_path,
            self.document.title,
            self.document.content,
            label="Manueller Snapshot"
        )
        self._load_versions()

    def _on_restore(self, btn):
        """Restore selected version."""
        row = self.list_box.get_selected_row()
        if row is None or not hasattr(row, '_version_entry'):
            return

        entry = row._version_entry
        content = self.history.get_version_content(
            self.document.file_path, self.document.title, entry.version_id
        )

        if content is not None:
            # Save current as backup first
            self.history.save_version(
                self.document.file_path,
                self.document.title,
                self.document.content,
                label="Vor Wiederherstellung"
            )
            self.on_restore(content)
            self.close()
