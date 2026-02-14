"""
Persistent Execution State Tracker.

Maintains agent state across multiple turns:
- Current goal and plan
- Execution history
- Accumulated context
- Error tracking for retry strategies
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

LOG = logging.getLogger("agentic.state")

# Database path
try:
    from config.paths import get_db
    STATE_DB_PATH = get_db("agent_state")
except ImportError:
    STATE_DB_PATH = Path("/home/ai-core-node/.local/share/frank/db/agent_state.db")


class StepStatus(str, Enum):
    """Status of an execution step."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING_APPROVAL = "waiting_approval"


@dataclass
class ExecutionStep:
    """A single step in the execution plan."""
    id: str
    description: str
    tool_name: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None
    status: StepStatus = StepStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 3

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "description": self.description,
            "tool_name": self.tool_name,
            "tool_input": self.tool_input,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExecutionStep:
        """Create from dictionary."""
        return cls(
            id=data["id"],
            description=data["description"],
            tool_name=data.get("tool_name"),
            tool_input=data.get("tool_input"),
            status=StepStatus(data.get("status", "pending")),
            result=data.get("result"),
            error=data.get("error"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
        )

    def mark_started(self) -> None:
        """Mark step as started."""
        self.status = StepStatus.IN_PROGRESS
        self.started_at = time.time()

    def mark_completed(self, result: Dict[str, Any]) -> None:
        """Mark step as completed."""
        self.status = StepStatus.COMPLETED
        self.result = result
        self.completed_at = time.time()

    def mark_failed(self, error: str) -> None:
        """Mark step as failed."""
        self.status = StepStatus.FAILED
        self.error = error
        self.completed_at = time.time()
        self.retry_count += 1

    def can_retry(self) -> bool:
        """Check if step can be retried."""
        return self.retry_count < self.max_retries

    def duration_ms(self) -> Optional[float]:
        """Get execution duration in milliseconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at) * 1000
        return None


@dataclass
class AgentState:
    """
    Complete agent execution state.

    Persisted to SQLite for recovery across restarts.
    """
    id: str  # Unique state ID
    session_id: str  # Frank session ID for correlation
    goal: str  # The user's original goal/request
    status: str = "active"  # active, completed, failed, cancelled
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # Plan and execution
    plan_steps: List[ExecutionStep] = field(default_factory=list)
    current_step_index: int = 0

    # Accumulated context from tool results
    context: List[str] = field(default_factory=list)
    context_max_chars: int = 8000  # Limit context size

    # Conversation for this goal
    messages: List[Dict[str, str]] = field(default_factory=list)

    # Error tracking for retry strategies
    consecutive_failures: int = 0
    total_tool_calls: int = 0
    successful_tool_calls: int = 0
    total_tokens_used: int = 0

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "goal": self.goal,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "plan_steps": [s.to_dict() for s in self.plan_steps],
            "current_step_index": self.current_step_index,
            "context": self.context,
            "context_max_chars": self.context_max_chars,
            "messages": self.messages,
            "consecutive_failures": self.consecutive_failures,
            "total_tool_calls": self.total_tool_calls,
            "successful_tool_calls": self.successful_tool_calls,
            "total_tokens_used": self.total_tokens_used,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentState:
        """Deserialize from dictionary."""
        state = cls(
            id=data["id"],
            session_id=data["session_id"],
            goal=data["goal"],
            status=data.get("status", "active"),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            current_step_index=data.get("current_step_index", 0),
            context=data.get("context", []),
            context_max_chars=data.get("context_max_chars", 8000),
            messages=data.get("messages", []),
            consecutive_failures=data.get("consecutive_failures", 0),
            total_tool_calls=data.get("total_tool_calls", 0),
            successful_tool_calls=data.get("successful_tool_calls", 0),
            total_tokens_used=data.get("total_tokens_used", 0),
            metadata=data.get("metadata", {}),
        )
        state.plan_steps = [
            ExecutionStep.from_dict(s) for s in data.get("plan_steps", [])
        ]
        return state

    # ============ State Management ============

    def get_current_step(self) -> Optional[ExecutionStep]:
        """Get the current step to execute."""
        if 0 <= self.current_step_index < len(self.plan_steps):
            return self.plan_steps[self.current_step_index]
        return None

    def advance_to_next_step(self) -> Optional[ExecutionStep]:
        """Move to the next step and return it."""
        self.current_step_index += 1
        self.updated_at = time.time()
        return self.get_current_step()

    def is_complete(self) -> bool:
        """Check if all steps are complete."""
        if not self.plan_steps:
            return self.status in ("completed", "failed", "cancelled")
        return all(
            s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED)
            for s in self.plan_steps
        )

    def has_failed(self) -> bool:
        """Check if the plan has failed."""
        return self.status == "failed" or any(
            s.status == StepStatus.FAILED and not s.can_retry()
            for s in self.plan_steps
        )

    def get_progress(self) -> Dict[str, Any]:
        """Get execution progress summary."""
        total = len(self.plan_steps)
        completed = sum(1 for s in self.plan_steps if s.status == StepStatus.COMPLETED)
        failed = sum(1 for s in self.plan_steps if s.status == StepStatus.FAILED)

        return {
            "total_steps": total,
            "completed": completed,
            "failed": failed,
            "current_step": self.current_step_index,
            "percent_complete": round((completed / total) * 100, 1) if total > 0 else 0,
            "status": self.status,
        }

    # ============ Context Management ============

    def add_context(self, content: str) -> None:
        """Add execution result to context."""
        self.context.append(content)
        self._trim_context()
        self.updated_at = time.time()

    def _trim_context(self) -> None:
        """Trim context to stay within limits."""
        total_chars = sum(len(c) for c in self.context)
        while total_chars > self.context_max_chars and len(self.context) > 1:
            removed = self.context.pop(0)
            total_chars -= len(removed)

    def get_context_string(self) -> str:
        """Get accumulated context as string for LLM."""
        if not self.context:
            return ""
        return "\n---\n".join(self.context)

    # ============ Message Management ============

    def add_message(self, role: str, content: str) -> None:
        """Add a message to the conversation."""
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": time.time(),
        })
        self.updated_at = time.time()

    def get_messages_for_llm(self, max_messages: int = 10) -> List[Dict[str, str]]:
        """Get recent messages formatted for LLM."""
        recent = self.messages[-max_messages:]
        return [{"role": m["role"], "content": m["content"]} for m in recent]

    # ============ Error Handling ============

    def record_failure(self) -> None:
        """Record a failure for retry strategy."""
        self.consecutive_failures += 1
        self.updated_at = time.time()

    def record_success(self) -> None:
        """Record a success (resets consecutive failures)."""
        self.consecutive_failures = 0
        self.successful_tool_calls += 1
        self.updated_at = time.time()

    def should_abort(self, max_consecutive_failures: int = 5) -> bool:
        """Check if agent should abort due to too many failures."""
        return self.consecutive_failures >= max_consecutive_failures

    # ============ Plan Management ============

    def set_plan(self, steps: List[ExecutionStep]) -> None:
        """Set the execution plan."""
        self.plan_steps = steps
        self.current_step_index = 0
        self.updated_at = time.time()

    def replan(self, new_steps: List[ExecutionStep]) -> None:
        """Replace remaining steps with new plan."""
        # Keep completed steps
        completed = [s for s in self.plan_steps if s.status == StepStatus.COMPLETED]
        self.plan_steps = completed + new_steps
        self.current_step_index = len(completed)
        self.updated_at = time.time()

    def mark_completed(self, final_response: str = "") -> None:
        """Mark the entire goal as completed."""
        self.status = "completed"
        self.updated_at = time.time()
        if final_response:
            self.metadata["final_response"] = final_response

    def mark_failed(self, reason: str = "") -> None:
        """Mark the entire goal as failed."""
        self.status = "failed"
        self.updated_at = time.time()
        if reason:
            self.metadata["failure_reason"] = reason

    def mark_cancelled(self) -> None:
        """Mark the goal as cancelled by user."""
        self.status = "cancelled"
        self.updated_at = time.time()


class StateStore:
    """
    SQLite-backed persistent state storage.

    Thread-safe with connection pooling.
    """

    def __init__(self, db_path: Path = STATE_DB_PATH):
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local connection."""
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(str(self.db_path))
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self) -> None:
        """Initialize database schema."""
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = self._get_conn()
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS agent_states (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                goal TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                state_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_session ON agent_states(session_id);
            CREATE INDEX IF NOT EXISTS idx_status ON agent_states(status);
            CREATE INDEX IF NOT EXISTS idx_updated ON agent_states(updated_at DESC);

            -- Execution log for debugging/analysis
            CREATE TABLE IF NOT EXISTS execution_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                state_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_data TEXT,
                timestamp REAL NOT NULL,
                FOREIGN KEY (state_id) REFERENCES agent_states(id)
            );

            CREATE INDEX IF NOT EXISTS idx_log_state ON execution_log(state_id);
        """)
            conn.commit()
            LOG.info(f"StateStore initialized at {self.db_path}")
        except sqlite3.Error as e:
            LOG.error(f"Failed to initialize database at {self.db_path}: {e}")
            raise

    def save(self, state: AgentState) -> None:
        """Save or update agent state."""
        try:
            conn = self._get_conn()
            state_json = json.dumps(state.to_dict(), ensure_ascii=False)
            conn.execute("""
                INSERT OR REPLACE INTO agent_states
                (id, session_id, goal, status, state_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                state.id,
                state.session_id,
                state.goal,
                state.status,
                state_json,
                state.created_at,
                state.updated_at,
            ))
            conn.commit()
        except (json.JSONEncodeError, sqlite3.Error) as e:
            LOG.error(f"Failed to save agent state {state.id}: {e}")
            raise

    def load(self, state_id: str) -> Optional[AgentState]:
        """Load agent state by ID."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT state_json FROM agent_states WHERE id = ?",
            (state_id,)
        ).fetchone()
        if row:
            return AgentState.from_dict(json.loads(row["state_json"]))
        return None

    def load_active_for_session(self, session_id: str) -> Optional[AgentState]:
        """Load active agent state for a session."""
        conn = self._get_conn()
        row = conn.execute("""
            SELECT state_json FROM agent_states
            WHERE session_id = ? AND status = 'active'
            ORDER BY updated_at DESC LIMIT 1
        """, (session_id,)).fetchone()
        if row:
            return AgentState.from_dict(json.loads(row["state_json"]))
        return None

    def list_recent(self, limit: int = 20) -> List[AgentState]:
        """List recent agent states."""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT state_json FROM agent_states
            ORDER BY updated_at DESC LIMIT ?
        """, (limit,)).fetchall()
        return [AgentState.from_dict(json.loads(r["state_json"])) for r in rows]

    def log_event(self, state_id: str, event_type: str, event_data: Any = None) -> None:
        """Log an execution event for debugging."""
        conn = self._get_conn()
        data_json = json.dumps(event_data, ensure_ascii=False) if event_data else None
        conn.execute("""
            INSERT INTO execution_log (state_id, event_type, event_data, timestamp)
            VALUES (?, ?, ?, ?)
        """, (state_id, event_type, data_json, time.time()))
        conn.commit()

    def cleanup_old(self, days: int = 7) -> int:
        """Delete states older than N days. Returns count deleted."""
        conn = self._get_conn()
        cutoff = time.time() - (days * 24 * 3600)
        cursor = conn.execute("""
            DELETE FROM agent_states
            WHERE updated_at < ? AND status IN ('completed', 'failed', 'cancelled')
        """, (cutoff,))
        deleted = cursor.rowcount
        conn.execute("DELETE FROM execution_log WHERE state_id NOT IN (SELECT id FROM agent_states)")
        conn.commit()
        return deleted


# Global singleton with thread-safe initialization
_store: Optional[StateStore] = None
_store_lock = threading.Lock()


def get_store() -> StateStore:
    """Get the global state store (thread-safe)."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:  # Double-check inside lock
                _store = StateStore()
    return _store
