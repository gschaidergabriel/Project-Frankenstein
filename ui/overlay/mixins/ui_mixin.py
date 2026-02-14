"""UiMixin -- UI construction, drag, resize, key bindings, focus hacks.

Extracted from chat_overlay_monolith.py lines ~4463-4878.
Plain mixin class; all `self.*` references resolve at runtime via MRO.
"""

import tkinter as tk
from tkinter import filedialog
from overlay.constants import COLORS, LOG, FRANK_IDENTITY, DND_AVAILABLE, DND_FILES
from overlay.bsn.constants import get_workarea_y
from overlay.widgets.modern_button import ModernButton
from overlay.widgets.modern_entry import ModernEntry
from overlay.widgets.file_action_bar import FileActionBar
from overlay.voice.push_to_talk import PushToTalk


class UiMixin:

    # ---- Main UI Build ----

    def _build_ui(self):
        # Main container with border
        outer = tk.Frame(self, bg=COLORS["neon_magenta"], padx=2, pady=2)
        outer.pack(fill="both", expand=True)

        main = tk.Frame(outer, bg=COLORS["bg_main"])
        main.pack(fill="both", expand=True)

        # ═══════════════════════════════════════════════════════════════
        # CUSTOM CYBERPUNK TITLEBAR (44px for easier dragging)
        # ═══════════════════════════════════════════════════════════════
        titlebar = tk.Frame(main, bg=COLORS["bg_elevated"], height=44)
        titlebar.pack(fill="x", side="top")
        titlebar.pack_propagate(False)  # Fixed height

        # Accent line at bottom of titlebar
        accent_line = tk.Frame(titlebar, bg=COLORS["neon_magenta"], height=2)
        accent_line.pack(fill="x", side="bottom")

        # Title area (draggable)
        title_area = tk.Frame(titlebar, bg=COLORS["bg_elevated"])
        title_area.pack(fill="both", expand=True, side="left")

        # Status dot in titlebar (also draggable)
        self.status_dot = tk.Canvas(
            title_area, width=10, height=10,
            bg=COLORS["bg_elevated"], highlightthickness=0
        )
        self.status_dot.pack(side="left", padx=(12, 6), pady=16)

        # Title label
        title_label = tk.Label(
            title_area,
            text="F.R.A.N.K.",
            bg=COLORS["bg_elevated"],
            fg=COLORS["neon_magenta"],
            font=("Consolas", 11, "bold")
        )
        title_label.pack(side="left", pady=12)

        # Subtitle
        subtitle_label = tk.Label(
            title_area,
            text="  // CHAT",
            bg=COLORS["bg_elevated"],
            fg=COLORS["text_muted"],
            font=("Consolas", 9)
        )
        subtitle_label.pack(side="left", pady=12)

        # Window control buttons (right side)
        btn_frame = tk.Frame(titlebar, bg=COLORS["bg_elevated"])
        btn_frame.pack(side="right", padx=4)

        # Minimize button
        min_btn = tk.Label(
            btn_frame,
            text="\u2500",
            bg=COLORS["bg_elevated"],
            fg=COLORS["text_muted"],
            font=("Consolas", 12),
            width=3,
            cursor="hand2"
        )
        min_btn.pack(side="left", padx=2)
        min_btn.bind("<Button-1>", lambda e: self._toggle_hide())  # Minimize to tray
        min_btn.bind("<Enter>", lambda e: min_btn.configure(fg=COLORS["neon_cyan"], bg=COLORS["bg_highlight"]))
        min_btn.bind("<Leave>", lambda e: min_btn.configure(fg=COLORS["text_muted"], bg=COLORS["bg_elevated"]))

        # Close button
        close_btn = tk.Label(
            btn_frame,
            text="\u2715",
            bg=COLORS["bg_elevated"],
            fg=COLORS["text_muted"],
            font=("Consolas", 12),
            width=3,
            cursor="hand2"
        )
        close_btn.pack(side="left", padx=2)
        close_btn.bind("<Button-1>", lambda e: self.destroy())
        close_btn.bind("<Enter>", lambda e: close_btn.configure(fg="#ffffff", bg=COLORS["error"]))
        close_btn.bind("<Leave>", lambda e: close_btn.configure(fg=COLORS["text_muted"], bg=COLORS["bg_elevated"]))

        # Drag bindings for moving window (expanded to more widgets)
        for widget in [titlebar, title_area, title_label, subtitle_label,
                       self.status_dot, accent_line]:
            widget.bind("<Button-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._on_drag)
            widget.bind("<ButtonRelease-1>", self._end_drag)

        # Draw static status dot (animation starts after window reveal)
        self.status_dot.create_oval(1, 1, 7, 7, fill=COLORS["neon_cyan"], outline="")

        # Hidden status label for compatibility
        self.status_label = tk.Label(main, text="", bg=COLORS["bg_main"])
        # Don't pack - keep hidden

        # Chat area with scrollbar
        chat_container = tk.Frame(main, bg=COLORS["bg_chat"])
        chat_container.pack(fill="both", expand=True, padx=10, pady=5)

        # Canvas for scrolling
        self.chat_canvas = tk.Canvas(
            chat_container,
            bg=COLORS["bg_chat"],
            highlightthickness=0,
            relief="flat"
        )

        # Scrollbar (thin, neon-colored)
        scrollbar = tk.Scrollbar(
            chat_container,
            orient="vertical",
            command=self.chat_canvas.yview,
            bg=COLORS["neon_magenta"],
            troughcolor=COLORS["bg_deep"],
            activebackground=COLORS["neon_cyan"],
            width=6  # Thin scrollbar
        )

        self.chat_canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self.chat_canvas.pack(side="left", fill="both", expand=True)

        # Frame inside canvas for messages
        self.messages_frame = tk.Frame(self.chat_canvas, bg=COLORS["bg_chat"])
        self.canvas_window = self.chat_canvas.create_window(
            (0, 0),
            window=self.messages_frame,
            anchor="nw"
        )

        # Bind resize
        self.messages_frame.bind("<Configure>", self._on_frame_configure)
        self.chat_canvas.bind("<Configure>", self._on_canvas_configure)

        # Mouse wheel scrolling
        self.chat_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.chat_canvas.bind_all("<Button-4>", self._on_mousewheel)
        self.chat_canvas.bind_all("<Button-5>", self._on_mousewheel)

        # Search results area (initially hidden)
        self.results_container = tk.Frame(main, bg=COLORS["bg_main"])

        # File actions area (initially hidden)
        self.file_actions_container = tk.Frame(main, bg=COLORS["bg_main"])

        # Input area
        input_area = tk.Frame(main, bg=COLORS["bg_main"])
        input_area.pack(fill="x", padx=15, pady=10)

        # Attach button (visible border with + symbol)
        self.attach_btn = ModernButton(
            input_area,
            text="+",
            command=self._on_attach,
            width=40,
            height=40,
            bg=COLORS["accent"],  # Magenta border - visible!
            hover_bg=COLORS["accent_hover"],
            corner_radius=0
        )
        self.attach_btn.pack(side="left", padx=(0, 8))

        # Push-to-Talk microphone button (visible border)
        self.ptt_btn = ModernButton(
            input_area,
            text="MIC",  # Text instead of emoji for better visibility
            command=lambda: None,  # We use bind for press/release
            width=40,
            height=40,
            bg=COLORS["neon_cyan"],  # Cyan border - visible!
            hover_bg="#ff4444",  # Red when hovering (recording indicator)
            corner_radius=0
        )
        self.ptt_btn.pack(side="left", padx=(0, 8))

        # PTT bindings (press and hold)
        self.ptt_btn.bind("<ButtonPress-1>", self._on_ptt_press)
        self.ptt_btn.bind("<ButtonRelease-1>", self._on_ptt_release)

        # Initialize Push-to-Talk
        self.ptt = PushToTalk(callback=self._on_ptt_result, error_callback=self._on_ptt_error)
        self._ptt_recording = False

        # Entry (ChatGPT-style growing text input)
        self.entry = ModernEntry(input_area)
        self.entry.pack(side="left", fill="both", expand=True, padx=(0, 8))
        # NOTE: Don't auto-focus - wait for user to click on overlay
        # This prevents stealing focus from other applications

        # Send button
        self.send_btn = ModernButton(
            input_area,
            text="\u25b6",
            command=self._on_send,
            width=40,
            height=40,
            bg=COLORS["neon_cyan"],
            hover_bg=COLORS["accent"],
            corner_radius=0
        )
        self.send_btn.pack(side="right")

        # DnD support
        if DND_AVAILABLE:
            try:
                self.entry.text.drop_target_register(DND_FILES)
                self.entry.text.dnd_bind("<<Drop>>", self._on_drop)
                self.drop_target_register(DND_FILES)
                self.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass

    # ---- Canvas / scroll helpers ----

    def _on_frame_configure(self, event):
        self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.chat_canvas.itemconfig(self.canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        try:
            if event.num == 4:
                self.chat_canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                self.chat_canvas.yview_scroll(1, "units")
            else:
                self.chat_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass  # Canvas may be temporarily unavailable during widget rebuild

    # ---- Drag ----

    def _start_drag(self, event):
        """Start dragging the window."""
        self._drag_start_x = event.x
        self._drag_start_y = event.y
        self._dragging = True  # Flag to block focus hack during drag
        # Visual feedback: change cursor to move cursor
        self.configure(cursor="fleur")

    def _on_drag(self, event):
        """Handle window dragging with screen boundary enforcement."""
        if not getattr(self, '_dragging', False):
            return

        x = self.winfo_x() + (event.x - self._drag_start_x)
        y = self.winfo_y() + (event.y - self._drag_start_y)

        # Get screen dimensions and window size
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        win_w = self.winfo_width()
        win_h = self.winfo_height()

        # Enforce strict boundaries -- titlebar with controls must ALWAYS
        # remain fully on-screen so the user can never lose the window.
        # Horizontal: entire window width stays on screen
        x = max(0, min(x, screen_w - win_w))
        # Vertical: NEVER above GNOME panel (dynamic from workarea)
        min_y = get_workarea_y()
        y = max(min_y, min(y, screen_h - 44))

        self.geometry(f"+{x}+{y}")

    def _end_drag(self, event):
        """End dragging the window."""
        self._dragging = False
        # Restore default cursor
        self.configure(cursor="")

    # ---- Resize functionality for frameless window ----

    def _init_resize(self):
        """Initialize resize handling for frameless window."""
        self._resize_edge = None
        self._resize_start_x = 0
        self._resize_start_y = 0
        self._resize_start_width = 0
        self._resize_start_height = 0
        self._resize_start_win_x = 0
        self._resize_start_win_y = 0

        # Bind mouse motion for cursor changes at edges
        self.bind("<Motion>", self._on_motion_resize_cursor)
        self.bind("<ButtonPress-1>", self._on_resize_start, add="+")
        self.bind("<B1-Motion>", self._on_resize_drag, add="+")
        self.bind("<ButtonRelease-1>", self._on_resize_end, add="+")

    def _get_resize_edge(self, event):
        """Determine which edge/corner the mouse is near.

        Uses screen-relative coordinates (event.x_root) converted to
        window-relative, so edge detection works regardless of which
        child widget received the event.
        """
        x = event.x_root - self.winfo_rootx()
        y = event.y_root - self.winfo_rooty()
        w = self.winfo_width()
        h = self.winfo_height()
        edge_size = 12  # pixels from edge to trigger resize
        top_edge_size = 6  # smaller at top to avoid conflict with titlebar drag

        edge = ""
        if y < top_edge_size:
            edge += "n"
        elif y > h - edge_size:
            edge += "s"
        if x < edge_size:
            edge += "w"
        elif x > w - edge_size:
            edge += "e"

        return edge if edge else None

    def _on_motion_resize_cursor(self, event):
        """Change cursor when near edges."""
        edge = self._get_resize_edge(event)

        cursors = {
            "n": "top_side", "s": "bottom_side",
            "e": "right_side", "w": "left_side",
            "ne": "top_right_corner", "nw": "top_left_corner",
            "se": "bottom_right_corner", "sw": "bottom_left_corner"
        }

        if edge and edge in cursors:
            self.configure(cursor=cursors[edge])
        else:
            self.configure(cursor="")

    def _on_resize_start(self, event):
        """Start resize if mouse is on edge."""
        # Don't start resize if dragging is active
        if getattr(self, '_dragging', False):
            return
        self._resize_edge = self._get_resize_edge(event)
        if self._resize_edge:
            self._resize_start_x = event.x_root
            self._resize_start_y = event.y_root
            self._resize_start_width = self.winfo_width()
            self._resize_start_height = self.winfo_height()
            self._resize_start_win_x = self.winfo_x()
            self._resize_start_win_y = self.winfo_y()

    def _on_resize_drag(self, event):
        """Handle resize drag."""
        if not self._resize_edge:
            return

        dx = event.x_root - self._resize_start_x
        dy = event.y_root - self._resize_start_y

        new_w = self._resize_start_width
        new_h = self._resize_start_height
        new_x = self._resize_start_win_x
        new_y = self._resize_start_win_y

        min_w, min_h = self.minsize()

        if "e" in self._resize_edge:
            new_w = max(min_w, self._resize_start_width + dx)
        if "w" in self._resize_edge:
            new_w = max(min_w, self._resize_start_width - dx)
            if new_w > min_w:
                new_x = self._resize_start_win_x + dx
        if "s" in self._resize_edge:
            new_h = max(min_h, self._resize_start_height + dy)
        if "n" in self._resize_edge:
            new_h = max(min_h, self._resize_start_height - dy)
            if new_h > min_h:
                new_y = self._resize_start_win_y + dy

        # Enforce: NEVER above GNOME panel
        min_y = get_workarea_y()
        if new_y < min_y:
            # Shrink height instead of going above panel
            if "n" in self._resize_edge:
                new_h -= (min_y - new_y)
                new_h = max(min_h, new_h)
            new_y = min_y

        self.geometry(f"{int(new_w)}x{int(new_h)}+{int(new_x)}+{int(new_y)}")

    def _on_resize_end(self, event):
        """End resize."""
        self._resize_edge = None

    # ---- Key bindings ----

    def _bind_keys(self):
        self.entry.bind("<Return>", lambda e: self._on_send())
        # NOTE: ESC does NOT close/hide the overlay - only manual X/- buttons do
        # NOTE: Ctrl+Q also removed - overlay is closed only via titlebar buttons

    # ---- Focus hacks ----

    def _on_window_click_focus(self, event):
        """Focus the overlay when the user clicks on it.

        With WM-managed windows (no overrideredirect), the WM handles focus
        naturally. We just need to ensure the entry widget gets focus.
        """
        if getattr(self, '_dragging', False):
            return
        try:
            self.lift()
            self.focus_force()
            if hasattr(self, 'entry') and hasattr(self.entry, 'text'):
                self.entry.text.focus_force()
        except Exception:
            pass

    def _toggle_hide(self):
        if getattr(self, '_toggle_in_progress', False):
            return
        self._toggle_in_progress = True
        try:
            if getattr(self, '_overlay_minimized', False):
                self._show_overlay()
            else:
                self._minimize_overlay()
        finally:
            self.after(300, self._clear_toggle_lock)

    def _clear_toggle_lock(self):
        self._toggle_in_progress = False

    def _minimize_overlay(self):
        """Minimize overlay to taskbar. Restore by clicking taskbar icon or tray."""
        self._saved_geometry = self.geometry()
        self._overlay_minimized = True
        self._overlay_hidden = True
        self.iconify()
        LOG.info("Overlay minimized (geometry saved: %s)", self._saved_geometry)

    def _show_overlay(self):
        """Restore overlay to visible state (from iconify or any hidden state)."""
        LOG.info("_show_overlay called (minimized=%s, hidden=%s)",
                 getattr(self, '_overlay_minimized', '?'),
                 getattr(self, '_overlay_hidden', '?'))

        # Set flags FIRST to prevent re-entrant calls from pollers
        self._overlay_minimized = False
        self._overlay_hidden = False

        # Clear user-closed signal — if user restores overlay, they want it running
        try:
            from overlay.mixins.lifecycle_mixin import USER_CLOSED_SIGNAL
            USER_CLOSED_SIGNAL.unlink(missing_ok=True)
        except Exception:
            pass

        # Restore geometry if available
        if hasattr(self, '_saved_geometry') and self._saved_geometry:
            self.geometry(self._saved_geometry)

        # deiconify restores from iconified (minimized) state
        self.deiconify()

        if not getattr(self, '_fullscreen_yielded', False):
            self.attributes("-topmost", True)
        self.attributes("-alpha", 0.95)
        self.lift()
        self.update_idletasks()

        # Enforce panel boundary after restore
        if hasattr(self, '_enforce_panel_boundary'):
            self.after(50, self._enforce_panel_boundary)
        try:
            self.entry.focus_set()
        except Exception:
            pass
        LOG.info("Overlay restored")

    # ---- File actions / results clearing ----

    def _hide_file_actions(self):
        for child in list(self.file_actions_container.winfo_children()):
            child.destroy()
        self.file_actions_container.pack_forget()

    def _clear_results(self):
        for child in list(self.results_container.winfo_children()):
            child.destroy()
        self.results_container.pack_forget()
