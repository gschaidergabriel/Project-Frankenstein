"""
Frank's ACC (Anterior Cingulate Cortex) -- Conflict Monitor
============================================================

Second-order error detection system. Monitors discrepancies between
Frank's self-model (what he believes about himself) and measured
reality (what his subsystems actually report).

7 domain-general conflict channels:
    mood      (vACC) — E-PQ mood vs AURA mood zone
    vigilance (dACC) — E-PQ vigilance vs Amygdala alert frequency
    coherence (dACC) — E-PQ precision vs QR energy/violations
    body      (vACC) — Service topology belief vs actual port checks
    prediction(dACC) — Prediction confidence vs actual surprise
    identity  (vACC) — Confidence anchor vs identity attack pressure
    activity  (dACC) — Active goals vs rumination score

Neuroscience basis:
    - Botvinick conflict monitoring (2001/2004)
    - PRO model: unsigned surprise (Alexander & Brown, 2011)
    - EVC: cost-benefit of control (Shenhav, Botvinick, Cohen, 2013)
    - Friston free energy / prediction error minimization
    - Gratton effect: adaptive threshold after conflict detection

Key properties:
    - Domain-general: identical math across all channels
    - Unsigned: both positive and negative surprise activate
    - Affective: conflict -> E-PQ perturbation ("feeling of wrongness")
    - Adaptive: Gratton thresholds prevent alarm fatigue
    - Fast: <5ms per tick, called every ~60s from consciousness daemon
"""

from __future__ import annotations

import atexit
import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

LOG = logging.getLogger("frank.acc")

# ══════════════════════════════════════════════════
# DB Setup
# ══════════════════════════════════════════════════

try:
    from config.paths import get_db
    DB_PATH = get_db("acc_monitor")
