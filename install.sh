#!/usr/bin/env bash
# ============================================================================
# AI-Core / Frank — Installation Script
# ============================================================================
# Usage:  ./install.sh [--no-models] [--cpu-only]
#
# This script:
#   1. Installs system dependencies (apt)
#   2. Creates a Python venv and installs pip packages
#   3. Detects your GPU and configures the backend
#   4. Downloads default LLM models (unless --no-models)
#   5. Installs Ollama (for vision models)
#   6. Creates data directories
#   7. Installs systemd user services
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

# --- 1. System dependencies ---
echo "[1/7] Installing system dependencies..."
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

# --- 2. GPU detection ---
echo "[2/7] Detecting GPU..."
if $CPU_ONLY; then
    echo "  CPU-only mode (forced)"
    GPU_BACKEND="cpu"
else
    # Quick detection
    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
        GPU_BACKEND="cuda"
        GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)
        echo "  NVIDIA GPU detected: $GPU_NAME (CUDA)"
    elif lspci -d 1002: 2>/dev/null | grep -qi "VGA\|Display"; then
        GPU_BACKEND="vulkan"
        GPU_NAME=$(lspci -d 1002: 2>/dev/null | grep -i "VGA\|Display" | sed 's/.*: //')
        echo "  AMD GPU detected: $GPU_NAME (Vulkan)"
        # Install Vulkan deps for AMD
        sudo apt-get install -y -qq mesa-vulkan-drivers vulkan-tools 2>/dev/null || true
    elif lspci -d 8086: 2>/dev/null | grep -qi "VGA\|Display"; then
        GPU_BACKEND="vulkan"
        GPU_NAME=$(lspci -d 8086: 2>/dev/null | grep -i "VGA\|Display" | sed 's/.*: //')
        echo "  Intel GPU detected: $GPU_NAME (Vulkan)"
        sudo apt-get install -y -qq mesa-vulkan-drivers vulkan-tools 2>/dev/null || true
    else
        GPU_BACKEND="cpu"
        echo "  No GPU detected, using CPU-only mode"
    fi
fi

# --- 3. Python venv ---
echo "[3/7] Setting up Python virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q
pip install -r "$SCRIPT_DIR/requirements.txt" -q
echo "  Done. ($(python3 --version))"

# --- 4. Create data directories ---
echo "[4/7] Creating data directories..."
python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
from config.paths import ensure_dirs
ensure_dirs()
print('  Done.')
"

# --- 5. Install Ollama ---
echo "[5/7] Installing Ollama (local LLM inference)..."
if command -v ollama &>/dev/null; then
    echo "  Ollama already installed ($(ollama --version 2>/dev/null || echo 'unknown version'))"
else
    curl -fsSL https://ollama.com/install.sh | sh
    echo "  Ollama installed."
fi

# Configure Ollama for detected GPU
if [ "$GPU_BACKEND" = "vulkan" ]; then
    # Create systemd override for Ollama with Vulkan
    OLLAMA_OVERRIDE_DIR="/etc/systemd/system/ollama.service.d"
    if [ ! -f "$OLLAMA_OVERRIDE_DIR/vulkan.conf" ]; then
        sudo mkdir -p "$OLLAMA_OVERRIDE_DIR"
        echo -e "[Service]\nEnvironment=OLLAMA_VULKAN=1" | sudo tee "$OLLAMA_OVERRIDE_DIR/vulkan.conf" >/dev/null
        sudo systemctl daemon-reload
        echo "  Configured Ollama for Vulkan GPU acceleration."
    fi
fi

# Start Ollama
sudo systemctl enable ollama 2>/dev/null || true
sudo systemctl start ollama 2>/dev/null || true

# --- 6. Download models ---
if $NO_MODELS; then
    echo "[6/7] Skipping model download (--no-models)"
else
    echo "[6/7] Downloading default models..."
    mkdir -p "$MODELS_DIR"

    # Pull Ollama models (for vision)
    echo "  Pulling LLaVA 7B (vision)..."
    ollama pull llava:7b 2>/dev/null || echo "  Warning: Could not pull llava:7b"
    echo "  Pulling Moondream (lightweight vision fallback)..."
    ollama pull moondream 2>/dev/null || echo "  Warning: Could not pull moondream"

    # llama.cpp GGUF models (download if not present)
    LLAMA_URL="https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf"
    QWEN_URL="https://huggingface.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf"

    if [ ! -f "$MODELS_DIR/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf" ]; then
        echo "  Downloading Llama 3.1 8B (Q4_K_M, ~4.9 GB)..."
        wget -q --show-progress -O "$MODELS_DIR/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf" "$LLAMA_URL" || \
            echo "  Warning: Download failed. You can manually place the model in $MODELS_DIR"
    else
        echo "  Llama 3.1 8B already present."
    fi

    if [ ! -f "$MODELS_DIR/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf" ]; then
        echo "  Downloading Qwen 2.5 Coder 7B (Q4_K_M, ~4.7 GB)..."
        wget -q --show-progress -O "$MODELS_DIR/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf" "$QWEN_URL" || \
            echo "  Warning: Download failed. You can manually place the model in $MODELS_DIR"
    else
        echo "  Qwen 2.5 Coder 7B already present."
    fi
fi

# --- 7. Install systemd user services ---
echo "[7/7] Installing systemd user services..."
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_USER_DIR"

# Generate service files from template
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
echo "  GPU Backend: $GPU_BACKEND"
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
