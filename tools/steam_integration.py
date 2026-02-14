#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Steam Integration for Frank

Provides:
- List installed Steam games
- Launch games by name (fuzzy matching)
- Get game info
- Close running games

Note: Frank can do everything EXCEPT delete games.
"""

import os
import re
import subprocess
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import difflib

LOG = logging.getLogger("steam_integration")

# Possible Steam installation paths
STEAM_PATHS = [
    Path.home() / "snap/steam/common/.local/share/Steam",
    Path.home() / ".steam/steam",
    Path.home() / ".local/share/Steam",
    Path("/usr/share/steam"),
]


@dataclass
class SteamGame:
    """Represents an installed Steam game."""
    appid: str
    name: str
    install_dir: str
    size_on_disk: int = 0
    last_played: int = 0
    is_downloading: bool = False

    def __str__(self):
        return f"{self.name} (ID: {self.appid})"


def find_steam_path() -> Optional[Path]:
    """Find the Steam installation directory."""
    for path in STEAM_PATHS:
        steamapps = path / "steamapps"
        if steamapps.exists():
            return path
    return None


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

            game = SteamGame(
                appid=data.get("appid", ""),
                name=data.get("name", "Unknown"),
                install_dir=data.get("installdir", ""),
                size_on_disk=int(data.get("sizeondisk", 0)),
                last_played=int(data.get("lastplayed", 0)),
                is_downloading=data.get("stateflags", "") == "1026"
            )
            games.append(game)

    # Sort by name
    games.sort(key=lambda g: g.name.lower())
    return games


def find_game_by_name(query: str, games: Optional[List[SteamGame]] = None) -> Optional[SteamGame]:
    """Find a game by name using fuzzy matching."""
    if games is None:
        games = get_installed_games()

    if not games:
        return None

    query_lower = query.lower().strip()

    # First try exact match
    for game in games:
        if game.name.lower() == query_lower:
            return game

    # Then try contains
    for game in games:
        if query_lower in game.name.lower():
            return game

    # Normalized match (strip hyphens, spaces, special chars)
    query_norm = re.sub(r'[^a-z0-9]', '', query_lower)
    for game in games:
        game_norm = re.sub(r'[^a-z0-9]', '', game.name.lower())
        if query_norm in game_norm or game_norm.startswith(query_norm):
            return game

    # Fuzzy matching (case-insensitive)
    game_names_lower = [g.name.lower() for g in games]
    matches = difflib.get_close_matches(query_lower, game_names_lower, n=1, cutoff=0.4)

    if matches:
        for game in games:
            if game.name.lower() == matches[0]:
                return game

    return None


def launch_game(game: SteamGame) -> Tuple[bool, str]:
    """Launch a Steam game."""
    try:
        # Use steam:// protocol to launch game
        cmd = ["steam", f"steam://rungameid/{game.appid}"]

        # For snap-installed Steam
        if (Path.home() / "snap/steam").exists():
            cmd = ["snap", "run", "steam", f"steam://rungameid/{game.appid}"]

        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        return True, f"Starte {game.name}..."

    except Exception as e:
        LOG.error(f"Error launching {game.name}: {e}")
        return False, f"Fehler beim Starten von {game.name}: {e}"


def launch_game_by_name(query: str) -> Tuple[bool, str]:
    """Find and launch a game by name."""
    games = get_installed_games()

    if not games:
        return False, "Keine Steam-Spiele gefunden. Ist Steam installiert?"

    game = find_game_by_name(query, games)

    if not game:
        # Suggest similar games
        suggestions = []
        query_lower = query.lower()
        for g in games[:5]:  # Show up to 5 suggestions
            suggestions.append(g.name)

        msg = f"Spiel '{query}' nicht gefunden."
        if suggestions:
            msg += f" Installierte Spiele: {', '.join(suggestions)}"
        return False, msg

    return launch_game(game)


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
                return True, f"{game.name} wird geschlossen..."

        # Generic: close any running game via Steam
        # This sends a close signal to Steam for the running game
        subprocess.run(
            ["steam", "steam://close/gamepadui"],
            capture_output=True
        )

        return True, "Spiel wird geschlossen..."

    except Exception as e:
        LOG.error(f"Error closing game: {e}")
        return False, f"Fehler beim Schliessen: {e}"


def get_running_game() -> Optional[str]:
    """Try to detect which Steam game is currently running."""
    try:
        steam_path = find_steam_path()
        if not steam_path:
            return None

        # Check common folder for running games
        steamapps = steam_path / "steamapps" / "common"

        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=5
        )

        for line in result.stdout.split("\n"):
            if "steamapps/common" in line.lower():
                # Extract game folder name
                match = re.search(r'steamapps/common/([^/]+)', line, re.I)
                if match:
                    return match.group(1)

        return None

    except Exception as e:
        LOG.error(f"Error detecting running game: {e}")
        return None


def list_games_formatted() -> str:
    """Get a formatted list of installed games."""
    games = get_installed_games()

    if not games:
        return "Keine Steam-Spiele gefunden."

    lines = [f"Installierte Steam-Spiele ({len(games)}):"]
    for i, game in enumerate(games, 1):
        lines.append(f"  {i}. {game.name}")

    return "\n".join(lines)


# CLI interface for testing
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("Usage: steam_integration.py [list|launch <game>|close]")
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

    else:
        print("Unknown command")
