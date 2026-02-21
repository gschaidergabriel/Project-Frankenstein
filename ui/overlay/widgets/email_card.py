import tkinter as tk
import email.utils
from dataclasses import dataclass
from datetime import datetime
from overlay.constants import COLORS


@dataclass
class EmailData:
    idx: int
    msg_id: str
    sender: str
    subject: str
    date: str
    timestamp: float
    snippet: str
    read: bool
    starred: bool
    folder: str = "INBOX"
    to: str = ""
    cc: str = ""


def format_sender(from_header: str) -> str:
    """Extract display name from 'Name <email@example.com>' format."""
    if "<" in from_header:
        name = from_header.split("<")[0].strip().strip('"').strip("'")
        if name:
            return name[:35]
        # No display name, extract user part from <email@domain>
        email_part = from_header.split("<")[1].split(">")[0].strip()
        if "@" in email_part:
            return email_part.split("@")[0][:35]
        return email_part[:35]
    if "@" in from_header:
        return from_header.split("@")[0].strip().strip('"')[:35]
    return from_header[:35]


def format_date_short(date_str: str) -> str:
    """Format RFC2822 date to 'DD.MM. HH:MM'."""
    try:
        dt = email.utils.parsedate_tz(date_str)
        if dt:
            ts = email.utils.mktime_tz(dt)
            d = datetime.fromtimestamp(ts)
            return d.strftime("%d.%m. %H:%M")
    except Exception:
        pass
    return date_str[:16] if date_str else "?"


class EmailCard(tk.Frame):
    """Cyberpunk-styled email card with real metadata (no LLM)."""

    def __init__(self, parent, email_data: EmailData, on_click=None):
        super().__init__(parent, bg=COLORS["bg_main"])

        self.email_data = email_data
        self.on_click = on_click
        self._normal_bg = COLORS["bg_elevated"]
        self._hover_bg = COLORS["bg_highlight"]
        self._border_color = COLORS["neon_cyan"] if not email_data.read else COLORS["text_muted"]

        # Card container
        self.card = tk.Frame(self, bg=self._normal_bg)
        self.card.pack(fill="both", pady=2)

        # Left border stripe
        self.border_stripe = tk.Frame(self.card, bg=self._border_color, width=3)
        self.border_stripe.pack(side="left", fill="y")

        # Content area
        content = tk.Frame(self.card, bg=self._normal_bg, padx=12, pady=6)
        content.pack(side="left", fill="both", expand=True)

        # Header row: badge + sender + date
        header = tk.Frame(content, bg=self._normal_bg)
        header.pack(anchor="w", fill="x")

        if not email_data.read:
            badge = tk.Label(
                header, text=" NEU ",
                bg=COLORS["neon_green"], fg=COLORS["bg_main"],
                font=("Consolas", 8, "bold")
            )
            badge.pack(side="left", padx=(0, 6))

        sender_text = format_sender(email_data.sender)
        self.sender_label = tk.Label(
            header, text=sender_text,
            bg=self._normal_bg, fg=COLORS["link"],
            font=("Consolas", 10, "bold"),
            anchor="w", cursor="hand2"
        )
        self.sender_label.pack(side="left", fill="x", expand=True)

        date_text = format_date_short(email_data.date)
        self.date_label = tk.Label(
            header, text=date_text,
            bg=self._normal_bg, fg=COLORS["text_muted"],
            font=("Consolas", 8), anchor="e"
        )
        self.date_label.pack(side="right")

        # Subject line
        subj = email_data.subject or "(kein Betreff)"
        if len(subj) > 55:
            subj = subj[:55] + "..."
        self.subject_label = tk.Label(
            content, text=subj,
            bg=self._normal_bg, fg=COLORS["text_primary"],
            font=("Consolas", 9), anchor="w"
        )
        self.subject_label.pack(anchor="w", fill="x", pady=(2, 0))

        self._bind_all_children()

    def _bind_all_children(self):
        widgets = [self, self.card, self.sender_label, self.subject_label, self.date_label]
        for widget in widgets:
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)
            widget.bind("<Button-1>", self._on_click)
            # Propagate scroll events to parent canvas
            widget.bind("<Button-4>", self._on_scroll)
            widget.bind("<Button-5>", self._on_scroll)

    def _on_scroll(self, event):
        """Propagate scroll to parent canvas."""
        # Walk up widget tree to find the Canvas
        w = self.master
        while w is not None:
            if isinstance(w, tk.Canvas):
                w.yview_scroll(-1 if event.num == 4 else 1, "units")
                return "break"
            w = getattr(w, 'master', None)
        return "break"

    def _update_colors(self, bg_color, border_color):
        self.card.configure(bg=bg_color)
        self.border_stripe.configure(bg=border_color)
        self.sender_label.configure(bg=bg_color)
        self.subject_label.configure(bg=bg_color)
        self.date_label.configure(bg=bg_color)
        for child in self.card.winfo_children():
            if isinstance(child, tk.Frame) and child != self.border_stripe:
                child.configure(bg=bg_color)
                for gc in child.winfo_children():
                    try:
                        if gc.cget('bg') not in [COLORS["neon_green"]]:
                            gc.configure(bg=bg_color)
                    except tk.TclError:
                        pass

    def _on_enter(self, event):
        self._update_colors(self._hover_bg, COLORS["neon_green"])
        self.sender_label.configure(fg=COLORS.get("link_hover", COLORS["neon_cyan"]))

    def _on_leave(self, event):
        self._update_colors(self._normal_bg, self._border_color)
        self.sender_label.configure(fg=COLORS["link"])

    def _on_click(self, event):
        if self.on_click:
            self.on_click(self.email_data)
