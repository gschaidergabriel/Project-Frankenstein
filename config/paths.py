"""
Centralized path configuration for AI-Core / Frank.

All modules MUST import paths from here instead of hardcoding them.

Resolution order:
1. Environment variable (if set)
2. Auto-detect from this file's location

Directory structure:
    AICORE_ROOT/    = source code root (this repo)
    AICORE_DATA/    = ~/.local/share/frank  (databases, state, models)
    AICORE_CONFIG/  = ~/.config/frank        (user overrides)
    AICORE_LOG/     = ~/.local/share/frank/logs
"""

import os
import tempfile
from pathlib import Path

# === Root paths ===

# Source code root (where this repo lives)
AICORE_ROOT = Path(os.environ.get(
    "AICORE_ROOT",
    str(Path(__file__).resolve().parents[1])
))

# Data directory (databases, state, models)
AICORE_DATA = Path(os.environ.get(
    "AICORE_DATA",
    str(Path.home() / ".local" / "share" / "frank")
))

# User config overrides
AICORE_CONFIG = Path(os.environ.get(
    "AICORE_CONFIG",
    str(Path.home() / ".config" / "frank")
))

# Logs
AICORE_LOG = Path(os.environ.get(
    "AICORE_LOG",
    str(AICORE_DATA / "logs")
))

# Runtime directory (XDG_RUNTIME_DIR / frank — for sockets, locks, PID files)
RUNTIME_DIR = Path(os.environ.get(
    "FRANK_RUNTIME_DIR",
    str(Path(f"/run/user/{os.getuid()}/frank"))
))

# Temp directory (for IPC signal files, transient data)
TEMP_DIR = Path(os.environ.get(
    "FRANK_TEMP_DIR",
    str(Path(tempfile.gettempdir()) / "frank")
))

# === Derived paths ===

DB_DIR = AICORE_DATA / "db"
STATE_DIR = AICORE_DATA / "state"

# Individual database paths
DB_PATHS = {
    "frank": DB_DIR / "frank.db",
    "titan": DB_DIR / "titan.db",
    # titan_shadow is managed by invariants subsystem at INVARIANTS_DIR/titan_shadow.db
    "consciousness": DB_DIR / "consciousness.db",
    "world_experience": DB_DIR / "world_experience.db",
    "chat_memory": DB_DIR / "chat_memory.db",
    "agent_state": DB_DIR / "agent_state.db",
    "e_sir": DB_DIR / "e_sir.db",
    "e_cpmm": DB_DIR / "e_cpmm.db",
    "e_wish": DB_DIR / "e_wish.db",
    "fas_scavenger": DB_DIR / "fas_scavenger.db",
    "system_bridge": DB_DIR / "system_bridge.db",
    "notes": DB_DIR / "notes.db",
    "todos": DB_DIR / "todos.db",
    "passwords": DB_DIR / "passwords.db",
    "clipboard_history": DB_DIR / "clipboard_history.db",
    "news_scanner": DB_DIR / "news_scanner.db",
    "sandbox_awareness": DB_DIR / "sandbox_awareness.db",
    "akam_cache": DB_DIR / "akam_cache.db",
    "intelligence_hub": DB_DIR / "intelligence_hub.db",
    "sovereign": DB_DIR / "sovereign.db",
    "invariants": DB_DIR / "invariants.db",
    "titan_validator": DB_DIR / "titan_validator.db",
    "therapist": DB_DIR / "therapist.db",
    "mirror": DB_DIR / "mirror.db",
    "atlas": DB_DIR / "atlas.db",
    "muse": DB_DIR / "muse.db",
    "quantum_reflector": DB_DIR / "quantum_reflector.db",
    "dream": DB_DIR / "dream.db",
    "autonomous_research": DB_DIR / "autonomous_research.db",
    "aura_analyzer": DB_DIR / "aura_analyzer.db",
    "aicore": DB_DIR / "aicore.sqlite",
}

