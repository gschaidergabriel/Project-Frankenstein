"""LogPanelMixin — Slide-out daemon activity log panel.

Adds an "L" toggle button next to the AURA "A" button and a floating
Toplevel panel (override-redirect) that slides out from the overlay's
right edge.  Idle thoughts, entity messages, and dream notifications
are routed here instead of the main chat.
"""

from __future__ import annotations

import json
import logging
import math
import time
import tkinter as tk
from pathlib import Path
from typing import Dict, List, Optional

LOG = logging.getLogger("frank_overlay")

_LOG_FILE = Path.home() / ".local/share/frank/log_panel.json"
_MAX_PERSISTENT = 30

# Categories routed to this panel (must match notification_mixin)
LOG_CATEGORIES = frozenset({
    "consciousness", "dream", "entity",
    "therapist", "mirror", "atlas", "muse",
})

_LOG_PANEL_WIDTH = 340   # BSNConstants.FRANK_MIN_WIDTH
_SLIDE_OPEN_MS = 300
_SLIDE_CLOSE_MS = 200
_MAX_LOG_ENTRIES = 200

# Icon map (same icons as notification_mixin)
_LOG_ICONS: Dict[str, str] = {
    "consciousness": "\U0001F9E0",
    "dream":         "\U0001F4AD",
    "entity":        "\U0001F464",
    "therapist":     "\U0001F49A",
    "mirror":        "\u2694\uFE0F",
    "atlas":         "\U0001F9ED",
    "muse":          "\U0001F3A8",
}

# Category → left-stripe color
_CAT_COLORS: Dict[str, str] = {
    "consciousness": "#00fff9",
    "dream":         "#B34DFF",
    "entity":        "#FF00CC",
    "therapist":     "#00ff88",
    "mirror":        "#FFD900",
    "atlas":         "#00B3FF",
    "muse":          "#FF8000",
}

# Button styling (matches AURA button)
_BTN_BG = "#0d0d0d"
_BTN_BG_HOVER = "#1a1a1a"
_BTN_BORDER_CLR = "#00cc44"
_BTN_BORDER_HOVER = "#00fff9"

_BG = "#0D1117"
_BG_HEADER = "#141414"


