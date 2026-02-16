"""Command Palette -- floating dropdown for slash-commands.

Appears above the input field when user types '/'.
Keyboard-navigable (Up/Down/Enter/Escape).
Filters live as the user types.
Scrollable when items exceed visible area.
"""

import tkinter as tk
from overlay.constants import COLORS, LOG
from overlay.commands.registry import COMMANDS, filter_commands, Command

_ITEM_H = 28  # pixel height per item row
_BG = COLORS["bg_deep"]
_BG_SEL = COLORS["bg_highlight"]
_FG_SLASH = COLORS["accent_secondary"]
_FG_SLASH_SEL = COLORS["neon_cyan"]
_FG_DESC = COLORS["text_secondary"]
_FG_ICON = COLORS["text_muted"]


class CommandPalette(tk.Toplevel):
    """Floating command palette dropdown with scroll support."""

    MAX_VISIBLE = 10

    def __init__(self, parent, entry_widget, on_select):
        super().__init__(parent)

        self.entry_widget = entry_widget
        self.on_select = on_select
        self._selected_idx = 0
        self._items = list(COMMANDS)
        self._item_rows = []  # [(frame, icon_lbl, slash_lbl, desc_lbl), ...]
        self._last_filter = None  # avoid redundant rebuilds

        # Frameless popup
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=COLORS["neon_cyan"])  # 1px border color

        # Inner frame (1px inset from border)
        inner = tk.Frame(self, bg=_BG)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        # Header
        hdr = tk.Frame(inner, bg=COLORS["bg_elevated"])
        hdr.pack(fill="x")
        tk.Label(
            hdr, text="/ COMMANDS", bg=COLORS["bg_elevated"],
            fg=COLORS["neon_cyan"], font=("Consolas", 8, "bold"),
            padx=8, pady=3,
        ).pack(anchor="w")

        # ── Scrollable item area ──
        scroll_wrap = tk.Frame(inner, bg=_BG)
        scroll_wrap.pack(fill="both", expand=True)

        self._canvas = tk.Canvas(
            scroll_wrap, bg=_BG, highlightthickness=0, bd=0,
        )
        self._scrollbar = tk.Scrollbar(
            scroll_wrap, orient="vertical", command=self._canvas.yview,
            width=6, troughcolor=_BG,
        )
        self._canvas.configure(yscrollcommand=self._scrollbar.set)

        self._list_frame = tk.Frame(self._canvas, bg=_BG)
        self._canvas_win = self._canvas.create_window(
            (0, 0), window=self._list_frame, anchor="nw",
        )

        # Resize canvas window width to match canvas
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._list_frame.bind("<Configure>", self._on_list_configure)

        self._canvas.pack(side="left", fill="both", expand=True)
        # Scrollbar packed on demand in _update_scrollbar

        # Mousewheel scrolling (bind recursively)
        self._bind_scroll(self._canvas)

        # Build initial items
        self._build_items("")

        # Position above entry
        self._position()

        # Keyboard fallback (entry normally handles keys)
        self.bind("<Escape>", lambda e: self.dismiss())
        self.bind("<Return>", self._on_enter)
        self.bind("<Up>", self._on_up)
        self.bind("<Down>", self._on_down)
        self.bind("<Key>", self._on_key)
        self.bind("<FocusOut>", self._on_focus_out)

    # ── Canvas / Scroll helpers ──

    def _on_canvas_configure(self, event):
        self._canvas.itemconfig(self._canvas_win, width=event.width)

    def _on_list_configure(self, event):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _bind_scroll(self, widget):
        """Bind mousewheel to widget and all children recursively."""
        widget.bind("<Button-4>", self._scroll_up)
        widget.bind("<Button-5>", self._scroll_down)
        widget.bind("<MouseWheel>", self._scroll_wheel)
        for child in widget.winfo_children():
            self._bind_scroll(child)

    def _scroll_up(self, event):
        self._canvas.yview_scroll(-2, "units")
        return "break"

    def _scroll_down(self, event):
        self._canvas.yview_scroll(2, "units")
        return "break"

    def _scroll_wheel(self, event):
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    def _update_scrollbar(self):
        """Show/hide scrollbar based on content vs visible area."""
        total = len(self._items)
        if total > self.MAX_VISIBLE:
            self._scrollbar.pack(side="right", fill="y")
        else:
            self._scrollbar.pack_forget()

    # ── Positioning ──

    def _position(self):
        """Position palette above the entry widget."""
        try:
            ex = self.entry_widget.winfo_rootx()
            ey = self.entry_widget.winfo_rooty()
            ew = self.entry_widget.winfo_width()

            pw = min(max(ew, 340), 420)
            visible = min(len(self._items), self.MAX_VISIBLE)
            visible = max(visible, 1)
            ph = 26 + visible * _ITEM_H + 6  # header + items + padding

            px = ex
            py = ey - ph - 4

            if py < 0:
                py = ey + self.entry_widget.winfo_height() + 4

            self.geometry(f"{pw}x{ph}+{px}+{py}")
        except Exception as e:
            LOG.debug(f"CommandPalette position error: {e}")
            self.geometry("380x300+100+100")

    # ── Build / Rebuild Items ──

    def _build_items(self, query: str):
        """Full rebuild of item widgets (only when filter text changes)."""
        self._last_filter = query

        # Destroy old rows
        for row in self._item_rows:
            row[0].destroy()
        self._item_rows = []

        # Filter commands
        self._items = filter_commands(query)
        if not self._items:
            lbl = tk.Label(
                self._list_frame, text="  No matches",
                bg=_BG, fg=COLORS["text_muted"],
                font=("Consolas", 9), anchor="w", padx=8, height=2,
            )
            lbl.pack(fill="x")
            self._item_rows.append((lbl, lbl, lbl, lbl))
            self._update_scrollbar()
            return

        self._selected_idx = max(0, min(self._selected_idx, len(self._items) - 1))

        for i, cmd in enumerate(self._items):
            frame = tk.Frame(self._list_frame, bg=_BG, height=_ITEM_H)
            frame.pack(fill="x")
            frame.pack_propagate(False)

            icon_lbl = tk.Label(
                frame, text=f" {cmd.icon} ",
                bg=_BG, fg=_FG_ICON,
                font=("Consolas", 9), width=3,
            )
            icon_lbl.pack(side="left")

            slash_lbl = tk.Label(
                frame, text=cmd.slash,
                bg=_BG, fg=_FG_SLASH,
                font=("Consolas", 9, "bold"), anchor="w",
            )
            slash_lbl.pack(side="left", padx=(0, 6))

            desc_lbl = tk.Label(
                frame, text=cmd.description,
                bg=_BG, fg=_FG_DESC,
                font=("Consolas", 8), anchor="w",
            )
            desc_lbl.pack(side="left", fill="x", expand=True)

            # Click + hover bindings
            for w in (frame, icon_lbl, slash_lbl, desc_lbl):
                w.bind("<Button-1>", lambda e, j=i: self._select_item(j))
                w.bind("<Enter>", lambda e, j=i: self._hover_item(j))

            # Scroll bindings
            self._bind_scroll(frame)

            self._item_rows.append((frame, icon_lbl, slash_lbl, desc_lbl))

        self._update_scrollbar()
        self._highlight_selected()

    def _highlight_selected(self):
        """Update highlight colors without rebuilding widgets (fast, no flicker)."""
        for i, (frame, icon_lbl, slash_lbl, desc_lbl) in enumerate(self._item_rows):
            if i == self._selected_idx:
                bg, fg_sl = _BG_SEL, _FG_SLASH_SEL
            else:
                bg, fg_sl = _BG, _FG_SLASH

            try:
                frame.configure(bg=bg)
                icon_lbl.configure(bg=bg)
                slash_lbl.configure(bg=bg, fg=fg_sl)
                desc_lbl.configure(bg=bg)
            except tk.TclError:
                pass

    def _ensure_visible(self):
        """Scroll so the selected item is visible in the canvas."""
        if not self._item_rows or self._selected_idx >= len(self._item_rows):
            return
        try:
            y_top = self._selected_idx * _ITEM_H
            y_bot = y_top + _ITEM_H
            canvas_h = self._canvas.winfo_height()
            if canvas_h <= 0:
                return

            # Get current scroll position in pixels
            regions = self._canvas.cget("scrollregion").split()
            if len(regions) < 4:
                return
            total_h = int(float(regions[3]))
            if total_h <= 0:
                return

            view = self._canvas.yview()
            vis_top = view[0] * total_h
            vis_bot = view[1] * total_h

            if y_top < vis_top:
                self._canvas.yview_moveto(y_top / total_h)
            elif y_bot > vis_bot:
                self._canvas.yview_moveto((y_bot - canvas_h) / total_h)
        except Exception:
            pass

    # ── Hover / Select ──

    def _hover_item(self, idx: int):
        """Highlight on mouse hover (no rebuild, just color change)."""
        if idx != self._selected_idx and 0 <= idx < len(self._item_rows):
            self._selected_idx = idx
            self._highlight_selected()

    def _select_item(self, idx: int):
        if 0 <= idx < len(self._items):
            self.on_select(self._items[idx])
            self.dismiss()

    # ── Keyboard ──

    def _on_enter(self, event):
        if 0 <= self._selected_idx < len(self._items):
            self.on_select(self._items[self._selected_idx])
            self.dismiss()
        return "break"

    def _on_up(self, event):
        if self._items:
            self._selected_idx = (self._selected_idx - 1) % len(self._items)
            self._highlight_selected()
            self._ensure_visible()
        return "break"

    def _on_down(self, event):
        if self._items:
            self._selected_idx = (self._selected_idx + 1) % len(self._items)
            self._highlight_selected()
            self._ensure_visible()
        return "break"

    def _on_key(self, event):
        """Forward typing to entry when palette somehow has focus."""
        if event.keysym in ("Up", "Down", "Return", "Escape",
                            "Shift_L", "Shift_R", "Control_L", "Control_R",
                            "Alt_L", "Alt_R", "Tab"):
            return
        try:
            if event.keysym == "BackSpace":
                content = self.entry_widget.get("1.0", "end-1c")
                if len(content) > 1:
                    self.entry_widget.delete("end-2c", "end-1c")
                else:
                    self.entry_widget.delete("1.0", "end")
                    self.dismiss()
                    return
            elif event.char and event.char.isprintable():
                self.entry_widget.insert("end", event.char)
        except Exception:
            pass
        self.after(10, self._sync_filter)

    # ── Filter sync ──

    def _sync_filter(self):
        query = self._get_current_query()
        if query != self._last_filter:
            self._selected_idx = 0
            self._build_items(query)
            self._position()

    def _get_current_query(self) -> str:
        try:
            text = self.entry_widget.get("1.0", "end-1c").strip()
            return text[1:] if text.startswith("/") else text
        except Exception:
            return ""

    def update_filter(self, query: str):
        """Called externally by entry on keypress."""
        if query != self._last_filter:
            self._selected_idx = 0
            self._build_items(query)
            self._position()

    # ── Focus / Dismiss ──

    def _on_focus_out(self, event):
        self.after(150, self._check_focus)

    def _check_focus(self):
        try:
            focused = self.focus_get()
            if focused is None or (focused is not self and
                                   focused is not self.entry_widget and
                                   not str(focused).startswith(str(self))):
                self.dismiss()
        except Exception:
            self.dismiss()

    def dismiss(self):
        try:
            self.destroy()
        except Exception:
            pass
