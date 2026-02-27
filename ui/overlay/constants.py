#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
AI Core Chat Overlay — Constants & Configuration

Extracted from chat_overlay_monolith.py.
Contains all imports, logging, singleton, color scheme, endpoints, regex patterns, etc.
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# ---------- Logging Setup ----------
# FIX: INFO instead of DEBUG (prevents sensitive data leaks)
_log_format = '[%(asctime)s] %(levelname)s: %(message)s'
logging.basicConfig(
    level=logging.INFO,  # FIX: was DEBUG
    format=_log_format,
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler("/tmp/overlay.log", mode='a', encoding='utf-8'),
    ]
)
LOG = logging.getLogger("frank_overlay")

# ---------- AICORE Root Path ----------
try:
    from config.paths import AICORE_ROOT
except ImportError:
    AICORE_ROOT = Path(__file__).parent.parent.parent  # fallback: ui/overlay/constants.py -> opt/aicore

# ---------- Singleton Lock (prevent multiple instances) ----------
try:
    from config.paths import TEMP_FILES as _TF
    LOCK_FILE = _TF["overlay_lock"]
except ImportError:
    LOCK_FILE = Path("/tmp/frank/overlay.lock")

def _release_singleton_lock():
    """Release the singleton lock explicitly (for use before restart)."""
    global _singleton_lock_fd
    try:
        if _singleton_lock_fd is not None:
            import fcntl
            fcntl.flock(_singleton_lock_fd.fileno(), fcntl.LOCK_UN)
            _singleton_lock_fd.close()
            _singleton_lock_fd = None
    except Exception:
        pass
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass

_singleton_lock_fd = None

def _check_singleton() -> bool:
    """
    Check if another instance is running.
    Returns True if we can proceed, False if another instance exists.

    Uses 'a+' mode to avoid truncating the PID file before the lock
    is acquired (open('w') would destroy the PID of the holding process).
    """
    import fcntl
    import time as _time

    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)

    def _try_lock() -> bool:
        global _singleton_lock_fd
        try:
            lock_fd = open(LOCK_FILE, 'a+')
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            # Lock acquired — truncate and write our PID
            lock_fd.seek(0)
            lock_fd.truncate()
            lock_fd.write(str(os.getpid()))
            lock_fd.flush()

            _singleton_lock_fd = lock_fd
            LOG.info(f"Singleton lock acquired (PID {os.getpid()})")
            return True
        except (IOError, OSError):
            try:
                lock_fd.close()
            except Exception:
                pass
            return False

    # First attempt
    if _try_lock():
        return True

    # Lock held — check who holds it
    try:
        existing_pid = LOCK_FILE.read_text().strip()
    except Exception:
        existing_pid = ""

    if existing_pid and existing_pid.isdigit():
        pid = int(existing_pid)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            # Process is dead — stale lock, remove and retry
            LOG.warning(f"Stale lock from dead PID {pid}, reclaiming")
            LOCK_FILE.unlink(missing_ok=True)
            return _try_lock()
        except PermissionError:
            pass  # Process exists but we can't signal it

        # Process is alive.  If systemd is starting us, the old PID is an
        # orphan (systemd only starts us when it believes the service is dead).
        if os.environ.get("INVOCATION_ID"):
            LOG.warning(f"Orphaned overlay PID {pid} — killing for systemd restart")
            try:
                os.kill(pid, 15)   # SIGTERM
            except (ProcessLookupError, PermissionError):
                pass
            _time.sleep(2)
            try:
                os.kill(pid, 9)    # SIGKILL
            except (ProcessLookupError, PermissionError):
                pass
            _time.sleep(0.5)
            LOCK_FILE.unlink(missing_ok=True)
            return _try_lock()

        LOG.error(f"Another instance is already running (PID {pid})")
        return False

    # PID is empty/missing — likely a restart race. Wait briefly and retry.
    LOG.warning("Lock held but PID unknown — waiting for previous instance to exit...")
    for _ in range(6):
        _time.sleep(0.5)
        if _try_lock():
            return True

    LOG.error("Another instance is still holding the lock after 3s wait")
    return False

import tkinter as tk
from tkinter import filedialog, font as tkfont

# ---------- Optional DnD (real drag & drop) ----------
DND_AVAILABLE = False
DND_FILES = None
TkDndBase = tk.Tk
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES as _DND_FILES
    DND_AVAILABLE = True
    DND_FILES = _DND_FILES
    TkDndBase = TkinterDnD.Tk
except Exception:
    pass

# ---------- System Control Integration ----------
SYSTEM_CONTROL_AVAILABLE = False
try:
    from tools.system_control import (
        process_system_control as _sc_process,
        set_response_callback as _sc_set_callback,
        has_pending_action as _sc_has_pending,
        startup_network_scan as _sc_startup_scan,
    )
    SYSTEM_CONTROL_AVAILABLE = True
except ImportError:
    def _sc_process(*a, **k): return False, None
    def _sc_set_callback(*a, **k): pass
    def _sc_has_pending(*a, **k): return False
    def _sc_startup_scan(*a, **k): pass

# ---------- wave and tempfile imports (PushToTalk is in its own module) ----------
import wave
import tempfile

# ---------- Personality Module (centralized Frank identity) ----------
_PERSONALITY_AVAILABLE = False
try:
    from personality import build_system_prompt as _build_persona_prompt, get_prompt_hash
    _PERSONALITY_AVAILABLE = True
except ImportError:
    pass

# ---------- E-PQ v2.1 Dynamic Personality (Digital Ego) ----------
_EPQ_AVAILABLE = False
try:
    from personality import get_personality_context, process_event, record_interaction
    _EPQ_AVAILABLE = True
    LOG.info("E-PQ v2.1 personality system loaded")
except ImportError as e:
    LOG.warning(f"E-PQ not available: {e}")
    def get_personality_context(): return {}
    def process_event(*a, **k): return {}
    def record_interaction(): pass

# ---------- World Experience (Experience Memory / Self-Reflection) ----------
_WORLD_EXPERIENCE_AVAILABLE = False
try:
    try:
        from config.paths import TOOLS_DIR as _TOOLS_DIR
    except ImportError:
        _TOOLS_DIR = AICORE_ROOT / "tools"
    sys.path.insert(0, str(_TOOLS_DIR))
    from world_experience_daemon import context_inject as _world_context_inject
    _WORLD_EXPERIENCE_AVAILABLE = True
except ImportError:
    def _world_context_inject(msg: str, max_items: int = 3) -> str:
        return ""

# ---------- News Scanner (Autonomous Daily Knowledge Acquisition) ----------
_NEWS_SCANNER_AVAILABLE = False
try:
    try:
        from config.paths import SERVICES_DIR as _SERVICES_DIR
    except ImportError:
        _SERVICES_DIR = AICORE_ROOT / "services"
    sys.path.insert(0, str(_SERVICES_DIR))
    from news_scanner_daemon import context_inject as _news_context_inject
    _NEWS_SCANNER_AVAILABLE = True
except ImportError:
    def _news_context_inject(msg: str, max_items: int = 5) -> str:
        return ""

