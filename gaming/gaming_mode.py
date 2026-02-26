#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gaming Mode Daemon

Monitors for games (Steam, native, Wine/Proton, Lutris, etc.) and automatically:
- Stops heavy LLM services to free RAM
- Keeps a lightweight LLM for basic voice commands
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
    "heavy_services": [
        {"name": "rlm-8101", "port": 8101, "pattern": "llama-server.*8101"},
    ],
    "keep_services": ["toolboxd"],
}

# Directories where games are commonly installed (case-insensitive match on cmdline)
GAME_DIRS = [
    "steamapps/common",
    "OldUnreal/UT2004",
    "OldUnreal/UnrealTournament",
    "OldUnreal/Unreal",
    ".local/share/lutris",
    "Games/",
    "GOG Games/",
    ".wine/drive_c/",
    ".local/share/bottles/",
    ".local/share/itch/apps/",
]

# Known game binary names (matched as word boundaries in cmdline, case-insensitive)
# These are matched with \b word boundaries to avoid false positives
KNOWN_GAME_BINARIES = [
    r"\but2004-bin\b", r"\but2004\b", r"\but-bin\b",
    r"\bunrealtournament\b", r"\bucc-bin\b",
    r"\bxonotic\b", r"\bopenarena\b", r"\bquake[23]?\b",
    r"\bsupertuxkart\b", r"\b0ad\b", r"\bwesnoth\b",
    r"\bminecraft-launcher\b", r"java.*minecraft",
    r"\bdosbox\b", r"\bretroarch\b", r"\bmednafen\b",
    r"\blutris-wrapper\b",
]

