#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gaming Mode Daemon

Monitors for Steam games and automatically:
- Stops heavy LLM services to free RAM
- Keeps a lightweight LLM for basic voice commands
- Shows mini Frank overlay
- Restarts everything when game closes
"""

import os
import sys
import time
import subprocess
import signal
import logging
import json
import fcntl
from pathlib import Path
from typing import Optional, Set, List
import threading

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler('/tmp/gaming_mode.log')
    ]
)
LOG = logging.getLogger("gaming_mode")

# Configuration
CONFIG = {
    "check_interval": 1,  # seconds between game checks
    "steam_game_patterns": [
        # Common Steam game process patterns
        r"\.x86_64$",
        r"\.x86$",
        r"wine.*\.exe",
        r"proton.*\.exe",
        r"steamapps/common",
    ],
    "heavy_services": [
        # Services to stop during gaming (PIDs will be found dynamically)
        {"name": "llama-8101", "port": 8101, "pattern": "llama-server.*8101"},
        {"name": "llama-8102", "port": 8102, "pattern": "llama-server.*8102"},
    ],
    "keep_services": [
        # Services to keep running
        "toolboxd",
        "ollama",
    ],
    "gaming_llm_model": "tinyllama",  # Small model for gaming mode
    "ollama_url": "http://localhost:11434",
}

# State
STATE_FILE = Path("/tmp/gaming_mode_state.json")


class GamingModeState:
    """Tracks gaming mode state."""

    def __init__(self):
        self.active = False
        self.game_pid: Optional[int] = None
        self.game_name: Optional[str] = None
        self.stopped_services: List[dict] = []
        # CRITICAL #3: Track daemon threads for proper cleanup
        self._background_threads: List[threading.Thread] = []
        self._shutdown_event = threading.Event()
        self.load()

    def save(self):
        """Save state with file locking to prevent race conditions."""
        data = {
            "active": self.active,
            "game_pid": self.game_pid,
            "game_name": self.game_name,
            "stopped_services": self.stopped_services,
        }
        # Atomic write with file locking
        tmp_file = STATE_FILE.with_suffix('.tmp')
        try:
            with open(tmp_file, 'w') as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump(data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            # Atomic rename
            tmp_file.rename(STATE_FILE)
        except (IOError, OSError) as e:
            LOG.error(f"Failed to save state: {e}")
            if tmp_file.exists():
                tmp_file.unlink()

    def load(self):
        """Load state with file locking to prevent race conditions."""
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, 'r') as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                    try:
                        data = json.load(f)
                    finally:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                self.active = data.get("active", False)
                self.game_pid = data.get("game_pid")
                self.game_name = data.get("game_name")
                self.stopped_services = data.get("stopped_services", [])
            except (json.JSONDecodeError, IOError, OSError) as e:
                LOG.warning(f"Failed to load state file: {e}")

    def cleanup_threads(self, timeout: float = 5.0):
        """CRITICAL #3: Properly cleanup background threads."""
        self._shutdown_event.set()

        # Wait for all background threads to finish
        for thread in self._background_threads:
            if thread.is_alive():
                LOG.debug(f"Waiting for thread {thread.name} to finish...")
                thread.join(timeout=timeout)
                if thread.is_alive():
                    LOG.warning(f"Thread {thread.name} did not finish in time")

        self._background_threads.clear()
        self._shutdown_event.clear()


def get_steam_games() -> List[dict]:
    """Find running Steam game processes."""
    games = []
    # Skip runtime/helper folders - not actual games
    skip_names = {"steamlinuxruntime", "proton", "steamworks", "steam_app_0"}
    try:
        # Get all processes
        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=5
        )

        for line in result.stdout.split("\n"):
            lower = line.lower()
            # Check if this looks like a Steam game
            if "steamapps/common" not in lower:
                continue
            parts = line.split(None, 10)
            if len(parts) < 11:
                continue
            pid = int(parts[1])
            cmd = parts[10]
            # Extract ALL game folder names from the full command line
            import re as _re
            folders = _re.findall(r"steamapps/common/([^/]+)", cmd, _re.IGNORECASE)
            for folder in folders:
                folder_clean = folder.strip("'\" ")
                if not folder_clean:
                    continue
                # Skip runtimes and helpers
                if any(s in folder_clean.lower() for s in skip_names):
                    continue
                games.append({
                    "pid": pid,
                    "name": folder_clean,
                    "cmd": cmd[:100]
                })
                break  # Take first real game folder per process
    except Exception as e:
        LOG.error(f"Error getting Steam games: {e}")

    # Deduplicate by game name (keep first PID)
    seen = set()
    unique = []
    for g in games:
        if g["name"] not in seen:
            seen.add(g["name"])
            unique.append(g)
    return unique


