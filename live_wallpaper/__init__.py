"""
Frank Live Wallpaper - HAL Edition v4.0
=======================================

Franks visuelle Präsenz - inspiriert von HAL 9000

Ein pulsierendes, gewölbtes Glasauge das Franks Zustand visualisiert.
Minimalistisch, performant, cyberpunk.

Visual Features (HAL v4.0):
- Rotes HAL-Auge mit Glas/Konvex-Effekt (mehrere Schichten)
- Weiße Glasreflektionen für 3D-Tiefe
- Sanftes Pulsieren (Breathing-Effekt)
- Hardware-Stats oben (CPU/GPU Temp, Load, RAM)
- Modul-Status seitlich

Animationen:
- Normal: Sanftes rotes Pulsieren
- Thinking: Farbwechsel zu Orange/Gelb, verstärktes Pulsieren, äußeres Glühen
- Error: Flackern/Glitchen

Gaming Mode:
- Nahtloses Ausblenden wenn Games starten
- Nahtloses Einblenden wenn Games enden
- User bemerkt keine Übergänge

Event Reactions:
- inference.start/thinking.start: Thinking-Mode (Orange, Glow)
- error: Flicker-Effekt
- gaming.start: Verzögertes Ausblenden (0.4s nach Game-Start)
- gaming.end: Sofortiges Einblenden

Performance: ~10-13% CPU, 15 FPS, Cyberpunk-Ästhetik

Das Wallpaper ist Franks visuelle Präsenz - sein digitales Auge.

Usage:
    # Send events to wallpaper
    from live_wallpaper.wallpaper_events import (
        publish_event,
        event_chat_request,
        event_inference_start,
        event_voice_active,
        event_error,
        send_voice_levels,
        wallpaper_activity,
    )

    # NEC-specific events
    from live_wallpaper import (
        event_hypothesis_new,
        event_memory_recall,
        event_self_improve,
    )

    # Control wallpaper daemon
    from live_wallpaper.wallpaper_control import (
        start, stop, restart, status,
        trigger_scan, trigger_eye_glow, trigger_mouth, trigger_error,
        run_demo,
    )

    # Access NEC core directly
    from live_wallpaper.nec_core import NeuralEmergenceCore, NECState
"""

from .wallpaper_events import (
    publish_event,
    publish_many,
    send_voice_levels,
    wallpaper_activity,
    event_chat_request,
    event_chat_response,
    event_thinking_start,
    event_thinking_pulse,
    event_thinking_end,
    event_inference_start,
    event_inference_end,
    event_tool_call,
    event_voice_active,
    event_voice_recognized,
    event_game_launch,
    event_game_exit,
    event_screenshot,
    event_file_read,
    event_web_search,
    event_error,
    event_system_info,
    event_memory_access,
    event_sensory_noise,
    event_scan_face,
    event_eye_glow,
    event_mouth_speak,
    event_glitch,
    wallpaper_ping,
    wallpaper_status,
    wallpaper_is_running,
)

# Optional control module
try:
    from .wallpaper_control import (
        start,
        stop,
        restart,
        status,
        is_running,
        send_pulse,
        trigger_scan,
        trigger_eye_glow,
        trigger_mouth,
        trigger_error,
        trigger_thinking,
        enable_autostart,
        disable_autostart,
        run_demo,
    )
    CONTROL_AVAILABLE = True
except ImportError:
    CONTROL_AVAILABLE = False
    # Dummy functions
    def start(): pass
    def stop(): pass
    def restart(): pass
    def status(): return "unknown"
    def is_running(): return False
    def send_pulse(): pass
    def trigger_scan(): pass
    def trigger_eye_glow(): pass
    def trigger_mouth(): pass
    def trigger_error(): pass
    def trigger_thinking(): pass
    def enable_autostart(): pass
    def disable_autostart(): pass
    def run_demo(): pass

# NEC-specific imports
try:
    from .nec_core import (
        NeuralEmergenceCore,
        NECState,
        NeuralNode,
        NeuralEdge,
        HypothesisDisplay,
        PrivacyFilter,
        DataIntegration,
    )
    NEC_AVAILABLE = True
except ImportError:
    NEC_AVAILABLE = False


# NEC-specific event functions
def event_hypothesis_new(text: str = ""):
    """Trigger hypothesis.new event - spawns temporary node."""
    publish_event("world_exp", "hypothesis.new", "info", extra={"text": text})


