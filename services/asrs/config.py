#!/usr/bin/env python3
"""
A.S.R.S. Configuration
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import json


try:
    from config.paths import get_db as _asrs_get_db, ASRS_BACKUP_DIR as _ASRS_BACKUP_DIR, AICORE_LOG as _ASRS_LOG, AICORE_ROOT as _ASRS_ROOT
    _ASRS_DB_PATH = _asrs_get_db("fas_scavenger")
    _ASRS_REPORTS_DIR = _ASRS_LOG / "asrs_reports"
    _ASRS_CONFIG_FILE = _ASRS_ROOT / "config" / "asrs_config.json"
except ImportError:
    _ASRS_DB_PATH = Path("/home/ai-core-node/aicore/database/fas_scavenger.db")
    _ASRS_BACKUP_DIR = Path("/home/ai-core-node/aicore/database/asrs_backups")
    _ASRS_REPORTS_DIR = Path("/home/ai-core-node/aicore/logs/asrs_reports")
    _ASRS_CONFIG_FILE = Path("/home/ai-core-node/aicore/opt/aicore/config/asrs_config.json")


@dataclass
class ASRSConfig:
    """Configuration for Autonomous Safety Recovery System."""

    # Paths
    db_path: Path = field(default_factory=lambda: _ASRS_DB_PATH)
    backup_dir: Path = field(default_factory=lambda: _ASRS_BACKUP_DIR)
    reports_dir: Path = field(default_factory=lambda: _ASRS_REPORTS_DIR)

    # Observation Window
    observation_window_sec: int = 300  # 5 minutes after integration
    check_interval_sec: int = 10       # Check every 10 seconds

    # Thresholds for anomaly detection
    memory_spike_threshold: float = 1.3      # 30% more than baseline
    memory_leak_threshold: float = 1.1       # 10% increase over time
    cpu_spike_threshold: int = 90            # 90% CPU
    cpu_spike_duration_sec: int = 30         # For 30+ seconds
    error_rate_multiplier: float = 3.0       # 3x more errors than normal
    response_time_threshold_ms: int = 5000   # 5 second timeout
    crash_threshold: int = 1                 # 1 crash = critical

    # Thermal thresholds (Celsius)
    thermal_warning_c: int = 80              # >=80°C warning
    thermal_critical_c: int = 90             # >=90°C critical
    thermal_emergency_c: int = 95            # >=95°C emergency

    # Disk usage thresholds (percent)
    disk_warning_percent: int = 85           # >=85% warning
    disk_critical_percent: int = 90          # >=90% critical
    disk_emergency_percent: int = 95         # >=95% emergency

    # I/O pressure thresholds (PSI avg10)
    io_pressure_warning: float = 50.0        # >50 warning
    io_pressure_critical: float = 80.0       # >80 critical

    # Swap usage thresholds (percent)
    swap_warning_percent: int = 50           # >50% warning
    swap_critical_percent: int = 80          # >80% critical

    # Rollback settings
    auto_rollback_on_critical: bool = True
    rollback_timeout_sec: int = 60

    # Quarantine settings
    max_quarantine_retries: int = 3
    quarantine_cooldown_hours: int = 24

    # Retry settings
    enable_auto_retry: bool = True
    retry_delay_minutes: int = 30
    max_auto_retries: int = 2

    # Escalation
    escalate_after_retries: int = 2
    notify_user_on_failure: bool = True

    # Services to monitor
    critical_services: List[str] = field(default_factory=lambda: [
        "aicore-core.service",
        "aicore-router.service",
        "aicore-llama3-gpu.service",
        "aicore-toolboxd.service",
    ])

    # Metrics collection
    metrics_history_size: int = 100  # Keep last 100 measurements

    def __post_init__(self):
        """Ensure directories exist."""
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "db_path": str(self.db_path),
            "backup_dir": str(self.backup_dir),
            "reports_dir": str(self.reports_dir),
            "observation_window_sec": self.observation_window_sec,
            "check_interval_sec": self.check_interval_sec,
            "memory_spike_threshold": self.memory_spike_threshold,
            "memory_leak_threshold": self.memory_leak_threshold,
            "cpu_spike_threshold": self.cpu_spike_threshold,
            "cpu_spike_duration_sec": self.cpu_spike_duration_sec,
            "error_rate_multiplier": self.error_rate_multiplier,
            "response_time_threshold_ms": self.response_time_threshold_ms,
            "crash_threshold": self.crash_threshold,
            "thermal_warning_c": self.thermal_warning_c,
            "thermal_critical_c": self.thermal_critical_c,
            "thermal_emergency_c": self.thermal_emergency_c,
            "disk_warning_percent": self.disk_warning_percent,
            "disk_critical_percent": self.disk_critical_percent,
            "disk_emergency_percent": self.disk_emergency_percent,
            "io_pressure_warning": self.io_pressure_warning,
            "io_pressure_critical": self.io_pressure_critical,
            "swap_warning_percent": self.swap_warning_percent,
            "swap_critical_percent": self.swap_critical_percent,
            "auto_rollback_on_critical": self.auto_rollback_on_critical,
            "max_quarantine_retries": self.max_quarantine_retries,
            "enable_auto_retry": self.enable_auto_retry,
            "retry_delay_minutes": self.retry_delay_minutes,
            "notify_user_on_failure": self.notify_user_on_failure,
            "critical_services": self.critical_services,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "ASRSConfig":
        """Create from dictionary."""
        if "db_path" in data:
            data["db_path"] = Path(data["db_path"])
        if "backup_dir" in data:
            data["backup_dir"] = Path(data["backup_dir"])
        if "reports_dir" in data:
            data["reports_dir"] = Path(data["reports_dir"])
        return cls(**data)


# Singleton
_config: Optional[ASRSConfig] = None


def get_asrs_config() -> ASRSConfig:
    """Get or create ASRS config singleton."""
    global _config
    if _config is None:
        config_file = _ASRS_CONFIG_FILE
        if config_file.exists():
            try:
                data = json.loads(config_file.read_text())
                _config = ASRSConfig.from_dict(data)
            except Exception:
                _config = ASRSConfig()
        else:
            _config = ASRSConfig()
    return _config


def save_asrs_config(config: ASRSConfig):
    """Save ASRS config to file."""
    config_file = _ASRS_CONFIG_FILE
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(config.to_dict(), indent=2))
