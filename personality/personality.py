#!/usr/bin/env python3
"""
Frank Personality Module

Single source of truth for Frank's identity, capabilities, and behavior.
Provides loading, validation, and prompt assembly for all clients.

Usage:
    from personality import get_persona, build_system_prompt, get_prompt_hash

    # Get current persona
    persona = get_persona()

    # Build system prompt for LLM
    system_prompt = build_system_prompt()

    # Build with runtime context
    system_prompt = build_system_prompt(
        runtime_context={"cpu_temp": "45°C", "ram_used": "8GB/32GB"}
    )

    # Get hash for version tracking
    info = get_prompt_hash()
    print(f"Persona: {info['id']} v{info['version']} ({info['sha256'][:12]})")
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Module directory
MODULE_DIR = Path(__file__).parent
PERSONA_FILE = MODULE_DIR / "frank.persona.json"
SCHEMA_FILE = MODULE_DIR / "frank.persona.schema.json"
CACHE_FILE = Path("/var/lib/aicore/personality_cache.json")

# Reload settings
RELOAD_CHECK_INTERVAL = 5.0  # Check file mtime every 5 seconds
MAX_PROMPT_LENGTH = 6500  # Hard limit for system prompt (chars, ~2000 tokens — fits in 4096 LLM context)

# Thread-safe state
_lock = threading.RLock()
_persona: Optional[Dict[str, Any]] = None
_persona_hash: str = ""
_persona_mtime: float = 0.0
_last_known_good: Optional[Dict[str, Any]] = None


class PersonaValidationError(Exception):
    """Raised when persona file is invalid."""
    pass


class PersonaLoadError(Exception):
    """Raised when persona file cannot be loaded."""
    pass


def _compute_hash(data: str) -> str:
    """Compute SHA256 hash of string data."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _validate_persona(persona: Dict[str, Any]) -> List[str]:
    """
    Validate persona against required structure.
    Returns list of validation errors (empty if valid).
    """
    errors = []

    # Required top-level keys
    required_keys = ["id", "version", "name", "language", "voice", "self_model", "prompts"]
    for key in required_keys:
        if key not in persona:
            errors.append(f"Missing required key: {key}")

    # Validate voice
    voice = persona.get("voice", {})
    if not isinstance(voice.get("tone"), str):
        errors.append("voice.tone must be a string")
    if not isinstance(voice.get("style_rules"), list):
        errors.append("voice.style_rules must be a list")

    # Validate self_model
    self_model = persona.get("self_model", {})
    if not isinstance(self_model.get("runs_local"), bool):
        errors.append("self_model.runs_local must be a boolean")
    if not isinstance(self_model.get("os"), str):
        errors.append("self_model.os must be a string")

    # Validate prompts
    prompts = persona.get("prompts", {})
    if not isinstance(prompts.get("identity_core"), str):
        errors.append("prompts.identity_core must be a string")

    # Check prompt lengths
    for key, val in prompts.items():
        if isinstance(val, str) and len(val) > MAX_PROMPT_LENGTH:
            errors.append(f"prompts.{key} exceeds max length ({len(val)} > {MAX_PROMPT_LENGTH})")

    return errors


def _load_persona_from_file(filepath: Path) -> Dict[str, Any]:
    """Load and parse persona JSON file."""
    if not filepath.exists():
        raise PersonaLoadError(f"Persona file not found: {filepath}")

    try:
        content = filepath.read_text(encoding="utf-8")
        persona = json.loads(content)
    except json.JSONDecodeError as e:
        raise PersonaLoadError(f"Invalid JSON in persona file: {e}")
    except IOError as e:
        raise PersonaLoadError(f"Cannot read persona file: {e}")

    return persona


