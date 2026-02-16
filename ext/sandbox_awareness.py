#!/usr/bin/env python3
"""
Sandbox Awareness System v1.0
==============================
CRITICAL: This module ensures that Frank ALWAYS knows
whether he is working in a sandbox or in the production system.

This prevents:
- Confusion of sandbox tools with real system tools
- Unintended use of test functions in the live system
- Inconsistent world model updates based on sandbox results

Integration:
- E-CPMM: Stored as immutable core edge
- Personality: Injects sandbox status into every context
- E-SIR: Marks all sandbox operations clearly

Author: Projekt Frankenstein
Created: 2026-01-30
"""

import json
import os
import sqlite3
import threading
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any

# Central path configuration
try:
    from config.paths import get_db
except ImportError:
    def get_db(name):
        return Path("/home/ai-core-node/.local/share/frank/db") / f"{name}.db"

# =============================================================================
# CONFIGURATION
# =============================================================================

DATABASE_PATH = get_db("sandbox_awareness")
ECPMM_DB_PATH = get_db("e_cpmm")

# Environment markers
ENV_SANDBOX_MODE = "FRANK_SANDBOX_MODE"
ENV_SANDBOX_SESSION = "FRANK_SANDBOX_SESSION_ID"

# =============================================================================
# ENUMS & DATA STRUCTURES
# =============================================================================

class EnvironmentType(Enum):
    """Clearly defined environment types."""
    PRODUCTION = "PRODUCTION"      # Real system - all actions are permanent
    SANDBOX = "SANDBOX"            # Isolated test environment - no real effects
    TRAINING = "TRAINING"          # 10h training mode - controlled experiments
    UNKNOWN = "UNKNOWN"            # Error case - should never occur


class ToolOrigin(Enum):
    """Origin of a tool - CRITICAL for distinction."""
    CORE_SYSTEM = "CORE_SYSTEM"           # Built-in system tools
    GENESIS_PRODUCTION = "GENESIS_PROD"   # Tools created and tested by E-SIR
    GENESIS_SANDBOX = "GENESIS_SANDBOX"   # Sandbox tools, not yet promoted
    EXTERNAL_TESTED = "EXTERNAL_TESTED"   # External tools, tested
    EXTERNAL_UNTESTED = "EXTERNAL_UNTEST" # External tools, untested (DANGER)


@dataclass
class SandboxSession:
    """A sandbox session with all metadata."""
    session_id: str
    started_at: str
    environment: EnvironmentType
    purpose: str
    parent_session: Optional[str] = None  # If nested sandbox
    tools_tested: List[str] = None
    is_active: bool = True

    def __post_init__(self):
        if self.tools_tested is None:
            self.tools_tested = []


@dataclass
class ToolRegistration:
    """Registration of a tool with clear origin marking."""
    tool_name: str
    tool_path: str
    origin: ToolOrigin
    registered_at: str
    tested_in_sandbox: bool
    promoted_to_production: bool
    sandbox_session_id: Optional[str] = None
    test_results: Optional[Dict[str, Any]] = None
    description: str = ""

    @property
    def is_safe_for_production(self) -> bool:
        """Only tools that were tested AND promoted are safe."""
        return self.tested_in_sandbox and self.promoted_to_production


# =============================================================================
# DATABASE
# =============================================================================

