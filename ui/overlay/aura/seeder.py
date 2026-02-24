"""Aura — Grid Seeding from Frank's Consciousness State.

Seeds the 256×256 cellular automaton grid from Frank's real-time
subsystem data.  8 zones in 4×2 layout, each 64w × 128h.

Pseudo-3D enhancements:
  - Organic blob seeding via gaussian-filtered noise
  - Gosper Glider Guns for permanent autonomous movement
  - LWSS/HWSS floaters at edges
  - "Nerve path" random-walk connections between zone centres
  - 5-8 % base noise fill across the entire grid
"""

import hashlib

import numpy as np

try:
    from scipy.ndimage import gaussian_filter as _gauss
    _HAS_GAUSS = True
except ImportError:
    _HAS_GAUSS = False

from .config import GRID_SIZE, ZONE_WIDTH, ZONE_HEIGHT, MAX_DENSITY, ZONE_LAYOUT
from .patterns import (
    BLOCK, BEEHIVE, LOAF, BLINKER, TOAD, PULSAR, GLIDER, LWSS, HWSS,
    GOSPER_GLIDER_GUN, place_pattern, select_pattern_by_length,
    get_glider_towards,
)


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _get_zone(grid: np.ndarray, zone_name: str) -> np.ndarray:
    """Get a view of the zone region (ZONE_HEIGHT × ZONE_WIDTH) in the grid."""
    row, col = ZONE_LAYOUT[zone_name]
    y0 = row * ZONE_HEIGHT
    x0 = col * ZONE_WIDTH
    return grid[y0:y0 + ZONE_HEIGHT, x0:x0 + ZONE_WIDTH]


def _organic_fill(zone: np.ndarray, density: float, rng, sigma: float = 3.0):
    """Fill *zone* with organic blobs using gaussian-smoothed noise."""
    if _HAS_GAUSS and density > 0:
        raw = rng.random(zone.shape).astype(np.float32)
        smoothed = _gauss(raw, sigma=sigma)
        threshold = np.percentile(smoothed, max(0, (1.0 - density) * 100))
        zone[:] |= (smoothed >= threshold).astype(np.uint8)
    else:
        zone[:] |= (rng.random(zone.shape) < density).astype(np.uint8)


def _fill_with_beehives(zone: np.ndarray, radius: int):
    """Fill zone with stable beehive patterns inside a circular region."""
    zh, zw = zone.shape
    cy, cx = zh // 2, zw // 2
    for y in range(0, zh - 3, 5):
        for x in range(0, zw - 4, 6):
            dy, dx = y + 1 - cy, x + 2 - cx
            if dy * dy + dx * dx <= radius * radius:
                place_pattern(zone, y, x, BEEHIVE)


