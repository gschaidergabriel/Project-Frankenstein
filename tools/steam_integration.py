#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Steam Integration for Frank

Provides:
- List installed Steam games
- Launch games by name (fuzzy matching + aliases)
- Game status detection (updates, downloading)
- Launch verification (checks if game actually started)
- Uninstalled game support (open Steam Store page)
- Get game info
- Close running games

Note: Frank can do everything EXCEPT delete games.
"""

import os
import re
import subprocess
import logging
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
import difflib

LOG = logging.getLogger("steam_integration")

# Possible Steam installation paths
STEAM_PATHS = [
    Path.home() / "snap/steam/common/.local/share/Steam",
    Path.home() / ".steam/steam",
    Path.home() / ".local/share/Steam",
    Path("/usr/share/steam"),
]

# Common game aliases → canonical name fragments or appids
# Maps user-friendly abbreviations to (appid, canonical_name) tuples
GAME_ALIASES: Dict[str, Tuple[str, str]] = {
    # Counter-Strike
    "cs2": ("730", "Counter-Strike 2"),
    "cs": ("730", "Counter-Strike 2"),
    "csgo": ("730", "Counter-Strike 2"),
    "counterstrike": ("730", "Counter-Strike 2"),
    "counter strike": ("730", "Counter-Strike 2"),
    # Dota
    "dota": ("570", "Dota 2"),
    "dota2": ("570", "Dota 2"),
    # Team Fortress
    "tf2": ("440", "Team Fortress 2"),
    "tf": ("440", "Team Fortress 2"),
    "teamfortress": ("440", "Team Fortress 2"),
    # Half-Life
    "hl2": ("220", "Half-Life 2"),
    "halflife2": ("220", "Half-Life 2"),
    "halflife": ("70", "Half-Life"),
    # Portal
    "portal": ("400", "Portal"),
    "portal2": ("620", "Portal 2"),
    # Left 4 Dead
    "l4d": ("500", "Left 4 Dead"),
    "l4d2": ("550", "Left 4 Dead 2"),
    # GTA
    "gta5": ("271590", "Grand Theft Auto V"),
    "gtav": ("271590", "Grand Theft Auto V"),
    "gta": ("271590", "Grand Theft Auto V"),
    # Civilization
    "civ6": ("289070", "Sid Meier's Civilization VI"),
    "civ5": ("8930", "Sid Meier's Civilization V"),
    # Others
    "nms": ("275850", "No Man's Sky"),
    "nomanssky": ("275850", "No Man's Sky"),
    "pubg": ("578080", "PUBG: BATTLEGROUNDS"),
    "rust": ("252490", "Rust"),
    "ark": ("346110", "ARK: Survival Evolved"),
    "elden ring": ("1245620", "ELDEN RING"),
    "eldenring": ("1245620", "ELDEN RING"),
    "cyberpunk": ("1091500", "Cyberpunk 2077"),
    "witcher3": ("292030", "The Witcher 3"),
    "witcher": ("292030", "The Witcher 3"),
    "darksouls3": ("374320", "DARK SOULS III"),
    "darksouls": ("374320", "DARK SOULS III"),
    "minecraft": ("1672970", "Minecraft: Java & Bedrock Edition"),
    "terraria": ("105600", "Terraria"),
    "stardew": ("413150", "Stardew Valley"),
    "stardewvalley": ("413150", "Stardew Valley"),
    "among us": ("945360", "Among Us"),
    "amongus": ("945360", "Among Us"),
    "apex": ("1172470", "Apex Legends"),
    "apexlegends": ("1172470", "Apex Legends"),
    "valorant": ("0", "Valorant"),  # Not on Steam, but we can tell the user
    "fortnite": ("0", "Fortnite"),  # Not on Steam
    "lol": ("0", "League of Legends"),  # Not on Steam
    "overwatch": ("2357570", "Overwatch 2"),
    "ow2": ("2357570", "Overwatch 2"),
    "palworld": ("1623730", "Palworld"),
    "lethal company": ("1966720", "Lethal Company"),
    "lethalcompany": ("1966720", "Lethal Company"),
    "baldurs gate": ("1086940", "Baldur's Gate 3"),
    "bg3": ("1086940", "Baldur's Gate 3"),
    "dark and darker": ("2016590", "Dark and Darker"),
    "darkanddarker": ("2016590", "Dark and Darker"),
    "dad": ("2016590", "Dark and Darker"),
}

# Steam ACF StateFlags meaning
STATE_FULLY_INSTALLED = 4
STATE_UPDATE_REQUIRED = 2
STATE_UPDATE_RUNNING = 1024


@dataclass
class SteamGame:
    """Represents an installed Steam game."""
    appid: str
    name: str
    install_dir: str
    size_on_disk: int = 0
    last_played: int = 0
    is_downloading: bool = False
    state_flags: int = 0
    bytes_to_download: int = 0
    bytes_downloaded: int = 0

    def __str__(self):
        return f"{self.name} (ID: {self.appid})"

    @property
    def needs_update(self) -> bool:
        """Check if game has a pending update."""
        return bool(self.state_flags & STATE_UPDATE_REQUIRED)

    @property
    def is_update_running(self) -> bool:
        """Check if game update is currently downloading."""
        return bool(self.state_flags & STATE_UPDATE_RUNNING)

    @property
    def update_progress_mb(self) -> Tuple[int, int]:
        """Return (downloaded_mb, total_mb) for pending update."""
        return (
            self.bytes_downloaded // (1024 * 1024),
            self.bytes_to_download // (1024 * 1024),
        )


def find_steam_path() -> Optional[Path]:
    """Find the Steam installation directory."""
    for path in STEAM_PATHS:
        steamapps = path / "steamapps"
        if steamapps.exists():
            return path
    return None


def is_steam_snap() -> bool:
    """Check if Steam is installed as a snap."""
    return (Path.home() / "snap/steam").exists()


def _steam_cmd_prefix() -> List[str]:
    """Get the correct command prefix for launching Steam commands."""
    if is_steam_snap():
        return ["snap", "run", "steam"]
    return ["steam"]


def parse_acf_file(filepath: Path) -> Dict[str, str]:
    """Parse a Steam ACF (App Cache File) manifest."""
    data = {}
    try:
        content = filepath.read_text(encoding='utf-8', errors='ignore')

        # Simple regex-based parsing for key-value pairs
        # Format: "key"		"value"
        pattern = r'"(\w+)"\s+"([^"]*)"'
        matches = re.findall(pattern, content)

        for key, value in matches:
            data[key.lower()] = value

    except Exception as e:
        LOG.error(f"Error parsing {filepath}: {e}")

    return data


def get_installed_games() -> List[SteamGame]:
    """Get list of all installed Steam games."""
    games = []
    steam_path = find_steam_path()

    if not steam_path:
        LOG.warning("Steam not found")
        return games

    steamapps = steam_path / "steamapps"

    # Also check library folders (external drives etc.)
    library_folders = [steamapps]

    # Parse libraryfolders.vdf for additional library paths
    libfolders_file = steamapps / "libraryfolders.vdf"
    if libfolders_file.exists():
        try:
            content = libfolders_file.read_text()
            # Find paths in format "path"		"/some/path"
            paths = re.findall(r'"path"\s+"([^"]+)"', content)
            for p in paths:
                lib_path = Path(p) / "steamapps"
                if lib_path.exists() and lib_path not in library_folders:
                    library_folders.append(lib_path)
        except Exception as e:
            LOG.error(f"Error reading library folders: {e}")

    # Scan all library folders for games
    for lib_folder in library_folders:
        for acf_file in lib_folder.glob("appmanifest_*.acf"):
            data = parse_acf_file(acf_file)

            if not data.get("appid") or not data.get("name"):
                continue

            # Skip non-games (tools, runtimes, etc.)
            name = data.get("name", "")
            if any(skip in name.lower() for skip in [
                "runtime", "proton", "redistributable", "sdk",
                "dedicated server", "steamworks"
            ]):
                continue

            state_flags = int(data.get("stateflags", "0"))
            game = SteamGame(
                appid=data.get("appid", ""),
                name=data.get("name", "Unknown"),
                install_dir=data.get("installdir", ""),
                size_on_disk=int(data.get("sizeondisk", 0)),
                last_played=int(data.get("lastplayed", 0)),
                is_downloading=state_flags == 1026,
                state_flags=state_flags,
                bytes_to_download=int(data.get("bytestodownload", 0)),
                bytes_downloaded=int(data.get("bytesdownloaded", 0)),
            )
            games.append(game)

    # Sort by name
    games.sort(key=lambda g: g.name.lower())
    return games


def find_game_by_name(query: str, games: Optional[List[SteamGame]] = None) -> Optional[SteamGame]:
    """Find a game by name using aliases + fuzzy matching."""
    if games is None:
        games = get_installed_games()

    if not games:
        return None

    query_lower = query.lower().strip()
    query_norm = re.sub(r'[^a-z0-9]', '', query_lower)

    # Step 0: Check aliases first — maps common abbreviations to appids
    alias = GAME_ALIASES.get(query_norm) or GAME_ALIASES.get(query_lower)
    if alias:
        target_appid, _ = alias
        for game in games:
            if game.appid == target_appid:
                return game
        # Alias matched but game not installed — don't fuzzy-match something wrong
        return None

    # Step 1: Exact name match
    for game in games:
        if game.name.lower() == query_lower:
            return game

    # Step 2: Contains match
    for game in games:
        if query_lower in game.name.lower():
            return game

    # Step 3: Normalized match (strip hyphens, spaces, special chars)
    for game in games:
        game_norm = re.sub(r'[^a-z0-9]', '', game.name.lower())
        if query_norm in game_norm or game_norm.startswith(query_norm):
            return game

    # Step 4: Fuzzy matching (case-insensitive)
    game_names_lower = [g.name.lower() for g in games]
    matches = difflib.get_close_matches(query_lower, game_names_lower, n=1, cutoff=0.4)

    if matches:
        for game in games:
            if game.name.lower() == matches[0]:
                return game

    return None


def resolve_alias(query: str) -> Optional[Tuple[str, str]]:
    """Resolve a game alias to (appid, canonical_name).

    Returns None if query is not a known alias.
    """
    query_norm = re.sub(r'[^a-z0-9]', '', query.lower().strip())
    return GAME_ALIASES.get(query_norm) or GAME_ALIASES.get(query.lower().strip())


def is_steam_running() -> bool:
    """Check if the Steam client is currently running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "ubuntu12_32/steam|bin_steam.sh"],
            capture_output=True, text=True, timeout=3
        )
        return result.returncode == 0
    except Exception:
        return False


