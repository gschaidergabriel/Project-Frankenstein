#!/bin/bash
# Quick install script for Vulkan dependencies
# Run with: sudo bash install_vulkan_deps.sh

set -e

echo "Installing Vulkan development packages..."

apt-get update
apt-get install -y \
    libvulkan-dev \
    vulkan-tools \
    glslang-tools \
    glslang-dev \
    spirv-tools \
    mesa-vulkan-drivers \
    glslc \
    libshaderc-dev

echo ""
echo "Verifying Vulkan installation..."
vulkaninfo --summary | head -20

echo ""
echo "Done! Now run: ./setup_gpu_acceleration.sh"
