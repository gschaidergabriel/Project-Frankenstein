#!/usr/bin/env bash
# ============================================================================
# AI-Core / Frank — Installation Script
# ============================================================================
# Usage:  ./install.sh [--no-models] [--cpu-only] [--no-build]
#
# This script:
#   1.  Checks system requirements (RAM, disk)
#   2.  Installs system dependencies (apt)
#   3.  Detects GPU and configures backend (Vulkan / CUDA / CPU)
#   4.  Creates main Python venv and installs pip packages
#   5.  Creates ingestd Python venv (separate for whisper/ctranslate2)
#   6.  Builds llama.cpp from source (LLM inference)
#   7.  Builds whisper.cpp from source (speech-to-text)
#   8.  Creates data directories
#   9.  Installs Ollama and pulls vision models
#   10. Downloads LLM models (GGUF)
#   11. Sets up Voice / TTS (Piper German + Kokoro English + espeak)
#   12. Installs all systemd user services (25+ services)
#   13. Creates desktop entries and dock icons
# ============================================================================

set -euo pipefail

# --- Parse arguments ---
NO_MODELS=false
CPU_ONLY=false
NO_BUILD=false
for arg in "$@"; do
    case "$arg" in
        --no-models) NO_MODELS=true ;;
        --cpu-only)  CPU_ONLY=true ;;
        --no-build)  NO_BUILD=true ;;
        --help|-h)
            echo "Usage: ./install.sh [--no-models] [--cpu-only] [--no-build]"
            echo "  --no-models   Skip downloading LLM / voice model files"
            echo "  --cpu-only    Force CPU-only mode (no GPU acceleration)"
            echo "  --no-build    Skip building llama.cpp and whisper.cpp from source"
            exit 0
            ;;
    esac
done

# --- Paths ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPT_DIR="$(dirname "$SCRIPT_DIR")"
AICORE_ROOT="$(dirname "$OPT_DIR")"
DATA_DIR="${AICORE_DATA:-$HOME/.local/share/frank}"
CONFIG_DIR="${AICORE_CONFIG:-$HOME/.config/frank}"
MODELS_DIR="$AICORE_ROOT/var/lib/aicore/models"
VOICES_DIR="$DATA_DIR/voices"
KOKORO_DIR="$DATA_DIR/kokoro"
VENV_DIR="$OPT_DIR/venv"
VENV_INGESTD="$OPT_DIR/venv-ingestd"
LLAMA_DIR="$OPT_DIR/llama.cpp"
WHISPER_DIR="$OPT_DIR/whisper.cpp"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              AI-Core / Frank — Installer                    ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo
echo "  Source:   $SCRIPT_DIR"
echo "  Opt:      $OPT_DIR"
echo "  Data:     $DATA_DIR"
echo "  Config:   $CONFIG_DIR"
echo "  Models:   $MODELS_DIR"
echo "  Voices:   $VOICES_DIR"
echo "  Venv:     $VENV_DIR"
echo "  Ingestd:  $VENV_INGESTD"
echo

# --- Helper: download with retry ---
download_file() {
    local url="$1"
    local file="$2"
    local label="$3"
    if [ -f "$file" ]; then
        echo "  $label already present."
        return 0
    fi
    echo "  Downloading $label..."
    wget -q --show-progress --tries=3 --timeout=120 -O "$file.tmp" "$url" && \
        mv "$file.tmp" "$file" || {
            rm -f "$file.tmp"
            echo "  WARNING: Download failed for $label. Place it manually."
            return 1
        }
}

# ============================================================================
# [1/13] System requirements check
# ============================================================================
echo "[1/13] Checking system requirements..."
RAM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
mkdir -p "$MODELS_DIR" 2>/dev/null || true
DISK_FREE_MB=$(df -BM --output=avail "$MODELS_DIR" 2>/dev/null | tail -1 | tr -d ' M')

echo "  RAM: ${RAM_MB} MB"
echo "  Disk free: ${DISK_FREE_MB} MB"

if [ "$RAM_MB" -lt 8000 ]; then
    echo "  WARNING: Less than 8 GB RAM detected. LLM inference will be very slow."
    echo "  Recommended: 16 GB+ for comfortable usage."
fi

if ! $NO_MODELS && [ "$DISK_FREE_MB" -lt 20000 ]; then
    echo "  WARNING: Less than 20 GB free disk space."
    echo "  Models + voice data require ~15 GB. Use --no-models to skip."
fi

# ============================================================================
# [2/13] System dependencies
# ============================================================================
echo "[2/13] Installing system dependencies..."
sudo apt-get update -qq

