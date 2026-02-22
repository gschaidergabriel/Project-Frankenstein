"""Notification mixin -- polls daemon notification directory and shows reminders in chat.

The notification_daemon.py writes JSON files to TEMP_DIR/notifications/.
This mixin picks them up and displays them as chat messages.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from overlay.constants import COLORS, LOG

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

                # Truncate long notifications to max 15 words
                # (entity agents already truncate, but daemon/proactive don't)
                words = body.split()
                if len(words) > 15:
                    body = " ".join(words[:15]) + " …"

                icon_map = {
                    "calendar": "\U0001F4C5",       # calendar
                    "todo": "\U0001F4CB",            # clipboard
                    "meeting_prep": "\U0001F91D",    # handshake
                    "email_priority": "\U0001F4E8",  # envelope with arrow
                    "system_health": "\u26A0\uFE0F", # warning sign
                    "morning_briefing": "\u2600\uFE0F",  # sun
                    "download": "\U0001F4E5",        # inbox tray
                    "therapist": "\U0001F49A",       # green heart (Dr. Hibbert)
                    "mirror": "\u2694\uFE0F",         # crossed swords (Kairos)
                    "atlas": "\U0001F9ED",            # compass (Atlas)
                    "muse": "\U0001F3A8",             # palette (Echo)
                }
                icon = icon_map.get(category, "\U0001F514")  # default: bell

                msg = f"{icon} {body}"
                is_system = urgency != "critical"
                sender = data.get("sender", "Frank")
                filepath = data.get("filepath", "")

                if category == "download" and filepath:
                    self._ui_call(
                        lambda m=msg, s=is_system, sn=sender, fp=filepath:
                            self._add_download_message(sn, m, fp, is_system=s)
                    )
                else:
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

    def _add_download_message(self, sender: str, msg: str, filepath: str, is_system: bool = True):
        """Add a download notification with clickable filename that opens the folder."""
        import tkinter as tk
        from overlay.widgets.message_bubble import MessageBubble

        bubble = MessageBubble(
            self.messages_frame,
            sender=sender,
            message=msg,
            is_user=False,
            is_system=is_system,
        )
        bubble.pack(fill="x", anchor="w")

        # Add clickable "Open folder" link below the message
        link_frame = tk.Frame(bubble, bg=COLORS["bg_chat"])
        link_frame.pack(anchor="w", padx=12, pady=(0, 4))

        link = tk.Label(
            link_frame,
            text=f"\U0001F4C2 {Path(filepath).name}",
            fg=COLORS["link"], bg=COLORS["bg_chat"],
            font=("Consolas", 9, "underline"),
            cursor="hand2",
        )
        link.pack(side="left")

        def _open_folder(event=None, fp=filepath):
            try:
                subprocess.Popen(
                    ["nautilus", "--select", fp],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                try:
                    subprocess.Popen(
                        ["xdg-open", str(Path(fp).parent)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception as e:
                    LOG.warning(f"Could not open folder: {e}")

        link.bind("<Button-1>", _open_folder)
        link.bind("<Enter>", lambda e: link.configure(fg=COLORS["link_hover"]))
        link.bind("<Leave>", lambda e: link.configure(fg=COLORS["link"]))

        self.messages_frame.update_idletasks()
        self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))
        self._smart_scroll()
