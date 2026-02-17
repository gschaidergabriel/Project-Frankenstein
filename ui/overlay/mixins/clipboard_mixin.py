"""Clipboard History mixin -- passive monitoring with search/restore.

Polling runs on main thread (tkinter clipboard_get requires it).
Worker methods run on the IO thread (via _io_q dispatch in worker_mixin).
"""
from __future__ import annotations

import hashlib
import re
import sys
import tkinter as tk

from overlay.constants import COLORS, LOG, URL_REGEX

# Ensure tools/ is importable
try:
    from config.paths import TOOLS_DIR as _TOOLS_DIR
except ImportError:
    from pathlib import Path as _Path
    _TOOLS_DIR = _Path(__file__).resolve().parents[3] / "tools"
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
                    # Auto-analyze hint
                    self._show_clipboard_hint(current)
        except Exception:
            pass  # TclError when clipboard is empty or contains binary data
        self.after(_CLIPBOARD_POLL_MS, self._clipboard_poll_timer)

    # ── Clipboard Auto-Analyze Hint ──────────────────────────────────

    def _show_clipboard_hint(self, content: str):
        """Show a contextual hint bar when clipboard changes with actionable content."""
        if not content or len(content) < 20:
            return

        # Determine content type and action
        label = None
        command = None

        if URL_REGEX.search(content):
            url = URL_REGEX.search(content).group(1)
            label = "URL copied \u2014 Summarize?"
            command = f"fetch {url}"
        elif len(content) > 150 and any(kw in content for kw in
                ['def ', 'function ', 'class ', 'import ', '#include', 'const ', 'var ', 'let ']):
            label = "Code copied \u2014 Analyze?"
            command = f"Analyze this code:\n```\n{content[:2000]}\n```"
        elif len(content) > 200:
            label = "Text copied \u2014 Summarize?"
            command = f"Summarize: {content[:2000]}"
        else:
            return

        # Dismiss old hint
        self._dismiss_clipboard_hint()

        try:
            # Create hint bar above input area
            if not hasattr(self, '_status_bar'):
                return

            self._clipboard_hint_bar = tk.Frame(
                self._status_bar.master,  # main frame
                bg=COLORS["bg_elevated"], height=24,
            )
            # Insert just above the status bar
            self._clipboard_hint_bar.pack(side="bottom", fill="x", before=self._status_bar)
            self._clipboard_hint_bar.pack_propagate(False)

            # Content
            hint_lbl = tk.Label(
                self._clipboard_hint_bar, text=f"  \u25c6 {label}",
                bg=COLORS["bg_elevated"], fg=COLORS["accent_secondary"],
                font=("Consolas", 8), cursor="hand2",
            )
            hint_lbl.pack(side="left", padx=4)
            hint_lbl.bind("<Button-1>", lambda e, c=command: self._execute_clipboard_action(c))
            hint_lbl.bind("<Enter>", lambda e: hint_lbl.configure(fg=COLORS["neon_cyan"]))
            hint_lbl.bind("<Leave>", lambda e: hint_lbl.configure(fg=COLORS["accent_secondary"]))

            dismiss_lbl = tk.Label(
                self._clipboard_hint_bar, text="\u2715",
                bg=COLORS["bg_elevated"], fg=COLORS["text_muted"],
                font=("Consolas", 8), cursor="hand2", padx=6,
            )
            dismiss_lbl.pack(side="right")
            dismiss_lbl.bind("<Button-1>", lambda e: self._dismiss_clipboard_hint())

            # Auto-dismiss after 8 seconds
            self.after(8000, self._dismiss_clipboard_hint)

        except Exception as e:
            LOG.debug(f"Clipboard hint error: {e}")

    def _execute_clipboard_action(self, command: str):
        """Execute a clipboard hint action."""
        self._dismiss_clipboard_hint()
        if hasattr(self, '_route_message'):
            self._route_message(command)

    def _dismiss_clipboard_hint(self):
        """Remove clipboard hint bar."""
        if hasattr(self, '_clipboard_hint_bar') and self._clipboard_hint_bar:
            try:
                self._clipboard_hint_bar.destroy()
            except Exception:
                pass
            self._clipboard_hint_bar = None

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
