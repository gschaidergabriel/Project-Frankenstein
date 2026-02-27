"""Email Settings Popup — Configure mail provider and account.

Cyberpunk-styled Toplevel for /mailconfig slash command.
Supports Thunderbird auto-detect AND manual IMAP/SMTP credentials.
"""
from __future__ import annotations

import tkinter as tk
from typing import Optional, Callable, List, Dict

from overlay.constants import COLORS, LOG
from overlay.bsn.constants import get_workarea_y

_FONT = ("Consolas", 10)
_FONT_BOLD = ("Consolas", 10, "bold")
_FONT_TITLE = ("Consolas", 11, "bold")
_FONT_SMALL = ("Consolas", 9)

_POPUP_W = 500
_POPUP_H = 660  # fixed height for both modes

_PROVIDERS = [
    ("auto", "Auto-Detect"),
    ("gmail", "Gmail"),
    ("outlook", "Outlook / Hotmail"),
    ("yahoo", "Yahoo Mail"),
    ("icloud", "iCloud Mail"),
    ("gmx", "GMX"),
    ("webde", "Web.de"),
    ("tonline", "T-Online"),
    ("proton", "ProtonMail"),
    ("fastmail", "Fastmail"),
    ("generic", "Generic IMAP"),
]

# Server keyword → provider for auto-detection in manual mode
_SERVER_PROVIDERS = {
    "gmail": "gmail", "googlemail": "gmail",
    "outlook": "outlook", "office365": "outlook",
    "hotmail": "outlook", "live.com": "outlook",
    "yahoo": "yahoo",
    "icloud": "icloud", "me.com": "icloud",
    "gmx": "gmx",
    "web.de": "webde",
    "t-online": "tonline", "telekom": "tonline",
    "proton": "proton",
    "fastmail": "fastmail",
}