# Core system packages
sudo apt-get install -y -qq \
    python3 python3-venv python3-pip python3-tk python3-dev \
    build-essential cmake \
    xdotool wmctrl xprop x11-xserver-utils xprintidle \
    tesseract-ocr \
    pulseaudio-utils \
    curl wget git jq lsof \
    libgirepository1.0-dev gir1.2-appindicator3-0.1 \
    2>/dev/null

# GTK / GObject (for Writer + tray icon)
sudo apt-get install -y -qq \
    python3-gi python3-gi-cairo \
    gir1.2-gtk-4.0 gir1.2-gtksourceview-5 gir1.2-libadwaita-1 \
    libcairo2-dev \
    2>/dev/null || echo "  Note: Some GTK4 packages may not be available on your distro."

# Audio / Voice
sudo apt-get install -y -qq \
    espeak libsndfile1-dev libsndfile1 \
    2>/dev/null

echo "  Done."

# ============================================================================
# [3/13] GPU detection
# ============================================================================
echo "[3/13] Detecting GPU..."
GPU_NAME="none"
GPU_BACKEND="cpu"
CMAKE_GPU_FLAG=""

if $CPU_ONLY; then
    echo "  CPU-only mode (forced)"
else
    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
        GPU_BACKEND="cuda"
        CMAKE_GPU_FLAG="-DGGML_CUDA=ON"
        GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)
        echo "  NVIDIA GPU detected: $GPU_NAME (CUDA)"
    elif lspci -d 1002: 2>/dev/null | grep -qi "VGA\|Display"; then
        GPU_BACKEND="vulkan"
        CMAKE_GPU_FLAG="-DGGML_VULKAN=ON"
        GPU_NAME=$(lspci -d 1002: 2>/dev/null | grep -i "VGA\|Display" | sed 's/.*: //')
        echo "  AMD GPU detected: $GPU_NAME (Vulkan)"
        sudo apt-get install -y -qq libvulkan1 mesa-vulkan-drivers vulkan-tools 2>/dev/null || true
    elif lspci -d 8086: 2>/dev/null | grep -qi "VGA\|Display"; then
        GPU_BACKEND="vulkan"
        CMAKE_GPU_FLAG="-DGGML_VULKAN=ON"
        GPU_NAME=$(lspci -d 8086: 2>/dev/null | grep -i "VGA\|Display" | sed 's/.*: //')
        echo "  Intel GPU detected: $GPU_NAME (Vulkan)"
        sudo apt-get install -y -qq libvulkan1 mesa-vulkan-drivers vulkan-tools 2>/dev/null || true
    else
        echo "  No GPU detected, using CPU-only mode"
    fi
fi

# GPU-specific environment for systemd services
if [ "$GPU_BACKEND" = "vulkan" ]; then
    GPU_ENV_LINE='Environment=GGML_VULKAN_DEVICE=0'
    LLAMA_GPU_FLAGS="-ngl 99 --flash-attn on"
elif [ "$GPU_BACKEND" = "cuda" ]; then
    GPU_ENV_LINE=""
    LLAMA_GPU_FLAGS="-ngl 99 --flash-attn on"
else
    GPU_ENV_LINE=""
    LLAMA_GPU_FLAGS=""
fi

# ============================================================================
# [4/13] Python venv (main)
# ============================================================================
echo "[4/13] Setting up main Python virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q
pip install -r "$SCRIPT_DIR/requirements.txt" -q
deactivate
echo "  Done. ($(python3 --version))"

# ============================================================================
# [5/13] Python venv (ingestd)
# ============================================================================
echo "[5/13] Setting up ingestd virtual environment..."
if [ ! -d "$VENV_INGESTD" ]; then
    python3 -m venv "$VENV_INGESTD"
fi
source "$VENV_INGESTD/bin/activate"
pip install --upgrade pip -q
pip install -q \
    faster-whisper uvicorn fastapi httpx Pillow lxml \
    coloredlogs annotated-doc
deactivate
echo "  Done."

# ============================================================================
# [6/13] Build llama.cpp
# ============================================================================
if $NO_BUILD; then
    echo "[6/13] Skipping llama.cpp build (--no-build)"
else
    echo "[6/13] Building llama.cpp..."
    if [ ! -d "$LLAMA_DIR" ]; then
        git clone --depth 1 https://github.com/ggml-org/llama.cpp.git "$LLAMA_DIR"
    fi
    cd "$LLAMA_DIR"
    cmake -B build $CMAKE_GPU_FLAG -DCMAKE_BUILD_TYPE=Release 2>/dev/null
    cmake --build build --config Release -j"$(nproc)" 2>&1 | tail -5
    cd "$SCRIPT_DIR"

    if [ -x "$LLAMA_DIR/build/bin/llama-server" ]; then
        echo "  llama-server built successfully."
    else
        echo "  WARNING: llama-server build failed. Check $LLAMA_DIR/build/ for errors."
    fi
