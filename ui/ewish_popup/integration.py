#!/usr/bin/env python3
"""
E-WISH Integration Module
Connects E-WISH backend with the popup UI and chat overlay.
"""

import json
import logging
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, Optional, Any

LOG = logging.getLogger("ewish_integration")

# Paths
try:
    from config.paths import AICORE_ROOT
except ImportError:
    AICORE_ROOT = Path("/home/ai-core-node/aicore/opt/aicore")
POPUP_SCRIPT = AICORE_ROOT / "ui" / "ewish_popup" / "main_window.py"
STATE_FILE = Path("/tmp/ewish_popup_state.json")


class EWishIntegration:
    """
    Integration layer between E-WISH and the rest of the system.

    Handles:
    - Triggering the popup
    - Processing cycles
    - Callback management
    - State persistence
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._response_callbacks: list = []
        self._last_popup_time: Optional[datetime] = None
        self._popup_process: Optional[subprocess.Popen] = None
        self._min_interval_hours = 4
        self._max_popups_per_day = 3
        self._popups_today: list = []

        self._load_state()
        self._initialized = True

        LOG.info("E-WISH Integration initialized")

    def _load_state(self):
        """Load state from file."""
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text())
                if data.get("last_popup_time"):
                    self._last_popup_time = datetime.fromisoformat(data["last_popup_time"])
                self._popups_today = data.get("popups_today", [])

                # Clean old popups
                today = datetime.now().date().isoformat()
                self._popups_today = [p for p in self._popups_today if p.startswith(today)]
            except Exception as e:
                LOG.warning(f"Could not load state: {e}")

    def _save_state(self):
        """Save state to file."""
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps({
                "last_popup_time": self._last_popup_time.isoformat() if self._last_popup_time else None,
                "popups_today": self._popups_today,
            }, indent=2))
        except Exception as e:
            LOG.warning(f"Could not save state: {e}")

    def add_response_callback(self, callback: Callable[[str, Any, str], None]):
        """
        Add callback for when user responds to a wish.

        Callback signature: (action: str, wish: Wish, response: str)
        Actions: "approved", "rejected", "postponed", "more_info", "approved_with_message"
        """
        self._response_callbacks.append(callback)

    def remove_response_callback(self, callback: Callable):
        """Remove a response callback."""
        if callback in self._response_callbacks:
            self._response_callbacks.remove(callback)

    def _notify_callbacks(self, action: str, wish, response: str):
        """Notify all callbacks."""
        for cb in self._response_callbacks:
            try:
                cb(action, wish, response)
            except Exception as e:
                LOG.error(f"Callback error: {e}")

    def can_show_popup(self, context: Dict = None) -> tuple:
        """
        Check if we can show a popup now.

        Returns: (can_show, reason)
        """
        context = context or {}

        # Check gaming mode
        if context.get("gaming_mode", False):
            return False, "Gaming mode active"

        # Check daily limit
        today = datetime.now().date().isoformat()
        self._popups_today = [p for p in self._popups_today if p.startswith(today)]
        if len(self._popups_today) >= self._max_popups_per_day:
            return False, f"Daily limit reached ({len(self._popups_today)}/{self._max_popups_per_day})"

        # Check cooldown
        if self._last_popup_time:
            hours_since = (datetime.now() - self._last_popup_time).total_seconds() / 3600
            if hours_since < self._min_interval_hours:
                return False, f"Cooldown: {self._min_interval_hours - hours_since:.1f}h remaining"

        # Check if user is active
        if not context.get("user_active", True):
            return False, "User not active"

        return True, "OK"

    def trigger_popup(self, wish_id: str = None, force: bool = False) -> bool:
        """
        Trigger the E-WISH popup.

        Args:
            wish_id: Specific wish to show (or None for top wish)
            force: Bypass cooldown/limit checks

        Returns:
            True if popup was triggered
        """
        if not force:
            can_show, reason = self.can_show_popup()
            if not can_show:
                LOG.info(f"Cannot show popup: {reason}")
                return False

        # Check if popup already running
        if self._popup_process and self._popup_process.poll() is None:
            LOG.info("Popup already running")
            return False

        # Build command
        cmd = ["python3", str(POPUP_SCRIPT)]
        if wish_id:
            cmd.extend(["--wish-id", wish_id])

        try:
            # Start popup in background
            env = {
                **dict(__import__('os').environ),
                "DISPLAY": ":0",
                "PYTHONPATH": str(AICORE_ROOT),
            }

            self._popup_process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # Record popup shown
            self._last_popup_time = datetime.now()
            self._popups_today.append(datetime.now().isoformat())
            self._save_state()

            LOG.info(f"E-WISH popup triggered (wish_id={wish_id})")
            return True

        except Exception as e:
            LOG.error(f"Failed to trigger popup: {e}")
            return False

    def process_cycle(self, context: Dict = None) -> Optional[str]:
        """
        Run E-WISH processing cycle.
        Call this periodically (e.g., every 5 minutes).

        Args:
            context: Dict with self_model, reflection, last_interaction, etc.

        Returns:
            Wish expression string if one should be shown, None otherwise
        """
        context = context or {}

        try:
            from ext.e_wish import get_ewish

            ewish = get_ewish()

            # Set popup callback
            def popup_callback(wish):
                self.trigger_popup(wish.id)

            ewish.set_popup_callback(popup_callback)

            # Run cycle
            expression = ewish.process_cycle(context)

            return expression

        except ImportError as e:
            LOG.warning(f"E-WISH not available: {e}")
            return None
        except Exception as e:
            LOG.error(f"E-WISH cycle error: {e}")
            return None

    def get_status(self) -> Dict:
        """Get integration status."""
        try:
            from ext.e_wish import get_ewish
            ewish = get_ewish()
            ewish_status = ewish.get_status()
        except Exception:
            ewish_status = {"error": "E-WISH not available"}

        today = datetime.now().date().isoformat()
        popups_today = len([p for p in self._popups_today if p.startswith(today)])

        return {
            "ewish": ewish_status,
            "popups_today": popups_today,
            "max_popups_per_day": self._max_popups_per_day,
            "last_popup": self._last_popup_time.isoformat() if self._last_popup_time else None,
            "cooldown_hours": self._min_interval_hours,
            "popup_running": self._popup_process is not None and self._popup_process.poll() is None,
        }

    def add_test_wish(self, description: str = None) -> Optional[str]:
        """Add a test wish and return its ID."""
        try:
            from ext.e_wish import get_ewish, WishCategory

            ewish = get_ewish()
            wish = ewish.add_manual_wish(
                description or "Test-Wunsch: Ich möchte diese Funktion testen",
                WishCategory.EXPERIENCE,
                "Manuell für Testing hinzugefügt"
            )
            return wish.id

        except Exception as e:
            LOG.error(f"Could not add test wish: {e}")
            return None


# Singleton access
_integration: Optional[EWishIntegration] = None


def get_ewish_integration() -> EWishIntegration:
    """Get E-WISH integration singleton."""
    global _integration
    if _integration is None:
        _integration = EWishIntegration()
    return _integration


def trigger_wish_popup(wish_id: str = None, force: bool = False) -> bool:
    """Convenience function to trigger popup."""
    return get_ewish_integration().trigger_popup(wish_id, force)


def run_ewish_cycle(context: Dict = None) -> Optional[str]:
    """Convenience function to run E-WISH cycle."""
    return get_ewish_integration().process_cycle(context)


# CLI for testing
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    integration = get_ewish_integration()

    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "status":
            status = integration.get_status()
            print(json.dumps(status, indent=2))

        elif cmd == "trigger":
            wish_id = sys.argv[2] if len(sys.argv) > 2 else None
            success = integration.trigger_popup(wish_id, force=True)
            print(f"Triggered: {success}")

        elif cmd == "test":
            # Add test wish and trigger popup
            wish_id = integration.add_test_wish()
            if wish_id:
                print(f"Added test wish: {wish_id}")
                success = integration.trigger_popup(wish_id, force=True)
                print(f"Triggered: {success}")
            else:
                print("Failed to add test wish")

        elif cmd == "cycle":
            # Run a cycle with test context
            context = {
                "user_active": True,
                "gaming_mode": False,
            }
            result = integration.process_cycle(context)
            print(f"Cycle result: {result}")

        else:
            print("Usage: integration.py [status|trigger [wish_id]|test|cycle]")
    else:
        print("E-WISH Integration")
        status = integration.get_status()
        print(f"Popups today: {status['popups_today']}/{status['max_popups_per_day']}")
        print(f"Popup running: {status['popup_running']}")
