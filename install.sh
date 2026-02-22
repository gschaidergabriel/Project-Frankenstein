#!/usr/bin/env bash
# ============================================================================
# AI-Core / Frank — Installation Script
# ============================================================================
# Usage:  ./install.sh [--no-models] [--cpu-only] [--no-build] [--force]
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
#   13. Creates desktop entries, dock icons, wallpaper, autostart
#   14. Starts all services
# ============================================================================

set -euo pipefail

# --- Parse arguments ---
NO_MODELS=false
CPU_ONLY=false
NO_BUILD=false
FORCE=false
for arg in "$@"; do
    case "$arg" in
        --no-models) NO_MODELS=true ;;
        --cpu-only)  CPU_ONLY=true ;;
        --no-build)  NO_BUILD=true ;;
        --force)     FORCE=true ;;
        --help|-h)
            echo "Usage: ./install.sh [--no-models] [--cpu-only] [--no-build] [--force]"
            echo "  --no-models   Skip downloading LLM / voice model files"
            echo "  --cpu-only    Force CPU-only mode (no GPU acceleration)"
            echo "  --no-build    Skip building llama.cpp and whisper.cpp from source"
            echo "  --force       Overwrite existing service files (for reinstall/update)"
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
# [1/14] System requirements check
# ============================================================================
echo "[1/14] Checking system requirements..."
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
# [2/14] System dependencies
# ============================================================================
echo "[2/14] Installing system dependencies..."
sudo apt-get update -qq

# Core system packages
sudo apt-get install -y -qq \
    python3 python3-venv python3-pip python3-tk python3-dev \
    build-essential cmake pkg-config meson \
    xdotool wmctrl x11-utils x11-xserver-utils xprintidle \
    tesseract-ocr \
    pulseaudio-utils \
    curl wget git jq lsof zstd \
    firejail \
    libnotify-bin \
    libgirepository1.0-dev gir1.2-appindicator3-0.1 \
    libdbus-1-dev libglib2.0-dev \
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

# QR code scanning (pyzbar C backend) + screenshots
sudo apt-get install -y -qq \
    libzbar0 maim \
    2>/dev/null

echo "  Done."

# ============================================================================
# [3/14] GPU detection
# ============================================================================
echo "[3/14] Detecting GPU..."
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
# [4/14] Python venv (main)
# ============================================================================
echo "[4/14] Setting up main Python virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q
pip install -r "$SCRIPT_DIR/requirements.txt" -q
deactivate
echo "  Done. ($(python3 --version))"

# ============================================================================
# [5/14] Python venv (ingestd)
# ============================================================================
echo "[5/14] Setting up ingestd virtual environment..."
if [ ! -d "$VENV_INGESTD" ]; then
    python3 -m venv "$VENV_INGESTD"
fi
source "$VENV_INGESTD/bin/activate"
pip install --upgrade pip -q
pip install -q \
    faster-whisper uvicorn fastapi httpx Pillow lxml \
    coloredlogs annotated-doc \
    python-multipart pypdf python-docx
deactivate
echo "  Done."

# ============================================================================
# [6/14] Build llama.cpp
# ============================================================================
if $NO_BUILD; then
    echo "[6/14] Skipping llama.cpp build (--no-build)"
else
    echo "[6/14] Building llama.cpp..."
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
# [7/14] Build whisper.cpp
# ============================================================================
if $NO_BUILD; then
    echo "[7/14] Skipping whisper.cpp build (--no-build)"
else
    echo "[7/14] Building whisper.cpp..."
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
        mkdir -p "$WHISPER_DIR/models"
        if [ ! -f "$WHISPER_MODEL" ]; then
            echo "  Downloading Whisper medium model (~1.5 GB)..."
            # Try the bundled download script first, then direct URL fallback
            cd "$WHISPER_DIR"
            bash models/download-ggml-model.sh medium 2>/dev/null || {
                echo "  Script download failed, trying direct URL..."
                download_file \
                    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin" \
                    "$WHISPER_MODEL" \
                    "Whisper medium model (~1.5 GB)" || \
                    echo "  WARNING: Whisper model download failed. Place ggml-medium.bin in $WHISPER_DIR/models/"
            }
            cd "$SCRIPT_DIR"
        else
            echo "  Whisper medium model already present."
        fi
    fi
fi

# ============================================================================
# [8/14] Create data directories
# ============================================================================
echo "[8/14] Creating data directories..."
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
# [9/14] Install Ollama + pull vision models
# ============================================================================
echo "[9/14] Installing Ollama (local vision inference)..."
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
# [10/14] Download LLM models (GGUF)
# ============================================================================
if $NO_MODELS; then
    echo "[10/14] Skipping model downloads (--no-models)"
