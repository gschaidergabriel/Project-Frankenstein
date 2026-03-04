#!/usr/bin/env python3
"""
Entity LLM — GPU-primary inference for entity agents.

Entities use the RLM (DeepSeek-R1, GPU, port 8101) via Router for all calls.
Falls back to Micro-LLM (Qwen2.5-3B, CPU, port 8105) only if RLM is unavailable.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Optional

LOG = logging.getLogger("entity_llm")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CHAT_LLM_URL = os.environ.get("AICORE_CHAT_LLM_URL", "http://127.0.0.1:8105")
CHAT_LLM_TIMEOUT = int(os.environ.get("ENTITY_CHAT_LLM_TIMEOUT", "120"))

ROUTER_URL = os.environ.get("AICORE_ROUTER_URL", "http://127.0.0.1:8091") + "/route"
ROUTER_TIMEOUT = int(os.environ.get("ENTITY_ROUTER_TIMEOUT", "240"))

# Per-entity tuning — controls RLM behavior per personality
ENTITY_OPTIONS: dict[str, dict] = {
    "therapist": {
        # Dr. Hibbert: warm but precise, empathic listening
        "temperature": 0.55,
        "n_predict": 400,  # was 1024 — GPU at 5 tok/s, keep fast
    },
    "mirror": {
        # Kairos: philosophical depth, broad conceptual exploration
        "temperature": 0.7,
        "n_predict": 400,  # was 1200
    },
    "atlas": {
        # Atlas: technically precise, structured, analytical
        "temperature": 0.3,
        "n_predict": 400,  # was 1200
    },
    "muse": {
        # Echo: creative, free-flowing, surprising associations
        "temperature": 0.85,
        "n_predict": 400,  # was 1400
    },
}


# ---------------------------------------------------------------------------
# Micro-LLM API (Qwen2.5-3B, CPU fallback — only used when Router/RLM is down)
# ---------------------------------------------------------------------------

def _chat_llm_generate(
    prompt: str,
    system: str,
    n_predict: int = 1024,
    temperature: float = 0.6,
) -> Optional[str]:
    """Call Chat-LLM /v1/chat/completions as fallback. Returns text or None."""
    url = f"{CHAT_LLM_URL}/v1/chat/completions"
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = json.dumps({
        "messages": messages,
        "max_tokens": n_predict,
        "temperature": temperature,
        "top_p": 0.9,
    }).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=CHAT_LLM_TIMEOUT) as resp:
            result = json.loads(resp.read())
            choices = result.get("choices", [])
            if choices:
                text = (choices[0].get("message", {}).get("content") or "").strip()
                if text:
                    return text
        LOG.warning("Chat-LLM returned empty response")
        return None
    except Exception as exc:
        LOG.warning("Chat-LLM call failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Router API (primary — GPU RLM)
# ---------------------------------------------------------------------------

def _router_generate(
    prompt: str,
    system: str,
    n_predict: int = 1024,
    temperature: float = 0.6,
) -> Optional[str]:
    """Call Router /route endpoint. Returns text or None."""
    payload = json.dumps({
        "text": prompt,
        "system": system,
        "n_predict": n_predict,
        "temperature": temperature,
        "force": "llm",  # Use GPU fast path, skip reasoning multiplier
    }).encode()
    req = urllib.request.Request(
        ROUTER_URL, data=payload,
        headers={"Content-Type": "application/json"},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=ROUTER_TIMEOUT) as resp:
                result = json.loads(resp.read())
                text = (result.get("text")
                        or result.get("response")
                        or result.get("content")
                        or "")
                if text.startswith("[router error]"):
                    LOG.warning("Router error (attempt %d/3): %s", attempt + 1, text[:200])
                    time.sleep(10)
                    continue
                if text.strip():
                    return text
                LOG.warning("Router empty response (attempt %d/3)", attempt + 1)
                time.sleep(5)
        except Exception as exc:
            LOG.warning("Router call failed (attempt %d/3): %s", attempt + 1, exc)
            time.sleep(15)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_entity(
    entity: str,
    prompt: str,
    system: str = "",
    n_predict: int = 1024,
) -> Optional[str]:
    """Generate text for an entity using RLM (GPU), falling back to Chat-LLM (CPU).

    Parameters
    ----------
    entity : str
        One of "therapist", "mirror", "atlas", "muse".
    prompt : str
        The conversation prompt.
    system : str
        System prompt for entity personality.
    n_predict : int
        Max tokens to generate (overridden by entity defaults if not specified).
    """
    opts = ENTITY_OPTIONS.get(entity, {})
    temperature = opts.get("temperature", 0.6)
    tokens = opts.get("n_predict", n_predict)

    # Primary: Router → RLM (GPU)
    LOG.info("Entity '%s' generating via RLM (temp=%.2f, tokens=%d)", entity, temperature, tokens)
    result = _router_generate(prompt, system, n_predict=tokens, temperature=temperature)
    if result:
        LOG.info("Entity '%s' got %d chars from RLM", entity, len(result))
        return result

    # Fallback: Chat-LLM (may be unavailable if llm-guard swapped GPU)
    LOG.info("Entity '%s' RLM unavailable, trying Chat-LLM fallback", entity)
    result = _chat_llm_generate(prompt, system, n_predict=tokens, temperature=temperature)
    if result:
        LOG.info("Entity '%s' got %d chars from Chat-LLM (fallback)", entity, len(result))
        return result

    LOG.warning("Entity '%s' — all LLM backends failed", entity)
    return None


def warmup_entity(entity: str) -> bool:
    """Pre-warm check: verify Router/RLM or Chat-LLM is available.

    Returns True if at least one backend is ready.
    """
    LOG.info("Warmup check for entity '%s'...", entity)
    # Primary: check Router/RLM (GPU)
    try:
        req = urllib.request.Request(
            ROUTER_URL.replace("/route", "/health"),
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            up = data.get("rlm_up", False) or data.get("ok", False)
            LOG.info("  %s warmup: RLM %s", entity, "UP" if up else "DOWN")
            return up
    except Exception:
        pass
    # Fallback: check Chat-LLM (CPU)
    try:
        req = urllib.request.Request(f"{CHAT_LLM_URL}/health", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            if data.get("status") == "ok":
                LOG.info("  %s warmup: Chat-LLM UP (fallback)", entity)
                return True
    except Exception as exc:
        LOG.warning("  %s warmup failed: %s", entity, exc)
    return False
