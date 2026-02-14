"""
Coding Theme Manager for Frank Writer
Provides coding-specific themes and style schemes
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('GtkSource', '5')
from gi.repository import Gtk, Gdk, GtkSource

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ThemeColor:
    """Represents a color in a theme"""
    foreground: str
    background: str = ""
    bold: bool = False
    italic: bool = False
    underline: bool = False


@dataclass
class CodingThemeDefinition:
    """Complete theme definition for coding mode"""
    name: str
    display_name: str
    is_dark: bool

    # Base colors
    background: str
    foreground: str
    selection: str
    cursor: str
    line_highlight: str
    line_numbers_fg: str
    line_numbers_bg: str
    right_margin: str

    # Syntax colors
    keyword: ThemeColor
    string: ThemeColor
    number: ThemeColor
    comment: ThemeColor
    operator: ThemeColor
    function: ThemeColor
    class_name: ThemeColor
    variable: ThemeColor
    constant: ThemeColor
    type: ThemeColor
    preprocessor: ThemeColor
    error: ThemeColor
    warning: ThemeColor

    # UI colors
    bracket_match_bg: str = ""
    bracket_match_fg: str = ""
    search_highlight: str = ""
    diff_added: str = ""
    diff_removed: str = ""
    diff_changed: str = ""


# Built-in theme definitions
BUILTIN_THEMES: Dict[str, CodingThemeDefinition] = {
    "monokai": CodingThemeDefinition(
        name="monokai",
        display_name="Monokai",
        is_dark=True,
        background="#272822",
        foreground="#f8f8f2",
        selection="#49483e",
        cursor="#f8f8f0",
        line_highlight="#3e3d32",
        line_numbers_fg="#90908a",
        line_numbers_bg="#272822",
        right_margin="#3e3d32",
        keyword=ThemeColor("#f92672", bold=True),
        string=ThemeColor("#e6db74"),
        number=ThemeColor("#ae81ff"),
        comment=ThemeColor("#75715e", italic=True),
        operator=ThemeColor("#f92672"),
        function=ThemeColor("#a6e22e"),
        class_name=ThemeColor("#a6e22e", underline=True),
        variable=ThemeColor("#f8f8f2"),
        constant=ThemeColor("#ae81ff"),
        type=ThemeColor("#66d9ef", italic=True),
        preprocessor=ThemeColor("#f92672"),
        error=ThemeColor("#f92672", "#3c1518", bold=True),
        warning=ThemeColor("#e6db74", "#3c3010"),
        bracket_match_bg="#49483e",
        bracket_match_fg="#f8f8f0",
        search_highlight="#e6db74",
        diff_added="#a6e22e",
        diff_removed="#f92672",
        diff_changed="#66d9ef",
    ),

    "dracula": CodingThemeDefinition(
        name="dracula",
        display_name="Dracula",
        is_dark=True,
        background="#282a36",
        foreground="#f8f8f2",
        selection="#44475a",
        cursor="#f8f8f2",
        line_highlight="#44475a",
        line_numbers_fg="#6272a4",
        line_numbers_bg="#282a36",
        right_margin="#44475a",
        keyword=ThemeColor("#ff79c6", bold=True),
        string=ThemeColor("#f1fa8c"),
        number=ThemeColor("#bd93f9"),
        comment=ThemeColor("#6272a4", italic=True),
        operator=ThemeColor("#ff79c6"),
        function=ThemeColor("#50fa7b"),
        class_name=ThemeColor("#8be9fd", italic=True),
        variable=ThemeColor("#f8f8f2"),
        constant=ThemeColor("#bd93f9"),
        type=ThemeColor("#8be9fd", italic=True),
        preprocessor=ThemeColor("#ff79c6"),
        error=ThemeColor("#ff5555", "#3c1f1f", bold=True),
        warning=ThemeColor("#ffb86c", "#3c2f1f"),
        bracket_match_bg="#44475a",
        bracket_match_fg="#f8f8f2",
        search_highlight="#ffb86c",
        diff_added="#50fa7b",
        diff_removed="#ff5555",
        diff_changed="#8be9fd",
    ),

    "solarized_dark": CodingThemeDefinition(
        name="solarized_dark",
        display_name="Solarized Dark",
        is_dark=True,
        background="#002b36",
        foreground="#839496",
        selection="#073642",
        cursor="#839496",
        line_highlight="#073642",
        line_numbers_fg="#586e75",
        line_numbers_bg="#002b36",
        right_margin="#073642",
        keyword=ThemeColor("#859900", bold=True),
        string=ThemeColor("#2aa198"),
        number=ThemeColor("#d33682"),
        comment=ThemeColor("#586e75", italic=True),
        operator=ThemeColor("#859900"),
        function=ThemeColor("#268bd2"),
        class_name=ThemeColor("#b58900"),
        variable=ThemeColor("#839496"),
        constant=ThemeColor("#cb4b16"),
        type=ThemeColor("#b58900"),
        preprocessor=ThemeColor("#cb4b16"),
        error=ThemeColor("#dc322f", "#3c1f1f", bold=True),
        warning=ThemeColor("#b58900", "#2f2f1f"),
        bracket_match_bg="#073642",
        bracket_match_fg="#93a1a1",
        search_highlight="#b58900",
        diff_added="#859900",
        diff_removed="#dc322f",
        diff_changed="#268bd2",
    ),

    "nord": CodingThemeDefinition(
        name="nord",
        display_name="Nord",
        is_dark=True,
        background="#2e3440",
        foreground="#d8dee9",
        selection="#434c5e",
        cursor="#d8dee9",
        line_highlight="#3b4252",
        line_numbers_fg="#4c566a",
        line_numbers_bg="#2e3440",
        right_margin="#3b4252",
        keyword=ThemeColor("#81a1c1", bold=True),
        string=ThemeColor("#a3be8c"),
        number=ThemeColor("#b48ead"),
        comment=ThemeColor("#616e88", italic=True),
        operator=ThemeColor("#81a1c1"),
        function=ThemeColor("#88c0d0"),
        class_name=ThemeColor("#8fbcbb"),
        variable=ThemeColor("#d8dee9"),
        constant=ThemeColor("#b48ead"),
        type=ThemeColor("#8fbcbb"),
        preprocessor=ThemeColor("#5e81ac"),
        error=ThemeColor("#bf616a", "#3c2626", bold=True),
        warning=ThemeColor("#ebcb8b", "#3c3620"),
        bracket_match_bg="#434c5e",
        bracket_match_fg="#eceff4",
        search_highlight="#ebcb8b",
        diff_added="#a3be8c",
        diff_removed="#bf616a",
        diff_changed="#81a1c1",
    ),
}


class CodingTheme:
    """
    Manages coding-specific themes for GtkSourceView.

    Provides theme definitions, CSS generation, and style scheme
    application for syntax highlighting.
    """

    # Scheme directory for custom schemes
    CUSTOM_SCHEMES_DIR = Path.home() / ".local" / "share" / "gtksourceview-5" / "styles"

    def __init__(self):
        """Initialize the CodingTheme manager"""
        self._current_theme: str = "monokai"
        self._themes: Dict[str, CodingThemeDefinition] = BUILTIN_THEMES.copy()
        self._css_provider: Optional[Gtk.CssProvider] = None

        # Ensure custom schemes directory exists
        self.CUSTOM_SCHEMES_DIR.mkdir(parents=True, exist_ok=True)

        # Generate scheme files for built-in themes
        self._generate_builtin_schemes()

    def get_available_themes(self) -> List[Dict[str, str]]:
        """
        Get list of available themes.

        Returns:
            List of dicts with 'name' and 'display_name' keys
        """
        themes = []
        for name, theme_def in self._themes.items():
            themes.append({
                "name": name,
                "display_name": theme_def.display_name,
                "is_dark": theme_def.is_dark
            })
        return themes

    def get_theme(self, name: str) -> Optional[CodingThemeDefinition]:
        """Get a theme definition by name"""
        return self._themes.get(name)

    def get_current_theme(self) -> CodingThemeDefinition:
        """Get current theme definition"""
        return self._themes.get(self._current_theme, BUILTIN_THEMES["monokai"])

    def apply_theme(self, source_view, theme_name: str) -> bool:
        """
        Apply a theme to a GtkSourceView.

        Args:
            source_view: GtkSourceView instance
            theme_name: Name of theme to apply

        Returns:
            True if successful
        """
        if theme_name not in self._themes:
            logger.warning(f"Theme not found: {theme_name}")
            return False

        theme = self._themes[theme_name]
        self._current_theme = theme_name

        # Try to apply GtkSourceView style scheme
        scheme_manager = GtkSource.StyleSchemeManager.get_default()

        # Add custom schemes directory to search path
        search_paths = list(scheme_manager.get_search_path())
        custom_path = str(self.CUSTOM_SCHEMES_DIR)
        if custom_path not in search_paths:
            search_paths.insert(0, custom_path)
            scheme_manager.set_search_path(search_paths)

        # Try custom scheme first, then fallback to built-in
        scheme = scheme_manager.get_scheme(f"frank-{theme_name}")
        if scheme is None:
            # Try built-in schemes
            for fallback in [theme_name, 'Adwaita-dark' if theme.is_dark else 'Adwaita']:
                scheme = scheme_manager.get_scheme(fallback)
                if scheme:
                    break

        if scheme:
            buffer = source_view.get_buffer()
            if buffer:
                buffer.set_style_scheme(scheme)
                logger.debug(f"Applied style scheme: {scheme.get_id()}")

        # Apply additional CSS styling
        self._apply_theme_css(source_view, theme)

        return True

    def _apply_theme_css(self, source_view, theme: CodingThemeDefinition):
        """Apply CSS styling for the theme"""
        css = self.generate_css(theme.name)

        # Remove old provider
        if self._css_provider:
            try:
                display = Gdk.Display.get_default()
                if display:
                    Gtk.StyleContext.remove_provider_for_display(
                        display, self._css_provider
                    )
            except Exception as e:
                logger.debug(f"Could not remove old CSS provider: {e}")

        # Apply new CSS
        self._css_provider = Gtk.CssProvider()
        try:
            self._css_provider.load_from_string(css)
            display = Gdk.Display.get_default()
            if display:
                Gtk.StyleContext.add_provider_for_display(
                    display,
                    self._css_provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
                )
        except Exception as e:
            logger.error(f"Failed to apply theme CSS: {e}")

    def generate_css(self, theme_name: str) -> str:
        """
        Generate CSS for a theme.

        Args:
            theme_name: Name of the theme

        Returns:
            CSS string
        """
        theme = self._themes.get(theme_name)
        if not theme:
            return ""

        css = f"""
