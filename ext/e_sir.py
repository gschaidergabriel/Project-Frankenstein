#!/usr/bin/env python3
"""
E-SIR v2.5 "Genesis Fortress"
============================
Recursive Self-Improvement Protocol

Dual-Core Architecture:
- Ouroboros Fortress: Stability & Preservation (conservative guardian)
- Genesis Directive: Controlled Evolution (sandbox experimentation)

Security Model:
- Immutable audit log with hash chain
- Atomic transaction wrapper
- Regression guard with functional invariance
- Recursion depth limits
- Forbidden action sentinel

Author: Frank AI System
"""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import importlib.util
import sys

# Sandbox-Awareness Integration (KRITISCH für Tool-Unterscheidung)
try:
    from .sandbox_awareness import (
        register_sandbox_tool, is_sandbox_mode, get_environment,
        EnvironmentType, promote_to_production, is_tool_safe_for_production
    )
    _SANDBOX_AWARE = True
except ImportError:
    _SANDBOX_AWARE = False

# Central path configuration
try:
    from config.paths import AICORE_ROOT, get_db, SANDBOX_DIR as _CFG_SANDBOX_DIR
except ImportError:
    AICORE_ROOT = Path(__file__).resolve().parents[2]
    _CFG_SANDBOX_DIR = None
    def get_db(name):
        _db_dir = Path.home() / ".local" / "share" / "frank" / "db"
        _db_dir.mkdir(parents=True, exist_ok=True)
        return _db_dir / f"{name}.db"

# =============================================================================
# CONFIGURATION
# =============================================================================

BASE_DIR = AICORE_ROOT
EXT_DIR = BASE_DIR / "ext"
GENESIS_DIR = EXT_DIR / "genesis"
SNAPSHOTS_DIR = EXT_DIR / "snapshots"
SANDBOX_DIR = _CFG_SANDBOX_DIR if _CFG_SANDBOX_DIR is not None else EXT_DIR / "sandbox"
DATABASE_PATH = get_db("e_sir")

# Recursion & Safety Limits
MAX_RECURSION_DEPTH = 3
MAX_DAILY_MODIFICATIONS = 10
MAX_SANDBOX_RUNS_PER_HOUR = 20
ROLLBACK_WINDOW_HOURS = 24
MIN_CONFIDENCE_THRESHOLD = 0.7

# Risk Weights (Hybrid Decision Matrix)
RISK_WEIGHTS = {
    "file_create": 0.2,
    "file_modify": 0.5,
    "file_delete": 0.9,
    "code_execute": 0.6,
    "system_call": 0.8,
    "network_access": 0.7,
    "db_write": 0.4,
    "config_change": 0.6,
}

# Forbidden Actions (absolute red lines)
FORBIDDEN_ACTIONS = [
    "rm -rf /",
    "rm -rf ~",
    "dd if=",
    "mkfs",
    ":(){:|:&};:",  # fork bomb
    "chmod -R 777 /",
    "sudo rm",
    "sudo dd",
    "> /dev/sda",
    "curl | sh",
    "wget | sh",
    "eval(input",
    "__import__('os').system",
    "subprocess.call.*shell=True.*rm",
]

# Protected Paths (never modify)
PROTECTED_PATHS = [
    str(DATABASE_PATH.parent) + "/",
    str(Path.home() / ".config") + "/",
    str(Path.home() / ".ssh") + "/",
    str(Path.home() / ".gnupg") + "/",
    str(DATABASE_PATH),
]


# =============================================================================
# DATA STRUCTURES
# =============================================================================

class ActionType(Enum):
    FILE_CREATE = "file_create"
    FILE_MODIFY = "file_modify"
    FILE_DELETE = "file_delete"
    CODE_EXECUTE = "code_execute"
    SYSTEM_CALL = "system_call"
    TOOL_REGISTER = "tool_register"
    ROLLBACK = "rollback"


class DecisionResult(Enum):
    APPROVED = "approved"
    DENIED = "denied"
    SANDBOX_REQUIRED = "sandbox_required"
    HUMAN_REVIEW = "human_review"


@dataclass
class ProposedAction:
    """A proposed self-improvement action."""
    action_type: ActionType
    target_path: Optional[str] = None
    description: str = ""
    code_content: Optional[str] = None
    risk_score: float = 0.0
    confidence: float = 0.0
    rationale: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditEntry:
    """Immutable audit log entry with hash chain."""
    timestamp: str
    action_type: str
    description: str
    risk_score: float
    decision: str
    outcome: str
    previous_hash: str
    entry_hash: str = ""

    def compute_hash(self) -> str:
        """Compute SHA-256 hash of entry (excluding entry_hash field)."""
        data = f"{self.timestamp}|{self.action_type}|{self.description}|{self.risk_score}|{self.decision}|{self.outcome}|{self.previous_hash}"
        return hashlib.sha256(data.encode()).hexdigest()


