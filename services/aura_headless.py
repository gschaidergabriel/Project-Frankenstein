#!/usr/bin/env python3
"""
AURA Headless Introspect — Franks visuelle Selbstwahrnehmung als strukturierte Daten.

Conway's Game of Life (256x256) simulation where 8 zones map to Frank's
subsystems. Real service data seeds the grid. Pattern detection reveals
stability (still-lifes), processing (oscillators), and information flow (gliders).

Frank can read this via /introspect at any time — no vision model needed.

Port: 8098
RAM:  < 20 MB
CPU:  Minimal (GoL on 256x256 numpy array)
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import threading
import time
import urllib.request
import urllib.error
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
LOG = logging.getLogger("aura_headless")

# --- Config ---
GRID_SIZE = 256
TICK_HZ = 10  # GoL steps per second
SEED_INTERVAL_S = 5.0  # Re-seed from services every N seconds

# Resolve data paths
try:
    from config.paths import get_db, AICORE_DATA
except ImportError:
    AICORE_DATA = Path.home() / ".local" / "share" / "frank"
    def get_db(name):
        return AICORE_DATA / "db" / f"{name}.db"

# Service URLs
QUANTUM_URL = os.environ.get("AURA_QUANTUM_URL", "http://127.0.0.1:8097")

# --- Zone definitions ---
# Each zone occupies a region of the 256x256 grid
ZONE_BOUNDS: Dict[str, Tuple[int, int, int, int]] = {
    # 4×2 equal grid (64w × 128h each) — matches overlay renderer layout
    "epq":      (0,   0,   64,  128),   # top-left
    "mood":     (64,  0,   128, 128),   # top-center-left
    "thoughts": (128, 0,   192, 128),   # top-center-right
    "entities": (192, 0,   256, 128),   # top-right
    "ego":      (0,   128, 64,  256),   # bottom-left
    "quantum":  (64,  128, 128, 256),   # bottom-center-left
    "memory":   (128, 128, 192, 256),   # bottom-center-right
    "hw":       (192, 128, 256, 256),   # bottom-right
}

# Zone display labels (dynamic, updated from state)
ZONE_LABELS = {
    "epq": "processing", "mood": "emotional", "thoughts": "flowing",
    "entities": "idle", "ego": "anchored", "quantum": "nominal",
    "memory": "consolidating", "hw": "nominal",
}

# Known GoL patterns as numpy arrays
PATTERNS = {
    "block":   np.array([[1, 1], [1, 1]], dtype=np.uint8),
    "beehive": np.array([[0, 1, 1, 0], [1, 0, 0, 1], [0, 1, 1, 0]], dtype=np.uint8),
    "blinker": np.array([[1, 1, 1]], dtype=np.uint8),
    "toad":    np.array([[0, 1, 1, 1], [1, 1, 1, 0]], dtype=np.uint8),
    "glider":  np.array([[0, 1, 0], [0, 0, 1], [1, 1, 1]], dtype=np.uint8),
}


# --- Pattern detection (pure numpy, no scipy) ---

def _count_pattern(region: np.ndarray, pattern: np.ndarray) -> int:
    """Count occurrences of a GoL pattern in a region via sliding window."""
    ph, pw = pattern.shape
    rh, rw = region.shape
    if rh < ph or rw < pw:
        return 0
    target = int(pattern.sum())
    count = 0
    # Sliding window with step=2 for performance (patterns don't overlap much)
    for y in range(0, rh - ph + 1, 2):
        for x in range(0, rw - pw + 1, 2):
            window = region[y:y+ph, x:x+pw]
            if int((window * pattern).sum()) == target:
                count += 1
    return count


# --- Data fetching (from real services) ---

def _read_db_value(db_name: str, query: str, default=None):
    """Safely read a single value from a SQLite database."""
    try:
        db_path = get_db(db_name)
        if not db_path.exists():
            return default
        conn = sqlite3.connect(str(db_path), timeout=2.0)
        conn.row_factory = sqlite3.Row
        row = conn.execute(query).fetchone()
        conn.close()
        if row:
            return row[0] if len(row) == 1 else dict(row)
        return default
    except Exception:
        return default


def _http_get(url: str, timeout: float = 2.0) -> Optional[dict]:
    """Quick HTTP GET, returns JSON dict or None."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def _get_cpu_temp() -> int:
    """Read CPU temperature from hwmon."""
    try:
        for hwmon in Path("/sys/class/hwmon").iterdir():
            name_file = hwmon / "name"
            if name_file.exists() and "k10temp" in name_file.read_text():
                temp_file = hwmon / "temp1_input"
                if temp_file.exists():
                    return int(temp_file.read_text().strip()) // 1000
        # Fallback: any temp1_input
        for hwmon in Path("/sys/class/hwmon").iterdir():
            temp_file = hwmon / "temp1_input"
            if temp_file.exists():
                return int(temp_file.read_text().strip()) // 1000
    except Exception:
        pass
    return 0


