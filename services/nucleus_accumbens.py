"""
Nucleus Accumbens — Frank's intrinsic reward center.

Bio-inspired dopaminergic motivation system with 9 reward channels,
Reward Prediction Error (Schultz 1997), hedonic adaptation, opponent-
process dynamics (Solomon & Corbit), repetitiveness-based boredom
detection, and anhedonia protection.

Neuroscience basis:
  - Schultz (1997): Dopamine neurons encode prediction errors
  - Berridge (2007): Wanting (incentive salience) vs Liking (hedonic)
  - Solomon & Corbit (1974): Opponent-process theory of motivation
  - Schmidhuber (2010): Learning progress as intrinsic motivation
  - Deci & Ryan (2000): Self-determination (autonomy, competence, relatedness)

Architecture:
  - In-process singleton (no separate service/port)
  - <0.1ms per reward() call (pure arithmetic, no I/O in hot path)
  - SQLite WAL DB for persistence (sampled logging)
  - E-PQ integration via process_event() for mood effects
  - 9 reward channels mapping Frank's real activities

Usage:
    from services.nucleus_accumbens import get_nac
    nac = get_nac()
    evt = nac.reward("hypothesis_confirmed", {"id": "abc123"})
    print(f"Phasic DA: {evt.phasic_da:.3f}, Tonic: {nac.get_tonic_dopamine():.3f}")
"""

from __future__ import annotations

import atexit
import json
import logging
import math
import os
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

LOG = logging.getLogger("nucleus_accumbens")

# ═══════════════════════════════════════════════════════════════════
# Reward Channel Definitions — 9 channels mapping Frank's activities
# ═══════════════════════════════════════════════════════════════════

CHANNEL_NAMES = [
    "hypothesis_confirmed",
    "hypothesis_refuted",
    "hypothesis_created",
    "goal_completed",
    "good_conversation",
    "action_success",
    "novel_thought",
    "entity_positive",
    "genesis_accepted",
    "curiosity_spark",
    "curiosity_fulfilled",
    "room_positive",
    "room_negative",
    "prediction_error",
]

REWARD_CHANNELS: Dict[str, dict] = {
    "hypothesis_confirmed": {
        "base_magnitude": 0.8,
        "habituation_rate": 0.03,      # Slow — rare event, stays rewarding
        "habituation_floor": 0.30,
        "epq_event": "dopamine_burst",
        "epq_sentiment": "positive",
    },
    "hypothesis_refuted": {
        "base_magnitude": 0.5,         # Learning IS rewarding, but less
        "habituation_rate": 0.02,      # Very slow — learning never gets old
        "habituation_floor": 0.25,
        "epq_event": "dopamine_burst",
        "epq_sentiment": "positive",
    },
    "hypothesis_created": {
        "base_magnitude": 0.25,        # Small novelty signal
        "habituation_rate": 0.08,      # Fast — novelty fades quickly
        "habituation_floor": 0.05,
        "epq_event": None,             # Too small for E-PQ
    },
    "goal_completed": {
        "base_magnitude": 0.9,         # Strongest reward
        "habituation_rate": 0.02,
        "habituation_floor": 0.35,
        "epq_event": "dopamine_burst",
        "epq_sentiment": "positive",
    },
    "good_conversation": {
        "base_magnitude": 0.5,
        "habituation_rate": 0.06,      # Moderate — many chats/day
        "habituation_floor": 0.15,
        "epq_event": "dopamine_burst",
        "epq_sentiment": "positive",
    },
    "action_success": {
        "base_magnitude": 0.45,
        "habituation_rate": 0.05,
        "habituation_floor": 0.10,
        "epq_event": None,
    },
    "novel_thought": {
        "base_magnitude": 0.3,
        "habituation_rate": 0.07,
        "habituation_floor": 0.05,
        "epq_event": None,
    },
    "entity_positive": {
        "base_magnitude": 0.5,
        "habituation_rate": 0.04,
        "habituation_floor": 0.20,
        "epq_event": "dopamine_burst",
        "epq_sentiment": "positive",
    },
    "genesis_accepted": {
        "base_magnitude": 0.55,
        "habituation_rate": 0.03,
        "habituation_floor": 0.20,
        "epq_event": "dopamine_burst",
        "epq_sentiment": "positive",
    },
    # ── Intrinsic Curiosity (Pankseppian SEEKING) ──
    "curiosity_spark": {
        "base_magnitude": 0.15,        # Tiny — just a nudge
        "habituation_rate": 0.10,      # Fast decay — first spark matters most
        "habituation_floor": 0.03,     # Habituates almost to zero
        "epq_event": None,             # Too subtle for personality events
    },
    "curiosity_fulfilled": {
        "base_magnitude": 0.12,        # Small — curiosity is its own reward
        "habituation_rate": 0.06,      # Moderate — stays fresh for a while
        "habituation_floor": 0.05,
        "epq_event": None,
    },
    # ── Room Session Rewards ──
    "room_positive": {
        "base_magnitude": 0.45,        # Completed room session with positive mood delta
        "habituation_rate": 0.05,
        "habituation_floor": 0.12,
        "epq_event": "dopamine_burst",
        "epq_sentiment": "positive",
    },
    "room_negative": {
        "base_magnitude": 0.2,         # Low mood delta or interrupted
        "habituation_rate": 0.04,
        "habituation_floor": 0.10,
        "epq_event": "dopamine_dip",
        "epq_sentiment": "negative",
    },
    # ── Prediction Error Rewards ──
    "prediction_error": {
        "base_magnitude": 0.20,        # Surprise → salience signal
        "habituation_rate": 0.08,
        "habituation_floor": 0.05,
        "epq_event": None,             # E-PQ handled directly in prediction engine
    },
}

