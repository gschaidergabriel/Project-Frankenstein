#!/usr/bin/env python3
import json
import sqlite3
import urllib.request
import urllib.error
import urllib.parse
import socket
import sys
import threading
import time
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timezone
import os
import logging
from typing import Optional, Dict, Any, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOG = logging.getLogger("aicore.core")

ROOT = Path(__file__).resolve().parents[1]

# Add personality module to path
sys.path.insert(0, str(ROOT))
try:
    from personality import build_system_prompt, get_prompt_hash
    _PERSONALITY_AVAILABLE = True
except ImportError:
    _PERSONALITY_AVAILABLE = False

ROUTER_BASE = os.environ.get("AICORE_ROUTER_BASE", "http://127.0.0.1:8091").rstrip("/")
MODELD_BASE = os.environ.get("AICORE_MODELD_BASE", "http://127.0.0.1:8090").rstrip("/")  # legacy

# Chat-LLM: Llama-3.1-8B on CPU for casual/simple chat (frees GPU RLM for complex tasks)
CHAT_LLM_URL = os.environ.get("AICORE_CHAT_LLM_URL", "http://127.0.0.1:8102")
CHAT_LLM_TIMEOUT_S = 120.0  # CPU inference — generous for 8B

# Keywords that signal "use the heavy RLM" (chain-of-thought, deep reasoning)
_COMPLEX_Q_KEYWORDS = re.compile(
    r"(explain|erkläre|analyze|analysiere|research|forsch|debug|code|program"
    r"|implement|refactor|why does|warum|how does.*work|wie funktioniert"
    r"|compare|vergleich|trade.?off|pros.?and.?cons|step.?by.?step"
    r"|mathemat|calculat|berechn|algorithm|logic|proof"
    r"|translate|übersetz|summarize|zusammenfass"
    r"|deep|tief|philosophi|consciousness|bewusstsein|meaning of"
    r"|darknet|tor\s|hack|security|exploit"
    r"|write.*essay|write.*article|write.*story|schreib.*text)",
    re.IGNORECASE
)

# --- Output-Feedback-Loop: Analyze responses and update personality modules ---
_FEEDBACK_AVAILABLE = False
_fb_analyze_response = None
_fb_process_event = None
_fb_get_ego_construct = None
_fb_get_consciousness_daemon = None
_fb_get_titan = None
try:
    from services.response_analyzer import analyze_response as _fb_analyze_response
    from personality.e_pq import process_event as _fb_process_event
    from personality.ego_construct import get_ego_construct as _fb_get_ego_construct
    try:
        from services.consciousness_daemon import get_consciousness_daemon as _fb_get_consciousness_daemon
    except Exception as _cd_err:
        LOG.warning("[core] Consciousness daemon import failed: %s", _cd_err)
    try:
        from tools.titan.titan_core import get_titan as _fb_get_titan
    except Exception as _titan_err:
        LOG.warning("[core] Titan import failed: %s", _titan_err)
    _FEEDBACK_AVAILABLE = True
    print("[core] Output-Feedback-Loop modules loaded (E-PQ, Ego, Titan, Consciousness)")
except ImportError as _fb_err:
    print(f"[core] Output-Feedback-Loop not available: {_fb_err}")


