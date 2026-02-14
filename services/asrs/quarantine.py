#!/usr/bin/env python3
"""
A.S.R.S. Feature Quarantine
Isolates problematic features and manages retry logic.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import logging
import json

from .config import ASRSConfig, get_asrs_config

LOG = logging.getLogger("asrs.quarantine")


@dataclass
class QuarantineEntry:
    """Quarantine record for a feature."""
    feature_id: int
    reason: str
    quarantine_count: int
    quarantined_at: str
    retry_after: Optional[str]
    is_permanent: bool

    def to_dict(self) -> Dict:
        return {
            "feature_id": self.feature_id,
            "reason": self.reason,
            "quarantine_count": self.quarantine_count,
            "quarantined_at": self.quarantined_at,
            "retry_after": self.retry_after,
            "is_permanent": self.is_permanent,
        }


class FeatureQuarantine:
    """
    Manages quarantine of features that fail integration.
    """

    def __init__(self, config: ASRSConfig = None):
        self.config = config or get_asrs_config()
        self._ensure_db_schema()

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(
            str(self.config.db_path),
            check_same_thread=False,
            timeout=30.0
        )
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_db_schema(self):
        """Ensure quarantine columns exist."""
        conn = self._get_conn()
        try:
            # Check if columns exist
            cursor = conn.execute("PRAGMA table_info(extracted_features)")
            columns = {row['name'] for row in cursor.fetchall()}

            if 'quarantine_count' not in columns:
                conn.execute("ALTER TABLE extracted_features ADD COLUMN quarantine_count INTEGER DEFAULT 0")
            if 'quarantine_reason' not in columns:
                conn.execute("ALTER TABLE extracted_features ADD COLUMN quarantine_reason TEXT")
            if 'quarantined_at' not in columns:
                conn.execute("ALTER TABLE extracted_features ADD COLUMN quarantined_at TEXT")
            if 'retry_after' not in columns:
                conn.execute("ALTER TABLE extracted_features ADD COLUMN retry_after TEXT")
            if 'last_failure_report' not in columns:
                conn.execute("ALTER TABLE extracted_features ADD COLUMN last_failure_report TEXT")
            if 'retry_strategy' not in columns:
                conn.execute("ALTER TABLE extracted_features ADD COLUMN retry_strategy TEXT")

            conn.commit()
        except Exception as e:
            LOG.error(f"Failed to ensure DB schema: {e}")
        finally:
            conn.close()

    def quarantine(self, feature_id: int, reason: str,
                   failure_report: Dict = None) -> QuarantineEntry:
        """
        Quarantine a feature after integration failure.

        Args:
            feature_id: ID of the feature
            reason: Reason for quarantine
            failure_report: Optional failure report dict

        Returns:
            QuarantineEntry with quarantine details
        """
        conn = self._get_conn()
        now = datetime.now()

        try:
            # Get current quarantine count
            row = conn.execute(
                "SELECT quarantine_count FROM extracted_features WHERE id = ?",
                (feature_id,)
            ).fetchone()

            current_count = row['quarantine_count'] if row and row['quarantine_count'] else 0
            new_count = current_count + 1

            # Determine if permanent
            is_permanent = new_count >= self.config.max_quarantine_retries

            # Calculate retry time
            retry_after = None
            if not is_permanent:
                retry_after = (now + timedelta(hours=self.config.quarantine_cooldown_hours)).isoformat()

            # Determine status
            status = "rejected_auto" if is_permanent else "quarantined"

            # Update database
            conn.execute("""
                UPDATE extracted_features
                SET integration_status = ?,
                    quarantine_count = ?,
                    quarantine_reason = ?,
                    quarantined_at = ?,
                    retry_after = ?,
                    last_failure_report = ?,
                    user_approved = 0
                WHERE id = ?
            """, (
                status,
                new_count,
                reason,
                now.isoformat(),
                retry_after,
                json.dumps(failure_report) if failure_report else None,
                feature_id,
            ))
            conn.commit()

            entry = QuarantineEntry(
                feature_id=feature_id,
                reason=reason,
                quarantine_count=new_count,
                quarantined_at=now.isoformat(),
                retry_after=retry_after,
                is_permanent=is_permanent,
            )

            if is_permanent:
                LOG.warning(f"Feature #{feature_id} permanently rejected after {new_count} failures")
            else:
                LOG.info(f"Feature #{feature_id} quarantined (count: {new_count}), "
                         f"retry after: {retry_after}")

            return entry

        finally:
            conn.close()

    def release(self, feature_id: int) -> bool:
        """
        Release a feature from quarantine for retry.

        Args:
            feature_id: ID of the feature

        Returns:
            True if released, False if permanently rejected or not found
        """
        conn = self._get_conn()

        try:
            row = conn.execute(
                "SELECT integration_status, quarantine_count FROM extracted_features WHERE id = ?",
                (feature_id,)
            ).fetchone()

            if not row:
                return False

            if row['integration_status'] == 'rejected_auto':
                LOG.warning(f"Cannot release permanently rejected feature #{feature_id}")
                return False

            conn.execute("""
                UPDATE extracted_features
                SET integration_status = 'ready',
                    quarantined_at = NULL,
                    retry_after = NULL
                WHERE id = ?
            """, (feature_id,))
            conn.commit()

            LOG.info(f"Released feature #{feature_id} from quarantine")
            return True

        finally:
            conn.close()

    def get_quarantined(self) -> List[QuarantineEntry]:
        """Get all quarantined features."""
        conn = self._get_conn()

        try:
            rows = conn.execute("""
                SELECT id, quarantine_reason, quarantine_count, quarantined_at, retry_after
                FROM extracted_features
                WHERE integration_status = 'quarantined'
                ORDER BY quarantined_at DESC
            """).fetchall()

            return [
                QuarantineEntry(
                    feature_id=row['id'],
                    reason=row['quarantine_reason'] or "Unknown",
                    quarantine_count=row['quarantine_count'] or 1,
                    quarantined_at=row['quarantined_at'] or "",
                    retry_after=row['retry_after'],
                    is_permanent=False,
                )
                for row in rows
            ]

        finally:
            conn.close()

    def get_ready_for_retry(self) -> List[int]:
        """Get feature IDs that are ready for retry."""
        conn = self._get_conn()
        now = datetime.now().isoformat()

        try:
            rows = conn.execute("""
                SELECT id FROM extracted_features
                WHERE integration_status = 'quarantined'
                  AND retry_after IS NOT NULL
                  AND retry_after <= ?
            """, (now,)).fetchall()

            return [row['id'] for row in rows]

        finally:
            conn.close()

    def get_quarantine_info(self, feature_id: int) -> Optional[QuarantineEntry]:
        """Get quarantine info for a specific feature."""
        conn = self._get_conn()

        try:
            row = conn.execute("""
                SELECT id, quarantine_reason, quarantine_count, quarantined_at,
                       retry_after, integration_status
                FROM extracted_features
                WHERE id = ?
            """, (feature_id,)).fetchone()

            if not row:
                return None

            is_permanent = row['integration_status'] == 'rejected_auto'

            return QuarantineEntry(
                feature_id=row['id'],
                reason=row['quarantine_reason'] or "Unknown",
                quarantine_count=row['quarantine_count'] or 0,
                quarantined_at=row['quarantined_at'] or "",
                retry_after=row['retry_after'],
                is_permanent=is_permanent,
            )

        finally:
            conn.close()

    def reset_quarantine(self, feature_id: int) -> bool:
        """
        Reset quarantine count and status for a feature (admin action).

        Args:
            feature_id: ID of the feature

        Returns:
            True if reset successful
        """
        conn = self._get_conn()

        try:
            conn.execute("""
                UPDATE extracted_features
                SET integration_status = 'ready',
                    quarantine_count = 0,
                    quarantine_reason = NULL,
                    quarantined_at = NULL,
                    retry_after = NULL,
                    last_failure_report = NULL,
                    retry_strategy = NULL
                WHERE id = ?
            """, (feature_id,))
            conn.commit()

            LOG.info(f"Reset quarantine for feature #{feature_id}")
            return True

        except Exception as e:
            LOG.error(f"Failed to reset quarantine: {e}")
            return False

        finally:
            conn.close()

    def set_retry_strategy(self, feature_id: int, strategy: str):
        """Set retry strategy for a quarantined feature."""
        conn = self._get_conn()

        try:
            conn.execute("""
                UPDATE extracted_features
                SET retry_strategy = ?
                WHERE id = ?
            """, (strategy, feature_id))
            conn.commit()
            LOG.info(f"Set retry strategy '{strategy}' for feature #{feature_id}")

        finally:
            conn.close()

    def get_statistics(self) -> Dict:
        """Get quarantine statistics."""
        conn = self._get_conn()

        try:
            stats = {}

            # Count by status
            row = conn.execute("""
                SELECT COUNT(*) as count FROM extracted_features
                WHERE integration_status = 'quarantined'
            """).fetchone()
            stats['quarantined'] = row['count']

            row = conn.execute("""
                SELECT COUNT(*) as count FROM extracted_features
                WHERE integration_status = 'rejected_auto'
            """).fetchone()
            stats['permanently_rejected'] = row['count']

            # Ready for retry
            now = datetime.now().isoformat()
            row = conn.execute("""
                SELECT COUNT(*) as count FROM extracted_features
                WHERE integration_status = 'quarantined'
                  AND retry_after IS NOT NULL
                  AND retry_after <= ?
            """, (now,)).fetchone()
            stats['ready_for_retry'] = row['count']

            # Average quarantine count
            row = conn.execute("""
                SELECT AVG(quarantine_count) as avg FROM extracted_features
                WHERE quarantine_count > 0
            """).fetchone()
            stats['avg_quarantine_count'] = round(row['avg'] or 0, 2)

            return stats

        finally:
            conn.close()
