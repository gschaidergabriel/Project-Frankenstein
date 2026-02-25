"""AuraVisualizerMixin — Frank's Inner Life Visualizer Panel.

Adds a toggle button on the overlay and a separate floating window
(Toplevel, override-redirect) that appears right next to the overlay.
The overlay DOCK window is never resized — no strut changes, no
Mutter relayouts, no window-push.

The Aura window is a square (width = overlay height) showing a 256×256
cellular automaton grid inspired by Conway's Game of Life.
"""

import io
import json
import logging
import math
import random
import sqlite3
import threading
import time
import urllib.request
from pathlib import Path

import tkinter as tk
from PIL import Image

from overlay.aura.config import (
    GRID_SIZE, ZONE_WIDTH, ZONE_HEIGHT, ZONE_LAYOUT,
    SLIDE_DURATION_OPEN_MS, SLIDE_DURATION_CLOSE_MS,
    POLL_INTERVAL, INFO_FONT, INFO_COLOR,
    API_CORE, API_TOOLBOX, API_QUANTUM,
    ZONE_COLORS,
)

# Database paths
_DB_DIR = Path.home() / ".local/share/frank/db"
_DB_CONSCIOUSNESS = _DB_DIR / "consciousness.db"
_DB_WORLD_EXP = _DB_DIR / "world_experience.db"
from overlay.aura.engine import AuraEngine
from overlay.aura.headless_engine import HeadlessAuraEngine
from overlay.aura.seeder import seed_grid
from overlay.aura.renderer import AuraRenderer
from overlay.aura.events import EventManager

LOG = logging.getLogger("frank_overlay")

# Zone name → display info
_ZONE_NAMES = ["epq", "mood", "reflexion", "entities", "ego", "quantum", "titan", "hardware"]
_ZONE_DISPLAY = {
    "epq": "Personality", "mood": "Mood", "reflexion": "Thoughts",
    "entities": "Entities", "ego": "Ego", "quantum": "Coherence",
    "titan": "Memory", "hardware": "Hardware",
}
_ZONE_HEX = {
    "epq": "#00B3FF", "mood": "#FF8000", "reflexion": "#00FF4D",
    "entities": "#FF00CC", "ego": "#FFD900", "quantum": "#00FFFF",
    "titan": "#B34DFF", "hardware": "#FF331A",
}

# ── Toggle-Button Styling ──
_BTN_BG = "#0d0d0d"
_BTN_BG_HOVER = "#1a1a1a"
_BTN_BORDER_CLR = "#00cc44"
_BTN_BORDER_HOVER = "#00fff9"


try:
    from PIL import ImageTk as _ImageTk
    _HAS_IMAGETK = True
except ImportError:
    _HAS_IMAGETK = False


def _pil_to_tkphoto(pil_img: Image.Image) -> tk.PhotoImage:
    """Convert PIL Image → tk.PhotoImage. Uses ImageTk (fast) or PPM fallback."""
    if _HAS_IMAGETK:
        return _ImageTk.PhotoImage(pil_img)
    buf = io.BytesIO()
    pil_img.save(buf, format="PPM")
    return tk.PhotoImage(data=buf.getvalue())


