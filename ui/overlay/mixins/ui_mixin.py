"""UiMixin -- UI construction, drag, resize, key bindings, focus hacks.

Extracted from chat_overlay_monolith.py lines ~4463-4878.
Plain mixin class; all `self.*` references resolve at runtime via MRO.
"""

import os
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

        # Window control buttons + panel toggles (right side, single frame)
        btn_frame = tk.Frame(titlebar, bg=COLORS["bg_elevated"])
        btn_frame.pack(side="right", padx=4)

        # L/A panel buttons go first (packed left inside btn_frame)
        self._panel_btns = tk.Frame(btn_frame, bg=COLORS["bg_elevated"])
        self._panel_btns.pack(side="left", padx=(0, 6))

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
        chat_container.pack(fill="both", expand=True, padx=8, pady=3)

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

        # Input area (saved as self for pack ordering in results_container)
        self._input_area = tk.Frame(main, bg=COLORS["bg_main"])
        self._input_area.pack(fill="x", padx=10, pady=6)

        # Attach button (visible border with + symbol)
        self.attach_btn = ModernButton(
            self._input_area,
            text="+",
            command=self._on_attach,
            width=34,
            height=34,
            bg=COLORS["accent"],  # Magenta border - visible!
            hover_bg=COLORS["accent_hover"],
            corner_radius=0
        )
        self.attach_btn.pack(side="left", padx=(0, 6))

        # Push-to-Talk microphone button (visible border)
        self.ptt_btn = ModernButton(
            self._input_area,
            text="MIC",  # Text instead of emoji for better visibility
            command=lambda: None,  # We use bind for press/release
            width=34,
            height=34,
            bg=COLORS["neon_cyan"],  # Cyan border - visible!
            hover_bg="#ff4444",  # Red when hovering (recording indicator)
            corner_radius=0
        )
        self.ptt_btn.pack(side="left", padx=(0, 6))

        # PTT bindings (press and hold)
        self.ptt_btn.bind("<ButtonPress-1>", self._on_ptt_press)
        self.ptt_btn.bind("<ButtonRelease-1>", self._on_ptt_release)

        # Initialize Push-to-Talk
        self.ptt = PushToTalk(callback=self._on_ptt_result, error_callback=self._on_ptt_error)
        self._ptt_recording = False

        # Entry (ChatGPT-style growing text input)
        self.entry = ModernEntry(self._input_area)
        self.entry.pack(side="left", fill="both", expand=True, padx=(0, 6))
        # NOTE: Don't auto-focus - wait for user to click on overlay
        # This prevents stealing focus from other applications

        # ═══════════════════════════════════════════════════════════════
        # STATUS BAR (bottom, single compact row: dots + hw stats)
        # ═══════════════════════════════════════════════════════════════
        self._status_bar = tk.Frame(main, bg=COLORS["bg_deep"])
        self._status_bar.pack(side="bottom", fill="x")

        # Single row: service dots (left) + hardware stats (right)
        status_row = tk.Frame(self._status_bar, bg=COLORS["bg_deep"])
        status_row.pack(fill="x", padx=3, pady=2)

        self._svc_dots = {}
        for svc_name in ("Core", "LLM", "Tools", "Voice"):
            dot = tk.Label(
                status_row, text="\u25cf",
                font=("Consolas", 6),
                fg=COLORS["text_muted"], bg=COLORS["bg_deep"],
            )
            dot.pack(side="left", padx=1)
            name_lbl = tk.Label(
                status_row, text=svc_name,
                font=("Consolas", 6),
                fg=COLORS["text_muted"], bg=COLORS["bg_deep"],
            )
            name_lbl.pack(side="left", padx=(0, 4))
            self._svc_dots[svc_name] = dot

        self._hw_stats_label = tk.Label(
            status_row, text="",
            font=("Consolas", 6),
            fg=COLORS["neon_green"], bg=COLORS["bg_deep"],
            anchor="e",
        )
        self._hw_stats_label.pack(side="right", padx=1)

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
        # Suppress scrollregion updates during drag AND during post-resize settle
        if getattr(self, '_resize_edge', None) or getattr(self, '_resize_settling', False):
            return
        self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        # During resize drag: batch via after_idle (one reflow per event-loop
        # cycle instead of per-pixel — tight batching, no fixed delay)
        if getattr(self, '_resize_edge', None):
            self._pending_canvas_w = event.width
            if not getattr(self, '_canvas_reflow_pending', False):
                self._canvas_reflow_pending = True
                self.after_idle(self._do_canvas_reflow)
            return
        self.chat_canvas.itemconfig(self.canvas_window, width=event.width)

    def _do_canvas_reflow(self):
        """Batched canvas width sync during resize drag."""
        self._canvas_reflow_pending = False
        w = getattr(self, '_pending_canvas_w', None)
        if w:
            try:
                self.chat_canvas.itemconfig(self.canvas_window, width=w)
            except Exception:
                pass

    def _on_mousewheel(self, event):
        try:
            # Only scroll the chat if the cursor is actually over the chat area.
            # Other scrollable regions (email list canvas, popups) handle their
            # own scroll events — we must not steal them.
            widget_under = event.widget
            try:
                widget_under = event.widget.winfo_containing(event.x_root, event.y_root)
            except Exception:
                pass
            if widget_under is not None:
                # Walk up the widget tree — if we hit a Canvas that is NOT
                # our chat_canvas, the event belongs to that canvas (e.g.
                # the email list).  Let it through without scrolling chat.
                w = widget_under
                while w is not None:
                    if isinstance(w, tk.Canvas) and w is not self.chat_canvas:
                        return  # belongs to another scrollable area
                    if w is self.chat_canvas:
                        break  # cursor is over our chat — handle it
                    w = getattr(w, 'master', None)
                else:
                    # Widget is not inside chat_canvas at all.
                    # Only scroll chat if it's inside the main overlay window
                    # and not inside results_container (email list).
                    rc = getattr(self, 'results_container', None)
                    if rc is not None:
                        try:
                            wuc = widget_under
                            while wuc is not None:
                                if wuc is rc:
                                    return  # inside email/results list
                                wuc = getattr(wuc, 'master', None)
                        except Exception:
                            pass

            if event.num == 4:
                self.chat_canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                self.chat_canvas.yview_scroll(1, "units")
            else:
                self.chat_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            # If streaming is active, mark that user took manual scroll control
            if getattr(self, '_stream_text', None) is not None:
                self._stream_user_scrolled = True
        except Exception:
            pass  # Canvas may be temporarily unavailable during widget rebuild

    # ---- Resize (east-edge only in DOCK mode) ----

    def _init_resize(self):
        """Initialize east-edge resize for DOCK panel."""
        self._resize_edge = None
        self._resize_settling = False
        self._resize_start_x = 0
        self._resize_start_width = 0
        self._last_strut_update = 0.0

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
            # Cache windows touching right edge for sticky push
            self._sticky_windows = self._find_sticky_windows()
            # Save scroll state: at-bottom flag + bubble anchor for mid-scroll
            self._resize_was_at_bottom = False
            self._resize_scroll_anchor = None
            self._resize_scroll_offset = 0
            try:
                yv = self.chat_canvas.yview()
                if yv[1] >= 0.95:
                    self._resize_was_at_bottom = True
                else:
                    # Anchor the bottom-visible bubble (where user is reading)
                    vp_h = self.chat_canvas.winfo_height()
                    bottom_y = self.chat_canvas.canvasy(vp_h)
                    for child in reversed(self.messages_frame.winfo_children()):
                        cy = child.winfo_y()
                        ch = child.winfo_height()
                        if cy + ch <= bottom_y and ch > 0:
                            self._resize_scroll_anchor = child
                            # How far from bubble-bottom to viewport-bottom
                            self._resize_scroll_offset = bottom_y - (cy + ch)
                            break
            except Exception:
                pass
            # Save desktop icon positions before resize (safety net)
            self._save_desktop_icons()

    def _on_resize_drag(self, event):
        """Handle east-edge width resize with live strut updates.

        Updates strut via ctypes/Xlib (~60fps) so the WM pushes
        windows smoothly as the overlay grows/shrinks.  Also pushes
        windows that touch the old right edge (sticky resize).
        """
        if not self._resize_edge:
            return
        dx = event.x_root - self._resize_start_x
        min_w = self.minsize()[0]
        new_w = max(min_w, self._resize_start_width + dx)
        new_w = min(new_w, BSNConstants.FRANK_MAX_WIDTH)

        dock_x = getattr(self, '_dock_x', 0)
        old_w = self.winfo_width()
        delta = int(new_w) - old_w

        self.geometry(f"{int(new_w)}x{self.winfo_height()}+{dock_x}+{getattr(self, '_workarea_y', 0)}")

        # Live strut update (~60fps via ctypes Xlib, no subprocess)
        import time as _t
        now = _t.time()
        if now - self._last_strut_update > 0.016:
            self._last_strut_update = now
            self._update_strut_for_width(int(new_w))

    def _on_resize_end(self, event):
        """End resize: final strut + flush deferred reflows."""
        if not self._resize_edge:
            return
        self._resize_edge = None
        self._resize_settling = True  # Suppress frame_configure until scroll restored
        # Flush any pending canvas reflow immediately
        self._canvas_reflow_pending = False
        try:
            cw = self.chat_canvas.winfo_width()
            if cw > 1:
                self.chat_canvas.itemconfig(self.canvas_window, width=cw)
        except Exception:
            pass
        # Final authoritative strut update
        self._update_strut()
        # Atomic: remeasure + scrollregion + scroll restore in one step
        self.after(80, self._settle_after_resize)
        # Restore desktop icon positions (safety net for DING)
        self.after(500, self._restore_desktop_icons)
        # Reposition Aura panel if open
        if hasattr(self, '_aura_reposition_panel'):
            self.after(100, self._aura_reposition_panel)
        # Reposition Log panel if open
        if hasattr(self, '_log_reposition_panel'):
            self.after(100, self._log_reposition_panel)

    def _update_strut_for_width(self, overlay_w: int):
        """Update strut reservation for a specific overlay width.

        Called during resize drag to keep the WM informed in real-time.
        """
        try:
            from overlay.dock_hints import set_strut_partial
            xid = getattr(self, '_dock_xid', self.winfo_id())
            dock_x = getattr(self, '_dock_x', 66)
            left_total = dock_x + overlay_w
            mon = get_primary_monitor()
            set_strut_partial(xid, left_total, 0, mon["height"] - 1)
        except Exception:
            pass

    def _find_sticky_windows(self) -> list:
        """Snapshot windows touching Frank's right edge. Called once at resize start.

        Returns [(win_id_decimal, y), ...] for windows whose x is near the strut boundary.
        """
        import subprocess
        dock_x = getattr(self, '_dock_x', 66)
        frank_right = dock_x + self.winfo_width()
        sticky = []
        try:
            result = subprocess.run(
                ["wmctrl", "-lG"], capture_output=True, text=True, timeout=1
            )
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split(None, 8)
                if len(parts) < 8:
                    continue
                if parts[1] == "-1":
                    continue
                title = (parts[7] if len(parts) > 7 else "").lower()
                if "f.r.a.n.k" in title or "neural core" in title or "cybercore" in title:
                    continue
                try:
                    win_x = int(parts[2])
                    win_y = int(parts[3])
                    if abs(win_x - frank_right) < 20:
                        win_id_dec = str(int(parts[0], 16))
                        sticky.append((win_id_dec, win_y))
                except (ValueError, Exception):
                    pass
        except Exception:
            pass
        if sticky:
            LOG.debug(f"BSN: Sticky windows cached: {len(sticky)}")
        return sticky

    def _move_sticky_windows(self, new_right: int):
        """Move cached sticky windows to the new right edge. Fire-and-forget, no blocking."""
        import subprocess
        new_x = new_right + 2
        for win_id_dec, win_y in self._sticky_windows:
            try:
                subprocess.Popen(
                    ["xdotool", "windowmove", win_id_dec, str(new_x), str(win_y)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass

    def _save_desktop_icons(self):
        """Save desktop icon positions via GIO metadata before resize."""
        import subprocess
        self._saved_icon_positions = {}
        try:
            desktop_dir = subprocess.run(
                ["xdg-user-dir", "DESKTOP"],
                capture_output=True, text=True, timeout=2,
            ).stdout.strip()
            if not desktop_dir or not os.path.isdir(desktop_dir):
                return
            for entry in os.listdir(desktop_dir):
                fpath = os.path.join(desktop_dir, entry)
                try:
                    result = subprocess.run(
                        ["gio", "info", "-a", "metadata::nautilus-icon-position", fpath],
                        capture_output=True, text=True, timeout=2,
                    )
                    for line in result.stdout.split("\n"):
                        if "metadata::nautilus-icon-position" in line:
                            pos = line.split(":", 2)[-1].strip()
                            if pos:
                                self._saved_icon_positions[fpath] = pos
                except Exception:
                    pass
        except Exception:
            pass

    def _restore_desktop_icons(self):
        """Restore desktop icon positions via GIO metadata after resize."""
        import subprocess
        saved = getattr(self, '_saved_icon_positions', {})
        if not saved:
            return
        for fpath, pos in saved.items():
            try:
                subprocess.Popen(
                    ["gio", "set", "-t", "string", fpath,
                     "metadata::nautilus-icon-position", pos],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass
        self._saved_icon_positions = {}

    def _settle_after_resize(self):
        """Atomic post-resize: remeasure bubbles + update scrollregion + restore scroll.

        All in one callback so no intermediate frame_configure can cause jumps.
        """
        import tkinter as _tk
        from overlay.widgets.message_bubble import MessageBubble
        try:
            # 1. Remeasure all bubble heights
            for child in self.messages_frame.winfo_children():
                if isinstance(child, MessageBubble):
                    tw = getattr(child, '_text_widget', None)
                    if tw is None:
                        continue
                    try:
                        dl = tw.count("1.0", "end", "displaylines")
                        if dl:
                            h = dl[0] if isinstance(dl, tuple) else dl
                            tw.configure(height=max(1, h))
                    except _tk.TclError:
                        pass

            # 2. Let Tk process the height changes
            self.update_idletasks()

            # 3. Update scrollregion
            self.chat_canvas.configure(
                scrollregion=self.chat_canvas.bbox("all"))

            # 4. Restore scroll position
            if getattr(self, '_resize_was_at_bottom', False):
                # Was at bottom → stay at bottom
                self.chat_canvas.yview_moveto(1.0)
            else:
                # Anchor bottom-visible bubble to same viewport position
                anchor = getattr(self, '_resize_scroll_anchor', None)
                if anchor is not None and anchor.winfo_exists():
                    vp_h = self.chat_canvas.winfo_height()
                    new_cy = anchor.winfo_y()
                    new_ch = anchor.winfo_height()
                    offset = getattr(self, '_resize_scroll_offset', 0)
                    # Target: bubble-bottom + offset = viewport-bottom
                    target_bottom = new_cy + new_ch + offset
                    target_top = max(0, target_bottom - vp_h)
                    bbox = self.chat_canvas.bbox("all")
                    if bbox and bbox[3] > 0:
                        self.chat_canvas.yview_moveto(target_top / bbox[3])
            self._resize_scroll_anchor = None
        except Exception:
            pass
        finally:
            # 5. Un-suppress frame_configure
            self._resize_settling = False

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
        # Hide AURA/Log panels with overlay
        self._panels_were_open = {}
        if getattr(self, "_aura_open", False):
            self._panels_were_open["aura"] = True
            self._aura_close()
        if getattr(self, "_log_open", False):
            self._panels_were_open["log"] = True
            self._log_close()

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

        # Restore panels that were open before minimize
        panels = getattr(self, "_panels_were_open", {})
        if panels.get("aura") and hasattr(self, "_aura_open_panel"):
            self.after(200, self._aura_open_panel)
        elif panels.get("log") and hasattr(self, "_log_open_panel"):
            self.after(200, self._log_open_panel)

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
                "Core":  ["http://127.0.0.1:8088/health"],
                "LLM":   ["http://127.0.0.1:8101/health"],
                "Tools": ["http://127.0.0.1:8096/health"],
            }
            results = {}
            for name, urls in checks.items():
                ok = False
                for url in urls:
                    try:
                        req = urllib.request.Request(url, method="GET")
                        with urllib.request.urlopen(req, timeout=2) as resp:
                            if resp.status == 200:
                                ok = True
                                break
                    except Exception:
                        pass
                results[name] = ok

            # Voice: check Whisper server (PTT backend) via TCP connect
            import socket
            try:
                s = socket.create_connection(("127.0.0.1", 8103), timeout=2)
                s.close()
                results["Voice"] = True
            except Exception:
                results["Voice"] = False

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