def ensure_steam_running() -> bool:
    """Ensure Steam is running. Start it if not.

    Returns True if Steam is (or was started) running.
    """
    if is_steam_running():
        return True

    LOG.info("Steam not running, starting it...")
    try:
        cmd = _steam_cmd_prefix() + ["-silent"]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Wait for Steam to initialize
        for _ in range(15):
            time.sleep(1)
            if is_steam_running():
                LOG.info("Steam started successfully")
                return True
        LOG.warning("Steam did not start within 15s")
        return False
    except Exception as e:
        LOG.error(f"Error starting Steam: {e}")
        return False


def launch_game(game: SteamGame) -> Tuple[bool, str]:
    """Launch a Steam game.

    Returns (success, message) tuple with German messages.
    """
    # Check for pending update
    update_note = ""
    if game.needs_update:
        dl_mb, total_mb = game.update_progress_mb
        if total_mb > 0:
            update_note = f" (Update: {dl_mb}/{total_mb} MB)"
        else:
            update_note = " (update available)"

    try:
        cmd = _steam_cmd_prefix() + [f"steam://rungameid/{game.appid}"]

        LOG.info(f"Launching: {' '.join(cmd)}")
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        msg = f"Launching {game.name}...{update_note}"
        if update_note:
            msg += "\nSteam may download an update first."

        return True, msg

    except Exception as e:
        LOG.error(f"Error launching {game.name}: {e}")
        return False, f"Error launching {game.name}: {e}"


