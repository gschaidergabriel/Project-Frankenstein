#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AI Core Chat Overlay — Assembled ChatOverlay class.

This module assembles the ChatOverlay class from TkDndBase + 12 Mixins.
Each mixin provides a group of related methods; Python MRO resolves
self.* calls at runtime.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from overlay.constants import (
    LOG,
    COLORS,
    SearchResult,
    TkDndBase,
    DND_AVAILABLE,
    DND_FILES,
    SYSTEM_CONTROL_AVAILABLE,
    SESSION_ID,
)
from overlay.bsn.constants import BSNConstants, get_workarea_y, get_workarea_x, get_workarea
from overlay.bsn.controller import LayoutController
from overlay.genesis.watcher import GenesisWatcher
from overlay.services.system_control import sc_startup_scan
from overlay.tray_icon import start_tray_icon, stop_tray_icon

# ---------- Mixins ----------
from overlay.mixins.lifecycle_mixin import LifecycleMixin
from overlay.mixins.ui_mixin import UiMixin
from overlay.mixins.message_mixin import MessageMixin
from overlay.mixins.persistence_mixin import PersistenceMixin
from overlay.mixins.worker_mixin import WorkerMixin
from overlay.mixins.chat_mixin import ChatMixin
from overlay.mixins.voice_mixin import VoiceMixin
from overlay.mixins.approval_mixin import ApprovalMixin
from overlay.mixins.command_router_mixin import CommandRouterMixin
from overlay.mixins.io_workers_mixin import IOWorkersMixin
from overlay.mixins.app_workers_mixin import AppWorkersMixin
from overlay.mixins.analysis_mixin import AnalysisMixin
from overlay.mixins.file_attach_mixin import FileAttachMixin
from overlay.mixins.agentic_mixin import AgenticMixin
from overlay.mixins.email_mixin import EmailMixin
from overlay.mixins.calendar_mixin import CalendarMixin
from overlay.mixins.contacts_mixin import ContactsMixin
from overlay.mixins.notes_mixin import NotesMixin
from overlay.mixins.todo_mixin import TodoMixin
from overlay.mixins.calculator_mixin import CalculatorMixin
from overlay.mixins.clipboard_mixin import ClipboardMixin
from overlay.mixins.password_mixin import PasswordMixin
from overlay.mixins.qr_mixin import QrMixin
from overlay.mixins.printer_mixin import PrinterMixin
from overlay.mixins.notification_mixin import NotificationMixin


