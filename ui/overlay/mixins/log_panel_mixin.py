"""LogPanelMixin — Slide-out daemon activity log panel.

CRT retro terminal aesthetic — green phosphor on black, scanlines,
flicker, screen tear, typewriter effect. Amstrad/Fallout inspired.
"""

from __future__ import annotations

import json
import logging
import math
import random
import time
import tkinter as tk
from pathlib import Path
from typing import Dict, List, Optional

from config.paths import AICORE_DATA

LOG = logging.getLogger("frank_overlay")

_LOG_FILE = AICORE_DATA / "log_panel.json"
_MAX_PERSISTENT = 30

LOG_CATEGORIES = frozenset({
    "consciousness", "dream", "entity",
    "therapist", "mirror", "atlas", "muse",
})

_LOG_PANEL_WIDTH = 340
_SLIDE_OPEN_MS = 300
_SLIDE_CLOSE_MS = 200
_MAX_LOG_ENTRIES = 200

_LOG_ICONS: Dict[str, str] = {
    "consciousness": "\U0001F9E0",
    "dream":         "\U0001F4AD",
    "entity":        "\U0001F464",
    "therapist":     "\U0001F49A",
    "mirror":        "\u2694\uFE0F",
    "atlas":         "\U0001F9ED",
    "muse":          "\U0001F3A8",
}

_CAT_SHORT: Dict[str, str] = {
    "consciousness": "CSCN",
    "dream":         "DREM",
    "entity":        "ENTY",
    "therapist":     "THRP",
    "mirror":        "MIRR",
    "atlas":         "ATLS",
    "muse":          "MUSE",
}

# Button styling
_BTN_BG = "#0d0d0d"
_BTN_BG_HOVER = "#1a1a1a"
_BTN_BORDER_CLR = "#00cc44"
_BTN_BORDER_HOVER = "#00fff9"

# ── CRT Palette (Amstrad / Fallout Terminal) ──
_CRT_BG = "#0a0a0a"
_CRT_BG_GLOW = "#0a0c0a"      # Very subtle green tint — phosphor ambient
_CRT_FG = "#00FF41"            # Bright green phosphor
_CRT_FG_DIM = "#005500"        # Dim green (timestamps)
_CRT_FG_VDIM = "#003300"       # Very dim (UI chrome)
_CRT_SCANLINE = "#0d0e0d"      # Subtle scanline band
_CRT_EDGE = "#050505"          # Vignette edge
_CRT_FONT = ("Courier", 9)
_CRT_FONT_SM = ("Courier", 7)
_CRT_FONT_TINY = ("Courier", 4)

# Typewriter speed (ms per character)
_TYPEWRITER_MS = 18

# Entity accent colours (CRT-compatible neon tones)
_ENTITY_COLORS: Dict[str, str] = {
    "entity":    "#FFD700",   # Gold
    "therapist": "#00CCA3",   # Teal (Dr. Hibbert)
    "mirror":    "#FF9933",   # Amber (Kairos)
    "atlas":     "#33CCFF",   # Cyan
    "muse":      "#CC66FF",   # Violet (Echo)
    "dream":     "#6699FF",   # Soft blue
}
_ACCENT_CATS = frozenset(_ENTITY_COLORS)


