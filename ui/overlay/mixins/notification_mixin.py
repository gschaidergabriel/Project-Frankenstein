"""Notification mixin -- polls daemon notification directory and shows reminders in chat.

The notification_daemon.py writes JSON files to TEMP_DIR/notifications/.
This mixin picks them up and displays them as chat messages.
"""
from __future__ import annotations

import json
import os
import subprocess
import tkinter as tk
from pathlib import Path

from overlay.constants import COLORS, LOG

try:
    from config.paths import TEMP_FILES as _TF_notif
    NOTIFICATION_DIR = _TF_notif["notifications_dir"]
except ImportError:
    NOTIFICATION_DIR = Path("/tmp/frank/notifications")
_NOTIFICATION_POLL_MS = 15_000  # 15 seconds

# Categories routed to the Log Panel instead of main chat
_LOG_PANEL_CATEGORIES = frozenset({
    "consciousness", "dream",
    "wellness", "philosophy", "art_studio", "architecture",
    "painting",
})

# ── Art presentation colors ────────────────────────────────────────
_ART_GOLD = "#C8A04A"
_ART_GOLD_DIM = "#8B7D5A"
_ART_BG = "#0e0c08"
_ART_BG_INNER = "#12100a"
_ART_TEXT = "#E8E0D0"
_ART_TEXT_DIM = "#9B9080"
_ART_BORDER = "#3D3520"


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
                    "wellness": "\U0001F33F",         # herb (Wellness Room)
                    "philosophy": "\U0001F3DB",       # classical building (Philosophy Atrium)
                    "art_studio": "\U0001F58C",       # paintbrush (Art Studio)
                    "architecture": "\U0001F9E9",     # puzzle piece (Architecture Bay)
                    "autonomous": "\u2699\uFE0F",     # gear (autonomous action)
                    "consciousness": "\U0001F9E0",    # brain (consciousness)
                    "dream": "\U0001F4AD",            # thought bubble (dream)
                    "genesis": "\U0001F9EC",           # DNA (genesis)
                    "painting": "\U0001F3A8",          # palette (painting)
                }
                icon = icon_map.get(category, "\U0001F514")  # default: bell

                msg = f"{icon} {body}"
                is_system = urgency != "critical"
                sender = data.get("sender", "Frank")
                filepath = data.get("filepath", "")

                image_path = data.get("image_path", "")

                if category == "painting_share" and image_path and Path(image_path).is_file():
                    caption = body or "I painted something."
                    style = data.get("style", "")
                    self._ui_call(
                        lambda ip=image_path, c=caption, st=style:
                            self._add_painting_message(ip, c, st)
                    )
                elif category == "download" and filepath:
                    self._ui_call(
                        lambda m=msg, s=is_system, sn=sender, fp=filepath:
                            self._add_download_message(sn, m, fp, is_system=s)
                    )
                elif category in _LOG_PANEL_CATEGORIES and hasattr(self, "_log_add_entry"):
                    self._ui_call(
                        lambda cat=category, m=body, sn=sender:
                            self._log_add_entry(cat, m, sn)
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

    # ── Art presentation widget ────────────────────────────────────────

    def _add_painting_message(self, image_path: str, caption: str,
                              style: str = ""):
        """Show a painting in the chat as an elegant art presentation."""
        try:
            from PIL import Image, ImageTk
            from overlay.widgets.image_viewer import ImageViewer
        except ImportError:
            self._add_message("Frank", f"[Painting: {image_path}]", is_system=True)
            return

        try:
            pil_img = Image.open(image_path)
            if pil_img.mode != "RGB":
                pil_img = pil_img.convert("RGB")
        except Exception as e:
            LOG.error("Failed to load painting: %s", e)
            return

        # ── Outer frame ──
        outer = tk.Frame(self.messages_frame, bg=COLORS["bg_chat"])
        outer.pack(fill="x", padx=6, pady=6)

        # Gold accent border
        border = tk.Frame(outer, bg=_ART_BORDER, padx=1, pady=1)
        border.pack(anchor="w", fill="x")

        card = tk.Frame(border, bg=_ART_BG)
        card.pack(fill="x")

        # ── Header ──
        header = tk.Frame(card, bg=_ART_BG)
        header.pack(fill="x", padx=12, pady=(8, 4))

        # Gold top accent line
        tk.Frame(header, bg=_ART_GOLD, height=1).pack(fill="x", pady=(0, 6))

        header_row = tk.Frame(header, bg=_ART_BG)
        header_row.pack(fill="x")

        tk.Label(
            header_row, text="\U0001F3A8", bg=_ART_BG,
            font=("Segoe UI", 11),
        ).pack(side="left")

        tk.Label(
            header_row, text="FRANK'S STUDIO", bg=_ART_BG,
            fg=_ART_GOLD, font=("Consolas", 9, "bold"),
        ).pack(side="left", padx=(6, 0))

        # Style tag
        if style:
            display_style = style.replace("_", " ").upper()
            tk.Label(
                header_row, text=f"\u2022 {display_style}", bg=_ART_BG,
                fg=_ART_GOLD_DIM, font=("Consolas", 8),
            ).pack(side="left", padx=(8, 0))

        # ── Image ──
        img_container = tk.Frame(card, bg=_ART_BG)
        img_container.pack(fill="x", padx=12, pady=(4, 8))

        # Image with thin gold frame
        img_border = tk.Frame(img_container, bg=_ART_GOLD_DIM, padx=1, pady=1)
        img_border.pack(anchor="w")

        # Scale to fill width nicely (max ~320px wide)
        orig_w, orig_h = pil_img.size
        max_w = 320
        scale = min(max_w / orig_w, 1.0)
        thumb_w = int(orig_w * scale)
        thumb_h = int(orig_h * scale)

        thumbnail = pil_img.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(thumbnail)

        img_label = tk.Label(img_border, image=photo, bg=_ART_BG_INNER, cursor="hand2")
        img_label.image = photo  # prevent GC
        img_label.pack()

        def _open_viewer(event=None):
            try:
                geo = self.geometry()
                ImageViewer(self, image_path, overlay_geometry=geo)
            except Exception as e:
                LOG.error("Failed to open image viewer: %s", e)

        img_label.bind("<Button-1>", _open_viewer)
        img_label.bind("<Enter>", lambda e: img_border.configure(bg=_ART_GOLD))
        img_label.bind("<Leave>", lambda e: img_border.configure(bg=_ART_GOLD_DIM))

        # ── Caption — full text, wrapped, elegant ──
        if caption:
            caption_frame = tk.Frame(card, bg=_ART_BG)
            caption_frame.pack(fill="x", padx=14, pady=(0, 4))

            # Italic quote marks around the reflection
            caption_text = f"\u201C{caption.strip()}\u201D"

            cap_label = tk.Label(
                caption_frame, text=caption_text, bg=_ART_BG,
                fg=_ART_TEXT, font=("Segoe UI", 9, "italic"),
                anchor="w", justify="left", wraplength=310,
            )
            cap_label.pack(anchor="w")

        # ── Footer: open folder button ──
        footer = tk.Frame(card, bg=_ART_BG)
        footer.pack(fill="x", padx=12, pady=(2, 8))

        # Gold bottom accent line
        tk.Frame(footer, bg=_ART_BORDER, height=1).pack(fill="x", pady=(0, 6))

        footer_row = tk.Frame(footer, bg=_ART_BG)
        footer_row.pack(fill="x")

        # Click to enlarge hint
        view_btn = tk.Label(
            footer_row, text="\u25B8 VIEW", bg=_ART_BG,
            fg=_ART_GOLD_DIM, font=("Consolas", 8), cursor="hand2",
        )
        view_btn.pack(side="left")
        view_btn.bind("<Button-1>", _open_viewer)
        view_btn.bind("<Enter>", lambda e: view_btn.configure(fg=_ART_GOLD))
        view_btn.bind("<Leave>", lambda e: view_btn.configure(fg=_ART_GOLD_DIM))

        # Open folder button
        def _open_folder(event=None, fp=image_path):
            try:
                subprocess.Popen(
                    ["nautilus", "--select", fp],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except Exception:
                try:
                    subprocess.Popen(
                        ["xdg-open", str(Path(fp).parent)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                except Exception as e:
                    LOG.warning("Could not open folder: %s", e)

        folder_btn = tk.Label(
            footer_row, text="\U0001F4C2 OPEN FOLDER", bg=_ART_BG,
            fg=_ART_GOLD_DIM, font=("Consolas", 8), cursor="hand2",
        )
        folder_btn.pack(side="left", padx=(12, 0))
        folder_btn.bind("<Button-1>", _open_folder)
        folder_btn.bind("<Enter>", lambda e: folder_btn.configure(fg=_ART_GOLD))
        folder_btn.bind("<Leave>", lambda e: folder_btn.configure(fg=_ART_GOLD_DIM))

        # Scroll to bottom
        self.messages_frame.update_idletasks()
        self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))
        self._smart_scroll()