/* Frank Writer Coding Theme: {theme.display_name} */

/* Source View */
.coding-mode,
textview.coding-mode text {{
    background-color: {theme.background};
    color: {theme.foreground};
    caret-color: {theme.cursor};
}}

/* Line Numbers */
.coding-mode .line-numbers,
textview.coding-mode .line-numbers {{
    background-color: {theme.line_numbers_bg};
    color: {theme.line_numbers_fg};
    padding-left: 8px;
    padding-right: 8px;
}}

/* Current Line Highlight */
.coding-mode .current-line-number,
textview.coding-mode .current-line-number {{
    color: {theme.foreground};
    font-weight: bold;
}}

/* Selection */
.coding-mode text selection,
textview.coding-mode text selection {{
    background-color: {theme.selection};
}}

/* Right Margin */
.coding-mode .right-margin,
textview.coding-mode .right-margin {{
    background-color: {theme.right_margin};
}}

/* Bracket Matching */
.coding-mode .bracket-match,
textview.coding-mode .bracket-match {{
    background-color: {theme.bracket_match_bg};
    color: {theme.bracket_match_fg};
    border: 1px solid {theme.bracket_match_fg};
    border-radius: 2px;
}}

/* Search Highlight */
.coding-mode .search-match,
textview.coding-mode .search-match {{
    background-color: {theme.search_highlight};
    color: {theme.background};
}}

