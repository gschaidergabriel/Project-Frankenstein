#!/usr/bin/env python3
"""
Frank Universal Service Watchdog
=================================
Ensures critical Frank services stay alive.

Monitors:
- frank-overlay (Chat UI)
- aicore-core (Chat orchestrator)
- aicore-router (Model routing)
- aicore-llama3-gpu (Primary LLM)
Unlike the Genesis-specific watchdog, this covers Frank's core
infrastructure. If a service dies, it gets restarted automatically
without needing user approval (crash recovery is always safe).

This runs OUTSIDE Frank's main process tree as a supervisor.
"""

import json
import signal
import subprocess
import sys
import time
import logging
from datetime import datetime
from pathlib import Path

# Setup logging
try:
    from config.paths import AICORE_LOG
    LOG_DIR = AICORE_LOG
except ImportError:
    LOG_DIR = Path.home() / ".local" / "share" / "frank" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "frank_watchdog.log"

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ]
)
LOG = logging.getLogger("frank.watchdog")

# ============================================================================
# Configuration
# ============================================================================

# Services to monitor with their restart policies
MONITORED_SERVICES = {
    "frank-overlay": {
        "critical": True,       # Must always run
        "restart_delay": 3,     # Seconds before restart attempt
        "max_restarts": 15,     # Max restarts before giving up
        "cooldown": 30,         # Seconds between restart attempts
        "reset_after": 600,     # Reset counter after N seconds of uptime
        "description": "Chat Overlay (Main UI)",
    },
    "aicore-core": {
        "critical": True,
        "restart_delay": 1,
        "max_restarts": 20,
        "cooldown": 15,
        "reset_after": 300,
        "description": "Core Chat Orchestrator",
    },
    "aicore-router": {
        "critical": True,
        "restart_delay": 1,
        "max_restarts": 20,
        "cooldown": 15,
        "reset_after": 300,
        "description": "Model Router",
    },
    # NOTE: LLM services (llama3-gpu, chat-llm, micro-llm) are managed
    # by llm-guard.service (LLM Manager) — do NOT monitor them here.
    "llm-guard": {
        "critical": True,
        "restart_delay": 1,
        "max_restarts": 20,
        "cooldown": 15,
        "reset_after": 300,
        "description": "LLM Manager (GPU swap + guard)",
    },
    "aicore-toolboxd": {
        "critical": True,
        "restart_delay": 1,
        "max_restarts": 20,
        "cooldown": 15,
        "reset_after": 300,
        "description": "System Toolbox",
    },
    "aura-headless": {
        "critical": True,
        "restart_delay": 2,
        "max_restarts": 10,
        "cooldown": 30,
        "reset_after": 600,
        "description": "AURA Headless Introspect",
    },
    "aura-analyzer": {
        "critical": True,
        "restart_delay": 2,
        "max_restarts": 10,
        "cooldown": 30,
        "reset_after": 600,
        "description": "AURA Pattern Analyzer",
    },
    "aicore-quantum-reflector": {
        "critical": True,
        "restart_delay": 2,
        "max_restarts": 10,
        "cooldown": 30,
        "reset_after": 600,
        "description": "Quantum Reflector (Epistemic Coherence)",
    },
    "aicore-consciousness": {
        "critical": True,
        "restart_delay": 2,
        "max_restarts": 10,
        "cooldown": 30,
        "reset_after": 600,
        "description": "Consciousness Stream Daemon",
    },
    "aicore-whisper-gpu": {
        "critical": True,
        "restart_delay": 2,
        "max_restarts": 10,
        "cooldown": 60,
        "reset_after": 600,
        "description": "Whisper STT Server (GPU)",
    },
    "aicore-webd": {
        "critical": True,
        "restart_delay": 1,
        "max_restarts": 30,
        "cooldown": 10,
        "reset_after": 300,
        "description": "Web Search Daemon (DuckDuckGo + Tor)",
    },
    "aicore-entities": {
        "critical": True,
        "restart_delay": 2,
        "max_restarts": 15,
        "cooldown": 30,
        "reset_after": 600,
        "description": "Entity Session Dispatcher",
    },
    "aicore-desktopd": {
        "critical": True,
        "restart_delay": 2,
        "max_restarts": 15,
        "cooldown": 30,
        "reset_after": 600,
        "description": "Desktop Daemon (X11)",
    },
    "aicore-genesis": {
        "critical": True,
        "restart_delay": 3,
        "max_restarts": 10,
        "cooldown": 60,
        "reset_after": 600,
        "description": "Genesis Self-Improvement System",
    },
    "aicore-dream": {
        "critical": False,          # Runs only when idle, OK to be inactive
        "restart_delay": 5,
        "max_restarts": 5,
        "cooldown": 120,
        "reset_after": 1800,
        "description": "Dream Daemon (idle consolidation)",
    },
    "aicore-invariants": {
        "critical": True,
        "restart_delay": 2,
        "max_restarts": 15,
        "cooldown": 30,
        "reset_after": 600,
        "description": "Invariants Physics Engine",
    },
}

