"""
Markdown Parser for document ingestion
Parses Markdown content including GitHub Flavored Markdown
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum, auto

logger = logging.getLogger(__name__)

# Try to import cmarkgfm for GFM support
try:
    import cmarkgfm
    from cmarkgfm import cmark
    CMARKGFM_AVAILABLE = True
except ImportError:
    cmarkgfm = None
    CMARKGFM_AVAILABLE = False
    logger.debug("cmarkgfm not available, using regex fallback")


class MarkdownNodeType(Enum):
    """Types of Markdown nodes"""
    DOCUMENT = auto()
    HEADING = auto()
    PARAGRAPH = auto()
    CODE_BLOCK = auto()
    INLINE_CODE = auto()
    BLOCKQUOTE = auto()
    LIST = auto()
    LIST_ITEM = auto()
    LINK = auto()
    IMAGE = auto()
    EMPHASIS = auto()
    STRONG = auto()
    HORIZONTAL_RULE = auto()
    TABLE = auto()
    TABLE_ROW = auto()
    TABLE_CELL = auto()
    TEXT = auto()
    HTML_BLOCK = auto()
    TASK_LIST_ITEM = auto()
    FOOTNOTE = auto()


@dataclass
class MarkdownNode:
    """Represents a node in the Markdown AST"""
    type: MarkdownNodeType
    content: str = ""
    children: List['MarkdownNode'] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)
    start_line: int = 0
    end_line: int = 0


@dataclass
class Heading:
    """Represents a Markdown heading"""
    level: int
    text: str
    line: int
    anchor: str = ""


@dataclass
class CodeBlock:
    """Represents a code block"""
    language: str
    code: str
    start_line: int
    end_line: int
    info: str = ""  # Additional info string


@dataclass
class Link:
    """Represents a link"""
    text: str
    url: str
    title: str = ""
    line: int = 0


@dataclass
class Image:
    """Represents an image"""
    alt: str
    url: str
    title: str = ""
    line: int = 0


@dataclass
class MarkdownDocument:
    """Represents a parsed Markdown document"""
    # Raw content
    raw_content: str = ""

    # Parsed elements
    headings: List[Heading] = field(default_factory=list)
    paragraphs: List[str] = field(default_factory=list)
    code_blocks: List[CodeBlock] = field(default_factory=list)
    links: List[Link] = field(default_factory=list)
    images: List[Image] = field(default_factory=list)

    # Document structure
    root: Optional[MarkdownNode] = None
    frontmatter: Dict[str, Any] = field(default_factory=dict)

    # Metadata
    title: str = ""
    toc: List[Dict[str, Any]] = field(default_factory=list)

    # HTML output (if rendered)
    html: str = ""

    def get_outline(self) -> List[Dict[str, Any]]:
        """Get document outline from headings"""
        return [
            {
                'level': h.level,
                'text': h.text,
                'anchor': h.anchor,
                'line': h.line
            }
            for h in self.headings
        ]

    def get_text(self) -> str:
        """Get plain text content (paragraphs only)"""
        return '\n\n'.join(self.paragraphs)


class MarkdownParser:
    """
    Markdown parser with GitHub Flavored Markdown support

    Uses cmarkgfm for parsing when available, with regex fallback
    """

    def __init__(self, gfm: bool = True):
        """
        Initialize parser

        Args:
            gfm: Enable GitHub Flavored Markdown extensions
        """
        self.gfm = gfm
        self._use_cmark = CMARKGFM_AVAILABLE

    def parse(self, content: str) -> MarkdownDocument:
        """
        Parse Markdown content

        Args:
            content: Markdown content string

        Returns:
            MarkdownDocument with parsed elements
        """
        doc = MarkdownDocument(raw_content=content)

        if not content:
            return doc

        # Extract frontmatter first
        content, doc.frontmatter = self._extract_frontmatter(content)

        # Parse using cmarkgfm if available
        if self._use_cmark:
            doc.html = self._render_html(content)

        # Extract elements (works with or without cmark)
        doc.headings = self._extract_headings(content)
        doc.paragraphs = self._extract_paragraphs(content)
        doc.code_blocks = self._extract_code_blocks(content)
        doc.links = self._extract_links(content)
        doc.images = self._extract_images(content)

        # Build document structure
        doc.root = self._build_ast(content)

        # Set title from first H1
        if doc.headings:
            for h in doc.headings:
                if h.level == 1:
                    doc.title = h.text
                    break

        # Build TOC
        doc.toc = doc.get_outline()

        return doc

    def render_html(self, content: str) -> str:
        """
        Render Markdown to HTML

        Args:
            content: Markdown content

        Returns:
            HTML string
        """
        return self._render_html(content)

    def extract_headings(self, content: str) -> List[Heading]:
        """Extract all headings from content"""
        return self._extract_headings(content)

    def extract_code_blocks(self, content: str) -> List[CodeBlock]:
        """Extract all code blocks from content"""
        return self._extract_code_blocks(content)

    def to_document(self, md_doc: MarkdownDocument) -> Dict[str, Any]:
        """
        Convert MarkdownDocument to internal Document structure

        Args:
            md_doc: Parsed MarkdownDocument

        Returns:
            Dictionary compatible with Document model
        """
        sections = []
        for heading in md_doc.headings:
            sections.append({
                'name': self._slugify(heading.text),
                'title': heading.text,
                'level': heading.level,
                'start_line': heading.line,
            })

        return {
            'content': md_doc.raw_content,
            'title': md_doc.title or "Untitled",
            'language': 'markdown',
            'sections': sections,
            'metadata': md_doc.frontmatter,
        }

    # --- Private parsing methods ---

    def _extract_frontmatter(self, content: str) -> tuple:
        """Extract YAML frontmatter from content"""
        frontmatter = {}

        if content.startswith('---'):
            lines = content.split('\n')
            end_idx = None

            for i, line in enumerate(lines[1:], 1):
                if line.strip() == '---':
                    end_idx = i
                    break

            if end_idx:
                yaml_content = '\n'.join(lines[1:end_idx])
                try:
                    import yaml
                    frontmatter = yaml.safe_load(yaml_content) or {}
                except Exception as e:
                    logger.warning(f"Failed to parse frontmatter: {e}")

                content = '\n'.join(lines[end_idx + 1:])

        return content, frontmatter

    def _render_html(self, content: str) -> str:
        """Render content to HTML using cmarkgfm or fallback"""
        if self._use_cmark:
            try:
                if self.gfm:
                    return cmarkgfm.github_flavored_markdown_to_html(content)
                else:
                    return cmarkgfm.markdown_to_html(content)
            except Exception as e:
                logger.warning(f"cmarkgfm rendering failed: {e}")

        # Fallback: basic HTML rendering
        return self._fallback_render_html(content)

    def _fallback_render_html(self, content: str) -> str:
        """Basic HTML rendering without cmarkgfm"""
        html_parts = []
        lines = content.split('\n')
        in_code_block = False
        code_lang = ""
        code_lines = []
        in_list = False
        list_type = None

        i = 0
        while i < len(lines):
            line = lines[i]

            # Code blocks
            if line.startswith('```'):
                if in_code_block:
                    code = '\n'.join(code_lines)
                    lang_class = f' class="language-{code_lang}"' if code_lang else ''
                    html_parts.append(f'<pre><code{lang_class}>{self._escape_html(code)}</code></pre>')
                    in_code_block = False
                    code_lines = []
                else:
                    in_code_block = True
                    code_lang = line[3:].strip()
                i += 1
                continue

            if in_code_block:
                code_lines.append(line)
                i += 1
                continue

            # Close list if not a list item
            if in_list and not re.match(r'^(\s*[-*+]|\s*\d+\.)\s', line):
                tag = 'ul' if list_type == 'unordered' else 'ol'
                html_parts.append(f'</{tag}>')
                in_list = False

            # Headings
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
            if heading_match:
                level = len(heading_match.group(1))
                text = heading_match.group(2)
                anchor = self._slugify(text)
                html_parts.append(f'<h{level} id="{anchor}">{self._inline_html(text)}</h{level}>')
                i += 1
                continue

            # Horizontal rule
            if re.match(r'^[-*_]{3,}\s*$', line):
                html_parts.append('<hr>')
                i += 1
                continue

            # Blockquote
            if line.startswith('>'):
                quote_lines = []
                while i < len(lines) and lines[i].startswith('>'):
                    quote_lines.append(lines[i][1:].strip())
                    i += 1
                html_parts.append(f'<blockquote><p>{self._inline_html(" ".join(quote_lines))}</p></blockquote>')
                continue

            # Unordered list
            ul_match = re.match(r'^(\s*)[-*+]\s+(.+)$', line)
            if ul_match:
                if not in_list:
                    html_parts.append('<ul>')
                    in_list = True
                    list_type = 'unordered'
                text = ul_match.group(2)
                # Check for task list
                task_match = re.match(r'^\[([ xX])\]\s+(.+)$', text)
                if task_match:
                    checked = 'checked' if task_match.group(1).lower() == 'x' else ''
                    text = task_match.group(2)
                    html_parts.append(f'<li><input type="checkbox" {checked} disabled>{self._inline_html(text)}</li>')
                else:
                    html_parts.append(f'<li>{self._inline_html(text)}</li>')
                i += 1
                continue

            # Ordered list
            ol_match = re.match(r'^(\s*)\d+\.\s+(.+)$', line)
            if ol_match:
                if not in_list:
                    html_parts.append('<ol>')
                    in_list = True
                    list_type = 'ordered'
                html_parts.append(f'<li>{self._inline_html(ol_match.group(2))}</li>')
                i += 1
                continue

            # Paragraph
            if line.strip():
                para_lines = []
                while i < len(lines) and lines[i].strip() and not lines[i].startswith('#'):
                    if lines[i].startswith('```') or lines[i].startswith('>'):
                        break
                    if re.match(r'^[-*+]\s|^\d+\.\s', lines[i]):
                        break
                    para_lines.append(lines[i])
                    i += 1
                if para_lines:
                    html_parts.append(f'<p>{self._inline_html(" ".join(para_lines))}</p>')
                continue

            i += 1

        # Close any open list
        if in_list:
            tag = 'ul' if list_type == 'unordered' else 'ol'
            html_parts.append(f'</{tag}>')

        return '\n'.join(html_parts)

    def _inline_html(self, text: str) -> str:
        """Convert inline Markdown to HTML"""
        # Escape HTML first
        text = self._escape_html(text)

        # Images (before links since they use similar syntax)
        text = re.sub(
            r'!\[([^\]]*)\]\(([^)]+)\)',
            r'<img src="\2" alt="\1">',
            text
        )

        # Links
        text = re.sub(
            r'\[([^\]]+)\]\(([^)]+)\)',
            r'<a href="\2">\1</a>',
            text
        )

        # Bold (must be before italic)
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'__(.+?)__', r'<strong>\1</strong>', text)

        # Italic
        text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
        text = re.sub(r'_(.+?)_', r'<em>\1</em>', text)

        # Strikethrough (GFM)
        text = re.sub(r'~~(.+?)~~', r'<del>\1</del>', text)

        # Inline code
        text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

        return text

    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters"""
        return (text
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;'))

    def _extract_headings(self, content: str) -> List[Heading]:
        """Extract all headings from Markdown content"""
        headings = []
        lines = content.split('\n')
        in_code_block = False

        for i, line in enumerate(lines):
            # Track code blocks
            if line.startswith('```'):
                in_code_block = not in_code_block
                continue

            if in_code_block:
                continue

            # ATX headings (# style)
            match = re.match(r'^(#{1,6})\s+(.+?)(?:\s+#+)?$', line)
            if match:
                level = len(match.group(1))
                text = match.group(2).strip()
                headings.append(Heading(
                    level=level,
                    text=text,
                    line=i,
                    anchor=self._slugify(text)
                ))
                continue

            # Setext headings (underline style)
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                if re.match(r'^=+\s*$', next_line) and line.strip():
                    headings.append(Heading(
                        level=1,
                        text=line.strip(),
                        line=i,
                        anchor=self._slugify(line.strip())
                    ))
                elif re.match(r'^-+\s*$', next_line) and line.strip():
                    headings.append(Heading(
                        level=2,
                        text=line.strip(),
                        line=i,
                        anchor=self._slugify(line.strip())
                    ))

        return headings

    def _extract_paragraphs(self, content: str) -> List[str]:
        """Extract paragraph text from content"""
        paragraphs = []
        lines = content.split('\n')
        in_code_block = False
        current_para = []

        for line in lines:
            # Track code blocks
            if line.startswith('```'):
                in_code_block = not in_code_block
                if current_para:
                    paragraphs.append(' '.join(current_para))
                    current_para = []
                continue

            if in_code_block:
                continue

            # Skip headings, lists, blockquotes
            if line.startswith('#') or line.startswith('>'):
                if current_para:
                    paragraphs.append(' '.join(current_para))
                    current_para = []
                continue

            if re.match(r'^[-*+]\s|^\d+\.\s', line):
                if current_para:
                    paragraphs.append(' '.join(current_para))
                    current_para = []
                continue

            # Empty line ends paragraph
            if not line.strip():
                if current_para:
                    paragraphs.append(' '.join(current_para))
                    current_para = []
                continue

            current_para.append(line.strip())

        if current_para:
            paragraphs.append(' '.join(current_para))

        return paragraphs

    def _extract_code_blocks(self, content: str) -> List[CodeBlock]:
        """Extract fenced code blocks"""
        code_blocks = []
        lines = content.split('\n')
        in_block = False
        block_start = 0
        block_lang = ""
        block_info = ""
        block_lines = []

        for i, line in enumerate(lines):
            if line.startswith('```'):
                if in_block:
                    # End of code block
                    code_blocks.append(CodeBlock(
                        language=block_lang,
                        code='\n'.join(block_lines),
                        start_line=block_start,
                        end_line=i,
                        info=block_info
                    ))
                    in_block = False
                    block_lines = []
                else:
                    # Start of code block
                    in_block = True
                    block_start = i
                    info_string = line[3:].strip()
                    # Language is first word, rest is info
                    parts = info_string.split(None, 1)
                    block_lang = parts[0] if parts else ""
                    block_info = parts[1] if len(parts) > 1 else ""
            elif in_block:
                block_lines.append(line)

        return code_blocks

    def _extract_links(self, content: str) -> List[Link]:
        """Extract all links from content"""
        links = []
        lines = content.split('\n')

        for i, line in enumerate(lines):
            # Skip code blocks
            if line.startswith('```'):
                continue

            # Inline links [text](url "title")
            for match in re.finditer(r'\[([^\]]+)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)', line):
                # Skip images
                if match.start() > 0 and line[match.start() - 1] == '!':
                    continue
                links.append(Link(
                    text=match.group(1),
                    url=match.group(2),
                    title=match.group(3) or "",
                    line=i
                ))

        return links

    def _extract_images(self, content: str) -> List[Image]:
        """Extract all images from content"""
        images = []
        lines = content.split('\n')

        for i, line in enumerate(lines):
            # Skip code blocks
            if line.startswith('```'):
                continue

            # Images ![alt](url "title")
            for match in re.finditer(r'!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)', line):
                images.append(Image(
                    alt=match.group(1),
                    url=match.group(2),
                    title=match.group(3) or "",
                    line=i
                ))

        return images

    def _build_ast(self, content: str) -> MarkdownNode:
        """Build abstract syntax tree from content"""
        root = MarkdownNode(type=MarkdownNodeType.DOCUMENT)
        lines = content.split('\n')
        in_code_block = False
        code_node = None
        current_line = 0

        i = 0
        while i < len(lines):
            line = lines[i]

            # Code blocks
            if line.startswith('```'):
                if in_code_block and code_node:
                    code_node.end_line = i
                    root.children.append(code_node)
                    in_code_block = False
                    code_node = None
                else:
                    in_code_block = True
                    lang = line[3:].strip()
                    code_node = MarkdownNode(
                        type=MarkdownNodeType.CODE_BLOCK,
                        content="",
                        start_line=i,
                        attributes={'language': lang}
                    )
                i += 1
                continue

            if in_code_block and code_node:
                code_node.content += line + '\n'
                i += 1
                continue

            # Headings
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
            if heading_match:
                level = len(heading_match.group(1))
                text = heading_match.group(2)
                root.children.append(MarkdownNode(
                    type=MarkdownNodeType.HEADING,
                    content=text,
                    start_line=i,
                    end_line=i,
                    attributes={'level': level}
                ))
                i += 1
                continue

            # Blockquote
            if line.startswith('>'):
                quote_content = []
                start = i
                while i < len(lines) and lines[i].startswith('>'):
                    quote_content.append(lines[i][1:].strip())
                    i += 1
                root.children.append(MarkdownNode(
                    type=MarkdownNodeType.BLOCKQUOTE,
                    content='\n'.join(quote_content),
                    start_line=start,
                    end_line=i - 1
                ))
                continue

            # List
            list_match = re.match(r'^(\s*)([-*+]|\d+\.)\s+(.+)$', line)
            if list_match:
                is_ordered = list_match.group(2)[0].isdigit()
                list_node = MarkdownNode(
                    type=MarkdownNodeType.LIST,
                    start_line=i,
                    attributes={'ordered': is_ordered}
                )
                while i < len(lines):
                    item_match = re.match(r'^(\s*)([-*+]|\d+\.)\s+(.+)$', lines[i])
                    if not item_match:
                        break
                    list_node.children.append(MarkdownNode(
                        type=MarkdownNodeType.LIST_ITEM,
                        content=item_match.group(3),
                        start_line=i,
                        end_line=i
                    ))
                    i += 1
                list_node.end_line = i - 1
                root.children.append(list_node)
                continue

            # Paragraph
            if line.strip():
                para_lines = []
                start = i
                while i < len(lines) and lines[i].strip():
                    if lines[i].startswith('#') or lines[i].startswith('```'):
                        break
                    if lines[i].startswith('>'):
                        break
                    if re.match(r'^[-*+]\s|^\d+\.\s', lines[i]):
                        break
                    para_lines.append(lines[i])
                    i += 1
                if para_lines:
                    root.children.append(MarkdownNode(
                        type=MarkdownNodeType.PARAGRAPH,
                        content=' '.join(para_lines),
                        start_line=start,
                        end_line=i - 1
                    ))
                continue

            i += 1

        return root

    def _slugify(self, text: str) -> str:
        """Convert text to URL-safe slug"""
        # Convert to lowercase
        slug = text.lower()
        # Remove special characters
        slug = re.sub(r'[^\w\s-]', '', slug)
        # Replace spaces with hyphens
        slug = re.sub(r'[\s_]+', '-', slug)
        # Remove leading/trailing hyphens
        slug = slug.strip('-')
        return slug


def parse_markdown(content: str) -> MarkdownDocument:
    """Convenience function for parsing Markdown"""
    parser = MarkdownParser()
    return parser.parse(content)


def markdown_to_html(content: str, gfm: bool = True) -> str:
    """Convenience function for rendering Markdown to HTML"""
    parser = MarkdownParser(gfm=gfm)
    return parser.render_html(content)
