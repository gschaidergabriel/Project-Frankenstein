import json
import os
import subprocess
import threading
import time
from pathlib import Path
from overlay.constants import LOG
from overlay.bsn.constants import BSNConstants
from overlay.bsn.negotiator import SpaceNegotiator
from overlay.bsn.positioner import WindowPositioner
from overlay.bsn.watcher import WindowWatcher


class LayoutController:
    """Central control of the BSN system."""

    def __init__(self, overlay):
        self.overlay = overlay
        self.negotiator = SpaceNegotiator(overlay)
        self.positioner = WindowPositioner(overlay)
        self.watcher = WindowWatcher(self)
        self._started = False

    def start(self):
        """Starts the layout system."""
        if self._started:
            return
        self._started = True
        self.watcher.start()
        # Check existing windows and adjust Frank if needed.
        # Delay 3s to run AFTER ADI profile restoration (which runs at t=3000ms from app start).
        # ADI applies saved profiles at t=3s, so we must check overlaps AFTER that.
        threading.Thread(target=self._startup_avoid_overlap, daemon=True).start()
        LOG.info("BSN: LayoutController started")

    def stop(self):
        """Stops the layout system."""
        self.watcher.stop()
        self._started = False

    def is_gaming_mode(self) -> bool:
        """Checks if gaming mode is active."""
        try:
            state_file = Path("/tmp/gaming_mode_state.json")
            if state_file.exists():
                data = json.loads(state_file.read_text())
                return data.get("active", False)
        except Exception:
            pass
        return False

    def _apply_geometry(self, geo_str: str):
        """Apply geometry on main thread (tkinter thread-safety)."""
        try:
            self.overlay.geometry(geo_str)
            self.overlay.update_idletasks()
            LOG.info(f"BSN: Geometry applied on main thread: {geo_str}")
            # After resize, scroll chat to bottom (bubble heights may need recalc)
            if hasattr(self.overlay, 'chat_canvas'):
                self.overlay.after(100, lambda: (
                    self.overlay.chat_canvas.configure(
                        scrollregion=self.overlay.chat_canvas.bbox("all")),
                    self.overlay.chat_canvas.yview_moveto(1.0),
                ))
        except Exception as e:
            LOG.error(f"BSN: Failed to apply geometry: {e}")

    def handle_new_window(self, win_id: str):
        """Called when a new window is detected.

        Simply maximizes the window. The WM strut ensures it fills
        the space right of Frank. Maximized windows are natively sticky —
        they follow strut changes automatically when Frank resizes.
        """
        try:
            LOG.info(f"BSN: Maximizing {win_id} (strut-aware)")
            import subprocess
            # Maximize — the WM respects the strut and places it right of Frank
            subprocess.run([
                "wmctrl", "-i", "-r", win_id,
                "-b", "add,maximized_vert,maximized_horz"
            ], capture_output=True, timeout=2)
        except Exception as e:
            LOG.error(f"BSN: Error handling new window: {e}")

    def restore_frank(self):
        """No-op in DOCK mode — strut handles space reservation."""
        LOG.debug("BSN: restore_frank() — no-op in DOCK mode")

    def handle_fullscreen_app(self, win_id: str):
        """Handle apps that need the full primary monitor.

        In DOCK mode, Frank's strut prevents overlap. Apps that truly
        need fullscreen (games) are excluded by the watcher.
        """
        LOG.debug(f"BSN: handle_fullscreen_app({win_id}) — DOCK mode, strut active")

    # ---------- Startup overlap avoidance ----------

    def _startup_avoid_overlap(self):
        """At startup, gently snap existing windows out of Frank's strut area.

        Uses a simple xdotool windowmove — no unmaximize, no multi-stage
        positioning, no resize.  Just nudge the x coordinate.
        """
        import time
        time.sleep(3.5)  # Wait for ADI profile + strut to be fully set

        try:
            # Get Frank's real right edge from wmctrl
            frank_right = 0
            env = {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
            result = subprocess.run(
                ["wmctrl", "-lG"], capture_output=True, text=True, timeout=3, env=env,
            )
            for line in result.stdout.strip().split("\n"):
                if "F.R.A.N.K" in line:
                    p = line.split(None, 8)
                    if len(p) >= 6:
                        frank_right = int(p[2]) + int(p[4])
                        break

            if not frank_right:
                LOG.info("BSN: Startup overlap check — Frank not found in wmctrl")
                return

            snapped = 0
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split(None, 8)
                if len(parts) < 8:
                    continue
                win_id = parts[0]
                desktop = parts[1]
                title = (parts[7] if len(parts) > 7 else "").lower()

                if desktop == "-1":
                    continue
                if "f.r.a.n.k" in title or "neural core" in title or "cybercore" in title:
                    continue

                try:
                    win_x = int(parts[2])
                    win_y = int(parts[3])
                    win_w = int(parts[4])
                    # Skip windows on secondary monitors
                    from overlay.bsn.constants import get_primary_monitor
                    _pm = get_primary_monitor()
                    _primary_right = _pm["x"] + _pm["width"]
                    if win_x >= _primary_right:
                        continue
                    if win_x < frank_right and win_w > 50:
                        new_x = frank_right + 2
                        LOG.info(f"BSN: Startup snap '{title[:30]}' x={win_x} → x={new_x}")
                        subprocess.run(
                            ["xdotool", "windowmove", str(int(win_id, 16)),
                             str(new_x), str(win_y)],
                            capture_output=True, timeout=2, env=env,
                        )
                        snapped += 1
                except (ValueError, Exception):
                    pass

            LOG.info(f"BSN: Startup overlap check complete ({snapped} snapped)")
        except Exception as e:
            LOG.warning(f"BSN: Startup overlap avoidance error: {e}")
