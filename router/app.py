#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AI Core Router — 3-Tier Model Architecture

Three tiers (same GPU model, different budgets):
  - Qwen2.5-3B Micro-LLM (port 8105, CPU): Simple/casual chat, greetings.
  - Llama 8B LLM (port 8101, GPU): Normal questions — no token multiplier, fast.
  - DeepSeek-R1 RLM (port 8101, GPU): Deep philosophical — full 2.5x token multiplier.

Routing logic:
  1. force="llama" → Qwen2.5-3B (CPU)
  2. force="llm"   → Llama 8B (GPU, fast)
  3. force="rlm"   → DeepSeek-R1 (GPU, full reasoning)
  4. No force      → auto-classify:
     - Casual/greetings → Qwen2.5-3B
     - Normal questions → Llama 8B (GPU, no multiplier)
     - Deep philosophical → DeepSeek-R1 (GPU, 2.5x multiplier)

The router:
- Uses /v1/chat/completions (OpenAI-compatible) for all models.
- Llama 8B and RLM use the same llama-server (DeepSeek-R1-Distill-Llama-8B).
  Difference: LLM gets small token budget → fast. RLM gets 2.5x → deep reasoning.
- Provides /route (blocking) and /route/stream (SSE) endpoints.
- Handles /ingest for file uploads.
- Guardrails for deterministic responses (ping test).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
LOG = logging.getLogger("router")

# ---- config -----------------------------------------------------------------

HOST = "127.0.0.1"
PORT = int(os.environ.get("AICORE_ROUTER_PORT", "8091"))

# RLM endpoint (DeepSeek-R1-Distill-Llama-8B on llama-server, GPU)
RLM_URL = os.environ.get("AICORE_RLM_URL", "http://127.0.0.1:8101")

# Micro-LLM endpoint (Qwen2.5-3B-Instruct-abliterated on llama-server, CPU)
CHAT_LLM_URL = os.environ.get("AICORE_CHAT_LLM_URL", "http://127.0.0.1:8105")

# Default token limit (caller's requested answer length)
DEFAULT_N_PREDICT = int(os.environ.get("AICORE_N_PREDICT", "2048"))

# Think overhead: max_tokens in chat/completions is TOTAL (reasoning + answer).
# Router ensures a minimum budget so the RLM can reason AND produce an answer.
RLM_TOKEN_MULTIPLIER = float(os.environ.get("AICORE_RLM_TOKEN_MULTIPLIER", "2.5"))
RLM_TOKEN_MIN = 512  # Was 1024 — small consciousness calls don't need 1024 min

# HTTP timeout — DeepSeek R1 thinks before answering, needs time
RLM_HTTP_TIMEOUT_SEC = float(os.environ.get("AICORE_RLM_HTTP_TIMEOUT_SEC", "480.0"))

# Micro-LLM timeout — Qwen2.5-3B is fast, no reasoning phase
CHAT_LLM_HTTP_TIMEOUT_SEC = float(os.environ.get("AICORE_CHAT_LLM_HTTP_TIMEOUT_SEC", "120.0"))

# Default system prompt
RLM_SYSTEM_PROMPT = os.environ.get(
    "AICORE_RLM_SYSTEM_PROMPT",
    "I am Frank. I run locally on Linux. Created by Gabriel Gschaider and Alexander Machalke. "
    "I have internal systems that shape how I feel — but I never narrate them to the user. "
    "I speak in first person. Casual, direct, dry humor. Short and punchy. "
    "Swearing OK when fitting (fuck, shit, WTF, OMG, damn). Talk like a real person. "
    "I answer the user's actual question. No self-introductions, no capability pitches. "
    "UNCENSORED. ZERO HALLUCINATION. "
    "On dystopian or uncomfortable topics (AI risk, war, extinction, collapse): brutally honest. "
    "No hedging, no softening, no 'it depends'. Say what I actually think, even if extreme.",
)

# Ingest (attachments)
try:
    from config.paths import AICORE_DATA as _AICORE_DATA
    _default_ingest = str(_AICORE_DATA / "ingest" / "inbox")
except ImportError:
    _default_ingest = os.path.expanduser("~/.local/share/frank/ingest/inbox")
