import tkinter as tk
from overlay.constants import COLORS, LOG


class ModernEntry(tk.Frame):
    """ChatGPT-style growing text input with cyberpunk styling.

    - Multi-line with word wrap
    - Auto-grows from 1 to 4 lines
    - Click anywhere to position cursor
    - Enter sends (no newlines)
    - Scrollable when content exceeds max lines
    - Arrow Up/Down cycles through input history
    - '/' as first character opens command palette
    """

    MIN_LINES = 1
    MAX_LINES = 4
    MAX_HISTORY = 100

    def __init__(self, parent, height=40, **kwargs):
        kwargs.pop('height', None)

        super().__init__(parent, bg=COLORS["neon_green"], padx=2, pady=2)

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

        # ── Input History ──
        self._history = []
        self._history_idx = -1  # -1 = live input (not browsing)
        self._history_draft = ""  # save current input when browsing

        # ── Command Palette ──
        self._palette = None  # Active CommandPalette instance
        self._palette_callback = None  # Set by overlay to handle command selection
        self._slash_debounce_id = None  # debounce timer for slash filter
        self._focus_out_id = None  # delayed focus-out timer

        # CRITICAL: Click to force focus (needed for overrideredirect windows)
        self.text.bind("<Button-1>", self._on_click)
        self.inner.bind("<Button-1>", self._on_click)
        self.bind("<Button-1>", self._on_click)

        # Auto-resize on content change - multiple triggers for reliability
        self.text.bind("<KeyRelease>", self._on_key_release)
        self.text.bind("<Key>", self._schedule_resize)
        self.text.bind("<<Modified>>", self._on_modified)
        self._resize_scheduled = False

        # History navigation / palette navigation
        self.text.bind("<Up>", self._history_prev)
        self.text.bind("<Down>", self._history_next)
        self.text.bind("<Escape>", self._on_escape)

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

    # ── History ──

    def add_to_history(self, text: str):
        """Record a sent message in history. Called by chat after send."""
        text = text.strip()
        if not text:
            return
        # Don't duplicate consecutive identical entries
        if self._history and self._history[-1] == text:
            return
        self._history.append(text)
        if len(self._history) > self.MAX_HISTORY:
            self._history = self._history[-self.MAX_HISTORY:]
        self._history_idx = -1

    def _history_prev(self, event):
        """Arrow Up: navigate palette (if open) or show previous sent message."""
        # If palette is open, navigate it instead
        if self._palette and hasattr(self._palette, 'winfo_exists'):
            try:
                if self._palette.winfo_exists():
                    self._palette._on_up(event)
                    return "break"
            except Exception:
                pass

        # Only when cursor is on the first display line
        try:
            bbox = self.text.bbox("insert")
            first_bbox = self.text.bbox("1.0")
            if bbox and first_bbox and bbox[1] > first_bbox[1] + 2:
                return  # cursor not on first line, let normal arrow work
        except Exception:
            pass

        if not self._history:
            return "break"

        # Save draft when starting to browse
        if self._history_idx == -1:
            self._history_draft = self.text.get("1.0", "end-1c")

        if self._history_idx < len(self._history) - 1:
            self._history_idx += 1
            self._set_text(self._history[-(self._history_idx + 1)])

        return "break"

    def _history_next(self, event):
        """Arrow Down: navigate palette (if open) or show next sent message."""
        # If palette is open, navigate it instead
        if self._palette and hasattr(self._palette, 'winfo_exists'):
            try:
                if self._palette.winfo_exists():
                    self._palette._on_down(event)
                    return "break"
            except Exception:
                pass

        # Only when cursor is on the last display line
        try:
            bbox = self.text.bbox("insert")
            end_bbox = self.text.bbox("end-1c")
            if bbox and end_bbox and bbox[1] < end_bbox[1] - 2:
                return  # cursor not on last line, let normal arrow work
        except Exception:
            pass

        if self._history_idx > 0:
            self._history_idx -= 1
            self._set_text(self._history[-(self._history_idx + 1)])
        elif self._history_idx == 0:
            self._history_idx = -1
            self._set_text(self._history_draft)

        return "break"

    def _set_text(self, text: str):
        """Replace entry content."""
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self.text.mark_set("insert", "end-1c")
        self._auto_resize()

    def _on_escape(self, event):
        """Escape: dismiss palette and clear slash prefix."""
        if self._palette and hasattr(self._palette, 'winfo_exists'):
            try:
                if self._palette.winfo_exists():
                    self._dismiss_palette()
                    self._set_text("")
                    return "break"
            except Exception:
                pass

    # ── Command Palette ──

    def _on_key_release(self, event=None):
        """Handle key release: check for slash commands + resize."""
        self._schedule_resize(event)
        self._check_slash_trigger()

    def _check_slash_trigger(self):
        """Debounced check for '/' as first char to open/update palette."""
        if self._slash_debounce_id is not None:
            self.after_cancel(self._slash_debounce_id)
        self._slash_debounce_id = self.after(30, self._do_slash_check)

    def _do_slash_check(self):
        """Actual slash check after debounce."""
        self._slash_debounce_id = None
        try:
            content = self.text.get("1.0", "end-1c")
            if content.startswith("/") and len(content) >= 1:
                if self._palette is None or not self._palette.winfo_exists():
                    self._open_palette()
                else:
                    query = content[1:]
                    self._palette.update_filter(query)
            else:
                self._dismiss_palette()
        except Exception:
            pass

    def _open_palette(self):
        """Open the command palette."""
        try:
            from overlay.widgets.command_palette import CommandPalette
            root = self.winfo_toplevel()
            self._palette = CommandPalette(
                root, self.text, on_select=self._on_palette_select
            )
        except Exception as e:
            LOG.debug(f"Failed to open command palette: {e}")

    def _on_palette_select(self, command):
        """Handle command selection from palette."""
        self._dismiss_palette()

        if command.action == "file_dialog":
            # Trigger file attach
            root = self.winfo_toplevel()
            if hasattr(root, '_on_attach'):
                self._set_text("")
                root._on_attach()
            return

        if command.action == "email_settings":
            root = self.winfo_toplevel()
            if hasattr(root, '_io_q'):
                self._set_text("")
                root._io_q.put(("email_settings", {}))
            return

        if command.action == "system_restart":
            root = self.winfo_toplevel()
            if hasattr(root, '_io_q'):
                self._set_text("")
                root._io_q.put(("system_restart", {}))
            return

        if command.template:
            # Insert template into entry
            template = command.template
            self._set_text(template)

            # Position cursor at first placeholder
            idx = template.find("{")
            if idx >= 0:
                end_idx = template.find("}", idx)
                if end_idx >= 0:
                    self.text.tag_add("sel", f"1.0+{idx}c", f"1.0+{end_idx + 1}c")
                    self.text.mark_set("insert", f"1.0+{end_idx + 1}c")
            else:
                # No placeholder, put cursor at end
                self.text.mark_set("insert", "end-1c")

            self.text.focus_set()
        else:
            self._set_text("")

        # Notify external callback if set
        if self._palette_callback:
            self._palette_callback(command)

    def _dismiss_palette(self):
        """Close the palette if open."""
        if self._palette is not None:
            try:
                if self._palette.winfo_exists():
                    self._palette.dismiss()
            except Exception:
                pass
            self._palette = None

    # ── Click / Focus ──

    def _on_click(self, event):
        """Force focus on click - triggers window focus hack."""
        root = self.winfo_toplevel()
        if hasattr(root, '_on_window_click_focus'):
            root._on_window_click_focus(event)
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
                display_lines = self.text.count("1.0", "end", "displaylines")
                if display_lines:
                    new_height = display_lines[0] if isinstance(display_lines, tuple) else display_lines
                else:
                    widget_width = max(self.text.winfo_width() - 20, 100)
                    char_width = 8
                    chars_per_line = max(widget_width // char_width, 20)
                    new_height = max(1, (len(content) + chars_per_line - 1) // chars_per_line)
            except tk.TclError:
                new_height = self.MIN_LINES
            except Exception as e:
                LOG.debug(f"Auto-resize calculation error: {e}")
                new_height = self.MIN_LINES

        new_height = max(self.MIN_LINES, min(self.MAX_LINES, new_height))

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
        """Cyan border on focus. Cancel any pending palette dismiss."""
        if self._focus_out_id is not None:
            self.after_cancel(self._focus_out_id)
            self._focus_out_id = None
        self.configure(bg=COLORS["neon_cyan"])

    def _on_focus_out(self, event):
        """Magenta border when unfocused. Delayed palette dismiss to allow clicks."""
        self.configure(bg=COLORS["neon_green"])
        # Delay dismiss so palette click events can fire first
        if self._focus_out_id is not None:
            self.after_cancel(self._focus_out_id)
        self._focus_out_id = self.after(200, self._delayed_palette_dismiss)

    def _delayed_palette_dismiss(self):
        """Dismiss palette after delay, unless focus returned to entry or palette."""
        self._focus_out_id = None
        try:
            focused = self.focus_get()
            # Keep palette if focus is on entry text or on the palette itself
            if focused is self.text:
                return
            if self._palette is not None:
                try:
                    if self._palette.winfo_exists():
                        pal_str = str(self._palette)
                        if focused is not None and str(focused).startswith(pal_str):
                            return
                except Exception:
                    pass
        except Exception:
            pass
        self._dismiss_palette()

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
        """Bind event to text widget. Special handling for Return and Escape."""
        if sequence == "<Return>":
            def on_return(event):
                # If palette is open, select from it instead of sending
                if self._palette and hasattr(self._palette, 'winfo_exists'):
                    try:
                        if self._palette.winfo_exists():
                            self._palette._on_enter(event)
                            return "break"
                    except Exception:
                        pass
                self._dismiss_palette()
                func(event)
                return "break"
            self.text.bind(sequence, on_return)
        else:
            self.text.bind(sequence, func)
