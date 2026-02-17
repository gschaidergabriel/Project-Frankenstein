#!/usr/bin/env python3
"""
A.S.R.S. Baseline Manager
Creates and manages system snapshots before feature integration.
"""

import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

from .config import ASRSConfig, get_asrs_config

LOG = logging.getLogger("asrs.baseline")


@dataclass
class SystemMetrics:
    """System metrics at a point in time."""
    timestamp: str
    memory_used_mb: float
    memory_percent: float
    cpu_percent: float
    load_average: float
    error_rate_per_min: float
    service_states: Dict[str, str]
    response_times_ms: Dict[str, float]

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "memory_used_mb": self.memory_used_mb,
            "memory_percent": self.memory_percent,
            "cpu_percent": self.cpu_percent,
            "load_average": self.load_average,
            "error_rate_per_min": self.error_rate_per_min,
            "service_states": self.service_states,
            "response_times_ms": self.response_times_ms,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "SystemMetrics":
        return cls(**data)


@dataclass
class Baseline:
    """Complete system baseline before integration."""
    id: str
    feature_id: int
    created_at: str

    # File backups
    file_backups: Dict[str, str] = field(default_factory=dict)  # path -> backup_path
    file_checksums: Dict[str, str] = field(default_factory=dict)  # path -> sha256

    # Config state
    config_state: Dict[str, Any] = field(default_factory=dict)

    # Service state
    service_states: Dict[str, str] = field(default_factory=dict)

    # Affected files/services (to be filled during integration)
    affected_files: List[str] = field(default_factory=list)
    affected_services: List[str] = field(default_factory=list)

    # Baseline metrics
    baseline_metrics: Optional[SystemMetrics] = None

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "feature_id": self.feature_id,
            "created_at": self.created_at,
            "file_backups": self.file_backups,
            "file_checksums": self.file_checksums,
            "config_state": self.config_state,
            "service_states": self.service_states,
            "affected_files": self.affected_files,
            "affected_services": self.affected_services,
            "baseline_metrics": self.baseline_metrics.to_dict() if self.baseline_metrics else None,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Baseline":
        metrics = None
        if data.get("baseline_metrics"):
            metrics = SystemMetrics.from_dict(data["baseline_metrics"])
        return cls(
            id=data["id"],
            feature_id=data["feature_id"],
            created_at=data["created_at"],
            file_backups=data.get("file_backups", {}),
            file_checksums=data.get("file_checksums", {}),
            config_state=data.get("config_state", {}),
            service_states=data.get("service_states", {}),
            affected_files=data.get("affected_files", []),
            affected_services=data.get("affected_services", []),
            baseline_metrics=metrics,
        )


