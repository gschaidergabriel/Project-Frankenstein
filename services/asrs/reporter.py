#!/usr/bin/env python3
"""
A.S.R.S. Error Reporter
Creates detailed failure reports for integration issues.
"""

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

from .config import ASRSConfig, get_asrs_config
from .baseline import Baseline, SystemMetrics
from .detector import Anomaly
from .rollback import RollbackResult

LOG = logging.getLogger("asrs.reporter")


@dataclass
class FailureReport:
    """Comprehensive failure report."""
    id: str
    feature_id: int
    feature_name: str
    timestamp: str

    # Timing
    integrated_at: str
    failed_at: str
    duration_sec: float

    # Anomalies detected
    anomalies: List[Dict]

    # System state at failure
    system_state: Dict[str, Any]

    # Comparison with baseline
    baseline_diff: Dict[str, Any]

    # Affected resources
    modified_files: List[str]
    affected_services: List[str]

    # Analysis
    probable_cause: str
    root_cause_analysis: List[str]
    recommended_actions: List[str]

    # Rollback info
    rollback_result: Optional[Dict] = None

    # Severity
    severity: str = "critical"

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "feature_id": self.feature_id,
            "feature_name": self.feature_name,
            "timestamp": self.timestamp,
            "integrated_at": self.integrated_at,
            "failed_at": self.failed_at,
            "duration_sec": self.duration_sec,
            "anomalies": self.anomalies,
            "system_state": self.system_state,
            "baseline_diff": self.baseline_diff,
            "modified_files": self.modified_files,
            "affected_services": self.affected_services,
            "probable_cause": self.probable_cause,
            "root_cause_analysis": self.root_cause_analysis,
            "recommended_actions": self.recommended_actions,
            "rollback_result": self.rollback_result,
            "severity": self.severity,
        }

    def to_text(self) -> str:
        """Generate human-readable report."""
        lines = [
            "=" * 70,
            "         F.A.S. INTEGRATION FAILURE REPORT",
            "=" * 70,
            "",
            f"Report ID:      {self.id}",
            f"Feature ID:     #{self.feature_id}",
            f"Feature Name:   {self.feature_name}",
            f"Integrated:     {self.integrated_at}",
            f"Failed:         {self.failed_at} (+{self.duration_sec:.0f} seconds)",
            f"Severity:       {self.severity.upper()}",
            "",
            "-" * 70,
            "DETECTED ANOMALIES",
            "-" * 70,
        ]

        for anomaly in self.anomalies:
            severity = anomaly.get('severity', 'unknown').upper()
            atype = anomaly.get('type', 'unknown')
            lines.append(f"[{severity}] {atype}")

            details = anomaly.get('details', {})
            for key, value in details.items():
                lines.append(f"    {key}: {value}")
            lines.append("")

        lines.extend([
            "-" * 70,
            "SYSTEM STATE AT FAILURE",
            "-" * 70,
        ])

        state = self.system_state
        lines.append(f"Memory:     {state.get('memory_mb', 'N/A')} MB ({state.get('memory_percent', 'N/A')}%)")
        lines.append(f"CPU:        {state.get('cpu_percent', 'N/A')}%")
        lines.append(f"Errors:     {state.get('error_count', 'N/A')}")

        if state.get('crashed_services'):
            lines.append(f"Crashed:    {', '.join(state['crashed_services'])}")

        lines.extend([
            "",
            "-" * 70,
            "BASELINE COMPARISON",
            "-" * 70,
        ])

        diff = self.baseline_diff
        if diff.get('memory_change'):
            lines.append(f"Memory:     {diff['memory_change']:+.1f} MB ({diff.get('memory_ratio', 1):.2f}x)")
        if diff.get('cpu_change'):
            lines.append(f"CPU:        {diff['cpu_change']:+.1f}%")
        if diff.get('error_change'):
            lines.append(f"Errors:     {diff['error_change']:+d}")

        lines.extend([
            "",
            "-" * 70,
            "ROOT CAUSE ANALYSIS",
            "-" * 70,
            f"Probable cause: {self.probable_cause}",
            "",
        ])

        for i, analysis in enumerate(self.root_cause_analysis, 1):
            lines.append(f"  {i}. {analysis}")

        lines.extend([
            "",
            "-" * 70,
            "RECOMMENDED ACTIONS",
            "-" * 70,
        ])

        for i, action in enumerate(self.recommended_actions, 1):
            lines.append(f"  {i}. {action}")

        if self.rollback_result:
            lines.extend([
                "",
                "-" * 70,
                "ROLLBACK STATUS",
                "-" * 70,
            ])

            rb = self.rollback_result
            status = "SUCCESS" if rb.get('success') else "FAILED"
            lines.append(f"Status:     {status}")
            lines.append(f"Level:      {rb.get('level', 'unknown')}")
            lines.append(f"Duration:   {rb.get('duration_sec', 0):.2f}s")

            if rb.get('files_restored'):
                lines.append(f"Files:      {len(rb['files_restored'])} restored")
            if rb.get('services_restarted'):
                lines.append(f"Services:   {len(rb['services_restarted'])} restarted")
            if rb.get('errors'):
                lines.append(f"Errors:     {len(rb['errors'])}")
                for err in rb['errors'][:3]:
                    lines.append(f"  - {err}")

        lines.extend([
            "",
            "-" * 70,
            "AFFECTED FILES",
            "-" * 70,
        ])

        for f in self.modified_files[:10]:
            lines.append(f"  - {f}")
        if len(self.modified_files) > 10:
            lines.append(f"  ... and {len(self.modified_files) - 10} more")

        lines.extend([
            "",
            "=" * 70,
        ])

        return "\n".join(lines)