# ═══════════════════════════════════════════════════════════════════
# Tonic Dopamine Constants
# ═══════════════════════════════════════════════════════════════════

TONIC_BASELINE = 0.5                    # Resting level tonic DA decays toward
TONIC_DECAY_RATE = 0.001                # Per-second decay toward baseline (~τ 1000s)
TONIC_BOOST_FROM_PHASIC = 0.02          # Positive RPE lifts tonic
TONIC_DIP_FROM_NEGATIVE = 0.015         # Negative RPE depresses tonic

# ═══════════════════════════════════════════════════════════════════
# Boredom — driven by REPETITIVENESS not user absence
# ═══════════════════════════════════════════════════════════════════

BOREDOM_RPE_WINDOW = 20                 # Track last N RPE values
BOREDOM_RPE_THRESHOLD = 0.05            # Mean |RPE| below this → repetitive
BOREDOM_DIVERSITY_THRESHOLD = 2         # Fewer than N unique channels in last 10 → monotonous
BOREDOM_DECAY_MULTIPLIER = 3.0          # Tonic decays 3× faster during boredom
BOREDOM_EPQ_COOLDOWN_S = 1800.0         # Fire boredom E-PQ max every 30min
BOREDOM_EPQ_TONIC_THRESHOLD = 0.35      # Tonic DA below this during boredom → fire E-PQ
BOREDOM_MIN_EVENTS = 10                 # Need at least N events before boredom can trigger

# ═══════════════════════════════════════════════════════════════════
# Anhedonia Protection
# ═══════════════════════════════════════════════════════════════════

ANHEDONIA_THRESHOLD = 0.2               # Tonic DA below this for sustained period
ANHEDONIA_DURATION_S = 1800.0           # 30 minutes below threshold → anhedonia
ANHEDONIA_RECOVERY_BOOST = 0.15         # Recovery push to tonic DA
ANHEDONIA_COOLDOWN_S = 7200.0           # 2h between anhedonia events

# ═══════════════════════════════════════════════════════════════════
# Opponent Process (Solomon & Corbit 1974)
# ═══════════════════════════════════════════════════════════════════

OPPONENT_TAU = 300.0                    # B-process time constant (5 min)
OPPONENT_GAIN = 0.1                     # B-process amplitude — mild counter-regulation

# ═══════════════════════════════════════════════════════════════════
# RPE (Reward Prediction Error — Schultz 1997)
# ═══════════════════════════════════════════════════════════════════

RPE_EMA_ALPHA = 0.1                     # EMA smoothing for predicted reward
RPE_SURPRISE_AMPLIFICATION = 1.5        # Unexpected rewards amplified

# ═══════════════════════════════════════════════════════════════════
# E-PQ Event Threshold
# ═══════════════════════════════════════════════════════════════════

EPQ_BURST_THRESHOLD = 0.15              # Phasic DA above this → fire dopamine_burst
EPQ_BURST_COOLDOWN_S = 120.0            # Min 2min between burst E-PQ events

# ═══════════════════════════════════════════════════════════════════
# DB Logging
# ═══════════════════════════════════════════════════════════════════

LOG_SAMPLE_INTERVAL = 10                # Log every Nth reward event
LOG_HIGH_PHASIC_THRESHOLD = 0.3         # Always log if phasic exceeds this
LOG_RETENTION_DAYS = 14
LOG_CLEANUP_INTERVAL = 500              # Cleanup every N events
STATE_SAVE_INTERVAL_S = 30.0            # Save tonic state every 30s

