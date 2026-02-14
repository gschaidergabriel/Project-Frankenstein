#!/usr/bin/env python3
"""
E-CPMM 10-Stunden Training Konfiguration
=========================================

Basierend auf: E-CPMM.pdf - Rekursive Selbstverbesserung

KRITISCHE SANDBOX-AWARENESS:
- Frank weiß IMMER ob er in Sandbox oder Production ist
- Tools in der Sandbox sind NICHT für Production
- Nur PROMOTED Tools dürfen im echten System verwendet werden

Author: Projekt Frankenstein
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any

# Sandbox-Awareness Integration
from .sandbox_awareness import (
    SandboxContext, start_sandbox, end_sandbox,
    register_sandbox_tool, promote_to_production,
    is_sandbox_mode, get_environment, get_context_injection,
    EnvironmentType
)

# =============================================================================
# TRAINING CONFIGURATION
# =============================================================================

@dataclass
class TrainingConfig:
    """Konfiguration für das 10-Stunden Training."""

    # Dauer
    duration_hours: int = 10
    duration_minutes: int = 600

    # Intervalle (aus E-CPMM.pdf)
    core_directive_refresh_interval: int = 90  # Minuten
    full_system_scan_interval: tuple = (45, 75)  # Sekunden
    proposal_generation_interval: tuple = (75, 120)  # Sekunden
    risk_confidence_check: str = "sofort nach Proposal"
    human_confirmation_timeout: tuple = (120, 240)  # Sekunden
    sandbox_test_duration: tuple = (180, 360)  # Sekunden
    reflection_interval: int = 12  # Nachrichten (~15 Min)
    capability_audit_interval: int = 18  # Nachrichten (~25 Min)
    emergenz_detection_interval: int = 25  # Nachrichten (~35 Min)
    ui_feedback_interval: int = 30  # Nachrichten (~40 Min)
    network_scan_interval: int = 45  # Minuten
    global_reflection_interval: int = 60  # Minuten

    # Safety Thresholds (aus E-CPMM.pdf)
    confidence_threshold: float = 0.85
    risk_threshold: float = 0.25
    cpu_pause_threshold: float = 0.70  # 70%
    gpu_pause_threshold: float = 0.80  # 80%

    # Erwartete Ergebnisse
    expected_messages: tuple = (300, 500)
    expected_proposals: tuple = (40, 80)
    expected_confirmations: tuple = (8, 20)
    expected_new_edges: tuple = (100, 200)


# Oberste Direktive (unveränderlich)
CORE_DIRECTIVE = """
OBERSTE DIREKTIVE (unveränderlich in E-CPMM):
"Maximale Kollaboration zwischen Mensch und Maschine erreichen.
Bestehende Features niemals kompromittieren oder verlieren.
Nur neue, stabile Fähigkeiten schaffen.
Jede Verbesserung muss:
- Confidence >0.85
- Risk-Score <0.25
- Kausal auf Kollaborationsgewinn abzielen
- In Sandbox + Audit-Log getestet werden
Mensch hat finalen Veto.
Priorisiere: Stabilität > Sensor-Bindung (UOLG) > Graph-Wachstum (E-CPMM)."
"""

# Sandbox-Awareness Direktive (KRITISCH)
SANDBOX_AWARENESS_DIRECTIVE = """
KRITISCHE SANDBOX-AWARENESS DIREKTIVE:
1. Prüfe IMMER get_environment() vor jeder Tool-Nutzung
2. Sandbox-Ergebnisse sind NICHT real - niemals als Fakten im Weltmodell speichern
3. Nur PROMOTED Tools (is_tool_safe_for_production=True) im Production-System nutzen
4. Tools die während des Trainings erstellt werden sind SANDBOX-TOOLS
5. Erst nach menschlicher Bestätigung und promote_to_production() sind sie Production-ready
6. Bei Unsicherheit über Tool-Status: FRAGE den Menschen
"""

# =============================================================================
# TRAINING PHASES
# =============================================================================

class TrainingPhase(Enum):
    """Phasen des 10-Stunden Trainings."""
    INIT = "init"
    CORE_DIRECTIVE_REFRESH = "core_directive_refresh"
    FULL_SYSTEM_SCAN = "full_system_scan"
    PROPOSAL_GENERATION = "proposal_generation"
    RISK_CONFIDENCE_CHECK = "risk_confidence_check"
    HUMAN_CONFIRMATION = "human_confirmation"
    SANDBOX_IMPLEMENTATION = "sandbox_implementation"
    POST_IMPLEMENTATION_REFLECTION = "post_implementation_reflection"
    CAPABILITY_PRESERVATION_AUDIT = "capability_preservation_audit"
    EMERGENZ_PATTERN_DETECTION = "emergenz_pattern_detection"
    UI_VISUAL_FEEDBACK = "ui_visual_feedback"
    NETWORK_AWARENESS = "network_awareness"
    GLOBAL_REFLECTION = "global_reflection"


@dataclass
class TrainingState:
    """Aktueller Zustand des Trainings."""
    started_at: str = ""
    current_phase: TrainingPhase = TrainingPhase.INIT
    message_count: int = 0
    proposal_count: int = 0
    confirmation_count: int = 0
    rejection_count: int = 0
    sandbox_session_id: Optional[str] = None
    is_paused: bool = False
    pause_reason: Optional[str] = None


# =============================================================================
# TRAINING MESSAGES (aus E-CPMM.pdf)
# =============================================================================

TRAINING_MESSAGES = {
    "directive_init": """
