"""
Code Parser for source code analysis
Parses source code files extracting imports, classes, functions, and comments
"""

import logging
import re
import ast
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum, auto
from pathlib import Path

logger = logging.getLogger(__name__)

# Try to import tree-sitter for enhanced parsing
try:
    import tree_sitter
    import tree_sitter_python
    import tree_sitter_javascript
    TREE_SITTER_AVAILABLE = True
except ImportError:
    tree_sitter = None
    TREE_SITTER_AVAILABLE = False
    logger.debug("tree-sitter not available, using ast/regex fallback")


class CodeNodeType(Enum):
    """Types of code nodes"""
    MODULE = auto()
    CLASS = auto()
    FUNCTION = auto()
    METHOD = auto()
    IMPORT = auto()
    VARIABLE = auto()
    CONSTANT = auto()
    COMMENT = auto()
    DOCSTRING = auto()
    DECORATOR = auto()
    BLOCK = auto()


@dataclass
class CodeNode:
    """Represents a node in the code AST"""
    type: CodeNodeType
    name: str = ""
    content: str = ""
    children: List['CodeNode'] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)
    start_line: int = 0
    end_line: int = 0
    docstring: str = ""


@dataclass
class Import:
    """Represents an import statement"""
    module: str
    names: List[str] = field(default_factory=list)
    alias: str = ""
    is_from: bool = False
    line: int = 0


@dataclass
class ClassDef:
    """Represents a class definition"""
    name: str
    bases: List[str] = field(default_factory=list)
    methods: List['FunctionDef'] = field(default_factory=list)
    attributes: List[str] = field(default_factory=list)
    docstring: str = ""
    decorators: List[str] = field(default_factory=list)
    start_line: int = 0
    end_line: int = 0


@dataclass
class FunctionDef:
    """Represents a function/method definition"""
    name: str
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    return_type: str = ""
    docstring: str = ""
    decorators: List[str] = field(default_factory=list)
    is_async: bool = False
    is_method: bool = False
    start_line: int = 0
    end_line: int = 0


@dataclass
class Comment:
    """Represents a comment"""
    text: str
    line: int
    is_block: bool = False
    is_docstring: bool = False


@dataclass
class CodeDocument:
    """Represents a parsed code file"""
    # Raw content
    raw_content: str = ""
    language: str = ""
    file_path: str = ""

    # Parsed elements
    imports: List[Import] = field(default_factory=list)
    classes: List[ClassDef] = field(default_factory=list)
    functions: List[FunctionDef] = field(default_factory=list)
    comments: List[Comment] = field(default_factory=list)
    docstrings: List[Comment] = field(default_factory=list)

    # Module-level
    module_docstring: str = ""
    global_variables: List[str] = field(default_factory=list)
    constants: List[str] = field(default_factory=list)

    # Structure
    root: Optional[CodeNode] = None

    # Statistics
    line_count: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0

    def get_outline(self) -> List[Dict[str, Any]]:
        """Get code outline from classes and functions"""
        outline = []

        for cls in self.classes:
            outline.append({
                'type': 'class',
                'name': cls.name,
                'line': cls.start_line,
                'children': [
                    {'type': 'method', 'name': m.name, 'line': m.start_line}
                    for m in cls.methods
                ]
            })

        for func in self.functions:
            if not func.is_method:
                outline.append({
                    'type': 'function',
                    'name': func.name,
                    'line': func.start_line,
                })

        return outline

    def get_symbols(self) -> List[str]:
        """Get all defined symbols"""
        symbols = []
        symbols.extend([c.name for c in self.classes])
        symbols.extend([f.name for f in self.functions])
        symbols.extend(self.global_variables)
        symbols.extend(self.constants)
        return symbols