def launch_game_by_name(query: str) -> Tuple[bool, str]:
    """Find and launch a game by name. Handles aliases and uninstalled games."""
    games = get_installed_games()

    # Try to find installed game
    game = find_game_by_name(query, games) if games else None

    if game:
        return launch_game(game)

    # Game not installed — check if it's a known alias with an appid
    alias = resolve_alias(query)
    if alias:
        appid, canonical_name = alias
        if appid == "0":
            # Game not available on Steam
            return False, f"{canonical_name} is not available on Steam."
        # Offer to open Steam Store page
        return open_store_page(appid, canonical_name)

    # Not an alias either — suggest installed games
    if games:
        suggestions = [g.name for g in games[:5]]
        msg = f"Game '{query}' not found."
        msg += f"\nInstalled games: {', '.join(suggestions)}"
        msg += f"\nSay 'install {query}' to search the Steam Store."
        return False, msg

    return False, "No Steam games found. Is Steam installed?"


def open_store_page(appid: str, name: str = "") -> Tuple[bool, str]:
    """Open the Steam Store page for a game (to install/purchase)."""
    try:
        cmd = _steam_cmd_prefix() + [f"steam://store/{appid}"]
        LOG.info(f"Opening store page: {' '.join(cmd)}")
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        display_name = name or f"AppID {appid}"
        return True, f"Opening Steam Store for {display_name}..."

    except Exception as e:
        LOG.error(f"Error opening store page: {e}")
        return False, f"Error opening Steam Store: {e}"


