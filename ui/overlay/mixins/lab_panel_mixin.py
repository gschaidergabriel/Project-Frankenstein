"""LabPanelMixin — Slide-out experiment lab feed panel.

Amber CRT terminal aesthetic — warm phosphor on black, scanlines,
flicker, screen tear. Oscilloscope/spectrum analyzer inspired.
Feeds from experiment_lab.db in real-time.
"""

from __future__ import annotations

import json
import logging
import math
import random
import sqlite3
import time
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

LOG = logging.getLogger("frank_overlay")

try:
    from config.paths import get_db
    _LAB_DB_PATH = get_db("experiment_lab")
except Exception:
    _LAB_DB_PATH = Path.home() / ".local" / "share" / "frank" / "db" / "experiment_lab.db"

_LAB_PANEL_WIDTH = 380
_SLIDE_OPEN_MS = 300
_SLIDE_CLOSE_MS = 200
_MAX_DISPLAY_ENTRIES = 50
_POLL_INTERVAL_MS = 15_000  # Check for new experiments every 15s

# Button styling — amber/gold to distinguish from green (L) and red (A)
_BTN_BG = "#0d0d0d"
_BTN_BG_HOVER = "#1a1a0d"
_BTN_BORDER_CLR = "#FF9500"
_BTN_BORDER_HOVER = "#FFD700"

# ── Amber CRT Palette ──
_CRT_BG = "#0a0905"
_CRT_BG_GLOW = "#0c0a06"          # Warm phosphor ambient
_CRT_FG = "#FFB347"               # Bright amber phosphor
_CRT_FG_DIM = "#886600"           # Dim amber (timestamps)
_CRT_FG_VDIM = "#443300"          # Very dim (UI chrome)
_CRT_SCANLINE = "#0d0c08"         # Subtle warm scanline
_CRT_EDGE = "#050403"             # Vignette edge
_CRT_FONT = ("Courier", 9)
_CRT_FONT_SM = ("Courier", 7)
_CRT_FONT_TINY = ("Courier", 4)
_CRT_FONT_TITLE = ("Courier", 10, "bold")

# Typewriter speed
_TYPEWRITER_MS = 14

# Station styling
_STATION_ICONS: Dict[str, str] = {
    "physics":     "\u269B",   # ⚛
    "chemistry":   "\u2697",   # ⚗
    "astronomy":   "\u2726",   # ✦
    "gol":         "\u25A3",   # ▣
    "math":        "\u03C0",   # π
    "electronics": "\u26A1",   # ⚡
}

_STATION_COLORS: Dict[str, str] = {
    "physics":     "#6699FF",   # Blue-white
    "chemistry":   "#66FF99",   # Neon green
    "astronomy":   "#C8A2FF",   # Lavender
    "gol":         "#4ECDC4",   # Teal
    "math":        "#FFD700",   # Gold
    "electronics": "#FF8C00",   # Orange
}

_STATION_LABELS: Dict[str, str] = {
    "physics":     "PHYSICS",
    "chemistry":   "CHEMISTRY",
    "astronomy":   "ASTRONOMY",
    "gol":         "GAME OF LIFE",
    "math":        "MATHEMATICS",
    "electronics": "ELECTRONICS",
}

_SOURCE_TAGS: Dict[str, str] = {
    "autonomous":  "AUTO",
    "hypothesis":  "HYPO",
    "research":    "RSCH",
    "sanctum":     "SCTM",
    "chat":        "CHAT",
}


