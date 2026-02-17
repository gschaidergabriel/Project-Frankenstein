import subprocess
import threading
import time
from overlay.constants import LOG
from overlay.bsn.constants import get_primary_monitor


class WindowPositioner:
    """Applies calculated layout with aggressive multi-stage positioning."""

    def __init__(self, overlay):
        self.overlay = overlay

    def _clamp_to_primary(self, x: int, y: int, w: int, h: int) -> tuple:
        """Clamp geometry to primary monitor bounds. Never overflow to secondary."""
        mon = get_primary_monitor()
        mon_right = mon["x"] + mon["width"]
        mon_bottom = mon["y"] + mon["height"]

        # Clamp width so window doesn't extend beyond primary monitor
        if x + w > mon_right:
            w = mon_right - x
        # If still too wide (x is near the edge), also shift x left
        if w < 200 and x > mon["x"]:
            x = max(mon["x"], mon_right - max(w, 200))
            w = mon_right - x
        # Clamp height
        if y + h > mon_bottom:
            h = mon_bottom - y

        return x, y, max(w, 100), max(h, 100)

    def apply_layout(self, layout: dict, win_id: str):
        """Applies the layout."""
        # 1. Adjust Frank if necessary
        if layout["frank_action"] != "none":
            self._adjust_frank(layout["frank"], layout["frank_action"])
            time.sleep(0.15)

        # 2. Clamp app geometry to primary monitor bounds
        app = layout["app"]
        app["x"], app["y"], app["width"], app["height"] = self._clamp_to_primary(
            app["x"], app["y"], app["width"], app["height"]
        )

        # 3. Position app (aggressive)
        self._position_app_aggressive(win_id, app)

    def maximize_on_primary(self, win_id: str):
        """Maximize a window on the primary monitor (for fullscreen apps like Steam)."""
        mon = get_primary_monitor()
        x, y = mon["x"], mon["y"]
        w, h = mon["width"], mon["height"]

        def _do():
            LOG.info(f"BSN: Maximizing {win_id} on primary monitor: {w}x{h}+{x}+{y}")
            # First unmaximize to ensure clean state
            self._wmctrl_position(win_id, x, y, w, h)
            time.sleep(0.2)
            # Then maximize on primary monitor
            try:
                subprocess.run([
                    "wmctrl", "-i", "-r", win_id,
                    "-b", "add,maximized_vert,maximized_horz"
                ], capture_output=True, timeout=2)
            except Exception as e:
                LOG.debug(f"BSN: wmctrl maximize error: {e}")
            time.sleep(0.3)
            # Verify it's on the primary monitor, force if needed
            self._enforce_primary_bounds(win_id, x, y, w, h)

        threading.Thread(target=_do, daemon=True).start()

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
        """Positions app with multi-stage escalation.

        Stage 1: Immediate wmctrl + xdotool (aggressive from the start)
        Stage 2: Verify + retry if needed (100ms)
        Stage 3: Force retry with both tools (300ms)
        Stage 4: Final enforcement + bounds check (600ms)
        """
        x, y = geometry["x"], geometry["y"]
        w, h = geometry["width"], geometry["height"]

        def _do_position():
            LOG.debug(f"BSN: Positioning {win_id} to {w}x{h} at ({x},{y})")

            # Stage 1: Aggressive immediate positioning (both tools at once)
            self._force_position(win_id, x, y, w, h)

            # Stage 2: Quick verify + retry
            time.sleep(0.1)
            if not self._verify_position(win_id, x):
                LOG.debug(f"BSN: Stage 2 retry for {win_id}")
                self._wmctrl_position(win_id, x, y, w, h)

            # Stage 3: Force retry if still wrong
            time.sleep(0.2)
            if not self._verify_position(win_id, x):
                LOG.debug(f"BSN: Stage 3 FORCE for {win_id}")
                self._force_position(win_id, x, y, w, h)

            # Stage 4: Final verification + primary monitor bounds
            time.sleep(0.3)
            if self._verify_position(win_id, x):
                LOG.info(f"BSN: Window {win_id} positioned successfully")
            else:
                LOG.warning(f"BSN: Window {win_id} positioning may have failed")
            self._enforce_primary_bounds(win_id, x, y, w, h)

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

    def _enforce_primary_bounds(self, win_id: str, target_x: int, target_y: int,
                                target_w: int, target_h: int):
        """Check actual window geometry and force it within primary monitor if it overflows."""
        try:
            result = subprocess.run(
                ["xdotool", "getwindowgeometry", "--shell", win_id],
                capture_output=True, text=True, timeout=2
            )
            geo = {}
            for line in result.stdout.strip().split('\n'):
                if '=' in line:
                    k, v = line.split('=', 1)
                    geo[k] = int(v)

            actual_x = geo.get("X", target_x)
            actual_y = geo.get("Y", target_y)
            actual_w = geo.get("WIDTH", target_w)
            actual_h = geo.get("HEIGHT", target_h)

            mon = get_primary_monitor()
            mon_right = mon["x"] + mon["width"]
            mon_bottom = mon["y"] + mon["height"]

            needs_fix = False
            fix_x, fix_y, fix_w, fix_h = actual_x, actual_y, actual_w, actual_h

            # Window extends beyond primary monitor right edge
            if actual_x + actual_w > mon_right:
                fix_w = mon_right - actual_x
                if fix_w < 200:
                    fix_x = max(mon["x"], mon_right - max(actual_w, 400))
                    fix_w = mon_right - fix_x
                needs_fix = True

            # Window extends below primary monitor
            if actual_y + actual_h > mon_bottom:
                fix_h = mon_bottom - actual_y
                needs_fix = True

            # Window is on secondary monitor entirely
            if actual_x >= mon_right:
                fix_x = target_x
                fix_w = target_w
                needs_fix = True

            if needs_fix:
                LOG.warning(
                    f"BSN: Window {win_id} overflows primary monitor "
                    f"(actual: {actual_w}x{actual_h}+{actual_x}+{actual_y}), "
                    f"clamping to {fix_w}x{fix_h}+{fix_x}+{fix_y}"
                )
                self._wmctrl_position(win_id, fix_x, fix_y, fix_w, fix_h)
                time.sleep(0.1)
                self._force_position(win_id, fix_x, fix_y, fix_w, fix_h)
        except Exception as e:
            LOG.debug(f"BSN: Primary bounds enforcement error: {e}")

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
