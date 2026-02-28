#!/usr/bin/env python3
"""
LLM Guard — Single-RLM Watchdog
=================================
Ensures the single GPU LLM (DeepSeek-R1) and CPU background LLM (Qwen-3B)
stay running. Kills rogue llama-server processes.

Architecture (post RLM-migration Feb 2026):
  - GPU slot: DeepSeek-R1-Distill-Llama-8B on port 8101 (ALWAYS ON)
  - CPU slot: Qwen-3B on port 8105 (ALWAYS ON)
  - No model swapping — single RLM handles all tasks via router

Runs as: systemd user service (llm-guard.service)
"""

import json
import logging
import os
import signal
import subprocess
import time
import urllib.request
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

# GPU model — always on
GPU_RLM = "aicore-llama3-gpu"        # DeepSeek-R1 on port 8101
GPU_RLM_PORT = 8101

# CPU model — always on
CPU_BG = "aicore-micro-llm"          # Qwen-3B on port 8105
CPU_BG_PORT = 8105

# All known LLM ports (anything else = rogue)
KNOWN_PORTS = {GPU_RLM_PORT, CPU_BG_PORT}

# Rogue services that should never run
ROGUE_SERVICES = ["aicore-qwen-gpu", "aicore-chat-llm"]

# Check interval
CHECK_INTERVAL_S = 10

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
    "rlm_restarts": 0,
    "cpu_bg_restarts": 0,
    "rogue_kills": 0,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Grace period: skip HTTP checks for N seconds after service start
HTTP_GRACE_PERIOD_S = 90
_service_start_ts: dict[str, float] = {}

# Consecutive HTTP failures before force-restart
HTTP_FAIL_THRESHOLD = 3
_http_fail_counts: dict[int, int] = {}


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
            _service_start_ts[name] = time.time()
            _http_fail_counts.clear()
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


def _write_health():
    try:
        data = {
            "ts": datetime.now().isoformat(),
            "gpu_rlm_up": _is_service_active(GPU_RLM),
            "cpu_bg_up": _is_service_active(CPU_BG),
            "mem_available_mb": _get_mem_available_mb(),
            "stats": _stats,
        }
        tmp = HEALTH_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.rename(HEALTH_FILE)
    except Exception:
        pass


def _http_health_check(port: int, timeout: float = 5.0) -> bool:
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/health", method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _check_llm_http_health(port: int, service_name: str):
    if not _is_service_active(service_name):
        _http_fail_counts[port] = 0
        return

    started = _service_start_ts.get(service_name, 0)
    if started and (time.time() - started) < HTTP_GRACE_PERIOD_S:
        return

    if _http_health_check(port):
        if _http_fail_counts.get(port, 0) > 0:
            LOG.info(f"[HTTP] {service_name}:{port} recovered")
        _http_fail_counts[port] = 0
        return

    _http_fail_counts[port] = _http_fail_counts.get(port, 0) + 1
    count = _http_fail_counts[port]
    LOG.warning(
        f"[HTTP] {service_name}:{port} unresponsive "
        f"({count}/{HTTP_FAIL_THRESHOLD})"
    )

    if count >= HTTP_FAIL_THRESHOLD:
        LOG.error(f"[HTTP] {service_name}:{port} hung — force-restarting")
        _http_fail_counts[port] = 0
        subprocess.run(
            ["systemctl", "--user", "kill", "--signal=SIGKILL", service_name],
            capture_output=True, timeout=5,
        )
        time.sleep(2)
        _start_service(service_name)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

_running = True


def _signal_handler(signum, _frame):
    global _running
    LOG.info(f"Signal {signum}, shutting down")
    _running = False


