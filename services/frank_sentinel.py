#!/usr/bin/env python3
"""
Frank Sentinel — Backup Watchdog
==================================
Ultra-lightweight second watchdog that monitors the primary watchdog.
If frank-watchdog.service dies, this restarts it.

Also performs a minimal health-check on the 3 most critical services
(core, router, webd) as a last-resort safety net.

Design: ~20 lines of logic, zero dependencies beyond stdlib.
If BOTH watchdogs die, systemd Restart=always catches them independently.
"""

import json
import signal
import subprocess
import sys
import time
import logging
from pathlib import Path

LOG_DIR = Path.home() / ".local" / "share" / "frank" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "frank_sentinel.log"

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] SENTINEL %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ]
)
LOG = logging.getLogger("frank.sentinel")

# Primary watchdog + bare minimum safety-net services
PRIMARY_WATCHDOG = "frank-watchdog"
SAFETY_NET = ["aicore-core", "aicore-router", "aicore-webd"]

CHECK_INTERVAL = 30       # Check every 30 seconds
RESTART_COOLDOWN = 60     # Min seconds between restart attempts per service
FULL_SHUTDOWN_SIGNAL = Path("/tmp/frank/full_shutdown")

_last_restart: dict[str, float] = {}
_running = True


def _signal_handler(signum, frame):
    global _running
    LOG.info(f"Signal {signum}, stopping sentinel")
    _running = False


def _is_active(svc: str) -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", svc],
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip() == "active"
    except Exception:
        return False


def _restart(svc: str) -> bool:
    now = time.time()
    if now - _last_restart.get(svc, 0) < RESTART_COOLDOWN:
        return False
    try:
        subprocess.run(
            ["systemctl", "--user", "reset-failed", svc],
            capture_output=True, timeout=10,
        )
        r = subprocess.run(
            ["systemctl", "--user", "restart", svc],
            capture_output=True, text=True, timeout=30,
        )
        _last_restart[svc] = now
        return r.returncode == 0
    except Exception as e:
        LOG.error(f"Restart {svc} failed: {e}")
        _last_restart[svc] = now
        return False


def _sd_notify(msg: str):
    """Notify systemd (WatchdogSec support)."""
    addr = __import__("os").environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    import socket
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        if addr.startswith("@"):
            addr = "\0" + addr[1:]
        sock.connect(addr)
        sock.send(msg.encode())
    finally:
        sock.close()


def main():
    global _running
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    LOG.info("=" * 50)
    LOG.info("Frank Sentinel starting — watching the watcher")
    LOG.info("=" * 50)

    _sd_notify("READY=1")

    while _running:
        try:
            # Pause during full shutdown
            if FULL_SHUTDOWN_SIGNAL.exists():
                time.sleep(10)
                _sd_notify("WATCHDOG=1")
                continue

            # 1) Primary watchdog alive?
            if not _is_active(PRIMARY_WATCHDOG):
                LOG.warning(f"PRIMARY WATCHDOG DOWN — restarting {PRIMARY_WATCHDOG}")
                if _restart(PRIMARY_WATCHDOG):
                    time.sleep(3)
                    if _is_active(PRIMARY_WATCHDOG):
                        LOG.info("Primary watchdog restored")
                    else:
                        LOG.error("Primary watchdog restart failed — safety net active")
                else:
                    LOG.error("Could not restart primary watchdog")

            # 2) Safety net: check bare-minimum services
            #    (only acts if primary watchdog is also down)
            if not _is_active(PRIMARY_WATCHDOG):
                for svc in SAFETY_NET:
                    if not _is_active(svc):
                        LOG.warning(f"SAFETY NET: {svc} down, restarting")
                        if _restart(svc):
                            LOG.info(f"SAFETY NET: {svc} restarted")

            # Pet systemd watchdog
            _sd_notify("WATCHDOG=1")

        except Exception as e:
            LOG.error(f"Sentinel error: {e}")

        for _ in range(CHECK_INTERVAL):
            if not _running:
                break
            time.sleep(1)

    LOG.info("Frank Sentinel stopped")


if __name__ == "__main__":
    main()
