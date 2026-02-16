import subprocess
import threading
import time
from overlay.constants import LOG


class WindowPositioner:
    """Applies calculated layout with aggressive multi-stage positioning."""

    def __init__(self, overlay):
        self.overlay = overlay

    def apply_layout(self, layout: dict, win_id: str):
        """Applies the layout."""
        # 1. Adjust Frank if necessary
        if layout["frank_action"] != "none":
            self._adjust_frank(layout["frank"], layout["frank_action"])
            time.sleep(0.15)

        # 2. Position app (aggressive)
        self._position_app_aggressive(win_id, layout["app"])

    def _adjust_frank(self, geometry: dict, action: str):
        """Adjusts Frank (thread-safe via after())."""
        LOG.info(f"BSN: Adjusting Frank ({action}) -> {geometry['width']}x{geometry['height']} at ({geometry['x']},{geometry['y']})")

        x, y = geometry["x"], geometry["y"]
        w, h = geometry["width"], geometry["height"]
        geo_str = f"{w}x{h}+{x}+{y}"

        # CRITICAL: tkinter is NOT thread-safe! BSN runs in background threads.
        # Must schedule geometry changes on the main tkinter thread via after().
        # Also skip if user is currently dragging the window.
        def _apply():
            if getattr(self.overlay, '_dragging', False):
                LOG.info("BSN: Skipping Frank adjustment — user is dragging")
                return
            try:
                self.overlay.geometry(geo_str)
                self.overlay.update_idletasks()
            except Exception as e:
                LOG.error(f"BSN: Failed to adjust Frank: {e}")

        try:
            self.overlay.after(0, _apply)
        except Exception:
            pass  # Overlay may be destroyed

    def _position_app_aggressive(self, win_id: str, geometry: dict):
        """Positions app with 5-stage escalation."""
        x, y = geometry["x"], geometry["y"]
        w, h = geometry["width"], geometry["height"]

        def _do_position():
            LOG.debug(f"BSN: Positioning {win_id} to {w}x{h} at ({x},{y})")

            # Stage 1: Immediately
            self._wmctrl_position(win_id, x, y, w, h)

            # Stage 2: After 150ms
            time.sleep(0.15)
            if not self._verify_position(win_id, x):
                LOG.debug(f"BSN: Stage 2 retry for {win_id}")
                self._wmctrl_position(win_id, x, y, w, h)

            # Stage 3: After 350ms
            time.sleep(0.2)
            if not self._verify_position(win_id, x):
                LOG.debug(f"BSN: Stage 3 retry for {win_id}")
                self._wmctrl_position(win_id, x, y, w, h)

            # Stage 4: After 650ms - FORCE
            time.sleep(0.3)
            if not self._verify_position(win_id, x):
                LOG.debug(f"BSN: Stage 4 FORCE for {win_id}")
                self._force_position(win_id, x, y, w, h)

            # Stage 5: Final verification
            time.sleep(0.4)
            if self._verify_position(win_id, x):
                LOG.info(f"BSN: Window {win_id} positioned successfully")
            else:
                LOG.warning(f"BSN: Window {win_id} positioning may have failed")

        threading.Thread(target=_do_position, daemon=True).start()

    def _wmctrl_position(self, win_id: str, x: int, y: int, w: int, h: int):
        """Standard wmctrl positioning."""
        try:
            # Unmaximize
            subprocess.run([
                "wmctrl", "-i", "-r", win_id,
                "-b", "remove,maximized_vert,maximized_horz"
            ], capture_output=True, timeout=2)

            # Set position
            subprocess.run([
                "wmctrl", "-i", "-r", win_id,
                "-e", f"0,{x},{y},{w},{h}"
            ], capture_output=True, timeout=2)
        except Exception as e:
            LOG.error(f"BSN: wmctrl error: {e}")

    def _force_position(self, win_id: str, x: int, y: int, w: int, h: int):
        """Aggressive positioning with wmctrl + xdotool."""
        self._wmctrl_position(win_id, x, y, w, h)
        time.sleep(0.05)

        try:
            win_id_dec = str(int(win_id, 16))
            subprocess.run(["xdotool", "windowmove", win_id_dec, str(x), str(y)],
                          capture_output=True, timeout=2)
            subprocess.run(["xdotool", "windowsize", win_id_dec, str(w), str(h)],
                          capture_output=True, timeout=2)
        except Exception as e:
            LOG.debug(f"BSN: xdotool fallback error: {e}")

    def _verify_position(self, win_id: str, expected_x: int) -> bool:
        """Checks if window is correctly positioned."""
        try:
            result = subprocess.run(
                ["xdotool", "getwindowgeometry", "--shell", win_id],
                capture_output=True, text=True, timeout=2
            )
            for line in result.stdout.strip().split('\n'):
                if line.startswith("X="):
                    actual_x = int(line.split('=')[1])
                    return abs(actual_x - expected_x) < 100
        except Exception:
            pass
        return False
