#!/usr/bin/env python3
"""
A.S.R.S. Connector - Connects Genesis to the safety system
"""

from typing import Dict, Optional, Callable
from datetime import datetime
import logging
import sys
from pathlib import Path

# Add path for ASRS imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ..core.manifestation import Crystal

LOG = logging.getLogger("genesis.asrs_connector")


class ASRSConnector:
    """
    Connects Genesis to A.S.R.S. for safe implementation.
    """

    def __init__(self):
        self._asrs_available = False
        self._orchestrator = None
        self._check_asrs()

    def _check_asrs(self):
        """Check if A.S.R.S. is available."""
        try:
            from services.asrs import ASRSOrchestrator
            self._orchestrator = ASRSOrchestrator()
            self._asrs_available = True
            LOG.info("A.S.R.S. connector initialized")
        except ImportError as e:
            LOG.warning(f"A.S.R.S. not available: {e}")
            self._asrs_available = False

    def integrate_with_safety(
        self,
        crystal: Crystal,
        implementation_func: Callable,
        on_success: Callable = None,
        on_failure: Callable = None
    ) -> bool:
        """
        Integrate a crystal with A.S.R.S. safety monitoring.

        Args:
            crystal: The crystal to integrate
            implementation_func: Function that does the actual work
            on_success: Callback on success
            on_failure: Callback on failure

        Returns:
            True if integration started successfully
        """
        if not self._asrs_available:
            LOG.warning("A.S.R.S. not available, running without safety")
            return self._integrate_without_safety(
                crystal, implementation_func, on_success, on_failure
            )

        try:
            genome = crystal.organism.genome

            # Begin monitored integration
            baseline = self._orchestrator.begin_integration(
                feature_id=genome.feature_id or hash(crystal.id) % 100000,
                feature_name=crystal.title or f"Genesis: {genome.target}",
                on_success=on_success,
                on_failure=on_failure,
            )

            LOG.info(f"A.S.R.S. integration started for crystal {crystal.id}")

            # Run the implementation
            try:
                implementation_func()
            except Exception as e:
                LOG.error(f"Implementation failed: {e}")
                self._orchestrator.abort_integration(str(e))
                return False

            # Start observation
            self._orchestrator.start_observation()
            return True

        except Exception as e:
            LOG.error(f"A.S.R.S. integration failed: {e}")
            return False

    def _integrate_without_safety(
        self,
        crystal: Crystal,
        implementation_func: Callable,
        on_success: Callable = None,
        on_failure: Callable = None
    ) -> bool:
        """Fallback integration without A.S.R.S."""
        try:
            implementation_func()

            if on_success:
                on_success()

            return True

        except Exception as e:
            LOG.error(f"Integration failed: {e}")

            if on_failure:
                on_failure(str(e), [])

            return False

    def get_quarantined_features(self) -> list:
        """Get list of quarantined features from A.S.R.S."""
        if not self._asrs_available:
            return []

        try:
            return self._orchestrator.get_quarantined_features()
        except Exception as e:
            LOG.warning(f"Failed to get quarantined features: {e}")
            return []

    def is_feature_quarantined(self, feature_id: int) -> bool:
        """Check if a feature is quarantined."""
        quarantined = self.get_quarantined_features()
        return any(f.get("feature_id") == feature_id for f in quarantined)

    def get_asrs_status(self) -> Dict:
        """Get A.S.R.S. status."""
        if not self._asrs_available:
            return {"available": False}

        try:
            return {
                "available": True,
                **self._orchestrator.get_status()
            }
        except Exception as e:
            return {"available": True, "error": str(e)}
