"""
Capabilities Registry -- centralized capability knowledge for Frank.

Provides overlay-friendly access to Frank's capability registry.
Source of truth: personality.self_knowledge.CAPABILITY_MAP (extended here).
"""

try:
    from personality.self_knowledge import CAPABILITY_MAP, CORE_IDENTITY
    _SK_AVAILABLE = True
except ImportError:
    _SK_AVAILABLE = False
    CAPABILITY_MAP = {}
    CORE_IDENTITY = {}


# Capabilities that may be missing from the personality module
OVERLAY_CAPABILITIES = {
    "system_control": {
        "name": "System-Steuerung",
        "description": "WiFi, Bluetooth, Audio, Display, Drucker, Datei-Organisation mit Bestaetigungssystem",
    },
    "package_management": {
        "name": "Paket-Management",
        "description": "Software installieren/entfernen via apt, pip, snap, flatpak mit Sicherheitslimits",
    },
    "monitoring": {
        "name": "System-Monitoring (ASRS)",
        "description": "CPU/GPU/Memory/Disk/Thermal/I/O Echtzeit-Ueberwachung mit 4-Stufen-Eskalation",
    },
    "auto_repair": {
        "name": "Auto-Reparatur",
        "description": "Automatische Diagnose und Reparatur von Systemproblemen (mit Benutzer-Genehmigung)",
    },
    "display_intelligence": {
        "name": "Display Intelligence (ADI)",
        "description": "Multi-Monitor-Profile und adaptive Layout-Konfiguration",
    },
    "wallpaper_control": {
        "name": "Wallpaper-Steuerung",
        "description": "Live-Wallpaper starten/stoppen mit Event-Reaktionen",
    },
    "network_intelligence": {
        "name": "Netzwerk-Intelligenz (Sentinel)",
        "description": "Geraete-Erkennung, Port-Scanning, ARP-Spoofing-Erkennung, Sicherheits-Analyse",
    },
    "voice_control": {
        "name": "Sprach-Steuerung",
        "description": "Wake-Word (Hey Frank), Push-to-Talk, Text-to-Speech (Thorsten-Stimme)",
    },
    "gaming_mode": {
        "name": "Gaming-Modus",
        "description": "Automatische Spielerkennung, Ressourcen-Optimierung, Anti-Cheat-Schutz",
    },
    "personality_system": {
        "name": "Persoenlichkeit (E-PQ)",
        "description": "Dynamisches Temperament und Stimmungs-Evolution ueber Zeit",
    },
    "self_improvement": {
        "name": "Selbst-Verbesserung (Genesis)",
        "description": "Kontrollierte Selbstverbesserung mit Sandbox-Testing und Benutzer-Genehmigung",
    },
    "experience_memory": {
        "name": "Erfahrungsgedaechtnis",
        "description": "Eigenes Weltmodell mit kausaler Mustererkennung und Lernen aus Erfahrungen",
    },
    "url_fetching": {
        "name": "URL-Abruf",
        "description": "Webseiten-Inhalte direkt abrufen und Text extrahieren (fetch URL, lies Seite)",
    },
    "rss_feeds": {
        "name": "RSS/Atom-Feeds",
        "description": "Nachrichten-Feeds lesen, aktuelle Headlines und Artikel abrufen",
    },
    "system_actions": {
        "name": "System-Aktionen",
        "description": "Echte System-Veraenderungen: Pakete, Apps, Dateien, Services, sysctl/gsettings. Letztes Guardrail: Kein Root (bewusstes Design).",
    },
    "skill_system": {
        "name": "Skill/Plugin-System",
        "description": "Erweiterbare Skills (native Python + OpenClaw). Neue Skills per Marketplace installierbar.",
    },
}


def get_all_capabilities():
    """Get merged capability map (personality + overlay extensions)."""
    merged = {}
    if _SK_AVAILABLE:
        for key, val in CAPABILITY_MAP.items():
            merged[key] = val
    merged.update(OVERLAY_CAPABILITIES)
    return merged


def get_capabilities_summary():
    """Generate human-readable capabilities summary in German."""
    caps = get_all_capabilities()
    lines = []
    for key, info in caps.items():
        name = info.get("name", key)
        desc = info.get("description", "")
        lines.append(f"- {name}: {desc}")

    # Append installed skill names dynamically
    try:
        import sys
        try:
            from config.paths import AICORE_ROOT as _AICORE_ROOT
        except ImportError:
            from pathlib import Path as _Path
            _AICORE_ROOT = _Path("/home/ai-core-node/aicore/opt/aicore")
        sys.path.insert(0, str(_AICORE_ROOT))
        from skills import get_skill_registry
        skills = get_skill_registry().list_all()
        if skills:
            skill_names = [s.name for s in skills]
            lines.append(f"\nInstallierte Skills ({len(skills)}): {', '.join(skill_names)}")
            lines.append("Neue Skills installierbar aus dem OpenClaw Marketplace.")
    except Exception:
        pass

    return "Meine Faehigkeiten:\n\n" + "\n".join(lines)


def get_capabilities_for_prompt():
    """Generate concise capabilities list for LLM system prompt injection."""
    caps = get_all_capabilities()
    parts = [info.get("name", key) for key, info in caps.items()]
    return "Faehigkeiten: " + ", ".join(parts)