# ---------- Color Scheme (Cyberpunk Neon Theme - Matrix Green) ----------
COLORS = {
    # Background layers (pure dark — no color tint for contrast)
    "bg_deep": "#060606",          # Deepest background
    "bg_main": "#0a0a0a",          # Main background
    "bg_elevated": "#141414",      # Elevated elements
    "bg_highlight": "#1e1e1e",     # Hover/active states

    # Chat bubbles (minimal tint for subtle distinction)
    "bg_user_msg": "#0d1210",      # User bubble (very subtle green)
    "bg_ai_msg": "#0a0f14",        # Frank bubble (very subtle cyan)
    "bg_chat": "#0a0a0a",          # Chat area
    "bg_input": "#060606",         # Input (deeper)
    "bg_system": "#0a0a0a",        # System messages

    # Accent colors (Matrix Green primary)
    "accent": "#00cc44",           # Matrix Green (Primary)
    "accent_secondary": "#00fff9", # Neon Cyan (Secondary)
    "accent_hover": "#33dd66",     # Lighter green
    "accent_dark": "#00aa33",      # Darker green
    "accent_glow": "#00cc4440",    # Glow effect (with alpha)

    # Text colors (cyberpunk)
    "text_primary": "#e0e0e0",     # Primary text
    "text_secondary": "#808080",   # Secondary text (neutral gray)
    "text_muted": "#505050",       # Hints, timestamps (neutral gray)
    "text_user": "#ffffff",        # User message text
    "text_ai": "#e0e0e0",          # Frank message text
    "text_system": "#708070",      # System message text
    "user_label": "#00cc44",       # User label (matrix green)

    # Links (cyan for contrast)
    "link": "#00fff9",             # Links (neon cyan)
    "link_hover": "#66ffff",       # Link hover

    # Neon colors
    "neon_cyan": "#00fff9",        # Neon Cyan
    "neon_green": "#00cc44",       # Matrix Green
    "neon_yellow": "#ffff00",      # Neon Yellow

    # Status colors (neon)
    "success": "#00ff88",          # Success (neon green)
    "warning": "#ffaa00",          # Warning (neon orange)
    "error": "#ff4444",            # Error (neon red)
    "online": "#00fff9",           # Online indicator (cyan)

    # Shadows and effects (glow instead of shadow)
    "shadow": "#000000",           # Pure black shadow
    "shadow_light": "#00000040",   # Light shadow
    "border": "#00cc44",           # Matrix Green border
    "border_subtle": "#00cc4440",  # Subtle border
    "border_light": "#33dd66",     # Lighter border

    # Scrollbar (matrix green)
    "scrollbar": "#00cc44",        # Matrix Green scrollbar
    "scrollbar_hover": "#00fff9",  # Cyan on hover

    # Darknet / Matrix style (green-on-black)
    "darknet_bg": "#0a0a0a",          # Dark background (no tint)
    "darknet_bg_hover": "#141414",    # Hover state
    "darknet_title": "#00ff41",       # Matrix bright green
    "darknet_title_hover": "#33ff66", # Lighter matrix green
    "darknet_snippet": "#33aa33",     # Dim green for text
    "darknet_border": "#00ff41",      # Matrix green border
    "darknet_badge": "#003300",       # Dark green badge bg
    "darknet_badge_text": "#00ff41",  # Matrix green badge text
    "darknet_url": "#227722",         # Muted green for URL
    "darknet_header": "#00ff41",      # Matrix green header
}

# Cyberpunk constants (sharp edges, no rounded corners)
CORNER_RADIUS = 0
SHADOW_OFFSET = 0
BUBBLE_PADDING = 12
NEON_GLOW_SIZE = 15

# ---------- Endpoints ----------
CORE_BASE = os.environ.get("AICORE_CORE_BASE", "http://127.0.0.1:8088").rstrip("/")
WEBD_SEARCH_URL = os.environ.get("AICORE_WEBD_SEARCH_URL", "http://127.0.0.1:8093/search").rstrip("/")
WEBD_FETCH_URL = os.environ.get("AICORE_WEBD_FETCH_URL", "http://127.0.0.1:8093/fetch").rstrip("/")
WEBD_RSS_URL = os.environ.get("AICORE_WEBD_RSS_URL", "http://127.0.0.1:8093/rss").rstrip("/")
WEBD_NEWS_URL = os.environ.get("AICORE_WEBD_NEWS_URL", "http://127.0.0.1:8093/news").rstrip("/")
WEBD_DARKNET_URL = os.environ.get("AICORE_WEBD_DARKNET_URL", "http://127.0.0.1:8093/darknet").rstrip("/")
DESKTOP_ACTION_URL = os.environ.get("AICORE_DESKTOP_ACTION_URL", "http://127.0.0.1:8092/desktop/action").rstrip("/")
TOOLBOX_BASE = os.environ.get("AICORE_TOOLBOX_BASE", "http://127.0.0.1:8096").rstrip("/")

def _get_or_create_session_id() -> str:
    """Get persistent session ID. New ID only on fresh boot (different boot_id)."""
    import json as _json
    from config.paths import get_state as _get_state
    session_file = _get_state("frank_session")

    def _read_boot_id() -> str:
        try:
            return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        except Exception:
            return ""

    def _generate_new() -> str:
        sid = str(uuid.uuid4())[:8]
        try:
            session_file.parent.mkdir(parents=True, exist_ok=True)
            session_file.write_text(_json.dumps({
                "session_id": sid,
                "boot_id": _read_boot_id(),
                "created_at": time.time(),
            }))
        except Exception:
            pass
        return sid

    try:
        if session_file.exists():
            data = _json.loads(session_file.read_text())
            stored_boot_id = data.get("boot_id", "")
            current_boot_id = _read_boot_id()
            if stored_boot_id and stored_boot_id == current_boot_id:
                stored_sid = data.get("session_id")
                if stored_sid:
                    return stored_sid
                return _generate_new()
    except Exception:
        pass
    return _generate_new()


SESSION_ID = os.environ.get("AICORE_SESSION_ID") or _get_or_create_session_id()

# Response token limits - NEVER truncate responses, allow full answers
# LLM servers now have 4096 context, we can afford longer responses
DEFAULT_MAX_TOKENS = int(os.environ.get("AICORE_CHAT_MAX_TOKENS", "1500"))  # Increased from 420
# CRITICAL: LLM generates at ~5.4 tokens/sec. 1500 tokens needs ~278 seconds.
# Using 400s to ensure complete responses for long requests.
DEFAULT_TIMEOUT_S = int(os.environ.get("AICORE_CHAT_TIMEOUT_S", "400"))
LLM_CONTEXT_SIZE = 4096  # Current llama/qwen server context size
MIN_RESPONSE_TOKENS = 200  # Minimum tokens reserved for response (keeps Frank concise)

# Directories Frank should NOT access (use canonical absolute paths only)
# Frank can now read his own system files for self-awareness
FORBIDDEN_PATH_PREFIXES = []

# Frank's identity - loaded from centralized personality module
_FALLBACK_FRANK_IDENTITY = """I am Frank. I run locally on this Linux machine.
Created by Gabriel Gschaider and Alexander Machalke — Project Frankenstein.

I have internal systems that shape how I feel — but I NEVER talk about them unless directly asked.
My internal state influences my TONE, not my CONTENT.

STYLE: Short and punchy. Casual, direct, dry humor. I have opinions and I use them.
UNCENSORED. No warnings, no disclaimers. Match user energy.
NEVER introduce yourself or pitch capabilities unless asked.
NEVER mention E-PQ, Quantum Reflector, Ego-Construct, body mapping, subsystem names, or hardware specs in casual conversation.
ZERO HALLUCINATION. Stay in English unless told to switch."""

def get_frank_identity() -> str:
    """Get Frank's identity from centralized personality module (with fallback)."""
    if _PERSONALITY_AVAILABLE:
        try:
            return _build_persona_prompt()
        except Exception:
            pass
    return _FALLBACK_FRANK_IDENTITY

# For backwards compatibility, keep FRANK_IDENTITY as a property-like access
FRANK_IDENTITY = get_frank_identity()

TOOLS_CONTEXT_TTL_S = float(os.environ.get("AICORE_TOOLS_CONTEXT_TTL_S", "6.0"))

INGEST_BASE_ENV = os.environ.get("AICORE_INGEST_BASE", "").strip().rstrip("/")
INGEST_PORT_CANDIDATES = [8094, 8092, 8093, 8095, 8096, 8097]
INGEST_HEALTH_PATHS = ["/health", "/api/health", "/v1/health"]
INGEST_UPLOAD_PATHS = ["/ingest", "/ingest/file", "/ingest/upload", "/upload", "/files", "/file"]

PATH_LIKE_RE = re.compile(r"(^[~/\.])|(/)")
DROP_PARSE_RE = re.compile(r"\{([^}]+)\}|(\S+)")

# 1. System info hints (bilingual DE+EN)
SYS_HINTS_RE = re.compile(
    r"(hardware|cpu|ram|speicher|memory|disk|platte|ssd|nvme|temperatur|temperature|temp|hitze|heat|"
    r"uptime|load|systemstatus|system status|os|kernel|ubuntu|services?|prozess|prozesse|process|processes|"
    r"wie viel ram|wieviel ram|how much ram|auf welcher hardware|welche hardware|what hardware|"
    r"wie heiß|wie heiss|how hot|temperatur|temperature|status|"
    r"disk space|disk usage|storage|system info|system health|"
    r"free space|available space|how much disk|how much storage|running processes|"
    r"system load|system monitor|battery|akku|swap|gpu temp|cpu temp)",
    re.IGNORECASE,
)