class LogPanelMixin:
    """Mixin adding a slide-out CRT log panel for daemon activity."""

    # ── Init ─────────────────────────────────────────────────────

    def _init_log_panel(self):
        self._log_open: bool = False
        self._log_animating: bool = False
        self._log_win: Optional[tk.Toplevel] = None
        self._log_entries: List[Dict] = self._log_load_persistent()
        self._log_unread_count: int = 0
        self._log_text: Optional[tk.Text] = None
        self._log_flicker_phase: float = 0.0
        self._log_typing_active: bool = False
        self._log_typing_queue: List[Dict] = []

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
        if getattr(self, "_aura_open", False) and hasattr(self, "_aura_close"):
            self._aura_close()

        panel_h = self.winfo_height()
        win = tk.Toplevel(self)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="#003300")

        ox = self.winfo_rootx() + self.winfo_width()
        oy = self.winfo_rooty()
        win.geometry(f"1x{panel_h}+{ox}+{oy}")
        win.update_idletasks()

        self._log_win = win
        self._log_build_panel(win, panel_h)

        self._log_animating = True
        self._log_animate_open(_LOG_PANEL_WIDTH, time.monotonic(), _SLIDE_OPEN_MS)

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
        ease = 1 - (1 - t) ** 3
        w = max(1, int(target_w * ease))
        self._log_set_panel_geom(w)
        self.after(16, lambda: self._log_animate_open(target_w, t_start, duration_ms))

    def _log_close(self):
        self._log_typing_active = False
        self._log_typing_queue.clear()
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
        ease = t * t
        w = max(1, int(start_w * (1 - ease)))
        self._log_set_panel_geom(w)
        self.after(16, lambda: self._log_animate_close(start_w, t_start, duration_ms))

    def _log_close_done(self):
        self._log_animating = False
        self._log_open = False
        if self._log_win and self._log_win.winfo_exists():
            self._log_win.destroy()
        self._log_win = None
        self._log_text = None

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

    # ── Panel UI — CRT Terminal ──────────────────────────────────

    def _log_build_panel(self, win, panel_h):
        # Outer frame — black edge for vignette
        outer = tk.Frame(win, bg=_CRT_EDGE)
        outer.pack(fill="both", expand=True)

        inner = tk.Frame(outer, bg=_CRT_BG)
        inner.pack(fill="both", expand=True, padx=2, pady=2)

        # Top vignette gradient (dark → panel bg)
        for v in ["#030303", "#050505", "#070707"]:
            tk.Frame(inner, bg=v, height=1).pack(fill="x", side="top")

        # Header
        hdr = tk.Frame(inner, bg=_CRT_BG, height=28)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Frame(hdr, bg=_CRT_FG_VDIM, height=1).pack(fill="x", side="top")
        tk.Label(
            hdr, text="  LOG // DAEMON ACTIVITY", bg=_CRT_BG, fg=_CRT_FG_DIM,
            font=_CRT_FONT_SM, anchor="w",
        ).pack(side="left", fill="x", expand=True, pady=(3, 0))

        # CLR button
        clear_btn = tk.Label(
            hdr, text="CLR", bg=_CRT_BG, fg=_CRT_FG_VDIM,
            font=("Courier", 7), cursor="hand2",
        )
        clear_btn.pack(side="right", padx=6)
        clear_btn.bind("<Button-1>", lambda _: self._log_clear_entries())
        clear_btn.bind("<Enter>", lambda e: clear_btn.configure(fg=_CRT_FG))
        clear_btn.bind("<Leave>", lambda e: clear_btn.configure(fg=_CRT_FG_VDIM))

        tk.Frame(inner, bg=_CRT_FG_VDIM, height=1).pack(fill="x")

        # CRT text area
        txt = tk.Text(
            inner, bg=_CRT_BG_GLOW, fg=_CRT_FG, font=_CRT_FONT,
            wrap="word", padx=8, pady=6,
            insertbackground=_CRT_BG, selectbackground="#003300",
            highlightthickness=0, borderwidth=0,
            cursor="arrow", spacing3=2,
        )
        scrollbar = tk.Scrollbar(
            inner, orient="vertical", command=txt.yview,
            bg="#001a00", troughcolor="#000000",
            activebackground="#003300", width=4,
        )
        txt.configure(yscrollcommand=scrollbar.set)

        # Bottom vignette gradient
        bottom_vig = tk.Frame(inner, bg=_CRT_BG)
        bottom_vig.pack(fill="x", side="bottom")
        for v in ["#070707", "#050505", "#030303"]:
            tk.Frame(bottom_vig, bg=v, height=1).pack(fill="x")

        scrollbar.pack(side="right", fill="y")
        txt.pack(fill="both", expand=True)

        # Scroll isolation
        def _log_scroll(event):
            txt.yview_scroll(-1 if event.num == 4 else 1, "units")
            return "break"
        for w in (txt, inner, outer, win):
            w.bind("<Button-4>", _log_scroll)
            w.bind("<Button-5>", _log_scroll)

        # CRT text tags
        txt.tag_configure("timestamp", foreground=_CRT_FG_DIM, font=_CRT_FONT_SM)
        txt.tag_configure("message", foreground=_CRT_FG, font=_CRT_FONT)
        txt.tag_configure("separator", foreground="#0a1a0a", font=_CRT_FONT_TINY, spacing3=6)
        txt.tag_configure("scanline", background=_CRT_SCANLINE)
        txt.tag_configure("cursor_blink", foreground=_CRT_FG, font=_CRT_FONT)

        # Entity / dream accent tags
        for cat, color in _ENTITY_COLORS.items():
            txt.tag_configure(f"hdr_{cat}", foreground=color, font=_CRT_FONT_SM)
            txt.tag_configure(f"msg_{cat}", foreground=color, font=_CRT_FONT)
            txt.tag_configure(f"accent_{cat}", foreground=color, font=("Courier", 9, "bold"))

        self._log_text = txt

        # Render existing entries (instant, no typewriter for history)
        for entry in self._log_entries:
            self._log_render_entry_instant(entry)

        self._log_apply_scanlines()
        txt.configure(state="disabled")
        txt.see("end")

        # Start persistent CRT effects
        self._log_crt_flicker()
        self._log_schedule_tear()

    # ── Entry Rendering ──────────────────────────────────────────

    def _log_render_entry_instant(self, entry: Dict):
        """Render entry instantly (for history/bulk load)."""
        if not self._log_text:
            return
        txt = self._log_text
        was_disabled = str(txt.cget("state")) == "disabled"
        if was_disabled:
            txt.configure(state="normal")

        ts = entry.get("ts_display", "")
        cat = _CAT_SHORT.get(entry.get("category", ""), "LOG")
        icon = entry.get("icon", "")
        msg = entry.get("text", "")
        category = entry.get("category", "")

        if category in _ACCENT_CATS:
            hdr_tag = f"hdr_{category}"
            msg_tag = f"msg_{category}"
            txt.insert("end", "\u258c ", f"accent_{category}")
            txt.insert("end", f"{ts} [{cat}] {icon}\n", hdr_tag)
            txt.insert("end", f"{msg}\n", msg_tag)
        else:
            txt.insert("end", f"  {ts} [{cat}] {icon}\n", "timestamp")
            txt.insert("end", f"{msg}\n", "message")

        txt.insert("end", "\u2500" * 24 + "\n", "separator")

        if was_disabled:
            txt.configure(state="disabled")

    def _log_render_entry_typewriter(self, entry: Dict):
        """Render entry with typewriter effect for the message."""
        if not self._log_text or not self._log_text.winfo_exists():
            self._log_typing_active = False
            return

        txt = self._log_text
        txt.configure(state="normal")

        ts = entry.get("ts_display", "")
        cat = _CAT_SHORT.get(entry.get("category", ""), "LOG")
        icon = entry.get("icon", "")
        msg = entry.get("text", "")
        category = entry.get("category", "")

        is_entity = category in _ACCENT_CATS
        msg_tag = f"msg_{category}" if is_entity else "message"

        # Header appears instantly
        if is_entity:
            txt.insert("end", "\u258c ", f"accent_{category}")
            txt.insert("end", f"{ts} [{cat}] {icon}\n", f"hdr_{category}")
        else:
            txt.insert("end", f"  {ts} [{cat}] {icon}\n", "timestamp")
        txt.configure(state="disabled")
        txt.see("end")

        # Message types character by character
        self._log_typing_active = True
        self._log_typewriter_step(msg, 0, msg_tag)

    def _log_typewriter_step(self, msg: str, idx: int, msg_tag: str = "message"):
        """Type one character at a time."""
        if not self._log_text or not self._log_text.winfo_exists():
            self._log_typing_active = False
            return
        if not self._log_typing_active:
            # Cancelled (panel closed) — dump remaining text
            try:
                self._log_text.configure(state="normal")
                self._log_text.insert("end", msg[idx:] + "\n", msg_tag)
                self._log_text.insert("end", "\u2500" * 24 + "\n", "separator")
                self._log_apply_scanlines()
                self._log_text.configure(state="disabled")
                self._log_text.see("end")
            except Exception:
                pass
            self._log_process_typing_queue()
            return

        try:
            self._log_text.configure(state="normal")
            if idx < len(msg):
                self._log_text.insert("end", msg[idx], msg_tag)
                self._log_text.configure(state="disabled")
                self._log_text.see("end")
                delay = random.randint(12, 28)
                self.after(delay, lambda: self._log_typewriter_step(msg, idx + 1, msg_tag))
            else:
                # Done typing message
                self._log_text.insert("end", "\n", msg_tag)
                self._log_text.insert("end", "\u2500" * 24 + "\n", "separator")
                self._log_apply_scanlines()
                self._log_text.configure(state="disabled")
                self._log_text.see("end")
                self._log_typing_active = False
                self._log_process_typing_queue()
        except Exception:
            self._log_typing_active = False

    def _log_process_typing_queue(self):
        """Process next queued entry for typewriter."""
        if self._log_typing_queue and self._log_text:
            entry = self._log_typing_queue.pop(0)
            self._log_render_entry_typewriter(entry)

    def _log_apply_scanlines(self):
        """Apply scanline effect to every other line."""
        if not self._log_text:
            return
        txt = self._log_text
        try:
            txt.tag_remove("scanline", "1.0", "end")
            line_count = int(txt.index("end-1c").split(".")[0])
            for i in range(1, line_count + 1, 2):
                txt.tag_add("scanline", f"{i}.0", f"{i}.end")
        except Exception:
            pass

    # ── CRT Flicker Animation ─────────────────────────────────────

    def _log_crt_flicker(self):
        """Subtle phosphor flicker — sin-wave + random noise."""
        try:
            if not self._log_text or not self._log_text.winfo_exists():
                return
            self._log_flicker_phase += 0.08
            t = (math.sin(self._log_flicker_phase) + 1) / 2
            # Random jitter for organic feel (±0.03)
            t = max(0, min(1, t + random.uniform(-0.03, 0.03)))
            # Green channel: 0xE0..0xFF (0.97-1.0 effective brightness)
            g = int(0xE0 + t * 0x1F)
            self._log_text.tag_configure(
                "message", foreground=f"#00{g:02x}41",
            )
            # Scanline brightness pulsates subtly
            s = int(0x0C + t * 0x04)
            self._log_text.tag_configure(
                "scanline", background=f"#{s:02x}{s + 1:02x}{s:02x}",
            )
        except Exception:
            pass
        self.after(100, self._log_crt_flicker)

    # ── Screen Tear / VHS Glitch ──────────────────────────────────

    def _log_schedule_tear(self):
        """Schedule next screen tear (8-15 seconds)."""
        if not self._log_text:
            return
        delay = random.randint(8000, 15000)
        self.after(delay, self._log_screen_tear)

    def _log_screen_tear(self):
        """Brief horizontal glitch — shift a random line then restore."""
        if not self._log_text or not self._log_text.winfo_exists():
            return
        try:
            line_count = int(self._log_text.index("end-1c").split(".")[0])
            if line_count < 3:
                self._log_schedule_tear()
                return

            line = random.randint(1, max(1, line_count - 1))
            shift = random.randint(2, 5)
            spaces = " " * shift

            self._log_text.configure(state="normal")
            self._log_text.insert(f"{line}.0", spaces)
            self._log_text.configure(state="disabled")

            # Restore after 60-100ms
            self.after(
                random.randint(60, 100),
                lambda: self._log_tear_restore(line, shift),
            )
        except Exception:
            pass
        self._log_schedule_tear()

    def _log_tear_restore(self, line: int, count: int):
        """Remove the glitch characters."""
        try:
            if self._log_text and self._log_text.winfo_exists():
                self._log_text.configure(state="normal")
                self._log_text.delete(f"{line}.0", f"{line}.{count}")
                self._log_text.configure(state="disabled")
        except Exception:
            pass

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
        }

        self._log_entries.append(entry)
        self._log_save_persistent()

        # Trim ring buffer
        if len(self._log_entries) > _MAX_LOG_ENTRIES:
            self._log_entries.pop(0)
            if self._log_text:
                try:
                    was_disabled = str(self._log_text.cget("state")) == "disabled"
                    if was_disabled:
                        self._log_text.configure(state="normal")
                    self._log_text.delete("1.0", "4.0")
                    if was_disabled:
                        self._log_text.configure(state="disabled")
                except Exception:
                    pass

        # Render with typewriter if panel is open
        if self._log_open and self._log_text:
            if self._log_typing_active:
                self._log_typing_queue.append(entry)
            else:
                self._log_render_entry_typewriter(entry)

        # Unread badge
        if not self._log_open:
            self._log_unread_count += 1
            self._log_update_badge()

        # Live-update AURA CRT if open
        self._log_update_aura_crt(entry)

    def _log_update_aura_crt(self, entry: Dict):
        """Push new entry to AURA's CRT monitor if it's open."""
        crt_text = getattr(self, "_aura_crt_text", None)
        if not crt_text:
            return
        try:
            if not crt_text.winfo_exists():
                return
            was_disabled = str(crt_text.cget("state")) == "disabled"
            if was_disabled:
                crt_text.configure(state="normal")

            ts = entry.get("ts_display", "")
            cat = _CAT_SHORT.get(entry.get("category", ""), "LOG")
            msg = entry.get("text", "")

            crt_text.insert("end", f"{ts} [{cat}]\n", "timestamp")
            crt_text.insert("end", f"{msg}\n", "message")
            crt_text.insert("end", "\u2500" * 30 + "\n", "separator")

            # Reapply scanlines
            crt_text.tag_remove("scanline", "1.0", "end")
            line_count = int(crt_text.index("end-1c").split(".")[0])
            for i in range(1, line_count + 1, 2):
                crt_text.tag_add("scanline", f"{i}.0", f"{i}.end")

            if was_disabled:
                crt_text.configure(state="disabled")
            crt_text.see("end")
        except Exception:
            pass

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
        self._log_entries.clear()
        self._log_unread_count = 0
        self._log_update_badge()
        self._log_save_persistent()
        self._log_typing_active = False
        self._log_typing_queue.clear()
        if self._log_text:
            try:
                self._log_text.configure(state="normal")
                self._log_text.delete("1.0", "end")
                self._log_text.configure(state="disabled")
            except Exception:
                pass

    # ── Persistence ──────────────────────────────────────────────

    def _log_load_persistent(self) -> List[Dict]:
        try:
            if _LOG_FILE.exists():
                data = json.loads(_LOG_FILE.read_text())
                return data[-_MAX_PERSISTENT:]
        except Exception as e:
            LOG.warning("Log panel load failed: %s", e)
        return []

    def _log_save_persistent(self):
        try:
            _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            to_save = []
            for e in self._log_entries[-_MAX_PERSISTENT:]:
                to_save.append({
                    k: v for k, v in e.items()
                    if k not in ("widget",)
                })
            _LOG_FILE.write_text(json.dumps(to_save, ensure_ascii=False))
        except Exception as e:
            LOG.warning("Log panel save failed: %s", e)