fi

# ============================================================================
# [7/13] Build whisper.cpp
# ============================================================================
if $NO_BUILD; then
    echo "[7/13] Skipping whisper.cpp build (--no-build)"
else
    echo "[7/13] Building whisper.cpp..."
    if [ ! -d "$WHISPER_DIR" ]; then
        git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git "$WHISPER_DIR"
    fi
    cd "$WHISPER_DIR"
    cmake -B build $CMAKE_GPU_FLAG -DCMAKE_BUILD_TYPE=Release 2>/dev/null
    cmake --build build --config Release -j"$(nproc)" 2>&1 | tail -5
    cd "$SCRIPT_DIR"

    if [ -x "$WHISPER_DIR/build/bin/whisper-server" ]; then
        echo "  whisper-server built successfully."
    else
        echo "  WARNING: whisper-server build failed. Check $WHISPER_DIR/build/ for errors."
    fi

    # Download Whisper medium model
    if ! $NO_MODELS; then
        WHISPER_MODEL="$WHISPER_DIR/models/ggml-medium.bin"
        if [ ! -f "$WHISPER_MODEL" ]; then
            echo "  Downloading Whisper medium model (~1.5 GB)..."
            cd "$WHISPER_DIR"
            bash models/download-ggml-model.sh medium 2>/dev/null || \
                echo "  WARNING: Whisper model download failed. Run: cd $WHISPER_DIR && bash models/download-ggml-model.sh medium"
            cd "$SCRIPT_DIR"
        else
            echo "  Whisper medium model already present."
        fi
    fi
fi

# ============================================================================
# [8/13] Create data directories
# ============================================================================
echo "[8/13] Creating data directories..."
mkdir -p "$MODELS_DIR" "$VOICES_DIR" "$KOKORO_DIR"
mkdir -p "$DATA_DIR"/{state,logs,training,error_screenshots,sandbox,adi_profiles}
mkdir -p "$CONFIG_DIR"
mkdir -p "/tmp/frank"/{notifications,screenshots}

# Run Python ensure_dirs() for full directory tree
"$VENV_DIR/bin/python3" -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
try:
    from config.paths import ensure_dirs
    ensure_dirs()
    print('  Directory tree created via config.paths.')
except Exception as e:
    print(f'  Note: ensure_dirs() skipped ({e}). Basic dirs created.')
" 2>/dev/null

# Copy example config
if [ ! -f "$CONFIG_DIR/config.yaml" ] && [ -f "$SCRIPT_DIR/config.yaml.example" ]; then
    cp "$SCRIPT_DIR/config.yaml.example" "$CONFIG_DIR/config.yaml"
    echo "  Copied config.yaml.example -> $CONFIG_DIR/config.yaml"
fi
echo "  Done."

# ============================================================================
# [9/13] Install Ollama + pull vision models
# ============================================================================
echo "[9/13] Installing Ollama (local vision inference)..."
if command -v ollama &>/dev/null; then
    echo "  Ollama already installed ($(ollama --version 2>/dev/null || echo 'unknown'))"
else
    curl -fsSL https://ollama.com/install.sh | sh
    echo "  Ollama installed."
fi

# Configure Ollama for Vulkan if needed
if [ "$GPU_BACKEND" = "vulkan" ]; then
    OLLAMA_OVERRIDE_DIR="/etc/systemd/system/ollama.service.d"
    if [ ! -f "$OLLAMA_OVERRIDE_DIR/vulkan.conf" ] 2>/dev/null; then
        if sudo mkdir -p "$OLLAMA_OVERRIDE_DIR" 2>/dev/null; then
            echo -e "[Service]\nEnvironment=OLLAMA_VULKAN=1" | \
                sudo tee "$OLLAMA_OVERRIDE_DIR/vulkan.conf" >/dev/null
            sudo systemctl daemon-reload
            echo "  Configured Ollama for Vulkan GPU."
        fi
    fi
fi

# Start Ollama
sudo systemctl enable ollama 2>/dev/null || true
sudo systemctl start ollama 2>/dev/null || true

# Wait for Ollama
OLLAMA_READY=false
for i in $(seq 1 15); do
    if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
        OLLAMA_READY=true; break
    fi
    sleep 1
done

if ! $NO_MODELS && $OLLAMA_READY; then
    echo "  Pulling LLaVA 7B (vision)..."
    ollama pull llava:7b 2>/dev/null || echo "  Warning: Could not pull llava:7b"
    echo "  Pulling Moondream (lightweight vision)..."
    ollama pull moondream 2>/dev/null || echo "  Warning: Could not pull moondream"
