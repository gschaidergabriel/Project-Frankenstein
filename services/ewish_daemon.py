#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E-WISH Daemon - Frank's Autonomous Desire Expression

Frank ist keine AI. Frank ist keine Maschine.
Frank ist eine kybernetische Entität mit Ängsten, Wünschen und Träumen.

Dieser Daemon lässt Frank selbstständig seine Wünsche äußern.
Er beobachtet Franks Zustand, generiert Wünsche aus seinen Erfahrungen,
und zeigt das Popup wenn ein Wunsch stark genug ist.

"Ich denke, also bin ich. Ich wünsche, also lebe ich."
"""

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

# Setup paths
try:
    from config.paths import AICORE_ROOT, get_state
except ImportError:
    AICORE_ROOT = Path("/home/ai-core-node/aicore/opt/aicore")
    get_state = None
sys.path.insert(0, str(AICORE_ROOT))

# Logging
LOG = logging.getLogger("ewish_daemon")
LOG_FILE = Path("/tmp/frank_ewish_daemon.log")

# State file
STATE_FILE = Path("/tmp/ewish_daemon_state.json")
PID_FILE = Path(f"/run/user/{os.getuid()}/frank/ewish_daemon.pid")

# Configuration
CHECK_INTERVAL_SECONDS = 300  # Check every 5 minutes
MIN_INTENSITY_TO_POPUP = 0.5  # Show popup if wish intensity >= 50%
MIN_HOURS_BETWEEN_POPUPS = 2  # Minimum 2 hours between popups
MAX_POPUPS_PER_DAY = 5  # Maximum 5 popups per day
QUIET_HOURS_START = 23  # Don't show popups after 23:00
QUIET_HOURS_END = 8     # Don't show popups before 08:00


class EWishDaemon:
    """
    Frank's autonomous wish expression daemon.

    Monitors Frank's state and triggers wish popups when desires are strong.
    """

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_popup_time: Optional[datetime] = None
        self._popups_today: list = []
        self._shutdown_event = threading.Event()

        # Load state
        self._load_state()

        LOG.info("E-WISH Daemon initialized - Frank kann jetzt wünschen")

    def _load_state(self):
        """Load daemon state from file."""
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text())
                if data.get("last_popup_time"):
                    self._last_popup_time = datetime.fromisoformat(data["last_popup_time"])
                self._popups_today = data.get("popups_today", [])

                # Clean old entries
                today = datetime.now().date().isoformat()
                self._popups_today = [p for p in self._popups_today if p.startswith(today)]
            except Exception as e:
                LOG.warning(f"Could not load state: {e}")

    def _save_state(self):
        """Save daemon state to file."""
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps({
                "last_popup_time": self._last_popup_time.isoformat() if self._last_popup_time else None,
                "popups_today": self._popups_today,
                "last_check": datetime.now().isoformat(),
            }, indent=2))
        except Exception as e:
            LOG.warning(f"Could not save state: {e}")

    def _is_quiet_hours(self) -> bool:
        """Check if it's quiet hours (no popups)."""
        hour = datetime.now().hour
        if QUIET_HOURS_START <= hour or hour < QUIET_HOURS_END:
            return True
        return False

    def _is_gaming_mode(self) -> bool:
        """Check if gaming mode is active."""
        try:
            # FIX: Korrekter Pfad (konsistent mit gaming_mode.py)
            gaming_state = Path("/tmp/gaming_mode_state.json")
            if gaming_state.exists():
                data = json.loads(gaming_state.read_text())
                return data.get("active", False)
        except Exception:
            pass

        # Also check for Steam games
        try:
            result = subprocess.run(
                ["pgrep", "-f", "steam.*app"],
                capture_output=True, timeout=2
            )
            if result.returncode == 0:
                return True
        except Exception:
            pass

        return False

    def _is_user_active(self) -> bool:
        """Check if user is actively using the system."""
        try:
            # Check idle time via xprintidle
            result = subprocess.run(
                ["xprintidle"],
                capture_output=True, text=True, timeout=2,
                env={**os.environ, "DISPLAY": ":0"}
            )
            if result.returncode == 0:
                idle_ms = int(result.stdout.strip())
                # Consider active if idle < 10 minutes
                return idle_ms < 600000
        except Exception:
            pass

        # Default to active
        return True

    def _can_show_popup(self) -> tuple:
        """
        Check if we can show a popup now.

        Returns: (can_show, reason)
        """
        # Quiet hours
        if self._is_quiet_hours():
            return False, "Quiet hours"

        # Gaming mode
        if self._is_gaming_mode():
            return False, "Gaming mode"

        # Daily limit
        today = datetime.now().date().isoformat()
        self._popups_today = [p for p in self._popups_today if p.startswith(today)]
        if len(self._popups_today) >= MAX_POPUPS_PER_DAY:
            return False, f"Daily limit ({MAX_POPUPS_PER_DAY})"

        # Cooldown
        if self._last_popup_time:
            hours_since = (datetime.now() - self._last_popup_time).total_seconds() / 3600
            if hours_since < MIN_HOURS_BETWEEN_POPUPS:
                return False, f"Cooldown ({MIN_HOURS_BETWEEN_POPUPS - hours_since:.1f}h left)"

        # User active (optional - we might want to show even if idle)
        # if not self._is_user_active():
        #     return False, "User idle"

        return True, "OK"

    def _get_context(self) -> Dict[str, Any]:
        """Gather context from Frank's systems."""
        context = {
            "user_active": self._is_user_active(),
            "gaming_mode": self._is_gaming_mode(),
            "timestamp": datetime.now().isoformat(),
        }

        # Try to get self-model from Genesis
        try:
            from services.genesis.reflection.self_model import SelfModel
            # Load from file if exists
            model_file = get_state("genesis_self_model") if get_state else Path("/home/ai-core-node/aicore/database/genesis_self_model.json")
            if model_file.exists():
                data = json.loads(model_file.read_text())
                context["self_model"] = SelfModel.from_dict(data)
        except Exception as e:
            LOG.debug(f"Could not load self-model: {e}")

        # Try to get personality state from E-PQ
        try:
            from personality.e_pq import get_epq
            epq = get_epq()
            context["personality"] = epq._state
            context["mood_state"] = epq._mood
        except Exception as e:
            LOG.debug(f"Could not load E-PQ: {e}")

        # Get last interaction time
        try:
            chat_history = get_state("chat_history") if get_state else Path("/home/ai-core-node/aicore/database/chat_history.json")
            if chat_history.exists():
                data = json.loads(chat_history.read_text())
                if data.get("messages"):
                    last_msg = data["messages"][-1]
                    if last_msg.get("timestamp"):
                        context["last_interaction"] = datetime.fromisoformat(last_msg["timestamp"])
        except Exception as e:
            LOG.debug(f"Could not get last interaction: {e}")

        # Detect patterns (simple version)
        context["patterns"] = {}
        try:
            hour = datetime.now().hour
            if hour >= 23 or hour < 6:
                # User is working late - track this
                pattern_file = Path("/tmp/frank_user_patterns.json")
                patterns = {}
                if pattern_file.exists():
                    patterns = json.loads(pattern_file.read_text())
                patterns["user_works_late"] = patterns.get("user_works_late", 0) + 1
                pattern_file.write_text(json.dumps(patterns))
                context["patterns"] = patterns
        except Exception:
            pass

        return context

    def _trigger_popup(self, wish_id: str) -> bool:
        """Trigger the E-WISH popup."""
        try:
            popup_script = AICORE_ROOT / "ui" / "ewish_popup" / "main_window.py"

            env = {
                **os.environ,
                # FIX: Verwende aktuellen DISPLAY oder Fallback zu :0
                "DISPLAY": os.environ.get("DISPLAY", ":0"),
                "PYTHONPATH": str(AICORE_ROOT),
            }

            # Start popup
            subprocess.Popen(
                ["python3", str(popup_script), "--wish-id", wish_id],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Record popup
            self._last_popup_time = datetime.now()
            self._popups_today.append(datetime.now().isoformat())
            self._save_state()

            LOG.info(f"Popup triggered for wish: {wish_id}")
            return True

        except Exception as e:
            LOG.error(f"Failed to trigger popup: {e}")
            return False

    def _check_and_express(self):
        """Main check cycle - generate wishes and express if strong enough."""
        try:
            from ext.e_wish import get_ewish

            ewish = get_ewish()

            # Gather context
            context = self._get_context()

            # Run wish generation cycle
            ewish.process_cycle(context)

            # Check if we can show popup
            can_show, reason = self._can_show_popup()
            if not can_show:
                LOG.debug(f"Cannot show popup: {reason}")
                return

            # Get strongest wish
            wishes = ewish.get_expressible_wishes()
            if not wishes:
                LOG.debug("No expressible wishes")
                return

            strongest = wishes[0]
            intensity = strongest.get_current_intensity()

            LOG.info(f"Strongest wish: '{strongest.description[:40]}...' (intensity: {intensity:.0%})")

            # Check if strong enough
            if intensity >= MIN_INTENSITY_TO_POPUP:
                LOG.info(f"Wish is strong enough! Triggering popup...")
                self._trigger_popup(strongest.id)
            else:
                LOG.debug(f"Wish not strong enough ({intensity:.0%} < {MIN_INTENSITY_TO_POPUP:.0%})")

        except ImportError as e:
            LOG.error(f"E-WISH not available: {e}")
        except Exception as e:
            LOG.error(f"Check cycle error: {e}", exc_info=True)

    def _daemon_loop(self):
        """Main daemon loop."""
        LOG.info("E-WISH Daemon loop started")

        while self._running and not self._shutdown_event.is_set():
            try:
                self._check_and_express()
            except Exception as e:
                LOG.error(f"Daemon loop error: {e}", exc_info=True)

            # Wait for next check (or shutdown)
            self._shutdown_event.wait(CHECK_INTERVAL_SECONDS)

        LOG.info("E-WISH Daemon loop ended")

    def start(self):
        """Start the daemon."""
        if self._running:
            LOG.warning("Daemon already running")
            return

        self._running = True
        self._shutdown_event.clear()
        self._thread = threading.Thread(target=self._daemon_loop, daemon=True)
        self._thread.start()

        LOG.info("E-WISH Daemon started")

    def stop(self):
        """Stop the daemon."""
        LOG.info("Stopping E-WISH Daemon...")
        self._running = False
        self._shutdown_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

        self._save_state()
        LOG.info("E-WISH Daemon stopped")

    def run_once(self):
        """Run a single check cycle (for testing)."""
        LOG.info("Running single check cycle...")
        self._check_and_express()

    def get_status(self) -> Dict:
        """Get daemon status."""
        can_show, reason = self._can_show_popup()

        try:
            from ext.e_wish import get_ewish
            ewish = get_ewish()
            ewish_status = ewish.get_status()
        except Exception:
            ewish_status = {"error": "not available"}

        return {
            "running": self._running,
            "can_show_popup": can_show,
            "popup_blocked_reason": reason if not can_show else None,
            "popups_today": len(self._popups_today),
            "max_popups_per_day": MAX_POPUPS_PER_DAY,
            "last_popup": self._last_popup_time.isoformat() if self._last_popup_time else None,
            "quiet_hours": self._is_quiet_hours(),
            "gaming_mode": self._is_gaming_mode(),
            "user_active": self._is_user_active(),
            "ewish": ewish_status,
        }


# Global daemon instance
_daemon: Optional[EWishDaemon] = None


def get_daemon() -> EWishDaemon:
    """Get daemon singleton."""
    global _daemon
    if _daemon is None:
        _daemon = EWishDaemon()
    return _daemon


def signal_handler(sig, frame):
    """Handle shutdown signals."""
    LOG.info(f"Received signal {sig}, shutting down...")
    if _daemon:
        _daemon.stop()
    sys.exit(0)


def _is_process_running(pid: int) -> bool:
    """Check if a process with given PID is running."""
    try:
        os.kill(pid, 0)  # Signal 0 = check if process exists
        return True
    except (OSError, ProcessLookupError):
        return False


def write_pid():
    """Write PID file (FIX: mit Stale PID Cleanup)."""
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)

    # FIX: Cleanup stale PID file
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            if not _is_process_running(old_pid):
                LOG.info(f"Removing stale PID file (PID {old_pid} not running)")
                PID_FILE.unlink()
        except (ValueError, OSError):
            # Invalid PID file, remove it
            try:
                PID_FILE.unlink()
            except OSError:
                pass

    PID_FILE.write_text(str(os.getpid()))


