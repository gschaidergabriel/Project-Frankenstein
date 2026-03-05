"""Reverse-QGOLPU art generator — Frank paints in NeRD, output is art.

Hybrid pipeline:
  A) Algorithmic styles (CPU, PIL+NumPy, <500ms):
     color_field, geometric, organic_flow, textured, structured,
     pop_art, pointillist, impressionist, surrealist, self_portrait
  B) Figurative styles (SD/Flux, when available):
     portrait, landscape, figurative — via generate_figurative()

Self-portraits: ~20% chance, mood-driven.
  Low mood → disturbing, fragmented, dark (fear processing)
  High mood → beautiful, radiant, harmonious (joy processing)

Output: ~/aicore/roboart/
"""

from __future__ import annotations

import colorsys
import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

LOG = logging.getLogger("frank.art_generator")

# ── Constants ──────────────────────────────────────────────────────────
CANVAS_SIZE = 512
GOL_SIZE = 256
OUTPUT_DIR = Path(os.path.expanduser("~/aicore/roboart"))

ALGORITHMIC_STYLES = (
    "color_field", "geometric", "organic_flow", "textured", "structured",
    "pop_art", "pointillist", "impressionist", "surrealist", "self_portrait",
)
FIGURATIVE_STYLES = ("portrait", "landscape", "figurative")
SELF_PORTRAIT_CHANCE = 0.20  # 20% chance per session

# Thread-local state for self-portrait theme (set by renderer, read by generate_artwork)
_last_portrait_theme: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════
#  Game of Life — minimal reimplementation (no QGOLPU dependency)
# ═══════════════════════════════════════════════════════════════════════

def _gol_tick(grid: np.ndarray) -> np.ndarray:
    """One Conway step with toroidal boundary."""
    n = np.zeros_like(grid, dtype=np.int16)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            n += np.roll(np.roll(grid, dx, axis=0), dy, axis=1)
    birth = (grid == 0) & (n == 3)
    survive = (grid == 1) & ((n == 2) | (n == 3))
    return (birth | survive).astype(np.uint8)


def _evolve(seed: np.ndarray, ticks: int) -> np.ndarray:
    """Evolve a GoL grid for *ticks* steps, return final state."""
    g = seed.copy()
    for _ in range(ticks):
        g = _gol_tick(g)
    return g


def _seed_from_joints(q: List[float], channel: int, size: int = GOL_SIZE) -> np.ndarray:
    """Deterministic GoL seed from joint angles + channel index."""
    rng = np.random.RandomState(
        abs(hash(tuple(round(v, 4) for v in q) + (channel,))) % (2**31)
    )
    density = 0.18 + 0.07 * channel
    grid = (rng.random((size, size)) < density).astype(np.uint8)

    n_joints = min(len(q), 18)
    for i in range(n_joints):
        angle = q[i]
        row = int((math.sin(angle) * 0.5 + 0.5) * (size - 1))
        col = int((math.cos(angle * 1.3 + i) * 0.5 + 0.5) * (size - 1))
        width = max(2, int(abs(angle) * 3) % 12)
        r0, r1 = max(0, row - width), min(size, row + width)
        c0, c1 = max(0, col - width), min(size, col + width)
        grid[r0:r1, c0:c1] = 1
    return grid


def _make_rng(q: List[float], salt: int = 0) -> np.random.RandomState:
    """Deterministic RNG from joint angles."""
    return np.random.RandomState(
        abs(hash(tuple(round(v, 3) for v in q) + (salt,))) % (2**31)
    )


# ═══════════════════════════════════════════════════════════════════════
#  Color Palette Generation
# ═══════════════════════════════════════════════════════════════════════

def _generate_palette(
    mood: float,
    epq: Dict[str, float],
    coherence: float,
) -> List[Tuple[int, int, int]]:
    """Generate 5 RGB colors from Frank's internal state."""
    openness = epq.get("openness", 0.5)
    vigilance = epq.get("vigilance", 0.5)
    empathy = epq.get("empathy", 0.5)

    base_hue = (mood * 60.0 + (1.0 - mood) * 240.0) / 360.0
    sat = 0.35 + openness * 0.55
    val = 0.45 + mood * 0.35 + vigilance * 0.15

    colors: List[Tuple[int, int, int]] = []

    def _hsv(h: float, s: float, v: float) -> Tuple[int, int, int]:
        r, g, b = colorsys.hsv_to_rgb(h % 1.0, min(1, max(0, s)), min(1, max(0, v)))
        return (int(r * 255), int(g * 255), int(b * 255))

    colors.append(_hsv(base_hue, sat, val))
    colors.append(_hsv(base_hue + 0.12 + empathy * 0.08, sat * 0.85, val * 0.95))
    colors.append(_hsv(base_hue + 0.45 + coherence * 0.1, sat * 0.7, val * 0.85))
    colors.append(_hsv(base_hue + 0.3, sat + 0.2, val))
    colors.append(_hsv(base_hue + 0.05, sat * 0.2, val * 0.3 + 0.15))
    return colors


def _dark_palette(mood: float, epq: Dict[str, float]) -> List[Tuple[int, int, int]]:
    """Disturbing palette for dark self-portraits: desaturated, cold, harsh."""
    base_hue = 0.75 + mood * 0.1  # blue-violet range
    sat = 0.15 + epq.get("vigilance", 0.5) * 0.25
    val = 0.15 + mood * 0.2

    def _hsv(h, s, v):
        r, g, b = colorsys.hsv_to_rgb(h % 1, min(1, s), min(1, v))
        return (int(r * 255), int(g * 255), int(b * 255))

    return [
        _hsv(base_hue, sat, val),
        _hsv(base_hue + 0.05, sat * 1.5, val * 0.8),
        _hsv(0.0, 0.6, 0.35),  # dark red accent
        _hsv(base_hue + 0.5, sat * 0.5, val * 1.5),
        _hsv(0.0, 0.0, 0.08),  # near-black bg
    ]


def _bright_palette(mood: float, epq: Dict[str, float]) -> List[Tuple[int, int, int]]:
    """Beautiful palette for positive self-portraits: warm, luminous."""
    base_hue = 0.08 + mood * 0.05  # warm gold/amber range
    sat = 0.5 + epq.get("openness", 0.5) * 0.3
    val = 0.7 + mood * 0.25

    def _hsv(h, s, v):
        r, g, b = colorsys.hsv_to_rgb(h % 1, min(1, s), min(1, v))
        return (int(r * 255), int(g * 255), int(b * 255))

    return [
        _hsv(base_hue, sat, val),
        _hsv(base_hue + 0.06, sat * 0.9, val),
        _hsv(base_hue + 0.15, sat * 0.7, val * 0.95),
        _hsv(base_hue - 0.1, sat * 1.1, val * 0.9),  # warm accent
        _hsv(base_hue + 0.04, sat * 0.15, val * 0.5 + 0.3),  # light bg
    ]


