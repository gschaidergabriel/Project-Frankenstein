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
        "name": "System Control",
        "description": "WiFi, Bluetooth, Audio, Display, Printer, File Organization with Confirmation System",
    },
    "package_management": {
        "name": "Package Management",
        "description": "Install/remove software via apt, pip, snap, flatpak with security limits",
    },
    "monitoring": {
        "name": "System Monitoring (ASRS)",
        "description": "CPU/GPU/Memory/Disk/Thermal/I/O real-time monitoring with 4-level escalation",
    },
    "auto_repair": {
        "name": "Auto-Repair",
        "description": "Automatic diagnosis and repair of system issues (with user approval)",
    },
    "display_intelligence": {
        "name": "Display Intelligence (ADI)",
        "description": "Multi-Monitor Profiles and Adaptive Layout Configuration",
    },
    "network_intelligence": {
        "name": "Network Intelligence (Sentinel)",
        "description": "Device detection, port scanning, ARP spoofing detection, security analysis",
    },
    "voice_control": {
        "name": "Voice Control",
        "description": "Wake word (Hey Frank), Push-to-Talk, Text-to-Speech (Thorsten voice)",
    },
    "gaming_mode": {
        "name": "Gaming Mode",
        "description": "Automatic Game Detection, Resource Optimization, Anti-Cheat Protection",
    },
    "personality_system": {
        "name": "Personality (E-PQ)",
        "description": "Dynamic temperament and mood evolution over time",
    },
    "self_improvement": {
        "name": "Self-Improvement (Genesis)",
        "description": "Controlled self-improvement with sandbox testing and user approval",
    },
    "experience_memory": {
        "name": "Experience Memory",
        "description": "Own world model with causal pattern recognition and learning from experience",
    },
    "url_fetching": {
        "name": "URL Fetching",
        "description": "Retrieve webpage content directly and extract text (fetch URL, read page)",
    },
    "rss_feeds": {
        "name": "RSS/Atom Feeds",
        "description": "Read news feeds, retrieve current headlines and articles",
    },
    "system_actions": {
        "name": "System Actions",
        "description": "Real system changes: packages, apps, files, services, sysctl/gsettings. Last guardrail: no root (by design).",
    },
    "skill_system": {
        "name": "Skill/Plugin System",
        "description": "Extensible skills (native Python + OpenClaw). New skills installable via marketplace.",
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
    """Generate human-readable capabilities summary."""
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
            _AICORE_ROOT = _Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(_AICORE_ROOT))
        from skills import get_skill_registry
        skills = get_skill_registry().list_all()
        if skills:
            skill_names = [s.name for s in skills]
            lines.append(f"\nInstalled Skills ({len(skills)}): {', '.join(skill_names)}")
            lines.append("New skills installable from the OpenClaw Marketplace.")
    except Exception:
        pass

    return "My Capabilities:\n\n" + "\n".join(lines)


def get_capabilities_for_prompt():
    """Generate concise capabilities list for LLM system prompt injection."""
    caps = get_all_capabilities()
    parts = [info.get("name", key) for key, info in caps.items()]
    return "Capabilities: " + ", ".join(parts)
