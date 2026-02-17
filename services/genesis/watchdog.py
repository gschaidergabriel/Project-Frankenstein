#!/usr/bin/env python3
"""
Genesis Watchdog - Ensures Genesis never dies
=============================================

This is a separate lightweight process that:
1. Monitors if Genesis is running
2. Restarts it if it's not
3. Reports health status
4. Runs with minimal resources
"""

import subprocess
import time
import sys
import os
import signal
import logging
from datetime import datetime
from pathlib import Path

# Setup logging
try:
    from config.paths import AICORE_LOG as _WD_LOG_DIR
    LOG_FILE = _WD_LOG_DIR / "genesis" / "watchdog.log"
except ImportError:
    LOG_FILE = Path.home() / ".local" / "share" / "frank" / "logs" / "genesis" / "watchdog.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ]
)
LOG = logging.getLogger("genesis.watchdog")

# Configuration
CHECK_INTERVAL = 30  # Check every 30 seconds
MAX_RESTART_ATTEMPTS = 10
RESTART_COOLDOWN = 60  # Wait 60s between restart attempts
SERVICE_NAME = "aicore-genesis"

# State
restart_attempts = 0
last_restart_time = None
running = True


def signal_handler(signum, frame):
    global running
    LOG.info(f"Received signal {signum}, stopping watchdog...")
    running = False


def is_genesis_running() -> bool:
    """Check if Genesis service is running."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", SERVICE_NAME],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.stdout.strip() == "active"
    except Exception as e:
        LOG.warning(f"Failed to check service status: {e}")
        return False


def get_genesis_status() -> dict:
    """Get detailed Genesis status."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show", SERVICE_NAME,
             "--property=ActiveState,SubState,MainPID,MemoryCurrent,CPUUsageNSec"],
            capture_output=True,
            text=True,
            timeout=10
        )

        status = {}
        for line in result.stdout.strip().split('\n'):
            if '=' in line:
                key, value = line.split('=', 1)
                status[key] = value

        return status
    except Exception as e:
        LOG.warning(f"Failed to get service status: {e}")
        return {}


def restart_genesis() -> bool:
    """Restart the Genesis service."""
    global restart_attempts, last_restart_time

    # Check cooldown
    if last_restart_time:
        elapsed = (datetime.now() - last_restart_time).total_seconds()
        if elapsed < RESTART_COOLDOWN:
            LOG.warning(f"In restart cooldown, waiting {RESTART_COOLDOWN - elapsed:.0f}s")
            return False

    # Check max attempts
    if restart_attempts >= MAX_RESTART_ATTEMPTS:
        LOG.error(f"Max restart attempts ({MAX_RESTART_ATTEMPTS}) reached!")
        # Reset counter after some time
        if last_restart_time:
            elapsed = (datetime.now() - last_restart_time).total_seconds()
            if elapsed > 600:  # 10 minutes
                restart_attempts = 0
                LOG.info("Reset restart counter after 10 minutes")
        return False

    LOG.warning(f"Restarting Genesis (attempt {restart_attempts + 1})...")

    try:
        # Try restart
        result = subprocess.run(
            ["systemctl", "--user", "restart", SERVICE_NAME],
            capture_output=True,
            text=True,
            timeout=30
        )

        restart_attempts += 1
        last_restart_time = datetime.now()

        if result.returncode == 0:
            LOG.info("Genesis restart command sent successfully")
            time.sleep(5)  # Wait for startup

            if is_genesis_running():
                LOG.info("Genesis is running after restart!")
                restart_attempts = 0  # Reset on success
                return True
            else:
                LOG.error("Genesis failed to start after restart command")
                return False
        else:
            LOG.error(f"Restart failed: {result.stderr}")
            return False

    except Exception as e:
        LOG.error(f"Restart exception: {e}")
        restart_attempts += 1
        last_restart_time = datetime.now()
        return False


def ensure_service_enabled():
    """Make sure the service is enabled."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-enabled", SERVICE_NAME],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.stdout.strip() != "enabled":
            LOG.info("Enabling Genesis service...")
            subprocess.run(
                ["systemctl", "--user", "enable", SERVICE_NAME],
                capture_output=True,
                timeout=10
            )
    except Exception as e:
        LOG.warning(f"Failed to check/enable service: {e}")


def write_health_status(is_healthy: bool, details: dict):
    """Write health status to file for monitoring."""
    try:
        try:
            from config.paths import get_temp as _gw_get_temp
            status_file = _gw_get_temp("genesis_health.json")
        except ImportError:
            status_file = Path("/tmp/frank/genesis_health.json")
        import json
        status_file.write_text(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "healthy": is_healthy,
            "restart_attempts": restart_attempts,
            "details": details,
        }, indent=2))
    except Exception:
        pass


def main():
    global running

    LOG.info("=" * 50)
    LOG.info("Genesis Watchdog starting...")
    LOG.info("=" * 50)

    # Signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Ensure service is enabled
    ensure_service_enabled()

    # Initial check
    if not is_genesis_running():
        LOG.warning("Genesis not running at watchdog start, starting it...")
        restart_genesis()

    # Main loop
    consecutive_failures = 0

    while running:
        try:
            is_running = is_genesis_running()
            status = get_genesis_status()

            if is_running:
                consecutive_failures = 0
                write_health_status(True, status)
                LOG.debug(f"Genesis healthy: PID={status.get('MainPID', '?')}")
            else:
                consecutive_failures += 1
                LOG.warning(f"Genesis not running! (consecutive failures: {consecutive_failures})")
                write_health_status(False, {"consecutive_failures": consecutive_failures})

                # Try to restart
                if restart_genesis():
                    consecutive_failures = 0
                else:
                    # If restart failed multiple times, try harder
                    if consecutive_failures >= 5:
                        LOG.error("Multiple restart failures, trying full service reset...")
                        try:
                            subprocess.run(
                                ["systemctl", "--user", "reset-failed", SERVICE_NAME],
                                timeout=10
                            )
                            time.sleep(2)
                            restart_genesis()
                        except Exception as e:
                            LOG.error(f"Reset-failed also failed: {e}")

            # Sleep
            for _ in range(CHECK_INTERVAL):
                if not running:
                    break
                time.sleep(1)

        except Exception as e:
            LOG.error(f"Watchdog error: {e}")
            time.sleep(10)

    LOG.info("Genesis Watchdog stopped")


if __name__ == "__main__":
    main()