def _get_ram_usage() -> float:
    """Get RAM usage as fraction 0..1."""
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
        info = {}
        for line in lines:
            parts = line.split()
            if len(parts) >= 2:
                info[parts[0].rstrip(":")] = int(parts[1])
        total = info.get("MemTotal", 1)
        available = info.get("MemAvailable", total)
        return 1.0 - (available / total)
    except Exception:
        return 0.0


# --- Quantum dynamics constants ---
DIFFUSION_RATE = 0.04       # How fast type distributions blend with neighbors
DECOHERENCE_RATE = 0.002    # How fast dominant types sharpen over time
NUM_TYPES = 8               # Number of subsystem types

# Zone colors (RGB 0-1 float) — must match overlay renderer
ZONE_COLORS_RGB = np.array([
    [0.0, 0.7, 1.0],    # 0=epq: Electric Cyan Blue
    [1.0, 0.5, 0.0],    # 1=mood: Deep Amber
    [0.0, 1.0, 0.3],    # 2=thoughts: Neon Green
    [1.0, 0.0, 0.8],    # 3=entities: Hot Magenta
    [1.0, 0.85, 0.0],   # 4=ego: Bright Gold
    [0.0, 1.0, 1.0],    # 5=quantum: Pure Cyan
    [0.7, 0.3, 1.0],    # 6=memory: Electric Violet
    [1.0, 0.2, 0.1],    # 7=hw: Neon Red
], dtype=np.float32)


# --- AURA Headless Core (Quantum) ---

