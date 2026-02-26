#!/usr/bin/env python3
"""
Frank Notification Daemon — Calendar & Todo Reminders.

Polls calendar events and todo deadlines, sends desktop notifications
via notify-send, and writes JSON files for overlay pickup.

Usage:
    python3 notification_daemon.py --daemon   # Run as daemon
    python3 notification_daemon.py --once     # Single check + exit
    python3 notification_daemon.py --status   # Show state
    python3 notification_daemon.py --debug    # Verbose single check

Author: Projekt Frankenstein
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# ── Paths & Config ────────────────────────────────────────────────

try:
    from config.paths import AICORE_ROOT
except ImportError:
    AICORE_ROOT = Path(__file__).resolve().parents[1]
try:
    from config.paths import get_runtime as _nd_get_runtime, TEMP_FILES as _nd_temp_files
    STATE_FILE = _nd_temp_files["notification_state"]
    PID_FILE = _nd_get_runtime("notification_daemon.pid")
    LOG_FILE = _nd_temp_files["notification_daemon_log"]
    NOTIFICATION_DIR = _nd_temp_files["notifications_dir"]
    GAMING_MODE_FILE = _nd_temp_files["gaming_mode_state"]
except ImportError:
    STATE_FILE = Path("/tmp/frank/notification_state.json")
    PID_FILE = Path(f"/run/user/{os.getuid()}/frank/notification_daemon.pid")
    LOG_FILE = Path("/tmp/frank/notification_daemon.log")
    NOTIFICATION_DIR = Path("/tmp/frank/notifications")
    GAMING_MODE_FILE = Path("/tmp/frank/gaming_mode_state.json")

CHECK_INTERVAL_SECONDS = 150   # 2.5 minutes
QUIET_HOURS_START = 23
QUIET_HOURS_END = 8
REMINDER_WINDOWS = [15, 5, 1]  # minutes before event
MAX_NOTIFICATIONS_PER_HOUR = 20
STATE_CLEANUP_HOURS = 24       # remove old dedup entries

# ── Logging ───────────────────────────────────────────────────────

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
# Handlers added in main() to avoid double logging under systemd
LOG = logging.getLogger("notification_daemon")

# ── Imports (lazy, from aicore tools) ─────────────────────────────

sys.path.insert(0, str(AICORE_ROOT))
sys.path.insert(0, str(AICORE_ROOT / "tools"))


def _check_calendar(minutes: int) -> List[dict]:
    """Check upcoming calendar events."""
    try:
        from tools.calendar_reader import check_upcoming
        result = check_upcoming(minutes=minutes)
        if result.get("ok"):
            return result.get("upcoming", [])
    except Exception as e:
        LOG.debug(f"Calendar check error: {e}")
    return []


def _check_todos(minutes: int) -> List[dict]:
    """Check due todos."""
    try:
        from tools.todo_store import get_due_todos
        result = get_due_todos(within_minutes=minutes)
        if result.get("ok"):
            return result.get("todos", [])
    except Exception as e:
        LOG.debug(f"Todo check error: {e}")
    return []



# ── Notification Delivery ─────────────────────────────────────────

def _send_desktop_notification(title: str, body: str, urgency: str = "normal"):
    """Send desktop notification via notify-send."""
    try:
        icon = "appointment-soon" if "calendar" in title.lower() else "task-due"
        cmd = [
            "/usr/bin/notify-send",
            "--app-name=Frank",
            f"--urgency={urgency}",
            f"--icon={icon}",
            "--expire-time=10000",
            title, body,
        ]
        env = {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
        subprocess.run(cmd, env=env, timeout=5, capture_output=True)
        LOG.info(f"Desktop notification sent: {title}")
    except Exception as e:
        LOG.warning(f"notify-send failed: {e}")


def _write_notification_json(notification: dict):
    """Write notification JSON file for overlay pickup."""
    NOTIFICATION_DIR.mkdir(parents=True, exist_ok=True)
    nid = notification.get("id", "unknown")
    ts = int(time.time())
    path = NOTIFICATION_DIR / f"{ts}_{nid}.json"
    try:
        path.write_text(json.dumps(notification, ensure_ascii=False, indent=2))
        LOG.debug(f"Notification JSON written: {path.name}")
    except Exception as e:
        LOG.warning(f"Notification JSON write failed: {e}")


def _determine_urgency(minutes_until: int) -> str:
    """Determine notification urgency based on time remaining."""
    if minutes_until <= 1:
        return "critical"
    if minutes_until <= 5:
        return "normal"
    return "low"


# ── Daemon ────────────────────────────────────────────────────────

class NotificationDaemon:
    """Polls calendar and todos, sends reminders."""

    def __init__(self, debug: bool = False):
        self._running = False
        self._shutdown_event = threading.Event()
        self._debug = debug
        self._state: dict = {}
        self._load_state()

    # ── State ─────────────────────────────────────────────────

    def _load_state(self):
        try:
            if STATE_FILE.exists():
                self._state = json.loads(STATE_FILE.read_text())
        except Exception:
            self._state = {}
        self._state.setdefault("notified_events", {})
        self._state.setdefault("notified_todos", {})
        self._state.setdefault("notifications_this_hour", 0)
        self._state.setdefault("hour_reset_ts", time.time())

    def _save_state(self):
        try:
            STATE_FILE.write_text(json.dumps(self._state, ensure_ascii=False, indent=2))
        except Exception as e:
            LOG.warning(f"State save failed: {e}")

    # ── Guardrails ────────────────────────────────────────────

    def _is_quiet_hours(self) -> bool:
        hour = datetime.now().hour
        if QUIET_HOURS_START <= hour or hour < QUIET_HOURS_END:
            return True
        return False

    def _is_gaming_mode(self) -> bool:
        try:
            if GAMING_MODE_FILE.exists():
                data = json.loads(GAMING_MODE_FILE.read_text())
                return data.get("active", False)
        except Exception:
            pass
        return False

    def _check_rate_limit(self) -> bool:
        """Returns True if we can still send notifications."""
        now = time.time()
        if now - self._state.get("hour_reset_ts", 0) > 3600:
            self._state["notifications_this_hour"] = 0
            self._state["hour_reset_ts"] = now
        return self._state["notifications_this_hour"] < MAX_NOTIFICATIONS_PER_HOUR

    def _cleanup_old_state(self):
        """Remove dedup entries older than STATE_CLEANUP_HOURS."""
        cutoff = (datetime.now() - timedelta(hours=STATE_CLEANUP_HOURS)).isoformat()
        for key_group in ("notified_events", "notified_todos"):
            old_keys = [
                k for k, v in self._state.get(key_group, {}).items()
                if v < cutoff
            ]
            for k in old_keys:
                del self._state[key_group][k]

    def _cleanup_old_notifications(self):
        """Remove notification JSON files older than 1 hour."""
        if not NOTIFICATION_DIR.exists():
            return
        cutoff = time.time() - 3600
        for f in NOTIFICATION_DIR.glob("*.json"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except Exception:
                pass

    # ── Core Check ────────────────────────────────────────────

    def _check_and_notify(self):
        """Main poll cycle: check calendar + todos, send notifications."""
        if not self._debug and self._is_quiet_hours():
            LOG.debug("Quiet hours active, skipping check")
            return
        if not self._debug and self._is_gaming_mode():
            LOG.debug("Gaming mode active, skipping check")
            return

        self._cleanup_old_state()
        self._cleanup_old_notifications()

        now_iso = datetime.now().isoformat()

        # ── Calendar Events ──
        for window in REMINDER_WINDOWS:
            if not self._check_rate_limit():
                break
            events = _check_calendar(window)
            for ev in events:
                uid = ev.get("uid", "")
                title = ev.get("title", "Appointment")
                minutes_until = ev.get("minutes_until", window)
                start_time = ev.get("start_iso", "?")

                dedup_key = f"cal_{uid}_{datetime.now().strftime('%Y-%m-%d')}_{window}"
                if dedup_key in self._state["notified_events"]:
                    continue

                # Format time display
                try:
                    t = datetime.fromisoformat(start_time)
                    time_str = t.strftime("%H:%M")
                except (ValueError, TypeError):
                    time_str = start_time

                urgency = _determine_urgency(minutes_until)
                body = f"In {minutes_until} minutes: {title} at {time_str}"
                if ev.get("location"):
                    body += f" ({ev['location']})"

                LOG.info(f"Calendar reminder: {body} (urgency={urgency})")

                _send_desktop_notification("Calendar Reminder", body, urgency)
                _write_notification_json({
                    "id": dedup_key,
                    "category": "calendar",
                    "title": title,
                    "body": body,
                    "urgency": urgency,
                    "timestamp": now_iso,
                    "source_uid": uid,
                    "minutes_until": minutes_until,
                    "read": False,
                })
                self._state["notified_events"][dedup_key] = now_iso
                self._state["notifications_this_hour"] = \
                    self._state.get("notifications_this_hour", 0) + 1

        # ── Due Todos ──
        if self._check_rate_limit():
            todos = _check_todos(15)
            for t in todos:
                tid = t.get("id", 0)
                content = t.get("content", "Task")
                due_date = t.get("due_date", "?")

                dedup_key = f"todo_{tid}_{datetime.now().strftime('%Y-%m-%d')}"
                if dedup_key in self._state["notified_todos"]:
                    continue

                # Format due time
                try:
                    dt = datetime.fromisoformat(due_date)
                    time_str = dt.strftime("%H:%M")
                    diff = (dt - datetime.now()).total_seconds() / 60
                    minutes_until = max(0, int(diff))
                except (ValueError, TypeError):
                    time_str = due_date
                    minutes_until = 15

                urgency = _determine_urgency(minutes_until)
                if minutes_until <= 0:
                    body = f"Overdue: {content} (due at {time_str})"
                else:
                    body = f"Due in {minutes_until} min: {content}"

                LOG.info(f"Todo reminder: {body} (urgency={urgency})")

                _send_desktop_notification("Todo Reminder", body, urgency)
                _write_notification_json({
                    "id": dedup_key,
                    "category": "todo",
                    "title": content[:60],
                    "body": body,
                    "urgency": urgency,
                    "timestamp": now_iso,
                    "source_id": tid,
                    "minutes_until": minutes_until,
                    "read": False,
                })
                self._state["notified_todos"][dedup_key] = now_iso
                self._state["notifications_this_hour"] = \
                    self._state.get("notifications_this_hour", 0) + 1

        # ── Proactive Notifications ──
        if self._check_rate_limit():
            try:
                from services.proactive_controller import ProactiveController
                if not hasattr(self, '_proactive'):
                    self._proactive = ProactiveController()

                for notif in self._proactive.check_all():
                    nid = notif.get("id", "")
                    if nid in self._state.get("notified_events", {}):
                        continue

                    _write_notification_json(notif)

                    if notif.get("urgency") in ("normal", "critical"):
                        _send_desktop_notification(
                            notif["title"], notif["body"], notif["urgency"])

                    self._state["notified_events"][nid] = now_iso
                    self._state["notifications_this_hour"] = \
                        self._state.get("notifications_this_hour", 0) + 1

                    if not self._check_rate_limit():
                        break
            except Exception as e:
                LOG.warning(f"Proactive check error: {e}")

        self._save_state()

    # ── Daemon Loop ───────────────────────────────────────────

    def run_once(self):
        """Single check and exit."""
        LOG.info("Running single check...")
        self._check_and_notify()
        LOG.info("Done.")

    def run_daemon(self):
        """Main daemon loop."""
        self._running = True

        # PID file
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()))

        # Signal handlers
        def _handle_stop(signum, frame):
            LOG.info(f"Received signal {signum}, shutting down...")
            self._running = False
            self._shutdown_event.set()

        signal.signal(signal.SIGTERM, _handle_stop)
        signal.signal(signal.SIGINT, _handle_stop)

        LOG.info("=" * 60)
        LOG.info("Frank Notification Daemon started")
        LOG.info(f"Check interval: {CHECK_INTERVAL_SECONDS}s")
        LOG.info(f"Reminder windows: {REMINDER_WINDOWS} min")
        LOG.info(f"Quiet hours: {QUIET_HOURS_START}:00 - {QUIET_HOURS_END}:00")
        LOG.info("=" * 60)

        while self._running and not self._shutdown_event.is_set():
            try:
                self._check_and_notify()
            except Exception as e:
                LOG.error(f"Check cycle error: {e}", exc_info=True)
            self._shutdown_event.wait(CHECK_INTERVAL_SECONDS)

        # Cleanup
        try:
            PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        LOG.info("Notification Daemon stopped.")

    def show_status(self):
        """Print current state."""
        self._load_state()
        print(json.dumps(self._state, ensure_ascii=False, indent=2))


# ── CLI ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Frank Notification Daemon")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon")
    parser.add_argument("--once", action="store_true", help="Single check")
    parser.add_argument("--status", action="store_true", help="Show state")
    parser.add_argument("--debug", action="store_true", help="Verbose check")
    args = parser.parse_args()

    level = logging.DEBUG if args.debug else logging.INFO
    fmt = "[%(asctime)s] %(levelname)s: %(message)s"
    if args.daemon:
        # Under systemd: file only (stdout goes to same file via systemd)
        logging.basicConfig(level=level, format=fmt,
                            handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8")])
    else:
        # Interactive: stdout + file
        logging.basicConfig(level=level, format=fmt,
                            handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"),
                                      logging.StreamHandler(sys.stdout)])

    daemon = NotificationDaemon(debug=args.debug)

    if args.status:
        daemon.show_status()
    elif args.once or args.debug:
        daemon.run_once()
    elif args.daemon:
        daemon.run_daemon()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
