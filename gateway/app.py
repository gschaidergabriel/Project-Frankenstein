"""
Frank API Gateway — Secure remote access proxy.

Authenticates requests via API key, rate-limits, and proxies
to internal Frank services (Core, Toolbox, WebD, Router).

Usage:
    uvicorn gateway.app:app --host 127.0.0.1 --port 8443
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import base64
import io

import httpx
import pytesseract
from PIL import Image as PILImage
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from gateway.auth import init_auth, verify_api_key

# ── Config ──────────────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent / "config.json"
try:
    from config.paths import AICORE_LOG as _GW_LOG_DIR
    LOG_FILE = _GW_LOG_DIR / "gateway.log"
except ImportError:
    LOG_FILE = Path("/tmp/frank/gateway.log")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
LOG = logging.getLogger("gateway")


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


_config = _load_config()
UPSTREAM = _config.get("upstream", {
    "core": "http://127.0.0.1:8088",
    "toolbox": "http://127.0.0.1:8096",
    "webd": "http://127.0.0.1:8093",
    "router": "http://127.0.0.1:8091",
    "desktopd": "http://127.0.0.1:8092",
})

# Init auth
init_auth(
    api_key_hash=_config.get("api_key_hash", ""),
    default_rpm=_config.get("rate_limit_per_minute", 60),
    chat_rpm=_config.get("chat_rate_limit_per_minute", 10),
)

try:
    from config.paths import TEMP_FILES as _GW_TF
    NOTIFICATION_DIR = _GW_TF["notifications_dir"]
except ImportError:
    NOTIFICATION_DIR = Path("/tmp/frank/notifications")

# ── HTTP Client ─────────────────────────────────────────────────────

_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0))

# ── FastAPI App ─────────────────────────────────────────────────────

app = FastAPI(title="Frank API Gateway", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Audit Logging ───────────────────────────────────────────────────

@app.middleware("http")
async def audit_log(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    elapsed = time.time() - start
    client = request.client.host if request.client else "?"
    LOG.info(f"{request.method} {request.url.path} [{response.status_code}] "
             f"{elapsed:.2f}s from={client}")
    return response


# ── Helper: Proxy POST to internal service ──────────────────────────

async def _proxy_post(service: str, path: str, body: dict = None) -> dict:
    base = UPSTREAM.get(service, "")
    if not base:
        raise HTTPException(502, f"Unknown service: {service}")
    url = f"{base}{path}"
    try:
        resp = await _client.post(url, json=body or {}, timeout=120.0)
        return resp.json()
    except httpx.TimeoutException:
        raise HTTPException(504, f"Upstream timeout: {service}{path}")
    except Exception as e:
        raise HTTPException(502, f"Upstream error: {e}")


async def _proxy_get(service: str, path: str) -> dict:
    base = UPSTREAM.get(service, "")
    if not base:
        raise HTTPException(502, f"Unknown service: {service}")
    url = f"{base}{path}"
    try:
        resp = await _client.get(url, timeout=30.0)
        return resp.json()
    except httpx.TimeoutException:
        raise HTTPException(504, f"Upstream timeout: {service}{path}")
    except Exception as e:
        raise HTTPException(502, f"Upstream error: {e}")


# ── Request/Response Models ─────────────────────────────────────────

class ChatRequest(BaseModel):
    text: str
    task: str = "chat.fast"
    max_tokens: int = 256

class CreateEventRequest(BaseModel):
    title: str
    start: str
    end: Optional[str] = None
    description: Optional[str] = ""
    location: Optional[str] = ""

class CreateTodoRequest(BaseModel):
    content: str
    due_date: Optional[str] = None
    priority: Optional[int] = 1

class CreateNoteRequest(BaseModel):
    title: str
    content: str

class SearchRequest(BaseModel):
    query: str
    limit: int = 5


# ── Endpoints ───────────────────────────────────────────────────────

# Health (no auth required)
@app.get("/health")
async def health():
    return {"ok": True, "service": "frank-gateway", "ts": datetime.now().isoformat()}


# ── Chat ────────────────────────────────────────────────────────────

@app.post("/chat", dependencies=[Depends(verify_api_key)])
async def chat(req: ChatRequest):
    """Chat with Frank."""
    result = await _proxy_post("core", "/chat", {
        "text": req.text,
        "task": req.task,
        "max_tokens": req.max_tokens,
    })
    return result


@app.post("/chat/voice", dependencies=[Depends(verify_api_key)])
async def chat_voice(audio: UploadFile = File(...)):
    """Voice chat: upload audio → STT → chat → text response."""
    # Read audio data
    audio_data = await audio.read()
    if len(audio_data) > 5 * 1024 * 1024:  # 5MB limit
        raise HTTPException(413, "Audio file too large (max 5MB)")

    # Send to Whisper for STT
    try:
        whisper_resp = await _client.post(
            "http://127.0.0.1:8103/inference",
            files={"file": (audio.filename or "audio.wav", audio_data, "audio/wav")},
            data={"response_format": "json"},
            timeout=60.0,
        )
        whisper_data = whisper_resp.json()
        transcript = whisper_data.get("text", "").strip()
    except Exception as e:
        raise HTTPException(502, f"Speech-to-text failed: {e}")

    if not transcript:
        return {"ok": False, "error": "empty_transcript", "text": ""}

    # Send transcript to chat
    result = await _proxy_post("core", "/chat", {
        "text": transcript,
        "task": "chat.fast",
        "max_tokens": 256,
    })
    result["transcript"] = transcript
    return result


# ── Chat Vision ────────────────────────────────────────────────────

@app.post("/chat/vision", dependencies=[Depends(verify_api_key)])
async def chat_vision(
    image: UploadFile = File(...),
    text: str = Form("Was siehst du auf diesem Bild?"),
):
    """Vision chat: upload image + question → Ollama LLaVA analysis."""
    image_data = await image.read()
    if len(image_data) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(413, "Image too large (max 10MB)")

    img_b64 = base64.b64encode(image_data).decode("utf-8")

    # OCR: extract text from image in background thread (non-blocking)
    import asyncio
    import functools

    def _do_ocr(img_bytes: bytes) -> str:
        try:
            pil_img = PILImage.open(io.BytesIO(img_bytes))
            # Try with common languages first
            return pytesseract.image_to_string(
                pil_img, lang="deu+eng+ara", timeout=15
            ).strip()
        except Exception:
            try:
                pil_img = PILImage.open(io.BytesIO(img_bytes))
                return pytesseract.image_to_string(pil_img, timeout=10).strip()
            except Exception:
                return ""

    loop = asyncio.get_event_loop()
    ocr_text = await loop.run_in_executor(
        None, functools.partial(_do_ocr, image_data)
    )

    prompt = text
    if ocr_text:
        prompt += f"\n\nDetected text in image (OCR):\n{ocr_text[:2000]}"

    # Try LLaVA first, fallback to Moondream
    for model in ("llava", "moondream"):
        try:
            resp = await _client.post(
                "http://127.0.0.1:11434/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "system": "You are Frank, a local AI assistant. Answer concisely.",
                    "images": [img_b64],
                    "stream": False,
                },
                timeout=120.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                raw_answer = data.get("response", "").strip()
                if raw_answer:
                    # Pass vision output through Core LLM for cleanup
                    # IMPORTANT: Avoid trigger words (desktop, bildschirm,
                    # screen, siehst du, was siehst) — Core API returns
                    # canned response if these appear in text!
                    safe_answer = (raw_answer
                        .replace("desktop", "Computer")
                        .replace("Desktop", "Computer")
                        .replace("screen", "Display")
                        .replace("Screen", "Display")
                        .replace("bildschirm", "Monitor")
                        .replace("Bildschirm", "Monitor")
                        .replace("siehst du", "erkennst du")
                        .replace("was siehst", "was erkennst"))
                    safe_question = (text
                        .replace("desktop", "Computer")
                        .replace("Desktop", "Computer")
                        .replace("screen", "Display")
                        .replace("Screen", "Display")
                        .replace("bildschirm", "Monitor")
                        .replace("Bildschirm", "Monitor")
                        .replace("siehst du", "erkennst du")
                        .replace("was siehst", "was erkennst"))
                    ocr_section = ""
                    if ocr_text:
                        ocr_section = f"\nVerifizierter Text (OCR): {ocr_text[:1500]}\n"

                    try:
                        refine_resp = await _client.post(
                            UPSTREAM["core"] + "/chat",
                            json={
                                "text": (
                                    f"An AI model analyzed a photo from a phone.\n"
                                    f"Question: {safe_question}\n"
                                    f"Raw analysis: {safe_answer}\n"
                                    f"{ocr_section}\n"
                                    f"Summarize the analysis briefly and answer the question. "
                                    f"The OCR text is verified and reliable — use it for translations. "
                                    f"Ignore obviously false or fabricated details from the vision analysis."
                                ),
                                "task": "chat.fast",
                                "max_tokens": 300,
                            },
                            timeout=30.0,
                        )
                        refined = refine_resp.json().get("text", raw_answer)
                    except Exception:
                        refined = raw_answer

                    return {
                        "ok": True,
                        "text": refined,
                        "model": model,
                        "question": text,
                    }
        except Exception:
            continue

    raise HTTPException(502, "Vision analysis failed — no model available")


# ── System ──────────────────────────────────────────────────────────

@app.get("/system/summary", dependencies=[Depends(verify_api_key)])
async def system_summary():
    """Get system status (CPU, RAM, Disk, Temp)."""
    return await _proxy_post("toolbox", "/sys/summary")


@app.get("/system/status", dependencies=[Depends(verify_api_key)])
async def system_status():
    """Get service health overview."""
    services = {}
    for name, base in UPSTREAM.items():
        try:
            resp = await _client.get(f"{base}/health", timeout=3.0)
            services[name] = resp.status_code == 200
        except Exception:
            services[name] = False
    return {"ok": True, "services": services, "ts": datetime.now().isoformat()}


# ── Calendar ────────────────────────────────────────────────────────

@app.get("/calendar/today", dependencies=[Depends(verify_api_key)])
async def calendar_today():
    return await _proxy_post("toolbox", "/calendar/today")


@app.get("/calendar/week", dependencies=[Depends(verify_api_key)])
async def calendar_week():
    return await _proxy_post("toolbox", "/calendar/week")


@app.get("/calendar/events", dependencies=[Depends(verify_api_key)])
async def calendar_events():
    return await _proxy_post("toolbox", "/calendar/events")


@app.post("/calendar/create", dependencies=[Depends(verify_api_key)])
async def calendar_create(req: CreateEventRequest):
    return await _proxy_post("toolbox", "/calendar/create", req.model_dump())


@app.delete("/calendar/{event_id}", dependencies=[Depends(verify_api_key)])
async def calendar_delete(event_id: str):
    return await _proxy_post("toolbox", "/calendar/delete", {"id": event_id})


# ── Email ───────────────────────────────────────────────────────────

@app.get("/email/unread", dependencies=[Depends(verify_api_key)])
async def email_unread():
    return await _proxy_post("toolbox", "/email/unread")


@app.get("/email/list", dependencies=[Depends(verify_api_key)])
async def email_list(limit: int = 20):
    return await _proxy_post("toolbox", "/email/list", {"limit": limit})


@app.get("/email/read/{email_id}", dependencies=[Depends(verify_api_key)])
async def email_read(email_id: str):
    return await _proxy_post("toolbox", "/email/read", {"id": email_id})


# ── Todos ───────────────────────────────────────────────────────────

@app.get("/todo/list", dependencies=[Depends(verify_api_key)])
async def todo_list():
    return await _proxy_post("toolbox", "/todo/list")


@app.post("/todo/create", dependencies=[Depends(verify_api_key)])
async def todo_create(req: CreateTodoRequest):
    return await _proxy_post("toolbox", "/todo/create", req.model_dump())


@app.post("/todo/complete/{todo_id}", dependencies=[Depends(verify_api_key)])
async def todo_complete(todo_id: int):
    return await _proxy_post("toolbox", "/todo/complete", {"id": todo_id})


@app.delete("/todo/{todo_id}", dependencies=[Depends(verify_api_key)])
async def todo_delete(todo_id: int):
    return await _proxy_post("toolbox", "/todo/delete", {"id": todo_id})


# ── Notes ───────────────────────────────────────────────────────────

@app.get("/notes/list", dependencies=[Depends(verify_api_key)])
async def notes_list():
    return await _proxy_post("toolbox", "/notes/list")


@app.post("/notes/create", dependencies=[Depends(verify_api_key)])
async def notes_create(req: CreateNoteRequest):
    return await _proxy_post("toolbox", "/notes/create", req.model_dump())


@app.get("/notes/search", dependencies=[Depends(verify_api_key)])
async def notes_search(q: str):
    return await _proxy_post("toolbox", "/notes/search", {"query": q})


@app.delete("/notes/{note_id}", dependencies=[Depends(verify_api_key)])
async def notes_delete(note_id: int):
    return await _proxy_post("toolbox", "/notes/delete", {"id": note_id})


# ── Contacts ────────────────────────────────────────────────────────

@app.get("/contacts/list", dependencies=[Depends(verify_api_key)])
async def contacts_list():
    return await _proxy_post("toolbox", "/contacts/list")


@app.get("/contacts/search", dependencies=[Depends(verify_api_key)])
async def contacts_search(q: str):
    return await _proxy_post("toolbox", "/contacts/search", {"query": q})


# ── Web Search ──────────────────────────────────────────────────────

@app.post("/search", dependencies=[Depends(verify_api_key)])
async def web_search(req: SearchRequest):
    return await _proxy_post("webd", "/search", req.model_dump())


# ── Notifications ───────────────────────────────────────────────────

@app.get("/notifications", dependencies=[Depends(verify_api_key)])
async def notifications():
    """Get recent notifications."""
    items = []
    if NOTIFICATION_DIR.exists():
        for f in sorted(NOTIFICATION_DIR.glob("*.json"), reverse=True)[:20]:
            try:
                items.append(json.loads(f.read_text()))
            except Exception:
                pass
    return {"ok": True, "notifications": items}


# ── CLI: Generate API Key ───────────────────────────────────────────

if __name__ == "__main__":
    import secrets
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "genkey":
        key = secrets.token_urlsafe(32)
        from gateway.auth import hash_api_key
        print(f"API Key:  {key}")
        print(f"Hash:     {hash_api_key(key)}")
        print(f"\nPut the hash in gateway/config.json as 'api_key_hash'")
        print(f"Put the key in your Android app settings")
    else:
        print("Usage: python -m gateway.app genkey")