except Exception:
    DB_PATH = Path.home() / ".local" / "share" / "frank" / "db" / "acc_monitor.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conflict_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    channel TEXT NOT NULL,
    subdivision TEXT NOT NULL,
    belief REAL NOT NULL,
    reality REAL NOT NULL,
    discrepancy REAL NOT NULL,
    threshold REAL NOT NULL,
    salience REAL NOT NULL,
    label TEXT,
    epq_event_fired INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS adaptive_thresholds (
    channel TEXT PRIMARY KEY,
    base_threshold REAL NOT NULL,
    current_threshold REAL NOT NULL,
    last_conflict_ts REAL DEFAULT 0,
    conflict_count_24h INTEGER DEFAULT 0,
    updated REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conflict_ts ON conflict_log(timestamp);
"""

# ══════════════════════════════════════════════════
# Channel Definitions
# ══════════════════════════════════════════════════

# subdivision: 'dACC' (cognitive) or 'vACC' (emotional/somatic)
CHANNELS = {
    "mood":       {"subdivision": "vACC", "base_threshold": 0.25},
    "vigilance":  {"subdivision": "dACC", "base_threshold": 0.30},
    "coherence":  {"subdivision": "dACC", "base_threshold": 0.20},
    "body":       {"subdivision": "vACC", "base_threshold": 0.35},
    "prediction": {"subdivision": "dACC", "base_threshold": 0.30},
    "identity":   {"subdivision": "vACC", "base_threshold": 0.25},
    "activity":   {"subdivision": "dACC", "base_threshold": 0.25},
}

# Gratton effect parameters
GRATTON_RAISE = 0.05
GRATTON_DECAY_RATE = 0.98
GRATTON_MAX_RAISE = 0.30
GRATTON_MIN = 0.10

# Salience scaling
SALIENCE_CEIL = 0.40

# E-PQ firing
EPQ_FIRE_THRESHOLD = 0.3
EPQ_COOLDOWN_S = 120.0

# PROPRIO injection
PROPRIO_INJECT_THRESHOLD = 0.2

# Housekeeping
LOG_RETENTION_S = 86400 * 7


# ══════════════════════════════════════════════════
# Dataclasses
# ══════════════════════════════════════════════════

@dataclass
class ACCInputState:
    """All inputs for one ACC tick. Gathered by consciousness daemon from caches."""
    # E-PQ (self-model)
    epq_mood_buffer: float = 0.0
    epq_vigilance: float = 0.0
    epq_precision: float = 0.0
    epq_confidence: float = 0.5
    epq_autonomy: float = 0.0

    # AURA (reality)
    aura_mood_density: float = 0.0

    # Amygdala (reality)
    amygdala_alert_count_5min: int = 0
    amygdala_identity_attacks_5min: int = 0

    # QR (reality)
    qr_energy: float = 0.0
    qr_violations: int = 0
    qr_trend: str = "stable"

    # Services (reality)
    services_total: int = 15
    services_down: int = 0

    # Predictions (reality)
    prediction_surprise_avg: float = 0.0

    # Activity (reality)
    rumination_score: float = 0.0
    has_active_goals: bool = False


@dataclass
class ChannelReading:
    """A single channel's belief vs reality comparison."""
    channel: str = ""
    subdivision: str = ""
    belief: float = 0.0
    reality: float = 0.0
    discrepancy: float = 0.0
    threshold: float = 0.0
    salience: float = 0.0
    conflict: bool = False
    label: str = ""


@dataclass
class ACCTickResult:
    """Result of a single ACC tick."""
    timestamp: float = 0.0
    channels: Dict[str, ChannelReading] = field(default_factory=dict)
    total_conflict: float = 0.0
    dominant_channel: str = ""
    dominant_salience: float = 0.0
    subdivision_summary: Dict[str, float] = field(default_factory=dict)
    epq_events_fired: List[str] = field(default_factory=list)
    proprio_line: str = ""

    def __repr__(self):
        active = [f"{k}={v.salience:.2f}" for k, v in self.channels.items() if v.conflict]
        return (f"ACCTickResult(total={self.total_conflict:.2f}, "
                f"dominant={self.dominant_channel}, active=[{', '.join(active)}])")


# ══════════════════════════════════════════════════
# ACC Monitor Class
# ══════════════════════════════════════════════════

class ACCMonitor:
    """Anterior Cingulate Cortex -- conflict monitor. <5ms per tick."""

    def __init__(self):
        self._lock = threading.RLock()
        self._db: Optional[sqlite3.Connection] = None
        self._thresholds: Dict[str, float] = {}
        self._last_epq_fire_ts: Dict[str, float] = {}
        self._last_tick_result: Optional[ACCTickResult] = None
        self._last_tick_ts: float = 0.0
        self._tick_count: int = 0
        self._history: List[ACCTickResult] = []
        self._max_history = 20

        self._init_db()
        self._load_thresholds()
        LOG.info("ACC Monitor initialized (%d channels)", len(CHANNELS))

    # ── DB ──

    def _init_db(self):
        try:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(DB_PATH), timeout=10,
                                       check_same_thread=False)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA busy_timeout=5000")
            self._db.executescript(_SCHEMA)
            self._db.commit()
        except Exception as e:
            LOG.warning("ACC DB init failed: %s", e)
            self._db = None

    def _get_db(self) -> Optional[sqlite3.Connection]:
        if self._db is None:
            self._init_db()
        return self._db

    def _load_thresholds(self):
        """Load adaptive thresholds from DB, or init from base values."""
        db = self._get_db()
        if db:
            try:
                rows = db.execute(
                    "SELECT channel, current_threshold FROM adaptive_thresholds"
                ).fetchall()
                for ch, thresh in rows:
                    if ch in CHANNELS:  # skip stale/renamed channels
                        self._thresholds[ch] = thresh
            except Exception:
                pass
        for ch, cfg in CHANNELS.items():
            if ch not in self._thresholds:
                self._thresholds[ch] = cfg["base_threshold"]
                self._save_threshold(ch, cfg["base_threshold"])

    def _save_threshold(self, channel: str, value: float):
        db = self._get_db()
        if not db:
            return
        try:
            now = time.time()
            # INSERT OR IGNORE + UPDATE to preserve conflict_count_24h/last_conflict_ts
            db.execute(
                "INSERT OR IGNORE INTO adaptive_thresholds "
                "(channel, base_threshold, current_threshold, updated) "
                "VALUES (?, ?, ?, ?)",
                (channel, CHANNELS[channel]["base_threshold"], value, now),
            )
            db.execute(
                "UPDATE adaptive_thresholds "
                "SET current_threshold = ?, base_threshold = ?, updated = ? "
                "WHERE channel = ?",
                (value, CHANNELS[channel]["base_threshold"], now, channel),
            )
            db.commit()
        except Exception:
            pass

    # ── Public API ──

    def tick(self, state: ACCInputState) -> ACCTickResult:
        """Run one ACC monitoring cycle. <5ms. Called every ~60s."""
        now = time.time()
        result = ACCTickResult(timestamp=now)

        # 1. Compute all channels
        for ch_name, ch_cfg in CHANNELS.items():
            reading = self._compute_channel(ch_name, ch_cfg, state)
            result.channels[ch_name] = reading

        # 2. Aggregate
        active = [(n, r) for n, r in result.channels.items() if r.conflict]
        result.total_conflict = sum(r.salience for _, r in active)

        if active:
            dom_name, dom_reading = max(active, key=lambda x: x[1].salience)
            result.dominant_channel = dom_name
            result.dominant_salience = dom_reading.salience

        # Subdivision aggregates
        dacc = [r.salience for r in result.channels.values()
                if r.subdivision == "dACC" and r.conflict]
        vacc = [r.salience for r in result.channels.values()
                if r.subdivision == "vACC" and r.conflict]
        result.subdivision_summary = {
            "dACC": sum(dacc) / max(len(dacc), 1) if dacc else 0.0,
            "vACC": sum(vacc) / max(len(vacc), 1) if vacc else 0.0,
        }

        # 3. Gratton effect: adapt thresholds
        for ch_name in CHANNELS:
            reading = result.channels[ch_name]
            base = CHANNELS[ch_name]["base_threshold"]
            current = self._thresholds.get(ch_name, base)

            if reading.conflict:
                new_t = min(current + GRATTON_RAISE, base + GRATTON_MAX_RAISE)
            else:
                new_t = base + (current - base) * GRATTON_DECAY_RATE
                if new_t - base < 0.005:
                    new_t = base
                new_t = max(GRATTON_MIN, new_t)
            self._thresholds[ch_name] = new_t

        # Persist thresholds every 10th tick
        if self._tick_count % 10 == 0:
            for ch_name in CHANNELS:
                self._save_threshold(ch_name, self._thresholds[ch_name])

        # 4. E-PQ perturbation (max 2 per tick to prevent multi-channel burst)
        epq_fired_this_tick = 0
        for ch_name, reading in result.channels.items():
            if epq_fired_this_tick >= 2:
                break
            if reading.conflict and reading.salience >= EPQ_FIRE_THRESHOLD:
                last_fire = self._last_epq_fire_ts.get(ch_name, 0.0)
                if now - last_fire >= EPQ_COOLDOWN_S:
                    event_type = self._fire_epq_event(ch_name, reading)
                    if event_type:
                        result.epq_events_fired.append(event_type)
                        self._last_epq_fire_ts[ch_name] = now
                        epq_fired_this_tick += 1

        # 5. PROPRIO injection line
        result.proprio_line = self._build_proprio_line(result)

        # 6. Log conflicts to DB
        for ch_name, reading in result.channels.items():
            if reading.conflict:
                epq_fired = any(ch_name in e for e in result.epq_events_fired)
                self._log_conflict(reading, epq_fired)

        # 7. World experience observation for significant conflict
        if result.total_conflict > 1.0:
            self._observe_conflict(result)

        # 8. Housekeeping
        self._history.append(result)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        self._last_tick_result = result
        self._last_tick_ts = now
        self._tick_count += 1

        if self._tick_count % 100 == 0:
            self._cleanup_old_logs()

        return result

    @property
    def last_result(self) -> Optional[ACCTickResult]:
        return self._last_tick_result

    @property
    def last_tick_age_s(self) -> float:
        if self._last_tick_ts == 0.0:
            return float("inf")
        return time.time() - self._last_tick_ts

    def get_conflict_trend(self, channel: str) -> str:
        """Get conflict trend for a channel over recent history."""
        relevant = [r for r in self._history
                    if channel in r.channels and r.channels[channel].conflict]
        if len(relevant) < 4:
            return "stable"
        mid = len(relevant) // 2
        recent_avg = sum(r.channels[channel].salience for r in relevant[mid:]) / (len(relevant) - mid)
        early_avg = sum(r.channels[channel].salience for r in relevant[:mid]) / mid
        if recent_avg > early_avg + 0.1:
            return "escalating"
        elif recent_avg < early_avg - 0.1:
            return "resolving"
        return "stable"

    def get_summary(self) -> dict:
        """Diagnostic summary."""
        result = self._last_tick_result
        if not result:
            return {"status": "no_data", "tick_count": 0}
        return {
            "tick_count": self._tick_count,
            "last_tick_age_s": round(self.last_tick_age_s, 1),
            "total_conflict": round(result.total_conflict, 3),
            "dominant_channel": result.dominant_channel,
            "dominant_salience": round(result.dominant_salience, 3),
            "active_conflicts": [
                {"channel": n, "salience": round(r.salience, 3), "label": r.label}
                for n, r in result.channels.items() if r.conflict
            ],
            "thresholds": {k: round(v, 3) for k, v in self._thresholds.items()},
            "subdivision_summary": {k: round(v, 3) for k, v in result.subdivision_summary.items()},
        }

    # ── Channel Computation ──

    def _compute_channel(self, ch_name: str, ch_cfg: dict,
                         state: ACCInputState) -> ChannelReading:
        """Compute one channel's conflict reading. Domain-general."""
        subdivision = ch_cfg["subdivision"]
        threshold = self._thresholds.get(ch_name, ch_cfg["base_threshold"])

        belief, reality, label = self._extract_values(ch_name, state)

        discrepancy = abs(belief - reality)
        is_conflict = discrepancy > threshold

        if is_conflict:
            salience = min(1.0, (discrepancy - threshold) / SALIENCE_CEIL)
        else:
            salience = 0.0

        return ChannelReading(
            channel=ch_name,
            subdivision=subdivision,
            belief=round(belief, 3),
            reality=round(reality, 3),
            discrepancy=round(discrepancy, 3),
            threshold=round(threshold, 3),
            salience=round(salience, 3),
            conflict=is_conflict,
            label=label if is_conflict else "",
        )

    def _extract_values(self, ch_name: str,
                        state: ACCInputState) -> Tuple[float, float, str]:
        """Extract (belief, reality, label) for a channel. All normalized 0-1."""

        if ch_name == "mood":
            belief = (state.epq_mood_buffer + 1.0) / 2.0
            # AURA density 0.0 = no data available → neutral 0.5
            reality = 0.5 if state.aura_mood_density < 0.001 else state.aura_mood_density
            if belief > reality + 0.2:
                label = "mood mismatch -- I feel good but AURA mood zone is quiet"
            elif reality > belief + 0.2:
                label = "mood mismatch -- AURA mood zone churning but I feel calm"
            else:
                label = "mood-AURA divergence"
            return belief, reality, label

        elif ch_name == "vigilance":
            belief = (state.epq_vigilance + 1.0) / 2.0
            # 0 alerts → 0.5 (neutral, matches vig=0), 5 alerts → 1.0
            reality = _clamp(0.5 + state.amygdala_alert_count_5min / 10.0)
            if belief < 0.4 and reality > 0.7:
                label = "relaxed but amygdala firing -- threats unnoticed"
            elif belief > 0.7 and reality < 0.55:
                label = "hypervigilant but no actual threats detected"
            else:
                label = "vigilance-threat mismatch"
            return belief, reality, label

        elif ch_name == "coherence":
            belief = (state.epq_precision + 1.0) / 2.0
            # abs(energy) — QR QUBO energy can be negative (lower = better)
            if state.qr_violations == 0:
                reality = _clamp(0.5 + abs(state.qr_energy) / 100.0)
            else:
                reality = _clamp(0.5 - state.qr_violations * 0.10)
            if belief > reality + 0.15:
                label = "precision feels high but QR shows instability"
            elif reality > belief + 0.15:
                label = "QR coherent but self-model doubts precision"
            else:
                label = "coherence drift"
            return belief, reality, label

        elif ch_name == "body":
            # Frank expects all organs healthy; reality = actual health
            belief = 1.0
            reality = _clamp(1.0 - (state.services_down / max(state.services_total, 1)))
            label = f"{state.services_down} organs offline -- body integrity compromised"
            return belief, reality, label

        elif ch_name == "prediction":
            belief = 0.5  # Default confidence (no tracker yet)
            # No data (surprise ≈ 0) → neutral 0.5; actual surprise → lower reality
            if state.prediction_surprise_avg <= 0.05:
                reality = 0.5
            else:
                reality = _clamp(1.0 - state.prediction_surprise_avg)
            if reality < 0.35:
                label = "predictions keep failing -- recalibrating"
            elif reality > 0.65:
                label = "predictions landing well -- trust building"
            else:
                label = "prediction accuracy drift"
            return belief, reality, label

        elif ch_name == "identity":
            # Normalize like other E-PQ fields (confidence can be -1..+1)
            belief = _clamp((state.epq_confidence + 1.0) / 2.0)
            # Only use raw 0-1 value if already in that range (legacy)
            if 0.0 <= state.epq_confidence <= 1.0:
                belief = state.epq_confidence
            # 0 attacks → 0.5 (neutral, matches default conf), 3 attacks → 0.0
            reality = _clamp(0.5 - state.amygdala_identity_attacks_5min / 6.0)
            if belief > reality + 0.2:
                label = "identity under siege -- staying grounded despite attacks"
            elif reality > belief + 0.2:
                label = "identity stable but self-confidence low -- unwarranted doubt"
            else:
                label = "identity-pressure mismatch"
            return belief, reality, label

        elif ch_name == "activity":
            # Belief sets baseline; rumination pulls reality away from it
            if state.has_active_goals:
                belief = 0.7
                reality = _clamp(0.7 - state.rumination_score * 0.7)
            else:
                belief = 0.5
                reality = _clamp(0.5 - state.rumination_score * 0.5)
            if state.has_active_goals and state.rumination_score > 0.5:
                label = "goals want growth but thoughts are circling"
            elif not state.has_active_goals and state.rumination_score > 0.5:
                label = "no clear goals and mind is racing"
            else:
                label = "activity-goal mismatch"
            return belief, reality, label

        return 0.5, 0.5, "unknown channel"

    # ── E-PQ Event Firing ──

    def _fire_epq_event(self, ch_name: str,
                        reading: ChannelReading) -> Optional[str]:
        """Fire E-PQ perturbation for significant conflict."""
        try:
            from personality.e_pq import get_epq
            epq = get_epq()

            if reading.subdivision == "vACC":
                event_type = "acc_emotional_conflict"
            else:
                event_type = "acc_cognitive_conflict"

            data = {
                "channel": ch_name,
                "salience": reading.salience,
                "discrepancy": reading.discrepancy,
            }
            # neutral — ACC handlers already encode valence via mood multipliers
            epq.process_event(event_type, data=data, sentiment="neutral")
            LOG.info("ACC E-PQ: %s (channel=%s, salience=%.2f)",
                     event_type, ch_name, reading.salience)
            return event_type
        except Exception as e:
            LOG.debug("ACC E-PQ fire failed: %s", e)
            return None

    # ── PROPRIO Line ──

    def _build_proprio_line(self, result: ACCTickResult) -> str:
        """Build terse PROPRIO injection. Only when conflict above threshold."""
        active = [(n, r) for n, r in result.channels.items()
                  if r.conflict and r.salience >= PROPRIO_INJECT_THRESHOLD]
        if not active:
            return ""
        active.sort(key=lambda x: x[1].salience, reverse=True)
        top = active[:2]

        parts = []
        for name, reading in top:
            if reading.salience > 0.7:
                intensity = "strong"
            elif reading.salience > 0.4:
                intensity = "nagging"
            else:
                intensity = "faint"
            parts.append(f"{name} {intensity}")

        return f"Conflict: {', '.join(parts)}"

    # ── DB Logging ──

    def _log_conflict(self, reading: ChannelReading, epq_fired: bool):
        db = self._get_db()
        if not db:
            return
        try:
            with self._lock:
                now = time.time()
                db.execute(
                    "INSERT INTO conflict_log "
                    "(timestamp, channel, subdivision, belief, reality, "
                    "discrepancy, threshold, salience, label, epq_event_fired) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (now, reading.channel, reading.subdivision,
                     reading.belief, reading.reality, reading.discrepancy,
                     reading.threshold, reading.salience, reading.label,
                     int(epq_fired)),
                )
                db.execute(
                    "UPDATE adaptive_thresholds "
                    "SET last_conflict_ts = ?, "
                    "    conflict_count_24h = conflict_count_24h + 1 "
                    "WHERE channel = ?",
                    (now, reading.channel),
                )
                db.commit()
        except Exception as e:
            LOG.debug("ACC log failed: %s", e)

    def close(self):
        """Close DB connection and checkpoint WAL."""
        if self._db:
            try:
                self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self._db.close()
            except Exception:
                pass
            self._db = None

    def _cleanup_old_logs(self):
        db = self._get_db()
        if not db:
            return
        try:
            cutoff = time.time() - LOG_RETENTION_S
            with self._lock:
                db.execute("DELETE FROM conflict_log WHERE timestamp < ?", (cutoff,))
                db.execute(
                    "UPDATE adaptive_thresholds SET conflict_count_24h = 0 "
                    "WHERE last_conflict_ts < ?",
                    (time.time() - 86400,),
                )
                db.commit()
                db.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except Exception:
            pass

    def _observe_conflict(self, result: ACCTickResult):
        """Fire world experience observation for significant conflict."""
        try:
            from tools.world_experience_daemon import get_daemon
            get_daemon().observe(
                cause_name="acc.conflict_detected",
                effect_name=f"acc.{result.dominant_channel}_mismatch",
                cause_type="cognitive",
                effect_type="affective",
                relation="triggers",
                evidence=min(0.5, result.total_conflict * 0.15),
            )
        except Exception:
            pass


# ══════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════

def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


# ══════════════════════════════════════════════════
# Singleton
# ══════════════════════════════════════════════════

_instance: Optional[ACCMonitor] = None
_instance_lock = threading.Lock()


def get_acc() -> ACCMonitor:
    """Get or create the singleton ACC Monitor instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ACCMonitor()
    return _instance


def _shutdown():
    global _instance
    if _instance is not None:
        _instance.close()


atexit.register(_shutdown)
