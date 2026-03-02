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

import base64
import json
import logging
import os
import sqlite3
import sys
import threading
import time
import urllib.request
import urllib.error
import zlib
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy.ndimage import convolve, gaussian_filter, zoom
from scipy.signal import correlate2d

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse, Response

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
SEED_INTERVAL_S = 10.0  # Re-seed from services every N seconds

# --- Stochastic Fine Graining ---
FINE_SIZE = 2560           # Stochastic fine grid (256 × 10)
SCALE = 10                 # Expansion factor per axis
EXPAND_SIGMA = 2.5         # Gaussian blur sigma for organic halos (at 256×256)
NOISE_BLEND_RATE = 0.08    # Temporal noise coherence (low=smooth morph, high=flicker)
NOISE_AMPLITUDE = 0.12     # ±12% probability variation for organic texture
NOISE_OCTAVES = 3          # Multi-frequency organic texture layers
FINE_INTERVAL = 21         # Recompute fine grid every N ticks (~2s at 10Hz), odd to align with stochastic

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
    """Count GoL pattern occurrences via 2D correlation (C-only, no GIL contention)."""
    ph, pw = pattern.shape
    rh, rw = region.shape
    if rh < ph or rw < pw:
        return 0
    # correlate2d runs entirely in C — releases GIL for full computation
    r = region.astype(np.float32)
    p = pattern.astype(np.float32)
    # Positive match: alive cells match pattern
    pos = correlate2d(r, p, mode='valid')
    # Negative match: dead cells in pattern region must be 0
    anti_p = 1.0 - p
    neg = correlate2d(r, anti_p, mode='valid')
    matches = (pos == pattern.sum()) & (neg == 0.0)
    return int(matches.sum())


# --- Data fetching (from real services) ---

def _read_db_value(db_name: str, query: str, default=None):
    """Safely read a single value from a SQLite database."""
    conn = None
    try:
        db_path = get_db(db_name)
        if not db_path.exists():
            return default
        conn = sqlite3.connect(str(db_path), timeout=2.0)
        conn.row_factory = sqlite3.Row
        row = conn.execute(query).fetchone()
        if row:
            return row[0] if len(row) == 1 else dict(row)
        return default
    except Exception:
        return default
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _read_db_rows(db_name: str, query: str, params=()) -> list:
    """Safely read multiple rows from a SQLite database."""
    conn = None
    try:
        db_path = get_db(db_name)
        if not db_path.exists():
            return []
        conn = sqlite3.connect(str(db_path), timeout=2.0)
        rows = conn.execute(query, params).fetchall()
        return rows
    except Exception:
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


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


_prev_cpu_idle = 0
_prev_cpu_total = 0


def _get_cpu_percent() -> float:
    """Read CPU usage percentage from /proc/stat (delta between calls)."""
    global _prev_cpu_idle, _prev_cpu_total
    try:
        with open("/proc/stat") as f:
            line = f.readline()  # First line: cpu  user nice system idle ...
        parts = line.split()
        if parts[0] != "cpu":
            return 0.0
        vals = [int(x) for x in parts[1:]]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
        total = sum(vals)
        d_idle = idle - _prev_cpu_idle
        d_total = total - _prev_cpu_total
        _prev_cpu_idle = idle
        _prev_cpu_total = total
        if d_total <= 0:
            return 0.0
        return (1.0 - d_idle / d_total) * 100.0
    except Exception:
        return 0.0


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


def _get_gpu_temp() -> int:
    """Read GPU temperature from amdgpu hwmon."""
    try:
        for hwmon in Path("/sys/class/hwmon").iterdir():
            name_file = hwmon / "name"
            if name_file.exists() and "amdgpu" in name_file.read_text():
                temp_file = hwmon / "temp1_input"
                if temp_file.exists():
                    return int(temp_file.read_text().strip()) // 1000
    except Exception:
        pass
    return 0


def _get_gpu_busy() -> int:
    """Read GPU busy percent from DRM sysfs."""
    try:
        for card in Path("/sys/class/drm").glob("card*/device/gpu_busy_percent"):
            return int(card.read_text().strip())
    except Exception:
        pass
    return 0