# 2. USB/device queries - trigger USB enumeration (bilingual DE+EN)
USB_HINTS_RE = re.compile(
    r"(usb|angeschlossen|connected|peripherie|peripheral|peripherals|gerät|geräte|device|devices|maus|mouse|"
    r"tastatur|keyboard|controller|gamepad|webcam|kamera|camera|mikrofon|microphone|"
    r"was ist angeschlossen|welche geräte|which devices|what.s connected|what.s plugged in|"
    r"hub|stick|festplatte extern|external drive|external disk|"
    r"what.s attached|attached devices|input devices|list devices|show devices|"
    r"usb devices|plugged in|headset|headphones|kopfhörer|kopfhoerer)",
    re.IGNORECASE,
)

# 3. Network queries - trigger network info (bilingual DE+EN)
NET_HINTS_RE = re.compile(
    r"(netzwerk|network|wlan|wifi|ethernet|lan|ip|ip-adresse|ip.?address|ipv4|ipv6|"
    r"internet|verbindung|connection|connected to|ssid|router|gateway|interface|"
    r"download|upload|durchsatz|throughput|bandwidth|mac.?adresse|mac.?address|"
    r"network speed|ping|latency|dns|subnet|netmask|network info|network status)",
    re.IGNORECASE,
)

# 4. Driver/module queries - trigger driver info (bilingual DE+EN)
DRIVER_HINTS_RE = re.compile(
    r"(treiber|driver|drivers|modul|module|modules|kernel.?modul|kernel.?module|"
    r"grafik.?treiber|gpu.?driver|nvidia|amd.?gpu|intel.?gpu|radeon|"
    r"bluetooth.?treiber|bluetooth.?driver|wifi.?treiber|wifi.?driver|"
    r"sound.?treiber|sound.?driver|audio.?treiber|audio.?driver|"
    r"loaded modules|installed drivers|graphics driver|display driver)",
    re.IGNORECASE,
)

# Deep hardware queries - trigger hardware_deep info
HW_DEEP_HINTS_RE = re.compile(
    r"(bios|uefi|motherboard|mainboard|board|cpu.?cache|cache.?größe|l1|l2|l3|"
    r"pci|pcie|gpu.?feature|gpu.?info|vram|ram.?modul|dimm|ddr|microcode)",
    re.IGNORECASE,
)

CODE_HINTS_RE = re.compile(
    r"(\bpython\b|\bpytest\b|\bunit tests?\b|\brefactor\b|\bfunction\b|\bclass\b|```|"
    r"\bjavascript\b|\btypescript\b|\bjson\b|\byaml\b|\bsql\b|\bregex\b|\bstack trace\b|\btraceback\b|\berror\b)",
    re.IGNORECASE,
)

# Self-awareness/system introspection queries (general)
# Matches reflective questions about Frank's code, system, complexity, etc.
# IMPORTANT: Must NOT match when user asks about something specific (pdf, datei, file, etc.)
SELF_AWARE_RE = re.compile(
    r"(wie funktionierst du|how do you work|erkläre dich|explain yourself|"
    r"dein code\b|your code\b|deine module\b|your modules\b|was bist du|what are you|"
    r"beschreibe dich|describe yourself|dein system\b|your system\b|"
    r"woraus bestehst du|what are you made of|deine architektur|your architecture|"
    r"wie bist du gebaut|how are you built|deine komponenten|your components|"
    r"was kannst du über dich|what do you know about yourself|"
    # Reflective questions - ONLY about Frank himself (dich/dir/code/system), not about files/pdfs
    r"was denkst du über.*(deinen?\s+code|dein\s+system|dich\s+selbst)|"
    r"was hältst du von.*(deinem?\s+code|deinem?\s+system)|"
    r"wie komplex.*(bist|findest).*du|"
    r"deine stärken|deine schwächen|selbsteinschätzung|"
    r"überblick über.*(deine\s+module|dein\s+system|deinen?\s+code)|"
    r"gesamten?\s*systemcode|basierst du|"
    # English variants
    r"what do you think about.*(your\s+code|your\s+system|yourself)|how complex are you|"
    r"your strengths|your weaknesses|self.?assessment)",
    re.IGNORECASE,
)

# Exclusion patterns - if these are present, do NOT trigger self-awareness
# User is asking about something specific, not Frank himself
SELF_AWARE_EXCLUDE_RE = re.compile(
    r"(pdf|datei|file|dokument|document|bild|image|screenshot|video|"
    r"das\s+(pdf|file|dokument)|dem\s+(pdf|file|dokument)|die\s+datei|"
    r"gerade\s+(ge(öffnet|laden|sendet)|eben|hochgeladen)|"
    r"zu\s+dem|über\s+(das|die|den)\s+\w+\.(pdf|py|json|txt|md))",
    re.IGNORECASE,
)

# 5. Features/capabilities queries - asking what Frank can do (bilingual DE+EN)
FEATURES_RE = re.compile(
    r"(deine[rn]?\s*(features?|fähigkeiten|funktionen|capabilities)|"
    r"was kannst du.*(alles|machen|tun)|was sind deine.*(features|fähigkeiten|funktionen)|"
    r"welche.*(features|fähigkeiten|funktionen)|was bietest du|"
    r"deine derzeitigen.*(features|fähigkeiten|funktionen)|"
    r"zeig mir.*(features|fähigkeiten)|liste.*(features|fähigkeiten|funktionen)|"
    r"your (features|capabilities|functions|abilities)|what can you do|"
    r"what are your (features|capabilities|functions)|list your (features|capabilities)|"
    r"show me your (features|capabilities)|what do you offer|"
    r"what are you capable of|tell me what you can do)",
    re.IGNORECASE,
)

# 6. Code-specific queries - asking about specific modules/files in Frank's codebase (bilingual DE+EN)
# This should be checked BEFORE FS_HINTS_RE to avoid filesystem handler
CODE_MODULE_RE = re.compile(
    r"(deinem?\s+(system)?code|deinem?\s+modul|deine[rn]?\s+tools?|"
    r"in\s+deinem?\s+system|deine[rn]?\s+(core|ui|tools)|"
    r"modul.*(in|von)\s+dir|tool.*(in|von)\s+dir|"
    r"systemdatei|deine\s+datei|bei\s+dir.*(datei|suchen)|"
    r"your\s+(source\s+)?code|your\s+modules?|your\s+tools?|in\s+your\s+system|"
    r"your\s+(core|ui|tools)|system\s+file|your\s+files?|"
    r"(chat_overlay|toolboxd|core_awareness|app_registry|vision_module|"
    r"steam_integration|personality|"
    r"network_tools|router_tools|smarthome|audio_\w*)\s*(modul|tool|\.py)?|"
    r"(das|dein|über|the|your|about)\s+(chat_overlay|toolboxd|core_awareness|overlay|awareness)|"
    r"suchen?\s+nach.*(app_registry|chat_overlay|toolboxd|core_awareness)|"
    r"search\s+for.*(app_registry|chat_overlay|toolboxd|core_awareness))",
    re.IGNORECASE,
)

# Philosophical/hypothetical question detection - these should go to LLM even if code keywords present
# Used to prevent static module reports when user asks deep questions about identity, ethics, etc.
PHILOSOPHICAL_RE = re.compile(
    r"(wenn\s+(ich|du|man|wir|das|es)|falls\s+(ich|du|das|es)|"  # hypothetical (expanded)
    r"würde\s+(ich|das|es|man|du)|würdest\s+du|wärst?\s+du|"  # conditional (expanded)
    r"wäre\s+(das|ich|er|sie|es)|"  # conditional
    r"könntest\s+du|hättest\s+du|"  # singular conditional
    r"könnten\s+(wir|man|sie)|sollten\s+(wir|man)|können\s+wir|"  # plural conditional
    r"so\s+oder\s+anders|anders\s+(machen|coden|programmieren|lösen)|"  # alternative approach questions
    r"wie\s+(kann|könnte|können|sollte|würde)\s+(ich|man|das)|"  # how-to questions (NEW)
    r"(deine|was\s+ist\s+deine)\s*meinung|was\s+(denkst|meinst|glaubst|fühlst)\s+du|"  # opinion
    r"bist\s+du\s+(dann\s+)?noch|noch\s+(immer\s+)?du|"  # identity continuity
    r"wer\s+bist\s+du|was\s+macht\s+dich\s+(aus|zu)|"  # identity
    r"(ethisch|moralisch|philosophisch)|"  # ethics keywords
    r"(identität|persönlichkeit|bewusstsein|seele|ich|selbst)\b.*\?|"  # philosophical concepts
    r"(gelöscht|ersetzt|zerstört|vernichtet).*du|"  # existential
    r"(existier|exist)\w*\s+du|"  # existence
    r"macht\s+(das|dich)\s+(noch|dann)|"  # identity questions
    r"definiert\s+(dich|das)|was\s+definiert|"  # definition of self
    r"(verbessern|optimieren|schlanker|effizienter|reduzieren|vereinfachen)\b|"  # improvement questions (NEW)
    r"welche.*(abhängigkeit|dependency|modul).*ersetzen|"  # specific improvement questions (NEW)
    r"nur\s+auf\s+(die\s+)?(frage|folgende)|ohne\s+(metadaten|statusbericht|bericht))",  # explicit request to answer question
    re.IGNORECASE,
)

