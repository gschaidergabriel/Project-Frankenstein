#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
coherence_monitor.py — Event-getriebener Kohärenz-Daemon

Polling-basierter Hintergrund-Loop:
1. Liest Frank's Zustand alle POLL_INTERVAL Sekunden
2. Bei relevanter Zustandsänderung: QUBO Rebuild + Anneal
3. Trackt Energy-History für Trend-Erkennung
4. Delegiert E-PQ Events an die EPQ-Bridge
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Deque, Dict, List, Optional

import numpy as np

from .annealer import AnnealerConfig, AnnealResult, compute_energy, solve
from .qubo_builder import FrankState, QUBOBuilder

LOG = logging.getLogger("quantum_reflector.monitor")

# ============ CONFIG ============

POLL_INTERVAL = 5.0          # Sekunden zwischen State-Checks
ENERGY_HISTORY_SIZE = 200    # Rolling Window für Trend-Erkennung
TREND_WINDOW = 20            # Letzte N Werte für Trend-Berechnung
IMPROVEMENT_REL_THRESHOLD = 0.02  # Energy mindestens 2% besser als Moving Avg
DEGRADATION_REL_THRESHOLD = 0.05  # Energy mindestens 5% schlechter als Moving Avg
PERIODIC_SOLVE_INTERVAL = 300.0  # Force re-solve every 5min even without state change


@dataclass
class CoherenceSnapshot:
    """Ein Zeitpunkt der Kohärenz-Messung."""
    timestamp: float
    energy: float
    mean_energy: float
    std_energy: float
    violations: int
    optimal_state: Dict
    current_state_energy: float
    gap: float  # optimal - current (negativ = current ist schlechter)


