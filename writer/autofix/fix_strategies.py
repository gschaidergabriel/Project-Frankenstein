"""
Fix Strategies
Language-specific fix strategies for auto-fixing code errors
"""

import re
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Type

from .error_analyzer import ErrorInfo, ErrorCategory

logger = logging.getLogger(__name__)


@dataclass
class FixResult:
    """Result of applying a fix"""
    success: bool
    fixed_code: str
    description: str
    confidence: float = 0.0  # 0.0 to 1.0


class FixStrategy(ABC):
    """Base class for fix strategies"""

    # Override in subclasses
    LANGUAGE: str = ""

    @abstractmethod
    def can_fix(self, error_info: ErrorInfo) -> bool:
        """
        Check if this strategy can fix the given error.

        Args:
            error_info: Parsed error information

        Returns:
            True if this strategy can attempt a fix
        """
        pass

    @abstractmethod
    def apply_fix(self, code: str, error_info: ErrorInfo) -> Optional[FixResult]:
        """
        Apply a fix to the code.

        Args:
            code: Original code with error
            error_info: Parsed error information

        Returns:
            FixResult with fixed code, or None if fix failed
        """
        pass

    def get_fix_confidence(self, error_info: ErrorInfo) -> float:
        """
        Get confidence level for fixing this error.

        Returns:
            Confidence between 0.0 and 1.0
        """
        return 0.5


