"""
Agentic Loop - The core Think-Act-Observe execution cycle.

This is the heart of Frank's agentic behavior:
1. THINK: Analyze current state, decide next action
2. ACT: Execute the chosen tool
3. OBSERVE: Process result, update state
4. ITERATE: Continue until goal achieved or failure

Integrates with:
- Planner for goal decomposition
- Executor for safe tool execution
- State for persistent tracking
- E-SIR for risk assessment
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
import logging

from .tools import (
    ToolRegistry,
    ToolResult,
    ParsedToolCall,
    get_registry,
    parse_tool_call,
    validate_tool_call,
)
from .state import (
    AgentState,
    ExecutionStep,
    StepStatus,
    StateStore,
    get_store,
)
from .planner import Planner, Plan, analyze_and_plan
from .executor import ToolExecutor, ExecutionConfig

LOG = logging.getLogger("agentic.loop")


@dataclass
class AgentConfig:
    """Configuration for the agent loop."""
    max_iterations: int = 20  # Maximum think-act-observe cycles
    max_consecutive_failures: int = 8  # Qwen 7B has ~30% JSON parse rate, needs headroom
    thinking_timeout_s: float = 60.0
    execution_timeout_s: float = 120.0
    auto_approve_risk_threshold: float = 0.3
    require_approval_risk_threshold: float = 0.6
    enable_replanning: bool = True
    max_replans: int = 3
    verbose: bool = True


@dataclass
class AgentEvent:
    """Event emitted during agent execution."""
    event_type: str  # thinking, acting, observing, completed, failed, waiting_approval
    data: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)


# Type alias for event callback
EventCallback = Callable[[AgentEvent], None]


# System prompt for the agent's reasoning
AGENT_SYSTEM_PROMPT = """You are a code agent. Respond ONLY with a JSON tool call.

## Goal
{goal}

## Context
{context}

## Plan
{plan}

## Available Tools
- fs_list: List a DIRECTORY. Input: {{"path":"/some/dir/"}}. Do NOT use on files!
- fs_read: Read a FILE's contents. Input: {{"path":"/some/file.py"}}. Use for code, configs, text.
- fs_write: Write a file. Input: {{"path":"...","content":"...","overwrite":true}}.
- bash_execute: Run a shell command. Input: {{"command":"..."}}.
  Use for: sqlite3 (DB inspection), python3, grep, find, etc.
- final_answer: Return your result. Input: {{"response":"Your answer here"}}.

## Rules
1. Respond with ONLY a JSON object — no text, no markdown, no explanation.
2. Use REAL paths from the context — never placeholders.
3. For ANALYSIS: Read at least 5 source files with fs_read before calling final_answer.
   Skip __init__.py and trivial files — read the MAIN modules (.py files over 50 lines).
4. For CREATION: mkdir with bash_execute, then fs_write files.
5. NEVER repeat the same tool call with the same arguments — try a different approach.
6. After reading files, THINK about what you found and report via final_answer.
7. Do NOT use fs_list on a file path — use fs_read instead.
8. For SQLite databases (.db files): Use bash_execute with sqlite3, e.g.:
   {{"action":"bash_execute","action_input":{{"command":"sqlite3 /path/to/db '.schema' 2>&1 | head -50"}}}}