def stop_heavy_services(state: GamingModeState):
    """Stop heavy LLM services to free RAM using systemctl."""
    LOG.info("Stopping heavy services via systemctl...")

    # User systemd services for heavy LLM backends
    heavy_systemd_services = [
        "aicore-llama3-gpu.service",  # Llama 3.1 8B on port 8101
        "aicore-qwen-gpu.service",   # Qwen Coder 7B on port 8102
    ]

    for service in heavy_systemd_services:
        try:
            LOG.info(f"Stopping {service}...")
            # Mask first to prevent Restart=always from reviving the service
            subprocess.run(
                ["systemctl", "--user", "mask", "--runtime", service],
                capture_output=True, text=True, timeout=10
            )
            result = subprocess.run(
                ["systemctl", "--user", "stop", service],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                state.stopped_services.append({"name": service, "type": "systemd"})
                LOG.info(f"Stopped {service} (masked until gaming ends)")
            else:
                LOG.warning(f"Could not stop {service}: {result.stderr}")
        except Exception as e:
            LOG.error(f"Error stopping {service}: {e}")

    # Also drop caches to free RAM
    try:
        subprocess.run(["sync"], timeout=10)
    except (subprocess.TimeoutExpired, OSError) as e:
        LOG.debug(f"Sync command failed: {e}")  # HIGH #6: Log but continue

    # Give services time to fully stop and release RAM
    time.sleep(2)

    state.save()
    LOG.info(f"Stopped {len(state.stopped_services)} services")


def restart_services(state: GamingModeState):
    """Restart previously stopped services using systemctl."""
    LOG.info("Restarting services via systemctl...")

    for service in state.stopped_services:
        name = service.get("name", "")
        stype = service.get("type", "")

        if stype == "systemd":
            try:
                LOG.info(f"Restarting {name}...")
                # Unmask first (was masked during gaming to prevent Restart=always)
                subprocess.run(
                    ["systemctl", "--user", "unmask", name],
                    capture_output=True, text=True, timeout=10
                )
                result = subprocess.run(
                    ["systemctl", "--user", "start", name],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0:
                    LOG.info(f"Restarted {name}")
                else:
                    LOG.warning(f"Could not restart {name}: {result.stderr}")
            except Exception as e:
                LOG.error(f"Error restarting {name}: {e}")

    state.stopped_services = []
    state.save()
    LOG.info("Services restarted")


def ensure_lightweight_llm():
    """Make sure tinyllama is loaded in Ollama for voice commands."""
    LOG.info("Loading lightweight LLM (tinyllama) for voice commands...")
    try:
        # Preload tinyllama so it's ready for voice commands
        import urllib.request
        import json

        data = json.dumps({"model": "tinyllama", "prompt": "hi", "stream": False}).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=data,
            headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=30)
        LOG.info("Lightweight LLM ready for voice commands")
    except Exception as e:
        LOG.warning(f"Could not preload tinyllama: {e}")


GAMING_LOCK = Path("/tmp/frank_gaming_lock")


def stop_main_frank():
    """Stop Frank overlay and create lock file to prevent restart."""
    LOG.info("Stopping main Frank overlay...")
    # Create lock file FIRST - Frank checks this on startup
    try:
        GAMING_LOCK.write_text(str(os.getpid()))
    except Exception:
        pass
    # Stop via systemd
    try:
        subprocess.run(
            ["systemctl", "--user", "stop", "frank-overlay.service"],
            capture_output=True, text=True, timeout=10
        )
    except Exception as e:
        LOG.warning(f"systemd stop error: {e}")
    # Kill any lingering process
    subprocess.run(["pkill", "-9", "-f", "chat_overlay.py"], capture_output=True)
    LOG.info("Frank overlay stopped (lock file active)")


def is_frank_running() -> bool:
    """Check if Frank overlay is currently running (service OR process)."""
    try:
        # Check systemd service
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "frank-overlay.service"],
            capture_output=True, text=True, timeout=5
        )
        if result.stdout.strip() in ("active", "activating"):
            return True
    except Exception:
        pass
    try:
        # Also check for lingering process
        result = subprocess.run(
            ["pgrep", "-f", "chat_overlay.py"],
            capture_output=True, text=True, timeout=3
        )
        return result.returncode == 0
    except Exception:
        return False