class AuraHeadless:
    """Quantum-enhanced AURA — Conway GoL with type superposition and diffusion.

    Each cell has:
    - Binary alive/dead state (standard Conway B3/S23)
    - type_dist[8]: probability distribution across 8 subsystem types
      A cell born in the Thoughts zone starts as [0,0,1,0,0,0,0,0].
      As it interacts with neighbors, probabilities diffuse:
      [0,0,0.7,0,0,0,0.2,0.1] = mostly Thought, some Memory, hint of HW.
    - Quantum color: weighted blend of zone colors by type_dist
    """

    # Zone name → type index
    ZONE_IDS = {"epq": 0, "mood": 1, "thoughts": 2, "entities": 3,
                "ego": 4, "quantum": 5, "memory": 6, "hw": 7}

    def __init__(self, size: int = GRID_SIZE):
        self.size = size
        self.generation = 0
        self.history: deque = deque(maxlen=100)
        self.start_time = time.time()

        # Cached service data (updated every SEED_INTERVAL_S)
        self.mood = 0.0
        self.coherence = 0.0
        self.hw_temp = 0
        self.ram_usage = 0.0
        self.epq_vectors: Dict[str, float] = {}
        self.energy_level = 0.5
        self.thought_count = 0
        self.entity_active = ""

        self._lock = threading.Lock()
        self._last_seed_time = 0.0

        # Zone map: static assignment (cell → home zone)
        self.zone_map = np.zeros((size, size), dtype=np.uint8)
        for zone_name, (x1, y1, x2, y2) in ZONE_BOUNDS.items():
            self.zone_map[y1:y2, x1:x2] = self.ZONE_IDS[zone_name]

        # ── Binary grid (Conway state) ──
        self.grid = (np.random.random((size, size)) < 0.05).astype(np.uint8)

        # ── Quantum state: type probability distribution per cell ──
        # type_dist[y, x, t] = probability that cell (y,x) is of type t
        self.type_dist = np.zeros((size, size, NUM_TYPES), dtype=np.float32)
        # Initialize: each alive cell gets 100% of its home zone type
        for zone_name, (x1, y1, x2, y2) in ZONE_BOUNDS.items():
            zone_id = self.ZONE_IDS[zone_name]
            alive_in_zone = self.grid[y1:y2, x1:x2] == 1
            self.type_dist[y1:y2, x1:x2, zone_id][alive_in_zone] = 1.0

        # ── Precomputed quantum color map (updated each tick) ──
        # quantum_colors[y, x, 3] = blended RGB from type_dist × zone colors
        self.quantum_colors = np.zeros((size, size, 3), dtype=np.float32)
        self._update_quantum_colors()

    def tick(self):
        """One quantum GoL step: Conway + type diffusion + decoherence."""
        with self._lock:
            old_grid = self.grid.copy()

            # 1. Standard Conway step (binary birth/death)
            self.grid = self._conway_step(self.grid)

            # 2. Quantum type diffusion
            self._diffuse_types(old_grid)

            # 3. Decoherence (dominant type slowly sharpens)
            self._decohere()

            # 4. Update blended quantum colors
            self._update_quantum_colors()

            self.generation += 1

            # Re-seed from services periodically
            now = time.time()
            if now - self._last_seed_time >= SEED_INTERVAL_S:
                self._seed_from_services()
                self._last_seed_time = now

            self.history.append(self._snapshot_stats())

    def _conway_step(self, grid: np.ndarray) -> np.ndarray:
        """Standard Conway's Game of Life (B3/S23)."""
        neighbors = np.zeros_like(grid, dtype=np.int16)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if di == 0 and dj == 0:
                    continue
                neighbors += np.roll(np.roll(grid, di, 0), dj, 1)
        return ((neighbors == 3) | ((grid == 1) & (neighbors == 2))).astype(np.uint8)

    def _diffuse_types(self, old_grid: np.ndarray):
        """Quantum type propagation: alive cells blend type_dist with neighbors."""
        births = (self.grid == 1) & (old_grid == 0)
        deaths = (self.grid == 0) & (old_grid == 1)
        surviving = (self.grid == 1) & (old_grid == 1)

        # Compute neighbor-weighted type average
        neighbor_types = np.zeros_like(self.type_dist)
        neighbor_count = np.zeros((self.size, self.size), dtype=np.float32)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if di == 0 and dj == 0:
                    continue
                shifted_types = np.roll(np.roll(self.type_dist, di, 0), dj, 1)
                shifted_alive = np.roll(np.roll(old_grid, di, 0), dj, 1).astype(np.float32)
                neighbor_types += shifted_types * shifted_alive[:, :, np.newaxis]
                neighbor_count += shifted_alive

        # Avoid division by zero
        safe_count = np.maximum(neighbor_count, 1.0)[:, :, np.newaxis]
        neighbor_avg = neighbor_types / safe_count

        # Surviving cells: blend slightly toward neighbors (diffusion)
        if surviving.any():
            surv_3d = surviving[:, :, np.newaxis]
            self.type_dist = np.where(
                surv_3d,
                self.type_dist * (1.0 - DIFFUSION_RATE) + neighbor_avg * DIFFUSION_RATE,
                self.type_dist,
            )

        # Newborn cells: inherit type from alive neighbors
        if births.any():
            birth_has_neighbors = births & (neighbor_count > 0)
            self.type_dist[birth_has_neighbors] = neighbor_avg[birth_has_neighbors]
            # Births with no alive neighbors (shouldn't happen in Conway) → zone default
            birth_no_neighbors = births & (neighbor_count == 0)
            if birth_no_neighbors.any():
                for zone_name, (x1, y1, x2, y2) in ZONE_BOUNDS.items():
                    zone_id = self.ZONE_IDS[zone_name]
                    local_births = birth_no_neighbors[y1:y2, x1:x2]
                    if local_births.any():
                        default = np.zeros(NUM_TYPES, dtype=np.float32)
                        default[zone_id] = 1.0
                        self.type_dist[y1:y2, x1:x2][local_births] = default

        # Dead cells: fade type_dist (ghost trail)
        if deaths.any():
            self.type_dist[deaths] *= 0.5

        # Zero out completely dead cells after fade
        long_dead = (self.grid == 0)
        self.type_dist[long_dead] *= 0.9  # slow fade for dead cells

        # Normalize alive cells
        alive = self.grid == 1
        if alive.any():
            sums = self.type_dist[alive].sum(axis=1, keepdims=True)
            sums[sums == 0] = 1.0
            self.type_dist[alive] = self.type_dist[alive] / sums

    def _decohere(self):
        """Decoherence: dominant type slowly strengthens (superposition decays)."""
        alive = self.grid == 1
        if not alive.any():
            return
        alive_dist = self.type_dist[alive]
        dominant_idx = alive_dist.argmax(axis=1)
        # Boost dominant type slightly
        boost = np.zeros_like(alive_dist)
        boost[np.arange(len(dominant_idx)), dominant_idx] = DECOHERENCE_RATE
        alive_dist = alive_dist + boost
        # Re-normalize
        sums = alive_dist.sum(axis=1, keepdims=True)
        sums[sums == 0] = 1.0
        self.type_dist[alive] = alive_dist / sums

    def _update_quantum_colors(self):
        """Compute per-cell blended RGB from type_dist × zone colors."""
        # type_dist: (256,256,8), ZONE_COLORS_RGB: (8,3)
        # Result: (256,256,3) — weighted sum
        self.quantum_colors = np.einsum('ijk,kl->ijl', self.type_dist, ZONE_COLORS_RGB)

    def _seed_from_services(self):
        """Inject real subsystem data as living cells into zones."""
        self._fetch_mood()
        self._fetch_epq()
        self._fetch_quantum()
        self._fetch_hardware()
        self._fetch_thoughts()
        self._fetch_entities()

        epq_activity = sum(abs(v) for v in self.epq_vectors.values()) / max(len(self.epq_vectors), 1)
        self._seed_zone("epq", epq_activity)
        self._seed_zone("mood", abs(self.mood) * 0.8 + 0.1)
        thought_activity = min(self.thought_count / 10.0, 1.0)
        self._seed_zone("thoughts", thought_activity * 0.6 + 0.05)
        entity_activity = 0.6 if self.entity_active else 0.05
        self._seed_zone("entities", entity_activity)
        self._seed_zone("ego", self.energy_level * 0.5 + 0.1)
        self._seed_zone("quantum", self.coherence * 0.6 + 0.1)
        self._seed_zone("memory", 0.15 + abs(self.mood) * 0.2)
        hw_stress = (self.hw_temp / 100.0) * 0.4 + self.ram_usage * 0.3
        self._seed_zone("hw", min(hw_stress, 0.8))

    def _seed_zone(self, zone: str, intensity: float):
        """Inject cells with quantum type initialization."""
        x1, y1, x2, y2 = ZONE_BOUNDS[zone]
        zone_id = self.ZONE_IDS[zone]
        region = self.grid[y1:y2, x1:x2]
        density = region.sum() / region.size
        if density < intensity:
            seed_count = int((intensity - density) * region.size * 0.05)
            for _ in range(min(seed_count, 100)):
                ry = np.random.randint(0, y2 - y1)
                rx = np.random.randint(0, x2 - x1)
                cy, cx = y1 + ry, x1 + rx
                if self.grid[cy, cx] == 0:
                    self.grid[cy, cx] = 1
                    # New cell: 100% home zone type (pure superposition)
                    self.type_dist[cy, cx] = 0.0
                    self.type_dist[cy, cx, zone_id] = 1.0
        if intensity > 0.3 and np.random.random() < 0.3:
            self._inject_random_pattern(zone)

    def _inject_random_pattern(self, zone: str):
        """Place a GoL pattern with quantum type initialization."""
        x1, y1, x2, y2 = ZONE_BOUNDS[zone]
        zone_id = self.ZONE_IDS[zone]
        pattern_name = np.random.choice(list(PATTERNS.keys()))
        pattern = PATTERNS[pattern_name]
        ph, pw = pattern.shape
        zw, zh = x2 - x1, y2 - y1
        if zw > pw + 2 and zh > ph + 2:
            px = np.random.randint(0, zw - pw)
            py = np.random.randint(0, zh - ph)
            # Find newly born cells from pattern injection
            region = self.grid[y1+py:y1+py+ph, x1+px:x1+px+pw]
            new_cells = (pattern == 1) & (region == 0)
            self.grid[y1+py:y1+py+ph, x1+px:x1+px+pw] |= pattern
            # Initialize type for new cells
            self.type_dist[y1+py:y1+py+ph, x1+px:x1+px+pw, zone_id][new_cells] = 1.0

    def _fetch_mood(self):
        """Read mood from consciousness DB."""
        val = _read_db_value(
            "consciousness",
            "SELECT mood_value FROM mood_trajectory ORDER BY id DESC LIMIT 1",
            0.0
        )
        if val is not None:
            self.mood = float(val)

    def _fetch_epq(self):
        """Read E-PQ personality vectors via module."""
        try:
            from personality.e_pq import get_personality_context
            ctx = get_personality_context()
            if ctx and "vectors" in ctx:
                self.epq_vectors = {k: float(v) for k, v in ctx["vectors"].items()}
            if ctx and "mood_value" in ctx:
                self.mood = float(ctx["mood_value"])
            self.energy_level = 0.5 + self.mood * 0.3  # Derive from mood
        except Exception:
            pass
        if not self.epq_vectors:
            self.epq_vectors = {"precision": 0.0, "empathy": 0.0, "risk": 0.0}

    def _fetch_quantum(self):
        """Read coherence from Quantum Reflector API."""
        data = _http_get(f"{QUANTUM_URL}/status")
        if data and "last_snapshot" in data:
            snap = data["last_snapshot"]
            # Normalize energy to 0..1 coherence (lower energy = more coherent)
            energy = snap.get("energy", 0)
            self.coherence = max(0.0, min(1.0, (-energy) / 30.0))

    def _fetch_hardware(self):
        """Read hardware state."""
        self.hw_temp = _get_cpu_temp()
        self.ram_usage = _get_ram_usage()

    def _fetch_thoughts(self):
        """Count recent reflections from consciousness DB."""
        val = _read_db_value(
            "consciousness",
            "SELECT COUNT(*) FROM reflections WHERE timestamp > " + str(time.time() - 3600),
            0
        )
        self.thought_count = int(val) if val else 0

    def _fetch_entities(self):
        """Check if any entity is currently active."""
        # Check entity session recency
        val = _read_db_value(
            "therapist",
            "SELECT MAX(timestamp) FROM sessions",
            0
        )
        if val and time.time() - float(val) < 300:
            self.entity_active = "therapist"
            return
        for name in ("mirror", "atlas", "muse"):
            val = _read_db_value(
                name,
                "SELECT MAX(timestamp) FROM sessions",
                0
            )
            if val and time.time() - float(val) < 300:
                self.entity_active = name
                return
        self.entity_active = ""

    def _snapshot_stats(self) -> dict:
        """Compact snapshot for history."""
        return {
            name: int(self.grid[y1:y2, x1:x2].sum())
            for name, (x1, y1, x2, y2) in ZONE_BOUNDS.items()
        }

    # --- Analysis ---

    def zone_stats(self) -> Dict[str, Dict[str, Any]]:
        """Compute statistics per zone."""
        with self._lock:
            grid_copy = self.grid.copy()
            history_copy = list(self.history)

        stats = {}
        for name, (x1, y1, x2, y2) in ZONE_BOUNDS.items():
            region = grid_copy[y1:y2, x1:x2]
            total = region.size
            alive = int(region.sum())

            oscillators = _count_pattern(region, PATTERNS["blinker"]) + _count_pattern(region, PATTERNS["toad"])
            still_lifes = _count_pattern(region, PATTERNS["block"]) + _count_pattern(region, PATTERNS["beehive"])
            gliders = _count_pattern(region, PATTERNS["glider"])

            stats[name] = {
                "density": round(alive / total, 3) if total > 0 else 0,
                "alive_cells": alive,
                "oscillators": oscillators,
                "still_lifes": still_lifes,
                "gliders": gliders,
                "trend": self._compute_trend(name, history_copy),
                "interactions": self._border_activity(name, grid_copy),
                "anomaly": self._detect_zone_anomaly(name, history_copy),
            }
        return stats

    def _compute_trend(self, zone_name: str, history: list) -> str:
        """Trend over recent generations."""
        if len(history) < 10:
            return "\u2192"  # →
        recent = [h.get(zone_name, 0) for h in history[-10:]]
        delta = recent[-1] - recent[0]
        if delta > 5:
            return "\u2191\u2191" if delta > 20 else "\u2191"  # ↑↑ or ↑
        elif delta < -5:
            return "\u2193\u2193" if delta < -20 else "\u2193"  # ↓↓ or ↓
        return "\u2192"  # →

    def _border_activity(self, zone_name: str, grid: np.ndarray) -> float:
        """Activity at zone borders (interaction with neighbors)."""
        x1, y1, x2, y2 = ZONE_BOUNDS[zone_name]
        border_cells = 0
        total_border = 0
        # Top edge
        if y1 > 0:
            border_cells += int(grid[y1, x1:x2].sum()) + int(grid[y1-1, x1:x2].sum())
            total_border += (x2 - x1) * 2
        # Bottom edge
        if y2 < self.size:
            border_cells += int(grid[y2-1, x1:x2].sum())
            if y2 < self.size:
                border_cells += int(grid[min(y2, self.size-1), x1:x2].sum())
            total_border += (x2 - x1) * 2
        # Left edge
        if x1 > 0:
            border_cells += int(grid[y1:y2, x1].sum()) + int(grid[y1:y2, x1-1].sum())
            total_border += (y2 - y1) * 2
        # Right edge
        if x2 < self.size:
            border_cells += int(grid[y1:y2, x2-1].sum())
            if x2 < self.size:
                border_cells += int(grid[y1:y2, min(x2, self.size-1)].sum())
            total_border += (y2 - y1) * 2
        return round(border_cells / max(total_border, 1), 2)

    def _detect_zone_anomaly(self, zone_name: str, history: list) -> bool:
        """Detect unusual activity patterns."""
        if len(history) < 20:
            return False
        recent = [h.get(zone_name, 0) for h in history[-20:]]
        avg_first = sum(recent[:10]) / 10
        avg_second = sum(recent[10:]) / 10
        return abs(avg_second - avg_first) > avg_first * 0.4 if avg_first > 0 else False

    def compute_entropy(self) -> float:
        """Shannon entropy of the grid."""
        with self._lock:
            p = self.grid.sum() / self.grid.size
        if p == 0 or p == 1:
            return 0.0
        return round(-p * np.log2(p) - (1 - p) * np.log2(1 - p), 3)

    def quantum_entropy(self) -> float:
        """Quantum type entropy — how mixed are the type distributions?
        High = cells are in superposition (many types). Low = cells are pure."""
        with self._lock:
            alive = self.grid == 1
            if not alive.any():
                return 0.0
            dists = self.type_dist[alive]
        # Per-cell Shannon entropy of type distribution, then average
        dists = np.clip(dists, 1e-10, 1.0)
        cell_entropy = -np.sum(dists * np.log2(dists), axis=1)
        return float(np.mean(cell_entropy))

    def quantum_coherence_score(self) -> float:
        """How coherent are cells? 1.0 = all pure types, 0.0 = max superposition."""
        qe = self.quantum_entropy()
        max_entropy = np.log2(NUM_TYPES)  # ~3.0 for 8 types
        return max(0.0, 1.0 - qe / max_entropy)

    def detect_anomalies(self) -> List[str]:
        """Global anomaly detection."""
        anomalies = []
        for name, stats in self.zone_stats().items():
            if stats["anomaly"]:
                trend = stats["trend"]
                anomalies.append(f"{name} zone {trend} anomaly (density={stats['density']})")
        return anomalies

    def _compute_interactions(self, zones: dict) -> List[str]:
        """Interaction strings for output."""
        pairs = [
            ("epq", "mood"), ("thoughts", "quantum"), ("mood", "ego"),
            ("ego", "memory"), ("thoughts", "entities"), ("hw", "quantum"),
        ]
        results = []
        for a, b in pairs:
            strength = max(zones.get(a, {}).get("interactions", 0),
                          zones.get(b, {}).get("interactions", 0))
            if strength > 0.1:
                level = "HIGH" if strength > 0.5 else "low"
                results.append(f"{a}\u2194{b} {level} ({strength:.2f})")
        return results

    def _dynamic_label(self, zone_name: str, stats: dict) -> str:
        """Generate dynamic status label based on zone activity."""
        density = stats["density"]
        trend = stats["trend"]
        gliders = stats["gliders"]
        oscillators = stats["oscillators"]

        if density < 0.01:
            return "dormant"
        if density > 0.3:
            return "OVERACTIVE"
        if gliders > 5:
            return "flowing"
        if oscillators > 8:
            return "processing"
        if "\u2191\u2191" in trend:
            return "EXPANDING"
        if "\u2193\u2193" in trend:
            return "declining"
        if stats["still_lifes"] > oscillators + gliders:
            return "ANCHORED"
        return ZONE_LABELS.get(zone_name, "nominal")

    # --- Introspect output ---

    def introspect(self, depth: str = "full") -> str:
        """LLM-readable compact report."""
        zones = self.zone_stats()
        entropy = self.compute_entropy()
        uptime_s = time.time() - self.start_time
        uptime_str = f"{int(uptime_s // 3600)}h{int((uptime_s % 3600) // 60)}m"

        if depth == "quick":
            active = [n for n, s in zones.items() if s["density"] > 0.05]
            return (
                f"Gen {self.generation} | mood={self.mood:.2f} "
                f"cohr={self.coherence:.2f} | active: {','.join(active)} | "
                f"{self.hw_temp}\u00b0C"
            )

        q_ent = self.quantum_entropy()
        q_coh = self.quantum_coherence_score()

        lines = [
            f"\u2550\u2550\u2550 AURA QUANTUM INTROSPECT ({depth}) \u2550\u2550\u2550",
            f"Gen {self.generation} | {self.hw_temp}\u00b0C | Uptime {uptime_str}",
            "",
            f"STATE: mood={self.mood:.2f} coherence={self.coherence:.2f} entropy={entropy:.2f}",
            f"QUANTUM: type_entropy={q_ent:.2f} type_coherence={q_coh:.2f}",
            "",
            "ZONES:",
        ]

        for name, stats in zones.items():
            alert = " \u26a1" if stats["anomaly"] else ""
            label = self._dynamic_label(name, stats)
            lines.append(
                f"  \u25a0 {name:12s} {stats['density']:.2f} {stats['trend']:3s} | "
                f"{stats['oscillators']:2d} osc {stats['still_lifes']:2d} still "
                f"{stats['gliders']:2d} glide | {label}{alert}"
            )

        interactions = self._compute_interactions(zones)
        if interactions:
            lines.append("")
            lines.append("INTERACTIONS: " + " | ".join(interactions))

        anomalies = self.detect_anomalies()
        if anomalies:
            lines.append("")
            for a in anomalies:
                lines.append(f"\u26a0 {a}")

        if depth == "diagnostic":
            lines.append("")
            lines.append("DIAGNOSTIC:")
            lines.append(f"  RAM: {self.ram_usage*100:.0f}%")
            lines.append(f"  CPU temp: {self.hw_temp}\u00b0C")
            lines.append(f"  E-PQ vectors: {json.dumps({k: round(v, 2) for k, v in self.epq_vectors.items()})}")
            lines.append(f"  Energy: {self.energy_level:.2f}")
            lines.append(f"  Active entity: {self.entity_active or 'none'}")
            lines.append(f"  Thoughts (1h): {self.thought_count}")
            # History trend (last 50 gens total alive)
            if len(self.history) >= 10:
                hist = list(self.history)
                total_trend = [sum(h.values()) for h in hist[-50:]]
                lines.append(f"  Alive cells (recent 50 gens): min={min(total_trend)} max={max(total_trend)} avg={sum(total_trend)//len(total_trend)}")

        lines.append("\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550")
        return "\n".join(lines)

    def introspect_json(self, depth: str = "full") -> dict:
        """JSON output for structured consumption."""
        zones = self.zone_stats()
        result = {
            "generation": self.generation,
            "quantum": True,
            "global": {
                "total_alive": int(self.grid.sum()),
                "entropy": self.compute_entropy(),
                "quantum_entropy": round(self.quantum_entropy(), 3),
                "quantum_coherence": round(self.quantum_coherence_score(), 3),
                "coherence": self.coherence,
                "mood": self.mood,
                "temperature": self.hw_temp,
            },
            "zones": zones,
            "anomalies": self.detect_anomalies(),
        }
        if depth == "diagnostic":
            result["diagnostic"] = {
                "ram_usage": self.ram_usage,
                "epq_vectors": self.epq_vectors,
                "energy_level": self.energy_level,
                "entity_active": self.entity_active,
                "thought_count": self.thought_count,
            }
            if len(self.history) >= 10:
                result["history"] = [
                    {"gen": self.generation - len(self.history) + i, **h}
                    for i, h in enumerate(self.history)
                ]
        return result


