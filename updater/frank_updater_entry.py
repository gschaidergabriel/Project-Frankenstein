#!/usr/bin/env python3
"""
F.R.A.N.K. Updater — Entry Point
══════════════════════════════════
Single binary entry point for the Frank update system.

Usage:
    ./frank-updater              Start tray icon (default)
    ./frank-updater --update     Run TUI updater directly
    ./frank-updater --check      Silent check (exit 0=available, 1=up-to-date)
    ./frank-updater --install    Install updater (binary + autostart + menu entry)
    ./frank-updater --uninstall  Remove updater
"""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

BIN_PATH = Path.home() / ".local" / "bin" / "frank-updater"
AUTOSTART_DIR = Path.home() / ".config" / "autostart"
APPS_DIR = Path.home() / ".local" / "share" / "applications"
AUTOSTART_FILE = AUTOSTART_DIR / "frank-updater-tray.desktop"
DESKTOP_FILE = APPS_DIR / "frank-updater.desktop"

DESKTOP_ENTRY = """\
[Desktop Entry]
Type=Application
Name=F.R.A.N.K. Updater
Comment=AI Core System Update Manager
Exec={bin_path} --update
Icon=system-software-update
Terminal=true
Categories=System;Utility;
Keywords=frank;update;ai;
"""

AUTOSTART_ENTRY = """\
[Desktop Entry]
Type=Application
Name=F.R.A.N.K. Updater Tray
Comment=AI Core System Update Tray Icon
Exec={bin_path}
Icon=system-software-update
Terminal=false
X-GNOME-Autostart-enabled=true
Hidden=false
"""

GREEN = "\033[32m"
CYAN = "\033[36m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _install():
    """Install updater: copy binary, create .desktop files, start tray."""
    print(f"{GREEN}{BOLD}F.R.A.N.K. Updater — Installation{RESET}")
    print()

    # Determine source binary
    if getattr(sys, '_MEIPASS', None):
        # PyInstaller binary — copy ourselves
        src = Path(sys.executable)
    else:
        # Running from source — create a wrapper script
        src = None
        script_dir = Path(__file__).resolve().parent
        wrapper_content = f"""#!/bin/bash
cd "{script_dir.parent}"
exec python3 -m updater.frank_updater_entry "$@"
"""

    # Copy/create binary
    BIN_PATH.parent.mkdir(parents=True, exist_ok=True)
    if src and src.exists():
        print(f"  {GREEN}[1/4]{RESET} Copying binary to {BIN_PATH}")
        shutil.copy2(str(src), str(BIN_PATH))
        BIN_PATH.chmod(BIN_PATH.stat().st_mode | stat.S_IEXEC)
    else:
        print(f"  {GREEN}[1/4]{RESET} Creating launcher at {BIN_PATH}")
        BIN_PATH.write_text(wrapper_content)
        BIN_PATH.chmod(BIN_PATH.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    # Create .desktop for app menu (Update Now → opens terminal TUI)
    APPS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  {GREEN}[2/4]{RESET} Creating menu entry: {DESKTOP_FILE}")
    DESKTOP_FILE.write_text(DESKTOP_ENTRY.format(bin_path=BIN_PATH))

    # Create autostart entry (tray icon at login)
    AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  {GREEN}[3/4]{RESET} Creating autostart: {AUTOSTART_FILE}")
    AUTOSTART_FILE.write_text(AUTOSTART_ENTRY.format(bin_path=BIN_PATH))

    # Start tray icon now
    print(f"  {GREEN}[4/4]{RESET} Starting tray icon...")
    if getattr(sys, '_MEIPASS', None):
        subprocess.Popen([str(BIN_PATH)], start_new_session=True)
    else:
        tray_script = Path(__file__).resolve().parent / "frank_updater_tray.py"
        subprocess.Popen(
            ["python3", str(tray_script)],
            start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    print()
    print(f"  {GREEN}{BOLD}Installation complete!{RESET}")
    print(f"  {CYAN}Tray icon:{RESET} Green [F] in system tray")
    print(f"  {CYAN}Auto-check:{RESET} Every 6 hours (toggle from tray menu)")
    print(f"  {CYAN}Manual update:{RESET} Click tray icon → 'Update Now'")
    print(f"  {CYAN}Uninstall:{RESET} {BIN_PATH} --uninstall")
    print()


def _uninstall():
    """Remove updater: delete binary, .desktop files."""
    print(f"{GREEN}{BOLD}F.R.A.N.K. Updater — Uninstall{RESET}")
    print()

    # Kill running tray
    try:
        subprocess.run(["pkill", "-f", "frank_updater_tray"], timeout=5)
    except Exception:
        pass

    for path, desc in [
        (AUTOSTART_FILE, "autostart entry"),
        (DESKTOP_FILE, "menu entry"),
        (BIN_PATH, "binary"),
    ]:
        if path.exists():
            path.unlink()
            print(f"  {GREEN}Removed:{RESET} {path}")
        else:
            print(f"  {DIM}Not found:{RESET} {path}")

    print()
    print(f"  {GREEN}Uninstall complete.{RESET}")
    print(f"  {DIM}Config preserved at: ~/.local/share/frank/updater/{RESET}")
    print()


def main():
    if len(sys.argv) < 2:
        # Default: start tray icon
        from updater.frank_updater_tray import main as tray_main
        tray_main()
        return

    arg = sys.argv[1]

    if arg == "--install":
        _install()
    elif arg == "--uninstall":
        _uninstall()
    elif arg == "--update":
        from updater.frank_updater import main as updater_main
        sys.argv = [sys.argv[0]] + sys.argv[2:]  # Strip --update from args
        updater_main()
    elif arg == "--check":
        from updater.frank_updater import check_for_updates
        result = check_for_updates()
        if result.get("error"):
            print(f"Error: {result['error']}")
            sys.exit(2)
        if result["available"]:
            print(f"Update available: {result['local']} → {result['remote']} ({result.get('commits', '?')} commits)")
            sys.exit(0)
        else:
            print(f"Up to date: {result.get('local', '?')}")
            sys.exit(1)
    elif arg in ("--help", "-h"):
        print(__doc__)
    else:
        print(f"Unknown option: {arg}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
