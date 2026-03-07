#!/usr/bin/env python3
"""
F.R.A.N.K. AI Core System — Database Recovery Tool
════════════════════════════════════════════════════
Replaces live databases with reference copies from the repo.
Use when Frank's memory/state is corrupted or for fresh installs.
"""

import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Bootstrap: ensure 'rich' is available ────────────────────────────────────
try:
    import rich
except ImportError:
    if getattr(sys, '_MEIPASS', None):
        print("\033[31m[ERROR] rich library missing from PyInstaller bundle.\033[0m")
        sys.exit(1)
    print("\033[32m[*] Installing rich library...\033[0m")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "rich", "-q"])
    import rich

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich.prompt import Confirm
from rich import box

# ── Matrix green theme ───────────────────────────────────────────────────────
MATRIX_GREEN = "#00FF41"
MATRIX_DIM = "#008F11"
MATRIX_BRIGHT = "#33FF77"
MATRIX_CYAN = "#00FFCC"
MATRIX_RED = "#FF3333"
MATRIX_YELLOW = "#FFAA00"

console = Console(highlight=False)

# ── Paths ────────────────────────────────────────────────────────────────────
def _find_reference_db_dir() -> Path:
    """Find reference database directory. Searches multiple locations."""
    candidates = [
        # Running from repo source (updater/ -> repo root)
        Path(__file__).resolve().parent.parent / "database",
        # Standard install location
        Path.home() / "aicore" / "opt" / "aicore" / "database",
        # Env override
        Path(os.environ.get("AICORE_REPO", "")) / "database",
        # Binary placed next to database/ dir
        Path(sys.executable).resolve().parent / "database",
        # Binary in dist/ -> repo root
        Path(sys.executable).resolve().parent.parent / "database",
    ]
    for p in candidates:
        if p.is_dir() and any(p.glob("*.db")):
            return p
    # Fallback (will fail later with a clear error)
    return Path.home() / "aicore" / "opt" / "aicore" / "database"

REFERENCE_DB_DIR = _find_reference_db_dir()
LIVE_DB_DIR = Path(os.environ.get(
    "AICORE_DATA", str(Path.home() / ".local" / "share" / "frank")
)) / "db"

# ── All Frank services (ordered: background first, user-facing last) ─────────
FRANK_SERVICES = [
    "aicore-consciousness",
    "aicore-dream",
    "aicore-genesis",
    "aicore-rooms",
    "aicore-quantum-reflector",
    "aura-headless",
    "aura-analyzer",
    "aicore-nerd-physics",
    "aicore-invariants",
    "aicore-asrs",
    "aicore-gaming-mode",
    "aicore-ingestd",
    "aicore-toolboxd",
    "aicore-desktopd",
    "aicore-webd",
    "aicore-modeld",
    "aicore-core",
    "aicore-router",
    "frank-overlay",
]

