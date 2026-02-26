#!/usr/bin/env python3
"""
LLM Manager — Single-GPU Model Swap + Guard
=============================================
Manages which LLM is loaded on the GPU based on user presence,
and ensures no rogue LLM processes run.

Architecture:
  - GPU slot: ONE of DeepSeek-R1 (idle/reasoning) or Llama-3.1 (chat)
  - CPU slot: Qwen-3B always on (background consciousness tasks)
  - Rogue protection: any unexpected llama-server process is killed

Model swap logic:
  - User ACTIVE  (idle < 30s):  GPU = Llama-3.1   (fast chat)
  - User IDLE    (idle > 5min): GPU = DeepSeek-R1  (deep thinking)
  - Hysteresis prevents thrashing (must stay in state for SWAP_DELAY)

Runs as: systemd user service (llm-guard.service)
"""

import json
import logging
import os
import signal
import subprocess
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

try:
    from config.paths import AICORE_LOG, TEMP_FILES
    LOG_DIR = AICORE_LOG
except ImportError:
    LOG_DIR = Path.home() / ".local" / "share" / "frank" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "llm_guard.log"

LOG = logging.getLogger("llm_guard")
LOG.setLevel(logging.INFO)
_fmt = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s")
_fh = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=2)
_fh.setFormatter(_fmt)
_sh = logging.StreamHandler()
_sh.setFormatter(_fmt)
LOG.addHandler(_fh)
LOG.addHandler(_sh)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# GPU models — only ONE active at a time
GPU_CHAT = "aicore-chat-llm"       # Llama-3.1 on port 8102 (user chat)
GPU_CHAT_PORT = 8102
GPU_REASON = "aicore-llama3-gpu"   # DeepSeek-R1 on port 8101 (reasoning/idle)
GPU_REASON_PORT = 8101

# CPU model — always on
CPU_BG = "aicore-micro-llm"        # Qwen-3B on port 8105 (background)
CPU_BG_PORT = 8105

# All known LLM ports (anything else = rogue)
KNOWN_PORTS = {GPU_CHAT_PORT, GPU_REASON_PORT, CPU_BG_PORT}

# Rogue services that should never run
ROGUE_SERVICES = ["aicore-qwen-gpu"]

# User presence thresholds
USER_ACTIVE_THRESHOLD_S = 30.0    # idle < this = user is active
USER_IDLE_THRESHOLD_S = 300.0     # idle > this = user is idle (5 min)

# Swap hysteresis — must stay in new state this long before swapping
SWAP_DELAY_TO_REASON_S = 60.0    # Wait 60s of idle before swapping to DeepSeek
SWAP_DELAY_TO_CHAT_S = 0.0       # Swap to Llama INSTANTLY when user returns

# Cooldown after swap (prevent thrashing)
SWAP_COOLDOWN_S = 30.0

# Check intervals
CHECK_INTERVAL_S = 5              # Fast checks for responsive swapping

# Shutdown signal (written by overlay on user-initiated close)
try:
    FULL_SHUTDOWN_SIGNAL = TEMP_FILES["full_shutdown"]
except NameError:
    FULL_SHUTDOWN_SIGNAL = Path("/tmp/frank/full_shutdown")

# Health file
try:
    HEALTH_FILE = TEMP_FILES["llm_guard_health"]
except NameError:
    HEALTH_FILE = Path("/tmp/frank/llm_guard_health.json")
HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)

# Startup / user-closed signals
try:
    FULL_STARTUP_SIGNAL = TEMP_FILES["full_startup"]
    USER_CLOSED_SIGNAL = TEMP_FILES["user_closed"]
except NameError:
    FULL_STARTUP_SIGNAL = Path("/tmp/frank/full_startup")
    USER_CLOSED_SIGNAL = Path("/tmp/frank/user_closed")

# Stats
_stats = {
    "started": datetime.now().isoformat(),
    "checks": 0,
    "swaps_to_chat": 0,
    "swaps_to_reason": 0,
    "rogue_kills": 0,
    "cpu_bg_restarts": 0,
}

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

# Which GPU model is currently intended to be active
# "chat" = Llama-3.1, "reason" = DeepSeek-R1
_gpu_mode = "reason"  # Start with reasoning model (idle state)
_last_swap_ts = 0.0
_idle_since_ts = 0.0   # When did user become idle?
_active_since_ts = 0.0  # When did user become active?

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_idle_s() -> float:
    """Get user idle time via xprintidle. Returns seconds."""
    try:
        r = subprocess.run(
            ["xprintidle"],
            capture_output=True, text=True, timeout=2,
            env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
        )
        if r.returncode == 0:
            return int(r.stdout.strip()) / 1000.0
    except Exception:
        pass
    return 0.0


