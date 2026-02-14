import subprocess
import threading
import time
from overlay.constants import LOG


class WindowWatcher:
    """Überwacht neue Fenster und triggert Layout-Anpassung."""

    def __init__(self, layout_controller):
        self.controller = layout_controller
        self.known_windows = set()
        self.running = False
        self._thread = None

    def start(self):
        """Startet den Watcher."""
        self.running = True
        self.known_windows = self._get_windows()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        LOG.info("BSN: WindowWatcher started")

    def stop(self):
        """Stoppt den Watcher."""
        self.running = False
        LOG.info("BSN: WindowWatcher stopped")

    def _loop(self):
        """Hauptschleife - prüft alle 250ms auf neue Fenster."""
        while self.running:
            try:
                current = self._get_windows()
                new_windows = current - self.known_windows

                for win_id in new_windows:
                    self._handle_new_window(win_id)

                self.known_windows = current
            except Exception as e:
                LOG.error(f"BSN: WindowWatcher error: {e}")

            time.sleep(0.25)

    def _get_windows(self) -> set:
        """Holt alle Window-IDs via wmctrl."""
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

    def _handle_new_window(self, win_id: str):
        """Behandelt ein neues Fenster."""
        # Gaming Mode Check
        if self.controller.is_gaming_mode():
            LOG.debug(f"BSN: Gaming mode - ignoring {win_id}")
            return

        # Skip Frank selbst
        if self._is_frank_window(win_id):
            LOG.debug(f"BSN: Frank window - ignoring {win_id}")
            return

        # Skip kleine Dialoge
        if self._is_dialog(win_id):
            LOG.debug(f"BSN: Dialog detected - ignoring {win_id}")
            return

        # Skip Games (vollständig ausgenommen von Positionierung)
        if self._is_game(win_id):
            LOG.info(f"BSN: Game window detected - ignoring {win_id}")
            return

        # Skip Wallpaper (FRANK NEURAL CORE)
        if self._is_wallpaper(win_id):
            LOG.debug(f"BSN: Wallpaper window - ignoring {win_id}")
            return

        LOG.info(f"BSN: New window detected: {win_id}")

        # Kurz warten bis Fenster vollständig gerendert
        time.sleep(0.1)

        self.controller.handle_new_window(win_id)

    def _is_frank_window(self, win_id: str) -> bool:
        """Prüft ob es das Frank-Fenster ist."""
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
        """Prüft ob es das Wallpaper-Fenster ist (FRANK NEURAL CORE)."""
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
        """Prüft ob es ein kleiner Dialog ist."""
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

            # Dialoge sind typischerweise klein
            return w < 400 and h < 300
        except Exception:
            return False

    def _is_game(self, win_id: str) -> bool:
        """
        Prüft ob es ein Game-Fenster ist (Games werden nicht repositioniert).
        Erkennung via WM_CLASS und bekannte Game-Patterns.
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