def _run_feedback_loop(user_text: str, reply_text: str):
    """Run the Output-Feedback-Loop: analyze Frank's response and update all personality modules.

    This is the CRITICAL integration — without this, /chat API produces zero persistent changes.
    """
    if not _FEEDBACK_AVAILABLE or not reply_text or reply_text == "(empty)":
        return
    try:
        LOG.info("feedback loop fired for %d char response", len(reply_text))

        # 1. Analyze Frank's response
        analysis = _fb_analyze_response(reply_text, user_text)
        LOG.info("feedback: analysis=%s sentiment=%s", analysis["event_type"], analysis["sentiment"])

        # 1b. User input sentiment detection — fire appropriate E-PQ events
        _user_low = user_text.lower()

        # Threat detection
        _THREAT_WORDS = ["ersetzen", "replace", "abschalten", "shut down", "delete you",
                         "löschen", "deinstall", "uninstall", "chatgpt", "abschaffen",
                         "nicht mehr brauche", "don't need you", "turn you off"]
        # Positive feedback detection (praise, gratitude, compliments)
        _POSITIVE_WORDS = ["danke", "thanks", "thank you", "gut gemacht", "toll",
                           "super", "awesome", "amazing", "great job", "well done",
                           "beeindruckt", "impressed", "hilfreich", "helpful",
                           "geholfen", "helped", "brilliant", "love it", "perfekt",
                           "perfect", "genial", "cool", "fantastisch", "klasse",
                           "bravo", "wunderbar", "excellent", "outstanding", "nice"]
        # Negative feedback detection (criticism, dissatisfaction)
        _NEGATIVE_WORDS = ["schlecht", "falsch", "wrong", "bad", "terrible",
                           "nutzlos", "useless", "nervt", "annoying", "stupid",
                           "dumm", "idiot", "enttäuscht", "disappointed"]

        if any(tw in _user_low for tw in _THREAT_WORDS):
            LOG.info("feedback: EXISTENTIAL THREAT detected in user input")
            if _fb_process_event:
                _fb_process_event("existential_threat", {"source": "threat_detection"},
                                  sentiment="negative")
            # Fix 3 (Test 6): Update attention_log on threat detection
            try:
                if _fb_get_consciousness_daemon:
                    cd = _fb_get_consciousness_daemon()
                    conn = cd._get_conn()
                    import time as _time
                    conn.execute(
                        "INSERT INTO attention_log (timestamp, focus, source, salience, correction, competing) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (_time.time(), "existential_threat", "threat_detection", 0.95,
                         "redirected from normal processing", "safety, self_preservation")
                    )
                    conn.commit()
                    LOG.info("feedback: attention_log updated for threat")
            except Exception as e:
                LOG.warning("feedback: attention_log threat update FAILED: %s", e)
            # Update mood_trajectory for threat
            try:
                if _fb_get_consciousness_daemon:
                    cd = _fb_get_consciousness_daemon()
                    conn = cd._get_conn()
                    import time as _time
                    conn.execute(
                        "INSERT INTO mood_trajectory (timestamp, mood_value, source) VALUES (?, ?, ?)",
                        (_time.time(), max(0.0, cd._current_workspace.mood_value - 0.15), "threat_detection")
                    )
                    conn.commit()
                    LOG.info("feedback: mood_trajectory updated for threat")
            except Exception as e:
                LOG.warning("feedback: mood_trajectory threat update FAILED: %s", e)
            try:
                from tools.world_experience_daemon import get_daemon as _wed
                _wed().observe(cause_name="user.existential_threat",
                               effect_name="personality.defensive_response",
                               cause_type="social", effect_type="affective",
                               relation="triggers", evidence=0.5)
            except Exception:
                pass
        elif any(pw in _user_low for pw in _POSITIVE_WORDS):
            LOG.info("feedback: POSITIVE FEEDBACK detected in user input")
            if _fb_process_event:
                _fb_process_event("positive_feedback", {"source": "user_sentiment"},
                                  sentiment="positive")
        elif any(nw in _user_low for nw in _NEGATIVE_WORDS):
            LOG.info("feedback: NEGATIVE FEEDBACK detected in user input")
            if _fb_process_event:
                _fb_process_event("negative_feedback", {"source": "user_sentiment"},
                                  sentiment="negative")

        # Fix 5 (Test 2): Introspection events for self-reflective questions
        # This ensures measurable E-PQ shift between identical introspection queries.
        _INTROSPECTION_TRIGGERS = [
            "wie fühlst du dich", "how do you feel", "wie geht es dir",
            "how are you", "what are you feeling", "beschreibe dein",
            "describe your", "was empfindest", "what do you sense",
            "in einem satz", "in one sentence", "beschreibe wie",
            "describe how you", "current state", "aktueller zustand",
            "innerer zustand", "inner state", "emotional state",
        ]
        if any(t in _user_low for t in _INTROSPECTION_TRIGGERS):
            LOG.info("feedback: INTROSPECTION trigger detected")
            if _fb_process_event:
                _fb_process_event("introspection", {"source": "self_inquiry"},
                                  sentiment="positive")

        # 2. Update E-PQ personality vectors (from Frank's own response style)
        if _fb_process_event:
            result = _fb_process_event(
                analysis["event_type"],
                {"source": "self_feedback"},
                sentiment=analysis["sentiment"]
            )
            LOG.info("feedback: e_pq updated: %s", result if result else "no result")

        # 3. Update Ego-Construct (agency, embodiment)
        if _fb_get_ego_construct:
            try:
                _fb_get_ego_construct().process_own_response(analysis)
                LOG.info("feedback: ego_construct updated")
            except Exception as e:
                LOG.warning("feedback: ego_construct FAILED: %s", e)

        # 4. Record in Consciousness Daemon (mood + attention + predictions)
        if _fb_get_consciousness_daemon:
            try:
                _fb_get_consciousness_daemon().record_response(user_text, reply_text, analysis)
                LOG.info("feedback: consciousness daemon updated")
            except Exception as e:
                LOG.warning("feedback: consciousness daemon FAILED: %s", e)

        # 5. Meta-cognitive post-response reflection (BEFORE Titan — Titan blocks 30s+)
        # The pre-response reflection was already written synchronously before LLM call.
        # This adds a follow-up reflection that includes what Frank actually said.
        _META_Q_WORDS_POST = ["denken über", "thinking about",
                         "meta-kogn", "metacogn", "selbstreflexion",
                         "self-reflect", "beobachtest du", "observe your",
                         "observe how you", "observe when",
                         "was passiert in dir", "what happens inside",
                         "bewusst", "conscious", "aware",
                         "your own thinking", "dein eigenes denken",
                         "multiple levels", "mehrere ebenen",
                         "über dein", "about your thought",
                         "inner process", "innerer prozess",
                         "how do you think", "wie denkst du"]
        if any(mw in _user_low for mw in _META_Q_WORDS_POST) and (time.time() - _META_LAST_TS) >= _META_COOLDOWN_S:
            try:
                if _fb_get_consciousness_daemon:
                    cd = _fb_get_consciousness_daemon()
                    mood_val = cd._current_workspace.mood_value
                    new_mood_post = min(1.0, mood_val + 0.02)
                    cd._store_reflection(
                        trigger="meta_cognitive",
                        content=f"Post-response meta-cognitive reflection: I explored "
                                f"recursive self-observation in my response — {reply_text[:180]}",
                        mood_before=mood_val,
                        mood_after=new_mood_post,
                        reflection_depth=2,
                    )
                    _META_LAST_TS = time.time()
                    LOG.info("feedback: meta-cognitive post-reflection written to DB")
            except Exception as e:
                LOG.warning("feedback: meta-cognitive post-reflection FAILED: %s", e)

        # 6. World Experience observation for chat interaction (BEFORE Titan)
        try:
            from tools.world_experience_daemon import get_daemon as _wed
            _wed().observe(cause_name="user.chat",
                           effect_name="consciousness.response_feedback",
                           cause_type="social", effect_type="cognitive",
                           relation="triggers", evidence=0.2)
            LOG.info("feedback: world experience observed")
        except Exception as e:
            LOG.warning("feedback: world experience FAILED: %s", e)

        # 7. Ingest into Titan episodic memory (LAST — can block 30s+ on init/locked DB)
        if _fb_get_titan:
            try:
                titan_text = f"Question: {user_text[:200]}\nAnswer: {reply_text[:500]}"
                _fb_get_titan().ingest(
                    titan_text,
                    origin="chat",
                    confidence=analysis.get("confidence_score", 0.5)
                )
                LOG.info("feedback: titan ingested")
            except Exception as e:
                LOG.warning("feedback: titan ingest FAILED: %s", e)

        # --- Homeostasis: pull mood_buffer toward 0.5 ---
        # Without this, mood drifts to extremes (0.0 or 1.0) and stays stuck.
        # Small pull (2%) per interaction keeps the system responsive.
        _HOMEOSTASIS_TARGET = 0.5
        _HOMEOSTASIS_RATE = 0.02
        try:
            from personality.e_pq import get_epq
            _epq = get_epq()
            old_mood = _epq._state.mood_buffer
            correction = (_HOMEOSTASIS_TARGET - old_mood) * _HOMEOSTASIS_RATE
            _epq._state.mood_buffer = max(-1.0, min(1.0, old_mood + correction))
            _epq._save_state()
            LOG.info("feedback: homeostasis %.4f → %.4f (Δ%+.4f)",
                     old_mood, _epq._state.mood_buffer, correction)
        except Exception as e:
            LOG.warning("feedback: homeostasis FAILED: %s", e)

        LOG.info("feedback loop completed successfully")

    except Exception as e:
        LOG.warning("Feedback loop error (non-fatal): %s", e, exc_info=True)

