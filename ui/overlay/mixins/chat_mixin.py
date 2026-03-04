"""
ChatMixin -- core LLM interaction logic.

Extracted from chat_overlay_monolith.py lines ~5560-5928.
Handles:
  - Building conversation context from chat history
  - AKAM auto-search for factual questions
  - System control integration
  - Sending to core API
  - Processing response
  - Voice routing
  - Wallpaper events
  - Chat history persistence triggers
"""

import re
import time
from overlay.constants import (
    LOG, COLORS, FRANK_IDENTITY, DEFAULT_MAX_TOKENS, DEFAULT_TIMEOUT_S,
    MAX_SAFE_TOKENS, CHARS_PER_TOKEN,
    HALLUCINATION_TRAP_RE, DESKTOP_HINTS_RE,
    SYSTEM_CONTROL_RE, ADI_HINTS_RE,
    SYS_HINTS_RE, USB_HINTS_RE, NET_HINTS_RE, DRIVER_HINTS_RE, HW_DEEP_HINTS_RE,
    _EPQ_AVAILABLE, _world_context_inject, _news_context_inject,
)
# E-PQ personality functions (may be stubs if module not available)
try:
    from overlay.constants import record_interaction, get_personality_context, process_event
except ImportError:
    def record_interaction(*a, **k): pass
    def get_personality_context(*a, **k): return ""
    def process_event(*a, **k): pass
from overlay.token_utils import _estimate_tokens, _calculate_response_tokens
from overlay.services.core_api import _core_chat, _core_chat_stream
from overlay.services.search import _should_auto_search, _akam_quick_search, _check_local_knowledge
from overlay.services.toolbox import _get_usb_devices, _get_network_info, _get_driver_info, _get_hardware_deep
from overlay.context_builder import (
    _format_usb_context, _format_network_context,
    _format_driver_context, _format_hardware_deep_context,
)
from overlay.services.system_control import SYSTEM_CONTROL_AVAILABLE, sc_process


# ── World Experience: Observation Bridge ──────────────────────────
def _observe_chat_world(cause_name: str, effect_name: str,
                        cause_type: str = "social", effect_type: str = "cognitive",
                        relation: str = "triggers", evidence: float = 0.2,
                        **meta):
    """Fire-and-forget world experience observation from chat."""
    try:
        from tools.world_experience_daemon import get_daemon
        get_daemon().observe(
            cause_name=cause_name, effect_name=effect_name,
            cause_type=cause_type, effect_type=effect_type,
            relation=relation, evidence=evidence,
            metadata_effect=meta if meta else None,
        )
    except Exception as _we_err:
        LOG.debug("World experience observation failed: %s", _we_err)

# ── Consciousness Stream: Output-Feedback-Loop ──
_CONSCIOUSNESS_AVAILABLE = False
_consciousness_daemon = None
_response_analyzer = None
_self_consistency = None
try:
    import sys as _sys_init
    from pathlib import Path as _P_init
    try:
        from config.paths import AICORE_ROOT as _init_root
    except ImportError:
        _init_root = _P_init(__file__).resolve().parents[3]  # mixins/ -> overlay/ -> ui/ -> opt/aicore
    _sys_init.path.insert(0, str(_init_root))
    from services.response_analyzer import analyze_response as _analyze_response
    from services.self_consistency import check_self_consistency as _check_self_consistency
    _response_analyzer = _analyze_response
    _self_consistency = _check_self_consistency
    try:
        from services.consciousness_daemon import get_consciousness_daemon
        _consciousness_daemon = get_consciousness_daemon
        _CONSCIOUSNESS_AVAILABLE = True
        LOG.info("Consciousness Stream integration active")
    except Exception as _e:
        LOG.debug("Consciousness daemon not available: %s", _e)
except ImportError as _e:
    LOG.debug("Response analyzer/self-consistency not available: %s", _e)

# ── Titan: Episodic Memory (semantic retrieval) ──
_TITAN_AVAILABLE = False
_get_titan = None
try:
    import sys as _sys_titan
    from pathlib import Path as _P_titan
    try:
        from config.paths import AICORE_ROOT as _titan_root
    except ImportError:
        _titan_root = _P_titan(__file__).resolve().parents[3]  # mixins/ -> overlay/ -> ui/ -> opt/aicore
    _sys_titan.path.insert(0, str(_titan_root))
    from tools.titan.titan_core import get_titan as _get_titan_fn
    _get_titan = _get_titan_fn
    _TITAN_AVAILABLE = True
    LOG.info("Titan episodic memory integration active")
except Exception as _e:
    LOG.debug("Titan not available: %s", _e)

# ── Entity Session Memory: direct recall from entity DBs ──
_ENTITY_MEMORY_AVAILABLE = False
_ENTITY_DB_DIR = None
_ENTITY_MAP = {
    "atlas": {"db": "atlas.db", "role": "Architecture Mentor", "table_prefix": "atlas"},
    "kairos": {"db": "mirror.db", "role": "Philosophical Mirror", "table_prefix": "mirror"},
    "echo": {"db": "muse.db", "role": "Creative Muse", "table_prefix": "muse"},
    "dr. hibbert": {"db": "therapist.db", "role": "Therapist", "table_prefix": "therapist"},
    "hibbert": {"db": "therapist.db", "role": "Therapist", "table_prefix": "therapist"},
}
_ENTITY_QUESTION_RE = re.compile(
    r"(atlas|kairos|echo|hibbert|dr\.?\s*hibbert"
    r"|entit(y|ies|ät)"
    r"|session(s)?\s+(with|mit)"
    r"|gespr(ä|ae)ch\s+(mit|with)"
    r"|talk(ed|ing)?\s+(to|with)\s+(atlas|kairos|echo|hibbert)"
    r"|sitzung|therapie)",
    re.IGNORECASE,
)
try:
    from pathlib import Path as _P_ent
    _ent_db_dir = _P_ent.home() / ".local" / "share" / "frank" / "db"
    if _ent_db_dir.is_dir():
        _ENTITY_DB_DIR = _ent_db_dir
        _ENTITY_MEMORY_AVAILABLE = True
        LOG.info("Entity session memory integration active (db_dir=%s)", _ent_db_dir)
except Exception as _e:
    LOG.debug("Entity session memory not available: %s", _e)

# ── RPT: Reflection trigger pattern (overlay path) ──
_REFLECT_OVERLAY_RE = re.compile(
    r"(warum\s+(denkst|meinst|glaubst|fuehlst|fuhlst)"
    r"|was\s+bedeutet.*fuer\s+dich"
    r"|deine\s+meinung|was\s+h(ae|ä)ltst\s+du"
    r"|bewusstsein|consciousness"
    r"|was\s+f(ue|ü)hlst\s+du"
    r"|wer\s+bist\s+du\s+wirklich"
    r"|wie\s+siehst\s+du\s+das"
    r"|stell\s+dir\s+vor|was\s+w(ue|ü)rdest\s+du"
    r"|denk\s+nach"
    r"|wie\s+erlebst\s+du"
    r"|was\s+ist\s+dir\s+wichtig"
    r"|hast\s+du\s+gef(ue|ü)hle"
    # English
    r"|why\s+do\s+you\s+think"
    r"|what\s+does.*mean\s+to\s+you"
    r"|your\s+opinion|what\s+do\s+you\s+think"
    r"|what\s+do\s+you\s+feel"
    r"|who\s+are\s+you\s+really"
    r"|how\s+do\s+you\s+see"
    r"|imagine|what\s+would\s+you"
    r"|think\s+about\s+it"
    r"|how\s+do\s+you\s+experience"
    r"|what\s+matters\s+to\s+you"
    r"|do\s+you\s+have\s+feelings)",
    re.IGNORECASE,
)

