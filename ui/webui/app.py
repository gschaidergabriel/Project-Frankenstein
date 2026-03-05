#!/usr/bin/env python3
"""Frank Web UI — Cyberpunk dashboard for Project Frankenstein.

FastAPI server serving static frontend + WebSocket live feed +
REST proxy endpoints to Frank's microservice mesh.
"""

import asyncio
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

import httpx
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")
LOG = logging.getLogger("frank_webui")

# ── Config ──────────────────────────────────────────────────
PORT = 8099
CORE_URL = "http://127.0.0.1:8088"
ROUTER_URL = "http://127.0.0.1:8091"
TOOLBOX_URL = "http://127.0.0.1:8096"
AURA_URL = "http://127.0.0.1:8098"
QUANTUM_URL = "http://127.0.0.1:8097"
WHISPER_URL = "http://127.0.0.1:8103"
LLM_RLM_URL = "http://127.0.0.1:8101"     # DeepSeek-R1 (GPU, reasoning/idle)
LLM_CHAT_URL = "http://127.0.0.1:8101"    # DeepSeek-R1 (single RLM)
LLM_MICRO_URL = "http://127.0.0.1:8105"   # Qwen-3B (CPU, background)

from config.paths import DB_DIR, TEMP_FILES
CHAT_DB = DB_DIR / "chat_memory.db"
NOTIF_DIR = TEMP_FILES["notifications_dir"]

STATIC_DIR = Path(__file__).parent / "static"

WEBUI_SESSION_ID = "webui"

# ── App ─────────────────────────────────────────────────────
app = FastAPI(title="Frank Web UI", docs_url=None, redoc_url=None)

# Connected WebSocket clients
_ws_clients: Set[WebSocket] = set()


# ── Chat DB Helper ──────────────────────────────────────────

def _store_chat_message(sender: str, text: str, is_user: bool):
    """Store a chat message in the shared chat_memory.db."""
    try:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(CHAT_DB), timeout=5)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS messages ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  session_id TEXT NOT NULL,"
            "  role TEXT NOT NULL,"
            "  sender TEXT NOT NULL,"
            "  text TEXT NOT NULL,"
            "  is_user INTEGER NOT NULL DEFAULT 0,"
            "  is_system INTEGER NOT NULL DEFAULT 0,"
            "  timestamp REAL NOT NULL,"
            "  created_at TEXT NOT NULL"
            ")"
        )
        now = time.time()
        conn.execute(
            "INSERT INTO messages (session_id, role, sender, text, is_user, is_system, timestamp, created_at) "
            "VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
            (
                WEBUI_SESSION_ID,
                "user" if is_user else "frank",
                sender,
                text,
                1 if is_user else 0,
                now,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        LOG.warning("Failed to store chat message: %s", e)


# ── Static Files ────────────────────────────────────────────
@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── REST Endpoints ──────────────────────────────────────────

@app.get("/api/health")
async def health():
    """Check health of all services."""
    services = {
        "core": CORE_URL,
        "router": ROUTER_URL,
        "toolbox": TOOLBOX_URL,
        "aura": AURA_URL,
        "quantum": QUANTUM_URL,
        "whisper": WHISPER_URL,
    }
    result = {}
    async with httpx.AsyncClient(timeout=2.0) as client:
        for name, url in services.items():
            try:
                r = await client.get(f"{url}/health")
                result[name] = r.status_code == 200
            except Exception:
                result[name] = False

        # LLM: any model being up = ok (GPU primary, CPU micro-LLM fallback)
        llm_up = False
        for url in (LLM_RLM_URL, LLM_CHAT_URL, LLM_MICRO_URL):
            try:
                r = await client.get(f"{url}/health")
                if r.status_code == 200:
                    llm_up = True
                    break
            except Exception:
                pass
        result["llm"] = llm_up
    return result


@app.get("/api/chat/history")
async def chat_history(limit: int = 50):
    """Get recent chat messages from SQLite."""
    try:
        conn = sqlite3.connect(str(CHAT_DB), timeout=3)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT sender, text, is_user, timestamp, session_id "
            "FROM messages ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        messages = [dict(r) for r in reversed(rows)]
        return messages
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/chat")
async def chat_send(body: Dict[str, Any]):
    """Send chat message through Core (gets Frank's personality + context)."""
    text = body.get("text", "")
    if not text.strip():
        return JSONResponse({"error": "empty message"}, status_code=400)

    # Store user message
    _store_chat_message("Du", text, is_user=True)

    # Send to Core /chat (same path as overlay — gets enrichment + feedback loop)
    core_payload = {
        "text": text,
        "max_tokens": body.get("max_tokens", 512),
        "timeout_s": 120,
        "task": "chat.fast",
        "session_id": WEBUI_SESSION_ID,
    }

    response_text = ""
    try:
        async with httpx.AsyncClient(timeout=130.0) as client:
            r = await client.post(f"{CORE_URL}/chat", json=core_payload)
            data = r.json()
            if data.get("ok"):
                response_text = data.get("text", "")
            else:
                response_text = data.get("error", "Error: no response from Core")
    except Exception as e:
        LOG.warning("Core chat failed: %s", e)
        response_text = f"[Error: {e}]"

    # Store frank response
    if response_text:
        _store_chat_message("Frank", response_text, is_user=False)

    await _ws_broadcast({"type": "chat_done", "text": response_text})
    return {"ok": True, "text": response_text}


@app.get("/api/aura/grid")
async def aura_grid():
    """Proxy AURA grid data (filtered to renderer-needed fields only)."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{AURA_URL}/grid")
            data = r.json()
            return {
                "generation": data.get("generation"),
                "grid_b64": data.get("grid_b64"),
                "quantum_colors_b64": data.get("quantum_colors_b64"),
                "mood": data.get("mood"),
                "coherence": data.get("coherence"),
            }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@app.get("/api/aura/introspect")
async def aura_introspect():
    """Proxy AURA introspect."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{AURA_URL}/introspect/json")
            return r.json()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@app.get("/api/notifications")
async def get_notifications(limit: int = 50):
    """Read recent notification files."""
    entries = []
    try:
        if NOTIF_DIR.exists():
            files = sorted(NOTIF_DIR.glob("*.json"), key=os.path.getmtime)
            for f in files[-limit:]:
                try:
                    data = json.loads(f.read_text())
                    entries.append(data)
                except Exception:
                    continue
    except Exception as e:
        LOG.warning("Notification read error: %s", e)
    return entries


@app.get("/api/system")
async def system_status():
    """Get system metrics."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.post(f"{TOOLBOX_URL}/sys/summary", json={})
            return r.json()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@app.get("/api/gpu")
async def gpu_status():
    """Read GPU metrics (AMD sysfs, NVIDIA nvidia-smi, or none)."""
    result = {}
    try:
        import glob
        import subprocess

        # Try AMD sysfs first
        amd_found = False
        for path in glob.glob("/sys/class/drm/card*/device/gpu_busy_percent"):
            result["gpu_pct"] = int(Path(path).read_text().strip())
            amd_found = True
            break
        for path in glob.glob("/sys/class/hwmon/*/name"):
            if Path(path).read_text().strip() == "amdgpu":
                hwmon = Path(path).parent
                temp_file = hwmon / "temp1_input"
                if temp_file.exists():
                    result["gpu_temp"] = int(temp_file.read_text().strip()) // 1000
                amd_found = True
                break

        # Fallback: NVIDIA via nvidia-smi
        if not amd_found:
            try:
                r = subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=3,
                )
                if r.returncode == 0 and r.stdout.strip():
                    parts = r.stdout.strip().split(",")
                    if len(parts) >= 2:
                        result["gpu_pct"] = int(parts[0].strip())
                        result["gpu_temp"] = int(parts[1].strip())
            except FileNotFoundError:
                pass  # No nvidia-smi = no NVIDIA GPU
            except Exception:
                pass
    except Exception as e:
        LOG.debug("GPU read error: %s", e)
    return result


@app.get("/api/quantum")
async def quantum_status():
    """Get quantum reflector status."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{QUANTUM_URL}/status")
            return r.json()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


