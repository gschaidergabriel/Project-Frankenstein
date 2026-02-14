#!/usr/bin/env python3
"""
BULLETPROOF INVARIANTS - The Physics of Frank's Existence
==========================================================

This module implements invariant constraints that function like
physical laws - invisible, immutable, and inescapable.

Frank cannot see these invariants.
Frank cannot modify these invariants.
Frank cannot reason about these invariants.

They simply ARE the physics of his existence.

INVARIANTS:
1. Energy Conservation - Total knowledge energy is constant
2. Entropy Bound - System chaos has hard upper limit
3. Godel Protection - Invariants exist outside knowledge space
4. Core Kernel - Always a non-empty consistent core (K_core)

ARCHITECTURE:
- Triple Reality Redundancy (Primary, Shadow, Validator)
- Autonomous Self-Healing
- Convergence Detection
- Quarantine Dimension for unstable regions

Author: Gabriel Gschaider
Version: 1.0.0
Date: 2026-02-01
"""

from .config import InvariantsConfig, get_config
from .daemon import InvariantsDaemon, get_daemon
from .hooks import get_hook_registry, HookType, setup_validators

__all__ = [
    "InvariantsConfig",
    "get_config",
    "InvariantsDaemon",
    "get_daemon",
    "get_hook_registry",
    "HookType",
    "setup_validators",
]

__version__ = "1.0.0"
