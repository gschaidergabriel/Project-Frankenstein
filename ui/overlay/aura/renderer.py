"""Aura — Pseudo-3D Grid Renderer.

Layered rendering pipeline that fakes volumetric depth:
  1. Base noise   — dark static texture ("the void")
  2. Cells+Trails — living cells + fading afterglow from dead cells
  3. Bloom/Glow   — downscaled gaussian blur, upscaled, additive blend

All heavy work is NumPy array ops — zero Python pixel loops.
"""

import math
import time

import numpy as np
from PIL import Image

try:
    from scipy.ndimage import gaussian_filter, zoom
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False

from .config import (
    GRID_SIZE, ZONE_WIDTH, ZONE_HEIGHT, ZONE_COLORS, ZONE_LAYOUT,
    BRIGHTNESS_DECAY, BRIGHTNESS_MIN,
    TRANSITION_WIDTH,
    GLOW_DOWNSAMPLE, GLOW_SIGMA, GLOW_INTENSITY,
    TRAIL_DECAY, BASE_NOISE_DENSITY,
    BREATH_PERIOD_S, BREATH_AMPLITUDE,
    NEWBORN_FLASH,
)


# ──────────────────────────────────────────────────────────────
# Zone color map (built once per process)
# ──────────────────────────────────────────────────────────────

def _build_zone_color_map() -> np.ndarray:
    """Pre-compute per-cell zone base color (GRID_SIZE×GRID_SIZE×3), float 0-1."""
    color_map = np.zeros((GRID_SIZE, GRID_SIZE, 3), dtype=np.float32)

    for zone_name, (row, col) in ZONE_LAYOUT.items():
        y0 = row * ZONE_HEIGHT
        x0 = col * ZONE_WIDTH
        r, g, b = ZONE_COLORS[zone_name]
        color_map[y0:y0 + ZONE_HEIGHT, x0:x0 + ZONE_WIDTH] = [r, g, b]

    tw = TRANSITION_WIDTH
    # Horizontal boundaries (between columns)
    for col in range(1, 4):
        x = col * ZONE_WIDTH
        for dx in range(-tw, tw):
            xi = x + dx
            if 0 <= xi < GRID_SIZE:
                alpha = (dx + tw) / (2 * tw)
                left_x = max(0, x - tw - 1)
                right_x = min(GRID_SIZE - 1, x + tw)
                color_map[:, xi] = (
                    (1 - alpha) * color_map[:, left_x]
                    + alpha * color_map[:, right_x]
                )
    # Vertical boundary (between rows)
    y = ZONE_HEIGHT
    for dy in range(-tw, tw):
        yi = y + dy
        if 0 <= yi < GRID_SIZE:
            alpha = (dy + tw) / (2 * tw)
            top_y = max(0, y - tw - 1)
            bot_y = min(GRID_SIZE - 1, y + tw)
            color_map[yi, :] = (
                (1 - alpha) * color_map[top_y, :]
                + alpha * color_map[bot_y, :]
            )

    return color_map


_ZONE_COLOR_MAP: np.ndarray | None = None


def _get_zone_color_map() -> np.ndarray:
    global _ZONE_COLOR_MAP
    if _ZONE_COLOR_MAP is None:
        _ZONE_COLOR_MAP = _build_zone_color_map()
    return _ZONE_COLOR_MAP


# ──────────────────────────────────────────────────────────────
# AuraRenderer — stateful per-session renderer
# ──────────────────────────────────────────────────────────────

