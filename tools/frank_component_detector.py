#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
"""
Frank Component Detector - Erkennt Franks eigene UI-Komponenten auf dem Desktop.

Nutzt wmctrl und pgrep um Franks sichtbare Fenster und Prozesse zu identifizieren.
Wird von VCB genutzt um Self-Awareness in die Bildanalyse einzubringen.

Usage:
    from tools.frank_component_detector import detect_frank_components
    result = detect_frank_components()
    # result = {
    #     "frank_components": [...],
    #     "other_windows": [...],
    #     "monitor_count": 1,
    #     "monitors": [...],
    #     "summary": "Dein Chat-Overlay ist sichtbar..."
    # }
"""

import logging
import re
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

LOG = logging.getLogger("frank.component_detector")

# Known Frank component signatures
# Each entry: (process_pattern, window_title_pattern, display_name, description)
FRANK_SIGNATURES = [
    {
        "process_patterns": ["chat_overlay.py"],
        "title_patterns": [r"F\.R\.A\.N\.K\.", r"^Frank$", r"Frank Chat"],
        "name": "Chat-Overlay",
        "description": "Franks Chat-Fenster fuer Benutzer-Interaktion",
    },
    {
        "process_patterns": ["adi_popup", "main_window.py"],
        "title_patterns": [r"ADI", r"Display.*Setup", r"Monitor.*Config"],
        "name": "ADI Display Intelligence Popup",
        "description": "Franks Display-Konfigurations-Tool",
    },
    {
        "process_patterns": ["tray_indicator.py"],
        "title_patterns": [],
        "name": "System-Tray Indicator",
        "description": "Franks System-Tray-Icon fuer Schnellzugriff",
    },
]


@dataclass
class WindowInfo:
    """Information about a detected window."""
    window_id: str
    title: str
    x: int
    y: int
    width: int
    height: int
    is_frank: bool
    frank_component_name: str = ""
    frank_component_desc: str = ""
    monitor_index: int = 0


@dataclass
class MonitorLayout:
    """Basic monitor layout info for component placement."""
    name: str
    x: int
    y: int
    width: int
    height: int
    is_primary: bool


def _get_monitors() -> List[MonitorLayout]:
    """Get monitor layout via xrandr (lightweight, no EDID)."""
    monitors = []
    try:
        result = subprocess.run(
            ["xrandr", "--query"],
            capture_output=True, text=True, timeout=5,
            env={"DISPLAY": os.environ.get("DISPLAY", ":0"), "PATH": "/usr/bin:/bin"}
        )
        if result.returncode != 0:
            return monitors

        for line in result.stdout.split('\n'):
            match = re.match(
                r'^(\S+)\s+connected\s*(primary)?\s*(\d+)x(\d+)\+(\d+)\+(\d+)',
                line
            )
            if match:
                monitors.append(MonitorLayout(
                    name=match.group(1),
                    x=int(match.group(5)),
                    y=int(match.group(6)),
                    width=int(match.group(3)),
                    height=int(match.group(4)),
                    is_primary=match.group(2) == "primary",
                ))
    except Exception as e:
        LOG.debug(f"xrandr failed: {e}")

    return monitors


def _get_window_monitor(win_x: int, win_y: int, monitors: List[MonitorLayout]) -> int:
    """Determine which monitor a window is on based on its position."""
    if not monitors:
        return 0

    for i, mon in enumerate(monitors):
        if (mon.x <= win_x < mon.x + mon.width and
                mon.y <= win_y < mon.y + mon.height):
            return i

    # Fallback: closest monitor
    return 0


