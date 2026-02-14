"""Notes/Memos integration mixin – persistent local notes with FTS search.

Worker methods run on the IO thread (via _io_q dispatch in worker_mixin).
No polling needed.
"""
from __future__ import annotations

from overlay.constants import LOG, FRANK_IDENTITY
from overlay.services.core_api import _core_chat
from overlay.services.toolbox import _toolbox_call


class NotesMixin:
    """Persistent notes: create, list, search, delete memos."""

    # ── Worker methods (IO thread) ──────────────────────────────────

    def _do_notes_create_worker(self, user_msg: str = "", content: str = "", voice: bool = False):
        """Create a note. Content is pre-extracted by regex in router."""
        note_text = content.strip() if content.strip() else user_msg.strip()

        if not note_text:
            self._ui_call(lambda: self._add_message("Frank", "What should I remember?", is_system=True))
            return

        try:
            result = _toolbox_call("/notes/create", {"content": note_text}, timeout_s=10.0)

            if result and result.get("ok"):
                note_id = result.get("id", "?")
                reply = f"Noted! (#{note_id}): {note_text[:80]}{'...' if len(note_text) > 80 else ''}"
                LOG.info(f"Note created via chat: #{note_id}")
            else:
                error = (result or {}).get("error", "Unknown error")
                reply = f"Could not save note: {error}"

            if voice and hasattr(self, '_voice_respond'):
                self._ui_call(lambda r=reply: self._voice_respond(r))
            else:
                self._ui_call(lambda r=reply: self._add_message("Frank", r))

        except Exception as e:
            self._ui_call(lambda e=e: self._add_message("Frank", f"Note error: {e}", is_system=True))

    def _do_notes_list_worker(self, voice: bool = False):
        """List recent notes."""
        self._ui_call(self._show_typing)

        try:
            result = _toolbox_call("/notes/list", {"limit": 15}, timeout_s=10.0)
            if not result or not result.get("ok"):
                error = (result or {}).get("error", "Notes service unreachable")
                self._ui_call(self._hide_typing)
                self._ui_call(lambda e=error: self._add_message("Frank", f"Error: {e}", is_system=True))
                return

            notes = result.get("notes", [])
            if not notes:
                self._ui_call(self._hide_typing)
                reply = "You have no saved notes."
                if voice and hasattr(self, '_voice_respond'):
                    self._ui_call(lambda r=reply: self._voice_respond(r))
                else:
                    self._ui_call(lambda r=reply: self._add_message("Frank", r))
                return

            lines = []
            for n in notes:
                nid = n.get("id", "?")
                content = n.get("content", "?")[:60]
                date = n.get("created_at", "?")[:10]
                lines.append(f"  #{nid} [{date}] {content}{'...' if len(n.get('content', '')) > 60 else ''}")

            reply = f"Your notes ({len(notes)}):\n" + "\n".join(lines)

            self._ui_call(self._hide_typing)
            if voice and hasattr(self, '_voice_respond'):
                self._ui_call(lambda r=reply: self._voice_respond(r))
            else:
                self._ui_call(lambda r=reply: self._add_message("Frank", r))

        except Exception as e:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda e=e: self._add_message("Frank", f"Note error: {e}", is_system=True))

    def _do_notes_search_worker(self, query: str = "", voice: bool = False):
        """Search notes by content."""
        self._ui_call(self._show_typing)

        try:
            result = _toolbox_call("/notes/search", {"query": query}, timeout_s=10.0)
            if not result or not result.get("ok"):
                error = (result or {}).get("error", "Search failed")
                self._ui_call(self._hide_typing)
                self._ui_call(lambda e=error: self._add_message("Frank", f"Error: {e}", is_system=True))
                return

            notes = result.get("notes", [])
            if not notes:
                self._ui_call(self._hide_typing)
                reply = f"No notes found for '{query}'."
                if voice and hasattr(self, '_voice_respond'):
                    self._ui_call(lambda r=reply: self._voice_respond(r))
                else:
                    self._ui_call(lambda r=reply: self._add_message("Frank", r))
                return

            lines = []
            for n in notes:
                nid = n.get("id", "?")
                content = n.get("content", "?")[:60]
                lines.append(f"  #{nid} {content}{'...' if len(n.get('content', '')) > 60 else ''}")

            reply = f"Found ({len(notes)}):\n" + "\n".join(lines)

            self._ui_call(self._hide_typing)
            if voice and hasattr(self, '_voice_respond'):
                self._ui_call(lambda r=reply: self._voice_respond(r))
            else:
                self._ui_call(lambda r=reply: self._add_message("Frank", r))

        except Exception as e:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda e=e: self._add_message("Frank", f"Search error: {e}", is_system=True))

    def _do_notes_delete_worker(self, query: str = "", user_msg: str = "", voice: bool = False):
        """Delete a note by searching for it first."""
        self._ui_call(self._show_typing)

        try:
            # List all notes to find match
            result = _toolbox_call("/notes/list", {"limit": 50}, timeout_s=10.0)
            if not result or not result.get("ok"):
                self._ui_call(self._hide_typing)
                self._ui_call(lambda: self._add_message("Frank", "Could not fetch notes.", is_system=True))
                return

            notes = result.get("notes", [])
            if not notes:
                self._ui_call(self._hide_typing)
                self._ui_call(lambda: self._add_message("Frank", "No notes to delete.", is_system=True))
                return

            # Try to find matching note
            search = (query or user_msg).lower()
            match = None
            for n in notes:
                content = (n.get("content") or "").lower()
                if any(word in content for word in search.split() if len(word) > 2):
                    match = n
                    break

            if not match:
                lines = [f"  #{n['id']} {n['content'][:50]}" for n in notes[:8]]
                reply = "Which note should I delete?\n" + "\n".join(lines)
                self._ui_call(self._hide_typing)
                self._ui_call(lambda r=reply: self._add_message("Frank", r))
                return

            # Delete
            note_id = match.get("id")
            del_result = _toolbox_call("/notes/delete", {"id": note_id}, timeout_s=10.0)
            self._ui_call(self._hide_typing)

            if del_result and del_result.get("ok"):
                reply = f"Note deleted: #{note_id} {match.get('content', '?')[:50]}"
                LOG.info(f"Note deleted via chat: #{note_id}")
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

    def _do_notes_general_worker(self, user_msg: str = "", voice: bool = False):
        """Handle general notes-related queries via LLM with notes context."""
        self._ui_call(self._show_typing)

        try:
            # Get recent notes for context
            notes_result = _toolbox_call("/notes/list", {"limit": 10}, timeout_s=10.0)
            ctx = ""
            if notes_result and notes_result.get("ok"):
                notes = notes_result.get("notes", [])
                if notes:
                    lines = [f"- #{n['id']}: {n['content'][:60]}" for n in notes]
                    ctx = f"Saved notes ({len(notes)}):\n" + "\n".join(lines)
                else:
                    ctx = "No notes saved."

            prompt = (
                f"[Identity: {FRANK_IDENTITY}]\n\n"
                f"You have a local notes system.\n"
                f"Your notes commands:\n"
                f"- 'remember that ...' → Save a note\n"
                f"- 'show my notes' → List all notes\n"
                f"- 'search notes X' → Search notes\n"
                f"- 'delete note X' → Delete a note\n\n"
                f"Current status:\n{ctx}\n\n"
                f"The user says: '{user_msg}'\n\n"
                f"Answer the question or point to the relevant command. "
                f"Reply briefly and helpfully."
            )

            try:
                res = _core_chat(prompt, max_tokens=300, timeout_s=60, task="chat.fast", force="llama")
                reply = (res.get("text") or "").strip() if res.get("ok") else "Could not process your notes request."
            except Exception:
                reply = "Could not process your notes request."

            self._ui_call(self._hide_typing)
            if voice and hasattr(self, '_voice_respond'):
                self._ui_call(lambda r=reply: self._voice_respond(r))
            else:
                self._ui_call(lambda r=reply: self._add_message("Frank", r))

        except Exception as e:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda err=e: self._add_message("Frank", f"Notes request failed: {err}", is_system=True))