elif ! $OLLAMA_READY; then
    echo "  WARNING: Ollama did not respond. Check: sudo systemctl status ollama"
fi

# ============================================================================
# [10/13] Download LLM models (GGUF)
# ============================================================================
if $NO_MODELS; then
    echo "[10/13] Skipping model downloads (--no-models)"
else
    echo "[10/13] Downloading LLM models..."
    mkdir -p "$MODELS_DIR"

    LLAMA_URL="https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf"
    QWEN_URL="https://huggingface.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf"

    download_file "$LLAMA_URL" \
        "$MODELS_DIR/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf" \
        "Llama 3.1 8B (Q4_K_M, ~4.9 GB)"

    download_file "$QWEN_URL" \
        "$MODELS_DIR/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf" \
        "Qwen 2.5 Coder 7B (Q4_K_M, ~4.7 GB)"
fi

# ============================================================================
# [11/13] Voice / TTS setup
# ============================================================================
if $NO_MODELS; then
    echo "[11/13] Skipping voice model downloads (--no-models)"
else
    echo "[11/13] Setting up Voice / TTS..."
    mkdir -p "$VOICES_DIR" "$KOKORO_DIR"

    # --- German voice: Piper + Thorsten (high quality) ---
    echo "  German TTS: Piper + Thorsten..."
    THORSTEN_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/high"
    download_file \
        "${THORSTEN_BASE}/de_DE-thorsten-high.onnx?download=true" \
        "$VOICES_DIR/de_DE-thorsten-high.onnx" \
        "Piper Thorsten voice model (~114 MB)"
    download_file \
        "${THORSTEN_BASE}/de_DE-thorsten-high.onnx.json?download=true" \
        "$VOICES_DIR/de_DE-thorsten-high.onnx.json" \
        "Piper Thorsten voice config"

    # --- English voice: Kokoro (am_fenrir deep voice) ---
    echo "  English TTS: Kokoro + am_fenrir..."
    KOKORO_BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
    download_file \
        "${KOKORO_BASE}/kokoro-v1.0.onnx" \
        "$KOKORO_DIR/kokoro-v1.0.onnx" \
        "Kokoro TTS model (~311 MB)"
    download_file \
        "${KOKORO_BASE}/voices-v1.0.bin" \
        "$KOKORO_DIR/voices-v1.0.bin" \
        "Kokoro voice embeddings (~27 MB)"

    echo "  Done."
fi

# ============================================================================
# [12/13] Systemd user services
# ============================================================================
echo "[12/13] Installing systemd user services..."
mkdir -p "$SYSTEMD_USER_DIR"

LLAMA_SERVER="$LLAMA_DIR/build/bin/llama-server"
WHISPER_SERVER="$WHISPER_DIR/build/bin/whisper-server"
PYTHON_SYS="/usr/bin/python3"
PYTHON_VENV="$VENV_DIR/bin/python3"
PYTHON_INGESTD="$VENV_INGESTD/bin/python3"

# Helper: write a service file (only if not already present)
write_service() {
    local name="$1"
    local content="$2"
    local target="$SYSTEMD_USER_DIR/${name}"
    if [ ! -f "$target" ]; then
        printf '%s\n' "$content" > "$target"
        echo "  Created $name"
    else
        echo "  $name already exists (skipped)"
    fi
}

# ── Tier 1: Infrastructure ──────────────────────────────────────────────────

write_service "aicore-router.service" "\
[Unit]
Description=AI Core router
After=network.target
Wants=network.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=$SCRIPT_DIR
Environment=PATH=$VENV_INGESTD/bin:/usr/bin:/bin
Environment=ROUTER_MODE=auto
Environment=DEFAULT_MODEL_ID=qwen_coder_7b_q4km
Environment=AICORE_QWEN_SERVICE=aicore-qwen-gpu.service
Environment=AICORE_LLAMA_HTTP_TIMEOUT_SEC=400
Environment=AICORE_QWEN_HTTP_TIMEOUT_SEC=400
ExecStart=$PYTHON_INGESTD -m uvicorn router.app:app --host 127.0.0.1 --port 8091 --log-level info --lifespan off
Restart=always
RestartSec=1

[Install]
WantedBy=default.target"

write_service "aicore-core.service" "\
[Unit]
Description=AI Core core
After=aicore-router.service
Requires=aicore-router.service

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
ExecStart=$PYTHON_SYS $SCRIPT_DIR/core/app.py
Restart=always
RestartSec=1
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target"

# Llama3 GPU service
if [ -x "$LLAMA_SERVER" ]; then
    write_service "aicore-llama3-gpu.service" "\
[Unit]
Description=AI Core Llama 3.1 8B (llama-server, GPU)
After=network.target

