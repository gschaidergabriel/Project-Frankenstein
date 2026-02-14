#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AI Core Chat Overlay — HTTP Helper Functions

Extracted from chat_overlay_monolith.py.
Contains HTTP GET/POST helpers, multipart form upload, ingest detection, and URL opening.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import time
import uuid
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from overlay.constants import (
    LOG,
    SESSION_ID,
    DESKTOP_ACTION_URL,
    INGEST_BASE_ENV,
    INGEST_PORT_CANDIDATES,
    INGEST_HEALTH_PATHS,
    INGEST_UPLOAD_PATHS,
)


# ---------- HTTP Helpers ----------
def _http_get_json(url: str, timeout_s: float = 2.0) -> Optional[Dict[str, Any]]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except Exception:
        return None


def _http_post_json(url: str, payload: Dict[str, Any], timeout_s: float = 30.0) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = "<failed to read body>"
        raise RuntimeError(f"HTTP {e.code}: {body[:1200]}") from None
    except Exception as e:
        raise RuntimeError(str(e)) from None


def _multipart_form(file_path: Path, field_name: str = "file") -> Tuple[bytes, str]:
    boundary = f"----aicoreboundary{uuid.uuid4().hex}"
    ctype = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    filename = file_path.name
    file_bytes = file_path.read_bytes()
    meta = json.dumps({"session_id": SESSION_ID, "ts": time.time()}, ensure_ascii=False).encode("utf-8")

    parts: List[bytes] = []
    parts.append(f"--{boundary}\r\n".encode("utf-8"))
    parts.append(
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
        f"Content-Type: {ctype}\r\n\r\n".encode("utf-8")
    )
    parts.append(file_bytes)
    parts.append(b"\r\n")

    parts.append(f"--{boundary}\r\n".encode("utf-8"))
    parts.append(b'Content-Disposition: form-data; name="meta"\r\n')
    parts.append(b"Content-Type: application/json\r\n\r\n")
    parts.append(meta)
    parts.append(b"\r\n")

    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    return body, f"multipart/form-data; boundary={boundary}"


def _http_post_multipart(url: str, file_path: Path, timeout_s: float = 60.0) -> Dict[str, Any]:
    body, content_type = _multipart_form(file_path, field_name="file")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": content_type, "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body_txt = ""
        try:
            body_txt = e.read().decode("utf-8", errors="replace")
        except Exception:
            body_txt = "<failed to read body>"
        raise RuntimeError(f"HTTP {e.code}: {body_txt[:1200]}") from None
    except Exception as e:
        raise RuntimeError(str(e)) from None


def _is_ok_health(j: Optional[Dict[str, Any]]) -> bool:
    return isinstance(j, dict) and (j.get("ok") is True or j.get("status") == "ok")


def _detect_ingest_base() -> Optional[str]:
    if INGEST_BASE_ENV:
        return INGEST_BASE_ENV
    for port in INGEST_PORT_CANDIDATES:
        base = f"http://127.0.0.1:{port}"
        for hp in INGEST_HEALTH_PATHS:
            j = _http_get_json(base + hp, timeout_s=0.8)
            if _is_ok_health(j):
                return base
    return None


def _try_ingest_upload(file_path: Path) -> Tuple[bool, str]:
    base = _detect_ingest_base()
    if not base:
        return False, "ingest base not found"
    last_err = ""
    for up in INGEST_UPLOAD_PATHS:
        url = base + up
        try:
            _http_post_multipart(url, file_path, timeout_s=60.0)
            return True, f"{url}"
        except Exception as e:
            last_err = str(e)
    return False, f"upload failed ({base}): {last_err}"


def _open_url(url: str) -> None:
    try:
        _http_post_json(DESKTOP_ACTION_URL, {"type": "open_url", "url": url}, timeout_s=4.0)
    except Exception:
        try:
            webbrowser.open(url)
        except Exception:
            pass
