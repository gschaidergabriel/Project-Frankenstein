"""Aura Engine — Cellular Automaton Core.

Double-buffered 256×256 grid with cell age tracking.
Uses cellular automaton rules inspired by Conway's Game of Life
to drive the visual evolution of Frank's inner state.
Runs at 10 Hz in a dedicated thread.
"""

import threading
import time

import numpy as np
from scipy.signal import convolve2d

from .config import GRID_SIZE, AURA_TICK_INTERVAL, EMPTY_GRID_RESEED_S


class AuraEngine:
    """Cellular automaton engine with double-buffering and cell age tracking."""

    def __init__(self):
        self._grids = [
            np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.uint8),
            np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.uint8),
        ]
        self._write_idx = 0
        self._read_idx = 1

        # Cell age: how many generations a cell has been alive
        self._cell_age = np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.uint16)

        # Convolution kernel for neighbor counting
        self._kernel = np.array([
            [1, 1, 1],
            [1, 0, 1],
            [1, 1, 1],
        ], dtype=np.uint8)

        self._generation = 0
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        # Empty grid detection
        self._empty_since: float | None = None
        self._reseed_callback = None

    @property
    def generation(self) -> int:
        return self._generation

    def get_read_grid(self) -> np.ndarray:
        """Get the current read buffer (safe to read from render thread)."""
        return self._grids[self._read_idx]

    def get_cell_age(self) -> np.ndarray:
        """Get cell age array (read-only from render thread)."""
        return self._cell_age

    def set_grid(self, grid: np.ndarray):
        """Set the write grid directly (for seeding)."""
        with self._lock:
            self._grids[self._write_idx][:] = grid
            self._cell_age[:] = 0
            self._cell_age[grid > 0] = 1
            self._swap_buffers()
            self._generation = 0
            self._empty_since = None

    def inject_cells(self, mask: np.ndarray):
        """Inject living cells into the current grid (for events like ripple)."""
        with self._lock:
            self._grids[self._write_idx][:] = self._grids[self._read_idx]
            self._grids[self._write_idx][mask] = 1
            self._cell_age[mask & (self._grids[self._read_idx] == 0)] = 1
            self._swap_buffers()

    def set_reseed_callback(self, callback):
        """Set callback for when grid becomes empty."""
        self._reseed_callback = callback

    def start(self):
        """Start the automaton engine thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the automaton engine thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _tick_loop(self):
        """Main engine loop — ticks at AURA_TICK_INTERVAL."""
        while self._running:
            t0 = time.monotonic()
            self._step()
            elapsed = time.monotonic() - t0
            sleep_time = AURA_TICK_INTERVAL - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _step(self):
        """Compute one automaton generation (Conway's Game of Life rules)."""
        with self._lock:
            current = self._grids[self._read_idx]
            next_grid = self._grids[self._write_idx]

            # Count neighbors via convolution (wrapping boundary)
            neighbors = convolve2d(current, self._kernel, mode='same', boundary='wrap')

            # Birth/survival rules (B3/S23):
            birth = (current == 0) & (neighbors == 3)
            survive = (current == 1) & ((neighbors == 2) | (neighbors == 3))
            next_grid[:] = 0
            next_grid[birth | survive] = 1

            # Update cell age
            self._cell_age[next_grid == 1] += 1
            self._cell_age[next_grid == 0] = 0

            self._swap_buffers()
            self._generation += 1

            # Check for empty grid
            if np.sum(self._grids[self._read_idx]) == 0:
                if self._empty_since is None:
                    self._empty_since = time.monotonic()
                elif (time.monotonic() - self._empty_since) > EMPTY_GRID_RESEED_S:
                    if self._reseed_callback:
                        self._reseed_callback()
                    self._empty_since = None
            else:
                self._empty_since = None

    def _swap_buffers(self):
        """Swap read/write buffer indices."""
        self._write_idx, self._read_idx = self._read_idx, self._write_idx
