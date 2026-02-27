#!/usr/bin/env python3
"""
Dream Meta-Watchdog — Watches the Dream Watchdog
=================================================

Secondary failsafe layer. If the primary dream watchdog
(aicore-dream-watchdog.service) dies, this meta-watchdog
detects it and restarts both the watchdog and the dream daemon.

Defense in depth:
  Layer 0: systemd Restart=always on aicore-dream
  Layer 1: dream_watchdog.py (primary, monitors dream daemon)
  Layer 2: dream_watchdog_meta.py (THIS, monitors Layer 1)
"""

import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Path setup
_aicore_root = Path(__file__).resolve().parent.parent
if str(_aicore_root) not in sys.path:
    sys.path.insert(0, str(_aicore_root))

try:
    from config.paths import AICORE_LOG as _LOG_DIR
except ImportError:
    _LOG_DIR = Path.home() / ".local" / "share" / "frank" / "logs"

LOG_FILE = _LOG_DIR / "dream_watchdog_meta.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
LOG = logging.getLogger("dream.watchdog.meta")

# Config
PRIMARY_WATCHDOG = "aicore-dream-watchdog"
DREAM_SERVICE = "aicore-dream"
CHECK_INTERVAL = 60          # Check every 60s (slower than primary)
HEALTH_FILE = Path("/tmp/frank/dream_watchdog_health.json")
HEALTH_STALE_TIMEOUT = 120   # If health file >120s old, primary is frozen
META_HEALTH_FILE = Path("/tmp/frank/dream_meta_watchdog_health.json")

running = True


def signal_handler(signum, frame):
    global running
    LOG.info("Signal %d received, stopping meta-watchdog...", signum)
    running = False


def is_service_running(name: str) -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", name],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False


def restart_service(name: str) -> bool:
    LOG.warning("Restarting %s...", name)
    try:
        subprocess.run(
            ["systemctl", "--user", "enable", name],
            capture_output=True, timeout=10,
        )
        result = subprocess.run(
            ["systemctl", "--user", "restart", name],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            time.sleep(5)
            if is_service_running(name):
                LOG.info("%s restarted successfully", name)
                return True
        LOG.error("Failed to restart %s: %s", name, result.stderr)
        return False
    except Exception as e:
        LOG.error("Restart exception for %s: %s", name, e)
        return False


def check_primary_health_file() -> str:
    """Check if primary watchdog health file is recent.
    Returns: 'ok', 'stale', 'missing'
    """
    try:
        if not HEALTH_FILE.exists():
            return "missing"

        data = json.loads(HEALTH_FILE.read_text())
        ts = datetime.fromisoformat(data["timestamp"])
        age = (datetime.now() - ts).total_seconds()

        if age > HEALTH_STALE_TIMEOUT:
            return "stale"
        return "ok"
    except Exception:
        return "missing"


def write_meta_health(status: str, details: dict):
    try:
        META_HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        META_HEALTH_FILE.write_text(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "status": status,
            "primary_watchdog": PRIMARY_WATCHDOG,
            "dream_service": DREAM_SERVICE,
            "details": details,
        }, indent=2))
    except Exception:
        pass


def main():
    global running

    LOG.info("=" * 50)
    LOG.info("Dream Meta-Watchdog starting...")
    LOG.info("  Monitors: %s (primary watchdog)", PRIMARY_WATCHDOG)
    LOG.info("  Fallback: %s (dream daemon)", DREAM_SERVICE)
    LOG.info("=" * 50)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    while running:
        try:
            primary_alive = is_service_running(PRIMARY_WATCHDOG)
            dream_alive = is_service_running(DREAM_SERVICE)
            health_status = check_primary_health_file()

            # Case 1: Everything OK
            if primary_alive and dream_alive:
                write_meta_health("ok", {
                    "primary_watchdog": "running",
                    "dream_daemon": "running",
                    "health_file": health_status,
                })
                LOG.debug("All OK: primary watchdog + dream daemon running")

            # Case 2: Primary watchdog dead
            elif not primary_alive:
                LOG.error("PRIMARY WATCHDOG DOWN! Restarting...")
                write_meta_health("primary_down", {
                    "primary_watchdog": "dead",
                    "dream_daemon": "running" if dream_alive else "dead",
                })

                # Restart primary watchdog (it will handle the dream daemon)
                restart_service(PRIMARY_WATCHDOG)

                # If dream is also dead, restart it directly (don't wait for primary)
                if not dream_alive:
                    LOG.error("Dream daemon also down, direct restart...")
                    restart_service(DREAM_SERVICE)

            # Case 3: Primary alive but dream dead (primary should handle this,
            #          but intervene if health file is stale = primary is frozen)
            elif primary_alive and not dream_alive:
                if health_status == "stale":
                    LOG.error(
                        "Dream down + primary health stale (>%ds). "
                        "Primary watchdog may be frozen, restarting both...",
                        HEALTH_STALE_TIMEOUT,
                    )
                    restart_service(PRIMARY_WATCHDOG)
                    time.sleep(3)
                    if not is_service_running(DREAM_SERVICE):
                        restart_service(DREAM_SERVICE)
                else:
                    LOG.warning(
                        "Dream down, but primary watchdog is alive. "
                        "Giving primary 60s to handle it..."
                    )
                    write_meta_health("dream_down_primary_handling", {
                        "primary_watchdog": "running",
                        "dream_daemon": "dead",
                        "health_file": health_status,
                    })

            for _ in range(CHECK_INTERVAL):
                if not running:
                    break
                time.sleep(1)

        except Exception as e:
            LOG.error("Meta-watchdog error: %s", e)
            time.sleep(10)

    LOG.info("Dream Meta-Watchdog stopped")


if __name__ == "__main__":
    main()