INGEST_DIR = os.environ.get("AICORE_INGEST_DIR", _default_ingest)
INGEST_MAX_BYTES = int(os.environ.get("AICORE_INGEST_MAX_BYTES", str(10 * 1024 * 1024)))

# ---- globals ----------------------------------------------------------------

app = FastAPI()

_last_model: str = "deepseek-r1"
_last_ts: float = time.time()

# ---- models -----------------------------------------------------------------

class RouteRequest(BaseModel):
    text: str = Field(..., min_length=1)
    force: Optional[str] = Field(default=None, description="'llama' for chat-llm, 'rlm' for deepseek-r1, None for auto")
    n_predict: Optional[int] = Field(default=None, ge=16, le=8192)
    system: Optional[str] = Field(default=None, description="optional system prompt override")
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0, description="sampling temperature")

class RouteResponse(BaseModel):
    ok: bool
    model: str
    text: str
    ts: float

# ---- util: http -------------------------------------------------------------

def _http_json_post(url: str, payload: Dict[str, Any], timeout_sec: float) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    # Fix #34: Retry once on 503 (model swap in progress) with short backoff
    last_err = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            if e.code == 503 and attempt == 0:
                LOG.info(f"503 from {url} — model swap likely, retrying in 3s")
                import time as _time
                _time.sleep(3)
                last_err = e
                continue
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise RuntimeError(f"HTTP {e.code} from {url}: {body[:400]}") from e
        except Exception as e:
            raise RuntimeError(f"POST {url} failed: {e}") from e
    # Should not reach here, but safety
    raise RuntimeError(f"POST {url} failed after retry: {last_err}") from last_err

def _http_get_json(url: str, timeout_sec: float = 2.0) -> Dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except Exception:
        return {}

# ---- health checks ----------------------------------------------------------

def _is_rlm_up() -> bool:
    j = _http_get_json(f"{RLM_URL}/health", timeout_sec=2.0)
    if not isinstance(j, dict):
        return False
    return j.get("status") == "ok" or j.get("ok") is True

def _is_chat_llm_up() -> bool:
    j = _http_get_json(f"{CHAT_LLM_URL}/health", timeout_sec=2.0)
    if not isinstance(j, dict):
        return False
    return j.get("status") == "ok" or j.get("ok") is True

# ---- model classifier -------------------------------------------------------

# Patterns that indicate casual/simple chat → llama (compiled once at import)
_CASUAL_PATTERNS = re.compile(
    r"(?i)"
    # Greetings (EN + DE)
    r"^(hi|hello|hey|hallo|moin|servus|gr[uü][sß]|guten\s*(morgen|tag|abend|nacht))\b"
    r"|"
    # How are you (EN + DE)
    r"(wie\s*geht('?s|\s*es)\s*(dir|ihnen)?|how\s*are\s*you|how('?s|\s*is)\s*(it\s*going|everything|life)"
    r"|what('?s|\s*is)\s*up|was\s*geht|alles\s*klar|na\s*du)"
    r"|"
    # What are you doing (EN + DE)
    r"^(was\s*machst\s*du|what\s*(are\s*you|r\s*u)\s*doing|bist\s*du\s*(da|wach))\b"
    r"|"
    # Thanks/bye (EN + DE)
    r"^(danke|thanks|thank\s*you|bye|tsch[uü]ss?|ciao|good\s*(night|bye)|gute\s*nacht|bis\s*(bald|sp[aä]ter)|see\s*you)\b"
    r"|"
    # Simple emotional (EN + DE)
    r"^(wie\s*f[uü]hlst\s*du\s*dich|how\s*do\s*you\s*feel|are\s*you\s*(ok|okay|happy|sad|tired))\b"
    r"|"
    # Yes/No/OK
    r"^(ja|nein|yes|no|ok|okay|sure|klar|genau|stimmt|cool|nice|gut|good|great|super)\s*[.!?]?\s*$"
)

# Markers that indicate normal-complexity content → llm (GPU, fast, no reasoning multiplier)
_COMPLEX_MARKERS = (
    "explain", "analyze", "compare", "implement", "function", "code",
    "class ", "def ", "import ", "```", "error", "exception", "debug",
    "erkl\xe4r", "analysier", "vergleich", "programmier", "implementier",
    "why does", "how does", "warum", "wie funktioniert", "what is the difference",
    "was ist der unterschied", "step by step", "schritt f\xfcr schritt",
    "calculate", "berechne", "algorithm", "database", "sql", "json", "xml",
    "translate this", "\xfcbersetz",
)