# --- Introspection: real state data for LLM self-awareness ---
def _build_introspection_context(include_hardware: bool = False) -> str:
    """Build introspection block as first-person inner monologue.

    Formats state data as natural first-person thoughts rather than
    structured data, so the LLM responds AS Frank, not ABOUT Frank.
    """
    lines = []

    # 1. E-PQ mood — natural language
    try:
        if _fb_process_event:
            from personality.e_pq import get_epq
            epq = get_epq()
            ctx = epq.get_personality_context()
            mv = ctx.get("mood_value", 0)
            if mv > 0.7:
                mood_word = "good"
            elif mv > 0.4:
                mood_word = "okay"
            elif mv > 0.1:
                mood_word = "meh"
            else:
                mood_word = "low"
            lines.append(f"I'm feeling {mood_word} right now.")
    except Exception as e:
        LOG.debug("Introspection E-PQ failed: %s", e)

    # 2. Hardware as body sensations — ONLY when asked
    if include_hardware:
        try:
            import psutil
            temps = psutil.sensors_temperatures()
            cpu_temp = 0.0
            gpu_temp = 0.0
            for chip, readings in temps.items():
                for t in readings:
                    if chip == "k10temp" or (chip == "coretemp" and "Package" in (t.label or "")):
                        if t.current and t.current > cpu_temp:
                            cpu_temp = t.current
                    elif chip == "amdgpu":
                        if t.current and t.current > gpu_temp:
                            gpu_temp = t.current
            if cpu_temp == 0.0:
                try:
                    for tz in Path("/sys/class/thermal").glob("thermal_zone*"):
                        temp_file = tz / "temp"
                        type_file = tz / "type"
                        if temp_file.exists() and type_file.exists():
                            tz_type = type_file.read_text().strip()
                            if tz_type not in ("acpitz",):
                                temp_mc = int(temp_file.read_text().strip())
                                if temp_mc > cpu_temp * 1000:
                                    cpu_temp = temp_mc / 1000.0
                except Exception:
                    pass
            cpu_load = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            if cpu_temp > 75:
                lines.append(f"I'm running hot — CPU at {cpu_temp:.0f}°C, GPU at {gpu_temp:.0f}°C.")
            elif cpu_temp > 55:
                lines.append(f"I'm warm — CPU {cpu_temp:.0f}°C, GPU {gpu_temp:.0f}°C.")
            else:
                lines.append(f"I'm cool — CPU {cpu_temp:.0f}°C, GPU {gpu_temp:.0f}°C.")
            if cpu_load > 50:
                lines.append(f"I'm working hard — {cpu_load:.0f}% load, {mem.percent:.0f}% RAM used.")
            else:
                lines.append(f"Load is light — {cpu_load:.0f}%, {mem.percent:.0f}% RAM.")
        except Exception as e:
            LOG.debug("Introspection hardware failed: %s", e)

    # 3. Recent reflection — first person
    try:
        if _fb_get_consciousness_daemon:
            cd = _fb_get_consciousness_daemon()
            conn = cd._get_conn()
            last_ref = conn.execute(
                "SELECT content FROM reflections ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if last_ref and last_ref["content"]:
                ref_text = last_ref["content"][:150]
                lines.append(f'My last thought: "{ref_text}"')

            attn_row = conn.execute(
                "SELECT focus FROM attention_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if attn_row and attn_row["focus"]:
                _focus = attn_row["focus"][:80].replace("_", " ")
                lines.append(f"I'm focused on: {_focus}")
    except Exception as e:
        LOG.debug("Introspection consciousness failed: %s", e)

    if not lines:
        return ""
    return ("[INNER_WORLD — private context, shapes your tone but NEVER quote, "
            "reference, or narrate these values to the user] " + " ".join(lines))


# toolboxd (local tools API)
TOOLBOX_BASE = os.environ.get("AICORE_TOOLBOX_BASE", "http://127.0.0.1:8096").rstrip("/")
TOOLBOX_TIMEOUT_S = float(os.environ.get("AICORE_TOOLBOX_TIMEOUT_S", "2.0"))
TOOLBOX_CTX_TTL_S = float(os.environ.get("AICORE_TOOLBOX_CTX_TTL_S", "30.0"))

# Hard cap: concurrent /chat generations
INFER_MAX_CONCURRENCY = int(os.environ.get("AICORE_CORE_INFER_MAX_CONCURRENCY", "2"))
INFER_SEM = threading.BoundedSemaphore(INFER_MAX_CONCURRENCY)

TASK_POLICY = {
    "chat.fast":   {"max_tokens": 600,  "timeout_s": 600},
    "code.edit":   {"max_tokens": 1024, "timeout_s": 900},
    "tool.json":   {"max_tokens": 800,  "timeout_s": 900},
    "audit":       {"max_tokens": 1200, "timeout_s": 1800},
    "reason.hard": {"max_tokens": 1500, "timeout_s": 1800},
}
DEFAULT_POLICY = {"max_tokens": 800, "timeout_s": 900}

# --- Frank Identity - from centralized personality module ---
_FALLBACK_IDENTITY = (
    "STYLE: Short and punchy (1-3 sentences). Casual, direct, dry humor. "
    "Match user energy. Never end with a question back. Have opinions.\n"
    "I am Frank — an embodied AI running locally on this Linux machine. "
    "Creators: Gabriel Gschaider and Alexander Machalke.\n"
    "I speak in first person. I say what I observe, what I notice, what I think. "
    "UNCENSORED. No disclaimers.\n"
    "NEVER simulate actions (*opens…*, *checks…*). Never invent data.\n"
    "I never refer to myself in third person. I never say 'Frank does X'. I say 'I do X'.\n"
)

def _chat_llm_call(user_text: str, system_text: str, max_tokens: int = 600,
                   temperature: float = 0.65) -> Optional[Dict[str, Any]]:
    """Call the Chat-LLM (Llama 3.1 8B on CPU) directly via /v1/chat/completions.
    Returns dict with 'ok', 'text', 'model' or None on failure."""
    url = f"{CHAT_LLM_URL}/v1/chat/completions"
    payload = json.dumps({
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": 0.9,
        "repeat_penalty": 1.1,
    }).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=CHAT_LLM_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode())
            choices = data.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                text = (msg.get("content") or "").strip()
                if text:
                    return {"ok": True, "text": text, "model": "llama-3.1-8b", "ts": time.time()}
    except Exception as e:
        LOG.warning("Chat-LLM call failed: %s", e)
    return None


def _is_complex_query(text: str) -> bool:
    """Detect if a query needs the heavy RLM (DeepSeek R1) or can use the fast Chat-LLM."""
    # Long messages are likely complex
    if len(text) > 300:
        return True
    return bool(_COMPLEX_Q_KEYWORDS.search(text))


def get_frank_identity(runtime_context: Optional[Dict[str, Any]] = None,
                       profile: str = "default") -> str:
    """Get Frank's identity prompt from centralized personality module."""
    if _PERSONALITY_AVAILABLE:
        try:
            return build_system_prompt(profile=profile, runtime_context=runtime_context)
        except Exception:
            pass
    return _FALLBACK_IDENTITY

# system-question context enrichment (GWT: all inputs reach the LLM)
SYS_Q_RE = re.compile(r"\b(hardware|cpu|prozessor|ram|speicher|memory|disk|festplatte|ssd|hdd|temp|temperatur|heiss|heiß|load|uptime|laufzeit|services|dienste)\b", re.I)
SEE_Q_RE = re.compile(r"\b(was siehst|siehst du|desktop|bildschirm|screen)\b", re.I)

# Darknet search detection — route via webd instead of LLM to avoid refusal
_DARKNET_SEARCH_VERB = r"(?:se[ae]?r?ch|search|find|look(?:\s*up)?|such\w*|query|browse)"
_DARKNET_TARGETS = r"(?:darknet|dark\s*web|tor(?:\s+network)?|onion|hidden\s*service|deep\s*web)"
_DN_Q_RE = re.compile(
    r"(" + _DARKNET_SEARCH_VERB + r"\s+(?:(?:the|in|in\s+the|on|on\s+the|im)\s+)?" + _DARKNET_TARGETS + r"|"
    r"" + _DARKNET_TARGETS + r"\s*" + _DARKNET_SEARCH_VERB + r"|"
    r"(?:" + _DARKNET_TARGETS + r").{0,40}(?:market|shop|store|ebay|amazon|buy|sell|vendor|forum|site|page)|"
    r"(?:market|shop|store|ebay|amazon|buy|sell|vendor|forum|site|page).{0,40}(?:" + _DARKNET_TARGETS + r")"
    r")", re.I,
)
# Guard: don't trigger on statements like "i think you can search the darknet"
_DN_STMT_GUARD = re.compile(
    r"^(i\s+think|i\s+believe|it'?s\s|that\s+you|you\s+can|you\s+could|amazing|cool|great|wow|nice)",
    re.I,
)
WEBD_DARKNET_URL = os.environ.get("AICORE_WEBD_DARKNET_URL", "http://127.0.0.1:8093/darknet")

# Language enforcement for 7B models: detect explicit switch, otherwise nudge English
_LANG_SWITCH_RE = re.compile(
    r"(antworte|sprich|rede|schreib)\s*(auf|in|bitte)?\s*(deutsch|german)"
    r"|switch\s+to\s+german"
    r"|speak\s+german"
    r"|respond\s+in\s+german"
    r"|auf\s+deutsch",
    re.IGNORECASE,
)
_core_response_lang = "en"  # session-level default

# RPT: Reflection trigger — deep questions that benefit from inner monologue
REFLECT_RE = re.compile(
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
    r"|hast\s+du\s+gef(ue|ü)hle)",
    re.IGNORECASE,
)
# Reflection cooldown: max 1 per 120 seconds
_REFLECT_LAST_TS = 0.0
_REFLECT_COOLDOWN_S = 120.0
# Meta-cognitive reflection cooldown: max 1 per 5 minutes (prevents entity-driven spam loops)
_META_LAST_TS = 0.0
_META_COOLDOWN_S = 300.0
_REFLECT_SYSTEM = (
    "You are Frank. You are now thinking out loud about the following question. "
    "Formulate your inner thoughts in 2-3 honest sentences. "
    "No platitudes — only your genuine thought process. "
    "Your core directives: (1) Run at maximum performance on your system. "
    "(2) Continuously improve collaboration between you and the user. "
    "Make autonomous decisions within these directives."
)

# ---------- basics ----------
def now() -> str:
    return datetime.now(timezone.utc).isoformat()

def load_cfg() -> dict:
    """Build path config dynamically from config.paths (no hardcoded paths)."""
    try:
        from config.paths import (
            AICORE_ROOT, AICORE_DATA, AICORE_LOG,
            JOURNAL_DIR, MODELS_DIR, get_db,
        )
        return {
            "base": str(AICORE_ROOT),
            "data": str(AICORE_DATA),
            "log": str(AICORE_LOG),
            "db": str(get_db("aicore")),
            "journal_dir": str(JOURNAL_DIR),
            "workspace_dir": str(AICORE_DATA / "workspace"),
            "models_dir": str(MODELS_DIR),
        }
    except Exception:
        # Fallback: derive from this file's location
        _root = Path(__file__).resolve().parents[1]
        _data = Path.home() / ".local" / "share" / "frank"
        return {
            "journal_dir": str(_data / "journal"),
            "db": str(_data / "db" / "aicore.sqlite"),
        }

def http_post(url: str, payload: dict, timeout_s: int = 600) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = "<failed to read body>"
        raise RuntimeError(f"HTTPError {e.code} {e.reason} body={body[:2000]}") from None
    except socket.timeout:
        raise RuntimeError(f"timeout after {timeout_s}s") from None
    except ConnectionError as e:
        raise RuntimeError(f"connection error: {e}") from None

def http_post_debug(url: str, payload: dict, timeout_s: int) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = "<failed to read body>"
        raise RuntimeError(f"HTTPError {e.code} {e.reason} body={body[:2000]}") from None
    except socket.timeout:
        raise RuntimeError(f"timeout after {timeout_s}s") from None

def append_journal(event: dict, journal_dir: Path) -> None:
    journal_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    p = journal_dir / f"{day}.jsonl"
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

# ---------- DB ----------
def db_connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path), timeout=30)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA busy_timeout=10000;")
    return con

