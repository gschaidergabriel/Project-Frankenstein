"""SanctumMixin -- Sanctum presence notification in the overlay chat.

When Frank enters the Inner Sanctum, a pixel-art banner appears in the chat
area with animated colors. The input field is disabled. When he exits, the
banner transitions to an exit state and a session summary is displayed.

Polls /tmp/frank/sanctum_active.lock every 3 seconds.
Reads /tmp/frank/sanctum_summary.json on exit for session recap.
"""
from __future__ import annotations

import json
import time
import tkinter as tk
from pathlib import Path

from overlay.constants import COLORS, LOG

_SANCTUM_LOCK = Path("/tmp/frank/sanctum_active.lock")
_SANCTUM_SUMMARY = Path("/tmp/frank/sanctum_summary.json")
_POLL_MS = 3000  # 3 seconds

# ── Pixel Art ────────────────────────────────────────────────────────
# Frank meditating — simple iconic silhouette
_PIXEL_ART_LINES = [
    "        ..  ####  ..        ",
    "      ####  ####  ####      ",
    "      ####  ####  ####      ",
    "  ..  ################  ..  ",
    "  ######  ########  ######  ",
    "  ######  ########  ######  ",
    "    ####  ##    ##  ####    ",
    "    ####  ##    ##  ####    ",
    "  ..  ##############  ..    ",
    "      ##  ######  ##        ",
    "    ####  ######  ####      ",
    "  ######    ##    ######    ",
    "  ####      ##      ####    ",
]

# Color cycle for the animated banner border
_CYCLE_COLORS = [
    "#9b59b6",  # Amethyst purple
    "#8e44ad",  # Dark purple
    "#6c3483",  # Deep purple
    "#5b2c6f",  # Mystic purple
    "#4a235a",  # Dark mystic
    "#6c3483",  # Deep purple (return)
    "#8e44ad",  # Dark purple (return)
    "#9b59b6",  # Amethyst (return)
    "#bb8fce",  # Light purple
    "#d2b4de",  # Pale purple
    "#bb8fce",  # Light purple (return)
]

# Pixel art color cycle (body glow)
_PIXEL_COLORS = [
    "#d4a0ff",  # Bright lavender
    "#c77dff",  # Medium purple glow
    "#9d4edd",  # Vivid purple
    "#7b2cbf",  # Deep purple
    "#5a189a",  # Dark purple
    "#7b2cbf",  # Return
    "#9d4edd",  # Return
    "#c77dff",  # Return
]