class CoherenceMonitor:
    """
    Hintergrund-Daemon für kontinuierliche Kohärenz-Überwachung.
    """

    def __init__(
        self,
        db_dir: Path,
        reflector_db: Path,
        annealer_config: AnnealerConfig = None,
        on_coherence_change: Optional[Callable] = None,
    ):
        self.builder = QUBOBuilder(db_dir)
        self.reflector_db = reflector_db
        self.config = annealer_config or AnnealerConfig()
        self.on_coherence_change = on_coherence_change

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

        # Energy History
        self._history: Deque[CoherenceSnapshot] = deque(maxlen=ENERGY_HISTORY_SIZE)
        self._last_result: Optional[AnnealResult] = None
        self._last_snapshot: Optional[CoherenceSnapshot] = None
        self._solve_count = 0
        self._last_solve_time: float = 0.0

        # DB setup
        self._ensure_schema()

    def _ensure_schema(self):
        """Erstelle Reflector-DB Schema."""
        conn = sqlite3.connect(str(self.reflector_db), timeout=10.0)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS energy_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                best_energy REAL NOT NULL,
                mean_energy REAL NOT NULL,
                std_energy REAL NOT NULL,
                current_state_energy REAL,
                gap REAL,
                violations INTEGER,
                optimal_state TEXT,
                frank_state TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_eh_ts ON energy_history(timestamp);

            CREATE TABLE IF NOT EXISTS coherence_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                event_type TEXT NOT NULL,
                energy REAL,
                moving_avg REAL,
                details TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_ce_ts ON coherence_events(timestamp);
        """)
        conn.commit()
        conn.close()

    @property
    def last_snapshot(self) -> Optional[CoherenceSnapshot]:
        with self._lock:
            return self._last_snapshot

    @property
    def last_result(self) -> Optional[AnnealResult]:
        with self._lock:
            return self._last_result

    @property
    def moving_average(self) -> Optional[float]:
        with self._lock:
            if len(self._history) < 2:
                return None
            recent = [s.energy for s in list(self._history)[-TREND_WINDOW:]]
            return float(np.mean(recent))

    @property
    def energy_trend(self) -> Optional[str]:
        """Bestimme Energietrend: 'improving', 'stable', 'degrading'."""
        with self._lock:
            if len(self._history) < TREND_WINDOW:
                return None
            recent = [s.energy for s in list(self._history)[-TREND_WINDOW:]]
            older = [s.energy for s in list(self._history)[-2 * TREND_WINDOW:-TREND_WINDOW]]
            if not older:
                return "stable"
            mean_recent = np.mean(recent)
            mean_older = np.mean(older)
            if abs(mean_older) > 0.01:
                rel_delta = (mean_recent - mean_older) / abs(mean_older)
                if rel_delta < -IMPROVEMENT_REL_THRESHOLD:
                    return "improving"
                elif rel_delta > DEGRADATION_REL_THRESHOLD:
                    return "degrading"
            return "stable"

    def solve_once(self) -> CoherenceSnapshot:
        """Führe einen einzelnen QUBO-Solve durch."""
        linear, Q, state = self.builder.build()

        result = solve(
            linear=linear,
            Q=Q,
            one_hot_groups=self.builder.one_hot_groups,
            config=self.config,
        )

        # Aktuellen Zustand als Vektor kodieren für Energy-Vergleich
        current_x = self._state_to_vector(state)
        current_energy = compute_energy(current_x, linear, Q)

        # Optimale Lösung interpretieren
        optimal_state = self.builder.interpret_solution(result.best_state)

        snapshot = CoherenceSnapshot(
            timestamp=time.time(),
            energy=result.best_energy,
            mean_energy=result.mean_energy,
            std_energy=result.std_energy,
            violations=result.violations,
            optimal_state=optimal_state,
            current_state_energy=current_energy,
            gap=result.best_energy - current_energy,
        )

        with self._lock:
            self._last_result = result
            self._last_snapshot = snapshot
            self._history.append(snapshot)
            self._solve_count += 1

        # Persistiere
        self._store_snapshot(snapshot, state)

        return snapshot

    def _state_to_vector(self, state: FrankState) -> np.ndarray:
        """Konvertiere FrankState in einen binären Vektor (n=43)."""
        from .qubo_builder import _epq_bucket

        x = np.zeros(self.builder.n, dtype=np.float64)

        # Entity [0-3]
        entity_map = {"therapist": 0, "mirror": 1, "atlas": 2, "muse": 3}
        x[entity_map.get(state.last_entity, 0)] = 1.0

        # Intent [4-6]
        intent_map = {"update": 4, "review": 5, "creative": 6}
        x[intent_map.get(state.current_intent, 4)] = 1.0

        # Phase [7-9]
        phase_map = {"idle": 7, "engaged": 8, "reflecting": 9}
        x[phase_map.get(state.current_phase, 7)] = 1.0

        # Mode [10-12]
        mode_map = {"meeting": 10, "project": 11, "focus": 12}
        x[mode_map.get(state.current_mode, 11)] = 1.0

        # Mood [13-14]
        x[13 if state.mood > 0 else 14] = 1.0

        # E-PQ tri-state [15-29]
        bucket_idx = {"low": 0, "mid": 1, "high": 2}
        for attr, base in [("precision", 15), ("risk", 18), ("empathy", 21),
                           ("autonomy", 24), ("vigilance", 27)]:
            b = _epq_bucket(getattr(state, attr))
            x[base + bucket_idx[b]] = 1.0

        # Task load [30-32]
        if state.active_goals == 0:
            x[30] = 1.0
        elif state.active_goals <= 3:
            x[31] = 1.0
        else:
            x[32] = 1.0

        # Engagement [33-35]
        if state.chat_recency_s > 600:
            x[33] = 1.0
        elif state.chat_recency_s > 120:
            x[34] = 1.0
        else:
            x[35] = 1.0

        # Binaries [36-39]
        x[36] = 1.0 if state.surprise_level > 0.3 else 0.0
        x[37] = 1.0 if state.confidence_anchor > 0.6 else 0.0
        x[38] = 1.0 if state.has_urgent_goal else 0.0
        x[39] = 0.0  # reflector_aligned: set by optimization

        # AURA reverse integration [40-42]
        x[40] = 1.0 if state.aura_anomaly_detected else 0.0
        x[41] = 1.0 if state.aura_grid_entropy > 0.5 else 0.0
        x[42] = 1.0 if state.aura_zone_contrast > 0.3 else 0.0

        return x

    def _store_snapshot(self, snap: CoherenceSnapshot, state: FrankState):
        """Speichere Snapshot in der Reflector-DB."""
        try:
            conn = sqlite3.connect(str(self.reflector_db), timeout=5.0)
            conn.execute(
                "INSERT INTO energy_history "
                "(timestamp, best_energy, mean_energy, std_energy, "
                "current_state_energy, gap, violations, optimal_state, frank_state) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snap.timestamp, snap.energy, snap.mean_energy, snap.std_energy,
                    snap.current_state_energy, snap.gap, snap.violations,
                    str(snap.optimal_state),
                    str({
                        "entity": state.last_entity,
                        "phase": state.current_phase,
                        "mode": state.current_mode,
                        "mood": state.mood,
                        "precision": state.precision,
                        "risk": state.risk,
                        "empathy": state.empathy,
                        "autonomy": state.autonomy,
                        "vigilance": state.vigilance,
                    }),
                ),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            LOG.warning("Failed to store snapshot: %s", exc)

    def _store_event(self, event_type: str, energy: float, moving_avg: float, details: str = ""):
        """Speichere ein Kohärenz-Event."""
        try:
            conn = sqlite3.connect(str(self.reflector_db), timeout=5.0)
            conn.execute(
                "INSERT INTO coherence_events (timestamp, event_type, energy, moving_avg, details) "
                "VALUES (?, ?, ?, ?, ?)",
                (time.time(), event_type, energy, moving_avg, details),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            LOG.warning("Failed to store event: %s", exc)

    def start(self):
        """Starte den Monitor-Thread."""
        if self._running:
            LOG.warning("Monitor already running")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="coherence-monitor",
            daemon=True,
        )
        self._thread.start()
        LOG.info("CoherenceMonitor started (poll=%.1fs)", POLL_INTERVAL)

    def stop(self):
        """Stoppe den Monitor."""
        LOG.info("Stopping CoherenceMonitor...")
        self._running = False
        if self._thread:
            self._thread.join(timeout=15)
        LOG.info("CoherenceMonitor stopped (total solves: %d)", self._solve_count)

    @staticmethod
    def _is_gaming_active() -> bool:
        """Check if gaming mode is active — pause coherence monitoring."""
        try:
            import json as _json
            try:
                from config.paths import TEMP_FILES as _qr_temp_files
                state_file = _qr_temp_files["gaming_mode_state"]
            except ImportError:
                state_file = Path("/tmp/frank/gaming_mode_state.json")
            if state_file.exists():
                data = _json.loads(state_file.read_text())
                return data.get("active", False)
        except Exception:
            pass
        return False

    def _monitor_loop(self):
        """Haupt-Loop: poll → check → solve → event."""
        # Erster Solve sofort
        try:
            self.solve_once()
            self._last_solve_time = time.time()
            LOG.info("Initial solve complete: energy=%.2f", self._last_snapshot.energy)
        except Exception as exc:
            LOG.error("Initial solve failed: %s", exc, exc_info=True)

        while self._running:
            try:
                time.sleep(POLL_INTERVAL)
                if not self._running:
                    break

                # Gaming mode: pause coherence monitoring
                if self._is_gaming_active():
                    continue

                # State lesen
                new_state = self.builder.read_frank_state()

                # Solve wenn State sich geändert hat ODER periodisches Intervall erreicht
                time_since_solve = time.time() - self._last_solve_time
                state_changed = self.builder.state_changed(new_state)
                periodic_due = time_since_solve >= PERIODIC_SOLVE_INTERVAL

                if not state_changed and not periodic_due:
                    continue

                if periodic_due and not state_changed:
                    LOG.debug("Periodic re-solve (%.0fs since last)", time_since_solve)
                else:
                    LOG.debug("State changed, solving...")

                snapshot = self.solve_once()
                self._last_solve_time = time.time()

                # Trend prüfen und ggf. Callback feuern
                # Use absolute relative delta — works correctly for negative energies
                ma = self.moving_average
                if ma is not None and self.on_coherence_change and abs(ma) > 0.01:
                    rel_delta = (snapshot.energy - ma) / abs(ma)
                    # For QUBO: lower energy = better, so negative rel_delta = improvement
                    if rel_delta < -IMPROVEMENT_REL_THRESHOLD:
                        self._store_event("improvement", snapshot.energy, ma)
                        self.on_coherence_change("improvement", snapshot, ma)
                    elif rel_delta > DEGRADATION_REL_THRESHOLD:
                        self._store_event("degradation", snapshot.energy, ma)
                        self.on_coherence_change("degradation", snapshot, ma)

            except Exception as exc:
                LOG.error("Monitor tick error: %s", exc, exc_info=True)
                time.sleep(POLL_INTERVAL)  # Extra Pause bei Fehler
