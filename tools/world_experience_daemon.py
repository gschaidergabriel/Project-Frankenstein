#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
world_experience_daemon v2.0.0 - Frank's Resilient Subconscious

Hybrid Epistemic Architecture: Bridges static system knowledge (system_core.json)
with experiential causal learning (world_experience.db).

Transforms Frank from a reactive tool into an antifragile learning partner that
understands causalities without falling into rigid dogmas.

Architecture:
  - Anatomy (system_core.json): Immutable blueprint knowledge ("What am I?")
  - Experience (world_experience.db): Causal memory ("What happens when...?")
    SQLite WAL-mode, 10 GB hard cap.

Key Subsystems:
  1. Enhanced Causal Graph (Entities, CausalLinks, High-Fidelity Fingerprints)
  2. Bayesian Erosion ("Wisdom vs. Ballast", epsilon=0.01)
  3. Anti-Hallucination Continuous Validation
  4. Gaming Mode Passive Telemetry (RAM ring-buffer, post-session analysis)
  5. Structural Versioning & Decay (anatomy hash-sync)
  6. Asymmetric Quantization Tiers (raw -> dense -> sparse)
  7. Confidence Reporting & Mut-Parameter
  8. Heartbeat Flush (15-minute checkpoints for crash resilience)

Database: <AICORE_BASE>/database/world_experience.db
Anatomy: <AICORE_BASE>/database/system_core.json
"""

import collections
import hashlib
import json
import logging
import math
import os
import sqlite3
import struct
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
)
LOG = logging.getLogger("world_experience")

# ---------------------------------------------------------------------------
# Paths & Constants
# ---------------------------------------------------------------------------
try:
    from config.paths import get_db, get_state, DB_DIR as DATABASE_DIR
    DB_PATH = get_db("world_experience")
    ANATOMY_PATH = get_state("system_core")
except ImportError:
    _DATA_DIR = Path.home() / ".local" / "share" / "frank"
    DATABASE_DIR = _DATA_DIR / "db"
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH = DATABASE_DIR / "world_experience.db"
    _STATE_DIR = _DATA_DIR / "state"
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    ANATOMY_PATH = _STATE_DIR / "system_core.json"

# Capacity
MAX_DB_SIZE_BYTES = 10 * 1024 * 1024 * 1024  # 10 GB hard cap
QUANTIZE_THRESHOLD_BYTES = 8 * 1024 * 1024 * 1024  # 8 GB -> start quantizing old data
PURGE_TRIGGER_BYTES = 9 * 1024 * 1024 * 1024  # 9 GB -> aggressive purge

# Erosion
EROSION_EPSILON = 0.01  # Conservative: keep nuances >= 1% evidence change
EROSION_COOLDOWN_SECONDS = 300  # 5 min batch window before erosion runs

# Quantization tiers (days)
TIER_RAW_DAYS = 7       # 0-7 days: raw high-fidelity
TIER_DENSE_DAYS = 90    # 8-90 days: 4-bit asymmetric quantization
                        # >90 days: sparse (Bayesian values + CausalLinks only)

# Gaming mode
RAM_BUFFER_MAX_BYTES = 1 * 1024 * 1024 * 1024  # 1 GB RAM ring-buffer
TELEMETRY_HZ = 5  # Sampling rate during gaming
TELEMETRY_RECORD_SIZE = 640  # ~640 bytes per record at 5 Hz

# Daemon
DAEMON_TICK_SECONDS = 10  # Main loop tick
IDLE_THRESHOLD_SECONDS = 30  # Consider system idle after 30s of low activity
ANATOMY_CHECK_INTERVAL = 60  # Check anatomy hash every 60s

# Heartbeat Flush (crash resilience)
HEARTBEAT_INTERVAL_SECONDS = 900  # 15 minutes - the "sweet spot"

# Mut-Parameter (courage)
DEFAULT_MUT = 0.5  # 0.0 = very cautious, 1.0 = fully proactive

# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class Entity:
    id: int = 0
    entity_type: str = ""       # 'hardware', 'software', 'user_context', 'event'
    name: str = ""
    metadata: Dict = field(default_factory=dict)
    first_seen: str = ""
    last_seen: str = ""
    anatomy_hash: str = ""


@dataclass
class CausalLink:
    id: int = 0
    cause_entity_id: int = 0
    effect_entity_id: int = 0
    relation_type: str = ""     # 'triggers', 'inhibits', 'modulates', 'correlates'
    confidence: float = 0.5     # Bayesian P(H|E)
    weight: float = 1.0
    observation_count: int = 1
    first_observed: str = ""
    last_observed: str = ""
    last_validated: str = ""
    anatomy_hash: str = ""
    status: str = "active"      # 'active', 'legacy', 'invalidated'


@dataclass
class Fingerprint:
    id: int = 0
    causal_link_id: int = 0
    timestamp: str = ""
    thermal_vector: Dict = field(default_factory=dict)
    logical_vector: Dict = field(default_factory=dict)
    temporal_vector: Dict = field(default_factory=dict)
    cross_module_data: Dict = field(default_factory=dict)
    fidelity_level: str = "raw"  # 'raw', 'dense', 'sparse'
    data_size_bytes: int = 0
    anatomy_hash: str = ""


@dataclass
class TelemetryRecord:
    """In-memory telemetry record for gaming mode RAM buffer."""
    timestamp: float
    thermal: Dict = field(default_factory=dict)
    logical: Dict = field(default_factory=dict)
    temporal: Dict = field(default_factory=dict)
    cross_module: Dict = field(default_factory=dict)
    raw_bytes: int = 0


# ---------------------------------------------------------------------------
# Database Layer
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA cache_size=-64000;
PRAGMA temp_store=MEMORY;
PRAGMA mmap_size=268435456;

CREATE TABLE IF NOT EXISTS entities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type     TEXT    NOT NULL,
    name            TEXT    NOT NULL UNIQUE,
    metadata        TEXT    DEFAULT '{}',
    first_seen      TEXT    NOT NULL,
    last_seen       TEXT    NOT NULL,
    anatomy_hash    TEXT    DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);

CREATE TABLE IF NOT EXISTS causal_links (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    cause_entity_id     INTEGER NOT NULL,
    effect_entity_id    INTEGER NOT NULL,
    relation_type       TEXT    NOT NULL,
    confidence          REAL    NOT NULL DEFAULT 0.5,
    weight              REAL    NOT NULL DEFAULT 1.0,
    observation_count   INTEGER NOT NULL DEFAULT 1,
    first_observed      TEXT    NOT NULL,
    last_observed       TEXT    NOT NULL,
    last_validated      TEXT    DEFAULT '',
    anatomy_hash        TEXT    DEFAULT '',
    status              TEXT    NOT NULL DEFAULT 'active',
    FOREIGN KEY (cause_entity_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY (effect_entity_id) REFERENCES entities(id) ON DELETE CASCADE,
    UNIQUE(cause_entity_id, effect_entity_id, relation_type)
);
CREATE INDEX IF NOT EXISTS idx_cl_cause ON causal_links(cause_entity_id);
CREATE INDEX IF NOT EXISTS idx_cl_effect ON causal_links(effect_entity_id);
CREATE INDEX IF NOT EXISTS idx_cl_status ON causal_links(status);
CREATE INDEX IF NOT EXISTS idx_cl_confidence ON causal_links(confidence);

CREATE TABLE IF NOT EXISTS fingerprints (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    causal_link_id      INTEGER,
    timestamp           TEXT    NOT NULL,
    thermal_vector      TEXT    DEFAULT '{}',
    logical_vector      TEXT    DEFAULT '{}',
    temporal_vector     TEXT    DEFAULT '{}',
    cross_module_data   TEXT    DEFAULT '{}',
    fidelity_level      TEXT    NOT NULL DEFAULT 'raw',
    data_size_bytes     INTEGER NOT NULL DEFAULT 0,
    anatomy_hash        TEXT    DEFAULT '',
    FOREIGN KEY (causal_link_id) REFERENCES causal_links(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_fp_timestamp ON fingerprints(timestamp);
CREATE INDEX IF NOT EXISTS idx_fp_fidelity ON fingerprints(fidelity_level);
CREATE INDEX IF NOT EXISTS idx_fp_link ON fingerprints(causal_link_id);

CREATE TABLE IF NOT EXISTS telemetry_buffer (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    timestamp   TEXT    NOT NULL,
    data        TEXT    NOT NULL,
    processed   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tb_session ON telemetry_buffer(session_id);
CREATE INDEX IF NOT EXISTS idx_tb_processed ON telemetry_buffer(processed);

CREATE TABLE IF NOT EXISTS anatomy_versions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    hash            TEXT    NOT NULL UNIQUE,
    timestamp       TEXT    NOT NULL,
    module_count    INTEGER DEFAULT 0,
    diff_summary    TEXT    DEFAULT ''
);

CREATE TABLE IF NOT EXISTS daemon_meta (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL,
    updated TEXT NOT NULL
);
"""