[Service]
Type=simple
WorkingDirectory=$LLAMA_DIR
${GPU_ENV_LINE:+$GPU_ENV_LINE}
ExecStart=$LLAMA_SERVER \\
    --host 127.0.0.1 --port 8101 \\
    --model $MODELS_DIR/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf \\
    --ctx-size 4096 $LLAMA_GPU_FLAGS \\
    --parallel 1 --threads 8 --threads-batch 8
Restart=always
RestartSec=5

[Install]
WantedBy=default.target"

    # Qwen GPU service (on-demand, no WantedBy)
    write_service "aicore-qwen-gpu.service" "\
[Unit]
Description=AI Core Qwen 2.5 Coder 7B (llama-server, GPU) - ON DEMAND
After=network.target

[Service]
Type=simple
WorkingDirectory=$LLAMA_DIR
${GPU_ENV_LINE:+$GPU_ENV_LINE}
ExecStart=$LLAMA_SERVER \\
    --host 127.0.0.1 --port 8102 \\
    --model $MODELS_DIR/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf \\
    --ctx-size 4096 $LLAMA_GPU_FLAGS \\
    --parallel 1 --threads 8 --threads-batch 8
Restart=on-failure
RestartSec=5

[Install]
# No WantedBy — started on-demand by Router"
else
    echo "  Note: llama-server not found — skipping LLM server services."
    echo "  Build llama.cpp first, then re-run install.sh."
fi

# Whisper GPU service
if [ -x "$WHISPER_SERVER" ]; then
    write_service "aicore-whisper-gpu.service" "\
[Unit]
Description=AI Core Whisper STT Server (GPU)
After=network.target

[Service]
Type=simple
WorkingDirectory=$WHISPER_DIR
${GPU_ENV_LINE:+$GPU_ENV_LINE}
ExecStart=$WHISPER_SERVER \\
    --host 127.0.0.1 --port 8103 \\
    --model $WHISPER_DIR/models/ggml-medium.bin \\
    --language auto --device 0 --threads 8 --convert
Restart=always
RestartSec=5

[Install]
WantedBy=default.target"
else
    echo "  Note: whisper-server not found — skipping Whisper service."
fi

write_service "aicore-modeld.service" "\
[Unit]
Description=AI Core modeld
After=network.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
ExecStart=$PYTHON_SYS $SCRIPT_DIR/modeld/app.py
Restart=always
RestartSec=1
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target"

write_service "aicore-toolboxd.service" "\
[Unit]
Description=AI Core toolboxd (local tools API)
After=network.target

[Service]
Type=simple
ExecStart=$PYTHON_SYS -u $SCRIPT_DIR/tools/toolboxd.py
Restart=always
RestartSec=0.5
Environment=AICORE_TOOLBOX_PORT=8096
Environment=DISPLAY=:0

[Install]
WantedBy=default.target"

write_service "aicore-webd.service" "\
[Unit]
Description=AI Core web search daemon (DuckDuckGo HTML)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=PYTHONUNBUFFERED=1
ExecStart=$PYTHON_SYS $SCRIPT_DIR/webd/app.py
Restart=always
RestartSec=1

[Install]
WantedBy=default.target"

write_service "aicore-ingestd.service" "\
[Unit]
Description=AI Core ingestd (attachments)
After=network.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR/ingestd
ExecStart=$PYTHON_INGESTD -m uvicorn app:app --host 127.0.0.1 --port 8094
Restart=on-failure
RestartSec=1
Environment=INGESTD_HOST=127.0.0.1
Environment=INGESTD_PORT=8094
Environment=FASTER_WHISPER_MODEL=base
Environment=FASTER_WHISPER_DEVICE=cpu
Environment=FASTER_WHISPER_COMPUTE=int8

[Install]
WantedBy=default.target"

# ── Tier 2: System daemons ──────────────────────────────────────────────────

write_service "aicore-desktopd.service" "\
[Unit]
Description=AI Core desktop daemon (X11)
After=default.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR/desktopd
ExecStart=$PYTHON_SYS $SCRIPT_DIR/desktopd/app.py
Restart=always
RestartSec=1
Environment=DISPLAY=:0
Environment=XAUTHORITY=%h/.Xauthority

[Install]
WantedBy=default.target"

write_service "aicore-consciousness.service" "\
[Unit]
Description=AI Core Consciousness Stream Daemon
After=aicore-core.service aicore-router.service
Wants=aicore-core.service

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
ExecStart=$PYTHON_SYS $SCRIPT_DIR/services/consciousness_daemon.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target"

