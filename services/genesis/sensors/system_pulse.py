#!/usr/bin/env python3
"""
System Pulse Sensor - Feels the heartbeat of the system
"""

from typing import List, Dict, Any
import subprocess
import logging

from .base import BaseSensor
from ..core.wave import Wave

LOG = logging.getLogger("genesis.sensors.system")


class SystemPulse(BaseSensor):
    """
    Senses the system's vital signs:
    - CPU usage
    - Memory usage
    - Disk space
    - System load
    """

    def __init__(self):
        super().__init__("system_pulse")
        self.previous_cpu = None

    def sense(self) -> List[Wave]:
        """Generate waves based on system state."""
        waves = []

        try:
            cpu = self._get_cpu_usage()
            memory = self._get_memory_usage()
            load = self._get_system_load()

            # High idle = boredom wave
            if cpu < 0.3:
                waves.append(Wave(
                    target_field="boredom",
                    amplitude=0.3 * (1 - cpu / 0.3),  # Higher amplitude when lower CPU
                    decay=0.05,
                    source=self.name,
                    metadata={"cpu": cpu},
                ))

                # Also satisfaction (system is healthy)
                waves.append(Wave(
                    target_field="satisfaction",
                    amplitude=0.2,
                    decay=0.03,
                    source=self.name,
                ))

            # Medium load = drive wave (good time to work)
            elif 0.3 <= cpu < 0.6:
                waves.append(Wave(
                    target_field="drive",
                    amplitude=0.25,
                    decay=0.04,
                    source=self.name,
                    metadata={"cpu": cpu},
                ))

            # High load = concern wave
            elif cpu >= 0.7:
                waves.append(Wave(
                    target_field="concern",
                    amplitude=0.3 * (cpu - 0.7) / 0.3,
                    decay=0.08,
                    source=self.name,
                    metadata={"cpu": cpu, "reason": "high_cpu"},
                ))

            # Memory pressure = concern
            if memory > 0.8:
                waves.append(Wave(
                    target_field="concern",
                    amplitude=0.4 * (memory - 0.8) / 0.2,
                    decay=0.1,
                    source=self.name,
                    metadata={"memory": memory, "reason": "memory_pressure"},
                ))

                # Also frustration (system struggling)
                waves.append(Wave(
                    target_field="frustration",
                    amplitude=0.2,
                    decay=0.05,
                    source=self.name,
                ))

            # Stable system = satisfaction
            if cpu < 0.5 and memory < 0.7:
                waves.append(Wave(
                    target_field="satisfaction",
                    amplitude=0.15,
                    decay=0.02,
                    source=self.name,
                    metadata={"stable": True},
                ))

        except Exception as e:
            LOG.warning(f"System pulse sensing error: {e}")

        return waves

    def get_observations(self) -> List[Dict[str, Any]]:
        """System observations that could become optimization seeds."""
        import random as _rnd
        observations = []

        try:
            cpu = self._get_cpu_usage()
            memory = self._get_memory_usage()
            load = self._get_system_load()

            # High memory usage → diverse optimization approaches
            if memory > 0.75:
                approach = _rnd.choice(["lazy_load", "caching", "precompute", "config_change"])
                observations.append({
                    "type": "optimization",
                    "target": "memory_usage",
                    "approach": approach,
                    "origin": "system_observation",
                    "strength": memory - 0.5,
                    "novelty": 0.3 + _rnd.random() * 0.3,
                    "risk": 0.2,
                    "impact": 0.6,
                })

            # High CPU → diverse approaches (not always caching!)
            if cpu > 0.6:
                approach = _rnd.choice(["caching", "parallel", "lazy_load", "refactoring"])
                observations.append({
                    "type": "optimization",
                    "target": "cpu_usage",
                    "approach": approach,
                    "origin": "system_observation",
                    "strength": cpu - 0.4,
                    "novelty": 0.4 + _rnd.random() * 0.3,
                    "risk": 0.3,
                    "impact": 0.5,
                })

            # NOTE: Random exploration seeds removed — they produced generic
            # proposals with no grounding in actual code or metrics.
            # Real observations come from CodeAnalyzer and ErrorTremor.

        except Exception as e:
            LOG.warning(f"Error getting observations: {e}")

        return observations

    def _get_cpu_usage(self) -> float:
        """Get current CPU usage (0-1)."""
        try:
            with open("/proc/stat") as f:
                line = f.readline()
            parts = line.split()
            idle = int(parts[4])
            total = sum(int(p) for p in parts[1:])

            if self.previous_cpu is None:
                self.previous_cpu = (idle, total)
                return 0.3  # Default

            prev_idle, prev_total = self.previous_cpu
            idle_delta = idle - prev_idle
            total_delta = total - prev_total

            self.previous_cpu = (idle, total)

            if total_delta == 0:
                return 0.0

            return 1.0 - (idle_delta / total_delta)
        except Exception:
            return 0.3

    def _get_memory_usage(self) -> float:
        """Get memory usage (0-1)."""
        try:
            with open("/proc/meminfo") as f:
                lines = f.readlines()
            info = {}
            for line in lines:
                parts = line.split()
                if len(parts) >= 2:
                    info[parts[0].rstrip(':')] = int(parts[1])
            total = info.get("MemTotal", 1)
            available = info.get("MemAvailable", 0)
            return (total - available) / total
        except Exception:
            return 0.5

    def _get_system_load(self) -> float:
        """Get system load average (normalized)."""
        try:
            with open("/proc/loadavg") as f:
                load = float(f.read().split()[0])

            # Get CPU count for normalization
            import os
            cpus = os.cpu_count() or 4
            return min(1.0, load / cpus)
        except Exception:
            return 0.3

    def get_current_metrics(self) -> Dict:
        """Get current system metrics."""
        return {
            "cpu": self._get_cpu_usage(),
            "memory": self._get_memory_usage(),
            "load": self._get_system_load(),
        }
