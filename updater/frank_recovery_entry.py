#!/usr/bin/env python3
"""
F.R.A.N.K. Recovery — Entry Point
═══════════════════════════════════
Single binary entry point for the Frank database recovery tool.

Usage:
    ./frank-recovery              Run recovery TUI
    ./frank-recovery --install    Install to ~/.local/bin + app menu
    ./frank-recovery --uninstall  Remove installation
"""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

BIN_PATH = Path.home() / ".local" / "bin" / "frank-recovery"
APPS_DIR = Path.home() / ".local" / "share" / "applications"
DESKTOP_FILE = APPS_DIR / "frank-recovery.desktop"

DESKTOP_ENTRY = """\
[Desktop Entry]
Type=Application
Name=F.R.A.N.K. Recovery
Comment=AI Core Database Recovery Tool
Exec={bin_path}
Icon=system-restart
Terminal=true
Categories=System;Utility;
Keywords=frank;recovery;database;
"""

GREEN = "\033[32m"
CYAN = "\033[36m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _install():
    """Install recovery tool: copy binary, create .desktop."""
    print(f"{GREEN}{BOLD}F.R.A.N.K. Recovery — Installation{RESET}")
    print()

    if getattr(sys, '_MEIPASS', None):
        src = Path(sys.executable)
    else:
        src = None
        script_dir = Path(__file__).resolve().parent
        wrapper_content = f"""#!/bin/bash
cd "{script_dir.parent}"
exec python3 -m updater.frank_recovery_entry "$@"
"""

    BIN_PATH.parent.mkdir(parents=True, exist_ok=True)
    if src and src.exists():
        print(f"  {GREEN}[1/2]{RESET} Copying binary to {BIN_PATH}")
        shutil.copy2(str(src), str(BIN_PATH))
        BIN_PATH.chmod(BIN_PATH.stat().st_mode | stat.S_IEXEC)
    else:
        print(f"  {GREEN}[1/2]{RESET} Creating launcher at {BIN_PATH}")
        BIN_PATH.write_text(wrapper_content)
        BIN_PATH.chmod(BIN_PATH.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    APPS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  {GREEN}[2/2]{RESET} Creating menu entry: {DESKTOP_FILE}")
    DESKTOP_FILE.write_text(DESKTOP_ENTRY.format(bin_path=BIN_PATH))

    print()
    print(f"  {GREEN}{BOLD}Installation complete!{RESET}")
    print(f"  {CYAN}Run:{RESET} frank-recovery")
    print(f"  {CYAN}Menu:{RESET} Search 'F.R.A.N.K. Recovery' in app launcher")
    print(f"  {CYAN}Uninstall:{RESET} frank-recovery --uninstall")
    print()


def _uninstall():
    """Remove recovery tool."""
    print(f"{GREEN}{BOLD}F.R.A.N.K. Recovery — Uninstall{RESET}")
    print()

    for path, desc in [
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
    print()


def main():
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--install":
            _install()
            return
        elif arg == "--uninstall":
            _uninstall()
            return
        elif arg in ("--help", "-h"):
            print(__doc__)
            return
        elif not arg.startswith("-"):
            pass  # ignore unknown positional args
        else:
            print(f"Unknown option: {arg}")
            print(__doc__)
            sys.exit(1)

    from updater.frank_recovery import main as recovery_main
    recovery_main()


if __name__ == "__main__":
    main()
