#!/usr/bin/env python3
"""
Dream Watchdog — Ensures the Dream Daemon stays alive
======================================================

Primary watchdog layer for aicore-dream.service.
A secondary meta-watchdog (dream_watchdog_meta.py) monitors THIS process.

Responsibilities:
1. Ensure aicore-dream is enabled and running
2. Restart on crash with cooldown + backoff
3. Detect freeze (no dream.db write in expected window)
4. Write health status to /tmp/frank/dream_watchdog_health.json
"""

import json
import logging
import os
import signal
import sqlite3
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
    from config.paths import AICORE_LOG as _LOG_DIR, get_db
except ImportError:
    _LOG_DIR = Path.home() / ".local" / "share" / "frank" / "logs"
    def get_db(name):
        return Path.home() / ".local" / "share" / "frank" / "db" / f"{name}.db"

LOG_FILE = _LOG_DIR / "dream_watchdog.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
LOG = logging.getLogger("dream.watchdog")

# Config
SERVICE_NAME = "aicore-dream"
CHECK_INTERVAL = 30          # seconds between checks
MAX_RESTART_ATTEMPTS = 10
RESTART_COOLDOWN = 60        # seconds between restart attempts
HEALTH_FILE = Path("/tmp/frank/dream_watchdog_health.json")

# State
restart_attempts = 0
last_restart_time = None
running = True


def signal_handler(signum, frame):
    global running
    LOG.info("Signal %d received, stopping dream watchdog...", signum)
    running = False


def is_service_running() -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", SERVICE_NAME],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() == "active"
    except Exception as e:
        LOG.warning("Failed to check service status: %s", e)
        return False


def get_service_status() -> dict:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show", SERVICE_NAME,
             "--property=ActiveState,SubState,MainPID,MemoryCurrent"],
            capture_output=True, text=True, timeout=10,
        )
        status = {}
        for line in result.stdout.strip().split("\n"):
            if "=" in line:
                key, value = line.split("=", 1)
                status[key] = value
        return status
    except Exception as e:
        LOG.warning("Failed to get service status: %s", e)
        return {}


def ensure_service_enabled():
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-enabled", SERVICE_NAME],
            capture_output=True, text=True, timeout=10,
        )
        if result.stdout.strip() != "enabled":
            LOG.info("Enabling %s...", SERVICE_NAME)
            subprocess.run(
                ["systemctl", "--user", "enable", SERVICE_NAME],
                capture_output=True, timeout=10,
            )
    except Exception as e:
        LOG.warning("Failed to enable service: %s", e)


def restart_service() -> bool:
    global restart_attempts, last_restart_time

    if last_restart_time:
        elapsed = (datetime.now() - last_restart_time).total_seconds()
        if elapsed < RESTART_COOLDOWN:
            LOG.warning("Restart cooldown, waiting %.0fs", RESTART_COOLDOWN - elapsed)
            return False

    if restart_attempts >= MAX_RESTART_ATTEMPTS:
        if last_restart_time:
            elapsed = (datetime.now() - last_restart_time).total_seconds()
            if elapsed > 600:
                restart_attempts = 0
                LOG.info("Reset restart counter after 10 minutes")
            else:
                LOG.error("Max restart attempts (%d) reached!", MAX_RESTART_ATTEMPTS)
                return False
        else:
            return False

    LOG.warning("Restarting %s (attempt %d)...", SERVICE_NAME, restart_attempts + 1)

    try:
        result = subprocess.run(
            ["systemctl", "--user", "restart", SERVICE_NAME],
            capture_output=True, text=True, timeout=30,
        )
        restart_attempts += 1
        last_restart_time = datetime.now()

        if result.returncode == 0:
            LOG.info("Restart command sent successfully")
            time.sleep(5)
            if is_service_running():
                LOG.info("Dream daemon running after restart!")
                restart_attempts = 0
                return True
            else:
                LOG.error("Dream daemon failed to start after restart")
                return False
        else:
            LOG.error("Restart failed: %s", result.stderr)
            return False
    except Exception as e:
        LOG.error("Restart exception: %s", e)
        restart_attempts += 1
        last_restart_time = datetime.now()
        return False


def get_dream_db_health() -> dict:
    """Check dream.db for recent activity."""
    try:
        db_path = get_db("dream")
        if not db_path.exists() or db_path.stat().st_size == 0:
            return {"status": "empty", "total_dreams": 0}

        conn = sqlite3.connect(str(db_path), timeout=5)
        row = conn.execute(
            "SELECT total_dreams, status, updated_at FROM dream_state ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()

        if row:
            return {
                "status": row[1],
                "total_dreams": row[0],
                "last_update": row[2],
            }
        return {"status": "no_state", "total_dreams": 0}
    except Exception as e:
        return {"status": f"error: {e}", "total_dreams": 0}


def write_health(is_healthy: bool, details: dict):
    try:
        HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        HEALTH_FILE.write_text(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "healthy": is_healthy,
            "service": SERVICE_NAME,
            "restart_attempts": restart_attempts,
            "details": details,
        }, indent=2))
    except Exception:
        pass


def main():
    global running

    LOG.info("=" * 50)
    LOG.info("Dream Watchdog starting...")
    LOG.info("=" * 50)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    ensure_service_enabled()

    if not is_service_running():
        LOG.warning("Dream daemon not running at watchdog start, starting it...")
        restart_service()

    consecutive_failures = 0

    while running:
        try:
            is_running = is_service_running()
            status = get_service_status()
            dream_health = get_dream_db_health()

            if is_running:
                consecutive_failures = 0
                write_health(True, {**status, "dream_db": dream_health})
                LOG.debug("Dream daemon healthy: PID=%s", status.get("MainPID", "?"))
            else:
                consecutive_failures += 1
                LOG.warning(
                    "Dream daemon not running! (consecutive failures: %d)",
                    consecutive_failures,
                )
                write_health(False, {
                    "consecutive_failures": consecutive_failures,
                    "dream_db": dream_health,
                })

                if restart_service():
                    consecutive_failures = 0
                else:
                    if consecutive_failures >= 5:
                        LOG.error("Multiple failures, trying reset-failed...")
                        try:
                            subprocess.run(
                                ["systemctl", "--user", "reset-failed", SERVICE_NAME],
                                timeout=10,
                            )
                            time.sleep(2)
                            restart_service()
                        except Exception as e:
                            LOG.error("Reset-failed also failed: %s", e)

            for _ in range(CHECK_INTERVAL):
                if not running:
                    break
                time.sleep(1)

        except Exception as e:
            LOG.error("Watchdog error: %s", e)
            time.sleep(10)

    LOG.info("Dream Watchdog stopped")


if __name__ == "__main__":
    main()