def _save_cache(persona: Dict[str, Any]) -> None:
    """Save persona to cache file (last-known-good)."""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(persona, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.rename(CACHE_FILE)
    except Exception:
        pass  # Cache save failure is not critical


def _load_cache() -> Optional[Dict[str, Any]]:
    """Load persona from cache file."""
    try:
        if CACHE_FILE.exists():
            content = CACHE_FILE.read_text(encoding="utf-8")
            return json.loads(content)
    except Exception:
        pass
    return None


def load(force: bool = False) -> Dict[str, Any]:
    """
    Load persona from file with validation.

    Args:
        force: If True, bypass cache and reload from disk

    Returns:
        Validated persona dictionary

    Raises:
        PersonaLoadError: If file cannot be loaded
        PersonaValidationError: If persona is invalid (falls back to last-known-good)
    """
    global _persona, _persona_hash, _persona_mtime, _last_known_good

    with _lock:
        # Check if reload needed
        if not force and _persona is not None:
            try:
                current_mtime = PERSONA_FILE.stat().st_mtime
                if current_mtime == _persona_mtime:
                    return _persona
            except OSError:
                return _persona  # File inaccessible, use cached

        # Attempt to load from file
        try:
            persona = _load_persona_from_file(PERSONA_FILE)
            file_content = PERSONA_FILE.read_text(encoding="utf-8")
        except PersonaLoadError:
            # Try cache as fallback
            cached = _load_cache()
            if cached is not None:
                _persona = cached
                return _persona
            raise

        # Validate
        errors = _validate_persona(persona)
        if errors:
            # Try last-known-good
            if _last_known_good is not None:
                _persona = _last_known_good
                return _persona
            # Try cache
            cached = _load_cache()
            if cached is not None:
                _persona = cached
                return _persona
            raise PersonaValidationError(f"Invalid persona: {'; '.join(errors)}")

        # Success - update state
        _persona = persona
        _persona_hash = _compute_hash(file_content)
        _persona_mtime = PERSONA_FILE.stat().st_mtime
        _last_known_good = persona.copy()

        # Save to cache
        _save_cache(persona)

        return _persona


def get_persona() -> Dict[str, Any]:
    """
    Get current persona (thread-safe).
    Loads from file if not already loaded.
    """
    with _lock:
        if _persona is None:
            return load()
        return _persona


def reload() -> Dict[str, Any]:
    """Force reload persona from disk."""
    return load(force=True)


def get_prompt_hash() -> Dict[str, str]:
    """
    Get persona identification info for version tracking.

    Returns:
        Dict with id, version, name, sha256
    """
    persona = get_persona()
    with _lock:
        return {
            "id": persona.get("id", "unknown"),
            "version": persona.get("version", "0.0.0"),
            "name": persona.get("name", "Unknown"),
            "sha256": _persona_hash or "unknown"
        }


def build_system_prompt(
    profile: str = "default",
    runtime_context: Optional[Dict[str, Any]] = None,
    include_tools: bool = True,
    include_self_knowledge: bool = True,
    max_length: Optional[int] = None
) -> str:
    """
    Build the complete system prompt for LLM.

    Args:
        profile: Which profile to use (default, minimal, full)
        runtime_context: Optional runtime data (sys_summary, temps, etc.)
        include_tools: Whether to include tool/capability descriptions
        include_self_knowledge: Whether to include self-knowledge context
        max_length: Optional max length override

    Returns:
        Complete system prompt string

    Assembly order (deterministic):
        1. Identity core
        2. Self-knowledge context (if enabled)
        3. Voice/style rules
        4. Capabilities (if include_tools)
        5. Restrictions
        6. Personality traits
        7. Runtime context (if provided)
    """
    persona = get_persona()
    prompts = persona.get("prompts", {})
    profiles = persona.get("profiles", {})

    # Get profile sections
    profile_cfg = profiles.get(profile, profiles.get("default", {"include_sections": ["identity_core"]}))
    sections_to_include = profile_cfg.get("include_sections", ["identity_core"])

    # Build prompt parts
    parts = []

    for section in sections_to_include:
        if section in prompts:
            parts.append(prompts[section])

    # Add self-knowledge context (minimal status only - NO identity injection!)
    if include_self_knowledge:
        try:
            from .self_knowledge import get_implicit_context
            sk_context = get_implicit_context()
            if sk_context:
                parts.insert(1, sk_context)  # After identity_core - just status, no identity
        except ImportError:
            pass  # Self-knowledge module not available

    # Inject user name if known (persistent across sessions)
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from tools.user_profile import get_user_name
        user_name = get_user_name()
        if user_name:
            parts.insert(1, f"Der User heisst {user_name}. Sprich ihn mit Namen an (Du-Form).")
    except Exception:
        pass

    # KRITISCH: Sandbox-Awareness injizieren
    # Frank MUSS immer wissen ob er in Sandbox oder Production ist
    try:
        from ..ext.sandbox_awareness import get_context_injection, is_sandbox_mode
        sandbox_ctx = get_context_injection()
        if sandbox_ctx:
            parts.insert(3, sandbox_ctx)  # Nach Identity und Self-Knowledge
    except ImportError:
        pass  # Sandbox-Awareness nicht verfügbar

    # Add runtime context if provided
    if runtime_context:
        ctx_lines = ["", "AKTUELLER SYSTEM-KONTEXT:"]
        for key, val in runtime_context.items():
            if val is not None:
                ctx_lines.append(f"- {key}: {val}")
        if len(ctx_lines) > 2:
            parts.append("\n".join(ctx_lines))

    # Join with double newlines
    system_prompt = "\n\n".join(parts)

    # Enforce length limit
    limit = max_length or MAX_PROMPT_LENGTH
    if len(system_prompt) > limit:
        system_prompt = system_prompt[:limit-3] + "..."

    return system_prompt


def build_minimal_prompt() -> str:
    """Build minimal identity prompt (for fast/simple requests)."""
    return build_system_prompt(profile="minimal", include_tools=False)


def build_full_prompt(runtime_context: Optional[Dict[str, Any]] = None) -> str:
    """Build full prompt with all sections."""
    return build_system_prompt(profile="full", runtime_context=runtime_context)


def get_capability_description(capability: str) -> Optional[str]:
    """Get description for a specific capability."""
    persona = get_persona()
    capabilities = persona.get("capabilities", {})
    cap = capabilities.get(capability)
    if cap:
        return f"{cap['name']}: {cap['description']}"
    return None


def get_tool_policy() -> Dict[str, Any]:
    """Get tool policy configuration."""
    persona = get_persona()
    return persona.get("tool_policy", {"default": "allow"})


def is_tool_allowed(tool_name: str) -> bool:
    """Check if a tool is allowed by policy."""
    policy = get_tool_policy()
    deny_list = policy.get("deny", [])
    allow_list = policy.get("allow", [])
    default = policy.get("default", "allow")

    # Check deny list first
    for pattern in deny_list:
        if tool_name == pattern or tool_name.startswith(pattern.rstrip("*")):
            return False

    # Check allow list
    for pattern in allow_list:
        if tool_name == pattern or tool_name.startswith(pattern.rstrip("*")):
            return True

    # Fall back to default
    return default == "allow"


def get_style_rules() -> List[str]:
    """Get voice/style rules."""
    persona = get_persona()
    return persona.get("voice", {}).get("style_rules", [])


def get_tone() -> str:
    """Get voice tone description."""
    persona = get_persona()
    return persona.get("voice", {}).get("tone", "neutral")


# Signal handler for hot reload
def _sighup_handler(signum, frame):
    """Handle SIGHUP for hot reload."""
    try:
        reload()
        print("[personality] Reloaded persona via SIGHUP", flush=True)
    except Exception as e:
        print(f"[personality] Reload failed: {e}", flush=True)


# Register signal handler (Unix only)
try:
    signal.signal(signal.SIGHUP, _sighup_handler)
except (AttributeError, ValueError):
    pass  # Windows or signal not available


# Background reload checker (optional)
_reload_thread: Optional[threading.Thread] = None
_reload_stop = threading.Event()


def start_auto_reload(interval: float = RELOAD_CHECK_INTERVAL) -> None:
    """Start background thread that checks for file changes."""
    global _reload_thread

    if _reload_thread is not None:
        return

    def _checker():
        last_mtime = 0.0
        while not _reload_stop.is_set():
            try:
                mtime = PERSONA_FILE.stat().st_mtime
                if mtime != last_mtime and last_mtime > 0:
                    reload()
                    print("[personality] Auto-reloaded persona (file changed)", flush=True)
                last_mtime = mtime
            except Exception:
                pass
            _reload_stop.wait(interval)

    _reload_thread = threading.Thread(target=_checker, daemon=True)
    _reload_thread.start()


def stop_auto_reload() -> None:
    """Stop background reload checker."""
    global _reload_thread
    _reload_stop.set()
    if _reload_thread is not None:
        _reload_thread.join(timeout=2.0)
        _reload_thread = None
    _reload_stop.clear()


# CLI for testing
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "validate":
            try:
                persona = load(force=True)
                info = get_prompt_hash()
                print(f"Valid: {info['id']} v{info['version']}")
                print(f"SHA256: {info['sha256']}")
            except (PersonaLoadError, PersonaValidationError) as e:
                print(f"INVALID: {e}")
                sys.exit(1)

        elif cmd == "prompt":
            profile = sys.argv[2] if len(sys.argv) > 2 else "default"
            print(build_system_prompt(profile=profile))

        elif cmd == "hash":
            info = get_prompt_hash()
            print(f"{info['id']} v{info['version']} sha256:{info['sha256'][:16]}")

        elif cmd == "policy":
            policy = get_tool_policy()
            print(json.dumps(policy, indent=2))

        else:
            print(f"Unknown command: {cmd}")
            print("Usage: personality.py [validate|prompt [profile]|hash|policy]")
            sys.exit(1)
    else:
        # Default: show prompt
        print("=== Frank System Prompt ===")
        print(build_system_prompt())
        print("\n=== Info ===")
        info = get_prompt_hash()
        print(f"ID: {info['id']}")
        print(f"Version: {info['version']}")
        print(f"SHA256: {info['sha256'][:32]}...")