## JSON Format Examples
{{"action":"fs_list","action_input":{{"path":"/home/user/project/"}}}}
{{"action":"fs_read","action_input":{{"path":"/home/user/project/main.py"}}}}
{{"action":"bash_execute","action_input":{{"command":"sqlite3 /path/db '.tables'"}}}}
{{"action":"final_answer","action_input":{{"response":"Found 2 bugs: ..."}}}}
"""


class AgentLoop:
    """
    The main agentic execution loop.

    Implements the Think-Act-Observe cycle for autonomous task completion.
    """

    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        tool_registry: Optional[ToolRegistry] = None,
        state_store: Optional[StateStore] = None,
        event_callback: Optional[EventCallback] = None,
        llm_endpoint: str = "http://127.0.0.1:8091/route",
    ):
        self.config = config or AgentConfig()
        self.registry = tool_registry or get_registry()
        self.store = state_store or get_store()
        self.event_callback = event_callback
        self.llm_endpoint = llm_endpoint
        self._cancelled = False

        self.executor = ToolExecutor(
            registry=self.registry,
            config=ExecutionConfig(
                timeout_s=self.config.execution_timeout_s,
                require_approval_above_risk=self.config.require_approval_risk_threshold,
                auto_approve_below_risk=self.config.auto_approve_risk_threshold,
            ),
        )
        self.planner = Planner(tool_registry=self.registry)

        self._current_state: Optional[AgentState] = None
        self._replan_count = 0

    def run(
        self,
        goal: str,
        session_id: str,
        initial_context: str = "",
    ) -> Tuple[str, AgentState]:
        """
        Run the agent loop for a goal.

        Args:
            goal: The user's goal/request
            session_id: Session ID for state correlation
            initial_context: Optional initial context

        Returns:
            Tuple of (final_response, final_state)
        """
        # Create initial state
        state = AgentState(
            id=f"agent_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            goal=goal,
        )

        if initial_context:
            state.add_context(initial_context)

        self._current_state = state
        self._replan_count = 0

        # Create initial plan
        self._emit_event("planning", {"goal": goal})
        plan, clarification = analyze_and_plan(goal, initial_context, self.registry)

        if clarification:
            # Need more info from user
            state.add_message("assistant", clarification)
            state.status = "waiting_input"
            self.store.save(state)
            return clarification, state

        # Set execution plan
        state.set_plan(plan.to_execution_steps())
        state.add_message("user", goal)
        self.store.save(state)

        LOG.info(f"Starting agent loop for: {goal[:50]}...")
        self._emit_event("started", {"goal": goal, "steps": len(state.plan_steps)})

        # Main execution loop
        try:
            result = self._run_loop(state)
            return result
        except Exception as e:
            LOG.exception(f"Agent loop failed: {e}")
            state.mark_failed(str(e))
            self.store.save(state)
            self._emit_event("failed", {"error": str(e)})
            return f"Execution error: {e}", state

    def _capture_visual_context(self, context: str) -> None:
        """Capture error screenshot for visual debugging (non-blocking, rate-limited)."""
        try:
            from tools.vcb_bridge import capture_error_screenshot
            capture_error_screenshot(context)
        except Exception:
            pass  # Non-critical, never block the loop

    def _run_loop(self, state: AgentState) -> Tuple[str, AgentState]:
        """Main execution loop."""
        iteration = 0
        # Track previous tool calls to detect duplicates
        _prev_tool_calls: List[str] = []
        _consecutive_parse_failures = 0

        while iteration < self.config.max_iterations:
            iteration += 1
            LOG.debug(f"Iteration {iteration}/{self.config.max_iterations}")

            # Check cancel
            if self._cancelled:
                state.mark_cancelled()
                self.store.save(state)
                self._emit_event("failed", {"error": "Cancelled by user"})
                return "Task cancelled.", state

            # Check abort conditions
            if state.should_abort(self.config.max_consecutive_failures):
                # Before aborting: if we have any successful reads, force a final_answer
                if state.successful_tool_calls > 0:
                    state.add_context(
                        "INSTRUCTION: You have read files successfully. "
                        "Now call final_answer with your findings. Do NOT call more tools."
                    )
                    self._emit_event("thinking", {"iteration": iteration})
                    thought, tool_call = self._think(state)
                    if tool_call and tool_call.is_final_answer:
                        response = tool_call.action_input.get("response", "Analysis complete.")
                        state.mark_completed(response)
                        self.store.save(state)
                        self._emit_event("completed", {"response": response})
                        return response, state

                self._capture_visual_context(
                    f"Agentic loop abort: {state.consecutive_failures} consecutive failures, goal: {state.goal[:80]}"
                )
                state.mark_failed("Too many consecutive failures")
                self.store.save(state)
                return "Too many consecutive errors. Aborting.", state

            # THINK: Analyze state and decide action
            self._emit_event("thinking", {"iteration": iteration, "total": self.config.max_iterations})
            thought, tool_call = self._think(state)

            if thought:
                state.add_message("assistant", thought)

            # Check if done — block premature final_answer
            if tool_call and tool_call.is_final_answer:
                # Detect analysis tasks (need to read multiple files)
                goal_lower = state.goal.lower()
                _is_analysis = any(w in goal_lower for w in [
                    "bug", "error", "issue", "review", "search", "find", "scan",
                    "check", "inspect", "analyze", "analyse", "debug",
                    "such", "prüf", "pruef", "fehler", "untersuche", "analysiere",
                ])
                min_tools = 5 if _is_analysis else 1  # Analysis: read multiple files

                if state.successful_tool_calls < min_tools and iteration <= min_tools + 2:
                    LOG.warning(
                        f"Blocked premature final_answer "
                        f"({state.successful_tool_calls}/{min_tools} tools, iter {iteration})"
                    )
                    state.record_failure()
                    state.add_context(
                        f"BLOCKED: You only used {state.successful_tool_calls} tools. "
                        f"For analysis tasks, you must read at least {min_tools} files before concluding. "
                        f"Read more source files with fs_read — check the main Python modules, "
                        f"not just __init__.py files."
                    )
                    self.store.save(state)
                    continue
                response = tool_call.action_input.get("response", "Task completed.")
                state.mark_completed(response)
                self.store.save(state)
                self._emit_event("completed", {"response": response})
                return response, state

            # Check for user question
            if tool_call and tool_call.action == "ask_user":
                question = tool_call.action_input.get("question", "Can you explain that in more detail?")
                state.add_message("assistant", question)
                state.status = "waiting_input"
                self.store.save(state)
                return question, state

            # No valid action — give parse format reminder
            if not tool_call:
                _consecutive_parse_failures += 1
                state.record_failure()

                # After multiple parse failures, inject a strong JSON reminder
                if _consecutive_parse_failures >= 2:
                    state.add_context(
                        'PARSE ERROR: Your response was not valid JSON. '
                        'Respond with ONLY a JSON object like: '
                        '{"action":"fs_read","action_input":{"path":"/some/file.py"}} '
                        'NO text before or after the JSON.'
                    )

                # After many parse failures, force final_answer if we have results
                if _consecutive_parse_failures >= 4 and state.successful_tool_calls > 0:
                    state.add_context(
                        "INSTRUCTION: Too many parse failures. Call final_answer NOW with whatever you found so far."
                    )

                if self.config.enable_replanning and self._replan_count < self.config.max_replans:
                    self._replan(state, "No valid action parsed from response")
                    continue
                else:
                    return thought or "I could not find a suitable action.", state

            _consecutive_parse_failures = 0  # Reset on successful parse

            # Duplicate tool call detection
            call_sig = f"{tool_call.action}:{json.dumps(tool_call.action_input, sort_keys=True)}"
            if call_sig in _prev_tool_calls:
                LOG.warning(f"Duplicate tool call detected: {call_sig[:100]}")
                state.record_failure()
                state.add_context(
                    f"DUPLICATE: You already called {tool_call.action} with these exact arguments. "
                    f"Try a DIFFERENT tool or different arguments. "
                    f"Available tools: fs_read (read files), fs_list (list directories), "
                    f"bash_execute (run commands like sqlite3), final_answer (report findings)."
                )
                self.store.save(state)
                continue
            _prev_tool_calls.append(call_sig)

            # Validate tool call
            validation_error = validate_tool_call(tool_call, self.registry)
            if validation_error:
                state.record_failure()
                state.add_context(f"Validation error: {validation_error}")
                self.store.save(state)
                continue

            # ACT: Execute the tool
            self._emit_event("acting", {
                "tool": tool_call.action,
                "input": tool_call.action_input,
            })

            # Auto-approve tools in agentic mode — user consented by
            # triggering agentic execution.  Bash safety checks in
            # _execute_bash() still block truly dangerous commands.
            result = self.executor.execute(
                tool_call.action,
                tool_call.action_input,
                skip_approval=True,
            )

            # OBSERVE: Process result
            self._emit_event("observing", {
                "tool": tool_call.action,
                "success": result.success,
            })

            state.total_tool_calls += 1

            if result.success:
                state.record_success()
                self._replan_count = 0  # Reset replan count on success
                state.add_context(result.to_context())

                # Update step if tracking
                current_step = state.get_current_step()
                if current_step and current_step.tool_name == tool_call.action:
                    current_step.mark_completed(result.data)
                    state.advance_to_next_step()
            else:
                state.record_failure()
                state.add_context(f"FAILED: {result.error}")

                # Capture visual context on tool failure (rate-limited)
                if state.consecutive_failures >= 2:
                    self._capture_visual_context(
                        f"Tool '{tool_call.action}' failed ({state.consecutive_failures}x): {result.error}"
                    )

                # Replan on failure
                if self.config.enable_replanning and self._replan_count < self.config.max_replans:
                    self._replan(state, result.error or "Tool execution failed")

            self.store.save(state)

        # Max iterations reached
        state.mark_failed("Maximum iterations reached")
        self.store.save(state)
        return "Maximum number of steps reached. Please clarify your goal.", state

    def _think(self, state: AgentState) -> Tuple[str, Optional[ParsedToolCall]]:
        """
        Think phase: Analyze state and decide next action.

        Returns (thought_text, parsed_tool_call)
        """
        # Build prompt
        context = state.get_context_string() or "No actions executed yet."

        plan_desc = "No plan."
        if state.plan_steps:
            plan_lines = []
            for i, step in enumerate(state.plan_steps):
                status_icon = {
                    StepStatus.COMPLETED: "✓",
                    StepStatus.FAILED: "✗",
                    StepStatus.IN_PROGRESS: "→",
                    StepStatus.PENDING: "○",
                }.get(step.status, "?")
                plan_lines.append(f"{status_icon} {i+1}. {step.description}")
            plan_desc = "\n".join(plan_lines)

        system_prompt = AGENT_SYSTEM_PROMPT.format(
            goal=state.goal,
            context=context[-3000:],  # Limit context size
            plan=plan_desc,
        )

        # Get recent messages
        messages = state.get_messages_for_llm(max_messages=5)
        user_prompt = "Respond ONLY with a JSON tool call. Which tool do you call next?"

        # Call LLM
        try:
            response = self._call_llm(system_prompt, user_prompt, messages)
        except Exception as e:
            LOG.error(f"LLM call failed: {e}")
            return f"Error during thinking: {e}", None

        # Parse tool call from response
        tool_call = parse_tool_call(response)

        if not tool_call:
            LOG.warning(f"Failed to parse tool call from LLM response ({len(response)} chars): {response[:300]}")

        return response, tool_call

    def _replan(self, state: AgentState, failure_reason: str) -> None:
        """Replan after failure."""
        self._replan_count += 1
        LOG.info(f"Replanning (attempt {self._replan_count}): {failure_reason}")

        self._emit_event("replanning", {
            "reason": failure_reason,
            "attempt": self._replan_count,
        })

        new_plan = self.planner.replan(state, failure_reason)
        state.replan(new_plan.to_execution_steps())
        state.add_context(f"Replanned due to: {failure_reason}")

    def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        messages: List[Dict[str, str]] = None,
    ) -> str:
        """Call LLM for reasoning with short timeout and retry."""
        import urllib.request

        # Build conversation
        conversation = []
        if messages:
            conversation.extend(messages)
        conversation.append({"role": "user", "content": user_prompt})

        # Format text with context for router (bypasses Core API identity injection)
        formatted_text = user_prompt
        if messages:
            context_parts = [f"{m['role']}: {m['content']}" for m in messages[-3:]]
            formatted_text = "\n".join(context_parts) + "\n\nCurrent: " + user_prompt

        payload = {
            "text": formatted_text,
            "system": system_prompt,
            "force": "qwen",
            "n_predict": 3500,
            "temperature": 0.1,
        }

        data = json.dumps(payload).encode("utf-8")

        # Retry with short timeouts (30s each) instead of one 300s block
        last_error = None
        for attempt in range(3):
            if self._cancelled:
                raise RuntimeError("Cancelled by user")

            req = urllib.request.Request(
                self.llm_endpoint,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    return result.get("text", result.get("response", ""))
            except urllib.request.URLError as e:
                last_error = e
                LOG.warning(f"LLM call attempt {attempt + 1}/3 failed: {e}")
                if attempt < 2:
                    time.sleep(2)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"LLM response parse error: {e}")

        raise RuntimeError(f"LLM network error after 3 attempts: {last_error}")

    def _emit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Emit an event to the callback."""
        if self.config.verbose:
            LOG.info(f"Event: {event_type} - {data}")

        if self.event_callback:
            try:
                self.event_callback(AgentEvent(event_type=event_type, data=data))
            except Exception as e:
                LOG.warning(f"Event callback failed: {e}")

    # ============ Public API ============

    def continue_with_input(
        self,
        state_id: str,
        user_input: str,
    ) -> Tuple[str, AgentState]:
        """
        Continue an agent that was waiting for user input.

        Args:
            state_id: ID of the waiting state
            user_input: User's response

        Returns:
            Tuple of (response, updated_state)
        """
        state = self.store.load(state_id)
        if not state:
            return "Could not find the state.", None

        if state.status != "waiting_input":
            return "The agent is not waiting for input.", state

        # Add user input and resume
        state.add_message("user", user_input)
        state.add_context(f"User input: {user_input}")
        state.status = "active"

        self._current_state = state
        return self._run_loop(state)

    def cancel(self, state_id: str = None) -> bool:
        """Cancel a running agent."""
        self._cancelled = True
        if state_id:
            state = self.store.load(state_id)
            if state:
                state.mark_cancelled()
                self.store.save(state)
        return True

    def get_status(self, state_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of an agent."""
        state = self.store.load(state_id)
        if not state:
            return None

        return {
            "id": state.id,
            "goal": state.goal,
            "status": state.status,
            "progress": state.get_progress(),
            "last_update": state.updated_at,
        }


# ============ Convenience Functions ============

def run_agent(
    goal: str,
    session_id: str = "default",
    context: str = "",
    event_callback: Optional[EventCallback] = None,
) -> Tuple[str, AgentState]:
    """
    Run an agent for a goal.

    Simple wrapper for common use case.
    """
    loop = AgentLoop(event_callback=event_callback)
    return loop.run(goal, session_id, context)


def is_agentic_query(query: str) -> bool:
    """
    Determine if a query should use agentic execution.

    Returns True for complex multi-step tasks.
    """
    planner = Planner()
    analysis = planner.analyze_complexity(query)
    return analysis["needs_planning"]