# State files (JSON)
STATE_PATHS = {
    "chat_history": STATE_DIR / "chat_history.json",
    "frank_session": STATE_DIR / "frank_session.json",
    "system_core": STATE_DIR / "system_core.json",
    "user_profile": STATE_DIR / "user_profile.json",
    "vcb_state": STATE_DIR / "vcb_state.json",
    "security_log": STATE_DIR / "security_log.json",
    "network_health": STATE_DIR / "network_health.json",
    "network_map": STATE_DIR / "network_map.json",
    "device_cache": STATE_DIR / "device_cache.json",
    "genesis_self_model": STATE_DIR / "genesis_self_model.json",
    "genesis_state": STATE_DIR / "genesis_state.json",
    "email_config": STATE_DIR / "email_config.json",
    "email_outbox": STATE_DIR / "email_outbox.json",
}

# Event journal (daily JSONL logs)
JOURNAL_DIR = AICORE_DATA / "journal"

# Special data directories
ADI_PROFILES_DIR = AICORE_DATA / "adi_profiles"
ASRS_BACKUP_DIR = AICORE_DATA / "asrs_backups"
INVARIANTS_DIR = AICORE_DATA / "invariants"
ERROR_SCREENSHOTS_DIR = AICORE_DATA / "error_screenshots"
SYSTEM_CONTROL_DIR = AICORE_DATA / "system_control"
TRAINING_LOG_DIR = AICORE_LOG / "training"
SANDBOX_DIR = AICORE_DATA / "sandbox"

# Models and voices (downloaded by install.sh)
MODELS_DIR = Path(os.environ.get(
    "AICORE_MODELS_DIR",
    str(AICORE_DATA / "models")
))
VOICES_DIR = Path(os.environ.get(
    "AICORE_VOICES_DIR",
    str(AICORE_DATA / "voices")
))

# Source subdirectories
TOOLS_DIR = AICORE_ROOT / "tools"
SERVICES_DIR = AICORE_ROOT / "services"
UI_DIR = AICORE_ROOT / "ui"
PERSONALITY_DIR = AICORE_ROOT / "personality"
SOUNDS_DIR = UI_DIR / "sounds"


def ensure_dirs():
    """Create all required data directories. Called by install.sh and on first run."""
    for d in [
        AICORE_DATA, AICORE_CONFIG, AICORE_LOG, DB_DIR, STATE_DIR,
        JOURNAL_DIR, ADI_PROFILES_DIR, ASRS_BACKUP_DIR, INVARIANTS_DIR,
        ERROR_SCREENSHOTS_DIR, SYSTEM_CONTROL_DIR, MODELS_DIR, VOICES_DIR,
        TRAINING_LOG_DIR, SANDBOX_DIR,
    ]:
        d.mkdir(parents=True, exist_ok=True)


def get_db(name: str) -> Path:
    """Get database path by name. Creates parent dir if needed."""
    p = DB_PATHS.get(name)
    if p is None:
        p = DB_DIR / f"{name}.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_state(name: str) -> Path:
    """Get state file path by name. Creates parent dir if needed."""
    p = STATE_PATHS.get(name)
    if p is None:
        p = STATE_DIR / f"{name}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_temp(name: str) -> Path:
    """Get a temp file path (e.g. get_temp('voice_event.json'))."""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    return TEMP_DIR / name


def get_runtime(name: str) -> Path:
    """Get a runtime file path (e.g. get_runtime('asrs_daemon.sock'))."""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    return RUNTIME_DIR / name


def get_lock(name: str) -> Path:
    """Get a lock file path (e.g. get_lock('overlay.lock'))."""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    return TEMP_DIR / f"{name}.lock"


# === Well-known temp/IPC file names ===
# Modules SHOULD use these instead of hardcoding /tmp/frank_*

