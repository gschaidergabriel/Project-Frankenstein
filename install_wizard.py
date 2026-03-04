#!/usr/bin/env python3
"""
F.R.A.N.K. AI Core System — Installation Wizard
═══════════════════════════════════════════════════
Terminal TUI installer with Matrix-green cyberpunk aesthetic.
Wraps install.sh steps with live progress and terminal output.
"""

import os
import sys
import time
import shutil
import subprocess
import threading
from pathlib import Path

# ── Bootstrap: ensure 'rich' is available ───────────────────────────────────
try:
    import rich
except ImportError:
    if getattr(sys, '_MEIPASS', None):
        print("\033[31m[ERROR] rich library missing from PyInstaller bundle.\033[0m")
        print("\033[31m        Rebuild with: pyinstaller install-wizard.spec\033[0m")
        sys.exit(1)
    print("\033[32m[*] Installing rich library...\033[0m")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "rich", "-q"])
    import rich

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.text import Text
from rich.live import Live
from rich.layout import Layout
from rich.align import Align
from rich import box
import random

# ── Matrix green theme ──────────────────────────────────────────────────────
MATRIX_GREEN = "#00FF41"
MATRIX_DIM = "#008F11"
MATRIX_BRIGHT = "#33FF77"
MATRIX_CYAN = "#00FFCC"
BG_BLACK = "on #000000"

console = Console(highlight=False)

# ── Paths (handle both normal and PyInstaller --onefile mode) ───────────────
def _get_base_dir() -> Path:
    """Return the base directory, handling PyInstaller bundle mode."""
    if getattr(sys, '_MEIPASS', None):
        # Running as PyInstaller onefile — bundled data is in temp dir
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent

_BASE_DIR = _get_base_dir()
SCRIPT_DIR = Path(__file__).resolve().parent if not getattr(sys, '_MEIPASS', None) else Path.cwd()
OPT_DIR = SCRIPT_DIR.parent if not getattr(sys, '_MEIPASS', None) else SCRIPT_DIR
AICORE_ROOT = OPT_DIR.parent if not getattr(sys, '_MEIPASS', None) else OPT_DIR
INSTALL_SH = _BASE_DIR / "install.sh"

# ── ASCII Art Logo ──────────────────────────────────────────────────────────
FRANK_TITLE = """
[bold #00FF41]███████╗[/][bold #008F11]██████╗ [/][bold #00FF41] █████╗ [/][bold #008F11]███╗   ██╗[/][bold #00FF41]██╗  ██╗[/]
[bold #00FF41]██╔════╝[/][bold #008F11]██╔══██╗[/][bold #00FF41]██╔══██╗[/][bold #008F11]████╗  ██║[/][bold #00FF41]██║ ██╔╝[/]
[bold #00FF41]█████╗  [/][bold #008F11]██████╔╝[/][bold #00FF41]███████║[/][bold #008F11]██╔██╗ ██║[/][bold #00FF41]█████╔╝ [/]
[bold #00FF41]██╔══╝  [/][bold #008F11]██╔══██╗[/][bold #00FF41]██╔══██║[/][bold #008F11]██║╚██╗██║[/][bold #00FF41]██╔═██╗ [/]
[bold #00FF41]██║     [/][bold #008F11]██║  ██║[/][bold #00FF41]██║  ██║[/][bold #008F11]██║ ╚████║[/][bold #00FF41]██║  ██╗[/]
[bold #00FF41]╚═╝     [/][bold #008F11]╚═╝  ╚═╝[/][bold #00FF41]╚═╝  ╚═╝[/][bold #008F11]╚═╝  ╚═══╝[/][bold #00FF41]╚═╝  ╚═╝[/]
"""

SUBTITLE = f"[bold {MATRIX_CYAN}]AI CORE SYSTEM[/]  [dim {MATRIX_DIM}]—  Installation Wizard  —[/]"

