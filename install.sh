#!/usr/bin/env bash
# ============================================================================
# AI-Core / Frank — Installation Script
# ============================================================================
# Usage:  ./install.sh [--no-models] [--cpu-only]
#
# This script:
#   1. Checks system requirements (RAM, disk)
#   2. Installs system dependencies (apt)
#   3. Detects your GPU and configures the backend
#   4. Creates a Python venv and installs pip packages
#   5. Downloads default LLM models (unless --no-models)
#   6. Installs Ollama (for vision models)
#   7. Creates data directories
#   8. Installs systemd user services
# ============================================================================

set -euo pipefail

# --- Parse arguments ---
NO_MODELS=false
CPU_ONLY=false
for arg in "$@"; do
    case "$arg" in
        --no-models) NO_MODELS=true ;;
        --cpu-only)  CPU_ONLY=true ;;
        --help|-h)
            echo "Usage: ./install.sh [--no-models] [--cpu-only]"
            echo "  --no-models   Skip downloading LLM model files"
            echo "  --cpu-only    Force CPU-only mode (no GPU acceleration)"
            exit 0
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${AICORE_DATA:-$HOME/.local/share/frank}"
CONFIG_DIR="${AICORE_CONFIG:-$HOME/.config/frank}"
MODELS_DIR="${AICORE_MODELS_DIR:-$DATA_DIR/models}"
VENV_DIR="$(dirname "$SCRIPT_DIR")/venv"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              AI-Core / Frank — Installer                    ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo
echo "  Source:  $SCRIPT_DIR"
echo "  Data:    $DATA_DIR"
echo "  Config:  $CONFIG_DIR"
echo "  Models:  $MODELS_DIR"
echo "  Venv:    $VENV_DIR"
echo

# --- Helper: download with retry + optional checksum ---
download_model() {
    local url="$1"
    local file="$2"
    local label="$3"
    local expected_sha256="${4:-}"
    if [ -f "$file" ]; then
        echo "  $label already present."
        return 0
    fi
    echo "  Downloading $label..."
    wget -q --show-progress --tries=3 --timeout=60 -O "$file.tmp" "$url" && \
        mv "$file.tmp" "$file" || {
            rm -f "$file.tmp"
            echo "  Warning: Download failed after 3 attempts. Place the model manually in $MODELS_DIR"
            return 1
        }
    # Verify checksum if provided
    if [ -n "$expected_sha256" ] && [ -f "$file" ]; then
        echo "  Verifying checksum..."
        actual_sha256=$(sha256sum "$file" | awk '{print $1}')
        if [ "$actual_sha256" != "$expected_sha256" ]; then
            echo "  WARNING: Checksum mismatch for $label!"
            echo "    Expected: $expected_sha256"
            echo "    Got:      $actual_sha256"
            echo "  The file may be corrupted. Re-download manually if needed."
        else
            echo "  Checksum OK."
        fi
    fi
}

# --- 1. System requirements check ---
echo "[1/8] Checking system requirements..."
RAM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
# Check disk on the models target mountpoint (may differ from $HOME)
MODELS_PARENT="$(dirname "$MODELS_DIR")"
mkdir -p "$MODELS_PARENT" 2>/dev/null || true
DISK_FREE_MB=$(df -BM --output=avail "$MODELS_PARENT" 2>/dev/null | tail -1 | tr -d ' M')

echo "  RAM: ${RAM_MB} MB"
echo "  Disk free: ${DISK_FREE_MB} MB"

if [ "$RAM_MB" -lt 8000 ]; then
    echo "  WARNING: Less than 8 GB RAM detected. LLM inference will be very slow."
    echo "  Recommended: 16 GB+ for comfortable usage."
fi

if ! $NO_MODELS && [ "$DISK_FREE_MB" -lt 15000 ]; then
    echo "  WARNING: Less than 15 GB free disk space. Model downloads require ~12 GB."
    echo "  Consider using --no-models and downloading models later."
fi

