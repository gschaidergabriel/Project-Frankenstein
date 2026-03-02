#!/usr/bin/env python3
"""
Hypothesis Insight Sensor — Bridges empirical findings into Genesis.

Reads resolved hypotheses from hypothesis_engine.db and converts them
into actionable waves and observations. Frank's scientific discoveries
steer his own evolution.

Inspired by Active Inference: prediction errors are precision-weighted —
high-confidence refutations produce stronger surprise signals than
low-confidence ones. This mirrors biological free energy minimization
where unexpected outcomes at high precision drive learning most.

No LLM calls — classification is pure status/metric-based.
Read-only on hypothesis_engine.db.
"""

from typing import List, Dict, Any, Optional
from pathlib import Path
import math
import sqlite3
import logging
import time

from .base import BaseSensor
from ..core.wave import Wave

LOG = logging.getLogger("genesis.sensors.hypothesis_insight")

try:
    from config.paths import DB_PATHS
    HYPOTHESIS_DB = DB_PATHS["hypothesis_engine"]
except (ImportError, KeyError):
    HYPOTHESIS_DB = (
        Path.home() / ".local" / "share" / "frank" / "db" / "hypothesis_engine.db"
    )

# ── Rate Limits ──────────────────────────────────────────────────
_DB_CHECK_INTERVAL_S = 600      # Check DB every 10 min
_MAX_OBSERVATIONS_PER_TICK = 3  # Cap observations per sense cycle
_WAVE_COOLDOWN_S = 300          # Min 5 min between waves of same category
_MAX_HYPOTHESES_PER_READ = 10   # Max resolved hypotheses to process per read

# ── Category Definitions ────────────────────────────────────────
# Each category maps to wave field, amplitude, observation template.
# All observations designed to pass soup quality gate (≥ 2/4):
# target has ":", approach is concrete, evidence populated → 4/4.

_CATEGORIES = {
    "confirmed_discovery": {
        "wave_field": "satisfaction",
        "wave_amplitude": 0.30,
        "wave_decay": 0.04,
        "obs_type": "optimization",
        "obs_approach": "empirical_finding",
        "obs_target_prefix": "hypothesis:confirmed",
    },
    "refuted_surprise": {
        "wave_field": "curiosity",
        "wave_amplitude": 0.25,
        "wave_decay": 0.05,
        "obs_type": "exploration",
        "obs_approach": "hypothesis_revision",
        "obs_target_prefix": "hypothesis:refuted",
    },
    "experiment_insight": {
        "wave_field": "drive",
        "wave_amplitude": 0.20,
        "wave_decay": 0.04,
        "obs_type": "skill",
        "obs_approach": "simulation_result",
        "obs_target_prefix": "hypothesis:experiment",
    },
    "prediction_accuracy_high": {
        "wave_field": "satisfaction",
        "wave_amplitude": 0.15,
        "wave_decay": 0.03,
        "obs_type": "optimization",
        "obs_approach": "prediction_calibration",
        "obs_target_prefix": "hypothesis:accuracy",
    },
    "prediction_accuracy_low": {
        "wave_field": "concern",
        "wave_amplitude": 0.20,
        "wave_decay": 0.05,
        "obs_type": "fix",
        "obs_approach": "prediction_recalibration",
        "obs_target_prefix": "hypothesis:accuracy",
    },
}

# Domain-specific observation targets for richer specificity
_DOMAIN_TARGETS = {
    "physics": "science:physics",
    "chemistry": "science:chemistry",
    "astronomy": "science:astronomy",
    "gol": "science:game_of_life",
    "math": "science:math",
    "electronics": "science:electronics",
    "self": "consciousness:self_model",
    "affect": "consciousness:affect",
    "hardware": "system:hardware",
}