class ExperienceDB:
    """Thread-safe SQLite wrapper for the world experience database."""

    def __init__(self, db_path: Path = DB_PATH):
        self._db_path = db_path
        self._local = threading.local()
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self._db_path),
                timeout=30.0,
                check_same_thread=False,
            )
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    def _init_schema(self):
        conn = self._get_conn()
        conn.executescript(_SCHEMA_SQL)
        conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._get_conn().execute(sql, params)

    def executemany(self, sql: str, params_list: list) -> sqlite3.Cursor:
        return self._get_conn().executemany(sql, params_list)

    def commit(self):
        self._get_conn().commit()

    def fetchone(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        return self.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        return self.execute(sql, params).fetchall()

    def db_size_bytes(self) -> int:
        """Current database file size on disk (main + WAL + SHM)."""
        total = 0
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(self._db_path) + suffix)
            if p.exists():
                total += p.stat().st_size
        return total

    # -- Meta helpers --

    def get_meta(self, key: str, default: str = "") -> str:
        row = self.fetchone("SELECT value FROM daemon_meta WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_meta(self, key: str, value: str):
        now = _now_iso()
        self.execute(
            "INSERT INTO daemon_meta (key, value, updated) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated=excluded.updated",
            (key, value, now),
        )
        self.commit()

    # -- Entity CRUD --

    def upsert_entity(self, entity_type: str, name: str,
                      metadata: Dict = None, anatomy_hash: str = "") -> int:
        now = _now_iso()
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        row = self.fetchone("SELECT id FROM entities WHERE name = ?", (name,))
        if row:
            self.execute(
                "UPDATE entities SET last_seen=?, metadata=?, anatomy_hash=? WHERE id=?",
                (now, meta_json, anatomy_hash, row["id"]),
            )
            self.commit()
            return row["id"]
        else:
            cur = self.execute(
                "INSERT INTO entities (entity_type, name, metadata, first_seen, last_seen, anatomy_hash) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (entity_type, name, meta_json, now, now, anatomy_hash),
            )
            self.commit()
            return cur.lastrowid

    def get_entity(self, name: str) -> Optional[Entity]:
        row = self.fetchone("SELECT * FROM entities WHERE name = ?", (name,))
        if not row:
            return None
        return Entity(
            id=row["id"], entity_type=row["entity_type"], name=row["name"],
            metadata=json.loads(row["metadata"] or "{}"),
            first_seen=row["first_seen"], last_seen=row["last_seen"],
            anatomy_hash=row["anatomy_hash"] or "",
        )

    def get_entities_by_type(self, entity_type: str) -> List[Entity]:
        rows = self.fetchall("SELECT * FROM entities WHERE entity_type = ?", (entity_type,))
        return [
            Entity(
                id=r["id"], entity_type=r["entity_type"], name=r["name"],
                metadata=json.loads(r["metadata"] or "{}"),
                first_seen=r["first_seen"], last_seen=r["last_seen"],
                anatomy_hash=r["anatomy_hash"] or "",
            )
            for r in rows
        ]

    # -- CausalLink CRUD --

    def upsert_causal_link(self, cause_id: int, effect_id: int,
                           relation_type: str, confidence_delta: float = 0.0,
                           anatomy_hash: str = "") -> int:
        now = _now_iso()
        row = self.fetchone(
            "SELECT * FROM causal_links WHERE cause_entity_id=? AND effect_entity_id=? AND relation_type=?",
            (cause_id, effect_id, relation_type),
        )
        if row:
            new_conf = _bayesian_update(row["confidence"], confidence_delta)
            self.execute(
                "UPDATE causal_links SET confidence=?, weight=?, observation_count=observation_count+1, "
                "last_observed=?, anatomy_hash=? WHERE id=?",
                (new_conf, row["weight"] + 0.1, now, anatomy_hash, row["id"]),
            )
            self.commit()
            return row["id"]
        else:
            initial_conf = max(0.01, min(0.99, 0.5 + confidence_delta))
            cur = self.execute(
                "INSERT INTO causal_links "
                "(cause_entity_id, effect_entity_id, relation_type, confidence, weight, "
                " observation_count, first_observed, last_observed, anatomy_hash, status) "
                "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, 'active')",
                (cause_id, effect_id, relation_type, initial_conf, 1.0, now, now, anatomy_hash),
            )
            self.commit()
            return cur.lastrowid

    def get_causal_links_for_entity(self, entity_id: int,
                                    direction: str = "both") -> List[CausalLink]:
        links = []
        if direction in ("cause", "both"):
            rows = self.fetchall(
                "SELECT * FROM causal_links WHERE cause_entity_id = ? AND status = 'active'",
                (entity_id,),
            )
            links.extend(self._rows_to_links(rows))
        if direction in ("effect", "both"):
            rows = self.fetchall(
                "SELECT * FROM causal_links WHERE effect_entity_id = ? AND status = 'active'",
                (entity_id,),
            )
            links.extend(self._rows_to_links(rows))
        return links

    def get_all_links(self, status: str = "active") -> List[CausalLink]:
        rows = self.fetchall("SELECT * FROM causal_links WHERE status = ?", (status,))
        return self._rows_to_links(rows)

    def _rows_to_links(self, rows) -> List[CausalLink]:
        return [
            CausalLink(
                id=r["id"], cause_entity_id=r["cause_entity_id"],
                effect_entity_id=r["effect_entity_id"],
                relation_type=r["relation_type"], confidence=r["confidence"],
                weight=r["weight"], observation_count=r["observation_count"],
                first_observed=r["first_observed"], last_observed=r["last_observed"],
                last_validated=r["last_validated"] or "",
                anatomy_hash=r["anatomy_hash"] or "", status=r["status"],
            )
            for r in rows
        ]

    # -- Fingerprint CRUD --

    def insert_fingerprint(self, fp: Fingerprint) -> int:
        cur = self.execute(
            "INSERT INTO fingerprints "
            "(causal_link_id, timestamp, thermal_vector, logical_vector, temporal_vector, "
            " cross_module_data, fidelity_level, data_size_bytes, anatomy_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fp.causal_link_id, fp.timestamp,
                json.dumps(fp.thermal_vector, ensure_ascii=False),
                json.dumps(fp.logical_vector, ensure_ascii=False),
                json.dumps(fp.temporal_vector, ensure_ascii=False),
                json.dumps(fp.cross_module_data, ensure_ascii=False),
                fp.fidelity_level, fp.data_size_bytes, fp.anatomy_hash,
            ),
        )
        self.commit()
        return cur.lastrowid

    def count_fingerprints(self, fidelity: str = None) -> int:
        if fidelity:
            row = self.fetchone(
                "SELECT COUNT(*) as cnt FROM fingerprints WHERE fidelity_level=?", (fidelity,)
            )
        else:
            row = self.fetchone("SELECT COUNT(*) as cnt FROM fingerprints")
        return row["cnt"] if row else 0

    # -- Anatomy Versions --

    def record_anatomy_version(self, hash_val: str, module_count: int,
                               diff_summary: str = "") -> bool:
        now = _now_iso()
        try:
            self.execute(
                "INSERT INTO anatomy_versions (hash, timestamp, module_count, diff_summary) "
                "VALUES (?, ?, ?, ?)",
                (hash_val, now, module_count, diff_summary),
            )
            self.commit()
            return True
        except sqlite3.IntegrityError:
            return False  # Already recorded

    def get_latest_anatomy_hash(self) -> str:
        row = self.fetchone(
            "SELECT hash FROM anatomy_versions ORDER BY id DESC LIMIT 1"
        )
        return row["hash"] if row else ""


# ---------------------------------------------------------------------------
# Math / Bayesian Utilities
# ---------------------------------------------------------------------------

def _bayesian_update(prior: float, evidence_strength: float) -> float:
    """
    Update Bayesian confidence P(H|E).

    Uses a simplified Bayesian update:
        P(H|E) = P(E|H) * P(H) / P(E)

    evidence_strength > 0 = confirming evidence
    evidence_strength < 0 = contradicting evidence
    """
    prior = max(0.001, min(0.999, prior))
    if abs(evidence_strength) < 1e-9:
        return prior

    # Likelihood ratio based on evidence strength
    if evidence_strength > 0:
        likelihood_ratio = 1.0 + evidence_strength
    else:
        likelihood_ratio = 1.0 / (1.0 - evidence_strength)

    # Convert to odds, update, convert back
    prior_odds = prior / (1.0 - prior)
    posterior_odds = prior_odds * likelihood_ratio
    posterior = posterior_odds / (1.0 + posterior_odds)

    return max(0.001, min(0.999, posterior))


def _anomaly_score(observation: Dict, baseline_links: List[CausalLink]) -> float:
    """
    Score how anomalous an observation is relative to existing causal knowledge.
    Returns 0.0 (perfectly expected) to 1.0 (completely novel).
    """
    if not baseline_links:
        return 1.0  # No prior knowledge -> fully anomalous

    # Average confidence of related links
    avg_conf = sum(lk.confidence for lk in baseline_links) / len(baseline_links)
    # High confidence in existing rules -> observation likely expected
    # Low confidence -> everything is somewhat unexpected
    return 1.0 - avg_conf


