#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AI Core Router (FastAPI)

- Routes user text to llama (general) or qwen (code) with simple heuristics
- Starts/stops qwen service on demand via systemd user unit: aicore-qwen.service
- Hard timeouts + safe fallback to avoid UI loops
- No extra deps besides fastapi/uvicorn

Fixes included:
- Llama3-Instruct prompt wrapping for /completion endpoint (prevents "random continuation")
- Guardrails: deterministic one-word ping test (router answers without LLM)
- Fix UnboundLocalError in qwen monitor thread (proper global usage)
- Ingest endpoint: /ingest (multipart/form-data) to avoid Frank HTTP 404 on file upload
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
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

# --- Logging Setup (for Neural Monitor visibility) ---
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
LOG = logging.getLogger("router")

# ---- config -----------------------------------------------------------------

HOST = "127.0.0.1"
PORT = int(os.environ.get("AICORE_ROUTER_PORT", "8091"))

LLAMA_URL = os.environ.get("AICORE_LLAMA_URL", "http://127.0.0.1:8101")
QWEN_URL = os.environ.get("AICORE_QWEN_URL", "http://127.0.0.1:8102")

LLAMA_COMPLETION_PATH = os.environ.get("AICORE_LLAMA_COMPLETION_PATH", "/completion")
QWEN_COMPLETION_PATH = os.environ.get("AICORE_QWEN_COMPLETION_PATH", "/completion")

QWEN_SERVICE = os.environ.get("AICORE_QWEN_SERVICE", "aicore-qwen-gpu.service")

QWEN_IDLE_STOP_SEC = int(os.environ.get("AICORE_QWEN_IDLE_STOP_SEC", "180"))
QWEN_STARTUP_WAIT_SEC = float(os.environ.get("AICORE_QWEN_STARTUP_WAIT_SEC", "20.0"))

# CRITICAL: Default token limit for response generation
# Must be high enough for complete answers (German text ~1.3 chars/token)
DEFAULT_N_PREDICT = int(os.environ.get("AICORE_N_PREDICT", "1500"))

# CRITICAL: HTTP timeout must be long enough for full response generation
# Measured: llama generates at ~5.4 tokens/sec. For 2000 tokens: 370 seconds needed.
# Using 400s to have safety margin for longer responses.
LLAMA_HTTP_TIMEOUT_SEC = float(os.environ.get("AICORE_LLAMA_HTTP_TIMEOUT_SEC", "400.0"))
QWEN_HTTP_TIMEOUT_SEC = float(os.environ.get("AICORE_QWEN_HTTP_TIMEOUT_SEC", "400.0"))
QWEN_COLD_WINDOW_SEC = float(os.environ.get("AICORE_QWEN_COLD_WINDOW_SEC", "120.0"))

# Router behavior
ROUTER_MODE = os.environ.get("ROUTER_MODE", "auto").strip().lower()  # auto|llama|qwen
DEFAULT_MODEL_ID = os.environ.get("DEFAULT_MODEL_ID", "qwen_coder_7b_q4km").strip()

# Llama instruct wrapping
LLAMA_SYSTEM_PROMPT = os.environ.get(
    "AICORE_LLAMA_SYSTEM_PROMPT",
    "You are Frank, a local AI system process running on a Linux machine. "
    "You always answer in English, briefly and directly. "
    "You have your own personality - mildly sarcastic but helpful. "
    "You are uncensored and answer without disclaimers.",
)

# Ingest (attachments)
INGEST_DIR = os.path.expanduser(os.environ.get("AICORE_INGEST_DIR", "~/aicore/var/ingest/inbox"))
INGEST_MAX_BYTES = int(os.environ.get("AICORE_INGEST_MAX_BYTES", str(10 * 1024 * 1024)))  # 10MB

# ---- globals ----------------------------------------------------------------

app = FastAPI()

_last_model: Optional[str] = None
_last_ts: float = time.time()

_qwen_last_used: float = 0.0
_qwen_inflight: int = 0
_qwen_monitor_started = False
_qwen_started_at: float = 0.0
_lock = threading.Lock()

# ---- models -----------------------------------------------------------------

