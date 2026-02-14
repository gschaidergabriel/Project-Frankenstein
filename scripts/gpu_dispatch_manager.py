#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI-Core GPU Dispatch Manager

Intelligent routing between GPU and CPU based on:
- GPU VRAM availability
- Current GPU utilization
- Request complexity (token length)
- Thermal conditions

Auto-detects GPU via config/gpu.py (supports NVIDIA, AMD, Intel, CPU-only).
"""

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.request
import urllib.error

# Configuration
HOST = "127.0.0.1"
PORT = int(os.environ.get("AICORE_DISPATCH_PORT", "8099"))

# Backend URLs
LLAMA_GPU_URL = os.environ.get("AICORE_LLAMA_GPU_URL", "http://127.0.0.1:8101")
LLAMA_CPU_URL = os.environ.get("AICORE_LLAMA_CPU_URL", "http://127.0.0.1:8103")
QWEN_GPU_URL = os.environ.get("AICORE_QWEN_GPU_URL", "http://127.0.0.1:8102")
QWEN_CPU_URL = os.environ.get("AICORE_QWEN_CPU_URL", "http://127.0.0.1:8104")

# Thresholds
GPU_BUSY_THRESHOLD = 85  # % - switch to CPU if GPU is busier
GPU_TEMP_THRESHOLD = 85  # °C - switch to CPU if GPU is too hot
VRAM_MIN_FREE_MB = 256   # MB - minimum free VRAM for GPU inference
TOKEN_GPU_MAX = 512      # Max tokens for GPU (shorter = faster)
TOKEN_CPU_THRESHOLD = 256 # Below this, always try GPU first

# State
_gpu_stats: Dict[str, float] = {}
_stats_lock = threading.Lock()


@dataclass
class GPUStats:
    busy_percent: float = 0.0
    temp_c: float = 0.0
    vram_used_mb: float = 0.0
    vram_total_mb: float = 2048.0
    available: bool = True


def _read_file(path: str) -> Optional[str]:
    """Read a sysfs file safely."""
    try:
        return Path(path).read_text().strip()
    except Exception:
        return None


def _get_gpu_stats() -> GPUStats:
    """Get current AMD GPU statistics from sysfs."""
    stats = GPUStats()

    # Find the AMD GPU card
    drm_base = Path("/sys/class/drm")
    amd_card = None

    for card in drm_base.glob("card*"):
        device = card / "device"
        vendor = _read_file(str(device / "vendor"))
        if vendor == "0x1002":  # AMD vendor ID
            amd_card = device
            break

    if not amd_card:
        stats.available = False
        return stats

    # GPU busy percentage
    busy = _read_file(str(amd_card / "gpu_busy_percent"))
    if busy:
        try:
            stats.busy_percent = float(busy)
        except ValueError:
            pass

    # GPU temperature (hwmon)
    hwmon_base = amd_card / "hwmon"
    if hwmon_base.exists():
        for hwmon in hwmon_base.iterdir():
            temp_file = hwmon / "temp1_input"
            if temp_file.exists():
                temp = _read_file(str(temp_file))
                if temp:
                    try:
                        stats.temp_c = float(temp) / 1000.0  # millidegrees to degrees
                    except ValueError:
                        pass
                break

    # VRAM usage
    vram_used = _read_file(str(amd_card / "mem_info_vram_used"))
    vram_total = _read_file(str(amd_card / "mem_info_vram_total"))

    if vram_used:
        try:
            stats.vram_used_mb = float(vram_used) / (1024 * 1024)
        except ValueError:
            pass

    if vram_total:
        try:
            stats.vram_total_mb = float(vram_total) / (1024 * 1024)
        except ValueError:
            pass

    return stats


def _is_service_healthy(url: str) -> bool:
    """Check if a backend service is healthy."""
    try:
        req = urllib.request.Request(f"{url}/health", method="GET")
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("status") == "ok" or data.get("ok") is True
    except Exception:
        return False


def _estimate_tokens(text: str) -> int:
    """Rough token estimation (4 chars per token)."""
    return len(text) // 4


def decide_backend(model: str, prompt: str, n_predict: int = 256) -> Tuple[str, str]:
    """
    Decide which backend to use based on current conditions.

    Returns:
        Tuple of (backend_url, reason)
    """
    gpu_stats = _get_gpu_stats()
    input_tokens = _estimate_tokens(prompt)
    total_tokens = input_tokens + n_predict

    # Determine base URLs
    if model in ("qwen", "coder", "code"):
        gpu_url = QWEN_GPU_URL
        cpu_url = QWEN_CPU_URL
    else:
        gpu_url = LLAMA_GPU_URL
        cpu_url = LLAMA_CPU_URL

    # Decision logic
    reasons = []
    use_gpu = True

    # Check 1: Is GPU available?
    if not gpu_stats.available:
        use_gpu = False
        reasons.append("GPU not available")

    # Check 2: GPU temperature
    if gpu_stats.temp_c > GPU_TEMP_THRESHOLD:
        use_gpu = False
        reasons.append(f"GPU too hot ({gpu_stats.temp_c:.0f}°C)")

    # Check 3: GPU busy
    if gpu_stats.busy_percent > GPU_BUSY_THRESHOLD:
        use_gpu = False
        reasons.append(f"GPU busy ({gpu_stats.busy_percent:.0f}%)")

    # Check 4: VRAM availability
    vram_free = gpu_stats.vram_total_mb - gpu_stats.vram_used_mb
    if vram_free < VRAM_MIN_FREE_MB:
        use_gpu = False
        reasons.append(f"Low VRAM ({vram_free:.0f}MB free)")

    # Check 5: Token count (long generations better on CPU for iGPU)
    if total_tokens > TOKEN_GPU_MAX:
        use_gpu = False
        reasons.append(f"Long generation ({total_tokens} tokens)")

    # Check 6: Backend health
    target_url = gpu_url if use_gpu else cpu_url
    if not _is_service_healthy(target_url):
        # Try the other one
        fallback_url = cpu_url if use_gpu else gpu_url
        if _is_service_healthy(fallback_url):
            target_url = fallback_url
            use_gpu = not use_gpu
            reasons.append("Primary backend unhealthy, using fallback")
        else:
            reasons.append("Both backends unhealthy!")

    # Build reason string
    if use_gpu:
        reason = f"GPU: busy={gpu_stats.busy_percent:.0f}%, temp={gpu_stats.temp_c:.0f}°C, tokens={total_tokens}"
    else:
        reason = "; ".join(reasons) if reasons else "CPU preferred"

    return target_url, reason


def _update_stats_loop():
    """Background thread to update GPU stats periodically."""
    global _gpu_stats
    while True:
        try:
            stats = _get_gpu_stats()
            with _stats_lock:
                _gpu_stats = {
                    "busy_percent": stats.busy_percent,
                    "temp_c": stats.temp_c,
                    "vram_used_mb": stats.vram_used_mb,
                    "vram_total_mb": stats.vram_total_mb,
                    "available": stats.available,
                    "timestamp": time.time(),
                }
        except Exception as e:
            print(f"Stats update error: {e}")
        time.sleep(1.0)


class DispatchHandler(BaseHTTPRequestHandler):
    """HTTP handler for dispatch API."""

    def log_message(self, format, *args):
        pass  # Suppress default logging

    def _json_response(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self):
        if self.path == "/health":
            self._json_response(200, {"ok": True, "status": "ok"})
            return

        if self.path == "/stats":
            with _stats_lock:
                stats = dict(_gpu_stats)
            self._json_response(200, {"ok": True, "gpu": stats})
            return

        self._json_response(404, {"ok": False, "error": "not_found"})

    def do_POST(self):
        if self.path == "/decide":
            try:
                payload = self._read_json()
                model = payload.get("model", "llama")
                prompt = payload.get("prompt", "")
                n_predict = payload.get("n_predict", 256)

                backend_url, reason = decide_backend(model, prompt, n_predict)

                self._json_response(200, {
                    "ok": True,
                    "backend_url": backend_url,
                    "reason": reason,
                })
            except Exception as e:
                self._json_response(500, {"ok": False, "error": str(e)})
            return

        self._json_response(404, {"ok": False, "error": "not_found"})


def main():
    # Start stats update thread
    stats_thread = threading.Thread(target=_update_stats_loop, daemon=True)
    stats_thread.start()

    # Start HTTP server
    server = ThreadingHTTPServer((HOST, PORT), DispatchHandler)
    print(f"GPU Dispatch Manager listening on http://{HOST}:{PORT}")
    print(f"  GPU threshold: {GPU_BUSY_THRESHOLD}% busy, {GPU_TEMP_THRESHOLD}°C temp")
    print(f"  Token threshold: {TOKEN_GPU_MAX} max for GPU")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
