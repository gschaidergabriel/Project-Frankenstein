"""
Mode Controller
Manages switching between Chat Overlay and Frank Writer
"""

import os
import signal
import socket
import json
import subprocess
import logging
import time
import atexit
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass

# Configure logger
logger = logging.getLogger(__name__)

# Same signal file used by overlay lifecycle and watchdog
try:
    from config.paths import TEMP_FILES as _WMC_TF
    USER_CLOSED_SIGNAL = _WMC_TF["user_closed"]
except ImportError:
    USER_CLOSED_SIGNAL = Path("/tmp/frank/user_closed")


@dataclass
class ModeState:
    """Current mode state"""
    active_mode: str  # 'overlay' or 'writer'
    writer_pid: Optional[int] = None
    overlay_pid: Optional[int] = None
    context: Dict[str, Any] = None


class ModeController:
    """Controls mode switching between Overlay and Writer"""

    SOCKET_PATH = Path(f"/run/user/{os.getuid()}/frank/mode_controller.sock")
    SOCKET_CONNECT_TIMEOUT = 5.0  # Connection timeout in seconds
    SOCKET_SEND_TIMEOUT = 5.0  # Send timeout in seconds
    MAX_MESSAGE_SIZE = 65536  # Maximum message size (64KB)

    def __init__(self):
        self.state = ModeState(active_mode='overlay')
        self._ensure_socket_dir()

    def _ensure_socket_dir(self):
        """Ensure socket directory exists"""
        self.SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)

    def notify_writer_opening(self):
        """Notify that Writer is opening - Overlay should close and STAY closed.

        Sets USER_CLOSED_SIGNAL so neither systemd (ExecCondition) nor the
        watchdog will auto-restart the overlay while Writer is running.
        """
        self.state.active_mode = 'writer'

        # Set user-closed signal BEFORE stopping — prevents restart race
        self._set_user_closed_signal("writer_active")

        # Send message to overlay
        self._send_message({
            'type': 'WRITER_OPENING',
            'pid': os.getpid()
        })

        # Stop overlay via systemd
        self._stop_overlay()

    def notify_writer_closed(self):
        """Notify that Writer is closing - Overlay should reopen.

        Clears USER_CLOSED_SIGNAL first so systemd ExecCondition and the
        watchdog will allow the overlay to start again.
        """
        self.state.active_mode = 'overlay'

        # Clear the signal BEFORE starting — so ExecCondition passes
        self._clear_user_closed_signal()

        # Send message
        self._send_message({
            'type': 'WRITER_CLOSED',
            'session_summary': self._get_session_summary()
        })

        # Start overlay via systemd
        self._start_overlay()

    def _send_message(self, message: Dict) -> bool:
        """Send message to mode socket

        Returns True if message was sent successfully, False otherwise
        """
        # Avoid TOCTOU race: don't check exists(), just try to connect
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                # Set connection timeout
                sock.settimeout(self.SOCKET_CONNECT_TIMEOUT)
                sock.connect(str(self.SOCKET_PATH))

                # Set send timeout
                sock.settimeout(self.SOCKET_SEND_TIMEOUT)

                # Serialize message
                try:
                    data = json.dumps(message).encode('utf-8')
                except (TypeError, ValueError) as e:
                    logger.error(f"Failed to serialize message: {e}")
                    return False

                # Handle partial sends
                total_sent = 0
                while total_sent < len(data):
                    sent = sock.send(data[total_sent:])
                    if sent == 0:
                        logger.error("Socket connection broken during send")
                        return False
                    total_sent += sent

                logger.debug(f"Successfully sent {total_sent} bytes")
                return True

        except socket.timeout:
            logger.warning("Socket timeout while sending message")
            return False
        except FileNotFoundError:
            logger.debug(f"Socket path does not exist: {self.SOCKET_PATH}")
            return False
        except ConnectionRefusedError:
            logger.warning("Connection refused - mode controller not running")
            return False
        except Exception as e:
            logger.error(f"Mode controller message failed: {e}")
            return False

    def _set_user_closed_signal(self, reason: str = "writer_active"):
        """Write the user-closed signal file so watchdog + systemd skip restart."""
        try:
            USER_CLOSED_SIGNAL.write_text(json.dumps({
                "timestamp": time.time(),
                "reason": reason,
            }))
            logger.info(f"User-closed signal set: {reason}")
        except Exception as e:
            logger.warning(f"Failed to set user-closed signal: {e}")

    def _clear_user_closed_signal(self):
        """Remove the user-closed signal so the overlay can start again."""
        try:
            USER_CLOSED_SIGNAL.unlink(missing_ok=True)
            logger.info("User-closed signal cleared")
        except Exception as e:
            logger.warning(f"Failed to clear user-closed signal: {e}")

    def _stop_overlay(self):
        """Stop the chat overlay"""
        try:
            # Try systemd first
            subprocess.run(
                ['systemctl', '--user', 'stop', 'frank-overlay.service'],
                capture_output=True,
                timeout=5
            )
        except Exception as e:
            logger.debug(f"Failed to stop overlay via systemd: {e}")
            # Fallback: kill by name
            try:
                subprocess.run(
                    ['pkill', '-f', 'chat_overlay.py'],
                    capture_output=True,
                    timeout=5
                )
            except Exception as e2:
                logger.warning(f"Failed to stop overlay via pkill: {e2}")

    def _start_overlay(self):
        """Start the chat overlay"""
        try:
            subprocess.run(
                ['systemctl', '--user', 'start', 'frank-overlay.service'],
                capture_output=True,
                timeout=5
            )
        except Exception as e:
            logger.debug(f"Failed to start overlay via systemd: {e}")
            # Fallback: start directly
            try:
                try:
                    from config.paths import UI_DIR as _UI_DIR
                except ImportError:
                    _UI_DIR = Path(__file__).resolve().parents[2] / "ui"
                overlay_path = _UI_DIR / "chat_overlay.py"
                if overlay_path.exists():
                    subprocess.Popen(
                        ['python3', str(overlay_path)],
                        env={**os.environ, 'DISPLAY': ':0'},
                        start_new_session=True
                    )
            except Exception as e2:
                logger.error(f"Failed to start overlay: {e2}")

    def _get_session_summary(self) -> Dict:
        """Get summary of writer session"""
        return {
            'documents_created': 0,
            'documents_saved': [],
            'time_spent': 0
        }