class LogPanelMixin:
    """Mixin adding a slide-out log panel for daemon activity."""

    # ── Init ─────────────────────────────────────────────────────

    def _init_log_panel(self):
        self._log_open: bool = False
        self._log_animating: bool = False
        self._log_win: Optional[tk.Toplevel] = None
        self._log_entries: List[Dict] = self._log_load_persistent()
        self._log_unread_count: int = 0
        self._log_canvas: Optional[tk.Canvas] = None
        self._log_messages_frame: Optional[tk.Frame] = None

        self._log_create_toggle_button()
        self.bind("<Configure>", self._log_on_overlay_configure, add="+")

    # ── Toggle Button — 22×22 · Cyan "L" ────────────────────────

    def _log_create_toggle_button(self):
        s = 22
        parent = getattr(self, "_panel_btns", self)
        btn = tk.Canvas(
            parent, width=s, height=s,
            bg=_BTN_BG, highlightthickness=0, cursor="hand2",
        )
        btn.create_rectangle(
            0, 0, s - 1, s - 1,
            outline=_BTN_BORDER_CLR, width=1, tags="border",
        )
        self._log_btn_text_id = btn.create_text(
            s // 2, s // 2,
            text="L", fill="#00fff9",
            font=("Consolas", 11, "bold"),
        )
        # Unread badge (top-right corner, initially hidden)
        self._log_btn_badge_id = btn.create_text(
            s - 2, 2, text="", fill="#ff3333",
            font=("Consolas", 7, "bold"), anchor="ne",
        )
        btn.bind("<Button-1>", lambda _: self._log_toggle())
        btn.bind("<Enter>", self._log_btn_enter)
        btn.bind("<Leave>", self._log_btn_leave)
        btn.pack(side="right", padx=(6, 0), pady=2)
        self._log_btn = btn

    def _log_btn_enter(self, _ev):
        self._log_btn.configure(bg=_BTN_BG_HOVER)
        self._log_btn.itemconfigure("border", outline=_BTN_BORDER_HOVER)

    def _log_btn_leave(self, _ev):
        self._log_btn.configure(bg=_BTN_BG)
        self._log_btn.itemconfigure("border", outline=_BTN_BORDER_CLR)

    # ── Toggle / Open / Close ────────────────────────────────────

    def _log_toggle(self):
        if self._log_animating:
            return
        if self._log_open:
            self._log_close()
        else:
            self._log_open_panel()

    def _log_open_panel(self):
        # Mutual exclusion: close AURA if open
        if getattr(self, "_aura_open", False) and hasattr(self, "_aura_close"):
            self._aura_close()

        panel_h = self.winfo_height()

        win = tk.Toplevel(self)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="#00cc44")

        ox = self.winfo_rootx() + self.winfo_width()
        oy = self.winfo_rooty()
        win.geometry(f"1x{panel_h}+{ox}+{oy}")
        win.update_idletasks()

        self._log_win = win
        self._log_build_panel(win, panel_h)

        # Animate slide open
        self._log_animating = True
        self._log_animate_open(_LOG_PANEL_WIDTH, time.monotonic(), _SLIDE_OPEN_MS)

        # Clear unread badge
        self._log_unread_count = 0
        self._log_update_badge()

    def _log_animate_open(self, target_w, t_start, duration_ms):
        if not self._log_win or not self._log_win.winfo_exists():
            self._log_animating = False
            return
        elapsed = (time.monotonic() - t_start) * 1000
        if elapsed >= duration_ms:
            self._log_set_panel_geom(target_w)
            self._log_animating = False
            self._log_open = True
            return
        t = elapsed / duration_ms
        ease = 1 - (1 - t) ** 3  # cubic ease-out
        w = max(1, int(target_w * ease))
        self._log_set_panel_geom(w)
        self.after(16, lambda: self._log_animate_open(target_w, t_start, duration_ms))

    def _log_close(self):
        self._log_animating = True
        self._log_animate_close(
            _LOG_PANEL_WIDTH, time.monotonic(), _SLIDE_CLOSE_MS,
        )

    def _log_animate_close(self, start_w, t_start, duration_ms):
        if not self._log_win or not self._log_win.winfo_exists():
            self._log_animating = False
            self._log_open = False
            return
        elapsed = (time.monotonic() - t_start) * 1000
        if elapsed >= duration_ms:
            self._log_close_done()
            return
        t = elapsed / duration_ms
        ease = t * t  # quadratic ease-in
        w = max(1, int(start_w * (1 - ease)))
        self._log_set_panel_geom(w)
        self.after(16, lambda: self._log_animate_close(start_w, t_start, duration_ms))

    def _log_close_done(self):
        self._log_animating = False
        self._log_open = False
        if self._log_win and self._log_win.winfo_exists():
            self._log_win.destroy()
        self._log_win = None
        self._log_canvas = None
        self._log_messages_frame = None

    def _log_set_panel_geom(self, w):
        try:
            ox = self.winfo_rootx() + self.winfo_width()
            oy = self.winfo_rooty()
            h = self.winfo_height()
            self._log_win.geometry(f"{w}x{h}+{ox}+{oy}")
        except Exception:
            pass

    def _log_on_overlay_configure(self, _event):
        if self._log_open and self._log_win and not self._log_animating:
            try:
                self._log_set_panel_geom(_LOG_PANEL_WIDTH)
            except Exception:
                pass

    def _log_reposition_panel(self):
        if self._log_open and self._log_win and not self._log_animating:
            self._log_set_panel_geom(_LOG_PANEL_WIDTH)

    # ── Panel UI ─────────────────────────────────────────────────

    def _log_build_panel(self, win, panel_h):
        inner = tk.Frame(win, bg=_BG)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        # Header
        header = tk.Frame(inner, bg=_BG_HEADER, height=36)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        tk.Label(
            header, text="LOG", bg=_BG_HEADER, fg="#00fff9",
            font=("Consolas", 10, "bold"),
        ).pack(side="left", padx=8, pady=8)
        tk.Label(
            header, text="// DAEMON ACTIVITY", bg=_BG_HEADER, fg="#505050",
            font=("Consolas", 7),
        ).pack(side="left", pady=8)

        # Clear button
        clear_btn = tk.Label(
            header, text="CLR", bg=_BG_HEADER, fg="#505050",
            font=("Consolas", 8), cursor="hand2",
        )
        clear_btn.pack(side="right", padx=8)
        clear_btn.bind("<Button-1>", lambda _: self._log_clear_entries())
        clear_btn.bind("<Enter>", lambda e: clear_btn.configure(fg="#ff4444"))
        clear_btn.bind("<Leave>", lambda e: clear_btn.configure(fg="#505050"))

        # Accent line
        tk.Frame(inner, bg="#00cc44", height=1).pack(fill="x")

        # Scrollable log area
        canvas = tk.Canvas(inner, bg=_BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(
            inner, orient="vertical", command=canvas.yview,
            bg="#00cc44", troughcolor="#060606",
            activebackground="#00fff9", width=4,
        )
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        messages_frame = tk.Frame(canvas, bg=_BG)
        canvas_window = canvas.create_window(
            (0, 0), window=messages_frame, anchor="nw",
        )
        self._log_canvas = canvas
        self._log_messages_frame = messages_frame
        self._log_canvas_window = canvas_window

        messages_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(canvas_window, width=e.width),
        )

        # Mouse wheel — return "break" to prevent propagation to chat
        def _log_scroll_up(e):
            canvas.yview_scroll(-2, "units")
            return "break"
        def _log_scroll_down(e):
            canvas.yview_scroll(2, "units")
            return "break"
        for widget in (canvas, messages_frame, win):
            widget.bind("<Button-4>", _log_scroll_up)
            widget.bind("<Button-5>", _log_scroll_down)

        # Render existing entries
        for entry in self._log_entries:
            self._log_render_entry(entry)

        canvas.update_idletasks()
        canvas.yview_moveto(1.0)

    # ── Entry Rendering ──────────────────────────────────────────

    def _log_render_entry(self, entry: Dict):
        if not self._log_messages_frame or not self._log_messages_frame.winfo_exists():
            return

        frame = tk.Frame(self._log_messages_frame, bg=_BG)
        frame.pack(fill="x", padx=4, pady=1)

        # Category color stripe (2px left)
        stripe_color = _CAT_COLORS.get(entry.get("category", ""), "#505050")
        tk.Frame(frame, bg=stripe_color, width=2).pack(side="left", fill="y")

        content = tk.Frame(frame, bg=_BG, padx=6, pady=3)
        content.pack(side="left", fill="x", expand=True)

        # Top row: icon + timestamp + category tag
        top = tk.Frame(content, bg=_BG)
        top.pack(fill="x")

        icon = entry.get("icon", "\U0001F514")
        ts = entry.get("ts_display", "")
        tk.Label(
            top, text=f"{icon} {ts}", bg=_BG, fg="#505050",
            font=("Consolas", 7), anchor="w",
        ).pack(side="left")

        cat_label = entry.get("category", "")
        tk.Label(
            top, text=cat_label.upper(), bg=_BG, fg=stripe_color,
            font=("Consolas", 6, "bold"), anchor="e",
        ).pack(side="right")

        # Message text
        msg_text = entry.get("text", "")
        tk.Label(
            content, text=msg_text, bg=_BG, fg="#b0b0b0",
            font=("Consolas", 8), anchor="w", justify="left",
            wraplength=300,
        ).pack(fill="x", anchor="w")

        # Separator
        tk.Frame(self._log_messages_frame, bg="#1a1a1a", height=1).pack(fill="x")

        entry["widget"] = frame

    # ── Public API (called from notification_mixin) ──────────────

    def _log_add_entry(self, category: str, text: str, sender: str = "Frank"):
        icon = _LOG_ICONS.get(category, "\U0001F514")
        ts_display = time.strftime("%H:%M:%S")

        entry: Dict = {
            "category": category,
            "icon": icon,
            "text": text,
            "sender": sender,
            "ts": time.time(),
            "ts_display": ts_display,
            "widget": None,
        }

        self._log_entries.append(entry)
        self._log_save_persistent()

        # Trim ring buffer
        if len(self._log_entries) > _MAX_LOG_ENTRIES:
            removed = self._log_entries.pop(0)
            w = removed.get("widget")
            if w and w.winfo_exists():
                w.destroy()

        # Render immediately if panel is open
        if self._log_open and self._log_messages_frame:
            try:
                self._log_render_entry(entry)
                self._log_canvas.update_idletasks()
                self._log_canvas.yview_moveto(1.0)
            except Exception:
                pass

        # Unread badge (only when panel is closed)
        if not self._log_open:
            self._log_unread_count += 1
            self._log_update_badge()

    def _log_update_badge(self):
        try:
            if self._log_unread_count > 0:
                text = str(min(self._log_unread_count, 99))
                self._log_btn.itemconfigure(self._log_btn_badge_id, text=text)
            else:
                self._log_btn.itemconfigure(self._log_btn_badge_id, text="")
        except Exception:
            pass

    def _log_clear_entries(self):
        for entry in self._log_entries:
            w = entry.get("widget")
            if w and w.winfo_exists():
                w.destroy()
        self._log_entries.clear()
        self._log_unread_count = 0
        self._log_update_badge()
        self._log_save_persistent()

    # ── Persistence ──────────────────────────────────────────────

    def _log_load_persistent(self) -> List[Dict]:
        try:
            if _LOG_FILE.exists():
                data = json.loads(_LOG_FILE.read_text())
                # Strip widget refs (not serializable), keep last 30
                for e in data:
                    e["widget"] = None
                return data[-_MAX_PERSISTENT:]
        except Exception as e:
            LOG.warning("Log panel load failed: %s", e)
        return []

    def _log_save_persistent(self):
        try:
            _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            # Save last 30, strip widget refs
            to_save = []
            for e in self._log_entries[-_MAX_PERSISTENT:]:
                to_save.append({
                    k: v for k, v in e.items() if k != "widget"
                })
            _LOG_FILE.write_text(json.dumps(to_save, ensure_ascii=False))
        except Exception as e:
            LOG.warning("Log panel save failed: %s", e)
