"""Command Palette -- floating dropdown for slash-commands.

Appears above the input field when user types '/'.
Keyboard-navigable (Up/Down/Enter/Escape).
Filters live as the user types.
"""

import tkinter as tk
from overlay.constants import COLORS, LOG
from overlay.commands.registry import COMMANDS, filter_commands, Command


class CommandPalette(tk.Toplevel):
    """Floating command palette dropdown."""

    MAX_VISIBLE = 8  # max items shown at once

    def __init__(self, parent, entry_widget, on_select):
        """
        Args:
            parent:       Root overlay window
            entry_widget: The ModernEntry.text widget (for positioning)
            on_select:    Callback(Command) when a command is selected
        """
        super().__init__(parent)

        self.entry_widget = entry_widget
        self.on_select = on_select
        self._selected_idx = 0
        self._items = list(COMMANDS)

        # Frameless popup
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=COLORS["neon_cyan"])

        # Inner frame with 1px border effect
        inner = tk.Frame(self, bg=COLORS["bg_deep"], padx=1, pady=1)
        inner.pack(fill="both", expand=True)

        # Header
        header = tk.Frame(inner, bg=COLORS["bg_elevated"])
        header.pack(fill="x")
        tk.Label(
            header, text="/ COMMANDS", bg=COLORS["bg_elevated"],
            fg=COLORS["neon_cyan"], font=("Consolas", 8, "bold"),
            padx=8, pady=4
        ).pack(anchor="w")

        # Item list frame
        self._list_frame = tk.Frame(inner, bg=COLORS["bg_deep"])
        self._list_frame.pack(fill="both", expand=True)

        # Build initial items
        self._item_widgets = []
        self._rebuild_items("")

        # Position above entry
        self._position()

        # Keep keyboard bindings as fallback (in case palette somehow gets focus)
        self.bind("<Escape>", lambda e: self.dismiss())
        self.bind("<Return>", self._on_enter)
        self.bind("<Up>", self._on_up)
        self.bind("<Down>", self._on_down)
        self.bind("<Key>", self._on_key)
        self.bind("<FocusOut>", self._on_focus_out)

        # Do NOT steal focus — entry handles keystrokes and forwards to us

    def _position(self):
        """Position palette above the entry widget."""
        try:
            # Get entry's screen position
            ex = self.entry_widget.winfo_rootx()
            ey = self.entry_widget.winfo_rooty()
            ew = self.entry_widget.winfo_width()

            # Palette dimensions
            pw = min(max(ew, 340), 420)
            item_h = 32
            visible = min(len(self._items), self.MAX_VISIBLE)
            ph = 28 + visible * item_h + 4  # header + items + padding

            # Place above entry
            px = ex
            py = ey - ph - 4

            # Ensure on screen
            if py < 0:
                py = ey + self.entry_widget.winfo_height() + 4

            self.geometry(f"{pw}x{ph}+{px}+{py}")
        except Exception as e:
            LOG.debug(f"CommandPalette positioning error: {e}")
            self.geometry("380x300+100+100")

    def _rebuild_items(self, query: str):
        """Rebuild the item list based on filter query."""
        # Clear old widgets
        for w in self._item_widgets:
            w.destroy()
        self._item_widgets = []

        # Filter
        self._items = filter_commands(query)
        if not self._items:
            lbl = tk.Label(
                self._list_frame, text="  No matches",
                bg=COLORS["bg_deep"], fg=COLORS["text_muted"],
                font=("Consolas", 9), anchor="w", padx=8, pady=6
            )
            lbl.pack(fill="x")
            self._item_widgets.append(lbl)
            return

        # Clamp selection
        self._selected_idx = max(0, min(self._selected_idx, len(self._items) - 1))

        # Build items (limit to MAX_VISIBLE)
        visible_items = self._items[:self.MAX_VISIBLE]
        for i, cmd in enumerate(visible_items):
            frame = tk.Frame(self._list_frame, bg=COLORS["bg_deep"])
            frame.pack(fill="x")

            # Selection highlight
            bg = COLORS["bg_highlight"] if i == self._selected_idx else COLORS["bg_deep"]
            fg_slash = COLORS["neon_cyan"] if i == self._selected_idx else COLORS["accent_secondary"]

            # Icon + slash
            icon_lbl = tk.Label(
                frame, text=f" {cmd.icon} ",
                bg=bg, fg=COLORS["text_muted"],
                font=("Consolas", 9), width=3
            )
            icon_lbl.pack(side="left")

            slash_lbl = tk.Label(
                frame, text=cmd.slash,
                bg=bg, fg=fg_slash,
                font=("Consolas", 9, "bold"), anchor="w"
            )
            slash_lbl.pack(side="left", padx=(0, 8))

            desc_lbl = tk.Label(
                frame, text=cmd.description,
                bg=bg, fg=COLORS["text_secondary"],
                font=("Consolas", 9), anchor="w"
            )
            desc_lbl.pack(side="left", fill="x", expand=True)

            # Bind click on all labels
            idx = i
            for widget in [frame, icon_lbl, slash_lbl, desc_lbl]:
                widget.configure(bg=bg)
                widget.bind("<Button-1>", lambda e, j=idx: self._select_item(j))
                widget.bind("<Enter>", lambda e, f=frame, j=idx: self._hover_item(j))

            self._item_widgets.append(frame)

        # Show count if more items exist
        if len(self._items) > self.MAX_VISIBLE:
            more = len(self._items) - self.MAX_VISIBLE
            more_lbl = tk.Label(
                self._list_frame, text=f"  +{more} more...",
                bg=COLORS["bg_deep"], fg=COLORS["text_muted"],
                font=("Consolas", 8), anchor="w", padx=8
            )
            more_lbl.pack(fill="x")
            self._item_widgets.append(more_lbl)

    def _hover_item(self, idx: int):
        """Highlight item on mouse hover."""
        self._selected_idx = idx
        query = self._get_current_query()
        self._rebuild_items(query)

    def _select_item(self, idx: int):
        """Select item by index."""
        if 0 <= idx < len(self._items):
            self.on_select(self._items[idx])
            self.dismiss()

    def _on_enter(self, event):
        """Handle Enter key."""
        if 0 <= self._selected_idx < len(self._items):
            self.on_select(self._items[self._selected_idx])
            self.dismiss()
        return "break"

    def _on_up(self, event):
        """Move selection up."""
        if self._items:
            self._selected_idx = (self._selected_idx - 1) % min(len(self._items), self.MAX_VISIBLE)
            query = self._get_current_query()
            self._rebuild_items(query)
        return "break"

    def _on_down(self, event):
        """Move selection down."""
        if self._items:
            self._selected_idx = (self._selected_idx + 1) % min(len(self._items), self.MAX_VISIBLE)
            query = self._get_current_query()
            self._rebuild_items(query)
        return "break"

    def _on_key(self, event):
        """Handle typing when palette has focus — forward to entry widget."""
        if event.keysym in ("Up", "Down", "Return", "Escape", "Shift_L", "Shift_R",
                            "Control_L", "Control_R", "Alt_L", "Alt_R", "Tab"):
            return

        # Forward printable chars to entry (palette shouldn't normally have focus)
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

    def _sync_filter(self):
        """Sync filter with entry widget content."""
        query = self._get_current_query()
        self._selected_idx = 0
        self._rebuild_items(query)
        self._position()

    def _get_current_query(self) -> str:
        """Get current filter query from entry widget."""
        try:
            text = self.entry_widget.get("1.0", "end-1c").strip()
            if text.startswith("/"):
                return text[1:]  # Remove leading /
            return text
        except Exception:
            return ""

    def update_filter(self, query: str):
        """Update filter externally (called by entry on keypress)."""
        self._selected_idx = 0
        self._rebuild_items(query)
        self._position()

    def _on_focus_out(self, event):
        """Dismiss when focus leaves palette."""
        # Small delay to allow click events to register first
        self.after(150, self._check_focus)

    def _check_focus(self):
        """Check if focus is still on palette or entry."""
        try:
            focused = self.focus_get()
            if focused is None or (focused is not self and
                                   focused is not self.entry_widget and
                                   not str(focused).startswith(str(self))):
                self.dismiss()
        except Exception:
            self.dismiss()

    def dismiss(self):
        """Close the palette."""
        try:
            self.destroy()
        except Exception:
            pass