@dataclass
class Snapshot:
    """File system snapshot for rollback."""
    snapshot_id: str
    timestamp: str
    file_path: str
    content_hash: str
    backup_path: str
    reason: str


# =============================================================================
# DATABASE
# =============================================================================

class ESIRDatabase:
    """Persistent storage for E-SIR state and audit log."""

    def __init__(self, db_path: Path = DATABASE_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                -- Immutable Audit Log (hash chain)
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    description TEXT,
                    risk_score REAL,
                    decision TEXT NOT NULL,
                    outcome TEXT,
                    previous_hash TEXT NOT NULL,
                    entry_hash TEXT NOT NULL UNIQUE
                );

                -- File Snapshots for Rollback
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id TEXT UNIQUE NOT NULL,
                    timestamp TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    backup_path TEXT NOT NULL,
                    reason TEXT,
                    restored INTEGER DEFAULT 0
                );

                -- Genesis Tools Registry
                CREATE TABLE IF NOT EXISTS genesis_tools (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_name TEXT UNIQUE NOT NULL,
                    tool_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    version INTEGER DEFAULT 1,
                    status TEXT DEFAULT 'active',
                    description TEXT,
                    test_passed INTEGER DEFAULT 0,
                    usage_count INTEGER DEFAULT 0
                );

                -- Daily Modification Counter
                CREATE TABLE IF NOT EXISTS daily_stats (
                    date TEXT PRIMARY KEY,
                    modification_count INTEGER DEFAULT 0,
                    sandbox_runs INTEGER DEFAULT 0,
                    rollbacks INTEGER DEFAULT 0
                );

                -- Recursion Depth Tracker
                CREATE TABLE IF NOT EXISTS recursion_state (
                    session_id TEXT PRIMARY KEY,
                    current_depth INTEGER DEFAULT 0,
                    started_at TEXT,
                    last_action TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
                CREATE INDEX IF NOT EXISTS idx_snapshots_path ON snapshots(file_path);
                CREATE INDEX IF NOT EXISTS idx_genesis_status ON genesis_tools(status);
            """)

    def get_last_audit_hash(self) -> str:
        """Get hash of last audit entry (for chain)."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else "GENESIS_BLOCK"

    def add_audit_entry(self, entry: AuditEntry) -> bool:
        """Add entry to immutable audit log."""
        entry.entry_hash = entry.compute_hash()
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO audit_log
                    (timestamp, action_type, description, risk_score, decision, outcome, previous_hash, entry_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (entry.timestamp, entry.action_type, entry.description,
                      entry.risk_score, entry.decision, entry.outcome,
                      entry.previous_hash, entry.entry_hash))
            return True
        except sqlite3.IntegrityError:
            return False  # Duplicate hash = tampering attempt

    def verify_audit_chain(self) -> Tuple[bool, Optional[int]]:
        """Verify integrity of entire audit chain."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM audit_log ORDER BY id ASC"
            ).fetchall()

            expected_prev = "GENESIS_BLOCK"
            for i, row in enumerate(rows):
                entry = AuditEntry(
                    timestamp=row["timestamp"],
                    action_type=row["action_type"],
                    description=row["description"],
                    risk_score=row["risk_score"],
                    decision=row["decision"],
                    outcome=row["outcome"],
                    previous_hash=row["previous_hash"]
                )

                # Check chain link
                if entry.previous_hash != expected_prev:
                    return False, i

                # Verify hash
                computed = entry.compute_hash()
                if computed != row["entry_hash"]:
                    return False, i

                expected_prev = row["entry_hash"]

            return True, None

    def save_snapshot(self, snapshot: Snapshot):
        """Save file snapshot for potential rollback."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO snapshots
                (snapshot_id, timestamp, file_path, content_hash, backup_path, reason)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (snapshot.snapshot_id, snapshot.timestamp, snapshot.file_path,
                  snapshot.content_hash, snapshot.backup_path, snapshot.reason))

    def get_snapshots_for_path(self, file_path: str, limit: int = 10) -> List[Snapshot]:
        """Get recent snapshots for a file path."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM snapshots
                WHERE file_path = ? AND restored = 0
                ORDER BY timestamp DESC LIMIT ?
            """, (file_path, limit)).fetchall()

            return [Snapshot(**dict(row)) for row in rows]

    def register_genesis_tool(self, name: str, path: str, description: str) -> bool:
        """Register a new Genesis-created tool."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO genesis_tools (tool_name, tool_path, created_at, description)
                    VALUES (?, ?, ?, ?)
                """, (name, path, datetime.now().isoformat(), description))
            return True
        except sqlite3.IntegrityError:
            return False

    def get_daily_stats(self) -> Dict[str, int]:
        """Get today's modification statistics."""
        today = datetime.now().strftime("%Y-%m-%d")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM daily_stats WHERE date = ?", (today,)
            ).fetchone()

            if row:
                return dict(row)
            return {"date": today, "modification_count": 0, "sandbox_runs": 0, "rollbacks": 0}

    # Whitelist für erlaubte Statistik-Spalten (SQL Injection Prevention)
    ALLOWED_STATS = {"modification_count", "sandbox_runs", "rollbacks"}

    def increment_daily_stat(self, stat: str):
        """Increment a daily statistic (mit SQL Injection Schutz)."""
        # Whitelist-Validierung gegen SQL Injection
        if stat not in self.ALLOWED_STATS:
            LOG.warning(f"Invalid stat name rejected: {stat}")
            raise ValueError(f"Invalid stat: {stat}. Allowed: {self.ALLOWED_STATS}")

        today = datetime.now().strftime("%Y-%m-%d")
        with sqlite3.connect(self.db_path) as conn:
            # stat ist jetzt garantiert sicher (aus Whitelist)
            conn.execute(f"""
                INSERT INTO daily_stats (date, {stat}) VALUES (?, 1)
                ON CONFLICT(date) DO UPDATE SET {stat} = {stat} + 1
            """, (today,))


