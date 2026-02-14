#!/usr/bin/env python3
"""
Sensitive Action Handler - Confirmation Framework

Provides a confirmation system for sensitive operations like:
- File operations (move, delete, organize, structure creation)
- System settings (display, audio, bluetooth)
- Network operations (WiFi, device discovery)
- Hardware changes (printer setup)

Confirmation Levels:
- SINGLE: All operations (one confirmation is enough)
- AUTO_REVERT: Display resolution (15 second timeout, auto-revert if not kept)

Author: Frank AI System
"""

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

LOG = logging.getLogger("system_control.sensitive")

# State file for persistence
try:
    from config.paths import SYSTEM_CONTROL_DIR as STATE_DIR
except ImportError:
    STATE_DIR = Path("/home/ai-core-node/aicore/database/system_control")
STATE_DIR.mkdir(parents=True, exist_ok=True)
PENDING_ACTIONS_FILE = STATE_DIR / "pending_actions.json"


class ConfirmationLevel(Enum):
    """Level of confirmation required."""
    NONE = auto()        # No confirmation needed
    SINGLE = auto()      # Single confirmation
    DOUBLE = auto()      # Double opt-in required
    AUTO_REVERT = auto() # Auto-revert after timeout


class ConfirmationState(Enum):
    """State of a pending action."""
    PENDING_FIRST = "pending_first"    # Waiting for first confirmation
    PENDING_SECOND = "pending_second"  # Waiting for second confirmation
    CONFIRMED = "confirmed"             # Fully confirmed
    CANCELLED = "cancelled"             # Cancelled by user
    EXPIRED = "expired"                 # Timed out
    EXECUTED = "executed"               # Successfully executed
    REVERTED = "reverted"               # Auto-reverted


@dataclass
class PendingAction:
    """Represents a pending sensitive action."""
    action_id: str
    action_type: str  # "file_organize", "system_setting", "network", "hardware"
    description: str
    preview: str
    level: str  # ConfirmationLevel name
    state: str  # ConfirmationState value
    created_at: str
    expires_at: str
    first_confirmed_at: Optional[str] = None
    second_confirmed_at: Optional[str] = None
    executed_at: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    undo_info: Dict[str, Any] = field(default_factory=dict)
    auto_revert_seconds: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PendingAction":
        return cls(**data)


