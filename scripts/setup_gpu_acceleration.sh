#!/bin/bash
# =============================================================================
# AI-Core GPU Acceleration Setup
# Build llama.cpp with Vulkan GPU acceleration (auto-detects GPU)
# =============================================================================

set -e

echo "=============================================="
echo " AI-Core GPU Acceleration Setup"
echo " Hardware: auto-detected GPU"
echo "=============================================="
echo ""

# Farben
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

AICORE_BASE="${AICORE_BASE:-$HOME/aicore}"
LLAMA_DIR="${AICORE_BASE}/opt/llama.cpp"
BACKUP_DIR="${AICORE_BASE}/opt/llama.cpp.backup.$(date +%Y%m%d_%H%M%S)"

# Step 1: Install dependencies
echo -e "${YELLOW}[1/6] Installing Vulkan development packages...${NC}"
sudo apt-get update
sudo apt-get install -y \
    libvulkan-dev \
    vulkan-tools \
    glslang-tools \
    glslang-dev \
    spirv-tools \
    cmake \
    build-essential \
    pkg-config

echo -e "${GREEN}Dependencies installed.${NC}"

# Step 1b: Ensure user is in video and render groups for GPU access
echo ""
echo -e "${YELLOW}[1b/6] Ensuring GPU device permissions...${NC}"
CURRENT_USER=$(whoami)
if ! groups "$CURRENT_USER" | grep -qE "\b(video|render)\b"; then
    echo "Adding $CURRENT_USER to video and render groups..."
    sudo usermod -aG video,render "$CURRENT_USER"
    echo -e "${GREEN}User added to GPU groups.${NC}"
    echo -e "${YELLOW}NOTE: You may need to logout/login or reboot for group changes to take effect.${NC}"
else
    echo -e "${GREEN}User already in video/render groups.${NC}"
fi

# Step 2: Verify Vulkan works
echo ""
echo -e "${YELLOW}[2/6] Verifying Vulkan...${NC}"
if vulkaninfo --summary 2>/dev/null | grep -q "AMD"; then
    echo -e "${GREEN}Vulkan AMD driver detected!${NC}"
    vulkaninfo --summary 2>/dev/null | grep -E "(deviceName|driverVersion)" | head -5
else
    echo -e "${RED}WARNING: Vulkan AMD driver not properly detected${NC}"
    echo "Continuing anyway..."
fi

# Step 3: Stop services
echo ""
echo -e "${YELLOW}[3/6] Stopping AI-Core services...${NC}"
systemctl --user stop aicore-llama3.service 2>/dev/null || true
systemctl --user stop aicore-qwen.service 2>/dev/null || true
systemctl --user stop aicore-router.service 2>/dev/null || true
echo -e "${GREEN}Services stopped.${NC}"

# Step 4: Backup old build
echo ""
echo -e "${YELLOW}[4/6] Backing up current llama.cpp build...${NC}"
if [ -d "$LLAMA_DIR/build" ]; then
    mv "$LLAMA_DIR/build" "$BACKUP_DIR"
    echo "Backup created: $BACKUP_DIR"
fi

# Step 5: Rebuild llama.cpp with Vulkan + AVX-512
echo ""
echo -e "${YELLOW}[5/6] Building llama.cpp with Vulkan + AVX-512...${NC}"
cd "$LLAMA_DIR"

# Update repo if git
if [ -d ".git" ]; then
    echo "Updating llama.cpp..."
    git pull --ff-only 2>/dev/null || true
fi

mkdir -p build
cd build

# Configure with Vulkan and optimal CPU flags for Ryzen 9 7940HS (Zen4)
cmake .. \
    -DCMAKE_BUILD_TYPE=Release \
    -DGGML_VULKAN=ON \
    -DGGML_AVX=ON \
    -DGGML_AVX2=ON \
    -DGGML_AVX512=ON \
    -DGGML_AVX512_VBMI=ON \
    -DGGML_AVX512_VNNI=ON \
    -DGGML_AVX512_BF16=ON \
    -DGGML_FMA=ON \
    -DGGML_F16C=ON \
    -DGGML_NATIVE=ON \
    -DLLAMA_BUILD_SERVER=ON \
    -DLLAMA_BUILD_TESTS=OFF \
    -DLLAMA_BUILD_EXAMPLES=ON

