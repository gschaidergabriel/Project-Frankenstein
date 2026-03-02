#!/usr/bin/env python3
"""NeRD Physics service — entry point.

Starts the physics simulation loop (100 Hz background thread)
and the HTTP API server on port 8100.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup — ensure aicore root is on sys.path
# ---------------------------------------------------------------------------
_THIS_DIR = Path(__file__).resolve().parent
_AICORE_ROOT = _THIS_DIR.parents[1]  # services/nerd_physics -> services -> aicore root
if str(_AICORE_ROOT) not in sys.path:
    sys.path.insert(0, str(_AICORE_ROOT))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = Path.home() / ".local" / "share" / "frank" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_DIR / "nerd_physics.log")),
    ],
)
LOG = logging.getLogger("nerd_physics")

# ---------------------------------------------------------------------------
# DB setup
# ---------------------------------------------------------------------------

def _init_db() -> None:
    """Create nerd_physics.db tables if they don't exist."""
    import sqlite3

    try:
        from config.paths import get_db
        db_path = get_db("nerd_physics")
    except (ImportError, KeyError):
        db_path = Path.home() / ".local" / "share" / "frank" / "db" / "nerd_physics.db"

    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS physics_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                session_id TEXT,
                room TEXT,
                q_json TEXT,
                contacts_json TEXT,
                sensation TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_phys_ts ON physics_snapshots(ts);

            CREATE TABLE IF NOT EXISTS training_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                state_in BLOB,
                state_out BLOB,
                dt REAL DEFAULT 0.01
            );
        """)
        conn.commit()
    finally:
        conn.close()

    LOG.info("Database initialised at %s", db_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    LOG.info("NeRD Physics service starting...")
    LOG.info("AICORE_ROOT=%s", _AICORE_ROOT)

    # Init DB
    _init_db()

    # Create engine
    from .engine import PhysicsEngine, SimulationThread
    from .api import create_server

    use_neural = os.environ.get("NERD_USE_NEURAL", "0") == "1"
    engine = PhysicsEngine(use_neural=use_neural)
    engine.reset("library")

    # Start simulation thread
    sim_thread = SimulationThread(engine)
    sim_thread.start()
    LOG.info("Simulation thread started (100 Hz)")

    # Create HTTP server
    server = create_server(engine)

    # Signal handling for clean shutdown
    shutdown_event = threading.Event()

    def _signal_handler(signum: int, frame: object) -> None:
        LOG.info("Signal %d received, shutting down...", signum)
        shutdown_event.set()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    # Start HTTP server in a thread
    server_thread = threading.Thread(target=server.serve_forever, daemon=True,
                                     name="nerd-physics-http")
    server_thread.start()
    LOG.info("HTTP server listening on %s:%s",
             os.environ.get("NERD_PHYSICS_HOST", "127.0.0.1"),
             os.environ.get("NERD_PHYSICS_PORT", "8100"))

    LOG.info("NeRD Physics service ready.")

    # Wait for shutdown signal
    shutdown_event.wait()

    LOG.info("Stopping simulation thread...")
    sim_thread.stop()
    sim_thread.join(timeout=5.0)

    LOG.info("Stopping HTTP server...")
    server.shutdown()

    LOG.info("NeRD Physics service stopped.")


if __name__ == "__main__":
    main()
