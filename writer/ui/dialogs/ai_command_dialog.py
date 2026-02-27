"""
AI Command Palette Dialog
Quick access to AI actions — B2 FIX: passes selected_text properly
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk


class AICommandDialog(Adw.Window):
    """AI command palette"""

    COMMANDS = [
        # Writer mode commands
        ('rewrite', 'Rewrite', 'Rephrase text', 'writer'),
        ('expand', 'Expand', 'Add more details', 'writer'),
        ('shorten', 'Shorten', 'Compress text', 'writer'),
        ('formalize', 'Formalize', 'Academic/formal tone', 'writer'),
        ('simplify', 'Simplify', 'Simpler language', 'writer'),
        ('translate_en', 'To English', 'Translate to English', 'writer'),
        ('translate_de', 'To German', 'Translate to German', 'writer'),
        ('structure', 'Suggest Structure', 'Generate outline', 'writer'),

        # Coding mode commands
        ('explain', 'Explain', 'Explain code', 'coding'),
        ('refactor', 'Refactor', 'Improve code', 'coding'),
        ('document', 'Document', 'Generate docstrings', 'coding'),
        ('test', 'Generate Tests', 'Create unit tests', 'coding'),
        ('debug', 'Find Bug', 'Identify errors', 'coding'),
        ('optimize', 'Optimize', 'Improve performance', 'coding'),
        ('types', 'Add Types', 'Add type hints', 'coding'),

        # Both modes
        ('continue', 'Continue', 'Continue text/code', 'both'),
        ('custom', 'Custom Instruction...', 'Free input', 'both'),
    ]

    def __init__(self, parent, document, frank_bridge, mode='writer', selected_text=""):
        super().__init__()
        self.parent_window = parent
        self.document = document
        self.frank_bridge = frank_bridge
        self.mode = mode
        self.selected_text = selected_text  # B2 FIX: accept selected text

        self._setup_window()
        self._build_ui()
        self._setup_shortcuts()

    def _setup_window(self):
        self.set_title("AI Command")
        self.set_default_size(500, 400)
        self.set_transient_for(self.parent_window)
        self.set_modal(True)
        self.set_decorated(True)

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # Info label if text is selected
        if self.selected_text:
            preview = self.selected_text[:80] + ("..." if len(self.selected_text) > 80 else "")
            info = Gtk.Label(label=f"Selection: \"{preview}\"")
            info.add_css_class("dim-label")
            info.set_ellipsize(True)
            info.set_margin_start(12)
            info.set_margin_end(12)
            info.set_margin_top(8)
            main_box.append(info)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Search command...")
        self.search_entry.set_margin_start(12)
        self.search_entry.set_margin_end(12)
        self.search_entry.set_margin_top(12)
        self.search_entry.set_margin_bottom(6)
        self.search_entry.connect('search-changed', self._on_search_changed)
        self.search_entry.connect('activate', self._on_activate_selected)
        main_box.append(self.search_entry)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list_box.connect('row-activated', self._on_row_activated)
        self.list_box.add_css_class("boxed-list")
        scrolled.set_child(self.list_box)
        main_box.append(scrolled)

        self._populate_commands()
        self.search_entry.grab_focus()

    def _populate_commands(self):
        icon_map = {
            'rewrite': 'edit-symbolic',
            'expand': 'list-add-symbolic',
            'shorten': 'list-remove-symbolic',
            'explain': 'help-about-symbolic',
            'refactor': 'emblem-synchronizing-symbolic',
            'document': 'text-x-generic-symbolic',
            'test': 'emblem-ok-symbolic',
            'debug': 'bug-symbolic',
            'continue': 'go-next-symbolic',
            'custom': 'system-search-symbolic',
        }

        for cmd_id, cmd_name, cmd_desc, cmd_mode in self.COMMANDS:
            if cmd_mode != 'both' and cmd_mode != self.mode:
                continue

            row = Adw.ActionRow(title=cmd_name, subtitle=cmd_desc)
            row._command_id = cmd_id
            row._searchable = f"{cmd_name} {cmd_desc}".lower()

            icon_name = icon_map.get(cmd_id, 'go-next-symbolic')
            icon = Gtk.Image.new_from_icon_name(icon_name)
            row.add_prefix(icon)
            self.list_box.append(row)

        first_row = self.list_box.get_row_at_index(0)
        if first_row:
            self.list_box.select_row(first_row)

    def _on_search_changed(self, entry):
        search_text = entry.get_text().lower()
        idx = 0
        while True:
            row = self.list_box.get_row_at_index(idx)
            if row is None:
                break
            if hasattr(row, '_searchable'):
                row.set_visible(search_text in row._searchable)
            idx += 1

    def _on_row_activated(self, list_box, row):
        if hasattr(row, '_command_id'):
            self._execute_command(row._command_id)

    def _on_activate_selected(self, entry):
        row = self.list_box.get_selected_row()
        if row and hasattr(row, '_command_id'):
            self._execute_command(row._command_id)

    def _execute_command(self, command_id: str):
        self.close()

        if command_id == 'custom':
            self._show_custom_input()
        else:
            # B2 FIX: pass actual selected text to the action
            self.parent_window._apply_ai_action(command_id, {
                'text': self.selected_text
            })

    def _show_custom_input(self):
        dialog = Adw.MessageDialog(
            transient_for=self.parent_window,
            heading="Custom Instruction",
            body="Describe what Frank should do:"
        )

        entry = Gtk.Entry()
        entry.set_margin_start(12)
        entry.set_margin_end(12)
        dialog.set_extra_child(entry)

        dialog.add_response("cancel", "Cancel")
        dialog.add_response("execute", "Execute")
        dialog.set_response_appearance("execute", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect('response', self._on_custom_response, entry)
        dialog.present()

    def _on_custom_response(self, dialog, response, entry):
        if response == "execute":
            instruction = entry.get_text().strip()
            if instruction:
                self.parent_window._apply_ai_action('custom', {
                    'instruction': instruction,
                    'text': self.selected_text
                })

    def _setup_shortcuts(self):
        controller = Gtk.EventControllerKey()
        controller.connect('key-pressed', self._on_key_pressed)
        self.add_controller(controller)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        elif keyval == Gdk.KEY_Down:
            self._select_next()
            return True
        elif keyval == Gdk.KEY_Up:
            self._select_previous()
            return True
        return False

    def _select_next(self):
        row = self.list_box.get_selected_row()
        if row:
            idx = row.get_index()
            next_row = self.list_box.get_row_at_index(idx + 1)
            if next_row and next_row.get_visible():
                self.list_box.select_row(next_row)

    def _select_previous(self):
        row = self.list_box.get_selected_row()
        if row:
            idx = row.get_index()
            if idx > 0:
                prev_row = self.list_box.get_row_at_index(idx - 1)
                if prev_row and prev_row.get_visible():
                    self.list_box.select_row(prev_row)
