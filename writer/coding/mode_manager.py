"""
Mode Manager for Frank Writer
Manages switching between Writer and Coding modes
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('GtkSource', '5')
from gi.repository import Gtk, Gdk, GLib, GObject

import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any, Callable
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)


class WriterMode(Enum):
    """Available editor modes"""
    WRITER = "writer"
    CODING = "coding"


@dataclass
class ModeConfig:
    """Configuration for a specific mode"""
    name: str
    theme: str
    show_line_numbers: bool
    show_minimap: bool
    show_right_margin: bool
    right_margin_position: int
    font_family: str
    monospace: bool
    word_wrap: bool
    bracket_matching: bool
    auto_indent: bool
    toolbar_items: list


# Default mode configurations
MODE_CONFIGS = {
    WriterMode.WRITER: ModeConfig(
        name="Writer",
        theme="writer_light",
        show_line_numbers=False,
        show_minimap=False,
        show_right_margin=False,
        right_margin_position=80,
        font_family="Cantarell",
        monospace=False,
        word_wrap=True,
        bracket_matching=False,
        auto_indent=True,
        toolbar_items=[
            "bold", "italic", "heading", "list", "quote",
            "separator", "ai_rewrite", "ai_expand", "ai_shorten",
            "separator", "export"
        ]
    ),
    WriterMode.CODING: ModeConfig(
        name="Coding",
        theme="coding_monokai",
        show_line_numbers=True,
        show_minimap=True,
        show_right_margin=True,
        right_margin_position=80,
        font_family="JetBrains Mono",
        monospace=True,
        word_wrap=False,
        bracket_matching=True,
        auto_indent=True,
        toolbar_items=[
            "run", "debug", "separator",
            "comment", "indent", "outdent",
            "separator", "format", "lint",
            "separator", "ai_explain", "ai_fix"
        ]
    )
}


class ModeManager(GObject.Object):
    """
    Manages switching between Writer and Coding modes.

    Applies different themes, UI layouts, and toolbar configurations
    based on the current mode.
    """

    __gsignals__ = {
        'mode-changed': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        'theme-applied': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        'toolbar-updated': (GObject.SignalFlags.RUN_LAST, None, ()),
    }

    def __init__(self, config=None):
        """
        Initialize the ModeManager.

        Args:
            config: Optional WriterConfig instance for theme paths
        """
        super().__init__()
        self._current_mode = WriterMode.WRITER
        self._config = config
        self._css_provider: Optional[Gtk.CssProvider] = None
        self._mode_change_callbacks: list = []
        self._source_views: list = []  # Weak refs to managed source views

        # Theme paths — B8 FIX: relative to package location
        self._themes_dir = Path(__file__).resolve().parent.parent / "themes"

    @property
    def current_mode(self) -> WriterMode:
        """Get current mode"""
        return self._current_mode

    @property
    def current_mode_name(self) -> str:
        """Get current mode name as string"""
        return self._current_mode.value

    def get_current_mode(self) -> str:
        """Get current mode as string"""
        return self._current_mode.value

    def get_mode_config(self, mode: WriterMode = None) -> ModeConfig:
        """Get configuration for a mode"""
        mode = mode or self._current_mode
        return MODE_CONFIGS.get(mode, MODE_CONFIGS[WriterMode.WRITER])

    def switch_to_writer(self) -> bool:
        """
        Switch to Writer mode.

        Returns:
            True if mode was changed, False if already in Writer mode
        """
        if self._current_mode == WriterMode.WRITER:
            return False

        return self._switch_mode(WriterMode.WRITER)

    def switch_to_coding(self) -> bool:
        """
        Switch to Coding mode.

        Returns:
            True if mode was changed, False if already in Coding mode
        """
        if self._current_mode == WriterMode.CODING:
            return False

        return self._switch_mode(WriterMode.CODING)

    def toggle_mode(self) -> str:
        """
        Toggle between Writer and Coding modes.

        Returns:
            The new mode name
        """
        if self._current_mode == WriterMode.WRITER:
            self.switch_to_coding()
        else:
            self.switch_to_writer()
        return self._current_mode.value

    def _switch_mode(self, new_mode: WriterMode) -> bool:
        """
        Internal method to switch modes.

        Args:
            new_mode: The mode to switch to

        Returns:
            True if successful
        """
        old_mode = self._current_mode
        self._current_mode = new_mode

        logger.info(f"Switching mode from {old_mode.value} to {new_mode.value}")

        # Apply mode configuration
        mode_config = self.get_mode_config(new_mode)

        # Apply theme
        self._apply_mode_theme(new_mode)

        # Emit signals
        self.emit('mode-changed', new_mode.value)
        self.emit('toolbar-updated')

        # Call registered callbacks
        for callback in self._mode_change_callbacks:
            try:
                callback(new_mode.value, mode_config)
            except Exception as e:
                logger.error(f"Mode change callback failed: {e}")

        return True

    def _apply_mode_theme(self, mode: WriterMode):
        """Apply CSS theme for the mode"""
        mode_config = self.get_mode_config(mode)
        css_file = self._themes_dir / f"{mode_config.theme}.css"

        # Remove old provider if exists
        if self._css_provider is not None:
            try:
                display = Gdk.Display.get_default()
                if display:
                    Gtk.StyleContext.remove_provider_for_display(
                        display,
                        self._css_provider
                    )
            except Exception as e:
                logger.warning(f"Failed to remove old CSS provider: {e}")

        # Load new CSS
        self._css_provider = Gtk.CssProvider()

        if css_file.exists():
            try:
                self._css_provider.load_from_path(str(css_file))
            except Exception as e:
                logger.error(f"Failed to load theme CSS from {css_file}: {e}")
                self._load_fallback_css(mode)
        else:
            logger.warning(f"Theme file not found: {css_file}")
            self._load_fallback_css(mode)

        # Apply provider
        try:
            display = Gdk.Display.get_default()
            if display:
                Gtk.StyleContext.add_provider_for_display(
                    display,
                    self._css_provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
                self.emit('theme-applied', mode_config.theme)
        except Exception as e:
            logger.error(f"Failed to apply CSS provider: {e}")

    def _load_fallback_css(self, mode: WriterMode):
        """Load fallback CSS when theme file is missing"""
        if mode == WriterMode.CODING:
            css = """
            .source-view {
                font-family: "JetBrains Mono", "Source Code Pro", monospace;
                background-color: #272822;
                color: #f8f8f2;
            }
            .coding-toolbar {
                background-color: #1e1e1e;
            }
            """
        else:
            css = """
            .source-view {
                font-family: "Cantarell", sans-serif;
                background-color: #ffffff;
                color: #2e3436;
            }
            .writer-toolbar {
                background-color: #f6f5f4;
            }
            """

        try:
            self._css_provider.load_from_string(css)
        except Exception as e:
            logger.error(f"Failed to load fallback CSS: {e}")

    def apply_mode_to_source_view(self, source_view):
        """
        Apply current mode settings to a GtkSourceView.

        Args:
            source_view: A GtkSourceView instance to configure
        """
        mode_config = self.get_mode_config()

        try:
            # Basic settings
            source_view.set_show_line_numbers(mode_config.show_line_numbers)
            source_view.set_show_right_margin(mode_config.show_right_margin)
            source_view.set_right_margin_position(mode_config.right_margin_position)
            source_view.set_auto_indent(mode_config.auto_indent)
            source_view.set_monospace(mode_config.monospace)

            # Word wrap
            if mode_config.word_wrap:
                source_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            else:
                source_view.set_wrap_mode(Gtk.WrapMode.NONE)

            # Bracket matching (on buffer)
            buffer = source_view.get_buffer()
            if buffer and hasattr(buffer, 'set_highlight_matching_brackets'):
                buffer.set_highlight_matching_brackets(mode_config.bracket_matching)

            # Add mode-specific CSS class
            source_view.remove_css_class("writer-mode")
            source_view.remove_css_class("coding-mode")
            source_view.add_css_class(f"{self._current_mode.value}-mode")

        except Exception as e:
            logger.error(f"Failed to apply mode settings to source view: {e}")

    def get_toolbar_items(self) -> list:
        """Get toolbar items for current mode"""
        mode_config = self.get_mode_config()
        return mode_config.toolbar_items.copy()

    def register_mode_change_callback(self, callback: Callable[[str, ModeConfig], None]):
        """
        Register a callback to be called on mode changes.

        Args:
            callback: Function taking (mode_name, mode_config)
        """
        if callback not in self._mode_change_callbacks:
            self._mode_change_callbacks.append(callback)

    def unregister_mode_change_callback(self, callback: Callable):
        """Unregister a mode change callback"""
        if callback in self._mode_change_callbacks:
            self._mode_change_callbacks.remove(callback)

    def create_mode_toggle_buttons(self) -> Gtk.Box:
        """
        Create mode toggle button group widget.

        Returns:
            Gtk.Box containing toggle buttons for each mode
        """
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        box.add_css_class("linked")

        writer_btn = Gtk.ToggleButton(label="Writer")
        writer_btn.set_active(self._current_mode == WriterMode.WRITER)

        coding_btn = Gtk.ToggleButton(label="Coding")
        coding_btn.set_active(self._current_mode == WriterMode.CODING)
        coding_btn.set_group(writer_btn)

        def on_writer_toggled(btn):
            if btn.get_active():
                self.switch_to_writer()

        def on_coding_toggled(btn):
            if btn.get_active():
                self.switch_to_coding()

        writer_btn.connect('toggled', on_writer_toggled)
        coding_btn.connect('toggled', on_coding_toggled)

        # Update buttons on mode change
        def update_buttons(manager, mode_name):
            if mode_name == 'writer':
                if not writer_btn.get_active():
                    writer_btn.set_active(True)
            else:
                if not coding_btn.get_active():
                    coding_btn.set_active(True)

        self.connect('mode-changed', update_buttons)

        box.append(writer_btn)
        box.append(coding_btn)

        return box

    def create_toolbar_for_mode(self, action_callback: Callable[[str], None]) -> Gtk.Box:
        """
        Create toolbar widget for current mode.

        Args:
            action_callback: Function to call when toolbar item is clicked

        Returns:
            Gtk.Box containing toolbar items
        """
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        toolbar.add_css_class("toolbar")
        toolbar.add_css_class(f"{self._current_mode.value}-toolbar")

        # Icon mappings
        icon_map = {
            # Writer mode
            "bold": "format-text-bold-symbolic",
            "italic": "format-text-italic-symbolic",
            "heading": "format-text-heading-symbolic",
            "list": "view-list-symbolic",
            "quote": "format-text-blockquote-symbolic",
            "ai_rewrite": "edit-symbolic",
            "ai_expand": "list-add-symbolic",
            "ai_shorten": "list-remove-symbolic",
            "export": "document-send-symbolic",
            # Coding mode
            "run": "media-playback-start-symbolic",
            "debug": "debug-symbolic",
            "comment": "format-text-strikethrough-symbolic",
            "indent": "format-indent-more-symbolic",
            "outdent": "format-indent-less-symbolic",
            "format": "format-text-symbolic",
            "lint": "dialog-warning-symbolic",
            "ai_explain": "help-about-symbolic",
            "ai_fix": "emblem-ok-symbolic",
        }

        tooltip_map = {
            "bold": "Bold (Ctrl+B)",
            "italic": "Italic (Ctrl+I)",
            "heading": "Heading",
            "list": "List",
            "quote": "Quote",
            "ai_rewrite": "AI Rewrite",
            "ai_expand": "AI Expand",
            "ai_shorten": "AI Shorten",
            "export": "Export (Ctrl+E)",
            "run": "Run Code (F5)",
            "debug": "Debug (F9)",
            "comment": "Toggle Comment (Ctrl+/)",
            "indent": "Indent (Tab)",
            "outdent": "Outdent (Shift+Tab)",
            "format": "Format Code",
            "lint": "Run Linter",
            "ai_explain": "AI Explain Code",
            "ai_fix": "AI Fix Error",
        }

        items = self.get_toolbar_items()

        for item in items:
            if item == "separator":
                sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
                sep.set_margin_start(4)
                sep.set_margin_end(4)
                toolbar.append(sep)
            else:
                icon_name = icon_map.get(item, "application-x-executable-symbolic")
                btn = Gtk.Button(icon_name=icon_name)
                btn.set_tooltip_text(tooltip_map.get(item, item.replace("_", " ").title()))
                btn.connect('clicked', lambda b, action=item: action_callback(action))
                toolbar.append(btn)

        return toolbar

    def get_mode_specific_keybindings(self) -> Dict[str, str]:
        """
        Get keybindings specific to current mode.

        Returns:
            Dict mapping key combos to action names
        """
        common_bindings = {
            "<Ctrl>s": "save",
            "<Ctrl>o": "open",
            "<Ctrl>n": "new",
            "<Ctrl>z": "undo",
            "<Ctrl><Shift>z": "redo",
            "<Ctrl>k": "ai_command",
        }

        if self._current_mode == WriterMode.CODING:
            coding_bindings = {
                "F5": "run",
                "F9": "debug",
                "<Ctrl>slash": "toggle_comment",
                "<Ctrl><Shift>f": "format",
                "<Ctrl>b": "build",
                "<Ctrl>g": "goto_definition",
                "<Ctrl><Shift>g": "find_references",
            }
            return {**common_bindings, **coding_bindings}
        else:
            writer_bindings = {
                "<Ctrl>b": "bold",
                "<Ctrl>i": "italic",
                "<Ctrl>e": "export",
                "<Ctrl>Return": "ai_suggest",
            }
            return {**common_bindings, **writer_bindings}