/* Error Squiggle */
.coding-mode .error,
textview.coding-mode .error {{
    text-decoration: underline;
    text-decoration-color: {theme.error.foreground};
    text-decoration-style: wavy;
}}

/* Warning Squiggle */
.coding-mode .warning,
textview.coding-mode .warning {{
    text-decoration: underline;
    text-decoration-color: {theme.warning.foreground};
    text-decoration-style: wavy;
}}

/* Diff Colors */
.coding-mode .diff-added {{
    background-color: alpha({theme.diff_added}, 0.2);
}}

.coding-mode .diff-removed {{
    background-color: alpha({theme.diff_removed}, 0.2);
}}

.coding-mode .diff-changed {{
    background-color: alpha({theme.diff_changed}, 0.2);
}}

/* Minimap */
.coding-mode .minimap {{
    background-color: {theme.line_numbers_bg};
    opacity: 0.8;
}}

/* Scrollbar */
.coding-mode scrollbar {{
    background-color: {theme.background};
}}

.coding-mode scrollbar slider {{
    background-color: {theme.selection};
    min-width: 8px;
    border-radius: 4px;
}}

/* Coding Toolbar */
.coding-toolbar {{
    background-color: {theme.line_numbers_bg};
    border-bottom: 1px solid {theme.right_margin};
    padding: 4px 8px;
}}