def install_game(appid: str, name: str = "") -> Tuple[bool, str]:
    """Trigger Steam install dialog for a game."""
    try:
        cmd = _steam_cmd_prefix() + [f"steam://install/{appid}"]
        LOG.info(f"Triggering install: {' '.join(cmd)}")
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        display_name = name or f"AppID {appid}"
        return True, f"Steam install dialog opened for {display_name}."

    except Exception as e:
        LOG.error(f"Error triggering install: {e}")
        return False, f"Error installing: {e}"


def _game_search_names(game: SteamGame) -> List[str]:
    """Build a list of names/patterns to search for in process lists and window classes.

    Steam games can appear as:
    - steamapps/common/<install_dir>/...
    - steam_app_<appid> (WM_CLASS for Proton/Wine games)
    - <game_name_slug> (native Linux games, e.g. "dota2" for "Dota 2")
    - gameoverlayui <appid> (Steam overlay attached to the game)
    """
    names = []
    # install_dir from ACF (e.g. "dota 2 beta", "Counter-Strike Global Offensive")
    if game.install_dir:
        names.append(game.install_dir.lower())
    # appid patterns
    names.append(f"steam_app_{game.appid}")
    names.append(f"appid {game.appid}")
    names.append(f"rungameid/{game.appid}")
    # Slug: "Dota 2" → "dota2", "Counter-Strike 2" → "counterstrike2"
    slug = re.sub(r"[^a-z0-9]", "", game.name.lower())
    if slug and slug not in names:
        names.append(slug)
    # Also try name without trailing numbers for series (e.g. "dota")
    slug_no_num = slug.rstrip("0123456789")
    if slug_no_num and len(slug_no_num) >= 3 and slug_no_num not in names:
        names.append(slug_no_num)
    return names


