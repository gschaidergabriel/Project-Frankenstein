"""
LaTeX Parser for document ingestion
Parses LaTeX content including sections, equations, figures, and citations
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum, auto

logger = logging.getLogger(__name__)

# Try to import TexSoup for enhanced parsing
try:
    from TexSoup import TexSoup
    TEXSOUP_AVAILABLE = True
except ImportError:
    TexSoup = None
    TEXSOUP_AVAILABLE = False
    logger.debug("TexSoup not available, using regex fallback")


class LatexNodeType(Enum):
    """Types of LaTeX nodes"""
    DOCUMENT = auto()
    SECTION = auto()
    SUBSECTION = auto()
    SUBSUBSECTION = auto()
    PARAGRAPH = auto()
    EQUATION = auto()
    EQUATION_INLINE = auto()
    FIGURE = auto()
    TABLE = auto()
    LISTING = auto()
    ITEMIZE = auto()
    ENUMERATE = auto()
    ITEM = auto()
    CITATION = auto()
    REFERENCE = auto()
    LABEL = auto()
    CAPTION = auto()
    ABSTRACT = auto()
    TITLE = auto()
    AUTHOR = auto()
    ENVIRONMENT = auto()
    COMMAND = auto()
    TEXT = auto()


@dataclass
class LatexNode:
    """Represents a node in the LaTeX AST"""
    type: LatexNodeType
    content: str = ""
    children: List['LatexNode'] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)
    start_line: int = 0
    end_line: int = 0


@dataclass
class Section:
    """Represents a LaTeX section"""
    level: int  # 1=section, 2=subsection, 3=subsubsection
    title: str
    content: str = ""
    label: str = ""
    start_line: int = 0
    end_line: int = 0
    numbered: bool = True


@dataclass
class Equation:
    """Represents an equation"""
    latex: str
    label: str = ""
    inline: bool = False
    environment: str = ""  # equation, align, gather, etc.
    start_line: int = 0
    end_line: int = 0


@dataclass
class Figure:
    """Represents a figure"""
    path: str
    caption: str = ""
    label: str = ""
    position: str = ""  # h, t, b, p, H, etc.
    width: str = ""
    start_line: int = 0
    end_line: int = 0


@dataclass
class Table:
    """Represents a table"""
    content: str
    caption: str = ""
    label: str = ""
    columns: str = ""  # Column specification
    rows: List[List[str]] = field(default_factory=list)
    start_line: int = 0
    end_line: int = 0


@dataclass
class Citation:
    """Represents a citation"""
    key: str
    type: str = "cite"  # cite, citep, citet, etc.
    prefix: str = ""
    suffix: str = ""
    line: int = 0


@dataclass
class BibEntry:
    """Represents a BibTeX entry"""
    key: str
    entry_type: str  # article, book, inproceedings, etc.
    fields: Dict[str, str] = field(default_factory=dict)


@dataclass
class LatexDocument:
    """Represents a parsed LaTeX document"""
    # Raw content
    raw_content: str = ""

    # Document metadata
    document_class: str = ""
    packages: List[str] = field(default_factory=list)
    title: str = ""
    author: str = ""
    date: str = ""
    abstract: str = ""

    # Parsed elements
    sections: List[Section] = field(default_factory=list)
    equations: List[Equation] = field(default_factory=list)
    figures: List[Figure] = field(default_factory=list)
    tables: List[Table] = field(default_factory=list)
    citations: List[Citation] = field(default_factory=list)

    # References
    labels: Dict[str, str] = field(default_factory=dict)
    bibliography: List[BibEntry] = field(default_factory=list)

    # Document structure
    root: Optional[LatexNode] = None
    preamble: str = ""
    body: str = ""

    def get_outline(self) -> List[Dict[str, Any]]:
        """Get document outline from sections"""
        return [
            {
                'level': s.level,
                'title': s.title,
                'label': s.label,
                'line': s.start_line,
                'numbered': s.numbered
            }
            for s in self.sections
        ]

    def get_text(self) -> str:
        """Get plain text content (without LaTeX commands)"""
        return self._strip_latex(self.body)

    def _strip_latex(self, content: str) -> str:
        """Remove LaTeX commands and return plain text"""
        text = content
        # Remove comments
        text = re.sub(r'%.*$', '', text, flags=re.MULTILINE)
        # Remove commands
        text = re.sub(r'\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^}]*\})*', ' ', text)
        # Remove environments
        text = re.sub(r'\\begin\{[^}]+\}.*?\\end\{[^}]+\}', '', text, flags=re.DOTALL)
        # Remove braces
        text = re.sub(r'[{}]', '', text)
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text)
        return text.strip()


class LatexParser:
    """
    LaTeX parser with support for common document structures

    Uses TexSoup for parsing when available, with regex fallback
    """

    # Section command mapping
    SECTION_COMMANDS = {
        'chapter': 0,
        'section': 1,
        'subsection': 2,
        'subsubsection': 3,
        'paragraph': 4,
        'subparagraph': 5,
    }

    # Math environments
    MATH_ENVIRONMENTS = [
        'equation', 'equation*',
        'align', 'align*',
        'gather', 'gather*',
        'multline', 'multline*',
        'eqnarray', 'eqnarray*',
        'displaymath',
        'math',
    ]

    def __init__(self):
        """Initialize parser"""
        self._use_texsoup = TEXSOUP_AVAILABLE

    def parse(self, content: str) -> LatexDocument:
        """
        Parse LaTeX content

        Args:
            content: LaTeX content string

        Returns:
            LatexDocument with parsed elements
        """
        doc = LatexDocument(raw_content=content)

        if not content:
            return doc

        # Split preamble and body
        doc.preamble, doc.body = self._split_document(content)

        # Parse preamble
        doc.document_class = self._extract_document_class(doc.preamble)
        doc.packages = self._extract_packages(doc.preamble)
        doc.title = self._extract_title(content)
        doc.author = self._extract_author(content)
        doc.date = self._extract_date(content)

        # Parse body
        doc.abstract = self._extract_abstract(doc.body)
        doc.sections = self._extract_sections(content)
        doc.equations = self._extract_equations(content)
        doc.figures = self._extract_figures(content)
        doc.tables = self._extract_tables(content)
        doc.citations = self._extract_citations(content)
        doc.labels = self._extract_labels(content)

        # Build AST
        doc.root = self._build_ast(content)

        return doc

    def parse_bibtex(self, content: str) -> List[BibEntry]:
        """
        Parse BibTeX content

        Args:
            content: BibTeX content string

        Returns:
            List of BibEntry objects
        """
        return self._extract_bibtex_entries(content)

    def extract_sections(self, content: str) -> List[Section]:
        """Extract all sections from content"""
        return self._extract_sections(content)

    def extract_equations(self, content: str) -> List[Equation]:
        """Extract all equations from content"""
        return self._extract_equations(content)

    def to_document(self, latex_doc: LatexDocument) -> Dict[str, Any]:
        """
        Convert LatexDocument to internal Document structure

        Args:
            latex_doc: Parsed LatexDocument

        Returns:
            Dictionary compatible with Document model
        """
        sections = []
        for section in latex_doc.sections:
            sections.append({
                'name': section.label or self._slugify(section.title),
                'title': section.title,
                'level': section.level,
                'start_line': section.start_line,
            })

        return {
            'content': latex_doc.raw_content,
            'title': latex_doc.title or "Untitled",
            'language': 'latex',
            'sections': sections,
            'metadata': {
                'author': latex_doc.author,
                'date': latex_doc.date,
                'document_class': latex_doc.document_class,
                'packages': latex_doc.packages,
            },
        }

    def to_markdown(self, latex_doc: LatexDocument) -> str:
        """
        Convert LaTeX document to Markdown

        Args:
            latex_doc: Parsed LatexDocument

        Returns:
            Markdown string
        """
        md_parts = []

        # Title
        if latex_doc.title:
            md_parts.append(f"# {latex_doc.title}\n")

        # Author
        if latex_doc.author:
            md_parts.append(f"*{latex_doc.author}*\n")

        # Abstract
        if latex_doc.abstract:
            md_parts.append(f"## Abstract\n\n{latex_doc.abstract}\n")

        # Convert body
        body_md = self._latex_to_markdown(latex_doc.body)
        md_parts.append(body_md)

        return '\n'.join(md_parts)

    # --- Private parsing methods ---

    def _split_document(self, content: str) -> Tuple[str, str]:
        """Split document into preamble and body"""
        begin_match = re.search(r'\\begin\{document\}', content)
        end_match = re.search(r'\\end\{document\}', content)

        if begin_match:
            preamble = content[:begin_match.start()]
            if end_match:
                body = content[begin_match.end():end_match.start()]
            else:
                body = content[begin_match.end():]
        else:
            preamble = ""
            body = content

        return preamble.strip(), body.strip()

    def _extract_document_class(self, preamble: str) -> str:
        """Extract document class"""
        match = re.search(r'\\documentclass(?:\[[^\]]*\])?\{([^}]+)\}', preamble)
        return match.group(1) if match else ""

    def _extract_packages(self, preamble: str) -> List[str]:
        """Extract used packages"""
        packages = []
        for match in re.finditer(r'\\usepackage(?:\[[^\]]*\])?\{([^}]+)\}', preamble):
            # Handle multiple packages in one usepackage
            pkg_list = match.group(1).split(',')
            packages.extend([p.strip() for p in pkg_list])
        return packages

    def _extract_title(self, content: str) -> str:
        """Extract document title"""
        match = re.search(r'\\title\{([^}]+)\}', content)
        if match:
            return self._clean_text(match.group(1))
        return ""

    def _extract_author(self, content: str) -> str:
        """Extract document author"""
        match = re.search(r'\\author\{([^}]+)\}', content)
        if match:
            return self._clean_text(match.group(1))
        return ""

    def _extract_date(self, content: str) -> str:
        """Extract document date"""
        match = re.search(r'\\date\{([^}]+)\}', content)
        if match:
            date_text = match.group(1)
            if date_text == '\\today':
                return "today"
            return self._clean_text(date_text)
        return ""

    def _extract_abstract(self, body: str) -> str:
        """Extract abstract"""
        match = re.search(
            r'\\begin\{abstract\}(.*?)\\end\{abstract\}',
            body,
            re.DOTALL
        )
        if match:
            return self._clean_text(match.group(1))
        return ""

    def _extract_sections(self, content: str) -> List[Section]:
        """Extract all sections from content"""
        sections = []
        lines = content.split('\n')

        # Patterns for section commands
        section_pattern = r'\\(chapter|section|subsection|subsubsection|paragraph|subparagraph)\*?\{([^}]+)\}'

        current_section = None
        section_start_line = 0

        for i, line in enumerate(lines):
            match = re.search(section_pattern, line)
            if match:
                # Save previous section
                if current_section:
                    current_section.end_line = i - 1
                    current_section.content = '\n'.join(lines[section_start_line:i])
                    sections.append(current_section)

                cmd = match.group(1)
                title = self._clean_text(match.group(2))
                starred = '*' in line[match.start():match.end()]

                # Extract label if present
                label = ""
                label_match = re.search(r'\\label\{([^}]+)\}', line)
                if label_match:
                    label = label_match.group(1)

                current_section = Section(
                    level=self.SECTION_COMMANDS.get(cmd, 1),
                    title=title,
                    label=label,
                    start_line=i,
                    numbered=not starred
                )
                section_start_line = i + 1

        # Add last section
        if current_section:
            current_section.end_line = len(lines) - 1
            current_section.content = '\n'.join(lines[section_start_line:])
            sections.append(current_section)

        return sections

    def _extract_equations(self, content: str) -> List[Equation]:
        """Extract all equations from content"""
        equations = []
        lines = content.split('\n')

        # Inline math: $...$
        for i, line in enumerate(lines):
            for match in re.finditer(r'(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)', line):
                equations.append(Equation(
                    latex=match.group(1),
                    inline=True,
                    start_line=i,
                    end_line=i
                ))

        # Display math: $$...$$
        content_str = content
        for match in re.finditer(r'\$\$(.+?)\$\$', content_str, re.DOTALL):
            latex = match.group(1).strip()
            start = content[:match.start()].count('\n')
            end = content[:match.end()].count('\n')
            equations.append(Equation(
                latex=latex,
                inline=False,
                start_line=start,
                end_line=end
            ))

        # Math environments
        for env in self.MATH_ENVIRONMENTS:
            pattern = rf'\\begin\{{{env}\}}(.*?)\\end\{{{env}\}}'
            for match in re.finditer(pattern, content, re.DOTALL):
                latex = match.group(1).strip()
                start = content[:match.start()].count('\n')
                end = content[:match.end()].count('\n')

                # Extract label
                label = ""
                label_match = re.search(r'\\label\{([^}]+)\}', latex)
                if label_match:
                    label = label_match.group(1)
                    latex = re.sub(r'\\label\{[^}]+\}', '', latex).strip()

                equations.append(Equation(
                    latex=latex,
                    label=label,
                    inline=False,
                    environment=env,
                    start_line=start,
                    end_line=end
                ))

        return equations

    def _extract_figures(self, content: str) -> List[Figure]:
        """Extract all figures from content"""
        figures = []

        pattern = r'\\begin\{figure\}(?:\[([^\]]*)\])?(.*?)\\end\{figure\}'
        for match in re.finditer(pattern, content, re.DOTALL):
            position = match.group(1) or ""
            figure_content = match.group(2)

            start = content[:match.start()].count('\n')
            end = content[:match.end()].count('\n')

            # Extract includegraphics
            path = ""
            width = ""
            include_match = re.search(
                r'\\includegraphics(?:\[([^\]]*)\])?\{([^}]+)\}',
                figure_content
            )
            if include_match:
                options = include_match.group(1) or ""
                path = include_match.group(2)
                # Parse width from options
                width_match = re.search(r'width=([^,\]]+)', options)
                if width_match:
                    width = width_match.group(1)

            # Extract caption
            caption = ""
            caption_match = re.search(r'\\caption\{([^}]+)\}', figure_content)
            if caption_match:
                caption = self._clean_text(caption_match.group(1))

            # Extract label
            label = ""
            label_match = re.search(r'\\label\{([^}]+)\}', figure_content)
            if label_match:
                label = label_match.group(1)

            figures.append(Figure(
                path=path,
                caption=caption,
                label=label,
                position=position,
                width=width,
                start_line=start,
                end_line=end
            ))

        return figures

    def _extract_tables(self, content: str) -> List[Table]:
        """Extract all tables from content"""
        tables = []

        pattern = r'\\begin\{table\}(?:\[([^\]]*)\])?(.*?)\\end\{table\}'
        for match in re.finditer(pattern, content, re.DOTALL):
            table_content = match.group(2)

            start = content[:match.start()].count('\n')
            end = content[:match.end()].count('\n')

            # Extract tabular
            columns = ""
            rows = []
            tabular_match = re.search(
                r'\\begin\{tabular\}\{([^}]+)\}(.*?)\\end\{tabular\}',
                table_content,
                re.DOTALL
            )
            if tabular_match:
                columns = tabular_match.group(1)
                tabular_content = tabular_match.group(2)

                # Parse rows
                for row in tabular_content.split('\\\\'):
                    row = row.strip()
                    if row and not row.startswith('\\hline'):
                        cells = [c.strip() for c in row.split('&')]
                        rows.append(cells)

            # Extract caption
            caption = ""
            caption_match = re.search(r'\\caption\{([^}]+)\}', table_content)
            if caption_match:
                caption = self._clean_text(caption_match.group(1))

            # Extract label
            label = ""
            label_match = re.search(r'\\label\{([^}]+)\}', table_content)
            if label_match:
                label = label_match.group(1)

            tables.append(Table(
                content=table_content,
                caption=caption,
                label=label,
                columns=columns,
                rows=rows,
                start_line=start,
                end_line=end
            ))

        return tables

    def _extract_citations(self, content: str) -> List[Citation]:
        """Extract all citations from content"""
        citations = []
        lines = content.split('\n')

        cite_patterns = [
            (r'\\cite(?:p|t|author|year|alp|alt)?\{([^}]+)\}', 'cite'),
            (r'\\citep\{([^}]+)\}', 'citep'),
            (r'\\citet\{([^}]+)\}', 'citet'),
            (r'\\citeauthor\{([^}]+)\}', 'citeauthor'),
            (r'\\citeyear\{([^}]+)\}', 'citeyear'),
        ]

        for i, line in enumerate(lines):
            for pattern, cite_type in cite_patterns:
                for match in re.finditer(pattern, line):
                    keys = match.group(1).split(',')
                    for key in keys:
                        citations.append(Citation(
                            key=key.strip(),
                            type=cite_type,
                            line=i
                        ))

        return citations

    def _extract_labels(self, content: str) -> Dict[str, str]:
        """Extract all labels and their types"""
        labels = {}

        # Find labels with context
        for match in re.finditer(r'\\label\{([^}]+)\}', content):
            label = match.group(1)
            # Determine type from context
            context_start = max(0, match.start() - 100)
            context = content[context_start:match.start()]

            if '\\begin{figure}' in context:
                labels[label] = 'figure'
            elif '\\begin{table}' in context:
                labels[label] = 'table'
            elif '\\begin{equation}' in context or '$' in context:
                labels[label] = 'equation'
            elif re.search(r'\\(sub)*section', context):
                labels[label] = 'section'
            else:
                labels[label] = 'unknown'

        return labels

    def _extract_bibtex_entries(self, content: str) -> List[BibEntry]:
        """Parse BibTeX content"""
        entries = []

        # Match @type{key, ... }
        pattern = r'@(\w+)\s*\{\s*([^,]+)\s*,([^@]*)\}'
        for match in re.finditer(pattern, content, re.DOTALL):
            entry_type = match.group(1).lower()
            key = match.group(2).strip()
            fields_str = match.group(3)

            fields = {}
            # Parse fields: name = {value} or name = "value"
            field_pattern = r'(\w+)\s*=\s*[{"]([^}"]*)[}"]'
            for field_match in re.finditer(field_pattern, fields_str):
                field_name = field_match.group(1).lower()
                field_value = field_match.group(2)
                fields[field_name] = field_value

            entries.append(BibEntry(
                key=key,
                entry_type=entry_type,
                fields=fields
            ))

        return entries

    def _build_ast(self, content: str) -> LatexNode:
        """Build abstract syntax tree from content"""
        root = LatexNode(type=LatexNodeType.DOCUMENT)

        # Use TexSoup if available
        if self._use_texsoup:
            try:
                soup = TexSoup(content)
                root = self._texsoup_to_ast(soup)
                return root
            except Exception as e:
                logger.warning(f"TexSoup parsing failed: {e}")

        # Fallback: basic AST from sections
        for section in self._extract_sections(content):
            node = LatexNode(
                type=LatexNodeType.SECTION,
                content=section.title,
                start_line=section.start_line,
                end_line=section.end_line,
                attributes={
                    'level': section.level,
                    'label': section.label,
                    'numbered': section.numbered
                }
            )
            root.children.append(node)

        return root

    def _texsoup_to_ast(self, soup) -> LatexNode:
        """Convert TexSoup tree to AST"""
        root = LatexNode(type=LatexNodeType.DOCUMENT)

        def process_node(tex_node, parent):
            if hasattr(tex_node, 'name'):
                name = tex_node.name
                # Map to node type
                if name in self.SECTION_COMMANDS:
                    node_type = LatexNodeType.SECTION
                elif name in ['equation', 'align', 'gather']:
                    node_type = LatexNodeType.EQUATION
                elif name == 'figure':
                    node_type = LatexNodeType.FIGURE
                elif name == 'table':
                    node_type = LatexNodeType.TABLE
                else:
                    node_type = LatexNodeType.COMMAND

                node = LatexNode(
                    type=node_type,
                    content=str(tex_node.string) if hasattr(tex_node, 'string') else "",
                    attributes={'name': name}
                )
                parent.children.append(node)

                # Process children
                if hasattr(tex_node, 'contents'):
                    for child in tex_node.contents:
                        process_node(child, node)
            elif isinstance(tex_node, str):
                if tex_node.strip():
                    parent.children.append(LatexNode(
                        type=LatexNodeType.TEXT,
                        content=tex_node
                    ))

        if hasattr(soup, 'contents'):
            for child in soup.contents:
                process_node(child, root)

        return root

    def _clean_text(self, text: str) -> str:
        """Clean LaTeX text by removing simple commands"""
        # Remove common formatting commands
        text = re.sub(r'\\textbf\{([^}]+)\}', r'\1', text)
        text = re.sub(r'\\textit\{([^}]+)\}', r'\1', text)
        text = re.sub(r'\\emph\{([^}]+)\}', r'\1', text)
        text = re.sub(r'\\underline\{([^}]+)\}', r'\1', text)
        # Remove line breaks
        text = text.replace('\\\\', ' ')
        text = text.replace('\n', ' ')
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def _slugify(self, text: str) -> str:
        """Convert text to URL-safe slug"""
        slug = text.lower()
        slug = re.sub(r'[^\w\s-]', '', slug)
        slug = re.sub(r'[\s_]+', '-', slug)
        slug = slug.strip('-')
        return slug

    def _latex_to_markdown(self, latex: str) -> str:
        """Convert LaTeX body to Markdown"""
        md = latex

        # Section commands
        md = re.sub(r'\\section\*?\{([^}]+)\}', r'\n## \1\n', md)
        md = re.sub(r'\\subsection\*?\{([^}]+)\}', r'\n### \1\n', md)
        md = re.sub(r'\\subsubsection\*?\{([^}]+)\}', r'\n#### \1\n', md)

        # Text formatting
        md = re.sub(r'\\textbf\{([^}]+)\}', r'**\1**', md)
        md = re.sub(r'\\textit\{([^}]+)\}', r'*\1*', md)
        md = re.sub(r'\\emph\{([^}]+)\}', r'*\1*', md)
        md = re.sub(r'\\underline\{([^}]+)\}', r'_\1_', md)

        # Lists
        md = re.sub(r'\\begin\{itemize\}', '', md)
        md = re.sub(r'\\end\{itemize\}', '', md)
        md = re.sub(r'\\begin\{enumerate\}', '', md)
        md = re.sub(r'\\end\{enumerate\}', '', md)
        md = re.sub(r'\\item\s+', '- ', md)

        # Math
        md = re.sub(r'\$\$([^$]+)\$\$', r'\n$$\1$$\n', md)

        # Remove other commands
        md = re.sub(r'\\[a-zA-Z]+\{[^}]*\}', '', md)
        md = re.sub(r'\\[a-zA-Z]+', '', md)

        # Clean up
        md = re.sub(r'\n{3,}', '\n\n', md)

        return md.strip()


def parse_latex(content: str) -> LatexDocument:
    """Convenience function for parsing LaTeX"""
    parser = LatexParser()
    return parser.parse(content)


def parse_bibtex(content: str) -> List[BibEntry]:
    """Convenience function for parsing BibTeX"""
    parser = LatexParser()
    return parser.parse_bibtex(content)