# --- 2. System dependencies ---
echo "[2/8] Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3 python3-venv python3-pip python3-tk \
    xdotool wmctrl xprop xrandr \
    tesseract-ocr \
    pulseaudio-utils \
    curl wget git jq \
    libgirepository1.0-dev gir1.2-appindicator3-0.1 \
    2>/dev/null
echo "  Done."

# --- 3. GPU detection ---
echo "[3/8] Detecting GPU..."
GPU_NAME="none"
if $CPU_ONLY; then
    echo "  CPU-only mode (forced)"
    GPU_BACKEND="cpu"
else
    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
        GPU_BACKEND="cuda"
        GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)
        echo "  NVIDIA GPU detected: $GPU_NAME (CUDA)"
    elif lspci -d 1002: 2>/dev/null | grep -qi "VGA\|Display"; then
        GPU_BACKEND="vulkan"
        GPU_NAME=$(lspci -d 1002: 2>/dev/null | grep -i "VGA\|Display" | sed 's/.*: //')
        echo "  AMD GPU detected: $GPU_NAME (Vulkan)"
        # Full Vulkan stack for AMD (RADV is the performant open-source driver)
        sudo apt-get install -y -qq libvulkan1 mesa-vulkan-drivers vulkan-tools 2>/dev/null || true
    elif lspci -d 8086: 2>/dev/null | grep -qi "VGA\|Display"; then
        GPU_BACKEND="vulkan"
        GPU_NAME=$(lspci -d 8086: 2>/dev/null | grep -i "VGA\|Display" | sed 's/.*: //')
        echo "  Intel GPU detected: $GPU_NAME (Vulkan)"
        sudo apt-get install -y -qq libvulkan1 mesa-vulkan-drivers vulkan-tools 2>/dev/null || true
    else
        GPU_BACKEND="cpu"
        echo "  No GPU detected, using CPU-only mode"
    fi
fi

# --- 4. Python venv ---
echo "[4/8] Setting up Python virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q
pip install -r "$SCRIPT_DIR/requirements.txt" -q
echo "  Done. ($(python3 --version))"

# --- 5. Create data directories ---
echo "[5/8] Creating data directories..."
python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
from config.paths import ensure_dirs
ensure_dirs()
print('  Done.')
"

# Copy example config if no user config exists
if [ ! -f "$CONFIG_DIR/config.yaml" ] && [ -f "$SCRIPT_DIR/config.yaml.example" ]; then
    mkdir -p "$CONFIG_DIR"
    cp "$SCRIPT_DIR/config.yaml.example" "$CONFIG_DIR/config.yaml"
    echo "  Copied config.yaml.example -> $CONFIG_DIR/config.yaml"
fi

# --- 6. Install Ollama ---
echo "[6/8] Installing Ollama (local LLM inference)..."
if command -v ollama &>/dev/null; then
    echo "  Ollama already installed ($(ollama --version 2>/dev/null || echo 'unknown version'))"
else
    curl -fsSL https://ollama.com/install.sh | sh
    echo "  Ollama installed."
fi

# Configure Ollama for detected GPU
if [ "$GPU_BACKEND" = "vulkan" ]; then
    OLLAMA_OVERRIDE_DIR="/etc/systemd/system/ollama.service.d"
    if [ ! -f "$OLLAMA_OVERRIDE_DIR/vulkan.conf" ] 2>/dev/null; then
        if sudo mkdir -p "$OLLAMA_OVERRIDE_DIR" 2>/dev/null; then
            echo -e "[Service]\nEnvironment=OLLAMA_VULKAN=1" | sudo tee "$OLLAMA_OVERRIDE_DIR/vulkan.conf" >/dev/null
            sudo systemctl daemon-reload
            echo "  Configured Ollama for Vulkan GPU acceleration."
        else
            echo "  Note: Could not create systemd override. Set OLLAMA_VULKAN=1 manually."
        fi
    fi
fi

# Start Ollama
sudo systemctl enable ollama 2>/dev/null || true
sudo systemctl start ollama 2>/dev/null || true
# Wait for Ollama to be ready
OLLAMA_READY=false
for i in $(seq 1 15); do
    if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
        OLLAMA_READY=true
        break
    fi
    sleep 1