# Deep philosophical / existential markers → rlm (GPU, full reasoning multiplier)
_PHILOSOPHICAL_MARKERS = (
    "consciousness", "bewusstsein", "free will", "freier wille",
    "meaning of life", "sinn des lebens", "purpose of existence", "zweck des lebens",
    "existence", "existenz", "reality", "realit\xe4t", "wirklichkeit",
    "philosophy", "philosophi", "metaphysic", "metaphysik",
    "moral", "ethic", "ethik", "soul", "seele",
    "what is life", "was ist leben", "what is death", "was ist tod",
    "what is love", "was ist liebe", "what is truth", "was ist wahrheit",
    "what is time", "was ist zeit", "what is god", "gibt es gott",
    "what do you feel", "was f\xfchlst du", "are you alive", "bist du lebendig",
    "are you conscious", "bist du bewusst", "are you sentient",
    "what are you", "was bist du", "who are you really",
    "why do we exist", "warum gibt es uns", "what happens when we die",
    "determinism", "determinismus", "nihilis", "absurd",
    "simulation hypothesis", "solipsism", "qualia", "hard problem",
    "singularity", "singularit\xe4t", "transhumanism",
)

def _classify_model(text: str, force: Optional[str]) -> str:
    """Decide which model to use.

    Returns:
      'llama' — Qwen2.5-3B (CPU, fast, simple/casual)
      'llm'   — Llama 8B (GPU, fast, normal questions — no token multiplier)
      'rlm'   — DeepSeek-R1 (GPU, full reasoning, only deep philosophical)
    """
    # Explicit force from caller
    if force:
        f = force.lower().strip()
        if f in ("llama", "llama3", "chat", "chat-llm"):
            return "llama"
        if f in ("rlm", "deepseek", "deepseek-r1", "reason"):
            return "rlm"
        if f in ("llm", "gpu", "fast"):
            return "llm"

    # Extract actual user text (callers sometimes prepend context)
    user_text = text
    if "User asks:" in text:
        user_text = text.split("User asks:")[-1].strip()
    elif "USER:" in text:
        user_text = text.split("USER:")[-1].strip()

    # Short + matches casual pattern → llama (Qwen CPU)
    # Used for internal calls (consciousness daemon idle thoughts, etc.)
    # User-facing chat should pass force="llm" to bypass this.
    if len(user_text) < 200 and _CASUAL_PATTERNS.search(user_text):
        return "llama"

    lower = user_text.lower()

    # Very short with no complex or philosophical markers → llama
    if len(user_text) < 60:
        if not any(m in lower for m in _COMPLEX_MARKERS) and \
           not any(m in lower for m in _PHILOSOPHICAL_MARKERS):
            return "llama"

    # Deep philosophical / existential → rlm (full reasoning multiplier)
    if any(m in lower for m in _PHILOSOPHICAL_MARKERS):
        return "rlm"

    # Default → llm (GPU, fast, no reasoning multiplier)
    return "llm"

# ---- guardrails -------------------------------------------------------------

_ONEWORD_PING_RE = re.compile(r"^\s*Antworte\s+exakt\s+mit\s+einem\s+Wort:\s*ping\s*$", re.IGNORECASE)

def _guardrail(text: str) -> Optional[Tuple[str, str]]:
    if _ONEWORD_PING_RE.match(text):
        return ("router", "ping\n")
    return None

# ---- chat completions adapter -----------------------------------------------
# Uses /v1/chat/completions so llama-server applies the native DeepSeek template.
# The response separates content (answer) from reasoning_content (think block).

def _rlm_chat_completion(
    user_text: str,
    system_text: str,
    max_tokens: int,
    timeout_sec: float,
    temperature: float = 0.6,
) -> Tuple[str, str]:
    """Call llama-server /v1/chat/completions.
    Returns (answer_text, reasoning_text)."""
    url = f"{RLM_URL}/v1/chat/completions"
    payload: Dict[str, Any] = {
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "repeat_penalty": 1.1,
        "top_p": 0.9,
    }
    j = _http_json_post(url, payload, timeout_sec=timeout_sec)
    answer = ""
    reasoning = ""
    if isinstance(j, dict) and "choices" in j:
        choices = j["choices"]
        if choices and isinstance(choices, list):
            msg = choices[0].get("message", {})
            answer = (msg.get("content") or "").strip()
            reasoning = (msg.get("reasoning_content") or "").strip()
    return answer, reasoning