class PythonFixStrategy(FixStrategy):
    """Fix strategies for Python code"""

    LANGUAGE = "python"

    # Common import mappings
    IMPORT_MAP = {
        # NumPy/SciPy
        'np': 'import numpy as np',
        'numpy': 'import numpy',
        'scipy': 'import scipy',

        # Pandas
        'pd': 'import pandas as pd',
        'pandas': 'import pandas',

        # Visualization
        'plt': 'import matplotlib.pyplot as plt',
        'matplotlib': 'import matplotlib',
        'sns': 'import seaborn as sns',
        'seaborn': 'import seaborn',
        'plotly': 'import plotly',

        # Standard library
        'json': 'import json',
        'os': 'import os',
        'sys': 'import sys',
        're': 'import re',
        'math': 'import math',
        'random': 'import random',
        'time': 'import time',
        'datetime': 'from datetime import datetime',
        'timedelta': 'from datetime import timedelta',
        'date': 'from datetime import date',
        'Path': 'from pathlib import Path',
        'pathlib': 'from pathlib import Path',
        'asyncio': 'import asyncio',
        'functools': 'import functools',
        'itertools': 'import itertools',
        'collections': 'import collections',
        'defaultdict': 'from collections import defaultdict',
        'Counter': 'from collections import Counter',
        'namedtuple': 'from collections import namedtuple',
        'deque': 'from collections import deque',
        'copy': 'import copy',
        'deepcopy': 'from copy import deepcopy',
        'logging': 'import logging',
        'argparse': 'import argparse',
        'subprocess': 'import subprocess',
        'threading': 'import threading',
        'multiprocessing': 'import multiprocessing',
        'pickle': 'import pickle',
        'csv': 'import csv',
        'io': 'import io',
        'StringIO': 'from io import StringIO',
        'BytesIO': 'from io import BytesIO',
        'tempfile': 'import tempfile',
        'shutil': 'import shutil',
        'glob': 'import glob',
        'hashlib': 'import hashlib',
        'base64': 'import base64',
        'uuid': 'import uuid',
        'contextlib': 'import contextlib',
        'warnings': 'import warnings',
        'traceback': 'import traceback',
        'inspect': 'import inspect',
        'typing': 'import typing',
        'abc': 'import abc',
        'dataclasses': 'import dataclasses',

        # Typing
        'Optional': 'from typing import Optional',
        'List': 'from typing import List',
        'Dict': 'from typing import Dict',
        'Tuple': 'from typing import Tuple',
        'Any': 'from typing import Any',
        'Union': 'from typing import Union',
        'Callable': 'from typing import Callable',
        'Set': 'from typing import Set',
        'Type': 'from typing import Type',
        'Sequence': 'from typing import Sequence',
        'Mapping': 'from typing import Mapping',
        'Iterable': 'from typing import Iterable',
        'Iterator': 'from typing import Iterator',
        'Generator': 'from typing import Generator',
        'Awaitable': 'from typing import Awaitable',
        'Coroutine': 'from typing import Coroutine',
        'AsyncIterator': 'from typing import AsyncIterator',
        'AsyncGenerator': 'from typing import AsyncGenerator',

        # Dataclasses
        'dataclass': 'from dataclasses import dataclass',
        'field': 'from dataclasses import field',
        'asdict': 'from dataclasses import asdict',
        'astuple': 'from dataclasses import astuple',

        # ABC
        'ABC': 'from abc import ABC',
        'abstractmethod': 'from abc import abstractmethod',

        # Enum
        'Enum': 'from enum import Enum',
        'IntEnum': 'from enum import IntEnum',
        'auto': 'from enum import auto',

        # External libraries
        'requests': 'import requests',
        'httpx': 'import httpx',
        'aiohttp': 'import aiohttp',
        'bs4': 'from bs4 import BeautifulSoup',
        'BeautifulSoup': 'from bs4 import BeautifulSoup',
        'lxml': 'import lxml',
        'yaml': 'import yaml',
        'toml': 'import toml',
        'dotenv': 'from dotenv import load_dotenv',
        'load_dotenv': 'from dotenv import load_dotenv',

        # Machine Learning
        'sklearn': 'import sklearn',
        'tf': 'import tensorflow as tf',
        'tensorflow': 'import tensorflow',
        'torch': 'import torch',
        'nn': 'import torch.nn as nn',
        'cv2': 'import cv2',
        'PIL': 'from PIL import Image',
        'Image': 'from PIL import Image',
    }

    # Attribute corrections
    ATTRIBUTE_CORRECTIONS = {
        # Common typos/mistakes
        ('list', 'append'): [('add', 'append')],
        ('str', 'len'): [('length', 'len()')],
        ('dict', 'keys'): [('key', 'keys')],
        ('dict', 'values'): [('value', 'values')],
        ('dict', 'items'): [('item', 'items')],
    }

    # Syntax fix patterns
    SYNTAX_FIXES = [
        # Missing colon after if/for/while/def/class
        (r'^(\s*)(if|elif|for|while|def|class|with|try|except|finally)\s+(.+[^:])$',
         r'\1\2 \3:'),
        # Missing closing parenthesis
        (r'(\([^)]*$)', r'\1)'),
        # Missing closing bracket
        (r'(\[[^\]]*$)', r'\1]'),
        # Missing closing brace
        (r'(\{[^}]*$)', r'\1}'),
        # f-string without f prefix
        (r'(["\'])\{(\w+)\}\1', r'f\1{\2}\1'),
    ]

    def can_fix(self, error_info: ErrorInfo) -> bool:
        """Check if this strategy can fix the given error"""
        fixable_categories = {
            ErrorCategory.IMPORT,
            ErrorCategory.NAME,
            ErrorCategory.SYNTAX,
            ErrorCategory.TYPE,
            ErrorCategory.ATTRIBUTE,
        }
        return error_info.category in fixable_categories

    def apply_fix(self, code: str, error_info: ErrorInfo) -> Optional[FixResult]:
        """Apply Python-specific fix"""

        if error_info.category == ErrorCategory.IMPORT:
            return self._fix_import(code, error_info)
        elif error_info.category == ErrorCategory.NAME:
            return self._fix_name_error(code, error_info)
        elif error_info.category == ErrorCategory.SYNTAX:
            return self._fix_syntax(code, error_info)
        elif error_info.category == ErrorCategory.TYPE:
            return self._fix_type_error(code, error_info)
        elif error_info.category == ErrorCategory.ATTRIBUTE:
            return self._fix_attribute_error(code, error_info)

        return None

    def _fix_import(self, code: str, error_info: ErrorInfo) -> Optional[FixResult]:
        """Fix missing import errors"""
        symbol = error_info.related_symbol
        if not symbol:
            return None

        # Check if we have an import mapping
        if symbol in self.IMPORT_MAP:
            import_stmt = self.IMPORT_MAP[symbol]

            # Check if import already exists
            if import_stmt in code or self._import_exists(code, import_stmt):
                return None

            # Add import at appropriate location
            fixed_code = self._add_import(code, import_stmt)

            return FixResult(
                success=True,
                fixed_code=fixed_code,
                description=f"Added import: {import_stmt}",
                confidence=0.9
            )

        return None

    def _fix_name_error(self, code: str, error_info: ErrorInfo) -> Optional[FixResult]:
        """Fix undefined name errors"""
        symbol = error_info.related_symbol
        if not symbol:
            return None

        # Try import fix first
        import_result = self._fix_import(code, error_info)
        if import_result:
            return import_result

        # Check for common typos in variable names
        lines = code.split('\n')
        defined_names = self._find_defined_names(code)

        # Find similar names
        similar = self._find_similar_names(symbol, defined_names)
        if similar:
            # Replace the undefined symbol with the closest match
            fixed_code = code.replace(symbol, similar[0])
            return FixResult(
                success=True,
                fixed_code=fixed_code,
                description=f"Replaced '{symbol}' with '{similar[0]}' (possible typo)",
                confidence=0.7
            )

        return None

    def _fix_syntax(self, code: str, error_info: ErrorInfo) -> Optional[FixResult]:
        """Fix syntax errors"""
        lines = code.split('\n')
        line_num = error_info.line_number

        if line_num and 0 < line_num <= len(lines):
            line = lines[line_num - 1]
            original_line = line

            # Try each syntax fix pattern
            for pattern, replacement in self.SYNTAX_FIXES:
                new_line, count = re.subn(pattern, replacement, line, flags=re.MULTILINE)
                if count > 0 and new_line != line:
                    lines[line_num - 1] = new_line
                    return FixResult(
                        success=True,
                        fixed_code='\n'.join(lines),
                        description=f"Fixed syntax at line {line_num}",
                        confidence=0.8
                    )

        # Check for common bracket mismatches
        bracket_fix = self._fix_brackets(code)
        if bracket_fix:
            return bracket_fix

        return None

    def _fix_type_error(self, code: str, error_info: ErrorInfo) -> Optional[FixResult]:
        """Fix type errors"""
        message = error_info.message

        # Common type conversion patterns
        if "can only concatenate str" in message or "must be str, not int" in message:
            # Need str() conversion - this is complex and may need AI
            pass
        elif "argument must be str, not int" in message:
            # Likely needs str conversion
            pass

        return None

    def _fix_attribute_error(self, code: str, error_info: ErrorInfo) -> Optional[FixResult]:
        """Fix attribute errors"""
        # Extract type and attribute from error
        match = re.search(r"'(\w+)' object has no attribute '(\w+)'", error_info.message)
        if not match:
            return None

        obj_type = match.group(1)
        wrong_attr = match.group(2)

        # Check for known corrections
        corrections = self.ATTRIBUTE_CORRECTIONS.get((obj_type, wrong_attr))
        if corrections:
            for wrong, correct in corrections:
                if wrong in code:
                    fixed_code = code.replace(f".{wrong}", f".{correct}")
                    return FixResult(
                        success=True,
                        fixed_code=fixed_code,
                        description=f"Replaced .{wrong} with .{correct}",
                        confidence=0.8
                    )

        return None

    def _add_import(self, code: str, import_stmt: str) -> str:
        """Add import statement at the appropriate location"""
        lines = code.split('\n')

        # Find the best place to insert the import
        insert_idx = 0
        last_import_idx = -1
        in_docstring = False
        docstring_char = None

        for i, line in enumerate(lines):
            stripped = line.strip()

            # Track docstrings
            if not in_docstring:
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    docstring_char = stripped[:3]
                    if not stripped.endswith(docstring_char) or len(stripped) == 3:
                        in_docstring = True
                    continue
            else:
                if docstring_char and docstring_char in stripped:
                    in_docstring = False
                continue

            # Skip comments and empty lines at start
            if not stripped or stripped.startswith('#'):
                continue

            # Track import statements
            if stripped.startswith('import ') or stripped.startswith('from '):
                last_import_idx = i
            elif last_import_idx >= 0:
                # First non-import line after imports
                break

        # Insert after last import, or at beginning if no imports
        if last_import_idx >= 0:
            insert_idx = last_import_idx + 1
        else:
            # Find first non-comment, non-docstring line
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped and not stripped.startswith('#'):
                    if not (stripped.startswith('"""') or stripped.startswith("'''")):
                        insert_idx = i
                        break

        lines.insert(insert_idx, import_stmt)
        return '\n'.join(lines)

    def _import_exists(self, code: str, import_stmt: str) -> bool:
        """Check if an import or equivalent already exists"""
        # Extract module/symbol being imported
        import_match = re.match(r'import\s+(\w+)', import_stmt)
        if import_match:
            module = import_match.group(1)
            if re.search(rf'import\s+{module}\b', code):
                return True
            if re.search(rf'from\s+{module}\b', code):
                return True

        from_match = re.match(r'from\s+([\w.]+)\s+import\s+(.+)', import_stmt)
        if from_match:
            module = from_match.group(1)
            symbols = from_match.group(2)
            if re.search(rf'from\s+{re.escape(module)}\s+import\s+.*{re.escape(symbols)}', code):
                return True
            if re.search(rf'from\s+{re.escape(module)}\s+import\s+\*', code):
                return True

        return False

    def _find_defined_names(self, code: str) -> List[str]:
        """Find all defined variable/function names in code"""
        names = []

        # Function definitions
        for match in re.finditer(r'def\s+(\w+)', code):
            names.append(match.group(1))

        # Class definitions
        for match in re.finditer(r'class\s+(\w+)', code):
            names.append(match.group(1))

        # Variable assignments (simple)
        for match in re.finditer(r'^(\w+)\s*=', code, re.MULTILINE):
            names.append(match.group(1))

        return list(set(names))

    def _find_similar_names(self, name: str, candidates: List[str], threshold: float = 0.8) -> List[str]:
        """Find similar names using edit distance"""
        similar = []

        for candidate in candidates:
            # Simple similarity check
            if name.lower() == candidate.lower():
                similar.append(candidate)
            elif self._levenshtein_ratio(name, candidate) >= threshold:
                similar.append(candidate)

        return similar

    def _levenshtein_ratio(self, s1: str, s2: str) -> float:
        """Calculate similarity ratio using Levenshtein distance"""
        if not s1 or not s2:
            return 0.0

        # Simple implementation
        len1, len2 = len(s1), len(s2)
        if len1 == 0 or len2 == 0:
            return 0.0

        # Create distance matrix
        matrix = [[0] * (len2 + 1) for _ in range(len1 + 1)]

        for i in range(len1 + 1):
            matrix[i][0] = i
        for j in range(len2 + 1):
            matrix[0][j] = j

        for i in range(1, len1 + 1):
            for j in range(1, len2 + 1):
                cost = 0 if s1[i-1] == s2[j-1] else 1
                matrix[i][j] = min(
                    matrix[i-1][j] + 1,      # deletion
                    matrix[i][j-1] + 1,      # insertion
                    matrix[i-1][j-1] + cost  # substitution
                )

        distance = matrix[len1][len2]
        max_len = max(len1, len2)
        return 1.0 - (distance / max_len)

    def _fix_brackets(self, code: str) -> Optional[FixResult]:
        """Fix unmatched brackets"""
        brackets = {'(': ')', '[': ']', '{': '}'}
        reverse_brackets = {v: k for k, v in brackets.items()}

        stack = []
        for char in code:
            if char in brackets:
                stack.append(char)
            elif char in reverse_brackets:
                if stack and stack[-1] == reverse_brackets[char]:
                    stack.pop()
                else:
                    # Mismatched closing bracket
                    return None

        # If stack is not empty, we have unclosed brackets
        if stack:
            closing = ''.join(brackets[b] for b in reversed(stack))
            return FixResult(
                success=True,
                fixed_code=code + closing,
                description=f"Added missing closing bracket(s): {closing}",
                confidence=0.7
            )

        return None

    def get_fix_confidence(self, error_info: ErrorInfo) -> float:
        """Get confidence level for fixing this error"""
        # Higher confidence for import errors with known mappings
        if error_info.category == ErrorCategory.IMPORT:
            if error_info.related_symbol in self.IMPORT_MAP:
                return 0.95
        elif error_info.category == ErrorCategory.NAME:
            if error_info.related_symbol in self.IMPORT_MAP:
                return 0.9
        elif error_info.category == ErrorCategory.SYNTAX:
            return 0.6

        return 0.5


