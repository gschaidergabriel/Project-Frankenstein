"""Notification mixin -- polls daemon notification directory and shows reminders in chat.

The notification_daemon.py writes JSON files to TEMP_DIR/notifications/.
This mixin picks them up and displays them as chat messages.
"""
from __future__ import annotations

import json
from pathlib import Path

from overlay.constants import LOG

try:
    from config.paths import TEMP_FILES as _TF_notif
    NOTIFICATION_DIR = _TF_notif["notifications_dir"]
except ImportError:
    NOTIFICATION_DIR = Path("/tmp/frank/notifications")
_NOTIFICATION_POLL_MS = 15_000  # 15 seconds


class NotificationMixin:
    """Polls notification JSON files from the daemon and shows them in chat."""

    def _notification_poll_timer(self):
        """Schedule periodic notification file checks."""
        try:
            self._io_q.put(("notification_check", {}))
        except Exception as e:
            LOG.warning(f"Notification poll error: {e}")
        self.after(_NOTIFICATION_POLL_MS, self._notification_poll_timer)

    def _do_notification_check_worker(self):
        """Check NOTIFICATION_DIR for new notification JSON files."""
        if not NOTIFICATION_DIR.exists():
            return

        if not hasattr(self, "_seen_notification_ids"):
            self._seen_notification_ids = set()

        for json_file in sorted(NOTIFICATION_DIR.glob("*.json")):
            try:
                data = json.loads(json_file.read_text())
                nid = data.get("id", "")
                if not nid or nid in self._seen_notification_ids:
                    continue

                # Already read by another overlay instance?
                if data.get("read"):
                    self._seen_notification_ids.add(nid)
                    continue

                self._seen_notification_ids.add(nid)

                category = data.get("category", "reminder")
                urgency = data.get("urgency", "normal")
                body = data.get("body", data.get("title", "Erinnerung"))

                icon_map = {
                    "calendar": "\U0001F4C5",       # calendar
                    "todo": "\U0001F4CB",            # clipboard
                    "meeting_prep": "\U0001F91D",    # handshake
                    "email_priority": "\U0001F4E8",  # envelope with arrow
                    "system_health": "\u26A0\uFE0F", # warning sign
                    "morning_briefing": "\u2600\uFE0F",  # sun
                    "download": "\U0001F4E5",        # inbox tray
                    "therapist": "\U0001F9D1\u200D\u2695\uFE0F",  # health worker
                    "mirror": "\U0001FA9E",                     # mirror
                }
                icon = icon_map.get(category, "\U0001F514")  # default: bell

                msg = f"{icon} {body}"
                is_system = urgency != "critical"
                sender = data.get("sender", "Frank")

                self._ui_call(
                    lambda m=msg, s=is_system, sn=sender: self._add_message(
                        sn, m, is_system=s,
                    )
                )

                # Mark as read
                data["read"] = True
                json_file.write_text(json.dumps(data, ensure_ascii=False))

            except Exception as e:
                LOG.warning(f"Notification file error: {e}")
