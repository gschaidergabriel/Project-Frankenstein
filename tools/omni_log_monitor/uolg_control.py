#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UOLG Control Script

Control interface for the Universal Omniscient Log Gateway.

Usage:
    python3 uolg_control.py start       # Start UOLG daemon
    python3 uolg_control.py stop        # Stop UOLG daemon
    python3 uolg_control.py status      # Show status
    python3 uolg_control.py insights    # Show recent insights
    python3 uolg_control.py health      # Show system health
    python3 uolg_control.py explain "query"  # Explain something
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).parent
UIF_API_URL = "http://localhost:8197"
UOLG_PID_FILE = Path("/tmp/uolg/uolg.pid")
UOLG_LOG = Path("/tmp/uolg/uolg.log")


def http_get(endpoint: str, timeout: float = 5.0) -> dict:
    """Make HTTP GET request."""
    try:
        req = urllib.request.Request(f"{UIF_API_URL}{endpoint}")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.URLError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


def http_post(endpoint: str, data: dict, timeout: float = 5.0) -> dict:
    """Make HTTP POST request."""
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"{UIF_API_URL}{endpoint}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}


def is_running() -> bool:
    """Check if UOLG is running."""
    result = http_get("/health")
    return "error" not in result


def start():
    """Start UOLG daemon."""
    if is_running():
        print("UOLG is already running")
        return True

    print("Starting UOLG...")

    # Start log ingest daemon
    ingest_script = BASE_DIR / "log_ingest.py"
    subprocess.Popen(
        ["python3", str(ingest_script), "--daemon"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    # Start UIF bridge API
    bridge_script = BASE_DIR / "uif_bridge.py"
    subprocess.Popen(
        ["python3", str(bridge_script), "--server"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    # Wait for startup
    time.sleep(2)

    if is_running():
        print("UOLG started successfully")
        return True
    else:
        print("UOLG failed to start")
        return False


def stop():
    """Stop UOLG daemon."""
    print("Stopping UOLG...")

    # Kill processes
    subprocess.run(["pkill", "-f", "log_ingest.py"], capture_output=True)
    subprocess.run(["pkill", "-f", "uif_bridge.py.*--server"], capture_output=True)

    time.sleep(1)

    if not is_running():
        print("UOLG stopped")
        return True
    else:
        print("UOLG may still be running")
        return False


def status():
    """Show UOLG status."""
    result = http_get("/status")

    if "error" in result:
        print("UOLG Status: NOT RUNNING")
        print(f"Error: {result['error']}")
        return

    print("UOLG Status: RUNNING")
    print(f"System Health: {result.get('health', 'unknown')}")
    print(f"Summary: {result.get('health_summary', '')}")
    print()

    stats = result.get("statistics", {})
    print("Statistics:")
    print(f"  Recent Insights: {stats.get('recent_insights', 0)}")
    print(f"  Alerts: {stats.get('alerts', 0)}")
    print(f"  Investigations: {stats.get('investigations', 0)}")
    print(f"  Known Patterns: {stats.get('pattern_count', 0)}")
    print(f"  Failure Chains: {stats.get('failure_chain_count', 0)}")

    troubled = result.get("troubled_entities", [])
    if troubled:
        print()
        print("Troubled Entities:")
        for entity in troubled:
            print(f"  - {entity['entity']}: {entity['event_count']} events")


def insights(count: int = 10):
    """Show recent insights."""
    result = http_get("/insights")

    if "error" in result:
        print(f"Error: {result['error']}")
        return

    insights_list = result.get("insights", [])

    if not insights_list:
        print("No recent insights")
        return

    print(f"Recent Insights ({len(insights_list)}):")
    print("-" * 60)

    for i in insights_list[-count:]:
        time_str = i.get("time", "?")[:19]
        entity = i.get("entity", "?")
        event_class = i.get("event_class", "?")
        confidence = i.get("confidence", 0)
        action = i.get("actionability", "?")

        # Color coding based on actionability
        if action == "alert":
            prefix = "[!]"
        elif action == "investigate":
            prefix = "[?]"
        else:
            prefix = "[ ]"

        print(f"{prefix} {time_str} | {entity:<20} | {event_class:<20} | conf={confidence:.2f}")

        hypotheses = i.get("hypotheses", [])[:2]
        for h in hypotheses:
            print(f"    -> {h['cause']}: {h['weight']:.0%}")


def alerts():
    """Show recent alerts."""
    result = http_get("/alerts")

    if "error" in result:
        print(f"Error: {result['error']}")
        return

    alerts_list = result.get("alerts", [])

    if not alerts_list:
        print("No recent alerts")
        return

    print(f"Alerts ({len(alerts_list)}):")
    print("-" * 60)

    for a in alerts_list:
        time_str = a.get("time", "?")[:19]
        entity = a.get("entity", "?")
        event_class = a.get("event_class", "?")

        print(f"[ALERT] {time_str} | {entity} | {event_class}")

        hypotheses = a.get("hypotheses", [])[:3]
        for h in hypotheses:
            print(f"  Hypothesis: {h['cause']} ({h['weight']:.0%})")


def explain(query: str):
    """Get explanation for a query."""
    result = http_post("/explain", {"query": query})

    if "error" in result:
        print(f"Error: {result['error']}")
        return

    print(f"Query: {result.get('query', query)}")
    print(f"Relevant Events: {result.get('relevant_events', 0)}")
    print(f"Confidence: {result.get('confidence', 0):.0%}")
    print(f"Context: {result.get('system_context', '')}")
    print()

    hypotheses = result.get("hypotheses", [])
    if hypotheses:
        print("Hypotheses:")
        for h in hypotheses:
            print(f"  - {h['cause']}: {h['weight']:.0%}")
    else:
        print("No specific hypotheses formed")


def security():
    """Show security events."""
    result = http_get("/security")

    if "error" in result:
        print(f"Error: {result['error']}")
        return

    events = result.get("security_events", [])

    if not events:
        print("No security events in last 24 hours")
        return

    print(f"Security Events ({len(events)}):")
    print("-" * 60)

    for e in events[-10:]:
        time_str = e.get("time", "?")[:19]
        entity = e.get("entity", "?")
        event_class = e.get("event_class", "?")

        print(f"[SEC] {time_str} | {entity} | {event_class}")


def policy():
    """Show policy guard status."""
    from policy_guard import get_guard

    guard = get_guard()
    status = guard.get_status()

    print("Policy Guard Status:")
    print(f"  Mode: {status['mode']}")
    print(f"  Gaming Active: {status['gaming_active']}")
    print(f"  Intrusive Allowed: {status['intrusive_allowed']}")
    print(f"  Anti-Cheat Detected: {status['anti_cheat_detected']}")
    print(f"  Resource: {status['resource_status']}")

    blocked = status.get("blocked_operations", [])
    if blocked:
        print(f"  Blocked Operations: {', '.join(blocked)}")


def main():
    """Entry point."""
    if len(sys.argv) < 2:
        print("UOLG - Universal Omniscient Log Gateway")
        print()
        print("Usage: uolg_control.py <command>")
        print()
        print("Commands:")
        print("  start     - Start UOLG daemon")
        print("  stop      - Stop UOLG daemon")
        print("  restart   - Restart UOLG daemon")
        print("  status    - Show system status")
        print("  health    - Show system health")
        print("  insights  - Show recent insights")
        print("  alerts    - Show recent alerts")
        print("  security  - Show security events")
        print("  policy    - Show policy guard status")
        print("  explain <query> - Explain something")
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "start":
        start()
    elif cmd == "stop":
        stop()
    elif cmd == "restart":
        stop()
        time.sleep(1)
        start()
    elif cmd == "status":
        status()
    elif cmd == "health":
        result = http_get("/health")
        if "error" in result:
            print(f"Health: UNKNOWN ({result['error']})")
        else:
            print(f"Health: {result.get('health', 'unknown').upper()}")
            print(f"Summary: {result.get('summary', '')}")
    elif cmd == "insights":
        count = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        insights(count)
    elif cmd == "alerts":
        alerts()
    elif cmd == "security":
        security()
    elif cmd == "policy":
        policy()
    elif cmd == "explain":
        if len(sys.argv) < 3:
            print("Usage: uolg_control.py explain <query>")
            sys.exit(1)
        query = " ".join(sys.argv[2:])
        explain(query)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
