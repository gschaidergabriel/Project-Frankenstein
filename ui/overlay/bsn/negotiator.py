from overlay.bsn.constants import BSNConstants, _get_primary_monitor
from overlay.constants import LOG


class SpaceNegotiator:
    """
    Berechnet optimales Layout für Frank + App.
    App füllt IMMER den gesamten verfügbaren Platz.
    Alle Berechnungen beschränkt auf den primären Monitor.
    """

    def __init__(self, overlay):
        self.overlay = overlay
        self.monitor = None    # Primary monitor info
        self.screen_w = None   # Primary monitor width
        self.screen_h = None   # Primary monitor height
        self.screen_x = None   # Primary monitor X offset
        self.screen_y = None   # Primary monitor Y offset
        self.usable_h = None

    def _ensure_screen_info(self):
        """Erkennt primären Monitor und cached die Werte."""
        if self.screen_w is None:
            self.monitor = _get_primary_monitor()
            self.screen_w = self.monitor["width"]
            self.screen_h = self.monitor["height"]
            self.screen_x = self.monitor["x"]
            self.screen_y = self.monitor["y"]
            self.usable_h = self.screen_h - BSNConstants.PANEL_HEIGHT
            LOG.debug(f"BSN: Using primary monitor bounds: {self.screen_w}x{self.screen_h}+{self.screen_x}+{self.screen_y}")

    def get_frank_geometry(self) -> dict:
        """Aktuelle Frank-Geometrie."""
        return {
            "x": self.overlay.winfo_x(),
            "y": self.overlay.winfo_y(),
            "width": self.overlay.winfo_width(),
            "height": self.overlay.winfo_height()
        }

    def negotiate(self) -> dict:
        """
        Berechnet optimales Layout.

        Returns:
            {"success", "frank_action", "frank": {geometry}, "app": {geometry}}
        """
        self._ensure_screen_info()
        frank = self.get_frank_geometry()

        # Strategie 1: Frank bleibt, App füllt den Rest
        result = self._try_keep_frank(frank)
        if result["success"]:
            return result

        # Strategie 2: Frank schrumpft horizontal
        result = self._try_shrink_frank(frank)
        if result["success"]:
            return result

        # Strategie 3: Frank verschiebt sich an den linken Rand
        result = self._try_move_frank(frank)
        if result["success"]:
            return result

        # Strategie 4: Frank schrumpft UND verschiebt sich
        result = self._try_shrink_and_move()
        if result["success"]:
            return result

        # Strategie 5: Notfall-Layout
        return self._emergency_layout()

    def _try_keep_frank(self, frank: dict) -> dict:
        """Strategie 1: Frank bleibt, App passt daneben."""
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

        # Prüfe links von Frank
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
        """Strategie 2: Frank schrumpft horizontal."""
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
        """Strategie 3: Frank verschiebt sich an linken Rand."""
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
        """Strategie 4: Frank auf Minimum und an linken Rand."""
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
        """Strategie 5: Notfall für sehr kleine Screens."""
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
