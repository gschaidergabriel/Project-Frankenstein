"""
Error Analyzer
Analyze and classify errors from code execution
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
    """Categories of errors"""
    SYNTAX = "syntax"
    IMPORT = "import"
    NAME = "name"
    TYPE = "type"
    ATTRIBUTE = "attribute"
    INDEX = "index"
    KEY = "key"
    VALUE = "value"
    RUNTIME = "runtime"
    PERMISSION = "permission"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


@dataclass
class ErrorInfo:
    """Information about a parsed error"""
    error_type: str
    category: ErrorCategory
    line_number: Optional[int] = None
    column: Optional[int] = None
    message: str = ""
    suggestion: Optional[str] = None
    context_lines: List[str] = field(default_factory=list)
    root_cause: Optional[str] = None
    stack_trace: List[str] = field(default_factory=list)
    related_symbol: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization"""
        return {
            "error_type": self.error_type,
            "category": self.category.value,
            "line_number": self.line_number,
            "column": self.column,
            "message": self.message,
            "suggestion": self.suggestion,
            "context_lines": self.context_lines,
            "root_cause": self.root_cause,
            "stack_trace": self.stack_trace,
            "related_symbol": self.related_symbol,
        }


class ErrorAnalyzer:
    """Analyze and classify errors from code execution"""

    # Python error patterns
    PYTHON_PATTERNS = {
        'NameError': {
            'pattern': r"NameError: name '(\w+)' is not defined",
            'category': ErrorCategory.NAME,
            'suggestion_template': "Variable or function '{0}' is not defined. Check spelling or add import.",
        },
        'ModuleNotFoundError': {
            'pattern': r"ModuleNotFoundError: No module named '([\w.]+)'",
            'category': ErrorCategory.IMPORT,
            'suggestion_template': "Module '{0}' is not installed. Try: pip install {0}",
        },
        'ImportError': {
            'pattern': r"ImportError: cannot import name '(\w+)' from '([\w.]+)'",
            'category': ErrorCategory.IMPORT,
            'suggestion_template': "Cannot import '{0}' from '{1}'. Check the module's available exports.",
        },
        'SyntaxError': {
            'pattern': r"SyntaxError: (.+)",
            'category': ErrorCategory.SYNTAX,
            'suggestion_template': "Syntax error: {0}. Check for missing brackets, quotes, or colons.",
        },
        'IndentationError': {
            'pattern': r"IndentationError: (.+)",
            'category': ErrorCategory.SYNTAX,
            'suggestion_template': "Indentation error: {0}. Check consistent use of tabs/spaces.",
        },
        'TypeError': {
            'pattern': r"TypeError: (.+)",
            'category': ErrorCategory.TYPE,
            'suggestion_template': "Type error: {0}",
        },
        'TypeError_argument': {
            'pattern': r"TypeError: (\w+)\(\) takes (\d+) positional arguments? but (\d+) (?:was|were) given",
            'category': ErrorCategory.TYPE,
            'suggestion_template': "Function '{0}' expects {1} argument(s) but received {2}.",
        },
        'TypeError_unsupported': {
            'pattern': r"TypeError: unsupported operand type\(s\) for (.+): '(\w+)' and '(\w+)'",
            'category': ErrorCategory.TYPE,
            'suggestion_template': "Cannot use '{0}' operator between types '{1}' and '{2}'.",
        },
        'AttributeError': {
            'pattern': r"AttributeError: '(\w+)' object has no attribute '(\w+)'",
            'category': ErrorCategory.ATTRIBUTE,
            'suggestion_template': "Object of type '{0}' has no attribute '{1}'. Check spelling or documentation.",
        },
        'IndexError': {
            'pattern': r"IndexError: (.+)",
            'category': ErrorCategory.INDEX,
            'suggestion_template': "Index error: {0}. Check array bounds.",
        },
        'KeyError': {
            'pattern': r"KeyError: ['\"]?(.+?)['\"]?$",
            'category': ErrorCategory.KEY,
            'suggestion_template': "Key '{0}' not found in dictionary. Check key spelling or use .get() method.",
        },
        'ValueError': {
            'pattern': r"ValueError: (.+)",
            'category': ErrorCategory.VALUE,
            'suggestion_template': "Value error: {0}",
        },
        'ZeroDivisionError': {
            'pattern': r"ZeroDivisionError: (.+)",
            'category': ErrorCategory.RUNTIME,
            'suggestion_template': "Division by zero. Add a check for zero before dividing.",
        },
        'FileNotFoundError': {
            'pattern': r"FileNotFoundError: .+?'(.+?)'",
            'category': ErrorCategory.RUNTIME,
            'suggestion_template': "File '{0}' not found. Check the file path.",
        },
        'PermissionError': {
            'pattern': r"PermissionError: .+?'(.+?)'",
            'category': ErrorCategory.PERMISSION,
            'suggestion_template': "Permission denied for '{0}'. Check file permissions.",
        },
    }

    # JavaScript error patterns
    JAVASCRIPT_PATTERNS = {
        'ReferenceError': {
            'pattern': r"ReferenceError: (\w+) is not defined",
            'category': ErrorCategory.NAME,
            'suggestion_template': "Variable '{0}' is not defined. Check spelling or add import/require.",
        },
        'SyntaxError': {
            'pattern': r"SyntaxError: (.+)",
            'category': ErrorCategory.SYNTAX,
            'suggestion_template': "Syntax error: {0}",
        },
        'SyntaxError_unexpected': {
            'pattern': r"SyntaxError: Unexpected token (.+)",
            'category': ErrorCategory.SYNTAX,
            'suggestion_template': "Unexpected token '{0}'. Check for missing brackets or semicolons.",
        },
        'TypeError': {
            'pattern': r"TypeError: (.+)",
            'category': ErrorCategory.TYPE,
            'suggestion_template': "Type error: {0}",
        },
        'TypeError_undefined': {
            'pattern': r"TypeError: Cannot read propert(?:y|ies) ['\"]?(\w+)['\"]? of (undefined|null)",
            'category': ErrorCategory.TYPE,
            'suggestion_template': "Cannot read '{0}' of {1}. Add null check before accessing property.",
        },
        'TypeError_not_function': {
            'pattern': r"TypeError: (\w+) is not a function",
            'category': ErrorCategory.TYPE,
            'suggestion_template': "'{0}' is not a function. Check if it's properly imported or defined.",
        },
        'RangeError': {
            'pattern': r"RangeError: (.+)",
            'category': ErrorCategory.INDEX,
            'suggestion_template': "Range error: {0}. Check array size or recursion depth.",
        },
    }

    # Bash error patterns
    BASH_PATTERNS = {
        'command_not_found': {
            'pattern': r"(.+): command not found",
            'category': ErrorCategory.NAME,
            'suggestion_template': "Command '{0}' not found. Check spelling or install the package.",
        },
        'syntax_error': {
            'pattern': r"syntax error near unexpected token ['\"]?(.+?)['\"]?",
            'category': ErrorCategory.SYNTAX,
            'suggestion_template': "Bash syntax error near '{0}'. Check quoting and escaping.",
        },
        'no_such_file': {
            'pattern': r"(.+): No such file or directory",
            'category': ErrorCategory.RUNTIME,
            'suggestion_template': "File or directory '{0}' not found.",
        },
        'permission_denied': {
            'pattern': r"(.+): Permission denied",
            'category': ErrorCategory.PERMISSION,
            'suggestion_template': "Permission denied for '{0}'. Try with sudo or check permissions.",
        },
        'unbound_variable': {
            'pattern': r"(.+): unbound variable",
            'category': ErrorCategory.NAME,
            'suggestion_template': "Variable '{0}' is not set. Initialize it before use.",
        },
    }

    # SQL error patterns
    SQL_PATTERNS = {
        'syntax_error': {
            'pattern': r"(?:syntax error|ERROR).*?(?:at or near|near) ['\"](.+?)['\"]",
            'category': ErrorCategory.SYNTAX,
            'suggestion_template': "SQL syntax error near '{0}'. Check SQL syntax.",
        },
        'table_not_found': {
            'pattern': r"(?:relation|table) ['\"]?(\w+)['\"]? does not exist",
            'category': ErrorCategory.NAME,
            'suggestion_template': "Table '{0}' does not exist. Check table name or create the table.",
        },
        'column_not_found': {
            'pattern': r"column ['\"]?(\w+)['\"]? (?:does not exist|of relation)",
            'category': ErrorCategory.NAME,
            'suggestion_template': "Column '{0}' does not exist. Check column name.",
        },
        'constraint_violation': {
            'pattern': r"(?:violates|duplicate key).+?constraint ['\"]?(\w+)['\"]?",
            'category': ErrorCategory.VALUE,
            'suggestion_template': "Constraint violation: '{0}'. Check data uniqueness or foreign keys.",
        },
    }

    # Language pattern mapping
    LANGUAGE_PATTERNS = {
        'python': PYTHON_PATTERNS,
        'javascript': JAVASCRIPT_PATTERNS,
        'bash': BASH_PATTERNS,
        'sql': SQL_PATTERNS,
    }

    # Common import suggestions for Python
    PYTHON_COMMON_IMPORTS = {
        'np': 'numpy',
        'pd': 'pandas',
        'plt': 'matplotlib.pyplot',
        'sns': 'seaborn',
        'tf': 'tensorflow',
        'torch': 'torch',
        'cv2': 'cv2',
        'sklearn': 'sklearn',
        'requests': 'requests',
        'json': 'json',
        'os': 'os',
        'sys': 'sys',
        're': 're',
        'datetime': 'datetime',
        'Path': 'pathlib',
        'defaultdict': 'collections',
        'Counter': 'collections',
        'namedtuple': 'collections',
        'dataclass': 'dataclasses',
        'field': 'dataclasses',
        'Optional': 'typing',
        'List': 'typing',
        'Dict': 'typing',
        'Tuple': 'typing',
        'Any': 'typing',
        'Union': 'typing',
        'Callable': 'typing',
        'asyncio': 'asyncio',
        'aiohttp': 'aiohttp',
    }

    def analyze(self, stderr: str, language: str) -> ErrorInfo:
        """
        Analyze error output and return structured ErrorInfo.

        Args:
            stderr: The error output from code execution
            language: Programming language (python, javascript, bash, sql)

        Returns:
            ErrorInfo with parsed error details
        """
        if not stderr or not stderr.strip():
            return ErrorInfo(
                error_type="Unknown",
                category=ErrorCategory.UNKNOWN,
                message="No error message provided"
            )

        # Get patterns for the language
        patterns = self.LANGUAGE_PATTERNS.get(language.lower(), {})

        # Extract stack trace first
        stack_trace = self._extract_stack_trace(stderr, language)

        # Try to match each pattern
        for error_name, pattern_info in patterns.items():
            match = re.search(pattern_info['pattern'], stderr, re.MULTILINE | re.IGNORECASE)
            if match:
                groups = match.groups()

                # Build suggestion from template
                suggestion = None
                if 'suggestion_template' in pattern_info and groups:
                    try:
                        suggestion = pattern_info['suggestion_template'].format(*groups)
                    except (IndexError, KeyError):
                        suggestion = pattern_info['suggestion_template']

                # Extract line number
                line_number, column = self._extract_location(stderr, language)

                # Get the base error type (without variant suffix)
                base_error_type = error_name.split('_')[0]

                # Get related symbol if available
                related_symbol = groups[0] if groups else None

                # Enhance suggestion for known imports
                if language == 'python' and pattern_info['category'] == ErrorCategory.NAME:
                    enhanced_suggestion = self._enhance_python_suggestion(related_symbol)
                    if enhanced_suggestion:
                        suggestion = enhanced_suggestion

                # Extract root cause
                root_cause = self._identify_root_cause(stderr, stack_trace, language)

                return ErrorInfo(
                    error_type=base_error_type,
                    category=pattern_info['category'],
                    line_number=line_number,
                    column=column,
                    message=stderr.strip(),
                    suggestion=suggestion,
                    stack_trace=stack_trace,
                    root_cause=root_cause,
                    related_symbol=related_symbol,
                )

        # No pattern matched - try generic extraction
        return self._analyze_generic(stderr, language, stack_trace)

    def _extract_stack_trace(self, stderr: str, language: str) -> List[str]:
        """Extract stack trace from error output"""
        stack_trace = []

        if language == 'python':
            # Python traceback format
            in_traceback = False
            for line in stderr.split('\n'):
                if 'Traceback (most recent call last):' in line:
                    in_traceback = True
                    continue
                if in_traceback:
                    if line.strip().startswith('File '):
                        stack_trace.append(line.strip())
                    elif line.strip() and not line.startswith(' '):
                        # End of traceback
                        break

        elif language == 'javascript':
            # Node.js stack trace format
            for line in stderr.split('\n'):
                if re.match(r'\s+at .+', line):
                    stack_trace.append(line.strip())

        return stack_trace

    def _extract_location(self, stderr: str, language: str) -> Tuple[Optional[int], Optional[int]]:
        """Extract line number and column from error"""
        line_number = None
        column = None

        if language == 'python':
            # Python: File "...", line X, in ...
            match = re.search(r'File ".+?", line (\d+)', stderr)
            if match:
                line_number = int(match.group(1))
            # Also check for column
            col_match = re.search(r'\s+\^+\s*$', stderr, re.MULTILINE)
            if col_match:
                # Column is position of caret
                caret_line = col_match.group(0)
                column = caret_line.index('^') if '^' in caret_line else None

        elif language == 'javascript':
            # JavaScript: file:line:column
            match = re.search(r':(\d+):(\d+)', stderr)
            if match:
                line_number = int(match.group(1))
                column = int(match.group(2))
            else:
                # Just line number
                match = re.search(r':(\d+)\)?$', stderr, re.MULTILINE)
                if match:
                    line_number = int(match.group(1))

        elif language == 'bash':
            # Bash: line X:
            match = re.search(r'line (\d+):', stderr)
            if match:
                line_number = int(match.group(1))

        elif language == 'sql':
            # SQL varies by database, try common patterns
            match = re.search(r'(?:LINE|line|Line)\s+(\d+)', stderr)
            if match:
                line_number = int(match.group(1))
            col_match = re.search(r'(?:POSITION|position|Position)\s+(\d+)', stderr)
            if col_match:
                column = int(col_match.group(1))

        return line_number, column

    def _enhance_python_suggestion(self, symbol: Optional[str]) -> Optional[str]:
        """Enhance suggestion for Python NameError with import info"""
        if not symbol:
            return None

        if symbol in self.PYTHON_COMMON_IMPORTS:
            module = self.PYTHON_COMMON_IMPORTS[symbol]
            if module == symbol:
                return f"Add 'import {symbol}' at the top of your file."
            else:
                return f"Add 'from {module} import {symbol}' or 'import {module}' at the top of your file."

        return None

    def _identify_root_cause(
        self,
        stderr: str,
        stack_trace: List[str],
        language: str
    ) -> Optional[str]:
        """Try to identify the root cause of the error"""

        if not stack_trace:
            return None

        # For Python, the last stack frame (before the error) is often the root cause
        if language == 'python' and stack_trace:
            last_frame = stack_trace[-1] if stack_trace else None
            if last_frame:
                # Extract file and line from frame
                match = re.search(r'File "(.+?)", line (\d+), in (\w+)', last_frame)
                if match:
                    file_path = match.group(1)
                    line_num = match.group(2)
                    func_name = match.group(3)
                    return f"Error occurred in function '{func_name}' at line {line_num}"

        return None

    def _analyze_generic(
        self,
        stderr: str,
        language: str,
        stack_trace: List[str]
    ) -> ErrorInfo:
        """Generic error analysis when no specific pattern matches"""

        # Try to extract error type from common formats
        error_type = "Unknown"
        category = ErrorCategory.UNKNOWN

        # Look for common error type patterns
        error_match = re.search(r'(\w+Error):', stderr)
        if error_match:
            error_type = error_match.group(1)
            # Categorize based on name
            if 'Syntax' in error_type:
                category = ErrorCategory.SYNTAX
            elif 'Type' in error_type:
                category = ErrorCategory.TYPE
            elif 'Name' in error_type or 'Reference' in error_type:
                category = ErrorCategory.NAME
            elif 'Import' in error_type or 'Module' in error_type:
                category = ErrorCategory.IMPORT

        line_number, column = self._extract_location(stderr, language)

        return ErrorInfo(
            error_type=error_type,
            category=category,
            line_number=line_number,
            column=column,
            message=stderr.strip(),
            suggestion="Check the error message for details.",
            stack_trace=stack_trace,
        )

    def get_error_summary(self, error_info: ErrorInfo) -> str:
        """Get a human-readable summary of the error"""
        parts = [f"{error_info.error_type}"]

        if error_info.line_number:
            parts.append(f"at line {error_info.line_number}")
            if error_info.column:
                parts.append(f"column {error_info.column}")

        if error_info.related_symbol:
            parts.append(f"('{error_info.related_symbol}')")

        summary = " ".join(parts)

        if error_info.suggestion:
            summary += f"\nSuggestion: {error_info.suggestion}"

        return summary

    def compare_errors(self, error1: ErrorInfo, error2: ErrorInfo) -> bool:
        """Check if two errors are essentially the same"""
        return (
            error1.error_type == error2.error_type and
            error1.category == error2.category and
            error1.related_symbol == error2.related_symbol
        )
