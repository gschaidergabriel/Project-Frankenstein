#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import hashlib
import json
import mimetypes
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel

from PIL import Image  # kept for future, not strictly required yet
from pypdf import PdfReader
from docx import Document

# ---------------- config ----------------

HOST = os.environ.get("INGESTD_HOST", "127.0.0.1")
PORT = int(os.environ.get("INGESTD_PORT", "8094"))

AICORE_VAR = Path.home() / "aicore" / "var" / "lib" / "aicore"
ART_DIR = AICORE_VAR / "artifacts"
POLICY_PATH = AICORE_VAR / "file_access.json"

# VLM (OpenAI-compatible chat completions is assumed)
VLM_URL = os.environ.get("VLM_URL", "").strip()          # e.g. http://127.0.0.1:8103/v1/chat/completions
VLM_MODEL = os.environ.get("VLM_MODEL", "").strip()      # optional; depends on server

# whisper selection
WHISPER_CPP_BIN = os.environ.get("WHISPER_CPP_BIN", "").strip()        # e.g. /home/.../whisper.cpp/build/bin/whisper-cli
WHISPER_CPP_MODEL = os.environ.get("WHISPER_CPP_MODEL", "").strip()    # e.g. /home/.../ggml-base.bin
FASTER_WHISPER_MODEL = os.environ.get("FASTER_WHISPER_MODEL", "base")  # tiny/base/small/medium/large-v3
FASTER_WHISPER_DEVICE = os.environ.get("FASTER_WHISPER_DEVICE", "cpu") # cpu/cuda
FASTER_WHISPER_COMPUTE = os.environ.get("FASTER_WHISPER_COMPUTE", "int8")

MAX_TEXT_CHARS = int(os.environ.get("INGESTD_MAX_TEXT_CHARS", "250000"))

# ---------------- policy ----------------

DEFAULT_POLICY = {
    "mode": "read_only",
    # If you want "everything", add "/" here.
    "allowed_roots": [
        str(Path.home()),
        str(Path.home() / "aicore"),
    ],
}

