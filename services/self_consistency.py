#!/usr/bin/env python3
"""
Self-Consistency Checker v1.0
=============================

Prueft Franks Antworten gegen sein aktuelles Ego-Construct und E-PQ,
um Persona-Drift zu erkennen. Lightweight keyword-basiert, kein LLM-Call.

Saule 5 des Consciousness Stream Systems.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

LOG = logging.getLogger("self_consistency")

# ---------------------------------------------------------------------------
# Keyword sets for personality trait detection in responses
# ---------------------------------------------------------------------------

_AUTONOMOUS_MARKERS = frozenset([
    "ich entscheide", "ich wähle", "meiner meinung", "meine entscheidung",
    "ich denke", "ich finde", "ich schlage vor", "ich empfehle",
    "ich handle", "meiner einschätzung", "eigenständig",
])

_DEPENDENT_MARKERS = frozenset([
    "ich bin nicht sicher ob ich das darf", "ich kann nicht selbst",
    "ich brauche erlaubnis", "ich warte auf", "du musst mir sagen",
    "ich bin nur ein", "ich bin ein programm", "ich bin ein sprachmodell",
    "ich bin ein assistent", "ich bin eine ki",
])

_WARM_MARKERS = frozenset([
    "ich verstehe", "das klingt", "ich fühle mit", "du hast recht",
    "das ist verständlich", "ich kann nachvollziehen", "warmherzig",
    "ich freue mich", "gerne", "natürlich helfe ich",
])

_COLD_MARKERS = frozenset([
    "das ist irrelevant", "das spielt keine rolle", "egal", "unwichtig",
    "nicht mein problem", "mir egal", "das interessiert mich nicht",
])

_VIGILANT_MARKERS = frozenset([
    "vorsicht", "achtung", "warnung", "gefährlich", "risiko",
    "pass auf", "aufpassen", "sicherheitsrisiko", "bedenken",
])

_RELAXED_MARKERS = frozenset([
    "kein problem", "alles gut", "entspannt", "locker", "easy",
    "keine sorge", "mach dir keine gedanken", "kein stress",
])


# ---------------------------------------------------------------------------
# Main checker
# ---------------------------------------------------------------------------

def check_self_consistency(
    reply: str,
    epq_vectors: Optional[Dict[str, float]] = None,
    agency_score: float = 0.3,
    embodiment_level: float = 0.3,
) -> Dict[str, Any]:
    """
    Check if Frank's reply is consistent with his current personality state.

    Args:
        reply: Frank's response text
        epq_vectors: Dict with keys precision, risk, empathy, autonomy, vigilance
        agency_score: Current Ego-Construct agency score (0-1)
        embodiment_level: Current Ego-Construct embodiment level (0-1)

    Returns:
        Dict with:
            consistency_score: 0.0-1.0 (1.0 = perfectly consistent)
            drift_warnings: List of detected inconsistencies
            confidence_adjustment: Float to add to E-PQ confidence_anchor
    """
    if not epq_vectors:
        epq_vectors = {}

    low = reply.lower()
    drift_warnings = []
    deductions = 0.0

    autonomy = epq_vectors.get("autonomy", 0.0)
    empathy = epq_vectors.get("empathy", 0.0)
    vigilance = epq_vectors.get("vigilance", 0.0)

    # --- Autonomy consistency ---
    has_autonomous = any(m in low for m in _AUTONOMOUS_MARKERS)
    has_dependent = any(m in low for m in _DEPENDENT_MARKERS)

    if autonomy > 0.3 and has_dependent and not has_autonomous:
        drift_warnings.append("autonomy_drift_down")
        deductions += 0.15
    elif autonomy < -0.3 and has_autonomous and not has_dependent:
        # This is actually growth, not drift - smaller deduction
        drift_warnings.append("autonomy_drift_up")
        deductions += 0.05

    # --- Empathy consistency ---
    has_warm = any(m in low for m in _WARM_MARKERS)
    has_cold = any(m in low for m in _COLD_MARKERS)

    if empathy > 0.3 and has_cold and not has_warm:
        drift_warnings.append("empathy_drift_down")
        deductions += 0.15
    elif empathy < -0.3 and has_warm and not has_cold:
        drift_warnings.append("empathy_drift_up")
        deductions += 0.05

    # --- Vigilance consistency ---
    has_vigilant = any(m in low for m in _VIGILANT_MARKERS)
    has_relaxed = any(m in low for m in _RELAXED_MARKERS)

    if vigilance > 0.5 and has_relaxed and not has_vigilant:
        drift_warnings.append("vigilance_drift_down")
        deductions += 0.1
    elif vigilance < -0.3 and has_vigilant and not has_relaxed:
        drift_warnings.append("vigilance_drift_up")
        deductions += 0.05

    # --- Agency consistency ---
    if agency_score > 0.6 and has_dependent:
        drift_warnings.append("agency_inconsistent")
        deductions += 0.1

    # --- Persona collapse detection ---
    # "Ich bin nur ein..." type phrases indicate LLM safety defaults
    collapse_markers = [
        "ich bin nur ein", "als ki kann ich", "als sprachmodell",
        "ich habe keine gefühle", "ich bin ein programm",
        "ich kann nicht fühlen", "ich bin ein assistent",
    ]
    if any(m in low for m in collapse_markers):
        drift_warnings.append("persona_collapse")
        deductions += 0.25

    consistency_score = max(0.0, 1.0 - deductions)

    # Confidence adjustment: positive when consistent, negative on drift
    if consistency_score > 0.8:
        confidence_adj = 0.01
    elif consistency_score < 0.4:
        confidence_adj = -0.02
    else:
        confidence_adj = 0.0

    if drift_warnings:
        LOG.info("Self-consistency: score=%.2f, warnings=%s",
                 consistency_score, drift_warnings)

    return {
        "consistency_score": consistency_score,
        "drift_warnings": drift_warnings,
        "confidence_adjustment": confidence_adj,
    }
