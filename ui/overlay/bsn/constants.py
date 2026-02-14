import os
import subprocess
from overlay.constants import LOG


def _get_workarea() -> dict:
    """
    Detect the usable workarea from the window manager via _NET_WORKAREA.

    This gives us the exact panel/dock offsets on ANY monitor setup.
    Returns:
        {"x": int, "y": int, "width": int, "height": int}
        On error: fallback to heuristic
    """
    try:
        env = {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
        result = subprocess.run(
            ["xprop", "-root", "_NET_WORKAREA"],
            capture_output=True, text=True, timeout=3, env=env
        )
        if result.returncode == 0 and "=" in result.stdout:
            # Parse: "_NET_WORKAREA(CARDINAL) = 66, 38, 958, 562, 66, 38, 958, 562"
            values = result.stdout.split("=")[1].strip().split(",")
            x = int(values[0].strip())
            y = int(values[1].strip())
            w = int(values[2].strip())
            h = int(values[3].strip())
            LOG.info(f"BSN: Workarea detected: x={x}, y={y}, w={w}, h={h}")
            return {"x": x, "y": y, "width": w, "height": h}
    except Exception as e:
        LOG.warning(f"BSN: Workarea detection failed: {e}")

    # Fallback: assume 40px panel, 66px dock
    return {"x": 66, "y": 40, "width": 1920 - 66, "height": 1080 - 40}


# Cache workarea at module load
_WORKAREA = _get_workarea()


def get_workarea_y() -> int:
    """Get the Y offset where the usable screen area starts (below GNOME panel)."""
    return _WORKAREA["y"]


def get_workarea_x() -> int:
    """Get the X offset where the usable screen area starts (right of GNOME dock)."""
    return _WORKAREA["x"]


def get_workarea() -> dict:
    """Get the full workarea dict."""
    return _WORKAREA.copy()


def refresh_workarea():
    """Re-detect workarea (call after monitor change)."""
    global _WORKAREA
    _WORKAREA = _get_workarea()


def _get_primary_monitor() -> dict:
    """
    Detect the primary monitor via xrandr.

    Returns:
        {"width": int, "height": int, "x": int, "y": int, "name": str}
        On error: fallback to 1920x1080
    """
    try:
        result = subprocess.run(
            ["xrandr", "--listmonitors"],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode != 0:
            raise RuntimeError("xrandr failed")

        # Parse output: "0: +*HDMI-A-0 1920/509x1080/286+0+0  HDMI-A-0"
        # Format: index: +[*]name width/mmx height/mm+x+y  name
        for line in result.stdout.splitlines():
            if '+*' in line:  # Primary monitor has asterisk
                # Extract geometry: "1920/509x1080/286+0+0"
                parts = line.split()
                for part in parts:
                    if '/' in part and 'x' in part and '+' in part:
                        # Parse "1920/509x1080/286+0+0"
                        geo = part.split('+')
                        dims = geo[0]  # "1920/509x1080/286"
                        x = int(geo[1])
                        y = int(geo[2])

                        # Extract width/height from "1920/509x1080/286"
                        w_part, h_part = dims.split('x')
                        width = int(w_part.split('/')[0])
                        height = int(h_part.split('/')[0])

                        name = parts[-1]  # Monitor name

                        LOG.info(f"BSN: Primary monitor detected: {name} {width}x{height}+{x}+{y}")
                        return {
                            "width": width,
                            "height": height,
                            "x": x,
                            "y": y,
                            "name": name
                        }

        raise RuntimeError("No primary monitor found")

    except Exception as e:
        LOG.warning(f"BSN: Monitor detection failed ({e}), using fallback 1920x1080")
        return {
            "width": 1920,
            "height": 1080,
            "x": 0,
            "y": 0,
            "name": "fallback"
        }


class BSNConstants:
    """Constants for the layout system."""
    # Frank Constraints
    FRANK_MIN_WIDTH = 340      # Minimum for usable UI
    FRANK_MIN_HEIGHT = 500     # Title + Messages + Input
    FRANK_DEFAULT_WIDTH = 420  # Default width

    # App Constraints
    APP_MIN_WIDTH = 600        # Minimum for usable app
    APP_MIN_HEIGHT = 400       # Minimum for usable app

    # Layout
    GAP = 15                   # Gap between Frank and app
    PANEL_HEIGHT = _WORKAREA["y"]   # Dynamic: from _NET_WORKAREA (GNOME Top Panel)
    DOCK_WIDTH = _WORKAREA["x"]     # Dynamic: from _NET_WORKAREA (GNOME Dock)
