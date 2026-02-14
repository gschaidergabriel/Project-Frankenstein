#!/bin/bash
# Install missing glslc for Vulkan shader compilation
sudo apt-get install -y glslc
echo "glslc installed: $(which glslc)"