# ── ASCII Art ────────────────────────────────────────────────────────────────
TITLE = """
[bold #00FF41]██████╗ [/][bold #008F11]███████╗[/][bold #00FF41] ██████╗[/][bold #008F11] ██████╗ [/][bold #00FF41]██╗   ██╗[/][bold #008F11]███████╗[/][bold #00FF41]██████╗ [/][bold #008F11]██╗   ██╗[/]
[bold #00FF41]██╔══██╗[/][bold #008F11]██╔════╝[/][bold #00FF41]██╔════╝[/][bold #008F11]██╔═══██╗[/][bold #00FF41]██║   ██║[/][bold #008F11]██╔════╝[/][bold #00FF41]██╔══██╗[/][bold #008F11]╚██╗ ██╔╝[/]
[bold #00FF41]██████╔╝[/][bold #008F11]█████╗  [/][bold #00FF41]██║     [/][bold #008F11]██║   ██║[/][bold #00FF41]██║   ██║[/][bold #008F11]█████╗  [/][bold #00FF41]██████╔╝[/][bold #008F11] ╚████╔╝ [/]
[bold #00FF41]██╔══██╗[/][bold #008F11]██╔══╝  [/][bold #00FF41]██║     [/][bold #008F11]██║   ██║[/][bold #00FF41]╚██╗ ██╔╝[/][bold #008F11]██╔══╝  [/][bold #00FF41]██╔══██╗[/][bold #008F11]  ╚██╔╝  [/]
[bold #00FF41]██║  ██║[/][bold #008F11]███████╗[/][bold #00FF41]╚██████╗[/][bold #008F11]╚██████╔╝[/][bold #00FF41] ╚████╔╝ [/][bold #008F11]███████╗[/][bold #00FF41]██║  ██║[/][bold #008F11]   ██║   [/]
[bold #00FF41]╚═╝  ╚═╝[/][bold #008F11]╚══════╝[/][bold #00FF41] ╚═════╝[/][bold #008F11] ╚═════╝ [/][bold #00FF41]  ╚═══╝  [/][bold #008F11]╚══════╝[/][bold #00FF41]╚═╝  ╚═╝[/][bold #008F11]   ╚═╝   [/]"""


def _run(cmd, timeout=30, cwd=None):
    """Run a command, return (ok, stdout, stderr)."""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd,
        )
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "timeout"
    except Exception as e:
        return False, "", str(e)


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def show_header():
    console.print(Panel(
        Align.center(TITLE),
        border_style=MATRIX_GREEN,
        box=box.DOUBLE,
        padding=(0, 2),
    ))
    console.print(
        f"  [{MATRIX_CYAN}]Database Recovery Tool[/]  "
        f"[{MATRIX_DIM}]— Replace live DBs with reference copies from repo[/]\n",
        justify="center",
    )


def show_reference_info():
    """Show what's available in the reference database directory."""
    if not REFERENCE_DB_DIR.exists():
        console.print(f"  [{MATRIX_RED}]ERROR: Reference DB dir not found: {REFERENCE_DB_DIR}[/]")
        return False

    db_files = sorted(REFERENCE_DB_DIR.glob("*.db"))
    extra_files = [
        f for f in REFERENCE_DB_DIR.iterdir()
        if f.is_file() and f.suffix not in (".db", ".db-shm", ".db-wal")
        and not f.name.startswith(".")
    ]

    if not db_files:
        console.print(f"  [{MATRIX_RED}]ERROR: No .db files found in {REFERENCE_DB_DIR}[/]")
        return False

    table = Table(
        title=f"[{MATRIX_BRIGHT}]Reference Databases ({len(db_files)} files)[/]",
        box=box.SIMPLE_HEAVY,
        border_style=MATRIX_DIM,
        show_lines=False,
    )
    table.add_column("Database", style=MATRIX_GREEN, min_width=30)
    table.add_column("Size", style=MATRIX_CYAN, justify="right")

    total_size = 0
    for f in db_files:
        sz = f.stat().st_size
        total_size += sz
        table.add_row(f.name, _fmt_size(sz))

    for f in extra_files:
        sz = f.stat().st_size
        total_size += sz
        table.add_row(f"  {f.name}", _fmt_size(sz))

    table.add_section()
    table.add_row(f"[bold]TOTAL[/]", f"[bold]{_fmt_size(total_size)}[/]")

    console.print(table)
    console.print()
    return True


def show_live_info():
    """Show current live database status."""
    if not LIVE_DB_DIR.exists():
        console.print(f"  [{MATRIX_YELLOW}]Live DB dir does not exist yet: {LIVE_DB_DIR}[/]")
        console.print(f"  [{MATRIX_DIM}]Will be created during recovery.[/]\n")
        return

    db_files = sorted(LIVE_DB_DIR.glob("*.db"))
    total = sum(f.stat().st_size for f in db_files)
    console.print(
        f"  [{MATRIX_CYAN}]Live DB directory:[/] [{MATRIX_GREEN}]{LIVE_DB_DIR}[/]\n"
        f"  [{MATRIX_CYAN}]Current state:[/] [{MATRIX_GREEN}]{len(db_files)} databases, {_fmt_size(total)}[/]\n"
    )


