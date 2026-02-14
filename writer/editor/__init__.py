"""Editor module"""
from .document import Document, DocumentSection
from .source_view import WriterSourceView
from .rich_view import RichTextView
from .cursor_tracker import CursorTracker, CursorPosition, Selection
from .language_manager import LanguageManager, get_default as get_language_manager

__all__ = [
    'Document',
    'DocumentSection',
    'WriterSourceView',
    'RichTextView',
    'CursorTracker',
    'CursorPosition',
    'Selection',
    'LanguageManager',
    'get_language_manager',
]