# --- Gaming mode check ---

def _is_gaming_active() -> bool:
    try:
        state_file = Path("/tmp/frank/gaming_mode_state.json")
        if state_file.exists():
            data = json.loads(state_file.read_text())
            return data.get("active", False)
    except Exception:
        pass
    return False


# --- GoL tick loop (background thread) ---

aura = AuraHeadless()

def _tick_loop():
    """Run GoL simulation at TICK_HZ."""
    interval = 1.0 / TICK_HZ
    LOG.info(f"GoL tick loop started ({TICK_HZ} Hz, {GRID_SIZE}x{GRID_SIZE})")
    while True:
        try:
            if not _is_gaming_active():
                aura.tick()
        except Exception as e:
            LOG.error(f"Tick error: {e}")
        time.sleep(interval)


# --- FastAPI app ---

app = FastAPI()


_tick_thread_started = False

def _ensure_tick_thread():
    """Start tick loop thread on first request (works with --lifespan off)."""
    global _tick_thread_started
    if _tick_thread_started:
        return
    _tick_thread_started = True
    t = threading.Thread(target=_tick_loop, daemon=True)
    t.start()
    LOG.info(f"[AURA] Headless Introspect active")
    LOG.info(f"[AURA] Grid: {GRID_SIZE}x{GRID_SIZE}, Tick: {TICK_HZ} Hz, Seed: every {SEED_INTERVAL_S}s")


