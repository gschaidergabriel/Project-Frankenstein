"""X11 DOCK window type and strut management.

Primary: ctypes/Xlib (microsecond latency, no subprocess).
Fallback: xprop subprocess (if Xlib fails).
"""

import ctypes
import ctypes.util
import os
import subprocess
import threading

try:
    from overlay.constants import LOG
except ImportError:
    import logging
    LOG = logging.getLogger(__name__)

_ENV = {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}


# ── Xlib ctypes interface (fast path) ───────────────────────────────

# Xlib error handler type: int handler(Display*, XErrorEvent*)
_XERROR_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
# Xlib IO error handler type: int handler(Display*)
_XIOERROR_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p)


def _noop_error_handler(_display, _event):
    """Suppress Xlib errors instead of crashing the process.

    Default Xlib error handler calls exit(1). We replace it with a no-op
    so protocol errors (stale window IDs, etc.) don't kill the overlay.
    """
    return 0


def _io_error_handler(_display):
    """Handle fatal X11 IO errors (connection lost).

    XSetIOErrorHandler callback must NOT return (undefined behavior).
    We log the error, then _exit to avoid SEGV from returning.
    """
    import sys
    try:
        LOG.error("FATAL: X11 IO error (display connection lost) — exiting")
    except Exception:
        pass
    # os._exit bypasses Python cleanup which could trigger more X11 calls
    os._exit(11)  # exit code 11 like SEGV for easy identification
    return 0  # unreachable but required by signature


_noop_handler_ref = _XERROR_HANDLER(_noop_error_handler)  # prevent GC
_io_handler_ref = _XIOERROR_HANDLER(_io_error_handler)  # prevent GC


class _XlibStrut:
    """Direct Xlib strut setter — avoids subprocess overhead.

    Thread-safe: a lock serializes all Xlib calls on this connection.
    """

    _PropModeReplace = 0

    def __init__(self):
        self._display = None
        self._lib = None
        self._atom_strut_partial = 0
        self._atom_strut = 0
        self._atom_cardinal = 0
        self._lock = threading.Lock()
        self._setup()

    def _setup(self):
        path = ctypes.util.find_library("X11")
        if not path:
            return
        try:
            lib = ctypes.cdll.LoadLibrary(path)
            # Signatures
            lib.XOpenDisplay.restype = ctypes.c_void_p
            lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
            lib.XInternAtom.restype = ctypes.c_ulong
            lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
            lib.XChangeProperty.restype = ctypes.c_int
            lib.XChangeProperty.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
                ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                ctypes.c_void_p, ctypes.c_int,
            ]
            lib.XSync.restype = ctypes.c_int
            lib.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
            lib.XSetErrorHandler.restype = ctypes.c_void_p
            lib.XSetErrorHandler.argtypes = [_XERROR_HANDLER]
            lib.XSetIOErrorHandler.restype = ctypes.c_void_p
            lib.XSetIOErrorHandler.argtypes = [_XIOERROR_HANDLER]
            lib.XCloseDisplay.restype = ctypes.c_int
            lib.XCloseDisplay.argtypes = [ctypes.c_void_p]

            display_name = os.environ.get("DISPLAY", ":0").encode()
            display = lib.XOpenDisplay(display_name)
            if not display:
                return

            # Install error handlers so Xlib errors don't SEGV/exit the process.
            # These are GLOBAL (affect all Xlib connections including tkinter's).
            lib.XSetErrorHandler(_noop_handler_ref)
            lib.XSetIOErrorHandler(_io_handler_ref)

            self._lib = lib
            self._display = display
            self._atom_strut_partial = lib.XInternAtom(
                display, b"_NET_WM_STRUT_PARTIAL", 0)
            self._atom_strut = lib.XInternAtom(
                display, b"_NET_WM_STRUT", 0)
            self._atom_cardinal = lib.XInternAtom(
                display, b"CARDINAL", 0)
            LOG.info("Xlib strut fast-path ready")
        except Exception as e:
            LOG.warning("Xlib strut init failed (will use xprop fallback): %s", e)

    @property
    def available(self):
        return self._display is not None

    def set_strut(self, wid: int, left: int, left_start_y: int, left_end_y: int) -> bool:
        if not self.available:
            return False
        with self._lock:
            try:
                data12 = (ctypes.c_long * 12)(
                    left, 0, 0, 0, left_start_y, left_end_y, 0, 0, 0, 0, 0, 0)
                self._lib.XChangeProperty(
                    self._display, wid,
                    self._atom_strut_partial, self._atom_cardinal,
                    32, self._PropModeReplace,
                    ctypes.byref(data12), 12)

                data4 = (ctypes.c_long * 4)(left, 0, 0, 0)
                self._lib.XChangeProperty(
                    self._display, wid,
                    self._atom_strut, self._atom_cardinal,
                    32, self._PropModeReplace,
                    ctypes.byref(data4), 4)

                # XSync (not XFlush): flushes output AND drains pending events.
                # XFlush only flushes output, leaving incoming events unprocessed
                # which can corrupt the connection state over time.
                self._lib.XSync(self._display, 0)
                return True
            except Exception:
                return False

    def clear_strut(self, wid: int) -> bool:
        return self.set_strut(wid, 0, 0, 0)

    def __del__(self):
        if self._display and self._lib:
            try:
                self._lib.XCloseDisplay(self._display)
            except Exception:
                pass


