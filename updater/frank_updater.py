#!/usr/bin/env python3
"""
F.R.A.N.K. AI Core System — Update System
═══════════════════════════════════════════
Terminal TUI updater with Matrix-green cyberpunk aesthetic.
Smart diff-based service restart, rollback on failure.
"""

import json
import os
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

import random
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich import box

# ── Matrix green theme (same as install_wizard.py) ───────────────────────────
MATRIX_GREEN = "#00FF41"
MATRIX_DIM = "#008F11"
MATRIX_BRIGHT = "#33FF77"
MATRIX_CYAN = "#00FFCC"

console = Console(highlight=False)

# ── Paths ────────────────────────────────────────────────────────────────────
DEFAULT_REPO = Path.home() / "aicore" / "opt" / "aicore"
STATE_DIR = Path.home() / ".local" / "share" / "frank" / "updater"
OPT_DIR = DEFAULT_REPO.parent
AICORE_ROOT = OPT_DIR.parent
DATA_DIR = Path(os.environ.get("AICORE_DATA", str(Path.home() / ".local" / "share" / "frank")))
MODELS_DIR = Path(os.environ.get("AICORE_MODELS_DIR", str(AICORE_ROOT / "var" / "lib" / "aicore" / "models")))
VOICES_DIR = DATA_DIR / "voices"
KOKORO_DIR = DATA_DIR / "kokoro"
LLAMA_DIR = OPT_DIR / "llama.cpp"
WHISPER_DIR = OPT_DIR / "whisper.cpp"

# ── ASCII Art Logo ───────────────────────────────────────────────────────────
FRANK_TITLE = """
[bold #00FF41]███████╗[/][bold #008F11]██████╗ [/][bold #00FF41] █████╗ [/][bold #008F11]███╗   ██╗[/][bold #00FF41]██╗  ██╗[/]
[bold #00FF41]██╔════╝[/][bold #008F11]██╔══██╗[/][bold #00FF41]██╔══██╗[/][bold #008F11]████╗  ██║[/][bold #00FF41]██║ ██╔╝[/]
[bold #00FF41]█████╗  [/][bold #008F11]██████╔╝[/][bold #00FF41]███████║[/][bold #008F11]██╔██╗ ██║[/][bold #00FF41]█████╔╝ [/]
[bold #00FF41]██╔══╝  [/][bold #008F11]██╔══██╗[/][bold #00FF41]██╔══██║[/][bold #008F11]██║╚██╗██║[/][bold #00FF41]██╔═██╗ [/]
[bold #00FF41]██║     [/][bold #008F11]██║  ██║[/][bold #00FF41]██║  ██║[/][bold #008F11]██║ ╚████║[/][bold #00FF41]██║  ██╗[/]
[bold #00FF41]╚═╝     [/][bold #008F11]╚═╝  ╚═╝[/][bold #00FF41]╚═╝  ╚═╝[/][bold #008F11]╚═╝  ╚═══╝[/][bold #00FF41]╚═╝  ╚═╝[/]
"""

SUBTITLE = f"[bold {MATRIX_CYAN}]AI CORE SYSTEM[/]  [dim {MATRIX_DIM}]— Update System —[/]"

# ── Matrix rain effect ───────────────────────────────────────────────────────
_RAIN_CHARS_UNICODE = "ﾊﾐﾋｰｳｼﾅﾓﾆｻﾜﾂｵﾘｱﾎﾃﾏｹﾒｴｶｷﾑﾕﾗｾﾈｽﾀﾇﾍ"
_RAIN_CHARS_ASCII = "012345789ZXCVBNM@#$%&*=+<>|~"

def _detect_unicode() -> bool:
    try:
        enc = sys.stdout.encoding or "ascii"
        return enc.lower() in ("utf-8", "utf8", "utf_8")
    except Exception:
        return False

_RAIN_CHARS = (_RAIN_CHARS_UNICODE + _RAIN_CHARS_ASCII) if _detect_unicode() else _RAIN_CHARS_ASCII

def matrix_rain_line(width: int) -> str:
    width = min(width, 200)
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

def matrix_rain(lines: int = 3):
    import shutil
    width = shutil.get_terminal_size().columns
    for _ in range(lines):
        console.print(matrix_rain_line(width), highlight=False)
    time.sleep(0.15)

# ── Service mapping: changed files → affected systemd services ───────────────
SERVICE_MAP = {
    "core/":                  ["aicore-core"],
    "router/":                ["aicore-router"],
    "ui/overlay/":            ["frank-overlay"],
    "ui/chat_overlay.py":     ["frank-overlay"],
    "ui/webui/":              ["aicore-webui"],
    "services/consciousness": ["aicore-consciousness"],
    "services/dream_daemon":  ["aicore-dream"],
    "services/genesis/":      ["aicore-genesis"],
    "services/room_":          ["aicore-rooms"],
    "services/quantum_":      ["aicore-quantum-reflector"],
    "services/aura_headless": ["aura-headless"],
    "services/aura_pattern":  ["aura-analyzer"],
    "services/nerd_physics/": ["aicore-nerd-physics"],
    "services/neural_immune/": ["aicore-invariants"],
    "services/asrs/":         ["aicore-asrs"],
    "services/thalamus":      ["aicore-consciousness"],
    "services/subconscious":  ["aicore-consciousness"],
    "services/nucleus_":      ["aicore-consciousness"],
    "services/experiment_":   ["aicore-consciousness"],
    "services/hypothesis_":   ["aicore-consciousness"],
    "services/spatial_":      ["aicore-consciousness"],
    "tools/":                 ["aicore-toolboxd"],
    "ext/":                   ["aicore-desktopd"],
    "personality/":           [],
    "config/":                [],
    "updater/":               [],
}

# Services with /health endpoints for post-update verification
HEALTH_CHECKS = {
    "aicore-core":              ("localhost", 8099),
    "aicore-router":            ("localhost", 8100),
    "aicore-quantum-reflector": ("localhost", 8097),
    "aura-headless":            ("localhost", 8098),
}


