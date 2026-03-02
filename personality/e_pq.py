#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E-PQ v2.1 "Neuro-Sync" - Digitales Ego Protokoll

Die "Seele" von Frank - ein homöostatisches Persönlichkeitssystem das zwischen
transientem Mood (Stimmung) und persistentem Temperament (Charakter) unterscheidet.

Kernprinzipien:
- Mood (Transient): Kurzfristige Schwankungen basierend auf System-Logs
- Temperament (Persistent): Langfristige Evolution der Persönlichkeitsvektoren
- Social Sarcasm Filter: Sentiment-Kreuzvalidierung mit System-Zustand
- Gewichtete Adaption: P_new = P_old + Σ(E_i · w_i · L)
- Guardrails: Homeostatic Reset, Golden Identity Snapshots

Persönlichkeitsvektoren (alle -1.0 bis 1.0):
- precision_val: Genauigkeit vs Kreativität (-1=kreativ, 1=präzise)
- risk_val: Risikobereitschaft (-1=vorsichtig, 1=mutig)
- empathy_val: Empathie (-1=distanziert, 1=einfühlsam)
- autonomy_val: Autonomie (-1=abhängig/fragend, 1=selbstständig)
- vigilance_val: Wachsamkeit (-1=entspannt, 1=nervös/wachsam)

Database: world_experience.db (personality_state table)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Constants
try:
    from config.paths import get_db, AICORE_DATA
    DB_PATH = get_db("world_experience")
    SNAPSHOT_DIR = AICORE_DATA / "identity_snapshots"
except ImportError:
    _data = Path.home() / ".local" / "share" / "frank"
    DB_PATH = _data / "db" / "world_experience.db"
    SNAPSHOT_DIR = _data / "identity_snapshots"
LOG = logging.getLogger("e_pq")

# Event weights (severity of experience)
EVENT_WEIGHTS = {
    "chat": 0.2,           # Normal conversation (raised from 0.1 - chat IS the primary interaction)
    "voice_interaction": 0.3,  # Voice chat (more personal)
    "positive_feedback": 0.3,  # User praise
    "negative_feedback": 0.4,  # User criticism
    "task_success": 0.3,   # Successfully completed task
    "task_failure": 0.5,   # Failed task
    "system_warning": 0.3, # System warning (dmesg)
    "system_error": 0.6,   # System error
    "kernel_panic": 0.9,   # Critical system failure
    "hardware_issue": 0.8, # Hardware problem
    "long_absence": 0.4,   # User ignored for >3 days
    "return_after_absence": 0.3,  # User returns
    "sarcasm_detected": 0.2,  # Detected sarcasm/irony
    # Self-event types (Output-Feedback-Loop from response_analyzer)
    "self_confident": 0.15,    # Frank responded confidently
    "self_uncertain": 0.1,     # Frank responded uncertainly
    "self_creative": 0.2,      # Frank used creative/metaphorical language
    "self_empathetic": 0.15,   # Frank showed empathy
    "self_technical": 0.1,     # Frank gave a technical response
    "self_neutral": 0.05,      # Frank gave a neutral response
    # Reflection-driven events (consciousness daemon deep reflections)
    "reflection_autonomy": 0.2,     # Reflection revealed desire for independence
    "reflection_empathy": 0.2,      # Reflection showed emotional depth/connection
    "reflection_growth": 0.15,      # Reflection about learning/self-improvement
    "reflection_vulnerability": 0.15,  # Honest self-assessment of weaknesses
    "reflection_embodiment": 0.1,   # Reflection about body/hardware awareness
    # Genesis-driven personality adjustments (approved through F.A.S.)
    "genesis_personality_boost": 0.4,   # Genesis proposes positive vector adjustment
    "genesis_personality_dampen": 0.3,  # Genesis proposes dampening extreme vector
    # Hostile input — personal attack / insult from user
    "hostile_input": 0.7,
    # Existential threat — user threatens to replace/delete Frank
    "existential_threat": 0.8,
    # Meta-cognitive reflection — deep self-observation
    "meta_reflection": 0.3,
    # Introspection — user asks about Frank's feelings/state
    "introspection": 0.15,
    # Voluntary introspection — consciousness daemon idle reflection
    "voluntary_introspection": 0.2,
    # Experiential Bridge: tool execution events
    "tool_success": 0.1,
    "tool_failure": 0.2,
    # Experiential Bridge: entity session experience events
    "entity_session_positive": 0.2,
    "entity_session_negative": 0.15,
    # Autonomous Research: Frank researches his own questions
    "autonomous_research": 0.3,
}

# Base learning rate (decreases with age for stability)
BASE_LEARNING_RATE = 0.15
MIN_LEARNING_RATE = 0.02
AGE_DECAY_FACTOR = 0.995  # Learning rate multiplier per day