CHECK_INTERVAL = 15  # Check every 15 seconds
OVERLAY_FREEZE_THRESHOLD = 30  # Overlay heartbeat stale after 30s → frozen
try:
    from config.paths import TEMP_FILES as _wd_temp_files
    HEALTH_FILE = _wd_temp_files["watchdog_health"]
    USER_CLOSED_SIGNAL = _wd_temp_files["user_closed"]
    GAMING_LOCK = _wd_temp_files["gaming_lock"]
    MPC_LLAMA_PARKED = _wd_temp_files["mpc_llama_parked"]
    OVERLAY_HEARTBEAT = _wd_temp_files["overlay_heartbeat"]
    OVERLAY_LOCK = _wd_temp_files["overlay_lock"]
except ImportError:
    HEALTH_FILE = Path("/tmp/frank/watchdog_health.json")
    USER_CLOSED_SIGNAL = Path("/tmp/frank/user_closed")
    GAMING_LOCK = Path("/tmp/frank/gaming_lock")
    MPC_LLAMA_PARKED = Path("/tmp/frank/mpc_llama_parked")
    OVERLAY_HEARTBEAT = Path("/tmp/frank/overlay_heartbeat")
    OVERLAY_LOCK = Path("/tmp/frank/overlay.lock")

try:
    FULL_SHUTDOWN_SIGNAL = _wd_temp_files["full_shutdown"]
except NameError:
    FULL_SHUTDOWN_SIGNAL = Path("/tmp/frank/full_shutdown")

# All services to stop on full shutdown (LLMs handled by llm-guard)
FULL_SHUTDOWN_SERVICES = [
    "aicore-consciousness",
    "aicore-entities",
    "aicore-genesis",
    "aicore-genesis-watchdog",
    "aicore-invariants",
    "aicore-quantum-reflector",
    "aicore-asrs",
    "aura-headless",
    "aura-analyzer",
    "aicore-dream",
    "aicore-gaming-mode",
    "aicore-modeld",
    "aicore-desktopd",
    "aicore-whisper-gpu",
    "aicore-ingestd",
    "aicore-webd",
    "aicore-webui",
    "aicore-toolboxd",
    "aicore-core",
    "aicore-router",
]

# ============================================================================
# State tracking
# ============================================================================

class ServiceTracker:
    """Track restart attempts and health for a single service."""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.restart_count = 0
        self.last_restart: float = 0
        self.last_seen_running: float = time.time()
        self.gave_up = False

    def should_restart(self) -> bool:
        """Check if we should attempt a restart."""
        if self.gave_up:
            # Check if enough time passed to try again
            if time.time() - self.last_restart > self.config["reset_after"] * 2:
                LOG.info(f"[{self.name}] Resetting gave_up after long wait")
                self.gave_up = False
                self.restart_count = 0
            else:
                return False

        if self.restart_count >= self.config["max_restarts"]:
            LOG.error(f"[{self.name}] Max restarts ({self.config['max_restarts']}) reached, giving up")
            self.gave_up = True
            return False

        # Cooldown check
        elapsed = time.time() - self.last_restart
        if elapsed < self.config["cooldown"]:
            return False

        return True

    def record_restart(self):
        self.restart_count += 1
        self.last_restart = time.time()

    def record_healthy(self):
        now = time.time()
        uptime = now - self.last_seen_running if self.last_seen_running else 0

        # Reset counter after sustained uptime
        if self.restart_count > 0 and uptime > self.config["reset_after"]:
            LOG.info(f"[{self.name}] Healthy for {uptime:.0f}s, resetting restart counter")
            self.restart_count = 0
            self.gave_up = False

        self.last_seen_running = now

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.config["description"],
            "restart_count": self.restart_count,
            "last_restart": datetime.fromtimestamp(self.last_restart).isoformat() if self.last_restart else None,
            "gave_up": self.gave_up,
            "critical": self.config["critical"],
        }


