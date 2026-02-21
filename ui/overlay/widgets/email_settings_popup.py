"""Email Settings Popup — Configure mail provider and account.

Cyberpunk-styled Toplevel for /mailconfig slash command.
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

_POPUP_W = 480
_POPUP_H = 420

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


class EmailSettingsPopup(tk.Toplevel):
    """Cyberpunk email settings popup."""

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
        self._config = current_config or {"account": "auto", "provider": "auto"}
        self._on_save = on_save
        self._on_destroy = on_destroy

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

        # Position left of parent overlay
        self.update_idletasks()
        parent.update_idletasks()
        px = parent.winfo_x()
        py = parent.winfo_y()
        screen_w = self.winfo_screenwidth()
        x = px - _POPUP_W - 8
        if x < 0:
            x = px + parent.winfo_width() + 8
        if x + _POPUP_W > screen_w:
            x = max(0, screen_w - _POPUP_W)
        y = max(get_workarea_y(), py)
        self.geometry(f"{_POPUP_W}x{_POPUP_H}+{x}+{y}")

        self.bind("<Escape>", lambda e: self.destroy())

        self._build_ui()
        self.focus_force()

    def destroy(self):
        if self._on_destroy:
            try:
                self._on_destroy()
            except Exception:
                pass
        super().destroy()

    def _build_ui(self):
        outer = tk.Frame(self, bg=COLORS["neon_cyan"], padx=2, pady=2)
        outer.pack(fill="both", expand=True)
        main = tk.Frame(outer, bg=COLORS["bg_main"])
        main.pack(fill="both", expand=True)

        # Titlebar
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

        # ── Account Selection ──
        section1 = tk.Frame(main, bg=COLORS["bg_elevated"], padx=16, pady=12)
        section1.pack(fill="x")

        tk.Label(
            section1, text="MAIL ACCOUNT",
            bg=COLORS["bg_elevated"], fg=COLORS["neon_cyan"],
            font=_FONT_BOLD
        ).pack(anchor="w")

        tk.Label(
            section1, text="Thunderbird IMAP accounts detected on this system:",
            bg=COLORS["bg_elevated"], fg=COLORS["text_muted"],
            font=_FONT_SMALL
        ).pack(anchor="w", pady=(2, 8))

        self._account_var = tk.StringVar(value=self._config.get("account", "auto"))

        # Auto option
        auto_frame = tk.Frame(section1, bg=COLORS["bg_elevated"])
        auto_frame.pack(fill="x", pady=1)
        tk.Radiobutton(
            auto_frame, text="Auto (Thunderbird Default)",
            variable=self._account_var, value="auto",
            bg=COLORS["bg_elevated"], fg=COLORS["text_primary"],
            selectcolor=COLORS["bg_main"], activebackground=COLORS["bg_elevated"],
            activeforeground=COLORS["neon_cyan"], font=_FONT,
            highlightthickness=0, command=self._on_account_change,
        ).pack(anchor="w")

        # Detected accounts
        if self._accounts:
            for acc in self._accounts:
                server = acc.get("server", "?")
                provider = acc.get("provider", "generic")
                label = f"{server}  ({provider})"

                acc_frame = tk.Frame(section1, bg=COLORS["bg_elevated"])
                acc_frame.pack(fill="x", pady=1)
                tk.Radiobutton(
                    acc_frame, text=label,
                    variable=self._account_var, value=server,
                    bg=COLORS["bg_elevated"], fg=COLORS["text_primary"],
                    selectcolor=COLORS["bg_main"], activebackground=COLORS["bg_elevated"],
                    activeforeground=COLORS["neon_cyan"], font=_FONT,
                    highlightthickness=0, command=self._on_account_change,
                ).pack(anchor="w")
        else:
            tk.Label(
                section1, text="No IMAP accounts found in Thunderbird.",
                bg=COLORS["bg_elevated"], fg=COLORS["error"], font=_FONT_SMALL
            ).pack(anchor="w", pady=4)

        # Separator
        tk.Frame(main, bg=COLORS["neon_cyan"], height=1).pack(fill="x")

        # ── Provider Override ──
        section2 = tk.Frame(main, bg=COLORS["bg_elevated"], padx=16, pady=12)
        section2.pack(fill="x")

        tk.Label(
            section2, text="PROVIDER TYPE",
            bg=COLORS["bg_elevated"], fg=COLORS["neon_cyan"],
            font=_FONT_BOLD
        ).pack(anchor="w")

        tk.Label(
            section2, text="Override folder mapping (spam, sent, drafts, trash):",
            bg=COLORS["bg_elevated"], fg=COLORS["text_muted"],
            font=_FONT_SMALL
        ).pack(anchor="w", pady=(2, 8))

        self._provider_var = tk.StringVar(value=self._config.get("provider", "auto"))

        # Provider grid (2 columns)
        grid = tk.Frame(section2, bg=COLORS["bg_elevated"])
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

        # Separator
        tk.Frame(main, bg=COLORS["neon_cyan"], height=1).pack(fill="x")

        # ── Action buttons ──
        actions = tk.Frame(main, bg=COLORS["bg_elevated"], padx=16, pady=10)
        actions.pack(fill="x")

        save_btn = tk.Label(
            actions, text=" SAVE ", bg="#006400", fg="#FFFFFF",
            font=_FONT_BOLD, padx=12, pady=4, cursor="hand2"
        )
        save_btn.pack(side="left", padx=(0, 8))
        save_btn.bind("<Button-1>", lambda e: self._on_save_click())
        save_btn.bind("<Enter>", lambda e: save_btn.configure(bg="#007700"))
        save_btn.bind("<Leave>", lambda e: save_btn.configure(bg="#006400"))

        close_btn2 = tk.Label(
            actions, text=" CLOSE ",
            bg=COLORS.get("neon_cyan", "#00fff9"), fg=COLORS["bg_main"],
            font=_FONT_BOLD, padx=12, pady=4, cursor="hand2"
        )
        close_btn2.pack(side="left")
        close_btn2.bind("<Button-1>", lambda e: self.destroy())

        # Status
        self._status_label = tk.Label(
            main, text="", bg=COLORS["bg_main"], fg=COLORS["text_muted"],
            font=_FONT_SMALL, anchor="w", padx=12
        )
        self._status_label.pack(fill="x")

    def _on_account_change(self):
        """Auto-set provider when account changes."""
        account = self._account_var.get()
        if account == "auto":
            self._provider_var.set("auto")
        else:
            # Find the detected provider for this account
            for acc in self._accounts:
                if acc.get("server") == account:
                    detected = acc.get("provider", "generic")
                    self._provider_var.set(detected)
                    break

    def _on_save_click(self):
        config = {
            "account": self._account_var.get(),
            "provider": self._provider_var.get(),
        }
        if self._on_save:
            self._on_save(config)
        self._status_label.configure(text="Settings saved!", fg=COLORS["neon_green"])
        self.after(1500, self.destroy)

    def _start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag(self, event):
        x = self.winfo_x() + (event.x - self._drag_x)
        y = self.winfo_y() + (event.y - self._drag_y)
        y = max(get_workarea_y(), y)
        self.geometry(f"+{x}+{y}")