class ChatOverlay(
    LifecycleMixin,
    UiMixin,
    MessageMixin,
    PersistenceMixin,
    WorkerMixin,
    ChatMixin,
    VoiceMixin,
    ApprovalMixin,
    AgenticMixin,  # Agentic execution support
    CommandRouterMixin,
    IOWorkersMixin,
    EmailMixin,
    CalendarMixin,
    ContactsMixin,
    NotesMixin,
    TodoMixin,
    CalculatorMixin,
    ClipboardMixin,
    PasswordMixin,
    QrMixin,
    PrinterMixin,
    NotificationMixin,
    AppWorkersMixin,
    AnalysisMixin,
    FileAttachMixin,
    TkDndBase,
):
    """Cyberpunk-styled AI Chat Overlay with neon aesthetics."""

    def __init__(self):
        super().__init__()

        # FAST STARTUP: withdraw() unmaps the window so Tk skips all rendering.
        # Widget creation and message loading happen with zero rendering overhead.
        # After init, _reveal_window() re-maps and fixes message heights.
        self.withdraw()

        # Clear user-closed signal on startup — overlay is starting, so it's wanted
        try:
            from overlay.mixins.lifecycle_mixin import USER_CLOSED_SIGNAL
            USER_CLOSED_SIGNAL.unlink(missing_ok=True)
        except Exception:
            pass

        self.title("F.R.A.N.K.")

        # WM-managed window WITHOUT decorations (Motif hints).
        # This gives us: taskbar entry, Alt+Tab, proper iconify/deiconify —
        # while still having a custom titlebar and no WM frame.
        self.overrideredirect(False)
        self.attributes("-topmost", True)

        # Dynamic position from workarea (respects GNOME panel + dock)
        wa = get_workarea()
        wa_y = wa["y"]   # Below GNOME panel
        wa_x = wa["x"]   # Right of GNOME dock
        screen_h = self.winfo_screenheight()
        frank_h = min(720, screen_h - wa_y - 10)
        frank_h = max(BSNConstants.FRANK_MIN_HEIGHT, frank_h)
        self._workarea_y = wa_y
        self._workarea_x = wa_x

        self.geometry(f"{BSNConstants.FRANK_DEFAULT_WIDTH}x{frank_h}+{wa_x + 1}+{wa_y}")
        self.minsize(BSNConstants.FRANK_MIN_WIDTH, BSNConstants.FRANK_MIN_HEIGHT)
        self.configure(bg=COLORS["bg_main"])

        # Remove WM decorations via Motif hints (keeps taskbar + Alt+Tab)
        self.update_idletasks()
        self._remove_wm_decorations()

        # Set window icon for taskbar (reuse tray icon)
        self._set_taskbar_icon()

        # Track WM-initiated map/unmap (user clicks taskbar to restore)
        self.bind("<Map>", self._on_wm_map)
        self.bind("<Unmap>", self._on_wm_unmap)

        # Variables for window dragging
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._dragging = False  # Flag to prevent focus hack during drag

        # State
        self._pending_results: List[SearchResult] = []
        self._pending_darknet: bool = False
        self._last_file: Optional[Path] = None
        self._last_file_lang: str = "text"
        self._last_file_content: str = ""

        # Conversation history for context
        self._chat_history: List[Dict[str, str]] = []
        self._chat_history_max = 50
        try:
            from config.paths import get_state
            self._chat_history_file = get_state("chat_history")
        except ImportError:
            self._chat_history_file = Path("/home/ai-core-node/.local/share/frank/state/chat_history.json")

        # Persistent conversation memory (SQLite + FTS5)
        try:
            from services.chat_memory import ChatMemoryDB
            self._chat_memory_db = ChatMemoryDB()
            self._memory_session_id = SESSION_ID
            self._chat_memory_db.start_session(self._memory_session_id)
            # Migrate existing JSON history on first run
            stats = self._chat_memory_db.get_stats()
            if not stats.get("total_messages", 0) and self._chat_history_file.exists():
                count = self._chat_memory_db.migrate_from_json(
                    self._chat_history_file, f"legacy_{SESSION_ID}",
                )
                LOG.info(f"Migrated {count} messages from JSON to SQLite")
            LOG.info(f"Chat memory DB ready ({stats.get('total_messages', 0)} messages)")
        except Exception as e:
            LOG.warning(f"Chat memory DB init failed (JSON fallback): {e}")

        # Context cache
        self._ctx_lock = threading.Lock()
        self._ctx_text: str = ""
        self._ctx_ts: float = 0.0

        # Two worker queues: chat (slow, LLM) and io (fast, tools)
        self._chat_q: "queue.Queue[Tuple[str, Any]]" = queue.Queue()
        self._io_q: "queue.Queue[Tuple[str, Any]]" = queue.Queue()
        # Thread-safe UI update queue
        self._ui_queue: "queue.Queue[Callable[[], None]]" = queue.Queue()
        threading.Thread(target=self._chat_worker_loop, daemon=True).start()
        threading.Thread(target=self._io_worker_loop, daemon=True).start()

        # Typing indicator state
        self._is_typing = False
        self._typing_dots = 0

        # PTT state
        self._ptt_recording = False

        self._build_ui()
        self._bind_keys()
        self._init_resize()

        # NOTE: Chat history is loaded AFTER reveal via _deferred_load_history().
        # MessageBubble creation is slow (~250ms each), so we show the window
        # immediately and load messages asynchronously to keep startup instant.

        # Background context refresh
        threading.Thread(target=self._context_loop, daemon=True).start()

        # Start UI polling for thread-safe updates
        self._poll_ui_queue()

        # Location auto-detection (1x per session via IP geolocation)
        threading.Thread(target=self._startup_location_refresh, daemon=True).start()

        # Voice integration
        self._voice_event_file = Path("/tmp/frank_voice_event.json")
        self._voice_outbox_file = Path("/tmp/frank_voice_outbox.json")
        self._last_voice_event_ts = 0.0
        self._voice_listening = False
        self._pending_voice_session: Optional[str] = None
        self._poll_voice_events()

        # FAS Popup dimming signal
        self._fas_dim_signal_file = Path("/tmp/frank_fas_dim_signal")
        self._fas_dimmed = False
        self._fas_original_alpha = 0.95
        self._poll_fas_dim_signal()

        # Restore signal
        self._restore_signal_file = Path("/tmp/frank_overlay_show")
        self._poll_restore_signal()

        # BSN v4.0 - Bidirectional Space Negotiator
        self._layout_controller = LayoutController(self)
        self.after(1500, self._start_layout_controller)

        # Approval System (unified daemon approval queue)
        self._init_approval_system()

        # Agentic Execution Support (autonomous multi-step tasks)
        self._init_agentic()

        # Skill System (plugin loader)
        try:
            import sys
            try:
                from config.paths import AICORE_ROOT as _AICORE_ROOT
            except ImportError:
                _AICORE_ROOT = Path("/home/ai-core-node/aicore/opt/aicore")
            sys.path.insert(0, str(_AICORE_ROOT))
            from skills import get_skill_registry
            _sr = get_skill_registry()
            LOG.info(f"Skill system ready: {len(_sr.list_all())} skills")
        except Exception as e:
            LOG.warning(f"Skill system init failed: {e}")

        # Email integration (Thunderbird polling)
        self.after(10000, self._email_poll_timer)  # First check after 10s
        LOG.info("Email poll timer scheduled")

        # Calendar integration (Google Calendar reminders)
        self._reminded_calendar_uids = set()
        self.after(15000, self._calendar_poll_timer)  # First check after 15s
        LOG.info("Calendar poll timer scheduled")

        # Todo reminder polling
        self._reminded_todo_ids = set()
        self.after(20000, self._todo_poll_timer)  # First check after 20s
        LOG.info("Todo poll timer scheduled")

        # Clipboard history polling (passive capture)
        self._last_clipboard_hash = ""
        self.after(5000, self._clipboard_poll_timer)  # First check after 5s
        LOG.info("Clipboard history poll timer scheduled")

        # Password Manager popup reference (singleton)
        self._password_popup = None
        LOG.info("Password Manager ready")

        # Genesis Proposal Watcher
        self._genesis_watcher = GenesisWatcher(self)
        LOG.info("Genesis Proposal Watcher started")

        # ADI (Adaptive Display Intelligence)
        self.after(3000, self._check_monitor_on_startup)
        self.after(3500, self._poll_adi_apply_signal)
        LOG.info("ADI monitor check scheduled")

        # System Control - Startup network scan
        if SYSTEM_CONTROL_AVAILABLE:
            self.after(5000, sc_startup_scan)
            LOG.info("System Control startup scan scheduled")

        # Memory maintenance timer (hourly: cleanup old messages, generate summaries)
        self.after(3600_000, self._memory_maintenance_timer)

        # Notification daemon overlay integration
        self._seen_notification_ids = set()
        self.after(25000, self._notification_poll_timer)
        LOG.info("Notification poll timer scheduled")

        # Fullscreen detection state
        self._fullscreen_yielded = False

        # System tray icon for minimize-to-tray
        self._tray_available = start_tray_icon()
        if self._tray_available:
            LOG.info("System tray icon active")
            self._poll_tray_signals()
            self._poll_tray_quit_signal()

        # Fullscreen detection polling
        self.after(2000, self._poll_fullscreen)

        # CRITICAL: Enforce position below GNOME panel after startup
        # Multiple enforcement passes to catch any drift from WM, focus hacks, etc.
        self.after(100, self._enforce_panel_boundary)
        self.after(500, self._enforce_panel_boundary)
        self.after(2000, self._enforce_panel_boundary)
        # Periodic enforcement every 10 seconds (catches drift from focus hacks, etc.)
        self.after(10000, self._periodic_panel_enforcement)

        # FINAL STEP: Reveal fully-built window in one frame — no flicker
        self._reveal_window()

    def _remove_wm_decorations(self):
        """Remove WM decorations via _MOTIF_WM_HINTS (keeps taskbar + Alt+Tab)."""
        try:
            wid = self.winfo_id()
            # Motif hints: flags=0x2 (decorations bit), decorations=0 (none)
            subprocess.run(
                ['xprop', '-id', str(wid),
                 '-f', '_MOTIF_WM_HINTS', '32c',
                 '-set', '_MOTIF_WM_HINTS', '0x2, 0x0, 0x0, 0x0, 0x0'],
                capture_output=True, timeout=2,
                env={**os.environ, 'DISPLAY': ':0'},
            )
            LOG.info("WM decorations removed via Motif hints (wid=%s)", wid)
        except Exception as e:
            LOG.warning("Could not remove WM decorations: %s — falling back to overrideredirect", e)
            self.overrideredirect(True)

    def _set_taskbar_icon(self):
        """Set window icon for taskbar/Alt+Tab display."""
        try:
            import tkinter as tk
            icon_path = Path("/tmp/frank_icons/frank-tray.png")
            if icon_path.exists():
                img = tk.PhotoImage(file=str(icon_path))
                self.iconphoto(True, img)
                self._taskbar_icon_img = img  # prevent GC
        except Exception as e:
            LOG.debug("Could not set taskbar icon: %s", e)

    def _on_wm_map(self, event):
        """Handle WM-initiated window map (e.g. user clicks taskbar icon)."""
        if event.widget is not self:
            return
        if getattr(self, '_overlay_minimized', False):
            self._overlay_minimized = False
            self._overlay_hidden = False
            if not getattr(self, '_fullscreen_yielded', False):
                self.attributes("-topmost", True)
            self.attributes("-alpha", 0.95)
            LOG.info("Overlay restored via WM (taskbar click)")

    def _on_wm_unmap(self, event):
        """Handle WM-initiated window unmap (e.g. WM minimizes window)."""
        if event.widget is not self:
            return
        if not getattr(self, '_overlay_minimized', False):
            self._overlay_minimized = True
            LOG.info("Overlay minimized via WM")

    def _startup_location_refresh(self):
        """Detect real location on startup via IP/WiFi geolocation (1x per session)."""
        try:
            import sys
            try:
                from config.paths import AICORE_ROOT as _AICORE_ROOT2
            except ImportError:
                _AICORE_ROOT2 = Path("/home/ai-core-node/aicore/opt/aicore")
            sys.path.insert(0, str(_AICORE_ROOT2))
            from personality.self_knowledge import get_location_service
            loc_service = get_location_service()
            loc = loc_service.get_location(force_refresh=True)
            LOG.info("Location detected: %s, %s (source=%s, tz=%s)",
                     loc.city, loc.country, loc.source, loc.timezone)
        except Exception as e:
            LOG.warning("Startup location refresh failed: %s", e)

    def _reveal_window(self):
        """Reveal the UI shell instantly, then load messages asynchronously.

        _build_ui() takes ~40ms. We show that immediately (titlebar + input).
        Messages load in the background via after() so the UI stays responsive.
        """
        self.deiconify()
        self.update_idletasks()
        self.attributes("-alpha", 0.95)
        if not getattr(self, '_fullscreen_yielded', False):
            self.attributes("-topmost", True)
        # Start the status dot animation
        self.after(200, self._draw_status_dot)
        # Load chat history AFTER window is visible and has real dimensions.
        # 200ms delay gives Tk time to process Configure events so canvas has real width.
        self.after(200, self._deferred_load_history)

    def _deferred_load_history(self):
        """Load chat history after window is visible."""
        # CRITICAL: Ensure canvas_window has the real canvas width BEFORE creating bubbles.
        # Without this, messages_frame may have width 0 and all bubbles render invisible.
        try:
            canvas_w = self.chat_canvas.winfo_width()
            if canvas_w > 1:
                self.chat_canvas.itemconfig(self.canvas_window, width=canvas_w)
                LOG.info(f"Deferred load: canvas width = {canvas_w}")
            else:
                # Canvas not ready yet, retry in 200ms
                LOG.warning("Deferred load: canvas width still 0, retrying in 200ms")
                self.after(200, self._deferred_load_history)
                return
        except Exception as e:
            LOG.warning(f"Deferred load: canvas width check failed: {e}")
        if not self._load_chat_history():
            self._add_message("Frank", "Hey! Was kann ich fuer dich tun?", is_system=False)
