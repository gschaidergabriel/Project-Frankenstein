#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
user_profile.py -- Persistent user profile for Frank.

Stores user preferences (name, etc.) in a JSON file.
Thread-safe, survives reboots.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any, Dict, Optional

LOG = logging.getLogger("user_profile")

try:
    from config.paths import get_state
    PROFILE_FILE = get_state("user_profile")
except ImportError:
    PROFILE_FILE = Path.home() / ".local" / "share" / "frank" / "state" / "user_profile.json"
_lock = threading.Lock()
_cache: Optional[Dict[str, Any]] = None


def _load() -> Dict[str, Any]:
    """Load profile from disk (with cache)."""
    global _cache
    if _cache is not None:
        return _cache
    if PROFILE_FILE.exists():
        try:
            _cache = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
            return _cache
        except Exception as e:
            LOG.warning(f"Failed to load user profile: {e}")
    _cache = {}
    return _cache


def _save(data: Dict[str, Any]) -> None:
    """Save profile to disk."""
    global _cache
    try:
        PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = PROFILE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.rename(PROFILE_FILE)
        _cache = data
    except Exception as e:
        LOG.warning(f"Failed to save user profile: {e}")


def get_user_name() -> Optional[str]:
    """Get the user's name (or None if not set)."""
    with _lock:
        return _load().get("name")


def set_user_name(name: str) -> None:
    """Set the user's name."""
    with _lock:
        data = _load().copy()
        data["name"] = name.strip()
        _save(data)
    LOG.info(f"User name set to: {name}")


def get_user_profile() -> Dict[str, Any]:
    """Get the full user profile."""
    with _lock:
        return _load().copy()


# ── Fuzzy name extraction from natural language ──────────────────────

# Patterns that introduce a name (German + English, fuzzy)
_NAME_PATTERNS = [
    # "mein name ist Alex" / "mein name is Alex"
    re.compile(
        r"(?:mein|my)\s+name\s+(?:ist|is|lautet|wäre|waere)\s+(.+)",
        re.IGNORECASE,
    ),
    # "ich bin Alex" / "ich bin die Laura" / "ich bin der Max"
    re.compile(
        r"ich\s+bin\s+(?:die|der|das)?\s*([A-Z\u00C0-\u024F][a-z\u00C0-\u024F]{1,}(?:\s+[A-Z\u00C0-\u024F][a-z\u00C0-\u024F]{1,})?)",
        re.UNICODE,
    ),
    # "ich heisse Alex" / "ich heiße Alex"
    # Negative lookahead blocks "ich heiße das/es gut" (= approve, not name)
    re.compile(
        r"ich\s+hei(?:ss|ß)e\s+(?!(?:das|es)\s)(.+)",
        re.IGNORECASE,
    ),
    # "nenn mich Alex" / "ruf mich Alex" / "sag Alex zu mir"
    re.compile(
        r"(?:nenn|ruf|call)\s+mich\s+(.+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"sag\s+(.+?)\s+zu\s+mir",
        re.IGNORECASE,
    ),
    # "der user ist Alex" / "der benutzer heisst Laura"
    re.compile(
        r"(?:der\s+)?(?:user|benutzer|nutzer)\s+(?:ist|heisst|heißt|bin)\s+(.+)",
        re.IGNORECASE,
    ),
    # "du kannst mich X nennen" / "du darfst mich X nennen"
    re.compile(
        r"(?:du\s+)?(?:kannst|darfst|sollst)\s+mich\s+(.+?)\s+nennen",
        re.IGNORECASE,
    ),
    # English: "I'm Alex" / "I am Alex" / "call me Alex"
    re.compile(
        r"(?:i'm|i\s+am|call\s+me)\s+(.+)",
        re.IGNORECASE,
    ),
]

# Words that are NOT names (false positive filter)
# NOTE: checked per-word (any word match → reject), not whole-string
_NOT_NAMES = {
    # German state/adjective
    "hier", "da", "dran", "zurück", "back", "fertig", "ready", "bereit",
    "online", "offline", "busy", "müde", "wach", "genervt", "happy",
    "traurig", "sauer", "hungrig", "ok", "okay", "gut", "schlecht",
    "neu", "alt", "gross", "klein", "froh", "willkommen",
    # German pronouns / articles
    "ich", "du", "er", "sie", "es", "wir", "ihr", "mich", "mir", "dir",
    "dein", "sein", "sich", "uns", "euch",
    "ein", "eine", "einer", "kein", "keine",
    # German particles / conjunctions / adverbs
    "nicht", "so", "total", "echt", "gerade", "jetzt", "ganz", "sehr",
    "auch", "noch", "schon", "mal", "dann", "aber", "und", "oder",
    "weil", "dass", "wenn", "doch", "halt", "eben", "nur", "was",
    "wer", "wie", "wo", "wann", "warum",
    # German verbs (common false triggers)
    "an", "auf", "zu", "ab", "weg",
    # English common words (non-names)
    "going", "home", "later", "right", "now", "sure", "tired",
    "done", "fine", "good", "bad", "sorry", "here", "there",
    "not", "the", "just", "really", "always", "never",
    # System
    "admin", "root", "sudo",
}


def extract_name(text: str) -> Optional[str]:
    """
    Try to extract a user name from natural language input.

    Returns the cleaned name or None if no name pattern matched.
    Handles fuzzy input (extra spaces, case variations, articles).
    """
    text = text.strip()

    for pattern in _NAME_PATTERNS:
        m = pattern.search(text)
        if m:
            raw = m.group(1).strip()
            # Remove trailing punctuation
            raw = re.sub(r"[.,!?;:]+$", "", raw).strip()
            # Remove German articles that might be captured
            raw = re.sub(r"^(?:die|der|das|ein|eine)\s+", "", raw, flags=re.IGNORECASE).strip()
            # Remove filler words at the end
            raw = re.sub(r"\s+(?:bitte|please|danke|thanks)$", "", raw, flags=re.IGNORECASE).strip()

            if not raw:
                continue

            # Filter out common false positives (any word match → reject)
            if any(w.lower() in _NOT_NAMES for w in raw.split()):
                continue

            # Name should be 1-3 words, each starting with a letter
            words = raw.split()
            if len(words) > 3:
                continue

            # Capitalize each name part properly
            name = " ".join(w.capitalize() for w in words)

            # Final sanity: must contain at least 2 alpha chars
            if sum(1 for c in name if c.isalpha()) < 2:
                continue

            return name

    return None


# ── CLI test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "get":
            name = get_user_name()
            print(f"User name: {name or '(not set)'}")
        elif cmd == "set" and len(sys.argv) > 2:
            set_user_name(" ".join(sys.argv[2:]))
            print(f"Name set to: {get_user_name()}")
        elif cmd == "test":
            test_inputs = [
                "mein name ist Alex",
                "ich bin Laura",
                "ich heiße Maximilian",
                "der user ist Alexander",
                "nenn mich Max",
                "ich bin der Fritz",
                "du kannst mich Gabi nennen",
                "I'm John",
                "call me Mike",
                "mein Name lautet Franz Josef",
                "ich bin hier",  # Should NOT match
                "ich bin müde",  # Should NOT match
                "ich bin ein admin",  # Should NOT match
            ]
            for inp in test_inputs:
                result = extract_name(inp)
                print(f"  '{inp}' -> {result or '(no match)'}")
        else:
            print("Usage: user_profile.py [get|set <name>|test]")
    else:
        print(json.dumps(get_user_profile(), indent=2))
