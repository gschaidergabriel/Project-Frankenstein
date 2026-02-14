"""System control integration wrapper."""
from __future__ import annotations

SYSTEM_CONTROL_AVAILABLE = False
try:
    from tools.system_control import (
        process_system_control as sc_process,
        set_response_callback as sc_set_callback,
        has_pending_action as sc_has_pending,
        startup_network_scan as sc_startup_scan,
    )
    SYSTEM_CONTROL_AVAILABLE = True
except ImportError:
    def sc_process(*a, **k): return False, None
    def sc_set_callback(*a, **k): pass
    def sc_has_pending(*a, **k): return False
    def sc_startup_scan(*a, **k): pass
