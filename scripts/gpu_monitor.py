#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI-Core GPU Monitor

Real-time GPU monitoring for AI inference (auto-detects GPU).
Shows GPU utilization, temperature, VRAM, and inference performance.
"""

import os
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any
import json
import urllib.request


def read_sysfs(path: str) -> Optional[str]:
    """Read sysfs file safely."""
    try:
        return Path(path).read_text().strip()
    except Exception:
        return None


def find_amd_gpu() -> Optional[Path]:
    """Find AMD GPU device path."""
    drm = Path("/sys/class/drm")
    for card in drm.glob("card*"):
        device = card / "device"
        vendor = read_sysfs(str(device / "vendor"))
        if vendor == "0x1002":
            return device
    return None


def get_gpu_metrics(device: Path) -> Dict[str, Any]:
    """Get all GPU metrics."""
    metrics = {
        "busy_percent": 0.0,
        "temp_c": 0.0,
        "power_w": 0.0,
        "vram_used_mb": 0.0,
        "vram_total_mb": 0.0,
        "gfx_mhz": 0,
        "mem_mhz": 0,
    }

    # GPU busy
    busy = read_sysfs(str(device / "gpu_busy_percent"))
    if busy:
        try:
            metrics["busy_percent"] = float(busy)
        except ValueError:
            pass

    # VRAM
    vram_used = read_sysfs(str(device / "mem_info_vram_used"))
    vram_total = read_sysfs(str(device / "mem_info_vram_total"))
    if vram_used:
        metrics["vram_used_mb"] = int(vram_used) / (1024 * 1024)
    if vram_total:
        metrics["vram_total_mb"] = int(vram_total) / (1024 * 1024)

    # Clock speeds
    pp_dpm_sclk = read_sysfs(str(device / "pp_dpm_sclk"))
    if pp_dpm_sclk:
        for line in pp_dpm_sclk.split("\n"):
            if "*" in line:  # Active frequency
                try:
                    mhz = int(line.split("Mhz")[0].split()[-1])
                    metrics["gfx_mhz"] = mhz
                except (ValueError, IndexError):
                    pass
                break

    pp_dpm_mclk = read_sysfs(str(device / "pp_dpm_mclk"))
    if pp_dpm_mclk:
        for line in pp_dpm_mclk.split("\n"):
            if "*" in line:
                try:
                    mhz = int(line.split("Mhz")[0].split()[-1])
                    metrics["mem_mhz"] = mhz
                except (ValueError, IndexError):
                    pass
                break

    # Temperature (hwmon)
    hwmon = device / "hwmon"
    if hwmon.exists():
        for hw in hwmon.iterdir():
            temp = read_sysfs(str(hw / "temp1_input"))
            if temp:
                metrics["temp_c"] = int(temp) / 1000.0
            power = read_sysfs(str(hw / "power1_average"))
            if power:
                metrics["power_w"] = int(power) / 1000000.0
            break

    return metrics


def get_llm_stats(url: str) -> Optional[Dict[str, Any]]:
    """Get stats from llama.cpp server."""
    try:
        req = urllib.request.Request(f"{url}/health", method="GET")
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def format_bar(value: float, max_val: float, width: int = 20) -> str:
    """Create a text progress bar."""
    if max_val <= 0:
        return "[" + " " * width + "]"
    filled = int((value / max_val) * width)
    filled = min(filled, width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}]"


def main():
    print("\033[2J\033[H")  # Clear screen
    print("=" * 60)
    print(" AI-Core GPU Monitor")
    print("=" * 60)
    print()

    device = find_amd_gpu()
    if not device:
        print("ERROR: AMD GPU not found!")
        sys.exit(1)

    print(f"GPU Device: {device}")
    print()

    # LLM endpoints
    endpoints = {
        "DeepSeek-R1 (8101)": "http://127.0.0.1:8101",
    }

    try:
        while True:
            # Move cursor to top
            print("\033[5;0H")

            metrics = get_gpu_metrics(device)

            # GPU Status
            print(f"GPU Busy:    {metrics['busy_percent']:5.1f}% {format_bar(metrics['busy_percent'], 100)}")
            print(f"Temperature: {metrics['temp_c']:5.1f}°C {format_bar(metrics['temp_c'], 100)}")
            if metrics['power_w'] > 0:
                print(f"Power:       {metrics['power_w']:5.1f}W  {format_bar(metrics['power_w'], 35)}")
            print(f"GFX Clock:   {metrics['gfx_mhz']:5d} MHz")
            print(f"MEM Clock:   {metrics['mem_mhz']:5d} MHz")
            print()

            # VRAM
            vram_pct = (metrics['vram_used_mb'] / metrics['vram_total_mb'] * 100) if metrics['vram_total_mb'] > 0 else 0
            print(f"VRAM Used:   {metrics['vram_used_mb']:.0f} / {metrics['vram_total_mb']:.0f} MB ({vram_pct:.1f}%)")
            print(f"             {format_bar(metrics['vram_used_mb'], metrics['vram_total_mb'], 30)}")
            print()

            # LLM Backends
            print("LLM Backends:")
            for name, url in endpoints.items():
                stats = get_llm_stats(url)
                if stats and (stats.get("status") == "ok" or stats.get("ok")):
                    slots = stats.get("slots_processing", 0)
                    idle = stats.get("slots_idle", 0)
                    status = f"✓ Online (slots: {slots} busy, {idle} idle)"
                else:
                    status = "✗ Offline"
                print(f"  {name}: {status}")

            print()
            print("-" * 60)
            print("Press Ctrl+C to exit")

            time.sleep(1.0)

    except KeyboardInterrupt:
        print("\n\nMonitor stopped.")


if __name__ == "__main__":
    main()