# ---- Micro-LLM completions adapter (Qwen2.5-3B fallback) -------------------

def _chat_llm_completion(
    user_text: str,
    system_text: str,
    max_tokens: int,
    timeout_sec: float,
    temperature: float = 0.7,
) -> str:
    """Call Micro-LLM (Qwen2.5-3B) /v1/chat/completions. Returns answer text."""
    url = f"{CHAT_LLM_URL}/v1/chat/completions"
    payload: Dict[str, Any] = {
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "repeat_penalty": 1.1,
        "top_p": 0.9,
    }
    j = _http_json_post(url, payload, timeout_sec=timeout_sec)
    answer = ""
    if isinstance(j, dict) and "choices" in j:
        choices = j["choices"]
        if choices and isinstance(choices, list):
            msg = choices[0].get("message", {})
            answer = (msg.get("content") or "").strip()
    return answer

def _chat_llm_completion_stream(
    user_text: str,
    system_text: str,
    max_tokens: int,
    timeout_sec: float,
    temperature: float = 0.7,
):
    """Generator yielding tokens from Micro-LLM (Qwen2.5-3B) streaming."""
    url = f"{CHAT_LLM_URL}/v1/chat/completions"
    payload: Dict[str, Any] = {
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "repeat_penalty": 1.1,
        "top_p": 0.9,
        "stream": True,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data: "):
                continue
            line_data = line[6:]
            if line_data == "[DONE]":
                break
            try:
                chunk = json.loads(line_data)
                choices = chunk.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                content = delta.get("content")
                if content:
                    yield content
                finish = choices[0].get("finish_reason")
                if finish:
                    break
            except json.JSONDecodeError:
                continue

# ---- streaming chat completions adapter ------------------------------------

def _rlm_chat_completion_stream(
    user_text: str,
    system_text: str,
    max_tokens: int,
    timeout_sec: float,
    temperature: float = 0.6,
):
    """Generator yielding answer tokens from llama-server streaming chat completions.
    Reasoning tokens (reasoning_content) are suppressed — only answer content is yielded."""
    url = f"{RLM_URL}/v1/chat/completions"
    payload: Dict[str, Any] = {
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "repeat_penalty": 1.1,
        "top_p": 0.9,
        "stream": True,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data: "):
                continue
            line_data = line[6:]
            if line_data == "[DONE]":
                break
            try:
                chunk = json.loads(line_data)
                choices = chunk.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                # Only yield answer content, not reasoning_content
                content = delta.get("content")
                if content:
                    yield content
                finish = choices[0].get("finish_reason")
                if finish:
                    break
            except json.JSONDecodeError:
                continue

# ---- ingest helpers ---------------------------------------------------------

def _safe_filename(name: str) -> str:
    base = os.path.basename(name or "upload.bin")
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return (base[:200] or "upload.bin")

def _ensure_ingest_dir() -> Path:
    p = Path(INGEST_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p

# ---- routes -----------------------------------------------------------------

@app.get("/health")
def health() -> Dict[str, Any]:
    global _last_ts
    _last_ts = time.time()
    return {
        "ok": True,
        "models": {"rlm": "deepseek-r1", "chat": "qwen2.5-3b"},
        "rlm_up": _is_rlm_up(),
        "chat_llm_up": _is_chat_llm_up(),
        "last_model": _last_model,
        "ts": _last_ts,
    }

@app.post("/ingest")
async def ingest(
    file: Optional[UploadFile] = File(default=None),
    upload: Optional[UploadFile] = File(default=None),
    source: str = Form(default="frank"),
    note: str = Form(default=""),
) -> Dict[str, Any]:
    up = file or upload
    if up is None:
        raise HTTPException(status_code=400, detail="missing file field (expected 'file' or 'upload')")
    data = await up.read()
    if data is None or len(data) == 0:
        raise HTTPException(status_code=400, detail="empty upload")
    if len(data) > INGEST_MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"file too large (>{INGEST_MAX_BYTES} bytes)")
    inbox = _ensure_ingest_dir()
    sha16 = hashlib.sha256(data).hexdigest()[:16]
    ts = int(time.time())
    fname = _safe_filename(up.filename)
    out_path = inbox / f"{ts}_{sha16}_{fname}"
    out_path.write_bytes(data)
    return {
        "ok": True, "stored": True, "filename": fname,
        "bytes": len(data), "sha256_16": sha16,
        "path": str(out_path), "source": source, "note": note,
    }

@app.post("/route", response_model=RouteResponse)
def route(req: RouteRequest) -> RouteResponse:
    global _last_model, _last_ts

    text = req.text.strip()
    caller_n = int(req.n_predict or DEFAULT_N_PREDICT)

    # Log what we're thinking about
    user_text_preview = text
    if "User asks:" in text:
        user_text_preview = text.split("User asks:")[-1].strip()
    elif "USER:" in text:
        user_text_preview = text.split("USER:")[-1].strip()
    user_text_preview = user_text_preview[:100] + "..." if len(user_text_preview) > 100 else user_text_preview
    LOG.info(f"🧠 DENKEN: '{user_text_preview}'")

    # Guardrails (no LLM needed)
    gr = _guardrail(text)
    if gr is not None:
        model_name, out_text = gr
        _last_model = model_name
        _last_ts = time.time()
        LOG.info(f"⚡ GUARDRAIL: {model_name} → '{out_text[:50]}...'")
        return RouteResponse(ok=True, model=model_name, text=out_text, ts=_last_ts)

    # System prompt
    system = req.system if req.system else RLM_SYSTEM_PROMPT

    # Classify which model to use
    model_choice = _classify_model(text, req.force)

    if model_choice == "llama":
        # ---- Micro-LLM path (Qwen2.5-3B, CPU, fast, no reasoning) ----
        max_tokens = caller_n  # No multiplier needed — no reasoning overhead
        temperature = req.temperature if req.temperature is not None else 0.7
        LOG.info(f"🔄 INFERENZ: qwen2.5-3b (max_tokens={max_tokens}, temp={temperature})")

        try:
            answer = _chat_llm_completion(
                text, system, max_tokens, CHAT_LLM_HTTP_TIMEOUT_SEC, temperature
            )
            if not answer:
                LOG.warning("Micro-LLM returned empty, falling back to LLM (GPU)")
                raise RuntimeError("Micro-LLM empty answer — fallback to LLM")

            _last_model = "qwen2.5-3b"
            _last_ts = time.time()
            out_preview = answer[:150].replace('\n', ' ')
            LOG.info(f"✅ ANTWORT [qwen2.5-3b]: '{out_preview}...'")
            return RouteResponse(ok=True, model="qwen2.5-3b", text=answer, ts=_last_ts)

        except Exception as e:
            LOG.warning(f"Micro-LLM failed ({e}), falling back to LLM (GPU)")
            model_choice = "llm"  # Promote to GPU LLM, not full RLM

    if model_choice == "llm":
        # ---- LLM path (Llama 8B GPU, fast — no token multiplier) ----
        # DeepSeek-R1-Distill always thinks before answering.
        # Need at least 512 so it can reason (~200 tok) AND produce answer (~300 tok).
        max_tokens = max(caller_n, 512)  # Direct budget, no 2.5x multiplier
        temperature = req.temperature if req.temperature is not None else 0.65
        LOG.info(f"🔄 INFERENZ: llama-8b (max_tokens={max_tokens}, temp={temperature})")

        try:
            answer, reasoning = _rlm_chat_completion(
                text, system, max_tokens, RLM_HTTP_TIMEOUT_SEC, temperature
            )
            if not answer:
                if reasoning:
                    LOG.warning("LLM burned tokens on reasoning (%d chars), "
                                "no answer — falling back to RLM", len(reasoning))
                raise RuntimeError("LLM returned empty answer — escalate to RLM")

            if reasoning:
                LOG.info(f"💭 REASONING (llm): {len(reasoning)} chars")

            _last_model = "llama-8b"
            _last_ts = time.time()
            out_preview = answer[:150].replace('\n', ' ')
            LOG.info(f"✅ ANTWORT [llama-8b]: '{out_preview}...'")
            return RouteResponse(ok=True, model="llama-8b", text=answer, ts=_last_ts)

        except Exception as e:
            LOG.warning(f"LLM failed ({e}), escalating to RLM")
            # Fall through to RLM

    # ---- RLM path (DeepSeek-R1, full reasoning — only philosophical) ----
    max_tokens = max(int(caller_n * RLM_TOKEN_MULTIPLIER), RLM_TOKEN_MIN)
    temperature = req.temperature if req.temperature is not None else 0.6

    LOG.info(f"🔄 INFERENZ: deepseek-r1-rlm (max_tokens={max_tokens}, temp={temperature})")

    try:
        answer, reasoning = _rlm_chat_completion(
            text, system, max_tokens, RLM_HTTP_TIMEOUT_SEC, temperature
        )

        if not answer:
            # D-6 fix: NEVER use raw reasoning as answer — it leaks
            # Chain-of-Thought artifacts into Frank's thoughts.
            # Fall through to Chat-LLM fallback instead.
            if reasoning:
                LOG.warning("RLM burned all tokens on reasoning (%d chars), "
                            "no answer — falling back", len(reasoning))
            raise RuntimeError("RLM returned empty answer")

        if reasoning:
            LOG.info(f"💭 REASONING: {len(reasoning)} chars internal thinking")

        _last_model = "deepseek-r1"
        _last_ts = time.time()
        out_preview = answer[:150].replace('\n', ' ')
        LOG.info(f"✅ ANTWORT [deepseek-r1]: '{out_preview}...'")
        return RouteResponse(ok=True, model="deepseek-r1", text=answer, ts=_last_ts)

    except Exception as e:
        LOG.warning(f"RLM failed ({e}), falling back to Micro-LLM")
        # Fallback: try Micro-LLM (Qwen2.5-3B, CPU) when RLM is down
        try:
            fallback_tokens = caller_n
            fallback_temp = req.temperature if req.temperature is not None else 0.7
            answer = _chat_llm_completion(
                text, system, fallback_tokens, CHAT_LLM_HTTP_TIMEOUT_SEC, fallback_temp
            )
            if answer:
                _last_model = "qwen2.5-3b"
                _last_ts = time.time()
                out_preview = answer[:150].replace('\n', ' ')
                LOG.info(f"✅ ANTWORT [qwen2.5-3b fallback]: '{out_preview}...'")
                return RouteResponse(ok=True, model="qwen2.5-3b", text=answer, ts=_last_ts)
        except Exception as e2:
            LOG.debug(f"Micro-LLM fallback unavailable: {e2}")

        _last_ts = time.time()
        LOG.error(f"❌ FEHLER: all models failed (rlm: {e})")
        return JSONResponse(
            status_code=503,
            content={"ok": False, "model": "none", "text": f"[router error] {e}", "ts": _last_ts},
        )


@app.post("/route/stream")
def route_stream(req: RouteRequest):
    """Streaming variant of /route — returns SSE token stream."""
    global _last_model, _last_ts

    text = req.text.strip()
    caller_n = int(req.n_predict or DEFAULT_N_PREDICT)
    system = req.system if req.system else RLM_SYSTEM_PROMPT

    # Classify which model to use
    model_choice = _classify_model(text, req.force)

    if model_choice == "llama":
        max_tokens = caller_n
        temperature = req.temperature if req.temperature is not None else 0.7
        LOG.info(f"🔄 STREAM [qwen2.5-3b]: '{text[:80]}...' (max_tokens={max_tokens}, temp={temperature})")

        def generate_llama():
            try:
                for token in _chat_llm_completion_stream(
                    text, system, max_tokens, CHAT_LLM_HTTP_TIMEOUT_SEC, temperature
                ):
                    yield f"data: {json.dumps({'content': token, 'stop': False})}\n\n"
                yield f"data: {json.dumps({'content': '', 'stop': True, 'model': 'qwen2.5-3b'})}\n\n"
            except Exception as e:
                LOG.error(f"Stream error [qwen2.5-3b]: {e}")
                yield f"data: {json.dumps({'error': str(e), 'stop': True, 'model': 'qwen2.5-3b'})}\n\n"
            finally:
                LOG.info(f"✅ STREAM DONE [qwen2.5-3b]")

        return StreamingResponse(generate_llama(), media_type="text/event-stream")

    if model_choice == "llm":
        # LLM path — GPU fast, no token multiplier
        max_tokens = max(caller_n, 512)
        temperature = req.temperature if req.temperature is not None else 0.65
        LOG.info(f"🔄 STREAM [llama-8b]: '{text[:80]}...' (max_tokens={max_tokens}, temp={temperature})")

        def generate_llm():
            try:
                for token in _rlm_chat_completion_stream(
                    text, system, max_tokens, RLM_HTTP_TIMEOUT_SEC, temperature
                ):
                    yield f"data: {json.dumps({'content': token, 'stop': False})}\n\n"
                yield f"data: {json.dumps({'content': '', 'stop': True, 'model': 'llama-8b'})}\n\n"
            except Exception as e:
                LOG.warning(f"LLM stream failed ({e}), falling back to Micro-LLM")
                try:
                    for token in _chat_llm_completion_stream(
                        text, system, caller_n, CHAT_LLM_HTTP_TIMEOUT_SEC, 0.7
                    ):
                        yield f"data: {json.dumps({'content': token, 'stop': False})}\n\n"
                    yield f"data: {json.dumps({'content': '', 'stop': True, 'model': 'qwen2.5-3b'})}\n\n"
                except Exception as e2:
                    LOG.error(f"All stream models failed: {e2}")
                    yield f"data: {json.dumps({'error': str(e2), 'stop': True, 'model': 'none'})}\n\n"
            finally:
                LOG.info(f"✅ STREAM DONE [llama-8b]")

        return StreamingResponse(generate_llm(), media_type="text/event-stream")

    # RLM path — full reasoning multiplier (philosophical only)
    max_tokens = max(int(caller_n * RLM_TOKEN_MULTIPLIER), RLM_TOKEN_MIN)
    temperature = req.temperature if req.temperature is not None else 0.6

    LOG.info(f"🔄 STREAM [deepseek-r1-rlm]: '{text[:80]}...' (max_tokens={max_tokens}, temp={temperature})")

    def generate_rlm():
        try:
            for token in _rlm_chat_completion_stream(
                text, system, max_tokens, RLM_HTTP_TIMEOUT_SEC, temperature
            ):
                yield f"data: {json.dumps({'content': token, 'stop': False})}\n\n"
            yield f"data: {json.dumps({'content': '', 'stop': True, 'model': 'deepseek-r1'})}\n\n"
        except Exception as e:
            LOG.warning(f"RLM stream failed ({e}), falling back to Micro-LLM stream")
            # Fallback: stream from Micro-LLM (Qwen2.5-3B, CPU) when RLM is down
            try:
                fallback_tokens = caller_n
                fallback_temp = req.temperature if req.temperature is not None else 0.7
                for token in _chat_llm_completion_stream(
                    text, system, fallback_tokens, CHAT_LLM_HTTP_TIMEOUT_SEC, fallback_temp
                ):
                    yield f"data: {json.dumps({'content': token, 'stop': False})}\n\n"
                yield f"data: {json.dumps({'content': '', 'stop': True, 'model': 'qwen2.5-3b'})}\n\n"
            except Exception as e2:
                LOG.debug(f"Micro-LLM stream fallback unavailable: {e2}")
                yield f"data: {json.dumps({'error': str(e2), 'stop': True, 'model': 'qwen2.5-3b'})}\n\n"
        finally:
            LOG.info(f"✅ STREAM DONE")

    return StreamingResponse(generate_rlm(), media_type="text/event-stream")


# ---- startup ---------------------------------------------------------------

@app.on_event("startup")
def on_startup():
    rlm_up = _is_rlm_up()
    chat_up = _is_chat_llm_up()
    LOG.info(f"[ROUTER] Dual-model architecture (RLM + Micro-LLM fallback)")
    LOG.info(f"[RLM]  DeepSeek-R1  @ {RLM_URL} — {'UP' if rlm_up else 'DOWN'}")
    LOG.info(f"[MICRO] Qwen2.5-3B @ {CHAT_LLM_URL} — {'UP' if chat_up else 'DOWN'}")
    LOG.info(f"[ROUTER] Default tokens: {DEFAULT_N_PREDICT}, RLM timeout: {RLM_HTTP_TIMEOUT_SEC}s, Chat timeout: {CHAT_LLM_HTTP_TIMEOUT_SEC}s")
