#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qubo_builder.py — Frank-State → QUBO Matrix (v3)

Schema v3: 43 Variablen
    [0-3]   Entity:     therapist, mirror, atlas, muse              (one-hot)
    [4-6]   Intent:     update, review, creative                     (one-hot)
    [7-9]   Phase:      idle, engaged, reflecting                    (one-hot)
    [10-12] Mode:       meeting, project, focus                      (one-hot)
    [13-14] Mood:       positive, negative                           (one-hot)
    [15-17] Precision:  low, mid, high                               (one-hot)
    [18-20] Risk:       low, mid, high                               (one-hot)
    [21-23] Empathy:    low, mid, high                               (one-hot)
    [24-26] Autonomy:   low, mid, high                               (one-hot)
    [27-29] Vigilance:  low, mid, high                               (one-hot)
    [30-32] Task load:  idle, light, heavy                           (one-hot)
    [33-35] Engagement: absent, passive, active                      (one-hot)
    [36]    Prediction: surprise_high                                 (binary)
    [37]    Confidence: anchor_high                                   (binary)
    [38]    Goal:       has_urgent_goal                               (binary)
    [39]    Coherence:  reflector_aligned (current ≈ optimal)        (binary)
    [40]    AURA:       aura_anomaly_detected                        (binary)
    [41]    AURA:       aura_grid_entropy_high                       (binary)
    [42]    AURA:       aura_zone_contrast_high                      (binary)

Changes from v2 (n=40):
    - AURA reverse integration: QR reads AURA grid anomalies, entropy,
      zone contrast to close the feedback loop
    - 3 new binary variables for AURA state awareness
    - HTTP fetch from AURA headless /introspect/json with crash-safe fallback
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

LOG = logging.getLogger("quantum_reflector.qubo_builder")

# ============ VARIABLE SCHEMA ============

N_VARIABLES = 43

# AURA headless URL (configurable via env, default localhost:8098)
AURA_URL = os.environ.get("AURA_HEADLESS_URL", "http://127.0.0.1:8098")
AURA_FETCH_TIMEOUT = 3.0  # seconds — crash-safe, never blocks QR

LABELS = [
    # Entities (one-hot, idx 0-3)
    "entity_therapist", "entity_mirror", "entity_atlas", "entity_muse",
    # Intent (one-hot, idx 4-6)
    "intent_update", "intent_review", "intent_creative",
    # Phase (one-hot, idx 7-9)
    "phase_idle", "phase_engaged", "phase_reflecting",
    # Mode (one-hot, idx 10-12)
    "mode_meeting", "mode_project", "mode_focus",
    # Mood (one-hot, idx 13-14)
    "mood_positive", "mood_negative",
    # Precision (one-hot, idx 15-17)
    "precision_low", "precision_mid", "precision_high",
    # Risk (one-hot, idx 18-20)
    "risk_low", "risk_mid", "risk_high",
    # Empathy (one-hot, idx 21-23)
    "empathy_low", "empathy_mid", "empathy_high",
    # Autonomy (one-hot, idx 24-26)
    "autonomy_low", "autonomy_mid", "autonomy_high",
    # Vigilance (one-hot, idx 27-29)
    "vigilance_low", "vigilance_mid", "vigilance_high",
    # Task load (one-hot, idx 30-32)
    "task_idle", "task_light", "task_heavy",
    # Engagement (one-hot, idx 33-35)
    "engagement_absent", "engagement_passive", "engagement_active",
    # Binaries (idx 36-39)
    "surprise_high", "confidence_high", "goal_urgent", "reflector_aligned",
    # AURA reverse integration (idx 40-42)
    "aura_anomaly_detected", "aura_entropy_high", "aura_zone_contrast_high",
]