def stop_all_services():
    """Stop all Frank services."""
    console.print(f"\n  [{MATRIX_CYAN}][1/5] Stopping all Frank services...[/]")
    stopped = []
    for svc in FRANK_SERVICES:
        ok, state, _ = _run(["systemctl", "--user", "is-active", svc])
        if ok and state == "active":
            console.print(f"    [{MATRIX_DIM}]Stopping {svc}...[/]")
            ok2, _, err = _run(["systemctl", "--user", "stop", svc], timeout=30)
            if ok2:
                stopped.append(svc)
            else:
                console.print(f"    [{MATRIX_YELLOW}]Warning: {svc} stop failed: {err[:60]}[/]")
    console.print(f"    [{MATRIX_GREEN}]Stopped {len(stopped)} service(s)[/]")
    # Also kill any llama-server processes that hold DB locks
    _run(["pkill", "-f", "llama-server"], timeout=5)
    time.sleep(1)
    return stopped


def backup_live_dbs():
    """Create backup of current live DBs."""
    console.print(f"\n  [{MATRIX_CYAN}][2/5] Backing up current databases...[/]")
    if not LIVE_DB_DIR.exists():
        console.print(f"    [{MATRIX_DIM}]No live DB dir — nothing to back up[/]")
        return None

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = LIVE_DB_DIR / f"backup_{ts}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for f in LIVE_DB_DIR.iterdir():
        if f.is_file() and not f.name.startswith("backup_"):
            shutil.copy2(f, backup_dir / f.name)
            count += 1

    console.print(f"    [{MATRIX_GREEN}]Backed up {count} files to {backup_dir.name}/[/]")
    return backup_dir


def wipe_live_dbs():
    """Remove all DB files + WAL/SHM from live directory."""
    console.print(f"\n  [{MATRIX_CYAN}][3/5] Wiping current databases...[/]")
    if not LIVE_DB_DIR.exists():
        LIVE_DB_DIR.mkdir(parents=True, exist_ok=True)
        console.print(f"    [{MATRIX_DIM}]Created {LIVE_DB_DIR}[/]")
        return

    removed = 0
    for f in LIVE_DB_DIR.iterdir():
        if f.is_file() and not f.name.startswith("backup_"):
            f.unlink()
            removed += 1
    # Also remove backup dirs older than the one we just created
    # (keep only the latest backup)
    backups = sorted(LIVE_DB_DIR.glob("backup_*"))
    if len(backups) > 3:
        for old in backups[:-3]:
            shutil.rmtree(old, ignore_errors=True)
            console.print(f"    [{MATRIX_DIM}]Cleaned old backup: {old.name}[/]")

    console.print(f"    [{MATRIX_GREEN}]Removed {removed} files[/]")


def copy_reference_dbs():
    """Copy reference databases from repo to live directory."""
    console.print(f"\n  [{MATRIX_CYAN}][4/5] Restoring reference databases...[/]")
    LIVE_DB_DIR.mkdir(parents=True, exist_ok=True)

    copied = 0
    total_size = 0
    for f in sorted(REFERENCE_DB_DIR.iterdir()):
        if not f.is_file():
            continue
        # Skip WAL/SHM files, hidden files, and invariants subdir
        if f.suffix in (".db-shm", ".db-wal") or f.name.startswith("."):
            continue
        # Skip pre-fix backups
        if "pre_fix" in f.name:
            continue

        dst = LIVE_DB_DIR / f.name
        shutil.copy2(f, dst)
        sz = f.stat().st_size
        total_size += sz
        copied += 1
        if sz > 1024 * 1024:
            console.print(f"    [{MATRIX_DIM}]{f.name} ({_fmt_size(sz)})[/]")

    # Copy invariants subdir if exists
    inv_src = REFERENCE_DB_DIR / "invariants"
    if inv_src.is_dir():
        inv_dst = LIVE_DB_DIR / "invariants"
        if inv_dst.exists():
            shutil.rmtree(inv_dst)
        shutil.copytree(inv_src, inv_dst)
        console.print(f"    [{MATRIX_DIM}]invariants/ (subdir)[/]")

    console.print(f"    [{MATRIX_GREEN}]Restored {copied} files ({_fmt_size(total_size)})[/]")