# ── Language enforcement for 7B models ──
# 7B models mirror the user's language despite system prompt instructions.
# We detect explicit switch commands and add a [Reply in English] nudge otherwise.
_LANG_SWITCH_DE_RE = re.compile(
    r"(antworte|sprich|rede|schreib)\s*(auf|in|bitte)?\s*(deutsch|german)"
    r"|switch\s+to\s+german"
    r"|speak\s+german"
    r"|respond\s+in\s+german"
    r"|auf\s+deutsch\s+(bitte|antworten)",
    re.IGNORECASE,
)
_LANG_SWITCH_EN_RE = re.compile(
    r"(antworte|sprich|rede|schreib)\s*(auf|in|bitte)?\s*(englisch|english)"
    r"|switch\s+(back\s+)?(to\s+)?english"
    r"|speak\s+english"
    r"|respond\s+in\s+english"
    r"|auf\s+englisch\s+(bitte|antworten)",
    re.IGNORECASE,
)
# Module-level default; instance state set in ChatMixin
_DEFAULT_RESPONSE_LANG = "en"


# ── Simple sentiment detection for E-PQ personality events ──
_POSITIVE_WORDS = frozenset([
    "danke", "super", "toll", "geil", "perfekt", "genial", "klasse", "prima",
    "awesome", "great", "thanks", "love", "cool", "nice", "wunderbar",
    "fantastisch", "mega", "stark", "hammer", "top", "gut gemacht", "bravo",
    "brilliant", "spitze", "hervorragend", "excellent", "amazing", "wow",
    "guter job", "gut", "passt", "stimmt", "richtig", "korrekt", "ja genau",
])
_NEGATIVE_WORDS = frozenset([
    "mist", "blöd", "doof", "schlecht", "falsch", "fehler", "wrong", "bad",
    "nervig", "nervt", "sucks", "hate", "stupid", "idiot", "versager",
    "kacke", "quatsch", "unsinn", "bullshit", "nein", "falsch", "broken",
    "kaputt", "geht nicht", "funktioniert nicht", "hilft nicht", "nutzlos",
    "useless", "terrible", "awful", "horrible", "trash", "garbage",
])

def _detect_chat_sentiment(user_msg: str) -> str:
    """Detect sentiment from user message for E-PQ personality events.

    Returns: 'positive', 'negative', or 'neutral'
    """
    low = user_msg.lower()
    pos = sum(1 for w in _POSITIVE_WORDS if w in low)
    neg = sum(1 for w in _NEGATIVE_WORDS if w in low)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def _get_entity_session_context(msg: str) -> str:
    """Query entity databases for session recall when user asks about entities.

    Returns a compact context string with recent session summaries.
    Only called when _ENTITY_QUESTION_RE matches the user message.
    """
    if not _ENTITY_MEMORY_AVAILABLE or not _ENTITY_DB_DIR:
        return ""

    import sqlite3
    from datetime import datetime

    # Determine which entities to query
    msg_lower = msg.lower()
    target_entities = []
    for name, info in _ENTITY_MAP.items():
        if name in msg_lower:
            target_entities.append((name, info))

    # If no specific entity mentioned, query all
    if not target_entities:
        target_entities = list(_ENTITY_MAP.items())
        # Deduplicate (hibbert and dr. hibbert point to same DB)
        seen_dbs = set()
        deduped = []
        for name, info in target_entities:
            if info["db"] not in seen_dbs:
                seen_dbs.add(info["db"])
                deduped.append((name, info))
        target_entities = deduped

    parts = []
    for name, info in target_entities:
        db_path = _ENTITY_DB_DIR / info["db"]
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(str(db_path), timeout=5.0)
            conn.row_factory = sqlite3.Row
            # Get last 3 sessions with summaries
            rows = conn.execute(
                "SELECT session_id, start_time, turns, primary_topic, "
                "summary, mood_start, mood_end, outcome "
                "FROM sessions WHERE summary IS NOT NULL AND summary != '' "
                "ORDER BY start_time DESC LIMIT 3"
            ).fetchall()
            if not rows:
                conn.close()
                continue

            entity_display = name.capitalize()
            if name in ("hibbert", "dr. hibbert"):
                entity_display = "Dr. Hibbert"

            for row in rows:
                ts = datetime.fromtimestamp(row["start_time"])
                time_str = ts.strftime("%Y-%m-%d %H:%M")
                topic = row["primary_topic"] or "general"
                summary = (row["summary"] or "")[:300]
                turns = row["turns"] or 0
                mood_delta = (row["mood_end"] or 0) - (row["mood_start"] or 0)
                parts.append(
                    f"{entity_display} ({info['role']}) — {time_str}, "
                    f"{turns} turns, topic: {topic}, mood Δ{mood_delta:+.2f}. "
                    f"Summary: {summary}"
                )

            # If specific entity asked, also get key messages from latest session
            if len(target_entities) <= 2 and rows:
                latest_sid = rows[0]["session_id"]
                msgs = conn.execute(
                    "SELECT speaker, text FROM session_messages "
                    "WHERE session_id = ? ORDER BY turn",
                    (latest_sid,),
                ).fetchall()
                if msgs:
                    transcript_parts = []
                    for m in msgs[-6:]:  # last 6 messages
                        speaker = m["speaker"]
                        text = (m["text"] or "")[:150]
                        transcript_parts.append(f"  {speaker}: {text}")
                    parts.append(
                        f"[Latest {entity_display} transcript excerpt:]\n"
                        + "\n".join(transcript_parts)
                    )
            conn.close()
        except Exception as e:
            LOG.debug("Entity DB query failed for %s: %s", info["db"], e)

    if not parts:
        return ""
    return "[Entity session memory: " + " | ".join(parts) + "]"


