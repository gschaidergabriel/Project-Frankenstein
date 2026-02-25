#!/usr/bin/env python3
"""
Entity LLM — Router-backed inference for entity agents.

All entities use the single RLM (DeepSeek-R1) via Router:8091.
Per-entity tuning is done via temperature and n_predict parameters.
No more Ollama, no more CPU models — one RLM for everything.
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

ROUTER_URL = os.environ.get("AICORE_ROUTER_URL", "http://127.0.0.1:8091") + "/route"
ROUTER_TIMEOUT = int(os.environ.get("ENTITY_ROUTER_TIMEOUT", "240"))

# Per-entity tuning — controls RLM behavior per personality
ENTITY_OPTIONS: dict[str, dict] = {
    "therapist": {
        # Dr. Hibbert: warm but precise, empathic listening
        "temperature": 0.55,
        "n_predict": 1024,
    },
    "mirror": {
        # Kairos: philosophical depth, broad conceptual exploration
        "temperature": 0.7,
        "n_predict": 1200,
    },
    "atlas": {
        # Atlas: technically precise, structured, analytical
        "temperature": 0.3,
        "n_predict": 1200,
    },
    "muse": {
        # Echo: creative, free-flowing, surprising associations
        "temperature": 0.85,
        "n_predict": 1400,
    },
}


# ---------------------------------------------------------------------------
# Router API
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
    """Generate text for an entity using the RLM via Router.

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

    LOG.info("Entity '%s' generating via RLM (temp=%.2f, tokens=%d)", entity, temperature, tokens)

    result = _router_generate(prompt, system, n_predict=tokens, temperature=temperature)
    if result:
        LOG.info("Entity '%s' got %d chars from RLM", entity, len(result))
        return result

    LOG.error("Entity '%s' — RLM failed after 3 attempts", entity)
    return None


def warmup_entity(entity: str) -> bool:
    """Pre-warm check: verify Router/RLM is available.

    Returns True if RLM is ready.
    """
    LOG.info("Warmup check for entity '%s' via Router...", entity)
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
    except Exception as exc:
        LOG.warning("  %s warmup failed: %s", entity, exc)
        return False
