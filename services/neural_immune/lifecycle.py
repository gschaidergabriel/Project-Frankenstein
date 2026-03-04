"""
Neural Immune System — Lifecycle Manager
==========================================
Handles startup, shutdown, and restart wave orchestration.
Reuses the dependency-ordered wave pattern from command_router_mixin.py.

Waves:
  0: Infrastructure (standalone services, LLMs)
  1: Router
  2: Core
  3: Daemons (depend on core+router)
  4: Overlay + watchdog (last)
"""

import logging
import os
import subprocess
import time
from typing import Callable, Dict, List, Optional, Tuple

from .db import ImmuneDB

# Clean environment for subprocess calls — strip NOTIFY_SOCKET
_CLEAN_ENV = {k: v for k, v in os.environ.items() if k != "NOTIFY_SOCKET"}

LOG = logging.getLogger("immune.lifecycle")


# Dependency-ordered restart waves (from command_router_mixin.py)
RESTART_WAVES = [
    # Wave 0 — standalone services (all parallel)
    [
        "aicore-llama3-gpu", "aicore-micro-llm", "aicore-whisper-gpu",
        "aicore-modeld", "aicore-toolboxd", "aicore-webd",
        "aicore-desktopd", "aicore-ingestd", "aicore-webui",
        "aicore-quantum-reflector", "aura-headless",
        "frank-sentinel",
    ],
    # Wave 1 — router
    ["aicore-router"],
    # Wave 2 — core (requires router)
    ["aicore-core"],
    # Wave 3 — daemons depending on core+router (all parallel)
    [
        "aicore-consciousness", "aicore-entities", "aicore-asrs",
        "aicore-gaming-mode", "aicore-genesis", "aicore-genesis-watchdog",
        "aicore-invariants", "aicore-dream", "aura-analyzer",
        "aicore-therapist", "aicore-mirror", "aicore-atlas", "aicore-muse",
    ],
    # Wave 4 — overlay (last)
    ["frank-overlay"],
]

WAVE_LABELS = ["Infrastructure", "Router", "Core", "Daemons", "Overlay"]

# Timeouts per wave
WAVE_TIMEOUTS = {
    0: 60,   # LLM services need time to load models
    1: 15,
    2: 15,
    3: 30,
    4: 15,
}

# All services to stop on full shutdown (superset of RESTART_WAVES)
FULL_SHUTDOWN_SERVICES = [
    "aicore-consciousness", "aicore-entities", "aicore-genesis",
    "aicore-genesis-watchdog", "aicore-invariants",
    "aicore-quantum-reflector", "aicore-asrs",
    "aura-headless", "aura-analyzer", "aicore-dream",
    "aicore-gaming-mode", "aicore-modeld", "aicore-desktopd",
    "aicore-whisper-gpu", "aicore-ingestd", "aicore-webd",
    "aicore-webui", "aicore-toolboxd", "aicore-micro-llm",
    "aicore-core", "aicore-router",
    "aicore-therapist", "aicore-mirror", "aicore-atlas", "aicore-muse",
    "aicore-llama3-gpu", "frank-overlay", "frank-sentinel",
]


def _is_active(service: str) -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", service],
            capture_output=True, text=True, timeout=10, env=_CLEAN_ENV,
        )
        return r.stdout.strip() == "active"
    except Exception:
        return False


def _start_service(service: str) -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "start", service],
            capture_output=True, text=True, timeout=30, env=_CLEAN_ENV,
        )
        return r.returncode == 0
    except Exception as e:
        LOG.error("Failed to start %s: %s", service, e)
        return False


def _stop_service(service: str) -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "stop", service],
            capture_output=True, text=True, timeout=15, env=_CLEAN_ENV,
        )
        return r.returncode == 0
    except Exception as e:
        LOG.error("Failed to stop %s: %s", service, e)
        return False


def _restart_service(service: str) -> bool:
    """Restart with reset-failed fallback (from frank_watchdog.py pattern)."""
    try:
        r = subprocess.run(
            ["systemctl", "--user", "restart", service],
            capture_output=True, text=True, timeout=30, env=_CLEAN_ENV,
        )
        if r.returncode == 0:
            return True

        # Reset-failed + retry
        subprocess.run(
            ["systemctl", "--user", "reset-failed", service],
            capture_output=True, text=True, timeout=10, env=_CLEAN_ENV,
        )
        time.sleep(1)
        r = subprocess.run(
            ["systemctl", "--user", "restart", service],
            capture_output=True, text=True, timeout=30, env=_CLEAN_ENV,
        )
        return r.returncode == 0
    except Exception as e:
        LOG.error("Failed to restart %s: %s", service, e)
        return False


