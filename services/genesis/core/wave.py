#!/usr/bin/env python3
"""
Wave System - The language of sensory input
==========================================

Sensors don't send discrete signals - they create WAVES
that propagate through the Motivational Field.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional
from collections import deque
import threading
import logging

LOG = logging.getLogger("genesis.wave")


@dataclass
class Wave:
    """
    A wave in the Motivational Field.

    Waves are created by sensors and propagate through
    the emotional landscape, creating interference patterns.
    """

    # Which emotional field does this wave affect?
    target_field: str  # "curiosity", "frustration", "satisfaction", etc.

    # Wave properties
    amplitude: float  # 0.0 - 1.0, strength of the wave
    decay: float = 0.1  # How fast the wave loses strength per tick

    # Metadata
    source: str = ""  # Which sensor created this wave?
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Internal state
    current_amplitude: float = field(init=False)
    age: int = 0  # Ticks since creation

    def __post_init__(self):
        self.current_amplitude = self.amplitude

    def tick(self) -> bool:
        """
        Evolve the wave by one tick.
        Returns False if wave has dissipated.
        """
        self.age += 1
        self.current_amplitude *= (1 - self.decay)

        # Wave dissipates when amplitude too low
        return self.current_amplitude > 0.01

    def get_contribution(self) -> float:
        """Get current contribution to the field."""
        return self.current_amplitude

    def __repr__(self):
        return f"Wave({self.target_field}, amp={self.current_amplitude:.3f}, src={self.source})"


class WaveBus:
    """
    The medium through which waves propagate.
    Collects waves and delivers them to the Motivational Field.
    """

    def __init__(self, max_waves: int = 1000):
        self.waves: deque = deque(maxlen=max_waves)
        self.lock = threading.Lock()
        self.wave_history: deque = deque(maxlen=100)  # Recent waves for analysis

    def emit(self, wave: Wave):
        """Emit a new wave into the bus."""
        with self.lock:
            self.waves.append(wave)
            self.wave_history.append({
                "field": wave.target_field,
                "amplitude": wave.amplitude,
                "source": wave.source,
                "timestamp": wave.timestamp.isoformat(),
                "metadata": wave.metadata,
            })
            LOG.debug(f"Wave emitted: {wave}")

    def emit_many(self, waves: List[Wave]):
        """Emit multiple waves."""
        for wave in waves:
            self.emit(wave)

    def tick(self) -> Dict[str, float]:
        """
        Process all waves for one tick.
        Returns the total contribution to each field.
        """
        contributions: Dict[str, float] = {}
        dead_waves = []

        with self.lock:
            for wave in self.waves:
                # Get contribution before tick
                field = wave.target_field
                contrib = wave.get_contribution()
                contributions[field] = contributions.get(field, 0) + contrib

                # Tick the wave
                if not wave.tick():
                    dead_waves.append(wave)

            # Remove dead waves
            for dead in dead_waves:
                try:
                    self.waves.remove(dead)
                except ValueError:
                    pass

        return contributions

    def get_active_waves(self) -> List[Wave]:
        """Get all currently active waves."""
        with self.lock:
            return list(self.waves)

    def get_field_activity(self, field: str) -> float:
        """Get total wave activity for a specific field."""
        with self.lock:
            return sum(w.get_contribution() for w in self.waves
                      if w.target_field == field)

    def get_recent_history(self, limit: int = 20) -> List[Dict]:
        """Get recent wave history for analysis."""
        with self.lock:
            return list(self.wave_history)[-limit:]

    def clear(self):
        """Clear all waves."""
        with self.lock:
            self.waves.clear()
