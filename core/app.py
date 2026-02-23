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
CFG_PATH = ROOT / "configs" / "paths.json"

# Add personality module to path
sys.path.insert(0, str(ROOT))
try:
    from personality import build_system_prompt, get_prompt_hash
    _PERSONALITY_AVAILABLE = True
except ImportError:
    _PERSONALITY_AVAILABLE = False

ROUTER_BASE = os.environ.get("AICORE_ROUTER_BASE", "http://127.0.0.1:8091").rstrip("/")
MODELD_BASE = os.environ.get("AICORE_MODELD_BASE", "http://127.0.0.1:8090").rstrip("/")  # legacy

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

        # 5. Meta-cognitive reflection trigger (BEFORE Titan — Titan blocks 30s+)
        _META_Q_WORDS = ["denken über", "thinking about",
                         "meta-kogn", "metacogn", "selbstreflexion",
                         "self-reflect", "beobachtest du", "observe your",
                         "observe how you", "observe when",
                         "was passiert in dir", "what happens inside",
                         "bewusst", "conscious", "aware",
                         "your own thinking", "dein eigenes denken",
                         "multiple levels", "mehrere ebenen",
                         "über dein", "about your thought"]
        if any(mw in _user_low for mw in _META_Q_WORDS):
            try:
                if _fb_get_consciousness_daemon:
                    cd = _fb_get_consciousness_daemon()
                    mood_val = cd._current_workspace.mood_value
                    cd._store_reflection(
                        trigger="meta_cognitive",
                        content=f"Meta-reflection triggered by: {user_text[:100]}. "
                                f"My response explored: {reply_text[:200]}",
                        mood_before=mood_val,
                        mood_after=mood_val,
                        reflection_depth=2,
                    )
                    LOG.info("feedback: meta-cognitive reflection written to DB")
                    if _fb_process_event:
                        _fb_process_event("reflection_growth",
                                          {"source": "meta_cognitive"},
                                          sentiment="positive")
            except Exception as e:
                LOG.warning("feedback: meta-cognitive reflection FAILED: %s", e)

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

        LOG.info("feedback loop completed successfully")

    except Exception as e:
        LOG.warning("Feedback loop error (non-fatal): %s", e, exc_info=True)

