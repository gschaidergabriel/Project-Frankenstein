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
from overlay.bsn.constants import BSNConstants, get_workarea_y, get_workarea_x, get_workarea, get_primary_monitor
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

        # DOCK panel mode: WM-managed window with _NET_WM_WINDOW_TYPE_DOCK.
        # The WM treats this as a panel (like the taskbar): no decorations,
        # reserves screen space via strut, other windows avoid our area.
        self.overrideredirect(False)

        # Read workarea BEFORE setting our strut (after strut, workarea changes)
        wa = get_workarea()
        wa_y = wa["y"]   # Below GNOME panel
        wa_x = wa["x"]   # Right of GNOME dock
        mon = get_primary_monitor()
        frank_h = mon["height"] - wa_y  # Full height from panel to screen bottom
        frank_h = max(BSNConstants.FRANK_MIN_HEIGHT, frank_h)
        self._workarea_y = wa_y
        self._workarea_x = wa_x
        self._dock_x = wa_x  # Fixed X position (right of GNOME dock)

        self.geometry(f"{BSNConstants.FRANK_DEFAULT_WIDTH}x{frank_h}+{wa_x}+{wa_y}")
        self.minsize(BSNConstants.FRANK_MIN_WIDTH, BSNConstants.FRANK_MIN_HEIGHT)
        self.configure(bg=COLORS["bg_main"])

        # Set DOCK type on client window BEFORE mapping (Mutter reads it on MapRequest).
        # update_idletasks() ensures the X window exists so xwininfo can find it.
        self.update_idletasks()
        self._setup_dock_type_pre_map()

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
            self._chat_history_file = Path.home() / ".local" / "share" / "frank" / "state" / "chat_history.json"

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

        # Voice outbox file (used by PTT TTS responses)
        try:
            from config.paths import TEMP_FILES as _TF
            self._voice_outbox_file = _TF["voice_outbox"]
        except ImportError:
            self._voice_outbox_file = Path("/tmp/frank/voice_outbox.json")

        # FAS Popup dimming signal
        try:
            from config.paths import get_temp as _get_temp_fas
            self._fas_dim_signal_file = _get_temp_fas("fas_dim_signal")
        except ImportError:
            self._fas_dim_signal_file = Path("/tmp/frank/fas_dim_signal")
        self._fas_dimmed = False
        self._fas_original_alpha = 0.95
        self._poll_fas_dim_signal()

        # Restore signal
        try:
            from config.paths import TEMP_FILES as _TF3
            self._restore_signal_file = _TF3["overlay_show"]
        except ImportError:
            self._restore_signal_file = Path("/tmp/frank/overlay_show")
        self._poll_restore_signal()

        # BSN v4.0 - Bidirectional Space Negotiator
        self._layout_controller = LayoutController(self)
        self.after(1500, self._start_layout_controller)

        # Approval System (unified daemon approval queue)
        self._init_approval_system()

        # Agentic Execution Support (autonomous multi-step tasks)
        self._init_agentic()
        self._pending_action_escalation = None  # Auto-escalation state (chat → agentic)

        # Skill System (plugin loader)
        try:
            import sys
            try:
                from config.paths import AICORE_ROOT as _AICORE_ROOT
            except ImportError:
                _AICORE_ROOT = Path(__file__).resolve().parents[2]
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

        # System tray icon for minimize-to-tray
        self._tray_available = start_tray_icon()
        if self._tray_available:
            LOG.info("System tray icon active")
            self._poll_tray_signals()
            self._poll_tray_quit_signal()

        # Periodic monitor change check (resolution/display changes)
        self.after(60000, self._periodic_monitor_check)

        # Register SIGTERM/SIGINT handlers for graceful shutdown
        # MUST be after all init so cleanup can run properly
        self.register_signal_handlers()

        # FINAL STEP: Reveal fully-built window in one frame — no flicker
        self._reveal_window()

    def _setup_dock_type_pre_map(self):
        """Set DOCK type on the Tk client window BEFORE deiconify().

        Mutter reads _NET_WM_WINDOW_TYPE during the initial MapRequest.
        If set after mapping, decorations persist. We find the correct
        client window (parent of winfo_id's internal container) and
        set DOCK type while the window is still withdrawn/unmapped.
        """
        try:
            from overlay.dock_hints import set_window_type_dock, find_client_window
            client_xid = find_client_window(self.winfo_id())
            self._dock_xid = client_xid
            set_window_type_dock(client_xid)
            LOG.info("DOCK type set pre-map on client window 0x%x", client_xid)
        except Exception as e:
            LOG.warning("Pre-map DOCK setup failed: %s — falling back to topmost", e)
            self.attributes("-topmost", True)

    def _update_strut(self):
        """Update strut reservation based on current Frank width."""
        try:
            from overlay.dock_hints import set_strut_partial
            xid = getattr(self, '_dock_xid', self.winfo_id())
            frank_w = self.winfo_width()
            left_total = self._dock_x + frank_w
            mon = get_primary_monitor()
            set_strut_partial(xid, left_total, 0, mon["height"] - 1)
        except Exception as e:
            LOG.warning("Strut update failed: %s", e)

    def _periodic_monitor_check(self):
        """Check for monitor changes every 60s. Reapply DOCK geometry and strut."""
        try:
            old_mon = get_primary_monitor()
            from overlay.bsn.constants import refresh_primary_monitor
            refresh_primary_monitor()
            new_mon = get_primary_monitor()
            if (old_mon["width"] != new_mon["width"]
                    or old_mon["height"] != new_mon["height"]):
                LOG.info("Monitor changed: %dx%d -> %dx%d",
                         old_mon["width"], old_mon["height"],
                         new_mon["width"], new_mon["height"])
                frank_h = new_mon["height"] - self._workarea_y
                frank_h = max(BSNConstants.FRANK_MIN_HEIGHT, frank_h)
                self.geometry(f"{self.winfo_width()}x{frank_h}+{self._dock_x}+{self._workarea_y}")
                self._update_strut()
        except Exception as e:
            LOG.debug("Monitor check error: %s", e)
        self.after(60000, self._periodic_monitor_check)

    def _startup_location_refresh(self):
        """Detect real location on startup via IP/WiFi geolocation (1x per session)."""
        try:
            import sys
            try:
                from config.paths import AICORE_ROOT as _AICORE_ROOT2
            except ImportError:
                _AICORE_ROOT2 = Path(__file__).resolve().parents[2]
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

        DOCK type was already set pre-map. Now set strut with real dimensions.
        """
        self.deiconify()
        self.update_idletasks()
        # Set strut NOW — window has real dimensions after deiconify+update
        self._update_strut()
        self.attributes("-alpha", 0.95)
        # Start the status dot animation
        self.after(200, self._draw_status_dot)
        # Load chat history AFTER window is visible and has real dimensions.
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
