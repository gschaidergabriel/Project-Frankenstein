"""
Outline Panel - Document Structure View
B9 FIX: efficient clearing, collapse/expand, keyboard nav
"""

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, Pango

from typing import Callable, Optional
from writer.editor.document import Document


class OutlinePanel(Gtk.Box):
    """Panel showing document outline/structure with collapse support."""

    def __init__(self, on_section_clicked: Callable):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.on_section_clicked = on_section_clicked
        self.document = None
        self._collapsed_sections = set()  # Track collapsed H1 sections

        self.set_margin_start(6)
        self.set_margin_end(6)
        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_spacing(6)

        self._build_ui()

    def _build_ui(self):
        """Build panel UI"""
        # Toolbar with collapse/expand all
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        expand_btn = Gtk.Button(icon_name="list-add-symbolic")
        expand_btn.set_tooltip_text("Alle aufklappen")
        expand_btn.add_css_class("flat")
        expand_btn.connect('clicked', lambda b: self._expand_all())
        toolbar.append(expand_btn)

        collapse_btn = Gtk.Button(icon_name="list-remove-symbolic")
        collapse_btn.set_tooltip_text("Alle zuklappen")
        collapse_btn.add_css_class("flat")
        collapse_btn.connect('clicked', lambda b: self._collapse_all())
        toolbar.append(collapse_btn)

        self.append(toolbar)

        # Scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        # List box for outline
        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list_box.connect('row-activated', self._on_row_activated)
        scrolled.set_child(self.list_box)

        # Keyboard navigation
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect('key-pressed', self._on_key_pressed)
        self.list_box.add_controller(key_ctrl)

        self.append(scrolled)

        # Empty state
        self.empty_label = Gtk.Label(label="Keine Struktur erkannt")
        self.empty_label.add_css_class("dim-label")
        self.append(self.empty_label)

    def set_document(self, document: Optional[Document]):
        """Set document to show outline for"""
        self.document = document
        self._update_outline()

    def _update_outline(self):
        """Update outline display"""
        # B9 FIX: Efficient clearing — use remove_all if available, else batch remove
        self.list_box.remove_all()

        if not self.document:
            self.empty_label.set_visible(True)
            return

        outline = self.document.get_outline()

        if not outline:
            self.empty_label.set_visible(True)
            return

        self.empty_label.set_visible(False)

        current_h1_title = None
        for item in outline:
            level = item.get('level', 1)
            title = item.get('title', '')

            if level == 1:
                current_h1_title = title

            row = self._create_outline_row(item)

            # Handle collapse: hide children of collapsed H1 sections
            if level > 1 and current_h1_title in self._collapsed_sections:
                row.set_visible(False)

            self.list_box.append(row)

    def _create_outline_row(self, item: dict) -> Gtk.ListBoxRow:
        """Create outline row with collapse toggle for H1"""
        row = Gtk.ListBoxRow()
        row._line = item.get('line', 0)
        row._level = item.get('level', 1)
        row._title = item.get('title', '')

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        # Indent based on level
        level = item.get('level', 1)
        indent = (level - 1) * 16
        box.set_margin_start(indent)
        box.set_margin_top(3)
        box.set_margin_bottom(3)

        # Collapse/expand toggle for H1
        if level == 1:
            is_collapsed = item.get('title', '') in self._collapsed_sections
            toggle_icon = "go-next-symbolic" if is_collapsed else "go-down-symbolic"
            toggle_btn = Gtk.Button(icon_name=toggle_icon)
            toggle_btn.add_css_class("flat")
            toggle_btn.add_css_class("circular")
            toggle_btn.set_valign(Gtk.Align.CENTER)
            toggle_btn.connect('clicked', self._on_toggle_collapse, item.get('title', ''))
            box.append(toggle_btn)
        else:
            # Icon based on level
            if level == 2:
                icon = Gtk.Image.new_from_icon_name("go-next-symbolic")
            else:
                icon = Gtk.Image.new_from_icon_name("document-symbolic")
            icon.add_css_class("dim-label")
            box.append(icon)

        # Title
        label = Gtk.Label(label=item.get('title', ''))
        label.set_halign(Gtk.Align.START)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_max_width_chars(25)

        if level == 1:
            label.add_css_class("heading")

        box.append(label)

        # Line number suffix
        line_label = Gtk.Label(label=str(item.get('line', 0) + 1))
        line_label.add_css_class("dim-label")
        line_label.set_hexpand(True)
        line_label.set_halign(Gtk.Align.END)
        box.append(line_label)

        row.set_child(box)
        return row

    def _on_row_activated(self, list_box, row):
        """Handle row activation"""
        if hasattr(row, '_line'):
            self.on_section_clicked(row._line)

    def _on_toggle_collapse(self, button, title):
        """Toggle collapse state for an H1 section."""
        if title in self._collapsed_sections:
            self._collapsed_sections.discard(title)
        else:
            self._collapsed_sections.add(title)
        self._update_outline()

    def _collapse_all(self):
        """Collapse all H1 sections."""
        if not self.document:
            return
        outline = self.document.get_outline()
        for item in outline:
            if item.get('level', 1) == 1:
                self._collapsed_sections.add(item.get('title', ''))
        self._update_outline()

    def _expand_all(self):
        """Expand all sections."""
        self._collapsed_sections.clear()
        self._update_outline()

    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Keyboard navigation for outline."""
        row = self.list_box.get_selected_row()
        if not row:
            return False

        if keyval == Gdk.KEY_Return or keyval == Gdk.KEY_KP_Enter:
            if hasattr(row, '_line'):
                self.on_section_clicked(row._line)
            return True
        elif keyval == Gdk.KEY_Left:
            # Collapse current section or move to parent
            if hasattr(row, '_level') and row._level == 1:
                if hasattr(row, '_title') and row._title not in self._collapsed_sections:
                    self._collapsed_sections.add(row._title)
                    self._update_outline()
                    return True
        elif keyval == Gdk.KEY_Right:
            # Expand current section
            if hasattr(row, '_level') and row._level == 1:
                if hasattr(row, '_title') and row._title in self._collapsed_sections:
                    self._collapsed_sections.discard(row._title)
                    self._update_outline()
                    return True
        return False