class JavaScriptFixStrategy(FixStrategy):
    """Fix strategies for JavaScript code"""

    LANGUAGE = "javascript"

    # Common import/require mappings
    IMPORT_MAP = {
        # React
        'React': "import React from 'react';",
        'useState': "import { useState } from 'react';",
        'useEffect': "import { useEffect } from 'react';",
        'useContext': "import { useContext } from 'react';",
        'useReducer': "import { useReducer } from 'react';",
        'useCallback': "import { useCallback } from 'react';",
        'useMemo': "import { useMemo } from 'react';",
        'useRef': "import { useRef } from 'react';",

        # Common libraries
        'axios': "import axios from 'axios';",
        '$': "import $ from 'jquery';",
        'jQuery': "import jQuery from 'jquery';",
        '_': "import _ from 'lodash';",
        'lodash': "import _ from 'lodash';",
        'moment': "import moment from 'moment';",
        'dayjs': "import dayjs from 'dayjs';",

        # Node.js built-ins (CommonJS)
        'fs': "const fs = require('fs');",
        'path': "const path = require('path');",
        'http': "const http = require('http');",
        'https': "const https = require('https');",
        'url': "const url = require('url');",
        'os': "const os = require('os');",
        'crypto': "const crypto = require('crypto');",
        'util': "const util = require('util');",
        'events': "const events = require('events');",
        'stream': "const stream = require('stream');",
        'buffer': "const { Buffer } = require('buffer');",
    }

    def can_fix(self, error_info: ErrorInfo) -> bool:
        """Check if this strategy can fix the given error"""
        fixable_categories = {
            ErrorCategory.NAME,
            ErrorCategory.SYNTAX,
            ErrorCategory.TYPE,
        }
        return error_info.category in fixable_categories

    def apply_fix(self, code: str, error_info: ErrorInfo) -> Optional[FixResult]:
        """Apply JavaScript-specific fix"""

        if error_info.category == ErrorCategory.NAME:
            return self._fix_reference_error(code, error_info)
        elif error_info.category == ErrorCategory.SYNTAX:
            return self._fix_syntax(code, error_info)
        elif error_info.category == ErrorCategory.TYPE:
            return self._fix_type_error(code, error_info)

        return None

    def _fix_reference_error(self, code: str, error_info: ErrorInfo) -> Optional[FixResult]:
        """Fix undefined reference errors"""
        symbol = error_info.related_symbol
        if not symbol:
            return None

        # Check if we have an import mapping
        if symbol in self.IMPORT_MAP:
            import_stmt = self.IMPORT_MAP[symbol]

            # Check if import already exists
            if import_stmt in code:
                return None

            # Add import at the beginning
            fixed_code = self._add_import(code, import_stmt)

            return FixResult(
                success=True,
                fixed_code=fixed_code,
                description=f"Added import: {import_stmt}",
                confidence=0.9
            )

        return None

    def _fix_syntax(self, code: str, error_info: ErrorInfo) -> Optional[FixResult]:
        """Fix JavaScript syntax errors"""
        lines = code.split('\n')
        line_num = error_info.line_number

        # Common fixes
        fixes_applied = []
        fixed_code = code

        # Missing semicolons (add if not in a block statement)
        # This is tricky in JS due to ASI, so we're conservative

        # Fix missing closing brackets/braces
        bracket_fix = self._fix_brackets(code)
        if bracket_fix:
            return bracket_fix

        # Check for common issues
        if "Unexpected token" in error_info.message:
            # Try to identify and fix the issue
            pass

        return None

    def _fix_type_error(self, code: str, error_info: ErrorInfo) -> Optional[FixResult]:
        """Fix JavaScript type errors"""
        message = error_info.message

        # Cannot read property of undefined/null
        if "Cannot read propert" in message and ("undefined" in message or "null" in message):
            # This usually requires optional chaining (?.) or null checks
            # Complex fix that may need AI assistance
            pass

        return None

    def _add_import(self, code: str, import_stmt: str) -> str:
        """Add import at the appropriate location"""
        lines = code.split('\n')

        # Find the best insertion point
        insert_idx = 0
        last_import_idx = -1

        for i, line in enumerate(lines):
            stripped = line.strip()

            # Skip 'use strict'
            if "'use strict'" in stripped or '"use strict"' in stripped:
                insert_idx = i + 1
                continue

            # Track imports
            if stripped.startswith('import ') or stripped.startswith('const ') and 'require(' in stripped:
                last_import_idx = i
            elif last_import_idx >= 0:
                break

        if last_import_idx >= 0:
            insert_idx = last_import_idx + 1

        lines.insert(insert_idx, import_stmt)
        return '\n'.join(lines)

    def _fix_brackets(self, code: str) -> Optional[FixResult]:
        """Fix unmatched brackets in JavaScript"""
        brackets = {'(': ')', '[': ']', '{': '}'}
        reverse_brackets = {v: k for k, v in brackets.items()}

        # Track brackets outside of strings
        stack = []
        in_string = False
        string_char = None
        escape_next = False

        for char in code:
            if escape_next:
                escape_next = False
                continue

            if char == '\\':
                escape_next = True
                continue

            if char in '"\'`':
                if not in_string:
                    in_string = True
                    string_char = char
                elif char == string_char:
                    in_string = False
                    string_char = None
                continue

            if in_string:
                continue

            if char in brackets:
                stack.append(char)
            elif char in reverse_brackets:
                if stack and stack[-1] == reverse_brackets[char]:
                    stack.pop()

        if stack:
            closing = ''.join(brackets[b] for b in reversed(stack))
            return FixResult(
                success=True,
                fixed_code=code + closing,
                description=f"Added missing closing bracket(s): {closing}",
                confidence=0.7
            )

        return None

    def get_fix_confidence(self, error_info: ErrorInfo) -> float:
        """Get confidence level for fixing this error"""
        if error_info.category == ErrorCategory.NAME:
            if error_info.related_symbol in self.IMPORT_MAP:
                return 0.9
        return 0.5


