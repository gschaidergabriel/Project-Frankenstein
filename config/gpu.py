"""
GPU auto-detection for AI-Core / Frank.

Detects the available GPU and recommends the best backend for Ollama
and other ML workloads. Supports NVIDIA, AMD, Intel, and CPU-only.

Usage:
    from config.gpu import detect_gpu
    gpu = detect_gpu()
    print(gpu.vendor, gpu.backend, gpu.vram_mb)
"""

import os
import subprocess
import re
from dataclasses import dataclass, field
from pathlib import Path
from functools import lru_cache
from typing import Optional


@dataclass
class GPUInfo:
    vendor: str       # "nvidia", "amd", "intel", "none"
    name: str         # e.g. "NVIDIA RTX 4070" or "AMD Radeon 780M"
    vram_mb: int      # dedicated VRAM in MB (0 for iGPU shared memory)
    shared_mb: int    # shared/system memory available to GPU
    backend: str      # "cuda", "vulkan", "rocm", "cpu"
    ollama_env: dict = field(default_factory=dict)

    @property
    def total_memory_mb(self) -> int:
        """Total usable GPU memory (dedicated + shared)."""
        return self.vram_mb + self.shared_mb

    @property
    def is_igpu(self) -> bool:
        """True if this is an integrated GPU (no dedicated VRAM)."""
        return self.vram_mb == 0 and self.shared_mb > 0

    @property
    def is_discrete(self) -> bool:
        """True if this is a discrete GPU with dedicated VRAM."""
        return self.vram_mb > 0

    def summary(self) -> str:
        """Human-readable one-line summary."""
        mem = self.vram_mb or self.shared_mb
        unit = "VRAM" if self.vram_mb > 0 else "shared"
        return f"{self.name} ({mem} MB {unit}, backend: {self.backend})"


def _run(cmd: list[str], timeout: int = 5) -> Optional[str]:
    """Run a command and return stdout, or None on failure."""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def _detect_nvidia() -> Optional[GPUInfo]:
    """Detect NVIDIA GPU via nvidia-smi."""
    out = _run(["nvidia-smi", "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits"])
    if not out:
        return None

    # Parse first GPU line: "NVIDIA GeForce RTX 4070, 12288"
    line = out.split("\n")[0].strip()
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 2:
        return None

    name = parts[0]
    try:
        vram_mb = int(float(parts[1]))
    except (ValueError, IndexError):
        vram_mb = 0

    return GPUInfo(
        vendor="nvidia",
        name=name,
        vram_mb=vram_mb,
        shared_mb=0,
        backend="cuda",
        ollama_env={},  # CUDA is Ollama's default
    )


def _detect_amd() -> Optional[GPUInfo]:
    """Detect AMD GPU via sysfs and DRM."""
    # Check PCI devices for AMD vendor (0x1002)
    gpu_name = None
    vram_mb = 0
    shared_mb = 0

    # Try lspci first for the name
    out = _run(["lspci", "-d", "1002:", "-nn"])
    if out:
        # Extract VGA/Display controller name
        for line in out.split("\n"):
            if "VGA" in line or "Display" in line:
                # "06:00.0 VGA compatible controller [0300]: Advanced Micro Devices, Inc. [AMD/ATI] Phoenix1 [1002:15bf] (rev c8)"
                m = re.search(r"\]\s+(.+?)(?:\s+\[[\da-f:]+\])?\s*(?:\(rev|$)", line)
                if m:
                    gpu_name = m.group(1).strip()
                break

    if not gpu_name:
        return None

    # Try to get VRAM info from DRM
    drm_path = Path("/sys/class/drm")
    if drm_path.exists():
        for card in sorted(drm_path.glob("card[0-9]*")):
            device_vendor = card / "device" / "vendor"
            if device_vendor.exists():
                try:
                    vendor = device_vendor.read_text().strip()
                    if vendor != "0x1002":
                        continue
                except OSError:
                    continue

            # Check dedicated VRAM
            mem_vram = card / "device" / "mem_info_vram_total"
            if mem_vram.exists():
                try:
                    vram_mb = int(mem_vram.read_text().strip()) // (1024 * 1024)
                except (ValueError, OSError):
                    pass

            # Check GTT (shared system memory available to GPU)
            mem_gtt = card / "device" / "mem_info_gtt_total"
            if mem_gtt.exists():
                try:
                    shared_mb = int(mem_gtt.read_text().strip()) // (1024 * 1024)
                except (ValueError, OSError):
                    pass
            break

    # Determine best backend
    # ROCm works on some AMD GPUs but not all (esp. not iGPUs like gfx1103)
    # Vulkan is the safest universal choice for AMD
    backend = "vulkan"
    ollama_env = {"OLLAMA_VULKAN": "1"}

    # If ROCm is available AND this is a discrete GPU, prefer ROCm
    if vram_mb > 0:
        rocm_check = _run(["rocminfo"])
        if rocm_check and "gfx" in rocm_check:
            # Extract gfx version
            gfx_match = re.search(r"(gfx\d+)", rocm_check)
            if gfx_match:
                gfx = gfx_match.group(1)
                # Known well-supported ROCm GPUs
                rocm_supported = {
                    "gfx900", "gfx906", "gfx908", "gfx90a", "gfx940",
                    "gfx941", "gfx942", "gfx1010", "gfx1030", "gfx1100",
                    "gfx1101", "gfx1102",
                }
                if gfx in rocm_supported:
                    backend = "rocm"
                    ollama_env = {}  # ROCm is auto-detected by Ollama

    return GPUInfo(
        vendor="amd",
        name=gpu_name,
        vram_mb=vram_mb,
        shared_mb=shared_mb,
        backend=backend,
        ollama_env=ollama_env,
    )