def _erosion_value(link: CausalLink, epsilon: float = EROSION_EPSILON) -> float:
    """
    Calculate the erosion value of confirming evidence for a causal link.
    Returns the marginal information gain. If below epsilon, the fingerprint
    is redundant ("ballast") and should be eroded.

    For a link with confidence c observed n times, the marginal information
    gain of one more confirmation decreases as:
        delta_info = (1 - c) / (n + 1)
    """
    c = link.confidence
    n = link.observation_count
    delta_info = (1.0 - c) / (n + 1)
    return delta_info


def _quantize_vector_4bit(vector: Dict) -> Dict:
    """
    Apply 4-bit asymmetric quantization to a fingerprint vector.
    Reduces storage by ~8x while preserving key patterns.
    """
    quantized = {}
    for key, value in vector.items():
        if isinstance(value, (int, float)):
            # 4-bit: 16 levels (0-15)
            # Normalize to [0, 1] then scale to [0, 15]
            # For simplicity, use modular quantization
            qval = int(round(value * 10)) % 16
            quantized[key] = qval
        elif isinstance(value, list):
            quantized[key] = [int(round(v * 10)) % 16 if isinstance(v, (int, float)) else v
                              for v in value[:8]]  # Truncate to 8 elements
        else:
            quantized[key] = value
    return quantized


# ---------------------------------------------------------------------------
# System Telemetry Collectors
# ---------------------------------------------------------------------------

def _collect_thermal() -> Dict:
    """Collect thermal data from system sensors."""
    thermal = {}
    try:
        hwmon_base = Path("/sys/class/hwmon")
        if hwmon_base.exists():
            for hwmon in sorted(hwmon_base.iterdir()):
                name_path = hwmon / "name"
                if name_path.exists():
                    sensor_name = name_path.read_text().strip()
                else:
                    sensor_name = hwmon.name
                for temp_input in sorted(hwmon.glob("temp*_input")):
                    try:
                        val = int(temp_input.read_text().strip()) / 1000.0
                        label_path = temp_input.parent / temp_input.name.replace("_input", "_label")
                        if label_path.exists():
                            label = label_path.read_text().strip()
                        else:
                            label = temp_input.stem
                        thermal[f"{sensor_name}/{label}"] = round(val, 1)
                    except (ValueError, OSError):
                        continue
    except OSError:
        pass
    return thermal


def _collect_logical() -> Dict:
    """Collect logical system state (CPU, memory, load)."""
    logical = {}
    try:
        # Load average
        with open("/proc/loadavg") as f:
            parts = f.read().split()
            logical["load_1m"] = float(parts[0])
            logical["load_5m"] = float(parts[1])
            logical["load_15m"] = float(parts[2])
            logical["running_procs"] = parts[3]
    except (OSError, IndexError, ValueError):
        pass
    try:
        # Memory
        with open("/proc/meminfo") as f:
            meminfo = {}
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip().split()[0]
                    meminfo[key] = int(val)
            if "MemTotal" in meminfo and "MemAvailable" in meminfo:
                logical["mem_total_kb"] = meminfo["MemTotal"]
                logical["mem_avail_kb"] = meminfo["MemAvailable"]
                logical["mem_usage_pct"] = round(
                    100.0 * (1.0 - meminfo["MemAvailable"] / meminfo["MemTotal"]), 1
                )
    except (OSError, ValueError, KeyError, ZeroDivisionError):
        pass
    try:
        # CPU stat snapshot
        with open("/proc/stat") as f:
            line = f.readline()
            parts = line.split()
            if parts[0] == "cpu":
                logical["cpu_user"] = int(parts[1])
                logical["cpu_system"] = int(parts[3])
                logical["cpu_idle"] = int(parts[4])
    except (OSError, IndexError, ValueError):
        pass
    return logical


def _collect_temporal() -> Dict:
    """Collect temporal context."""
    now = datetime.now()
    temporal = {
        "hour": now.hour,
        "minute": now.minute,
        "weekday": now.isoweekday(),  # 1=Mon, 7=Sun
        "day_of_month": now.day,
        "month": now.month,
        "is_weekend": now.isoweekday() >= 6,
    }
    try:
        with open("/proc/uptime") as f:
            temporal["uptime_seconds"] = float(f.read().split()[0])
    except (OSError, IndexError, ValueError):
        pass
    return temporal


def _collect_cross_module() -> Dict:
    """Collect cross-module interference data (active processes, I/O)."""
    xmod = {}
    try:
        with open("/proc/diskstats") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 14 and parts[2] in ("sda", "nvme0n1", "vda"):
                    xmod[f"disk_{parts[2]}_reads"] = int(parts[3])
                    xmod[f"disk_{parts[2]}_writes"] = int(parts[7])
    except (OSError, IndexError, ValueError):
        pass
    try:
        # Count active processes
        proc_count = sum(1 for p in Path("/proc").iterdir()
                         if p.name.isdigit())
        xmod["active_processes"] = proc_count
    except OSError:
        pass
    return xmod


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compute_anatomy_hash() -> Tuple[str, int]:
    """Compute SHA-256 hash of system_core.json and return (hash, module_count)."""
    if not ANATOMY_PATH.exists():
        return "", 0
    try:
        content = ANATOMY_PATH.read_bytes()
        h = hashlib.sha256(content).hexdigest()
        data = json.loads(content)
        module_count = data.get("total_modules", 0)
        return h, module_count
    except (OSError, json.JSONDecodeError) as exc:
        LOG.warning("Failed to hash anatomy: %s", exc)
        return "", 0


def _estimate_record_size(record: Dict) -> int:
    """Estimate bytes for a telemetry record."""
    return len(json.dumps(record, ensure_ascii=False).encode("utf-8"))


# ---------------------------------------------------------------------------
# RAM Ring Buffer for Gaming Mode
# ---------------------------------------------------------------------------

class TelemetryRingBuffer:
    """
    Lock-free-ish ring buffer in RAM for gaming mode passive telemetry.
    Capacity: ~1 GB. At 5 Hz with ~640 B/record -> ~93 hours.
    """

    def __init__(self, max_bytes: int = RAM_BUFFER_MAX_BYTES):
        self._max_bytes = max_bytes
        self._current_bytes = 0
        self._buffer: Deque[TelemetryRecord] = collections.deque()
        self._lock = threading.Lock()
        self._session_id = ""
        self._overflow_count = 0

    def start_session(self) -> str:
        self._session_id = str(uuid.uuid4())[:12]
        self._overflow_count = 0
        LOG.info("Telemetry session started: %s", self._session_id)
        return self._session_id

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def current_bytes(self) -> int:
        return self._current_bytes

    @property
    def record_count(self) -> int:
        return len(self._buffer)

    def push(self, record: TelemetryRecord):
        """Add record to ring buffer, evicting oldest if over capacity."""
        with self._lock:
            self._buffer.append(record)
            self._current_bytes += record.raw_bytes
            # Evict oldest if over capacity
            while self._current_bytes > self._max_bytes and self._buffer:
                evicted = self._buffer.popleft()
                self._current_bytes -= evicted.raw_bytes
                self._overflow_count += 1

    def drain(self) -> List[TelemetryRecord]:
        """Drain all records from buffer. Returns list and clears buffer."""
        with self._lock:
            records = list(self._buffer)
            self._buffer.clear()
            self._current_bytes = 0
            return records

    def stats(self) -> Dict:
        return {
            "session_id": self._session_id,
            "record_count": len(self._buffer),
            "current_bytes": self._current_bytes,
            "max_bytes": self._max_bytes,
            "usage_pct": round(100.0 * self._current_bytes / self._max_bytes, 2)
            if self._max_bytes > 0 else 0.0,
            "overflow_count": self._overflow_count,
            "capacity_hours": round(
                (self._max_bytes - self._current_bytes) /
                max(1, TELEMETRY_RECORD_SIZE * TELEMETRY_HZ * 3600), 1
            ),
        }


# ---------------------------------------------------------------------------
# World Experience Daemon
# ---------------------------------------------------------------------------