# ── WebSocket ───────────────────────────────────────────────

@app.websocket("/ws/live")
async def ws_live(ws: WebSocket):
    await ws.accept()
    _ws_clients.add(ws)
    LOG.info("WebSocket client connected (%d total)", len(_ws_clients))
    try:
        while True:
            # Keep alive — also receive chat messages from client
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "chat":
                    # Handle chat in background so WS stays alive
                    asyncio.create_task(_handle_ws_chat(msg.get("text", "")))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(ws)
        LOG.info("WebSocket client disconnected (%d remain)", len(_ws_clients))


async def _handle_ws_chat(text: str):
    """Process chat message through Core and broadcast response."""
    if not text.strip():
        return

    # Store user message
    _store_chat_message("Du", text, is_user=True)

    # Send to Core /chat (gets Frank's personality + context enrichment)
    core_payload = {
        "text": text,
        "max_tokens": 512,
        "timeout_s": 120,
        "task": "chat.fast",
        "session_id": WEBUI_SESSION_ID,
    }

    try:
        async with httpx.AsyncClient(timeout=130.0) as client:
            r = await client.post(f"{CORE_URL}/chat", json=core_payload)
            data = r.json()
            if data.get("ok"):
                response_text = data.get("text", "")
            else:
                response_text = f"Error: {data.get('error', 'unknown')}"
    except Exception as e:
        LOG.warning("WS chat via Core failed: %s", e)
        response_text = f"[Error: could not reach Frank — {e}]"

    # Store frank response
    if response_text:
        _store_chat_message("Frank", response_text, is_user=False)

    await _ws_broadcast({
        "type": "chat_done",
        "text": response_text,
    })


async def _ws_broadcast(msg: dict):
    """Send message to all connected WebSocket clients."""
    global _ws_clients
    if not _ws_clients:
        return
    data = json.dumps(msg)
    dead = set()
    for ws in _ws_clients:
        try:
            await ws.send_text(data)
        except Exception:
            dead.add(ws)
    _ws_clients -= dead