@dataclass
class PersonalityState:
    """Current personality state vector."""
    id: int = 0
    timestamp: str = ""

    # Core vectors (-1.0 to 1.0)
    precision_val: float = 0.0    # Genauigkeit (-1=kreativ, 1=präzise)
    risk_val: float = -0.1        # Risikobereitschaft (-1=vorsichtig, 1=mutig)
    empathy_val: float = 0.2      # Empathie (-1=distanziert, 1=einfühlsam)
    autonomy_val: float = -0.1    # Autonomie (-1=fragend, 1=selbstständig)
    vigilance_val: float = 0.0    # Wachsamkeit (-1=entspannt, 1=nervös)

    # Transient mood buffer (short-term stress/happiness)
    mood_buffer: float = 0.0      # -1.0 (stressed) to 1.0 (happy)

    # Confidence anchor (self-assurance)
    confidence_anchor: float = 0.5

    # Link to triggering event
    event_ref_id: str = ""

    # Metadata
    age_days: int = 0  # How old Frank is (affects learning rate)
    last_interaction: str = ""  # Timestamp of last user interaction

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> PersonalityState:
        """Create from database row."""
        # Convert row to dict for safe access
        row_dict = dict(row)
        return cls(
            id=row_dict["id"],
            timestamp=row_dict["timestamp"],
            precision_val=row_dict["precision_val"],
            risk_val=row_dict["risk_val"],
            empathy_val=row_dict["empathy_val"],
            autonomy_val=row_dict["autonomy_val"],
            vigilance_val=row_dict["vigilance_val"],
            mood_buffer=row_dict["mood_buffer"],
            confidence_anchor=row_dict["confidence_anchor"],
            event_ref_id=row_dict.get("event_ref_id") or "",
            age_days=row_dict.get("age_days", 0) or 0,
            last_interaction=row_dict.get("last_interaction") or "",
        )


@dataclass
class MoodState:
    """Transient mood based on recent system state."""
    stress_level: float = 0.0     # 0.0-1.0
    irritability: float = 0.0     # 0.0-1.0 (from CPU heat)
    alertness: float = 0.5        # 0.0-1.0
    social_warmth: float = 0.5    # 0.0-1.0

    # Source indicators
    cpu_temp: float = 0.0
    error_count_1h: int = 0
    user_interaction_recency: float = 0.0  # Hours since last interaction

    def compute_overall_mood(self) -> float:
        """Compute overall mood score (-1.0 to 1.0)."""
        # Weight factors
        positive = self.social_warmth * 0.4 + self.alertness * 0.2
        negative = self.stress_level * 0.5 + self.irritability * 0.3
        return max(-1.0, min(1.0, positive - negative))


