"""
Lightweight helper for autonomous-action overlay notifications.

Any background service (consciousness, dream, entities, genesis) can import
``notify_autonomous`` to drop a one-liner notification into the overlay.

The overlay's notification_mixin polls /tmp/frank/notifications/ every 15s and
displays the message in the chat stream.  No socket, no HTTP — just a JSON
file write.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path

LOG = logging.getLogger("frank.autonomous_notify")

_NOTIFY_DIR = Path(
    os.environ.get("FRANK_TEMP_DIR", "/tmp/frank")
) / "notifications"


def notify_autonomous(
    action: str,
    detail: str = "",
    *,
    category: str = "autonomous",
    urgency: str = "low",
    source: str = "",
) -> None:
    """Write a short overlay notification for an autonomous action.

    Parameters
    ----------
    action : str
        Short label, e.g. "Deep Reflection", "Web Search", "Dream Phase 1".
    detail : str
        One-line summary of what happened / was found.
    category : str
        Notification category for icon mapping.
        Supported: autonomous, consciousness, dream, entity, genesis.
    urgency : str
        "low" (subtle), "normal" (standard), "critical" (highlighted).
    source : str
        Originating service name (for logging), e.g. "consciousness_daemon".
    """
    try:
        _NOTIFY_DIR.mkdir(parents=True, exist_ok=True)

        body = f"{action}: {detail}" if detail else action
        # Keep short — overlay space is limited
        if len(body) > 200:
            body = body[:197] + "..."

        nid = f"auto_{uuid.uuid4().hex[:8]}"
        ts_iso = time.strftime("%Y-%m-%dT%H:%M:%S")
        notification = {
            "id": nid,
            "category": category,
            "title": action,
            "body": body,
            "urgency": urgency,
            "timestamp": ts_iso,
            "read": False,
            "source": source or "autonomous",
        }

        path = _NOTIFY_DIR / f"{int(time.time())}_{nid}.json"
        path.write_text(json.dumps(notification, ensure_ascii=False))
        LOG.debug("Autonomous notification: %s → %s", action, path.name)
    except Exception as exc:
        LOG.debug("notify_autonomous failed: %s", exc)
