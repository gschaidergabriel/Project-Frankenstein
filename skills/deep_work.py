"""Deep Work Tracker — Pomodoro / Focus session skill with notifications."""

import json
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

SKILL = {
    "name": "deep_work",
    "description": "Start, pause, and show statistics for focus sessions (Pomodoro).",
    "version": "1.0",
    "category": "productivity",
    "risk_level": 0.0,
    "parameters": [
        {
            "name": "action",
            "type": "string",
            "description": "start | stop | status | stats",
            "required": False,
            "default": "start",
        },
        {
            "name": "minutes",
            "type": "number",
            "description": "Session duration in minutes (default: 25)",
            "required": False,
            "default": 25,
        },
        {
            "name": "label",
            "type": "string",
            "description": "What you are working on",
            "required": False,
            "default": "",
        },
    ],
    "keywords": [
        "deep work", "fokus", "focus", "pomodoro",
        "fokus session", "fokussession", "konzentration",
        "deep work starten", "fokus starten", "pomodoro starten",
        "fokus stoppen", "fokus status", "fokus statistik",
    ],
    "timeout_s": 5.0,
}

# ── State ────────────────────────────────────────────────────────

try:
    from config.paths import get_temp as _dw_get_temp
    _STATE_FILE = _dw_get_temp("deep_work.json")
    _HISTORY_FILE = _dw_get_temp("deep_work_history.json")
    _NOTIFICATION_DIR = _dw_get_temp("notifications")
except ImportError:
    import tempfile as _dw_tempfile
    _dw_tmp = Path(_dw_tempfile.gettempdir()) / "frank"
    _dw_tmp.mkdir(parents=True, exist_ok=True)
    _STATE_FILE = _dw_tmp / "deep_work.json"
    _HISTORY_FILE = _dw_tmp / "deep_work_history.json"
    _NOTIFICATION_DIR = _dw_tmp / "notifications"

_active_session: dict = {}
_session_lock = threading.Lock()


def _load_active() -> dict:
    """Load active session from state file."""
    try:
        if _STATE_FILE.exists():
            data = json.loads(_STATE_FILE.read_text())
            if data.get("active"):
                return data
    except Exception:
        pass
    return {}


def _save_active(session: dict):
    """Save active session state."""
    try:
        _STATE_FILE.write_text(json.dumps(session, ensure_ascii=False, indent=2))
    except Exception:
        pass


def _clear_active():
    """Remove active session state."""
    try:
        _STATE_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _append_history(entry: dict):
    """Append completed session to history."""
    history = []
    try:
        if _HISTORY_FILE.exists():
            history = json.loads(_HISTORY_FILE.read_text())
    except Exception:
        pass

    history.append(entry)
    # Keep last 100 sessions
    history = history[-100:]

    try:
        _HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2))
    except Exception:
        pass


def _load_history() -> list:
    """Load session history."""
    try:
        if _HISTORY_FILE.exists():
            return json.loads(_HISTORY_FILE.read_text())
    except Exception:
        pass
    return []


# ── Notifications ────────────────────────────────────────────────

def _notify(title: str, body: str, urgency: str = "normal"):
    """Send desktop notification + overlay notification."""
    # Desktop
    try:
        import os
        env = {**os.environ, "DISPLAY": ":0"}
        subprocess.run(
            ["notify-send", "--app-name=Frank", f"--urgency={urgency}",
             "--icon=appointment-soon", "--expire-time=10000", title, body],
            env=env, timeout=5, capture_output=True,
        )
    except Exception:
        pass

    # Overlay via JSON file
    try:
        _NOTIFICATION_DIR.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        nid = f"deep_work_{ts}"
        notif = {
            "id": nid,
            "category": "todo",
            "title": title,
            "body": body,
            "urgency": urgency,
            "timestamp": datetime.now().isoformat(),
            "read": False,
        }
        path = _NOTIFICATION_DIR / f"{ts}_{nid}.json"
        path.write_text(json.dumps(notif, ensure_ascii=False, indent=2))
    except Exception:
        pass


# ── Session Timer Thread ─────────────────────────────────────────

def _session_thread(minutes: int, label: str, start_ts: float):
    """Background thread: wait for session end, then notify."""
    total_seconds = minutes * 60
    elapsed = 0

    while elapsed < total_seconds:
        time.sleep(min(30, total_seconds - elapsed))
        elapsed = time.time() - start_ts

        # Check if session was stopped early
        session = _load_active()
        if not session.get("active"):
            return

    # Session complete
    _notify(
        "Focus session completed!",
        f"{minutes} minutes done! {label}" if label else f"{minutes} minutes done!",
        "critical",
    )

    # Record to history
    _append_history({
        "start": datetime.fromtimestamp(start_ts).isoformat(),
        "end": datetime.now().isoformat(),
        "minutes": minutes,
        "label": label,
        "completed": True,
    })

    _clear_active()


# ── Actions ──────────────────────────────────────────────────────

def _start_session(minutes: int, label: str) -> dict:
    """Start a new focus session."""
    existing = _load_active()
    if existing.get("active"):
        elapsed = (time.time() - existing["start_ts"]) / 60
        remaining = existing["minutes"] - elapsed
        return {
            "ok": False,
            "error": (
                f"Already a session active: \"{existing.get('label', '')}\" "
                f"({remaining:.0f} min remaining). "
                f"Stop it first with 'focus stop'."
            ),
        }

    start_ts = time.time()
    session = {
        "active": True,
        "start_ts": start_ts,
        "start_iso": datetime.now().isoformat(),
        "minutes": minutes,
        "label": label,
    }
    _save_active(session)

    # Start background timer
    t = threading.Thread(
        target=_session_thread, args=(minutes, label, start_ts), daemon=True,
    )
    t.start()

    parts = [f"Focus session started: **{minutes} minutes**"]
    if label:
        parts.append(f"Task: {label}")
    parts.append(f"Ends at: {datetime.fromtimestamp(start_ts + minutes * 60).strftime('%H:%M')}")
    parts.append("Stop with: *focus stop*")

    return {"ok": True, "output": "\n".join(parts)}


