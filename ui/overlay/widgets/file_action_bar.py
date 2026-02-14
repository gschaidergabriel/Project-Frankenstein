import tkinter as tk
from overlay.constants import COLORS
from overlay.widgets.modern_button import ModernButton


class FileActionBar(tk.Frame):
    """Cyberpunk-styled file action buttons."""

    def __init__(self, parent, filename: str, on_action, on_cancel):
        super().__init__(parent, bg=COLORS["bg_input"], padx=12, pady=10)

        # Top border line (neon accent)
        border_line = tk.Frame(self, bg=COLORS["neon_magenta"], height=2)
        border_line.pack(fill="x", pady=(0, 8))

        # File info with cyberpunk styling
        info = tk.Label(
            self,
            text=f"◆ FILE: {filename}",
            bg=COLORS["bg_input"],
            fg=COLORS["neon_cyan"],
            font=("Consolas", 10, "bold")
        )
        info.pack(anchor="w")

        question = tk.Label(
            self,
            text="SELECT ACTION:",
            bg=COLORS["bg_input"],
            fg=COLORS["text_secondary"],
            font=("Consolas", 9)
        )
        question.pack(anchor="w", pady=(2, 8))

        # Buttons row
        btn_frame = tk.Frame(self, bg=COLORS["bg_input"])
        btn_frame.pack(fill="x")

        actions = [
            ("EXPLAIN", "Explain the content simply."),
            ("SUMMARY", "Summarize the content (bullet points)."),
            ("ANALYZE", "Analyze the content thoroughly: purpose, structure, key sections, risks."),
            ("DEBUG", "If code: find bugs/edge-cases and suggest fixes."),
        ]

        for text, action in actions:
            btn = ModernButton(
                btn_frame, text=text,
                command=lambda a=action: on_action(a),
                width=72, height=28,
                bg=COLORS["neon_cyan"],
                hover_bg=COLORS["accent_hover"]
            )
            btn.pack(side="left", padx=(0, 4))

        cancel_btn = ModernButton(
            btn_frame, text="CANCEL",
            command=on_cancel,
            width=65, height=28,
            bg=COLORS["error"],
            hover_bg=COLORS["error"]
        )
        cancel_btn.pack(side="left")