class BashFixStrategy(FixStrategy):
    """Fix strategies for Bash scripts"""

    LANGUAGE = "bash"

    def can_fix(self, error_info: ErrorInfo) -> bool:
        """Check if this strategy can fix the given error"""
        fixable_categories = {
            ErrorCategory.SYNTAX,
            ErrorCategory.NAME,
            ErrorCategory.PERMISSION,
        }
        return error_info.category in fixable_categories

    def apply_fix(self, code: str, error_info: ErrorInfo) -> Optional[FixResult]:
        """Apply Bash-specific fix"""

        if error_info.category == ErrorCategory.SYNTAX:
            return self._fix_syntax(code, error_info)
        elif error_info.category == ErrorCategory.NAME:
            return self._fix_command_not_found(code, error_info)
        elif error_info.category == ErrorCategory.PERMISSION:
            return self._fix_permission(code, error_info)

        return None

    def _fix_syntax(self, code: str, error_info: ErrorInfo) -> Optional[FixResult]:
        """Fix Bash syntax errors"""
        lines = code.split('\n')

        # Common syntax fixes
        fixed = False
        fixed_lines = []

        for i, line in enumerate(lines):
            new_line = line

            # Fix missing 'then' after 'if'
            if re.match(r'^\s*if\s+.+[^;]\s*$', line) and not line.strip().endswith('then'):
                # Check if next line isn't 'then'
                if i + 1 < len(lines) and not lines[i + 1].strip().startswith('then'):
                    new_line = line + '; then'
                    fixed = True

            # Fix missing 'do' after 'for' or 'while'
            if re.match(r'^\s*(for|while)\s+.+[^;]\s*$', line) and not line.strip().endswith('do'):
                if i + 1 < len(lines) and not lines[i + 1].strip().startswith('do'):
                    new_line = line + '; do'
                    fixed = True

            # Fix variable references without braces in certain contexts
            # e.g., $varname/ -> ${varname}/
            new_line = re.sub(r'\$(\w+)([^a-zA-Z0-9_\s])', r'${\1}\2', new_line)
            if new_line != line:
                fixed = True

            fixed_lines.append(new_line)

        if fixed:
            return FixResult(
                success=True,
                fixed_code='\n'.join(fixed_lines),
                description="Fixed Bash syntax issues",
                confidence=0.7
            )

        return None

    def _fix_command_not_found(self, code: str, error_info: ErrorInfo) -> Optional[FixResult]:
        """Fix command not found errors"""
        # Common aliases/alternatives
        alternatives = {
            'python': 'python3',
            'pip': 'pip3',
            'node': 'nodejs',
        }

        command = error_info.related_symbol
        if command and command in alternatives:
            alt = alternatives[command]
            fixed_code = code.replace(command, alt)
            return FixResult(
                success=True,
                fixed_code=fixed_code,
                description=f"Replaced '{command}' with '{alt}'",
                confidence=0.6
            )

        return None

    def _fix_permission(self, code: str, error_info: ErrorInfo) -> Optional[FixResult]:
        """Suggest permission fixes"""
        # We can't actually fix permissions, but we can add chmod
        # This is informational only
        return None

    def get_fix_confidence(self, error_info: ErrorInfo) -> float:
        """Get confidence level for fixing this error"""
        if error_info.category == ErrorCategory.SYNTAX:
            return 0.6
        return 0.4


