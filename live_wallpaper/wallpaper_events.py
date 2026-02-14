#!/usr/bin/env python3
"""
Wallpaper Event System
======================
Publishes events from aicore components to the live wallpaper via UDP.
The wallpaper listens on port 8198 for event packets.
"""

import socket
import json
import time

WALLPAPER_EVENT_PORT = 8198
WALLPAPER_EVENT_HOST = "127.0.0.1"

_socket = None

def _get_socket():
    """Get or create UDP socket."""
    global _socket
    if _socket is None:
        _socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return _socket

def publish_event(source: str, event_type: str, level: str = "info", data: dict = None, extra: dict = None):
    """
    Publish an event to the wallpaper.

    Args:
        source: Component name (ui, desktop, fs, steam, voice, net, toolbox)
        event_type: Event type (chat.request, thinking.start, etc.)
        level: Event level (info, warning, error)
        data: Optional additional data
        extra: Alias for data (backwards compat)
    """
    try:
        sock = _get_socket()
        packet = {
            "source": source,
            "type": event_type,
            "level": level,
            "time": time.time(),
            "data": data or extra or {}
        }
        sock.sendto(
            json.dumps(packet).encode('utf-8'),
            (WALLPAPER_EVENT_HOST, WALLPAPER_EVENT_PORT)
        )
    except Exception:
        pass  # Silently fail if wallpaper not running

def publish_many(events: list):
    """Publish multiple events at once."""
    for event in events:
        publish_event(**event)

def send_voice_levels(levels: list):
    """Send voice level data for visualization."""
    publish_event("voice", "voice.levels", "info", {"levels": levels})

def wallpaper_activity(activity_type: str = "pulse"):
    """Generic activity pulse."""
    publish_event("system", f"activity.{activity_type}", "info")

# ============================================
# UI Events (Chat Overlay)
# ============================================

def event_chat_request(message: str = ""):
    """User sent a message."""
    publish_event("ui", "chat.request", "info", {"message": message[:50] if message else ""})

def event_chat_response(message: str = ""):
    """Frank responded."""
    publish_event("ui", "chat.response", "info", {"message": message[:50] if message else ""})

def event_thinking_start(source: str = "ui"):
    """Frank started thinking/processing."""
    publish_event(source, "thinking.start", "info")

def event_thinking_pulse(source: str = "ui"):
    """Thinking in progress (periodic pulse)."""
    publish_event(source, "thinking.pulse", "info")

def event_thinking_end(source: str = "ui"):
    """Frank finished thinking."""
    publish_event(source, "thinking.end", "info")

def event_inference_start(source: str = "ui"):
    """LLM inference started."""
    publish_event(source, "inference.start", "info")

def event_inference_end(source: str = "ui"):
    """LLM inference finished."""
    publish_event(source, "inference.end", "info")

# ============================================
# Desktop Events
# ============================================

def event_screenshot(source: str = "desktop"):
    """Screenshot taken."""
    publish_event("desktop", "screenshot", "info", {"source": source})

# ============================================
# File System Events
# ============================================

def event_file_read(path: str = ""):
    """File was read."""
    publish_event("fs", "file.read", "info", {"path": path})

# ============================================
# Web Events
# ============================================

def event_web_search(query: str = ""):
    """Web search performed."""
    publish_event("net", "web.search", "info", {"query": query[:30] if query else ""})

# ============================================
# Tool Events
# ============================================

def event_tool_call(tool_name: str = ""):
    """Tool was called."""
    publish_event("toolbox", f"tool.{tool_name}", "info")

# ============================================
# Voice Events
# ============================================

def event_voice_active():
    """Voice input detected."""
    publish_event("voice", "voice.active", "info")

def event_voice_recognized(text: str = ""):
    """Voice was recognized."""
    publish_event("voice", "voice.recognized", "info", {"text": text[:50] if text else ""})

# ============================================
# Gaming Events
# ============================================

def event_game_launch(game: str = ""):
    """Game launched."""
    publish_event("steam", "game.launch", "info", {"game": game})

def event_game_exit(game: str = ""):
    """Game exited."""
    publish_event("steam", "game.exit", "info", {"game": game})

# ============================================
# Error / System Events
# ============================================

def event_error(error_code: str = "", message: str = ""):
    """Error occurred."""
    publish_event("system", "error", "error", {"code": error_code, "message": message})

def event_warning(message: str = ""):
    """Warning occurred."""
    publish_event("system", "warning", "warning", {"message": message})

def event_system_info(info: str = ""):
    """System info event."""
    publish_event("system", "info", "info", {"info": info})

def event_memory_access(memory_type: str = ""):
    """Memory access event."""
    publish_event("memory", "memory.access", "info", {"type": memory_type})

def event_sensory_noise(intensity: float = 0.5):
    """Sensory noise event for visual effects."""
    publish_event("sensory", "noise", "info", {"intensity": intensity})

# ============================================
# Visual Effect Events
# ============================================

def event_scan_face():
    """Trigger face scan effect."""
    publish_event("visual", "scan.face", "info")

def event_eye_glow(intensity: float = 1.0):
    """Trigger eye glow effect."""
    publish_event("visual", "eye.glow", "info", {"intensity": intensity})

def event_mouth_speak():
    """Trigger mouth speaking animation."""
    publish_event("visual", "mouth.speak", "info")

def event_glitch(intensity: float = 1.0):
    """Trigger glitch effect."""
    publish_event("visual", "glitch", "info", {"intensity": intensity})

# ============================================
# Status/Control
# ============================================

def wallpaper_ping():
    """Ping the wallpaper to check if it's alive."""
    publish_event("control", "ping", "info")

def wallpaper_status():
    """Request wallpaper status."""
    publish_event("control", "status.request", "info")

def wallpaper_is_running() -> bool:
    """Check if wallpaper is running by attempting to send a ping."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.1)
        sock.sendto(b'{"type":"ping"}', (WALLPAPER_EVENT_HOST, WALLPAPER_EVENT_PORT))
        return True
    except:
        return False