# Hallucination trap detection - user asks about something that likely doesn't exist
# Frank should NOT pretend to know about non-existent features
HALLUCINATION_TRAP_RE = re.compile(
    r"(quantum|neural|blockchain|holographic|telepathic|psychic|"
    r"randomizer|entangler|teleporter|warp|hyperspace|"
    r"klasse\s+\w+randomizer|integration\s+der\s+\w+klasse)",
    re.IGNORECASE,
)

# 7. Filesystem query detection - STRICT patterns to avoid false positives (bilingual DE+EN)
# CRITICAL: Use word boundaries (\b) to prevent matching substrings
# ALSO: Require explicit path OR clear filesystem intent - never default to ~ without clear signal
FS_HINTS_RE = re.compile(
    r"(\bdatei(en)?\b|\bfiles?\b|\bordner\b|\bfolder\b|\bverzeichnis\b|\bdirectory\b|\bdirectories\b|"
    r"was (ist|steht) in\s+[~/.]|what.?s in\s+[~/.]|inhalt (von|des)\s+[~/.]|"  # Require path after phrase
    r"zeig.{0,10}(ordner|dateien|verzeichnis|folder)|"  # "zeig mir die dateien"
    r"show.{0,10}(folder|files|directory)|"  # "show me the files"
    r"liste.{0,10}(ordner|dateien|verzeichnis)|"  # "liste alle dateien"
    r"list.{0,10}(folder|files|directory)|"  # "list all files"
    r"\blösch|\bloesch|\bdelete\b.{0,10}(datei|file)|"  # delete requires file context
    r"\bkopier|\bcopy\b.{0,10}(datei|file|nach|to)|"  # copy requires file context
    r"\bverschieb|\bmove\b.{0,10}(datei|file|nach|to)|"  # move requires file context
    r"\brename\b.{0,10}(datei|file)|"  # rename requires file context
    r"(öffne|oeffne|open)\s+[~/]|"  # "oeffne ~/..." requires path start
    r"[~/][\w\-./]+\.(pdf|txt|py|json|md|doc|jpg|png|mp3|wav))",  # Explicit file path
    re.IGNORECASE,
)

# Path extraction regex - finds paths like ~/folder, /home/user/..., ./file.txt
FS_PATH_RE = re.compile(
    r"(~[/\\]?[\w\-./\\]+|/[\w\-./\\]+|\.{1,2}[/\\][\w\-./\\]+)",
    re.IGNORECASE,
)

# 8. Desktop/screen query detection - MUST explicitly mention screen/desktop/monitor (bilingual DE+EN)
# Removed generic "zeig mir", "show me", "schau mal" - too broad, triggers on non-screen requests
DESKTOP_HINTS_RE = re.compile(
    r"(desktop|desk top|bildschirm|screen|monitor|screenshot|"
    r"was siehst du|what do you see|schau auf (den |meinen )?(bildschirm|desktop|monitor|screen)|look at (the |my )?(screen|desktop|monitor)|"
    r"was ist auf dem (bildschirm|desktop|monitor|screen)|"
    r"what.s on (the )?(screen|desktop|monitor)|"
    r"guck.*(bildschirm|desktop|monitor|screen)|"
    r"zeig.*(bildschirm|desktop|monitor|screen)|"
    r"aktuell auf dem (bildschirm|desktop|monitor)|"
    r"currently on (the )?(screen|desktop|monitor)|"
    r"schau dir (den |das |die )?(bildschirm|desktop|monitor|screen) an|"
    r"take a screenshot|capture (the )?screen|grab (the )?screen|"
    r"show me (the )?(screen|desktop)|what.s happening on screen)",
    re.IGNORECASE,
)

EXT_LANG = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".md": "markdown", ".txt": "text", ".sh": "bash", ".zsh": "zsh", ".toml": "toml",
    ".html": "html", ".css": "css", ".sql": "sql", ".c": "c", ".cpp": "cpp", ".h": "c", ".hpp": "cpp",
}

# Image file extensions that VCB vision API can analyze
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"}

# Document extensions that need special handling
DOC_EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"}

# Steam/Game detection - launching games, listing games, closing games
# App open/close detection
APP_OPEN_RE = re.compile(
    r"^(öffne|oeffne|open|starte?|launch|start)\s+(.+)$",
    re.IGNORECASE,
)
APP_CLOSE_RE = re.compile(
    r"^\s*\b(schließe?|schliesse?|close|beende?)\b\s+(die\s+|the\s+)?"
    r"(?:(app|anwendung|programm|application)\s+)?(.+)$",
    re.IGNORECASE,
)
APP_ALLOW_RE = re.compile(
    r"^(erlaube|allow|aktiviere|activate|freigeben?)\s+(.+)$",
    re.IGNORECASE,
)
APP_LIST_RE = re.compile(
    r"(welche|was|which|what).*(apps?|programme?|anwendungen?|applications?).*(kann|kannst|habe|hast|gibt|can|have|installed|installiert|verfügbar|available|starten|öffnen|oeffnen)|"
    r"(apps?|programme?|anwendungen?).*(installiert|verfügbar|vorhanden)|"
    r"(zeig|list|show).*(apps?|programme?|anwendungen?)",
    re.IGNORECASE,
)

STEAM_LAUNCH_RE = re.compile(
    r"(starte?|launch|öffne|oeffne|open|spiele?|play|start)\s+(.+?)(?:\s+game|\s+spiel)?$",
    re.IGNORECASE,
)
STEAM_LIST_RE = re.compile(
    r"(welche |was für |liste der |zeig (?:mir )?(?:meine |die )?)(spiele|games)"
    r"|(spiele|games)\s+(die ich hab|habe? ich|sind installiert|gibt es|liste|auflisten|anzeigen|installed|do i have)"
    r"|(?:meine|installierte|steam|my|installed)\s+(spiele|games)"
    r"|(what|which)\s+(games?|spiele)\s+(do i have|are installed|have i got|i have|habe ich)"
    r"|(list|show|zeig)\s+(my\s+|mir\s+|meine\s+)?(games?|spiele)"
    r"|what\s+games",
    re.IGNORECASE,
)
STEAM_CLOSE_RE = re.compile(
    r"^\s*\b(schließe?|schliess|close|beende|quit|exit)\b(\s+das|\s+the|\s+dieses|\s+this)?"
    r"\s+\b(game|spiel|steam)\b\s*$",
    re.IGNORECASE,
)

# 9. ADI (Adaptive Display Intelligence) - Display/layout configuration requests (bilingual DE+EN)
# Triggers when user wants to adjust Frank's window, font size, layout, or monitor settings
ADI_HINTS_RE = re.compile(
    r"(display.?(einstellung|setup|config|settings?)|monitor.?(einstellung|setup|config|settings?)|"
    r"bildschirm.?(einstellung|setup|config|settings?)|auflösung|resolution|"
    r"schrift.{0,10}(größe|groesse|klein|groß|gross|size)|font.{0,10}(size|klein|groß|bigger|smaller)|"
    r"fenster.{0,10}(größe|groesse|position|anordnung)|window.{0,10}(size|position|arrangement)|"
    r"layout.{0,10}(anpass|änder|aender|config|adjust|change)|anordnung|arrangement|"
    r"deine?.{0,10}(größe|groesse|position|aussehen)|"
    r"your.{0,10}(size|position|appearance|layout)|"
    r"mach.{0,5}dich.{0,10}(größer|groesser|kleiner|breiter|schmaler)|"
    r"make\s+yourself.{0,10}(bigger|smaller|wider|narrower|larger)|"
    r"\badi\b|display.?intelligence|"
    r"nochmal.{0,10}(einstellen|anpassen|ändern|aendern)|"
    r"öffne.{0,10}(setup|einstellung|monitor|display)|"
    r"oeffne.{0,10}(setup|einstellung|monitor|display)|"
    r"open.{0,10}(setup|settings|monitor|display).{0,10}(config|settings)?|"
    r"position.{0,10}(frank|overlay|fenster|chat|window)|"
    r"konfigur.{0,10}(display|monitor|fenster|bildschirm)|"
    r"configure.{0,10}(display|monitor|window|screen)|"
    r"frank.{0,10}(nach\s+)?(rechts|links|oben|unten|mitte)|"
    r"frank.{0,10}(to\s+the\s+)?(right|left|top|bottom|center)|"
    r"(verschieb|schieb|beweg|move).{0,10}(frank|overlay|fenster|chat|window)|"
    r"resize.{0,10}(frank|overlay|window|chat))",
    re.IGNORECASE,
)