_xlib = None


def _get_xlib() -> _XlibStrut:
    global _xlib
    if _xlib is None:
        _xlib = _XlibStrut()
    return _xlib


# ── Public API ───────────────────────────────────────────────────────

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
                if parent_id > 0x10000:
                    LOG.info("Client window: 0x%x (parent of 0x%x)", parent_id, tk_winfo_id)
                    return parent_id
    except Exception as e:
        LOG.warning("find_client_window failed: %s", e)
    return tk_winfo_id


def find_frank_xid() -> int:
    """Find the actual X11 window ID for 'F.R.A.N.K.' via xdotool."""
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
    """Set _NET_WM_WINDOW_TYPE to _NET_WM_WINDOW_TYPE_DOCK and hide from taskbar."""
    try:
        subprocess.run(
            ["xprop", "-id", str(wid),
             "-f", "_NET_WM_WINDOW_TYPE", "32a",
             "-set", "_NET_WM_WINDOW_TYPE", "_NET_WM_WINDOW_TYPE_DOCK"],
            capture_output=True, timeout=2, env=_ENV,
        )
        # Hide from GNOME dock/taskbar so only the pinned .desktop favorite
        # (full-size icon) is visible — DOCK windows render tiny otherwise.
        subprocess.run(
            ["xprop", "-id", str(wid),
             "-f", "_NET_WM_STATE", "32a",
             "-set", "_NET_WM_STATE",
             "_NET_WM_STATE_SKIP_TASKBAR, _NET_WM_STATE_SKIP_PAGER"],
            capture_output=True, timeout=2, env=_ENV,
        )
        LOG.info("Window type set to DOCK + SKIP_TASKBAR (wid=%s)", wid)
        return True
    except Exception as e:
        LOG.error("Failed to set DOCK window type: %s", e)
        return False


def set_strut_partial(wid: int, left: int, left_start_y: int, left_end_y: int) -> bool:
    """Set _NET_WM_STRUT_PARTIAL to reserve left-side screen space.

    Uses ctypes/Xlib (fast) with xprop subprocess as fallback.
    """
    xlib = _get_xlib()
    if xlib.available and xlib.set_strut(wid, left, left_start_y, left_end_y):
        return True

    # Fallback: xprop subprocess
    strut = f"{left}, 0, 0, 0, {left_start_y}, {left_end_y}, 0, 0, 0, 0, 0, 0"
    try:
        subprocess.run(
            ["xprop", "-id", str(wid),
             "-f", "_NET_WM_STRUT_PARTIAL", "32c",
             "-set", "_NET_WM_STRUT_PARTIAL", strut],
            capture_output=True, timeout=2, env=_ENV,
        )
        subprocess.run(
            ["xprop", "-id", str(wid),
             "-f", "_NET_WM_STRUT", "32c",
             "-set", "_NET_WM_STRUT", f"{left}, 0, 0, 0"],
            capture_output=True, timeout=2, env=_ENV,
        )
        return True
    except Exception as e:
        LOG.error("Failed to set strut: %s", e)
        return False


def clear_strut(wid: int) -> bool:
    """Clear strut reservation (for hide/destroy)."""
    xlib = _get_xlib()
    if xlib.available and xlib.clear_strut(wid):
        LOG.info("Strut cleared via Xlib (wid=%s)", wid)
        return True

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
        LOG.info("Strut cleared via xprop (wid=%s)", wid)
        return True
    except Exception as e:
        LOG.error("Failed to clear strut: %s", e)
        return False