done
if ! $OLLAMA_READY; then
    echo "  WARNING: Ollama did not respond after 15s. Check: sudo systemctl status ollama"
fi

# --- 7. Download models ---
if $NO_MODELS; then
    echo "[7/8] Skipping model download (--no-models)"
else
    echo "[7/8] Downloading default models..."
    mkdir -p "$MODELS_DIR"

    # Pull Ollama models (for vision)
    echo "  Pulling LLaVA 7B (vision)..."
    ollama pull llava:7b 2>/dev/null || echo "  Warning: Could not pull llava:7b"
    echo "  Pulling Moondream (lightweight vision fallback)..."
    ollama pull moondream 2>/dev/null || echo "  Warning: Could not pull moondream"

    # llama.cpp GGUF models
    LLAMA_URL="https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf"
    QWEN_URL="https://huggingface.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf"

    download_model "$LLAMA_URL" "$MODELS_DIR/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf" "Llama 3.1 8B (Q4_K_M, ~4.9 GB)"
    download_model "$QWEN_URL" "$MODELS_DIR/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf" "Qwen 2.5 Coder 7B (Q4_K_M, ~4.7 GB)"
fi

# --- 8. Install systemd user services ---
echo "[8/8] Installing systemd user services..."
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_USER_DIR"

PYTHON_BIN="$VENV_DIR/bin/python3"
COMMON_ENV="Environment=PYTHONUNBUFFERED=1\nEnvironment=PYTHONPATH=$SCRIPT_DIR\nEnvironment=DISPLAY=:0"

if [ "$GPU_BACKEND" = "vulkan" ]; then
    GPU_ENV="\nEnvironment=GGML_VULKAN_DEVICE=0"
elif [ "$GPU_BACKEND" = "cuda" ]; then
    GPU_ENV=""
else
    GPU_ENV=""
fi

# Core services
for svc in router core gateway toolboxd webd desktopd modeld; do
    SVC_FILE="$SYSTEMD_USER_DIR/aicore-${svc}.service"
    if [ ! -f "$SVC_FILE" ]; then
        case "$svc" in
            router)
                EXEC="$PYTHON_BIN -m uvicorn router.app:app --host 127.0.0.1 --port 8091"
                ;;
            core)
                EXEC="$PYTHON_BIN $SCRIPT_DIR/core/app.py"
                ;;
            gateway)
                EXEC="$PYTHON_BIN -m uvicorn gateway.app:app --host 127.0.0.1 --port 8089"
                ;;
            toolboxd)
                EXEC="$PYTHON_BIN $SCRIPT_DIR/tools/toolboxd.py"
                ;;
            webd)
                EXEC="$PYTHON_BIN -m uvicorn webd.app:app --host 127.0.0.1 --port 8093"
                ;;
            desktopd)
                EXEC="$PYTHON_BIN $SCRIPT_DIR/desktopd/app.py"
                ;;
            modeld)
                EXEC="$PYTHON_BIN $SCRIPT_DIR/modeld/app.py"
                ;;
        esac

        cat > "$SVC_FILE" <<UNIT
[Unit]
Description=AI-Core ${svc}
After=network.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
ExecStart=$EXEC
$(echo -e "$COMMON_ENV")
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UNIT
        echo "  Created $SVC_FILE"
    fi
done

systemctl --user daemon-reload
echo "  Done."

# --- Summary ---
echo
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                 Installation Complete                       ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo
echo "  GPU Backend: $GPU_BACKEND ($GPU_NAME)"
echo "  RAM:         ${RAM_MB} MB"
echo "  Data:        $DATA_DIR"
echo "  Models:      $MODELS_DIR"
echo
echo "  Start all services:"
echo "    systemctl --user start aicore-router aicore-core aicore-toolboxd"
echo
echo "  Start the overlay:"
echo "    $PYTHON_BIN $SCRIPT_DIR/ui/chat_overlay.py"
echo
echo "  View logs:"
echo "    journalctl --user -u aicore-router -f"
echo
