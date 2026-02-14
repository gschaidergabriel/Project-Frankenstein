"""
Ingestion module for Frank Writer
Handles document parsing, format detection, and content analysis
"""
from .parsers import (
    extract_text_from_pdf, get_pdf_metadata,
    extract_text_from_docx, extract_structure_from_docx, get_docx_metadata
)

# Format detection
from .detector import (
    FormatDetector,
    FileFormat,
    detect_format,
    detect_format_from_content,
)

# Document analysis
from .analyzer import (
    DocumentAnalyzer,
    DocumentAnalysis,
    StyleAnalysis,
    analyze_document,
)

# Markdown parsing
from .markdown_parser import (
    MarkdownParser,
    MarkdownDocument,
    MarkdownNode,
    MarkdownNodeType,
    parse_markdown,
    markdown_to_html,
)

# LaTeX parsing
from .latex_parser import (
    LatexParser,
    LatexDocument,
    LatexNode,
    LatexNodeType,
    parse_latex,
    parse_bibtex,
)

# Code parsing
from .code_parser import (
    CodeParser,
    CodeDocument,
    CodeNode,
    CodeNodeType,
    parse_code,
    parse_code_file,
)

__all__ = [
    # PDF/DOCX parsers
    'extract_text_from_pdf', 'get_pdf_metadata',
    'extract_text_from_docx', 'extract_structure_from_docx', 'get_docx_metadata',
    # Format detection
    'FormatDetector', 'FileFormat', 'detect_format', 'detect_format_from_content',
    # Document analysis
    'DocumentAnalyzer', 'DocumentAnalysis', 'StyleAnalysis', 'analyze_document',
    # Markdown parsing
    'MarkdownParser', 'MarkdownDocument', 'MarkdownNode', 'MarkdownNodeType',
    'parse_markdown', 'markdown_to_html',
    # LaTeX parsing
    'LatexParser', 'LatexDocument', 'LatexNode', 'LatexNodeType',
    'parse_latex', 'parse_bibtex',
    # Code parsing
    'CodeParser', 'CodeDocument', 'CodeNode', 'CodeNodeType',
    'parse_code', 'parse_code_file',
]
