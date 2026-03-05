"""
Neural Immune System — Entry Point
====================================
Run as: python3 -m services.neural_immune

Integrates with systemd via sd_notify:
  - READY=1      after initialization
  - WATCHDOG=1   every WatchdogSec/2 (30s)

Hardware-agnostic: runs on any Linux with systemd + Python 3.10+.
"""

import logging
import logging.handlers
import os
import sys
import threading
import time
from pathlib import Path

# Ensure project root is on path
_project_root = str(Path(__file__).resolve().parents[2])
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Setup logging
try:
    from config.paths import AICORE_LOG
    LOG_DIR = AICORE_LOG
except ImportError:
    LOG_DIR = Path.home() / ".local" / "share" / "frank" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(name)s %(levelname)s: %(message)s",
    handlers=[
        logging.handlers.RotatingFileHandler(
            LOG_DIR / "immune_system.log",
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=3,
        ),
        logging.StreamHandler(),
    ],
)
LOG = logging.getLogger("immune")


def _sd_notify(msg: str):
    """Send sd_notify message (portable: works with or without systemd)."""
    sock_path = os.environ.get("NOTIFY_SOCKET")
    if not sock_path:
        return
    try:
        import socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            if sock_path.startswith("@"):
                sock_path = "\0" + sock_path[1:]
            sock.connect(sock_path)
            sock.sendall(msg.encode())
        finally:
            sock.close()
    except Exception:
        pass


def _watchdog_thread(interval: float = 30.0):
    """Background thread sending WATCHDOG=1 every interval seconds."""
    while True:
        _sd_notify("WATCHDOG=1")
        time.sleep(interval)


def main():
    LOG.info("Neural Immune System starting...")

    from services.neural_immune import get_immune_system
    immune = get_immune_system()

    # Start watchdog pinger (daemon thread — dies with main)
    wd_thread = threading.Thread(target=_watchdog_thread, args=(30.0,), daemon=True)
    wd_thread.start()

    # Signal ready to systemd
    _sd_notify("READY=1")
    LOG.info("sd_notify READY=1 sent")

    # Run main loop (blocking)
    immune.run()


if __name__ == "__main__":
    from config.logging_config import setup_file_logging
    setup_file_logging("immune")
    try:
        main()
    except Exception:
        LOG.critical("Fatal error in immune system", exc_info=True)
        sys.exit(1)
