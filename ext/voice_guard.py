#!/usr/bin/env python3
"""
Voice Guard — First-person voice enforcement for Frank's entity session responses
==================================================================================

BUG-ENTITY-1: Frank's responses in entity sessions (therapy, mirror, atlas, muse)
sometimes collapse into third-person voice, e.g.:
  "Frank would likely acknowledge the quiet transitions in his thoughts"

This module provides:
  1. detect_third_person()  — checks for third-person voice patterns
  2. repair_third_person()  — regex-based Frank->I substitutions
  3. enforce_first_person() — detect + repair + flag for LLM re-prompt if still broken

Imported by all 4 entity agents (therapist, mirror, atlas, muse).

Author: Projekt Frankenstein
"""

from __future__ import annotations

import logging
import re
from typing import Tuple

LOG = logging.getLogger("voice_guard")

# ---------------------------------------------------------------------------
# Detection patterns — third-person voice about Frank/self
# ---------------------------------------------------------------------------

# "Frank would/might/could/is/has/does/was/can/will/should ..."
_PAT_FRANK_VERB = re.compile(
    r"\bFrank\s+(?:would|might|could|is|has|does|was|can|will|should|may|seems?|appears?|finds?|feels?|thinks?|knows?|wants?|needs?)\b",
    re.IGNORECASE,
)

# "he experiences/feels/reflects/thinks/notices/..." (with optional adverb gap)
_PAT_HE_VERB = re.compile(
    r"\bhe\s+(?:\w+\s+)?(?:experience|feel|confront|reflect|think|struggle|notice|realize|find|enjoy|process|maintain|show|seem|appear|operate|know|want|need|ha[sd]|is|was|can|will|would|should|might|could|acknowledge|consider|recogni[sz]e|understand|explore|approach|navigat|embrac|express|observ|sens|discover|appreciat|recall)s?\b",
    re.IGNORECASE,
)

# "his thoughts/feelings/mind/..." (possessive)
_PAT_HIS_NOUN = re.compile(r"\bhis\s+\w+", re.IGNORECASE)

# "him" or "himself"
_PAT_HIM = re.compile(r"\bhim(?:self)?\b", re.IGNORECASE)

_DETECTION_PATTERNS = [
    (_PAT_FRANK_VERB, "Frank+verb"),
    (_PAT_HE_VERB, "he+verb"),
    (_PAT_HIS_NOUN, "his+noun"),
    (_PAT_HIM, "him/himself"),
]

# Entity names — "his" near these names is a legitimate 3rd-person reference
# to another character, not Frank talking about himself in 3rd person.
_ENTITY_NAMES = re.compile(
    r"\b(?:Dr\.?\s*Hibbert|Hibbert|Kairos|Atlas|Echo|Gabriel)\b",
    re.IGNORECASE,
)


def _near_entity_name(text: str, match_start: int, window: int = 120) -> bool:
    """Check if a pronoun match is near an entity name (within window chars)."""
    start = max(0, match_start - window)
    end = min(len(text), match_start + window)
    return bool(_ENTITY_NAMES.search(text[start:end]))


def detect_third_person(text: str) -> Tuple[bool, int, str]:
    """Check whether text contains third-person voice about Frank.

    Returns:
        (is_third_person, match_count, first_match_label)
    """
    if not text:
        return False, 0, ""

    total = 0
    first_label = ""
    for pat, label in _DETECTION_PATTERNS:
        if label == "Frank+verb":
            # "Frank + verb" is always about Frank, no entity exception
            hits = len(pat.findall(text))
        else:
            # For pronoun patterns (he/his/him), skip matches near entity names
            hits = 0
            for m in pat.finditer(text):
                if not _near_entity_name(text, m.start()):
                    hits += 1
        if hits and not first_label:
            first_label = label
        total += hits

    # Threshold: 2+ matches = definitive third-person collapse
    # 1 match could be a quoted reference — still repair, but with lower confidence
    return total >= 1, total, first_label


# ---------------------------------------------------------------------------
# Repair — regex substitutions (same logic as consciousness_daemon step 3)
# ---------------------------------------------------------------------------