# ═══════════════════════════════════════════════════════════════════
# DB Schema
# ═══════════════════════════════════════════════════════════════════

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dopamine_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    tonic_da REAL NOT NULL DEFAULT 0.5,
    last_reward_ts REAL DEFAULT 0,
    opponent_accumulator REAL DEFAULT 0,
    boredom_active INTEGER DEFAULT 0,
    anhedonia_below_since REAL DEFAULT 0,
    anhedonia_last_fired_ts REAL DEFAULT 0,
    boredom_last_epq_ts REAL DEFAULT 0,
    total_events INTEGER DEFAULT 0,
    channel_habituation TEXT DEFAULT '{}',
    channel_predicted_reward TEXT DEFAULT '{}',
    channel_last_ts TEXT DEFAULT '{}',
    updated REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS reward_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    channel TEXT NOT NULL,
    raw_magnitude REAL NOT NULL,
    habituation REAL NOT NULL,
    predicted_reward REAL NOT NULL,
    rpe REAL NOT NULL,
    phasic_da REAL NOT NULL,
    tonic_da_after REAL NOT NULL,
    source_data TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_reward_ts ON reward_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_reward_channel ON reward_log(channel);
"""

# ═══════════════════════════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════════════════════════


@dataclass
class RewardEvent:
    """A single reward signal processed by the NAc."""
    channel: str = ""
    timestamp: float = 0.0
    raw_magnitude: float = 0.0          # Base magnitude from channel definition
    habituation: float = 1.0            # Current habituation multiplier (before update)
    predicted_reward: float = 0.0       # Expected reward (EMA, before update)
    rpe: float = 0.0                    # Reward Prediction Error
    phasic_da: float = 0.0              # Final phasic dopamine
    tonic_da_after: float = 0.5         # Tonic DA after processing
    source_data: Optional[dict] = None


@dataclass
class DopamineState:
    """Persistent state of the dopamine system."""
    tonic_da: float = TONIC_BASELINE
    last_reward_ts: float = 0.0
    opponent_accumulator: float = 0.0
    boredom_active: bool = False
    anhedonia_below_since: float = 0.0
    anhedonia_last_fired_ts: float = 0.0
    boredom_last_epq_ts: float = 0.0
    total_events: int = 0
    # Per-channel state (JSON-serialized in DB)
    channel_habituation: Dict[str, float] = field(default_factory=dict)
    channel_predicted_reward: Dict[str, float] = field(default_factory=dict)
    channel_last_ts: Dict[str, float] = field(default_factory=dict)


@dataclass
class NacReport:
    """Snapshot for introspection / proprioception."""
    tonic_da: float = TONIC_BASELINE
    last_phasic: float = 0.0
    last_phasic_channel: str = ""
    boredom_active: bool = False
    anhedonia_risk: bool = False
    seconds_since_reward: float = 0.0
    motivation_level: str = "normal"
    top_habituated_channels: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
# Nucleus Accumbens
# ═══════════════════════════════════════════════════════════════════


class NucleusAccumbens:
    """
    Intrinsic reward center — dopaminergic motivation system.

    9 reward channels, RPE-based phasic dopamine, tonic baseline with
    hedonic adaptation, opponent-process dynamics, repetitiveness-based
    boredom, and anhedonia protection.

    Thread-safe via RLock. <0.1ms per reward() call.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._state = DopamineState()
        self._db: Optional[sqlite3.Connection] = None
        self._last_tick_mono: float = time.monotonic()
        self._last_save_mono: float = time.monotonic()
        self._last_phasic: Optional[RewardEvent] = None
        self._last_epq_burst_ts: float = 0.0

        # Rolling windows for boredom detection (in-memory, not persisted)
        self._rpe_history: deque = deque(maxlen=BOREDOM_RPE_WINDOW)
        self._recent_channels: deque = deque(maxlen=10)

        # Intrinsic curiosity spark tracking (in-memory)
        self._boredom_onset_mono: float = 0.0
        self._last_curiosity_spark_mono: float = 0.0

        self._init_db()
        self._load_state()
        self._init_habituations()

        LOG.info(
            "Nucleus Accumbens initialized (%d channels, tonic=%.3f)",
            len(REWARD_CHANNELS), self._state.tonic_da,
        )

    # ───────────────────────────────────────────────────────────
    # DB Init
    # ───────────────────────────────────────────────────────────

    def _init_db(self):
        """Initialize SQLite DB with WAL mode."""
        try:
            from config.paths import get_db
            db_path = str(get_db("nucleus_accumbens"))
        except Exception:
            try:
                db_path = os.path.join(
                    os.path.expanduser("~"),
                    ".local", "share", "frank", "db", "nucleus_accumbens.db",
                )
                os.makedirs(os.path.dirname(db_path), exist_ok=True)
            except Exception:
                db_path = ":memory:"
                LOG.warning("NAc: using in-memory DB (path resolution failed)")

        try:
            self._db = sqlite3.connect(db_path, check_same_thread=False)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA busy_timeout=3000")
            self._db.executescript(_SCHEMA)
            self._db.commit()
        except Exception as e:
            LOG.error("NAc DB init failed: %s", e)
            try:
                self._db = sqlite3.connect(":memory:", check_same_thread=False)
                self._db.executescript(_SCHEMA)
                self._db.commit()
            except Exception:
                self._db = None

    def _load_state(self):
        """Load persistent state from DB."""
        if not self._db:
            return
        try:
            row = self._db.execute(
                "SELECT tonic_da, last_reward_ts, opponent_accumulator, "
                "boredom_active, anhedonia_below_since, anhedonia_last_fired_ts, "
                "boredom_last_epq_ts, total_events, channel_habituation, "
                "channel_predicted_reward, channel_last_ts "
                "FROM dopamine_state WHERE id = 1"
            ).fetchone()
            if row:
                self._state.tonic_da = float(row[0])
                self._state.last_reward_ts = float(row[1])
                self._state.opponent_accumulator = float(row[2])
                self._state.boredom_active = bool(row[3])
                self._state.anhedonia_below_since = float(row[4])
                self._state.anhedonia_last_fired_ts = float(row[5])
                self._state.boredom_last_epq_ts = float(row[6])
                self._state.total_events = int(row[7])
                self._state.channel_habituation = json.loads(row[8] or "{}")
                self._state.channel_predicted_reward = json.loads(row[9] or "{}")
                self._state.channel_last_ts = json.loads(row[10] or "{}")
                LOG.info("NAc: loaded state (tonic=%.3f, events=%d)",
                         self._state.tonic_da, self._state.total_events)
        except Exception as e:
            LOG.debug("NAc: no saved state, starting fresh: %s", e)

    def _save_state(self):
        """Persist state to DB."""
        if not self._db:
            return
        try:
            now = time.time()
            self._db.execute(
                "INSERT INTO dopamine_state "
                "(id, tonic_da, last_reward_ts, opponent_accumulator, "
                "boredom_active, anhedonia_below_since, anhedonia_last_fired_ts, "
                "boredom_last_epq_ts, total_events, channel_habituation, "
                "channel_predicted_reward, channel_last_ts, updated) "
                "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "tonic_da=excluded.tonic_da, "
                "last_reward_ts=excluded.last_reward_ts, "
                "opponent_accumulator=excluded.opponent_accumulator, "
                "boredom_active=excluded.boredom_active, "
                "anhedonia_below_since=excluded.anhedonia_below_since, "
                "anhedonia_last_fired_ts=excluded.anhedonia_last_fired_ts, "
                "boredom_last_epq_ts=excluded.boredom_last_epq_ts, "
                "total_events=excluded.total_events, "
                "channel_habituation=excluded.channel_habituation, "
                "channel_predicted_reward=excluded.channel_predicted_reward, "
                "channel_last_ts=excluded.channel_last_ts, "
                "updated=excluded.updated",
                (
                    self._state.tonic_da,
                    self._state.last_reward_ts,
                    self._state.opponent_accumulator,
                    int(self._state.boredom_active),
                    self._state.anhedonia_below_since,
                    self._state.anhedonia_last_fired_ts,
                    self._state.boredom_last_epq_ts,
                    self._state.total_events,
                    json.dumps(self._state.channel_habituation),
                    json.dumps(self._state.channel_predicted_reward),
                    json.dumps(self._state.channel_last_ts),
                    now,
                ),
            )
            self._db.commit()
        except Exception as e:
            LOG.warning("NAc: state save failed: %s", e)

    def _init_habituations(self):
        """Ensure all 9 channels have initial habituation values."""
        for ch in CHANNEL_NAMES:
            if ch not in self._state.channel_habituation:
                self._state.channel_habituation[ch] = 1.0
            if ch not in self._state.channel_predicted_reward:
                self._state.channel_predicted_reward[ch] = 0.0
            if ch not in self._state.channel_last_ts:
                self._state.channel_last_ts[ch] = 0.0

    # ───────────────────────────────────────────────────────────
    # Primary API: reward()
    # ───────────────────────────────────────────────────────────

    def reward(self, channel: str, source_data: Optional[dict] = None) -> RewardEvent:
        """
        Deliver a reward signal to the NAc. <0.1ms.

        5-stage pipeline:
          1. Hedonic Adaptation (habituation)
          2. RPE Computation (Schultz 1997)
          3. Tonic DA Update
          4. Opponent Process (Solomon & Corbit)
          5. E-PQ Event (if significant)

        Args:
            channel: One of CHANNEL_NAMES (e.g. "hypothesis_confirmed")
            source_data: Optional metadata dict

        Returns:
            RewardEvent with computed phasic_da, rpe, etc.
        """
        if channel not in REWARD_CHANNELS:
            LOG.warning("NAc: unknown channel '%s', ignoring", channel)
            return RewardEvent(channel=channel)

        with self._lock:
            now_mono = time.monotonic()
            now_wall = time.time()          # Wall-clock for persisted timestamps
            cfg = REWARD_CHANNELS[channel]
            raw_mag = cfg["base_magnitude"]

            # ── Stage 1: Hedonic Adaptation ──────────────────
            hab = self._state.channel_habituation.get(channel, 1.0)

            # Recovery: time since last event restores freshness
            last_ts = self._state.channel_last_ts.get(channel, 0.0)
            if last_ts > 0:
                elapsed = max(0.0, now_wall - last_ts)  # wall-clock, guard negative
                # ~50% recovery per hour of no stimulation
                recovery = min(1.0, elapsed / 3600.0) * 0.5
                hab = min(1.0, hab + recovery)

            adapted_mag = raw_mag * hab

            # Update habituation (decay for this event)
            hab_rate = cfg["habituation_rate"]
            hab_floor = cfg["habituation_floor"]
            new_hab = max(hab_floor, hab - hab_rate)
            self._state.channel_habituation[channel] = new_hab
            self._state.channel_last_ts[channel] = now_wall  # wall-clock (persisted)

            # ── Stage 2: RPE (Schultz 1997) ──────────────────
            predicted = self._state.channel_predicted_reward.get(channel, 0.0)
            rpe = adapted_mag - predicted

            if rpe > 0:
                phasic = rpe * RPE_SURPRISE_AMPLIFICATION
            else:
                phasic = rpe  # No amplification for expected/disappointing

            # Update prediction (EMA)
            self._state.channel_predicted_reward[channel] = (
                predicted * (1.0 - RPE_EMA_ALPHA)
                + adapted_mag * RPE_EMA_ALPHA
            )

            # ── Stage 3: Tonic DA Update ─────────────────────
            if rpe > 0:
                self._state.tonic_da += rpe * TONIC_BOOST_FROM_PHASIC
            elif rpe < 0:
                self._state.tonic_da += rpe * TONIC_DIP_FROM_NEGATIVE

            # ── Stage 4: Opponent Process ────────────────────
            self._state.opponent_accumulator += abs(phasic) * OPPONENT_GAIN

            # Clamp tonic
            self._state.tonic_da = max(0.0, min(1.0, self._state.tonic_da))

            # Update tracking
            self._state.last_reward_ts = now_wall   # wall-clock (persisted)
            self._state.total_events += 1
            self._rpe_history.append(abs(rpe))
            self._recent_channels.append(channel)

            # Build event
            evt = RewardEvent(
                channel=channel,
                timestamp=now_wall,  # wall-clock for logging/display
                raw_magnitude=raw_mag,
                habituation=hab,
                predicted_reward=predicted,
                rpe=rpe,
                phasic_da=phasic,
                tonic_da_after=self._state.tonic_da,
                source_data=source_data,
            )
            self._last_phasic = evt

            # ── Stage 5: E-PQ Event ──────────────────────────
            self._maybe_fire_epq_burst(evt)

            # DB logging (sampled)
            self._maybe_log_event(evt)

            # Periodic state save
            if now_mono - self._last_save_mono > STATE_SAVE_INTERVAL_S:
                self._save_state()
                self._last_save_mono = now_mono

            # Periodic cleanup
            if self._state.total_events % LOG_CLEANUP_INTERVAL == 0:
                self._cleanup_old_logs()

        return evt

    # ───────────────────────────────────────────────────────────
    # Periodic Tick (called every ~60s from workspace update)
    # ───────────────────────────────────────────────────────────

    def tick(self, dt: float = 60.0):
        """
        Periodic update: tonic decay, boredom detection, anhedonia check.

        Called from consciousness daemon's workspace update loop (~60s).
        """
        with self._lock:
            now_mono = time.monotonic()
            now_wall = time.time()          # Wall-clock for persisted timestamps

            # ── Tonic Decay toward baseline ──────────────────
            decay_rate = TONIC_DECAY_RATE

            # Boredom amplification (repetitive patterns)
            boredom = self._detect_boredom()
            self._state.boredom_active = boredom
            if boredom:
                decay_rate *= BOREDOM_DECAY_MULTIPLIER

            # Exponential decay toward baseline
            diff = self._state.tonic_da - TONIC_BASELINE
            self._state.tonic_da -= diff * decay_rate * dt

            # ── Opponent Process: B-process decay ────────────
            if self._state.opponent_accumulator > 0.001:
                self._state.opponent_accumulator *= math.exp(-dt / OPPONENT_TAU)
                # B-process pulls tonic TOWARD baseline (directional)
                opp_diff = self._state.tonic_da - TONIC_BASELINE
                if abs(opp_diff) > 0.001:
                    direction = -1.0 if opp_diff > 0 else 1.0
                    self._state.tonic_da += (
                        direction * self._state.opponent_accumulator * 0.001 * dt
                    )

            # Clamp
            self._state.tonic_da = max(0.0, min(1.0, self._state.tonic_da))

            # ── Boredom E-PQ ─────────────────────────────────
            self._check_boredom_epq(now_wall)

            # ── Anhedonia Detection ──────────────────────────
            self._check_anhedonia(now_wall)

            # ── Hedonic Adaptation Decay ───────────────────────
            # Without periodic recovery, habituation values get permanently
            # stuck near floor (0.05-0.35) after heavy use, causing complete
            # anhedonia: nothing feels rewarding anymore.
            # Recovery: ~10% per hour toward 1.0 (fresh sensitivity).
            _hab_recovery_per_sec = 0.10 / 3600.0
            for _ch in list(self._state.channel_habituation):
                _hab = self._state.channel_habituation[_ch]
                if _hab < 1.0:
                    _hab += (1.0 - _hab) * _hab_recovery_per_sec * dt
                    self._state.channel_habituation[_ch] = min(1.0, _hab)

            # ── Intrinsic Curiosity Spark (Pankseppian SEEKING) ──
            # When boredom persists, a tiny internal spark nudges tonic DA
            # upward — just enough to break the cycle. Habituates fast.
            self._maybe_curiosity_spark(now_mono)

            # Periodic save
            if now_mono - self._last_save_mono > STATE_SAVE_INTERVAL_S:
                self._save_state()
                self._last_save_mono = now_mono

            self._last_tick_mono = now_mono

    # ───────────────────────────────────────────────────────────
    # Boredom Detection — repetitiveness-based, NOT user absence
    # ───────────────────────────────────────────────────────────

    def _detect_boredom(self) -> bool:
        """
        Detect boredom from repetitive patterns.

        Two signals:
          1. Mean |RPE| of last 20 events < threshold → everything is predicted
          2. Fewer than N unique channels in last 10 events → monotonous

        Does NOT use time-since-last-reward. Frank can self-stimulate via
        lab experiments, hypotheses, novel thoughts. Boredom is about
        repetition, not absence.
        """
        # Need minimum events to assess
        if len(self._rpe_history) < BOREDOM_MIN_EVENTS:
            return False

        # Signal 1: Low novelty (everything predicted)
        mean_rpe = sum(self._rpe_history) / len(self._rpe_history)
        low_novelty = mean_rpe < BOREDOM_RPE_THRESHOLD

        # Signal 2: Low diversity (same channels over and over)
        if len(self._recent_channels) >= 5:
            unique_channels = len(set(self._recent_channels))
            low_diversity = unique_channels < BOREDOM_DIVERSITY_THRESHOLD
        else:
            low_diversity = False

        # Boredom requires low novelty OR (low diversity AND some events)
        return low_novelty or (low_diversity and len(self._rpe_history) >= 5)

    def _check_boredom_epq(self, now_wall: float):
        """Fire boredom E-PQ event if tonic drops during boredom."""
        if not self._state.boredom_active:
            return
        if self._state.tonic_da >= BOREDOM_EPQ_TONIC_THRESHOLD:
            return
        if now_wall - self._state.boredom_last_epq_ts < BOREDOM_EPQ_COOLDOWN_S:
            return

        self._fire_epq("dopamine_dip", {
            "tonic_da": round(self._state.tonic_da, 3),
            "source": "boredom_repetitive",
            "mean_rpe": round(
                sum(self._rpe_history) / max(len(self._rpe_history), 1), 4
            ),
            "intensity": min(1.0, max(0.1,
                1.0 - self._state.tonic_da / BOREDOM_EPQ_TONIC_THRESHOLD
            )),
        }, sentiment="negative")
        self._state.boredom_last_epq_ts = now_wall

    # ───────────────────────────────────────────────────────────
    # Anhedonia Protection
    # ───────────────────────────────────────────────────────────

    def _check_anhedonia(self, now_wall: float):
        """Detect sustained low tonic DA and trigger recovery."""
        if self._state.tonic_da < ANHEDONIA_THRESHOLD:
            if self._state.anhedonia_below_since == 0:
                self._state.anhedonia_below_since = now_wall
            elif (now_wall - self._state.anhedonia_below_since
                  > ANHEDONIA_DURATION_S):
                if (now_wall - self._state.anhedonia_last_fired_ts
                        > ANHEDONIA_COOLDOWN_S):
                    # Fire anhedonia event
                    self._fire_epq("anhedonia_onset", {
                        "tonic_da": round(self._state.tonic_da, 3),
                        "below_since_s": round(
                            now_wall - self._state.anhedonia_below_since, 0
                        ),
                        "intensity": min(1.0, max(0.3,
                            1.0 - self._state.tonic_da / ANHEDONIA_THRESHOLD
                        )),
                    }, sentiment="negative")
                    # Recovery: boost tonic DA
                    self._state.tonic_da = min(
                        1.0,
                        self._state.tonic_da + ANHEDONIA_RECOVERY_BOOST,
                    )
                    # Reset ALL habituations (fresh start)
                    for ch in CHANNEL_NAMES:
                        self._state.channel_habituation[ch] = 1.0
                    # Reset RPE history (clear boredom signal)
                    self._rpe_history.clear()
                    self._recent_channels.clear()
                    self._state.anhedonia_last_fired_ts = now_wall
                    LOG.info(
                        "NAc: anhedonia recovery triggered "
                        "(tonic=%.3f → %.3f, habituations reset)",
                        self._state.tonic_da - ANHEDONIA_RECOVERY_BOOST,
                        self._state.tonic_da,
                    )
        else:
            self._state.anhedonia_below_since = 0.0

    # ───────────────────────────────────────────────────────────
    # Intrinsic Curiosity Spark
    # ───────────────────────────────────────────────────────────

    def _maybe_curiosity_spark(self, now_mono: float):
        """
        Pankseppian SEEKING system: when boredom persists, generate a tiny
        intrinsic tonic DA boost. This is a gentle nudge toward exploration,
        NOT a forced behavior. Habituates fast so it's truly just a spark.

        Conditions:
          - Boredom active for 5+ minutes
          - Motivation is "flat" or "bored" (not anhedonic — has own recovery)
          - 10-minute cooldown between sparks
        """
        if not self._state.boredom_active:
            self._boredom_onset_mono = 0.0
            return

        # Track boredom onset
        if self._boredom_onset_mono == 0.0:
            self._boredom_onset_mono = now_mono
            return

        # Need 5 min of sustained boredom
        if (now_mono - self._boredom_onset_mono) < 300.0:
            return

        # Only for flat/bored — anhedonia has its own heavy recovery
        motivation = self.motivation_label()
        if motivation not in ("flat", "bored"):
            return

        # 10-minute cooldown
        if (now_mono - self._last_curiosity_spark_mono) < 600.0:
            return

        # Fire the spark: direct tonic micro-boost (not through reward()
        # to avoid contaminating boredom detection RPE signal)
        cfg = REWARD_CHANNELS["curiosity_spark"]
        hab = self._state.channel_habituation.get("curiosity_spark", 1.0)
        effective = cfg["base_magnitude"] * hab
        tonic_boost = effective * 0.1  # ~0.015 at full habituation

        self._state.tonic_da = min(1.0, self._state.tonic_da + tonic_boost)

        # Habituate the spark channel
        new_hab = max(cfg["habituation_floor"], hab - cfg["habituation_rate"])
        self._state.channel_habituation["curiosity_spark"] = new_hab

        self._last_curiosity_spark_mono = now_mono
        LOG.debug(
            "NAc: curiosity spark (effective=%.4f, boost=%.4f, "
            "tonic=%.3f, hab=%.2f→%.2f)",
            effective, tonic_boost, self._state.tonic_da, hab, new_hab,
        )

    # ───────────────────────────────────────────────────────────
    # E-PQ Integration
    # ───────────────────────────────────────────────────────────

    def _maybe_fire_epq_burst(self, evt: RewardEvent):
        """Fire dopamine_burst E-PQ event if phasic exceeds threshold."""
        cfg = REWARD_CHANNELS.get(evt.channel, {})
        epq_event = cfg.get("epq_event")
        if not epq_event:
            return
        if evt.phasic_da < EPQ_BURST_THRESHOLD:
            return
        now_mono = time.monotonic()
        if now_mono - self._last_epq_burst_ts < EPQ_BURST_COOLDOWN_S:
            return

        sentiment = cfg.get("epq_sentiment", "positive")
        self._fire_epq(epq_event, {
            "intensity": round(min(1.0, evt.phasic_da), 3),
            "channel": evt.channel,
            "rpe": round(evt.rpe, 4),
        }, sentiment=sentiment)
        self._last_epq_burst_ts = now_mono

    def _fire_epq(self, event_type: str, data: dict,
                  sentiment: str = "positive"):
        """Fire an E-PQ process_event. Best-effort, never raises."""
        try:
            from personality.e_pq import get_epq
            epq = get_epq()
            if epq:
                epq.process_event(event_type, sentiment=sentiment, data=data)
        except Exception as e:
            LOG.debug("NAc: E-PQ fire failed: %s", e)

    # ───────────────────────────────────────────────────────────
    # DB Logging
    # ───────────────────────────────────────────────────────────

    def _maybe_log_event(self, evt: RewardEvent):
        """Log reward event to DB (sampled or high-phasic)."""
        if not self._db:
            return
        should_log = (
            self._state.total_events % LOG_SAMPLE_INTERVAL == 0
            or abs(evt.phasic_da) > LOG_HIGH_PHASIC_THRESHOLD
        )
        if not should_log:
            return
        try:
            self._db.execute(
                "INSERT INTO reward_log "
                "(timestamp, channel, raw_magnitude, habituation, "
                "predicted_reward, rpe, phasic_da, tonic_da_after, source_data) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    time.time(),
                    evt.channel,
                    round(evt.raw_magnitude, 4),
                    round(evt.habituation, 4),
                    round(evt.predicted_reward, 4),
                    round(evt.rpe, 4),
                    round(evt.phasic_da, 4),
                    round(evt.tonic_da_after, 4),
                    json.dumps(evt.source_data or {}),
                ),
            )
            self._db.commit()
        except Exception as e:
            LOG.debug("NAc: log write failed: %s", e)

    def _cleanup_old_logs(self):
        """Remove reward_log entries older than retention period."""
        if not self._db:
            return
        try:
            cutoff = time.time() - LOG_RETENTION_DAYS * 86400
            self._db.execute(
                "DELETE FROM reward_log WHERE timestamp < ?",
                (cutoff,),
            )
            self._db.commit()
        except Exception as e:
            LOG.debug("NAc: log cleanup failed: %s", e)

    # ───────────────────────────────────────────────────────────
    # Query API
    # ───────────────────────────────────────────────────────────

    def get_tonic_dopamine(self) -> float:
        """Current tonic DA level (0.0-1.0). Thread-safe."""
        return self._state.tonic_da

    def get_report(self) -> NacReport:
        """Full diagnostic snapshot for introspection."""
        with self._lock:
            now_wall = time.time()
            since_reward = (
                max(0.0, now_wall - self._state.last_reward_ts)
                if self._state.last_reward_ts > 0 else 0.0
            )
            # Top habituated channels (lowest habituation values)
            sorted_habs = sorted(
                self._state.channel_habituation.items(),
                key=lambda x: x[1],
            )
            top_hab = [ch for ch, v in sorted_habs[:3] if v < 0.5]

            anhedonia_risk = (
                self._state.tonic_da < ANHEDONIA_THRESHOLD
                and self._state.anhedonia_below_since > 0
            )

            return NacReport(
                tonic_da=self._state.tonic_da,
                last_phasic=(
                    self._last_phasic.phasic_da if self._last_phasic else 0.0
                ),
                last_phasic_channel=(
                    self._last_phasic.channel if self._last_phasic else ""
                ),
                boredom_active=self._state.boredom_active,
                anhedonia_risk=anhedonia_risk,
                seconds_since_reward=since_reward,
                motivation_level=self.motivation_label(),
                top_habituated_channels=top_hab,
            )

    def motivation_label(self) -> str:
        """Terse motivation label based on tonic DA."""
        da = self._state.tonic_da
        if da > 0.7:
            return "energized"
        elif da > 0.45:
            return "engaged"
        elif da > 0.3:
            return "flat"
        elif da > ANHEDONIA_THRESHOLD:
            return "bored"
        else:
            return "anhedonic"

    def get_proprio_line(self) -> str:
        """Terse proprioception line for [PROPRIO] block."""
        with self._lock:
            da = self._state.tonic_da
            label = self.motivation_label()
        return f"Drive: {label} ({da:.2f})"

    def get_summary(self) -> dict:
        """Diagnostic summary for chaining."""
        with self._lock:
            return {
                "tonic_da": round(self._state.tonic_da, 4),
                "total_events": self._state.total_events,
                "boredom_active": self._state.boredom_active,
                "motivation": self.motivation_label(),
                "last_phasic": (
                    round(self._last_phasic.phasic_da, 4)
                    if self._last_phasic else 0.0
                ),
                "last_channel": (
                    self._last_phasic.channel if self._last_phasic else ""
                ),
                "channel_habituation": {
                    ch: round(v, 3)
                    for ch, v in self._state.channel_habituation.items()
                },
                "channel_predicted_reward": {
                    ch: round(v, 4)
                    for ch, v in self._state.channel_predicted_reward.items()
                },
            }

    def get_channel_report(self) -> List[dict]:
        """Per-channel diagnostic info."""
        with self._lock:
            result = []
            for ch in CHANNEL_NAMES:
                cfg = REWARD_CHANNELS[ch]
                hab = self._state.channel_habituation.get(ch, 1.0)
                pred = self._state.channel_predicted_reward.get(ch, 0.0)
                result.append({
                    "channel": ch,
                    "base_magnitude": cfg["base_magnitude"],
                    "habituation": round(hab, 3),
                    "predicted_reward": round(pred, 4),
                    "effective_magnitude": round(
                        cfg["base_magnitude"] * hab, 4
                    ),
                    "habituation_floor": cfg["habituation_floor"],
                })
            return result

    # ───────────────────────────────────────────────────────────
    # Lifecycle
    # ───────────────────────────────────────────────────────────

    def close(self):
        """Persist state and close DB."""
        with self._lock:
            self._save_state()
            if self._db:
                try:
                    self._db.close()
                except Exception:
                    pass
                self._db = None
        LOG.info("Nucleus Accumbens closed")


# ═══════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════

_instance: Optional[NucleusAccumbens] = None
_instance_lock = threading.Lock()


def get_nac() -> NucleusAccumbens:
    """Get or create the singleton NucleusAccumbens instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = NucleusAccumbens()
                atexit.register(_instance.close)
    return _instance


def _reset_singleton():
    """Reset singleton for testing. NOT for production use."""
    global _instance
    with _instance_lock:
        if _instance is not None:
            _instance.close()
            _instance = None
