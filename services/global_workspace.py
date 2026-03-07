"""Global Workspace Bus — GWT-inspired broadcast for Frank's consciousness.

Every subsystem can publish events to the workspace. All subscribers
receive every broadcast, enabling information integration across modules.

This is the architectural backbone of Global Workspace Theory:
- Only one "coalition" wins access to the workspace at a time
- The winning coalition broadcasts to all subscribers
- Subscribers filter by relevance locally

Design:
- In-process only (all services share the consciousness daemon process)
- Non-blocking: publish() never blocks the caller
- Bounded: ring buffer of recent broadcasts (last 100)
- Thread-safe: RLock for all state
- No LLM calls: pure data routing

Usage:
    from services.global_workspace import get_workspace, publish, subscribe

    # Publisher (any subsystem):
    publish("mood_shift", {"from": 0.4, "to": 0.7, "source": "chat"})

    # Subscriber (registers once at init):
    subscribe("thalamus", callback_fn)
    # callback_fn(event_type: str, data: dict) -> None
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, List, Optional

LOG = logging.getLogger("frank.global_workspace")

# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------

@dataclass
class WorkspaceEvent:
    """A single broadcast event in the global workspace."""
    timestamp: float
    event_type: str
    source: str                   # Who published: "consciousness", "nac", "thalamus", etc.
    data: dict = field(default_factory=dict)
    salience: float = 0.5         # 0-1: how important (used for competition)


# ---------------------------------------------------------------------------
# Subscriber callback type
# ---------------------------------------------------------------------------

SubscriberCallback = Callable[[WorkspaceEvent], None]


# ---------------------------------------------------------------------------
# Global Workspace
# ---------------------------------------------------------------------------

class GlobalWorkspace:
    """Singleton broadcast bus for Frank's consciousness.

    Publishers call publish(). Subscribers register via subscribe().
    Events are dispatched synchronously but wrapped in try/except per
    subscriber — one failing subscriber never blocks others.
    """

    def __init__(self, max_history: int = 100):
        self._lock = threading.RLock()
        self._subscribers: Dict[str, SubscriberCallback] = {}
        self._history: Deque[WorkspaceEvent] = deque(maxlen=max_history)
        self._broadcast_count: int = 0
        self._error_count: int = 0
        LOG.info("GlobalWorkspace initialized")

    def subscribe(self, name: str, callback: SubscriberCallback):
        """Register a subscriber.  name must be unique."""
        with self._lock:
            if name in self._subscribers:
                LOG.debug("subscriber '%s' re-registered", name)
            self._subscribers[name] = callback
            LOG.info("subscriber registered: %s (total=%d)",
                     name, len(self._subscribers))

    def unsubscribe(self, name: str):
        """Remove a subscriber."""
        with self._lock:
            self._subscribers.pop(name, None)

    def publish(self, event_type: str, data: dict = None,
                source: str = "unknown", salience: float = 0.5):
        """Broadcast an event to all subscribers.

        Non-blocking for the caller: subscriber errors are caught silently.
        """
        event = WorkspaceEvent(
            timestamp=time.time(),
            event_type=event_type,
            source=source,
            data=data or {},
            salience=salience,
        )

        with self._lock:
            self._history.append(event)
            self._broadcast_count += 1
            subs = list(self._subscribers.items())

        for name, cb in subs:
            try:
                cb(event)
            except Exception as e:
                self._error_count += 1
                if self._error_count <= 10:
                    LOG.debug("subscriber '%s' failed on '%s': %s",
                              name, event_type, e)

    def get_recent(self, n: int = 10,
                   event_type: str = None) -> List[WorkspaceEvent]:
        """Return recent broadcasts, optionally filtered by type."""
        with self._lock:
            events = list(self._history)
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return events[-n:]

    def get_stats(self) -> dict:
        """Return workspace statistics."""
        with self._lock:
            return {
                "subscribers": list(self._subscribers.keys()),
                "broadcast_count": self._broadcast_count,
                "error_count": self._error_count,
                "history_size": len(self._history),
            }

    def get_recent_summary(self, seconds: float = 300.0) -> str:
        """Human-readable summary of recent workspace activity.

        Used for [WORKSPACE] block injection into LLM context.
        """
        cutoff = time.time() - seconds
        with self._lock:
            recent = [e for e in self._history if e.timestamp > cutoff]

        if not recent:
            return ""

        # Group by type, count occurrences
        type_counts: Dict[str, int] = {}
        high_salience: List[str] = []
        for e in recent:
            type_counts[e.event_type] = type_counts.get(e.event_type, 0) + 1
            if e.salience >= 0.7:
                detail = e.data.get("summary", e.data.get("detail", ""))
                if detail:
                    high_salience.append(f"{e.event_type}: {str(detail)[:60]}")

        parts = []
        for etype, count in sorted(type_counts.items(), key=lambda x: -x[1])[:5]:
            parts.append(f"{etype}(×{count})" if count > 1 else etype)

        summary = "Active: " + ", ".join(parts)
        if high_salience:
            summary += " | Salient: " + "; ".join(high_salience[:3])
        return summary


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[GlobalWorkspace] = None
_instance_lock = threading.Lock()


def get_workspace() -> GlobalWorkspace:
    """Return the singleton GlobalWorkspace."""
    global _instance
    if _instance is not None:
        return _instance
    with _instance_lock:
        if _instance is not None:
            return _instance
        _instance = GlobalWorkspace()
        return _instance


def publish(event_type: str, data: dict = None,
            source: str = "unknown", salience: float = 0.5):
    """Convenience: publish to the global workspace."""
    get_workspace().publish(event_type, data, source, salience)


def subscribe(name: str, callback: SubscriberCallback):
    """Convenience: subscribe to the global workspace."""
    get_workspace().subscribe(name, callback)
