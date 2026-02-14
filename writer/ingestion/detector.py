"""
Format Detector for document ingestion
Identifies file types using magic bytes, extensions, and content analysis
"""

import logging
import mimetypes
from enum import Enum, auto
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class FileFormat(Enum):
    """Supported file formats for Frank Writer"""
    # Text formats
    MARKDOWN = auto()
    LATEX = auto()
    HTML = auto()
    XML = auto()
    JSON = auto()
    YAML = auto()
    TOML = auto()
    TEXT = auto()

    # Binary document formats
    PDF = auto()
    DOCX = auto()
    ODT = auto()
    RTF = auto()

    # Code formats
    PYTHON = auto()
    JAVASCRIPT = auto()
    TYPESCRIPT = auto()
    BASH = auto()
    GO = auto()
    RUST = auto()
    JAVA = auto()
    C = auto()
    CPP = auto()
    CSHARP = auto()
    RUBY = auto()
    PHP = auto()
    SQL = auto()
    CSS = auto()

    # Data formats
    CSV = auto()
    TSV = auto()

    # Image formats (for reference)
    PNG = auto()
    JPEG = auto()
    GIF = auto()
    SVG = auto()

    # Unknown
    UNKNOWN = auto()


# Magic byte signatures for binary format detection
MAGIC_BYTES = {
    # PDF: %PDF
    b'%PDF': FileFormat.PDF,
    # DOCX/XLSX/PPTX (ZIP-based): PK
    b'PK\x03\x04': FileFormat.DOCX,  # Need further inspection for DOCX vs others
    # PNG
    b'\x89PNG\r\n\x1a\n': FileFormat.PNG,
    # JPEG
    b'\xff\xd8\xff': FileFormat.JPEG,
    # GIF87a and GIF89a
    b'GIF87a': FileFormat.GIF,
    b'GIF89a': FileFormat.GIF,
    # RTF
    b'{\\rtf': FileFormat.RTF,
}

# Extension to format mapping
EXTENSION_MAP = {
    # Markdown
    '.md': FileFormat.MARKDOWN,
    '.markdown': FileFormat.MARKDOWN,
    '.mdown': FileFormat.MARKDOWN,
    '.mkd': FileFormat.MARKDOWN,

    # LaTeX
    '.tex': FileFormat.LATEX,
    '.latex': FileFormat.LATEX,
    '.ltx': FileFormat.LATEX,
    '.bib': FileFormat.LATEX,

    # HTML/XML
    '.html': FileFormat.HTML,
    '.htm': FileFormat.HTML,
    '.xhtml': FileFormat.HTML,
    '.xml': FileFormat.XML,
    '.svg': FileFormat.SVG,

    # Data formats
    '.json': FileFormat.JSON,
    '.yaml': FileFormat.YAML,
    '.yml': FileFormat.YAML,
    '.toml': FileFormat.TOML,
    '.csv': FileFormat.CSV,
    '.tsv': FileFormat.TSV,

    # Documents
    '.pdf': FileFormat.PDF,
    '.docx': FileFormat.DOCX,
    '.odt': FileFormat.ODT,
    '.rtf': FileFormat.RTF,
    '.txt': FileFormat.TEXT,

    # Python
    '.py': FileFormat.PYTHON,
    '.pyw': FileFormat.PYTHON,
    '.pyi': FileFormat.PYTHON,

    # JavaScript/TypeScript
    '.js': FileFormat.JAVASCRIPT,
    '.mjs': FileFormat.JAVASCRIPT,
    '.cjs': FileFormat.JAVASCRIPT,
    '.jsx': FileFormat.JAVASCRIPT,
    '.ts': FileFormat.TYPESCRIPT,
    '.tsx': FileFormat.TYPESCRIPT,

    # Shell
    '.sh': FileFormat.BASH,
    '.bash': FileFormat.BASH,
    '.zsh': FileFormat.BASH,

    # Other languages
    '.go': FileFormat.GO,
    '.rs': FileFormat.RUST,
    '.java': FileFormat.JAVA,
    '.c': FileFormat.C,
    '.h': FileFormat.C,
    '.cpp': FileFormat.CPP,
    '.cc': FileFormat.CPP,
    '.cxx': FileFormat.CPP,
    '.hpp': FileFormat.CPP,
    '.hxx': FileFormat.CPP,
    '.cs': FileFormat.CSHARP,
    '.rb': FileFormat.RUBY,
    '.php': FileFormat.PHP,
    '.sql': FileFormat.SQL,
    '.css': FileFormat.CSS,
    '.scss': FileFormat.CSS,
    '.sass': FileFormat.CSS,
    '.less': FileFormat.CSS,

    # Images
    '.png': FileFormat.PNG,
    '.jpg': FileFormat.JPEG,
    '.jpeg': FileFormat.JPEG,
    '.gif': FileFormat.GIF,
}