@app.get("/health")
def health():
    _ensure_tick_thread()
    return {
        "ok": True,
        "service": "aura-headless",
        "generation": aura.generation,
        "uptime_s": int(time.time() - aura.start_time),
    }


@app.get("/introspect")
def introspect_endpoint(depth: str = "full"):
    """LLM-readable text output (GET)."""
    _ensure_tick_thread()
    text = aura.introspect(depth)
    return PlainTextResponse(text)


@app.post("/introspect")
def introspect_endpoint_post(body: dict = {}):
    """LLM-readable text output (POST — for agentic tool executor)."""
    depth = body.get("depth", "full")
    text = aura.introspect(depth)
    return {"ok": True, "text": text, "generation": aura.generation}


@app.get("/introspect/json")
def introspect_json_endpoint(depth: str = "full"):
    """Structured JSON output."""
    return JSONResponse(aura.introspect_json(depth))


@app.get("/grid")
def grid_endpoint():
    """Raw grid + quantum state export.

    Returns base64-encoded 256x256 arrays:
    - grid_b64: binary cell states (0/1), uint8
    - zone_map_b64: static zone IDs (0-7), uint8
    - quantum_colors_b64: per-cell blended RGB (256×256×3), uint8 (0-255)
    - dominant_type_b64: per-cell dominant type index, uint8
    - Full subsystem context
    """
    import base64
    _ensure_tick_thread()
    with aura._lock:
        grid_bytes = aura.grid.tobytes()
        zone_bytes = aura.zone_map.tobytes()
        gen = aura.generation
        # Quantum: blended colors quantized to uint8
        qcolors_u8 = np.clip(aura.quantum_colors * 255, 0, 255).astype(np.uint8)
        qcolors_bytes = qcolors_u8.tobytes()
        # Dominant type per cell
        dominant = aura.type_dist.argmax(axis=2).astype(np.uint8)
        dominant_bytes = dominant.tobytes()
    return {
        "generation": gen,
        "size": aura.size,
        "quantum": True,
        "grid_b64": base64.b64encode(grid_bytes).decode("ascii"),
        "zone_map_b64": base64.b64encode(zone_bytes).decode("ascii"),
        "quantum_colors_b64": base64.b64encode(qcolors_bytes).decode("ascii"),
        "dominant_type_b64": base64.b64encode(dominant_bytes).decode("ascii"),
        "zone_names": {0: "epq", 1: "mood", 2: "thoughts", 3: "entities",
                       4: "ego", 5: "quantum", 6: "memory", 7: "hw"},
        # Subsystem context
        "mood": aura.mood,
        "coherence": aura.coherence,
        "hw_temp": aura.hw_temp,
        "ram_usage": aura.ram_usage,
        "epq_vectors": aura.epq_vectors,
        "energy_level": aura.energy_level,
        "thought_count": aura.thought_count,
        "entity_active": aura.entity_active,
    }