# ── Installation steps ──────────────────────────────────────────────────────
STEPS = [
    {"id": "sysreq",   "name": "System Requirements",   "desc": "Checking RAM, disk space, architecture"},
    {"id": "apt",      "name": "System Packages",       "desc": "Installing apt dependencies (python3, cmake, GTK, firejail...)"},
    {"id": "gpu",      "name": "GPU Detection",         "desc": "Detecting GPU backend (Vulkan / CUDA / CPU)"},
    {"id": "venv",     "name": "Python Venv (main)",    "desc": "Creating virtual environment, installing pip packages"},
    {"id": "ingestd",  "name": "Python Venv (ingestd)", "desc": "Setting up ingestd venv (faster-whisper, ctranslate2)"},
    {"id": "llama",    "name": "Build llama.cpp",       "desc": "Compiling LLM inference engine from source"},
    {"id": "whisper",  "name": "Build whisper.cpp",     "desc": "Compiling speech-to-text engine from source"},
    {"id": "dirs",     "name": "Data & Databases",       "desc": "Creating directory tree, seeding databases, copying config"},
    {"id": "ollama",   "name": "Ollama + Vision Models","desc": "Installing Ollama, pulling LLaVA and Moondream"},
    {"id": "models",   "name": "LLM Models (GGUF)",     "desc": "Downloading DeepSeek-R1 + Llama 3.1 + Qwen 2.5 3B (~13 GB)"},
    {"id": "voice",    "name": "Voice / TTS Setup",     "desc": "Piper (Thorsten DE) + Kokoro (am_fenrir EN) + espeak"},
    {"id": "systemd",  "name": "Systemd Services",      "desc": "Installing and enabling 40+ user services"},
    {"id": "desktop",  "name": "Desktop Integration",   "desc": "Desktop entries, dock icons, autostart"},
    {"id": "start",    "name": "Start Services",        "desc": "Starting all services and the Frank overlay"},
]


# ── Matrix rain effect ──────────────────────────────────────────────────────
# Two char sets: Unicode katakana (most terminals) and ASCII fallback
_RAIN_CHARS_UNICODE = "ﾊﾐﾋｰｳｼﾅﾓﾆｻﾜﾂｵﾘｱﾎﾃﾏｹﾒｴｶｷﾑﾕﾗｾﾈｽﾀﾇﾍ"
_RAIN_CHARS_ASCII = "012345789ZXCVBNM@#$%&*=+<>|~"

def _detect_unicode_support() -> bool:
    """Check if the terminal can render Unicode characters."""
    try:
        enc = sys.stdout.encoding or "ascii"
        return enc.lower() in ("utf-8", "utf8", "utf_8")
    except Exception:
        return False

_USE_UNICODE = _detect_unicode_support()
_RAIN_CHARS = (_RAIN_CHARS_UNICODE + _RAIN_CHARS_ASCII) if _USE_UNICODE else _RAIN_CHARS_ASCII

def matrix_rain_line(width: int) -> str:
    """Generate one line of Matrix rain characters."""
    width = min(width, 200)  # Cap for very wide terminals
    line = ""
    for _ in range(width):
        if random.random() < 0.08:
            c = random.choice(_RAIN_CHARS)
            if random.random() < 0.3:
                line += f"[bold {MATRIX_BRIGHT}]{c}[/]"
            else:
                line += f"[{MATRIX_DIM}]{c}[/]"
        else:
            line += " "
    return line


