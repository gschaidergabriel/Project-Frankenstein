"""
Neural Immune System — Self-Healing Service Organism
=====================================================
3 micro neural networks (~19K params, CPU-only) that learn from Frank's
operational history to monitor, predict failures, and restart services.

Replaces: frank_watchdog.py, frank_sentinel.py, llm_guard.py, dream watchdogs.

Usage:
    from services.neural_immune import get_immune_system
    immune = get_immune_system()
    immune.run()  # Main loop (blocking)

    # Or from dream daemon:
    immune.train_cycle()  # <50ms training on accumulated data
"""

import threading
from typing import Optional

_instance: Optional["ImmuneSystem"] = None
_lock = threading.Lock()


def get_immune_system() -> "ImmuneSystem":
    """Get or create singleton ImmuneSystem instance."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                from .supervisor import ImmuneSystem
                _instance = ImmuneSystem()
    return _instance
