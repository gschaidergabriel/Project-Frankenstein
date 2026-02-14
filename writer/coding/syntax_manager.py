"""
Syntax Manager for Frank Writer
Advanced syntax features: bracket matching, code folding, auto-indent
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('GtkSource', '5')
from gi.repository import Gtk, GtkSource, Gdk

import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Set
from enum import Enum

logger = logging.getLogger(__name__)


class BracketType(Enum):
    """Types of brackets"""
    PARENTHESIS = ("(", ")")
    SQUARE = ("[", "]")
    CURLY = ("{", "}")
    ANGLE = ("<", ">")


@dataclass
class BracketPair:
    """A matched pair of brackets"""
    open_line: int
    open_column: int
    close_line: int
    close_column: int
    bracket_type: BracketType
    is_valid: bool = True


@dataclass
class FoldRegion:
    """A foldable region in the code"""
    start_line: int
    end_line: int
    fold_text: str  # Text to display when folded
    is_folded: bool = False
    fold_type: str = "block"  # block, comment, import, function, class


@dataclass
class IndentInfo:
    """Information about indentation at a position"""
    level: int
    char: str  # ' ' or '\t'
    size: int  # Spaces per indent level
    text: str  # The actual indent string


# Language-specific configuration
LANGUAGE_CONFIG: Dict[str, Dict] = {
    "python": {
        "indent_triggers": [":", "\\"],
        "dedent_triggers": ["return", "break", "continue", "pass", "raise"],
        "fold_patterns": [
            (r"^\s*(def|class|if|elif|else|for|while|try|except|finally|with|async)\b", "block"),
            (r"^\s*#\s*region\b", "region"),
            (r'^\s*"""', "docstring"),
            (r"^\s*(import|from)\b", "import"),
        ],
        "comment_prefix": "#",
        "string_delimiters": ['"', "'", '"""', "'''"],
        "bracket_pairs": [BracketType.PARENTHESIS, BracketType.SQUARE, BracketType.CURLY],
    },
    "javascript": {
        "indent_triggers": ["{", "[", "("],
        "dedent_triggers": ["}", "]", ")", "break", "return"],
        "fold_patterns": [
            (r"^\s*(function|class|if|else|for|while|switch|try|catch|finally)\b", "block"),
            (r"^\s*/\*", "comment"),
            (r"^\s*(import|export)\b", "import"),
        ],
        "comment_prefix": "//",
        "block_comment": ("/*", "*/"),
        "string_delimiters": ['"', "'", "`"],
        "bracket_pairs": [BracketType.PARENTHESIS, BracketType.SQUARE, BracketType.CURLY],
    },
    "typescript": {
        "indent_triggers": ["{", "[", "("],
        "dedent_triggers": ["}", "]", ")", "break", "return"],
        "fold_patterns": [
            (r"^\s*(function|class|interface|if|else|for|while|switch|try|catch|finally)\b", "block"),
            (r"^\s*/\*", "comment"),
            (r"^\s*(import|export)\b", "import"),
        ],
        "comment_prefix": "//",
        "block_comment": ("/*", "*/"),
        "string_delimiters": ['"', "'", "`"],
        "bracket_pairs": [BracketType.PARENTHESIS, BracketType.SQUARE, BracketType.CURLY, BracketType.ANGLE],
    },
    "rust": {
        "indent_triggers": ["{", "[", "("],
        "dedent_triggers": ["}", "]", ")"],
        "fold_patterns": [
            (r"^\s*(fn|impl|struct|enum|trait|mod|if|else|for|while|match|loop)\b", "block"),
            (r"^\s*/\*", "comment"),
            (r"^\s*(use|mod)\b", "import"),
        ],
        "comment_prefix": "//",
        "block_comment": ("/*", "*/"),
        "string_delimiters": ['"', 'r"', 'r#"'],
        "bracket_pairs": [BracketType.PARENTHESIS, BracketType.SQUARE, BracketType.CURLY, BracketType.ANGLE],
    },
    "go": {
        "indent_triggers": ["{"],
        "dedent_triggers": ["}"],
        "fold_patterns": [
            (r"^\s*(func|type|if|else|for|switch|select)\b", "block"),
            (r"^\s*/\*", "comment"),
            (r"^\s*(import|package)\b", "import"),
        ],
        "comment_prefix": "//",
        "block_comment": ("/*", "*/"),
        "string_delimiters": ['"', "`"],
        "bracket_pairs": [BracketType.PARENTHESIS, BracketType.SQUARE, BracketType.CURLY],
    },
    "default": {
        "indent_triggers": ["{", "[", "("],
        "dedent_triggers": ["}", "]", ")"],
        "fold_patterns": [],
        "comment_prefix": "//",
        "string_delimiters": ['"', "'"],
        "bracket_pairs": [BracketType.PARENTHESIS, BracketType.SQUARE, BracketType.CURLY],
    }
}


