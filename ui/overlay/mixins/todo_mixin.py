"""Todo/Task list integration mixin – persistent tasks with due-date reminders.

Worker methods run on the IO thread (via _io_q dispatch in worker_mixin).
Reminder polling runs via tkinter after() like calendar reminders.
"""
from __future__ import annotations

import re
from datetime import datetime

from overlay.constants import LOG, FRANK_IDENTITY
from overlay.services.core_api import _core_chat
from overlay.services.toolbox import _toolbox_call

_TODO_POLL_MS = 300_000  # 5 minutes

# Date-related keywords that signal LLM extraction is needed
_DATE_HINTS_RE = re.compile(
    r"(morgen|übermorgen|uebermorgen|heute|montag|dienstag|mittwoch|donnerstag"
    r"|freitag|samstag|sonntag|nächste|naechste|in\s+\d+\s+(stunden?|tagen?|minuten?|wochen?)"
    r"|um\s+\d+|bis\s+(zum|morgen|freitag|montag|\d)|am\s+\w+|tomorrow|tonight|next\s+\w+)",
    re.IGNORECASE,
)


class TodoMixin:
    """Persistent todo list: create, list, complete, delete tasks with reminders."""

    # ── Polling (main thread via after()) ────────────────────────────

    def _todo_poll_timer(self):
        """Schedule periodic reminder checks. Call once during init."""
        try:
            self._io_q.put(("todo_reminder", {}))
        except Exception as e:
            LOG.warning(f"Todo poll error: {e}")
        self.after(_TODO_POLL_MS, self._todo_poll_timer)

    # ── Worker methods (IO thread) ──────────────────────────────────

    def _do_todo_reminder_worker(self):
        """Check for due todos and notify user."""
        try:
            result = _toolbox_call("/todo/due", {"within_minutes": 15}, timeout_s=10.0)
        except Exception as e:
            LOG.warning(f"Todo reminder check error: {e}")
            return

        if not result or not result.get("ok"):
            return

        todos = result.get("todos", [])
        if not todos:
            return

        if not hasattr(self, "_reminded_todo_ids"):
            self._reminded_todo_ids = set()

        for t in todos:
            tid = t.get("id", 0)
            if tid in self._reminded_todo_ids:
                continue
            self._reminded_todo_ids.add(tid)

            content = t.get("content", "Task")
            due = t.get("due_date", "?")
            # Format due date nicely
            try:
                dt = datetime.fromisoformat(due)
                due_fmt = dt.strftime("%H:%M") if dt.date() == datetime.now().date() else dt.strftime("%d.%m. %H:%M")
            except Exception:
                due_fmt = due[:16] if due else "?"

            msg = f"Reminder: {content} (due {due_fmt})"
            self._ui_call(lambda m=msg: self._add_message("Frank", m, is_system=True))
            LOG.info(f"Todo reminder: {msg}")

    def _do_todo_create_worker(self, user_msg: str = "", content: str = "", voice: bool = False):
        """Create a todo. Uses LLM for date extraction if time words detected."""
        todo_text = content.strip() if content.strip() else user_msg.strip()

        if not todo_text:
            self._ui_call(lambda: self._add_message("Frank", "What should I put on the list?", is_system=True))
            return

        due_date = None

        # Check if message contains date/time hints
        if _DATE_HINTS_RE.search(user_msg or todo_text):
            self._ui_call(self._show_typing)
            # Use LLM to extract date
            now = datetime.now()
            from datetime import timedelta
            tomorrow_9 = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
            prompt = (
                f"Extract the task content and due date from the following message.\n"
                f"Current date/time: {now.strftime('%Y-%m-%d %H:%M')} ({now.strftime('%A')})\n\n"
                f"Message: \"{user_msg}\"\n\n"
                f"Reply ONLY in this format (no explanation):\n"
                f"CONTENT: <task text without time reference>\n"
                f"DUE: <ISO datetime YYYY-MM-DDTHH:MM:SS or NONE>\n\n"
                f"Examples:\n"
                f"- 'remind me tomorrow about dentist' → CONTENT: Dentist / DUE: {tomorrow_9.isoformat(timespec='seconds')}\n"
                f"- 'task: shopping' → CONTENT: shopping / DUE: NONE"
            )
            try:
                res = _core_chat(prompt, max_tokens=100, timeout_s=30, task="chat.fast", force="llama")
                if res and res.get("ok"):
                    text = res.get("text", "")
                    # Parse CONTENT line
                    cm = re.search(r"CONTENT:\s*(.+?)(?:\n|$)", text)
                    if cm:
                        extracted = cm.group(1).strip().rstrip("/").strip()
                        if extracted and len(extracted) > 2:
                            todo_text = extracted
                    # Parse DUE line
                    dm = re.search(r"DUE:\s*(\S+)", text)
                    if dm:
                        due_val = dm.group(1).strip()
                        if due_val and due_val.upper() != "NONE":
                            # Validate ISO format
                            try:
                                datetime.fromisoformat(due_val)
                                due_date = due_val
                            except ValueError:
                                pass
            except Exception as e:
                LOG.warning(f"Todo date extraction failed: {e}")
            self._ui_call(self._hide_typing)

        try:
            payload = {"content": todo_text}
            if due_date:
                payload["due_date"] = due_date

            result = _toolbox_call("/todo/create", payload, timeout_s=10.0)

            if result and result.get("ok"):
                todo_id = result.get("id", "?")
                due_info = ""
                if due_date:
                    try:
                        dt = datetime.fromisoformat(due_date)
                        due_info = f" (due: {dt.strftime('%d.%m. %H:%M')})"
                    except Exception:
                        due_info = f" (due: {due_date[:16]})"
                reply = f"Task created (#{todo_id}): {todo_text[:80]}{'...' if len(todo_text) > 80 else ''}{due_info}"
                LOG.info(f"Todo created via chat: #{todo_id}")
            else:
                error = (result or {}).get("error", "Unknown error")
                reply = f"Task could not be created: {error}"

            if voice and hasattr(self, '_voice_respond'):
                self._ui_call(lambda r=reply: self._voice_respond(r))
            else:
                self._ui_call(lambda r=reply: self._add_message("Frank", r))

        except Exception as e:
            self._ui_call(lambda e=e: self._add_message("Frank", f"Todo error: {e}", is_system=True))

    def _do_todo_list_worker(self, voice: bool = False):
        """List pending todos."""
        self._ui_call(self._show_typing)

        try:
            result = _toolbox_call("/todo/list", {"status": "pending", "limit": 20}, timeout_s=10.0)
            if not result or not result.get("ok"):
                error = (result or {}).get("error", "Todo list not reachable")
                self._ui_call(self._hide_typing)
                self._ui_call(lambda e=error: self._add_message("Frank", f"Error: {e}", is_system=True))
                return

            todos = result.get("todos", [])
            if not todos:
                self._ui_call(self._hide_typing)
                reply = "Your todo list is empty. No open tasks."
                if voice and hasattr(self, '_voice_respond'):
                    self._ui_call(lambda r=reply: self._voice_respond(r))
                else:
                    self._ui_call(lambda r=reply: self._add_message("Frank", r))
                return

            lines = []
            for t in todos:
                tid = t.get("id", "?")
                content = t.get("content", "?")[:55]
                due = t.get("due_date")
                due_str = ""
                if due:
                    try:
                        dt = datetime.fromisoformat(due)
                        due_str = f" [by {dt.strftime('%d.%m. %H:%M')}]"
                    except Exception:
                        due_str = f" [by {due[:10]}]"
                dots = "..." if len(t.get("content", "")) > 55 else ""
                lines.append(f"  #{tid} {content}{dots}{due_str}")

            reply = f"Open tasks ({len(todos)}):\n" + "\n".join(lines)

            self._ui_call(self._hide_typing)
            if voice and hasattr(self, '_voice_respond'):
                self._ui_call(lambda r=reply: self._voice_respond(r))
            else:
                self._ui_call(lambda r=reply: self._add_message("Frank", r))

        except Exception as e:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda e=e: self._add_message("Frank", f"Todo error: {e}", is_system=True))

    def _do_todo_complete_worker(self, query: str = "", user_msg: str = "", voice: bool = False):
        """Mark a todo as completed by searching for it."""
        self._ui_call(self._show_typing)

        try:
            result = _toolbox_call("/todo/list", {"status": "pending", "limit": 50}, timeout_s=10.0)
            if not result or not result.get("ok"):
                self._ui_call(self._hide_typing)
                self._ui_call(lambda: self._add_message("Frank", "Could not fetch tasks.", is_system=True))
                return

            todos = result.get("todos", [])
            if not todos:
                self._ui_call(self._hide_typing)
                self._ui_call(lambda: self._add_message("Frank", "No open tasks available.", is_system=True))
                return

            # Find matching todo
            search = (query or user_msg).lower()
            match = None
            for t in todos:
                content = (t.get("content") or "").lower()
                if any(word in content for word in search.split() if len(word) > 2):
                    match = t
                    break

            if not match:
                lines = [f"  #{t['id']} {t['content'][:50]}" for t in todos[:8]]
                reply = "Which task is done?\n" + "\n".join(lines)
                self._ui_call(self._hide_typing)
                self._ui_call(lambda r=reply: self._add_message("Frank", r))
                return

            # Complete it
            todo_id = match.get("id")
            comp_result = _toolbox_call("/todo/complete", {"id": todo_id}, timeout_s=10.0)
            self._ui_call(self._hide_typing)

            if comp_result and comp_result.get("ok"):
                reply = f"Done! #{todo_id}: {match.get('content', '?')[:50]}"
                LOG.info(f"Todo completed via chat: #{todo_id}")
            else:
                error = (comp_result or {}).get("error", "Unknown error")
                reply = f"Could not complete task: {error}"

            if voice and hasattr(self, '_voice_respond'):
                self._ui_call(lambda r=reply: self._voice_respond(r))
            else:
                self._ui_call(lambda r=reply: self._add_message("Frank", r))

        except Exception as e:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda e=e: self._add_message("Frank", f"Todo error: {e}", is_system=True))

    def _do_todo_delete_worker(self, query: str = "", user_msg: str = "", voice: bool = False):
        """Delete a todo by searching for it."""
        self._ui_call(self._show_typing)

        try:
            result = _toolbox_call("/todo/list", {"status": "all", "limit": 50}, timeout_s=10.0)
            if not result or not result.get("ok"):
                self._ui_call(self._hide_typing)
                self._ui_call(lambda: self._add_message("Frank", "Could not fetch tasks.", is_system=True))
                return

            todos = result.get("todos", [])
            if not todos:
                self._ui_call(self._hide_typing)
                self._ui_call(lambda: self._add_message("Frank", "No tasks available to delete.", is_system=True))
                return

            search = (query or user_msg).lower()
            match = None
            for t in todos:
                content = (t.get("content") or "").lower()
                if any(word in content for word in search.split() if len(word) > 2):
                    match = t
                    break

            if not match:
                lines = [f"  #{t['id']} {t['content'][:50]}" for t in todos[:8]]
                reply = "Which task should I delete?\n" + "\n".join(lines)
                self._ui_call(self._hide_typing)
                self._ui_call(lambda r=reply: self._add_message("Frank", r))
                return

            todo_id = match.get("id")
            del_result = _toolbox_call("/todo/delete", {"id": todo_id}, timeout_s=10.0)
            self._ui_call(self._hide_typing)

            if del_result and del_result.get("ok"):
                reply = f"Task deleted: #{todo_id} {match.get('content', '?')[:50]}"
                LOG.info(f"Todo deleted via chat: #{todo_id}")
            else:
                error = (del_result or {}).get("error", "Unknown error")
                reply = f"Delete failed: {error}"

            if voice and hasattr(self, '_voice_respond'):
                self._ui_call(lambda r=reply: self._voice_respond(r))
            else:
                self._ui_call(lambda r=reply: self._add_message("Frank", r))

        except Exception as e:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda e=e: self._add_message("Frank", f"Delete failed: {e}", is_system=True))

    def _do_todo_general_worker(self, user_msg: str = "", voice: bool = False):
        """Handle general todo-related queries via LLM with todo context."""
        self._ui_call(self._show_typing)

        try:
            todos_result = _toolbox_call("/todo/list", {"status": "pending", "limit": 10}, timeout_s=10.0)
            ctx = ""
            if todos_result and todos_result.get("ok"):
                todos = todos_result.get("todos", [])
                if todos:
                    lines = []
                    for t in todos:
                        due = f" [by {t['due_date'][:10]}]" if t.get("due_date") else ""
                        lines.append(f"- #{t['id']}: {t['content'][:60]}{due}")
                    ctx = f"Open tasks ({len(todos)}):\n" + "\n".join(lines)
                else:
                    ctx = "No open tasks."

            prompt = (
                f"[Identity: {FRANK_IDENTITY}]\n\n"
                f"You have a local todo list.\n"
                f"Your todo commands:\n"
                f"- 'remind me tomorrow about ...' → Task with date\n"
                f"- 'task: ...' → Create task\n"
                f"- 'what's on my list?' → Open tasks\n"
                f"- 'task done ...' → Mark as completed\n"
                f"- 'delete task ...' → Delete task\n\n"
                f"Current status:\n{ctx}\n\n"
                f"The user says: '{user_msg}'\n\n"
                f"Answer the question or point to the appropriate command. "
                f"Respond briefly and helpfully in English."
            )

            try:
                res = _core_chat(prompt, max_tokens=300, timeout_s=60, task="chat.fast", force="llama")
                reply = (res.get("text") or "").strip() if res.get("ok") else "I could not process your todo request."
            except Exception:
                reply = "I could not process your todo request."

            self._ui_call(self._hide_typing)
            if voice and hasattr(self, '_voice_respond'):
                self._ui_call(lambda r=reply: self._voice_respond(r))
            else:
                self._ui_call(lambda r=reply: self._add_message("Frank", r))

        except Exception as e:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda err=e: self._add_message("Frank", f"Todo request failed: {err}", is_system=True))