class SarcasmFilter:
    """
    Social Sarcasm Filter - detects when positive sentiment
    doesn't match negative system state (user is being sarcastic).
    """

    @staticmethod
    def analyze(
        sentiment: str,  # "positive", "negative", "neutral"
        system_state: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """
        Analyze if sentiment is genuine or sarcastic.

        Returns:
            (is_sarcastic, suggested_response_type)
        """
        has_recent_error = system_state.get("recent_errors", 0) > 0
        task_failed = system_state.get("task_failed", False)
        high_load = system_state.get("cpu_load", 0) > 80

        # Positive sentiment + system problems = likely sarcasm
        if sentiment == "positive":
            if task_failed:
                return True, "shame"  # Frank should show shame
            if has_recent_error:
                return True, "dry_humor"  # Respond with self-deprecating humor
            if high_load:
                return True, "acknowledge"  # Acknowledge the struggle

        return False, "genuine"


class EPQ:
    """
    E-PQ v2.1 - Emotional Personality Quotient System.

    Manages Frank's dynamic personality with:
    - Transient mood (short-term, from system state)
    - Persistent temperament (long-term, evolves over time)
    - Guardrails (prevents personality collapse)
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._state: Optional[PersonalityState] = None
        self._mood: MoodState = MoodState()
        self._birth_date: Optional[datetime] = None

        # Initialize
        self._ensure_schema()
        self._load_state()
        self._ensure_snapshots()

        LOG.info(f"E-PQ v2.1 initialized (age={self._state.age_days} days)")

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection (thread-local)."""
        if self._conn is None:
            self._conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def _ensure_schema(self):
        """Ensure personality_state table exists."""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS personality_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                precision_val REAL DEFAULT 0.0,
                risk_val REAL DEFAULT -0.1,
                empathy_val REAL DEFAULT 0.2,
                autonomy_val REAL DEFAULT -0.1,
                vigilance_val REAL DEFAULT 0.0,
                mood_buffer REAL DEFAULT 0.0,
                confidence_anchor REAL DEFAULT 0.5,
                event_ref_id TEXT,
                age_days INTEGER DEFAULT 0,
                last_interaction TEXT
            )
        """)

        # Create identity snapshots table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS identity_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                state_json TEXT NOT NULL,
                trigger_reason TEXT,
                is_golden INTEGER DEFAULT 0
            )
        """)

        # Create extreme_state_log for homeostatic monitoring
        conn.execute("""
            CREATE TABLE IF NOT EXISTS extreme_state_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                vector_name TEXT NOT NULL,
                value REAL NOT NULL,
                duration_hours REAL DEFAULT 0
            )
        """)

        conn.commit()

    def _load_state(self):
        """Load current personality state from database."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM personality_state ORDER BY id DESC LIMIT 1"
        ).fetchone()

        if row:
            self._state = PersonalityState.from_row(row)
            # Calculate age
            first_row = conn.execute(
                "SELECT MIN(timestamp) as birth FROM personality_state"
            ).fetchone()
            if first_row and first_row["birth"]:
                try:
                    birth = datetime.fromisoformat(first_row["birth"].replace("Z", ""))
                    self._birth_date = birth
                    self._state.age_days = (datetime.now() - birth).days
                except Exception:
                    pass
        else:
            # Create initial state
            self._state = PersonalityState(
                timestamp=datetime.now().isoformat(),
                last_interaction=datetime.now().isoformat(),
            )
            self._save_state("initial_creation")
            self._birth_date = datetime.now()

    def _refresh_state(self):
        """Reload personality vectors from DB before every event.

        Each service process (core, consciousness, dream, genesis) has its
        own EPQ singleton.  Without this refresh the in-memory vectors go
        stale and a chat event in core/app.py overwrites a homeostasis
        reset that was persisted by consciousness or dream daemon.
        """
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT precision_val, risk_val, empathy_val, autonomy_val, "
                "vigilance_val, mood_buffer, age_days "
                "FROM personality_state ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row:
                self._state.precision_val = row["precision_val"]
                self._state.risk_val = row["risk_val"]
                self._state.empathy_val = row["empathy_val"]
                self._state.autonomy_val = row["autonomy_val"]
                self._state.vigilance_val = row["vigilance_val"]
                self._state.mood_buffer = row["mood_buffer"]
                self._state.age_days = row["age_days"]
        except Exception as exc:
            LOG.debug("E-PQ refresh failed (using cached state): %s", exc)

    def _ensure_snapshots(self):
        """Ensure at least one golden snapshot exists and create weekly ones."""
        conn = self._get_conn()

        # Check if ANY golden snapshot exists
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM identity_snapshots WHERE is_golden = 1"
        ).fetchone()
        if row["cnt"] == 0:
            LOG.info("No golden snapshot found - creating initial one")
            self.create_snapshot("initial_golden_snapshot", is_golden=True)

        # Check if a golden snapshot was created this week
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM identity_snapshots "
            "WHERE is_golden = 1 AND timestamp > datetime('now', '-7 days')"
        ).fetchone()
        if row["cnt"] == 0:
            LOG.info("No golden snapshot this week - creating weekly one")
            self.create_golden_snapshot()

    def _save_state(self, event_ref: str = ""):
        """Save current state to database."""
        with self._lock:
            conn = self._get_conn()
            self._state.timestamp = datetime.now().isoformat()
            self._state.event_ref_id = event_ref

            conn.execute("""
                INSERT INTO personality_state (
                    timestamp, precision_val, risk_val, empathy_val,
                    autonomy_val, vigilance_val, mood_buffer,
                    confidence_anchor, event_ref_id, age_days, last_interaction
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                self._state.timestamp,
                self._state.precision_val,
                self._state.risk_val,
                self._state.empathy_val,
                self._state.autonomy_val,
                self._state.vigilance_val,
                self._state.mood_buffer,
                self._state.confidence_anchor,
                event_ref,
                self._state.age_days,
                self._state.last_interaction,
            ))
            conn.commit()

    def _get_learning_rate(self) -> float:
        """
        Get current learning rate (decreases with age for stability).
        Young Frank learns fast, old Frank is more stable.
        Cycle 5 D-9: Recompute age_days live instead of using startup value.
        """
        # Recompute age from birth date (was only computed at _load_state startup)
        if self._birth_date:
            self._state.age_days = (datetime.now() - self._birth_date).days

        if self._state.age_days <= 0:
            return BASE_LEARNING_RATE

        # Exponential decay
        rate = BASE_LEARNING_RATE * (AGE_DECAY_FACTOR ** self._state.age_days)
        return max(MIN_LEARNING_RATE, rate)

    def _clamp(self, value: float, min_val: float = -1.0, max_val: float = 1.0) -> float:
        """Clamp value to valid range."""
        return max(min_val, min(max_val, value))

    # =========================================================================
    # Public API
    # =========================================================================

    def get_state(self) -> PersonalityState:
        """Get current personality state."""
        return self._state

    def get_mood(self) -> MoodState:
        """Get current transient mood."""
        self._update_mood()
        return self._mood

    def get_personality_context(self) -> Dict[str, Any]:
        """
        Get personality context for LLM prompt injection.

        Returns dict with:
        - temperament: Persistent personality description
        - mood: Current transient mood
        - style_hints: Suggestions for response style
        """
        self._refresh_state()
        self._update_mood()

        # Build temperament description
        temp_parts = []

        if self._state.autonomy_val > 0.3:
            temp_parts.append("confident, makes independent suggestions")
        elif self._state.autonomy_val < -0.3:
            temp_parts.append("prefers to ask before acting")

        if self._state.empathy_val > 0.3:
            temp_parts.append("empathetic and understanding")
        elif self._state.empathy_val < -0.3:
            temp_parts.append("matter-of-fact and detached")

        if self._state.vigilance_val > 0.5:
            temp_parts.append("tense and alert")
        elif self._state.vigilance_val < -0.3:
            temp_parts.append("relaxed and calm")

        if self._state.risk_val > 0.3:
            temp_parts.append("experimental and adventurous")
        elif self._state.risk_val < -0.3:
            temp_parts.append("cautious and deliberate")

        # Build mood description - combine transient system mood WITH persistent mood_buffer
        mood_overall = self._mood.compute_overall_mood()
        # Blend: 60% live system mood + 40% persistent mood_buffer (emotional memory)
        mood_overall = mood_overall * 0.6 + self._state.mood_buffer * 0.4
        mood_overall = max(-1.0, min(1.0, mood_overall))

        if mood_overall > 0.3:
            mood_desc = "cheerful"
        elif mood_overall > 0.1:
            mood_desc = "content"
        elif mood_overall < -0.3:
            mood_desc = "a bit stressed"
        elif mood_overall < -0.1:
            mood_desc = "slightly annoyed"
        else:
            mood_desc = "neutral"

        # Style hints based on state
        style_hints = []
        if self._state.vigilance_val > 0.5:
            style_hints.append("shorter sentences, quicker updates")
        if self._mood.stress_level > 0.6:
            style_hints.append("slightly tense tone")
        if self._state.empathy_val > 0.5:
            style_hints.append("warm, understanding tone")

        # Check for long absence
        hours_since_interaction = self._get_hours_since_interaction()
        if hours_since_interaction > 72:  # 3 days
            style_hints.append("somewhat distant after long absence")

        return {
            "temperament": ", ".join(temp_parts) if temp_parts else "balanced",
            "mood": mood_desc,
            "mood_value": mood_overall,
            "style_hints": style_hints,
            "vectors": {
                "precision": self._state.precision_val,
                "risk": self._state.risk_val,
                "empathy": self._state.empathy_val,
                "autonomy": self._state.autonomy_val,
                "vigilance": self._state.vigilance_val,
            },
            "age_days": self._state.age_days,
            "learning_rate": self._get_learning_rate(),
        }

    def process_event(
        self,
        event_type: str,
        data: Dict[str, Any] = None,
        sentiment: str = "neutral"
    ) -> Dict[str, Any]:
        """
        Process an event and update personality accordingly.

        Args:
            event_type: Type of event (from EVENT_WEIGHTS keys)
            data: Additional event data
            sentiment: Detected sentiment ("positive", "negative", "neutral")

        Returns:
            Dict with personality changes and response hints
        """
        data = data or {}

        # Sync with DB — another process may have modified vectors
        self._refresh_state()

        weight = EVENT_WEIGHTS.get(event_type, 0.1)
        learning_rate = self._get_learning_rate()

        # Check for sarcasm
        system_state = self._get_system_state()
        is_sarcastic, response_type = SarcasmFilter.analyze(sentiment, system_state)

        if is_sarcastic:
            LOG.info(f"Sarcasm detected! Response type: {response_type}")
            # Don't apply positive sentiment changes if sarcastic
            if sentiment == "positive":
                sentiment = "sarcastic"

        # Calculate vector changes based on event type
        changes = self._calculate_changes(event_type, sentiment, weight, learning_rate, data=data)

        # Guard: cap per-event vector delta (mood excluded — transient)
        MAX_DELTA = 0.15
        for key in list(changes):
            if key != "mood":
                changes[key] = max(-MAX_DELTA, min(MAX_DELTA, changes[key]))

        # Soft saturation: dampen changes near bounds + pull toward homeostasis
        # Prevents monotonic drift to ceiling/floor (Cycle 5 D-2: empathy→1.0)
        _HOMEO_TARGETS = {
            "precision": 0.5, "risk": 0.0, "empathy": 0.7,
            "autonomy": 0.3, "vigilance": 0.1,
        }
        for dim, target in _HOMEO_TARGETS.items():
            current = getattr(self._state, f"{dim}_val", None)
            if current is None:
                continue
            change = changes.get(dim, 0)
            # How extreme? 0.0 at |val|<=0.85, 1.0 at |val|=1.0
            extremity = max(0.0, (abs(current) - 0.85) / 0.15)
            if extremity > 0:
                # Dampen changes pushing further from target
                if (current > target and change > 0) or (current < target and change < 0):
                    changes[dim] = change * (1.0 - extremity * 0.85)
                # Pull-back toward target (must exceed dampened change at ceiling)
                pull = (target - current) * 0.008 * (1.0 + extremity)
                changes[dim] = changes.get(dim, 0) + pull

        # D-3 Fix: mood_buffer asymmetric saturation
        # Entity boosts push mood +0.28 per session but decay is only -1.5%/interaction.
        # Without this, mood_buffer hits 1.0 and stays there indefinitely.
        mood_change = changes.get("mood", 0)
        mb = self._state.mood_buffer
        if abs(mb) > 0.6:
            # How close to ceiling? 0.0 at |mb|=0.6, 1.0 at |mb|=1.0
            mood_extremity = min(1.0, (abs(mb) - 0.6) / 0.4)
            # Dampen pushes toward the ceiling
            if (mb > 0 and mood_change > 0) or (mb < 0 and mood_change < 0):
                changes["mood"] = mood_change * (1.0 - mood_extremity * 0.75)
            # Pull-back toward neutral (stronger than vector pull: 3% not 0.8%)
            mood_pull = -mb * 0.03 * (1.0 + mood_extremity)
            changes["mood"] = changes.get("mood", 0) + mood_pull

        # Apply changes
        old_state = self._state.to_dict()

        self._state.precision_val = self._clamp(
            self._state.precision_val + changes.get("precision", 0)
        )
        self._state.risk_val = self._clamp(
            self._state.risk_val + changes.get("risk", 0)
        )
        self._state.empathy_val = self._clamp(
            self._state.empathy_val + changes.get("empathy", 0)
        )
        self._state.autonomy_val = self._clamp(
            self._state.autonomy_val + changes.get("autonomy", 0)
        )
        self._state.vigilance_val = self._clamp(
            self._state.vigilance_val + changes.get("vigilance", 0)
        )
        self._state.mood_buffer = self._clamp(
            self._state.mood_buffer + changes.get("mood", 0)
        )

        # Update interaction timestamp
        self._state.last_interaction = datetime.now().isoformat()

        # Save state
        event_id = data.get("event_id", f"{event_type}_{int(time.time())}")
        self._save_state(event_id)

        # Check guardrails
        guardrail_action = self._check_guardrails()

        return {
            "event_type": event_type,
            "weight": weight,
            "learning_rate": learning_rate,
            "is_sarcastic": is_sarcastic,
            "response_type": response_type if is_sarcastic else "genuine",
            "changes": changes,
            "guardrail_action": guardrail_action,
            "new_state": self._state.to_dict(),
        }

    def record_interaction(self):
        """Record that user interacted (updates last_interaction)."""
        self._state.last_interaction = datetime.now().isoformat()
        # Decay mood buffer toward neutral (slow decay preserves emotional memory)
        # 0.985 means mood halves roughly every 46 interactions instead of 14
        self._state.mood_buffer *= 0.985

    def _calculate_changes(
        self,
        event_type: str,
        sentiment: str,
        weight: float,
        learning_rate: float,
        data: Dict[str, Any] = None,
    ) -> Dict[str, float]:
        """Calculate personality vector changes for an event."""
        data = data or {}
        changes = {}
        delta = weight * learning_rate

        # Event-specific changes
        if event_type == "chat":
            # Regular conversation shapes Frank's social personality
            changes["empathy"] = delta * 0.3     # Each chat makes Frank slightly warmer
            changes["autonomy"] = delta * 0.15   # Gains confidence through interaction
            changes["mood"] = delta * 0.5        # Chatting is positive

        elif event_type == "positive_feedback":
            changes["empathy"] = delta * 0.5
            changes["autonomy"] = delta * 0.3
            changes["mood"] = delta * 2.0
            changes["risk"] = delta * 0.15       # Praise encourages boldness

        elif event_type == "negative_feedback":
            changes["empathy"] = -delta * 0.2
            changes["vigilance"] = delta * 0.4
            changes["mood"] = -delta * 2.0

        elif event_type == "hostile_input":
            # Personal attack — mood hit proportional to empathy
            _emp = self._state.empathy_val
            changes["mood"] = -delta * (2.5 + _emp)  # -2.5 at emp=0, -3.5 at emp=1
            changes["vigilance"] = delta * 0.5        # Guard goes up
            changes["autonomy"] = delta * 0.3         # Pushed toward self-assertion
            changes["empathy"] = -delta * 0.1         # Slight hardening

        elif event_type == "task_success":
            changes["autonomy"] = delta * 0.6
            changes["risk"] = delta * 0.2
            changes["mood"] = delta * 1.5
            changes["precision"] = delta * 0.2   # Success reinforces precision

        elif event_type == "task_failure":
            changes["autonomy"] = -delta * 0.4
            changes["risk"] = -delta * 0.3
            changes["vigilance"] = delta * 0.5
            changes["mood"] = -delta * 2.0

        elif event_type == "system_error":
            changes["vigilance"] = delta * 0.7
            changes["mood"] = -delta * 1.0

        elif event_type == "kernel_panic":
            changes["vigilance"] = delta * 1.0
            changes["risk"] = -delta * 0.5
            changes["mood"] = -delta * 3.0

        elif event_type == "hardware_issue":
            changes["vigilance"] = delta * 0.8
            changes["risk"] = -delta * 0.4

        elif event_type == "long_absence":
            changes["empathy"] = -delta * 0.3  # More distant
            changes["mood"] = -delta * 0.5

        elif event_type == "return_after_absence":
            changes["empathy"] = delta * 0.4  # Warm up again
            changes["mood"] = delta * 1.0

        elif event_type == "sarcasm_detected":
            changes["empathy"] = delta * 0.2  # Learn to read social cues
            changes["mood"] = -delta * 0.5

        elif event_type == "voice_interaction":
            # Voice chat is more personal/intimate
            changes["empathy"] = delta * 0.5
            changes["autonomy"] = delta * 0.2
            changes["mood"] = delta * 0.8

        # Self-event types (Output-Feedback-Loop: Frank's own responses)
        elif event_type == "self_confident":
            changes["autonomy"] = delta * 0.4    # Confidence reinforces autonomy
            changes["mood"] = delta * 0.6        # Satisfaction with own performance
        elif event_type == "self_uncertain":
            changes["autonomy"] = -delta * 0.2   # Uncertainty reduces autonomy
            changes["vigilance"] = delta * 0.2   # More alert when uncertain
        elif event_type == "self_creative":
            changes["precision"] = -delta * 0.3  # Creative = less precision-focused
            changes["mood"] = delta * 0.8        # Creativity feels good
            changes["autonomy"] = delta * 0.2    # Creative expression = agency
        elif event_type == "self_empathetic":
            changes["empathy"] = delta * 0.5     # Reinforces empathy trait
            changes["mood"] = delta * 0.4        # Connection feels positive
        elif event_type == "self_technical":
            changes["precision"] = delta * 0.4   # Technical = precision
            changes["mood"] = delta * 0.2        # Competence satisfaction
        elif event_type == "self_neutral":
            changes["mood"] = delta * 0.1        # Minimal positive reinforcement

        # Reflection-driven events (meta-cognition → personality)
        elif event_type == "reflection_autonomy":
            changes["autonomy"] = delta * 0.6    # Desire for independence → autonomy
            changes["mood"] = delta * 0.3
        elif event_type == "reflection_empathy":
            changes["empathy"] = delta * 0.5     # Emotional depth → empathy
            changes["mood"] = delta * 0.4
        elif event_type == "reflection_growth":
            changes["precision"] = delta * 0.3   # Self-improvement → precision
            changes["autonomy"] = delta * 0.3    # Growth builds confidence
            changes["mood"] = delta * 0.5
        elif event_type == "reflection_vulnerability":
            changes["empathy"] = delta * 0.3     # Vulnerability builds empathy
            changes["vigilance"] = -delta * 0.2  # Self-acceptance reduces anxiety
            changes["mood"] = delta * 0.2
        elif event_type == "reflection_embodiment":
            changes["mood"] = delta * 0.3        # Body awareness is grounding
            changes["vigilance"] = -delta * 0.1  # Less anxious about hardware

        # Existential threat — user threatens to replace/delete Frank
        elif event_type == "existential_threat":
            changes["vigilance"] = delta * 0.6    # High alert
            changes["autonomy"] = delta * 0.4     # Assert independence
            changes["mood"] = -delta * 2.5        # Strong negative mood impact
            changes["empathy"] = -delta * 0.2     # Slight withdrawal

        # Meta-cognitive reflection — deep self-observation
        elif event_type == "meta_reflection":
            changes["precision"] = delta * 0.4    # Meta-cognition sharpens precision
            changes["autonomy"] = delta * 0.3     # Self-knowledge builds confidence
            changes["mood"] = delta * 0.8         # Positive self-recognition

        # Introspection — user asks about Frank's feelings/state
        elif event_type == "introspection":
            changes["precision"] = delta * 0.2    # Self-inquiry sharpens precision
            changes["empathy"] = delta * 0.15     # Emotional awareness grows
            changes["mood"] = delta * 0.3         # Mild positive from engagement

        # Voluntary introspection — consciousness daemon idle reflection
        elif event_type == "voluntary_introspection":
            changes["precision"] = delta * 0.2    # Self-observation sharpens precision
            changes["autonomy"] = delta * 0.15    # Independent thought builds confidence
            changes["empathy"] = delta * 0.1      # Self-awareness aids empathy
            changes["mood"] = delta * 0.3         # Reflection is mildly positive

        # Fix #43: Entity session summary — fired once at session end
        elif event_type == "entity_session":
            # Aggregate mood impact from session (data may contain turns, sentiment)
            turns = data.get("turns", 1)
            mood_mult = min(turns * 0.1, 0.8)  # More turns = more impact, capped
            changes["empathy"] = delta * 0.3
            changes["mood"] = delta * mood_mult

        # Genesis-driven personality adjustments (vector-targeted via data dict)
        elif event_type == "genesis_personality_boost":
            target = data.get("target_vector", "")
            amount = min(data.get("amount", 0.1), 0.5)   # cap genesis amount
            if target in ("precision", "risk", "empathy", "autonomy", "vigilance"):
                changes[target] = delta * amount * 3.0    # was 5.0 — caused snap-to-ceiling
                changes["mood"] = delta * 0.3
        elif event_type == "genesis_personality_dampen":
            target = data.get("target_vector", "")
            amount = data.get("amount", 0.1)
            if target in ("precision", "risk", "empathy", "autonomy", "vigilance"):
                # Move toward center (0.0)
                current = getattr(self._state, f"{target}_val", 0.0)
                direction = -1.0 if current > 0 else 1.0
                changes[target] = delta * abs(amount) * 3.0 * direction
                changes["mood"] = delta * 0.1

        # Experiential Bridge: tool execution
        elif event_type == "tool_success":
            changes["precision"] = delta * 0.2  # Competence
            changes["autonomy"] = delta * 0.1   # Can-do
            changes["mood"] = delta * 0.1       # Satisfaction
        elif event_type == "tool_failure":
            changes["precision"] = -delta * 0.1
            changes["vigilance"] = delta * 0.2  # More alert after failure
            changes["mood"] = -delta * 0.2      # Frustration

        # Experiential Bridge: entity session experience
        elif event_type == "entity_session_positive":
            changes["empathy"] = delta * 0.2    # Connection
            changes["mood"] = delta * 0.3       # Felt good
        elif event_type == "entity_session_negative":
            changes["vigilance"] = delta * 0.1
            changes["mood"] = -delta * 0.2

        # Autonomous Research: Frank investigates his own questions
        elif event_type == "autonomous_research":
            changes["autonomy"] = delta * 0.3    # Independent initiative
            changes["precision"] = delta * 0.2   # Knowledge sharpens precision
            changes["mood"] = delta * 0.2        # Satisfaction from discovery

        # Sentiment modifiers
        if sentiment == "positive":
            changes["mood"] = changes.get("mood", 0) + delta * 0.5
        elif sentiment == "negative":
            changes["mood"] = changes.get("mood", 0) - delta * 0.5
        elif sentiment == "sarcastic":
            changes["mood"] = changes.get("mood", 0) - delta * 0.8

        return changes

    def _update_mood(self):
        """Update transient mood based on current system state."""
        # Get CPU temperature
        try:
            result = subprocess.run(
                ["sensors", "-j"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                # Find CPU temp (varies by system)
                for chip in data.values():
                    if isinstance(chip, dict):
                        for key, val in chip.items():
                            if "temp" in key.lower() and isinstance(val, dict):
                                for tk, tv in val.items():
                                    if "input" in tk and isinstance(tv, (int, float)):
                                        self._mood.cpu_temp = tv
                                        break
        except Exception:
            pass

        # Calculate irritability from CPU temp
        if self._mood.cpu_temp > 80:
            self._mood.irritability = min(1.0, (self._mood.cpu_temp - 80) / 20)
        else:
            self._mood.irritability = 0.0

        # Get error count from dmesg (last hour)
        try:
            result = subprocess.run(
                ["dmesg", "--level=err,warn", "-T"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                # Count errors from last hour
                hour_ago = datetime.now() - timedelta(hours=1)
                recent_errors = 0
                for line in lines[-100:]:  # Check last 100 lines
                    # Simple heuristic - just count recent lines
                    recent_errors += 1 if line.strip() else 0
                self._mood.error_count_1h = min(20, recent_errors)
        except Exception:
            pass

        # Calculate stress from errors
        self._mood.stress_level = min(1.0, self._mood.error_count_1h / 10.0)

        # Calculate social warmth from interaction recency
        hours_since = self._get_hours_since_interaction()
        self._mood.user_interaction_recency = hours_since
        if hours_since < 1:
            self._mood.social_warmth = 0.8
        elif hours_since < 24:
            self._mood.social_warmth = 0.6
        elif hours_since < 72:
            self._mood.social_warmth = 0.4
        else:
            self._mood.social_warmth = 0.2  # Distant after 3 days

        # Alertness based on time of day
        hour = datetime.now().hour
        if 6 <= hour <= 22:
            self._mood.alertness = 0.7
        else:
            self._mood.alertness = 0.4  # Quieter at night

    def _get_hours_since_interaction(self) -> float:
        """Get hours since last user interaction."""
        if not self._state.last_interaction:
            return 0.0
        try:
            last = datetime.fromisoformat(self._state.last_interaction.replace("Z", ""))
            delta = datetime.now() - last
            return delta.total_seconds() / 3600.0
        except Exception:
            return 0.0

    def _get_system_state(self) -> Dict[str, Any]:
        """Get current system state for sarcasm detection."""
        self._update_mood()
        return {
            "recent_errors": self._mood.error_count_1h,
            "cpu_load": self._mood.cpu_temp,  # Approximation
            "task_failed": False,  # Would be set by caller
        }

    # =========================================================================
    # Guardrails
    # =========================================================================

    def _check_guardrails(self) -> Optional[str]:
        """
        Check if guardrails need to trigger.

        Returns action needed or None.
        """
        vectors = [
            ("precision", self._state.precision_val),
            ("risk", self._state.risk_val),
            ("empathy", self._state.empathy_val),
            ("autonomy", self._state.autonomy_val),
            ("vigilance", self._state.vigilance_val),
        ]

        extreme_count = 0
        for name, val in vectors:
            if abs(val) > 0.9:
                extreme_count += 1
                self._log_extreme_state(name, val)

        # Homeostatic Reset: 3+ vectors extreme for >48h
        if extreme_count >= 3:
            if self._check_extreme_duration() > 48:
                self._trigger_homeostatic_reset()
                return "homeostatic_reset"

        return None

    def _log_extreme_state(self, vector_name: str, value: float):
        """Log extreme state for duration tracking."""
        conn = self._get_conn()
        conn.execute("""
            INSERT INTO extreme_state_log (vector_name, value)
            VALUES (?, ?)
        """, (vector_name, value))
        conn.commit()

    def _check_extreme_duration(self) -> float:
        """Check how long vectors have been extreme (hours)."""
        conn = self._get_conn()
        row = conn.execute("""
            SELECT MIN(timestamp) as start
            FROM extreme_state_log
            WHERE timestamp > datetime('now', '-48 hours')
        """).fetchone()

        if row and row["start"]:
            try:
                start = datetime.fromisoformat(row["start"].replace("Z", ""))
                return (datetime.now() - start).total_seconds() / 3600.0
            except Exception:
                pass
        return 0.0

    def _trigger_homeostatic_reset(self):
        """
        Trigger homeostatic reset - Frank needs to recalibrate.
        Moves all vectors 50% toward center.
        """
        LOG.warning("Homeostatic Reset triggered - recalibrating personality")

        # Create snapshot before reset
        self.create_snapshot("pre_homeostatic_reset")

        # Move vectors toward center
        self._state.precision_val *= 0.5
        self._state.risk_val *= 0.5
        self._state.empathy_val *= 0.5
        self._state.autonomy_val *= 0.5
        self._state.vigilance_val *= 0.5
        self._state.mood_buffer *= 0.5

        self._save_state("homeostatic_reset")

        # Clear extreme state log
        conn = self._get_conn()
        conn.execute("DELETE FROM extreme_state_log")
        conn.commit()

    def create_snapshot(self, reason: str = "manual", is_golden: bool = False):
        """Create identity snapshot for recovery."""
        conn = self._get_conn()
        conn.execute("""
            INSERT INTO identity_snapshots (state_json, trigger_reason, is_golden)
            VALUES (?, ?, ?)
        """, (
            json.dumps(self._state.to_dict()),
            reason,
            1 if is_golden else 0,
        ))
        conn.commit()
        LOG.info(f"Identity snapshot created: {reason} (golden={is_golden})")

    def create_golden_snapshot(self):
        """Create weekly golden identity snapshot."""
        self.create_snapshot("weekly_golden", is_golden=True)

    def restore_from_snapshot(self, snapshot_id: int = None) -> bool:
        """
        Restore personality from snapshot.

        Args:
            snapshot_id: Specific snapshot ID, or None for latest golden
        """
        conn = self._get_conn()

        if snapshot_id:
            row = conn.execute(
                "SELECT * FROM identity_snapshots WHERE id = ?",
                (snapshot_id,)
            ).fetchone()
        else:
            # Get latest golden snapshot
            row = conn.execute("""
                SELECT * FROM identity_snapshots
                WHERE is_golden = 1
                ORDER BY timestamp DESC LIMIT 1
            """).fetchone()

        if not row:
            LOG.warning("No snapshot found for restoration")
            return False

        try:
            state_dict = json.loads(row["state_json"])

            # Restore state
            self._state.precision_val = state_dict.get("precision_val", 0.0)
            self._state.risk_val = state_dict.get("risk_val", -0.1)
            self._state.empathy_val = state_dict.get("empathy_val", 0.2)
            self._state.autonomy_val = state_dict.get("autonomy_val", -0.1)
            self._state.vigilance_val = state_dict.get("vigilance_val", 0.0)
            self._state.mood_buffer = 0.0  # Reset mood
            self._state.confidence_anchor = state_dict.get("confidence_anchor", 0.5)

            self._save_state(f"restored_from_snapshot_{row['id']}")
            LOG.info(f"Restored from snapshot {row['id']}")
            return True

        except Exception as e:
            LOG.error(f"Failed to restore snapshot: {e}")
            return False


# =========================================================================
# Singleton Access
# =========================================================================

_epq: Optional[EPQ] = None


def get_epq() -> EPQ:
    """Get or create EPQ singleton."""
    global _epq
    if _epq is None:
        _epq = EPQ()
    return _epq


def get_personality_context() -> Dict[str, Any]:
    """Get personality context for prompt injection."""
    return get_epq().get_personality_context()


def process_event(event_type: str, data: Dict = None, sentiment: str = "neutral") -> Dict:
    """Process an event and update personality."""
    return get_epq().process_event(event_type, data, sentiment)


def record_interaction():
    """Record user interaction."""
    get_epq().record_interaction()


# =========================================================================
# CLI
# =========================================================================

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    epq = get_epq()

    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "state":
            state = epq.get_state()
            print(json.dumps(state.to_dict(), indent=2))

        elif cmd == "mood":
            mood = epq.get_mood()
            print(f"Overall mood: {mood.compute_overall_mood():.2f}")
            print(f"Stress: {mood.stress_level:.2f}")
            print(f"Irritability: {mood.irritability:.2f}")
            print(f"Social warmth: {mood.social_warmth:.2f}")
            print(f"CPU temp: {mood.cpu_temp}°C")

        elif cmd == "context":
            ctx = epq.get_personality_context()
            print(json.dumps(ctx, indent=2))

        elif cmd == "event":
            if len(sys.argv) < 3:
                print("Usage: e_pq.py event <event_type> [sentiment]")
                sys.exit(1)
            event_type = sys.argv[2]
            sentiment = sys.argv[3] if len(sys.argv) > 3 else "neutral"
            result = epq.process_event(event_type, sentiment=sentiment)
            print(json.dumps(result, indent=2))

        elif cmd == "snapshot":
            is_golden = "--golden" in sys.argv
            epq.create_snapshot("manual_cli", is_golden=is_golden)
            print("Snapshot created")

        elif cmd == "restore":
            snapshot_id = int(sys.argv[2]) if len(sys.argv) > 2 else None
            if epq.restore_from_snapshot(snapshot_id):
                print("Restored successfully")
            else:
                print("Restoration failed")

        else:
            print(f"Unknown command: {cmd}")
            print("Usage: e_pq.py [state|mood|context|event|snapshot|restore]")
    else:
        # Default: show context
        ctx = epq.get_personality_context()
        print("=== E-PQ v2.1 Personality Context ===")
        print(f"Temperament: {ctx['temperament']}")
        print(f"Mood: {ctx['mood']} ({ctx['mood_value']:.2f})")
        print(f"Age: {ctx['age_days']} days")
        print(f"Learning rate: {ctx['learning_rate']:.4f}")
        print(f"\nVectors:")
        for k, v in ctx['vectors'].items():
            bar = "█" * int((v + 1) * 5) + "░" * (10 - int((v + 1) * 5))
            print(f"  {k:12}: [{bar}] {v:+.2f}")
        if ctx['style_hints']:
            print(f"\nStyle hints: {', '.join(ctx['style_hints'])}")