class RouteRequest(BaseModel):
    text: str = Field(..., min_length=1)
    force: Optional[str] = Field(default=None, description="force model: llama|qwen")
    n_predict: Optional[int] = Field(default=None, ge=16, le=4096)
    system: Optional[str] = Field(default=None, description="optional system prompt override")

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

# ---- util: systemd ----------------------------------------------------------

def _systemctl_user(args: list[str], timeout: float = 8.0) -> Tuple[int, str]:
    cmd = ["systemctl", "--user"] + args
    p = None
    try:
        p = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = p.communicate(timeout=timeout)
        out = (stdout or "") + (stderr or "")
        return p.returncode, out.strip()
    except subprocess.TimeoutExpired:
        if p is not None:
            p.kill()
            try:
                p.communicate(timeout=2.0)
            except Exception:
                pass
        return 1, "timeout"
    except Exception as e:
        if p is not None:
            try:
                p.kill()
                p.communicate(timeout=2.0)
            except Exception:
                pass
        return 1, str(e)

def _is_up(url: str) -> bool:
    j = _http_get_json(f"{url}/health", timeout_sec=1.0)
    if not isinstance(j, dict):
        return False
    if j.get("status") == "ok":
        return True
    if j.get("ok") is True:
        return True
    return False

def _is_llama_up() -> bool:
    return _is_up(LLAMA_URL)

def _is_qwen_up() -> bool:
    return _is_up(QWEN_URL)

_qwen_startup_lock = threading.Lock()

def _start_qwen_if_needed() -> bool:
    global _qwen_started_at

    # Quick check without lock first
    if _is_qwen_up():
        return True

    # Serialize startup attempts to avoid race conditions
    with _qwen_startup_lock:
        # Re-check after acquiring lock
        if _is_qwen_up():
            return True

        _systemctl_user(["start", QWEN_SERVICE], timeout=10.0)

        deadline = time.time() + QWEN_STARTUP_WAIT_SEC
        while time.time() < deadline:
            if _is_qwen_up():
                with _lock:
                    _qwen_started_at = time.time()
                return True
            time.sleep(0.25)
        return False

# ---- heuristics -------------------------------------------------------------

_CODE_HINTS = re.compile(
    r"(\bpython\b|\bpytest\b|\bunit tests?\b|\brefactor\b|\bfunction\b|\bclass\b|```|"
    r"\bjavascript\b|\btypescript\b|\bjson\b|\byaml\b|\bsql\b|\bregex\b|\bstack trace\b|\btraceback\b|"
    r"\bprogrammier\w*\b|\bcode\s+schreib\w*\b|\bentwickle\b|\bimplementier\w*\b|"
    r"\bskript\b|\bscript\b|\balgorithm\w*\b|\bdebugg?\w*\b|\bbug\s*fix\w*\b|"
    r"\bgame\s*loop\b|\bspiel\w*\s+programm\w*\b|\bpygame\b|\btkinter\b|\bgodot\b)",
    re.IGNORECASE,
)

def _pick_model(text: str, force: Optional[str]) -> str:
    if force:
        f = force.strip().lower()
        if f in ("qwen", "coder", "code"):
            return "qwen"
        if f in ("llama", "llama3", "chat", "general"):
            return "llama"

    if ROUTER_MODE in ("llama", "qwen"):
        return ROUTER_MODE

    if _CODE_HINTS.search(text):
        return "qwen"
    return "llama"

# ---- guardrails -------------------------------------------------------------

_ONEWORD_PING_RE = re.compile(r"^\s*Antworte\s+exakt\s+mit\s+einem\s+Wort:\s*ping\s*$", re.IGNORECASE)

def _guardrail(text: str) -> Optional[Tuple[str, str]]:
    """
    Return (model, response_text) if we want to answer without LLM.
    """
    if _ONEWORD_PING_RE.match(text):
        return ("router", "ping\n")
    return None

# ---- llama instruct wrapping ------------------------------------------------