.coding-toolbar button {{
    background: transparent;
    color: {theme.foreground};
    border: none;
    padding: 4px 8px;
    border-radius: 4px;
}}

.coding-toolbar button:hover {{
    background-color: {theme.selection};
}}

/* Status Bar */
.coding-statusbar {{
    background-color: {theme.line_numbers_bg};
    color: {theme.line_numbers_fg};
    border-top: 1px solid {theme.right_margin};
    padding: 2px 12px;
    font-size: 0.9em;
}}
"""
        return css

    def _generate_builtin_schemes(self):
        """Generate GtkSourceView style scheme XML files for built-in themes"""
        for name, theme in self._themes.items():
            scheme_path = self.CUSTOM_SCHEMES_DIR / f"frank-{name}.xml"
            if not scheme_path.exists():
                xml = self._generate_scheme_xml(theme)
                try:
                    scheme_path.write_text(xml)
                    logger.debug(f"Generated scheme file: {scheme_path}")
                except Exception as e:
                    logger.error(f"Failed to write scheme file {scheme_path}: {e}")

    def _generate_scheme_xml(self, theme: CodingThemeDefinition) -> str:
        """Generate GtkSourceView style scheme XML"""

        def color_to_attrs(tc: ThemeColor) -> str:
            attrs = [f'foreground="{tc.foreground}"']
            if tc.background:
                attrs.append(f'background="{tc.background}"')
            if tc.bold:
                attrs.append('bold="true"')
            if tc.italic:
                attrs.append('italic="true"')
            if tc.underline:
                attrs.append('underline="true"')
            return " ".join(attrs)

        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<style-scheme id="frank-{theme.name}" name="Frank {theme.display_name}" version="1.0">
  <author>Frank Writer</author>
  <description>Frank Writer coding theme: {theme.display_name}</description>

  <!-- Colors -->
  <color name="background" value="{theme.background}"/>
  <color name="foreground" value="{theme.foreground}"/>
  <color name="selection" value="{theme.selection}"/>
  <color name="cursor" value="{theme.cursor}"/>
  <color name="line-highlight" value="{theme.line_highlight}"/>

  <!-- Base Styles -->
  <style name="text" foreground="foreground" background="background"/>
  <style name="selection" background="selection"/>
  <style name="cursor" foreground="cursor"/>
  <style name="current-line" background="line-highlight"/>
  <style name="line-numbers" foreground="{theme.line_numbers_fg}" background="{theme.line_numbers_bg}"/>
  <style name="right-margin" foreground="{theme.right_margin}" background="{theme.right_margin}"/>
  <style name="bracket-match" {color_to_attrs(ThemeColor(theme.bracket_match_fg, theme.bracket_match_bg, bold=True))}/>

  <!-- Syntax Highlighting -->
  <style name="def:keyword" {color_to_attrs(theme.keyword)}/>
  <style name="def:string" {color_to_attrs(theme.string)}/>
  <style name="def:number" {color_to_attrs(theme.number)}/>
  <style name="def:comment" {color_to_attrs(theme.comment)}/>
  <style name="def:operator" {color_to_attrs(theme.operator)}/>
  <style name="def:function" {color_to_attrs(theme.function)}/>
  <style name="def:type" {color_to_attrs(theme.type)}/>
  <style name="def:constant" {color_to_attrs(theme.constant)}/>
  <style name="def:identifier" {color_to_attrs(theme.variable)}/>
  <style name="def:preprocessor" {color_to_attrs(theme.preprocessor)}/>
  <style name="def:error" {color_to_attrs(theme.error)}/>
  <style name="def:warning" {color_to_attrs(theme.warning)}/>
  <style name="def:note" foreground="{theme.comment.foreground}" italic="true"/>
  <style name="def:special-char" foreground="{theme.constant.foreground}"/>
  <style name="def:builtin" foreground="{theme.function.foreground}"/>
  <style name="def:boolean" foreground="{theme.constant.foreground}"/>
  <style name="def:decimal" foreground="{theme.number.foreground}"/>
  <style name="def:base-n-integer" foreground="{theme.number.foreground}"/>
  <style name="def:floating-point" foreground="{theme.number.foreground}"/>
  <style name="def:complex" foreground="{theme.number.foreground}"/>
  <style name="def:character" foreground="{theme.string.foreground}"/>
  <style name="def:special-constant" foreground="{theme.constant.foreground}" bold="true"/>
  <style name="def:reserved" foreground="{theme.keyword.foreground}" bold="true"/>

  <!-- Diff -->
  <style name="diff:added-line" foreground="{theme.diff_added}"/>
  <style name="diff:removed-line" foreground="{theme.diff_removed}"/>
  <style name="diff:changed-line" foreground="{theme.diff_changed}"/>
  <style name="diff:location" foreground="{theme.type.foreground}"/>

  <!-- Search -->
  <style name="search-match" background="{theme.search_highlight}" foreground="{theme.background}"/>

</style-scheme>
"""
        return xml

    def add_custom_theme(self, theme: CodingThemeDefinition) -> bool:
        """
        Add a custom theme.

        Args:
            theme: Theme definition to add

        Returns:
            True if successful
        """
        if not theme.name:
            logger.error("Theme must have a name")
            return False

        self._themes[theme.name] = theme

        # Generate scheme file
        scheme_path = self.CUSTOM_SCHEMES_DIR / f"frank-{theme.name}.xml"
        xml = self._generate_scheme_xml(theme)
        try:
            scheme_path.write_text(xml)
            logger.info(f"Added custom theme: {theme.name}")
            return True
        except Exception as e:
            logger.error(f"Failed to save custom theme {theme.name}: {e}")
            return False

    def remove_custom_theme(self, name: str) -> bool:
        """
        Remove a custom theme.

        Args:
            name: Theme name to remove

        Returns:
            True if successful
        """
        if name in BUILTIN_THEMES:
            logger.warning(f"Cannot remove built-in theme: {name}")
            return False

        if name not in self._themes:
            return False

        del self._themes[name]

        # Remove scheme file
        scheme_path = self.CUSTOM_SCHEMES_DIR / f"frank-{name}.xml"
        try:
            if scheme_path.exists():
                scheme_path.unlink()
            return True
        except Exception as e:
            logger.error(f"Failed to remove theme file: {e}")
            return False

    def get_theme_colors_for_language(self, language: str) -> Dict[str, str]:
        """
        Get recommended syntax colors for a specific language.

        Args:
            language: Programming language name

        Returns:
            Dict mapping syntax elements to colors
        """
        theme = self.get_current_theme()

        # Language-specific color recommendations
        base_colors = {
            "keyword": theme.keyword.foreground,
            "string": theme.string.foreground,
            "number": theme.number.foreground,
            "comment": theme.comment.foreground,
            "function": theme.function.foreground,
            "class": theme.class_name.foreground,
            "variable": theme.variable.foreground,
            "operator": theme.operator.foreground,
            "type": theme.type.foreground,
        }

        # Add language-specific mappings
        if language in ("python", "py"):
            base_colors.update({
                "decorator": theme.preprocessor.foreground,
                "self": theme.constant.foreground,
                "magic_method": theme.function.foreground,
            })
        elif language in ("javascript", "typescript", "js", "ts"):
            base_colors.update({
                "this": theme.constant.foreground,
                "arrow": theme.operator.foreground,
                "template_string": theme.string.foreground,
            })
        elif language in ("rust", "rs"):
            base_colors.update({
                "lifetime": theme.type.foreground,
                "macro": theme.preprocessor.foreground,
                "unsafe": theme.error.foreground,
            })

        return base_colors
