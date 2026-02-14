"""File attachment handlers – attach, drag-drop, auto-analyze, and file actions."""
from __future__ import annotations

import re
from pathlib import Path
from typing import List
from tkinter import filedialog

from overlay.constants import LOG, COLORS, IMAGE_EXTENSIONS, DOC_EXTENSIONS, EXT_LANG, DROP_PARSE_RE, DEFAULT_TIMEOUT_S
from overlay.file_utils import _fmt_bytes, _read_file_preview, _build_file_prompt


class FileAttachMixin:
    """File picker, drag-drop, auto-analysis, and file action runners."""

    def _on_attach(self):
        path = filedialog.askopenfilename(title="Select file")
        if not path:
            return
        self._handle_attach(Path(path))

    def _on_drop(self, event):
        data = getattr(event, "data", "") or ""
        paths: List[str] = []
        for a, b in DROP_PARSE_RE.findall(data):
            s = a or b
            if s and len(s) <= 4096:  # Reject too-long paths
                paths.append(s)
        if not paths:
            return
        try:
            p = Path(paths[0]).expanduser()
            if p.exists() and p.is_file():
                self._handle_attach(p)
        except OSError:
            # Catch file name too long or other path errors
            pass

    def _handle_attach(self, p: Path):
        self._add_message("Frank", f"File received: {p.name}", is_system=True)
        self._last_file = p
        self._last_file_lang, self._last_file_content = _read_file_preview(p)

        # Best-effort ingest
        self._io_q.put(("ingest", {"path": p}))

        # Auto-analyze file content automatically
        self._auto_analyze_file(p)

    def _auto_analyze_file(self, p: Path):
        """Automatically analyze file content without requiring button click.
        Uses VCB for images, PDF extraction for documents, LLM for text files."""

        ext = p.suffix.lower()
        size = p.stat().st_size if p.exists() else 0
        size_str = _fmt_bytes(size)

        # Image files - show preview thumbnail and analyze with VCB
        if ext in IMAGE_EXTENSIONS:
            # Show image preview in chat as user message
            try:
                self._add_image(str(p), caption=f"Image: {p.name}", is_user=True)
            except Exception as e:
                LOG.error(f"Failed to show image preview: {e}")
                self._add_message("Du", f"[Image: {p.name}]", is_user=True)
            # Queue analysis
            self._chat_q.put(("analyze_image", {"path": p}))
            return

        # PDF files - extract text and analyze
        if ext == ".pdf":
            self._add_message("Du", f"[PDF analysis: {p.name}]", is_user=True)
            self._chat_q.put(("analyze_pdf", {"path": p}))
            return

        # Other document types
        if ext in DOC_EXTENSIONS:
            self._add_message("Frank", f"File received: {p.name} ({size_str}). Document format {ext} is not fully supported yet.", is_system=True)
            return

        # Text/code files - use existing logic
        if not self._last_file_content:
            self._add_message("Frank", "File is empty or not readable.", is_system=True)
            return

        # Determine analysis type based on file extension
        is_code = ext in (".py", ".js", ".ts", ".cpp", ".c", ".h", ".hpp", ".java", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala")

        if is_code:
            action = "Briefly explain what this code does (max 3 sentences). If bugs/issues are apparent, mention them."
        else:
            action = "Briefly explain the content of this file (max 3 sentences)."

        ctx = self._get_context_line()
        prompt = _build_file_prompt(action, p, self._last_file_lang, self._last_file_content, ctx)

        task = "code.edit" if is_code else "chat.fast"
        max_tokens = 400  # Short auto-analysis

        # Show user message for visual feedback (like _run_file_action does)
        self._add_message("Du", f"[Auto-analysis: {p.name}]", is_user=True)
        self._chat_q.put(("chat", {"msg": prompt, "max_tokens": max_tokens, "timeout_s": DEFAULT_TIMEOUT_S, "task": task, "force": "llama"}))

    def _run_file_action(self, action: str):
        """Run file action - called from quick action buttons."""
        if not self._last_file:
            self._add_message("Frank", "No active file.", is_system=True)
            return
        p = self._last_file

        ctx = self._get_context_line()
        prompt = _build_file_prompt(action, p, self._last_file_lang, self._last_file_content, ctx)
        self._hide_file_actions()

        is_code = p.suffix.lower() in (".py", ".js", ".ts", ".cpp", ".c", ".h", ".hpp")
        task = "code.edit" if is_code else "chat.fast"
        max_tokens = 800 if is_code else 600

        self._add_message("Du", f"[{action[:30]}...]", is_user=True)
        self._chat_q.put(("chat", {"msg": prompt, "max_tokens": max_tokens, "timeout_s": DEFAULT_TIMEOUT_S, "task": task, "force": "llama"}))

    def _run_file_action_with_query(self, user_query: str, action: str):
        """Run file action with user's actual query preserved - called from text input."""
        if not self._last_file:
            self._add_message("Frank", "No active file.", is_system=True)
            return
        p = self._last_file

        ctx = self._get_context_line()
        prompt = _build_file_prompt(action, p, self._last_file_lang, self._last_file_content, ctx)
        self._hide_file_actions()

        is_code = p.suffix.lower() in (".py", ".js", ".ts", ".cpp", ".c", ".h", ".hpp")
        task = "code.edit" if is_code else "chat.fast"
        max_tokens = 800 if is_code else 600

        # Note: user message already added by caller, don't add again
        self._chat_q.put(("chat", {"msg": prompt, "max_tokens": max_tokens, "timeout_s": DEFAULT_TIMEOUT_S, "task": task, "force": "llama"}))
