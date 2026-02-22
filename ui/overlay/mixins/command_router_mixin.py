"""
CommandRouterMixin -- main command dispatcher (_on_send).

Extracted from chat_overlay_monolith.py lines ~6917-7310.
Routes user input through a priority chain:
  1.  File path detection (_maybe_path)
  2.  Status commands
  3.  System control pending confirmations
  4.  Wallpaper control
  5.  File read requests (FILE_READ_RE)
  6.  Quick file intent mapping
  7.  Open top result / open N
  8.  Search commands
  9.  Steam list/close
  10. App allow/close/list/open
  11. Self-awareness queries
  12. Features queries
  13. Code module queries
  14. System control
  15. ADI display hints
  16. Desktop/screenshot
  17. Filesystem listing
  18. Normal chat fallthrough
"""

import re
import time
from overlay.constants import (
    LOG, COLORS, SESSION_ID, DEFAULT_MAX_TOKENS, DEFAULT_TIMEOUT_S,
    FRANK_IDENTITY,
    FILE_READ_RE,
    STEAM_LIST_RE, STEAM_CLOSE_RE,
    APP_ALLOW_RE, APP_CLOSE_RE, APP_LIST_RE,
    SELF_AWARE_RE, SELF_AWARE_EXCLUDE_RE,
    FEATURES_RE, CODE_MODULE_RE, HALLUCINATION_TRAP_RE,
    SYSTEM_CONTROL_RE, ADI_HINTS_RE, DESKTOP_HINTS_RE,
    FS_HINTS_RE, CODE_HINTS_RE,
    URL_FETCH_RE, RSS_FEED_RE, NEWS_RE,
    USER_NAME_RE,
    EMAIL_LIST_RE, EMAIL_READ_RE, EMAIL_READ_LATEST_RE, EMAIL_UNREAD_RE,
    EMAIL_DELETE_RE, EMAIL_COMPOSE_RE, EMAIL_GENERAL_RE,
    CALENDAR_TODAY_RE, CALENDAR_WEEK_RE, CALENDAR_CREATE_RE,
    CALENDAR_DELETE_RE, CALENDAR_LIST_RE, CALENDAR_GENERAL_RE,
    CONTACTS_LIST_RE, CONTACTS_SEARCH_RE, CONTACTS_CREATE_RE,
    CONTACTS_DELETE_RE, CONTACTS_GENERAL_RE,
    NOTES_CREATE_RE, NOTES_LIST_RE, NOTES_SEARCH_RE,
    NOTES_DELETE_RE, NOTES_GENERAL_RE,
    TODO_CREATE_RE, TODO_LIST_RE, TODO_COMPLETE_RE,
    TODO_DELETE_RE, TODO_GENERAL_RE,
    CLIPBOARD_LIST_RE, CLIPBOARD_SEARCH_RE, CLIPBOARD_RESTORE_RE,
    CLIPBOARD_DELETE_RE, CLIPBOARD_CLEAR_RE, CLIPBOARD_GENERAL_RE,
    PASSWORD_POPUP_RE, PASSWORD_LIST_RE, PASSWORD_SEARCH_RE,
    PASSWORD_AUTOTYPE_RE, PASSWORD_COPY_RE, PASSWORD_GENERAL_RE,
    QR_SCAN_RE, QR_SCAN_CAM_RE, QR_GENERATE_RE, QR_GENERAL_RE,
    PRINT_FILE_RE, PRINTER_STATUS_RE,
    CONVERT_RE, CONVERT_QUERY_RE,
    DARKNET_RE,
    USB_EJECT_RE, USB_MOUNT_RE, USB_UNMOUNT_RE, USB_STORAGE_RE,
    PACKAGE_LIST_RE,
    FILE_SEARCH_RE, FILE_SEARCH_ALT_RE,
)
from overlay.file_utils import _maybe_path, _detect_ingest_base
from overlay.services.system_control import SYSTEM_CONTROL_AVAILABLE, sc_process, sc_has_pending
from overlay.services.toolbox import _core_reflect, _core_features, _core_summary


# ── Inventory intent detection ──────────────────────────────────────────
# Keyword-based, not regex-based. Handles fuzzy/colloquial input.
# Returns: "games", "apps", "pkg:<backend>", or None.

_QUERY_SIGNALS = {
    # Words that signal "I'm asking what I have"
    "what", "whats", "which", "show", "list", "any", "got", "have", "do",
    "my", "all", "the", "installed", "available",
    # German
    "welche", "zeig", "liste", "meine", "habe", "hab",
    "was", "gibt", "installiert", "verfügbar",
}

_GAME_WORDS = {"game", "games", "spiel", "spiele", "gaming", "steam"}
_SNAP_WORDS = {"snap", "snaps"}
_FLATPAK_WORDS = {"flatpak", "flatpaks"}
_PIP_WORDS = {"pip", "pip3", "python"}
_APT_WORDS = {"apt", "dpkg", "deb", "debian"}
_PKG_WORDS = {"package", "packages", "paket", "pakete", "software", "installed", "programs", "programme"}
_APP_WORDS = {"app", "apps", "application", "applications", "anwendung", "anwendungen", "programm", "programme"}


_ACTION_VERBS = {
    "open", "launch", "start", "run", "play", "close", "kill", "stop", "quit",
    "öffne", "starte", "starten", "schließe", "schließen", "beende",
}


def _detect_inventory_query(text: str):
    """Detect if user is asking about installed games/apps/packages.

    Uses keyword overlap scoring instead of rigid regex patterns.
    Returns "games", "apps", "pkg:<backend>", or None.
    """
    words = set(re.sub(r"[?!.,;:'\"]", " ", text).lower().split())

    # Action verbs like "open steam" mean "launch it", NOT "list inventory"
    if words & _ACTION_VERBS:
        return None

    # Must have at least one query signal word
    if not words & _QUERY_SIGNALS:
        # Exception: bare category words like "games?" or "snap list" or "python packages"
        if not (words & _GAME_WORDS or words & _SNAP_WORDS or words & _FLATPAK_WORDS
                or words & _PIP_WORDS or words & _APT_WORDS
                or words & _PKG_WORDS or words & _APP_WORDS):
            return None

    # Category detection by keyword presence
    has_game = bool(words & _GAME_WORDS)
    has_snap = bool(words & _SNAP_WORDS)
    has_flatpak = bool(words & _FLATPAK_WORDS)
    has_pip = bool(words & _PIP_WORDS)
    has_apt = bool(words & _APT_WORDS)
    has_pkg = bool(words & _PKG_WORDS)
    has_app = bool(words & _APP_WORDS)

    # ── Games ──
    if has_game:
        return "games"

    # ── Specific package backends ──
    if has_snap:
        return "pkg:snap"
    if has_flatpak:
        return "pkg:flatpak"
    if has_pip:
        return "pkg:pip"
    if has_apt:
        return "pkg:apt"

    # ── Generic packages ("what packages do i have", "was ist installiert") ──
    if has_pkg:
        return "pkg:all"

    # ── Apps ("what apps do i have") ──
    if has_app:
        return "apps"

    # ── Bare "what's installed" / "was ist installiert" with no category ──
    if "installed" in words or "installiert" in words:
        return "pkg:all"

    return None


