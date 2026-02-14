#!/usr/bin/env python3
"""
Code Analyzer Sensor - Finds real issues in the codebase via AST
"""

import ast
import os
import re
from typing import List, Dict, Any, Set
from pathlib import Path
from datetime import datetime
import logging

from .base import BaseSensor
from ..core.wave import Wave

LOG = logging.getLogger("genesis.sensors.code_analyzer")

try:
    from config.paths import AICORE_ROOT as _CODE_SCAN_ROOT
    SCAN_ROOT = _CODE_SCAN_ROOT
except ImportError:
    SCAN_ROOT = Path("/home/ai-core-node/aicore/opt/aicore/")
FILES_PER_TICK = 5
MAX_FUNC_LINES = 80
MAX_FILE_LINES = 500
MAX_NESTED_TRY = 2


class CodeAnalyzer(BaseSensor):
    """
    Scans Python source files incrementally using AST.
    Finds real code issues: long functions, bare excepts, TODOs, etc.
    """

    def __init__(self):
        super().__init__("code_analyzer")
        self._file_list: List[Path] = []
        self._scan_index: int = 0
        self._mtime_cache: Dict[str, float] = {}
        self._findings: Dict[str, Dict] = {}  # key → finding
        self._emitted_keys: Set[str] = set()
        self._last_issue_count: int = 0
        self._files_refreshed_at: float = 0

    def sense(self) -> List[Wave]:
        """Scan a batch of files and emit waves based on findings."""
        waves = []

        try:
            self._refresh_file_list()
            new_findings = self._scan_batch()

            current_count = len(self._findings)
            prev_count = self._last_issue_count

            if new_findings > 0:
                waves.append(Wave(
                    target_field="curiosity",
                    amplitude=min(0.4, 0.1 * new_findings),
                    decay=0.06,
                    source=self.name,
                    metadata={"new_issues": new_findings, "total": current_count},
                ))

            bare_excepts = sum(
                1 for f in self._findings.values() if f.get("check") == "bare_except"
            )
            if bare_excepts > 5:
                waves.append(Wave(
                    target_field="concern",
                    amplitude=min(0.3, 0.05 * bare_excepts),
                    decay=0.04,
                    source=self.name,
                    metadata={"bare_excepts": bare_excepts},
                ))

            if prev_count > 0 and current_count < prev_count:
                waves.append(Wave(
                    target_field="satisfaction",
                    amplitude=0.2,
                    decay=0.03,
                    source=self.name,
                    metadata={"issues_resolved": prev_count - current_count},
                ))

            self._last_issue_count = current_count

        except Exception as e:
            LOG.warning(f"Code analyzer sensing error: {e}")

        return waves

    def get_observations(self) -> List[Dict[str, Any]]:
        """Return un-emitted findings as observations for the soup."""
        observations = []
        for key, finding in self._findings.items():
            if key in self._emitted_keys:
                continue
            obs = {
                "type": finding["obs_type"],
                "target": finding["target"],
                "approach": "refactoring",
                "origin": "code_analysis",
                "strength": finding.get("strength", 0.5),
                "novelty": 0.6,
                "risk": 0.2,
                "impact": finding.get("impact", 0.5),
            }
            observations.append(obs)
            self._emitted_keys.add(key)
        return observations

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _refresh_file_list(self):
        """Rebuild list of .py files periodically (every 60 ticks)."""
        if self._file_list and (self.sense_count - self._files_refreshed_at) < 60:
            return
        try:
            self._file_list = sorted(
                p for p in SCAN_ROOT.rglob("*.py")
                if ".venv" not in p.parts
                and "__pycache__" not in p.parts
                and "node_modules" not in p.parts
            )
            self._files_refreshed_at = self.sense_count
            if self._scan_index >= len(self._file_list):
                self._scan_index = 0
        except Exception as e:
            LOG.warning(f"File list refresh error: {e}")

    def _scan_batch(self) -> int:
        """Scan next FILES_PER_TICK files. Returns count of new findings."""
        if not self._file_list:
            return 0

        new_count = 0
        for _ in range(FILES_PER_TICK):
            if self._scan_index >= len(self._file_list):
                self._scan_index = 0
            fp = self._file_list[self._scan_index]
            self._scan_index += 1

            try:
                mtime = fp.stat().st_mtime
            except OSError:
                continue

            key = str(fp)
            if self._mtime_cache.get(key) == mtime:
                continue
            self._mtime_cache[key] = mtime

            # Remove old findings for this file before re-scanning
            stale = [k for k in self._findings if k.startswith(key + ":")]
            for k in stale:
                del self._findings[k]
                self._emitted_keys.discard(k)

            new_count += self._analyze_file(fp)

        return new_count

    def _analyze_file(self, fp: Path) -> int:
        """Run all checks on one file. Returns count of new findings."""
        try:
            source = fp.read_text(errors="replace")
        except Exception:
            return 0

        lines = source.split("\n")
        rel = str(fp.relative_to(SCAN_ROOT))
        count = 0

        # Check 1: File too long
        if len(lines) > MAX_FILE_LINES:
            k = f"{fp}:file_too_long"
            if k not in self._findings:
                self._findings[k] = {
                    "check": "file_too_long",
                    "obs_type": "optimization",
                    "target": rel,
                    "strength": min(1.0, len(lines) / 1000),
                    "impact": 0.4,
                    "detail": f"{len(lines)} lines",
                }
                count += 1

        # Check 2: TODO/FIXME/HACK comments
        for i, line in enumerate(lines, 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                upper = stripped.upper()
                if any(tag in upper for tag in ("TODO", "FIXME", "HACK", "XXX")):
                    k = f"{fp}:todo:{i}"
                    if k not in self._findings:
                        self._findings[k] = {
                            "check": "todo_comment",
                            "obs_type": "fix",
                            "target": f"{rel}:{i}",
                            "strength": 0.3,
                            "impact": 0.3,
                            "detail": stripped[:80],
                        }
                        count += 1

        # AST-based checks
        try:
            tree = ast.parse(source, filename=str(fp))
        except SyntaxError:
            return count

        count += self._check_functions(tree, fp, rel)
        count += self._check_bare_excepts(tree, fp, rel)
        count += self._check_nested_try(tree, fp, rel)
        count += self._check_duplicate_names(tree, fp, rel)

        return count

    def _check_functions(self, tree: ast.AST, fp: Path, rel: str) -> int:
        """Check for overly long functions."""
        count = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if hasattr(node, "end_lineno") and node.end_lineno:
                    length = node.end_lineno - node.lineno
                    if length > MAX_FUNC_LINES:
                        k = f"{fp}:long_func:{node.name}"
                        if k not in self._findings:
                            self._findings[k] = {
                                "check": "long_function",
                                "obs_type": "optimization",
                                "target": f"{rel}:{node.name}",
                                "strength": min(1.0, length / 200),
                                "impact": 0.5,
                                "detail": f"{node.name}() is {length} lines",
                            }
                            count += 1
        return count

    def _check_bare_excepts(self, tree: ast.AST, fp: Path, rel: str) -> int:
        """Check for bare except clauses (no exception type)."""
        count = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    k = f"{fp}:bare_except:{node.lineno}"
                    if k not in self._findings:
                        self._findings[k] = {
                            "check": "bare_except",
                            "obs_type": "fix",
                            "target": f"{rel}:{node.lineno}",
                            "strength": 0.5,
                            "impact": 0.5,
                            "detail": f"Bare except at line {node.lineno}",
                        }
                        count += 1
        return count

    def _check_nested_try(self, tree: ast.AST, fp: Path, rel: str) -> int:
        """Check for deeply nested try/except blocks."""
        count = 0

        def _walk_try(node: ast.AST, depth: int, parent_func: str):
            nonlocal count
            for child in ast.iter_child_nodes(node):
                func_name = parent_func
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_name = child.name
                if isinstance(child, ast.Try):
                    new_depth = depth + 1
                    if new_depth > MAX_NESTED_TRY:
                        k = f"{fp}:nested_try:{child.lineno}"
                        if k not in self._findings:
                            self._findings[k] = {
                                "check": "nested_try",
                                "obs_type": "optimization",
                                "target": f"{rel}:{func_name or 'module'}",
                                "strength": 0.4,
                                "impact": 0.4,
                                "detail": f"try nesting depth {new_depth} at line {child.lineno}",
                            }
                            count += 1
                    _walk_try(child, new_depth, func_name)
                else:
                    _walk_try(child, depth, func_name)

        _walk_try(tree, 0, "")
        return count

    def _check_duplicate_names(self, tree: ast.AST, fp: Path, rel: str) -> int:
        """Check for duplicate function names at module level."""
        count = 0
        seen: Dict[str, int] = {}
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
                if name in seen:
                    k = f"{fp}:dup_func:{name}"
                    if k not in self._findings:
                        self._findings[k] = {
                            "check": "duplicate_name",
                            "obs_type": "fix",
                            "target": f"{rel}:{name}",
                            "strength": 0.6,
                            "impact": 0.6,
                            "detail": f"Duplicate function '{name}' (lines {seen[name]} and {node.lineno})",
                        }
                        count += 1
                else:
                    seen[name] = node.lineno
        return count