class WorldExperienceDaemon:
    """
    The resilient subconscious: learns causal relationships from system
    observations and maintains an antifragile world model.
    """

    def __init__(self, db_path: Path = DB_PATH, mut: float = DEFAULT_MUT):
        self.db = ExperienceDB(db_path)
        self._mut = max(0.0, min(1.0, mut))
        self._running = False
        self._gaming_mode = False
        self._thread: Optional[threading.Thread] = None
        self._ring_buffer = TelemetryRingBuffer()
        self._telemetry_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._last_anatomy_hash = ""
        self._last_erosion_time = 0.0
        self._last_anatomy_check = 0.0
        self._last_heartbeat_flush = 0.0
        self._idle_counter = 0
        self._lock = threading.Lock()

        # Crash recovery check on startup
        self._crash_recovery_check()

        # Load persisted state
        self._load_state()
        LOG.info(
            "WorldExperienceDaemon v2.0.0 initialized (mut=%.2f, db=%s)",
            self._mut, db_path,
        )

    # -- Properties --

    @property
    def mut(self) -> float:
        return self._mut

    @mut.setter
    def mut(self, value: float):
        self._mut = max(0.0, min(1.0, value))
        self.db.set_meta("mut_parameter", str(self._mut))

    @property
    def gaming_mode(self) -> bool:
        return self._gaming_mode

    @property
    def is_running(self) -> bool:
        return self._running

    # -- State Management --

    def _load_state(self):
        mut_str = self.db.get_meta("mut_parameter", str(DEFAULT_MUT))
        try:
            self._mut = float(mut_str)
        except ValueError:
            pass
        self._last_anatomy_hash = self.db.get_latest_anatomy_hash()

    # -- Crash Recovery (Heartbeat Flush) --

    def _crash_recovery_check(self):
        """
        Crash recovery logic on startup.

        Checks if an unclean shutdown occurred and repairs:
        1. WAL recovery: SQLite repairs itself with .db-wal
        2. Buffer check: Checks telemetry_buffer for unprocessed data
        3. Anatomy validation: Ensures integrity
        """
        LOG.info("Crash recovery check started...")

        # 1. WAL recovery: SQLite does this automatically on first connect
        # We force a checkpoint to materialize WAL data
        try:
            self.db.execute("PRAGMA wal_checkpoint(PASSIVE);")
            LOG.debug("WAL checkpoint performed")
        except Exception as e:
            LOG.warning("WAL checkpoint failed: %s", e)

        # 2. Buffer check: Check for unprocessed telemetry data
        try:
            unprocessed = self.db.fetchone(
                "SELECT COUNT(*) as cnt FROM telemetry_buffer WHERE processed = 0"
            )
            if unprocessed and unprocessed["cnt"] > 0:
                LOG.info(
                    "Crash recovery: %d unprocessed telemetry entries found",
                    unprocessed["cnt"]
                )
                # Mark old unprocessed entries for later analysis
                self.db.execute(
                    "UPDATE telemetry_buffer SET processed = -1 "
                    "WHERE processed = 0 AND timestamp < datetime('now', '-1 hour')"
                )
                self.db.commit()
        except Exception as e:
            LOG.warning("Buffer check failed: %s", e)

        # 3. Anatomy validation: Check for corrupt entries
        try:
            corrupt = self.db.fetchone(
                "SELECT COUNT(*) as cnt FROM anatomy_versions WHERE hash = '' OR hash IS NULL"
            )
            if corrupt and corrupt["cnt"] > 0:
                LOG.warning(
                    "Crash recovery: %d corrupt anatomy entries removed",
                    corrupt["cnt"]
                )
                self.db.execute("DELETE FROM anatomy_versions WHERE hash = '' OR hash IS NULL")
                self.db.commit()
        except Exception as e:
            LOG.warning("Anatomy validation failed: %s", e)

        # 4. Check gaming mode status
        gaming_status = self.db.get_meta("gaming_mode", "inactive")
        if gaming_status == "active":
            LOG.warning(
                "Crash recovery: Gaming mode was active during crash. "
                "Last 15 minutes may be lost."
            )
            self.db.set_meta("gaming_mode", "inactive")
            self.db.set_meta("last_crash_recovery", _now_iso())

        LOG.info("Crash recovery check completed")

    def _heartbeat_checkpoint(self):
        """
        Heartbeat Flush: Saves RAM telemetry to SSD every 15 minutes.

        The "sweet spot" of 15 minutes:
        - Data loss minimization: Max. 15 min loss on power failure
        - I/O preservation: Barely measurable SSD wear
        - WAL management: Prevents gigantic .db-wal files
        """
        LOG.debug("Heartbeat-Thread gestartet (Intervall: %ds)", HEARTBEAT_INTERVAL_SECONDS)

        while self._running:
            time.sleep(HEARTBEAT_INTERVAL_SECONDS)

            if not self._running:
                break

            # Only during active gaming mode with data in buffer
            if self._gaming_mode and self._ring_buffer.record_count > 0:
                try:
                    LOG.info(
                        "Heartbeat: Saving RAM telemetry to SSD... "
                        "(%d records, %s)",
                        self._ring_buffer.record_count,
                        _human_size(self._ring_buffer.current_bytes)
                    )

                    # Save telemetry snapshot to DB (without clearing buffer)
                    self._flush_telemetry_snapshot()

                    # Force WAL checkpoint to push data from .db-wal to .db
                    self.db.execute("PRAGMA wal_checkpoint(PASSIVE);")
                    self.db.commit()

                    self._last_heartbeat_flush = time.time()
                    self.db.set_meta("last_heartbeat_flush", _now_iso())

                    LOG.info("Heartbeat: Checkpoint successful")

                except Exception as e:
                    LOG.error("Heartbeat flush failed: %s", e)

        LOG.debug("Heartbeat thread ended")

    def _flush_telemetry_snapshot(self):
        """
        Saves a snapshot of current telemetry to the DB.
        The ring buffer is NOT cleared (that happens on gaming-off).
        """
        session_id = self._ring_buffer.session_id
        if not session_id:
            return

        # Get current records (without clearing)
        with self._ring_buffer._lock:
            records = list(self._ring_buffer._buffer)

        if not records:
            return

        # Save aggregated statistics as checkpoint
        now = _now_iso()
        stats = self._ring_buffer.stats()

        # Compressed JSON snapshot of recent records (max 100)
        recent_records = records[-100:] if len(records) > 100 else records
        snapshot_data = {
            "checkpoint_type": "heartbeat",
            "session_id": session_id,
            "timestamp": now,
            "total_records": len(records),
            "buffer_stats": stats,
            "recent_samples": [
                {
                    "ts": rec.timestamp,
                    "thermal": rec.thermal,
                    "logical": rec.logical,
                }
                for rec in recent_records[-10:]  # Only last 10 for checkpoint
            ]
        }

        # Save to telemetry_buffer (for recovery)
        self.db.execute(
            "INSERT INTO telemetry_buffer (session_id, timestamp, data, processed) "
            "VALUES (?, ?, ?, 0)",
            (session_id, now, json.dumps(snapshot_data, ensure_ascii=False))
        )
        self.db.commit()

    # -- Anatomy Sync (Structural Versioning) --

    def check_anatomy(self) -> Dict:
        """
        Check system_core.json for structural changes.
        On mismatch: trigger Causal Context Invalidation.
        Returns dict with status info.
        """
        current_hash, module_count = _compute_anatomy_hash()
        if not current_hash:
            return {"status": "no_anatomy", "message": "system_core.json not found"}

        stored_hash = self._last_anatomy_hash

        if stored_hash == current_hash:
            return {"status": "unchanged", "hash": current_hash}

        # Mismatch detected! Record new version and invalidate
        LOG.info(
            "Anatomy change detected: %s -> %s (%d modules)",
            stored_hash[:16] if stored_hash else "NONE",
            current_hash[:16],
            module_count,
        )

        # Compute diff summary
        diff_summary = self._compute_anatomy_diff(stored_hash, current_hash)

        # Record new version
        self.db.record_anatomy_version(current_hash, module_count, diff_summary)
        self._last_anatomy_hash = current_hash

        # Causal Context Invalidation
        invalidated = self._invalidate_stale_links(stored_hash, current_hash)

        return {
            "status": "changed",
            "old_hash": stored_hash[:16] if stored_hash else "NONE",
            "new_hash": current_hash[:16],
            "module_count": module_count,
            "links_invalidated": invalidated,
            "diff": diff_summary,
        }

    def _compute_anatomy_diff(self, old_hash: str, new_hash: str) -> str:
        """Try to describe what changed in the anatomy."""
        if not old_hash:
            return "Initial anatomy registration"
        try:
            data = json.loads(ANATOMY_PATH.read_text())
            modules = data.get("modules", {})
            pending = data.get("pending_changes", [])
            if pending:
                return f"Pending changes: {', '.join(pending[:5])}"
            return f"Anatomy updated ({len(modules)} modules)"
        except (OSError, json.JSONDecodeError):
            return "Anatomy hash changed"

    def _invalidate_stale_links(self, old_hash: str, new_hash: str) -> int:
        """
        Causal Context Invalidation: when anatomy changes, lower confidence
        of links tied to the old anatomy instead of deleting them.
        Marks them as 'legacy' for re-validation.
        """
        if not old_hash:
            return 0

        # Find links tied to the old anatomy
        rows = self.db.fetchall(
            "SELECT id, confidence FROM causal_links WHERE anatomy_hash = ? AND status = 'active'",
            (old_hash,),
        )
        if not rows:
            return 0

        count = 0
        now = _now_iso()
        for row in rows:
            # Confidence reset to 0.1 (not deletion)
            self.db.execute(
                "UPDATE causal_links SET confidence = 0.1, status = 'legacy', "
                "last_validated = ? WHERE id = ?",
                (now, row["id"]),
            )
            count += 1
        self.db.commit()

        LOG.info(
            "Causal Context Invalidation: %d links degraded to legacy (hash %s)",
            count, old_hash[:16],
        )
        return count

    # -- Observation & Learning --

    def observe(self, cause_name: str, effect_name: str,
                cause_type: str = "software", effect_type: str = "software",
                relation: str = "triggers", evidence: float = 0.1,
                metadata_cause: Dict = None, metadata_effect: Dict = None) -> Dict:
        """
        Record a causal observation: cause -> effect.
        The core learning primitive.
        """
        anatomy_hash = self._last_anatomy_hash

        # Upsert entities
        cause_id = self.db.upsert_entity(cause_type, cause_name, metadata_cause, anatomy_hash)
        effect_id = self.db.upsert_entity(effect_type, effect_name, metadata_effect, anatomy_hash)

        # Upsert causal link with Bayesian update
        link_id = self.db.upsert_causal_link(
            cause_id, effect_id, relation, evidence, anatomy_hash
        )

        # Collect fingerprint
        fp = self._build_fingerprint(link_id, anatomy_hash)

        # Erosion decision: is this fingerprint worth keeping?
        link_row = self.db.fetchone("SELECT * FROM causal_links WHERE id = ?", (link_id,))
        link = self.db._rows_to_links([link_row])[0] if link_row else None

        stored_fp = False
        if link:
            erosion_val = _erosion_value(link, EROSION_EPSILON)
            related_links = self.db.get_causal_links_for_entity(cause_id, "cause")
            anom_score = _anomaly_score(
                {"cause": cause_name, "effect": effect_name}, related_links
            )

            if anom_score > 0.5:
                # Anomaly path: store with highest priority
                fp.fidelity_level = "raw"
                self.db.insert_fingerprint(fp)
                stored_fp = True
                LOG.debug("Anomaly stored (score=%.2f): %s -> %s", anom_score, cause_name, effect_name)
            elif erosion_val >= EROSION_EPSILON:
                # Worth storing: marginal info gain above threshold
                fp.fidelity_level = "raw"
                self.db.insert_fingerprint(fp)
                stored_fp = True
            else:
                # Redundant ("ballast"): confidence already updated via Bayesian,
                # no need to store the raw fingerprint
                LOG.debug(
                    "Erosion: fingerprint eroded (delta_info=%.4f < epsilon=%.4f) for %s->%s",
                    erosion_val, EROSION_EPSILON, cause_name, effect_name,
                )

        # Capacity check
        self._check_capacity()

        return {
            "cause_id": cause_id,
            "effect_id": effect_id,
            "link_id": link_id,
            "confidence": link.confidence if link else 0.5,
            "fingerprint_stored": stored_fp,
            "anatomy_hash": anatomy_hash[:16] if anatomy_hash else "",
        }

    def _build_fingerprint(self, link_id: int, anatomy_hash: str) -> Fingerprint:
        """Build a high-fidelity fingerprint from current system state."""
        thermal = _collect_thermal()
        logical = _collect_logical()
        temporal = _collect_temporal()
        cross_mod = _collect_cross_module()

        fp = Fingerprint(
            causal_link_id=link_id,
            timestamp=_now_iso(),
            thermal_vector=thermal,
            logical_vector=logical,
            temporal_vector=temporal,
            cross_module_data=cross_mod,
            fidelity_level="raw",
            anatomy_hash=anatomy_hash,
        )
        fp.data_size_bytes = _estimate_record_size({
            "thermal": thermal, "logical": logical,
            "temporal": temporal, "cross_module": cross_mod,
        })
        return fp

    # -- Erosion & Quantization --

    def run_erosion(self, force: bool = False) -> Dict:
        """
        Run the erosion algorithm: "Wisdom vs. Ballast".
        Quantizes old data and purges if over capacity.
        """
        now = time.time()
        if not force and (now - self._last_erosion_time) < EROSION_COOLDOWN_SECONDS:
            return {"status": "cooldown", "next_in": int(EROSION_COOLDOWN_SECONDS - (now - self._last_erosion_time))}

        self._last_erosion_time = now
        stats = {"quantized_dense": 0, "quantized_sparse": 0, "purged": 0}

        # Tier 1: Raw -> Dense (7-90 days old)
        cutoff_dense = (datetime.now(timezone.utc) - timedelta(days=TIER_RAW_DAYS)).isoformat()
        cutoff_sparse = (datetime.now(timezone.utc) - timedelta(days=TIER_DENSE_DAYS)).isoformat()

        # Quantize raw fingerprints older than 7 days to dense
        rows = self.db.fetchall(
            "SELECT id, thermal_vector, logical_vector, temporal_vector, cross_module_data "
            "FROM fingerprints WHERE fidelity_level = 'raw' AND timestamp < ?",
            (cutoff_dense,),
        )
        for row in rows:
            try:
                thermal_q = _quantize_vector_4bit(json.loads(row["thermal_vector"] or "{}"))
                logical_q = _quantize_vector_4bit(json.loads(row["logical_vector"] or "{}"))
                temporal = json.loads(row["temporal_vector"] or "{}")  # Keep temporal as-is
                cross_q = _quantize_vector_4bit(json.loads(row["cross_module_data"] or "{}"))
                new_size = _estimate_record_size({
                    "t": thermal_q, "l": logical_q, "T": temporal, "x": cross_q
                })
                self.db.execute(
                    "UPDATE fingerprints SET thermal_vector=?, logical_vector=?, "
                    "cross_module_data=?, fidelity_level='dense', data_size_bytes=? WHERE id=?",
                    (
                        json.dumps(thermal_q), json.dumps(logical_q),
                        json.dumps(cross_q), new_size, row["id"],
                    ),
                )
                stats["quantized_dense"] += 1
            except (json.JSONDecodeError, TypeError):
                continue

        # Tier 2: Dense -> Sparse (>90 days old) - strip vectors, keep only link refs
        rows = self.db.fetchall(
            "SELECT id FROM fingerprints WHERE fidelity_level = 'dense' AND timestamp < ?",
            (cutoff_sparse,),
        )
        for row in rows:
            self.db.execute(
                "UPDATE fingerprints SET thermal_vector='{}', logical_vector='{}', "
                "temporal_vector='{}', cross_module_data='{}', "
                "fidelity_level='sparse', data_size_bytes=64 WHERE id=?",
                (row["id"],),
            )
            stats["quantized_sparse"] += 1

        self.db.commit()

        # Capacity purge if needed
        db_size = self.db.db_size_bytes()
        if db_size > PURGE_TRIGGER_BYTES:
            stats["purged"] = self._capacity_purge(db_size)

        LOG.info(
            "Erosion complete: dense=%d, sparse=%d, purged=%d (db=%s)",
            stats["quantized_dense"], stats["quantized_sparse"], stats["purged"],
            _human_size(self.db.db_size_bytes()),
        )
        return stats

    def _check_capacity(self):
        """Quick capacity check; triggers erosion if needed."""
        db_size = self.db.db_size_bytes()
        if db_size > QUANTIZE_THRESHOLD_BYTES:
            LOG.warning("DB size %.1f GB approaching limit, triggering erosion", db_size / (1024**3))
            self.run_erosion(force=True)

    def _capacity_purge(self, current_size: int) -> int:
        """
        Emergency purge: delete oldest sparse fingerprints and low-confidence
        invalidated links until under the purge threshold.
        """
        purged = 0
        target = QUANTIZE_THRESHOLD_BYTES  # Aim to get back to 8 GB

        # Phase 1: Delete sparse fingerprints (oldest first)
        if current_size > target:
            rows = self.db.fetchall(
                "SELECT id FROM fingerprints WHERE fidelity_level = 'sparse' "
                "ORDER BY timestamp ASC LIMIT 10000"
            )
            ids = [r["id"] for r in rows]
            if ids:
                placeholders = ",".join("?" * len(ids))
                self.db.execute(
                    f"DELETE FROM fingerprints WHERE id IN ({placeholders})", tuple(ids)
                )
                self.db.commit()
                purged += len(ids)

        # Phase 2: Delete invalidated causal links with very low confidence
        current_size = self.db.db_size_bytes()
        if current_size > target:
            self.db.execute(
                "DELETE FROM causal_links WHERE status = 'invalidated' AND confidence < 0.05"
            )
            self.db.commit()

        # Phase 3: Vacuum to reclaim space
        try:
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.OperationalError:
            pass

        return purged

    # -- Gaming Mode --

    def enter_gaming_mode(self) -> Dict:
        """
        Switch to gaming mode: "observing coma".
        - Disable active learning/pattern recognition
        - Start passive telemetry to RAM ring buffer
        - No disk I/O
        """
        with self._lock:
            if self._gaming_mode:
                return {"status": "already_active", "session": self._ring_buffer.session_id}

            self._gaming_mode = True
            session_id = self._ring_buffer.start_session()
            self.db.set_meta("gaming_mode", "active")
            self.db.set_meta("gaming_session_id", session_id)

            # Start low-priority telemetry collection thread
            self._telemetry_thread = threading.Thread(
                target=self._telemetry_loop,
                name="wed-telemetry",
                daemon=True,
            )
            self._telemetry_thread.start()

            LOG.info("Gaming mode ACTIVATED (session=%s). Active learning suspended.", session_id)
            return {"status": "activated", "session": session_id}

    def exit_gaming_mode(self) -> Dict:
        """
        Exit gaming mode. Triggers post-session analysis.
        Telemetry data is flushed from RAM to DB asynchronously.
        """
        with self._lock:
            if not self._gaming_mode:
                return {"status": "not_active"}

            self._gaming_mode = False
            self.db.set_meta("gaming_mode", "inactive")

            # Drain ring buffer
            records = self._ring_buffer.drain()
            session_id = self._ring_buffer.session_id
            overflow = self._ring_buffer._overflow_count

            LOG.info(
                "Gaming mode DEACTIVATED (session=%s). %d records collected (%d overflowed). "
                "Starting post-session analysis.",
                session_id, len(records), overflow,
            )

        # Post-session analysis in background
        if records:
            t = threading.Thread(
                target=self._post_session_analysis,
                args=(session_id, records),
                name="wed-post-session",
                daemon=True,
            )
            t.start()

        return {
            "status": "deactivated",
            "session": session_id,
            "records_collected": len(records),
            "overflow_count": overflow,
            "post_analysis": "started" if records else "skipped",
        }

    def _telemetry_loop(self):
        """Low-priority telemetry collection during gaming mode."""
        interval = 1.0 / TELEMETRY_HZ
        LOG.debug("Telemetry loop started (%.1f Hz)", TELEMETRY_HZ)

        while self._gaming_mode:
            try:
                thermal = _collect_thermal()
                logical = _collect_logical()
                temporal = _collect_temporal()
                cross_mod = _collect_cross_module()

                data = {
                    "thermal": thermal, "logical": logical,
                    "temporal": temporal, "cross_module": cross_mod,
                }
                raw_bytes = _estimate_record_size(data)

                record = TelemetryRecord(
                    timestamp=time.time(),
                    thermal=thermal,
                    logical=logical,
                    temporal=temporal,
                    cross_module=cross_mod,
                    raw_bytes=raw_bytes,
                )
                self._ring_buffer.push(record)
            except Exception as exc:
                LOG.debug("Telemetry collection error: %s", exc)

            time.sleep(interval)

        LOG.debug("Telemetry loop stopped")

    def _post_session_analysis(self, session_id: str, records: List[TelemetryRecord]):
        """
        Post-session analysis ("Das Nachgluehen"):
        Analyze gaming session telemetry for causal patterns.
        Runs asynchronously after gaming mode ends.
        """
        LOG.info("Post-session analysis started for %s (%d records)", session_id, len(records))
        anatomy_hash = self._last_anatomy_hash

        if not records:
            return

        # Aggregate statistics from the session
        temps_max = {}
        temps_min = {}
        load_samples = []
        mem_samples = []

        for rec in records:
            # Track thermal extremes
            for sensor, val in rec.thermal.items():
                if isinstance(val, (int, float)):
                    temps_max[sensor] = max(temps_max.get(sensor, float("-inf")), val)
                    temps_min[sensor] = min(temps_min.get(sensor, float("inf")), val)

            # Track load
            load_1m = rec.logical.get("load_1m")
            if load_1m is not None:
                load_samples.append(load_1m)

            mem_pct = rec.logical.get("mem_usage_pct")
            if mem_pct is not None:
                mem_samples.append(mem_pct)

        # Detect thermal anomalies
        for sensor, max_temp in temps_max.items():
            if max_temp > 85.0:  # Critical threshold
                self.observe(
                    cause_name=f"gaming_session_{session_id}",
                    effect_name=f"thermal_critical_{sensor}",
                    cause_type="event",
                    effect_type="hardware",
                    relation="triggers",
                    evidence=0.3,
                    metadata_cause={"session_id": session_id, "type": "gaming"},
                    metadata_effect={"sensor": sensor, "max_temp": max_temp},
                )

        # Detect sustained high load
        if load_samples:
            avg_load = sum(load_samples) / len(load_samples)
            max_load = max(load_samples)
            if avg_load > 4.0:  # Sustained high load
                self.observe(
                    cause_name=f"gaming_session_{session_id}",
                    effect_name="sustained_high_load",
                    cause_type="event",
                    effect_type="software",
                    relation="triggers",
                    evidence=0.2,
                    metadata_cause={"session_id": session_id},
                    metadata_effect={"avg_load": round(avg_load, 2), "max_load": round(max_load, 2)},
                )

        # Detect memory pressure
        if mem_samples:
            avg_mem = sum(mem_samples) / len(mem_samples)
            max_mem = max(mem_samples)
            if max_mem > 90.0:
                self.observe(
                    cause_name=f"gaming_session_{session_id}",
                    effect_name="memory_pressure",
                    cause_type="event",
                    effect_type="hardware",
                    relation="triggers",
                    evidence=0.25,
                    metadata_cause={"session_id": session_id},
                    metadata_effect={"avg_mem_pct": round(avg_mem, 1), "max_mem_pct": round(max_mem, 1)},
                )

        # Store a summary fingerprint for the entire session
        summary_fp = Fingerprint(
            causal_link_id=0,
            timestamp=_now_iso(),
            thermal_vector={"max": temps_max, "min": temps_min},
            logical_vector={
                "load_avg": round(sum(load_samples) / len(load_samples), 2) if load_samples else 0,
                "load_max": round(max(load_samples), 2) if load_samples else 0,
                "mem_avg": round(sum(mem_samples) / len(mem_samples), 1) if mem_samples else 0,
                "mem_max": round(max(mem_samples), 1) if mem_samples else 0,
            },
            temporal_vector={
                "session_id": session_id,
                "record_count": len(records),
                "duration_seconds": round(records[-1].timestamp - records[0].timestamp, 1)
                if len(records) > 1 else 0,
            },
            cross_module_data={"source": "post_session_analysis"},
            fidelity_level="raw",
            anatomy_hash=anatomy_hash,
        )
        summary_fp.data_size_bytes = _estimate_record_size({
            "t": summary_fp.thermal_vector, "l": summary_fp.logical_vector,
            "T": summary_fp.temporal_vector, "x": summary_fp.cross_module_data,
        })
        self.db.insert_fingerprint(summary_fp)

        LOG.info(
            "Post-session analysis complete for %s: %d records analyzed, "
            "%d thermal sensors tracked",
            session_id, len(records), len(temps_max),
        )

    # -- Counterfactual Simulation (Idle Processing) --

    def run_idle_simulation(self) -> Dict:
        """
        Asynchronous simulation during idle phases:
        - Re-validate legacy links
        - Check for contradictions in the causal graph
        - Prune invalidated links that can't be re-confirmed
        """
        if self._gaming_mode:
            return {"status": "gaming_mode", "message": "Idle simulation skipped during gaming"}

        results = {"revalidated": 0, "pruned": 0, "contradictions": 0}

        # Re-validate legacy links
        legacy_links = self.db.get_all_links(status="legacy")
        for link in legacy_links[:50]:  # Process in batches
            # Check if the cause and effect entities still exist in anatomy
            cause = self.db.fetchone("SELECT * FROM entities WHERE id = ?", (link.cause_entity_id,))
            effect = self.db.fetchone("SELECT * FROM entities WHERE id = ?", (link.effect_entity_id,))

            if not cause or not effect:
                # Entities gone -> mark link as invalidated
                self.db.execute(
                    "UPDATE causal_links SET status = 'invalidated' WHERE id = ?",
                    (link.id,),
                )
                results["pruned"] += 1
                continue

            # Check if link has been re-observed since becoming legacy
            if link.last_observed > link.last_validated and link.observation_count > 3:
                # Re-confirmed under new anatomy -> restore to active
                self.db.execute(
                    "UPDATE causal_links SET status = 'active', confidence = ?, "
                    "last_validated = ? WHERE id = ?",
                    (min(0.7, link.confidence + 0.2), _now_iso(), link.id),
                )
                results["revalidated"] += 1
            elif link.confidence < 0.05:
                # Confidence eroded below threshold -> prune
                self.db.execute(
                    "UPDATE causal_links SET status = 'invalidated' WHERE id = ?",
                    (link.id,),
                )
                results["pruned"] += 1

        # Check for contradictions (A->B triggers AND A->B inhibits)
        rows = self.db.fetchall(
            "SELECT cause_entity_id, effect_entity_id, COUNT(DISTINCT relation_type) as rtypes "
            "FROM causal_links WHERE status = 'active' "
            "GROUP BY cause_entity_id, effect_entity_id HAVING rtypes > 1"
        )
        for row in rows:
            # Conflicting relations -> lower confidence of the weaker one
            conflicting = self.db.fetchall(
                "SELECT id, relation_type, confidence FROM causal_links "
                "WHERE cause_entity_id = ? AND effect_entity_id = ? AND status = 'active' "
                "ORDER BY confidence ASC",
                (row["cause_entity_id"], row["effect_entity_id"]),
            )
            if len(conflicting) >= 2:
                weaker = conflicting[0]
                self.db.execute(
                    "UPDATE causal_links SET confidence = confidence * 0.5 WHERE id = ?",
                    (weaker["id"],),
                )
                results["contradictions"] += 1

        self.db.commit()

        if any(v > 0 for v in results.values()):
            LOG.info("Idle simulation: revalidated=%d, pruned=%d, contradictions=%d",
                     results["revalidated"], results["pruned"], results["contradictions"])
        return results

    # -- Confidence & Mut Reporting --

    def query_confidence(self, cause_name: str, effect_name: str) -> Dict:
        """
        Query the system's confidence in a cause-effect relationship.
        Returns evidence-based reporting per the spec.
        """
        cause = self.db.get_entity(cause_name)
        effect = self.db.get_entity(effect_name)

        if not cause or not effect:
            return {
                "known": False,
                "confidence": 0.0,
                "message": f"No experience with the relationship '{cause_name}' -> '{effect_name}'.",
                "mut_action": "ask" if self._mut < 0.5 else "hypothesize",
            }

        # Find the link
        row = self.db.fetchone(
            "SELECT * FROM causal_links WHERE cause_entity_id = ? AND effect_entity_id = ? "
            "AND status = 'active' ORDER BY confidence DESC LIMIT 1",
            (cause.id, effect.id),
        )

        if not row:
            return {
                "known": False,
                "confidence": 0.0,
                "message": f"No causal relationship known between '{cause_name}' and '{effect_name}'.",
                "mut_action": "ask" if self._mut < 0.5 else "hypothesize",
            }

        link = self.db._rows_to_links([row])[0]

        # Build evidence-based message
        conf_pct = int(link.confidence * 100)
        obs = link.observation_count

        if conf_pct >= 80:
            msg = (f"I am very confident ({conf_pct}% evidence, {obs} observations): "
                   f"'{cause_name}' {link.relation_type} '{effect_name}'.")
        elif conf_pct >= 50:
            msg = (f"I have moderate evidence ({conf_pct}%, {obs} observations) that "
                   f"'{cause_name}' {link.relation_type} '{effect_name}'.")
        elif conf_pct >= 30:
            msg = (f"I see context '{cause_name}' -> '{effect_name}', "
                   f"but only have {conf_pct}% evidence ({obs} observations).")
        else:
            msg = (f"Weak hypothesis ({conf_pct}% evidence): '{cause_name}' might "
                   f"influence '{effect_name}', but I am uncertain.")

        # Mut-based action
        if self._mut >= 0.7 and conf_pct >= 50:
            action = "act_proactive"
        elif self._mut >= 0.4:
            action = "suggest"
        else:
            action = "report_only"

        return {
            "known": True,
            "confidence": link.confidence,
            "confidence_pct": conf_pct,
            "observations": obs,
            "relation": link.relation_type,
            "status": link.status,
            "message": msg,
            "mut_action": action,
            "hypothetical": conf_pct < 50 and self._mut >= 0.7,
        }

    # -- Context Injection (Feedback Loop / Self-Reflection) --

    def context_inject(self, user_message: str, max_items: int = 3) -> str:
        """
        Feedback loop: Query the world model for knowledge relevant to the
        user's message and return a formatted context snippet for prompt injection.

        This closes the one-way-street gap: Frank now checks his own experiential
        database before answering, treating it as part of his own mind rather than
        an external tool.

        Args:
            user_message: The raw user message to find relevant knowledge for.
            max_items: Maximum number of causal insights to inject.

        Returns:
            Formatted context string, or "" if nothing relevant found.
        """
        if not user_message or not user_message.strip():
            return ""

        keywords = self._extract_keywords(user_message)
        if not keywords:
            return ""

        # Search entities matching any keyword
        relevant_links = []
        seen_link_ids = set()

        for kw in keywords:
            rows = self.db.fetchall(
                "SELECT id, name FROM entities WHERE name LIKE ? OR metadata LIKE ?",
                (f"%{kw}%", f"%{kw}%"),
            )
            for row in rows:
                entity_id = row["id"]
                links = self.db.get_causal_links_for_entity(entity_id)
                for link in links:
                    if link.id not in seen_link_ids and link.status == "active":
                        seen_link_ids.add(link.id)
                        relevant_links.append(link)

        if not relevant_links:
            return ""

        # Sort by confidence * weight (most relevant first)
        relevant_links.sort(key=lambda lk: lk.confidence * lk.weight, reverse=True)
        top_links = relevant_links[:max_items]

        # Build human-readable context
        lines = []
        for link in top_links:
            cause_row = self.db.fetchone("SELECT name FROM entities WHERE id = ?", (link.cause_entity_id,))
            effect_row = self.db.fetchone("SELECT name FROM entities WHERE id = ?", (link.effect_entity_id,))
            if cause_row and effect_row:
                conf_pct = int(link.confidence * 100)
                cause_name = cause_row["name"]
                effect_name = effect_row["name"]
                lines.append(
                    f"- {cause_name} {link.relation_type} {effect_name} "
                    f"({conf_pct}% confidence, observed {link.observation_count}x)"
                )

        if not lines:
            return ""

        header = "[Your experiential memory (world_experience.db) on this topic:"
        return f"{header}\n" + "\n".join(lines) + "]\n"

    def _extract_keywords(self, message: str) -> List[str]:
        """Extract meaningful keywords from a user message for knowledge lookup."""
        import re
        # Lowercase and strip
        msg = message.lower().strip()

        # Remove common German stop words
        stop_words = {
            "ich", "du", "er", "sie", "es", "wir", "ihr", "und", "oder", "aber",
            "der", "die", "das", "den", "dem", "des", "ein", "eine", "einem", "einen",
            "ist", "sind", "war", "hat", "haben", "wird", "werden", "kann", "nicht",
            "mit", "von", "auf", "fuer", "für", "als", "auch", "noch", "schon",
            "wie", "was", "wer", "wo", "wann", "warum", "wenn", "dann", "denn",
            "nur", "mal", "mir", "mich", "dir", "dich", "sich", "bitte", "danke",
            "hast", "bist", "sein", "mein", "dein", "zum", "zur", "vom", "beim",
            "über", "ueber", "nach", "vor", "neben", "zwischen", "durch", "ohne",
            "gegen", "unter", "hinter", "dass", "weil", "obwohl", "welche", "welcher",
            "diese", "dieser", "dieses", "jetzt", "hier", "dort", "immer", "nie",
            "viel", "mehr", "sehr", "ganz", "gerade", "eigentlich", "sag", "sage",
            "zeig", "zeige", "mach", "mache", "kannst", "koenntest", "könntest",
        }

        # Split into words, remove punctuation
        words = re.findall(r'[a-zäöüß]+', msg)
        keywords = [w for w in words if len(w) >= 3 and w not in stop_words]

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique.append(kw)
        return unique[:10]  # Max 10 keywords

    # -- Summary & Stats --

    def get_summary(self) -> Dict:
        """Get a comprehensive summary of the world model state."""
        db_size = self.db.db_size_bytes()

        entity_counts = {}
        for etype in ("hardware", "software", "user_context", "event"):
            row = self.db.fetchone(
                "SELECT COUNT(*) as cnt FROM entities WHERE entity_type = ?", (etype,)
            )
            entity_counts[etype] = row["cnt"] if row else 0

        link_counts = {}
        for status in ("active", "legacy", "invalidated"):
            row = self.db.fetchone(
                "SELECT COUNT(*) as cnt FROM causal_links WHERE status = ?", (status,)
            )
            link_counts[status] = row["cnt"] if row else 0

        fp_counts = {}
        for fidelity in ("raw", "dense", "sparse"):
            fp_counts[fidelity] = self.db.count_fingerprints(fidelity)

        avg_conf_row = self.db.fetchone(
            "SELECT AVG(confidence) as avg_c FROM causal_links WHERE status = 'active'"
        )
        avg_confidence = round(avg_conf_row["avg_c"], 3) if avg_conf_row and avg_conf_row["avg_c"] else 0.0

        return {
            "version": "2.0.0",
            "db_size_bytes": db_size,
            "db_size_human": _human_size(db_size),
            "db_capacity_pct": round(100.0 * db_size / MAX_DB_SIZE_BYTES, 2),
            "entities": entity_counts,
            "entities_total": sum(entity_counts.values()),
            "causal_links": link_counts,
            "links_total": sum(link_counts.values()),
            "fingerprints": fp_counts,
            "fingerprints_total": sum(fp_counts.values()),
            "avg_confidence": avg_confidence,
            "mut_parameter": self._mut,
            "gaming_mode": self._gaming_mode,
            "anatomy_hash": self._last_anatomy_hash[:16] if self._last_anatomy_hash else "none",
            "erosion_epsilon": EROSION_EPSILON,
            "last_erosion": datetime.fromtimestamp(self._last_erosion_time).isoformat()
            if self._last_erosion_time > 0 else "never",
            "heartbeat_interval_sec": HEARTBEAT_INTERVAL_SECONDS,
            "last_heartbeat_flush": datetime.fromtimestamp(self._last_heartbeat_flush).isoformat()
            if self._last_heartbeat_flush > 0 else "never",
        }

    def get_top_links(self, limit: int = 20) -> List[Dict]:
        """Get the highest-confidence causal links."""
        rows = self.db.fetchall(
            "SELECT cl.*, e1.name as cause_name, e2.name as effect_name "
            "FROM causal_links cl "
            "JOIN entities e1 ON cl.cause_entity_id = e1.id "
            "JOIN entities e2 ON cl.effect_entity_id = e2.id "
            "WHERE cl.status = 'active' "
            "ORDER BY cl.confidence DESC LIMIT ?",
            (limit,),
        )
        return [
            {
                "cause": r["cause_name"],
                "effect": r["effect_name"],
                "relation": r["relation_type"],
                "confidence": round(r["confidence"], 3),
                "observations": r["observation_count"],
                "last_observed": r["last_observed"],
            }
            for r in rows
        ]

    # -- Daemon Lifecycle --

    def start(self):
        """Start the background daemon thread."""
        if self._running:
            LOG.warning("Daemon already running")
            return

        self._running = True

        # Main daemon thread
        self._thread = threading.Thread(
            target=self._daemon_loop,
            name="world-experience-daemon",
            daemon=True,
        )
        self._thread.start()

        # Heartbeat thread for 15-minute checkpoints
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_checkpoint,
            name="wed-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

        LOG.info(
            "WorldExperienceDaemon started (heartbeat interval: %ds)",
            HEARTBEAT_INTERVAL_SECONDS
        )

    def stop(self):
        """Stop the daemon gracefully."""
        LOG.info("Stopping WorldExperienceDaemon...")
        self._running = False

        # Cleanly end gaming mode (including final flush)
        if self._gaming_mode:
            self.exit_gaming_mode()

        # Final WAL checkpoint before shutdown
        try:
            LOG.info("Final WAL checkpoint...")
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            self.db.commit()
        except Exception as e:
            LOG.warning("Final checkpoint failed: %s", e)

        # Stop threads
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=5)
        if self._thread:
            self._thread.join(timeout=15)

        LOG.info("WorldExperienceDaemon stopped")

    def _daemon_loop(self):
        """Main daemon loop: periodic tasks."""
        LOG.info("Daemon loop started (tick=%ds)", DAEMON_TICK_SECONDS)

        tick_count = 0
        while self._running:
            try:
                tick_count += 1

                # Anatomy check (every ANATOMY_CHECK_INTERVAL seconds)
                now = time.time()
                if (now - self._last_anatomy_check) >= ANATOMY_CHECK_INTERVAL:
                    self._last_anatomy_check = now
                    result = self.check_anatomy()
                    if result.get("status") == "changed":
                        LOG.info("Anatomy sync: %s", result)

                # Periodic erosion (every ~30 ticks = ~5 min)
                if tick_count % 30 == 0 and not self._gaming_mode:
                    self.run_erosion()

                # Idle simulation (every ~60 ticks = ~10 min, only when idle)
                if tick_count % 60 == 0 and not self._gaming_mode:
                    self.run_idle_simulation()

            except Exception as exc:
                LOG.error("Daemon tick error: %s", exc, exc_info=True)

            time.sleep(DAEMON_TICK_SECONDS)

        LOG.info("Daemon loop exited")


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _human_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    else:
        return f"{size_bytes / (1024 ** 3):.2f} GB"