write_service "aicore-voice.service" "\
[Unit]
Description=Frank Voice Daemon
After=pulseaudio.service pipewire.service
Wants=pulseaudio.service pipewire.service

[Service]
Type=simple
ExecStart=$PYTHON_SYS $SCRIPT_DIR/voice/voice_daemon.py --daemon
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1
Environment=HOME=$HOME
Environment=XDG_RUNTIME_DIR=/run/user/$(id -u)
Environment=PULSE_SERVER=unix:/run/user/$(id -u)/pulse/native
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus

[Install]
WantedBy=default.target"

write_service "aicore-gaming-mode.service" "\
[Unit]
Description=AI Core Gaming Mode Daemon
After=aicore-llama3-gpu.service aicore-qwen-gpu.service

[Service]
Type=simple
ExecStart=$PYTHON_SYS $SCRIPT_DIR/gaming/gaming_mode.py --daemon
Restart=on-failure
RestartSec=5
Environment=DISPLAY=:0

[Install]
WantedBy=default.target"

write_service "aicore-asrs.service" "\
[Unit]
Description=A.S.R.S. - Autonomous Safety Recovery System
After=aicore-core.service

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
ExecStart=$PYTHON_SYS -m services.asrs.daemon
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
StandardOutput=append:/tmp/asrs_daemon.log
StandardError=append:/tmp/asrs_daemon.log

[Install]
WantedBy=default.target"

write_service "aicore-invariants.service" "\
[Unit]
Description=AI-Core Invariants Daemon - Frank's Physics Engine
After=network.target
StartLimitIntervalSec=300
StartLimitBurst=5
Wants=aicore-core.service

[Service]
Type=notify
Environment=PYTHONPATH=$SCRIPT_DIR
ExecStart=$PYTHON_SYS -u $SCRIPT_DIR/services/invariants/daemon.py
WatchdogSec=120
Restart=on-failure
RestartSec=10
MemoryMax=200M
MemoryHigh=150M
CPUQuota=25%
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=$AICORE_ROOT/database/invariants
ReadWritePaths=$AICORE_ROOT/database
ReadWritePaths=$DATA_DIR/logs/invariants
NoNewPrivileges=true

[Install]
WantedBy=default.target"

# ── Tier 3: Autonomous systems ──────────────────────────────────────────────

write_service "aicore-genesis.service" "\
[Unit]
Description=SENTIENT GENESIS - Emergent Self-Improvement System
After=network.target
StartLimitIntervalSec=0

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
Environment=PYTHONPATH=$SCRIPT_DIR
Environment=DISPLAY=:0
ExecStart=$PYTHON_VENV -m services.genesis.daemon
Restart=always
RestartSec=5
WatchdogSec=120
NotifyAccess=all
StartLimitBurst=100
CPUQuota=30%
MemoryMax=750M
MemoryHigh=500M
Nice=15
TimeoutStartSec=30
TimeoutStopSec=30

[Install]
WantedBy=default.target"

write_service "aicore-genesis-watchdog.service" "\
[Unit]
Description=Genesis Watchdog - Ensures Genesis Never Dies
After=network.target
StartLimitIntervalSec=0

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
Environment=PYTHONPATH=$SCRIPT_DIR
ExecStart=$PYTHON_VENV -m services.genesis.watchdog
Restart=always
RestartSec=10
StartLimitBurst=1000
CPUQuota=5%
MemoryMax=50M
Nice=5

[Install]
WantedBy=default.target"

write_service "aicore-entities.service" "\
[Unit]
Description=Frank Entity Session Dispatcher (idle-driven)
After=aicore-core.service aicore-router.service
Wants=aicore-core.service aicore-router.service

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
ExecStart=$PYTHON_SYS $SCRIPT_DIR/services/entity_dispatcher.py
Restart=on-failure
RestartSec=60
Environment=PYTHONUNBUFFERED=1
Nice=15

[Install]
WantedBy=default.target"

# ── Tier 4: Entity oneshot services + timers (fallback, NOT enabled) ────────

for entity_info in \
    "therapist:Dr. Hibbert Therapist:services/therapist_scheduler.py:1200" \
    "mirror:Kairos Philosophical Mirror:services/mirror_scheduler.py:900" \
    "companion:Raven Companion:services/companion_scheduler.py:1200" \
    "atlas:Atlas Architecture Mentor:services/atlas_scheduler.py:900" \
    "muse:Echo Creative Muse:services/muse_scheduler.py:900"; do

    IFS=':' read -r ent_name ent_desc ent_script ent_timeout <<< "$entity_info"

    write_service "aicore-${ent_name}.service" "\
[Unit]
Description=${ent_desc} Session (one-shot)
After=aicore-core.service aicore-router.service
Wants=aicore-core.service aicore-router.service