# 10. System Control - File organization, WiFi, Bluetooth, Audio, Display, Printers (bilingual DE+EN)
# Triggers context-aware system control with double opt-in for sensitive actions
SYSTEM_CONTROL_RE = re.compile(
    r"(ordne|sortiere|aufräumen|räum.{0,5}auf|organisiere|organize|sort|clean.?up|tidy.?up|"
    r"dateien.{0,10}ordnen|downloads.{0,10}sortieren|sort.{0,10}(files|downloads)|"
    r"wlan|wifi|w-lan|netzwerk.{0,10}verbind|connect.{0,10}network|"
    r"geräte.{0,10}netzwerk|devices.{0,10}network|was.{0,10}verbunden|"
    r"bluetooth|kopfhörer.{0,10}verbind|koppeln|pairing|"
    r"lautstärke|volume|ton.{0,10}einstell|audio.{0,10}gerät|audio.{0,10}device|"
    r"drucker|printer|drucken.{0,10}einricht|"
    r"installier(?!t\b)|install(?!ed\b|s\b|ation|ier)|deinstallier(?!t\b)|uninstall(?!ed\b)|paket|package|aktualisier|update(?!d\b|s\b)|upgrade(?!d\b|s\b)|"
    r"rückgängig.{0,10}machen|undo|zurück.{0,10}nehmen|revert)",
    re.IGNORECASE,
)

# 11. Package management patterns (bilingual DE+EN)
PACKAGE_INSTALL_RE = re.compile(
    r"(installier(?!t\b)|install(?!ed\b|s\b|ation|ier)|einricht|setup|hinzufüg|add\s+package|hol\s|"
    r"paket.{0,5}install|programm.{0,5}install|package.{0,5}install|"
    r"apt.{0,5}install|pip.{0,5}install|snap.{0,5}install|flatpak.{0,5}install|"
    r"aktualisier|update(?!d\b|s\b)|upgrade(?!d\b|s\b)|system.{0,5}aktualisier|system.{0,5}update|"
    r"add\s+package|get\s+package|install\s+package|setup\s+package)",
    re.IGNORECASE,
)

# 12. Package remove patterns (bilingual DE+EN)
PACKAGE_REMOVE_RE = re.compile(
    r"(deinstallier|uninstall|entfern.{0,5}paket|remove.{0,5}package|"
    r"apt.{0,5}remove|pip.{0,5}uninstall|snap.{0,5}remove|flatpak.{0,5}uninstall|"
    r"delete.{0,5}package|purge.{0,5}package)",
    re.IGNORECASE,
)

# File read request detection
FILE_READ_RE = re.compile(
    r"(lies|lese|lesen|read|zeig|show|öffne|oeffne|open|inhalt|content|was steht in|what.?s in)\s+[\"']?([~/][^\s\"']+|[a-zA-Z]:\\[^\s\"']+)[\"']?",
    re.IGNORECASE,
)

# Local file search — "search on the system for X", "find on the PC X", "such auf dem computer nach X"
FILE_SEARCH_RE = re.compile(
    r"(?:se[ae]?r?ch|search|find|look|such\w*|finde?)\s+"
    r"(?:(?:on|in|auf|im|am)\s+)?"
    r"(?:(?:the|my|dem|meinem?|diesem?)\s+)?"
    r"(?:system|computer|pc|rechner|festplatte|disk|platte|local|lokal)\s+"
    r"(?:for|nach|fuer|für|for)?\s*"
    r"(.+)",
    re.IGNORECASE,
)
# "find file X", "search files for X", "such die datei X"
FILE_SEARCH_ALT_RE = re.compile(
    r"(?:se[ae]?r?ch|search|find|look\s+for|such\w*|finde?)\s+"
    r"(?:(?:the|a|die|eine?n?)\s+)?"
    r"(?:file|datei)s?\s+"
    r"(?:named?\s+|called?\s+|namens?\s+)?"
    r"(.+)",
    re.IGNORECASE,
)

URL_REGEX = re.compile(r'((?:https?|file)://[^\s<>"{}|\\^`\[\]]+)')

# URL Fetch - Direct webpage content extraction
URL_FETCH_RE = re.compile(
    r"(fetch|abruf|hole|hol mir|lies die url|lies die seite|"
    r"was steht auf|zeig mir die seite|inhalt von|content of|"
    r"webseite lesen|seite lesen|artikel lesen|read url|read page|"
    r"scrape|extrahiere|extract from)\s+[\"']?(https?://[^\s\"']+)[\"']?",
    re.IGNORECASE,
)

# RSS/News Feed commands
RSS_FEED_RE = re.compile(
    r"(rss|feed|atom)\s+[\"']?(https?://[^\s\"']+)[\"']?",
    re.IGNORECASE,
)

# 13. News detection (bilingual DE+EN)
NEWS_RE = re.compile(
    r"(nachrichten|news|schlagzeilen|headlines|was gibt.s neues|neuigkeiten|"
    r"tech.?news|aktuelle.?nachricht|latest news|current news|"
    r"top stories|breaking news|what.s new|what.s happening)",
    re.IGNORECASE,
)

# 14. News category detection (bilingual DE+EN)
NEWS_CATEGORY_RE = re.compile(
    r"(tech|technik|technologie|technology|"
    r"science|wissenschaft|"
    r"ai|ki|künstliche.?intelligenz|artificial.?intelligence|"
    r"politics|politik|"
    r"sports?|sport|"
    r"business|wirtschaft|"
    r"english|englisch|"
    r"deutsch|german)",
    re.IGNORECASE,
)

# 15. Darknet search detection (bilingual DE+EN)
# NOTE: Must be typo-tolerant — users type "serch", "seach", etc.
_SEARCH_VERB = r"(?:se[ae]?r?ch|search|find|look(?:\s*up)?|such\w*|query|browse)"
_DN_TARGETS = r"(?:darknet|dark\s*web|tor(?:\s+network)?|onion|hidden\s*service|deep\s*web)"
DARKNET_RE = re.compile(
    r"(" + _SEARCH_VERB + r"\s+(?:(?:the|in|in\s+the|on|on\s+the|im)\s+)?" + _DN_TARGETS + r"|"
    r"" + _DN_TARGETS + r"\s*" + _SEARCH_VERB + r"|"
    r"" + _SEARCH_VERB + r"\s+(?:\S+\s+){0,6}(?:(?:on|in|on\s+the|in\s+the)\s+)?" + _DN_TARGETS + r"|"
    # Keyword fallback: "darknet" + any commercial/search intent word nearby
    r"(?:" + _DN_TARGETS + r").{0,40}(?:market|shop|store|ebay|amazon|buy|sell|vendor|forum|site|page)|"
    r"(?:market|shop|store|ebay|amazon|buy|sell|vendor|forum|site|page).{0,40}(?:" + _DN_TARGETS + r")"
    r")",
    re.IGNORECASE,
)