# ── System detection ────────────────────────────────────────────────────────
def _run_cmd(cmd: list, timeout: int = 5) -> str:
    """Run a command and return stdout, or empty string on failure."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _detect_gpu() -> tuple:
    """
    Detect GPU using multiple methods for maximum compatibility.
    Returns (gpu_name, gpu_backend).

    Detection order:
      1. nvidia-smi (NVIDIA CUDA)
      2. lspci (AMD/Intel/NVIDIA fallback)
      3. /sys/class/drm (kernel DRM subsystem)
      4. vulkaninfo (Vulkan runtime)
      5. glxinfo (OpenGL/Mesa)
    """
    # Method 1: nvidia-smi (most reliable for NVIDIA)
    out = _run_cmd(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
    if out:
        return out.split("\n")[0].strip(), "cuda"

    # Method 2: lspci (works on most Linux systems)
    out = _run_cmd(["lspci"])
    if out:
        for line in out.splitlines():
            low = line.lower()
            if "vga" in low or "display" in low or "3d controller" in low:
                # Extract the device name (everything after the last colon)
                parts = line.split(":")
                name = parts[-1].strip() if len(parts) >= 3 else line.strip()
                if any(k in low for k in ("nvidia", "geforce", "quadro", "tesla", "rtx")):
                    return name, "cuda"
                elif any(k in low for k in ("amd", "ati", "radeon", "navi", "phoenix", "rembrandt")):
                    return name, "vulkan"
                elif any(k in low for k in ("intel", "iris", "uhd", "arc ")):
                    return name, "vulkan"

    # Method 3: /sys/class/drm (kernel-level, no lspci needed)
    try:
        drm_path = Path("/sys/class/drm")
        if drm_path.exists():
            for card_dir in sorted(drm_path.glob("card[0-9]*")):
                dev_path = card_dir / "device"
                vendor_file = dev_path / "vendor"
                if vendor_file.exists():
                    vendor = vendor_file.read_text().strip()
                    # Read device name from uevent or product
                    uevent = (dev_path / "uevent").read_text() if (dev_path / "uevent").exists() else ""
                    if vendor == "0x10de":  # NVIDIA
                        return f"NVIDIA GPU ({card_dir.name})", "cuda"
                    elif vendor == "0x1002":  # AMD
                        return f"AMD GPU ({card_dir.name})", "vulkan"
                    elif vendor == "0x8086":  # Intel
                        return f"Intel GPU ({card_dir.name})", "vulkan"
    except Exception:
        pass

    # Method 4: vulkaninfo (if Vulkan runtime is installed)
    out = _run_cmd(["vulkaninfo", "--summary"], timeout=10)
    if out and "GPU" in out:
        for line in out.splitlines():
            if "deviceName" in line:
                name = line.split("=")[-1].strip() if "=" in line else line.strip()
                if name:
                    backend = "cuda" if "nvidia" in name.lower() else "vulkan"
                    return name, backend

    # Method 5: glxinfo (Mesa/OpenGL fallback)
    out = _run_cmd(["glxinfo"])
    if out:
        for line in out.splitlines():
            if "OpenGL renderer" in line:
                name = line.split(":")[-1].strip()
                if name and name.lower() not in ("llvmpipe", "softpipe", "swrast"):
                    low = name.lower()
                    if "nvidia" in low:
                        return name, "cuda"
                    elif any(k in low for k in ("amd", "radeon", "radv")):
                        return name, "vulkan"
                    elif "intel" in low:
                        return name, "vulkan"

    return "None (CPU-only)", "cpu"


def detect_system_info() -> dict:
    """Gather system information for display."""
    info = {}

    # RAM (works on any Linux)
    info["ram_mb"] = 0
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    info["ram_mb"] = int(line.split()[1]) // 1024
                    break
    except Exception:
        pass

    # Disk free space
    info["disk_free_gb"] = 0
    try:
        st = os.statvfs(str(AICORE_ROOT))
        info["disk_free_gb"] = (st.f_bavail * st.f_frsize) // (1024 ** 3)
    except Exception:
        try:
            st = os.statvfs(str(Path.home()))
            info["disk_free_gb"] = (st.f_bavail * st.f_frsize) // (1024 ** 3)
        except Exception:
            pass

    # CPU
    info["cpu_cores"] = os.cpu_count() or 1
    info["cpu_name"] = "Unknown"
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if "model name" in line:
                    info["cpu_name"] = line.split(":")[1].strip()
                    break
    except Exception:
        pass

    # GPU (comprehensive multi-method detection)
    info["gpu_name"], info["gpu_backend"] = _detect_gpu()

    # Architecture
    info["arch"] = os.uname().machine  # x86_64, aarch64, armv7l, etc.

    # OS (try multiple methods)
    info["os"] = "Linux"
    # Try /etc/os-release first (most universal)
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    info["os"] = line.split("=", 1)[1].strip().strip('"')
                    break
    except Exception:
        out = _run_cmd(["lsb_release", "-d", "-s"])
        if out:
            info["os"] = out

    info["kernel"] = os.uname().release

    return info


def build_sysinfo_table(info: dict) -> Table:
    """Build a styled system info table."""
    table = Table(
        box=box.SIMPLE_HEAVY,
        show_header=False,
        border_style=MATRIX_DIM,
        padding=(0, 2),
        expand=True,
    )
    table.add_column("Key", style=f"bold {MATRIX_CYAN}", min_width=12)
    table.add_column("Value", style=f"{MATRIX_GREEN}")

    backend_color = MATRIX_BRIGHT if info["gpu_backend"] != "cpu" else "#FF4444"
    ram_color = MATRIX_GREEN if info["ram_mb"] >= 16000 else ("#FFAA00" if info["ram_mb"] >= 8000 else "#FF4444")
    disk_color = MATRIX_GREEN if info["disk_free_gb"] >= 20 else ("#FFAA00" if info["disk_free_gb"] >= 10 else "#FF4444")

    table.add_row("OS", info["os"])
    table.add_row("Kernel", f"{info['kernel']} ({info.get('arch', 'unknown')})")
    table.add_row("CPU", f"{info.get('cpu_name', 'Unknown')} ({info['cpu_cores']} cores)")
    table.add_row("RAM", f"[{ram_color}]{info['ram_mb']} MB[/]")
    table.add_row("Disk Free", f"[{disk_color}]{info['disk_free_gb']} GB[/]")
    table.add_row("GPU", f"{info['gpu_name']}")
    table.add_row("Backend", f"[bold {backend_color}]{info['gpu_backend'].upper()}[/]")
    table.add_row("Install Path", str(SCRIPT_DIR))

    return table


# ── Step execution ──────────────────────────────────────────────────────────
def build_steps_table(step_status: dict, current_step: int) -> Table:
    """Build step progress table."""
    table = Table(
        box=box.ROUNDED,
        border_style=MATRIX_DIM,
        show_header=True,
        header_style=f"bold {MATRIX_CYAN}",
        expand=True,
        padding=(0, 1),
    )
    table.add_column("#", width=5, justify="center")
    table.add_column("Step", min_width=25)
    table.add_column("Status", width=12, justify="center")

    for i, step in enumerate(STEPS):
        status = step_status.get(step["id"], "pending")
        num = f"{i + 1}/{len(STEPS)}"

        if status == "done":
            icon = f"[bold {MATRIX_GREEN}]  OK  [/]"
            name_style = f"[{MATRIX_DIM}]{step['name']}[/]"
        elif status == "running":
            icon = f"[bold {MATRIX_BRIGHT}] >>>  [/]"
            name_style = f"[bold {MATRIX_GREEN}]{step['name']}[/]"
        elif status == "skipped":
            icon = f"[{MATRIX_DIM}] SKIP [/]"
            name_style = f"[{MATRIX_DIM}]{step['name']}[/]"
        elif status == "error":
            icon = "[bold #FF4444] FAIL [/]"
            name_style = f"[#FF4444]{step['name']}[/]"
        else:
            icon = f"[{MATRIX_DIM}]  --  [/]"
            name_style = f"[{MATRIX_DIM}]{step['name']}[/]"

        table.add_row(
            f"[{MATRIX_DIM}]{num}[/]",
            name_style,
            icon,
        )

    return table


def run_install_step(step_idx: int, args: list, output_lines: list, max_lines: int = 12) -> int:
    """Run a portion of install.sh and capture output. Returns exit code."""
    step = STEPS[step_idx]

    # We run the full install.sh but we could also run individual commands.
    # For now, run install.sh with special env vars to track progress.
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["TERM"] = "dumb"

    try:
        proc = subprocess.Popen(
            ["bash", str(INSTALL_SH)] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
            bufsize=1,
        )

        for line in proc.stdout:
            line = line.rstrip()
            if line:
                output_lines.append(line)
                # Keep only last N lines
                if len(output_lines) > max_lines:
                    output_lines.pop(0)

        proc.wait()
        return proc.returncode

    except Exception as e:
        output_lines.append(f"Error: {e}")
        return 1


def format_output_panel(lines: list, width: int = 70) -> Panel:
    """Format captured output as a terminal-like panel."""
    text = Text()
    for line in lines[-14:]:
        # Color code the output
        if line.startswith("[") and "]" in line[:8]:
            text.append(line + "\n", style=f"bold {MATRIX_GREEN}")
        elif "WARNING" in line or "Warning" in line:
            text.append(line + "\n", style="#FFAA00")
        elif "ERROR" in line or "Error" in line or "FAIL" in line:
            text.append(line + "\n", style="#FF4444")
        elif line.startswith("  "):
            text.append(line + "\n", style=MATRIX_DIM)
        elif "Done" in line or "OK" in line or "success" in line.lower():
            text.append(line + "\n", style=MATRIX_BRIGHT)
        else:
            text.append(line + "\n", style=MATRIX_GREEN)

    return Panel(
        text,
        title=f"[{MATRIX_CYAN}] Terminal Output [/]",
        border_style=MATRIX_DIM,
        padding=(0, 1),
    )


# ── Options selection ───────────────────────────────────────────────────────
def ask_options() -> list:
    """Interactive option selection."""
    console.print()
    console.print(f"  [{MATRIX_CYAN}]Installation Options[/]", highlight=False)
    console.print(f"  [{MATRIX_DIM}]{'─' * 50}[/]")
    console.print()

    options = {
        "models": True,
        "build": True,
        "cpu_only": False,
        "force": False,
    }

    # Models
    console.print(f"  [{MATRIX_GREEN}][1][/] Download LLM + Voice models (~15 GB)?")
    console.print(f"      [{MATRIX_DIM}]DeepSeek-R1 8B, Llama 3.1 8B, Qwen 2.5 3B, Piper Thorsten, Kokoro[/]")
    r = console.input(f"      [{MATRIX_BRIGHT}]> [Y/n]: [/]").strip().lower()
    options["models"] = r != "n"
    console.print()

    # Build from source
    console.print(f"  [{MATRIX_GREEN}][2][/] Build llama.cpp + whisper.cpp from source?")
    console.print(f"      [{MATRIX_DIM}]Required for LLM inference and speech-to-text[/]")
    r = console.input(f"      [{MATRIX_BRIGHT}]> [Y/n]: [/]").strip().lower()
    options["build"] = r != "n"
    console.print()

    # CPU only
    console.print(f"  [{MATRIX_GREEN}][3][/] Force CPU-only mode? (skip GPU detection)")
    console.print(f"      [{MATRIX_DIM}]Use if GPU drivers cause issues[/]")
    r = console.input(f"      [{MATRIX_BRIGHT}]> [y/N]: [/]").strip().lower()
    options["cpu_only"] = r == "y"
    console.print()

    # Force reinstall
    console.print(f"  [{MATRIX_GREEN}][4][/] Force overwrite existing service files? (reinstall/update)")
    console.print(f"      [{MATRIX_DIM}]Use when updating an existing installation[/]")
    r = console.input(f"      [{MATRIX_BRIGHT}]> [y/N]: [/]").strip().lower()
    options["force"] = r == "y"
    console.print()

    args = []
    if not options["models"]:
        args.append("--no-models")
    if not options["build"]:
        args.append("--no-build")
    if options["cpu_only"]:
        args.append("--cpu-only")
    if options["force"]:
        args.append("--force")

    return args


# ── Main wizard flow ────────────────────────────────────────────────────────
def show_welcome():
    """Display the welcome screen with logo and system info."""
    # Clear screen
    console.clear()
    os.system("")  # Enable ANSI on Windows (no-op on Linux)

    # Title
    console.print()
    console.print(Align.center(FRANK_TITLE), highlight=False)
    console.print(Align.center(SUBTITLE), highlight=False)
    console.print()

    # Separator
    width = shutil.get_terminal_size().columns
    console.print(f"  [{MATRIX_DIM}]{'━' * (width - 4)}[/]")
    console.print()


def show_sysinfo(info: dict):
    """Display system info panel."""
    table = build_sysinfo_table(info)
    console.print(Panel(
        table,
        title=f"[bold {MATRIX_CYAN}] System Detection [/]",
        border_style=MATRIX_GREEN,
        padding=(1, 2),
    ))
    console.print()


def run_installation(args: list):
    """Run the full installation with live progress display."""
    console.print()
    console.print(f"  [bold {MATRIX_GREEN}]Initiating installation sequence...[/]")
    console.print()
    time.sleep(1)

    output_lines = []
    step_status = {s["id"]: "pending" for s in STEPS}
    current_step_name = ""

    # Step-to-install.sh marker mapping
    STEP_MARKERS = {
        "[1/14]":  "sysreq",
        "[2/14]":  "apt",
        "[3/14]":  "gpu",
        "[4/14]":  "venv",
        "[5/14]":  "ingestd",
        "[6/14]":  "llama",
        "[7/14]":  "whisper",
        "[8/14]":  "dirs",
        "[9/14]":  "ollama",
        "[10/14]": "models",
        "[11/14]": "voice",
        "[12/14]": "systemd",
        "[13/14]": "desktop",
        "[14/14]": "start",
    }

    # Track which step we're on by parsing install.sh output
    active_step = None

    def update_step_from_line(line: str):
        nonlocal active_step
        for marker, step_id in STEP_MARKERS.items():
            if marker in line:
                # Mark previous step as done
                if active_step and step_status[active_step] == "running":
                    step_status[active_step] = "done"
                active_step = step_id
                step_status[step_id] = "running"
                return
        if "Skipping" in line and active_step:
            step_status[active_step] = "skipped"
        elif ("WARNING" in line or "FAIL" in line) and active_step:
            pass  # Don't mark as error for warnings

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["TERM"] = "dumb"
    env["DEBIAN_FRONTEND"] = "noninteractive"

    proc = subprocess.Popen(
        ["bash", str(INSTALL_SH)] + args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
        bufsize=1,
    )

    done_event = threading.Event()

    def read_output():
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                update_step_from_line(line)
                output_lines.append(line)
                if len(output_lines) > 200:
                    output_lines.pop(0)
        proc.wait()
        # Mark last active step
        if active_step and step_status[active_step] == "running":
            step_status[active_step] = "done" if proc.returncode == 0 else "error"
        done_event.set()

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()

    # Live display
    with Live(console=console, refresh_per_second=4, transient=False) as live:
        while not done_event.is_set():
            # Count progress
            done_count = sum(1 for s in step_status.values() if s in ("done", "skipped"))
            total = len(STEPS)
            pct = (done_count / total) * 100

            # Build display
            steps_table = build_steps_table(step_status, 0)
            output_panel = format_output_panel(output_lines)

            # Progress bar text
            bar_width = 40
            filled = int(bar_width * done_count / total)
            bar = f"[bold {MATRIX_GREEN}]{'█' * filled}[/][{MATRIX_DIM}]{'░' * (bar_width - filled)}[/]"
            progress_text = f"  {bar}  [{MATRIX_BRIGHT}]{pct:.0f}%[/]  [{MATRIX_DIM}]({done_count}/{total})[/]"

            # Current step description
            current_desc = ""
            for s in STEPS:
                if step_status[s["id"]] == "running":
                    current_desc = f"  [{MATRIX_CYAN}]> {s['desc']}[/]"
                    break

            # Compose layout
            display = Table.grid(expand=True)
            display.add_row(steps_table)
            display.add_row("")
            display.add_row(progress_text)
            display.add_row(current_desc)
            display.add_row("")
            display.add_row(output_panel)

            live.update(display)
            done_event.wait(timeout=0.25)

    reader.join(timeout=5)
    return proc.returncode


def show_completion(exit_code: int):
    """Show installation completion screen."""
    console.print()
    width = shutil.get_terminal_size().columns

    if exit_code == 0:
        console.print(f"  [{MATRIX_DIM}]{'━' * (width - 4)}[/]")
        console.print()
        console.print(Align.center(f"[bold {MATRIX_GREEN}]╔══════════════════════════════════════════╗[/]"))
        console.print(Align.center(f"[bold {MATRIX_GREEN}]║                                          ║[/]"))
        console.print(Align.center(f"[bold {MATRIX_GREEN}]║     INSTALLATION COMPLETE                ║[/]"))
        console.print(Align.center(f"[bold {MATRIX_GREEN}]║                                          ║[/]"))
        console.print(Align.center(f"[bold {MATRIX_GREEN}]║     F.R.A.N.K. is ready.                ║[/]"))
        console.print(Align.center(f"[bold {MATRIX_GREEN}]║                                          ║[/]"))
        console.print(Align.center(f"[bold {MATRIX_GREEN}]╚══════════════════════════════════════════╝[/]"))
        console.print()
        console.print(f"  [{MATRIX_CYAN}]All services have been started automatically.[/]")
        console.print()
        console.print(f"  [{MATRIX_CYAN}]Check service status:[/]")
        console.print(f"  [{MATRIX_GREEN}]  systemctl --user status aicore-core[/]")
        console.print(f"  [{MATRIX_GREEN}]  systemctl --user list-units 'aicore-*' --state=running[/]")
        console.print()
        console.print(f"  [{MATRIX_CYAN}]Restart overlay:[/]")
        console.print(f"  [{MATRIX_GREEN}]  {SCRIPT_DIR}/ui/frank_overlay_launcher.sh[/]")
        console.print()
        console.print(f"  [{MATRIX_CYAN}]View logs:[/]")
        console.print(f"  [{MATRIX_GREEN}]  journalctl --user -u aicore-core -f[/]")
        console.print()
    else:
        console.print(Align.center(f"[bold #FF4444]╔══════════════════════════════════════════╗[/]"))
        console.print(Align.center(f"[bold #FF4444]║     INSTALLATION FAILED (code {exit_code})         ║[/]"))
        console.print(Align.center(f"[bold #FF4444]╚══════════════════════════════════════════╝[/]"))
        console.print()
        console.print(f"  [{MATRIX_DIM}]Check the output above for errors.[/]")
        console.print(f"  [{MATRIX_DIM}]You can re-run: python3 {__file__}[/]")
        console.print()

    console.print()


# ── Repo setup (for standalone binary mode) ─────────────────────────────────
REPO_URL = "https://github.com/gschaidergabriel/Project-Frankenstein.git"
DEFAULT_INSTALL_DIR = Path.home() / "aicore"

def setup_repo_if_needed() -> Path:
    """
    When running as a standalone binary, the source code isn't present yet.
    Clone the repo and return the path to the aicore source directory.
    """
    global SCRIPT_DIR, OPT_DIR, AICORE_ROOT, INSTALL_SH

    # Running from source tree (not a PyInstaller binary)?
    # Check that the REAL source tree exists (not just the bundled install.sh)
    if not getattr(sys, '_MEIPASS', None) and INSTALL_SH.exists():
        return SCRIPT_DIR

    # In standalone binary mode, check if real source exists at default path
    default_src = DEFAULT_INSTALL_DIR / "opt" / "aicore"
    if (default_src / "install.sh").exists() and (default_src / "core").is_dir():
        SCRIPT_DIR = default_src
        OPT_DIR = SCRIPT_DIR.parent
        AICORE_ROOT = OPT_DIR.parent
        INSTALL_SH = SCRIPT_DIR / "install.sh"
        console.print(f"  [{MATRIX_GREEN}]Found existing installation at {SCRIPT_DIR}[/]")
        return SCRIPT_DIR

    console.print()
    console.print(f"  [{MATRIX_CYAN}]Standalone mode detected — source code not found locally.[/]")
    console.print(f"  [{MATRIX_GREEN}]The F.R.A.N.K. repository will be cloned from GitHub.[/]")
    console.print()

    # Ask for install directory
    default = str(DEFAULT_INSTALL_DIR)
    console.print(f"  [{MATRIX_GREEN}]Install directory?[/]")
    target = console.input(f"  [{MATRIX_BRIGHT}]> [{MATRIX_DIM}]{default}[/][{MATRIX_BRIGHT}]: [/]").strip()
    if not target:
        target = default

    target_path = Path(target)
    aicore_src = target_path / "opt" / "aicore"

    if aicore_src.exists() and (aicore_src / "install.sh").exists():
        console.print(f"  [{MATRIX_GREEN}]Existing installation found at {aicore_src}[/]")
    else:
        console.print()
        console.print(f"  [{MATRIX_GREEN}]Cloning repository...[/]")

        clone_target = target_path / "opt" / "aicore"

        # Remove empty/incomplete clone targets
        if clone_target.exists() and not (clone_target / "install.sh").exists():
            import shutil as _sh
            _sh.rmtree(clone_target, ignore_errors=True)

        clone_target.parent.mkdir(parents=True, exist_ok=True)

        proc = subprocess.run(
            ["git", "clone", REPO_URL, str(clone_target)],
            capture_output=True, text=True, timeout=600,
        )
        if proc.returncode != 0:
            console.print(f"  [bold #FF4444]Git clone failed:[/]")
            console.print(f"  [#FF4444]{proc.stderr}[/]")
            console.print()
            console.print(f"  [{MATRIX_DIM}]If this is a private repo, clone it manually first:[/]")
            console.print(f"  [{MATRIX_GREEN}]  git clone {REPO_URL} {clone_target}[/]")
            console.print(f"  [{MATRIX_DIM}]Then re-run this installer.[/]")
            sys.exit(1)

        # Find install.sh in the cloned tree
        for candidate in [
            clone_target / "install.sh",
            target_path / "opt" / "aicore" / "install.sh",
            target_path / "install.sh",
        ]:
            if candidate.exists():
                aicore_src = candidate.parent
                break
        else:
            console.print(f"  [bold #FF4444]Could not find install.sh in cloned repo.[/]")
            sys.exit(1)

        console.print(f"  [{MATRIX_GREEN}]Repository cloned to {aicore_src}[/]")

    # Update global paths
    SCRIPT_DIR = aicore_src
    OPT_DIR = SCRIPT_DIR.parent
    AICORE_ROOT = OPT_DIR.parent
    INSTALL_SH = SCRIPT_DIR / "install.sh"

    return SCRIPT_DIR


# ── Entry point ─────────────────────────────────────────────────────────────
def main():
    # Welcome screen
    show_welcome()

    # System detection
    console.print(f"  [{MATRIX_GREEN}]Scanning system...[/]")
    console.print()
    info = detect_system_info()
    show_sysinfo(info)

    # Ensure repo/source is available
    setup_repo_if_needed()

    if not INSTALL_SH.exists():
        console.print(f"[bold #FF4444]Error: install.sh not found at {INSTALL_SH}[/]")
        sys.exit(1)

    # Options
    args = ask_options()

    # Confirm
    console.print(f"  [{MATRIX_DIM}]{'━' * 50}[/]")
    console.print()
    args_str = " ".join(args) if args else "(full installation)"
    console.print(f"  [{MATRIX_CYAN}]Configuration:[/] [{MATRIX_GREEN}]{args_str}[/]")
    console.print(f"  [{MATRIX_CYAN}]Source:[/] [{MATRIX_GREEN}]{SCRIPT_DIR}[/]")
    console.print()
    r = console.input(f"  [bold {MATRIX_BRIGHT}]Start installation? [Y/n]: [/]").strip().lower()

    if r == "n":
        console.print(f"\n  [{MATRIX_DIM}]Installation cancelled.[/]\n")
        sys.exit(0)

    # Run installation
    console.clear()
    console.print()
    console.print(Align.center(f"[bold {MATRIX_GREEN}]F.R.A.N.K.[/]  [{MATRIX_CYAN}]AI CORE SYSTEM[/]  [{MATRIX_DIM}]— Installing —[/]"))
    console.print()

    exit_code = run_installation(args)

    # Completion
    show_completion(exit_code)


if __name__ == "__main__":
    main()