class FixStrategyRegistry:
    """Registry for fix strategies"""

    def __init__(self):
        self._strategies: Dict[str, List[FixStrategy]] = {}

        # Register default strategies
        self.register(PythonFixStrategy())
        self.register(JavaScriptFixStrategy())
        self.register(BashFixStrategy())

    def register(self, strategy: FixStrategy) -> None:
        """Register a fix strategy"""
        lang = strategy.LANGUAGE.lower()
        if lang not in self._strategies:
            self._strategies[lang] = []
        self._strategies[lang].append(strategy)

    def get_strategies(self, language: str) -> List[FixStrategy]:
        """Get all strategies for a language"""
        return self._strategies.get(language.lower(), [])

    def find_fix(
        self,
        code: str,
        error_info: ErrorInfo,
        language: str
    ) -> Optional[FixResult]:
        """Find and apply the best fix for an error"""
        strategies = self.get_strategies(language)

        best_fix = None
        best_confidence = 0.0

        for strategy in strategies:
            if strategy.can_fix(error_info):
                confidence = strategy.get_fix_confidence(error_info)
                if confidence > best_confidence:
                    fix_result = strategy.apply_fix(code, error_info)
                    if fix_result:
                        fix_result.confidence = confidence
                        best_fix = fix_result
                        best_confidence = confidence

        return best_fix


# Global registry instance
_registry = FixStrategyRegistry()


def get_fix_strategy_registry() -> FixStrategyRegistry:
    """Get the global fix strategy registry"""
    return _registry