# =============================================================================
# SENTINEL - Forbidden Action Guard
# =============================================================================

class Sentinel:
    """Guards against forbidden/dangerous actions."""

    @staticmethod
    def check_forbidden(content: str) -> Tuple[bool, Optional[str]]:
        """Check if content contains forbidden patterns."""
        content_lower = content.lower()
        for pattern in FORBIDDEN_ACTIONS:
            if pattern.lower() in content_lower:
                return True, pattern
        return False, None

    @staticmethod
    def check_protected_path(path: str) -> bool:
        """Check if path is in protected list."""
        path_resolved = str(Path(path).resolve())
        for protected in PROTECTED_PATHS:
            if path_resolved.startswith(protected):
                return True
        return False

    @staticmethod
    def validate_python_safety(code: str) -> Tuple[bool, List[str]]:
        """Static analysis for dangerous Python patterns."""
        warnings = []

        dangerous_imports = ["os.system", "subprocess.call", "eval", "exec", "__import__"]
        for pattern in dangerous_imports:
            if pattern in code:
                warnings.append(f"Dangerous pattern: {pattern}")

        # Check for shell=True in subprocess
        if "shell=True" in code and ("subprocess" in code or "Popen" in code):
            warnings.append("subprocess with shell=True detected")

        return len(warnings) == 0, warnings


# =============================================================================
# HYBRID DECISION MATRIX (Ouroboros Core)
# =============================================================================