def load_policy() -> Dict[str, Any]:
    try:
        if not POLICY_PATH.exists():
            POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
            POLICY_PATH.write_text(json.dumps(DEFAULT_POLICY, indent=2), encoding="utf-8")
            return DEFAULT_POLICY
        j = json.loads(POLICY_PATH.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(j, dict):
            return DEFAULT_POLICY
        j.setdefault("mode", "read_only")
        j.setdefault("allowed_roots", DEFAULT_POLICY["allowed_roots"])
        return j
    except Exception:
        return DEFAULT_POLICY

def path_allowed(p: Path, policy: Dict[str, Any]) -> bool:
    roots = [Path(r).resolve() for r in policy.get("allowed_roots", []) if r]
    try:
        rp = p.resolve()
    except Exception:
        return False
    for r in roots:
        try:
            rp.relative_to(r)
            return True
        except Exception:
            pass
    return False

# ---------------- helpers ----------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def make_artifact_dir() -> Path:
    ART_DIR.mkdir(parents=True, exist_ok=True)
    aid = uuid.uuid4().hex[:12]
    d = ART_DIR / aid
    d.mkdir(parents=True, exist_ok=False)
    return d

def clamp_text(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\x00", "")
    if len(s) > MAX_TEXT_CHARS:
        return s[:MAX_TEXT_CHARS] + "\n\n[truncated]"
    return s

def guess_kind(filename: str, content_type: Optional[str]) -> str:
    fn = (filename or "").lower()
    ct = (content_type or "").lower()

    if ct.startswith("image/") or fn.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return "image"
    if ct.startswith("audio/") or fn.endswith((".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg")):
        return "audio"
    if fn.endswith(".pdf") or ct == "application/pdf":
        return "pdf"
    if fn.endswith(".docx") or ct in ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",):
        return "docx"
    if ct.startswith("text/") or fn.endswith((".txt", ".md", ".json", ".yaml", ".yml", ".py", ".js", ".ts", ".html", ".css")):
        return "text"

    mt, _ = mimetypes.guess_type(filename)
    if mt and mt.startswith("text/"):
        return "text"
    return "binary"

def read_text_file(path: Path) -> str:
    try:
        return clamp_text(path.read_text(encoding="utf-8"))
    except Exception:
        try:
            return clamp_text(path.read_text(encoding="latin-1"))
        except Exception:
            return ""

def extract_pdf(path: Path) -> Dict[str, Any]:
    r = PdfReader(str(path))
    pages_text = []
    for i, page in enumerate(r.pages):
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        t = (t or "").strip()
        if t:
            pages_text.append({"page": i + 1, "text": t})
    full = "\n\n".join([f"[page {p['page']}]\n{p['text']}" for p in pages_text])
    return {"text": clamp_text(full), "pages": len(r.pages), "extracted_pages": len(pages_text)}

def extract_docx(path: Path) -> Dict[str, Any]:
    doc = Document(str(path))
    paras = [p.text for p in doc.paragraphs if (p.text or "").strip()]
    full = "\n".join(paras)
    return {"text": clamp_text(full), "paragraphs": len(paras)}

def vlm_describe_image_openai_compat(image_path: Path) -> Dict[str, Any]:
    """
    Calls an OpenAI-compatible /v1/chat/completions endpoint with image input.
    Many local servers accept:
      {"model":"...", "messages":[{"role":"user","content":[{"type":"text","text":"..."},
                                                          {"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}]}]}
    If your server differs, adjust here.
    """
    if not VLM_URL:
        raise RuntimeError("VLM_URL is not set (set it in aicore-ingestd.service)")

    with image_path.open("rb") as f:
        b = f.read()

    ext = image_path.suffix.lower().lstrip(".")
    mime = "image/png" if ext == "png" else ("image/webp" if ext == "webp" else "image/jpeg")
    data_url = f"data:{mime};base64," + base64.b64encode(b).decode("ascii")

    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Beschreibe das Bild präzise. Wenn Text erkennbar ist, gib ihn mit an. Antworte knapp, aber vollständig."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "max_tokens": 350,
        "temperature": 0.2,
    }
    if VLM_MODEL:
        payload["model"] = VLM_MODEL

    cmd = ["curl", "-sS", "-X", "POST", VLM_URL, "-H", "Content-Type: application/json", "-d", json.dumps(payload)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError(f"VLM call failed: {p.stderr[:200]}")
    try:
        j = json.loads(p.stdout)
    except Exception:
        raise RuntimeError(f"VLM returned non-JSON: {p.stdout[:200]}")

    text = ""
    try:
        text = j["choices"][0]["message"]["content"]
    except Exception:
        text = json.dumps(j)[:500]

    return {"text": clamp_text(text), "provider": "vlm_openai_compat", "url": VLM_URL}

def transcribe_with_whisper_cpp(audio_path: Path) -> Dict[str, Any]:
    if not WHISPER_CPP_BIN or not Path(WHISPER_CPP_BIN).exists():
        raise RuntimeError("whisper.cpp binary not available (set WHISPER_CPP_BIN)")
    if not WHISPER_CPP_MODEL or not Path(WHISPER_CPP_MODEL).exists():
        raise RuntimeError("whisper.cpp model not available (set WHISPER_CPP_MODEL)")

    out_prefix = audio_path.with_suffix(".whispercpp")
    cmd = [
        WHISPER_CPP_BIN,
        "-m", WHISPER_CPP_MODEL,
        "-f", str(audio_path),
        "-otxt",
        "-of", str(out_prefix),
        "-nt",
    ]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    dt = time.time() - t0
    if p.returncode != 0:
        raise RuntimeError(f"whisper.cpp failed: {p.stderr[:300]}")

    produced = Path(str(out_prefix) + ".txt")
    text = produced.read_text(encoding="utf-8", errors="replace") if produced.exists() else ""
    return {"text": clamp_text(text.strip()), "engine": "whisper.cpp", "seconds": round(dt, 3)}

def transcribe_with_faster_whisper(audio_path: Path) -> Dict[str, Any]:
    from faster_whisper import WhisperModel

    t0 = time.time()
    model = WhisperModel(FASTER_WHISPER_MODEL, device=FASTER_WHISPER_DEVICE, compute_type=FASTER_WHISPER_COMPUTE)
    segments, info = model.transcribe(str(audio_path), beam_size=5)
    parts = []
    for s in segments:
        parts.append(s.text.strip())
    dt = time.time() - t0
    text = " ".join([p for p in parts if p])
    return {
        "text": clamp_text(text),
        "engine": "faster-whisper",
        "seconds": round(dt, 3),
        "language": getattr(info, "language", None),
    }

def transcribe_audio_auto(audio_path: Path) -> Dict[str, Any]:
    """
    Auto-pick:
      - prefer whisper.cpp if configured (typically fast/robust on CPU)
      - else use faster-whisper
    """
    if WHISPER_CPP_BIN and Path(WHISPER_CPP_BIN).exists() and WHISPER_CPP_MODEL and Path(WHISPER_CPP_MODEL).exists():
        return transcribe_with_whisper_cpp(audio_path)
    return transcribe_with_faster_whisper(audio_path)

# ---------------- API models ----------------

class ReadFileRequest(BaseModel):
    path: str

# ---------------- app ----------------

app = FastAPI(title="ingestd", version="0.1")

@app.get("/health")
def health():
    policy = load_policy()
    return {
        "ok": True,
        "artifacts_dir": str(ART_DIR),
        "vlm_url_set": bool(VLM_URL),
        "whispercpp_set": bool(WHISPER_CPP_BIN and WHISPER_CPP_MODEL),
        "policy": {"mode": policy.get("mode"), "allowed_roots": policy.get("allowed_roots", [])},
    }

@app.post("/read_file")
def read_file(req: ReadFileRequest):
    policy = load_policy()
    p = Path(req.path).expanduser()
    if not p.exists():
        raise HTTPException(status_code=404, detail="file does not exist")
    if not path_allowed(p, policy):
        raise HTTPException(status_code=403, detail=f"path not allowed by policy. Edit {POLICY_PATH} allowed_roots.")

    kind = guess_kind(p.name, mimetypes.guess_type(str(p))[0])

    art_dir = make_artifact_dir()
    orig = art_dir / ("original" + p.suffix.lower())
    shutil.copy2(p, orig)

    meta = {"source": "read_file", "path": str(p), "filename": p.name, "kind": kind, "sha256": sha256_file(orig)}
    extracted = {"text": "", "meta": {}}

    try:
        extracted = process_file(orig, kind)
    except Exception as e:
        meta["error"] = str(e)

    (art_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (art_dir / "extracted.json").write_text(json.dumps(extracted, indent=2), encoding="utf-8")

    return {"ok": True, "artifact_id": art_dir.name, "kind": kind, "meta": meta, "summary": summarize_extracted(extracted)}

@app.post("/ingest")
async def ingest(file: UploadFile = File(...)):
    art_dir = make_artifact_dir()
    filename = file.filename or "upload.bin"
    kind = guess_kind(filename, file.content_type)
    ext = Path(filename).suffix.lower() or ""
    orig = art_dir / ("original" + ext)

    with orig.open("wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)

    meta = {
        "source": "upload",
        "filename": filename,
        "content_type": file.content_type,
        "kind": kind,
        "sha256": sha256_file(orig),
        "bytes": orig.stat().st_size,
    }

    extracted = {"text": "", "meta": {}}
    try:
        extracted = process_file(orig, kind)
    except Exception as e:
        meta["error"] = str(e)

    (art_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (art_dir / "extracted.json").write_text(json.dumps(extracted, indent=2), encoding="utf-8")

    return {"ok": True, "artifact_id": art_dir.name, "kind": kind, "meta": meta, "summary": summarize_extracted(extracted)}

@app.get("/artifact/{artifact_id}")
def get_artifact(artifact_id: str):
    d = ART_DIR / artifact_id
    if not d.exists():
        raise HTTPException(status_code=404, detail="artifact not found")
    meta_p = d / "meta.json"
    ext_p = d / "extracted.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
    extracted = json.loads(ext_p.read_text(encoding="utf-8")) if ext_p.exists() else {}
    return {"ok": True, "artifact_id": artifact_id, "meta": meta, "extracted": extracted}

# ---------------- processing ----------------

def summarize_extracted(ex: Dict[str, Any]) -> Dict[str, Any]:
    t = (ex.get("text") or "").strip()
    return {"chars": len(t), "preview": (t[:240] + ("…" if len(t) > 240 else ""))}

def process_file(path: Path, kind: str) -> Dict[str, Any]:
    if kind == "text":
        return {"text": read_text_file(path), "meta": {"kind": "text"}}

    if kind == "pdf":
        out = extract_pdf(path)
        return {"text": out.get("text", ""), "meta": {"kind": "pdf", **{k: v for k, v in out.items() if k != "text"}}}

    if kind == "docx":
        out = extract_docx(path)
        return {"text": out.get("text", ""), "meta": {"kind": "docx", **{k: v for k, v in out.items() if k != "text"}}}

    if kind == "image":
        out = vlm_describe_image_openai_compat(path)
        return {"text": out.get("text", ""), "meta": {"kind": "image", **{k: v for k, v in out.items() if k != "text"}}}

    if kind == "audio":
        out = transcribe_audio_auto(path)
        return {"text": out.get("text", ""), "meta": {"kind": "audio", **{k: v for k, v in out.items() if k != "text"}}}

    t = read_text_file(path)
    if t:
        return {"text": t, "meta": {"kind": "binary_as_text"}}

    raise RuntimeError(f"unsupported file kind: {kind}")

# If you later want to run ingestd directly without uvicorn service:
# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run("app:app", host=HOST, port=PORT, reload=False)