# Index groups
IDX_ENTITY    = (0, 1, 2, 3)
IDX_INTENT    = (4, 5, 6)
IDX_PHASE     = (7, 8, 9)
IDX_MODE      = (10, 11, 12)
IDX_MOOD      = (13, 14)
IDX_PRECISION = (15, 16, 17)
IDX_RISK      = (18, 19, 20)
IDX_EMPATHY   = (21, 22, 23)
IDX_AUTONOMY  = (24, 25, 26)
IDX_VIGILANCE = (27, 28, 29)
IDX_TASKLOAD  = (30, 31, 32)
IDX_ENGAGE    = (33, 34, 35)

ONE_HOT_GROUPS: List[Tuple[int, ...]] = [
    IDX_ENTITY, IDX_INTENT, IDX_PHASE, IDX_MODE, IDX_MOOD,
    IDX_PRECISION, IDX_RISK, IDX_EMPATHY, IDX_AUTONOMY, IDX_VIGILANCE,
    IDX_TASKLOAD, IDX_ENGAGE,
]

# E-PQ discretization thresholds
EPQ_LOW_THRESHOLD = -0.10
EPQ_HIGH_THRESHOLD = 0.10

# ============ CONSTRAINT STRENGTHS ============

ONE_HOT_PENALTY = 5.0

# Logical couplings: (i, j) → strength
# Negative = encouraged when both active, Positive = penalized
IMPLICATIONS = {
    # --- Phase + E-PQ coherence ---
    # Reflecting: empathy_high + precision_mid encouraged
    (9, 23): -1.5,    # reflecting + empathy_high
    (9, 16): -0.6,    # reflecting + precision_mid

    # Engaged: vigilance_high + precision_high encouraged
    (8, 29): -1.0,    # engaged + vigilance_high
    (8, 17): -0.8,    # engaged + precision_high

    # Idle: low vigilance + low precision natural
    (7, 15): -0.4,    # idle + precision_low
    (7, 27): -0.5,    # idle + vigilance_low
    (7, 17): 0.5,     # idle + precision_high (unnatural)
    (7, 29): 0.6,     # idle + vigilance_high (unnatural)

    # --- Mode + E-PQ coherence ---
    # Focus: precision_high + vigilance_high
    (12, 17): -1.2,   # focus + precision_high
    (12, 29): -0.8,   # focus + vigilance_high

    # Meeting: empathy_high + autonomy_mid
    (10, 23): -1.0,   # meeting + empathy_high
    (10, 25): -0.6,   # meeting + autonomy_mid

    # Project: precision_mid + risk_mid balanced
    (11, 16): -0.7,   # project + precision_mid
    (11, 19): -0.5,   # project + risk_mid

    # --- Intent + E-PQ coherence ---
    # Review: precision_high mandatory
    (5, 17): -1.3,    # review + precision_high
    (5, 15): 0.8,     # review + precision_low (bad)

    # Creative: risk_high + empathy encouraged
    (6, 20): -1.0,    # creative + risk_high
    (6, 23): -0.6,    # creative + empathy_high

    # Update: balanced, slight precision
    (4, 16): -0.5,    # update + precision_mid

    # --- Mood + E-PQ coherence ---
    # Positive mood: autonomy_high, empathy encouraged
    (13, 26): -0.7,   # positive + autonomy_high
    (13, 23): -0.5,   # positive + empathy_high

    # Negative mood: vigilance_high, risk_low defensive
    (14, 29): -0.8,   # negative + vigilance_high
    (14, 18): -0.5,   # negative + risk_low

    # --- Entity + Phase/Mode coherence ---
    # Mirror (Kairos) → reflecting
    (1, 9): -1.0,     # mirror + reflecting
    # Atlas → project mode
    (2, 11): -0.8,    # atlas + project
    # Muse (Echo) → creative intent
    (3, 6): -1.2,     # muse + creative
    # Therapist → engaged + empathy
    (0, 8): -0.5,     # therapist + engaged
    (0, 23): -0.8,    # therapist + empathy_high

    # --- Engagement + Phase coherence ---
    # Active engagement → engaged phase
    (35, 8): -0.8,    # active + engaged
    # Passive → idle or reflecting
    (34, 7): -0.5,    # passive + idle
    (34, 9): -0.4,    # passive + reflecting
    # Absent → idle
    (33, 7): -0.7,    # absent + idle

    # --- Task load coherence ---
    # Heavy task load → engaged phase, focus mode
    (32, 8): -0.6,    # heavy + engaged
    (32, 12): -0.5,   # heavy + focus
    # Idle tasks → idle phase natural
    (30, 7): -0.4,    # task_idle + phase_idle

    # --- Surprise + Vigilance ---
    (36, 29): -0.8,   # surprise_high + vigilance_high

    # --- Confidence + Autonomy ---
    (37, 26): -0.7,   # confidence_high + autonomy_high

    # --- Goal urgency + Engagement ---
    (38, 35): -0.6,   # goal_urgent + engagement_active
    (38, 8): -0.5,    # goal_urgent + engaged

    # --- Coherence aligned → stability ---
    (39, 13): -0.3,   # aligned + positive mood
    (39, 25): -0.2,   # aligned + autonomy_mid (balanced)

    # --- AURA reverse integration ---
    # Anomaly detected → heightened vigilance + reflecting
    (40, 29): -0.9,   # aura_anomaly + vigilance_high
    (40, 9): -0.6,    # aura_anomaly + reflecting
    (40, 14): -0.3,   # aura_anomaly + negative mood (anomaly = tension)

    # High grid entropy → creative intent, risk tolerance
    (41, 6): -0.7,    # aura_entropy_high + creative
    (41, 20): -0.5,   # aura_entropy_high + risk_high
    (41, 17): 0.4,    # aura_entropy_high + precision_high (entropy ≠ precision)

    # High zone contrast → engaged phase, focus mode
    (42, 8): -0.6,    # aura_zone_contrast_high + engaged
    (42, 12): -0.5,   # aura_zone_contrast_high + focus
    (42, 29): -0.4,   # aura_zone_contrast_high + vigilance_high
}


