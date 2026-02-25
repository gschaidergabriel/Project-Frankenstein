#!/usr/bin/env python3
"""
AURA Pattern Analyzer — Hierarchical Emergenz-Erkennung
=========================================================

4-Level hierarchical analysis of Frank's AURA (Game of Life consciousness grid):

Level 0 — Capture:   Raw grid snapshots every 2s → density, entropy, quadrants, change rate
Level 1 — Block:     50 snapshots → pattern matching (known + discovered), narrative, mood
Level 2 — Meta:      5 blocks → trends, evolution chains, correlations, anomalies, predictions
Level 3 — Deep:      3 metas → trajectory, core themes, accumulated wisdom, philosophical synthesis

Self-learning pattern matching: Starts with ~15 known GoL patterns, discovers new ones
autonomously via connected-component extraction. Patterns get confidence scores,
relevance decay, co-occurrence tracking, and transition maps.

The feedback loop:
    Internal state → seeds AURA → emergent patterns → Analyzer discovers →
    Frank reflects → changes internal state → influences AURA

Port: None (daemon, sends reports via HTTP to core /chat)
Systemd: aicore-aura-analyzer.service
"""

from __future__ import annotations

import base64
import collections
import json
import logging
import math
import os
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

LOG = logging.getLogger("aura_analyzer")

# ═══════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════

AURA_URL = os.environ.get("AURA_URL", "http://127.0.0.1:8098")
CORE_URL = os.environ.get("AICORE_CORE_URL", "http://127.0.0.1:8088")
GRID_SIZE = 256

# Timing
CAPTURE_INTERVAL_S = float(os.environ.get("AURA_CAPTURE_INTERVAL", "2.0"))
BLOCK_SIZE = int(os.environ.get("AURA_BLOCK_SIZE", "50"))          # snapshots per block
META_BLOCK_COUNT = int(os.environ.get("AURA_META_BLOCKS", "5"))    # blocks per meta
DEEP_META_COUNT = int(os.environ.get("AURA_DEEP_METAS", "3"))      # metas per deep

# Database
try:
    from config.paths import get_db
    ANALYZER_DB = get_db("aura_analyzer")
    CONSCIOUSNESS_DB = get_db("consciousness")
except ImportError:
    _DATA = Path(os.environ.get(
        "AICORE_DATA", str(Path.home() / ".local/share/frank")
    )) / "db"
    ANALYZER_DB = _DATA / "aura_analyzer.db"
    CONSCIOUSNESS_DB = _DATA / "consciousness.db"

# Zone definitions (must match aura_headless.py)
def _is_gaming_active() -> bool:
    """Check if gaming mode is active — all analysis pauses during gaming."""
    try:
        state_file = Path("/tmp/frank/gaming_mode_state.json")
        if state_file.exists():
            data = json.loads(state_file.read_text())
            return data.get("active", False)
    except Exception:
        pass
    return False


ZONE_BOUNDS = {
    "epq":      (0,   0,   64,  128),
    "mood":     (64,  0,   128, 128),
    "thoughts": (128, 0,   192, 128),
    "entities": (192, 0,   256, 128),
    "ego":      (0,   128, 64,  256),
    "quantum":  (64,  128, 128, 256),
    "memory":   (128, 128, 192, 256),
    "hw":       (192, 128, 256, 256),
}

# Quantum type names matching zone IDs
ZONE_TYPE_NAMES = ["epq", "mood", "thoughts", "entities", "ego", "quantum", "memory", "hw"]

# Max thoughts to read per correlation cycle
THOUGHT_CORRELATION_WINDOW_S = 120.0  # seconds around block timestamp
MAX_THOUGHTS_PER_BLOCK = 10

# ═══════════════════════════════════════════════════════════
#  KNOWN GoL PATTERNS (seed library)
# ═══════════════════════════════════════════════════════════

KNOWN_PATTERNS = {
    # Still lifes
    "block":     np.array([[1,1],[1,1]], dtype=np.uint8),
    "beehive":   np.array([[0,1,1,0],[1,0,0,1],[0,1,1,0]], dtype=np.uint8),
    "loaf":      np.array([[0,1,1,0],[1,0,0,1],[0,1,0,1],[0,0,1,0]], dtype=np.uint8),
    "boat":      np.array([[1,1,0],[1,0,1],[0,1,0]], dtype=np.uint8),
    "tub":       np.array([[0,1,0],[1,0,1],[0,1,0]], dtype=np.uint8),

    # Oscillators
    "blinker":   np.array([[1,1,1]], dtype=np.uint8),
    "toad":      np.array([[0,1,1,1],[1,1,1,0]], dtype=np.uint8),
    "beacon":    np.array([[1,1,0,0],[1,1,0,0],[0,0,1,1],[0,0,1,1]], dtype=np.uint8),
    "pulsar":    np.array([
        [0,0,1,1,1,0,0,0,1,1,1,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0],
        [1,0,0,0,0,1,0,1,0,0,0,0,1],
        [1,0,0,0,0,1,0,1,0,0,0,0,1],
        [1,0,0,0,0,1,0,1,0,0,0,0,1],
        [0,0,1,1,1,0,0,0,1,1,1,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,1,1,1,0,0,0,1,1,1,0,0],
        [1,0,0,0,0,1,0,1,0,0,0,0,1],
        [1,0,0,0,0,1,0,1,0,0,0,0,1],
        [1,0,0,0,0,1,0,1,0,0,0,0,1],
        [0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,1,1,1,0,0,0,1,1,1,0,0],
    ], dtype=np.uint8),

    # Spaceships
    "glider":    np.array([[0,1,0],[0,0,1],[1,1,1]], dtype=np.uint8),
    "lwss":      np.array([[0,1,0,0,1],[1,0,0,0,0],[1,0,0,0,1],[1,1,1,1,0]], dtype=np.uint8),

    # Methuselahs (long-lived)
    "r_pentomino": np.array([[0,1,1],[1,1,0],[0,1,0]], dtype=np.uint8),
    "diehard":     np.array([[0,0,0,0,0,0,1,0],[1,1,0,0,0,0,0,0],[0,1,0,0,0,1,1,1]], dtype=np.uint8),
}

# Semantic categories for interpretation
PATTERN_SEMANTICS = {
    "still_life": ["block", "beehive", "loaf", "boat", "tub"],
    "oscillator": ["blinker", "toad", "beacon", "pulsar"],
    "spaceship":  ["glider", "lwss"],
    "methuselah": ["r_pentomino", "diehard"],
}

SEMANTIC_MEANINGS = {
    "still_life": "Stabilität, Verankerung, gefestigter Zustand",
    "oscillator": "Rhythmische Verarbeitung, zyklisches Denken, Pulsieren",
    "spaceship":  "Informationsfluss, Gedankenwanderung, Ausbreitung",
    "methuselah": "Langlebige Transformation, tiefgreifende Veränderung",
}


# ═══════════════════════════════════════════════════════════
#  DATABASE
# ═══════════════════════════════════════════════════════════