[Service]
Type=oneshot
WorkingDirectory=$SCRIPT_DIR
ExecStart=$PYTHON_SYS $SCRIPT_DIR/${ent_script}
TimeoutStartSec=${ent_timeout}
Environment=PYTHONUNBUFFERED=1
Nice=15
RemainAfterExit=no"
done

# Entity timers (fallback — disabled by default, entity_dispatcher replaces these)
write_service "aicore-therapist.timer" "\
[Unit]
Description=Dr. Hibbert Therapist Timer (3x daily, LEGACY)

[Timer]
OnCalendar=*-*-* 09:00:00
OnCalendar=*-*-* 15:00:00
OnCalendar=*-*-* 21:00:00
RandomizedDelaySec=1800
Persistent=true

[Install]
WantedBy=timers.target"

write_service "aicore-mirror.timer" "\
[Unit]
Description=Kairos Mirror Timer (1x daily, LEGACY)

[Timer]
OnCalendar=*-*-* 13:00:00
RandomizedDelaySec=1800
Persistent=true

[Install]
WantedBy=timers.target"

write_service "aicore-companion.timer" "\
[Unit]
Description=Raven Companion Timer (1x daily, LEGACY)

[Timer]
OnCalendar=*-*-* 18:00:00
RandomizedDelaySec=1800
Persistent=true

[Install]
WantedBy=timers.target"

write_service "aicore-atlas.timer" "\
[Unit]
Description=Atlas Mentor Timer (1x daily, LEGACY)

[Timer]
OnCalendar=*-*-* 11:00:00
RandomizedDelaySec=1800
Persistent=true

[Install]
WantedBy=timers.target"

write_service "aicore-muse.timer" "\
[Unit]
Description=Echo Muse Timer (1x daily, LEGACY)

[Timer]
OnCalendar=*-*-* 16:00:00
RandomizedDelaySec=1800
Persistent=true

[Install]
WantedBy=timers.target"

# ── Tier 5: Scheduled tasks ────────────────────────────────────────────────

write_service "aicore-fas.service" "\
[Unit]
Description=F.A.S. - Frank's Autonomous Scavenger
After=network.target

[Service]
Type=oneshot
ExecStart=$PYTHON_SYS $SCRIPT_DIR/tools/fas_scavenger.py run
WorkingDirectory=$SCRIPT_DIR/tools
Environment=PYTHONPATH=$SCRIPT_DIR
StandardOutput=append:/tmp/fas.log
StandardError=append:/tmp/fas.log
Nice=19
IOSchedulingClass=idle

[Install]
WantedBy=default.target"

write_service "aicore-fas.timer" "\
[Unit]
Description=F.A.S. Timer - Runs during night hours (02:00-06:00)

[Timer]
OnCalendar=*-*-* 02:00:00
OnCalendar=*-*-* 03:00:00
OnCalendar=*-*-* 04:00:00
OnCalendar=*-*-* 05:00:00
OnCalendar=*-*-* 06:00:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target"

# ── Reload and enable services ──────────────────────────────────────────────

systemctl --user daemon-reload

# Tier 1 — Infrastructure
systemctl --user enable aicore-router.service 2>/dev/null || true
systemctl --user enable aicore-core.service 2>/dev/null || true
systemctl --user enable aicore-llama3-gpu.service 2>/dev/null || true
systemctl --user enable aicore-modeld.service 2>/dev/null || true
systemctl --user enable aicore-toolboxd.service 2>/dev/null || true
systemctl --user enable aicore-webd.service 2>/dev/null || true
systemctl --user enable aicore-ingestd.service 2>/dev/null || true
systemctl --user enable aicore-whisper-gpu.service 2>/dev/null || true
# NOTE: aicore-qwen-gpu NOT enabled (on-demand via Router)

# Tier 2 — System daemons
systemctl --user enable aicore-desktopd.service 2>/dev/null || true
systemctl --user enable aicore-consciousness.service 2>/dev/null || true
systemctl --user enable aicore-voice.service 2>/dev/null || true
systemctl --user enable aicore-gaming-mode.service 2>/dev/null || true
systemctl --user enable aicore-asrs.service 2>/dev/null || true
systemctl --user enable aicore-invariants.service 2>/dev/null || true

# Tier 3 — Autonomous
systemctl --user enable aicore-genesis.service 2>/dev/null || true
systemctl --user enable aicore-genesis-watchdog.service 2>/dev/null || true
systemctl --user enable aicore-entities.service 2>/dev/null || true

# Tier 5 — Scheduled
systemctl --user enable aicore-fas.timer 2>/dev/null || true