# ── Model & Binary Registry ───────────────────────────────────────────────────
# Each entry: (id, name, filename, directory, url, min_bytes, category,
#              test_port, service_name, ollama_tag)
# category: gguf | whisper | voice | ollama

MODEL_REGISTRY = [
    # GGUF LLM models
    ("deepseek_r1",
     "DeepSeek-R1 8B (Q6_K) — RLM",
     "DeepSeek-R1-Distill-Llama-8B-Abliterated.i1-Q6_K.gguf",
     MODELS_DIR,
     "https://huggingface.co/mradermacher/DeepSeek-R1-Distill-Llama-8B-abliterated-i1-GGUF/resolve/main/DeepSeek-R1-Distill-Llama-8B-Abliterated.i1-Q6_K.gguf",
     6_000_000_000, "gguf", 8101, "aicore-llama3-gpu", None),

    ("llama3_chat",
     "Llama 3.1 8B (Q4_K_M) — Chat (router-managed)",
     "Meta-Llama-3.1-8B-Instruct-abliterated-Q4_K_M.gguf",
     MODELS_DIR,
     "https://huggingface.co/mlabonne/Meta-Llama-3.1-8B-Instruct-abliterated-GGUF/resolve/main/meta-llama-3.1-8b-instruct-abliterated.Q4_K_M.gguf",
     4_500_000_000, "gguf", None, None, None),

    ("qwen_micro",
     "Qwen 2.5 3B (Q4_K_M) — Micro LLM",
     "Qwen2.5-3B-Instruct-abliterated.Q4_K_M.gguf",
     MODELS_DIR,
     "https://huggingface.co/bartowski/Qwen2.5-3B-Instruct-GGUF/resolve/main/Qwen2.5-3B-Instruct-Q4_K_M.gguf",
     1_800_000_000, "gguf", 8105, "aicore-micro-llm", None),

    # Whisper
    ("whisper_medium",
     "Whisper Medium — STT",
     "ggml-medium.bin",
     WHISPER_DIR / "models",
     "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin",
     1_400_000_000, "whisper", 8103, "aicore-whisper-gpu", None),

    # Voice / TTS
    ("piper_thorsten",
     "Piper Thorsten (DE) — TTS",
     "de_DE-thorsten-high.onnx",
     VOICES_DIR,
     "https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/high/de_DE-thorsten-high.onnx?download=true",
     100_000_000, "voice", None, None, None),

    ("piper_thorsten_cfg",
     "Piper Thorsten Config",
     "de_DE-thorsten-high.onnx.json",
     VOICES_DIR,
     "https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/high/de_DE-thorsten-high.onnx.json?download=true",
     1_000, "voice", None, None, None),

    ("kokoro_model",
     "Kokoro TTS (EN)",
     "kokoro-v1.0.onnx",
     KOKORO_DIR,
     "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
     200_000_000, "voice", None, None, None),

    ("kokoro_voices",
     "Kokoro Voice Embeddings",
     "voices-v1.0.bin",
     KOKORO_DIR,
     "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
     20_000_000, "voice", None, None, None),

    # Ollama vision models
    ("ollama_llava",
     "LLaVA 7B (Ollama) — Vision",
     "", Path("/dev/null"), "", 0, "ollama", None, None, "llava:7b"),

    ("ollama_moondream",
     "Moondream (Ollama) — Vision",
     "", Path("/dev/null"), "", 0, "ollama", None, None, "moondream"),
]

BINARY_CHECKS = [
    ("llama_server",  "llama-server",  LLAMA_DIR / "build" / "bin" / "llama-server"),
    ("whisper_server", "whisper-server", WHISPER_DIR / "build" / "bin" / "whisper-server"),
    ("piper",         "piper",         Path.home() / ".local" / "bin" / "piper"),
    ("ollama",        "ollama",        Path("/usr/local/bin/ollama")),
]


# ── Model check / repair helpers ─────────────────────────────────────────────

def _fmt_size(n: int) -> str:
    if n >= 1_000_000_000: return f"{n / 1_000_000_000:.1f} GB"
    if n >= 1_000_000: return f"{n / 1_000_000:.0f} MB"
    if n >= 1_000: return f"{n / 1_000:.0f} KB"
    return f"{n} B"


