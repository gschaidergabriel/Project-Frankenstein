#!/usr/bin/env python3
"""
Pattern Memory - Remembers patterns for anticipation
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import sqlite3
import logging

from ..config import get_config

LOG = logging.getLogger("genesis.patterns")


@dataclass
class Pattern:
    """A recognized pattern."""
    id: str
    pattern_type: str  # "temporal", "causal", "behavioral"
    description: str
    conditions: Dict  # When does this pattern apply?
    prediction: str  # What does it predict?
    confidence: float  # How confident are we?
    occurrences: int  # How many times observed?
    last_seen: datetime
    success_rate: float = 0.5  # How often was the prediction correct?


class PatternMemory:
    """
    Stores and retrieves patterns for anticipation.
    This enables Frank to predict future needs.
    """

    def __init__(self):
        self.config = get_config()
        self.patterns: Dict[str, Pattern] = {}

        # Temporal patterns (time-based)
        self.temporal_observations: List[Dict] = []

        # Causal patterns (event → consequence)
        self.causal_observations: List[Dict] = []

        # Load from database
        self._load_patterns()

    def record_observation(self, observation_type: str, context: Dict,
                          outcome: Optional[str] = None):
        """Record an observation for pattern detection."""
        obs = {
            "timestamp": datetime.now(),
            "type": observation_type,
            "context": context,
            "outcome": outcome,
            "hour": datetime.now().hour,
            "weekday": datetime.now().weekday(),
        }

        if observation_type == "temporal":
            self.temporal_observations.append(obs)
            # Trim
            if len(self.temporal_observations) > 1000:
                self.temporal_observations = self.temporal_observations[-500:]
        else:
            self.causal_observations.append(obs)
            if len(self.causal_observations) > 1000:
                self.causal_observations = self.causal_observations[-500:]

        # Try to detect patterns
        self._detect_patterns()

    def _detect_patterns(self):
        """Detect patterns from observations."""
        # Detect temporal patterns
        self._detect_temporal_patterns()

        # Detect causal patterns
        self._detect_causal_patterns()

    def _detect_temporal_patterns(self):
        """Detect time-based patterns."""
        if len(self.temporal_observations) < 10:
            return

        # Group by hour and type
        hour_type_counts = defaultdict(lambda: defaultdict(int))
        for obs in self.temporal_observations[-100:]:
            hour = obs["hour"]
            obs_type = obs["context"].get("activity_type", "unknown")
            hour_type_counts[hour][obs_type] += 1

        # Find significant patterns
        for hour, types in hour_type_counts.items():
            total = sum(types.values())
            for activity, count in types.items():
                if count >= 5 and count / total > 0.3:
                    # Significant pattern found
                    pattern_id = f"temporal_{hour}_{activity}"
                    if pattern_id not in self.patterns:
                        self.patterns[pattern_id] = Pattern(
                            id=pattern_id,
                            pattern_type="temporal",
                            description=f"At hour {hour}, activity '{activity}' is common",
                            conditions={"hour": hour},
                            prediction=activity,
                            confidence=count / total,
                            occurrences=count,
                            last_seen=datetime.now(),
                        )
                    else:
                        # Update existing
                        self.patterns[pattern_id].occurrences = count
                        self.patterns[pattern_id].confidence = count / total
                        self.patterns[pattern_id].last_seen = datetime.now()

    def _detect_causal_patterns(self):
        """Detect event → consequence patterns."""
        if len(self.causal_observations) < 10:
            return

        # Look for sequences
        sequences = defaultdict(int)
        obs_list = self.causal_observations[-100:]

        for i in range(len(obs_list) - 1):
            curr = obs_list[i]
            next_obs = obs_list[i + 1]

            # If close in time, might be related
            time_diff = (next_obs["timestamp"] - curr["timestamp"]).total_seconds()
            if time_diff < 300:  # Within 5 minutes
                curr_type = curr["context"].get("event_type", "unknown")
                next_type = next_obs["context"].get("event_type", "unknown")
                seq_key = f"{curr_type}→{next_type}"
                sequences[seq_key] += 1

        # Find significant sequences
        for seq, count in sequences.items():
            if count >= 3:
                parts = seq.split("→")
                if len(parts) == 2:
                    pattern_id = f"causal_{seq.replace('→', '_')}"
                    if pattern_id not in self.patterns:
                        self.patterns[pattern_id] = Pattern(
                            id=pattern_id,
                            pattern_type="causal",
                            description=f"After '{parts[0]}', '{parts[1]}' often follows",
                            conditions={"trigger": parts[0]},
                            prediction=parts[1],
                            confidence=min(0.9, count / 10),
                            occurrences=count,
                            last_seen=datetime.now(),
                        )

    def get_anticipations(self, current_context: Dict) -> List[Tuple[str, float]]:
        """
        Get anticipations based on current context.
        Returns list of (prediction, confidence) tuples.
        """
        anticipations = []
        now = datetime.now()

        for pattern in self.patterns.values():
            # Check if pattern applies
            applies = True

            if pattern.pattern_type == "temporal":
                # Check hour
                if "hour" in pattern.conditions:
                    if pattern.conditions["hour"] != now.hour:
                        applies = False

            elif pattern.pattern_type == "causal":
                # Check trigger
                trigger = pattern.conditions.get("trigger")
                if trigger:
                    recent_event = current_context.get("recent_event")
                    if recent_event != trigger:
                        applies = False

            if applies and pattern.confidence > 0.3:
                anticipations.append((pattern.prediction, pattern.confidence))

        # Sort by confidence
        anticipations.sort(key=lambda x: x[1], reverse=True)
        return anticipations[:5]

    def update_pattern_success(self, pattern_id: str, was_correct: bool):
        """Update pattern success rate based on outcome."""
        if pattern_id in self.patterns:
            pattern = self.patterns[pattern_id]

            # Update success rate with exponential moving average
            alpha = 0.3
            new_value = 1.0 if was_correct else 0.0
            pattern.success_rate = (1 - alpha) * pattern.success_rate + alpha * new_value

            # Remove patterns that are often wrong
            if pattern.occurrences > 10 and pattern.success_rate < 0.2:
                del self.patterns[pattern_id]
                LOG.info(f"Removed unreliable pattern: {pattern_id}")

    def _load_patterns(self):
        """Load patterns from database."""
        try:
            db_path = self.config.db_path
            if not db_path.exists():
                return

            conn = sqlite3.connect(str(db_path), timeout=5)

            # Check if table exists
            cursor = conn.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='genesis_patterns'
            """)
            if not cursor.fetchone():
                conn.close()
                return

            cursor = conn.execute("""
                SELECT id, pattern_type, description, conditions,
                       prediction, confidence, occurrences, last_seen, success_rate
                FROM genesis_patterns
            """)

            import json
            for row in cursor:
                self.patterns[row[0]] = Pattern(
                    id=row[0],
                    pattern_type=row[1],
                    description=row[2],
                    conditions=json.loads(row[3]) if row[3] else {},
                    prediction=row[4],
                    confidence=row[5],
                    occurrences=row[6],
                    last_seen=datetime.fromisoformat(row[7]) if row[7] else datetime.now(),
                    success_rate=row[8] or 0.5,
                )

            conn.close()
            LOG.info(f"Loaded {len(self.patterns)} patterns from database")

        except Exception as e:
            LOG.warning(f"Error loading patterns: {e}")

    def save_patterns(self):
        """Save patterns to database."""
        try:
            db_path = self.config.db_path
            conn = sqlite3.connect(str(db_path), timeout=5)

            # Create table if needed
            conn.execute("""
                CREATE TABLE IF NOT EXISTS genesis_patterns (
                    id TEXT PRIMARY KEY,
                    pattern_type TEXT,
                    description TEXT,
                    conditions TEXT,
                    prediction TEXT,
                    confidence REAL,
                    occurrences INTEGER,
                    last_seen TEXT,
                    success_rate REAL
                )
            """)

            import json
            for pattern in self.patterns.values():
                conn.execute("""
                    INSERT OR REPLACE INTO genesis_patterns
                    (id, pattern_type, description, conditions, prediction,
                     confidence, occurrences, last_seen, success_rate)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    pattern.id,
                    pattern.pattern_type,
                    pattern.description,
                    json.dumps(pattern.conditions),
                    pattern.prediction,
                    pattern.confidence,
                    pattern.occurrences,
                    pattern.last_seen.isoformat(),
                    pattern.success_rate,
                ))

            conn.commit()
            conn.close()
            LOG.debug(f"Saved {len(self.patterns)} patterns")

        except Exception as e:
            LOG.warning(f"Error saving patterns: {e}")

    def to_dict(self) -> Dict:
        """Serialize to dictionary."""
        return {
            "patterns": {k: {
                "type": v.pattern_type,
                "description": v.description,
                "confidence": v.confidence,
                "occurrences": v.occurrences,
                "success_rate": v.success_rate,
            } for k, v in self.patterns.items()},
            "temporal_observations": len(self.temporal_observations),
            "causal_observations": len(self.causal_observations),
        }
