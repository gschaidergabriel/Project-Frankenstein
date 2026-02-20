"""
User Preference Extractor — Pattern-based extraction from chat messages.

Phase 5a: Pure regex extraction (immediate, ~1ms per message).
Phase 5b: LLM-based extraction (deferred, controlled by feature flag).

Extracts preferences like:
  - "ich mag kein X" → dislikes: X
  - "mach immer X" → habit: X
  - "ich bevorzuge X" → prefers: X
  - "bitte nie X" → dislikes: X

Stores in user_preferences table in chat_memory.db.
"""

import logging
import re
from typing import List, Optional, Tuple

LOG = logging.getLogger("preference_extractor")

# Feature flag for LLM extractor (Phase 5b — enable after 1 week of regex data)
PREF_LLM_EXTRACTOR_ENABLED = False


def _normalize_value(v: str) -> str:
    """Normalize preference value: strip + lower + collapse whitespace."""
    return " ".join(v.strip().lower().split())


# ── Regex patterns for preference extraction ──

_PATTERNS: List[Tuple[str, re.Pattern, int]] = [
    # German: dislikes
    ("dislikes", re.compile(
        r"(?:ich\s+)(?:mag|moechte?|will)\s+(?:kein(?:e[nmrs]?)?|nicht?)\s+(.+?)(?:\.|!|$)",
        re.IGNORECASE,
    ), 1),
    ("dislikes", re.compile(
        r"(?:ich\s+)?hasse?\s+(.+?)(?:\.|!|$)",
        re.IGNORECASE,
    ), 1),
    ("dislikes", re.compile(
        r"(?:bitte\s+)?(?:nie(?:mals)?|niemals|auf keinen fall)\s+(.+?)(?:\.|!|$)",
        re.IGNORECASE,
    ), 1),
    ("dislikes", re.compile(
        r"(?:ich\s+)?(?:finde|find)\s+(.+?)\s+(?:nervig|doof|bloed|bloeed|schlecht|schrecklich|furchtbar|aetzend)",
        re.IGNORECASE,
    ), 1),

    # German: prefers (exclude negations like "mag kein/nicht")
    ("prefers", re.compile(
        r"(?:ich\s+)?(?:bevorzuge|praeferiere)\s+(?:lieber\s+)?(.+?)(?:\.|!|$)",
        re.IGNORECASE,
    ), 1),
    ("prefers", re.compile(
        r"(?:ich\s+)?(?:mag|moechte?|will)\s+(?:lieber\s+)(.+?)(?:\.|!|$)",
        re.IGNORECASE,
    ), 1),
    ("prefers", re.compile(
        r"(?:ich\s+)?(?:mag|liebe|finde)\s+(.+?)\s+(?:gut|toll|super|geil|genial|klasse|cool|nice)",
        re.IGNORECASE,
    ), 1),

    # German: habits
    ("habit", re.compile(
        r"(?:mach|tu|schreib|antworte|verwende|nutze|benutze)\s+(?:immer|grundsaetzlich|standardmaessig|normalerweise)\s+(.+?)(?:\.|!|$)",
        re.IGNORECASE,
    ), 1),
    ("habit", re.compile(
        r"(?:ich\s+)?(?:will|moechte?|wuensche)\s+(?:immer|grundsaetzlich)\s+(.+?)(?:\.|!|$)",
        re.IGNORECASE,
    ), 1),

    # English: dislikes
    ("dislikes", re.compile(
        r"(?:i\s+)?(?:don.?t\s+like|hate|dislike|can.?t\s+stand)\s+(.+?)(?:\.|!|$)",
        re.IGNORECASE,
    ), 1),
    ("dislikes", re.compile(
        r"(?:please\s+)?(?:never|don.?t\s+ever)\s+(.+?)(?:\.|!|$)",
        re.IGNORECASE,
    ), 1),

    # English: prefers
    ("prefers", re.compile(
        r"(?:i\s+)?(?:prefer|like|love|enjoy)\s+(.+?)(?:\.|!|$)",
        re.IGNORECASE,
    ), 1),

    # English: habits
    ("habit", re.compile(
        r"(?:always|usually|normally)\s+(.+?)(?:\.|!|$)",
        re.IGNORECASE,
    ), 1),
]

# Short-value filter: ignore extractions shorter than 3 chars
_MIN_VALUE_LEN = 3
# Max value length
_MAX_VALUE_LEN = 200


def extract_preferences(text: str) -> List[Tuple[str, str]]:
    """Extract (key, value) preference pairs from a user message.

    Returns list of (key, normalized_value) tuples.
    Fast: ~1ms per message (pure regex).
    """
    results = []
    seen_values = set()

    for key, pattern, group in _PATTERNS:
        match = pattern.search(text)
        if match:
            raw_value = match.group(group).strip()
            # Clean trailing punctuation
            raw_value = re.sub(r'[.!?,;:]+$', '', raw_value).strip()

            if len(raw_value) < _MIN_VALUE_LEN:
                continue
            if len(raw_value) > _MAX_VALUE_LEN:
                raw_value = raw_value[:_MAX_VALUE_LEN]

            normalized = _normalize_value(raw_value)
            if normalized and normalized not in seen_values:
                seen_values.add(normalized)
                results.append((key, normalized))

    return results