class EmailSettingsPopup(tk.Toplevel):
    """Cyberpunk email settings popup with Thunderbird + Manual modes."""

    def __init__(
        self,
        parent,
        accounts: List[Dict[str, str]] = None,
        current_config: Dict = None,
        on_save: Optional[Callable] = None,
        on_destroy: Optional[Callable] = None,
    ):
        super().__init__(parent)
        self._parent = parent
        self._accounts = accounts or []
        self._config = current_config or {"mode": "thunderbird", "account": "auto", "provider": "auto"}
        self._on_save = on_save
        self._on_destroy = on_destroy

        self.withdraw()  # Hidden until positioned
        self.title("FRANK MAIL SETTINGS")
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

        # Position LEFT of parent overlay
        self.update_idletasks()
        parent.update_idletasks()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        screen_w = self.winfo_screenwidth()

        x = px - _POPUP_W - 8
        if x < 0:
            x = px + pw + 8
        if x + _POPUP_W > screen_w:
            x = max(0, (px - _POPUP_W) // 2)
        y = max(get_workarea_y(), py)
        self.geometry(f"{_POPUP_W}x{_POPUP_H}+{x}+{y}")

        self.bind("<Escape>", lambda e: self.destroy())

        self._build_ui()
        self.deiconify()  # Show only after positioned
        self.focus_force()

    def destroy(self):
        if self._on_destroy:
            try:
                self._on_destroy()
            except Exception:
                pass
        super().destroy()

    # ── UI Construction ──────────────────────────────────────────────

    def _build_ui(self):
        outer = tk.Frame(self, bg=COLORS["neon_cyan"], padx=2, pady=2)
        outer.pack(fill="both", expand=True)
        main = tk.Frame(outer, bg=COLORS["bg_main"])
        main.pack(fill="both", expand=True)

        # ── Titlebar ──
        titlebar = tk.Frame(main, bg=COLORS["bg_elevated"], height=32)
        titlebar.pack(fill="x")
        titlebar.pack_propagate(False)
        tk.Frame(titlebar, bg=COLORS["neon_cyan"], height=2).pack(fill="x", side="bottom")

        title_frame = tk.Frame(titlebar, bg=COLORS["bg_elevated"])
        title_frame.pack(fill="both", expand=True, side="left")
        tk.Label(
            title_frame, text="MAIL // SETTINGS",
            bg=COLORS["bg_elevated"], fg=COLORS["neon_cyan"],
            font=_FONT_TITLE
        ).pack(side="left", padx=12, pady=6)

        close_btn = tk.Label(
            titlebar, text="\u2715", bg=COLORS["bg_elevated"],
            fg=COLORS["text_muted"], font=("Consolas", 12), width=3, cursor="hand2"
        )
        close_btn.pack(side="right", padx=4)
        close_btn.bind("<Button-1>", lambda e: self.destroy())

        for w in [titlebar, title_frame]:
            w.bind("<Button-1>", self._start_drag)
            w.bind("<B1-Motion>", self._on_drag)

        # ── Connection Mode ──
        mode_section = tk.Frame(main, bg=COLORS["bg_elevated"], padx=16, pady=8)
        mode_section.pack(fill="x")

        tk.Label(
            mode_section, text="CONNECTION MODE",
            bg=COLORS["bg_elevated"], fg=COLORS["neon_cyan"],
            font=_FONT_BOLD
        ).pack(anchor="w")

        self._mode_var = tk.StringVar(value=self._config.get("mode", "thunderbird"))

        mode_row = tk.Frame(mode_section, bg=COLORS["bg_elevated"])
        mode_row.pack(fill="x", pady=(4, 0))

        tk.Radiobutton(
            mode_row, text="Thunderbird (auto)",
            variable=self._mode_var, value="thunderbird",
            bg=COLORS["bg_elevated"], fg=COLORS["text_primary"],
            selectcolor=COLORS["bg_main"], activebackground=COLORS["bg_elevated"],
            activeforeground=COLORS["neon_cyan"], font=_FONT,
            highlightthickness=0, command=self._on_mode_change,
        ).pack(side="left", padx=(0, 16))

        tk.Radiobutton(
            mode_row, text="Manual IMAP/SMTP",
            variable=self._mode_var, value="manual",
            bg=COLORS["bg_elevated"], fg=COLORS["text_primary"],
            selectcolor=COLORS["bg_main"], activebackground=COLORS["bg_elevated"],
            activeforeground=COLORS["neon_cyan"], font=_FONT,
            highlightthickness=0, command=self._on_mode_change,
        ).pack(side="left")

        # Separator
        tk.Frame(main, bg=COLORS["neon_cyan"], height=1).pack(fill="x")

        # ── Mode content area (fixed container) ──
        self._content = tk.Frame(main, bg=COLORS["bg_elevated"])
        self._content.pack(fill="both", expand=True)

        # Build both sections inside the content area (only one visible at a time)
        self._tb_section = tk.Frame(self._content, bg=COLORS["bg_elevated"], padx=16, pady=8)
        self._build_thunderbird_section()

        self._manual_section = tk.Frame(self._content, bg=COLORS["bg_elevated"], padx=16, pady=8)
        self._build_manual_section()

        # ── Provider Override (below content, always shown) ──
        tk.Frame(main, bg=COLORS["neon_cyan"], height=1).pack(fill="x")

        provider_section = tk.Frame(main, bg=COLORS["bg_elevated"], padx=16, pady=8)
        provider_section.pack(fill="x")
        self._build_provider_section(provider_section)

        # ── Signature ──
        tk.Frame(main, bg=COLORS["neon_cyan"], height=1).pack(fill="x")

        sig_section = tk.Frame(main, bg=COLORS["bg_elevated"], padx=16, pady=8)
        sig_section.pack(fill="x")
        self._build_signature_section(sig_section)

        # ── Actions (always shown) ──
        tk.Frame(main, bg=COLORS["neon_cyan"], height=1).pack(fill="x")

        actions = tk.Frame(main, bg=COLORS["bg_elevated"], padx=16, pady=8)
        actions.pack(fill="x")
        self._build_actions(actions)

        self._status_label = tk.Label(
            main, text="", bg=COLORS["bg_main"], fg=COLORS["text_muted"],
            font=_FONT_SMALL, anchor="w", padx=12
        )
        self._status_label.pack(fill="x")

        # Show correct section (no geometry changes here!)
        self._on_mode_change()

    def _build_thunderbird_section(self):
        """Build the Thunderbird auto-detect account list."""
        s = self._tb_section

        tk.Label(
            s, text="THUNDERBIRD ACCOUNT",
            bg=COLORS["bg_elevated"], fg=COLORS["neon_cyan"],
            font=_FONT_BOLD
        ).pack(anchor="w")

        tk.Label(
            s, text="Detected IMAP accounts on this system:",
            bg=COLORS["bg_elevated"], fg=COLORS["text_muted"],
            font=_FONT_SMALL
        ).pack(anchor="w", pady=(2, 6))

        self._account_var = tk.StringVar(value=self._config.get("account", "auto"))

        tk.Radiobutton(
            s, text="Auto (Thunderbird Default)",
            variable=self._account_var, value="auto",
            bg=COLORS["bg_elevated"], fg=COLORS["text_primary"],
            selectcolor=COLORS["bg_main"], activebackground=COLORS["bg_elevated"],
            activeforeground=COLORS["neon_cyan"], font=_FONT,
            highlightthickness=0, command=self._on_account_change,
        ).pack(anchor="w", pady=1)

        if self._accounts:
            for acc in self._accounts:
                server = acc.get("server", "?")
                provider = acc.get("provider", "generic")
                label = f"{server}  ({provider})"
                tk.Radiobutton(
                    s, text=label,
                    variable=self._account_var, value=server,
                    bg=COLORS["bg_elevated"], fg=COLORS["text_primary"],
                    selectcolor=COLORS["bg_main"], activebackground=COLORS["bg_elevated"],
                    activeforeground=COLORS["neon_cyan"], font=_FONT,
                    highlightthickness=0, command=self._on_account_change,
                ).pack(anchor="w", pady=1)
        else:
            tk.Label(
                s, text="No IMAP accounts found in Thunderbird.",
                bg=COLORS["bg_elevated"], fg=COLORS["error"], font=_FONT_SMALL
            ).pack(anchor="w", pady=4)

    def _build_manual_section(self):
        """Build the manual IMAP/SMTP credential fields."""
        s = self._manual_section

        # ── Server fields ──
        tk.Label(
            s, text="IMAP / SMTP SERVER",
            bg=COLORS["bg_elevated"], fg=COLORS["neon_cyan"],
            font=_FONT_BOLD
        ).pack(anchor="w")

        # IMAP row
        imap_row = tk.Frame(s, bg=COLORS["bg_elevated"])
        imap_row.pack(fill="x", pady=(6, 2))
        tk.Label(
            imap_row, text="IMAP:", bg=COLORS["bg_elevated"],
            fg=COLORS["text_muted"], font=_FONT, width=6, anchor="w"
        ).pack(side="left")
        self._imap_host = self._make_entry(imap_row, width=28)
        self._imap_host.pack(side="left", padx=(0, 4))
        tk.Label(
            imap_row, text=":", bg=COLORS["bg_elevated"],
            fg=COLORS["text_muted"], font=_FONT
        ).pack(side="left")
        self._imap_port = self._make_entry(imap_row, width=5)
        self._imap_port.pack(side="left", padx=(2, 0))

        # SMTP row
        smtp_row = tk.Frame(s, bg=COLORS["bg_elevated"])
        smtp_row.pack(fill="x", pady=2)
        tk.Label(
            smtp_row, text="SMTP:", bg=COLORS["bg_elevated"],
            fg=COLORS["text_muted"], font=_FONT, width=6, anchor="w"
        ).pack(side="left")
        self._smtp_host = self._make_entry(smtp_row, width=28)
        self._smtp_host.pack(side="left", padx=(0, 4))
        tk.Label(
            smtp_row, text=":", bg=COLORS["bg_elevated"],
            fg=COLORS["text_muted"], font=_FONT
        ).pack(side="left")
        self._smtp_port = self._make_entry(smtp_row, width=5)
        self._smtp_port.pack(side="left", padx=(2, 0))

        # Separator
        tk.Frame(s, bg=COLORS["bg_main"], height=4).pack(fill="x", pady=4)

        # ── Credentials ──
        tk.Label(
            s, text="CREDENTIALS",
            bg=COLORS["bg_elevated"], fg=COLORS["neon_cyan"],
            font=_FONT_BOLD
        ).pack(anchor="w")

        # Email row
        user_row = tk.Frame(s, bg=COLORS["bg_elevated"])
        user_row.pack(fill="x", pady=(6, 2))
        tk.Label(
            user_row, text="Email:", bg=COLORS["bg_elevated"],
            fg=COLORS["text_muted"], font=_FONT, width=6, anchor="w"
        ).pack(side="left")
        self._username = self._make_entry(user_row, width=36)
        self._username.pack(side="left")

        # Password row
        pw_row = tk.Frame(s, bg=COLORS["bg_elevated"])
        pw_row.pack(fill="x", pady=2)
        tk.Label(
            pw_row, text="Pass:", bg=COLORS["bg_elevated"],
            fg=COLORS["text_muted"], font=_FONT, width=6, anchor="w"
        ).pack(side="left")
        self._password = self._make_entry(pw_row, width=30, show="*")
        self._password.pack(side="left", padx=(0, 4))

        self._pw_shown = False
        self._pw_toggle = tk.Label(
            pw_row, text="SHOW", bg=COLORS["bg_main"],
            fg=COLORS["text_muted"], font=_FONT_SMALL, padx=6, cursor="hand2"
        )
        self._pw_toggle.pack(side="left")
        self._pw_toggle.bind("<Button-1>", self._toggle_password)

        # Hint
        tk.Label(
            s, text="Password is stored encrypted on this machine.",
            bg=COLORS["bg_elevated"], fg=COLORS["text_muted"],
            font=("Consolas", 8)
        ).pack(anchor="w", pady=(4, 0))

        # Pre-fill from config
        self._imap_host.insert(0, self._config.get("imap_host", ""))
        self._imap_port.insert(0, str(self._config.get("imap_port", "993")))
        self._smtp_host.insert(0, self._config.get("smtp_host", ""))
        self._smtp_port.insert(0, str(self._config.get("smtp_port", "587")))
        self._username.insert(0, self._config.get("username", ""))
        if self._config.get("password"):
            self._password.insert(0, self._config["password"])

        # Auto-detect provider from IMAP host
        self._imap_host.bind("<KeyRelease>", self._on_imap_host_change)

    def _build_provider_section(self, parent):
        """Build the provider override selector."""
        tk.Label(
            parent, text="PROVIDER TYPE",
            bg=COLORS["bg_elevated"], fg=COLORS["neon_cyan"],
            font=_FONT_BOLD
        ).pack(anchor="w")

        tk.Label(
            parent, text="Folder mapping (spam, sent, drafts, trash):",
            bg=COLORS["bg_elevated"], fg=COLORS["text_muted"],
            font=_FONT_SMALL
        ).pack(anchor="w", pady=(2, 6))

        self._provider_var = tk.StringVar(value=self._config.get("provider", "auto"))

        grid = tk.Frame(parent, bg=COLORS["bg_elevated"])
        grid.pack(fill="x")

        for i, (value, label) in enumerate(_PROVIDERS):
            col = i % 2
            row = i // 2
            tk.Radiobutton(
                grid, text=label,
                variable=self._provider_var, value=value,
                bg=COLORS["bg_elevated"], fg=COLORS["text_primary"],
                selectcolor=COLORS["bg_main"], activebackground=COLORS["bg_elevated"],
                activeforeground=COLORS["neon_cyan"], font=_FONT_SMALL,
                highlightthickness=0,
            ).grid(row=row, column=col, sticky="w", padx=(0, 20))

    def _build_signature_section(self, parent):
        """Build the default email signature editor."""
        tk.Label(
            parent, text="DEFAULT SIGNATURE",
            bg=COLORS["bg_elevated"], fg=COLORS["neon_cyan"],
            font=_FONT_BOLD
        ).pack(anchor="w")

        tk.Label(
            parent, text="Appended to every outgoing email:",
            bg=COLORS["bg_elevated"], fg=COLORS["text_muted"],
            font=_FONT_SMALL
        ).pack(anchor="w", pady=(2, 4))

        self._signature_text = tk.Text(
            parent, bg=COLORS["bg_deep"], fg=COLORS["text_primary"],
            insertbackground=COLORS["neon_cyan"], font=_FONT,
            width=50, height=3, wrap="word", relief="flat", bd=0,
            highlightbackground=COLORS["text_muted"],
            highlightcolor=COLORS["neon_cyan"],
            highlightthickness=1,
        )
        self._signature_text.pack(fill="x")

        # Pre-fill from config
        sig = self._config.get("signature", "")
        if sig:
            self._signature_text.insert("1.0", sig)

    def _build_actions(self, parent):
        """Build save/test/close action buttons."""
        save_btn = tk.Label(
            parent, text=" SAVE ", bg="#006400", fg="#FFFFFF",
            font=_FONT_BOLD, padx=12, pady=4, cursor="hand2"
        )
        save_btn.pack(side="left", padx=(0, 8))
        save_btn.bind("<Button-1>", lambda e: self._on_save_click())
        save_btn.bind("<Enter>", lambda e: save_btn.configure(bg="#007700"))
        save_btn.bind("<Leave>", lambda e: save_btn.configure(bg="#006400"))

        test_btn = tk.Label(
            parent, text=" TEST ", bg="#1a1a3e", fg="#FFD700",
            font=_FONT_BOLD, padx=12, pady=4, cursor="hand2"
        )
        test_btn.pack(side="left", padx=(0, 8))
        test_btn.bind("<Button-1>", lambda e: self._on_test_click())
        test_btn.bind("<Enter>", lambda e: test_btn.configure(bg="#282850"))
        test_btn.bind("<Leave>", lambda e: test_btn.configure(bg="#1a1a3e"))

        close_btn = tk.Label(
            parent, text=" CLOSE ",
            bg=COLORS.get("neon_cyan", "#00fff9"), fg=COLORS["bg_main"],
            font=_FONT_BOLD, padx=12, pady=4, cursor="hand2"
        )
        close_btn.pack(side="left")
        close_btn.bind("<Button-1>", lambda e: self.destroy())

    # ── Helpers ──────────────────────────────────────────────────────

    def _make_entry(self, parent, width=20, show=None):
        """Create a styled entry field."""
        entry = tk.Entry(
            parent, bg=COLORS["bg_deep"], fg=COLORS["text_primary"],
            insertbackground=COLORS["neon_cyan"], font=_FONT,
            width=width, relief="flat", bd=0,
            highlightbackground=COLORS["text_muted"],
            highlightcolor=COLORS["neon_cyan"],
            highlightthickness=1,
        )
        if show:
            entry.configure(show=show)
        return entry

    def _toggle_password(self, event=None):
        """Toggle password visibility."""
        self._pw_shown = not self._pw_shown
        self._password.configure(show="" if self._pw_shown else "*")
        self._pw_toggle.configure(text="HIDE" if self._pw_shown else "SHOW")

    # ── Mode switching (simple show/hide, no geometry changes) ──────

    def _on_mode_change(self):
        """Show/hide sections based on connection mode."""
        mode = self._mode_var.get()

        # Hide both, show the right one
        self._tb_section.pack_forget()
        self._manual_section.pack_forget()

        if mode == "thunderbird":
            self._tb_section.pack(fill="both", expand=True)
        else:
            self._manual_section.pack(fill="both", expand=True)

    # ── Auto-detection ──────────────────────────────────────────────

    def _on_imap_host_change(self, event=None):
        """Auto-detect provider from IMAP host input."""
        host = self._imap_host.get().lower().strip()
        for keyword, provider in _SERVER_PROVIDERS.items():
            if keyword in host:
                self._provider_var.set(provider)
                return
        if host:
            self._provider_var.set("generic")

    def _on_account_change(self):
        """Auto-set provider when Thunderbird account changes."""
        account = self._account_var.get()
        if account == "auto":
            self._provider_var.set("auto")
        else:
            for acc in self._accounts:
                if acc.get("server") == account:
                    detected = acc.get("provider", "generic")
                    self._provider_var.set(detected)
                    break

    # ── Save ──────────────────────────────────────────────────────────

    def _on_save_click(self):
        mode = self._mode_var.get()
        sig = self._signature_text.get("1.0", "end-1c").strip()
        config = {
            "mode": mode,
            "provider": self._provider_var.get(),
            "signature": sig,
        }

        if mode == "thunderbird":
            config["account"] = self._account_var.get()
        else:
            # Validate required fields
            imap_host = self._imap_host.get().strip()
            username = self._username.get().strip()
            password = self._password.get().strip()

            if not imap_host:
                self._status_label.configure(text="IMAP server is required!", fg=COLORS["error"])
                return
            if not username:
                self._status_label.configure(text="Email address is required!", fg=COLORS["error"])
                return
            if not password:
                self._status_label.configure(text="Password is required!", fg=COLORS["error"])
                return

            config["imap_host"] = imap_host
            config["imap_port"] = self._imap_port.get().strip() or "993"
            smtp_host = self._smtp_host.get().strip()
            config["smtp_host"] = smtp_host or imap_host.replace("imap.", "smtp.")
            config["smtp_port"] = self._smtp_port.get().strip() or "587"
            config["username"] = username
            config["password"] = password
            config["account"] = "manual"

        if self._on_save:
            self._on_save(config)

        self._status_label.configure(text="Settings saved!", fg=COLORS["neon_green"])
        self.after(1500, self.destroy)

    # ── IMAP Test ────────────────────────────────────────────────────

    def _on_test_click(self):
        """Test IMAP connection in a background thread."""
        self._status_label.configure(text="Testing connection...", fg=COLORS["neon_cyan"])

        import threading

        mode = self._mode_var.get()

        def _test():
            try:
                from tools.email_reader import test_imap_connection

                if mode == "manual":
                    result = test_imap_connection(
                        host=self._imap_host.get().strip(),
                        port=int(self._imap_port.get().strip() or "993"),
                        user=self._username.get().strip(),
                        password=self._password.get().strip(),
                    )
                else:
                    result = test_imap_connection()

                def _show():
                    try:
                        if result.get("ok"):
                            folders = result.get("folders", [])
                            msg = result["message"]
                            if folders:
                                msg += f" | {len(folders)} folders found"
                            self._status_label.configure(text=msg, fg=COLORS["neon_green"])
                        else:
                            self._status_label.configure(
                                text=result.get("error", "Test failed"), fg=COLORS["error"])
                    except Exception:
                        pass

                self.after(0, _show)
            except Exception as e:
                try:
                    self.after(0, lambda: self._status_label.configure(
                        text=f"Test error: {e}", fg=COLORS["error"]))
                except Exception:
                    pass

        threading.Thread(target=_test, daemon=True).start()

    # ── Drag ──────────────────────────────────────────────────────────

    def _start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag(self, event):
        x = self.winfo_x() + (event.x - self._drag_x)
        y = self.winfo_y() + (event.y - self._drag_y)
        y = max(get_workarea_y(), y)
        self.geometry(f"+{x}+{y}")