def _is_service_active(name: str) -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", name],
            capture_output=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def _stop_service(name: str) -> bool:
    LOG.info(f"Stopping {name}...")
    try:
        r = subprocess.run(
            ["systemctl", "--user", "stop", name],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            LOG.info(f"  {name} stopped")
            return True
        LOG.warning(f"  {name} stop failed: {r.stderr.strip()}")
        return False
    except Exception as e:
        LOG.error(f"  {name} stop error: {e}")
        return False


def _start_service(name: str) -> bool:
    LOG.info(f"Starting {name}...")
    try:
        # Reset failed state first (in case of prior crash)
        subprocess.run(
            ["systemctl", "--user", "reset-failed", name],
            capture_output=True, timeout=5,
        )
        r = subprocess.run(
            ["systemctl", "--user", "start", name],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            LOG.info(f"  {name} started")
            return True
        LOG.warning(f"  {name} start failed: {r.stderr.strip()}")
        return False
    except Exception as e:
        LOG.error(f"  {name} start error: {e}")
        return False


def _find_llama_servers() -> list[dict]:
    """Return all running llama-server processes."""
    results = []
    try:
        out = subprocess.run(
            ["ps", "-eo", "pid,rss,args"],
            capture_output=True, text=True, timeout=5,
        )
        for line in out.stdout.strip().splitlines():
            if "llama-server" not in line or "grep" in line:
                continue
            # Skip lines that are clearly shell wrappers, not actual servers
            if "/bin/bash" in line or "/bin/sh" in line:
                continue
            parts = line.split(None, 2)
            if len(parts) < 3:
                continue
            try:
                pid = int(parts[0])
                rss_kb = int(parts[1])
            except ValueError:
                continue
            cmdline = parts[2]

            port = None
            if "--port" in cmdline:
                try:
                    idx = cmdline.index("--port")
                    port_str = cmdline[idx:].split()[1]
                    port = int(port_str)
                except (IndexError, ValueError):
                    pass

            results.append({
                "pid": pid,
                "port": port,
                "rss_mb": rss_kb / 1024,
                "cmdline": cmdline[:120],
            })
    except Exception as e:
        LOG.warning(f"ps enumeration failed: {e}")
    return results


def _kill_pid(pid: int):
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(2)
        try:
            os.kill(pid, 0)
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    except (ProcessLookupError, PermissionError):
        pass


def _get_mem_available_mb() -> int:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return 0


def _write_health(gpu_mode: str, idle_s: float, swapping: bool):
    try:
        data = {
            "ts": datetime.now().isoformat(),
            "gpu_mode": gpu_mode,
            "gpu_chat_up": _is_service_active(GPU_CHAT),
            "gpu_reason_up": _is_service_active(GPU_REASON),
            "cpu_bg_up": _is_service_active(CPU_BG),
            "user_idle_s": round(idle_s, 1),
            "swapping": swapping,
            "mem_available_mb": _get_mem_available_mb(),
            "stats": _stats,
        }
        tmp = HEALTH_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.rename(HEALTH_FILE)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Model swap
# ---------------------------------------------------------------------------

def _swap_to_chat():
    """Swap GPU to Llama-3.1 (user is chatting)."""
    global _gpu_mode, _last_swap_ts
    LOG.info("=" * 40)
    LOG.info("SWAP → CHAT MODE (Llama-3.1 on GPU)")
    LOG.info("=" * 40)

    # Stop reasoning model first to free VRAM
    if _is_service_active(GPU_REASON):
        _stop_service(GPU_REASON)
        # Wait for VRAM to be released
        time.sleep(3)

    # Start chat model
    if _start_service(GPU_CHAT):
        _gpu_mode = "chat"
        _last_swap_ts = time.time()
        _stats["swaps_to_chat"] += 1
        LOG.info("GPU now in CHAT mode (Llama-3.1)")
    else:
        # Fallback: restart reasoning model if chat failed
        LOG.error("Failed to start chat LLM, reverting to reasoning")
        _start_service(GPU_REASON)


def _swap_to_reason():
    """Swap GPU to DeepSeek-R1 (user is idle)."""
    global _gpu_mode, _last_swap_ts
    LOG.info("=" * 40)
    LOG.info("SWAP → REASON MODE (DeepSeek-R1 on GPU)")
    LOG.info("=" * 40)

    # Stop chat model first to free VRAM
    if _is_service_active(GPU_CHAT):
        _stop_service(GPU_CHAT)
        time.sleep(3)

    # Start reasoning model
    if _start_service(GPU_REASON):
        _gpu_mode = "reason"
        _last_swap_ts = time.time()
        _stats["swaps_to_reason"] += 1
        LOG.info("GPU now in REASON mode (DeepSeek-R1)")
    else:
        # Fallback: restart chat model if reasoning failed
        LOG.error("Failed to start reasoning LLM, reverting to chat")
        _start_service(GPU_CHAT)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

_running = True


def _signal_handler(signum, _frame):
    global _running
    LOG.info(f"Signal {signum}, shutting down")
    _running = False


def main():
    global _running, _gpu_mode, _idle_since_ts, _active_since_ts, _last_swap_ts

    LOG.info("=" * 60)
    LOG.info("LLM Manager — Single-GPU Model Swap + Guard")
    LOG.info(f"  GPU chat:   {GPU_CHAT} (port {GPU_CHAT_PORT})")
    LOG.info(f"  GPU reason: {GPU_REASON} (port {GPU_REASON_PORT})")
    LOG.info(f"  CPU bg:     {CPU_BG} (port {CPU_BG_PORT})")
    LOG.info(f"  Active < {USER_ACTIVE_THRESHOLD_S}s, Idle > {USER_IDLE_THRESHOLD_S}s")
    LOG.info(f"  Swap delay: chat={SWAP_DELAY_TO_CHAT_S}s, reason={SWAP_DELAY_TO_REASON_S}s")
    LOG.info("=" * 60)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Ensure CPU background model is running
    if not _is_service_active(CPU_BG):
        _start_service(CPU_BG)

    # Detect initial state based on CURRENT user presence
    idle_s = _get_idle_s()
    user_is_here = idle_s < USER_ACTIVE_THRESHOLD_S
    reason_up = _is_service_active(GPU_REASON)
    chat_up = _is_service_active(GPU_CHAT)

    LOG.info(f"Startup: user idle={idle_s:.0f}s ({'ACTIVE' if user_is_here else 'IDLE'}), "
             f"reason={'UP' if reason_up else 'DOWN'}, chat={'UP' if chat_up else 'DOWN'}")

    if user_is_here:
        # User is active → we need chat model
        _gpu_mode = "chat"
        if reason_up:
            _stop_service(GPU_REASON)
            time.sleep(3)
        if not chat_up:
            _start_service(GPU_CHAT)
    else:
        # User is idle → we need reasoning model
        _gpu_mode = "reason"
        if chat_up:
            _stop_service(GPU_CHAT)
            time.sleep(3)
        if not reason_up:
            _start_service(GPU_REASON)

    # No cooldown at startup — allow immediate swap if state changes
    _last_swap_ts = 0.0
    _idle_since_ts = 0.0 if user_is_here else time.time()
    _active_since_ts = time.time() if user_is_here else 0.0

    LOG.info(f"Initial GPU mode: {_gpu_mode}")

    while _running:
        try:
            _stats["checks"] += 1

            # ── 0. Full shutdown signal ──────────────────────────────
            if FULL_SHUTDOWN_SIGNAL.exists():
                LOG.info("=" * 60)
                LOG.info("FULL SHUTDOWN — user closed overlay, unloading ALL LLMs")
                LOG.info("=" * 60)
                try:
                    FULL_SHUTDOWN_SIGNAL.unlink(missing_ok=True)
                except Exception:
                    pass

                # Stop ALL LLM services
                for svc in [GPU_CHAT, GPU_REASON, CPU_BG]:
                    if _is_service_active(svc):
                        _stop_service(svc)

                # Kill any remaining llama-server processes
                time.sleep(2)
                servers = _find_llama_servers()
                for s in servers:
                    LOG.info(f"  Killing remaining llama-server PID {s['pid']}")
                    _kill_pid(s["pid"])

                LOG.info("All LLMs unloaded. Waiting for restart signal...")
                _write_health("shutdown", 0, False)

                # Wait until shutdown signal is cleared (overlay restarted)
                while _running and not FULL_STARTUP_SIGNAL.exists():
                    # Also break if overlay restarts (user_closed removed)
                    if not USER_CLOSED_SIGNAL.exists():
                        LOG.info("user_closed signal removed — Frank is restarting")
                        break
                    time.sleep(2)

                # Clean up startup signal if present
                FULL_STARTUP_SIGNAL.unlink(missing_ok=True)

                if _running:
                    LOG.info("Resuming LLM Manager — restarting models...")
                    idle_s = _get_idle_s()
                    if idle_s < USER_ACTIVE_THRESHOLD_S:
                        _gpu_mode = "chat"
                        _start_service(GPU_CHAT)
                    else:
                        _gpu_mode = "reason"
                        _start_service(GPU_REASON)
                    _start_service(CPU_BG)
                    _last_swap_ts = 0.0
                    LOG.info(f"Resumed in {_gpu_mode} mode")
                continue

            idle_s = _get_idle_s()
            now = time.time()
            swap_age = now - _last_swap_ts
            swapping = False

            # ── 1. User presence tracking ────────────────────────────
            user_active = idle_s < USER_ACTIVE_THRESHOLD_S
            user_idle = idle_s > USER_IDLE_THRESHOLD_S

            if user_active:
                if _active_since_ts == 0.0:
                    _active_since_ts = now
                    LOG.info(f"User RETURNED (idle was {idle_s:.0f}s)")
                _idle_since_ts = 0.0
            elif user_idle:
                if _idle_since_ts == 0.0:
                    _idle_since_ts = now
                _active_since_ts = 0.0

            # ── 2. GPU model swap logic ──────────────────────────────
            if swap_age > SWAP_COOLDOWN_S:

                # User active + GPU is in reason mode → swap to chat
                if (user_active and _gpu_mode == "reason"
                        and _active_since_ts > 0
                        and (now - _active_since_ts) >= SWAP_DELAY_TO_CHAT_S):
                    swapping = True
                    _swap_to_chat()

                # User idle + GPU is in chat mode → swap to reason
                elif (user_idle and _gpu_mode == "chat"
                      and _idle_since_ts > 0
                      and (now - _idle_since_ts) >= SWAP_DELAY_TO_REASON_S):
                    swapping = True
                    _swap_to_reason()

            # ── 3. Ensure correct GPU service is actually running ────
            if not swapping:
                if _gpu_mode == "chat" and not _is_service_active(GPU_CHAT):
                    LOG.warning("Chat LLM died unexpectedly, restarting")
                    _start_service(GPU_CHAT)
                elif _gpu_mode == "reason" and not _is_service_active(GPU_REASON):
                    LOG.warning("Reasoning LLM died unexpectedly, restarting")
                    _start_service(GPU_REASON)

            # ── 4. Ensure the OTHER GPU service is NOT running ───────
            if _gpu_mode == "chat" and _is_service_active(GPU_REASON):
                LOG.warning("Both GPU models active! Stopping reasoning model")
                _stop_service(GPU_REASON)
            elif _gpu_mode == "reason" and _is_service_active(GPU_CHAT):
                LOG.warning("Both GPU models active! Stopping chat model")
                _stop_service(GPU_CHAT)

            # ── 5. Ensure CPU background model is running ────────────
            if not _is_service_active(CPU_BG):
                LOG.warning(f"CPU background LLM ({CPU_BG}) down, restarting")
                _start_service(CPU_BG)
                _stats["cpu_bg_restarts"] += 1

            # ── 6. Kill rogue llama-server processes ─────────────────
            servers = _find_llama_servers()
            for s in servers:
                if s["port"] not in KNOWN_PORTS:
                    LOG.warning(
                        f"ROGUE llama-server PID {s['pid']} port={s['port']} "
                        f"RSS={s['rss_mb']:.0f}MB — killing"
                    )
                    _kill_pid(s["pid"])
                    _stats["rogue_kills"] += 1

            # Also stop any rogue systemd services
            for svc in ROGUE_SERVICES:
                if _is_service_active(svc):
                    LOG.warning(f"Rogue service {svc} active — stopping")
                    _stop_service(svc)

            # ── 7. Low-memory warning ────────────────────────────────
            avail = _get_mem_available_mb()
            if avail > 0 and avail < 2048:
                LOG.warning(f"LOW MEMORY: {avail}MB available")

            # ── Write health ─────────────────────────────────────────
            _write_health(_gpu_mode, idle_s, swapping)

            # ── Sleep ────────────────────────────────────────────────
            for _ in range(CHECK_INTERVAL_S):
                if not _running:
                    break
                time.sleep(1)

        except Exception as e:
            LOG.error(f"Manager error: {e}", exc_info=True)
            time.sleep(10)

    LOG.info("LLM Manager stopped")
    LOG.info(f"Final stats: {json.dumps(_stats)}")


if __name__ == "__main__":
    main()
