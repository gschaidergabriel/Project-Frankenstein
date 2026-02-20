#!/usr/bin/env python3
"""
Frank Self-Restart Tool
========================
Allows Frank to request restarts of his own services via the watchdog.

Instead of going through the approval queue (which requires user confirmation),
Frank writes a restart request file that the watchdog picks up and executes.

This is SAFE because:
1. Only user-level services can be restarted (no system services)
2. The watchdog validates the service name against its monitored list
3. Systemd handles clean shutdown/startup
4. The watchdog has restart limits and cooldowns

Usage:
    from tools.self_restart import request_restart, request_full_restart

    # Restart a specific service
    request_restart("frank-overlay", reason="UI hang detected")

    # Restart all monitored services
    request_full_restart(reason="Major configuration change")
"""

import json
import logging
import time
from pathlib import Path

LOG = logging.getLogger("tools.self_restart")

try:
    from config.paths import get_temp as _sr_get_temp
    RESTART_REQUEST_FILE = _sr_get_temp("restart_request.json")
    USER_CLOSED_SIGNAL = _sr_get_temp("user_closed")
except ImportError:
    import tempfile as _sr_tempfile
    _sr_temp_dir = Path(_sr_tempfile.gettempdir()) / "frank"
    _sr_temp_dir.mkdir(parents=True, exist_ok=True)
    RESTART_REQUEST_FILE = _sr_temp_dir / "restart_request.json"
    USER_CLOSED_SIGNAL = _sr_temp_dir / "user_closed"

# Services Frank is allowed to restart
ALLOWED_SERVICES = {
    "frank-overlay",
    "aicore-core",
    "aicore-router",
    "aicore-llama3-gpu",
    "aicore-qwen-gpu",
    "aicore-whisper-gpu",
    "aicore-modeld",
    "aicore-toolboxd",
    "aicore-webd",
    "aicore-desktopd",
    "aicore-ingestd",
    "aicore-genesis",
    "frank-ewish-daemon",
    "frank-sentinel",
    "frank-news-scanner",
    "uolg",
    "all",  # Special: restart all monitored services
}


def request_restart(service: str, reason: str = "self-restart") -> bool:
    """
    Request restart of a specific service via the watchdog.

    Args:
        service: Service name (e.g., "frank-overlay", "aicore-core")
        reason: Human-readable reason for the restart

    Returns:
        True if request was written successfully
    """
    if service not in ALLOWED_SERVICES:
        LOG.warning(f"Service '{service}' not in allowed list, rejecting restart request")
        return False

    try:
        # Clear user-closed signal so watchdog allows the restart
        if service in ("frank-overlay", "all"):
            try:
                USER_CLOSED_SIGNAL.unlink(missing_ok=True)
                LOG.info("Cleared user-close signal for frank-overlay restart")
            except Exception:
                pass

        request = {
            "service": service,
            "reason": reason,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": "frank_self_restart",
        }

        # Atomic write
        tmp = RESTART_REQUEST_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(request))
        tmp.rename(RESTART_REQUEST_FILE)

        LOG.info(f"Restart request written for '{service}': {reason}")
        return True

    except Exception as e:
        LOG.error(f"Failed to write restart request: {e}")
        return False


def request_full_restart(reason: str = "full self-restart") -> bool:
    """Request restart of ALL monitored services."""
    return request_restart("all", reason)


def get_watchdog_health() -> dict:
    """Read the watchdog health status."""
    try:
        from config.paths import get_temp as _sr_gt
        health_file = _sr_gt("watchdog_health.json")
    except ImportError:
        import tempfile as _sr_tmp
        health_file = Path(_sr_tmp.gettempdir()) / "frank" / "watchdog_health.json"
    try:
        if health_file.exists():
            return json.loads(health_file.read_text())
    except Exception:
        pass
    return {"overall_healthy": None, "services": {}}


def is_watchdog_running() -> bool:
    """Check if the watchdog itself is running."""
    import subprocess
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "frank-watchdog"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: self_restart.py <service|all|status> [reason]")
        print(f"\nAllowed services: {', '.join(sorted(ALLOWED_SERVICES - {'all'}))}")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "status":
        health = get_watchdog_health()
        watchdog_active = is_watchdog_running()
        print(f"Watchdog active: {watchdog_active}")
        print(f"Overall healthy: {health.get('overall_healthy', '?')}")
        print(f"Last check: {health.get('timestamp', '?')}")
        for name, svc in health.get("services", {}).items():
            status = "OK" if not svc.get("gave_up") else "GAVE UP"
            restarts = svc.get("restart_count", 0)
            print(f"  {name}: {status} (restarts: {restarts})")
    elif cmd == "all":
        reason = " ".join(sys.argv[2:]) or "manual full restart"
        if request_full_restart(reason):
            print("Full restart request sent to watchdog")
        else:
            print("Failed to send restart request")
    elif cmd in ALLOWED_SERVICES:
        reason = " ".join(sys.argv[2:]) or "manual restart"
        if request_restart(cmd, reason):
            print(f"Restart request for '{cmd}' sent to watchdog")
        else:
            print("Failed to send restart request")
    else:
        print(f"Unknown service: {cmd}")
        print(f"Allowed: {', '.join(sorted(ALLOWED_SERVICES - {'all'}))}")