def _check_model(entry: tuple) -> dict:
    """Check a single model entry. Returns status dict."""
    mid, name, filename, directory, url, min_bytes, category, port, svc, ollama_tag = entry
    result = {"id": mid, "name": name, "category": category, "status": "ok",
              "file_ok": False, "file_size": 0, "health_ok": False,
              "service_running": False, "url": url, "entry": entry}

    if category == "ollama":
        ok2, out, _ = _run(["ollama", "list"], timeout=10)
        tag_base = (ollama_tag or "").split(":")[0]
        result["file_ok"] = ok2 and any(tag_base in line for line in out.splitlines())
        result["status"] = "ok" if result["file_ok"] else "missing"
        return result

    fpath = directory / filename
    if fpath.exists():
        result["file_size"] = fpath.stat().st_size
        result["file_ok"] = result["file_size"] >= min_bytes
    else:
        result["file_ok"] = False

    # Service status
    if svc:
        ok2, state, _ = _run(["systemctl", "--user", "is-active", f"{svc}.service"], timeout=5)
        result["service_running"] = ok2 and state == "active"

    # Health endpoint
    if port:
        try:
            import urllib.request
            req = urllib.request.Request(f"http://127.0.0.1:{port}/health", method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                result["health_ok"] = resp.status == 200
        except Exception:
            result["health_ok"] = False

    # Determine status
    if not fpath.exists():
        result["status"] = "missing"
    elif not result["file_ok"]:
        result["status"] = "corrupt"
    elif port and not result["health_ok"]:
        result["status"] = "service_down"
    else:
        result["status"] = "ok"

    return result


def _check_binary(entry: tuple) -> dict:
    bid, name, path = entry
    exists = path.exists() and os.access(path, os.X_OK)
    if not exists:
        ok2, _, _ = _run(["which", path.name], timeout=5)
        exists = ok2
    return {"id": bid, "name": name, "path": str(path), "status": "ok" if exists else "missing"}


def _download_model(entry: tuple) -> bool:
    """Download a model file with wget. Returns True on success."""
    mid, name, filename, directory, url, min_bytes, category, *_ = entry
    fpath = directory / filename
    tmp = fpath.with_suffix(fpath.suffix + ".tmp")
    directory.mkdir(parents=True, exist_ok=True)

    console.print(f"      [{MATRIX_DIM}]Downloading {name}...[/]", highlight=False)
    try:
        r = subprocess.run(
            ["wget", "-q", "--show-progress", "--tries=3", "--timeout=120",
             "-O", str(tmp), url],
            timeout=3600,
        )
        if r.returncode != 0:
            tmp.unlink(missing_ok=True)
            return False
        if tmp.stat().st_size < min_bytes:
            console.print(f"      [#FF4444]File too small ({_fmt_size(tmp.stat().st_size)} < {_fmt_size(min_bytes)})[/]", highlight=False)
            tmp.unlink(missing_ok=True)
            return False
        fpath.unlink(missing_ok=True)
        tmp.rename(fpath)
        return True
    except Exception as e:
        console.print(f"      [#FF4444]Download error: {e}[/]", highlight=False)
        tmp.unlink(missing_ok=True)
        return False


def _pull_ollama(tag: str) -> bool:
    """Pull an Ollama model. Returns True on success."""
    # Ensure Ollama is running
    try:
        import urllib.request
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3)
    except Exception:
        console.print(f"      [{MATRIX_DIM}]Starting Ollama...[/]", highlight=False)
        subprocess.run(["sudo", "systemctl", "start", "ollama"], timeout=15,
                       capture_output=True)
        time.sleep(3)

    console.print(f"      [{MATRIX_DIM}]Pulling {tag}...[/]", highlight=False)
    try:
        r = subprocess.run(["ollama", "pull", tag], timeout=3600)
        return r.returncode == 0
    except Exception:
        return False


def _test_inference(port: int) -> bool:
    """Send a tiny completion to verify LLM actually works."""
    try:
        import urllib.request
        payload = json.dumps({
            "model": "test",
            "messages": [{"role": "user", "content": "Say OK"}],
            "max_tokens": 5, "temperature": 0,
        }).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return len(content) > 0
    except Exception:
        return False


