"""Clipboard History mixin -- passive monitoring with search/restore.

Polling runs on main thread (tkinter clipboard_get requires it).
Worker methods run on the IO thread (via _io_q dispatch in worker_mixin).
"""
from __future__ import annotations

import hashlib
import re
import sys

from overlay.constants import LOG

# Ensure tools/ is importable
try:
    from config.paths import TOOLS_DIR as _TOOLS_DIR
except ImportError:
    from pathlib import Path as _Path
    _TOOLS_DIR = _Path("/home/ai-core-node/aicore/opt/aicore/tools")
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

_CLIPBOARD_POLL_MS = 3000  # 3 seconds


class ClipboardMixin:
    """Clipboard history: passive capture, list, search, restore, delete, clear."""

    # ── Polling (main thread via after()) ────────────────────────────

    def _clipboard_poll_timer(self):
        """Poll clipboard for changes. Call once during init to start."""
        try:
            current = self.clipboard_get()
            if current and current.strip():
                h = hashlib.sha256(current.encode("utf-8", errors="replace")).hexdigest()
                if h != self._last_clipboard_hash:
                    self._last_clipboard_hash = h
                    self._io_q.put(("clipboard_capture", {"content": current}))
        except Exception:
            pass  # TclError when clipboard is empty or contains binary data
        self.after(_CLIPBOARD_POLL_MS, self._clipboard_poll_timer)

    # ── Workers (IO thread) ──────────────────────────────────────────

    def _do_clipboard_capture_worker(self, content: str):
        """Store a new clipboard entry (background, silent)."""
        try:
            from clipboard_store import add_entry
            result = add_entry(content)
            if result.get("ok") and not result.get("duplicate"):
                LOG.debug(f"Clipboard captured: {len(content)} chars")
        except Exception as e:
            LOG.warning(f"Clipboard capture error: {e}")

    def _do_clipboard_list_worker(self, voice: bool = False):
        """List recent clipboard entries."""
        self._ui_call(self._show_typing)
        try:
            from clipboard_store import list_entries
            result = list_entries(limit=20)

            if not result or not result.get("ok"):
                self._ui_call(self._hide_typing)
                self._ui_call(lambda: self._add_message("Frank", "Error loading clipboard history.", is_system=True))
                return

            entries = result.get("entries", [])
            if not entries:
                reply = "Your clipboard history is empty."
            else:
                lines = []
                for e in entries:
                    eid = e.get("id", "?")
                    preview = e.get("preview", "?")
                    if len(preview) > 55:
                        preview = preview[:55] + "..."
                    ts = e.get("timestamp", "?")[:16]
                    lines.append(f"  #{eid} [{ts}] {preview}")
                reply = f"Clipboard history ({len(entries)}):\n" + "\n".join(lines)

            self._ui_call(self._hide_typing)
            if voice and hasattr(self, '_voice_respond'):
                self._ui_call(lambda r=reply: self._voice_respond(r))
            else:
                self._ui_call(lambda r=reply: self._add_message("Frank", r))

        except Exception as e:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda err=e: self._add_message("Frank", f"Clipboard error: {err}", is_system=True))

    def _do_clipboard_search_worker(self, query: str = "", voice: bool = False):
        """Search clipboard history by content."""
        self._ui_call(self._show_typing)
        try:
            from clipboard_store import search_entries
            result = search_entries(query)

            if not result or not result.get("ok"):
                self._ui_call(self._hide_typing)
                self._ui_call(lambda: self._add_message("Frank", "Search failed.", is_system=True))
                return

            entries = result.get("entries", [])
            if not entries:
                reply = f"Nothing found for '{query}'."
            else:
                lines = []
                for e in entries:
                    eid = e.get("id", "?")
                    preview = e.get("preview", "?")
                    if len(preview) > 55:
                        preview = preview[:55] + "..."
                    lines.append(f"  #{eid} {preview}")
                reply = f"Clipboard search '{query}' ({len(entries)}):\n" + "\n".join(lines)

            self._ui_call(self._hide_typing)
            if voice and hasattr(self, '_voice_respond'):
                self._ui_call(lambda r=reply: self._voice_respond(r))
            else:
                self._ui_call(lambda r=reply: self._add_message("Frank", r))

        except Exception as e:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda err=e: self._add_message("Frank", f"Clipboard search failed: {err}", is_system=True))

    def _do_clipboard_restore_worker(self, entry_id: int = 0, query: str = "", voice: bool = False):
        """Restore a clipboard entry to the system clipboard."""
        self._ui_call(self._show_typing)
        try:
            from clipboard_store import get_entry, search_entries

            # If no ID given, try to extract from query
            if not entry_id and query:
                m = re.search(r"#?(\d+)", query)
                if m:
                    entry_id = int(m.group(1))

            if entry_id:
                result = get_entry(entry_id)
            else:
                self._ui_call(self._hide_typing)
                self._ui_call(lambda: self._add_message("Frank", "Which entry? Provide the ID, e.g. 'restore entry #3'.", is_system=True))
                return

            if not result or not result.get("ok"):
                error = (result or {}).get("error", "Entry not found")
                self._ui_call(self._hide_typing)
                self._ui_call(lambda e=error: self._add_message("Frank", f"Error: {e}", is_system=True))
                return

            entry = result["entry"]
            content = entry["content"]

            # Clipboard write MUST happen on main thread
            def _restore():
                try:
                    self.clipboard_clear()
                    self.clipboard_append(content)
                except Exception:
                    pass
            self._ui_call(_restore)

            # Update hash to prevent re-capture
            self._last_clipboard_hash = hashlib.sha256(
                content.encode("utf-8", errors="replace")
            ).hexdigest()

            preview = entry.get("preview", "?")
            if len(preview) > 50:
                preview = preview[:50] + "..."
            reply = f"Restored: #{entry['id']} {preview}"

            self._ui_call(self._hide_typing)
            if voice and hasattr(self, '_voice_respond'):
                self._ui_call(lambda r=reply: self._voice_respond(r))
            else:
                self._ui_call(lambda r=reply: self._add_message("Frank", r))

        except Exception as e:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda err=e: self._add_message("Frank", f"Restore failed: {err}", is_system=True))

    def _do_clipboard_delete_worker(self, entry_id: int = 0, query: str = "", voice: bool = False):
        """Delete a clipboard history entry."""
        self._ui_call(self._show_typing)
        try:
            from clipboard_store import delete_entry

            if not entry_id and query:
                m = re.search(r"#?(\d+)", query)
                if m:
                    entry_id = int(m.group(1))

            if not entry_id:
                self._ui_call(self._hide_typing)
                self._ui_call(lambda: self._add_message("Frank", "Which entry to delete? Provide the ID.", is_system=True))
                return

            result = delete_entry(entry_id)
            self._ui_call(self._hide_typing)

            if result and result.get("ok"):
                reply = f"Clipboard entry #{entry_id} deleted."
            else:
                error = (result or {}).get("error", "Not found")
                reply = f"Error: {error}"

            if voice and hasattr(self, '_voice_respond'):
                self._ui_call(lambda r=reply: self._voice_respond(r))
            else:
                self._ui_call(lambda r=reply: self._add_message("Frank", r))

        except Exception as e:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda err=e: self._add_message("Frank", f"Delete failed: {err}", is_system=True))

    def _do_clipboard_clear_worker(self, voice: bool = False):
        """Clear all clipboard history."""
        self._ui_call(self._show_typing)
        try:
            from clipboard_store import clear_all
            result = clear_all()
            self._ui_call(self._hide_typing)

            if result and result.get("ok"):
                deleted = result.get("deleted", 0)
                reply = f"Clipboard history cleared ({deleted} entries)."
            else:
                reply = "Error clearing history."

            if voice and hasattr(self, '_voice_respond'):
                self._ui_call(lambda r=reply: self._voice_respond(r))
            else:
                self._ui_call(lambda r=reply: self._add_message("Frank", r))

        except Exception as e:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda err=e: self._add_message("Frank", f"Delete failed: {err}", is_system=True))
