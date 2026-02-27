"""HeadlessAuraEngine — Proxy engine that streams grid data from aura-headless service.

Drop-in replacement for AuraEngine. Same interface: get_read_grid(), get_cell_age(),
generation, start(), stop(), inject_cells(), set_grid(), set_reseed_callback().

Polls http://127.0.0.1:8098/grid at 10 Hz, decodes base64 grid + quantum colors,
computes cell_age locally by frame-diffing.

Falls back gracefully: if headless unreachable, grid stays at last known state.
"""

import base64
import json
import logging
import threading
import time
import urllib.request

import numpy as np

from .config import GRID_SIZE

LOG = logging.getLogger("frank_overlay")

HEADLESS_URL = "http://127.0.0.1:8098"
POLL_INTERVAL = 0.1  # 100ms = 10 Hz to match headless tick rate
CONNECT_RETRY_S = 2.0  # Retry interval when disconnected


class HeadlessAuraEngine:
    """Streams grid + quantum state from aura-headless service."""

    def __init__(self):
        self._grids = [
            np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.uint8),
            np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.uint8),
        ]
        self._write_idx = 0
        self._read_idx = 1
        self._cell_age = np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.uint16)

        # Injection overlay (for local events like ripples)
        self._injection = np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.uint8)
        # Accumulated injection mask to push to headless
        self._pending_inject = np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.uint8)

        # Quantum: per-cell blended RGB from type superposition
        self._quantum_colors = np.zeros((GRID_SIZE, GRID_SIZE, 3), dtype=np.float32)
        self._has_quantum = False

        self._generation = 0
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        # Connection state
        self._connected = False

        # Cached metadata from headless response
        self._metadata: dict = {}
        self._metadata_lock = threading.Lock()

        # Reseed callback (unused for headless, kept for interface compat)
        self._reseed_callback = None

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def connected(self) -> bool:
        return self._connected

    def get_read_grid(self) -> np.ndarray:
        """Get current grid (safe to read from render thread)."""
        grid = self._grids[self._read_idx]
        inj = self._injection
        if inj.any():
            # TTL overlay: any value > 0 means alive
            return np.maximum(grid, (inj > 0).view(np.uint8))
        return grid

    def get_cell_age(self) -> np.ndarray:
        return self._cell_age

    def get_quantum_colors(self) -> np.ndarray | None:
        """Get per-cell quantum blended RGB (256,256,3) float32, or None."""
        if self._has_quantum:
            return self._quantum_colors
        return None

    def get_metadata(self) -> dict:
        """Get cached service metadata from last successful fetch."""
        with self._metadata_lock:
            return dict(self._metadata)

    def set_grid(self, grid: np.ndarray):
        """No-op for headless (grid managed by service)."""
        pass

    def inject_cells(self, mask: np.ndarray):
        """Inject cells into the live headless simulation + local overlay."""
        with self._lock:
            # TTL=5: overlay persists for ~5 poll cycles (~500ms)
            self._injection[mask] = 5
            # Accumulate injection for next headless push
            self._pending_inject[mask] = 1

    def _push_injections(self):
        """Push accumulated injections to headless service (called from poll thread)."""
        with self._lock:
            if not self._pending_inject.any():
                return
            inject_mask = self._pending_inject.copy()
            self._pending_inject[:] = 0

        try:
            mask_bytes = inject_mask.tobytes()
            payload = json.dumps({
                "cells_b64": base64.b64encode(mask_bytes).decode("ascii"),
            }).encode()
            req = urllib.request.Request(
                f"{HEADLESS_URL}/inject",
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=0.5)
        except Exception:
            pass  # Non-critical

    def set_reseed_callback(self, callback):
        """No-op for headless (service reseeds itself)."""
        self._reseed_callback = callback

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="headless-aura-poll",
        )
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _poll_loop(self):
        """Main loop: fetch grid from headless at ~10 Hz, push injections."""
        while self._running:
            t0 = time.monotonic()
            try:
                # Push any accumulated injections to headless first
                if self._connected:
                    self._push_injections()
                self._fetch_grid()
            except Exception as exc:
                if self._connected:
                    LOG.debug("Headless fetch error: %s", exc)
                self._connected = False

            elapsed = time.monotonic() - t0
            sleep = (CONNECT_RETRY_S if not self._connected else POLL_INTERVAL) - elapsed
            if sleep > 0:
                time.sleep(sleep)

    def _fetch_grid(self):
        """Fetch grid + quantum colors + metadata from headless /grid endpoint."""
        req = urllib.request.Request(f"{HEADLESS_URL}/grid", method="GET")
        with urllib.request.urlopen(req, timeout=0.5) as resp:
            data = json.loads(resp.read())

        grid_bytes = base64.b64decode(data["grid_b64"])
        grid = np.frombuffer(grid_bytes, dtype=np.uint8).reshape(
            GRID_SIZE, GRID_SIZE,
        ).copy()

        gen = data.get("generation", 0)

        # Decode quantum colors if present
        qcolors = None
        if "quantum_colors_b64" in data:
            try:
                qc_bytes = base64.b64decode(data["quantum_colors_b64"])
                qcolors_u8 = np.frombuffer(qc_bytes, dtype=np.uint8).reshape(
                    GRID_SIZE, GRID_SIZE, 3,
                )
                qcolors = qcolors_u8.astype(np.float32) / 255.0
            except Exception:
                pass

        with self._lock:
            prev_grid = self._grids[self._read_idx]

            # Write new grid
            self._grids[self._write_idx][:] = grid

            # Update cell age by diffing
            still_alive = (grid == 1) & (prev_grid == 1)
            new_born = (grid == 1) & (prev_grid == 0)
            self._cell_age[still_alive] += 1
            self._cell_age[new_born] = 1
            self._cell_age[grid == 0] = 0

            # Decay injection overlay with TTL:
            # Clear where headless grid already has cells (absorbed).
            # Decrement TTL elsewhere — keeps burst visible ~500ms.
            self._injection[grid == 1] = 0
            decay_mask = self._injection > 0
            self._injection[decay_mask] -= 1

            # Store quantum colors
            if qcolors is not None:
                self._quantum_colors[:] = qcolors
                self._has_quantum = True

            # Swap buffers
            self._write_idx, self._read_idx = self._read_idx, self._write_idx
            self._generation = gen

        # Cache metadata
        with self._metadata_lock:
            self._metadata = {
                "mood": data.get("mood", 0.0),
                "coherence": data.get("coherence", 0.5),
                "hw_temp": data.get("hw_temp", 0),
                "ram_usage": data.get("ram_usage", 0.0),
                "gpu_temp": data.get("gpu_temp", 0),
                "gpu_busy": data.get("gpu_busy", 0),
                "nvme_temp": data.get("nvme_temp", 0),
                "swap_percent": data.get("swap_percent", 0.0),
                "disk_percent": data.get("disk_percent", 0.0),
                "uptime_s": data.get("uptime_s", 0.0),
                "epq_vectors": data.get("epq_vectors", {}),
                "energy_level": data.get("energy_level", 0.5),
                "thought_count": data.get("thought_count", 0),
                "entity_active": data.get("entity_active", ""),
            }

        self._connected = True
