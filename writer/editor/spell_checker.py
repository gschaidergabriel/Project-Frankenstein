"""
Spell Checker for Frank Writer
Uses hunspell via subprocess for spell checking.
Gracefully degrades if hunspell or enchant is not available.
"""

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gdk, Pango, GLib

import subprocess
import re
import threading
from typing import Optional, Set


class SpellChecker:
    """
    Spell checker that attaches to a GtkSource.Buffer.
    Uses hunspell subprocess or pyenchant for checking.
    Underlines misspelled words with a red wavy underline tag.
    """

    def __init__(self, language: str = "de_DE"):
        self._language = language
        self._enabled = False
        self._buffer = None
        self._view = None
        self._tag = None
        self._check_timer_id = None
        self._known_words: Set[str] = set()
        self._backend = self._detect_backend()

    def _detect_backend(self) -> str:
        """Detect available spell checking backend."""
        # Try pyenchant first
        try:
            import enchant
            enchant.Dict(self._language)
            return "enchant"
        except Exception:
            pass

        # Try hunspell subprocess
        try:
            result = subprocess.run(
                ["hunspell", "-D"],
                capture_output=True, text=True, timeout=2
            )
            return "hunspell"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Try aspell subprocess
        try:
            result = subprocess.run(
                ["aspell", "--version"],
                capture_output=True, text=True, timeout=2
            )
            return "aspell"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return "none"

    @property
    def available(self) -> bool:
        return self._backend != "none"

    @property
    def enabled(self) -> bool:
        return self._enabled

    def attach(self, view):
        """Attach spell checker to a GtkSourceView."""
        self._view = view
        self._buffer = view.get_buffer()

        # Create misspelling tag
        tag_table = self._buffer.get_tag_table()
        self._tag = tag_table.lookup("misspelled")
        if not self._tag:
            self._tag = Gtk.TextTag.new("misspelled")
            self._tag.set_property("underline", Pango.Underline.ERROR)
            rgba = Gdk.RGBA()
            rgba.parse("#e01b24")
            self._tag.set_property("underline-rgba", rgba)
            tag_table.add(self._tag)

        # Connect buffer changed signal for live checking
        self._buffer.connect('changed', self._on_buffer_changed)

    def enable(self):
        """Enable spell checking."""
        if not self.available:
            return
        self._enabled = True
        self._schedule_check()

    def disable(self):
        """Disable spell checking and clear marks."""
        self._enabled = False
        if self._check_timer_id:
            GLib.source_remove(self._check_timer_id)
            self._check_timer_id = None
        self._clear_marks()

    def set_language(self, language: str):
        """Change spell checking language."""
        self._language = language
        if self._enabled:
            self._schedule_check()

    def add_word(self, word: str):
        """Add word to known-good words."""
        self._known_words.add(word.lower())

    def _on_buffer_changed(self, buffer):
        """Debounced recheck on buffer change."""
        if not self._enabled:
            return
        self._schedule_check()

    def _schedule_check(self):
        """Schedule a spell check with debouncing."""
        if self._check_timer_id:
            GLib.source_remove(self._check_timer_id)
        self._check_timer_id = GLib.timeout_add(500, self._do_check)

    def _do_check(self):
        """Perform spell check on current buffer content."""
        self._check_timer_id = None
        if not self._enabled or not self._buffer:
            return False

        start = self._buffer.get_start_iter()
        end = self._buffer.get_end_iter()
        text = self._buffer.get_text(start, end, True)

        if not text.strip():
            return False

        # Run check in thread to avoid blocking UI
        thread = threading.Thread(
            target=self._check_text_async, args=(text,), daemon=True
        )
        thread.start()
        return False

    def _check_text_async(self, text: str):
        """Check text in background thread, apply results on main thread."""
        misspelled = self._find_misspelled(text)
        GLib.idle_add(self._apply_misspelled_marks, text, misspelled)

    def _find_misspelled(self, text: str) -> Set[str]:
        """Find misspelled words using the available backend."""
        words = set(re.findall(r'\b[a-zA-ZäöüÄÖÜß]{2,}\b', text))
        misspelled = set()

        if self._backend == "enchant":
            try:
                import enchant
                d = enchant.Dict(self._language)
                for word in words:
                    if word.lower() not in self._known_words and not d.check(word):
                        misspelled.add(word)
            except Exception:
                pass

        elif self._backend == "hunspell":
            try:
                # Feed words to hunspell
                word_list = '\n'.join(words)
                result = subprocess.run(
                    ["hunspell", "-d", self._language, "-l"],
                    input=word_list, capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.strip().split('\n'):
                    word = line.strip()
                    if word and word.lower() not in self._known_words:
                        misspelled.add(word)
            except Exception:
                pass

        elif self._backend == "aspell":
            try:
                word_list = '\n'.join(words)
                result = subprocess.run(
                    ["aspell", "-d", self._language, "list"],
                    input=word_list, capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.strip().split('\n'):
                    word = line.strip()
                    if word and word.lower() not in self._known_words:
                        misspelled.add(word)
            except Exception:
                pass

        return misspelled

    def _apply_misspelled_marks(self, text: str, misspelled: Set[str]):
        """Apply misspelling underlines on the main thread."""
        if not self._enabled or not self._buffer or not self._tag:
            return False

        # Clear old marks
        start = self._buffer.get_start_iter()
        end = self._buffer.get_end_iter()
        self._buffer.remove_tag(self._tag, start, end)

        if not misspelled:
            return False

        # Mark each misspelled word
        for word in misspelled:
            # Find all occurrences using word boundary regex
            pattern = re.compile(r'\b' + re.escape(word) + r'\b')
            for match in pattern.finditer(text):
                start_offset = match.start()
                end_offset = match.end()

                start_iter = self._buffer.get_iter_at_offset(start_offset)
                end_iter = self._buffer.get_iter_at_offset(end_offset)
                self._buffer.apply_tag(self._tag, start_iter, end_iter)

        return False

    def _clear_marks(self):
        """Remove all misspelling marks."""
        if self._buffer and self._tag:
            start = self._buffer.get_start_iter()
            end = self._buffer.get_end_iter()
            self._buffer.remove_tag(self._tag, start, end)

    def get_suggestions(self, word: str, max_count: int = 5) -> list:
        """Get spelling suggestions for a word."""
        if self._backend == "enchant":
            try:
                import enchant
                d = enchant.Dict(self._language)
                return d.suggest(word)[:max_count]
            except Exception:
                pass

        elif self._backend == "hunspell":
            try:
                result = subprocess.run(
                    ["hunspell", "-d", self._language, "-a"],
                    input=word, capture_output=True, text=True, timeout=3
                )
                suggestions = []
                for line in result.stdout.split('\n'):
                    if line.startswith('&'):
                        parts = line.split(':')
                        if len(parts) > 1:
                            suggestions = [s.strip() for s in parts[1].split(',')]
                return suggestions[:max_count]
            except Exception:
                pass

        return []
