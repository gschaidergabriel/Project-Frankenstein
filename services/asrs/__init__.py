#!/usr/bin/env python3
"""
A.S.R.S. - Autonomous Safety Recovery System

Provides automatic rollback and recovery when integrated features cause system instability.

Components:
- BaselineManager: Creates snapshots before integration
- SystemWatchdog: Monitors system health after integration
- AnomalyDetector: Detects deviations from baseline
- RollbackExecutor: Reverts changes when critical issues detected
- FeatureQuarantine: Isolates problematic features
- ErrorReporter: Creates detailed failure reports
- RetryStrategy: Suggests alternative integration approaches
"""

from .config import ASRSConfig, get_asrs_config
from .baseline import BaselineManager, Baseline
from .watchdog import SystemWatchdog
from .detector import AnomalyDetector, Anomaly
from .rollback import RollbackExecutor, RollbackLevel, RollbackResult
from .quarantine import FeatureQuarantine, QuarantineEntry
from .reporter import ErrorReporter, FailureReport
from .retry import RetryStrategy, Alternative, RetryStrategyType
from .orchestrator import ASRSOrchestrator, integrate_with_safety
from .auto_repair import AutoRepairManager, SystemDiagnoser, RepairActionGenerator, RepairExecutor
from .integrator import FeatureIntegrator, IntegrationResult, get_integrator
from .db_schema import ensure_schema, get_statistics, cleanup_old_records

__version__ = "1.0.0"
__all__ = [
    # Config
    "ASRSConfig",
    "get_asrs_config",
    # Baseline
    "BaselineManager",
    "Baseline",
    # Watchdog
    "SystemWatchdog",
    # Detector
    "AnomalyDetector",
    "Anomaly",
    # Rollback
    "RollbackExecutor",
    "RollbackLevel",
    "RollbackResult",
    # Quarantine
    "FeatureQuarantine",
    "QuarantineEntry",
    # Reporter
    "ErrorReporter",
    "FailureReport",
    # Retry
    "RetryStrategy",
    "Alternative",
    "RetryStrategyType",
    # Orchestrator
    "ASRSOrchestrator",
    "integrate_with_safety",
    # Auto-Repair
    "AutoRepairManager",
    "SystemDiagnoser",
    "RepairActionGenerator",
    "RepairExecutor",
    # Integrator
    "FeatureIntegrator",
    "IntegrationResult",
    "get_integrator",
    # DB Schema
    "ensure_schema",
    "get_statistics",
    "cleanup_old_records",
]
