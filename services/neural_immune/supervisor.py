"""
Neural Immune System — Supervisor
===================================
Main supervision loop: collects health → predicts failures → acts → logs.
Replaces frank_watchdog.py, frank_sentinel.py, and dream watchdogs.

Tick cycle (every 15s):
  1. Collect health metrics for all services
  2. BaselineNet: detect system-wide anomaly
  3. AnomalyNet: per-service failure prediction
  4. Circuit breaker + RestartNet: smart restart decisions
  5. Log snapshot for future training

Special cases preserved from frank_watchdog.py:
  - Overlay freeze detection (heartbeat stale)
  - User-closed / gaming-lock skip for overlay
  - MPC llama parked skip
  - Non-critical services: only restart on "failed" not "inactive"
  - Restart request file protocol
"""

import json
import logging
import math
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional

from .collector import HealthCollector, SERVICE_REGISTRY, get_service_state
from .circuit_breaker import CircuitBreaker, CircuitState
from .db import ImmuneDB
from .lifecycle import LifecycleManager
from .models import ImmuneModels
from .training import ImmuneTrainer

LOG = logging.getLogger("immune.supervisor")

# Clean environment for subprocess calls — strip NOTIFY_SOCKET
_CLEAN_ENV = {k: v for k, v in os.environ.items() if k != "NOTIFY_SOCKET"}

# Timing
CHECK_INTERVAL = 15           # seconds between ticks
OVERLAY_FREEZE_THRESHOLD = 30 # seconds before heartbeat considered stale

# File paths (resolved at init, with fallbacks)
_TEMP_DIR = Path("/tmp/frank")
try:
    from config.paths import TEMP_FILES, TEMP_DIR as _CFG_TEMP
    _TEMP_DIR = _CFG_TEMP
except ImportError:
    TEMP_FILES = {}

def _get_temp(name: str) -> Path:
    return TEMP_FILES.get(name, _TEMP_DIR / f"{name}")


