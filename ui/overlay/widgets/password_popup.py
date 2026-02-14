"""Password Manager Popup — Cyberpunk-styled Toplevel window.

Screens: Master-Password unlock → Password list → Add/Edit form.
All Fernet encryption handled by password_store module.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
import tkinter as tk
from typing import Optional, Callable

from overlay.constants import COLORS, LOG
from overlay.bsn.constants import get_workarea_y

# Ensure tools/ importable
try:
    from config.paths import TOOLS_DIR as _TOOLS_DIR
except ImportError:
    from pathlib import Path as _Path
    _TOOLS_DIR = _Path("/home/ai-core-node/aicore/opt/aicore/tools")
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import password_store

_FONT = ("Consolas", 10)
_FONT_BOLD = ("Consolas", 10, "bold")
_FONT_TITLE = ("Consolas", 11, "bold")
_FONT_SMALL = ("Consolas", 9)
_AUTO_LOCK_MS = 300_000  # 5 minutes


class PasswordPopup(tk.Toplevel):
    """Cyberpunk password manager popup."""

    def __init__(self, parent, on_destroy: Optional[Callable] = None,
                 on_autotype: Optional[Callable] = None):
        super().__init__(parent)
        self._parent = parent
        self._on_destroy = on_destroy
        self._on_autotype = on_autotype
        self._auto_lock_id: Optional[str] = None

        self.title("PASSWORD MANAGER")
        self.configure(bg=COLORS["bg_main"])
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.95)
        except tk.TclError:
            pass

        # Position next to parent
        self.update_idletasks()
        parent.update_idletasks()
        px = parent.winfo_x()
        py = parent.winfo_y()
        pw = parent.winfo_width()
        screen_w = self.winfo_screenwidth()
        popup_w, popup_h = 420, 500
        # Try right of parent, fall back to left
        x = px + pw + 8
        if x + popup_w > screen_w:
            x = max(0, px - popup_w - 8)
        y = max(get_workarea_y(), py)
        self.geometry(f"{popup_w}x{popup_h}+{x}+{y}")

        # Drag state
        self._drag_x = 0
        self._drag_y = 0

        # Show appropriate screen
        if password_store.is_unlocked():
            self._build_list_screen()
        else:
            self._build_lock_screen()

        self._reset_auto_lock()

        # Activity reset on any key/click
        self.bind("<Key>", lambda e: self._reset_auto_lock())
        self.bind("<Button>", lambda e: self._reset_auto_lock())

    def destroy(self):
        if self._auto_lock_id:
            try:
                self.after_cancel(self._auto_lock_id)
            except Exception:
                pass
        if self._on_destroy:
            try:
                self._on_destroy()
            except Exception:
                pass
        super().destroy()

    # ── Auto-lock ─────────────────────────────────────────────────────

    def _reset_auto_lock(self):
        if self._auto_lock_id:
            try:
                self.after_cancel(self._auto_lock_id)
            except Exception:
                pass
        self._auto_lock_id = self.after(_AUTO_LOCK_MS, self._do_auto_lock)

    def _do_auto_lock(self):
        password_store.lock()
        self._clear_content()
        self._build_lock_screen()

    # ── Shared UI helpers ─────────────────────────────────────────────

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
            titlebar, text="✕", bg=COLORS["bg_elevated"],
            fg=COLORS["text_muted"], font=("Consolas", 12), width=3, cursor="hand2"
        )
        close_btn.pack(side="right", padx=4)
        close_btn.bind("<Button-1>", lambda e: self.destroy())
        close_btn.bind("<Enter>", lambda e: close_btn.configure(fg="#ffffff", bg=COLORS["error"]))
        close_btn.bind("<Leave>", lambda e: close_btn.configure(fg=COLORS["text_muted"], bg=COLORS["bg_elevated"]))

        for w in [titlebar, title_frame]:
            w.bind("<Button-1>", self._start_drag)
            w.bind("<B1-Motion>", self._on_drag)

    def _make_button(self, parent, text, fg_color, bg_color, command):
        btn = tk.Label(
            parent, text=text, bg=bg_color, fg=fg_color,
            font=_FONT_BOLD, padx=12, pady=6, cursor="hand2"
        )
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

    # ── Screen 1: Lock / Master Password ──────────────────────────────

    def _build_lock_screen(self):
        self._clear_content()
        outer = tk.Frame(self, bg=COLORS["neon_cyan"], padx=2, pady=2)
        outer.pack(fill="both", expand=True)
        main = tk.Frame(outer, bg=COLORS["bg_main"])
        main.pack(fill="both", expand=True)

        is_first = not password_store.is_initialized()
        title = "░▒▓ PASSWORT-MANAGER // SETUP" if is_first else "░▒▓ PASSWORT-MANAGER // LOCK"
        self._build_titlebar(main, title)

        content = tk.Frame(main, bg=COLORS["bg_main"], padx=24, pady=20)
        content.pack(fill="both", expand=True)

        # Icon
        tk.Label(
            content, text="🔐", bg=COLORS["bg_main"], font=("Segoe UI", 28)
        ).pack(pady=(20, 10))

        hint = "Set master password:" if is_first else "Enter master password:"
        tk.Label(
            content, text=hint, bg=COLORS["bg_main"],
            fg=COLORS["text_primary"], font=_FONT
        ).pack(pady=(0, 8))

        # Password entry
        pw_frame = tk.Frame(content, bg=COLORS["bg_main"])
        pw_frame.pack(fill="x", pady=(0, 4))
        self._lock_pw_var = tk.StringVar()
        self._lock_pw_entry = tk.Entry(
            pw_frame, textvariable=self._lock_pw_var, show="*",
            bg=COLORS["bg_elevated"], fg=COLORS["text_primary"],
            insertbackground=COLORS["neon_cyan"], font=_FONT,
            relief="flat", bd=0, highlightthickness=1,
            highlightcolor=COLORS["neon_cyan"], highlightbackground=COLORS["text_muted"]
        )
        self._lock_pw_entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 4))
        self._lock_pw_entry.focus_set()

        # Show/hide toggle
        self._pw_visible = False
        self._toggle_btn = tk.Label(
            pw_frame, text="👁", bg=COLORS["bg_elevated"],
            fg=COLORS["text_muted"], font=_FONT, cursor="hand2", padx=6
        )
        self._toggle_btn.pack(side="right")
        self._toggle_btn.bind("<Button-1>", lambda e: self._toggle_pw_visibility())

        # Confirm field (first-time only)
        if is_first:
            tk.Label(
                content, text="Confirm password:", bg=COLORS["bg_main"],
                fg=COLORS["text_primary"], font=_FONT
            ).pack(pady=(8, 4))
            self._lock_pw2_var = tk.StringVar()
            self._lock_pw2_entry = tk.Entry(
                content, textvariable=self._lock_pw2_var, show="*",
                bg=COLORS["bg_elevated"], fg=COLORS["text_primary"],
                insertbackground=COLORS["neon_cyan"], font=_FONT,
                relief="flat", bd=0, highlightthickness=1,
                highlightcolor=COLORS["neon_cyan"], highlightbackground=COLORS["text_muted"]
            )
            self._lock_pw2_entry.pack(fill="x", ipady=6)

        # Error label
        self._lock_error = tk.Label(
            content, text="", bg=COLORS["bg_main"],
            fg=COLORS["error"], font=_FONT_SMALL
        )
        self._lock_error.pack(pady=(8, 0))

        # Buttons
        btn_frame = tk.Frame(content, bg=COLORS["bg_main"])
        btn_frame.pack(fill="x", pady=(16, 0))

        action_text = "ERSTELLEN" if is_first else "ENTSPERREN"
        self._make_button(
            btn_frame, f"✓ {action_text}", "#ffffff", COLORS["success"],
            self._do_unlock
        ).pack(side="left", padx=(0, 8))

        self._make_button(
            btn_frame, "✕ ABBRECHEN", "#ffffff", COLORS["error"],
            self.destroy
        ).pack(side="left")

        # Enter key binding
        self._lock_pw_entry.bind("<Return>", lambda e: self._do_unlock())
        if is_first and hasattr(self, '_lock_pw2_entry'):
            self._lock_pw2_entry.bind("<Return>", lambda e: self._do_unlock())

    def _toggle_pw_visibility(self):
        self._pw_visible = not self._pw_visible
        self._lock_pw_entry.configure(show="" if self._pw_visible else "*")
        self._toggle_btn.configure(fg=COLORS["neon_cyan"] if self._pw_visible else COLORS["text_muted"])

    def _do_unlock(self):
        pw = self._lock_pw_var.get()
        if not pw:
            self._lock_error.configure(text="Enter password!")
            return

        is_first = not password_store.is_initialized()

        if is_first:
            pw2 = self._lock_pw2_var.get() if hasattr(self, '_lock_pw2_var') else ""
            if pw != pw2:
                self._lock_error.configure(text="Passwords do not match!")
                return
            result = password_store.init_store(pw)
        else:
            result = password_store.unlock(pw)

        if result.get("ok"):
            self._build_list_screen()
        else:
            self._lock_error.configure(text=result.get("error", "Error"))

    # ── Screen 2: Password List ───────────────────────────────────────

    def _build_list_screen(self):
        self._clear_content()
        outer = tk.Frame(self, bg=COLORS["neon_cyan"], padx=2, pady=2)
        outer.pack(fill="both", expand=True)
        main = tk.Frame(outer, bg=COLORS["bg_main"])
        main.pack(fill="both", expand=True)

        self._build_titlebar(main, "░▒▓ PASSWORT-MANAGER ▓▒░")

        content = tk.Frame(main, bg=COLORS["bg_main"], padx=12, pady=8)
        content.pack(fill="both", expand=True)

        # Search bar
        search_frame = tk.Frame(content, bg=COLORS["bg_elevated"], padx=8, pady=4)
        search_frame.pack(fill="x", pady=(0, 8))
        tk.Label(
            search_frame, text="🔍", bg=COLORS["bg_elevated"],
            fg=COLORS["text_muted"], font=_FONT_SMALL
        ).pack(side="left")
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *a: self._refresh_list())
        search_entry = tk.Entry(
            search_frame, textvariable=self._search_var,
            bg=COLORS["bg_elevated"], fg=COLORS["text_primary"],
            insertbackground=COLORS["neon_cyan"], font=_FONT,
            relief="flat", bd=0, highlightthickness=0
        )
        search_entry.pack(side="left", fill="x", expand=True, padx=4, ipady=2)

        # Scrollable list area
        list_frame = tk.Frame(content, bg=COLORS["bg_main"])
        list_frame.pack(fill="both", expand=True)

        self._list_canvas = tk.Canvas(
            list_frame, bg=COLORS["bg_main"], highlightthickness=0, bd=0
        )
        scrollbar = tk.Scrollbar(
            list_frame, orient="vertical", command=self._list_canvas.yview,
            bg=COLORS["bg_elevated"], troughcolor=COLORS["bg_deep"]
        )
        self._list_inner = tk.Frame(self._list_canvas, bg=COLORS["bg_main"])
        self._list_inner.bind("<Configure>",
            lambda e: self._list_canvas.configure(scrollregion=self._list_canvas.bbox("all")))
        self._list_canvas.create_window((0, 0), window=self._list_inner, anchor="nw")
        self._list_canvas.configure(yscrollcommand=scrollbar.set)

        self._list_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Mouse wheel scrolling
        self._list_canvas.bind("<Button-4>", lambda e: self._list_canvas.yview_scroll(-3, "units"))
        self._list_canvas.bind("<Button-5>", lambda e: self._list_canvas.yview_scroll(3, "units"))

        # Bottom buttons
        btn_frame = tk.Frame(content, bg=COLORS["bg_main"])
        btn_frame.pack(fill="x", pady=(8, 0))

        self._make_button(
            btn_frame, "+ NEUER EINTRAG", "#ffffff", COLORS["neon_cyan"],
            lambda: self._build_add_screen()
        ).pack(side="left", padx=(0, 8))

        self._make_button(
            btn_frame, "🔒 SPERREN", "#ffffff", COLORS["neon_magenta"],
            self._do_lock_and_show
        ).pack(side="right")

        self._refresh_list()

    def _refresh_list(self):
        """Refresh the password list (optionally filtered by search)."""
        for w in self._list_inner.winfo_children():
            w.destroy()

        query = self._search_var.get().strip() if hasattr(self, '_search_var') else ""
        if query:
            result = password_store.search_passwords(query)
        else:
            result = password_store.list_passwords()

        if not result.get("ok"):
            tk.Label(
                self._list_inner, text=result.get("error", "Error"),
                bg=COLORS["bg_main"], fg=COLORS["error"], font=_FONT
            ).pack(pady=20)
            return

        entries = result.get("entries", [])
        if not entries:
            msg = f"No matches for '{query}'" if query else "No passwords saved"
            tk.Label(
                self._list_inner, text=msg,
                bg=COLORS["bg_main"], fg=COLORS["text_muted"], font=_FONT
            ).pack(pady=20)
            return

        for entry in entries:
            self._build_entry_row(entry)

    def _build_entry_row(self, entry: dict):
        """Build a single password entry row."""
        eid = entry["id"]
        row = tk.Frame(self._list_inner, bg=COLORS["bg_elevated"], padx=8, pady=6)
        row.pack(fill="x", pady=2)

        # Name + Username
        info = tk.Frame(row, bg=COLORS["bg_elevated"])
        info.pack(side="left", fill="x", expand=True)

        tk.Label(
            info, text=entry["name"], bg=COLORS["bg_elevated"],
            fg=COLORS["neon_cyan"], font=_FONT_BOLD, anchor="w"
        ).pack(fill="x")

        username = entry.get("username", "")
        if username:
            tk.Label(
                info, text=username, bg=COLORS["bg_elevated"],
                fg=COLORS["text_muted"], font=_FONT_SMALL, anchor="w"
            ).pack(fill="x")
        elif entry.get("url"):
            tk.Label(
                info, text=entry["url"], bg=COLORS["bg_elevated"],
                fg=COLORS["text_muted"], font=_FONT_SMALL, anchor="w"
            ).pack(fill="x")

        # Action buttons
        btns = tk.Frame(row, bg=COLORS["bg_elevated"])
        btns.pack(side="right")

        # Copy password
        copy_btn = tk.Label(
            btns, text="📋", bg=COLORS["bg_elevated"],
            fg=COLORS["text_muted"], font=("Segoe UI", 12), cursor="hand2", padx=4
        )
        copy_btn.pack(side="left")
        copy_btn.bind("<Button-1>", lambda e, i=eid: self._copy_password(i))
        copy_btn.bind("<Enter>", lambda e: copy_btn.configure(fg=COLORS["neon_cyan"]))
        copy_btn.bind("<Leave>", lambda e: copy_btn.configure(fg=COLORS["text_muted"]))

        # Auto-type
        type_btn = tk.Label(
            btns, text="⌨", bg=COLORS["bg_elevated"],
            fg=COLORS["text_muted"], font=("Segoe UI", 12), cursor="hand2", padx=4
        )
        type_btn.pack(side="left")
        type_btn.bind("<Button-1>", lambda e, i=eid: self._autotype_password(i))
        type_btn.bind("<Enter>", lambda e: type_btn.configure(fg=COLORS["success"]))
        type_btn.bind("<Leave>", lambda e: type_btn.configure(fg=COLORS["text_muted"]))

        # Delete
        del_btn = tk.Label(
            btns, text="🗑", bg=COLORS["bg_elevated"],
            fg=COLORS["text_muted"], font=("Segoe UI", 12), cursor="hand2", padx=4
        )
        del_btn.pack(side="left")
        del_btn.bind("<Button-1>", lambda e, i=eid, n=entry["name"]: self._delete_entry(i, n))
        del_btn.bind("<Enter>", lambda e: del_btn.configure(fg=COLORS["error"]))
        del_btn.bind("<Leave>", lambda e: del_btn.configure(fg=COLORS["text_muted"]))

    def _copy_password(self, entry_id: int):
        result = password_store.get_password(entry_id)
        if not result.get("ok"):
            return
        pw = result["entry"]["password"]
        try:
            self._parent.clipboard_clear()
            self._parent.clipboard_append(pw)
            # Auto-clear after 30 seconds
            self._parent.after(30000, self._clear_clipboard_safe)
            LOG.info(f"Password copied for entry #{entry_id}")
        except Exception as e:
            LOG.warning(f"Clipboard copy failed: {e}")

    def _clear_clipboard_safe(self):
        try:
            self._parent.clipboard_clear()
            self._parent.clipboard_append("")
        except Exception:
            pass

    def _autotype_password(self, entry_id: int):
        result = password_store.get_password(entry_id)
        if not result.get("ok"):
            return
        entry = result["entry"]
        if self._on_autotype:
            self._on_autotype(entry["username"], entry["password"])

    def _delete_entry(self, entry_id: int, name: str):
        """Delete with confirmation (replace row with confirm buttons)."""
        result = password_store.delete_password(entry_id)
        if result.get("ok"):
            self._refresh_list()

    def _do_lock_and_show(self):
        password_store.lock()
        self._build_lock_screen()

    # ── Screen 3: Add / Edit ──────────────────────────────────────────

    def _build_add_screen(self, edit_entry: Optional[dict] = None):
        self._clear_content()
        outer = tk.Frame(self, bg=COLORS["neon_cyan"], padx=2, pady=2)
        outer.pack(fill="both", expand=True)
        main = tk.Frame(outer, bg=COLORS["bg_main"])
        main.pack(fill="both", expand=True)

        title = "░▒▓ EINTRAG BEARBEITEN" if edit_entry else "░▒▓ NEUER EINTRAG"
        self._build_titlebar(main, title)

        content = tk.Frame(main, bg=COLORS["bg_main"], padx=24, pady=16)
        content.pack(fill="both", expand=True)

        # Fields
        fields = [
            ("Name:", "name", False),
            ("Username:", "username", False),
            ("Password:", "password", True),
            ("URL:", "url", False),
            ("Notes:", "notes", False),
        ]

        self._add_vars = {}
        for label, key, is_pw in fields:
            tk.Label(
                content, text=label, bg=COLORS["bg_main"],
                fg=COLORS["text_primary"], font=_FONT, anchor="w"
            ).pack(fill="x", pady=(8, 2))

            entry_frame = tk.Frame(content, bg=COLORS["bg_main"])
            entry_frame.pack(fill="x")

            var = tk.StringVar(value=edit_entry.get(key, "") if edit_entry else "")
            self._add_vars[key] = var

            entry = tk.Entry(
                entry_frame, textvariable=var,
                show="*" if is_pw else "",
                bg=COLORS["bg_elevated"], fg=COLORS["text_primary"],
                insertbackground=COLORS["neon_cyan"], font=_FONT,
                relief="flat", bd=0, highlightthickness=1,
                highlightcolor=COLORS["neon_cyan"], highlightbackground=COLORS["text_muted"]
            )
            entry.pack(side="left", fill="x", expand=True, ipady=5)

            if is_pw:
                # Show/hide toggle
                _visible = [False]
                toggle = tk.Label(
                    entry_frame, text="👁", bg=COLORS["bg_elevated"],
                    fg=COLORS["text_muted"], font=_FONT, cursor="hand2", padx=6
                )
                toggle.pack(side="left")

                def _toggle(e, ent=entry, vis=_visible, tog=toggle):
                    vis[0] = not vis[0]
                    ent.configure(show="" if vis[0] else "*")
                    tog.configure(fg=COLORS["neon_cyan"] if vis[0] else COLORS["text_muted"])
                toggle.bind("<Button-1>", _toggle)

                # Generate button
                gen_btn = tk.Label(
                    entry_frame, text="🎲", bg=COLORS["bg_elevated"],
                    fg=COLORS["text_muted"], font=("Segoe UI", 11), cursor="hand2", padx=6
                )
                gen_btn.pack(side="left")

                def _gen(e, v=var, ent=entry):
                    v.set(password_store.generate_password(16))
                    ent.configure(show="")  # Show generated password
                gen_btn.bind("<Button-1>", _gen)
                gen_btn.bind("<Enter>", lambda e: gen_btn.configure(fg=COLORS["neon_cyan"]))
                gen_btn.bind("<Leave>", lambda e: gen_btn.configure(fg=COLORS["text_muted"]))

        # Error label
        self._add_error = tk.Label(
            content, text="", bg=COLORS["bg_main"],
            fg=COLORS["error"], font=_FONT_SMALL
        )
        self._add_error.pack(pady=(8, 0))

        # Buttons
        btn_frame = tk.Frame(content, bg=COLORS["bg_main"])
        btn_frame.pack(fill="x", pady=(12, 0))

        self._make_button(
            btn_frame, "✓ SPEICHERN", "#ffffff", COLORS["success"],
            lambda: self._do_save(edit_entry)
        ).pack(side="left", padx=(0, 8))

        self._make_button(
            btn_frame, "✕ ABBRECHEN", "#ffffff", COLORS["text_muted"],
            self._build_list_screen
        ).pack(side="left")

    def _do_save(self, edit_entry: Optional[dict] = None):
        name = self._add_vars["name"].get().strip()
        username = self._add_vars["username"].get()
        password = self._add_vars["password"].get()
        url = self._add_vars["url"].get().strip()
        notes = self._add_vars["notes"].get().strip()

        if not name:
            self._add_error.configure(text="Name is required!")
            return
        if not username:
            self._add_error.configure(text="Username is required!")
            return
        if not password:
            self._add_error.configure(text="Password is required!")
            return

        if edit_entry:
            result = password_store.update_password(
                edit_entry["id"], name=name, username=username,
                password=password, url=url, notes=notes
            )
        else:
            result = password_store.add_password(name, username, password, url, notes)

        if result.get("ok"):
            self._build_list_screen()
        else:
            self._add_error.configure(text=result.get("error", "Error"))
