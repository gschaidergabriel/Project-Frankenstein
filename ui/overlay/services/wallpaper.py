"""Wallpaper event publishing wrapper."""
from __future__ import annotations
import sys

# Try to import wallpaper events, provide no-op fallbacks
try:
    try:
        from config.paths import AICORE_ROOT as _AICORE_ROOT
    except ImportError:
        from pathlib import Path as _P
        _AICORE_ROOT = _P("/home/ai-core-node/aicore/opt/aicore")
    sys.path.insert(0, str(_AICORE_ROOT))
    from live_wallpaper.wallpaper_events import (
        publish_event as wp_event,
        event_chat_request as wp_chat_req,
        event_chat_response as wp_chat_resp,
        event_thinking_start as wp_thinking_start,
        event_thinking_pulse as wp_thinking_pulse,
        event_thinking_end as wp_thinking_end,
        event_inference_start as wp_inference_start,
        event_inference_end as wp_inference_end,
        event_screenshot as wp_screenshot,
        event_file_read as wp_file_read,
        event_web_search as wp_web_search,
        event_tool_call as wp_tool,
        event_game_launch as wp_game_launch,
        event_game_exit as wp_game_exit,
    )
    WALLPAPER_EVENTS = True
except Exception:
    WALLPAPER_EVENTS = False
    def wp_event(*a, **k): pass
    def wp_chat_req(*a, **k): pass
    def wp_chat_resp(*a, **k): pass
    def wp_thinking_start(*a, **k): pass
    def wp_thinking_pulse(*a, **k): pass
    def wp_thinking_end(*a, **k): pass
    def wp_inference_start(*a, **k): pass
    def wp_inference_end(*a, **k): pass
    def wp_screenshot(*a, **k): pass
    def wp_file_read(*a, **k): pass
    def wp_web_search(*a, **k): pass
    def wp_tool(*a, **k): pass
    def wp_game_launch(*a, **k): pass
    def wp_game_exit(*a, **k): pass
