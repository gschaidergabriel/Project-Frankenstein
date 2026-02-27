"""
Formatting Toolbar for Frank Writer - Writer Mode
Word-like WYSIWYG formatting bar using GtkTextTags for visual formatting.
B4 FIX: Link dialog with URL input. Added alignment, line spacing, font picker.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gdk, Pango, GLib, Adw

from typing import Callable, Optional


FONT_SIZES = [10, 11, 12, 14, 16, 18, 20, 24, 28, 32]

HEADING_OPTIONS = [
    ("Normal", 0),
    ("H1", 1),
    ("H2", 2),
    ("H3", 3),
]

FONT_FAMILIES = [
    "Cantarell",
    "Liberation Serif",
    "Liberation Sans",
    "JetBrains Mono",
    "Noto Sans",
    "Noto Serif",
    "DejaVu Sans",
    "DejaVu Serif",
]

LINE_SPACING_OPTIONS = [
    ("1.0", 0),
    ("1.15", 2),
    ("1.5", 6),
    ("2.0", 10),
]


class FormattingToolbar(Gtk.Box):
    """Word-like WYSIWYG formatting toolbar for Writer mode."""

    def __init__(self, get_editor_callback: Callable):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._get_editor = get_editor_callback
        self._current_font_size = 12
        self._updating_heading = False

        self.add_css_class("formatting-toolbar")
        self.set_margin_start(8)
        self.set_margin_end(8)
        self.set_margin_top(4)
        self.set_margin_bottom(4)

        self._build()

    # ── Build ─────────────────────────────────────────────

    def _build(self):
        # Font family dropdown
        self.font_family_dropdown = Gtk.DropDown.new_from_strings(FONT_FAMILIES)
        self.font_family_dropdown.set_selected(0)  # Cantarell default for writer
        self.font_family_dropdown.set_tooltip_text("Font Family")
        self.font_family_dropdown.set_size_request(110, -1)
        self.font_family_dropdown.connect('notify::selected', self._on_font_family_changed)
        self.append(self.font_family_dropdown)

        # Heading dropdown
        self.heading_dropdown = Gtk.DropDown.new_from_strings(
            [h[0] for h in HEADING_OPTIONS]
        )
        self.heading_dropdown.set_selected(0)
        self.heading_dropdown.set_tooltip_text("Paragraph Style")
        self.heading_dropdown.set_size_request(80, -1)
        self.heading_dropdown.connect('notify::selected', self._on_heading_changed)
        self.append(self.heading_dropdown)

        self._sep()

        # Font size dropdown
        self.font_size_dropdown = Gtk.DropDown.new_from_strings(
            [str(s) for s in FONT_SIZES]
        )
        self.font_size_dropdown.set_selected(FONT_SIZES.index(12))
        self.font_size_dropdown.set_tooltip_text("Font Size")
        self.font_size_dropdown.set_size_request(60, -1)
        self.font_size_dropdown.connect('notify::selected', self._on_font_size_changed)
        self.append(self.font_size_dropdown)

        self._sep()

        # Bold
        self.bold_btn = self._fmt_btn("B", "Bold (Ctrl+B)", "format-bold")
        self.bold_btn.connect('clicked', lambda _: self.apply_bold())
        self.append(self.bold_btn)

        # Italic
        self.italic_btn = self._fmt_btn("I", "Italic (Ctrl+I)", "format-italic")
        self.italic_btn.connect('clicked', lambda _: self.apply_italic())
        self.append(self.italic_btn)

        # Underline
        self.underline_btn = self._fmt_btn("U", "Underline (Ctrl+U)", "format-underline")
        self.underline_btn.connect('clicked', lambda _: self.apply_underline())
        self.append(self.underline_btn)

        # Strikethrough
        self.strike_btn = self._fmt_btn("S", "Strikethrough", "format-strike")
        self.strike_btn.connect('clicked', lambda _: self.apply_strikethrough())
        self.append(self.strike_btn)

        self._sep()

        # Alignment buttons
        align_left_btn = Gtk.Button(icon_name="format-justify-left-symbolic")
        align_left_btn.set_tooltip_text("Align Left")
        align_left_btn.connect('clicked', lambda _: self._apply_alignment(Gtk.Justification.LEFT))
        self.append(align_left_btn)

        align_center_btn = Gtk.Button(icon_name="format-justify-center-symbolic")
        align_center_btn.set_tooltip_text("Center")
        align_center_btn.connect('clicked', lambda _: self._apply_alignment(Gtk.Justification.CENTER))
        self.append(align_center_btn)

        align_right_btn = Gtk.Button(icon_name="format-justify-right-symbolic")
        align_right_btn.set_tooltip_text("Align Right")
        align_right_btn.connect('clicked', lambda _: self._apply_alignment(Gtk.Justification.RIGHT))
        self.append(align_right_btn)

        align_fill_btn = Gtk.Button(icon_name="format-justify-fill-symbolic")
        align_fill_btn.set_tooltip_text("Justify")
        align_fill_btn.connect('clicked', lambda _: self._apply_alignment(Gtk.Justification.FILL))
        self.append(align_fill_btn)

        self._sep()

        # Line spacing dropdown
        self.line_spacing_dropdown = Gtk.DropDown.new_from_strings(
            [label for label, _ in LINE_SPACING_OPTIONS]
        )
        self.line_spacing_dropdown.set_selected(0)
        self.line_spacing_dropdown.set_tooltip_text("Line Spacing")
        self.line_spacing_dropdown.set_size_request(55, -1)
        self.line_spacing_dropdown.connect('notify::selected', self._on_line_spacing_changed)
        self.append(self.line_spacing_dropdown)

        self._sep()

        # Color
        self._current_color = Gdk.RGBA()
        self._current_color.parse("#ff0000")
        self.color_btn = Gtk.Button()
        color_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._color_label = Gtk.Label(label="A")
        self._color_label.add_css_class("format-bold")
        color_box.append(self._color_label)
        # Color indicator bar via CSS (no cairo needed)
        self._color_bar = Gtk.Box()
        self._color_bar.set_size_request(18, 3)
        self._color_css = Gtk.CssProvider()
        self._color_bar.get_style_context().add_provider(
            self._color_css, Gtk.STYLE_PROVIDER_PRIORITY_USER
        )
        self._update_color_indicator()
        color_box.append(self._color_bar)
        self.color_btn.set_child(color_box)
        self.color_btn.set_tooltip_text("Text Color")
        self.color_btn.connect('clicked', self._on_color_clicked)
        self.append(self.color_btn)

        self._sep()

        # Bullet list
        bullet_btn = Gtk.Button(icon_name="view-list-symbolic")
        bullet_btn.set_tooltip_text("Bullet List")
        bullet_btn.connect('clicked', lambda _: self._toggle_line_prefix("- "))
        self.append(bullet_btn)

        # Numbered list
        num_btn = Gtk.Button(icon_name="view-list-ordered-symbolic")
        num_btn.set_tooltip_text("Numbered List")
        num_btn.connect('clicked', lambda _: self._toggle_line_prefix("1. "))
        self.append(num_btn)

        self._sep()

        # Code (monospace)
        code_btn = Gtk.Button(icon_name="utilities-terminal-symbolic")
        code_btn.set_tooltip_text("Code (Monospace)")
        code_btn.connect('clicked', lambda _: self._apply_monospace())
        self.append(code_btn)

        # Link — B4 FIX: proper dialog instead of literal [text](url)
        link_btn = Gtk.Button(icon_name="insert-link-symbolic")
        link_btn.set_tooltip_text("Insert Link")
        link_btn.connect('clicked', self._on_link)
        self.append(link_btn)

    # ── Helpers ───────────────────────────────────────────

    def _sep(self):
        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep.set_margin_start(2)
        sep.set_margin_end(2)
        self.append(sep)

    def _fmt_btn(self, label: str, tooltip: str, css_class: str) -> Gtk.Button:
        btn = Gtk.Button()
        lbl = Gtk.Label(label=label)
        btn.set_child(lbl)
        btn.set_tooltip_text(tooltip)
        btn.add_css_class(css_class)
        return btn

    def _update_color_indicator(self):
        """Update color indicator bar via CSS."""
        r = int(self._current_color.red * 255)
        g = int(self._current_color.green * 255)
        b = int(self._current_color.blue * 255)
        css = f"box {{ background-color: #{r:02x}{g:02x}{b:02x}; min-height: 3px; }}"
        self._color_css.load_from_string(css)

    # ── Public formatting methods (called by shortcuts) ──

    def apply_bold(self):
        """Toggle bold on selection (visual, like Word)."""
        editor = self._get_editor()
        if editor:
            editor.toggle_format_tag("bold")

    def apply_italic(self):
        """Toggle italic on selection (visual, like Word)."""
        editor = self._get_editor()
        if editor:
            editor.toggle_format_tag("italic")

    def apply_underline(self):
        """Toggle underline on selection (visual, like Word)."""
        editor = self._get_editor()
        if editor:
            editor.toggle_format_tag("underline")

    def apply_strikethrough(self):
        """Toggle strikethrough on selection (visual, like Word)."""
        editor = self._get_editor()
        if editor:
            editor.toggle_format_tag("strikethrough")

    # ── Font Family ──────────────────────────────────────

    def _on_font_family_changed(self, dropdown, _param):
        idx = dropdown.get_selected()
        if idx < 0 or idx >= len(FONT_FAMILIES):
            return
        family = FONT_FAMILIES[idx]

        editor = self._get_editor()
        if not editor:
            return

        css = (
            f"textview {{ font-family: '{family}'; }}\n"
            f"textview text {{ font-family: '{family}'; }}"
        )
        if not hasattr(editor, '_font_family_css'):
            editor._font_family_css = Gtk.CssProvider()
            editor.get_style_context().add_provider(
                editor._font_family_css, Gtk.STYLE_PROVIDER_PRIORITY_USER
            )
        editor._font_family_css.load_from_string(css)

    # ── Heading (visual) ─────────────────────────────────

    def _on_heading_changed(self, dropdown, _param):
        if self._updating_heading:
            return
        editor = self._get_editor()
        if not editor:
            return

        idx = dropdown.get_selected()
        if idx < 0 or idx >= len(HEADING_OPTIONS):
            return

        _, level = HEADING_OPTIONS[idx]
        editor.apply_heading_to_line(level)

    # ── Font Size ─────────────────────────────────────────

    def _on_font_size_changed(self, dropdown, _param):
        idx = dropdown.get_selected()
        if idx < 0 or idx >= len(FONT_SIZES):
            return

        size = FONT_SIZES[idx]
        self._current_font_size = size

        editor = self._get_editor()
        if not editor:
            return

        # Apply via per-widget CSS provider (overrides theme)
        css = (
            f"textview {{ font-size: {size}pt; }}\n"
            f"textview text {{ font-size: {size}pt; }}"
        )
        if not hasattr(editor, '_font_css_provider'):
            editor._font_css_provider = Gtk.CssProvider()
            editor.get_style_context().add_provider(
                editor._font_css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_USER
            )
        editor._font_css_provider.load_from_string(css)

    # ── Alignment ────────────────────────────────────────

    def _apply_alignment(self, justification):
        """Apply text alignment to the editor view."""
        editor = self._get_editor()
        if not editor:
            return
        editor.set_justification(justification)

    # ── Line Spacing ─────────────────────────────────────

    def _on_line_spacing_changed(self, dropdown, _param):
        idx = dropdown.get_selected()
        if idx < 0 or idx >= len(LINE_SPACING_OPTIONS):
            return

        _, pixels = LINE_SPACING_OPTIONS[idx]
        editor = self._get_editor()
        if not editor:
            return

        editor.set_pixels_above_lines(pixels // 2)
        editor.set_pixels_below_lines(pixels // 2)
        editor.set_pixels_inside_wrap(max(1, pixels // 3))

    # ── Color (visual tag) ────────────────────────────────

    def _on_color_clicked(self, _btn):
        window = self.get_root()

        if hasattr(Gtk, 'ColorDialog'):
            dialog = Gtk.ColorDialog()
            dialog.set_title("Text Color")
            dialog.choose_rgba(window, self._current_color, None, self._on_color_chosen)
        else:
            dialog = Gtk.ColorChooserDialog(
                title="Text Color",
                transient_for=window,
                modal=True,
            )
            dialog.set_rgba(self._current_color)
            dialog.connect('response', self._on_color_chooser_response)
            dialog.present()

    def _on_color_chosen(self, dialog, result):
        try:
            rgba = dialog.choose_rgba_finish(result)
        except GLib.Error:
            return

        if rgba:
            self._apply_color(rgba)

    def _on_color_chooser_response(self, dialog, response):
        if response == Gtk.ResponseType.OK:
            rgba = dialog.get_rgba()
            self._apply_color(rgba)
        dialog.destroy()

    def _apply_color(self, rgba):
        self._current_color = rgba
        self._update_color_indicator()

        r = int(rgba.red * 255)
        g = int(rgba.green * 255)
        b = int(rgba.blue * 255)
        hex_color = f"#{r:02x}{g:02x}{b:02x}"

        editor = self._get_editor()
        if editor:
            editor.apply_color_tag(hex_color)

    # ── Code (monospace tag) ──────────────────────────────

    def _apply_monospace(self):
        editor = self._get_editor()
        if editor:
            editor.toggle_format_tag("monospace")

    # ── Line prefix (bullets, numbers) ────────────────────

    def _toggle_line_prefix(self, prefix: str):
        """Add/remove prefix at start of current line."""
        editor = self._get_editor()
        if not editor:
            return

        buf = editor.buffer
        cursor = buf.get_iter_at_mark(buf.get_insert())
        line = cursor.get_line()

        line_start = buf.get_iter_at_line(line)
        line_end = line_start.copy()
        if not line_end.ends_line():
            line_end.forward_to_line_end()
        line_text = buf.get_text(line_start, line_end, True)

        buf.begin_user_action()
        if line_text.startswith(prefix):
            prefix_end = buf.get_iter_at_line_offset(line, len(prefix))
            buf.delete(line_start, prefix_end)
        else:
            buf.insert(buf.get_iter_at_line(line), prefix)
        buf.end_user_action()

    # ── Link — B4 FIX: proper dialog with URL input ──────

    def _on_link(self, _btn):
        editor = self._get_editor()
        if not editor:
            return

        selected = editor.get_selected_text() or ""
        window = self.get_root()

        dialog = Adw.MessageDialog(
            transient_for=window,
            heading="Insert Link",
            body="Enter the link text and URL:"
        )

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(12)
        box.set_margin_end(12)

        text_entry = Gtk.Entry()
        text_entry.set_placeholder_text("Link text")
        if selected:
            text_entry.set_text(selected)
        box.append(text_entry)

        url_entry = Gtk.Entry()
        url_entry.set_placeholder_text("https://...")
        box.append(url_entry)

        dialog.set_extra_child(box)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("insert", "Insert")
        dialog.set_response_appearance("insert", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect('response', self._on_link_response, text_entry, url_entry, editor)
        dialog.present()

        # Focus the URL entry since text is often pre-filled
        url_entry.grab_focus()

    def _on_link_response(self, dialog, response, text_entry, url_entry, editor):
        if response != "insert":
            return

        link_text = text_entry.get_text().strip() or "Link"
        url = url_entry.get_text().strip()
        if not url:
            return

        md_link = f"[{link_text}]({url})"
        buf = editor.buffer
        buf.begin_user_action()
        if editor.get_selected_text():
            editor.replace_selection(md_link)
        else:
            buf.insert_at_cursor(md_link)
        buf.end_user_action()
