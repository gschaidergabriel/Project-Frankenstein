"""HTTP API for the NeRD Physics service.

ThreadingHTTPServer (stdlib) on port 8100, matching the quantum_reflector pattern.
"""

from __future__ import annotations

import json
import logging
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict

from .engine import ActionType, PhysicsAction, PhysicsEngine
from .sensation import build_body_physics_block

LOG = logging.getLogger("nerd_physics.api")

HOST = os.environ.get("NERD_PHYSICS_HOST", "127.0.0.1")
PORT = int(os.environ.get("NERD_PHYSICS_PORT", "8100"))


class PhysicsHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the physics service."""

    engine: PhysicsEngine  # set by factory
    _start_time: float     # set by factory

    def log_message(self, format: str, *args: Any) -> None:
        # Route to Python logging instead of stderr
        LOG.debug(format, *args)

    # -------------------------------------------------------------------
    # GET endpoints
    # -------------------------------------------------------------------

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        params = self._parse_query()

        if path == "/health":
            self._handle_health()
        elif path == "/state":
            self._handle_state()
        elif path == "/sensation":
            try:
                mood = float(params.get("mood", "0.5"))
            except (ValueError, TypeError):
                mood = 0.5
            self._handle_sensation(mood)
        elif path == "/metrics":
            self._handle_metrics()
        elif path == "/room":
            self._handle_room()
        elif path == "/neural":
            self._handle_neural_status()
        else:
            self._send_json({"error": "not found"}, 404)

    # -------------------------------------------------------------------
    # POST endpoints
    # -------------------------------------------------------------------

    def do_POST(self) -> None:
        path = self.path.split("?")[0]

        if path == "/action":
            self._handle_action()
        elif path == "/reset":
            self._handle_reset()
        elif path == "/mood":
            self._handle_set_mood()
        elif path == "/coherence":
            self._handle_set_coherence()
        elif path == "/neural":
            self._handle_toggle_neural()
        else:
            self._send_json({"error": "not found"}, 404)

    # -------------------------------------------------------------------
    # Handlers
    # -------------------------------------------------------------------

    def _handle_health(self) -> None:
        metrics = self.engine.get_metrics()
        self._send_json({
            "status": "ok",
            "tick_rate": metrics["tick_rate"],
            "sim_time": metrics["sim_time"],
            "uptime": round(time.time() - self._start_time, 1),
            "room": metrics["room"],
        })

    def _handle_state(self) -> None:
        state = self.engine.get_state()
        self._send_json({
            "q": state.q.tolist(),
            "qd": state.qd.tolist(),
            "root_pos": state.root_pos.tolist(),
            "root_vel": state.root_vel.tolist(),
            "torques": state.torques.tolist(),
            "current_room": state.current_room,
            "is_walking": state.is_walking,
            "is_sitting": state.is_sitting,
            "walk_speed": round(state.walk_speed, 3),
            "walk_progress": round(state.walk_progress, 3),
            "sim_time": round(state.sim_time, 2),
            "num_contacts": len(state.contacts),
            "contacts": [
                {
                    "link": c.link,
                    "object": c.object_name,
                    "force": round(c.normal_force, 1),
                    "penetration": round(c.penetration, 4),
                }
                for c in state.contacts
            ],
        })

    def _handle_sensation(self, mood: float) -> None:
        state = self.engine.get_state()
        block = build_body_physics_block(state, mood)
        self._send_json({
            "block": block,
            "room": state.current_room,
            "is_walking": state.is_walking,
            "is_sitting": state.is_sitting,
            "num_contacts": len(state.contacts),
        })

    def _handle_metrics(self) -> None:
        self._send_json(self.engine.get_metrics())

    def _handle_room(self) -> None:
        from .rooms import ROOMS
        state = self.engine.get_state()
        room = ROOMS.get(state.current_room)
        if room is None:
            self._send_json({"error": "unknown room"}, 404)
            return
        self._send_json({
            "key": room.key,
            "name": room.name,
            "bounds_min": room.bounds_min.tolist(),
            "bounds_max": room.bounds_max.tolist(),
            "gravity_mul": room.gravity_mul,
            "friction": room.friction,
            "temperature": room.temperature,
            "objects": [
                {
                    "name": o.name,
                    "type": o.obj_type,
                    "interactable": o.interactable,
                    "sit": o.sit,
                }
                for o in room.objects
            ],
            "exits": list(room.exits.keys()),
        })

    def _handle_action(self) -> None:
        body = self._read_body()
        if body is None:
            return

        action_str = body.get("action", "idle")
        try:
            action_type = ActionType(action_str)
        except ValueError:
            self._send_json({"error": f"unknown action: {action_str}"}, 400)
            return

        pa = PhysicsAction(
            action_type=action_type,
            target_room=body.get("target_room", ""),
            target_object=body.get("target", ""),
            hand=body.get("hand", "right"),
        )
        self.engine.set_action(pa)
        self._send_json({"ok": True, "action": action_str})

    def _handle_reset(self) -> None:
        body = self._read_body() or {}
        room = body.get("room", "library")
        self.engine.reset(room)
        self._send_json({"ok": True, "room": room})

    def _handle_set_mood(self) -> None:
        body = self._read_body()
        if body is None:
            return
        try:
            mood = float(body.get("mood", 0.5))
        except (ValueError, TypeError):
            self._send_json({"error": "invalid mood value"}, 400)
            return
        self.engine.set_mood(mood)
        self._send_json({"ok": True, "mood": max(0.0, min(1.0, mood))})

    def _handle_set_coherence(self) -> None:
        body = self._read_body()
        if body is None:
            return
        try:
            coherence = float(body.get("coherence", 0.8))
        except (ValueError, TypeError):
            self._send_json({"error": "invalid coherence value"}, 400)
            return
        self.engine.set_coherence(coherence)
        self._send_json({"ok": True, "coherence": max(0.0, min(1.0, coherence))})

    def _handle_neural_status(self) -> None:
        metrics = self.engine.get_metrics()
        with self.engine._lock:
            ne = self.engine._neural_engine
            result = {
                "enabled": metrics.get("neural_enabled", False),
                "neural_steps": metrics.get("neural_steps", 0),
                "analytical_steps": metrics.get("analytical_steps", 0),
            }
            if ne is not None:
                result["model_loaded"] = ne.is_loaded
                result["divergence_count"] = ne._divergence_count
                result["max_divergence"] = ne._max_divergence
        self._send_json(result)

    def _handle_toggle_neural(self) -> None:
        body = self._read_body() or {}
        with self.engine._lock:
            enable = body.get("enable", not self.engine._use_neural)
            if enable and self.engine._neural_engine is None:
                try:
                    from .neural import NeuralPhysicsEngine
                    ne = NeuralPhysicsEngine()
                    if not ne.is_loaded:
                        self._send_json({"error": "neural model not found"}, 400)
                        return
                    self.engine._neural_engine = ne
                except Exception as e:
                    self._send_json({"error": str(e)}, 500)
                    return
            self.engine._use_neural = bool(enable)
            if self.engine._neural_engine:
                self.engine._neural_engine.reset_divergence()
            self._send_json({"ok": True, "neural_enabled": self.engine._use_neural})

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    def _parse_query(self) -> Dict[str, str]:
        params: Dict[str, str] = {}
        if "?" in self.path:
            qs = self.path.split("?", 1)[1]
            for pair in qs.split("&"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    params[k] = v
        return params

    def _read_body(self) -> Dict | None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            return json.loads(raw)
        except Exception as e:
            self._send_json({"error": str(e)}, 400)
            return None

    def _send_json(self, data: Dict, status: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def create_server(engine: PhysicsEngine) -> ThreadingHTTPServer:
    """Create and return the HTTP server (not yet serving)."""
    start_time = time.time()

    class Handler(PhysicsHandler):
        pass

    Handler.engine = engine  # type: ignore[attr-defined]
    Handler._start_time = start_time  # type: ignore[attr-defined]

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    LOG.info("HTTP server created on %s:%d", HOST, PORT)
    return server