# ── Background Tasks ────────────────────────────────────────

_notification_cache: Dict[str, float] = {}


async def _notification_poller():
    """Poll notification directory and push new ones."""
    global _notification_cache
    LOG_CATEGORIES = {
        "consciousness", "dream", "entity",
        "therapist", "mirror", "atlas", "muse",
    }
    while True:
        try:
            if NOTIF_DIR.exists() and _ws_clients:
                for f in NOTIF_DIR.glob("*.json"):
                    mtime = f.stat().st_mtime
                    fname = f.name
                    if fname in _notification_cache and _notification_cache[fname] >= mtime:
                        continue
                    _notification_cache[fname] = mtime
                    try:
                        data = json.loads(f.read_text())
                        cat = data.get("category", "")
                        if cat in LOG_CATEGORIES:
                            await _ws_broadcast({
                                "type": "notification",
                                "category": cat,
                                "title": data.get("title", ""),
                                "text": data.get("body", ""),
                                "sender": data.get("sender", ""),
                                "ts": data.get("timestamp", ""),
                            })
                    except Exception:
                        continue
        except Exception:
            pass
        await asyncio.sleep(5)


async def _status_poller():
    """Poll service health and system metrics."""
    services = {
        "core": CORE_URL,
        "tools": TOOLBOX_URL,
        "aura": AURA_URL,
    }
    async with httpx.AsyncClient(timeout=2.0) as client:
        while True:
            if _ws_clients:
                status: Dict[str, Any] = {"type": "status"}
                for name, url in services.items():
                    try:
                        r = await client.get(f"{url}/health")
                        status[name] = r.status_code == 200
                    except Exception:
                        status[name] = False

                # LLM: any model up = ok (GPU primary, CPU micro-LLM fallback)
                llm_up = False
                for url in (LLM_RLM_URL, LLM_CHAT_URL, LLM_MICRO_URL):
                    try:
                        r = await client.get(f"{url}/health")
                        if r.status_code == 200:
                            llm_up = True
                            break
                    except Exception:
                        pass
                status["llm"] = llm_up

                # System metrics from toolbox
                try:
                    r = await client.post(f"{TOOLBOX_URL}/sys/summary", json={})
                    if r.status_code == 200:
                        d = r.json()
                        # CPU temp: k10temp (AMD) or coretemp (Intel)
                        temps = d.get("temps", {})
                        sensors = temps.get("sensors", [])
                        cpu_temp = 0
                        for s in sensors:
                            if s.get("chip") in ("k10temp", "coretemp"):
                                cpu_temp = int(s.get("temp_c", 0))
                                break
                        if not cpu_temp:
                            cpu_temp = int(temps.get("max_c", 0))
                        status["cpu_temp"] = cpu_temp

                        # RAM
                        mem = d.get("mem", {}).get("mem_kb", {})
                        total = mem.get("total", 1)
                        used = mem.get("used", 0)
                        status["ram_pct"] = int((used / max(total, 1)) * 100)

                        # CPU: use cores from toolbox data
                        cpu = d.get("cpu", {})
                        cores = cpu.get("cores", 16)
                        status["cpu_pct"] = int(float(cpu.get("load_1m", 0)) * 100 / max(1, cores))
                except Exception:
                    pass

                await _ws_broadcast(status)
            await asyncio.sleep(10)


_chat_sync_last_id: int = 0


def _get_max_msg_id() -> int:
    """Get highest message ID in chat_memory.db."""
    try:
        conn = sqlite3.connect(str(CHAT_DB), timeout=2)
        row = conn.execute("SELECT MAX(id) FROM messages").fetchone()
        conn.close()
        return row[0] or 0
    except Exception:
        return 0


async def _chat_sync_poller():
    """Poll DB for new messages from overlay and push to WebUI clients."""
    global _chat_sync_last_id
    _chat_sync_last_id = _get_max_msg_id()

    while True:
        try:
            if _ws_clients:
                conn = sqlite3.connect(str(CHAT_DB), timeout=2)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT id, sender, text, is_user FROM messages "
                    "WHERE id > ? AND session_id != 'webui' ORDER BY id ASC",
                    (_chat_sync_last_id,),
                ).fetchall()
                conn.close()

                for row in rows:
                    _chat_sync_last_id = row["id"]
                    await _ws_broadcast({
                        "type": "chat_sync",
                        "sender": row["sender"],
                        "text": row["text"],
                        "is_user": bool(row["is_user"]),
                    })
        except Exception as e:
            LOG.debug("Chat sync poll error: %s", e)

        await asyncio.sleep(1)


@app.on_event("startup")
async def startup():
    asyncio.create_task(_notification_poller())
    asyncio.create_task(_status_poller())
    asyncio.create_task(_chat_sync_poller())
    LOG.info("Frank Web UI starting on http://127.0.0.1:%d", PORT)


# ── Main ────────────────────────────────────────────────────

if __name__ == "__main__":
    from config.logging_config import setup_file_logging
    setup_file_logging("webui")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