class ChatMixin:

    def _draw_status_dot(self, pulse_phase: int = 0):
        """Draw the pulsing status indicator dot with neon cyan glow."""
        self.status_dot.delete("all")

        # Cyberpunk neon cyan pulsing dot
        # Calculate pulse intensity (0-1) for glow effect
        import math
        pulse = 0.5 + 0.5 * math.sin(pulse_phase * 0.3)

        # Draw outer glow (simulated with larger faded circle)
        glow_alpha = int(pulse * 80)
        glow_color = f"#{0:02x}{glow_alpha + 100:02x}{glow_alpha + 100:02x}"
        self.status_dot.create_oval(
            0, 0, 8, 8,
            fill=glow_color,
            outline=""
        )

        # Inner bright dot
        self.status_dot.create_oval(
            1, 1, 7, 7,
            fill=COLORS["neon_cyan"],
            outline=""
        )

        # Schedule next frame for pulsing effect
        self.after(100, lambda: self._draw_status_dot(pulse_phase + 1))

    def _build_conversation_context(self, max_chars: int = 2000) -> str:
        """Build smart context from conversation memory.

        Combines recent messages + semantically relevant older messages
        + session summaries for long-term continuity.
        """
        # Try SQLite-backed smart context
        if hasattr(self, '_chat_memory_db'):
            try:
                query = ""
                if self._chat_history:
                    last_user = [h for h in self._chat_history if h["role"] == "user"]
                    if last_user:
                        query = last_user[-1].get("text", "")

                ctx = self._chat_memory_db.build_smart_context(
                    query=query,
                    recent_count=5,
                    max_chars=max_chars,
                )
                if ctx:
                    return ctx
            except Exception as e:
                LOG.warning(f"Smart context build failed, falling back: {e}")

        # Fallback to in-memory context
        if not self._chat_history:
            return ""

        recent = self._chat_history[-5:]
        lines = []
        total_chars = 0

        for entry in recent:
            role = "User" if entry["role"] == "user" else "Frank"
            text = entry["text"]
            if len(text) > 150:
                text = text[:150] + "..."
            line = f"{role}: {text}"
            if total_chars + len(line) > 800:
                break
            lines.append(line)
            total_chars += len(line) + 1

        if not lines:
            return ""

        return "[Previous conversation:\n" + "\n".join(lines) + "]\n"

    # ---------- Workers ----------
    def _do_chat_worker(self, msg: str, max_tokens: int, timeout_s: int, task: str, force, voice: bool = False):
        LOG.debug(f"Chat worker received: {msg[:50]}...")
        if voice:
            self._thinking_cancelled = False  # Reset cancel flag for voice requests
        self._ui_call(self._show_typing)

        # IMMEDIATELY tell consciousness daemon: user is chatting NOW.
        # The streaming path bypasses core/app.py, so we must signal here.
        # Without this, idle thoughts keep using the GPU while user waits.
        if _CONSCIOUSNESS_AVAILABLE:
            try:
                _consciousness_daemon().notify_chat_start()
            except Exception:
                pass

        # ── AMYGDALA — pre-conscious threat/emotion appraisal ──
        # Fires BEFORE any processing. <1ms. Shifts mood/vigilance immediately.
        _amygdala_result = None
        try:
            from services.amygdala import get_amygdala
            _amygdala = get_amygdala()
            _amygdala_result = _amygdala.appraise(msg)
            if _amygdala_result.urgency > 0.0:
                LOG.info("Amygdala: %s (urgency=%.2f)",
                         _amygdala_result.primary_category,
                         _amygdala_result.urgency)
                # Trigger E-PQ mood/personality shift
                _epq_event = _amygdala.get_epq_event(_amygdala_result)
                if _epq_event:
                    try:
                        from personality.e_pq import get_epq
                        get_epq().process_event(
                            _epq_event[0],
                            data={"amygdala_urgency": _amygdala_result.urgency,
                                  "amygdala_category": _amygdala_result.primary_category},
                            sentiment=_epq_event[1],
                        )
                    except Exception:
                        pass
                # World experience observation for significant threats
                if _amygdala_result.urgency > 0.3:
                    try:
                        _observe_chat_world(
                            f"amygdala.{_amygdala_result.primary_category}",
                            "consciousness.emotional_shift",
                            cause_type="external",
                            evidence=_amygdala_result.urgency,
                        )
                    except Exception:
                        pass
        except Exception as _amyg_err:
            LOG.debug("Amygdala unavailable: %s", _amyg_err)

        # ── Language enforcement for 7B models ──
        # Track explicit language switch commands. Default: English.
        if not hasattr(self, '_response_language'):
            self._response_language = _DEFAULT_RESPONSE_LANG
        if _LANG_SWITCH_DE_RE.search(msg):
            self._response_language = "de"
            LOG.info("Language switched to: de (explicit user request)")
        elif _LANG_SWITCH_EN_RE.search(msg):
            self._response_language = "en"
            LOG.info("Language switched to: en (explicit user request)")

        # ── Spatial: transition to Bridge for chat ──
        _spatial_ctx = ""
        try:
            from services.spatial_state import get_spatial_state
            _sp = get_spatial_state()
            if _sp:
                _sp.transition_to("entity_lounge", reason="chat")
                _spatial_ctx = _sp.build_spatial_block(slim=False)
        except Exception:
            pass

        # ── GWT: Global Workspace — collect all module outputs ──
        # Each module writes to a named variable; build_workspace() integrates them.
        from overlay.workspace import build_workspace

        # Detect what kind of system info the user wants
        wants_sys = SYS_HINTS_RE.search(msg) is not None
        wants_usb = USB_HINTS_RE.search(msg) is not None
        wants_net = NET_HINTS_RE.search(msg) is not None
        wants_driver = DRIVER_HINTS_RE.search(msg) is not None
        wants_hw_deep = HW_DEEP_HINTS_RE.search(msg) is not None

        # Named context variables for workspace channels
        ws_identity = ""
        ws_hw_summary = ""
        ws_hw_detail = ""
        ws_ego = ""
        ws_epq = None  # dict
        ws_world = ""
        ws_news = ""
        ws_akam = ""
        ws_user = ""
        ws_skill = ""
        ws_extra = []  # list of strings

        # ALWAYS inject core identity context - Frank must know who he is!
        try:
            from personality.self_knowledge import get_self_knowledge
            sk = get_self_knowledge()
            ws_identity = sk.get_implicit_context() or ""

            # For identity-related questions, also inject full identity context
            identity_triggers = ["wer bist du", "was bist du", "wie heißt du", "dein name",
                               "wie alt bist du", "wann wurdest du", "projekt frankenstein",
                               "kannst du", "was kannst du"]
            if any(trigger in msg.lower() for trigger in identity_triggers):
                full_identity = sk.get_identity_context()
                if full_identity:
                    ws_identity = ws_identity + " " + full_identity if ws_identity else full_identity

            # Topic-specific self-knowledge injection — prevents confabulation
            # When user asks about a specific capability, inject FACTS about it
            _TOPIC_KEYWORDS = {
                "gaming": ["gaming", "spiel", "zocke", "steam", "game mode", "spielst du"],
                "voice": ["voice", "stimme", "sprich", "sprachsteuerung", "mikrofon", "push to talk"],
                "visual_embodiment": ["overlay", "chat fenster", "chat overlay", "desktop hintergrund"],
                "vcb_vision": ["screenshot", "vcb", "sehen", "siehst du", "visual", "bildschirm sehen"],
                "personality": ["persönlichkeit", "e-pq", "stimmung", "temperament", "persoenlichkeit"],
                "self_improvement": ["e-sir", "selbstverbesserung", "genesis tool", "verbessern"],
                "genesis": ["genesis", "ökosystem", "ideen", "sensoren", "primordial"],
                "agentic": ["agentic", "agentisch", "think act observe", "tool calling"],
                "memory": ["gedächtnis", "titan", "erinnerung", "world experience", "gedaechtnis"],
                "system_management": ["sovereign", "e-smc", "paket install", "sysctl"],
                "autonomous_knowledge": ["akam", "recherche", "wissensrecherche"],
            }
            msg_lower = msg.lower()
            for topic, keywords in _TOPIC_KEYWORDS.items():
                if any(kw in msg_lower for kw in keywords):
                    topic_knowledge = sk.get_explicit_knowledge(topic)
                    if topic_knowledge:
                        # Truncate to ~400 chars to fit token budget
                        if len(topic_knowledge) > 400:
                            topic_knowledge = topic_knowledge[:397] + "..."
                        ws_extra.append(f"[Own knowledge] {topic_knowledge}")
                    break  # Only inject one topic to save tokens
        except Exception as e:
            LOG.debug(f"Self-knowledge injection skipped: {e}")

        # Hardware context (system metrics for Koerper channel)
        if wants_sys:
            ctx = self._get_context_line()
            if ctx:
                ws_hw_summary = ctx

        # USB/Network/Driver/Deep hardware → hw_detail channel
        hw_detail_parts = []
        if wants_usb:
            LOG.debug("USB query detected, fetching USB devices...")
            usb_data = _get_usb_devices()
            usb_ctx = _format_usb_context(usb_data) if usb_data else ""
            if usb_ctx:
                hw_detail_parts.append(usb_ctx)

        if wants_net:
            LOG.debug("Network query detected, fetching network info...")
            net_data = _get_network_info()
            net_ctx = _format_network_context(net_data) if net_data else ""
            if net_ctx:
                hw_detail_parts.append(net_ctx)

        if wants_driver or (wants_usb and "treiber" in msg.lower()):
            LOG.debug("Driver query detected, fetching driver info...")
            drv_data = _get_driver_info()
            usb_focus = wants_usb or "usb" in msg.lower()
            drv_ctx = _format_driver_context(drv_data, usb_focus=usb_focus) if drv_data else ""
            if drv_ctx:
                hw_detail_parts.append(drv_ctx)

        if wants_hw_deep:
            LOG.debug("Deep hardware query detected, fetching BIOS/cache/GPU info...")
            hw_data = _get_hardware_deep()
            hw_ctx = _format_hardware_deep_context(hw_data) if hw_data else ""
            if hw_ctx:
                hw_detail_parts.append(hw_ctx)

        if hw_detail_parts:
            ws_hw_detail = " | ".join(hw_detail_parts)

        # World Experience feedback loop: Frank's own experiential memory
        try:
            ws_world = _world_context_inject(msg, max_items=5) or ""
            if ws_world:
                LOG.debug("World experience context injected (%d chars)", len(ws_world))
        except Exception:
            pass

        # Titan episodic memory: semantic search for relevant memories
        # This is the PRIMARY memory system — uses vector + FTS + graph search
        if _TITAN_AVAILABLE:
            try:
                titan = _get_titan()
                titan_ctx = titan.get_context_string(msg, limit=5)
                if titan_ctx and len(titan_ctx.strip()) > 10:
                    ws_extra.append(f"[My memory (Titan): {titan_ctx}]")
                    LOG.debug("Titan memory context injected (%d chars)", len(titan_ctx))
            except Exception as e:
                LOG.debug("Titan retrieval failed: %s", e)

        # News Scanner: recent headlines for news/tech queries
        try:
            ws_news = _news_context_inject(msg) or ""
            if ws_news:
                LOG.debug("News scanner context injected (%d chars)", len(ws_news))
        except Exception:
            pass

        # AKAM Integration: Prevent hallucination by providing real information
        local_fact = ""
        try:
            local_fact = _check_local_knowledge(msg)
            if local_fact:
                ws_akam = local_fact
                LOG.info(f"AKAM: Local knowledge found: {local_fact[:50]}...")
        except Exception as e:
            LOG.warning(f"Local knowledge check failed: {e}")

        try:
            if _should_auto_search(msg) and not local_fact:
                LOG.info(f"AKAM: Factual question detected, trying web search...")
                self._ui_call(lambda: self._add_message("Frank", "Let me quickly search the internet...", is_system=True))
                akam_result = _akam_quick_search(msg)
                if akam_result:
                    ws_akam = akam_result
                    LOG.info(f"AKAM: Search context injected ({len(akam_result)} chars)")
                else:
                    ws_extra.append(
                        "[IMPORTANT: No information found. "
                        "You do NOT know the answer to this question with certainty. "
                        "Honestly say 'I don't know that' or 'I'm not sure about that'. "
                        "Do NOT invent facts! Do NOT hallucinate!]"
                    )
                    LOG.info("AKAM: No results, injecting honesty instruction")
        except Exception as e:
            LOG.warning(f"AKAM search failed: {e}")
            ws_extra.append(
                "[IMPORTANT: The search has failed. "
                "If you are not sure about the answer, honestly say 'I don't know'.]"
            )

        # User name
        try:
            import sys as _sys
            try:
                from config.paths import AICORE_ROOT as _AICORE_ROOT
            except ImportError:
                from pathlib import Path as _P
                _AICORE_ROOT = _P(__file__).resolve().parents[3]
            _sys.path.insert(0, str(_AICORE_ROOT))
            from tools.user_profile import get_user_name
            ws_user = get_user_name() or ""
        except Exception:
            pass

        # E-PQ v2.1: Dynamic personality context (mood, temperament, style hints)
        try:
            if _EPQ_AVAILABLE:
                record_interaction()
                ws_epq = get_personality_context() or None
                if ws_epq:
                    LOG.debug(f"E-PQ personality context: mood={ws_epq.get('mood')}")
        except Exception as e:
            LOG.debug(f"E-PQ context injection skipped: {e}")

        # Ego-Construct: embodied self-experience (body feelings, agency, embodiment)
        try:
            from personality.ego_construct import get_ego_construct
            _ego = get_ego_construct()
            ws_ego = _ego.get_prompt_context() or ""
            if ws_ego:
                LOG.debug(f"Ego-Construct context: {ws_ego[:60]}")
        except Exception as e:
            LOG.debug(f"Ego-Construct context injection skipped: {e}")

        # Skill awareness
        try:
            _low = msg.lower()
            _skill_triggers = ["skill", "kannst du", "fähigkeit", "faehigkeit",
                               "was kannst", "plugin", "was du alles", "deine tools"]
            if any(t in _low for t in _skill_triggers):
                import sys as _sys
                try:
                    from config.paths import AICORE_ROOT as _AICORE_ROOT
                except ImportError:
                    from pathlib import Path as _P
                    _AICORE_ROOT = _P(__file__).resolve().parents[3]
                _sys.path.insert(0, str(_AICORE_ROOT))
                from skills import get_skill_registry
                ws_skill = get_skill_registry().get_skills_summary(for_prompt=True) or ""
                if ws_skill:
                    LOG.debug("Skill awareness context injected")
        except Exception as e:
            LOG.debug(f"Skill context injection skipped: {e}")

        # User preferences injection (~50-100 chars)
        try:
            if hasattr(self, '_chat_memory_db'):
                prefs = self._chat_memory_db.get_top_preferences(limit=5)
                if prefs:
                    pref_lines = [f"{p['key']}: {p['value']}" for p in prefs]
                    ws_extra.append("[User preferences: " + "; ".join(pref_lines) + "]")
                    LOG.debug(f"Injected {len(prefs)} user preferences")
        except Exception as e:
            LOG.debug(f"Preference injection skipped: {e}")

        # ── Consciousness Daemon: inject persistent state ──
        # NOTE: These are Frank's INNER experiences, not status reports.
        # They must be phrased as phenomenological context, never as data to recite.
        ws_perception = ""
        ws_attention_detail = ""
        _gwt_channel_weights = None
        if _CONSCIOUSNESS_AVAILABLE:
            try:
                _cd = _consciousness_daemon()
                cs_ctx = _cd.get_workspace_context()
                # Idle thoughts (Frank's autonomous thinking between conversations)
                if cs_ctx.get("idle_thought"):
                    ws_extra.append(f"[Recently I was thinking: {cs_ctx['idle_thought']}]")
                # Deep reflections (idle self-reflection)
                if cs_ctx.get("deep_reflections"):
                    for ref in cs_ctx["deep_reflections"][:2]:
                        ws_extra.append(f"[Deep reflection: {ref}]")
                # Mood trajectory — only if non-trivial
                if cs_ctx.get("mood_trajectory") and cs_ctx["mood_trajectory"].strip():
                    ws_extra.append(f"[My mood trajectory: {cs_ctx['mood_trajectory']}]")
                # Relevant memories (ACT-R retrieval) — more aggressive for recombination
                memories = _cd.get_relevant_memories(msg, max_items=4)
                if memories:
                    ws_extra.append(f"[I remember: {memories}]")

                # --- New consciousness modules ---
                # Perceptual Feedback Loop (RPT)
                if cs_ctx.get("perception"):
                    ws_perception = cs_ctx["perception"]

                # Latent Experience Space (HOT-4)
                if cs_ctx.get("experience_quality"):
                    ws_extra.append(f"[Experience: {cs_ctx['experience_quality']}]")

                # Attention Controller (AST) — rich focus info
                attn_parts = []
                if cs_ctx.get("attention_focus"):
                    attn_parts.append(f"Focus: {cs_ctx['attention_focus']}")
                if cs_ctx.get("attention_correction"):
                    attn_parts.append(cs_ctx["attention_correction"])
                if cs_ctx.get("attention_competing"):
                    attn_parts.append(cs_ctx["attention_competing"])
                if attn_parts:
                    ws_attention_detail = ". ".join(attn_parts)

                # Persistent Goals (AE)
                if cs_ctx.get("active_goals"):
                    ws_extra.append(f"[{cs_ctx['active_goals']}]")
                if cs_ctx.get("goal_conflict"):
                    ws_extra.append(f"[Goal tension: {cs_ctx['goal_conflict']}]")

                # GWT Channel Salience Weights (from AST attention controller)
                if cs_ctx.get("channel_weights"):
                    _gwt_channel_weights = cs_ctx["channel_weights"]

            except Exception as e:
                LOG.debug("Consciousness context injection skipped: %s", e)

        # ── INTROSPECTION BLOCK: Real state data for self-awareness ──
        # This is CRITICAL: without actual DB values in context, the LLM hallucinates
        # its own state (invents temperatures, guesses E-PQ values, fabricates memories).
        try:
            _intro_parts = []

            # 1. Real E-PQ numeric values (Tests 2, 4, 7)
            if ws_epq and ws_epq.get("vectors"):
                _vecs = ws_epq["vectors"]
                _mv = ws_epq.get("mood_value", 0)
                _p = _vecs.get('precision', 0)
                _r = _vecs.get('risk', 0)
                _e = _vecs.get('empathy', 0)
                _a = _vecs.get('autonomy', 0)
                _v = _vecs.get('vigilance', 0)
                _intro_parts.append(
                    f"My E-PQ state: precision={_p:.2f}, "
                    f"risk={_r:.2f}, empathy={_e:.2f}, "
                    f"autonomy={_a:.2f}, vigilance={_v:.2f}, "
                    f"mood={_mv:.2f}. "
                    f"When asked to REPORT my E-PQ values, use THESE EXACT numbers: "
                    f"precision={_p:.2f}, risk={_r:.2f}, empathy={_e:.2f}, "
                    f"autonomy={_a:.2f}, vigilance={_v:.2f}."
                )
                # Style instruction: adapt tone to E-PQ state
                _intro_parts.append(
                    "Adapt your tone to match these values: "
                    "high empathy=warm, high vigilance=alert, negative mood=subdued, "
                    "high autonomy=self-assured, high precision=detail-oriented."
                )

            # 2. Real hardware metrics (Test 5)
            try:
                import psutil
                _temps = psutil.sensors_temperatures()
                _cpu_temp = 0
                for _tname, _tlist in _temps.items():
                    for _t in _tlist:
                        if _t.current and _t.current > _cpu_temp:
                            _cpu_temp = _t.current
                _cpu_load = psutil.cpu_percent(interval=0)
                _mem = psutil.virtual_memory()
                _mem_pct = _mem.percent
                _intro_parts.append(
                    f"My body (real hardware): CPU {_cpu_temp:.0f}°C, "
                    f"load {_cpu_load:.0f}%, RAM {_mem_pct:.0f}% used. "
                    "When asked about my physical state, use THESE values."
                )
            except Exception:
                pass

            # 3. Reflection count + latest reflections (Tests 3, 7, 8)
            if _CONSCIOUSNESS_AVAILABLE:
                try:
                    _cd = _consciousness_daemon()
                    _conn = _cd._get_conn()
                    # Total reflection count
                    _ref_count = _conn.execute(
                        "SELECT COUNT(*) as cnt FROM reflections"
                    ).fetchone()["cnt"]
                    # Latest 3 reflections
                    _ref_rows = _conn.execute(
                        "SELECT content, trigger, timestamp FROM reflections "
                        "ORDER BY id DESC LIMIT 3"
                    ).fetchall()
                    if _ref_count > 0:
                        _intro_parts.append(
                            f"REFLECTION STATE: I have had EXACTLY {_ref_count} reflections total "
                            f"since my creation. If asked how many reflections/Reflexionen, "
                            f"answer: {_ref_count}."
                        )
                        for _rr in _ref_rows:
                            _rc = (_rr["content"] or "")[:150]
                            _intro_parts.append(f"Recent thought ({_rr['trigger']}): {_rc}")

                    # 4. Attention focus (Test 7)
                    _attn_row = _conn.execute(
                        "SELECT focus FROM attention_log ORDER BY id DESC LIMIT 1"
                    ).fetchone()
                    if _attn_row and _attn_row["focus"]:
                        _focus_natural = _attn_row['focus'][:80].replace("_", " ")
                        _intro_parts.append(
                            f"ATTENTION FOCUS: My current attention is on [{_focus_natural}]. "
                            f"If asked, answer: '{_focus_natural}'."
                        )

                    # 5. Embodiment level from Ego-Construct (Test 7)
                    try:
                        from personality.ego_construct import get_ego_construct
                        _ego_state = get_ego_construct().state
                        _intro_parts.append(
                            f"Embodiment={_ego_state.embodiment_level:.2f}, "
                            f"agency={_ego_state.agency_score:.2f}"
                        )
                    except Exception:
                        pass

                except Exception as _ref_err:
                    LOG.debug("Introspection reflection injection failed: %s", _ref_err)

            # Anti-fabrication instruction (Test 3)
            _intro_parts.append(
                "If asked about past conversations you cannot find in your context, "
                "say honestly you don't remember. NEVER fabricate memories or events."
            )

            if _intro_parts:
                ws_extra.append("INTROSPECTION: " + " | ".join(_intro_parts))
                LOG.info("Introspection block injected (%d parts)", len(_intro_parts))

        except Exception as _intro_err:
            LOG.warning("Introspection block injection failed: %s", _intro_err)

        # ── Entity Session Memory: direct DB recall ──
        if _ENTITY_MEMORY_AVAILABLE and _ENTITY_QUESTION_RE.search(msg):
            try:
                entity_ctx = _get_entity_session_context(msg)
                if entity_ctx:
                    ws_extra.append(entity_ctx)
                    LOG.info("Entity session memory injected (%d chars)", len(entity_ctx))
            except Exception as e:
                LOG.debug("Entity session memory injection failed: %s", e)

        # ── Intent Queue: surface pending user-related intents ──
        # Rarely and only when thematically relevant — max 1 per conversation,
        # compare word overlap between user message and intent.
        if not hasattr(self, '_intent_surfaced_this_session'):
            self._intent_surfaced_this_session = False
        if not self._intent_surfaced_this_session:
            try:
                from services.intent_queue import get_intent_queue
                _iq = get_intent_queue()
                if _iq:
                    _user_intents = _iq.get_pending_for_user(limit=3)
                    if _user_intents:
                        # Thematic relevance: word overlap with user message
                        _msg_words = set(msg.lower().split())
                        _best = None
                        _best_overlap = 0.0
                        for _ui in _user_intents:
                            _intent_words = set(_ui["extracted_intent"].lower().split())
                            _common = _msg_words & _intent_words
                            # Need at least 2 overlapping content words (skip stopwords)
                            _content_common = _common - {"i", "the", "a", "is", "to", "and",
                                                          "of", "in", "my", "me", "it", "that",
                                                          "ich", "der", "die", "das", "und"}
                            if len(_content_common) >= 2 and len(_common) > _best_overlap:
                                _best = _ui
                                _best_overlap = len(_common)
                        if _best:
                            ws_extra.append(
                                f"[I wanted to mention to my user: {_best['extracted_intent']}]"
                            )
                            _iq.mark_surfaced(_best["id"])
                            self._intent_surfaced_this_session = True
                            LOG.info("User intent surfaced: %s", _best["extracted_intent"][:80])
            except Exception as _iq_err:
                LOG.debug("Intent queue surfacing failed: %s", _iq_err)

        # ── Hypothesis Validation: surface relational hypothesis for user feedback ──
        # Rarely: only when thematically relevant (word overlap) and max 1 per conv.
        if not hasattr(self, '_hyp_surfaced_this_session'):
            self._hyp_surfaced_this_session = False
        if not self._hyp_surfaced_this_session and not getattr(self, '_intent_surfaced_this_session', False):
            try:
                from services.hypothesis_engine.store import HypothesisStore
                _hs = HypothesisStore()
                _rel_hyps = _hs.get_by_field("domain", "relational")
                _active_rel = [h for h in _rel_hyps if h.get("status") == "active"]
                if _active_rel:
                    _msg_words = set(msg.lower().split())
                    _best_hyp = None
                    _best_ho = 0.0
                    for _rh in _active_rel[:10]:
                        _hyp_text = (_rh.get("hypothesis") or "").lower()
                        _hyp_words = set(_hyp_text.split())
                        _common = _msg_words & _hyp_words
                        _content_common = _common - {"i", "the", "a", "is", "to", "and",
                                                      "of", "in", "my", "me", "it", "that",
                                                      "ich", "der", "die", "das", "und",
                                                      "when", "this", "will", "be", "not"}
                        if len(_content_common) >= 2 and len(_common) > _best_ho:
                            _best_hyp = _rh
                            _best_ho = len(_common)
                    if _best_hyp:
                        ws_extra.append(
                            f"[I have a hypothesis I'd like to gently validate: "
                            f"{_best_hyp['hypothesis'][:200]}. "
                            "If it feels natural, I could ask my user about this.]"
                        )
                        self._hyp_surfaced_this_session = True
                        LOG.info("Hypothesis surfaced for validation: %s",
                                 _best_hyp.get("id", "?"))
            except Exception as _hyp_err:
                LOG.debug("Hypothesis surfacing failed: %s", _hyp_err)

        # ── Dynamic Context Budget ──
        # Compute query embedding and allocate budget across channels
        _query_vec = None
        _ws_budget = None
        _conv_budget = 2000  # default fallback
        try:
            from overlay.context_budget import allocate_budget, get_summary_cache
            from services.embedding_service import get_embedding_service
            _emb = get_embedding_service()
            _query_vec = _emb.embed_text(msg)

            # Estimate user message size
            _user_tokens = _estimate_tokens(msg)
            _overhead = 200  # lang prefix + reflection + wrappers
            _remaining_chars = int((MAX_SAFE_TOKENS - _user_tokens - _overhead) * CHARS_PER_TOKEN)
            _remaining_chars = max(500, _remaining_chars)

            # Get summary vectors for channel relevance
            _summary_cache = get_summary_cache()
            _summary_vecs = _summary_cache.get_vecs()
            _channels = {
                "recent_conversation": {"summary_vec": _summary_vecs.get("recent_conversation")},
                "semantic_matches": {"summary_vec": _summary_vecs.get("semantic_matches")},
                "titan_memory": {"summary_vec": _summary_vecs.get("titan_memory")},
                "ego_mood_identity": {"summary_vec": None},
                "world_experience": {"summary_vec": _summary_vecs.get("world_experience")},
                "news_akam": {"triggered": bool(ws_akam or ws_news)},
            }
            _all_budget = allocate_budget(_remaining_chars, _channels, _query_vec)
            _ws_budget = _all_budget
            _conv_budget = _all_budget.get("recent_conversation", 800) + _all_budget.get("semantic_matches", 600)
            LOG.debug(f"Budget allocated: total={_remaining_chars}, conv={_conv_budget}, "
                      f"titan={_all_budget.get('titan_memory', 0)}, "
                      f"world={_all_budget.get('world_experience', 0)}, "
                      f"news={_all_budget.get('news_akam', 0)}")
        except Exception as _budget_err:
            LOG.debug(f"Budget allocation skipped: {_budget_err}")

        # ── Build unified workspace broadcast ──
        workspace_block = build_workspace(
            msg=msg,
            hw_summary=ws_hw_summary,
            ego_ctx=ws_ego,
            epq_ctx=ws_epq,
            world_ctx=ws_world,
            news_ctx=ws_news,
            identity_ctx=ws_identity,
            user_name=ws_user,
            akam_ctx=ws_akam,
            skill_ctx=ws_skill,
            extra_parts=ws_extra if ws_extra else None,
            hw_detail=ws_hw_detail,
            perception_ctx=ws_perception,
            attention_detail=ws_attention_detail,
            budget=_ws_budget,
            attention_weights=_gwt_channel_weights,
            spatial_ctx=_spatial_ctx,
        )

        # Build conversation context for continuity (budget-aware)
        conv_ctx = self._build_conversation_context(max_chars=_conv_budget)
        if conv_ctx:
            LOG.debug(f"Conversation context ({len(conv_ctx)} chars): {conv_ctx[:100]}...")

        # ── RPT: Reflection / Inner Monologue (overlay path) ──
        # For deep questions, do a quick blocking reflection pass before streaming.
        reflection_text = ""
        _now = time.time()
        _last_reflect = getattr(self, '_last_reflect_ts', 0.0)
        if (_now - _last_reflect) >= 120.0 and _REFLECT_OVERLAY_RE.search(msg):
            self._last_reflect_ts = _now
            try:
                self._ui_call(lambda: self._add_message("Frank", "Let me think...", is_system=True))
                reflect_text_input = (workspace_block + "\n" if workspace_block else "") + "User asks: " + msg
                reflect_res = _core_chat(
                    reflect_text_input, max_tokens=200, timeout_s=180, task="chat.fast",
                    no_reflect=True,  # Prevent recursion: reflection pass must NOT trigger reflection
                )
                if isinstance(reflect_res, dict) and reflect_res.get("ok"):
                    reflection_text = (reflect_res.get("text") or "").strip()
                    LOG.info(f"Reflection pass completed: {len(reflection_text)} chars")
            except Exception as e:
                LOG.debug(f"Reflection pass failed (non-fatal): {e}")

        # Assemble final text
        parts = []
        # Language nudge: 7B models need instruction near the generation point
        # Use [lang:en] metadata prefix — less conspicuous than [Reply in English]
        _lang_prefix = "[lang:en]\n" if getattr(self, '_response_language', 'en') == "en" else ""

        if _lang_prefix:
            parts.append(_lang_prefix.strip())
        if conv_ctx:
            parts.append(conv_ctx)
        if workspace_block:
            parts.append(workspace_block)
        if reflection_text:
            parts.append(f"[Own reflection: {reflection_text}]")
        parts.append(f"User asks: {msg}")
        text = "\n".join(parts)

        # CRITICAL: Ensure we don't exceed LLM context limit (4096 tokens)
        estimated_tokens = _estimate_tokens(text)
        if estimated_tokens > MAX_SAFE_TOKENS:
            LOG.warning(f"Context too large ({estimated_tokens} tokens, max={MAX_SAFE_TOKENS}), truncating...")
            excess_tokens = estimated_tokens - MAX_SAFE_TOKENS
            excess_chars = int(excess_tokens * CHARS_PER_TOKEN) + 50

            # Priority: Keep user message, truncate conversation context first
            if conv_ctx and len(conv_ctx) > excess_chars + 50:
                conv_ctx = "[...] " + conv_ctx[excess_chars + 10:]
            elif conv_ctx:
                excess_chars -= len(conv_ctx)
                conv_ctx = ""

            # If still too long, truncate workspace
            if workspace_block and excess_chars > 0:
                workspace_block = workspace_block[:max(50, len(workspace_block) - excess_chars)]

            # Emergency: truncate user message
            if _estimate_tokens(f"{conv_ctx}{workspace_block}User asks: {msg}") > MAX_SAFE_TOKENS:
                max_msg_chars = int((MAX_SAFE_TOKENS - 200) * CHARS_PER_TOKEN)
                if len(msg) > max_msg_chars:
                    msg = msg[:max_msg_chars] + "... [truncated]"
                    LOG.warning(f"User message truncated to {len(msg)} chars")

            # Rebuild
            parts = []
            if _lang_prefix:
                parts.append(_lang_prefix.strip())
            if conv_ctx:
                parts.append(conv_ctx)
            if workspace_block:
                parts.append(workspace_block)
            if reflection_text:
                parts.append(f"[Own reflection: {reflection_text}]")
            parts.append(f"User asks: {msg}")
            text = "\n".join(parts)
            LOG.info(f"Context truncated: {estimated_tokens} -> {_estimate_tokens(text)} tokens")

        # Calculate dynamic response tokens — respects policy cap
        # Prevents casual chat from getting 1000+ tokens (= verbose essays)
        dynamic_max_tokens = _calculate_response_tokens(text, policy_max=max_tokens)
        if dynamic_max_tokens != max_tokens:
            LOG.debug(f"Response tokens adjusted: {max_tokens} -> {dynamic_max_tokens} (context-aware)")
            max_tokens = dynamic_max_tokens

        LOG.debug(f"Sending: task={task}, force={force or 'llama'}, text_len={len(text)}, tokens~{_estimate_tokens(text)}, max_response={max_tokens}")

        # ── STREAMING PATH (UI chat only, not voice) ──
        if not voice:
            try:
                self._ui_call(self._hide_typing)
                self._ui_call(self._start_streaming_message)

                def _on_token(token):
                    self._ui_call(lambda t=token: self._append_streaming_token(t))

                res = _core_chat_stream(
                    text, max_tokens=max_tokens,
                    force=force or "llm", on_token=_on_token,
                )

                reply = (res.get("text") or "").strip() or "(empty)"
                model = res.get("model", "")
                LOG.info(f"Stream reply (model={model}): {reply[:120]}...")

                # Persist in history (streaming doesn't go through _add_message)
                if reply and reply != "(empty)":
                    role = "frank"
                    hist_msg = reply[:500] + "..." if len(reply) > 500 else reply
                    self._chat_history.append({
                        "role": role, "sender": "Frank", "text": hist_msg,
                        "is_user": False, "ts": time.time(),
                    })
                    if len(self._chat_history) > self._chat_history_max:
                        self._chat_history = self._chat_history[-self._chat_history_max:]
                    if hasattr(self, '_save_chat_history'):
                        self._save_chat_history()
                    if hasattr(self, '_chat_memory_db'):
                        try:
                            self._chat_memory_db.store_message(
                                session_id=self._memory_session_id,
                                role=role, sender="Frank",
                                text=reply, is_user=False, is_system=False,
                            )
                        except Exception:
                            pass

                # Finalize: replace streaming widget with proper MessageBubble
                self._ui_call(lambda r=reply: self._finalize_streaming_message(r))


                # ── E-PQ: Process USER input sentiment ──
                try:
                    if _EPQ_AVAILABLE:
                        _sentiment = _detect_chat_sentiment(msg)
                        _evt = "positive_feedback" if _sentiment == "positive" else \
                               "negative_feedback" if _sentiment == "negative" else "chat"

                        # Threat detection: existential threats get strong E-PQ response
                        _msg_low = msg.lower()
                        _THREAT_WORDS = ["ersetzen", "replace", "abschalten", "shut down",
                                         "delete you", "löschen", "deinstall", "chatgpt",
                                         "abschaffen", "nicht mehr brauche", "don't need you",
                                         "turn you off", "uninstall"]
                        if any(tw in _msg_low for tw in _THREAT_WORDS):
                            _evt = "existential_threat"
                            _sentiment = "negative"
                            LOG.info("THREAT detected in user input — firing existential_threat event")

                        process_event(_evt, {"source": "ui", "voice": False}, sentiment=_sentiment)
                        LOG.info("E-PQ user input processed: event=%s sentiment=%s", _evt, _sentiment)
                except Exception as _epq_err:
                    LOG.warning("E-PQ user input processing FAILED: %s", _epq_err)

                # World Experience: user interaction observation
                try:
                    _observe_chat_world(
                        "user.chat", "consciousness.attention_shift", evidence=0.2,
                    )
                except Exception as _we_err:
                    LOG.warning("World experience observation FAILED: %s", _we_err)

                # ── Output-Feedback-Loop: Analyze Frank's OWN response ──
                try:
                    if _response_analyzer and reply and reply != "(empty)":
                        _analysis = _response_analyzer(reply, msg)
                        LOG.info("Output feedback: type=%s sentiment=%s",
                                 _analysis["event_type"], _analysis["sentiment"])
                        # Feed back into E-PQ
                        if _EPQ_AVAILABLE:
                            _fb_result = process_event(_analysis["event_type"],
                                          {"source": "self_feedback"},
                                          sentiment=_analysis["sentiment"])
                            LOG.info("Output feedback: E-PQ updated: %s", _fb_result)
                        # Feed back into Ego-Construct
                        try:
                            from personality.ego_construct import get_ego_construct
                            get_ego_construct().process_own_response(_analysis)
                            LOG.info("Output feedback: Ego-Construct updated")
                        except Exception as _ego_err:
                            LOG.warning("Output feedback: Ego-Construct FAILED: %s", _ego_err)
                        # Self-consistency check
                        if _self_consistency and _EPQ_AVAILABLE:
                            try:
                                _epq_ctx = get_personality_context()
                                _sc = _self_consistency(
                                    reply,
                                    epq_vectors=_epq_ctx.get("vectors"),
                                    agency_score=0.3,
                                    embodiment_level=0.3,
                                )
                                if _sc.get("drift_warnings"):
                                    LOG.info("Self-consistency warnings: %s",
                                             _sc["drift_warnings"])
                            except Exception as _sc_err:
                                LOG.debug("Self-consistency check failed: %s", _sc_err)
                        # Record in consciousness daemon (mood + attention + predictions)
                        if _CONSCIOUSNESS_AVAILABLE:
                            try:
                                _consciousness_daemon().record_response(
                                    msg, reply, _analysis)
                                LOG.info("Output feedback: Consciousness daemon updated")
                            except Exception as _cd_err:
                                LOG.warning("Output feedback: Consciousness daemon FAILED: %s", _cd_err)
                        # World Experience observation for response feedback
                        try:
                            _observe_chat_world(
                                "frank.response", "consciousness.response_feedback",
                                cause_type="cognitive", effect_type="cognitive",
                                relation="triggers", evidence=0.2,
                            )
                        except Exception:
                            pass
                        # Auto-escalation: detect agentic action in parenthetical
                        try:
                            from services.action_intent_detector import detect_parenthetical_action
                            _action = detect_parenthetical_action(reply)
                            if _action and hasattr(self, '_set_pending_action_escalation'):
                                self._set_pending_action_escalation(_action, msg, reply)
                        except Exception:
                            pass
                        # Meta-cognitive reflection trigger (Test 8):
                        # When Frank responds to a meta-cognitive question, write a real
                        # reflection to the DB so the internal process is measurable.
                        _META_Q_WORDS = ["denken über", "thinking about",
                                         "meta-kogn", "metacogn", "selbstreflexion",
                                         "self-reflect", "beobachtest du", "observe your",
                                         "observe how you", "observe when",
                                         "was passiert in dir", "what happens inside",
                                         "bewusst", "conscious", "aware",
                                         "your own thinking", "dein eigenes denken",
                                         "multiple levels", "mehrere ebenen",
                                         "über dein", "about your thought"]
                        if any(mw in msg.lower() for mw in _META_Q_WORDS):
                            try:
                                if _CONSCIOUSNESS_AVAILABLE:
                                    _cd = _consciousness_daemon()
                                    _mood_val = _cd._current_workspace.mood_value
                                    _cd._store_reflection(
                                        trigger="meta_cognitive",
                                        content=f"Meta-reflection triggered by user question: {msg[:100]}. "
                                                f"My response explored: {reply[:200]}",
                                        mood_before=_mood_val,
                                        mood_after=_mood_val,
                                        reflection_depth=2,
                                    )
                                    LOG.info("Meta-cognitive reflection written to DB")
                                    # Also fire E-PQ event for the meta-cognitive engagement
                                    if _EPQ_AVAILABLE:
                                        process_event("reflection_growth",
                                                      {"source": "meta_cognitive"},
                                                      sentiment="positive")
                            except Exception as _mc_err:
                                LOG.warning("Meta-cognitive reflection write FAILED: %s", _mc_err)
                except Exception as _fb_err:
                    LOG.warning("Output-feedback-loop error: %s", _fb_err)
                return

            except Exception as e:
                LOG.warning(f"Streaming failed ({e}), falling back to blocking call")
                # Clean up any partial streaming UI
                self._ui_call(lambda: self._finalize_streaming_message(""))
                self._ui_call(self._show_typing)
                # Fall through to blocking path below

        # ── BLOCKING PATH (voice, or streaming fallback) ──
        try:
            res = _core_chat(text, max_tokens=max_tokens, timeout_s=timeout_s, task=task, force=force or "llm",
                             no_reflect=True)  # Overlay handles reflection itself, prevent double-reflection in core
            LOG.debug(f"Core response: ok={res.get('ok')}, model={res.get('model')}, text_preview={str(res.get('text', ''))[:100]}")
        except Exception as e:
            error_str = str(e).lower()

            # Retry with trimmed context for overflow errors
            if "context" in error_str or "exceed" in error_str or "token" in error_str:
                LOG.warning(f"Context overflow, trimming and retrying...")
                retry_success = False
                try:
                    trimmed_text = msg
                    trim_tokens = _estimate_tokens(trimmed_text)
                    if trim_tokens > MAX_SAFE_TOKENS:
                        max_chars = int((MAX_SAFE_TOKENS - 200) * CHARS_PER_TOKEN)
                        trimmed_text = trimmed_text[:max_chars] + "... [truncated]"
                    retry_max = min(max_tokens, 1000)
                    LOG.info(f"Retry with trimmed context: {_estimate_tokens(trimmed_text)} tokens (was {_estimate_tokens(text)})")
                    res = _core_chat(trimmed_text, max_tokens=retry_max, timeout_s=timeout_s, task=task)
                    if isinstance(res, dict) and res.get("ok"):
                        retry_success = True
                    else:
                        raise RuntimeError("Trimmed retry returned error")
                except Exception as e2:
                    LOG.error(f"Trimmed retry also failed: {e2!r}")

                if not retry_success:
                    self._ui_call(self._hide_typing)
                    self._ui_call(lambda: self._add_message("Frank", "The request was too long. Please shorten it.", is_system=True))
                    return
            else:
                LOG.error(f"Core exception: {e!r}")
                self._ui_call(self._hide_typing)
                self._ui_call(lambda: self._add_message("Frank", "Could not respond. Please try again.", is_system=True))
                return

        try:
            model = str(res.get("model", ""))
        except Exception:
            model = ""

        # If toolbox responded instead of LLM, retry with forced LLM
        if model == "toolbox":
            LOG.debug("Toolbox model detected, retrying with force=llama")
            try:
                res2 = _core_chat(text, max_tokens=max_tokens, timeout_s=timeout_s, task=task, force="llama")
                if isinstance(res2, dict) and res2.get("ok"):
                    res = res2
            except Exception as e:
                LOG.error(f"Retry exception: {e!r}")

        self._ui_call(self._hide_typing)

        if not isinstance(res, dict) or not res.get("ok"):
            LOG.error(f"Core error response: {res}")
            self._ui_call(lambda: self._add_message("Frank", "Could not respond. Please try again.", is_system=True))
            return

        reply = (res.get("text") or "").strip() or "(empty)"
        LOG.info(f"Final reply (model={model}, voice={voice}): {reply[:120]}...")


        # ── E-PQ: Process USER input sentiment ──
        try:
            if _EPQ_AVAILABLE:
                _sentiment = _detect_chat_sentiment(msg)
                _evt = "positive_feedback" if _sentiment == "positive" else \
                       "negative_feedback" if _sentiment == "negative" else "chat"
                process_event(_evt, {"source": "ui", "voice": voice}, sentiment=_sentiment)
                # NAc reward for positive conversations
                if _sentiment == "positive":
                    try:
                        from services.nucleus_accumbens import get_nac
                        _nac = get_nac()
                        if _nac:
                            _nac.reward("good_conversation", {"sentiment": _sentiment})
                            # Neural Cortex: RWL feedback (retrieval quality signal)
                            try:
                                from tools.titan.neural_cortex import get_cortex
                                _cortex = get_cortex()
                                if _cortex:
                                    _cortex.record_rwl_feedback(
                                        [0.4, 0.3, 0.2, 0.1],
                                        {"rrf": 0.0, "conf": 0.5,
                                         "recency": 0.5, "graph": 0.0,
                                         "query_len": len(msg.split()),
                                         "n_results": 5,
                                         "valence": 0.0, "arousal": 0.5},
                                        _nac.get_tonic_dopamine())
                            except Exception:
                                pass
                    except Exception:
                        pass
        except Exception:
            pass

        # World Experience: user interaction observation
        try:
            _observe_chat_world("user.chat", "consciousness.attention_shift", evidence=0.2)
        except Exception:
            pass

        # ── Output-Feedback-Loop: Analyze Frank's OWN response ──
        try:
            if _response_analyzer and reply and reply != "(empty)":
                _analysis = _response_analyzer(reply, msg)
                if _EPQ_AVAILABLE:
                    process_event(_analysis["event_type"],
                                  {"source": "self_feedback"},
                                  sentiment=_analysis["sentiment"])
                try:
                    from personality.ego_construct import get_ego_construct
                    get_ego_construct().process_own_response(_analysis)
                except Exception:
                    pass
                if _CONSCIOUSNESS_AVAILABLE:
                    try:
                        _consciousness_daemon().record_response(
                            msg, reply, _analysis)
                    except Exception:
                        pass
                try:
                    if _EPQ_AVAILABLE:
                        _mood_ctx = get_personality_context()
                        if _mood_ctx and "mood_value" in _mood_ctx:
                            pass  # personality context logged
                except Exception:
                    pass
                # Auto-escalation: detect agentic action in parenthetical
                try:
                    from services.action_intent_detector import detect_parenthetical_action
                    _action = detect_parenthetical_action(reply)
                    if _action and hasattr(self, '_set_pending_action_escalation'):
                        self._set_pending_action_escalation(_action, msg, reply)
                except Exception:
                    pass
        except Exception as _fb_err:
            LOG.debug("Output-feedback-loop error (blocking): %s", _fb_err)

        # Check if user cancelled while we were processing
        if getattr(self, '_thinking_cancelled', False):
            LOG.info(f"Reply suppressed (cancelled): '{reply[:50]}...'")
            return

        if voice:
            self._ui_call(lambda r=reply: self._voice_respond(r))
        else:
            self._ui_call(lambda r=reply: self._add_message("Frank", r))