def _run(cmd: list, timeout: int = 30, cwd: str = None) -> tuple:
    """Run a command, return (success, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)


def _find_repo() -> Path:
    """Find the aicore git repository."""
    # Check default location
    if (DEFAULT_REPO / ".git").exists():
        return DEFAULT_REPO
    # Check if we're inside the repo
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if (parent / ".git").exists() and (parent / "core").is_dir():
            return parent
    return DEFAULT_REPO


def _step_icon(status: str) -> str:
    if status == "done":
        return f"[bold {MATRIX_GREEN}]  ✓  [/]"
    elif status == "running":
        return f"[bold {MATRIX_BRIGHT}] >>> [/]"
    elif status == "skipped":
        return f"[{MATRIX_DIM}] SKIP[/]"
    elif status == "error":
        return "[bold #FF4444] FAIL[/]"
    return f"[{MATRIX_DIM}]  --  [/]"


# ── Update steps ─────────────────────────────────────────────────────────────

class FrankUpdater:
    """10-step update process with live progress and rollback."""

    STEPS = [
        ("preflight",   "Pre-flight Check",    "Verifying git repo, venv, lock file"),
        ("fetch",       "Fetch Remote",        "Fetching latest changes from origin"),
        ("changelog",   "Changelog",           "Comparing local vs remote"),
        ("backup",      "Backup State",        "Saving current SHA for rollback"),
        ("stop",        "Stop Services",       "Stopping affected services"),
        ("pull",        "Pull Changes",        "Applying update (fast-forward)"),
        ("pip_sync",    "Pip Sync",            "Updating Python dependencies"),
        ("service_files", "Service Files",     "Reloading systemd if needed"),
        ("start",       "Start Services",      "Restarting affected services"),
        ("health",      "Health Check",        "Verifying services are running"),
        ("overlay_env", "Overlay Display",     "Ensuring overlay has display access"),
        ("models",      "Model Verification",  "Checking LLM models are loaded and responding"),
    ]

    def __init__(self, repo_path: Path = None, auto_confirm: bool = False):
        self.repo = repo_path or _find_repo()
        self.auto_confirm = auto_confirm
        self.venv = self.repo / "venv"
        self.step_status = {s[0]: "pending" for s in self.STEPS}
        self.local_sha = ""
        self.remote_sha = ""
        self.changed_files = []
        self.affected_services = set()
        self.stopped_services = []
        self.backup_sha = ""
        self.errors = []

    def _print_step(self, step_id: str, status: str, detail: str = ""):
        self.step_status[step_id] = status
        idx = next(i for i, s in enumerate(self.STEPS) if s[0] == step_id)
        name = self.STEPS[idx][1]
        num = f"{idx + 1}/{len(self.STEPS)}"
        icon = _step_icon(status)
        line = f"  [{MATRIX_DIM}]{num}[/]  {icon}  "
        if status == "running":
            line += f"[bold {MATRIX_GREEN}]{name}[/]"
        elif status == "done":
            line += f"[{MATRIX_DIM}]{name}[/]"
        elif status == "error":
            line += f"[#FF4444]{name}[/]"
        else:
            line += f"[{MATRIX_DIM}]{name}[/]"
        if detail:
            line += f"  [{MATRIX_DIM}]{detail}[/]"
        console.print(line, highlight=False)

    def _fail(self, step_id: str, msg: str):
        self._print_step(step_id, "error", msg)
        self.errors.append(f"{step_id}: {msg}")

    # ── Step 1: Pre-flight ────────────────────────────────────────────────
    def step_preflight(self) -> bool:
        sid = "preflight"
        self._print_step(sid, "running")

        if not self.repo.exists():
            self._fail(sid, f"Repo not found: {self.repo}")
            return False

        if not (self.repo / ".git").exists():
            self._fail(sid, "Not a git repository")
            return False

        # Check for lock file (another update in progress)
        lock = STATE_DIR / "update.lock"
        if lock.exists():
            try:
                age = time.time() - lock.stat().st_mtime
                if age < 600:  # 10 minutes
                    self._fail(sid, "Another update in progress (lock file exists)")
                    return False
            except Exception:
                pass
            lock.unlink(missing_ok=True)

        # Create lock
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        lock.write_text(str(os.getpid()))

        # Get current SHA
        ok, out, _ = _run(["git", "rev-parse", "HEAD"], cwd=str(self.repo))
        if not ok:
            self._fail(sid, "Cannot read HEAD")
            return False
        self.local_sha = out[:8]

        self._print_step(sid, "done", f"HEAD={self.local_sha}")
        return True

    # ── Step 2: Fetch ─────────────────────────────────────────────────────
    def step_fetch(self) -> bool:
        sid = "fetch"
        self._print_step(sid, "running")

        ok, _, err = _run(["git", "fetch", "origin", "main"], timeout=60, cwd=str(self.repo))
        if not ok:
            self._fail(sid, f"git fetch failed: {err[:80]}")
            return False

        ok, out, _ = _run(["git", "rev-parse", "origin/main"], cwd=str(self.repo))
        if not ok:
            self._fail(sid, "Cannot read origin/main")
            return False
        self.remote_sha = out[:8]

        if self.local_sha == self.remote_sha:
            self._print_step(sid, "done", "Already up to date!")
            return False  # Not an error, just nothing to do

        self._print_step(sid, "done", f"origin/main={self.remote_sha}")
        return True

    # ── Step 3: Changelog ─────────────────────────────────────────────────
    def step_changelog(self) -> bool:
        sid = "changelog"
        self._print_step(sid, "running")

        # Get commit log
        ok, log_out, _ = _run(
            ["git", "log", "HEAD..origin/main", "--oneline", "--no-decorate"],
            cwd=str(self.repo)
        )
        if not ok or not log_out:
            self._fail(sid, "Cannot read changelog")
            return False

        commits = log_out.strip().splitlines()

        # Get changed files
        ok, diff_out, _ = _run(
            ["git", "diff", "--name-only", "HEAD..origin/main"],
            cwd=str(self.repo)
        )
        if ok and diff_out:
            self.changed_files = diff_out.strip().splitlines()

        # Determine affected services
        for f in self.changed_files:
            for prefix, services in SERVICE_MAP.items():
                if f.startswith(prefix):
                    self.affected_services.update(services)
                    break

        # Display changelog
        console.print()
        table = Table(
            box=box.ROUNDED,
            border_style=MATRIX_DIM,
            title=f"[bold {MATRIX_CYAN}] Changelog ({len(commits)} commits) [/]",
            expand=True,
            padding=(0, 1),
        )
        table.add_column("SHA", style=f"bold {MATRIX_GREEN}", width=8)
        table.add_column("Message", style=MATRIX_GREEN)

        for line in commits[:20]:  # Show max 20
            parts = line.split(" ", 1)
            sha = parts[0] if parts else "?"
            msg = parts[1] if len(parts) > 1 else ""
            table.add_row(sha, msg)

        if len(commits) > 20:
            table.add_row("...", f"[{MATRIX_DIM}]+{len(commits) - 20} more commits[/]")

        console.print(table)
        console.print()

        # Show affected files/services
        if self.changed_files:
            console.print(f"  [{MATRIX_CYAN}]Changed files:[/] [{MATRIX_GREEN}]{len(self.changed_files)}[/]", highlight=False)

        if self.affected_services:
            svc_list = ", ".join(sorted(self.affected_services))
            console.print(f"  [{MATRIX_CYAN}]Services to restart:[/] [{MATRIX_GREEN}]{svc_list}[/]", highlight=False)
        else:
            console.print(f"  [{MATRIX_CYAN}]Services to restart:[/] [{MATRIX_DIM}]none (config/personality only)[/]", highlight=False)

        console.print()

        # Ask for confirmation
        if not self.auto_confirm:
            r = console.input(f"  [bold {MATRIX_BRIGHT}]Apply update? [Y/n]: [/]").strip().lower()
            if r == "n":
                self._print_step(sid, "skipped", "User cancelled")
                return False

        self._print_step(sid, "done")
        console.print()
        matrix_rain(2)
        return True

    # ── Step 4: Backup ────────────────────────────────────────────────────
    def step_backup(self) -> bool:
        sid = "backup"
        self._print_step(sid, "running")

        ok, full_sha, _ = _run(["git", "rev-parse", "HEAD"], cwd=str(self.repo))
        if not ok:
            self._fail(sid, "Cannot read full SHA")
            return False

        self.backup_sha = full_sha.strip()
        backup_data = {
            "sha": self.backup_sha,
            "timestamp": datetime.now().isoformat(),
            "changed_files": self.changed_files,
            "affected_services": list(self.affected_services),
        }

        STATE_DIR.mkdir(parents=True, exist_ok=True)
        backup_file = STATE_DIR / "pre_update.json"
        backup_file.write_text(json.dumps(backup_data, indent=2))

        self._print_step(sid, "done", f"Saved {self.backup_sha[:8]}")
        return True

    # ── Step 5: Stop services ─────────────────────────────────────────────
    def step_stop_services(self) -> bool:
        sid = "stop"
        self._print_step(sid, "running")

        if not self.affected_services:
            self._print_step(sid, "skipped", "No services affected")
            return True

        for svc in sorted(self.affected_services):
            # Check if service is active
            ok, state, _ = _run(["systemctl", "--user", "is-active", svc])
            if ok and state == "active":
                console.print(f"    [{MATRIX_DIM}]Stopping {svc}...[/]", highlight=False)
                ok2, _, err = _run(["systemctl", "--user", "stop", svc], timeout=30)
                if ok2:
                    self.stopped_services.append(svc)
                else:
                    console.print(f"    [#FFAA00]Warning: Failed to stop {svc}: {err[:60]}[/]", highlight=False)

        detail = f"Stopped {len(self.stopped_services)} service(s)"
        self._print_step(sid, "done", detail)
        return True

    # ── Step 6: Pull ──────────────────────────────────────────────────────
    def step_pull(self) -> bool:
        sid = "pull"
        self._print_step(sid, "running")

        ok, out, err = _run(
            ["git", "pull", "--ff-only", "origin", "main"],
            timeout=120, cwd=str(self.repo)
        )
        if not ok:
            self._fail(sid, f"git pull failed: {err[:80]}")
            return False

        self._print_step(sid, "done", out.splitlines()[-1] if out else "OK")
        return True

    # ── Step 7: Pip sync ──────────────────────────────────────────────────
    def step_pip_sync(self) -> bool:
        sid = "pip_sync"
        self._print_step(sid, "running")

        req_changed = any(f.endswith("requirements.txt") for f in self.changed_files)
        if not req_changed:
            self._print_step(sid, "skipped", "requirements.txt unchanged")
            return True

        req_file = self.repo / "requirements.txt"
        if not req_file.exists():
            self._print_step(sid, "skipped", "No requirements.txt found")
            return True

        pip = self.venv / "bin" / "pip" if self.venv.exists() else "pip3"
        ok, out, err = _run(
            [str(pip), "install", "-r", str(req_file), "-q"],
            timeout=300, cwd=str(self.repo)
        )
        if not ok:
            self._fail(sid, f"pip install failed: {err[:80]}")
            return False

        self._print_step(sid, "done", "Dependencies updated")
        return True

    # ── Step 8: Service files ─────────────────────────────────────────────
    def step_service_files(self) -> bool:
        sid = "service_files"
        self._print_step(sid, "running")

        service_changed = any(
            f.endswith(".service") or f.endswith(".timer") or "systemd" in f
            for f in self.changed_files
        )
        if not service_changed:
            self._print_step(sid, "skipped", "No service files changed")
            return True

        ok, _, err = _run(["systemctl", "--user", "daemon-reload"])
        if not ok:
            self._fail(sid, f"daemon-reload failed: {err[:60]}")
            return False

        self._print_step(sid, "done", "daemon-reload complete")
        return True

    # ── Step 9: Start services ────────────────────────────────────────────
    def step_start_services(self) -> bool:
        sid = "start"
        self._print_step(sid, "running")

        if not self.stopped_services:
            self._print_step(sid, "skipped", "No services to restart")
            return True

        started = 0
        for svc in self.stopped_services:
            console.print(f"    [{MATRIX_DIM}]Starting {svc}...[/]", highlight=False)
            ok, _, err = _run(["systemctl", "--user", "start", svc], timeout=15)
            if ok:
                started += 1
            else:
                console.print(f"    [#FFAA00]Warning: Failed to start {svc}: {err[:60]}[/]", highlight=False)

        self._print_step(sid, "done", f"Started {started}/{len(self.stopped_services)}")
        return True

    # ── Step 10: Health check ─────────────────────────────────────────────
    def step_health_check(self) -> bool:
        sid = "health"
        self._print_step(sid, "running")

        # Wait a moment for services to initialize
        time.sleep(2)

        # Check systemd status for stopped services
        all_ok = True
        for svc in self.stopped_services:
            ok, state, _ = _run(["systemctl", "--user", "is-active", svc])
            icon = f"[{MATRIX_GREEN}]●[/]" if ok else "[#FF4444]●[/]"
            console.print(f"    {icon}  [{MATRIX_DIM}]{svc}: {state}[/]", highlight=False)
            if not ok:
                all_ok = False

        # Hit /health endpoints for affected services
        for svc in self.stopped_services:
            if svc in HEALTH_CHECKS:
                host, port = HEALTH_CHECKS[svc]
                try:
                    import urllib.request
                    url = f"http://{host}:{port}/health"
                    req = urllib.request.Request(url, method="GET")
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        if resp.status == 200:
                            console.print(f"    [{MATRIX_GREEN}]●[/]  [{MATRIX_DIM}]{svc} /health: OK[/]", highlight=False)
                        else:
                            console.print(f"    [#FFAA00]●[/]  [{MATRIX_DIM}]{svc} /health: {resp.status}[/]", highlight=False)
                except Exception:
                    console.print(f"    [{MATRIX_DIM}]○[/]  [{MATRIX_DIM}]{svc} /health: not reachable (may need warmup)[/]", highlight=False)

        self._print_step(sid, "done" if all_ok else "done", "All services verified" if all_ok else "Some services need attention")
        return True

    # ── Step 11: Overlay Display Environment ──────────────────────────
    def step_overlay_env(self) -> bool:
        """Ensure frank-overlay.service has correct DISPLAY/XAUTHORITY for this system."""
        sid = "overlay_env"
        self._print_step(sid, "running")

        svc_dir = Path.home() / ".config" / "systemd" / "user"
        svc_file = svc_dir / "frank-overlay.service"

        if not svc_file.exists():
            self._print_step(sid, "skipped", "frank-overlay.service not found")
            return True

        content = svc_file.read_text()

        # --- Detect current display environment ---
        display = os.environ.get("DISPLAY", "")
        xauthority = os.environ.get("XAUTHORITY", "")

        # If DISPLAY not available (e.g. SSH session), try common defaults
        if not display:
            display = ":0"

        # Find a valid XAUTHORITY file
        xauth_resolved = ""
        if xauthority and Path(xauthority).exists():
            xauth_resolved = xauthority
        else:
            # Search for valid Xauthority files (Wayland + X11 locations)
            uid = os.getuid()
            run_user = Path(f"/run/user/{uid}")
            candidates = []
            # Wayland: mutter-Xwaylandauth files (ephemeral, created by GNOME)
            if run_user.exists():
                try:
                    for f in run_user.iterdir():
                        if "Xwaylandauth" in f.name or "xauth" in f.name.lower():
                            candidates.append(f)
                except PermissionError:
                    pass
            # X11 / GDM locations
            candidates.extend([
                run_user / "gdm" / "Xauthority",
                Path.home() / ".Xauthority",
            ])
            for c in candidates:
                if c.exists():
                    xauth_resolved = str(c)
                    break

        # Fallback: use %h/.Xauthority (systemd expands %h to $HOME)
        if not xauth_resolved:
            xauth_resolved = "%h/.Xauthority"

        # --- Check current service file ---
        lines = content.splitlines()
        has_display = False
        has_xauth = False
        current_display = ""
        current_xauth = ""

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("Environment=DISPLAY="):
                has_display = True
                current_display = stripped.split("=", 2)[2]
            elif stripped.startswith("Environment=XAUTHORITY="):
                has_xauth = True
                current_xauth = stripped.split("=", 2)[2]

        # Check if XAUTHORITY path actually exists (resolve %h)
        xauth_check = current_xauth.replace("%h", str(Path.home()))
        xauth_exists = Path(xauth_check).exists() if xauth_check else False

        if has_display and has_xauth and xauth_exists:
            self._print_step(sid, "done", f"DISPLAY={current_display} XAUTHORITY=.../{Path(xauth_check).name}")
            return True

        # --- Need to fix the service file ---
        needs_restart = False

        # Determine best XAUTHORITY value for the service file
        # Prefer %h/.Xauthority if it exists (works across sessions)
        # Otherwise use the resolved absolute path
        home_xauth = Path.home() / ".Xauthority"
        if home_xauth.exists():
            svc_xauth = "%h/.Xauthority"
        elif xauth_resolved and xauth_resolved != "%h/.Xauthority":
            svc_xauth = xauth_resolved
        else:
            svc_xauth = "%h/.Xauthority"

        new_lines = []
        display_written = False
        xauth_written = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("Environment=DISPLAY="):
                new_lines.append(f"Environment=DISPLAY={display}")
                display_written = True
                if stripped != f"Environment=DISPLAY={display}":
                    needs_restart = True
            elif stripped.startswith("Environment=XAUTHORITY="):
                new_lines.append(f"Environment=XAUTHORITY={svc_xauth}")
                xauth_written = True
                if stripped != f"Environment=XAUTHORITY={svc_xauth}":
                    needs_restart = True
            else:
                new_lines.append(line)
                # Insert DISPLAY/XAUTHORITY before ExecStart if not found yet
                if stripped.startswith("ExecStart="):
                    insert_before = len(new_lines) - 1
                    if not display_written:
                        new_lines.insert(insert_before, f"Environment=DISPLAY={display}")
                        display_written = True
                        needs_restart = True
                    if not xauth_written:
                        new_lines.insert(insert_before + (1 if not has_display else 0),
                                         f"Environment=XAUTHORITY={svc_xauth}")
                        xauth_written = True
                        needs_restart = True

        if needs_restart:
            svc_file.write_text("\n".join(new_lines))
            _run(["systemctl", "--user", "daemon-reload"])

            # Also import current session's display env into systemd user manager
            if os.environ.get("DISPLAY"):
                _run(["systemctl", "--user", "import-environment", "DISPLAY", "XAUTHORITY"])

            # Restart overlay to pick up new env
            _run(["systemctl", "--user", "restart", "frank-overlay"], timeout=10)

            detail = f"Fixed: DISPLAY={display}"
            if svc_xauth != "%h/.Xauthority":
                detail += f" XAUTHORITY={svc_xauth}"
            console.print(f"    [{MATRIX_GREEN}]Patched frank-overlay.service and restarted[/]", highlight=False)
            self._print_step(sid, "done", detail)
        else:
            self._print_step(sid, "done", "DISPLAY/XAUTHORITY OK")

        return True

    # ── Step 12: Model Verification & Auto-Repair ─────────────────────
    def step_models(self) -> bool:
        sid = "models"
        self._print_step(sid, "running")

        # Check all binaries
        bin_results = [_check_binary(b) for b in BINARY_CHECKS]
        # Check all models
        model_results = [_check_model(m) for m in MODEL_REGISTRY]

        # Display binary status
        console.print(f"\n    [{MATRIX_CYAN}]Binaries[/]", highlight=False)
        for b in bin_results:
            icon = f"[{MATRIX_GREEN}]●[/]" if b["status"] == "ok" else "[#FF4444]●[/]"
            console.print(f"    {icon}  [{MATRIX_DIM}]{b['name']}: {b['status']}[/]", highlight=False)

        # Display model status grouped by category
        categories = [("gguf", "LLM Models"), ("whisper", "Speech-to-Text"),
                      ("voice", "Voice / TTS"), ("ollama", "Ollama Vision")]
        for cat, label in categories:
            entries = [m for m in model_results if m["category"] == cat]
            if not entries:
                continue
            console.print(f"\n    [{MATRIX_CYAN}]{label}[/]", highlight=False)
            for m in entries:
                if m["status"] == "ok":
                    icon = f"[{MATRIX_GREEN}]●[/]"
                elif m["status"] in ("missing", "corrupt"):
                    icon = "[#FF4444]●[/]"
                else:
                    icon = "[#FFAA00]●[/]"
                extra = ""
                if m["file_size"] > 0:
                    extra += f" ({_fmt_size(m['file_size'])})"
                if m.get("service_running"):
                    extra += f" [{MATRIX_GREEN}]running[/]"
                if m.get("health_ok"):
                    extra += f" [{MATRIX_GREEN}]healthy[/]"
                console.print(f"    {icon}  [{MATRIX_DIM}]{m['name']}: {m['status']}{extra}[/]", highlight=False)

        # Find broken models that need repair
        broken = [m for m in model_results if m["status"] in ("missing", "corrupt")]
        missing_bins = [b for b in bin_results if b["status"] == "missing"]

        if missing_bins:
            console.print(f"\n    [#FFAA00]Missing binaries (need manual build via install.sh):[/]", highlight=False)
            for b in missing_bins:
                console.print(f"      - {b['name']} ({b['path']})", highlight=False)

        if not broken:
            # All models present — run inference tests on healthy LLM services
            console.print(f"\n    [{MATRIX_CYAN}]Inference Tests[/]", highlight=False)
            for m in model_results:
                port = m["entry"][7]  # test_port
                cat = m["category"]
                if port and m.get("health_ok"):
                    if cat in ("gguf",):
                        # LLM: full inference test
                        ok = _test_inference(port)
                        icon = f"[{MATRIX_GREEN}]●[/]" if ok else "[#FFAA00]●[/]"
                        status = "inference OK" if ok else "health OK, inference failed"
                    else:
                        # Whisper etc: health check is sufficient
                        icon = f"[{MATRIX_GREEN}]●[/]"
                        status = "health OK"
                    console.print(f"    {icon}  [{MATRIX_DIM}]{m['name']}: {status}[/]", highlight=False)

            total = len(model_results) + len(bin_results)
            ok_count = sum(1 for m in model_results if m["status"] == "ok") + \
                       sum(1 for b in bin_results if b["status"] == "ok")
            console.print()
            self._print_step(sid, "done", f"{ok_count}/{total} components OK")
            return True

        # Auto-repair: download missing/corrupt models
        console.print(f"\n    [bold #FFAA00]{len(broken)} model(s) need repair:[/]", highlight=False)
        for m in broken:
            console.print(f"      - {m['name']} ({m['status']})", highlight=False)

        if not self.auto_confirm:
            console.print()
            r = console.input(f"    [bold {MATRIX_BRIGHT}]Download missing models? [Y/n]: [/]").strip().lower()
            if r == "n":
                self._print_step(sid, "done", f"{len(broken)} models skipped")
                return True

        fixed = 0
        for m in broken:
            entry = m["entry"]
            cat = m["category"]
            if cat == "ollama":
                ollama_tag = entry[9]
                ok = _pull_ollama(ollama_tag)
            else:
                ok = _download_model(entry)

            if ok:
                fixed += 1
                console.print(f"      [{MATRIX_GREEN}]OK[/]: {m['name']}", highlight=False)
            else:
                console.print(f"      [#FF4444]FAILED[/]: {m['name']}", highlight=False)

        # Re-check after repair
        if fixed > 0:
            console.print(f"\n    [{MATRIX_DIM}]Re-checking...[/]", highlight=False)
            model_results = [_check_model(m) for m in MODEL_REGISTRY]
            still_broken = [m for m in model_results if m["status"] in ("missing", "corrupt")]
            ok_count = sum(1 for m in model_results if m["status"] == "ok") + \
                       sum(1 for b in bin_results if b["status"] == "ok")
            total = len(model_results) + len(bin_results)

            if still_broken:
                self._print_step(sid, "done", f"{ok_count}/{total} OK, {len(still_broken)} still broken")
            else:
                self._print_step(sid, "done", f"Repaired {fixed} model(s), {ok_count}/{total} OK")
        else:
            self._print_step(sid, "error", "Downloads failed")

        return True

    # ── Rollback ──────────────────────────────────────────────────────────
    def rollback(self):
        """Rollback to saved SHA and restart all stopped services."""
        console.print()
        console.print(f"  [bold #FF4444]Rolling back to {self.backup_sha[:8]}...[/]", highlight=False)

        if self.backup_sha:
            ok, _, err = _run(
                ["git", "reset", "--hard", self.backup_sha],
                cwd=str(self.repo)
            )
            if ok:
                console.print(f"  [{MATRIX_GREEN}]Git reset successful[/]", highlight=False)
            else:
                console.print(f"  [#FF4444]Git reset failed: {err[:80]}[/]", highlight=False)

        # Restart all stopped services
        for svc in self.stopped_services:
            _run(["systemctl", "--user", "start", svc], timeout=15)
            console.print(f"    [{MATRIX_DIM}]Restarted {svc}[/]", highlight=False)

        console.print(f"  [{MATRIX_GREEN}]Rollback complete[/]", highlight=False)

    # ── Cleanup ───────────────────────────────────────────────────────────
    def cleanup(self):
        lock = STATE_DIR / "update.lock"
        lock.unlink(missing_ok=True)

    # ── Main run ──────────────────────────────────────────────────────────
    def run(self) -> bool:
        """Execute the full update pipeline. Returns True on success."""
        import shutil
        width = shutil.get_terminal_size().columns

        # Show header
        console.clear()
        console.print()
        console.print(Align.center(FRANK_TITLE), highlight=False)
        console.print(Align.center(SUBTITLE), highlight=False)
        console.print()
        console.print(f"  [{MATRIX_DIM}]{'━' * (width - 4)}[/]")
        console.print()
        console.print(f"  [{MATRIX_CYAN}]Repository:[/]  [{MATRIX_GREEN}]{self.repo}[/]", highlight=False)
        console.print()

        try:
            # Step 1: Pre-flight
            if not self.step_preflight():
                return False

            # Step 2: Fetch
            result = self.step_fetch()
            if not result and self.local_sha == self.remote_sha:
                # Up to date — still check models
                console.print()
                console.print(Align.center(
                    f"[bold {MATRIX_GREEN}]System is already up to date ({self.local_sha})[/]"
                ))
                console.print()
                self.step_overlay_env()
                self.step_models()
                return True
            elif not result:
                return False

            # Step 3: Changelog + confirmation
            if not self.step_changelog():
                return True  # User cancelled — not an error

            # Step 4: Backup
            if not self.step_backup():
                return False

            # Step 5: Stop services
            if not self.step_stop_services():
                return False

            # Step 6-8: Pull, pip sync, service files (rollback on failure)
            steps_with_rollback = [
                self.step_pull,
                self.step_pip_sync,
                self.step_service_files,
            ]
            for step_fn in steps_with_rollback:
                if not step_fn():
                    console.print()
                    console.print(f"  [bold #FF4444]Update failed at {step_fn.__name__}[/]", highlight=False)
                    self.rollback()
                    return False

            # Step 9: Start services
            self.step_start_services()

            # Step 10: Health check
            self.step_health_check()

            # Step 11: Overlay display environment
            self.step_overlay_env()

            # Step 12: Model verification & auto-repair
            self.step_models()

            # Success banner
            console.print()
            console.print(f"  [{MATRIX_DIM}]{'━' * (width - 4)}[/]")
            matrix_rain(2)
            console.print()
            console.print(Align.center(f"[bold {MATRIX_GREEN}]╔══════════════════════════════════════════╗[/]"))
            console.print(Align.center(f"[bold {MATRIX_GREEN}]║                                          ║[/]"))
            console.print(Align.center(f"[bold {MATRIX_GREEN}]║       UPDATE COMPLETE                    ║[/]"))
            console.print(Align.center(f"[bold {MATRIX_GREEN}]║                                          ║[/]"))
            console.print(Align.center(f"[bold {MATRIX_GREEN}]╚══════════════════════════════════════════╝[/]"))
            console.print()

            ok, new_sha, _ = _run(["git", "rev-parse", "--short", "HEAD"], cwd=str(self.repo))
            if ok:
                console.print(f"  [{MATRIX_CYAN}]Version:[/]  [{MATRIX_GREEN}]{self.local_sha} → {new_sha}[/]", highlight=False)

            if self.stopped_services:
                console.print(f"  [{MATRIX_CYAN}]Restarted:[/] [{MATRIX_GREEN}]{', '.join(sorted(self.stopped_services))}[/]", highlight=False)

            console.print()
            return True

        except KeyboardInterrupt:
            console.print()
            console.print(f"  [{MATRIX_DIM}]Update interrupted by user[/]", highlight=False)
            if self.stopped_services:
                console.print(f"  [{MATRIX_DIM}]Restarting stopped services...[/]", highlight=False)
                for svc in self.stopped_services:
                    _run(["systemctl", "--user", "start", svc], timeout=15)
            return False
        finally:
            self.cleanup()


# ── Silent check mode ────────────────────────────────────────────────────────

def check_for_updates(repo_path: Path = None) -> dict:
    """Silent update check. Returns dict with status info."""
    repo = repo_path or _find_repo()

    if not (repo / ".git").exists():
        return {"available": False, "error": "Not a git repository"}

    ok, local, _ = _run(["git", "rev-parse", "--short", "HEAD"], cwd=str(repo))
    if not ok:
        return {"available": False, "error": "Cannot read HEAD"}

    ok, _, err = _run(["git", "fetch", "origin", "main"], timeout=30, cwd=str(repo))
    if not ok:
        return {"available": False, "error": f"Fetch failed: {err[:60]}"}

    ok, remote, _ = _run(["git", "rev-parse", "--short", "origin/main"], cwd=str(repo))
    if not ok:
        return {"available": False, "error": "Cannot read origin/main"}

    if local == remote:
        return {"available": False, "local": local, "remote": remote}

    ok, log_out, _ = _run(
        ["git", "log", "HEAD..origin/main", "--oneline", "--no-decorate"],
        cwd=str(repo)
    )
    commits = log_out.strip().splitlines() if ok and log_out else []

    return {
        "available": True,
        "local": local,
        "remote": remote,
        "commits": len(commits),
        "changelog": commits[:10],
    }


# ── CLI entry ────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="F.R.A.N.K. Update System")
    parser.add_argument("--check", action="store_true", help="Silent update check (exit 0=available, 1=up-to-date)")
    parser.add_argument("--models", action="store_true", help="Only check/repair models (skip git update)")
    parser.add_argument("--yes", "-y", action="store_true", help="Auto-confirm (no prompts)")
    parser.add_argument("--repo", type=str, help="Path to aicore repo (default: ~/aicore/opt/aicore)")
    args = parser.parse_args()

    repo = Path(args.repo) if args.repo else None

    if args.check:
        result = check_for_updates(repo)
        if result.get("error"):
            print(f"Error: {result['error']}")
            sys.exit(2)
        if result["available"]:
            print(f"Update available: {result['local']} → {result['remote']} ({result['commits']} commits)")
            sys.exit(0)
        else:
            print(f"Up to date: {result.get('local', '?')}")
            sys.exit(1)

    if args.models:
        # Standalone model check/repair — no git update
        updater = FrankUpdater(repo_path=repo, auto_confirm=args.yes)
        import shutil
        width = shutil.get_terminal_size().columns
        console.clear()
        console.print()
        console.print(Align.center(FRANK_TITLE), highlight=False)
        console.print(Align.center(f"[bold {MATRIX_CYAN}]AI CORE SYSTEM[/]  [dim {MATRIX_DIM}]— Model Verification —[/]"), highlight=False)
        console.print()
        console.print(f"  [{MATRIX_DIM}]{'━' * (width - 4)}[/]")
        console.print()
        updater.step_models()
        console.print()
        if not args.yes:
            console.input(f"  [{MATRIX_DIM}]Press Enter to close...[/]")
        sys.exit(0)

    updater = FrankUpdater(repo_path=repo, auto_confirm=args.yes)
    success = updater.run()

    if not success and updater.errors:
        sys.exit(1)

    # Keep terminal open for user to read
    if not args.yes:
        console.print()
        console.input(f"  [{MATRIX_DIM}]Press Enter to close...[/]")


if __name__ == "__main__":
    main()
