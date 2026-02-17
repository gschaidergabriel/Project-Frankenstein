"""
Action Intent Detector — detects when Frank proposes an agentic action.

Scans Frank's response for parenthetical proposals at the end that require
tool access (fetch URLs, search web, analyze files, etc.).

This detector does NOT change Frank's behavior — it only identifies when
Frank's emergent parenthetical suggestions are actionable.

Pure function, no LLM, no state — same pattern as response_analyzer.py.
"""

import re
from typing import Optional, Dict

# ---------------------------------------------------------------------------
# Parenthetical extraction: find the last parenthetical block in the response
# ---------------------------------------------------------------------------
# Matches text in parentheses near the end of the response.
# Allows nested parentheses (e.g. "(would you mind if I look into AGI (artificial general intelligence)?)")
_TRAILING_PAREN_RE = re.compile(
    r"\((.{20,500})\)\s*$",
    re.DOTALL,
)

# ---------------------------------------------------------------------------
# Agentic action verbs (bilingual) — things that need tool access
# ---------------------------------------------------------------------------
_AGENTIC_VERBS_EN = re.compile(
    r"\b(fetch|search|look\s+(?:up|into|for)|find|retrieve|download|"
    r"browse|scan|analyze|check|read|summarize|research|"
    r"install|open|run|execute|create|write|build|"
    r"take\s+a\s+(?:look|peek)|dive\s+(?:into|deeper)|"
    r"pull\s+up|look\s+(?:through|at)|go\s+through|"
    r"explore|investigate|gather|collect|compile|"
    r"grab|get|access|review|examine|inspect)\b",
    re.IGNORECASE,
)

_AGENTIC_VERBS_DE = re.compile(
    r"\b(abrufen|suchen|nachschauen|herausfinden|laden|"
    r"herunterladen|durchsuchen|analysieren|prüfen|prufen|checken|"
    r"lesen|zusammenfassen|recherchieren|öffnen|oeffnen|"
    r"installieren|ausführen|ausfuehren|erstellen|schreiben|"
    r"anschauen|ansehen|holen|scannen|untersuchen|"
    r"sammeln|zusammentragen|einlesen)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Offer/proposal framing patterns — Frank offering to do something
# ---------------------------------------------------------------------------
_OFFER_PATTERNS = re.compile(
    r"\b("
    # English offers
    r"shall\s+I|should\s+I|would\s+you\s+(?:like|mind|want)\s+(?:me\s+to|if\s+I)|"
    r"I\s+(?:can|could|might|shall|should|will|'ll|'d\s+like\s+to)|"
    r"let\s+me|want\s+me\s+to|if\s+you(?:'d)?\s+like|"
    r"mind\s+if\s+I|how\s+about\s+I|"
    # German offers
    r"soll\s+ich|darf\s+ich|kann\s+ich|könnte\s+ich|koennte\s+ich|"
    r"möchtest\s+du|moechtest\s+du|willst\s+du|"
    r"wenn\s+du\s+(?:möchtest|willst|magst)"
    r")\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# NON-agentic patterns — just remarks, observations, meta-commentary
# These should NOT trigger "do this"
# ---------------------------------------------------------------------------
_REMARK_PATTERNS = re.compile(
    r"\b("
    r"just\s+(?:a\s+)?(?:thought|observation|note|reminder|saying|kidding)|"
    r"no\s+pun\s+intended|pun\s+intended|"
    r"if\s+you\s+know\s+what\s+I\s+mean|"
    r"figuratively|metaphorically|so\s+to\s+speak|in\s+a\s+sense|"
    r"nur\s+so\s+(?:ein|eine)|"
    r"spaß\s+beiseite|spass\s+beiseite|kleiner\s+scherz"
    r")\b",
    re.IGNORECASE,
)


def detect_parenthetical_action(reply: str) -> Optional[Dict[str, str]]:
    """
    Detect if Frank's response ends with a parenthetical that proposes
    an agentic action (something requiring tool access).

    Args:
        reply: Frank's full response text

    Returns:
        Dict with keys if agentic action detected:
            parenthetical: str  — the text inside the parentheses
            goal: str           — reconstructed goal for agentic execution
        None if no actionable parenthetical found.
    """
    if not reply or len(reply) < 30:
        return None

    # Only look at the last 600 chars for efficiency
    tail = reply[-600:]

    m = _TRAILING_PAREN_RE.search(tail)
    if not m:
        return None

    paren_text = m.group(1).strip()

    # Skip if it's just a remark/observation (not an action proposal)
    if _REMARK_PATTERNS.search(paren_text):
        return None

    # Must contain an offer pattern (Frank proposing to do something)
    if not _OFFER_PATTERNS.search(paren_text):
        return None

    # Must contain at least one agentic verb (action that needs tools)
    has_en_verb = _AGENTIC_VERBS_EN.search(paren_text)
    has_de_verb = _AGENTIC_VERBS_DE.search(paren_text)

    if not has_en_verb and not has_de_verb:
        return None

    # Build a goal from the parenthetical
    # Strip leading "Also, " or "By the way, " etc.
    goal = re.sub(
        r"^(?:also,?\s*|by\s+the\s+way,?\s*|übrigens,?\s*|nebenbei,?\s*)",
        "", paren_text, flags=re.IGNORECASE,
    ).strip()

    # Capitalize first letter
    if goal:
        goal = goal[0].upper() + goal[1:]

    # Remove trailing question mark (it's a directive now)
    goal = goal.rstrip("?").strip()

    return {
        "parenthetical": paren_text,
        "goal": goal,
    }
