"""Editor module"""
from .document import Document, DocumentSection
from .source_view import WriterSourceView
from .language_manager import LanguageManager, get_default as get_language_manager

__all__ = [
    'Document',
    'DocumentSection',
    'WriterSourceView',
    'LanguageManager',
    'get_language_manager',
]