def main():
    global _running

    LOG.info("=" * 60)
    LOG.info("LLM Guard — Single-RLM Watchdog")
    LOG.info(f"  GPU RLM: {GPU_RLM} (port {GPU_RLM_PORT})")
    LOG.info(f"  CPU BG:  {CPU_BG} (port {CPU_BG_PORT})")
    LOG.info("=" * 60)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Ensure both models are running at startup
    if not _is_service_active(GPU_RLM):
        _start_service(GPU_RLM)
    else:
        _service_start_ts[GPU_RLM] = time.time()

    if not _is_service_active(CPU_BG):
        _start_service(CPU_BG)
    else:
        _service_start_ts[CPU_BG] = time.time()

    LOG.info("Initial state: RLM + CPU BG both targeted")

    while _running:
        try:
            _stats["checks"] += 1

            # ── 0. Full shutdown signal ──────────────────────────────
            if FULL_SHUTDOWN_SIGNAL.exists():
                LOG.info("=" * 60)
                LOG.info("FULL SHUTDOWN — unloading ALL LLMs")
                LOG.info("=" * 60)
                try:
                    FULL_SHUTDOWN_SIGNAL.unlink(missing_ok=True)
                except Exception:
                    pass

                for svc in [GPU_RLM, CPU_BG]:
                    if _is_service_active(svc):
                        _stop_service(svc)

                time.sleep(2)
                servers = _find_llama_servers()
                for s in servers:
                    LOG.info(f"  Killing remaining llama-server PID {s['pid']}")
                    _kill_pid(s["pid"])

                LOG.info("All LLMs unloaded. Waiting for restart signal...")
                _write_health()

                while _running and not FULL_STARTUP_SIGNAL.exists():
                    if not USER_CLOSED_SIGNAL.exists():
                        LOG.info("user_closed signal removed — restarting")
                        break
                    time.sleep(2)

                FULL_STARTUP_SIGNAL.unlink(missing_ok=True)

                if _running:
                    LOG.info("Resuming — restarting models...")
                    _start_service(GPU_RLM)
                    _start_service(CPU_BG)
                    LOG.info("Resumed")
                continue

            # ── 1. Ensure GPU RLM is running ─────────────────────────
            if not _is_service_active(GPU_RLM):
                LOG.warning("GPU RLM died, restarting")
                _start_service(GPU_RLM)
                _stats["rlm_restarts"] += 1

            # ── 2. Ensure CPU BG is running ──────────────────────────
            if not _is_service_active(CPU_BG):
                LOG.warning(f"CPU BG ({CPU_BG}) down, restarting")
                _start_service(CPU_BG)
                _stats["cpu_bg_restarts"] += 1

            # ── 3. HTTP health checks ────────────────────────────────
            _check_llm_http_health(GPU_RLM_PORT, GPU_RLM)
            _check_llm_http_health(CPU_BG_PORT, CPU_BG)

            # ── 4. Kill rogue llama-server processes ─────────────────
            servers = _find_llama_servers()
            for s in servers:
                if s["port"] not in KNOWN_PORTS:
                    LOG.warning(
                        f"ROGUE llama-server PID {s['pid']} port={s['port']} "
                        f"RSS={s['rss_mb']:.0f}MB — killing"
                    )
                    _kill_pid(s["pid"])
                    _stats["rogue_kills"] += 1

            for svc in ROGUE_SERVICES:
                if _is_service_active(svc):
                    LOG.warning(f"Rogue service {svc} active — stopping")
                    _stop_service(svc)

            # ── 5. Low-memory warning ────────────────────────────────
            avail = _get_mem_available_mb()
            if avail > 0 and avail < 2048:
                LOG.warning(f"LOW MEMORY: {avail}MB available")

            # ── Write health ─────────────────────────────────────────
            _write_health()

            # ── Sleep ────────────────────────────────────────────────
            for _ in range(CHECK_INTERVAL_S):
                if not _running:
                    break
                time.sleep(1)

        except Exception as e:
            LOG.error(f"Guard error: {e}", exc_info=True)
            time.sleep(10)

    LOG.info("LLM Guard stopped")
    LOG.info(f"Final stats: {json.dumps(_stats)}")


if __name__ == "__main__":
    main()