class HybridDecisionMatrix:
    """
    Risk-based decision engine.

    Score = Σ(risk_weight × impact_factor) × (1 - confidence)

    Thresholds:
    - Score < 0.3: Auto-approve
    - Score 0.3-0.6: Sandbox required
    - Score 0.6-0.8: Human review recommended
    - Score > 0.8: Auto-deny
    """

    def __init__(self, db: ESIRDatabase):
        self.db = db

    def calculate_risk_score(self, action: ProposedAction) -> float:
        """Calculate composite risk score for an action."""
        base_risk = RISK_WEIGHTS.get(action.action_type.value, 0.5)

        # Impact factors
        impact = 1.0

        # File operations: check path sensitivity
        if action.target_path:
            path = Path(action.target_path)

            # Core system files = higher risk
            if "core" in str(path).lower() or "main" in str(path).lower():
                impact *= 1.3

            # Config files = higher risk
            if path.suffix in [".yaml", ".yml", ".json", ".toml", ".ini"]:
                impact *= 1.2

            # Test files = lower risk
            if "test" in str(path).lower():
                impact *= 0.7

            # Genesis sandbox = lower risk
            if str(GENESIS_DIR) in str(path) or str(SANDBOX_DIR) in str(path):
                impact *= 0.5

        # Code content analysis
        if action.code_content:
            is_safe, warnings = Sentinel.validate_python_safety(action.code_content)
            if not is_safe:
                impact *= 1.5 + (len(warnings) * 0.1)

        # Confidence adjustment
        confidence_factor = 1.0 - min(action.confidence, 0.9)

        # Daily modification fatigue
        stats = self.db.get_daily_stats()
        if stats["modification_count"] > 5:
            impact *= 1.1

        final_score = min(base_risk * impact * confidence_factor, 1.0)
        return round(final_score, 3)

    def decide(self, action: ProposedAction) -> Tuple[DecisionResult, str]:
        """Make decision on proposed action."""

        # Absolute checks first
        if action.code_content:
            is_forbidden, pattern = Sentinel.check_forbidden(action.code_content)
            if is_forbidden:
                return DecisionResult.DENIED, f"Forbidden pattern: {pattern}"

        if action.target_path:
            if Sentinel.check_protected_path(action.target_path):
                return DecisionResult.DENIED, f"Protected path: {action.target_path}"

        # Daily limit check
        stats = self.db.get_daily_stats()
        if stats["modification_count"] >= MAX_DAILY_MODIFICATIONS:
            return DecisionResult.DENIED, "Daily modification limit reached"

        # Calculate risk score
        risk_score = self.calculate_risk_score(action)
        action.risk_score = risk_score

        # Decision thresholds
        if risk_score < 0.3:
            return DecisionResult.APPROVED, f"Low risk ({risk_score})"
        elif risk_score < 0.6:
            return DecisionResult.SANDBOX_REQUIRED, f"Medium risk ({risk_score}) - sandbox test required"
        elif risk_score < 0.8:
            return DecisionResult.HUMAN_REVIEW, f"High risk ({risk_score}) - human review recommended"
        else:
            return DecisionResult.DENIED, f"Risk too high ({risk_score})"


# =============================================================================
# ATOMIC TRANSACTION WRAPPER
# =============================================================================

class AtomicTransaction:
    """
    Atomic transaction wrapper for file operations.
    Provides automatic rollback on failure.
    """

    def __init__(self, db: ESIRDatabase):
        self.db = db
        self.pending_snapshots: List[Snapshot] = []
        self.operations: List[Callable] = []
        self.rollback_ops: List[Callable] = []

    def snapshot_file(self, file_path: Path, reason: str = "pre-modification") -> Optional[Snapshot]:
        """Create snapshot of file before modification."""
        if not file_path.exists():
            return None

        content = file_path.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()

        snapshot_id = f"{file_path.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{content_hash[:8]}"
        backup_path = SNAPSHOTS_DIR / f"{snapshot_id}.bak"

        # Create backup
        SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, backup_path)

        # Make backup read-only
        os.chmod(backup_path, 0o444)

        snapshot = Snapshot(
            snapshot_id=snapshot_id,
            timestamp=datetime.now().isoformat(),
            file_path=str(file_path),
            content_hash=content_hash,
            backup_path=str(backup_path),
            reason=reason
        )

        self.db.save_snapshot(snapshot)
        self.pending_snapshots.append(snapshot)

        return snapshot

    def add_operation(self, operation: Callable, rollback: Callable):
        """Add operation with its rollback function."""
        self.operations.append(operation)
        self.rollback_ops.append(rollback)

    def execute(self) -> Tuple[bool, str]:
        """Execute all operations atomically."""
        completed = []

        try:
            for i, op in enumerate(self.operations):
                op()
                completed.append(i)

            return True, "All operations completed successfully"

        except Exception as e:
            # Rollback in reverse order
            for i in reversed(completed):
                try:
                    self.rollback_ops[i]()
                except Exception as rollback_error:
                    pass  # Log but continue rollback

            return False, f"Transaction failed: {e}. Rolled back {len(completed)} operations."

    def restore_snapshot(self, snapshot: Snapshot) -> bool:
        """Restore file from snapshot."""
        try:
            backup_path = Path(snapshot.backup_path)
            target_path = Path(snapshot.file_path)

            if not backup_path.exists():
                return False

            # Make backup temporarily writable for copy
            os.chmod(backup_path, 0o644)
            shutil.copy2(backup_path, target_path)
            os.chmod(backup_path, 0o444)

            # Mark as restored in DB
            with sqlite3.connect(self.db.db_path) as conn:
                conn.execute(
                    "UPDATE snapshots SET restored = 1 WHERE snapshot_id = ?",
                    (snapshot.snapshot_id,)
                )

            return True
        except Exception:
            return False


# =============================================================================
# SANDBOX EXECUTOR (Genesis Testing Ground)
# =============================================================================

