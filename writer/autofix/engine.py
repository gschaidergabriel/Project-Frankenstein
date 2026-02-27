"""
Auto-Fix Engine
Autonomous code error correction
"""

import asyncio
import hashlib
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable, Set
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from writer.sandbox.executor import SandboxExecutor, ExecutionResult
from writer.ai.bridge import FrankBridge


@dataclass
class FixAttempt:
    """A single fix attempt"""
    attempt_num: int
    error_type: str
    error_message: str
    fix_applied: str
    code_before: str
    code_after: str
    success: bool
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class AutoFixResult:
    """Result of auto-fix session"""
    success: bool
    final_code: str
    attempts: List[FixAttempt] = field(default_factory=list)
    visual_output: Optional[bytes] = None
    error: Optional[str] = None
    requires_user_input: bool = False


class AutoFixEngine:
    """Autonomous code error fixing"""

    # Common error patterns and fixes
    ERROR_PATTERNS = {
        'python': {
            'NameError': {
                'missing_import': r"name '(\w+)' is not defined",
            },
            'ModuleNotFoundError': {
                'missing_module': r"No module named '(\w+)'",
            },
            'SyntaxError': {
                'syntax': r"(.+)",
            },
            'IndentationError': {
                'indent': r"(.+)",
            },
            'TypeError': {
                'type_mismatch': r"(.+)",
            },
            'AttributeError': {
                'wrong_attribute': r"'(\w+)' object has no attribute '(\w+)'",
            },
            'ImportError': {
                'import_error': r"cannot import name '(\w+)'",
            },
        },
        'javascript': {
            'ReferenceError': {
                'undefined': r"(\w+) is not defined",
            },
            'SyntaxError': {
                'syntax': r"(.+)",
            },
            'TypeError': {
                'type_error': r"(.+)",
            },
        }
    }

    # Common import mappings
    IMPORT_MAP = {
        'np': 'import numpy as np',
        'numpy': 'import numpy',
        'pd': 'import pandas as pd',
        'pandas': 'import pandas',
        'plt': 'import matplotlib.pyplot as plt',
        'matplotlib': 'import matplotlib',
        'sns': 'import seaborn as sns',
        'seaborn': 'import seaborn',
        'json': 'import json',
        'os': 'import os',
        'sys': 'import sys',
        're': 'import re',
        'datetime': 'from datetime import datetime',
        'Path': 'from pathlib import Path',
        'pathlib': 'from pathlib import Path',
        'requests': 'import requests',
        'asyncio': 'import asyncio',
        'typing': 'from typing import *',
    }

    def __init__(
        self,
        sandbox: SandboxExecutor,
        frank_bridge: FrankBridge,
        max_attempts: int = 5,
        on_progress: Callable = None
    ):
        self.sandbox = sandbox
        self.frank = frank_bridge
        self.max_attempts = max_attempts
        self.on_progress = on_progress or (lambda *args: None)
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._seen_code_hashes: Set[str] = set()

    def _normalize_code(self, code: str) -> str:
        """Normalize code by removing all whitespace for comparison"""
        return re.sub(r'\s+', '', code)

    def _code_hash(self, code: str) -> str:
        """Generate hash of normalized code to detect identical behavior"""
        normalized = self._normalize_code(code)
        return hashlib.sha256(normalized.encode()).hexdigest()

    async def execute_with_autofix(
        self,
        code: str,
        language: str
    ) -> AutoFixResult:
        """Execute code and auto-fix errors"""

        attempts = []
        current_code = code
        # Reset seen hashes for this execution session
        self._seen_code_hashes = {self._code_hash(code)}

        for attempt_num in range(1, self.max_attempts + 1):
            # Notify progress
            self.on_progress('attempt_start', {
                'attempt': attempt_num,
                'max_attempts': self.max_attempts
            })

            # Execute code
            result = await self.sandbox.execute(current_code, language)

            # Check success
            if result.success:
                self.on_progress('success', {'attempt': attempt_num})
                # Mark the last attempt as successful if there were any
                if attempts:
                    attempts[-1].success = True
                return AutoFixResult(
                    success=True,
                    final_code=current_code,
                    attempts=attempts,
                    visual_output=result.visual_output
                )

            # If no output but also no error, might still be okay
            if not result.stderr and not result.visual_output:
                # Code ran but produced no output
                if result.stdout:
                    # Mark the last attempt as successful if there were any
                    if attempts:
                        attempts[-1].success = True
                    return AutoFixResult(
                        success=True,
                        final_code=current_code,
                        attempts=attempts
                    )

            # Try to fix error
            fix_result = await self._try_fix(
                current_code,
                result,
                language,
                attempts
            )

            if fix_result is None:
                # Cannot fix
                self.on_progress('cannot_fix', {
                    'error': result.stderr,
                    'attempt': attempt_num
                })
                return AutoFixResult(
                    success=False,
                    final_code=current_code,
                    attempts=attempts,
                    error=result.stderr,
                    requires_user_input=True
                )

            # Apply fix
            attempt = FixAttempt(
                attempt_num=attempt_num,
                error_type=result.error_type or "Unknown",
                error_message=result.stderr,
                fix_applied=fix_result['description'],
                code_before=current_code,
                code_after=fix_result['code'],
                success=False  # Will update if next iteration succeeds
            )
            attempts.append(attempt)

            current_code = fix_result['code']

            self.on_progress('fix_applied', {
                'attempt': attempt_num,
                'fix': fix_result['description']
            })

        # Max attempts reached
        return AutoFixResult(
            success=False,
            final_code=current_code,
            attempts=attempts,
            error=f"Could not fix after {self.max_attempts} attempts",
            requires_user_input=True
        )

    async def _try_fix(
        self,
        code: str,
        result: ExecutionResult,
        language: str,
        previous_attempts: List[FixAttempt]
    ) -> Optional[Dict]:
        """Try to fix an error"""

        error = result.stderr
        error_type = result.error_type

        # Try pattern-based fixes first
        pattern_fix = self._try_pattern_fix(code, error, error_type, language)
        if pattern_fix:
            return pattern_fix

        # Try Frank AI fix
        ai_fix = await self._try_ai_fix(code, error, language, previous_attempts)
        if ai_fix:
            return ai_fix

        return None

    def _try_pattern_fix(
        self,
        code: str,
        error: str,
        error_type: str,
        language: str
    ) -> Optional[Dict]:
        """Try to fix using known patterns"""

        if language not in self.ERROR_PATTERNS:
            return None

        patterns = self.ERROR_PATTERNS[language]

        if error_type not in patterns:
            return None

        for fix_type, pattern in patterns[error_type].items():
            match = re.search(pattern, error)
            if not match:
                continue

            if fix_type == 'missing_import':
                var_name = match.group(1)
                if var_name in self.IMPORT_MAP:
                    import_stmt = self.IMPORT_MAP[var_name]
                    # Check if import already exists to prevent duplicates
                    if import_stmt in code or self._import_exists(code, import_stmt):
                        continue  # Skip, import already present
                    # Add import at the beginning
                    lines = code.split('\n')
                    # Find first non-comment, non-empty line
                    insert_idx = 0
                    for i, line in enumerate(lines):
                        if line.strip() and not line.strip().startswith('#'):
                            insert_idx = i
                            break

                    lines.insert(insert_idx, import_stmt)
                    return {
                        'code': '\n'.join(lines),
                        'description': f"Added import: {import_stmt}"
                    }

            elif fix_type == 'undefined':
                # JavaScript undefined variable handler
                var_name = match.group(1)
                # Check if it's a common library that should be imported/required
                js_imports = {
                    'React': "import React from 'react';",
                    'useState': "import { useState } from 'react';",
                    'useEffect': "import { useEffect } from 'react';",
                    'axios': "import axios from 'axios';",
                    'fetch': '',  # fetch is built-in, likely a different issue
                    '$': "import $ from 'jquery';",
                    'jQuery': "import jQuery from 'jquery';",
                    '_': "import _ from 'lodash';",
                    'lodash': "import _ from 'lodash';",
                    'moment': "import moment from 'moment';",
                }
                if var_name in js_imports and js_imports[var_name]:
                    import_stmt = js_imports[var_name]
                    # Check if import already exists
                    if import_stmt in code:
                        continue
                    lines = code.split('\n')
                    # Insert at beginning (after 'use strict' if present)
                    insert_idx = 0
                    for i, line in enumerate(lines):
                        if "'use strict'" in line or '"use strict"' in line:
                            insert_idx = i + 1
                            break
                    lines.insert(insert_idx, import_stmt)
                    return {
                        'code': '\n'.join(lines),
                        'description': f"Added import: {import_stmt}"
                    }

            elif fix_type == 'missing_module':
                module = match.group(1)
                # Can't auto-install, but can suggest
                return None  # Let AI handle it

        return None

    def _import_exists(self, code: str, import_stmt: str) -> bool:
        """Check if an import statement or equivalent already exists in code"""
        # Extract the module/symbol being imported
        # Handle 'import X' and 'import X as Y'
        import_match = re.match(r'import\s+(\w+)', import_stmt)
        if import_match:
            module = import_match.group(1)
            # Check for various import patterns
            if re.search(rf'import\s+{module}\b', code):
                return True
            if re.search(rf'from\s+{module}\b', code):
                return True

        # Handle 'from X import Y'
        from_match = re.match(r'from\s+(\w+)\s+import\s+(.+)', import_stmt)
        if from_match:
            module = from_match.group(1)
            symbols = from_match.group(2)
            # Check if module is already imported
            if re.search(rf'from\s+{module}\s+import\s+.*{symbols}', code):
                return True
            # Check for wildcard import
            if re.search(rf'from\s+{module}\s+import\s+\*', code):
                return True

        return False

    async def _try_ai_fix(
        self,
        code: str,
        error: str,
        language: str,
        previous_attempts: List[FixAttempt]
    ) -> Optional[Dict]:
        """Try to fix using Frank AI"""

        # Build context from previous attempts
        context = ""
        if previous_attempts:
            context = "\n\nPreviously attempted fixes:\n"
            for attempt in previous_attempts[-3:]:  # Last 3 attempts
                context += f"- {attempt.fix_applied} (failed)\n"

        # Run blocking I/O in thread pool to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            self._executor,
            lambda: self.frank.fix_code(code, error + context, language)
        )

        if response.success and response.content:
            new_code = response.content
            # Compute hash of new code to detect infinite loops
            new_hash = self._code_hash(new_code)

            # Check if we've seen this code before (whitespace-only changes)
            if new_hash in self._seen_code_hashes:
                # This code is functionally identical to a previous version
                # Reject to prevent infinite loop
                return None

            # Also check basic string comparison for obvious duplicates
            if new_code.strip() == code.strip():
                return None

            # Track this code version
            self._seen_code_hashes.add(new_hash)

            return {
                'code': new_code,
                'description': "AI-generated fix"
            }

        return None

    def get_fix_summary(self, result: AutoFixResult) -> str:
        """Get human-readable summary of fix attempts"""

        if result.success:
            if not result.attempts:
                return "Code ran successfully on first try."
            else:
                fixes = [a.fix_applied for a in result.attempts]
                return f"Successful after {len(result.attempts)} fix(es): {', '.join(fixes)}"
        else:
            return f"Failed after {len(result.attempts)} attempts. Last error: {result.error}"