class AuraRenderer:
    """Pseudo-3D renderer with trails, bloom, breathing, and base noise."""

    def __init__(self):
        self._zone_colors = _get_zone_color_map()
        self._visual_decay = np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.float32)
        self._base_noise = self._generate_base_noise()
        self._highlight_zone: str | None = None  # For legend hover highlight
        self._t0 = time.monotonic()

    def _generate_base_noise(self) -> np.ndarray:
        """Static background noise — dark, organic texture."""
        rng = np.random.default_rng(42)
        noise = np.zeros((GRID_SIZE, GRID_SIZE, 3), dtype=np.float32)
        mask = rng.random((GRID_SIZE, GRID_SIZE)) < BASE_NOISE_DENSITY
        # Tint noise pixels with faint zone colors
        noise[mask] = self._zone_colors[mask] * 0.06 + rng.random((int(np.sum(mask)), 3)).astype(np.float32) * 0.03
        if _HAS_SCIPY:
            noise = gaussian_filter(noise, sigma=(1.5, 1.5, 0))
        return noise

    def render(
        self,
        grid: np.ndarray,
        cell_age: np.ndarray,
        mood_buffer: float = 0.5,
        threat_intensity: float = 0.0,
        quantum_colors: np.ndarray | None = None,
        density_map: np.ndarray | None = None,
    ) -> Image.Image:
        """Full render pass: noise → cells+trails → bloom → output.

        quantum_colors: optional (256,256,3) float32 per-cell RGB from quantum
                        type distribution. If provided, overrides static zone colors.
        density_map: optional (256,256) float32 stochastic density (0.0-1.0).
                     When provided, enables organic continuous-brightness rendering
                     instead of binary alive/dead.
        """

        # ── Update visual decay (trails) ──
        self._visual_decay *= TRAIL_DECAY
        self._visual_decay[grid > 0] = 1.0

        # ── Breath animation ──
        elapsed = time.monotonic() - self._t0
        breath = 1.0 + BREATH_AMPLITUDE * math.sin(
            2.0 * math.pi * elapsed / BREATH_PERIOD_S,
        )

        # ── Layer 1: Base noise (dark background) ──
        img = self._base_noise.copy()

        # Color source
        color_source = quantum_colors if quantum_colors is not None else self._zone_colors

        # ── Layer 2a: Organic ambient glow from density (subtle, underneath) ──
        if density_map is not None:
            # Only glow where density exists but cell is NOT alive (the halos)
            halo_mask = (density_map > 0.01) & (grid == 0) & (self._visual_decay < 0.05)
            if np.any(halo_mask):
                d_halo = density_map[halo_mask]
                halo_colors = color_source[halo_mask]
                # Subtle ambient glow — dim enough to not overpower sharp cells
                halo_bright = np.clip(d_halo * 0.5, 0.0, 0.15) * breath
                img[halo_mask] += halo_colors * halo_bright[:, np.newaxis]

        # ── Layer 2b: Sharp cells + trails (original rendering, always) ──
        visible = self._visual_decay > 0.01
        if np.any(visible):
            decay = self._visual_decay[visible]
            colors = color_source[visible]

            # Mood → saturation
            sat = 0.4 + max(0.0, min(1.0, mood_buffer)) * 0.6
            gray = np.mean(colors, axis=1, keepdims=True)
            colors = gray + (colors - gray) * sat

            # Age-based brightness
            alive = grid[visible] > 0
            ages = cell_age[visible].astype(np.float32)
            brightness = np.clip(
                1.0 - ages * BRIGHTNESS_DECAY, BRIGHTNESS_MIN, 1.0,
            )
            # Newborn flash
            brightness[ages == 1] = NEWBORN_FLASH

            # Alive cells: full brightness · trails: dim decay
            intensity = np.where(alive, brightness, decay * 0.35) * breath

            # Additive blend
            img[visible] += colors * intensity[:, np.newaxis]

        # ── Threat overlay ──
        if threat_intensity > 0.01:
            t = min(1.0, threat_intensity)
            threat_tint = np.array([0.6, 0.02, 0.02], dtype=np.float32)
            img = img * (1.0 - t * 0.4) + threat_tint * (t * 0.4)

        # ── Zone highlight (legend hover) ──
        if self._highlight_zone and self._highlight_zone in ZONE_LAYOUT:
            row, col = ZONE_LAYOUT[self._highlight_zone]
            y0 = row * ZONE_HEIGHT
            x0 = col * ZONE_WIDTH
            img[y0:y0 + ZONE_HEIGHT, x0:x0 + ZONE_WIDTH] *= 1.2

        # ── Layer 3: Downscaled bloom (glow) ──
        if _HAS_SCIPY:
            ds = GLOW_DOWNSAMPLE
            small = img[::ds, ::ds, :].copy()  # (64, 64, 3)
            small = gaussian_filter(small, sigma=(GLOW_SIGMA, GLOW_SIGMA, 0))
            glow = zoom(small, (float(ds), float(ds), 1.0), order=1)
            # Safety crop (zoom may produce ±1 pixel off)
            gy = min(glow.shape[0], GRID_SIZE)
            gx = min(glow.shape[1], GRID_SIZE)
            img[:gy, :gx] += glow[:gy, :gx, :3] * GLOW_INTENSITY

        # ── Final clamp & convert ──
        np.clip(img, 0.0, 1.0, out=img)
        return Image.fromarray((img * 255).astype(np.uint8), mode="RGB")


# ──────────────────────────────────────────────────────────────
# Backward-compatible function API
# ──────────────────────────────────────────────────────────────

_DEFAULT_RENDERER: AuraRenderer | None = None


def render_grid(
    grid: np.ndarray,
    cell_age: np.ndarray,
    mood_buffer: float = 0.5,
    threat_intensity: float = 0.0,
) -> Image.Image:
    """Legacy wrapper — uses module-level singleton."""
    global _DEFAULT_RENDERER
    if _DEFAULT_RENDERER is None:
        _DEFAULT_RENDERER = AuraRenderer()
    return _DEFAULT_RENDERER.render(grid, cell_age, mood_buffer, threat_intensity)