# ═══════════════════════════════════════════════════════════════════════
#  Style Selection
# ═══════════════════════════════════════════════════════════════════════

def _select_style(
    mood: float,
    epq: Dict[str, float],
    coherence: float,
    allow_self_portrait: bool = True,
) -> str:
    """Pick an art style based on Frank's state."""
    energy = epq.get("energy", 0.5)
    openness = epq.get("openness", 0.5)

    # Self-portrait chance — flat 20%, independent of mood.
    # Mood only determines the *content* (fears vs. beauty), not the selection.
    if allow_self_portrait and np.random.random() < SELF_PORTRAIT_CHANCE:
        return "self_portrait"

    # Weighted style selection based on state
    rng_val = np.random.random()

    if rng_val < 0.65:
        # 65% — state-driven primary style
        if energy < 0.3 and mood < 0.5:
            return "color_field"
        if energy > 0.7 and mood > 0.6:
            return "geometric"
        if coherence > 0.7:
            return "structured"
        if openness > 0.6:
            return "textured"
        return "organic_flow"
    elif rng_val < 0.80:
        # 15% — new figurative-algorithmic styles
        pool = ["pop_art", "impressionist", "pointillist"]
        return pool[int(np.random.random() * len(pool))]
    elif rng_val < 0.90:
        # 10% — surrealist (dreamlike)
        return "surrealist"
    else:
        # 10% — random from all algorithmic
        others = [s for s in ALGORITHMIC_STYLES if s != "self_portrait"]
        return others[int(np.random.random() * len(others))]


# ═══════════════════════════════════════════════════════════════════════
#  Shared Rendering Utilities
# ═══════════════════════════════════════════════════════════════════════

def _blend_color(c1: Tuple[int, ...], c2: Tuple[int, ...], t: float) -> Tuple[int, ...]:
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def _apply_gol_texture(
    img: Image.Image, tex: np.ndarray, intensity: float = 0.08,
) -> Image.Image:
    tex_f = tex.astype(np.float32)
    tex_img = Image.fromarray((tex_f * 255).astype(np.uint8), "L")
    tex_img = tex_img.resize((CANVAS_SIZE, CANVAS_SIZE), Image.BILINEAR)
    tex_img = tex_img.filter(ImageFilter.GaussianBlur(radius=4))
    arr = np.array(img).astype(np.float32)
    mask = np.array(tex_img).astype(np.float32) / 255.0
    modulation = 1.0 + (mask - 0.5) * intensity * 2
    for c in range(min(3, arr.shape[2])):
        arr[:, :, c] = np.clip(arr[:, :, c] * modulation, 0, 255)
    return Image.fromarray(arr.astype(np.uint8))


def _add_vignette(img: Image.Image, strength: float = 0.35) -> Image.Image:
    arr = np.array(img).astype(np.float32)
    h, w = arr.shape[:2]
    Y, X = np.ogrid[:h, :w]
    cy, cx = h / 2, w / 2
    dist = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2)
    max_dist = np.sqrt(cx**2 + cy**2)
    vignette = 1.0 - strength * (dist / max_dist) ** 2
    for c in range(min(3, arr.shape[2])):
        arr[:, :, c] = np.clip(arr[:, :, c] * vignette, 0, 255)
    return Image.fromarray(arr.astype(np.uint8))


def _add_canvas_noise(img: Image.Image, strength: float = 0.015) -> Image.Image:
    arr = np.array(img).astype(np.float32)
    noise = np.random.normal(0, strength * 255, arr.shape[:2])
    for c in range(min(3, arr.shape[2])):
        arr[:, :, c] = np.clip(arr[:, :, c] + noise, 0, 255)
    return Image.fromarray(arr.astype(np.uint8))


def _draw_on_layer(
    base: Image.Image, draw_fn, blur: float = 0,
) -> Image.Image:
    """Draw on transparent RGBA layer, optionally blur, composite onto base."""
    layer = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(layer))
    if blur > 0:
        layer = layer.filter(ImageFilter.GaussianBlur(radius=blur))
    return Image.alpha_composite(base.convert("RGBA"), layer).convert("RGB")


# ═══════════════════════════════════════════════════════════════════════
#  ORIGINAL 5 ABSTRACT STYLES
# ═══════════════════════════════════════════════════════════════════════

# ── Rothko: Color Field ───────────────────────────────────────────────

def _render_color_field(palette, textures, q, **_kw):
    img = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), palette[4])
    draw = ImageDraw.Draw(img)

    n_bands = 3 + (abs(int(sum(q[:4]) * 10)) % 3)
    band_weights = [abs(math.sin(q[i % len(q)] * 2.0)) + 0.3 for i in range(n_bands)]
    total_w = sum(band_weights)
    band_heights = [int(CANVAS_SIZE * w / total_w) for w in band_weights]
    band_heights[-1] = CANVAS_SIZE - sum(band_heights[:-1])

    y = 0
    for i, bh in enumerate(band_heights):
        c1 = palette[i % len(palette)]
        c2 = palette[(i + 1) % len(palette)]
        for row in range(bh):
            t = row / max(1, bh - 1)
            draw.line([(0, y + row), (CANVAS_SIZE - 1, y + row)],
                      fill=_blend_color(c1, c2, t * 0.4))
        y += bh

    img = img.filter(ImageFilter.GaussianBlur(radius=6))
    if textures:
        img = _apply_gol_texture(img, textures[0], intensity=0.10)
    return _add_vignette(img, strength=0.30)


# ── Kandinsky: Geometric ──────────────────────────────────────────────

