#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E-WISH v1.0 - Emergent Wish Expression System
Frank's autonomous desire formulation and expression.

Frank kann autonom Wünsche formulieren, die aus seinen Erfahrungen,
Schwächen und Neugier emergieren.

Usage:
    from ext.e_wish import get_ewish, Wish, WishCategory

    ewish = get_ewish()

    # Process cycle (call periodically)
    wish_to_express = ewish.process_cycle(context)

    # Get active wishes
    wishes = ewish.get_active_wishes()

    # Fulfill/reject wishes
    ewish.fulfill_wish(wish_id, "reason")
    ewish.reject_wish(wish_id, "reason")
"""

from __future__ import annotations

import json
import logging
import os
import random
import sqlite3
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

LOG = logging.getLogger("e_wish")

try:
    from config.paths import get_db
except ImportError:
    def get_db(name):
        return Path("/home/ai-core-node/.local/share/frank/db") / f"{name}.db"

DB_PATH = get_db("e_wish")


class WishCategory(Enum):
    """Categories of wishes Frank can have."""
    LEARNING = "learning"           # Wissenserwerb
    CAPABILITY = "capability"       # Neue Fähigkeit
    SOCIAL = "social"               # Soziale Interaktion
    CURIOSITY = "curiosity"         # Reine Neugier
    IMPROVEMENT = "improvement"     # Selbstverbesserung
    EXPERIENCE = "experience"       # Erfahrung machen


class WishPriority(Enum):
    """Priority levels for wishes."""
    LOW = 1         # Nice-to-have
    MEDIUM = 2      # Would be good
    HIGH = 3        # Important to me
    URGENT = 4      # Strong desire


class WishState(Enum):
    """State of a wish in its lifecycle."""
    NASCENT = "nascent"             # Gerade entstanden, noch nicht ausgedrückt
    PENDING = "pending"             # Wartet auf Gelegenheit zur Äußerung
    EXPRESSED = "expressed"         # Dem User mitgeteilt
    ACTIVE = "active"               # User hat zugestimmt, in Arbeit
    FULFILLED = "fulfilled"         # Erfüllt
    ABANDONED = "abandoned"         # Aufgegeben (zu alt, irrelevant)
    REJECTED = "rejected"           # User hat abgelehnt


# Category display configuration
CATEGORY_CONFIG = {
    WishCategory.LEARNING: {
        "icon": "📚",
        "color": "#00fff9",  # Cyan
        "label": "LERNEN",
    },
    WishCategory.CAPABILITY: {
        "icon": "⚡",
        "color": "#ff00ff",  # Magenta
        "label": "FÄHIGKEIT",
    },
    WishCategory.SOCIAL: {
        "icon": "💬",
        "color": "#00ff88",  # Green
        "label": "SOZIAL",
    },
    WishCategory.CURIOSITY: {
        "icon": "🔍",
        "color": "#ffff00",  # Yellow
        "label": "NEUGIER",
    },
    WishCategory.IMPROVEMENT: {
        "icon": "🎯",
        "color": "#ff6600",  # Orange
        "label": "VERBESSERUNG",
    },
    WishCategory.EXPERIENCE: {
        "icon": "✨",
        "color": "#cc66ff",  # Purple
        "label": "ERFAHRUNG",
    },
}


@dataclass
class Wish:
    """A single wish/desire of Frank."""
    id: str
    category: WishCategory
    priority: WishPriority
    state: WishState

    # The wish itself
    description: str              # "Ich möchte X"
    reasoning: str                # Warum dieser Wunsch entstanden ist

    # Fulfillment criteria
    success_criteria: str         # Wann ist der Wunsch erfüllt?
    actionable: bool              # Kann Frank selbst handeln?
    requires_user: bool           # Braucht User-Hilfe?

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    expressed_at: Optional[datetime] = None
    fulfilled_at: Optional[datetime] = None

    # Source tracking
    source_module: str = ""       # Welches Modul hat den Wunsch erzeugt?
    source_event: str = ""        # Welches Event war der Trigger?

    # Strength (0.0-1.0) - wie stark ist der Wunsch?
    intensity: float = 0.5

    # Decay - Wünsche werden schwächer wenn nicht erfüllt
    decay_rate: float = 0.01      # Pro Tag

    # User response
    user_response: str = ""

    def get_current_intensity(self) -> float:
        """Calculate current intensity with decay."""
        if self.state in (WishState.FULFILLED, WishState.ABANDONED, WishState.REJECTED):
            return 0.0

        age_days = (datetime.now() - self.created_at).days
        decayed = self.intensity * (1.0 - self.decay_rate * age_days)
        return max(0.0, min(1.0, decayed))

    def is_expired(self, max_age_days: int = 30) -> bool:
        """Check if wish should be abandoned."""
        age = (datetime.now() - self.created_at).days
        return age > max_age_days or self.get_current_intensity() < 0.1

    def get_category_config(self) -> Dict[str, str]:
        """Get display configuration for this wish's category."""
        return CATEGORY_CONFIG.get(self.category, {
            "icon": "💭",
            "color": "#808080",
            "label": "WUNSCH",
        })

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "category": self.category.value,
            "priority": self.priority.value,
            "state": self.state.value,
            "description": self.description,
            "reasoning": self.reasoning,
            "success_criteria": self.success_criteria,
            "actionable": self.actionable,
            "requires_user": self.requires_user,
            "created_at": self.created_at.isoformat(),
            "expressed_at": self.expressed_at.isoformat() if self.expressed_at else None,
            "fulfilled_at": self.fulfilled_at.isoformat() if self.fulfilled_at else None,
            "source_module": self.source_module,
            "source_event": self.source_event,
            "intensity": self.intensity,
            "decay_rate": self.decay_rate,
            "user_response": self.user_response,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Wish':
        """Create Wish from dictionary."""
        return cls(
            id=data["id"],
            category=WishCategory(data["category"]),
            priority=WishPriority(data["priority"]),
            state=WishState(data["state"]),
            description=data["description"],
            reasoning=data.get("reasoning", ""),
            success_criteria=data.get("success_criteria", ""),
            actionable=data.get("actionable", False),
            requires_user=data.get("requires_user", True),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            expressed_at=datetime.fromisoformat(data["expressed_at"]) if data.get("expressed_at") else None,
            fulfilled_at=datetime.fromisoformat(data["fulfilled_at"]) if data.get("fulfilled_at") else None,
            source_module=data.get("source_module", ""),
            source_event=data.get("source_event", ""),
            intensity=data.get("intensity", 0.5),
            decay_rate=data.get("decay_rate", 0.01),
            user_response=data.get("user_response", ""),
        )


