"""Worker mixin -- daemon thread loops and thread-safe UI callback.

Methods rely on self.* attributes provided by the assembled ChatOverlay
at runtime via MRO.  Dispatch targets (_do_chat_worker, _do_search_worker,
etc.) live in other mixins and resolve via MRO at runtime.
"""

import queue
import time
import traceback

from overlay.constants import LOG, TOOLS_CONTEXT_TTL_S
from overlay.file_utils import _extract_context_line
from overlay.services.toolbox import _tools_call
from overlay.services.search import _open_url, _open_url_tor, _open_file_in_manager


class WorkerMixin:

    def _chat_worker_loop(self):
        """Handle slow LLM chat operations."""
        while True:
            kind, arg = self._chat_q.get()
            try:
                if kind == "chat":
                    self._do_chat_worker(**arg)
                elif kind == "screenshot":
                    self._do_screenshot_worker(**arg)
                elif kind == "analyze_image":
                    self._do_analyze_image_worker(**arg)
                elif kind == "analyze_pdf":
                    self._do_analyze_pdf_worker(**arg)
                elif kind == "read_file":
                    self._do_read_file_worker(**arg)
            except Exception as e:
                self._ui_call(lambda err=e: self._add_message("Error", str(err), is_system=True))
            finally:
                self._chat_q.task_done()

    def _io_worker_loop(self):
        """Handle fast IO operations (doesn't block on LLM)."""
        while True:
            kind, arg = self._io_q.get()
            try:
                if kind == "search":
                    self._do_search_worker(**arg)
                elif kind == "darknet_search":
                    self._do_darknet_search_worker(**arg)
                elif kind == "darknet_open":
                    _open_url_tor(str(arg))
                elif kind == "open":
                    url_str = str(arg)
                    if url_str.startswith("file://"):
                        _open_file_in_manager(url_str)
                    else:
                        _open_url(url_str)
                elif kind == "file_search":
                    self._do_file_search_worker(**arg)
                elif kind == "ingest":
                    self._do_ingest_worker(**arg)
                elif kind == "fs_list":
                    self._do_fs_list_worker(**arg)
                elif kind == "fs_action":
                    self._do_fs_action_worker(**arg)
                elif kind == "steam_list":
                    # Pass voice flag if present
                    self._do_steam_list_worker(**arg) if isinstance(arg, dict) else self._do_steam_list_worker()
                elif kind == "steam_launch":
                    self._do_steam_launch_worker(**arg)
                elif kind == "steam_close":
                    # Pass voice flag if present
                    self._do_steam_close_worker(**arg) if isinstance(arg, dict) else self._do_steam_close_worker()
                # App Registry operations
                elif kind == "app_search":
                    self._do_app_search_worker(**arg)
                elif kind == "app_open":
                    self._do_app_open_worker(**arg)
                elif kind == "app_close":
                    self._do_app_close_worker(**arg)
                elif kind == "app_allow":
                    self._do_app_allow_worker(**arg)
                elif kind == "app_list":
                    self._do_app_list_worker(**arg)
                # Package list
                elif kind == "package_list":
                    self._do_package_list_worker(**arg)
                # USB device management
                elif kind == "usb_storage":
                    self._do_usb_storage_worker()
                elif kind == "usb_mount":
                    self._do_usb_mount_worker(**arg)
                elif kind == "usb_unmount":
                    self._do_usb_unmount_worker(**arg)
                elif kind == "usb_eject":
                    self._do_usb_eject_worker(**arg)
                # External data: URL fetch, RSS, News
                elif kind == "fetch_url":
                    self._do_fetch_url_worker(**arg)
                elif kind == "rss_feed":
                    self._do_rss_feed_worker(**arg)
                elif kind == "news":
                    self._do_news_worker(**arg)
                # Skill system
                elif kind == "skill":
                    self._do_skill_worker(**arg)
                elif kind == "skill_reload":
                    self._do_skill_reload_worker()
                elif kind == "skill_list":
                    self._do_skill_list_worker()
                elif kind == "skill_browse":
                    self._do_skill_browse_worker(**arg)
                elif kind == "skill_install":
                    self._do_skill_install_worker(**arg)
                elif kind == "skill_uninstall":
                    self._do_skill_uninstall_worker(**arg)
                elif kind == "skill_updates":
                    self._do_skill_updates_worker()
                # Email operations
                elif kind == "email_list":
                    self._do_email_list_worker(**arg)
                elif kind == "email_list_cards":
                    self._do_email_list_cards_worker(**arg)
                elif kind == "email_detail":
                    self._do_email_detail_worker(**arg)
                elif kind == "email_read":
                    self._do_email_read_worker(**arg)
                elif kind == "email_read_latest":
                    self._do_email_read_latest_worker(**arg)
                elif kind == "email_unread":
                    self._do_email_unread_worker(**arg)
                elif kind == "email_check":
                    self._do_email_check_worker(**arg) if isinstance(arg, dict) else self._do_email_check_worker()
                elif kind == "email_delete":
                    self._do_email_delete_worker(**arg)
                elif kind == "email_delete_single":
                    self._do_email_delete_single_worker(**arg)
                elif kind == "email_spam":
                    self._do_email_spam_worker(**arg)
                elif kind == "email_general":
                    self._do_email_general_worker(**arg)
                elif kind == "email_popup":
                    self._do_email_popup_worker(**arg)
                elif kind == "email_send":
                    self._do_email_send_worker(**arg)
                elif kind == "email_draft":
                    self._do_email_draft_worker(**arg)
                elif kind == "email_toggle_read":
                    self._do_email_toggle_read_worker(**arg)
                elif kind == "email_compose":
                    self._do_email_compose_worker(**arg)
                elif kind == "email_reply_draft":
                    self._do_email_reply_draft_worker(**arg)
                elif kind == "email_settings":
                    self._do_email_settings_worker(**arg)
                elif kind == "email_search":
                    self._do_email_search_worker(**arg)
                elif kind == "email_thread":
                    self._do_email_thread_worker(**arg)
                elif kind == "email_save_attachment":
                    self._do_email_save_attachment_worker(**arg)
                elif kind == "email_undo_delete":
                    self._do_email_undo_delete_worker(**arg)
                elif kind == "_email_execute_delete":
                    self._do_email_execute_delete_worker(**arg)
                # Calendar operations
                elif kind == "calendar_today":
                    self._do_calendar_today_worker(**arg)
                elif kind == "calendar_week":
                    self._do_calendar_week_worker(**arg)
                elif kind == "calendar_list":
                    self._do_calendar_list_worker(**arg)
                elif kind == "calendar_event":
                    self._do_calendar_event_worker(**arg)
                elif kind == "calendar_create":
                    self._do_calendar_create_worker(**arg)
                elif kind == "calendar_delete":
                    self._do_calendar_delete_worker(**arg)
                elif kind == "calendar_general":
                    self._do_calendar_general_worker(**arg)
                elif kind == "calendar_reminder":
                    self._do_calendar_reminder_worker()
                # Contacts operations
                elif kind == "contacts_list":
                    self._do_contacts_list_worker(**arg)
                elif kind == "contacts_search":
                    self._do_contacts_search_worker(**arg)
                elif kind == "contacts_create":
                    self._do_contacts_create_worker(**arg)
                elif kind == "contacts_delete":
                    self._do_contacts_delete_worker(**arg)
                elif kind == "contacts_general":
                    self._do_contacts_general_worker(**arg)
                # Notes operations
                elif kind == "notes_create":
                    self._do_notes_create_worker(**arg)
                elif kind == "notes_list":
                    self._do_notes_list_worker(**arg)
                elif kind == "notes_search":
                    self._do_notes_search_worker(**arg)
                elif kind == "notes_delete":
                    self._do_notes_delete_worker(**arg)
                elif kind == "notes_general":
                    self._do_notes_general_worker(**arg)
                # Todo operations
                elif kind == "todo_create":
                    self._do_todo_create_worker(**arg)
                elif kind == "todo_list":
                    self._do_todo_list_worker(**arg)
                elif kind == "todo_complete":
                    self._do_todo_complete_worker(**arg)
                elif kind == "todo_delete":
                    self._do_todo_delete_worker(**arg)
                elif kind == "todo_general":
                    self._do_todo_general_worker(**arg)
                elif kind == "todo_reminder":
                    self._do_todo_reminder_worker()
                # Converter
                elif kind == "convert":
                    self._do_convert_worker(**arg)
                # Clipboard History
                elif kind == "clipboard_capture":
                    self._do_clipboard_capture_worker(**arg)
                elif kind == "clipboard_list":
                    self._do_clipboard_list_worker(**arg)
                elif kind == "clipboard_search":
                    self._do_clipboard_search_worker(**arg)
                elif kind == "clipboard_restore":
                    self._do_clipboard_restore_worker(**arg)
                elif kind == "clipboard_delete":
                    self._do_clipboard_delete_worker(**arg)
                elif kind == "clipboard_clear":
                    self._do_clipboard_clear_worker(**arg)
                # Password Manager
                elif kind == "password_popup":
                    self._do_password_popup_worker(**arg)
                elif kind == "password_list":
                    self._do_password_list_worker(**arg)
                elif kind == "password_search":
                    self._do_password_search_worker(**arg)
                elif kind == "password_autotype":
                    self._do_password_autotype_worker(**arg)
                elif kind == "password_copy":
                    self._do_password_copy_worker(**arg)
                # QR Code
                elif kind == "qr_scan_screen":
                    self._do_qr_scan_screen_worker(**arg)
                elif kind == "qr_scan_camera":
                    self._do_qr_scan_camera_worker(**arg)
                elif kind == "qr_scan_file":
                    self._do_qr_scan_file_worker(**arg)
                elif kind == "qr_generate":
                    self._do_qr_generate_worker(**arg)
                # Printer
                elif kind == "printer_status":
                    self._do_printer_status_worker(**arg)
                elif kind == "print_file":
                    self._do_print_file_worker(**arg)
                # Notifications
                elif kind == "notification_check":
                    self._do_notification_check_worker()
                # System restart
                elif kind == "system_restart":
                    self._do_system_restart_worker()
            except Exception as e:
                self._ui_call(lambda err=e: self._add_message("Error", str(err), is_system=True))
            finally:
                self._io_q.task_done()

    def _context_loop(self):
        while True:
            try:
                self._refresh_context_if_needed(force=False)
            except Exception as e:
                LOG.warning(f"Context refresh: {e}")
            time.sleep(2.0)

    def _refresh_context_if_needed(self, force: bool):
        with self._ctx_lock:
            age = time.time() - self._ctx_ts
            if not force and self._ctx_ts > 0 and age < TOOLS_CONTEXT_TTL_S:
                return

        j = _tools_call("/sys/summary", {}, timeout_s=1.6)
        if not isinstance(j, dict) or not j.get("ok"):
            return
        line = _extract_context_line(j)
        with self._ctx_lock:
            self._ctx_text = line
            self._ctx_ts = time.time()

    def _get_context_line(self) -> str:
        self._refresh_context_if_needed(force=False)
        with self._ctx_lock:
            return self._ctx_text

    def _poll_ui_queue(self):
        """Poll UI queue from main thread - thread-safe updates."""
        processed = 0
        try:
            while True:
                callback = self._ui_queue.get_nowait()
                try:
                    callback()
                    processed += 1
                except Exception as e:
                    LOG.error(f"UI callback error: {e}")
        except queue.Empty:
            pass

        # Force refresh if we processed any callbacks
        if processed > 0:
            try:
                self.update_idletasks()
                self.update()
            except Exception:
                pass

        # Schedule next poll (faster polling for better responsiveness)
        self.after(30, self._poll_ui_queue)

    # ── Overlay Heartbeat (for watchdog) ──

    _HEARTBEAT_INTERVAL_MS = 5000  # 5 seconds

    def _start_heartbeat(self):
        """Start periodic heartbeat writes for the overlay watchdog."""
        self._write_heartbeat()

    def _write_heartbeat(self):
        """Write current timestamp to heartbeat file."""
        try:
            try:
                from config.paths import TEMP_FILES
                hb_path = TEMP_FILES["overlay_heartbeat"]
            except (ImportError, KeyError):
                from pathlib import Path
                hb_path = Path("/tmp/frank/overlay_heartbeat")
            hb_path.parent.mkdir(parents=True, exist_ok=True)
            hb_path.write_text(str(time.time()))
        except Exception:
            pass
        self.after(self._HEARTBEAT_INTERVAL_MS, self._write_heartbeat)

    def _ui_call(self, callback: "Callable[[], None]"):
        """Thread-safe way to schedule UI updates from worker threads."""
        self._ui_queue.put(callback)