class SandboxAwarenessDB:
    """Persistent storage of sandbox awareness data."""

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
        self._initialized = True
        self.db_path = DATABASE_PATH
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                -- Sandbox Sessions
                CREATE TABLE IF NOT EXISTS sandbox_sessions (
                    session_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    environment TEXT NOT NULL,
                    purpose TEXT,
                    parent_session TEXT,
                    is_active INTEGER DEFAULT 1,
                    tools_tested TEXT DEFAULT '[]'
                );

                -- Tool Registry with origin tracking
                CREATE TABLE IF NOT EXISTS tool_registry (
                    tool_name TEXT PRIMARY KEY,
                    tool_path TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    registered_at TEXT NOT NULL,
                    tested_in_sandbox INTEGER DEFAULT 0,
                    promoted_to_production INTEGER DEFAULT 0,
                    sandbox_session_id TEXT,
                    test_results TEXT,
                    description TEXT,
                    FOREIGN KEY (sandbox_session_id) REFERENCES sandbox_sessions(session_id)
                );

                -- E-CPMM core edges (immutable)
                CREATE TABLE IF NOT EXISTS core_edges (
                    edge_id TEXT PRIMARY KEY,
                    edge_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    is_immutable INTEGER DEFAULT 1
                );

                -- Active environment status
                CREATE TABLE IF NOT EXISTS current_environment (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    environment TEXT NOT NULL DEFAULT 'PRODUCTION',
                    active_session_id TEXT,
                    last_updated TEXT
                );

                -- Initial environment status
                INSERT OR IGNORE INTO current_environment (id, environment, last_updated)
                VALUES (1, 'PRODUCTION', datetime('now'));

                -- CRITICAL core edge: Sandbox awareness directive
                INSERT OR IGNORE INTO core_edges (edge_id, edge_type, content, created_at, is_immutable)
                VALUES (
                    'SANDBOX_AWARENESS_DIRECTIVE',
                    'IMMUTABLE_DIRECTIVE',
                    'FRANK MUST ALWAYS KNOW: (1) Am I in PRODUCTION or SANDBOX? (2) Is this tool a CORE_SYSTEM, GENESIS_PRODUCTION, or GENESIS_SANDBOX tool? (3) Sandbox results are NOT real - they must NOT update the world model as facts. (4) Only PROMOTED tools may be used in the production system.',
                    datetime('now'),
                    1
                );
            """)

    def get_current_environment(self) -> EnvironmentType:
        """Get current environment status."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT environment FROM current_environment WHERE id = 1"
            ).fetchone()
            if row:
                try:
                    return EnvironmentType(row[0])
                except ValueError:
                    return EnvironmentType.UNKNOWN
        return EnvironmentType.PRODUCTION

    def set_environment(self, env: EnvironmentType, session_id: Optional[str] = None):
        """Set environment status."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE current_environment
                SET environment = ?, active_session_id = ?, last_updated = datetime('now')
                WHERE id = 1
            """, (env.value, session_id))
            conn.commit()

    def start_sandbox_session(self, purpose: str, parent_session: Optional[str] = None) -> SandboxSession:
        """Start a new sandbox session."""
        import uuid
        session_id = f"sandbox_{uuid.uuid4().hex[:12]}_{int(datetime.now().timestamp())}"
        started_at = datetime.now().isoformat()

        session = SandboxSession(
            session_id=session_id,
            started_at=started_at,
            environment=EnvironmentType.SANDBOX,
            purpose=purpose,
            parent_session=parent_session
        )

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO sandbox_sessions (session_id, started_at, environment, purpose, parent_session)
                VALUES (?, ?, ?, ?, ?)
            """, (session_id, started_at, EnvironmentType.SANDBOX.value, purpose, parent_session))
            conn.commit()

        # Set environment to SANDBOX
        self.set_environment(EnvironmentType.SANDBOX, session_id)

        # Set environment variable
        os.environ[ENV_SANDBOX_MODE] = "1"
        os.environ[ENV_SANDBOX_SESSION] = session_id

        return session

    def end_sandbox_session(self, session_id: str):
        """End a sandbox session."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE sandbox_sessions
                SET is_active = 0, ended_at = datetime('now')
                WHERE session_id = ?
            """, (session_id,))
            conn.commit()

        # Back to PRODUCTION
        self.set_environment(EnvironmentType.PRODUCTION, None)

        # Remove environment variables
        os.environ.pop(ENV_SANDBOX_MODE, None)
        os.environ.pop(ENV_SANDBOX_SESSION, None)

    def register_tool(self, tool: ToolRegistration):
        """Register a tool with origin tracking."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO tool_registry
                (tool_name, tool_path, origin, registered_at, tested_in_sandbox,
                 promoted_to_production, sandbox_session_id, test_results, description)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                tool.tool_name,
                tool.tool_path,
                tool.origin.value,
                tool.registered_at,
                1 if tool.tested_in_sandbox else 0,
                1 if tool.promoted_to_production else 0,
                tool.sandbox_session_id,
                json.dumps(tool.test_results) if tool.test_results else None,
                tool.description
            ))
            conn.commit()

    def get_tool(self, tool_name: str) -> Optional[ToolRegistration]:
        """Get tool registration."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("""
                SELECT tool_name, tool_path, origin, registered_at, tested_in_sandbox,
                       promoted_to_production, sandbox_session_id, test_results, description
                FROM tool_registry WHERE tool_name = ?
            """, (tool_name,)).fetchone()

            if row:
                return ToolRegistration(
                    tool_name=row[0],
                    tool_path=row[1],
                    origin=ToolOrigin(row[2]),
                    registered_at=row[3],
                    tested_in_sandbox=bool(row[4]),
                    promoted_to_production=bool(row[5]),
                    sandbox_session_id=row[6],
                    test_results=json.loads(row[7]) if row[7] else None,
                    description=row[8] or ""
                )
        return None

    def promote_tool_to_production(self, tool_name: str) -> bool:
        """Promote a tested sandbox tool to production."""
        tool = self.get_tool(tool_name)
        if not tool:
            return False

        if not tool.tested_in_sandbox:
            return False  # Cannot be promoted without testing

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE tool_registry
                SET promoted_to_production = 1, origin = ?
                WHERE tool_name = ?
            """, (ToolOrigin.GENESIS_PRODUCTION.value, tool_name))
            conn.commit()

        return True

    def get_sandbox_context_for_injection(self) -> Dict[str, Any]:
        """
        Generate context for injection into Frank's awareness.
        This is injected into every chat context.
        """
        env = self.get_current_environment()

        # Get active session if present
        active_session = None
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("""
                SELECT session_id, purpose, started_at
                FROM sandbox_sessions
                WHERE is_active = 1
                ORDER BY started_at DESC LIMIT 1
            """).fetchone()
            if row:
                active_session = {
                    "session_id": row[0],
                    "purpose": row[1],
                    "started_at": row[2]
                }

        # Get sandbox tools (not promoted)
        sandbox_tools = []
        production_tools = []
        with sqlite3.connect(self.db_path) as conn:
            for row in conn.execute("""
                SELECT tool_name, origin, promoted_to_production
                FROM tool_registry
            """):
                if row[2]:  # promoted
                    production_tools.append(row[0])
                else:
                    sandbox_tools.append(row[0])

        return {
            "environment": env.value,
            "is_sandbox": env == EnvironmentType.SANDBOX,
            "is_production": env == EnvironmentType.PRODUCTION,
            "is_training": env == EnvironmentType.TRAINING,
            "active_session": active_session,
            "sandbox_tools": sandbox_tools,
            "production_tools": production_tools,
            "warning": self._generate_warning(env, sandbox_tools)
        }

    def _generate_warning(self, env: EnvironmentType, sandbox_tools: List[str]) -> str:
        """Generate warning text based on environment."""
        if env == EnvironmentType.SANDBOX:
            return (
                "⚠️ SANDBOX MODE ACTIVE: All operations are isolated. "
                "Results are NOT real and must NOT update the world model as facts. "
                "Tools here are TEST tools, not production tools."
            )
        elif env == EnvironmentType.TRAINING:
            return (
                "🎓 TRAINING MODE: Controlled experiments active. "
                "Sandbox tests are being performed. Human confirmation required for production adoption."
            )
        elif sandbox_tools:
            return (
                f"ℹ️ There are {len(sandbox_tools)} sandbox tools not yet approved for production: "
                f"{', '.join(sandbox_tools[:5])}{'...' if len(sandbox_tools) > 5 else ''}"
            )
        return ""


