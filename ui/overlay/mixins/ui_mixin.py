"""UiMixin -- UI construction, drag, resize, key bindings, focus hacks.

Extracted from chat_overlay_monolith.py lines ~4463-4878.
Plain mixin class; all `self.*` references resolve at runtime via MRO.
"""

import tkinter as tk
from tkinter import filedialog
from overlay.constants import COLORS, LOG, FRANK_IDENTITY, DND_AVAILABLE, DND_FILES
from overlay.bsn.constants import get_workarea_y, get_primary_monitor, BSNConstants
from overlay.widgets.modern_button import ModernButton
from overlay.widgets.modern_entry import ModernEntry
from overlay.widgets.file_action_bar import FileActionBar
from overlay.voice.push_to_talk import PushToTalk


class UiMixin:

    # ---- Main UI Build ----

    def _build_ui(self):
        # Main container with border
        outer = tk.Frame(self, bg=COLORS["neon_green"], padx=2, pady=2)
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
        accent_line = tk.Frame(titlebar, bg=COLORS["neon_green"], height=2)
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
            fg=COLORS["neon_green"],
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

        # DOCK mode: no drag — panel is fixed. Click to focus instead.
        for widget in [titlebar, title_area, title_label, subtitle_label,
                       self.status_dot, accent_line]:
            widget.bind("<Button-1>", self._on_window_click_focus)

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
            bg=COLORS["neon_green"],
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

        # ═══════════════════════════════════════════════════════════════
        # STATUS BAR (bottom, two rows: services + hardware stats)
        # ═══════════════════════════════════════════════════════════════
        self._status_bar = tk.Frame(main, bg=COLORS["bg_deep"])
        self._status_bar.pack(side="bottom", fill="x")

        # Row 1: Service health dots
        svc_row = tk.Frame(self._status_bar, bg=COLORS["bg_deep"])
        svc_row.pack(fill="x", padx=4, pady=(2, 0))

        self._svc_dots = {}
        for svc_name in ("Core", "LLM", "Tools", "Voice"):
            dot = tk.Label(
                svc_row, text="\u25cf",
                font=("Consolas", 7),
                fg=COLORS["text_muted"], bg=COLORS["bg_deep"],
            )
            dot.pack(side="left", padx=2)
            name_lbl = tk.Label(
                svc_row, text=svc_name,
                font=("Consolas", 7),
                fg=COLORS["text_muted"], bg=COLORS["bg_deep"],
            )
            name_lbl.pack(side="left", padx=(0, 6))
            self._svc_dots[svc_name] = dot

        # Row 2: Hardware stats (own line)
        hw_row = tk.Frame(self._status_bar, bg=COLORS["bg_deep"])
        hw_row.pack(fill="x", padx=4, pady=(0, 2))

        self._hw_stats_label = tk.Label(
            hw_row, text="",
            font=("Consolas", 7),
            fg=COLORS["neon_green"], bg=COLORS["bg_deep"],
            anchor="w",
        )
        self._hw_stats_label.pack(side="left", padx=2)

        # Start health polling after UI is up
        self.after(5000, self._poll_service_health)
        # Start hardware stats polling
        self.after(3000, self._poll_hw_stats)

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
        # Suppress during active drag — the geometry change already resizes the
        # canvas visually. Both canvas and messages_frame share bg_chat color so
        # no black gap is visible. Width sync happens once in _on_resize_end.
        if getattr(self, '_resize_edge', None):
            return
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

    # ---- Resize (east-edge only in DOCK mode) ----

    def _init_resize(self):
        """Initialize east-edge resize for DOCK panel."""
        self._resize_edge = None
        self._resize_start_x = 0
        self._resize_start_width = 0
        self._last_strut_update = 0.0
        self._last_canvas_resize = 0.0

        self.bind("<Motion>", self._on_motion_resize_cursor)
        self.bind("<ButtonPress-1>", self._on_resize_start, add="+")
        self.bind("<B1-Motion>", self._on_resize_drag, add="+")
        self.bind("<ButtonRelease-1>", self._on_resize_end, add="+")

    def _get_resize_edge(self, event):
        """Only detect east edge for width-only resize."""
        x = event.x_root - self.winfo_rootx()
        w = self.winfo_width()
        if x > w - 12:
            return "e"
        return None

    def _on_motion_resize_cursor(self, event):
        """Change cursor when near east edge."""
        edge = self._get_resize_edge(event)
        if edge == "e":
            self.configure(cursor="right_side")
        else:
            self.configure(cursor="")

    def _on_resize_start(self, event):
        """Start resize if mouse is on east edge."""
        self._resize_edge = self._get_resize_edge(event)
        if self._resize_edge:
            self._resize_start_x = event.x_root
            self._resize_start_width = self.winfo_width()

    def _on_resize_drag(self, event):
        """Handle east-edge width resize with live strut update.

        Position and height stay fixed. Adjacent maximized windows
        resize smoothly as the strut changes during drag.
        """
        if not self._resize_edge:
            return
        dx = event.x_root - self._resize_start_x
        min_w = self.minsize()[0]
        new_w = max(min_w, self._resize_start_width + dx)
        # Enforce max width (leave room for apps)
        new_w = min(new_w, BSNConstants.FRANK_MAX_WIDTH)
        self.geometry(f"{int(new_w)}x{self.winfo_height()}+{getattr(self, '_dock_x', 0)}+{getattr(self, '_workarea_y', 0)}")
        # Live strut update — maximized windows adjust in real-time
        # Throttled to ~20fps to avoid subprocess lag
        import time as _t
        now = _t.time()
        if now - self._last_strut_update > 0.05 and hasattr(self, '_update_strut'):
            self._last_strut_update = now
            self._update_strut()

    def _on_resize_end(self, event):
        """End resize and finalize strut + re-layout chat content."""
        if self._resize_edge == "e":
            if hasattr(self, '_update_strut'):
                self._update_strut()
        # Clear resize flag FIRST so _on_canvas_configure is unblocked,
        # then trigger the width sync via a deferred configure event.
        self._resize_edge = None
        try:
            cw = self.chat_canvas.winfo_width()
            self.chat_canvas.itemconfig(self.canvas_window, width=cw)
        except Exception:
            pass
        # Scrollregion update after bubble remeasurements settle (150ms debounce)
        self.after(300, self._finalize_resize_layout)

    def _finalize_resize_layout(self):
        """Deferred scrollregion update after resize settles."""
        try:
            self.chat_canvas.configure(
                scrollregion=self.chat_canvas.bbox("all"))
            self._smart_scroll()
        except Exception:
            pass

    # ---- Key bindings ----

    def _bind_keys(self):
        self.entry.bind("<Return>", lambda e: self._on_send())
        # NOTE: ESC does NOT close/hide the overlay - only manual X/- buttons do
        # NOTE: Ctrl+Q also removed - overlay is closed only via titlebar buttons

    # ---- Focus hacks ----

    def _on_window_click_focus(self, event=None):
        """Focus the DOCK overlay when clicked.

        DOCK windows never receive automatic focus from the WM.
        We must explicitly grab focus on any click inside the window.
        """
        try:
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
        """Hide DOCK overlay. Restore via tray icon."""
        self._saved_geometry = self.geometry()
        self._overlay_minimized = True
        self._overlay_hidden = True
        # Clear strut so other windows can use the space
        try:
            from overlay.dock_hints import clear_strut
            xid = getattr(self, '_dock_xid', self.winfo_id())
            clear_strut(xid)
        except Exception:
            pass
        self.withdraw()
        LOG.info("Overlay hidden (strut cleared, geometry saved: %s)", self._saved_geometry)

    def _show_overlay(self):
        """Restore DOCK overlay to visible state."""
        LOG.info("_show_overlay called (minimized=%s, hidden=%s)",
                 getattr(self, '_overlay_minimized', '?'),
                 getattr(self, '_overlay_hidden', '?'))

        self._overlay_minimized = False
        self._overlay_hidden = False

        try:
            from overlay.mixins.lifecycle_mixin import USER_CLOSED_SIGNAL
            USER_CLOSED_SIGNAL.unlink(missing_ok=True)
        except Exception:
            pass

        if hasattr(self, '_saved_geometry') and self._saved_geometry:
            self.geometry(self._saved_geometry)

        self.deiconify()
        self.attributes("-alpha", 0.95)
        self.update_idletasks()

        # Restore strut reservation
        if hasattr(self, '_update_strut'):
            self._update_strut()
        try:
            self.entry.focus_set()
        except Exception:
            pass
        LOG.info("Overlay restored (strut re-applied)")

    # ---- File actions / results clearing ----

    def _hide_file_actions(self):
        for child in list(self.file_actions_container.winfo_children()):
            child.destroy()
        self.file_actions_container.pack_forget()

    def _clear_results(self):
        for child in list(self.results_container.winfo_children()):
            child.destroy()
        self.results_container.pack_forget()

    # ---- Status Bar Health Polling ----

    def _poll_service_health(self):
        """Check service health and update status bar dots. Runs on IO thread."""
        import threading

        def _check():
            import urllib.request
            checks = {
                "Core":  "http://127.0.0.1:8088/health",
                "LLM":   "http://127.0.0.1:8101/health",
                "Tools": "http://127.0.0.1:8096/health",
                "Voice": "http://127.0.0.1:8197/health",
            }
            results = {}
            for name, url in checks.items():
                try:
                    req = urllib.request.Request(url, method="GET")
                    with urllib.request.urlopen(req, timeout=2) as resp:
                        results[name] = resp.status == 200
                except Exception:
                    results[name] = False

            # Update UI on main thread
            def _update():
                if not hasattr(self, '_svc_dots'):
                    return
                for name, ok in results.items():
                    if name in self._svc_dots:
                        color = COLORS["neon_cyan"] if ok else COLORS["error"]
                        try:
                            self._svc_dots[name].configure(fg=color)
                        except Exception:
                            pass
            try:
                self.after(0, _update)
            except Exception:
                pass

        threading.Thread(target=_check, daemon=True).start()
        # Re-poll every 30 seconds
        self.after(30000, self._poll_service_health)

    def _poll_hw_stats(self):
        """Poll CPU/GPU temps, usage, and RAM. Update status bar."""
        import threading

        def _read():
            import psutil
            parts = []
            try:
                # CPU temp (k10temp or coretemp)
                temps = psutil.sensors_temperatures()
                cpu_t = None
                for chip in ("k10temp", "coretemp", "zenpower"):
                    if chip in temps and temps[chip]:
                        cpu_t = int(temps[chip][0].current)
                        break
                if cpu_t is not None:
                    parts.append(f"CPU:{cpu_t}°C")
            except Exception:
                pass
            try:
                # GPU temp (amdgpu)
                temps = psutil.sensors_temperatures()
                gpu_t = None
                for chip in ("amdgpu", "nvidia", "radeon"):
                    if chip in temps and temps[chip]:
                        gpu_t = int(temps[chip][0].current)
                        break
                if gpu_t is not None:
                    parts.append(f"GPU:{gpu_t}°C")
            except Exception:
                pass
            try:
                parts.append(f"CPU:{psutil.cpu_percent(interval=0.1):.0f}%")
            except Exception:
                pass
            try:
                # GPU usage via sysfs (AMD/Intel)
                import glob
                for p in glob.glob("/sys/class/drm/card*/device/gpu_busy_percent"):
                    gpu_pct = int(open(p).read().strip())
                    parts.append(f"GPU:{gpu_pct}%")
                    break
            except Exception:
                pass
            try:
                mem = psutil.virtual_memory()
                parts.append(f"RAM:{mem.percent:.0f}%")
            except Exception:
                pass

            text = " | ".join(parts)

            def _update():
                try:
                    self._hw_stats_label.configure(text=text)
                except Exception:
                    pass
            try:
                self.after(0, _update)
            except Exception:
                pass

        threading.Thread(target=_read, daemon=True).start()
        self.after(5000, self._poll_hw_stats)
