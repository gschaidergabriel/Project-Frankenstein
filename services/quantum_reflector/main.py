#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py — Entry Point für den Quantum Reflector Service

Startet:
1. CoherenceMonitor (Hintergrund-Thread: poll → solve → events)
2. EPQBridge (Callback-Handler für Kohärenz-Events)
3. HTTP API (ThreadingHTTPServer auf Port 8097)

Systemd-kompatibel: ExecStart zeigt auf diese Datei.
"""

from __future__ import annotations

import logging
import os
import sys
import signal
import threading
from pathlib import Path

# ============ PATH SETUP ============
# Sicherstellen dass Frank's Module importierbar sind
_aicore_root = Path(__file__).resolve().parents[2]  # quantum_reflector → services → aicore
if str(_aicore_root) not in sys.path:
    sys.path.insert(0, str(_aicore_root))

# ============ CONFIG ============

try:
    from config.paths import get_db, DB_DIR, AICORE_LOG
except ImportError:
    _data = Path.home() / ".local" / "share" / "frank"
    DB_DIR = _data / "db"
    AICORE_LOG = _data / "logs"
    DB_DIR.mkdir(parents=True, exist_ok=True)

    def get_db(name: str) -> Path:
        return DB_DIR / f"{name}.db"

# ============ LOGGING ============

LOG_DIR = AICORE_LOG
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_DIR / "quantum_reflector.log"), encoding="utf-8"),
    ],
)
LOG = logging.getLogger("quantum_reflector")

# ============ IMPORTS (nach PATH setup) ============

from services.quantum_reflector.annealer import AnnealerConfig
from services.quantum_reflector.coherence_monitor import CoherenceMonitor
from services.quantum_reflector.epq_bridge import EPQBridge
from services.quantum_reflector import api as reflector_api

# ============ SERVICE CONFIG ============

ANNEALER_CONFIG = AnnealerConfig(
    T_start=4.0,
    T_end=0.05,
    steps=2000,
    num_runs=200,
    max_flips=3,
)

REFLECTOR_DB = get_db("quantum_reflector")


def main():
    """Hauptfunktion: Initialisiere und starte alle Komponenten."""
    LOG.info("=" * 60)
    LOG.info("Quantum Reflector v1.0 starting...")
    LOG.info("  DB dir:       %s", DB_DIR)
    LOG.info("  Reflector DB: %s", REFLECTOR_DB)
    LOG.info("  Annealer:     runs=%d steps=%d T=%.1f→%.2f flips=%d",
             ANNEALER_CONFIG.num_runs, ANNEALER_CONFIG.steps,
             ANNEALER_CONFIG.T_start, ANNEALER_CONFIG.T_end,
             ANNEALER_CONFIG.max_flips)
    LOG.info("=" * 60)

    # --- EPQ Bridge ---
    bridge = EPQBridge()

    # --- Coherence Monitor ---
    monitor = CoherenceMonitor(
        db_dir=DB_DIR,
        reflector_db=REFLECTOR_DB,
        annealer_config=ANNEALER_CONFIG,
        on_coherence_change=bridge.on_coherence_change,
    )

    # --- API Setup ---
    reflector_api.set_components(monitor, bridge)

    # --- Start Monitor Thread ---
    monitor.start()

    # --- Start HTTP API (daemon thread) ---
    api_thread = threading.Thread(
        target=reflector_api.run_server,
        name="reflector-api",
        daemon=True,
    )
    api_thread.start()

    # --- Graceful Shutdown ---
    shutdown_event = threading.Event()

    def _signal_handler(signum, frame):
        LOG.info("Signal %d received, shutting down...", signum)
        shutdown_event.set()

    try:
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)
    except ValueError:
        # Signal-Handler nur im Main-Thread möglich
        LOG.warning("Signal handlers not available (not main thread)")

    LOG.info("All components started. Waiting for shutdown signal...")

    # Warte auf Shutdown
    try:
        shutdown_event.wait()
    except KeyboardInterrupt:
        pass

    # Cleanup
    LOG.info("Shutting down components...")
    monitor.stop()
    LOG.info("Quantum Reflector stopped.")


if __name__ == "__main__":
    main()
