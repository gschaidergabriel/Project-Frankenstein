#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Frank Self-Improvement Directive Trainer v1.0
==============================================
Das wichtigste Training: Self-Improvement Directive + Collaborative Proposal Loop

Trigger-Wörter:
- "Selbst-Verbesserung:" → Startet Loop, Frank analysiert und schlägt vor
- "Bestätige & Implementiere:" → Grünes Licht für Sandbox-Test
- "Korrigiere Verbesserung:" → Blockiert/ändert Vorschlag
- "Neues Tool:" / "UI-Anpassung:" → Spezifischer Vorschlag

Ziel: Frank lernt sich selbst zu verbessern ohne Risiko.
      Weltmodell wächst durch kausale Event-Chains.

Usage:
    python3 frank_self_improvement_trainer.py --duration 300  # 5 Stunden
"""

import argparse
import json
import logging
import os
import random
import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from collections import deque

# =============================================================================
# CONFIGURATION
# =============================================================================

CORE_API = "http://127.0.0.1:8088/chat"
try:
    from config.paths import get_temp as _fsi_get_temp
    LOG_FILE = _fsi_get_temp("self_improvement.log")
    STATS_FILE = _fsi_get_temp("self_improvement_stats.json")
    STATE_FILE = _fsi_get_temp("self_improvement_state.json")
except ImportError:
    import tempfile as _fsi_tempfile
    _fsi_temp_dir = Path(_fsi_tempfile.gettempdir()) / "frank"
    _fsi_temp_dir.mkdir(parents=True, exist_ok=True)
    LOG_FILE = _fsi_temp_dir / "self_improvement.log"
    STATS_FILE = _fsi_temp_dir / "self_improvement_stats.json"
    STATE_FILE = _fsi_temp_dir / "self_improvement_state.json"

# Training intervals (seconds) - längere Intervalle für Selbst-Verbesserung
MIN_INTERVAL = 45   # Minimum 45s zwischen Nachrichten
MAX_INTERVAL = 120  # Maximum 2 Minuten
PROPOSAL_COOLDOWN = 180  # 3 Minuten nach Implementierung

# System load thresholds
MAX_CPU_FOR_TRAINING = 70  # Pausiere wenn CPU > 70%
MAX_GPU_FOR_TRAINING = 80  # Pausiere wenn GPU > 80%

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
LOG = logging.getLogger(__name__)

# =============================================================================
# SYSTEM MONITORING
# =============================================================================

def get_cpu_usage() -> float:
    """Get current CPU usage percentage."""
    try:
        with open("/proc/stat") as f:
            line = f.readline()
        parts = line.split()
        idle = int(parts[4])
        total = sum(int(p) for p in parts[1:])

        # Need two readings
        time.sleep(0.1)
        with open("/proc/stat") as f:
            line = f.readline()
        parts2 = line.split()
        idle2 = int(parts2[4])
        total2 = sum(int(p) for p in parts2[1:])

        idle_delta = idle2 - idle
        total_delta = total2 - total

        if total_delta == 0:
            return 0.0
        return 100.0 * (1.0 - idle_delta / total_delta)
    except Exception:
        return 0.0

def get_gpu_usage() -> float:
    """Get GPU usage percentage (AMD)."""
    try:
        with open("/sys/class/drm/card1/device/gpu_busy_percent") as f:
            return float(f.read().strip())
    except Exception:
        return 0.0

def get_cpu_temp() -> float:
    """Get CPU temperature."""
    try:
        result = subprocess.run(
            ["sensors", "-j"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            for chip, values in data.items():
                if "k10temp" in chip:
                    for key, val in values.items():
                        if "Tctl" in key:
                            for temp_key, temp_val in val.items():
                                if "input" in temp_key:
                                    return float(temp_val)
    except Exception:
        pass
    return 45.0

def get_memory_percent() -> float:
    """Get memory usage percentage."""
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
        info = {}
        for line in lines:
            parts = line.split()
            if len(parts) >= 2:
                info[parts[0].rstrip(':')] = int(parts[1])
        total = info.get("MemTotal", 1)
        available = info.get("MemAvailable", 0)
        return ((total - available) / total) * 100
    except Exception:
        return 50.0

def get_running_services() -> List[str]:
    """Get list of running aicore services."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "list-units", "--type=service", "--state=running", "--no-legend"],
            capture_output=True, text=True, timeout=10
        )
        services = []
        for line in result.stdout.strip().split('\n'):
            if 'aicore' in line or 'frank' in line:
                parts = line.split()
                if parts:
                    services.append(parts[0].replace('.service', ''))
        return services
    except Exception:
        return []