else
    echo "[10/14] Downloading LLM models..."
    mkdir -p "$MODELS_DIR"

    LLAMA_URL="https://huggingface.co/mlabonne/Meta-Llama-3.1-8B-Instruct-abliterated-GGUF/resolve/main/meta-llama-3.1-8b-instruct-abliterated.Q4_K_M.gguf"
    QWEN_URL="https://huggingface.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf"

    download_file "$LLAMA_URL" \
        "$MODELS_DIR/Meta-Llama-3.1-8B-Instruct-abliterated-Q4_K_M.gguf" \
        "Llama 3.1 8B abliterated (Q4_K_M, ~4.6 GB)"

    download_file "$QWEN_URL" \
        "$MODELS_DIR/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf" \
        "Qwen 2.5 Coder 7B (Q4_K_M, ~4.7 GB)"
fi

# ============================================================================
# [11/14] Voice / TTS setup
# ============================================================================
if $NO_MODELS; then
    echo "[11/14] Skipping voice model downloads (--no-models)"
else
    echo "[11/14] Setting up Voice / TTS..."
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
# [12/14] Systemd user services
# ============================================================================
echo "[12/14] Installing systemd user services..."
mkdir -p "$SYSTEMD_USER_DIR"

LLAMA_SERVER="$LLAMA_DIR/build/bin/llama-server"
WHISPER_SERVER="$WHISPER_DIR/build/bin/whisper-server"
PYTHON_SYS="/usr/bin/python3"
PYTHON_VENV="$VENV_DIR/bin/python3"
PYTHON_INGESTD="$VENV_INGESTD/bin/python3"

