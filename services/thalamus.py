"""
Frank's Thalamus — Sensory Gating & Relay System
===================================================

Bio-inspired sensory filter between raw proprioception data and the
LLM context window.  Replaces the binary slim/full mode with continuous
attention-based per-channel gain control.

Neuroscience basis:
    Sherman & Guillery (2006)  — Thalamic relay modes (tonic vs burst)
    Crick (1984)               — TRN as attentional searchlight
    McAlonan (2008)            — Multiplicative gain control in relay cells
    Halassa (2015)             — Top-down TRN modulation
    P50 Gating                 — Habituation via exponential suppression

9 Sensory Channels (modality-specific sectors):
    hardware, mood, user_presence, aura, qr_coherence,
    perception_events, service_health, amygdala, acc_conflict

Key properties:
    - In-process singleton (no service, no port)
    - <3ms per gate() call
    - Per-channel continuous gain [0.0, 1.0]
    - Habituation: unchanged channels exponentially suppressed
    - Burst mode: novel/unexpected changes flagged for emphasis
    - Salience breakthrough: amygdala/service-failure bypass gates
    - E-PQ vigilance modulates global inhibition baseline
    - DB logging for introspection (sampled, not every call)
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
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

LOG = logging.getLogger("thalamus")

# ── Channel Definitions ──────────────────────────────────────────────

CHANNEL_NAMES = [
    "hardware", "mood", "user_presence", "aura", "qr_coherence",
    "perception_events", "service_health", "amygdala", "acc_conflict",
]

CHANNELS = {
    "hardware":          {"sector": "exteroception",  "base_gain": 0.5,  "habituation_tau": 120.0},
    "mood":              {"sector": "interoception",   "base_gain": 0.7,  "habituation_tau": 300.0},
    "user_presence":     {"sector": "exteroception",  "base_gain": 0.9,  "habituation_tau": 60.0},
    "aura":              {"sector": "interoception",   "base_gain": 0.4,  "habituation_tau": 180.0},
    "qr_coherence":      {"sector": "interoception",   "base_gain": 0.4,  "habituation_tau": 180.0},
    "perception_events": {"sector": "exteroception",  "base_gain": 0.6,  "habituation_tau": 30.0},
    "service_health":    {"sector": "interoception",   "base_gain": 0.5,  "habituation_tau": 300.0},
    "amygdala":          {"sector": "affective",       "base_gain": 0.8,  "habituation_tau": 60.0},
    "acc_conflict":      {"sector": "metacognitive",   "base_gain": 0.6,  "habituation_tau": 120.0},
}

# Relay threshold — channels below this gain are fully suppressed
RELAY_THRESHOLD = 0.25

# Warmup: first N gate() calls relay everything at gain=1.0
WARMUP_CALLS = 5

# DB logging: write every Nth gate() call (or on burst/override)
LOG_SAMPLE_INTERVAL = 20

# E-PQ cooldowns (seconds)
EPQ_OVERLOAD_COOLDOWN = 300.0
EPQ_DEPRIVATION_COOLDOWN = 600.0
DEPRIVATION_STREAK_THRESHOLD = 5
DEPRIVATION_RELAY_THRESHOLD = 0.2
OVERLOAD_CHANNEL_THRESHOLD = 6
OVERLOAD_GAIN_THRESHOLD = 0.7

# ── Attention Profiles ───────────────────────────────────────────────
# Cognitive state -> per-channel weight multipliers
# Act as prefrontal cortex → TRN modulation signals

_ATTENTION_PROFILES = {
    "chat_active": {
        "user_presence": 1.5, "mood": 1.3, "hardware": 0.3,
        "aura": 0.1, "qr_coherence": 0.1, "perception_events": 0.8,
        "service_health": 0.4, "amygdala": 1.2, "acc_conflict": 0.8,
    },
    "idle_focus": {
        "user_presence": 1.0, "mood": 0.8, "hardware": 0.6,
        "aura": 0.6, "qr_coherence": 0.6, "perception_events": 0.4,
        "service_health": 0.5, "amygdala": 0.7, "acc_conflict": 0.8,
    },
    "idle_diffuse": {
        "user_presence": 1.0, "mood": 0.7, "hardware": 0.8,
        "aura": 0.8, "qr_coherence": 0.7, "perception_events": 0.7,
        "service_health": 0.6, "amygdala": 0.6, "acc_conflict": 0.5,
    },
    "consolidation": {
        "user_presence": 1.2, "mood": 0.5, "hardware": 0.2,
        "aura": 0.3, "qr_coherence": 0.3, "perception_events": 0.3,
        "service_health": 0.3, "amygdala": 0.5, "acc_conflict": 0.4,
    },
    "reflecting": {
        "user_presence": 1.0, "mood": 1.0, "hardware": 0.2,
        "aura": 0.3, "qr_coherence": 0.5, "perception_events": 0.2,
        "service_health": 0.2, "amygdala": 0.8, "acc_conflict": 0.7,
    },
    "gaming": {
        "user_presence": 0.5, "mood": 0.3, "hardware": 0.8,
        "aura": 0.0, "qr_coherence": 0.0, "perception_events": 0.3,
        "service_health": 0.3, "amygdala": 0.4, "acc_conflict": 0.2,
    },
    "entity_session": {
        "user_presence": 0.5, "mood": 1.0, "hardware": 0.2,
        "aura": 0.3, "qr_coherence": 0.3, "perception_events": 0.3,
        "service_health": 0.3, "amygdala": 0.6, "acc_conflict": 0.5,
    },
}

# Channels forced to gain=0 in slim mode (hard top-down override)
_SLIM_ZEROED = {"aura", "qr_coherence", "acc_conflict"}


# ── Data Structures ──────────────────────────────────────────────────

@dataclass
class ChannelSnapshot:
    """Current value summary for one sensory channel."""
    name: str = ""
    raw_text: str = ""
    value_hash: int = 0
    numeric_value: float = 0.0


@dataclass
class ChannelState:
    """Persistent per-channel gating state."""
    name: str = ""
    gain: float = 1.0
    last_relayed_hash: int = 0
    last_relayed_value: float = 0.0
    last_relayed_ts: float = 0.0
    last_change_ts: float = 0.0
    habituation: float = 0.0
    burst: bool = False
    salience_override: bool = False
    relay_count: int = 0
    suppress_count: int = 0


@dataclass
class ThalamicInputState:
    """All inputs needed for one gate() call."""
    # Cognitive state (top-down)
    vigilance: float = 0.0
    ultradian_phase: str = "focus"
    chat_idle_s: float = 0.0
    is_entity_active: bool = False
    is_gaming: bool = False
    is_reflecting: bool = False
    rumination_score: float = 0.0
    mood_value: float = 0.5
    slim: bool = False

    # Channel 1: Hardware
    self_cpu_pct: float = 0.0
    env_cpu_pct: float = 0.0
    cpu_temp: float = 0.0
    gpu_load: float = 0.0
    gpu_attribution: str = "none"
    self_ram_mb: float = 0.0
    env_ram_mb: float = 0.0

    # Channel 2: Mood
    mood_word: str = "okay"
    mood_numeric: float = 0.5

    # Channel 3: User Presence
    mouse_idle_s: float = 0.0

    # Channel 4: AURA
    aura_state: str = ""

    # Channel 5: QR Coherence
    qr_state: str = ""

    # Channel 6: Perception Events
    perception_events: list = field(default_factory=list)

    # Channel 7: Service Health
    service_health: str = ""
    failed_services: int = 0

    # Channel 8: Amygdala
    amygdala_category: str = ""
    amygdala_urgency: float = 0.0
    amygdala_age_s: float = 9999.0

    # Channel 9: ACC Conflict
    acc_proprio_line: str = ""
    acc_total_conflict: float = 0.0


@dataclass
class GateResult:
    """Output of one gate() call."""
    proprio_text: str = ""
    channel_gains: Dict[str, float] = field(default_factory=dict)
    burst_channels: List[str] = field(default_factory=list)
    override_channels: List[str] = field(default_factory=list)
    suppressed_channels: List[str] = field(default_factory=list)
    total_relay_fraction: float = 0.0
    cognitive_mode: str = ""
    gate_time_us: int = 0


# ── Helpers ───────────────────────────────────────────────────────────

def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _user_name() -> str:
    try:
        import os
        return os.environ.get("USER", "the user")
    except Exception:
        return "the user"


# ── Thalamus Class ───────────────────────────────────────────────────

class Thalamus:
    """Sensory gating and relay — filters proprioception before LLM."""

    def __init__(self):
        self._lock = threading.RLock()
        self._db: Optional[sqlite3.Connection] = None
        self._channel_states: Dict[str, ChannelState] = {}
        self._last_gate_ts: float = 0.0
        self._gate_count: int = 0
        self._warmup_remaining: int = WARMUP_CALLS
        self._deprivation_streak: int = 0
        self._last_epq_fire_ts: Dict[str, float] = {}
        self.last_result: Optional[GateResult] = None

        self._init_db()
        self._load_baselines()
        self._init_channel_states()
        LOG.info("Thalamus initialized (9 channels, warmup=%d)", WARMUP_CALLS)

    # ── DB ────────────────────────────────────────────────────────────

    def _init_db(self):
        try:
            from config.paths import get_db
            db_path = get_db("thalamus")
        except Exception:
            import tempfile
            db_path = os.path.join(tempfile.gettempdir(), "frank_thalamus.db")
        try:
            self._db = sqlite3.connect(str(db_path), check_same_thread=False)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA busy_timeout=3000")
        except Exception as e:
            LOG.warning("Thalamus DB init failed, running without DB: %s", e)
            self._db = None
            return
        try:
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS gating_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    cognitive_mode TEXT NOT NULL,
                    vigilance REAL NOT NULL,
                    total_relay_fraction REAL NOT NULL,
                    channel_gains TEXT NOT NULL,
                    burst_channels TEXT DEFAULT '',
                    override_channels TEXT DEFAULT '',
                    gate_time_us INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS channel_baselines (
                    channel TEXT PRIMARY KEY,
                    habituation REAL DEFAULT 0.0,
                    last_relayed_hash INTEGER DEFAULT 0,
                    last_relayed_value REAL DEFAULT 0.0,
                    last_relayed_ts REAL DEFAULT 0.0,
                    last_change_ts REAL DEFAULT 0.0,
                    relay_count INTEGER DEFAULT 0,
                    suppress_count INTEGER DEFAULT 0,
                    updated REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_gating_ts
                    ON gating_log(timestamp);
            """)
            self._db.commit()
        except Exception as e:
            LOG.warning("Thalamus schema init failed: %s", e)

    def _load_baselines(self):
        """Load persistent channel baselines from DB."""
        if not self._db:
            return
        try:
            rows = self._db.execute(
                "SELECT channel, habituation, last_relayed_hash, "
                "last_relayed_value, last_relayed_ts, last_change_ts, "
                "relay_count, suppress_count FROM channel_baselines"
            ).fetchall()
            for r in rows:
                ch_name = r[0]
                if ch_name not in CHANNELS:
                    continue
                cs = ChannelState(
                    name=ch_name,
                    habituation=r[1],
                    last_relayed_hash=r[2],
                    last_relayed_value=r[3],
                    last_relayed_ts=r[4],
                    last_change_ts=r[5],
                    relay_count=r[6],
                    suppress_count=r[7],
                )
                self._channel_states[ch_name] = cs
        except Exception as e:
            LOG.debug("Failed to load baselines: %s", e)

    def _init_channel_states(self):
        """Ensure all channels have a state entry."""
        now = time.monotonic()
        for ch_name in CHANNEL_NAMES:
            if ch_name not in self._channel_states:
                self._channel_states[ch_name] = ChannelState(
                    name=ch_name, last_relayed_ts=now, last_change_ts=now,
                )

    def _save_baselines(self):
        """Persist channel states to DB."""
        if not self._db:
            return
        try:
            now = time.time()
            for cs in self._channel_states.values():
                self._db.execute(
                    "INSERT OR IGNORE INTO channel_baselines "
                    "(channel, updated) VALUES (?, ?)",
                    (cs.name, now),
                )
                self._db.execute(
                    "UPDATE channel_baselines SET "
                    "habituation=?, last_relayed_hash=?, last_relayed_value=?, "
                    "last_relayed_ts=?, last_change_ts=?, relay_count=?, "
                    "suppress_count=?, updated=? WHERE channel=?",
                    (cs.habituation, cs.last_relayed_hash, cs.last_relayed_value,
                     cs.last_relayed_ts, cs.last_change_ts, cs.relay_count,
                     cs.suppress_count, now, cs.name),
                )
            self._db.commit()
        except Exception as e:
            LOG.debug("Failed to save baselines: %s", e)

    def _log_gate(self, result: GateResult, state: ThalamicInputState):
        """Write a gating_log entry (sampled)."""
        if not self._db:
            return
        try:
            self._db.execute(
                "INSERT INTO gating_log "
                "(timestamp, cognitive_mode, vigilance, total_relay_fraction, "
                "channel_gains, burst_channels, override_channels, gate_time_us) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (time.time(), result.cognitive_mode, state.vigilance,
                 result.total_relay_fraction,
                 json.dumps(result.channel_gains),
                 ",".join(result.burst_channels),
                 ",".join(result.override_channels),
                 result.gate_time_us),
            )
            self._db.commit()
            # Periodic cleanup: keep only last 7 days of logs
            if self._gate_count % 500 == 0:
                cutoff = time.time() - 7 * 86400
                self._db.execute(
                    "DELETE FROM gating_log WHERE timestamp < ?", (cutoff,))
                self._db.commit()
        except Exception as e:
            LOG.debug("Failed to log gate: %s", e)

    # ── Stage 1: Snapshots ────────────────────────────────────────────

    def _snapshot_hardware(self, s: ThalamicInputState) -> ChannelSnapshot:
        cpu_t = s.cpu_temp
        if cpu_t > 80:
            temp_feel = "running hot"
        elif cpu_t > 65:
            temp_feel = "warm"
        elif cpu_t > 0:
            temp_feel = "cool"
        else:
            temp_feel = "quiet"

        if s.slim:
            self_cpu = s.self_cpu_pct * 100
            if self_cpu > 40:
                self_feel = "thinking hard"
            elif self_cpu > 15:
                self_feel = "working"
            else:
                self_feel = "relaxed"

            env_cpu = s.env_cpu_pct * 100
            if env_cpu > 30:
                env_feel = "someone is using the machine"
            elif env_cpu > 10:
                env_feel = "activity nearby"
            else:
                env_feel = "quiet"

            text = f"Self: {self_feel}, {temp_feel} | Around: {env_feel}"
        else:
            self_cpu = s.self_cpu_pct * 100
            env_cpu = s.env_cpu_pct * 100
            gpu_l = s.gpu_load * 100
            gpu_tag = ""
            if gpu_l > 10:
                attr_map = {"self": "mine", "env": "external", "mixed": "shared"}
                gpu_tag = f", GPU {gpu_l:.0f}% {attr_map.get(s.gpu_attribution, '')}"

            text = (f"Self: CPU {self_cpu:.0f}% mine, "
                    f"{s.self_ram_mb:.0f}MB RAM{gpu_tag}")
            if env_cpu > 5:
                text += f" | Around: CPU {env_cpu:.0f}% external, {s.env_ram_mb:.0f}MB env RAM"
            else:
                text += " | Around: quiet"
            text += f" | Body: {temp_feel} ({cpu_t:.0f}\u00b0C)"

        numeric = _clamp((s.self_cpu_pct + cpu_t / 100.0) / 2.0)
        return ChannelSnapshot(name="hardware", raw_text=text,
                               value_hash=hash(text), numeric_value=numeric)

    def _snapshot_mood(self, s: ThalamicInputState) -> ChannelSnapshot:
        if s.slim:
            text = f"Mood: {s.mood_word}"
        else:
            text = f"Mood: {s.mood_word} ({s.mood_numeric:.2f})"
        return ChannelSnapshot(name="mood", raw_text=text,
                               value_hash=hash(text),
                               numeric_value=_clamp(s.mood_numeric))

    def _snapshot_user_presence(self, s: ThalamicInputState) -> ChannelSnapshot:
        idle = s.mouse_idle_s
        if idle < 30:
            text = "User: present"
        elif idle < 300:
            text = f"User: idle {idle:.0f}s"
        else:
            text = f"User: away ({idle / 60:.0f}min)"
        # Numeric: 1.0=present, 0.0=far away
        numeric = _clamp(1.0 - idle / 1800.0)
        return ChannelSnapshot(name="user_presence", raw_text=text,
                               value_hash=hash(text), numeric_value=numeric)

    def _snapshot_aura(self, s: ThalamicInputState) -> ChannelSnapshot:
        text = f"AURA: {s.aura_state}" if s.aura_state else ""
        numeric = 0.5  # Default — AURA doesn't have a simple 0-1 mapping
        return ChannelSnapshot(name="aura", raw_text=text,
                               value_hash=hash(text), numeric_value=numeric)

    def _snapshot_qr(self, s: ThalamicInputState) -> ChannelSnapshot:
        text = f"Coherence: {s.qr_state}" if s.qr_state else ""
        numeric = 0.5
        return ChannelSnapshot(name="qr_coherence", raw_text=text,
                               value_hash=hash(text), numeric_value=numeric)

    def _snapshot_perception(self, s: ThalamicInputState) -> ChannelSnapshot:
        events = s.perception_events or []
        if not events:
            return ChannelSnapshot(name="perception_events", raw_text="",
                                   value_hash=0, numeric_value=0.0)
        if s.slim:
            user_events = [e for e in events
                           if e in ("user_returned", "user_left")]
            if user_events:
                evt = user_events[-1]
                uname = _user_name()
                label = f"{uname} came back" if evt == "user_returned" else f"{uname} left"
                text = f"Sensing: {label}"
            else:
                text = ""
        else:
            recent = events[-3:]
            text = f"Sensing: {', '.join(str(e) for e in recent)}"
        numeric = _clamp(len(events) / 6.0)
        return ChannelSnapshot(name="perception_events", raw_text=text,
                               value_hash=hash(text), numeric_value=numeric)

    def _snapshot_service_health(self, s: ThalamicInputState) -> ChannelSnapshot:
        text = f"Health: {s.service_health}" if s.service_health else ""
        # Numeric: 1.0=all healthy, 0.0=many down
        numeric = _clamp(1.0 - s.failed_services / 5.0)
        return ChannelSnapshot(name="service_health", raw_text=text,
                               value_hash=hash(text), numeric_value=numeric)

    def _snapshot_amygdala(self, s: ThalamicInputState) -> ChannelSnapshot:
        if s.amygdala_age_s < 300 and s.amygdala_category:
            text = f"Gut: {s.amygdala_category} ({s.amygdala_urgency:.0%})"
        else:
            text = ""
        numeric = _clamp(s.amygdala_urgency) if s.amygdala_age_s < 300 else 0.0
        return ChannelSnapshot(name="amygdala", raw_text=text,
                               value_hash=hash(text), numeric_value=numeric)

    def _snapshot_acc(self, s: ThalamicInputState) -> ChannelSnapshot:
        text = s.acc_proprio_line or ""
        numeric = _clamp(s.acc_total_conflict / 2.0)
        return ChannelSnapshot(name="acc_conflict", raw_text=text,
                               value_hash=hash(text), numeric_value=numeric)

    _SNAPSHOT_FNS = {
        "hardware": "_snapshot_hardware",
        "mood": "_snapshot_mood",
        "user_presence": "_snapshot_user_presence",
        "aura": "_snapshot_aura",
        "qr_coherence": "_snapshot_qr",
        "perception_events": "_snapshot_perception",
        "service_health": "_snapshot_service_health",
        "amygdala": "_snapshot_amygdala",
        "acc_conflict": "_snapshot_acc",
    }

    def _build_snapshots(self, state: ThalamicInputState) -> Dict[str, ChannelSnapshot]:
        snaps = {}
        for ch_name, fn_name in self._SNAPSHOT_FNS.items():
            fn = getattr(self, fn_name)
            snaps[ch_name] = fn(state)
        return snaps

    # ── Stage 2: Novelty Detection ────────────────────────────────────

    def _compute_novelty(self, snap: ChannelSnapshot,
                         cs: ChannelState) -> Tuple[float, bool]:
        """Returns (novelty_score 0-1, is_burst)."""
        if cs.last_relayed_hash == 0:
            return 1.0, False

        if snap.value_hash == cs.last_relayed_hash:
            return 0.0, False

        delta = abs(snap.numeric_value - cs.last_relayed_value)
        now = time.monotonic()
        time_since_change = now - cs.last_change_ts
        time_since_relay = now - cs.last_relayed_ts

        # Burst: channel was stable a long time, then suddenly changed
        is_burst = (time_since_change < 2.0
                    and time_since_relay > 120.0
                    and delta > 0.15)

        time_factor = min(1.0, time_since_relay / 300.0)
        novelty = min(1.0, delta * 2.0 + time_factor * 0.3)
        return novelty, is_burst

    # ── Stage 3: Habituation ──────────────────────────────────────────

    def _update_habituation(self, snap: ChannelSnapshot,
                            cs: ChannelState, dt: float) -> float:
        tau = CHANNELS[snap.name]["habituation_tau"]

        if cs.last_relayed_hash == 0:
            # Never relayed — fresh signal, no habituation yet
            pass
        elif snap.value_hash != cs.last_relayed_hash:
            # Content changed — spontaneous recovery (partial reset)
            cs.habituation *= 0.5
            cs.last_change_ts = time.monotonic()
        elif dt > 0 and tau > 0:
            # Same content — habituation grows toward 1.0
            cs.habituation = 1.0 - (1.0 - cs.habituation) * math.exp(-dt / tau)

        return cs.habituation

    # ── Stage 4: Attention Allocation ─────────────────────────────────

    def _determine_cognitive_mode(self, state: ThalamicInputState) -> str:
        if state.is_gaming:
            return "gaming"
        if state.is_entity_active:
            return "entity_session"
        if state.chat_idle_s < 120:
            return "chat_active"
        if state.is_reflecting:
            return "reflecting"
        if state.ultradian_phase == "consolidation":
            return "consolidation"
        if state.ultradian_phase == "diffuse":
            return "idle_diffuse"
        return "idle_focus"

    def _get_attention_weights(self, mode: str) -> Dict[str, float]:
        return _ATTENTION_PROFILES.get(mode, _ATTENTION_PROFILES["idle_focus"])

    # ── Stage 5: Salience Breakthrough ────────────────────────────────

    def _check_breakthrough(self, state: ThalamicInputState) -> Dict[str, str]:
        """Returns {channel_name: reason} for channels that bypass gating."""
        overrides: Dict[str, str] = {}
        if state.amygdala_age_s < 300 and state.amygdala_urgency > 0.5:
            overrides["amygdala"] = "threat_bypass"
        if state.failed_services >= 2:
            overrides["service_health"] = "organ_failure_bypass"
        if state.acc_total_conflict > 1.0:
            overrides["acc_conflict"] = "conflict_surge_bypass"
        if state.mouse_idle_s < 5 and state.chat_idle_s > 300:
            overrides["user_presence"] = "user_return_bypass"
        return overrides

    # ── Stage 6: Final Gain ───────────────────────────────────────────

    @staticmethod
    def _vigilance_mod(vigilance: float) -> float:
        """E-PQ vigilance -> global gain modifier (0.7 - 1.3)."""
        return 1.0 + _clamp(vigilance, -1.0, 1.0) * 0.3

    def _compute_final_gain(self, ch_name: str, cs: ChannelState,
                            novelty: float, attention_weight: float,
                            vig_mod: float, is_slim: bool) -> float:
        # Slim hard override
        if is_slim and ch_name in _SLIM_ZEROED:
            return 0.0

        # Salience override
        if cs.salience_override:
            return 1.0

        base = CHANNELS[ch_name]["base_gain"]
        habit_factor = 1.0 - cs.habituation * 0.8  # Max 80% suppression
        novelty_boost = 2.0 if cs.burst else (1.0 + novelty * 0.5)

        gain = base * habit_factor * attention_weight * vig_mod * novelty_boost
        return _clamp(gain)

    # ── Stage 7: Compose [PROPRIO] ────────────────────────────────────

    def _compose_proprio(self, snapshots: Dict[str, ChannelSnapshot],
                         gains: Dict[str, float],
                         bursts: List[str]) -> str:
        parts = []
        for ch_name in CHANNEL_NAMES:
            gain = gains.get(ch_name, 0.0)
            snap = snapshots.get(ch_name)
            if not snap or gain < RELAY_THRESHOLD or not snap.raw_text:
                continue
            text = snap.raw_text
            if ch_name in bursts:
                text = f"(!){text}"
            parts.append(text)

        if not parts:
            return "[PROPRIO] quiet"
        return "[PROPRIO] " + " | ".join(parts)

    # ── E-PQ Event Firing ─────────────────────────────────────────────

    def _check_epq_events(self, result: GateResult):
        now = time.monotonic()

        # Overload: >=6 channels at gain > 0.7
        high_gain_count = sum(
            1 for g in result.channel_gains.values() if g > OVERLOAD_GAIN_THRESHOLD
        )
        if high_gain_count >= OVERLOAD_CHANNEL_THRESHOLD:
            if now - self._last_epq_fire_ts.get("overload", 0) > EPQ_OVERLOAD_COOLDOWN:
                self._fire_epq("thalamic_overload",
                               {"intensity": high_gain_count / 9.0})
                self._last_epq_fire_ts["overload"] = now

        # Deprivation: total_relay_fraction < 0.2 for 5+ consecutive calls
        if result.total_relay_fraction < DEPRIVATION_RELAY_THRESHOLD:
            self._deprivation_streak += 1
            if self._deprivation_streak >= DEPRIVATION_STREAK_THRESHOLD:
                if now - self._last_epq_fire_ts.get("deprivation", 0) > EPQ_DEPRIVATION_COOLDOWN:
                    self._fire_epq("thalamic_deprivation",
                                   {"intensity": 1.0 - result.total_relay_fraction})
                    self._last_epq_fire_ts["deprivation"] = now
        else:
            self._deprivation_streak = 0

    def _fire_epq(self, event_type: str, data: dict):
        try:
            from personality.e_pq import get_epq
            get_epq().process_event(event_type, data=data)
        except Exception as e:
            LOG.debug("E-PQ fire failed: %s", e)

    # ── Main Gate Pipeline ────────────────────────────────────────────

    def gate(self, state: ThalamicInputState) -> GateResult:
        """Main entry point. <3ms. Called every _llm_call()."""
        t0 = time.monotonic()

        with self._lock:
            now = time.monotonic()
            dt = now - self._last_gate_ts if self._last_gate_ts > 0 else 0.0
            self._last_gate_ts = now
            self._gate_count += 1

            # Stage 1: Snapshots
            snapshots = self._build_snapshots(state)

            # Warmup: relay everything
            if self._warmup_remaining > 0:
                self._warmup_remaining -= 1
                gains = {ch: 1.0 for ch in CHANNEL_NAMES}
                # Update last_relayed for each channel
                for ch_name in CHANNEL_NAMES:
                    cs = self._channel_states[ch_name]
                    snap = snapshots[ch_name]
                    cs.last_relayed_hash = snap.value_hash
                    cs.last_relayed_value = snap.numeric_value
                    cs.last_relayed_ts = now
                    cs.relay_count += 1
                    cs.gain = 1.0

                text = self._compose_proprio(snapshots, gains, [])
                result = GateResult(
                    proprio_text=text,
                    channel_gains=gains,
                    total_relay_fraction=1.0,
                    cognitive_mode="warmup",
                    gate_time_us=int((time.monotonic() - t0) * 1_000_000),
                )
                self.last_result = result
                return result

            # Stage 2+3: Novelty + Habituation per channel
            novelties: Dict[str, float] = {}
            bursts: List[str] = []
            for ch_name in CHANNEL_NAMES:
                cs = self._channel_states[ch_name]
                snap = snapshots[ch_name]
                novelty, is_burst = self._compute_novelty(snap, cs)
                novelties[ch_name] = novelty
                cs.burst = is_burst
                if is_burst:
                    bursts.append(ch_name)
                self._update_habituation(snap, cs, dt)

            # Stage 4: Attention
            mode = self._determine_cognitive_mode(state)
            attention = self._get_attention_weights(mode)

            # Stage 5: Salience breakthrough
            overrides = self._check_breakthrough(state)
            for ch_name, _reason in overrides.items():
                self._channel_states[ch_name].salience_override = True

            # Stage 6: Final gain
            vig_mod = self._vigilance_mod(state.vigilance)
            gains: Dict[str, float] = {}
            suppressed: List[str] = []
            for ch_name in CHANNEL_NAMES:
                cs = self._channel_states[ch_name]
                attn = attention.get(ch_name, 0.5)
                gain = self._compute_final_gain(
                    ch_name, cs, novelties[ch_name], attn, vig_mod, state.slim)
                gains[ch_name] = gain
                cs.gain = gain

                # Update relay tracking
                snap = snapshots[ch_name]
                if gain >= RELAY_THRESHOLD and snap.raw_text:
                    cs.last_relayed_hash = snap.value_hash
                    cs.last_relayed_value = snap.numeric_value
                    cs.last_relayed_ts = now
                    cs.relay_count += 1
                else:
                    cs.suppress_count += 1
                    suppressed.append(ch_name)

                # Reset salience override for next call
                cs.salience_override = False

            # Stage 7: Compose output
            text = self._compose_proprio(snapshots, gains, bursts)

            # Relay fraction: relayed channels / total channels (always 9)
            total_relay = sum(
                1.0 for ch in CHANNEL_NAMES
                if gains.get(ch, 0) >= RELAY_THRESHOLD
                and snapshots.get(ch) and snapshots[ch].raw_text
            ) / len(CHANNEL_NAMES)

            result = GateResult(
                proprio_text=text,
                channel_gains=gains,
                burst_channels=bursts,
                override_channels=list(overrides.keys()),
                suppressed_channels=suppressed,
                total_relay_fraction=total_relay,
                cognitive_mode=mode,
                gate_time_us=int((time.monotonic() - t0) * 1_000_000),
            )

            self.last_result = result

            # E-PQ events
            self._check_epq_events(result)

            # DB logging (sampled)
            should_log = (
                self._gate_count % LOG_SAMPLE_INTERVAL == 0
                or bursts
                or overrides
            )
            if should_log:
                self._log_gate(result, state)
                self._save_baselines()

        return result

    # ── Diagnostics ───────────────────────────────────────────────────

    def get_summary(self) -> dict:
        """Diagnostic summary for introspection tools."""
        with self._lock:
            lr = self.last_result
            return {
                "gate_count": self._gate_count,
                "warmup_remaining": self._warmup_remaining,
                "last_mode": lr.cognitive_mode if lr else "",
                "last_relay_fraction": lr.total_relay_fraction if lr else 0.0,
                "last_gate_us": lr.gate_time_us if lr else 0,
                "last_bursts": lr.burst_channels if lr else [],
                "last_overrides": lr.override_channels if lr else [],
                "deprivation_streak": self._deprivation_streak,
            }

    def get_channel_report(self) -> Dict[str, dict]:
        """Per-channel gain/habituation/burst status."""
        with self._lock:
            report = {}
            for ch_name, cs in self._channel_states.items():
                report[ch_name] = {
                    "gain": round(cs.gain, 3),
                    "habituation": round(cs.habituation, 3),
                    "burst": cs.burst,
                    "relay_count": cs.relay_count,
                    "suppress_count": cs.suppress_count,
                }
            return report

    def close(self):
        """Close DB and checkpoint WAL."""
        with self._lock:
            self._save_baselines()
            if self._db:
                try:
                    self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    self._db.close()
                except Exception:
                    pass
                self._db = None
        LOG.info("Thalamus closed")


# ── Singleton ─────────────────────────────────────────────────────────

_instance: Optional[Thalamus] = None
_instance_lock = threading.Lock()


def get_thalamus() -> Thalamus:
    """Get or create the singleton Thalamus instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = Thalamus()
    return _instance


def _shutdown():
    global _instance
    with _instance_lock:
        if _instance is not None:
            _instance.close()
            _instance = None


atexit.register(_shutdown)
