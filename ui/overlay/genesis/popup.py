import tkinter as tk
from overlay.constants import COLORS, LOG
from overlay.genesis.proposal import GenesisProposal


class GenesisNotificationPopup(tk.Toplevel):
    """Cyberpunk-styled popup for Genesis proposals."""

    def __init__(self, parent, proposals: list, on_action: callable):
        super().__init__(parent)
        self.withdraw()  # Hidden until positioned
        self.proposals = proposals
        self.on_action = on_action
        self.current_idx = 0

        self.title("GENESIS // PROPOSAL")
        self.configure(bg=COLORS["bg_main"])
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.95)
        except tk.TclError:
            pass

        self._build_ui()
        self._show_proposal(0)

        # Position next to parent — after content is built
        self.update_idletasks()
        parent.update_idletasks()
        px = parent.winfo_x()
        py = parent.winfo_y()
        pw = parent.winfo_width()
        self.geometry(f"450x380+{px + pw + 10}+{py}")
        self.deiconify()  # Show only after positioned

        # Drag support
        self._drag_x = 0
        self._drag_y = 0

    def _build_ui(self):
        # Border
        outer = tk.Frame(self, bg=COLORS["neon_cyan"], padx=2, pady=2)
        outer.pack(fill="both", expand=True)

        main = tk.Frame(outer, bg=COLORS["bg_main"])
        main.pack(fill="both", expand=True)

        # Titlebar
        titlebar = tk.Frame(main, bg=COLORS["bg_elevated"], height=32)
        titlebar.pack(fill="x")
        titlebar.pack_propagate(False)

        # Accent line
        tk.Frame(titlebar, bg=COLORS["neon_cyan"], height=2).pack(fill="x", side="bottom")

        # Title
        title_frame = tk.Frame(titlebar, bg=COLORS["bg_elevated"])
        title_frame.pack(fill="both", expand=True, side="left")

        tk.Label(
            title_frame, text="◈ GENESIS", bg=COLORS["bg_elevated"],
            fg=COLORS["neon_cyan"], font=("Consolas", 11, "bold")
        ).pack(side="left", padx=12, pady=6)

        self.counter_label = tk.Label(
            title_frame, text="", bg=COLORS["bg_elevated"],
            fg=COLORS["text_muted"], font=("Consolas", 9)
        )
        self.counter_label.pack(side="left", pady=6)

        # Close button
        close_btn = tk.Label(
            titlebar, text="✕", bg=COLORS["bg_elevated"],
            fg=COLORS["text_muted"], font=("Consolas", 12), width=3, cursor="hand2"
        )
        close_btn.pack(side="right", padx=4)
        close_btn.bind("<Button-1>", lambda e: self.destroy())
        close_btn.bind("<Enter>", lambda e: close_btn.configure(fg="#ffffff", bg=COLORS["error"]))
        close_btn.bind("<Leave>", lambda e: close_btn.configure(fg=COLORS["text_muted"], bg=COLORS["bg_elevated"]))

        # Drag bindings
        for w in [titlebar, title_frame]:
            w.bind("<Button-1>", self._start_drag)
            w.bind("<B1-Motion>", self._on_drag)

        # Content
        content = tk.Frame(main, bg=COLORS["bg_main"], padx=16, pady=12)
        content.pack(fill="both", expand=True)

        # Category + Confidence
        info_frame = tk.Frame(content, bg=COLORS["bg_main"])
        info_frame.pack(fill="x", pady=(0, 10))

        self.category_label = tk.Label(
            info_frame, text="", bg=COLORS["bg_elevated"],
            fg=COLORS["neon_green"], font=("Consolas", 10, "bold"), padx=8, pady=2
        )
        self.category_label.pack(side="left")

        self.confidence_label = tk.Label(
            info_frame, text="", bg=COLORS["bg_main"],
            fg=COLORS["text_muted"], font=("Consolas", 9)
        )
        self.confidence_label.pack(side="right")

        # Description
        desc_frame = tk.Frame(content, bg=COLORS["bg_elevated"], padx=12, pady=10)
        desc_frame.pack(fill="both", expand=True, pady=(0, 12))

        self.desc_text = tk.Text(
            desc_frame, bg=COLORS["bg_elevated"], fg=COLORS["text_primary"],
            font=("Segoe UI", 10), wrap="word", height=8, borderwidth=0,
            highlightthickness=0, state="disabled"
        )
        self.desc_text.pack(fill="both", expand=True)

        # Risk indicator
        risk_frame = tk.Frame(content, bg=COLORS["bg_main"])
        risk_frame.pack(fill="x", pady=(0, 12))

        tk.Label(
            risk_frame, text="RISK:", bg=COLORS["bg_main"],
            fg=COLORS["text_muted"], font=("Consolas", 9)
        ).pack(side="left")

        self.risk_bar = tk.Canvas(risk_frame, width=100, height=8, bg=COLORS["bg_elevated"], highlightthickness=0)
        self.risk_bar.pack(side="left", padx=8)

        self.risk_label = tk.Label(
            risk_frame, text="", bg=COLORS["bg_main"],
            fg=COLORS["text_muted"], font=("Consolas", 9)
        )
        self.risk_label.pack(side="left")

        # Buttons
        btn_frame = tk.Frame(content, bg=COLORS["bg_main"])
        btn_frame.pack(fill="x")

        # Navigation
        nav_frame = tk.Frame(btn_frame, bg=COLORS["bg_main"])
        nav_frame.pack(side="left")

        self.prev_btn = tk.Label(
            nav_frame, text="◄ PREV", bg=COLORS["bg_elevated"],
            fg=COLORS["text_muted"], font=("Consolas", 9), padx=10, pady=6, cursor="hand2"
        )
        self.prev_btn.pack(side="left", padx=(0, 4))
        self.prev_btn.bind("<Button-1>", lambda e: self._navigate(-1))

        self.next_btn = tk.Label(
            nav_frame, text="NEXT ►", bg=COLORS["bg_elevated"],
            fg=COLORS["text_muted"], font=("Consolas", 9), padx=10, pady=6, cursor="hand2"
        )
        self.next_btn.pack(side="left")
        self.next_btn.bind("<Button-1>", lambda e: self._navigate(1))

        # Action buttons
        action_frame = tk.Frame(btn_frame, bg=COLORS["bg_main"])
        action_frame.pack(side="right")

        reject_btn = tk.Label(
            action_frame, text="✕ REJECT", bg=COLORS["error"],
            fg="#ffffff", font=("Consolas", 10, "bold"), padx=12, pady=6, cursor="hand2"
        )
        reject_btn.pack(side="left", padx=(0, 8))
        reject_btn.bind("<Button-1>", lambda e: self._do_action("reject"))

        approve_btn = tk.Label(
            action_frame, text="✓ APPROVE", bg=COLORS["success"],
            fg="#ffffff", font=("Consolas", 10, "bold"), padx=12, pady=6, cursor="hand2"
        )
        approve_btn.pack(side="left")
        approve_btn.bind("<Button-1>", lambda e: self._do_action("approve"))

    def _start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag(self, event):
        x = self.winfo_x() + (event.x - self._drag_x)
        y = self.winfo_y() + (event.y - self._drag_y)
        self.geometry(f"+{x}+{y}")

    def _show_proposal(self, idx):
        if not self.proposals:
            return
        idx = max(0, min(idx, len(self.proposals) - 1))
        self.current_idx = idx
        p = self.proposals[idx]

        # Update counter
        self.counter_label.configure(text=f"// {idx + 1}/{len(self.proposals)} PENDING")

        # Category
        self.category_label.configure(text=p.category.upper())

        # Confidence
        self.confidence_label.configure(text=f"CONFIDENCE: {p.confidence:.0%}")

        # Description
        self.desc_text.configure(state="normal")
        self.desc_text.delete("1.0", "end")
        self.desc_text.insert("1.0", p.description)
        self.desc_text.configure(state="disabled")

        # Risk bar
        self.risk_bar.delete("all")
        risk_width = int(p.risk * 100)
        risk_color = COLORS["success"] if p.risk < 0.3 else (COLORS["warning"] if p.risk < 0.6 else COLORS["error"])
        self.risk_bar.create_rectangle(0, 0, risk_width, 8, fill=risk_color, outline="")
        self.risk_label.configure(text=f"{p.risk:.0%}", fg=risk_color)

        # Nav buttons
        self.prev_btn.configure(fg=COLORS["text_primary"] if idx > 0 else COLORS["text_muted"])
        self.next_btn.configure(fg=COLORS["text_primary"] if idx < len(self.proposals) - 1 else COLORS["text_muted"])

    def _navigate(self, delta):
        new_idx = self.current_idx + delta
        if 0 <= new_idx < len(self.proposals):
            self._show_proposal(new_idx)

    def _do_action(self, action):
        if self.proposals:
            p = self.proposals[self.current_idx]
            self.on_action(p.id, action)
            # Remove from list
            self.proposals.pop(self.current_idx)
            if self.proposals:
                self._show_proposal(min(self.current_idx, len(self.proposals) - 1))
            else:
                self.destroy()