class ImmuneSystem:
    """Neural Immune System — self-learning service supervisor."""

    def __init__(self, db_path: Optional[Path] = None,
                 model_path: Optional[Path] = None):
        # Core components
        self.db = ImmuneDB(db_path)
        self.models = ImmuneModels(model_path)
        self.collector = HealthCollector()
        self.lifecycle = LifecycleManager(self.db)
        self.trainer = ImmuneTrainer(self.models, self.db)

        # Circuit breakers (one per service)
        self.breakers: Dict[str, CircuitBreaker] = {}
        for name, info in SERVICE_REGISTRY.items():
            self.breakers[name] = CircuitBreaker(
                name, self.db, base_delay=info.get("delay", 3.0)
            )

        # State
        self._running = True
        self._shutdown_active = False
        self._restart_counts: Dict[str, int] = {}

        # Signal paths
        self._user_closed = _get_temp("user_closed")
        self._gaming_lock = _get_temp("gaming_lock")
        self._full_shutdown = _get_temp("full_shutdown")
        self._mpc_parked = _get_temp("mpc_llama_parked")
        self._overlay_heartbeat = _get_temp("overlay_heartbeat")
        self._overlay_lock = _get_temp("overlay_lock")
        self._health_file = _get_temp("watchdog_health")
        self._restart_request = _get_temp("restart_request")

        LOG.info("Neural Immune System initialized (%d services, %d params)",
                 len(SERVICE_REGISTRY), self.models.total_params())

    def stop(self):
        self._running = False

    # ── Main Loop ─────────────────────────────────────────────────

    def run(self):
        """Main supervisor loop."""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        LOG.info("=" * 60)
        LOG.info("Neural Immune System starting (%d services)", len(SERVICE_REGISTRY))
        LOG.info("=" * 60)

        while self._running:
            try:
                self._tick()
            except Exception as e:
                LOG.error("Tick error: %s", e, exc_info=True)
                time.sleep(5)

            # Interruptible sleep
            for _ in range(CHECK_INTERVAL):
                if not self._running:
                    break
                time.sleep(1)

        LOG.info("Neural Immune System stopped")
        self.db.close()

    def _signal_handler(self, signum, frame):
        LOG.info("Signal %d, stopping immune system", signum)
        self._running = False

    # ── Tick ──────────────────────────────────────────────────────

    def _tick(self):
        """One supervision cycle."""

        # ── Full shutdown check ──
        if self._full_shutdown.exists() and not self._shutdown_active:
            self._handle_full_shutdown()
            return

        if self._shutdown_active:
            if not self._user_closed.exists():
                LOG.info("Shutdown cleared — resuming monitoring")
                self._shutdown_active = False
                for b in self.breakers.values():
                    b.reset()
            return

        # ── Collect health metrics ──
        snapshot = self.collector.collect_all()

        # ── BaselineNet: system-wide anomaly ──
        baseline_vec = self.collector.get_baseline_vector()
        baseline_mse = self.models.baseline_anomaly(baseline_vec)
        is_healthy = baseline_mse < 0.5  # Normalized threshold

        if baseline_mse > 0.7:
            LOG.warning("System-wide anomaly detected (score=%.2f)", baseline_mse)

        # ── Per-service monitoring ──
        overall_healthy = True

        for name, info in SERVICE_REGISTRY.items():
            state = get_service_state(name)
            breaker = self.breakers[name]

            if state == "active":
                breaker.record_success()
                self.collector.update_restart_count(name, self._restart_counts.get(name, 0))
                continue

            # ── Skip conditions (preserved from frank_watchdog.py) ──

            # Non-critical + inactive = expected (e.g. dream daemon)
            if not info.get("critical", True) and state == "inactive":
                continue

            # Overlay: skip if user closed or gaming
            if name == "frank-overlay":
                if self._user_closed.exists() or self._gaming_lock.exists():
                    continue

            # LLM: skip if parked by MPC
            if name == "aicore-llama3-gpu" and self._mpc_parked.exists():
                continue

            overall_healthy = False
            breaker.record_failure()

            # ── AnomalyNet: per-service failure prediction ──
            window = self.collector.get_window(name)
            anomaly_score = self.models.predict_failure(window)

            # ── RestartNet: should we restart? ──
            if breaker.allows_restart():
                # Build restart features
                hour = time.localtime().tm_hour + time.localtime().tm_min / 60.0
                n_down = sum(1 for n, i in SERVICE_REGISTRY.items()
                             if get_service_state(n) != "active" and i.get("critical"))
                system_metrics = self.collector.get_system_metrics_cached()

                restart_features = {
                    "service_tier": info.get("tier", 2) / 4.0,
                    "restart_count_recent": min(self._restart_counts.get(name, 0) / 20.0, 1.0),
                    "uptime_before_crash": 0.5,
                    "time_since_last_restart": min(breaker.time_in_state / 300.0, 1.0),
                    "hour_sin": math.sin(2 * math.pi * hour / 24.0),
                    "hour_cos": math.cos(2 * math.pi * hour / 24.0),
                    "dependency_health": self.collector._calc_dependency_health(info.get("tier", 0)),
                    "is_critical": 1.0 if info.get("critical") else 0.0,
                    "historical_mttr": info.get("delay", 3.0) / 30.0,
                    "historical_success_rate": 0.5,
                    "n_concurrent_failures": min(n_down / 10.0, 1.0),
                    "circuit_breaker_state": 0.0 if breaker.is_closed else 0.5,
                    "anomaly_score": anomaly_score,
                    "baseline_mse": baseline_mse,
                    "cpu_system": system_metrics.get("cpu_system", 50.0) / 100.0,
                    "ram_system_pct": system_metrics.get("ram_system_pct", 50.0) / 100.0,
                    "user_active": 1.0 if self.collector.is_user_active() else 0.0,
                    "recent_restart_failures": 0.0,
                }

                policy = self.models.restart_policy(
                    restart_features, default_delay=info.get("delay", 3.0)
                )

                should_restart = policy["should_restart"] > 0.5
                max_restarts = info.get("max_restarts", 20)

                if should_restart and self._restart_counts.get(name, 0) < max_restarts:
                    delay = breaker.get_recommended_delay(policy["delay"])
                    self._do_restart(name, delay, anomaly_score, breaker)
                else:
                    LOG.debug("[%s] RestartNet says skip (p=%.2f, count=%d/%d)",
                              name, policy["should_restart"],
                              self._restart_counts.get(name, 0), max_restarts)

        # ── Overlay freeze detection ──
        self._check_overlay_freeze()

        # ── Restart requests ──
        self._check_restart_requests()

        # ── Log snapshot ──
        self.db.log_snapshot(snapshot, is_healthy=overall_healthy, anomaly_score=baseline_mse)

        # ── Write health file (compatible with frank_watchdog.py format) ──
        self._write_health(overall_healthy)

    # ── Restart Execution ─────────────────────────────────────────

    def _do_restart(self, service: str, delay: float,
                    anomaly_score: float, breaker: CircuitBreaker):
        """Execute a restart with logging."""
        count = self._restart_counts.get(service, 0) + 1
        self._restart_counts[service] = count

        LOG.info("[%s] Restarting (attempt %d, delay=%.1fs, anomaly=%.2f, breaker=%s)",
                 service, count, delay, anomaly_score, breaker.state)

        # Log pre-restart window
        pre_window = json.dumps(self.collector.get_window(service))

        time.sleep(delay)
        success = self.lifecycle.restart_service(service)

        if success:
            time.sleep(3)
            if self.lifecycle.is_active(service):
                LOG.info("[%s] Restart successful!", service)
                self._restart_counts[service] = 0
                breaker.record_success()
            else:
                LOG.error("[%s] Restart command OK but service not active", service)
                success = False
        else:
            LOG.error("[%s] Restart FAILED", service)

        # Log incident
        self.db.log_incident(
            service=service,
            event_type="restart",
            details=f"attempt={count}, anomaly={anomaly_score:.3f}",
            pre_window=pre_window,
            restart_delay=delay,
            restart_success=success,
            cascade_triggered=False,
            circuit_state=breaker.state,
        )

        self.collector.update_restart_count(service, self._restart_counts.get(service, 0))

    # ── Overlay Freeze Detection ──────────────────────────────────

    def _check_overlay_freeze(self):
        """Detect frozen overlay via stale heartbeat (from frank_watchdog.py)."""
        if self._user_closed.exists() or self._gaming_lock.exists():
            return
        if not self.lifecycle.is_active("frank-overlay"):
            return

        try:
            if self._overlay_heartbeat.exists():
                last_ts = float(self._overlay_heartbeat.read_text().strip())
                age = time.time() - last_ts
                if age > OVERLAY_FREEZE_THRESHOLD:
                    LOG.warning("[frank-overlay] FREEZE — heartbeat stale %.0fs, force-restarting", age)
                    subprocess.run(
                        ["systemctl", "--user", "kill", "--signal=SIGKILL", "frank-overlay"],
                        capture_output=True, timeout=5, env=_CLEAN_ENV,
                    )
                    time.sleep(2)
                    self._overlay_lock.unlink(missing_ok=True)
                    self._overlay_heartbeat.unlink(missing_ok=True)
                    self.lifecycle.restart_service("frank-overlay")
                    self._restart_counts["frank-overlay"] = self._restart_counts.get("frank-overlay", 0) + 1
                    self.db.log_incident("frank-overlay", "freeze", "heartbeat stale")
        except (ValueError, OSError, UnicodeDecodeError) as e:
            LOG.debug("Heartbeat read error: %s", e)

    # ── Restart Requests ──────────────────────────────────────────

    def _check_restart_requests(self):
        """Process restart requests from Frank (restart_request.json protocol)."""
        if not self._restart_request.exists():
            return

        try:
            data = json.loads(self._restart_request.read_text())
            self._restart_request.unlink(missing_ok=True)

            service = data.get("service")
            reason = data.get("reason", "self-restart request")

            if not service:
                return

            LOG.info("Restart request for '%s': %s", service, reason)

            # Clear user-closed signal for overlay restarts
            if service in ("frank-overlay", "all"):
                self._user_closed.unlink(missing_ok=True)

            if service == "all":
                for name in SERVICE_REGISTRY:
                    self.lifecycle.restart_service(name)
                    time.sleep(1)
            else:
                self.lifecycle.restart_service(service)

        except Exception as e:
            LOG.error("Restart request error: %s", e)

    # ── Full Shutdown ─────────────────────────────────────────────

    def _handle_full_shutdown(self):
        self._shutdown_active = True
        LOG.info("=" * 50)
        LOG.info("FULL SHUTDOWN — stopping all services")
        LOG.info("=" * 50)
        self.lifecycle.full_shutdown()
        LOG.info("All services stopped. Monitoring paused until restart.")

    # ── Health File Output ────────────────────────────────────────

    def _write_health(self, overall_healthy: bool):
        """Write health status JSON (compatible with watchdog_health.json format)."""
        try:
            from datetime import datetime
            status = {
                "timestamp": datetime.now().isoformat(),
                "overall_healthy": overall_healthy,
                "immune_system": True,
                "services": {},
            }
            for name in SERVICE_REGISTRY:
                breaker = self.breakers.get(name)
                status["services"][name] = {
                    "name": name,
                    "restart_count": self._restart_counts.get(name, 0),
                    "gave_up": False,
                    "critical": SERVICE_REGISTRY[name].get("critical", True),
                    "circuit_breaker": breaker.state if breaker else "unknown",
                }
            tmp = self._health_file.with_suffix(".tmp")
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(status, indent=2))
            tmp.rename(self._health_file)
        except Exception:
            pass

    # ── Training Hook ─────────────────────────────────────────────

    def train_cycle(self):
        """Trigger training on accumulated data (called from dream daemon)."""
        self.trainer.train_cycle()
        self.db.prune_old_data(max_age_days=30)