class ErrorReporter:
    """
    Creates comprehensive error reports for integration failures.
    """

    def __init__(self, config: ASRSConfig = None):
        self.config = config or get_asrs_config()

    def create_report(self, feature_id: int, feature_name: str,
                      baseline: Baseline,
                      anomalies: List[Anomaly],
                      rollback_result: RollbackResult = None) -> FailureReport:
        """
        Create a comprehensive failure report.

        Args:
            feature_id: ID of the failed feature
            feature_name: Name of the feature
            baseline: The baseline that was used
            anomalies: List of detected anomalies
            rollback_result: Optional rollback result

        Returns:
            FailureReport object
        """
        now = datetime.now()
        report_id = f"failure_{feature_id}_{int(now.timestamp())}"

        # Calculate timing
        integrated_at = baseline.created_at
        failed_at = now.isoformat()

        try:
            integrated_dt = datetime.fromisoformat(integrated_at)
            duration_sec = (now - integrated_dt).total_seconds()
        except Exception:
            duration_sec = 0

        # Get current system state
        system_state = self._capture_system_state()

        # Compute baseline diff
        baseline_diff = self._compute_baseline_diff(baseline, system_state)

        # Analyze root cause
        probable_cause, root_cause_analysis = self._analyze_root_cause(anomalies, baseline_diff)

        # Generate recommended actions
        recommended_actions = self._generate_recommendations(anomalies, probable_cause)

        # Determine severity
        severity = self._determine_severity(anomalies)

        report = FailureReport(
            id=report_id,
            feature_id=feature_id,
            feature_name=feature_name,
            timestamp=now.isoformat(),
            integrated_at=integrated_at,
            failed_at=failed_at,
            duration_sec=duration_sec,
            anomalies=[a.to_dict() if hasattr(a, 'to_dict') else a for a in anomalies],
            system_state=system_state,
            baseline_diff=baseline_diff,
            modified_files=baseline.affected_files,
            affected_services=baseline.affected_services,
            probable_cause=probable_cause,
            root_cause_analysis=root_cause_analysis,
            recommended_actions=recommended_actions,
            rollback_result=rollback_result.to_dict() if rollback_result else None,
            severity=severity,
        )

        # Save report
        self._save_report(report)

        LOG.info(f"Created failure report {report_id} for feature #{feature_id}")
        return report

    def _capture_system_state(self) -> Dict:
        """Capture current system state."""
        import os

        state = {}

        # Memory
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
                state['memory_mb'] = round(used / 1024, 1)
                state['memory_percent'] = round((used / total) * 100, 1)
        except Exception:
            pass

        # CPU
        try:
            with open('/proc/loadavg') as f:
                parts = f.read().split()
                load = float(parts[0])
                cpu_count = os.cpu_count() or 1
                state['cpu_percent'] = round((load / cpu_count) * 100, 1)
                state['load_average'] = load
        except Exception:
            pass

        # Recent errors
        try:
            result = subprocess.run(
                ["journalctl", "--user", "--since", "5 minutes ago",
                 "-p", "err", "--no-pager", "-q"],
                capture_output=True, text=True, timeout=10
            )
            errors = [l for l in result.stdout.strip().split('\n') if l]
            state['error_count'] = len(errors)
            state['recent_errors'] = errors[:10]
        except Exception:
            state['error_count'] = 0
            state['recent_errors'] = []

        # Service states
        state['service_states'] = {}
        for service in self.config.critical_services:
            try:
                result = subprocess.run(
                    ["systemctl", "--user", "is-active", service],
                    capture_output=True, text=True, timeout=5
                )
                state['service_states'][service] = result.stdout.strip()
            except Exception:
                state['service_states'][service] = "unknown"

        # Crashed services
        state['crashed_services'] = [
            s for s, status in state['service_states'].items()
            if status not in ('active', 'activating')
        ]

        return state

    def _compute_baseline_diff(self, baseline: Baseline, current: Dict) -> Dict:
        """Compute difference from baseline."""
        diff = {}

        if not baseline.baseline_metrics:
            return diff

        bm = baseline.baseline_metrics

        # Memory
        if bm.memory_used_mb > 0:
            current_mem = current.get('memory_mb', 0)
            diff['memory_change'] = current_mem - bm.memory_used_mb
            diff['memory_ratio'] = current_mem / bm.memory_used_mb if bm.memory_used_mb > 0 else 1

        # CPU
        diff['cpu_change'] = current.get('cpu_percent', 0) - bm.cpu_percent

        # Errors
        diff['error_change'] = current.get('error_count', 0) - int(bm.error_rate_per_min)

        # Service changes
        diff['service_changes'] = {}
        for service, baseline_status in bm.service_states.items():
            current_status = current.get('service_states', {}).get(service, 'unknown')
            if baseline_status != current_status:
                diff['service_changes'][service] = {
                    'was': baseline_status,
                    'now': current_status,
                }

        return diff

    def _analyze_root_cause(self, anomalies: List, diff: Dict) -> tuple:
        """Analyze anomalies to determine root cause."""
        probable_cause = "Unknown"
        analysis = []

        anomaly_types = set()
        for a in anomalies:
            if hasattr(a, 'type'):
                anomaly_types.add(a.type)
            elif isinstance(a, dict):
                anomaly_types.add(a.get('type', ''))

        # Memory-related
        if any('memory' in t for t in anomaly_types):
            if 'memory_leak' in anomaly_types:
                probable_cause = "Memory leak"
                analysis.append("Consistent memory increase detected over time")
                analysis.append("Feature likely has unbounded data structures or missing cleanup")
            elif diff.get('memory_ratio', 1) > 2:
                probable_cause = "Memory exhaustion"
                analysis.append(f"Memory usage increased {diff.get('memory_ratio', 1):.1f}x from baseline")
                analysis.append("Feature may be loading large datasets without pagination")
            else:
                probable_cause = "Excessive memory usage"
                analysis.append("Memory spike detected during operation")

        # Service crash
        elif 'service_crash' in anomaly_types:
            probable_cause = "Service crash"
            analysis.append("One or more critical services terminated unexpectedly")
            if diff.get('memory_ratio', 1) > 1.5:
                analysis.append("Crash may be OOM-related (high memory before crash)")
            else:
                analysis.append("Check service logs for exception details")

        # CPU-related
        elif any('cpu' in t or 'loop' in t for t in anomaly_types):
            if 'possible_infinite_loop' in anomaly_types:
                probable_cause = "Infinite loop"
                analysis.append("CPU at 100% with no progress detected")
                analysis.append("Feature contains unbounded loop or blocking operation")
            else:
                probable_cause = "CPU overload"
                analysis.append("Sustained high CPU usage detected")
                analysis.append("Feature may have inefficient algorithms")

        # Error surge
        elif 'error_surge' in anomaly_types or 'error_emergence' in anomaly_types:
            probable_cause = "Runtime errors"
            analysis.append("Significant increase in error rate")
            analysis.append("Feature introduced bugs or incompatibilities")

        # Deadlock
        elif 'possible_deadlock' in anomaly_types:
            probable_cause = "Deadlock"
            analysis.append("System unresponsive with high CPU")
            analysis.append("Feature may have threading/locking issues")

        # Response time
        elif any('response' in t or 'unreachable' in t for t in anomaly_types):
            probable_cause = "Performance degradation"
            analysis.append("Services became slow or unresponsive")
            analysis.append("Feature may be blocking critical paths")

        if not analysis:
            analysis.append("No specific pattern identified")
            analysis.append("Manual investigation recommended")

        return probable_cause, analysis

    def _generate_recommendations(self, anomalies: List, probable_cause: str) -> List[str]:
        """Generate recommended actions based on analysis."""
        recommendations = []

        cause_lower = probable_cause.lower()

        if 'memory' in cause_lower:
            recommendations.append("Add memory limits (e.g., max 512MB per operation)")
            recommendations.append("Implement batch processing for large datasets")
            recommendations.append("Add explicit cleanup/garbage collection")
            recommendations.append("Use generators instead of loading full lists")

        elif 'loop' in cause_lower:
            recommendations.append("Add iteration limits to all loops")
            recommendations.append("Implement timeout guards")
            recommendations.append("Add progress tracking and early termination")

        elif 'crash' in cause_lower:
            recommendations.append("Add exception handling around critical sections")
            recommendations.append("Implement graceful degradation")
            recommendations.append("Add resource cleanup in finally blocks")

        elif 'error' in cause_lower:
            recommendations.append("Review error logs for specific exceptions")
            recommendations.append("Add input validation")
            recommendations.append("Implement defensive programming patterns")

        elif 'deadlock' in cause_lower:
            recommendations.append("Review thread synchronization")
            recommendations.append("Use timeout on all lock acquisitions")
            recommendations.append("Consider async/await patterns")

        elif 'performance' in cause_lower:
            recommendations.append("Profile the feature for bottlenecks")
            recommendations.append("Add caching for expensive operations")
            recommendations.append("Consider async processing")

        # Always add these
        recommendations.append("Run feature in isolated sandbox with stricter limits")
        recommendations.append("Consider staged rollout (10% -> 50% -> 100%)")

        return recommendations

    def _determine_severity(self, anomalies: List) -> str:
        """Determine overall severity from anomalies."""
        severities = set()

        for a in anomalies:
            if hasattr(a, 'severity'):
                severities.add(a.severity.value if hasattr(a.severity, 'value') else str(a.severity))
            elif isinstance(a, dict):
                severities.add(a.get('severity', 'warning'))

        if 'emergency' in severities:
            return 'emergency'
        elif 'critical' in severities:
            return 'critical'
        elif 'warning' in severities:
            return 'warning'
        else:
            return 'info'

    def _save_report(self, report: FailureReport):
        """Save report to disk."""
        # JSON format
        json_file = self.config.reports_dir / f"{report.id}.json"
        json_file.write_text(json.dumps(report.to_dict(), indent=2))

        # Human-readable format
        text_file = self.config.reports_dir / f"{report.id}.txt"
        text_file.write_text(report.to_text())

        LOG.debug(f"Saved report to {json_file} and {text_file}")

    def get_report(self, report_id: str) -> Optional[FailureReport]:
        """Load a report by ID."""
        json_file = self.config.reports_dir / f"{report_id}.json"
        if not json_file.exists():
            return None

        try:
            data = json.loads(json_file.read_text())
            return FailureReport(**data)
        except Exception as e:
            LOG.error(f"Failed to load report {report_id}: {e}")
            return None

    def list_reports(self, limit: int = 20) -> List[Dict]:
        """List recent failure reports."""
        reports = []

        for json_file in sorted(self.config.reports_dir.glob("failure_*.json"),
                                key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            try:
                data = json.loads(json_file.read_text())
                reports.append({
                    "id": data.get("id"),
                    "feature_id": data.get("feature_id"),
                    "feature_name": data.get("feature_name"),
                    "timestamp": data.get("timestamp"),
                    "severity": data.get("severity"),
                    "probable_cause": data.get("probable_cause"),
                })
            except Exception:
                pass

        return reports