def _get_frank_processes() -> Dict[str, str]:
    """Get running Frank processes. Returns {pattern: cmdline}."""
    found = {}
    try:
        result = subprocess.run(
            ["pgrep", "-a", "python3"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                for sig in FRANK_SIGNATURES:
                    for pattern in sig["process_patterns"]:
                        if pattern in line:
                            found[pattern] = line
    except Exception as e:
        LOG.debug(f"pgrep failed: {e}")

    return found


def _get_windows() -> List[dict]:
    """Get all windows via wmctrl."""
    windows = []
    try:
        result = subprocess.run(
            ["wmctrl", "-l", "-G"],
            capture_output=True, text=True, timeout=5,
            env={"DISPLAY": os.environ.get("DISPLAY", ":0"), "PATH": "/usr/bin:/bin"}
        )
        if result.returncode != 0:
            return windows

        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            # Format: 0xWINID DESKTOP X Y W H HOSTNAME TITLE...
            parts = line.split(None, 7)
            if len(parts) < 8:
                continue

            windows.append({
                "id": parts[0],
                "desktop": parts[1],
                "x": int(parts[2]),
                "y": int(parts[3]),
                "width": int(parts[4]),
                "height": int(parts[5]),
                "host": parts[6],
                "title": parts[7] if len(parts) > 7 else "",
            })
    except Exception as e:
        LOG.debug(f"wmctrl failed: {e}")

    return windows


def _match_window_to_frank(title: str, frank_processes: Dict[str, str]) -> Optional[dict]:
    """Try to match a window to a known Frank component."""
    for sig in FRANK_SIGNATURES:
        # Check title patterns
        for pattern in sig["title_patterns"]:
            if re.search(pattern, title, re.IGNORECASE):
                return sig

        # Check if associated process is running
        for proc_pattern in sig["process_patterns"]:
            if proc_pattern in frank_processes:
                # Process is running - check if title could be this component
                # For wallpaper: always matches if process runs (desktop=-1)
                if "wallpaper" in sig["name"].lower() or "tray" in sig["name"].lower():
                    continue  # These are matched by title, not loosely
    return None


def detect_frank_components() -> dict:
    """
    Detect Frank's visible UI components and other windows on the desktop.

    Returns:
        dict with keys:
        - frank_components: list of detected Frank components
        - other_windows: list of non-Frank windows
        - monitor_count: number of connected monitors
        - monitors: list of monitor info dicts
        - summary: human-readable summary string (German)
    """
    monitors = _get_monitors()
    frank_processes = _get_frank_processes()
    windows = _get_windows()

    frank_components = []
    other_windows = []

    for win in windows:
        title = win["title"]
        mon_idx = _get_window_monitor(win["x"], win["y"], monitors)

        # Try title-based matching first
        matched_sig = None
        for sig in FRANK_SIGNATURES:
            for pattern in sig["title_patterns"]:
                if re.search(pattern, title, re.IGNORECASE):
                    matched_sig = sig
                    break
            if matched_sig:
                break

        # For desktop=-1 windows, check if they're wallpaper
        if not matched_sig and win["desktop"] == "-1":
            if "NEURAL CORE" in title.upper() or "NEC" in title.upper():
                for sig in FRANK_SIGNATURES:
                    if "Wallpaper" in sig["name"]:
                        matched_sig = sig
                        break

        if matched_sig:
            frank_components.append({
                "name": matched_sig["name"],
                "description": matched_sig["description"],
                "title": title,
                "position": {"x": win["x"], "y": win["y"],
                             "width": win["width"], "height": win["height"]},
                "monitor": mon_idx,
                "monitor_name": monitors[mon_idx].name if mon_idx < len(monitors) else "unknown",
            })
        else:
            # Skip desktop/root windows and system internals
            if not title or title in ("Desktop", "N/A") or win["desktop"] == "-1":
                # Special check for the Frank overlay which sometimes has N/A host
                if "F.R.A.N.K." in title:
                    for sig in FRANK_SIGNATURES:
                        if sig["name"] == "Chat-Overlay":
                            frank_components.append({
                                "name": sig["name"],
                                "description": sig["description"],
                                "title": title,
                                "position": {"x": win["x"], "y": win["y"],
                                             "width": win["width"], "height": win["height"]},
                                "monitor": mon_idx,
                                "monitor_name": monitors[mon_idx].name if mon_idx < len(monitors) else "unknown",
                            })
                            break
                    else:
                        continue
                else:
                    continue

            other_windows.append({
                "title": title,
                "position": {"x": win["x"], "y": win["y"],
                             "width": win["width"], "height": win["height"]},
                "monitor": mon_idx,
            })

    # Also check for running Frank processes that might not have visible windows
    for sig in FRANK_SIGNATURES:
        already_found = any(c["name"] == sig["name"] for c in frank_components)
        if not already_found:
            for proc_pattern in sig["process_patterns"]:
                if proc_pattern in frank_processes:
                    frank_components.append({
                        "name": sig["name"],
                        "description": sig["description"],
                        "title": "(Prozess laeuft, kein sichtbares Fenster)",
                        "position": None,
                        "monitor": -1,
                        "monitor_name": "background",
                    })
                    break

    # Build monitor info
    monitor_info = []
    for i, mon in enumerate(monitors):
        monitor_info.append({
            "index": i,
            "name": mon.name,
            "resolution": f"{mon.width}x{mon.height}",
            "position": f"+{mon.x}+{mon.y}",
            "primary": mon.is_primary,
        })

    # Build summary
    summary_parts = []
    if monitors:
        summary_parts.append(f"{len(monitors)} Monitor(e) angeschlossen")

    if frank_components:
        names = [c["name"] for c in frank_components]
        summary_parts.append(f"Eigene Komponenten sichtbar: {', '.join(names)}")

    if other_windows:
        titles = [w["title"][:40] for w in other_windows[:5]]
        summary_parts.append(f"Andere Fenster: {', '.join(titles)}")

    return {
        "frank_components": frank_components,
        "other_windows": other_windows,
        "monitor_count": len(monitors),
        "monitors": monitor_info,
        "summary": ". ".join(summary_parts) if summary_parts else "Keine Fenster erkannt",
    }


def get_self_awareness_context() -> str:
    """
    Generate a self-awareness context string for the VCB vision prompt.

    Returns a German text block describing Frank's visible components
    and monitor setup, ready to inject into the vision model prompt.
    """
    data = detect_frank_components()

    lines = []

    # Monitor info
    if data["monitors"]:
        if len(data["monitors"]) == 1:
            mon = data["monitors"][0]
            lines.append(f"MONITOR-SETUP: 1 Monitor ({mon['name']}, {mon['resolution']})")
        else:
            lines.append(f"MONITOR-SETUP: {len(data['monitors'])} Monitore:")
            for mon in data["monitors"]:
                primary = " [PRIMARY]" if mon["primary"] else ""
                lines.append(f"  - {mon['name']}: {mon['resolution']}{primary}")

    # Frank's own components
    if data["frank_components"]:
        lines.append("")
        lines.append("DEINE EIGENEN SICHTBAREN KOMPONENTEN (das bist DU):")
        for comp in data["frank_components"]:
            pos_str = ""
            if comp["position"]:
                p = comp["position"]
                pos_str = f" bei Position ({p['x']},{p['y']}) Groesse {p['width']}x{p['height']}"
            lines.append(f"  - {comp['name']}: {comp['description']}{pos_str}")

    # Other windows for context
    if data["other_windows"]:
        lines.append("")
        lines.append("ANDERE SICHTBARE FENSTER:")
        for win in data["other_windows"][:5]:
            lines.append(f"  - {win['title'][:60]}")

    return "\n".join(lines)


# CLI for testing
if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.DEBUG)

    print("=== Frank Component Detector ===\n")

    result = detect_frank_components()
    print(f"Monitors: {result['monitor_count']}")
    for mon in result["monitors"]:
        print(f"  {mon['name']}: {mon['resolution']} {'[PRIMARY]' if mon['primary'] else ''}")

    print(f"\nFrank Components ({len(result['frank_components'])}):")
    for comp in result["frank_components"]:
        pos = comp["position"]
        pos_str = f"({pos['x']},{pos['y']} {pos['width']}x{pos['height']})" if pos else "(background)"
        print(f"  {comp['name']}: {pos_str}")
        print(f"    Title: {comp['title']}")

    print(f"\nOther Windows ({len(result['other_windows'])}):")
    for win in result["other_windows"]:
        print(f"  {win['title'][:60]}")

    print(f"\nSummary: {result['summary']}")

    print("\n=== Self-Awareness Context ===")
    print(get_self_awareness_context())
