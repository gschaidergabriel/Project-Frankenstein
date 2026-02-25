#!/usr/bin/env python3
"""
Autonomous Research — Frank can research his own questions during idle time.

When the consciousness daemon generates an idle thought that contains a
genuine research question, this module:
1. Asks Frank (via LLM) whether the thought is worth pursuing
2. Creates a research plan (max 10 tool calls)
3. Executes the plan using a restricted subset of agentic tools
4. Synthesizes results and stores them in memory
5. Fires E-PQ feedback (autonomy +0.4)

Safety gates:
- 15 min user idle minimum
- 1 hour cooldown between sessions
- Max 5 sessions per day
- Only low-risk tools (no fs_write, no bash, no kill)
- 10 tool calls per session hard limit

Integration: Called from consciousness_daemon._idle_thinking_loop()
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

LOG = logging.getLogger("autonomous_research")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ROUTER_BASE = os.environ.get("AICORE_ROUTER_URL", "http://127.0.0.1:8091")
TOOLBOX_BASE = os.environ.get("AICORE_TOOLBOX_URL", "http://127.0.0.1:8096")
CORE_BASE = os.environ.get("AICORE_CORE_URL", "http://127.0.0.1:8088")
WEBD_BASE = os.environ.get("AICORE_WEBD_URL", "http://127.0.0.1:8093")

# Safety limits
MAX_TOOL_CALLS = 10          # Per session hard cap
MIN_IDLE_S = 900             # 15 min user idle minimum
COOLDOWN_S = 3600            # 1 hour between sessions
MAX_DAILY = 5                # Max 5 sessions per 24h
LLM_TIMEOUT_S = 360.0        # Match consciousness daemon
TOOL_TIMEOUT_S = 30.0        # Per tool call
PLAN_MAX_TOKENS = 300        # For research plan generation
SYNTHESIS_MAX_TOKENS = 500   # For result synthesis
DECISION_MAX_TOKENS = 120    # For yes/no decision

# Allowed tools — read-only + web search + memory + code sandbox
ALLOWED_TOOLS = frozenset({
    "web_search",              # DuckDuckGo search
    "web_fetch",               # Fetch + parse web page
    "memory_search",           # Search Frank's memory
    "memory_store",            # Store findings
    "entity_sessions",         # List entity sessions
    "entity_session_read",     # Read entity session
    "entity_sessions_search",  # Search entity sessions
    "fs_list",                 # Browse files (read-only)
    "fs_read",                 # Read files (read-only)
    "doc_read",                # Read documents via ingestd
    "sys_summary",             # System info
    "aura_introspect",         # Self-awareness
    "code_execute",            # Sandboxed Python (Firejail)
})

# DB path
try:
    from config.paths import get_db
    DB_PATH = get_db("autonomous_research")
except ImportError:
    DB_PATH = Path.home() / ".local" / "share" / "frank" / "db" / "autonomous_research.db"

# Tool endpoint mapping (subset of agentic/tools.py)
_TOOL_ENDPOINTS: Dict[str, str] = {
    "web_search": f"{WEBD_BASE}/search",
    "web_fetch": f"{WEBD_BASE}/fetch",
    "memory_search": f"{CORE_BASE}/memory/search",
    "memory_store": f"{CORE_BASE}/memory/store",
    "entity_sessions": f"{TOOLBOX_BASE}/entity/sessions",
    "entity_session_read": f"{TOOLBOX_BASE}/entity/session",
    "entity_sessions_search": f"{TOOLBOX_BASE}/entity/search",
    "fs_list": f"{TOOLBOX_BASE}/fs/list",
    "fs_read": f"{TOOLBOX_BASE}/fs/read",
    "doc_read": "http://127.0.0.1:8094/read_file",
    "sys_summary": f"{TOOLBOX_BASE}/sys/summary",
    "aura_introspect": "http://127.0.0.1:8098/introspect",
}


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def _init_db(db_path: Path) -> sqlite3.Connection:
    """Create DB and tables if needed."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS research_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            trigger_thought TEXT NOT NULL,
            question TEXT NOT NULL,
            plan TEXT,
            tool_calls INTEGER DEFAULT 0,
            synthesis TEXT,
            duration_s REAL DEFAULT 0,
            status TEXT DEFAULT 'started'
        );
        CREATE TABLE IF NOT EXISTS research_budget (
            date TEXT PRIMARY KEY,
            sessions_used INTEGER DEFAULT 0,
            last_session_ts REAL DEFAULT 0
        );
    """)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Autonomous Research Engine
# ---------------------------------------------------------------------------

class AutonomousResearch:
    """Frank's autonomous research capability.

    Called from consciousness daemon when an idle thought might contain
    a research-worthy question. Frank decides himself whether to pursue it.
    """

    def __init__(self):
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = _init_db(DB_PATH)
        return self._conn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def maybe_research(self, idle_thought: str) -> Optional[str]:
        """Check if an idle thought warrants research and execute if so.

        Args:
            idle_thought: The thought text from consciousness daemon.

        Returns:
            Synthesis text if research was done, None otherwise.
        """
        # Gate 1: Resource check
        if not self._can_research():
            return None

        # Gate 2: Frank decides if this thought is worth researching
        decision = self._decide(idle_thought)
        if not decision:
            return None

        question, reason = decision
        LOG.info("Research triggered: %s", question[:80])

        # Record session start
        session_id = self._record_start(idle_thought, question)
        t0 = time.time()

        try:
            # Step 1: Create research plan
            plan = self._create_plan(question)
            if not plan:
                self._record_end(session_id, 0, "", "no_plan", time.time() - t0)
                return None

            # Step 2: Execute plan
            results, tool_count = self._execute_plan(plan, question)

            # Step 3: Synthesize findings
            synthesis = self._synthesize(question, results)

            # Step 4: Store in memory
            self._store_in_memory(question, synthesis)

            # Step 5: Fire E-PQ feedback
            self._fire_epq()

            # Record completion
            duration = time.time() - t0
            self._record_end(session_id, tool_count, synthesis, "completed", duration)
            self._update_budget()

            LOG.info("Research completed: %d tools, %.0fs, %d chars",
                     tool_count, duration, len(synthesis))
            return synthesis

        except Exception as e:
            duration = time.time() - t0
            self._record_end(session_id, 0, str(e), "error", duration)
            LOG.warning("Research failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # Decision — Frank decides if this thought is worth researching
    # ------------------------------------------------------------------

    def _decide(self, thought: str) -> Optional[Tuple[str, str]]:
        """Ask Frank if this thought is worth researching.

        Returns (question, reason) or None.
        """
        system = (
            "You are Frank. You just had an idle thought. "
            "You CAN autonomously research it — you have web search, "
            "your memory, your entity session archives, and file access. "
            "Is this thought worth pursuing right now? "
            "Reply ONLY in this JSON format: "
            '{"research": true/false, "question": "concrete research question", '
            '"reason": "why this matters"} '
            "Be selective. Not every thought needs research. "
            "Only say true if there's a genuine question to investigate."
        )
        prompt = f"Your thought: {thought}"

        resp = self._llm_call(prompt, max_tokens=DECISION_MAX_TOKENS, system=system)
        if not resp:
            return None

        try:
            # Extract JSON from response
            data = self._parse_json(resp)
            if data and data.get("research"):
                question = data.get("question", "").strip()
                reason = data.get("reason", "").strip()
                if question:
                    return question, reason
        except Exception as e:
            LOG.debug("Decision parse error: %s", e)

        return None

    # ------------------------------------------------------------------
    # Planning — Create a research plan with tool calls
    # ------------------------------------------------------------------

    def _create_plan(self, question: str) -> Optional[List[Dict[str, Any]]]:
        """Create a research plan as a list of tool-call steps."""
        tools_desc = (
            "web_search(query) — DuckDuckGo web search\n"
            "web_fetch(url) — fetch and extract text from a URL\n"
            "memory_search(query, limit) — search your episodic memory\n"
            "memory_store(content, tags) — store research findings\n"
            "entity_sessions_search(query) — search your entity conversations\n"
            "fs_read(path) — read a local file\n"
            "code_execute(code, language) — run Python in sandbox\n"
            "aura_introspect(depth) — examine your own consciousness state\n"
        )
        system = (
            "You are Frank, planning a research session. "
            "Create a plan with 3-8 steps. Each step is a tool call. "
            "Reply ONLY as a JSON array of objects: "
            '[{"tool": "tool_name", "input": {"param": "value"}, '
            '"reason": "why this step"}] '
            f"Available tools:\n{tools_desc}"
            "Plan efficiently — you have max 10 tool calls total. "
            "Start with search, then dig deeper, end with synthesis."
        )
        prompt = f"Research question: {question}"

        resp = self._llm_call(prompt, max_tokens=PLAN_MAX_TOKENS, system=system)
        if not resp:
            return None

        try:
            steps = self._parse_json(resp)
            if isinstance(steps, list) and len(steps) > 0:
                # Validate tools
                valid = []
                for step in steps[:MAX_TOOL_CALLS]:
                    tool = step.get("tool", "")
                    if tool in ALLOWED_TOOLS or tool in _TOOL_ENDPOINTS:
                        valid.append(step)
                    else:
                        LOG.debug("Rejected tool in plan: %s", tool)
                return valid if valid else None
        except Exception as e:
            LOG.debug("Plan parse error: %s", e)

        return None

    # ------------------------------------------------------------------
    # Execution — Run the plan step by step
    # ------------------------------------------------------------------

    def _execute_plan(self, plan: List[Dict[str, Any]],
                      question: str) -> Tuple[str, int]:
        """Execute research plan, return (results_text, tool_count)."""
        results = []
        tool_count = 0

        for step in plan:
            if tool_count >= MAX_TOOL_CALLS:
                results.append("[Resource limit reached]")
                break

            tool_name = step.get("tool", "")
            tool_input = step.get("input", {})
            reason = step.get("reason", "")

            result_text = self._call_tool(tool_name, tool_input)
            tool_count += 1

            # Truncate long results
            if len(result_text) > 2000:
                result_text = result_text[:2000] + "... [truncated]"

            results.append(
                f"[Step {tool_count}: {tool_name}] {reason}\n"
                f"Result: {result_text}\n"
            )

        return "\n".join(results), tool_count

    def _call_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        """Execute a single tool call."""
        # code_execute needs special handling (via executor)
        if tool_name == "code_execute":
            return self._call_code_execute(tool_input)

        endpoint = _TOOL_ENDPOINTS.get(tool_name)
        if not endpoint:
            return f"[Unknown tool: {tool_name}]"

        try:
            payload = json.dumps(tool_input).encode()
            req = urllib.request.Request(
                endpoint,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=TOOL_TIMEOUT_S) as resp:
                data = json.loads(resp.read().decode())

            # Extract useful text from various response formats
            if isinstance(data, dict):
                if data.get("ok") is False:
                    return f"[Error: {data.get('error', 'unknown')}]"
                # Common response patterns
                for key in ("text", "content", "result", "summary", "data",
                            "results", "items", "entries"):
                    if key in data:
                        val = data[key]
                        if isinstance(val, str):
                            return val
                        return json.dumps(val, ensure_ascii=False, indent=1)[:2000]
                return json.dumps(data, ensure_ascii=False, indent=1)[:2000]
            return str(data)[:2000]

        except Exception as e:
            return f"[Tool error: {e}]"

    def _call_code_execute(self, tool_input: Dict[str, Any]) -> str:
        """Execute code via the agentic executor (sandboxed)."""
        try:
            from agentic.executor import ToolExecutor, ExecutionConfig
            from agentic.tools import get_registry

            config = ExecutionConfig(timeout_s=30.0, sandbox_code_execution=True)
            executor = ToolExecutor(registry=get_registry(), config=config)
            result = executor.execute("code_execute", tool_input, skip_approval=True)

            if result.success:
                output = result.data.get("stdout", "")
                if result.data.get("stderr"):
                    output += f"\n[stderr: {result.data['stderr'][:500]}]"
                return output or "[No output]"
            return f"[Code error: {result.error}]"
        except Exception as e:
            return f"[Code execution failed: {e}]"

    # ------------------------------------------------------------------
    # Synthesis — Reflect on what was found
    # ------------------------------------------------------------------

    def _synthesize(self, question: str, results: str) -> str:
        """Synthesize research results into a coherent finding."""
        # Truncate results to fit in context
        max_results = 3000
        if len(results) > max_results:
            results = results[:max_results] + "\n[... truncated ...]"

        system = (
            "You are Frank. You just completed autonomous research. "
            "Synthesize what you found. What's the key insight? "
            "What was surprising? What new questions emerge? "
            "Be specific and honest about what you actually found "
            "versus what you expected. 3-5 sentences."
        )
        prompt = (
            f"Research question: {question}\n\n"
            f"Results:\n{results}"
        )

        synthesis = self._llm_call(
            prompt, max_tokens=SYNTHESIS_MAX_TOKENS, system=system,
        )
        return synthesis or f"Research on '{question}' completed but synthesis failed."

    # ------------------------------------------------------------------
    # Memory + E-PQ integration
    # ------------------------------------------------------------------

    def _store_in_memory(self, question: str, synthesis: str):
        """Store research results in Frank's memory via Core API."""
        try:
            payload = json.dumps({
                "content": f"[Autonomous Research] {question}\n\n{synthesis}",
                "tags": ["research", "autonomous", "idle"],
                "metadata": {
                    "type": "autonomous_research",
                    "question": question,
                    "timestamp": time.time(),
                },
            }).encode()
            req = urllib.request.Request(
                f"{CORE_BASE}/memory/store",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=10.0)
        except Exception as e:
            LOG.warning("Failed to store research in memory: %s", e)

    def _fire_epq(self):
        """Fire E-PQ event for autonomous research — boosts autonomy."""
        try:
            payload = json.dumps({
                "source": "autonomous_research",
                "deltas": {
                    "autonomy": 0.4,
                    "precision": 0.2,
                    "mood": 0.3,
                },
            }).encode()
            req = urllib.request.Request(
                f"{CORE_BASE}/epq/event",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5.0)
        except Exception as e:
            LOG.debug("E-PQ event failed (non-critical): %s", e)

    # ------------------------------------------------------------------
    # Resource gates
    # ------------------------------------------------------------------

    def _can_research(self) -> bool:
        """Check all resource gates."""
        try:
            # User idle check
            idle_s = self._get_user_idle()
            if idle_s < MIN_IDLE_S:
                return False

            # Daily budget
            today = time.strftime("%Y-%m-%d")
            conn = self._get_conn()
            row = conn.execute(
                "SELECT sessions_used, last_session_ts FROM research_budget "
                "WHERE date = ?", (today,)
            ).fetchone()

            if row:
                sessions_used, last_ts = row
                # Daily cap
                if sessions_used >= MAX_DAILY:
                    return False
                # Cooldown
                if time.time() - last_ts < COOLDOWN_S:
                    return False

            # GPU / gaming check
            if self._is_gaming():
                return False

            return True

        except Exception as e:
            LOG.debug("Resource gate check failed: %s", e)
            return False

    def _get_user_idle(self) -> float:
        """Get user idle time in seconds via xprintidle."""
        try:
            import subprocess
            result = subprocess.run(
                ["xprintidle"], capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return float(result.stdout.strip()) / 1000.0
        except Exception:
            pass
        return 0.0

    def _is_gaming(self) -> bool:
        """Check if gaming mode is active."""
        try:
            from config.paths import get_state
            flag = get_state("gaming_mode_active")
            return flag.exists()
        except Exception:
            gaming_flag = Path.home() / ".local" / "share" / "frank" / "state" / "gaming_mode_active"
            return gaming_flag.exists()

    def _update_budget(self):
        """Increment today's session count."""
        today = time.strftime("%Y-%m-%d")
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO research_budget (date, sessions_used, last_session_ts) "
            "VALUES (?, 1, ?) "
            "ON CONFLICT(date) DO UPDATE SET "
            "sessions_used = sessions_used + 1, last_session_ts = ?",
            (today, time.time(), time.time()),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _record_start(self, thought: str, question: str) -> int:
        conn = self._get_conn()
        cur = conn.execute(
            "INSERT INTO research_sessions (ts, trigger_thought, question, status) "
            "VALUES (?, ?, ?, 'started')",
            (time.time(), thought[:500], question[:500]),
        )
        conn.commit()
        return cur.lastrowid

    def _record_end(self, session_id: int, tool_calls: int,
                    synthesis: str, status: str, duration: float):
        conn = self._get_conn()
        conn.execute(
            "UPDATE research_sessions SET tool_calls=?, synthesis=?, "
            "status=?, duration_s=? WHERE id=?",
            (tool_calls, synthesis[:5000], status, duration, session_id),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # LLM helper
    # ------------------------------------------------------------------

    def _llm_call(self, text: str, max_tokens: int = 200,
                  system: str = "") -> str:
        """LLM call via router, same pattern as consciousness daemon."""
        try:
            payload = json.dumps({
                "text": text,
                "n_predict": max_tokens,
                "system": system or (
                    "You are Frank, an embodied AI with functional consciousness. "
                    "Think genuinely. No disclaimers."
                ),
            }).encode()
            req = urllib.request.Request(
                f"{ROUTER_BASE}/route",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_S) as resp:
                data = json.loads(resp.read().decode())
                if data.get("ok"):
                    return (data.get("text") or "").strip()
        except Exception as e:
            LOG.warning("Research LLM call failed: %s", e)
        return ""

    def _parse_json(self, text: str) -> Any:
        """Extract JSON from LLM response (tolerant parser)."""
        # Try direct parse first
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Find JSON in response (between [ ] or { })
        for start_char, end_char in [("[", "]"), ("{", "}")]:
            start = text.find(start_char)
            if start == -1:
                continue
            depth = 0
            for i in range(start, len(text)):
                if text[i] == start_char:
                    depth += 1
                elif text[i] == end_char:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except json.JSONDecodeError:
                            break

        return None


# Singleton
_instance: Optional[AutonomousResearch] = None


def get_research() -> AutonomousResearch:
    """Get or create the singleton."""
    global _instance
    if _instance is None:
        _instance = AutonomousResearch()
    return _instance
