#!/usr/bin/env python3
"""
A.S.R.S. Orchestrator
Main coordinator for the Autonomous Safety Recovery System.
"""

import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any
import logging
import json

from .config import ASRSConfig, get_asrs_config
from .baseline import BaselineManager, Baseline
from .watchdog import SystemWatchdog
from .detector import AnomalyDetector, Anomaly
from .rollback import RollbackExecutor, RollbackLevel, RollbackResult
from .quarantine import FeatureQuarantine
from .reporter import ErrorReporter, FailureReport
from .retry import RetryStrategy, Alternative
from .auto_repair import AutoRepairManager

LOG = logging.getLogger("asrs.orchestrator")


class ASRSOrchestrator:
    """
    Main orchestrator for A.S.R.S.
    Coordinates all components for safe feature integration.
    """

    def __init__(self, config: ASRSConfig = None):
        self.config = config or get_asrs_config()

        # Initialize components
        self.baseline_manager = BaselineManager(self.config)
        self.watchdog = SystemWatchdog(self.config)
        self.detector = AnomalyDetector(self.config)
        self.rollback_executor = RollbackExecutor(self.config)
        self.quarantine = FeatureQuarantine(self.config)
        self.reporter = ErrorReporter(self.config)
        self.retry_strategy = RetryStrategy(self.config)
        self.auto_repair = AutoRepairManager()

        # Current integration state
        self._current_baseline: Optional[Baseline] = None
        self._current_feature_id: Optional[int] = None
        self._current_feature_name: str = ""
        # FIX CRITICAL #1: Use RLock to allow same thread to acquire lock multiple times
        # and hold lock for entire integration lifecycle
        self._integration_lock = threading.RLock()
        self._integration_lock_holder: Optional[int] = None  # Thread ID holding the lock

        # Callbacks
        self._on_success: Optional[Callable] = None
        self._on_failure: Optional[Callable] = None
        self._on_rollback: Optional[Callable] = None

        LOG.info("A.S.R.S. Orchestrator initialized")

    def begin_integration(self, feature_id: int, feature_name: str,
                          files_to_modify: List[str] = None,
                          services_affected: List[str] = None,
                          on_success: Callable = None,
                          on_failure: Callable = None,
                          on_rollback: Callable = None) -> Baseline:
        """
        Begin a monitored feature integration.

        Args:
            feature_id: ID of the feature being integrated
            feature_name: Human-readable name
            files_to_modify: List of files that will be modified
            services_affected: List of services that may be affected
            on_success: Callback when integration succeeds
            on_failure: Callback(report, alternatives) when integration fails
            on_rollback: Callback(result) when rollback is performed

        Returns:
            Baseline object for the integration

        Note:
            FIX CRITICAL #1: The lock is acquired here and held for the ENTIRE
            integration lifecycle until _cleanup_integration() is called.
            This prevents race conditions with parallel integrations.
        """
        # FIX CRITICAL #1: Acquire lock for entire integration lifecycle
        self._integration_lock.acquire()
        try:
            if self._current_baseline:
                self._integration_lock.release()
                raise RuntimeError("Integration already in progress")

            self._integration_lock_holder = threading.current_thread().ident

            LOG.info(f"Beginning monitored integration for feature #{feature_id}: {feature_name}")

            # Store callbacks
            self._on_success = on_success
            self._on_failure = on_failure
            self._on_rollback = on_rollback

            # Create baseline
            self._current_baseline = self.baseline_manager.create_baseline(
                feature_id=feature_id,
                files_to_modify=files_to_modify,
                services_affected=services_affected,
            )
            self._current_feature_id = feature_id
            self._current_feature_name = feature_name

            # NOTE: Lock is intentionally NOT released here - it will be released
            # in _cleanup_integration() after the integration completes or fails
            return self._current_baseline
        except Exception as e:
            # Release lock on any error during setup
            if self._integration_lock_holder == threading.current_thread().ident:
                self._integration_lock_holder = None
                self._integration_lock.release()
            raise

    def start_observation(self):
        """
        Start the observation window after integration is complete.
        Call this after the actual integration code has run.
        """
        if not self._current_baseline:
            raise RuntimeError("No integration in progress")

        LOG.info(f"Starting observation for feature #{self._current_feature_id}")

        self.watchdog.start_observation(
            baseline=self._current_baseline,
            on_anomaly=self._handle_anomalies,
            on_complete=self._handle_success,
        )

    def abort_integration(self, reason: str = "Manual abort"):
        """
        Abort the current integration without triggering full failure flow.
        """
        # FIX CRITICAL #1: No need for with-block since we hold the lock
        # during entire integration lifecycle
        if self._current_baseline:
            LOG.warning(f"Aborting integration: {reason}")
            self.watchdog.stop_observation()

            # Quick rollback
            result = self.rollback_executor.execute(
                baseline=self._current_baseline,
                level=RollbackLevel.SOFT,
                feature_id=self._current_feature_id,
            )

            self._cleanup_integration()

    def _capture_visual_context(self, context: str) -> Optional[dict]:
        """Capture error screenshot for visual debugging (rate-limited, non-blocking)."""
        try:
            from tools.vcb_bridge import capture_error_screenshot
            result = capture_error_screenshot(context)
            if result:
                LOG.info(f"Visual context captured: {result.get('screenshot_path', '?')}")
            return result
        except Exception as e:
            LOG.debug(f"Visual context capture failed (non-critical): {e}")
            return None

    def _handle_anomalies(self, raw_anomalies: List[Dict]):
        """Handle detected anomalies from watchdog."""
        LOG.warning(f"Anomalies detected: {len(raw_anomalies)}")

        # Capture visual context for anomaly debugging
        anomaly_types = [a.get("type", "unknown") if isinstance(a, dict) else getattr(a, "type", "unknown")
                         for a in raw_anomalies]
        self._capture_visual_context(f"ASRS anomalies: {', '.join(anomaly_types[:5])}")

        # Convert to Anomaly objects if needed
        anomalies = []
        for a in raw_anomalies:
            if isinstance(a, dict):
                from .detector import Anomaly, AnomalySeverity
                # Convert string severity to enum
                sev_str = a.get('severity', 'warning').upper()
                try:
                    severity = AnomalySeverity[sev_str]
                except KeyError:
                    severity = AnomalySeverity.WARNING
                anomalies.append(Anomaly(
                    type=a.get('type', 'unknown'),
                    severity=severity,
                    details=a,
                ))
            else:
                anomalies.append(a)

        # Determine action
        action = self.detector.get_severity_action(anomalies)
        LOG.info(f"Recommended action: {action}")

        if action in ("rollback", "emergency_rollback"):
            # Attempt auto-repair before triggering rollback
            repair_actions = self.auto_repair.attempt_repair(anomalies)

            if repair_actions and action != "emergency_rollback":
                # Non-emergency: give user up to 120s to approve the repair
                LOG.info(f"Auto-repair proposed {len(repair_actions)} actions — "
                         f"waiting for approval before rollback")
                thread = threading.Thread(
                    target=self._await_repair_or_rollback,
                    args=(anomalies, repair_actions),
                    daemon=True,
                )
                thread.start()
            else:
                # Emergency or no repair actions — rollback immediately
                self._execute_failure_flow(anomalies, action == "emergency_rollback")
        elif action == "warn":
            LOG.warning("Warning-level anomalies detected, continuing observation")

    def _await_repair_or_rollback(self, anomalies, repair_actions):
        """Background thread: wait for repair approval, then verify or rollback."""
        from tools.approval_queue import check_response as _check
        from .auto_repair import RepairStatus

        deadline = time.time() + 120
        approved_any = False

        while time.time() < deadline:
            all_resolved = True
            for action in repair_actions:
                if action.status.value == "pending" and action.request_id:
                    resp = _check(action.request_id, consume=True)
                    if resp and resp.get("decision") == "approved":
                        action.status = RepairStatus.APPROVED
                        self.auto_repair.executor.execute(action)
                        approved_any = True
                    elif resp:
                        action.status = RepairStatus.REJECTED
                    else:
                        all_resolved = False
            if all_resolved:
                break
            time.sleep(3)

        if approved_any:
            # Give repair a moment to take effect, then re-check health
            time.sleep(10)
            issues = self.force_check()
            if not issues:
                LOG.info("Auto-repair resolved the anomalies — skipping rollback")
                return
            LOG.warning("Auto-repair did not resolve anomalies — falling back to rollback")

        self._execute_failure_flow(anomalies, is_emergency=False)

    def _handle_success(self):
        """Handle successful integration (observation complete without critical issues)."""
        LOG.info(f"Integration successful for feature #{self._current_feature_id}")

        # Mark feature as integrated in DB
        self._update_feature_status("integrated")

        # Call success callback
        if self._on_success:
            try:
                self._on_success()
            except Exception as e:
                LOG.error(f"Error in success callback: {e}")

        self._cleanup_integration()

    def _execute_failure_flow(self, anomalies: List[Anomaly], is_emergency: bool = False):
        """Execute the full failure handling flow."""
        LOG.warning(f"Executing failure flow for feature #{self._current_feature_id}")

        # Capture visual context BEFORE rollback (shows the problem state)
        emergency_str = "EMERGENCY " if is_emergency else ""
        visual_ctx = self._capture_visual_context(
            f"{emergency_str}Failure in feature #{self._current_feature_id}: {self._current_feature_name}"
        )

        # Stop observation
        self.watchdog.stop_observation()

        # Determine rollback level
        level = RollbackLevel.EMERGENCY if is_emergency else RollbackLevel.HARD

        # Execute rollback
        rollback_result = self.rollback_executor.execute(
            baseline=self._current_baseline,
            level=level,
            feature_id=self._current_feature_id,
        )

        if self._on_rollback:
            try:
                self._on_rollback(rollback_result)
            except Exception as e:
                LOG.error(f"Error in rollback callback: {e}")

        # Create failure report (with visual context if available)
        report = self.reporter.create_report(
            feature_id=self._current_feature_id,
            feature_name=self._current_feature_name,
            baseline=self._current_baseline,
            anomalies=anomalies,
            rollback_result=rollback_result,
        )

        # Quarantine the feature
        quarantine_entry = self.quarantine.quarantine(
            feature_id=self._current_feature_id,
            reason=report.probable_cause,
            failure_report=report.to_dict(),
        )

        # Generate retry alternatives
        alternatives = self.retry_strategy.suggest_alternatives(report)

        # Call failure callback
        if self._on_failure:
            try:
                self._on_failure(report, alternatives)
            except Exception as e:
                LOG.error(f"Error in failure callback: {e}")

        # Notify user if configured
        if self.config.notify_user_on_failure:
            self._notify_user(report, alternatives, quarantine_entry)

        self._cleanup_integration()

    def _update_feature_status(self, status: str):
        """Update feature status in database."""
        try:
            conn = sqlite3.connect(str(self.config.db_path), timeout=30)
            conn.execute("""
                UPDATE extracted_features
                SET integration_status = ?,
                    integrated_at = ?
                WHERE id = ?
            """, (status, datetime.now().isoformat(), self._current_feature_id))
            conn.commit()
            conn.close()
        except Exception as e:
            LOG.error(f"Failed to update feature status: {e}")

    def _notify_user(self, report: FailureReport, alternatives: List[Alternative],
                     quarantine_entry):
        """Create notification for user about failure."""
        notification = {
            "type": "asrs_failure",
            "feature_id": self._current_feature_id,
            "feature_name": self._current_feature_name,
            "severity": report.severity,
            "cause": report.probable_cause,
            "quarantine_count": quarantine_entry.quarantine_count,
            "is_permanent": quarantine_entry.is_permanent,
            "alternatives": [a.to_dict() for a in alternatives[:3]],
            "report_id": report.id,
            "timestamp": datetime.now().isoformat(),
        }

        # Write to notification file for Frank to pick up
        try:
            from config.paths import TEMP_FILES as _orch_temp_files
            notif_file = _orch_temp_files["asrs_notification"]
        except ImportError:
            notif_file = Path("/tmp/frank/asrs_notification.json")
        notif_file.write_text(json.dumps(notification, indent=2))

        LOG.info(f"User notification written to {notif_file}")

    def _cleanup_integration(self):
        """Clean up after integration (success or failure)."""
        # FIX CRITICAL #1: Release the integration lock at the end of lifecycle
        try:
            self._current_baseline = None
            self._current_feature_id = None
            self._current_feature_name = ""
            self._on_success = None
            self._on_failure = None
            self._on_rollback = None
        finally:
            # Release the lock that was acquired in begin_integration()
            if self._integration_lock_holder == threading.current_thread().ident:
                self._integration_lock_holder = None
                self._integration_lock.release()
                LOG.debug("Integration lock released after cleanup")

    # --- Utility Methods ---

    def get_status(self) -> Dict:
        """Get current A.S.R.S. status."""
        return {
            "integration_in_progress": self._current_baseline is not None,
            "current_feature_id": self._current_feature_id,
            "current_feature_name": self._current_feature_name,
            "observing": self.watchdog.is_observing(),
            "quarantine_stats": self.quarantine.get_statistics(),
            "recent_reports": self.reporter.list_reports(5),
        }

    def get_quarantined_features(self) -> List[Dict]:
        """Get list of quarantined features."""
        entries = self.quarantine.get_quarantined()
        return [e.to_dict() for e in entries]

    def get_ready_for_retry(self) -> List[int]:
        """Get feature IDs ready for retry."""
        return self.quarantine.get_ready_for_retry()

    def retry_feature(self, feature_id: int, strategy: str = None) -> bool:
        """
        Attempt to retry a quarantined feature.

        Args:
            feature_id: ID of the feature to retry
            strategy: Optional strategy to use

        Returns:
            True if feature was released for retry
        """
        # Check if feature is ready for retry
        ready = self.quarantine.get_ready_for_retry()
        if feature_id not in ready:
            info = self.quarantine.get_quarantine_info(feature_id)
            if info and info.is_permanent:
                LOG.warning(f"Feature #{feature_id} is permanently rejected")
                return False
            LOG.warning(f"Feature #{feature_id} not ready for retry")
            return False

        # Set retry strategy if provided
        if strategy:
            self.quarantine.set_retry_strategy(feature_id, strategy)

        # Release from quarantine
        return self.quarantine.release(feature_id)

    def get_failure_report(self, report_id: str) -> Optional[FailureReport]:
        """Get a specific failure report."""
        return self.reporter.get_report(report_id)

    def force_check(self) -> List[Dict]:
        """Force an immediate health check during observation."""
        if not self.watchdog.is_observing():
            return []
        return self.watchdog.force_check()

    def cleanup_old_data(self, days: int = 7):
        """Clean up old baselines and reports."""
        self.baseline_manager.cleanup_old_baselines(days)
        LOG.info(f"Cleaned up data older than {days} days")


# Convenience function
def integrate_with_safety(feature_id: int, feature_name: str,
                          integration_func: Callable,
                          files_to_modify: List[str] = None,
                          on_success: Callable = None,
                          on_failure: Callable = None) -> bool:
    """
    Convenience function to run integration with A.S.R.S. protection.

    Args:
        feature_id: ID of the feature
        feature_name: Name of the feature
        integration_func: Function that performs the actual integration
        files_to_modify: Files that will be modified
        on_success: Success callback
        on_failure: Failure callback(report, alternatives)

    Returns:
        True if integration started successfully, False otherwise
    """
    orchestrator = ASRSOrchestrator()

    try:
        # Begin monitored integration
        baseline = orchestrator.begin_integration(
            feature_id=feature_id,
            feature_name=feature_name,
            files_to_modify=files_to_modify,
            on_success=on_success,
            on_failure=on_failure,
        )

        # Run the actual integration
        integration_func()

        # Start observation
        orchestrator.start_observation()

        return True

    except Exception as e:
        LOG.error(f"Integration failed to start: {e}")
        orchestrator.abort_integration(f"Exception: {e}")
        return False