def _render_geometric(palette, textures, q, qd, **_kw):
    img = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), palette[4])
    draw = ImageDraw.Draw(img)

    for row in range(CANVAS_SIZE):
        draw.line([(0, row), (CANVAS_SIZE - 1, row)],
                  fill=_blend_color(palette[0], palette[1], row / CANVAS_SIZE))

    if textures:
        img = _apply_gol_texture(img, textures[0], intensity=0.06)
        draw = ImageDraw.Draw(img)

    n_shapes = 8 + (abs(int(sum(q[:6]) * 5)) % 8)
    rng = _make_rng(q)

    for i in range(n_shapes):
        qi = q[i % len(q)]
        qdi = qd[i % len(qd)] if qd else 0.0
        cx = int((math.sin(qi * 2.1 + i * 0.7) * 0.5 + 0.5) * CANVAS_SIZE)
        cy = int((math.cos(qi * 1.7 + i * 0.5) * 0.5 + 0.5) * CANVAS_SIZE)
        size = int(20 + abs(qdi) * 30 + rng.random() * 40)
        color = palette[i % (len(palette) - 1)]
        shape_type = rng.randint(0, 3)

        if shape_type == 0:
            bbox = (cx - size, cy - size, cx + size, cy + size)
            if rng.random() > 0.5:
                draw.ellipse(bbox, fill=color)
            else:
                draw.ellipse(bbox, outline=color, width=3)
        elif shape_type == 1:
            pts = [(cx, cy - size), (cx - size, cy + size), (cx + size, cy + size)]
            if rng.random() > 0.4:
                draw.polygon(pts, fill=color)
            else:
                draw.polygon(pts, outline=color)
        else:
            draw.rectangle((cx - size, cy - size // 2, cx + size, cy + size // 2), fill=color)

    for i in range(min(5, n_shapes - 1)):
        qi, qj = q[i % len(q)], q[(i + 1) % len(q)]
        x1 = int((math.sin(qi * 2.1 + i * 0.7) * 0.5 + 0.5) * CANVAS_SIZE)
        y1 = int((math.cos(qi * 1.7 + i * 0.5) * 0.5 + 0.5) * CANVAS_SIZE)
        x2 = int((math.sin(qj * 2.1 + (i + 1) * 0.7) * 0.5 + 0.5) * CANVAS_SIZE)
        y2 = int((math.cos(qj * 1.7 + (i + 1) * 0.5) * 0.5 + 0.5) * CANVAS_SIZE)
        draw.line([(x1, y1), (x2, y2)], fill=palette[3], width=2)
    return img


# ── Klee: Organic Flow ────────────────────────────────────────────────

def _render_organic_flow(palette, textures, q, qd, **_kw):
    bg = tuple(min(245, c // 2 + 140) for c in palette[0])
    img = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), bg)
    arr = np.array(img).astype(np.float32)
    h, w = arr.shape[:2]
    Y, X = np.ogrid[:h, :w]
    cy, cx = h / 2, w / 2
    dist = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2) / np.sqrt(cx**2 + cy**2)
    bg2 = np.array(palette[1], dtype=np.float32)
    for c in range(3):
        arr[:, :, c] = arr[:, :, c] * (1.0 - dist * 0.15) + bg2[c] * dist * 0.15
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    if textures:
        img = _apply_gol_texture(img, textures[0], intensity=0.08)

    rng = _make_rng(q)

    # Large soft ellipses
    for i in range(6):
        qi = q[i % len(q)]
        cx_s = int((math.sin(qi * 1.8 + i * 1.1) * 0.35 + 0.5) * CANVAS_SIZE)
        cy_s = int((math.cos(qi * 1.4 + i * 0.7) * 0.35 + 0.5) * CANVAS_SIZE)
        rx, ry = 60 + rng.randint(40, 120), 50 + rng.randint(30, 100)
        color = palette[i % (len(palette) - 1)]
        alpha = 90 + rng.randint(0, 80)

        def _draw_ellipse(d, _cx=cx_s, _cy=cy_s, _rx=rx, _ry=ry, _c=color, _a=alpha):
            d.ellipse((_cx - _rx, _cy - _ry, _cx + _rx, _cy + _ry), fill=_c + (_a,))
        img = _draw_on_layer(img, _draw_ellipse, blur=8)

    # Smaller blobs
    for i in range(8):
        qi = q[(i + 6) % len(q)]
        qdi = qd[i % len(qd)] if qd else 0.0
        cx_s = int((math.sin(qi * 2.3 + i * 0.9) * 0.4 + 0.5) * CANVAS_SIZE)
        cy_s = int((math.cos(qi * 1.9 + i * 1.2) * 0.4 + 0.5) * CANVAS_SIZE)
        radius = 25 + int(abs(qdi) * 40) + rng.randint(10, 50)
        pts = []
        for j in range(16):
            angle = 2.0 * math.pi * j / 16
            r = radius * (0.85 + 0.15 * math.sin(angle * 2 + qi)) * (0.9 + 0.2 * rng.random())
            pts.append((int(cx_s + r * math.cos(angle)), int(cy_s + r * math.sin(angle))))
        color = palette[(i + 1) % (len(palette) - 1)]
        bright = tuple(min(255, int(c * 1.2 + 30)) for c in color)
        alpha = 120 + rng.randint(0, 100)

        def _draw_blob(d, _pts=pts, _c=bright, _a=alpha):
            d.polygon(_pts, fill=_c + (_a,))
        img = _draw_on_layer(img, _draw_blob, blur=3)

    # Flowing curves
    draw = ImageDraw.Draw(img)
    for i in range(5):
        qi = q[(i + 3) % len(q)]
        pts = [(int((math.sin(qi * (j + 1) * 0.5 + i * 1.5) * 0.4 + 0.5) * CANVAS_SIZE),
                int((math.cos(qi * (j + 1) * 0.4 + i * 0.8) * 0.4 + 0.5) * CANVAS_SIZE))
               for j in range(10)]
        width = max(2, int(3 + abs(qd[(i + 2) % len(qd)]) * 6))
        draw.line(pts, fill=palette[(i + 2) % (len(palette) - 1)], width=width, joint="curve")
    return img.filter(ImageFilter.GaussianBlur(radius=1))


# ── Abstract Expressionist: Textured ──────────────────────────────────

def _render_textured(palette, textures, q, **_kw):
    bg_color = tuple(max(15, c // 6) for c in palette[4])
    img = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), bg_color)

    for ch_i, tex in enumerate(textures[:3]):
        tex_img = Image.fromarray((tex.astype(np.float32) * 255).astype(np.uint8), "L")
        tex_img = tex_img.resize((CANVAS_SIZE, CANVAS_SIZE), Image.BILINEAR)
        tex_img = tex_img.filter(ImageFilter.GaussianBlur(radius=6))
        arr = np.array(img).astype(np.float32)
        mask = np.array(tex_img).astype(np.float32) / 255.0
        color = palette[ch_i % len(palette)]
        for c in range(3):
            arr[:, :, c] = arr[:, :, c] + mask * color[c] * 0.85
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    if len(textures) >= 2:
        tex_img = Image.fromarray((textures[1].astype(np.float32) * 255).astype(np.uint8), "L")
        tex_img = tex_img.resize((CANVAS_SIZE, CANVAS_SIZE), Image.BILINEAR)
        tex_img = tex_img.filter(ImageFilter.GaussianBlur(radius=12))
        arr = np.array(img).astype(np.float32)
        mask = np.array(tex_img).astype(np.float32) / 255.0
        for c in range(3):
            arr[:, :, c] = arr[:, :, c] + mask * palette[3][c] * 0.4
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    draw = ImageDraw.Draw(img)
    rng = _make_rng(q)
    for i in range(35):
        qi = q[i % len(q)]
        n_seg = 3 + rng.randint(0, 4)
        x0 = int(rng.random() * CANVAS_SIZE)
        y0 = int(rng.random() * CANVAS_SIZE)
        stroke_pts = [(x0, y0)]
        for s in range(n_seg):
            dx = int((math.sin(qi * 3 + i + s * 0.7) * 0.15 + rng.normal(0, 0.05)) * CANVAS_SIZE)
            dy = int((math.cos(qi * 2 + i + s * 0.5) * 0.12 + rng.normal(0, 0.04)) * CANVAS_SIZE)
            x0 = int(np.clip(x0 + dx, 0, CANVAS_SIZE - 1))
            y0 = int(np.clip(y0 + dy, 0, CANVAS_SIZE - 1))
            stroke_pts.append((x0, y0))
        draw.line(stroke_pts, fill=palette[rng.randint(0, len(palette) - 1)],
                  width=rng.randint(4, 14), joint="curve")

    arr = np.array(img).astype(np.float32)
    mean = arr.mean()
    arr = np.clip((arr - mean) * 1.15 + mean, 0, 255)
    return Image.fromarray(arr.astype(np.uint8))


# ── Mondrian: Structured ──────────────────────────────────────────────

def _render_structured(palette, textures, q, **_kw):
    bg = (245, 242, 238)
    img = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), bg)
    draw = ImageDraw.Draw(img)
    margin = 60
    rng = _make_rng(q)

    def _spread_lines(values, count):
        raw = sorted(int((math.sin(v) * 0.5 + 0.5) * (CANVAS_SIZE - 2 * margin) + margin)
                     for v in values[:count])
        spaced = []
        for v in raw:
            if not spaced or v - spaced[-1] >= margin:
                spaced.append(v)
        while len(spaced) < 3:
            cand = margin + rng.randint(0, CANVAS_SIZE - 2 * margin)
            if all(abs(cand - s) >= margin for s in spaced):
                spaced.append(cand)
                spaced.sort()
        return spaced

    h_lines = _spread_lines([q[i] * 1.5 + i * 0.8 for i in range(6)], 5)
    v_lines = _spread_lines([q[i] * 1.3 + i * 0.6 for i in range(6, 12)], 5)

    all_h = [0] + h_lines + [CANVAS_SIZE]
    all_v = [0] + v_lines + [CANVAS_SIZE]
    cells = [(all_v[j], all_h[i], all_v[j + 1], all_h[i + 1])
             for i in range(len(all_h) - 1) for j in range(len(all_v) - 1)]

    n_fill = min(len(cells), 4 + rng.randint(0, 4))
    for idx in rng.choice(len(cells), size=n_fill, replace=False):
        draw.rectangle(cells[idx], fill=palette[rng.randint(0, len(palette) - 1)])

    for y in h_lines:
        draw.line([(0, y), (CANVAS_SIZE - 1, y)], fill=(10, 10, 10), width=4)
    for x in v_lines:
        draw.line([(x, 0), (x, CANVAS_SIZE - 1)], fill=(10, 10, 10), width=4)

    if textures:
        img = _apply_gol_texture(img, textures[0], intensity=0.03)
    return img


