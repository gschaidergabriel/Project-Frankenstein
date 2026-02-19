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
        """Called when a new window is detected."""
        try:
            layout = self.negotiator.negotiate()

            if layout["success"]:
                LOG.info(f"BSN: Layout negotiated - frank_action={layout['frank_action']}")
                self.positioner.apply_layout(layout, win_id)
            else:
                LOG.error("BSN: Layout negotiation failed!")
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
        """At startup, reposition existing windows that overlap Frank's strut area.

        In DOCK mode, Frank is fixed and has a strut reservation. Windows that
        were opened before Frank started may still be in the strut zone.
        """
        import time
        time.sleep(3.5)  # Wait for ADI profile + strut to be fully set

        try:
            env = {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
            frank_right = self.overlay.winfo_x() + self.overlay.winfo_width()

            result = subprocess.run(
                ["wmctrl", "-l"], capture_output=True, text=True, timeout=3, env=env,
            )
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split(None, 4)
                if len(parts) < 5:
                    continue
                win_id = parts[0]
                desktop = parts[1]
                title = (parts[4] if len(parts) > 4 else "").lower()

                if desktop == "-1":
                    continue
                if "f.r.a.n.k" in title or "neural core" in title or "cybercore" in title:
                    continue

                # Check if window overlaps Frank's strut zone
                try:
                    geo_result = subprocess.run(
                        ["xdotool", "getwindowgeometry", "--shell", win_id],
                        capture_output=True, text=True, timeout=2, env=env,
                    )
                    geo = {}
                    for gline in geo_result.stdout.strip().split("\n"):
                        if "=" in gline:
                            k, v = gline.split("=", 1)
                            geo[k] = int(v)
                    win_x = geo.get("X", 9999)
                    if win_x < frank_right:
                        # Window overlaps Frank — trigger BSN layout
                        LOG.info(f"BSN: Startup — window '{parts[4][:40]}' overlaps strut, repositioning")
                        self.handle_new_window(win_id)
                except Exception:
                    pass

            LOG.info("BSN: Startup overlap check complete")
        except Exception as e:
            LOG.warning(f"BSN: Startup overlap avoidance error: {e}")
