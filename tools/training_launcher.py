#!/usr/bin/env python3
"""
E-CPMM Training Launcher with Auto-Analysis
============================================
Starts training and generates detailed report on exit.
Enhanced with detailed tool ratings (1-10), function analysis,
connections, and performance assessment.
"""

import ast
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Paths
try:
    from config.paths import TRAINING_LOG_DIR as LOG_DIR, SANDBOX_DIR as SANDBOX_BASE_DIR, AICORE_ROOT
    DAEMON_SCRIPT = AICORE_ROOT / "ext" / "autonomous_training_daemon.py"
except ImportError:
    _tl_project_root = Path(__file__).resolve().parents[3]  # tools/ -> opt/aicore -> opt -> aicore
    LOG_DIR = _tl_project_root / "logs" / "training"
    SANDBOX_BASE_DIR = _tl_project_root / "sandbox"
    AICORE_ROOT = Path(__file__).resolve().parents[1]  # tools/ -> opt/aicore
    DAEMON_SCRIPT = AICORE_ROOT / "ext" / "autonomous_training_daemon.py"


class ToolAnalyzer:
    """Analyzes Python tool files for detailed assessment."""

    def __init__(self, tool_path: Path):
        self.tool_path = tool_path
        self.code = ""
        self.ast_tree = None
        self.parse_error = None

        try:
            self.code = tool_path.read_text()
            self.ast_tree = ast.parse(self.code)
        except SyntaxError as e:
            self.parse_error = str(e)
        except Exception as e:
            self.parse_error = str(e)

    def get_functions(self) -> list:
        """Extract all function definitions with docstrings."""
        functions = []
        if not self.ast_tree:
            return functions

        for node in ast.walk(self.ast_tree):
            if isinstance(node, ast.FunctionDef):
                doc = ast.get_docstring(node) or "No documentation"
                args = [arg.arg for arg in node.args.args]
                functions.append({
                    'name': node.name,
                    'args': args,
                    'docstring': doc[:200],
                    'line': node.lineno
                })
        return functions

    def get_classes(self) -> list:
        """Extract all class definitions."""
        classes = []
        if not self.ast_tree:
            return classes

        for node in ast.walk(self.ast_tree):
            if isinstance(node, ast.ClassDef):
                doc = ast.get_docstring(node) or "No documentation"
                methods = [n.name for n in node.body if isinstance(n, ast.FunctionDef)]
                classes.append({
                    'name': node.name,
                    'methods': methods,
                    'docstring': doc[:200],
                    'line': node.lineno
                })
        return classes

    def get_imports(self) -> list:
        """Extract all imports."""
        imports = []
        if not self.ast_tree:
            return imports

        for node in ast.walk(self.ast_tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imports.append(module)
        return list(set(imports))

    def get_external_connections(self) -> dict:
        """Detect external connections (HTTP, files, databases, etc.)."""
        connections = {
            'http_calls': [],
            'file_operations': [],
            'database': [],
            'subprocess': [],
            'sockets': []
        }

        if not self.code:
            return connections

        # HTTP patterns
        http_patterns = re.findall(r'(requests\.(get|post|put|delete)|urllib|http\.client|aiohttp)', self.code)
        connections['http_calls'] = list(set([p[0] if isinstance(p, tuple) else p for p in http_patterns]))

        # File operations
        file_patterns = re.findall(r'(open\s*\(|Path\(|os\.path|shutil\.|pathlib)', self.code)
        connections['file_operations'] = list(set(file_patterns))

        # Database
        db_patterns = re.findall(r'(sqlite3|psycopg|mysql|pymongo|redis|sqlalchemy)', self.code)
        connections['database'] = list(set(db_patterns))

        # Subprocess
        if 'subprocess' in self.code:
            connections['subprocess'] = ['subprocess']

        # Sockets
        if 'socket' in self.code:
            connections['sockets'] = ['socket']

        return connections

    def calculate_complexity(self) -> int:
        """Calculate code complexity score (1-10)."""
        if not self.ast_tree:
            return 0

        complexity = 0

        for node in ast.walk(self.ast_tree):
            # Control flow adds complexity
            if isinstance(node, (ast.If, ast.For, ast.While, ast.Try)):
                complexity += 1
            # Nested functions add complexity
            elif isinstance(node, ast.FunctionDef):
                complexity += 0.5
            # Classes add complexity
            elif isinstance(node, ast.ClassDef):
                complexity += 2
            # Comprehensions add complexity
            elif isinstance(node, (ast.ListComp, ast.DictComp, ast.SetComp)):
                complexity += 0.5

        # Normalize to 1-10 scale
        return min(10, max(1, int(complexity / 3) + 1))

    def calculate_rating(self, proposal: dict = None) -> dict:
        """Calculate overall rating (1-10) based on multiple factors."""
        rating = {
            'syntax': 0,
            'completeness': 0,
            'complexity': 0,
            'documentation': 0,
            'execution': 0,
            'connections': 0,
            'overall': 0,
            'details': []
        }

        # Syntax score (0-10)
        if self.ast_tree:
            rating['syntax'] = 10
            rating['details'].append("Syntactically valid Python code")
        else:
            rating['syntax'] = 0
            rating['details'].append(f"Syntax error: {self.parse_error}")

        # Completeness score (0-10)
        functions = self.get_functions()
        classes = self.get_classes()

        if functions or classes:
            has_main = any(f['name'] == 'main' for f in functions)
            has_docstrings = sum(1 for f in functions if f['docstring'] != "No documentation")

            completeness = 5
            if has_main:
                completeness += 2
            if has_docstrings > 0:
                completeness += min(3, has_docstrings)
            rating['completeness'] = min(10, completeness)
            rating['details'].append(f"{len(functions)} functions, {len(classes)} classes defined")
        else:
            rating['completeness'] = 3
            rating['details'].append("No functions or classes found")

        # Complexity score (1-10, higher is more sophisticated)
        rating['complexity'] = self.calculate_complexity()

        # Documentation score (0-10)
        doc_count = sum(1 for f in functions if f['docstring'] != "No documentation")
        if functions:
            rating['documentation'] = min(10, int((doc_count / len(functions)) * 10))
        else:
            rating['documentation'] = 0

        # Execution score from proposal
        if proposal:
            if proposal.get('execution_success'):
                rating['execution'] = 10
                rating['details'].append("Executes successfully")
            elif proposal.get('syntax_valid'):
                rating['execution'] = 5
                rating['details'].append("Valid syntax but execution failed")
            else:
                rating['execution'] = 0
                rating['details'].append("Does not execute")

        # Connections score (0-10, based on integration capability)
        connections = self.get_external_connections()
        conn_count = sum(len(v) for v in connections.values())
        rating['connections'] = min(10, conn_count * 2)

        # Calculate overall rating (weighted average)
        weights = {
            'syntax': 0.25,
            'execution': 0.25,
            'completeness': 0.20,
            'documentation': 0.10,
            'complexity': 0.10,
            'connections': 0.10
        }

        rating['overall'] = sum(
            rating[k] * w for k, w in weights.items()
        )
        rating['overall'] = round(rating['overall'], 1)

        return rating


class TrainingLauncher:
    def __init__(self):
        self.daemon_process = None
        self.start_time = datetime.now()
        self.running = True

        # Signal handlers
        signal.signal(signal.SIGTERM, self._handle_exit)
        signal.signal(signal.SIGINT, self._handle_exit)

    def _handle_exit(self, signum, frame):
        print("\n[Launcher] Stopping training...")
        self.running = False
        if self.daemon_process:
            self.daemon_process.terminate()
            try:
                self.daemon_process.wait(timeout=10)
            except:
                self.daemon_process.kill()

    def start(self):
        """Start the training daemon."""
        print("=" * 60)
        print("E-CPMM TRAINING LAUNCHER")
        print("=" * 60)
        print(f"Started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Logs: {LOG_DIR}")
        print(f"Sandbox Base: {SANDBOX_BASE_DIR}")
        print("=" * 60)
        print("\nPress Ctrl+C or close window to stop and generate report.\n")

        # Start daemon
        self.daemon_process = subprocess.Popen(
            [sys.executable, str(DAEMON_SCRIPT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        # Stream output
        try:
            while self.running and self.daemon_process.poll() is None:
                line = self.daemon_process.stdout.readline()
                if line:
                    print(line, end='')
                time.sleep(0.1)
        except KeyboardInterrupt:
            self._handle_exit(None, None)

        # Generate report
        self.generate_report()

    def _find_latest_sandbox_dir(self) -> Path:
        """Find the most recent training session sandbox directory."""
        try:
            # Look for directories starting with "training_" in sandbox base
            session_dirs = [d for d in SANDBOX_BASE_DIR.iterdir()
                          if d.is_dir() and d.name.startswith("training_")]

            if session_dirs:
                # Sort by name (which includes timestamp) and get the latest
                latest = sorted(session_dirs, key=lambda x: x.name)[-1]
                print(f"[Launcher] Found sandbox directory: {latest}")
                return latest

            # Fallback: check for old-style 'tools' directory
            old_tools_dir = SANDBOX_BASE_DIR / "tools"
            if old_tools_dir.exists():
                print(f"[Launcher] Using legacy sandbox directory: {old_tools_dir}")
                return old_tools_dir

        except Exception as e:
            print(f"[Launcher] Error finding sandbox dir: {e}")

        return SANDBOX_BASE_DIR

    def generate_report(self):
        """Generate detailed training analysis report with ALL information."""
        print("\n[Launcher] Generating comprehensive analysis report...")

        end_time = datetime.now()
        duration = end_time - self.start_time

        # Load training state
        state_file = LOG_DIR / "training_state.json"
        state = {}
        if state_file.exists():
            try:
                with open(state_file) as f:
                    state = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"[Launcher] Warning: Could not load training state: {e}")
                state = {}

        # Load ALL proposals (keep full history, not just unique)
        proposals_file = LOG_DIR / "proposals.jsonl"
        all_proposals = []
        if proposals_file.exists():
            with open(proposals_file) as f:
                for line in f:
                    try:
                        all_proposals.append(json.loads(line.strip()))
                    except:
                        pass

        # Get unique proposals (last entry for each ID) for analysis
        unique_proposals = {}
        for p in all_proposals:
            unique_proposals[p.get('id', str(len(unique_proposals)))] = p
        proposals = list(unique_proposals.values())

        # Find the most recent training session sandbox directory
        sandbox_dir = self._find_latest_sandbox_dir()

        # Get ALL Python files in sandbox (not just frank_*.py)
        tools = []
        if sandbox_dir and sandbox_dir.exists():
            tools = list(sandbox_dir.glob("*.py"))
            # Also check subdirectories
            tools.extend(sandbox_dir.glob("**/*.py"))
            # Remove duplicates and sort
            tools = sorted(set(tools), key=lambda x: x.name)

        print(f"[Launcher] Found {len(tools)} tool files")
        print(f"[Launcher] Found {len(proposals)} unique proposals")
        print(f"[Launcher] Full proposal history: {len(all_proposals)} entries")

        # Generate report
        report_file = LOG_DIR / f"training_report_{end_time.strftime('%Y%m%d_%H%M%S')}.txt"

        try:
            # Ensure log directory exists
            LOG_DIR.mkdir(parents=True, exist_ok=True)

            with open(report_file, 'w') as f:
                self._write_report(f, state, proposals, all_proposals, tools,
                                 duration, end_time, sandbox_dir)

            print(f"[Launcher] Report saved: {report_file}")
        except (IOError, OSError, PermissionError) as e:
            print(f"[Launcher] ERROR: Could not write report: {e}")
            # Try fallback location in /tmp
            try:
                import tempfile as _tl_tmpmod
                _tl_fallback_dir = Path(_tl_tmpmod.gettempdir()) / "frank"
                _tl_fallback_dir.mkdir(parents=True, exist_ok=True)
                fallback_file = _tl_fallback_dir / f"training_report_{end_time.strftime('%Y%m%d_%H%M%S')}.txt"
                with open(fallback_file, 'w') as f:
                    self._write_report(f, state, proposals, all_proposals, tools,
                                     duration, end_time, sandbox_dir)
                print(f"[Launcher] Report saved to fallback location: {fallback_file}")
                report_file = fallback_file
            except Exception as e2:
                print(f"[Launcher] ERROR: Could not write to fallback either: {e2}")
                return

        # Open in text editor (positioned nicely)
        self._open_report(report_file)

    def _write_report(self, f, state, proposals, all_proposals, tools,
                      duration, end_time, sandbox_dir):
        """Write comprehensive report with detailed descriptions and ratings (NO CODE)."""

        # Header
        f.write("=" * 70 + "\n")
        f.write("        E-CPMM AUTONOMOUS TRAINING - ANALYSIS REPORT\n")
        f.write("=" * 70 + "\n\n")

        # Executive Summary
        f.write("EXECUTIVE SUMMARY\n")
        f.write("-" * 70 + "\n\n")

        hours = duration.total_seconds() / 3600
        f.write(f"Training Duration:     {hours:.2f} hours ({duration})\n")
        f.write(f"Start Time:            {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"End Time:              {end_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Sandbox Directory:     {sandbox_dir}\n")
        f.write(f"Total Loops:           {state.get('loop_count', 0)}\n")
        f.write(f"Total Messages:        {state.get('message_count', 0)}\n")
        f.write(f"Tools Created:         {len(tools)}\n")
        f.write(f"Proposals Generated:   {len(all_proposals)}\n\n")

        # Key Metrics
        f.write("KEY METRICS\n")
        f.write("-" * 70 + "\n\n")

        total_proposals = state.get('proposal_count', 0) or len(proposals)
        approved = state.get('approved_count', 0)
        rejected = state.get('rejected_count', 0)
        implemented = state.get('implemented_count', 0)
        tools_created = state.get('tools_created', 0) or len(tools)
        syntax_valid = state.get('tools_syntax_valid', 0)
        exec_success = state.get('tools_execution_success', 0)

        f.write(f"Proposals Generated:   {total_proposals}\n")
        f.write(f"Proposals Approved:    {approved} ({approved/max(total_proposals,1)*100:.1f}%)\n")
        f.write(f"Proposals Rejected:    {rejected} ({rejected/max(total_proposals,1)*100:.1f}%)\n")
        f.write(f"Proposals Implemented: {implemented}\n\n")

        f.write(f"Tools Created:         {tools_created}\n")
        f.write(f"Syntax Valid:          {syntax_valid} ({syntax_valid/max(tools_created,1)*100:.1f}%)\n")
        f.write(f"Execution Success:     {exec_success} ({exec_success/max(tools_created,1)*100:.1f}%)\n\n")

        syntax_rate = syntax_valid / max(tools_created, 1) * 100
        exec_rate = exec_success / max(tools_created, 1) * 100

        # Success Assessment
        f.write("SUCCESS ASSESSMENT\n")
        f.write("-" * 70 + "\n\n")

        if syntax_rate >= 90:
            f.write("[EXCELLENT] Code Quality: Frank generates syntactically correct Python\n")
            f.write(f"            code {syntax_rate:.0f}% of the time.\n\n")
        elif syntax_rate >= 70:
            f.write("[GOOD] Code Quality: Frank generates valid Python code most of the time.\n")
            f.write(f"       Syntax success rate: {syntax_rate:.0f}%\n\n")
        else:
            f.write("[NEEDS IMPROVEMENT] Code Quality: Syntax errors are common.\n")
            f.write(f"                    Syntax success rate: {syntax_rate:.0f}%\n\n")

        if exec_rate >= 50:
            f.write("[GOOD] Execution: More than half of the tools run successfully.\n")
            f.write(f"       Execution success rate: {exec_rate:.0f}%\n\n")
        elif exec_rate >= 25:
            f.write("[MODERATE] Execution: Some tools run, but many fail.\n")
            f.write(f"           Success rate: {exec_rate:.0f}%\n\n")
        else:
            f.write("[NEEDS IMPROVEMENT] Execution: Most tools fail to run.\n\n")

        # ================================================================
        # DETAILED TOOL ANALYSIS WITH RATINGS
        # ================================================================
        f.write("\n" + "=" * 70 + "\n")
        f.write("DETAILED TOOL DESCRIPTIONS AND RATINGS (1-10)\n")
        f.write("=" * 70 + "\n\n")

        f.write("Rating Scale:\n")
        f.write("  1-3:  Poor - Major issues, not functional\n")
        f.write("  4-5:  Below Average - Some functionality, needs work\n")
        f.write("  6-7:  Average - Works but has room for improvement\n")
        f.write("  8-9:  Good - Well implemented, minor issues\n")
        f.write("  10:   Excellent - Production-ready quality\n\n")

        all_ratings = []

        for i, tool_path in enumerate(sorted(tools), 1):
            tool_name = tool_path.stem

            # Analyze the tool
            analyzer = ToolAnalyzer(tool_path)

            # Find corresponding proposal
            tool_proposal = None
            for p in proposals:
                if p.get('tool_name') == tool_name or p.get('tool_file', '').endswith(tool_path.name):
                    tool_proposal = p
                    break

            # Calculate rating
            rating = analyzer.calculate_rating(tool_proposal)
            all_ratings.append({
                'name': tool_name,
                'rating': rating['overall'],
                'path': str(tool_path)
            })

            f.write(f"\n{'=' * 70}\n")
            f.write(f"TOOL #{i}: {tool_name}\n")
            f.write(f"{'=' * 70}\n\n")

            # Overall Rating Banner
            overall = rating['overall']
            stars = "*" * int(overall) + "." * (10 - int(overall))
            f.write(f"OVERALL RATING: [{stars}] {overall}/10\n\n")

            # Basic Info
            f.write("BASIC INFORMATION:\n")
            f.write(f"  File Location:     {tool_path}\n")
            try:
                f.write(f"  File Size:         {tool_path.stat().st_size} bytes\n")
            except (OSError, FileNotFoundError):
                f.write(f"  File Size:         unknown (file may have been moved)\n")
            f.write(f"  Lines of Code:     {len(analyzer.code.splitlines())}\n")
            if tool_proposal:
                f.write(f"  Category:          {tool_proposal.get('category', 'unknown')}\n")
            f.write("\n")

            # Sub-Ratings with explanations
            f.write("DETAILED RATINGS:\n")
            f.write(f"  Syntax Quality:    {rating['syntax']}/10")
            if rating['syntax'] == 10:
                f.write(" - Valid Python syntax, no errors\n")
            elif rating['syntax'] >= 5:
                f.write(" - Minor syntax issues\n")
            else:
                f.write(" - Syntax errors present\n")

            f.write(f"  Execution:         {rating['execution']}/10")
            if rating['execution'] == 10:
                f.write(" - Runs successfully without errors\n")
            elif rating['execution'] >= 5:
                f.write(" - Partial execution, some errors\n")
            else:
                f.write(" - Does not execute properly\n")

            f.write(f"  Completeness:      {rating['completeness']}/10")
            if rating['completeness'] >= 8:
                f.write(" - Well-structured with main() and functions\n")
            elif rating['completeness'] >= 5:
                f.write(" - Basic structure present\n")
            else:
                f.write(" - Incomplete implementation\n")

            f.write(f"  Documentation:     {rating['documentation']}/10")
            if rating['documentation'] >= 8:
                f.write(" - Well documented with docstrings\n")
            elif rating['documentation'] >= 5:
                f.write(" - Partial documentation\n")
            else:
                f.write(" - Lacks documentation\n")

            f.write(f"  Complexity:        {rating['complexity']}/10")
            if rating['complexity'] >= 7:
                f.write(" - Sophisticated implementation\n")
            elif rating['complexity'] >= 4:
                f.write(" - Moderate complexity\n")
            else:
                f.write(" - Simple implementation\n")

            f.write(f"  Integration:       {rating['connections']}/10")
            if rating['connections'] >= 5:
                f.write(" - Connects to external systems\n")
            else:
                f.write(" - Standalone functionality\n")
            f.write("\n")

            # Purpose and Functionality Description
            f.write("PURPOSE AND FUNCTIONALITY:\n")

            # Get description from proposal or generate from analysis
            desc = ""
            if tool_proposal:
                desc = tool_proposal.get('description', '')

            if desc:
                # Word wrap the description
                words = desc.split()
                line = "  "
                for word in words:
                    if len(line) + len(word) > 68:
                        f.write(line + "\n")
                        line = "  "
                    line += word + " "
                if line.strip():
                    f.write(line + "\n")
            else:
                # Generate description from code analysis
                functions = analyzer.get_functions()
                classes = analyzer.get_classes()
                imports = analyzer.get_imports()

                if functions or classes:
                    f.write("  This tool provides the following capabilities:\n")
                    if classes:
                        for cls in classes:
                            f.write(f"  - Class '{cls['name']}' with methods: {', '.join(cls['methods'][:5])}\n")
                            if cls['docstring'] != "No documentation":
                                f.write(f"    Purpose: {cls['docstring'][:100]}...\n")
                    if functions:
                        for func in functions[:5]:
                            args = ", ".join(func['args']) if func['args'] else "none"
                            f.write(f"  - Function '{func['name']}' (parameters: {args})\n")
                            if func['docstring'] != "No documentation":
                                f.write(f"    Purpose: {func['docstring'][:100]}...\n")
                else:
                    f.write("  No detailed description available.\n")
            f.write("\n")

            # Technical Components
            functions = analyzer.get_functions()
            classes = analyzer.get_classes()
            imports = analyzer.get_imports()

            f.write("TECHNICAL COMPONENTS:\n")
            f.write(f"  Functions:         {len(functions)}\n")
            f.write(f"  Classes:           {len(classes)}\n")
            f.write(f"  Dependencies:      {len(imports)} modules\n")

            if imports:
                # Categorize imports
                std_lib = ['os', 'sys', 'json', 're', 'time', 'datetime', 'pathlib',
                          'subprocess', 'threading', 'collections', 'functools',
                          'itertools', 'math', 'random', 'hashlib', 'base64',
                          'urllib', 'http', 'socket', 'logging', 'argparse', 'ast']
                external = [i for i in imports if i and i.split('.')[0] not in std_lib]
                if external:
                    f.write(f"  External Packages: {', '.join(external[:5])}\n")
            f.write("\n")

            # External Connections
            connections = analyzer.get_external_connections()
            has_connections = any(v for v in connections.values())
            if has_connections:
                f.write("EXTERNAL INTEGRATIONS:\n")
                if connections['http_calls']:
                    f.write("  - Makes HTTP/API calls (web requests)\n")
                if connections['file_operations']:
                    f.write("  - Performs file system operations\n")
                if connections['database']:
                    f.write(f"  - Database connectivity: {', '.join(connections['database'])}\n")
                if connections['subprocess']:
                    f.write("  - Executes shell commands\n")
                if connections['sockets']:
                    f.write("  - Network socket communication\n")
                f.write("\n")

            # Execution Results
            if tool_proposal:
                test_out = tool_proposal.get('test_output', '')
                if test_out:
                    f.write("EXECUTION RESULTS:\n")
                    # Summarize test output (no raw code)
                    lines = test_out.strip().split('\n')
                    if 'error' in test_out.lower() or 'exception' in test_out.lower():
                        f.write("  Status: Failed with errors\n")
                        # Extract error type
                        for line in lines:
                            if 'Error' in line or 'Exception' in line:
                                f.write(f"  Issue: {line[:60]}...\n")
                                break
                    else:
                        f.write("  Status: Completed successfully\n")
                        if lines:
                            f.write(f"  Output summary: {lines[0][:60]}...\n")
                    f.write("\n")

            # Performance Assessment
            f.write("ASSESSMENT:\n")
            if overall >= 8:
                f.write("  Status: PRODUCTION CANDIDATE\n")
                f.write("  This tool demonstrates high quality implementation and could be\n")
                f.write("  considered for promotion to production use.\n")
            elif overall >= 6:
                f.write("  Status: PROMISING\n")
                f.write("  This tool shows good potential. With some refinement and testing,\n")
                f.write("  it could become a useful addition to the toolkit.\n")
            elif overall >= 4:
                f.write("  Status: NEEDS WORK\n")
                f.write("  This tool requires significant improvements before it can be\n")
                f.write("  considered functional. Focus on fixing errors and adding tests.\n")
            else:
                f.write("  Status: NOT FUNCTIONAL\n")
                f.write("  This tool has major issues that prevent it from working.\n")
                f.write("  Consider redesigning the approach or discarding.\n")
            f.write("\n")

        # ================================================================
        # RATINGS SUMMARY TABLE
        # ================================================================
        f.write("\n" + "=" * 70 + "\n")
        f.write("RATINGS SUMMARY\n")
        f.write("=" * 70 + "\n\n")

        avg_rating = 0
        sorted_ratings = []

        if all_ratings:
            sorted_ratings = sorted(all_ratings, key=lambda x: x['rating'], reverse=True)
            avg_rating = sum(r['rating'] for r in all_ratings) / len(all_ratings)

            f.write(f"{'#':<4} {'Tool Name':<35} {'Rating':<10} {'Status':<15}\n")
            f.write("-" * 65 + "\n")

            for idx, item in enumerate(sorted_ratings, 1):
                status = "EXCELLENT" if item['rating'] >= 8 else \
                         "GOOD" if item['rating'] >= 6 else \
                         "AVERAGE" if item['rating'] >= 4 else "POOR"
                f.write(f"{idx:<4} {item['name'][:33]:<35} {item['rating']:<10.1f} {status:<15}\n")

            # Statistics
            max_rating = max(r['rating'] for r in all_ratings)
            min_rating = min(r['rating'] for r in all_ratings)

            f.write("\n" + "-" * 65 + "\n")
            f.write(f"Average Rating:  {avg_rating:.1f}/10\n")
            f.write(f"Highest Rating:  {max_rating:.1f}/10\n")
            f.write(f"Lowest Rating:   {min_rating:.1f}/10\n")

            # Distribution
            excellent = sum(1 for r in all_ratings if r['rating'] >= 8)
            good = sum(1 for r in all_ratings if 6 <= r['rating'] < 8)
            average = sum(1 for r in all_ratings if 4 <= r['rating'] < 6)
            poor = sum(1 for r in all_ratings if r['rating'] < 4)

            f.write(f"\nRating Distribution:\n")
            f.write(f"  Excellent (8-10): {excellent} tools ({excellent/len(all_ratings)*100:.0f}%)\n")
            f.write(f"  Good (6-7):       {good} tools ({good/len(all_ratings)*100:.0f}%)\n")
            f.write(f"  Average (4-5):    {average} tools ({average/len(all_ratings)*100:.0f}%)\n")
            f.write(f"  Poor (1-3):       {poor} tools ({poor/len(all_ratings)*100:.0f}%)\n")
        else:
            f.write("No tools found to rate.\n")

        # ================================================================
        # PROPOSALS SUMMARY (descriptions only, no code)
        # ================================================================
        f.write("\n" + "=" * 70 + "\n")
        f.write("PROPOSALS HISTORY SUMMARY\n")
        f.write("=" * 70 + "\n\n")
        f.write(f"Total proposals generated during training: {len(all_proposals)}\n\n")

        for i, prop in enumerate(all_proposals, 1):
            f.write(f"Proposal #{i}:\n")
            f.write(f"  Tool:     {prop.get('tool_name', 'N/A')}\n")
            f.write(f"  Category: {prop.get('category', 'N/A')}\n")
            f.write(f"  Status:   {prop.get('status', 'N/A')}\n")
            f.write(f"  Valid:    {'Yes' if prop.get('syntax_valid') else 'No'}\n")
            f.write(f"  Runs:     {'Yes' if prop.get('execution_success') else 'No'}\n")

            desc = prop.get('description', '')
            if desc:
                # Truncate and wrap description
                desc_short = desc[:150] + "..." if len(desc) > 150 else desc
                f.write(f"  Purpose:  {desc_short}\n")

            feedback = prop.get('claude_feedback', '') or prop.get('feedback', '')
            if feedback:
                feedback_short = feedback[:100] + "..." if len(feedback) > 100 else feedback
                f.write(f"  Feedback: {feedback_short}\n")

            f.write("\n")

        # ================================================================
        # CATEGORIES BREAKDOWN
        # ================================================================
        f.write("\n" + "=" * 70 + "\n")
        f.write("CATEGORIES BREAKDOWN\n")
        f.write("=" * 70 + "\n\n")

        categories = {}
        for p in proposals:
            cat = p.get('category', 'unknown')
            if cat not in categories:
                categories[cat] = {'total': 0, 'syntax_ok': 0, 'exec_ok': 0}
            categories[cat]['total'] += 1
            if p.get('syntax_valid'):
                categories[cat]['syntax_ok'] += 1
            if p.get('execution_success'):
                categories[cat]['exec_ok'] += 1

        if categories:
            f.write(f"{'Category':<20} {'Total':<8} {'Valid':<10} {'Working':<10}\n")
            f.write("-" * 50 + "\n")
            for cat, stats in sorted(categories.items()):
                f.write(f"{cat:<20} {stats['total']:<8} {stats['syntax_ok']:<10} {stats['exec_ok']:<10}\n")
        else:
            f.write("No category data available.\n")

        # ================================================================
        # RECOMMENDATIONS
        # ================================================================
        f.write("\n" + "=" * 70 + "\n")
        f.write("RECOMMENDATIONS FOR NEXT TRAINING SESSION\n")
        f.write("=" * 70 + "\n\n")

        rec_num = 1

        if syntax_rate < 90:
            f.write(f"{rec_num}. IMPROVE CODE GENERATION QUALITY\n")
            f.write("   Focus on generating syntactically correct Python code.\n")
            f.write("   Consider adding more code examples to training prompts.\n\n")
            rec_num += 1

        if exec_rate < 50:
            f.write(f"{rec_num}. REDUCE EXTERNAL DEPENDENCIES\n")
            f.write("   Many tools fail because they require unavailable packages.\n")
            f.write("   Encourage use of Python standard library modules only.\n\n")
            rec_num += 1

        if all_ratings and avg_rating < 6:
            f.write(f"{rec_num}. FOCUS ON QUALITY OVER QUANTITY\n")
            f.write(f"   Current average rating: {avg_rating:.1f}/10\n")
            f.write("   Fewer, better-tested tools are more valuable than many broken ones.\n\n")
            rec_num += 1

        f.write(f"{rec_num}. EXTEND TRAINING DURATION\n")
        f.write(f"   This session ran for {hours:.1f} hours.\n")
        f.write("   Longer sessions allow more iterations and learning cycles.\n\n")
        rec_num += 1

        if all_ratings:
            top_tools = [r for r in sorted_ratings if r['rating'] >= 7]
            if top_tools:
                f.write(f"{rec_num}. REVIEW TOP-RATED TOOLS FOR PRODUCTION\n")
                f.write("   The following tools show promise:\n")
                for t in top_tools[:5]:
                    f.write(f"   - {t['name']} (Rating: {t['rating']:.1f}/10)\n")
                f.write("\n")

        # ================================================================
        # FOOTER
        # ================================================================
        f.write("\n" + "=" * 70 + "\n")
        f.write("END OF TRAINING REPORT\n")
        f.write("-" * 70 + "\n")
        f.write(f"Generated:       {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Tools Analyzed:  {len(tools)}\n")
        f.write(f"Proposals Total: {len(all_proposals)}\n")
        if all_ratings:
            f.write(f"Average Rating:  {avg_rating:.1f}/10\n")
        f.write("=" * 70 + "\n")

    def _open_report(self, report_file):
        """Open report in text editor, positioned at center-left like terminal."""
        try:
            # Target position: center-left, similar to terminal window
            # Based on screenshot analysis: approximately 800x600, center-left
            width = 800
            height = 600
            x = 100  # Left side with some margin
            y = 100  # Top with some margin

            # Try to get screen size for better positioning
            try:
                result = subprocess.run(
                    ['xdpyinfo'], capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.split('\n'):
                    if 'dimensions:' in line:
                        try:
                            parts = line.split()[1].split('x')
                            screen_w = int(parts[0])
                            screen_h = int(parts[1])
                            # Center-left position (similar to terminal in screenshot)
                            x = int(screen_w * 0.1)  # 10% from left
                            y = int((screen_h - height) / 2)  # Vertically centered
                        except (IndexError, ValueError):
                            pass  # Keep default values if parsing fails
                        break
            except Exception:
                pass  # Use default values

            # Open with text editor
            editors = ['gedit', 'xed', 'pluma', 'mousepad', 'leafpad', 'kate', 'kwrite']
            editor_launched = False

            for editor in editors:
                try:
                    # Check if editor exists
                    subprocess.run(['which', editor], capture_output=True, check=True)

                    # Launch editor
                    env = os.environ.copy()
                    env['DISPLAY'] = ':0'
                    subprocess.Popen(
                        [editor, str(report_file)],
                        env=env,
                        start_new_session=True
                    )
                    print(f"[Launcher] Opened report with {editor}")
                    editor_launched = True

                    # Wait for window to appear then position it
                    time.sleep(1.5)

                    # Try wmctrl for positioning
                    try:
                        subprocess.run([
                            'wmctrl', '-r', ':ACTIVE:', '-e', f'0,{x},{y},{width},{height}'
                        ], capture_output=True, timeout=5)
                        print(f"[Launcher] Positioned window at ({x},{y}) size {width}x{height}")
                    except:
                        # Try xdotool as fallback
                        try:
                            # Get window ID
                            result = subprocess.run(
                                ['xdotool', 'search', '--name', report_file.name],
                                capture_output=True, text=True, timeout=5
                            )
                            if result.stdout.strip():
                                wid = result.stdout.strip().split()[0]
                                subprocess.run([
                                    'xdotool', 'windowmove', wid, str(x), str(y)
                                ], timeout=5)
                                subprocess.run([
                                    'xdotool', 'windowsize', wid, str(width), str(height)
                                ], timeout=5)
                        except:
                            pass

                    return
                except subprocess.CalledProcessError:
                    continue
                except Exception as e:
                    continue

            # Fallback: xdg-open
            if not editor_launched:
                subprocess.Popen(['xdg-open', str(report_file)], start_new_session=True)
                print("[Launcher] Opened report with xdg-open")

        except Exception as e:
            print(f"[Launcher] Could not open report: {e}")
            print(f"[Launcher] Report saved at: {report_file}")


def main():
    launcher = TrainingLauncher()
    launcher.start()


if __name__ == "__main__":
    main()
