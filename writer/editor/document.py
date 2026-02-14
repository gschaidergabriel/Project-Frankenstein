"""
Document Model for Frank Writer
"""

import hashlib
import re
import threading
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import yaml


@dataclass
class DocumentSection:
    """A section within a document"""
    name: str
    title: str
    content: str = ""
    level: int = 1
    start_line: int = 0
    end_line: int = 0


@dataclass
class Document:
    """Represents a document in the editor"""

    # Content
    content: str = ""

    # Metadata
    title: str = "Untitled"
    schema_type: Optional[str] = None
    language: Optional[str] = None
    file_path: Optional[Path] = None

    # State
    is_modified: bool = False
    created_at: datetime = field(default_factory=datetime.now)
    modified_at: datetime = field(default_factory=datetime.now)

    # Schema structure
    sections: List[DocumentSection] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Tracking
    _original_content: str = ""
    _content_hash: str = ""
    _word_count_cache: Optional[int] = None
    _word_count_hash: str = ""
    _content_lock: threading.Lock = field(default_factory=threading.Lock)
    _structure_dirty: bool = False
    _structure_hash: str = ""

    def __post_init__(self):
        self._original_content = self.content
        self._update_hash()
        self._detect_language()

    @classmethod
    def from_file(cls, path: Path) -> 'Document':
        """Load document from file"""
        path = Path(path)

        # Try multiple encodings for robustness
        content = None
        encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']
        for encoding in encodings:
            try:
                content = path.read_text(encoding=encoding)
                break
            except UnicodeDecodeError:
                continue

        if content is None:
            # Last resort: read with errors ignored
            content = path.read_text(encoding='utf-8', errors='replace')

        doc = cls(
            content=content,
            title=path.stem,
            file_path=path
        )
        doc._original_content = content
        doc.is_modified = False
        doc._detect_language()
        doc._parse_structure()

        return doc

    @classmethod
    def from_schema(cls, schema_path: Path) -> 'Document':
        """Create document from schema template"""
        try:
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema = yaml.safe_load(f)
        except (IOError, OSError) as e:
            raise ValueError(f"Failed to read schema file: {e}")
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in schema file: {e}")

        # Handle null/empty schema
        if schema is None:
            schema = {}

        doc = cls(
            title=f"New {schema.get('schema', {}).get('name', 'Document')}",
            schema_type=schema.get('schema', {}).get('name'),
            metadata=schema.get('metadata', {}) or {}
        )

        # Generate initial content from schema
        content_lines = []
        for section in schema.get('structure', []):
            section_name = section.get('section', '')
            if section_name:
                level = section.get('level', 1)
                prefix = '#' * level
                content_lines.append(f"{prefix} {section_name.title()}")
                content_lines.append("")
                content_lines.append(f"<!-- {section.get('ai_help', '')} -->")
                content_lines.append("")

        doc.content = '\n'.join(content_lines)
        doc._original_content = ""
        doc.is_modified = True

        return doc

    def save(self, path: Path = None):
        """Save document to file"""
        if path:
            self.file_path = path
            self.title = path.stem

        if not self.file_path:
            raise ValueError("No file path specified")

        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.write_text(self.content, encoding='utf-8')

        self._original_content = self.content
        self.is_modified = False
        self.modified_at = datetime.now()
        self._update_hash()

    def set_content(self, content: str):
        """Set document content with thread safety.

        Structure parsing is deferred (lazy) to avoid O(n) work on every
        keystroke.  Call get_outline() or get_section_at_line() to trigger
        a reparse when actually needed.
        """
        with self._content_lock:
            self.content = content
            self.is_modified = content != self._original_content
            self.modified_at = datetime.now()
            self._update_hash()
            # Mark structure as dirty — reparse lazily on next access
            self._structure_dirty = True

    def get_content(self) -> str:
        """Get document content"""
        return self.content

    @property
    def word_count(self) -> int:
        """Count words in document (cached for performance)"""
        # Return cached value if content hasn't changed
        if self._word_count_cache is not None and self._word_count_hash == self._content_hash:
            return self._word_count_cache

        # Compute word count
        text = re.sub(r'[^\w\s]', '', self.content)
        words = text.split()
        count = len(words)

        # Cache the result
        self._word_count_cache = count
        self._word_count_hash = self._content_hash
        return count

    @property
    def line_count(self) -> int:
        """Count lines in document"""
        return len(self.content.splitlines())

    @property
    def char_count(self) -> int:
        """Count characters in document"""
        return len(self.content)

    @property
    def content_hash(self) -> str:
        """Get content hash"""
        return self._content_hash

    def _update_hash(self):
        """Update content hash"""
        self._content_hash = hashlib.sha256(
            self.content.encode('utf-8')
        ).hexdigest()[:16]

    def _detect_language(self):
        """Detect document language/type"""
        if self.file_path:
            ext = self.file_path.suffix.lower()
            language_map = {
                '.py': 'python',
                '.js': 'javascript',
                '.ts': 'typescript',
                '.html': 'html',
                '.css': 'css',
                '.json': 'json',
                '.yaml': 'yaml',
                '.yml': 'yaml',
                '.md': 'markdown',
                '.tex': 'latex',
                '.sh': 'bash',
                '.bash': 'bash',
                '.sql': 'sql',
                '.rs': 'rust',
                '.go': 'go',
                '.java': 'java',
                '.cpp': 'cpp',
                '.c': 'c',
                '.h': 'c',
                '.hpp': 'cpp',
                '.rb': 'ruby',
                '.php': 'php',
                '.xml': 'xml',
                '.toml': 'toml',
            }
            self.language = language_map.get(ext, 'text')
        elif not self.language:
            # Try to detect from content
            if self.content.startswith('#!/usr/bin/env python') or \
               self.content.startswith('#!/usr/bin/python'):
                self.language = 'python'
            elif self.content.startswith('#!/bin/bash') or \
                 self.content.startswith('#!/bin/sh'):
                self.language = 'bash'
            elif self.content.strip().startswith('<!DOCTYPE html') or \
                 self.content.strip().startswith('<html'):
                self.language = 'html'
            elif self.content.strip().startswith('{'):
                self.language = 'json'
            else:
                self.language = 'text'

    def _parse_structure(self):
        """Parse document structure (headings, sections)"""
        self.sections = []
        lines = self.content.splitlines()
        current_section = None

        for i, line in enumerate(lines):
            # Markdown headings
            if line.startswith('#'):
                level = len(line) - len(line.lstrip('#'))
                title = line.lstrip('#').strip()

                if current_section:
                    current_section.end_line = i - 1

                current_section = DocumentSection(
                    name=title.lower().replace(' ', '_'),
                    title=title,
                    level=level,
                    start_line=i
                )
                self.sections.append(current_section)

        if current_section:
            current_section.end_line = len(lines) - 1

    def _ensure_structure(self):
        """Reparse structure if dirty (lazy evaluation)."""
        if self._structure_dirty:
            self._parse_structure()
            self._structure_dirty = False

    def get_section_at_line(self, line: int) -> Optional[DocumentSection]:
        """Get section at specified line with boundary validation"""
        self._ensure_structure()
        # Validate line number
        if line < 0:
            return None

        line_count = self.line_count
        if line >= line_count:
            line = line_count - 1 if line_count > 0 else 0

        for section in self.sections:
            # Validate section boundaries
            start = max(0, section.start_line)
            end = min(line_count - 1, section.end_line) if line_count > 0 else 0
            if start <= line <= end:
                return section
        return None

    def get_outline(self) -> List[Dict]:
        """Get document outline for sidebar"""
        self._ensure_structure()
        return [
            {
                'name': s.name,
                'title': s.title,
                'level': s.level,
                'line': s.start_line
            }
            for s in self.sections
        ]

    def to_context(self) -> Dict[str, Any]:
        """Convert to context dict for AI"""
        return {
            'title': self.title,
            'schema_type': self.schema_type,
            'language': self.language,
            'word_count': self.word_count,
            'line_count': self.line_count,
            'is_modified': self.is_modified,
            'sections': [
                {
                    'name': s.name,
                    'title': s.title,
                    'level': s.level
                }
                for s in self.sections
            ],
            'metadata': self.metadata
        }