# Helper: write a service file (overwrites if --force is set)
write_service() {
    local name="$1"
    local content="$2"
    local target="$SYSTEMD_USER_DIR/${name}"
    if $FORCE || [ ! -f "$target" ]; then
        printf '%s\n' "$content" > "$target"
        if $FORCE && [ -f "$target" ]; then
            echo "  Updated $name"
        else
            echo "  Created $name"
        fi
    else
        echo "  $name already exists (use --force to overwrite)"
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
Environment=PYTHONPATH=$SCRIPT_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$PYTHON_SYS $SCRIPT_DIR/core/app.py
Restart=always
RestartSec=1

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
    --model $MODELS_DIR/Meta-Llama-3.1-8B-Instruct-abliterated-Q4_K_M.gguf \\
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
Environment=PYTHONPATH=$SCRIPT_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$PYTHON_SYS $SCRIPT_DIR/modeld/app.py
Restart=always
RestartSec=1

[Install]
WantedBy=default.target"

write_service "aicore-toolboxd.service" "\
[Unit]
Description=AI Core toolboxd (local tools API)
After=network.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
Environment=PYTHONPATH=$SCRIPT_DIR
Environment=AICORE_TOOLBOX_PORT=8096
Environment=DISPLAY=:0
ExecStart=$PYTHON_SYS -u $SCRIPT_DIR/tools/toolboxd.py
Restart=always
RestartSec=0.5

[Install]
WantedBy=default.target"

write_service "aicore-webd.service" "\
[Unit]
Description=AI Core web search daemon (DuckDuckGo HTML)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
Environment=PYTHONPATH=$SCRIPT_DIR
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
Environment=PYTHONPATH=$SCRIPT_DIR
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
WorkingDirectory=$SCRIPT_DIR
Environment=PYTHONPATH=$SCRIPT_DIR
Environment=DISPLAY=:0
Environment=XAUTHORITY=%h/.Xauthority
ExecStart=$PYTHON_SYS $SCRIPT_DIR/desktopd/app.py
Restart=always
RestartSec=1

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
Environment=PYTHONPATH=$SCRIPT_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$PYTHON_SYS $SCRIPT_DIR/services/consciousness_daemon.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target"

write_service "aicore-gaming-mode.service" "\
[Unit]
Description=AI Core Gaming Mode Daemon
After=aicore-llama3-gpu.service aicore-qwen-gpu.service

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
Environment=PYTHONPATH=$SCRIPT_DIR
Environment=DISPLAY=:0
ExecStart=$PYTHON_SYS $SCRIPT_DIR/gaming/gaming_mode.py --daemon
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target"

write_service "aicore-asrs.service" "\
[Unit]
Description=A.S.R.S. - Autonomous Safety Recovery System
After=aicore-core.service

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
Environment=PYTHONPATH=$SCRIPT_DIR
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

# ── Frank Overlay (Chat UI) ────────────────────────────────────────────────

write_service "frank-overlay.service" "\
[Unit]
Description=Frank Chat Overlay
After=aicore-core.service aicore-router.service
Wants=aicore-core.service aicore-router.service

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR/ui
Environment=PYTHONPATH=$SCRIPT_DIR
Environment=PYTHONUNBUFFERED=1
Environment=DISPLAY=:0
Environment=XAUTHORITY=%h/.Xauthority
ExecStart=$PYTHON_VENV $SCRIPT_DIR/ui/chat_overlay.py
Restart=on-failure
RestartSec=3

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
Environment=PYTHONPATH=$SCRIPT_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$PYTHON_SYS $SCRIPT_DIR/services/entity_dispatcher.py
Restart=on-failure
RestartSec=60
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
Environment=PYTHONPATH=$SCRIPT_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$PYTHON_SYS $SCRIPT_DIR/${ent_script}
TimeoutStartSec=${ent_timeout}
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

systemctl --user daemon-reload 2>/dev/null || echo "  Note: systemctl --user daemon-reload failed (no user bus?). Run manually after install."

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
# Voice daemon removed — PTT uses Whisper server directly
systemctl --user enable aicore-gaming-mode.service 2>/dev/null || true
systemctl --user enable aicore-asrs.service 2>/dev/null || true
systemctl --user enable aicore-invariants.service 2>/dev/null || true
systemctl --user enable frank-overlay.service 2>/dev/null || true

# Tier 3 — Autonomous
systemctl --user enable aicore-genesis.service 2>/dev/null || true
systemctl --user enable aicore-genesis-watchdog.service 2>/dev/null || true
systemctl --user enable aicore-entities.service 2>/dev/null || true

# Tier 5 — Scheduled
systemctl --user enable aicore-fas.timer 2>/dev/null || true

# Entity timers NOT enabled (entity_dispatcher handles scheduling)
echo "  Done. ($(ls "$SYSTEMD_USER_DIR"/aicore-*.service 2>/dev/null | wc -l) services installed)"

# ============================================================================
# [13/14] Desktop entries & dock icons
# ============================================================================
echo "[13/14] Creating desktop entries..."
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

# ── GNOME desktop configuration ──
if command -v gsettings &>/dev/null; then
    echo "  Configuring GNOME desktop..."

    # Dark mode
    gsettings set org.gnome.desktop.interface color-scheme 'prefer-dark' 2>/dev/null || true

    # Dock: left side, extended, fixed icon size
    gsettings set org.gnome.shell.extensions.dash-to-dock dock-position 'LEFT' 2>/dev/null || true
    gsettings set org.gnome.shell.extensions.dash-to-dock extend-height true 2>/dev/null || true
    gsettings set org.gnome.shell.extensions.dash-to-dock dash-max-icon-size 48 2>/dev/null || true
    gsettings set org.gnome.shell.extensions.dash-to-dock icon-size-fixed true 2>/dev/null || true

    # Pin Frank & Writer to dock
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

# Generate & set FRANK wallpaper (resolution-adaptive)
LOGO_SRC="$SCRIPT_DIR/assets/frank_logo.png"
WALLPAPER_OUT="$SCRIPT_DIR/assets/wallpaper_frank.png"
if [ -f "$LOGO_SRC" ] && command -v gsettings &>/dev/null; then
    # Use venv Python which has Pillow installed (system python3 may not)
    WALLPAPER_PYTHON="$PYTHON_VENV"
    [ -x "$WALLPAPER_PYTHON" ] || WALLPAPER_PYTHON=python3

    "$WALLPAPER_PYTHON" - "$LOGO_SRC" "$WALLPAPER_OUT" << 'PYGEN' || echo "  WARNING: Wallpaper generation failed (Pillow missing?). Skipping."
import sys, subprocess
from PIL import Image

logo_path, out_path = sys.argv[1], sys.argv[2]

# Detect screen resolution via xrandr (primary monitor)
screen_w, screen_h = 1920, 1080
try:
    out = subprocess.check_output(["xrandr", "--current"], text=True)
    for line in out.splitlines():
        if " connected " in line and "primary" in line:
            for part in line.split():
                if "x" in part and "+" in part:
                    res = part.split("+")[0]
                    screen_w, screen_h = map(int, res.split("x"))
                    break
            break
    else:
        # No primary? Use first connected monitor
        for line in out.splitlines():
            if " connected " in line:
                for part in line.split():
                    if "x" in part and "+" in part:
                        res = part.split("+")[0]
                        screen_w, screen_h = map(int, res.split("x"))
                        break
                break
except Exception:
    pass

# Overlay left reservation: GNOME dock (~66px) + Frank default width (~420px)
overlay_right = 486
visible_w = max(screen_w - overlay_right, 200)

# Load logo, scale to ~27% of visible width (keeps it tasteful)
logo = Image.open(logo_path).convert("RGBA")
target_w = int(visible_w * 0.27)
scale = target_w / logo.size[0]
target_h = int(logo.size[1] * scale)
logo_small = logo.resize((target_w, target_h), Image.LANCZOS)

# Center in visible area, vertically centered
cx = overlay_right + (visible_w - target_w) // 2
cy = (screen_h - target_h) // 2

canvas = Image.new("RGB", (screen_w, screen_h), (0, 0, 0))
canvas.paste(logo_small, (cx, cy), logo_small)
canvas.save(out_path, "PNG")
print(f"  Wallpaper: {screen_w}x{screen_h}, logo at ({cx},{cy}) {target_w}x{target_h}")
PYGEN
    if [ -f "$WALLPAPER_OUT" ]; then
        gsettings set org.gnome.desktop.background picture-uri "file://$WALLPAPER_OUT" 2>/dev/null
        gsettings set org.gnome.desktop.background picture-uri-dark "file://$WALLPAPER_OUT" 2>/dev/null
        gsettings set org.gnome.desktop.background picture-options "zoom" 2>/dev/null
        echo "  FRANK wallpaper set."
    fi
fi

# Overlay autostart (XDG autostart — starts overlay on login)
AUTOSTART_DIR="$HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"
cat > "$AUTOSTART_DIR/frank-overlay.desktop" <<AUTOSTART
[Desktop Entry]
Name=Frank Overlay
Comment=Start Frank AI Overlay on login
Exec=$SCRIPT_DIR/ui/frank_overlay_launcher.sh
Icon=$ICONS_DIR/48x48/apps/frank-overlay.svg
Terminal=false
Type=Application
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=5
AUTOSTART
echo "  Overlay autostart installed."

echo "  Done."

# ============================================================================
# [14/14] Start all services
# ============================================================================
echo "[14/14] Starting all services..."

# Stop any existing overlay (clean state)
pkill -f chat_overlay.py 2>/dev/null || true
rm -f /tmp/frank_overlay.lock 2>/dev/null || true

# Start infrastructure first
systemctl --user start aicore-router.service 2>/dev/null || true
sleep 1
systemctl --user start aicore-core.service 2>/dev/null || true
systemctl --user start aicore-llama3-gpu.service 2>/dev/null || true
systemctl --user start aicore-modeld.service 2>/dev/null || true
systemctl --user start aicore-toolboxd.service 2>/dev/null || true
systemctl --user start aicore-webd.service 2>/dev/null || true
systemctl --user start aicore-ingestd.service 2>/dev/null || true
systemctl --user start aicore-whisper-gpu.service 2>/dev/null || true

# System daemons
systemctl --user start aicore-desktopd.service 2>/dev/null || true
systemctl --user start aicore-consciousness.service 2>/dev/null || true
systemctl --user start aicore-gaming-mode.service 2>/dev/null || true
systemctl --user start aicore-asrs.service 2>/dev/null || true
systemctl --user start aicore-invariants.service 2>/dev/null || true

# Autonomous
systemctl --user start aicore-genesis.service 2>/dev/null || true
systemctl --user start aicore-genesis-watchdog.service 2>/dev/null || true
systemctl --user start aicore-entities.service 2>/dev/null || true

# Start the overlay via systemd
systemctl --user start frank-overlay.service 2>/dev/null || true

# Count running services
sleep 2
RUNNING=$( (systemctl --user list-units 'aicore-*' --state=running --no-pager --no-legend 2>/dev/null || true) | wc -l)
echo "  $RUNNING services running."
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
echo "  Services:        $RUNNING running"
echo
echo "  All services are already started."
echo
echo "  Manage services:"
echo "    systemctl --user status aicore-core"
echo "    journalctl --user -u aicore-core -f"
echo
echo "  Restart overlay:"
echo "    systemctl --user restart frank-overlay.service"
echo
echo "  Ports:"
echo "    8091 Router | 8088 Core | 8101 Llama3 | 8102 Qwen (on-demand)"
echo "    8103 Whisper | 8096 Toolbox | 8094 Ingestd | 11434 Ollama"
echo
