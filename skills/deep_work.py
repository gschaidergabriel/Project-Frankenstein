"""Deep Work Tracker — Pomodoro / Focus session skill with notifications."""

import json
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

SKILL = {
    "name": "deep_work",
    "description": "Fokus-Sessions (Pomodoro) starten, pausieren und Statistik anzeigen.",
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
            "description": "Session-Dauer in Minuten (Standard: 25)",
            "required": False,
            "default": 25,
        },
        {
            "name": "label",
            "type": "string",
            "description": "Woran du arbeitest",
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

_STATE_FILE = Path("/tmp/frank_deep_work.json")
_HISTORY_FILE = Path("/tmp/frank_deep_work_history.json")
_NOTIFICATION_DIR = Path("/tmp/frank_notifications")

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
        "Fokus-Session beendet!",
        f"{minutes} Minuten geschafft! {label}" if label else f"{minutes} Minuten geschafft!",
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
                f"Bereits eine Session aktiv: \"{existing.get('label', '')}\" "
                f"({remaining:.0f} Min verbleibend). "
                f"Stoppe sie zuerst mit 'fokus stoppen'."
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

    parts = [f"Fokus-Session gestartet: **{minutes} Minuten**"]
    if label:
        parts.append(f"Aufgabe: {label}")
    parts.append(f"Ende um: {datetime.fromtimestamp(start_ts + minutes * 60).strftime('%H:%M')}")
    parts.append("Stoppen mit: *fokus stoppen*")

    return {"ok": True, "output": "\n".join(parts)}


def _stop_session() -> dict:
    """Stop active session early."""
    session = _load_active()
    if not session.get("active"):
        return {"ok": False, "error": "Keine aktive Fokus-Session."}

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
            f"Fokus-Session nach {elapsed_min:.0f} Minuten gestoppt.\n"
            f"(Geplant: {session['minutes']} Min)"
        ),
    }


def _get_status() -> dict:
    """Get current session status."""
    session = _load_active()
    if not session.get("active"):
        return {"ok": True, "output": "Keine aktive Fokus-Session.\nStarte eine mit: *fokus 25 minuten*"}

    elapsed = (time.time() - session["start_ts"]) / 60
    remaining = session["minutes"] - elapsed
    label = session.get("label", "")

    progress_pct = min(100, (elapsed / session["minutes"]) * 100)
    bar_len = 20
    filled = int(bar_len * progress_pct / 100)
    bar = "=" * filled + "-" * (bar_len - filled)

    lines = [
        f"**Fokus-Session aktiv**",
        f"[{bar}] {progress_pct:.0f}%",
        f"Verstrichen: {elapsed:.0f} Min / {session['minutes']} Min",
        f"Verbleibend: {remaining:.0f} Min",
    ]
    if label:
        lines.insert(1, f"Aufgabe: {label}")

    return {"ok": True, "output": "\n".join(lines)}


def _get_stats() -> dict:
    """Get session statistics."""
    history = _load_history()
    if not history:
        return {"ok": True, "output": "Noch keine Fokus-Sessions aufgezeichnet."}

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
        "**Deep Work Statistik**",
        f"Heute: {len(today_sessions)} Sessions, {today_minutes} Min",
        f"Gesamt: {total_sessions} Sessions, {total_minutes} Min",
        f"Abgeschlossen: {len(completed)}/{total_sessions}",
        f"Streak: {streak} Tage",
    ]

    # Last 5 sessions
    if history:
        lines.append("\n**Letzte Sessions:**")
        for s in history[-5:]:
            start = s.get("start", "?")
            try:
                start = datetime.fromisoformat(start).strftime("%d.%m. %H:%M")
            except (ValueError, TypeError):
                pass
            status = "abgeschlossen" if s.get("completed") else "abgebrochen"
            label = s.get("label", "")
            label_str = f" — {label}" if label else ""
            lines.append(f"  - {start}: {s.get('minutes', '?')} Min ({status}){label_str}")

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