# ============ STATE ============

@dataclass
class FrankState:
    """Snapshot of Frank's current state from the DBs."""
    # Entity
    last_entity: Optional[str] = None
    # E-PQ vectors
    precision: float = 0.0
    risk: float = 0.0
    empathy: float = 0.0
    autonomy: float = 0.0
    vigilance: float = 0.0
    mood: float = 0.0
    confidence_anchor: float = 0.5
    # Consciousness
    attention_focus: Optional[str] = None
    # Inferred
    current_phase: str = "idle"
    current_mode: str = "project"
    current_intent: str = "update"
    # New v2 fields
    active_goals: int = 0
    has_urgent_goal: bool = False
    surprise_level: float = 0.0
    chat_recency_s: float = 9999.0
    # AURA reverse integration
    aura_anomaly_detected: bool = False
    aura_grid_entropy: float = 0.0
    aura_zone_contrast: float = 0.0
    # Timestamp
    read_at: float = 0.0


def _epq_bucket(val: float) -> str:
    """Discretize E-PQ value into low/mid/high."""
    if val < EPQ_LOW_THRESHOLD:
        return "low"
    elif val > EPQ_HIGH_THRESHOLD:
        return "high"
    return "mid"


# ============ BUILDER ============

class QUBOBuilder:
    """
    Builds the QUBO matrix from Frank's current state.

    Two layers:
    1. Structural constraints (static, cached): One-Hot-Penalties, Implications
    2. State-dependent linear terms (dynamic, incremental): Plausibilities from DBs
    """

    def __init__(self, db_dir: Path):
        self.db_dir = db_dir
        self._last_state: Optional[FrankState] = None
        self._last_linear: Optional[np.ndarray] = None
        self._quad: Optional[np.ndarray] = None

    @property
    def n(self) -> int:
        return N_VARIABLES

    @property
    def labels(self) -> List[str]:
        return LABELS

    @property
    def one_hot_groups(self) -> List[Tuple[int, ...]]:
        return ONE_HOT_GROUPS

    def _build_quad_matrix(self) -> np.ndarray:
        """Build the static quadratic coupling matrix (cached)."""
        Q = np.zeros((self.n, self.n), dtype=np.float64)

        for group in ONE_HOT_GROUPS:
            for i in group:
                for j in group:
                    if i < j:
                        Q[i, j] = ONE_HOT_PENALTY
                        Q[j, i] = ONE_HOT_PENALTY

        for (i, j), strength in IMPLICATIONS.items():
            Q[i, j] = strength
            Q[j, i] = strength

        return Q

    def get_quad_matrix(self) -> np.ndarray:
        """Return the (cached) quadratic matrix."""
        if self._quad is None:
            self._quad = self._build_quad_matrix()
        return self._quad

    def read_frank_state(self) -> FrankState:
        """Read Frank's current state from the databases."""
        state = FrankState(read_at=time.time())

        # === E-PQ from world_experience.db ===
        try:
            we_db = self.db_dir / "world_experience.db"
            if we_db.exists():
                conn = sqlite3.connect(str(we_db), timeout=5.0)
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT precision_val, risk_val, empathy_val, autonomy_val, "
                    "vigilance_val, mood_buffer, confidence_anchor FROM personality_state "
                    "ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if row:
                    state.precision = float(row["precision_val"] or 0)
                    state.risk = float(row["risk_val"] or 0)
                    state.empathy = float(row["empathy_val"] or 0)
                    state.autonomy = float(row["autonomy_val"] or 0)
                    state.vigilance = float(row["vigilance_val"] or 0)
                    state.mood = float(row["mood_buffer"] or 0)
                    state.confidence_anchor = float(row["confidence_anchor"] or 0.5)
                conn.close()
        except Exception as exc:
            LOG.warning("E-PQ read failed: %s", exc)

        # === Consciousness state ===
        try:
            c_db = self.db_dir / "consciousness.db"
            if c_db.exists():
                conn = sqlite3.connect(str(c_db), timeout=5.0)
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT attention_focus, mood_value FROM workspace_state "
                    "ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if row:
                    state.attention_focus = row["attention_focus"]
                # Goals
                goal_rows = conn.execute(
                    "SELECT COUNT(*) as cnt, MAX(priority) as max_p "
                    "FROM goals WHERE status='active'"
                ).fetchone()
                if goal_rows:
                    state.active_goals = int(goal_rows["cnt"] or 0)
                    state.has_urgent_goal = float(goal_rows["max_p"] or 0) > 0.7
                # Predictions (surprise)
                pred = conn.execute(
                    "SELECT surprise FROM predictions "
                    "WHERE resolved=1 ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if pred:
                    state.surprise_level = float(pred["surprise"] or 0)
                conn.close()
        except Exception as exc:
            LOG.warning("Consciousness read failed: %s", exc)

        # === Chat recency ===
        try:
            cm_db = self.db_dir / "chat_memory.db"
            if cm_db.exists():
                conn = sqlite3.connect(str(cm_db), timeout=5.0)
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT timestamp FROM messages WHERE is_user=1 "
                    "ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if row:
                    ts = float(row["timestamp"] or 0)
                    state.chat_recency_s = time.time() - ts
                conn.close()
        except Exception as exc:
            LOG.debug("Chat recency read failed: %s", exc)

        # === Last active entity ===
        try:
            _last_ts = 0.0
            for ename in ("therapist", "mirror", "atlas", "muse"):
                edb = self.db_dir / f"{ename}.db"
                if edb.exists():
                    conn = sqlite3.connect(str(edb), timeout=5.0)
                    conn.row_factory = sqlite3.Row
                    row = conn.execute(
                        "SELECT start_time FROM sessions ORDER BY id DESC LIMIT 1"
                    ).fetchone()
                    if row:
                        ts = float(row["start_time"] or 0)
                        if ts > _last_ts:
                            _last_ts = ts
                            state.last_entity = ename
                    conn.close()
        except Exception as exc:
            LOG.warning("Entity read failed: %s", exc)

        # === Infer phase from attention ===
        focus = (state.attention_focus or "").lower()
        if "idle" in focus or "curiosity" in focus:
            state.current_phase = "idle"
        elif "reflect" in focus or "prediction" in focus or "consolidat" in focus:
            state.current_phase = "reflecting"
        else:
            state.current_phase = "engaged"

        # === AURA reverse integration (crash-safe HTTP fetch) ===
        try:
            req = urllib.request.Request(
                f"{AURA_URL}/introspect/json?depth=full",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=AURA_FETCH_TIMEOUT) as resp:
                aura_data = json.loads(resp.read().decode("utf-8"))

            # Anomalies
            anomalies = aura_data.get("anomalies", [])
            state.aura_anomaly_detected = len(anomalies) > 0

            # Grid entropy
            g = aura_data.get("global", {})
            state.aura_grid_entropy = float(g.get("entropy", 0.0))

            # Zone contrast: max density - min density across zones
            zones = aura_data.get("zones", {})
            if zones:
                densities = [z.get("density", 0.0) for z in zones.values()]
                state.aura_zone_contrast = max(densities) - min(densities)
        except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
            LOG.debug("AURA fetch skipped (service down?): %s", exc)
        except Exception as exc:
            LOG.warning("AURA fetch unexpected error: %s", exc)

        self._last_state = state
        return state

    def build_linear(self, state: FrankState) -> np.ndarray:
        """Build state-dependent linear terms."""
        h = np.zeros(self.n, dtype=np.float64)

        # === Entity [0-3] ===
        entity_map = {"therapist": 0, "mirror": 1, "atlas": 2, "muse": 3}
        for name, idx in entity_map.items():
            h[idx] = -0.4 if name == state.last_entity else -0.2

        # === Intent [4-6] ===
        h[4] = -0.5   # update
        h[5] = -0.3   # review
        h[6] = -0.3   # creative

        # === Phase [7-9] ===
        phase_map = {"idle": 7, "engaged": 8, "reflecting": 9}
        for phase, idx in phase_map.items():
            h[idx] = -0.6 if phase == state.current_phase else -0.1

        # === Mode [10-12] ===
        mode_map = {"meeting": 10, "project": 11, "focus": 12}
        for mode, idx in mode_map.items():
            h[idx] = -0.5 if mode == state.current_mode else -0.2

        # === Mood [13-14] ===
        if state.mood > 0:
            h[13], h[14] = -0.5, 0.1
        else:
            h[13], h[14] = 0.1, -0.5

        # === E-PQ tri-state [15-29] ===
        epq_groups = [
            (state.precision, 15),
            (state.risk, 18),
            (state.empathy, 21),
            (state.autonomy, 24),
            (state.vigilance, 27),
        ]
        for val, base_idx in epq_groups:
            bucket = _epq_bucket(val)
            strength = 0.3 + 0.3 * abs(val)  # stronger preference for extreme values
            for offset, level in enumerate(("low", "mid", "high")):
                idx = base_idx + offset
                if level == bucket:
                    h[idx] = -strength
                else:
                    h[idx] = 0.05  # slight penalty for non-matching

        # === Task load [30-32] ===
        goals = state.active_goals
        if goals == 0:
            h[30], h[31], h[32] = -0.5, -0.1, 0.1
        elif goals <= 3:
            h[30], h[31], h[32] = -0.1, -0.5, -0.1
        else:
            h[30], h[31], h[32] = 0.1, -0.1, -0.5

        # === Engagement [33-35] ===
        rec = state.chat_recency_s
        if rec > 600:       # >10min → absent
            h[33], h[34], h[35] = -0.5, -0.1, 0.1
        elif rec > 120:     # >2min → passive
            h[33], h[34], h[35] = -0.1, -0.5, -0.1
        else:               # recent → active
            h[33], h[34], h[35] = 0.1, -0.1, -0.5

        # === Binaries: very strong grounding ===
        # Must outweigh 2*sum(implications) to prevent false activation.
        # Max coupling per binary is ~2.2 (two implications * 2x from symmetric Q).
        # Penalty of 3.0 guarantees grounding even with all couplings active.

        # Surprise [36]
        h[36] = -0.5 if state.surprise_level > 0.3 else 3.0

        # Confidence [37]
        h[37] = -0.5 if state.confidence_anchor > 0.6 else 3.0

        # Goal urgency [38]
        h[38] = -0.5 if state.has_urgent_goal else 3.0

        # Coherence aligned [39]
        h[39] = -0.2  # Weakly encouraged; low coupling impact

        # === AURA reverse integration [40-42] ===
        # Grounding penalty 3.0 when inactive, encouragement when active
        # (same pattern as other binaries: must outweigh coupling sum)

        # Anomaly detected [40]
        h[40] = -0.5 if state.aura_anomaly_detected else 3.0

        # Grid entropy high [41] — threshold: 0.5 (mid-range Shannon entropy)
        h[41] = -0.5 if state.aura_grid_entropy > 0.5 else 3.0

        # Zone contrast high [42] — threshold: 0.3 (significant density spread)
        h[42] = -0.5 if state.aura_zone_contrast > 0.3 else 3.0

        self._last_linear = h.copy()
        return h

    def build_linear_incremental(
        self, old_state: FrankState, new_state: FrankState
    ) -> Optional[np.ndarray]:
        """
        Incremental linear rebuild: only recalculate changed indices.
        Returns updated linear vector, or None if full rebuild needed.
        """
        if self._last_linear is None:
            return None

        h = self._last_linear.copy()
        changed_indices = set()

        # Entity changed?
        if old_state.last_entity != new_state.last_entity:
            entity_map = {"therapist": 0, "mirror": 1, "atlas": 2, "muse": 3}
            for name, idx in entity_map.items():
                h[idx] = -0.4 if name == new_state.last_entity else -0.2
                changed_indices.update(IDX_ENTITY)

        # Phase changed?
        if old_state.current_phase != new_state.current_phase:
            phase_map = {"idle": 7, "engaged": 8, "reflecting": 9}
            for phase, idx in phase_map.items():
                h[idx] = -0.6 if phase == new_state.current_phase else -0.1
            changed_indices.update(IDX_PHASE)

        # Mode changed?
        if old_state.current_mode != new_state.current_mode:
            mode_map = {"meeting": 10, "project": 11, "focus": 12}
            for mode, idx in mode_map.items():
                h[idx] = -0.5 if mode == new_state.current_mode else -0.2
            changed_indices.update(IDX_MODE)

        # Mood polarity changed?
        if (old_state.mood > 0) != (new_state.mood > 0):
            if new_state.mood > 0:
                h[13], h[14] = -0.5, 0.1
            else:
                h[13], h[14] = 0.1, -0.5
            changed_indices.update(IDX_MOOD)

        # E-PQ bucket changes
        for attr, base_idx in [("precision", 15), ("risk", 18), ("empathy", 21),
                                ("autonomy", 24), ("vigilance", 27)]:
            old_val = getattr(old_state, attr)
            new_val = getattr(new_state, attr)
            if _epq_bucket(old_val) != _epq_bucket(new_val) or abs(old_val - new_val) > 0.15:
                strength = 0.3 + 0.3 * abs(new_val)
                bucket = _epq_bucket(new_val)
                for offset, level in enumerate(("low", "mid", "high")):
                    idx = base_idx + offset
                    h[idx] = -strength if level == bucket else 0.05
                    changed_indices.add(idx)

        # Task load changed?
        if old_state.active_goals != new_state.active_goals:
            goals = new_state.active_goals
            if goals == 0:
                h[30], h[31], h[32] = -0.5, -0.1, 0.1
            elif goals <= 3:
                h[30], h[31], h[32] = -0.1, -0.5, -0.1
            else:
                h[30], h[31], h[32] = 0.1, -0.1, -0.5
            changed_indices.update(IDX_TASKLOAD)

        # Engagement changed?
        old_eng = "absent" if old_state.chat_recency_s > 600 else "passive" if old_state.chat_recency_s > 120 else "active"
        new_eng = "absent" if new_state.chat_recency_s > 600 else "passive" if new_state.chat_recency_s > 120 else "active"
        if old_eng != new_eng:
            rec = new_state.chat_recency_s
            if rec > 600:
                h[33], h[34], h[35] = -0.5, -0.1, 0.1
            elif rec > 120:
                h[33], h[34], h[35] = -0.1, -0.5, -0.1
            else:
                h[33], h[34], h[35] = 0.1, -0.1, -0.5
            changed_indices.update(IDX_ENGAGE)

        # Surprise threshold crossing?
        old_surp = old_state.surprise_level > 0.3
        new_surp = new_state.surprise_level > 0.3
        if old_surp != new_surp:
            h[36] = (-0.3 - 0.3 * new_state.surprise_level) if new_surp else 0.1
            changed_indices.add(36)

        # Confidence threshold crossing?
        old_conf = old_state.confidence_anchor > 0.6
        new_conf = new_state.confidence_anchor > 0.6
        if old_conf != new_conf:
            h[37] = -0.4 if new_conf else 0.1
            changed_indices.add(37)

        # Goal urgency?
        if old_state.has_urgent_goal != new_state.has_urgent_goal:
            h[38] = -0.5 if new_state.has_urgent_goal else 0.1
            changed_indices.add(38)

        # AURA anomaly?
        if old_state.aura_anomaly_detected != new_state.aura_anomaly_detected:
            h[40] = -0.5 if new_state.aura_anomaly_detected else 3.0
            changed_indices.add(40)

        # AURA entropy threshold crossing?
        old_ent_high = old_state.aura_grid_entropy > 0.5
        new_ent_high = new_state.aura_grid_entropy > 0.5
        if old_ent_high != new_ent_high:
            h[41] = -0.5 if new_ent_high else 3.0
            changed_indices.add(41)

        # AURA zone contrast threshold crossing?
        old_ctr_high = old_state.aura_zone_contrast > 0.3
        new_ctr_high = new_state.aura_zone_contrast > 0.3
        if old_ctr_high != new_ctr_high:
            h[42] = -0.5 if new_ctr_high else 3.0
            changed_indices.add(42)

        if not changed_indices:
            return None  # Nothing changed

        LOG.debug("Incremental rebuild: %d indices changed: %s",
                  len(changed_indices), sorted(changed_indices))
        self._last_linear = h.copy()
        return h

    def build(self) -> Tuple[np.ndarray, np.ndarray, FrankState]:
        """Full QUBO build."""
        state = self.read_frank_state()
        Q = self.get_quad_matrix()

        # Try incremental first
        if self._last_state is not None and self._last_linear is not None:
            incremental = self.build_linear_incremental(self._last_state, state)
            if incremental is not None:
                LOG.debug("Used incremental linear rebuild")
                self._last_state = state
                return incremental, Q, state

        # Full rebuild
        linear = self.build_linear(state)
        return linear, Q, state

    def state_changed(self, new_state: FrankState) -> bool:
        """
        Check if state changed enough to warrant re-solving.
        Uses cumulative drift detection across all vectors.
        """
        if self._last_state is None:
            return True

        old = self._last_state

        # Categorical changes: always trigger
        if old.last_entity != new_state.last_entity:
            return True
        if old.current_phase != new_state.current_phase:
            return True
        if old.current_mode != new_state.current_mode:
            return True
        if (old.mood > 0) != (new_state.mood > 0):
            return True
        if old.has_urgent_goal != new_state.has_urgent_goal:
            return True

        # E-PQ bucket crossing (low/mid/high changed)
        for attr in ("precision", "risk", "empathy", "autonomy", "vigilance"):
            if _epq_bucket(getattr(old, attr)) != _epq_bucket(getattr(new_state, attr)):
                return True

        # Engagement level changed
        old_eng = "absent" if old.chat_recency_s > 600 else "passive" if old.chat_recency_s > 120 else "active"
        new_eng = "absent" if new_state.chat_recency_s > 600 else "passive" if new_state.chat_recency_s > 120 else "active"
        if old_eng != new_eng:
            return True

        # Cumulative drift: sum of absolute deltas across all continuous vars
        cumulative_drift = 0.0
        for attr in ("precision", "risk", "empathy", "autonomy", "vigilance", "mood"):
            cumulative_drift += abs(getattr(new_state, attr) - getattr(old, attr))

        if cumulative_drift > 0.4:
            LOG.debug("Cumulative drift %.3f > 0.4, triggering re-solve", cumulative_drift)
            return True

        # Task load change
        if old.active_goals != new_state.active_goals:
            return True

        # Surprise threshold crossing
        if (old.surprise_level > 0.3) != (new_state.surprise_level > 0.3):
            return True

        # AURA state changes
        if old.aura_anomaly_detected != new_state.aura_anomaly_detected:
            return True
        if (old.aura_grid_entropy > 0.5) != (new_state.aura_grid_entropy > 0.5):
            return True
        if (old.aura_zone_contrast > 0.3) != (new_state.aura_zone_contrast > 0.3):
            return True

        return False

    def interpret_solution(self, x: np.ndarray) -> Dict[str, Any]:
        """Interpret a QUBO solution into readable form."""
        def _find_active(indices, names):
            for idx, name in zip(indices, names):
                if x[idx] > 0.5:
                    return name
            return None

        entity = _find_active(IDX_ENTITY, ("therapist", "mirror", "atlas", "muse"))
        intent = _find_active(IDX_INTENT, ("update", "review", "creative"))
        phase = _find_active(IDX_PHASE, ("idle", "engaged", "reflecting"))
        mode = _find_active(IDX_MODE, ("meeting", "project", "focus"))
        mood = _find_active(IDX_MOOD, ("positive", "negative"))

        precision = _find_active(IDX_PRECISION, ("low", "mid", "high"))
        risk = _find_active(IDX_RISK, ("low", "mid", "high"))
        empathy = _find_active(IDX_EMPATHY, ("low", "mid", "high"))
        autonomy = _find_active(IDX_AUTONOMY, ("low", "mid", "high"))
        vigilance = _find_active(IDX_VIGILANCE, ("low", "mid", "high"))

        task_load = _find_active(IDX_TASKLOAD, ("idle", "light", "heavy"))
        engagement = _find_active(IDX_ENGAGE, ("absent", "passive", "active"))

        return {
            "entity": entity,
            "intent": intent,
            "phase": phase,
            "mode": mode,
            "mood": mood,
            "epq": {
                "precision": precision,
                "risk": risk,
                "empathy": empathy,
                "autonomy": autonomy,
                "vigilance": vigilance,
            },
            "task_load": task_load,
            "engagement": engagement,
            "surprise_high": x[36] > 0.5,
            "confidence_high": x[37] > 0.5,
            "goal_urgent": x[38] > 0.5,
            "reflector_aligned": x[39] > 0.5,
            "aura_anomaly_detected": x[40] > 0.5,
            "aura_entropy_high": x[41] > 0.5,
            "aura_zone_contrast_high": x[42] > 0.5,
            "active_labels": [LABELS[i] for i in range(self.n) if x[i] > 0.5],
        }
