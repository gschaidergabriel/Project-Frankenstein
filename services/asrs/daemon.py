#!/usr/bin/env python3
"""
A.S.R.S. Daemon - Autonomous Safety Recovery System v2.0
Intelligent multi-stage monitoring with feature-specific correlation.

Protection Layers:
1. IMMEDIATE (0-5 min): Critical failures, instant rollback
2. SHORT-TERM (5 min - 2 hours): Trend analysis, gradual degradation
3. LONG-TERM (2-24 hours): Memory leaks, slow degradation
4. PERMANENT: Correlation of any crash with recent features

Smart Recovery:
- Feature-specific rollback (not blanket rollback)
- Automatic revalidation of innocent features
- Quarantine system for corrupt features
"""

import fcntl
import hashlib
import json
import logging
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Setup logging
LOG_FILE = Path("/tmp/asrs_daemon.log")
LOG = logging.getLogger("asrs.daemon")
LOG.setLevel(logging.DEBUG)
LOG.handlers.clear()
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s'))
LOG.addHandler(file_handler)
LOG.propagate = False

# Paths
SIGNAL_FILE = Path("/tmp/asrs_monitor_queue.json")
SOCKET_PATH = Path(f"/run/user/{os.getuid()}/frank/asrs_daemon.sock")
try:
    from config.paths import ASRS_BACKUP_DIR as _ASRS_BKP_DIR, AICORE_ROOT as _ASRS_DAEMON_ROOT
    BACKUP_DIR = _ASRS_BKP_DIR
except ImportError:
    BACKUP_DIR = Path("/home/ai-core-node/aicore/database/asrs_backups")
    _ASRS_DAEMON_ROOT = Path("/home/ai-core-node/aicore/opt/aicore")
QUARANTINE_DIR = BACKUP_DIR / "quarantine"
FEATURE_DB = BACKUP_DIR / "feature_registry.json"
METRICS_DIR = BACKUP_DIR / "metrics"
NOTIFY_SOCKET = Path(f"/run/user/{os.getuid()}/frank/frank_events.sock")

# Monitoring stages
STAGE_1_DURATION = 300      # 5 minutes - critical monitoring
STAGE_1_INTERVAL = 10       # Check every 10 seconds

STAGE_2_DURATION = 7200     # 2 hours - short-term monitoring
STAGE_2_INTERVAL = 60       # Check every 60 seconds

STAGE_3_DURATION = 86400    # 24 hours - long-term monitoring
STAGE_3_INTERVAL = 300      # Check every 5 minutes

REVALIDATION_DURATION = 600 # 10 minutes per feature revalidation
REVALIDATION_TIMEOUT = 900  # FIX MEDIUM #7: 15 minutes max - mark as failed if exceeded

# Thresholds
MEMORY_SPIKE_THRESHOLD = 1.3      # 30% above baseline
MEMORY_LEAK_THRESHOLD = 1.05      # 5% increase per hour (trend)
CPU_SPIKE_THRESHOLD = 95          # 95% CPU
ERROR_RATE_CRITICAL = 10          # 10 errors/min = critical
ERROR_RATE_WARNING = 5            # 5 errors/min = warning

# Retention
BASELINE_RETENTION_DAYS = 30


class FeatureStatus(Enum):
    PENDING = "pending"
    ACTIVE = "active"
    MONITORING_STAGE_1 = "monitoring_stage_1"
    MONITORING_STAGE_2 = "monitoring_stage_2"
    MONITORING_STAGE_3 = "monitoring_stage_3"
    STABLE = "stable"
    SUSPECT = "suspect"
    QUARANTINED = "quarantined"
    ROLLED_BACK = "rolled_back"
    REVALIDATING = "revalidating"


@dataclass
class SystemMetrics:
    """System metrics snapshot."""
    timestamp: float
    memory_percent: float
    memory_mb: float
    cpu_percent: float
    load_average: float
    error_count: int
    services: Dict[str, bool]
    cpu_temp_c: Optional[float] = None
    disk_usage: Optional[Dict[str, float]] = None
    io_pressure_avg10: Optional[float] = None
    swap_percent: Optional[float] = None

    def to_dict(self) -> Dict:
        d = {
            "timestamp": self.timestamp,
            "memory_percent": self.memory_percent,
            "memory_mb": self.memory_mb,
            "cpu_percent": self.cpu_percent,
            "load_average": self.load_average,
            "error_count": self.error_count,
            "services": self.services,
        }
        if self.cpu_temp_c is not None:
            d["cpu_temp_c"] = self.cpu_temp_c
        if self.disk_usage is not None:
            d["disk_usage"] = self.disk_usage
        if self.io_pressure_avg10 is not None:
            d["io_pressure_avg10"] = self.io_pressure_avg10
        if self.swap_percent is not None:
            d["swap_percent"] = self.swap_percent
        return d

    @classmethod
    def from_dict(cls, d: Dict) -> "SystemMetrics":
        # Handle forward-compatible loading: ignore unknown keys, supply defaults for new fields
        known = {"timestamp", "memory_percent", "memory_mb", "cpu_percent",
                 "load_average", "error_count", "services", "cpu_temp_c",
                 "disk_usage", "io_pressure_avg10", "swap_percent"}
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)


