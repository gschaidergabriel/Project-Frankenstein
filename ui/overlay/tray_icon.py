"""System tray icon for Frank overlay.

Launches tray_indicator.py as a separate process.
Communicates via TEMP_DIR/tray_toggle signal file.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from overlay.constants import LOG

# tray_indicator.py needs system GTK/GObject bindings (python3-gi,
# gir1.2-ayatanaappindicator3) which are not available inside a venv
# unless --system-site-packages is set.  Always use system python3.
_SYSTEM_PYTHON = shutil.which("python3") or "/usr/bin/python3"

try:
    from config.paths import TEMP_FILES as _TEMP_FILES
    TRAY_TOGGLE_SIGNAL = _TEMP_FILES["tray_toggle"]
except ImportError:
    TRAY_TOGGLE_SIGNAL = Path("/tmp/frank/tray_toggle")
_INDICATOR_SCRIPT = Path(__file__).parent / "tray_indicator.py"

_proc = None


def _kill_old_tray_procs():
    """Kill leftover tray icon processes from previous runs."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "tray_indicator.py"],
            capture_output=True, text=True, timeout=3,
        )
        for pid_str in result.stdout.strip().split():
            try:
                pid = int(pid_str)
                if pid != os.getpid():
                    os.kill(pid, 15)
            except Exception:
                pass
    except Exception:
        pass


def start_tray_icon() -> bool:
    """Start tray icon as separate process."""
    global _proc

    _kill_old_tray_procs()

    try:
        TRAY_TOGGLE_SIGNAL.unlink(missing_ok=True)
    except Exception:
        pass

    if not _INDICATOR_SCRIPT.exists():
        LOG.warning("tray_indicator.py not found")
        return False

    try:
        env = {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
        _proc = subprocess.Popen(
            [_SYSTEM_PYTHON, str(_INDICATOR_SCRIPT)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        LOG.info("System tray icon started (PID %d)", _proc.pid)
        return True
    except Exception as e:
        LOG.warning(f"Failed to start tray icon: {e}")
        return False


def stop_tray_icon():
    global _proc
    if _proc is not None:
        try:
            _proc.terminate()
            _proc.wait(timeout=3)
        except Exception:
            try:
                _proc.kill()
            except Exception:
                pass
        _proc = None
    _kill_old_tray_procs()
    try:
        TRAY_TOGGLE_SIGNAL.unlink(missing_ok=True)
    except Exception:
        pass
