"""
Neural Immune System — Database Layer
======================================
SQLite schema + access methods for immune_system.db.

Tables:
  health_snapshots  — Training data for BaselineNet
  incident_log      — Training data for AnomalyNet + RestartNet
  service_baselines — Learned normal ranges per service
  circuit_states    — Persistent circuit breaker states
  training_meta     — Training step counters per module
  lifecycle_events  — Startup/shutdown/restart sequences
"""

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

LOG = logging.getLogger("immune.db")

# Default DB path (overridden by config.paths if available)
_DEFAULT_DB = Path.home() / ".local" / "share" / "frank" / "db" / "immune_system.db"

try:
    from config.paths import DB_DIR
    DEFAULT_DB_PATH = DB_DIR / "immune_system.db"
except ImportError:
    DEFAULT_DB_PATH = _DEFAULT_DB


class ImmuneDB:
    """Thread-safe SQLite access for the immune system."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._conns: List[sqlite3.Connection] = []
        self._conns_lock = threading.Lock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self._db_path), timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
            with self._conns_lock:
                self._conns.append(conn)
        return conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS health_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                snapshot TEXT NOT NULL,
                is_healthy INTEGER DEFAULT 1,
                anomaly_score REAL DEFAULT 0.0
            );
            CREATE INDEX IF NOT EXISTS idx_hs_ts ON health_snapshots(timestamp);

            CREATE TABLE IF NOT EXISTS incident_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                service TEXT NOT NULL,
                event_type TEXT NOT NULL,
                details TEXT DEFAULT '',
                pre_window TEXT DEFAULT '',
                restart_delay REAL DEFAULT 0.0,
                restart_success INTEGER DEFAULT 0,
                cascade_triggered INTEGER DEFAULT 0,
                circuit_state TEXT DEFAULT 'closed'
            );
            CREATE INDEX IF NOT EXISTS idx_inc_svc ON incident_log(service);
            CREATE INDEX IF NOT EXISTS idx_inc_ts ON incident_log(timestamp);

            CREATE TABLE IF NOT EXISTS service_baselines (
                service TEXT PRIMARY KEY,
                mean_cpu REAL DEFAULT 0.0,
                std_cpu REAL DEFAULT 1.0,
                mean_rss REAL DEFAULT 0.0,
                std_rss REAL DEFAULT 1.0,
                mean_response REAL DEFAULT 0.0,
                std_response REAL DEFAULT 1.0,
                mean_uptime REAL DEFAULT 0.0,
                updated_at REAL
            );

            CREATE TABLE IF NOT EXISTS circuit_states (
                service TEXT PRIMARY KEY,
                state TEXT DEFAULT 'closed',
                failure_count INTEGER DEFAULT 0,
                last_transition REAL,
                cooldown_until REAL DEFAULT 0.0,
                last_delay REAL DEFAULT 3.0
            );

            CREATE TABLE IF NOT EXISTS training_meta (
                module TEXT PRIMARY KEY,
                training_steps INTEGER DEFAULT 0,
                last_trained REAL,
                last_loss REAL DEFAULT 0.0
            );

            CREATE TABLE IF NOT EXISTS lifecycle_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                event_type TEXT NOT NULL,
                wave INTEGER DEFAULT -1,
                services TEXT NOT NULL,
                success INTEGER DEFAULT 1,
                duration REAL DEFAULT 0.0
            );
            CREATE INDEX IF NOT EXISTS idx_lc_ts ON lifecycle_events(timestamp);
        """)
        conn.commit()

    # ── Health Snapshots ──────────────────────────────────────────

    def log_snapshot(self, snapshot: Dict[str, Any], is_healthy: bool = True,
                     anomaly_score: float = 0.0):
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO health_snapshots (timestamp, snapshot, is_healthy, anomaly_score) "
            "VALUES (?, ?, ?, ?)",
            (time.time(), json.dumps(snapshot), int(is_healthy), anomaly_score)
        )
        conn.commit()

    def get_healthy_snapshots(self, limit: int = 500) -> List[Dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT snapshot FROM health_snapshots WHERE is_healthy=1 "
            "ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        results = []
        for r in rows:
            try:
                results.append(json.loads(r["snapshot"]))
            except (json.JSONDecodeError, TypeError):
                continue
        return results

    def get_snapshot_count(self, healthy_only: bool = True) -> int:
        conn = self._get_conn()
        if healthy_only:
            row = conn.execute(
                "SELECT COUNT(*) as c FROM health_snapshots WHERE is_healthy=1"
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) as c FROM health_snapshots").fetchone()
        return row["c"]

    # ── Incident Log ──────────────────────────────────────────────

    def log_incident(self, service: str, event_type: str, details: str = "",
                     pre_window: str = "", restart_delay: float = 0.0,
                     restart_success: bool = False, cascade_triggered: bool = False,
                     circuit_state: str = "closed"):
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO incident_log "
            "(timestamp, service, event_type, details, pre_window, restart_delay, "
            "restart_success, cascade_triggered, circuit_state) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (time.time(), service, event_type, details, pre_window, restart_delay,
             int(restart_success), int(cascade_triggered), circuit_state)
        )
        conn.commit()

    def get_incidents(self, service: Optional[str] = None,
                      since: Optional[float] = None,
                      limit: int = 200) -> List[Dict]:
        conn = self._get_conn()
        query = "SELECT * FROM incident_log WHERE 1=1"
        params: list = []
        if service:
            query += " AND service=?"
            params.append(service)
        if since:
            query += " AND timestamp>?"
            params.append(since)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_incident_count(self, service: Optional[str] = None) -> int:
        conn = self._get_conn()
        if service:
            row = conn.execute(
                "SELECT COUNT(*) as c FROM incident_log WHERE service=?", (service,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) as c FROM incident_log").fetchone()
        return row["c"]

    def get_training_windows(self, limit: int = 500) -> List[Tuple[str, int]]:
        """Get (pre_window_json, crashed_within_3_cycles) pairs for AnomalyNet."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT pre_window, event_type FROM incident_log "
            "WHERE pre_window != '' ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        result = []
        for r in rows:
            label = 1 if r["event_type"] in ("crash", "freeze") else 0
            result.append((r["pre_window"], label))
        return result

    # ── Service Baselines ─────────────────────────────────────────

    def update_baseline(self, service: str, mean_cpu: float, std_cpu: float,
                        mean_rss: float, std_rss: float,
                        mean_response: float, std_response: float,
                        mean_uptime: float):
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO service_baselines "
            "(service, mean_cpu, std_cpu, mean_rss, std_rss, "
            "mean_response, std_response, mean_uptime, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (service, mean_cpu, std_cpu, mean_rss, std_rss,
             mean_response, std_response, mean_uptime, time.time())
        )
        conn.commit()

    def get_baseline(self, service: str) -> Optional[Dict]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM service_baselines WHERE service=?", (service,)
        ).fetchone()
        return dict(row) if row else None

    # ── Circuit States ────────────────────────────────────────────

    def save_circuit_state(self, service: str, state: str, failure_count: int,
                           cooldown_until: float, last_delay: float):
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO circuit_states "
            "(service, state, failure_count, last_transition, cooldown_until, last_delay) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (service, state, failure_count, time.time(), cooldown_until, last_delay)
        )
        conn.commit()

    def load_circuit_state(self, service: str) -> Optional[Dict]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM circuit_states WHERE service=?", (service,)
        ).fetchone()
        return dict(row) if row else None

    def load_all_circuit_states(self) -> Dict[str, Dict]:
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM circuit_states").fetchall()
        return {r["service"]: dict(r) for r in rows}

    # ── Training Meta ─────────────────────────────────────────────

    def get_training_steps(self, module: str) -> int:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT training_steps FROM training_meta WHERE module=?", (module,)
        ).fetchone()
        return row["training_steps"] if row else 0

    def update_training_meta(self, module: str, steps: int, loss: float):
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO training_meta "
            "(module, training_steps, last_trained, last_loss) "
            "VALUES (?, ?, ?, ?)",
            (module, steps, time.time(), loss)
        )
        conn.commit()

    # ── Lifecycle Events ──────────────────────────────────────────

    def log_lifecycle(self, event_type: str, wave: int, services: List[str],
                      success: bool, duration: float):
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO lifecycle_events "
            "(timestamp, event_type, wave, services, success, duration) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), event_type, wave, json.dumps(services),
             int(success), duration)
        )
        conn.commit()

    # ── Maintenance ───────────────────────────────────────────────

    def prune_old_data(self, max_age_days: int = 30):
        """Remove data older than max_age_days."""
        cutoff = time.time() - (max_age_days * 86400)
        conn = self._get_conn()
        conn.execute("DELETE FROM health_snapshots WHERE timestamp < ?", (cutoff,))
        conn.execute("DELETE FROM incident_log WHERE timestamp < ?", (cutoff,))
        conn.execute("DELETE FROM lifecycle_events WHERE timestamp < ?", (cutoff,))
        conn.commit()

    def close(self):
        with self._conns_lock:
            for conn in self._conns:
                try:
                    conn.close()
                except Exception:
                    pass
            self._conns.clear()
        self._local.conn = None