# Shebang patterns for script detection
SHEBANG_PATTERNS = {
    'python': FileFormat.PYTHON,
    'python3': FileFormat.PYTHON,
    'bash': FileFormat.BASH,
    'sh': FileFormat.BASH,
    'zsh': FileFormat.BASH,
    'node': FileFormat.JAVASCRIPT,
    'ruby': FileFormat.RUBY,
    'php': FileFormat.PHP,
    'perl': FileFormat.UNKNOWN,  # Not directly supported but detected
}


class FormatDetector:
    """Detects file format using multiple strategies"""

    def __init__(self):
        """Initialize the format detector"""
        # Initialize mimetypes
        mimetypes.init()

    def detect(self, file_path: Path) -> FileFormat:
        """
        Detect file format from file path

        Uses multiple strategies:
        1. Magic bytes for binary files
        2. Extension mapping
        3. Content analysis if needed

        Args:
            file_path: Path to the file

        Returns:
            FileFormat enum value
        """
        file_path = Path(file_path)

        if not file_path.exists():
            logger.warning(f"File not found: {file_path}")
            return FileFormat.UNKNOWN

        # Try magic bytes first (for binary files)
        magic_format = self._detect_magic_bytes(file_path)
        if magic_format != FileFormat.UNKNOWN:
            # Special handling for ZIP-based formats
            if magic_format == FileFormat.DOCX:
                magic_format = self._detect_office_format(file_path)
            return magic_format

        # Try extension mapping
        ext_format = self._detect_by_extension(file_path)
        if ext_format != FileFormat.UNKNOWN:
            return ext_format

        # Try content analysis for text files
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            return self.detect_from_content(content, file_path.name)
        except Exception as e:
            logger.warning(f"Failed to read file for content analysis: {e}")
            return FileFormat.UNKNOWN

    def detect_from_content(self, content: str, filename: str = "") -> FileFormat:
        """
        Detect format from content and optional filename

        Args:
            content: File content as string
            filename: Optional filename for extension hint

        Returns:
            FileFormat enum value
        """
        # Try extension first if filename provided
        if filename:
            ext_format = self._detect_by_extension(Path(filename))
            if ext_format != FileFormat.UNKNOWN:
                return ext_format

        # Analyze content
        return self._analyze_content(content)

    def _detect_magic_bytes(self, file_path: Path) -> FileFormat:
        """Detect format using magic bytes"""
        try:
            with open(file_path, 'rb') as f:
                header = f.read(16)  # Read first 16 bytes

            # Check against known magic bytes
            for magic, fmt in MAGIC_BYTES.items():
                if header.startswith(magic):
                    return fmt

            return FileFormat.UNKNOWN
        except Exception as e:
            logger.debug(f"Magic byte detection failed: {e}")
            return FileFormat.UNKNOWN

    def _detect_by_extension(self, file_path: Path) -> FileFormat:
        """Detect format using file extension"""
        ext = file_path.suffix.lower()
        return EXTENSION_MAP.get(ext, FileFormat.UNKNOWN)

    def _detect_office_format(self, file_path: Path) -> FileFormat:
        """
        Detect specific Office format from ZIP-based file
        DOCX, XLSX, PPTX all use ZIP container
        """
        try:
            import zipfile

            with zipfile.ZipFile(file_path, 'r') as zf:
                names = zf.namelist()

                # Check for content types
                if '[Content_Types].xml' in names:
                    content_types = zf.read('[Content_Types].xml').decode('utf-8', errors='ignore')

                    if 'wordprocessingml' in content_types:
                        return FileFormat.DOCX
                    # Could add XLSX, PPTX detection here

                # Fallback: check for word/ directory
                if any(n.startswith('word/') for n in names):
                    return FileFormat.DOCX

            return FileFormat.DOCX  # Default to DOCX for ZIP with PK header
        except Exception as e:
            logger.debug(f"Office format detection failed: {e}")
            return FileFormat.DOCX

    def _analyze_content(self, content: str) -> FileFormat:
        """Analyze text content to determine format"""
        if not content or not content.strip():
            return FileFormat.TEXT

        content = content.strip()
        first_line = content.split('\n')[0].strip() if '\n' in content else content

        # Check for shebang
        if first_line.startswith('#!'):
            shebang_format = self._parse_shebang(first_line)
            if shebang_format != FileFormat.UNKNOWN:
                return shebang_format

        # Check for HTML/XML
        if content.startswith('<!DOCTYPE html') or content.startswith('<html'):
            return FileFormat.HTML
        if content.startswith('<?xml') or (content.startswith('<') and '>' in content):
            return FileFormat.XML

        # Check for JSON
        if (content.startswith('{') and content.endswith('}')) or \
           (content.startswith('[') and content.endswith(']')):
            try:
                import json
                json.loads(content)
                return FileFormat.JSON
            except json.JSONDecodeError:
                pass

        # Check for YAML (common patterns)
        if content.startswith('---') or ': ' in first_line:
            # Could be YAML
            try:
                import yaml
                yaml.safe_load(content)
                # Additional heuristics to distinguish YAML from markdown
                if not first_line.startswith('#') or ': ' in first_line:
                    return FileFormat.YAML
            except yaml.YAMLError:
                pass

        # Check for LaTeX
        if '\\documentclass' in content or '\\begin{document}' in content:
            return FileFormat.LATEX
        if content.startswith('%') and ('\\' in content or 'LaTeX' in first_line):
            return FileFormat.LATEX

        # Check for Markdown (headings, links, emphasis)
        markdown_indicators = [
            first_line.startswith('#'),  # Headings
            '**' in content,  # Bold
            '*' in content and not content.startswith('/*'),  # Italic (not C comment)
            '[' in content and '](' in content,  # Links
            '```' in content,  # Code blocks
            '- ' in content or '* ' in content,  # Lists
        ]
        if sum(markdown_indicators) >= 2:
            return FileFormat.MARKDOWN

        # Check for Python
        python_indicators = [
            'import ' in content,
            'from ' in content and ' import ' in content,
            'def ' in content,
            'class ' in content,
            'if __name__' in content,
        ]
        if sum(python_indicators) >= 2:
            return FileFormat.PYTHON

        # Check for JavaScript
        js_indicators = [
            'const ' in content,
            'let ' in content,
            'var ' in content,
            'function ' in content,
            'require(' in content,
            'import ' in content and 'from ' in content,
            '=>' in content,
        ]
        if sum(js_indicators) >= 2:
            return FileFormat.JAVASCRIPT

        # Check for CSS
        if '{' in content and '}' in content:
            css_patterns = [':' in content, ';' in content,
                           any(p in content for p in ['color:', 'margin:', 'padding:', 'font-'])]
            if sum(css_patterns) >= 2:
                return FileFormat.CSS

        # Default to text
        return FileFormat.TEXT

    def _parse_shebang(self, shebang_line: str) -> FileFormat:
        """Parse shebang line to detect script type"""
        # Remove #! and split
        shebang = shebang_line[2:].strip()

        # Handle /usr/bin/env
        if 'env ' in shebang:
            interpreter = shebang.split('env ')[-1].split()[0]
        else:
            # Get basename of interpreter
            interpreter = shebang.split('/')[-1].split()[0]

        return SHEBANG_PATTERNS.get(interpreter, FileFormat.UNKNOWN)

    def get_mime_type(self, file_format: FileFormat) -> str:
        """Get MIME type for a file format"""
        mime_map = {
            FileFormat.MARKDOWN: 'text/markdown',
            FileFormat.LATEX: 'application/x-latex',
            FileFormat.HTML: 'text/html',
            FileFormat.XML: 'application/xml',
            FileFormat.JSON: 'application/json',
            FileFormat.YAML: 'application/x-yaml',
            FileFormat.TOML: 'application/toml',
            FileFormat.TEXT: 'text/plain',
            FileFormat.PDF: 'application/pdf',
            FileFormat.DOCX: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            FileFormat.ODT: 'application/vnd.oasis.opendocument.text',
            FileFormat.RTF: 'application/rtf',
            FileFormat.PYTHON: 'text/x-python',
            FileFormat.JAVASCRIPT: 'application/javascript',
            FileFormat.TYPESCRIPT: 'application/typescript',
            FileFormat.BASH: 'application/x-sh',
            FileFormat.CSS: 'text/css',
            FileFormat.CSV: 'text/csv',
            FileFormat.PNG: 'image/png',
            FileFormat.JPEG: 'image/jpeg',
            FileFormat.GIF: 'image/gif',
            FileFormat.SVG: 'image/svg+xml',
        }
        return mime_map.get(file_format, 'application/octet-stream')

    def is_binary(self, file_format: FileFormat) -> bool:
        """Check if format is binary"""
        binary_formats = {
            FileFormat.PDF, FileFormat.DOCX, FileFormat.ODT, FileFormat.RTF,
            FileFormat.PNG, FileFormat.JPEG, FileFormat.GIF,
        }
        return file_format in binary_formats

    def is_code(self, file_format: FileFormat) -> bool:
        """Check if format is source code"""
        code_formats = {
            FileFormat.PYTHON, FileFormat.JAVASCRIPT, FileFormat.TYPESCRIPT,
            FileFormat.BASH, FileFormat.GO, FileFormat.RUST, FileFormat.JAVA,
            FileFormat.C, FileFormat.CPP, FileFormat.CSHARP, FileFormat.RUBY,
            FileFormat.PHP, FileFormat.SQL, FileFormat.CSS,
        }
        return file_format in code_formats

    def is_document(self, file_format: FileFormat) -> bool:
        """Check if format is a document type"""
        doc_formats = {
            FileFormat.MARKDOWN, FileFormat.LATEX, FileFormat.HTML,
            FileFormat.PDF, FileFormat.DOCX, FileFormat.ODT, FileFormat.RTF,
            FileFormat.TEXT,
        }
        return file_format in doc_formats


def detect_format(file_path: Path) -> FileFormat:
    """Convenience function for format detection"""
    detector = FormatDetector()
    return detector.detect(file_path)


def detect_format_from_content(content: str, filename: str = "") -> FileFormat:
    """Convenience function for content-based detection"""
    detector = FormatDetector()
    return detector.detect_from_content(content, filename)
