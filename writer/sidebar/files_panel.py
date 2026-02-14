"""
Files Panel - Project File Tree (Coding Mode)
"""

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio, GLib

from typing import Callable, Optional
from pathlib import Path


class FilesPanel(Gtk.Box):
    """Panel showing project files"""

    # File type icons
    ICONS = {
        '.py': 'text-x-python-symbolic',
        '.js': 'text-x-javascript-symbolic',
        '.ts': 'text-x-javascript-symbolic',
        '.html': 'text-html-symbolic',
        '.css': 'text-css-symbolic',
        '.json': 'text-x-generic-symbolic',
        '.yaml': 'text-x-generic-symbolic',
        '.yml': 'text-x-generic-symbolic',
        '.md': 'text-x-generic-symbolic',
        '.txt': 'text-x-generic-symbolic',
        '.sh': 'text-x-script-symbolic',
        'default': 'text-x-generic-symbolic',
        'folder': 'folder-symbolic',
    }

    def __init__(self, on_file_selected: Callable):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.on_file_selected = on_file_selected
        self.root_path = None

        self.set_margin_start(6)
        self.set_margin_end(6)
        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_spacing(6)

        self._build_ui()

    def _build_ui(self):
        """Build panel UI"""
        # Header with folder button
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        self.path_label = Gtk.Label(label="Kein Projekt")
        self.path_label.add_css_class("dim-label")
        self.path_label.set_ellipsize(True)
        self.path_label.set_hexpand(True)
        self.path_label.set_halign(Gtk.Align.START)
        header.append(self.path_label)

        open_btn = Gtk.Button(icon_name="folder-open-symbolic")
        open_btn.set_tooltip_text("Ordner öffnen")
        open_btn.connect('clicked', self._on_open_folder)
        header.append(open_btn)

        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Aktualisieren")
        refresh_btn.connect('clicked', lambda b: self._refresh())
        header.append(refresh_btn)

        self.append(header)

        # Scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        # Tree view
        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list_box.connect('row-activated', self._on_row_activated)
        scrolled.set_child(self.list_box)

        self.append(scrolled)

    def set_root_path(self, path: Path):
        """Set root path for file tree"""
        self.root_path = Path(path) if path else None
        if self.root_path:
            self.path_label.set_label(self.root_path.name)
        else:
            self.path_label.set_label("Kein Projekt")
        self._refresh()

    def _refresh(self):
        """Refresh file tree"""
        # Clear existing
        while True:
            row = self.list_box.get_row_at_index(0)
            if row is None:
                break
            self.list_box.remove(row)

        if not self.root_path or not self.root_path.exists():
            return

        # Add files
        self._add_directory(self.root_path, 0)

    def _add_directory(self, path: Path, depth: int):
        """Add directory contents to tree"""
        if depth > 5:  # Limit depth
            return

        try:
            items = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return

        for item in items:
            # Skip hidden files and common ignores
            if item.name.startswith('.') or item.name in ['__pycache__', 'node_modules', 'venv', '.git']:
                continue

            row = self._create_file_row(item, depth)
            self.list_box.append(row)

            # Recursively add subdirectories
            if item.is_dir():
                self._add_directory(item, depth + 1)

    def _create_file_row(self, path: Path, depth: int) -> Gtk.ListBoxRow:
        """Create file/folder row"""
        row = Gtk.ListBoxRow()
        row._path = str(path)
        row._is_dir = path.is_dir()

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_margin_start(depth * 16)
        box.set_margin_top(2)
        box.set_margin_bottom(2)

        # Icon
        if path.is_dir():
            icon_name = self.ICONS['folder']
        else:
            icon_name = self.ICONS.get(path.suffix.lower(), self.ICONS['default'])

        icon = Gtk.Image.new_from_icon_name(icon_name)
        box.append(icon)

        # Name
        label = Gtk.Label(label=path.name)
        label.set_halign(Gtk.Align.START)
        box.append(label)

        row.set_child(box)
        return row

    def _on_row_activated(self, list_box, row):
        """Handle row activation"""
        if hasattr(row, '_path') and not row._is_dir:
            self.on_file_selected(row._path)

    def _on_open_folder(self, button):
        """Open folder dialog"""
        dialog = Gtk.FileDialog()
        dialog.set_title("Projektordner öffnen")

        # We need a window to show the dialog - check that get_root() is not None
        window = self.get_root()
        if window is not None:
            dialog.select_folder(window, None, self._on_folder_selected)

    def _on_folder_selected(self, dialog, result):
        """Handle folder selection"""
        try:
            folder = dialog.select_folder_finish(result)
            if folder:
                self.set_root_path(Path(folder.get_path()))
        except GLib.Error as e:
            import logging
            logging.getLogger(__name__).debug(f"Folder selection cancelled or failed: {e}")