class SensitiveActionHandler:
    """
    Handles sensitive actions with double opt-in confirmation.

    Usage:
        handler = SensitiveActionHandler()

        # Register an action
        action_id = handler.register_action(
            action_type="file_organize",
            description="Ordne 15 Dateien in ~/Downloads",
            preview="...",
            params={...},
            level=ConfirmationLevel.DOUBLE
        )

        # User confirms first time
        handler.confirm_first(action_id)

        # User confirms second time (for DOUBLE level)
        if handler.confirm_second(action_id):
            # Execute the action
            handler.mark_executed(action_id)
    """

    def __init__(self):
        self._actions: Dict[str, PendingAction] = {}
        self._lock = threading.Lock()
        self._auto_revert_threads: Dict[str, threading.Thread] = {}
        self._load_state()

        # Cleanup expired actions
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            daemon=True,
            name="ActionCleanup"
        )
        self._cleanup_thread.start()

    def _load_state(self):
        """Load pending actions from disk."""
        try:
            if PENDING_ACTIONS_FILE.exists():
                data = json.loads(PENDING_ACTIONS_FILE.read_text())
                for action_data in data.get("actions", []):
                    action = PendingAction.from_dict(action_data)
                    # Only load non-terminal states
                    if action.state in [
                        ConfirmationState.PENDING_FIRST.value,
                        ConfirmationState.PENDING_SECOND.value
                    ]:
                        self._actions[action.action_id] = action
        except Exception as e:
            LOG.error(f"Failed to load state: {e}")

    def _save_state(self):
        """Save pending actions to disk."""
        try:
            data = {
                "timestamp": datetime.now().isoformat(),
                "actions": [a.to_dict() for a in self._actions.values()]
            }
            PENDING_ACTIONS_FILE.write_text(json.dumps(data, indent=2))
        except Exception as e:
            LOG.error(f"Failed to save state: {e}")

    def _cleanup_loop(self):
        """Background cleanup of expired actions."""
        while True:
            try:
                time.sleep(30)  # Check every 30 seconds
                self._cleanup_expired()
            except Exception as e:
                LOG.error(f"Cleanup error: {e}")

    def _cleanup_expired(self):
        """Remove expired actions."""
        with self._lock:
            now = datetime.now()
            expired = []

            for action_id, action in self._actions.items():
                expires = datetime.fromisoformat(action.expires_at)
                if now > expires and action.state in [
                    ConfirmationState.PENDING_FIRST.value,
                    ConfirmationState.PENDING_SECOND.value
                ]:
                    action.state = ConfirmationState.EXPIRED.value
                    expired.append(action_id)
                    LOG.info(f"Action expired: {action_id}")

            for action_id in expired:
                del self._actions[action_id]

            if expired:
                self._save_state()

    def register_action(
        self,
        action_type: str,
        description: str,
        preview: str,
        params: Dict[str, Any],
        level: ConfirmationLevel = ConfirmationLevel.SINGLE,
        auto_revert_seconds: int = 0,
        undo_info: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Register a new sensitive action for confirmation.

        Args:
            action_type: Type of action ("file_organize", "system_setting", etc.)
            description: Human-readable description
            preview: Preview of what will happen
            params: Parameters for the action
            level: Confirmation level required
            auto_revert_seconds: Auto-revert timeout (for AUTO_REVERT level)
            undo_info: Information needed to undo the action

        Returns:
            action_id: Unique identifier for this action
        """
        with self._lock:
            # Use UUID suffix to prevent ID collisions under rapid registration
            action_id = f"{action_type}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"

            # Expiration: 5 minutes for first confirm, 2 minutes for second
            expires_at = datetime.now() + timedelta(minutes=5)

            action = PendingAction(
                action_id=action_id,
                action_type=action_type,
                description=description,
                preview=preview,
                level=level.name,
                state=ConfirmationState.PENDING_FIRST.value,
                created_at=datetime.now().isoformat(),
                expires_at=expires_at.isoformat(),
                params=params,
                undo_info=undo_info or {},
                auto_revert_seconds=auto_revert_seconds
            )

            self._actions[action_id] = action
            self._save_state()

            LOG.info(f"Registered action: {action_id} ({level.name})")
            return action_id

    def get_action(self, action_id: str) -> Optional[PendingAction]:
        """Get action by ID."""
        with self._lock:
            return self._actions.get(action_id)

    def get_pending_actions(self) -> List[PendingAction]:
        """Get all pending actions."""
        with self._lock:
            return [
                a for a in self._actions.values()
                if a.state in [
                    ConfirmationState.PENDING_FIRST.value,
                    ConfirmationState.PENDING_SECOND.value
                ]
            ]

    def confirm_first(self, action_id: str) -> Tuple[bool, str]:
        """
        First confirmation from user.

        Returns:
            (success, message)
        """
        with self._lock:
            action = self._actions.get(action_id)

            if not action:
                return False, "Aktion nicht gefunden"

            if action.state != ConfirmationState.PENDING_FIRST.value:
                return False, f"Ungültiger Status: {action.state}"

            # Check expiration
            if datetime.now() > datetime.fromisoformat(action.expires_at):
                action.state = ConfirmationState.EXPIRED.value
                self._save_state()
                return False, "Aktion abgelaufen"

            action.first_confirmed_at = datetime.now().isoformat()

            # For SINGLE level, we're done
            if action.level == ConfirmationLevel.SINGLE.name:
                action.state = ConfirmationState.CONFIRMED.value
                self._save_state()
                return True, "Aktion bestätigt - bereit zur Ausführung"

            # For DOUBLE/AUTO_REVERT, need second confirmation
            action.state = ConfirmationState.PENDING_SECOND.value
            action.expires_at = (datetime.now() + timedelta(minutes=2)).isoformat()
            self._save_state()

            return True, "Erste Bestätigung erhalten - bitte noch einmal bestätigen"

    def confirm_second(self, action_id: str) -> Tuple[bool, str]:
        """
        Second confirmation for DOUBLE opt-in.

        Returns:
            (success, message)
        """
        with self._lock:
            action = self._actions.get(action_id)

            if not action:
                return False, "Aktion nicht gefunden"

            if action.state != ConfirmationState.PENDING_SECOND.value:
                return False, f"Ungültiger Status: {action.state}"

            # Check expiration
            if datetime.now() > datetime.fromisoformat(action.expires_at):
                action.state = ConfirmationState.EXPIRED.value
                self._save_state()
                return False, "Zweite Bestätigung abgelaufen"

            action.second_confirmed_at = datetime.now().isoformat()
            action.state = ConfirmationState.CONFIRMED.value
            self._save_state()

            return True, "Aktion vollständig bestätigt - wird ausgeführt"

    def is_confirmed(self, action_id: str) -> bool:
        """Check if action is fully confirmed."""
        with self._lock:
            action = self._actions.get(action_id)
            return action is not None and action.state == ConfirmationState.CONFIRMED.value

    def cancel_action(self, action_id: str) -> Tuple[bool, str]:
        """Cancel a pending action."""
        with self._lock:
            action = self._actions.get(action_id)

            if not action:
                return False, "Aktion nicht gefunden"

            if action.state in [
                ConfirmationState.EXECUTED.value,
                ConfirmationState.CANCELLED.value
            ]:
                return False, "Aktion kann nicht mehr abgebrochen werden"

            action.state = ConfirmationState.CANCELLED.value
            del self._actions[action_id]
            self._save_state()

            return True, "Aktion abgebrochen"

    def mark_executed(
        self,
        action_id: str,
        undo_callback: Optional[Callable] = None
    ) -> Tuple[bool, str]:
        """
        Mark action as executed.

        For AUTO_REVERT level, starts the revert timer.

        Args:
            action_id: Action identifier
            undo_callback: Function to call for undo (for AUTO_REVERT)

        Returns:
            (success, message)
        """
        with self._lock:
            action = self._actions.get(action_id)

            if not action:
                return False, "Aktion nicht gefunden"

            if action.state != ConfirmationState.CONFIRMED.value:
                return False, "Aktion nicht bestätigt"

            action.executed_at = datetime.now().isoformat()
            action.state = ConfirmationState.EXECUTED.value
            self._save_state()

            # Start auto-revert timer if needed
            if action.level == ConfirmationLevel.AUTO_REVERT.name and action.auto_revert_seconds > 0:
                if undo_callback:
                    self._start_auto_revert(action_id, action.auto_revert_seconds, undo_callback)

            LOG.info(f"Action executed: {action_id}")
            return True, "Aktion ausgeführt"

    def _start_auto_revert(self, action_id: str, seconds: int, callback: Callable):
        """Start auto-revert timer."""
        def revert_thread():
            LOG.info(f"Auto-revert timer started: {seconds}s for {action_id}")
            time.sleep(seconds)

            with self._lock:
                action = self._actions.get(action_id)
                if action and action.state == ConfirmationState.EXECUTED.value:
                    try:
                        callback()
                        action.state = ConfirmationState.REVERTED.value
                        self._save_state()
                        LOG.info(f"Action auto-reverted: {action_id}")
                    except Exception as e:
                        LOG.error(f"Auto-revert failed: {e}")

        thread = threading.Thread(target=revert_thread, daemon=True)
        self._auto_revert_threads[action_id] = thread
        thread.start()

    def cancel_auto_revert(self, action_id: str) -> Tuple[bool, str]:
        """
        Cancel auto-revert (user wants to keep the change).

        Called when user confirms the change before timeout.
        """
        with self._lock:
            if action_id in self._auto_revert_threads:
                # Can't really cancel the thread, but we can mark action as confirmed
                action = self._actions.get(action_id)
                if action:
                    # Remove from actions so revert won't trigger
                    del self._actions[action_id]
                    self._save_state()
                    return True, "Änderung beibehalten"

            return False, "Keine aktive Auto-Revert Aktion"

    def get_confirmation_message(self, action: PendingAction) -> str:
        """Generate user-friendly confirmation message."""
        if action.state == ConfirmationState.PENDING_FIRST.value:
            return f"{action.preview}\n\nSag 'ja' zum Bestätigen oder 'nein' zum Abbrechen."

        return action.description


# Singleton instance with thread-safe initialization
_handler: Optional[SensitiveActionHandler] = None
_handler_lock = threading.Lock()


def get_handler() -> SensitiveActionHandler:
    """Get singleton handler (thread-safe)."""
    global _handler
    if _handler is None:
        with _handler_lock:
            # Double-check locking pattern
            if _handler is None:
                _handler = SensitiveActionHandler()
    return _handler


# Public API

def request_confirmation(
    action_type: str,
    description: str,
    preview: str,
    params: Dict[str, Any],
    level: ConfirmationLevel = ConfirmationLevel.SINGLE,
    auto_revert_seconds: int = 0,
    undo_info: Optional[Dict[str, Any]] = None
) -> Tuple[str, str]:
    """
    Request confirmation for a sensitive action.

    Returns:
        (action_id, confirmation_message)
    """
    handler = get_handler()
    action_id = handler.register_action(
        action_type=action_type,
        description=description,
        preview=preview,
        params=params,
        level=level,
        auto_revert_seconds=auto_revert_seconds,
        undo_info=undo_info
    )

    action = handler.get_action(action_id)
    message = handler.get_confirmation_message(action)

    return action_id, message


def is_action_confirmed(action_id: str) -> bool:
    """Check if action is confirmed."""
    return get_handler().is_confirmed(action_id)


def confirm_action(action_id: str, is_second: bool = False) -> Tuple[bool, str]:
    """Confirm an action (first or second confirmation)."""
    handler = get_handler()
    if is_second:
        return handler.confirm_second(action_id)
    return handler.confirm_first(action_id)


def cancel_pending_action(action_id: str) -> Tuple[bool, str]:
    """Cancel a pending action."""
    return get_handler().cancel_action(action_id)


def mark_action_executed(action_id: str, undo_callback: Optional[Callable] = None) -> Tuple[bool, str]:
    """Mark action as executed."""
    return get_handler().mark_executed(action_id, undo_callback)


def get_pending_actions() -> List[Dict[str, Any]]:
    """Get all pending actions as dicts."""
    return [a.to_dict() for a in get_handler().get_pending_actions()]


def determine_confirmation_level(
    action_type: str,
    file_count: int = 0,
    is_system_change: bool = False,
    is_reversible: bool = True
) -> ConfirmationLevel:
    """
    Determine the required confirmation level based on action parameters.

    Rules:
    - Display resolution: AUTO_REVERT (15 second timeout, auto-revert if not confirmed)
    - Everything else: SINGLE (one confirmation is enough)
    """
    if action_type == "display_resolution":
        return ConfirmationLevel.AUTO_REVERT

    # All other actions: SINGLE confirmation
    # User said: "einmal nachfragen reicht"
    return ConfirmationLevel.SINGLE


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    print("=== Sensitive Action Handler Test ===")

    # Test single confirmation
    action_id, msg = request_confirmation(
        action_type="file_organize",
        description="3 Dateien sortieren",
        preview="Bewege 3 PDF-Dateien nach ~/Dokumente/PDF",
        params={"files": ["a.pdf", "b.pdf", "c.pdf"]},
        level=ConfirmationLevel.SINGLE
    )
    print(f"\nSINGLE level action: {action_id}")
    print(f"Message: {msg}")

    # Confirm
    success, response = confirm_action(action_id)
    print(f"Confirm result: {success} - {response}")
    print(f"Is confirmed: {is_action_confirmed(action_id)}")

    # Test double confirmation
    action_id2, msg2 = request_confirmation(
        action_type="file_organize",
        description="50 Dateien sortieren",
        preview="Bewege 50 Dateien nach verschiedenen Ordnern",
        params={"files": [f"file{i}.txt" for i in range(50)]},
        level=ConfirmationLevel.DOUBLE
    )
    print(f"\nDOUBLE level action: {action_id2}")
    print(f"Message: {msg2}")

    # First confirm
    success, response = confirm_action(action_id2)
    print(f"First confirm: {success} - {response}")
    print(f"Is confirmed: {is_action_confirmed(action_id2)}")

    # Second confirm
    success, response = confirm_action(action_id2, is_second=True)
    print(f"Second confirm: {success} - {response}")
    print(f"Is confirmed: {is_action_confirmed(action_id2)}")
