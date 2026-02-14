#!/usr/bin/env python3
"""
F.A.S. Popup Daemon
Background service that monitors feature queue and triggers popup when appropriate.
Also handles global hotkey for manual popup opening.
"""

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.fas_popup_config import get_config
from ui.fas_popup.activity_detector import ActivityDetector
from ui.fas_popup.queue_manager import ProposalQueueManager

import logging

LOG = logging.getLogger("fas_popup_daemon")


class FASPopupDaemon:
    """
    Daemon that monitors F.A.S. feature queue and triggers popup.

    Features:
    - Periodic check if popup should be shown
    - Activity detection for optimal timing
    - Global hotkey support via socket
    - Systemd watchdog integration
    """

    CHECK_INTERVAL = 300  # Check every 5 minutes
    HOTKEY_SOCKET_PATH = "/run/user/{uid}/frank/fas_hotkey.sock"

    def __init__(self):
        self.config = get_config()
        self.queue_manager = ProposalQueueManager(self.config)
        self.activity_detector = ActivityDetector(self.config)

        self._running = False
        self._popup_process: Optional[subprocess.Popen] = None

        # Socket path for hotkey communication
        self.socket_path = Path(
            self.config.get("hotkey_socket", self.HOTKEY_SOCKET_PATH.format(uid=os.getuid()))
        )

        LOG.info("F.A.S. Popup Daemon initialized")

    def start(self):
        """Start the daemon."""
        self._running = True

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # Start hotkey listener thread
        hotkey_thread = threading.Thread(target=self._hotkey_listener, daemon=True)
        hotkey_thread.start()

        # Notify systemd we're ready
        self._notify_systemd("READY=1")

        LOG.info("F.A.S. Popup Daemon started")

        # Main loop
        self._main_loop()

    def stop(self):
        """Stop the daemon."""
        self._running = False
        self._cleanup_socket()
        LOG.info("F.A.S. Popup Daemon stopped")

    def _signal_handler(self, signum, frame):
        """Handle termination signals."""
        LOG.info(f"Received signal {signum}, shutting down...")
        self.stop()

    def _main_loop(self):
        """Main daemon loop."""
        last_check = 0

        while self._running:
            now = time.time()

            # Periodic check
            if now - last_check >= self.CHECK_INTERVAL:
                last_check = now
                self._check_and_trigger()

            # Notify systemd watchdog
            self._notify_systemd("WATCHDOG=1")

            # Sleep with interrupt capability
            for _ in range(min(60, self.CHECK_INTERVAL)):
                if not self._running:
                    break
                time.sleep(1)

    def _check_and_trigger(self):
        """Check if popup should be triggered and do so if appropriate."""
        LOG.debug("Checking trigger conditions...")

        # Check if popup should trigger
        should_trigger, reason = self.queue_manager.should_trigger_popup()
        LOG.debug(f"Should trigger: {should_trigger} ({reason})")

        if not should_trigger:
            return

        # Check if user is receptive
        is_receptive, receptive_reason = self.activity_detector.is_user_receptive()
        LOG.debug(f"User receptive: {is_receptive} ({receptive_reason})")

        if not is_receptive:
            LOG.info(f"Popup ready but user not receptive: {receptive_reason}")
            return

        # Trigger popup
        LOG.info("Triggering popup...")
        self._launch_popup(manual=False)

    def _launch_popup(self, manual: bool = False):
        """Launch the popup window."""
        # Check if popup already running
        if self._popup_process is not None and self._popup_process.poll() is None:
            LOG.info("Popup already running")
            return

        # Get features
        features = self.queue_manager.get_high_confidence_features() if not manual else self.queue_manager.get_ready_features()

        if not features and not manual:
            LOG.info("No features to show")
            return

        # Launch popup
        popup_script = Path(__file__).parent.parent / "ui" / "fas_popup" / "main_window.py"

        cmd = [
            sys.executable,
            str(popup_script),
            "--features", json.dumps(features),
        ]
        if manual:
            cmd.append("--manual")

        env = os.environ.copy()
        env["DISPLAY"] = os.environ.get("DISPLAY", ":0")

        try:
            self._popup_process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            LOG.info(f"Popup launched (PID: {self._popup_process.pid})")
        except Exception as e:
            LOG.error(f"Failed to launch popup: {e}")

    def _hotkey_listener(self):
        """Listen for hotkey events via Unix socket."""
        self._cleanup_socket()

        try:
            self.socket_path.parent.mkdir(parents=True, exist_ok=True)

            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            sock.bind(str(self.socket_path))
            sock.settimeout(5.0)

            LOG.info(f"Hotkey listener started on {self.socket_path}")

            while self._running:
                try:
                    data, addr = sock.recvfrom(1024)
                    message = data.decode().strip()
                    LOG.debug(f"Received hotkey message: {message}")

                    if message == "toggle":
                        self._toggle_popup()
                    elif message == "show":
                        self._launch_popup(manual=True)
                    elif message == "hide":
                        self._hide_popup()

                except socket.timeout:
                    continue
                except Exception as e:
                    LOG.error(f"Hotkey listener error: {e}")

        except Exception as e:
            LOG.error(f"Failed to start hotkey listener: {e}")
        finally:
            self._cleanup_socket()

    def _toggle_popup(self):
        """Toggle popup visibility."""
        if self._popup_process is not None and self._popup_process.poll() is None:
            self._hide_popup()
        else:
            self._launch_popup(manual=True)

    def _hide_popup(self):
        """Hide/close the popup."""
        if self._popup_process is not None:
            try:
                self._popup_process.terminate()
                self._popup_process.wait(timeout=5)
            except:
                try:
                    self._popup_process.kill()
                except:
                    pass
            self._popup_process = None
            LOG.info("Popup closed")

    def _cleanup_socket(self):
        """Remove socket file if exists."""
        try:
            if self.socket_path.exists():
                self.socket_path.unlink()
        except:
            pass

    def _notify_systemd(self, message: str):
        """Send notification to systemd."""
        try:
            notify_socket = os.environ.get("NOTIFY_SOCKET")
            if notify_socket:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                if notify_socket.startswith("@"):
                    notify_socket = "\0" + notify_socket[1:]
                sock.connect(notify_socket)
                sock.sendall(message.encode())
                sock.close()
        except Exception as e:
            LOG.debug(f"Systemd notify failed: {e}")


