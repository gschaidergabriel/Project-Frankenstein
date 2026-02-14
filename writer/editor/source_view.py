"""
GtkSourceView Wrapper for Frank Writer
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('GtkSource', '5')
from gi.repository import Gtk, GtkSource, Gdk, Pango, GLib

import weakref
from typing import Callable, Optional
from writer.editor.document import Document


class WriterSourceView(GtkSource.View):
    """Extended GtkSourceView for Frank Writer"""

    def __init__(self, document: Document, config, mode: str = 'writer'):
        super().__init__()
        self.document = document
        self.config = config
        self.mode = mode

        # Callbacks
        self._on_modified_callback = None
        self._on_cursor_moved_callback = None

        # Setup
        self._setup_buffer()
        self._setup_view()
        self._apply_mode_settings()
        self._connect_buffer_signals()

    def _setup_buffer(self):
        """Setup the source buffer"""
        self.buffer = GtkSource.Buffer()
        self.set_buffer(self.buffer)

        # Set initial content
        self.buffer.set_text(self.document.content)

        # Setup WYSIWYG formatting tags (Writer mode)
        self._pending_tags = set()
        self._setup_format_tags()

        # Setup language
        self._set_language()

        # Setup style scheme
        self._set_style_scheme()

    def _setup_view(self):
        """Setup view properties"""
        config = self.config.editor

        # Font
        font_desc = Pango.FontDescription()
        if self.mode == 'coding':
            font_desc.set_family(config.font_family)
        else:
            font_desc.set_family("Cantarell")  # Readable font for writing
        font_desc.set_size(config.font_size * Pango.SCALE)

        # Basic settings
        self.set_show_line_numbers(config.show_line_numbers)
        self.set_highlight_current_line(config.highlight_current_line)
        self.set_tab_width(config.tab_width)
        self.set_insert_spaces_instead_of_tabs(config.use_spaces)
        self.set_auto_indent(config.auto_indent)

        # Word wrap
        if config.word_wrap:
            self.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        else:
            self.set_wrap_mode(Gtk.WrapMode.NONE)

        # Margins
        self.set_left_margin(10)
        self.set_right_margin(10)
        self.set_top_margin(10)
        self.set_bottom_margin(10)

        # Monospace for coding
        self.set_monospace(self.mode == 'coding')

        # Smart features
        self.set_smart_backspace(True)
        self.set_indent_on_tab(True)

        # Enable undo
        self.buffer.set_max_undo_levels(5000)  # High limit (GTK4 requires unsigned)

    # ── WYSIWYG Formatting Tags ─────────────────────────

    def _setup_format_tags(self):
        """Create text tags for Word-like WYSIWYG formatting."""
        tag_table = self.buffer.get_tag_table()

        # Bold
        bold = Gtk.TextTag(name="bold")
        bold.set_property("weight", Pango.Weight.BOLD)
        tag_table.add(bold)

        # Italic
        italic = Gtk.TextTag(name="italic")
        italic.set_property("style", Pango.Style.ITALIC)
        tag_table.add(italic)

        # Underline
        underline = Gtk.TextTag(name="underline")
        underline.set_property("underline", Pango.Underline.SINGLE)
        tag_table.add(underline)

        # Strikethrough
        strike = Gtk.TextTag(name="strikethrough")
        strike.set_property("strikethrough", True)
        tag_table.add(strike)

        # Monospace (for inline code)
        mono = Gtk.TextTag(name="monospace")
        mono.set_property("family", "JetBrains Mono")
        tag_table.add(mono)

        # Heading tags (visual only - larger/bolder text)
        heading_sizes = {1: 24, 2: 20, 3: 16}
        for level, size in heading_sizes.items():
            tag = Gtk.TextTag(name=f"heading-{level}")
            tag.set_property("weight", Pango.Weight.BOLD)
            tag.set_property("size-points", size)
            tag_table.add(tag)

        # Connect insert-text for pending tags (typing with format active)
        self.buffer.connect_after('insert-text', self._on_insert_text_after)

    def _on_insert_text_after(self, buffer, location, text, length):
        """Apply pending format tags to newly typed text."""
        if not self._pending_tags:
            return

        # location points past the inserted text after default handler
        end_iter = location.copy()
        start_iter = end_iter.copy()
        start_iter.backward_chars(len(text))

        for tag_name in list(self._pending_tags):
            tag = buffer.get_tag_table().lookup(tag_name)
            if tag:
                buffer.apply_tag(tag, start_iter, end_iter)

    def toggle_format_tag(self, tag_name: str):
        """Toggle a WYSIWYG formatting tag (bold, italic, etc.)."""
        tag = self.buffer.get_tag_table().lookup(tag_name)
        if not tag:
            return

        if self.buffer.get_has_selection():
            start, end = self.buffer.get_selection_bounds()
            if self._selection_has_tag(start, end, tag):
                self.buffer.remove_tag(tag, start, end)
            else:
                self.buffer.apply_tag(tag, start, end)
        else:
            # No selection: toggle pending tag for subsequent typing
            if tag_name in self._pending_tags:
                self._pending_tags.discard(tag_name)
            else:
                self._pending_tags.add(tag_name)

    def _selection_has_tag(self, start, end, tag) -> bool:
        """Check if the entire selection has the given tag."""
        it = start.copy()
        while it.compare(end) < 0:
            if not it.has_tag(tag):
                return False
            if not it.forward_char():
                break
        return True

    def apply_color_tag(self, hex_color: str):
        """Apply a foreground color tag to the selection."""
        if not self.buffer.get_has_selection():
            return

        tag_name = f"color-{hex_color}"
        tag_table = self.buffer.get_tag_table()
        tag = tag_table.lookup(tag_name)
        if not tag:
            tag = Gtk.TextTag(name=tag_name)
            tag.set_property("foreground", hex_color)
            tag_table.add(tag)

        start, end = self.buffer.get_selection_bounds()
        self.buffer.apply_tag(tag, start, end)

    def apply_heading_to_line(self, level: int):
        """Apply heading formatting to the current line (0=normal, 1-3=heading)."""
        cursor = self.buffer.get_iter_at_mark(self.buffer.get_insert())
        line = cursor.get_line()

        line_start = self.buffer.get_iter_at_line(line)
        line_end = line_start.copy()
        if not line_end.ends_line():
            line_end.forward_to_line_end()

        # Remove all heading tags from line
        for i in range(1, 4):
            tag = self.buffer.get_tag_table().lookup(f"heading-{i}")
            if tag:
                self.buffer.remove_tag(tag, line_start, line_end)

        # Apply new heading tag
        if 1 <= level <= 3:
            tag = self.buffer.get_tag_table().lookup(f"heading-{level}")
            if tag:
                self.buffer.apply_tag(tag, line_start, line_end)

    def get_format_at_cursor(self) -> set:
        """Get set of active format tag names at cursor position."""
        cursor = self.buffer.get_iter_at_mark(self.buffer.get_insert())
        tags = cursor.get_tags()
        return {tag.get_property("name") for tag in tags if tag.get_property("name")}

    def _set_language(self):
        """Set syntax highlighting language"""
        lang_manager = GtkSource.LanguageManager.get_default()

        lang_id = self.document.language
        if lang_id:
            language = lang_manager.get_language(lang_id)
            if language:
                self.buffer.set_language(language)
                self.buffer.set_highlight_syntax(True)
            else:
                self.buffer.set_highlight_syntax(False)

    def _set_style_scheme(self):
        """Set color scheme"""
        scheme_manager = GtkSource.StyleSchemeManager.get_default()

        if self.mode == 'coding':
            # Dark theme for coding
            scheme_id = 'Adwaita-dark'
            for preferred in ['monokai', 'dracula', 'Adwaita-dark', 'oblivion']:
                if scheme_manager.get_scheme(preferred):
                    scheme_id = preferred
                    break
        else:
            # Light theme for writing
            scheme_id = 'Adwaita'
            for preferred in ['Adwaita', 'classic', 'kate']:
                if scheme_manager.get_scheme(preferred):
                    scheme_id = preferred
                    break

        scheme = scheme_manager.get_scheme(scheme_id)
        if scheme:
            self.buffer.set_style_scheme(scheme)

    def _apply_mode_settings(self):
        """Apply mode-specific settings"""
        if self.mode == 'coding':
            self.set_show_line_numbers(True)
            self.set_show_line_marks(True)
            self.set_highlight_current_line(True)
            self.set_monospace(True)

            # Show right margin at 80 chars
            self.set_show_right_margin(True)
            self.set_right_margin_position(80)

            # Bracket matching
            self.buffer.set_highlight_matching_brackets(True)
        else:
            self.set_show_line_numbers(self.config.editor.show_line_numbers)
            self.set_show_line_marks(False)
            self.set_show_right_margin(False)
            self.set_monospace(False)

    def _connect_buffer_signals(self):
        """Connect buffer signals using weak references to prevent circular refs"""
        # Use weak reference to self to prevent circular references
        weak_self = weakref.ref(self)

        def on_buffer_changed_wrapper(buffer):
            obj = weak_self()
            if obj is not None:
                obj._on_buffer_changed(buffer)

        def on_cursor_changed_wrapper(buffer, param):
            obj = weak_self()
            if obj is not None:
                obj._on_cursor_changed(buffer, param)

        self._buffer_changed_handler = self.buffer.connect('changed', on_buffer_changed_wrapper)
        self._cursor_changed_handler = self.buffer.connect('notify::cursor-position', on_cursor_changed_wrapper)

    def connect_signals(self, on_modified: Callable = None, on_cursor_moved: Callable = None):
        """Connect external callbacks"""
        self._on_modified_callback = on_modified
        self._on_cursor_moved_callback = on_cursor_moved

    def _on_buffer_changed(self, buffer):
        """Handle buffer changes"""
        try:
            # Update document
            start = buffer.get_start_iter()
            end = buffer.get_end_iter()
            content = buffer.get_text(start, end, True)
            self.document.set_content(content)

            # Notify with exception handling for callback
            if self._on_modified_callback:
                try:
                    self._on_modified_callback(self.document)
                except Exception as e:
                    print(f"Error in modified callback: {e}")
        except Exception as e:
            print(f"Error in buffer changed handler: {e}")

    def _on_cursor_changed(self, buffer, param):
        """Handle cursor position change"""
        if self._on_cursor_moved_callback:
            insert_mark = buffer.get_insert()
            if insert_mark is None:
                return
            cursor_iter = buffer.get_iter_at_mark(insert_mark)
            line = cursor_iter.get_line() + 1
            col = cursor_iter.get_line_offset() + 1
            self._on_cursor_moved_callback(line, col)

    def set_mode(self, mode: str):
        """Change editor mode"""
        self.mode = mode
        self._apply_mode_settings()
        self._set_style_scheme()

        # Update font
        font_desc = Pango.FontDescription()
        if mode == 'coding':
            font_desc.set_family(self.config.editor.font_family)
        else:
            font_desc.set_family("Cantarell")
        font_desc.set_size(self.config.editor.font_size * Pango.SCALE)
        self.set_monospace(mode == 'coding')

    def get_selected_text(self) -> Optional[str]:
        """Get currently selected text"""
        try:
            if self.buffer.get_has_selection():
                bounds = self.buffer.get_selection_bounds()
                if bounds:
                    start, end = bounds
                    return self.buffer.get_text(start, end, True)
        except Exception as e:
            print(f"Error getting selection bounds: {e}")
        return None

    def get_current_line(self) -> int:
        """Get current line number"""
        cursor = self.buffer.get_iter_at_mark(self.buffer.get_insert())
        return cursor.get_line() + 1

    def get_current_column(self) -> int:
        """Get current column number"""
        cursor = self.buffer.get_iter_at_mark(self.buffer.get_insert())
        return cursor.get_line_offset() + 1

    def insert_text(self, text: str):
        """Insert text at cursor"""
        self.buffer.insert_at_cursor(text)

    def replace_selection(self, text: str):
        """Replace selected text"""
        if self.buffer.get_has_selection():
            self.buffer.delete_selection(True, True)
        self.buffer.insert_at_cursor(text)

    def select_range(self, start_line: int, start_col: int, end_line: int, end_col: int):
        """Select text range with bounds validation"""
        line_count = self.buffer.get_line_count()

        # Validate and clamp line numbers
        start_line = max(1, min(start_line, line_count))
        end_line = max(1, min(end_line, line_count))

        # Get start iterator with column validation
        start_iter = self.buffer.get_iter_at_line(start_line - 1)
        start_line_end = start_iter.copy()
        if not start_line_end.ends_line():
            start_line_end.forward_to_line_end()
        max_start_col = start_line_end.get_line_offset()
        start_col = max(1, min(start_col, max_start_col + 1))
        start_iter = self.buffer.get_iter_at_line_offset(start_line - 1, start_col - 1)

        # Get end iterator with column validation
        end_iter = self.buffer.get_iter_at_line(end_line - 1)
        end_line_end = end_iter.copy()
        if not end_line_end.ends_line():
            end_line_end.forward_to_line_end()
        max_end_col = end_line_end.get_line_offset()
        end_col = max(1, min(end_col, max_end_col + 1))
        end_iter = self.buffer.get_iter_at_line_offset(end_line - 1, end_col - 1)

        self.buffer.select_range(start_iter, end_iter)

    def goto_line(self, line: int):
        """Go to specified line with bounds checking"""
        # Validate line number
        line_count = self.buffer.get_line_count()
        line = max(1, min(line, line_count))

        line_iter = self.buffer.get_iter_at_line(line - 1)
        self.buffer.place_cursor(line_iter)
        # GTK4 scroll_to_iter: (iter, within_margin, use_align, xalign, yalign)
        self.scroll_to_iter(line_iter, 0.2, True, 0.0, 0.5)

    def undo(self):
        """Undo last action"""
        if self.buffer.can_undo():
            self.buffer.undo()

    def redo(self):
        """Redo last undone action"""
        if self.buffer.can_redo():
            self.buffer.redo()

    def get_context_at_cursor(self) -> dict:
        """Get context information at cursor position"""
        cursor = self.buffer.get_iter_at_mark(self.buffer.get_insert())
        line = cursor.get_line()
        col = cursor.get_line_offset()

        # Get surrounding text
        start = self.buffer.get_iter_at_line(max(0, line - 5))
        end = self.buffer.get_iter_at_line(min(self.buffer.get_line_count(), line + 5))
        end.forward_to_line_end()
        surrounding = self.buffer.get_text(start, end, True)

        # Get current line text
        line_start = self.buffer.get_iter_at_line(line)
        line_end = line_start.copy()
        line_end.forward_to_line_end()
        current_line = self.buffer.get_text(line_start, line_end, True)

        # Get selection if any
        selection = self.get_selected_text()

        return {
            'line': line + 1,
            'column': col + 1,
            'current_line_text': current_line,
            'surrounding_text': surrounding,
            'selection': selection,
            'section': self.document.get_section_at_line(line)
        }