# ============================================================================
# Service management functions
# ============================================================================

def get_service_state(service_name: str) -> str:
    """Get systemd user service state: 'active', 'inactive', 'failed', 'activating', or 'unknown'."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", service_name],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip() or "unknown"
    except Exception as e:
        LOG.warning(f"Failed to check {service_name}: {e}")
        return "unknown"


def is_service_active(service_name: str) -> bool:
    """Check if a systemd user service is active."""
    return get_service_state(service_name) == "active"


def restart_service(service_name: str) -> bool:
    """Restart a systemd user service."""
    try:
        # First try normal restart
        result = subprocess.run(
            ["systemctl", "--user", "restart", service_name],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return True

        # If restart failed, try reset-failed first
        LOG.warning(f"Restart failed for {service_name}, trying reset-failed...")
        subprocess.run(
            ["systemctl", "--user", "reset-failed", service_name],
            capture_output=True, text=True, timeout=10
        )
        time.sleep(1)

        # Retry
        result = subprocess.run(
            ["systemctl", "--user", "restart", service_name],
            capture_output=True, text=True, timeout=30
        )
        return result.returncode == 0

    except Exception as e:
        LOG.error(f"Failed to restart {service_name}: {e}")
        return False


def write_health(trackers: dict, overall_healthy: bool):
    """Write health status to JSON file for other services to read."""
    try:
        status = {
            "timestamp": datetime.now().isoformat(),
            "overall_healthy": overall_healthy,
            "services": {name: t.to_dict() for name, t in trackers.items()},
        }
        tmp = HEALTH_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(status, indent=2))
        tmp.rename(HEALTH_FILE)
    except Exception:
        pass


# ============================================================================
# Self-restart API (callable from Frank's tools)
# ============================================================================

try:
    from config.paths import TEMP_FILES as _wd_temp_files2
    RESTART_REQUEST_FILE = _wd_temp_files2["restart_request"]
except ImportError:
    RESTART_REQUEST_FILE = Path("/tmp/frank/restart_request.json")


def check_restart_requests(trackers: dict):
    """
    Check if Frank (or ASRS) has requested a service restart.
    This allows Frank to restart himself without approval queue.
    """
    if not RESTART_REQUEST_FILE.exists():
        return

    try:
        data = json.loads(RESTART_REQUEST_FILE.read_text())
        RESTART_REQUEST_FILE.unlink(missing_ok=True)

        service = data.get("service")
        reason = data.get("reason", "self-restart request")
        requested_at = data.get("timestamp", "?")

        if not service:
            return

        LOG.info(f"Self-restart request for '{service}': {reason} (requested at {requested_at})")

        # Clear user-closed signal — Frank explicitly requested restart
        if service in ("frank-overlay", "all"):
            try:
                USER_CLOSED_SIGNAL.unlink(missing_ok=True)
                LOG.info("Cleared user-close signal for self-restart")
            except Exception:
                pass

        if service == "all":
            # Restart all monitored services
            for name in trackers:
                LOG.info(f"Restarting {name} (full self-restart)...")
                restart_service(name)
                time.sleep(2)
        elif service in trackers:
            restart_service(service)
        else:
            # Try anyway even if not in monitored list
            restart_service(service)

    except Exception as e:
        LOG.error(f"Error processing restart request: {e}")


# ============================================================================
# Main loop
# ============================================================================

running = True


def signal_handler(signum, frame):
    global running
    LOG.info(f"Received signal {signum}, stopping watchdog...")
    running = False


def main():
    global running

    LOG.info("=" * 60)
    LOG.info("Frank Universal Service Watchdog starting...")
    LOG.info(f"Monitoring {len(MONITORED_SERVICES)} services")
    LOG.info("=" * 60)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Initialize trackers
    trackers = {
        name: ServiceTracker(name, config)
        for name, config in MONITORED_SERVICES.items()
    }

    _shutdown_active = False  # True while in full shutdown state

    while running:
        try:
            # ── Full shutdown check ──────────────────────────────
            if FULL_SHUTDOWN_SIGNAL.exists() and not _shutdown_active:
                _shutdown_active = True
                LOG.info("=" * 60)
                LOG.info("FULL SHUTDOWN — stopping all Frank services")
                LOG.info("=" * 60)
                for svc in FULL_SHUTDOWN_SERVICES:
                    if is_service_active(svc):
                        LOG.info(f"  Stopping {svc}...")
                        try:
                            subprocess.run(
                                ["systemctl", "--user", "stop", svc],
                                capture_output=True, timeout=15,
                            )
                        except Exception:
                            pass
                LOG.info("All services stopped. Watchdog paused until restart.")

            # While in shutdown state, skip all monitoring
            if _shutdown_active:
                # Check if shutdown signal was cleared (Frank restarting)
                if not USER_CLOSED_SIGNAL.exists():
                    LOG.info("Shutdown cleared — resuming watchdog")
                    _shutdown_active = False
                    # Reset all trackers
                    for t in trackers.values():
                        t.restart_count = 0
                        t.gave_up = False
                else:
                    time.sleep(5)
                    continue

            overall_healthy = True

            for name, tracker in trackers.items():
                state = get_service_state(name)

                if state == "active":
                    tracker.record_healthy()
                    continue

                # Non-critical services: only restart on "failed", not "inactive"
                # (e.g. dream daemon is legitimately inactive until idle trigger)
                if not tracker.config["critical"] and state == "inactive":
                    continue

                overall_healthy = False

                # Skip auto-restart of frank-overlay if user closed it intentionally
                if name == "frank-overlay" and USER_CLOSED_SIGNAL.exists():
                    LOG.debug(f"[{name}] User closed overlay intentionally, skipping restart")
                    continue

                # Skip auto-restart of frank-overlay during gaming mode
                if name == "frank-overlay" and GAMING_LOCK.exists():
                    LOG.debug(f"[{name}] Gaming mode active (lock file), skipping restart")
                    continue

                # Skip Llama restart when Router intentionally parked it for Qwen (MPC)
                if name == "aicore-llama3-gpu" and MPC_LLAMA_PARKED.exists():
                    LOG.debug(f"[{name}] Parked by MPC (Qwen active), skipping restart")
                    continue

                LOG.warning(f"[{name}] {state.upper()} ({tracker.config['description']})")

                if tracker.should_restart():
                    time.sleep(tracker.config["restart_delay"])
                    LOG.info(f"[{name}] Attempting restart (attempt {tracker.restart_count + 1}/{tracker.config['max_restarts']})...")

                    if restart_service(name):
                        tracker.record_restart()
                        time.sleep(3)  # Wait for startup

                        if is_service_active(name):
                            LOG.info(f"[{name}] Successfully restarted!")
                            tracker.restart_count = 0  # Reset on success
                        else:
                            LOG.error(f"[{name}] Restart command succeeded but service not active")
                            tracker.record_restart()
                    else:
                        LOG.error(f"[{name}] Restart FAILED")
                        tracker.record_restart()

            # ── Overlay freeze detection (heartbeat-based) ──
            # The overlay writes a timestamp every 5s.  If the file is
            # stale (>30s) but the systemd service is still "active",
            # the Tk main loop is frozen.  Force-restart the overlay.
            if "frank-overlay" in trackers and is_service_active("frank-overlay"):
                if not USER_CLOSED_SIGNAL.exists() and not GAMING_LOCK.exists():
                    try:
                        if OVERLAY_HEARTBEAT.exists():
                            last_ts = float(OVERLAY_HEARTBEAT.read_text().strip())
                            age = time.time() - last_ts
                            if age > OVERLAY_FREEZE_THRESHOLD:
                                LOG.warning(
                                    f"[frank-overlay] FREEZE DETECTED — heartbeat "
                                    f"stale for {age:.0f}s, force-restarting overlay"
                                )
                                # Kill the frozen process tree first
                                subprocess.run(
                                    ["systemctl", "--user", "kill", "--signal=SIGKILL",
                                     "frank-overlay"],
                                    capture_output=True, timeout=5,
                                )
                                time.sleep(2)
                                # Remove stale lock + heartbeat so restart succeeds
                                OVERLAY_LOCK.unlink(missing_ok=True)
                                OVERLAY_HEARTBEAT.unlink(missing_ok=True)
                                restart_service("frank-overlay")
                                trackers["frank-overlay"].record_restart()
                    except (ValueError, OSError) as e:
                        LOG.debug(f"Heartbeat read error: {e}")

            # Check for self-restart requests from Frank
            check_restart_requests(trackers)

            # Write health status
            write_health(trackers, overall_healthy)

            # Sleep with interrupt check
            for _ in range(CHECK_INTERVAL):
                if not running:
                    break
                time.sleep(1)

        except Exception as e:
            LOG.error(f"Watchdog error: {e}")
            time.sleep(10)

    LOG.info("Frank Universal Service Watchdog stopped")


if __name__ == "__main__":
    main()