def _draw_nerve_paths(grid: np.ndarray, rng):
    """Draw organic 'nerve' connections between zone centres via random walks."""
    centres = []
    for _name, (row, col) in ZONE_LAYOUT.items():
        centres.append((row * ZONE_HEIGHT + ZONE_HEIGHT // 2,
                         col * ZONE_WIDTH + ZONE_WIDTH // 2))

    pairs = [
        (0, 1), (1, 2), (2, 3),           # top row
        (4, 5), (5, 6), (6, 7),           # bottom row
        (0, 4), (1, 5), (2, 6), (3, 7),   # vertical
    ]
    for i, j in pairs:
        if rng.random() < 0.45:
            continue
        y, x = centres[i]
        ty, tx = centres[j]
        steps = int((abs(ty - y) + abs(tx - x)) * 1.3)
        for _ in range(steps):
            yi, xi = int(y), int(x)
            if 0 <= yi < GRID_SIZE and 0 <= xi < GRID_SIZE:
                grid[yi, xi] = 1
            dy = (1 if ty > y else -1 if ty < y else 0) if rng.random() < 0.55 else rng.choice([-1, 0, 1])
            dx = (1 if tx > x else -1 if tx < x else 0) if rng.random() < 0.55 else rng.choice([-1, 0, 1])
            y = int(np.clip(y + dy, 0, GRID_SIZE - 1))
            x = int(np.clip(x + dx, 0, GRID_SIZE - 1))


# ──────────────────────────────────────────────────────────────
# Main seeder
# ──────────────────────────────────────────────────────────────

def seed_grid(state: dict) -> np.ndarray:
    """Seed a 256×256 grid from Frank's current state."""
    grid = np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.uint8)
    rng = np.random.default_rng()

    # Base noise fill (6 %)
    _organic_fill(grid, 0.06, rng, sigma=2.0)

    # Zone-specific seeding
    _seed_epq(grid, state.get("epq_vectors", {}), rng)
    _seed_mood(grid, state.get("mood_buffer", 0.5), state.get("coherence", 0.5), rng)
    _seed_reflexion(grid, state.get("reflections", []))
    _seed_entities(grid, state.get("entities", []))
    _seed_ego(grid, state.get("ego_state", {}), rng)
    _seed_quantum(grid, state.get("quantum_coherence", 0.5), rng)
    _seed_titan(grid, state.get("reflections", []), rng)
    _seed_hardware(grid, state.get("cpu_temp", 50), state.get("ram_percent", 50), rng)

    # Nerve paths between zones
    _draw_nerve_paths(grid, rng)

    # Glider Guns (permanent autonomous movement)
    _place_glider_guns(grid)

    # Edge floaters (LWSS / HWSS)
    _place_edge_floaters(grid, rng)

    # Global density clamp
    alive = int(np.sum(grid))
    max_alive = int(GRID_SIZE * GRID_SIZE * MAX_DENSITY)
    if alive > max_alive:
        live_coords = np.argwhere(grid == 1)
        excess = alive - max_alive
        kill_idx = rng.choice(len(live_coords), size=int(excess), replace=False)
        grid[live_coords[kill_idx, 0], live_coords[kill_idx, 1]] = 0

    return grid


# ──────────────────────────────────────────────────────────────
# Movement generators
# ──────────────────────────────────────────────────────────────

def _place_glider_guns(grid: np.ndarray):
    """Place 2–3 Gosper Glider Guns at strategic positions."""
    gun = GOSPER_GLIDER_GUN
    place_pattern(grid, 8, 8, gun)
    place_pattern(grid, GRID_SIZE - 18, GRID_SIZE - 44, np.rot90(gun, 2))
    place_pattern(grid, GRID_SIZE // 2 - 18, 4, np.rot90(gun, 1))


def _place_edge_floaters(grid: np.ndarray, rng):
    """Spawn 3–5 spaceships at random edges."""
    ships = [LWSS, HWSS, LWSS]
    for ship in ships:
        rot = rng.integers(0, 4)
        pat = np.rot90(ship, rot)
        ph, pw = pat.shape
        edge = rng.integers(0, 4)
        if edge == 0:
            y, x = 2, rng.integers(10, GRID_SIZE - pw - 10)
        elif edge == 1:
            y, x = rng.integers(10, GRID_SIZE - ph - 10), GRID_SIZE - pw - 2
        elif edge == 2:
            y, x = GRID_SIZE - ph - 2, rng.integers(10, GRID_SIZE - pw - 10)
        else:
            y, x = rng.integers(10, GRID_SIZE - ph - 10), 2
        place_pattern(grid, y, x, pat)


# ──────────────────────────────────────────────────────────────
# Zone seeders (all use zone.shape for dimensions)
# ──────────────────────────────────────────────────────────────

def _seed_epq(grid: np.ndarray, epq_vectors: dict, rng):
    """E-PQ Zone: 5 vectors → organic bands, density ∝ |value|."""
    zone = _get_zone(grid, "epq")
    zh, zw = zone.shape
    default_vectors = {
        "precision": 0.15, "risk": -0.1, "empathy": 0.3,
        "autonomy": 0.2, "vigilance": -0.05,
    }
    vectors = {**default_vectors, **epq_vectors}
    band_h = zh // 5
    for i, (name, value) in enumerate(list(vectors.items())[:5]):
        y0 = i * band_h
        y1 = min(y0 + band_h, zh)
        density = min(abs(value), 1.0)
        band = zone[y0:y1, :]
        _organic_fill(band, density, rng, sigma=2.5)


def _seed_mood(grid: np.ndarray, mood_buffer: float, coherence: float, rng):
    """Mood Zone: concentric circle + geometric/chaotic fill."""
    zone = _get_zone(grid, "mood")
    zh, zw = zone.shape
    radius = int(max(0.0, min(1.0, mood_buffer)) * min(zh, zw) * 0.45)
    if coherence > 0.7:
        _fill_with_beehives(zone, max(radius, 5))
    else:
        cy, cx = zh // 2, zw // 2
        yy, xx = np.ogrid[:zh, :zw]
        dist = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
        mask = dist <= max(radius, 3)
        density = max(0.15, mood_buffer)
        sub = np.zeros_like(zone)
        sub[mask] = 1
        _organic_fill(sub, density, rng, sigma=2.0)
        zone[:] |= sub & mask.astype(np.uint8)


def _seed_reflexion(grid: np.ndarray, reflections: list):
    """Reflexion Zone: recent reflections → GoL patterns by length."""
    zone = _get_zone(grid, "reflexion")
    zh, zw = zone.shape
    recent = reflections[-8:] if reflections else []
    for i, ref in enumerate(recent):
        content = ref.get("content", "") if isinstance(ref, dict) else str(ref)
        text_len = len(content)
        pattern = select_pattern_by_length(text_len)
        h = int(hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()[:8], 16)
        x = h % max(1, zw - pattern.shape[1])
        y = (i * (zh // 8)) % max(1, zh - pattern.shape[0])
        place_pattern(zone, y, x, pattern)


def _seed_entities(grid: np.ndarray, entities: list):
    """Entity Zone: active entities → pulsars/blinkers/blocks + gliders."""
    zone = _get_zone(grid, "entities")
    zh, zw = zone.shape
    if not entities:
        place_pattern(zone, 10, 10, BLOCK)
        place_pattern(zone, zh // 2, zw // 2, BLINKER)
        return

    spacing = max(1, zh // max(len(entities), 1))
    for i, entity in enumerate(entities):
        if isinstance(entity, dict):
            in_session = entity.get("is_in_session", False)
            is_active = entity.get("is_active", False)
        else:
            in_session = False
            is_active = True

        y = (i * spacing) % (zh - 15)
        x = (i * 17 + 5) % (zw - 15)

        if in_session:
            place_pattern(zone, y, x, PULSAR)
            glider = get_glider_towards("center")
            place_pattern(zone, y + 14, x + 14, glider)
        elif is_active:
            place_pattern(zone, y, x, BLINKER)
        else:
            place_pattern(zone, y, x, BLOCK)


def _seed_ego(grid: np.ndarray, ego_state: dict, rng):
    """Ego Zone: embodiment level → organic density core."""
    zone = _get_zone(grid, "ego")
    zh, zw = zone.shape
    embodiment = ego_state.get("embodiment_level", 0.5)
    density = max(0.1, min(0.6, embodiment))

    core_h = int(20 + density * 40)
    core_w = int(20 + density * 20)
    cy, cx = zh // 2, zw // 2
    y0, y1 = max(0, cy - core_h // 2), min(zh, cy + core_h // 2)
    x0, x1 = max(0, cx - core_w // 2), min(zw, cx + core_w // 2)
    core = zone[y0:y1, x0:x1]
    _organic_fill(core, density, rng, sigma=2.5)

    place_pattern(zone, 5, 5, BLOCK)
    place_pattern(zone, 5, zw - 7, BLOCK)
    place_pattern(zone, zh - 7, 5, BLOCK)
    place_pattern(zone, zh - 7, zw - 7, BLOCK)


def _seed_quantum(grid: np.ndarray, coherence_score: float, rng):
    """Quantum Zone: coherence → 4-fold symmetry with organic fill."""
    zone = _get_zone(grid, "quantum")
    zh, zw = zone.shape
    half_h, half_w = zh // 2, zw // 2

    if coherence_score > 0.6:
        quadrant = np.zeros((half_h, half_w), dtype=np.uint8)
        _organic_fill(quadrant, 0.3, rng, sigma=3.0)
        zone[0:half_h, 0:half_w] = quadrant
        zone[0:half_h, half_w:zw] = np.fliplr(quadrant)
        zone[half_h:zh, 0:half_w] = np.flipud(quadrant)
        zone[half_h:zh, half_w:zw] = np.fliplr(np.flipud(quadrant))
    else:
        _organic_fill(zone, 0.4, rng, sigma=2.0)


def _seed_titan(grid: np.ndarray, reflections: list, rng):
    """Titan Memory Zone: sparse organic base + stable patterns."""
    zone = _get_zone(grid, "titan")
    zh, zw = zone.shape
    n_reflections = len(reflections)
    base_density = min(0.3, 0.05 + n_reflections * 0.02)
    _organic_fill(zone, base_density, rng, sigma=3.5)

    for i in range(min(6, n_reflections)):
        y = (i * (zh // 6) + 3) % (zh - 4)
        x = (i * 11 + 7) % (zw - 4)
        place_pattern(zone, y, x, LOAF if i % 2 == 0 else BEEHIVE)


def _seed_hardware(grid: np.ndarray, cpu_temp: float, ram_percent: float, rng):
    """Hardware Zone: CPU temp → density, RAM → fill level, organic."""
    zone = _get_zone(grid, "hardware")
    zh, zw = zone.shape
    base_density = min(0.7, cpu_temp / 100.0)
    ram_level = int((ram_percent / 100.0) * zh)
    ram_level = max(1, min(zh, ram_level))

    bottom = zone[zh - ram_level:, :]
    _organic_fill(bottom, base_density, rng, sigma=2.0)
