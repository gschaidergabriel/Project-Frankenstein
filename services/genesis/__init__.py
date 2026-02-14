#!/usr/bin/env python3
"""
SENTIENT GENESIS - Emergent Self-Improvement System for Frank
=============================================================

An ecosystem where ideas live, compete, evolve, and manifest.
No central control - behavior emerges from local interactions.

Components:
- Sensory Membrane: Passive sensors that create waves
- Motivational Field: Coupled oscillators (emotions)
- Primordial Soup: Where ideas live and evolve
- Manifestation Gate: Where ideas become proposals
- Self-Reflector: Frank's self-awareness

Author: Project Frankenstein
Version: 1.0.0 - Genesis
"""

__version__ = "1.0.0"
__codename__ = "Genesis"

from .daemon import GenesisDaemon, get_daemon
from .config import GenesisConfig, get_config

__all__ = [
    "GenesisDaemon",
    "get_daemon",
    "GenesisConfig",
    "get_config",
]