class LabPanelMixin:
    """Mixin adding a slide-out amber CRT lab experiment feed panel."""

    # ── Init ─────────────────────────────────────────────────────

    def _init_lab_panel(self):
        self._lab_open: bool = False
        self._lab_animating: bool = False
        self._lab_win: Optional[tk.Toplevel] = None
        self._lab_text: Optional[tk.Text] = None
        self._lab_flicker_phase: float = 0.0
        self._lab_typing_active: bool = False
        self._lab_typing_queue: List[Dict] = []
        self._lab_last_id: int = 0  # Track last seen experiment ID
        self._lab_entries: List[Dict] = []
        self._lab_unread_count: int = 0

        self._lab_create_toggle_button()
        self.bind("<Configure>", self._lab_on_overlay_configure, add="+")

        # Background poll for new experiments
        self._lab_poll_thread_active = False

    # ── Toggle Button — 22×22 · Amber "E" ────────────────────────

    def _lab_create_toggle_button(self):
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
        self._lab_btn_text_id = btn.create_text(
            s // 2, s // 2,
            text="E", fill="#FFB347",
            font=("Consolas", 11, "bold"),
        )
        self._lab_btn_badge_id = btn.create_text(
            s - 2, 2, text="", fill="#ff3333",
            font=("Consolas", 7, "bold"), anchor="ne",
        )
        btn.bind("<Button-1>", lambda _: self._lab_toggle())
        btn.bind("<Enter>", self._lab_btn_enter)
        btn.bind("<Leave>", self._lab_btn_leave)
        btn.pack(side="right", padx=(6, 0), pady=2)
        self._lab_btn = btn

    def _lab_btn_enter(self, _ev):
        self._lab_btn.configure(bg=_BTN_BG_HOVER)
        self._lab_btn.itemconfigure("border", outline=_BTN_BORDER_HOVER)

    def _lab_btn_leave(self, _ev):
        self._lab_btn.configure(bg=_BTN_BG)
        self._lab_btn.itemconfigure("border", outline=_BTN_BORDER_CLR)

    # ── Toggle / Open / Close ────────────────────────────────────

    def _lab_toggle(self):
        if self._lab_animating:
            return
        if self._lab_open:
            self._lab_close()
        else:
            self._lab_open_panel()

    def _lab_open_panel(self):
        # Mutual exclusion: close log and AURA panels
        if getattr(self, "_log_open", False) and hasattr(self, "_log_close"):
            self._log_close()
        if getattr(self, "_aura_open", False) and hasattr(self, "_aura_close"):
            self._aura_close()

        # Load experiments from DB
        self._lab_entries = self._lab_load_from_db()

        panel_h = self.winfo_height()
        win = tk.Toplevel(self)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=_CRT_EDGE)

        ox = self.winfo_rootx() + self.winfo_width()
        oy = self.winfo_rooty()
        win.geometry(f"1x{panel_h}+{ox}+{oy}")
        win.update_idletasks()

        self._lab_win = win
        self._lab_build_panel(win, panel_h)

        self._lab_animating = True
        self._lab_animate_open(_LAB_PANEL_WIDTH, time.monotonic(), _SLIDE_OPEN_MS)

        self._lab_unread_count = 0
        self._lab_update_badge()

        # Start polling for new experiments
        self._lab_poll_thread_active = True
        self._lab_schedule_poll()

    def _lab_animate_open(self, target_w, t_start, duration_ms):
        if not self._lab_win or not self._lab_win.winfo_exists():
            self._lab_animating = False
            return
        elapsed = (time.monotonic() - t_start) * 1000
        if elapsed >= duration_ms:
            self._lab_set_panel_geom(target_w)
            self._lab_animating = False
            self._lab_open = True
            return
        t = elapsed / duration_ms
        ease = 1 - (1 - t) ** 3
        w = max(1, int(target_w * ease))
        self._lab_set_panel_geom(w)
        self.after(16, lambda: self._lab_animate_open(target_w, t_start, duration_ms))

    def _lab_close(self):
        self._lab_typing_active = False
        self._lab_typing_queue.clear()
        self._lab_poll_thread_active = False
        self._lab_animating = True
        self._lab_animate_close(
            _LAB_PANEL_WIDTH, time.monotonic(), _SLIDE_CLOSE_MS,
        )

    def _lab_animate_close(self, start_w, t_start, duration_ms):
        if not self._lab_win or not self._lab_win.winfo_exists():
            self._lab_animating = False
            self._lab_open = False
            return
        elapsed = (time.monotonic() - t_start) * 1000
        if elapsed >= duration_ms:
            self._lab_close_done()
            return
        t = elapsed / duration_ms
        ease = t * t
        w = max(1, int(start_w * (1 - ease)))
        self._lab_set_panel_geom(w)
        self.after(16, lambda: self._lab_animate_close(start_w, t_start, duration_ms))

    def _lab_close_done(self):
        self._lab_animating = False
        self._lab_open = False
        self._lab_poll_thread_active = False
        if self._lab_win and self._lab_win.winfo_exists():
            self._lab_win.destroy()
        self._lab_win = None
        self._lab_text = None

    def _lab_set_panel_geom(self, w):
        try:
            ox = self.winfo_rootx() + self.winfo_width()
            oy = self.winfo_rooty()
            h = self.winfo_height()
            self._lab_win.geometry(f"{w}x{h}+{ox}+{oy}")
        except Exception:
            pass

    def _lab_on_overlay_configure(self, _event):
        if self._lab_open and self._lab_win and not self._lab_animating:
            try:
                self._lab_set_panel_geom(_LAB_PANEL_WIDTH)
            except Exception:
                pass

    def _lab_reposition_panel(self):
        if self._lab_open and self._lab_win and not self._lab_animating:
            self._lab_set_panel_geom(_LAB_PANEL_WIDTH)

    # ── Panel UI — Amber CRT Terminal ─────────────────────────────

    def _lab_build_panel(self, win, panel_h):
        outer = tk.Frame(win, bg=_CRT_EDGE)
        outer.pack(fill="both", expand=True)

        inner = tk.Frame(outer, bg=_CRT_BG)
        inner.pack(fill="both", expand=True, padx=2, pady=2)

        # Top vignette
        for v in ["#040302", "#060503", "#080704"]:
            tk.Frame(inner, bg=v, height=1).pack(fill="x", side="top")

        # Header
        hdr = tk.Frame(inner, bg=_CRT_BG, height=28)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Frame(hdr, bg=_CRT_FG_VDIM, height=1).pack(fill="x", side="top")
        tk.Label(
            hdr, text="  LAB // EXPERIMENT FEED", bg=_CRT_BG, fg=_CRT_FG_DIM,
            font=_CRT_FONT_SM, anchor="w",
        ).pack(side="left", fill="x", expand=True, pady=(3, 0))

        # Stats label (right side of header)
        self._lab_stats_label = tk.Label(
            hdr, text="", bg=_CRT_BG, fg=_CRT_FG_VDIM,
            font=("Courier", 7),
        )
        self._lab_stats_label.pack(side="right", padx=6)
        self._lab_update_stats()

        tk.Frame(inner, bg=_CRT_FG_VDIM, height=1).pack(fill="x")

        # CRT text area
        txt = tk.Text(
            inner, bg=_CRT_BG_GLOW, fg=_CRT_FG, font=_CRT_FONT,
            wrap="word", padx=8, pady=6,
            insertbackground=_CRT_BG, selectbackground="#332200",
            highlightthickness=0, borderwidth=0,
            cursor="arrow", spacing3=2,
        )
        scrollbar = tk.Scrollbar(
            inner, orient="vertical", command=txt.yview,
            bg="#1a1000", troughcolor="#000000",
            activebackground="#332200", width=4,
        )
        txt.configure(yscrollcommand=scrollbar.set)

        # Bottom vignette
        bottom_vig = tk.Frame(inner, bg=_CRT_BG)
        bottom_vig.pack(fill="x", side="bottom")
        for v in ["#080704", "#060503", "#040302"]:
            tk.Frame(bottom_vig, bg=v, height=1).pack(fill="x")

        scrollbar.pack(side="right", fill="y")
        txt.pack(fill="both", expand=True)

        # Scroll isolation
        def _lab_scroll(event):
            txt.yview_scroll(-1 if event.num == 4 else 1, "units")
            return "break"
        for w in (txt, inner, outer, win):
            w.bind("<Button-4>", _lab_scroll)
            w.bind("<Button-5>", _lab_scroll)

        # CRT text tags
        txt.tag_configure("timestamp", foreground=_CRT_FG_DIM, font=_CRT_FONT_SM)
        txt.tag_configure("message", foreground=_CRT_FG, font=_CRT_FONT)
        txt.tag_configure("separator", foreground="#1a1408", font=_CRT_FONT_TINY,
                          spacing3=4)
        txt.tag_configure("scanline", background=_CRT_SCANLINE)
        txt.tag_configure("station_rule", foreground=_CRT_FG_VDIM,
                          font=("Courier", 8))
        txt.tag_configure("source_tag", foreground=_CRT_FG_DIM,
                          font=("Courier", 7))
        txt.tag_configure("narration", foreground=_CRT_FG,
                          font=("Courier", 8), lmargin1=8, lmargin2=8,
                          spacing1=1, spacing3=1)
        txt.tag_configure("empty_msg", foreground=_CRT_FG_VDIM,
                          font=("Courier", 9), justify="center")

        # Station-specific color tags
        for station, color in _STATION_COLORS.items():
            txt.tag_configure(f"hdr_{station}", foreground=color,
                              font=_CRT_FONT_TITLE)
            txt.tag_configure(f"icon_{station}", foreground=color,
                              font=("Courier", 12, "bold"))
            txt.tag_configure(f"nar_{station}", foreground=color,
                              font=("Courier", 8), lmargin1=8, lmargin2=8,
                              spacing1=1, spacing3=1)

        self._lab_text = txt

        # Render existing entries
        if self._lab_entries:
            for entry in self._lab_entries:
                self._lab_render_entry_instant(entry)
        else:
            txt.configure(state="normal")
            txt.insert("end", "\n\n", "separator")
            txt.insert("end", "  No experiments yet.\n", "empty_msg")
            txt.insert("end", "  Frank runs simulations\n", "empty_msg")
            txt.insert("end", "  during idle thinking.\n", "empty_msg")
            txt.configure(state="disabled")

        self._lab_apply_scanlines()
        txt.configure(state="disabled")
        txt.see("end")

        # CRT effects
        self._lab_crt_flicker()
        self._lab_schedule_tear()

    # ── Entry Rendering ──────────────────────────────────────────

    def _lab_render_entry_instant(self, entry: Dict):
        if not self._lab_text:
            return
        txt = self._lab_text
        was_disabled = str(txt.cget("state")) == "disabled"
        if was_disabled:
            txt.configure(state="normal")

        station = entry.get("station", "unknown")
        icon = _STATION_ICONS.get(station, "\u2022")
        label = _STATION_LABELS.get(station, station.upper())
        ts = entry.get("ts_display", "")
        source = _SOURCE_TAGS.get(entry.get("source", ""), "")
        narration = entry.get("narration", "")
        duration = entry.get("duration_ms", 0)

        hdr_tag = f"hdr_{station}" if station in _STATION_COLORS else "message"
        icon_tag = f"icon_{station}" if station in _STATION_COLORS else "message"
        nar_tag = f"nar_{station}" if station in _STATION_COLORS else "narration"

        # Station header line
        txt.insert("end", f" {icon} ", icon_tag)
        txt.insert("end", f"{label}", hdr_tag)
        txt.insert("end", f"  {ts}", "timestamp")
        if source:
            txt.insert("end", f"  [{source}]", "source_tag")
        if duration > 0:
            txt.insert("end", f"  {duration:.0f}ms", "source_tag")
        txt.insert("end", "\n")

        # Thin rule under header
        txt.insert("end", " \u2500" * 20 + "\n", "station_rule")

        # Narration body — clean up the raw lab output
        clean = self._lab_clean_narration(narration, station)
        for line in clean.split("\n"):
            txt.insert("end", f"{line}\n", nar_tag)

        # Bottom separator
        txt.insert("end", "\u2501" * 24 + "\n", "separator")

        if was_disabled:
            txt.configure(state="disabled")

    def _lab_render_entry_typewriter(self, entry: Dict):
        if not self._lab_text or not self._lab_text.winfo_exists():
            self._lab_typing_active = False
            return

        txt = self._lab_text
        txt.configure(state="normal")

        station = entry.get("station", "unknown")
        icon = _STATION_ICONS.get(station, "\u2022")
        label = _STATION_LABELS.get(station, station.upper())
        ts = entry.get("ts_display", "")
        source = _SOURCE_TAGS.get(entry.get("source", ""), "")
        duration = entry.get("duration_ms", 0)
        narration = entry.get("narration", "")

        hdr_tag = f"hdr_{station}" if station in _STATION_COLORS else "message"
        icon_tag = f"icon_{station}" if station in _STATION_COLORS else "message"
        nar_tag = f"nar_{station}" if station in _STATION_COLORS else "narration"

        # Header appears instantly
        txt.insert("end", f" {icon} ", icon_tag)
        txt.insert("end", f"{label}", hdr_tag)
        txt.insert("end", f"  {ts}", "timestamp")
        if source:
            txt.insert("end", f"  [{source}]", "source_tag")
        if duration > 0:
            txt.insert("end", f"  {duration:.0f}ms", "source_tag")
        txt.insert("end", "\n")
        txt.insert("end", " \u2500" * 20 + "\n", "station_rule")
        txt.configure(state="disabled")
        txt.see("end")

        # Typewriter the narration
        clean = self._lab_clean_narration(narration, station)
        self._lab_typing_active = True
        self._lab_typing_station = station
        self._lab_typewriter_step(clean, 0, nar_tag)

    def _lab_typewriter_step(self, msg: str, idx: int, nar_tag: str):
        if not self._lab_text or not self._lab_text.winfo_exists():
            self._lab_typing_active = False
            return
        if not self._lab_typing_active:
            try:
                self._lab_text.configure(state="normal")
                self._lab_text.insert("end", msg[idx:] + "\n", nar_tag)
                self._lab_text.insert("end", "\u2501" * 24 + "\n", "separator")
                self._lab_apply_scanlines()
                self._lab_text.configure(state="disabled")
                self._lab_text.see("end")
            except Exception:
                pass
            self._lab_process_typing_queue()
            return

        try:
            self._lab_text.configure(state="normal")
            if idx < len(msg):
                self._lab_text.insert("end", msg[idx], nar_tag)
                self._lab_text.configure(state="disabled")
                self._lab_text.see("end")
                delay = random.randint(8, 20)
                self.after(delay, lambda: self._lab_typewriter_step(
                    msg, idx + 1, nar_tag))
            else:
                self._lab_text.insert("end", "\n", nar_tag)
                self._lab_text.insert("end", "\u2501" * 24 + "\n", "separator")
                self._lab_apply_scanlines()
                self._lab_text.configure(state="disabled")
                self._lab_text.see("end")
                self._lab_typing_active = False
                self._lab_process_typing_queue()
        except Exception:
            self._lab_typing_active = False

    def _lab_process_typing_queue(self):
        if self._lab_typing_queue and self._lab_text:
            entry = self._lab_typing_queue.pop(0)
            self._lab_render_entry_typewriter(entry)

    @staticmethod
    def _lab_clean_narration(narration: str, station: str) -> str:
        """Clean raw lab narration for display."""
        lines = narration.strip().split("\n")
        # Remove the first "=== STATION ===" header line (redundant with our UI header)
        if lines and lines[0].startswith("==="):
            lines = lines[1:]
        # Remove trailing "===" separator
        while lines and lines[-1].strip().startswith("==="):
            lines.pop()
        # Strip leading whitespace from each line
        cleaned = "\n".join(line.strip() for line in lines if line.strip())
        return cleaned if cleaned else "(no result)"

    def _lab_apply_scanlines(self):
        if not self._lab_text:
            return
        try:
            txt = self._lab_text
            txt.tag_remove("scanline", "1.0", "end")
            line_count = int(txt.index("end-1c").split(".")[0])
            for i in range(1, line_count + 1, 2):
                txt.tag_add("scanline", f"{i}.0", f"{i}.end")
        except Exception:
            pass

    # ── CRT Flicker (amber) ──────────────────────────────────────

    def _lab_crt_flicker(self):
        try:
            if not self._lab_text or not self._lab_text.winfo_exists():
                return
            self._lab_flicker_phase += 0.08
            t = (math.sin(self._lab_flicker_phase) + 1) / 2
            t = max(0, min(1, t + random.uniform(-0.03, 0.03)))
            # Amber: R=0xE0..0xFF, G=0xA0..0xB3
            r = int(0xE0 + t * 0x1F)
            g = int(0xA0 + t * 0x13)
            self._lab_text.tag_configure(
                "message", foreground=f"#{r:02x}{g:02x}47",
            )
            s = int(0x0B + t * 0x04)
            self._lab_text.tag_configure(
                "scanline", background=f"#{s:02x}{s:02x}{s - 2:02x}",
            )
        except Exception:
            pass
        if self._lab_open:
            self.after(100, self._lab_crt_flicker)

    # ── Screen Tear ──────────────────────────────────────────────

    def _lab_schedule_tear(self):
        if not self._lab_text or not self._lab_open:
            return
        delay = random.randint(10000, 20000)
        self.after(delay, self._lab_screen_tear)

    def _lab_screen_tear(self):
        if not self._lab_text or not self._lab_text.winfo_exists():
            return
        try:
            line_count = int(self._lab_text.index("end-1c").split(".")[0])
            if line_count < 3:
                self._lab_schedule_tear()
                return
            line = random.randint(1, max(1, line_count - 1))
            shift = random.randint(2, 4)
            spaces = " " * shift
            self._lab_text.configure(state="normal")
            self._lab_text.insert(f"{line}.0", spaces)
            self._lab_text.configure(state="disabled")
            self.after(
                random.randint(60, 100),
                lambda: self._lab_tear_restore(line, shift),
            )
        except Exception:
            pass
        self._lab_schedule_tear()

    def _lab_tear_restore(self, line: int, count: int):
        try:
            if self._lab_text and self._lab_text.winfo_exists():
                self._lab_text.configure(state="normal")
                self._lab_text.delete(f"{line}.0", f"{line}.{count}")
                self._lab_text.configure(state="disabled")
        except Exception:
            pass

    # ── DB Loading ───────────────────────────────────────────────

    def _lab_load_from_db(self) -> List[Dict]:
        """Load recent experiments from experiment_lab.db."""
        entries = []
        try:
            if not _LAB_DB_PATH.exists():
                return entries
            conn = sqlite3.connect(str(_LAB_DB_PATH), timeout=2)
            conn.execute("PRAGMA journal_mode=WAL")
            try:
                rows = conn.execute(
                    "SELECT id, ts, station, narration, source, duration_ms "
                    "FROM experiments ORDER BY id DESC LIMIT ?",
                    (_MAX_DISPLAY_ENTRIES,),
                ).fetchall()
                for row in reversed(rows):  # Oldest first
                    exp_id, ts, station, narration, source, dur = row
                    entries.append({
                        "id": exp_id,
                        "station": station,
                        "narration": narration or "",
                        "source": source or "unknown",
                        "duration_ms": dur or 0,
                        "ts_display": datetime.fromtimestamp(ts).strftime(
                            "%H:%M") if ts else "",
                    })
                    if exp_id > self._lab_last_id:
                        self._lab_last_id = exp_id
            finally:
                conn.close()
        except Exception as e:
            LOG.debug("Lab panel DB load failed: %s", e)
        return entries

    def _lab_check_new_experiments(self) -> List[Dict]:
        """Check for experiments newer than last seen ID."""
        new_entries = []
        try:
            if not _LAB_DB_PATH.exists():
                return new_entries
            conn = sqlite3.connect(str(_LAB_DB_PATH), timeout=2)
            conn.execute("PRAGMA journal_mode=WAL")
            try:
                rows = conn.execute(
                    "SELECT id, ts, station, narration, source, duration_ms "
                    "FROM experiments WHERE id > ? ORDER BY id ASC",
                    (self._lab_last_id,),
                ).fetchall()
                for row in rows:
                    exp_id, ts, station, narration, source, dur = row
                    new_entries.append({
                        "id": exp_id,
                        "station": station,
                        "narration": narration or "",
                        "source": source or "unknown",
                        "duration_ms": dur or 0,
                        "ts_display": datetime.fromtimestamp(ts).strftime(
                            "%H:%M") if ts else "",
                    })
                    self._lab_last_id = exp_id
            finally:
                conn.close()
        except Exception as e:
            LOG.debug("Lab panel new experiment check failed: %s", e)
        return new_entries

    # ── Polling ──────────────────────────────────────────────────

    def _lab_schedule_poll(self):
        if not self._lab_poll_thread_active or not self._lab_open:
            return
        self.after(_POLL_INTERVAL_MS, self._lab_poll_new)

    def _lab_poll_new(self):
        if not self._lab_open or not self._lab_poll_thread_active:
            return

        new = self._lab_check_new_experiments()
        for entry in new:
            self._lab_entries.append(entry)
            if self._lab_text:
                if self._lab_typing_active:
                    self._lab_typing_queue.append(entry)
                else:
                    self._lab_render_entry_typewriter(entry)

        self._lab_update_stats()
        self._lab_schedule_poll()

    # ── Stats ────────────────────────────────────────────────────

    def _lab_update_stats(self):
        try:
            n = len(self._lab_entries)
            if hasattr(self, "_lab_stats_label"):
                self._lab_stats_label.configure(
                    text=f"{n} exp" if n else "")
        except Exception:
            pass

    # ── Badge ────────────────────────────────────────────────────

    def _lab_update_badge(self):
        try:
            if self._lab_unread_count > 0:
                text = str(min(self._lab_unread_count, 99))
                self._lab_btn.itemconfigure(self._lab_btn_badge_id, text=text)
            else:
                self._lab_btn.itemconfigure(self._lab_btn_badge_id, text="")
        except Exception:
            pass

    def _lab_notify_new_experiment(self):
        """Called externally when a new experiment completes."""
        if not self._lab_open:
            self._lab_unread_count += 1
            self._lab_update_badge()