# Build with all cores
echo "Compiling (this may take a few minutes)..."
make -j$(nproc)

echo -e "${GREEN}Build complete!${NC}"

# Verify Vulkan backend was built
if [ -f "bin/libggml-vulkan.so" ]; then
    echo -e "${GREEN}Vulkan backend: ENABLED${NC}"
else
    echo -e "${RED}WARNING: Vulkan backend not built!${NC}"
fi

# Step 6: Update service files for GPU offload
echo ""
echo -e "${YELLOW}[6/6] Creating GPU-optimized service configurations...${NC}"

# Create new service files with GPU offload
mkdir -p ~/.config/systemd/user

# Llama3 service with GPU offload (use 20 layers on GPU)
cat > ~/.config/systemd/user/aicore-llama3-gpu.service << 'EOF'
[Unit]
Description=AI Core llama backend (llama3) with GPU acceleration
After=network.target

[Service]
Type=simple
WorkingDirectory=${AICORE_BASE}/opt/llama.cpp
Environment="GGML_VULKAN_DEVICE=0"
ExecStart=${AICORE_BASE}/opt/llama.cpp/build/bin/llama-server \
    --host 127.0.0.1 \
    --port 8101 \
    --model ${AICORE_BASE}/var/lib/aicore/models/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf \
    --ctx-size 4096 \
    --n-gpu-layers 20 \
    --parallel 2 \
    --threads 8 \
    --threads-batch 8 \
    --flash-attn
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

# Qwen service with GPU offload
cat > ~/.config/systemd/user/aicore-qwen-gpu.service << 'EOF'
[Unit]
Description=AI Core llama backend (qwen) with GPU acceleration
After=network.target

[Service]
Type=simple
WorkingDirectory=${AICORE_BASE}/opt/llama.cpp
Environment="GGML_VULKAN_DEVICE=0"
ExecStart=${AICORE_BASE}/opt/llama.cpp/build/bin/llama-server \
    --host 127.0.0.1 \
    --port 8102 \
    --model ${AICORE_BASE}/var/lib/aicore/models/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf \
    --ctx-size 4096 \
    --n-gpu-layers 20 \
    --parallel 2 \
    --threads 8 \
    --threads-batch 8 \
    --flash-attn
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

# Update original services with optimized CPU settings (fallback)
cat > ~/.config/systemd/user/aicore-llama3.service << 'EOF'
[Unit]
Description=AI Core llama backend (llama3) on 8101
After=network.target

[Service]
Type=simple
WorkingDirectory=${AICORE_BASE}/opt/llama.cpp
ExecStart=${AICORE_BASE}/opt/llama.cpp/build/bin/llama-server \
    --host 127.0.0.1 \
    --port 8101 \
    --model ${AICORE_BASE}/var/lib/aicore/models/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf \
    --ctx-size 4096 \
    --parallel 2 \
    --threads 12 \
    --threads-batch 12
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

cat > ~/.config/systemd/user/aicore-qwen.service << 'EOF'
[Unit]
Description=AI Core llama backend (qwen) on 8102
After=network.target

[Service]
Type=simple
WorkingDirectory=${AICORE_BASE}/opt/llama.cpp
ExecStart=${AICORE_BASE}/opt/llama.cpp/build/bin/llama-server \
    --host 127.0.0.1 \
    --port 8102 \
    --model ${AICORE_BASE}/var/lib/aicore/models/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf \
    --ctx-size 4096 \
    --parallel 2 \
    --threads 12 \
    --threads-batch 12
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload

echo ""
echo "=============================================="
echo -e "${GREEN}GPU Acceleration Setup Complete!${NC}"
echo "=============================================="
echo ""
echo "Available configurations:"
echo "  CPU-only (AVX-512):  systemctl --user start aicore-llama3"
echo "  GPU-accelerated:     systemctl --user start aicore-llama3-gpu"
echo ""
echo "To switch to GPU mode:"
echo "  systemctl --user stop aicore-llama3 aicore-qwen"
echo "  systemctl --user start aicore-llama3-gpu aicore-qwen-gpu"
echo ""
echo "To verify GPU is being used:"
echo "  watch -n 1 'cat /sys/class/drm/card*/device/gpu_busy_percent'"
echo ""
