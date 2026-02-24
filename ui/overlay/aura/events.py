"""Aura — Event Animations.

Reactive animations that modify the automaton grid in response to Frank's events:
- Chat ripple (expanding ring of cells from center)
- Threat flash (red overlay)
- Entity pulse (new patterns in entity zone)
- Reflexion pop-in (new automaton structure in reflexion zone)
- Memory flash (brief burst in titan zone)
"""

import time
from collections import deque

import numpy as np

from .config import (
    GRID_SIZE, ZONE_WIDTH, ZONE_HEIGHT, ZONE_LAYOUT,
    RIPPLE_CENTER, RIPPLE_MAX_RADIUS, RIPPLE_RING_THICKNESS,
    RIPPLE_DENSITY, RIPPLE_STEP,
    THREAT_FLASH_MS, THREAT_DECAY_MS,
)
from .patterns import (
    PULSAR, BLINKER, BLOCK, LWSS, HWSS,
    place_pattern, select_pattern_by_length,
)


class EventManager:
    """Manages event-driven animations on the GoL grid."""

    def __init__(self):
        # Active ripple animations: list of (current_radius, center_y, center_x)
        self._ripples: list[dict] = []

        # Threat state
        self._threat_start: float = 0.0
        self._threat_active: bool = False

        # Pending cell injections (applied on next tick)
        self._pending_injections: deque[np.ndarray] = deque(maxlen=32)

        # Titan flash state
        self._titan_flash_until: float = 0.0

    @property
    def threat_intensity(self) -> float:
        """Current threat visual intensity (0.0-1.0)."""
        if not self._threat_active:
            return 0.0
        elapsed_ms = (time.monotonic() - self._threat_start) * 1000
        if elapsed_ms < THREAT_FLASH_MS:
            return 1.0  # Full flash
        decay_elapsed = elapsed_ms - THREAT_FLASH_MS
        if decay_elapsed > THREAT_DECAY_MS:
            self._threat_active = False
            return 0.0
        return 1.0 - (decay_elapsed / THREAT_DECAY_MS)

    @property
    def titan_flash_active(self) -> bool:
        return time.monotonic() < self._titan_flash_until

    def trigger_chat_ripple(self, center: tuple[int, int] = RIPPLE_CENTER):
        """Trigger a ripple effect (expanding ring of cells from center)."""
        self._ripples.append({
            "radius": 0,
            "center_y": center[0],
            "center_x": center[1],
            "max_radius": RIPPLE_MAX_RADIUS,
        })

    def trigger_threat(self):
        """Trigger existential threat flash."""
        self._threat_active = True
        self._threat_start = time.monotonic()

    def trigger_entity_session(self, entity_idx: int = 0):
        """Trigger entity session start — inject pulsar in entity zone."""
        row, col = ZONE_LAYOUT["entities"]
        y0 = row * ZONE_HEIGHT
        x0 = col * ZONE_WIDTH
        ey = y0 + (entity_idx * 17 + 5) % (ZONE_HEIGHT - 15)
        ex = x0 + (entity_idx * 13 + 10) % (ZONE_WIDTH - 15)
        mask = np.zeros((GRID_SIZE, GRID_SIZE), dtype=bool)
        ph, pw = PULSAR.shape
        ey1 = min(ey + ph, GRID_SIZE)
        ex1 = min(ex + pw, GRID_SIZE)
        mask[ey:ey1, ex:ex1] = PULSAR[:ey1 - ey, :ex1 - ex] > 0
        self._pending_injections.append(mask)

    def trigger_reflexion(self, content: str = ""):
        """Trigger new reflexion — inject GoL pattern in reflexion zone."""
        row, col = ZONE_LAYOUT["reflexion"]
        y0 = row * ZONE_HEIGHT
        x0 = col * ZONE_WIDTH
        pattern = select_pattern_by_length(len(content))
        ph, pw = pattern.shape
        rng = np.random.default_rng()
        ey = y0 + rng.integers(0, max(1, ZONE_HEIGHT - ph))
        ex = x0 + rng.integers(0, max(1, ZONE_WIDTH - pw))
        mask = np.zeros((GRID_SIZE, GRID_SIZE), dtype=bool)
        ey1 = min(ey + ph, GRID_SIZE)
        ex1 = min(ex + pw, GRID_SIZE)
        mask[ey:ey1, ex:ex1] = pattern[:ey1 - ey, :ex1 - ex] > 0
        self._pending_injections.append(mask)

    def trigger_titan_flash(self):
        """Brief light flash in titan memory zone."""
        self._titan_flash_until = time.monotonic() + 0.2
        row, col = ZONE_LAYOUT["titan"]
        y0 = row * ZONE_HEIGHT
        x0 = col * ZONE_WIDTH
        rng = np.random.default_rng()
        mask = np.zeros((GRID_SIZE, GRID_SIZE), dtype=bool)
        burst = rng.random((ZONE_HEIGHT, ZONE_WIDTH)) < 0.15
        mask[y0:y0 + ZONE_HEIGHT, x0:x0 + ZONE_WIDTH] = burst
        self._pending_injections.append(mask)

    def trigger_mood_shift(self, mood_delta: float):
        """Mood shift — inject/remove cells in mood zone."""
        row, col = ZONE_LAYOUT["mood"]
        y0 = row * ZONE_HEIGHT
        x0 = col * ZONE_WIDTH
        if mood_delta > 0:
            rng = np.random.default_rng()
            mask = np.zeros((GRID_SIZE, GRID_SIZE), dtype=bool)
            burst = rng.random((ZONE_HEIGHT, ZONE_WIDTH)) < (mood_delta * 0.3)
            mask[y0:y0 + ZONE_HEIGHT, x0:x0 + ZONE_WIDTH] = burst
            self._pending_injections.append(mask)

    def trigger_floater(self):
        """Inject a random spaceship at a random grid edge."""
        rng = np.random.default_rng()
        pattern = HWSS if rng.random() < 0.4 else LWSS
        rot = rng.integers(0, 4)
        pattern = np.rot90(pattern, rot)
        ph, pw = pattern.shape

        edge = rng.integers(0, 4)
        if edge == 0:      # top
            y, x = 2, rng.integers(10, GRID_SIZE - pw - 10)
        elif edge == 1:    # right
            y, x = rng.integers(10, GRID_SIZE - ph - 10), GRID_SIZE - pw - 2
        elif edge == 2:    # bottom
            y, x = GRID_SIZE - ph - 2, rng.integers(10, GRID_SIZE - pw - 10)
        else:              # left
            y, x = rng.integers(10, GRID_SIZE - ph - 10), 2

        mask = np.zeros((GRID_SIZE, GRID_SIZE), dtype=bool)
        y1 = min(y + ph, GRID_SIZE)
        x1 = min(x + pw, GRID_SIZE)
        mask[y:y1, x:x1] = pattern[:y1 - y, :x1 - x] > 0
        self._pending_injections.append(mask)

    def advance_ripples(self) -> list[np.ndarray]:
        """Advance all active ripples by one step. Returns injection masks."""
        masks = []
        surviving = []
        for ripple in self._ripples:
            r = ripple["radius"]
            cy, cx = ripple["center_y"], ripple["center_x"]

            if r >= ripple["max_radius"]:
                continue

            # Create ring mask
            mask = _create_ring_mask(
                GRID_SIZE, GRID_SIZE, cy, cx,
                r, RIPPLE_RING_THICKNESS,
            )
            # Sparsify
            rng = np.random.default_rng()
            sparse = mask & (rng.random((GRID_SIZE, GRID_SIZE)) < RIPPLE_DENSITY)
            if np.any(sparse):
                masks.append(sparse)

            ripple["radius"] += RIPPLE_STEP
            if ripple["radius"] < ripple["max_radius"]:
                surviving.append(ripple)

        self._ripples = surviving
        return masks

    def get_pending_injections(self) -> list[np.ndarray]:
        """Drain and return all pending cell injection masks."""
        masks = list(self._pending_injections)
        self._pending_injections.clear()
        return masks


def _create_ring_mask(
    h: int, w: int,
    cy: int, cx: int,
    radius: int, thickness: int,
) -> np.ndarray:
    """Create a boolean ring mask."""
    yy, xx = np.ogrid[:h, :w]
    dist = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    return (dist >= radius) & (dist < radius + thickness)