@dataclass
class FeatureRecord:
    """Complete record of an integrated feature."""
    feature_id: int
    feature_name: str
    integrated_at: float
    status: FeatureStatus

    # What this feature changed
    modified_files: List[str] = field(default_factory=list)
    modified_functions: List[str] = field(default_factory=list)

    # Baseline when integrated
    baseline_dir: str = ""
    baseline_metrics: Optional[Dict] = None

    # Monitoring history
    metrics_history: List[Dict] = field(default_factory=list)

    # Confidence score (0-100, increases over time if stable)
    confidence_score: int = 10

    # Issues detected
    issues: List[str] = field(default_factory=list)

    # Timestamps
    stage_1_end: float = 0
    stage_2_end: float = 0
    stage_3_end: float = 0
    last_check: float = 0

    def to_dict(self) -> Dict:
        return {
            "feature_id": self.feature_id,
            "feature_name": self.feature_name,
            "integrated_at": self.integrated_at,
            "status": self.status.value,
            "modified_files": self.modified_files,
            "modified_functions": self.modified_functions,
            "baseline_dir": self.baseline_dir,
            "baseline_metrics": self.baseline_metrics,
            "metrics_history": self.metrics_history[-100:],  # Keep last 100
            "confidence_score": self.confidence_score,
            "issues": self.issues,
            "stage_1_end": self.stage_1_end,
            "stage_2_end": self.stage_2_end,
            "stage_3_end": self.stage_3_end,
            "last_check": self.last_check,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "FeatureRecord":
        d["status"] = FeatureStatus(d["status"])
        return cls(**d)


class FeatureRegistry:
    """Persistent registry of all integrated features."""

    # FIX CRITICAL #2: Backup file for corrupt registry recovery
    BACKUP_SUFFIX = ".backup"

    def __init__(self):
        self.features: Dict[int, FeatureRecord] = {}
        self._load()

    def _load(self):
        """Load registry from disk with backup recovery for corrupt files."""
        if FEATURE_DB.exists():
            try:
                data = json.loads(FEATURE_DB.read_text())
                for fid, fdata in data.items():
                    self.features[int(fid)] = FeatureRecord.from_dict(fdata)
                LOG.info(f"Loaded {len(self.features)} features from registry")
                # FIX CRITICAL #2: Create backup after successful load
                self._create_backup()
            except json.JSONDecodeError as e:
                # FIX CRITICAL #2: JSON parse error - try backup
                LOG.error(f"Registry file corrupt (JSON error): {e}")
                self._load_from_backup()
            except Exception as e:
                LOG.error(f"Failed to load feature registry: {e}")
                self._load_from_backup()

    def _create_backup(self):
        """Create backup of current registry."""
        try:
            backup_path = Path(str(FEATURE_DB) + self.BACKUP_SUFFIX)
            if FEATURE_DB.exists():
                shutil.copy2(FEATURE_DB, backup_path)
        except Exception as e:
            LOG.warning(f"Failed to create registry backup: {e}")

    def _load_from_backup(self):
        """Load from backup registry if available."""
        backup_path = Path(str(FEATURE_DB) + self.BACKUP_SUFFIX)
        if backup_path.exists():
            try:
                data = json.loads(backup_path.read_text())
                for fid, fdata in data.items():
                    self.features[int(fid)] = FeatureRecord.from_dict(fdata)
                LOG.warning(f"Loaded {len(self.features)} features from BACKUP registry")
                # Restore main registry from backup
                shutil.copy2(backup_path, FEATURE_DB)
                return
            except Exception as e:
                LOG.error(f"Backup registry also corrupt: {e}")

        # FIX CRITICAL #2: No backup available - start with empty registry
        LOG.warning("Starting with empty feature registry - no valid backup found")
        self.features = {}

    def save(self):
        """Save registry to disk with file locking."""
        try:
            FEATURE_DB.parent.mkdir(parents=True, exist_ok=True)
            data = {str(fid): f.to_dict() for fid, f in self.features.items()}

            # FIX HIGH #3: Use file locking to prevent concurrent writes
            # Write to temp file first, then atomic rename
            temp_file = Path(str(FEATURE_DB) + ".tmp")
            with open(temp_file, 'w') as f:
                # Acquire exclusive lock
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump(data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())  # Ensure data is written to disk
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            # Atomic rename
            temp_file.rename(FEATURE_DB)

            # FIX CRITICAL #2: Create backup after successful save
            self._create_backup()
        except Exception as e:
            LOG.error(f"Failed to save feature registry: {e}")

    def add_feature(self, feature: FeatureRecord):
        """Add or update a feature."""
        self.features[feature.feature_id] = feature
        self.save()

    def get_feature(self, feature_id: int) -> Optional[FeatureRecord]:
        """Get a feature by ID."""
        return self.features.get(feature_id)

    def get_active_features(self) -> List[FeatureRecord]:
        """Get all features currently being monitored."""
        active_statuses = {
            FeatureStatus.MONITORING_STAGE_1,
            FeatureStatus.MONITORING_STAGE_2,
            FeatureStatus.MONITORING_STAGE_3,
            FeatureStatus.ACTIVE,
            FeatureStatus.REVALIDATING,
        }
        return [f for f in self.features.values() if f.status in active_statuses]

    def get_recent_features(self, hours: int = 24) -> List[FeatureRecord]:
        """Get features integrated in the last N hours."""
        cutoff = time.time() - (hours * 3600)
        return [f for f in self.features.values()
                if f.integrated_at > cutoff and f.status != FeatureStatus.QUARANTINED]

    def get_suspects(self, error_location: str = None) -> List[FeatureRecord]:
        """Get features that might have caused an issue."""
        recent = self.get_recent_features(24)

        if error_location:
            # Prioritize features that modified the error location
            suspects = []
            for f in recent:
                if any(error_location in mf for mf in f.modified_files):
                    suspects.insert(0, f)  # High priority
                elif any(error_location in mf for mf in f.modified_functions):
                    suspects.insert(0, f)
                else:
                    suspects.append(f)
            return suspects
        else:
            # Sort by integration time (newest first = most suspect)
            return sorted(recent, key=lambda f: f.integrated_at, reverse=True)


class ASRSDaemon:
    """Main A.S.R.S. Daemon with intelligent monitoring."""

    CRITICAL_SERVICES = [
        "aicore-core.service",
        "aicore-router.service",
        "aicore-toolboxd.service",
    ]

    def __init__(self):
        self.running = False
        self.registry = FeatureRegistry()
        self._lock = threading.Lock()
        self._revalidation_queue: List[int] = []
        self._revalidating_feature: Optional[int] = None
        self._revalidation_start: float = 0

        # FIX HIGH #4: Use Event for clean shutdown instead of sleep loop
        self._stop_event = threading.Event()

        # FIX HIGH #5: Lock for revalidation queue access
        self._revalidation_lock = threading.Lock()

        # Auto-repair subsystem
        from services.asrs.auto_repair import AutoRepairManager
        self.auto_repair = AutoRepairManager()

        # Ensure directories exist
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
        METRICS_DIR.mkdir(parents=True, exist_ok=True)
        SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)

    def start(self):
        """Start the daemon."""
        LOG.info("=" * 60)
        LOG.info("A.S.R.S. Daemon v2.0 - Intelligent Safety Recovery")
        LOG.info("=" * 60)

        self.running = True

        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

        # Start socket listener
        socket_thread = threading.Thread(target=self._run_socket_listener, daemon=True)
        socket_thread.start()

        # Start cleanup thread
        cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        cleanup_thread.start()

        # Main monitoring loop
        self._main_loop()

    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signal."""
        LOG.info("Shutdown signal received")
        self.running = False
        # FIX HIGH #4: Signal stop event to wake up waiting threads
        self._stop_event.set()

    def _main_loop(self):
        """Main daemon loop - checks all active features."""
        LOG.info("A.S.R.S. monitoring active")

        last_check = {}

        while self.running:
            try:
                now = time.time()

                # Check for new feature signals
                self._check_signal_file()

                # Check revalidation queue
                self._process_revalidation()

                # Process pending auto-repair approvals
                self.auto_repair.process_queue()

                # Monitor all active features
                for feature in self.registry.get_active_features():
                    interval = self._get_check_interval(feature)
                    last = last_check.get(feature.feature_id, 0)

                    if now - last >= interval:
                        self._check_feature(feature)
                        last_check[feature.feature_id] = now

                time.sleep(5)  # Base loop interval

            except Exception as e:
                LOG.error(f"Main loop error: {e}")
                time.sleep(10)

        LOG.info("A.S.R.S. Daemon stopped")

    def _get_check_interval(self, feature: FeatureRecord) -> int:
        """Get check interval based on feature's monitoring stage."""
        if feature.status == FeatureStatus.MONITORING_STAGE_1:
            return STAGE_1_INTERVAL
        elif feature.status == FeatureStatus.MONITORING_STAGE_2:
            return STAGE_2_INTERVAL
        elif feature.status == FeatureStatus.MONITORING_STAGE_3:
            return STAGE_3_INTERVAL
        elif feature.status == FeatureStatus.REVALIDATING:
            return STAGE_1_INTERVAL  # Strict monitoring during revalidation
        else:
            return STAGE_3_INTERVAL  # Default to long-term

    def _check_signal_file(self):
        """Check for new monitoring requests."""
        if not SIGNAL_FILE.exists():
            return

        try:
            # FIX CRITICAL #2: Read and parse BEFORE deleting
            content = SIGNAL_FILE.read_text()
            try:
                data = json.loads(content)
            except json.JSONDecodeError as e:
                # FIX CRITICAL #2: Log corrupt signal file, then delete it
                LOG.error(f"Signal file corrupt (JSON error): {e}")
                LOG.error(f"Corrupt content: {content[:500]}")
                SIGNAL_FILE.unlink()  # Delete corrupt file to prevent infinite loop
                return

            # FIX CRITICAL #2: Only delete AFTER successful parse
            SIGNAL_FILE.unlink()

            if data.get("action") == "monitor":
                feature_ids = data.get("feature_ids", [])
                features_data = data.get("features", [])

                for i, fid in enumerate(feature_ids):
                    # Get feature details if provided
                    fdata = features_data[i] if i < len(features_data) else {}
                    self._start_feature_monitoring(fid, fdata)

        except Exception as e:
            LOG.error(f"Signal file error: {e}")
            # Don't delete the file on unexpected errors - let it be retried

    def _start_feature_monitoring(self, feature_id: int, feature_data: Dict = None):
        """Start monitoring a newly integrated feature."""
        feature_data = feature_data or {}
        now = time.time()

        LOG.info(f"Starting monitoring for feature #{feature_id}: {feature_data.get('name', 'Unknown')}")

        # Capture baseline metrics
        baseline = self._capture_metrics()

        # Create baseline directory
        baseline_dir = BACKUP_DIR / f"feature_{feature_id}_{int(now)}"
        baseline_dir.mkdir(parents=True, exist_ok=True)

        # Save baseline
        (baseline_dir / "baseline.json").write_text(json.dumps(baseline.to_dict(), indent=2))

        # Create feature record
        record = FeatureRecord(
            feature_id=feature_id,
            feature_name=feature_data.get("name", f"Feature #{feature_id}"),
            integrated_at=now,
            status=FeatureStatus.MONITORING_STAGE_1,
            modified_files=feature_data.get("modified_files", []),
            modified_functions=feature_data.get("modified_functions", []),
            baseline_dir=str(baseline_dir),
            baseline_metrics=baseline.to_dict(),
            stage_1_end=now + STAGE_1_DURATION,
            stage_2_end=now + STAGE_1_DURATION + STAGE_2_DURATION,
            stage_3_end=now + STAGE_1_DURATION + STAGE_2_DURATION + STAGE_3_DURATION,
        )

        self.registry.add_feature(record)

        LOG.info(f"Feature #{feature_id} baseline: mem={baseline.memory_percent:.1f}%, "
                 f"cpu={baseline.cpu_percent:.1f}%, errors={baseline.error_count}")

    def _check_feature(self, feature: FeatureRecord):
        """Check a feature's health and update monitoring stage."""
        now = time.time()
        current = self._capture_metrics()
        baseline = SystemMetrics.from_dict(feature.baseline_metrics) if feature.baseline_metrics else current

        feature.last_check = now
        feature.metrics_history.append(current.to_dict())

        # Check for problems
        problems = self._analyze_metrics(feature, baseline, current)

        if problems:
            LOG.warning(f"Feature #{feature.feature_id} issues: {problems}")
            feature.issues.extend(problems)
            self._handle_feature_problem(feature, problems)
            return

        # Update stage based on time
        if feature.status == FeatureStatus.MONITORING_STAGE_1:
            if now >= feature.stage_1_end:
                feature.status = FeatureStatus.MONITORING_STAGE_2
                feature.confidence_score = min(100, feature.confidence_score + 20)
                LOG.info(f"Feature #{feature.feature_id} promoted to Stage 2 (confidence: {feature.confidence_score})")

        elif feature.status == FeatureStatus.MONITORING_STAGE_2:
            if now >= feature.stage_2_end:
                feature.status = FeatureStatus.MONITORING_STAGE_3
                feature.confidence_score = min(100, feature.confidence_score + 30)
                LOG.info(f"Feature #{feature.feature_id} promoted to Stage 3 (confidence: {feature.confidence_score})")

        elif feature.status == FeatureStatus.MONITORING_STAGE_3:
            if now >= feature.stage_3_end:
                feature.status = FeatureStatus.STABLE
                feature.confidence_score = min(100, feature.confidence_score + 40)
                LOG.info(f"Feature #{feature.feature_id} is now STABLE (confidence: {feature.confidence_score})")
                self._notify_user(f"Feature '{feature.feature_name}' is now stable.", "low")

        elif feature.status == FeatureStatus.REVALIDATING:
            # FIX MEDIUM #7: Check for revalidation timeout
            with self._revalidation_lock:
                revalidation_elapsed = now - self._revalidation_start

            if revalidation_elapsed >= REVALIDATION_TIMEOUT:
                # FIX MEDIUM #7: Revalidation took too long - mark as failed
                LOG.error(f"Feature #{feature.feature_id} revalidation TIMEOUT after {revalidation_elapsed:.0f}s")
                feature.status = FeatureStatus.QUARANTINED
                feature.issues.append(f"REVALIDATION_TIMEOUT: Exceeded {REVALIDATION_TIMEOUT}s")
                self._quarantine_feature(feature)
                self._notify_user(
                    f"Feature '{feature.feature_name}' revalidation failed (timeout).",
                    "critical"
                )
                with self._revalidation_lock:
                    self._revalidating_feature = None
            elif revalidation_elapsed >= REVALIDATION_DURATION:
                # Revalidation period passed successfully
                feature.status = FeatureStatus.STABLE
                feature.confidence_score = 50  # Reset to moderate confidence
                LOG.info(f"Feature #{feature.feature_id} revalidation PASSED")
                self._notify_user(f"Feature '{feature.feature_name}' was successfully revalidated.", "low")
                with self._revalidation_lock:
                    self._revalidating_feature = None

        self.registry.save()

    def _analyze_metrics(self, feature: FeatureRecord, baseline: SystemMetrics,
                         current: SystemMetrics) -> List[str]:
        """Analyze metrics and return list of problems."""
        problems = []

        # Critical: Service crash
        for service, is_active in current.services.items():
            if not is_active:
                problems.append(f"CRITICAL: Service {service} crashed")

        # Critical: Memory spike
        if current.memory_percent > baseline.memory_percent * MEMORY_SPIKE_THRESHOLD:
            if current.memory_percent > 90:
                problems.append(f"CRITICAL: Memory at {current.memory_percent:.1f}%")

        # Critical: Error spike
        if current.error_count >= ERROR_RATE_CRITICAL:
            problems.append(f"CRITICAL: {current.error_count} errors/min")

        # Warning: Memory trend (check over time)
        if len(feature.metrics_history) >= 6:
            mem_trend = self._calculate_trend(feature.metrics_history, "memory_percent")
            if mem_trend > 0.5:  # 0.5% increase per check
                problems.append(f"WARNING: Memory leak detected (trend: +{mem_trend:.2f}%/check)")

        # Warning: Error trend
        if current.error_count >= ERROR_RATE_WARNING:
            problems.append(f"WARNING: Elevated error rate: {current.error_count}/min")

        # Warning: CPU sustained high
        if current.cpu_percent > CPU_SPIKE_THRESHOLD:
            problems.append(f"WARNING: High CPU: {current.cpu_percent:.1f}%")

        # Thermal checks
        if current.cpu_temp_c is not None:
            if current.cpu_temp_c >= 95:
                problems.append(f"CRITICAL: CPU temp emergency {current.cpu_temp_c:.1f}°C")
            elif current.cpu_temp_c >= 90:
                problems.append(f"CRITICAL: CPU temp critical {current.cpu_temp_c:.1f}°C")
            elif current.cpu_temp_c >= 80:
                problems.append(f"WARNING: CPU temp elevated {current.cpu_temp_c:.1f}°C")

        # Disk usage checks
        if current.disk_usage:
            for path, pct in current.disk_usage.items():
                if pct >= 95:
                    problems.append(f"CRITICAL: Disk {path} at {pct:.1f}%")
                elif pct >= 90:
                    problems.append(f"CRITICAL: Disk {path} at {pct:.1f}%")
                elif pct >= 85:
                    problems.append(f"WARNING: Disk {path} at {pct:.1f}%")

        # I/O pressure checks
        if current.io_pressure_avg10 is not None:
            if current.io_pressure_avg10 > 80:
                problems.append(f"CRITICAL: I/O pressure avg10={current.io_pressure_avg10:.1f}")
            elif current.io_pressure_avg10 > 50:
                problems.append(f"WARNING: I/O pressure avg10={current.io_pressure_avg10:.1f}")

        # Swap usage checks
        if current.swap_percent is not None:
            if current.swap_percent > 80:
                problems.append(f"CRITICAL: Swap usage {current.swap_percent:.1f}%")
            elif current.swap_percent > 50:
                problems.append(f"WARNING: Swap usage {current.swap_percent:.1f}%")

        return problems

    def _calculate_trend(self, history: List[Dict], metric: str) -> float:
        """Calculate trend of a metric over recent history."""
        if len(history) < 2:
            return 0

        recent = history[-6:]  # Last 6 samples
        values = [h.get(metric, 0) for h in recent]

        if len(values) < 2:
            return 0

        # Simple linear trend
        n = len(values)
        avg_x = (n - 1) / 2
        avg_y = sum(values) / n

        numerator = sum((i - avg_x) * (v - avg_y) for i, v in enumerate(values))
        denominator = sum((i - avg_x) ** 2 for i in range(n))

        if denominator == 0:
            return 0

        return numerator / denominator

    def _handle_feature_problem(self, feature: FeatureRecord, problems: List[str]):
        """Handle detected problems with a feature."""
        is_critical = any("CRITICAL" in p for p in problems)

        # FIX MEDIUM #7: Special handling for features during revalidation
        if feature.status == FeatureStatus.REVALIDATING:
            LOG.error(f"Feature #{feature.feature_id} FAILED revalidation: {problems}")
            feature.status = FeatureStatus.QUARANTINED
            feature.issues.append(f"REVALIDATION_FAILED: {problems}")
            self._quarantine_feature(feature)
            self._notify_user(
                f"Feature '{feature.feature_name}' failed revalidation.",
                "critical"
            )
            # Clear revalidation state
            with self._revalidation_lock:
                if self._revalidating_feature == feature.feature_id:
                    self._revalidating_feature = None
            return

        if is_critical:
            LOG.error(f"CRITICAL problem in feature #{feature.feature_id}")
            # Attempt auto-repair before escalating to full emergency response
            try:
                from .detector import Anomaly, AnomalySeverity
                anomaly_objs = []
                for p in problems:
                    sev = AnomalySeverity.CRITICAL if "CRITICAL" in p else AnomalySeverity.WARNING
                    anomaly_objs.append(Anomaly(type=p.split(":")[0].strip().lower().replace(" ", "_"),
                                                severity=sev,
                                                details={"problem": p, "feature_id": feature.feature_id}))
                repair_actions = self.auto_repair.attempt_repair(anomaly_objs)
                if repair_actions:
                    LOG.info(f"Auto-repair proposed {len(repair_actions)} actions for feature #{feature.feature_id}")
            except Exception as exc:
                LOG.warning(f"Auto-repair attempt failed: {exc}")
            self._emergency_response(feature, problems)
        else:
            # Warning - increase suspicion but don't rollback yet
            feature.confidence_score = max(0, feature.confidence_score - 10)
            if feature.confidence_score <= 0:
                LOG.warning(f"Feature #{feature.feature_id} confidence depleted - initiating rollback")
                self._emergency_response(feature, problems)

    def _emergency_response(self, trigger_feature: FeatureRecord, problems: List[str]):
        """Emergency response: identify and rollback problematic features."""
        LOG.error("=" * 60)
        LOG.error("EMERGENCY RESPONSE ACTIVATED")
        LOG.error(f"Trigger: Feature #{trigger_feature.feature_id} - {trigger_feature.feature_name}")
        LOG.error(f"Problems: {problems}")
        LOG.error("=" * 60)

        # Get all suspect features (integrated in last 24h)
        suspects = self.registry.get_suspects()

        if not suspects:
            LOG.error("No suspect features found - manual intervention required")
            self._notify_user("CRITICAL: System problems detected, but no suspect features found.", "critical")
            return

        LOG.info(f"Identified {len(suspects)} suspect features")

        # Try to correlate with specific feature first
        error_location = self._get_error_location()
        if error_location:
            LOG.info(f"Error location detected: {error_location}")
            # Re-sort suspects by correlation
            suspects = self.registry.get_suspects(error_location)

        # If only one suspect and high confidence it's the culprit
        if len(suspects) == 1 or (error_location and suspects[0].modified_files):
            culprit = suspects[0]
            LOG.info(f"High confidence culprit: Feature #{culprit.feature_id}")
            self._rollback_feature(culprit)
            self._notify_user(
                f"Feature '{culprit.feature_name}' identified as problem cause and rolled back.",
                "critical"
            )
        else:
            # Multiple suspects - rollback all, then revalidate
            LOG.info("Multiple suspects - initiating mass rollback with revalidation")
            self._mass_rollback_with_revalidation(suspects, problems)

    def _mass_rollback_with_revalidation(self, suspects: List[FeatureRecord], problems: List[str]):
        """Rollback all suspects, then revalidate one by one."""
        LOG.info(f"Rolling back {len(suspects)} features for analysis")

        # Phase 1: Rollback all
        for feature in suspects:
            self._rollback_feature(feature, temporary=True)

        # Wait for system to stabilize
        LOG.info("Waiting for system stabilization...")
        time.sleep(30)

        # Check if system is stable now
        current = self._capture_metrics()
        all_services_ok = all(current.services.values())

        if not all_services_ok:
            LOG.error("System still unstable after mass rollback - manual intervention required")
            self._notify_user(
                "CRITICAL: System unstable despite rollback. Manual intervention required.",
                "critical"
            )
            return

        LOG.info("System stabilized - starting revalidation")

        # Phase 2: Queue features for revalidation (oldest first)
        # FIX HIGH #5: Use lock when modifying revalidation queue
        with self._revalidation_lock:
            self._revalidation_queue = [f.feature_id for f in sorted(suspects, key=lambda x: x.integrated_at)]

        self._notify_user(
            f"{len(suspects)} features rolled back. "
            f"Automatic revalidation starting to identify the faulty feature.",
            "critical"
        )

    def _process_revalidation(self):
        """Process the revalidation queue."""
        # FIX HIGH #5: Use lock for thread-safe access to revalidation state
        with self._revalidation_lock:
            if self._revalidating_feature is not None:
                # Already revalidating - check if done
                feature = self.registry.get_feature(self._revalidating_feature)
                if feature and feature.status != FeatureStatus.REVALIDATING:
                    # Revalidation complete (success or failure handled in _check_feature)
                    self._revalidating_feature = None
                return

            if not self._revalidation_queue:
                return

            # Start next revalidation
            feature_id = self._revalidation_queue.pop(0)

        # Release lock before potentially slow operations
        feature = self.registry.get_feature(feature_id)

        if not feature:
            return

        LOG.info(f"Starting revalidation of feature #{feature_id}: {feature.feature_name}")

        # Restore the feature
        self._restore_feature(feature)

        # Set to revalidating status
        feature.status = FeatureStatus.REVALIDATING
        feature.baseline_metrics = self._capture_metrics().to_dict()

        # FIX HIGH #5: Update shared state under lock
        with self._revalidation_lock:
            self._revalidation_start = time.time()
            self._revalidating_feature = feature_id

        self.registry.save()

        LOG.info(f"Feature #{feature_id} restored - monitoring for {REVALIDATION_DURATION}s")

    def _rollback_feature(self, feature: FeatureRecord, temporary: bool = False):
        """Rollback a specific feature."""
        LOG.info(f"Rolling back feature #{feature.feature_id}: {feature.feature_name}")

        try:
            baseline_dir = Path(feature.baseline_dir)
            if not baseline_dir.exists():
                LOG.error(f"Baseline directory not found: {baseline_dir}")
                return

            # Find backup files
            for backup_file in baseline_dir.glob("*.py"):
                # Determine original location
                # Files are stored with original name in baseline dir
                original_name = backup_file.name

                # Find where this file came from
                possible_locations = [
                    _ASRS_DAEMON_ROOT / "core" / original_name,
                    _ASRS_DAEMON_ROOT / "tools" / original_name,
                    _ASRS_DAEMON_ROOT / "services" / original_name,
                ]

                for original_path in possible_locations:
                    if original_path.exists():
                        LOG.info(f"Restoring {original_path} from backup")
                        shutil.copy2(backup_file, original_path)
                        break

            # Update feature status
            if temporary:
                feature.status = FeatureStatus.ROLLED_BACK
            else:
                feature.status = FeatureStatus.QUARANTINED
                self._quarantine_feature(feature)

            self.registry.save()

            # Restart affected services
            self._restart_services()

            LOG.info(f"Feature #{feature.feature_id} rolled back successfully")

        except Exception as e:
            LOG.error(f"Rollback failed for feature #{feature.feature_id}: {e}")

    def _restore_feature(self, feature: FeatureRecord):
        """Restore a rolled-back feature for revalidation."""
        LOG.info(f"Restoring feature #{feature.feature_id} for revalidation")

        # Find the feature's integration backup (not baseline)
        # The feature code should be in a separate integration record
        # For now, we just mark it as restored - actual restore depends on how
        # features are integrated

        # In a full implementation, this would:
        # 1. Re-apply the feature's code changes
        # 2. Or re-enable a feature flag

        feature.issues.clear()
        feature.metrics_history.clear()

    def _quarantine_feature(self, feature: FeatureRecord):
        """Move a feature to quarantine."""
        LOG.info(f"Quarantining feature #{feature.feature_id}")

        quarantine_dir = QUARANTINE_DIR / f"feature_{feature.feature_id}_{int(time.time())}"
        quarantine_dir.mkdir(parents=True, exist_ok=True)

        # Save quarantine report
        report = {
            "feature_id": feature.feature_id,
            "feature_name": feature.feature_name,
            "quarantined_at": time.time(),
            "reason": feature.issues,
            "metrics_at_failure": feature.metrics_history[-10:] if feature.metrics_history else [],
            "integrated_at": feature.integrated_at,
            "time_to_failure": time.time() - feature.integrated_at,
        }

        (quarantine_dir / "quarantine_report.json").write_text(json.dumps(report, indent=2))

        LOG.info(f"Quarantine report saved to {quarantine_dir}")

    def _restart_services(self):
        """Restart critical services after rollback."""
        LOG.info("Restarting critical services...")

        for service in self.CRITICAL_SERVICES:
            try:
                subprocess.run(
                    ["systemctl", "--user", "restart", service],
                    capture_output=True, timeout=30
                )
                LOG.info(f"Restarted {service}")
            except Exception as e:
                LOG.error(f"Failed to restart {service}: {e}")

    def _get_error_location(self) -> Optional[str]:
        """Try to determine where the error occurred."""
        try:
            # Check recent journal for error locations
            result = subprocess.run(
                ["journalctl", "--user", "--since", "5 minutes ago",
                 "-p", "err", "--no-pager", "-o", "cat"],
                capture_output=True, text=True, timeout=10
            )

            # Look for file/line references in error messages
            for line in result.stdout.split('\n'):
                if 'File "' in line and '.py"' in line:
                    # Extract file path
                    start = line.find('File "') + 6
                    end = line.find('"', start)
                    if end > start:
                        return line[start:end]

        except Exception as e:
            LOG.warning(f"Could not determine error location: {e}")

        return None

    def _capture_metrics(self) -> SystemMetrics:
        """Capture current system metrics."""
        # Memory
        memory_percent = 0.0
        memory_mb = 0.0
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
                memory_percent = (used / total) * 100
                memory_mb = used / 1024
        except Exception:
            pass

        # CPU / Load
        cpu_percent = 0.0
        load_average = 0.0
        try:
            with open('/proc/loadavg') as f:
                parts = f.read().split()
                load_average = float(parts[0])
                cpu_count = os.cpu_count() or 1
                cpu_percent = (load_average / cpu_count) * 100
        except Exception:
            pass

        # Error count — exclude systemd service start/stop messages
        # (ASRS's own restarts during rollback/revalidation generate these)
        error_count = 0
        try:
            result = subprocess.run(
                ["journalctl", "--user", "--since", "1 minute ago",
                 "-p", "err", "--no-pager", "-q"],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                # Skip systemd service lifecycle messages (caused by ASRS restarts)
                if 'systemd[' in line and ('Failed to start' in line or
                    'Stopped' in line or 'Starting' in line or
                    'Start request repeated' in line):
                    continue
                error_count += 1
        except Exception:
            pass

        # Services
        services = {}
        for service in self.CRITICAL_SERVICES:
            try:
                result = subprocess.run(
                    ["systemctl", "--user", "is-active", service],
                    capture_output=True, text=True, timeout=3
                )
                services[service] = result.stdout.strip() == "active"
            except Exception:
                services[service] = False

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
            for mount_path in ["/", str(Path.home()), str(_ASRS_DAEMON_ROOT.parent.parent)]:
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

        # Swap percent
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

        return SystemMetrics(
            timestamp=time.time(),
            memory_percent=memory_percent,
            memory_mb=memory_mb,
            cpu_percent=cpu_percent,
            load_average=load_average,
            error_count=error_count,
            services=services,
            cpu_temp_c=cpu_temp_c,
            disk_usage=disk_usage if disk_usage else None,
            io_pressure_avg10=io_pressure_avg10,
            swap_percent=swap_percent,
        )

    def _notify_user(self, message: str, urgency: str = "normal"):
        """Send notification to user."""
        # Desktop notification
        try:
            icon = "dialog-warning" if urgency == "critical" else "dialog-information"
            subprocess.run([
                "notify-send",
                "-u", urgency,
                "-i", icon,
                "🛡️ A.S.R.S.",
                message
            ], timeout=5)
        except Exception:
            pass

        # Log
        LOG.info(f"USER NOTIFICATION [{urgency}]: {message}")

        # Try Frank event socket
        try:
            if NOTIFY_SOCKET.exists():
                notification = {
                    "type": "asrs_notification",
                    "message": message,
                    "urgency": urgency,
                    "timestamp": time.time(),
                }
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                sock.sendto(json.dumps(notification).encode(), str(NOTIFY_SOCKET))
                sock.close()
        except Exception:
            pass

    def _run_socket_listener(self):
        """Listen for commands on Unix socket."""
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()

        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(str(SOCKET_PATH))
            sock.listen(5)
            sock.settimeout(1.0)

            LOG.info(f"Socket listener on {SOCKET_PATH}")

            while self.running:
                conn = None
                try:
                    conn, _ = sock.accept()
                    # FIX HIGH #6: Handle decode errors
                    raw_data = conn.recv(4096)
                    try:
                        data = raw_data.decode('utf-8')
                    except UnicodeDecodeError as e:
                        LOG.warning(f"Socket decode error: {e}")
                        response = json.dumps({"status": "error", "message": "Invalid encoding"})
                        conn.send(response.encode())
                        continue

                    response = self._handle_command(data)
                    conn.send(response.encode())
                except socket.timeout:
                    continue
                except Exception as e:
                    LOG.error(f"Socket error: {e}")
                finally:
                    # FIX HIGH #6: Always close connection in finally block
                    if conn is not None:
                        try:
                            conn.close()
                        except Exception:
                            pass

        finally:
            sock.close()
            if SOCKET_PATH.exists():
                SOCKET_PATH.unlink()

    def _handle_command(self, data: str) -> str:
        """Handle incoming command."""
        try:
            cmd = json.loads(data)
            action = cmd.get("action")

            if action == "status":
                active = self.registry.get_active_features()
                return json.dumps({
                    "status": "ok",
                    "active_features": len(active),
                    "revalidation_queue": len(self._revalidation_queue),
                    "revalidating": self._revalidating_feature,
                    "features": [f.to_dict() for f in active],
                })

            elif action == "monitor":
                feature_ids = cmd.get("feature_ids", [])
                features_data = cmd.get("features", [])
                for i, fid in enumerate(feature_ids):
                    fdata = features_data[i] if i < len(features_data) else {}
                    self._start_feature_monitoring(fid, fdata)
                return json.dumps({"status": "ok", "message": f"Monitoring {len(feature_ids)} features"})

            elif action == "list":
                all_features = list(self.registry.features.values())
                return json.dumps({
                    "status": "ok",
                    "features": [f.to_dict() for f in all_features],
                })

            elif action == "quarantine":
                return json.dumps({
                    "status": "ok",
                    "quarantined": [
                        f.to_dict() for f in self.registry.features.values()
                        if f.status == FeatureStatus.QUARANTINED
                    ],
                })

            else:
                return json.dumps({"status": "error", "message": "Unknown action"})

        except Exception as e:
            return json.dumps({"status": "error", "message": str(e)})

    def _cleanup_loop(self):
        """Periodic cleanup of old baselines."""
        while self.running:
            try:
                self._cleanup_old_baselines()
            except Exception as e:
                LOG.error(f"Cleanup error: {e}")

            # FIX HIGH #4: Use Event.wait instead of sleep loop for clean shutdown
            # Run cleanup once per hour, but wake up immediately on shutdown
            if self._stop_event.wait(timeout=3600):
                # Event was set - shutdown requested
                break

    def _cleanup_old_baselines(self):
        """Remove baselines older than retention period."""
        cutoff = time.time() - (BASELINE_RETENTION_DAYS * 86400)

        for item in BACKUP_DIR.iterdir():
            if item.is_dir() and item.name.startswith(("feature_", "monitoring_")):
                try:
                    if item.stat().st_mtime < cutoff:
                        shutil.rmtree(item)
                        LOG.info(f"Cleaned up old baseline: {item.name}")
                except Exception as e:
                    LOG.warning(f"Cleanup failed for {item}: {e}")


def main():
    daemon = ASRSDaemon()
    daemon.start()


if __name__ == "__main__":
    main()
