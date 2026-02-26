#!/usr/bin/env python3
"""
A.S.R.S. Rollback Executor
Handles automatic rollback when integration fails.
"""

import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional
import logging

from .config import ASRSConfig, get_asrs_config
from .baseline import Baseline

LOG = logging.getLogger("asrs.rollback")


class RollbackLevel(Enum):
    """Levels of rollback severity."""
    SOFT = "soft"          # Disable feature, reload configs
    HARD = "hard"          # Restore files, restart services
    EMERGENCY = "emergency" # Full revert, safe mode


@dataclass
class RollbackResult:
    """Result of a rollback operation."""
    success: bool
    level: RollbackLevel
    timestamp: str
    files_restored: List[str]
    services_restarted: List[str]
    errors: List[str]
    duration_sec: float

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "level": self.level.value,
            "timestamp": self.timestamp,
            "files_restored": self.files_restored,
            "services_restarted": self.services_restarted,
            "errors": self.errors,
            "duration_sec": self.duration_sec,
        }


class RollbackExecutor:
    """
    Executes rollback operations to restore system stability.
    """

    def __init__(self, config: ASRSConfig = None):
        self.config = config or get_asrs_config()

    def execute(self, baseline: Baseline, level: RollbackLevel = RollbackLevel.HARD,
                feature_id: int = None) -> RollbackResult:
        """
        Execute rollback to restore system to baseline state.

        Args:
            baseline: The baseline to restore to
            level: Severity level of rollback
            feature_id: Optional feature ID for logging

        Returns:
            RollbackResult with details of what was done
        """
        start_time = time.time()
        LOG.warning(f"Starting {level.value} rollback for baseline {baseline.id}")

        files_restored = []
        services_restarted = []
        errors = []

        try:
            if level == RollbackLevel.SOFT:
                # Soft rollback: just disable and reload
                self._disable_feature(feature_id, errors)
                self._reload_configs(baseline, errors)

            elif level == RollbackLevel.HARD:
                # Hard rollback: restore files and restart
                self._disable_feature(feature_id, errors)
                files_restored = self._restore_files(baseline, errors)
                self._restore_configs(baseline, errors)
                services_restarted = self._restart_services(baseline, errors)
                self._clear_caches(errors)

            elif level == RollbackLevel.EMERGENCY:
                # Emergency: everything plus safe mode
                self._disable_feature(feature_id, errors)
                files_restored = self._restore_files(baseline, errors)
                self._restore_configs(baseline, errors)
                services_restarted = self._restart_all_services(errors)
                self._clear_caches(errors)
                self._enter_safe_mode(errors)

            # Verify system health
            health_ok = self._verify_health(baseline)
            if not health_ok:
                errors.append("System health verification failed after rollback")

            success = len(errors) == 0 or (len(files_restored) > 0 and health_ok)

        except Exception as e:
            LOG.error(f"Rollback failed with exception: {e}")
            errors.append(f"Exception: {str(e)}")
            success = False

        duration = time.time() - start_time

        result = RollbackResult(
            success=success,
            level=level,
            timestamp=datetime.now().isoformat(),
            files_restored=files_restored,
            services_restarted=services_restarted,
            errors=errors,
            duration_sec=duration,
        )

        LOG.info(f"Rollback completed: success={success}, duration={duration:.2f}s, "
                 f"files={len(files_restored)}, services={len(services_restarted)}, "
                 f"errors={len(errors)}")

        return result

    def _disable_feature(self, feature_id: Optional[int], errors: List[str]):
        """Mark feature as disabled in database."""
        if feature_id is None:
            return

        try:
            import sqlite3
            conn = sqlite3.connect(str(self.config.db_path), timeout=30)
            conn.execute("""
                UPDATE extracted_features
                SET integration_status = 'rollback',
                    user_approved = 0
                WHERE id = ?
            """, (feature_id,))
            conn.commit()
            conn.close()
            LOG.info(f"Disabled feature #{feature_id}")
        except Exception as e:
            errors.append(f"Failed to disable feature: {e}")
            LOG.error(f"Failed to disable feature #{feature_id}: {e}")

    def _restore_files(self, baseline: Baseline, errors: List[str]) -> List[str]:
        """Restore files from baseline backups."""
        restored = []

        for original_path, backup_path in baseline.file_backups.items():
            try:
                backup = Path(backup_path)
                original = Path(original_path)

                if not backup.exists():
                    errors.append(f"Backup not found: {backup_path}")
                    continue

                # Create backup of current state before restoring (just in case)
                if original.exists():
                    emergency_backup = original.with_suffix(original.suffix + ".pre_rollback")
                    shutil.copy2(original, emergency_backup)

                # Restore from backup
                shutil.copy2(backup, original)
                restored.append(original_path)
                LOG.info(f"Restored {original_path} from {backup_path}")

            except Exception as e:
                errors.append(f"Failed to restore {original_path}: {e}")
                LOG.error(f"Failed to restore {original_path}: {e}")

        return restored

    def _restore_configs(self, baseline: Baseline, errors: List[str]):
        """Restore configuration files."""
        if not baseline.config_state:
            return

        # Restore systemd service configs
        systemd_configs = baseline.config_state.get("systemd_services", {})
        user_service_dir = Path.home() / ".config/systemd/user"

        for filename, content in systemd_configs.items():
            try:
                service_file = user_service_dir / filename
                service_file.write_text(content)
                LOG.debug(f"Restored systemd config: {filename}")
            except Exception as e:
                errors.append(f"Failed to restore {filename}: {e}")

        # Reload systemd if configs were restored
        if systemd_configs:
            try:
                subprocess.run(
                    ["systemctl", "--user", "daemon-reload"],
                    capture_output=True, timeout=30
                )
                LOG.info("Reloaded systemd daemon")
            except Exception as e:
                errors.append(f"Failed to reload systemd: {e}")

    def _reload_configs(self, baseline: Baseline, errors: List[str]):
        """Reload configuration without full restore."""
        try:
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                capture_output=True, timeout=30
            )
        except Exception as e:
            errors.append(f"Failed to reload configs: {e}")

    def _restart_services(self, baseline: Baseline, errors: List[str]) -> List[str]:
        """Restart affected services."""
        restarted = []

        services = baseline.affected_services or self.config.critical_services

        for service in services:
            try:
                result = subprocess.run(
                    ["systemctl", "--user", "restart", service],
                    capture_output=True, text=True, timeout=60
                )
                if result.returncode == 0:
                    restarted.append(service)
                    LOG.info(f"Restarted service: {service}")
                else:
                    errors.append(f"Failed to restart {service}: {result.stderr}")
                    LOG.error(f"Failed to restart {service}: {result.stderr}")

            except subprocess.TimeoutExpired:
                errors.append(f"Timeout restarting {service}")
            except Exception as e:
                errors.append(f"Error restarting {service}: {e}")

        # Wait for services to stabilize
        time.sleep(3)

        return restarted

    def _restart_all_services(self, errors: List[str]) -> List[str]:
        """Restart all critical services (emergency mode)."""
        restarted = []

        for service in self.config.critical_services:
            try:
                # Stop first
                subprocess.run(
                    ["systemctl", "--user", "stop", service],
                    capture_output=True, timeout=30
                )
                time.sleep(1)

                # Then start
                result = subprocess.run(
                    ["systemctl", "--user", "start", service],
                    capture_output=True, text=True, timeout=60
                )

                if result.returncode == 0:
                    restarted.append(service)
                else:
                    errors.append(f"Failed to start {service}")

            except Exception as e:
                errors.append(f"Error with {service}: {e}")

        time.sleep(5)  # Longer wait for emergency restart
        return restarted

    def _clear_caches(self, errors: List[str]):
        """Clear system caches."""
        try:
            # Sync and drop caches
            subprocess.run(["sync"], capture_output=True, timeout=30)
            LOG.debug("Synced filesystem")

            # Clear Python bytecode cache
            try:
                from config.paths import AICORE_ROOT as _rb_root
            except ImportError:
                _rb_root = Path(__file__).resolve().parents[2]
            pycache_dirs = list(_rb_root.rglob("__pycache__"))
            for pycache in pycache_dirs[:10]:  # Limit to prevent long operation
                try:
                    shutil.rmtree(pycache)
                except Exception:
                    pass

            LOG.info("Cleared caches")

        except Exception as e:
            errors.append(f"Failed to clear caches: {e}")

    def _enter_safe_mode(self, errors: List[str]):
        """Enter safe mode (minimal services only)."""
        LOG.warning("Entering safe mode")

        # Create safe mode flag
        try:
            from config.paths import TEMP_FILES as _rb_temp_files
            safe_mode_file = _rb_temp_files["asrs_safe_mode"]
        except ImportError:
            safe_mode_file = Path("/tmp/frank/aicore_safe_mode")
        try:
            safe_mode_file.write_text(datetime.now().isoformat())
        except Exception as e:
            errors.append(f"Failed to create safe mode flag: {e}")

        # Stop non-essential services
        non_essential = [
            "aicore-qwen-gpu.service",
            "frank-training-daemon.service",
            "aicore-fas.service",
        ]

        for service in non_essential:
            try:
                subprocess.run(
                    ["systemctl", "--user", "stop", service],
                    capture_output=True, timeout=30
                )
                LOG.info(f"Stopped non-essential service: {service}")
            except Exception:
                pass

    def _verify_health(self, baseline: Baseline) -> bool:
        """Verify system health after rollback."""
        import socket

        # Check critical services
        for service in self.config.critical_services:
            try:
                result = subprocess.run(
                    ["systemctl", "--user", "is-active", service],
                    capture_output=True, text=True, timeout=5
                )
                if result.stdout.strip() != "active":
                    LOG.warning(f"Service {service} not active after rollback")
                    return False
            except Exception:
                return False

        # Check critical endpoints
        endpoints = [
            ("127.0.0.1", 8088),  # core
            ("127.0.0.1", 8091),  # router
        ]

        for host, port in endpoints:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5.0)
                sock.connect((host, port))
                sock.close()
            except Exception:
                LOG.warning(f"Endpoint {host}:{port} not reachable after rollback")
                return False

        LOG.info("System health verified OK")
        return True

    def quick_rollback(self, feature_id: int, files: List[str]) -> bool:
        """
        Quick rollback for a specific feature without full baseline.
        Used when we just need to undo recent file changes.

        Args:
            feature_id: Feature to rollback
            files: List of files to restore from .pre_rollback backups

        Returns:
            True if successful
        """
        errors = []

        self._disable_feature(feature_id, errors)

        for file_path in files:
            path = Path(file_path)
            backup = path.with_suffix(path.suffix + ".pre_rollback")

            if backup.exists():
                try:
                    shutil.copy2(backup, path)
                    LOG.info(f"Quick restored {file_path}")
                except Exception as e:
                    errors.append(str(e))

        return len(errors) == 0
