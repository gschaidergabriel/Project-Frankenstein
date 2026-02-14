#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UIF Bridge - Unified Insight Format Bridge

Translates UOLG insights into Frank's world model.
Provides API for Frank to query system understanding.

This bridge serves as the interface between:
- UOLG (raw log processing)
- Frank's epistemics (hypothesis-driven understanding)
- World experience database (long-term learning)
"""

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging
import sys

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s [UIF]: %(message)s',
)
LOG = logging.getLogger("uif_bridge")

# Paths
try:
    from config.paths import DB_DIR, get_state, get_db
    SECURITY_LOG = get_state("security_log")
    WORLD_EXPERIENCE_DB = get_db("world_experience")
    INSIGHT_CACHE = get_state("insight_cache")
except ImportError:
    DB_DIR = Path("/home/ai-core-node/aicore/database")
    DB_DIR.mkdir(parents=True, exist_ok=True)
    SECURITY_LOG = DB_DIR / "security_log.json"
    WORLD_EXPERIENCE_DB = DB_DIR / "world_experience.db"
    INSIGHT_CACHE = DB_DIR / "insight_cache.json"

# API Port
UIF_API_PORT = 8197


@dataclass
class WorldExperience:
    """Long-term system experience entry."""
    pattern_id: str
    pattern_type: str  # "failure_chain", "load_pattern", "stability_signal"
    description: str
    occurrence_count: int
    first_seen: datetime
    last_seen: datetime
    confidence: float
    related_entities: List[str]


class WorldExperienceDB:
    """
    SQLite database for long-term system experience.

    Stores:
    - Recurring load patterns
    - Typical failure chains
    - Long-term system dynamics

    No personalized profiles - only technical abstractions.
    """

    def __init__(self, db_path: Path = WORLD_EXPERIENCE_DB):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS patterns (
                    pattern_id TEXT PRIMARY KEY,
                    pattern_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    occurrence_count INTEGER DEFAULT 1,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    confidence REAL DEFAULT 0.5,
                    related_entities TEXT DEFAULT '[]'
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS failure_chains (
                    chain_id TEXT PRIMARY KEY,
                    trigger_event TEXT NOT NULL,
                    consequence_events TEXT NOT NULL,
                    occurrence_count INTEGER DEFAULT 1,
                    avg_time_delta_sec REAL,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS hypothesis_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hypothesis_cause TEXT NOT NULL,
                    predicted_weight REAL,
                    actual_outcome TEXT,
                    correct INTEGER,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_patterns_type
                ON patterns(pattern_type)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_chains_trigger
                ON failure_chains(trigger_event)
            """)

            conn.commit()

    def record_pattern(self, pattern_type: str, description: str,
                       entities: List[str], confidence: float = 0.5) -> str:
        """Record or update a system pattern."""
        import hashlib
        pattern_id = hashlib.md5(
            f"{pattern_type}:{description}".encode()
        ).hexdigest()[:16]

        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                # Check if exists
                row = conn.execute(
                    "SELECT occurrence_count, confidence FROM patterns WHERE pattern_id = ?",
                    (pattern_id,)
                ).fetchone()

                if row:
                    # Update existing
                    new_count = row[0] + 1
                    # Confidence increases with repetition (max 0.95)
                    new_confidence = min(0.95, row[1] + 0.05)

                    conn.execute("""
                        UPDATE patterns SET
                            occurrence_count = ?,
                            last_seen = CURRENT_TIMESTAMP,
                            confidence = ?,
                            related_entities = ?
                        WHERE pattern_id = ?
                    """, (new_count, new_confidence, json.dumps(entities), pattern_id))
                else:
                    # Insert new
                    conn.execute("""
                        INSERT INTO patterns (pattern_id, pattern_type, description,
                                            confidence, related_entities)
                        VALUES (?, ?, ?, ?, ?)
                    """, (pattern_id, pattern_type, description,
                          confidence, json.dumps(entities)))

                conn.commit()

        return pattern_id

    def record_failure_chain(self, trigger: str, consequences: List[str],
                            time_delta_sec: float):
        """Record a failure chain (trigger -> consequences)."""
        import hashlib
        chain_id = hashlib.md5(
            f"{trigger}:{':'.join(sorted(consequences))}".encode()
        ).hexdigest()[:16]

        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT occurrence_count, avg_time_delta_sec FROM failure_chains WHERE chain_id = ?",
                    (chain_id,)
                ).fetchone()

                if row:
                    new_count = row[0] + 1
                    # Running average of time delta
                    new_avg = (row[1] * row[0] + time_delta_sec) / new_count

                    conn.execute("""
                        UPDATE failure_chains SET
                            occurrence_count = ?,
                            avg_time_delta_sec = ?,
                            last_seen = CURRENT_TIMESTAMP
                        WHERE chain_id = ?
                    """, (new_count, new_avg, chain_id))
                else:
                    conn.execute("""
                        INSERT INTO failure_chains (chain_id, trigger_event,
                                                   consequence_events, avg_time_delta_sec)
                        VALUES (?, ?, ?, ?)
                    """, (chain_id, trigger, json.dumps(consequences), time_delta_sec))

                conn.commit()

        return chain_id

    def get_patterns_for_entity(self, entity: str) -> List[dict]:
        """Get patterns related to an entity."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT * FROM patterns
                    WHERE related_entities LIKE ?
                    ORDER BY confidence DESC, occurrence_count DESC
                    LIMIT 10
                """, (f'%"{entity}"%',)).fetchall()

                return [dict(row) for row in rows]

    def get_failure_chains_for_trigger(self, trigger: str) -> List[dict]:
        """Get known failure chains for a trigger event."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT * FROM failure_chains
                    WHERE trigger_event = ?
                    ORDER BY occurrence_count DESC
                    LIMIT 5
                """, (trigger,)).fetchall()

                return [dict(row) for row in rows]

    def record_hypothesis_outcome(self, hypothesis_cause: str,
                                   predicted_weight: float,
                                   actual_outcome: str,
                                   correct: int) -> None:
        """Record whether a hypothesis prediction was correct.

        Args:
            hypothesis_cause: The predicted cause (e.g. "Memory_Leak")
            predicted_weight: The weight the hypothesis was assigned (0-1)
            actual_outcome: What actually happened (e.g. "confirmed_Resource_Anomaly")
            correct: 1 if hypothesis was correct, 0 if wrong
        """
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO hypothesis_outcomes
                    (hypothesis_cause, predicted_weight, actual_outcome, correct)
                    VALUES (?, ?, ?, ?)
                """, (hypothesis_cause, predicted_weight, actual_outcome, correct))
                conn.commit()

    def get_hypothesis_accuracy(self, cause: Optional[str] = None,
                                limit: int = 50) -> List[dict]:
        """Get prediction accuracy stats, optionally filtered by cause type."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                if cause:
                    rows = conn.execute("""
                        SELECT hypothesis_cause,
                               COUNT(*) as total,
                               SUM(correct) as correct_count,
                               AVG(predicted_weight) as avg_weight
                        FROM hypothesis_outcomes
                        WHERE hypothesis_cause = ?
                        GROUP BY hypothesis_cause
                        ORDER BY total DESC
                        LIMIT ?
                    """, (cause, limit)).fetchall()
                else:
                    rows = conn.execute("""
                        SELECT hypothesis_cause,
                               COUNT(*) as total,
                               SUM(correct) as correct_count,
                               AVG(predicted_weight) as avg_weight
                        FROM hypothesis_outcomes
                        GROUP BY hypothesis_cause
                        ORDER BY total DESC
                        LIMIT ?
                    """, (limit,)).fetchall()

                return [
                    {
                        "cause": r[0],
                        "total": r[1],
                        "correct": r[2] or 0,
                        "accuracy": round((r[2] or 0) / r[1], 3) if r[1] > 0 else 0,
                        "avg_weight": round(r[3] or 0, 3),
                    }
                    for r in rows
                ]

    def get_statistics(self) -> dict:
        """Get database statistics."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                pattern_count = conn.execute(
                    "SELECT COUNT(*) FROM patterns"
                ).fetchone()[0]

                chain_count = conn.execute(
                    "SELECT COUNT(*) FROM failure_chains"
                ).fetchone()[0]

                hypothesis_count = conn.execute(
                    "SELECT COUNT(*) FROM hypothesis_outcomes"
                ).fetchone()[0]

                hypothesis_accuracy = 0
                if hypothesis_count > 0:
                    row = conn.execute(
                        "SELECT AVG(correct) FROM hypothesis_outcomes"
                    ).fetchone()
                    hypothesis_accuracy = round((row[0] or 0), 3)

                avg_confidence = conn.execute(
                    "SELECT AVG(confidence) FROM patterns"
                ).fetchone()[0] or 0

                return {
                    "pattern_count": pattern_count,
                    "failure_chain_count": chain_count,
                    "hypothesis_outcome_count": hypothesis_count,
                    "hypothesis_accuracy": hypothesis_accuracy,
                    "average_confidence": round(avg_confidence, 3),
                }


class UIFBridge:
    """
    Bridge between UOLG and Frank's world model.

    Provides:
    - Query API for recent insights
    - Pattern learning from insights
    - Hypothesis refinement based on outcomes
    """

    # Hypothesis validation settings
    HYPOTHESIS_TTL_SEC = 300  # 5 minutes to see follow-up events

    def __init__(self):
        self.world_db = WorldExperienceDB()
        self._insight_cache: List[dict] = []
        self._cache_lock = threading.Lock()
        self._pending_hypotheses: List[dict] = []
        self._hyp_lock = threading.Lock()
        self._load_cache()

    def _load_cache(self):
        """Load insight cache from disk."""
        try:
            if INSIGHT_CACHE.exists():
                self._insight_cache = json.loads(INSIGHT_CACHE.read_text())
        except Exception:
            self._insight_cache = []

    def _save_cache(self):
        """Save insight cache to disk."""
        try:
            INSIGHT_CACHE.write_text(json.dumps(self._insight_cache[-200:], indent=2))
        except Exception as e:
            LOG.error(f"Failed to save cache: {e}")

    def ingest_insight(self, insight: dict):
        """Ingest a new insight from UOLG."""
        with self._cache_lock:
            self._insight_cache.append(insight)
            if len(self._insight_cache) > 500:
                self._insight_cache = self._insight_cache[-200:]

        # Learn from insight
        self._learn_from_insight(insight)

    def _learn_from_insight(self, insight: dict):
        """Extract patterns, validate hypotheses, and learn from insight."""
        entity = insight.get("entity", "Unknown")
        event_class = insight.get("event_class", "General")
        hypotheses = insight.get("hypotheses", [])

        # ── STEP 1: Validate pending hypotheses against this new event ──
        self._validate_hypotheses(entity, event_class)

        # ── STEP 2: Record pattern (existing logic) ──
        if hypotheses:
            top_cause = hypotheses[0].get("cause", "Unknown")
            # Adjust weight using historical accuracy
            adjusted = self._get_adaptive_weight(top_cause)
            confidence = insight.get("confidence", 0.5)
            if adjusted is not None:
                confidence = confidence * 0.6 + adjusted * 0.4

            description = f"{event_class}: {top_cause}"
            self.world_db.record_pattern(
                pattern_type=event_class.lower(),
                description=description,
                entities=[entity],
                confidence=confidence,
            )

        # ── STEP 3: Record failure chain (existing logic) ──
        correlation_ids = insight.get("correlation_ids", [])
        if correlation_ids:
            self.world_db.record_failure_chain(
                trigger=event_class,
                consequences=correlation_ids[:3],
                time_delta_sec=5.0,
            )

        # ── STEP 4: Store new hypotheses as pending for future validation ──
        if hypotheses:
            with self._hyp_lock:
                self._pending_hypotheses.append({
                    "timestamp": time.time(),
                    "entity": entity,
                    "event_class": event_class,
                    "hypotheses": hypotheses,
                })
                # Cap pending buffer
                if len(self._pending_hypotheses) > 200:
                    self._pending_hypotheses = self._pending_hypotheses[-100:]

        # ── STEP 5: Clean up expired hypotheses ──
        self._cleanup_expired_hypotheses()

    def _validate_hypotheses(self, entity: str, event_class: str):
        """Check pending hypotheses against a new event for this entity.

        When the same entity has a follow-up event, we can assess whether
        the original hypothesized cause was plausible.
        """
        with self._hyp_lock:
            now = time.time()
            validated_indices = []

            for i, pending in enumerate(self._pending_hypotheses):
                # Only match same entity
                if pending["entity"] != entity:
                    continue
                # Skip expired (cleanup handles those)
                if now - pending["timestamp"] > self.HYPOTHESIS_TTL_SEC:
                    continue

                for hyp in pending["hypotheses"]:
                    cause = hyp.get("cause", "Unknown")
                    weight = hyp.get("weight", 0.5)

                    if pending["event_class"] == event_class:
                        # Same event class recurrence → hypothesis cause confirmed
                        self.world_db.record_hypothesis_outcome(
                            cause, weight,
                            f"confirmed:{event_class}",
                            correct=1,
                        )
                    else:
                        # Different event class → top hypothesis was less accurate
                        # Only penalize the top hypothesis (weight > 0.3)
                        if weight >= 0.3:
                            self.world_db.record_hypothesis_outcome(
                                cause, weight,
                                f"diverged:{pending['event_class']}->{event_class}",
                                correct=0,
                            )

                validated_indices.append(i)

            # Remove validated (reverse order to preserve indices)
            for i in reversed(validated_indices):
                self._pending_hypotheses.pop(i)

    def _cleanup_expired_hypotheses(self):
        """Clean up hypotheses that expired without follow-up events.

        No contradiction within TTL = weak confirmation of the top hypothesis.
        """
        with self._hyp_lock:
            now = time.time()
            remaining = []
            for pending in self._pending_hypotheses:
                age = now - pending["timestamp"]
                if age > self.HYPOTHESIS_TTL_SEC:
                    # Expired - top hypothesis gets weak confirmation
                    if pending["hypotheses"]:
                        top = pending["hypotheses"][0]
                        self.world_db.record_hypothesis_outcome(
                            top.get("cause", "Unknown"),
                            top.get("weight", 0.5),
                            "expired_no_contradiction",
                            correct=1,
                        )
                else:
                    remaining.append(pending)
            self._pending_hypotheses = remaining

    def _get_adaptive_weight(self, cause: str) -> Optional[float]:
        """Get adjusted confidence based on historical accuracy of this cause type.

        Returns None if insufficient data, otherwise 0.0-1.0 accuracy score.
        """
        accuracy_data = self.world_db.get_hypothesis_accuracy(cause=cause)
        if not accuracy_data:
            return None
        data = accuracy_data[0]
        if data["total"] < 5:
            return None  # Not enough data yet
        return data["accuracy"]

    def query_recent_insights(self, count: int = 10,
                              filter_actionability: Optional[str] = None) -> List[dict]:
        """Query recent insights."""
        with self._cache_lock:
            results = list(self._insight_cache)

        if filter_actionability:
            results = [i for i in results
                      if i.get("actionability") == filter_actionability]

        return results[-count:]

    def query_security_events(self, hours: int = 24) -> List[dict]:
        """Query recent security events."""
        try:
            if not SECURITY_LOG.exists():
                return []

            data = json.loads(SECURITY_LOG.read_text())
            cutoff = datetime.now() - timedelta(hours=hours)

            recent = []
            for entry in data:
                try:
                    ts = datetime.fromisoformat(entry.get("time", ""))
                    if ts > cutoff:
                        recent.append(entry)
                except Exception:
                    continue

            return recent
        except Exception as e:
            LOG.error(f"Failed to query security events: {e}")
            return []

    def get_system_understanding(self) -> dict:
        """
        Get Frank's current understanding of the system.

        This is the main API for Frank to understand what's happening.
        """
        recent_insights = self.query_recent_insights(20)
        security_events = self.query_security_events(1)  # Last hour
        db_stats = self.world_db.get_statistics()

        # Analyze recent insights
        alert_count = sum(1 for i in recent_insights
                        if i.get("actionability") == "alert")
        investigate_count = sum(1 for i in recent_insights
                               if i.get("actionability") == "investigate")

        # Group by entity
        entities: Dict[str, List[dict]] = {}
        for insight in recent_insights:
            entity = insight.get("entity", "Unknown")
            if entity not in entities:
                entities[entity] = []
            entities[entity].append(insight)

        # Find most affected entities
        troubled_entities = sorted(
            entities.items(),
            key=lambda x: sum(1 for i in x[1] if i.get("actionability") != "observe"),
            reverse=True
        )[:5]

        # Overall health assessment
        if alert_count >= 3:
            health = "critical"
            health_summary = "Multiple alerts requiring attention"
        elif alert_count >= 1:
            health = "degraded"
            health_summary = "Some alerts present"
        elif investigate_count >= 3:
            health = "attention"
            health_summary = "Several events worth investigating"
        elif len(recent_insights) == 0:
            health = "quiet"
            health_summary = "No significant events detected"
        else:
            health = "nominal"
            health_summary = "System operating normally"

        return {
            "timestamp": datetime.now().isoformat(),
            "health": health,
            "health_summary": health_summary,
            "statistics": {
                "recent_insights": len(recent_insights),
                "alerts": alert_count,
                "investigations": investigate_count,
                "security_events_1h": len(security_events),
                **db_stats,
            },
            "troubled_entities": [
                {
                    "entity": entity,
                    "event_count": len(events),
                    "top_event": events[-1] if events else None,
                }
                for entity, events in troubled_entities
                if len(events) > 0
            ],
            "recent_alerts": [
                i for i in recent_insights
                if i.get("actionability") == "alert"
            ][-5:],
        }

    def get_entity_history(self, entity: str) -> dict:
        """Get historical understanding of a specific entity."""
        patterns = self.world_db.get_patterns_for_entity(entity)

        # Get recent insights for entity
        recent = [
            i for i in self._insight_cache
            if i.get("entity") == entity
        ][-10:]

        # Get failure chains
        for insight in recent:
            event_class = insight.get("event_class", "")
            chains = self.world_db.get_failure_chains_for_trigger(event_class)
            if chains:
                break
        else:
            chains = []

        return {
            "entity": entity,
            "known_patterns": patterns,
            "recent_events": recent,
            "failure_chains": chains,
        }

    def form_explanation(self, query: str) -> dict:
        """
        Form an explanation for a query about system state.

        This enables Frank to provide explanatory answers.
        """
        understanding = self.get_system_understanding()

        # Simple keyword matching for now
        keywords = query.lower().split()

        relevant_insights = []
        for insight in self._insight_cache[-50:]:
            insight_text = json.dumps(insight).lower()
            if any(kw in insight_text for kw in keywords):
                relevant_insights.append(insight)

        # Form hypotheses
        hypotheses = []
        if relevant_insights:
            # Aggregate hypotheses from relevant insights
            cause_weights: Dict[str, float] = {}
            for insight in relevant_insights:
                for h in insight.get("hypotheses", []):
                    cause = h.get("cause", "Unknown")
                    weight = h.get("weight", 0.5)
                    if cause in cause_weights:
                        cause_weights[cause] = max(cause_weights[cause], weight)
                    else:
                        cause_weights[cause] = weight

            hypotheses = [
                {"cause": cause, "weight": round(weight, 2)}
                for cause, weight in sorted(
                    cause_weights.items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:5]
            ]

        return {
            "query": query,
            "relevant_events": len(relevant_insights),
            "hypotheses": hypotheses,
            "system_context": understanding["health_summary"],
            "confidence": min(0.9, 0.3 + len(relevant_insights) * 0.1),
        }


class UIFAPIHandler(BaseHTTPRequestHandler):
    """HTTP API for UIF Bridge."""

    bridge: UIFBridge = None

    def log_message(self, format, *args):
        pass  # Suppress default logging

    def _send_json(self, data: dict, code: int = 200):
        body = json.dumps(data, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/status" or self.path == "/":
            self._send_json(self.bridge.get_system_understanding())

        elif self.path == "/health":
            understanding = self.bridge.get_system_understanding()
            self._send_json({
                "status": "running",
                "health": understanding["health"],
                "summary": understanding["health_summary"],
            })

        elif self.path == "/insights":
            insights = self.bridge.query_recent_insights(20)
            self._send_json({"insights": insights})

        elif self.path == "/alerts":
            alerts = self.bridge.query_recent_insights(
                50, filter_actionability="alert"
            )
            self._send_json({"alerts": alerts})

        elif self.path == "/security":
            events = self.bridge.query_security_events(24)
            self._send_json({"security_events": events})

        elif self.path.startswith("/entity/"):
            entity = self.path[8:]
            history = self.bridge.get_entity_history(entity)
            self._send_json(history)

        elif self.path == "/stats":
            stats = self.bridge.world_db.get_statistics()
            self._send_json(stats)

        elif self.path == "/hypotheses":
            accuracy = self.bridge.world_db.get_hypothesis_accuracy()
            pending_count = len(self.bridge._pending_hypotheses)
            self._send_json({
                "accuracy_by_cause": accuracy,
                "pending_hypotheses": pending_count,
            })

        else:
            self._send_json({"error": "unknown endpoint"}, 404)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
        except Exception:
            body = {}

        if self.path == "/ingest":
            # Ingest new insight from UOLG
            if "insight" in body:
                self.bridge.ingest_insight(body["insight"])
                self._send_json({"ok": True})
            else:
                self._send_json({"error": "missing insight"}, 400)

        elif self.path == "/explain":
            # Form explanation for query
            query = body.get("query", "")
            explanation = self.bridge.form_explanation(query)
            self._send_json(explanation)

        else:
            self._send_json({"error": "unknown endpoint"}, 404)


def run_api_server(bridge: UIFBridge, port: int = UIF_API_PORT):
    """Run the UIF API server."""
    UIFAPIHandler.bridge = bridge
    server = HTTPServer(("127.0.0.1", port), UIFAPIHandler)
    LOG.info(f"UIF Bridge API running on port {port}")
    server.serve_forever()


def main():
    """Entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="UIF Bridge")
    parser.add_argument("--server", action="store_true", help="Run API server")
    parser.add_argument("--status", action="store_true", help="Show status")
    parser.add_argument("--explain", type=str, help="Explain a query")
    args = parser.parse_args()

    bridge = UIFBridge()

    if args.status:
        understanding = bridge.get_system_understanding()
        print(json.dumps(understanding, indent=2))
        return

    if args.explain:
        explanation = bridge.form_explanation(args.explain)
        print(json.dumps(explanation, indent=2))
        return

    if args.server:
        run_api_server(bridge)
        return

    # Default: show status
    understanding = bridge.get_system_understanding()
    print(f"System Health: {understanding['health']}")
    print(f"Summary: {understanding['health_summary']}")
    print(f"Statistics: {json.dumps(understanding['statistics'], indent=2)}")


if __name__ == "__main__":
    main()