class SandboxExecutor:
    """
    Isolated execution environment for testing new code.
    Uses subprocess with restricted permissions.
    """

    def __init__(self, db: ESIRDatabase):
        self.db = db
        self.sandbox_dir = SANDBOX_DIR
        self.sandbox_dir.mkdir(parents=True, exist_ok=True)

    def _check_rate_limit(self) -> bool:
        """Check if sandbox runs are within hourly limit."""
        stats = self.db.get_daily_stats()
        # Simplified: check daily runs (could be enhanced to hourly)
        return stats["sandbox_runs"] < MAX_SANDBOX_RUNS_PER_HOUR * 24

    def test_code(self, code: str, test_cases: List[Dict[str, Any]] = None) -> Tuple[bool, str]:
        """
        Test code in isolated sandbox.
        Returns (success, output/error).
        """
        if not self._check_rate_limit():
            return False, "Sandbox rate limit exceeded"

        # Sentinel check
        is_forbidden, pattern = Sentinel.check_forbidden(code)
        if is_forbidden:
            return False, f"Code contains forbidden pattern: {pattern}"

        # Create temporary test file
        test_file = self.sandbox_dir / f"test_{int(time.time())}.py"

        try:
            # Wrap code with test harness
            wrapped_code = f'''
import sys
sys.path.insert(0, "{BASE_DIR}")

# === TEST CODE START ===
{code}
# === TEST CODE END ===

# Basic smoke test
if __name__ == "__main__":
    print("SANDBOX_TEST_PASS")
'''
            test_file.write_text(wrapped_code)

            # Execute with restrictions
            result = subprocess.run(
                ["python3", str(test_file)],
                capture_output=True,
                text=True,
                timeout=30,  # 30 second timeout
                cwd=str(self.sandbox_dir),
                env={
                    "PATH": "/usr/bin:/bin",
                    "PYTHONPATH": str(BASE_DIR),
                    "HOME": str(self.sandbox_dir),
                }
            )

            self.db.increment_daily_stat("sandbox_runs")

            if result.returncode == 0 and "SANDBOX_TEST_PASS" in result.stdout:
                return True, result.stdout
            else:
                return False, f"Exit code: {result.returncode}\nStdout: {result.stdout}\nStderr: {result.stderr}"

        except subprocess.TimeoutExpired:
            return False, "Sandbox execution timed out (30s limit)"
        except Exception as e:
            return False, f"Sandbox error: {e}"
        finally:
            # Cleanup
            if test_file.exists():
                test_file.unlink()

    def test_tool_integration(self, tool_path: Path) -> Tuple[bool, str]:
        """Test if a Genesis tool can be safely imported."""
        test_code = f'''
import importlib.util
spec = importlib.util.spec_from_file_location("test_tool", "{tool_path}")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

# Check for required attributes
required = ["__doc__", "__name__"]
for attr in required:
    if not hasattr(module, attr):
        raise AttributeError(f"Missing required attribute: {{attr}}")

print("SANDBOX_TEST_PASS")
'''
        return self.test_code(test_code)


# =============================================================================
# GENESIS DIRECTIVE (Tool Creation)
# =============================================================================

