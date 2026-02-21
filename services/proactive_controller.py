"""
Frank Proactive Intelligence Controller.

Aggregates multiple context sources into intelligent, contextual notifications.
Called by notification_daemon.py during its poll cycle.

Sources:
- Morning Briefing: Calendar + Todos + Emails + Weather summary at day start
- Email Priority: Detect important/urgent unread emails
- System Health: CPU/RAM/disk threshold alerts
- Download Monitor: New file completion in ~/Downloads
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

try:
    from config.paths import AICORE_ROOT
except ImportError:
    AICORE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AICORE_ROOT))
sys.path.insert(0, str(AICORE_ROOT / "tools"))

LOG = logging.getLogger("proactive_controller")

# ── State ─────────────────────────────────────────────────────────

try:
    from config.paths import get_temp as _pc_get_temp
    _STATE_FILE = _pc_get_temp("proactive_state.json")
except ImportError:
    _STATE_FILE = Path("/tmp/frank/proactive_state.json")

# ── Thresholds ────────────────────────────────────────────────────

CPU_ALERT_THRESHOLD = 90        # % (load / cpu_count * 100)
RAM_ALERT_THRESHOLD = 85        # %
DISK_ALERT_THRESHOLD = 90       # %
HEALTH_COOLDOWN_S = 300         # 5 min between health alerts
EMAIL_COOLDOWN_S = 3600         # 1 hour between email priority alerts
DOWNLOAD_MIN_SIZE = 50_000      # 50 KB minimum
DOWNLOAD_MAX_AGE_S = 600        # 10 minutes

URGENCY_KEYWORDS = [
    "dringend", "urgent", "wichtig", "important",
    "deadline", "asap", "sofort", "critical",
    "eilt", "eilig", "priorität", "priority",
]

# Files to skip in Downloads
_PARTIAL_SUFFIXES = {".part", ".crdownload", ".tmp", ".download", ".aria2"}


class ProactiveController:
    """Generates intelligent, contextual proactive notifications."""

    def __init__(self):
        self._state = self._load_state()

    # ── State Persistence ─────────────────────────────────────

    def _load_state(self) -> dict:
        try:
            if _STATE_FILE.exists():
                return json.loads(_STATE_FILE.read_text())
        except Exception:
            pass
        return {
            "last_morning_briefing_date": "",
            "last_health_alert_ts": 0,
            "last_email_priority_ts": 0,
            "known_downloads": [],
        }

    def _save_state(self):
        try:
            _STATE_FILE.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2))
        except Exception as e:
            LOG.debug(f"Proactive state save failed: {e}")

    # ── Main Entry Point ──────────────────────────────────────

    def check_all(self) -> List[dict]:
        """Run all proactive checks. Returns list of notification dicts."""
        notifications = []

        try:
            briefing = self._check_morning_briefing()
            if briefing:
                notifications.append(briefing)
        except Exception as e:
            LOG.debug(f"Morning briefing error: {e}")

        try:
            notifications.extend(self._check_email_priority())
        except Exception as e:
            LOG.debug(f"Email priority error: {e}")

        try:
            notifications.extend(self._check_system_health())
        except Exception as e:
            LOG.debug(f"System health error: {e}")

        try:
            notifications.extend(self._check_new_downloads())
        except Exception as e:
            LOG.debug(f"Download monitor error: {e}")

        self._save_state()
        return notifications

    # ── 1. Morning Briefing ───────────────────────────────────

    def _check_morning_briefing(self) -> Optional[dict]:
        """Generate once-per-day morning briefing (6:00-11:00).

        Combines: today's calendar, pending todos, unread emails, weather.
        """
        today_str = datetime.now().strftime("%Y-%m-%d")
        if self._state.get("last_morning_briefing_date") == today_str:
            return None

        hour = datetime.now().hour
        if hour < 6 or hour > 11:
            return None

        parts = []

        # Calendar
        try:
            from tools.calendar_reader import list_events
            now = datetime.now()
            end = now.replace(hour=23, minute=59, second=59)
            result = list_events(start=now.isoformat(), end=end.isoformat())
            events = result.get("events", []) if result.get("ok") else []
            if events:
                parts.append(f"**{len(events)} appointments today**")
                for ev in events[:3]:
                    t = ev.get("start", "?")
                    try:
                        t = datetime.fromisoformat(t).strftime("%H:%M")
                    except (ValueError, TypeError):
                        pass
                    parts.append(f"  - {ev.get('title', '?')} at {t}")
            else:
                parts.append("No appointments today")
        except Exception:
            pass

        # Todos
        try:
            from tools.todo_store import list_todos
            result = list_todos(status="pending")
            todos = result.get("todos", []) if result.get("ok") else []
            if todos:
                due_today = [t for t in todos if self._is_due_today(t.get("due_date"))]
                if due_today:
                    parts.append(f"**{len(due_today)} tasks due today**")
                    for t in due_today[:3]:
                        parts.append(f"  - {t.get('content', '?')}")
                else:
                    parts.append(f"{len(todos)} open tasks")
        except Exception:
            pass

        # Unread emails
        try:
            from tools.email_reader import get_unread_count
            result = get_unread_count()
            if result and "error" not in result:
                total_unread = sum(v.get("unread", 0) for v in result.values())
                if total_unread > 0:
                    parts.append(f"**{total_unread} unread emails**")
        except Exception:
            pass

        # Weather
        try:
            from skills.weather import run as weather_run
            w = weather_run()
            if w.get("ok"):
                output = w.get("output", "")
                for line in output.split("\n"):
                    if "temperatur" in line.lower() or "°" in line:
                        parts.append(line.strip())
                        break
        except Exception:
            pass

        if not parts:
            return None

        self._state["last_morning_briefing_date"] = today_str

        body = "Good morning! Your day:\n" + "\n".join(parts)

        return {
            "id": f"morning_briefing_{today_str}",
            "category": "morning_briefing",
            "title": "Morning Briefing",
            "body": body,
            "urgency": "low",
            "timestamp": datetime.now().isoformat(),
            "read": False,
        }

    def _is_due_today(self, due_date_str: str) -> bool:
        if not due_date_str:
            return False
        try:
            dt = datetime.fromisoformat(due_date_str)
            return dt.date() == datetime.now().date()
        except (ValueError, TypeError):
            return False

    # ── 2. Email Priority ─────────────────────────────────────

    def _check_email_priority(self) -> List[dict]:
        """Check for high-priority unread emails.

        Priority criteria:
        - Subject contains urgency keywords (dringend, urgent, wichtig, etc.)
        - Multiple unread from same sender (>= 3)
        """
        # Rate limit
        if time.time() - self._state.get("last_email_priority_ts", 0) < EMAIL_COOLDOWN_S:
            return []

        try:
            from tools.email_reader import list_emails
            all_emails = list_emails(folder="INBOX", limit=30)
            if not all_emails or (len(all_emails) == 1 and "error" in all_emails[0]):
                return []

            # Filter to unread only
            emails = [e for e in all_emails if not e.get("read", True)]
            if not emails:
                return []
        except Exception:
            return []

        urgent_emails = []
        sender_counts: Dict[str, int] = {}

        for em in emails:
            sender = em.get("from", "").lower()
            subject = (em.get("subject", "") or "").lower()

            sender_counts[sender] = sender_counts.get(sender, 0) + 1

            if any(kw in subject for kw in URGENCY_KEYWORDS):
                urgent_emails.append(em)

        # Also flag senders with 3+ unread
        frequent_senders = [s for s, c in sender_counts.items() if c >= 3]

        if not urgent_emails and not frequent_senders:
            return []

        self._state["last_email_priority_ts"] = time.time()

        body_lines = []
        if urgent_emails:
            body_lines.append(f"**{len(urgent_emails)} urgent email(s):**")
            for em in urgent_emails[:3]:
                sender_short = em.get("from", "?").split("<")[0].strip()[:30]
                subject = (em.get("subject", "") or "(no subject)")[:50]
                body_lines.append(f"  - {sender_short}: {subject}")

        if frequent_senders:
            for s in frequent_senders[:2]:
                name = s.split("@")[0].replace(".", " ").title()[:25]
                body_lines.append(f"  - {sender_counts[s]} emails from {name}")

        return [{
            "id": f"email_priority_{datetime.now().strftime('%Y%m%d_%H')}",
            "category": "email_priority",
            "title": "Important Emails",
            "body": "\n".join(body_lines),
            "urgency": "normal",
            "timestamp": datetime.now().isoformat(),
            "read": False,
        }]

    # ── 3. System Health ──────────────────────────────────────

    def _check_system_health(self) -> List[dict]:
        """Check CPU, RAM, disk usage. Alert on thresholds."""
        if time.time() - self._state.get("last_health_alert_ts", 0) < HEALTH_COOLDOWN_S:
            return []

        notifications = []

        # CPU (from /proc/loadavg)
        try:
            loadavg_text = Path("/proc/loadavg").read_text()
            load_1min = float(loadavg_text.split()[0])
            cpu_count = os.cpu_count() or 1
            cpu_pct = (load_1min / cpu_count) * 100

            if cpu_pct > CPU_ALERT_THRESHOLD:
                top_proc = "?"
                try:
                    out = subprocess.run(
                        ["ps", "-eo", "comm", "--sort=-%cpu", "--no-headers"],
                        capture_output=True, text=True, timeout=3,
                    ).stdout
                    top_proc = out.split("\n")[0].strip() or "?"
                except Exception:
                    pass

                notifications.append({
                    "id": f"sys_cpu_{datetime.now().strftime('%Y%m%d_%H%M')}",
                    "category": "system_health",
                    "title": "High CPU Usage",
                    "body": f"CPU at {cpu_pct:.0f}% (Top: {top_proc})",
                    "urgency": "low",
                    "timestamp": datetime.now().isoformat(),
                    "read": False,
                })
        except Exception:
            pass

        # RAM (from /proc/meminfo)
        try:
            meminfo = Path("/proc/meminfo").read_text()
            mem_total = int(re.search(r"MemTotal:\s+(\d+)", meminfo).group(1))
            mem_avail = int(re.search(r"MemAvailable:\s+(\d+)", meminfo).group(1))
            ram_pct = ((mem_total - mem_avail) / mem_total) * 100

            if ram_pct > RAM_ALERT_THRESHOLD:
                free_mb = mem_avail // 1024
                notifications.append({
                    "id": f"sys_ram_{datetime.now().strftime('%Y%m%d_%H%M')}",
                    "category": "system_health",
                    "title": "High RAM Usage",
                    "body": f"RAM at {ram_pct:.0f}% ({free_mb} MB free)",
                    "urgency": "normal" if ram_pct > 95 else "low",
                    "timestamp": datetime.now().isoformat(),
                    "read": False,
                })
        except Exception:
            pass

        # Disk (os.statvfs)
        try:
            stat = os.statvfs("/")
            disk_total = stat.f_blocks * stat.f_frsize
            disk_free = stat.f_bavail * stat.f_frsize
            disk_pct = ((disk_total - disk_free) / disk_total) * 100

            if disk_pct > DISK_ALERT_THRESHOLD:
                free_gb = disk_free / (1024 ** 3)
                notifications.append({
                    "id": f"sys_disk_{datetime.now().strftime('%Y%m%d')}",
                    "category": "system_health",
                    "title": "Low Disk Space",
                    "body": f"Disk {disk_pct:.0f}% full ({free_gb:.1f} GB free)",
                    "urgency": "normal",
                    "timestamp": datetime.now().isoformat(),
                    "read": False,
                })
        except Exception:
            pass

        if notifications:
            self._state["last_health_alert_ts"] = time.time()

        return notifications

    # ── 4. Download Monitor ───────────────────────────────────

    def _check_new_downloads(self) -> List[dict]:
        """Check ~/Downloads for new large files completed since last check."""
        downloads_dir = Path.home() / "Downloads"
        if not downloads_dir.exists():
            return []

        known = set(self._state.get("known_downloads", []))
        notifications = []
        current_files = []

        try:
            for f in downloads_dir.iterdir():
                if not f.is_file():
                    continue
                if f.suffix.lower() in _PARTIAL_SUFFIXES:
                    continue

                name = f.name

                if name in known:
                    current_files.append(name)
                    continue

                try:
                    fstat = f.stat()
                except OSError:
                    continue

                if fstat.st_size < DOWNLOAD_MIN_SIZE:
                    continue

                age_s = time.time() - fstat.st_mtime
                if age_s > DOWNLOAD_MAX_AGE_S:
                    # Too old — don't add to known so it can be picked up
                    # if the file gets re-downloaded (new mtime)
                    continue

                size_mb = fstat.st_size / (1024 * 1024)
                notifications.append({
                    "id": f"download_{name}_{int(fstat.st_mtime)}",
                    "category": "download",
                    "title": "Download complete",
                    "body": f"{name} ({size_mb:.1f} MB)",
                    "filepath": str(f),
                    "urgency": "low",
                    "timestamp": datetime.now().isoformat(),
                    "read": False,
                })
                current_files.append(name)

            # Keep only notified + previously known files
            self._state["known_downloads"] = current_files[-100:]

        except Exception as e:
            LOG.debug(f"Download check error: {e}")

        return notifications