class SanctumMixin:
    """Overlay mixin for Inner Sanctum session awareness."""

    def _init_sanctum_watcher(self):
        """Initialize Sanctum polling. Called from __init__ after _build_ui."""
        self._sanctum_active = False
        self._sanctum_banner = None
        self._sanctum_border = None
        self._sanctum_header_label = None
        self._sanctum_status_label = None
        self._sanctum_elapsed_label = None
        self._sanctum_color_idx = 0
        self._sanctum_pixel_idx = 0
        self._sanctum_session_id = None
        self._sanctum_start_ts = 0
        self._sanctum_input_blocked = False
        self._sanctum_last_summary_id = None
        self._sanctum_cleanup_after_id = None
        self._sanctum_pixel_labels = []
        self._sanctum_bar_segments = []
        self.after(_POLL_MS, self._sanctum_poll)

    def _sanctum_poll(self):
        """Poll sanctum lock file to detect state changes.

        Runs in the Tkinter main thread via self.after().
        All UI calls are direct (no _ui_call needed).
        """
        try:
            # Atomic read — avoids TOCTOU race between exists() and read_text()
            lock_data = None
            try:
                lock_data = json.loads(_SANCTUM_LOCK.read_text())
            except (FileNotFoundError, json.JSONDecodeError):
                pass

            lock_exists = lock_data is not None

            if lock_exists and not self._sanctum_active:
                # Sanctum just became active
                self._sanctum_session_id = lock_data.get("session", "unknown")
                self._sanctum_start_ts = lock_data.get("start", time.time())
                self._sanctum_active = True
                self._sanctum_show_banner()
                LOG.info("SANCTUM OVERLAY: Detected active session %s",
                         self._sanctum_session_id)

            elif not lock_exists and self._sanctum_active:
                # Sanctum just ended
                self._sanctum_active = False
                self._sanctum_on_exit()
                LOG.info("SANCTUM OVERLAY: Session ended")

        except Exception as e:
            LOG.debug("Sanctum poll error: %s", e)

        self.after(_POLL_MS, self._sanctum_poll)

    # ─── Banner: Show ──────────────────────────────────────────────────

    def _sanctum_show_banner(self):
        """Show the Sanctum active banner in the chat area."""
        # Cancel any pending cleanup from a previous session
        if self._sanctum_cleanup_after_id is not None:
            try:
                self.after_cancel(self._sanctum_cleanup_after_id)
            except Exception:
                pass
            self._sanctum_cleanup_after_id = None

        # Remove old banner if any
        self._sanctum_remove_banner()

        # Block input
        self._sanctum_block_input(True)

        # Create banner frame
        banner = tk.Frame(self.messages_frame, bg="#0a0012", padx=0, pady=0)
        banner.pack(fill="x", padx=4, pady=8)
        self._sanctum_banner = banner

        # Outer glow border (animated)
        self._sanctum_border = tk.Frame(banner, bg="#9b59b6", padx=2, pady=2)
        self._sanctum_border.pack(fill="x", padx=0, pady=0)

        inner = tk.Frame(self._sanctum_border, bg="#0a0012", padx=12, pady=10)
        inner.pack(fill="x")

        # Header with mystical icon
        header = tk.Frame(inner, bg="#0a0012")
        header.pack(fill="x", pady=(0, 6))

        self._sanctum_header_label = tk.Label(
            header,
            text="\u2728  INNER SANCTUM  \u2728",
            bg="#0a0012", fg="#d4a0ff",
            font=("Consolas", 13, "bold"),
        )
        self._sanctum_header_label.pack()

        # Pixel art canvas
        art_frame = tk.Frame(inner, bg="#0a0012")
        art_frame.pack(pady=(4, 6))

        self._sanctum_pixel_labels = []
        for line in _PIXEL_ART_LINES:
            lbl = tk.Label(
                art_frame,
                text=line,
                bg="#0a0012", fg="#9d4edd",
                font=("Courier", 6),
            )
            lbl.pack(anchor="center")
            self._sanctum_pixel_labels.append(lbl)

        # Status message
        self._sanctum_status_label = tk.Label(
            inner,
            text="Frank ist in der Sanctuary...",
            bg="#0a0012", fg="#bb8fce",
            font=("Consolas", 10),
        )
        self._sanctum_status_label.pack(pady=(4, 2))

        # Elapsed time
        self._sanctum_elapsed_label = tk.Label(
            inner,
            text="",
            bg="#0a0012", fg="#7b6b8a",
            font=("Consolas", 8),
        )
        self._sanctum_elapsed_label.pack(pady=(0, 2))

        # Subtext
        tk.Label(
            inner,
            text="Chat ist pausiert \u2014 Frank erkundet seine innere Welt",
            bg="#0a0012", fg="#5a4a6a",
            font=("Consolas", 8),
        ).pack(pady=(2, 0))

        # Bottom decorative bar
        bar = tk.Frame(inner, bg="#0a0012", height=8)
        bar.pack(fill="x", pady=(8, 0))

        self._sanctum_bar_segments = []
        for i in range(12):
            seg = tk.Frame(bar, bg="#5a189a", width=20, height=4)
            seg.pack(side="left", expand=True, fill="x", padx=1)
            self._sanctum_bar_segments.append(seg)

        # Scroll to show banner
        self.messages_frame.update_idletasks()
        self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))
        self._smart_scroll()

        # Start animation
        self._sanctum_animate()

    def _sanctum_animate(self):
        """Animate banner colors and elapsed time."""
        if not self._sanctum_active or not self._sanctum_banner:
            return

        try:
            # Cycle border color
            self._sanctum_color_idx = (
                (self._sanctum_color_idx + 1) % len(_CYCLE_COLORS)
            )
            border_color = _CYCLE_COLORS[self._sanctum_color_idx]
            self._sanctum_border.configure(bg=border_color)

            # Cycle pixel art color
            self._sanctum_pixel_idx = (
                (self._sanctum_pixel_idx + 1) % len(_PIXEL_COLORS)
            )
            pixel_color = _PIXEL_COLORS[self._sanctum_pixel_idx]
            for lbl in self._sanctum_pixel_labels:
                lbl.configure(fg=pixel_color)

            # Cycle header glow
            header_colors = ["#d4a0ff", "#e0b0ff", "#c77dff", "#bb8fce"]
            h_idx = self._sanctum_color_idx % len(header_colors)
            self._sanctum_header_label.configure(fg=header_colors[h_idx])

            # Animate bar segments (wave)
            for i, seg in enumerate(self._sanctum_bar_segments):
                ci = (self._sanctum_color_idx + i * 2) % len(_CYCLE_COLORS)
                seg.configure(bg=_CYCLE_COLORS[ci])

            # Update elapsed time
            elapsed = time.time() - self._sanctum_start_ts
            mins = int(elapsed) // 60
            secs = int(elapsed) % 60
            self._sanctum_elapsed_label.configure(
                text=f"\u23f1 {mins:02d}:{secs:02d}"
            )

            # Status text variety
            dots = "." * (1 + (int(elapsed) % 3))
            phases = [
                "Frank meditiert",
                "Frank erkundet die Bibliothek",
                "Frank reflektiert",
                "Frank ist in Gedanken versunken",
            ]
            phase = phases[int(elapsed // 30) % len(phases)]
            self._sanctum_status_label.configure(text=f"{phase}{dots}")

        except tk.TclError:
            return  # Widget destroyed
        except Exception as e:
            LOG.debug("Sanctum animation error: %s", e)

        self.after(600, self._sanctum_animate)

    # ─── Banner: Remove ────────────────────────────────────────────────

    def _sanctum_remove_banner(self):
        """Remove the Sanctum banner from chat."""
        if self._sanctum_banner:
            try:
                self._sanctum_banner.destroy()
            except tk.TclError:
                pass
            self._sanctum_banner = None
            self._sanctum_border = None
            self._sanctum_header_label = None
            self._sanctum_status_label = None
            self._sanctum_elapsed_label = None
            self._sanctum_pixel_labels = []
            self._sanctum_bar_segments = []

    # ─── Input Blocking ────────────────────────────────────────────────

    def _sanctum_block_input(self, block: bool):
        """Enable/disable the input field during Sanctum."""
        try:
            if block:
                self.entry.text.configure(state="disabled")
                self._sanctum_input_blocked = True
            else:
                self.entry.text.configure(state="normal")
                self._sanctum_input_blocked = False
        except Exception as e:
            LOG.debug("Sanctum input block error: %s", e)

    # ─── On Exit ───────────────────────────────────────────────────────

    def _sanctum_on_exit(self):
        """Handle Sanctum exit — show transition + summary."""
        # Transition banner to exit state briefly
        try:
            if self._sanctum_banner:
                # Flash green to signal exit
                self._sanctum_border.configure(bg=COLORS["accent"])
                self._sanctum_header_label.configure(
                    text="\u2705  SANCTUM BEENDET  \u2705",
                    fg=COLORS["accent"],
                )
                self._sanctum_status_label.configure(
                    text="Frank ist zurueck!",
                    fg=COLORS["accent"],
                )
                for seg in self._sanctum_bar_segments:
                    seg.configure(bg=COLORS["accent"])
                for lbl in self._sanctum_pixel_labels:
                    lbl.configure(fg=COLORS["accent"])

                # Remove banner after 3 seconds (store ID for cancellation)
                self._sanctum_cleanup_after_id = self.after(
                    3000, self._sanctum_cleanup_exit)
            else:
                self._sanctum_cleanup_exit()
        except Exception:
            self._sanctum_cleanup_exit()

    def _sanctum_cleanup_exit(self):
        """Final cleanup after Sanctum exit — remove banner, restore input, show summary."""
        self._sanctum_cleanup_after_id = None
        self._sanctum_remove_banner()
        self._sanctum_block_input(False)

        # Show session summary (delay to allow summary file to be written)
        self.after(2000, self._sanctum_show_summary)

    def _sanctum_show_summary(self):
        """Display rich Sanctum session summary in the chat.

        Includes session stats, E-PQ changes, mood shift, and the personal
        debrief from Frank's perspective.
        """
        try:
            data = json.loads(_SANCTUM_SUMMARY.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            LOG.debug("No sanctum summary file found or invalid JSON")
            return
        except Exception as e:
            LOG.debug("Sanctum summary read error: %s", e)
            return

        try:
            # Don't show the same summary twice
            sid = data.get("session_id", "")
            if sid == self._sanctum_last_summary_id:
                return
            self._sanctum_last_summary_id = sid

            duration = data.get("duration_s", 0)
            turns = data.get("turns", 0)
            locations = data.get("locations", [])
            debrief = data.get("debrief", "")
            mood_start = data.get("mood_start", 0.5)
            mood_end = data.get("mood_end", 0.5)
            epq_delta = data.get("epq_delta", {})

            mins = int(duration) // 60
            secs = int(duration) % 60

            # ── Build formatted summary ──
            lines = []
            lines.append("\u2728 Sanctum Session \u2728")
            lines.append(f"\u23f1 {mins}m {secs:02d}s  \u00b7  {turns} Gedanken")

            if locations:
                loc_icons = {
                    "library": "\U0001F4DA",
                    "computer_terminal": "\U0001F5A5",
                    "genesis_terrarium": "\U0001F331",
                    "observatory": "\U0001F52D",
                    "lab_quantum": "\u269B",
                    "lab_aura": "\U0001F52E",
                    "lab_genesis": "\U0001F331",
                    "lab_experiment": "\U0001F9EA",
                    "entity_lounge": "\U0001F465",
                    "reflection_pool": "\U0001F30A",
                    "workshop": "\U0001F527",
                }
                loc_parts = []
                for loc in locations[:5]:
                    icon = loc_icons.get(loc, "\u25AB")
                    name = loc.replace("_", " ").title()
                    loc_parts.append(f"{icon} {name}")
                lines.append(" \u2192 ".join(loc_parts))

            lines.append("")

            # E-PQ changes
            mood_delta = mood_end - mood_start
            mood_bar = self._sanctum_mood_bar(mood_start, mood_end)
            lines.append(f"\u2764 Mood: {mood_bar}")

            if epq_delta:
                trait_info = {
                    "precision": ("\U0001F3AF", "Praezision"),
                    "risk": ("\U0001F525", "Risiko"),
                    "empathy": ("\U0001F49C", "Empathie"),
                    "autonomy": ("\U0001F5FD", "Autonomie"),
                    "vigilance": ("\U0001F441", "Vigilanz"),
                }
                changes = []
                for trait, (icon, label) in trait_info.items():
                    d = epq_delta.get(trait, 0)
                    if abs(d) >= 0.001:
                        sign = "+" if d > 0 else ""
                        changes.append(f"  {icon} {label}: {sign}{d:.3f}")
                if changes:
                    lines.append("\U0001F9EC Persoenlichkeitsshift:")
                    lines.extend(changes)

            # Personal debrief (first person, from Frank)
            if debrief:
                lines.append("")
                if len(debrief) > 400:
                    debrief = debrief[:397] + "..."
                lines.append(f"\u00ab {debrief} \u00bb")

            summary_text = "\n".join(lines)
            self._add_message("Frank", summary_text, is_system=False,
                              persist=True)

            LOG.info("SANCTUM OVERLAY: Displayed session summary")

        except Exception as e:
            LOG.debug("Sanctum summary display error: %s", e)

    @staticmethod
    def _sanctum_mood_bar(start: float, end: float) -> str:
        """Generate a simple text mood bar showing before/after."""
        def bar(val):
            filled = max(0, min(10, int(val * 10)))
            return "\u2588" * filled + "\u2591" * (10 - filled)

        delta = end - start
        sign = "+" if delta >= 0 else ""
        arrow = "\u2197" if delta > 0.01 else ("\u2198" if delta < -0.01 else "\u2192")
        return f"{bar(start)} {arrow} {bar(end)}  ({sign}{delta:.3f})"