class LifecycleManager:
    """Manages startup, shutdown, and restart waves."""

    def __init__(self, db: ImmuneDB):
        self._db = db

    def startup_wave(self, wave_idx: int,
                     on_progress: Optional[Callable] = None) -> bool:
        """Start a single wave. Returns True if all services came up."""
        if wave_idx >= len(RESTART_WAVES):
            return True

        services = RESTART_WAVES[wave_idx]
        timeout = WAVE_TIMEOUTS.get(wave_idx, 30)
        label = WAVE_LABELS[wave_idx] if wave_idx < len(WAVE_LABELS) else f"Wave {wave_idx}"
        t0 = time.monotonic()

        LOG.info("Starting wave %d (%s): %s", wave_idx, label, ", ".join(services))
        if on_progress:
            on_progress(wave_idx, label, "starting")

        # Start all services in this wave
        for svc in services:
            if not _is_active(svc):
                _start_service(svc)

        # Wait for health with timeout
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            all_up = all(_is_active(svc) for svc in services)
            if all_up:
                break
            time.sleep(1)

        duration = time.monotonic() - t0
        success = all(_is_active(svc) for svc in services)

        failed = [s for s in services if not _is_active(s)]
        if failed:
            LOG.warning("Wave %d: %d/%d failed: %s",
                        wave_idx, len(failed), len(services), ", ".join(failed))

        self._db.log_lifecycle("startup", wave_idx, services, success, duration)

        if on_progress:
            on_progress(wave_idx, label, "done" if success else "partial")

        return success

    def full_startup(self, on_progress: Optional[Callable] = None) -> bool:
        """Start all services in wave order."""
        LOG.info("=" * 50)
        LOG.info("FULL STARTUP — bringing up all services")
        LOG.info("=" * 50)

        all_ok = True
        for wave_idx in range(len(RESTART_WAVES)):
            ok = self.startup_wave(wave_idx, on_progress)
            if not ok:
                all_ok = False
                # Continue anyway — partial startup is better than none

        LOG.info("Startup complete (all_ok=%s)", all_ok)
        return all_ok

    def full_shutdown(self, on_progress: Optional[Callable] = None) -> bool:
        """Stop all services in reverse wave order."""
        LOG.info("=" * 50)
        LOG.info("FULL SHUTDOWN — stopping all services")
        LOG.info("=" * 50)

        t0 = time.monotonic()

        # Stop in reverse wave order
        for wave_idx in reversed(range(len(RESTART_WAVES))):
            services = RESTART_WAVES[wave_idx]
            label = WAVE_LABELS[wave_idx] if wave_idx < len(WAVE_LABELS) else f"Wave {wave_idx}"

            LOG.info("Stopping wave %d (%s)", wave_idx, label)
            if on_progress:
                on_progress(wave_idx, label, "stopping")

            for svc in services:
                if _is_active(svc):
                    _stop_service(svc)

            # Brief wait between waves
            time.sleep(1)

        # Final sweep: stop anything still running
        for svc in FULL_SHUTDOWN_SERVICES:
            if _is_active(svc):
                LOG.warning("Forcing stop: %s", svc)
                _stop_service(svc)

        # Check actual success — are all services stopped?
        still_running = [s for s in FULL_SHUTDOWN_SERVICES if _is_active(s)]
        success = len(still_running) == 0
        if still_running:
            LOG.error("Shutdown incomplete — still running: %s", ", ".join(still_running))

        duration = time.monotonic() - t0
        self._db.log_lifecycle("shutdown", -1, FULL_SHUTDOWN_SERVICES, success, duration)

        LOG.info("Shutdown complete in %.1fs (success=%s)", duration, success)
        return success

    def restart_wave(self, wave_idx: int) -> bool:
        """Restart a single wave (stop then start)."""
        if wave_idx >= len(RESTART_WAVES):
            return True

        services = RESTART_WAVES[wave_idx]
        label = WAVE_LABELS[wave_idx] if wave_idx < len(WAVE_LABELS) else f"Wave {wave_idx}"
        t0 = time.monotonic()

        LOG.info("Restarting wave %d (%s)", wave_idx, label)

        results = []
        for svc in services:
            ok = _restart_service(svc)
            results.append(ok)
            if not ok:
                LOG.error("Failed to restart %s in wave %d", svc, wave_idx)

        duration = time.monotonic() - t0
        success = all(results)
        self._db.log_lifecycle("restart_wave", wave_idx, services, success, duration)
        return success

    def restart_service(self, service: str) -> bool:
        """Restart a single service."""
        return _restart_service(service)

    def is_active(self, service: str) -> bool:
        """Check if a service is active."""
        return _is_active(service)
