#!/usr/bin/env python3
"""
A.S.R.S. Anomaly Detector
Advanced pattern-based anomaly detection.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
import logging

from .config import ASRSConfig, get_asrs_config
from .baseline import Baseline, SystemMetrics
from .watchdog import MetricSample

LOG = logging.getLogger("asrs.detector")


class AnomalySeverity(Enum):
    """Severity levels for anomalies."""
    INFO = 1
    WARNING = 2
    CRITICAL = 3
    EMERGENCY = 4

    def __lt__(self, other):
        if isinstance(other, AnomalySeverity):
            return self.value < other.value
        return NotImplemented

    def __gt__(self, other):
        if isinstance(other, AnomalySeverity):
            return self.value > other.value
        return NotImplemented


@dataclass
class Anomaly:
    """Represents a detected anomaly."""
    type: str
    severity: AnomalySeverity
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    details: Dict[str, Any] = field(default_factory=dict)
    recommended_action: str = ""

    def to_dict(self) -> Dict:
        return {
            "type": self.type,
            "severity": self.severity.name.lower(),
            "timestamp": self.timestamp,
            "details": self.details,
            "recommended_action": self.recommended_action,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Anomaly":
        severity_str = data.get("severity", "warning").upper()
        try:
            severity = AnomalySeverity[severity_str]
        except KeyError:
            severity = AnomalySeverity.WARNING
        return cls(
            type=data["type"],
            severity=severity,
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            details=data.get("details", {}),
            recommended_action=data.get("recommended_action", ""),
        )

    def is_critical(self) -> bool:
        return self.severity in (AnomalySeverity.CRITICAL, AnomalySeverity.EMERGENCY)


class AnomalyDetector:
    """
    Advanced anomaly detection with pattern recognition.
    Goes beyond simple threshold checking.
    """

    def __init__(self, config: ASRSConfig = None):
        self.config = config or get_asrs_config()

    def analyze(self, baseline: Baseline, samples: List[MetricSample]) -> List[Anomaly]:
        """
        Analyze samples against baseline and detect anomalies.

        Args:
            baseline: The reference baseline
            samples: List of collected metric samples

        Returns:
            List of detected anomalies
        """
        if not samples:
            return []

        anomalies = []

        # Run all detectors
        anomalies.extend(self._detect_memory_anomalies(baseline, samples))
        anomalies.extend(self._detect_cpu_anomalies(baseline, samples))
        anomalies.extend(self._detect_error_anomalies(baseline, samples))
        anomalies.extend(self._detect_service_anomalies(baseline, samples))
        anomalies.extend(self._detect_response_anomalies(baseline, samples))
        anomalies.extend(self._detect_patterns(samples))
        anomalies.extend(self._detect_thermal_anomalies(samples))
        anomalies.extend(self._detect_disk_anomalies(samples))
        anomalies.extend(self._detect_io_anomalies(samples))
        anomalies.extend(self._detect_swap_anomalies(samples))

        return anomalies

    def _detect_memory_anomalies(self, baseline: Baseline,
                                  samples: List[MetricSample]) -> List[Anomaly]:
        """Detect memory-related anomalies."""
        anomalies = []

        if not baseline.baseline_metrics:
            return anomalies

        baseline_mem = baseline.baseline_metrics.memory_used_mb
        if baseline_mem <= 0:
            return anomalies

        current_mem = samples[-1].memory_mb

        # Spike detection
        ratio = current_mem / baseline_mem
        if ratio > self.config.memory_spike_threshold:
            severity = AnomalySeverity.WARNING
            if ratio > 2.0:
                severity = AnomalySeverity.CRITICAL
            if ratio > 3.0:
                severity = AnomalySeverity.EMERGENCY

            anomalies.append(Anomaly(
                type="memory_spike",
                severity=severity,
                details={
                    "baseline_mb": baseline_mem,
                    "current_mb": current_mem,
                    "ratio": ratio,
                    "increase_mb": current_mem - baseline_mem,
                },
                recommended_action="Check for memory leaks or unbounded data structures",
            ))

        # Leak detection (monotonic increase)
        if len(samples) >= 10:
            recent = samples[-10:]
            memory_values = [s.memory_mb for s in recent]

            # Check for consistent upward trend
            increases = sum(1 for i in range(len(memory_values)-1)
                           if memory_values[i+1] > memory_values[i])

            if increases >= 8:  # 8 out of 9 samples increasing
                total_increase = memory_values[-1] - memory_values[0]
                if total_increase > 50:  # At least 50MB increase
                    anomalies.append(Anomaly(
                        type="memory_leak",
                        severity=AnomalySeverity.WARNING,
                        details={
                            "samples_analyzed": 10,
                            "increases": increases,
                            "total_increase_mb": total_increase,
                            "trend": "monotonic_increase",
                        },
                        recommended_action="Investigate memory allocation patterns",
                    ))

        # OOM risk detection
        if samples[-1].memory_percent > 90:
            anomalies.append(Anomaly(
                type="oom_risk",
                severity=AnomalySeverity.CRITICAL,
                details={
                    "memory_percent": samples[-1].memory_percent,
                    "memory_mb": samples[-1].memory_mb,
                },
                recommended_action="Immediate rollback recommended to prevent OOM",
            ))

        return anomalies

    def _detect_cpu_anomalies(self, baseline: Baseline,
                               samples: List[MetricSample]) -> List[Anomaly]:
        """Detect CPU-related anomalies."""
        anomalies = []

        # Sustained high CPU
        high_cpu_samples = [s for s in samples if s.cpu_percent > self.config.cpu_spike_threshold]

        if len(high_cpu_samples) >= 3:  # At least 3 consecutive high samples
            # Calculate duration
            if len(samples) >= 3:
                duration = samples[-1].timestamp - samples[-3].timestamp

                severity = AnomalySeverity.WARNING
                if duration > 60:
                    severity = AnomalySeverity.CRITICAL

                anomalies.append(Anomaly(
                    type="sustained_high_cpu",
                    severity=severity,
                    details={
                        "avg_cpu_percent": sum(s.cpu_percent for s in high_cpu_samples) / len(high_cpu_samples),
                        "duration_sec": duration,
                        "samples": len(high_cpu_samples),
                    },
                    recommended_action="Check for infinite loops or blocking operations",
                ))

        # Infinite loop detection (100% CPU sustained)
        max_cpu_samples = [s for s in samples if s.cpu_percent >= 95]
        if len(max_cpu_samples) >= 5:
            anomalies.append(Anomaly(
                type="possible_infinite_loop",
                severity=AnomalySeverity.CRITICAL,
                details={
                    "samples_at_max": len(max_cpu_samples),
                    "total_samples": len(samples),
                },
                recommended_action="Likely infinite loop - immediate rollback recommended",
            ))

        return anomalies

    def _detect_error_anomalies(self, baseline: Baseline,
                                 samples: List[MetricSample]) -> List[Anomaly]:
        """Detect error-related anomalies."""
        anomalies = []

        if not samples:
            return anomalies

        current_errors = samples[-1].error_count
        baseline_rate = baseline.baseline_metrics.error_rate_per_min if baseline.baseline_metrics else 0

        # Error surge
        if baseline_rate > 0:
            multiplier = current_errors / baseline_rate
            if multiplier >= self.config.error_rate_multiplier:
                severity = AnomalySeverity.WARNING
                if multiplier >= 5:
                    severity = AnomalySeverity.CRITICAL
                if multiplier >= 10:
                    severity = AnomalySeverity.EMERGENCY

                anomalies.append(Anomaly(
                    type="error_surge",
                    severity=severity,
                    details={
                        "baseline_rate": baseline_rate,
                        "current_count": current_errors,
                        "multiplier": multiplier,
                    },
                    recommended_action="Check logs for error patterns",
                ))
        elif current_errors > 10:
            # No baseline errors but now have many
            anomalies.append(Anomaly(
                type="error_emergence",
                severity=AnomalySeverity.CRITICAL,
                details={
                    "error_count": current_errors,
                    "baseline_was_zero": True,
                },
                recommended_action="New errors appearing where none existed before",
            ))

        # Rapid error increase
        if len(samples) >= 3:
            error_counts = [s.error_count for s in samples[-3:]]
            if all(error_counts[i] < error_counts[i+1] for i in range(len(error_counts)-1)):
                if error_counts[-1] - error_counts[0] > 5:
                    anomalies.append(Anomaly(
                        type="accelerating_errors",
                        severity=AnomalySeverity.WARNING,
                        details={
                            "error_trend": error_counts,
                        },
                        recommended_action="Error rate accelerating - investigate immediately",
                    ))

        return anomalies

    def _detect_service_anomalies(self, baseline: Baseline,
                                   samples: List[MetricSample]) -> List[Anomaly]:
        """Detect service-related anomalies."""
        anomalies = []

        if not samples:
            return anomalies

        crashed = samples[-1].crashed_services
        if crashed:
            anomalies.append(Anomaly(
                type="service_crash",
                severity=AnomalySeverity.CRITICAL,
                details={
                    "crashed_services": crashed,
                    "count": len(crashed),
                },
                recommended_action="Critical services have crashed - immediate rollback required",
            ))

        return anomalies

    def _detect_response_anomalies(self, baseline: Baseline,
                                    samples: List[MetricSample]) -> List[Anomaly]:
        """Detect response time anomalies."""
        anomalies = []

        if not samples or not baseline.baseline_metrics:
            return anomalies

        current = samples[-1].response_times
        baseline_times = baseline.baseline_metrics.response_times_ms

        for endpoint, resp_time in current.items():
            baseline_time = baseline_times.get(endpoint, -1)

            # Service became unreachable
            if resp_time < 0 and baseline_time >= 0:
                anomalies.append(Anomaly(
                    type="service_unreachable",
                    severity=AnomalySeverity.CRITICAL,
                    details={
                        "endpoint": endpoint,
                        "baseline_time_ms": baseline_time,
                    },
                    recommended_action=f"Service {endpoint} is no longer responding",
                ))

            # Response time severely degraded
            elif resp_time > 0 and baseline_time > 0:
                if resp_time > baseline_time * 5:  # 5x slower
                    anomalies.append(Anomaly(
                        type="response_degradation",
                        severity=AnomalySeverity.WARNING,
                        details={
                            "endpoint": endpoint,
                            "baseline_ms": baseline_time,
                            "current_ms": resp_time,
                            "slowdown_factor": resp_time / baseline_time,
                        },
                        recommended_action=f"Service {endpoint} response time severely degraded",
                    ))

        return anomalies

    def _detect_patterns(self, samples: List[MetricSample]) -> List[Anomaly]:
        """Detect complex patterns across metrics."""
        anomalies = []

        if len(samples) < 5:
            return anomalies

        # Deadlock pattern: High CPU but no response from services
        recent = samples[-5:]
        high_cpu_no_response = all(
            s.cpu_percent > 80 and any(t < 0 for t in s.response_times.values())
            for s in recent
        )

        if high_cpu_no_response:
            anomalies.append(Anomaly(
                type="possible_deadlock",
                severity=AnomalySeverity.EMERGENCY,
                details={
                    "pattern": "high_cpu_unresponsive_services",
                    "duration_samples": 5,
                },
                recommended_action="System appears deadlocked - emergency rollback required",
            ))

        # Resource exhaustion pattern: Memory and CPU both high
        resource_exhaustion = all(
            s.memory_percent > 80 and s.cpu_percent > 80
            for s in recent
        )

        if resource_exhaustion:
            anomalies.append(Anomaly(
                type="resource_exhaustion",
                severity=AnomalySeverity.CRITICAL,
                details={
                    "avg_memory_percent": sum(s.memory_percent for s in recent) / len(recent),
                    "avg_cpu_percent": sum(s.cpu_percent for s in recent) / len(recent),
                },
                recommended_action="System resources critically exhausted",
            ))

        return anomalies

    def _detect_thermal_anomalies(self, samples: List[MetricSample]) -> List[Anomaly]:
        """Detect temperature anomalies from CPU thermal sensors."""
        anomalies = []

        if not samples:
            return anomalies

        temp = samples[-1].cpu_temp_c
        if temp is None:
            return anomalies

        thermal_warn = getattr(self.config, 'thermal_warning_c', 80)
        thermal_crit = getattr(self.config, 'thermal_critical_c', 90)
        thermal_emerg = getattr(self.config, 'thermal_emergency_c', 95)

        if temp >= thermal_emerg:
            anomalies.append(Anomaly(
                type="thermal_emergency",
                severity=AnomalySeverity.EMERGENCY,
                details={"temp_c": temp, "threshold_c": thermal_emerg},
                recommended_action="CPU temperature critical - immediate throttling or shutdown required",
            ))
        elif temp >= thermal_crit:
            anomalies.append(Anomaly(
                type="thermal_critical",
                severity=AnomalySeverity.CRITICAL,
                details={"temp_c": temp, "threshold_c": thermal_crit},
                recommended_action="CPU temperature very high - reduce workload immediately",
            ))
        elif temp >= thermal_warn:
            anomalies.append(Anomaly(
                type="thermal_warning",
                severity=AnomalySeverity.WARNING,
                details={"temp_c": temp, "threshold_c": thermal_warn},
                recommended_action="CPU temperature elevated - monitor cooling system",
            ))

        return anomalies

    def _detect_disk_anomalies(self, samples: List[MetricSample]) -> List[Anomaly]:
        """Detect disk usage anomalies per path."""
        anomalies = []

        if not samples:
            return anomalies

        disk_usage = samples[-1].disk_usage
        if not disk_usage:
            return anomalies

        disk_warn = getattr(self.config, 'disk_warning_percent', 85)
        disk_crit = getattr(self.config, 'disk_critical_percent', 90)
        disk_emerg = getattr(self.config, 'disk_emergency_percent', 95)

        for path, percent in disk_usage.items():
            if percent >= disk_emerg:
                anomalies.append(Anomaly(
                    type="disk_emergency",
                    severity=AnomalySeverity.EMERGENCY,
                    details={"path": path, "percent_used": percent, "threshold": disk_emerg},
                    recommended_action=f"Disk {path} nearly full - free space immediately",
                ))
            elif percent >= disk_crit:
                anomalies.append(Anomaly(
                    type="disk_critical",
                    severity=AnomalySeverity.CRITICAL,
                    details={"path": path, "percent_used": percent, "threshold": disk_crit},
                    recommended_action=f"Disk {path} usage critical - clean up or expand storage",
                ))
            elif percent >= disk_warn:
                anomalies.append(Anomaly(
                    type="disk_warning",
                    severity=AnomalySeverity.WARNING,
                    details={"path": path, "percent_used": percent, "threshold": disk_warn},
                    recommended_action=f"Disk {path} usage elevated - plan cleanup",
                ))

        return anomalies

    def _detect_io_anomalies(self, samples: List[MetricSample]) -> List[Anomaly]:
        """Detect I/O pressure anomalies from PSI avg10."""
        anomalies = []

        if not samples:
            return anomalies

        io_pressure = samples[-1].io_pressure_avg10
        if io_pressure is None:
            return anomalies

        io_warn = getattr(self.config, 'io_pressure_warning', 50)
        io_crit = getattr(self.config, 'io_pressure_critical', 80)

        if io_pressure > io_crit:
            anomalies.append(Anomaly(
                type="io_pressure_critical",
                severity=AnomalySeverity.CRITICAL,
                details={"avg10": io_pressure, "threshold": io_crit},
                recommended_action="I/O pressure critical - check for disk bottlenecks or failing drives",
            ))
        elif io_pressure > io_warn:
            anomalies.append(Anomaly(
                type="io_pressure_warning",
                severity=AnomalySeverity.WARNING,
                details={"avg10": io_pressure, "threshold": io_warn},
                recommended_action="I/O pressure elevated - monitor disk activity",
            ))

        return anomalies

    def _detect_swap_anomalies(self, samples: List[MetricSample]) -> List[Anomaly]:
        """Detect swap usage anomalies."""
        anomalies = []

        if not samples:
            return anomalies

        swap_pct = samples[-1].swap_percent
        if swap_pct is None:
            return anomalies

        swap_warn = getattr(self.config, 'swap_warning_percent', 50)
        swap_crit = getattr(self.config, 'swap_critical_percent', 80)

        if swap_pct > swap_crit:
            anomalies.append(Anomaly(
                type="swap_critical",
                severity=AnomalySeverity.CRITICAL,
                details={"swap_percent": swap_pct, "threshold": swap_crit},
                recommended_action="Swap usage critical - system may become unresponsive, investigate memory consumers",
            ))
        elif swap_pct > swap_warn:
            anomalies.append(Anomaly(
                type="swap_warning",
                severity=AnomalySeverity.WARNING,
                details={"swap_percent": swap_pct, "threshold": swap_warn},
                recommended_action="Swap usage elevated - check for memory-hungry processes",
            ))

        return anomalies

    def get_severity_action(self, anomalies: List) -> str:
        """
        Determine recommended action based on anomaly severities.

        Returns:
            One of: "monitor", "warn", "rollback", "emergency_rollback"
        """
        if not anomalies:
            return "monitor"

        # Handle both Anomaly objects and dicts
        severities = []
        for a in anomalies:
            if hasattr(a, 'severity'):
                severities.append(a.severity)
            elif isinstance(a, dict):
                sev_str = a.get('severity', 'warning').upper()
                try:
                    severities.append(AnomalySeverity[sev_str])
                except KeyError:
                    severities.append(AnomalySeverity.WARNING)

        if not severities:
            return "monitor"

        max_severity = max(severities)

        if max_severity == AnomalySeverity.EMERGENCY:
            return "emergency_rollback"
        elif max_severity == AnomalySeverity.CRITICAL:
            return "rollback"
        elif max_severity == AnomalySeverity.WARNING:
            return "warn"
        else:
            return "monitor"