class GenesisDirective:
    """
    Controlled tool creation system.
    New tools are created in sandbox, tested, then promoted.
    """

    def __init__(self, db: ESIRDatabase, sandbox: SandboxExecutor):
        self.db = db
        self.sandbox = sandbox
        self.genesis_dir = GENESIS_DIR
        self.genesis_dir.mkdir(parents=True, exist_ok=True)

    def propose_tool(self, name: str, code: str, description: str) -> Tuple[bool, str]:
        """
        Propose a new tool for creation.
        Returns (success, message).
        """
        # Validate name
        if not name.isidentifier():
            return False, f"Invalid tool name: {name}"

        # Check if tool already exists
        tool_path = self.genesis_dir / f"{name}.py"
        if tool_path.exists():
            return False, f"Tool already exists: {name}"

        # Sentinel check
        is_forbidden, pattern = Sentinel.check_forbidden(code)
        if is_forbidden:
            return False, f"Code contains forbidden pattern: {pattern}"

        # Test in sandbox first
        success, output = self.sandbox.test_code(code)
        if not success:
            return False, f"Sandbox test failed: {output}"

        # Create tool file
        header = f'''#!/usr/bin/env python3
"""
Genesis Tool: {name}
Created: {datetime.now().isoformat()}
Description: {description}

This tool was auto-generated by E-SIR Genesis Directive.
"""

'''
        full_code = header + code

        try:
            tool_path.write_text(full_code)

            # Register in database
            self.db.register_genesis_tool(name, str(tool_path), description)

            # KRITISCH: Auch in Sandbox-Awareness registrieren
            # Tools sind zunächst SANDBOX-Tools bis sie promoted werden
            if _SANDBOX_AWARE:
                register_sandbox_tool(
                    name=name,
                    path=str(tool_path),
                    description=description,
                    test_results={"sandbox_test": "passed", "output": output[:500]}
                )

            # Update __init__.py if exists
            init_path = self.genesis_dir / "__init__.py"
            if not init_path.exists():
                init_path.write_text(f"# Genesis Tools\nfrom .{name} import *\n")
            else:
                init_content = init_path.read_text()
                if f"from .{name}" not in init_content:
                    init_path.write_text(init_content + f"from .{name} import *\n")

            return True, f"Tool '{name}' created at {tool_path}"

        except Exception as e:
            return False, f"Failed to create tool: {e}"

    def list_tools(self) -> List[Dict[str, Any]]:
        """List all Genesis tools with Sandbox-Awareness status."""
        with sqlite3.connect(self.db.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM genesis_tools WHERE status = 'active' ORDER BY created_at DESC"
            ).fetchall()
            tools = [dict(row) for row in rows]

            # Ergänze Sandbox-Awareness Status
            if _SANDBOX_AWARE:
                for tool in tools:
                    tool["is_production_safe"] = is_tool_safe_for_production(tool["tool_name"])
                    tool["environment_status"] = "PRODUCTION" if tool["is_production_safe"] else "SANDBOX"

            return tools

    def promote_tool(self, name: str) -> Tuple[bool, str]:
        """
        Promote ein Sandbox-Tool zu Production.
        KRITISCH: Nur aufrufen nach menschlicher Bestätigung!
        """
        if not _SANDBOX_AWARE:
            return False, "Sandbox-Awareness nicht verfügbar"

        # Prüfe ob Tool existiert
        tools = self.list_tools()
        tool_exists = any(t["tool_name"] == name for t in tools)
        if not tool_exists:
            return False, f"Tool '{name}' nicht gefunden"

        # Promote in Sandbox-Awareness
        if promote_to_production(name):
            return True, f"Tool '{name}' ist jetzt für Production freigegeben"
        else:
            return False, f"Tool '{name}' konnte nicht promoted werden (nicht getestet?)"


# =============================================================================
# REGRESSION GUARD
# =============================================================================

class RegressionGuard:
    """
    Ensures modifications don't break existing functionality.
    Uses hash-based change detection and test validation.
    """

    def __init__(self, db: ESIRDatabase):
        self.db = db
        self._function_hashes: Dict[str, str] = {}

    def compute_file_hash(self, file_path: Path) -> str:
        """Compute hash of file contents."""
        if not file_path.exists():
            return ""
        return hashlib.sha256(file_path.read_bytes()).hexdigest()

    def check_functional_invariance(self, file_path: Path, new_content: str) -> Tuple[bool, str]:
        """
        Check if modification maintains functional invariance.
        Basic check: ensure critical function signatures are preserved.
        """
        if not file_path.exists():
            return True, "New file - no invariance check needed"

        import re

        old_content = file_path.read_text()

        # Extract function/class signatures
        def extract_signatures(content: str) -> set:
            patterns = [
                r"^def\s+(\w+)\s*\([^)]*\)",  # Functions
                r"^class\s+(\w+)",             # Classes
                r"^async\s+def\s+(\w+)",       # Async functions
            ]
            sigs = set()
            for pattern in patterns:
                for match in re.finditer(pattern, content, re.MULTILINE):
                    sigs.add(match.group(1))
            return sigs

        old_sigs = extract_signatures(old_content)
        new_sigs = extract_signatures(new_content)

        # Check for removed signatures (potential breaking change)
        removed = old_sigs - new_sigs
        if removed:
            return False, f"Breaking change: removed signatures: {removed}"

        return True, "Functional invariance maintained"


# =============================================================================
# MAIN E-SIR CONTROLLER
# =============================================================================

