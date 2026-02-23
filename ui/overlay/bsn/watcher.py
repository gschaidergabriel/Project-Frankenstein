import subprocess
import threading
import time
from overlay.constants import LOG


class WindowWatcher:
    """Monitors new windows and triggers layout adjustment."""

    def __init__(self, layout_controller):
        self.controller = layout_controller
        self.known_windows = set()
        self.running = False
        self._thread = None

    def start(self):
        """Starts the watcher."""
        self.running = True
        self.known_windows = self._get_windows()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        LOG.info("BSN: WindowWatcher started")

    def stop(self):
        """Stops the watcher."""
        self.running = False
        LOG.info("BSN: WindowWatcher stopped")

    def _loop(self):
        """Main loop — new window detection + boundary snap on drop."""
        self._prev_positions = {}  # win_id → (x, y) from last cycle
        self._stable_counts = {}   # win_id → consecutive cycles at same position
        self._frank_right_cache = (0, 0)  # (value, timestamp)
        while self.running:
            # Completely pause during gaming mode — no wmctrl/xprop/xdotool
            # calls that anti-cheat systems could flag as suspicious
            if self.controller.is_gaming_mode():
                time.sleep(2)
                continue

            try:
                result = subprocess.run(
                    ["wmctrl", "-lG"],
                    capture_output=True, text=True, timeout=2
                )
                current = set()
                win_info = {}  # win_id → (desktop, title)
                for line in result.stdout.strip().split('\n'):
                    if not line:
                        continue
                    parts = line.split(None, 8)
                    if len(parts) >= 8:
                        current.add(parts[0])
                        win_info[parts[0]] = (parts[1], parts[7] if len(parts) > 7 else "")

                new_windows = current - self.known_windows
                for win_id in new_windows:
                    desktop, title = win_info.get(win_id, ("0", ""))
                    self._handle_new_window(win_id, desktop, title)
                self.known_windows = current

            except Exception as e:
                LOG.error(f"BSN: WindowWatcher error: {e}")

            time.sleep(0.5)

    def _get_frank_right(self) -> int:
        """Get Frank's actual right edge in wmctrl coordinates (cached 1s)."""
        now = time.time()
        val, ts = self._frank_right_cache
        if now - ts < 1.0 and val:
            return val
        try:
            result = subprocess.run(
                ["wmctrl", "-lG"], capture_output=True, text=True, timeout=1
            )
            for line in result.stdout.strip().split('\n'):
                if "F.R.A.N.K" in line:
                    p = line.split(None, 8)
                    if len(p) >= 6:
                        right = int(p[2]) + int(p[4])
                        self._frank_right_cache = (right, now)
                        return right
        except Exception:
            pass
        return 0

    def _enforce_boundary_on_drop(self, windows_geo: list):
        """Snap windows to the overlay boundary when user releases the drag.

        Also clamps windows overflowing the primary monitor (once, with cooldown).
        Windows on secondary monitors are left completely untouched.
        """
        frank_right = self._get_frank_right()
        if not frank_right:
            return

        primary_right = self._get_primary_right()
        now = time.time()
        if not hasattr(self, '_clamp_cooldown'):
            self._clamp_cooldown = {}  # win_id → timestamp of last clamp

        new_positions = {}
        new_stable = {}
        for win_id, desktop, x, y, w, h, title in windows_geo:
            if desktop == "-1":
                continue
            tl = title.lower()
            if "f.r.a.n.k" in tl or "neural core" in tl or "cybercore" in tl:
                continue

            new_positions[win_id] = (x, y, w)

            # Skip windows on secondary monitors (x beyond primary)
            if x >= primary_right:
                continue

            if w <= 50:
                continue

            # Clamp windows overflowing primary monitor right edge (once per 30s)
            if x + w > primary_right + 10 and x >= frank_right:
                last_clamp = self._clamp_cooldown.get(win_id, 0)
                if now - last_clamp > 30:
                    new_w = primary_right - x
                    if new_w >= 200:
                        LOG.info(f"BSN: Clamp overflow {win_id} w={w} → {new_w}")
                        try:
                            subprocess.run(
                                ["wmctrl", "-i", "-r", win_id,
                                 "-e", f"0,{x},{y},{new_w},{h}"],
                                capture_output=True, timeout=1
                            )
                            new_positions[win_id] = (x, y, new_w)
                            self._clamp_cooldown[win_id] = now
                        except Exception:
                            pass
                continue

            if x >= frank_right:
                continue

            # Skip if width changed (user is resizing, not dragging)
            prev = self._prev_positions.get(win_id)
            if prev and len(prev) >= 3 and prev[2] != w:
                new_stable[win_id] = 0
                continue

            # Track how many cycles window has been at the same position
            if prev and (prev[0], prev[1]) == (x, y):
                new_stable[win_id] = self._stable_counts.get(win_id, 0) + 1
            else:
                new_stable[win_id] = 0

            # Only snap after 5 stable cycles (500ms of no movement = drop)
            if new_stable.get(win_id, 0) >= 5:
                new_x = frank_right + 2
                new_w = min(w, primary_right - new_x)
                LOG.info(f"BSN: Snap {win_id} → x={new_x}, w={new_w}")
                try:
                    subprocess.run(
                        ["wmctrl", "-i", "-r", win_id,
                         "-e", f"0,{new_x},{y},{new_w},{h}"],
                        capture_output=True, timeout=1
                    )
                    new_positions[win_id] = (new_x, y, new_w)
                    new_stable[win_id] = 0
                except Exception:
                    pass

        self._prev_positions = new_positions
        self._stable_counts = new_stable

    def _get_primary_right(self) -> int:
        """Get the right edge of the primary monitor (cached)."""
        cached = getattr(self, '_primary_right_cache', 0)
        if cached:
            return cached
        try:
            from overlay.bsn.constants import get_primary_monitor
            mon = get_primary_monitor()
            val = mon["x"] + mon["width"]
            self._primary_right_cache = val
            return val
        except Exception:
            return 1600

    def _get_windows(self) -> set:
        """Gets all window IDs via wmctrl."""
        try:
            result = subprocess.run(
                ["wmctrl", "-l"],
                capture_output=True, text=True, timeout=2
            )
            windows = set()
            for line in result.stdout.strip().split('\n'):
                if line:
                    parts = line.split()
                    if len(parts) >= 1:
                        windows.add(parts[0])
            return windows
        except Exception:
            return set()

    def _handle_new_window(self, win_id: str, desktop: str = "0", title: str = ""):
        """Handles a new window.

        Uses wmctrl-provided desktop/title for fast filtering (no xprop/xdotool).
        Only falls back to subprocess probes for windows that pass the fast checks.
        """
        tl = title.lower()

        # Gaming Mode Check
        if self.controller.is_gaming_mode():
            LOG.debug(f"BSN: Gaming mode - ignoring {win_id}")
            return

        # Skip sticky windows (desktop=-1): Steam client, desktop overlays, etc.
        if desktop == "-1":
            LOG.debug(f"BSN: Sticky window (desktop=-1) - ignoring {win_id}")
            return

        # Skip Frank / wallpaper by title (no subprocess needed)
        if "f.r.a.n.k" in tl or "neural core" in tl or "cybercore" in tl:
            LOG.debug(f"BSN: Frank/wallpaper - ignoring {win_id}")
            return

        # Skip known game patterns by title (no subprocess probing!)
        game_patterns = [
            "steam_app_", "unreal", "godot", "unity",
            "proton", "wine", "lutris", "dosbox", "retroarch",
            "oldunreal", "ut2004", "ut2003", "unrealtournament",
            "dota", "counter-strike", "factorio", "minecraft", "terraria",
        ]
        for gp in game_patterns:
            if gp in tl:
                LOG.info(f"BSN: Game window '{title[:30]}' - ignoring {win_id}")
                return

        # Skip windows on secondary monitors (needs xdotool - safe, not a game)
        if self._is_on_secondary_monitor(win_id):
            LOG.debug(f"BSN: Secondary monitor - ignoring {win_id}")
            return

        # Skip small dialogs
        if self._is_dialog(win_id):
            LOG.debug(f"BSN: Dialog detected - ignoring {win_id}")
            return

        LOG.info(f"BSN: New window detected: {win_id} '{title[:40]}'")


        # Brief wait for window to be renderable
        time.sleep(0.05)

        self.controller.handle_new_window(win_id)

    def _unmaximize_if_needed(self, win_id: str):
        """Immediately unmaximize a window if it started maximized.

        Apps like Firefox, Nautilus, etc. often start maximized by default.
        BSN needs them un-maximized to position them side-by-side with Frank.
        Doing this ASAP prevents the visible flash of a fullscreen window.
        """
        try:
            result = subprocess.run(
                ["xprop", "-id", win_id, "_NET_WM_STATE"],
                capture_output=True, text=True, timeout=1
            )
            state = result.stdout
            if ('_NET_WM_STATE_MAXIMIZED_VERT' in state
                    and '_NET_WM_STATE_MAXIMIZED_HORZ' in state):
                LOG.info(f"BSN: Window {win_id} started maximized — unmaximizing for layout")
                subprocess.run([
                    "wmctrl", "-i", "-r", win_id,
                    "-b", "remove,maximized_vert,maximized_horz"
                ], capture_output=True, timeout=1)
        except Exception as e:
            LOG.debug(f"BSN: Unmaximize check error: {e}")

    def _is_sticky_window(self, win_id: str) -> bool:
        """Check if window is on desktop -1 (sticky/all-desktops, e.g. Steam client)."""
        try:
            result = subprocess.run(
                ["xprop", "-id", win_id, "_NET_WM_DESKTOP"],
                capture_output=True, text=True, timeout=1
            )
            # _NET_WM_DESKTOP(CARDINAL) = 4294967295  (= 0xFFFFFFFF = -1)
            if "4294967295" in result.stdout:
                return True
        except Exception:
            pass
        return False

    def _is_frank_window(self, win_id: str) -> bool:
        """Checks if it is the Frank window."""
        try:
            result = subprocess.run(
                ["xdotool", "getwindowname", win_id],
                capture_output=True, text=True, timeout=1
            )
            name = result.stdout.strip().lower()
            return "f.r.a.n.k" in name or ("frank" in name and "chat" in name)
        except Exception:
            return False

    def _is_wallpaper(self, win_id: str) -> bool:
        """Checks if it is the wallpaper window (FRANK NEURAL CORE)."""
        try:
            result = subprocess.run(
                ["xdotool", "getwindowname", win_id],
                capture_output=True, text=True, timeout=1
            )
            name = result.stdout.strip().lower()
            return "neural core" in name or "cybercore" in name
        except Exception:
            return False

    def _is_dialog(self, win_id: str) -> bool:
        """Checks if it is a small dialog."""
        try:
            result = subprocess.run(
                ["xdotool", "getwindowgeometry", "--shell", win_id],
                capture_output=True, text=True, timeout=1
            )
            geo = {}
            for line in result.stdout.strip().split('\n'):
                if '=' in line:
                    k, v = line.split('=')
                    geo[k] = int(v)

            w = geo.get("WIDTH", 0)
            h = geo.get("HEIGHT", 0)

            # Dialogs are typically small
            return w < 400 and h < 300
        except Exception:
            return False

    def _is_on_secondary_monitor(self, win_id: str) -> bool:
        """Check if a window is on a secondary monitor (not the primary)."""
        try:
            result = subprocess.run(
                ["xdotool", "getwindowgeometry", "--shell", win_id],
                capture_output=True, text=True, timeout=1
            )
            geo = {}
            for line in result.stdout.strip().split('\n'):
                if '=' in line:
                    k, v = line.split('=')
                    geo[k] = int(v)
            win_x = geo.get("X", 0)
            primary_right = self._get_primary_right()
            return win_x >= primary_right
        except Exception:
            return False

    def _is_game(self, win_id: str) -> bool:
        """
        Checks if it is a game window (games are not repositioned).
        Detection via WM_CLASS and known game patterns.
        """
        try:
            # Get WM_CLASS via xprop
            result = subprocess.run(
                ["xprop", "-id", win_id, "WM_CLASS"],
                capture_output=True, text=True, timeout=1
            )
            wm_class = result.stdout.lower()

            # Steam games have WM_CLASS containing "steam_app_"
            if "steam_app_" in wm_class:
                LOG.debug(f"BSN: Steam game detected via WM_CLASS")
                return True

            # Common game engines/launchers
            game_classes = [
                "unity", "unreal", "godot", "gamemaker",
                "proton", "wine", "lutris",
                "dosbox", "retroarch", "pcsx", "dolphin-emu",
                "factorio", "minecraft", "terraria",
            ]
            for gc in game_classes:
                if gc in wm_class:
                    LOG.debug(f"BSN: Game detected via WM_CLASS pattern: {gc}")
                    return True

            # Get window name
            result = subprocess.run(
                ["xdotool", "getwindowname", win_id],
                capture_output=True, text=True, timeout=1
            )
            name = result.stdout.strip().lower()

            # Known game title patterns
            game_titles = [
                "steam", "proton", "wine",
                # Add specific game titles as needed
            ]

            # Don't mark as game just for these - they're launchers, not games
            # Only steam_app_* WM_CLASS should trigger game mode

        except Exception as e:
            LOG.debug(f"BSN: Game detection error: {e}")

        return False
