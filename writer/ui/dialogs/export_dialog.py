"""
Export Dialog — B3 FIX: double extensions, B21 FIX: overwrite check
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib

from pathlib import Path


class ExportDialog(Adw.Window):
    """Export document dialog"""

    FORMATS = [
        ('pdf', 'PDF-Dokument', '.pdf'),
        ('docx', 'Word-Dokument', '.docx'),
        ('tex', 'LaTeX', '.tex'),
        ('md', 'Markdown', '.md'),
        ('html', 'HTML', '.html'),
        ('txt', 'Reintext', '.txt'),
    ]

    def __init__(self, parent, document, config):
        super().__init__()
        self.parent_window = parent
        self.document = document
        self.config = config
        self.selected_format = 'pdf'

        self._setup_window()
        self._build_ui()

    def _setup_window(self):
        self.set_title("Exportieren")
        self.set_default_size(450, 400)
        self.set_transient_for(self.parent_window)
        self.set_modal(True)

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)

        cancel_btn = Gtk.Button(label="Abbrechen")
        cancel_btn.connect('clicked', lambda b: self.close())
        header.pack_start(cancel_btn)

        self.export_btn = Gtk.Button(label="Exportieren")
        self.export_btn.add_css_class("suggested-action")
        self.export_btn.connect('clicked', self._on_export)
        header.pack_end(self.export_btn)

        main_box.append(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_start(24)
        content.set_margin_end(24)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        main_box.append(content)

        # Format selection
        format_group = Adw.PreferencesGroup(title="Format")
        content.append(format_group)

        self.format_buttons = {}
        first_btn = None

        for fmt_id, fmt_name, fmt_ext in self.FORMATS:
            row = Adw.ActionRow(title=fmt_name, subtitle=fmt_ext)

            radio = Gtk.CheckButton()
            if first_btn:
                radio.set_group(first_btn)
            else:
                first_btn = radio
                radio.set_active(True)

            radio.connect('toggled', self._on_format_changed, fmt_id)
            row.add_prefix(radio)
            row.set_activatable_widget(radio)

            self.format_buttons[fmt_id] = radio
            format_group.add(row)

        # Filename
        filename_group = Adw.PreferencesGroup(title="Dateiname")
        content.append(filename_group)

        self.filename_entry = Adw.EntryRow(title="Name")
        self.filename_entry.set_text(self.document.title)
        filename_group.add(self.filename_entry)

        # Location
        location_row = Adw.ActionRow(title="Speicherort")

        self.location_label = Gtk.Label(label=str(Path.home() / "Documents"))
        self.location_label.add_css_class("dim-label")
        self.location_label.set_ellipsize(True)
        location_row.add_suffix(self.location_label)

        browse_btn = Gtk.Button(icon_name="folder-open-symbolic")
        browse_btn.add_css_class("flat")
        browse_btn.connect('clicked', self._on_browse)
        location_row.add_suffix(browse_btn)

        filename_group.add(location_row)

        self.export_path = Path.home() / "Documents"

    def _on_format_changed(self, button, fmt_id):
        if button.get_active():
            self.selected_format = fmt_id

    def _on_browse(self, button):
        dialog = Gtk.FileDialog()
        dialog.set_title("Speicherort wählen")
        dialog.select_folder(self.parent_window, None, self._on_folder_selected)

    def _on_folder_selected(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
            if folder:
                self.export_path = Path(folder.get_path())
                self.location_label.set_label(str(self.export_path))
        except GLib.Error:
            pass

    def _on_export(self, button):
        filename = self.filename_entry.get_text().strip()
        if not filename:
            filename = self.document.title

        # Sanitize filename
        filename = "".join(c if c.isalnum() or c in '-_. ' else '_' for c in filename)

        # Get target extension
        ext = None
        for fmt_id, _, fmt_ext in self.FORMATS:
            if fmt_id == self.selected_format:
                ext = fmt_ext
                break

        # B3 FIX: Remove any existing extension before adding the correct one
        stem = Path(filename).stem
        # Also strip known extensions to prevent double extensions
        known_exts = {fmt_ext for _, _, fmt_ext in self.FORMATS}
        current_ext = Path(filename).suffix.lower()
        if current_ext in known_exts:
            filename = stem
        filename += ext

        output_path = self.export_path / filename

        # B21 FIX: Check for overwrite
        if output_path.exists():
            self._confirm_overwrite(output_path)
            return

        self._do_export_and_close(output_path)

    def _confirm_overwrite(self, output_path):
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Datei überschreiben?",
            body=f"'{output_path.name}' existiert bereits. Überschreiben?"
        )
        dialog.add_response("cancel", "Abbrechen")
        dialog.add_response("overwrite", "Überschreiben")
        dialog.set_response_appearance("overwrite", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect('response', self._on_overwrite_response, output_path)
        dialog.present()

    def _on_overwrite_response(self, dialog, response, output_path):
        if response == "overwrite":
            self._do_export_and_close(output_path)

    def _do_export_and_close(self, output_path: Path):
        try:
            self._do_export(output_path)
            self.close()
        except Exception as e:
            dialog = Adw.MessageDialog(
                transient_for=self,
                heading="Export fehlgeschlagen",
                body=str(e)
            )
            dialog.add_response("ok", "OK")
            dialog.present()

    def _do_export(self, output_path: Path):
        from writer.export.renderer import DocumentRenderer

        renderer = DocumentRenderer(self.config)

        if self.selected_format == 'pdf':
            renderer.to_pdf(self.document, output_path)
        elif self.selected_format == 'docx':
            renderer.to_docx(self.document, output_path)
        elif self.selected_format == 'tex':
            renderer.to_latex(self.document, output_path)
        elif self.selected_format == 'md':
            renderer.to_markdown(self.document, output_path)
        elif self.selected_format == 'html':
            renderer.to_html(self.document, output_path)
        elif self.selected_format == 'txt':
            renderer.to_text(self.document, output_path)