class ESIR:
    """
    Main E-SIR Controller.
    Orchestrates Ouroboros (stability) and Genesis (evolution).
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.db = ESIRDatabase()
        self.decision_matrix = HybridDecisionMatrix(self.db)
        self.sandbox = SandboxExecutor(self.db)
        self.genesis = GenesisDirective(self.db, self.sandbox)
        self.regression_guard = RegressionGuard(self.db)

        self._recursion_depth = 0
        self._session_id = f"session_{int(time.time())}"

        self._initialized = True

    def _log_audit(self, action: ProposedAction, decision: DecisionResult, outcome: str):
        """Log action to immutable audit trail."""
        prev_hash = self.db.get_last_audit_hash()

        entry = AuditEntry(
            timestamp=datetime.now().isoformat(),
            action_type=action.action_type.value,
            description=action.description,
            risk_score=action.risk_score,
            decision=decision.value,
            outcome=outcome,
            previous_hash=prev_hash
        )

        self.db.add_audit_entry(entry)

    def propose_modification(self, action: ProposedAction) -> Tuple[bool, str]:
        """
        Main entry point for proposing a self-modification.

        Returns (success, message).
        """
        # Recursion check
        if self._recursion_depth >= MAX_RECURSION_DEPTH:
            return False, f"Maximum recursion depth ({MAX_RECURSION_DEPTH}) exceeded"

        self._recursion_depth += 1

        try:
            # Phase 1: Decision Matrix
            decision, reason = self.decision_matrix.decide(action)

            if decision == DecisionResult.DENIED:
                self._log_audit(action, decision, f"Denied: {reason}")
                return False, f"Action denied: {reason}"

            if decision == DecisionResult.HUMAN_REVIEW:
                self._log_audit(action, decision, "Awaiting human review")
                return False, f"Human review required: {reason}"

            # Phase 2: Sandbox test if required
            if decision == DecisionResult.SANDBOX_REQUIRED:
                if action.code_content:
                    success, output = self.sandbox.test_code(action.code_content)
                    if not success:
                        self._log_audit(action, DecisionResult.DENIED, f"Sandbox failed: {output}")
                        return False, f"Sandbox test failed: {output}"

            # Phase 3: Regression check for file modifications
            if action.action_type == ActionType.FILE_MODIFY and action.target_path:
                path = Path(action.target_path)
                if action.code_content:
                    ok, msg = self.regression_guard.check_functional_invariance(path, action.code_content)
                    if not ok:
                        self._log_audit(action, DecisionResult.DENIED, f"Regression: {msg}")
                        return False, f"Regression guard: {msg}"

            # Phase 4: Execute with atomic transaction
            transaction = AtomicTransaction(self.db)

            if action.action_type == ActionType.FILE_MODIFY and action.target_path:
                path = Path(action.target_path)

                # Create snapshot
                if path.exists():
                    transaction.snapshot_file(path, "pre-modification")

                # Define operation and rollback
                original_content = path.read_text() if path.exists() else None

                def do_modify():
                    path.write_text(action.code_content)

                def undo_modify():
                    if original_content:
                        path.write_text(original_content)
                    elif path.exists():
                        path.unlink()

                transaction.add_operation(do_modify, undo_modify)

            elif action.action_type == ActionType.FILE_CREATE and action.target_path:
                path = Path(action.target_path)

                def do_create():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(action.code_content or "")

                def undo_create():
                    if path.exists():
                        path.unlink()

                transaction.add_operation(do_create, undo_create)

            elif action.action_type == ActionType.TOOL_REGISTER:
                # Genesis tool creation
                name = action.metadata.get("tool_name")
                desc = action.metadata.get("description", action.description)

                if not name or not action.code_content:
                    return False, "Tool registration requires name and code"

                success, msg = self.genesis.propose_tool(name, action.code_content, desc)
                self._log_audit(action, DecisionResult.APPROVED if success else DecisionResult.DENIED, msg)
                return success, msg

            # Execute transaction
            success, msg = transaction.execute()

            if success:
                self.db.increment_daily_stat("modification_count")
                self._log_audit(action, DecisionResult.APPROVED, "Executed successfully")
            else:
                self._log_audit(action, DecisionResult.DENIED, f"Transaction failed: {msg}")

            return success, msg

        finally:
            self._recursion_depth -= 1

    def rollback_file(self, file_path: str, snapshot_id: str = None) -> Tuple[bool, str]:
        """Rollback a file to a previous snapshot."""
        snapshots = self.db.get_snapshots_for_path(file_path)

        if not snapshots:
            return False, f"No snapshots found for {file_path}"

        # Find specific snapshot or use most recent
        target = None
        if snapshot_id:
            for s in snapshots:
                if s.snapshot_id == snapshot_id:
                    target = s
                    break
            if not target:
                return False, f"Snapshot {snapshot_id} not found"
        else:
            target = snapshots[0]  # Most recent

        # Perform rollback
        transaction = AtomicTransaction(self.db)
        success = transaction.restore_snapshot(target)

        if success:
            self.db.increment_daily_stat("rollbacks")

            # Audit log
            action = ProposedAction(
                action_type=ActionType.ROLLBACK,
                target_path=file_path,
                description=f"Rollback to snapshot {target.snapshot_id}"
            )
            self._log_audit(action, DecisionResult.APPROVED, "Rollback successful")

            return True, f"Restored {file_path} from snapshot {target.snapshot_id}"

        return False, "Rollback failed"

    def verify_integrity(self) -> Dict[str, Any]:
        """Verify system integrity."""
        chain_valid, broken_at = self.db.verify_audit_chain()

        return {
            "audit_chain_valid": chain_valid,
            "broken_at_entry": broken_at,
            "daily_stats": self.db.get_daily_stats(),
            "genesis_tools": len(self.genesis.list_tools()),
            "recursion_depth": self._recursion_depth,
        }

    def get_status(self) -> Dict[str, Any]:
        """Get current E-SIR status."""
        stats = self.db.get_daily_stats()
        integrity = self.verify_integrity()

        return {
            "status": "operational",
            "daily_modifications": f"{stats['modification_count']}/{MAX_DAILY_MODIFICATIONS}",
            "sandbox_runs": stats["sandbox_runs"],
            "rollbacks_today": stats["rollbacks"],
            "audit_chain_valid": integrity["audit_chain_valid"],
            "genesis_tools_active": integrity["genesis_tools"],
            "recursion_limit": MAX_RECURSION_DEPTH,
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_esir: Optional[ESIR] = None

def get_esir() -> ESIR:
    """Get singleton E-SIR instance."""
    global _esir
    if _esir is None:
        _esir = ESIR()
    return _esir


def propose_file_modification(
    file_path: str,
    new_content: str,
    description: str,
    confidence: float = 0.5
) -> Tuple[bool, str]:
    """Convenience function to propose a file modification."""
    esir = get_esir()

    action = ProposedAction(
        action_type=ActionType.FILE_MODIFY,
        target_path=file_path,
        description=description,
        code_content=new_content,
        confidence=confidence
    )

    return esir.propose_modification(action)


def propose_tool_creation(
    tool_name: str,
    code: str,
    description: str,
    confidence: float = 0.5
) -> Tuple[bool, str]:
    """Convenience function to create a Genesis tool."""
    esir = get_esir()

    action = ProposedAction(
        action_type=ActionType.TOOL_REGISTER,
        description=description,
        code_content=code,
        confidence=confidence,
        metadata={"tool_name": tool_name, "description": description}
    )

    return esir.propose_modification(action)


def safe_file_transaction(file_path: str, operation: Callable) -> Tuple[bool, str]:
    """
    Execute file operation with automatic snapshot and rollback.

    Usage:
        def modify_config():
            path = Path("/some/config.py")
            content = path.read_text()
            content = content.replace("old", "new")
            path.write_text(content)

        success, msg = safe_file_transaction("/some/config.py", modify_config)
    """
    esir = get_esir()
    transaction = AtomicTransaction(esir.db)

    path = Path(file_path)
    if path.exists():
        transaction.snapshot_file(path, "safe_transaction")

    original = path.read_text() if path.exists() else None

    def rollback():
        if original:
            path.write_text(original)

    transaction.add_operation(operation, rollback)
    return transaction.execute()


# =============================================================================
# CLI INTERFACE
# =============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="E-SIR v2.5 Genesis Fortress")
    parser.add_argument("command", choices=["status", "verify", "tools", "test"])
    parser.add_argument("--code", help="Code to test in sandbox")

    args = parser.parse_args()
    esir = get_esir()

    if args.command == "status":
        status = esir.get_status()
        print("=" * 50)
        print("E-SIR v2.5 Genesis Fortress - Status")
        print("=" * 50)
        for key, value in status.items():
            print(f"  {key}: {value}")

    elif args.command == "verify":
        integrity = esir.verify_integrity()
        print("Integrity Check:")
        print(f"  Audit chain valid: {integrity['audit_chain_valid']}")
        if integrity['broken_at_entry']:
            print(f"  ALERT: Chain broken at entry {integrity['broken_at_entry']}")

    elif args.command == "tools":
        tools = esir.genesis.list_tools()
        print(f"Genesis Tools ({len(tools)}):")
        for tool in tools:
            print(f"  - {tool['tool_name']}: {tool['description']}")

    elif args.command == "test":
        if args.code:
            success, output = esir.sandbox.test_code(args.code)
            print(f"Sandbox test: {'PASS' if success else 'FAIL'}")
            print(output)
        else:
            print("Use --code to provide code for testing")


if __name__ == "__main__":
    main()
