"""Timer skill — set a countdown with desktop notification."""

import re
import subprocess
import threading

SKILL = {
    "name": "timer",
    "description": "Set a countdown timer with desktop notification.",
    "version": "1.0",
    "category": "utility",
    "risk_level": 0.0,
    "parameters": [
        {
            "name": "seconds",
            "type": "number",
            "description": "Timer duration in seconds",
            "required": False,
            "default": 0,
        },
        {
            "name": "label",
            "type": "string",
            "description": "Description (e.g. 'Tea ready')",
            "required": False,
            "default": "Timer expired",
        },
    ],
    "keywords": [
        "timer", "wecker", "erinner mich", "countdown",
        "in 5 minuten", "in 10 minuten", "in einer minute",
    ],
    "timeout_s": 5.0,  # Only for setup, timer runs in background
}

# Track active timers
_active_timers: list = []


def _parse_duration(text: str) -> int:
    """Parse natural language duration to seconds."""
    text = text.lower()
    total = 0

    # "X stunde(n)" / "X hour(s)"
    m = re.search(r"(\d+)\s*(?:stunden?|hours?|h)\b", text)
    if m:
        total += int(m.group(1)) * 3600

    # "X minute(n)" / "X min"
    m = re.search(r"(\d+)\s*(?:minuten?|min|m)\b", text)
    if m:
        total += int(m.group(1)) * 60

    # "X sekunde(n)" / "X sec"
    m = re.search(r"(\d+)\s*(?:sekunden?|seconds?|sek|sec|s)\b", text)
    if m:
        total += int(m.group(1))

    # "einer minute" / "eine stunde"
    if "einer minute" in text or "eine minute" in text:
        total += 60
    if "einer stunde" in text or "eine stunde" in text:
        total += 3600

    # Bare number without unit → minutes
    if total == 0:
        m = re.search(r"(\d+)", text)
        if m:
            total = int(m.group(1)) * 60

    return total


def _timer_thread(seconds: int, label: str):
    """Background thread that sleeps and then sends notification."""
    import time
    time.sleep(seconds)

    # Desktop notification via notify-send
    try:
        subprocess.run(
            ["notify-send", "-u", "critical", "-t", "10000",
             "Frank Timer", label],
            timeout=5,
        )
    except Exception:
        pass

    # Also write to signal file for Frank overlay to pick up
    try:
        from pathlib import Path
        import json
        try:
            from config.paths import get_temp as _t_get_temp
            signal = _t_get_temp("timer_done.json")
        except ImportError:
            import tempfile as _t_tempfile
            signal = Path(_t_tempfile.gettempdir()) / "frank" / "timer_done.json"
        signal.write_text(json.dumps({
            "label": label,
            "seconds": seconds,
            "timestamp": time.time(),
        }))
    except Exception:
        pass


def run(seconds: int = 0, label: str = "Timer expired",
        user_query: str = "", **kwargs) -> dict:
    """Set a countdown timer."""
    # Parse duration from query if not given directly
    if not seconds and user_query:
        seconds = _parse_duration(user_query)

    if not seconds:
        return {"ok": False, "error": "No duration recognized. Example: 'timer 5 minutes'"}

    if seconds > 86400:
        return {"ok": False, "error": "Maximum duration: 24 hours"}

    # Extract label from query if default
    if label == "Timer expired" and user_query:
        # Try to find purpose: "erinner mich X zu Y"
        m = re.search(r"(?:fuer|für|zu|an|wegen)\s+(.+?)(?:\s+in\s+\d|\s*$)", user_query)
        if m:
            label = m.group(1).strip().rstrip(".")

    # Format duration for display
    if seconds >= 3600:
        display = f"{seconds // 3600}h {(seconds % 3600) // 60}min"
    elif seconds >= 60:
        display = f"{seconds // 60} minutes"
    else:
        display = f"{seconds} seconds"

    # Start background timer
    t = threading.Thread(target=_timer_thread, args=(seconds, label), daemon=True)
    t.start()
    _active_timers.append({"seconds": seconds, "label": label, "thread": t})

    return {
        "ok": True,
        "output": f"Timer set: {display}\nNotification: \"{label}\"",
    }