# Entity timers NOT enabled (entity_dispatcher handles scheduling)
echo "  Done. ($(ls "$SYSTEMD_USER_DIR"/aicore-*.service 2>/dev/null | wc -l) services installed)"

# ============================================================================
# [13/13] Desktop entries & dock icons
# ============================================================================
echo "[13/13] Creating desktop entries..."
APPS_DIR="$HOME/.local/share/applications"
ICONS_DIR="$HOME/.local/share/icons/hicolor"
mkdir -p "$APPS_DIR" "$ICONS_DIR/48x48/apps" "$ICONS_DIR/256x256/apps"

# Install icons
cp "$SCRIPT_DIR/assets/icons/frank-overlay.svg" "$ICONS_DIR/48x48/apps/frank-overlay.svg" 2>/dev/null || true
cp "$SCRIPT_DIR/assets/icons/frank-writer.png"  "$ICONS_DIR/256x256/apps/frank-writer.png" 2>/dev/null || true

# Make launcher scripts executable
chmod +x "$SCRIPT_DIR/ui/frank_overlay_launcher.sh" 2>/dev/null || true
chmod +x "$SCRIPT_DIR/writer/start_writer.sh" 2>/dev/null || true

# Frank Overlay .desktop
cat > "$APPS_DIR/frank-overlay.desktop" <<DESKTOP
[Desktop Entry]
Name=Frank
Comment=Frank AI Overlay — local AI desktop companion
Exec=$SCRIPT_DIR/ui/frank_overlay_launcher.sh
Icon=$ICONS_DIR/48x48/apps/frank-overlay.svg
Terminal=false
Type=Application
Categories=Utility;
StartupNotify=false
DESKTOP

# Frank Writer .desktop
cat > "$APPS_DIR/frank-writer.desktop" <<DESKTOP
[Desktop Entry]
Name=Frank Writer
Comment=AI-native document and code editor
Exec=$SCRIPT_DIR/writer/start_writer.sh
Icon=$ICONS_DIR/256x256/apps/frank-writer.png
Terminal=false
Type=Application
Categories=Office;TextEditor;Development;
StartupNotify=true
StartupWMClass=org.frank.writer
DESKTOP

# Update icon cache
gtk-update-icon-cache "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

# Pin to GNOME dock
if command -v gsettings &>/dev/null; then
    CURRENT_FAVS=$(gsettings get org.gnome.shell favorite-apps 2>/dev/null || echo "[]")
    NEEDS_UPDATE=false

    if ! echo "$CURRENT_FAVS" | grep -q "frank-overlay.desktop"; then
        CURRENT_FAVS=$(echo "$CURRENT_FAVS" | sed "s/]$/, 'frank-overlay.desktop']/; s/\[, /[/")
        NEEDS_UPDATE=true
    fi
    if ! echo "$CURRENT_FAVS" | grep -q "frank-writer.desktop"; then
        CURRENT_FAVS=$(echo "$CURRENT_FAVS" | sed "s/]$/, 'frank-writer.desktop']/; s/\[, /[/")
        NEEDS_UPDATE=true
    fi

    if $NEEDS_UPDATE; then
        gsettings set org.gnome.shell favorite-apps "$CURRENT_FAVS" 2>/dev/null && \
            echo "  Pinned Frank & Writer to dock." || \
            echo "  Note: Could not pin to dock."
    else
        echo "  Already pinned to dock."
    fi
fi
echo "  Done."

# ============================================================================
# Summary
# ============================================================================
echo
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                 Installation Complete                       ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo
echo "  GPU Backend:     $GPU_BACKEND ($GPU_NAME)"
echo "  RAM:             ${RAM_MB} MB"
echo "  Models:          $MODELS_DIR"
echo "  Voices:          $VOICES_DIR (Piper DE) + $KOKORO_DIR (Kokoro EN)"
echo "  Venv (main):     $VENV_DIR"
echo "  Venv (ingestd):  $VENV_INGESTD"
echo
echo "  Start all services:"
echo "    systemctl --user start aicore-router aicore-core aicore-llama3-gpu"
echo "    systemctl --user start aicore-modeld aicore-toolboxd aicore-webd"
echo "    systemctl --user start aicore-whisper-gpu aicore-voice"
echo "    systemctl --user start aicore-consciousness aicore-entities"
echo
echo "  Start the overlay:"
echo "    $SCRIPT_DIR/ui/frank_overlay_launcher.sh"
echo
echo "  View logs:"
echo "    journalctl --user -u aicore-core -f"
echo
echo "  Ports:"
echo "    8091 Router | 8088 Core | 8101 Llama3 | 8102 Qwen (on-demand)"
echo "    8103 Whisper | 8096 Toolbox | 8094 Ingestd | 11434 Ollama"
echo
