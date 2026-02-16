"""AgentProgressBar -- live progress display for agentic execution.

Shows step-by-step progress with status icons and a cancel button.
Embeds into the chat message stream.
"""

import tkinter as tk
from overlay.constants import COLORS


class AgentProgressBar(tk.Frame):
    """Agentic execution progress bar widget."""

    def __init__(self, parent, on_cancel=None):
        super().__init__(parent, bg=COLORS["bg_chat"])

        self._steps = []  # list of (tool, description, status)
        self._on_cancel = on_cancel

        # Container
        container = tk.Frame(self, bg=COLORS["bg_chat"])
        container.pack(fill="x", padx=8, pady=4)

        # Bubble frame
        bubble = tk.Frame(container, bg=COLORS["bg_ai_msg"])
        bubble.pack(anchor="w", fill="x")

        # Left accent stripe
        stripe = tk.Frame(bubble, bg=COLORS["neon_yellow"], width=3)
        stripe.pack(side="left", fill="y")

        # Content
        self._content = tk.Frame(bubble, bg=COLORS["bg_ai_msg"], padx=12, pady=8)
        self._content.pack(side="left", fill="both", expand=True)

        # Header
        header = tk.Frame(self._content, bg=COLORS["bg_ai_msg"])
        header.pack(fill="x")

        self._header_label = tk.Label(
            header, text="\u25c6 AGENTIC MODE",
            bg=COLORS["bg_ai_msg"], fg=COLORS["neon_yellow"],
            font=("Consolas", 9, "bold"), anchor="w"
        )
        self._header_label.pack(side="left")

        self._step_label = tk.Label(
            header, text="",
            bg=COLORS["bg_ai_msg"], fg=COLORS["text_muted"],
            font=("Consolas", 8), anchor="e"
        )
        self._step_label.pack(side="right")

        # Steps frame
        self._steps_frame = tk.Frame(self._content, bg=COLORS["bg_ai_msg"])
        self._steps_frame.pack(fill="x", pady=(4, 0))

        # Status label
        self._status_label = tk.Label(
            self._content, text="Analyzing task...",
            bg=COLORS["bg_ai_msg"], fg=COLORS["text_secondary"],
            font=("Consolas", 9), anchor="w"
        )
        self._status_label.pack(anchor="w", pady=(4, 0))

        # Cancel button
        if on_cancel:
            cancel_btn = tk.Label(
                self._content, text="[ CANCEL ]",
                bg=COLORS["bg_ai_msg"], fg=COLORS["error"],
                font=("Consolas", 8), cursor="hand2"
            )
            cancel_btn.pack(anchor="e", pady=(4, 0))
            cancel_btn.bind("<Button-1>", lambda e: on_cancel())
            cancel_btn.bind("<Enter>", lambda e: cancel_btn.configure(fg="#ff6666"))
            cancel_btn.bind("<Leave>", lambda e: cancel_btn.configure(fg=COLORS["error"]))

    def update_step(self, step: int = 0, total: int = 0, tool: str = "",
                    description: str = "", status: str = "running"):
        """Update progress display.

        Args:
            step: Current step number (1-based)
            total: Total number of steps (0 if unknown)
            tool: Tool name being executed
            description: Description of current action
            status: "running", "done", "error", "pending"
        """
        # Update header
        if total > 0:
            self._step_label.configure(text=f"Step {step}/{total}")
        elif step > 0:
            self._step_label.configure(text=f"Step {step}")

        # Add/update step in list
        if step > 0:
            while len(self._steps) < step:
                self._steps.append(("", "", "pending"))
            self._steps[step - 1] = (tool, description, status)

        # Rebuild steps display
        for child in self._steps_frame.winfo_children():
            child.destroy()

        for i, (s_tool, s_desc, s_status) in enumerate(self._steps):
            frame = tk.Frame(self._steps_frame, bg=COLORS["bg_ai_msg"])
            frame.pack(fill="x", pady=1)

            # Status icon
            if s_status == "done":
                icon, color = "\u2713", COLORS["neon_cyan"]
            elif s_status == "running":
                icon, color = "\u25cf", COLORS["neon_yellow"]
            elif s_status == "error":
                icon, color = "\u2717", COLORS["error"]
            else:
                icon, color = "\u25cb", COLORS["text_muted"]

            tk.Label(
                frame, text=f"  {icon}",
                bg=COLORS["bg_ai_msg"], fg=color,
                font=("Consolas", 9), width=3, anchor="w"
            ).pack(side="left")

            tool_text = s_tool or "..."
            tk.Label(
                frame, text=tool_text,
                bg=COLORS["bg_ai_msg"], fg=COLORS["neon_cyan"] if s_status != "pending" else COLORS["text_muted"],
                font=("Consolas", 9, "bold"), anchor="w"
            ).pack(side="left", padx=(0, 6))

            if s_desc:
                tk.Label(
                    frame, text=s_desc[:40],
                    bg=COLORS["bg_ai_msg"], fg=COLORS["text_secondary"],
                    font=("Consolas", 8), anchor="w"
                ).pack(side="left")

        # Update status
        self._status_label.configure(text=description or "Processing...")

    def set_status(self, text: str, color: str = None):
        """Set status text."""
        self._status_label.configure(
            text=text,
            fg=color or COLORS["text_secondary"]
        )

    def mark_complete(self):
        """Mark the progress as complete."""
        self._header_label.configure(fg=COLORS["neon_cyan"])
        self._status_label.configure(
            text="Done", fg=COLORS["neon_cyan"]
        )

    def mark_failed(self, error: str = ""):
        """Mark the progress as failed."""
        self._header_label.configure(fg=COLORS["error"])
        self._status_label.configure(
            text=f"Failed: {error[:60]}" if error else "Failed",
            fg=COLORS["error"]
        )