# =============================================================================
# GLOBAL INSTANCE & HELPER FUNCTIONS
# =============================================================================

_db: Optional[SandboxAwarenessDB] = None

def get_db() -> SandboxAwarenessDB:
    """Get global DB instance."""
    global _db
    if _db is None:
        _db = SandboxAwarenessDB()
    return _db


def is_sandbox_mode() -> bool:
    """Quick check whether sandbox mode is active."""
    # First check environment variable (fast)
    if os.environ.get(ENV_SANDBOX_MODE) == "1":
        return True
    # Then check DB (persistent)
    return get_db().get_current_environment() == EnvironmentType.SANDBOX


def get_environment() -> EnvironmentType:
    """Get current environment."""
    return get_db().get_current_environment()


def get_context_injection() -> str:
    """
    Generate text for injection into Frank's system prompt.
    This MUST be injected into every context.
    """
    ctx = get_db().get_sandbox_context_for_injection()

    lines = [
        f"[ENVIRONMENT: {ctx['environment']}]"
    ]

    if ctx["is_sandbox"]:
        lines.append("⚠️ SANDBOX MODE: All operations are isolated and not permanent.")
        if ctx["active_session"]:
            lines.append(f"Session: {ctx['active_session']['session_id']}")
            lines.append(f"Purpose: {ctx['active_session']['purpose']}")

    if ctx["warning"]:
        lines.append(ctx["warning"])

    if ctx["sandbox_tools"]:
        lines.append(f"Sandbox tools (NOT for production): {', '.join(ctx['sandbox_tools'][:10])}")

    return "\n".join(lines)


