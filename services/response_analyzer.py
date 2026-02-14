#!/usr/bin/env python3
"""
Response Analyzer — Output-Feedback für Franks Bewusstsein
==========================================================

Analysiert Franks eigene Antworten (keyword-basiert, kein LLM-Call)
und gibt Event-Types zurück, die E-PQ und Ego-Construct aktualisieren.

Teil des Consciousness Stream Systems (Säule 2: Output-Feedback-Loop).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Keyword-Listen (Deutsch + Englisch, lowercase-Matching)
# ---------------------------------------------------------------------------

_CONFIDENCE_HIGH = {
    "sicher", "definitiv", "eindeutig", "bestimmt", "garantiert",
    "klar", "offensichtlich", "zweifellos", "natuerlich", "natürlich",
    "selbstverstaendlich", "auf jeden fall", "genau", "exakt",
    "ich weiss", "ich weiß", "das ist", "das bedeutet",
}

_CONFIDENCE_LOW = {
    "vielleicht", "vermutlich", "wahrscheinlich", "koennte", "könnte",
    "moeglicherweise", "möglicherweise", "denke ich", "glaube ich",
    "ich bin mir nicht sicher", "schwer zu sagen", "eventuell",
    "keine ahnung", "weiss nicht", "weiß nicht", "nicht sicher",
    "schwierig", "unklar", "unsicher",
}

_CREATIVE_MARKERS = {
    "stell dir vor", "wie ein", "als ob", "metaphorisch",
    "bildlich", "symbolisch", "poetisch", "imagine",
    "lass mich dir zeigen", "quasi", "sozusagen",
    "im uebertragenen sinne", "im übertragenen sinne",
}

_EMOTIONAL_MARKERS = {
    "ich fuehle", "ich fühle", "ich empfinde", "das beruehrt",
    "das berührt", "es macht mich", "freut mich", "aergert",
    "ärgert", "traurig", "gluecklich", "glücklich", "frustriert",
    "zufrieden", "stolz", "neugierig", "aufgeregt", "besorgt",
    "warmherzig", "dankbar",
}

_TECHNICAL_MARKERS = {
    "cpu", "ram", "gpu", "algorithmus", "funktion", "code",
    "programmier", "system", "prozess", "datenbank", "api",
    "server", "service", "thread", "debug", "error", "log",
    "speicher", "netzwerk", "konfiguration", "parameter",
}

_EMPATHETIC_MARKERS = {
    "ich verstehe", "das klingt", "das muss", "fuer dich", "für dich",
    "ich kann nachvollziehen", "das ist schwer", "ich hoere",
    "ich höre", "du hast recht", "das ist verstaendlich",
    "das ist verständlich", "es tut mir", "das tut mir",
}


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

def analyze_response(reply: str, user_input: str = "") -> Dict[str, Any]:
    """
    Analyze Frank's own response for personality feedback.

    Returns a dict with:
        event_type: str — E-PQ event type
        sentiment: str — "confident" | "uncertain" | "neutral"
        tone: str — "technical" | "creative" | "emotional" | "empathetic" | "neutral"
        verbosity: str — "concise" | "moderate" | "verbose"
        confidence_score: float — 0.0-1.0
        creative: bool
        emotional: bool
        empathetic: bool
        technical: bool
    """
    low = reply.lower()
    reply_len = len(reply)

    # --- Confidence ---
    conf_high = sum(1 for m in _CONFIDENCE_HIGH if m in low)
    conf_low = sum(1 for m in _CONFIDENCE_LOW if m in low)
    if conf_high > conf_low + 1:
        sentiment = "confident"
        confidence_score = min(1.0, 0.5 + conf_high * 0.1)
    elif conf_low > conf_high + 1:
        sentiment = "uncertain"
        confidence_score = max(0.0, 0.5 - conf_low * 0.1)
    else:
        sentiment = "neutral"
        confidence_score = 0.5

    # --- Tone detection ---
    creative = any(m in low for m in _CREATIVE_MARKERS)
    emotional = any(m in low for m in _EMOTIONAL_MARKERS)
    empathetic = any(m in low for m in _EMPATHETIC_MARKERS)
    technical = any(m in low for m in _TECHNICAL_MARKERS)

    if creative:
        tone = "creative"
    elif emotional:
        tone = "emotional"
    elif empathetic:
        tone = "empathetic"
    elif technical:
        tone = "technical"
    else:
        tone = "neutral"

    # --- Verbosity ---
    if reply_len < 80:
        verbosity = "concise"
    elif reply_len < 400:
        verbosity = "moderate"
    else:
        verbosity = "verbose"

    # --- Determine E-PQ event type ---
    if sentiment == "confident" and creative:
        event_type = "self_creative"
    elif sentiment == "confident":
        event_type = "self_confident"
    elif sentiment == "uncertain":
        event_type = "self_uncertain"
    elif empathetic:
        event_type = "self_empathetic"
    elif technical:
        event_type = "self_technical"
    else:
        event_type = "self_neutral"

    return {
        "event_type": event_type,
        "sentiment": sentiment,
        "tone": tone,
        "verbosity": verbosity,
        "confidence_score": confidence_score,
        "creative": creative,
        "emotional": emotional,
        "empathetic": empathetic,
        "technical": technical,
        "response_length": reply_len,
    }