class CommandRouterMixin:

    # ---------- Send Logic ----------
    def _on_send(self):
        msg = self.entry.get().strip()
        if not msg:
            return
        self.entry.delete(0, "end")

        # Reset cancel flag for new request
        self._thinking_cancelled = False

        # Record in input history for arrow-key recall
        if hasattr(self, 'entry') and hasattr(self.entry, 'add_to_history'):
            self.entry.add_to_history(msg)

        try:
            self._route_message(msg)
        except Exception as e:
            LOG.error(f"CRITICAL: Command router exception, forcing chat fallback: {e}", exc_info=True)
            try:
                self._add_message("Du", msg, is_user=True)
                self._chat_q.put(("chat", {"msg": msg, "max_tokens": 150, "timeout_s": DEFAULT_TIMEOUT_S, "task": "chat.fast", "force": None}))
            except Exception as e2:
                LOG.error(f"FATAL: Even chat fallback failed: {e2}", exc_info=True)

    # ---------- Auto-Escalation (Chat → Agentic) ----------

    def _set_pending_action_escalation(self, intent: dict, user_msg: str, frank_reply: str):
        """Store pending action escalation from Output-Feedback-Loop.

        Called from chat worker thread; uses _ui_call for thread-safe state update.
        """
        escalation = {
            "intent": intent,
            "user_msg": user_msg,
            "frank_reply": frank_reply[:500],
            "ts": time.time(),
            "msg_counter": 0,
        }
        self._ui_call(lambda esc=escalation: setattr(self, '_pending_action_escalation', esc))
        LOG.info(f"Action escalation armed: {intent.get('goal', '')[:80]}")

    def _check_action_escalation(self, msg: str) -> bool:
        """Check if user input confirms a pending action escalation.

        Returns True if handled (confirmed or rejected).
        Returns False if no pending escalation, expired, or unrelated input.
        """
        esc = getattr(self, '_pending_action_escalation', None)
        if not esc:
            return False

        low = msg.strip().lower()

        # Timeout: 60 seconds
        if time.time() - esc["ts"] > 60.0:
            self._pending_action_escalation = None
            return False

        # Message counter: max 2 non-confirmation messages
        if esc["msg_counter"] >= 2:
            self._pending_action_escalation = None
            return False

        _YES = {
            "ja", "yes", "ok", "okay", "jep", "jup", "mach", "mach das",
            "do it", "klar", "passt", "bitte", "gerne", "mach mal",
            "go ahead", "sure", "yep", "alright", "please", "go",
            "ja bitte", "ja gerne", "ja mach", "ja klar",
        }
        _NO = {
            "nein", "no", "nope", "lieber nicht", "lass mal",
            "nicht nötig", "nicht noetig", "brauchst nicht",
            "skip", "cancel", "abbrechen", "nee", "ne",
        }

        if low in _YES:
            goal = esc["intent"].get("goal", esc["user_msg"])
            self._pending_action_escalation = None
            self._add_message("Du", msg, is_user=True)
            LOG.info(f"Action escalation confirmed -> agentic: {goal[:100]}")
            self._start_agentic_execution(goal)
            return True

        if low in _NO:
            self._pending_action_escalation = None
            self._add_message("Du", msg, is_user=True)
            self._add_message("Frank", "Alright, no worries.", is_system=True)
            return True

        # Unrelated input: increment counter, fall through to normal routing
        esc["msg_counter"] += 1
        return False

    def _route_message(self, msg: str):
        """Route message to appropriate handler. Extracted for safety wrapper."""
        low = msg.lower().strip()

        # Record user activity for approval idle detection
        self._approval_record_user_activity()

        # Approval system: check if this is a response to a pending approval
        if self._approval_check_input(msg):
            return

        # Email delete confirmation handling
        if hasattr(self, '_pending_email_delete') and self._pending_email_delete:
            if low in ("ja", "yes", "j", "y", "ok", "sicher", "mach"):
                self._add_message("Du", msg, is_user=True)
                self._io_q.put(("email_delete", self._pending_email_delete))
                self._pending_email_delete = None
                return
            elif low in ("nein", "no", "n", "abbrechen", "cancel", "stop"):
                self._add_message("Du", msg, is_user=True)
                self._add_message("Frank", "Deletion cancelled.", is_system=True)
                self._pending_email_delete = None
                return
            # Anything else clears the pending state and processes normally
            self._pending_email_delete = None

        # Auto-escalation: user confirms Frank's agentic action proposal (typed or voice)
        if hasattr(self, '_pending_action_escalation') and self._pending_action_escalation:
            if self._check_action_escalation(msg):
                return

        # Agentic response handling: check if agent is active and needs response
        if hasattr(self, '_agentic_active') and self._agentic_active:
            if hasattr(self, '_handle_agentic_response') and self._handle_agentic_response(msg):
                self._add_message("Du", msg, is_user=True)
                return
            # Block ALL other input while agent is running (prevent parallel LLM chat)
            self._add_message("Du", msg, is_user=True)
            self._add_message("Frank", "I'm still working on the previous task. Say 'cancel' to stop it.", is_system=True)
            LOG.info(f"Blocked input during agentic execution: '{msg[:50]}...'")
            return

        # Agentic execution detection - complex multi-step tasks
        # PRIORITY: Must come BEFORE keyword matchers (fs, steam, system control)
        # to prevent simple regex matches from hijacking complex requests
        if hasattr(self, '_is_agentic_query') and self._is_agentic_query(msg):
            self._add_message("Du", msg, is_user=True)
            LOG.info(f"Agentic query detected (early): {msg[:80]}...")
            self._start_agentic_execution(msg)
            return

        # File path detection
        p = _maybe_path(msg)
        if p:
            self._handle_attach(p)
            return

        # Status command
        if low in ("/health", "health", "status", "/status"):
            ing = _detect_ingest_base()
            ctx = self._get_context_line()
            line = f"Session: {SESSION_ID} | Ingest: {ing or 'n/a'}"
            if ctx:
                line += f"\n{ctx}"
            self._add_message("Du", msg, is_user=True)
            self._add_message("Frank", line, is_system=True)
            return

        # ── Full System Restart Command ──
        if low in ("restart frank", "frank restart", "restart system",
                    "system restart", "neustart", "frank neustarten",
                    "alles neustarten", "restart all", "restart everything",
                    "/restart", "system neustart", "frank neu starten",
                    "starte alles neu", "starte frank neu"):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("system_restart", {}))
            return

        # ── LLM Restart Command (no LLM call needed) ──
        if low in ("restart llm", "llm restart", "llm neustarten",
                    "/llm", "neustart llm", "llm neu starten"):
            self._add_message("Du", msg, is_user=True)
            self._add_message("Frank", "Restarting LLM server...", is_system=True)
            import threading
            def _restart_llm():
                import subprocess
                try:
                    r = subprocess.run(
                        ["systemctl", "--user", "restart", "aicore-llama3-gpu.service"],
                        capture_output=True, text=True, timeout=30,
                    )
                    if r.returncode == 0:
                        import time as _t
                        _t.sleep(5)  # Give it time to load model
                        self._ui_call(lambda: self._add_message(
                            "Frank", "LLM server restarted successfully.", is_system=True))
                    else:
                        err = (r.stderr or r.stdout or "unknown error")[:200]
                        self._ui_call(lambda: self._add_message(
                            "Frank", f"LLM restart failed: {err}", is_system=True))
                except Exception as e:
                    self._ui_call(lambda: self._add_message(
                        "Frank", f"LLM restart error: {e}", is_system=True))
            threading.Thread(target=_restart_llm, daemon=True).start()
            return

        # System Control - Check for pending confirmations first
        # This allows users to confirm/cancel actions with simple "ja"/"nein"
        if SYSTEM_CONTROL_AVAILABLE and sc_has_pending():
            handled, response = sc_process(msg)
            if handled and response:
                self._add_message("Du", msg, is_user=True)
                self._add_message("Frank", response)
                return

        # File read request detection (e.g., "lies ~/test.txt", "zeig mir /home/user/doc.pdf")
        file_read_match = FILE_READ_RE.search(msg)
        if file_read_match:
            file_path = file_read_match.group(2)
            self._add_message("Du", msg, is_user=True)
            self._add_message("Frank", f"Reading file: {file_path}...", is_system=True)
            self._chat_q.put(("read_file", {"path": file_path, "user_query": msg}))
            return

        # Quick file intent mapping - ONLY trigger when user EXPLICITLY asks about the file
        # Must mention "datei", "file", or "drin/drinnen" to trigger - NOT just generic words
        # EXCEPTION: If user asks about Frank's OWN code files, let CODE_MODULE_RE handle it
        franks_code_keywords = ["app_registry", "chat_overlay", "toolboxd", "core_awareness",
                                "steam_integration", "vision_module", "personality",
                                "systemdatei", "deinem code", "deine datei", "bei dir", "von dir"]
        is_asking_about_franks_code = any(k in low for k in franks_code_keywords)

        if self._last_file and not is_asking_about_franks_code and \
           re.search(r"(datei|file|drin\b|drinnen|dieser code|diesen code|diese datei|this file)", low):
            # Show the user's ACTUAL message, not a truncated action prompt
            self._add_message("Du", msg, is_user=True)
            if "debug" in low:
                self._run_file_action_with_query(msg, "If code: find bugs/edge cases and suggest fixes.")
            elif "analys" in low:
                self._run_file_action_with_query(msg, "Analyze the content thoroughly: purpose, structure, key sections, risks.")
            elif "summ" in low or "zusammenfass" in low:
                self._run_file_action_with_query(msg, "Summarize the content (bullet points).")
            elif "erklär" in low or "erklaer" in low or "explain" in low:
                self._run_file_action_with_query(msg, "Explain the content simply.")
            else:
                # Use user's actual question if specific, otherwise default description
                self._run_file_action_with_query(msg, f"User asks: {msg}")
            return

        # Open top result
        if low in ("egal", "mach einfach", "öffne einfach", "oeffne einfach", "open anyway", "just open"):
            if self._pending_results:
                self._add_message("Du", msg, is_user=True)
                open_kind = "darknet_open" if getattr(self, '_pending_darknet', False) else "open"
                self._add_message("Frank", "Opening top result.", is_system=True)
                self._io_q.put((open_kind, self._pending_results[0].url))
                self._clear_results()
                self._pending_darknet = False
            else:
                self._add_message("Du", msg, is_user=True)
                self._add_message("Frank", "No results list open.", is_system=True)
            return

        # Open N
        m = re.match(r"^(open|öffne|oeffne)\s+(\d+)\s*$", low)
        if m:
            self._add_message("Du", msg, is_user=True)
            if not self._pending_results:
                self._add_message("Frank", "No results list open.", is_system=True)
                return
            n = int(m.group(2))
            if 1 <= n <= len(self._pending_results):
                open_kind = "darknet_open" if getattr(self, '_pending_darknet', False) else "open"
                self._io_q.put((open_kind, self._pending_results[n - 1].url))
                self._clear_results()
                self._pending_darknet = False
            else:
                self._add_message("Frank", f"Invalid number (1..{len(self._pending_results)}).", is_system=True)
            return

        # Darknet Search (BEFORE normal search — "suche im darknet ...")
        # Guard: only trigger on commands, NOT on statements like "i think you can search the darknet"
        _STATEMENT_GUARD = re.compile(
            r"^(i\s+think|i\s+believe|it'?s\s|that\s+you|you\s+can|you\s+could|"
            r"he\s+can|she\s+can|amazing|cool|great|wow|nice|"
            r"ich\s+finde|ich\s+glaub|toll\s+dass|es\s+ist)",
            re.IGNORECASE,
        )
        if DARKNET_RE.search(low) and not _STATEMENT_GUARD.search(low):
            # Extract query: strip darknet/tor keywords, verbs, prepositions (typo-tolerant)
            q = re.sub(
                r"((?:se[ae]?r?ch|search|find|look(?:\s*(?:up|for))?|such\w*|query|browse)"
                r"\s+(?:(?:in|on|in\s+the|on\s+the|the|im)\s+)?"
                r"(?:darknet|dark\s*web|deep\s*web|tor(?:\s+network)?|onion|hidden\s*service)\s*"
                r"|(?:darknet|dark\s*web|deep\s*web|tor|onion)\s*"
                r"(?:se[ae]?r?ch|search|find|look|query|market|shop|store|site|forum)\w*\s*"
                r"|(?:(?:in|on|in\s+the|on\s+the)\s+)?"
                r"(?:darknet|dark\s*web|deep\s*web|tor|onion)\s*"
                r"|^(?:se[ae]?r?ch|search|find|look\s+for|look\s+up|browse)\s+"
                r"|nach\s+|for\s+)",
                "", msg, flags=re.IGNORECASE
            ).strip()
            if q:
                self._add_message("Du", msg, is_user=True)
                self._add_message("Frank", f"Darknet search: {q}", is_system=True)
                self._io_q.put(("darknet_search", {"query": q, "limit": 8}))
            return

        # Local file search — "search on the system for X", "find file X",
        # "look on the PC for X", "such auf dem computer nach X"
        # Must come BEFORE web search to intercept system/PC/file keywords
        _fs_match = FILE_SEARCH_RE.search(low) or FILE_SEARCH_ALT_RE.search(low)
        if _fs_match:
            q = _fs_match.group(_fs_match.lastindex).strip().strip("\"'")
            if q:
                self._add_message("Du", msg, is_user=True)
                self._add_message("Frank", f"Searching system for: {q}", is_system=True)
                self._io_q.put(("file_search", {"query": q}))
                return

        # Search (web) — typo-tolerant: "search X", "serch for X",
        # "search in the web for X", "suche nach X", "such mal X"
        _WEB_SEARCH_RE = re.compile(
            r"^(?:se[ae]?r?ch|search|such\w*)\s+"
            r"(?:(?:in\s+)?(?:the\s+)?(?:web|internet|net|google|bing)\s+(?:for\s+|nach\s+)?)?"
            r"(?:for\s+|nach\s+|mal\s+)?",
            re.IGNORECASE,
        )
        ws_match = _WEB_SEARCH_RE.match(low)
        if ws_match:
            q = msg[ws_match.end():].strip()
            if q:
                self._add_message("Du", msg, is_user=True)
                self._add_message("Frank", f"Searching for: {q}", is_system=True)
                self._io_q.put(("search", {"query": q, "limit": 8}))
            return

        # URL Fetch - Direct webpage content extraction
        fetch_match = URL_FETCH_RE.search(msg)
        if fetch_match:
            url = fetch_match.group(2) if fetch_match.lastindex >= 2 else fetch_match.group(1)
            # Ensure we got the URL part (group with http)
            if not url.startswith("http"):
                # Try to find URL in the match groups
                for i in range(fetch_match.lastindex or 0, 0, -1):
                    g = fetch_match.group(i)
                    if g and g.startswith("http"):
                        url = g
                        break
            if url.startswith("http"):
                self._add_message("Du", msg, is_user=True)
                self._add_message("Frank", f"Fetching page: {url[:60]}...", is_system=True)
                self._io_q.put(("fetch_url", {"url": url}))
                return

        # RSS/Atom Feed reading
        rss_match = RSS_FEED_RE.search(msg)
        if rss_match:
            url = rss_match.group(2)
            self._add_message("Du", msg, is_user=True)
            self._add_message("Frank", f"Reading feed: {url[:60]}...", is_system=True)
            self._io_q.put(("rss_feed", {"url": url}))
            return

        # News - Pre-configured category-based news
        if NEWS_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._add_message("Frank", "Getting latest news...", is_system=True)
            self._io_q.put(("news", {"msg": msg}))
            return

        # ── Inventory queries: "what games/snaps/apps do i have" ──────
        # Single intent detector covers all fuzzy/colloquial English + German
        _inv = _detect_inventory_query(low)
        if _inv:
            self._add_message("Du", msg, is_user=True)
            if _inv == "games":
                self._io_q.put(("steam_list", {}))
            elif _inv == "apps":
                self._io_q.put(("app_list", {"filter_type": "all"}))
            elif _inv.startswith("pkg:"):
                self._io_q.put(("package_list", {"backend": _inv[4:]}))
            return

        # Steam: Close game
        if STEAM_CLOSE_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("steam_close", {}))
            return

        # App allow request (e.g., "erlaube Firefox", "allow Firefox")
        allow_match = APP_ALLOW_RE.match(msg)
        if allow_match:
            app_name = allow_match.group(2).strip()
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("app_allow", {"app": app_name}))
            return

        # App close request (e.g., "schließe Firefox", "beende die App")
        close_match = APP_CLOSE_RE.search(msg)
        if close_match and close_match.group(4):
            app_name = close_match.group(4).strip()
            if app_name and not STEAM_CLOSE_RE.search(low):  # Don't conflict with steam close
                self._add_message("Du", msg, is_user=True)
                self._io_q.put(("app_close", {"app": app_name}))
                return

        # NOTE: App list queries are now handled by _detect_inventory_query() above

        # Open => check App Registry first, then Steam games, then web search
        if low.startswith("öffne ") or low.startswith("oeffne ") or low.startswith("open ") or low.startswith("starte ") or low.startswith("start ") or low.startswith("launch ") or low.startswith("spiele ") or low.startswith("play "):
            q = msg.split(" ", 1)[1].strip()

            # Direct URL - open immediately
            if re.match(r"^https?://", q):
                self._add_message("Du", msg, is_user=True)
                self._io_q.put(("open", q))
                return

            # File path - handle as file
            if q.startswith("/") or q.startswith("~"):
                self._add_message("Du", msg, is_user=True)
                self._add_message("Frank", f"Reading file: {q}...", is_system=True)
                self._chat_q.put(("read_file", {"path": q, "user_query": msg}))
                return

            # Try App Registry first - unified app/steam launcher
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("app_open", {"app": q, "from_user_query": msg}))
            return

        # Self-awareness queries - Frank reflects on himself using Core-Awareness
        # BUT only if user is NOT asking about something specific (pdf, file, etc.)
        if SELF_AWARE_RE.search(low) and not SELF_AWARE_EXCLUDE_RE.search(low):
            self._add_message("Du", msg, is_user=True)

            # REVERSED LOGIC: Only show static report for SIMPLE self-awareness queries.
            # Simple = short "was bist du", "beschreibe dich", "wie komplex bist du"
            # Everything else (complex, analytical, hypothetical) goes to LLM with context.
            is_simple = len(msg.strip()) < 50 and bool(re.search(
                r"^(was\s+bist\s+du|wer\s+bist\s+du|beschreibe?\s+dich|"
                r"wie\s+komplex|erkläre?\s+dich|dein\s+system\b$|dein\s+code\b$|"
                r"woraus\s+bestehst|wie\s+bist\s+du\s+gebaut|"
                r"überblick|deine\s+komponenten)",
                low
            ))

            if is_simple:
                LOG.debug(f"Simple self-awareness query, showing static report")
                result = _core_reflect()
                if result and result.get("ok"):
                    reflection = result.get("reflection", "I can't analyze myself right now.")
                    self._add_message("Frank", reflection)
                else:
                    self._add_message("Frank", "I can't access my self-analysis right now.", is_system=True)
                return

            # COMPLEX QUESTION about self/code: Send to LLM with system context
            LOG.debug(f"Complex self-awareness question, routing to LLM with context")
            context_parts = []
            result = _core_reflect()
            if result and result.get("ok"):
                reflection = result.get("reflection", "")
                if reflection:
                    context_parts.append(f"[Your system overview:\n{reflection[:400]}...]")

            context_parts.append("[The user is asking a deep question about your code/system. "
                               "Answer thoughtfully and address the specific question. "
                               "Do NOT give a generic system report, but answer the concrete question.]")

            ctx = "\n".join(context_parts)
            llm_text = f"{ctx}\n\nUser asks: {msg}"
            self._chat_q.put(("chat", {"msg": llm_text, "max_tokens": 800, "timeout_s": 60, "task": "chat.deep", "force": "llama"}))
            return

        # Features/capabilities queries - what can Frank do?
        if FEATURES_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            result = _core_features()
            if result and result.get("ok"):
                features_text = result.get("features_text", "I couldn't list my features.")
                self._add_message("Frank", features_text)
            else:
                # Fallback: use overlay capabilities registry
                try:
                    from overlay.capabilities import get_capabilities_summary
                    self._add_message("Frank", get_capabilities_summary())
                except Exception as e:
                    LOG.error(f"Capabilities error: {e}", exc_info=True)
                    self._add_message("Frank", "I can't access my feature list right now.", is_system=True)
            return

        # Code-specific queries - asking about specific modules/files in Frank's code
        # Must be checked BEFORE FS_HINTS_RE to avoid filesystem handler
        if CODE_MODULE_RE.search(low):
            self._add_message("Du", msg, is_user=True)

            # Check if asking about general categories (tools, modules, system)
            if re.search(r'deine[rn]?\s+tools?\b', low) and not re.search(r'(chat_overlay|toolboxd|core_awareness|app_registry)', low):
                # User asks about tools in general - show summary
                summary = _core_summary()
                if summary and summary.get("ok"):
                    s = summary.get("summary", {})
                    response = f"I have **{s.get('total_modules', 0)} modules** in my system:\n\n"
                    response += f"- **{s.get('core_modules', 0)}** core modules (main components)\n"
                    response += f"- **{s.get('tools', 0)}** tools (utilities)\n"
                    response += f"\nLast scan: {s.get('last_scan', 'unknown')[:10]}"
                    self._add_message("Frank", response)
                else:
                    self._add_message("Frank", "I can't access my system overview right now.", is_system=True)
                return

            # Extract module name
            query = None
            known_modules = ['chat_overlay', 'toolboxd', 'core_awareness', 'app_registry',
                           'vision_module', 'steam_integration', 'personality', 'overlay']
            for mod in known_modules:
                if mod in low:
                    query = mod
                    break
            if not query:
                file_match = re.search(r'(\w+(?:_\w+)*\.py)', low)
                module_match = re.search(r'(?:das|über|zum?)\s+(\w+(?:[-_]\w+)*)\s*(?:modul|tool)?', low)
                if file_match:
                    query = file_match.group(1).replace('.py', '')
                elif module_match:
                    query = module_match.group(1)
            if not query:
                query = "chat_overlay"

            # REVERSED LOGIC: Only show static report for SIMPLE queries.
            # Simple = short question that just asks "what is/does module X?"
            # Everything else (complex, analytical, hypothetical) goes to LLM with context.
            is_simple_technical = bool(re.search(
                r"^(was\s+(macht|ist|kann)|erkläre?\s+|beschreibe?\s+|"
                r"zeig\s+mir\s+|schau\s+mal\s+nach|"
                r"was\s+weißt\s+du\s+über|erzähl\s+mir\s+(was\s+über|über)|"
                r"show\s+me|what\s+(is|does)|explain|describe)\b",
                low
            ))
            # Also simple if the entire message is very short and just names a module
            is_very_short = len(msg.strip()) < 50

            if is_simple_technical and is_very_short:
                LOG.debug(f"Simple technical query for module '{query}', showing static report")
                result = _core_reflect(query)
                if result and result.get("ok"):
                    reflection = result.get("reflection", "")
                    if reflection and "kenne kein Modul" not in reflection:
                        self._add_message("Frank", reflection)
                    else:
                        self._add_message("Frank", f"I don't have a module named '{query}' in my code.")
                else:
                    self._add_message("Frank", "I can't access my code analysis right now.", is_system=True)
                return

            # COMPLEX QUESTION: Send to LLM with module context
            LOG.debug(f"Complex code question detected, routing to LLM with context for '{query}'")
            context_parts = []

            # Get module info for grounding
            result = _core_reflect(query)
            if result and result.get("ok"):
                reflection = result.get("reflection", "")
                if reflection and "kenne kein Modul" not in reflection:
                    context_parts.append(f"[Technical context for '{query}':\n{reflection[:400]}...]")

            # Check for hallucination trap
            if HALLUCINATION_TRAP_RE.search(low):
                context_parts.append("[IMPORTANT: The user is asking about something that may NOT exist. "
                                   "Do NOT invent features! If you don't know it, honestly say it doesn't exist.]")

            context_parts.append("[The user is asking a complex question about your code. "
                               "Answer the SPECIFIC question thoughtfully. "
                               "Do NOT give a generic module report, but address the specific question.]")

            ctx = "\n".join(context_parts)
            llm_text = f"{ctx}\n\nUser asks: {msg}"
            self._chat_q.put(("chat", {"msg": llm_text, "max_tokens": 800, "timeout_s": 60, "task": "chat.deep", "force": "llama"}))
            return

        # USB device management — eject > unmount > mount > storage list
        if USB_EJECT_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            device = re.sub(r"(auswerfen|eject|sicher\w*\s*entfern\w*|abziehen|usb|den|die|das|bitte)\s*", "", msg, flags=re.IGNORECASE).strip() or "auto"
            self._io_q.put(("usb_eject", {"device": device}))
            return
        if USB_UNMOUNT_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            device = re.sub(r"(unmount\w*|aushäng\w*|aushaeng\w*|abmeld\w*|usb|den|die|das|bitte)\s*", "", msg, flags=re.IGNORECASE).strip() or "auto"
            self._io_q.put(("usb_unmount", {"device": device}))
            return
        if USB_MOUNT_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            device = re.sub(r"(mount\w*|einhäng\w*|einhaeng\w*|einbind\w*|usb|den|die|das|bitte)\s*", "", msg, flags=re.IGNORECASE).strip() or "auto"
            self._io_q.put(("usb_mount", {"device": device}))
            return
        if USB_STORAGE_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("usb_storage", {}))
            return

        # Printer status / print file — catch BEFORE generic system control
        # (SYSTEM_CONTROL_RE also matches "drucker" but routes to detection/setup)
        if PRINTER_STATUS_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("printer_status", {}))
            return

        pm_file_early = PRINT_FILE_RE.search(msg)
        if pm_file_early:
            file_path = ""
            if pm_file_early.group(6):
                file_path = pm_file_early.group(6).strip()
            else:
                import re as _re
                path_m = _re.search(r'["\']?([~/][^\s"\']+)["\']?', msg)
                if path_m:
                    file_path = path_m.group(1)
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("print_file", {"path": file_path, "user_msg": msg}))
            return

        # NOTE: Package list queries are now handled by _detect_inventory_query() above

        # System Control - File org, WiFi, Bluetooth, Audio, Display, Printers
        # Check BEFORE ADI since system control handles confirmations and actions
        if SYSTEM_CONTROL_AVAILABLE and SYSTEM_CONTROL_RE.search(low):
            handled, response = sc_process(msg)
            if handled and response:
                self._add_message("Du", msg, is_user=True)
                self._add_message("Frank", response)
                return
            # If not fully handled, fall through to other handlers

        # ADI (Adaptive Display Intelligence) - Display/layout configuration
        # Check BEFORE desktop hints since ADI is more specific
        if ADI_HINTS_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._handle_adi_request(msg)
            return

        # Desktop/Screenshot detection - automatically take screenshot
        if DESKTOP_HINTS_RE.search(low) and not FS_HINTS_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._add_message("Frank", "Looking at your desktop...", is_system=True)
            self._chat_q.put(("screenshot", {"user_query": msg}))
            return

        # Filesystem listing detection - ONLY proceed with explicit path
        # CRITICAL: Never default to ~ without clear user intent (prevents false triggers)
        if FS_HINTS_RE.search(low):
            # Try to extract explicit path from message
            path = None
            path_patterns = [
                r"(?:in|von|im|auf)\s+[\"']?([~/][^\s\"']+)[\"']?",
                r"\b(home)\b",
                r"\b(desktop)\b",
                r"\b(dokumente|documents)\b",
                r"\b(downloads)\b",
                r"\b(bilder|pictures)\b",
                r"\b(videos)\b",
                r"\b(musik|music)\b",
            ]

            for pattern in path_patterns:
                m = re.search(pattern, low)
                if m:
                    matched = m.group(1) if m.lastindex else m.group(0)
                    if matched in ["home"]:
                        path = "~"
                    elif matched in ["desktop"]:
                        path = "~/Desktop"
                    elif matched in ["dokumente", "documents"]:
                        path = "~/Documents"
                    elif matched in ["downloads"]:
                        path = "~/Downloads"
                    elif matched in ["bilder", "pictures"]:
                        path = "~/Pictures"
                    elif matched in ["videos"]:
                        path = "~/Videos"
                    elif matched in ["musik", "music"]:
                        path = "~/Music"
                    elif matched.startswith(("~", "/", ".")):
                        path = matched
                    break

            # ONLY proceed if we found an explicit path
            if path:
                self._add_message("Du", msg, is_user=True)
                LOG.info(f"Filesystem request: {path}")
                self._io_q.put(("fs_list", {"path": path, "user_query": msg}))
                return
            # No path found - fall through to normal chat (don't trigger fs_list)

        # User name introduction detection ("mein name ist X", "ich bin Laura", etc.)
        if USER_NAME_RE.search(msg):
            try:
                import sys
                try:
                    from config.paths import AICORE_ROOT as _AICORE_ROOT
                except ImportError:
                    from pathlib import Path as _P
                    _AICORE_ROOT = _P(__file__).resolve().parents[3]
                sys.path.insert(0, str(_AICORE_ROOT))
                from tools.user_profile import extract_name, set_user_name, get_user_name
                name = extract_name(msg)
                if name:
                    old_name = get_user_name()
                    set_user_name(name)
                    self._add_message("Du", msg, is_user=True)
                    if old_name and old_name.lower() != name.lower():
                        reply = f"Alright, so you're {name} now. Never could remember the old one anyway."
                    else:
                        reply = f"Got it, {name}. I'll remember that."
                    self._add_message("Frank", reply)
                    # Update all existing user bubbles with new name
                    self._update_user_bubbles(name)
                    LOG.info(f"User name set to: {name}")
                    return
            except Exception as e:
                LOG.warning(f"Name extraction failed: {e}")

        # Email commands — must come before skill keyword matching
        # Order: delete → unread check → read single → list → general email

        # Helper: detect folder from natural language
        def _detect_email_folder(text: str) -> str:
            t = text.lower()
            if "spam" in t:
                return "[Gmail]/Spam"
            if "papierkorb" in t or "trash" in t or "mülleimer" in t or "muelleimer" in t:
                return "[Gmail]/Papierkorb"
            if "gesendet" in t or "sent" in t or "gesendete" in t:
                return "[Gmail]/Gesendet"
            if "entwürf" in t or "entwuerf" in t or "draft" in t:
                return "[Gmail]/Entw&APw-rfe"
            if "wichtig" in t or "important" in t:
                return "[Gmail]/Wichtig"
            if "alle nachricht" in t or "all mail" in t or "alle mail" in t:
                return "[Gmail]/Alle Nachrichten"
            # "diese" = last notified folder context
            if "diese" in t and hasattr(self, '_last_email_notification_folder'):
                return self._last_email_notification_folder
            return "INBOX"

        # Friendly folder names for display
        _FOLDER_DISPLAY = {
            "INBOX": "Inbox",
            "[Gmail]/Spam": "Spam",
            "[Gmail]/Papierkorb": "Trash",
            "[Gmail]/Gesendet": "Sent",
            "[Gmail]/Entw&APw-rfe": "Drafts",
            "[Gmail]/Wichtig": "Important",
            "[Gmail]/Alle Nachrichten": "All Mail",
        }

        # Compose new email — /compose, "write an email to X", "schreib eine mail"
        if EMAIL_COMPOSE_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            # Try to extract recipient from message (e.g., "mail an john@example.com")
            import re as _re
            _to_match = _re.search(r"(?:an|to|für|for)\s+(\S+@\S+)", msg, _re.IGNORECASE)
            _to_hint = _to_match.group(1) if _to_match else ""
            self._io_q.put(("email_compose_intent", {"user_msg": msg, "to_hint": _to_hint}))
            return

        em = EMAIL_DELETE_RE.search(low)
        if em:
            self._add_message("Du", msg, is_user=True)
            folder = _detect_email_folder(low)
            # Default to spam for delete unless user specified otherwise
            if folder == "INBOX" and not ("inbox" in low or "posteingang" in low):
                folder = "[Gmail]/Spam"
            display = _FOLDER_DISPLAY.get(folder, folder)
            # Get email count for confirmation
            count_text = ""
            try:
                from overlay.services.toolbox import _toolbox_call
                result = _toolbox_call("/email/list", {"folder": folder, "limit": 500}, timeout_s=10.0)
                if result and result.get("ok"):
                    n = result.get("count", 0)
                    count_text = f" ({n} emails)" if n > 0 else " (empty)"
            except Exception:
                pass
            # Safety: confirm batch deletion with count
            self._pending_email_delete = {"folder": folder, "delete_all": True, "user_msg": msg}
            self._add_message("Frank",
                f"Should I really delete all emails in {display}{count_text}? Reply with 'yes' or 'no'.",
                is_system=True)
            return

        # "was steht in der neuen mail", "lies die letzte mail" → show card list (unread first)
        if EMAIL_READ_LATEST_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            folder = _detect_email_folder(low)
            self._io_q.put(("email_list_cards", {"folder": folder, "unread_only": True}))
            return

        em = EMAIL_UNREAD_RE.search(low)
        if em:
            self._add_message("Du", msg, is_user=True)
            folder = _detect_email_folder(low)
            self._io_q.put(("email_list_cards", {"folder": folder, "unread_only": True}))
            return

        em = EMAIL_READ_RE.search(msg)
        if em:
            self._add_message("Du", msg, is_user=True)
            query = (em.group(4) or "").strip()
            folder = _detect_email_folder(low)
            self._io_q.put(("email_detail", {"folder": folder, "query": query}))
            return

        em = EMAIL_LIST_RE.search(low)
        if em:
            self._add_message("Du", msg, is_user=True)
            folder = _detect_email_folder(low)
            self._io_q.put(("email_list_cards", {"folder": folder}))
            return

        # General email intent fallback — route through LLM with email context
        if EMAIL_GENERAL_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("email_general", {"user_msg": msg}))
            return

        # Calendar commands — delete → create → today → week → list → general
        # DELETE must be checked before CREATE (both can match "delete ... lege an")
        if CALENDAR_DELETE_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("calendar_delete", {"query": msg, "user_msg": msg}))
            return

        if CALENDAR_CREATE_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("calendar_create", {"user_msg": msg}))
            return

        if CALENDAR_TODAY_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("calendar_today", {}))
            return

        if CALENDAR_WEEK_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("calendar_week", {}))
            return

        if CALENDAR_LIST_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("calendar_list", {}))
            return

        if CALENDAR_GENERAL_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("calendar_general", {"user_msg": msg}))
            return

        # Skill keyword matching (trigger installed skills) — checked BEFORE generic
        # handlers (notes, todo, clipboard, etc.) to give skills priority
        try:
            from skills import get_skill_registry
            _matched_skill = get_skill_registry().match_keywords(low)
            if _matched_skill:
                self._add_message("Du", msg, is_user=True)
                LOG.info(f"Skill matched: {_matched_skill.name} for '{msg[:50]}'")
                self._io_q.put(("skill", {
                    "skill_name": _matched_skill.name,
                    "user_query": msg,
                    "voice": getattr(self, '_pending_voice_session', None) is not None,
                }))
                return
        except Exception as e:
            LOG.error(f"Skill matching error (early): {e}", exc_info=True)

        # Contacts commands — create → delete → search → list → general
        if CONTACTS_CREATE_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("contacts_create", {"user_msg": msg}))
            return

        if CONTACTS_DELETE_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("contacts_delete", {"query": msg, "user_msg": msg}))
            return

        cm = CONTACTS_SEARCH_RE.search(msg)
        if cm:
            search_query = cm.group(2).strip()
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("contacts_search", {"query": search_query}))
            return

        if CONTACTS_LIST_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("contacts_list", {}))
            return

        if CONTACTS_GENERAL_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("contacts_general", {"user_msg": msg}))
            return

        # Notes/Memos — list → search → delete → create → general
        # (non-ambiguous patterns first, create last to avoid false matches)
        if NOTES_LIST_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("notes_list", {}))
            return

        nm = NOTES_SEARCH_RE.search(msg)
        if nm:
            search_query = nm.group(4).strip() if nm.lastindex >= 4 else nm.group(1).strip()
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("notes_search", {"query": search_query}))
            return

        if NOTES_DELETE_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("notes_delete", {"query": msg, "user_msg": msg}))
            return

        nm = NOTES_CREATE_RE.search(msg)
        if nm:
            note_content = nm.group(2).strip()
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("notes_create", {"user_msg": msg, "content": note_content}))
            return

        if len(msg) < 120 and NOTES_GENERAL_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("notes_general", {"user_msg": msg}))
            return

        # Skip keyword-based command routing for long messages (>120 chars).
        # Long messages are conversations, not commands. Commands are short
        # ("zeig meine aufgaben", "erinner mich an meeting"). This prevents
        # false matches on words like "Erinnerungen" (memory vs reminder),
        # "Prozesse" (philosophical vs sysadmin), etc.
        _skip_keyword_routing = len(msg) > 120

        # Todo/Tasks — list → complete → delete → create → general
        # (non-ambiguous patterns first, create last to avoid false matches)
        if not _skip_keyword_routing and TODO_LIST_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("todo_list", {}))
            return

        if not _skip_keyword_routing and TODO_COMPLETE_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("todo_complete", {"query": msg, "user_msg": msg}))
            return

        if not _skip_keyword_routing and TODO_DELETE_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("todo_delete", {"query": msg, "user_msg": msg}))
            return

        if not _skip_keyword_routing:
            tm = TODO_CREATE_RE.search(msg)
            if tm:
                todo_content = tm.group(2).strip()
                self._add_message("Du", msg, is_user=True)
                self._io_q.put(("todo_create", {"user_msg": msg, "content": todo_content}))
                return

        if not _skip_keyword_routing and TODO_GENERAL_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("todo_general", {"user_msg": msg}))
            return

        # Clipboard History — clear → restore → search → delete → list → general
        if not _skip_keyword_routing and CLIPBOARD_CLEAR_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("clipboard_clear", {}))
            return

        if not _skip_keyword_routing:
            cm = CLIPBOARD_RESTORE_RE.search(msg)
            if cm:
                entry_id_str = cm.group(3)
                entry_id = int(entry_id_str) if entry_id_str else 0
                self._add_message("Du", msg, is_user=True)
                self._io_q.put(("clipboard_restore", {"entry_id": entry_id, "query": msg}))
                return

        if not _skip_keyword_routing:
            cm = CLIPBOARD_SEARCH_RE.search(msg)
            if cm:
                search_query = cm.group(3).strip()
                self._add_message("Du", msg, is_user=True)
                self._io_q.put(("clipboard_search", {"query": search_query}))
                return

        if not _skip_keyword_routing:
            cm = CLIPBOARD_DELETE_RE.search(msg)
            if cm:
                entry_id_str = cm.group(4) if cm.lastindex and cm.lastindex >= 4 else None
                entry_id = int(entry_id_str) if entry_id_str else 0
                self._add_message("Du", msg, is_user=True)
                self._io_q.put(("clipboard_delete", {"entry_id": entry_id, "query": msg}))
                return

        if not _skip_keyword_routing and CLIPBOARD_LIST_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("clipboard_list", {}))
            return

        if not _skip_keyword_routing and CLIPBOARD_GENERAL_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("clipboard_list", {}))
            return

        # ── Password Manager ──────────────────────────────────
        # Order: autotype → copy → search → list → popup → general

        pm = PASSWORD_AUTOTYPE_RE.search(msg)
        if pm:
            query = (pm.group(3) or pm.group(4) or "").strip()
            if query:
                self._add_message("Du", msg, is_user=True)
                self._io_q.put(("password_autotype", {"query": query}))
                return

        pm = PASSWORD_COPY_RE.search(msg)
        if pm:
            query = (pm.group(3) or pm.group(6) or "").strip()
            if query:
                self._add_message("Du", msg, is_user=True)
                self._io_q.put(("password_copy", {"query": query}))
                return

        pm = PASSWORD_SEARCH_RE.search(msg)
        if pm:
            query = (pm.group(3) or pm.group(4) or pm.group(7) or "").strip()
            if query:
                self._add_message("Du", msg, is_user=True)
                self._io_q.put(("password_search", {"query": query}))
                return

        if PASSWORD_LIST_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("password_list", {}))
            return

        if PASSWORD_POPUP_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("password_popup", {}))
            return

        if PASSWORD_GENERAL_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("password_popup", {}))
            return

        # ── QR Code ──────────────────────────────────────────────
        # Order: generate → camera → screen scan → general

        qm = QR_GENERATE_RE.search(msg)
        if qm:
            data = (qm.group(3) or qm.group(5) or "").strip()
            if data:
                self._add_message("Du", msg, is_user=True)
                self._io_q.put(("qr_generate", {"data": data}))
                return

        if QR_SCAN_CAM_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("qr_scan_camera", {}))
            return

        if QR_SCAN_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("qr_scan_screen", {}))
            return

        if QR_GENERAL_RE.search(low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("qr_scan_screen", {}))
            return

        # Unit/Currency conversion — "150 USD in Euro", "500 MB in GB"
        # Check natural language pattern first (more specific), then direct pattern
        cm = CONVERT_QUERY_RE.search(msg) if len(msg) < 120 else None
        if cm:
            val_str = cm.group(1).replace(",", ".")
            try:
                val = float(val_str)
                self._add_message("Du", msg, is_user=True)
                self._io_q.put(("convert", {
                    "user_msg": msg, "value": val,
                    "from_unit": cm.group(2).strip(), "to_unit": cm.group(3).strip(),
                }))
                return
            except ValueError:
                pass

        cm = CONVERT_RE.search(msg) if len(msg) < 120 else None
        if cm:
            val_str = cm.group(1).replace(",", ".")
            try:
                val = float(val_str)
                self._add_message("Du", msg, is_user=True)
                self._io_q.put(("convert", {
                    "user_msg": msg, "value": val,
                    "from_unit": cm.group(2).strip(), "to_unit": cm.group(3).strip(),
                }))
                return
            except ValueError:
                pass

        # Skill system — explicit commands + keyword matching
        if low in ("skill reload", "skills neu laden", "skills reload"):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("skill_reload", {}))
            return

        # Skill list: "welche skills hast du", "deine skills", "skill liste"
        if re.search(r"(welche\s+skills|deine\s+skills|skill\s*liste|meine\s+skills|"
                     r"skills?\s+auflisten|skills?\s+anzeigen|zeig\s+(?:mir\s+)?(?:deine\s+)?skills|"
                     r"hast\s+du\s+skills|was\s+fuer\s+skills)", low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("skill_list", {}))
            return

        # Skill browse: "openclaw skills", "verfuegbare skills", "skill store"
        if re.search(r"(openclaw\s+skills?|verfuegbare\s+skills?|verfügbare\s+skills?|"
                     r"skill\s*(store|marketplace|marktplatz|katalog|shop)|"
                     r"neue\s+skills?\s*(suchen|finden|zeigen|browse)|"
                     r"skills?\s+(?:zum\s+)?(?:download|herunterladen|installieren))", low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("skill_browse", {"query": msg}))
            return

        # Skill install: "fuege skill X hinzu", "installiere skill X", "add skill X"
        _install_m = re.search(
            r"(?:fuege?|füge?|add)\s+(?:den\s+)?skill\s+(\S+)\s+hinzu|"
            r"(?:installiere?|install)\s+(?:den\s+)?skill\s+(\S+)|"
            r"skill\s+(\S+)\s+(?:installieren|hinzufuegen|hinzufügen|adden)",
            low
        )
        if _install_m:
            slug = _install_m.group(1) or _install_m.group(2) or _install_m.group(3)
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("skill_install", {"slug": slug}))
            return

        # Skill uninstall: "entferne skill X", "deinstalliere skill X"
        _uninstall_m = re.search(
            r"(?:entferne?|deinstalliere?|uninstall|remove|loesche?|lösche?)\s+(?:den\s+)?skill\s+(\S+)|"
            r"skill\s+(\S+)\s+(?:entfernen|deinstallieren|loeschen|löschen|removen)",
            low
        )
        if _uninstall_m:
            slug = _uninstall_m.group(1) or _uninstall_m.group(2)
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("skill_uninstall", {"slug": slug}))
            return

        # Skill updates: "skill updates", "skills aktualisieren"
        if re.search(r"skill\s*updates?|updates?\s+(?:fuer|für)\s+skills|skills?\s+aktualisier", low):
            self._add_message("Du", msg, is_user=True)
            self._io_q.put(("skill_updates", {}))
            return

        # Normal chat
        self._add_message("Du", msg, is_user=True)
        task = "code.edit" if CODE_HINTS_RE.search(msg) else "chat.fast"
        # Dynamic token budget: short for casual, more for explicit detail requests
        if task == "code.edit":
            max_tokens = 500
        elif re.search(r"\b(detail|explain|ausf[uü]hrlich|erzähl|erklär|tell me about|describe|how does|wie funktioniert)\b", msg, re.IGNORECASE):
            max_tokens = 600
        else:
            max_tokens = 150
        self._chat_q.put(("chat", {"msg": msg, "max_tokens": max_tokens, "timeout_s": DEFAULT_TIMEOUT_S, "task": task, "force": None}))

    # ---------- System Restart Worker ----------
    def _do_system_restart_worker(self):
        """Restart all Frank backend services, then the overlay itself."""
        import subprocess

        self._ui_call(lambda: self._add_message(
            "Frank", "Restarting all Frank services...", is_system=True))

        # Discover active services
        try:
            r = subprocess.run(
                ["systemctl", "--user", "list-units", "--type=service",
                 "--state=active,activating", "--no-pager", "--plain", "--no-legend"],
                capture_output=True, text=True, timeout=10,
            )
            services = []
            for line in r.stdout.strip().split("\n"):
                parts = line.strip().split()
                if parts and (parts[0].startswith("aicore-") or parts[0].startswith("frank-")):
                    services.append(parts[0])
        except Exception:
            services = []

        if not services:
            services = [
                "aicore-router.service", "aicore-core.service",
                "aicore-llama3-gpu.service", "aicore-toolboxd.service",
                "aicore-webd.service", "aicore-modeld.service",
                "aicore-desktopd.service", "aicore-consciousness.service",
                "aicore-invariants.service", "aicore-asrs.service",
                "aicore-genesis.service", "aicore-genesis-watchdog.service",
                "aicore-entities.service", "aicore-gaming-mode.service",
                "aicore-ingestd.service", "aicore-whisper-gpu.service",
                "frank-overlay.service",
            ]

        # Split: backend first, overlay last
        backend = [s for s in services if "frank-overlay" not in s]
        has_overlay = any("frank-overlay" in s for s in services)

        failed = []
        succeeded = []

        for svc in backend:
            try:
                r = subprocess.run(
                    ["systemctl", "--user", "restart", svc],
                    capture_output=True, text=True, timeout=30,
                )
                if r.returncode == 0:
                    succeeded.append(svc.replace(".service", ""))
                else:
                    failed.append(svc.replace(".service", ""))
            except Exception:
                failed.append(svc.replace(".service", ""))

        status = f"Restarted {len(succeeded)}/{len(backend)} backend services."
        if failed:
            status += f"\nFailed: {', '.join(failed)}"

        if has_overlay:
            status += "\nRestarting overlay in 3s..."

        self._ui_call(lambda s=status: self._add_message("Frank", s, is_system=True))

        if has_overlay:
            time.sleep(3)
            subprocess.Popen(
                ["systemctl", "--user", "restart", "frank-overlay.service"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
