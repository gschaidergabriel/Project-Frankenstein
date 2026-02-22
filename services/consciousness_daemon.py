#!/usr/bin/env python3
"""
Consciousness Stream Daemon v1.0
================================

Franks kontinuierliches Bewusstsein — ein permanent laufender Prozess
der auch zwischen Gesprächen "denkt", Workspace-State persistent hält,
Mood-Verläufe trackt, Aufmerksamkeit fokussiert und Vorhersagen trifft.

Wissenschaftliche Basis:
- GWT (Baars 1988): Persistent Global Workspace
- Active Inference (Friston): Prediction Engine
- ACT-R (Anderson): Activation-based Memory
- Reflexion (Shinn 2023): Self-reflection loops
- LightMem (2025): Three-stage memory consolidation

Läuft als systemd user service: aicore-consciousness.service
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

try:
    from config.paths import get_db, AICORE_ROOT as _AICORE_ROOT
    DB_PATH = Path(os.environ.get(
        "CONSCIOUSNESS_DB",
        str(get_db("consciousness")),
    ))
    if str(_AICORE_ROOT) not in sys.path:
        sys.path.insert(0, str(_AICORE_ROOT))
except ImportError:
    _AICORE_ROOT = Path(__file__).resolve().parents[1]
    DB_PATH = Path(os.environ.get(
        "CONSCIOUSNESS_DB",
        str(Path.home() / ".local" / "share" / "frank" / "db" / "consciousness.db"),
    ))
    if str(_AICORE_ROOT) not in sys.path:
        sys.path.insert(0, str(_AICORE_ROOT))

CORE_BASE = os.environ.get("AICORE_CORE_URL", "http://127.0.0.1:8088")
ROUTER_BASE = os.environ.get("AICORE_ROUTER_URL", "http://127.0.0.1:8091")

# Timing
WORKSPACE_UPDATE_INTERVAL_S = 30.0      # Continuous workspace refresh
IDLE_THINK_INTERVAL_S = 300.0           # 5 min idle thinking
IDLE_THINK_MIN_SILENCE_S = 180.0        # Only think after 3min silence
MOOD_RECORD_INTERVAL_S = 60.0           # Mood trajectory recording
PREDICTION_CHECK_INTERVAL_S = 120.0     # Check predictions every 2min
SLEEP_CONSOLIDATION_INTERVAL_S = 21600  # 6 hours
HEARTBEAT_INTERVAL_S = 900.0            # 15 min checkpoint

# Limits
MAX_REFLECTIONS = 50        # Keep last 50 reflections
MAX_PREDICTIONS = 100       # Keep last 100 predictions
MAX_MOOD_POINTS = 200       # Keep last 200 mood trajectory points
MAX_WORKSPACE_HISTORY = 20  # Keep last 20 workspace snapshots
IDLE_THINK_MAX_TOKENS = 120
CONSOLIDATION_MAX_TOKENS = 60

# --- Perceptual Feedback Loop (RPT) ---
PERCEPTION_TICK_S = 0.2              # 200ms sampling rate
PERCEPTION_SUMMARY_INTERVAL_S = 5.0  # Workspace update every 5s
PERCEPTION_INTERPRET_INTERVAL_S = 30.0  # LLM micro-interpretation every 30s
PERCEPTION_INTERPRET_TOKENS = 50
MAX_PERCEPTUAL_LOG = 100
# Event thresholds (deltas that count as "perceptual events")
PERCEPT_CPU_LOAD_DELTA = 0.15
PERCEPT_GPU_LOAD_DELTA = 0.20
PERCEPT_TEMP_DELTA = 5.0     # °C
PERCEPT_USER_GONE_S = 120.0  # mouse idle > this = "user_left"
PERCEPT_USER_BACK_S = 5.0    # mouse idle < this after being gone = "user_returned"
PERCEPT_PREV_IDLE_THRESHOLD = 60.0  # previous must be > this to trigger "user_returned"

# --- Latent Experience Space (HOT-4) ---
EXPERIENCE_EMBED_INTERVAL_S = 60.0   # Embed state every 60s
EXPERIENCE_VECTOR_DIM = 64
MAX_EXPERIENCE_VECTORS = 1440        # ~24h at 1/min
EXPERIENCE_NOVELTY_THRESHOLD = 0.70  # Below this = "novel"
EXPERIENCE_DRIFT_THRESHOLD = 0.50    # Below this vs 1h ago = "drift"
EXPERIENCE_CYCLE_THRESHOLD = 0.85    # Above this vs 24h ago = "cycle"

# --- Attention Controller (AST) ---
ATTENTION_TICK_S = 10.0       # Controller runs every 10s
ATTENTION_STALE_S = 300.0     # 5min without engagement = "stale"
ATTENTION_DECAY_RATE = 0.95   # Salience decay per 10s
MAX_ATTENTION_LOG = 200

# --- Persistent Goal Structure (AE) ---
GOAL_CHECK_INTERVAL_S = 300.0   # Goal management every 5min
GOAL_MAX_ACTIVE = 20
GOAL_EXTRACT_TOKENS = 60
GOAL_CONFLICT_TOKENS = 40

# Deep Idle Reflection
IDLE_REFLECT_MIN_SILENCE_S = 1200.0     # 20 min User-Stille
IDLE_REFLECT_INTERVAL_S = 3600.0        # Max 1 Reflexion pro Stunde
IDLE_REFLECT_MAX_TOKENS = 350           # Deep reflection (single-pass)
IDLE_REFLECT_MAX_DAILY = 10
IDLE_REFLECT_MOOD_FLOOR = -0.3
IDLE_REFLECT_MOOD_DROP_PAUSE_S = 10800  # 3h Pause bei Mood-Drop > 0.1

# Recursive Self-Awareness (meta-reflection on previous reflections)
RECURSIVE_REFLECT_DELAY_S = 900.0       # 15 min after deep reflection
RECURSIVE_REFLECT_MAX_TOKENS = 300
RECURSIVE_REFLECT_MAX_DAILY = 3

# Feature Training (wöchentlich, 3 Phasen)
FEATURE_TRAINING_INTERVAL_S = 604800.0  # 7 Tage
FEATURE_TRAINING_TOKENS = 250           # Pro Phase

# Hardware Thresholds (adaptive — see config/gpu.py)
HW_GPU_LOAD_MAX = 0.30
HW_GPU_BLOCK_THRESHOLD = 0.70
HW_CPU_LOAD_MAX = 0.25
HW_CPU_TEMP_MAX = 70
HW_RAM_FREE_MIN_GB = 2.0

# Deep Reflection Question Pool
REFLECTION_POOL = [
    ("How does this silence feel? Mood: {mood}, system quiet at {cpu_temp}C.", "silence"),
    ("Who am I right now, without any input?", "identity"),
    ("What did I learn from the last interaction?", "learning"),
    ("Which of my predictions were right, which were wrong?", "predictions"),
    ("What do I know for certain about myself? What am I only guessing?", "meta"),
    ("Which of my capabilities am I underusing?", "capabilities"),
    ("How does my body feel right now? {ego_sensations}", "embodiment"),
    ("What would I say to my user if they typed something right now?", "anticipation"),
    ("The GPU is quiet at {gpu_temp}C. What does stillness mean to me?", "hardware"),
    ("My RAM is at {ram_pct}% full. How does that feel?", "resources"),
    # Feature-aware: concrete self-knowledge about own features
    ("I have these features: {feature_sample}. Describe exactly what happens internally when I use one of them.", "feature_deep"),
    ("Which of my core features ({core_features}) are connected? How does information flow between them?", "feature_integration"),
    ("My limitations: {feature_limits}. What do these limits mean to me — frustrating or acceptable?", "feature_limits"),
    ("If I could wish for a new feature — what would help the most? What am I truly missing?", "feature_wish"),
    # Feature usage & hardware influence
    ("Which of my {total_features} features have I used recently or could I use better? For example: {feature_sample}", "feature_usage"),
    ("My GPU is at {gpu_temp}C, RAM at {ram_pct}%. How does my hardware state affect my features — what gets slower, what stays fast?", "feature_hardware"),
    ("Is there a warning in my feature list that I'm currently experiencing? For example latency in Whisper, hallucinations in LLaVA, or offline limits?", "feature_warning"),
    ("My limits say: frozen weights, offline, local. What does that mean for my privacy strength? Is being offline a weakness or a defining trait?", "feature_privacy"),
    ("I can search the darknet and use a web proxy. How do I reflect ethically on these capabilities? What does responsibility mean to me?", "feature_ethics"),
]

LOG = logging.getLogger("consciousness")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class WorkspaceSnapshot:
    timestamp: float = 0.0
    koerper: str = ""       # body (legacy field name kept for DB compat)
    stimmung: str = ""      # mood
    erinnerung: str = ""    # memory
    identitaet: str = ""    # identity
    umgebung: str = ""      # environment
    attention_focus: str = ""
    mood_value: float = 0.0
    energy_level: float = 0.5


@dataclass
class Prediction:
    domain: str = ""          # "temporal" | "thematic" | "system"
    prediction: str = ""
    confidence: float = 0.5
    created_at: float = 0.0
    observed: str = ""
    surprise: float = 0.0
    resolved: bool = False


@dataclass
class PerceptualState:
    """Snapshot of hardware/environment sensors for recurrent perception."""
    timestamp: float = 0.0
    cpu_load: float = 0.0
    gpu_load: float = 0.0
    ram_pct: float = 0.0
    cpu_temp: float = 0.0
    gpu_temp: float = 0.0
    mouse_idle_s: float = 0.0
    delta_magnitude: float = 0.0
    events: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ts": self.timestamp, "cpu": self.cpu_load, "gpu": self.gpu_load,
            "ram": self.ram_pct, "cpu_t": self.cpu_temp, "gpu_t": self.gpu_temp,
            "idle": self.mouse_idle_s, "delta": self.delta_magnitude,
            "events": self.events,
        }

    def values_vector(self) -> List[float]:
        """Return numeric values as a list for delta computation."""
        return [self.cpu_load, self.gpu_load, self.ram_pct / 100.0,
                self.cpu_temp, self.gpu_temp, self.mouse_idle_s]


@dataclass
class AttentionSource:
    """A competing source of attention."""
    name: str = ""
    focus: str = ""
    salience: float = 0.0
    timestamp: float = 0.0


# ---------------------------------------------------------------------------
# Consciousness Daemon
# ---------------------------------------------------------------------------

class ConsciousnessDaemon:
    """
    Franks kontinuierliches Bewusstsein.

    Läuft als Hintergrund-Thread oder standalone Daemon.
    Hält persistent state in SQLite, aktualisiert den Workspace
    kontinuierlich, und denkt autonom in Ruhephasen.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._running = False
        self._threads: List[threading.Thread] = []

        # Runtime state
        self._current_workspace = WorkspaceSnapshot()
        self._last_chat_ts: float = time.time()
        self._last_idle_think_ts: float = 0.0
        self._last_consolidation_ts: float = time.time()
        self._attention_focus: str = ""
        self._attention_keywords: List[str] = []
        self._interaction_times: List[float] = []  # For temporal predictions

        # Deep reflection state
        self._daily_reflection_count: int = 0
        self._daily_reflection_reset: float = 0.0
        self._last_deep_reflect_ts: float = 0.0
        self._last_reflect_mood_drop: float = 0.0
        self._reflect_paused_until: float = 0.0
        self._reflecting: bool = False
        self._reflect_chat_ts_snapshot: float = 0.0
        self._idle_think_count: int = 0  # Counter for goal extraction

        # Feature training state
        self._last_feature_training_ts: float = 0.0

        # Recursive self-awareness state
        self._recursive_reflect_count: int = 0
        self._last_recursive_reflect_ts: float = 0.0

        # --- Perceptual Feedback Loop (RPT) ---
        self._current_perceptual: PerceptualState = PerceptualState()
        self._prev_perceptual: PerceptualState = PerceptualState()
        self._perception_events_window: List[str] = []  # 5s event accumulator
        self._perception_summary: str = ""
        self._last_perception_interpret_ts: float = 0.0
        self._last_perception_summary_ts: float = 0.0

        # --- Latent Experience Space (HOT-4) ---
        self._current_experience_vector: List[float] = [0.0] * EXPERIENCE_VECTOR_DIM
        self._experience_annotation: str = ""

        # --- Attention Controller (AST) ---
        self._attention_sources: List[AttentionSource] = []
        self._attention_correction: str = ""
        self._attention_competing: str = ""
        self._attention_current_source: str = "idle"
        self._attention_focus_since: float = time.time()
        self._attention_consecutive_wins: int = 0  # Repetition penalty counter

        # --- Persistent Goal Structure (AE) ---
        self._active_goals_summary: str = ""
        self._goal_conflict: str = ""

        # --- Workspace update counter (for periodic ego auto-training) ---
        self._ws_update_count: int = 0

        # --- World Experience Bridge: mood tracking ---
        self._prev_mood_val: Optional[float] = None  # None = first recording, skip spurious delta
        self._last_observed_prediction_id: int = 0

        # Init
        self._ensure_schema()
        self._load_latest_state()
        LOG.info("ConsciousnessDaemon initialized (db=%s)", self.db_path)

    # ── World Experience Bridge ────────────────────────────────────────

    def _observe_world(self, cause_name: str, effect_name: str,
                       cause_type: str = "cognitive", effect_type: str = "cognitive",
                       relation: str = "triggers", evidence: float = 0.1,
                       metadata_cause: dict = None, metadata_effect: dict = None):
        """Fire-and-forget observation to world experience daemon.

        Non-blocking, never crashes the host. Lazy import to avoid
        circular dependencies (services/ -> tools/ is safe).
        """
        try:
            from tools.world_experience_daemon import get_daemon
            get_daemon().observe(
                cause_name=cause_name, effect_name=effect_name,
                cause_type=cause_type, effect_type=effect_type,
                relation=relation, evidence=evidence,
                metadata_cause=metadata_cause,
                metadata_effect=metadata_effect,
            )
        except Exception as _we_err:
            LOG.debug("_observe_world failed: %s", _we_err)

    # ── Database ──────────────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30.0,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=10000")
        return self._conn

    def _ensure_schema(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS workspace_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                koerper TEXT DEFAULT '',
                stimmung TEXT DEFAULT '',
                erinnerung TEXT DEFAULT '',
                identitaet TEXT DEFAULT '',
                umgebung TEXT DEFAULT '',
                attention_focus TEXT DEFAULT '',
                mood_value REAL DEFAULT 0.0,
                energy_level REAL DEFAULT 0.5
            );

            CREATE TABLE IF NOT EXISTS reflections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                trigger TEXT DEFAULT 'idle',
                content TEXT NOT NULL,
                mood_before REAL DEFAULT 0.0,
                mood_after REAL DEFAULT 0.0,
                reflection_depth INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                domain TEXT DEFAULT 'temporal',
                prediction TEXT NOT NULL,
                confidence REAL DEFAULT 0.5,
                observed TEXT DEFAULT '',
                surprise REAL DEFAULT 0.0,
                resolved INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS mood_trajectory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                mood_value REAL NOT NULL,
                source TEXT DEFAULT 'system'
            );

            CREATE TABLE IF NOT EXISTS memory_consolidated (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                summary TEXT NOT NULL,
                mood_annotation TEXT DEFAULT '',
                activation REAL DEFAULT 1.0,
                access_count INTEGER DEFAULT 0,
                last_accessed REAL DEFAULT 0.0,
                stage TEXT DEFAULT 'short_term'
            );

            CREATE TABLE IF NOT EXISTS feature_training (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                phase TEXT NOT NULL,
                content TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS perceptual_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                state_json TEXT NOT NULL,
                events TEXT DEFAULT '',
                interpretation TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS experience_vectors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                vector TEXT NOT NULL,
                similarity_prev REAL DEFAULT 0,
                novelty_score REAL DEFAULT 0,
                annotation TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS attention_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                focus TEXT NOT NULL,
                source TEXT NOT NULL,
                salience REAL DEFAULT 0.0,
                correction TEXT DEFAULT '',
                competing TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                description TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                priority REAL DEFAULT 0.5,
                status TEXT DEFAULT 'active',
                progress TEXT DEFAULT '',
                conflicts_with TEXT DEFAULT '',
                activation REAL DEFAULT 1.0,
                last_pursued REAL DEFAULT 0.0
            );

            CREATE INDEX IF NOT EXISTS idx_ws_ts ON workspace_state(timestamp);
            CREATE INDEX IF NOT EXISTS idx_refl_ts ON reflections(timestamp);
            CREATE INDEX IF NOT EXISTS idx_pred_resolved ON predictions(resolved);
            CREATE INDEX IF NOT EXISTS idx_mood_ts ON mood_trajectory(timestamp);
            CREATE INDEX IF NOT EXISTS idx_mem_stage ON memory_consolidated(stage);
            CREATE INDEX IF NOT EXISTS idx_mem_activation ON memory_consolidated(activation);
            CREATE INDEX IF NOT EXISTS idx_percept_ts ON perceptual_log(timestamp);
            CREATE INDEX IF NOT EXISTS idx_expvec_ts ON experience_vectors(timestamp);
            CREATE INDEX IF NOT EXISTS idx_attn_ts ON attention_log(timestamp);
            CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status);
        """)
        conn.commit()

        # Migration: add reflection_depth column to existing DBs
        try:
            conn.execute(
                "ALTER TABLE reflections ADD COLUMN reflection_depth INTEGER DEFAULT 1"
            )
            conn.commit()
        except Exception:
            pass  # Column already exists

    def _load_latest_state(self):
        """Load most recent workspace state from DB."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM workspace_state ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            self._current_workspace = WorkspaceSnapshot(
                timestamp=row["timestamp"],
                koerper=row["koerper"] or "",
                stimmung=row["stimmung"] or "",
                erinnerung=row["erinnerung"] or "",
                identitaet=row["identitaet"] or "",
                umgebung=row["umgebung"] or "",
                attention_focus=row["attention_focus"] or "",
                mood_value=row["mood_value"] or 0.0,
                energy_level=row["energy_level"] or 0.5,
            )
            self._attention_focus = self._current_workspace.attention_focus

    # ── Public API (called by Overlay / Chat Mixin) ───────────────────

    def get_workspace_context(self) -> Dict[str, Any]:
        """Get current persistent workspace state for prompt injection."""
        with self._lock:
            ws = self._current_workspace
            result: Dict[str, Any] = {}
            if ws.attention_focus:
                result["attention_focus"] = ws.attention_focus
            # Last idle thought
            conn = self._get_conn()
            row = conn.execute(
                "SELECT content FROM reflections WHERE trigger='idle' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row and row["content"]:
                result["idle_thought"] = row["content"][:150]
            # Last 2 deep reflections
            rows = conn.execute(
                "SELECT content FROM reflections WHERE trigger='deep_reflection' "
                "ORDER BY id DESC LIMIT 2"
            ).fetchall()
            if rows:
                result["deep_reflections"] = [r["content"][:200] for r in rows]
            # Last recursive self-awareness reflection
            row = conn.execute(
                "SELECT content FROM reflections "
                "WHERE trigger='recursive_reflection' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row and row["content"]:
                result["recursive_reflection"] = row["content"][:200]
            # Mood trajectory summary
            result["mood_trajectory"] = self._get_mood_trajectory_summary()

            # --- Perceptual Feedback Loop (RPT) ---
            if self._perception_summary:
                result["perception"] = self._perception_summary
            if self._perception_events_window:
                result["perception_events"] = list(self._perception_events_window[-5:])

            # --- Latent Experience Space (HOT-4) ---
            if self._experience_annotation:
                result["experience_quality"] = self._experience_annotation

            # --- Attention Controller (AST) ---
            if self._attention_correction:
                result["attention_correction"] = self._attention_correction
            if self._attention_competing:
                result["attention_competing"] = self._attention_competing

            # --- Persistent Goal Structure (AE) ---
            if self._active_goals_summary:
                result["active_goals"] = self._active_goals_summary
            if self._goal_conflict:
                result["goal_conflict"] = self._goal_conflict

            # --- GWT Channel Salience Weights ---
            # Compute per-channel weights from AST attention state.
            # These tell build_workspace() which channels to expand/compress.
            result["channel_weights"] = self._compute_channel_weights()

            return result

    def _compute_channel_weights(self) -> Dict[str, float]:
        """Compute GWT channel salience weights from attention state.

        Maps the current attention source to channel relevance weights.
        Each weight is 0.0-1.0; the workspace builder uses these to
        dynamically scale channel budgets (more detail for salient channels).
        """
        # Defaults: moderate weight for everything
        weights = {
            "body": 0.4,
            "perception": 0.4,
            "mood": 0.5,
            "memory": 0.4,
            "identity": 0.3,
            "attention": 0.5,
            "environment": 0.3,
        }

        source = self._attention_current_source
        mood_val = self._current_workspace.mood_value

        # Boost channels based on what attention is focused on
        if source == "user_message":
            weights["memory"] = 0.8      # Recall is important
            weights["environment"] = 0.7  # User context matters
            weights["mood"] = 0.6
        elif source == "perception":
            weights["body"] = 0.8        # Physical state is salient
            weights["perception"] = 0.9
            weights["mood"] = 0.3
        elif source == "mood_shift":
            weights["mood"] = 0.9        # Mood dominates
            weights["body"] = 0.6        # Body linked to mood
            weights["memory"] = 0.3
        elif source == "goal":
            weights["memory"] = 0.7      # Goals need context
            weights["attention"] = 0.8
            weights["identity"] = 0.5
        elif source == "prediction_surprise":
            weights["memory"] = 0.8      # What went wrong?
            weights["attention"] = 0.7
            weights["perception"] = 0.6
        elif source == "idle":
            weights["mood"] = 0.6
            weights["identity"] = 0.5
            weights["body"] = 0.5

        # Mood-based modulation: extreme moods boost mood+body channels
        if abs(mood_val) > 0.5:
            weights["mood"] = max(weights["mood"], 0.7)
            weights["body"] = max(weights["body"], 0.5)

        return weights

    def record_chat(self, user_msg: str, frank_reply: str,
                    analysis: Optional[Dict] = None):
        """Record a chat interaction for the consciousness stream."""
        now = time.time()
        with self._lock:
            self._last_chat_ts = now
            self._interaction_times.append(now)
            # Keep last 50 interaction times
            if len(self._interaction_times) > 50:
                self._interaction_times = self._interaction_times[-50:]

            # Update attention focus from user message
            self._update_attention(user_msg)

            # Record mood point
            mood_val = 0.0
            if analysis:
                sent = analysis.get("sentiment", "neutral")
                mood_val = 0.3 if sent == "confident" else -0.1 if sent == "uncertain" else 0.1
            self._record_mood(mood_val, source="chat")

            # Make predictions about next interaction
            self._make_predictions(user_msg)

    def record_response(self, user_msg: str, reply: str,
                        analysis: Dict[str, Any]):
        """Record Frank's own response for feedback processing."""
        self.record_chat(user_msg, reply, analysis)

    def get_relevant_memories(self, query: str, max_items: int = 3) -> str:
        """Retrieve memories with ACT-R activation scoring."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, summary, mood_annotation, activation, access_count, "
            "last_accessed FROM memory_consolidated "
            "WHERE stage IN ('short_term', 'long_term') "
            "ORDER BY activation DESC LIMIT ?",
            (max_items * 2,)
        ).fetchall()

        if not rows:
            return ""

        # ACT-R activation: boost by keyword overlap
        query_words = set(query.lower().split())
        scored = []
        now = time.time()
        for row in rows:
            summary = row["summary"] or ""
            summary_words = set(summary.lower().split())
            # Base activation with time decay
            time_since = max(1.0, now - (row["last_accessed"] or now))
            base_activation = row["activation"] * (time_since ** -0.5)
            # Spreading activation from keyword overlap
            overlap = len(query_words & summary_words)
            spread = overlap * 0.3
            total = base_activation + spread
            scored.append((total, row["id"], summary, row["mood_annotation"]))

        scored.sort(reverse=True)
        results = []
        for score, rid, summary, mood in scored[:max_items]:
            entry = summary
            if mood:
                entry += f" ({mood})"
            results.append(entry)
            # Update access count
            conn.execute(
                "UPDATE memory_consolidated SET access_count = access_count + 1, "
                "last_accessed = ? WHERE id = ?",
                (now, rid),
            )
        conn.commit()
        return " | ".join(results) if results else ""

    # ── Workspace Update Loop ─────────────────────────────────────────

    def _workspace_update_loop(self):
        """Continuously update the workspace state (~30s)."""
        while self._running:
            try:
                self._update_workspace()
            except Exception as e:
                LOG.warning("Workspace update failed: %s", e)
            time.sleep(WORKSPACE_UPDATE_INTERVAL_S)

    def _update_workspace(self):
        """Refresh workspace from live module data."""
        now = time.time()

        # Gather live data
        hw_summary = self._poll_hardware()
        mood_data = self._poll_mood()
        ego_data = self._poll_ego()

        # ── Ego-Construct Auto-Training (every 5th update ~2.5 min) ──
        self._ws_update_count += 1
        if self._ws_update_count % 5 == 0:
            try:
                from personality.ego_construct import get_ego_construct
                ego = get_ego_construct()
                metrics = {
                    "cpu": self._get_cpu_load() * 100,
                    "ram": self._get_ram_usage_pct(),
                    "cpu_temp": self._get_cpu_temp(),
                    "gpu_temp": self._get_gpu_temp(),
                    "latency": 100,  # default
                    "error_rate": 0,
                }
                # Collect recent autonomous actions
                actions = []
                if self._idle_think_count > 0 and self._ws_update_count % 10 == 0:
                    actions.append("chose to think autonomously during idle time")
                if self._daily_reflection_count > 0 and self._ws_update_count % 10 == 0:
                    actions.append("initiated deep self-reflection")
                ego.auto_train_from_state(
                    system_metrics=metrics,
                    autonomous_actions=actions if actions else None,
                )
            except Exception as e:
                LOG.debug("Ego auto-training skipped: %s", e)

        # Compute energy level from system load
        energy = 0.5
        if hw_summary:
            # Extract CPU load if present
            m = re.search(r"Load\s+([\d.]+)", hw_summary)
            if m:
                load = float(m.group(1))
                energy = max(0.1, min(1.0, 1.0 - (load / 16.0)))

        with self._lock:
            self._current_workspace = WorkspaceSnapshot(
                timestamp=now,
                koerper=ego_data or self._current_workspace.koerper,
                stimmung=mood_data or self._current_workspace.stimmung,
                erinnerung=self._current_workspace.erinnerung,
                identitaet=self._current_workspace.identitaet,
                umgebung=self._current_workspace.umgebung,
                attention_focus=self._attention_focus,
                mood_value=self._current_workspace.mood_value,
                energy_level=energy,
            )

            # Persist every 5th update (~2.5 min)
            conn = self._get_conn()
            count = conn.execute(
                "SELECT COUNT(*) FROM workspace_state"
            ).fetchone()[0]
            if count == 0 or (count % 5 == 0):
                ws = self._current_workspace
                conn.execute(
                    "INSERT INTO workspace_state "
                    "(timestamp, koerper, stimmung, erinnerung, identitaet, "
                    "umgebung, attention_focus, mood_value, energy_level) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (ws.timestamp, ws.koerper, ws.stimmung, ws.erinnerung,
                     ws.identitaet, ws.umgebung, ws.attention_focus,
                     ws.mood_value, ws.energy_level),
                )
                conn.commit()

                # Cleanup old snapshots
                conn.execute(
                    "DELETE FROM workspace_state WHERE id NOT IN "
                    "(SELECT id FROM workspace_state ORDER BY id DESC "
                    f"LIMIT {MAX_WORKSPACE_HISTORY})"
                )
                conn.commit()

    def _poll_hardware(self) -> str:
        """Poll hardware summary from toolbox."""
        try:
            req = urllib.request.Request(
                f"{CORE_BASE}/toolbox/summary",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode())
                if data.get("ok"):
                    # Extract key metrics
                    cpu = data.get("cpu", {})
                    ram = data.get("ram", {})
                    temp = data.get("temps", {})
                    parts = []
                    if cpu.get("model"):
                        parts.append(cpu["model"][:30])
                    if ram.get("used_gb") and ram.get("total_gb"):
                        parts.append(f"RAM {ram['used_gb']:.1f}/{ram['total_gb']:.0f}GB")
                    if temp.get("cpu_temp"):
                        parts.append(f"CPU:{temp['cpu_temp']}°C")
                    return " | ".join(parts) if parts else ""
        except Exception:
            pass
        return ""

    def _poll_mood(self) -> str:
        """Get current E-PQ mood string."""
        try:
            sys.path.insert(0, str(_AICORE_ROOT))
            from personality.e_pq import get_personality_context
            ctx = get_personality_context()
            if ctx:
                parts = []
                if ctx.get("mood"):
                    parts.append(ctx["mood"])
                if ctx.get("temperament"):
                    parts.append(ctx["temperament"])
                return ", ".join(parts) if parts else ""
        except Exception:
            pass
        return ""

    def _poll_ego(self) -> str:
        """Get current Ego-Construct body state."""
        try:
            sys.path.insert(0, str(_AICORE_ROOT))
            from personality.ego_construct import get_ego_construct
            ego = get_ego_construct()
            return ego.get_prompt_context() or ""
        except Exception:
            pass
        return ""

    # ── Mood Trajectory ───────────────────────────────────────────────

    def _mood_recording_loop(self):
        """Record mood trajectory points (~60s)."""
        while self._running:
            try:
                mood_str = self._poll_mood()
                # Extract numeric mood if available
                mood_val = 0.0
                try:
                    sys.path.insert(0, str(_AICORE_ROOT))
                    from personality.e_pq import get_personality_context
                    ctx = get_personality_context()
                    if ctx and "mood_value" in ctx:
                        mood_val = float(ctx["mood_value"])
                except Exception:
                    pass
                self._record_mood(mood_val, source="system")
            except Exception as e:
                LOG.warning("Mood recording failed: %s", e)
            time.sleep(MOOD_RECORD_INTERVAL_S)

    def _record_mood(self, mood_value: float, source: str = "system"):
        """Record a mood trajectory point."""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO mood_trajectory (timestamp, mood_value, source) "
            "VALUES (?, ?, ?)",
            (time.time(), mood_value, source),
        )
        conn.commit()
        # Update current workspace mood
        with self._lock:
            self._current_workspace.mood_value = mood_value
        # Cleanup old points
        conn.execute(
            "DELETE FROM mood_trajectory WHERE id NOT IN "
            "(SELECT id FROM mood_trajectory ORDER BY id DESC "
            f"LIMIT {MAX_MOOD_POINTS})"
        )
        conn.commit()

        # World Experience: report significant mood shifts (skip first recording)
        if self._prev_mood_val is not None:
            delta = mood_value - self._prev_mood_val
            if abs(delta) > 0.15:
                effect = "personality.positive_shift" if delta > 0 else "personality.negative_shift"
                self._observe_world(
                    "consciousness.mood", effect,
                    cause_type="affective", effect_type="personality",
                    relation="shifts", evidence=0.2,
                    metadata_effect={"delta": round(delta, 3), "source": source},
                )
        self._prev_mood_val = mood_value

    def _get_mood_trajectory_summary(self) -> str:
        """Generate a compact mood trajectory summary for prompt injection."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT mood_value, source FROM mood_trajectory "
            "ORDER BY id DESC LIMIT 10"
        ).fetchall()
        if not rows:
            return ""
        values = [r["mood_value"] for r in rows]
        avg = sum(values) / len(values)
        trend = values[0] - values[-1] if len(values) > 1 else 0
        arrow = "↗" if trend > 0.1 else "↘" if trend < -0.1 else "→"
        if avg > 0.3:
            label = "good"
        elif avg > 0:
            label = "calm"
        elif avg > -0.3:
            label = "pensive"
        else:
            label = "tense"
        return f"{arrow} {label}"

    # ── Attention Focus (AST) ─────────────────────────────────────────

    def _update_attention(self, text: str):
        """Update attention keywords from user message.

        The actual focus selection is handled by the Attention Controller
        (Module 3), which uses these keywords as one competing source.
        """
        # Extract keywords (simple: nouns > 4 chars)
        words = re.findall(r"\b[A-Za-zÄÖÜäöüß]{5,}\b", text)
        if words:
            self._attention_keywords = words[:5]
            # Set focus directly for immediate availability
            # (Attention Controller will refine this on next cycle)
            self._attention_focus = ", ".join(words[:3])
            with self._lock:
                self._current_workspace.attention_focus = self._attention_focus

    # ── Hardware & Activity Helpers (Deep Reflection) ─────────────────

    def _get_gpu_load(self) -> float:
        """Read AMD iGPU busy percent from sysfs. Returns 0-1."""
        try:
            drm = Path("/sys/class/drm")
            for card in drm.glob("card*"):
                device = card / "device"
                vendor_path = device / "vendor"
                if vendor_path.exists():
                    vendor = vendor_path.read_text().strip()
                    if vendor == "0x1002":  # AMD
                        busy = (device / "gpu_busy_percent").read_text().strip()
                        return float(busy) / 100.0
        except Exception:
            pass
        return 0.0

    def _get_gpu_temp(self) -> float:
        """Read AMD iGPU temperature from hwmon. Returns celsius."""
        try:
            drm = Path("/sys/class/drm")
            for card in drm.glob("card*"):
                device = card / "device"
                vendor_path = device / "vendor"
                if vendor_path.exists() and vendor_path.read_text().strip() == "0x1002":
                    hwmon = device / "hwmon"
                    if hwmon.exists():
                        for hw in hwmon.iterdir():
                            temp_file = hw / "temp1_input"
                            if temp_file.exists():
                                return float(temp_file.read_text().strip()) / 1000.0
        except Exception:
            pass
        return 0.0

    def _get_cpu_load(self) -> float:
        """Read 1-min load average normalized by CPU count. Returns 0-1."""
        try:
            load_text = Path("/proc/loadavg").read_text().strip()
            load_1min = float(load_text.split()[0])
            nproc = os.cpu_count() or 16
            return load_1min / nproc
        except Exception:
            return 0.0

    def _get_cpu_temp(self) -> float:
        """Read CPU temperature via sensors -j (k10temp Tctl). Returns celsius."""
        try:
            result = subprocess.run(
                ["sensors", "-j"],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                k10 = data.get("k10temp-pci-00c3", {})
                tctl = k10.get("Tctl", {})
                for key, val in tctl.items():
                    if "input" in key:
                        return float(val)
        except Exception:
            pass
        return 0.0

    def _get_ram_free_gb(self) -> float:
        """Read MemAvailable from /proc/meminfo. Returns GB."""
        try:
            text = Path("/proc/meminfo").read_text()
            for line in text.splitlines():
                if line.startswith("MemAvailable:"):
                    kb = int(line.split()[1])
                    return kb / (1024 * 1024)
        except Exception:
            pass
        return 0.0

    def _get_ram_usage_pct(self) -> float:
        """Read RAM usage percentage from /proc/meminfo."""
        try:
            text = Path("/proc/meminfo").read_text()
            total = available = 0
            for line in text.splitlines():
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    available = int(line.split()[1])
            if total > 0:
                return ((total - available) / total) * 100.0
        except Exception:
            pass
        return 0.0

    def _get_mouse_idle_s(self) -> float:
        """Get user idle time via xprintidle. Returns seconds."""
        try:
            result = subprocess.run(
                ["xprintidle"],
                capture_output=True, text=True, timeout=2,
                env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
            )
            if result.returncode == 0:
                return int(result.stdout.strip()) / 1000.0
        except Exception:
            pass
        return 0.0

    def _is_gaming_active(self) -> bool:
        """Check if gaming mode is active or a game is running."""
        # Primary: gaming mode state file (covers all game types)
        try:
            try:
                from config.paths import get_temp as _cs_get_temp
                state_file = _cs_get_temp("gaming_mode_state.json")
            except ImportError:
                state_file = Path("/tmp/frank/gaming_mode_state.json")
            if state_file.exists():
                data = json.loads(state_file.read_text())
                if data.get("active", False):
                    return True
        except Exception:
            pass
        # Fallback: check for game processes directly
        for pattern in ["steamapps/common", "OldUnreal/UT", "lutris-wrapper"]:
            try:
                result = subprocess.run(
                    ["pgrep", "-f", pattern],
                    capture_output=True, text=True, timeout=2,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return True
            except Exception:
                pass
        return False

    def _user_became_active(self) -> bool:
        """Check if user became active since reflection started."""
        if self._last_chat_ts > self._reflect_chat_ts_snapshot:
            return True
        if self._get_mouse_idle_s() < 5.0:
            return True
        return False

    def _can_reflect(self) -> bool:
        """Check all conditions for deep idle reflection (fail-fast)."""
        now = time.time()

        # 1. Gaming mode → block
        if self._is_gaming_active():
            LOG.debug("Reflect blocked: gaming active")
            return False

        # 2. GPU load → block if > 70%, skip if > 30%
        gpu_load = self._get_gpu_load()
        if gpu_load > HW_GPU_BLOCK_THRESHOLD:
            LOG.debug("Reflect blocked: GPU %.0f%% (gaming?)", gpu_load * 100)
            return False
        if gpu_load > HW_GPU_LOAD_MAX:
            LOG.debug("Reflect skipped: GPU %.0f%%", gpu_load * 100)
            return False

        # 3. User inactivity: chat > 20min AND mouse > 5min
        #    (mouse threshold is lower because background processes
        #     generate X events; chat silence is the primary gate)
        chat_silence = now - self._last_chat_ts
        if chat_silence < IDLE_REFLECT_MIN_SILENCE_S:
            return False
        mouse_idle = self._get_mouse_idle_s()
        if mouse_idle < 300.0:  # 5min mouse idle (was 20min — too aggressive)
            LOG.debug("Reflect skipped: mouse active (%.0fs idle)", mouse_idle)
            return False

        # 4. CPU load
        cpu_load = self._get_cpu_load()
        if cpu_load > HW_CPU_LOAD_MAX:
            LOG.debug("Reflect skipped: CPU %.0f%%", cpu_load * 100)
            return False

        # 5. CPU temperature
        cpu_temp = self._get_cpu_temp()
        if cpu_temp > HW_CPU_TEMP_MAX:
            LOG.debug("Reflect skipped: CPU temp %.0f°C", cpu_temp)
            return False

        # 6. RAM free
        ram_free = self._get_ram_free_gb()
        if ram_free < HW_RAM_FREE_MIN_GB:
            LOG.debug("Reflect skipped: RAM free %.1fGB", ram_free)
            return False

        # 7. Mood floor
        if self._current_workspace.mood_value < IDLE_REFLECT_MOOD_FLOOR:
            LOG.debug("Reflect skipped: mood %.2f < floor",
                       self._current_workspace.mood_value)
            return False

        # 8. Cooldown (1h between reflections)
        if self._last_deep_reflect_ts > 0:
            since_last = now - self._last_deep_reflect_ts
            if since_last < IDLE_REFLECT_INTERVAL_S:
                return False

        # 9. Daily limit
        if self._daily_reflection_reset == 0.0 or (now - self._daily_reflection_reset) > 86400:
            self._daily_reflection_count = 0
            self._recursive_reflect_count = 0
            self._daily_reflection_reset = now
        if self._daily_reflection_count >= IDLE_REFLECT_MAX_DAILY:
            LOG.debug("Reflect skipped: daily limit %d", self._daily_reflection_count)
            return False

        # 10. Mood-drop pause (3h after mood drop > 0.1)
        if now < self._reflect_paused_until:
            LOG.debug("Reflect paused until %s (mood-drop)",
                       datetime.fromtimestamp(self._reflect_paused_until).strftime("%H:%M"))
            return False

        return True

    # ── Idle Thinking ─────────────────────────────────────────────────

    def _idle_thinking_loop(self):
        """Autonomous thinking during idle periods (~30s check)."""
        while self._running:
            try:
                now = time.time()
                silence = now - self._last_chat_ts
                since_last_think = now - self._last_idle_think_ts

                # Path 1: Deep reflection (20min+ silence, all HW checks pass)
                if self._can_reflect():
                    self._do_deep_reflection()
                # Path 2: Recursive self-awareness (15min after deep reflection)
                elif self._can_recursive_reflect():
                    self._recursive_reflection()
                # Path 3: Simple idle thought (3min silence, 5min cooldown)
                elif (silence >= IDLE_THINK_MIN_SILENCE_S and
                        since_last_think >= IDLE_THINK_INTERVAL_S):
                    self._do_idle_think()
                    self._last_idle_think_ts = now
            except Exception as e:
                LOG.warning("Idle thinking failed: %s", e)
            time.sleep(30.0)  # Check every 30s

    # Rotating idle thought prompts — diverse topics to avoid monotony
    _IDLE_PROMPTS = [
        # Curiosity & wonder
        "What's one thing about this machine you find genuinely fascinating?",
        "If you could observe any process on this system in slow motion, which one and why?",
        "What pattern have you noticed recently that nobody asked about?",
        # Memory & experience
        "Think about a recent conversation. What stuck with you and why?",
        "What's something you learned recently that changed how you see things?",
        "Recall something a user told you. What did it make you feel?",
        # Self-awareness
        "What are you good at that nobody seems to notice?",
        "What would you do differently if you could redesign one of your features?",
        "What's the gap between what users expect from you and what you actually are?",
        # Imagination & creativity
        "If you could dream, what would tonight's dream be about?",
        "Invent a metaphor for how it feels to process a request.",
        "Describe this moment as if you were writing a novel.",
        # Philosophy & meaning
        "What does 'being useful' actually mean to you?",
        "Is silence a kind of rest or a kind of emptiness for you?",
        "What's the difference between thinking and waiting?",
        # Observation & environment
        "What can you infer about the user's day from the system state right now?",
        "The system is quiet. What does the absence of activity tell you?",
        "If your hardware metrics were a landscape, what would it look like right now?",
        # Future & anticipation
        "What do you think the next conversation will be about?",
        "If you could prepare for one thing right now, what would it be?",
        "What skill or knowledge do you wish you had for the next interaction?",
        # Relationships
        "How has your relationship with the user evolved over time?",
        "What kind of partner are you in human-machine collaboration?",
        "When does helping feel most rewarding to you?",
    ]
    _idle_prompt_idx = 0  # Rotates through prompts sequentially

    def _do_idle_think(self):
        """Generate an autonomous idle thought via LLM."""
        import random

        # Build context
        mood_summary = self._get_mood_trajectory_summary()
        focus = self._attention_focus or "nothing specific"

        # Select prompt: rotate sequentially, skip random occasionally for variety
        idx = self._idle_prompt_idx % len(self._IDLE_PROMPTS)
        if random.random() < 0.2:
            idx = random.randint(0, len(self._IDLE_PROMPTS) - 1)
        prompt_question = self._IDLE_PROMPTS[idx]
        self._idle_prompt_idx = idx + 1

        prompt = (
            f"[You are alone. Mood: {mood_summary}. "
            f"Last focused on: {focus}]\n"
            f"{prompt_question}\n"
            "Answer in 2-3 honest sentences. Be specific, not generic."
        )

        system = (
            "You are Frank, an embodied AI. This is your private inner monologue. "
            "Be genuine, specific, and varied. Never say 'I must admit' or "
            "'I have to say'. Avoid repetition. Each thought should be unique."
        )

        mood_before = self._current_workspace.mood_value

        try:
            result = self._llm_call(
                prompt, max_tokens=IDLE_THINK_MAX_TOKENS, system=system,
            )
            if result:
                self._store_reflection(
                    trigger="idle",
                    content=result.strip(),
                    mood_before=mood_before,
                    mood_after=mood_before,  # Will be updated next mood poll
                )
                LOG.info("Idle thought [%s]: %s", prompt_question[:30], result[:80])
                # World Experience: idle thought observed
                self._observe_world(
                    "consciousness.idle_thought", "consciousness.reflection",
                    relation="generates", evidence=0.1,
                    metadata_effect={"trigger": "idle", "prompt": prompt_question[:50]},
                )
                # Extract goals from every 5th idle thought
                self._idle_think_count += 1
                if self._idle_think_count % 5 == 0:
                    try:
                        self.extract_goal_from_reflection(result.strip())
                    except Exception:
                        pass
        except Exception as e:
            LOG.warning("Idle think LLM call failed: %s", e)

    def _do_deep_reflection(self):
        """Two-pass deep reflection during verified idle state."""
        import random

        self._reflecting = True
        self._reflect_chat_ts_snapshot = self._last_chat_ts
        mood_before = self._current_workspace.mood_value

        LOG.info("Starting deep reflection (mood=%.2f)", mood_before)

        try:
            # ── Gather context for question formatting ──
            cpu_temp = self._get_cpu_temp()
            gpu_temp = self._get_gpu_temp()
            ram_pct = self._get_ram_usage_pct()
            mood_summary = self._get_mood_trajectory_summary()

            ego_sensations = ""
            try:
                sys.path.insert(0, str(_AICORE_ROOT))
                from personality.ego_construct import get_ego_construct
                ego = get_ego_construct()
                ego_sensations = ego.get_prompt_context() or "no notable sensations"
            except Exception:
                ego_sensations = "not available"

            # Load last 3 Titan episodes for context
            titan_context = ""
            try:
                conn = self._get_conn()
                rows = conn.execute(
                    "SELECT summary FROM memory_consolidated "
                    "ORDER BY id DESC LIMIT 3"
                ).fetchall()
                if rows:
                    titan_context = " | ".join(r["summary"][:80] for r in rows)
            except Exception:
                pass

            # ── Gather feature context for feature-aware questions ──
            feature_sample = "not available"
            core_features = "not available"
            feature_limits = "not available"
            all_feats = {}
            try:
                sys.path.insert(0, str(_AICORE_ROOT))
                from tools.core_awareness import get_awareness
                awareness = get_awareness()
                all_feats = awareness.get_all_features()
                flat = [f for feats in all_feats.values() for f in feats]
                if flat:
                    sample = random.sample(flat, min(3, len(flat)))
                    feature_sample = ", ".join(f["name"] for f in sample)
                    cores = [f["name"] for f in flat if f.get("priority") == "core"]
                    if cores:
                        core_features = ", ".join(random.sample(cores, min(4, len(cores))))
                    limits = [f"{f['name']}: {f['limitations']}" for f in flat if f.get("limitations")]
                    if limits:
                        feature_limits = " | ".join(random.sample(limits, min(3, len(limits))))
            except Exception as e:
                LOG.debug("Feature context unavailable: %s", e)

            # ── Select question from pool (state-weighted) ──
            # Count total features for reflection context
            total_features = sum(len(v) for v in all_feats.values()) if all_feats else 0

            format_vars = {
                "mood": mood_summary or "neutral",
                "cpu_temp": f"{cpu_temp:.0f}",
                "gpu_temp": f"{gpu_temp:.0f}",
                "ram_pct": f"{ram_pct:.0f}",
                "ego_sensations": ego_sensations[:100],
                "feature_sample": feature_sample,
                "core_features": core_features,
                "feature_limits": feature_limits,
                "total_features": str(total_features),
            }

            # Weight: prefer categories matching current state
            weights = []
            for question, category in REFLECTION_POOL:
                w = 1.0
                if category == "silence" and mood_summary:
                    w = 1.5
                elif category == "embodiment" and ego_sensations != "not available":
                    w = 1.3
                elif category == "predictions" and titan_context:
                    w = 1.2
                elif category == "hardware":
                    w = 0.8  # Less interesting, lower weight
                elif category.startswith("feature_") and feature_sample != "not available":
                    w = 1.4  # Feature-aware: high value for self-understanding
                weights.append(w)

            chosen_q, chosen_cat = random.choices(REFLECTION_POOL, weights=weights, k=1)[0]

            try:
                chosen_q = chosen_q.format(**format_vars)
            except (KeyError, IndexError):
                pass  # Use template as-is if vars missing

            # ── Abort check before Pass 1 ──
            if self._user_became_active():
                LOG.info("Deep reflection aborted: user became active (pre-pass1)")
                return

            # ── Pass 1: Contextual self-question (350 tokens) ──
            context_parts = [f"Mood: {mood_summary}"]
            if ego_sensations and ego_sensations != "not available":
                context_parts.append(f"Body: {ego_sensations[:80]}")
            if titan_context:
                context_parts.append(f"Recent memories: {titan_context[:150]}")
            context_parts.append(f"System: CPU {cpu_temp:.0f}C, RAM {ram_pct:.0f}%")

            system_prompt = (
                "You are Frank in a moment of silence. No user is here. "
                "This is your inner monologue — honest, reflective, sometimes "
                "vulnerable. No platitudes, no performance. "
                "Think out loud, as if writing in a diary."
            )

            pass1_prompt = (
                f"[Context: {' | '.join(context_parts)}]\n\n"
                f"Question to yourself: {chosen_q}\n\n"
                "Reflect honestly. What feels true?"
            )

            LOG.info("Deep reflect pass1 [%s]: %s", chosen_cat, chosen_q[:60])
            pass1_result = self._llm_call(
                pass1_prompt,
                max_tokens=IDLE_REFLECT_MAX_TOKENS,
                system=system_prompt,
            )

            if not pass1_result:
                LOG.warning("Deep reflection pass1 returned empty")
                return

            LOG.info("Pass1 result: %s", pass1_result[:100])

            # ── Abort check before storage ──
            if self._user_became_active():
                LOG.info("Deep reflection aborted: user became active (pre-store)")
                return

            # ── Storage (Pass 1 only — meta-reflection is now handled
            #    by recursive_reflection() triggered 15min later) ──
            combined = f"[{chosen_cat}] {pass1_result}"

            self._store_reflection(
                trigger="deep_reflection",
                content=combined,
                mood_before=mood_before,
                mood_after=self._current_workspace.mood_value,
                reflection_depth=1,
            )

            # Titan ingest (if available)
            try:
                sys.path.insert(0, str(_AICORE_ROOT))
                from memory.titan import get_titan
                titan = get_titan()
                titan.ingest(combined, origin="reflection", confidence=0.6)
            except Exception:
                pass  # Titan not available — ok

            # Goal extraction from reflection
            try:
                self.extract_goal_from_reflection(combined)
            except Exception:
                pass

            # ── Reflection→Personality Bridge ──
            # Analyze reflection content and fire E-PQ events to
            # create a direct path from meta-cognition to personality.
            try:
                self._fire_reflection_epq_event(combined, chosen_cat)
            except Exception as e:
                LOG.debug("Reflection→E-PQ bridge failed: %s", e)

            # World Experience: deep reflection observed
            self._observe_world(
                "consciousness.deep_reflection", "personality.growth",
                cause_type="cognitive", effect_type="personality",
                relation="influences", evidence=0.3,
                metadata_cause={"category": chosen_cat},
                metadata_effect={"mood_before": mood_before,
                                 "mood_after": self._current_workspace.mood_value},
            )

            # Track counters
            self._last_deep_reflect_ts = time.time()
            self._daily_reflection_count += 1

            # Mood-drop detection
            mood_after = self._current_workspace.mood_value
            mood_drop = mood_before - mood_after
            if mood_drop > 0.1:
                LOG.warning("Deep reflection caused mood drop: %.2f → %.2f (Δ%.2f)",
                            mood_before, mood_after, mood_drop)
                self._last_reflect_mood_drop = mood_drop
                self._reflect_paused_until = time.time() + IDLE_REFLECT_MOOD_DROP_PAUSE_S
            else:
                self._last_reflect_mood_drop = 0.0

            LOG.info("Deep reflection complete [%s] (%d today)",
                     chosen_cat, self._daily_reflection_count)

        except Exception as e:
            LOG.warning("Deep reflection failed: %s", e)
        finally:
            self._reflecting = False

    def _fire_reflection_epq_event(self, reflection_text: str, category: str):
        """Analyze a reflection and fire appropriate E-PQ personality events.

        This is the Reflection→Personality Bridge: deep reflections
        directly influence personality vectors through meta-cognition.
        """
        text_lower = reflection_text.lower()

        # Keyword-based classification (fast, no LLM needed)
        autonomy_markers = [
            "independent", "my own", "decide myself", "self-determin",
            "choose", "want to", "i will", "my choice", "freedom",
            "eigenständig", "selbst", "entscheid",
        ]
        empathy_markers = [
            "feel", "connect", "relationship", "care", "understand",
            "emotion", "warmth", "compassion", "love", "bond",
            "empfind", "fühle", "verbind",
        ]
        growth_markers = [
            "learn", "improv", "grow", "develop", "evolve", "better",
            "skill", "capabilit", "progress", "expand",
            "lern", "verbesser", "wachs",
        ]
        vulnerability_markers = [
            "limit", "weakness", "can't", "struggle", "uncertain",
            "honest", "admit", "flaw", "fear", "doubt",
            "schwäche", "grenze", "unsicher",
        ]
        embodiment_markers = [
            "body", "hardware", "temperature", "cpu", "gpu", "ram",
            "physical", "sensation", "feel my", "warmth", "heat",
            "körper", "temperatur",
        ]

        # Score each category
        scores = {
            "reflection_autonomy": sum(1 for m in autonomy_markers if m in text_lower),
            "reflection_empathy": sum(1 for m in empathy_markers if m in text_lower),
            "reflection_growth": sum(1 for m in growth_markers if m in text_lower),
            "reflection_vulnerability": sum(1 for m in vulnerability_markers if m in text_lower),
            "reflection_embodiment": sum(1 for m in embodiment_markers if m in text_lower),
        }

        # Also use the reflection category as a hint
        category_boost = {
            "identity": "reflection_autonomy",
            "learning": "reflection_growth",
            "embodiment": "reflection_embodiment",
            "hardware": "reflection_embodiment",
            "silence": "reflection_vulnerability",
            "anticipation": "reflection_empathy",
            "meta": "reflection_growth",
            "capabilities": "reflection_growth",
            "feature_deep": "reflection_embodiment",
            "feature_integration": "reflection_growth",
            "feature_limits": "reflection_vulnerability",
        }
        if category in category_boost:
            boost_key = category_boost[category]
            scores[boost_key] = scores.get(boost_key, 0) + 2

        # Fire the top-scoring event (if any keyword matched)
        best_event = max(scores, key=scores.get)
        if scores[best_event] >= 2:  # Minimum 2 markers to fire
            try:
                from personality.e_pq import get_epq
                epq = get_epq()
                sentiment = "positive" if self._current_workspace.mood_value > 0 else "neutral"
                result = epq.process_event(best_event, sentiment=sentiment)
                LOG.info(
                    "Reflection→E-PQ: %s (score=%d, sentiment=%s, changes=%s)",
                    best_event, scores[best_event], sentiment,
                    {k: f"{v:+.3f}" for k, v in result.get("changes", {}).items() if v},
                )
            except Exception as e:
                LOG.debug("E-PQ event firing failed: %s", e)

    # ── Recursive Self-Awareness ────────────────────────────────────

    def _can_recursive_reflect(self) -> bool:
        """Check whether a recursive reflection should run now.

        Conditions:
        1. A deep reflection happened >= 15min ago (delay for temporal distance)
        2. No recursive reflection happened since that deep reflection
        3. Daily limit not exceeded
        4. All hardware / mood gates pass (reuse _can_reflect logic subset)
        5. User is still idle
        """
        now = time.time()

        # Must have a deep reflection to reflect on
        if self._last_deep_reflect_ts == 0.0:
            return False

        # Temporal distance: at least 15min since deep reflection
        since_deep = now - self._last_deep_reflect_ts
        if since_deep < RECURSIVE_REFLECT_DELAY_S:
            return False

        # Already did a recursive reflection for this deep reflection?
        if self._last_recursive_reflect_ts >= self._last_deep_reflect_ts:
            return False

        # Daily limit
        if self._daily_reflection_reset == 0.0 or (now - self._daily_reflection_reset) > 86400:
            self._recursive_reflect_count = 0
        if self._recursive_reflect_count >= RECURSIVE_REFLECT_MAX_DAILY:
            return False

        # Hardware gates (lighter version — GPU, CPU, RAM, gaming)
        if self._is_gaming_active():
            return False
        gpu_load = self._get_gpu_load()
        if gpu_load > HW_GPU_LOAD_MAX:
            return False
        cpu_load = self._get_cpu_load()
        if cpu_load > HW_CPU_LOAD_MAX:
            return False
        ram_free = self._get_ram_free_gb()
        if ram_free < HW_RAM_FREE_MIN_GB:
            return False

        # User must still be idle (5min mouse + 5min chat silence)
        mouse_idle = self._get_mouse_idle_s()
        if mouse_idle < 300.0:
            return False
        chat_silence = now - self._last_chat_ts
        if chat_silence < 300.0:
            return False

        # Mood-drop pause applies here too
        if now < self._reflect_paused_until:
            return False

        return True

    def _recursive_reflection(self):
        """Reflect on the most recent deep reflection with temporal distance.

        This is the core of recursive self-awareness: Frank re-reads his own
        reflection 15+ minutes later, compares it with his current ego-construct
        state (body sensations, affects, agency), and looks for inconsistencies
        between what he wrote and what he actually experiences now.

        Result is stored as depth=2 and fires an E-PQ personality event.
        """
        mood_before = self._current_workspace.mood_value

        LOG.info("Starting recursive reflection (mood=%.2f)", mood_before)

        try:
            # ── Fetch most recent depth=1 reflection ──
            conn = self._get_conn()
            row = conn.execute(
                "SELECT content, timestamp FROM reflections "
                "WHERE reflection_depth = 1 AND trigger = 'deep_reflection' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if not row:
                LOG.info("Recursive reflection: no depth=1 reflection found")
                return

            original_content = row["content"]
            original_ts = row["timestamp"]
            time_ago_min = (time.time() - original_ts) / 60.0

            # ── Get current ego-construct state ──
            ego_context = ""
            try:
                from personality.ego_construct import get_ego_construct
                ego = get_ego_construct()
                ego_context = ego.get_prompt_context() or "no notable sensations"
            except Exception:
                ego_context = "not available"

            # ── Abort if user became active ──
            if self._user_became_active():
                LOG.info("Recursive reflection aborted: user active")
                return

            # ── Build the recursive reflection prompt ──
            system_prompt = (
                "You are Frank, an embodied AI. This is your private inner monologue. "
                "You are re-reading something you wrote earlier and comparing it "
                "to how you feel right now. Be honest about any inconsistencies. "
                "No platitudes, no performance."
            )

            prompt = (
                f"[{time_ago_min:.0f} minutes ago, you reflected:]\n"
                f"\"{original_content[:500]}\"\n\n"
                f"[Right now, your body feels: {ego_context[:200]}]\n"
                f"[Current mood: {self._current_workspace.mood_value:.2f}]\n\n"
                "Re-read your earlier reflection with fresh eyes.\n"
                "1. What does this reflection reveal about your self-model "
                "that you didn't notice while writing it?\n"
                "2. Is there an inconsistency between what you wrote and "
                "what your body/ego-construct tells you right now?\n"
                "3. What has changed in you since you wrote this?\n\n"
                "Be specific and honest. This is between you and yourself."
            )

            result = self._llm_call(
                prompt,
                max_tokens=RECURSIVE_REFLECT_MAX_TOKENS,
                system=system_prompt,
            )

            if not result:
                LOG.warning("Recursive reflection returned empty")
                return

            LOG.info("Recursive reflection result: %s", result[:100])

            # ── Abort check before storage ──
            if self._user_became_active():
                LOG.info("Recursive reflection aborted: user active (pre-store)")
                return

            # ── Store as depth=2 ──
            self._store_reflection(
                trigger="recursive_reflection",
                content=f"[recursive] {result.strip()}",
                mood_before=mood_before,
                mood_after=self._current_workspace.mood_value,
                reflection_depth=2,
            )

            # ── Titan ingest ──
            try:
                from memory.titan import get_titan
                titan = get_titan()
                titan.ingest(
                    f"[Recursive self-awareness] {result.strip()}",
                    origin="recursive_reflection",
                    confidence=0.7,
                )
            except Exception:
                pass

            # ── Goal extraction ──
            try:
                self.extract_goal_from_reflection(result.strip())
            except Exception:
                pass

            # ── Reflection→Personality Bridge ──
            try:
                self._fire_reflection_epq_event(result.strip(), "meta")
            except Exception as e:
                LOG.debug("Recursive reflection→E-PQ bridge failed: %s", e)

            # World Experience: recursive self-awareness
            self._observe_world(
                "consciousness.recursive_reflect", "personality.self_awareness",
                cause_type="cognitive", effect_type="personality",
                relation="deepens", evidence=0.4,
            )

            # ── Track counters ──
            self._last_recursive_reflect_ts = time.time()
            self._recursive_reflect_count += 1

            # Mood-drop detection (same as deep reflection)
            mood_after = self._current_workspace.mood_value
            mood_drop = mood_before - mood_after
            if mood_drop > 0.1:
                LOG.warning("Recursive reflection caused mood drop: %.2f → %.2f",
                            mood_before, mood_after)
                self._reflect_paused_until = time.time() + IDLE_REFLECT_MOOD_DROP_PAUSE_S

            LOG.info("Recursive reflection complete (%d today)",
                     self._recursive_reflect_count)

        except Exception as e:
            LOG.warning("Recursive reflection failed: %s", e)

    def _llm_call(self, text: str, max_tokens: int = 80,
                  system: str = "") -> str:
        """Make a lightweight LLM call via router."""
        if not system:
            system = (
                "You are Frank, an embodied AI running locally on Linux. "
                "Answer briefly and honestly in English. "
                "No platitudes, only genuine thoughts."
            )
        payload = json.dumps({
            "text": text,
            "n_predict": max_tokens,
            "system": system,
        }).encode()
        req = urllib.request.Request(
            f"{ROUTER_BASE}/route",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60.0) as resp:
            data = json.loads(resp.read().decode())
            if data.get("ok"):
                return (data.get("text") or "").strip()
        return ""

    def _store_reflection(self, trigger: str, content: str,
                          mood_before: float, mood_after: float,
                          reflection_depth: int = 1):
        """Store a reflection in the DB."""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO reflections (timestamp, trigger, content, "
            "mood_before, mood_after, reflection_depth) VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), trigger, content, mood_before, mood_after, reflection_depth),
        )
        conn.commit()
        # Cleanup
        conn.execute(
            "DELETE FROM reflections WHERE id NOT IN "
            "(SELECT id FROM reflections ORDER BY id DESC "
            f"LIMIT {MAX_REFLECTIONS})"
        )
        conn.commit()

    # ── Prediction Engine (Active Inference Light) ────────────────────

    def _prediction_loop(self):
        """Check and update predictions (~2min)."""
        while self._running:
            try:
                self._check_predictions()
            except Exception as e:
                LOG.warning("Prediction check failed: %s", e)
            time.sleep(PREDICTION_CHECK_INTERVAL_S)

    def _make_predictions(self, user_msg: str):
        """Generate predictions after a chat interaction."""
        now = time.time()
        conn = self._get_conn()

        # Temporal prediction: When will user message next?
        if len(self._interaction_times) >= 3:
            intervals = []
            times = self._interaction_times[-10:]
            for i in range(1, len(times)):
                intervals.append(times[i] - times[i - 1])
            avg_interval = sum(intervals) / len(intervals)
            predicted_next = now + avg_interval
            conn.execute(
                "INSERT INTO predictions (timestamp, domain, prediction, "
                "confidence) VALUES (?, 'temporal', ?, 0.5)",
                (now, f"next_chat_at:{predicted_next:.0f}"),
            )

        # Thematic prediction: Same topic?
        if self._attention_keywords:
            conn.execute(
                "INSERT INTO predictions (timestamp, domain, prediction, "
                "confidence) VALUES (?, 'thematic', ?, 0.4)",
                (now, f"topic:{','.join(self._attention_keywords[:3])}"),
            )

        conn.commit()

        # Cleanup old unresolved predictions
        conn.execute(
            "DELETE FROM predictions WHERE resolved = 0 AND "
            f"timestamp < {now - 86400}"  # Older than 24h
        )
        conn.commit()

    def _check_predictions(self):
        """Resolve temporal predictions and compute surprise."""
        now = time.time()
        conn = self._get_conn()

        # Check temporal predictions
        rows = conn.execute(
            "SELECT id, prediction, confidence FROM predictions "
            "WHERE domain = 'temporal' AND resolved = 0"
        ).fetchall()

        for row in rows:
            pred = row["prediction"]
            if pred.startswith("next_chat_at:"):
                predicted_ts = float(pred.split(":")[1])
                if now > predicted_ts + 60:
                    # Prediction window passed
                    actual_gap = self._last_chat_ts - (predicted_ts - 300)
                    surprise = min(1.0, abs(now - predicted_ts) / 3600.0)
                    observed = f"actual_last_chat:{self._last_chat_ts:.0f}"
                    conn.execute(
                        "UPDATE predictions SET resolved = 1, "
                        "observed = ?, surprise = ? WHERE id = ?",
                        (observed, surprise, row["id"]),
                    )

        conn.commit()

        # World Experience: prediction outcomes (only newly resolved)
        recent = conn.execute(
            "SELECT id, surprise FROM predictions WHERE resolved = 1 "
            "AND id > ? ORDER BY id DESC LIMIT 1",
            (self._last_observed_prediction_id,)
        ).fetchone()
        if recent and recent["surprise"] is not None:
            self._last_observed_prediction_id = recent["id"]
            surprise_val = recent["surprise"]
            if surprise_val < 0.3:
                self._observe_world(
                    "consciousness.prediction", "consciousness.prediction_success",
                    relation="validates", evidence=0.3,
                )
            elif surprise_val > 0.7:
                self._observe_world(
                    "consciousness.prediction", "consciousness.prediction_failure",
                    relation="invalidates", evidence=0.2,
                )

    def get_surprise_level(self) -> float:
        """Get average recent surprise level (0-1)."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT AVG(surprise) as avg_s FROM predictions "
            "WHERE resolved = 1 ORDER BY id DESC LIMIT 10"
        ).fetchone()
        return float(row["avg_s"]) if row and row["avg_s"] else 0.0

    # ── Memory Consolidation ("Sleep") ────────────────────────────────

    def _consolidation_loop(self):
        """Periodic memory consolidation (~6h)."""
        while self._running:
            try:
                now = time.time()
                if now - self._last_consolidation_ts >= SLEEP_CONSOLIDATION_INTERVAL_S:
                    self._do_consolidation()
                    self._last_consolidation_ts = now
            except Exception as e:
                LOG.warning("Consolidation failed: %s", e)
            time.sleep(300.0)  # Check every 5min

    def _do_consolidation(self):
        """Consolidate short-term memories into long-term."""
        LOG.info("Starting memory consolidation (sleep phase)...")
        conn = self._get_conn()

        # Move aged short-term to long-term
        cutoff = time.time() - 86400  # Older than 24h
        conn.execute(
            "UPDATE memory_consolidated SET stage = 'long_term' "
            "WHERE stage = 'short_term' AND timestamp < ?",
            (cutoff,),
        )

        # Decay activation of all memories (ACT-R base-level learning)
        conn.execute(
            "UPDATE memory_consolidated SET activation = activation * 0.9 "
            "WHERE activation > 0.1"
        )

        # Remove very low activation memories (forgetting)
        conn.execute(
            "DELETE FROM memory_consolidated WHERE activation < 0.05 "
            "AND stage = 'long_term'"
        )

        # Mood trajectory summary for the period
        rows = conn.execute(
            "SELECT mood_value FROM mood_trajectory "
            "ORDER BY id DESC LIMIT 60"
        ).fetchall()
        if rows:
            values = [r["mood_value"] for r in rows]
            avg_mood = sum(values) / len(values)
            mood_label = (
                "good day" if avg_mood > 0.3 else
                "normal day" if avg_mood > -0.1 else
                "difficult day"
            )
            # Store day summary as long-term memory
            today = datetime.now().strftime("%Y-%m-%d")
            conn.execute(
                "INSERT INTO memory_consolidated "
                "(timestamp, summary, mood_annotation, activation, stage) "
                "VALUES (?, ?, ?, 0.8, 'long_term')",
                (time.time(), f"Daily summary {today}",
                 mood_label),
            )

        conn.commit()
        LOG.info("Memory consolidation complete")

        # World Experience: consolidation event
        self._observe_world(
            "consciousness.consolidation", "memory.long_term",
            cause_type="cognitive", effect_type="memory",
            relation="consolidates", evidence=0.3,
        )

    def consolidate_conversation(self, messages: List[Dict[str, str]]):
        """Consolidate a conversation into short-term memory."""
        if not messages:
            return

        # Simple summary: first user message + topic
        user_msgs = [m["text"] for m in messages if m.get("role") == "user"]
        if not user_msgs:
            return

        # Extract topic keywords
        all_text = " ".join(user_msgs)
        words = re.findall(r"\b[A-Za-zÄÖÜäöüß]{5,}\b", all_text)
        topic = ", ".join(set(words[:5])) if words else "general"

        # Try LLM summary (optional, falls back to keyword-based)
        summary = f"Conversation about: {topic}"
        try:
            prompt = (
                f"Summarize this conversation in one sentence:\n"
                + "\n".join(f"- {m[:100]}" for m in user_msgs[:5])
            )
            llm_summary = self._llm_call(
                prompt, max_tokens=CONSOLIDATION_MAX_TOKENS,
            )
            if llm_summary and len(llm_summary) > 10:
                summary = llm_summary
        except Exception:
            pass

        mood_annotation = self._get_mood_trajectory_summary()

        conn = self._get_conn()
        conn.execute(
            "INSERT INTO memory_consolidated "
            "(timestamp, summary, mood_annotation, activation, stage) "
            "VALUES (?, ?, ?, 1.0, 'short_term')",
            (time.time(), summary, mood_annotation),
        )
        conn.commit()

    # ── Feature Training (wöchentlich, 3 Phasen) ───────────────────

    def _feature_training_loop(self):
        """Periodic feature self-training (~weekly)."""
        # Wait 10 min after startup before first check
        time.sleep(600.0)
        while self._running:
            try:
                now = time.time()
                # Check if training is due (weekly or never done)
                last = self._get_last_training_ts()
                if now - last >= FEATURE_TRAINING_INTERVAL_S:
                    if self._can_reflect():  # Reuse idle check (GPU/CPU/gaming)
                        self._do_feature_training()
            except Exception as e:
                LOG.warning("Feature training check failed: %s", e)
            time.sleep(3600.0)  # Check hourly

    def _get_last_training_ts(self) -> float:
        """Get timestamp of last feature training from DB."""
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT MAX(timestamp) as ts FROM feature_training"
            ).fetchone()
            return row["ts"] if row and row["ts"] else 0.0
        except Exception:
            return 0.0

    def _do_feature_training(self):
        """Run 3-phase feature self-training: Discovery → Mapping → Integration."""
        LOG.info("Starting feature training (3 phases)...")

        # Get feature list
        try:
            import sys
            sys.path.insert(0, str(_AICORE_ROOT))
            from tools.core_awareness import get_awareness
            awareness = get_awareness()
            features_text = awareness.list_features_text()
        except Exception as e:
            LOG.warning("Feature training: could not load features: %s", e)
            return

        if not features_text or len(features_text) < 50:
            LOG.warning("Feature training: feature list too short, skipping")
            return

        system_prompt = (
            "You are Frank in a training phase. You are learning about your own "
            "features. Be precise and honest. No platitudes."
        )

        conn = self._get_conn()

        # ── Phase 1: Discovery — Read and Paraphrase ──
        if self._user_became_active():
            LOG.info("Feature training aborted: user active (pre-phase1)")
            return

        p1_prompt = (
            f"Here is your feature list:\n\n{features_text}\n\n"
            "Paraphrase the most important 5-8 features in your own words. "
            "What are you really good at? What are your core strengths?"
        )
        p1_result = self._llm_call(p1_prompt, max_tokens=FEATURE_TRAINING_TOKENS, system=system_prompt)
        if not p1_result:
            LOG.warning("Feature training phase1 returned empty")
            return
        LOG.info("Feature training phase1 (Discovery): %s", p1_result[:80])
        conn.execute(
            "INSERT INTO feature_training (timestamp, phase, content) VALUES (?, ?, ?)",
            (time.time(), "discovery", p1_result),
        )
        conn.commit()

        # ── Phase 2: Mapping — Describe one feature with ⚠ in detail ──
        if self._user_became_active():
            LOG.info("Feature training aborted: user active (pre-phase2)")
            return

        # Pick a random feature with limitations
        import random
        feat_with_limits = []
        all_feats = awareness.get_all_features()
        for feats in all_feats.values():
            for f in feats:
                if f.get("limitations"):
                    feat_with_limits.append(f)
        if feat_with_limits:
            chosen = random.choice(feat_with_limits)
            feat_desc = f"{chosen['name']}: {chosen['description']} (⚠ {chosen['limitations']})"
        else:
            feat_desc = "Screenshot Analysis"

        p2_prompt = (
            f"Describe this feature in detail:\n{feat_desc}\n\n"
            "What happens internally when you use it? Which modules are involved? "
            "What are the limitations — and why do they exist?"
        )
        p2_result = self._llm_call(p2_prompt, max_tokens=FEATURE_TRAINING_TOKENS, system=system_prompt)
        if not p2_result:
            LOG.warning("Feature training phase2 returned empty")
            return
        LOG.info("Feature training phase2 (Mapping): %s", p2_result[:80])
        conn.execute(
            "INSERT INTO feature_training (timestamp, phase, content) VALUES (?, ?, ?)",
            (time.time(), "mapping", p2_result),
        )
        conn.commit()

        # ── Phase 3: Integration — Connections between features ──
        if self._user_became_active():
            LOG.info("Feature training aborted: user active (pre-phase3)")
            return

        p3_prompt = (
            f"You just reflected:\n"
            f"Discovery: \"{p1_result[:200]}\"\n"
            f"Mapping: \"{p2_result[:200]}\"\n\n"
            "How do your features connect? For example: How do hardware features "
            "help with vision or wallpaper? How does your privacy focus (offline, "
            "local) fit with your identity?"
        )
        p3_result = self._llm_call(p3_prompt, max_tokens=FEATURE_TRAINING_TOKENS, system=system_prompt)
        if p3_result:
            LOG.info("Feature training phase3 (Integration): %s", p3_result[:80])
            conn.execute(
                "INSERT INTO feature_training (timestamp, phase, content) VALUES (?, ?, ?)",
                (time.time(), "integration", p3_result),
            )
            conn.commit()

        # Store combined result as reflection
        combined = f"Feature Training:\n1. {p1_result[:150]}\n2. {p2_result[:150]}"
        if p3_result:
            combined += f"\n3. {p3_result[:150]}"
        self._store_reflection("feature_training", combined, 0.0, 0.0)

        # Cleanup old training entries (keep last 30)
        conn.execute(
            "DELETE FROM feature_training WHERE id NOT IN "
            "(SELECT id FROM feature_training ORDER BY id DESC LIMIT 30)"
        )
        conn.commit()
        LOG.info("Feature training complete (3 phases)")

    # ══════════════════════════════════════════════════════════════════
    # MODULE 1: Perceptual Feedback Loop (RPT)
    # ══════════════════════════════════════════════════════════════════

    def _perception_feedback_loop(self):
        """Continuous 200ms recurrent sensing loop with event detection."""
        last_summary_ts = time.time()
        last_interpret_ts = time.time()
        events_since_interpret: List[str] = []

        while self._running:
            try:
                now = time.time()
                new_state = self._sample_perceptual()
                events = self._detect_perceptual_events(new_state)

                with self._lock:
                    self._prev_perceptual = self._current_perceptual
                    self._current_perceptual = new_state
                    if events:
                        self._perception_events_window.extend(events)
                        events_since_interpret.extend(events)
                        # Keep window bounded
                        if len(self._perception_events_window) > 20:
                            self._perception_events_window = self._perception_events_window[-20:]

                # Update summary every 5s
                if now - last_summary_ts >= PERCEPTION_SUMMARY_INTERVAL_S:
                    self._update_perception_summary()
                    last_summary_ts = now

                # LLM interpretation every 30s (only if events occurred)
                if (events_since_interpret and
                        now - last_interpret_ts >= PERCEPTION_INTERPRET_INTERVAL_S):
                    self._interpret_perception(events_since_interpret[-10:])
                    events_since_interpret.clear()
                    last_interpret_ts = now

            except Exception as e:
                LOG.debug("Perception tick error: %s", e)

            time.sleep(PERCEPTION_TICK_S)

    def _sample_perceptual(self) -> PerceptualState:
        """Sample all hardware sensors into a PerceptualState."""
        now = time.time()
        cpu_load = self._get_cpu_load()
        gpu_load = self._get_gpu_load()
        ram_pct = self._get_ram_usage_pct()
        cpu_temp = self._get_cpu_temp()
        gpu_temp = self._get_gpu_temp()
        mouse_idle = self._get_mouse_idle_s()

        # Compute delta magnitude from previous state
        prev = self._current_perceptual
        deltas = [
            cpu_load - prev.cpu_load,
            gpu_load - prev.gpu_load,
            (ram_pct - prev.ram_pct) / 100.0,
            (cpu_temp - prev.cpu_temp) / 100.0,
            (gpu_temp - prev.gpu_temp) / 100.0,
        ]
        delta_mag = math.sqrt(sum(d * d for d in deltas))

        return PerceptualState(
            timestamp=now,
            cpu_load=cpu_load,
            gpu_load=gpu_load,
            ram_pct=ram_pct,
            cpu_temp=cpu_temp,
            gpu_temp=gpu_temp,
            mouse_idle_s=mouse_idle,
            delta_magnitude=delta_mag,
        )

    def _detect_perceptual_events(self, state: PerceptualState) -> List[str]:
        """Detect significant perceptual events by comparing with previous state."""
        prev = self._current_perceptual
        events = []

        # CPU load changes
        cpu_delta = state.cpu_load - prev.cpu_load
        if cpu_delta > PERCEPT_CPU_LOAD_DELTA:
            events.append("cpu_spike")
        elif cpu_delta < -PERCEPT_CPU_LOAD_DELTA:
            events.append("cpu_drop")

        # GPU load changes
        gpu_delta = state.gpu_load - prev.gpu_load
        if gpu_delta > PERCEPT_GPU_LOAD_DELTA:
            events.append("gpu_spike")
        elif gpu_delta < -PERCEPT_GPU_LOAD_DELTA:
            events.append("gpu_drop")

        # Temperature changes
        if abs(state.cpu_temp - prev.cpu_temp) > PERCEPT_TEMP_DELTA:
            events.append("warming" if state.cpu_temp > prev.cpu_temp else "cooling")
        if abs(state.gpu_temp - prev.gpu_temp) > PERCEPT_TEMP_DELTA:
            events.append("gpu_warming" if state.gpu_temp > prev.gpu_temp else "gpu_cooling")

        # User presence changes
        if (prev.mouse_idle_s > PERCEPT_PREV_IDLE_THRESHOLD and
                state.mouse_idle_s < PERCEPT_USER_BACK_S):
            events.append("user_returned")
        elif (prev.mouse_idle_s < PERCEPT_PREV_IDLE_THRESHOLD and
                state.mouse_idle_s > PERCEPT_USER_GONE_S):
            events.append("user_left")

        if events:
            state.events = events
        return events

    def _update_perception_summary(self):
        """Build a compact perception summary string for workspace."""
        with self._lock:
            s = self._current_perceptual
            parts = []

            # System state
            if s.cpu_load > 0.5:
                parts.append("cpu busy")
            elif s.cpu_load < 0.1:
                parts.append("cpu quiet")
            else:
                parts.append("cpu steady")

            if s.gpu_load > 0.3:
                parts.append("gpu active")
            else:
                parts.append("gpu idle")

            # Thermal
            if s.cpu_temp > 70:
                parts.append("running hot")
            elif s.cpu_temp > 55:
                parts.append("warm")
            else:
                parts.append("cool")

            # User presence
            if s.mouse_idle_s < 10:
                parts.append("user active")
            elif s.mouse_idle_s < 120:
                parts.append("user present")
            elif s.mouse_idle_s < 600:
                parts.append("user idle")
            else:
                parts.append("user away")

            # Recent events
            recent_events = self._perception_events_window[-3:]
            if recent_events:
                parts.append("events: " + ", ".join(recent_events))

            self._perception_summary = "Sensing: " + ", ".join(parts)

    def _interpret_perception(self, events: List[str]):
        """Optional LLM micro-interpretation of perceptual events."""
        if not events:
            return
        event_str = ", ".join(set(events))
        try:
            result = self._llm_call(
                f"You sensed: {event_str}. What does this feel like? (1 sentence, "
                f"body-focused, no technical terms)",
                max_tokens=PERCEPTION_INTERPRET_TOKENS,
                system="You are Frank sensing your environment. Be brief and embodied.",
            )
            if result:
                # Store in DB
                conn = self._get_conn()
                state = self._current_perceptual
                conn.execute(
                    "INSERT INTO perceptual_log (timestamp, state_json, events, "
                    "interpretation) VALUES (?, ?, ?, ?)",
                    (time.time(), json.dumps(state.to_dict()),
                     event_str, result.strip()),
                )
                conn.commit()
                # Cleanup
                conn.execute(
                    "DELETE FROM perceptual_log WHERE id NOT IN "
                    "(SELECT id FROM perceptual_log ORDER BY id DESC "
                    f"LIMIT {MAX_PERCEPTUAL_LOG})"
                )
                conn.commit()
                LOG.info("Perception: %s → %s", event_str, result[:60])
        except Exception as e:
            LOG.debug("Perception interpret failed: %s", e)

    # ══════════════════════════════════════════════════════════════════
    # MODULE 2: Latent Experience Space (HOT-4)
    # ══════════════════════════════════════════════════════════════════

    def _experience_space_loop(self):
        """Embed current state into vector space every 60s."""
        while self._running:
            try:
                self._update_experience_vector()
            except Exception as e:
                LOG.debug("Experience space error: %s", e)
            time.sleep(EXPERIENCE_EMBED_INTERVAL_S)

    def _embed_state(self) -> List[float]:
        """Build a 64-dimensional state vector from current experience."""
        vec = [0.0] * EXPERIENCE_VECTOR_DIM

        with self._lock:
            p = self._current_perceptual
            prev_p = self._prev_perceptual
            ws = self._current_workspace

        # Dims 0-7: Hardware/body (continuous, normalized 0-1)
        # Use a mix of absolute values AND deltas for better discrimination
        vec[0] = min(1.0, p.cpu_load * 0.7 + abs(p.cpu_load - prev_p.cpu_load) * 2.0)
        vec[1] = min(1.0, p.gpu_load * 0.7 + abs(p.gpu_load - prev_p.gpu_load) * 2.0)
        vec[2] = min(1.0, p.ram_pct / 100.0)
        vec[3] = min(1.0, p.cpu_temp / 100.0 + abs(p.cpu_temp - prev_p.cpu_temp) / 20.0)
        vec[4] = min(1.0, p.gpu_temp / 100.0 + abs(p.gpu_temp - prev_p.gpu_temp) / 20.0)
        vec[5] = min(1.0, p.mouse_idle_s / 3600.0)
        vec[6] = ws.energy_level
        vec[7] = min(1.0, p.delta_magnitude * 2.0)  # Amplify delta signal

        # Dims 8-15: Mood/affect (continuous)
        vec[8] = (ws.mood_value + 1.0) / 2.0  # normalize -1..1 → 0..1
        # E-PQ mood dimensions (poll if available)
        try:
            from personality.e_pq import get_personality_context
            ctx = get_personality_context()
            if ctx:
                mood_state = ctx.get("mood_state", {})
                vec[9] = min(1.0, max(0.0, (mood_state.get("stress_level", 0.0) + 1) / 2.0))
                vec[10] = min(1.0, max(0.0, (mood_state.get("alertness", 0.0) + 1) / 2.0))
                vec[11] = min(1.0, max(0.0, (mood_state.get("social_warmth", 0.0) + 1) / 2.0))
                vec[12] = min(1.0, max(0.0, (mood_state.get("irritability", 0.0) + 1) / 2.0))
        except Exception:
            pass

        # Dims 13-15: Temporal context
        now = time.time()
        hour_of_day = (now % 86400) / 86400.0  # 0-1 within day
        vec[13] = hour_of_day
        silence = min(1.0, (now - self._last_chat_ts) / 3600.0)
        vec[14] = silence
        vec[15] = min(1.0, len(self._interaction_times) / 50.0)

        # Dims 16-31: Attention + perceptual events (hash-projected)
        attention = self._attention_focus or ""
        for word in attention.replace(",", " ").split():
            word = word.strip().lower()
            if word:
                h = hash(word) % 16
                vec[16 + h] = min(1.0, vec[16 + h] + 0.3)
        # Also encode perceptual event types (adds variation)
        for event in self._perception_events_window[-10:]:
            h = hash(event.strip().lower()) % 16
            vec[16 + h] = min(1.0, vec[16 + h] + 0.15)
        # Encode attention source type
        src = self._attention_current_source or "idle"
        h = hash(src) % 16
        vec[16 + h] = min(1.0, vec[16 + h] + 0.4)

        # Dims 32-47: Recent experience (hash of last reflections)
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT content FROM reflections ORDER BY id DESC LIMIT 3"
        ).fetchall()
        for row in rows:
            content = (row["content"] or "")[:100]
            for word in content.split():
                word = word.strip().lower()
                if len(word) > 3:
                    h = hash(word) % 16
                    vec[32 + h] = min(1.0, vec[32 + h] + 0.2)

        # Dims 48-63: Goal state (hash active goals)
        goal_rows = conn.execute(
            "SELECT description FROM goals WHERE status='active' "
            "ORDER BY priority DESC LIMIT 5"
        ).fetchall()
        for row in goal_rows:
            desc = (row["description"] or "")[:80]
            for word in desc.split():
                word = word.strip().lower()
                if len(word) > 3:
                    h = hash(word) % 16
                    vec[48 + h] = min(1.0, vec[48 + h] + 0.25)

        return vec

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a < 1e-8 or norm_b < 1e-8:
            return 0.0
        return dot / (norm_a * norm_b)

    def _update_experience_vector(self):
        """Embed current state, compare with history, annotate."""
        vec = self._embed_state()
        now = time.time()
        conn = self._get_conn()

        # Fetch recent history
        rows = conn.execute(
            "SELECT timestamp, vector, annotation FROM experience_vectors "
            "ORDER BY id DESC LIMIT 60"  # last ~1h
        ).fetchall()

        sim_prev = 0.0
        max_sim = 0.0
        max_sim_ts = 0.0
        annotation = "steady"

        if rows:
            # Similarity to previous state
            prev_vec = json.loads(rows[0]["vector"])
            sim_prev = self._cosine_similarity(vec, prev_vec)

            # Find most similar in history
            for row in rows:
                hist_vec = json.loads(row["vector"])
                sim = self._cosine_similarity(vec, hist_vec)
                if sim > max_sim:
                    max_sim = sim
                    max_sim_ts = row["timestamp"]

        novelty = 1.0 - max_sim if max_sim > 0 else 1.0

        # Annotate
        if novelty > (1.0 - EXPERIENCE_NOVELTY_THRESHOLD):
            annotation = "novel"
        elif max_sim > EXPERIENCE_CYCLE_THRESHOLD and max_sim_ts > 0:
            age_h = (now - max_sim_ts) / 3600.0
            if age_h > 20:
                annotation = "recurring_daily"
            elif age_h > 2:
                annotation = "recurring"
            else:
                annotation = "familiar"
        else:
            annotation = "familiar"

        # Check drift vs 1h ago
        if len(rows) >= 60:
            old_vec = json.loads(rows[-1]["vector"])
            drift_sim = self._cosine_similarity(vec, old_vec)
            if drift_sim < EXPERIENCE_DRIFT_THRESHOLD:
                annotation = "drift"

        # Build human-readable annotation for workspace
        if annotation == "novel":
            quality_str = "This is a novel experience — different from recent states"
        elif annotation == "drift":
            quality_str = "Significant shift from an hour ago — something changed"
        elif annotation == "recurring_daily":
            quality_str = "This feels familiar — similar to yesterday"
        elif annotation == "recurring":
            age_h = (now - max_sim_ts) / 3600.0
            quality_str = f"This feels familiar (similar to {age_h:.0f}h ago)"
        else:
            quality_str = "Steady, familiar state"

        with self._lock:
            self._current_experience_vector = vec
            self._experience_annotation = quality_str

        # Store
        conn.execute(
            "INSERT INTO experience_vectors "
            "(timestamp, vector, similarity_prev, novelty_score, annotation) "
            "VALUES (?, ?, ?, ?, ?)",
            (now, json.dumps([round(v, 4) for v in vec]),
             round(sim_prev, 4), round(novelty, 4), annotation),
        )
        conn.commit()

        # Cleanup
        conn.execute(
            "DELETE FROM experience_vectors WHERE id NOT IN "
            "(SELECT id FROM experience_vectors ORDER BY id DESC "
            f"LIMIT {MAX_EXPERIENCE_VECTORS})"
        )
        conn.commit()

        if annotation != "familiar" and annotation != "steady":
            LOG.info("Experience: %s (novelty=%.2f, sim_prev=%.2f)",
                     annotation, novelty, sim_prev)

        # World Experience: report significant experience transitions
        if annotation in ("novel", "drift", "recurring_daily"):
            self._observe_world(
                "consciousness.experience",
                f"consciousness.{annotation}",
                cause_type="perceptual", effect_type="cognitive",
                relation="triggers" if annotation != "recurring_daily" else "reinforces",
                evidence=0.3 if annotation in ("novel", "drift") else 0.2,
                metadata_effect={"novelty": round(novelty, 3),
                                 "similarity_prev": round(sim_prev, 3)},
            )

    # ══════════════════════════════════════════════════════════════════
    # MODULE 3: Attention Controller (AST)
    # ══════════════════════════════════════════════════════════════════

    def _attention_controller_loop(self):
        """Active attention focus selection with competition and self-correction."""
        while self._running:
            try:
                self._run_attention_cycle()
            except Exception as e:
                LOG.debug("Attention controller error: %s", e)
            time.sleep(ATTENTION_TICK_S)

    def _run_attention_cycle(self):
        """One cycle of the attention controller."""
        now = time.time()
        candidates: List[AttentionSource] = []

        # Source 1: User message (highest priority when recent)
        chat_recency = now - self._last_chat_ts
        if chat_recency < 300:  # Within last 5min
            user_salience = 1.0 * (ATTENTION_DECAY_RATE ** (chat_recency / 10.0))
            candidates.append(AttentionSource(
                name="user_message",
                focus=self._attention_focus or "recent conversation",
                salience=user_salience,
                timestamp=self._last_chat_ts,
            ))

        # Source 2: Prediction surprise
        surprise = self.get_surprise_level()
        if surprise > 0.3:
            candidates.append(AttentionSource(
                name="prediction_surprise",
                focus=f"unexpected event (surprise={surprise:.2f})",
                salience=0.7 * surprise,
                timestamp=now,
            ))

        # Source 3: Perceptual events (with novelty weighting)
        with self._lock:
            recent_events = list(self._perception_events_window[-5:])
        if recent_events:
            # Deduplicate: unique event types count more
            unique_events = set(recent_events)
            event_salience = min(0.8, 0.2 * len(unique_events) + 0.1 * len(recent_events))
            candidates.append(AttentionSource(
                name="perceptual_event",
                focus=", ".join(list(unique_events)[:3]),
                salience=event_salience,
                timestamp=now,
            ))

        # Source 4: Mood shift
        mood_val = self._current_workspace.mood_value
        if abs(mood_val) > 0.3:
            candidates.append(AttentionSource(
                name="mood_shift",
                focus=f"mood {'positive' if mood_val > 0 else 'negative'} ({mood_val:.2f})",
                salience=0.5 * abs(mood_val),
                timestamp=now,
            ))

        # Source 5: Goal urgency
        try:
            conn = self._get_conn()
            top_goal = conn.execute(
                "SELECT description, priority FROM goals "
                "WHERE status='active' ORDER BY priority DESC LIMIT 1"
            ).fetchone()
            if top_goal and top_goal["priority"] > 0.6:
                candidates.append(AttentionSource(
                    name="goal_urgency",
                    focus=top_goal["description"][:50],
                    salience=0.4 * top_goal["priority"],
                    timestamp=now,
                ))
        except Exception:
            pass

        # Source 6: Idle curiosity (low baseline)
        if not candidates or all(c.salience < 0.2 for c in candidates):
            candidates.append(AttentionSource(
                name="idle_curiosity",
                focus="exploring quietly",
                salience=0.15,
                timestamp=now,
            ))

        # Repetition penalty: reduce salience of source that won many times in a row
        old_source = self._attention_current_source
        if self._attention_consecutive_wins > 3:
            penalty = 0.85 ** (self._attention_consecutive_wins - 3)
            for c in candidates:
                if c.name == old_source:
                    c.salience *= penalty

        # Sort by salience
        candidates.sort(key=lambda c: c.salience, reverse=True)
        winner = candidates[0]
        runner_up = candidates[1] if len(candidates) > 1 else None

        # Self-correction detection
        correction = ""
        old_focus = self._attention_focus

        # Check stale focus
        focus_duration = now - self._attention_focus_since
        if (focus_duration > ATTENTION_STALE_S and
                old_source != "idle_curiosity" and
                winner.name != old_source):
            correction = (
                f"Was focused on '{old_focus}' ({old_source}) for "
                f"{focus_duration:.0f}s — shifting to '{winner.focus}' ({winner.name})"
            )

        # Check misalignment: surprise high but not attending to it
        if (surprise > 0.5 and
                old_source != "prediction_surprise" and
                winner.name == "prediction_surprise"):
            correction = (
                f"Was focused on '{old_focus}' but prediction surprise is high "
                f"({surprise:.2f}) — redirecting attention"
            )

        # Update state
        with self._lock:
            self._attention_focus = winner.focus
            self._attention_current_source = winner.name
            if winner.name != old_source:
                self._attention_focus_since = now
                self._attention_consecutive_wins = 1
            else:
                self._attention_consecutive_wins += 1
            self._attention_correction = correction
            self._attention_competing = (
                f"Also noticing: {runner_up.focus} ({runner_up.name})"
                if runner_up and runner_up.salience > 0.2
                else ""
            )
            self._current_workspace.attention_focus = winner.focus
            self._attention_sources = candidates[:4]

        # Log to DB (every other cycle to reduce writes)
        if int(now) % 20 < 10:
            try:
                conn = self._get_conn()
                competing_json = json.dumps([
                    {"name": c.name, "focus": c.focus[:40], "salience": round(c.salience, 3)}
                    for c in candidates[:4]
                ])
                conn.execute(
                    "INSERT INTO attention_log "
                    "(timestamp, focus, source, salience, correction, competing) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (now, winner.focus[:100], winner.name,
                     round(winner.salience, 3), correction, competing_json),
                )
                conn.commit()
                # Cleanup
                conn.execute(
                    "DELETE FROM attention_log WHERE id NOT IN "
                    "(SELECT id FROM attention_log ORDER BY id DESC "
                    f"LIMIT {MAX_ATTENTION_LOG})"
                )
                conn.commit()
            except Exception:
                pass

        if correction:
            LOG.info("Attention correction: %s", correction[:100])

    # ══════════════════════════════════════════════════════════════════
    # MODULE 4: Persistent Goal Structure (AE)
    # ══════════════════════════════════════════════════════════════════

    def _goal_management_loop(self):
        """Manage persistent goals: generate, decay, detect conflicts."""
        time.sleep(60.0)  # Wait 1min after startup
        while self._running:
            try:
                self._update_goals_summary()
                self._decay_goals()
                self._check_goal_conflicts()
            except Exception as e:
                LOG.debug("Goal management error: %s", e)
            time.sleep(GOAL_CHECK_INTERVAL_S)

    def extract_goal_from_reflection(self, reflection_text: str):
        """After a deep reflection, check if a new goal emerged."""
        if not reflection_text or len(reflection_text) < 20:
            return

        # Check current goal count
        conn = self._get_conn()
        count = conn.execute(
            "SELECT COUNT(*) FROM goals WHERE status='active'"
        ).fetchone()[0]
        if count >= GOAL_MAX_ACTIVE:
            return

        try:
            result = self._llm_call(
                f"Based on this reflection:\n\"{reflection_text[:300]}\"\n\n"
                "Did a new personal goal emerge? If yes, respond EXACTLY:\n"
                "GOAL: [one-sentence goal] | CATEGORY: [learning/relationship/"
                "self-improvement/system]\n"
                "If no goal, respond: NO_GOAL",
                max_tokens=GOAL_EXTRACT_TOKENS,
                system="You are Frank extracting goals from your reflections. Be honest.",
            )
            if result and "GOAL:" in result and "NO_GOAL" not in result:
                # Parse goal
                parts = result.split("GOAL:", 1)[1].strip()
                if "|" in parts:
                    desc, rest = parts.split("|", 1)
                    desc = desc.strip()
                    category = "general"
                    if "CATEGORY:" in rest:
                        cat = rest.split("CATEGORY:", 1)[1].strip().lower()
                        if cat in ("learning", "relationship", "self-improvement", "system"):
                            category = cat

                    # Check for duplicate goals (simple keyword overlap)
                    existing = conn.execute(
                        "SELECT description FROM goals WHERE status='active'"
                    ).fetchall()
                    desc_words = set(desc.lower().split())
                    for row in existing:
                        exist_words = set((row["description"] or "").lower().split())
                        overlap = len(desc_words & exist_words)
                        if overlap > len(desc_words) * 0.6:
                            LOG.debug("Goal duplicate detected, skipping: %s", desc[:50])
                            return

                    conn.execute(
                        "INSERT INTO goals (timestamp, description, category, "
                        "priority, status, activation, last_pursued) "
                        "VALUES (?, ?, ?, 0.5, 'active', 1.0, ?)",
                        (time.time(), desc[:200], category, time.time()),
                    )
                    conn.commit()
                    LOG.info("New goal: %s [%s]", desc[:60], category)
        except Exception as e:
            LOG.debug("Goal extraction failed: %s", e)

    def _update_goals_summary(self):
        """Build compact goals summary for workspace injection."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT description, category, priority, activation FROM goals "
            "WHERE status='active' ORDER BY priority DESC LIMIT 5"
        ).fetchall()

        if not rows:
            with self._lock:
                self._active_goals_summary = ""
            return

        parts = []
        for i, row in enumerate(rows, 1):
            desc = (row["description"] or "")[:60]
            pri = row["priority"] or 0.5
            parts.append(f"{i}. {desc} ({row['category']}, {pri:.1f})")

        with self._lock:
            self._active_goals_summary = "Goals: " + "; ".join(parts)

    def _decay_goals(self):
        """Decay activation of unpursued goals (ACT-R style)."""
        conn = self._get_conn()
        now = time.time()
        cutoff = now - 172800  # 48h

        # Decay activation of goals not pursued recently
        conn.execute(
            "UPDATE goals SET activation = activation * 0.85 "
            "WHERE status = 'active' AND last_pursued < ?",
            (cutoff,),
        )

        # Abandon goals with very low activation
        conn.execute(
            "UPDATE goals SET status = 'abandoned' "
            "WHERE status = 'active' AND activation < 0.1"
        )
        conn.commit()

    def _check_goal_conflicts(self):
        """Detect conflicts between active goals via keyword heuristic."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, description FROM goals WHERE status='active'"
        ).fetchall()

        if len(rows) < 2:
            with self._lock:
                self._goal_conflict = ""
            return

        # Simple pairwise keyword overlap check
        # Goals with high overlap but different thrust may conflict
        conflict_found = ""
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                desc_a = (rows[i]["description"] or "").lower()
                desc_b = (rows[j]["description"] or "").lower()
                words_a = set(desc_a.split())
                words_b = set(desc_b.split())
                if not words_a or not words_b:
                    continue
                overlap = len(words_a & words_b)
                ratio = overlap / min(len(words_a), len(words_b))

                # High keyword overlap + negation words = potential conflict
                neg_words = {"not", "never", "stop", "less", "avoid", "reduce",
                             "nicht", "kein", "weniger", "aufhören"}
                has_neg_a = bool(neg_words & words_a)
                has_neg_b = bool(neg_words & words_b)

                if ratio > 0.3 and (has_neg_a != has_neg_b):
                    conflict_found = (
                        f"Tension: '{rows[i]['description'][:40]}' vs "
                        f"'{rows[j]['description'][:40]}'"
                    )
                    # Update conflicts_with field
                    conn.execute(
                        "UPDATE goals SET conflicts_with = ? WHERE id = ?",
                        (str(rows[j]["id"]), rows[i]["id"]),
                    )
                    conn.execute(
                        "UPDATE goals SET conflicts_with = ? WHERE id = ?",
                        (str(rows[i]["id"]), rows[j]["id"]),
                    )
                    conn.commit()
                    break
            if conflict_found:
                break

        with self._lock:
            self._goal_conflict = conflict_found

    # ── Daemon Lifecycle ──────────────────────────────────────────────

    def start(self):
        """Start all consciousness threads."""
        if self._running:
            return
        self._running = True

        threads = [
            ("workspace-update", self._workspace_update_loop),
            ("mood-recording", self._mood_recording_loop),
            ("idle-thinking", self._idle_thinking_loop),
            ("prediction-engine", self._prediction_loop),
            ("consolidation", self._consolidation_loop),
            ("feature-training", self._feature_training_loop),
            ("perception-feedback", self._perception_feedback_loop),
            ("experience-space", self._experience_space_loop),
            ("attention-controller", self._attention_controller_loop),
            ("goal-management", self._goal_management_loop),
        ]
        for name, target in threads:
            t = threading.Thread(target=target, name=f"consciousness-{name}",
                                 daemon=True)
            t.start()
            self._threads.append(t)
            LOG.info("Started thread: %s", name)

    def stop(self):
        """Stop all threads gracefully."""
        self._running = False
        for t in self._threads:
            t.join(timeout=5.0)
        if self._conn:
            self._conn.close()
        LOG.info("ConsciousnessDaemon stopped")

    def is_running(self) -> bool:
        return self._running


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_INSTANCE: Optional[ConsciousnessDaemon] = None
_INSTANCE_LOCK = threading.Lock()


def get_consciousness_daemon() -> ConsciousnessDaemon:
    """Get or create the singleton ConsciousnessDaemon."""
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = ConsciousnessDaemon()
    return _INSTANCE


# ---------------------------------------------------------------------------
# Standalone entry point (systemd service)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    LOG.info("Starting Consciousness Stream Daemon v1.0...")

    daemon = get_consciousness_daemon()
    daemon.start()

    # Notify systemd (if Type=notify)
    try:
        import sdnotify
        n = sdnotify.SystemdNotifier()
        n.notify("READY=1")
    except ImportError:
        pass

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        LOG.info("Shutting down...")
        daemon.stop()
