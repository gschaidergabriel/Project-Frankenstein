"""
Sidebar Manager for Frank Writer
Manages all sidebar panels
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Pango

from typing import Callable, Optional
from pathlib import Path

from writer.sidebar.chat_panel import ChatPanel
from writer.sidebar.templates_panel import TemplatesPanel
from writer.sidebar.outline_panel import OutlinePanel
from writer.sidebar.files_panel import FilesPanel


class SidebarManager(Gtk.Box):
    """Manages sidebar panels"""

    def __init__(self, config, frank_bridge, on_action: Callable):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.config = config
        self.frank_bridge = frank_bridge
        self.on_action = on_action
        self.mode = 'writer'

        self.set_size_request(280, -1)
        self.add_css_class("sidebar")

        self._build_ui()

    def _build_ui(self):
        """Build sidebar UI"""
        # Stack for panels
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_vexpand(True)

        # Templates panel (Writer mode)
        self.templates_panel = TemplatesPanel(
            config=self.config,
            on_select=self._on_template_selected
        )
        self.stack.add_titled(self.templates_panel, "templates", "Templates")

        # Files panel (Coding mode)
        self.files_panel = FilesPanel(
            on_file_selected=self._on_file_selected
        )
        self.stack.add_titled(self.files_panel, "files", "Files")

        # Outline panel
        self.outline_panel = OutlinePanel(
            on_section_clicked=self._on_section_clicked
        )
        self.stack.add_titled(self.outline_panel, "outline", "Outline")

        # Stack switcher
        self.stack_switcher = Gtk.StackSwitcher()
        self.stack_switcher.set_stack(self.stack)
        self.stack_switcher.set_margin_start(6)
        self.stack_switcher.set_margin_end(6)
        self.stack_switcher.set_margin_top(6)
        self.stack_switcher.set_margin_bottom(6)
        self.append(self.stack_switcher)

        # Add stack
        self.append(self.stack)

        # Separator
        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Chat panel (always visible at bottom)
        self.chat_panel = ChatPanel(
            frank_bridge=self.frank_bridge,
            on_action=self._on_chat_action
        )
        self.chat_panel.set_vexpand(True)
        self.chat_panel.set_size_request(-1, 300)
        self.append(self.chat_panel)

    def set_mode(self, mode: str):
        """Set sidebar mode"""
        self.mode = mode
        if mode == 'coding':
            self.stack.set_visible_child_name("files")
        else:
            self.stack.set_visible_child_name("templates")

    def set_document(self, document):
        """Set current document for outline"""
        self.outline_panel.set_document(document)

    def set_project_path(self, path: Path):
        """Set project path for files panel"""
        self.files_panel.set_root_path(path)

    def _on_template_selected(self, schema_type: str):
        """Handle template selection"""
        self.on_action('new', {'schema': schema_type})

    def _on_file_selected(self, path: str):
        """Handle file selection"""
        self.on_action('open', {'path': path})

    def _on_section_clicked(self, line: int):
        """Handle section click in outline"""
        self.on_action('goto_line', {'line': line})

    def _on_chat_action(self, action: str, data: dict = None):
        """Handle chat panel action"""
        # Default data to empty dict if None
        if data is None:
            data = {}
        self.on_action(action, data)


class SidebarPanel(Gtk.Box):
    """Base class for sidebar panels"""

    def __init__(self, title: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_margin_start(6)
        self.set_margin_end(6)
        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_spacing(6)

        # Title
        title_label = Gtk.Label(label=title)
        title_label.add_css_class("heading")
        title_label.set_halign(Gtk.Align.START)
        self.append(title_label)
