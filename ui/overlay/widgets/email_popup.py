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

        # Pick up pre-injected attachments (avoids double build)
        # Immediately consume and clear to prevent leakage to next instance
        pre_att = getattr(self.__class__, '_pre_attachments', None)
        if pre_att:
            self._read_attachments_data = list(pre_att)  # copy, don't share ref
            self.__class__._pre_attachments = None
        else:
            self._read_attachments_data = []

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

        # Force focus to this window on any click (overrideredirect windows
        # don't receive focus automatically from the window manager)
        self.bind("<Button-1>", self._force_focus, add=True)

        # Scroll events are handled per-widget (no global bind_all)

        if email_data:
            self._build_read_view()
        else:
            self._build_compose_view()

        # Take focus immediately
        self.focus_force()

    def _force_focus(self, event=None):
        """Force focus to popup and to the clicked widget if it accepts input."""
        self.focus_force()
        # In reply-intent mode, ALWAYS redirect focus to the intent text field
        # unless user clicked directly on a different editable widget (Entry/Text)
        if hasattr(self, "_intent_text"):
            try:
                if self._intent_text.winfo_exists():
                    clicked = event.widget if event else None
                    # Only let focus go elsewhere if it's an editable Entry
                    if isinstance(clicked, tk.Entry):
                        clicked.focus_set()
                    else:
                        self._intent_text.focus_set()
                    return
            except Exception:
                pass
        if event and event.widget:
            try:
                w = event.widget
                if isinstance(w, (tk.Text, tk.Entry)):
                    # Don't focus disabled text widgets (preview)
                    if isinstance(w, tk.Text):
                        try:
                            if w.cget("state") == "disabled":
                                return
                        except Exception:
                            pass
                    w.focus_set()
            except Exception:
                pass

    def _bind_scroll_to_text(self, text_widget: tk.Text):
        """Bind scroll events directly to a Text widget (no global bind_all)."""
        def _scroll(event):
            if event.num == 4:
                text_widget.yview_scroll(-3, "units")
            elif event.num == 5:
                text_widget.yview_scroll(3, "units")
            elif event.delta:
                text_widget.yview_scroll(-1 * (event.delta // 120), "units")
            return "break"
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            text_widget.bind(seq, _scroll)

    def destroy(self):
        if self._on_destroy:
            try:
                self._on_destroy()
            except Exception:
                pass
        super().destroy()

    # ── Shared helpers ─────────────────────────────────────────────

    def _clear_content(self):
        # Remove intent_text ref so _force_focus doesn't redirect to dead widget
        if hasattr(self, "_intent_text"):
            del self._intent_text
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

    # ── Button styles ──
    _BTN_BG = "#1a1a2e"
    _BTN_BG_HOVER = "#282840"
    _BTN_BORDER = "#333355"

    def _make_button(self, parent, text, fg_color="#aaaacc", command=None,
                     bg_color=None, min_width=0):
        """Create a uniform cyberpunk-styled action button.

        All buttons share the same dark bg; only the text colour varies
        to indicate function (green=positive, red=destructive, etc.).
        """
        bg = bg_color or self._BTN_BG
        btn = tk.Frame(parent, bg=self._BTN_BORDER, padx=1, pady=1)
        lbl = tk.Label(
            btn, text=text, bg=bg, fg=fg_color,
            font=_FONT_BOLD, padx=10, pady=4, cursor="hand2",
        )
        if min_width:
            lbl.configure(width=min_width)
        lbl.pack(fill="both", expand=True)
        if command:
            lbl.bind("<Button-1>", lambda e: command())
        lbl.bind("<Enter>", lambda e: lbl.configure(bg=self._BTN_BG_HOVER))
        lbl.bind("<Leave>", lambda e: lbl.configure(bg=bg))
        # Store label ref for external access
        btn._lbl = lbl
        return btn

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

        # Separator (below header)
        tk.Frame(main, bg=COLORS["neon_cyan"], height=1).pack(fill="x")

        # ── Pack bottom elements FIRST so they are always visible ──

        # Status bar (very bottom)
        self._status_label = tk.Label(
            main, text="", bg=COLORS["bg_main"], fg=COLORS["text_muted"],
            font=_FONT_SMALL, anchor="w", padx=12
        )
        self._status_label.pack(side="bottom", fill="x")

        # Action bar
        actions = tk.Frame(main, bg=COLORS["bg_elevated"], padx=10, pady=8)
        actions.pack(side="bottom", fill="x")

        # Row 1: primary communication actions
        row1 = tk.Frame(actions, bg=COLORS["bg_elevated"])
        row1.pack(fill="x", pady=(0, 4))

        self._make_button(row1, "REPLY", fg_color="#00cc88",
                          command=self._on_reply).pack(side="left", padx=2)
        self._make_button(row1, "FORWARD", fg_color="#44aadd",
                          command=self._on_forward).pack(side="left", padx=2)
        self._make_button(row1, "COMPOSE", fg_color="#8899bb",
                          command=self._on_compose_new).pack(side="left", padx=2)
        self._make_button(row1, "THREAD", fg_color="#aa88cc",
                          command=self._on_thread).pack(side="left", padx=2)
        read_label = "MARK UNREAD" if ed.read else "MARK READ"
        self._make_button(row1, read_label, fg_color="#8899bb",
                          command=self._on_toggle_read).pack(side="left", padx=2)

        # Row 2: destructive + utility
        row2 = tk.Frame(actions, bg=COLORS["bg_elevated"])
        row2.pack(fill="x")

        self._make_button(row2, "SPAM", fg_color="#ccaa33",
                          command=self._on_spam).pack(side="left", padx=2)
        self._make_button(row2, "DELETE", fg_color="#dd4444",
                          command=self._on_delete).pack(side="left", padx=2)
        self._make_button(row2, "THUNDERBIRD", fg_color="#5588cc",
                          command=self._on_thunderbird).pack(side="left", padx=2)
        self._make_button(row2, "CLOSE", fg_color=COLORS.get("neon_cyan", "#00fff9"),
                          command=self.destroy).pack(side="right", padx=2)

        # Separator above actions
        tk.Frame(main, bg=COLORS["neon_cyan"], height=1).pack(side="bottom", fill="x")

        # ── Attachment preview section (above body, below actions) ──
        self._read_attachments = getattr(self, "_read_attachments_data", None) or []
        if self._read_attachments:
            att_sep = tk.Frame(main, bg=COLORS["neon_cyan"], height=1)
            att_sep.pack(side="bottom", fill="x")

            att_frame = tk.Frame(main, bg=COLORS["bg_elevated"], padx=12, pady=6)
            att_frame.pack(side="bottom", fill="x")

            att_header = tk.Frame(att_frame, bg=COLORS["bg_elevated"])
            att_header.pack(fill="x")
            tk.Label(att_header, text=f"Attachments ({len(self._read_attachments)}):",
                     bg=COLORS["bg_elevated"], fg=COLORS["text_muted"],
                     font=_FONT_SMALL).pack(side="left")

            for att in self._read_attachments[:10]:
                arow = tk.Frame(att_frame, bg=COLORS["bg_elevated"])
                arow.pack(fill="x", pady=1)

                fname = att.get("filename", "unknown")
                fsize = att.get("size", 0)
                ftype = att.get("content_type", "")
                aidx = att.get("index", 0)

                # Format size
                if fsize < 1024:
                    size_str = f"{fsize} B"
                elif fsize < 1024 * 1024:
                    size_str = f"{fsize // 1024} KB"
                else:
                    size_str = f"{fsize // (1024 * 1024)} MB"

                # Type icon
                icon = "\U0001f4ce"  # paperclip
                if "pdf" in ftype:
                    icon = "\U0001f4c4"  # page
                elif "image" in ftype:
                    icon = "\U0001f5bc"  # picture
                elif "zip" in ftype or "archive" in ftype:
                    icon = "\U0001f4e6"  # package

                info_text = f"  {icon} {fname}  ({size_str})"
                tk.Label(arow, text=info_text, bg=COLORS["bg_elevated"],
                         fg=COLORS["text_primary"], font=_FONT_SMALL,
                         anchor="w").pack(side="left", fill="x", expand=True)

                save_btn = tk.Label(
                    arow, text=" SAVE ", bg=self._BTN_BG,
                    fg="#44aadd", font=("Consolas", 8, "bold"),
                    cursor="hand2", padx=4,
                )
                save_btn.pack(side="right", padx=2)
                save_btn.bind("<Button-1>", lambda e, i=aidx, f=fname: self._on_save_attachment(i, f))
                save_btn.bind("<Enter>", lambda e, b=save_btn: b.configure(bg=self._BTN_BG_HOVER))
                save_btn.bind("<Leave>", lambda e, b=save_btn: b.configure(bg=self._BTN_BG))

        # ── Body section fills remaining space (packed LAST) ──
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
        self._bind_scroll_to_text(self._body_text)

    # ── COMPOSE VIEW ───────────────────────────────────────────────

    def _build_compose_view(self, reply_to: str = "", reply_subject: str = "",
                            reply_body: str = "", in_reply_to: str = "",
                            references: str = "", cc: str = ""):
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

        # Form fields
        form = tk.Frame(main, bg=COLORS["bg_elevated"], padx=16, pady=10)
        form.pack(fill="x")

        def _make_field(parent, label, value=""):
            row = tk.Frame(parent, bg=COLORS["bg_elevated"])
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, bg=COLORS["bg_elevated"],
                     fg=COLORS["text_muted"], font=_FONT_HEADER, width=9, anchor="w").pack(side="left")
            entry = tk.Entry(
                row, bg=COLORS["bg_main"], fg=COLORS["text_primary"],
                font=_FONT, insertbackground=COLORS["neon_cyan"],
                borderwidth=1, relief="solid", highlightcolor=COLORS["neon_cyan"],
            )
            entry.pack(side="left", fill="x", expand=True)
            if value:
                entry.insert(0, value)
            return entry

        self._to_entry = _make_field(form, "To:", reply_to)
        self._cc_entry = _make_field(form, "CC:", cc)
        self._bcc_entry = _make_field(form, "BCC:")

        # Subject field
        self._subject_entry = _make_field(form, "Subject:", reply_subject)

        # Separator (below form)
        tk.Frame(main, bg=COLORS["neon_cyan"], height=1).pack(fill="x")

        # ── Pack bottom elements FIRST so they are always visible ──

        # Status bar (very bottom)
        self._status_label = tk.Label(
            main, text="", bg=COLORS["bg_main"], fg=COLORS["text_muted"],
            font=_FONT_SMALL, anchor="w", padx=12
        )
        self._status_label.pack(side="bottom", fill="x")

        # Action bar
        actions = tk.Frame(main, bg=COLORS["bg_elevated"], padx=10, pady=8)
        actions.pack(side="bottom", fill="x")

        self._make_button(actions, "SEND", fg_color="#00cc88",
                          command=self._on_send).pack(side="left", padx=2)
        self._make_button(actions, "SAVE DRAFT", fg_color="#ccaa33",
                          command=self._on_save_draft).pack(side="left", padx=2)
        self._make_button(actions, "CLOSE", fg_color=COLORS.get("neon_cyan", "#00fff9"),
                          command=self.destroy).pack(side="right", padx=2)

        # Separator above actions
        tk.Frame(main, bg=COLORS["neon_cyan"], height=1).pack(side="bottom", fill="x")

        # Attachments section
        attach_frame = tk.Frame(main, bg=COLORS["bg_elevated"], padx=12, pady=6)
        attach_frame.pack(side="bottom", fill="x")

        attach_header = tk.Frame(attach_frame, bg=COLORS["bg_elevated"])
        attach_header.pack(fill="x")
        tk.Label(attach_header, text="Attachments:", bg=COLORS["bg_elevated"],
                 fg=COLORS["text_muted"], font=_FONT_SMALL).pack(side="left")
        self._make_button(attach_header, "+ ADD", fg_color="#8899bb",
                          command=self._on_add_attachment).pack(side="right")

        # Scrollable attachment list (max 80px height)
        self._attach_canvas = tk.Canvas(
            attach_frame, bg=COLORS["bg_elevated"],
            highlightthickness=0, height=0,
        )
        self._attach_list_frame = tk.Frame(self._attach_canvas, bg=COLORS["bg_elevated"])
        self._attach_canvas.create_window(
            (0, 0), window=self._attach_list_frame, anchor="nw", tags="attach_win"
        )
        self._attach_list_frame.bind("<Configure>", self._on_attach_list_configure)
        self._attach_canvas.bind("<Configure>", lambda e: self._attach_canvas.itemconfig(
            "attach_win", width=e.width))
        self._attach_canvas.pack(fill="x")

        # Separator above attachments
        tk.Frame(main, bg=COLORS["neon_cyan"], height=1).pack(side="bottom", fill="x")

        # ── Body text fills remaining space (packed LAST) ──
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

        self._bind_scroll_to_text(self._compose_text)

        if reply_body:
            self._compose_text.insert("1.0", f"\n\n--- Original ---\n{reply_body}")
            self._compose_text.mark_set("insert", "1.0")

        # Focus: body for replies, To for new compose
        if reply_to:
            self._compose_text.focus_set()
        else:
            self._to_entry.focus_set()

        self._sending = False

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

    _ATTACH_MAX_H = 80

    def _on_attach_list_configure(self, event=None):
        """Resize attachment canvas to fit content, max 80px."""
        if not hasattr(self, '_attach_canvas'):
            return
        try:
            self._attach_canvas.configure(scrollregion=self._attach_canvas.bbox("all"))
            req_h = self._attach_list_frame.winfo_reqheight()
            h = min(req_h, self._ATTACH_MAX_H) if req_h > 0 else 0
            self._attach_canvas.configure(height=h)
        except tk.TclError:
            pass

    # ── Read view actions ──────────────────────────────────────────

    def _on_reply(self):
        """Show reply intent prompt, then generate AI reply."""
        self._build_reply_intent_view()

    def _build_reply_intent_view(self, reply_all: bool = False):
        """Ask the user what they want to reply before generating."""
        self._clear_content()
        self._reply_all = reply_all
        ed = self._email_data

        outer = tk.Frame(self, bg=COLORS["neon_cyan"], padx=2, pady=2)
        outer.pack(fill="both", expand=True)
        main = tk.Frame(outer, bg=COLORS["bg_main"])
        main.pack(fill="both", expand=True)

        self._build_titlebar(main, "REPLY // Was willst du antworten?")

        # Show original email context (compact)
        ctx = tk.Frame(main, bg=COLORS["bg_elevated"], padx=16, pady=8)
        ctx.pack(fill="x")
        from overlay.widgets.email_card import format_sender
        sender_short = format_sender(ed.sender)
        subj_short = (ed.subject or "(kein Betreff)")[:60]
        tk.Label(ctx, text=f"An: {sender_short}", bg=COLORS["bg_elevated"],
                 fg=COLORS["text_muted"], font=_FONT_SMALL, anchor="w").pack(anchor="w")
        tk.Label(ctx, text=f"Re: {subj_short}", bg=COLORS["bg_elevated"],
                 fg=COLORS["text_muted"], font=_FONT_SMALL, anchor="w").pack(anchor="w")

        tk.Frame(main, bg=COLORS["neon_cyan"], height=1).pack(fill="x")

        # ── Pack bottom elements FIRST ──

        # Status bar (very bottom)
        self._status_label = tk.Label(
            main, text="Enter = Absenden  |  Shift+Enter = Neue Zeile",
            bg=COLORS["bg_elevated"], fg=COLORS["text_muted"],
            font=_FONT_SMALL, anchor="w", padx=12
        )
        self._status_label.pack(side="bottom", fill="x")

        # Buttons row
        btn_row = tk.Frame(main, bg=COLORS["bg_elevated"], padx=10, pady=6)
        btn_row.pack(side="bottom", fill="x")

        self._make_button(btn_row, "GENERATE REPLY", fg_color="#00cc88",
                          command=self._on_generate_reply).pack(side="left", padx=2)
        self._make_button(btn_row, "BACK", fg_color="#8899bb",
                          command=self._build_read_view).pack(side="left", padx=2)

        # Chat input section
        input_section = tk.Frame(main, bg=COLORS["bg_elevated"], padx=12, pady=10)
        input_section.pack(side="bottom", fill="x")

        # Instruction label
        tk.Label(input_section, text="Was soll Frank antworten?",
                 bg=COLORS["bg_elevated"], fg=COLORS["neon_cyan"],
                 font=_FONT_BOLD, anchor="w").pack(fill="x", pady=(0, 6))

        # User intent text area — clearly visible with cyan border
        intent_border = tk.Frame(input_section, bg=COLORS["neon_cyan"], padx=1, pady=1)
        intent_border.pack(fill="x")

        self._intent_text = tk.Text(
            intent_border, bg="#1a1a2e", fg="#ffffff",
            font=_FONT_BODY, wrap="word", borderwidth=0,
            highlightthickness=0,
            insertbackground=COLORS["neon_cyan"], height=4,
            padx=10, pady=8,
        )
        self._intent_text.pack(fill="x")

        # Bind Enter to generate (Shift+Enter for newline)
        self._intent_text.bind("<Return>", self._on_intent_enter)

        # Bind click on intent text to grab focus (overrideredirect fix)
        self._intent_text.bind("<Button-1>", self._focus_intent, add=True)

        # Separator above input
        tk.Frame(main, bg=COLORS["neon_cyan"], height=1).pack(side="bottom", fill="x")

        # ── Body preview fills remaining space ──
        body_preview = self._full_body or ed.snippet or ""
        if body_preview:
            preview_frame = tk.Frame(main, bg=COLORS["bg_main"])
            preview_frame.pack(fill="both", expand=True)
            tk.Label(preview_frame, text="Original:", bg=COLORS["bg_main"],
                     fg=COLORS["text_muted"], font=_FONT_SMALL,
                     anchor="w").pack(fill="x", padx=16, pady=(8, 0))
            preview_text = tk.Text(
                preview_frame, bg=COLORS["bg_main"], fg=COLORS["text_secondary"],
                font=_FONT_SMALL, wrap="word", borderwidth=0,
                highlightthickness=0, padx=16, pady=4, height=8,
            )
            preview_text.pack(fill="both", expand=True)
            preview_text.insert("1.0", body_preview[:2000])
            preview_text.configure(state="disabled", takefocus=False)
            self._bind_scroll_to_text(preview_text)

        # Force focus to intent text with short delay (overrideredirect needs this)
        self.after(100, self._focus_intent)

    def _focus_intent(self, event=None):
        """Force keyboard focus to the reply intent text widget."""
        if hasattr(self, "_intent_text"):
            try:
                self.focus_force()
                self._intent_text.focus_set()
            except Exception:
                pass

    def _on_intent_enter(self, event):
        """Enter generates reply, Shift+Enter inserts newline."""
        if event.state & 0x1:  # Shift held
            return  # let default handler insert newline
        self._on_generate_reply()
        return "break"

    def _on_generate_reply(self):
        """Send user intent + original email to LLM for reply generation."""
        intent = self._intent_text.get("1.0", "end-1c").strip()
        if not intent:
            self._show_status("Bitte beschreib was du antworten willst.", COLORS["error"])
            return

        ed = self._email_data
        subject = ed.subject or ""
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        body = self._full_body or ed.snippet or ""

        reply_all = getattr(self, "_reply_all", False)

        self._show_status("Generating reply...", COLORS["neon_cyan"])
        self._dispatch(
            "email_reply_draft",
            sender=ed.sender, subject=ed.subject,
            body=body, reply_to=ed.sender,
            reply_subject=subject,
            msg_id=ed.msg_id,
            user_intent=intent,
            reply_all=reply_all,
            to=getattr(ed, "to", ""),
            cc=getattr(ed, "cc", ""),
        )

    def _on_thread(self):
        """Show conversation thread for this email."""
        ed = self._email_data
        self._dispatch(
            "email_thread",
            subject=ed.subject or "",
            msg_id=ed.msg_id or "",
            folder=ed.folder,
        )
        self._show_status("Loading thread...", COLORS["neon_cyan"])

    def _on_reply_all(self):
        """Reply to all recipients."""
        self._build_reply_intent_view(reply_all=True)

    def _on_forward(self):
        """Forward this email."""
        ed = self._email_data
        subject = ed.subject or ""
        if not subject.lower().startswith("fwd:"):
            subject = f"Fwd: {subject}"
        body = self._full_body or ed.snippet or ""
        from overlay.widgets.email_card import format_sender
        fwd_body = (
            f"\n\n--- Forwarded message ---\n"
            f"From: {ed.sender}\n"
            f"Date: {self._format_date(ed.date)}\n"
            f"Subject: {ed.subject or '(kein Betreff)'}\n\n"
            f"{body}"
        )
        self._build_compose_view(reply_subject=subject, reply_body=fwd_body)

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
        self.destroy()

    def _on_delete(self):
        ed = self._email_data
        self._dispatch("email_delete_single", folder=ed.folder, msg_id=ed.msg_id, query=ed.sender)
        self.destroy()

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
        cc = self._cc_entry.get().strip() if hasattr(self, "_cc_entry") else ""
        bcc = self._bcc_entry.get().strip() if hasattr(self, "_bcc_entry") else ""

        if not to:
            self._show_status("Recipient (To) is required.", COLORS["error"])
            self._to_entry.focus_set()
            return
        if not subject:
            self._show_status("Subject is required.", COLORS["error"])
            self._subject_entry.focus_set()
            return

        # Check attachment sizes (25MB Gmail limit)
        if self._attachments:
            total_size = sum(Path(f).stat().st_size for f in self._attachments if Path(f).exists())
            if total_size > 25 * 1024 * 1024:
                mb = total_size // (1024 * 1024)
                self._show_status(f"Attachments too large ({mb}MB). Limit: 25MB.", COLORS["error"])
                return

        self._show_status("Sending...", COLORS["neon_cyan"])
        self._sending = True

        kwargs = {
            "to": to, "subject": subject, "body": body,
            "attachments": self._attachments if self._attachments else None,
        }
        if cc:
            kwargs["cc"] = cc
        if bcc:
            kwargs["bcc"] = bcc
        if hasattr(self, "_in_reply_to") and self._in_reply_to:
            kwargs["in_reply_to"] = self._in_reply_to
            kwargs["references"] = self._references

        self._dispatch("email_send", **kwargs)

    def send_result(self, success: bool, message: str = "", warning: bool = False):
        """Called by the worker after send completes."""
        self._sending = False
        if warning:
            self._show_status(message or "SMTP failed — opened in Thunderbird.", "#FFD700")
        elif success:
            self._show_status(message or "Email sent!", COLORS["neon_green"])
            self.after(1500, self.destroy)
        else:
            self._show_status(message or "Send failed!", COLORS["error"])

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

    def update_body(self, full_body: str, attachments: Optional[List[Dict]] = None):
        """Update the body text after async fetch completes."""
        self._full_body = full_body
        if attachments is not None:
            self._read_attachments_data = attachments
            # Rebuild read view to show attachments
            if attachments and self._email_data:
                self._build_read_view()
                return
        if hasattr(self, "_body_text") and self._body_text.winfo_exists():
            self._body_text.configure(state="normal")
            self._body_text.delete("1.0", "end")
            self._body_text.insert("1.0", full_body)
            self._body_text.configure(state="disabled")

    def _on_save_attachment(self, att_index: int, filename: str):
        """Save an attachment to ~/Downloads via IO dispatch."""
        ed = self._email_data
        if ed and ed.msg_id:
            self._show_status(f"Saving {filename}...", COLORS["neon_cyan"])
            self._dispatch("email_save_attachment",
                           folder=ed.folder, msg_id=ed.msg_id,
                           attachment_index=att_index)

    def fill_compose(self, reply_to: str, reply_subject: str,
                     reply_body: str, ai_draft: str,
                     in_reply_to: str = "", references: str = "",
                     cc: str = ""):
        """Switch to compose view with AI-generated reply pre-filled."""
        self._build_compose_view(
            reply_to=reply_to,
            reply_subject=reply_subject,
            reply_body=reply_body,
            in_reply_to=in_reply_to,
            references=references,
            cc=cc,
        )
        # Insert AI draft at top of compose text (before quoted original)
        if ai_draft and hasattr(self, "_compose_text"):
            self._compose_text.insert("1.0", ai_draft)
            self._compose_text.mark_set("insert", "1.0")