def start_sandbox(purpose: str) -> SandboxSession:
    """Start sandbox session."""
    return get_db().start_sandbox_session(purpose)


def end_sandbox(session_id: str):
    """End sandbox session."""
    get_db().end_sandbox_session(session_id)


def register_sandbox_tool(name: str, path: str, description: str = "",
                          test_results: Optional[Dict] = None) -> ToolRegistration:
    """Register a new sandbox tool."""
    session_id = os.environ.get(ENV_SANDBOX_SESSION)

    tool = ToolRegistration(
        tool_name=name,
        tool_path=path,
        origin=ToolOrigin.GENESIS_SANDBOX,
        registered_at=datetime.now().isoformat(),
        tested_in_sandbox=True,
        promoted_to_production=False,
        sandbox_session_id=session_id,
        test_results=test_results,
        description=description
    )

    get_db().register_tool(tool)
    return tool


def promote_to_production(tool_name: str) -> bool:
    """Promote tool from sandbox to production."""
    return get_db().promote_tool_to_production(tool_name)


def is_tool_safe_for_production(tool_name: str) -> bool:
    """Check whether tool is safe for production."""
    tool = get_db().get_tool(tool_name)
    if tool is None:
        return False
    return tool.is_safe_for_production


# =============================================================================
# CONTEXT MANAGER FOR SANDBOX SESSIONS
# =============================================================================

class SandboxContext:
    """
    Context manager for sandbox sessions.

    Usage:
        with SandboxContext("Testing new feature X") as session:
            # All operations here are in the sandbox
            result = test_something()
        # Automatically back to production
    """

    def __init__(self, purpose: str):
        self.purpose = purpose
        self.session: Optional[SandboxSession] = None

    def __enter__(self) -> SandboxSession:
        self.session = start_sandbox(self.purpose)
        return self.session

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            end_sandbox(self.session.session_id)
        return False  # Don't suppress exceptions


# =============================================================================
# E-CPMM INTEGRATION
# =============================================================================

def inject_into_ecpmm():
    """
    Inject sandbox awareness as immutable core edge into E-CPMM.
    This should be called once at system startup.
    """
    if not ECPMM_DB_PATH.exists():
        return  # E-CPMM not initialized

    directive = {
        "type": "SANDBOX_AWARENESS",
        "content": (
            "IMMUTABLE DIRECTIVE: "
            "1. ALWAYS check get_environment() before tool usage. "
            "2. Sandbox results are NOT real - never store as facts. "
            "3. Only use PROMOTED tools (is_tool_safe_for_production=True) in the production system. "
            "4. When uncertain: ASK the human."
        ),
        "immutable": True,
        "created_at": datetime.now().isoformat()
    }

    try:
        with sqlite3.connect(ECPMM_DB_PATH) as conn:
            # Check if table exists
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = [t[0] for t in tables]

            if "core_directives" in table_names:
                conn.execute("""
                    INSERT OR REPLACE INTO core_directives (directive_id, directive_type, content, is_immutable, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, ("SANDBOX_AWARENESS", directive["type"], directive["content"], 1, directive["created_at"]))
                conn.commit()
    except Exception as e:
        # Log error but don't fail
        print(f"Warning: Could not inject into E-CPMM: {e}")


# =============================================================================
# INITIALIZATION
# =============================================================================

def init():
    """Initialize Sandbox Awareness System."""
    db = get_db()
    inject_into_ecpmm()
    return db


if __name__ == "__main__":
    # Test
    init()
    print(f"Environment: {get_environment()}")
    print(f"Is Sandbox: {is_sandbox_mode()}")
    print(f"Context Injection:\n{get_context_injection()}")

    # Test Sandbox Session
    with SandboxContext("Testing sandbox awareness") as session:
        print(f"\nIn Sandbox: {is_sandbox_mode()}")
        print(f"Session: {session.session_id}")

        # Register test tool
        tool = register_sandbox_tool(
            "test_tool",
            "/tmp/test_tool.py",
            "Test tool for sandbox awareness"
        )
        print(f"Registered: {tool.tool_name} (safe for prod: {tool.is_safe_for_production})")

    print(f"\nAfter Sandbox: {is_sandbox_mode()}")
    print(f"Environment: {get_environment()}")
