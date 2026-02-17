#!/usr/bin/env python3
"""
A.S.R.S. System Watchdog
Monitors system health after feature integration.
"""

import os
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Deque
import logging
import json

from .config import ASRSConfig, get_asrs_config
from .baseline import Baseline, SystemMetrics, BaselineManager

LOG = logging.getLogger("asrs.watchdog")


@dataclass
class MetricSample:
    """Single metric sample."""
    timestamp: float
    memory_mb: float
    memory_percent: float
    cpu_percent: float
    error_count: int
    crashed_services: List[str]
    response_times: Dict[str, float]
    cpu_temp_c: Optional[float] = None
    disk_usage: Optional[Dict[str, float]] = None
    io_pressure_avg10: Optional[float] = None
    swap_percent: Optional[float] = None


class SystemWatchdog:
    """
    Monitors system health after feature integration.
    Detects anomalies and triggers callbacks when issues are found.
    """

    def __init__(self, config: ASRSConfig = None):
        self.config = config or get_asrs_config()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._baseline: Optional[Baseline] = None
        self._samples: Deque[MetricSample] = deque(maxlen=self.config.metrics_history_size)
        self._observation_start: float = 0
        self._on_anomaly: Optional[Callable] = None
        self._on_observation_complete: Optional[Callable] = None
        self._last_service_states: Dict[str, str] = {}
        self._cpu_spike_start: float = 0

    def start_observation(self, baseline: Baseline,
                          on_anomaly: Callable = None,
                          on_complete: Callable = None):
        """
        Start observing system after integration.

        Args:
            baseline: The baseline to compare against
            on_anomaly: Callback(anomalies) when anomalies detected
            on_complete: Callback() when observation window completes successfully
        """
        if self._running:
            LOG.warning("Watchdog already running, stopping previous observation")
            self.stop_observation()

        self._baseline = baseline
        self._on_anomaly = on_anomaly
        self._on_observation_complete = on_complete
        self._samples.clear()
        self._observation_start = time.time()
        self._last_service_states = baseline.baseline_metrics.service_states.copy() if baseline.baseline_metrics else {}
        self._cpu_spike_start = 0

        self._running = True
        self._thread = threading.Thread(target=self._observation_loop, daemon=True)
        self._thread.start()

        LOG.info(f"Started observation for baseline {baseline.id}, "
                 f"window: {self.config.observation_window_sec}s")

    def stop_observation(self):
        """Stop the observation."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._baseline = None
        LOG.info("Observation stopped")

    def is_observing(self) -> bool:
        """Check if currently observing."""
        return self._running

    def get_current_metrics(self) -> Optional[MetricSample]:
        """Get most recent metrics sample."""
        if self._samples:
            return self._samples[-1]
        return None

    def get_metrics_history(self) -> List[MetricSample]:
        """Get all collected metrics."""
        return list(self._samples)

    def _observation_loop(self):
        """Main observation loop."""
        LOG.debug("Observation loop started")

        while self._running:
            elapsed = time.time() - self._observation_start

            # Check if observation window complete
            if elapsed >= self.config.observation_window_sec:
                LOG.info("Observation window complete, no critical anomalies detected")
                if self._on_observation_complete:
                    try:
                        self._on_observation_complete()
                    except Exception as e:
                        LOG.error(f"Error in observation complete callback: {e}")
                self._running = False
                break

            # Collect sample
            sample = self._collect_sample()
            self._samples.append(sample)

            # Check for anomalies
            anomalies = self._check_for_anomalies(sample)

            if anomalies:
                # Check severity
                critical = [a for a in anomalies if a.get("severity") == "critical"]

                if critical:
                    LOG.warning(f"Critical anomalies detected: {critical}")
                    if self._on_anomaly:
                        try:
                            self._on_anomaly(anomalies)
                        except Exception as e:
                            LOG.error(f"Error in anomaly callback: {e}")
                    # Don't stop immediately for critical - let callback handle it
                else:
                    LOG.info(f"Warning anomalies: {anomalies}")

            # Sleep until next check
            time.sleep(self.config.check_interval_sec)

        LOG.debug("Observation loop ended")

    def _collect_sample(self) -> MetricSample:
        """Collect current system metrics."""
        # Memory
        memory_mb = 0.0
        memory_percent = 0.0
        try:
            with open('/proc/meminfo') as f:
                meminfo = {}
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        meminfo[parts[0].rstrip(':')] = int(parts[1])
                total = meminfo.get('MemTotal', 1)
                available = meminfo.get('MemAvailable', 0)
                used = total - available
                memory_mb = used / 1024
                memory_percent = (used / total) * 100
        except Exception:
            pass

        # CPU
        cpu_percent = 0.0
        try:
            with open('/proc/loadavg') as f:
                parts = f.read().split()
                load = float(parts[0])
                cpu_count = os.cpu_count() or 1
                cpu_percent = (load / cpu_count) * 100
        except Exception:
            pass

        # Error count
        error_count = self._count_recent_errors()

        # Crashed services
        crashed_services = self._check_crashed_services()

        # Response times
        response_times = self._measure_response_times()

        # CPU temperature from /sys/class/thermal
        cpu_temp_c = None
        try:
            tz_path = Path("/sys/class/thermal")
            if tz_path.exists():
                max_temp = None
                for zone in sorted(tz_path.glob("thermal_zone*")):
                    temp_file = zone / "temp"
                    if temp_file.exists():
                        temp_m = int(temp_file.read_text().strip())
                        t_c = temp_m / 1000.0
                        if max_temp is None or t_c > max_temp:
                            max_temp = t_c
                cpu_temp_c = max_temp
        except Exception:
            pass

        # Disk usage per mount
        disk_usage = {}
        try:
            try:
                from config.paths import AICORE_ROOT as _wd_root
                _wd_mount = str(_wd_root.parent.parent)
            except ImportError:
                _wd_mount = str(Path(__file__).resolve().parents[3])
            for mount_path in ["/", str(Path.home()), _wd_mount]:
                mp = Path(mount_path)
                if mp.exists():
                    st = os.statvfs(str(mp))
                    total = st.f_blocks * st.f_frsize
                    free = st.f_bavail * st.f_frsize
                    if total > 0:
                        disk_usage[mount_path] = round(((total - free) / total) * 100, 1)
        except Exception:
            pass

        # I/O pressure from /proc/pressure/io
        io_pressure_avg10 = None
        try:
            psi_io = Path("/proc/pressure/io")
            if psi_io.exists():
                for line in psi_io.read_text().splitlines():
                    if line.startswith("some"):
                        for part in line.split():
                            if part.startswith("avg10="):
                                io_pressure_avg10 = float(part.split("=", 1)[1])
                                break
                        break
        except Exception:
            pass

        # Swap percent from /proc/meminfo
        swap_percent = None
        try:
            with open('/proc/meminfo') as f:
                swap_info = {}
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2 and parts[0].rstrip(':') in ('SwapTotal', 'SwapFree'):
                        swap_info[parts[0].rstrip(':')] = int(parts[1])
                s_total = swap_info.get('SwapTotal', 0)
                s_free = swap_info.get('SwapFree', 0)
                if s_total > 0:
                    swap_percent = round(((s_total - s_free) / s_total) * 100, 1)
        except Exception:
            pass

        return MetricSample(
            timestamp=time.time(),
            memory_mb=memory_mb,
            memory_percent=memory_percent,
            cpu_percent=cpu_percent,
            error_count=error_count,
            crashed_services=crashed_services,
            response_times=response_times,
            cpu_temp_c=cpu_temp_c,
            disk_usage=disk_usage if disk_usage else None,
            io_pressure_avg10=io_pressure_avg10,
            swap_percent=swap_percent,
        )

    def _count_recent_errors(self) -> int:
        """Count errors in journal since observation started."""
        try:
            since = datetime.fromtimestamp(self._observation_start).strftime("%Y-%m-%d %H:%M:%S")
            result = subprocess.run(
                ["journalctl", "--user", "--since", since, "-p", "err", "--no-pager", "-q"],
                capture_output=True, text=True, timeout=10
            )
            lines = [l for l in result.stdout.strip().split('\n') if l]
            return len(lines)
        except Exception:
            return 0

    def _check_crashed_services(self) -> List[str]:
        """Check if any critical services have crashed/restarted."""
        crashed = []

        for service in self.config.critical_services:
            try:
                # Check if service is active
                result = subprocess.run(
                    ["systemctl", "--user", "is-active", service],
                    capture_output=True, text=True, timeout=5
                )
                current_state = result.stdout.strip()

                # Check if it was previously active and now isn't
                prev_state = self._last_service_states.get(service, "unknown")
                if prev_state == "active" and current_state != "active":
                    crashed.append(service)
                    LOG.warning(f"Service {service} crashed: {prev_state} -> {current_state}")

                self._last_service_states[service] = current_state

            except Exception as e:
                LOG.error(f"Error checking service {service}: {e}")

        return crashed

    def _measure_response_times(self) -> Dict[str, float]:
        """Measure response times of critical endpoints."""
        import socket

        response_times = {}
        endpoints = {
            "core": ("127.0.0.1", 8088),
            "router": ("127.0.0.1", 8091),
            "toolbox": ("127.0.0.1", 8096),
        }

        for name, (host, port) in endpoints.items():
            try:
                start = time.time()
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2.0)
                sock.connect((host, port))
                sock.close()
                response_times[name] = (time.time() - start) * 1000
            except Exception:
                response_times[name] = -1

        return response_times

    def _check_for_anomalies(self, sample: MetricSample) -> List[Dict]:
        """Check sample against baseline for anomalies."""
        anomalies = []

        if not self._baseline or not self._baseline.baseline_metrics:
            return anomalies

        baseline = self._baseline.baseline_metrics

        # Memory spike
        if baseline.memory_used_mb > 0:
            memory_ratio = sample.memory_mb / baseline.memory_used_mb
            if memory_ratio > self.config.memory_spike_threshold:
                anomalies.append({
                    "type": "memory_spike",
                    "severity": "warning" if memory_ratio < 2.0 else "critical",
                    "baseline": baseline.memory_used_mb,
                    "current": sample.memory_mb,
                    "ratio": memory_ratio,
                })

        # Memory leak detection (consistent increase)
        if len(self._samples) >= 5:
            recent = list(self._samples)[-5:]
            if all(recent[i].memory_mb < recent[i+1].memory_mb for i in range(len(recent)-1)):
                increase = recent[-1].memory_mb - recent[0].memory_mb
                if increase > 100:  # 100MB increase
                    anomalies.append({
                        "type": "memory_leak",
                        "severity": "warning",
                        "increase_mb": increase,
                        "samples": 5,
                    })

        # CPU spike
        if sample.cpu_percent > self.config.cpu_spike_threshold:
            if self._cpu_spike_start == 0:
                self._cpu_spike_start = time.time()
            elif time.time() - self._cpu_spike_start > self.config.cpu_spike_duration_sec:
                anomalies.append({
                    "type": "cpu_spike",
                    "severity": "warning",
                    "current": sample.cpu_percent,
                    "threshold": self.config.cpu_spike_threshold,
                    "duration_sec": time.time() - self._cpu_spike_start,
                })
        else:
            self._cpu_spike_start = 0

        # Error surge
        if baseline.error_rate_per_min > 0:
            if sample.error_count > baseline.error_rate_per_min * self.config.error_rate_multiplier:
                anomalies.append({
                    "type": "error_surge",
                    "severity": "critical",
                    "baseline_rate": baseline.error_rate_per_min,
                    "current_count": sample.error_count,
                })
        elif sample.error_count > 10:  # Absolute threshold if baseline was 0
            anomalies.append({
                "type": "error_surge",
                "severity": "critical",
                "baseline_rate": 0,
                "current_count": sample.error_count,
            })

        # Service crash
        if sample.crashed_services:
            anomalies.append({
                "type": "service_crash",
                "severity": "critical",
                "services": sample.crashed_services,
            })

        # Response time degradation
        for endpoint, resp_time in sample.response_times.items():
            if resp_time < 0:  # Unreachable
                baseline_time = baseline.response_times_ms.get(endpoint, -1)
                if baseline_time >= 0:  # Was reachable before
                    anomalies.append({
                        "type": "service_unreachable",
                        "severity": "critical",
                        "endpoint": endpoint,
                    })
            elif resp_time > self.config.response_time_threshold_ms:
                anomalies.append({
                    "type": "response_time_high",
                    "severity": "warning",
                    "endpoint": endpoint,
                    "time_ms": resp_time,
                    "threshold_ms": self.config.response_time_threshold_ms,
                })

        return anomalies

    def force_check(self) -> List[Dict]:
        """Force an immediate check and return anomalies."""
        if not self._baseline:
            return []
        sample = self._collect_sample()
        self._samples.append(sample)
        return self._check_for_anomalies(sample)
