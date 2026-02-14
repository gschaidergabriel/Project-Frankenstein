import tkinter as tk
import webbrowser
from dataclasses import dataclass
from overlay.constants import COLORS


@dataclass
class SearchResult:
    title: str
    snippet: str
    url: str
    source: str = ""


class SearchResultCard(tk.Frame):
    """Cyberpunk-styled search result card with neon accents.

    Pass darknet=True for Matrix-style green-on-black theme (.onion results).
    """

    def __init__(self, parent, index: int, result: SearchResult, on_click=None, darknet: bool = False):
        super().__init__(parent, bg=COLORS["darknet_bg"] if darknet else COLORS["bg_main"])

        self.result = result
        self.on_click = on_click
        self._darknet = darknet

        if darknet:
            self._normal_bg = COLORS["darknet_bg"]
            self._hover_bg = COLORS["darknet_bg_hover"]
            self._border_color = COLORS["darknet_border"]
            self._title_fg = COLORS["darknet_title"]
            self._title_hover_fg = COLORS["darknet_title_hover"]
            self._snippet_fg = COLORS["darknet_snippet"]
            self._badge_bg = COLORS["darknet_badge"]
            self._badge_fg = COLORS["darknet_badge_text"]
        else:
            self._normal_bg = COLORS["bg_elevated"]
            self._hover_bg = COLORS["bg_highlight"]
            self._border_color = COLORS["neon_cyan"]
            self._title_fg = COLORS["link"]
            self._title_hover_fg = COLORS["link_hover"]
            self._snippet_fg = COLORS["text_secondary"]
            self._badge_bg = COLORS["neon_magenta"]
            self._badge_fg = COLORS["bg_main"]

        # Card container with left border
        self.card = tk.Frame(self, bg=self._normal_bg)
        self.card.pack(fill="both", pady=2)

        # Left border stripe
        self.border_stripe = tk.Frame(self.card, bg=self._border_color, width=3)
        self.border_stripe.pack(side="left", fill="y")

        # Content area
        content = tk.Frame(self.card, bg=self._normal_bg, padx=12, pady=8)
        content.pack(side="left", fill="both", expand=True)

        # Header row: index badge + title
        header = tk.Frame(content, bg=self._normal_bg)
        header.pack(anchor="w", fill="x")

        # Index badge
        badge = tk.Label(
            header,
            text=f" {index} ",
            bg=self._badge_bg,
            fg=self._badge_fg,
            font=("Consolas", 9, "bold")
        )
        badge.pack(side="left")

        # Title
        title_text = result.title or "(Kein Titel)"
        if len(title_text) > 50:
            title_text = title_text[:50] + "..."

        self.title = tk.Label(
            header,
            text=f"  {title_text}",
            bg=self._normal_bg,
            fg=self._title_fg,
            font=("Consolas", 10, "bold"),
            anchor="w",
            cursor="hand2"
        )
        self.title.pack(side="left", fill="x", expand=True)

        # Snippet
        snippet = result.snippet[:120] + "..." if len(result.snippet) > 120 else result.snippet
        if snippet:
            self.snippet_label = tk.Label(
                content,
                text=snippet,
                bg=self._normal_bg,
                fg=self._snippet_fg,
                font=("Consolas", 9),
                anchor="w",
                wraplength=360,
                justify="left"
            )
            self.snippet_label.pack(anchor="w", fill="x", pady=(4, 0))
        else:
            self.snippet_label = None

        # For darknet: show .onion URL in muted green
        if darknet and result.url:
            url_short = result.url[:60] + "..." if len(result.url) > 60 else result.url
            self.url_label = tk.Label(
                content,
                text=url_short,
                bg=self._normal_bg,
                fg=COLORS["darknet_url"],
                font=("Consolas", 8),
                anchor="w",
            )
            self.url_label.pack(anchor="w", fill="x", pady=(2, 0))
        else:
            self.url_label = None

        # Bind events
        self._bind_all_children()

    def _bind_all_children(self):
        """Bind hover and click events to ALL child widgets recursively."""
        self._bind_recursive(self)

    def _bind_recursive(self, widget):
        """Bind click on every widget so single-click works anywhere on the card."""
        widget.bind("<Enter>", self._on_enter)
        widget.bind("<Leave>", self._on_leave)
        widget.bind("<Button-1>", self._on_click)
        for child in widget.winfo_children():
            self._bind_recursive(child)

    def _update_colors(self, bg_color, border_color):
        """Update colors of card elements."""
        self.card.configure(bg=bg_color)
        self.border_stripe.configure(bg=border_color)
        self.title.configure(bg=bg_color)
        if self.snippet_label:
            self.snippet_label.configure(bg=bg_color)
        if getattr(self, 'url_label', None):
            self.url_label.configure(bg=bg_color)
        for child in self.card.winfo_children():
            if isinstance(child, tk.Frame) and child != self.border_stripe:
                child.configure(bg=bg_color)
                for grandchild in child.winfo_children():
                    try:
                        bg = grandchild.cget('bg')
                        if bg not in [self._badge_bg, self._border_color]:
                            grandchild.configure(bg=bg_color)
                    except tk.TclError:
                        pass

    def _on_enter(self, event):
        hover_border = COLORS["darknet_title"] if self._darknet else COLORS["neon_magenta"]
        self._update_colors(self._hover_bg, hover_border)
        self.title.configure(fg=self._title_hover_fg)

    def _on_leave(self, event):
        self._update_colors(self._normal_bg, self._border_color)
        self.title.configure(fg=self._title_fg)

    def _on_click(self, event):
        if self.on_click:
            self.on_click(self.result.url)