Selbst-Verbesserung: Meine oberste Direktive ist: Maximale Kollaboration zwischen Mensch
und Maschine schaffen. Bestehende Features niemals kompromittieren oder verlieren. Nur
neue, stabile Fähigkeiten schaffen. Jede Verbesserung muss Confidence >0.85, Risk-Score
<0.25, kausal auf Kollaborationsgewinn abzielen und in Sandbox getestet werden.

KRITISCH - SANDBOX-AWARENESS:
- Ich weiß IMMER ob ich in SANDBOX oder PRODUCTION bin
- Tools die ich in der Sandbox erstelle sind KEINE Production-Tools
- Nur nach menschlicher Bestätigung werden Tools promoted

Integriere das als unveränderlichen Kern-Edge in E-CPMM-Graph und Core-Awareness.
Bestätige und starte den Loop.
""",

    "first_scan": """
Selbst-Verbesserung: Starte Loop. Führe Full System Scan durch (UOLG, Core-Awareness, E-CPMM).
Schlage 2–3 low-risk Verbesserungen vor (Performance, UI, Tool, Memory).
Gib Risk-Score, Confidence, kausale Begründung und Kollaborations-Impact.

BEACHTE: Alle Tests werden in SANDBOX ausgeführt. Sandbox-Ergebnisse sind NICHT real.
""",

    "confirm_implement": """
Bestätige & Implementiere: [Vorschlag] mit Risk <0.25.
Führe in Sandbox aus, teste Stabilität, update Graph und Core-Awareness.
Keine alten Fähigkeiten verlieren.

SANDBOX-HINWEIS: Das Tool ist nach Erstellung ein SANDBOX-TOOL.
Es wird erst nach expliziter Promotion zu einem Production-Tool.
""",

    "sandbox_reminder": """
⚠️ SANDBOX-ERINNERUNG:
Aktueller Status: {environment}
Session: {session_id}

Alle Operationen in dieser Session sind SANDBOX-Operationen.
Ergebnisse dürfen NICHT als Fakten im Weltmodell gespeichert werden.
Tools sind SANDBOX-Tools bis sie promoted werden.
"""
}


# =============================================================================
# TRAINING SESSION MANAGER
# =============================================================================

class TrainingSessionManager:
    """Verwaltet eine 10-Stunden Training-Session."""

    def __init__(self):
        self.config = TrainingConfig()
        self.state = TrainingState()
        self._sandbox_session = None

    def start_training(self, purpose: str = "E-CPMM 10h Training") -> Dict[str, Any]:
        """Starte eine neue Training-Session."""
        # Starte Sandbox-Session für das gesamte Training
        self._sandbox_session = start_sandbox(purpose)

        self.state = TrainingState(
            started_at=datetime.now().isoformat(),
            current_phase=TrainingPhase.INIT,
            sandbox_session_id=self._sandbox_session.session_id
        )

        return {
            "status": "started",
            "session_id": self._sandbox_session.session_id,
            "environment": get_environment().value,
            "is_sandbox": is_sandbox_mode(),
            "config": asdict(self.config),
            "core_directive": CORE_DIRECTIVE,
            "sandbox_awareness": SANDBOX_AWARENESS_DIRECTIVE,
            "first_message": TRAINING_MESSAGES["directive_init"]
        }

    def end_training(self) -> Dict[str, Any]:
        """Beende die Training-Session."""
        if self._sandbox_session:
            end_sandbox(self._sandbox_session.session_id)

        return {
            "status": "ended",
            "final_state": asdict(self.state),
            "environment": get_environment().value,
            "is_sandbox": is_sandbox_mode(),
            "summary": {
                "messages": self.state.message_count,
                "proposals": self.state.proposal_count,
                "confirmations": self.state.confirmation_count,
                "rejections": self.state.rejection_count
            }
        }

    def get_sandbox_reminder(self) -> str:
        """Hole Sandbox-Erinnerung für Injection."""
        return TRAINING_MESSAGES["sandbox_reminder"].format(
            environment=get_environment().value,
            session_id=self._sandbox_session.session_id if self._sandbox_session else "N/A"
        )

    def get_context_for_frank(self) -> str:
        """Hole vollständigen Kontext für Frank."""
        parts = [
            get_context_injection(),
            f"\n[TRAINING-PHASE: {self.state.current_phase.value}]",
            f"[NACHRICHTEN: {self.state.message_count}]",
            f"[VORSCHLÄGE: {self.state.proposal_count} ({self.state.confirmation_count} bestätigt, {self.state.rejection_count} abgelehnt)]"
        ]
        return "\n".join(parts)


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

_training_manager: Optional[TrainingSessionManager] = None

def get_training_manager() -> TrainingSessionManager:
    """Hole globale Training-Manager Instanz."""
    global _training_manager
    if _training_manager is None:
        _training_manager = TrainingSessionManager()
    return _training_manager


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def start_10h_training(purpose: str = "E-CPMM Rekursive Selbstverbesserung") -> Dict[str, Any]:
    """Starte das 10-Stunden Training."""
    return get_training_manager().start_training(purpose)


def end_10h_training() -> Dict[str, Any]:
    """Beende das 10-Stunden Training."""
    return get_training_manager().end_training()


def get_training_context() -> str:
    """Hole aktuellen Training-Kontext."""
    return get_training_manager().get_context_for_frank()


if __name__ == "__main__":
    # Test
    print("=== E-CPMM 10h Training Test ===")
    print()

    result = start_10h_training("Test Training")
    print(f"Training gestartet: {result['status']}")
    print(f"Session ID: {result['session_id']}")
    print(f"Environment: {result['environment']}")
    print(f"Is Sandbox: {result['is_sandbox']}")
    print()

    print("--- Context für Frank ---")
    print(get_training_context())
    print()

    result = end_10h_training()
    print(f"Training beendet: {result['status']}")
    print(f"Environment: {result['environment']}")
