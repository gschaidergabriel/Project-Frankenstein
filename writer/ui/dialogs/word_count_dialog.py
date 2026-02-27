"""
Word Count Dialog - detailed document statistics
"""

import re
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw


class WordCountDialog(Adw.Window):
    """Detailed word/character/line count dialog."""

    def __init__(self, parent, document):
        super().__init__()
        self.set_title("Document Statistics")
        self.set_default_size(350, 300)
        self.set_transient_for(parent)
        self.set_modal(True)

        content = document.content if document else ""
        stats = self._compute_stats(content)
        self._build_ui(stats)

    def _compute_stats(self, content: str) -> dict:
        lines = content.splitlines()
        words = content.split()
        chars_with_spaces = len(content)
        chars_no_spaces = len(content.replace(' ', '').replace('\t', '').replace('\n', ''))
        paragraphs = len([p for p in content.split('\n\n') if p.strip()])
        sentences = len(re.findall(r'[.!?]+\s', content)) + (1 if content.strip() else 0)

        # Estimate pages (250 words per page)
        pages = max(1, (len(words) + 249) // 250) if words else 0

        # Reading time (~200 wpm)
        reading_min = max(1, len(words) // 200) if words else 0

        return {
            'words': len(words),
            'chars_with_spaces': chars_with_spaces,
            'chars_no_spaces': chars_no_spaces,
            'lines': len(lines),
            'paragraphs': paragraphs,
            'sentences': sentences,
            'pages': pages,
            'reading_min': reading_min,
        }

    def _build_ui(self, stats: dict):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        main_box.append(header)

        group = Adw.PreferencesGroup(title="Document Statistics")
        group.set_margin_start(24)
        group.set_margin_end(24)
        group.set_margin_top(12)
        group.set_margin_bottom(24)

        rows = [
            ("Words", str(stats['words'])),
            ("Characters (with spaces)", str(stats['chars_with_spaces'])),
            ("Characters (no spaces)", str(stats['chars_no_spaces'])),
            ("Lines", str(stats['lines'])),
            ("Paragraphs", str(stats['paragraphs'])),
            ("Sentences", str(stats['sentences'])),
            ("Estimated Pages", str(stats['pages'])),
            ("Reading Time", f"~{stats['reading_min']} min"),
        ]

        for title, value in rows:
            row = Adw.ActionRow(title=title)
            label = Gtk.Label(label=value)
            label.add_css_class("dim-label")
            row.add_suffix(label)
            group.add(row)

        main_box.append(group)
