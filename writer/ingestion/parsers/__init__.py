"""Parsers module"""
from .pdf_parser import extract_text_from_pdf, get_pdf_metadata
from .docx_parser import extract_text_from_docx, extract_structure_from_docx, get_docx_metadata

__all__ = [
    'extract_text_from_pdf', 'get_pdf_metadata',
    'extract_text_from_docx', 'extract_structure_from_docx', 'get_docx_metadata'
]
