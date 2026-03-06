"""Pip client — helper for Frank's subsystems to interact with Pip.

Usage from anywhere in Frank:
    from services.pip_agent.client import pip_chat, pip_task, pip_shutdown

    # Start Pip (if not running) and send a message
    response = pip_chat("Check the services for me")

    # Execute a specific task
    result = pip_task("system_check")

    # Shut Pip down early
    pip_shutdown()
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Dict, Optional

LOG = logging.getLogger("pip_agent.client")

PIP_URL = "http://127.0.0.1:8106"
_pip_process: Optional[subprocess.Popen] = None


def is_pip_running() -> bool:
    """Check if Pip is currently running."""
    try:
        req = urllib.request.Request(f"{PIP_URL}/health", method="GET")
        resp = urllib.request.urlopen(req, timeout=2.0)
        data = json.loads(resp.read())
        return data.get("status") == "ok"
    except Exception:
        return False


def start_pip(room: str = "library") -> bool:
    """Start Pip as a background subprocess.  Returns True if ready."""
    global _pip_process

    if is_pip_running():
        return True

    try:
        aicore_root = Path(__file__).resolve().parents[2]
        # Prefer venv python
        # Try known venv locations
        for candidate in [
            Path.home() / "aicore" / "opt" / "venv" / "bin" / "python3",
            Path.home() / "aicore" / "venv" / "bin" / "python3",
            Path.home() / "aicore" / "opt" / "venv" / "bin" / "python",
        ]:
            if candidate.exists():
                python = str(candidate)
                break
        else:
            python = sys.executable

        _pip_process = subprocess.Popen(
            [python, "-m", "services.pip_agent.main"],
            cwd=str(aicore_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        # Wait up to 15 s for startup (first LLM greeting can be slow)
        for _ in range(150):
            time.sleep(0.1)
            if is_pip_running():
                LOG.info("Pip started (PID=%d)", _pip_process.pid)
                return True

        LOG.warning("Pip process started but not responding")
        return False
    except Exception as e:
        LOG.error("Failed to start Pip: %s", e)
        return False


def pip_chat(message: str, room: str = "library") -> Optional[str]:
    """Send a message to Pip.  Starts Pip automatically if needed."""
    if not is_pip_running():
        if not start_pip(room):
            return None

    try:
        data = json.dumps({"message": message}).encode()
        req = urllib.request.Request(
            f"{PIP_URL}/chat", data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=120.0)
        result = json.loads(resp.read())
        return result.get("response")
    except Exception as e:
        LOG.error("Pip chat failed: %s", e)
        return None


def pip_task(task_type: str, **params: object) -> Optional[Dict]:
    """Execute a task via Pip.  Starts Pip automatically if needed."""
    if not is_pip_running():
        if not start_pip():
            return None

    try:
        data = json.dumps({"type": task_type, "params": params}).encode()
        req = urllib.request.Request(
            f"{PIP_URL}/task", data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=30.0)
        return json.loads(resp.read()).get("result")
    except Exception as e:
        LOG.error("Pip task failed: %s", e)
        return None


def pip_shutdown() -> Optional[str]:
    """Shut Pip down."""
    try:
        req = urllib.request.Request(
            f"{PIP_URL}/shutdown", data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=5.0)
        return json.loads(resp.read()).get("farewell")
    except Exception:
        return None


def pip_status() -> Optional[Dict]:
    """Get Pip's current status."""
    try:
        req = urllib.request.Request(f"{PIP_URL}/status", method="GET")
        resp = urllib.request.urlopen(req, timeout=2.0)
        return json.loads(resp.read())
    except Exception:
        return None