def start_main_frank():
    """Remove lock file and start the Frank overlay."""
    LOG.info("Starting main Frank overlay...")
    # Remove lock file FIRST
    try:
        GAMING_LOCK.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        # Start directly (bypasses systemd After= dependencies on LLM services)
        env = os.environ.copy()
        env["DISPLAY"] = ":0"
        env["PYTHONUNBUFFERED"] = "1"
        subprocess.Popen(
            [sys.executable, "/home/ai-core-node/aicore/opt/aicore/ui/chat_overlay.py"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        LOG.info("Frank overlay started (direct)")
    except Exception as e:
        LOG.error(f"Error starting Frank: {e}")
        # Fallback to systemd
        try:
            subprocess.run(
                ["systemctl", "--user", "start", "frank-overlay.service"],
                capture_output=True, text=True, timeout=10
            )
        except Exception:
            pass


def stop_wallpaper():
    """Stop the Kinetic Synthetic live wallpaper to save GPU during gaming."""
    LOG.info("Stopping live wallpaper...")
    try:
        result = subprocess.run(
            ["systemctl", "--user", "stop", "frank-wallpaperd"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            LOG.info("Live wallpaper stopped")
        else:
            LOG.warning(f"Could not stop wallpaper: {result.stderr}")
    except Exception as e:
        LOG.warning(f"Error stopping wallpaper: {e}")


def start_wallpaper():
    """Start the Kinetic Synthetic live wallpaper."""
    LOG.info("Starting live wallpaper...")
    try:
        result = subprocess.run(
            ["systemctl", "--user", "start", "frank-wallpaperd"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            LOG.info("Live wallpaper started")
        else:
            LOG.warning(f"Could not start wallpaper: {result.stderr}")
    except Exception as e:
        LOG.warning(f"Error starting wallpaper: {e}")


def stop_network_sentinel():
    """IMMEDIATELY stop network sentinel to prevent anti-cheat conflicts."""
    LOG.info("⚡ KILLING Network Sentinel (anti-cheat safety)...")
    try:
        # Direct kill - must be fast (<500ms)
        subprocess.run(
            ["pkill", "-f", "network_sentinel"],
            capture_output=True, timeout=1
        )
        # Also stop via API if running
        try:
            from tools.network_sentinel import stop_sentinel
            stop_sentinel()
        except (ImportError, AttributeError, Exception) as e:
            LOG.debug(f"Sentinel API stop failed: {e}")  # HIGH #6: Log import failures
        LOG.info("Network Sentinel stopped")
    except Exception as e:
        LOG.warning(f"Sentinel stop error: {e}")


def start_network_sentinel():
    """Start network sentinel after gaming."""
    LOG.info("Starting Network Sentinel...")
    try:
        from tools.network_sentinel import start_sentinel
        start_sentinel()
        LOG.info("Network Sentinel started")
    except Exception as e:
        LOG.warning(f"Sentinel start error: {e}")


def enter_gaming_mode(state: GamingModeState, game: dict):
    """Enter gaming mode - stops heavy services, keeps lightweight LLM for voice."""
    LOG.info(f"🎮 ENTERING GAMING MODE for: {game['name']}")

    # CRITICAL: Stop network monitoring FIRST and IMMEDIATELY
    # Must complete in <500ms to avoid anti-cheat detection
    stop_network_sentinel()

    state.active = True
    state.game_pid = game["pid"]
    state.game_name = game["name"]
    state.save()

    # 1. Stop main Frank overlay (no visible UI during gaming)
    stop_main_frank()
    time.sleep(0.5)

    # 2. Stop heavy LLM services to free RAM
    stop_heavy_services(state)
    time.sleep(1)

    # 3. Ensure lightweight LLM is ready for voice commands
    ensure_lightweight_llm()

    # 4. Stop live wallpaper after 3 seconds (seamless transition)
    # User won't notice because they're focused on the game loading
    def delayed_wallpaper_stop():
        # CRITICAL #3: Use shutdown event for clean exit
        if state._shutdown_event.wait(timeout=3.0):
            return  # Shutdown requested, don't stop wallpaper
        if state.active:  # Only if still in gaming mode
            stop_wallpaper()

    # CRITICAL #3: Store thread reference for cleanup
    wallpaper_thread = threading.Thread(target=delayed_wallpaper_stop, daemon=True, name="wallpaper_stop")
    wallpaper_thread.start()
    state._background_threads.append(wallpaper_thread)

    LOG.info("Gaming mode activated! No overlay, voice-ready, network monitoring OFF. ✓")


def exit_gaming_mode(state: GamingModeState):
    """Exit gaming mode - restart all services and Frank overlay."""
    LOG.info("🎮 EXITING GAMING MODE")

    # 1. Remove lock file FIRST so Frank can start immediately
    try:
        GAMING_LOCK.unlink(missing_ok=True)
    except Exception:
        pass

    # 2. Reset state immediately
    state.active = False
    state.game_pid = None
    state.game_name = None
    state.save()

    # 3. Start Frank overlay + wallpaper + LLM services ALL in parallel
    def restore_all():
        threads = [
            threading.Thread(target=start_main_frank, daemon=True),
            threading.Thread(target=start_wallpaper, daemon=True),
            threading.Thread(target=lambda: (restart_services(state), start_network_sentinel()), daemon=True),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        LOG.info("Gaming mode deactivated! Frank + Wallpaper + LLM services restored.")

    # CRITICAL #3: Store thread reference for cleanup
    restore_thread = threading.Thread(target=restore_services, daemon=True, name="restore_services")
    restore_thread.start()
    state._background_threads.append(restore_thread)


def is_process_running(pid: int) -> bool:
    """Check if a process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def has_game_window() -> bool:
    """Check if any game window is visible (steam_app_*, fullscreen game, etc.)."""
    try:
        # Check all windows for steam_app_ WM_CLASS
        result = subprocess.run(
            ["wmctrl", "-l"], capture_output=True, text=True, timeout=3
        )
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            win_id = line.split()[0]
            try:
                cls_result = subprocess.run(
                    ["xprop", "-id", win_id, "WM_CLASS"],
                    capture_output=True, text=True, timeout=2
                )
                cls = cls_result.stdout.lower()
                if "steam_app_" in cls:
                    return True
                # Also detect common game engine windows
                if any(g in cls for g in ["dota", "csgo", "hl2", "unity", "unreal"]):
                    return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def is_steam_foreground() -> bool:
    """Check if Steam client is the active/foreground window."""
    try:
        result = subprocess.run(
            ["xdotool", "getactivewindow"],
            capture_output=True, text=True, timeout=2
        )
        win_id = result.stdout.strip()
        if not win_id:
            return False
        cls_result = subprocess.run(
            ["xprop", "-id", win_id, "WM_CLASS"],
            capture_output=True, text=True, timeout=2
        )
        cls = cls_result.stdout.lower()
        return "steam" in cls
    except Exception:
        return False


def is_steam_client_running() -> bool:
    """Check if Steam client process is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "ubuntu12_32/steam"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            return True
        # Also check snap steam
        result2 = subprocess.run(
            ["pgrep", "-f", "bin_steam.sh"],
            capture_output=True, text=True, timeout=3
        )
        return result2.returncode == 0
    except Exception:
        return False


def daemon_loop():
    """Main daemon loop."""
    state = GamingModeState()
    LOG.info("Gaming Mode Daemon started")
    exit_grace_counter = 0   # Counts checks since game process disappeared
    EXIT_GRACE_CHECKS = 1    # Wait 1 check (2 sec) before exiting if Steam also gone
    EXIT_GRACE_STEAM = 1     # Wait 1 check (2 sec) if Steam still open
    MIN_GAMING_SECS = 30     # Minimum 30 sec in gaming mode (game loading protection)
    gaming_entered_at = 0    # Timestamp when gaming mode was entered

    # If we crashed while in gaming mode, clean up
    if state.active:
        LOG.info("Recovering from previous gaming mode state...")
        games = get_steam_games()
        pid_alive = state.game_pid and is_process_running(state.game_pid)
        game_window = has_game_window()
        steam_running = is_steam_client_running()
        if not games and not pid_alive and not game_window and not steam_running:
            LOG.info("Game no longer running after recovery - exiting gaming mode")
            exit_gaming_mode(state)
        else:
            gaming_entered_at = time.time()  # Treat recovery as fresh entry
            LOG.info("Game still active after recovery - re-enforcing service stops")
            stop_heavy_services(state)
            stop_main_frank()

    while True:
        try:
            games = get_steam_games()

            if state.active:
                # ENFORCE: Frank must ALWAYS be off during gaming
                if is_frank_running():
                    LOG.info("Frank restarted during gaming mode - stopping again")
                    stop_main_frank()

                # Don't even check for exit during minimum period
                elapsed = time.time() - gaming_entered_at
                if elapsed < MIN_GAMING_SECS:
                    time.sleep(CONFIG["check_interval"])
                    continue

                # Check ALL signals
                process_running = bool(games) or (state.game_pid and is_process_running(state.game_pid))
                game_window = has_game_window()
                steam_fg = is_steam_foreground()
                steam_alive = is_steam_client_running()

                # Game is active if process OR window OR steam foreground
                game_active = process_running or game_window or steam_fg

                if game_active:
                    exit_grace_counter = 0
                elif steam_alive:
                    # Game process gone but Steam still open
                    exit_grace_counter += 1
                    if exit_grace_counter >= EXIT_GRACE_STEAM:
                        LOG.info(f"Game closed, Steam open ({exit_grace_counter} checks) - exiting")
                        exit_gaming_mode(state)
                        exit_grace_counter = 0
                        gaming_entered_at = 0
                else:
                    # Neither game nor Steam running - exit fast
                    exit_grace_counter += 1
                    if exit_grace_counter >= EXIT_GRACE_CHECKS:
                        LOG.info(f"Game + Steam closed ({exit_grace_counter} checks) - exiting")
                        exit_gaming_mode(state)
                        exit_grace_counter = 0
                        gaming_entered_at = 0
            else:
                # Check if a new game started (process OR window)
                if games:
                    game = games[0]
                    LOG.info(f"Detected Steam game: {game['name']}")
                    enter_gaming_mode(state, game)
                    gaming_entered_at = time.time()
                elif has_game_window():
                    LOG.info("Detected Steam game window (no process match)")
                    enter_gaming_mode(state, {"pid": 0, "name": "Steam Game", "cmd": ""})
                    gaming_entered_at = time.time()

            time.sleep(CONFIG["check_interval"])

        except KeyboardInterrupt:
            LOG.info("Daemon interrupted")
            # CRITICAL #3: Clean shutdown with thread cleanup
            state._shutdown_event.set()
            if state.active:
                exit_gaming_mode(state)
            state.cleanup_threads()
            break
        except Exception as e:
            LOG.error(f"Daemon error: {e}")
            time.sleep(5)


def main():
    """Entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Gaming Mode Daemon")
    parser.add_argument("--start", action="store_true", help="Start gaming mode manually")
    parser.add_argument("--stop", action="store_true", help="Stop gaming mode manually")
    parser.add_argument("--status", action="store_true", help="Show status")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon")
    args = parser.parse_args()

    state = GamingModeState()

    if args.status:
        print(f"Gaming Mode Active: {state.active}")
        print(f"Game: {state.game_name or 'None'}")
        print(f"Stopped Services: {len(state.stopped_services)}")
        return

    if args.start:
        if not state.active:
            enter_gaming_mode(state, {"pid": 0, "name": "Manual"})
        else:
            print("Already in gaming mode")
        return

    if args.stop:
        if state.active:
            exit_gaming_mode(state)
        else:
            print("Not in gaming mode")
        return

    if args.daemon:
        daemon_loop()
        return

    # Default: run daemon
    daemon_loop()


if __name__ == "__main__":
    main()