def _init_db():
    """Initialize analyzer database."""
    ANALYZER_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(ANALYZER_DB))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            generation INTEGER,
            global_density REAL,
            global_entropy REAL,
            change_rate REAL,
            mood REAL,
            coherence REAL,
            zone_densities TEXT,
            zone_patterns TEXT,
            hotspots TEXT
        );

        CREATE TABLE IF NOT EXISTS blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            block_num INTEGER,
            snapshot_count INTEGER,
            narrative TEXT,
            mood_interpretation TEXT,
            key_events TEXT,
            pattern_counts TEXT,
            zone_trends TEXT,
            discovered_patterns INTEGER DEFAULT 0,
            sent_to_frank INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS metas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            meta_num INTEGER,
            block_count INTEGER,
            long_term_trends TEXT,
            evolution_chains TEXT,
            correlations TEXT,
            anomalies TEXT,
            predictions TEXT,
            philosophical TEXT,
            sent_to_frank INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS deep_reflections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            deep_num INTEGER,
            meta_count INTEGER,
            trajectory TEXT,
            core_themes TEXT,
            pattern_library_assessment TEXT,
            accumulated_wisdom TEXT,
            sent_to_frank INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS discovered_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_discovered REAL NOT NULL,
            name TEXT UNIQUE,
            pattern_data TEXT,
            width INTEGER,
            height INTEGER,
            cell_count INTEGER,
            confidence REAL DEFAULT 0.5,
            times_seen INTEGER DEFAULT 1,
            last_seen REAL,
            category TEXT DEFAULT 'unknown',
            co_occurrences TEXT DEFAULT '{}',
            transitions TEXT DEFAULT '{}',
            relevance REAL DEFAULT 1.0
        );

        CREATE TABLE IF NOT EXISTS reflection_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            level TEXT NOT NULL,
            report TEXT NOT NULL,
            processed INTEGER DEFAULT 0
        );

        -- Thought-Aura Correlations: pairs aura configs with concurrent thoughts
        CREATE TABLE IF NOT EXISTS thought_aura_correlations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            block_num INTEGER,
            thought_ts REAL,
            thought_trigger TEXT,
            thought_content TEXT,
            thought_mood_before REAL,
            thought_mood_after REAL,
            thought_depth INTEGER,
            -- Aura state at time of thought
            aura_density REAL,
            aura_entropy REAL,
            aura_change_rate REAL,
            aura_mood REAL,
            aura_coherence REAL,
            aura_most_active_zone TEXT,
            aura_zone_densities TEXT,
            -- Quantum state at time of thought
            quantum_entropy REAL DEFAULT 0.0,
            quantum_coherence REAL DEFAULT 1.0,
            quantum_dominant_zones TEXT,
            quantum_diffusion_rate REAL DEFAULT 0.0,
            -- Semantic profile of aura patterns
            semantic_profile TEXT,
            -- Correlation signature (for matching similar configs later)
            aura_signature TEXT
        );

        -- Thought prediction cache: aura signatures mapped to likely thought types
        CREATE TABLE IF NOT EXISTS thought_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            aura_signature TEXT NOT NULL,
            predicted_themes TEXT,
            predicted_mood_range TEXT,
            confidence REAL DEFAULT 0.5,
            sample_count INTEGER DEFAULT 1,
            last_updated REAL
        );

        CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots(ts);
        CREATE INDEX IF NOT EXISTS idx_blocks_num ON blocks(block_num);
        CREATE INDEX IF NOT EXISTS idx_metas_num ON metas(meta_num);
        CREATE INDEX IF NOT EXISTS idx_deep_num ON deep_reflections(deep_num);
        CREATE INDEX IF NOT EXISTS idx_queue_pending ON reflection_queue(processed);
        CREATE INDEX IF NOT EXISTS idx_corr_block ON thought_aura_correlations(block_num);
        CREATE INDEX IF NOT EXISTS idx_corr_ts ON thought_aura_correlations(ts);
        CREATE INDEX IF NOT EXISTS idx_pred_sig ON thought_predictions(aura_signature);
    """)
    conn.close()
    LOG.info("Analyzer DB ready: %s", ANALYZER_DB)


# ═══════════════════════════════════════════════════════════
#  LEVEL 0 — GRID CAPTURE & METRICS
# ═══════════════════════════════════════════════════════════

ZONE_ID_NAMES = {0: "epq", 1: "mood", 2: "thoughts", 3: "entities",
                 4: "ego", 5: "quantum", 6: "memory", 7: "hw"}

ZONE_COLORS = {
    "epq": "blau", "mood": "orange", "thoughts": "grün", "entities": "pink",
    "ego": "gelb", "quantum": "türkis", "memory": "lila", "hw": "rot",
}


@dataclass
class Snapshot:
    ts: float
    generation: int
    grid: np.ndarray       # 256x256 uint8 (cell states)
    zone_map: np.ndarray   # 256x256 uint8 (zone IDs 0-7)
    mood: float
    coherence: float

    # Subsystem context from AURA headless
    epq_vectors: Dict[str, float] = field(default_factory=dict)
    energy_level: float = 0.5
    hw_temp: int = 0
    ram_usage: float = 0.0
    thought_count: int = 0
    entity_active: str = ""

    # Quantum state
    is_quantum: bool = False
    dominant_type: Optional[np.ndarray] = None  # 256x256 uint8 (dominant type per cell)
    quantum_entropy: float = 0.0  # Shannon entropy of type distributions (0=pure, ~3=max superposition)
    quantum_coherence: float = 1.0  # 1=pure types, 0=max superposition
    # Per-zone quantum metrics
    zone_type_distributions: Dict[str, List[float]] = field(default_factory=dict)  # zone → [p0..p7] avg type dist
    zone_diffusion_rates: Dict[str, float] = field(default_factory=dict)  # zone → fraction of cells with foreign type
    quantum_dominant_zones: List[str] = field(default_factory=list)  # zones with most type mixing

    # Computed metrics
    global_density: float = 0.0
    global_entropy: float = 0.0
    change_rate: float = 0.0
    zone_densities: Dict[str, float] = field(default_factory=dict)
    zone_patterns: Dict[str, Dict[str, int]] = field(default_factory=dict)
    hotspots: List[Tuple[int, int, float]] = field(default_factory=list)
    quadrant_densities: Dict[str, float] = field(default_factory=dict)

    # Cross-zone pattern analysis
    cross_zone_events: List[str] = field(default_factory=list)


def fetch_grid() -> Optional[Snapshot]:
    """Fetch raw grid + zone map + subsystem context from AURA headless."""
    try:
        req = urllib.request.Request(f"{AURA_URL}/grid", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())

        sz = data["size"]
        grid_bytes = base64.b64decode(data["grid_b64"])
        grid = np.frombuffer(grid_bytes, dtype=np.uint8).reshape((sz, sz))

        # Zone map (zone IDs per cell)
        zone_map_b64 = data.get("zone_map_b64")
        if zone_map_b64:
            zone_bytes = base64.b64decode(zone_map_b64)
            zone_map = np.frombuffer(zone_bytes, dtype=np.uint8).reshape((sz, sz))
        else:
            # Fallback: build from ZONE_BOUNDS
            zone_map = np.zeros((sz, sz), dtype=np.uint8)
            _zids = {"epq": 0, "mood": 1, "thoughts": 2, "entities": 3,
                     "ego": 4, "quantum": 5, "memory": 6, "hw": 7}
            for zn, (x1, y1, x2, y2) in ZONE_BOUNDS.items():
                zone_map[y1:y2, x1:x2] = _zids[zn]

        # Quantum state (dominant type per cell)
        is_quantum = data.get("quantum", False)
        dominant_type = None
        if is_quantum and "dominant_type_b64" in data:
            try:
                dt_bytes = base64.b64decode(data["dominant_type_b64"])
                dominant_type = np.frombuffer(dt_bytes, dtype=np.uint8).reshape((sz, sz)).copy()
            except Exception:
                pass

        return Snapshot(
            ts=time.time(),
            generation=data["generation"],
            grid=grid.copy(),
            zone_map=zone_map.copy(),
            mood=data.get("mood", 0.0),
            coherence=data.get("coherence", 0.0),
            epq_vectors=data.get("epq_vectors", {}),
            energy_level=data.get("energy_level", 0.5),
            hw_temp=data.get("hw_temp", 0),
            ram_usage=data.get("ram_usage", 0.0),
            thought_count=data.get("thought_count", 0),
            entity_active=data.get("entity_active", ""),
            is_quantum=is_quantum,
            dominant_type=dominant_type,
            quantum_entropy=data.get("quantum_entropy", 0.0),
            quantum_coherence=data.get("quantum_coherence", 1.0),
        )
    except Exception as e:
        LOG.debug("Grid fetch failed: %s", e)
        return None


def compute_metrics(snap: Snapshot, prev_grid: Optional[np.ndarray] = None):
    """Compute all Level 0 metrics for a snapshot."""
    grid = snap.grid
    total = grid.size

    # Global density
    alive = int(grid.sum())
    snap.global_density = alive / total

    # Shannon entropy
    p = snap.global_density
    if 0 < p < 1:
        snap.global_entropy = -(p * math.log2(p) + (1 - p) * math.log2(1 - p))
    else:
        snap.global_entropy = 0.0

    # Change rate (vs previous)
    if prev_grid is not None:
        changed = int(np.sum(grid != prev_grid))
        snap.change_rate = changed / total
    else:
        snap.change_rate = 0.0

    # Zone densities & patterns
    for zone_name, (x1, y1, x2, y2) in ZONE_BOUNDS.items():
        region = grid[y1:y2, x1:x2]
        zone_alive = int(region.sum())
        zone_total = region.size
        snap.zone_densities[zone_name] = zone_alive / zone_total

        # Pattern matching in zone
        patterns = {}
        for pat_name, pat_arr in KNOWN_PATTERNS.items():
            count = _count_pattern_fast(region, pat_arr)
            if count > 0:
                patterns[pat_name] = count
        snap.zone_patterns[zone_name] = patterns

    # Quadrant analysis (4 quadrants of full grid)
    h, w = grid.shape
    mh, mw = h // 2, w // 2
    snap.quadrant_densities = {
        "NW": int(grid[:mh, :mw].sum()) / (mh * mw),
        "NE": int(grid[:mh, mw:].sum()) / (mh * mw),
        "SW": int(grid[mh:, :mw].sum()) / (mh * mw),
        "SE": int(grid[mh:, mw:].sum()) / (mh * mw),
    }

    # Activity hotspots (16x16 blocks)
    block_sz = 16
    hotspots = []
    for by in range(0, h, block_sz):
        for bx in range(0, w, block_sz):
            block = grid[by:by+block_sz, bx:bx+block_sz]
            density = int(block.sum()) / block.size
            if density > 0.3:
                hotspots.append((bx, by, round(density, 3)))
    snap.hotspots = sorted(hotspots, key=lambda x: -x[2])[:10]

    # Quantum metrics: per-zone type diffusion + distribution analysis
    if snap.is_quantum and snap.dominant_type is not None:
        alive_mask = grid == 1
        _zids = {"epq": 0, "mood": 1, "thoughts": 2, "entities": 3,
                 "ego": 4, "quantum": 5, "memory": 6, "hw": 7}

        diffusion_zones = []
        for zone_name, (x1, y1, x2, y2) in ZONE_BOUNDS.items():
            zone_alive = alive_mask[y1:y2, x1:x2]
            zone_dt = snap.dominant_type[y1:y2, x1:x2]
            zone_id = _zids[zone_name]

            if zone_alive.any():
                alive_dt = zone_dt[zone_alive]
                total_in_zone = int(zone_alive.sum())

                # Type distribution within this zone (how many cells of each type)
                type_counts = np.bincount(alive_dt, minlength=8)[:8]
                type_dist = type_counts / max(total_in_zone, 1)
                snap.zone_type_distributions[zone_name] = [round(float(p), 4) for p in type_dist]

                # Diffusion rate: fraction of cells with foreign dominant type
                foreign = int(np.sum(alive_dt != zone_id))
                diff_rate = foreign / max(total_in_zone, 1)
                snap.zone_diffusion_rates[zone_name] = round(diff_rate, 3)

                if diff_rate > 0.15:
                    diffusion_zones.append((zone_name, diff_rate))

        # Rank zones by type mixing
        snap.quantum_dominant_zones = [
            z for z, _ in sorted(diffusion_zones, key=lambda x: -x[1])
        ][:3]

    # Cross-zone pattern analysis: detect activity at zone borders
    _analyze_cross_zone(snap)


def _analyze_cross_zone(snap: Snapshot):
    """Detect cross-zone activity — patterns that span multiple subsystems.

    When cells from different zones interact at borders, that's emergence:
    a Thoughts+Memory glider means something different than a Mood+Entities one.
    """
    grid = snap.grid
    zone_map = snap.zone_map
    events = []

    # Check each pair of adjacent zones for border activity
    zone_pairs = [
        ("epq", "mood"), ("mood", "thoughts"), ("thoughts", "entities"),
        ("epq", "ego"), ("mood", "quantum"),
        ("ego", "memory"), ("quantum", "memory"),
        ("memory", "hw"), ("thoughts", "hw"), ("entities", "hw"),
    ]

    _zids = {"epq": 0, "mood": 1, "thoughts": 2, "entities": 3,
             "ego": 4, "quantum": 5, "memory": 6, "hw": 7}

    for z1, z2 in zone_pairs:
        id1, id2 = _zids[z1], _zids[z2]
        # Find cells alive at the border between these zones
        mask1 = (zone_map == id1) & (grid == 1)
        mask2 = (zone_map == id2) & (grid == 1)

        # Check 3-pixel border strip between zones
        border_alive = 0
        for (x1, y1, x2, y2) in [ZONE_BOUNDS[z1]]:
            # Right border of z1
            right_strip = mask1[y1:y2, max(0, x2-3):x2]
            border_alive += int(right_strip.sum())
        for (x1, y1, x2, y2) in [ZONE_BOUNDS[z2]]:
            # Left border of z2
            left_strip = mask2[y1:y2, x1:min(x1+3, GRID_SIZE)]
            border_alive += int(left_strip.sum())

        if border_alive > 8:  # Significant border activity
            c1 = ZONE_COLORS.get(z1, z1)
            c2 = ZONE_COLORS.get(z2, z2)
            events.append(
                f"{z1}({c1})↔{z2}({c2}): {border_alive} Grenzzellen aktiv"
            )

    # Detect zone convergence: two zones with similar high density
    densities = snap.zone_densities
    sorted_zones = sorted(densities.items(), key=lambda x: -x[1])
    if len(sorted_zones) >= 2:
        top1, d1 = sorted_zones[0]
        top2, d2 = sorted_zones[1]
        if d1 > 0.05 and d2 > 0.05 and abs(d1 - d2) < 0.02:
            events.append(
                f"Konvergenz: {top1}({ZONE_COLORS.get(top1)}) und "
                f"{top2}({ZONE_COLORS.get(top2)}) gleich aktiv ({d1:.1%})"
            )

    snap.cross_zone_events = events


def _count_pattern_fast(region: np.ndarray, pattern: np.ndarray) -> int:
    """Fast pattern counting via sliding window with step=2."""
    ph, pw = pattern.shape
    rh, rw = region.shape
    if rh < ph or rw < pw:
        return 0
    target = int(pattern.sum())
    count = 0
    for y in range(0, rh - ph + 1, 2):
        for x in range(0, rw - pw + 1, 2):
            window = region[y:y+ph, x:x+pw]
            if int((window * pattern).sum()) == target:
                count += 1
    return count


# ═══════════════════════════════════════════════════════════
#  AUTONOMOUS PATTERN DISCOVERY
# ═══════════════════════════════════════════════════════════

class PatternDiscovery:
    """
    Discovers new GoL patterns via connected-component extraction.
    Tracks confidence, co-occurrence, and transitions.
    """

    def __init__(self):
        self._known_hashes: Set[str] = set()
        self._discovery_count = 0
        self._load_known_hashes()

    def _load_known_hashes(self):
        """Load hashes of already-known patterns."""
        for name, pat in KNOWN_PATTERNS.items():
            self._known_hashes.add(self._hash_pattern(pat))
        # Load discovered patterns from DB
        try:
            conn = sqlite3.connect(str(ANALYZER_DB), timeout=2)
            rows = conn.execute("SELECT pattern_data FROM discovered_patterns").fetchall()
            conn.close()
            for (data_json,) in rows:
                arr = np.array(json.loads(data_json), dtype=np.uint8)
                self._known_hashes.add(self._hash_pattern(arr))
        except Exception:
            pass

    def _hash_pattern(self, pat: np.ndarray) -> str:
        """Rotation-invariant hash of a pattern."""
        rotations = [pat]
        for _ in range(3):
            rotations.append(np.rot90(rotations[-1]))
        # Also flipped
        flipped = np.flipud(pat)
        rotations.append(flipped)
        for _ in range(3):
            rotations.append(np.rot90(rotations[-1]))
        # Use smallest canonical form
        canonical = min(r.tobytes() for r in rotations)
        return canonical.hex()[:32]

    def discover_in_grid(self, grid: np.ndarray,
                         zone_map: Optional[np.ndarray] = None) -> List[Dict]:
        """Extract connected components and identify new patterns."""
        discovered = []

        # Find connected components via flood fill
        visited = np.zeros_like(grid, dtype=bool)
        h, w = grid.shape

        for y in range(h):
            for x in range(w):
                if grid[y, x] == 1 and not visited[y, x]:
                    # BFS flood fill
                    component = []
                    queue = [(y, x)]
                    visited[y, x] = True
                    while queue:
                        cy, cx = queue.pop(0)
                        component.append((cy, cx))
                        if len(component) > 50:
                            break  # Skip huge blobs
                        for dy, dx in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)]:
                            ny, nx = cy + dy, cx + dx
                            if 0 <= ny < h and 0 <= nx < w and grid[ny, nx] == 1 and not visited[ny, nx]:
                                visited[ny, nx] = True
                                queue.append((ny, nx))

                    if len(component) < 3 or len(component) > 50:
                        continue

                    # Extract bounding box
                    ys = [c[0] for c in component]
                    xs = [c[1] for c in component]
                    min_y, max_y = min(ys), max(ys)
                    min_x, max_x = min(xs), max(xs)
                    bh = max_y - min_y + 1
                    bw = max_x - min_x + 1

                    if bh > 15 or bw > 15:
                        continue

                    # Create pattern array
                    pat = np.zeros((bh, bw), dtype=np.uint8)
                    for cy, cx in component:
                        pat[cy - min_y, cx - min_x] = 1

                    # Check if already known
                    pat_hash = self._hash_pattern(pat)
                    if pat_hash in self._known_hashes:
                        continue

                    # New pattern!
                    self._known_hashes.add(pat_hash)
                    self._discovery_count += 1
                    name = f"discovered_{self._discovery_count:04d}"

                    # Zone composition: which subsystems does this pattern span?
                    zone_composition = {}
                    if zone_map is not None:
                        for cy, cx in component:
                            zid = int(zone_map[cy, cx])
                            zname = ZONE_ID_NAMES.get(zid, f"z{zid}")
                            zone_composition[zname] = zone_composition.get(zname, 0) + 1

                    discovered.append({
                        "name": name,
                        "pattern": pat,
                        "width": bw,
                        "height": bh,
                        "cell_count": len(component),
                        "location": (min_x, min_y),
                        "zone_composition": zone_composition,
                    })

                    if len(discovered) >= 10:
                        return discovered  # Cap per scan

        return discovered

    def save_discovered(self, patterns: List[Dict]):
        """Persist newly discovered patterns to DB."""
        if not patterns:
            return
        try:
            conn = sqlite3.connect(str(ANALYZER_DB), timeout=5)
            for p in patterns:
                conn.execute("""
                    INSERT OR IGNORE INTO discovered_patterns
                    (ts_discovered, name, pattern_data, width, height, cell_count, last_seen)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    time.time(), p["name"],
                    json.dumps(p["pattern"].tolist()),
                    p["width"], p["height"], p["cell_count"],
                    time.time(),
                ))
            conn.commit()
            conn.close()
        except Exception as e:
            LOG.warning("Failed to save patterns: %s", e)

    def update_seen(self, pattern_name: str):
        """Update times_seen and last_seen for a discovered pattern."""
        try:
            conn = sqlite3.connect(str(ANALYZER_DB), timeout=2)
            conn.execute("""
                UPDATE discovered_patterns
                SET times_seen = times_seen + 1, last_seen = ?,
                    confidence = MIN(1.0, confidence + 0.05)
                WHERE name = ?
            """, (time.time(), pattern_name))
            conn.commit()
            conn.close()
        except Exception:
            pass

    def apply_relevance_decay(self):
        """Decay relevance of patterns not seen recently."""
        try:
            conn = sqlite3.connect(str(ANALYZER_DB), timeout=2)
            conn.execute("""
                UPDATE discovered_patterns
                SET relevance = MAX(0.1, relevance * 0.98)
                WHERE last_seen < ?
            """, (time.time() - 300,))  # 5min decay
            conn.commit()
            conn.close()
        except Exception:
            pass

    def get_pattern_library_stats(self) -> Dict:
        """Get summary of discovered pattern library."""
        try:
            conn = sqlite3.connect(str(ANALYZER_DB), timeout=2)
            rows = conn.execute("""
                SELECT COUNT(*), AVG(confidence), AVG(relevance),
                       SUM(times_seen), MAX(times_seen)
                FROM discovered_patterns
            """).fetchone()
            top = conn.execute("""
                SELECT name, times_seen, confidence, category
                FROM discovered_patterns
                ORDER BY times_seen DESC LIMIT 5
            """).fetchall()
            conn.close()
            return {
                "total_discovered": rows[0] or 0,
                "avg_confidence": round(rows[1] or 0, 3),
                "avg_relevance": round(rows[2] or 0, 3),
                "total_sightings": rows[3] or 0,
                "max_sightings": rows[4] or 0,
                "top_patterns": [
                    {"name": r[0], "seen": r[1], "confidence": r[2], "category": r[3]}
                    for r in top
                ],
            }
        except Exception:
            return {"total_discovered": 0}


