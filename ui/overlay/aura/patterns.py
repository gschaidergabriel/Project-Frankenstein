"""Aura — Cellular Automaton Patterns.

Predefined structures used for seeding and event animations.
These patterns follow Conway's Game of Life rules (B3/S23).
"""

import numpy as np

# ---- Still Lifes ----

BLOCK = np.array([
    [1, 1],
    [1, 1],
], dtype=np.uint8)

BEEHIVE = np.array([
    [0, 1, 1, 0],
    [1, 0, 0, 1],
    [0, 1, 1, 0],
], dtype=np.uint8)

LOAF = np.array([
    [0, 1, 1, 0],
    [1, 0, 0, 1],
    [0, 1, 0, 1],
    [0, 0, 1, 0],
], dtype=np.uint8)

# ---- Oscillators ----

BLINKER = np.array([
    [0, 1, 0],
    [0, 1, 0],
    [0, 1, 0],
], dtype=np.uint8)

TOAD = np.array([
    [0, 1, 1, 1],
    [1, 1, 1, 0],
], dtype=np.uint8)

PULSAR = np.array([
    [0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1],
    [0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0],
    [1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0],
], dtype=np.uint8)

# ---- Spaceships ----

GLIDER = np.array([
    [0, 1, 0],
    [0, 0, 1],
    [1, 1, 1],
], dtype=np.uint8)

LWSS = np.array([
    [0, 1, 0, 0, 1],
    [1, 0, 0, 0, 0],
    [1, 0, 0, 0, 1],
    [1, 1, 1, 1, 0],
], dtype=np.uint8)

HWSS = np.array([
    [0, 0, 1, 1, 0, 0, 0],
    [1, 0, 0, 0, 0, 1, 0],
    [0, 0, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 0, 1],
    [0, 1, 1, 1, 1, 1, 1],
], dtype=np.uint8)

# ---- Guns ----

GOSPER_GLIDER_GUN = np.zeros((9, 36), dtype=np.uint8)
# Left block
GOSPER_GLIDER_GUN[4, 0] = 1
GOSPER_GLIDER_GUN[5, 0] = 1
GOSPER_GLIDER_GUN[4, 1] = 1
GOSPER_GLIDER_GUN[5, 1] = 1
# Left part
GOSPER_GLIDER_GUN[4, 10] = 1
GOSPER_GLIDER_GUN[5, 10] = 1
GOSPER_GLIDER_GUN[6, 10] = 1
GOSPER_GLIDER_GUN[3, 11] = 1
GOSPER_GLIDER_GUN[7, 11] = 1
GOSPER_GLIDER_GUN[2, 12] = 1
GOSPER_GLIDER_GUN[8, 12] = 1
GOSPER_GLIDER_GUN[2, 13] = 1
GOSPER_GLIDER_GUN[8, 13] = 1
GOSPER_GLIDER_GUN[5, 14] = 1
GOSPER_GLIDER_GUN[3, 15] = 1
GOSPER_GLIDER_GUN[7, 15] = 1
GOSPER_GLIDER_GUN[4, 16] = 1
GOSPER_GLIDER_GUN[5, 16] = 1
GOSPER_GLIDER_GUN[6, 16] = 1
GOSPER_GLIDER_GUN[5, 17] = 1
# Right part
GOSPER_GLIDER_GUN[2, 20] = 1
GOSPER_GLIDER_GUN[3, 20] = 1
GOSPER_GLIDER_GUN[4, 20] = 1
GOSPER_GLIDER_GUN[2, 21] = 1
GOSPER_GLIDER_GUN[3, 21] = 1
GOSPER_GLIDER_GUN[4, 21] = 1
GOSPER_GLIDER_GUN[1, 22] = 1
GOSPER_GLIDER_GUN[5, 22] = 1
GOSPER_GLIDER_GUN[0, 24] = 1
GOSPER_GLIDER_GUN[1, 24] = 1
GOSPER_GLIDER_GUN[5, 24] = 1
GOSPER_GLIDER_GUN[6, 24] = 1
# Right block
GOSPER_GLIDER_GUN[2, 34] = 1
GOSPER_GLIDER_GUN[3, 34] = 1
GOSPER_GLIDER_GUN[2, 35] = 1
GOSPER_GLIDER_GUN[3, 35] = 1


def place_pattern(grid: np.ndarray, y: int, x: int, pattern: np.ndarray):
    """Place a pattern on the grid at (y, x), clipping to bounds."""
    ph, pw = pattern.shape
    gh, gw = grid.shape

    # Source region (clip pattern if it extends beyond grid)
    sy0 = max(0, -y)
    sx0 = max(0, -x)
    sy1 = min(ph, gh - y)
    sx1 = min(pw, gw - x)

    # Target region on grid
    gy0 = max(0, y)
    gx0 = max(0, x)
    gy1 = gy0 + (sy1 - sy0)
    gx1 = gx0 + (sx1 - sx0)

    if gy1 <= gy0 or gx1 <= gx0:
        return

    grid[gy0:gy1, gx0:gx1] |= pattern[sy0:sy1, sx0:sx1]


def select_pattern_by_length(text_len: int) -> np.ndarray:
    """Select a GoL pattern based on text length (for reflections)."""
    if text_len < 50:
        return BLOCK
    elif text_len < 200:
        return BLINKER
    else:
        return GOSPER_GLIDER_GUN


def get_glider_towards(direction: str = "center") -> np.ndarray:
    """Return a glider oriented to move in a given direction."""
    if direction == "center":
        # Default: moves down-right
        return GLIDER
    elif direction == "up":
        return np.rot90(GLIDER, 2)
    elif direction == "left":
        return np.rot90(GLIDER, 1)
    elif direction == "right":
        return np.rot90(GLIDER, 3)
    return GLIDER
