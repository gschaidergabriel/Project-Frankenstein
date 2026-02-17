"""
AgenticMixin -- Agentic execution integration for ChatOverlay.

Detects complex multi-step queries and routes them through the
agentic execution loop instead of single-turn LLM calls.

Features:
- Automatic detection of agentic vs. simple queries
- Real-time progress display during agent execution
- Approval handling for risky actions
- Cancel/pause support
"""

from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from overlay.constants import LOG, COLORS
from overlay.widgets.agent_progress import AgentProgressBar


class AgenticMixin:
    """Mixin for agentic execution in ChatOverlay."""

    def _init_agentic(self):
        """Initialize agentic execution support."""
        self._agentic_active = False
        self._agentic_state_id: Optional[str] = None
        self._agentic_cancel_requested = False
        self._agentic_lock = threading.Lock()  # Thread safety for flags
        self._agent_progress_widget: Optional[AgentProgressBar] = None

        # Event queue for agent updates
        self._agent_event_queue: "queue.Queue" = queue.Queue()

        # Start polling for agent events
        self.after(500, self._poll_agent_events)

        LOG.info("Agentic execution support initialized")

    def _is_agentic_query(self, query: str) -> bool:
        """
        Determine if query should use agentic execution.

        Uses heuristics to detect complex multi-step tasks.
        """
        import re as _re
        query_lower = query.lower()

        # ── Early exit: discussion/opinion/explanation queries are NEVER agentic ──
        discussion_patterns = [
            "meinung", "denkst du", "was hältst du", "was haeltst du",
            "reflektier", "erkläre", "erklaere", "erklär", "erklaer",
            "was sagst du", "wie findest du", "bewerte", "beurteile",
            "zusammenfassung", "zusammenfass", "was denkst",
            "deine sicht", "dein eindruck", "deine einschätzung",
            "deine einschaetzung", "kommentiere", "kommentar",
            # English
            "opinion", "what do you think", "explain", "summarize",
            "summary", "your view", "your impression", "comment on",
            "how do you feel", "what's your take",
        ]
        if any(p in query_lower for p in discussion_patterns):
            return False

        # Explicit agentic triggers (exact substring match)
        explicit_triggers = [
            "führe aus", "automatisch", "erledige", "mach das",
            "schrittweise", "analysiere und", "finde und",
            "suche und", "lies und", "erstelle und",
            "konfiguriere", "code schreiben",
            "schreib mir ein", "baue mir", "bau mir", "erstelle mir",
            # English
            "execute", "automatically", "do this", "step by step",
            "analyze and", "find and", "search and", "read and",
            "create and", "configure", "write code",
            "write me a", "build me", "create me",
        ]

        for trigger in explicit_triggers:
            if trigger in query_lower:
                return True

        # Self-analysis / code inspection — regex-based for flexible word order
        # Matches any combination of action verb + Frank's own systems/code
        # Works on any system where Frank runs, not hardcoded to paths

        # Frank's own subsystem names (case-insensitive)
        _FRANK_MODULES = (
            r"titan|e-?pq|ego.?construct|consciousness|agentic|"
            r"wallpaper|sentinel|genesis|asrs|akam|adi|bsn|vcb|"
            r"world.?model|world.?experience|chat.?memory|"
            r"core.?awareness|personality|self.?knowledge|"
            r"voice.?mixin|chat.?mixin|command.?router|"
            r"planner|executor|loop|tools|router|gateway"
        )

        # Pattern: action verb ... (your/my/frank/the) [0-2 extra words] (code/system/module/subsystem)
        _self_analysis_re = _re.compile(
            r"(?:search|find|look|scan|check|inspect|examine|analyze|analyse|review|debug|"
            r"read|untersuche?|such|schau|prüfe?|pruefe?|lies|analysiere?|geh)"
            r".*?"
            r"(?:your|my|frank.?s?|deine[nmrs]?|meine[nmrs]?|the|das|dem|den|im)\s+"
            r"(?:\w+\s+){0,2}"  # Allow 0-2 extra words (e.g. "your OWN code", "your ENTIRE system")
            r"(?:code|system|module|files?|dateien|ordner|source|codebase|"
            r"quellcode|systemordner|" + _FRANK_MODULES + r")",
            _re.IGNORECASE,
        )
        if _self_analysis_re.search(query_lower):
            return True

        # Pattern: bug/error/issue ... in ... (your/frank/the) [0-2 extra words] (code/system/module)
        _bug_in_system_re = _re.compile(
            r"(?:bug|fehler|error|issue|problem|anomal)"
            r".*?"
            r"(?:in|im|bei)\s+"
            r"(?:your|my|frank.?s?|deine[nmrs]?|meine[nmrs]?|the|das|dem|den)?\s*"
            r"(?:\w+\s+){0,2}"
            r"(?:code|system|module|" + _FRANK_MODULES + r")",
            _re.IGNORECASE,
        )
        if _bug_in_system_re.search(query_lower):
            return True

        # Pattern: (your/frank's) [0-2 extra words] (code/module/system) ... (bug/error/check/review)
        _system_then_action_re = _re.compile(
            r"(?:your|frank.?s?|deine[nmrs]?)\s+"
            r"(?:\w+\s+){0,2}"
            r"(?:code|system|module|source|" + _FRANK_MODULES + r")"
            r".*?"
            r"(?:bug|fehler|error|check|review|inspect|analyz|analys|scan|debug|prüf|such)",
            _re.IGNORECASE,
        )
        if _system_then_action_re.search(query_lower):
            return True

        # Regex-based triggers — imperative/infinitive ONLY, not past participle
        # programmiere/programmieren → agentic (requesting action)
        # implementiert/programmiert → NOT agentic (describing past action)
        agentic_verb_re = _re.compile(
            r"\b(programmier(?:e|en|st)?|entwickle(?:n|st)?|implementier(?:e|en|st)?"
            r"|installier(?:e|en|st)?|codier(?:e|en|st)?"
            r"|skript\w*\s+schreib\w*|code\w*\s+schreib\w*)\b",
            _re.IGNORECASE,
        )
        if agentic_verb_re.search(query_lower):
            return True

        # Multi-step indicators
        multi_step_patterns = [
            " und dann ", " danach ", " anschließend ",
            " als nächstes ", ", dann ",
            # English
            " and then ", " after that ", " afterwards ",
            " next ", ", then ",
        ]

        step_count = sum(1 for p in multi_step_patterns if p in query_lower)
        if step_count >= 1:
            return True

        # Length + action heuristic (long requests with action verbs)
        if len(query) > 150 and any(w in query_lower for w in [
            "kannst du", "könntest du", "ich will", "ich möchte",
            "ich brauche", "mach mir", "wenn du fertig",
            "can you", "could you", "i want", "i need",
            "make me", "when you're done",
        ]):
            return True

        return False

    def _start_agentic_execution(self, query: str) -> None:
        """
        Start agentic execution for a query.

        Runs in background thread with progress updates.
        """
        with self._agentic_lock:
            if self._agentic_active:
                self._add_message(
                    "Frank",
                    "An agent is already running. Please wait or say 'cancel'.",
                    is_system=True
                )
                return

            self._agentic_active = True
            self._agentic_cancel_requested = False

        # Show initial status
        self._add_message(
            "Frank",
            "🤖 **Agentic Mode activated**\nAnalyzing task and creating execution plan...",
            is_system=True
        )

        # Run in background
        threading.Thread(
            target=self._agentic_worker,
            args=(query,),
            daemon=True
        ).start()

    def _agentic_worker(self, query: str) -> None:
        """Background worker for agentic execution."""
        try:
            # Import here to avoid circular imports
            from agentic import AgentLoop, AgentEvent

            def event_callback(event: AgentEvent):
                """Handle agent events."""
                self._agent_event_queue.put(event)

            # Get session ID from overlay constants
            from overlay.constants import SESSION_ID
            session_id = SESSION_ID

            # Build context — for self-analysis queries, inject code location
            context = self._get_conversation_context()
            query_lower = query.lower()
            _self_analysis_hints = [
                "bug", "your code", "your system", "deinen code", "dein system",
                "systemordner", "dateien", "titan", "your files",
            ]
            if any(h in query_lower for h in _self_analysis_hints):
                context += (
                    "\n\nIMPORTANT CONTEXT FOR SELF-ANALYSIS:"
                    "\n- Frank's source code is at: /home/ai-core-node/aicore/opt/aicore/"
                    "\n- Key directories: ui/overlay/mixins/, agentic/, services/, tools/, personality/"
                    "\n- Titan memory DB: /home/ai-core-node/.local/share/frank/db/titan.db"
                    "\n- Chat memory DB: /home/ai-core-node/.local/share/frank/db/chat_memory.db"
                    "\n- Config: /home/ai-core-node/.local/share/frank/db/"
                    "\n"
                    "\nHOW TO ANALYZE:"
                    "\n1. For Python source files (.py): Use fs_read to read them."
                    "\n2. For SQLite databases (.db): Use bash_execute with sqlite3:"
                    "\n   {\"action\":\"bash_execute\",\"action_input\":{\"command\":\"sqlite3 /path/to/file.db '.schema'\"}}"
                    "\n   {\"action\":\"bash_execute\",\"action_input\":{\"command\":\"sqlite3 /path/to/file.db 'SELECT * FROM table LIMIT 5'\"}}"
                    "\n3. For directories: Use fs_list to see contents, then fs_read individual files."
                    "\n4. Do NOT use fs_list on a file — use fs_read instead."
                    "\n5. After reading code, call final_answer with your bug findings."
                    "\n"
                    "\nSTART: List the target directory first, then read specific files."
                    "\nLook for: exception handling, logic errors, race conditions, missing imports, type errors."
                )

            # Create and run agent — store reference for cancel
            loop = AgentLoop(event_callback=event_callback)
            self._agentic_loop_ref = loop
            response, state = loop.run(
                goal=query,
                session_id=session_id,
                initial_context=context,
            )

            # Store state ID for potential continuation
            self._agentic_state_id = state.id

            # Queue final response
            self._agent_event_queue.put({
                "type": "final",
                "response": response,
                "state": state.to_dict() if state else None,
            })

        except Exception as e:
            LOG.exception(f"Agentic execution failed: {e}")
            self._agent_event_queue.put({
                "type": "error",
                "error": str(e),
            })

        finally:
            with self._agentic_lock:
                self._agentic_active = False

    def _poll_agent_events(self) -> None:
        """Poll and process agent events."""
        try:
            while True:
                try:
                    event = self._agent_event_queue.get_nowait()
                    self._handle_agent_event(event)
                except queue.Empty:
                    break
        except Exception as e:
            LOG.error(f"Error polling agent events: {e}")

        # Schedule next poll
        self.after(200, self._poll_agent_events)

    def _handle_agent_event(self, event: Any) -> None:
        """Handle an agent event."""
        if isinstance(event, dict):
            event_type = event.get("type", "")
        else:
            # AgentEvent dataclass
            event_type = event.event_type
            event = {"type": event_type, **event.data}

        if event_type == "planning":
            self._ensure_agent_progress()
            self._agent_progress_widget.set_status("Creating execution plan...")

        elif event_type == "started":
            steps = event.get("steps", 0)
            self._ensure_agent_progress()
            self._agent_progress_widget.set_status(f"Plan created: {steps} steps")

        elif event_type == "thinking":
            iteration = event.get("iteration", 0)
            total = event.get("total", 0)
            self._ensure_agent_progress()
            self._agent_progress_widget.update_step(
                step=iteration, total=total,
                description="Analyzing...", status="running"
            )

        elif event_type == "acting":
            tool = event.get("tool", "?")
            iteration = event.get("iteration", 0)
            total = event.get("total", 0)
            desc = event.get("description", "")
            self._ensure_agent_progress()
            self._agent_progress_widget.update_step(
                step=iteration, total=total,
                tool=tool, description=desc, status="running"
            )

        elif event_type == "observing":
            tool = event.get("tool", "?")
            iteration = event.get("iteration", 0)
            total = event.get("total", 0)
            success = event.get("success", True)
            self._ensure_agent_progress()
            self._agent_progress_widget.update_step(
                step=iteration, total=total,
                tool=tool, status="done" if success else "error"
            )

        elif event_type == "replanning":
            reason = event.get("reason", "")[:50]
            self._ensure_agent_progress()
            self._agent_progress_widget.set_status(f"Replanning: {reason}...")

        elif event_type == "waiting_approval":
            tool = event.get("tool", "?")
            self._show_approval_request(tool, event.get("risk", 0.5))

        elif event_type == "completed":
            response = event.get("response", "Task completed.")
            self._remove_agent_progress()
            self._hide_typing()
            self._add_message("Frank", response)
            # Speak the response via TTS if available
            if hasattr(self, '_tts_speak'):
                self._tts_speak(response[:500])

        elif event_type == "failed":
            error = event.get("error", "Unknown error")
            self._remove_agent_progress()
            self._hide_typing()
            self._add_message("Frank", f"Failed: {error}", is_system=True)

        elif event_type == "final":
            response = event.get("response", "")
            self._remove_agent_progress()
            self._hide_typing()
            if response:
                self._add_message("Frank", response)
                # Speak the response via TTS if available
                if hasattr(self, '_tts_speak'):
                    self._tts_speak(response[:500])

        elif event_type == "error":
            error = event.get("error", "Unknown error")
            self._remove_agent_progress()
            self._hide_typing()
            self._add_message("Frank", f"Error: {error}", is_system=True)

    def _ensure_agent_progress(self):
        """Create progress widget if not exists."""
        if self._agent_progress_widget is None:
            self._agent_progress_widget = AgentProgressBar(
                self.messages_frame,
                on_cancel=self._cancel_agentic_execution,
            )
            self._agent_progress_widget.pack(fill="x")
            # Scroll to show it
            self.messages_frame.update_idletasks()
            self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))
            self.chat_canvas.yview_moveto(1.0)

    def _remove_agent_progress(self):
        """Remove the progress widget."""
        if self._agent_progress_widget:
            try:
                self._agent_progress_widget.destroy()
            except Exception:
                pass
            self._agent_progress_widget = None

    def _show_approval_request(self, tool: str, risk: float) -> None:
        """Show approval request for risky action."""
        risk_level = "⚠️ Medium" if risk < 0.7 else "🔴 High"

        def show():
            self._add_message(
                "Frank",
                f"**Approval required**\n\n"
                f"Tool: `{tool}`\n"
                f"Risk: {risk_level} ({risk:.0%})\n\n"
                f"Say 'yes' to execute or 'no' to skip.",
                is_system=True
            )

        self._ui_queue.put(show)

    def _get_conversation_context(self) -> str:
        """Get recent conversation context for agent."""
        if not hasattr(self, '_chat_history'):
            return ""

        recent = self._chat_history[-5:]
        lines = []
        for msg in recent:
            role = msg.get("role", "user")
            content = msg.get("content", "")[:200]
            lines.append(f"{role}: {content}")

        return "\n".join(lines)

    def _cancel_agentic_execution(self) -> bool:
        """Cancel running agentic execution."""
        if not self._agentic_active:
            return False

        self._agentic_cancel_requested = True

        # Cancel the actual running loop instance (sets _cancelled flag)
        loop_ref = getattr(self, '_agentic_loop_ref', None)
        if loop_ref:
            try:
                loop_ref.cancel(self._agentic_state_id)
            except Exception as e:
                LOG.error(f"Failed to cancel agent: {e}")

        self._add_message("Frank", "🛑 Cancelling agent...", is_system=True)
        return True

    def _handle_agentic_response(self, user_input: str) -> bool:
        """
        Handle user input during agentic execution.

        Returns True if input was handled (approval response, cancel, etc.)
        """
        input_lower = user_input.lower().strip()

        # Cancel commands
        if input_lower in ("abbrechen", "stop", "cancel", "stopp"):
            return self._cancel_agentic_execution()

        # Approval responses
        if self._agentic_active:
            if input_lower in ("ja", "yes", "ok", "genehmigt", "approved"):
                self._respond_to_approval(True)
                return True
            elif input_lower in ("nein", "no", "ablehnen", "deny", "skip"):
                self._respond_to_approval(False)
                return True

        return False

    def _respond_to_approval(self, approved: bool) -> None:
        """Respond to an approval request."""
        # Write to approval response file
        response_file = Path("/tmp/frank_approval_responses.json")
        try:
            responses = []
            if response_file.exists():
                with open(response_file, "r") as f:
                    responses = json.load(f)

            # Add response for latest request
            responses.append({
                "id": self._agentic_state_id or "unknown",
                "approved": approved,
                "timestamp": time.time(),
            })

            with open(response_file, "w") as f:
                json.dump(responses, f)

            status = "approved" if approved else "denied"
            self._add_message("Frank", f"Action {status}.", is_system=True)

        except Exception as e:
            LOG.error(f"Failed to write approval response: {e}")


# ============ Integration Helper ============

def should_use_agentic(query: str) -> bool:
    """
    Quick check if a query should use agentic execution.

    Can be called before creating overlay instance.
    """
    query_lower = query.lower()

    triggers = [
        "führe aus", "automatisch", "erledige", "schrittweise",
        " und dann ", " danach ", " anschließend ",
        "installiere", "konfiguriere", "analysiere und",
        # English
        "execute", "automatically", "step by step",
        " and then ", " after that ",
        "install", "configure", "analyze and",
    ]

    return any(t in query_lower for t in triggers)
