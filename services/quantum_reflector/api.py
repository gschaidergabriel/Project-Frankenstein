#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
api.py — HTTP API für den Quantum Reflector

ThreadingHTTPServer (stdlib) auf Port 8097.
Endpoints:
    GET  /health     — Service Health
    GET  /status     — Detaillierter Status + letzte Kohärenz
    POST /solve      — Manueller Anneal-Trigger
    POST /simulate   — What-If Simulation (für Genesis)
    GET  /energy     — Aktuelle Kohärenz-Energy + History
    GET  /trend      — Energietrend + Moving Average
"""

from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

import numpy as np

LOG = logging.getLogger("quantum_reflector.api")

HOST = os.environ.get("AICORE_REFLECTOR_HOST", "127.0.0.1")
PORT = int(os.environ.get("AICORE_REFLECTOR_PORT", "8097"))

# Globale Referenz zum Monitor (wird von main.py gesetzt)
_monitor = None
_bridge = None


def set_components(monitor, bridge):
    """Setze Referenzen zu Monitor und Bridge (von main.py aufgerufen)."""
    global _monitor, _bridge
    _monitor = monitor
    _bridge = bridge


def _json_response(handler: BaseHTTPRequestHandler, status: int, data: Any):
    """Sende JSON Response."""
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.end_headers()
    body = json.dumps(data, ensure_ascii=False, default=str)
    handler.wfile.write(body.encode("utf-8"))


def _read_body(handler: BaseHTTPRequestHandler) -> Dict:
    """Lese JSON Body aus POST Request."""
    length = int(handler.headers.get("Content-Length", 0))
    if length == 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8"))


class ReflectorHandler(BaseHTTPRequestHandler):
    """HTTP Handler für den Quantum Reflector."""

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/health":
            self._handle_health()
        elif path == "/status":
            self._handle_status()
        elif path == "/energy":
            self._handle_energy()
        elif path == "/trend":
            self._handle_trend()
        else:
            _json_response(self, 404, {"error": "not_found", "path": path})

    def do_POST(self):
        path = self.path.split("?")[0]

        if path == "/solve":
            self._handle_solve()
        elif path == "/simulate":
            self._handle_simulate()
        else:
            _json_response(self, 404, {"error": "not_found", "path": path})

    # ============ GET HANDLERS ============

    def _handle_health(self):
        _json_response(self, 200, {
            "status": "ok",
            "service": "quantum-reflector",
            "port": PORT,
        })

    def _handle_status(self):
        if _monitor is None:
            _json_response(self, 503, {"error": "monitor_not_initialized"})
            return

        snap = _monitor.last_snapshot
        result = _monitor.last_result

        data = {
            "running": _monitor._running,
            "solve_count": _monitor._solve_count,
            "history_size": len(_monitor._history),
        }

        if snap:
            data["last_snapshot"] = {
                "timestamp": snap.timestamp,
                "energy": snap.energy,
                "mean_energy": snap.mean_energy,
                "std_energy": snap.std_energy,
                "violations": snap.violations,
                "current_state_energy": snap.current_state_energy,
                "gap": snap.gap,
                "optimal_state": snap.optimal_state,
            }

        if result:
            data["last_result"] = {
                "best_energy": result.best_energy,
                "mean_energy": result.mean_energy,
                "std_energy": result.std_energy,
                "violations": result.violations,
            }

        if _bridge:
            data["epq_bridge"] = _bridge.get_status()

        trend = _monitor.energy_trend
        if trend:
            data["trend"] = trend

        ma = _monitor.moving_average
        if ma is not None:
            data["moving_average"] = ma

        _json_response(self, 200, data)

    def _handle_energy(self):
        if _monitor is None:
            _json_response(self, 503, {"error": "monitor_not_initialized"})
            return

        snap = _monitor.last_snapshot
        if snap is None:
            _json_response(self, 200, {"energy": None, "message": "no_data_yet"})
            return

        # Letzte N Energien aus History
        history = []
        for s in list(_monitor._history)[-50:]:
            history.append({
                "timestamp": s.timestamp,
                "energy": s.energy,
                "violations": s.violations,
            })

        _json_response(self, 200, {
            "current_energy": snap.energy,
            "current_state_energy": snap.current_state_energy,
            "gap": snap.gap,
            "violations": snap.violations,
            "optimal_state": snap.optimal_state,
            "history": history,
        })

    def _handle_trend(self):
        if _monitor is None:
            _json_response(self, 503, {"error": "monitor_not_initialized"})
            return

        _json_response(self, 200, {
            "trend": _monitor.energy_trend,
            "moving_average": _monitor.moving_average,
            "history_size": len(_monitor._history),
            "solve_count": _monitor._solve_count,
        })

    # ============ POST HANDLERS ============

    def _handle_solve(self):
        """Manueller Anneal-Trigger. Blockiert bis Ergebnis da."""
        if _monitor is None:
            _json_response(self, 503, {"error": "monitor_not_initialized"})
            return

        try:
            snapshot = _monitor.solve_once()
            _json_response(self, 200, {
                "energy": snapshot.energy,
                "mean_energy": snapshot.mean_energy,
                "std_energy": snapshot.std_energy,
                "violations": snapshot.violations,
                "current_state_energy": snapshot.current_state_energy,
                "gap": snapshot.gap,
                "optimal_state": snapshot.optimal_state,
            })
        except Exception as exc:
            LOG.error("Manual solve failed: %s", exc, exc_info=True)
            _json_response(self, 500, {"error": str(exc)})

    def _handle_simulate(self):
        """
        What-If Simulation für Genesis.

        Body: {"hypothesis": {...}} — Optionale Zustandsmodifikation.
        Berechnet: Wie verändert sich die globale Energy wenn
        dieser hypothetische Zustand eintritt?
        """
        if _monitor is None:
            _json_response(self, 503, {"error": "monitor_not_initialized"})
            return

        try:
            body = _read_body(self)
            hypothesis = body.get("hypothesis", {})

            # Aktuellen State lesen
            linear, Q, state = _monitor.builder.build()

            # Hypothetische Modifikationen anwenden
            if "mood" in hypothesis:
                state.mood = float(hypothesis["mood"])
            if "entity" in hypothesis:
                state.last_entity = hypothesis["entity"]
            if "phase" in hypothesis:
                state.current_phase = hypothesis["phase"]
            if "mode" in hypothesis:
                state.current_mode = hypothesis["mode"]
            for epq_name in ("precision", "risk", "empathy", "autonomy", "vigilance"):
                if epq_name in hypothesis:
                    setattr(state, epq_name, float(hypothesis[epq_name]))

            # Linear-Terme mit modifiziertem State neu berechnen
            modified_linear = _monitor.builder.build_linear(state)

            # Solve mit modifiziertem State
            from .annealer import solve as sa_solve, AnnealerConfig
            sim_config = AnnealerConfig(
                num_runs=50,   # Weniger Runs für Schnelligkeit
                steps=1000,
            )
            result = sa_solve(
                linear=modified_linear,
                Q=Q,
                one_hot_groups=_monitor.builder.one_hot_groups,
                config=sim_config,
            )

            # Vergleiche mit aktuellem Optimum
            current_snap = _monitor.last_snapshot
            current_best = current_snap.energy if current_snap else 0.0

            coherence_delta = result.best_energy - current_best

            _json_response(self, 200, {
                "simulated_energy": result.best_energy,
                "current_energy": current_best,
                "coherence_delta": coherence_delta,
                "improves_coherence": coherence_delta < 0,
                "optimal_state": _monitor.builder.interpret_solution(result.best_state),
                "violations": result.violations,
            })

        except Exception as exc:
            LOG.error("Simulation failed: %s", exc, exc_info=True)
            _json_response(self, 500, {"error": str(exc)})

    def log_message(self, format, *args):
        """Logging via unser Logger statt stderr."""
        LOG.debug(format % args)


def run_server():
    """Starte den HTTP Server."""
    server = ThreadingHTTPServer((HOST, PORT), ReflectorHandler)
    LOG.info("quantum-reflector API listening on %s:%d", HOST, PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOG.info("API shutting down...")
        server.shutdown()
