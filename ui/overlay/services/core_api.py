"""Core chat API helper."""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Any, Callable, Dict, Optional

from overlay.constants import LOG, CORE_BASE, DEFAULT_MAX_TOKENS, DEFAULT_TIMEOUT_S, SESSION_ID, FRANK_IDENTITY, get_frank_identity
from overlay.http_helpers import _http_post_json

# Router base for direct streaming (bypasses core for SSE)
ROUTER_BASE = "http://127.0.0.1:8091"


def _core_chat(
    text: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    task: str = "chat.fast",
    force: Optional[str] = None,
    no_reflect: bool = False,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "text": text,
        "want_tools": False,
        "max_tokens": int(max_tokens),
        "timeout_s": int(timeout_s),
        "session_id": SESSION_ID,
        "task": task,
    }
    if force:
        payload["force"] = force
    if no_reflect:
        payload["no_reflect"] = True
    return _http_post_json(CORE_BASE + "/chat", payload, timeout_s=float(timeout_s) + 10.0)


def _core_chat_stream(
    text: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    force: Optional[str] = None,
    on_token: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Stream tokens from LLM via router SSE endpoint.

    Calls on_token(chunk_text) for each received token.
    Returns dict with 'ok', 'text', 'model' when done.
    Falls back to non-streaming _core_chat on connection error.
    """
    # CRITICAL: Pass Frank's identity as system prompt so Router uses it
    # instead of its generic fallback. Without this, the LLM loses Frank's
    # persona and reverts to "ich bin ein neutraler Assistent".
    identity = get_frank_identity()

    payload: Dict[str, Any] = {
        "text": text,
        "n_predict": int(max_tokens),
        "system": identity,
    }
    if force:
        payload["force"] = force

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{ROUTER_BASE}/route/stream",
        data=data,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )

    full_text = ""
    model = force or "llama"

    try:
        with urllib.request.urlopen(req, timeout=420) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data: "):
                    continue
                try:
                    chunk = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue

                if chunk.get("error"):
                    raise RuntimeError(chunk["error"])

                content = chunk.get("content", "")
                if content:
                    full_text += content
                    if on_token:
                        on_token(content)

                if chunk.get("model"):
                    model = chunk["model"]

                if chunk.get("stop", False):
                    break

    except (urllib.error.URLError, ConnectionRefusedError, OSError) as e:
        # Router streaming not available — fall back to blocking call
        LOG.warning(f"Streaming unavailable ({e}), falling back to blocking call")
        res = _core_chat(text, max_tokens=max_tokens, force=force)
        if on_token and res.get("text"):
            on_token(res["text"])
        return res

    return {"ok": True, "text": full_text, "model": model}