TEMP_FILES = {
    # Voice IPC
    "voice_event": TEMP_DIR / "voice_event.json",
    "voice_outbox": TEMP_DIR / "voice_outbox.json",

    # Overlay signals
    "overlay_lock": TEMP_DIR / "overlay.lock",
    "overlay_show": TEMP_DIR / "overlay_show",
    "overlay_heartbeat": TEMP_DIR / "overlay_heartbeat",
    "overlay_stderr_log": TEMP_DIR / "overlay_stderr.log",

    # Tray
    "tray_toggle": TEMP_DIR / "tray_toggle",
    "tray_quit": TEMP_DIR / "tray_quit",
    "tray_log": TEMP_DIR / "tray.log",

    # Gaming mode
    "gaming_lock": TEMP_DIR / "gaming_lock",
    "gaming_mode_state": TEMP_DIR / "gaming_mode_state.json",
    "user_closed": TEMP_DIR / "user_closed",

    # Shutdown / startup signals
    "full_shutdown": TEMP_DIR / "full_shutdown",
    "full_startup": TEMP_DIR / "full_startup",

    # Agentic approval
    "approval_queue": TEMP_DIR / "approval_queue.json",
    "approval_responses": TEMP_DIR / "approval_responses.json",

    # Notifications
    "notifications_dir": TEMP_DIR / "notifications",

    # Icons cache
    "icons_dir": TEMP_DIR / "icons",

    # Watchdog
    "watchdog_health": TEMP_DIR / "watchdog_health.json",
    "restart_request": TEMP_DIR / "restart_request.json",
    "restart_result": TEMP_DIR / "restart_result.json",
    "mpc_llama_parked": TEMP_DIR / "mpc_llama_parked",

    # LLM Guard
    "llm_guard_health": TEMP_DIR / "llm_guard_health.json",

    # News scanner
    "news_scanner_state": TEMP_DIR / "news_scanner_state.json",
    "news_scanner_log": TEMP_DIR / "news_scanner.log",

    # Notification daemon
    "notification_state": TEMP_DIR / "notification_state.json",
    "notification_daemon_log": TEMP_DIR / "notification_daemon.log",

    # Genesis
    "genesis_popup_result": TEMP_DIR / "genesis_popup_result.json",
    "genesis_pending_proposals": TEMP_DIR / "genesis_pending_proposals.json",
    "genesis_notification": TEMP_DIR / "genesis_notification.json",
    "genesis_health": TEMP_DIR / "genesis_health.json",
    "genesis_shown": TEMP_DIR / "genesis_shown.json",

    # ASRS
    "asrs_notification": TEMP_DIR / "asrs_notification.json",
    "asrs_safe_mode": TEMP_DIR / "aicore_safe_mode",
    "asrs_daemon_log": TEMP_DIR / "asrs_daemon.log",
    "asrs_monitor_queue": TEMP_DIR / "asrs_monitor_queue.json",

    # Gateway
    "gateway_log": TEMP_DIR / "gateway.log",

    # E-WISH
    "ewish_daemon_log": TEMP_DIR / "ewish_daemon.log",
    "ewish_daemon_state": TEMP_DIR / "ewish_daemon_state.json",
    "user_patterns": TEMP_DIR / "user_patterns.json",

    # Proactive controller
    "proactive_state": TEMP_DIR / "proactive_state.json",

    # FAS / ADI / E-WISH dim signals
    "fas_dim_signal": TEMP_DIR / "fas_dim_signal",
    "adi_dim_signal": TEMP_DIR / "adi_dim_signal",
    "adi_apply_signal": TEMP_DIR / "adi_apply_signal",
    "ewish_dim_signal": TEMP_DIR / "ewish_dim_signal",
    "ewish_popup_state": TEMP_DIR / "ewish_popup_state.json",

    # Vision debug
    "vision_debug_log": TEMP_DIR / "vision_debug.log",

    # Calendar
    "reminded_uids": TEMP_DIR / "reminded_uids.txt",
}
