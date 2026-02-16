#!/usr/bin/env python3
"""
A.S.R.S. Feature Integrator
Safe feature integration with A.S.R.S. monitoring.
"""

import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any
import logging
import json

from .orchestrator import ASRSOrchestrator
from .config import get_asrs_config
from .reporter import FailureReport
from .retry import Alternative

LOG = logging.getLogger("asrs.integrator")


@dataclass
class IntegrationResult:
    """Result of a feature integration."""
    feature_id: int
    feature_name: str
    success: bool
    status: str  # "integrated", "monitoring", "failed", "quarantined"
    message: str
    report: Optional[FailureReport] = None
    alternatives: Optional[List[Alternative]] = None

    def to_dict(self) -> Dict:
        return {
            "feature_id": self.feature_id,
            "feature_name": self.feature_name,
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "report_id": self.report.id if self.report else None,
            "alternatives": [a.to_dict() for a in (self.alternatives or [])],
        }


class FeatureIntegrator:
    """
    Handles safe feature integration with A.S.R.S. monitoring.
    """

    def __init__(self):
        self.config = get_asrs_config()
        self.orchestrator = ASRSOrchestrator(self.config)
        self._integration_results: Dict[int, IntegrationResult] = {}
        self._pending_integrations: Dict[int, threading.Event] = {}

    def integrate_feature(self, feature: Dict,
                          on_progress: Callable[[str], None] = None,
                          on_complete: Callable[[IntegrationResult], None] = None,
                          wait_for_observation: bool = False) -> IntegrationResult:
        """
        Integrate a feature with A.S.R.S. safety monitoring.

        Args:
            feature: Feature dict from database
            on_progress: Progress callback(message)
            on_complete: Completion callback(result)
            wait_for_observation: If True, wait for observation window to complete

        Returns:
            IntegrationResult with status
        """
        feature_id = feature.get("id")
        feature_name = feature.get("name", f"Feature #{feature_id}")

        LOG.info(f"Starting integration for {feature_name} (#{feature_id})")

        if on_progress:
            on_progress(f"Preparing integration: {feature_name}")

        # Determine what files might be affected
        files_to_modify = self._determine_affected_files(feature)

        # Create completion event for synchronous mode
        completion_event = threading.Event() if wait_for_observation else None
        final_result: List[IntegrationResult] = [None]

        def handle_success():
            result = IntegrationResult(
                feature_id=feature_id,
                feature_name=feature_name,
                success=True,
                status="integrated",
                message="Integration successful, system stable",
            )
            final_result[0] = result
            self._integration_results[feature_id] = result

            if on_complete:
                on_complete(result)

            if completion_event:
                completion_event.set()

            LOG.info(f"Integration successful for {feature_name}")

        def handle_failure(report: FailureReport, alternatives: List[Alternative]):
            result = IntegrationResult(
                feature_id=feature_id,
                feature_name=feature_name,
                success=False,
                status="quarantined",
                message=f"Integration failed: {report.probable_cause}",
                report=report,
                alternatives=alternatives,
            )
            final_result[0] = result
            self._integration_results[feature_id] = result

            if on_complete:
                on_complete(result)

            if completion_event:
                completion_event.set()

            LOG.warning(f"Integration failed for {feature_name}: {report.probable_cause}")

        try:
            # Begin monitored integration
            if on_progress:
                on_progress(f"Creating baseline snapshot...")

            baseline = self.orchestrator.begin_integration(
                feature_id=feature_id,
                feature_name=feature_name,
                files_to_modify=files_to_modify,
                on_success=handle_success,
                on_failure=handle_failure,
            )

            if on_progress:
                on_progress(f"Performing integration...")

            # Perform actual integration
            self._perform_integration(feature, on_progress)

            if on_progress:
                on_progress(f"Starting monitoring ({self.config.observation_window_sec}s)...")

            # Start observation
            self.orchestrator.start_observation()

            if wait_for_observation:
                # Wait for observation to complete
                completion_event.wait(timeout=self.config.observation_window_sec + 60)
                return final_result[0] or IntegrationResult(
                    feature_id=feature_id,
                    feature_name=feature_name,
                    success=False,
                    status="timeout",
                    message="Timeout during monitoring",
                )
            else:
                # Return immediately, result will come via callback
                return IntegrationResult(
                    feature_id=feature_id,
                    feature_name=feature_name,
                    success=True,
                    status="monitoring",
                    message=f"Integration running, monitoring for {self.config.observation_window_sec}s",
                )

        except Exception as e:
            LOG.error(f"Integration error: {e}")
            self.orchestrator.abort_integration(f"Exception: {e}")

            result = IntegrationResult(
                feature_id=feature_id,
                feature_name=feature_name,
                success=False,
                status="failed",
                message=f"Integration failed: {str(e)}",
            )
            self._integration_results[feature_id] = result

            if on_complete:
                on_complete(result)

            return result

    def _determine_affected_files(self, feature: Dict) -> List[str]:
        """Determine which files might be affected by this feature."""
        files = []

        # Check feature metadata for target files
        if feature.get("target_file"):
            files.append(feature["target_file"])

        if feature.get("affected_files"):
            files.extend(feature["affected_files"])

        # Default: assume core files might be affected
        if not files:
            files = [
                "/home/ai-core-node/aicore/opt/aicore/core/app.py",
                "/home/ai-core-node/aicore/opt/aicore/tools/toolboxd.py",
            ]

        return files

    def _perform_integration(self, feature: Dict, on_progress: Callable = None):
        """
        Perform the actual feature integration.
        This is where the feature code would be applied.
        """
        feature_id = feature.get("id")
        feature_name = feature.get("name", f"Feature #{feature_id}")

        # Check if feature has code to integrate
        code = feature.get("code_snippet") or feature.get("implementation")
        target_file = feature.get("target_file")

        if code and target_file:
            if on_progress:
                on_progress(f"Applying code changes...")

            # For now, we just log what would happen
            # Actual code integration would be done here
            LOG.info(f"Would apply code to {target_file}")

            # In a real implementation:
            # 1. Parse the target file
            # 2. Find insertion point
            # 3. Apply the changes
            # 4. Write back to file

        elif feature.get("config_changes"):
            if on_progress:
                on_progress(f"Applying configuration changes...")

            # Apply config changes
            LOG.info(f"Would apply config changes")

        else:
            # Feature might be a suggestion without direct code
            if on_progress:
                on_progress(f"Feature marked as approved...")

            LOG.info(f"Feature #{feature_id} marked as approved (no direct integration)")

        # Simulate some work
        time.sleep(0.5)

    def get_integration_status(self, feature_id: int) -> Optional[IntegrationResult]:
        """Get the status of a feature integration."""
        return self._integration_results.get(feature_id)

    def is_monitoring(self) -> bool:
        """Check if any integration is being monitored."""
        return self.orchestrator.watchdog.is_observing()

    def get_asrs_status(self) -> Dict:
        """Get current A.S.R.S. status."""
        return self.orchestrator.get_status()


# Singleton instance
_integrator: Optional[FeatureIntegrator] = None


def get_integrator() -> FeatureIntegrator:
    """Get or create integrator singleton."""
    global _integrator
    if _integrator is None:
        _integrator = FeatureIntegrator()
    return _integrator