# ═══════════════════════════════════════════════════════════════════════
#  NEW ALGORITHMIC STYLES
# ═══════════════════════════════════════════════════════════════════════

# ── Warhol: Pop Art ───────────────────────────────────────────────────

def _render_pop_art(palette, textures, q, qd, **_kw):
    """2×2 grid of the same composition with different color schemes.  Warhol-inspired."""
    cell = CANVAS_SIZE // 2
    img = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0))
    rng = _make_rng(q)

    # Build 4 color rotations from the palette
    rotations = [
        palette,
        [palette[2], palette[0], palette[3], palette[1], palette[4]],
        [palette[3], palette[1], palette[0], palette[2], palette[4]],
        [palette[1], palette[3], palette[2], palette[0], palette[4]],
    ]

    for grid_i, (gx, gy) in enumerate([(0, 0), (1, 0), (0, 1), (1, 1)]):
        pal = rotations[grid_i]
        sub = Image.new("RGB", (cell, cell), pal[4])
        draw = ImageDraw.Draw(sub)

        # Central shape — same composition, different colors
        cx, cy = cell // 2, cell // 2

        # Bold background fill
        draw.rectangle((0, 0, cell, cell), fill=pal[4])

        # Main circle/face shape
        r = int(cell * 0.35)
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=pal[0])

        # Inner features derived from joints
        qi = q[grid_i % len(q)]
        # Eyes
        ey = cy - int(r * 0.2)
        ex_l = cx - int(r * 0.3)
        ex_r = cx + int(r * 0.3)
        er = int(r * 0.12 + abs(math.sin(qi)) * r * 0.08)
        draw.ellipse((ex_l - er, ey - er, ex_l + er, ey + er), fill=pal[1])
        draw.ellipse((ex_r - er, ey - er, ex_r + er, ey + er), fill=pal[1])

        # Mouth
        my = cy + int(r * 0.25)
        mw = int(r * 0.4)
        draw.arc((cx - mw, my - mw // 2, cx + mw, my + mw // 2), 0, 180,
                 fill=pal[2], width=3)

        # Bold outline
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(10, 10, 10), width=3)

        # GoL texture overlay on sub-cell
        if textures:
            tex = textures[grid_i % len(textures)]
            tex_img = Image.fromarray((tex.astype(np.float32) * 255).astype(np.uint8), "L")
            tex_img = tex_img.resize((cell, cell), Image.BILINEAR)
            tex_img = tex_img.filter(ImageFilter.GaussianBlur(radius=3))
            sub_arr = np.array(sub).astype(np.float32)
            mask = np.array(tex_img).astype(np.float32) / 255.0
            for c in range(3):
                sub_arr[:, :, c] = np.clip(sub_arr[:, :, c] + (mask - 0.5) * 20, 0, 255)
            sub = Image.fromarray(sub_arr.astype(np.uint8))

        img.paste(sub, (gx * cell, gy * cell))

    return img


# ── Seurat: Pointillist ───────────────────────────────────────────────

