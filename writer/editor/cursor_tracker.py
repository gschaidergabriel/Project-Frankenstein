"""
Cursor Tracker for Frank Writer
Monitors cursor position and selection in GtkSourceView
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('GtkSource', '5')
from gi.repository import Gtk, GtkSource, GLib

import weakref
from typing import Optional, Callable, Dict, Any, Tuple
from dataclasses import dataclass


@dataclass
class CursorPosition:
    """Represents a cursor position in the document"""
    line: int
    column: int
    offset: int  # Absolute character offset from start

    def __str__(self) -> str:
        return f"Ln {self.line}, Col {self.column}"


@dataclass
class Selection:
    """Represents a text selection"""
    start_line: int
    start_column: int
    start_offset: int
    end_line: int
    end_column: int
    end_offset: int
    text: str

    @property
    def is_empty(self) -> bool:
        return self.start_offset == self.end_offset

    @property
    def length(self) -> int:
        return abs(self.end_offset - self.start_offset)

    @property
    def line_count(self) -> int:
        return abs(self.end_line - self.start_line) + 1


class CursorTracker:
    """
    Tracks cursor position and selection in a GtkSourceView.

    Provides:
    - Current cursor position (line, column)
    - Selection bounds and selected text
    - Position change callbacks
    - Context extraction for AI assistance

    Usage:
        tracker = CursorTracker(source_view)
        tracker.connect_position_changed(on_position_changed)
        tracker.connect_selection_changed(on_selection_changed)
    """

    def __init__(self, source_view: GtkSource.View = None):
        self._source_view: Optional[GtkSource.View] = None
        self._buffer: Optional[GtkSource.Buffer] = None

        # Cached state
        self._position: Optional[CursorPosition] = None
        self._selection: Optional[Selection] = None

        # Callbacks
        self._position_callbacks: list = []
        self._selection_callbacks: list = []

        # Signal handler IDs
        self._cursor_handler_id: Optional[int] = None
        self._selection_handler_id: Optional[int] = None

        # Debounce timer
        self._debounce_timer: Optional[int] = None
        self._debounce_ms: int = 50

        if source_view:
            self.attach(source_view)

    def attach(self, source_view: GtkSource.View):
        """
        Attach the tracker to a GtkSourceView.

        Args:
            source_view: The GtkSourceView to monitor
        """
        # Detach from previous view if any
        self.detach()

        self._source_view = source_view
        self._buffer = source_view.get_buffer()

        # Connect signals with weak reference
        weak_self = weakref.ref(self)

        def on_cursor_position_changed(buffer, param):
            obj = weak_self()
            if obj is not None:
                obj._schedule_update()

        def on_mark_set(buffer, location, mark):
            obj = weak_self()
            if obj is not None:
                # Check if this is the insert or selection_bound mark
                insert_mark = buffer.get_insert()
                selection_mark = buffer.get_selection_bound()
                if mark == insert_mark or mark == selection_mark:
                    obj._schedule_update()

        self._cursor_handler_id = self._buffer.connect(
            'notify::cursor-position',
            on_cursor_position_changed
        )
        self._selection_handler_id = self._buffer.connect(
            'mark-set',
            on_mark_set
        )

        # Initial update
        self._update_state()

    def detach(self):
        """Detach the tracker from the current view"""
        if self._buffer and self._cursor_handler_id:
            try:
                self._buffer.disconnect(self._cursor_handler_id)
            except Exception:
                pass
            self._cursor_handler_id = None

        if self._buffer and self._selection_handler_id:
            try:
                self._buffer.disconnect(self._selection_handler_id)
            except Exception:
                pass
            self._selection_handler_id = None

        if self._debounce_timer:
            GLib.source_remove(self._debounce_timer)
            self._debounce_timer = None

        self._source_view = None
        self._buffer = None

    def _schedule_update(self):
        """Schedule a debounced state update"""
        if self._debounce_timer:
            GLib.source_remove(self._debounce_timer)

        self._debounce_timer = GLib.timeout_add(
            self._debounce_ms,
            self._debounced_update
        )

    def _debounced_update(self) -> bool:
        """Perform debounced update"""
        self._debounce_timer = None
        self._update_state()
        return False  # Don't repeat

    def _update_state(self):
        """Update cached position and selection state"""
        if not self._buffer:
            return

        old_position = self._position
        old_selection = self._selection

        # Get cursor position
        insert_mark = self._buffer.get_insert()
        if insert_mark:
            cursor_iter = self._buffer.get_iter_at_mark(insert_mark)
            self._position = CursorPosition(
                line=cursor_iter.get_line() + 1,
                column=cursor_iter.get_line_offset() + 1,
                offset=cursor_iter.get_offset()
            )

        # Get selection
        if self._buffer.get_has_selection():
            bounds = self._buffer.get_selection_bounds()
            if bounds:
                start_iter, end_iter = bounds
                text = self._buffer.get_text(start_iter, end_iter, True)
                self._selection = Selection(
                    start_line=start_iter.get_line() + 1,
                    start_column=start_iter.get_line_offset() + 1,
                    start_offset=start_iter.get_offset(),
                    end_line=end_iter.get_line() + 1,
                    end_column=end_iter.get_line_offset() + 1,
                    end_offset=end_iter.get_offset(),
                    text=text
                )
            else:
                self._selection = None
        else:
            self._selection = None

        # Fire callbacks if changed
        position_changed = (
            old_position is None or
            self._position is None or
            old_position.line != self._position.line or
            old_position.column != self._position.column
        )

        selection_changed = (
            (old_selection is None) != (self._selection is None) or
            (old_selection and self._selection and
             (old_selection.start_offset != self._selection.start_offset or
              old_selection.end_offset != self._selection.end_offset))
        )

        if position_changed:
            for callback in self._position_callbacks:
                try:
                    callback(self._position)
                except Exception as e:
                    print(f"Error in position callback: {e}")

        if selection_changed:
            for callback in self._selection_callbacks:
                try:
                    callback(self._selection)
                except Exception as e:
                    print(f"Error in selection callback: {e}")

    # Properties

    @property
    def line(self) -> int:
        """Current cursor line (1-indexed)"""
        return self._position.line if self._position else 1

    @property
    def column(self) -> int:
        """Current cursor column (1-indexed)"""
        return self._position.column if self._position else 1

    @property
    def offset(self) -> int:
        """Absolute character offset from document start"""
        return self._position.offset if self._position else 0

    @property
    def position(self) -> Optional[CursorPosition]:
        """Current cursor position"""
        return self._position

    @property
    def selection_start(self) -> Optional[Tuple[int, int]]:
        """Selection start as (line, column) tuple, or None"""
        if self._selection:
            return (self._selection.start_line, self._selection.start_column)
        return None

    @property
    def selection_end(self) -> Optional[Tuple[int, int]]:
        """Selection end as (line, column) tuple, or None"""
        if self._selection:
            return (self._selection.end_line, self._selection.end_column)
        return None

    @property
    def selected_text(self) -> Optional[str]:
        """Currently selected text, or None if no selection"""
        return self._selection.text if self._selection else None

    @property
    def has_selection(self) -> bool:
        """Whether there is an active selection"""
        return self._selection is not None and not self._selection.is_empty

    @property
    def selection(self) -> Optional[Selection]:
        """Current selection object"""
        return self._selection

    # Callback registration

    def connect_position_changed(self, callback: Callable[[CursorPosition], None]):
        """
        Connect a callback for cursor position changes.

        Args:
            callback: Function called with CursorPosition when cursor moves
        """
        if callback not in self._position_callbacks:
            self._position_callbacks.append(callback)

    def disconnect_position_changed(self, callback: Callable):
        """Disconnect a position change callback"""
        if callback in self._position_callbacks:
            self._position_callbacks.remove(callback)

    def connect_selection_changed(self, callback: Callable[[Optional[Selection]], None]):
        """
        Connect a callback for selection changes.

        Args:
            callback: Function called with Selection (or None) when selection changes
        """
        if callback not in self._selection_callbacks:
            self._selection_callbacks.append(callback)

    def disconnect_selection_changed(self, callback: Callable):
        """Disconnect a selection change callback"""
        if callback in self._selection_callbacks:
            self._selection_callbacks.remove(callback)

    # Context extraction

    def get_context(self, lines_before: int = 5, lines_after: int = 5) -> Dict[str, Any]:
        """
        Get context around the current cursor position for AI assistance.

        Args:
            lines_before: Number of lines to include before cursor
            lines_after: Number of lines to include after cursor

        Returns:
            Dictionary with context information:
            - position: Current cursor position
            - current_line: Text of the current line
            - text_before: Text in lines before cursor
            - text_after: Text in lines after cursor
            - surrounding_text: Combined context text
            - selection: Selected text if any
            - word_at_cursor: Word under/before cursor
        """
        if not self._buffer or not self._position:
            return {
                'position': None,
                'current_line': '',
                'text_before': '',
                'text_after': '',
                'surrounding_text': '',
                'selection': None,
                'word_at_cursor': ''
            }

        line = self._position.line - 1  # 0-indexed
        line_count = self._buffer.get_line_count()

        # Calculate line ranges
        start_line = max(0, line - lines_before)
        end_line = min(line_count - 1, line + lines_after)

        # Get current line text
        current_line_start = self._buffer.get_iter_at_line(line)
        current_line_end = current_line_start.copy()
        if not current_line_end.ends_line():
            current_line_end.forward_to_line_end()
        current_line_text = self._buffer.get_text(
            current_line_start, current_line_end, True
        )

        # Get text before cursor (context lines)
        before_start = self._buffer.get_iter_at_line(start_line)
        before_end = self._buffer.get_iter_at_line(line)
        text_before = self._buffer.get_text(before_start, before_end, True)

        # Get text after cursor (context lines)
        after_start = self._buffer.get_iter_at_line(line)
        if not after_start.ends_line():
            after_start.forward_to_line_end()
        after_start.forward_char()  # Move to next line
        after_end = self._buffer.get_iter_at_line(end_line)
        if not after_end.ends_line():
            after_end.forward_to_line_end()
        text_after = self._buffer.get_text(after_start, after_end, True)

        # Get word at cursor
        word = self._get_word_at_cursor()

        # Combined surrounding text
        surrounding_start = self._buffer.get_iter_at_line(start_line)
        surrounding_end = self._buffer.get_iter_at_line(end_line)
        if not surrounding_end.ends_line():
            surrounding_end.forward_to_line_end()
        surrounding_text = self._buffer.get_text(
            surrounding_start, surrounding_end, True
        )

        return {
            'position': self._position,
            'current_line': current_line_text,
            'text_before': text_before,
            'text_after': text_after,
            'surrounding_text': surrounding_text,
            'selection': self.selected_text,
            'word_at_cursor': word
        }

    def _get_word_at_cursor(self) -> str:
        """Get the word at or immediately before the cursor"""
        if not self._buffer:
            return ''

        insert_mark = self._buffer.get_insert()
        if not insert_mark:
            return ''

        cursor = self._buffer.get_iter_at_mark(insert_mark)

        # Find word boundaries
        word_start = cursor.copy()
        word_end = cursor.copy()

        # Move to word start
        if not word_start.starts_word():
            word_start.backward_word_start()

        # Move to word end
        if not word_end.ends_word():
            word_end.forward_word_end()

        # Check if cursor is within a word
        if word_start.get_offset() <= cursor.get_offset() <= word_end.get_offset():
            return self._buffer.get_text(word_start, word_end, True)

        return ''

    def get_line_text(self, line: int) -> str:
        """
        Get the text of a specific line.

        Args:
            line: Line number (1-indexed)

        Returns:
            Text content of the line
        """
        if not self._buffer:
            return ''

        line_idx = line - 1
        if line_idx < 0 or line_idx >= self._buffer.get_line_count():
            return ''

        line_start = self._buffer.get_iter_at_line(line_idx)
        line_end = line_start.copy()
        if not line_end.ends_line():
            line_end.forward_to_line_end()

        return self._buffer.get_text(line_start, line_end, True)

    def get_text_range(self, start_line: int, start_col: int,
                       end_line: int, end_col: int) -> str:
        """
        Get text in a specific range.

        Args:
            start_line: Start line (1-indexed)
            start_col: Start column (1-indexed)
            end_line: End line (1-indexed)
            end_col: End column (1-indexed)

        Returns:
            Text in the specified range
        """
        if not self._buffer:
            return ''

        # Validate bounds
        line_count = self._buffer.get_line_count()
        start_line = max(1, min(start_line, line_count))
        end_line = max(1, min(end_line, line_count))

        start_iter = self._buffer.get_iter_at_line_offset(
            start_line - 1,
            max(0, start_col - 1)
        )
        end_iter = self._buffer.get_iter_at_line_offset(
            end_line - 1,
            max(0, end_col - 1)
        )

        return self._buffer.get_text(start_iter, end_iter, True)

    def set_debounce(self, ms: int):
        """
        Set the debounce interval for position updates.

        Args:
            ms: Milliseconds to debounce (default 50)
        """
        self._debounce_ms = max(0, ms)

    def force_update(self):
        """Force an immediate state update"""
        if self._debounce_timer:
            GLib.source_remove(self._debounce_timer)
            self._debounce_timer = None
        self._update_state()

    def __del__(self):
        """Cleanup on destruction"""
        self.detach()
