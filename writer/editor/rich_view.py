"""
Rich Text View for Frank Writer - WYSIWYG Preview
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Pango', '1.0')
from gi.repository import Gtk, Gdk, Pango, GLib

import re
import weakref
from typing import Optional, Callable, Dict, Any, List
from writer.editor.document import Document, DocumentSection


class RichTextView(Gtk.TextView):
    """
    WYSIWYG Rich Text Preview widget for Frank Writer.

    Renders formatted document preview with support for:
    - Headings (H1-H6)
    - Bold, italic, strikethrough
    - Lists (ordered and unordered)
    - Code blocks and inline code
    - Links and blockquotes

    Uses Pango markup for text formatting and syncs with source view.
    """

    def __init__(self, config=None):
        super().__init__()
        self.config = config
        self._document: Optional[Document] = None
        self._source_view = None
        self._sync_enabled = True
        self._scroll_handler_id = None
        self._debounce_timer_id = None  # B10 FIX: track debounce timer

        # Callbacks
        self._on_section_clicked: Optional[Callable] = None

        # Section tracking for navigation
        self._section_marks: Dict[str, Gtk.TextMark] = {}

        # Setup
        self._setup_view()
        self._setup_tags()

    def _setup_view(self):
        """Configure the text view for rich display"""
        self.set_editable(False)
        self.set_cursor_visible(False)
        self.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)

        # Margins for readability
        self.set_left_margin(40)
        self.set_right_margin(40)
        self.set_top_margin(20)
        self.set_bottom_margin(20)

        # Line spacing
        self.set_pixels_above_lines(4)
        self.set_pixels_below_lines(4)
        self.set_pixels_inside_wrap(2)

        # Font
        font_desc = Pango.FontDescription()
        font_desc.set_family("Cantarell, Liberation Serif, serif")
        font_desc.set_size(12 * Pango.SCALE)

        # Get the buffer
        self.buffer = self.get_buffer()

    def _setup_tags(self):
        """Create text tags for formatting"""
        tag_table = self.buffer.get_tag_table()

        # Heading tags
        heading_sizes = {
            'h1': 24,
            'h2': 20,
            'h3': 17,
            'h4': 14,
            'h5': 12,
            'h6': 11,
        }

        for tag_name, size in heading_sizes.items():
            tag = Gtk.TextTag.new(tag_name)
            tag.set_property('weight', Pango.Weight.BOLD)
            tag.set_property('size-points', size)
            tag.set_property('pixels-above-lines', 16)
            tag.set_property('pixels-below-lines', 8)
            tag_table.add(tag)

        # Bold tag
        bold_tag = Gtk.TextTag.new('bold')
        bold_tag.set_property('weight', Pango.Weight.BOLD)
        tag_table.add(bold_tag)

        # Italic tag
        italic_tag = Gtk.TextTag.new('italic')
        italic_tag.set_property('style', Pango.Style.ITALIC)
        tag_table.add(italic_tag)

        # Strikethrough tag
        strike_tag = Gtk.TextTag.new('strikethrough')
        strike_tag.set_property('strikethrough', True)
        tag_table.add(strike_tag)

        # Code inline tag
        code_tag = Gtk.TextTag.new('code')
        code_tag.set_property('family', 'JetBrains Mono, Source Code Pro, monospace')
        code_tag.set_property('background', '#f0f0f0')
        code_tag.set_property('size-points', 11)
        tag_table.add(code_tag)

        # Code block tag
        code_block_tag = Gtk.TextTag.new('code_block')
        code_block_tag.set_property('family', 'JetBrains Mono, Source Code Pro, monospace')
        code_block_tag.set_property('background', '#2d2d2d')
        code_block_tag.set_property('foreground', '#f8f8f2')
        code_block_tag.set_property('size-points', 11)
        code_block_tag.set_property('left-margin', 60)
        code_block_tag.set_property('right-margin', 60)
        code_block_tag.set_property('pixels-above-lines', 8)
        code_block_tag.set_property('pixels-below-lines', 8)
        tag_table.add(code_block_tag)

        # Blockquote tag
        quote_tag = Gtk.TextTag.new('blockquote')
        quote_tag.set_property('style', Pango.Style.ITALIC)
        quote_tag.set_property('left-margin', 60)
        quote_tag.set_property('foreground', '#666666')
        quote_tag.set_property('pixels-above-lines', 8)
        quote_tag.set_property('pixels-below-lines', 8)
        tag_table.add(quote_tag)

        # Link tag
        link_tag = Gtk.TextTag.new('link')
        link_tag.set_property('foreground', '#0066cc')
        link_tag.set_property('underline', Pango.Underline.SINGLE)
        tag_table.add(link_tag)

        # List item tag
        list_tag = Gtk.TextTag.new('list_item')
        list_tag.set_property('left-margin', 60)
        list_tag.set_property('pixels-above-lines', 2)
        list_tag.set_property('pixels-below-lines', 2)
        tag_table.add(list_tag)

        # Ordered list tag
        ordered_list_tag = Gtk.TextTag.new('ordered_list')
        ordered_list_tag.set_property('left-margin', 60)
        ordered_list_tag.set_property('pixels-above-lines', 2)
        ordered_list_tag.set_property('pixels-below-lines', 2)
        tag_table.add(ordered_list_tag)

        # Horizontal rule tag
        hr_tag = Gtk.TextTag.new('hr')
        hr_tag.set_property('foreground', '#cccccc')
        hr_tag.set_property('justification', Gtk.Justification.CENTER)
        hr_tag.set_property('pixels-above-lines', 16)
        hr_tag.set_property('pixels-below-lines', 16)
        tag_table.add(hr_tag)

    def set_document(self, doc: Document):
        """
        Set the document to preview.

        Args:
            doc: The Document instance to render
        """
        self._document = doc
        self.update_preview()

    def get_document(self) -> Optional[Document]:
        """Get the current document"""
        return self._document

    def update_preview(self):
        """
        Update the rich text preview from the current document.
        Parses markdown-like content and applies formatting tags.
        """
        if not self._document:
            self.buffer.set_text("")
            return

        # Clear buffer and section marks
        self.buffer.set_text("")
        self._section_marks.clear()

        content = self._document.content
        lines = content.split('\n')

        in_code_block = False
        code_block_content = []
        code_block_lang = ""
        list_number = 0

        for line in lines:
            # Handle code blocks
            if line.startswith('```'):
                if in_code_block:
                    # End code block
                    self._insert_code_block('\n'.join(code_block_content), code_block_lang)
                    code_block_content = []
                    code_block_lang = ""
                    in_code_block = False
                else:
                    # Start code block
                    in_code_block = True
                    code_block_lang = line[3:].strip()
                continue

            if in_code_block:
                code_block_content.append(line)
                continue

            # Handle headings
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
            if heading_match:
                level = len(heading_match.group(1))
                text = heading_match.group(2)
                self._insert_heading(text, level)
                list_number = 0
                continue

            # Handle horizontal rules
            if re.match(r'^(-{3,}|_{3,}|\*{3,})$', line.strip()):
                self._insert_hr()
                list_number = 0
                continue

            # Handle blockquotes
            if line.startswith('>'):
                quote_text = line[1:].strip()
                self._insert_blockquote(quote_text)
                list_number = 0
                continue

            # Handle unordered lists
            list_match = re.match(r'^(\s*)[-*+]\s+(.+)$', line)
            if list_match:
                indent = len(list_match.group(1))
                text = list_match.group(2)
                self._insert_list_item(text, indent)
                list_number = 0
                continue

            # Handle ordered lists
            ordered_match = re.match(r'^(\s*)(\d+)\.\s+(.+)$', line)
            if ordered_match:
                indent = len(ordered_match.group(1))
                num = int(ordered_match.group(2))
                text = ordered_match.group(3)
                self._insert_ordered_list_item(text, num, indent)
                list_number = num
                continue

            # Regular paragraph
            if line.strip():
                self._insert_paragraph(line)
            else:
                # Empty line
                self._insert_newline()

            list_number = 0

    def _insert_heading(self, text: str, level: int):
        """Insert a heading with appropriate formatting"""
        end_iter = self.buffer.get_end_iter()

        # Create section mark for navigation
        section_name = text.lower().replace(' ', '_')
        mark = self.buffer.create_mark(section_name, end_iter, True)
        self._section_marks[section_name] = mark

        # Insert with heading tag
        tag_name = f'h{min(level, 6)}'
        self.buffer.insert_with_tags_by_name(end_iter, text + '\n', tag_name)

    def _insert_paragraph(self, text: str):
        """Insert a paragraph with inline formatting"""
        end_iter = self.buffer.get_end_iter()
        self._insert_formatted_text(text)
        self.buffer.insert(self.buffer.get_end_iter(), '\n')

    def _insert_formatted_text(self, text: str):
        """
        Insert text with inline formatting (bold, italic, code, links).
        Parses inline markdown syntax.
        """
        # Pattern for inline formatting
        patterns = [
            (r'\*\*\*(.+?)\*\*\*', ['bold', 'italic']),  # Bold italic
            (r'___(.+?)___', ['bold', 'italic']),        # Bold italic alt
            (r'\*\*(.+?)\*\*', ['bold']),                # Bold
            (r'__(.+?)__', ['bold']),                    # Bold alt
            (r'\*(.+?)\*', ['italic']),                  # Italic
            (r'_(.+?)_', ['italic']),                    # Italic alt
            (r'~~(.+?)~~', ['strikethrough']),           # Strikethrough
            (r'`(.+?)`', ['code']),                      # Inline code
            (r'\[(.+?)\]\((.+?)\)', ['link']),           # Links
        ]

        # Simple approach: process text sequentially
        pos = 0
        remaining = text

        while remaining:
            earliest_match = None
            earliest_pos = len(remaining)
            matched_patterns = None

            # Find the earliest match
            for pattern, tags in patterns:
                match = re.search(pattern, remaining)
                if match and match.start() < earliest_pos:
                    earliest_match = match
                    earliest_pos = match.start()
                    matched_patterns = tags

            if earliest_match:
                # Insert text before match
                if earliest_pos > 0:
                    self.buffer.insert(self.buffer.get_end_iter(), remaining[:earliest_pos])

                # Insert matched text with tags
                if 'link' in matched_patterns:
                    # Link has two groups: text and url
                    link_text = earliest_match.group(1)
                    end_iter = self.buffer.get_end_iter()
                    self.buffer.insert_with_tags_by_name(end_iter, link_text, 'link')
                else:
                    # B1 FIX: Apply ALL tags at once instead of only the first
                    formatted_text = earliest_match.group(1)
                    end_iter = self.buffer.get_end_iter()
                    self.buffer.insert_with_tags_by_name(
                        end_iter, formatted_text, *matched_patterns
                    )

                remaining = remaining[earliest_match.end():]
            else:
                # No more matches, insert remaining text
                self.buffer.insert(self.buffer.get_end_iter(), remaining)
                break

    def _insert_code_block(self, code: str, language: str = ""):
        """Insert a code block"""
        end_iter = self.buffer.get_end_iter()
        self.buffer.insert(end_iter, '\n')
        end_iter = self.buffer.get_end_iter()
        self.buffer.insert_with_tags_by_name(end_iter, code + '\n', 'code_block')
        end_iter = self.buffer.get_end_iter()
        self.buffer.insert(end_iter, '\n')

    def _insert_blockquote(self, text: str):
        """Insert a blockquote"""
        end_iter = self.buffer.get_end_iter()
        self.buffer.insert_with_tags_by_name(end_iter, text + '\n', 'blockquote')

    def _insert_list_item(self, text: str, indent: int = 0):
        """Insert an unordered list item"""
        end_iter = self.buffer.get_end_iter()
        bullet = '  ' * (indent // 2) + '\u2022 '  # Bullet character
        self.buffer.insert_with_tags_by_name(end_iter, bullet, 'list_item')
        self._insert_formatted_text(text)
        self.buffer.insert(self.buffer.get_end_iter(), '\n')

    def _insert_ordered_list_item(self, text: str, number: int, indent: int = 0):
        """Insert an ordered list item"""
        end_iter = self.buffer.get_end_iter()
        prefix = '  ' * (indent // 2) + f'{number}. '
        self.buffer.insert_with_tags_by_name(end_iter, prefix, 'ordered_list')
        self._insert_formatted_text(text)
        self.buffer.insert(self.buffer.get_end_iter(), '\n')

    def _insert_hr(self):
        """Insert a horizontal rule"""
        end_iter = self.buffer.get_end_iter()
        self.buffer.insert_with_tags_by_name(end_iter, '\u2500' * 40 + '\n', 'hr')

    def _insert_newline(self):
        """Insert a blank line"""
        self.buffer.insert(self.buffer.get_end_iter(), '\n')

    def scroll_to_section(self, section_name: str) -> bool:
        """
        Scroll the view to a named section.

        Args:
            section_name: The section name (lowercase with underscores)

        Returns:
            True if section was found and scrolled to, False otherwise
        """
        # Normalize section name
        normalized = section_name.lower().replace(' ', '_')

        # Check marks first
        if normalized in self._section_marks:
            mark = self._section_marks[normalized]
            self.scroll_to_mark(mark, 0.1, True, 0.0, 0.0)
            return True

        # Search in document sections
        if self._document:
            for section in self._document.sections:
                if section.name == normalized or section.title.lower() == section_name.lower():
                    # Find mark by section title
                    title_normalized = section.title.lower().replace(' ', '_')
                    if title_normalized in self._section_marks:
                        mark = self._section_marks[title_normalized]
                        self.scroll_to_mark(mark, 0.1, True, 0.0, 0.0)
                        return True

        return False

    def scroll_to_line(self, line: int):
        """
        Scroll to approximate line position.
        Note: Rich view line numbers don't map 1:1 with source.
        """
        if not self._document:
            return

        # Find nearest section at or before this line
        target_section = None
        for section in self._document.sections:
            if section.start_line <= line:
                target_section = section
            else:
                break

        if target_section:
            self.scroll_to_section(target_section.name)

    def sync_with_source_view(self, source_view):
        """
        Setup synchronization with a source view.
        When cursor moves in source, scroll rich view to match.

        Args:
            source_view: WriterSourceView instance to sync with
        """
        self._source_view = source_view

        # Connect to cursor position changes
        if hasattr(source_view, 'buffer'):
            weak_self = weakref.ref(self)

            def on_cursor_changed(buffer, param):
                obj = weak_self()
                if obj is not None and obj._sync_enabled:
                    obj._on_source_cursor_changed(buffer)

            source_view.buffer.connect('notify::cursor-position', on_cursor_changed)

    def _on_source_cursor_changed(self, buffer):
        """Handle cursor change in source view"""
        if not self._sync_enabled:
            return

        insert_mark = buffer.get_insert()
        if insert_mark:
            cursor_iter = buffer.get_iter_at_mark(insert_mark)
            line = cursor_iter.get_line()

            # B10 FIX: Cancel previous debounce timer to prevent leak
            if self._debounce_timer_id is not None:
                GLib.source_remove(self._debounce_timer_id)
            self._debounce_timer_id = GLib.timeout_add(
                100, self._debounced_scroll_to_line, line
            )

    def _debounced_scroll_to_line(self, line):
        """Debounced scroll callback — returns False to auto-remove."""
        self._debounce_timer_id = None
        self.scroll_to_line(line)
        return False

    def set_sync_enabled(self, enabled: bool):
        """Enable or disable source view synchronization"""
        self._sync_enabled = enabled

    def set_theme(self, dark: bool = False):
        """
        Set the color theme for the rich view.

        Args:
            dark: If True, use dark theme colors
        """
        tag_table = self.buffer.get_tag_table()

        if dark:
            # Dark theme
            code_tag = tag_table.lookup('code')
            if code_tag:
                code_tag.set_property('background', '#3d3d3d')
                code_tag.set_property('foreground', '#f8f8f2')

            quote_tag = tag_table.lookup('blockquote')
            if quote_tag:
                quote_tag.set_property('foreground', '#999999')

            link_tag = tag_table.lookup('link')
            if link_tag:
                link_tag.set_property('foreground', '#66b3ff')
        else:
            # Light theme (default)
            code_tag = tag_table.lookup('code')
            if code_tag:
                code_tag.set_property('background', '#f0f0f0')
                code_tag.set_property('foreground', '#333333')

            quote_tag = tag_table.lookup('blockquote')
            if quote_tag:
                quote_tag.set_property('foreground', '#666666')

            link_tag = tag_table.lookup('link')
            if link_tag:
                link_tag.set_property('foreground', '#0066cc')

    def connect_section_clicked(self, callback: Callable[[str], None]):
        """
        Connect callback for section header clicks.

        Args:
            callback: Function called with section name when clicked
        """
        self._on_section_clicked = callback

    def get_visible_sections(self) -> List[str]:
        """
        Get list of section names currently visible in the viewport.

        Returns:
            List of visible section names
        """
        visible = []

        # Get visible area
        visible_rect = self.get_visible_rect()

        for name, mark in self._section_marks.items():
            mark_iter = self.buffer.get_iter_at_mark(mark)
            rect = self.get_iter_location(mark_iter)

            # Check if mark is in visible area
            if (rect.y >= visible_rect.y and
                rect.y <= visible_rect.y + visible_rect.height):
                visible.append(name)

        return visible

    def export_to_pango_markup(self) -> str:
        """
        Export the document as Pango markup string.
        Useful for printing or external rendering.

        Returns:
            Pango markup formatted string
        """
        if not self._document:
            return ""

        lines = []
        content = self._document.content

        for line in content.split('\n'):
            # Headings
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
            if heading_match:
                level = len(heading_match.group(1))
                text = GLib.markup_escape_text(heading_match.group(2))
                sizes = ['xx-large', 'x-large', 'large', 'medium', 'small', 'x-small']
                size = sizes[min(level - 1, 5)]
                lines.append(f'<span size="{size}" weight="bold">{text}</span>')
                continue

            # Process inline formatting
            processed = GLib.markup_escape_text(line)

            # Bold
            processed = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', processed)
            processed = re.sub(r'__(.+?)__', r'<b>\1</b>', processed)

            # Italic
            processed = re.sub(r'\*(.+?)\*', r'<i>\1</i>', processed)
            processed = re.sub(r'_(.+?)_', r'<i>\1</i>', processed)

            # Code
            processed = re.sub(r'`(.+?)`', r'<tt>\1</tt>', processed)

            lines.append(processed)

        return '\n'.join(lines)
