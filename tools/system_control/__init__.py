#!/usr/bin/env python3
"""
Frank System Control - Intelligent System Management

Provides context-aware system control capabilities with double opt-in
for sensitive actions.

Components:
    - sensitive_actions: Double opt-in confirmation framework
    - file_organizer: File organization with preview and undo
    - network_manager: WiFi, device discovery, key extraction
    - hardware_autosetup: Printer auto-setup with driver download
    - system_settings: Display, audio, bluetooth settings
    - chat_integration: Natural language processing for chat overlay
"""

__version__ = "1.0.0"

from .sensitive_actions import (
    SensitiveActionHandler,
    ConfirmationState,
    ConfirmationLevel,
    request_confirmation,
    is_action_confirmed,
    cancel_pending_action,
    confirm_action,
    get_pending_actions,
)

from .chat_integration import (
    process_system_control,
    set_response_callback,
    has_pending_action,
    get_pending_action_type,
)

__all__ = [
    # Sensitive Actions
    "SensitiveActionHandler",
    "ConfirmationState",
    "ConfirmationLevel",
    "request_confirmation",
    "is_action_confirmed",
    "cancel_pending_action",
    "confirm_action",
    "get_pending_actions",
    # Chat Integration
    "process_system_control",
    "set_response_callback",
    "has_pending_action",
    "get_pending_action_type",
    # Startup
    "startup_network_scan",
]


def startup_network_scan():
    """
    Perform startup network scan.

    Called when Frank starts to discover network devices.
    """
    import threading
    import logging

    LOG = logging.getLogger("system_control")

    def _scan():
        try:
            from .network_manager import discover_devices
            devices = discover_devices()
            total = sum(len(devs) for devs in devices.values())
            LOG.info(f"Startup scan complete: {total} devices in {len(devices)} categories")
        except Exception as e:
            LOG.warning(f"Startup network scan failed: {e}")

    # Run in background to not block startup
    thread = threading.Thread(target=_scan, daemon=True, name="StartupNetScan")
    thread.start()