class SyntaxManager:
    """
    Manages advanced syntax features for the code editor.

    Features:
    - Bracket matching with highlighting
    - Auto-indentation
    - Code folding regions
    - Smart bracket insertion
    """

    # All bracket characters for quick lookup
    OPEN_BRACKETS = "([{<"
    CLOSE_BRACKETS = ")]}>"
    BRACKET_PAIRS = dict(zip(OPEN_BRACKETS, CLOSE_BRACKETS))
    REVERSE_BRACKETS = dict(zip(CLOSE_BRACKETS, OPEN_BRACKETS))

    def __init__(self, source_view: GtkSource.View = None):
        """
        Initialize the SyntaxManager.

        Args:
            source_view: Optional GtkSourceView to manage
        """
        self._source_view = source_view
        self._buffer: Optional[GtkSource.Buffer] = None
        self._language: str = "default"
        self._config: Dict = LANGUAGE_CONFIG["default"]

        # State
        self._fold_regions: List[FoldRegion] = []
        self._bracket_marks: List[Gtk.TextMark] = []
        self._indent_size: int = 4
        self._use_tabs: bool = False

        if source_view:
            self.set_source_view(source_view)

    def set_source_view(self, source_view: GtkSource.View):
        """
        Set the source view to manage.

        Args:
            source_view: GtkSourceView instance
        """
        self._source_view = source_view
        self._buffer = source_view.get_buffer()

        # Connect signals
        if self._buffer:
            self._buffer.connect('changed', self._on_buffer_changed)
            self._buffer.connect('notify::cursor-position', self._on_cursor_moved)

            # Detect language
            lang = self._buffer.get_language()
            if lang:
                self.set_language(lang.get_id())

    def set_language(self, language: str):
        """
        Set the programming language for syntax features.

        Args:
            language: Language identifier (e.g., 'python', 'javascript')
        """
        self._language = language
        self._config = LANGUAGE_CONFIG.get(language, LANGUAGE_CONFIG["default"])
        logger.debug(f"Syntax manager set to language: {language}")

        # Refresh fold regions
        if self._buffer:
            self._update_fold_regions()

    def set_indent_settings(self, size: int = 4, use_tabs: bool = False):
        """Configure indentation settings"""
        self._indent_size = size
        self._use_tabs = use_tabs

    # Bracket Matching

    def get_matching_bracket(self, position: Tuple[int, int]) -> Optional[Tuple[int, int]]:
        """
        Find the matching bracket at a position.

        Args:
            position: (line, column) tuple (0-indexed)

        Returns:
            (line, column) of matching bracket, or None
        """
        if not self._buffer:
            return None

        line, column = position

        # Get character at position
        try:
            line_iter = self._buffer.get_iter_at_line(line)
            if not line_iter:
                return None

            char_iter = line_iter.copy()
            if not char_iter.forward_chars(column):
                return None

            char = char_iter.get_char()
        except Exception as e:
            logger.debug(f"Could not get character at position: {e}")
            return None

        # Check if it's a bracket
        if char in self.OPEN_BRACKETS:
            return self._find_closing_bracket(char_iter, char)
        elif char in self.CLOSE_BRACKETS:
            return self._find_opening_bracket(char_iter, char)

        return None

    def _find_closing_bracket(self, start_iter, open_char: str) -> Optional[Tuple[int, int]]:
        """Find matching closing bracket"""
        close_char = self.BRACKET_PAIRS[open_char]
        depth = 1

        iter_copy = start_iter.copy()
        iter_copy.forward_char()

        while not iter_copy.is_end():
            char = iter_copy.get_char()

            # Skip strings and comments (simplified check)
            if not self._is_in_string_or_comment(iter_copy):
                if char == open_char:
                    depth += 1
                elif char == close_char:
                    depth -= 1
                    if depth == 0:
                        return (iter_copy.get_line(), iter_copy.get_line_offset())

            iter_copy.forward_char()

        return None

    def _find_opening_bracket(self, start_iter, close_char: str) -> Optional[Tuple[int, int]]:
        """Find matching opening bracket"""
        open_char = self.REVERSE_BRACKETS[close_char]
        depth = 1

        iter_copy = start_iter.copy()

        while iter_copy.backward_char():
            char = iter_copy.get_char()

            # Skip strings and comments (simplified check)
            if not self._is_in_string_or_comment(iter_copy):
                if char == close_char:
                    depth += 1
                elif char == open_char:
                    depth -= 1
                    if depth == 0:
                        return (iter_copy.get_line(), iter_copy.get_line_offset())

        return None

    def _is_in_string_or_comment(self, text_iter) -> bool:
        """Check if position is inside a string or comment"""
        if not self._buffer:
            return False

        # Use GtkSourceView's context classes if available
        try:
            context_class = self._buffer.get_context_classes_at_iter(text_iter)
            return 'string' in context_class or 'comment' in context_class
        except Exception:
            return False

    def highlight_matching_bracket(self, position: Tuple[int, int]):
        """
        Highlight matching bracket at position.

        Args:
            position: (line, column) tuple
        """
        # Clear previous highlights
        self._clear_bracket_highlights()

        match = self.get_matching_bracket(position)
        if match:
            # Highlight both brackets
            self._add_bracket_highlight(position)
            self._add_bracket_highlight(match)

    def _add_bracket_highlight(self, position: Tuple[int, int]):
        """Add highlight to bracket at position"""
        if not self._buffer:
            return

        line, column = position
        start_iter = self._buffer.get_iter_at_line_offset(line, column)
        end_iter = start_iter.copy()
        end_iter.forward_char()

        # Apply tag
        tag = self._buffer.get_tag_table().lookup("bracket-match")
        if not tag:
            tag = self._buffer.create_tag(
                "bracket-match",
                background="#49483e",
                weight=700
            )

        self._buffer.apply_tag(tag, start_iter, end_iter)

    def _clear_bracket_highlights(self):
        """Clear all bracket highlights"""
        if not self._buffer:
            return

        tag = self._buffer.get_tag_table().lookup("bracket-match")
        if tag:
            start = self._buffer.get_start_iter()
            end = self._buffer.get_end_iter()
            self._buffer.remove_tag(tag, start, end)

    # Code Folding

    def get_fold_regions(self) -> List[FoldRegion]:
        """
        Get all foldable regions in the document.

        Returns:
            List of FoldRegion objects
        """
        return self._fold_regions.copy()

    def toggle_fold(self, line: int) -> bool:
        """
        Toggle fold state for region at line.

        Args:
            line: Line number (0-indexed)

        Returns:
            True if fold was toggled, False if no fold at line
        """
        for region in self._fold_regions:
            if region.start_line == line:
                region.is_folded = not region.is_folded
                self._apply_fold(region)
                return True
        return False

    def fold_all(self):
        """Fold all regions"""
        for region in self._fold_regions:
            region.is_folded = True
            self._apply_fold(region)

    def unfold_all(self):
        """Unfold all regions"""
        for region in self._fold_regions:
            region.is_folded = False
            self._apply_fold(region)

    def _update_fold_regions(self):
        """Update fold regions based on document content"""
        if not self._buffer:
            return

        self._fold_regions.clear()

        # Get document content
        start = self._buffer.get_start_iter()
        end = self._buffer.get_end_iter()
        text = self._buffer.get_text(start, end, True)
        lines = text.splitlines()

        # Find fold regions based on language patterns
        fold_patterns = self._config.get("fold_patterns", [])

        # Stack for nested blocks
        block_stack: List[Tuple[int, str, int]] = []  # (line, fold_type, indent)

        for i, line in enumerate(lines):
            # Check fold patterns
            for pattern, fold_type in fold_patterns:
                if re.match(pattern, line):
                    indent = len(line) - len(line.lstrip())
                    block_stack.append((i, fold_type, indent))
                    break

            # Check for block endings based on indent (for Python-like languages)
            if self._language == "python" and block_stack:
                current_indent = len(line) - len(line.lstrip()) if line.strip() else -1
                if current_indent >= 0:
                    while block_stack and current_indent <= block_stack[-1][2] and i > block_stack[-1][0]:
                        start_line, fold_type, _ = block_stack.pop()
                        if i - start_line > 1:  # Only fold if more than one line
                            self._fold_regions.append(FoldRegion(
                                start_line=start_line,
                                end_line=i - 1,
                                fold_text=f"... ({i - start_line} lines)",
                                fold_type=fold_type
                            ))

        # Handle bracket-based folding for C-like languages
        if self._language in ("javascript", "typescript", "rust", "go", "java", "c", "cpp"):
            self._find_bracket_fold_regions(lines)

        logger.debug(f"Found {len(self._fold_regions)} fold regions")

    def _find_bracket_fold_regions(self, lines: List[str]):
        """Find fold regions based on curly braces"""
        brace_stack: List[int] = []

        for i, line in enumerate(lines):
            for j, char in enumerate(line):
                if char == '{':
                    brace_stack.append(i)
                elif char == '}' and brace_stack:
                    start_line = brace_stack.pop()
                    if i - start_line > 1:
                        # Check if this region already exists
                        exists = any(
                            r.start_line == start_line and r.end_line == i
                            for r in self._fold_regions
                        )
                        if not exists:
                            self._fold_regions.append(FoldRegion(
                                start_line=start_line,
                                end_line=i,
                                fold_text=f"... ({i - start_line} lines)",
                                fold_type="block"
                            ))

    def _apply_fold(self, region: FoldRegion):
        """Apply or remove fold for a region"""
        if not self._buffer or not self._source_view:
            return

        # GtkSourceView doesn't have built-in folding, so we use tags to hide text
        tag_name = f"fold-{region.start_line}"
        tag = self._buffer.get_tag_table().lookup(tag_name)

        if region.is_folded:
            # Create invisible tag
            if not tag:
                tag = self._buffer.create_tag(tag_name, invisible=True)

            # Apply tag to folded lines
            start_iter = self._buffer.get_iter_at_line(region.start_line + 1)
            end_iter = self._buffer.get_iter_at_line(region.end_line)
            end_iter.forward_line()

            self._buffer.apply_tag(tag, start_iter, end_iter)
        else:
            # Remove tag
            if tag:
                start_iter = self._buffer.get_iter_at_line(region.start_line + 1)
                end_iter = self._buffer.get_iter_at_line(region.end_line)
                end_iter.forward_line()
                self._buffer.remove_tag(tag, start_iter, end_iter)

    # Auto-indentation

    def get_indent_for_line(self, line: int) -> IndentInfo:
        """
        Calculate proper indentation for a line.

        Args:
            line: Line number (0-indexed)

        Returns:
            IndentInfo with indentation details
        """
        if not self._buffer or line == 0:
            return IndentInfo(0, ' ', self._indent_size, '')

        # Get previous line
        prev_line = self._get_line_text(line - 1)
        if not prev_line:
            return IndentInfo(0, ' ', self._indent_size, '')

        # Calculate base indent from previous line
        prev_indent = self._get_indent_string(prev_line)
        prev_level = self._indent_string_to_level(prev_indent)

        # Check if previous line ends with indent trigger
        prev_stripped = prev_line.rstrip()
        indent_triggers = self._config.get("indent_triggers", [])

        should_indent = False
        for trigger in indent_triggers:
            if prev_stripped.endswith(trigger):
                should_indent = True
                break

        # Check if current line starts with dedent trigger
        current_line = self._get_line_text(line)
        should_dedent = False
        if current_line:
            current_stripped = current_line.strip()
            dedent_triggers = self._config.get("dedent_triggers", [])
            for trigger in dedent_triggers:
                if current_stripped.startswith(trigger):
                    should_dedent = True
                    break

        # Calculate final level
        new_level = prev_level
        if should_indent:
            new_level += 1
        if should_dedent and new_level > 0:
            new_level -= 1

        # Generate indent string
        if self._use_tabs:
            indent_str = '\t' * new_level
        else:
            indent_str = ' ' * (new_level * self._indent_size)

        return IndentInfo(
            level=new_level,
            char='\t' if self._use_tabs else ' ',
            size=self._indent_size,
            text=indent_str
        )

    def auto_indent_line(self, line: int) -> str:
        """
        Auto-indent a line and return the new content.

        Args:
            line: Line number (0-indexed)

        Returns:
            New line content with proper indentation
        """
        if not self._buffer:
            return ""

        indent_info = self.get_indent_for_line(line)
        current_text = self._get_line_text(line)

        if current_text is None:
            return indent_info.text

        return indent_info.text + current_text.lstrip()

    def _get_line_text(self, line: int) -> Optional[str]:
        """Get text of a specific line"""
        if not self._buffer:
            return None

        line_count = self._buffer.get_line_count()
        if line < 0 or line >= line_count:
            return None

        start_iter = self._buffer.get_iter_at_line(line)
        end_iter = start_iter.copy()
        if not end_iter.ends_line():
            end_iter.forward_to_line_end()

        return self._buffer.get_text(start_iter, end_iter, False)

    def _get_indent_string(self, line: str) -> str:
        """Extract indent string from line"""
        indent = ""
        for char in line:
            if char in (' ', '\t'):
                indent += char
            else:
                break
        return indent

    def _indent_string_to_level(self, indent: str) -> int:
        """Convert indent string to level number"""
        if not indent:
            return 0

        if '\t' in indent:
            return indent.count('\t')

        return len(indent) // self._indent_size

    # Smart Bracket Insertion

    def insert_bracket(self, open_bracket: str) -> str:
        """
        Get the auto-paired bracket string to insert.

        Args:
            open_bracket: Opening bracket character

        Returns:
            String to insert (open + close bracket)
        """
        if open_bracket in self.BRACKET_PAIRS:
            return open_bracket + self.BRACKET_PAIRS[open_bracket]
        return open_bracket

    def should_auto_close_bracket(self, char: str) -> bool:
        """
        Check if a bracket should be auto-closed.

        Args:
            char: Character that was typed

        Returns:
            True if should auto-close
        """
        return char in self.BRACKET_PAIRS

    def should_skip_closing_bracket(self, char: str) -> bool:
        """
        Check if cursor should skip over existing closing bracket.

        Args:
            char: Character being typed

        Returns:
            True if should skip
        """
        if not self._buffer or char not in self.CLOSE_BRACKETS:
            return False

        # Get character at cursor
        cursor = self._buffer.get_iter_at_mark(self._buffer.get_insert())
        next_char = cursor.get_char()

        return next_char == char

    # Signal Handlers

    def _on_buffer_changed(self, buffer):
        """Handle buffer changes"""
        # Update fold regions (debounced in real implementation)
        self._update_fold_regions()

    def _on_cursor_moved(self, buffer, param):
        """Handle cursor movement"""
        if not buffer:
            return

        # Get cursor position
        cursor = buffer.get_iter_at_mark(buffer.get_insert())
        line = cursor.get_line()
        column = cursor.get_line_offset()

        # Highlight matching bracket
        self.highlight_matching_bracket((line, column))