class HypothesisSensor(BaseSensor):
    """
    Senses empirical findings from the Hypothesis Engine.

    Reads from hypothesis_engine.db (read-only).
    Classifies resolved hypotheses by status and metrics.
    Emits precision-weighted waves (Active Inference pattern):
    surprise = confidence × |prediction_error|
    """

    def __init__(self):
        super().__init__("hypothesis_insight")

        # Incremental read tracking — start from now
        self._last_read_ts: float = time.time()
        self._last_db_check: float = 0.0

        # Recent resolved hypotheses for observation generation
        self._recent_resolved: List[Dict] = []

        # Wave cooldown per category
        self._last_wave_ts: Dict[str, float] = {}

        # Rolling accuracy tracker (last 20 resolutions)
        self._resolution_history: List[str] = []  # "confirmed" or "refuted"

    def sense(self) -> List[Wave]:
        """Read newly resolved hypotheses, classify, emit waves."""
        waves = []
        now = time.time()

        # Rate limit DB checks
        if (now - self._last_db_check) < _DB_CHECK_INTERVAL_S:
            return waves
        self._last_db_check = now

        try:
            resolved = self._read_resolved_hypotheses()
            if not resolved:
                return waves

            LOG.info("Read %d newly resolved hypothesis(es)", len(resolved))

            for h in resolved:
                category = self._classify(h)
                if not category:
                    continue

                # Track resolution history for accuracy detection
                if h["status"] in ("confirmed", "refuted"):
                    self._resolution_history.append(h["status"])
                    if len(self._resolution_history) > 20:
                        self._resolution_history = self._resolution_history[-20:]

                # Store for observation generation
                self._recent_resolved.append({
                    "hypothesis": h,
                    "category": category,
                    "timestamp": h.get("resolved_at") or h.get("updated_at", now),
                })

                # Emit wave with precision-weighted amplitude
                cat_def = _CATEGORIES[category]
                last_wave = self._last_wave_ts.get(category, 0)
                if (now - last_wave) < _WAVE_COOLDOWN_S:
                    continue

                amplitude = self._compute_surprise_amplitude(h, cat_def)

                waves.append(Wave(
                    target_field=cat_def["wave_field"],
                    amplitude=amplitude,
                    decay=cat_def["wave_decay"],
                    source=self.name,
                    metadata={
                        "category": category,
                        "domain": h.get("domain", "unknown"),
                        "hypothesis_preview": h.get("hypothesis", "")[:80],
                        "confidence": h.get("confidence", 0.5),
                        "confidence_delta": h.get("confidence_delta", 0),
                    },
                ))
                self._last_wave_ts[category] = now

            # Accuracy-level detection
            accuracy_wave = self._check_accuracy_trend()
            if accuracy_wave:
                waves.append(accuracy_wave)

            # Trim old resolved (keep last 24h)
            cutoff = now - 86400
            self._recent_resolved = [
                r for r in self._recent_resolved
                if r["timestamp"] > cutoff
            ]

        except Exception as e:
            LOG.warning("HypothesisSensor sensing error: %s", e)

        return waves

    def get_observations(self) -> List[Dict[str, Any]]:
        """Generate observations from recently resolved hypotheses."""
        observations = []

        if not self._recent_resolved:
            return observations

        for entry in self._recent_resolved[-_MAX_OBSERVATIONS_PER_TICK:]:
            h = entry["hypothesis"]
            category = entry["category"]
            cat_def = _CATEGORIES[category]
            domain = h.get("domain", "self")

            # Build domain-specific target with ":" for quality gate
            domain_target = _DOMAIN_TARGETS.get(domain, f"hypothesis:{domain}")
            target = f"{cat_def['obs_target_prefix']}:{domain_target}"

            # Strength from confidence
            confidence = h.get("confidence", 0.5)
            strength = min(1.0, 0.3 + confidence * 0.5)

            # Impact from confidence delta (precision-weighted)
            conf_delta = abs(h.get("confidence_delta", 0))
            impact = min(1.0, 0.3 + conf_delta * 2.0)

            # Build evidence from result/narration
            result_text = h.get("result", "") or ""
            hypothesis_text = h.get("hypothesis", "") or ""
            evidence = (
                f"Hypothesis: {hypothesis_text[:150]}\n"
                f"Result: {result_text[:150]}\n"
                f"Status: {h.get('status', 'unknown')} "
                f"(confidence: {confidence:.0%})"
            )

            obs = {
                "type": cat_def["obs_type"],
                "target": target,
                "approach": cat_def["obs_approach"],
                "origin": "hypothesis_insight",
                "strength": round(strength, 3),
                "novelty": 0.7 if category == "refuted_surprise" else 0.5,
                "risk": 0.15,
                "impact": round(impact, 3),
                "check": f"hypothesis_{h.get('status', 'unknown')}",
                "metric": (
                    f"confidence={confidence:.0%}, "
                    f"domain={domain}"
                ),
                "evidence": evidence,
                "detail": (
                    f"{h.get('status', '').title()}: "
                    f"{hypothesis_text[:120]}"
                ),
            }

            # Experiment-backed observations get boosted
            if h.get("experiment_id"):
                obs["strength"] = min(1.0, obs["strength"] + 0.15)
                obs["novelty"] = min(1.0, obs["novelty"] + 0.1)

            observations.append(obs)

            if len(observations) >= _MAX_OBSERVATIONS_PER_TICK:
                break

        # Clear emitted entries to prevent re-emission
        self._recent_resolved = []

        return observations

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _read_resolved_hypotheses(self) -> List[Dict]:
        """Read newly resolved hypotheses since last read. Read-only."""
        hypotheses = []
        db_path = Path(HYPOTHESIS_DB)

        if not db_path.exists():
            return hypotheses

        try:
            conn = sqlite3.connect(str(db_path), timeout=5)
            try:
                conn.row_factory = sqlite3.Row

                cursor = conn.execute(
                    "SELECT id, hypothesis, prediction, status, result, "
                    "confidence, confidence_delta, domain, source, "
                    "experiment_id, experiment_station, test_method, "
                    "resolved_at, updated_at, revision_depth "
                    "FROM hypotheses "
                    "WHERE status IN ('confirmed', 'refuted') "
                    "AND updated_at > ? "
                    "ORDER BY updated_at ASC "
                    "LIMIT ?",
                    (self._last_read_ts, _MAX_HYPOTHESES_PER_READ),
                )

                for row in cursor:
                    hypotheses.append(dict(row))

                # Update watermark
                if hypotheses:
                    self._last_read_ts = hypotheses[-1]["updated_at"]
            finally:
                conn.close()

        except sqlite3.OperationalError as e:
            LOG.debug("hypothesis_engine.db busy, will retry: %s", e)
        except Exception as e:
            LOG.warning("Error reading hypothesis_engine.db: %s", e)

        return hypotheses

    def _classify(self, h: dict) -> Optional[str]:
        """Classify a resolved hypothesis into a category."""
        status = h.get("status", "")

        if status == "confirmed":
            if h.get("experiment_id"):
                return "experiment_insight"
            return "confirmed_discovery"

        if status == "refuted":
            return "refuted_surprise"

        return None

    def _compute_surprise_amplitude(self, h: dict, cat_def: dict) -> float:
        """Compute precision-weighted wave amplitude (Active Inference).

        Surprise = base_amplitude × precision_weight
        where precision = confidence before resolution.

        High-confidence refutation → high surprise → strong learning signal.
        Low-confidence confirmation → expected → weak signal.
        """
        base = cat_def["wave_amplitude"]
        confidence = h.get("confidence", 0.5)
        conf_delta = abs(h.get("confidence_delta", 0))

        if h.get("status") == "refuted":
            # Refuted at high confidence = very surprising
            # precision_weight = 1 + confidence (range 1.0-1.95)
            precision_weight = 1.0 + confidence * 0.95
        elif h.get("status") == "confirmed":
            # Confirmed at low confidence = somewhat surprising
            # precision_weight = 1 + (1 - confidence) * 0.5
            precision_weight = 1.0 + (1.0 - confidence) * 0.5
        else:
            precision_weight = 1.0

        # Experiment-backed resolutions get slight boost
        if h.get("experiment_id"):
            precision_weight += 0.1

        amplitude = base * precision_weight
        return min(0.5, round(amplitude, 3))

    def _check_accuracy_trend(self) -> Optional[Wave]:
        """Detect prediction accuracy trends across rolling window."""
        if len(self._resolution_history) < 5:
            return None

        confirmed = self._resolution_history.count("confirmed")
        total = len(self._resolution_history)
        accuracy = confirmed / total

        now = time.time()

        if accuracy > 0.7:
            cat = "prediction_accuracy_high"
            last_wave = self._last_wave_ts.get(cat, 0)
            if (now - last_wave) < _WAVE_COOLDOWN_S:
                return None
            cat_def = _CATEGORIES[cat]
            self._last_wave_ts[cat] = now
            return Wave(
                target_field=cat_def["wave_field"],
                amplitude=cat_def["wave_amplitude"],
                decay=cat_def["wave_decay"],
                source=self.name,
                metadata={
                    "category": cat,
                    "accuracy": round(accuracy, 3),
                    "sample_size": total,
                },
            )

        if accuracy < 0.3:
            cat = "prediction_accuracy_low"
            last_wave = self._last_wave_ts.get(cat, 0)
            if (now - last_wave) < _WAVE_COOLDOWN_S:
                return None
            cat_def = _CATEGORIES[cat]
            self._last_wave_ts[cat] = now
            return Wave(
                target_field=cat_def["wave_field"],
                amplitude=cat_def["wave_amplitude"],
                decay=cat_def["wave_decay"],
                source=self.name,
                metadata={
                    "category": cat,
                    "accuracy": round(accuracy, 3),
                    "sample_size": total,
                },
            )

        return None
