"""X11 DOCK window type and strut management via xprop.

Sets _NET_WM_WINDOW_TYPE_DOCK so the WM treats Frank as a panel.
Sets _NET_WM_STRUT_PARTIAL to reserve left-edge screen space.
"""

import os
import subprocess

try:
    from overlay.constants import LOG
except ImportError:
    import logging
    LOG = logging.getLogger(__name__)

_ENV = {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}


def find_client_window(tk_winfo_id: int) -> int:
    """Find the Tk client window ID from winfo_id().

    Tk's winfo_id() returns an internal container. Its parent
    (the Tk toplevel with WM_CLASS "tk"/"Tk") is the actual client
    window that the WM manages. EWMH properties go on THAT window.
    """
    try:
        result = subprocess.run(
            ["xwininfo", "-id", str(tk_winfo_id), "-tree"],
            capture_output=True, text=True, timeout=2, env=_ENV,
        )
        for line in result.stdout.split("\n"):
            if "Parent window id:" in line:
                hex_str = line.split(":")[1].strip().split()[0]
                parent_id = int(hex_str, 16)
                # Don't return root window (usually small ID like 0x3dc)
                if parent_id > 0x10000:
                    LOG.info("Client window: 0x%x (parent of 0x%x)", parent_id, tk_winfo_id)
                    return parent_id
    except Exception as e:
        LOG.warning("find_client_window failed: %s", e)
    return tk_winfo_id


def find_frank_xid() -> int:
    """Find the actual X11 window ID for 'F.R.A.N.K.' via xdotool.

    Used as fallback when the window is already mapped.
    """
    try:
        result = subprocess.run(
            ["xdotool", "search", "--name", "F.R.A.N.K."],
            capture_output=True, text=True, timeout=3, env=_ENV,
        )
        wids = result.stdout.strip().split("\n")
        if wids and wids[0]:
            xid = int(wids[0])
            LOG.info("Found Frank X11 window: %d (0x%x)", xid, xid)
            return xid
    except Exception as e:
        LOG.warning("xdotool search failed: %s", e)
    return 0


def set_window_type_dock(wid: int) -> bool:
    """Set _NET_WM_WINDOW_TYPE to _NET_WM_WINDOW_TYPE_DOCK.

    Effects: no decorations, no taskbar entry, no Alt+Tab,
    WM respects strut for space reservation, own layer in WM.
    """
    try:
        subprocess.run(
            ["xprop", "-id", str(wid),
             "-f", "_NET_WM_WINDOW_TYPE", "32a",
             "-set", "_NET_WM_WINDOW_TYPE", "_NET_WM_WINDOW_TYPE_DOCK"],
            capture_output=True, timeout=2, env=_ENV,
        )
        LOG.info("Window type set to DOCK (wid=%s)", wid)
        return True
    except Exception as e:
        LOG.error("Failed to set DOCK window type: %s", e)
        return False


def set_strut_partial(wid: int, left: int, left_start_y: int, left_end_y: int) -> bool:
    """Set _NET_WM_STRUT_PARTIAL to reserve left-side screen space.

    The WM will shrink the workarea so other windows avoid this region.

    Args:
        wid: X11 window ID
        left: total pixels to reserve from the left screen edge
        left_start_y: top of reserved region (usually 0)
        left_end_y: bottom of reserved region (usually screen_height - 1)
    """
    strut = f"{left}, 0, 0, 0, {left_start_y}, {left_end_y}, 0, 0, 0, 0, 0, 0"
    try:
        subprocess.run(
            ["xprop", "-id", str(wid),
             "-f", "_NET_WM_STRUT_PARTIAL", "32c",
             "-set", "_NET_WM_STRUT_PARTIAL", strut],
            capture_output=True, timeout=2, env=_ENV,
        )
        # Legacy strut for older WMs
        subprocess.run(
            ["xprop", "-id", str(wid),
             "-f", "_NET_WM_STRUT", "32c",
             "-set", "_NET_WM_STRUT", f"{left}, 0, 0, 0"],
            capture_output=True, timeout=2, env=_ENV,
        )
        LOG.info("Strut set: left=%d, y_range=%d-%d", left, left_start_y, left_end_y)
        return True
    except Exception as e:
        LOG.error("Failed to set strut: %s", e)
        return False


def clear_strut(wid: int) -> bool:
    """Clear strut reservation (for hide/destroy)."""
    try:
        subprocess.run(
            ["xprop", "-id", str(wid),
             "-f", "_NET_WM_STRUT_PARTIAL", "32c",
             "-set", "_NET_WM_STRUT_PARTIAL", "0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0"],
            capture_output=True, timeout=2, env=_ENV,
        )
        subprocess.run(
            ["xprop", "-id", str(wid),
             "-f", "_NET_WM_STRUT", "32c",
             "-set", "_NET_WM_STRUT", "0, 0, 0, 0"],
            capture_output=True, timeout=2, env=_ENV,
        )
        LOG.info("Strut cleared (wid=%s)", wid)
        return True
    except Exception as e:
        LOG.error("Failed to clear strut: %s", e)
        return False
