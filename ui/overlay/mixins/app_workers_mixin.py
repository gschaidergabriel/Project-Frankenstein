"""App registry workers – search, open, close, allow, list apps, wallpaper control."""
from __future__ import annotations

import re
import subprocess

from overlay.constants import LOG
from overlay.services.toolbox import _app_search, _app_open, _app_close, _app_allow, _app_list, _get_window_ids
from overlay.services.wallpaper import wp_tool, wp_game_launch


class AppWorkersMixin:
    """App registry integration and wallpaper control workers."""

    def _do_app_search_worker(self, query: str, user_query: str = ""):
        """Search for apps via app registry."""
        result = _app_search(query, limit=10)
        if result and result.get("ok"):
            apps = result.get("apps", [])
            if apps:
                lines = [f"Apps found for '{query}':"]
                for i, app in enumerate(apps[:8], 1):
                    name = app.get("name", "?")
                    source = app.get("source", "?")
                    effective = app.get("effective", False)
                    status = "ready" if effective else "blocked"
                    lines.append(f"  {i}. {name} ({source}) - {status}")
                self._ui_call(lambda r="\n".join(lines): self._add_message("Frank", r))
            else:
                self._ui_call(lambda q=query: self._add_message("Frank", f"No apps found for '{q}'.", is_system=True))
        else:
            error = result.get("error", "Unknown error") if result else "No response"
            self._ui_call(lambda e=error: self._add_message("Frank", f"App search failed: {e}", is_system=True))

    def _ensure_steam_imports(self):
        """Lazy-import Steam integration module."""
        import sys
        try:
            from config.paths import AICORE_ROOT as _AICORE_ROOT
        except ImportError:
            from pathlib import Path as _P
            _AICORE_ROOT = _P("/home/ai-core-node/aicore/opt/aicore")
        if str(_AICORE_ROOT) not in sys.path:
            sys.path.insert(0, str(_AICORE_ROOT))
        import tools.steam_integration as steam
        return steam

    def _do_app_open_worker(self, app: str, from_user_query: str = "", voice: bool = False):
        """Open an app via app registry with robust Steam game support."""
        self._ui_call(lambda: self._show_typing())

        def _reply(msg, is_system=False):
            if voice:
                self._ui_call(lambda m=msg: self._voice_respond(m))
            else:
                self._ui_call(lambda m=msg: self._add_message("Frank", m, is_system=is_system))

        def _launch_steam_game(steam, game):
            """Launch a Steam game with wallpaper effect and verification."""
            try:
                wp_game_launch(game.name)
            except Exception:
                pass
            success, msg = steam.launch_game(game)
            self._ui_call(self._hide_typing)
            _reply(msg)
            if success:
                # Minimize overlay — gaming mode daemon handles full stop
                self._ui_call(lambda: self._minimize_overlay())
                # Verify game actually started (background check)
                self._verify_game_launch_bg(steam, game)

        # ── Import Steam integration (used across all steps) ──────────
        steam = None
        try:
            steam = self._ensure_steam_imports()
        except Exception as e:
            LOG.debug(f"Steam integration not available: {e}")

        # ── Step 1: Check if this is a Steam game via alias ────────────
        try:
            if not steam:
                raise ImportError("Steam not available")
            alias = steam.resolve_alias(app)
            if alias:
                appid, canonical_name = alias
                if appid == "0":
                    # Game not on Steam
                    self._ui_call(self._hide_typing)
                    _reply(f"{canonical_name} ist nicht auf Steam verfuegbar.", is_system=True)
                    return

                # Check if game is installed
                games = steam.get_installed_games()
                for game in games:
                    if game.appid == appid:
                        _launch_steam_game(steam, game)
                        return

                # Known alias but not installed — offer to install
                self._ui_call(self._hide_typing)
                success, msg = steam.open_store_page(appid, canonical_name)
                _reply(msg if success else f"{canonical_name} ist nicht installiert.")
                return
        except Exception as e:
            LOG.debug(f"Steam alias check failed: {e}")

        # ── Step 2: Search app registry (.desktop files) ──────────────
        search_result = _app_search(app, limit=5)
        apps = []
        if search_result and search_result.get("ok"):
            apps = search_result.get("apps", [])

        # If app registry found a Steam game, use Steam integration
        if apps:
            best = apps[0]
            exec_cmd = best.get("exec_cmd", "")
            app_name = best.get("name", app)

            if "steam://rungameid/" in exec_cmd and steam:
                # Steam game found in .desktop files — launch via Steam
                try:
                    import re as _re
                    appid_match = _re.search(r'rungameid/(\d+)', exec_cmd)
                    if appid_match:
                        appid = appid_match.group(1)
                        # Find full game info from ACF for update status
                        games = steam.get_installed_games()
                        game = None
                        for g in games:
                            if g.appid == appid:
                                game = g
                                break
                        if not game:
                            game = steam.SteamGame(appid=appid, name=app_name, install_dir="")
                        _launch_steam_game(steam, game)
                        return
                except Exception as e:
                    LOG.error(f"Steam desktop launch failed: {e}")

            # Non-Steam app from registry
            app_id = best.get("id", "")
            allowed = best.get("allowed", False)

            if not allowed:
                _app_allow(app_id)

            windows_before = _get_window_ids()
            open_result = _app_open(app_id)
            self._ui_call(self._hide_typing)

            if open_result and open_result.get("ok"):
                wp_tool("app_open", app_name)
                _reply(f"Starte {app_name}...")
                return
            else:
                reason = open_result.get("reason", "start_failed") if open_result else "no_response"
                if reason == "policy_blocked":
                    _app_allow(app_id)
                    retry = _app_open(app_id)
                    if retry and retry.get("ok"):
                        wp_tool("app_open", app_name)
                        _reply(f"Starte {app_name}...")
                        return
                # App registry launch failed — fall through to Steam fallback
                LOG.debug(f"App registry launch failed for '{app}', trying Steam fallback")

        # ── Step 3: Steam fallback — search installed games ───────────
        try:
            if not steam:
                steam = self._ensure_steam_imports()
            games = steam.get_installed_games()
            game = steam.find_game_by_name(app, games) if games else None

            if game:
                _launch_steam_game(steam, game)
                return

            # ── Step 4: Not installed — check alias or offer store ────
            alias = steam.resolve_alias(app)
            if alias:
                appid, canonical_name = alias
                if appid != "0":
                    self._ui_call(self._hide_typing)
                    success, msg = steam.open_store_page(appid, canonical_name)
                    _reply(msg if success else f"{canonical_name} ist nicht installiert.")
                    return

            # ── Step 5: Nothing found — inform user ───────────────────
            self._ui_call(self._hide_typing)
            if games:
                names = [g.name for g in games[:5]]
                _reply(
                    f"'{app}' nicht gefunden.\n"
                    f"Installierte Spiele: {', '.join(names)}",
                    is_system=True,
                )
            else:
                _reply(f"'{app}' nicht gefunden.", is_system=True)

        except Exception as e:
            LOG.error(f"Steam fallback failed: {e}")
            self._ui_call(self._hide_typing)
            _reply(f"Konnte '{app}' nicht starten: {e}", is_system=True)

    def _verify_game_launch_bg(self, steam, game):
        """Background verification that a game actually launched."""
        import threading

        def _check():
            try:
                launched, status = steam.verify_game_launched(game, timeout=20.0)
                if not launched:
                    # Game didn't appear — notify user
                    self._ui_call(
                        lambda s=status: self._add_message("Frank", s, is_system=True)
                    )
            except Exception as e:
                LOG.debug(f"Game launch verification failed: {e}")

        t = threading.Thread(target=_check, daemon=True, name=f"verify-{game.appid}")
        t.start()

    def _do_app_close_worker(self, app: str):
        """Close an app via app registry with fallback to direct kill."""
        app_lower = app.lower().strip()
        app_name = app

        # Try toolbox first
        result = _app_close(app)
        if result and result.get("ok"):
            app_name = result.get("name", app)
            self._ui_call(lambda n=app_name: self._add_message("Frank", f"Closing {n}..."))
            return

        # Toolbox failed - try direct methods
        LOG.debug(f"Toolbox close failed for '{app}', trying direct methods")

        closed = False

        # Method 1: Close window via wmctrl (graceful)
        try:
            res = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=2)
            for line in res.stdout.strip().split('\n'):
                if not line:
                    continue
                parts = line.split(None, 4)
                if len(parts) >= 4:
                    win_id = parts[0]
                    title = parts[-1].lower() if len(parts) > 3 else ""
                    if app_lower in title:
                        subprocess.run(["wmctrl", "-i", "-c", win_id], timeout=2)
                        LOG.debug(f"Closed window {win_id} via wmctrl -c")
                        closed = True
        except Exception as e:
            LOG.debug(f"wmctrl close failed: {e}")

        # Method 2: pkill by process name
        if not closed:
            # Map common app names to process names
            process_names = {
                "discord": ["Discord", "discord"],
                "firefox": ["firefox", "firefox-esr"],
                "chrome": ["chrome", "chromium", "google-chrome"],
                "steam": ["steam"],
                "spotify": ["spotify"],
                "slack": ["slack"],
                "code": ["code", "Code"],
                "vscode": ["code", "Code"],
                "blender": ["blender"],
                "gimp": ["gimp"],
                "vlc": ["vlc"],
                "nautilus": ["nautilus"],
                "files": ["nautilus"],
                "terminal": ["gnome-terminal", "konsole", "xterm"],
                "libreoffice": ["soffice"],
            }

            procs = process_names.get(app_lower, [app, app.capitalize(), app.title()])

            for proc in procs:
                try:
                    # Try graceful SIGTERM first
                    result = subprocess.run(["pkill", "-f", proc], capture_output=True, timeout=2)
                    if result.returncode == 0:
                        LOG.debug(f"Killed process '{proc}' via pkill")
                        closed = True
                        break
                except Exception:
                    pass

        # Method 3: Force kill if still running
        if not closed:
            for proc in procs if 'procs' in dir() else [app]:
                try:
                    result = subprocess.run(["pkill", "-9", "-f", proc], capture_output=True, timeout=2)
                    if result.returncode == 0:
                        LOG.debug(f"Force killed process '{proc}'")
                        closed = True
                        break
                except Exception:
                    pass

        if closed:
            self._ui_call(lambda a=app_name: self._add_message("Frank", f"{a} closed."))
        else:
            self._ui_call(lambda a=app: self._add_message("Frank", f"Could not close '{a}'.", is_system=True))

    def _do_app_allow_worker(self, app: str):
        """Allow an app (add to session permissions)."""
        # First search for the app
        search_result = _app_search(app, limit=3)
        if not search_result or not search_result.get("ok"):
            self._ui_call(lambda a=app: self._add_message("Frank", f"App '{a}' not found.", is_system=True))
            return

        apps = search_result.get("apps", [])
        if not apps:
            self._ui_call(lambda a=app: self._add_message("Frank", f"App '{a}' not found.", is_system=True))
            return

        best = apps[0]
        app_id = best.get("id", "")
        app_name = best.get("name", app)

        result = _app_allow(app_id)
        if result and result.get("ok"):
            self._ui_call(lambda n=app_name: self._add_message("Frank", f"'{n}' is now allowed. You can start it with 'open {n}'."))
        else:
            error = result.get("error", "Unknown error") if result else "No response"
            self._ui_call(lambda n=app_name, e=error: self._add_message("Frank", f"Could not allow '{n}': {e}", is_system=True))

    def _do_app_list_worker(self, filter_type: str = "all"):
        """List apps from registry, organized by category."""
        effective_only = (filter_type == "effective")
        result = _app_list(effective_only=effective_only, limit=500)
        if result and result.get("ok"):
            apps = result.get("apps", [])
            if apps:
                # Category mapping based on .desktop categories
                category_map = {
                    "Browser": ["WebBrowser", "Network"],
                    "Office": ["Office", "WordProcessor", "Spreadsheet", "Presentation"],
                    "Graphics": ["Graphics", "ImageEditor", "VectorGraphics", "3DGraphics", "Photography"],
                    "Multimedia": ["AudioVideo", "Audio", "Video", "Player", "Recorder"],
                    "Development": ["Development", "IDE", "TextEditor", "Debugger"],
                    "Games": ["Game", "ActionGame", "AdventureGame", "ArcadeGame", "StrategyGame"],
                    "System": ["System", "Settings", "DesktopSettings", "HardwareSettings", "Monitor"],
                    "Utilities": ["Utility", "FileManager", "Archiving", "Compression", "Calculator"],
                    "Communication": ["InstantMessaging", "Chat", "Email", "ContactManagement"],
                }

                # Categorize apps
                categorized = {cat: [] for cat in category_map}
                categorized["Other"] = []

                for app in apps:
                    name = app.get("name", "?")
                    source = app.get("source", "?")
                    effective = app.get("effective", False)
                    app_cats = app.get("categories", [])

                    status_icon = "\u2713" if effective else "\u25cb"
                    entry = f"{status_icon} {name}"
                    if source != "desktop":
                        entry += f" [{source}]"

                    # Find matching category
                    placed = False
                    for cat_name, cat_keys in category_map.items():
                        if any(k in app_cats for k in cat_keys):
                            categorized[cat_name].append(entry)
                            placed = True
                            break
                    if not placed:
                        categorized["Other"].append(entry)

                # Build output
                lines = ["Installed programs:\n"]
                lines.append("\u2713 = ready | \u25cb = blocked (use 'allow X' to enable)\n")

                for cat_name in ["Browser", "Office", "Graphics", "Multimedia", "Development",
                                 "Games", "System", "Utilities", "Communication", "Other"]:
                    cat_apps = categorized.get(cat_name, [])
                    if cat_apps:
                        lines.append(f"\u2501\u2501 {cat_name} ({len(cat_apps)}) \u2501\u2501")
                        for entry in sorted(set(cat_apps))[:15]:  # Dedupe & limit per category
                            lines.append(f"  {entry}")
                        if len(cat_apps) > 15:
                            lines.append(f"  ... +{len(cat_apps) - 15} more")
                        lines.append("")

                ready = sum(1 for a in apps if a.get("effective"))
                lines.append(f"Total: {len(apps)} apps ({ready} ready)")

                self._ui_call(lambda r="\n".join(lines): self._add_message("Frank", r))
            else:
                self._ui_call(lambda: self._add_message("Frank", "No apps found.", is_system=True))
        else:
            error = result.get("error", "Unknown error") if result else "No response"
            self._ui_call(lambda e=error: self._add_message("Frank", f"App list failed: {e}", is_system=True))

    # ---------- Wallpaper Control ----------
    def _control_wallpaper(self, action: str) -> tuple:
        """Control the live wallpaper (start/stop)."""
        try:
            import sys
            try:
                from config.paths import AICORE_ROOT as _AICORE_ROOT
            except ImportError:
                from pathlib import Path as _P
                _AICORE_ROOT = _P("/home/ai-core-node/aicore/opt/aicore")
            sys.path.insert(0, str(_AICORE_ROOT))
            from live_wallpaper.wallpaper_control import start, stop, status

            if action == "start":
                ok, msg = start()
                return ok, f"Wallpaper: {msg}"
            elif action == "stop":
                ok, msg = stop()
                return ok, f"Wallpaper: {msg}"
            elif action == "status":
                s = status()
                if s.get("running"):
                    return True, f"Wallpaper running (PID {s.get('pid', '?')})"
                return True, f"Wallpaper is off (systemd: {s.get('systemd', '?')})"
            else:
                return False, f"Unknown action: {action}"
        except Exception as e:
            LOG.error(f"Wallpaper control error: {e}")
            return False, f"Error: {e}"
