"""
Universal Omniscient Log Gateway (UOLG)

Frank's nervous system for log awareness.

Components:
- log_ingest.py: Main log ingestion and distillation
- uif_bridge.py: Unified Insight Format bridge to Frank
- policy_guard.py: Security and mode enforcement
- uolg_control.py: Control interface

Usage:
    from tools.omni_log_monitor import uif_bridge
    bridge = uif_bridge.UIFBridge()
    understanding = bridge.get_system_understanding()
"""

from pathlib import Path

__version__ = "2.0.0"
__all__ = ["log_ingest", "uif_bridge", "policy_guard", "uolg_control"]

BASE_DIR = Path(__file__).parent
try:
    from config.paths import DB_DIR
except ImportError:
    DB_DIR = Path.home() / ".local" / "share" / "frank" / "db"