def event_memory_recall(memory_id: str = ""):
    """Trigger memory.recall event - activates Titan node."""
    publish_event("titan", "memory.recall", "info", extra={"memory_id": memory_id})


def event_self_improve(tool_name: str = ""):
    """Trigger self_improve event - spawns permanent genesis node."""
    publish_event("e_sir", "self_improve", "info", extra={"tool": tool_name})


def event_neural_activation(node_id: str, glow: float = 0.8):
    """Trigger activation of a specific neural node."""
    publish_event("nec", "neural.activation", "info", extra={"node": node_id, "glow": glow})


def event_traversal_start(path: list = None):
    """Start a traversal animation through the neural network."""
    publish_event("nec", "traversal.start", "info", extra={"path": path or []})


# Gaming Mode Functions - für nahtloses Wallpaper-Handling
def gaming_mode_start():
    """
    Aktiviert Gaming Mode - Wallpaper wird nahtlos ausgeblendet.

    Wird aufgerufen NACHDEM das Game gestartet ist, damit der User
    das Ausblenden nicht sieht.
    """
    import os
    from pathlib import Path
    # Flag-Datei erstellen
    try:
        from config.paths import get_temp as _lw_get_temp
        _lw_gaming_flag = _lw_get_temp("gaming_mode")
    except ImportError:
        _lw_gaming_flag = Path("/tmp/frank/gaming_mode")
    _lw_gaming_flag.parent.mkdir(parents=True, exist_ok=True)
    _lw_gaming_flag.touch()
    # Event senden
    publish_event("gaming", "gaming.start", "info")


def gaming_mode_end():
    """
    Beendet Gaming Mode - Wallpaper wird nahtlos eingeblendet.

    Wird aufgerufen BEVOR das Game sich schließt, damit der User
    das Einblenden nicht sieht.
    """
    import os
    from pathlib import Path
    # Flag-Datei entfernen
    try:
        try:
            from config.paths import get_temp as _lw_get_temp2
            _lw_gaming_flag2 = _lw_get_temp2("gaming_mode")
        except ImportError:
            _lw_gaming_flag2 = Path("/tmp/frank/gaming_mode")
        _lw_gaming_flag2.unlink()
    except FileNotFoundError:
        pass
    # Event senden
    publish_event("gaming", "gaming.end", "info")


def is_gaming_mode() -> bool:
    """Prüft ob Gaming Mode aktiv ist."""
    from pathlib import Path
    try:
        from config.paths import get_temp as _lw_get_temp3
        _lw_gaming_flag3 = _lw_get_temp3("gaming_mode")
    except ImportError:
        _lw_gaming_flag3 = Path("/tmp/frank/gaming_mode")
    return _lw_gaming_flag3.exists()


__all__ = [
    # Events
    "publish_event",
    "publish_many",
    "send_voice_levels",
    "wallpaper_activity",
    "event_chat_request",
    "event_chat_response",
    "event_thinking_start",
    "event_thinking_pulse",
    "event_thinking_end",
    "event_inference_start",
    "event_inference_end",
    "event_tool_call",
    "event_voice_active",
    "event_voice_recognized",
    "event_game_launch",
    "event_game_exit",
    "event_screenshot",
    "event_file_read",
    "event_web_search",
    "event_error",
    "event_system_info",
    "event_memory_access",
    "event_sensory_noise",
    "event_scan_face",
    "event_eye_glow",
    "event_mouth_speak",
    "event_glitch",
    "wallpaper_ping",
    "wallpaper_status",
    "wallpaper_is_running",
    # Control
    "start",
    "stop",
    "restart",
    "status",
    "is_running",
    "send_pulse",
    "trigger_scan",
    "trigger_eye_glow",
    "trigger_mouth",
    "trigger_error",
    "trigger_thinking",
    "enable_autostart",
    "disable_autostart",
    "run_demo",
    # NEC
    "NeuralEmergenceCore",
    "NECState",
    "NeuralNode",
    "NeuralEdge",
    "HypothesisDisplay",
    "PrivacyFilter",
    "DataIntegration",
    "NEC_AVAILABLE",
    # NEC Events
    "event_hypothesis_new",
    "event_memory_recall",
    "event_self_improve",
    "event_neural_activation",
    "event_traversal_start",
    # Gaming Mode
    "gaming_mode_start",
    "gaming_mode_end",
    "is_gaming_mode",
]

__version__ = "4.0.0"  # HAL Edition
