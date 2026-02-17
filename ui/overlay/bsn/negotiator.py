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
        """Current Frank geometry."""
        return {
            "x": self.overlay.winfo_x(),
            "y": self.overlay.winfo_y(),
            "width": self.overlay.winfo_width(),
            "height": self.overlay.winfo_height()
        }

    def negotiate(self) -> dict:
        """
        Calculates optimal layout.

        Returns:
            {"success", "frank_action", "frank": {geometry}, "app": {geometry}}
        """
        self._ensure_screen_info()
        frank = self.get_frank_geometry()

        # Strategy 1: Frank stays, app fills the rest
        result = self._try_keep_frank(frank)
        if result["success"]:
            return result

        # Strategy 2: Frank shrinks horizontally
        result = self._try_shrink_frank(frank)
        if result["success"]:
            return result

        # Strategy 3: Frank moves to the left edge
        result = self._try_move_frank(frank)
        if result["success"]:
            return result

        # Strategy 4: Frank shrinks AND moves
        result = self._try_shrink_and_move()
        if result["success"]:
            return result

        # Strategy 5: Emergency layout
        return self._emergency_layout()

    def _try_keep_frank(self, frank: dict) -> dict:
        """Strategy 1: Frank stays, app fits beside it."""
        frank_right = frank["x"] + frank["width"]
        available_w = self.screen_w - frank_right - BSNConstants.GAP

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

        # Check left of Frank
        available_left = frank["x"] - BSNConstants.GAP
        if available_left >= BSNConstants.APP_MIN_WIDTH:
            return {
                "success": True,
                "frank_action": "none",
                "frank": frank,
                "app": {
                    "x": 0,
                    "y": BSNConstants.PANEL_HEIGHT,
                    "width": available_left,
                    "height": self.usable_h
                }
            }

        return {"success": False}

    def _try_shrink_frank(self, frank: dict) -> dict:
        """Strategy 2: Frank shrinks horizontally."""
        max_frank_w = self.screen_w - BSNConstants.GAP - BSNConstants.APP_MIN_WIDTH

        if max_frank_w < BSNConstants.FRANK_MIN_WIDTH:
            return {"success": False}

        new_frank_w = max(BSNConstants.FRANK_MIN_WIDTH, min(frank["width"], max_frank_w))

        new_frank = {
            "x": frank["x"],
            "y": frank["y"],
            "width": new_frank_w,
            "height": frank["height"]
        }

        frank_right = new_frank["x"] + new_frank["width"]
        app_w = self.screen_w - frank_right - BSNConstants.GAP

        if app_w >= BSNConstants.APP_MIN_WIDTH:
            return {
                "success": True,
                "frank_action": "shrink",
                "frank": new_frank,
                "app": {
                    "x": frank_right + BSNConstants.GAP,
                    "y": BSNConstants.PANEL_HEIGHT,
                    "width": app_w,
                    "height": self.usable_h
                }
            }

        return {"success": False}

    def _try_move_frank(self, frank: dict) -> dict:
        """Strategy 3: Frank moves to the left edge."""
        new_frank = {
            "x": 0,
            "y": BSNConstants.PANEL_HEIGHT,
            "width": frank["width"],
            "height": min(frank["height"], self.usable_h)
        }

        app_w = self.screen_w - frank["width"] - BSNConstants.GAP

        if app_w >= BSNConstants.APP_MIN_WIDTH:
            return {
                "success": True,
                "frank_action": "move",
                "frank": new_frank,
                "app": {
                    "x": frank["width"] + BSNConstants.GAP,
                    "y": BSNConstants.PANEL_HEIGHT,
                    "width": app_w,
                    "height": self.usable_h
                }
            }

        return {"success": False}

    def _try_shrink_and_move(self) -> dict:
        """Strategy 4: Frank at minimum size and at left edge."""
        new_frank = {
            "x": 0,
            "y": BSNConstants.PANEL_HEIGHT,
            "width": BSNConstants.FRANK_MIN_WIDTH,
            "height": min(BSNConstants.FRANK_MIN_HEIGHT, self.usable_h)
        }

        app_w = self.screen_w - BSNConstants.FRANK_MIN_WIDTH - BSNConstants.GAP

        if app_w >= BSNConstants.APP_MIN_WIDTH:
            return {
                "success": True,
                "frank_action": "shrink_and_move",
                "frank": new_frank,
                "app": {
                    "x": BSNConstants.FRANK_MIN_WIDTH + BSNConstants.GAP,
                    "y": BSNConstants.PANEL_HEIGHT,
                    "width": app_w,
                    "height": self.usable_h
                }
            }

        return {"success": False}

    def _emergency_layout(self) -> dict:
        """Strategy 5: Emergency for very small screens."""
        LOG.warning(f"BSN EMERGENCY: Screen too small ({self.screen_w}x{self.screen_h})")

        frank = {
            "x": 0,
            "y": BSNConstants.PANEL_HEIGHT,
            "width": BSNConstants.FRANK_MIN_WIDTH,
            "height": min(BSNConstants.FRANK_MIN_HEIGHT, self.usable_h)
        }

        app_w = max(100, self.screen_w - BSNConstants.FRANK_MIN_WIDTH - BSNConstants.GAP)

        return {
            "success": True,
            "frank_action": "emergency",
            "frank": frank,
            "app": {
                "x": BSNConstants.FRANK_MIN_WIDTH + BSNConstants.GAP,
                "y": BSNConstants.PANEL_HEIGHT,
                "width": app_w,
                "height": self.usable_h
            }
        }
