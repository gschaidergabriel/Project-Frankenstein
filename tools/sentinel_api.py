#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Frank API for Network Sentinel

Simple API for Frank to query network intelligence.

Usage:
    from tools.sentinel_api import get_network_status, scan_network, get_devices

    # Get current network status
    status = get_network_status()
    print(status["gaming_mode"])

    # Scan network (if not gaming)
    devices = scan_network()
    for d in devices:
        print(f"{d['ip']} - {d['hostname']}")

    # Get known devices
    net_map = get_devices()
"""

import json
from typing import Dict, List, Optional

# Lazy import to avoid loading heavy modules unnecessarily
_sentinel = None


def _get_sentinel():
    """Get sentinel module lazily."""
    global _sentinel
    if _sentinel is None:
        try:
            from tools import network_sentinel
            _sentinel = network_sentinel
        except ImportError:
            import sys
            try:
                from config.paths import AICORE_ROOT
                sys.path.insert(0, str(AICORE_ROOT))
            except ImportError:
                from pathlib import Path
                sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tools/ -> opt/aicore
            from tools import network_sentinel
            _sentinel = network_sentinel
    return _sentinel


def is_available() -> bool:
    """Check if Network Sentinel is available."""
    try:
        _get_sentinel()
        return True
    except:
        return False


def get_network_status() -> Dict:
    """
    Get current network intelligence status.

    Returns:
        {
            "running": bool,
            "gaming_mode": bool,
            "devices_known": int,
            "last_scan": str or None,
            "analyzer_enabled": bool,
        }
    """
    try:
        return _get_sentinel().get_status()
    except Exception as e:
        return {
            "running": False,
            "gaming_mode": False,
            "devices_known": 0,
            "last_scan": None,
            "analyzer_enabled": False,
            "error": str(e),
        }


def scan_network() -> List[Dict]:
    """
    Trigger network scan (if not in gaming mode).

    Returns:
        List of device dicts with ip, mac, hostname, etc.
    """
    try:
        return _get_sentinel().scan_network()
    except Exception as e:
        return []


def get_devices() -> Dict:
    """
    Get known network devices.

    Returns:
        {
            "timestamp": str,
            "gaming_mode": bool,
            "device_count": int,
            "devices": List[device_dict],
        }
    """
    try:
        return _get_sentinel().get_network_map()
    except Exception as e:
        return {
            "timestamp": None,
            "gaming_mode": False,
            "device_count": 0,
            "devices": [],
            "error": str(e),
        }


def is_gaming() -> bool:
    """Check if gaming mode is active."""
    try:
        return _get_sentinel().is_gaming()
    except:
        return False


def get_network_summary() -> str:
    """
    Get a one-line network summary for Frank's context.

    Returns:
        Human-readable summary string.
    """
    try:
        status = get_network_status()
        net_map = get_devices()

        if status.get("gaming_mode"):
            return "[Network: Monitoring paused - Gaming Mode]"

        device_count = net_map.get("device_count", 0)

        if not status.get("running"):
            return f"[Network: Sentinel offline, {device_count} devices cached]"

        return f"[Network: Active, {device_count} devices, Sentinel running]"

    except Exception as e:
        return f"[Network: Error - {e}]"


def get_security_alerts(hours: int = 24) -> List[Dict]:
    """
    Get recent security alerts from sentinel.

    Args:
        hours: How many hours back to look

    Returns:
        List of security event dicts
    """
    try:
        from pathlib import Path
        from datetime import datetime, timedelta

        try:
            from config.paths import get_state
            security_file = get_state("security_log")
        except ImportError:
            security_file = Path("/home/ai-core-node/aicore/database/security_log.json")
        if not security_file.exists():
            return []

        data = json.loads(security_file.read_text())
        events = data.get("events", [])

        # Filter by time
        cutoff = datetime.now() - timedelta(hours=hours)
        recent = []

        for e in events:
            try:
                ts = datetime.fromisoformat(e.get("timestamp", ""))
                if ts > cutoff and e.get("severity") in ("alert", "critical"):
                    recent.append(e)
            except:
                pass

        return recent

    except Exception as e:
        return []


# For Frank's context window
def get_context_block() -> str:
    """
    Get a formatted context block for Frank's prompt.

    Returns a concise summary suitable for injection into context.
    """
    if not is_available():
        return "[Sentinel: offline]"

    status = get_network_status()

    if status.get("gaming_mode"):
        return "[Sentinel: paused (gaming)]"

    lines = [f"[Sentinel: {'active' if status.get('running') else 'standby'}]"]

    # Add device count
    net_map = get_devices()
    lines.append(f"Network: {net_map.get('device_count', 0)} devices")

    # Add recent alerts
    alerts = get_security_alerts(24)
    if alerts:
        lines.append(f"Security alerts (24h): {len(alerts)}")
        for a in alerts[:2]:
            lines.append(f"  - {a.get('event_type', 'unknown')}: {a.get('description', '')[:50]}")

    return "\n".join(lines)


if __name__ == "__main__":
    print("Network Sentinel API Test")
    print("=" * 40)
    print(f"Available: {is_available()}")
    print()
    print("Status:")
    print(json.dumps(get_network_status(), indent=2))
    print()
    print("Summary:", get_network_summary())
    print()
    print("Context Block:")
    print(get_context_block())
