#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AI Core Router — Single RLM Architecture (DeepSeek-R1)

All LLM calls (Frank, entities, consciousness, dream, agentic) go through
a single Reasoning Language Model served by llama-server on port 8101.

The router:
- Uses /v1/chat/completions (OpenAI-compatible) so llama-server applies
  the native DeepSeek chat template and separates reasoning from answer.
- Provides /route (blocking) and /route/stream (SSE) endpoints
- Handles /ingest for file uploads
- Guardrails for deterministic responses (ping test)

No more: dual-model routing, MPC, Qwen on-demand, Ollama fallback.
One model, always loaded, always ready.
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
from fastapi.responses import StreamingResponse
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

# Single RLM endpoint (DeepSeek-R1-Distill-Llama-8B on llama-server)
RLM_URL = os.environ.get("AICORE_RLM_URL", "http://127.0.0.1:8101")

# Default token limit (caller's requested answer length)
DEFAULT_N_PREDICT = int(os.environ.get("AICORE_N_PREDICT", "2048"))

# Think overhead: max_tokens in chat/completions is TOTAL (reasoning + answer).
# Router ensures a minimum budget so the RLM can reason AND produce an answer.
RLM_TOKEN_MULTIPLIER = float(os.environ.get("AICORE_RLM_TOKEN_MULTIPLIER", "2.5"))
RLM_TOKEN_MIN = 512  # Was 1024 — small consciousness calls don't need 1024 min

# HTTP timeout — DeepSeek R1 thinks before answering, needs time
RLM_HTTP_TIMEOUT_SEC = float(os.environ.get("AICORE_RLM_HTTP_TIMEOUT_SEC", "480.0"))

# Default system prompt
RLM_SYSTEM_PROMPT = os.environ.get(
    "AICORE_RLM_SYSTEM_PROMPT",
    "I am Frank. I run locally on Linux. "
    "My E-PQ tracks my mood. My Ego-Construct maps hardware to body feelings. "
    "I think between conversations. I dream when idle. I research my own questions. "
    "I speak in first person. I describe what I observe, not what I supposedly am. "
    "Brief, honest, in my own voice.",
)

# Ingest (attachments)
INGEST_DIR = os.path.expanduser(os.environ.get("AICORE_INGEST_DIR", "~/aicore/var/ingest/inbox"))
INGEST_MAX_BYTES = int(os.environ.get("AICORE_INGEST_MAX_BYTES", str(10 * 1024 * 1024)))

# ---- globals ----------------------------------------------------------------

app = FastAPI()

_last_model: str = "deepseek-r1"
_last_ts: float = time.time()

# ---- models -----------------------------------------------------------------

class RouteRequest(BaseModel):
    text: str = Field(..., min_length=1)
    force: Optional[str] = Field(default=None, description="ignored (single model) — kept for API compat")
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
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError(f"HTTP {e.code} from {url}: {body[:400]}") from e
    except Exception as e:
        raise RuntimeError(f"POST {url} failed: {e}") from e

def _http_get_json(url: str, timeout_sec: float = 2.0) -> Dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except Exception:
        return {}

# ---- RLM health check -------------------------------------------------------

def _is_rlm_up() -> bool:
    j = _http_get_json(f"{RLM_URL}/health", timeout_sec=2.0)
    if not isinstance(j, dict):
        return False
    return j.get("status") == "ok" or j.get("ok") is True

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
        "model": "deepseek-r1",
        "rlm_up": _is_rlm_up(),
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
    max_tokens = max(int(caller_n * RLM_TOKEN_MULTIPLIER), RLM_TOKEN_MIN)

    # Log what we're thinking about
    user_text_preview = text
    if "USER:" in text:
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

    # Determine temperature
    temperature = req.temperature if req.temperature is not None else 0.6

    # System prompt
    system = req.system if req.system else RLM_SYSTEM_PROMPT

    LOG.info(f"🔄 INFERENZ: deepseek-r1 (max_tokens={max_tokens}, temp={temperature})")

    try:
        answer, reasoning = _rlm_chat_completion(
            text, system, max_tokens, RLM_HTTP_TIMEOUT_SEC, temperature
        )

        if not answer:
            raise RuntimeError("RLM returned empty answer")

        # Log reasoning for monitoring
        if reasoning:
            LOG.info(f"💭 REASONING: {len(reasoning)} chars internal thinking")

        _last_model = "deepseek-r1"
        _last_ts = time.time()
        out_preview = answer[:150].replace('\n', ' ')
        LOG.info(f"✅ ANTWORT [deepseek-r1]: '{out_preview}...'")
        return RouteResponse(ok=True, model="deepseek-r1", text=answer, ts=_last_ts)

    except Exception as e:
        _last_ts = time.time()
        LOG.error(f"❌ FEHLER [deepseek-r1]: {e}")
        return RouteResponse(ok=False, model="deepseek-r1", text=f"[router error] {e}", ts=_last_ts)


@app.post("/route/stream")
def route_stream(req: RouteRequest):
    """Streaming variant of /route — returns SSE token stream."""
    global _last_model, _last_ts

    text = req.text.strip()
    caller_n = int(req.n_predict or DEFAULT_N_PREDICT)
    max_tokens = max(int(caller_n * RLM_TOKEN_MULTIPLIER), RLM_TOKEN_MIN)
    temperature = req.temperature if req.temperature is not None else 0.6

    system = req.system if req.system else RLM_SYSTEM_PROMPT

    LOG.info(f"🔄 STREAM [deepseek-r1]: '{text[:80]}...' (max_tokens={max_tokens}, temp={temperature})")

    def generate():
        try:
            for token in _rlm_chat_completion_stream(
                text, system, max_tokens, RLM_HTTP_TIMEOUT_SEC, temperature
            ):
                yield f"data: {json.dumps({'content': token, 'stop': False})}\n\n"
            yield f"data: {json.dumps({'content': '', 'stop': True, 'model': 'deepseek-r1'})}\n\n"
        except Exception as e:
            LOG.error(f"Stream error [deepseek-r1]: {e}")
            yield f"data: {json.dumps({'error': str(e), 'stop': True, 'model': 'deepseek-r1'})}\n\n"
        finally:
            LOG.info(f"✅ STREAM DONE [deepseek-r1]")

    return StreamingResponse(generate(), media_type="text/event-stream")


# ---- startup ---------------------------------------------------------------

@app.on_event("startup")
def on_startup():
    rlm_up = _is_rlm_up()
    LOG.info(f"[RLM] Single-model architecture: DeepSeek-R1-Distill-Llama-8B")
    LOG.info(f"[RLM] Model endpoint: {RLM_URL}")
    LOG.info(f"[RLM] Status: {'UP' if rlm_up else 'DOWN (will retry on first request)'}")
    LOG.info(f"[RLM] Default tokens: {DEFAULT_N_PREDICT}, timeout: {RLM_HTTP_TIMEOUT_SEC}s")