class HotkeyTrigger:
    """Helper class to trigger popup via socket (used by keybinding)."""

    def __init__(self):
        uid = os.getuid()
        self.socket_path = f"/run/user/{uid}/frank/fas_hotkey.sock"

    def send(self, command: str = "toggle"):
        """Send command to daemon."""
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            sock.sendto(command.encode(), self.socket_path)
            sock.close()
            return True
        except Exception as e:
            print(f"Failed to send command: {e}")
            return False


def setup_xbindkeys():
    """Setup xbindkeys configuration for global hotkey."""
    config = get_config()
    hotkey = config.get("global_hotkey", "super+f")

    # Convert to xbindkeys format
    # super+f -> Mod4 + f
    xbindkeys_key = hotkey.replace("super", "Mod4").replace("+", " + ")

    xbindkeys_config = Path.home() / ".xbindkeysrc"
    trigger_script = Path(__file__).parent / "fas_hotkey_trigger.sh"

    # Create trigger script
    trigger_script.write_text(f'''#!/bin/bash
# F.A.S. Popup Hotkey Trigger
python3 -c "
import socket
import os
sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
sock.sendto(b'toggle', '/run/user/{os.getuid()}/frank/fas_hotkey.sock')
sock.close()
" 2>/dev/null
''')
    trigger_script.chmod(0o755)

    # Add to xbindkeys config if not present
    marker = "# F.A.S. Popup Hotkey"
    config_entry = f'''
{marker}
"{trigger_script}"
    {xbindkeys_key}
'''

    current_config = ""
    if xbindkeys_config.exists():
        current_config = xbindkeys_config.read_text()

    if marker not in current_config:
        with open(xbindkeys_config, "a") as f:
            f.write(config_entry)
        LOG.info(f"Added F.A.S. hotkey ({hotkey}) to xbindkeys config")

        # Reload xbindkeys
        subprocess.run(["killall", "-HUP", "xbindkeys"], capture_output=True)


def main():
    """Main entry point."""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s: %(message)s'
    )

    parser = argparse.ArgumentParser(description="F.A.S. Popup Daemon")
    parser.add_argument("--setup-hotkey", action="store_true", help="Setup xbindkeys hotkey")
    parser.add_argument("--trigger", action="store_true", help="Trigger popup via socket")
    parser.add_argument("--show", action="store_true", help="Show popup directly")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.setup_hotkey:
        setup_xbindkeys()
        return

    if args.trigger:
        trigger = HotkeyTrigger()
        trigger.send("toggle")
        return

    if args.show:
        # Direct show without daemon
        config = get_config()
        manager = ProposalQueueManager(config)
        features = manager.get_ready_features()

        popup_script = Path(__file__).parent.parent / "ui" / "fas_popup" / "main_window.py"
        subprocess.run([
            sys.executable,
            str(popup_script),
            "--features", json.dumps(features),
            "--manual",
        ])
        return

    # Run daemon
    daemon = FASPopupDaemon()
    daemon.start()


if __name__ == "__main__":
    main()