class BaselineManager:
    """Creates and manages system baselines."""

    def __init__(self, config: ASRSConfig = None):
        self.config = config or get_asrs_config()
        self._baselines: Dict[str, Baseline] = {}

    def create_baseline(self, feature_id: int, files_to_modify: List[str] = None,
                        services_affected: List[str] = None) -> Baseline:
        """
        Create a complete system baseline before integration.

        Args:
            feature_id: ID of the feature being integrated
            files_to_modify: List of file paths that will be modified
            services_affected: List of services that may be affected

        Returns:
            Baseline object with all snapshots
        """
        baseline_id = f"baseline_{feature_id}_{int(time.time())}"
        LOG.info(f"Creating baseline {baseline_id} for feature #{feature_id}")

        files_to_modify = files_to_modify or []
        services_affected = services_affected or self.config.critical_services

        baseline = Baseline(
            id=baseline_id,
            feature_id=feature_id,
            created_at=datetime.now().isoformat(),
            affected_files=files_to_modify,
            affected_services=services_affected,
        )

        # 1. Backup files
        baseline.file_backups, baseline.file_checksums = self._backup_files(
            baseline_id, files_to_modify
        )

        # 2. Capture config state
        baseline.config_state = self._capture_config_state()

        # 3. Capture service states
        baseline.service_states = self._get_service_states(services_affected)

        # 4. Capture baseline metrics
        baseline.baseline_metrics = self._capture_metrics()

        # Store baseline
        self._baselines[baseline_id] = baseline
        self._save_baseline_to_disk(baseline)

        LOG.info(f"Baseline {baseline_id} created successfully")
        return baseline

    def get_baseline(self, baseline_id: str) -> Optional[Baseline]:
        """Get a baseline by ID."""
        if baseline_id in self._baselines:
            return self._baselines[baseline_id]
        return self._load_baseline_from_disk(baseline_id)

    def _backup_files(self, baseline_id: str, files: List[str]) -> tuple:
        """Backup files and compute checksums."""
        backups = {}
        checksums = {}

        backup_dir = self.config.backup_dir / baseline_id
        backup_dir.mkdir(parents=True, exist_ok=True)

        for file_path in files:
            path = Path(file_path)
            if not path.exists():
                LOG.warning(f"File {file_path} does not exist, skipping backup")
                continue

            try:
                # Compute checksum
                checksums[file_path] = self._compute_checksum(path)

                # Create backup
                backup_path = backup_dir / path.name
                # Handle duplicate names by adding hash suffix
                if backup_path.exists():
                    backup_path = backup_dir / f"{path.stem}_{checksums[file_path][:8]}{path.suffix}"

                shutil.copy2(path, backup_path)
                backups[file_path] = str(backup_path)
                LOG.debug(f"Backed up {file_path} -> {backup_path}")

            except Exception as e:
                LOG.error(f"Failed to backup {file_path}: {e}")

        return backups, checksums

    def _compute_checksum(self, path: Path) -> str:
        """Compute SHA256 checksum of a file."""
        sha256 = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _capture_config_state(self) -> Dict:
        """Capture current configuration state."""
        config_state = {}

        # Capture systemd user service configs
        user_service_dir = Path.home() / ".config/systemd/user"
        if user_service_dir.exists():
            config_state["systemd_services"] = {}
            for service_file in user_service_dir.glob("aicore-*.service"):
                try:
                    config_state["systemd_services"][service_file.name] = service_file.read_text()
                except Exception as e:
                    LOG.warning(f"Could not read {service_file}: {e}")

        # Capture key config files
        try:
            from config.paths import AICORE_ROOT as _bl_root
        except ImportError:
            _bl_root = Path(__file__).resolve().parents[2]
        config_files = [
            _bl_root / "config" / "fas_popup_config.py",
            _bl_root / "config" / "asrs_config.json",
        ]
        config_state["config_files"] = {}
        for cfg_file in config_files:
            if cfg_file.exists():
                try:
                    config_state["config_files"][str(cfg_file)] = cfg_file.read_text()
                except Exception:
                    pass

        return config_state

    def _get_service_states(self, services: List[str]) -> Dict[str, str]:
        """Get current state of services."""
        states = {}
        for service in services:
            try:
                result = subprocess.run(
                    ["systemctl", "--user", "is-active", service],
                    capture_output=True, text=True, timeout=5
                )
                states[service] = result.stdout.strip()
            except Exception as e:
                states[service] = f"error: {e}"
        return states

    def _capture_metrics(self) -> SystemMetrics:
        """Capture current system metrics."""
        # Memory
        memory_used_mb = 0.0
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
                memory_used_mb = used / 1024
                memory_percent = (used / total) * 100
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

        # Error rate from journal
        error_rate = self._get_error_rate()

        # Service states
        service_states = self._get_service_states(self.config.critical_services)

        # Response times
        response_times = self._measure_response_times()

        return SystemMetrics(
            timestamp=datetime.now().isoformat(),
            memory_used_mb=memory_used_mb,
            memory_percent=memory_percent,
            cpu_percent=cpu_percent,
            load_average=load_average,
            error_rate_per_min=error_rate,
            service_states=service_states,
            response_times_ms=response_times,
        )

    def _get_error_rate(self) -> float:
        """Get error rate from journal (errors per minute)."""
        try:
            result = subprocess.run(
                ["journalctl", "--user", "--since", "1 minute ago",
                 "-p", "err", "--no-pager", "-q"],
                capture_output=True, text=True, timeout=10
            )
            lines = [l for l in result.stdout.strip().split('\n') if l]
            return float(len(lines))
        except Exception:
            return 0.0

    def _measure_response_times(self) -> Dict[str, float]:
        """Measure response times of critical services."""
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
                response_times[name] = -1  # Unreachable

        return response_times

    def _save_baseline_to_disk(self, baseline: Baseline):
        """Save baseline metadata to disk."""
        meta_file = self.config.backup_dir / baseline.id / "metadata.json"
        meta_file.parent.mkdir(parents=True, exist_ok=True)
        meta_file.write_text(json.dumps(baseline.to_dict(), indent=2))

    def _load_baseline_from_disk(self, baseline_id: str) -> Optional[Baseline]:
        """Load baseline from disk."""
        meta_file = self.config.backup_dir / baseline_id / "metadata.json"
        if not meta_file.exists():
            return None
        try:
            data = json.loads(meta_file.read_text())
            baseline = Baseline.from_dict(data)
            self._baselines[baseline_id] = baseline
            return baseline
        except Exception as e:
            LOG.error(f"Failed to load baseline {baseline_id}: {e}")
            return None

    def cleanup_old_baselines(self, keep_days: int = 7):
        """Remove baselines older than specified days."""
        import time
        cutoff = time.time() - (keep_days * 86400)

        for baseline_dir in self.config.backup_dir.iterdir():
            if baseline_dir.is_dir():
                try:
                    # Check creation time
                    if baseline_dir.stat().st_mtime < cutoff:
                        shutil.rmtree(baseline_dir)
                        LOG.info(f"Cleaned up old baseline: {baseline_dir.name}")
                except Exception as e:
                    LOG.warning(f"Could not clean up {baseline_dir}: {e}")