def start_all_services(stopped_services):
    """Restart previously stopped services."""
    console.print(f"\n  [{MATRIX_CYAN}][5/5] Starting Frank services...[/]")
    if not stopped_services:
        console.print(f"    [{MATRIX_DIM}]No services were stopped[/]")
        return

    started = 0
    failed = []
    for svc in reversed(stopped_services):  # Start in reverse order
        console.print(f"    [{MATRIX_DIM}]Starting {svc}...[/]")
        ok, _, err = _run(["systemctl", "--user", "start", svc], timeout=15)
        if ok:
            started += 1
        else:
            failed.append(svc)
            console.print(f"    [{MATRIX_YELLOW}]Warning: {svc} start failed: {err[:60]}[/]")

    if failed:
        console.print(f"    [{MATRIX_YELLOW}]Started {started}/{len(stopped_services)} "
                       f"({len(failed)} failed)[/]")
    else:
        console.print(f"    [{MATRIX_GREEN}]Started {started} service(s)[/]")


def run_recovery():
    """Main recovery flow."""
    show_header()

    # Show what we have
    if not show_reference_info():
        return False
    show_live_info()

    # Confirm
    console.print(Panel(
        f"[{MATRIX_YELLOW}]This will:[/]\n"
        f"  [{MATRIX_GREEN}]1.[/] Stop ALL Frank services\n"
        f"  [{MATRIX_GREEN}]2.[/] Backup current databases\n"
        f"  [{MATRIX_GREEN}]3.[/] Wipe all current DB files\n"
        f"  [{MATRIX_GREEN}]4.[/] Copy reference databases from repo\n"
        f"  [{MATRIX_GREEN}]5.[/] Restart all services\n\n"
        f"  [{MATRIX_DIM}]Backup is saved in {LIVE_DB_DIR}/backup_YYYYMMDD_HHMMSS/[/]",
        title=f"[{MATRIX_BRIGHT}]Recovery Plan[/]",
        border_style=MATRIX_YELLOW,
        box=box.ROUNDED,
    ))

    if not Confirm.ask(
        f"  [{MATRIX_CYAN}]Proceed with database recovery?[/]",
        default=False,
    ):
        console.print(f"\n  [{MATRIX_DIM}]Recovery cancelled.[/]")
        return False

    # Execute
    t0 = time.time()
    stopped = stop_all_services()
    backup_live_dbs()
    wipe_live_dbs()
    copy_reference_dbs()
    start_all_services(stopped)

    elapsed = time.time() - t0
    console.print(Panel(
        f"[{MATRIX_GREEN}]Database recovery complete in {elapsed:.1f}s[/]\n\n"
        f"  [{MATRIX_CYAN}]Frank is starting with reference databases.[/]\n"
        f"  [{MATRIX_DIM}]Previous databases backed up in {LIVE_DB_DIR}/backup_*/[/]",
        title=f"[{MATRIX_BRIGHT}]Recovery Complete[/]",
        border_style=MATRIX_GREEN,
        box=box.DOUBLE,
    ))
    return True


def main():
    try:
        run_recovery()
    except KeyboardInterrupt:
        console.print(f"\n  [{MATRIX_DIM}]Aborted by user.[/]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n  [{MATRIX_RED}]FATAL: {e}[/]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