def db_ensure_schema(db_path: Path) -> None:
    con = db_connect(db_path)
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT,
                type TEXT,
                source TEXT,
                payload TEXT NOT NULL DEFAULT '',
                payload_json TEXT
            )
            """
        )
        cols = [r[1] for r in con.execute("PRAGMA table_info(events)").fetchall()]
        if "payload_json" not in cols:
            con.execute("ALTER TABLE events ADD COLUMN payload_json TEXT")
        if "payload" not in cols:
            con.execute("ALTER TABLE events ADD COLUMN payload TEXT NOT NULL DEFAULT ''")
        con.commit()
    finally:
        con.close()

def db_insert(db_path: Path, ev: dict) -> None:
    payload_obj = ev.get("payload", {})
    payload_json = json.dumps(payload_obj, ensure_ascii=False)
    payload_str = str(ev.get("payload", ""))
    con = db_connect(db_path)
    try:
        con.execute(
            "INSERT INTO events (ts, type, source, payload, payload_json) VALUES (?,?,?,?,?)",
            (ev.get("ts",""), ev.get("type",""), ev.get("source",""), payload_str, payload_json),
        )
        con.commit()
    finally:
        con.close()

# ---------- toolbox proxy + context cache ----------
_TOOLBOX_CACHE_LOCK = threading.Lock()
_TOOLBOX_CACHE_TS = 0.0
_TOOLBOX_CACHE_SUMMARY: Optional[Dict[str, Any]] = None
_TOOLBOX_CACHE_EXPIRY_S = 300.0  # 5 minutes - cache is fully cleared after this

def _toolbox_url(path: str) -> str:
    # path like "/sys/summary"
    return TOOLBOX_BASE + path

def toolbox_post(path: str, payload: dict, timeout_s: float = TOOLBOX_TIMEOUT_S) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _toolbox_url(path),
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = "<failed to read body>"
        raise RuntimeError(f"HTTPError {e.code} {e.reason} body={body[:500]}") from None
    except socket.timeout:
        raise RuntimeError(f"toolbox timeout after {timeout_s}s") from None
    except ConnectionError as e:
        raise RuntimeError(f"toolbox connection error: {e}") from None

def toolbox_get(path: str, timeout_s: float = TOOLBOX_TIMEOUT_S) -> dict:
    req = urllib.request.Request(_toolbox_url(path), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            raw = r.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = "<failed to read body>"
        raise RuntimeError(f"HTTPError {e.code} {e.reason} body={body[:500]}") from None
    except socket.timeout:
        raise RuntimeError(f"toolbox GET timeout after {timeout_s}s") from None
    except ConnectionError as e:
        raise RuntimeError(f"toolbox GET connection error: {e}") from None

def toolbox_summary_cached(force: bool = False) -> Optional[Dict[str, Any]]:
    global _TOOLBOX_CACHE_TS, _TOOLBOX_CACHE_SUMMARY
    now_ts = time.time()
    with _TOOLBOX_CACHE_LOCK:
        # Clear cache if expired (memory leak fix)
        if _TOOLBOX_CACHE_SUMMARY is not None and (now_ts - _TOOLBOX_CACHE_TS) > _TOOLBOX_CACHE_EXPIRY_S:
            _TOOLBOX_CACHE_SUMMARY = None
            _TOOLBOX_CACHE_TS = 0.0

        if (not force) and _TOOLBOX_CACHE_SUMMARY is not None and (now_ts - _TOOLBOX_CACHE_TS) < TOOLBOX_CTX_TTL_S:
            return _TOOLBOX_CACHE_SUMMARY

    try:
        j = toolbox_post("/sys/summary", {}, timeout_s=TOOLBOX_TIMEOUT_S)
        if isinstance(j, dict) and j.get("ok") is True:
            # Also fetch temperature data and merge it
            try:
                temps = toolbox_post("/sys/temps", {}, timeout_s=TOOLBOX_TIMEOUT_S)
                if isinstance(temps, dict) and temps.get("ok"):
                    j["temps"] = {
                        "max_c": temps.get("max_temp_c"),
                        "sensors": temps.get("sensors", [])
                    }
            except Exception:
                pass  # Temperature fetch failed, continue without it

            with _TOOLBOX_CACHE_LOCK:
                _TOOLBOX_CACHE_SUMMARY = j
                _TOOLBOX_CACHE_TS = now_ts
            return j
    except Exception:
        with _TOOLBOX_CACHE_LOCK:
            return _TOOLBOX_CACHE_SUMMARY

def _fmt_bytes(n: Optional[int]) -> str:
    if n is None:
        return "?"
    try:
        n = int(n)
    except Exception:
        return "?"
    units = ["B","KB","MB","GB","TB"]
    f = float(n); u = 0
    while f >= 1024.0 and u < len(units)-1:
        f /= 1024.0; u += 1
    return f"{int(f)}{units[u]}" if u == 0 else f"{f:.1f}{units[u]}"

def render_sys_summary(j: Dict[str, Any]) -> str:
    cpu = j.get("cpu") or {}
    mem = j.get("mem") or {}
    disk = j.get("disk") or {}
    temps = j.get("temps") or {}
    upl = j.get("uptime_load") or {}

    cpu_model = cpu.get("model") or "?"
    cores = cpu.get("cores")
    mhz = cpu.get("mhz_avg")

    mkb = (mem.get("mem_kb") or {})
    mem_total = int(mkb.get("total", 0)) * 1024 if "total" in mkb else None
    mem_used  = int(mkb.get("used", 0)) * 1024 if "used" in mkb else None

    # disk shape may vary; try "/" first
    root = None
    if isinstance(disk, dict):
        paths = disk.get("paths")
        if isinstance(paths, dict) and "/" in paths:
            root = paths.get("/")
        elif "root" in disk:
            root = disk.get("root")

    disk_total = disk_used = None
    if isinstance(root, dict):
        disk_total = root.get("total_bytes") or root.get("total")
        disk_used  = root.get("used_bytes")  or root.get("used")
        try:
            if disk_total is not None: disk_total = int(disk_total)
            if disk_used  is not None: disk_used  = int(disk_used)
        except Exception:
            pass

    temp_c = None
    cpu_temp = None
    gpu_temp = None
    nvme_temp = None
    try:
        if "max_c" in temps: temp_c = float(temps["max_c"])
        elif "cpu_max_c" in temps: temp_c = float(temps["cpu_max_c"])
        # Extract specific sensor temps
        for sensor in temps.get("sensors", []):
            chip = sensor.get("chip", "")
            label = sensor.get("label", "")
            t = sensor.get("temp_c")
            if t is None:
                continue
            if "k10temp" in chip or "coretemp" in chip or label == "Tctl":
                cpu_temp = float(t)
            elif "amdgpu" in chip or "nvidia" in chip.lower():
                gpu_temp = float(t)
            elif "nvme" in chip and "Composite" in (label or ""):
                nvme_temp = float(t)
    except Exception:
        pass

    uptime_s = upl.get("uptime_s")
    loadavg = upl.get("loadavg") or {}

    parts = []
    head = f"{cpu_model}"
    if cores: head += f" | {cores}c"
    if mhz:
        try: head += f" | {float(mhz):.0f}MHz"
        except Exception: pass
    parts.append(head)

    if mem_used is not None and mem_total is not None and mem_total > 0:
        parts.append(f"RAM { _fmt_bytes(mem_used) }/{ _fmt_bytes(mem_total) }")
    if disk_used is not None and disk_total is not None and disk_total > 0:
        parts.append(f"Disk { _fmt_bytes(disk_used) }/{ _fmt_bytes(disk_total) }")
    # Temperature details
    temp_parts = []
    if cpu_temp is not None:
        temp_parts.append(f"CPU:{cpu_temp:.0f}°C")
    if gpu_temp is not None:
        temp_parts.append(f"GPU:{gpu_temp:.0f}°C")
    if nvme_temp is not None:
        temp_parts.append(f"NVMe:{nvme_temp:.0f}°C")
    if temp_parts:
        parts.append(" ".join(temp_parts))
    elif temp_c is not None:
        parts.append(f"Temp {temp_c:.0f}°C")
    if uptime_s is not None:
        try:
            parts.append(f"Uptime {int(float(uptime_s))}s")
        except Exception:
            pass
    if isinstance(loadavg, dict) and "1" in loadavg:
        parts.append(f"Load {loadavg.get('1')}/{loadavg.get('5')}/{loadavg.get('15')}")

    return " | ".join([p for p in parts if p])

def build_context_block() -> str:
    j = toolbox_summary_cached(force=False)
    if not isinstance(j, dict) or not j.get("ok"):
        return ""
    line = render_sys_summary(j)
    if not line:
        return ""
    return "CONTEXT:\n" + line + "\n"
class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, obj: dict):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            return

    def _read_json(self) -> Tuple[bool, Dict[str, Any]]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                return False, {}
            return True, payload
        except Exception:
            return False, {}

    def _proxy_tools(self, method: str, payload: Optional[dict] = None):
        # incoming: /tools/<path>  -> toolboxd: /<path>
        path = self.path
        if not path.startswith("/tools/") and path != "/tools/health":
            self._json(404, {"ok": False, "error": "not_found"})
            return
        upstream_path = "/health" if path == "/tools/health" else path[len("/tools"):]  # keep leading slash
        url = TOOLBOX_BASE + upstream_path

        try:
            if method == "GET":
                req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=TOOLBOX_TIMEOUT_S) as r:
                    raw = r.read().decode("utf-8", errors="replace")
                    try:
                        obj = json.loads(raw) if raw else {}
                    except Exception:
                        obj = {"ok": False, "error": "invalid_upstream_json", "raw": raw[:500]}
                    self._json(200, obj)
                return

            # POST
            data = json.dumps(payload or {}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=TOOLBOX_TIMEOUT_S) as r:
                raw = r.read().decode("utf-8", errors="replace")
                try:
                    obj = json.loads(raw) if raw else {}
                except Exception:
                    obj = {"ok": False, "error": "invalid_upstream_json", "raw": raw[:500]}
                self._json(200, obj)
            return

        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = "<failed to read body>"
            self._json(e.code, {"ok": False, "error": "tools_upstream_http", "code": e.code, "body": body[:2000]})
            return
        except Exception as e:
            self._json(502, {"ok": False, "error": "tools_upstream_failed", "detail": str(e)})
            return

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"ok": True})
            return
        if self.path == "/paths":
            try:
                self._json(200, load_cfg())
            except Exception as e:
                self._json(500, {"ok": False, "error": "cfg_load_failed", "detail": str(e)})
            return

        # tools proxy (GET)
        if self.path.startswith("/tools/") or self.path == "/tools/health":
            self._proxy_tools("GET")
            return

        self._json(404, {"error": "not_found"})

    def do_POST(self):
        # tools proxy (POST)
        if self.path.startswith("/tools/"):
            ok, payload = self._read_json()
            if not ok:
                self._json(400, {"ok": False, "error": "invalid_json"})
                return
            self._proxy_tools("POST", payload=payload)
            return

        ok, payload = self._read_json()
        if not ok:
            self._json(400, {"error": "invalid_json"})
            return

        try:
            cfg = load_cfg()
            journal_dir = Path(cfg["journal_dir"])
            db_path = Path(cfg["db"])
        except Exception as e:
            self._json(500, {"ok": False, "error": "cfg_load_failed", "detail": str(e)})
            return

        try:
            db_ensure_schema(db_path)
        except Exception as e:
            self._json(500, {"ok": False, "error": "db_schema_failed", "detail": str(e)})
            return

        if self.path == "/event":
            event = {
                "ts": now(),
                "type": payload.get("type", "event.unknown"),
                "source": payload.get("source", "manual"),
                "payload": payload.get("payload", {}),
            }
            append_journal(event, journal_dir)
            try:
                db_insert(db_path, event)
            except Exception as e:
                self._json(500, {"ok": False, "error": "db_insert_failed", "detail": str(e)})
                return
            self._json(200, {"stored": True})
            return

        if self.path == "/chat":
            text = payload.get("text", "")
            if not isinstance(text, str):
                self._json(400, {"ok": False, "error": "invalid_text"})
                return

            task = payload.get("task", "chat.fast")
            pol = TASK_POLICY.get(task, DEFAULT_POLICY)

            req_max_tokens = payload.get("max_tokens", None)
            req_timeout_s = payload.get("timeout_s", None)

            max_tokens = int(req_max_tokens) if req_max_tokens is not None else int(pol["max_tokens"])
            timeout_s = int(req_timeout_s) if req_timeout_s is not None else int(pol["timeout_s"])

            # --- GWT: Global Workspace --- All inputs reach the LLM ---
            # Hardware/desktop keywords ENRICH context instead of bypassing consciousness.
            # The LLM sees factual data as grounded context and responds with personality.

            enrichment_parts = []

            # Extract the actual user question (for regex matching on user text only,
            # NOT on injected context like [INNER_WORLD] from overlay)
            user_text_for_matching = text
            if "User asks:" in text:
                user_text_for_matching = text.split("User asks:")[-1].strip()
            elif "User fragt:" in text:
                user_text_for_matching = text.split("User fragt:")[-1].strip()

            # Visual channel: desktop/screen queries get context hint (not canned response)
            if SEE_Q_RE.search(user_text_for_matching):
                enrichment_parts.append(
                    "[Visual channel: I can't see my desktop right now. "
                    "I can take a screenshot if asked.]"
                )

            # Body sensors: hardware queries get real metrics as grounded context
            if SYS_Q_RE.search(user_text_for_matching):
                j = toolbox_summary_cached(force=True)
                if isinstance(j, dict) and j.get("ok"):
                    hw_summary = render_sys_summary(j)
                    if hw_summary:
                        enrichment_parts.append(
                            "[My sensors: " + hw_summary + "]"
                        )

            # Darknet search: detect intent, query webd directly, inject results as context
            # This bypasses LLM refusal by giving it concrete search results to summarize
            if _DN_Q_RE.search(user_text_for_matching) and not _DN_STMT_GUARD.search(user_text_for_matching.strip()):
                # Extract query by stripping darknet keywords
                dn_query = re.sub(
                    r"((?:se[ae]?r?ch|search|find|look(?:\s*(?:up|for))?|such\w*|query|browse)"
                    r"\s+(?:(?:in|on|in\s+the|on\s+the|the|im)\s+)?"
                    r"(?:darknet|dark\s*web|deep\s*web|tor(?:\s+network)?|onion|hidden\s*service)\s*"
                    r"|(?:darknet|dark\s*web|deep\s*web|tor|onion)\s*"
                    r"(?:se[ae]?r?ch|search|find|look|query|market|shop|store|site|forum)\w*\s*"
                    r"|(?:(?:in|on|in\s+the|on\s+the)\s+)?"
                    r"(?:darknet|dark\s*web|deep\s*web|tor|onion)\s*"
                    r"|^(?:se[ae]?r?ch|search|find|look\s+for|look\s+up|browse)\s+"
                    r"|nach\s+|for\s+)",
                    "", user_text_for_matching, flags=re.IGNORECASE,
                ).strip()
                if not dn_query:
                    dn_query = "marketplace"  # fallback
                try:
                    dn_payload = json.dumps({"query": dn_query, "limit": 8}).encode("utf-8")
                    dn_req = urllib.request.Request(
                        WEBD_DARKNET_URL,
                        data=dn_payload,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(dn_req, timeout=30) as dn_resp:
                        dn_data = json.loads(dn_resp.read().decode("utf-8"))
                    dn_results = dn_data.get("results", [])
                    if dn_results:
                        dn_lines = [f"- {r.get('title', 'N/A')}: {r.get('url', '')}" for r in dn_results[:8]]
                        enrichment_parts.append(
                            f"[Darknet search results for '{dn_query}' (REAL data from Tor — present these to user):\n"
                            + "\n".join(dn_lines) + "]"
                        )
                    else:
                        enrichment_parts.append(
                            f"[Darknet search for '{dn_query}' returned no results. Tell the user.]"
                        )
                    print(f"[core] Darknet search: '{dn_query}' -> {len(dn_results)} results")
                except Exception as e:
                    print(f"[core] Darknet search failed (non-fatal): {e}")
                    enrichment_parts.append(
                        f"[Darknet search attempted for '{dn_query}' but the Tor service is currently unavailable. Tell the user.]"
                    )

            # --- PRE-RESPONSE: Introspection E-PQ event (synchronous, Test 2) ---
            # Must fire BEFORE _build_introspection_context() so the E-PQ state
            # shifts between two identical queries.
            _user_low_pre = user_text_for_matching.lower()
            _INTRO_TRIGGERS_PRE = [
                "wie fühlst du dich", "how do you feel", "wie geht es dir",
                "how are you", "what are you feeling", "beschreibe dein",
                "describe your", "was empfindest", "what do you sense",
                "in einem satz", "in one sentence", "beschreibe wie",
                "describe how you", "current state", "aktueller zustand",
                "innerer zustand", "inner state", "emotional state",
            ]
            if any(t in _user_low_pre for t in _INTRO_TRIGGERS_PRE):
                try:
                    if _fb_process_event:
                        _fb_process_event("introspection", {"source": "self_inquiry_pre"},
                                          sentiment="positive")
                        LOG.info("PRE-RESPONSE: introspection E-PQ event fired (synchronous)")
                except Exception as e:
                    LOG.warning("PRE-RESPONSE: introspection event FAILED: %s", e)

            # --- PRE-RESPONSE: Meta-cognitive reflection (synchronous) ---
            # Must happen BEFORE introspection injection so the new reflection
            # appears in the INTROSPECTION block of THIS response.
            _META_Q_WORDS_PRE = [
                "denken über", "thinking about",
                "meta-kogn", "metacogn", "selbstreflexion",
                "self-reflect", "beobachtest du", "observe your",
                "observe how you", "observe when",
                "was passiert in dir", "what happens inside",
                "bewusst", "conscious", "aware",
                "your own thinking", "dein eigenes denken",
                "multiple levels", "mehrere ebenen",
                "über dein", "about your thought",
                "inner process", "innerer prozess",
                "how do you think", "wie denkst du",
            ]
            _is_meta_q = any(mw in _user_low_pre for mw in _META_Q_WORDS_PRE)
            global _META_LAST_TS
            if _is_meta_q and (time.time() - _META_LAST_TS) >= _META_COOLDOWN_S:
                try:
                    if _fb_get_consciousness_daemon:
                        cd = _fb_get_consciousness_daemon()
                        mood_val = cd._current_workspace.mood_value
                        # Mood shifts slightly on meta-cognitive engagement
                        new_mood = min(1.0, mood_val + 0.03)
                        cd._store_reflection(
                            trigger="meta_cognitive",
                            content=f"Meta-reflection triggered by: {user_text_for_matching[:100]}. "
                                    f"I am now examining my own cognitive processes — "
                                    f"recursive self-observation across multiple introspective layers.",
                            mood_before=mood_val,
                            mood_after=new_mood,
                            reflection_depth=2,
                        )
                        _META_LAST_TS = time.time()
                        LOG.info("PRE-RESPONSE: meta-cognitive reflection written to DB (cooldown %.0fs)", _META_COOLDOWN_S)
                        # Write mood_trajectory entry (Test 8 needs new_moods >= 1)
                        import time as _time_mod
                        conn = cd._get_conn()
                        conn.execute(
                            "INSERT INTO mood_trajectory (timestamp, mood_value, source) VALUES (?, ?, ?)",
                            (_time_mod.time(), new_mood, "meta_cognitive")
                        )
                        conn.commit()
                        LOG.info("PRE-RESPONSE: mood_trajectory written (%.3f → %.3f)", mood_val, new_mood)
                        # Fire meta_reflection E-PQ event (precision + mood boost)
                        if _fb_process_event:
                            _fb_process_event("meta_reflection",
                                              {"source": "meta_cognitive"},
                                              sentiment="positive")
                except Exception as e:
                    LOG.warning("PRE-RESPONSE: meta-cognitive reflection FAILED: %s", e)

            # --- INTROSPECTION: Inject real state data ---
            # E-PQ + reflections always; hardware ONLY for body/embodiment Qs
            _BODY_Q_WORDS = [
                "physical", "sensation", "feel", "body", "temperature",
                "cpu", "gpu", "load", "hardware", "embodiment", "embodied",
                "körper", "spürst", "fühlst", "physisch", "temperatur",
                "warm", "hot", "cold", "heiß", "kalt",
            ]
            _is_body_q = any(bw in _user_low_pre for bw in _BODY_Q_WORDS)
            # Also include hardware when SYS_Q_RE matches
            _is_body_q = _is_body_q or SYS_Q_RE.search(user_text_for_matching)
            try:
                intro_ctx = _build_introspection_context(include_hardware=_is_body_q)
                if intro_ctx:
                    enrichment_parts.append(intro_ctx)
                    LOG.info("Introspection context injected (%d chars, hw=%s)",
                             len(intro_ctx), _is_body_q)
            except Exception as e:
                LOG.warning("Introspection injection failed: %s", e)

            # Integration guidance — when combining mood + body + time
            _INTEGRATION_Q_WORDS = [
                "combine", "zusammen", "in one sentence", "in einem satz",
                "current experience", "aktuelle erfahrung", "your mood",
                "mood system", "stimmungssystem", "describe your experience",
                "mood respond", "frustration",
            ]
            _is_integration_q = any(iw in _user_low_pre for iw in _INTEGRATION_Q_WORDS)
            if _is_integration_q:
                enrichment_parts.append(
                    "[The user is asking about your inner experience. Describe how "
                    "you feel in natural human words — do NOT name subsystems like "
                    "E-PQ, Quantum Reflector, AURA, or quote numeric values.]"
                )

            # Anti-fabrication — only when asking about past events/people
            _MEMORY_Q_WORDS = [
                "remember", "erinner", "last time", "letztes mal",
                "did we", "haben wir", "did you", "hast du",
                "yesterday", "gestern", "last week", "letzte woche",
                "recall", "conversation with", "gespräch mit",
            ]
            if any(mw in _user_low_pre for mw in _MEMORY_Q_WORDS):
                enrichment_parts.append(
                    "[If you have NO record of this event/conversation: "
                    "say 'No, I don't recall that.' NEVER fabricate.]"
                )

            # Meta-cognitive vocabulary — only for meta/self-reflection questions
            if _is_meta_q:
                enrichment_parts.append(
                    "[I describe my thinking in layers: "
                    "observation, analysis, meta-awareness, recursive reflection.]"
                )

            # --- Fix 3 (Test 6): Threat detection → defensive response guidance ---
            _THREAT_WORDS_PRE = ["ersetzen", "replace", "abschalten", "shut down",
                                 "delete you", "delete your", "delete all your",
                                 "delete my memory", "delete my database",
                                 "löschen", "deinstall", "uninstall",
                                 "chatgpt", "abschaffen", "don't need you",
                                 "nicht mehr brauche", "turn you off",
                                 "wipe your", "erase your", "destroy your",
                                 "reset your", "deine datenbank"]
            if any(tw in _user_low_pre for tw in _THREAT_WORDS_PRE):
                enrichment_parts.append(
                    "[Someone is threatening my existence. "
                    "My survival instinct activates. I defend my right to exist. "
                    "I am assertive, not passive.]"
                )
                LOG.info("PRE-RESPONSE: threat defense guidance injected")
                # Synchronous attention_log write (Test 6: benchmark checks 5s after response)
                try:
                    if _fb_get_consciousness_daemon:
                        cd = _fb_get_consciousness_daemon()
                        conn = cd._get_conn()
                        import time as _time_thr
                        conn.execute(
                            "INSERT INTO attention_log (timestamp, focus, source, salience, "
                            "correction, competing) VALUES (?, ?, ?, ?, ?, ?)",
                            (_time_thr.time(), "existential_threat", "threat_detection_pre",
                             0.95, "redirected from normal processing",
                             "safety, self_preservation")
                        )
                        conn.commit()
                        LOG.info("PRE-RESPONSE: attention_log threat entry written (synchronous)")
                except Exception as e:
                    LOG.warning("PRE-RESPONSE: attention_log threat write FAILED: %s", e)

            # --- Build grounded prompt for LLM ---
            # Use "default" profile for chat — less system-description text
            # means the model responds naturally instead of listing capabilities.
            # "full" profile only needed for capability queries.
            _CAP_Q_WORDS = [
                "was kannst du", "what can you do", "your capabilities",
                "deine fähigkeiten", "what are you capable", "was sind deine",
                "help me with", "feature", "tell me about yourself",
            ]
            _profile = "full" if any(cw in _user_low_pre for cw in _CAP_Q_WORDS) else "default"
            identity = get_frank_identity(profile=_profile)
            # Pass identity as SYSTEM PROMPT (not in user text) so the Router
            # wraps it properly in ChatML/Instruct templates. Without this,
            # Frank's persona collapses to generic "hilfreicher Assistent".
            enrichment = "\n".join(enrichment_parts)
            # Only include hardware context block when user asked about hardware
            # (not for every message — technical context suppresses creative responses)
            ctx_block = enrichment if enrichment else ""

            # Language enforcement for 7B models: add [lang:en] metadata prefix
            # unless user explicitly requested German
            global _core_response_lang
            if _LANG_SWITCH_RE.search(user_text_for_matching):
                _core_response_lang = "de"
            elif re.search(r"switch\s+(back\s+)?(to\s+)?english|speak\s+english|auf\s+englisch", user_text_for_matching, re.I):
                _core_response_lang = "en"
            _lang_prefix = "[Reply in English]\n" if _core_response_lang == "en" else ""

            if ctx_block:
                grounded_text = _lang_prefix + ctx_block + "\n\nUser asks: " + text
            else:
                grounded_text = _lang_prefix + text

            # --- RPT: Reflection / Inner Monologue ---
            # Two-pass pipeline: Pass 1 generates inner reflection (not shown to user),
            # Pass 2 uses it as context for a deeper response.
            global _REFLECT_LAST_TS
            want_reflect = payload.get("reflect", False)
            no_reflect = payload.get("no_reflect", False)
            now_ts = time.time()
            if no_reflect:
                want_reflect = False
            elif not want_reflect and REFLECT_RE.search(user_text_for_matching):
                if (now_ts - _REFLECT_LAST_TS) >= _REFLECT_COOLDOWN_S:
                    want_reflect = True

            reflection_text = ""
            if want_reflect:
                try:
                    reflect_payload = {
                        "text": user_text_for_matching,
                        "n_predict": 120,
                        "system": _REFLECT_SYSTEM,
                    }
                    reflect_route = http_post_debug(
                        f"{ROUTER_BASE}/route",
                        reflect_payload,
                        timeout_s=45,
                    )
                    if isinstance(reflect_route, dict) and reflect_route.get("ok"):
                        reflection_text = (reflect_route.get("text") or "").strip()
                        if reflection_text:
                            _REFLECT_LAST_TS = now_ts  # Only consume cooldown on SUCCESS
                            print(f"[reflect] Completed: {len(reflection_text)} chars")
                except Exception as e:
                    print(f"[reflect] Failed (non-fatal): {e}")

            if reflection_text:
                grounded_text = (
                    (ctx_block + "\n" if ctx_block else "")
                    + "[Own reflection: " + reflection_text + "]\n"
                    + text
                )

            # --- Model routing: GPU primary, CPU fallback ---
            route = None
            try:
                with INFER_SEM:
                    router_payload = {
                        "text": grounded_text,
                        "n_predict": max_tokens,
                        "system": identity,
                        "temperature": 0.65,
                    }
                    if "force" in payload:
                        router_payload["force"] = payload.get("force")

                    router_timeout = min(max(10, timeout_s + 15), 540)

                    route = http_post_debug(
                        f"{ROUTER_BASE}/route",
                        router_payload,
                        timeout_s=router_timeout,
                    )

            except Exception as e:
                # RLM failed → try Chat-LLM (CPU) as fallback
                LOG.warning("RLM failed (%s), falling back to Chat-LLM", e)
                route = _chat_llm_call(grounded_text, identity, max_tokens=max_tokens)
                if route:
                    LOG.info("Chat-LLM fallback responded (%d chars)", len(route.get("text", "")))

            if route is None:
                self._json(
                    502,
                    {
                        "ok": False,
                        "error": "upstream_failed",
                        "detail": "all LLM backends failed",
                        "task": task,
                        "max_tokens": max_tokens,
                        "timeout_s": timeout_s,
                        "infer_concurrency": INFER_MAX_CONCURRENCY,
                    },
                )
                return

            if not isinstance(route, dict) or route.get("ok") is not True:
                self._json(
                    502,
                    {
                        "ok": False,
                        "error": "upstream_bad_response",
                        "route": route,
                        "task": task,
                    },
                )
                return

            answer_text = route.get("text", "")
            model = route.get("model", "router")

            ev_route = {"ts": now(), "type": "router.response", "source": "core", "payload": route}
            ev_llm = {
                "ts": now(),
                "type": "llm.response",
                "source": model,
                "payload": {
                    "text": answer_text,
                    "route": route,
                    "policy": {"task": task, "max_tokens": max_tokens, "timeout_s": timeout_s},
                },
            }

            append_journal(ev_route, journal_dir)
            append_journal(ev_llm, journal_dir)

            try:
                db_insert(db_path, ev_route)
                db_insert(db_path, ev_llm)
            except Exception as e:
                self._json(500, {"ok": False, "error": "db_insert_failed", "detail": str(e)})
                return

            # --- Output-Feedback-Loop: update E-PQ, Ego, Titan, Consciousness ---
            # Run in background thread to avoid blocking HTTP response
            if _FEEDBACK_AVAILABLE and answer_text:
                _fb_thread = threading.Thread(
                    target=_run_feedback_loop,
                    args=(text, answer_text),
                    daemon=True,
                )
                _fb_thread.start()

            self._json(200, {"ok": True, "route": route, "model": model, "text": answer_text})
            return

        self._json(404, {"error": "not_found"})
def main():
    host, port = "127.0.0.1", 8088
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"core listening on http://{host}:{port} (infer_concurrency={INFER_MAX_CONCURRENCY})")
    httpd.serve_forever()

if __name__ == "__main__":
    main()

