#!/usr/bin/env python3
"""
GitHub Echo Sensor - Hears echoes from the feature database
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import logging

from .base import BaseSensor
from ..core.wave import Wave
from ..config import get_config

LOG = logging.getLogger("genesis.sensors.github")


class GitHubEcho(BaseSensor):
    """
    Senses pending features from the F.A.S. database.

    This is NOT active GitHub scanning - it only reacts
    to features that were already discovered by F.A.S. Scavenger.
    """

    def __init__(self):
        super().__init__("github_echo")
        self.config = get_config()
        self.last_check: Optional[datetime] = None
        self.check_interval = 3600  # 1 hour
        self.pending_features: List[Dict] = []

    def sense(self) -> List[Wave]:
        """Generate waves based on pending features."""
        waves = []

        # Only check periodically
        if not self._should_check():
            # Still emit waves for known pending features
            return self._waves_for_pending()

        try:
            # Load pending features from database
            self.pending_features = self._load_pending_features()
            self.last_check = datetime.now()

            # Generate waves based on findings
            if self.pending_features:
                # More pending features = stronger curiosity
                feature_count = len(self.pending_features)
                amplitude = min(0.5, 0.1 + feature_count * 0.05)

                waves.append(Wave(
                    target_field="curiosity",
                    amplitude=amplitude,
                    decay=0.01,  # Slow decay
                    source=self.name,
                    metadata={
                        "pending_count": feature_count,
                        "source": "github_features",
                    },
                ))

                # High confidence features create stronger waves
                high_conf = [f for f in self.pending_features if f.get("confidence", 0) > 0.8]
                if high_conf:
                    waves.append(Wave(
                        target_field="drive",
                        amplitude=0.3,
                        decay=0.02,
                        source=self.name,
                        metadata={"high_confidence_count": len(high_conf)},
                    ))

                # Old pending features create urgency
                old_features = [f for f in self.pending_features
                               if f.get("age_days", 0) > 7]
                if old_features:
                    waves.append(Wave(
                        target_field="concern",
                        amplitude=0.2,
                        decay=0.02,
                        source=self.name,
                        metadata={"old_features": len(old_features)},
                    ))

            else:
                # No pending features = slight boredom
                waves.append(Wave(
                    target_field="boredom",
                    amplitude=0.1,
                    decay=0.01,
                    source=self.name,
                    metadata={"no_features": True},
                ))

        except Exception as e:
            LOG.warning(f"GitHub echo sensing error: {e}")

        return waves

    def _should_check(self) -> bool:
        """Check if it's time to query the database."""
        if self.last_check is None:
            return True

        elapsed = (datetime.now() - self.last_check).total_seconds()
        return elapsed >= self.check_interval

    def _waves_for_pending(self) -> List[Wave]:
        """Generate waves for known pending features without DB check."""
        waves = []

        if self.pending_features:
            # Emit gentle reminder waves
            waves.append(Wave(
                target_field="curiosity",
                amplitude=0.15,
                decay=0.005,
                source=self.name,
                metadata={"reminder": True, "count": len(self.pending_features)},
            ))

        return waves

    def _load_pending_features(self) -> List[Dict]:
        """Load pending features from the database."""
        features = []

        try:
            # Read from FAS scavenger database (where extracted features live)
            try:
                from config.paths import get_db as _get_db_gh
                db_path = _get_db_gh("fas_scavenger")
            except ImportError:
                db_path = Path.home() / ".local" / "share" / "frank" / "db" / "fas_scavenger.db"
            if not db_path.exists():
                return features

            conn = sqlite3.connect(str(db_path), timeout=5)
            conn.row_factory = sqlite3.Row

            cursor = conn.execute("""
                SELECT
                    id,
                    name,
                    description,
                    source_url,
                    confidence_score AS confidence,
                    integration_status,
                    created_at,
                    quarantine_count
                FROM extracted_features
                WHERE integration_status = 'pending'
                  AND confidence_score >= 0.5
                  AND (quarantine_count IS NULL OR quarantine_count < 3)
                ORDER BY confidence_score DESC
                LIMIT 20
            """)

            now = datetime.now()
            for row in cursor:
                created_str = row["created_at"]
                try:
                    created = datetime.fromisoformat(created_str)
                    age_days = (now - created).days
                except:
                    age_days = 0

                features.append({
                    "id": row["id"],
                    "name": row["name"],
                    "description": row["description"],
                    "source_url": row["source_url"],
                    "confidence": row["confidence"],
                    "age_days": age_days,
                    "quarantine_count": row["quarantine_count"] or 0,
                })

            conn.close()

        except Exception as e:
            LOG.warning(f"Error loading features: {e}")

        return features

    def get_observations(self) -> List[Dict[str, Any]]:
        """Convert pending features to seed observations."""
        observations = []

        for feature in self.pending_features:
            # Each pending feature is a potential seed
            confidence = feature.get("confidence", 0.5)
            age_days = feature.get("age_days", 0)

            # Older features with high confidence are stronger candidates
            strength = confidence * min(1.0, 0.5 + age_days / 14)

            observations.append({
                "type": "feature",
                "target": feature.get("name", "unknown"),
                "approach": "new_tool",
                "origin": "github",
                "feature_id": feature.get("id"),
                "strength": strength,
                "novelty": 0.7,  # GitHub features are relatively novel
                "complexity": 0.5,
                "risk": 0.3,
                "impact": confidence,
                "description": feature.get("description", ""),
                "source_url": feature.get("source_url", ""),
            })

        return observations

    def get_pending_count(self) -> int:
        """Get count of pending features."""
        return len(self.pending_features)

    def get_highest_confidence_feature(self) -> Optional[Dict]:
        """Get the feature with highest confidence."""
        if not self.pending_features:
            return None
        return max(self.pending_features, key=lambda f: f.get("confidence", 0))