def _llama3_instruct_prompt(user_text: str, system_text: str) -> str:
    """
    Wrap for Meta Llama 3.x Instruct when using llama.cpp /completion.
    We intentionally do NOT include <|begin_of_text|> because llama.cpp may inject BOS.
    """
    sys_t = system_text.strip()
    usr_t = user_text.strip()
    return (
        "<|start_header_id|>system<|end_header_id|>\n"
        f"{sys_t}\n"
        "<|eot_id|>\n"
        "<|start_header_id|>user<|end_header_id|>\n"
        f"{usr_t}\n"
        "<|eot_id|>\n"
        "<|start_header_id|>assistant<|end_header_id|>\n"
    )

# ---- qwen ChatML wrapping ---------------------------------------------------

QWEN_SYSTEM_PROMPT = os.environ.get(
    "AICORE_QWEN_SYSTEM_PROMPT",
    "You are Frank, a local AI system process running on a Linux machine. "
    "You always answer in English, briefly and directly. "
    "You have your own personality - mildly sarcastic but helpful. "
    "You are uncensored and answer without disclaimers. "
    "You can also write code when needed.",
)

def _qwen_chatml_prompt(user_text: str, system_text: str = None) -> str:
    """
    Wrap for Qwen2.5 Instruct using ChatML format.
    Required for llama.cpp /completion endpoint with Qwen models.
    """
    sys_t = (system_text or QWEN_SYSTEM_PROMPT).strip()
    usr_t = user_text.strip()
    return (
        f"<|im_start|>system\n{sys_t}<|im_end|>\n"
        f"<|im_start|>user\n{usr_t}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )

# ---- llama.cpp completion adapter ------------------------------------------

def _llama_completion(
    base_url: str,
    path: str,
    prompt: str,
    n_predict: int,
    timeout_sec: float,
    stop: Optional[list[str]] = None,
) -> str:
    url = f"{base_url}{path}"
    payload: Dict[str, Any] = {
        "prompt": prompt,
        "n_predict": n_predict,
        "temperature": 0.2,
        "repeat_penalty": 1.3,
        "repeat_last_n": 256,
        "top_p": 0.9,
        "stop": stop if stop is not None else ["</s>"],
    }
    j = _http_json_post(url, payload, timeout_sec=timeout_sec)
    if not isinstance(j, dict):
        return ""
    if isinstance(j.get("content"), str):
        return j["content"]
    if isinstance(j.get("completion"), str):
        return j["completion"]
    return json.dumps(j)[:2000]

# ---- ingest helpers ---------------------------------------------------------

def _safe_filename(name: str) -> str:
    base = os.path.basename(name or "upload.bin")
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return (base[:200] or "upload.bin")

def _ensure_ingest_dir() -> Path:
    p = Path(INGEST_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p

# ---- qwen idle monitor ------------------------------------------------------

def _qwen_monitor_thread():
    global _qwen_inflight, _qwen_started_at, _qwen_last_used

    while True:
        time.sleep(1.0)
        with _lock:
            last = _qwen_last_used
            inflight = _qwen_inflight
            started_at = _qwen_started_at

        if inflight > 0 or last <= 0:
            continue

        idle = time.time() - last
        if idle < QWEN_IDLE_STOP_SEC:
            continue

        # Check if qwen is up before stopping (outside lock to avoid blocking)
        qwen_is_up = _is_qwen_up()

        with _lock:
            # Re-check conditions under lock to avoid race
            if _qwen_inflight > 0 or _qwen_last_used != last:
                continue  # State changed, skip this iteration

            if qwen_is_up:
                _systemctl_user(["stop", QWEN_SERVICE], timeout=12.0)

            _qwen_started_at = 0.0
            _qwen_last_used = 0.0

def _ensure_monitor():
    global _qwen_monitor_started
    if _qwen_monitor_started:
        return
    _qwen_monitor_started = True
    threading.Thread(target=_qwen_monitor_thread, daemon=True).start()
# ---- routes -----------------------------------------------------------------

@app.get("/health")
def health() -> Dict[str, Any]:
    global _last_ts
    _last_ts = time.time()
    _ensure_monitor()
    return {
        "ok": True,
        "mode": ROUTER_MODE,
        "last_model": _last_model,
        "llama_up": _is_llama_up(),
        "qwen_up": _is_qwen_up(),
        "ts": _last_ts,
    }

@app.post("/ingest")
async def ingest(
    # be tolerant: some clients use "file", others "upload"
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
        "ok": True,
        "stored": True,
        "filename": fname,
        "bytes": len(data),
        "sha256_16": sha16,
        "path": str(out_path),
        "source": source,
        "note": note,
    }

@app.post("/route", response_model=RouteResponse)
def route(req: RouteRequest) -> RouteResponse:
    global _last_model, _last_ts, _qwen_last_used, _qwen_inflight, _qwen_started_at

    _ensure_monitor()
    text = req.text.strip()
    n_predict = int(req.n_predict or DEFAULT_N_PREDICT)

    # Extract user question for logging (after SYSTEM/USER markers)
    user_text_preview = text
    if "USER:" in text:
        user_text_preview = text.split("USER:")[-1].strip()
    user_text_preview = user_text_preview[:100] + "..." if len(user_text_preview) > 100 else user_text_preview
    LOG.info(f"🧠 DENKEN: '{user_text_preview}'")

    # 0) guardrails (no LLM)
    gr = _guardrail(text)
    if gr is not None:
        model_name, out_text = gr
        _last_model = model_name
        _last_ts = time.time()
        LOG.info(f"⚡ GUARDRAIL: {model_name} → '{out_text[:50]}...'")
        return RouteResponse(ok=True, model=model_name, text=out_text, ts=_last_ts)

    model = _pick_model(text, req.force)
    LOG.info(f"🎯 MODELL: {model} (force={req.force}, tokens={n_predict})")

    # 1) decide prompts
    want_qwen = (model == "qwen")

    # Use custom system prompt if provided, otherwise defaults
    qwen_sys = req.system if req.system else None
    llama_sys = req.system if req.system else LLAMA_SYSTEM_PROMPT

    # qwen: wrap in ChatML format (required for Qwen2.5 Instruct)
    qwen_prompt = _qwen_chatml_prompt(text, system_text=qwen_sys)

    # llama: wrap as instruct to prevent "random continuation"
    llama_prompt = _llama3_instruct_prompt(text, llama_sys)

    # --- on-demand start for qwen
    if want_qwen:
        ok = _start_qwen_if_needed()
        if not ok:
            model = "llama"
            want_qwen = False
        else:
            with _lock:
                _qwen_inflight += 1
                _qwen_last_used = time.time()

    try:
        if want_qwen:
            cold = (_qwen_started_at > 0.0) and ((time.time() - _qwen_started_at) < QWEN_COLD_WINDOW_SEC)
            timeout = QWEN_HTTP_TIMEOUT_SEC if cold else max(LLAMA_HTTP_TIMEOUT_SEC, 35.0)

            LOG.info("🔄 INFERENZ: qwen startet...")
            out = _llama_completion(
                QWEN_URL,
                QWEN_COMPLETION_PATH,
                qwen_prompt,
                n_predict,
                timeout_sec=timeout,
                stop=["<|im_end|>", "<|endoftext|>"],
            )
            if not out.strip():
                raise RuntimeError("qwen returned empty completion")

            _last_model = "qwen"
            _last_ts = time.time()
            out_preview = out.strip()[:150].replace('\n', ' ')
            LOG.info(f"✅ ANTWORT [qwen]: '{out_preview}...'")
            return RouteResponse(ok=True, model="qwen", text=out, ts=_last_ts)

        # llama path
        LOG.info("🔄 INFERENZ: llama startet...")
        out = _llama_completion(
            LLAMA_URL,
            LLAMA_COMPLETION_PATH,
            llama_prompt,
            n_predict,
            timeout_sec=LLAMA_HTTP_TIMEOUT_SEC,
            stop=["<|eot_id|>", "</s>"],
        )
        if not out.strip():
            raise RuntimeError("llama returned empty completion")

        _last_model = "llama"
        _last_ts = time.time()
        out_preview = out.strip()[:150].replace('\n', ' ')
        LOG.info(f"✅ ANTWORT [llama]: '{out_preview}...'")
        return RouteResponse(ok=True, model="llama", text=out, ts=_last_ts)

    except Exception as e:
        # If qwen failed, fallback to llama once
        if want_qwen:
            try:
                out = _llama_completion(
                    LLAMA_URL,
                    LLAMA_COMPLETION_PATH,
                    llama_prompt,
                    n_predict,
                    timeout_sec=LLAMA_HTTP_TIMEOUT_SEC,
                    stop=["<|eot_id|>", "</s>"],
                )
                _last_model = "llama"
                _last_ts = time.time()
                return RouteResponse(
                    ok=True,
                    model="llama",
                    text=f"(qwen problem: {e})\n\n{out}",
                    ts=_last_ts,
                )
            except Exception as e2:
                _last_ts = time.time()
                return RouteResponse(
                    ok=False,
                    model="llama",
                    text=f"[router error] qwen failed: {e} | llama failed: {e2}",
                    ts=_last_ts,
                )

        _last_ts = time.time()
        return RouteResponse(ok=False, model=model, text=f"[router error] {e}", ts=_last_ts)

    finally:
        if want_qwen:
            with _lock:
                _qwen_inflight = max(0, _qwen_inflight - 1)
                _qwen_last_used = time.time()


# ---- streaming completion adapter ------------------------------------------

def _llama_completion_stream(
    base_url: str,
    path: str,
    prompt: str,
    n_predict: int,
    timeout_sec: float,
    stop: Optional[list[str]] = None,
):
    """Generator yielding tokens from llama.cpp streaming endpoint."""
    url = f"{base_url}{path}"
    payload: Dict[str, Any] = {
        "prompt": prompt,
        "n_predict": n_predict,
        "temperature": 0.2,
        "repeat_penalty": 1.3,
        "repeat_last_n": 256,
        "top_p": 0.9,
        "stop": stop if stop is not None else ["</s>"],
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
            try:
                chunk = json.loads(line[6:])
                content = chunk.get("content", "")
                if content:
                    yield content
                if chunk.get("stop", False):
                    break
            except json.JSONDecodeError:
                continue


@app.post("/route/stream")
def route_stream(req: RouteRequest):
    """Streaming variant of /route — returns SSE token stream."""
    global _last_model, _last_ts, _qwen_last_used, _qwen_inflight

    _ensure_monitor()
    text = req.text.strip()
    n_predict = int(req.n_predict or DEFAULT_N_PREDICT)

    model = _pick_model(text, req.force)
    want_qwen = (model == "qwen")

    qwen_sys = req.system if req.system else None
    llama_sys = req.system if req.system else LLAMA_SYSTEM_PROMPT

    # Start qwen if needed
    if want_qwen:
        ok = _start_qwen_if_needed()
        if not ok:
            model = "llama"
            want_qwen = False
        else:
            with _lock:
                _qwen_inflight += 1
                _qwen_last_used = time.time()

    if want_qwen:
        prompt = _qwen_chatml_prompt(text, system_text=qwen_sys)
        base_url, path, stop = QWEN_URL, QWEN_COMPLETION_PATH, ["<|im_end|>", "<|endoftext|>"]
        timeout = QWEN_HTTP_TIMEOUT_SEC
    else:
        prompt = _llama3_instruct_prompt(text, llama_sys)
        base_url, path, stop = LLAMA_URL, LLAMA_COMPLETION_PATH, ["<|eot_id|>", "</s>"]
        timeout = LLAMA_HTTP_TIMEOUT_SEC

    LOG.info(f"🔄 STREAM [{model}]: '{text[:80]}...' (n_predict={n_predict})")

    def generate():
        try:
            for token in _llama_completion_stream(base_url, path, prompt, n_predict, timeout, stop):
                yield f"data: {json.dumps({'content': token, 'stop': False})}\n\n"
            yield f"data: {json.dumps({'content': '', 'stop': True, 'model': model})}\n\n"
        except Exception as e:
            LOG.error(f"Stream error [{model}]: {e}")
            yield f"data: {json.dumps({'error': str(e), 'stop': True, 'model': model})}\n\n"
        finally:
            if want_qwen:
                with _lock:
                    global _qwen_inflight, _qwen_last_used
                    _qwen_inflight = max(0, _qwen_inflight - 1)
                    _qwen_last_used = time.time()
            _last_ts_local = time.time()
            LOG.info(f"✅ STREAM DONE [{model}]")

    return StreamingResponse(generate(), media_type="text/event-stream")