def _detect_intel() -> Optional[GPUInfo]:
    """Detect Intel GPU via sysfs."""
    gpu_name = None
    shared_mb = 0

    out = _run(["lspci", "-d", "8086:", "-nn"])
    if out:
        for line in out.split("\n"):
            if "VGA" in line or "Display" in line:
                m = re.search(r"\]\s+(.+?)(?:\s+\[[\da-f:]+\])?\s*(?:\(rev|$)", line)
                if m:
                    gpu_name = m.group(1).strip()
                break

    if not gpu_name:
        return None

    # Intel iGPUs share system memory
    # Estimate from total RAM (Intel typically allows up to half)
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total_kb = int(line.split()[1])
                    # Conservative estimate: Intel iGPU can use ~25% of RAM
                    shared_mb = (total_kb // 1024) // 4
                    break
    except (OSError, ValueError):
        pass

    return GPUInfo(
        vendor="intel",
        name=gpu_name,
        vram_mb=0,
        shared_mb=shared_mb,
        backend="vulkan",
        ollama_env={"OLLAMA_VULKAN": "1"},
    )


def _cpu_fallback() -> GPUInfo:
    """Fallback when no GPU is detected."""
    return GPUInfo(
        vendor="none",
        name="CPU only",
        vram_mb=0,
        shared_mb=0,
        backend="cpu",
        ollama_env={},
    )


@lru_cache(maxsize=1)
def detect_gpu() -> GPUInfo:
    """
    Auto-detect the best available GPU.

    Detection order: NVIDIA (CUDA) > AMD (Vulkan/ROCm) > Intel (Vulkan) > CPU

    The result is cached — call detect_gpu.cache_clear() to force re-detection.
    """
    # Allow manual override via environment
    forced = os.environ.get("AICORE_GPU_BACKEND")
    if forced:
        forced = forced.lower()
        if forced == "cuda":
            gpu = _detect_nvidia()
            if gpu:
                return gpu
        elif forced == "vulkan":
            # Try AMD first, then Intel
            for detector in [_detect_amd, _detect_intel]:
                gpu = detector()
                if gpu:
                    gpu.backend = "vulkan"
                    gpu.ollama_env = {"OLLAMA_VULKAN": "1"}
                    return gpu
        elif forced == "rocm":
            gpu = _detect_amd()
            if gpu:
                gpu.backend = "rocm"
                gpu.ollama_env = {}
                return gpu
        elif forced == "cpu":
            return _cpu_fallback()

    # Auto-detect in priority order
    for detector in [_detect_nvidia, _detect_amd, _detect_intel]:
        gpu = detector()
        if gpu:
            return gpu

    return _cpu_fallback()


def get_ollama_env() -> dict[str, str]:
    """Get environment variables needed for Ollama based on detected GPU."""
    return detect_gpu().ollama_env


def get_model_recommendations(gpu: Optional[GPUInfo] = None) -> dict[str, str]:
    """
    Recommend model sizes based on available GPU memory.

    Returns a dict with suggested model tags for different roles.
    """
    if gpu is None:
        gpu = detect_gpu()

    mem = gpu.total_memory_mb

    if mem >= 24000:
        # 24GB+ — can run 13B+ models
        return {
            "chat": "qwen2.5:14b",
            "code": "qwen2.5-coder:14b",
            "vision": "llava:13b",
            "tiny": "tinyllama:1.1b",
        }
    elif mem >= 8000:
        # 8-24GB — comfortable with 7B models
        return {
            "chat": "qwen2.5:7b",
            "code": "qwen2.5-coder:7b",
            "vision": "llava:7b",
            "tiny": "tinyllama:1.1b",
        }
    elif mem >= 4000:
        # 4-8GB — tight, use smaller models
        return {
            "chat": "qwen2.5:3b",
            "code": "qwen2.5-coder:3b",
            "vision": "moondream:1.8b",
            "tiny": "tinyllama:1.1b",
        }
    else:
        # <4GB or CPU only — minimal models
        return {
            "chat": "tinyllama:1.1b",
            "code": "tinyllama:1.1b",
            "vision": "moondream:1.8b",
            "tiny": "tinyllama:1.1b",
        }