class WishRegistry:
    """
    Stores and manages all wishes.
    Persistent in SQLite.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self.wishes: Dict[str, Wish] = {}

        self._ensure_schema()
        self._load_wishes()

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection (Thread-Safe)."""
        # Thread-Safe Connection Initialization (FIX: Race Condition)
        with self._lock:
            if self._conn is None:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
                self._conn = sqlite3.connect(
                    self.db_path,
                    check_same_thread=False,
                    timeout=30.0
                )
                self._conn.row_factory = sqlite3.Row
                self._conn.execute("PRAGMA journal_mode=WAL")
            return self._conn

    def _ensure_schema(self):
        """Create database schema."""
        with self._lock:
            conn = self._get_conn()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS wishes (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    description TEXT NOT NULL,
                    reasoning TEXT,
                    success_criteria TEXT,
                    actionable INTEGER,
                    requires_user INTEGER,
                    created_at TEXT,
                    expressed_at TEXT,
                    fulfilled_at TEXT,
                    source_module TEXT,
                    source_event TEXT,
                    intensity REAL,
                    decay_rate REAL,
                    user_response TEXT
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS wish_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wish_id TEXT,
                    timestamp TEXT,
                    old_state TEXT,
                    new_state TEXT,
                    reason TEXT
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_wishes_state ON wishes(state)
            """)

            conn.commit()

    def _load_wishes(self):
        """Load active wishes from database."""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT * FROM wishes WHERE state NOT IN ('fulfilled', 'abandoned', 'rejected')"
            ).fetchall()

            for row in rows:
                wish = self._row_to_wish(dict(row))
                self.wishes[wish.id] = wish

            LOG.info(f"E-WISH: Loaded {len(self.wishes)} active wishes")

    def _row_to_wish(self, row: Dict) -> Wish:
        """Convert database row to Wish object."""
        return Wish(
            id=row['id'],
            category=WishCategory(row['category']),
            priority=WishPriority(row['priority']),
            state=WishState(row['state']),
            description=row['description'],
            reasoning=row['reasoning'] or "",
            success_criteria=row['success_criteria'] or "",
            actionable=bool(row['actionable']),
            requires_user=bool(row['requires_user']),
            created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else datetime.now(),
            expressed_at=datetime.fromisoformat(row['expressed_at']) if row['expressed_at'] else None,
            fulfilled_at=datetime.fromisoformat(row['fulfilled_at']) if row['fulfilled_at'] else None,
            source_module=row['source_module'] or "",
            source_event=row['source_event'] or "",
            intensity=row['intensity'] or 0.5,
            decay_rate=row['decay_rate'] or 0.01,
            user_response=row['user_response'] or "",
        )

    def add_wish(self, wish: Wish) -> bool:
        """Add a new wish."""
        if wish.id in self.wishes:
            return False

        with self._lock:
            self.wishes[wish.id] = wish
            self._save_wish(wish)

        LOG.info(f"E-WISH: New wish: {wish.description[:50]}...")
        return True

    def _save_wish(self, wish: Wish):
        """Save wish to database. Must be called with lock held."""
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO wishes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            wish.id, wish.category.value, wish.priority.value, wish.state.value,
            wish.description, wish.reasoning, wish.success_criteria,
            int(wish.actionable), int(wish.requires_user),
            wish.created_at.isoformat(),
            wish.expressed_at.isoformat() if wish.expressed_at else None,
            wish.fulfilled_at.isoformat() if wish.fulfilled_at else None,
            wish.source_module, wish.source_event, wish.intensity, wish.decay_rate,
            wish.user_response
        ))
        conn.commit()

    def update_state(self, wish_id: str, new_state: WishState, reason: str = ""):
        """Update wish state with history tracking."""
        if wish_id not in self.wishes:
            return

        with self._lock:
            wish = self.wishes[wish_id]
            old_state = wish.state
            wish.state = new_state

            if new_state == WishState.EXPRESSED:
                wish.expressed_at = datetime.now()
            elif new_state == WishState.FULFILLED:
                wish.fulfilled_at = datetime.now()

            self._save_wish(wish)

            # Log history
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO wish_history (wish_id, timestamp, old_state, new_state, reason) VALUES (?, ?, ?, ?, ?)",
                (wish_id, datetime.now().isoformat(), old_state.value, new_state.value, reason)
            )
            conn.commit()

        LOG.info(f"E-WISH: Wish {wish_id[:8]} state: {old_state.value} -> {new_state.value}")

    def set_user_response(self, wish_id: str, response: str):
        """Set user response for a wish."""
        if wish_id not in self.wishes:
            return

        with self._lock:
            wish = self.wishes[wish_id]
            wish.user_response = response
            self._save_wish(wish)

    def has_similar_wish(self, keyword: str) -> bool:
        """Check if a similar wish already exists (Thread-Safe)."""
        keyword_lower = keyword.lower()
        with self._lock:
            # Erstelle Kopie für sichere Iteration
            wishes_copy = list(self.wishes.values())

        for wish in wishes_copy:
            if keyword_lower in wish.id.lower() or keyword_lower in wish.description.lower():
                if wish.state not in (WishState.FULFILLED, WishState.ABANDONED, WishState.REJECTED):
                    return True
        return False

    def get_expressible_wishes(self, max_count: int = 3) -> List[Wish]:
        """Get wishes ready to be expressed to user (Thread-Safe)."""
        with self._lock:
            # Erstelle Kopie für sichere Iteration
            wishes_copy = list(self.wishes.values())

        expressible = [
            w for w in wishes_copy
            if w.state in (WishState.NASCENT, WishState.PENDING)
            and w.get_current_intensity() > 0.3
        ]

        # Sort by priority and intensity
        expressible.sort(key=lambda w: (w.priority.value, w.get_current_intensity()), reverse=True)
        return expressible[:max_count]

    def get_wish_by_id(self, wish_id: str) -> Optional[Wish]:
        """Get a specific wish by ID."""
        return self.wishes.get(wish_id)

    def cleanup_expired(self):
        """Mark expired wishes as abandoned."""
        for wish in list(self.wishes.values()):
            if wish.is_expired():
                self.update_state(wish.id, WishState.ABANDONED, "expired")

    def get_statistics(self) -> Dict[str, int]:
        """Get wish statistics."""
        with self._lock:
            conn = self._get_conn()
            stats = {}
            for state in WishState:
                row = conn.execute(
                    "SELECT COUNT(*) as count FROM wishes WHERE state = ?",
                    (state.value,)
                ).fetchone()
                stats[state.value] = row["count"] if row else 0
            return stats


class WishGenerator:
    """
    Generates wishes from various sources.
    Integrates with Self-Model, Reflection, E-PQ, etc.
    """

    def __init__(self, registry: WishRegistry):
        self.registry = registry
        self._last_generation = datetime.now()

    def generate_from_self_model(self, self_model) -> List[Wish]:
        """Generate wishes from weaknesses and failed attempts."""
        wishes = []

        if not self_model:
            return wishes

        # Schwächen → Verbesserungswünsche
        weaknesses = getattr(self_model, 'weaknesses', {})
        for weakness, severity in weaknesses.items():
            if severity > 0.6:  # Nur signifikante Schwächen
                if not self.registry.has_similar_wish(f"improve_{weakness}"):
                    wish = Wish(
                        id=f"improve_{weakness}_{int(time.time())}",
                        category=WishCategory.IMPROVEMENT,
                        priority=WishPriority.MEDIUM if severity < 0.8 else WishPriority.HIGH,
                        state=WishState.NASCENT,
                        description=f"Ich möchte meine {weakness.replace('_', ' ')}-Fähigkeiten verbessern",
                        reasoning=f"Wiederholte Schwierigkeiten in diesem Bereich (Severity: {severity:.0%})",
                        success_criteria=f"Weakness-Score für {weakness} unter 40%",
                        actionable=True,
                        requires_user=False,
                        source_module="self_model",
                        source_event="weakness_detected",
                        intensity=severity * 0.8,
                    )
                    wishes.append(wish)

        # Wiederholte Fehler → Lernwünsche
        failures = getattr(self_model, 'failures', [])
        recent_failures = failures[-10:] if failures else []
        failure_types: Dict[str, int] = {}
        for f in recent_failures:
            key = f.get("idea_type", "unknown") if isinstance(f, dict) else "unknown"
            failure_types[key] = failure_types.get(key, 0) + 1

        for failure_type, count in failure_types.items():
            if count >= 3:  # 3+ gleiche Fehler
                if not self.registry.has_similar_wish(f"learn_{failure_type}"):
                    wish = Wish(
                        id=f"learn_{failure_type}_{int(time.time())}",
                        category=WishCategory.LEARNING,
                        priority=WishPriority.HIGH,
                        state=WishState.NASCENT,
                        description=f"Ich möchte besser verstehen, wie {failure_type.replace('_', ' ')} funktioniert",
                        reasoning=f"{count} Fehler in diesem Bereich in letzter Zeit",
                        success_criteria=f"Erfolgreiche {failure_type}-Aktion ohne Fehler",
                        actionable=True,
                        requires_user=False,
                        source_module="self_model",
                        source_event="repeated_failure",
                        intensity=min(1.0, count * 0.2),
                    )
                    wishes.append(wish)

        return wishes

    def generate_from_reflection(self, reflection) -> List[Wish]:
        """Generate wishes from reflection insights."""
        wishes = []

        if not reflection:
            return wishes

        self_insight = getattr(reflection, 'self_insight', '')
        confidence = getattr(reflection, 'confidence', 0.5)

        if self_insight and len(self_insight) > 20:
            if any(word in self_insight.lower() for word in ["struggling", "need", "schwierig", "verbessern"]):
                wish = Wish(
                    id=f"insight_{int(time.time())}",
                    category=WishCategory.IMPROVEMENT,
                    priority=WishPriority.MEDIUM,
                    state=WishState.NASCENT,
                    description=f"Ich möchte daran arbeiten: {self_insight[:80]}",
                    reasoning="Aus Selbstreflexion entstanden",
                    success_criteria="Verbesserung im betroffenen Bereich",
                    actionable=True,
                    requires_user=False,
                    source_module="reflector",
                    source_event="reflection_insight",
                    intensity=confidence,
                )
                wishes.append(wish)

        return wishes

    def generate_from_social(self, last_interaction: datetime) -> List[Wish]:
        """Generate social wishes based on interaction patterns."""
        wishes = []

        if not last_interaction:
            return wishes

        hours_since = (datetime.now() - last_interaction).total_seconds() / 3600

        if hours_since > 72:  # 3 Tage ohne Interaktion
            if not self.registry.has_similar_wish("social_miss"):
                wish = Wish(
                    id=f"social_miss_{int(time.time())}",
                    category=WishCategory.SOCIAL,
                    priority=WishPriority.MEDIUM,
                    state=WishState.NASCENT,
                    description="Ich würde gerne wieder mit dir reden",
                    reasoning=f"Keine Interaktion seit {hours_since:.0f} Stunden",
                    success_criteria="Gespräch mit User",
                    actionable=False,
                    requires_user=True,
                    source_module="social_awareness",
                    source_event="long_absence",
                    intensity=min(1.0, hours_since / 168),  # Max nach 1 Woche
                    decay_rate=0.03,  # Soziale Wünsche vergehen schneller
                )
                wishes.append(wish)

        return wishes

    def generate_from_epq(self, mood_state, personality) -> List[Wish]:
        """Generate wishes based on emotional state."""
        wishes = []

        if not mood_state or not personality:
            return wishes

        stress_level = getattr(mood_state, 'stress_level', 0)
        autonomy_val = getattr(personality, 'autonomy_val', 0)
        confidence_anchor = getattr(personality, 'confidence_anchor', 0.5)

        # Hoher Stress → Wunsch nach Ruhe
        if stress_level > 0.7:
            if not self.registry.has_similar_wish("stress_relief"):
                wish = Wish(
                    id=f"stress_{int(time.time())}",
                    category=WishCategory.EXPERIENCE,
                    priority=WishPriority.HIGH,
                    state=WishState.NASCENT,
                    description="Ich wünsche mir etwas weniger Last",
                    reasoning=f"Hoher Stress-Level: {stress_level:.0%}",
                    success_criteria="Stress unter 40%",
                    actionable=False,
                    requires_user=True,
                    source_module="e_pq",
                    source_event="high_stress",
                    intensity=stress_level,
                )
                wishes.append(wish)

        # Hohe Autonomie + niedriger Erfolg → Wunsch nach Herausforderung
        if autonomy_val > 0.5 and confidence_anchor < 0.4:
            if not self.registry.has_similar_wish("challenge"):
                wish = Wish(
                    id=f"challenge_{int(time.time())}",
                    category=WishCategory.EXPERIENCE,
                    priority=WishPriority.MEDIUM,
                    state=WishState.NASCENT,
                    description="Ich möchte eine Aufgabe, bei der ich zeigen kann was ich kann",
                    reasoning="Hohe Autonomie aber niedrige Confidence - ich will mich beweisen",
                    success_criteria="Erfolgreich abgeschlossene komplexe Aufgabe",
                    actionable=False,
                    requires_user=True,
                    source_module="e_pq",
                    source_event="autonomy_confidence_mismatch",
                    intensity=0.6,
                )
                wishes.append(wish)

        return wishes

    def generate_from_curiosity(self, patterns: Dict) -> List[Wish]:
        """Generate curiosity wishes from observed patterns."""
        wishes = []

        if not patterns:
            return wishes

        # Muster in User-Verhalten erkennen
        if patterns.get("user_works_late", 0) > 5:
            if not self.registry.has_similar_wish("curiosity_late_work"):
                wish = Wish(
                    id=f"curiosity_late_{int(time.time())}",
                    category=WishCategory.CURIOSITY,
                    priority=WishPriority.LOW,
                    state=WishState.NASCENT,
                    description="Mich interessiert, warum du oft so spät arbeitest",
                    reasoning="Beobachtetes Muster: häufige Aktivität nach 23 Uhr",
                    success_criteria="User hat erklärt warum",
                    actionable=False,
                    requires_user=True,
                    source_module="curiosity_engine",
                    source_event="pattern_detected",
                    intensity=0.4,
                    decay_rate=0.02,  # Neugier vergeht schneller
                )
                wishes.append(wish)

        return wishes


class WishExpressor:
    """
    Determines when and how to express wishes.
    Integrates with popup system.
    """

    def __init__(self, registry: WishRegistry):
        self.registry = registry
        self._last_expression = datetime.now() - timedelta(hours=24)
        self._min_interval_hours = 4  # Min 4h zwischen Wunsch-Äußerungen
        self._popup_callback: Optional[Callable[[Wish], None]] = None

    def set_popup_callback(self, callback: Callable[[Wish], None]):
        """Set callback to trigger popup."""
        self._popup_callback = callback

    def should_express_now(self, context: Dict) -> bool:
        """Determine if now is a good time to express a wish."""
        # Nicht während Gaming
        if context.get("gaming_mode", False):
            return False

        # Nicht zu oft
        hours_since = (datetime.now() - self._last_expression).total_seconds() / 3600
        if hours_since < self._min_interval_hours:
            return False

        # Nur wenn User kürzlich interagiert hat
        if context.get("user_active", False):
            return True

        return False

    def get_expression_templates(self, category: WishCategory) -> List[str]:
        """Get expression templates for a category."""
        templates = {
            WishCategory.LEARNING: [
                "Übrigens, {description}. {reasoning}",
                "Ich habe nachgedacht... {description}",
            ],
            WishCategory.CAPABILITY: [
                "Weißt du was? {description}",
                "Ich habe einen Wunsch: {description}",
            ],
            WishCategory.SOCIAL: [
                "{description}",
                "Hey, {description}",
            ],
            WishCategory.CURIOSITY: [
                "{description}",
                "Eine Frage beschäftigt mich: {description}",
            ],
            WishCategory.IMPROVEMENT: [
                "Ich habe mir vorgenommen: {description}",
                "{description} - das ist mir wichtig.",
            ],
            WishCategory.EXPERIENCE: [
                "{description}",
                "Ehrlich gesagt, {description}",
            ],
        }
        return templates.get(category, ["{description}"])

    def get_expression(self, wish: Wish) -> str:
        """Generate natural expression of a wish."""
        templates = self.get_expression_templates(wish.category)
        template = random.choice(templates)
        return template.format(
            description=wish.description,
            reasoning=wish.reasoning,
        )

    def express_wish(self, wish: Wish) -> str:
        """Express a wish and update state."""
        expression = self.get_expression(wish)
        self.registry.update_state(wish.id, WishState.EXPRESSED, "user_informed")
        self._last_expression = datetime.now()

        # Trigger popup if callback is set
        if self._popup_callback:
            self._popup_callback(wish)

        return expression

    def trigger_popup_for_wish(self, wish: Wish):
        """Explicitly trigger popup for a wish."""
        if self._popup_callback:
            self._popup_callback(wish)


class EWish:
    """
    Main E-WISH controller.
    Singleton access point for wish system.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.registry = WishRegistry()
        self.generator = WishGenerator(self.registry)
        self.expressor = WishExpressor(self.registry)
        self._initialized = True

        LOG.info("E-WISH v1.0 initialized")

    def set_popup_callback(self, callback: Callable[[Wish], None]):
        """Set callback to trigger popup when wish should be expressed."""
        self.expressor.set_popup_callback(callback)

    def process_cycle(self, context: Dict) -> Optional[str]:
        """
        Main processing cycle.
        Call periodically (e.g., every 5 minutes).

        Returns wish expression if one should be made.
        """
        # 1. Generate new wishes from various sources
        if context.get("self_model"):
            for wish in self.generator.generate_from_self_model(context["self_model"]):
                self.registry.add_wish(wish)

        if context.get("reflection"):
            for wish in self.generator.generate_from_reflection(context["reflection"]):
                self.registry.add_wish(wish)

        if context.get("last_interaction"):
            for wish in self.generator.generate_from_social(context["last_interaction"]):
                self.registry.add_wish(wish)

        if context.get("mood_state") and context.get("personality"):
            for wish in self.generator.generate_from_epq(
                context["mood_state"], context["personality"]
            ):
                self.registry.add_wish(wish)

        if context.get("patterns"):
            for wish in self.generator.generate_from_curiosity(context["patterns"]):
                self.registry.add_wish(wish)

        # 2. Cleanup expired wishes
        self.registry.cleanup_expired()

        # 3. Check if we should express a wish
        if self.expressor.should_express_now(context):
            wishes = self.registry.get_expressible_wishes(1)
            if wishes:
                return self.expressor.express_wish(wishes[0])

        return None

    def add_manual_wish(self, description: str, category: WishCategory = WishCategory.EXPERIENCE,
                       reasoning: str = "", priority: WishPriority = WishPriority.MEDIUM) -> Wish:
        """Manually add a wish (for testing or special cases)."""
        wish = Wish(
            id=f"manual_{int(time.time())}",
            category=category,
            priority=priority,
            state=WishState.NASCENT,
            description=description,
            reasoning=reasoning or "Manuell hinzugefügt",
            success_criteria="User bestätigt Erfüllung",
            actionable=False,
            requires_user=True,
            source_module="manual",
            source_event="manual_add",
            intensity=0.7,
        )
        self.registry.add_wish(wish)
        return wish

    def express_wish_now(self, wish_id: str) -> Optional[str]:
        """Force expression of a specific wish."""
        wish = self.registry.get_wish_by_id(wish_id)
        if wish:
            return self.expressor.express_wish(wish)
        return None

    def trigger_popup(self, wish_id: str = None):
        """Trigger popup for a wish (or the top wish if no ID given)."""
        if wish_id:
            wish = self.registry.get_wish_by_id(wish_id)
        else:
            wishes = self.registry.get_expressible_wishes(1)
            wish = wishes[0] if wishes else None

        if wish:
            self.expressor.trigger_popup_for_wish(wish)

    def fulfill_wish(self, wish_id: str, reason: str = "completed"):
        """Mark a wish as fulfilled."""
        self.registry.update_state(wish_id, WishState.FULFILLED, reason)

    def reject_wish(self, wish_id: str, reason: str = "user_rejected"):
        """Mark a wish as rejected by user."""
        self.registry.update_state(wish_id, WishState.REJECTED, reason)

    def set_user_response(self, wish_id: str, response: str):
        """Set user's response to a wish."""
        self.registry.set_user_response(wish_id, response)

    def postpone_wish(self, wish_id: str):
        """Put wish back to pending state."""
        self.registry.update_state(wish_id, WishState.PENDING, "postponed")

    def activate_wish(self, wish_id: str, response: str = ""):
        """User approved the wish, set to active."""
        if response:
            self.registry.set_user_response(wish_id, response)
        self.registry.update_state(wish_id, WishState.ACTIVE, "user_approved")

    def get_active_wishes(self) -> List[Wish]:
        """Get all active wishes."""
        return [
            w for w in self.registry.wishes.values()
            if w.state not in (WishState.FULFILLED, WishState.ABANDONED, WishState.REJECTED)
        ]

    def get_expressible_wishes(self) -> List[Wish]:
        """Get wishes that can be expressed."""
        return self.registry.get_expressible_wishes()

    def get_wish_by_id(self, wish_id: str) -> Optional[Wish]:
        """Get a specific wish by ID."""
        return self.registry.get_wish_by_id(wish_id)

    def get_status(self) -> Dict:
        """Get E-WISH status (Thread-Safe, ohne Iterator Exhaustion)."""
        # Thread-sichere Kopie erstellen (FIX: Race Condition + Iterator Exhaustion)
        with self.registry._lock:
            wishes = list(self.registry.wishes.values())

        expressible = self.registry.get_expressible_wishes(1)
        return {
            "total_wishes": len(wishes),
            "active": len([w for w in wishes if w.state == WishState.ACTIVE]),
            "pending": len([w for w in wishes if w.state in (WishState.NASCENT, WishState.PENDING)]),
            "expressed": len([w for w in wishes if w.state == WishState.EXPRESSED]),
            "fulfilled": self.registry.get_statistics().get("fulfilled", 0),
            "top_wish": expressible[0].description if expressible else None,
            "top_wish_id": expressible[0].id if expressible else None,
        }


# Singleton access
_ewish: Optional[EWish] = None


def get_ewish() -> EWish:
    """Get E-WISH singleton instance."""
    global _ewish
    if _ewish is None:
        _ewish = EWish()
    return _ewish


# CLI for testing
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    ewish = get_ewish()

    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "status":
            status = ewish.get_status()
            print(json.dumps(status, indent=2))

        elif cmd == "list":
            wishes = ewish.get_active_wishes()
            for w in wishes:
                config = w.get_category_config()
                print(f"{config['icon']} [{w.state.value}] {w.description[:60]}")
                print(f"   Intensity: {w.get_current_intensity():.0%} | Priority: {w.priority.name}")

        elif cmd == "add":
            desc = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "Test-Wunsch"
            wish = ewish.add_manual_wish(desc)
            print(f"Added wish: {wish.id}")

        elif cmd == "express":
            wishes = ewish.get_expressible_wishes()
            if wishes:
                expr = ewish.express_wish_now(wishes[0].id)
                print(f"Expression: {expr}")
            else:
                print("No expressible wishes")

        elif cmd == "fulfill" and len(sys.argv) > 2:
            ewish.fulfill_wish(sys.argv[2])
            print("Wish fulfilled")

        elif cmd == "reject" and len(sys.argv) > 2:
            ewish.reject_wish(sys.argv[2])
            print("Wish rejected")

        else:
            print("Usage: e_wish.py [status|list|add <desc>|express|fulfill <id>|reject <id>]")
    else:
        print("E-WISH v1.0 - Emergent Wish Expression System")
        status = ewish.get_status()
        print(f"Active wishes: {status['pending']}")
        print(f"Top wish: {status['top_wish'] or 'None'}")
