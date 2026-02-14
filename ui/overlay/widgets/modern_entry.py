import tkinter as tk
from overlay.constants import COLORS, LOG


class ModernEntry(tk.Frame):
    """ChatGPT-style growing text input with cyberpunk styling.

    - Multi-line with word wrap
    - Auto-grows from 1 to 4 lines
    - Click anywhere to position cursor
    - Enter sends (no newlines)
    - Scrollable when content exceeds max lines
    """

    MIN_LINES = 1
    MAX_LINES = 4

    def __init__(self, parent, height=40, **kwargs):
        kwargs.pop('height', None)

        super().__init__(parent, bg=COLORS["neon_magenta"], padx=2, pady=2)

        # Inner frame for dark background
        self.inner = tk.Frame(self, bg=COLORS["bg_deep"])
        self.inner.pack(fill="both", expand=True)

        # Text widget (multi-line, word wrap, no scrollbar)
        self.text = tk.Text(
            self.inner,
            bg=COLORS["bg_deep"],
            fg=COLORS["text_primary"],
            insertbackground=COLORS["neon_cyan"],
            insertwidth=2,  # Visible cursor
            selectbackground=COLORS["accent"],
            selectforeground=COLORS["text_primary"],
            relief="flat",
            font=("Consolas", 11),
            wrap="word",
            height=self.MIN_LINES,
            bd=0,
            highlightthickness=0,
            padx=10,
            pady=8,
            undo=True,
            takefocus=True,
        )
        self.text.pack(fill="both", expand=True)

        # CRITICAL: Click to force focus (needed for overrideredirect windows)
        self.text.bind("<Button-1>", self._on_click)
        self.inner.bind("<Button-1>", self._on_click)
        self.bind("<Button-1>", self._on_click)

        # Auto-resize on content change - multiple triggers for reliability
        self.text.bind("<KeyRelease>", self._schedule_resize)
        self.text.bind("<Key>", self._schedule_resize)
        self.text.bind("<<Modified>>", self._on_modified)
        self._resize_scheduled = False

        # Focus effects
        self.text.bind("<FocusIn>", self._on_focus_in)
        self.text.bind("<FocusOut>", self._on_focus_out)

        # Right-click paste menu
        self.text.bind("<Button-3>", self._show_paste_menu)

        # Mousewheel scrolling (no visible scrollbar)
        self.text.bind("<Button-4>", self._on_scroll)
        self.text.bind("<Button-5>", self._on_scroll)
        self.text.bind("<MouseWheel>", self._on_scroll)

        # Store send callback (set via bind)
        self._send_callback = None

    def _on_click(self, event):
        """Force focus on click - triggers window focus hack."""
        # Get the root window and trigger its focus hack
        root = self.winfo_toplevel()
        if hasattr(root, '_on_window_click_focus'):
            root._on_window_click_focus(event)
        # Let the click propagate to position cursor
        return None

    def _schedule_resize(self, event=None):
        """Schedule resize after idle - prevents multiple rapid resizes."""
        if not self._resize_scheduled:
            self._resize_scheduled = True
            self.after_idle(self._do_resize)

    def _do_resize(self):
        """Actually perform the resize."""
        self._resize_scheduled = False
        self._auto_resize()

    def _on_modified(self, event=None):
        """Handle text modification."""
        if self.text.edit_modified():
            self._schedule_resize()
            self.text.edit_modified(False)

    def _auto_resize(self, event=None):
        """Resize text widget based on content - simple and reliable."""
        content = self.text.get("1.0", "end-1c")

        if not content:
            new_height = self.MIN_LINES
        else:
            try:
                # Method: Use displaylines count (most accurate for wrapped text)
                # This counts actual displayed lines including word-wrapped ones
                display_lines = self.text.count("1.0", "end", "displaylines")
                if display_lines:
                    new_height = display_lines[0] if isinstance(display_lines, tuple) else display_lines
                else:
                    # Fallback: estimate based on character count
                    widget_width = max(self.text.winfo_width() - 20, 100)  # subtract padding
                    char_width = 8  # approximate width per character in Consolas 11
                    chars_per_line = max(widget_width // char_width, 20)
                    new_height = max(1, (len(content) + chars_per_line - 1) // chars_per_line)
            except tk.TclError:
                new_height = self.MIN_LINES
            except Exception as e:
                LOG.debug(f"Auto-resize calculation error: {e}")
                new_height = self.MIN_LINES

        # Clamp to min/max
        new_height = max(self.MIN_LINES, min(self.MAX_LINES, new_height))

        # Update height if changed
        current_height = int(self.text.cget("height"))
        if current_height != new_height:
            self.text.configure(height=new_height)

    def _on_scroll(self, event):
        """Handle mousewheel scrolling."""
        if event.num == 4 or (hasattr(event, 'delta') and event.delta > 0):
            self.text.yview_scroll(-1, "units")
        elif event.num == 5 or (hasattr(event, 'delta') and event.delta < 0):
            self.text.yview_scroll(1, "units")
        return "break"

    def _on_focus_in(self, event):
        """Cyan border on focus."""
        self.configure(bg=COLORS["neon_cyan"])

    def _on_focus_out(self, event):
        """Magenta border when unfocused."""
        self.configure(bg=COLORS["neon_magenta"])

    def _show_paste_menu(self, event):
        """Show right-click context menu."""
        menu = tk.Menu(self.text, tearoff=0,
                      bg=COLORS["bg_elevated"],
                      fg=COLORS["text_primary"],
                      activebackground=COLORS["accent"],
                      activeforeground=COLORS["bg_main"],
                      font=("Consolas", 10))
        menu.add_command(label="Paste", command=self._paste_from_clipboard)
        menu.add_command(label="Select All", command=lambda: self.text.tag_add("sel", "1.0", "end-1c"))
        menu.add_command(label="Clear", command=lambda: self.text.delete("1.0", "end"))
        menu.tk_popup(event.x_root, event.y_root)

    def _paste_from_clipboard(self):
        """Paste from clipboard at cursor."""
        try:
            clipboard_text = self.text.clipboard_get()
            # Remove any newlines from pasted text
            clipboard_text = clipboard_text.replace("\n", " ").replace("\r", "")
            self.text.insert("insert", clipboard_text)
        except tk.TclError:
            pass

    def get(self):
        """Get text content (without trailing newline)."""
        return self.text.get("1.0", "end-1c").strip()

    def delete(self, first, last=None):
        """Clear all text."""
        self.text.delete("1.0", "end")
        self._auto_resize()

    def insert(self, index, string):
        """Insert text."""
        self.text.insert("end", string)
        self._auto_resize()

    def focus_set(self):
        """Set focus to text widget."""
        self.text.focus_set()

    def bind(self, sequence, func):
        """Bind event to text widget. Special handling for Return."""
        if sequence == "<Return>":
            # Enter sends, don't insert newline
            def on_return(event):
                func(event)
                return "break"  # Prevent newline insertion
            self.text.bind(sequence, on_return)
        else:
            self.text.bind(sequence, func)
