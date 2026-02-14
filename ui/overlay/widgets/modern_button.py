import tkinter as tk
from overlay.constants import COLORS


class ModernButton(tk.Canvas):
    """Cyberpunk-styled flat button with neon border and glow effects."""

    def __init__(self, parent, text, command=None, width=80, height=36,
                 bg=COLORS["accent"], fg=COLORS["text_primary"],
                 hover_bg=COLORS["accent_hover"], corner_radius=0, **kwargs):
        # Cyberpunk: no shadow, flat design with glow
        super().__init__(parent, width=width, height=height,
                        bg=COLORS["bg_main"], highlightthickness=0, **kwargs)

        self.command = command
        self.border_color = bg  # Border color (neon)
        self.fg = fg
        self.hover_border = hover_bg
        self.text = text.upper()  # Cyberpunk: uppercase text
        self._width = width
        self._height = height
        self._hovered = False
        self._pressed = False

        self._draw_button(hovered=False, pressed=False)

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _draw_button(self, hovered=False, pressed=False):
        self.delete("all")
        w, h = self._width, self._height
        border_width = 2

        # Determine colors based on state
        if pressed:
            # Pressed: filled with border color
            fill_color = self.border_color
            text_color = COLORS["bg_main"]
            border_color = self.border_color
        elif hovered:
            # Hovered: filled with glow
            fill_color = self.border_color
            text_color = COLORS["bg_main"]
            border_color = self.hover_border
        else:
            # Normal: transparent with border
            fill_color = COLORS["bg_main"]
            text_color = self.fg if self.fg != COLORS["text_primary"] else self.border_color
            border_color = self.border_color

        # Draw outer glow effect on hover
        if hovered and not pressed:
            # Glow layers (simulated with rectangles)
            for i, alpha in enumerate([15, 10, 5]):
                glow_offset = (i + 1) * 2
                glow_color = self._blend_color(self.border_color, COLORS["bg_main"], alpha / 100)
                self.create_rectangle(
                    -glow_offset, -glow_offset,
                    w + glow_offset, h + glow_offset,
                    fill="", outline=glow_color, width=1
                )

        # Main button border (sharp rectangle)
        self.create_rectangle(
            border_width // 2, border_width // 2,
            w - border_width // 2, h - border_width // 2,
            fill=fill_color, outline=border_color, width=border_width
        )

        # Draw text with monospace font
        text_y = h // 2
        # Add small arrow indicator (skip for small buttons)
        if w > 60:
            display_text = f"▸ {self.text}"
        else:
            display_text = self.text
        self.create_text(
            w // 2, text_y,
            text=display_text,
            fill=text_color,
            font=("Consolas", 9, "bold"),
            tags="text"
        )

    def _blend_color(self, color1, color2, ratio):
        """Simple color blend for glow effect."""
        # Parse hex colors
        r1, g1, b1 = int(color1[1:3], 16), int(color1[3:5], 16), int(color1[5:7], 16)
        r2, g2, b2 = int(color2[1:3], 16), int(color2[3:5], 16), int(color2[5:7], 16)
        # Blend
        r = int(r1 * ratio + r2 * (1 - ratio))
        g = int(g1 * ratio + g2 * (1 - ratio))
        b = int(b1 * ratio + b2 * (1 - ratio))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _on_enter(self, event):
        self._hovered = True
        if not self._pressed:
            self._draw_button(hovered=True, pressed=False)

    def _on_leave(self, event):
        self._hovered = False
        self._pressed = False
        self._draw_button(hovered=False, pressed=False)

    def _on_press(self, event):
        self._pressed = True
        self._draw_button(hovered=self._hovered, pressed=True)

    def _on_release(self, event):
        self._pressed = False
        self._draw_button(hovered=self._hovered, pressed=False)
        if self.command:
            self.command()
