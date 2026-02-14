#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UOLG API for Frank

Simple API for Frank to query system understanding.

Usage:
    from tools.omni_log_monitor.frank_api import get_system_health, get_insights, explain

    # Get current system health
    health = get_system_health()
    print(health["summary"])

    # Get recent insights
    insights = get_insights(count=5)
    for i in insights:
        print(f"{i['entity']}: {i['event_class']}")

    # Explain something
    explanation = explain("why is the GPU hot?")
    print(explanation["hypotheses"])
"""

import json
import urllib.request
import urllib.error
from typing import Dict, List, Optional

UIF_API_URL = "http://localhost:8197"
TIMEOUT = 5.0


def _http_get(endpoint: str) -> Optional[dict]:
    """Make HTTP GET request."""
    try:
        req = urllib.request.Request(f"{UIF_API_URL}{endpoint}")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def _http_post(endpoint: str, data: dict) -> Optional[dict]:
    """Make HTTP POST request."""
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"{UIF_API_URL}{endpoint}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def is_available() -> bool:
    """Check if UOLG is available."""
    result = _http_get("/health")
    return result is not None and "status" in result


def get_system_health() -> Dict:
    """
    Get current system health assessment.

    Returns:
        {
            "health": "nominal" | "attention" | "degraded" | "critical",
            "summary": "Human-readable summary",
            "alerts": int,
            "investigations": int,
        }
    """
    result = _http_get("/status")
    if result is None:
        return {
            "health": "unknown",
            "summary": "UOLG not available",
            "alerts": 0,
            "investigations": 0,
        }

    return {
        "health": result.get("health", "unknown"),
        "summary": result.get("health_summary", ""),
        "alerts": result.get("statistics", {}).get("alerts", 0),
        "investigations": result.get("statistics", {}).get("investigations", 0),
        "troubled_entities": result.get("troubled_entities", []),
    }


def get_insights(count: int = 10, alerts_only: bool = False) -> List[Dict]:
    """
    Get recent system insights.

    Args:
        count: Number of insights to return
        alerts_only: If True, only return alerts

    Returns:
        List of insight dicts with:
        - entity: Affected entity (e.g., "Browser", "systemd")
        - event_class: Event classification
        - hypotheses: List of {cause, weight} dicts
        - confidence: Overall confidence (0-1)
        - actionability: "observe" | "investigate" | "alert"
    """
    endpoint = "/alerts" if alerts_only else "/insights"
    result = _http_get(endpoint)

    if result is None:
        return []

    key = "alerts" if alerts_only else "insights"
    insights = result.get(key, [])

    return insights[-count:]


def get_security_events(hours: int = 24) -> List[Dict]:
    """
    Get recent security-relevant events.

    Args:
        hours: How many hours back to look

    Returns:
        List of security event dicts
    """
    result = _http_get("/security")
    if result is None:
        return []
    return result.get("security_events", [])


def get_entity_history(entity: str) -> Dict:
    """
    Get historical understanding of a specific entity.

    Args:
        entity: Entity name (e.g., "Browser", "nvidia-driver")

    Returns:
        {
            "entity": str,
            "known_patterns": List,
            "recent_events": List,
            "failure_chains": List,
        }
    """
    result = _http_get(f"/entity/{entity}")
    if result is None:
        return {"entity": entity, "known_patterns": [], "recent_events": [], "failure_chains": []}
    return result


def explain(query: str) -> Dict:
    """
    Get explanation for a query about system state.

    Args:
        query: Natural language query (e.g., "why did the browser crash?")

    Returns:
        {
            "query": str,
            "relevant_events": int,
            "hypotheses": List[{cause, weight}],
            "system_context": str,
            "confidence": float,
        }
    """
    result = _http_post("/explain", {"query": query})
    if result is None:
        return {
            "query": query,
            "relevant_events": 0,
            "hypotheses": [],
            "system_context": "UOLG not available",
            "confidence": 0.0,
        }
    return result


def ingest_insight(insight: Dict) -> bool:
    """
    Manually ingest an insight (for testing or external sources).

    Args:
        insight: UIF-formatted insight dict

    Returns:
        True if successful
    """
    result = _http_post("/ingest", {"insight": insight})
    return result is not None and result.get("ok", False)


# Convenience functions for common queries

def has_alerts() -> bool:
    """Check if there are any current alerts."""
    health = get_system_health()
    return health.get("alerts", 0) > 0


def get_system_summary() -> str:
    """Get a one-line system summary."""
    health = get_system_health()
    return f"[{health['health'].upper()}] {health['summary']}"


def get_top_hypotheses(count: int = 3) -> List[Dict]:
    """Get top hypotheses from recent insights."""
    insights = get_insights(20)

    # Aggregate hypotheses
    cause_weights = {}
    for insight in insights:
        for h in insight.get("hypotheses", []):
            cause = h.get("cause", "Unknown")
            weight = h.get("weight", 0.5)
            if cause in cause_weights:
                cause_weights[cause] = max(cause_weights[cause], weight)
            else:
                cause_weights[cause] = weight

    # Sort and return top
    sorted_causes = sorted(
        cause_weights.items(),
        key=lambda x: x[1],
        reverse=True
    )

    return [
        {"cause": cause, "weight": round(weight, 2)}
        for cause, weight in sorted_causes[:count]
    ]


# For Frank's context window
def get_context_block() -> str:
    """
    Get a formatted context block for Frank's prompt.

    Returns a concise summary suitable for injection into context.
    """
    if not is_available():
        return "[UOLG: offline]"

    health = get_system_health()
    insights = get_insights(3, alerts_only=True)

    lines = [f"[UOLG: {health['health']}] {health['summary']}"]

    if insights:
        lines.append("Recent alerts:")
        for i in insights:
            hyp = i.get("hypotheses", [{}])[0]
            lines.append(f"  - {i['entity']}: {hyp.get('cause', 'Unknown')} ({hyp.get('weight', 0):.0%})")

    return "\n".join(lines)


if __name__ == "__main__":
    # Quick test
    print("UOLG Frank API Test")
    print("=" * 40)
    print(f"Available: {is_available()}")
    print()
    print("System Health:")
    print(json.dumps(get_system_health(), indent=2))
    print()
    print("Context Block:")
    print(get_context_block())