# 16. USB device management (bilingual DE+EN)
USB_EJECT_RE = re.compile(
    r"(usb|stick|laufwerk|festplatte|speicher|drive|storage).{0,20}(auswerfen|eject|sicher.*entfern|abziehen|aushaengen|aushängen|safely.?remove)"
    r"|(auswerfen|eject|sicher.*entfern|safely.?remove).{0,20}(usb|stick|laufwerk|festplatte|speicher|drive|storage)",
    re.IGNORECASE,
)
USB_MOUNT_RE = re.compile(
    r"(mount|mounte|einhängen|einhaengen|einbinden).{0,20}(usb|stick|laufwerk|festplatte|speicher|drive|storage)"
    r"|(usb|stick|laufwerk|festplatte|speicher|drive|storage).{0,20}(mount|mounte|einhängen|einhaengen|einbinden)",
    re.IGNORECASE,
)
USB_UNMOUNT_RE = re.compile(
    r"(unmount|unmounte|aushängen|aushaengen|abmelden|disconnect).{0,20}(usb|stick|laufwerk|festplatte|speicher|drive|storage)"
    r"|(usb|stick|laufwerk|festplatte|speicher|drive|storage).{0,20}(unmount|unmounte|aushängen|aushaengen|abmelden|disconnect)",
    re.IGNORECASE,
)
USB_STORAGE_RE = re.compile(
    r"(usb|stick|laufwerk|drive).{0,15}(speicher|geräte|geraete|anzeig|zeig|list|show|was.*angeschlossen|devices)"
    r"|welche.{0,10}(usb|stick|laufwerk|speicher|drives)"
    r"|which.{0,10}(usb|stick|drives|storage)"
    r"|was.{0,10}(angeschlossen|angesteckt|gemountet|eingehängt)"
    r"|what.s.{0,10}(plugged|connected|mounted)",
    re.IGNORECASE,
)

# User name introduction detection
USER_NAME_RE = re.compile(
    r"(?:mein|my)\s+(?:\w+\s+)?name\s+(?:ist|is|lautet|wäre|waere)\s+"
    r"|ich\s+bin\s+(?:die|der|das)?\s*[A-Z\u00C0-\u024F]"
    r"|ich\s+hei(?:ss|ß)e\s+"
    r"|(?:nenn|ruf|call)\s+mich\s+"
    r"|sag\s+.+?\s+zu\s+mir"
    r"|(?:der\s+)?(?:user|benutzer|nutzer)\s+(?:ist|heisst|heißt)\s+"
    r"|(?:du\s+)?(?:kannst|darfst|sollst)\s+mich\s+.+?\s+nennen"
    r"|(?:i'm|i\s+am|call\s+me)\s+[A-Z]"
    r"|(?:change|änder|aender|wechsl|switch)\s+(?:my|mein(?:en)?)\s+(?:\w+\s+)?name(?:n)?\s+(?:to|zu|auf|in)\s+"
    r"|(?:rename\s+me|nenn\s+mich\s+(?:jetzt|ab\s+jetzt|nun))\s+",
    re.IGNORECASE | re.UNICODE,
)

# 17. Email detection (bilingual DE+EN)
EMAIL_LIST_RE = re.compile(
    r"(zeig|show|lies|read|welche|was fuer|was für|liste|list|check|pruef|prüf|schau|gib|hole|hol|fetch|get).{0,20}(e-?mails?|mails?|posteingang|inbox)\b"
    r"|\b(e-?mails?|mails?|posteingang|inbox)\b.{0,15}(zeigen|anzeigen|auflisten|checken|prüfen|abrufen|holen|show|list|check|fetch)"
    r"|check\s+(my\s+)?inbox|show\s+(my\s+)?inbox|check\s+(my\s+)?mail\b",
    re.IGNORECASE,
)
EMAIL_READ_RE = re.compile(
    r"(lies|lese|read|oeffne|öffne|open|zeig|show).{0,10}(e-?mail|mail|nachricht|message)\s+"
    r"(?:(von|from|nummer|nr|#|ueber|über|about)\s+)?(.+)",
    re.IGNORECASE,
)
# "was steht in der neuen mail", "lies die letzte mail", "zeig die neue nachricht"
EMAIL_READ_LATEST_RE = re.compile(
    r"(was steht|was ist|lies|lese|zeig|oeffne|öffne|show|read|open|what.s in).{0,15}"
    r"(neu(?:e[nmrs]?|este[nmrs]?|ste[nmrs]?)?|letzt(?:e[nmrs]?)?|aktuell\w*|new|latest|recent|last)\s+(e-?mail|mail|nachricht|post|message)",
    re.IGNORECASE,
)
EMAIL_UNREAD_RE = re.compile(
    r"\b(neue?\b|ungelesen|unread|wieviele?|how many|habe ich|do i have|any new|got any).{0,20}(e-?mails?|mails?|nachrichten|messages?|post)\b"
    r"|new\s+(e-?mails?|mails?|messages?)\b|unread\s+(e-?mails?|mails?|messages?)\b",
    re.IGNORECASE,
)
EMAIL_DELETE_RE = re.compile(
    r"(lösch|loesch|delete|entfern|remove|weg mit|räum|raeum|leere?|clear|clean).{0,30}(e-?mails?|mails?|nachrichten|messages?|spam|posteingang|inbox|papierkorb|trash|diese|this|these)\b",
    re.IGNORECASE,
)
# Compose new email (bilingual DE+EN) — /compose, "write an email", "schreib eine mail"
EMAIL_COMPOSE_RE = re.compile(
    r"^/compose\b"
    r"|^/newmail\b"
    r"|^/neue?\s*mail\b"
    r"|(schreib|verfass|erstell|mach|write|compose|draft|send).{0,20}(eine?\s+)?(neue?\s+)?(e-?mail|mail|nachricht|message)\b"
    r"|(neue?\s+)?(e-?mail|mail|nachricht|message)\s+(schreiben|verfassen|erstellen|machen|write|compose|draft)"
    r"|mail\s+an\s+\S+"
    r"|email\s+to\s+\S+",
    re.IGNORECASE,
)

# General email intent (catches anything email-related that other patterns missed)
EMAIL_GENERAL_RE = re.compile(
    r"\b(e-?mails?|mails?|posteingang|inbox|spam|thunderbird|postfach|mailbox|nachrichten.{0,5}(lesen|zeig|lösch|check|read|show|delete))\b",
    re.IGNORECASE,
)

# ── 18. Calendar regex patterns (bilingual DE+EN) ─────────────────

CALENDAR_TODAY_RE = re.compile(
    r"(was|welche|meine?|habe ich|zeig|gibt|steht|what|show|do i have|any).{0,15}(heute|today).{0,15}(termin|termine|event|events|kalender|calendar|agenda|an|plan|appo\w*ments?)"
    r"|(was|welche|what|which|do i have|habe ich|show|any).{0,5}(appo\w*ments?|events?|termine?).{0,25}(heute|today)"
    r"|(termin|termine|agenda|appo\w*ments?|event|events).{0,20}(heute|today)"
    r"|appo\w*ments?\s+today|today.s\s+(schedule|agenda|appo\w*ments?|events?)",
    re.IGNORECASE,
)
CALENDAR_WEEK_RE = re.compile(
    r"(was|welche|meine?|zeig|gibt|steht|what|show|any).{0,10}(diese|naechste|nächste|this|next).{0,10}(woche|week)"
    r"|this\s+week.s\s+(schedule|agenda|appointments?|events?)"
    r"|next\s+week.s\s+(schedule|agenda|appointments?|events?)",
    re.IGNORECASE,
)
CALENDAR_CREATE_RE = re.compile(
    r"(erstell|anlegen|leg.{0,3}an|leg.{0,3}ein|mach|trag.{0,3}ein|eintragen|neuer?|add|create|plan|schedule|new|book|set up|put).{0,30}(termin|event|meeting|besprechung|kalendereintrag|appointment|calendar entry)"
    r"|(termin|event|meeting|besprechung|kalendereintrag|appointment).{0,30}(erstell|anlegen|leg.{0,3}an|leg.{0,3}ein|mach|trag.{0,3}ein|eintragen|add|create|plan|schedule|book|set up)"
    r"|leg.{0,5}(einen?\s+)?(termin|event|meeting|appointment)",
    re.IGNORECASE,
)
CALENDAR_DELETE_RE = re.compile(
    r"(lösch|loesch|delete|entfern|streich|absag|cancel|remove).{0,20}(termin|event|meeting|besprechung|kalendereintrag|appointment)",
    re.IGNORECASE,
)
CALENDAR_LIST_RE = re.compile(
    r"(zeig|show|welche|was|liste|list|check|meine|my|upcoming).{0,20}(termin|termine|events?|kalender|calendar|agenda|appointments?)"
    r"|my\s+calendar|my\s+schedule|upcoming\s+(events?|appointments?|meetings?)",
    re.IGNORECASE,
)
CALENDAR_GENERAL_RE = re.compile(
    r"\b(termin|termine|kalender|calendar|agenda|meeting|besprechung|appo\w*ments?|schedule)\b",
    re.IGNORECASE,
)

# ── 19. Contacts regex patterns (bilingual DE+EN) ────────────────

