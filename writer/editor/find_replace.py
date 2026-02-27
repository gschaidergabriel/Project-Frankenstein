"""
Find & Replace Bar for Frank Writer
Ctrl+F = Find, Ctrl+H = Find & Replace
"""

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, GLib, GtkSource, Pango


class FindReplaceBar(Gtk.Revealer):
    """Slide-down Find & Replace bar (like VS Code / Sublime)."""

    def __init__(self, get_editor_callback):
        super().__init__()
        self._get_editor = get_editor_callback
        self._search_context = None
        self._search_settings = None
        self._match_count = 0
        self._current_match = 0

        self.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.set_reveal_child(False)

        self._build_ui()

    # ── Build ─────────────────────────────────────────────

    def _build_ui(self):
        frame = Gtk.Frame()
        frame.add_css_class("find-replace-bar")

        self._main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._main_box.set_margin_start(8)
        self._main_box.set_margin_end(8)
        self._main_box.set_margin_top(6)
        self._main_box.set_margin_bottom(6)
        frame.set_child(self._main_box)
        self.set_child(frame)

        # ── Find row ──
        find_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._main_box.append(find_row)

        self.find_entry = Gtk.SearchEntry()
        self.find_entry.set_placeholder_text("Search... (Ctrl+F)")
        self.find_entry.set_hexpand(True)
        self.find_entry.connect('search-changed', self._on_search_changed)
        self.find_entry.connect('activate', lambda e: self.find_next())
        find_row.append(self.find_entry)

        # Match counter
        self.match_label = Gtk.Label(label="")
        self.match_label.add_css_class("dim-label")
        self.match_label.set_width_chars(10)
        find_row.append(self.match_label)

        # Prev / Next
        prev_btn = Gtk.Button(icon_name="go-up-symbolic")
        prev_btn.set_tooltip_text("Previous (Shift+Enter)")
        prev_btn.connect('clicked', lambda b: self.find_previous())
        find_row.append(prev_btn)

        next_btn = Gtk.Button(icon_name="go-down-symbolic")
        next_btn.set_tooltip_text("Next (Enter)")
        next_btn.connect('clicked', lambda b: self.find_next())
        find_row.append(next_btn)

        # Options
        self.case_btn = Gtk.ToggleButton(label="Aa")
        self.case_btn.set_tooltip_text("Match Case")
        self.case_btn.connect('toggled', self._on_option_changed)
        find_row.append(self.case_btn)

        self.regex_btn = Gtk.ToggleButton(label=".*")
        self.regex_btn.set_tooltip_text("Regular Expression")
        self.regex_btn.connect('toggled', self._on_option_changed)
        find_row.append(self.regex_btn)

        self.word_btn = Gtk.ToggleButton(label="W")
        self.word_btn.set_tooltip_text("Whole Word")
        self.word_btn.connect('toggled', self._on_option_changed)
        find_row.append(self.word_btn)

        # Close
        close_btn = Gtk.Button(icon_name="window-close-symbolic")
        close_btn.add_css_class("flat")
        close_btn.add_css_class("circular")
        close_btn.connect('clicked', lambda b: self.hide_bar())
        find_row.append(close_btn)

        # ── Replace row (hidden by default) ──
        self.replace_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.replace_row.set_visible(False)
        self._main_box.append(self.replace_row)

        self.replace_entry = Gtk.Entry()
        self.replace_entry.set_placeholder_text("Replace with...")
        self.replace_entry.set_hexpand(True)
        self.replace_entry.connect('activate', lambda e: self.replace_current())
        self.replace_row.append(self.replace_entry)

        replace_btn = Gtk.Button(icon_name="edit-find-replace-symbolic")
        replace_btn.set_tooltip_text("Replace")
        replace_btn.connect('clicked', lambda b: self.replace_current())
        self.replace_row.append(replace_btn)

        replace_all_btn = Gtk.Button(label="Alle")
        replace_all_btn.set_tooltip_text("Replace All")
        replace_all_btn.connect('clicked', lambda b: self.replace_all())
        self.replace_row.append(replace_all_btn)

        # Keyboard handler for Escape
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect('key-pressed', self._on_key_pressed)
        self.find_entry.add_controller(key_ctrl)

        key_ctrl2 = Gtk.EventControllerKey()
        key_ctrl2.connect('key-pressed', self._on_key_pressed)
        self.replace_entry.add_controller(key_ctrl2)

    # ── Public API ────────────────────────────────────────

    def show_find(self):
        """Show find bar (Ctrl+F)."""
        self.replace_row.set_visible(False)
        self.set_reveal_child(True)
        self.find_entry.grab_focus()

        # Pre-fill with selection
        editor = self._get_editor()
        if editor:
            sel = editor.get_selected_text()
            if sel and '\n' not in sel:
                self.find_entry.set_text(sel)
        self.find_entry.select_region(0, -1)

    def show_find_replace(self):
        """Show find & replace bar (Ctrl+H)."""
        self.replace_row.set_visible(True)
        self.set_reveal_child(True)
        self.find_entry.grab_focus()

        editor = self._get_editor()
        if editor:
            sel = editor.get_selected_text()
            if sel and '\n' not in sel:
                self.find_entry.set_text(sel)
        self.find_entry.select_region(0, -1)

    def hide_bar(self):
        """Hide the find bar."""
        self.set_reveal_child(False)
        self._clear_highlights()
        editor = self._get_editor()
        if editor:
            editor.grab_focus()

    def find_next(self):
        """Find next occurrence."""
        ctx = self._ensure_search_context()
        if not ctx:
            return
        editor = self._get_editor()
        if not editor:
            return

        buf = editor.buffer
        cursor = buf.get_iter_at_mark(buf.get_insert())

        # Search forward from cursor
        found, start, end, wrapped = ctx.forward(cursor)
        if found:
            buf.select_range(start, end)
            editor.scroll_to_iter(start, 0.2, True, 0.0, 0.5)
            self._update_match_count()

    def find_previous(self):
        """Find previous occurrence."""
        ctx = self._ensure_search_context()
        if not ctx:
            return
        editor = self._get_editor()
        if not editor:
            return

        buf = editor.buffer
        cursor = buf.get_iter_at_mark(buf.get_insert())

        found, start, end, wrapped = ctx.backward(cursor)
        if found:
            buf.select_range(end, start)
            editor.scroll_to_iter(start, 0.2, True, 0.0, 0.5)
            self._update_match_count()

    def replace_current(self):
        """Replace current match."""
        ctx = self._ensure_search_context()
        if not ctx:
            return
        editor = self._get_editor()
        if not editor:
            return

        buf = editor.buffer
        if buf.get_has_selection():
            start, end = buf.get_selection_bounds()
            replacement = self.replace_entry.get_text()
            ctx.replace(start, end, replacement, len(replacement.encode('utf-8')))
            self.find_next()
            self._update_match_count()

    def replace_all(self):
        """Replace all occurrences."""
        ctx = self._ensure_search_context()
        if not ctx:
            return

        replacement = self.replace_entry.get_text()
        count = ctx.replace_all(replacement, len(replacement.encode('utf-8')))
        self.match_label.set_label(f"{count} replaced")
        self._update_match_count()

    # ── Internal ──────────────────────────────────────────

    def _ensure_search_context(self):
        """Create or update search context for current editor."""
        editor = self._get_editor()
        if not editor:
            return None

        buf = editor.buffer
        if not isinstance(buf, GtkSource.Buffer):
            return None

        # Create settings
        if self._search_settings is None:
            self._search_settings = GtkSource.SearchSettings()

        text = self.find_entry.get_text()
        if not text:
            self._clear_highlights()
            self.match_label.set_label("")
            return None

        self._search_settings.set_search_text(text)
        self._search_settings.set_case_sensitive(self.case_btn.get_active())
        self._search_settings.set_regex_enabled(self.regex_btn.get_active())
        self._search_settings.set_at_word_boundaries(self.word_btn.get_active())
        self._search_settings.set_wrap_around(True)

        # Create or reuse context
        if self._search_context is None or self._search_context.get_buffer() != buf:
            self._search_context = GtkSource.SearchContext.new(buf, self._search_settings)
            self._search_context.set_highlight(True)
        else:
            self._search_context.set_settings(self._search_settings)

        return self._search_context

    def _clear_highlights(self):
        """Clear search highlights."""
        if self._search_context:
            self._search_context.set_highlight(False)

    def _update_match_count(self):
        """Update match count label."""
        if self._search_context:
            count = self._search_context.get_occurrences_count()
            if count >= 0:
                self.match_label.set_label(f"{count} matches")
            else:
                self.match_label.set_label("")
        else:
            self.match_label.set_label("")

    def _on_search_changed(self, entry):
        """Handle search text change."""
        ctx = self._ensure_search_context()
        if ctx:
            # Auto-find first match
            GLib.idle_add(self._auto_find_first)
        else:
            self.match_label.set_label("")

    def _auto_find_first(self):
        """Find first match from current cursor position."""
        self.find_next()
        return False

    def _on_option_changed(self, btn):
        """Handle search option toggle."""
        self._ensure_search_context()
        if self.find_entry.get_text():
            GLib.idle_add(self._auto_find_first)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Handle key press in find/replace entries."""
        if keyval == Gdk.KEY_Escape:
            self.hide_bar()
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if state & Gdk.ModifierType.SHIFT_MASK:
                self.find_previous()
            else:
                self.find_next()
            return True
        return False
