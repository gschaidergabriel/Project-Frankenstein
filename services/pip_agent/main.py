#!/usr/bin/env python3
"""Pip agent — on-demand robot companion.  Entry point + HTTP server.

NOT a permanent service.  Started by Frank when needed, auto-shuts down
after 5 min of inactivity.  Port 8106.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

# ---- path setup -----------------------------------------------------
_THIS_DIR = Path(__file__).resolve().parent
_AICORE_ROOT = _THIS_DIR.parents[1]
if str(_AICORE_ROOT) not in sys.path:
    sys.path.insert(0, str(_AICORE_ROOT))

# ---- logging --------------------------------------------------------
LOG_DIR = Path.home() / ".local" / "share" / "frank" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_DIR / "pip_agent.log")),
    ],
)
try:
    from config.logging_config import setup_file_logging
    setup_file_logging("pip_agent")
except ImportError:
    pass

LOG = logging.getLogger("pip_agent")

HOST = os.environ.get("PIP_AGENT_HOST", "127.0.0.1")
PORT = int(os.environ.get("PIP_AGENT_PORT", "8106"))


# ---- HTTP handler ---------------------------------------------------

class PipHandler(BaseHTTPRequestHandler):
    agent: Any = None  # set by factory

    def log_message(self, fmt: str, *args: Any) -> None:
        LOG.debug(fmt, *args)

    # GET
    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/health":
            self._json({"status": "ok", "active": self.agent.is_active})
        elif path == "/status":
            self._json(self.agent.get_status())
        elif path == "/memory":
            hist = self.agent.memory.get_conversation_history(limit=30)
            self._json({"history": hist})
        else:
            self._json({"error": "not found"}, 404)

    # POST
    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        body = self._body() or {}

        if path == "/activate":
            room = body.get("room", "library")
            greeting = self.agent.activate(room)
            self._json({"status": "active", "greeting": greeting})
        elif path == "/chat":
            msg = body.get("message")
            if not msg:
                self._json({"error": "message required"}, 400)
                return
            response = self.agent.chat(msg)
            self._json({"response": response, "mood": self.agent._mood})
        elif path == "/task":
            ttype = body.get("type")
            if not ttype:
                self._json({"error": "type required"}, 400)
                return
            result = self.agent.run_task(ttype, body.get("params", {}))
            self._json({"result": result})
        elif path == "/shutdown":
            farewell = self.agent.deactivate()
            self._json({"status": "shutting_down", "farewell": farewell})
        else:
            self._json({"error": "not found"}, 404)

    # helpers
    def _body(self) -> Dict | None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                return {}
            return json.loads(self.rfile.read(length))
        except Exception:
            return None

    def _json(self, data: Dict, status: int = 200) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


# ---- main -----------------------------------------------------------

def main() -> None:
    LOG.info("Pip agent starting on %s:%d ...", HOST, PORT)

    from .core import PipAgent
    agent = PipAgent()

    class Handler(PipHandler):
        pass
    Handler.agent = agent  # type: ignore[attr-defined]

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True

    # Auto-activate
    agent.activate()

    # Signals
    def _sig(signum: int, frame: object) -> None:
        LOG.info("Signal %d — shutting down", signum)
        agent.deactivate()

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    srv_thread = threading.Thread(
        target=server.serve_forever, daemon=True, name="pip-http")
    srv_thread.start()
    LOG.info("Pip agent ready on port %d (idle timeout %ss)",
             PORT, os.environ.get("PIP_IDLE_TIMEOUT", "300"))

    # Block until idle-timeout or explicit /shutdown
    agent.wait_for_shutdown()
    LOG.info("Stopping HTTP server ...")
    server.shutdown()
    LOG.info("Pip agent stopped.")


if __name__ == "__main__":
    main()