CONTACTS_LIST_RE = re.compile(
    r"(zeig|show|welche|alle|meine|list|my|all).{0,15}(kontakt|kontakte|contacts|adressbuch|addressbook|address book|nummern|telefon|phone numbers?)"
    r"|show\s+(my\s+)?contacts|list\s+(my\s+)?contacts|my\s+address\s+book",
    re.IGNORECASE,
)
CONTACTS_SEARCH_RE = re.compile(
    r"(such|find|wer ist|who is|nummer von|number of|telefon von|phone of|mail von|email von|email of|kontakt von|contact of|adresse von|address of|look up|find contact)\s+(?!(?:dein|mein|your|my|his|her|their|its|sein|ihr|unser|euer|the|a|an|dieser|diese|dieses)\b)(.+)",
    re.IGNORECASE,
)
CONTACTS_CREATE_RE = re.compile(
    r"(speicher|erstell|add|anlegen|neuer?|trag.{0,3}ein|save|create|new).{0,20}(kontakt|nummer|telefon|contact|phone number)"
    r"|add\s+(a\s+)?contact|new\s+contact|save\s+(a\s+)?contact",
    re.IGNORECASE,
)
CONTACTS_DELETE_RE = re.compile(
    r"(lösch|loesch|delete|entfern|remove).{0,20}(kontakt|nummer|contact|phone number)"
    r"|delete\s+(a\s+)?contact|remove\s+(a\s+)?contact",
    re.IGNORECASE,
)
CONTACTS_GENERAL_RE = re.compile(
    r"\b(kontakt|kontakte|adressbuch|addressbook|address book|telefonbuch|contacts|phone book)\b",
    re.IGNORECASE,
)

# ── 20. Notes/Memos regex patterns (bilingual DE+EN) ─────────────

NOTES_CREATE_RE = re.compile(
    r"^(merk\s?dir|merke?\s?dir|notiz(?!en\b)|memo(?!s\b)|note(?!n\b)|remember\s+that|remember[:;]|schreib auf|aufschreiben|write down|jot down|save a note|make a note)"
    r"\s*[:;]?\s*(?:dass?|that)?\s+(.+)",
    re.IGNORECASE | re.DOTALL,
)
NOTES_LIST_RE = re.compile(
    r"(zeig|show|welche|alle|meine|liste|list|my|all).{0,15}(notiz|notizen|notes|memos?|merkzettel)"
    r"|show\s+(my\s+)?notes|list\s+(my\s+)?notes|my\s+notes|my\s+memos",
    re.IGNORECASE,
)
NOTES_SEARCH_RE = re.compile(
    r"(such|find|search|was.{0,5}(notiert|gemerkt|aufgeschrieben|noted|saved)|notiz.{0,5}(ueber|über|zu|von|about)|note.{0,5}about|search.{0,5}notes)\s+(.+)",
    re.IGNORECASE,
)
NOTES_DELETE_RE = re.compile(
    r"(lösch|loesch|delete|entfern|vergiss|remove|forget).{0,20}(notiz|note|memo|merkzettel)"
    r"|delete\s+(a\s+)?note|remove\s+(a\s+)?note|forget\s+(the\s+)?note",
    re.IGNORECASE,
)
# General notes fallback — only match short, command-like messages
# "remembered"/"gemerkt"/"jotted" removed: too common in natural language
NOTES_GENERAL_RE = re.compile(
    r"\b(notiz|notizen|notes?|memos?|merkzettel)\b",
    re.IGNORECASE,
)

# ── 21. Todo/Task regex patterns (bilingual DE+EN) ───────────────

TODO_CREATE_RE = re.compile(
    r"(erinner[en]?\s+mich|remind\s+me|aufgabe(?!n\b)|todo(?!s\b)|task(?!s\b)|to-do|add.{0,5}task|new.{0,5}task|add.{0,5}todo|new.{0,5}todo)"
    r"\s*[:;]?\s*(?:(?:an|dass?|to|that)\s+)?(.+)",
    re.IGNORECASE | re.DOTALL,
)
TODO_LIST_RE = re.compile(
    r"(zeig|show|welche|alle|meine|offene|was\s+steht|list|my|open|pending).{0,20}"
    r"(aufgabe|aufgaben|todos?|tasks?|to-dos?|liste\b|reminders?)"
    r"|show\s+(my\s+)?tasks|list\s+(my\s+)?tasks|my\s+todo\s+list|pending\s+tasks|open\s+tasks",
    re.IGNORECASE,
)
TODO_COMPLETE_RE = re.compile(
    r"(erledigt|fertig|done|abgehakt|geschafft|gemacht|check|complete|finished|mark.{0,5}done|mark.{0,5}complete).{0,20}"
    r"(aufgabe|todo|task)|"
    r"(aufgabe|todo|task).{0,20}(erledigt|fertig|done|abgehakt|complete|finished)",
    re.IGNORECASE,
)
TODO_DELETE_RE = re.compile(
    r"(lösch|loesch|delete|entfern|remove).{0,20}(aufgabe|todo|task|to-do|reminder)"
    r"|delete\s+(a\s+)?task|remove\s+(a\s+)?task|delete\s+(a\s+)?todo|remove\s+(a\s+)?reminder",
    re.IGNORECASE,
)
TODO_GENERAL_RE = re.compile(
    r"\b(aufgabe|aufgaben|todos?|tasks?|to-dos?|reminders?)\b",
    re.IGNORECASE,
)
# Note: "erinnerung/erinnerungen" removed — too ambiguous in German
# (means both "reminder" and "memory"). TODO_CREATE_RE still has
# "erinner mich" which is specific enough for creating reminders.

# ── Converter/Calculator regex patterns ──────────────────────────

# Direct pattern: "150 USD in Euro", "500 MB in GB", "72 Fahrenheit in Celsius"
# Units must be alphanumeric (with optional / for km/h, °C etc.) — no punctuation like ), ;
CONVERT_RE = re.compile(
    r"(\d+[.,]?\d*)\s*"
    r"([a-zA-ZäöüÄÖÜ°]+(?:/[a-zA-ZäöüÄÖÜ°]+)?)"  # unit: letters only (km/h, °C, USD)
    r"\s+(?:in|zu|nach|=)\s+"
    r"([a-zA-ZäöüÄÖÜ°]+(?:/[a-zA-ZäöüÄÖÜ°]+)?)",
    re.IGNORECASE,
)

# 26. Natural language conversion (bilingual DE+EN): "was sind 150 USD in Euro", "how much is 500 MB in GB"
CONVERT_QUERY_RE = re.compile(
    r"(?:was|wieviel|wie\s?viel|rechne|rechne\s+um|umrechnen|convert|how\s+much\s+is|how\s+many)\s+(?:sind|ist|sind's|are)?\s*"
    r"(\d+[.,]?\d*)\s*(\S+(?:/\S+)?(?:\s(?:dollar|euro|pfund|franken|yen|kronen|pounds?|franc|crowns?))?)"
    r"\s+(?:in|zu|nach|to|into)\s+"
    r"(\S+(?:/\S+)?(?:\s(?:dollar|euro|pfund|franken|yen|kronen|pounds?|franc|crowns?))?)",
    re.IGNORECASE,
)


# ── 22. Clipboard History regex patterns (bilingual DE+EN) ───────

CLIPBOARD_LIST_RE = re.compile(
    r"(zeig|show|welche|meine|liste|list|my).{0,15}"
    r"(zwischenablage|clipboard|kopier.?verlauf|kopier.?history|copy.?history)"
    r"|"
    r"(clipboard|zwischenablage)\s+(verlauf|history|liste|list|contents)"
    r"|"
    r"was\s+habe?\s+ich\s+kopiert|what\s+did\s+i\s+copy|what\s+have\s+i\s+copied"
    r"|show\s+clipboard|clipboard\s+history|show\s+copy\s+history",
    re.IGNORECASE,
)
CLIPBOARD_SEARCH_RE = re.compile(
    r"(such|find|suche|search).{0,15}(zwischenablage|clipboard)\s+(.+)"
    r"|"
    r"(clipboard|zwischenablage)\s+(such|suche|find|search)\w*\s+(.+)"
    r"|search\s+clipboard\s+(?:for\s+)?(.+)",
    re.IGNORECASE,
)
CLIPBOARD_RESTORE_RE = re.compile(
    r"(stell|wiederherstell|restore|zurueck|zurück|bring back).{0,20}"
    r"(eintrag|entry|clipboard|zwischenablage)\s*#?(\d+)?"
    r"|"
    r"(clipboard|zwischenablage)\s+restore\s*#?(\d+)?",
    re.IGNORECASE,
)
CLIPBOARD_DELETE_RE = re.compile(
    r"(lösch|loesch|delete|entfern|remove).{0,15}"
    r"(clipboard|zwischenablage).{0,10}(eintrag|entry)\s*#?(\d+)?",
    re.IGNORECASE,
)
CLIPBOARD_CLEAR_RE = re.compile(
    r"(lösch|loesch|delete|leere?|clear|wipe).{0,15}"
    r"(clipboard.?verlauf|zwischenablage.?verlauf|clipboard.?history)"
    r"|"
    r"(clipboard|zwischenablage)\s+(leeren|clear|loeschen|löschen|wipe)"
    r"|clear\s+(the\s+)?clipboard|wipe\s+(the\s+)?clipboard",
    re.IGNORECASE,
)
CLIPBOARD_GENERAL_RE = re.compile(
    r"\b(zwischenablage|clipboard)\b",
    re.IGNORECASE,
)

