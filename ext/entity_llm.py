#!/usr/bin/env python3
"""
Entity LLM — Ollama-backed inference for entity agents.

Each entity gets its own model via Ollama (port 11434, CPU-only).
Fallback: if Ollama fails, fall back to Router:8091 (Llama 8B GPU).

Model loading is automatic — Ollama pulls/loads on first call.
Only one entity session runs at a time, so only one model is loaded.
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

OLLAMA_BASE = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_GENERATE = f"{OLLAMA_BASE}/api/generate"
ROUTER_URL = os.environ.get("AICORE_ROUTER_URL", "http://127.0.0.1:8091") + "/route"

# Entity → Ollama model mapping
ENTITY_MODELS: dict[str, str] = {
    "therapist": "qwen2.5:3b",
    "mirror":    "phi4-mini",
    "atlas":     "phi4-mini",
    "muse":      "mistral:7b-instruct",
}

# CPU-only generation options — never compete with Llama 8B GPU
DEFAULT_OPTIONS: dict = {
    "num_gpu": 0,
    "num_predict": 512,
    "temperature": 0.7,
    "top_p": 0.9,
    "repeat_penalty": 1.1,
}

# Per-entity tuning — overrides DEFAULT_OPTIONS for each role
ENTITY_OPTIONS: dict[str, dict] = {
    "therapist": {
        # Dr. Hibbert: warm but precise, empathic listening, no rambling
        "temperature": 0.55,
        "top_p": 0.85,
        "top_k": 40,
        "repeat_penalty": 1.2,    # avoid repetitive reassurance loops
        "num_predict": 400,       # concise therapeutic responses
    },
    "mirror": {
        # Kairos: philosophical depth, broad conceptual exploration
        "temperature": 0.75,
        "top_p": 0.92,
        "top_k": 60,
        "repeat_penalty": 1.05,   # may revisit concepts deliberately
        "num_predict": 512,
    },
    "atlas": {
        # Atlas: technically precise, structured, analytical
        "temperature": 0.3,
        "top_p": 0.8,
        "top_k": 30,
        "repeat_penalty": 1.15,
        "num_predict": 512,
    },
    "muse": {
        # Echo: creative, free-flowing, surprising associations
        "temperature": 0.9,
        "top_p": 0.95,
        "top_k": 80,
        "repeat_penalty": 1.0,   # creative repetition is ok
        "num_predict": 600,       # longer creative output
    },
}

OLLAMA_TIMEOUT = 180       # CPU inference can be slow — 3 min
OLLAMA_PULL_TIMEOUT = 600  # Model download — 10 min
FALLBACK_TIMEOUT = 120     # Router fallback


# ---------------------------------------------------------------------------
# Ollama API
# ---------------------------------------------------------------------------

def _ollama_generate(
    model: str,
    prompt: str,
    system: str = "",
    num_predict: int = 512,
    timeout: int = OLLAMA_TIMEOUT,
    entity: str = "",
) -> Optional[str]:
    """Call Ollama /api/generate.  Returns text or None."""
    # Build options: defaults → entity-specific overrides → explicit num_predict
    opts = {**DEFAULT_OPTIONS}
    if entity and entity in ENTITY_OPTIONS:
        opts.update(ENTITY_OPTIONS[entity])
    opts["num_predict"] = num_predict
    payload = {
        "model": model,
        "prompt": prompt,
        "system": system,
        "options": opts,
        "stream": False,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        OLLAMA_GENERATE, data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
            text = result.get("response", "")
            if not text.strip():
                LOG.warning("Ollama empty response (model=%s)", model)
                return None
            return text
    except Exception as exc:
        LOG.warning("Ollama generate failed (model=%s): %s", model, exc)
        return None


def _ollama_available() -> bool:
    """Quick health check — is Ollama reachable?"""
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE}/api/version")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def _ollama_has_model(model: str) -> bool:
    """Check if the model is already pulled locally."""
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            names = [m.get("name", "") for m in data.get("models", [])]
            # Ollama stores full tag, e.g. "qwen2.5:3b" or "phi4-mini:latest"
            base = model.split(":")[0]
            return any(model == n or n.startswith(f"{base}:") for n in names)
    except Exception:
        return False


def _ollama_pull(model: str) -> bool:
    """Pull model from Ollama registry.  Blocking."""
    LOG.info("Pulling Ollama model %s (may take minutes)...", model)
    payload = json.dumps({"name": model, "stream": False}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/pull", data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=OLLAMA_PULL_TIMEOUT) as resp:
            result = json.loads(resp.read())
            LOG.info("Ollama pull %s: %s", model, result.get("status", "ok"))
            return True
    except Exception as exc:
        LOG.error("Ollama pull failed for %s: %s", model, exc)
        return False


# ---------------------------------------------------------------------------
# Router fallback (identical to today's behavior)
# ---------------------------------------------------------------------------

def _router_fallback(
    prompt: str, system: str, n_predict: int = 512,
) -> Optional[str]:
    """Fall back to Router:8091 → Llama 8B (original entity behavior)."""
    LOG.info("Entity LLM falling back to Router (Llama 8B)")
    payload = json.dumps({
        "text": prompt,
        "system": system,
        "force": "llama",
        "n_predict": n_predict,
    }).encode()
    req = urllib.request.Request(
        ROUTER_URL, data=payload,
        headers={"Content-Type": "application/json"},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=FALLBACK_TIMEOUT) as resp:
                result = json.loads(resp.read())
                text = (result.get("response")
                        or result.get("text")
                        or result.get("content")
                        or "")
                if text.startswith("[router error]"):
                    if "Loading model" in text:
                        time.sleep(30)
                        continue
                    return None
                if text.strip():
                    return text
                time.sleep(10)
        except Exception as exc:
            LOG.warning("Router fallback attempt %d/3: %s", attempt + 1, exc)
            time.sleep(15)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_entity(
    entity: str,
    prompt: str,
    system: str = "",
    n_predict: int = 512,
) -> Optional[str]:
    """Generate text for an entity using its dedicated Ollama model.

    Falls back to Router/Llama 8B if Ollama is unavailable.

    Parameters
    ----------
    entity : str
        One of "therapist", "mirror", "atlas", "muse".
    prompt : str
        The conversation prompt.
    system : str
        System prompt for entity personality.
    n_predict : int
        Max tokens to generate.
    """
    model = ENTITY_MODELS.get(entity)
    if not model:
        LOG.error("Unknown entity '%s' — using router fallback", entity)
        return _router_fallback(prompt, system, n_predict)

    # 1) Ollama reachable?
    if not _ollama_available():
        return _router_fallback(prompt, system, n_predict)

    # 2) Model pulled?
    if not _ollama_has_model(model):
        if not _ollama_pull(model):
            return _router_fallback(prompt, system, n_predict)

    # 3) Generate (with entity-specific tuning)
    result = _ollama_generate(model, prompt, system, num_predict=n_predict, entity=entity)
    if result:
        return result

    # 4) Retry once
    LOG.info("Ollama empty — retrying once for %s/%s", entity, model)
    time.sleep(5)
    result = _ollama_generate(model, prompt, system, num_predict=n_predict, entity=entity)
    if result:
        return result

    # 5) Total failure — Router fallback
    LOG.warning("Ollama failed for %s (%s) — falling back to Router", entity, model)
    return _router_fallback(prompt, system, n_predict)


def warmup_entity(entity: str) -> bool:
    """Pre-warm an entity's Ollama model at session start.

    Returns True if model is ready, False if Router fallback is needed.
    """
    model = ENTITY_MODELS.get(entity)
    if not model:
        return False

    if not _ollama_available():
        LOG.warning("Ollama not available for warmup (%s)", entity)
        return False

    if not _ollama_has_model(model):
        if not _ollama_pull(model):
            return False

    LOG.info("Warming up Ollama model %s for %s...", model, entity)
    result = _ollama_generate(model, "Hello", num_predict=8, timeout=120, entity=entity)
    if result:
        LOG.info("  %s/%s warm: OK", entity, model)
        return True

    LOG.warning("  %s/%s warmup failed", entity, model)
    return False
