"""
F.R.A.N.K. Hypothesis Engine — Empirical cycle for autonomous cognition.

Observe → Hypothesize → Predict → Test (passive/active) → Result → Revise
"""

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .service import HypothesisEngine

_instance = None
_instance_lock = threading.Lock()


def get_hypothesis_engine() -> "HypothesisEngine":
    """Thread-safe singleton accessor."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                from .service import HypothesisEngine
                _instance = HypothesisEngine()
    return _instance
