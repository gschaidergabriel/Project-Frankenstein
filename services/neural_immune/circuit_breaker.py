"""
Neural Immune System — Circuit Breaker
========================================
Per-service circuit breaker FSM with 3 states:
  CLOSED    → Normal operation, tracking failures
  OPEN      → Service failing, restart blocked during cooldown
  HALF_OPEN → Probing with one restart attempt

Uses decorrelated jitter backoff (AWS pattern) for cooldown periods.
States persist in DB across immune system restarts.
"""

import logging
import math
import random
import time
from typing import Dict, Optional

from .db import ImmuneDB

LOG = logging.getLogger("immune.breaker")

# Circuit breaker constants
FAILURE_THRESHOLD = 5         # Consecutive failures → OPEN
PROBE_WINDOW_SECONDS = 30     # How long service must stay up in HALF_OPEN
BASE_COOLDOWN = 3.0           # Minimum cooldown seconds
MAX_COOLDOWN = 120.0          # Maximum cooldown seconds


class CircuitState:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Per-service circuit breaker with decorrelated jitter backoff."""

    def __init__(self, service: str, db: ImmuneDB,
                 base_delay: float = BASE_COOLDOWN):
        self.service = service
        self._db = db
        self._base_delay = base_delay

        # State
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_transition = time.time()
        self.cooldown_until = 0.0
        self.last_delay = base_delay

        # Half-open tracking
        self._probe_start: Optional[float] = None

        # Load from DB if exists
        self._load()

    def _load(self):
        saved = self._db.load_circuit_state(self.service)
        if saved:
            self.state = saved.get("state", CircuitState.CLOSED)
            self.failure_count = saved.get("failure_count", 0)
            self.last_transition = saved.get("last_transition", time.time())
            self.cooldown_until = saved.get("cooldown_until", 0.0)
            self.last_delay = saved.get("last_delay", self._base_delay)

    def _save(self):
        self._db.save_circuit_state(
            self.service, self.state, self.failure_count,
            self.cooldown_until, self.last_delay
        )

    def _transition(self, new_state: str):
        old = self.state
        self.state = new_state
        self.last_transition = time.time()
        self._save()
        LOG.info("[%s] Circuit: %s → %s (failures=%d, delay=%.1fs)",
                 self.service, old, new_state, self.failure_count, self.last_delay)

    # ── Public API ────────────────────────────────────────────────

    def record_failure(self):
        """Record a service failure (service down or unhealthy)."""
        self.failure_count += 1

        if self.state == CircuitState.CLOSED:
            if self.failure_count >= FAILURE_THRESHOLD:
                self._open_circuit()

        elif self.state == CircuitState.HALF_OPEN:
            # Probe failed → back to OPEN with increased cooldown
            self._open_circuit()

    def record_success(self):
        """Record a service healthy check."""
        if self.state == CircuitState.HALF_OPEN:
            # Check if probe window passed
            if self._probe_start and (time.time() - self._probe_start >= PROBE_WINDOW_SECONDS):
                self._close_circuit()
        elif self.state == CircuitState.CLOSED:
            # Decay failure count on success
            if self.failure_count > 0:
                self.failure_count -= 1
                if self.failure_count == 0:
                    self._save()

    def allows_restart(self) -> bool:
        """Check if a restart attempt is currently allowed."""
        now = time.time()

        if self.state == CircuitState.CLOSED:
            return True

        elif self.state == CircuitState.OPEN:
            if now >= self.cooldown_until:
                # Cooldown expired → transition to HALF_OPEN
                self._probe_start = now
                self._transition(CircuitState.HALF_OPEN)
                return True
            return False

        elif self.state == CircuitState.HALF_OPEN:
            # Only one restart attempt allowed in HALF_OPEN
            return False

        return False

    def get_recommended_delay(self, neural_delay: Optional[float] = None) -> float:
        """Get recommended restart delay (with jitter)."""
        if neural_delay is not None and neural_delay > 0:
            base = neural_delay
        else:
            base = self._base_delay
        return self._jitter_delay(base)

    def reset(self):
        """Reset circuit breaker to closed state."""
        self.failure_count = 0
        self.cooldown_until = 0.0
        self.last_delay = self._base_delay
        self._probe_start = None
        self._transition(CircuitState.CLOSED)

    @property
    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN

    @property
    def is_closed(self) -> bool:
        return self.state == CircuitState.CLOSED

    @property
    def time_in_state(self) -> float:
        return time.time() - self.last_transition

    # ── Internal ──────────────────────────────────────────────────

    def _open_circuit(self):
        """Transition to OPEN with decorrelated jitter cooldown."""
        delay = self._jitter_delay(self.last_delay)
        self.cooldown_until = time.time() + delay
        self.last_delay = delay
        self._probe_start = None
        self._transition(CircuitState.OPEN)

    def _close_circuit(self):
        """Transition to CLOSED, reset counters."""
        self.failure_count = 0
        self.cooldown_until = 0.0
        self.last_delay = self._base_delay
        self._probe_start = None
        self._transition(CircuitState.CLOSED)

    def _jitter_delay(self, last_delay: float) -> float:
        """Decorrelated jitter (AWS pattern):
        delay = min(cap, random(base, last_delay * 3))
        """
        jittered = random.uniform(self._base_delay, max(self._base_delay, last_delay * 3))
        return min(MAX_COOLDOWN, jittered)

    def to_dict(self) -> Dict:
        return {
            "service": self.service,
            "state": self.state,
            "failure_count": self.failure_count,
            "cooldown_until": self.cooldown_until,
            "last_delay": self.last_delay,
            "time_in_state": self.time_in_state,
        }