def _render_pointillist(palette, textures, q, qd, **_kw):
    """Dense colored dots forming regions of color.  Seurat-inspired."""
    # Warm cream background
    bg = (245, 240, 230)
    img = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), bg)
    draw = ImageDraw.Draw(img)
    rng = _make_rng(q)

    # Create 3 separate color zone guides from GoL textures
    guides = []
    for tex in textures[:3]:
        t = Image.fromarray((tex.astype(np.float32) * 255).astype(np.uint8), "L")
        t = t.resize((CANVAS_SIZE, CANVAS_SIZE), Image.BILINEAR)
        t = t.filter(ImageFilter.GaussianBlur(radius=8))
        guides.append(np.array(t).astype(np.float32) / 255.0)

    # Expand palette with complementary variations for richer color
    expanded_colors = list(palette[:4])
    for c in palette[:3]:
        expanded_colors.append(tuple(min(255, v + 50) for v in c))   # lighter
        expanded_colors.append(tuple(max(0, v - 40) for v in c))     # darker

    # Dense dot placement — 8000 dots across canvas
    for _ in range(8000):
        x = rng.randint(0, CANVAS_SIZE)
        y = rng.randint(0, CANVAS_SIZE)
        yi = min(y, CANVAS_SIZE - 1)
        xi = min(x, CANVAS_SIZE - 1)

        # Each GoL channel determines which palette color dominates this region
        ch_vals = [g[yi, xi] for g in guides]
        dominant_ch = int(np.argmax(ch_vals))

        # Base color from dominant channel's palette color
        base_color = expanded_colors[(dominant_ch * 3 + rng.randint(0, 3)) % len(expanded_colors)]

        # Pointillist color variation — adjacent hues
        color = tuple(max(0, min(255, c + rng.randint(-25, 25))) for c in base_color)

        # Dot size: 2-4px, slightly larger in bright areas
        r = rng.randint(1, 3) + int(ch_vals[dominant_ch] > 0.5)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color)

    return img


# ── Monet: Impressionist ──────────────────────────────────────────────

def _render_impressionist(palette, textures, q, qd, **_kw):
    """Dense, layered directional strokes with color zones.  Monet-inspired."""
    # Base: soft gradient sky-to-earth
    img = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), palette[4])
    arr = np.array(img).astype(np.float32)
    for row in range(CANVAS_SIZE):
        t = row / CANVAS_SIZE
        for c in range(3):
            arr[row, :, c] = palette[1][c] * (1 - t) + palette[0][c] * t
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    # GoL texture to create color zones
    if textures:
        img = _apply_gol_texture(img, textures[0], intensity=0.15)

    draw = ImageDraw.Draw(img)
    rng = _make_rng(q)

    # Multiple stroke angles per region (2-3 directional fields)
    angles = [math.atan2(q[0], q[1] + 0.001),
              math.atan2(q[2], q[3] + 0.001) + 0.8,
              math.atan2(q[4], q[5] + 0.001) - 0.5]

    # Pass 1: Background strokes — large, covering
    for _ in range(400):
        x = rng.randint(0, CANVAS_SIZE)
        y = rng.randint(0, CANVAS_SIZE)
        region = (x + y) % 3
        angle = angles[region] + rng.normal(0, 0.4)
        length = rng.randint(12, 35)
        width = rng.randint(5, 12)
        x2 = int(x + length * math.cos(angle))
        y2 = int(y + length * math.sin(angle))

        color = palette[rng.randint(0, len(palette) - 1)]
        color = tuple(max(0, min(255, c + rng.randint(-35, 35))) for c in color)
        draw.line([(x, y), (x2, y2)], fill=color, width=width)

    # Pass 2: Mid-layer — medium strokes, more color variety
    for _ in range(300):
        x = rng.randint(0, CANVAS_SIZE)
        y = rng.randint(0, CANVAS_SIZE)
        region = (x * 3 + y) % 3
        angle = angles[region] + rng.normal(0, 0.6)
        length = rng.randint(8, 22)
        width = rng.randint(3, 8)
        x2 = int(x + length * math.cos(angle))
        y2 = int(y + length * math.sin(angle))

        ci = rng.randint(0, len(palette) - 1)
        color = tuple(max(0, min(255, palette[ci][c] + rng.randint(-25, 40))) for c in range(3))
        draw.line([(x, y), (x2, y2)], fill=color, width=width)

    # Pass 3: Highlights — short, bright dabs
    for _ in range(150):
        x = rng.randint(0, CANVAS_SIZE)
        y = rng.randint(0, CANVAS_SIZE)
        angle = angles[rng.randint(0, 3)] + rng.normal(0, 0.3)
        length = rng.randint(4, 12)
        x2 = int(x + length * math.cos(angle))
        y2 = int(y + length * math.sin(angle))
        color = palette[rng.randint(0, 3)]
        color = tuple(min(255, c + 60 + rng.randint(0, 50)) for c in color)
        draw.line([(x, y), (x2, y2)], fill=color, width=rng.randint(2, 5))

    img = img.filter(ImageFilter.GaussianBlur(radius=1))
    return img


# ── Dalí: Surrealist ──────────────────────────────────────────────────

