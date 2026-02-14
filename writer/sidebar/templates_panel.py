"""
Templates Panel for Writer Mode
"""

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio, GLib

from typing import Callable
from pathlib import Path
import yaml


class TemplatesPanel(Gtk.Box):
    """Panel showing available document templates"""

    CATEGORIES = [
        ('academic', 'Akademisch', 'school-symbolic'),
        ('business', 'Business', 'briefcase-symbolic'),
        ('creative', 'Kreativ', 'edit-symbolic'),
        ('technical', 'Technisch', 'utilities-terminal-symbolic'),
        ('personal', 'Persönlich', 'user-symbolic'),
        ('code', 'Code', 'code-symbolic'),
    ]

    def __init__(self, config, on_select: Callable):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.config = config
        self.on_select = on_select

        self.set_margin_start(6)
        self.set_margin_end(6)
        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_spacing(12)

        self._build_ui()
        self._load_templates()

    def _build_ui(self):
        """Build panel UI"""
        # Search entry
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Suchen...")
        self.search_entry.connect('search-changed', self._on_search_changed)
        self.append(self.search_entry)

        # Scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        # Templates list
        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.list_box.add_css_class("boxed-list")
        scrolled.set_child(self.list_box)

        self.append(scrolled)

    def _load_templates(self):
        """Load templates from schemas directory"""
        schemas_dir = self.config.schemas_dir

        for category_id, category_name, icon_name in self.CATEGORIES:
            category_path = schemas_dir / category_id

            # Category header
            header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            header.set_margin_top(12)
            header.set_margin_bottom(6)

            icon = Gtk.Image.new_from_icon_name(icon_name)
            header.append(icon)

            label = Gtk.Label(label=category_name)
            label.add_css_class("heading")
            header.append(label)

            header_row = Gtk.ListBoxRow()
            header_row.set_activatable(False)
            header_row.set_selectable(False)
            header_row.set_child(header)
            header_row._is_header = True
            self.list_box.append(header_row)

            # Load schemas in category
            if category_path.exists():
                for schema_file in sorted(category_path.glob('*.yaml')):
                    try:
                        with open(schema_file, 'r') as f:
                            schema = yaml.safe_load(f)

                        schema_info = schema.get('schema', {})
                        name = schema_info.get('name', schema_file.stem)
                        description = schema_info.get('description', '')

                        # Build structure preview (P3-37)
                        sections = schema.get('structure', [])
                        preview_lines = [f"<b>{name}</b>"]
                        if description:
                            preview_lines.append(description)
                        preview_lines.append("")
                        for sec in sections[:8]:
                            sec_name = sec.get('section', '')
                            required = "●" if sec.get('required') else "○"
                            preview_lines.append(f"  {required} {sec_name}")
                        if len(sections) > 8:
                            preview_lines.append(f"  ... +{len(sections) - 8} weitere")
                        preview_text = "\n".join(preview_lines)

                        row = self._create_template_row(
                            name, schema_file.stem, category_id,
                            description, preview_text
                        )
                        self.list_box.append(row)
                    except Exception as e:
                        import logging
                        logging.getLogger(__name__).error(f"Error loading schema {schema_file}: {e}")

    def _create_template_row(self, name: str, schema_id: str, category: str,
                              description: str = "",
                              preview_text: str = "") -> Gtk.ListBoxRow:
        """Create a template row with preview tooltip (P3-37)"""
        row = Gtk.ListBoxRow()
        row._schema_id = schema_id
        row._category = category
        row._name = name

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_start(24)  # Indent under category
        box.set_margin_top(4)
        box.set_margin_bottom(4)

        # Template info
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        label = Gtk.Label(label=name)
        label.set_halign(Gtk.Align.START)
        info_box.append(label)

        if description:
            desc_label = Gtk.Label(label=description)
            desc_label.add_css_class("dim-label")
            desc_label.set_halign(Gtk.Align.START)
            desc_label.set_ellipsize(True)
            desc_label.set_max_width_chars(30)
            info_box.append(desc_label)

        info_box.set_hexpand(True)
        box.append(info_box)

        # Set markup tooltip with structure preview (P3-37)
        if preview_text:
            box.set_tooltip_markup(preview_text)

        # Create button
        btn = Gtk.Button(icon_name="list-add-symbolic")
        btn.add_css_class("flat")
        btn.set_tooltip_text(f"Neues {name}")
        btn.connect('clicked', lambda b: self.on_select(f"{category}/{schema_id}"))
        box.append(btn)

        row.set_child(box)
        return row

    def _on_search_changed(self, entry):
        """Handle search input"""
        search_text = entry.get_text().lower()

        # GTK4 pattern: iterate through children using get_first_child/get_next_sibling
        child = self.list_box.get_first_child()
        while child is not None:
            row = child
            child = child.get_next_sibling()

            if hasattr(row, '_is_header') and row._is_header:
                continue

            if hasattr(row, '_name'):
                visible = search_text in row._name.lower()
                row.set_visible(visible)