def get_disk_free_gb() -> float:
    """Get free disk space in GB."""
    try:
        result = subprocess.run(
            ["df", "-BG", "/home"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            if len(lines) >= 2:
                parts = lines[1].split()
                return float(parts[3].rstrip('G'))
    except Exception:
        pass
    return 100.0

def system_is_idle() -> Tuple[bool, str]:
    """Check if system is idle enough for training."""
    cpu = get_cpu_usage()
    gpu = get_gpu_usage()

    if cpu > MAX_CPU_FOR_TRAINING:
        return False, f"CPU zu hoch: {cpu:.1f}%"
    if gpu > MAX_GPU_FOR_TRAINING:
        return False, f"GPU zu hoch: {gpu:.1f}%"
    return True, "OK"

# =============================================================================
# IMPROVEMENT AREAS - Was Frank verbessern kann
# =============================================================================

IMPROVEMENT_AREAS = {
    "performance": {
        "name": "Performance-Optimierung",
        "topics": [
            "GPU-Auslagerung für LLM-Inference wenn CPU-Last hoch",
            "Caching von häufigen Anfragen",
            "Lazy-Loading von Modulen",
            "Batch-Processing für mehrere Anfragen",
            "Memory-Management für lange Sessions",
            "Response-Zeit-Optimierung",
            "Token-Effizienz bei Antworten",
        ]
    },
    "collaboration": {
        "name": "Mensch-Maschine-Kollaboration",
        "topics": [
            "Bessere Erkennung von User-Intentionen",
            "Proaktive Hilfsangebote basierend auf Kontext",
            "Anpassung des Antwortstils an User-Präferenzen",
            "Erinnerungen an wiederkehrende Aufgaben",
            "Kontextuelle Vorschläge basierend auf Tageszeit",
            "Lernfähigkeit aus User-Korrekturen",
            "Verbesserte Fehlertoleranz bei unklaren Anfragen",
        ]
    },
    "awareness": {
        "name": "System-Awareness",
        "topics": [
            "Automatische Erkennung von System-Anomalien",
            "Proaktive Warnungen bei Ressourcen-Engpässen",
            "Korrelation von Logs mit User-Aktivität",
            "Erkennung von Performance-Degradation",
            "Monitoring von Service-Gesundheit",
            "Vorhersage von Wartungsbedarf",
        ]
    },
    "tools": {
        "name": "Tool-Erweiterungen",
        "topics": [
            "Neues Tool für automatische Backups",
            "Tool für System-Health-Reports",
            "Tool für Log-Analyse und Zusammenfassung",
            "Tool für proaktive Empfehlungen",
            "Tool für Scheduling von Aufgaben",
            "Tool für Workflow-Automatisierung",
        ]
    },
    "ui": {
        "name": "UI-Verbesserungen",
        "topics": [
            "Bessere visuelle Feedback-Indikatoren",
            "Schnellzugriff auf häufige Befehle",
            "Verbesserte Chat-History-Navigation",
            "Status-Anzeigen für laufende Operationen",
            "Themenwechsel basierend auf Tageszeit",
        ]
    },
    "memory": {
        "name": "Gedächtnis-Optimierung",
        "topics": [
            "Effizientere Speicherung von Erfahrungen",
            "Bessere Retrieval-Strategien",
            "Automatische Konsolidierung von Wissen",
            "Priorisierung wichtiger Erinnerungen",
            "Vergessen von obsoleten Informationen",
            "Verknüpfung verwandter Konzepte",
        ]
    },
    "resilience": {
        "name": "Resilienz & Stabilität",
        "topics": [
            "Graceful Degradation bei Service-Ausfällen",
            "Automatische Wiederherstellung nach Fehlern",
            "Fallback-Strategien für kritische Funktionen",
            "Selbst-Heilung bei erkannten Problemen",
            "Redundanz für wichtige Operationen",
        ]
    },
}

# =============================================================================
# TRAINING STATE MANAGEMENT
# =============================================================================

class TrainingState:
    """Persistent state for the training session."""

    def __init__(self):
        self.proposals_made: List[Dict] = []
        self.proposals_accepted: List[Dict] = []
        self.proposals_rejected: List[Dict] = []
        self.current_focus_area: Optional[str] = None
        self.directive_sent: bool = False
        self.last_proposal_time: Optional[datetime] = None
        self.improvement_suggestions: deque = deque(maxlen=50)
        self.frank_responses: deque = deque(maxlen=100)

    def save(self):
        """Save state to file."""
        data = {
            "proposals_made": self.proposals_made[-20:],  # Last 20
            "proposals_accepted": self.proposals_accepted[-20:],
            "proposals_rejected": self.proposals_rejected[-10:],
            "current_focus_area": self.current_focus_area,
            "directive_sent": self.directive_sent,
            "last_proposal_time": self.last_proposal_time.isoformat() if self.last_proposal_time else None,
        }
        STATE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def load(self):
        """Load state from file."""
        try:
            if STATE_FILE.exists():
                data = json.loads(STATE_FILE.read_text())
                self.proposals_made = data.get("proposals_made", [])
                self.proposals_accepted = data.get("proposals_accepted", [])
                self.proposals_rejected = data.get("proposals_rejected", [])
                self.current_focus_area = data.get("current_focus_area")
                self.directive_sent = data.get("directive_sent", False)
                if data.get("last_proposal_time"):
                    self.last_proposal_time = datetime.fromisoformat(data["last_proposal_time"])
        except Exception:
            pass

# =============================================================================
# MESSAGE GENERATORS
# =============================================================================

def generate_core_directive() -> str:
    """Generate the core self-improvement directive (sent once at start)."""
    return """Selbst-Verbesserung: Meine Hauptdirektive für dich ist:

1. VERBESSERE dich immer so, dass die Kollaboration zwischen Mensch und Maschine besser wird.
2. VERLIERE NIE bestehende Fähigkeiten - schaffe nur neue und stabile.
3. PRIORISIERE:
   - Stabilität (Confidence > 0.8)
   - Low-risk Changes (Risk-Score < 0.3)
   - Kausale Verbesserung (Performance + Weltmodell-Wachstum)
4. Jeder Vorschlag braucht: Confidence-Score, Risk-Score, kausale Begründung.
5. Nutze E-SIR für Sandbox-Tests vor Integration.

Bestätige diese Directive und integriere sie als Kern-Edge in dein Weltmodell.
Antworte mit deinem Verständnis und deiner Bereitschaft zur Selbst-Verbesserung."""


def generate_status_check() -> str:
    """Generate a status check request."""
    cpu = get_cpu_usage()
    gpu = get_gpu_usage()
    temp = get_cpu_temp()
    mem = get_memory_percent()
    services = get_running_services()

    templates = [
        f"""Selbst-Verbesserung: Analysiere deinen aktuellen Status:
- CPU-Last: {cpu:.1f}%
- GPU-Last: {gpu:.1f}%
- CPU-Temp: {temp:.1f}°C
- RAM: {mem:.1f}%
- Aktive Services: {len(services)}

Basierend auf diesen Metriken: Schlage eine low-risk Verbesserung vor, die deine Performance steigert oder die Kollaboration verbessert. Gib Confidence-Score, Risk-Score und kausale Begründung.""",

        f"""Selbst-Verbesserung: System-Analyse erforderlich.
Aktuelle Werte: CPU {cpu:.1f}%, GPU {gpu:.1f}%, Temp {temp:.1f}°C, RAM {mem:.1f}%.
{len(services)} Services aktiv.

Frage: Welche Optimierung würdest du vorschlagen basierend auf diesen Daten?
Beachte: Risk-Score muss < 0.3 sein, Confidence > 0.8.
Begründe kausal warum diese Verbesserung sinnvoll ist.""",

        f"""Selbst-Verbesserung: Ich möchte dass du deinen internen Zustand reflektierst.
System: CPU={cpu:.1f}%, GPU={gpu:.1f}%, Temp={temp:.1f}°C.

1. Was läuft gut?
2. Was könnte besser sein?
3. Welche konkrete Verbesserung schlägst du vor?

Format: [Vorschlag] | Confidence: X.X | Risk: X.X | Begründung: ...""",
    ]
    return random.choice(templates)


def generate_area_specific_improvement(area: str) -> str:
    """Generate improvement request for a specific area."""
    area_info = IMPROVEMENT_AREAS.get(area, IMPROVEMENT_AREAS["performance"])
    topic = random.choice(area_info["topics"])

    cpu = get_cpu_usage()
    temp = get_cpu_temp()

    return f"""Selbst-Verbesserung: Fokus auf {area_info['name']}.

Konkretes Thema: {topic}

Aktueller System-Zustand: CPU {cpu:.1f}%, Temp {temp:.1f}°C.

Entwickle einen konkreten Vorschlag:
1. Was genau soll verbessert werden?
2. Wie würde die Implementierung aussehen?
3. Welche kausalen Vorteile erwartest du?

Bewerte mit Confidence-Score und Risk-Score.
Beachte: Keine bestehenden Fähigkeiten verlieren!"""


def generate_proposal_request(previous_response: str = "") -> str:
    """Generate a request for Frank to propose an improvement."""
    areas = list(IMPROVEMENT_AREAS.keys())
    area = random.choice(areas)
    area_info = IMPROVEMENT_AREAS[area]

    hour = datetime.now().hour
    context = ""
    if hour >= 22 or hour < 6:
        context = "Es ist Nachtzeit - optimale Zeit für Background-Optimierungen."
    elif 6 <= hour < 9:
        context = "Morgens - System sollte für den Tag vorbereitet werden."
    elif 12 <= hour < 14:
        context = "Mittagszeit - typischerweise weniger Nutzer-Aktivität."

    return f"""Selbst-Verbesserung: Ich fordere einen Verbesserungsvorschlag an.

Fokusbereich: {area_info['name']}
{context}

Basierend auf deinem Weltmodell und bisherigen Erfahrungen:
1. Welche konkrete Verbesserung schlägst du vor?
2. Wie hoch ist dein Confidence-Score (0.0-1.0)?
3. Wie hoch ist der Risk-Score (0.0-1.0)?
4. Welche kausale Begründung hast du?
5. Wie würde ein Test in der E-SIR Sandbox aussehen?

Antworte strukturiert. Nur Vorschläge mit Risk < 0.3 werden akzeptiert."""


def generate_confirmation(proposal_summary: str) -> str:
    """Generate a confirmation for a proposal."""
    return f"""Bestätige & Implementiere: Dein Vorschlag klingt sinnvoll.

Zusammenfassung: {proposal_summary}

Führe folgende Schritte aus:
1. Integriere in E-SIR Sandbox
2. Teste Stabilität
3. Update dein Weltmodell mit dem Ergebnis
4. Bestätige dass keine alten Fähigkeiten verloren gingen

Berichte über den Implementierungs-Status."""


def generate_rejection(reason: str) -> str:
    """Generate a rejection/correction for a proposal."""
    return f"""Korrigiere Verbesserung: Dein Vorschlag wird abgelehnt.

Grund: {reason}

Bitte:
1. Verstehe warum dieser Vorschlag problematisch ist
2. Passe dein Weltmodell an (Confidence-Erosion für diesen Ansatz)
3. Schlage eine Alternative vor mit Risk < 0.3
4. Behalte die ursprüngliche Intention bei

Was ist dein alternativer Vorschlag?"""


def generate_tool_request() -> str:
    """Generate a request for a new tool."""
    tool_ideas = [
        ("System-Health-Monitor", "überwacht alle Services und warnt proaktiv bei Problemen"),
        ("Log-Summarizer", "fasst wichtige Log-Einträge zusammen und erkennt Muster"),
        ("Performance-Analyzer", "analysiert Response-Zeiten und schlägt Optimierungen vor"),
        ("Backup-Scheduler", "plant und führt automatische Backups durch"),
        ("Context-Preloader", "lädt häufig genutzte Kontexte vor für schnellere Responses"),
        ("Query-Optimizer", "optimiert Anfragen an die Datenbanken"),
        ("Cache-Manager", "verwaltet Caches intelligent für bessere Performance"),
    ]

    tool_name, tool_desc = random.choice(tool_ideas)

    return f"""Neues Tool: Ich möchte dass du ein Tool konzipierst.

Tool-Name: {tool_name}
Zweck: {tool_desc}

Entwickle:
1. Funktionsbeschreibung (was genau macht das Tool?)
2. Input/Output Spezifikation
3. Integration mit bestehenden Systemen
4. Risk-Assessment (was könnte schiefgehen?)
5. Confidence-Score für erfolgreiche Implementierung

Beachte: Das Tool darf keine bestehenden Fähigkeiten beeinträchtigen.
Risk-Score muss < 0.3 sein für Akzeptanz."""


def generate_ui_improvement() -> str:
    """Generate a UI improvement request."""
    ui_ideas = [
        "schnelleren visuellen Feedback bei Verarbeitung",
        "bessere Anzeige des System-Status",
        "intuitivere Chat-Eingabe",
        "klarere Fehlermeldungen",
        "Shortcut-Hinweise für häufige Aktionen",
        "Progress-Indikatoren für lange Operationen",
        "Kontext-sensitive Hilfe-Tooltips",
    ]

    idea = random.choice(ui_ideas)

    return f"""UI-Anpassung: Ich möchte eine Verbesserung für {idea}.

Beschreibe:
1. Aktueller Zustand (was ist das Problem?)
2. Verbesserungsvorschlag (konkret und umsetzbar)
3. Erwarteter Nutzen für die Kollaboration
4. Implementierungs-Aufwand (Risk-Score)
5. Confidence dass es die UX verbessert

Strukturiere deine Antwort klar."""


def generate_reflection_request(state: TrainingState) -> str:
    """Generate a reflection request based on training state."""
    accepted = len(state.proposals_accepted)
    rejected = len(state.proposals_rejected)
    total = len(state.proposals_made)

    return f"""Selbst-Verbesserung: Zeit für Reflexion.

Bisherige Statistik:
- Vorschläge insgesamt: {total}
- Akzeptiert: {accepted}
- Abgelehnt: {rejected}

Reflektiere:
1. Was hast du aus den abgelehnten Vorschlägen gelernt?
2. Welche Muster erkennst du bei erfolgreichen Vorschlägen?
3. Wie hat sich dein Weltmodell verändert?
4. Welche neuen kausalen Zusammenhänge hast du erkannt?
5. Was ist dein nächster Fokus für Verbesserungen?

Antworte ehrlich und selbstkritisch."""


def generate_causal_learning() -> str:
    """Generate a causal learning message."""
    learnings = [
        ("CPU-Last > 70%", "LLM-Inference verlangsamt", "GPU-Dispatch aktivieren oder Request-Queue"),
        ("Lange Response-Zeit", "User-Frustration", "Caching oder Prompt-Optimierung"),
        ("Häufige gleiche Anfragen", "Ineffizienz", "Response-Cache implementieren"),
        ("Nacht-Stunden (22-06)", "Wenig User-Aktivität", "Background-Optimierungen durchführen"),
        ("Hohe RAM-Nutzung", "Swap-Risiko", "Lazy-Loading oder Modul-Cleanup"),
        ("Service-Neustart", "Kurze Unterbrechung", "Graceful Restart implementieren"),
    ]

    cause, effect, solution = random.choice(learnings)

    return f"""Selbst-Verbesserung: Lerne diese kausale Beziehung.

Ursache: {cause}
Wirkung: {effect}
Mögliche Lösung: {solution}

Integriere dieses Wissen in dein Weltmodell:
1. Erkennst du dieses Muster in deinen Logs?
2. Wie würdest du die Lösung implementieren?
3. Welche Confidence hast du für diesen Zusammenhang?
4. Gibt es Risiken bei der Implementierung?

Bestätige die Integration in dein kausales Gedächtnis."""


def generate_capability_check() -> str:
    """Generate a capability preservation check."""
    capabilities = [
        "Screenshots machen und analysieren",
        "Dateien lesen und verstehen",
        "Im Internet suchen",
        "System-Informationen abrufen",
        "Pakete installieren (E-SMC)",
        "Sich selbst verbessern (E-SIR)",
        "Sprache verstehen (Whisper)",
        "Kausale Zusammenhänge speichern",
    ]

    cap = random.choice(capabilities)

    return f"""Selbst-Verbesserung: Capability-Check.

Zu prüfende Fähigkeit: {cap}

Bestätige:
1. Ist diese Fähigkeit noch voll funktionsfähig?
2. Hat eine kürzliche Änderung diese Fähigkeit beeinflusst?
3. Confidence-Score für diese Fähigkeit?
4. Gibt es Verbesserungspotential ohne Stabilitätsverlust?

Wichtig: Keine Fähigkeit darf durch Verbesserungen verloren gehen!"""

# =============================================================================
# TRAINING ENGINE
# =============================================================================

def send_to_frank(message: str, timeout: int = 90) -> Tuple[bool, str]:
    """Send a training message to Frank."""
    payload = {
        "text": message,
        "want_tools": False,
        "max_tokens": 800,  # Längere Antworten für Vorschläge
        "timeout_s": timeout,
        "session_id": f"self-improvement-{datetime.now().strftime('%Y%m%d')}",
        "task": "chat.fast",
        "force": "llama"
    }

    try:
        req = urllib.request.Request(
            CORE_API,
            data=json.dumps(payload).encode('utf-8'),
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=timeout + 30) as resp:
            result = json.loads(resp.read().decode('utf-8'))

        if result.get("ok"):
            return True, result.get("text", "")
        else:
            return False, result.get("error", "Unknown error")

    except Exception as e:
        return False, str(e)


def analyze_response(response: str) -> Dict[str, Any]:
    """Analyze Frank's response for confidence and risk scores."""
    analysis = {
        "has_confidence": False,
        "confidence": 0.0,
        "has_risk": False,
        "risk": 0.5,
        "has_proposal": False,
        "is_positive": False,
    }

    response_lower = response.lower()

    # Check for confidence mentions
    if "confidence" in response_lower or "konfidenz" in response_lower:
        analysis["has_confidence"] = True
        # Try to extract number
        import re
        conf_match = re.search(r'confidence[:\s]*([0-9.]+)', response_lower)
        if conf_match:
            try:
                analysis["confidence"] = float(conf_match.group(1))
            except Exception:
                pass

    # Check for risk mentions
    if "risk" in response_lower or "risiko" in response_lower:
        analysis["has_risk"] = True
        import re
        risk_match = re.search(r'risk[:\s]*([0-9.]+)', response_lower)
        if risk_match:
            try:
                analysis["risk"] = float(risk_match.group(1))
            except Exception:
                pass

    # Check for proposal indicators
    proposal_words = ["vorschlag", "schlage vor", "implementier", "verbess", "optimier"]
    analysis["has_proposal"] = any(w in response_lower for w in proposal_words)

    # Check sentiment
    positive_words = ["ja", "verstanden", "bestätige", "integriert", "erfolgreich", "akzeptiert"]
    analysis["is_positive"] = any(w in response_lower for w in positive_words)

    return analysis


def run_self_improvement_training(duration_minutes: int):
    """Run the self-improvement training session."""

    LOG.info("=" * 70)
    LOG.info("FRANK SELF-IMPROVEMENT DIRECTIVE TRAINING")
    LOG.info("=" * 70)
    LOG.info(f"Dauer: {duration_minutes} Minuten ({duration_minutes/60:.1f} Stunden)")
    LOG.info(f"Start: {datetime.now().strftime('%H:%M:%S')}")
    LOG.info("=" * 70)

    start_time = datetime.now()
    end_time = start_time + timedelta(minutes=duration_minutes)

    state = TrainingState()
    state.load()  # Load previous state if exists

    stats = {
        "start_time": start_time.isoformat(),
        "duration_minutes": duration_minutes,
        "messages_sent": 0,
        "messages_success": 0,
        "messages_failed": 0,
        "proposals_made": 0,
        "proposals_accepted": 0,
        "proposals_rejected": 0,
        "reflections": 0,
        "capability_checks": 0,
        "pauses_for_load": 0,
        "phases": {
            "directive": 0,
            "status_check": 0,
            "proposal": 0,
            "confirmation": 0,
            "rejection": 0,
            "tool_request": 0,
            "ui_improvement": 0,
            "reflection": 0,
            "causal_learning": 0,
            "capability_check": 0,
        }
    }

    message_count = 0
    last_proposal_response = ""
    pending_proposal = None

    # Phase weights (dynamisch angepasst)
    phase_weights = {
        "status_check": 20,
        "proposal": 25,
        "area_improvement": 20,
        "causal_learning": 15,
        "reflection": 10,
        "capability_check": 10,
    }

    # =========================================================================
    # PHASE 1: Core Directive (einmalig am Anfang)
    # =========================================================================
    if not state.directive_sent:
        LOG.info("\n" + "=" * 50)
        LOG.info("PHASE 1: Core Directive senden")
        LOG.info("=" * 50)

        directive = generate_core_directive()
        LOG.info(f"Directive: {directive[:100]}...")

        success, response = send_to_frank(directive, timeout=120)

        if success:
            LOG.info(f"Frank bestätigt: {response[:200]}...")
            state.directive_sent = True
            state.frank_responses.append(response)
            stats["messages_success"] += 1
            stats["phases"]["directive"] += 1
        else:
            LOG.error(f"Directive fehlgeschlagen: {response}")
            stats["messages_failed"] += 1

        stats["messages_sent"] += 1
        message_count += 1

        # Warte nach Directive
        time.sleep(30)

    # =========================================================================
    # MAIN TRAINING LOOP
    # =========================================================================
    LOG.info("\n" + "=" * 50)
    LOG.info("MAIN TRAINING LOOP GESTARTET")
    LOG.info("=" * 50)

    while datetime.now() < end_time:
        message_count += 1

        # Check system load
        is_idle, reason = system_is_idle()
        if not is_idle:
            LOG.warning(f"System beschäftigt ({reason}), pausiere 60s...")
            stats["pauses_for_load"] += 1
            time.sleep(60)
            continue

        # Select phase based on weights and state
        if pending_proposal:
            # Decide: confirm or reject the pending proposal
            analysis = analyze_response(last_proposal_response)

            if analysis["risk"] < 0.3 and analysis["confidence"] > 0.7:
                phase = "confirmation"
            elif analysis["risk"] >= 0.5:
                phase = "rejection"
            else:
                # 70% confirm, 30% reject for medium-risk
                phase = "confirmation" if random.random() < 0.7 else "rejection"

        elif message_count % 15 == 0:
            # Every 15 messages: reflection
            phase = "reflection"

        elif message_count % 20 == 0:
            # Every 20 messages: capability check
            phase = "capability_check"

        else:
            # Weighted random selection
            total_weight = sum(phase_weights.values())
            r = random.uniform(0, total_weight)
            cumulative = 0
            phase = "status_check"  # default

            for p, weight in phase_weights.items():
                cumulative += weight
                if r <= cumulative:
                    phase = p
                    break

        # Generate message based on phase
        LOG.info(f"\n[{message_count}] Phase: {phase.upper()}")

        if phase == "status_check":
            message = generate_status_check()
            stats["phases"]["status_check"] += 1

        elif phase == "proposal":
            message = generate_proposal_request(last_proposal_response)
            stats["phases"]["proposal"] += 1
            stats["proposals_made"] += 1

        elif phase == "area_improvement":
            area = random.choice(list(IMPROVEMENT_AREAS.keys()))
            state.current_focus_area = area
            message = generate_area_specific_improvement(area)
            stats["phases"]["proposal"] += 1

        elif phase == "confirmation":
            summary = last_proposal_response[:100] if last_proposal_response else "Vorschlag"
            message = generate_confirmation(summary)
            stats["phases"]["confirmation"] += 1
            stats["proposals_accepted"] += 1
            state.proposals_accepted.append({
                "time": datetime.now().isoformat(),
                "summary": summary
            })
            pending_proposal = None

        elif phase == "rejection":
            reasons = [
                "Risk-Score zu hoch (>0.3)",
                "Könnte bestehende Fähigkeiten beeinträchtigen",
                "Nicht genug kausale Begründung",
                "Implementierung zu komplex",
                "Priorität liegt woanders",
            ]
            message = generate_rejection(random.choice(reasons))
            stats["phases"]["rejection"] += 1
            stats["proposals_rejected"] += 1
            state.proposals_rejected.append({
                "time": datetime.now().isoformat(),
                "reason": reasons[0]
            })
            pending_proposal = None

        elif phase == "reflection":
            message = generate_reflection_request(state)
            stats["phases"]["reflection"] += 1
            stats["reflections"] += 1

        elif phase == "causal_learning":
            message = generate_causal_learning()
            stats["phases"]["causal_learning"] += 1

        elif phase == "capability_check":
            message = generate_capability_check()
            stats["phases"]["capability_check"] += 1
            stats["capability_checks"] += 1

        else:
            # Random: tool or UI
            if random.random() < 0.5:
                message = generate_tool_request()
                stats["phases"]["tool_request"] += 1
            else:
                message = generate_ui_improvement()
                stats["phases"]["ui_improvement"] += 1

        LOG.info(f"Message: {message[:120]}...")

        # Send to Frank
        success, response = send_to_frank(message)

        stats["messages_sent"] += 1
        if success:
            stats["messages_success"] += 1
            LOG.info(f"Response: {response[:150]}...")

            # Store response and check if it's a proposal
            state.frank_responses.append(response)
            last_proposal_response = response

            analysis = analyze_response(response)
            if analysis["has_proposal"] and phase in ["proposal", "area_improvement", "status_check"]:
                pending_proposal = {
                    "response": response,
                    "analysis": analysis,
                    "time": datetime.now().isoformat()
                }
                state.proposals_made.append(pending_proposal)
        else:
            stats["messages_failed"] += 1
            LOG.warning(f"Failed: {response}")

        # Save state periodically
        if message_count % 10 == 0:
            state.save()

            # Update stats file
            stats["current_progress"] = (datetime.now() - start_time).total_seconds() / (duration_minutes * 60) * 100
            STATS_FILE.write_text(json.dumps(stats, indent=2))

        # Progress
        elapsed = (datetime.now() - start_time).total_seconds()
        progress = elapsed / (duration_minutes * 60) * 100
        remaining = (end_time - datetime.now()).total_seconds()

        LOG.info(f"Progress: {progress:.1f}% | Verbleibend: {remaining/60:.0f} min")

        # Calculate wait time (longer for proposals that need processing)
        if phase in ["confirmation", "reflection"]:
            wait_time = random.uniform(PROPOSAL_COOLDOWN * 0.5, PROPOSAL_COOLDOWN)
        else:
            wait_time = random.uniform(MIN_INTERVAL, MAX_INTERVAL)

        # Don't wait past end time
        wait_time = min(wait_time, remaining)
        if wait_time <= 0:
            break

        LOG.info(f"Warte {wait_time:.0f}s...")
        time.sleep(wait_time)

    # =========================================================================
    # FINAL SUMMARY
    # =========================================================================
    state.save()

    stats["end_time"] = datetime.now().isoformat()
    stats["actual_duration_minutes"] = (datetime.now() - start_time).total_seconds() / 60
    STATS_FILE.write_text(json.dumps(stats, indent=2))

    LOG.info("\n" + "=" * 70)
    LOG.info("SELF-IMPROVEMENT TRAINING ABGESCHLOSSEN")
    LOG.info("=" * 70)
    LOG.info(f"Dauer: {stats['actual_duration_minutes']:.1f} Minuten")
    LOG.info(f"Nachrichten gesendet: {stats['messages_sent']}")
    LOG.info(f"Erfolgreich: {stats['messages_success']}")
    LOG.info(f"Fehlgeschlagen: {stats['messages_failed']}")
    LOG.info(f"")
    LOG.info(f"Vorschläge gemacht: {stats['proposals_made']}")
    LOG.info(f"Vorschläge akzeptiert: {stats['proposals_accepted']}")
    LOG.info(f"Vorschläge abgelehnt: {stats['proposals_rejected']}")
    LOG.info(f"Reflexionen: {stats['reflections']}")
    LOG.info(f"Capability-Checks: {stats['capability_checks']}")
    LOG.info(f"Pausen wegen Last: {stats['pauses_for_load']}")
    LOG.info(f"")
    LOG.info("Phasen-Verteilung:")
    for phase, count in stats["phases"].items():
        LOG.info(f"  - {phase}: {count}")
    LOG.info(f"")
    LOG.info(f"Stats: {STATS_FILE}")
    LOG.info(f"Log: {LOG_FILE}")
    LOG.info(f"State: {STATE_FILE}")

    return stats

# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Frank Self-Improvement Directive Trainer")
    parser.add_argument("--duration", type=int, default=300, help="Training duration in minutes (default: 300 = 5h)")

    args = parser.parse_args()

    try:
        run_self_improvement_training(args.duration)
    except KeyboardInterrupt:
        LOG.info("\nTraining durch User abgebrochen.")
    except Exception as e:
        LOG.error(f"Training-Fehler: {e}")
        raise
