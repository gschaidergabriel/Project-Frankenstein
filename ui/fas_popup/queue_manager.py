#!/usr/bin/env python3
"""
F.A.S. Proposal Queue Manager
Manages feature queue and trigger conditions for popup.
"""

import json
import logging
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Setup logging
LOG = logging.getLogger("fas_queue_manager")
if not LOG.handlers:
    LOG.addHandler(logging.StreamHandler(sys.stderr))
    LOG.setLevel(logging.DEBUG)


class ProposalQueueManager:
    """
    Manages the feature proposal queue and determines when to show popup.
    Thread-safe with proper locking for SQLite operations.
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        from config.paths import get_db as _get_db, get_state as _get_state
        _default_db = str(_get_db("fas_scavenger"))
        self.db_path = Path(self.config.get(
            "db_path",
            _default_db
        ))
        self.state_file = Path(self.config.get(
            "popup_state_file",
            str(_get_state("fas_popup_state"))
        ))

        # Trigger thresholds
        self.min_features = self.config.get("min_features_for_auto_popup", 7)
        self.min_confidence = self.config.get("min_confidence_score", 0.85)
        self.max_popups_per_day = self.config.get("max_popups_per_day", 2)
        self.cooldown_hours = self.config.get("cooldown_hours", 8)
        self.feature_expiry_days = self.config.get("feature_expiry_days", 14)
        self.postpone_hours = self.config.get("postpone_hours", 8)

        # Thread-safety: Lock for all DB operations (CRITICAL #2 fix)
        self._db_lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection. Must be called with _db_lock held."""
        if self._conn is None:
            self._conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0
            )
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _load_state(self) -> dict:
        """Load popup state from file."""
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text())
            except json.JSONDecodeError as e:
                LOG.warning(f"Could not parse state file: {e}")
            except OSError as e:
                LOG.warning(f"Could not read state file: {e}")
            except Exception as e:
                LOG.error(f"Unexpected error loading state: {e}")
        return {
            "popups_today": [],
            "last_popup_time": None,
            "postponed_until": None,
        }

    def _save_state(self, state: dict):
        """Save popup state to file."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, indent=2))

    def get_ready_features(self) -> List[Dict]:
        """
        Get features that are ready for proposal.
        - Passed sandbox testing
        - High confidence
        - Not yet approved by user
        - Not expired
        Thread-safe with proper locking.
        """
        with self._db_lock:
            conn = self._get_conn()
            expiry_date = (datetime.now() - timedelta(days=self.feature_expiry_days)).isoformat()

            # Fixed: Show all ready/notified features that haven't been approved yet
            # The user_notified flag only tracks if notification was attempted,
            # not whether user made a decision
            rows = conn.execute("""
                SELECT * FROM extracted_features
                WHERE sandbox_passed = 1
                  AND confidence_score >= ?
                  AND integration_status IN ('ready', 'notified')
                  AND user_approved = 0
                  AND created_at > ?
                ORDER BY confidence_score DESC
            """, (self.min_confidence, expiry_date)).fetchall()

            return [dict(row) for row in rows]

    def get_all_features(self) -> List[Dict]:
        """
        Get ALL features regardless of status filters.
        Shows everything that hasn't been permanently rejected or integrated.
        Includes pending, testing, ready, notified, approved, rollback features.
        """
        with self._db_lock:
            conn = self._get_conn()
            rows = conn.execute("""
                SELECT * FROM extracted_features
                WHERE integration_status NOT IN ('rejected_permanent', 'integrated')
                ORDER BY
                    CASE integration_status
                        WHEN 'ready' THEN 0
                        WHEN 'notified' THEN 1
                        WHEN 'approved' THEN 2
                        WHEN 'testing' THEN 3
                        WHEN 'pending' THEN 4
                        WHEN 'rollback' THEN 5
                        ELSE 6
                    END,
                    confidence_score DESC
            """).fetchall()
            return [dict(row) for row in rows]

    def get_high_confidence_features(self) -> List[Dict]:
        """Get features with confidence >= threshold."""
        features = self.get_ready_features()
        return [f for f in features if f.get("confidence_score", 0) >= self.min_confidence]

    def should_trigger_popup(self) -> Tuple[bool, str]:
        """
        Determine if popup should be triggered.
        Returns (should_trigger, reason).
        """
        state = self._load_state()

        # Clean old popup records (keep only today's)
        today = datetime.now().date().isoformat()
        state["popups_today"] = [
            p for p in state.get("popups_today", [])
            if p.startswith(today)
        ]
        self._save_state(state)

        # Check postponement
        if state.get("postponed_until"):
            postponed_until = datetime.fromisoformat(state["postponed_until"])
            if datetime.now() < postponed_until:
                remaining = (postponed_until - datetime.now()).total_seconds() / 3600
                return False, f"Postponed for {remaining:.1f}h more"

        # Check daily limit
        popups_today = len(state.get("popups_today", []))
        if popups_today >= self.max_popups_per_day:
            return False, f"Daily limit reached ({popups_today}/{self.max_popups_per_day})"

        # Check cooldown
        if state.get("last_popup_time"):
            last_popup = datetime.fromisoformat(state["last_popup_time"])
            hours_since = (datetime.now() - last_popup).total_seconds() / 3600
            if hours_since < self.cooldown_hours:
                remaining = self.cooldown_hours - hours_since
                return False, f"Cooldown: {remaining:.1f}h remaining"

        # Check feature count
        ready_features = self.get_high_confidence_features()
        feature_count = len(ready_features)

        if feature_count < self.min_features:
            return False, f"Only {feature_count}/{self.min_features} features ready"

        # All conditions met
        return True, f"{feature_count} features ready for proposal"

    def record_popup_shown(self):
        """Record that a popup was shown."""
        state = self._load_state()
        now = datetime.now()

        state["last_popup_time"] = now.isoformat()
        state["popups_today"] = state.get("popups_today", [])
        state["popups_today"].append(now.isoformat())
        state["postponed_until"] = None  # Clear postponement

        self._save_state(state)

    def postpone_popup(self, hours: int = None):
        """Postpone popup for specified hours."""
        if hours is None:
            hours = self.postpone_hours

        state = self._load_state()
        state["postponed_until"] = (datetime.now() + timedelta(hours=hours)).isoformat()
        self._save_state(state)

    def get_popups_today(self) -> int:
        """Get number of popups shown today."""
        state = self._load_state()
        today = datetime.now().date().isoformat()
        return len([p for p in state.get("popups_today", []) if p.startswith(today)])

    def get_queue_status(self) -> Dict:
        """Get current queue status."""
        state = self._load_state()
        ready_features = self.get_ready_features()
        high_conf_features = self.get_high_confidence_features()

        return {
            "total_ready": len(ready_features),
            "high_confidence": len(high_conf_features),
            "min_required": self.min_features,
            "progress": min(100, int((len(high_conf_features) / self.min_features) * 100)),
            "popups_today": self.get_popups_today(),
            "max_popups_per_day": self.max_popups_per_day,
            "postponed_until": state.get("postponed_until"),
            "last_popup": state.get("last_popup_time"),
            "cooldown_hours": self.cooldown_hours,
        }

    def approve_feature(self, feature_id: int, response: str = "") -> bool:
        """Approve a feature for integration. Thread-safe with proper locking."""
        with self._db_lock:
            conn = self._get_conn()
            try:
                conn.execute("""
                    UPDATE extracted_features
                    SET user_approved = 1,
                        user_approved_at = ?,
                        user_response = ?,
                        integration_status = 'approved'
                    WHERE id = ?
                """, (datetime.now().isoformat(), response, feature_id))
                conn.commit()
                return True
            except sqlite3.Error as e:
                LOG.error(f"SQLite error approving feature {feature_id}: {e}")
                return False
            except Exception as e:
                LOG.error(f"Error approving feature {feature_id}: {e}")
                return False

    def reject_feature(self, feature_id: int, permanent: bool = True, response: str = "") -> bool:
        """Reject a feature (optionally permanently). Thread-safe with proper locking."""
        with self._db_lock:
            conn = self._get_conn()
            status = "rejected_permanent" if permanent else "rejected"
            try:
                conn.execute("""
                    UPDATE extracted_features
                    SET user_approved = 0,
                        user_approved_at = ?,
                        user_response = ?,
                        integration_status = ?
                    WHERE id = ?
                """, (datetime.now().isoformat(), response, status, feature_id))
                conn.commit()
                return True
            except sqlite3.Error as e:
                LOG.error(f"SQLite error rejecting feature {feature_id}: {e}")
                return False
            except Exception as e:
                LOG.error(f"Error rejecting feature {feature_id}: {e}")
                return False

    def reactivate_feature(self, feature_id: int) -> bool:
        """Reactivate a rejected feature. Thread-safe with proper locking."""
        with self._db_lock:
            conn = self._get_conn()
            try:
                conn.execute("""
                    UPDATE extracted_features
                    SET integration_status = 'ready',
                        user_approved = 0,
                        user_notified = 0,
                        user_notified_at = NULL,
                        user_approved_at = NULL,
                        user_response = NULL
                    WHERE id = ?
                """, (feature_id,))
                conn.commit()
                return True
            except sqlite3.Error as e:
                LOG.error(f"SQLite error reactivating feature {feature_id}: {e}")
                return False
            except Exception as e:
                LOG.error(f"Error reactivating feature {feature_id}: {e}")
                return False

    def get_archived_features(self) -> List[Dict]:
        """Get rejected/archived features. Thread-safe with proper locking."""
        with self._db_lock:
            conn = self._get_conn()
            rows = conn.execute("""
                SELECT * FROM extracted_features
                WHERE integration_status IN ('rejected', 'rejected_permanent')
                ORDER BY user_approved_at DESC
                LIMIT 100
            """).fetchall()
            return [dict(row) for row in rows]

    def get_integrated_features(self) -> List[Dict]:
        """Get successfully integrated features. Thread-safe with proper locking."""
        with self._db_lock:
            conn = self._get_conn()
            rows = conn.execute("""
                SELECT * FROM extracted_features
                WHERE integration_status = 'integrated'
                ORDER BY integrated_at DESC
            """).fetchall()
            return [dict(row) for row in rows]

    def get_statistics(self) -> Dict:
        """Get overall statistics. Thread-safe with proper locking."""
        with self._db_lock:
            conn = self._get_conn()

            stats = {}
            for status in ["pending", "testing", "ready", "approved", "integrated",
                           "rejected", "rejected_permanent"]:
                row = conn.execute(
                    "SELECT COUNT(*) as count FROM extracted_features WHERE integration_status = ?",
                    (status,)
                ).fetchone()
                stats[status] = row["count"] if row else 0

            return {
                "in_queue": stats["pending"] + stats["testing"] + stats["ready"],
                "approved": stats["approved"],
                "integrated": stats["integrated"],
                "rejected": stats["rejected"] + stats["rejected_permanent"],
                "total": sum(stats.values()),
            }


# Singleton
_manager: Optional[ProposalQueueManager] = None


def get_queue_manager() -> ProposalQueueManager:
    """Get or create queue manager singleton."""
    global _manager
    if _manager is None:
        from config.fas_popup_config import get_config
        _manager = ProposalQueueManager(get_config())
    return _manager
