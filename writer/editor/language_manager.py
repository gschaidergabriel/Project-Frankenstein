"""
Language Manager for Frank Writer
Handles language detection and syntax highlighting configuration
"""

import gi
gi.require_version('GtkSource', '5')
from gi.repository import GtkSource

import re
from pathlib import Path
from typing import Optional, List, Dict, Tuple


class LanguageManager:
    """
    Manages language detection and syntax highlighting for Frank Writer.

    Wraps GtkSourceView's LanguageManager with additional features:
    - Automatic language detection from filename and content
    - Support for common programming and markup languages
    - Fallback detection using content analysis

    Supported languages:
    - Programming: python, javascript, typescript, bash, sql, rust, go, java, c, cpp
    - Markup: html, css, markdown, latex, xml
    - Data: json, yaml, toml
    """

    # Extension to language ID mapping
    EXTENSION_MAP: Dict[str, str] = {
        # Python
        '.py': 'python',
        '.pyw': 'python',
        '.pyi': 'python',

        # JavaScript/TypeScript
        '.js': 'javascript',
        '.mjs': 'javascript',
        '.cjs': 'javascript',
        '.jsx': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'typescript',

        # Web
        '.html': 'html',
        '.htm': 'html',
        '.xhtml': 'html',
        '.css': 'css',
        '.scss': 'css',
        '.sass': 'css',
        '.less': 'css',

        # Markup
        '.md': 'markdown',
        '.markdown': 'markdown',
        '.tex': 'latex',
        '.latex': 'latex',
        '.xml': 'xml',
        '.xsl': 'xml',
        '.xslt': 'xml',
        '.svg': 'xml',

        # Data formats
        '.json': 'json',
        '.jsonc': 'json',
        '.yaml': 'yaml',
        '.yml': 'yaml',
        '.toml': 'toml',

        # Shell
        '.sh': 'bash',
        '.bash': 'bash',
        '.zsh': 'bash',
        '.fish': 'bash',

        # Database
        '.sql': 'sql',

        # Systems programming
        '.rs': 'rust',
        '.go': 'go',
        '.c': 'c',
        '.h': 'c',
        '.cpp': 'cpp',
        '.hpp': 'cpp',
        '.cc': 'cpp',
        '.cxx': 'cpp',
        '.hh': 'cpp',
        '.hxx': 'cpp',

        # JVM
        '.java': 'java',
        '.kt': 'kotlin',
        '.scala': 'scala',
        '.groovy': 'groovy',

        # Other
        '.rb': 'ruby',
        '.php': 'php',
        '.pl': 'perl',
        '.pm': 'perl',
        '.lua': 'lua',
        '.r': 'r',
        '.R': 'r',
        '.swift': 'swift',
        '.m': 'objc',
        '.mm': 'objc',

        # Config
        '.ini': 'ini',
        '.cfg': 'ini',
        '.conf': 'ini',
        '.properties': 'ini',

        # Docs
        '.rst': 'rst',
        '.txt': 'text',
    }

    # Content patterns for language detection
    CONTENT_PATTERNS: List[Tuple[str, str]] = [
        # Shebangs
        (r'^#!.*\bpython', 'python'),
        (r'^#!.*\bnode', 'javascript'),
        (r'^#!.*\bbash', 'bash'),
        (r'^#!.*\bsh\b', 'bash'),
        (r'^#!.*\bzsh', 'bash'),
        (r'^#!.*\bruby', 'ruby'),
        (r'^#!.*\bperl', 'perl'),
        (r'^#!.*\bphp', 'php'),

        # HTML/XML
        (r'^\s*<!DOCTYPE\s+html', 'html'),
        (r'^\s*<html', 'html'),
        (r'^\s*<\?xml', 'xml'),

        # JSON
        (r'^\s*\{[\s\n]*"', 'json'),
        (r'^\s*\[[\s\n]*\{', 'json'),

        # YAML
        (r'^---\s*$', 'yaml'),
        (r'^\w+:\s*\n', 'yaml'),

        # Markdown
        (r'^#\s+\w', 'markdown'),
        (r'^\*\*\w.*\*\*', 'markdown'),

        # LaTeX
        (r'^\\documentclass', 'latex'),
        (r'^\\begin\{document\}', 'latex'),

        # Python
        (r'^import\s+\w', 'python'),
        (r'^from\s+\w+\s+import', 'python'),
        (r'^def\s+\w+\s*\(', 'python'),
        (r'^class\s+\w+[\(:]', 'python'),

        # JavaScript/TypeScript
        (r'^(const|let|var)\s+\w+\s*=', 'javascript'),
        (r'^function\s+\w+\s*\(', 'javascript'),
        (r'^export\s+(default\s+)?', 'javascript'),
        (r'^import\s+.*\s+from\s+[\'"]', 'javascript'),
        (r'^interface\s+\w+\s*\{', 'typescript'),
        (r'^type\s+\w+\s*=', 'typescript'),

        # Rust
        (r'^fn\s+\w+', 'rust'),
        (r'^use\s+\w+::', 'rust'),
        (r'^impl\s+', 'rust'),
        (r'^struct\s+\w+', 'rust'),

        # Go
        (r'^package\s+\w+', 'go'),
        (r'^func\s+\w*\(', 'go'),
        (r'^import\s+\(', 'go'),

        # Java
        (r'^public\s+class', 'java'),
        (r'^package\s+[\w\.]+;', 'java'),

        # C/C++
        (r'^#include\s*[<"]', 'cpp'),
        (r'^int\s+main\s*\(', 'c'),

        # SQL
        (r'^(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER)\s', 'sql'),

        # Shell
        (r'^(if|for|while|case)\s+.*;\s*(then|do)', 'bash'),
        (r'^\w+=.*\n.*\$\w+', 'bash'),
    ]

    # Common language IDs that GtkSourceView supports
    SUPPORTED_LANGUAGES: List[str] = [
        'python', 'python3',
        'javascript', 'js',
        'typescript',
        'html',
        'css',
        'markdown',
        'latex',
        'bash', 'sh',
        'sql',
        'json',
        'yaml',
        'xml',
        'rust',
        'go',
        'java',
        'c', 'cpp',
        'ruby',
        'php',
        'perl',
        'lua',
        'r',
        'swift',
        'kotlin',
        'scala',
        'groovy',
        'objc',
        'ini',
        'toml',
        'rst',
        'diff',
        'makefile',
        'cmake',
        'dockerfile',
    ]

    def __init__(self):
        """Initialize the language manager"""
        self._gtk_manager = GtkSource.LanguageManager.get_default()
        self._language_cache: Dict[str, Optional[GtkSource.Language]] = {}

        # Build reverse lookup for language IDs
        self._available_languages: Optional[List[str]] = None

    @property
    def gtk_manager(self) -> GtkSource.LanguageManager:
        """Get the underlying GtkSourceView LanguageManager"""
        return self._gtk_manager

    def detect_language(self, filename: Optional[str] = None,
                        content: Optional[str] = None) -> Optional[str]:
        """
        Detect the language from filename and/or content.

        Args:
            filename: The filename (with extension) to check
            content: The file content to analyze

        Returns:
            Language ID string, or None if detection fails
        """
        # Try filename first (most reliable)
        if filename:
            lang_id = self._detect_from_filename(filename)
            if lang_id:
                return lang_id

        # Fall back to content analysis
        if content:
            lang_id = self._detect_from_content(content)
            if lang_id:
                return lang_id

        return None

    def _detect_from_filename(self, filename: str) -> Optional[str]:
        """Detect language from filename extension"""
        path = Path(filename)

        # Check for special filenames
        name_lower = path.name.lower()
        special_files = {
            'makefile': 'makefile',
            'gnumakefile': 'makefile',
            'dockerfile': 'dockerfile',
            'cmakelists.txt': 'cmake',
            'requirements.txt': 'text',
            'pipfile': 'toml',
            'cargo.toml': 'toml',
            'package.json': 'json',
            'tsconfig.json': 'json',
            '.gitignore': 'sh',
            '.bashrc': 'bash',
            '.zshrc': 'bash',
            '.profile': 'bash',
        }

        if name_lower in special_files:
            return special_files[name_lower]

        # Check extension
        ext = path.suffix.lower()
        if ext in self.EXTENSION_MAP:
            return self.EXTENSION_MAP[ext]

        # Check compound extensions
        if len(path.suffixes) >= 2:
            compound = ''.join(path.suffixes[-2:]).lower()
            compound_map = {
                '.spec.ts': 'typescript',
                '.spec.js': 'javascript',
                '.test.ts': 'typescript',
                '.test.js': 'javascript',
                '.d.ts': 'typescript',
            }
            if compound in compound_map:
                return compound_map[compound]

        return None

    def _detect_from_content(self, content: str) -> Optional[str]:
        """Detect language from file content"""
        if not content or not content.strip():
            return None

        # Check first few lines for patterns
        lines = content[:2000]  # Only check beginning for performance

        for pattern, lang_id in self.CONTENT_PATTERNS:
            if re.search(pattern, lines, re.MULTILINE | re.IGNORECASE):
                return lang_id

        return None

    def get_language(self, lang_id: str) -> Optional[GtkSource.Language]:
        """
        Get a GtkSourceLanguage by ID.

        Args:
            lang_id: The language identifier (e.g., 'python', 'javascript')

        Returns:
            GtkSourceLanguage instance, or None if not found
        """
        # Check cache
        if lang_id in self._language_cache:
            return self._language_cache[lang_id]

        # Try direct lookup
        language = self._gtk_manager.get_language(lang_id)

        # Try aliases
        if not language:
            aliases = {
                'js': 'javascript',
                'ts': 'typescript',
                'py': 'python',
                'python3': 'python',
                'sh': 'bash',
                'shell': 'bash',
                'zsh': 'bash',
                'yml': 'yaml',
                'md': 'markdown',
                'tex': 'latex',
                'c++': 'cpp',
                'objective-c': 'objc',
                'objective-c++': 'objc',
            }
            if lang_id.lower() in aliases:
                language = self._gtk_manager.get_language(aliases[lang_id.lower()])

        # Cache result
        self._language_cache[lang_id] = language
        return language

    def get_supported_languages(self) -> List[str]:
        """
        Get a list of all available language IDs.

        Returns:
            List of language ID strings
        """
        if self._available_languages is None:
            self._available_languages = list(self._gtk_manager.get_language_ids() or [])
        return self._available_languages.copy()

    def get_language_info(self, lang_id: str) -> Optional[Dict]:
        """
        Get detailed information about a language.

        Args:
            lang_id: The language identifier

        Returns:
            Dictionary with language info, or None if not found
        """
        language = self.get_language(lang_id)
        if not language:
            return None

        return {
            'id': language.get_id(),
            'name': language.get_name(),
            'section': language.get_section(),
            'hidden': language.get_hidden(),
            'mime_types': list(language.get_mime_types() or []),
            'globs': list(language.get_globs() or []),
            'metadata': {
                key: language.get_metadata(key)
                for key in ['line-comment-start', 'block-comment-start',
                           'block-comment-end']
                if language.get_metadata(key)
            }
        }

    def get_languages_by_section(self) -> Dict[str, List[str]]:
        """
        Get languages organized by section (category).

        Returns:
            Dictionary mapping section names to lists of language IDs
        """
        sections: Dict[str, List[str]] = {}

        for lang_id in self.get_supported_languages():
            language = self.get_language(lang_id)
            if language and not language.get_hidden():
                section = language.get_section() or 'Other'
                if section not in sections:
                    sections[section] = []
                sections[section].append(lang_id)

        # Sort each section
        for section in sections:
            sections[section].sort()

        return sections

    def guess_language_for_snippet(self, code: str) -> Optional[str]:
        """
        Guess the language of a code snippet.

        Useful for detecting language in code blocks or pasted content.

        Args:
            code: The code snippet to analyze

        Returns:
            Best guess language ID, or None
        """
        return self._detect_from_content(code)

    def get_comment_syntax(self, lang_id: str) -> Optional[Dict[str, str]]:
        """
        Get comment syntax for a language.

        Args:
            lang_id: The language identifier

        Returns:
            Dictionary with 'line' and/or 'block_start'/'block_end' keys
        """
        language = self.get_language(lang_id)
        if not language:
            return None

        result = {}

        line_comment = language.get_metadata('line-comment-start')
        if line_comment:
            result['line'] = line_comment

        block_start = language.get_metadata('block-comment-start')
        block_end = language.get_metadata('block-comment-end')
        if block_start and block_end:
            result['block_start'] = block_start
            result['block_end'] = block_end

        return result if result else None

    def is_language_available(self, lang_id: str) -> bool:
        """
        Check if a language is available.

        Args:
            lang_id: The language identifier

        Returns:
            True if the language is available
        """
        return self.get_language(lang_id) is not None

    def apply_language_to_buffer(self, buffer: GtkSource.Buffer,
                                  lang_id: Optional[str] = None,
                                  filename: Optional[str] = None,
                                  content: Optional[str] = None) -> Optional[str]:
        """
        Apply syntax highlighting to a buffer.

        Can use an explicit language ID or auto-detect from filename/content.

        Args:
            buffer: The GtkSourceBuffer to configure
            lang_id: Explicit language ID (optional)
            filename: Filename for auto-detection (optional)
            content: Content for auto-detection (optional)

        Returns:
            The applied language ID, or None if no highlighting applied
        """
        # Determine language
        if not lang_id:
            lang_id = self.detect_language(filename, content)

        if lang_id:
            language = self.get_language(lang_id)
            if language:
                buffer.set_language(language)
                buffer.set_highlight_syntax(True)
                return lang_id

        # No language found - disable highlighting
        buffer.set_language(None)
        buffer.set_highlight_syntax(False)
        return None

    def get_file_patterns_for_language(self, lang_id: str) -> List[str]:
        """
        Get file patterns (globs) that match a language.

        Args:
            lang_id: The language identifier

        Returns:
            List of glob patterns (e.g., ['*.py', '*.pyw'])
        """
        language = self.get_language(lang_id)
        if not language:
            return []

        globs = language.get_globs()
        return list(globs) if globs else []

    def clear_cache(self):
        """Clear the language lookup cache"""
        self._language_cache.clear()
        self._available_languages = None


# Singleton instance
_default_manager: Optional[LanguageManager] = None


def get_default() -> LanguageManager:
    """
    Get the default LanguageManager instance.

    Returns:
        The shared LanguageManager instance
    """
    global _default_manager
    if _default_manager is None:
        _default_manager = LanguageManager()
    return _default_manager