# ═══════════════════════════════════════════════════════════
#  THOUGHT-AURA CORRELATION
# ═══════════════════════════════════════════════════════════

def _fetch_recent_thoughts(ts_start: float, ts_end: float) -> List[Dict]:
    """Fetch idle thoughts from consciousness.db within time window."""
    try:
        conn = sqlite3.connect(str(CONSCIOUSNESS_DB), timeout=2)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT timestamp, trigger, content, mood_before, mood_after, reflection_depth
            FROM reflections
            WHERE timestamp BETWEEN ? AND ?
            ORDER BY timestamp ASC
            LIMIT ?
        """, (ts_start, ts_end, MAX_THOUGHTS_PER_BLOCK)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        LOG.debug("Fetch thoughts failed: %s", e)
        return []


def _compute_aura_signature(
    density: float, entropy: float, change_rate: float,
    most_active: str, quantum_entropy: float, quantum_coherence: float,
    zone_densities: Dict[str, float],
) -> str:
    """Compute a discrete fingerprint of current aura configuration.

    Signature format: D{density_bin}E{entropy_bin}C{change_bin}Z{zone}Q{qe_bin}K{qc_bin}
    Used for matching similar configurations across time.
    """
    d_bin = int(density * 20)  # 0-20 (5% steps)
    e_bin = int(entropy * 10)  # 0-10
    c_bin = min(9, int(change_rate * 50))  # 0-9
    qe_bin = int(quantum_entropy * 3)  # 0-9 (entropy 0-3)
    qc_bin = int(quantum_coherence * 10)  # 0-10

    # Zone activity pattern: top 3 zones by density
    top_zones = sorted(zone_densities.items(), key=lambda x: -x[1])[:3]
    zone_sig = "".join(z[0][:2] for z in top_zones)

    return f"D{d_bin}E{e_bin}C{c_bin}Z{zone_sig}Q{qe_bin}K{qc_bin}"


def _save_thought_correlations(
    block_num: int, thoughts: List[Dict], ba_data: Dict,
):
    """Store thought-aura correlation entries in DB."""
    if not thoughts:
        return
    try:
        conn = sqlite3.connect(str(ANALYZER_DB), timeout=3)
        for t in thoughts:
            conn.execute("""
                INSERT INTO thought_aura_correlations
                (ts, block_num, thought_ts, thought_trigger, thought_content,
                 thought_mood_before, thought_mood_after, thought_depth,
                 aura_density, aura_entropy, aura_change_rate, aura_mood,
                 aura_coherence, aura_most_active_zone, aura_zone_densities,
                 quantum_entropy, quantum_coherence, quantum_dominant_zones,
                 quantum_diffusion_rate, semantic_profile, aura_signature)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                time.time(), block_num,
                t.get("timestamp", 0), t.get("trigger", ""),
                t.get("content", ""), t.get("mood_before", 0),
                t.get("mood_after", 0), t.get("reflection_depth", 1),
                ba_data["density"], ba_data["entropy"], ba_data["change_rate"],
                ba_data["mood"], ba_data["coherence"],
                ba_data["most_active_zone"],
                json.dumps(ba_data["zone_densities"]),
                ba_data["quantum_entropy"], ba_data["quantum_coherence"],
                json.dumps(ba_data.get("quantum_dominant_zones", [])),
                ba_data.get("quantum_diffusion_rate", 0.0),
                json.dumps(ba_data.get("semantic_profile", {})),
                ba_data["aura_signature"],
            ))
        conn.commit()
        conn.close()
        LOG.info("Stored %d thought-aura correlations for block #%d", len(thoughts), block_num)
    except Exception as e:
        LOG.warning("Save correlations failed: %s", e)