class AuraVisualizerMixin:
    """Mixin adding Aura (inner-life visualizer) as a floating panel."""

    # ──────────────────────────────────────────────────────────────
    # Init
    # ──────────────────────────────────────────────────────────────

    def _init_aura_visualizer(self):
        self._aura_engine = HeadlessAuraEngine()
        self._aura_using_headless = True
        self._aura_events = EventManager()
        self._aura_open = False
        self._aura_animating = False
        self._aura_photo: tk.PhotoImage | None = None
        self._aura_win: tk.Toplevel | None = None
        self._aura_crt_win: tk.Toplevel | None = None

        self._aura_panel_size: int = 0

        # Frank state (updated by poller thread)
        self._aura_state = {
            "epq_vectors": {},
            "mood_buffer": 0.5,
            "coherence": 0.5,
            "reflections": [],
            "entities": [],
            "ego_state": {},
            "quantum_coherence": 0.5,
            "cpu_temp": 50.0,
            "ram_percent": 50.0,
            "cpu_load": 0.0,
            "reflection_count": 0,
            "active_entity": None,
            "online": True,
        }
        self._aura_state_lock = threading.Lock()

        self._aura_renderer: AuraRenderer | None = None
        self._aura_poller_thread: threading.Thread | None = None
        self._aura_poller_running = False
        self._aura_render_active = False
        self._aura_last_floater: float = 0.0
        self._aura_frame_count: int = 0

        # Tooltip state
        self._aura_tooltip_win: tk.Toplevel | None = None
        self._aura_tooltip_zone: str | None = None
        self._aura_tooltip_after: str | None = None  # after() ID

        # Zoom state
        self._aura_zoom: float = 1.0      # 1.0 = full grid, 8.0 = max zoom
        self._aura_pan_x: float = 128.0   # Center of viewport in grid coords
        self._aura_pan_y: float = 128.0
        self._aura_drag_start: tuple | None = None  # For pan dragging

        # Notification state
        self._aura_notifications: list[dict] = []  # {text, color, born, id}
        self._aura_notif_id_counter = 0

        # Previous state for change detection (notifications)
        self._aura_prev_epq: dict = {}
        self._aura_prev_mood: float = 0.5
        self._aura_prev_coherence: float = 0.5

        self._aura_engine.set_reseed_callback(self._aura_reseed)
        self._aura_create_toggle_button()

        # Follow overlay position changes
        self.bind("<Configure>", self._aura_on_overlay_configure, add="+")

    # ──────────────────────────────────────────────────────────────
    # Toggle Button — 22×22 · Red "A" · Cyberpunk
    # ──────────────────────────────────────────────────────────────

    def _aura_create_toggle_button(self):
        """Small square button in the panel button bar (bottom area)."""
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
        self._aura_btn_text = btn.create_text(
            s // 2, s // 2,
            text="A", fill="#ff3333",
            font=("Consolas", 11, "bold"),
        )
        btn.bind("<Button-1>", lambda _e: self._aura_toggle())
        btn.bind("<Enter>", self._aura_btn_enter)
        btn.bind("<Leave>", self._aura_btn_leave)
        btn.pack(side="right", padx=(6, 0), pady=2)

        self._aura_btn = btn
        self._aura_btn_hover = False
        self._aura_pulse_phase = 0.0
        self._aura_pulse_btn()

    def _aura_btn_enter(self, _ev):
        self._aura_btn_hover = True
        self._aura_btn.configure(bg=_BTN_BG_HOVER)
        self._aura_btn.itemconfigure("border", outline=_BTN_BORDER_HOVER)

    def _aura_btn_leave(self, _ev):
        self._aura_btn_hover = False
        self._aura_btn.configure(bg=_BTN_BG)
        self._aura_btn.itemconfigure("border", outline=_BTN_BORDER_CLR)

    def _aura_pulse_btn(self):
        if not hasattr(self, "_aura_btn") or not self._aura_btn.winfo_exists():
            return
        try:
            self._aura_pulse_phase += 0.06
            t = (math.sin(self._aura_pulse_phase) + 1) / 2
            r = int(170 + t * 85)
            g = int(34 + t * 34)
            b = int(34 + t * 34)
            self._aura_btn.itemconfigure(
                self._aura_btn_text, fill=f"#{r:02x}{g:02x}{b:02x}",
            )
        except Exception:
            pass
        self.after(80, self._aura_pulse_btn)

    # ──────────────────────────────────────────────────────────────
    # Open / Close
    # ──────────────────────────────────────────────────────────────

    def _aura_toggle(self):
        if self._aura_animating:
            return
        if self._aura_open:
            self._aura_close()
        else:
            self._aura_open_panel()

    def _aura_open_panel(self):
        # Mutual exclusion: close log panel if open
        if getattr(self, "_log_open", False) and hasattr(self, "_log_close"):
            self._log_close()

        panel_h = self.winfo_height()
        self._aura_panel_size = panel_h  # square

        # Fresh renderer per session (resets trails/decay)
        self._aura_renderer = AuraRenderer()
        self._aura_last_floater = time.monotonic()
        self._aura_zoom = 1.0
        self._aura_pan_x = 128.0
        self._aura_pan_y = 128.0

        # Seed grid (only for local engine — headless manages its own)
        self._aura_poll_state_once()
        if not self._aura_using_headless:
            with self._aura_state_lock:
                grid = seed_grid(self._aura_state)
            self._aura_engine.set_grid(grid)

        # Create floating window
        win = tk.Toplevel(self)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="#00cc44")  # neon border color

        # Position flush against overlay right edge, start at width=1
        ox = self.winfo_rootx() + self.winfo_width()
        oy = self.winfo_rooty()
        win.geometry(f"1x{panel_h}+{ox}+{oy}")
        win.update_idletasks()

        self._aura_win = win

        # Build panel content
        self._aura_build_panel(win, panel_h)

        # Start engine + poller
        self._aura_engine.start()
        self._aura_poller_running = True
        self._aura_poller_thread = threading.Thread(
            target=self._aura_poller_loop, daemon=True,
        )
        self._aura_poller_thread.start()
        self._aura_render_active = True
        self._aura_render_loop()

        # Animate width from 1 → panel_size
        self._aura_animating = True
        self._aura_animate_open(
            panel_h, time.monotonic(), SLIDE_DURATION_OPEN_MS,
        )

    def _aura_animate_open(self, target_w, t_start, duration_ms):
        if not self._aura_win or not self._aura_win.winfo_exists():
            self._aura_animating = False
            return
        elapsed = (time.monotonic() - t_start) * 1000
        if elapsed >= duration_ms:
            self._aura_set_panel_geom(target_w)
            self._aura_animating = False
            self._aura_open = True
            # Open CRT log strip after AURA finishes opening
            self.after(50, self._aura_crt_open)
            return

        t = elapsed / duration_ms
        ease = 1 - (1 - t) ** 3  # cubic ease-out
        w = max(1, int(target_w * ease))
        self._aura_set_panel_geom(w)
        self.after(16, lambda: self._aura_animate_open(
            target_w, t_start, duration_ms,
        ))

    def _aura_close(self):
        self._aura_render_active = False
        self._aura_engine.stop()
        self._aura_poller_running = False
        self._aura_hide_tooltip()
        self._aura_notifications.clear()
        self._aura_crt_close()

        self._aura_animating = True
        self._aura_animate_close(
            self._aura_panel_size, time.monotonic(), SLIDE_DURATION_CLOSE_MS,
        )

    def _aura_animate_close(self, start_w, t_start, duration_ms):
        if not self._aura_win or not self._aura_win.winfo_exists():
            self._aura_animating = False
            self._aura_open = False
            return
        elapsed = (time.monotonic() - t_start) * 1000
        if elapsed >= duration_ms:
            self._aura_close_done()
            return

        t = elapsed / duration_ms
        ease = t * t  # quadratic ease-in
        w = max(1, int(start_w * (1 - ease)))
        self._aura_set_panel_geom(w)
        self.after(16, lambda: self._aura_animate_close(
            start_w, t_start, duration_ms,
        ))

    def _aura_close_done(self):
        self._aura_animating = False
        self._aura_open = False
        if self._aura_win and self._aura_win.winfo_exists():
            self._aura_win.destroy()
        self._aura_win = None

    def _aura_set_panel_geom(self, w):
        """Position/resize the Aura window flush against overlay right edge."""
        try:
            ox = self.winfo_rootx() + self.winfo_width()
            oy = self.winfo_rooty()
            h = self.winfo_height()
            self._aura_win.geometry(f"{w}x{h}+{ox}+{oy}")
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────
    # CRT Log Strip — Old-school monitor next to AURA
    # ──────────────────────────────────────────────────────────────

    def _aura_crt_open(self):
        """Open the CRT log strip to the right of AURA."""
        if self._aura_crt_win and self._aura_crt_win.winfo_exists():
            return
        if not self._aura_win or not self._aura_win.winfo_exists():
            return

        # Calculate position: right edge of AURA → right edge of screen
        try:
            from overlay.bsn.constants import get_primary_monitor
            mon = get_primary_monitor()
            screen_w = mon["width"]
        except Exception:
            screen_w = 1600

        aura_right = (self.winfo_rootx() + self.winfo_width()
                       + self._aura_panel_size)
        crt_w = screen_w - aura_right
        if crt_w < 80:
            return  # No space

        panel_h = self.winfo_height()
        crt_x = aura_right
        crt_y = self.winfo_rooty()

        win = tk.Toplevel(self)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="#000000")
        win.geometry(f"{crt_w}x{panel_h}+{crt_x}+{crt_y}")

        self._aura_crt_win = win
        self._aura_crt_build(win, crt_w, panel_h)

    def _aura_crt_build(self, win, w, h):
        """Build the CRT log monitor — Amstrad/Fallout terminal aesthetic."""
        _bg = "#0a0a0a"
        _bg_glow = "#0a0c0a"
        _fg = "#00FF41"
        _dim = "#005500"
        _vdim = "#003300"
        _sep = "#0a1a0a"
        _edge = "#050505"
        _scanline = "#0d0e0d"
        _font = ("Courier", 9)
        _font_sm = ("Courier", 7)

        # Outer frame — vignette edge
        edge = tk.Frame(win, bg=_edge)
        edge.pack(fill="both", expand=True)

        outer = tk.Frame(edge, bg=_bg)
        outer.pack(fill="both", expand=True, padx=2, pady=2)

        # Top vignette gradient
        for v in ["#030303", "#050505", "#070707"]:
            tk.Frame(outer, bg=v, height=1).pack(fill="x", side="top")

        # Header
        hdr = tk.Frame(outer, bg=_bg, height=24)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Frame(hdr, bg=_vdim, height=1).pack(fill="x", side="top")
        tk.Label(
            hdr, text="  // DAEMON LOG", bg=_bg, fg=_dim,
            font=_font_sm, anchor="w",
        ).pack(fill="x", pady=(3, 0))
        tk.Frame(outer, bg=_vdim, height=1).pack(fill="x")

        # Scrollable text area
        txt = tk.Text(
            outer, bg=_bg_glow, fg=_fg, font=_font,
            wrap="word", padx=8, pady=6,
            insertbackground=_bg, selectbackground="#003300",
            highlightthickness=0, borderwidth=0,
            cursor="arrow", spacing3=2,
        )
        scrollbar = tk.Scrollbar(
            outer, orient="vertical", command=txt.yview,
            bg="#001a00", troughcolor="#000000",
            activebackground="#003300", width=4,
        )
        txt.configure(yscrollcommand=scrollbar.set)

        # Bottom vignette
        bottom_vig = tk.Frame(outer, bg=_bg)
        bottom_vig.pack(fill="x", side="bottom")
        for v in ["#070707", "#050505", "#030303"]:
            tk.Frame(bottom_vig, bg=v, height=1).pack(fill="x")

        scrollbar.pack(side="right", fill="y")
        txt.pack(fill="both", expand=True)

        # Scroll isolation
        def _crt_scroll(event):
            txt.yview_scroll(-1 if event.num == 4 else 1, "units")
            return "break"
        for widget in (txt, outer, edge, win):
            widget.bind("<Button-4>", _crt_scroll)
            widget.bind("<Button-5>", _crt_scroll)

        # CRT text tags
        txt.tag_configure("timestamp", foreground=_dim, font=_font_sm)
        txt.tag_configure("message", foreground=_fg, font=_font)
        txt.tag_configure("separator", foreground=_sep, font=("Courier", 4))
        txt.tag_configure("scanline", background=_scanline)

        # Render entries
        entries = getattr(self, "_log_entries", [])
        for entry in entries[-30:]:
            ts = entry.get("ts_display", "")
            cat = entry.get("category", "")[:4].upper()
            text = entry.get("text", "")

            txt.insert("end", f"{ts} [{cat}]\n", "timestamp")
            txt.insert("end", f"{text}\n", "message")
            txt.insert("end", "\u2500" * 30 + "\n", "separator")

        # Apply scanlines
        txt.update_idletasks()
        try:
            line_count = int(txt.index("end-1c").split(".")[0])
            for i in range(1, line_count + 1, 2):
                txt.tag_add("scanline", f"{i}.0", f"{i}.end")
        except Exception:
            pass

        txt.configure(state="disabled")
        txt.see("end")
        self._aura_crt_text = txt
        self._aura_crt_flicker_phase = 0.0

        # Start persistent CRT effects
        self._aura_crt_flicker()
        self._aura_crt_schedule_tear()

    # ── AURA CRT Effects ──────────────────────────────────────────

    def _aura_crt_flicker(self):
        """Subtle phosphor flicker — sin-wave + random noise."""
        crt = getattr(self, "_aura_crt_text", None)
        if not crt or not crt.winfo_exists():
            return
        try:
            self._aura_crt_flicker_phase += 0.08
            t = (math.sin(self._aura_crt_flicker_phase) + 1) / 2
            t = max(0, min(1, t + random.uniform(-0.03, 0.03)))
            g = int(0xE0 + t * 0x1F)
            crt.tag_configure("message", foreground=f"#00{g:02x}41")
            s = int(0x0C + t * 0x04)
            crt.tag_configure("scanline", background=f"#{s:02x}{s+1:02x}{s:02x}")
        except Exception:
            pass
        self.after(100, self._aura_crt_flicker)

    def _aura_crt_schedule_tear(self):
        """Schedule next screen tear."""
        crt = getattr(self, "_aura_crt_text", None)
        if not crt:
            return
        self.after(random.randint(8000, 15000), self._aura_crt_screen_tear)

    def _aura_crt_screen_tear(self):
        """Brief horizontal VHS-style glitch."""
        crt = getattr(self, "_aura_crt_text", None)
        if not crt or not crt.winfo_exists():
            return
        try:
            line_count = int(crt.index("end-1c").split(".")[0])
            if line_count < 3:
                self._aura_crt_schedule_tear()
                return
            line = random.randint(1, max(1, line_count - 1))
            shift = random.randint(2, 5)
            crt.configure(state="normal")
            crt.insert(f"{line}.0", " " * shift)
            crt.configure(state="disabled")
            self.after(random.randint(60, 100),
                       lambda: self._aura_crt_tear_restore(line, shift))
        except Exception:
            pass
        self._aura_crt_schedule_tear()

    def _aura_crt_tear_restore(self, line: int, count: int):
        """Remove glitch characters."""
        crt = getattr(self, "_aura_crt_text", None)
        if not crt or not crt.winfo_exists():
            return
        try:
            crt.configure(state="normal")
            crt.delete(f"{line}.0", f"{line}.{count}")
            crt.configure(state="disabled")
        except Exception:
            pass

    def _aura_crt_close(self):
        """Close the CRT log strip."""
        if self._aura_crt_win and self._aura_crt_win.winfo_exists():
            self._aura_crt_win.destroy()
        self._aura_crt_win = None

    def _aura_crt_reposition(self):
        """Reposition CRT window when overlay/AURA moves."""
        if not self._aura_crt_win or not self._aura_crt_win.winfo_exists():
            return
        try:
            from overlay.bsn.constants import get_primary_monitor
            mon = get_primary_monitor()
            screen_w = mon["width"]
        except Exception:
            screen_w = 1600

        try:
            aura_right = (self.winfo_rootx() + self.winfo_width()
                           + self._aura_panel_size)
            crt_w = screen_w - aura_right
            if crt_w < 80:
                self._aura_crt_close()
                return
            crt_x = aura_right
            crt_y = self.winfo_rooty()
            h = self.winfo_height()
            self._aura_crt_win.geometry(f"{crt_w}x{h}+{crt_x}+{crt_y}")
        except Exception:
            pass

    def _aura_on_overlay_configure(self, _event):
        """Keep Aura window glued to the overlay when it moves."""
        if self._aura_open and self._aura_win and not self._aura_animating:
            try:
                self._aura_set_panel_geom(self._aura_panel_size)
                self._aura_crt_reposition()
            except Exception:
                pass

    # ──────────────────────────────────────────────────────────────
    # Panel UI — grid fills window, HUD overlaid at bottom
    # ──────────────────────────────────────────────────────────────

    def _aura_build_panel(self, win, panel_size):
        bg = "#0D1117"

        # Inner frame (1px green border effect via parent bg)
        inner = tk.Frame(win, bg=bg)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        # Grid canvas — fills entire area
        self._aura_canvas = tk.Canvas(inner, bg="#161B22", highlightthickness=0)
        self._aura_canvas.pack(fill="both", expand=True)

        self._aura_canvas_size = max(1, panel_size - 4)

        # Initial placeholder
        cs = self._aura_canvas_size
        img = Image.new("RGB", (GRID_SIZE, GRID_SIZE), (22, 27, 34))
        img_resized = img.resize((cs, cs), Image.NEAREST)
        self._aura_photo = _pil_to_tkphoto(img_resized)
        self._aura_canvas_img = self._aura_canvas.create_image(
            0, 0, anchor="nw", image=self._aura_photo,
        )

        # ── Grid mouse bindings (tooltips + zoom + pan) ──
        self._aura_canvas.bind("<Motion>", self._aura_on_grid_motion)
        self._aura_canvas.bind("<Leave>", self._aura_on_grid_leave)
        self._aura_canvas.bind("<Button-4>", self._aura_on_scroll_up)
        self._aura_canvas.bind("<Button-5>", self._aura_on_scroll_down)
        self._aura_canvas.bind("<ButtonPress-2>", self._aura_on_drag_start)
        self._aura_canvas.bind("<B2-Motion>", self._aura_on_drag_motion)
        self._aura_canvas.bind("<ButtonRelease-2>", self._aura_on_drag_end)
        self._aura_canvas.bind("<ButtonPress-3>", self._aura_on_zoom_reset)

        # ── Notification overlay items (top-right of grid canvas) ──
        self._aura_notif_items: list[dict] = []

        # ── HUD — Canvas-based for pixel-perfect control ──
        hud_h = 166
        hud_bg = "#0D1117"
        hud = tk.Canvas(
            inner, bg=hud_bg, highlightthickness=0, height=hud_h,
        )
        hud.place(relx=0, rely=1.0, anchor="sw", relwidth=1.0, height=hud_h)
        self._aura_hud = hud

        pw = panel_size

        # ── Accent line (y=0) ──
        hud.create_line(0, 0, 3000, 0, fill="#00cc44", width=1)

        # ── Title row (y=13) ──
        hud.create_text(12, 13, text="AURA", fill="#00fff9",
                         font=("Consolas", 9, "bold"), anchor="w")
        hud.create_text(52, 13, text="//", fill="#1e3a2a",
                         font=("Consolas", 8), anchor="w")
        hud.create_text(66, 13, text="INNER LIFE", fill="#2a2a2a",
                         font=("Consolas", 7), anchor="w")
        self._aura_hud_gen = hud.create_text(
            pw - 14, 13, text="", fill="#363636",
            font=("Consolas", 7), anchor="e")

        # ── Stats row (y=37) ──
        hud.create_line(10, 26, pw - 10, 26, fill="#161B22", width=1)
        _font = ("Consolas", 8)
        _bw = 90

        hud.create_text(12, 37, text="MOOD", fill="#505050",
                         font=_font, anchor="w")
        _bx = 50
        hud.create_rectangle(_bx, 34, _bx + _bw, 38,
                              fill="#161B22", outline="")
        self._aura_hud_mood_bar = hud.create_rectangle(
            _bx, 34, _bx + 45, 38, fill="#FF8000", outline="")
        self._aura_hud_mood_val = hud.create_text(
            _bx + _bw + 6, 37, text="---", fill="#FF8000",
            font=_font, anchor="w")

        _cx = 200
        hud.create_text(_cx, 37, text="COHR", fill="#505050",
                         font=_font, anchor="w")
        _cbx = _cx + 38
        hud.create_rectangle(_cbx, 34, _cbx + _bw, 38,
                              fill="#161B22", outline="")
        self._aura_hud_cohr_bar = hud.create_rectangle(
            _cbx, 34, _cbx + 45, 38, fill="#00FFFF", outline="")
        self._aura_hud_cohr_val = hud.create_text(
            _cbx + _bw + 6, 37, text="---", fill="#00FFFF",
            font=_font, anchor="w")

        self._aura_hud_refl = hud.create_text(
            pw - 80, 37, text="", fill="#00FF4D",
            font=_font, anchor="e")
        self._aura_hud_hw = hud.create_text(
            pw - 14, 37, text="", fill="#FF331A",
            font=_font, anchor="e")

        # ── ABOUT section — 2-column layout to use width, not height ──
        hud.create_line(10, 50, pw - 10, 50, fill="#161B22", width=1)

        _df = ("Consolas", 7)
        _dfs = ("Consolas", 6)
        _dc = "#3a4550"
        _dh = "#4a7060"
        _ls = 10  # line spacing

        hud.create_text(12, 54, text="ABOUT", fill="#0d5c2e",
                         font=("Consolas", 6), anchor="nw")

        # Left column (x=12): Description + Reading guide
        _lx = 12
        _y = 65
        hud.create_text(_lx, _y, anchor="nw", fill="#4a6a5a", font=_dfs,
            text="AURA \u2014 Autonomous Universal Resonance Automaton")
        _y += _ls
        hud.create_text(_lx, _y, anchor="nw", fill=_dc, font=_dfs,
            text="Frank's consciousness as a quantum cellular automaton.")
        _y += _ls
        hud.create_text(_lx, _y, anchor="nw", fill=_dc, font=_dfs,
            text="256\u00d7256 Game of Life at 10 Hz. 8 zones \u2192 live subsystems.")
        _y += _ls
        hud.create_text(_lx, _y, anchor="nw", fill=_dc, font=_dfs,
            text="Fed by real data: mood, thoughts, E-PQ, entities, HW.")
        _y += _ls
        hud.create_text(_lx, _y, anchor="nw", fill=_dc, font=_dfs,
            text="Seeded by real subsystem data. Patterns emerge autonomously.")

        # Right column (x=pw/2): Quantum + Reading guide
        _rx = pw // 2 + 10
        _ry = 65
        hud.create_text(_rx, _ry, anchor="nw", fill=_dh, font=_dfs,
            text="QUANTUM SUPERPOSITION")
        _ry += _ls
        hud.create_text(_rx, _ry, anchor="nw", fill=_dc, font=_dfs,
            text="Each cell: 8D type vector [p\u2080..p\u2087]. Colors = weighted blend.")
        _ry += _ls
        hud.create_text(_rx, _ry, anchor="nw", fill=_dc, font=_dfs,
            text="Diffusion \u2192 color gradients. Decoherence \u2192 crystallization.")
        _ry += _ls + 2
        hud.create_text(_rx, _ry, anchor="nw", fill=_dc, font=_dfs,
            text="Density=activity  Trails=recent  Blend=superposition")
        _ry += _ls
        hud.create_text(_rx, _ry, anchor="nw", fill=_dc, font=_dfs,
            text="Border glow=cross-zone flow  Pulse=alive cells")

        # ── ZONES legend — squares + hover (y=130 sep, y=145 items) ──
        hud.create_line(10, 130, pw - 10, 130, fill="#161B22", width=1)

        _lf = ("Consolas", 7)
        _ly = 145
        _legend = [
            ("epq",       "EPQ",      "#00B3FF"),
            ("mood",      "Mood",     "#FF8000"),
            ("reflexion", "Thoughts", "#00FF4D"),
            ("entities",  "Entities", "#FF00CC"),
            ("ego",       "Ego",      "#FFD900"),
            ("quantum",   "Quantum",  "#00FFFF"),
            ("titan",     "Memory",   "#B34DFF"),
            ("hardware",  "HW",       "#FF331A"),
        ]
        _margin = 12
        _col_w = max(1, (pw - _margin * 2) // len(_legend))
        self._aura_legend_items = []
        for i, (zone_key, label, color) in enumerate(_legend):
            lx = _margin + i * _col_w
            sq = hud.create_rectangle(lx, _ly - 4, lx + 8, _ly + 4,
                                       fill=color, outline="")
            txt = hud.create_text(lx + 12, _ly, text=label, fill="#606060",
                                   font=_lf, anchor="w")
            self._aura_legend_items.append({
                "zone": zone_key, "sq": sq, "txt": txt, "color": color,
            })
            # Hover bindings on each item
            for item_id in (sq, txt):
                hud.tag_bind(item_id, "<Enter>",
                    lambda _e, z=zone_key, c=color, t=txt:
                        self._aura_legend_enter(z, c, t))
                hud.tag_bind(item_id, "<Leave>",
                    lambda _e, t=txt:
                        self._aura_legend_leave(t))

    # ──────────────────────────────────────────────────────────────
    # Legend Hover (Change 4b)
    # ──────────────────────────────────────────────────────────────

    def _aura_legend_enter(self, zone_key: str, color: str, txt_id):
        try:
            self._aura_hud.itemconfigure(txt_id, fill=color)
            if self._aura_renderer:
                self._aura_renderer._highlight_zone = zone_key
        except Exception:
            pass

    def _aura_legend_leave(self, txt_id):
        try:
            self._aura_hud.itemconfigure(txt_id, fill="#606060")
            if self._aura_renderer:
                self._aura_renderer._highlight_zone = None
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────
    # Grid Tooltips (Change 1)
    # ──────────────────────────────────────────────────────────────

    def _aura_canvas_to_grid(self, px: int, py: int) -> tuple[float, float] | None:
        """Convert canvas pixel coords → grid coords, accounting for zoom."""
        cw = self._aura_canvas.winfo_width()
        ch = self._aura_canvas.winfo_height()
        cs = min(cw, ch)
        if cs < 1:
            return None
        x_off = (cw - cs) // 2
        y_off = (ch - cs) // 2
        # Normalized position in canvas (0..1)
        nx = (px - x_off) / cs
        ny = (py - y_off) / cs
        if not (0 <= nx <= 1 and 0 <= ny <= 1):
            return None
        # Map to grid coords with zoom
        vis = GRID_SIZE / self._aura_zoom
        half = vis / 2.0
        gx = (self._aura_pan_x - half) + nx * vis
        gy = (self._aura_pan_y - half) + ny * vis
        return (gx, gy)

    def _aura_pixel_to_zone(self, px: int, py: int) -> str | None:
        """Convert canvas pixel coords → zone name."""
        coords = self._aura_canvas_to_grid(px, py)
        if coords is None:
            return None
        gx, gy = coords
        if not (0 <= gx < GRID_SIZE and 0 <= gy < GRID_SIZE):
            return None
        col = min(int(gx) // ZONE_WIDTH, 3)
        row = min(int(gy) // ZONE_HEIGHT, 1)
        for name, (r, c) in ZONE_LAYOUT.items():
            if r == row and c == col:
                return name
        return None

    def _aura_on_grid_motion(self, event):
        zone = self._aura_pixel_to_zone(event.x, event.y)
        if zone == self._aura_tooltip_zone:
            return
        self._aura_hide_tooltip()
        self._aura_tooltip_zone = zone
        if zone:
            self._aura_tooltip_after = self._aura_canvas.after(
                300, lambda: self._aura_show_tooltip(zone, event.x, event.y))

    def _aura_on_grid_leave(self, _event):
        self._aura_hide_tooltip()
        self._aura_tooltip_zone = None

    def _aura_hide_tooltip(self):
        if self._aura_tooltip_after:
            try:
                self._aura_canvas.after_cancel(self._aura_tooltip_after)
            except Exception:
                pass
            self._aura_tooltip_after = None
        if self._aura_tooltip_win:
            try:
                self._aura_tooltip_win.destroy()
            except Exception:
                pass
            self._aura_tooltip_win = None

    def _aura_show_tooltip(self, zone: str, mx: int, my: int):
        self._aura_tooltip_after = None
        if not self._aura_open or not self._aura_win:
            return
        if self._aura_tooltip_zone != zone:
            return

        lines = self._aura_get_tooltip_lines(zone)
        if not lines:
            return

        color = _ZONE_HEX.get(zone, "#888888")
        tip = tk.Toplevel(self._aura_win)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tip.configure(bg=color)

        frame = tk.Frame(tip, bg="#0D1117", padx=6, pady=4)
        frame.pack(padx=1, pady=1)

        title = _ZONE_DISPLAY.get(zone, zone.upper())
        tk.Label(frame, text=title, bg="#0D1117", fg=color,
                 font=("Consolas", 9, "bold"), anchor="w").pack(anchor="w")

        for line in lines:
            tk.Label(frame, text=line, bg="#0D1117", fg="#8B949E",
                     font=("Consolas", 8), anchor="w").pack(anchor="w")

        tip.update_idletasks()

        # Position: offset from mouse cursor, clamped to screen
        sx = self._aura_canvas.winfo_rootx() + mx + 12
        sy = self._aura_canvas.winfo_rooty() + my + 12
        tw = tip.winfo_reqwidth()
        th = tip.winfo_reqheight()
        screen_w = tip.winfo_screenwidth()
        screen_h = tip.winfo_screenheight()
        if sx + tw > screen_w - 4:
            sx = self._aura_canvas.winfo_rootx() + mx - tw - 12
        if sy + th > screen_h - 4:
            sy = self._aura_canvas.winfo_rooty() + my - th - 12
        sx = max(0, sx)
        sy = max(0, sy)
        tip.geometry(f"+{sx}+{sy}")
        self._aura_tooltip_win = tip

    def _aura_get_tooltip_lines(self, zone: str) -> list[str]:
        with self._aura_state_lock:
            s = dict(self._aura_state)

        if zone == "epq":
            vecs = s.get("epq_vectors", {})
            parts = [f"{k[0].upper()}:{v:.2f}" for k, v in vecs.items()]
            return [" ".join(parts) if parts else "No data"]
        elif zone == "mood":
            mood = s.get("mood_buffer", 0.5)
            return [f"Value: {mood:.3f}"]
        elif zone == "reflexion":
            refls = s.get("reflections", [])
            if refls:
                txt = refls[0].get("content", "")[:55]
                if len(refls[0].get("content", "")) > 55:
                    txt += "..."
                trigger = refls[0].get("trigger", "")
                return [f"[{trigger}]", txt if txt else "..."]
            return ["No recent thoughts"]
        elif zone == "entities":
            ents = s.get("entities", [])
            if ents:
                lines = []
                for e in ents[:4]:
                    name = e.get("name", "?") if isinstance(e, dict) else str(e)
                    active = e.get("is_in_session", False) if isinstance(e, dict) else False
                    lines.append(f"{name}: {'active' if active else 'idle'}")
                return lines
            return ["No entities loaded"]
        elif zone == "ego":
            ego = s.get("ego_state", {})
            emb = ego.get("embodiment_level", 0.5)
            return [f"Embodiment: {emb:.2f}"]
        elif zone == "quantum":
            cohr = s.get("coherence", 0.5)
            return [f"Score: {cohr:.3f}"]
        elif zone == "titan":
            rc = s.get("reflection_count", 0)
            return [f"Reflections: {rc}"]
        elif zone == "hardware":
            cpu = s.get("cpu_temp", 0)
            ram = s.get("ram_percent", 0)
            load = s.get("cpu_load", 0)
            return [f"CPU: {cpu:.0f}\u00b0C  RAM: {ram:.0f}%  Load: {load:.1f}"]
        return []

    # ──────────────────────────────────────────────────────────────
    # Zoom & Pan (scroll wheel + middle-click drag)
    # ──────────────────────────────────────────────────────────────

    def _aura_clamp_pan(self):
        """Clamp pan so viewport stays within grid bounds."""
        vis = GRID_SIZE / self._aura_zoom
        half = vis / 2.0
        self._aura_pan_x = max(half, min(GRID_SIZE - half, self._aura_pan_x))
        self._aura_pan_y = max(half, min(GRID_SIZE - half, self._aura_pan_y))

    def _aura_on_scroll_up(self, event):
        """Zoom in towards cursor."""
        self._aura_zoom_towards(event.x, event.y, 1.25)

    def _aura_on_scroll_down(self, event):
        """Zoom out from cursor."""
        self._aura_zoom_towards(event.x, event.y, 0.8)

    def _aura_zoom_towards(self, mx: int, my: int, factor: float):
        """Zoom by factor, keeping the grid point under cursor fixed."""
        coords = self._aura_canvas_to_grid(mx, my)
        if coords is None:
            return

        gx, gy = coords
        old_zoom = self._aura_zoom
        new_zoom = max(1.0, min(10.0, old_zoom * factor))

        if abs(new_zoom - old_zoom) < 0.01:
            return

        # Calculate new pan to keep (gx,gy) under cursor
        cw = self._aura_canvas.winfo_width()
        ch = self._aura_canvas.winfo_height()
        cs = min(cw, ch)
        if cs < 1:
            return
        x_off = (cw - cs) // 2
        y_off = (ch - cs) // 2
        nx = (mx - x_off) / cs
        ny = (my - y_off) / cs

        new_vis = GRID_SIZE / new_zoom
        self._aura_pan_x = gx - (nx - 0.5) * new_vis
        self._aura_pan_y = gy - (ny - 0.5) * new_vis
        self._aura_zoom = new_zoom
        self._aura_clamp_pan()

    def _aura_on_drag_start(self, event):
        """Start panning with middle mouse button."""
        self._aura_drag_start = (event.x, event.y)

    def _aura_on_drag_motion(self, event):
        """Pan the viewport while dragging."""
        if self._aura_drag_start is None or self._aura_zoom <= 1.01:
            return
        dx = event.x - self._aura_drag_start[0]
        dy = event.y - self._aura_drag_start[1]
        self._aura_drag_start = (event.x, event.y)

        cw = self._aura_canvas.winfo_width()
        ch = self._aura_canvas.winfo_height()
        cs = min(cw, ch)
        if cs < 1:
            return

        vis = GRID_SIZE / self._aura_zoom
        self._aura_pan_x -= dx / cs * vis
        self._aura_pan_y -= dy / cs * vis
        self._aura_clamp_pan()

    def _aura_on_drag_end(self, _event):
        self._aura_drag_start = None

    def _aura_on_zoom_reset(self, _event):
        """Right-click resets zoom to 1x."""
        self._aura_zoom = 1.0
        self._aura_pan_x = 128.0
        self._aura_pan_y = 128.0

    # ──────────────────────────────────────────────────────────────
    # Event Notifications (Change 5)
    # ──────────────────────────────────────────────────────────────

    def _aura_push_notification(self, text: str, color: str):
        self._aura_notif_id_counter += 1
        notif = {
            "text": text, "color": color,
            "born": time.monotonic(),
            "nid": self._aura_notif_id_counter,
            "canvas_ids": [],
        }
        self._aura_notifications.append(notif)
        # Keep max 3
        while len(self._aura_notifications) > 3:
            old = self._aura_notifications.pop(0)
            self._aura_remove_notif_canvas(old)

    def _aura_remove_notif_canvas(self, notif: dict):
        for cid in notif.get("canvas_ids", []):
            try:
                self._aura_canvas.delete(cid)
            except Exception:
                pass

    def _aura_render_notifications(self):
        """Render/update notification cards on grid canvas."""
        canvas = self._aura_canvas
        now = time.monotonic()

        # Remove expired (>3.5s, includes fade time)
        alive = []
        for n in self._aura_notifications:
            if now - n["born"] > 3.5:
                self._aura_remove_notif_canvas(n)
            else:
                alive.append(n)
        self._aura_notifications = alive

        # Clear and re-draw (simple, max 3 items)
        for n in self._aura_notifications:
            self._aura_remove_notif_canvas(n)
            n["canvas_ids"] = []

        cw = canvas.winfo_width()
        y_base = 8
        for i, n in enumerate(self._aura_notifications):
            age = now - n["born"]
            # Fade: 0-0.2s fade in, 3.0-3.5s fade out
            if age < 0.2:
                alpha = age / 0.2
            elif age > 3.0:
                alpha = max(0, 1.0 - (age - 3.0) / 0.5)
            else:
                alpha = 1.0

            if alpha < 0.05:
                continue

            y = y_base + i * 22
            color = n["color"]
            # Dim color based on alpha
            try:
                cr = int(color[1:3], 16)
                cg = int(color[3:5], 16)
                cb = int(color[5:7], 16)
                dr = int(cr * alpha)
                dg = int(cg * alpha)
                db = int(cb * alpha)
                fill_color = f"#{dr:02x}{dg:02x}{db:02x}"
                bg_r = int(13 + (cr * 0.15) * alpha)
                bg_g = int(17 + (cg * 0.15) * alpha)
                bg_b = int(23 + (cb * 0.15) * alpha)
                bg_color = f"#{min(bg_r,255):02x}{min(bg_g,255):02x}{min(bg_b,255):02x}"
            except Exception:
                fill_color = color
                bg_color = "#0D1117"

            rect = canvas.create_rectangle(
                cw - 260, y, cw - 8, y + 18,
                fill=bg_color, outline=fill_color, width=1)
            txt = canvas.create_text(
                cw - 254, y + 9, text=n["text"][:40],
                fill=fill_color, font=("Consolas", 7), anchor="w")
            n["canvas_ids"] = [rect, txt]

    def _aura_check_state_notifications(self):
        """Compare current state vs previous, fire notifications for changes."""
        with self._aura_state_lock:
            s = dict(self._aura_state)

        mood = s.get("mood_buffer", 0.5)
        cohr = s.get("coherence", 0.5)
        epq = s.get("epq_vectors", {})

        # Mood jump > 0.1
        if abs(mood - self._aura_prev_mood) > 0.1:
            direction = "\u25b2" if mood > self._aura_prev_mood else "\u25bc"
            self._aura_push_notification(
                f"MOOD {direction} {self._aura_prev_mood:.2f} \u2192 {mood:.2f}",
                "#FF8000")

        # Coherence jump > 0.15
        if abs(cohr - self._aura_prev_coherence) > 0.15:
            self._aura_push_notification(
                f"\u25c8 Coherence: {self._aura_prev_coherence:.2f} \u2192 {cohr:.2f}",
                "#00FFFF")

        # E-PQ shifts > 0.05
        for key in ("precision", "risk", "empathy", "autonomy", "vigilance"):
            old_v = self._aura_prev_epq.get(key, 0)
            new_v = epq.get(key, 0)
            if abs(new_v - old_v) > 0.05:
                direction = "+" if new_v > old_v else ""
                self._aura_push_notification(
                    f"\u2191 {key} {direction}{new_v - old_v:.2f}",
                    "#00B3FF")
                break  # One EPQ notification per cycle max

        self._aura_prev_mood = mood
        self._aura_prev_coherence = cohr
        self._aura_prev_epq = dict(epq)

    # ──────────────────────────────────────────────────────────────
    # Render Loop (~50 FPS, main thread)
    # ──────────────────────────────────────────────────────────────

    def _aura_render_loop(self):
        if not self._aura_render_active:
            return
        if not self._aura_win or not self._aura_win.winfo_exists():
            self._aura_render_active = False
            return

        t0 = time.monotonic()
        try:
            # Event animation masks
            ripple_masks = self._aura_events.advance_ripples()
            injection_masks = self._aura_events.get_pending_injections()
            all_masks = ripple_masks + injection_masks
            if all_masks:
                combined = all_masks[0]
                for m in all_masks[1:]:
                    combined = combined | m
                self._aura_engine.inject_cells(combined)

            # Render grid → PIL image
            grid = self._aura_engine.get_read_grid()
            cell_age = self._aura_engine.get_cell_age()
            with self._aura_state_lock:
                mood = self._aura_state["mood_buffer"]
            threat = self._aura_events.threat_intensity

            # Get quantum colors from headless engine (per-cell blended RGB)
            qcolors = None
            if self._aura_using_headless and hasattr(self._aura_engine, "get_quantum_colors"):
                qcolors = self._aura_engine.get_quantum_colors()

            img = self._aura_renderer.render(grid, cell_age, mood, threat, quantum_colors=qcolors)

            # Scale to canvas size with zoom (crop + resize)
            cw = self._aura_canvas.winfo_width()
            ch = self._aura_canvas.winfo_height()
            if cw > 1 and ch > 1:
                cs = min(cw, ch)

                if self._aura_zoom > 1.01:
                    # Zoomed: crop viewport from grid image
                    vis = GRID_SIZE / self._aura_zoom
                    half = vis / 2.0
                    cx, cy = self._aura_pan_x, self._aura_pan_y
                    x0 = max(0, int(cx - half))
                    y0 = max(0, int(cy - half))
                    x1 = min(GRID_SIZE, int(cx + half))
                    y1 = min(GRID_SIZE, int(cy + half))
                    # Clamp to keep viewport size consistent
                    if x1 - x0 < 2:
                        x0, x1 = 0, GRID_SIZE
                    if y1 - y0 < 2:
                        y0, y1 = 0, GRID_SIZE
                    cropped = img.crop((x0, y0, x1, y1))
                    img_resized = cropped.resize((cs, cs), Image.NEAREST)
                else:
                    img_resized = img.resize((cs, cs), Image.NEAREST)

                self._aura_photo = _pil_to_tkphoto(img_resized)
                x_off = (cw - cs) // 2
                y_off = (ch - cs) // 2
                self._aura_canvas.coords(self._aura_canvas_img, x_off, y_off)
                self._aura_canvas.itemconfigure(
                    self._aura_canvas_img, image=self._aura_photo,
                )

            self._aura_frame_count += 1
            if self._aura_frame_count % 3 == 0:
                self._aura_update_info()
                self._aura_render_notifications()

            # Periodic floater injection (~every 8 s)
            now = time.monotonic()
            if now - self._aura_last_floater > 8.0:
                self._aura_events.trigger_floater()
                self._aura_last_floater = now

        except Exception as e:
            LOG.debug("Aura render error: %s", e)

        elapsed_ms = (time.monotonic() - t0) * 1000
        delay = max(8, 20 - int(elapsed_ms))  # target ~50 FPS
        self.after(delay, self._aura_render_loop)

    def _aura_update_info(self):
        try:
            hud = self._aura_hud
            with self._aura_state_lock:
                mood = self._aura_state["mood_buffer"]
                cohr = self._aura_state.get("coherence", 0.5)
                refl_count = self._aura_state.get("reflection_count", 0)
                cpu_temp = self._aura_state.get("cpu_temp", 0)
                online = self._aura_state.get("online", True)

            gen = self._aura_engine.generation

            # Gen counter
            hud.itemconfigure(self._aura_hud_gen, text=f"GEN {gen:,}")

            # Mood bar (track x=50, width=90)
            fill = int(max(0, min(1, mood)) * 90)
            hud.coords(self._aura_hud_mood_bar, 50, 34, 50 + fill, 38)
            hud.itemconfigure(self._aura_hud_mood_val, text=f"{mood:.2f}")

            # Coherence bar (track x=238, width=90)
            fill = int(max(0, min(1, cohr)) * 90)
            hud.coords(self._aura_hud_cohr_bar, 238, 34, 238 + fill, 38)
            hud.itemconfigure(self._aura_hud_cohr_val, text=f"{cohr:.2f}")

            # Reflections
            hud.itemconfigure(
                self._aura_hud_refl,
                text=f"{refl_count} refl" if refl_count else "",
            )

            # Hardware
            if cpu_temp > 0:
                hud.itemconfigure(self._aura_hud_hw, text=f"{cpu_temp:.0f}°C")

            # Online indicator
            if not online:
                hud.itemconfigure(self._aura_hud_gen, fill="#ff4444")
            else:
                hud.itemconfigure(self._aura_hud_gen, fill="#363636")
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────
    # State Poller (background thread)
    # ──────────────────────────────────────────────────────────────

    def _aura_poller_loop(self):
        while self._aura_poller_running:
            self._aura_poll_state_once()
            time.sleep(POLL_INTERVAL)

    def _aura_poll_state_once(self):
        new_state: dict = {}
        online = True

        # ── Headless mode: get state from cached headless metadata ──
        if self._aura_using_headless and getattr(self._aura_engine, "connected", False):
            meta = self._aura_engine.get_metadata()
            epq = meta.get("epq_vectors", {})
            if epq:
                new_state["epq_vectors"] = epq
            mood_val = meta.get("mood", 0.0)
            new_state["mood_buffer"] = abs(mood_val) if mood_val is not None else 0.5
            cohr = meta.get("coherence", 0.5)
            new_state["coherence"] = max(0.0, min(1.0, cohr)) if cohr else 0.5
            new_state["cpu_temp"] = meta.get("hw_temp", 0)
            new_state["ram_percent"] = meta.get("ram_usage", 0.0) * 100
            new_state["reflection_count"] = meta.get("thought_count", 0)
            new_state["online"] = True

            # Still fetch reflections from DB (headless doesn't cache content)
            try:
                rows = self._aura_db_query_all(
                    _DB_CONSCIOUSNESS,
                    "SELECT content, trigger FROM reflections "
                    "ORDER BY id DESC LIMIT 8",
                )
                if rows:
                    new_state["reflections"] = [
                        {"content": r[0], "trigger": r[1]} for r in rows
                    ]
                    new_state["reflection_count"] = len(rows)
            except Exception:
                pass
        else:
            # ── Fallback: direct DB/API polling ──

            # ── Read E-PQ + mood_buffer from world_experience.db ──
            try:
                row = self._aura_db_query(
                    _DB_WORLD_EXP,
                    "SELECT precision_val, risk_val, empathy_val, "
                    "autonomy_val, vigilance_val, mood_buffer, confidence_anchor "
                    "FROM personality_state ORDER BY id DESC LIMIT 1",
                )
                if row:
                    new_state["epq_vectors"] = {
                        "precision": row[0], "risk": row[1], "empathy": row[2],
                        "autonomy": row[3], "vigilance": row[4],
                    }
                    new_state["mood_buffer"] = float(row[5])
                    new_state["coherence"] = float(row[6])
            except Exception:
                online = False

            # ── Read live mood from consciousness.db ──
            try:
                row = self._aura_db_query(
                    _DB_CONSCIOUSNESS,
                    "SELECT mood_value FROM mood_trajectory "
                    "ORDER BY id DESC LIMIT 1",
                )
                if row:
                    new_state["mood_buffer"] = float(row[0])
            except Exception:
                pass

            # ── Read recent reflections from consciousness.db ──
            try:
                rows = self._aura_db_query_all(
                    _DB_CONSCIOUSNESS,
                    "SELECT content, trigger FROM reflections "
                    "ORDER BY id DESC LIMIT 8",
                )
                if rows:
                    reflections = [
                        {"content": r[0], "trigger": r[1]} for r in rows
                    ]
                    new_state["reflections"] = reflections
                    new_state["reflection_count"] = len(reflections)
            except Exception:
                pass

            # ── Read hardware from toolbox API ──
            try:
                data = self._aura_api_post(f"{API_TOOLBOX}/sys/summary")
                if data:
                    temps = data.get("temps", {})
                    new_state["cpu_temp"] = float(temps.get("max_c", 0))
                    mem = data.get("mem", {}).get("mem_kb", {})
                    total = mem.get("total", 1)
                    used = mem.get("used", 0)
                    new_state["ram_percent"] = (used / max(total, 1)) * 100
                    cpu = data.get("cpu", {})
                    new_state["cpu_load"] = float(cpu.get("load_1m", 0))
            except Exception:
                pass

            # ── Read coherence from quantum reflector API ──
            try:
                data = self._aura_api_get(f"{API_QUANTUM}/status")
                if data:
                    last = data.get("last_result") or {}
                    energy = last.get("energy")
                    if energy is not None:
                        new_state["coherence"] = max(
                            0.0, min(1.0, 1.0 - abs(energy) / 100.0),
                        )
            except Exception:
                pass

            new_state["online"] = online

        with self._aura_state_lock:
            old_mood = self._aura_state.get("mood_buffer", 0.5)
            old_refl_count = self._aura_state.get("reflection_count", 0)
            old_entity = self._aura_state.get("active_entity")
            self._aura_state.update(new_state)
            new_mood = self._aura_state.get("mood_buffer", 0.5)
            new_refl_count = self._aura_state.get("reflection_count", 0)
            new_entity = self._aura_state.get("active_entity")

        if abs(new_mood - old_mood) > 0.05:
            self._aura_events.trigger_mood_shift(new_mood - old_mood)
        if new_refl_count > old_refl_count:
            self._aura_events.trigger_reflexion("")
            self._aura_push_notification("\U0001f9e0 New reflection", "#00FF4D")
        if new_entity and new_entity != old_entity:
            self._aura_events.trigger_entity_session()
            name = new_entity.get("name", "Entity") if isinstance(new_entity, dict) else str(new_entity)
            self._aura_push_notification(f"\u26a1 {name} session started", "#FF00CC")

        # Check for significant state changes → notifications
        self._aura_check_state_notifications()

    def _aura_db_query(self, db_path, sql):
        """Execute SQL on a read-only SQLite connection, return one row."""
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=2.0)
        try:
            return conn.execute(sql).fetchone()
        finally:
            conn.close()

    def _aura_db_query_all(self, db_path, sql):
        """Execute SQL on a read-only SQLite connection, return all rows."""
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=2.0)
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()

    def _aura_api_get(self, url, timeout=1.5):
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except Exception:
            return None

    def _aura_api_post(self, url, data=None, timeout=1.5):
        try:
            body = json.dumps(data or {}).encode()
            req = urllib.request.Request(
                url, data=body, method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────
    # External Event Hooks
    # ──────────────────────────────────────────────────────────────

    def _aura_on_chat_message(self):
        if self._aura_open:
            if self._aura_using_headless:
                # Massive burst for headless — dense circle crossing all zones
                burst_mask = self._aura_events.trigger_chat_burst()
                self._aura_engine.inject_cells(burst_mask)
                # Also fire expanding ripple for additional visual flair
                self._aura_events.trigger_chat_ripple()
            else:
                self._aura_events.trigger_chat_ripple()

    def _aura_on_threat(self):
        if self._aura_open:
            self._aura_events.trigger_threat()

    def _aura_on_titan_access(self):
        if self._aura_open:
            self._aura_events.trigger_titan_flash()

    # ──────────────────────────────────────────────────────────────
    # Reseed & Reposition
    # ──────────────────────────────────────────────────────────────

    def _aura_reseed(self):
        if self._aura_using_headless:
            return  # Headless service manages its own seeding
        try:
            with self._aura_state_lock:
                state = dict(self._aura_state)
            grid = seed_grid(state)
            self._aura_engine.set_grid(grid)
        except Exception as e:
            LOG.debug("Aura reseed error: %s", e)

    def _aura_reposition_panel(self):
        if self._aura_open and self._aura_win and not self._aura_animating:
            self._aura_set_panel_geom(self._aura_panel_size)