# Process cmdline patterns to SKIP (helpers, installers, not games)
SKIP_PATTERNS = {
    "steamlinuxruntime", "proton", "steamworks", "steam_app_0",
    "pressure-vessel", "steam-runtime", "compatibilitytools",
    "install-ut", "install-unreal", "aria2c", "curl", "wget",
    "bash /tmp/", "7z", "tar ", "unshield",
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


def get_running_games() -> List[dict]:
    """Find running game processes (Steam, native, Wine, Lutris, etc.)."""
    import re as _re
    games = []
    try:
        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.split("\n"):
            parts = line.split(None, 10)
            if len(parts) < 11:
                continue
            try:
                pid = int(parts[1])
            except ValueError:
                continue  # skip header line
            cmd = parts[10]
            lower = cmd.lower()

            # Skip helper/runtime processes
            if any(s in lower for s in SKIP_PATTERNS):
                continue

            game_name = None

            # 1. Steam games: extract folder name from steamapps/common/GameName/
            m = _re.search(r"steamapps/common/([^/]+)", cmd, _re.IGNORECASE)
            if m:
                game_name = m.group(1).strip("'\" ")

            # 2. Known game directories (non-Steam)
            if not game_name:
                for gdir in GAME_DIRS:
                    if gdir.lower() == "steamapps/common":
                        continue  # already handled above
                    if gdir.lower() in lower:
                        # Extract the next path component after the game dir
                        pattern = _re.escape(gdir) + r"([^/]+)"
                        dm = _re.search(pattern, cmd, _re.IGNORECASE)
                        if dm:
                            game_name = dm.group(1).strip("'\" ")
                        else:
                            game_name = gdir.split("/")[0]
                        break

            # 3. Known game binary names (word-boundary regex)
            if not game_name:
                for binary in KNOWN_GAME_BINARIES:
                    bm = _re.search(binary, lower)
                    if bm:
                        game_name = bm.group(0)
                        break

            if game_name:
                games.append({"pid": pid, "name": game_name, "cmd": cmd[:100]})

    except Exception as e:
        LOG.error(f"Error detecting games: {e}")

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
        "aicore-llama3-gpu.service",  # DeepSeek-R1 RLM on port 8101
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
    """Restart previously stopped services using systemctl (parallel)."""
    LOG.info("Restarting services via systemctl...")

    def _restart_one(name: str):
        try:
            subprocess.run(
                ["systemctl", "--user", "unmask", name],
                capture_output=True, text=True, timeout=5
            )
            result = subprocess.run(
                ["systemctl", "--user", "start", name],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                LOG.info(f"Restarted {name}")
            else:
                LOG.warning(f"Could not restart {name}: {result.stderr}")
        except Exception as e:
            LOG.error(f"Error restarting {name}: {e}")

    threads = []
    for service in state.stopped_services:
        name = service.get("name", "")
        stype = service.get("type", "")
        if stype == "systemd" and name:
            t = threading.Thread(target=_restart_one, args=(name,), daemon=True)
            t.start()
            threads.append(t)

    for t in threads:
        t.join(timeout=15)

    state.stopped_services = []
    state.save()
    LOG.info("Services restarted")


def ensure_lightweight_llm():
    """Verify RLM backend is reachable for voice commands."""
    LOG.info("Checking RLM backend availability for voice commands...")
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:8091/health", method="GET")
        urllib.request.urlopen(req, timeout=5)
        LOG.info("RLM backend reachable for voice commands")
    except Exception as e:
        LOG.warning(f"RLM backend not reachable: {e}")


try:
    from config.paths import TEMP_FILES as _GM_TF
    GAMING_LOCK = _GM_TF["gaming_lock"]
except ImportError:
    GAMING_LOCK = Path("/tmp/frank/gaming_lock")


def stop_main_frank():
    """Stop Frank overlay and create lock file to prevent restart.

    Uses SIGTERM (graceful) first, allowing the overlay to save state and
    close databases. Only falls back to SIGKILL if SIGTERM doesn't work.
    """
    LOG.info("Stopping main Frank overlay...")
    # Create lock file FIRST - Frank checks this on startup
    try:
        GAMING_LOCK.write_text(str(os.getpid()))
    except Exception:
        pass
    # Stop via systemd (sends SIGTERM which our handler catches)
    try:
        subprocess.run(
            ["systemctl", "--user", "stop", "frank-overlay.service"],
            capture_output=True, text=True, timeout=10
        )
    except Exception as e:
        LOG.warning(f"systemd stop error: {e}")
    # Check if any lingering process remains — give it 2s to exit gracefully
    try:
        result = subprocess.run(["pgrep", "-f", "chat_overlay.py"],
                                capture_output=True, text=True, timeout=3)
        if result.returncode == 0:
            # Process still alive — send SIGTERM first
            subprocess.run(["pkill", "-f", "chat_overlay.py"], capture_output=True, timeout=3)
            time.sleep(2)
            # Check again — if still alive, force kill
            result2 = subprocess.run(["pgrep", "-f", "chat_overlay.py"],
                                     capture_output=True, text=True, timeout=3)
            if result2.returncode == 0:
                LOG.warning("Overlay didn't exit after SIGTERM, sending SIGKILL")
                subprocess.run(["pkill", "-9", "-f", "chat_overlay.py"], capture_output=True)
    except Exception:
        pass
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


try:
    from config.paths import TEMP_FILES as _TF
    USER_CLOSED_SIGNAL = _TF["user_closed"]
    FRANK_STDERR_LOG = _TF["overlay_stderr_log"]
except ImportError:
    USER_CLOSED_SIGNAL = Path("/tmp/frank/user_closed")
    FRANK_STDERR_LOG = Path("/tmp/frank/overlay_stderr.log")


def _clear_all_start_blockers():
    """Remove ALL files that can prevent Frank overlay from starting."""
    for f in (GAMING_LOCK, USER_CLOSED_SIGNAL):
        try:
            f.unlink(missing_ok=True)
        except Exception:
            pass


def _verify_frank_running(timeout: float = 10.0) -> bool:
    """Wait up to timeout seconds for Frank overlay to be running."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_frank_running():
            return True
        time.sleep(1.0)
    return False


def start_main_frank():
    """Remove all blocker files and start the Frank overlay.

    Tries systemd first (preferred), falls back to direct Popen.
    """
    LOG.info("Starting main Frank overlay...")
    _clear_all_start_blockers()

    # Reset-failed + start in one go (no need to wait between)
    try:
        subprocess.run(
            ["systemctl", "--user", "reset-failed", "frank-overlay.service"],
            capture_output=True, text=True, timeout=3
        )
    except Exception:
        pass

    # Attempt 1: systemd (preferred — proper lifecycle management)
    _clear_all_start_blockers()
    try:
        result = subprocess.run(
            ["systemctl", "--user", "start", "frank-overlay.service"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            LOG.info("Frank overlay start command sent (systemd)")
            # Quick verify (3s) — overlay starts in ~2s, no need to wait 8
            if _verify_frank_running(3.0):
                LOG.info("Frank overlay verified running (systemd)")
                return
            LOG.warning("Frank overlay started via systemd but not running after 3s")
        else:
            LOG.warning(f"systemd start failed ({result.returncode}): {result.stderr.strip()}")
    except Exception as e:
        LOG.warning(f"systemd start error: {e}")

    # Attempt 2: direct Popen (bypasses systemd After= dependencies)
    _clear_all_start_blockers()
    try:
        env = os.environ.copy()
        env["DISPLAY"] = os.environ.get("DISPLAY", ":0")
        env["PYTHONUNBUFFERED"] = "1"
        stderr_file = open(FRANK_STDERR_LOG, "a")
        stderr_file.write(f"\n--- Frank Popen start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        stderr_file.flush()
        try:
            from config.paths import UI_DIR as _UI_DIR_gm
        except ImportError:
            _UI_DIR_gm = Path(__file__).resolve().parents[1] / "ui"
        subprocess.Popen(
            [sys.executable, str(_UI_DIR_gm / "chat_overlay.py")],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=stderr_file,
            start_new_session=True,
        )
        LOG.info("Frank overlay start command sent (Popen)")
        if _verify_frank_running(8.0):
            LOG.info("Frank overlay verified running (Popen)")
            return
        LOG.error(f"Frank overlay NOT running after Popen start — check {FRANK_STDERR_LOG}")
    except Exception as e:
        LOG.error(f"Error starting Frank (direct): {e}")

    # Attempt 3: last resort — ask watchdog to handle it
    LOG.error("All start attempts failed — relying on watchdog for recovery")


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

    LOG.info("Gaming mode activated! No overlay, network monitoring OFF. ✓")


def exit_gaming_mode(state: GamingModeState):
    """Exit gaming mode - restart all services and Frank overlay."""
    LOG.info("🎮 EXITING GAMING MODE")

    # 1. Remove ALL start blockers FIRST so Frank can start immediately
    _clear_all_start_blockers()

    # 2. Reset state immediately
    state.active = False
    state.game_pid = None
    state.game_name = None
    state.save()

    # 3. Start Frank overlay + LLM services ALL in parallel
    def restore_all():
        threads = [
            threading.Thread(target=start_main_frank, daemon=True),
            threading.Thread(target=lambda: (restart_services(state), start_network_sentinel()), daemon=True),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        LOG.info("Gaming mode deactivated! Frank + LLM services restored.")

    # CRITICAL #3: Store thread reference for cleanup
    restore_thread = threading.Thread(target=restore_all, daemon=True, name="restore_all")
    restore_thread.start()
    state._background_threads.append(restore_thread)


def is_process_running(pid: int) -> bool:
    """Check if a process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


_GAME_WM_CLASSES = [
    "steam_app_", "dota", "csgo", "hl2", "unity", "unreal",
    "ut2004", "unrealtournament", "xonotic", "openarena",
    "quake", "supertuxkart", "0ad", "wesnoth", "retroarch",
    "wine", "lutris", "minecraft",
]


def has_game_window() -> bool:
    """Check if any game process is running (process-only, no X11 probing).

    Uses /proc cmdline scanning instead of wmctrl/xprop to avoid
    triggering anti-cheat systems (TCC, EAC, etc.) that detect
    X11 window inspection on game windows.
    """
    import os
    game_proc_patterns = [
        "steam_app_", "steamapps/common/", ".exe",
        "proton", "wine", "lutris",
        "dosbox", "retroarch",
        "oldunreal", "ut2004", "unrealtournament",
        "dota", "factorio", "minecraft",
    ]
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                cmdline = open(f"/proc/{pid}/cmdline", "rb").read().decode("utf-8", errors="ignore").lower()
                if any(g in cmdline for g in game_proc_patterns):
                    return True
            except (PermissionError, FileNotFoundError, ProcessLookupError):
                pass
    except Exception:
        pass
    return False


def is_steam_foreground() -> bool:
    """Check if Steam client is running (process-only, no X11 probing)."""
    return is_steam_client_running()


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
    EXIT_GRACE_CHECKS = 1    # Wait 1 check before exiting if Steam also gone
    EXIT_GRACE_STEAM = 1     # Wait 1 check if Steam still open
    MIN_GAMING_SECS = 30     # Minimum time in gaming mode (game loading protection)
    gaming_entered_at = 0    # Timestamp when gaming mode was entered
    # Entry grace: confirm game is still running before committing to gaming mode
    ENTRY_GRACE_CHECKS = 3   # Game must be detected 3 consecutive times (3s)
    entry_grace_counter = 0  # Counts consecutive game detections
    entry_grace_game = None  # Game info from first detection

    # If we crashed while in gaming mode, clean up
    if state.active:
        LOG.info("Recovering from previous gaming mode state...")
        games = get_running_games()
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
            games = get_running_games()

            if state.active:
                # ENFORCE: Frank must ALWAYS be off during gaming
                if is_frank_running():
                    LOG.info("Frank restarted during gaming mode - stopping again")
                    stop_main_frank()

                # Check ALL signals
                process_running = bool(games) or (state.game_pid and is_process_running(state.game_pid))
                game_window = has_game_window()
                steam_fg = is_steam_foreground()
                steam_alive = is_steam_client_running()

                # Game is active if process OR window OR steam foreground
                game_active = process_running or game_window or steam_fg

                # MIN_GAMING_SECS protection: only applies if game process is still
                # detectable (loading). If game is completely gone, exit immediately
                # (user cancelled launch).
                elapsed = time.time() - gaming_entered_at
                if elapsed < MIN_GAMING_SECS and (process_running or game_window):
                    # Game is loading — don't exit yet
                    time.sleep(CONFIG["check_interval"])
                    continue

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
                game_detected = bool(games) or has_game_window()

                if game_detected:
                    game = games[0] if games else {"pid": 0, "name": "Unknown Game", "cmd": ""}
                    entry_grace_counter += 1
                    if entry_grace_counter == 1:
                        entry_grace_game = game
                        LOG.info(f"Game detected: {game['name']} — confirming ({entry_grace_counter}/{ENTRY_GRACE_CHECKS})...")
                    elif entry_grace_counter < ENTRY_GRACE_CHECKS:
                        LOG.debug(f"Game still running — confirming ({entry_grace_counter}/{ENTRY_GRACE_CHECKS})...")
                    else:
                        # Confirmed! Game is stable — enter gaming mode
                        LOG.info(f"Game confirmed after {ENTRY_GRACE_CHECKS}s: {entry_grace_game['name']}")
                        enter_gaming_mode(state, entry_grace_game)
                        gaming_entered_at = time.time()
                        entry_grace_counter = 0
                        entry_grace_game = None
                else:
                    # No game detected — reset entry grace
                    if entry_grace_counter > 0:
                        LOG.info(f"Game disappeared during entry grace ({entry_grace_counter}/{ENTRY_GRACE_CHECKS}) — cancelled launch, not entering gaming mode")
                    entry_grace_counter = 0
                    entry_grace_game = None

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