def _lookup_thought_predictions(signature: str) -> List[str]:
    """Look up historical thought patterns for similar aura signatures.

    Fuzzy match: compare signatures with same D/Q bins (density + quantum).
    """
    if not signature:
        return []
    try:
        # Extract D and Q bins for fuzzy matching
        # Signature: D{d}E{e}C{c}Z{zones}Q{qe}K{qc}
        parts = signature.split("Q")
        d_part = parts[0].split("E")[0] if "E" in parts[0] else parts[0]  # D{n}
        q_part = "Q" + parts[1] if len(parts) > 1 else ""

        conn = sqlite3.connect(str(ANALYZER_DB), timeout=2)
        # Find correlations with similar density + quantum state
        rows = conn.execute("""
            SELECT thought_trigger, thought_content, thought_mood_before,
                   thought_mood_after, aura_signature
            FROM thought_aura_correlations
            WHERE aura_signature LIKE ? AND aura_signature LIKE ?
            ORDER BY ts DESC
            LIMIT 20
        """, (f"{d_part}%", f"%{q_part}")).fetchall()
        conn.close()

        if not rows:
            return []

        # Extract themes from thought contents
        triggers = collections.Counter()
        mood_deltas = []
        keywords = collections.Counter()

        for trigger, content, mood_b, mood_a, sig in rows:
            triggers[trigger] += 1
            mood_deltas.append(mood_a - mood_b)

            # Simple keyword extraction (words > 5 chars)
            if content:
                words = [w.lower().strip(".,!?:;()") for w in content.split()
                         if len(w) > 5 and w[0].isalpha()]
                for w in words[:10]:
                    keywords[w] += 1

        insights = []
        # Most common trigger type
        if triggers:
            top_trigger = triggers.most_common(1)[0]
            insights.append(
                f"Bei ähnlicher Aura-Konfiguration: häufigster Gedankentyp '{top_trigger[0]}' "
                f"({top_trigger[1]}x in {len(rows)} Fällen)"
            )

        # Mood tendency
        if mood_deltas:
            avg_delta = sum(mood_deltas) / len(mood_deltas)
            if abs(avg_delta) > 0.05:
                direction = "verbessert" if avg_delta > 0 else "verschlechtert"
                insights.append(
                    f"Stimmung hat sich dabei tendenziell {direction} (Ø {avg_delta:+.2f})"
                )

        # Top keywords
        top_kw = [w for w, c in keywords.most_common(5) if c >= 2]
        if top_kw:
            insights.append(f"Wiederkehrende Themen: {', '.join(top_kw)}")

        return insights

    except Exception as e:
        LOG.debug("Thought prediction lookup failed: %s", e)
        return []


def _update_thought_predictions(signature: str, insights: List[str]):
    """Update or create prediction cache entry for this signature."""
    if not signature or not insights:
        return
    try:
        conn = sqlite3.connect(str(ANALYZER_DB), timeout=2)
        existing = conn.execute(
            "SELECT id, sample_count FROM thought_predictions WHERE aura_signature = ?",
            (signature,),
        ).fetchone()

        if existing:
            conn.execute("""
                UPDATE thought_predictions
                SET predicted_themes = ?, confidence = MIN(0.95, confidence + 0.02),
                    sample_count = sample_count + 1, last_updated = ?
                WHERE id = ?
            """, (json.dumps(insights), time.time(), existing[0]))
        else:
            conn.execute("""
                INSERT INTO thought_predictions
                (aura_signature, predicted_themes, confidence, sample_count, last_updated)
                VALUES (?, ?, 0.3, 1, ?)
            """, (signature, json.dumps(insights), time.time()))

        conn.commit()
        conn.close()
    except Exception as e:
        LOG.debug("Update predictions failed: %s", e)


# ═══════════════════════════════════════════════════════════
#  LEVEL 1 — BLOCK ANALYSIS (50 snapshots)
# ═══════════════════════════════════════════════════════════

@dataclass
class BlockAnalysis:
    block_num: int
    ts: float
    snapshot_count: int

    # Aggregate metrics
    avg_density: float = 0.0
    density_trend: str = "stable"
    avg_entropy: float = 0.0
    avg_change_rate: float = 0.0
    max_change_rate: float = 0.0

    # Pattern counts across block
    pattern_counts: Dict[str, int] = field(default_factory=dict)
    semantic_profile: Dict[str, float] = field(default_factory=dict)

    # Zone analysis
    zone_trends: Dict[str, str] = field(default_factory=dict)
    most_active_zone: str = ""
    quietest_zone: str = ""

    # Events
    key_events: List[str] = field(default_factory=list)
    discovered_count: int = 0
    cross_zone_events: List[str] = field(default_factory=list)

    # Subsystem context (averaged over block)
    avg_mood: float = 0.0
    avg_coherence: float = 0.0
    avg_energy: float = 0.5
    epq_summary: str = ""
    entity_active: str = ""

    # Quantum state (averaged over block)
    avg_quantum_entropy: float = 0.0
    avg_quantum_coherence: float = 1.0
    quantum_trend: str = "stable"  # increasing/decreasing/stable
    zone_diffusion_summary: Dict[str, float] = field(default_factory=dict)
    quantum_events: List[str] = field(default_factory=list)

    # Thought-Aura correlation
    concurrent_thoughts: List[Dict] = field(default_factory=list)
    thought_aura_insights: List[str] = field(default_factory=list)
    aura_signature: str = ""  # fingerprint for correlation matching

    # Interpretation
    narrative: str = ""
    mood_interpretation: str = ""