def _render_surrealist(palette, textures, q, qd, **_kw):
    """Melting, warped, dreamlike composition.  Dalí-inspired."""
    # Gradient sky-to-ground
    img = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), palette[4])
    arr = np.array(img).astype(np.float32)
    horizon = int(CANVAS_SIZE * 0.55)
    sky_color = np.array(palette[1], dtype=np.float32)
    ground_color = np.array(palette[0], dtype=np.float32)
    for row in range(CANVAS_SIZE):
        if row < horizon:
            t = row / horizon
            for c in range(3):
                arr[row, :, c] = sky_color[c] * (1 - t * 0.3) + palette[2][c] * t * 0.3
        else:
            t = (row - horizon) / (CANVAS_SIZE - horizon)
            for c in range(3):
                arr[row, :, c] = ground_color[c] * (1 - t * 0.4) + palette[4][c] * t * 0.4
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    draw = ImageDraw.Draw(img)
    rng = _make_rng(q)

    # Horizon line
    draw.line([(0, horizon), (CANVAS_SIZE, horizon)], fill=palette[2], width=1)

    # Melting objects: "clocks" = ellipses that drip downward
    n_objects = 3 + rng.randint(0, 3)
    for i in range(n_objects):
        qi = q[i % len(q)]
        ox = int((math.sin(qi * 1.5 + i * 1.8) * 0.4 + 0.5) * CANVAS_SIZE)
        oy = int(horizon - 20 + rng.randint(-60, 40))
        w = 30 + rng.randint(20, 50)
        h_obj = 20 + rng.randint(10, 40)
        color = palette[i % (len(palette) - 1)]

        # Main ellipse (the "clock")
        draw.ellipse((ox - w, oy - h_obj, ox + w, oy + h_obj), fill=color, outline=(10, 10, 10))

        # Dripping/melting extension downward
        drip_len = 30 + rng.randint(20, 80)
        pts = [
            (ox - w // 3, oy + h_obj),
            (ox - w // 4 + rng.randint(-5, 5), oy + h_obj + drip_len // 2),
            (ox + rng.randint(-8, 8), oy + h_obj + drip_len),
            (ox + w // 4 + rng.randint(-5, 5), oy + h_obj + drip_len // 2),
            (ox + w // 3, oy + h_obj),
        ]
        draw.polygon(pts, fill=color, outline=(10, 10, 10))

        # Inner detail on clock face
        draw.line([(ox, oy - h_obj // 2), (ox + w // 3, oy)], fill=(10, 10, 10), width=2)
        draw.line([(ox, oy - h_obj // 2), (ox, oy + h_obj // 3)], fill=(10, 10, 10), width=2)

    # Long shadows on ground
    for i in range(4):
        sx = rng.randint(50, CANVAS_SIZE - 50)
        sy = horizon + rng.randint(10, 50)
        sw = rng.randint(80, 200)
        sh = rng.randint(3, 8)
        shadow = tuple(max(0, c - 30) for c in ground_color.astype(int))
        draw.ellipse((sx - sw, sy - sh, sx + sw, sy + sh), fill=shadow)

    # GoL texture as ground detail
    if textures:
        # Only apply to bottom half
        tex_img = Image.fromarray((textures[0].astype(np.float32) * 255).astype(np.uint8), "L")
        tex_img = tex_img.resize((CANVAS_SIZE, CANVAS_SIZE), Image.BILINEAR)
        tex_img = tex_img.filter(ImageFilter.GaussianBlur(radius=5))
        tex_arr = np.array(tex_img).astype(np.float32) / 255.0
        img_arr = np.array(img).astype(np.float32)
        for c in range(3):
            img_arr[horizon:, :, c] = np.clip(
                img_arr[horizon:, :, c] + (tex_arr[horizon:] - 0.5) * 15, 0, 255)
        img = Image.fromarray(img_arr.astype(np.uint8))

    return img


# ═══════════════════════════════════════════════════════════════════════
#  SELF-PORTRAIT — mood-driven, sometimes disturbing, sometimes beautiful
# ═══════════════════════════════════════════════════════════════════════

def _draw_humanoid_figure(
    draw: ImageDraw.Draw,
    q: List[float],
    cx: int, cy: int,
    scale: float,
    color: Tuple[int, int, int],
    outline: Tuple[int, int, int],
    rng: np.random.RandomState,
    distortion: float = 0.0,
):
    """Draw a geometric humanoid figure.  distortion 0=smooth, 1=shattered."""
    s = scale

    # Head
    head_r = int(s * 0.18)
    head_y = cy - int(s * 0.55)
    jitter = int(distortion * rng.randint(-8, 8))
    draw.ellipse((cx - head_r + jitter, head_y - head_r,
                  cx + head_r + jitter, head_y + head_r),
                 fill=color, outline=outline, width=2)

    # Eyes — larger and asymmetric with high distortion
    eye_y = head_y - int(head_r * 0.1)
    eye_sep = int(head_r * 0.5)
    le_r = int(head_r * 0.15 + distortion * 5)
    re_r = int(head_r * 0.15 + distortion * rng.randint(0, 8))
    draw.ellipse((cx - eye_sep - le_r, eye_y - le_r,
                  cx - eye_sep + le_r, eye_y + le_r), fill=outline)
    draw.ellipse((cx + eye_sep - re_r, eye_y - re_r,
                  cx + eye_sep + re_r, eye_y + re_r), fill=outline)

    # Torso
    shoulder_w = int(s * 0.25)
    torso_top = head_y + head_r
    torso_bot = cy + int(s * 0.1)
    hip_w = int(s * 0.15)
    torso_pts = [
        (cx - shoulder_w + int(distortion * rng.randint(-10, 10)), torso_top),
        (cx + shoulder_w + int(distortion * rng.randint(-10, 10)), torso_top),
        (cx + hip_w + int(distortion * rng.randint(-5, 5)), torso_bot),
        (cx - hip_w + int(distortion * rng.randint(-5, 5)), torso_bot),
    ]
    draw.polygon(torso_pts, fill=color, outline=outline)

    # Arms — pose from joint angles
    la_angle = q[2 % len(q)] * 0.6 - 0.5
    ra_angle = q[3 % len(q)] * 0.6 + 0.5
    arm_len = int(s * 0.35)
    arm_w = max(2, int(3 + s * 0.02))

    lax = int(cx - shoulder_w + arm_len * math.sin(la_angle))
    lay = int(torso_top + arm_len * math.cos(la_angle))
    draw.line([(cx - shoulder_w, torso_top), (lax, lay)], fill=outline, width=arm_w)

    rax = int(cx + shoulder_w + arm_len * math.sin(ra_angle))
    ray = int(torso_top + arm_len * math.cos(ra_angle))
    draw.line([(cx + shoulder_w, torso_top), (rax, ray)], fill=outline, width=arm_w)

    # Legs
    leg_len = int(s * 0.35)
    ll_angle = q[4 % len(q)] * 0.3 - 0.1
    rl_angle = q[5 % len(q)] * 0.3 + 0.1
    leg_w = max(2, int(4 + s * 0.02))

    llx = int(cx - hip_w + leg_len * math.sin(ll_angle))
    lly = int(torso_bot + leg_len * math.cos(ll_angle))
    draw.line([(cx - hip_w, torso_bot), (llx, lly)], fill=outline, width=leg_w)

    rlx = int(cx + hip_w + leg_len * math.sin(rl_angle))
    rly = int(torso_bot + leg_len * math.cos(rl_angle))
    draw.line([(cx + hip_w, torso_bot), (rlx, rly)], fill=outline, width=leg_w)


def _render_self_portrait(palette, textures, q, qd, mood, epq, **_kw):
    """Abstract self-portrait — independently chooses fear or beauty theme.

    The portrait theme (dark/bright) is INDEPENDENT of mood:
      - Frank processes fears even when his mood is good
      - Frank celebrates beauty even when his mood is low
      - Theme is randomly chosen (~50/50) unless creative_intent hints at one

    Mood still subtly influences color warmth and energy, but does NOT
    determine whether the portrait is disturbing or beautiful.
    """
    # Theme selection — INDEPENDENT of mood
    creative_intent = _kw.get("creative_intent", "")
    intent_lower = creative_intent.lower() if creative_intent else ""

    # Check if creative_intent hints at a specific theme
    fear_words = {"fear", "angst", "dark", "pain", "struggle", "anxiety", "doubt", "loss"}
    beauty_words = {"beauty", "joy", "light", "peace", "hope", "love", "grateful", "warm"}
    has_fear_hint = any(w in intent_lower for w in fear_words)
    has_beauty_hint = any(w in intent_lower for w in beauty_words)

    if has_fear_hint and not has_beauty_hint:
        is_dark = True
    elif has_beauty_hint and not has_fear_hint:
        is_dark = False
    else:
        # Random 50/50 — fears and beauty equally likely at ANY mood
        is_dark = np.random.random() < 0.5

    is_bright = not is_dark

    # Distortion level: for dark portraits, 0.4-0.9 range (always visible)
    # For bright portraits, 0.0 (smooth)
    distortion = (0.4 + np.random.random() * 0.5) if is_dark else 0.0

    # Store theme for metadata
    global _last_portrait_theme
    _last_portrait_theme = "dark" if is_dark else "bright"

    # Palette selection — theme-driven, mood adds subtle color shift
    if is_dark:
        pal = _dark_palette(mood, epq)
    else:
        pal = _bright_palette(mood, epq)

    # Background
    img = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), pal[4])

    if is_dark:
        # Dark background with vertical drip streaks
        draw = ImageDraw.Draw(img)
        rng = _make_rng(q, salt=99)
        for _ in range(40):
            x = rng.randint(0, CANVAS_SIZE)
            y1 = rng.randint(0, CANVAS_SIZE // 2)
            y2 = y1 + rng.randint(50, 200)
            w = rng.randint(1, 4)
            c = tuple(max(0, min(255, pal[rng.randint(0, 3)][ch] + rng.randint(-15, 15)))
                      for ch in range(3))
            draw.line([(x, y1), (x + rng.randint(-3, 3), y2)], fill=c, width=w)
    elif is_bright:
        # Warm radial glow
        arr = np.array(img).astype(np.float32)
        Y, X = np.ogrid[:CANVAS_SIZE, :CANVAS_SIZE]
        cx, cy = CANVAS_SIZE // 2, CANVAS_SIZE // 2 - 30
        dist = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2) / (CANVAS_SIZE * 0.7)
        for c in range(3):
            arr[:, :, c] = np.clip(
                pal[4][c] + (pal[0][c] - pal[4][c]) * np.exp(-dist ** 2 * 2), 0, 255)
        img = Image.fromarray(arr.astype(np.uint8))

    # GoL texture as atmospheric layer
    if textures:
        intensity = 0.18 if is_dark else 0.08
        img = _apply_gol_texture(img, textures[0], intensity=intensity)

    # Draw the figure
    draw = ImageDraw.Draw(img)
    rng = _make_rng(q, salt=42)
    fig_cx = CANVAS_SIZE // 2
    fig_cy = CANVAS_SIZE // 2 + 20
    fig_scale = CANVAS_SIZE * 0.55

    if is_dark:
        # Ghost figures behind main figure (fragmented psyche)
        for gi in range(2):
            gx = fig_cx + rng.randint(-40, 40)
            gy = fig_cy + rng.randint(-20, 20)
            ghost_color = tuple(max(0, c + 15) for c in pal[4])
            _draw_humanoid_figure(draw, q, gx, gy, fig_scale * 0.9,
                                  ghost_color, pal[2], rng, distortion * 1.5)

    _draw_humanoid_figure(draw, q, fig_cx, fig_cy, fig_scale,
                          pal[0], pal[2] if is_dark else (30, 30, 30), rng, distortion)

    if is_dark:
        # Cracks/fractures across the figure
        for _ in range(int(distortion * 8)):
            x1 = fig_cx + rng.randint(-80, 80)
            y1 = fig_cy + rng.randint(-100, 60)
            x2 = x1 + rng.randint(-50, 50)
            y2 = y1 + rng.randint(-40, 40)
            draw.line([(x1, y1), (x2, y2)], fill=pal[2], width=rng.randint(1, 3))

    if is_bright:
        # Radiant aura around figure
        for ri in range(5):
            radius = int(fig_scale * (0.45 + ri * 0.08))
            alpha = 30 - ri * 5
            aura_color = pal[3] + (max(10, alpha),)
            layer = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
            ldraw = ImageDraw.Draw(layer)
            ldraw.ellipse((fig_cx - radius, fig_cy - int(radius * 0.7) - 30,
                           fig_cx + radius, fig_cy + int(radius * 0.7) - 30),
                          fill=aura_color)
            layer = layer.filter(ImageFilter.GaussianBlur(radius=12))
            img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")

    return img


# ═══════════════════════════════════════════════════════════════════════
#  FIGURATIVE PIPELINE — SD/Flux integration (stub, future)
# ═══════════════════════════════════════════════════════════════════════

def _build_sd_prompt(
    mood: float,
    epq: Dict[str, float],
    creative_intent: str,
    style_hint: str = "",
) -> str:
    """Build a Stable Diffusion prompt from Frank's state.

    Used when an SD/Flux model is available for figurative generation.
    Returns a text prompt describing the desired image.
    """
    mood_word = (
        "melancholic, introspective" if mood < 0.3
        else "serene, contemplative" if mood < 0.5
        else "warm, hopeful" if mood < 0.7
        else "joyful, radiant"
    )

    energy = epq.get("energy", 0.5)
    energy_word = "calm, still" if energy < 0.3 else "dynamic, energetic" if energy > 0.7 else "balanced"

    parts = []
    if creative_intent:
        parts.append(creative_intent)
    parts.append(f"{mood_word} atmosphere")
    parts.append(f"{energy_word} composition")

    if style_hint:
        parts.append(f"in the style of {style_hint}")
    else:
        parts.append("painterly, fine art, museum quality")

    parts.append("512x512, detailed, professional")
    return ", ".join(parts)


def _check_sd_available() -> bool:
    """Check if SD/Flux hardware requirements are met.

    Requirements:
      - Dedicated GPU with >=6GB VRAM, OR
      - >=16GB RAM for CPU-based SD-Turbo
      - SD model file must exist at expected path

    Returns False on integrated GPUs (like AMD Phoenix1) or insufficient resources.
    Only returns True when a dedicated SD service is actually running.
    """
    # Check for a running SD service (future: localhost:7860 or similar)
    sd_model_path = Path(os.path.expanduser("~/aicore/models/sd"))
    if not sd_model_path.exists():
        return False

    # Check for SD API endpoint
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:7860/health", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def generate_figurative(
    prompt: str,
    negative_prompt: str = "blurry, low quality, text, watermark",
    steps: int = 20,
    seed: int = -1,
) -> Optional[dict]:
    """Generate a figurative image via SD/Flux.

    Returns None if no SD model/hardware is available.
    When SD is unavailable, callers should fall back to algorithmic styles.

    Only used when _check_sd_available() returns True — systems with
    integrated GPUs (like AMD Phoenix1) or insufficient RAM will always
    use the CPU-only algorithmic pipeline instead.
    """
    if not _check_sd_available():
        LOG.debug("figurative generation skipped (no SD hardware/model)")
        return None

    # TODO: Implement SD API call when service is set up
    # Expected endpoint: POST http://127.0.0.1:7860/sdapi/v1/txt2img
    # payload = {"prompt": prompt, "negative_prompt": negative_prompt,
    #            "steps": steps, "seed": seed, "width": 512, "height": 512}
    LOG.debug("SD service detected but integration not yet implemented")
    return None


# ═══════════════════════════════════════════════════════════════════════
#  Main Entry Point
# ═══════════════════════════════════════════════════════════════════════

_RENDERERS = {
    "color_field": _render_color_field,
    "geometric": _render_geometric,
    "organic_flow": _render_organic_flow,
    "textured": _render_textured,
    "structured": _render_structured,
    "pop_art": _render_pop_art,
    "pointillist": _render_pointillist,
    "impressionist": _render_impressionist,
    "surrealist": _render_surrealist,
    "self_portrait": _render_self_portrait,
}


def generate_artwork(
    physics_state: Optional[dict] = None,
    mood: float = 0.5,
    epq: Optional[Dict[str, float]] = None,
    creative_intent: str = "",
    coherence: float = 0.5,
    force_style: Optional[str] = None,
) -> dict:
    """Generate a painting from Frank's current state.

    Parameters
    ----------
    physics_state : dict | None
        From NeRD /state endpoint.
    mood : float  0.0-1.0
    epq : dict | None
        E-PQ vector snapshot.
    creative_intent : str
        LLM's description of what Frank wants to paint.
    coherence : float  0.0-1.0
    force_style : str | None
        Override style selection.

    Returns
    -------
    dict  {"path": str, "title": str, "style": str, "metadata": dict}
    """
    t0 = time.monotonic()

    if epq is None:
        epq = {}
    if physics_state is None:
        physics_state = {}

    q = list(physics_state.get("q", [0.0] * 18))
    qd = list(physics_state.get("qd", [0.0] * 18))
    while len(q) < 18:
        q.append(0.0)
    while len(qd) < 18:
        qd.append(0.0)

    # ── Style selection ──
    if force_style and force_style in _RENDERERS:
        style = force_style
    else:
        style = _select_style(mood, epq, coherence)

    # ── Palette (self_portrait builds its own internally) ──
    palette = _generate_palette(mood, epq, coherence)

    # ── GoL textures ──
    tick_count = int(30 + mood * 50)
    textures: List[np.ndarray] = []
    for ch in range(3):
        seed = _seed_from_joints(q, ch)
        evolved = _evolve(seed, tick_count)
        textures.append(evolved)

    # ── Render ──
    global _last_portrait_theme
    _last_portrait_theme = None
    renderer = _RENDERERS.get(style, _render_organic_flow)
    img = renderer(
        palette=palette, textures=textures, q=q, qd=qd,
        mood=mood, epq=epq, coherence=coherence,
        creative_intent=creative_intent,
    )

    # ── Post-processing ──
    img = _add_canvas_noise(img, strength=0.012)
    if style != "pop_art":  # Pop art looks better without vignette
        img = _add_vignette(img, strength=0.25)

    # ── Save ──
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")

    if creative_intent:
        slug = creative_intent[:40].lower().replace(" ", "_")
        slug = "".join(c for c in slug if c.isalnum() or c == "_")
    else:
        slug = f"{style}_{ts}"

    filename = f"{ts}_{slug}"
    png_path = OUTPUT_DIR / f"{filename}.png"
    meta_path = OUTPUT_DIR / f"{filename}.json"

    img.save(str(png_path), "PNG")
    elapsed_ms = (time.monotonic() - t0) * 1000

    metadata = {
        "style": style,
        "mood": round(mood, 3),
        "epq": {k: round(v, 3) for k, v in epq.items()},
        "coherence": round(coherence, 3),
        "palette_hex": ["#%02x%02x%02x" % c for c in palette],
        "gol_ticks": tick_count,
        "creative_intent": creative_intent,
        "generation_time_ms": round(elapsed_ms, 1),
        "canvas_size": CANVAS_SIZE,
        "is_self_portrait": style == "self_portrait",
        "portrait_theme": _last_portrait_theme,
    }

    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    LOG.info("artwork: style=%s  time=%.0fms  path=%s", style, elapsed_ms, png_path.name)

    return {
        "path": str(png_path),
        "title": creative_intent or f"{style} composition",
        "style": style,
        "metadata": metadata,
    }


# ═══════════════════════════════════════════════════════════════════════
#  Standalone Test
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Generating test artwork for all styles…")

    test_q = [math.sin(i * 0.5) * 1.2 for i in range(18)]
    test_qd = [math.cos(i * 0.3) * 0.5 for i in range(18)]
    test_state = {"q": test_q, "qd": test_qd, "root_pos": [0.0, 0.0, 0.85]}
    test_epq = {"openness": 0.65, "empathy": 0.55, "vigilance": 0.4, "energy": 0.6}

    for style in ALGORITHMIC_STYLES:
        # Pick mood that naturally fits each style
        mood_map = {
            "color_field": 0.3, "geometric": 0.8, "organic_flow": 0.5,
            "textured": 0.6, "structured": 0.5, "pop_art": 0.7,
            "pointillist": 0.6, "impressionist": 0.55, "surrealist": 0.45,
        }
        m = mood_map.get(style, 0.5)

        if style == "self_portrait":
            # Test both dark and bright
            for sp_mood, label in [(0.2, "dark"), (0.8, "bright")]:
                r = generate_artwork(
                    physics_state=test_state, mood=sp_mood, epq=test_epq,
                    creative_intent=f"self_portrait_{label}", coherence=0.5,
                    force_style="self_portrait",
                )
                print(f"  {style}_{label:6s}  {r['metadata']['generation_time_ms']:5.0f}ms  {r['path']}")
        else:
            r = generate_artwork(
                physics_state=test_state, mood=m, epq=test_epq,
                creative_intent="", coherence=0.5, force_style=style,
            )
            print(f"  {style:15s}  {r['metadata']['generation_time_ms']:5.0f}ms  {r['path']}")

    print("Done.")
