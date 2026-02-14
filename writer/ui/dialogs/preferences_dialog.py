"""
Preferences Dialog for Frank Writer
Full settings: Editor, Theme, Auto-Save, Spelling, etc.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib


class PreferencesDialog(Adw.PreferencesWindow):
    """Preferences dialog with multiple pages."""

    def __init__(self, parent, config, on_apply=None):
        super().__init__()
        self.config = config
        self._on_apply = on_apply

        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title("Einstellungen")
        self.set_default_size(600, 500)

        self._build_editor_page()
        self._build_theme_page()
        self._build_autosave_page()
        self._build_ai_page()
        self._build_export_page()

    # ── Editor Page ───────────────────────────────────────

    def _build_editor_page(self):
        page = Adw.PreferencesPage(title="Editor", icon_name="text-editor-symbolic")

        # Font group
        font_group = Adw.PreferencesGroup(title="Schrift")
        page.add(font_group)

        # Font family
        self.font_row = Adw.EntryRow(title="Schriftart (Code)")
        self.font_row.set_text(self.config.editor.font_family)
        self.font_row.connect('changed', self._on_font_changed)
        font_group.add(self.font_row)

        # Font size
        self.font_size_row = Adw.SpinRow.new_with_range(8, 36, 1)
        self.font_size_row.set_title("Schriftgröße")
        self.font_size_row.set_value(self.config.editor.font_size)
        self.font_size_row.connect('changed', self._on_font_size_changed)
        font_group.add(self.font_size_row)

        # Editor features
        features_group = Adw.PreferencesGroup(title="Funktionen")
        page.add(features_group)

        self.line_numbers_switch = self._add_switch_row(
            features_group, "Zeilennummern", self.config.editor.show_line_numbers
        )
        self.highlight_line_switch = self._add_switch_row(
            features_group, "Aktuelle Zeile hervorheben", self.config.editor.highlight_current_line
        )
        self.word_wrap_switch = self._add_switch_row(
            features_group, "Zeilenumbruch", self.config.editor.word_wrap
        )
        self.auto_indent_switch = self._add_switch_row(
            features_group, "Automatische Einrückung", self.config.editor.auto_indent
        )
        self.bracket_match_switch = self._add_switch_row(
            features_group, "Klammern-Matching", self.config.editor.bracket_matching
        )

        # Tabs
        tab_group = Adw.PreferencesGroup(title="Einrückung")
        page.add(tab_group)

        self.tab_width_row = Adw.SpinRow.new_with_range(2, 8, 1)
        self.tab_width_row.set_title("Tab-Breite")
        self.tab_width_row.set_value(self.config.editor.tab_width)
        tab_group.add(self.tab_width_row)

        self.use_spaces_switch = self._add_switch_row(
            tab_group, "Leerzeichen statt Tabs", self.config.editor.use_spaces
        )

        self.add(page)

    # ── Theme Page ────────────────────────────────────────

    def _build_theme_page(self):
        page = Adw.PreferencesPage(title="Aussehen", icon_name="applications-graphics-symbolic")

        theme_group = Adw.PreferencesGroup(title="Farbschema")
        page.add(theme_group)

        # Color scheme
        scheme_row = Adw.ComboRow(title="Erscheinungsbild")
        schemes = Gtk.StringList()
        for label in ["System-Standard", "Hell", "Dunkel"]:
            schemes.append(label)
        scheme_row.set_model(schemes)

        scheme_map = {"default": 0, "prefer-light": 1, "prefer-dark": 2}
        scheme_row.set_selected(scheme_map.get(self.config.theme.ui_color_scheme, 0))
        scheme_row.connect('notify::selected', self._on_scheme_changed)
        self._scheme_row = scheme_row
        theme_group.add(scheme_row)

        # Writer theme
        writer_theme_row = Adw.ComboRow(title="Writer-Theme")
        writer_themes = Gtk.StringList()
        for t in ["writer_light", "writer_dark"]:
            writer_themes.append(t)
        writer_theme_row.set_model(writer_themes)
        idx = 0 if self.config.theme.writer_theme == "writer_light" else 1
        writer_theme_row.set_selected(idx)
        writer_theme_row.connect('notify::selected', self._on_writer_theme_changed)
        self._writer_theme_row = writer_theme_row
        theme_group.add(writer_theme_row)

        # Coding theme
        coding_theme_row = Adw.ComboRow(title="Coding-Theme")
        coding_themes = Gtk.StringList()
        for t in ["coding_monokai", "coding_dracula"]:
            coding_themes.append(t)
        coding_theme_row.set_model(coding_themes)
        coding_theme_row.set_selected(0)
        self._coding_theme_row = coding_theme_row
        theme_group.add(coding_theme_row)

        self.add(page)

    # ── Auto-Save Page ────────────────────────────────────

    def _build_autosave_page(self):
        page = Adw.PreferencesPage(title="Speichern", icon_name="document-save-symbolic")

        save_group = Adw.PreferencesGroup(title="Automatisches Speichern")
        page.add(save_group)

        self.autosave_switch = self._add_switch_row(
            save_group, "Auto-Save aktivieren",
            self.config.save_config.autosave_enabled
        )

        self.autosave_interval_row = Adw.SpinRow.new_with_range(10, 300, 10)
        self.autosave_interval_row.set_title("Intervall (Sekunden)")
        self.autosave_interval_row.set_value(self.config.save_config.autosave_interval_sec)
        save_group.add(self.autosave_interval_row)

        # Spelling
        spell_group = Adw.PreferencesGroup(title="Rechtschreibung")
        page.add(spell_group)

        self.spell_switch = self._add_switch_row(
            spell_group, "Rechtschreibprüfung",
            self.config.save_config.spell_check_enabled
        )

        spell_lang_row = Adw.ComboRow(title="Sprache")
        langs = Gtk.StringList()
        for lang in ["de_DE", "en_US", "en_GB", "fr_FR", "es_ES"]:
            langs.append(lang)
        spell_lang_row.set_model(langs)
        spell_lang_row.set_selected(0)
        self._spell_lang_row = spell_lang_row
        spell_group.add(spell_lang_row)

        self.add(page)

    # ── AI Page ───────────────────────────────────────────

    def _build_ai_page(self):
        page = Adw.PreferencesPage(title="AI", icon_name="system-search-symbolic")

        ai_group = Adw.PreferencesGroup(title="Frank AI")
        page.add(ai_group)

        self.router_url_row = Adw.EntryRow(title="Router URL")
        self.router_url_row.set_text(self.config.ai.router_url)
        ai_group.add(self.router_url_row)

        self.auto_suggest_switch = self._add_switch_row(
            ai_group, "Auto-Suggest", self.config.ai.auto_suggest
        )

        self.confirm_switch = self._add_switch_row(
            ai_group, "Kritische Aktionen bestätigen", self.config.ai.confirm_critical_actions
        )

        self.add(page)

    # ── Export Page ────────────────────────────────────────

    def _build_export_page(self):
        page = Adw.PreferencesPage(title="Export", icon_name="document-send-symbolic")

        pdf_group = Adw.PreferencesGroup(title="PDF-Export")
        page.add(pdf_group)

        page_size_row = Adw.ComboRow(title="Seitengröße")
        sizes = Gtk.StringList()
        for s in ["A4", "Letter", "A5"]:
            sizes.append(s)
        page_size_row.set_model(sizes)
        page_size_row.set_selected(0)
        self._page_size_row = page_size_row
        pdf_group.add(page_size_row)

        self.pdf_font_row = Adw.EntryRow(title="PDF-Schriftart")
        self.pdf_font_row.set_text(self.config.export.pdf_font_family)
        pdf_group.add(self.pdf_font_row)

        self.toc_switch = self._add_switch_row(
            pdf_group, "Inhaltsverzeichnis", self.config.export.include_toc
        )
        self.page_numbers_switch = self._add_switch_row(
            pdf_group, "Seitennummern", self.config.export.include_page_numbers
        )

        self.add(page)

    # ── Helpers ───────────────────────────────────────────

    def _add_switch_row(self, group, title, active):
        row = Adw.SwitchRow(title=title)
        row.set_active(active)
        row.connect('notify::active', self._on_setting_changed)
        group.add(row)
        return row

    def _on_setting_changed(self, *args):
        """Apply setting changes immediately."""
        self._apply_settings()

    def _on_font_changed(self, row):
        self._apply_settings()

    def _on_font_size_changed(self, row):
        self._apply_settings()

    def _on_scheme_changed(self, row, param):
        self._apply_settings()

    def _on_writer_theme_changed(self, row, param):
        self._apply_settings()

    def _apply_settings(self):
        """Apply all settings to config and save."""
        c = self.config

        # Editor
        c.editor.font_family = self.font_row.get_text() or "JetBrains Mono"
        c.editor.font_size = int(self.font_size_row.get_value())
        c.editor.show_line_numbers = self.line_numbers_switch.get_active()
        c.editor.highlight_current_line = self.highlight_line_switch.get_active()
        c.editor.word_wrap = self.word_wrap_switch.get_active()
        c.editor.auto_indent = self.auto_indent_switch.get_active()
        c.editor.bracket_matching = self.bracket_match_switch.get_active()
        c.editor.tab_width = int(self.tab_width_row.get_value())
        c.editor.use_spaces = self.use_spaces_switch.get_active()

        # Theme
        scheme_idx = self._scheme_row.get_selected()
        scheme_map = {0: "default", 1: "prefer-light", 2: "prefer-dark"}
        c.theme.ui_color_scheme = scheme_map.get(scheme_idx, "default")

        theme_idx = self._writer_theme_row.get_selected()
        c.theme.writer_theme = "writer_light" if theme_idx == 0 else "writer_dark"

        # AI
        c.ai.router_url = self.router_url_row.get_text() or c.ai.router_url
        c.ai.auto_suggest = self.auto_suggest_switch.get_active()
        c.ai.confirm_critical_actions = self.confirm_switch.get_active()

        # Export
        c.export.pdf_font_family = self.pdf_font_row.get_text() or "Libertinus Serif"
        c.export.include_toc = self.toc_switch.get_active()
        c.export.include_page_numbers = self.page_numbers_switch.get_active()

        # Auto-save and spelling settings (via SaveConfig)
        c.save_config.autosave_enabled = self.autosave_switch.get_active()
        c.save_config.autosave_interval_sec = int(self.autosave_interval_row.get_value())
        c.save_config.spell_check_enabled = self.spell_switch.get_active()

        c.save()

        if self._on_apply:
            self._on_apply()