class ModeControllerDaemon:
    """Daemon that listens for mode changes"""

    RECV_BUFFER_SIZE = 4096
    MAX_MESSAGE_SIZE = 65536  # 64KB max message

    def __init__(self):
        self.controller = ModeController()
        self.running = False

    def start(self):
        """Start the daemon"""
        self.running = True

        # Remove old socket
        if self.controller.SOCKET_PATH.exists():
            self.controller.SOCKET_PATH.unlink()

        # Create socket with proper cleanup on exit
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(str(self.controller.SOCKET_PATH))
                server.listen(1)
                server.settimeout(1.0)

                print(f"Mode controller listening on {self.controller.SOCKET_PATH}")

                while self.running:
                    try:
                        conn, addr = server.accept()
                        with conn:
                            # Set receive timeout on connection
                            conn.settimeout(5.0)

                            # Receive complete message with proper framing
                            data = self._recv_complete_message(conn)
                            if data:
                                # Parse JSON with error handling
                                try:
                                    message = json.loads(data.decode('utf-8'))
                                    self._handle_message(message)
                                except json.JSONDecodeError as e:
                                    logger.error(f"Invalid JSON received: {e}")
                                except UnicodeDecodeError as e:
                                    logger.error(f"Invalid UTF-8 data received: {e}")

                    except socket.timeout:
                        continue
                    except Exception as e:
                        logger.error(f"Error in daemon loop: {e}")
        finally:
            # Clean up socket file on exit
            self._cleanup_socket()

    def _recv_complete_message(self, conn: socket.socket) -> Optional[bytes]:
        """Receive complete message from socket with proper framing

        Loops until connection closes or max size reached.
        For simple protocols, we read until the connection closes.
        """
        chunks = []
        total_received = 0

        try:
            while total_received < self.MAX_MESSAGE_SIZE:
                try:
                    chunk = conn.recv(self.RECV_BUFFER_SIZE)
                    if not chunk:
                        # Connection closed - end of message
                        break
                    chunks.append(chunk)
                    total_received += len(chunk)
                except socket.timeout:
                    # Timeout waiting for more data - assume message complete
                    logger.debug("Recv timeout - assuming message complete")
                    break

            if total_received >= self.MAX_MESSAGE_SIZE:
                logger.warning(f"Message exceeded max size ({self.MAX_MESSAGE_SIZE} bytes)")
                return None

            return b''.join(chunks) if chunks else None

        except Exception as e:
            logger.error(f"Error receiving message: {e}")
            return None

    def stop(self):
        """Stop the daemon"""
        self.running = False
        self._cleanup_socket()

    def _cleanup_socket(self):
        """Clean up socket file"""
        try:
            if self.controller.SOCKET_PATH.exists():
                self.controller.SOCKET_PATH.unlink()
                logger.debug(f"Removed socket file: {self.controller.SOCKET_PATH}")
        except Exception as e:
            logger.warning(f"Failed to clean up socket file: {e}")

    def _handle_message(self, message: Dict):
        """Handle incoming message"""
        if not isinstance(message, dict):
            logger.error(f"Expected dict message, got {type(message)}")
            return

        msg_type = message.get('type')

        if msg_type == 'WRITER_OPENING':
            print("Writer opening - stopping overlay")
            self.controller._stop_overlay()

        elif msg_type == 'WRITER_CLOSED':
            print("Writer closed - starting overlay")
            self.controller._start_overlay()

        elif msg_type == 'STATUS':
            print(f"Current mode: {self.controller.state.active_mode}")

        else:
            logger.warning(f"Unknown message type: {msg_type}")


def main():
    """Run mode controller daemon"""
    daemon = ModeControllerDaemon()

    # Register cleanup handlers for signals
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        daemon.stop()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Also register atexit handler as backup
    atexit.register(daemon._cleanup_socket)

    try:
        daemon.start()
    except KeyboardInterrupt:
        daemon.stop()


if __name__ == '__main__':
    main()
