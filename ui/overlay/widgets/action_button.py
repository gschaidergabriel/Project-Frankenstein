"""ActionButton -- minimal clickable label for message inline actions.

Used under Frank's message bubbles for Copy, Retry, Speak etc.
"""

import tkinter as tk
from overlay.constants import COLORS


class ActionButton(tk.Label):
    """Compact clickable action label with hover effect."""

    def __init__(self, parent, text, command, icon="", **kwargs):
        display = f"{icon} {text}" if icon else text
        super().__init__(
            parent,
            text=display,
            fg=COLORS["text_muted"],
            bg=parent.cget("bg"),
            font=("Consolas", 8),
            cursor="hand2",
            padx=6,
            pady=1,
            **kwargs,
        )
        self._command = command
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_click(self, event):
        self._command()

    def _on_enter(self, event):
        self.configure(fg=COLORS["neon_cyan"])

    def _on_leave(self, event):
        self.configure(fg=COLORS["text_muted"])
