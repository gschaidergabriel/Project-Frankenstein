import subprocess
from overlay.bsn.constants import BSNConstants, get_primary_monitor
from overlay.constants import LOG


class SpaceNegotiator:
    """
    Calculates optimal layout for Frank + App.
    App ALWAYS fills the entire available space.
    All calculations restricted to the primary monitor.
    """

    def __init__(self, overlay):
        self.overlay = overlay
        self.monitor = None    # Primary monitor info
        self.screen_w = None   # Primary monitor width
        self.screen_h = None   # Primary monitor height
        self.screen_x = None   # Primary monitor X offset
        self.screen_y = None   # Primary monitor Y offset
        self.usable_h = None

    def invalidate_screen_info(self):
        """Clear cached screen dimensions (call after monitor/resolution change)."""
        self.screen_w = None

    def _ensure_screen_info(self):
        """Detects primary monitor and caches the values."""
        if self.screen_w is None:
            self.monitor = get_primary_monitor()
            self.screen_w = self.monitor["width"]
            self.screen_h = self.monitor["height"]
            self.screen_x = self.monitor["x"]
            self.screen_y = self.monitor["y"]
            self.usable_h = self.screen_h - BSNConstants.PANEL_HEIGHT
            LOG.debug(f"BSN: Using primary monitor bounds: {self.screen_w}x{self.screen_h}+{self.screen_x}+{self.screen_y}")

    def get_frank_geometry(self) -> dict:
        """Current Frank geometry from wmctrl (WM coordinates, not Tk)."""
        try:
            result = subprocess.run(
                ["wmctrl", "-lG"], capture_output=True, text=True, timeout=2
            )
            for line in result.stdout.strip().split('\n'):
                if "F.R.A.N.K" in line:
                    p = line.split(None, 8)
                    if len(p) >= 6:
                        return {
                            "x": int(p[2]),
                            "y": int(p[3]),
                            "width": int(p[4]),
                            "height": int(p[5]),
                        }
        except Exception as e:
            LOG.debug(f"BSN: wmctrl frank lookup failed: {e}")
        # Fallback to Tk coordinates
        return {
            "x": self.overlay.winfo_x(),
            "y": self.overlay.winfo_y(),
            "width": self.overlay.winfo_width(),
            "height": self.overlay.winfo_height()
        }

    def negotiate(self) -> dict:
        """
        Calculates optimal layout for DOCK mode.
        Frank is fixed (DOCK panel with strut) — only app placement is calculated.

        Returns:
            {"success", "frank_action", "frank": {geometry}, "app": {geometry}}
        """
        self._ensure_screen_info()
        frank = self.get_frank_geometry()

        # DOCK mode: Frank never moves/shrinks, app fills space right of Frank
        result = self._try_keep_frank(frank)
        if result["success"]:
            return result

        # Screen too small for app beside fixed Frank
        return self._emergency_layout()

    def _try_keep_frank(self, frank: dict) -> dict:
        """Strategy 1: Frank stays, app fits beside it."""
        frank_right = frank["x"] + frank["width"]
        mon_right = self.screen_x + self.screen_w
        available_w = mon_right - frank_right - BSNConstants.GAP

        if available_w >= BSNConstants.APP_MIN_WIDTH:
            return {
                "success": True,
                "frank_action": "none",
                "frank": frank,
                "app": {
                    "x": frank_right + BSNConstants.GAP,
                    "y": BSNConstants.PANEL_HEIGHT,
                    "width": available_w,
                    "height": self.usable_h
                }
            }

        # Check left of Frank (right of dock)
        dock_x = self.screen_x + BSNConstants.DOCK_WIDTH
        available_left = frank["x"] - dock_x - BSNConstants.GAP
        if available_left >= BSNConstants.APP_MIN_WIDTH:
            return {
                "success": True,
                "frank_action": "none",
                "frank": frank,
                "app": {
                    "x": dock_x,
                    "y": BSNConstants.PANEL_HEIGHT,
                    "width": available_left,
                    "height": self.usable_h
                }
            }

        return {"success": False}

    def _emergency_layout(self) -> dict:
        """Strategy 5: Emergency for very small screens."""
        LOG.warning(f"BSN EMERGENCY: Screen too small ({self.screen_w}x{self.screen_h})")

        dock_x = self.screen_x + BSNConstants.DOCK_WIDTH
        frank = {
            "x": dock_x,
            "y": BSNConstants.PANEL_HEIGHT,
            "width": BSNConstants.FRANK_MIN_WIDTH,
            "height": min(BSNConstants.FRANK_MIN_HEIGHT, self.usable_h)
        }

        frank_right = dock_x + BSNConstants.FRANK_MIN_WIDTH
        mon_right = self.screen_x + self.screen_w
        app_w = max(100, mon_right - frank_right - BSNConstants.GAP)

        return {
            "success": True,
            "frank_action": "emergency",
            "frank": frank,
            "app": {
                "x": frank_right + BSNConstants.GAP,
                "y": BSNConstants.PANEL_HEIGHT,
                "width": app_w,
                "height": self.usable_h
            }
        }