# ---------------------------------------------------------------------------
# Singleton / Global Access
# ---------------------------------------------------------------------------

_daemon_instance: Optional[WorldExperienceDaemon] = None
_instance_lock = threading.Lock()


def get_daemon() -> WorldExperienceDaemon:
    """Get or create the global daemon instance."""
    global _daemon_instance
    with _instance_lock:
        if _daemon_instance is None:
            _daemon_instance = WorldExperienceDaemon()
        return _daemon_instance


def context_inject(user_message: str, max_items: int = 3) -> str:
    """
    Module-level convenience: query the world model for relevant causal
    knowledge and return a prompt-injectable context string.

    Usage from chat_overlay.py:
        from world_experience_daemon import context_inject
        world_ctx = context_inject(user_message)
        if world_ctx:
            ctx_parts.append(world_ctx)
    """
    try:
        daemon = get_daemon()
        return daemon.context_inject(user_message, max_items=max_items)
    except Exception as exc:
        LOG.debug("context_inject failed: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# CLI Interface
# ---------------------------------------------------------------------------

def _cli_main():
    import argparse

    parser = argparse.ArgumentParser(
        description="world_experience_daemon v2.0.0 - Frank's World Model",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  start           Start the daemon (foreground)
  summary         Show world model summary
  observe         Record a causal observation
  query           Query confidence for a cause-effect pair
  erosion         Run erosion algorithm
  anatomy         Check anatomy sync status
  simulate        Run idle simulation (counterfactual analysis)
  gaming-on       Enter gaming mode
  gaming-off      Exit gaming mode
  top             Show top causal links
  mut             Get/set the Mut-Parameter (courage)
  dbsize          Show database size info
        """,
    )
    parser.add_argument("command", nargs="?", default="summary",
                        help="Command to execute")
    parser.add_argument("--cause", help="Cause entity name")
    parser.add_argument("--effect", help="Effect entity name")
    parser.add_argument("--relation", default="triggers",
                        help="Relation type (triggers, inhibits, modulates, correlates)")
    parser.add_argument("--evidence", type=float, default=0.1,
                        help="Evidence strength (-1.0 to 1.0)")
    parser.add_argument("--cause-type", default="software",
                        help="Cause entity type")
    parser.add_argument("--effect-type", default="software",
                        help="Effect entity type")
    parser.add_argument("--mut", type=float, help="Set Mut-Parameter (0.0-1.0)")
    parser.add_argument("--limit", type=int, default=20, help="Limit for top links")
    parser.add_argument("--force", action="store_true", help="Force operation")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()
    daemon = get_daemon()

    def _output(data: Any):
        if args.json:
            print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        elif isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, dict):
                    print(f"  {k}:")
                    for k2, v2 in v.items():
                        print(f"    {k2}: {v2}")
                else:
                    print(f"  {k}: {v}")
        else:
            print(data)

    cmd = args.command.lower().replace("-", "_")

    if cmd == "start":
        print("WorldExperienceDaemon v2.0.0 starting (foreground)...")
        print(f"  Database: {DB_PATH}")
        print(f"  Anatomy:  {ANATOMY_PATH}")
        print(f"  Mut:      {daemon.mut}")
        print(f"  Epsilon:  {EROSION_EPSILON}")
        print(f"  DB Cap:   {_human_size(MAX_DB_SIZE_BYTES)}")
        print()
        daemon.check_anatomy()
        daemon.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down...")
            daemon.stop()

    elif cmd == "summary":
        print("=== World Experience Model v2.0.0 ===")
        _output(daemon.get_summary())

    elif cmd == "observe":
        if not args.cause or not args.effect:
            print("ERROR: --cause and --effect required")
            sys.exit(1)
        result = daemon.observe(
            cause_name=args.cause,
            effect_name=args.effect,
            cause_type=args.cause_type,
            effect_type=args.effect_type,
            relation=args.relation,
            evidence=args.evidence,
        )
        print("=== Observation Recorded ===")
        _output(result)

    elif cmd == "query":
        if not args.cause or not args.effect:
            print("ERROR: --cause and --effect required")
            sys.exit(1)
        result = daemon.query_confidence(args.cause, args.effect)
        print("=== Confidence Report ===")
        _output(result)

    elif cmd == "erosion":
        print("Running erosion algorithm...")
        result = daemon.run_erosion(force=args.force)
        _output(result)

    elif cmd == "anatomy":
        print("=== Anatomy Sync ===")
        result = daemon.check_anatomy()
        _output(result)

    elif cmd == "simulate":
        print("Running idle simulation (counterfactual analysis)...")
        result = daemon.run_idle_simulation()
        _output(result)

    elif cmd in ("gaming_on", "gaming"):
        result = daemon.enter_gaming_mode()
        print("=== Gaming Mode ===")
        _output(result)

    elif cmd == "gaming_off":
        result = daemon.exit_gaming_mode()
        print("=== Gaming Mode Exit ===")
        _output(result)

    elif cmd == "top":
        links = daemon.get_top_links(limit=args.limit)
        print(f"=== Top {len(links)} Causal Links ===")
        for i, lk in enumerate(links, 1):
            print(f"  {i:2d}. [{lk['confidence']:.1%}] {lk['cause']} --{lk['relation']}--> "
                  f"{lk['effect']} ({lk['observations']} obs)")

    elif cmd == "mut":
        if args.mut is not None:
            daemon.mut = args.mut
            print(f"Mut-Parameter set to {daemon.mut:.2f}")
        else:
            print(f"Mut-Parameter: {daemon.mut:.2f}")
            if daemon.mut >= 0.7:
                print("  Mode: Proactive (acts at >= 50% evidence)")
            elif daemon.mut >= 0.4:
                print("  Mode: Balanced (suggests, asks when uncertain)")
            else:
                print("  Mode: Cautious (reports only, does not act independently)")

    elif cmd == "dbsize":
        size = daemon.db.db_size_bytes()
        print(f"Database: {_human_size(size)}")
        print(f"Capacity: {100.0 * size / MAX_DB_SIZE_BYTES:.2f}% of {_human_size(MAX_DB_SIZE_BYTES)}")

    else:
        print(f"Unknown command: {args.command}")
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    _cli_main()