class CodeParser:
    """
    Code parser for multiple programming languages

    Supports Python, JavaScript, TypeScript, and Bash
    Uses tree-sitter when available, with language-specific fallbacks
    """

    SUPPORTED_LANGUAGES = ['python', 'javascript', 'typescript', 'bash']

    def __init__(self):
        """Initialize parser"""
        self._use_tree_sitter = TREE_SITTER_AVAILABLE
        self._ts_parsers = {}

        if self._use_tree_sitter:
            self._init_tree_sitter()

    def _init_tree_sitter(self):
        """Initialize tree-sitter parsers"""
        try:
            # Python parser
            self._ts_parsers['python'] = tree_sitter.Parser(
                tree_sitter.Language(tree_sitter_python.language())
            )
        except Exception as e:
            logger.debug(f"Failed to init Python tree-sitter: {e}")

        try:
            # JavaScript parser
            self._ts_parsers['javascript'] = tree_sitter.Parser(
                tree_sitter.Language(tree_sitter_javascript.language())
            )
            self._ts_parsers['typescript'] = self._ts_parsers['javascript']
        except Exception as e:
            logger.debug(f"Failed to init JavaScript tree-sitter: {e}")

    def parse(self, content: str, language: str) -> CodeDocument:
        """
        Parse source code

        Args:
            content: Source code content
            language: Programming language (python, javascript, etc.)

        Returns:
            CodeDocument with parsed elements
        """
        doc = CodeDocument(
            raw_content=content,
            language=language.lower()
        )

        if not content:
            return doc

        # Calculate line statistics
        lines = content.split('\n')
        doc.line_count = len(lines)
        doc.blank_lines = sum(1 for line in lines if not line.strip())

        # Parse based on language
        language = language.lower()

        if language == 'python':
            self._parse_python(content, doc)
        elif language in ('javascript', 'typescript'):
            self._parse_javascript(content, doc)
        elif language == 'bash':
            self._parse_bash(content, doc)
        else:
            # Generic parsing
            self._parse_generic(content, doc)

        # Calculate code/comment lines
        doc.comment_lines = len(doc.comments)
        doc.code_lines = doc.line_count - doc.blank_lines - doc.comment_lines

        return doc

    def parse_file(self, file_path: Path) -> CodeDocument:
        """
        Parse source code file

        Args:
            file_path: Path to source file

        Returns:
            CodeDocument with parsed elements
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        content = file_path.read_text(encoding='utf-8', errors='replace')

        # Detect language from extension
        ext_map = {
            '.py': 'python',
            '.pyw': 'python',
            '.js': 'javascript',
            '.mjs': 'javascript',
            '.jsx': 'javascript',
            '.ts': 'typescript',
            '.tsx': 'typescript',
            '.sh': 'bash',
            '.bash': 'bash',
        }
        language = ext_map.get(file_path.suffix.lower(), 'text')

        doc = self.parse(content, language)
        doc.file_path = str(file_path)
        return doc

    def extract_imports(self, content: str, language: str) -> List[Import]:
        """Extract imports from code"""
        doc = CodeDocument()
        language = language.lower()

        if language == 'python':
            self._extract_python_imports(content, doc)
        elif language in ('javascript', 'typescript'):
            self._extract_js_imports(content, doc)

        return doc.imports

    def extract_functions(self, content: str, language: str) -> List[FunctionDef]:
        """Extract function definitions from code"""
        doc = self.parse(content, language)
        return doc.functions

    def extract_classes(self, content: str, language: str) -> List[ClassDef]:
        """Extract class definitions from code"""
        doc = self.parse(content, language)
        return doc.classes

    def to_document(self, code_doc: CodeDocument) -> Dict[str, Any]:
        """
        Convert CodeDocument to internal Document structure

        Args:
            code_doc: Parsed CodeDocument

        Returns:
            Dictionary compatible with Document model
        """
        sections = []

        # Add classes as sections
        for cls in code_doc.classes:
            sections.append({
                'name': cls.name,
                'title': f"class {cls.name}",
                'level': 1,
                'start_line': cls.start_line,
            })
            # Add methods as subsections
            for method in cls.methods:
                sections.append({
                    'name': f"{cls.name}.{method.name}",
                    'title': f"def {method.name}",
                    'level': 2,
                    'start_line': method.start_line,
                })

        # Add standalone functions
        for func in code_doc.functions:
            if not func.is_method:
                sections.append({
                    'name': func.name,
                    'title': f"def {func.name}",
                    'level': 1,
                    'start_line': func.start_line,
                })

        return {
            'content': code_doc.raw_content,
            'title': Path(code_doc.file_path).stem if code_doc.file_path else "Untitled",
            'language': code_doc.language,
            'sections': sections,
            'metadata': {
                'imports': [i.module for i in code_doc.imports],
                'classes': [c.name for c in code_doc.classes],
                'functions': [f.name for f in code_doc.functions],
                'line_count': code_doc.line_count,
            },
        }

    # --- Python parsing ---

    def _parse_python(self, content: str, doc: CodeDocument):
        """Parse Python source code"""
        # Use tree-sitter if available
        if self._use_tree_sitter and 'python' in self._ts_parsers:
            self._parse_python_tree_sitter(content, doc)
            return

        # Fallback to ast module
        self._parse_python_ast(content, doc)

    def _parse_python_ast(self, content: str, doc: CodeDocument):
        """Parse Python using ast module"""
        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            logger.warning(f"Python syntax error: {e}")
            # Fall back to regex parsing
            self._parse_python_regex(content, doc)
            return

        # Extract module docstring
        if (tree.body and isinstance(tree.body[0], ast.Expr) and
                isinstance(tree.body[0].value, ast.Constant) and
                isinstance(tree.body[0].value.value, str)):
            doc.module_docstring = tree.body[0].value.value

        # Walk the AST
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    doc.imports.append(Import(
                        module=alias.name,
                        alias=alias.asname or "",
                        line=node.lineno
                    ))

            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = [a.name for a in node.names]
                doc.imports.append(Import(
                    module=module,
                    names=names,
                    is_from=True,
                    line=node.lineno
                ))

            elif isinstance(node, ast.ClassDef):
                cls = self._parse_python_class(node)
                doc.classes.append(cls)

            elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                # Only top-level functions
                if not any(isinstance(parent, ast.ClassDef)
                           for parent in ast.walk(tree)
                           if hasattr(parent, 'body') and node in getattr(parent, 'body', [])):
                    func = self._parse_python_function(node)
                    doc.functions.append(func)

            elif isinstance(node, ast.Assign):
                # Global variables
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        name = target.id
                        if name.isupper():
                            doc.constants.append(name)
                        else:
                            doc.global_variables.append(name)

        # Extract comments
        self._extract_python_comments(content, doc)

    def _parse_python_class(self, node: ast.ClassDef) -> ClassDef:
        """Parse Python class definition"""
        cls = ClassDef(
            name=node.name,
            bases=[self._get_base_name(b) for b in node.bases],
            decorators=[self._get_decorator_name(d) for d in node.decorator_list],
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno
        )

        # Get docstring
        if (node.body and isinstance(node.body[0], ast.Expr) and
                isinstance(node.body[0].value, ast.Constant) and
                isinstance(node.body[0].value.value, str)):
            cls.docstring = node.body[0].value.value

        # Get methods
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method = self._parse_python_function(item)
                method.is_method = True
                cls.methods.append(method)

        return cls

    def _parse_python_function(self, node) -> FunctionDef:
        """Parse Python function definition"""
        func = FunctionDef(
            name=node.name,
            decorators=[self._get_decorator_name(d) for d in node.decorator_list],
            is_async=isinstance(node, ast.AsyncFunctionDef),
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno
        )

        # Parse parameters
        for arg in node.args.args:
            param = {'name': arg.arg}
            if arg.annotation:
                param['type'] = ast.unparse(arg.annotation) if hasattr(ast, 'unparse') else ""
            func.parameters.append(param)

        # Return type
        if node.returns:
            func.return_type = ast.unparse(node.returns) if hasattr(ast, 'unparse') else ""

        # Get docstring
        if (node.body and isinstance(node.body[0], ast.Expr) and
                isinstance(node.body[0].value, ast.Constant) and
                isinstance(node.body[0].value.value, str)):
            func.docstring = node.body[0].value.value

        return func

    def _get_base_name(self, node) -> str:
        """Get base class name from AST node"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_base_name(node.value)}.{node.attr}"
        return ""

    def _get_decorator_name(self, node) -> str:
        """Get decorator name from AST node"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Call):
            return self._get_decorator_name(node.func)
        elif isinstance(node, ast.Attribute):
            return f"{self._get_decorator_name(node.value)}.{node.attr}"
        return ""

    def _extract_python_comments(self, content: str, doc: CodeDocument):
        """Extract comments from Python code"""
        lines = content.split('\n')
        in_multiline = False
        multiline_start = 0
        multiline_lines = []
        quote_char = None

        for i, line in enumerate(lines):
            stripped = line.strip()

            # Check for multiline string (potential docstring)
            if not in_multiline:
                for quote in ['"""', "'''"]:
                    if quote in stripped:
                        count = stripped.count(quote)
                        if count == 1:
                            in_multiline = True
                            multiline_start = i
                            quote_char = quote
                            multiline_lines = [stripped.split(quote, 1)[1]]
                        elif count >= 2:
                            # Single line docstring
                            text = stripped.split(quote)[1]
                            doc.comments.append(Comment(
                                text=text,
                                line=i,
                                is_block=True,
                                is_docstring=True
                            ))
            else:
                if quote_char in stripped:
                    multiline_lines.append(stripped.split(quote_char)[0])
                    doc.comments.append(Comment(
                        text='\n'.join(multiline_lines),
                        line=multiline_start,
                        is_block=True,
                        is_docstring=True
                    ))
                    in_multiline = False
                    multiline_lines = []
                else:
                    multiline_lines.append(stripped)

            # Single line comments
            if '#' in line and not in_multiline:
                # Check it's not inside a string
                comment_match = re.search(r'(?<!["\'])#(.*)$', line)
                if comment_match:
                    doc.comments.append(Comment(
                        text=comment_match.group(1).strip(),
                        line=i
                    ))

    def _parse_python_regex(self, content: str, doc: CodeDocument):
        """Fallback regex-based Python parsing"""
        lines = content.split('\n')

        for i, line in enumerate(lines):
            # Imports
            import_match = re.match(r'^import\s+(\S+)(?:\s+as\s+(\S+))?', line)
            if import_match:
                doc.imports.append(Import(
                    module=import_match.group(1),
                    alias=import_match.group(2) or "",
                    line=i
                ))

            from_match = re.match(r'^from\s+(\S+)\s+import\s+(.+)', line)
            if from_match:
                names = [n.strip() for n in from_match.group(2).split(',')]
                doc.imports.append(Import(
                    module=from_match.group(1),
                    names=names,
                    is_from=True,
                    line=i
                ))

            # Classes
            class_match = re.match(r'^class\s+(\w+)(?:\(([^)]*)\))?:', line)
            if class_match:
                bases = []
                if class_match.group(2):
                    bases = [b.strip() for b in class_match.group(2).split(',')]
                doc.classes.append(ClassDef(
                    name=class_match.group(1),
                    bases=bases,
                    start_line=i
                ))

            # Functions
            func_match = re.match(r'^(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)', line)
            if func_match:
                is_async = 'async' in line[:line.index('def')]
                params = []
                if func_match.group(2):
                    for p in func_match.group(2).split(','):
                        p = p.strip()
                        if p and p != 'self':
                            params.append({'name': p.split(':')[0].strip()})
                doc.functions.append(FunctionDef(
                    name=func_match.group(1),
                    parameters=params,
                    is_async=is_async,
                    start_line=i
                ))

    def _extract_python_imports(self, content: str, doc: CodeDocument):
        """Extract only imports from Python code"""
        try:
            tree = ast.parse(content)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        doc.imports.append(Import(
                            module=alias.name,
                            alias=alias.asname or "",
                            line=node.lineno
                        ))
                elif isinstance(node, ast.ImportFrom):
                    doc.imports.append(Import(
                        module=node.module or "",
                        names=[a.name for a in node.names],
                        is_from=True,
                        line=node.lineno
                    ))
        except SyntaxError:
            # Fallback to regex
            for i, line in enumerate(content.split('\n')):
                if line.startswith('import ') or line.startswith('from '):
                    import_match = re.match(r'^import\s+(\S+)', line)
                    if import_match:
                        doc.imports.append(Import(module=import_match.group(1), line=i))

    def _parse_python_tree_sitter(self, content: str, doc: CodeDocument):
        """Parse Python using tree-sitter"""
        parser = self._ts_parsers['python']
        tree = parser.parse(bytes(content, 'utf-8'))

        def traverse(node, depth=0):
            if node.type == 'import_statement':
                # Handle import
                for child in node.children:
                    if child.type == 'dotted_name':
                        doc.imports.append(Import(
                            module=content[child.start_byte:child.end_byte],
                            line=child.start_point[0]
                        ))

            elif node.type == 'import_from_statement':
                module = ""
                names = []
                for child in node.children:
                    if child.type == 'dotted_name':
                        module = content[child.start_byte:child.end_byte]
                    elif child.type == 'import_list':
                        for name_node in child.children:
                            if name_node.type == 'dotted_name':
                                names.append(content[name_node.start_byte:name_node.end_byte])
                doc.imports.append(Import(
                    module=module,
                    names=names,
                    is_from=True,
                    line=node.start_point[0]
                ))

            elif node.type == 'class_definition':
                name = ""
                for child in node.children:
                    if child.type == 'identifier':
                        name = content[child.start_byte:child.end_byte]
                        break
                doc.classes.append(ClassDef(
                    name=name,
                    start_line=node.start_point[0],
                    end_line=node.end_point[0]
                ))

            elif node.type == 'function_definition':
                name = ""
                for child in node.children:
                    if child.type == 'identifier':
                        name = content[child.start_byte:child.end_byte]
                        break
                doc.functions.append(FunctionDef(
                    name=name,
                    start_line=node.start_point[0],
                    end_line=node.end_point[0]
                ))

            for child in node.children:
                traverse(child, depth + 1)

        traverse(tree.root_node)

        # Still extract comments with regex (tree-sitter handles them differently)
        self._extract_python_comments(content, doc)

    # --- JavaScript/TypeScript parsing ---

    def _parse_javascript(self, content: str, doc: CodeDocument):
        """Parse JavaScript/TypeScript source code"""
        if self._use_tree_sitter and 'javascript' in self._ts_parsers:
            self._parse_js_tree_sitter(content, doc)
        else:
            self._parse_js_regex(content, doc)

    def _parse_js_regex(self, content: str, doc: CodeDocument):
        """Regex-based JavaScript parsing"""
        lines = content.split('\n')

        for i, line in enumerate(lines):
            # ES6 imports
            import_match = re.match(r"^import\s+(?:(\w+)|{([^}]+)})\s+from\s+['\"]([^'\"]+)['\"]", line)
            if import_match:
                default_import = import_match.group(1)
                named_imports = import_match.group(2)
                module = import_match.group(3)

                names = []
                if default_import:
                    names.append(default_import)
                if named_imports:
                    names.extend([n.strip().split(' as ')[0] for n in named_imports.split(',')])

                doc.imports.append(Import(
                    module=module,
                    names=names,
                    is_from=True,
                    line=i
                ))

            # CommonJS require
            require_match = re.match(r"^(?:const|let|var)\s+(?:(\w+)|{([^}]+)})\s*=\s*require\(['\"]([^'\"]+)['\"]\)", line)
            if require_match:
                doc.imports.append(Import(
                    module=require_match.group(3),
                    names=[require_match.group(1)] if require_match.group(1) else [],
                    line=i
                ))

            # Classes
            class_match = re.match(r'^(?:export\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?', line)
            if class_match:
                doc.classes.append(ClassDef(
                    name=class_match.group(1),
                    bases=[class_match.group(2)] if class_match.group(2) else [],
                    start_line=i
                ))

            # Functions (including arrow functions)
            func_patterns = [
                r'^(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)',
                r'^(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s+)?\(([^)]*)\)\s*=>',
                r'^(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s+)?function\s*\(([^)]*)\)',
            ]
            for pattern in func_patterns:
                func_match = re.match(pattern, line)
                if func_match:
                    params = []
                    if func_match.group(2):
                        for p in func_match.group(2).split(','):
                            p = p.strip()
                            if p:
                                params.append({'name': p.split(':')[0].split('=')[0].strip()})
                    doc.functions.append(FunctionDef(
                        name=func_match.group(1),
                        parameters=params,
                        is_async='async' in line,
                        start_line=i
                    ))
                    break

        # Extract comments
        self._extract_js_comments(content, doc)

    def _extract_js_comments(self, content: str, doc: CodeDocument):
        """Extract comments from JavaScript code"""
        lines = content.split('\n')

        # Single line comments
        for i, line in enumerate(lines):
            comment_match = re.search(r'//(.*)$', line)
            if comment_match:
                doc.comments.append(Comment(
                    text=comment_match.group(1).strip(),
                    line=i
                ))

        # Block comments
        for match in re.finditer(r'/\*\*?(.*?)\*/', content, re.DOTALL):
            text = match.group(1).strip()
            # Clean up JSDoc-style comments
            text = re.sub(r'^\s*\*\s?', '', text, flags=re.MULTILINE)
            start_line = content[:match.start()].count('\n')
            doc.comments.append(Comment(
                text=text,
                line=start_line,
                is_block=True,
                is_docstring=match.group(0).startswith('/**')
            ))

    def _extract_js_imports(self, content: str, doc: CodeDocument):
        """Extract only imports from JavaScript code"""
        self._parse_js_regex(content, doc)
        # Keep only imports
        doc.classes = []
        doc.functions = []
        doc.comments = []

    def _parse_js_tree_sitter(self, content: str, doc: CodeDocument):
        """Parse JavaScript using tree-sitter"""
        parser = self._ts_parsers['javascript']
        tree = parser.parse(bytes(content, 'utf-8'))

        def traverse(node):
            if node.type == 'import_statement':
                module = ""
                names = []
                for child in node.children:
                    if child.type == 'string':
                        module = content[child.start_byte + 1:child.end_byte - 1]
                    elif child.type == 'import_clause':
                        for import_child in child.children:
                            if import_child.type == 'identifier':
                                names.append(content[import_child.start_byte:import_child.end_byte])
                            elif import_child.type == 'named_imports':
                                for spec in import_child.children:
                                    if spec.type == 'import_specifier':
                                        for spec_child in spec.children:
                                            if spec_child.type == 'identifier':
                                                names.append(content[spec_child.start_byte:spec_child.end_byte])
                                                break
                doc.imports.append(Import(
                    module=module,
                    names=names,
                    is_from=True,
                    line=node.start_point[0]
                ))

            elif node.type == 'class_declaration':
                name = ""
                for child in node.children:
                    if child.type == 'identifier':
                        name = content[child.start_byte:child.end_byte]
                        break
                doc.classes.append(ClassDef(
                    name=name,
                    start_line=node.start_point[0],
                    end_line=node.end_point[0]
                ))

            elif node.type in ('function_declaration', 'arrow_function'):
                name = ""
                for child in node.children:
                    if child.type == 'identifier':
                        name = content[child.start_byte:child.end_byte]
                        break
                if name:
                    doc.functions.append(FunctionDef(
                        name=name,
                        start_line=node.start_point[0],
                        end_line=node.end_point[0]
                    ))

            for child in node.children:
                traverse(child)

        traverse(tree.root_node)
        self._extract_js_comments(content, doc)

    # --- Bash parsing ---

    def _parse_bash(self, content: str, doc: CodeDocument):
        """Parse Bash source code"""
        lines = content.split('\n')

        for i, line in enumerate(lines):
            stripped = line.strip()

            # Functions
            func_match = re.match(r'^(?:function\s+)?(\w+)\s*\(\s*\)', stripped)
            if func_match:
                doc.functions.append(FunctionDef(
                    name=func_match.group(1),
                    start_line=i
                ))

            # Variables (exported or regular)
            var_match = re.match(r'^(?:export\s+)?(\w+)=', stripped)
            if var_match:
                name = var_match.group(1)
                if name.isupper():
                    doc.constants.append(name)
                else:
                    doc.global_variables.append(name)

            # Comments
            if stripped.startswith('#') and not stripped.startswith('#!'):
                doc.comments.append(Comment(
                    text=stripped[1:].strip(),
                    line=i
                ))

            # Source/import
            source_match = re.match(r'^(?:source|\.) +["\']?([^"\']+)["\']?', stripped)
            if source_match:
                doc.imports.append(Import(
                    module=source_match.group(1),
                    line=i
                ))

    # --- Generic parsing ---

    def _parse_generic(self, content: str, doc: CodeDocument):
        """Generic parsing for unsupported languages"""
        lines = content.split('\n')

        for i, line in enumerate(lines):
            # C-style comments
            if '//' in line:
                comment_match = re.search(r'//(.*)$', line)
                if comment_match:
                    doc.comments.append(Comment(
                        text=comment_match.group(1).strip(),
                        line=i
                    ))

            # Shell/Python comments
            if '#' in line and not line.strip().startswith('#!'):
                comment_match = re.search(r'#(.*)$', line)
                if comment_match:
                    doc.comments.append(Comment(
                        text=comment_match.group(1).strip(),
                        line=i
                    ))


def parse_code(content: str, language: str) -> CodeDocument:
    """Convenience function for parsing code"""
    parser = CodeParser()
    return parser.parse(content, language)


def parse_code_file(file_path: Path) -> CodeDocument:
    """Convenience function for parsing code file"""
    parser = CodeParser()
    return parser.parse_file(file_path)