def _stop_session() -> dict:
    """Stop active session early."""
    session = _load_active()
    if not session.get("active"):
        return {"ok": False, "error": "No active focus session."}

    elapsed_min = (time.time() - session["start_ts"]) / 60
    label = session.get("label", "")

    # Record partial session
    _append_history({
        "start": session.get("start_iso", ""),
        "end": datetime.now().isoformat(),
        "minutes": round(elapsed_min, 1),
        "planned_minutes": session["minutes"],
        "label": label,
        "completed": False,
    })

    _clear_active()

    return {
        "ok": True,
        "output": (
            f"Focus session stopped after {elapsed_min:.0f} minutes.\n"
            f"(Planned: {session['minutes']} min)"
        ),
    }


def _get_status() -> dict:
    """Get current session status."""
    session = _load_active()
    if not session.get("active"):
        return {"ok": True, "output": "No active focus session.\nStart one with: *focus 25 minutes*"}

    elapsed = (time.time() - session["start_ts"]) / 60
    remaining = session["minutes"] - elapsed
    label = session.get("label", "")

    progress_pct = min(100, (elapsed / session["minutes"]) * 100)
    bar_len = 20
    filled = int(bar_len * progress_pct / 100)
    bar = "=" * filled + "-" * (bar_len - filled)

    lines = [
        f"**Focus session active**",
        f"[{bar}] {progress_pct:.0f}%",
        f"Elapsed: {elapsed:.0f} min / {session['minutes']} min",
        f"Remaining: {remaining:.0f} min",
    ]
    if label:
        lines.insert(1, f"Task: {label}")

    return {"ok": True, "output": "\n".join(lines)}


def _get_stats() -> dict:
    """Get session statistics."""
    history = _load_history()
    if not history:
        return {"ok": True, "output": "No focus sessions recorded yet."}

    total_sessions = len(history)
    completed = [s for s in history if s.get("completed")]
    total_minutes = sum(s.get("minutes", 0) for s in history)
    completed_minutes = sum(s.get("minutes", 0) for s in completed)

    # Today's stats
    today = datetime.now().strftime("%Y-%m-%d")
    today_sessions = [s for s in history if s.get("start", "").startswith(today)]
    today_minutes = sum(s.get("minutes", 0) for s in today_sessions)

    # Streak: consecutive days with at least one session
    dates = sorted(set(
        s.get("start", "")[:10] for s in history if s.get("start", "")
    ), reverse=True)
    streak = 0
    check_date = datetime.now().date()
    for d_str in dates:
        try:
            d = datetime.strptime(d_str, "%Y-%m-%d").date()
            if d == check_date:
                streak += 1
                check_date = check_date.replace(day=check_date.day - 1)
            else:
                break
        except (ValueError, AttributeError):
            break

    lines = [
        "**Deep Work Statistics**",
        f"Today: {len(today_sessions)} sessions, {today_minutes} min",
        f"Total: {total_sessions} sessions, {total_minutes} min",
        f"Completed: {len(completed)}/{total_sessions}",
        f"Streak: {streak} days",
    ]

    # Last 5 sessions
    if history:
        lines.append("\n**Recent sessions:**")
        for s in history[-5:]:
            start = s.get("start", "?")
            try:
                start = datetime.fromisoformat(start).strftime("%d.%m. %H:%M")
            except (ValueError, TypeError):
                pass
            status = "completed" if s.get("completed") else "cancelled"
            label = s.get("label", "")
            label_str = f" — {label}" if label else ""
            lines.append(f"  - {start}: {s.get('minutes', '?')} min ({status}){label_str}")

    return {"ok": True, "output": "\n".join(lines)}


# ── Entry Point ──────────────────────────────────────────────────

def run(action: str = "start", minutes: int = 25, label: str = "",
        user_query: str = "", **kwargs) -> dict:
    """Handle deep work / focus session commands."""
    import re

    query = (user_query or "").lower().strip()

    # Detect action from query
    if any(w in query for w in ("stopp", "stop", "beende", "abbrech")):
        action = "stop"
    elif any(w in query for w in ("status", "laeuft", "aktiv")):
        action = "status"
    elif any(w in query for w in ("statistik", "stats", "history", "verlauf", "uebersicht")):
        action = "stats"
    else:
        action = "start"

    # Parse minutes from query
    if action == "start" and query:
        m = re.search(r"(\d+)\s*(?:minuten?|min|m)\b", query)
        if m:
            minutes = int(m.group(1))
        elif "eine stunde" in query or "einer stunde" in query:
            minutes = 60
        elif "45" in query:
            minutes = 45

        # Parse label: "fokus auf X" / "fokus fuer X"
        lm = re.search(r"(?:auf|fuer|für|an|wegen)\s+(.+?)(?:\s+\d+\s*min|\s*$)", query)
        if lm:
            label = lm.group(1).strip().rstrip(".")

    # Clamp minutes
    if minutes < 1:
        minutes = 1
    elif minutes > 240:
        minutes = 240

    # Dispatch
    if action == "stop":
        return _stop_session()
    elif action == "status":
        return _get_status()
    elif action == "stats":
        return _get_stats()
    else:
        return _start_session(minutes, label)
