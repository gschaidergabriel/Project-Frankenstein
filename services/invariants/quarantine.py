#!/usr/bin/env python3
"""
QUARANTINE DIMENSION
====================

When knowledge is fundamentally unstable, it is not deleted.
It is moved to a quarantine dimension where it:
- Exists (not lost)
- Is isolated (cannot affect main system)
- Can be reviewed periodically
- May be restored if stability improves

Quarantine triggers:
- 3x divergence at same point
- Hard consolidation of unresolvable conflicts
- Entropy emergency (S > S_MAX)

Frank's perspective:
- Quarantined knowledge becomes "uncertain"
- He knows he doesn't know
- This is epistemological humility, not failure
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from .config import get_config, InvariantsConfig, QUARANTINE_DIR
from .db_schema import get_store, InvariantsStore

LOG = logging.getLogger("invariants.quarantine")


@dataclass
class QuarantinedItem:
    """A quarantined knowledge item."""
    quarantine_id: int
    knowledge_id: str
    original_data: Dict
    reason: str
    quarantined_at: datetime
    divergence_count: int
    region_id: Optional[str]
    reviewed: bool
    review_result: Optional[str]


class QuarantineDimension:
    """
    Manages the quarantine dimension for unstable knowledge.

    Quarantine is NOT deletion. It's isolation.
    Quarantined items:
    - Cannot affect the main knowledge system
    - Are periodically reviewed
    - May be restored if conditions improve
    - Are eventually deleted if too old
    """

    def __init__(self, config: InvariantsConfig = None, store: InvariantsStore = None):
        self.config = config or get_config()
        self.store = store or get_store()

        # Ensure quarantine directory exists
        self.quarantine_dir = self.config.quarantine_dir
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)

        LOG.info("Quarantine Dimension initialized")

    def quarantine_item(self, knowledge_id: str, data: str, reason: str,
                        region_id: str = None) -> int:
        """
        Move a knowledge item to quarantine.

        Returns the quarantine ID.
        """
        LOG.info(f"Quarantining {knowledge_id}: {reason}")

        # Add to database
        quarantine_id = self.store.quarantine_knowledge(
            knowledge_id, data, reason, region_id
        )

        # Also save to file for redundancy
        item_path = self.quarantine_dir / f"{knowledge_id}.json"
        try:
            item_data = {
                "quarantine_id": quarantine_id,
                "knowledge_id": knowledge_id,
                "original_data": data,
                "reason": reason,
                "region_id": region_id,
                "quarantined_at": datetime.now().isoformat(),
            }
            item_path.write_text(json.dumps(item_data, indent=2))
        except Exception as e:
            LOG.warning(f"Could not save quarantine file: {e}")

        # Update invariant state
        size = self.store.get_quarantine_size()
        self.store.update_invariant_state(
            "quarantine_dimension",
            size,
            threshold=self.config.quarantine_max_size,
            status="normal" if size < self.config.quarantine_max_size else "warning"
        )

        return quarantine_id

    def quarantine_region(self, titan_store, region_id: str, reason: str) -> int:
        """
        Quarantine all knowledge in a region.

        Returns count of quarantined items.
        """
        LOG.warning(f"Quarantining entire region {region_id}: {reason}")

        count = 0

        try:
            # Get nodes that match the region pattern
            # Region IDs are like "node_abc12345" or "conf_abc12345"
            node_prefix = region_id.replace("node_", "").replace("conf_", "")

            with titan_store.sqlite._get_conn() as conn:
                # Find matching nodes
                rows = conn.execute(
                    "SELECT id, content FROM nodes WHERE id LIKE ?",
                    (f"{node_prefix}%",)
                ).fetchall()

                for row in rows:
                    self.quarantine_item(
                        row["id"],
                        row["content"] or "",
                        f"region_quarantine: {reason}",
                        region_id
                    )
                    count += 1

                # Remove from main database
                conn.execute(
                    "DELETE FROM nodes WHERE id LIKE ?",
                    (f"{node_prefix}%",)
                )
                conn.execute(
                    "DELETE FROM edges WHERE src LIKE ? OR dst LIKE ?",
                    (f"{node_prefix}%", f"{node_prefix}%")
                )
                conn.commit()

        except Exception as e:
            LOG.error(f"Error quarantining region: {e}")

        # Record healing action
        self.store.record_healing_action(
            "region_quarantine",
            reason,
            count,
            True,
            region_id
        )

        return count

    def get_quarantined_items(self, region_id: str = None) -> List[QuarantinedItem]:
        """Get all quarantined items, optionally filtered by region."""
        items = self.store.get_quarantined(region_id)

        result = []
        for item in items:
            try:
                result.append(QuarantinedItem(
                    quarantine_id=item["id"],
                    knowledge_id=item["knowledge_id"],
                    original_data=json.loads(item["original_data"]) if item["original_data"].startswith("{") else {"content": item["original_data"]},
                    reason=item["quarantine_reason"],
                    quarantined_at=datetime.fromisoformat(item["quarantined_at"]),
                    divergence_count=item["divergence_count"],
                    region_id=item["region_id"],
                    reviewed=bool(item["reviewed"]),
                    review_result=item["review_result"]
                ))
            except Exception as e:
                LOG.warning(f"Error parsing quarantine item: {e}")

        return result

    def review_item(self, quarantine_id: int) -> Tuple[bool, str]:
        """
        Review a quarantined item for potential restoration.

        Returns (can_restore, reason).
        """
        items = self.store.get_quarantined()
        item = next((i for i in items if i["id"] == quarantine_id), None)

        if not item:
            return False, "Item not found"

        # Check age
        quarantined_at = datetime.fromisoformat(item["quarantined_at"])
        age_days = (datetime.now() - quarantined_at).days

        if age_days > self.config.quarantine_max_age_days:
            return False, f"Too old ({age_days} days)"

        # Check divergence count
        if item["divergence_count"] >= self.config.max_divergence_attempts:
            return False, f"Too many divergences ({item['divergence_count']})"

        # Check if region is still unstable
        region_id = item["region_id"]
        if region_id:
            divergence_count = self.store.get_divergence_count(region_id)
            if divergence_count >= self.config.max_divergence_attempts:
                return False, f"Region still unstable"

        return True, "Can be restored"

    def restore_item(self, titan_store, quarantine_id: int) -> bool:
        """
        Restore a quarantined item to the main knowledge base.
        """
        items = self.store.get_quarantined()
        item = next((i for i in items if i["id"] == quarantine_id), None)

        if not item:
            LOG.warning(f"Quarantine item {quarantine_id} not found")
            return False

        can_restore, reason = self.review_item(quarantine_id)
        if not can_restore:
            LOG.warning(f"Cannot restore {quarantine_id}: {reason}")
            return False

        try:
            # Parse original data
            try:
                data = json.loads(item["original_data"])
            except Exception:
                data = {"content": item["original_data"]}

            # Restore to Titan (simplified - full implementation would use proper API)
            with titan_store.sqlite._get_conn() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO nodes (id, content, confidence)
                    VALUES (?, ?, ?)
                """, (item["knowledge_id"], data.get("content", ""), 0.3))  # Low confidence
                conn.commit()

            # Remove from quarantine
            self.store.remove_from_quarantine(quarantine_id)

            # Remove quarantine file
            item_path = self.quarantine_dir / f"{item['knowledge_id']}.json"
            if item_path.exists():
                item_path.unlink()

            LOG.info(f"Restored {item['knowledge_id']} from quarantine")

            # Record healing action
            self.store.record_healing_action(
                "quarantine_restore",
                f"Restored {item['knowledge_id']}",
                1,
                True
            )

            return True

        except Exception as e:
            LOG.error(f"Error restoring from quarantine: {e}")
            return False

    def cleanup_old_items(self) -> int:
        """
        Clean up old quarantined items.

        Items older than quarantine_max_age_days are deleted.
        """
        items = self.get_quarantined_items()
        deleted = 0

        for item in items:
            age_days = (datetime.now() - item.quarantined_at).days

            if age_days > self.config.quarantine_max_age_days:
                LOG.info(f"Deleting old quarantine item {item.knowledge_id} ({age_days} days)")

                # Remove from database
                self.store.remove_from_quarantine(item.quarantine_id)

                # Remove file
                item_path = self.quarantine_dir / f"{item.knowledge_id}.json"
                if item_path.exists():
                    item_path.unlink()

                deleted += 1

        if deleted > 0:
            LOG.info(f"Cleaned up {deleted} old quarantine items")

        return deleted

    def enforce_size_limit(self) -> int:
        """
        Enforce quarantine size limit.

        If too many items, delete oldest ones.
        """
        current_size = self.store.get_quarantine_size()

        if current_size <= self.config.quarantine_max_size:
            return 0

        # Need to delete some
        to_delete = current_size - self.config.quarantine_max_size + 10  # Some buffer

        items = self.get_quarantined_items()
        items.sort(key=lambda i: i.quarantined_at)  # Oldest first

        deleted = 0
        for item in items[:to_delete]:
            self.store.remove_from_quarantine(item.quarantine_id)

            item_path = self.quarantine_dir / f"{item.knowledge_id}.json"
            if item_path.exists():
                item_path.unlink()

            deleted += 1

        LOG.warning(f"Enforced size limit: deleted {deleted} oldest items")
        return deleted

    def get_statistics(self) -> Dict:
        """Get quarantine statistics."""
        items = self.get_quarantined_items()

        if not items:
            return {
                "total": 0,
                "by_reason": {},
                "by_region": {},
                "avg_age_days": 0,
                "oldest_days": 0,
            }

        # Group by reason
        by_reason = {}
        for item in items:
            reason = item.reason.split(":")[0]  # First part of reason
            by_reason[reason] = by_reason.get(reason, 0) + 1

        # Group by region
        by_region = {}
        for item in items:
            region = item.region_id or "unknown"
            by_region[region] = by_region.get(region, 0) + 1

        # Calculate ages
        ages = [(datetime.now() - item.quarantined_at).days for item in items]
        avg_age = sum(ages) / len(ages) if ages else 0
        oldest = max(ages) if ages else 0

        return {
            "total": len(items),
            "by_reason": by_reason,
            "by_region": by_region,
            "avg_age_days": avg_age,
            "oldest_days": oldest,
            "can_restore": sum(1 for i in items if self.review_item(i.quarantine_id)[0]),
        }

    def get_status(self) -> Dict:
        """Get quarantine dimension status."""
        stats = self.get_statistics()

        return {
            "size": stats["total"],
            "max_size": self.config.quarantine_max_size,
            "utilization": stats["total"] / self.config.quarantine_max_size,
            "by_reason": stats["by_reason"],
            "avg_age_days": stats["avg_age_days"],
            "can_restore": stats.get("can_restore", 0),
        }


# Global instance
_quarantine: Optional[QuarantineDimension] = None


def get_quarantine() -> QuarantineDimension:
    """Get or create the global quarantine dimension instance."""
    global _quarantine
    if _quarantine is None:
        _quarantine = QuarantineDimension()
    return _quarantine