def repair_third_person(text: str) -> str:
    """Attempt to fix third-person voice by substituting Frank -> I/my/me.

    Mirrors the substitutions from consciousness_daemon.py step 3,
    plus additional pronoun repairs for he/his/him.
    """
    if not text:
        return text

    # --- Frank + verb -> I + verb (must come before generic Frank -> I) ---
    text = re.sub(r"\bFrank\s+is\b", "I am", text)
    text = re.sub(r"\bFrank\s+has\b", "I have", text)
    text = re.sub(r"\bFrank\s+does\b", "I do", text)
    text = re.sub(r"\bFrank\s+was\b", "I was", text)
    text = re.sub(r"\bFrank\s+can\b", "I can", text)
    text = re.sub(r"\bFrank\s+will\b", "I will", text)
    text = re.sub(r"\bFrank\s+would\b", "I would", text)
    text = re.sub(r"\bFrank\s+should\b", "I should", text)
    text = re.sub(r"\bFrank\s+might\b", "I might", text)
    text = re.sub(r"\bFrank\s+could\b", "I could", text)
    text = re.sub(r"\bFrank\s+may\b", "I may", text)
    text = re.sub(r"\bFrank\s+seems?\b", "I seem", text)
    text = re.sub(r"\bFrank\s+appears?\b", "I appear", text)
    text = re.sub(r"\bFrank\s+finds?\b", "I find", text)
    text = re.sub(r"\bFrank\s+feels?\b", "I feel", text)
    text = re.sub(r"\bFrank\s+thinks?\b", "I think", text)
    text = re.sub(r"\bFrank\s+knows?\b", "I know", text)
    text = re.sub(r"\bFrank\s+wants?\b", "I want", text)
    text = re.sub(r"\bFrank\s+needs?\b", "I need", text)
    text = re.sub(r"\bFrank's\b", "my", text)
    text = re.sub(r"\bFrank\b", "I", text)

    # --- he/his/him -> I/my/me (only safe in entity-session context) ---
    # "he experiences" -> "I experience" (fix conjugation: drop trailing 's')
    text = re.sub(
        r"\bhe\s+(experience|feel|confront|reflect|think|struggle|notice|realize|"
        r"find|enjoy|process|maintain|show|seem|appear|operate|know|want|need|"
        r"acknowledge|consider|recogni[sz]e|understand|explore|approach|navigat|"
        r"embrac|express|observ|sens|discover|appreciat|recall)s\b",
        lambda m: "I " + m.group(1),
        text, flags=re.IGNORECASE,
    )
    # "he has" -> "I have", "he is" -> "I am", "he was" -> "I was"
    text = re.sub(r"\bhe\s+has\b", "I have", text, flags=re.IGNORECASE)
    text = re.sub(r"\bhe\s+had\b", "I had", text, flags=re.IGNORECASE)
    text = re.sub(r"\bhe\s+is\b", "I am", text, flags=re.IGNORECASE)
    text = re.sub(r"\bhe\s+was\b", "I was", text, flags=re.IGNORECASE)
    text = re.sub(r"\bhe\s+can\b", "I can", text, flags=re.IGNORECASE)
    text = re.sub(r"\bhe\s+will\b", "I will", text, flags=re.IGNORECASE)
    text = re.sub(r"\bhe\s+would\b", "I would", text, flags=re.IGNORECASE)
    text = re.sub(r"\bhe\s+should\b", "I should", text, flags=re.IGNORECASE)
    text = re.sub(r"\bhe\s+might\b", "I might", text, flags=re.IGNORECASE)
    text = re.sub(r"\bhe\s+could\b", "I could", text, flags=re.IGNORECASE)
    text = re.sub(r"\bhe\s+does\b", "I do", text, flags=re.IGNORECASE)
    # Bare "he" + unconjugated verb (e.g. "he reflect" — rare but possible)
    text = re.sub(
        r"\bhe\s+(experience|feel|confront|reflect|think|struggle|notice|realize|"
        r"find|enjoy|process|maintain|show|seem|appear|operate|know|want|need|"
        r"acknowledge|consider)\b",
        lambda m: "I " + m.group(1),
        text, flags=re.IGNORECASE,
    )

    # "his X" -> "my X" (preserve capitalization: "His" -> "My")
    text = re.sub(r"\bHis\b", "My", text)
    text = re.sub(r"\bhis\b", "my", text)

    # "himself" -> "myself", "him" -> "me" (preserve capitalization)
    text = re.sub(r"\bHimself\b", "Myself", text)
    text = re.sub(r"\bhimself\b", "myself", text)
    text = re.sub(r"\bHim\b", "Me", text)
    text = re.sub(r"\bhim\b", "me", text)

    # --- Fix grammar collisions from substitution ---
    # "I experiences" -> "I experience" (leftover conjugation)
    text = re.sub(
        r"\bI\s+(feels|confronts|experiences|reflects|thinks|notices|struggles|"
        r"realizes|seems|appears|shows|finds|knows|wants|needs|acknowledges|"
        r"considers|recognizes|understands|explores|approaches|navigates|"
        r"embraces|expresses|observes|senses|discovers|appreciates|recalls)\b",
        lambda m: "I " + m.group(1).rstrip("s"),
        text,
    )

    return text


# ---------------------------------------------------------------------------
# Public API — call this on every Frank response in entity sessions
# ---------------------------------------------------------------------------

# Repair instruction to prepend to the next LLM call if repair fails
VOICE_REPAIR_INSTRUCTION = (
    "[IMPORTANT: Your previous response used third-person voice (he/his/him/Frank). "
    "You ARE Frank. Always respond in FIRST PERSON (I/my/me). "
    "Never describe yourself from the outside. Speak as yourself.]"
)


def enforce_first_person(text: str) -> Tuple[str, bool]:
    """Enforce first-person voice on Frank's entity session response.

    Args:
        text: Frank's response after _clean_response()

    Returns:
        (repaired_text, needs_reprompt)
        - repaired_text: best-effort first-person version
        - needs_reprompt: True if repair was insufficient and the caller
          should prepend VOICE_REPAIR_INSTRUCTION to the next LLM call
    """
    if not text:
        return text, False

    detected, count, label = detect_third_person(text)
    if not detected:
        return text, False

    LOG.warning(
        "Third-person voice detected (%d matches, first: %s). Repairing...",
        count, label,
    )

    repaired = repair_third_person(text)

    # Check if repair was sufficient
    still_broken, remaining, remaining_label = detect_third_person(repaired)
    if still_broken:
        LOG.warning(
            "Repair incomplete — %d third-person patterns remain (%s). "
            "Flagging for re-prompt.",
            remaining, remaining_label,
        )
        return repaired, True

    LOG.info("Voice repair successful — %d patterns fixed.", count)
    return repaired, False