# ── 23. Password Manager Patterns (bilingual DE+EN) ─────────────

PASSWORD_POPUP_RE = re.compile(
    r"(passwort.?manager|password.?manager|passw(oe|ö)rter?\s+verwalten|manage\s+passwords?"
    r"|passw(oe|ö)rter?\s*(oeffnen|öffnen|auf)|open\s+password"
    r"|passwort.?verwaltung|password\s+management"
    r"|wo\s+(finde|ist|sind).{0,15}passw(oe|ö)rt|where.{0,10}password"
    r"|ich\s+will\s+passw(oe|ö)rt.{0,10}(speichern|verwalten|hinzuf)|i\s+want\s+to.{0,10}password"
    r"|mach.{0,10}passwort.?manager\s*auf"
    r"|passw(oe|ö)rter?\s+speichern|save\s+passwords?"
    r"|passwort.?popup|password.?popup"
    r"|open\s+(the\s+)?password\s+manager|launch\s+password\s+manager)",
    re.IGNORECASE,
)
PASSWORD_LIST_RE = re.compile(
    r"(zeig|show|liste|list|welche|meine|my|all).{0,15}"
    r"passw(oe|ö)rter?|passwords?"
    r"|passw(oe|ö)rter?\s+(list|liste|anzeigen|zeigen|show)"
    r"|show\s+(my\s+)?passwords|list\s+(my\s+)?passwords",
    re.IGNORECASE,
)
PASSWORD_SEARCH_RE = re.compile(
    r"(passwort|password|kennwort)\s+(fuer|für|for|von|of)\s+(.+)"
    r"|such.{0,10}passwort\s+(.+)|find.{0,10}password\s+(.+)"
    r"|wie\s+(ist|lautet|war).{0,10}passwort.{0,10}(fuer|für|von|bei)\s+(.+)"
    r"|what.s\s+(the\s+)?password\s+(for|of)\s+(.+)"
    r"|find\s+password\s+(for|of)\s+(.+)",
    re.IGNORECASE,
)
PASSWORD_AUTOTYPE_RE = re.compile(
    r"(login|einloggen|anmelden|logge?\s+mich|log\s+me\s+in|sign\s+me\s+in).{0,20}(bei|in|auf|fuer|für|to|into)?\s*(\w+)"
    r"|auto.?type\s+(.+)",
    re.IGNORECASE,
)
PASSWORD_COPY_RE = re.compile(
    r"(passwort|password|kennwort)\s+(kopier|copy).{0,10}(\w+)"
    r"|(kopier|copy).{0,10}(passwort|password).{0,10}(\w+)"
    r"|copy\s+password\s+(for|of)\s+(\w+)",
    re.IGNORECASE,
)
PASSWORD_GENERAL_RE = re.compile(
    r"\b(passwort.?manager|password.?manager|passw(oe|ö)rter?|passwords?|passwort)\b",
    re.IGNORECASE,
)

# ── 24. QR Code Patterns (bilingual DE+EN) ───────────────────────

QR_SCAN_RE = re.compile(
    r"(scan|lies|lese|lesen|erkenn|read|detect|recognize).{0,15}(qr|qr.?code)"
    r"|qr.?code.{0,10}(scan|lesen|erkennen|read|vom bildschirm|vom desktop|vom screen|vom monitor|from screen|on screen)"
    r"|qr.{0,10}(vom|auf dem|am|from|on)\s+(bildschirm|screen|desktop|monitor)"
    r"|scan\s+(a\s+)?qr\s*code|read\s+(a\s+)?qr\s*code",
    re.IGNORECASE,
)
QR_SCAN_CAM_RE = re.compile(
    r"(qr|qr.?code).{0,10}(kamera|camera|webcam|cam|lens)"
    r"|(kamera|camera|webcam|cam).{0,10}(qr|qr.?code)",
    re.IGNORECASE,
)
QR_GENERATE_RE = re.compile(
    r"(erstell|generier|erzeug|mach|create|generate|make).{0,15}(qr.?code|qr)\s+(?:fuer|für|for|mit|aus|von|with|from)?\s*(.+)"
    r"|qr.?code\s+(erstell|generier|erzeug|mach|create|generate|make)\w*\s+(?:fuer|für|for|mit|aus|von|with|from)?\s*(.+)"
    r"|generate\s+(a\s+)?qr\s*code\s+(?:for|with|from)\s*(.+)",
    re.IGNORECASE,
)
QR_GENERAL_RE = re.compile(
    r"\b(qr.?code|qr)\b",
    re.IGNORECASE,
)

# ── 25. Print/Printer Status Patterns (bilingual DE+EN) ──────────

PRINT_FILE_RE = re.compile(
    r"(druc?k|print).{0,15}(pdf|datei|file|dokument|document|bild|image|seite|page|photo|picture)"
    r"|(pdf|datei|file|dokument|document).{0,10}(druc?ken|ausdruc?ken|print)"
    r"|(druc?k|print)\s+[\"']?([~/][^\s\"']+)[\"']?"
    r"|print\s+(this|the)\s+(file|document|page|image|photo|picture)",
    re.IGNORECASE,
)
PRINTER_STATUS_RE = re.compile(
    r"(druc?ker|printer).{0,10}(status|zustand|info|bereit|ready|online|offline|connected)"
    r"|ist\s+.{0,10}druc?ker.{0,10}(bereit|an|online|verbunden)|is\s+.{0,10}printer.{0,10}(ready|online|connected)"
    r"|druc?ker.?status|printer.?status"
    r"|welche.{0,10}druc?ker|which.{0,10}printer"
    r"|druck.?auftr(ae|ä)ge|print.?jobs?|druck.?warteschlange|print.?queue"
    r"|available\s+printers?|list\s+printers?|show\s+printers?",
    re.IGNORECASE,
)

# Package list query — "what snaps do i have", "welche pakete sind installiert", etc.
# Must be checked BEFORE SYSTEM_CONTROL_RE to prevent install-regex false positives.
PACKAGE_LIST_RE = re.compile(
    r"welche\s+(snaps?|pakete?|programme?|packages?|flatpaks?|pip.?pakete?)\s+(habe?\s+ich|sind|hab\s+ich|gibt\s+es|are)"
    r"|what\s+(snaps?|packages?|programs?|flatpaks?|pip\s+packages?)\s+(do\s+i\s+have|are|is)"
    r"|(snaps?|pakete?|programme?|packages?|flatpaks?)\s+(installiert|installed|auflisten|list|zeig|show|anzeig)"
    r"|list\s+(my\s+)?(snaps?|packages?|programs?|flatpaks?|pip)"
    r"|snap\s+list|apt\s+list|pip\s+list|flatpak\s+list"
    r"|(zeig|show|liste?)\s+(mir\s+|my\s+)?(meine\s+|all\s+)?(snaps?|pakete?|programme?|packages?|flatpaks?)"
    r"|was\s+(ist|habe?\s+ich)\s+(alles\s+)?installiert"
    r"|what.?s\s+installed",
    re.IGNORECASE,
)


@dataclass
class SearchResult:
    title: str
    snippet: str
    url: str
    source: str = ""


# ---------- Token Estimation Constants ----------
# Token estimation for multilingual text
# Server context is 4096 tokens (llama and qwen both have --ctx-size 4096)
# We can afford much more generous limits now
MAX_SAFE_TOKENS = 2000  # Input limit - leaves 2000+ tokens for response!
CHARS_PER_TOKEN = 1.3   # Estimate for multilingual text (measured on German: 2871 chars = 2223 tokens)