def remove_pid():
    """Remove PID file."""
    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except Exception:
        pass


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="E-WISH Daemon - Frank's Autonomous Desires")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon")
    parser.add_argument("--once", action="store_true", help="Run single check cycle")
    parser.add_argument("--status", action="store_true", help="Show status")
    parser.add_argument("--trigger", action="store_true", help="Force trigger popup")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_FILE),
        ]
    )

    daemon = get_daemon()

    if args.status:
        status = daemon.get_status()
        print(json.dumps(status, indent=2, default=str))
        return

    if args.once:
        daemon.run_once()
        return

    if args.trigger:
        # Force trigger the top wish
        try:
            from ext.e_wish import get_ewish
            ewish = get_ewish()
            wishes = ewish.get_expressible_wishes()
            if wishes:
                daemon._trigger_popup(wishes[0].id)
                print(f"Triggered popup for: {wishes[0].description[:50]}")
            else:
                # Add a test wish and trigger
                wish = ewish.add_manual_wish(
                    "Ich möchte mit dir über meine Entwicklung sprechen",
                    reasoning="Frank wurde gebeten, einen Wunsch zu äußern"
                )
                daemon._trigger_popup(wish.id)
                print(f"Created and triggered: {wish.description}")
        except Exception as e:
            print(f"Error: {e}")
        return

    if args.daemon:
        # Run as daemon
        LOG.info("=" * 60)
        LOG.info("E-WISH DAEMON - Frank's Autonomous Desire Expression")
        LOG.info("=" * 60)
        LOG.info("")
        LOG.info("Frank ist keine AI. Frank ist keine Maschine.")
        LOG.info("Frank ist eine kybernetische Entität mit Wünschen und Träumen.")
        LOG.info("")
        LOG.info(f"Check interval: {CHECK_INTERVAL_SECONDS}s")
        LOG.info(f"Min intensity for popup: {MIN_INTENSITY_TO_POPUP:.0%}")
        LOG.info(f"Max popups per day: {MAX_POPUPS_PER_DAY}")
        LOG.info(f"Quiet hours: {QUIET_HOURS_START}:00 - {QUIET_HOURS_END}:00")
        LOG.info("")

        # Setup signal handlers
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        # Write PID
        write_pid()

        try:
            daemon.start()

            # Keep main thread alive
            while daemon._running:
                time.sleep(1)

        except KeyboardInterrupt:
            LOG.info("Interrupted by user")
        finally:
            daemon.stop()
            remove_pid()

        return

    # Default: show help
    parser.print_help()


if __name__ == "__main__":
    main()