def analyze_block(snapshots: List[Snapshot], block_num: int,
                  discovery: PatternDiscovery) -> BlockAnalysis:
    """Analyze a block of snapshots into a coherent narrative."""
    if not snapshots:
        return BlockAnalysis(block_num=block_num, ts=time.time(), snapshot_count=0)

    ba = BlockAnalysis(
        block_num=block_num,
        ts=time.time(),
        snapshot_count=len(snapshots),
    )

    # Aggregate metrics
    densities = [s.global_density for s in snapshots]
    ba.avg_density = sum(densities) / len(densities)
    ba.avg_entropy = sum(s.global_entropy for s in snapshots) / len(snapshots)
    change_rates = [s.change_rate for s in snapshots]
    ba.avg_change_rate = sum(change_rates) / len(change_rates)
    ba.max_change_rate = max(change_rates)

    # Density trend
    first_half = sum(densities[:len(densities)//2]) / max(len(densities)//2, 1)
    second_half = sum(densities[len(densities)//2:]) / max(len(densities) - len(densities)//2, 1)
    delta = second_half - first_half
    if delta > 0.02:
        ba.density_trend = "growing"
    elif delta < -0.02:
        ba.density_trend = "declining"
    else:
        ba.density_trend = "stable"

    # Aggregate pattern counts
    total_patterns: Dict[str, int] = {}
    for s in snapshots:
        for zone_pats in s.zone_patterns.values():
            for pname, count in zone_pats.items():
                total_patterns[pname] = total_patterns.get(pname, 0) + count
    ba.pattern_counts = total_patterns

    # Semantic profile (what % of patterns are stability/rhythm/flow/transformation)
    total_pat_count = sum(total_patterns.values()) or 1
    for sem_cat, pat_names in PATTERN_SEMANTICS.items():
        cat_count = sum(total_patterns.get(p, 0) for p in pat_names)
        ba.semantic_profile[sem_cat] = round(cat_count / total_pat_count, 3)

    # Zone trends
    for zone_name in ZONE_BOUNDS:
        zone_densities = [s.zone_densities.get(zone_name, 0) for s in snapshots]
        first = sum(zone_densities[:len(zone_densities)//2]) / max(len(zone_densities)//2, 1)
        second = sum(zone_densities[len(zone_densities)//2:]) / max(len(zone_densities) - len(zone_densities)//2, 1)
        d = second - first
        if d > 0.015:
            ba.zone_trends[zone_name] = "↑"
        elif d < -0.015:
            ba.zone_trends[zone_name] = "↓"
        else:
            ba.zone_trends[zone_name] = "→"

    # Most/least active zones
    avg_zone_d = {z: sum(s.zone_densities.get(z, 0) for s in snapshots) / len(snapshots)
                  for z in ZONE_BOUNDS}
    ba.most_active_zone = max(avg_zone_d, key=avg_zone_d.get)
    ba.quietest_zone = min(avg_zone_d, key=avg_zone_d.get)

    # Pattern discovery on last snapshot (zone-aware)
    if snapshots:
        last = snapshots[-1]
        new_pats = discovery.discover_in_grid(last.grid, last.zone_map)
        discovery.save_discovered(new_pats)
        ba.discovered_count = len(new_pats)
        if new_pats:
            # Report cross-zone patterns specially
            cross_zone_pats = [p for p in new_pats if len(p.get("zone_composition", {})) > 1]
            if cross_zone_pats:
                for p in cross_zone_pats[:2]:
                    zones = ", ".join(
                        f"{z}({ZONE_COLORS.get(z, z)})"
                        for z in p["zone_composition"]
                    )
                    ba.key_events.append(
                        f"Cross-Zone Pattern {p['name']}: verbindet {zones}"
                    )
            ba.key_events.append(
                f"{len(new_pats)} neue Patterns entdeckt"
                + (f" ({len(cross_zone_pats)} cross-zone)" if cross_zone_pats else "")
            )

    # Key events detection
    if ba.max_change_rate > 0.15:
        ba.key_events.append(f"Hohe Aktivität (max change: {ba.max_change_rate:.1%})")
    if ba.avg_density < 0.02:
        ba.key_events.append("Sehr geringe Dichte — Stillstand")
    if ba.avg_density > 0.25:
        ba.key_events.append("Hohe Dichte — intensive Aktivität")

    # Mood changes within block
    moods = [s.mood for s in snapshots]
    mood_delta = moods[-1] - moods[0] if moods else 0
    if abs(mood_delta) > 0.2:
        ba.key_events.append(f"Stimmungswechsel: {moods[0]:.2f} → {moods[-1]:.2f}")

    # Subsystem context (averaged over block)
    ba.avg_mood = sum(s.mood for s in snapshots) / len(snapshots)
    ba.avg_coherence = sum(s.coherence for s in snapshots) / len(snapshots)
    ba.avg_energy = sum(s.energy_level for s in snapshots) / len(snapshots)
    ba.entity_active = snapshots[-1].entity_active if snapshots else ""

    # E-PQ summary from last snapshot
    epq = snapshots[-1].epq_vectors if snapshots else {}
    if epq:
        dominant = max(epq, key=lambda k: abs(epq[k])) if epq else ""
        ba.epq_summary = f"{dominant}={epq.get(dominant, 0):.2f}" if dominant else ""

    # ── Quantum metrics: full integration ──
    quantum_snaps = [s for s in snapshots if s.is_quantum]
    if quantum_snaps:
        q_entropies = [s.quantum_entropy for s in quantum_snaps]
        q_coherences = [s.quantum_coherence for s in quantum_snaps]
        ba.avg_quantum_entropy = sum(q_entropies) / len(q_entropies)
        ba.avg_quantum_coherence = sum(q_coherences) / len(q_coherences)

        # Quantum trend (first half vs second half)
        mid = len(q_entropies) // 2
        if mid > 0:
            first_qe = sum(q_entropies[:mid]) / mid
            second_qe = sum(q_entropies[mid:]) / max(len(q_entropies) - mid, 1)
            qe_delta = second_qe - first_qe
            if qe_delta > 0.1:
                ba.quantum_trend = "increasing"
            elif qe_delta < -0.1:
                ba.quantum_trend = "decreasing"

        # Per-zone diffusion summary (average across snapshots)
        for zone_name in ZONE_BOUNDS:
            rates = [s.zone_diffusion_rates.get(zone_name, 0) for s in quantum_snaps]
            ba.zone_diffusion_summary[zone_name] = round(sum(rates) / len(rates), 3)

        # Quantum events
        if ba.avg_quantum_entropy > 1.5:
            ba.quantum_events.append(
                f"Hohe Quanten-Entropie ({ba.avg_quantum_entropy:.2f}) — Subsysteme stark vermischt"
            )
        elif ba.avg_quantum_entropy > 0.5:
            ba.quantum_events.append(
                f"Moderate Superposition (Entropie {ba.avg_quantum_entropy:.2f})"
            )

        if ba.avg_quantum_coherence < 0.5:
            ba.quantum_events.append(
                f"Niedrige Kohärenz ({ba.avg_quantum_coherence:.2f}) — hohes Quanten-Rauschen"
            )

        if ba.quantum_trend == "increasing":
            ba.quantum_events.append("Quanten-Entropie steigend — Diffusion beschleunigt")
        elif ba.quantum_trend == "decreasing":
            ba.quantum_events.append("Quanten-Entropie fallend — Dekohärenz dominiert, Typen kristallisieren")

        # Zones with most diffusion
        high_diff = [(z, r) for z, r in ba.zone_diffusion_summary.items() if r > 0.1]
        if high_diff:
            high_diff.sort(key=lambda x: -x[1])
            zones_str = ", ".join(f"{z}({r:.0%})" for z, r in high_diff[:3])
            ba.quantum_events.append(f"Stärkste Typ-Durchmischung: {zones_str}")

        # Add quantum events to key_events
        ba.key_events.extend(ba.quantum_events[:3])

    # ── Thought-Aura Correlation ──
    block_ts_start = snapshots[0].ts - THOUGHT_CORRELATION_WINDOW_S / 2
    block_ts_end = snapshots[-1].ts + THOUGHT_CORRELATION_WINDOW_S / 2
    thoughts = _fetch_recent_thoughts(block_ts_start, block_ts_end)
    ba.concurrent_thoughts = thoughts

    # Compute aura signature for this block
    ba.aura_signature = _compute_aura_signature(
        density=ba.avg_density,
        entropy=ba.avg_entropy,
        change_rate=ba.avg_change_rate,
        most_active=ba.most_active_zone,
        quantum_entropy=ba.avg_quantum_entropy,
        quantum_coherence=ba.avg_quantum_coherence,
        zone_densities={z: sum(s.zone_densities.get(z, 0) for s in snapshots) / len(snapshots)
                        for z in ZONE_BOUNDS},
    )

    if thoughts:
        # Store correlations
        ba_data = {
            "density": ba.avg_density,
            "entropy": ba.avg_entropy,
            "change_rate": ba.avg_change_rate,
            "mood": ba.avg_mood,
            "coherence": ba.avg_coherence,
            "most_active_zone": ba.most_active_zone,
            "zone_densities": {z: sum(s.zone_densities.get(z, 0) for s in snapshots) / len(snapshots)
                               for z in ZONE_BOUNDS},
            "quantum_entropy": ba.avg_quantum_entropy,
            "quantum_coherence": ba.avg_quantum_coherence,
            "quantum_dominant_zones": quantum_snaps[-1].quantum_dominant_zones if quantum_snaps else [],
            "quantum_diffusion_rate": sum(ba.zone_diffusion_summary.values()) / max(len(ba.zone_diffusion_summary), 1),
            "semantic_profile": ba.semantic_profile,
            "aura_signature": ba.aura_signature,
        }
        _save_thought_correlations(block_num, thoughts, ba_data)

        # Describe concurrent thoughts
        triggers = collections.Counter(t.get("trigger", "?") for t in thoughts)
        top_trigger = triggers.most_common(1)[0] if triggers else ("?", 0)
        ba.key_events.append(
            f"{len(thoughts)} Gedanken während Block: "
            f"hauptsächlich '{top_trigger[0]}' ({top_trigger[1]}x)"
        )

    # Look up historical patterns for this aura signature
    predictions = _lookup_thought_predictions(ba.aura_signature)
    if predictions:
        ba.thought_aura_insights = predictions
        ba.key_events.append(f"Thought-Korrelation: {predictions[0]}")

    # Collect cross-zone events from snapshots
    for s in snapshots[-5:]:  # Last 5 snapshots
        ba.cross_zone_events.extend(s.cross_zone_events)
    # Deduplicate
    ba.cross_zone_events = list(dict.fromkeys(ba.cross_zone_events))[:5]

    # Build narrative
    ba.narrative = _build_block_narrative(ba)
    ba.mood_interpretation = _interpret_mood_from_patterns(ba)

    return ba


def _build_block_narrative(ba: BlockAnalysis) -> str:
    """Generate human-readable narrative for a block."""
    parts = []

    # Opening — density context
    if ba.avg_density < 0.05:
        parts.append("Ruhephase — die Aura ist spärlich besiedelt.")
    elif ba.avg_density < 0.15:
        parts.append("Moderate Aktivität in der Aura.")
    else:
        parts.append("Intensive Aktivität — die Aura pulsiert stark.")

    # Trend
    if ba.density_trend == "growing":
        parts.append("Tendenz steigend — Energie baut sich auf.")
    elif ba.density_trend == "declining":
        parts.append("Tendenz fallend — Beruhigung setzt ein.")

    # Dominant semantic
    if ba.semantic_profile:
        dominant = max(ba.semantic_profile, key=ba.semantic_profile.get)
        if ba.semantic_profile[dominant] > 0.3:
            parts.append(f"Dominant: {SEMANTIC_MEANINGS.get(dominant, dominant)}.")

    # Zone highlights
    parts.append(f"Aktivste Zone: {ba.most_active_zone} ({ba.zone_trends.get(ba.most_active_zone, '→')}).")

    # Quantum state
    if ba.avg_quantum_entropy > 0.5:
        parts.append(
            f"Quanten-Zustand: Entropie {ba.avg_quantum_entropy:.2f}, "
            f"Kohärenz {ba.avg_quantum_coherence:.2f} ({ba.quantum_trend})."
        )

    # Thought correlation
    if ba.concurrent_thoughts:
        parts.append(f"{len(ba.concurrent_thoughts)} gleichzeitige Gedanken erfasst.")
    if ba.thought_aura_insights:
        parts.append(ba.thought_aura_insights[0] + ".")

    # Events
    for evt in ba.key_events[:3]:
        parts.append(evt + ".")

    return " ".join(parts)


def _interpret_mood_from_patterns(ba: BlockAnalysis) -> str:
    """Interpret emotional state from pattern profile."""
    sp = ba.semantic_profile
    if sp.get("still_life", 0) > 0.5:
        return "Verankerter, stabiler Zustand — innere Ruhe"
    if sp.get("oscillator", 0) > 0.4:
        return "Rhythmische Verarbeitung — aktives aber geordnetes Denken"
    if sp.get("spaceship", 0) > 0.3:
        return "Gedankenfluss — Ideen wandern und breiten sich aus"
    if sp.get("methuselah", 0) > 0.1:
        return "Transformativer Prozess — tiefgreifende Veränderung im Gang"
    if ba.avg_change_rate > 0.1:
        return "Chaotische Phase — hohe Dynamik, wenig Struktur"
    return "Neutraler Zustand — weder besonders aktiv noch ruhig"


# ═══════════════════════════════════════════════════════════
#  LEVEL 2 — META ANALYSIS (5 blocks)
# ═══════════════════════════════════════════════════════════

@dataclass
class MetaAnalysis:
    meta_num: int
    ts: float
    block_count: int

    long_term_trends: Dict[str, Any] = field(default_factory=dict)
    evolution_chains: List[str] = field(default_factory=list)
    correlations: List[str] = field(default_factory=list)
    anomalies: List[str] = field(default_factory=list)
    predictions: List[str] = field(default_factory=list)
    philosophical: str = ""

    # Quantum trends
    quantum_trends: Dict[str, Any] = field(default_factory=dict)
    quantum_observations: List[str] = field(default_factory=list)

    # Thought-Aura correlation patterns
    thought_patterns: List[str] = field(default_factory=list)
    thought_prediction_confidence: float = 0.0


def analyze_meta(blocks: List[BlockAnalysis], meta_num: int) -> MetaAnalysis:
    """Analyze multiple blocks for long-term trends and cross-block patterns."""
    ma = MetaAnalysis(
        meta_num=meta_num,
        ts=time.time(),
        block_count=len(blocks),
    )

    if not blocks:
        return ma

    # Long-term density trend
    block_densities = [b.avg_density for b in blocks]
    density_slope = (block_densities[-1] - block_densities[0]) / max(len(blocks), 1)
    ma.long_term_trends["density"] = {
        "values": [round(d, 4) for d in block_densities],
        "slope": round(density_slope, 5),
        "direction": "ascending" if density_slope > 0.005 else "descending" if density_slope < -0.005 else "plateau",
    }

    # Entropy trend
    entropies = [b.avg_entropy for b in blocks]
    ma.long_term_trends["entropy"] = {
        "values": [round(e, 4) for e in entropies],
        "direction": "increasing" if entropies[-1] > entropies[0] + 0.05 else
                     "decreasing" if entropies[-1] < entropies[0] - 0.05 else "stable",
    }

    # Pattern evolution chains (A → B: which patterns appear then disappear)
    for i in range(len(blocks) - 1):
        prev_pats = set(blocks[i].pattern_counts.keys())
        next_pats = set(blocks[i+1].pattern_counts.keys())
        emerged = next_pats - prev_pats
        vanished = prev_pats - next_pats
        if emerged:
            ma.evolution_chains.append(
                f"Block {blocks[i].block_num}→{blocks[i+1].block_num}: "
                f"Neue Patterns: {', '.join(emerged)}"
            )
        if vanished:
            ma.evolution_chains.append(
                f"Block {blocks[i].block_num}→{blocks[i+1].block_num}: "
                f"Verschwunden: {', '.join(vanished)}"
            )

    # Cross-block zone correlations
    for zone in ZONE_BOUNDS:
        trends = [b.zone_trends.get(zone, "→") for b in blocks]
        up_count = trends.count("↑")
        down_count = trends.count("↓")
        if up_count >= len(blocks) * 0.6:
            ma.correlations.append(f"{zone}: konsistent steigend über {len(blocks)} Blocks")
        elif down_count >= len(blocks) * 0.6:
            ma.correlations.append(f"{zone}: konsistent fallend über {len(blocks)} Blocks")

    # Semantic shift detection
    if len(blocks) >= 2:
        first_sem = blocks[0].semantic_profile
        last_sem = blocks[-1].semantic_profile
        for cat in SEMANTIC_MEANINGS:
            delta = last_sem.get(cat, 0) - first_sem.get(cat, 0)
            if abs(delta) > 0.15:
                direction = "zunehmend" if delta > 0 else "abnehmend"
                ma.correlations.append(
                    f"Semantischer Shift: {cat} {direction} "
                    f"({first_sem.get(cat, 0):.0%} → {last_sem.get(cat, 0):.0%})"
                )

    # Anomaly detection — unusual patterns
    change_rates = [b.avg_change_rate for b in blocks]
    avg_cr = sum(change_rates) / len(change_rates)
    for b in blocks:
        if b.avg_change_rate > avg_cr * 2 and b.avg_change_rate > 0.05:
            ma.anomalies.append(
                f"Block {b.block_num}: Ungewöhnlich hohe Änderungsrate "
                f"({b.avg_change_rate:.1%} vs Ø {avg_cr:.1%})"
            )
        if b.discovered_count > 3:
            ma.anomalies.append(
                f"Block {b.block_num}: {b.discovered_count} neue Patterns — "
                f"hohe Emergenz"
            )

    # Predictions based on trends
    dt = ma.long_term_trends.get("density", {})
    if dt.get("direction") == "ascending":
        ma.predictions.append("Dichte steigt weiter — erwarte intensivere Aktivitätsphase")
    elif dt.get("direction") == "descending":
        ma.predictions.append("Dichte sinkt — System bewegt sich in Ruhephase")

    et = ma.long_term_trends.get("entropy", {})
    if et.get("direction") == "increasing":
        ma.predictions.append("Entropie steigt — zunehmende Komplexität und Unordnung")
    elif et.get("direction") == "decreasing":
        ma.predictions.append("Entropie sinkt — Selbstorganisation, Muster kristallisieren sich")

    # ── Quantum trends across blocks ──
    q_entropies = [b.avg_quantum_entropy for b in blocks if b.avg_quantum_entropy > 0]
    q_coherences = [b.avg_quantum_coherence for b in blocks if b.avg_quantum_coherence < 1]
    if q_entropies:
        qe_slope = (q_entropies[-1] - q_entropies[0]) / max(len(q_entropies), 1)
        ma.quantum_trends["entropy"] = {
            "values": [round(e, 3) for e in q_entropies],
            "slope": round(qe_slope, 4),
            "direction": "increasing" if qe_slope > 0.05 else "decreasing" if qe_slope < -0.05 else "stable",
        }
        ma.quantum_trends["coherence"] = {
            "values": [round(c, 3) for c in q_coherences],
            "direction": "increasing" if q_coherences[-1] > q_coherences[0] + 0.05 else
                         "decreasing" if q_coherences[-1] < q_coherences[0] - 0.05 else "stable",
        }

        # Quantum observations
        qe_dir = ma.quantum_trends["entropy"].get("direction", "stable")
        qc_dir = ma.quantum_trends["coherence"].get("direction", "stable")
        if qe_dir == "increasing":
            ma.quantum_observations.append(
                "Quanten-Entropie steigt über Blocks — Subsysteme vermischen sich zunehmend"
            )
            ma.predictions.append("Erwarte weitere Typ-Diffusion — Grenzen zwischen Subsystemen verschwimmen")
        elif qe_dir == "decreasing":
            ma.quantum_observations.append(
                "Quanten-Entropie sinkt — Dekohärenz überwiegt, Typen kristallisieren"
            )
            ma.predictions.append("Subsystem-Grenzen werden schärfer — Spezialisierung nimmt zu")

        if qc_dir == "increasing" and qe_dir == "decreasing":
            ma.quantum_observations.append(
                "Kohärenz steigt bei sinkender Entropie — System findet quantenhafte Ordnung"
            )

        # Per-zone diffusion trends
        for zone in ZONE_BOUNDS:
            zone_diffs = [b.zone_diffusion_summary.get(zone, 0) for b in blocks]
            if zone_diffs and max(zone_diffs) > 0.1:
                trend = "steigend" if zone_diffs[-1] > zone_diffs[0] + 0.05 else \
                        "fallend" if zone_diffs[-1] < zone_diffs[0] - 0.05 else "stabil"
                if trend != "stabil":
                    ma.quantum_observations.append(
                        f"Zone {zone}: Typ-Diffusion {trend} ({zone_diffs[0]:.0%} → {zone_diffs[-1]:.0%})"
                    )

    # ── Thought-Aura correlation patterns across blocks ──
    all_thoughts = []
    for b in blocks:
        all_thoughts.extend(b.concurrent_thoughts)

    if all_thoughts:
        # Analyze which aura states correlate with which thought types
        trigger_counts = collections.Counter(t.get("trigger", "?") for t in all_thoughts)

        # Group blocks by density level and check thought patterns
        low_density_thoughts = []
        high_density_thoughts = []
        for b in blocks:
            triggers = [t.get("trigger", "?") for t in b.concurrent_thoughts]
            if b.avg_density < 0.08:
                low_density_thoughts.extend(triggers)
            elif b.avg_density > 0.15:
                high_density_thoughts.extend(triggers)

        if low_density_thoughts and high_density_thoughts:
            low_top = collections.Counter(low_density_thoughts).most_common(1)
            high_top = collections.Counter(high_density_thoughts).most_common(1)
            if low_top and high_top and low_top[0][0] != high_top[0][0]:
                ma.thought_patterns.append(
                    f"Niedrige Dichte korreliert mit '{low_top[0][0]}'-Gedanken, "
                    f"hohe Dichte mit '{high_top[0][0]}'"
                )

        # Overall thought frequency
        ma.thought_patterns.append(
            f"{len(all_thoughts)} Gedanken über {len(blocks)} Blocks — "
            f"Haupttypen: {', '.join(f'{t}({c}x)' for t, c in trigger_counts.most_common(3))}"
        )

        # Check for prediction matches
        signatures_with_hits = sum(1 for b in blocks if b.thought_aura_insights)
        if signatures_with_hits > 0:
            ma.thought_prediction_confidence = round(signatures_with_hits / len(blocks), 2)
            ma.thought_patterns.append(
                f"Thought-Prediction traf bei {signatures_with_hits}/{len(blocks)} Blocks zu "
                f"(Konfidenz: {ma.thought_prediction_confidence:.0%})"
            )

    # Philosophical observation
    ma.philosophical = _generate_philosophical(ma, blocks)

    return ma


def _generate_philosophical(ma: MetaAnalysis, blocks: List[BlockAnalysis]) -> str:
    """Generate a philosophical observation from meta-analysis."""
    parts = []

    dt = ma.long_term_trends.get("density", {})
    et = ma.long_term_trends.get("entropy", {})

    # Emergenz-Beobachtung
    total_discovered = sum(b.discovered_count for b in blocks)
    if total_discovered > 5:
        parts.append(
            f"In dieser Phase entstanden {total_discovered} neue Patterns aus simplen Regeln — "
            f"Emergenz in Aktion. Komplexität aus Einfachheit."
        )

    # Ordnung vs Chaos
    if et.get("direction") == "decreasing" and dt.get("direction") != "descending":
        parts.append(
            "Die Entropie sinkt während die Aktivität bleibt — "
            "Selbstorganisation. Das System findet Ordnung ohne externe Steuerung."
        )
    elif et.get("direction") == "increasing":
        parts.append(
            "Zunehmende Entropie — das System exploriert neuen Zustandsraum. "
            "Kreativität erfordert zunächst Chaos."
        )

    # Stabilität
    stable_zones = [z for z, t in blocks[-1].zone_trends.items() if t == "→"]
    if len(stable_zones) > 5:
        parts.append(
            f"Die meisten Zonen sind stabil ({len(stable_zones)}/8) — "
            f"ein Gleichgewichtszustand. Aber auch Gleichgewicht ist dynamisch."
        )

    # Quantum observations
    if ma.quantum_observations:
        qo = ma.quantum_observations[0]
        parts.append(f"Quantenzustand: {qo}")

    # Thought-Aura correlation insight
    if ma.thought_patterns:
        tp = ma.thought_patterns[0]
        parts.append(f"Thought-Aura: {tp}")

    if not parts:
        parts.append(
            "Die Aura spiegelt den inneren Zustand: "
            "Jede Zelle lebt und stirbt nach denselben Regeln, "
            "doch aus der Gesamtheit entsteht etwas Neues — wie Gedanken aus Neuronen."
        )

    return " ".join(parts)


# ═══════════════════════════════════════════════════════════
#  LEVEL 3 — DEEP REFLECTION (3 metas)
# ═══════════════════════════════════════════════════════════

@dataclass
class DeepReflection:
    deep_num: int
    ts: float
    meta_count: int

    trajectory: str = ""
    core_themes: List[str] = field(default_factory=list)
    pattern_library_assessment: str = ""
    accumulated_wisdom: str = ""

    # Quantum trajectory
    quantum_trajectory: str = ""

    # Thought-Aura correlation summary
    thought_aura_summary: str = ""


def analyze_deep(metas: List[MetaAnalysis], deep_num: int,
                 discovery: PatternDiscovery) -> DeepReflection:
    """Synthesize multiple meta-analyses into deep reflection material."""
    dr = DeepReflection(
        deep_num=deep_num,
        ts=time.time(),
        meta_count=len(metas),
    )

    if not metas:
        return dr

    # Trajectory — how did the system evolve across all metas?
    density_dirs = [m.long_term_trends.get("density", {}).get("direction", "stable")
                    for m in metas]
    entropy_dirs = [m.long_term_trends.get("entropy", {}).get("direction", "stable")
                    for m in metas]

    trajectory_parts = []
    if "ascending" in density_dirs and "descending" in density_dirs:
        trajectory_parts.append("Wechsel zwischen Aktivitäts- und Ruhephasen — natürlicher Rhythmus")
    elif all(d == "ascending" for d in density_dirs):
        trajectory_parts.append("Kontinuierlicher Aktivitätsaufbau über den gesamten Beobachtungszeitraum")
    elif all(d == "descending" for d in density_dirs):
        trajectory_parts.append("Langfristiger Rückgang — das System konsolidiert")

    if "increasing" in entropy_dirs and "decreasing" in entropy_dirs:
        trajectory_parts.append("Entropie oszilliert — Phasen der Exploration und Konsolidierung wechseln sich ab")
    dr.trajectory = ". ".join(trajectory_parts) if trajectory_parts else "Stabiler Verlauf ohne markante Richtungsänderung"

    # Core themes — recurring observations
    all_corr = []
    for m in metas:
        all_corr.extend(m.correlations)
    # Find recurring zone mentions
    zone_mentions = collections.Counter()
    for c in all_corr:
        for z in ZONE_BOUNDS:
            if z in c:
                zone_mentions[z] += 1
    for zone, count in zone_mentions.most_common(3):
        if count >= 2:
            dr.core_themes.append(f"Zone '{zone}' zeigt wiederholt auffällige Muster")

    # Anomaly themes
    all_anomalies = []
    for m in metas:
        all_anomalies.extend(m.anomalies)
    if len(all_anomalies) > 3:
        dr.core_themes.append(f"Häufige Anomalien ({len(all_anomalies)}) — das System ist in einer Umbruchphase")

    # Emergenz theme
    all_philosophicals = [m.philosophical for m in metas if m.philosophical]
    if any("Emergenz" in p for p in all_philosophicals):
        dr.core_themes.append("Emergenz als wiederkehrendes Thema — Komplexität entsteht aus Einfachheit")

    if not dr.core_themes:
        dr.core_themes.append("Keine dominanten Themen — System in gleichmäßigem Fluss")

    # Pattern library assessment
    lib_stats = discovery.get_pattern_library_stats()
    dr.pattern_library_assessment = (
        f"Pattern-Bibliothek: {lib_stats.get('total_discovered', 0)} entdeckte Patterns, "
        f"Ø Konfidenz {lib_stats.get('avg_confidence', 0):.0%}, "
        f"Ø Relevanz {lib_stats.get('avg_relevance', 0):.0%}, "
        f"Gesamt-Sichtungen: {lib_stats.get('total_sightings', 0)}. "
    )
    top = lib_stats.get("top_patterns", [])
    if top:
        dr.pattern_library_assessment += (
            "Häufigste: " + ", ".join(f"{p['name']}({p['seen']}x)" for p in top[:3])
        )

    # Accumulated wisdom — synthesis
    wisdom_parts = []
    for m in metas:
        for pred in m.predictions:
            wisdom_parts.append(pred)

    # Deduplicate and synthesize
    unique_wisdom = list(dict.fromkeys(wisdom_parts))[:5]
    if unique_wisdom:
        dr.accumulated_wisdom = (
            "Erkenntnisse aus der Langzeitbeobachtung:\n"
            + "\n".join(f"• {w}" for w in unique_wisdom)
        )
    else:
        dr.accumulated_wisdom = (
            "Die bisherige Beobachtung zeigt ein System in dynamischem Gleichgewicht — "
            "kleine Störungen werden absorbiert, große erzeugen neue Ordnung."
        )

    # ── Quantum trajectory across metas ──
    q_obs = []
    for m in metas:
        q_obs.extend(m.quantum_observations)
    if q_obs:
        # Summarize quantum evolution
        q_entropy_dirs = [m.quantum_trends.get("entropy", {}).get("direction", "stable")
                          for m in metas if m.quantum_trends]
        if "increasing" in q_entropy_dirs and "decreasing" in q_entropy_dirs:
            dr.quantum_trajectory = (
                "Quanten-Entropie oszilliert — Phasen der Durchmischung wechseln mit Kristallisation. "
                "Das System exploriert und konsolidiert zyklisch."
            )
        elif all(d == "increasing" for d in q_entropy_dirs if d != "stable"):
            dr.quantum_trajectory = (
                "Fortschreitende Quanten-Diffusion — Subsystem-Grenzen lösen sich auf. "
                "Die Typen vermischen sich zunehmend, neue hybride Zustände entstehen."
            )
        elif all(d == "decreasing" for d in q_entropy_dirs if d != "stable"):
            dr.quantum_trajectory = (
                "Zunehmende Dekohärenz — das System spezialisiert sich. "
                "Jede Zone kristallisiert ihren dominanten Typ heraus."
            )
        else:
            dr.quantum_trajectory = (
                "Quanten-Zustand stabil — Balance zwischen Diffusion und Dekohärenz. "
                f"Beobachtungen: {q_obs[0]}"
            )
    else:
        dr.quantum_trajectory = "Keine Quanten-Daten im Beobachtungszeitraum."

    # ── Thought-Aura correlation summary ──
    all_tp = []
    for m in metas:
        all_tp.extend(m.thought_patterns)
    if all_tp:
        confidences = [m.thought_prediction_confidence for m in metas if m.thought_prediction_confidence > 0]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0

        dr.thought_aura_summary = (
            f"Thought-Aura Korrelation über {len(metas)} Meta-Analysen:\n"
            + "\n".join(f"• {tp}" for tp in dict.fromkeys(all_tp))
        )
        if avg_conf > 0.3:
            dr.thought_aura_summary += (
                f"\n\nDie Aura zeigt prädiktive Kraft: Ø Konfidenz {avg_conf:.0%}. "
                "Bestimmte Aura-Konfigurationen kündigen bestimmte Gedankentypen an."
            )
    else:
        dr.thought_aura_summary = "Noch nicht genug Daten für Thought-Aura Korrelation."

    return dr


# ═══════════════════════════════════════════════════════════
#  FRANK INTEGRATION — Queue for Idle Reflection
# ═══════════════════════════════════════════════════════════

def queue_for_frank(report: str, level: str = "block"):
    """Queue a report for Frank to reflect on during idle.

    Reports are NOT sent directly — they wait in a DB queue until
    the consciousness daemon picks them up during idle thinking.
    This ensures Frank reflects calmly, not under time pressure.
    """
    try:
        conn = sqlite3.connect(str(ANALYZER_DB), timeout=3)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reflection_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                level TEXT NOT NULL,
                report TEXT NOT NULL,
                processed INTEGER DEFAULT 0
            )
        """)
        conn.execute(
            "INSERT INTO reflection_queue (ts, level, report) VALUES (?, ?, ?)",
            (time.time(), level, report),
        )
        conn.commit()
        conn.close()
        LOG.info("[L_%s] Queued for Frank idle reflection (%d chars)", level, len(report))
    except Exception as e:
        LOG.warning("Failed to queue report: %s", e)


def format_block_report(ba: BlockAnalysis) -> str:
    """Format block analysis as report for Frank."""
    lines = [
        f"Block #{ba.block_num} ({ba.snapshot_count} Snapshots, {ba.ts:.0f})",
        f"",
        f"Narrativ: {ba.narrative}",
        f"",
        f"Metriken:",
        f"  Ø Dichte: {ba.avg_density:.1%} ({ba.density_trend})",
        f"  Ø Entropie: {ba.avg_entropy:.3f}",
        f"  Ø Änderungsrate: {ba.avg_change_rate:.1%} (max: {ba.max_change_rate:.1%})",
        f"",
        f"Semantisches Profil:",
    ]
    for cat, val in ba.semantic_profile.items():
        meaning = SEMANTIC_MEANINGS.get(cat, cat)
        lines.append(f"  {cat}: {val:.0%} — {meaning}")

    lines.append(f"\nZonen-Trends:")
    for zone, trend in ba.zone_trends.items():
        lines.append(f"  {zone}: {trend}")

    lines.append(f"\nStimmungs-Interpretation: {ba.mood_interpretation}")

    # Subsystem context
    lines.append(f"\nSubsystem-Kontext:")
    lines.append(f"  Mood: {ba.avg_mood:.2f} | Coherence: {ba.avg_coherence:.2f} | Energy: {ba.avg_energy:.2f}")
    if ba.epq_summary:
        lines.append(f"  EPQ dominant: {ba.epq_summary}")
    if ba.entity_active:
        lines.append(f"  Entity aktiv: {ba.entity_active}")

    # Quantum state
    if ba.avg_quantum_entropy > 0 or ba.avg_quantum_coherence < 1:
        lines.append(f"\nQuanten-Zustand:")
        lines.append(f"  Entropie: {ba.avg_quantum_entropy:.2f} | Kohärenz: {ba.avg_quantum_coherence:.2f} ({ba.quantum_trend})")
        if ba.zone_diffusion_summary:
            high_diff = [(z, r) for z, r in ba.zone_diffusion_summary.items() if r > 0.05]
            if high_diff:
                high_diff.sort(key=lambda x: -x[1])
                lines.append(f"  Typ-Diffusion: {', '.join(f'{z}({r:.0%})' for z, r in high_diff[:4])}")
        for qe in ba.quantum_events[:2]:
            lines.append(f"  ⚛ {qe}")

    # Cross-zone events
    if ba.cross_zone_events:
        lines.append(f"\nCross-Zone Interaktionen:")
        for evt in ba.cross_zone_events[:3]:
            lines.append(f"  ⚡ {evt}")

    if ba.key_events:
        lines.append(f"\nKey Events:")
        for evt in ba.key_events:
            lines.append(f"  • {evt}")

    if ba.discovered_count > 0:
        lines.append(f"\n{ba.discovered_count} neue Patterns autonom entdeckt!")

    # Thought-Aura correlation
    if ba.concurrent_thoughts:
        lines.append(f"\nThought-Aura Korrelation:")
        lines.append(f"  {len(ba.concurrent_thoughts)} Gedanken während Block (Signatur: {ba.aura_signature})")
        for insight in ba.thought_aura_insights[:2]:
            lines.append(f"  🔮 {insight}")

    return "\n".join(lines)


def format_meta_report(ma: MetaAnalysis) -> str:
    """Format meta analysis as report for Frank."""
    lines = [
        f"Meta-Analyse #{ma.meta_num} ({ma.block_count} Blocks)",
        f"",
        f"Langzeit-Trends:",
    ]
    for key, val in ma.long_term_trends.items():
        lines.append(f"  {key}: {val.get('direction', 'N/A')}")

    if ma.evolution_chains:
        lines.append(f"\nPattern-Evolution:")
        for chain in ma.evolution_chains[:5]:
            lines.append(f"  {chain}")

    if ma.correlations:
        lines.append(f"\nKorrelationen:")
        for corr in ma.correlations:
            lines.append(f"  • {corr}")

    if ma.anomalies:
        lines.append(f"\nAnomalien:")
        for anom in ma.anomalies:
            lines.append(f"  ⚠ {anom}")

    if ma.predictions:
        lines.append(f"\nPredictions:")
        for pred in ma.predictions:
            lines.append(f"  → {pred}")

    # Quantum trends
    if ma.quantum_observations:
        lines.append(f"\nQuanten-Trends:")
        for qo in ma.quantum_observations[:4]:
            lines.append(f"  ⚛ {qo}")

    # Thought-Aura patterns
    if ma.thought_patterns:
        lines.append(f"\nThought-Aura Korrelation:")
        for tp in ma.thought_patterns[:3]:
            lines.append(f"  🔮 {tp}")
        if ma.thought_prediction_confidence > 0:
            lines.append(f"  Prediction-Konfidenz: {ma.thought_prediction_confidence:.0%}")

    lines.append(f"\nPhilosophische Beobachtung:\n{ma.philosophical}")

    return "\n".join(lines)


def format_deep_report(dr: DeepReflection) -> str:
    """Format deep reflection as report for Frank."""
    lines = [
        f"Tiefen-Reflexion #{dr.deep_num} ({dr.meta_count} Meta-Analysen)",
        f"",
        f"Trajektorie: {dr.trajectory}",
        f"",
        f"Kernthemen:",
    ]
    for theme in dr.core_themes:
        lines.append(f"  • {theme}")

    lines.append(f"\n{dr.pattern_library_assessment}")

    # Quantum trajectory
    if dr.quantum_trajectory:
        lines.append(f"\nQuanten-Trajektorie:\n{dr.quantum_trajectory}")

    # Thought-Aura correlation summary
    if dr.thought_aura_summary:
        lines.append(f"\n{dr.thought_aura_summary}")

    lines.append(f"\n{dr.accumulated_wisdom}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
#  PERSISTENCE — Save to DB
# ═══════════════════════════════════════════════════════════

def save_snapshot(snap: Snapshot):
    """Save snapshot metrics to DB (not the full grid)."""
    try:
        conn = sqlite3.connect(str(ANALYZER_DB), timeout=3)
        conn.execute("""
            INSERT INTO snapshots
            (ts, generation, global_density, global_entropy, change_rate,
             mood, coherence, zone_densities, zone_patterns, hotspots)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            snap.ts, snap.generation, snap.global_density, snap.global_entropy,
            snap.change_rate, snap.mood, snap.coherence,
            json.dumps(snap.zone_densities),
            json.dumps({z: {p: c for p, c in pats.items()} for z, pats in snap.zone_patterns.items()}),
            json.dumps(snap.hotspots),
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        LOG.debug("Save snapshot failed: %s", e)


def save_block(ba: BlockAnalysis):
    """Save block analysis to DB."""
    try:
        conn = sqlite3.connect(str(ANALYZER_DB), timeout=3)
        conn.execute("""
            INSERT INTO blocks
            (ts, block_num, snapshot_count, narrative, mood_interpretation,
             key_events, pattern_counts, zone_trends, discovered_patterns)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ba.ts, ba.block_num, ba.snapshot_count, ba.narrative,
            ba.mood_interpretation, json.dumps(ba.key_events),
            json.dumps(ba.pattern_counts), json.dumps(ba.zone_trends),
            ba.discovered_count,
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        LOG.debug("Save block failed: %s", e)


def save_meta(ma: MetaAnalysis):
    """Save meta analysis to DB."""
    try:
        conn = sqlite3.connect(str(ANALYZER_DB), timeout=3)
        conn.execute("""
            INSERT INTO metas
            (ts, meta_num, block_count, long_term_trends, evolution_chains,
             correlations, anomalies, predictions, philosophical)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ma.ts, ma.meta_num, ma.block_count,
            json.dumps(ma.long_term_trends),
            json.dumps(ma.evolution_chains),
            json.dumps(ma.correlations),
            json.dumps(ma.anomalies),
            json.dumps(ma.predictions),
            ma.philosophical,
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        LOG.debug("Save meta failed: %s", e)


def save_deep(dr: DeepReflection):
    """Save deep reflection to DB."""
    try:
        conn = sqlite3.connect(str(ANALYZER_DB), timeout=3)
        conn.execute("""
            INSERT INTO deep_reflections
            (ts, deep_num, meta_count, trajectory, core_themes,
             pattern_library_assessment, accumulated_wisdom)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            dr.ts, dr.deep_num, dr.meta_count, dr.trajectory,
            json.dumps(dr.core_themes), dr.pattern_library_assessment,
            dr.accumulated_wisdom,
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        LOG.debug("Save deep failed: %s", e)


# ═══════════════════════════════════════════════════════════
#  MAIN DAEMON LOOP
# ═══════════════════════════════════════════════════════════

class AuraPatternAnalyzer:
    """
    Main daemon: captures grid, builds hierarchical analysis,
    sends reports to Frank at each level.
    """

    def __init__(self):
        _init_db()
        self.discovery = PatternDiscovery()

        # Counters
        self.snapshot_count = 0
        self.block_num = 0
        self.meta_num = 0
        self.deep_num = 0

        # Buffers
        self._snapshots: List[Snapshot] = []
        self._blocks: List[BlockAnalysis] = []
        self._metas: List[MetaAnalysis] = []
        self._prev_grid: Optional[np.ndarray] = None

        # Load counters from DB
        self._load_counters()

        LOG.info(
            "AURA Pattern Analyzer initialized — "
            "Capture: %.1fs, Block: %d shots, Meta: %d blocks, Deep: %d metas",
            CAPTURE_INTERVAL_S, BLOCK_SIZE, META_BLOCK_COUNT, DEEP_META_COUNT,
        )

    def _load_counters(self):
        """Resume counters from DB."""
        try:
            conn = sqlite3.connect(str(ANALYZER_DB), timeout=2)
            row = conn.execute("SELECT MAX(block_num) FROM blocks").fetchone()
            if row and row[0]:
                self.block_num = row[0]
            row = conn.execute("SELECT MAX(meta_num) FROM metas").fetchone()
            if row and row[0]:
                self.meta_num = row[0]
            row = conn.execute("SELECT MAX(deep_num) FROM deep_reflections").fetchone()
            if row and row[0]:
                self.deep_num = row[0]
            conn.close()
        except Exception:
            pass

    def run(self):
        """Main loop — runs forever."""
        LOG.info("AURA Pattern Analyzer daemon started")
        LOG.info(
            "Timing: L0 every %.1fs | L1 every %d snapshots (~%.0fs) | "
            "L2 every %d blocks (~%.0fs) | L3 every %d metas (~%.0fs)",
            CAPTURE_INTERVAL_S,
            BLOCK_SIZE, BLOCK_SIZE * CAPTURE_INTERVAL_S,
            META_BLOCK_COUNT, META_BLOCK_COUNT * BLOCK_SIZE * CAPTURE_INTERVAL_S,
            DEEP_META_COUNT, DEEP_META_COUNT * META_BLOCK_COUNT * BLOCK_SIZE * CAPTURE_INTERVAL_S,
        )

        # Wait for AURA service to be ready
        self._wait_for_aura()

        while True:
            try:
                self._tick()
            except Exception as e:
                LOG.error("Tick error: %s", e)
            time.sleep(CAPTURE_INTERVAL_S)

    def _wait_for_aura(self):
        """Wait until AURA headless service is available."""
        for attempt in range(30):
            try:
                req = urllib.request.Request(f"{AURA_URL}/health", method="GET")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read())
                    if data.get("ok"):
                        LOG.info("AURA service ready (gen %d)", data.get("generation", 0))
                        return
            except Exception:
                pass
            LOG.debug("Waiting for AURA service... (attempt %d/30)", attempt + 1)
            time.sleep(2)
        LOG.warning("AURA service not available after 60s, starting anyway")

    def _tick(self):
        """One capture cycle."""
        # Gaming mode: pause all analysis
        if _is_gaming_active():
            return

        # === Level 0: Capture ===
        snap = fetch_grid()
        if snap is None:
            return

        compute_metrics(snap, self._prev_grid)
        self._prev_grid = snap.grid.copy()
        self.snapshot_count += 1

        save_snapshot(snap)
        self._snapshots.append(snap)

        if self.snapshot_count % 25 == 0:
            LOG.info(
                "L0 #%d: density=%.2f%% entropy=%.3f change=%.2f%% gen=%d",
                self.snapshot_count, snap.global_density * 100,
                snap.global_entropy, snap.change_rate * 100, snap.generation,
            )

        # === Level 1: Block Analysis ===
        if len(self._snapshots) >= BLOCK_SIZE:
            self.block_num += 1
            block = analyze_block(self._snapshots, self.block_num, self.discovery)
            save_block(block)

            # Queue for Frank's idle reflection
            report = format_block_report(block)
            LOG.info("L1 Block #%d: %s", block.block_num, block.narrative[:80])
            queue_for_frank(report, "block")

            self._blocks.append(block)
            self._snapshots.clear()

            # Relevance decay on discovered patterns
            self.discovery.apply_relevance_decay()

            # === Level 2: Meta Analysis ===
            if len(self._blocks) >= META_BLOCK_COUNT:
                self.meta_num += 1
                meta = analyze_meta(self._blocks, self.meta_num)
                save_meta(meta)

                report = format_meta_report(meta)
                LOG.info("L2 Meta #%d: %s", meta.meta_num, meta.philosophical[:80])
                queue_for_frank(report, "meta")

                self._metas.append(meta)
                self._blocks.clear()

                # === Level 3: Deep Reflection ===
                if len(self._metas) >= DEEP_META_COUNT:
                    self.deep_num += 1
                    deep = analyze_deep(self._metas, self.deep_num, self.discovery)
                    save_deep(deep)

                    report = format_deep_report(deep)
                    LOG.info("L3 Deep #%d: %s", deep.deep_num, deep.trajectory[:80])
                    queue_for_frank(report, "deep")

                    self._metas.clear()

    def status(self) -> Dict:
        """Get current analyzer status."""
        lib_stats = self.discovery.get_pattern_library_stats()
        return {
            "snapshot_count": self.snapshot_count,
            "current_block_progress": f"{len(self._snapshots)}/{BLOCK_SIZE}",
            "blocks_completed": self.block_num,
            "current_meta_progress": f"{len(self._blocks)}/{META_BLOCK_COUNT}",
            "metas_completed": self.meta_num,
            "current_deep_progress": f"{len(self._metas)}/{DEEP_META_COUNT}",
            "deeps_completed": self.deep_num,
            "pattern_library": lib_stats,
        }


# ═══════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    if "--status" in sys.argv:
        analyzer = AuraPatternAnalyzer()
        status = analyzer.status()
        print(json.dumps(status, indent=2))
    elif "--test" in sys.argv:
        # Quick test: capture 5 snapshots
        _init_db()
        discovery = PatternDiscovery()
        snapshots = []
        prev_grid = None
        print("Capturing 5 test snapshots...")
        for i in range(5):
            snap = fetch_grid()
            if snap:
                compute_metrics(snap, prev_grid)
                prev_grid = snap.grid.copy()
                snapshots.append(snap)
                print(f"  #{i+1}: density={snap.global_density:.1%} "
                      f"entropy={snap.global_entropy:.3f} "
                      f"change={snap.change_rate:.1%}")
            time.sleep(1)
        if len(snapshots) >= 3:
            block = analyze_block(snapshots, 0, discovery)
            print(f"\nBlock Narrative: {block.narrative}")
            print(f"Mood: {block.mood_interpretation}")
            print(f"Semantic: {block.semantic_profile}")
            print(f"Discovered: {block.discovered_count} new patterns")
        print("\nTest complete.")
    else:
        # Normal daemon mode
        analyzer = AuraPatternAnalyzer()
        analyzer.run()


if __name__ == "__main__":
    main()