def _get_nvme_temp() -> int:
    """Read NVMe composite temperature from hwmon."""
    try:
        for hwmon in Path("/sys/class/hwmon").iterdir():
            name_file = hwmon / "name"
            if name_file.exists() and "nvme" in name_file.read_text():
                temp_file = hwmon / "temp1_input"
                if temp_file.exists():
                    return int(temp_file.read_text().strip()) // 1000
    except Exception:
        pass
    return 0


def _get_swap_percent() -> float:
    """Get swap usage as percent 0..100."""
    try:
        with open("/proc/meminfo") as f:
            info = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    info[parts[0].rstrip(":")] = int(parts[1])
        total = info.get("SwapTotal", 0)
        free = info.get("SwapFree", 0)
        if total > 0:
            return ((total - free) / total) * 100
    except Exception:
        pass
    return 0.0


def _get_disk_percent() -> float:
    """Get root filesystem usage percent."""
    try:
        import shutil
        du = shutil.disk_usage("/")
        return (du.used / du.total) * 100 if du.total > 0 else 0.0
    except Exception:
        return 0.0


def _get_uptime() -> float:
    """Get system uptime in seconds."""
    try:
        return float(Path("/proc/uptime").read_text().strip().split()[0])
    except Exception:
        return 0.0


# --- Quantum dynamics constants ---
DIFFUSION_RATE = 0.03       # How fast type distributions blend with neighbors
DECOHERENCE_RATE = 0.001    # How fast dominant types sharpen (reduced to prevent monochrome)
ZONE_ANCHOR_RATE = 0.008    # Gentle pull toward home zone (only for cells IN their home zone)
ZONE_ANCHOR_INTERVAL = 5    # Re-anchor every N ticks (2x/second at 10Hz)
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
        self.cpu_percent = 0.0
        self.ram_usage = 0.0
        self.gpu_temp = 0
        self.gpu_busy = 0
        self.nvme_temp = 0
        self.swap_percent = 0.0
        self.disk_percent = 0.0
        self.uptime_s = 0.0
        self.epq_vectors: Dict[str, float] = {}
        self.energy_level = 0.5
        self.thought_count = 0
        self.entity_active = ""
        self.entity_info: Dict[str, Dict] = {}  # Rich entity data for overlay

        self._lock = threading.Lock()
        self._last_seed_time = 0.0
        self._seed_pending = False
        self._grid_cache: dict = {}  # Pre-encoded /grid response (atomic swap)
        self._grid_json_bytes: bytes = b'{}'  # Pre-serialized JSON (no GIL in HTTP handler)
        self._grid_fine_json_bytes: bytes = b'{}'  # With fine grid included
        self._fine_grid_zb64: str = ""  # Pre-compressed fine grid (updated every FINE_INTERVAL)

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

        # ── Stochastic fine grid ──
        self._fine_grid = np.zeros((FINE_SIZE, FINE_SIZE), dtype=np.uint8)
        self._density_map = np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.float32)
        self._noise_field_256 = np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.float32)
        self._prob_field = np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.float32)
        self._rng = np.random.default_rng(42)

    def tick(self):
        """One quantum GoL step: Conway + type diffusion + decoherence."""
        _t0 = time.monotonic()
        with self._lock:
            old_grid = self.grid.copy()
            self.grid = self._conway_step(self.grid)
            _t1 = time.monotonic()

            # Diffuse every 2nd tick (5 Hz) — saves ~45ms, visually identical
            if self.generation % 2 == 0:
                self._diffuse_types(old_grid)
            _t2 = time.monotonic()

            self._decohere()
            # Zone anchoring: prevent monochrome convergence
            if self.generation % ZONE_ANCHOR_INTERVAL == 0:
                self._zone_anchor()
            self._update_quantum_colors()
            # Stochastic expand every 2nd tick (5 Hz) — density map changes slowly
            if self.generation % 2 == 1:
                self._stochastic_expand()
            _t3 = time.monotonic()

            self.generation += 1

            if self._seed_pending:
                self._apply_seeds()
                self._seed_pending = False

            self.history.append(self._snapshot_stats())

            # Fast array snapshots for /grid cache (memcpy only)
            _grid_copy = self.grid.copy()
            _grid_bytes = _grid_copy.tobytes()
            _zone_bytes = self.zone_map.tobytes()
            _qcolors_copy = self.quantum_colors.copy()
            _density_copy = self._density_map.copy()
            _type_dist_copy = self.type_dist.copy()
            _prob_copy = self._prob_field.copy() if self._prob_field is not None else None
            _gen = self.generation
            _do_fine = (_gen % FINE_INTERVAL == 1) and _prob_copy is not None
            _t4 = time.monotonic()

        # Build /grid cache OUTSIDE lock (fast, ~3ms)
        self._build_grid_cache(
            _grid_bytes, _zone_bytes, _qcolors_copy,
            _density_copy, _type_dist_copy, _gen, _grid_copy,
        )

        # Fine grid in background thread (~160ms, doesn't block tick loop at all)
        if _do_fine:
            threading.Thread(
                target=self._compute_fine_grid_async,
                args=(_prob_copy,),
                daemon=True,
                name="aura-fine-grid",
            ).start()

        _t5 = time.monotonic()

        total = (_t5 - _t0) * 1000
        if total > 40 or self.generation % 500 == 0:
            LOG.info(
                f"Tick {self.generation}: total={total:.0f}ms "
                f"conway={(_t1-_t0)*1000:.0f} diffuse={(_t2-_t1)*1000:.0f} "
                f"rest={(_t3-_t2)*1000:.0f} copy={(_t4-_t3)*1000:.0f} "
                f"cache={(_t5-_t4)*1000:.0f}"
            )

    def start_seed_thread(self):
        """Start background thread for periodic service data fetching."""
        def _seed_loop():
            while True:
                try:
                    self._seed_from_services()
                    self._seed_pending = True
                except Exception as e:
                    LOG.debug("Seed error: %s", e)
                time.sleep(SEED_INTERVAL_S)
        t = threading.Thread(target=_seed_loop, daemon=True, name="aura-seed")
        t.start()

    def _apply_seeds(self):
        """Apply cached service data as cell seeds (called under lock, no I/O)."""
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
        hw_stress = (self.hw_temp / 100.0) * 0.2 + (self.gpu_temp / 100.0) * 0.2 + self.ram_usage * 0.2 + (self.gpu_busy / 100.0) * 0.2
        self._seed_zone("hw", min(hw_stress, 0.8))

    def _conway_step(self, grid: np.ndarray) -> np.ndarray:
        """Standard Conway's Game of Life (B3/S23). Pure numpy chain — no Python loops."""
        p = np.pad(grid, 1, mode='wrap')  # (258, 258)
        s = self.size
        # 8 neighbor sum in a single expression — releases GIL for entire computation
        n = (p[0:s, 0:s] + p[0:s, 1:s+1] + p[0:s, 2:s+2] +
             p[1:s+1, 0:s]               + p[1:s+1, 2:s+2] +
             p[2:s+2, 0:s] + p[2:s+2, 1:s+1] + p[2:s+2, 2:s+2])
        return ((n == 3) | ((grid == 1) & (n == 2))).astype(np.uint8)

    _NEIGHBOR_KERNEL = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], dtype=np.float32)
    _NEIGHBOR_KERNEL_3D = _NEIGHBOR_KERNEL[:, :, np.newaxis]  # (3,3,1) for 3D convolve

    def _diffuse_types(self, old_grid: np.ndarray):
        """Quantum type propagation: alive cells blend type_dist with neighbors."""
        births = (self.grid == 1) & (old_grid == 0)
        deaths = (self.grid == 0) & (old_grid == 1)
        surviving = (self.grid == 1) & (old_grid == 1)

        # Single 3D convolution: (256,256,8) × (3,3,1) → spatial sum per type (one C call)
        alive_f = old_grid.astype(np.float32)
        weighted = self.type_dist * alive_f[:, :, np.newaxis]
        neighbor_types = convolve(weighted, self._NEIGHBOR_KERNEL_3D, mode='wrap')
        neighbor_count = convolve(alive_f, self._NEIGHBOR_KERNEL, mode='wrap')

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

        # Newborn cells: mostly inherit neighbor type (emergent color migration)
        # Only 10% zone tint so patterns can cross zone boundaries with their color
        if births.any():
            zone_ids = self.zone_map[births]
            zone_onehot = np.zeros((int(births.sum()), NUM_TYPES), dtype=np.float32)
            zone_onehot[np.arange(len(zone_ids)), zone_ids] = 1.0

            birth_has_neighbors = (neighbor_count[births] > 0)
            new_dist = np.where(
                birth_has_neighbors[:, np.newaxis],
                neighbor_avg[births] * 0.9 + zone_onehot * 0.1,
                zone_onehot,  # No neighbors → pure zone type
            )
            self.type_dist[births] = new_dist

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

    def _zone_anchor(self):
        """Gently pull cells toward home zone type — but ONLY cells still in their home zone.

        Cells that migrated into foreign zones keep their color freely,
        enabling emergent cross-zone color mixing and pattern migration.
        """
        alive = self.grid == 1
        if not alive.any():
            return
        zone_ids = self.zone_map[alive]
        dist = self.type_dist[alive]
        # Only anchor cells whose dominant type matches their home zone
        # (= they haven't been "recolored" by foreign neighbors)
        dominant = dist.argmax(axis=1)
        at_home = (dominant == zone_ids)
        if not at_home.any():
            return
        # Apply boost only to at-home cells
        boost = np.zeros_like(dist)
        home_indices = np.where(at_home)[0]
        boost[home_indices, zone_ids[at_home]] = ZONE_ANCHOR_RATE
        dist = dist + boost
        sums = dist.sum(axis=1, keepdims=True)
        sums[sums == 0] = 1.0
        self.type_dist[alive] = dist / sums

    def _update_quantum_colors(self):
        """Compute per-cell blended RGB from type_dist × zone colors."""
        # type_dist: (256,256,8), ZONE_COLORS_RGB: (8,3)
        # Result: (256,256,3) — weighted sum
        self.quantum_colors = np.einsum('ijk,kl->ijl', self.type_dist, ZONE_COLORS_RGB)

    def _stochastic_expand(self):
        """Compute organic density map at 256×256 (~5ms, no fine grid here)."""
        # 1. Probability field at 256×256: gaussian blur for organic transitions
        self._prob_field = gaussian_filter(
            self.grid.astype(np.float32), sigma=EXPAND_SIGMA,
        )

        # 2. Multi-octave noise at 256×256 (temporal coherent)
        noise = self._evolve_noise()
        np.clip(
            self._prob_field + noise * NOISE_AMPLITUDE, 0.0, 1.0,
            out=self._prob_field,
        )

        # 3. Density map = probability field (law of large numbers: E[Bernoulli(p)] = p)
        self._density_map = self._prob_field

    def _compute_fine_grid_async(self, prob_field: np.ndarray):
        """Generate 2560×2560 stochastic fine grid in background thread.

        Uses own RNG to avoid thread-safety issues with self._rng.
        numpy/zlib release GIL — tick thread runs unimpeded.
        """
        try:
            rng = np.random.default_rng()
            # Expand probability 256→2560 via repeat
            prob = np.repeat(prob_field, SCALE, axis=0)
            prob = np.repeat(prob, SCALE, axis=1)
            # Add fine-scale perturbation for organic texture within blocks
            prob += rng.standard_normal(prob.shape, dtype=np.float32) * 0.04
            np.clip(prob, 0.0, 1.0, out=prob)
            # Bernoulli sample
            fine = (rng.random((FINE_SIZE, FINE_SIZE)) < prob).astype(np.uint8)
            self._fine_grid = fine
            # Pre-compress for /grid?fine=1
            packed = np.packbits(fine)
            compressed = zlib.compress(packed.tobytes(), level=4)
            zb64 = base64.b64encode(compressed).decode("ascii")
            self._fine_grid_zb64 = zb64
            # Update pre-serialized fine JSON atomically
            if self._grid_cache:
                fine_cache = dict(self._grid_cache)
                fine_cache["fine_grid_zb64"] = zb64
                self._grid_fine_json_bytes = json.dumps(fine_cache).encode()
        except Exception as e:
            LOG.debug("Fine grid error: %s", e)

    def _evolve_noise(self) -> np.ndarray:
        """Multi-octave organic noise at 256×256 with temporal coherence.

        3 octaves at decreasing resolution create fractal, dendritric patterns.
        np.repeat for fast integer-factor upscale (10x faster than scipy.zoom).
        Temporal blend prevents flicker → smooth morphing.
        """
        target = np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.float32)
        for octave in range(NOISE_OCTAVES):
            base = max(4, GRID_SIZE >> (octave + 1))  # 128, 64, 32
            scale = GRID_SIZE // base                   # 2, 4, 8
            amp = 1.0 / (1 << octave)
            raw = self._rng.standard_normal((base, base)).astype(np.float32)
            # np.repeat: blocky upscale (pure C memcpy, ~0.1ms vs ~3ms for zoom)
            upscaled = np.repeat(np.repeat(raw, scale, axis=0), scale, axis=1)
            target += upscaled * amp
        # Temporal blend: smooth evolution
        self._noise_field_256 = (
            self._noise_field_256 * (1.0 - NOISE_BLEND_RATE)
            + target * NOISE_BLEND_RATE
        )
        return self._noise_field_256

    def _seed_from_services(self):
        """Fetch real subsystem data (I/O-heavy, runs in background thread)."""
        self._fetch_mood()
        self._fetch_epq()
        self._fetch_quantum()
        self._fetch_hardware()
        self._fetch_thoughts()
        self._fetch_entities()

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
            # Don't overwrite mood from DB [0,1] with E-PQ [-1,1] — keep DB value
            # self.mood is already set by _fetch_mood() in [0,1] range
            self.energy_level = 0.5 + (self.mood - 0.5) * 0.6  # Derive from [0,1] mood
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
        self.cpu_percent = _get_cpu_percent()
        self.ram_usage = _get_ram_usage()
        self.gpu_temp = _get_gpu_temp()
        self.gpu_busy = _get_gpu_busy()
        self.nvme_temp = _get_nvme_temp()
        self.swap_percent = _get_swap_percent()
        self.disk_percent = _get_disk_percent()
        self.uptime_s = _get_uptime()

    def _fetch_thoughts(self):
        """Count recent reflections from consciousness DB."""
        val = _read_db_value(
            "consciousness",
            "SELECT COUNT(*) FROM reflections WHERE timestamp > " + str(time.time() - 3600),
            0
        )
        self.thought_count = int(val) if val else 0

    _ENTITY_NAMES = {
        "therapist": "Dr. Hibbert",
        "mirror": "Kairos",
        "atlas": "Atlas",
        "muse": "Echo",
    }
    _ENTITY_QUOTAS = {
        "therapist": 3,
        "mirror": 1,
        "atlas": 1,
        "muse": 1,
    }

    def _fetch_entities(self):
        """Fetch rich entity data for overlay info panel."""
        import datetime
        now = time.time()
        today_start = datetime.datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()
        active = ""
        info: Dict[str, Dict] = {}

        for name in ("therapist", "mirror", "atlas", "muse"):
            # Sessions today (column is start_time, not timestamp)
            rows = _read_db_rows(
                name,
                "SELECT start_time, turns, primary_topic, outcome, end_time "
                "FROM sessions WHERE start_time > ? "
                "ORDER BY start_time DESC",
                (today_start,),
            )
            sessions_today = len(rows)
            last_ts = 0.0
            last_topic = ""
            last_turns = 0
            in_session = False
            if rows:
                last_ts = float(rows[0][0]) if rows[0][0] else 0.0
                last_turns = int(rows[0][1]) if rows[0][1] else 0
                last_topic = str(rows[0][2] or "")
                latest_end = rows[0][4]  # end_time
                # Session active if end_time is None or very recent
                if latest_end is None or (now - last_ts) < 300:
                    in_session = True
            if in_session and not active:
                active = name

            info[name] = {
                "display_name": self._ENTITY_NAMES[name],
                "in_session": in_session,
                "sessions_today": sessions_today,
                "quota": self._ENTITY_QUOTAS[name],
                "last_ts": last_ts,
                "last_topic": last_topic[:40],
                "last_turns": last_turns,
            }

        self.entity_active = active
        self.entity_info = info

    def _build_grid_cache(self, grid_bytes, zone_bytes, qcolors, density, type_dist, gen, grid_raw):
        """Build /grid response from array snapshots (runs OUTSIDE lock)."""
        qcolors_u8 = np.clip(qcolors * 255, 0, 255).astype(np.uint8)
        dominant = type_dist.argmax(axis=2).astype(np.uint8)
        density_u8 = np.clip(density * 255, 0, 255).astype(np.uint8)

        # Pre-compute quantum metrics (no lock needed, uses snapshot copies)
        alive = grid_raw == 1
        if alive.any():
            dists = np.clip(type_dist[alive], 1e-10, 1.0)
            cell_entropy = -np.sum(dists * np.log2(dists), axis=1)
            qe = float(np.mean(cell_entropy))
        else:
            qe = 0.0
        max_entropy = np.log2(NUM_TYPES)
        qc = max(0.0, 1.0 - qe / max_entropy)

        # Atomic dict assignment — /grid reads this without lock
        self._grid_cache = {
            "generation": gen,
            "size": self.size,
            "quantum": True,
            "grid_b64": base64.b64encode(grid_bytes).decode("ascii"),
            "zone_map_b64": base64.b64encode(zone_bytes).decode("ascii"),
            "quantum_colors_b64": base64.b64encode(qcolors_u8.tobytes()).decode("ascii"),
            "dominant_type_b64": base64.b64encode(dominant.tobytes()).decode("ascii"),
            "density_b64": base64.b64encode(density_u8.tobytes()).decode("ascii"),
            "fine_size": FINE_SIZE,
            "zone_names": {0: "epq", 1: "mood", 2: "thoughts", 3: "entities",
                           4: "ego", 5: "quantum", 6: "memory", 7: "hw"},
            "mood": self.mood,
            "coherence": self.coherence,
            "hw_temp": self.hw_temp,
            "cpu_percent": self.cpu_percent,
            "ram_usage": self.ram_usage,
            "gpu_temp": self.gpu_temp,
            "gpu_busy": self.gpu_busy,
            "nvme_temp": self.nvme_temp,
            "swap_percent": self.swap_percent,
            "disk_percent": self.disk_percent,
            "uptime_s": self.uptime_s,
            "epq_vectors": dict(self.epq_vectors),
            "energy_level": self.energy_level,
            "thought_count": self.thought_count,
            "entity_active": self.entity_active,
            "entity_info": self.entity_info,
            "quantum_entropy": round(qe, 4),
            "quantum_coherence": round(qc, 4),
        }

        # Pre-serialize JSON (eliminates GIL contention from HTTP JSON encoding)
        self._grid_json_bytes = json.dumps(self._grid_cache).encode()

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

    def detect_anomalies(self, zones: Dict | None = None) -> List[str]:
        """Global anomaly detection (reuses zones dict if provided)."""
        if zones is None:
            zones = self.zone_stats()
        anomalies = []
        for name, stats in zones.items():
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

        anomalies = self.detect_anomalies(zones)
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
                "quantum_entropy": self._grid_cache.get("quantum_entropy", 0.0),
                "quantum_coherence": self._grid_cache.get("quantum_coherence", 0.0),
                "coherence": self.coherence,
                "mood": self.mood,
                "temperature": self.hw_temp,
            },
            "zones": zones,
            "anomalies": self.detect_anomalies(zones),
        }
        if depth == "diagnostic":
            result["diagnostic"] = {
                "ram_usage": self.ram_usage,
                "epq_vectors": self.epq_vectors,
                "energy_level": self.energy_level,
                "entity_active": self.entity_active,
                "entity_info": self.entity_info,
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
        try:
            from config.paths import TEMP_FILES as _ah_temp_files
            state_file = _ah_temp_files["gaming_mode_state"]
        except ImportError:
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
    """Run GoL simulation at TICK_HZ with accurate timing."""
    import gc
    gc.disable()  # No GC pauses — numpy refcount handles cleanup, no cyclic refs
    interval = 1.0 / TICK_HZ
    LOG.info(f"GoL tick loop started ({TICK_HZ} Hz, {GRID_SIZE}x{GRID_SIZE})")
    while True:
        t0 = time.monotonic()
        try:
            if not _is_gaming_active():
                aura.tick()
        except Exception as e:
            LOG.error(f"Tick error: {e}")
        remaining = interval - (time.monotonic() - t0)
        if remaining > 0:
            time.sleep(remaining)


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
    aura.start_seed_thread()
    LOG.info(f"[AURA] Headless Introspect active")
    LOG.info(f"[AURA] Conway: {GRID_SIZE}x{GRID_SIZE}, Fine: {FINE_SIZE}x{FINE_SIZE}, Tick: {TICK_HZ} Hz")


@app.get("/health")
async def health():
    _ensure_tick_thread()
    grid = aura.grid
    alive = int(grid.sum()) if grid is not None else 0
    total = grid.size if grid is not None else 0
    return {
        "ok": True,
        "service": "aura-headless",
        "generation": aura.generation,
        "uptime_s": int(time.time() - aura.start_time),
        "alive_cells": alive,
        "total_cells": total,
    }


_introspect_text_cache = {"data": None, "time": 0.0}

@app.get("/introspect")
async def introspect_endpoint(depth: str = "full"):
    """LLM-readable text output (GET, cached 5s)."""
    _ensure_tick_thread()
    now = time.monotonic()
    cache = _introspect_text_cache
    if cache["data"] is not None and now - cache["time"] < 5.0:
        return PlainTextResponse(cache["data"])
    text = aura.introspect(depth)
    _introspect_text_cache["data"] = text
    _introspect_text_cache["time"] = now
    return PlainTextResponse(text)


@app.post("/introspect")
async def introspect_endpoint_post(body: dict = {}):
    """LLM-readable text output (POST — for agentic tool executor, cached 5s)."""
    depth = body.get("depth", "full")
    now = time.monotonic()
    cache = _introspect_text_cache
    if cache["data"] is not None and now - cache["time"] < 5.0:
        text = cache["data"]
    else:
        text = aura.introspect(depth)
        _introspect_text_cache["data"] = text
        _introspect_text_cache["time"] = now
    return {"ok": True, "text": text, "generation": aura.generation}


_introspect_json_cache = {"data": None, "time": 0.0}

@app.get("/introspect/json")
async def introspect_json_endpoint(depth: str = "full"):
    """Structured JSON output (cached 5s to avoid GIL contention)."""
    now = time.monotonic()
    cache = _introspect_json_cache
    if cache["data"] is not None and now - cache["time"] < 5.0:
        return JSONResponse(cache["data"])
    result = aura.introspect_json(depth)
    _introspect_json_cache["data"] = result
    _introspect_json_cache["time"] = now
    return JSONResponse(result)


@app.post("/inject")
async def inject_endpoint(body: dict):
    """Inject cells into the live simulation.

    Body: {"cells_b64": base64-encoded uint8 256x256 mask (1=inject)}
    Or:   {"positions": [[y,x], [y,x], ...]}
    """
    _ensure_tick_thread()
    count = 0
    with aura._lock:
        if "cells_b64" in body:
            mask_bytes = base64.b64decode(body["cells_b64"])
            mask = np.frombuffer(mask_bytes, dtype=np.uint8).reshape(
                aura.size, aura.size,
            )
            inject = mask > 0
            aura.grid[inject] = 1
            # Newborn cells inherit type from their zone
            ys, xs = np.where(inject)
            for y, x in zip(ys, xs):
                zid = int(aura.zone_map[y, x])
                aura.type_dist[y, x] = 0.0
                aura.type_dist[y, x, zid] = 1.0
            count = int(inject.sum())
        elif "positions" in body:
            for pos in body["positions"]:
                y, x = int(pos[0]), int(pos[1])
                if 0 <= y < aura.size and 0 <= x < aura.size:
                    aura.grid[y, x] = 1
                    zid = int(aura.zone_map[y, x])
                    aura.type_dist[y, x] = 0.0
                    aura.type_dist[y, x, zid] = 1.0
                    count += 1
    LOG.info(f"Injected {count} cells into live simulation")
    return {"ok": True, "injected": count}


@app.get("/grid")
async def grid_endpoint(fine: int = 0):
    """Raw grid export — returns pre-serialized JSON (zero CPU in HTTP handler)."""
    _ensure_tick_thread()
    if fine and aura._grid_fine_json_bytes:
        return Response(content=aura._grid_fine_json_bytes, media_type="application/json")
    return Response(content=aura._grid_json_bytes, media_type="application/json")