def verify_game_launched(game: SteamGame, timeout: float = 45.0) -> Tuple[bool, str]:
    """Wait up to timeout seconds and check if the game actually started.

    Uses multiple detection strategies:
    1. Process cmdline search (install_dir, appid, game name slug)
    2. Window WM_CLASS search (steam_app_APPID, game name)
    3. Steam gameoverlayui attachment (proves Steam knows game is running)

    Returns (launched, status_message).
    """
    start_time = time.time()
    check_interval = 3.0
    search_names = _game_search_names(game)

    while (time.time() - start_time) < timeout:
        time.sleep(check_interval)

        # 1. Check process cmdlines
        try:
            result = subprocess.run(
                ["ps", "aux"], capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.split("\n"):
                lower = line.lower()
                # Skip Steam client itself, helpers, and this python process
                if "ubuntu12_32/steam" in lower or "bin_steam.sh" in lower:
                    continue
                if "python" in lower and "steam_integration" in lower:
                    continue
                for name in search_names:
                    if name in lower:
                        return True, f"{game.name} is running!"
        except Exception:
            pass

        # 2. Check window WM_CLASS and window titles
        try:
            result = subprocess.run(
                ["wmctrl", "-l"], capture_output=True, text=True, timeout=3
            )
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                # Check window title (last column in wmctrl -l)
                parts = line.split(None, 3)
                if len(parts) >= 4:
                    title = parts[3].lower()
                    for name in search_names:
                        if name in title:
                            return True, f"{game.name} is running!"
                # Check WM_CLASS
                win_id = parts[0] if parts else ""
                if not win_id:
                    continue
                try:
                    cls_result = subprocess.run(
                        ["xprop", "-id", win_id, "WM_CLASS"],
                        capture_output=True, text=True, timeout=2
                    )
                    cls_lower = cls_result.stdout.lower()
                    for name in search_names:
                        if name in cls_lower:
                            return True, f"{game.name} is running!"
                except Exception:
                    pass
        except Exception:
            pass

    # Timeout — game didn't appear
    if game.needs_update:
        dl_mb, total_mb = game.update_progress_mb
        return False, f"{game.name} needs an update ({total_mb} MB). Steam is downloading it."
    return False, f"{game.name} not detected. Steam may still be loading."


def close_game(game_name: Optional[str] = None) -> Tuple[bool, str]:
    """Close a running Steam game."""
    try:
        if game_name:
            # Try to find and kill specific game
            game = find_game_by_name(game_name)
            if game:
                # Kill processes in the game's install directory
                result = subprocess.run(
                    ["pkill", "-f", game.install_dir],
                    capture_output=True
                )
                return True, f"Closing {game.name}..."

        # Generic: close any running game via Steam
        cmd = _steam_cmd_prefix() + ["steam://close/gamepadui"]
        subprocess.run(cmd, capture_output=True)

        return True, "Closing game..."

    except Exception as e:
        LOG.error(f"Error closing game: {e}")
        return False, f"Error closing game: {e}"


def get_running_game() -> Optional[str]:
    """Try to detect which Steam game is currently running."""
    try:
        steam_path = find_steam_path()
        if not steam_path:
            return None

        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=5
        )

        for line in result.stdout.split("\n"):
            if "steamapps/common" in line.lower():
                # Extract game folder name
                match = re.search(r'steamapps/common/([^/]+)', line, re.I)
                if match:
                    folder = match.group(1)
                    # Skip runtimes
                    if any(s in folder.lower() for s in [
                        "steamlinuxruntime", "proton", "steamworks"
                    ]):
                        continue
                    return folder

        return None

    except Exception as e:
        LOG.error(f"Error detecting running game: {e}")
        return None


def list_games_formatted() -> str:
    """Get a formatted list of installed games."""
    games = get_installed_games()

    if not games:
        return "No Steam games found."

    lines = [f"Installed Steam games ({len(games)}):"]
    for i, game in enumerate(games, 1):
        status = ""
        if game.needs_update:
            _, total_mb = game.update_progress_mb
            status = f" [Update: {total_mb} MB]"
        elif game.is_downloading:
            status = " [Download...]"
        lines.append(f"  {i}. {game.name}{status}")

    return "\n".join(lines)


# CLI interface for testing
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("Usage: steam_integration.py [list|launch <game>|close|store <appid>|verify <game>]")
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "list":
        print(list_games_formatted())

    elif cmd == "launch" and len(sys.argv) > 2:
        game_name = " ".join(sys.argv[2:])
        success, msg = launch_game_by_name(game_name)
        print(msg)

    elif cmd == "close":
        game_name = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else None
        success, msg = close_game(game_name)
        print(msg)

    elif cmd == "store" and len(sys.argv) > 2:
        appid = sys.argv[2]
        success, msg = open_store_page(appid)
        print(msg)

    elif cmd == "alias" and len(sys.argv) > 2:
        query = " ".join(sys.argv[2:])
        result = resolve_alias(query)
        if result:
            appid, name = result
            print(f"Alias: {query} -> {name} (AppID: {appid})")
        else:
            print(f"No alias for '{query}'")

    else:
        print("Unknown command")
