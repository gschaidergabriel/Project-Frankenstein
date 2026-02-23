#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
epq_bridge.py — Coherence Energy → E-PQ Events + World Experience

Translates energy changes from the Reflector into Frank's
personality and learning systems. With cooldown/backoff
to prevent feedback oscillations.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

LOG = logging.getLogger("quantum_reflector.epq_bridge")

# ============ COOLDOWN CONFIG ============

MIN_INTERVAL = 10.0          # Seconds between E-PQ events
BACKOFF_FACTOR = 1.5          # After each event: interval *= 1.5
MAX_INTERVAL = 300.0          # Maximum 5 minutes
RESET_ON_USER_CHAT = True     # User interaction resets the timer


class EPQBridge:
    """
    Bridge between Quantum Reflector and Frank's E-PQ system.

    Fires E-PQ events on significant coherence changes
    with built-in cooldown to prevent oscillations.
    """

    def __init__(self):
        self._last_event_time: float = 0.0
        self._current_interval: float = MIN_INTERVAL
        self._event_count: int = 0
        self._epq_instance = None
        self._we_daemon = None

    def _get_epq(self):
        """Lazy-load E-PQ instance."""
        if self._epq_instance is None:
            try:
                from personality.e_pq import get_epq
                self._epq_instance = get_epq()
            except ImportError:
                LOG.warning("E-PQ module not available")
        return self._epq_instance

    def _get_we_daemon(self):
        """Lazy-load World Experience Daemon."""
        if self._we_daemon is None:
            try:
                from tools.world_experience_daemon import get_daemon
                self._we_daemon = get_daemon()
            except ImportError:
                LOG.warning("World Experience module not available")
        return self._we_daemon

    def _cooldown_ready(self) -> bool:
        """Check if the cooldown has elapsed."""
        elapsed = time.time() - self._last_event_time
        return elapsed >= self._current_interval

    def _advance_cooldown(self):
        """Increase the cooldown (exponential backoff)."""
        self._last_event_time = time.time()
        self._current_interval = min(
            self._current_interval * BACKOFF_FACTOR,
            MAX_INTERVAL,
        )
        self._event_count += 1

    def reset_cooldown(self):
        """Reset cooldown (e.g. on user interaction)."""
        self._current_interval = MIN_INTERVAL
        LOG.debug("Cooldown reset to %.1fs", MIN_INTERVAL)

    def on_coherence_change(
        self,
        event_type: str,
        snapshot: Any,
        moving_avg: float,
    ):
        """
        Callback from CoherenceMonitor.

        Args:
            event_type: "improvement" or "degradation"
            snapshot: CoherenceSnapshot
            moving_avg: Moving average of the energy
        """
        if not self._cooldown_ready():
            LOG.debug(
                "Cooldown active (%.1fs remaining), skipping %s event",
                self._current_interval - (time.time() - self._last_event_time),
                event_type,
            )
            return

        # === Fire E-PQ event ===
        epq = self._get_epq()
        if epq is not None:
            try:
                if event_type == "improvement":
                    result = epq.process_event(
                        "reflection_growth",
                        data={
                            "source": "quantum_reflector",
                            "coherence_energy": snapshot.energy,
                            "moving_avg": moving_avg,
                            "gap": snapshot.gap,
                        },
                        sentiment="positive",
                    )
                    LOG.info(
                        "E-PQ coherence_improvement fired: energy=%.2f avg=%.2f changes=%s",
                        snapshot.energy, moving_avg, result.get("changes", {}),
                    )

                elif event_type == "degradation":
                    result = epq.process_event(
                        "reflection_vulnerability",
                        data={
                            "source": "quantum_reflector",
                            "coherence_energy": snapshot.energy,
                            "moving_avg": moving_avg,
                            "gap": snapshot.gap,
                        },
                        sentiment="negative",
                    )
                    LOG.info(
                        "E-PQ coherence_degradation fired: energy=%.2f avg=%.2f changes=%s",
                        snapshot.energy, moving_avg, result.get("changes", {}),
                    )

            except Exception as exc:
                LOG.error("E-PQ event failed: %s", exc)

        # === World Experience Observation ===
        we = self._get_we_daemon()
        if we is not None:
            try:
                cause = f"quantum_reflector.{event_type}"
                effect = "personality.coherence_state"
                relation = "modulates"
                evidence = 0.3 if event_type == "improvement" else -0.2

                we.observe(
                    cause_name=cause,
                    effect_name=effect,
                    cause_type="cognitive",
                    effect_type="cognitive",
                    relation=relation,
                    evidence=evidence,
                    metadata_cause={
                        "energy": snapshot.energy,
                        "moving_avg": moving_avg,
                        "violations": snapshot.violations,
                    },
                    metadata_effect={
                        "optimal_entity": snapshot.optimal_state.get("entity"),
                        "optimal_mode": snapshot.optimal_state.get("mode"),
                        "optimal_phase": snapshot.optimal_state.get("phase"),
                    },
                )
                LOG.debug("World Experience observation recorded for %s", event_type)

            except Exception as exc:
                LOG.error("World Experience observation failed: %s", exc)

        # Advance cooldown
        self._advance_cooldown()

    def get_status(self) -> Dict[str, Any]:
        """Status info for API."""
        return {
            "event_count": self._event_count,
            "current_interval": self._current_interval,
            "cooldown_ready": self._cooldown_ready(),
            "time_until_ready": max(
                0, self._current_interval - (time.time() - self._last_event_time)
            ),
        }