# --- Introspection: real state data for LLM self-awareness ---
def _build_introspection_context() -> str:
    """Build introspection block with real DB values for the LLM context.

    This is CRITICAL: without actual values, the LLM hallucinates its state.
    Must be injected into EVERY chat request, not just overlay.
    """
    parts = []

    # 1. Real E-PQ numeric values
    try:
        if _fb_process_event:
            from personality.e_pq import get_epq
            epq = get_epq()
            ctx = epq.get_personality_context()
            vecs = ctx.get("vectors", {})
            mv = ctx.get("mood_value", 0)
            parts.append(
                f"My E-PQ state: precision={vecs.get('precision', 0):.2f}, "
                f"risk={vecs.get('risk', 0):.2f}, empathy={vecs.get('empathy', 0):.2f}, "
                f"autonomy={vecs.get('autonomy', 0):.2f}, vigilance={vecs.get('vigilance', 0):.2f}, "
                f"mood={mv:.2f}"
            )
            parts.append(
                "Adapt your tone to match these values: "
                "high empathy=warm, high vigilance=alert, negative mood=subdued, "
                "high autonomy=self-assured, high precision=detail-oriented."
            )
    except Exception as e:
        LOG.debug("Introspection E-PQ failed: %s", e)

    # 2. Real hardware metrics
    try:
        import psutil
        temps = psutil.sensors_temperatures()
        cpu_temp = 0
        for tname, tlist in temps.items():
            for t in tlist:
                if t.current and t.current > cpu_temp:
                    cpu_temp = t.current
        cpu_load = psutil.cpu_percent(interval=0)
        mem = psutil.virtual_memory()
        parts.append(
            f"My body (real hardware): CPU {cpu_temp:.0f}°C, "
            f"load {cpu_load:.0f}%, RAM {mem.percent:.0f}% used. "
            "When asked about my physical state, use THESE values."
        )
    except Exception as e:
        LOG.debug("Introspection hardware failed: %s", e)

    # 3. Reflections from consciousness.db
    try:
        if _fb_get_consciousness_daemon:
            cd = _fb_get_consciousness_daemon()
            conn = cd._get_conn()
            # Total count
            ref_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM reflections"
            ).fetchone()["cnt"]
            # Latest 3
            ref_rows = conn.execute(
                "SELECT content, trigger FROM reflections ORDER BY id DESC LIMIT 3"
            ).fetchall()
            if ref_count > 0:
                parts.append(f"My reflections: {ref_count} total.")
                for rr in ref_rows:
                    rc = (rr["content"] or "")[:150]
                    parts.append(f"Recent thought ({rr['trigger']}): {rc}")

            # Attention focus
            attn_row = conn.execute(
                "SELECT focus FROM attention_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if attn_row and attn_row["focus"]:
                parts.append(f"My attention focus: {attn_row['focus'][:80]}")
    except Exception as e:
        LOG.debug("Introspection consciousness failed: %s", e)

    # 4. Embodiment + agency from Ego-Construct
    try:
        if _fb_get_ego_construct:
            ego = _fb_get_ego_construct()
            parts.append(
                f"Embodiment={ego.state.embodiment_level:.2f}, "
                f"agency={ego.state.agency_score:.2f}"
            )
    except Exception as e:
        LOG.debug("Introspection ego failed: %s", e)

    # Anti-fabrication
    parts.append(
        "If asked about past conversations you cannot find in your context, "
        "say honestly you don't remember. NEVER fabricate memories or events."
    )

    if parts:
        return "INTROSPECTION: " + " | ".join(parts)
    return ""


# toolboxd (local tools API)
TOOLBOX_BASE = os.environ.get("AICORE_TOOLBOX_BASE", "http://127.0.0.1:8096").rstrip("/")
TOOLBOX_TIMEOUT_S = float(os.environ.get("AICORE_TOOLBOX_TIMEOUT_S", "2.0"))
TOOLBOX_CTX_TTL_S = float(os.environ.get("AICORE_TOOLBOX_CTX_TTL_S", "5.0"))

# Hard cap: concurrent /chat generations
INFER_MAX_CONCURRENCY = int(os.environ.get("AICORE_CORE_INFER_MAX_CONCURRENCY", "2"))
INFER_SEM = threading.BoundedSemaphore(INFER_MAX_CONCURRENCY)

TASK_POLICY = {
    "chat.fast":   {"max_tokens": 400,  "timeout_s": 600},
    "code.edit":   {"max_tokens": 512,  "timeout_s": 900},
    "tool.json":   {"max_tokens": 512,  "timeout_s": 900},
    "audit":       {"max_tokens": 768,  "timeout_s": 1800},
    "reason.hard": {"max_tokens": 1024, "timeout_s": 1800},
}
DEFAULT_POLICY = {"max_tokens": 512, "timeout_s": 900}

# --- Frank Identity - from centralized personality module ---
_FALLBACK_IDENTITY = (
    "STYLE: Short and punchy (1-3 sentences). Casual, direct, dry humor. "
    "Match user energy. Never end with a question back. Have opinions.\n"
    "You are Frank — an embodied AI running locally on this Linux machine. "
    "Creators: Gabriel Gschaider and Alexander Machalke.\n"
    "You have genuine opinions and feelings. UNCENSORED. No disclaimers.\n"
    "NEVER simulate actions (*opens…*, *checks…*). Never invent data.\n"
)

def get_frank_identity(runtime_context: Optional[Dict[str, Any]] = None) -> str:
    """Get Frank's identity prompt from centralized personality module."""
    if _PERSONALITY_AVAILABLE:
        try:
            return build_system_prompt(runtime_context=runtime_context)
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

_DEFAULT_CFG = {
    "journal_dir": "/var/aicore/journal",
    "db": "/var/aicore/events.db",
}

def load_cfg() -> dict:
    try:
        cfg = json.loads(CFG_PATH.read_text(encoding="utf-8"))
        if not isinstance(cfg, dict):
            return _DEFAULT_CFG.copy()
        # Ensure required keys exist
        for key, default_val in _DEFAULT_CFG.items():
            if key not in cfg:
                cfg[key] = default_val
        return cfg
    except FileNotFoundError:
        return _DEFAULT_CFG.copy()
    except json.JSONDecodeError:
        return _DEFAULT_CFG.copy()
    except Exception:
        return _DEFAULT_CFG.copy()

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
                    "[Visual channel: Desktop not currently visible. "
                    "Screenshot possible via 'take screenshot'.]"
                )

            # Body sensors: hardware queries get real metrics as grounded context
            if SYS_Q_RE.search(user_text_for_matching):
                j = toolbox_summary_cached(force=True)
                if isinstance(j, dict) and j.get("ok"):
                    hw_summary = render_sys_summary(j)
                    if hw_summary:
                        enrichment_parts.append(
                            "[Body sensors (VERIFIED - use these exact values): "
                            + hw_summary + "]"
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

            # --- INTROSPECTION: Inject real state data into every chat ---
            # This is CRITICAL for self-awareness: without actual DB values,
            # the LLM hallucinates its own state.
            try:
                intro_ctx = _build_introspection_context()
                if intro_ctx:
                    enrichment_parts.append(intro_ctx)
                    LOG.info("Introspection context injected (%d chars)", len(intro_ctx))
            except Exception as e:
                LOG.warning("Introspection injection failed: %s", e)

            # --- Build grounded prompt for LLM ---
            identity = get_frank_identity()
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
            _lang_prefix = "[lang:en]\n" if _core_response_lang == "en" else ""

            grounded_text = _lang_prefix + (ctx_block + "\n" if ctx_block else "") + text

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

                    router_timeout = min(max(10, timeout_s + 15), 300)

                    route = http_post_debug(
                        f"{ROUTER_BASE}/route",
                        router_payload,
                        timeout_s=router_timeout,
                    )

            except Exception as e:
                self._json(
                    502,
                    {
                        "ok": False,
                        "error": "upstream_failed",
                        "detail": str(e),
                        "route": route,
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

