"""Email Detail / Compose Popup — Cyberpunk-styled Toplevel window.

Modes:
    - READ: Display email header + body + action buttons
    - COMPOSE: To/Subject/Body form + attachments + send/draft buttons
"""
from __future__ import annotations

import subprocess
import threading
import tkinter as tk
from tkinter import filedialog
from pathlib import Path
from typing import Optional, Callable, List, Dict, Any

from overlay.constants import COLORS, LOG
from overlay.bsn.constants import get_workarea_y

_FONT = ("Consolas", 10)
_FONT_BOLD = ("Consolas", 10, "bold")
_FONT_TITLE = ("Consolas", 11, "bold")
_FONT_SMALL = ("Consolas", 9)
_FONT_BODY = ("Consolas", 10)
_FONT_HEADER = ("Consolas", 9)

_POPUP_W = 600
_POPUP_H = 700


class EmailPopup(tk.Toplevel):
    """Cyberpunk email reader / compose popup."""

    def __init__(
        self,
        parent,
        email_data=None,
        full_body: str = "",
        on_destroy: Optional[Callable] = None,
        on_action: Optional[Callable] = None,
    ):
        super().__init__(parent)
        self._parent = parent
        self._email_data = email_data
        self._full_body = full_body
        self._on_destroy = on_destroy
        self._on_action = on_action  # callback(action, **kwargs) for IO dispatch
        self._attachments: List[str] = []

        self.title("FRANK MAIL")
        self.configure(bg=COLORS["bg_main"])
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.95)
        except tk.TclError:
            pass

        # Drag state
        self._drag_x = 0
        self._drag_y = 0

        # Position left of parent overlay
        self.update_idletasks()
        parent.update_idletasks()
        px = parent.winfo_x()
        py = parent.winfo_y()
        pw = parent.winfo_width()
        screen_w = self.winfo_screenwidth()
        x = px - _POPUP_W - 8
        if x < 0:
            x = px + pw + 8
        if x + _POPUP_W > screen_w:
            x = max(0, screen_w - _POPUP_W)
        y = max(get_workarea_y(), py)
        self.geometry(f"{_POPUP_W}x{_POPUP_H}+{x}+{y}")

        self.bind("<Escape>", lambda e: self.destroy())

        if email_data:
            self._build_read_view()
        else:
            self._build_compose_view()

    def destroy(self):
        if self._on_destroy:
            try:
                self._on_destroy()
            except Exception:
                pass
        super().destroy()

    # ── Shared helpers ─────────────────────────────────────────────

    def _clear_content(self):
        for w in self.winfo_children():
            w.destroy()

    def _build_titlebar(self, parent_frame: tk.Frame, title: str):
        titlebar = tk.Frame(parent_frame, bg=COLORS["bg_elevated"], height=32)
        titlebar.pack(fill="x")
        titlebar.pack_propagate(False)
        tk.Frame(titlebar, bg=COLORS["neon_cyan"], height=2).pack(fill="x", side="bottom")

        title_frame = tk.Frame(titlebar, bg=COLORS["bg_elevated"])
        title_frame.pack(fill="both", expand=True, side="left")
        tk.Label(
            title_frame, text=title, bg=COLORS["bg_elevated"],
            fg=COLORS["neon_cyan"], font=_FONT_TITLE
        ).pack(side="left", padx=12, pady=6)

        close_btn = tk.Label(
            titlebar, text="\u2715", bg=COLORS["bg_elevated"],
            fg=COLORS["text_muted"], font=("Consolas", 12), width=3, cursor="hand2"
        )
        close_btn.pack(side="right", padx=4)
        close_btn.bind("<Button-1>", lambda e: self.destroy())
        close_btn.bind("<Enter>", lambda e: close_btn.configure(fg="#ffffff", bg=COLORS["error"]))
        close_btn.bind("<Leave>", lambda e: close_btn.configure(fg=COLORS["text_muted"], bg=COLORS["bg_elevated"]))

        for w in [titlebar, title_frame]:
            w.bind("<Button-1>", self._start_drag)
            w.bind("<B1-Motion>", self._on_drag)

    def _make_button(self, parent, text, bg_color, fg_color="#FFFFFF", command=None):
        btn = tk.Label(
            parent, text=f" {text} ", bg=bg_color, fg=fg_color,
            font=_FONT_BOLD, padx=8, pady=4, cursor="hand2"
        )
        if command:
            btn.bind("<Button-1>", lambda e: command())
        btn.bind("<Enter>", lambda e: btn.configure(bg=self._lighten(bg_color)))
        btn.bind("<Leave>", lambda e: btn.configure(bg=bg_color))
        return btn

    @staticmethod
    def _lighten(hex_color: str) -> str:
        try:
            r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
            r, g, b = min(255, r + 30), min(255, g + 30), min(255, b + 30)
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return hex_color

    def _start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag(self, event):
        x = self.winfo_x() + (event.x - self._drag_x)
        y = self.winfo_y() + (event.y - self._drag_y)
        y = max(get_workarea_y(), y)
        self.geometry(f"+{x}+{y}")

    def _dispatch(self, action: str, **kwargs):
        """Dispatch an action back to the overlay's IO queue."""
        if self._on_action:
            self._on_action(action, **kwargs)

    def _show_status(self, msg: str, color: str = COLORS["neon_cyan"]):
        """Show a brief status message at the bottom."""
        if hasattr(self, "_status_label") and self._status_label.winfo_exists():
            self._status_label.configure(text=msg, fg=color)

    # ── READ VIEW ──────────────────────────────────────────────────

    def _build_read_view(self):
        self._clear_content()
        ed = self._email_data

        outer = tk.Frame(self, bg=COLORS["neon_cyan"], padx=2, pady=2)
        outer.pack(fill="both", expand=True)
        main = tk.Frame(outer, bg=COLORS["bg_main"])
        main.pack(fill="both", expand=True)

        subj_short = (ed.subject or "(kein Betreff)")[:50]
        self._build_titlebar(main, f"MAIL // {subj_short}")

        # Header section
        header = tk.Frame(main, bg=COLORS["bg_elevated"], padx=16, pady=10)
        header.pack(fill="x")

        for label_text, value in [
            ("From:", ed.sender),
            ("Subject:", ed.subject or "(kein Betreff)"),
            ("Date:", self._format_date(ed.date)),
        ]:
            row = tk.Frame(header, bg=COLORS["bg_elevated"])
            row.pack(anchor="w", fill="x", pady=1)
            tk.Label(
                row, text=label_text, bg=COLORS["bg_elevated"],
                fg=COLORS["text_muted"], font=_FONT_HEADER, width=9, anchor="w"
            ).pack(side="left")
            tk.Label(
                row, text=value[:80], bg=COLORS["bg_elevated"],
                fg=COLORS["text_primary"], font=_FONT_HEADER, anchor="w"
            ).pack(side="left", fill="x", expand=True)

        # Separator
        tk.Frame(main, bg=COLORS["neon_cyan"], height=1).pack(fill="x")

        # Body section (scrollable text)
        body_frame = tk.Frame(main, bg=COLORS["bg_main"])
        body_frame.pack(fill="both", expand=True)

        self._body_text = tk.Text(
            body_frame, bg=COLORS["bg_main"], fg=COLORS["text_primary"],
            font=_FONT_BODY, wrap="word", borderwidth=0, highlightthickness=0,
            padx=16, pady=12, insertbackground=COLORS["neon_cyan"],
            selectbackground=COLORS["bg_elevated"],
        )
        scrollbar = tk.Scrollbar(body_frame, orient="vertical", command=self._body_text.yview)
        self._body_text.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self._body_text.pack(side="left", fill="both", expand=True)

        body_content = self._full_body or self._email_data.snippet or ""
        self._body_text.insert("1.0", body_content)
        self._body_text.configure(state="disabled")

        # Separator
        tk.Frame(main, bg=COLORS["neon_cyan"], height=1).pack(fill="x")

        # Action bar
        actions = tk.Frame(main, bg=COLORS["bg_elevated"], padx=12, pady=8)
        actions.pack(fill="x")

        row1 = tk.Frame(actions, bg=COLORS["bg_elevated"])
        row1.pack(fill="x", pady=(0, 4))

        self._make_button(row1, "REPLY", "#006400",
                          command=self._on_reply).pack(side="left", padx=(0, 6))
        self._make_button(row1, "COMPOSE", "#005577",
                          command=self._on_compose_new).pack(side="left", padx=(0, 6))

        read_label = "MARK UNREAD" if ed.read else "MARK READ"
        self._make_button(row1, read_label, "#555500",
                          command=self._on_toggle_read).pack(side="left", padx=(0, 6))
        self._make_button(row1, "SPAM", "#8B8000",
                          command=self._on_spam).pack(side="left", padx=(0, 6))
        self._make_button(row1, "DELETE", "#8B0000",
                          command=self._on_delete).pack(side="left", padx=(0, 6))

        row2 = tk.Frame(actions, bg=COLORS["bg_elevated"])
        row2.pack(fill="x")

        self._make_button(row2, "THUNDERBIRD", "#1E90FF",
                          command=self._on_thunderbird).pack(side="left", padx=(0, 6))
        self._make_button(row2, "CLOSE", COLORS.get("neon_cyan", "#00fff9"),
                          fg_color=COLORS["bg_main"],
                          command=self.destroy).pack(side="left")

        # Status bar
        self._status_label = tk.Label(
            main, text="", bg=COLORS["bg_main"], fg=COLORS["text_muted"],
            font=_FONT_SMALL, anchor="w", padx=12
        )
        self._status_label.pack(fill="x")

    # ── COMPOSE VIEW ───────────────────────────────────────────────

    def _build_compose_view(self, reply_to: str = "", reply_subject: str = "",
                            reply_body: str = "", in_reply_to: str = "",
                            references: str = ""):
        self._clear_content()
        self._in_reply_to = in_reply_to
        self._references = references
        self._attachments = []

        outer = tk.Frame(self, bg=COLORS["neon_cyan"], padx=2, pady=2)
        outer.pack(fill="both", expand=True)
        main = tk.Frame(outer, bg=COLORS["bg_main"])
        main.pack(fill="both", expand=True)

        title = "REPLY" if reply_to else "COMPOSE"
        self._build_titlebar(main, f"MAIL // {title}")

        # To field
        form = tk.Frame(main, bg=COLORS["bg_elevated"], padx=16, pady=10)
        form.pack(fill="x")

        to_row = tk.Frame(form, bg=COLORS["bg_elevated"])
        to_row.pack(fill="x", pady=2)
        tk.Label(to_row, text="To:", bg=COLORS["bg_elevated"],
                 fg=COLORS["text_muted"], font=_FONT_HEADER, width=9, anchor="w").pack(side="left")
        self._to_entry = tk.Entry(
            to_row, bg=COLORS["bg_main"], fg=COLORS["text_primary"],
            font=_FONT, insertbackground=COLORS["neon_cyan"],
            borderwidth=1, relief="solid", highlightcolor=COLORS["neon_cyan"],
        )
        self._to_entry.pack(side="left", fill="x", expand=True)
        if reply_to:
            self._to_entry.insert(0, reply_to)

        # Subject field
        subj_row = tk.Frame(form, bg=COLORS["bg_elevated"])
        subj_row.pack(fill="x", pady=2)
        tk.Label(subj_row, text="Subject:", bg=COLORS["bg_elevated"],
                 fg=COLORS["text_muted"], font=_FONT_HEADER, width=9, anchor="w").pack(side="left")
        self._subject_entry = tk.Entry(
            subj_row, bg=COLORS["bg_main"], fg=COLORS["text_primary"],
            font=_FONT, insertbackground=COLORS["neon_cyan"],
            borderwidth=1, relief="solid", highlightcolor=COLORS["neon_cyan"],
        )
        self._subject_entry.pack(side="left", fill="x", expand=True)
        if reply_subject:
            self._subject_entry.insert(0, reply_subject)

        # Separator
        tk.Frame(main, bg=COLORS["neon_cyan"], height=1).pack(fill="x")

        # Body text area
        body_frame = tk.Frame(main, bg=COLORS["bg_main"])
        body_frame.pack(fill="both", expand=True)

        self._compose_text = tk.Text(
            body_frame, bg=COLORS["bg_main"], fg=COLORS["text_primary"],
            font=_FONT_BODY, wrap="word", borderwidth=0, highlightthickness=0,
            padx=16, pady=12, insertbackground=COLORS["neon_cyan"],
            selectbackground=COLORS["bg_elevated"],
            undo=True,
        )
        scrollbar = tk.Scrollbar(body_frame, orient="vertical", command=self._compose_text.yview)
        self._compose_text.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self._compose_text.pack(side="left", fill="both", expand=True)

        if reply_body:
            self._compose_text.insert("1.0", f"\n\n--- Original ---\n{reply_body}")
            self._compose_text.mark_set("insert", "1.0")

        # Separator
        tk.Frame(main, bg=COLORS["neon_cyan"], height=1).pack(fill="x")

        # Attachments section
        attach_frame = tk.Frame(main, bg=COLORS["bg_elevated"], padx=12, pady=6)
        attach_frame.pack(fill="x")

        attach_header = tk.Frame(attach_frame, bg=COLORS["bg_elevated"])
        attach_header.pack(fill="x")
        tk.Label(attach_header, text="Attachments:", bg=COLORS["bg_elevated"],
                 fg=COLORS["text_muted"], font=_FONT_SMALL).pack(side="left")
        self._make_button(attach_header, "+ ADD", "#333333",
                          command=self._on_add_attachment).pack(side="right")

        self._attach_list_frame = tk.Frame(attach_frame, bg=COLORS["bg_elevated"])
        self._attach_list_frame.pack(fill="x")

        # Separator
        tk.Frame(main, bg=COLORS["neon_cyan"], height=1).pack(fill="x")

        # Action bar
        actions = tk.Frame(main, bg=COLORS["bg_elevated"], padx=12, pady=8)
        actions.pack(fill="x")

        self._make_button(actions, "SEND", "#006400",
                          command=self._on_send).pack(side="left", padx=(0, 6))
        self._make_button(actions, "SAVE DRAFT", "#555500",
                          command=self._on_save_draft).pack(side="left", padx=(0, 6))
        self._make_button(actions, "CLOSE", COLORS.get("neon_cyan", "#00fff9"),
                          fg_color=COLORS["bg_main"],
                          command=self.destroy).pack(side="left")

        # Status bar
        self._status_label = tk.Label(
            main, text="", bg=COLORS["bg_main"], fg=COLORS["text_muted"],
            font=_FONT_SMALL, anchor="w", padx=12
        )
        self._status_label.pack(fill="x")

        # Focus the body or to field
        if reply_to:
            self._compose_text.focus_set()
        else:
            self._to_entry.focus_set()

    # ── Attachment management ──────────────────────────────────────

    def _on_add_attachment(self):
        path = filedialog.askopenfilename(
            title="Datei anhängen",
            parent=self,
        )
        if path and path not in self._attachments:
            self._attachments.append(path)
            self._refresh_attachment_list()

    def _refresh_attachment_list(self):
        for w in self._attach_list_frame.winfo_children():
            w.destroy()
        for fp in self._attachments:
            name = Path(fp).name
            row = tk.Frame(self._attach_list_frame, bg=COLORS["bg_elevated"])
            row.pack(fill="x", pady=1)
            tk.Label(row, text=f"  {name}", bg=COLORS["bg_elevated"],
                     fg=COLORS["text_primary"], font=_FONT_SMALL, anchor="w").pack(side="left")
            rm_btn = tk.Label(row, text=" \u2715 ", bg=COLORS["bg_elevated"],
                              fg=COLORS["error"], font=_FONT_SMALL, cursor="hand2")
            rm_btn.pack(side="right")
            rm_btn.bind("<Button-1>", lambda e, p=fp: self._remove_attachment(p))

    def _remove_attachment(self, filepath: str):
        if filepath in self._attachments:
            self._attachments.remove(filepath)
            self._refresh_attachment_list()

    # ── Read view actions ──────────────────────────────────────────

    def _on_reply(self):
        """Switch to compose mode with reply context."""
        ed = self._email_data
        # Extract reply-to address (use From header)
        reply_to = ed.sender
        # Build Re: subject
        subject = ed.subject or ""
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        # Quote original body
        body = self._full_body or ed.snippet or ""

        self._build_compose_view(
            reply_to=reply_to,
            reply_subject=subject,
            reply_body=body,
            in_reply_to=ed.msg_id,
            references=ed.msg_id,
        )

    def _on_compose_new(self):
        """Switch to blank compose mode."""
        self._email_data = None
        self._build_compose_view()

    def _on_toggle_read(self):
        ed = self._email_data
        new_read = not ed.read
        self._dispatch("email_toggle_read", folder=ed.folder, msg_id=ed.msg_id, mark_read=new_read)
        ed.read = new_read
        self._show_status(f"Marked as {'read' if new_read else 'unread'}.", COLORS["neon_green"])
        # Rebuild to update button text
        self.after(500, self._build_read_view)

    def _on_spam(self):
        ed = self._email_data
        self._dispatch("email_spam", folder=ed.folder, msg_id=ed.msg_id, query=ed.sender)
        self._show_status("Moved to spam.", COLORS["warning"])
        self.after(1000, self.destroy)

    def _on_delete(self):
        ed = self._email_data
        self._dispatch("email_delete_single", folder=ed.folder, msg_id=ed.msg_id, query=ed.sender)
        self._show_status("Deleted.", COLORS["error"])
        self.after(1000, self.destroy)

    def _on_thunderbird(self):
        try:
            subprocess.Popen(["thunderbird"], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            try:
                subprocess.Popen(["snap", "run", "thunderbird"], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                self._show_status("Thunderbird not found.", COLORS["error"])

    # ── Compose actions ────────────────────────────────────────────

    def _on_send(self):
        to = self._to_entry.get().strip()
        subject = self._subject_entry.get().strip()
        body = self._compose_text.get("1.0", "end-1c").strip()

        if not to:
            self._show_status("Recipient (To) is required.", COLORS["error"])
            self._to_entry.focus_set()
            return
        if not subject:
            self._show_status("Subject is required.", COLORS["error"])
            self._subject_entry.focus_set()
            return

        self._show_status("Sending...", COLORS["neon_cyan"])

        kwargs = {
            "to": to, "subject": subject, "body": body,
            "attachments": self._attachments if self._attachments else None,
        }
        if hasattr(self, "_in_reply_to") and self._in_reply_to:
            kwargs["in_reply_to"] = self._in_reply_to
            kwargs["references"] = self._references

        self._dispatch("email_send", **kwargs)
        self._show_status("Email sent!", COLORS["neon_green"])
        self.after(1500, self.destroy)

    def _on_save_draft(self):
        to = self._to_entry.get().strip()
        subject = self._subject_entry.get().strip()
        body = self._compose_text.get("1.0", "end-1c").strip()

        self._dispatch("email_draft", to=to, subject=subject, body=body)
        self._show_status("Draft saved!", COLORS["neon_green"])

    # ── Utility ────────────────────────────────────────────────────

    @staticmethod
    def _format_date(date_str: str) -> str:
        import email.utils
        from datetime import datetime
        try:
            dt = email.utils.parsedate_tz(date_str)
            if dt:
                ts = email.utils.mktime_tz(dt)
                d = datetime.fromtimestamp(ts)
                return d.strftime("%d.%m.%Y %H:%M")
        except Exception:
            pass
        return date_str[:25] if date_str else "?"

    def update_body(self, full_body: str):
        """Update the body text after async fetch completes."""
        self._full_body = full_body
        if hasattr(self, "_body_text") and self._body_text.winfo_exists():
            self._body_text.configure(state="normal")
            self._body_text.delete("1.0", "end")
            self._body_text.insert("1.0", full_body)
            self._body_text.configure(state="disabled")
