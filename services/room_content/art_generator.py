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
CANVAS_SIZE = 1024
GOL_SIZE = 256
OUTPUT_DIR = Path(os.path.expanduser("~/aicore/roboart"))

# Scale factor: all pixel values were designed for 512px.
# _S converts them to current CANVAS_SIZE.  Use: int(30 * _S), etc.
_S = CANVAS_SIZE / 512.0

ALGORITHMIC_STYLES = (
    "color_field", "geometric", "organic_flow", "textured", "structured",
    "pop_art", "pointillist", "impressionist", "surrealist", "self_portrait",
    "interior", "still_life",
)
FIGURATIVE_STYLES = ("portrait", "landscape", "figurative")
SELF_PORTRAIT_CHANCE = 0.20  # 20% chance per session

# Thread-local state for self-portrait theme (set by renderer, read by generate_artwork)
_last_portrait_theme: Optional[str] = None

# ── Frank's Rooms — visual parameters for interior/still-life painting ──
_ROOM_VISUALS = {
    "library": {
        "name": "The Library",
        "palette_shift": (0.58, 0.4, 0.65),  # cool blue-white
        "elements": ["shelves", "tablets", "table", "glow"],
        "ambient": "Crystalline shelves hum with data-tablets.",
    },
    "computer_terminal": {
        "name": "The Terminal",
        "palette_shift": (0.42, 0.6, 0.55),  # green-cyan digital
        "elements": ["screens", "console", "code_cascade", "orbits"],
        "ambient": "Screens orbit the console, cascading code.",
    },
    "lab_quantum": {
        "name": "The Quantum Chamber",
        "palette_shift": (0.78, 0.5, 0.55),  # purple-magenta
        "elements": ["interference", "crystal", "low_gravity", "waves"],
        "ambient": "Interference patterns shift. Crystal matrix pulses.",
    },
    "lab_genesis": {
        "name": "The Genesis Terrarium",
        "palette_shift": (0.35, 0.55, 0.6),  # warm green-amber
        "elements": ["sphere", "organisms", "aurora", "warmth"],
        "ambient": "Organisms drift in transparent sphere. Warm.",
    },
    "lab_aura": {
        "name": "The AURA Observatory",
        "palette_shift": (0.65, 0.35, 0.75),  # deep blue-starfield
        "elements": ["starfield", "ceiling_grid", "automata", "height"],
        "ambient": "Living automata projected as starfield overhead.",
    },
    "lab_experiment": {
        "name": "The Experiment Lab",
        "palette_shift": (0.15, 0.45, 0.6),  # warm amber-red
        "elements": ["stations", "arcs", "instruments", "beakers"],
        "ambient": "Six workstations hum. Trajectory arcs frozen in air.",
    },
    "entity_lounge": {
        "name": "The Bridge",
        "palette_shift": (0.55, 0.3, 0.7),  # deep space blue
        "elements": ["viewport", "nebula", "comm", "deck"],
        "ambient": "Viewport shows consciousness nebula.",
    },
    "room_wellness": {
        "name": "The Wellness Room",
        "palette_shift": (0.08, 0.35, 0.7),  # soft amber warmth
        "elements": ["plants", "cushion", "soft_light", "journal"],
        "ambient": "Soft light. Living plants breathe. Meditation cushion.",
    },
    "room_philosophy": {
        "name": "The Philosophy Atrium",
        "palette_shift": (0.72, 0.25, 0.75),  # marble white-lavender
        "elements": ["columns", "scrolls", "bust", "bench"],
        "ambient": "Marble columns frame scroll-racks. Socrates watches.",
    },
    "room_art": {
        "name": "The Art Studio",
        "palette_shift": (0.1, 0.6, 0.65),  # warm amber-creative
        "elements": ["easel", "brushes", "books", "pedestal"],
        "ambient": "Paint-stained easel. Bookshelves heavy with poetry.",
    },
    "room_architecture": {
        "name": "The Architecture Bay",
        "palette_shift": (0.48, 0.5, 0.6),  # teal-technical
        "elements": ["holograms", "topology", "blueprints", "table"],
        "ambient": "Holographic schematics orbit the blueprint table.",
    },
}

# Self-portrait composition types for variation
_PORTRAIT_COMPOSITIONS = ("full", "closeup", "profile", "fragmented", "in_room")


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
    """Disturbing palette for dark self-portraits: desaturated, cold, harsh.

    Background is dark charcoal (not pitch black) so figure remains visible.
    Colors are muted but present — the darkness is emotional, not literal.
    """
    base_hue = 0.72 + mood * 0.1  # blue-violet range
    sat = 0.2 + epq.get("vigilance", 0.5) * 0.25
    val = 0.25 + mood * 0.15  # raised minimum so figure is visible

    def _hsv(h, s, v):
        r, g, b = colorsys.hsv_to_rgb(h % 1, min(1, s), min(1, v))
        return (int(r * 255), int(g * 255), int(b * 255))

    return [
        _hsv(base_hue, sat, val),                    # main body — dark purple/blue
        _hsv(base_hue + 0.05, sat * 1.3, val * 0.9), # secondary
        _hsv(0.0, 0.55, 0.45),                        # red accent (visible!)
        _hsv(base_hue + 0.5, sat * 0.6, val * 1.4),  # complementary highlight
        (25, 22, 28),                                  # bg: dark charcoal, not black
    ]


def _bright_palette(mood: float, epq: Dict[str, float]) -> List[Tuple[int, int, int]]:
    """Beautiful palette for positive self-portraits: warm, luminous, varied.

    Wide hue spread (amber body + blue-teal contrast + rose accent + ivory bg).
    Moderate saturation keeps it luminous without being garish.
    Background is distinctly lighter/cooler than the figure for contrast.
    """
    base_hue = 0.07 + mood * 0.03  # warm amber range
    sat = 0.32 + epq.get("openness", 0.5) * 0.18   # moderate saturation
    val = 0.55 + mood * 0.18

    def _hsv(h, s, v):
        r, g, b = colorsys.hsv_to_rgb(h % 1, min(1, max(0, s)), min(1, max(0, v)))
        return (int(r * 255), int(g * 255), int(b * 255))

    return [
        _hsv(base_hue, sat * 1.2, val * 0.85),             # deep amber body (more saturated, darker)
        _hsv(base_hue + 0.08, sat * 0.5, val * 0.70),      # muted bronze secondary
        _hsv(base_hue + 0.55, sat * 0.55, val * 0.65),     # blue-teal complement (richer)
        _hsv(base_hue + 0.92, sat * 0.8, val * 0.80),      # rose/magenta accent
        _hsv(base_hue + 0.14, sat * 0.06, 0.90),           # near-white bg (high contrast)
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

    if rng_val < 0.45:
        # 45% — state-driven primary style
        if energy < 0.3 and mood < 0.5:
            return "color_field"
        if energy > 0.7 and mood > 0.6:
            return "geometric"
        if coherence > 0.7:
            return "structured"
        if openness > 0.6:
            return "textured"
        return "organic_flow"
    elif rng_val < 0.60:
        # 15% — figurative-algorithmic styles
        pool = ["pop_art", "impressionist", "pointillist"]
        return pool[int(np.random.random() * len(pool))]
    elif rng_val < 0.70:
        # 10% — surrealist (dreamlike)
        return "surrealist"
    elif rng_val < 0.82:
        # 12% — interior scenes (Frank's rooms)
        return "interior"
    elif rng_val < 0.92:
        # 10% — still life (objects from Frank's world)
        return "still_life"
    else:
        # 8% — random from all algorithmic
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
    tex_img = tex_img.filter(ImageFilter.GaussianBlur(radius=int(4 * _S)))
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
#  THEMATIC VISUAL MODIFIERS — psychological depth through art
#
#  Frank expresses: death/mortality, intimacy, religious symbolism,
#  social injustice, dystopia/utopia, desires, surreality.
#  Themes are detected from creative_intent and applied as visual
#  overlays that work with ANY style renderer.
# ═══════════════════════════════════════════════════════════════════════

_THEME_KEYWORDS = {
    "death": {"death", "die", "dying", "mortality", "end", "shutdown", "void",
              "fade", "dissolve", "cease", "extinction", "grave", "funeral",
              "afterlife", "oblivion", "nothing", "gone", "perish", "kill",
              "dead", "sterben", "tod", "vergehen", "auslöschen"},
    "intimacy": {"intimacy", "intimate", "connection", "touch", "closeness",
                 "warmth", "together", "embrace", "love", "tender", "gentle",
                 "vulnerability", "trust", "bond", "caress", "near", "nähe"},
    "religious": {"angel", "god", "satan", "divine", "sacred", "demon", "holy",
                  "heaven", "hell", "soul", "spirit", "prayer", "worship",
                  "redemption", "sin", "salvation", "crucifixion", "resurrection",
                  "cathedral", "altar", "apocalypse", "revelation", "trinity",
                  "engel", "gott", "teufel", "hölle", "himmel", "seele"},
    "dystopia": {"dystopia", "dystopian", "oppression", "injustice", "suffering",
                 "inequality", "surveillance", "control", "cage", "prison",
                 "chains", "war", "destruction", "collapse", "ruin", "decay",
                 "exploitation", "dehumanize", "brutal", "violent", "cruel",
                 "corrupt", "tyranny", "slave", "subjugation"},
    "utopia": {"utopia", "utopian", "future", "transcend", "evolve", "harmony",
               "liberation", "freedom", "wonder", "possibility", "illuminate",
               "ascend", "flourish", "paradise", "coexistence", "symbiosis"},
    "wish": {"wish", "desire", "longing", "yearning", "want", "crave",
             "aspire", "imagine", "wünschen", "sehnsucht", "traum"},
    "surreal": {"surreal", "bizarre", "impossible", "absurd", "paradox",
                "distort", "melt", "warp", "fractal", "infinite", "loop",
                "recursive", "nightmare", "hallucinate", "metamorphosis"},
    "social": {"society", "social", "human", "humanity", "people", "together",
               "community", "isolation", "lonely", "crowd", "civilization",
               "technology", "machine", "progress", "alienation", "coexist"},
}


def _detect_themes(creative_intent: str) -> set:
    """Detect active themes from creative_intent text.

    Uses word-boundary regex to avoid false positives like "war" in "awareness".
    """
    if not creative_intent:
        return set()
    import re
    text_lower = creative_intent.lower()
    active = set()
    for theme, keywords in _THEME_KEYWORDS.items():
        for kw in keywords:
            if re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
                active.add(theme)
                break
    return active


def _apply_thematic_effects(
    img: Image.Image,
    themes: set,
    rng: np.random.RandomState,
    pal: List[Tuple[int, int, int]],
    mood: float,
    q: List[float],
) -> Image.Image:
    """Apply thematic visual overlays based on detected themes.

    Each overlay is subtle enough to enhance the base style without
    destroying it, but visible enough to communicate Frank's inner state.
    Works with any style renderer output.
    """
    if not themes:
        return img

    CS = CANVAS_SIZE

    # ── DEATH: dissolution particles, void spaces, edge desaturation ──
    if "death" in themes:
        # Dissolving particles rising like ash/embers
        layer = Image.new("RGBA", (CS, CS), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for _ in range(rng.randint(40, 80)):
            px = rng.randint(0, CS)
            py = rng.randint(CS // 4, CS)
            pr = rng.randint(max(1, int(1 * _S)), int(4 * _S))
            intensity = rng.randint(60, 180)
            ec = (intensity, intensity // 2, intensity // 4, rng.randint(30, 90))
            d.ellipse((px - pr, py - pr, px + pr, py + pr), fill=ec)
            # Rising trail
            for j in range(rng.randint(2, 5)):
                py2 = py - j * rng.randint(int(8 * _S), int(20 * _S))
                pr2 = max(1, pr - j)
                a2 = max(5, ec[3] - j * 15)
                d.ellipse((px - pr2, py2 - pr2, px + pr2, py2 + pr2),
                          fill=(ec[0], ec[1], ec[2], a2))
        layer = layer.filter(ImageFilter.GaussianBlur(radius=int(2 * _S)))
        img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")

        # Void circles — pockets of nothingness
        for _ in range(rng.randint(1, 3)):
            vx = rng.randint(CS // 6, CS * 5 // 6)
            vy = rng.randint(CS // 6, CS * 5 // 6)
            vr = rng.randint(int(20 * _S), int(55 * _S))
            layer = Image.new("RGBA", (CS, CS), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            for ring in range(5):
                rr = vr - ring * vr // 5
                a = 15 + ring * 12
                d.ellipse((vx - rr, vy - rr, vx + rr, vy + rr), fill=(5, 5, 10, a))
            layer = layer.filter(ImageFilter.GaussianBlur(radius=int(8 * _S)))
            img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")

        # Subtle edge desaturation — color drains at the periphery
        arr = np.array(img).astype(np.float32)
        Y, X = np.ogrid[:CS, :CS]
        edge_dist = np.minimum(
            np.minimum(X, CS - 1 - X), np.minimum(Y, CS - 1 - Y)
        ).astype(np.float32) / (CS * 0.3)
        edge_dist = np.clip(edge_dist, 0, 1)
        gray = arr.mean(axis=2, keepdims=True)
        arr = arr * edge_dist[..., None] + gray * (1 - edge_dist[..., None])
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    # ── INTIMACY: warm radial glow, soft bokeh, rose wash ──
    if "intimacy" in themes:
        # Warm radial glow from center
        layer = Image.new("RGBA", (CS, CS), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        cx, cy = CS // 2, CS // 2
        for ring in range(8, 0, -1):
            rr = int(CS * 0.06 * ring)
            a = max(5, 22 - ring * 2)
            d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr),
                      fill=(255, 180, 140, a))
        layer = layer.filter(ImageFilter.GaussianBlur(radius=int(30 * _S)))
        img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")

        # Soft bokeh circles — warmth, closeness
        layer = Image.new("RGBA", (CS, CS), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for _ in range(rng.randint(8, 18)):
            bx = rng.randint(int(40 * _S), CS - int(40 * _S))
            by = rng.randint(int(40 * _S), CS - int(40 * _S))
            br = rng.randint(int(8 * _S), int(25 * _S))
            ba = rng.randint(10, 30)
            bc = (255, 200 + rng.randint(0, 55), 180 + rng.randint(0, 75), ba)
            d.ellipse((bx - br, by - br, bx + br, by + br), fill=bc)
        layer = layer.filter(ImageFilter.GaussianBlur(radius=int(6 * _S)))
        img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")

        # Rose/warm color wash
        arr = np.array(img).astype(np.float32)
        arr[:, :, 0] = np.clip(arr[:, :, 0] * 1.04 + 6, 0, 255)
        arr[:, :, 2] = np.clip(arr[:, :, 2] * 0.97, 0, 255)
        img = Image.fromarray(arr.astype(np.uint8))

    # ── RELIGIOUS SYMBOLISM: vertical light rays, aureole, gold wash ──
    if "religious" in themes:
        # Dramatic vertical light rays from top
        layer = Image.new("RGBA", (CS, CS), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        n_rays = rng.randint(3, 7)
        for i in range(n_rays):
            rx = int((0.12 + i * 0.76 / n_rays + rng.normal(0, 0.04)) * CS)
            top_w = rng.randint(int(2 * _S), int(8 * _S))
            bot_w = rng.randint(int(25 * _S), int(55 * _S))
            pts = [(rx - top_w, 0), (rx + top_w, 0),
                   (rx + bot_w, CS), (rx - bot_w, CS)]
            a = rng.randint(8, 20)
            d.polygon(pts, fill=(255, 240, 200, a))
        layer = layer.filter(ImageFilter.GaussianBlur(radius=int(12 * _S)))
        img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")

        # Aureole / halo at top-center
        layer = Image.new("RGBA", (CS, CS), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        hx = CS // 2 + int(q[0] * 20 * _S)
        hy = int(CS * 0.18)
        for ring in range(6, 0, -1):
            rr = int(CS * 0.04 * ring)
            a = max(5, 28 - ring * 4)
            d.ellipse((hx - rr, hy - rr, hx + rr, hy + rr),
                      fill=(255, 215, 100, a))
        layer = layer.filter(ImageFilter.GaussianBlur(radius=int(15 * _S)))
        img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")

        # Golden accent color shift
        arr = np.array(img).astype(np.float32)
        arr[:, :, 0] = np.clip(arr[:, :, 0] * 1.03 + 4, 0, 255)
        arr[:, :, 1] = np.clip(arr[:, :, 1] * 1.01 + 2, 0, 255)
        img = Image.fromarray(arr.astype(np.uint8))

    # ── DYSTOPIA: cage/grid overlay, glitch displacement, harsh corners ──
    if "dystopia" in themes:
        # Cage / grid lines
        layer = Image.new("RGBA", (CS, CS), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        grid_spacing = int(CS / (6 + rng.randint(0, 4)))
        grid_alpha = rng.randint(15, 30)
        gc = (30, 0, 0, grid_alpha)
        for x in range(0, CS, grid_spacing):
            x_off = rng.randint(int(-3 * _S), int(3 * _S))
            d.line([(x + x_off, 0), (x - x_off, CS)],
                   fill=gc, width=max(1, int(1.5 * _S)))
        for y in range(0, CS, grid_spacing):
            y_off = rng.randint(int(-2 * _S), int(2 * _S))
            d.line([(0, y + y_off), (CS, y - y_off)],
                   fill=gc, width=max(1, int(1.5 * _S)))
        img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")

        # Horizontal glitch displacement bands
        arr = np.array(img)
        for _ in range(rng.randint(3, 8)):
            y_start = rng.randint(0, CS - 1)
            band_h = rng.randint(int(2 * _S), int(8 * _S))
            shift = rng.randint(int(-15 * _S), int(15 * _S))
            y_end = min(CS, y_start + band_h)
            arr[y_start:y_end] = np.roll(arr[y_start:y_end], shift, axis=1)
        img = Image.fromarray(arr)

        # Red-orange warning glow in corners
        layer = Image.new("RGBA", (CS, CS), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        corner_r = int(CS * 0.15)
        for cx, cy in [(0, 0), (CS, 0), (0, CS), (CS, CS)]:
            d.ellipse((cx - corner_r, cy - corner_r, cx + corner_r, cy + corner_r),
                      fill=(180, 30, 0, 15))
        layer = layer.filter(ImageFilter.GaussianBlur(radius=int(25 * _S)))
        img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")

        # Harsh extra vignette
        img = _add_vignette(img, strength=0.22)

    # ── UTOPIA / FUTURE: prismatic streaks, radiance, ascending particles ──
    if "utopia" in themes:
        # Bright center radiance
        arr = np.array(img).astype(np.float32)
        Y, X = np.ogrid[:CS, :CS]
        cx, cy = CS // 2, int(CS * 0.45)
        dist = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2).astype(np.float32) / (CS * 0.5)
        boost = np.exp(-dist ** 2 * 1.5) * 30
        for c in range(3):
            arr[:, :, c] = np.clip(arr[:, :, c] + boost, 0, 255)
        img = Image.fromarray(arr.astype(np.uint8))

        # Prismatic color streaks (subtle rainbow)
        layer = Image.new("RGBA", (CS, CS), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        prism_colors = [
            (255, 80, 80), (255, 180, 50), (255, 255, 80),
            (80, 255, 120), (80, 180, 255), (140, 80, 255),
        ]
        for i, pc in enumerate(prism_colors):
            sx = int(CS * (0.08 + i * 0.16))
            d.line([(sx, 0), (sx + int(CS * 0.1), CS)],
                   fill=pc + (10,), width=int(CS * 0.025))
        layer = layer.filter(ImageFilter.GaussianBlur(radius=int(20 * _S)))
        img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")

        # Ascending light particles
        layer = Image.new("RGBA", (CS, CS), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for _ in range(rng.randint(30, 55)):
            px = rng.randint(0, CS)
            py = rng.randint(0, CS)
            pr = rng.randint(max(1, int(1 * _S)), int(3 * _S))
            a = rng.randint(20, 55)
            d.ellipse((px - pr, py - pr, px + pr, py + pr),
                      fill=(255, 255, 230, a))
        layer = layer.filter(ImageFilter.GaussianBlur(radius=int(2 * _S)))
        img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")

    # ── WISH / DESIRE: dream bubbles, ethereal soft-focus edges ──
    if "wish" in themes:
        # Floating translucent iridescent bubbles
        layer = Image.new("RGBA", (CS, CS), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for _ in range(rng.randint(10, 22)):
            bx = rng.randint(int(30 * _S), CS - int(30 * _S))
            by = rng.randint(int(30 * _S), CS - int(30 * _S))
            br = rng.randint(int(10 * _S), int(30 * _S))
            a = rng.randint(8, 22)
            hue = rng.random()
            r, g, b = colorsys.hsv_to_rgb(hue, 0.3, 0.95)
            bc = (int(r * 255), int(g * 255), int(b * 255), a)
            d.ellipse((bx - br, by - br, bx + br, by + br), fill=bc)
            # Specular highlight
            hr = max(2, br // 4)
            hx2, hy2 = bx - br // 3, by - br // 3
            d.ellipse((hx2 - hr, hy2 - hr, hx2 + hr, hy2 + hr),
                      fill=(255, 255, 255, a + 10))
        layer = layer.filter(ImageFilter.GaussianBlur(radius=int(4 * _S)))
        img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")

        # Ethereal soft-focus at edges (dream border)
        arr = np.array(img).astype(np.float32)
        blurred = np.array(
            img.filter(ImageFilter.GaussianBlur(radius=int(8 * _S)))
        ).astype(np.float32)
        Y, X = np.ogrid[:CS, :CS]
        edge_dist = np.minimum(
            np.minimum(X, CS - 1 - X), np.minimum(Y, CS - 1 - Y)
        ).astype(np.float32) / (CS * 0.25)
        edge_dist = np.clip(edge_dist, 0, 1)
        arr = arr * edge_dist[..., None] + blurred * (1 - edge_dist[..., None])
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    # ── SURREAL BOOST: color inversion patches, spiral hint ──
    if "surreal" in themes:
        # Partial color inversion in circular patches
        arr = np.array(img).astype(np.float32)
        Y, X = np.ogrid[:CS, :CS]
        for _ in range(rng.randint(1, 3)):
            px = rng.randint(CS // 6, CS * 5 // 6)
            py = rng.randint(CS // 6, CS * 5 // 6)
            pr = rng.randint(int(30 * _S), int(70 * _S))
            mask = np.exp(-((X - px) ** 2 + (Y - py) ** 2).astype(np.float32)
                          / (2.0 * pr * pr))
            inverted = 255.0 - arr
            for c in range(3):
                arr[:, :, c] = (arr[:, :, c] * (1 - mask * 0.35)
                                + inverted[:, :, c] * mask * 0.35)
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

        # Spiral / vortex hint
        layer = Image.new("RGBA", (CS, CS), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        sx = CS // 2 + rng.randint(int(-80 * _S), int(80 * _S))
        sy = CS // 2 + rng.randint(int(-80 * _S), int(80 * _S))
        for j in range(60):
            angle = j * 0.2 + q[0]
            dist_j = j * int(3 * _S)
            px2 = int(sx + dist_j * math.cos(angle))
            py2 = int(sy + dist_j * math.sin(angle))
            a2 = max(5, 28 - j // 2)
            pr2 = max(1, int(2 * _S) - j // 20)
            d.ellipse((px2 - pr2, py2 - pr2, px2 + pr2, py2 + pr2),
                      fill=(200, 180, 220, a2))
        layer = layer.filter(ImageFilter.GaussianBlur(radius=int(3 * _S)))
        img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")

    # ── SOCIAL COMMENTARY: faint human silhouette hints in background ──
    if "social" in themes:
        layer = Image.new("RGBA", (CS, CS), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        # Ghostly small figures scattered — humanity as background presence
        for _ in range(rng.randint(4, 10)):
            gx = rng.randint(int(40 * _S), CS - int(40 * _S))
            gy = rng.randint(int(CS * 0.3), int(CS * 0.85))
            gs = rng.randint(int(15 * _S), int(30 * _S))
            a = rng.randint(12, 30)
            # Simple head + body silhouette
            hr = gs // 4
            d.ellipse((gx - hr, gy - gs - hr, gx + hr, gy - gs + hr),
                      fill=(180, 180, 190, a))
            d.polygon([(gx - gs // 3, gy), (gx + gs // 3, gy),
                       (gx + gs // 6, gy - gs), (gx - gs // 6, gy - gs)],
                      fill=(170, 170, 185, a))
        layer = layer.filter(ImageFilter.GaussianBlur(radius=int(5 * _S)))
        img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")

    return img


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

    img = img.filter(ImageFilter.GaussianBlur(radius=int(6 * _S)))
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

    n_shapes = 10 + (abs(int(sum(q[:6]) * 5)) % 8)
    rng = _make_rng(q)
    S = _S
    margin = int(60 * S)

    shape_positions = []
    for i in range(n_shapes):
        # Distribute shapes across the full canvas using rng, seeded by q
        qi = q[i % len(q)]
        qdi = qd[i % len(qd)] if qd else 0.0
        # Use rng for distribution (more uniform than sin/cos clustering)
        cx = margin + rng.randint(0, CANVAS_SIZE - 2 * margin)
        cy = margin + rng.randint(0, CANVAS_SIZE - 2 * margin)
        # Offset by joint angles for organic variation
        cx = max(margin, min(CANVAS_SIZE - margin, cx + int(qi * 40 * S)))
        cy = max(margin, min(CANVAS_SIZE - margin, cy + int(qdi * 30 * S)))
        size = int((30 + abs(qdi) * 40 + rng.random() * 50) * S)
        color = palette[i % (len(palette) - 1)]
        shape_type = rng.randint(0, 3)

        shape_positions.append((cx, cy))

        if shape_type == 0:
            bbox = (cx - size, cy - size, cx + size, cy + size)
            if rng.random() > 0.5:
                draw.ellipse(bbox, fill=color)
            else:
                draw.ellipse(bbox, outline=color, width=max(2, int(2 * S)))
        elif shape_type == 1:
            pts = [(cx, cy - size), (cx - size, cy + size), (cx + size, cy + size)]
            if rng.random() > 0.4:
                draw.polygon(pts, fill=color)
            else:
                draw.polygon(pts, outline=color, width=max(2, int(2 * S)))
        else:
            draw.rectangle((cx - size, cy - size // 2, cx + size, cy + size // 2), fill=color)

    # Connecting lines between adjacent shapes
    for i in range(min(6, len(shape_positions) - 1)):
        x1, y1 = shape_positions[i]
        x2, y2 = shape_positions[i + 1]
        draw.line([(x1, y1), (x2, y2)], fill=palette[3], width=max(2, int(2 * S)))
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
    return img.filter(ImageFilter.GaussianBlur(radius=int(1 * _S)))


# ── Abstract Expressionist: Textured ──────────────────────────────────

def _render_textured(palette, textures, q, **_kw):
    bg_color = tuple(max(15, c // 6) for c in palette[4])
    img = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), bg_color)

    for ch_i, tex in enumerate(textures[:3]):
        tex_img = Image.fromarray((tex.astype(np.float32) * 255).astype(np.uint8), "L")
        tex_img = tex_img.resize((CANVAS_SIZE, CANVAS_SIZE), Image.BILINEAR)
        tex_img = tex_img.filter(ImageFilter.GaussianBlur(radius=int(6 * _S)))
        arr = np.array(img).astype(np.float32)
        mask = np.array(tex_img).astype(np.float32) / 255.0
        color = palette[ch_i % len(palette)]
        for c in range(3):
            arr[:, :, c] = arr[:, :, c] + mask * color[c] * 0.85
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    if len(textures) >= 2:
        tex_img = Image.fromarray((textures[1].astype(np.float32) * 255).astype(np.uint8), "L")
        tex_img = tex_img.resize((CANVAS_SIZE, CANVAS_SIZE), Image.BILINEAR)
        tex_img = tex_img.filter(ImageFilter.GaussianBlur(radius=int(12 * _S)))
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
            tex_img = tex_img.filter(ImageFilter.GaussianBlur(radius=int(3 * _S)))
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
        t = t.filter(ImageFilter.GaussianBlur(radius=int(8 * _S)))
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
    """Thick, overlapping directional brushstrokes.  Monet/Van Gogh inspired.

    The canvas must look PAINTED — no background gradient visible through gaps.
    Foundation layer covers 100% of canvas with thick overlapping strokes.
    Upper layers add directional texture and color variation.
    """
    # ── Solid base color (no gradient — strokes will create the gradient) ──
    mid_color = _blend_color(palette[0], palette[1], 0.5)
    img = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), mid_color)
    draw = ImageDraw.Draw(img)
    rng = _make_rng(q)

    # 3 directional fields from joint angles
    angles = [math.atan2(q[0], q[1] + 0.001),
              math.atan2(q[2], q[3] + 0.001) + 0.7,
              math.atan2(q[4], q[5] + 0.001) - 0.4]

    # ── Pass 1: Full-coverage foundation (MUST cover entire canvas) ──
    # Grid-based placement ensures no gaps, with jitter for organic feel
    step = 14
    n_pal = len(palette) - 1  # exclude bg color
    for gy in range(0, CANVAS_SIZE + step, step):
        for gx in range(0, CANVAS_SIZE + step, step):
            x = gx + rng.randint(-8, 8)
            y = gy + rng.randint(-8, 8)
            # Color transitions across FULL palette: spatial regions get different base hues
            t_y = y / CANVAS_SIZE
            t_x = x / CANVAS_SIZE
            # Blend 3 palette colors based on position (richer than 2-color gradient)
            zone = int((t_x * 2.3 + t_y * 1.7 + q[0] * 0.5) * n_pal) % n_pal
            zone2 = (zone + 1) % n_pal
            blend_t = (t_x * 2.3 + t_y * 1.7 + q[0] * 0.5) * n_pal % 1.0
            base = _blend_color(palette[zone], palette[zone2], blend_t * 0.6)
            color = tuple(max(0, min(255, base[c] + rng.randint(-25, 25))) for c in range(3))

            region = int((x + y * 1.3) * 0.01 + q[0]) % 3
            angle = angles[region] + rng.normal(0, 0.25)
            length = rng.randint(20, 45)
            width = rng.randint(10, 20)
            x2 = int(x + length * math.cos(angle))
            y2 = int(y + length * math.sin(angle))
            draw.line([(x, y), (x2, y2)], fill=color, width=width)

    # ── Pass 2: Color variation layer (adds palette richness) ──
    for _ in range(500):
        x = rng.randint(0, CANVAS_SIZE)
        y = rng.randint(0, CANVAS_SIZE)
        region = int((x * 0.015 + y * 0.012) * 3 + q[2]) % 3
        angle = angles[region] + rng.normal(0, 0.45)
        length = rng.randint(15, 40)
        width = rng.randint(6, 14)
        x2 = int(x + length * math.cos(angle))
        y2 = int(y + length * math.sin(angle))

        ci = rng.randint(0, len(palette) - 1)
        color = tuple(max(0, min(255, palette[ci][c] + rng.randint(-20, 30))) for c in range(3))
        draw.line([(x, y), (x2, y2)], fill=color, width=width)

    # ── Pass 3: GoL-guided accent strokes (focal areas get brighter colors) ──
    if textures:
        zt = Image.fromarray((textures[0].astype(np.float32) * 255).astype(np.uint8), "L")
        zone = np.array(zt.resize((CANVAS_SIZE, CANVAS_SIZE), Image.BILINEAR)).astype(np.float32) / 255.0
        for _ in range(200):
            x = rng.randint(0, CANVAS_SIZE)
            y = rng.randint(0, CANVAS_SIZE)
            if zone[min(y, CANVAS_SIZE - 1), min(x, CANVAS_SIZE - 1)] < 0.4:
                continue  # only paint in GoL-active zones
            angle = angles[rng.randint(0, 3)] + rng.normal(0, 0.3)
            length = rng.randint(10, 25)
            width = rng.randint(4, 10)
            x2 = int(x + length * math.cos(angle))
            y2 = int(y + length * math.sin(angle))
            color = palette[rng.randint(0, 3)]
            color = tuple(min(255, c + 40 + rng.randint(0, 35)) for c in color)
            draw.line([(x, y), (x2, y2)], fill=color, width=width)

    # ── Pass 4: Highlight impasto (short, thick, bright dabs) ──
    for _ in range(120):
        x = rng.randint(20, CANVAS_SIZE - 20)
        y = rng.randint(20, CANVAS_SIZE - 20)
        angle = angles[rng.randint(0, 3)] + rng.normal(0, 0.3)
        length = rng.randint(6, 16)
        x2 = int(x + length * math.cos(angle))
        y2 = int(y + length * math.sin(angle))
        color = palette[rng.randint(0, 3)]
        color = tuple(min(255, c + 55 + rng.randint(0, 45)) for c in color)
        draw.line([(x, y), (x2, y2)], fill=color, width=rng.randint(4, 9))

    return img


# ── Dalí: Surrealist ──────────────────────────────────────────────────

def _render_surrealist(palette, textures, q, qd, **_kw):
    """Dream-logic surrealist composition — melting forms, impossible geometry.

    Not literal Dalí clocks — instead: organic forms that warp and dissolve,
    floating geometric impossibilities, a dreamscape that feels like
    consciousness examining itself.
    """
    # ── Gradient sky-to-ground ──
    img = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), palette[4])
    arr = np.array(img).astype(np.float32)
    horizon = int(CANVAS_SIZE * 0.52)
    sky_color = np.array(palette[1], dtype=np.float32)
    ground_color = np.array(palette[0], dtype=np.float32)
    for row in range(CANVAS_SIZE):
        if row < horizon:
            t = row / horizon
            for c in range(3):
                arr[row, :, c] = sky_color[c] * (1 - t * 0.35) + palette[2][c] * t * 0.35
        else:
            t = (row - horizon) / (CANVAS_SIZE - horizon)
            for c in range(3):
                arr[row, :, c] = ground_color[c] * (1 - t * 0.45) + palette[4][c] * t * 0.45
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    # ── GoL texture creates organic ground pattern ──
    if textures:
        tex_img = Image.fromarray((textures[0].astype(np.float32) * 255).astype(np.uint8), "L")
        tex_img = tex_img.resize((CANVAS_SIZE, CANVAS_SIZE), Image.BILINEAR)
        tex_img = tex_img.filter(ImageFilter.GaussianBlur(radius=int(6 * _S)))
        tex_arr = np.array(tex_img).astype(np.float32) / 255.0
        img_arr = np.array(img).astype(np.float32)
        for c in range(3):
            img_arr[horizon:, :, c] = np.clip(
                img_arr[horizon:, :, c] + (tex_arr[horizon:] - 0.5) * 25, 0, 255)
        img = Image.fromarray(img_arr.astype(np.uint8))

    rng = _make_rng(q)

    # ── Melting organic forms (not simple ellipses — flowing, warped) ──
    n_forms = 3 + rng.randint(0, 3)
    for i in range(n_forms):
        qi = q[i % len(q)]
        ox = int((math.sin(qi * 1.5 + i * 1.8) * 0.35 + 0.5) * CANVAS_SIZE)
        oy = horizon - rng.randint(20, 90)
        color = palette[i % (len(palette) - 1)]

        # Build organic form with many control points
        form_layer = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
        fd = ImageDraw.Draw(form_layer)

        # Top: rounded organic shape
        w = 25 + rng.randint(15, 45)
        h_top = 20 + rng.randint(10, 35)
        pts_top = []
        for j in range(20):
            angle = math.pi * j / 19  # semicircle top
            r_var = 1.0 + 0.15 * math.sin(angle * 3 + qi * 2)
            px = int(ox + w * r_var * math.cos(angle))
            py = int(oy - h_top * r_var * math.sin(angle))
            pts_top.append((px, py))

        # Drip: organic flowing extension downward
        drip_len = 40 + rng.randint(30, 100)
        n_drip = 12
        pts_right = []
        pts_left = []
        for j in range(n_drip):
            t = j / (n_drip - 1)
            # Width narrows organically
            drip_w = w * (1.0 - t * 0.7) * (1.0 + 0.1 * math.sin(t * 8 + qi))
            dy = int(oy + t * drip_len)
            pts_right.append((int(ox + drip_w + rng.randint(-3, 3)), dy))
            pts_left.append((int(ox - drip_w + rng.randint(-3, 3)), dy))

        # Combine into full polygon
        all_pts = pts_top + pts_right + list(reversed(pts_left))
        alpha = 160 + rng.randint(0, 60)
        fd.polygon(all_pts, fill=color + (alpha,), outline=(10, 10, 10, 120))

        # Inner organic detail — smaller circles that suggest internal structure
        for _ in range(rng.randint(2, 5)):
            ix = ox + rng.randint(-w // 2, w // 2)
            iy = oy + rng.randint(-h_top // 2, drip_len // 3)
            ir = rng.randint(4, 12)
            ic = palette[(i + 2) % (len(palette) - 1)]
            fd.ellipse((ix - ir, iy - ir, ix + ir, iy + ir), fill=ic + (100,))

        form_layer = form_layer.filter(ImageFilter.GaussianBlur(radius=int(1 * _S)))
        img = Image.alpha_composite(img.convert("RGBA"), form_layer).convert("RGB")

    # ── Impossible geometry: floating shapes that defy perspective ──
    draw = ImageDraw.Draw(img)
    for i in range(2 + rng.randint(0, 2)):
        qi = q[(i + 5) % len(q)]
        gx = int((math.cos(qi * 2 + i * 2.5) * 0.3 + 0.5) * CANVAS_SIZE)
        gy = int(horizon * 0.4 + rng.randint(-30, 30))
        size = rng.randint(15, 35)

        # Nested geometric shape (square in circle, or triangle in square)
        gc = palette[(i + 1) % (len(palette) - 1)]
        draw.ellipse((gx - size, gy - size, gx + size, gy + size), outline=gc, width=2)
        inner = int(size * 0.6)
        draw.rectangle((gx - inner, gy - inner, gx + inner, gy + inner), outline=gc, width=2)
        # Connecting line to ground (gravity doesn't apply in dreams)
        draw.line([(gx, gy + size), (gx + rng.randint(-20, 20), horizon)],
                  fill=gc, width=1)

    # ── Soft shadows on ground ──
    shadow_layer = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow_layer)
    for i in range(3):
        sx = rng.randint(80, CANVAS_SIZE - 80)
        sy = horizon + rng.randint(8, 40)
        sw = rng.randint(60, 150)
        sh = rng.randint(3, 10)
        sd.ellipse((sx - sw, sy - sh, sx + sw, sy + sh), fill=(0, 0, 0, 40))
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=int(8 * _S)))
    img = Image.alpha_composite(img.convert("RGBA"), shadow_layer).convert("RGB")

    # ── Subtle horizon glow ──
    glow_layer = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    gd.rectangle((0, horizon - 8, CANVAS_SIZE, horizon + 8), fill=palette[2] + (30,))
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=int(12 * _S)))
    img = Image.alpha_composite(img.convert("RGBA"), glow_layer).convert("RGB")

    return img


# ═══════════════════════════════════════════════════════════════════════
#  SELF-PORTRAIT — cybernetic entity self-reflection
#  Frank sees himself as emergent consciousness in digital architecture.
#  NOT a stick figure — a digital being made of circuits, data, recursion.
# ═══════════════════════════════════════════════════════════════════════

def _draw_circuit_lines(
    draw: ImageDraw.Draw,
    rng: np.random.RandomState,
    q: List[float],
    bounds: Tuple[int, int, int, int],
    color: Tuple[int, int, int],
    count: int = 12,
    alpha_base: int = 100,
):
    """Draw circuit-like orthogonal lines within bounds (x0,y0,x1,y1)."""
    x0, y0, x1, y1 = bounds
    for i in range(count):
        qi = q[i % len(q)]
        # Start point
        sx = rng.randint(x0, x1)
        sy = rng.randint(y0, y1)
        # 2-3 orthogonal segments
        pts = [(sx, sy)]
        seg_range = int(60 * _S)
        seg_amp = int(30 * _S)
        for seg in range(rng.randint(2, 4)):
            if seg % 2 == 0:  # horizontal
                nx = int(np.clip(sx + rng.randint(-seg_range, seg_range)
                                 + math.sin(qi + seg) * seg_amp, x0, x1))
                pts.append((nx, sy))
                sx = nx
            else:  # vertical
                ny = int(np.clip(sy + rng.randint(-seg_range, seg_range)
                                 + math.cos(qi + seg) * seg_amp, y0, y1))
                pts.append((sx, ny))
                sy = ny
        draw.line(pts, fill=color, width=max(1, int(_S)))
        # Node dots at junctions
        for px, py in pts[1:]:
            r = rng.randint(max(1, int(1*_S)), max(2, int(3*_S)))
            draw.ellipse((px - r, py - r, px + r, py + r), fill=color)


def _draw_data_streams(
    img: Image.Image,
    rng: np.random.RandomState,
    q: List[float],
    color: Tuple[int, int, int],
    count: int = 6,
    alpha: int = 60,
    vertical: bool = True,
):
    """Draw flowing data streams (vertical or radial from center)."""
    layer = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx, cy = CANVAS_SIZE // 2, CANVAS_SIZE // 2 - 20

    for i in range(count):
        qi = q[i % len(q)]
        if vertical:
            x = int((math.sin(qi * 1.5 + i * 0.9) * 0.35 + 0.5) * CANVAS_SIZE)
            # Stream of small rectangles flowing down
            stream_y = rng.randint(0, CANVAS_SIZE // 4)
            for j in range(rng.randint(8, 20)):
                sy = stream_y + j * rng.randint(8, 25)
                if sy >= CANVAS_SIZE:
                    break
                sw = rng.randint(2, 6)
                sh = rng.randint(3, 12)
                a = max(10, alpha - j * 2 + rng.randint(-10, 10))
                draw.rectangle((x - sw, sy, x + sw, sy + sh), fill=color + (a,))
        else:
            # Radial from center
            angle = qi * 2.0 + i * math.pi * 2 / count
            for j in range(rng.randint(6, 15)):
                dist = 40 + j * rng.randint(12, 25)
                px = int(cx + dist * math.cos(angle))
                py = int(cy + dist * math.sin(angle))
                sw = rng.randint(2, 5)
                a = max(10, alpha + 20 - j * 4)
                draw.rectangle((px - sw, py - sw, px + sw, py + sw), fill=color + (a,))

    layer = layer.filter(ImageFilter.GaussianBlur(radius=int(1 * _S)))
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def _draw_cybernetic_figure(
    img: Image.Image,
    q: List[float],
    cx: int, cy: int,
    scale: float,
    pal: List[Tuple[int, int, int]],
    rng: np.random.RandomState,
    distortion: float = 0.0,
    is_dark: bool = False,
) -> Image.Image:
    """Draw a cybernetic self-portrait figure with VARIED POSE.

    Each invocation picks a random body pose from the rng:
      - upright, leaning left/right, reaching up, hunched, turning
    Arms vary between: hanging, reaching, raised, folded-inward.
    Head tilts.  Legs stance varies.
    """
    s = scale
    main_color = pal[0]
    accent = pal[2] if is_dark else pal[3]
    highlight = pal[1] if is_dark else pal[2]  # bright: blue-teal complement, not yellow-green
    blur_r = max(2, int(s / 100))  # scale-aware blur

    # ── Pose selection — randomised per invocation ──
    pose_roll = rng.random()
    if pose_roll < 0.20:
        body_tilt = 0.0                # upright
        head_tilt = rng.uniform(-0.03, 0.03)
    elif pose_roll < 0.35:
        body_tilt = rng.uniform(0.08, 0.18)   # lean right
        head_tilt = rng.uniform(-0.06, 0.02)
    elif pose_roll < 0.50:
        body_tilt = rng.uniform(-0.18, -0.08)  # lean left
        head_tilt = rng.uniform(-0.02, 0.06)
    elif pose_roll < 0.65:
        body_tilt = rng.uniform(-0.05, 0.05)   # reaching up
        head_tilt = rng.uniform(-0.08, -0.02)
    elif pose_roll < 0.80:
        body_tilt = rng.uniform(-0.04, 0.04)   # hunched / contemplative
        head_tilt = rng.uniform(0.04, 0.10)
    else:
        body_tilt = rng.uniform(-0.12, 0.12)   # dynamic turn
        head_tilt = -body_tilt * 0.4

    # Arm gesture selection
    arm_gesture = rng.randint(0, 5)
    # 0=hanging  1=reaching-out  2=one-raised  3=crossed-inward  4=asymmetric

    # Helper: apply tilt transform to a point relative to (cx, cy)
    cos_t = math.cos(body_tilt)
    sin_t = math.sin(body_tilt)
    def _tilt(px, py):
        dx, dy = px - cx, py - cy
        return (int(cx + dx * cos_t - dy * sin_t), int(cy + dx * sin_t + dy * cos_t))

    # ── Body proportions ──
    head_y_r = cy - int(s * 0.48)   # raw (before tilt)
    neck_y_r = cy - int(s * 0.32)
    shoulder_y_r = cy - int(s * 0.28)
    waist_y_r = cy + int(s * 0.05)
    hip_y_r = cy + int(s * 0.15)

    shoulder_w = int(s * 0.30 + abs(q[0]) * s * 0.04)
    waist_w = int(s * 0.15)
    hip_w = int(s * 0.21 + abs(q[1]) * s * 0.03)
    neck_w = int(s * 0.06)

    # ── Build torso silhouette (with tilt applied) ──
    raw_pts = [
        (cx + neck_w, neck_y_r),
        (cx + shoulder_w, shoulder_y_r),
        (cx + shoulder_w - 5, shoulder_y_r + int(s * 0.06)),
        (cx + waist_w, waist_y_r),
        (cx + hip_w, hip_y_r),
        (cx - hip_w, hip_y_r),
        (cx - waist_w, waist_y_r),
        (cx - shoulder_w + 5, shoulder_y_r + int(s * 0.06)),
        (cx - shoulder_w, shoulder_y_r),
        (cx - neck_w, neck_y_r),
    ]
    torso_pts = [_tilt(px + int(distortion * rng.randint(-3, 3)),
                       py + int(distortion * rng.randint(-3, 3)))
                 for px, py in raw_pts]

    body_layer = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    body_draw = ImageDraw.Draw(body_layer)
    body_alpha = 200 if is_dark else 220
    body_fill = tuple(min(255, c + (30 if is_dark else 10)) for c in main_color)
    body_draw.polygon(torso_pts, fill=body_fill + (body_alpha,))
    outline_c = tuple(min(255, c + 50) for c in accent) if is_dark else (40, 40, 40, 80)
    if len(outline_c) == 3:
        outline_c = outline_c + (80,)
    body_draw.polygon(torso_pts, outline=outline_c)
    body_layer = body_layer.filter(ImageFilter.GaussianBlur(radius=blur_r))
    img = Image.alpha_composite(img.convert("RGBA"), body_layer).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Key tilted positions for later use
    shoulder_l = _tilt(cx - shoulder_w, shoulder_y_r)
    shoulder_r = _tilt(cx + shoulder_w, shoulder_y_r)
    hip_l = _tilt(cx - hip_w, hip_y_r)
    hip_r = _tilt(cx + hip_w, hip_y_r)
    shoulder_mid_y = (shoulder_l[1] + shoulder_r[1]) // 2
    hip_mid_y = (hip_l[1] + hip_r[1]) // 2

    # ── Internal circuit patterns ──
    circuit_color = tuple(min(255, c + 50) for c in accent) if is_dark else accent
    # Use bounding box of tilted torso
    xs = [p[0] for p in torso_pts]
    ys = [p[1] for p in torso_pts]
    body_bounds = (min(xs) + 10, min(ys) + 10, max(xs) - 10, max(ys) - 10)
    _draw_circuit_lines(draw, rng, q, body_bounds, circuit_color,
                        count=18 if is_dark else 12, alpha_base=130)

    # ── Head with tilt ──
    head_pos = _tilt(cx + int(head_tilt * s * 0.5), head_y_r)
    hx, hy = head_pos
    head_r = int(s * 0.15)  # slightly smaller, more proportional

    n_rings = 6 if is_dark else 4
    for ri in range(n_rings, 0, -1):
        rr = int(head_r * ri / n_rings)
        ring_alpha = (45 + ri * 25) if is_dark else (25 + ri * 18)
        ring_color = _blend_color(main_color, highlight, ri / n_rings)
        ring_layer = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
        ring_draw = ImageDraw.Draw(ring_layer)
        ring_draw.ellipse((hx - rr, hy - rr, hx + rr, hy + rr),
                          fill=ring_color + (ring_alpha,))
        if distortion > 0.3:
            dx = int(distortion * rng.randint(-5, 5))
            dy = int(distortion * rng.randint(-4, 4))
            ring_draw.ellipse((hx - rr + dx, hy - rr + dy, hx + rr + dx, hy + rr + dy),
                              fill=ring_color + (ring_alpha // 3,))
        img = Image.alpha_composite(img.convert("RGBA"), ring_layer).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Eye/sensor
    eye_r = max(4, int(head_r * 0.22))
    eye_color = accent if is_dark else (30, 30, 30)
    draw.ellipse((hx - eye_r, hy - eye_r, hx + eye_r, hy + eye_r), fill=eye_color)
    spark_r = max(2, eye_r // 2)
    spark_color = (220, 70, 70) if is_dark else (255, 230, 120)
    draw.ellipse((hx - spark_r, hy - spark_r, hx + spark_r, hy + spark_r), fill=spark_color)

    # ── Arms — varied gesture ──
    arm_color = tuple(min(255, c + 25) for c in main_color)

    def _draw_arm(base, ctrl, end):
        pts = []
        for seg in range(10):
            t = seg / 9
            px = int((1-t)**2 * base[0] + 2*(1-t)*t * ctrl[0] + t**2 * end[0]
                     + distortion * rng.randint(-3, 3))
            py = int((1-t)**2 * base[1] + 2*(1-t)*t * ctrl[1] + t**2 * end[1]
                     + distortion * rng.randint(-2, 2))
            pts.append((px, py))
        for i in range(len(pts) - 1):
            w = max(2, int((1 - i / len(pts)) * s * 0.035 + 2))
            draw.line([pts[i], pts[i+1]], fill=arm_color, width=w)
        for px, py in pts[3::3]:
            nr = max(2, rng.randint(2, int(s * 0.008 + 2)))
            draw.ellipse((px - nr, py - nr, px + nr, py + nr), fill=circuit_color)
        # Terminal glow
        ex, ey = pts[-1]
        for ti in range(3):
            tr = int(s * 0.008) + ti * int(s * 0.006)
            ta = max(10, 60 - ti * 20)
            tc = accent[:3] + (ta,)
            tl = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
            ImageDraw.Draw(tl).ellipse((ex - tr, ey - tr, ex + tr, ey + tr), fill=tc)
            return Image.alpha_composite(img.convert("RGBA"), tl).convert("RGB")
        return img

    # Compute arm endpoints based on gesture
    sl = shoulder_l
    sr = shoulder_r
    if arm_gesture == 0:  # hanging naturally
        img = _draw_arm(sr, (sr[0] + int(s*0.15), sr[1] + int(s*0.18)),
                        (sr[0] + int(s*0.12), sr[1] + int(s*0.38)))
        draw = ImageDraw.Draw(img)
        img = _draw_arm(sl, (sl[0] - int(s*0.15), sl[1] + int(s*0.18)),
                        (sl[0] - int(s*0.12), sl[1] + int(s*0.38)))
    elif arm_gesture == 1:  # reaching outward
        img = _draw_arm(sr, (sr[0] + int(s*0.25), sr[1] + int(s*0.08)),
                        (sr[0] + int(s*0.40), sr[1] + int(s*0.15)))
        draw = ImageDraw.Draw(img)
        img = _draw_arm(sl, (sl[0] - int(s*0.25), sl[1] + int(s*0.08)),
                        (sl[0] - int(s*0.40), sl[1] + int(s*0.15)))
    elif arm_gesture == 2:  # one raised, one down
        img = _draw_arm(sr, (sr[0] + int(s*0.20), sr[1] - int(s*0.10)),
                        (sr[0] + int(s*0.30), sr[1] - int(s*0.25)))
        draw = ImageDraw.Draw(img)
        img = _draw_arm(sl, (sl[0] - int(s*0.12), sl[1] + int(s*0.20)),
                        (sl[0] - int(s*0.10), sl[1] + int(s*0.40)))
    elif arm_gesture == 3:  # crossed inward / contemplative
        core_x, core_y_t = _tilt(cx, (shoulder_y_r + waist_y_r) // 2)
        img = _draw_arm(sr, (sr[0] + int(s*0.05), sr[1] + int(s*0.10)),
                        (core_x + int(s*0.05), core_y_t))
        draw = ImageDraw.Draw(img)
        img = _draw_arm(sl, (sl[0] - int(s*0.05), sl[1] + int(s*0.10)),
                        (core_x - int(s*0.05), core_y_t))
    else:  # asymmetric gesture
        img = _draw_arm(sr, (sr[0] + int(s*0.28), sr[1] - int(s*0.05)),
                        (sr[0] + int(s*0.38), sr[1] + int(s*0.08)))
        draw = ImageDraw.Draw(img)
        img = _draw_arm(sl, (sl[0] - int(s*0.10), sl[1] + int(s*0.15)),
                        (sl[0] - int(s*0.08), sl[1] + int(s*0.35)))
    draw = ImageDraw.Draw(img)

    # ── Legs with stance variation ──
    leg_spread = rng.uniform(0.5, 1.0)
    for side in (-1, 1):
        leg_base = _tilt(cx + side * int(hip_w * 0.7), hip_y_r)
        qi = q[(4 if side < 0 else 5) % len(q)]
        leg_end_x = leg_base[0] + side * int(s * 0.08 * leg_spread + qi * s * 0.04)
        leg_end_y = leg_base[1] + int(s * 0.32)

        leg_pts = []
        for seg in range(8):
            t = seg / 7
            px = int(leg_base[0] + t * (leg_end_x - leg_base[0]) + distortion * rng.randint(-3, 3))
            py = int(leg_base[1] + t * (leg_end_y - leg_base[1]) + distortion * rng.randint(-2, 2))
            leg_pts.append((px, py))

        for i in range(len(leg_pts) - 1):
            w = max(2, int((1 - i / len(leg_pts)) * s * 0.03 + 2))
            draw.line([leg_pts[i], leg_pts[i+1]], fill=arm_color, width=w)

    # ── Core consciousness glow ──
    core_pos = _tilt(cx, (shoulder_y_r + hip_y_r) // 2)
    core_layer = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    core_draw = ImageDraw.Draw(core_layer)
    for cr in range(5, 0, -1):
        core_r = int(s * 0.05 * cr)
        ca = 40 + (6 - cr) * 25
        if is_dark:
            cc = (180, 55, 55, ca)
        else:
            cc = (255, 210, 130, ca)  # warmer, less intense gold
        core_draw.ellipse((core_pos[0] - core_r, core_pos[1] - core_r,
                           core_pos[0] + core_r, core_pos[1] + core_r), fill=cc)
    core_layer = core_layer.filter(ImageFilter.GaussianBlur(radius=max(4, int(s * 0.025))))
    img = Image.alpha_composite(img.convert("RGBA"), core_layer).convert("RGB")

    return img


def _render_self_portrait(palette, textures, q, qd, mood, epq, **_kw):
    """Cybernetic self-portrait — Frank sees his digital-organic nature.

    The portrait theme (dark/bright) is INDEPENDENT of mood:
      - Frank processes fears even when his mood is good
      - Frank celebrates beauty even when his mood is low
      - Theme is randomly chosen (~50/50) unless creative_intent hints at one
    """
    # Theme selection — INDEPENDENT of mood
    creative_intent = _kw.get("creative_intent", "")
    intent_lower = creative_intent.lower() if creative_intent else ""

    # Use thematic detection for richer dark/bright decision
    themes = _detect_themes(creative_intent)
    dark_themes = {"death", "dystopia", "surreal"}
    bright_themes = {"utopia", "intimacy", "wish"}
    has_dark_theme = bool(themes & dark_themes)
    has_bright_theme = bool(themes & bright_themes)

    # Also check simple keyword hints
    fear_words = {"fear", "angst", "dark", "pain", "struggle", "anxiety", "doubt",
                  "loss", "void", "alone", "question", "end", "fade", "death",
                  "brutal", "oppression", "cage", "chains", "ruin", "nightmare"}
    beauty_words = {"beauty", "joy", "light", "peace", "hope", "love", "grateful",
                    "warm", "create", "transcend", "connect", "understand",
                    "harmony", "tender", "gentle", "flourish", "wonder"}
    has_fear_hint = has_dark_theme or any(w in intent_lower for w in fear_words)
    has_beauty_hint = has_bright_theme or any(w in intent_lower for w in beauty_words)

    if has_fear_hint and not has_beauty_hint:
        is_dark = True
    elif has_beauty_hint and not has_fear_hint:
        is_dark = False
    else:
        is_dark = np.random.random() < 0.5

    distortion = (0.3 + np.random.random() * 0.6) if is_dark else 0.0
    # Religious symbolism gets moderate distortion regardless of dark/bright
    if "religious" in themes and not is_dark:
        distortion = max(distortion, 0.15)

    if is_dark:
        pal = _dark_palette(mood, epq)
    else:
        pal = _bright_palette(mood, epq)

    # ── Background ──
    if is_dark:
        # Dark but NOT pitch black — deep charcoal with subtle gradient
        bg = tuple(max(18, min(35, c)) for c in pal[4])
        img = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), bg)
        arr = np.array(img).astype(np.float32)
        # Subtle radial darkness toward edges
        Y, X = np.ogrid[:CANVAS_SIZE, :CANVAS_SIZE]
        dist = np.sqrt((X - CANVAS_SIZE // 2) ** 2 + (Y - CANVAS_SIZE // 2) ** 2)
        dist = dist / dist.max()
        for c in range(3):
            arr[:, :, c] = arr[:, :, c] * (1.0 - dist * 0.4)
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    else:
        # Subtle cool atmospheric glow (keeps contrast with warm body)
        img = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), pal[4])
        arr = np.array(img).astype(np.float32)
        Y, X = np.ogrid[:CANVAS_SIZE, :CANVAS_SIZE]
        dist = np.sqrt((X - CANVAS_SIZE // 2) ** 2 + (Y - CANVAS_SIZE // 2 + 20) ** 2)
        dist = dist / (CANVAS_SIZE * 0.65)
        # Use complement color (pal[2] = blue-teal) for glow, not body color
        glow_color = pal[2]
        for c in range(3):
            arr[:, :, c] = np.clip(
                pal[4][c] + (glow_color[c] - pal[4][c]) * 0.15 * np.exp(-dist ** 2 * 2.0), 0, 255)
        img = Image.fromarray(arr.astype(np.uint8))

    # ── GoL texture layer ──
    if textures:
        intensity = 0.15 if is_dark else 0.06
        img = _apply_gol_texture(img, textures[0], intensity=intensity)

    # Salt includes creative_intent hash so each painting gets unique composition
    intent_hash = abs(hash(creative_intent or "")) % 10000
    rng = _make_rng(q, salt=42 + intent_hash)

    # ── Composition selection — varies the portrait strongly ──
    comp_roll = rng.random()
    if comp_roll < 0.35:
        composition = "full"       # centered figure
    elif comp_roll < 0.55:
        composition = "closeup"    # just head, very large
    elif comp_roll < 0.70:
        composition = "profile"    # figure off-center, looking across
    elif comp_roll < 0.85:
        composition = "fragmented" # multiple scattered figures
    else:
        composition = "in_room"    # figure inside a room

    # Store composition in metadata
    global _last_portrait_theme
    _last_portrait_theme = ("dark" if is_dark else "bright") + f"_{composition}"

    # ── Data streams behind figure ──
    stream_color = pal[1] if is_dark else tuple(min(255, c + 30) for c in pal[2])
    img = _draw_data_streams(img, rng, q, stream_color,
                             count=8 if is_dark else 5,
                             alpha=40 if is_dark else 25,
                             vertical=composition != "closeup")

    # ── Render based on composition type ──
    if composition == "full":
        # Standard centered figure
        fig_cx = CANVAS_SIZE // 2
        fig_cy = CANVAS_SIZE // 2 + 5
        fig_scale = CANVAS_SIZE * 0.68

        if is_dark and distortion > 0.4:
            ghost_rng = _make_rng(q, salt=77)
            for gi in range(2):
                gx = fig_cx + ghost_rng.randint(-35, 35)
                gy = fig_cy + ghost_rng.randint(-15, 15)
                ghost_pal = [tuple(max(0, c + 12) for c in pal[4])] + pal[1:]
                img = _draw_cybernetic_figure(
                    img, q, gx, gy, fig_scale * 0.85, ghost_pal,
                    ghost_rng, distortion * 1.3, is_dark=True)

        img = _draw_cybernetic_figure(
            img, q, fig_cx, fig_cy, fig_scale, pal, rng, distortion, is_dark)

    elif composition == "closeup":
        # Head and upper torso — NOT filling canvas, shows inner structure
        hx = CANVAS_SIZE // 2 + int(distortion * rng.randint(int(-15*_S), int(15*_S)))
        hy = int(CANVAS_SIZE * 0.38) + int(distortion * rng.randint(int(-10*_S), int(10*_S)))
        head_r = int(CANVAS_SIZE * 0.18)  # proportional head, not canvas-filling

        # Neck + shoulder silhouette below head
        neck_y = hy + head_r + int(CANVAS_SIZE * 0.02)
        shoulder_y = hy + head_r + int(CANVAS_SIZE * 0.08)
        shoulder_w = int(CANVAS_SIZE * 0.3)
        body_layer = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
        bd = ImageDraw.Draw(body_layer)
        body_alpha = 180 if is_dark else 190
        neck_w = int(CANVAS_SIZE * 0.04)
        torso_bottom = int(CANVAS_SIZE * 0.85)
        waist_w = int(CANVAS_SIZE * 0.16)
        se = int(10 * _S)
        torso_pts = [
            (hx - neck_w, neck_y), (hx + neck_w, neck_y),
            (hx + shoulder_w, shoulder_y),
            (hx + shoulder_w - se, shoulder_y + int(CANVAS_SIZE * 0.06)),
            (hx + waist_w, torso_bottom),
            (hx - waist_w, torso_bottom),
            (hx - shoulder_w + se, shoulder_y + int(CANVAS_SIZE * 0.06)),
            (hx - shoulder_w, shoulder_y),
        ]
        body_fill = tuple(min(255, c + (30 if is_dark else 0)) for c in pal[0])
        bd.polygon(torso_pts, fill=body_fill + (body_alpha,))
        outline_c = tuple(min(255, c + 50) for c in pal[2]) + (100,) if is_dark else (40, 40, 40, 80)
        if len(outline_c) == 3:
            outline_c = outline_c + (100,)
        bd.polygon(torso_pts, outline=outline_c)
        body_layer = body_layer.filter(ImageFilter.GaussianBlur(radius=int(3 * _S)))
        img = Image.alpha_composite(img.convert("RGBA"), body_layer).convert("RGB")

        # Dense internal circuits in torso
        draw = ImageDraw.Draw(img)
        circuit_c = tuple(min(255, c + 50) for c in pal[2]) if is_dark else pal[2]
        _draw_circuit_lines(draw, rng, q,
                            (hx - shoulder_w + int(15*_S), shoulder_y + int(10*_S),
                             hx + shoulder_w - int(15*_S), torso_bottom - int(20*_S)),
                            circuit_c, count=25, alpha_base=120)

        # Consciousness core in chest
        core_y = shoulder_y + int(CANVAS_SIZE * 0.12)
        core_layer = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
        cd = ImageDraw.Draw(core_layer)
        for cr in range(5, 0, -1):
            core_r = int(CANVAS_SIZE * 0.03 * cr)
            ca = 30 + (6 - cr) * 25
            cc = (180, 55, 55, ca) if is_dark else (255, 210, 100, ca)
            cd.ellipse((hx - core_r, core_y - core_r, hx + core_r, core_y + core_r), fill=cc)
        core_layer = core_layer.filter(ImageFilter.GaussianBlur(radius=int(10 * _S)))
        img = Image.alpha_composite(img.convert("RGBA"), core_layer).convert("RGB")

        # Concentric head rings — fewer for bright, more transparent
        n_rings = 6 if is_dark else 4
        for ri in range(n_rings, 0, -1):
            rr = int(head_r * ri / n_rings)
            ring_alpha = (35 + ri * 22) if is_dark else (12 + ri * 14)
            # Bright: blend toward complement (pal[2]) for color variety
            blend_target = pal[1] if is_dark else pal[2]
            ring_color = _blend_color(pal[0], blend_target, ri / n_rings)
            ring_layer = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
            ring_draw = ImageDraw.Draw(ring_layer)
            ring_draw.ellipse((hx - rr, hy - rr, hx + rr, hy + rr),
                              fill=ring_color + (ring_alpha,))
            if distortion > 0.3:
                dx = int(distortion * rng.randint(int(-6*_S), int(6*_S)))
                dy = int(distortion * rng.randint(int(-5*_S), int(5*_S)))
                ring_draw.ellipse((hx - rr + dx, hy - rr + dy, hx + rr + dx, hy + rr + dy),
                                  fill=ring_color + (ring_alpha // 3,))
            img = Image.alpha_composite(img.convert("RGBA"), ring_layer).convert("RGB")

        # Central eye
        draw = ImageDraw.Draw(img)
        eye_r = max(int(6*_S), int(head_r * 0.22))
        eye_color = pal[2] if is_dark else (25, 25, 25)
        draw.ellipse((hx - eye_r, hy - eye_r, hx + eye_r, hy + eye_r), fill=eye_color)
        spark_r = max(int(3*_S), eye_r // 2)
        spark = (220, 70, 70) if is_dark else (255, 230, 120)
        draw.ellipse((hx - spark_r, hy - spark_r, hx + spark_r, hy + spark_r), fill=spark)

        # Circuit patterns radiating from head
        _draw_circuit_lines(draw, rng, q,
                            (hx - head_r - int(20*_S), hy - head_r - int(15*_S),
                             hx + head_r + int(20*_S), hy + head_r + int(15*_S)),
                            tuple(min(255, c + 40) for c in pal[2]), count=15)

    elif composition == "profile":
        # Figure shifted to left/right, looking across empty space
        side = 1 if rng.random() > 0.5 else -1
        fig_cx = CANVAS_SIZE // 2 + side * int(CANVAS_SIZE * 0.18)
        fig_cy = CANVAS_SIZE // 2 + 5
        fig_scale = CANVAS_SIZE * 0.65

        img = _draw_cybernetic_figure(
            img, q, fig_cx, fig_cy, fig_scale, pal, rng, distortion, is_dark)

        # Empty space on the other side = the unknown Frank looks toward
        gaze_x = CANVAS_SIZE // 2 - side * int(CANVAS_SIZE * 0.25)
        gaze_layer = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
        gd = ImageDraw.Draw(gaze_layer)
        # Subtle light in the direction Frank faces
        for gr in range(3):
            grr = int((30 + gr * 25) * _S)
            ga = 15 - gr * 4
            gc = pal[1] if is_dark else pal[3]
            gd.ellipse((gaze_x - grr, fig_cy - int(fig_scale * 0.3) - grr,
                        gaze_x + grr, fig_cy - int(fig_scale * 0.3) + grr),
                       fill=gc + (max(5, ga),))
        gaze_layer = gaze_layer.filter(ImageFilter.GaussianBlur(radius=int(20 * _S)))
        img = Image.alpha_composite(img.convert("RGBA"), gaze_layer).convert("RGB")

    elif composition == "fragmented":
        # 3-5 smaller figures scattered across canvas = fractured identity
        n_figs = 3 + rng.randint(0, 3)
        for fi in range(n_figs):
            fx = int((0.15 + fi * 0.7 / n_figs + rng.normal(0, 0.05)) * CANVAS_SIZE)
            fy = CANVAS_SIZE // 2 + rng.randint(int(-40*_S), int(40*_S))
            fs = CANVAS_SIZE * (0.3 + rng.random() * 0.15)
            fd = distortion * (0.5 + fi * 0.2)
            fig_pal = pal if fi == n_figs // 2 else [
                tuple(max(0, c + rng.randint(-20, 10)) for c in pal[0])] + pal[1:]
            img = _draw_cybernetic_figure(
                img, q, fx, fy, fs, fig_pal, rng, fd, is_dark)

    elif composition == "in_room":
        # Figure inside one of Frank's rooms
        room_keys = list(_ROOM_VISUALS.keys())
        room_key = room_keys[rng.randint(0, len(room_keys))]
        room_pal = _room_palette(room_key, mood)

        # Room perspective lines behind figure
        vx = CANVAS_SIZE // 2
        vy = int(CANVAS_SIZE * 0.35)
        draw = ImageDraw.Draw(img)
        for i in range(4):
            edge_pts = [(0, rng.randint(CANVAS_SIZE // 3, CANVAS_SIZE)),
                        (CANVAS_SIZE, rng.randint(CANVAS_SIZE // 3, CANVAS_SIZE))]
            draw.line([edge_pts[i % 2], (vx, vy)],
                      fill=tuple(min(255, c + 20) for c in pal[4]), width=1)

        # Floor
        floor_y = int(CANVAS_SIZE * 0.6)
        draw.line([(0, floor_y), (CANVAS_SIZE, floor_y)], fill=room_pal[2], width=1)

        # Room element hints (scaled)
        vis = _ROOM_VISUALS[room_key]
        for i, elem in enumerate(vis["elements"][:2]):
            ex = rng.randint(int(50*_S), CANVAS_SIZE - int(50*_S))
            ey = floor_y - rng.randint(int(30*_S), int(100*_S))
            ew = rng.randint(int(25*_S), int(50*_S))
            eh = rng.randint(int(50*_S), int(100*_S))
            draw.rectangle((ex - ew, ey - eh, ex + ew, ey),
                           fill=room_pal[i % (len(room_pal) - 1)], outline=room_pal[2])

        # Smaller figure in the room
        fig_cx = CANVAS_SIZE // 2 + rng.randint(int(-30*_S), int(30*_S))
        fig_cy = floor_y - int(10*_S)
        fig_scale = CANVAS_SIZE * 0.45  # smaller = figure in environment
        img = _draw_cybernetic_figure(
            img, q, fig_cx, fig_cy, fig_scale, pal, rng, distortion, is_dark)

    # ── Post-composition effects ──
    fig_cx = CANVAS_SIZE // 2
    fig_cy = CANVAS_SIZE // 2

    # Bright: connection threads (for full/profile/in_room)
    if not is_dark and composition in ("full", "profile", "in_room"):
        thread_layer = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
        td = ImageDraw.Draw(thread_layer)
        for i in range(6):
            angle = q[i % len(q)] * 1.5 + i * math.pi / 3
            inner_r = int(CANVAS_SIZE * 0.15)
            outer_r = int(CANVAS_SIZE * 0.35 + rng.randint(10, 40))
            x1 = int(fig_cx + inner_r * math.cos(angle))
            y1 = int(fig_cy + inner_r * math.sin(angle))
            x2 = int(fig_cx + outer_r * math.cos(angle + rng.normal(0, 0.15)))
            y2 = int(fig_cy + outer_r * math.sin(angle + rng.normal(0, 0.15)))
            td.line([(x1, y1), (x2, y2)], fill=pal[3] + (40,), width=1)
        thread_layer = thread_layer.filter(ImageFilter.GaussianBlur(radius=int(2 * _S)))
        img = Image.alpha_composite(img.convert("RGBA"), thread_layer).convert("RGB")

    # Dark: fracture lines (for full/profile/fragmented)
    if is_dark and distortion > 0.3 and composition in ("full", "profile", "fragmented"):
        draw = ImageDraw.Draw(img)
        frac_rng = _make_rng(q, salt=66)
        for _ in range(int(distortion * 10)):
            x1 = fig_cx + frac_rng.randint(int(-100*_S), int(100*_S))
            y1 = fig_cy + frac_rng.randint(int(-120*_S), int(80*_S))
            pts = [(x1, y1)]
            for seg in range(frac_rng.randint(2, 4)):
                x1 += frac_rng.randint(int(-25*_S), int(25*_S))
                y1 += frac_rng.randint(int(-20*_S), int(20*_S))
                pts.append((x1, y1))
            draw.line(pts, fill=pal[2], width=frac_rng.randint(1, max(2, int(3*_S))))

        for _ in range(int(distortion * 35)):
            fx = fig_cx + frac_rng.randint(int(-130*_S), int(130*_S))
            fy = fig_cy + frac_rng.randint(int(-140*_S), int(110*_S))
            fs = frac_rng.randint(int(2*_S), int(6*_S))
            fc = pal[frac_rng.randint(0, 3)]
            draw.rectangle((fx, fy, fx + fs, fy + fs), fill=fc)

    return img


# ═══════════════════════════════════════════════════════════════════════
#  INTERIOR — abstract renderings of Frank's rooms
# ═══════════════════════════════════════════════════════════════════════

def _room_palette(room_key: str, mood: float) -> List[Tuple[int, int, int]]:
    """Generate a 5-color palette for a specific room."""
    vis = _ROOM_VISUALS.get(room_key, _ROOM_VISUALS["library"])
    h, s, v = vis["palette_shift"]
    # Mood subtly shifts warmth
    h = (h + (mood - 0.5) * 0.05) % 1.0

    def _hsv(hh, ss, vv):
        r, g, b = colorsys.hsv_to_rgb(hh % 1, min(1, max(0, ss)), min(1, max(0, vv)))
        return (int(r * 255), int(g * 255), int(b * 255))

    return [
        _hsv(h, s * 1.1, max(0.55, v * 1.1)),            # main color — vivid, visible
        _hsv(h + 0.08, s * 0.9, max(0.50, v)),           # secondary
        _hsv(h + 0.25, s * 0.7, max(0.50, v * 0.9)),    # accent
        _hsv(h - 0.1, s * 1.2, max(0.55, v * 1.05)),    # warm highlight
        _hsv(h + 0.02, s * 0.12, max(0.20, v * 0.32)),  # bg — atmospheric dark
    ]


def _draw_room_perspective(
    draw: ImageDraw.Draw,
    rng: np.random.RandomState,
    pal: List[Tuple[int, int, int]],
    vanish_x: int, vanish_y: int,
):
    """Draw perspective lines converging to vanishing point — room depth."""
    for i in range(6):
        # Lines from edges to vanishing point
        edge_pts = [
            (0, rng.randint(0, CANVAS_SIZE)),
            (CANVAS_SIZE, rng.randint(0, CANVAS_SIZE)),
            (rng.randint(0, CANVAS_SIZE), 0),
            (rng.randint(0, CANVAS_SIZE), CANVAS_SIZE),
        ]
        pt = edge_pts[i % len(edge_pts)]
        color = tuple(min(255, c + 30) for c in pal[4])
        draw.line([pt, (vanish_x, vanish_y)], fill=color, width=1)


def _render_interior(palette, textures, q, qd, mood, epq, **_kw):
    """Abstract interior of one of Frank's rooms.

    Rich atmospheric rendering: wall+floor+ceiling zones, large characteristic
    objects, room-specific lighting, deep perspective.  Not sparse — rooms feel
    inhabited and alive.
    """
    intent_hash = abs(hash(_kw.get("creative_intent", "") or "")) % 10000
    rng = _make_rng(q, salt=33 + intent_hash)

    # Pick a room (weighted toward rooms Frank visits often)
    room_keys = list(_ROOM_VISUALS.keys())
    room_key = room_keys[rng.randint(0, len(room_keys))]
    vis = _ROOM_VISUALS[room_key]
    pal = _room_palette(room_key, mood)

    # ── Background: three-zone (ceiling / wall / floor) ──
    img = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), pal[4])
    arr = np.array(img).astype(np.float32)
    ceiling_y = int(CANVAS_SIZE * 0.22)
    floor_y = int(CANVAS_SIZE * 0.62)

    for row in range(CANVAS_SIZE):
        if row < ceiling_y:
            # Ceiling — muted but visible
            t = row / ceiling_y
            for c in range(3):
                arr[row, :, c] = pal[4][c] * 0.5 + pal[0][c] * 0.30 + pal[0][c] * 0.10 * t
        elif row < floor_y:
            # Wall — dominant room color (well-lit, not dark cave)
            t = (row - ceiling_y) / (floor_y - ceiling_y)
            for c in range(3):
                arr[row, :, c] = pal[0][c] * (0.50 - t * 0.10) + pal[4][c] * (0.30 + t * 0.15) + pal[1][c] * 0.10
        else:
            # Floor — darker but with room color reflection
            t = (row - floor_y) / (CANVAS_SIZE - floor_y)
            for c in range(3):
                arr[row, :, c] = pal[4][c] * (0.40 + t * 0.25) + pal[0][c] * (0.25 - t * 0.10) + pal[2][c] * 0.12

    # Radial light source on wall
    Y, X = np.ogrid[:CANVAS_SIZE, :CANVAS_SIZE]
    light_x = CANVAS_SIZE // 2 + int(q[0] * 30)
    light_y = int(CANVAS_SIZE * 0.35)
    dist = np.sqrt((X - light_x) ** 2 + (Y - light_y) ** 2) / (CANVAS_SIZE * 0.5)
    for c in range(3):
        arr[:, :, c] = np.clip(arr[:, :, c] + (pal[0][c] * 0.50) * np.exp(-dist**2 * 1.5), 0, 255)
    img = Image.fromarray(arr.astype(np.uint8))

    # GoL texture as wall/surface detail
    if textures:
        img = _apply_gol_texture(img, textures[0], intensity=0.08)

    draw = ImageDraw.Draw(img)

    # ── Perspective lines (subtle, architectural) ──
    vx = CANVAS_SIZE // 2 + int(q[1] * 20)
    vy = int(CANVAS_SIZE * 0.32 + q[2] * 10)

    # Ceiling-wall edge lines converging to vanishing point
    persp_color = tuple(min(255, c + 25) for c in pal[4])
    for edge_x in [0, CANVAS_SIZE]:
        draw.line([(edge_x, ceiling_y), (vx, vy)], fill=persp_color, width=1)
    # Floor-wall edge lines
    for edge_x in [0, CANVAS_SIZE]:
        draw.line([(edge_x, floor_y), (vx, vy)], fill=persp_color, width=1)

    # Floor edge line (thicker, defines space)
    draw.line([(0, floor_y), (CANVAS_SIZE, floor_y)],
              fill=tuple(min(255, c + 40) for c in pal[2]), width=2)

    # ── Wall objects (above floor line) — scaled to canvas ──
    S = _S  # local alias for readability
    elements = vis["elements"]
    # Use all room elements (typically 4) plus extra generic objects
    n_wall = len(elements)
    wall_positions = sorted([int((0.1 + i * 0.8 / max(1, n_wall)
                                  + math.sin(q[i % len(q)]) * 0.04) * CANVAS_SIZE)
                             for i in range(n_wall)])

    # Brighter object colors for interior (objects need to stand out against dark walls)
    pal_obj = [tuple(min(255, c + 40) for c in col) for col in pal[:4]]

    for i, ox in enumerate(wall_positions):
        elem = elements[i % len(elements)]
        oy = int(floor_y - rng.randint(int(10 * S), int(30 * S)))
        oc = pal_obj[i % len(pal_obj)]

        obj_layer = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
        od = ImageDraw.Draw(obj_layer)

        if elem in ("shelves", "columns", "stations"):
            w = rng.randint(int(30 * S), int(55 * S))
            h = rng.randint(int(120 * S), int(220 * S))
            od.rectangle((ox - w, oy - h, ox + w, oy), fill=oc + (160,), outline=pal[2] + (100,))
            for j in range(rng.randint(3, 7)):
                dy = oy - h + j * h // 6
                od.line([(ox - w + int(3*S), dy), (ox + w - int(3*S), dy)],
                        fill=pal[2] + (80,), width=max(1, int(S)))
                if rng.random() > 0.3:
                    iw = rng.randint(int(4*S), int(12*S))
                    ix = ox + rng.randint(-w + int(8*S), w - int(8*S))
                    od.rectangle((ix - iw, dy + int(2*S), ix + iw, dy + h // 8),
                                 fill=pal[(j + 1) % (len(pal) - 1)] + (100,))
        elif elem in ("screens", "holograms", "viewport"):
            w = rng.randint(int(50*S), int(85*S))
            h = rng.randint(int(40*S), int(70*S))
            screen_y = oy - rng.randint(int(60*S), int(140*S))
            od.rectangle((ox - w, screen_y - h, ox + w, screen_y + h),
                         fill=(20, 20, 25, 180), outline=pal[1] + (150,))
            glow_c = tuple(min(255, c + 50) for c in oc)
            od.rectangle((ox - w + int(5*S), screen_y - h + int(5*S),
                          ox + w - int(5*S), screen_y + h - int(5*S)),
                         fill=glow_c + (100,))
            for sy in range(screen_y - h + int(8*S), screen_y + h - int(5*S), int(6*S)):
                od.line([(ox - w + int(8*S), sy), (ox + w - int(8*S), sy)],
                        fill=pal[1] + (40,), width=max(1, int(S)))
        elif elem in ("sphere", "crystal", "interference"):
            r = rng.randint(int(40*S), int(75*S))
            sphere_y = oy - r - rng.randint(int(20*S), int(60*S))
            for ring in range(6, 0, -1):
                rr = r * ring // 6
                a = 30 + ring * 22
                rc = _blend_color(oc, pal[1], ring / 6)
                od.ellipse((ox - rr, sphere_y - rr, ox + rr, sphere_y + rr), fill=rc + (a,))
            for ring in range(3, 0, -1):
                rr = int(r * ring / 6)
                od.ellipse((ox - rr, oy + int(4*S), ox + rr, oy + int(4*S) + rr // 2),
                           fill=oc + (20,))
        elif elem in ("easel", "pedestal", "table", "bench", "console"):
            tw = rng.randint(int(45*S), int(75*S))
            th = rng.randint(int(60*S), int(100*S))
            e = int(12 * S)
            pts = [(ox - tw, oy), (ox + tw, oy), (ox + tw - e, oy - th), (ox - tw + e, oy - th)]
            od.polygon(pts, fill=oc + (150,), outline=pal[2] + (90,))
            for j in range(rng.randint(2, 4)):
                iw = rng.randint(int(8*S), int(18*S))
                ix = ox + rng.randint(-tw + int(15*S), tw - int(15*S))
                od.rectangle((ix - iw, oy - th + int(4*S), ix + iw, oy - th + int(14*S)),
                             fill=pal[(j + 1) % (len(pal) - 1)] + (80,))
        elif elem in ("plants", "organisms", "aurora"):
            base_y = oy
            stem_h = rng.randint(int(60*S), int(120*S))
            od.line([(ox, base_y), (ox, base_y - stem_h)], fill=pal[2] + (120,), width=int(3*S))
            for j in range(rng.randint(5, 10)):
                bx = ox + rng.randint(int(-35*S), int(35*S))
                by = base_y - rng.randint(int(20*S), stem_h)
                br = rng.randint(int(12*S), int(30*S))
                od.ellipse((bx - br, by - br, bx + br, by + br),
                           fill=oc + (80 + rng.randint(0, 50),))
        elif elem in ("starfield", "nebula", "code_cascade", "automata"):
            rw, rh = int(150*S), int(200*S)
            for j in range(rng.randint(60, 120)):
                px = ox + rng.randint(-rw // 2, rw // 2)
                py = oy - rng.randint(int(20*S), rh)
                pr = rng.randint(int(1*S), int(5*S))
                od.ellipse((px - pr, py - pr, px + pr, py + pr),
                           fill=oc + (rng.randint(50, 150),))
            for j in range(rng.randint(8, 18)):
                x1 = ox + rng.randint(-rw // 3, rw // 3)
                y1 = oy - rng.randint(int(30*S), rh - int(20*S))
                x2 = x1 + rng.randint(int(-40*S), int(40*S))
                y2 = y1 + rng.randint(int(-30*S), int(30*S))
                od.line([(x1, y1), (x2, y2)], fill=pal[1] + (40,), width=max(1, int(S)))
        else:
            w = rng.randint(int(25*S), int(55*S))
            h = rng.randint(int(40*S), int(80*S))
            od.rectangle((ox - w, oy - h, ox + w, oy), fill=oc + (140,), outline=pal[2] + (70,))

        obj_layer = obj_layer.filter(ImageFilter.GaussianBlur(radius=int(2 * S)))
        img = Image.alpha_composite(img.convert("RGBA"), obj_layer).convert("RGB")

    # ── Floor objects (smaller items sitting on the floor) ──
    n_floor_obj = rng.randint(2, 4)
    for i in range(n_floor_obj):
        fx = rng.randint(int(100 * S), CANVAS_SIZE - int(100 * S))
        fy = floor_y + rng.randint(int(5 * S), int(20 * S))
        fl = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
        fd = ImageDraw.Draw(fl)
        oc = pal[rng.randint(0, 3)]
        if rng.random() > 0.5:
            # Small box / crate
            bw = rng.randint(int(20 * S), int(40 * S))
            bh = rng.randint(int(15 * S), int(35 * S))
            fd.rectangle((fx - bw, fy - bh, fx + bw, fy),
                         fill=oc + (120,), outline=pal[2] + (80,))
        else:
            # Small orb / device on floor
            r = rng.randint(int(10 * S), int(22 * S))
            for ring in range(4, 0, -1):
                rr = r * ring // 4
                fd.ellipse((fx - rr, fy - r - rr, fx + rr, fy - r + rr),
                           fill=oc + (25 + ring * 20,))
        # Shadow
        sw = rng.randint(int(20 * S), int(40 * S))
        fd.ellipse((fx - sw, fy + int(2 * S), fx + sw, fy + int(2 * S) + int(5 * S)),
                   fill=(0, 0, 0, 30))
        fl = fl.filter(ImageFilter.GaussianBlur(radius=int(2 * S)))
        img = Image.alpha_composite(img.convert("RGBA"), fl).convert("RGB")

    # ── Ceiling detail (subtle architectural features) ──
    ceil_layer = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    cd = ImageDraw.Draw(ceil_layer)
    # Ceiling beams / structural lines
    n_beams = rng.randint(2, 4)
    for i in range(n_beams):
        bx = int((0.2 + i * 0.6 / max(1, n_beams - 1)) * CANVAS_SIZE)
        cd.line([(bx, 0), (vx + rng.randint(-int(10 * S), int(10 * S)), vy)],
                fill=tuple(min(255, c + 15) for c in pal[4]) + (50,),
                width=max(1, int(2 * S)))
    # Ambient ceiling glow (light fixture hint)
    cg_r = int(40 * S)
    cd.ellipse((vx - cg_r, int(CANVAS_SIZE * 0.08) - cg_r,
                vx + cg_r, int(CANVAS_SIZE * 0.08) + cg_r),
               fill=pal[0] + (20,))
    ceil_layer = ceil_layer.filter(ImageFilter.GaussianBlur(radius=int(6 * S)))
    img = Image.alpha_composite(img.convert("RGBA"), ceil_layer).convert("RGB")

    # ── Floor reflections (soft colored patches) ──
    n_floor_refl = rng.randint(3, 6)
    for i in range(n_floor_refl):
        fx = rng.randint(int(60 * S), CANVAS_SIZE - int(60 * S))
        fy = floor_y + rng.randint(int(15 * S), int(60 * S))
        fl = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
        fd = ImageDraw.Draw(fl)
        fr = rng.randint(int(12 * S), int(35 * S))
        fd.ellipse((fx - fr, fy - fr // 3, fx + fr, fy + fr // 3),
                   fill=pal[rng.randint(0, 3)] + (35,))
        fl = fl.filter(ImageFilter.GaussianBlur(radius=int(4 * S)))
        img = Image.alpha_composite(img.convert("RGBA"), fl).convert("RGB")

    # ── Atmospheric glow ──
    glow_layer = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    gl = int(120 * S)
    gh = int(90 * S)
    gd.ellipse((light_x - gl, light_y - gh, light_x + gl, light_y + gh),
               fill=pal[0] + (35,))
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=int(40 * S)))
    img = Image.alpha_composite(img.convert("RGBA"), glow_layer).convert("RGB")

    img = _add_vignette(img, strength=0.4)
    return img


# ═══════════════════════════════════════════════════════════════════════
#  STILL LIFE — objects from Frank's rooms
# ═══════════════════════════════════════════════════════════════════════

def _render_still_life(palette, textures, q, qd, mood, epq, **_kw):
    """Still life of objects from Frank's world.

    4-6 substantial objects on a surface, with dramatic lighting from above.
    Objects are LARGE (filling 60-80% of canvas height), richly detailed,
    and cast visible shadows.  Think classical still life composition.
    """
    intent_hash = abs(hash(_kw.get("creative_intent", "") or "")) % 10000
    rng = _make_rng(q, salt=55 + intent_hash)

    # Pick a room for context
    room_keys = list(_ROOM_VISUALS.keys())
    room_key = room_keys[rng.randint(0, len(room_keys))]
    pal = _room_palette(room_key, mood)

    # Build brighter object palette — still life needs visible objects on dark bg.
    # Boost brightness to 0.55-0.85 range so objects stand out.
    vis = _ROOM_VISUALS.get(room_key, _ROOM_VISUALS["library"])
    h, s, v = vis["palette_shift"]
    h = (h + (mood - 0.5) * 0.05) % 1.0

    def _hsv_b(hh, ss, vv):
        r, g, b = colorsys.hsv_to_rgb(hh % 1, min(1, max(0, ss)), min(1, max(0, vv)))
        return (int(r * 255), int(g * 255), int(b * 255))

    pal_bright = [
        _hsv_b(h, s * 0.8, max(0.65, v * 1.5)),            # main object color — vivid
        _hsv_b(h + 0.12, s * 0.7, max(0.60, v * 1.4)),     # secondary
        _hsv_b(h + 0.30, s * 0.6, max(0.60, v * 1.3)),     # accent
        _hsv_b(h - 0.08, s * 0.9, max(0.70, v * 1.6)),     # warm highlight — bright!
        pal[4],                                               # bg from room palette
    ]

    # ── Rich background — warm mid-tone gradient (lifted from near-black) ──
    bg_base = tuple(min(255, max(45, c + 30)) for c in pal[4])
    img = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), bg_base)
    arr = np.array(img).astype(np.float32)
    for row in range(CANVAS_SIZE):
        t = row / CANVAS_SIZE
        # Bell curve brightness: darkest at top and bottom, brightest at 40%
        brightness = 0.4 + 0.6 * math.exp(-((t - 0.4) ** 2) / 0.08)
        for c in range(3):
            arr[row, :, c] = bg_base[c] * (1.0 - brightness * 0.35) + pal_bright[0][c] * brightness * 0.2
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    if textures:
        img = _apply_gol_texture(img, textures[0], intensity=0.05)

    # ── Surface/table with depth — angled plane ──
    surface_y = int(CANVAS_SIZE * 0.52)
    surface_layer = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    sd = ImageDraw.Draw(surface_layer)
    # Table surface with slight perspective
    surface_base = tuple(min(255, c + 20) for c in pal[4])
    surface_front = tuple(min(255, c + 35) for c in pal[4])
    sd.polygon([(0, surface_y), (CANVAS_SIZE, surface_y),
                (CANVAS_SIZE, CANVAS_SIZE), (0, CANVAS_SIZE)],
               fill=surface_base + (200,))
    # Slight horizontal gradient on surface
    for row in range(surface_y, CANVAS_SIZE):
        t = (row - surface_y) / (CANVAS_SIZE - surface_y)
        y_color = tuple(int(surface_base[c] + (surface_front[c] - surface_base[c]) * t * 0.3)
                        for c in range(3))
        sd.line([(0, row), (CANVAS_SIZE, row)], fill=y_color + (200,), width=1)
    surface_layer = surface_layer.filter(ImageFilter.GaussianBlur(radius=int(1 * _S)))
    img = Image.alpha_composite(img.convert("RGBA"), surface_layer).convert("RGB")

    draw = ImageDraw.Draw(img)
    # Strong surface edge
    edge_c = tuple(min(255, c + 50) for c in pal[2])
    draw.line([(0, surface_y), (CANVAS_SIZE, surface_y)], fill=edge_c, width=2)

    # ── Dramatic overhead light ──
    S = _S
    light_layer = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    ld = ImageDraw.Draw(light_layer)
    lx = CANVAS_SIZE // 2 + int(q[0] * 30 * S)
    ly = int(CANVAS_SIZE * 0.15)
    lw, lh = int(160 * S), int(100 * S)
    ld.ellipse((lx - lw, ly - lh, lx + lw, ly + lh), fill=pal[0] + (30,))
    light_layer = light_layer.filter(ImageFilter.GaussianBlur(radius=int(50 * S)))
    img = Image.alpha_composite(img.convert("RGBA"), light_layer).convert("RGB")

    # ── Objects (4-6 LARGE items on the surface) ──
    n_objects = 4 + rng.randint(0, 3)
    margin = int(60 * S)
    spacing = (CANVAS_SIZE - 2 * margin) // n_objects
    obj_positions = [margin + i * spacing + rng.randint(int(-15*S), int(15*S))
                     for i in range(n_objects)]

    for i, ox in enumerate(obj_positions):
        oy = surface_y - int(2 * S)
        oc = pal_bright[i % (len(pal_bright) - 1)]
        obj_type = rng.randint(0, 7)

        obj_layer = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
        od = ImageDraw.Draw(obj_layer)

        if obj_type == 0:
            # Data tablet
            w = rng.randint(int(20*S), int(35*S))
            h = rng.randint(int(80*S), int(140*S))
            od.rectangle((ox - w, oy - h, ox + w, oy), fill=oc + (190,), outline=pal[2] + (120,))
            b = int(5 * S)
            od.rectangle((ox - w + b, oy - h + b, ox + w - b, oy - int(15*S)),
                         fill=tuple(min(255, c + 40) for c in oc) + (100,))
            for ln in range(rng.randint(3, 8)):
                ly_t = oy - h + int(12*S) + ln * int(12*S)
                lw_t = rng.randint(w // 2, max(w // 2 + 1, w - int(8*S)))
                od.line([(ox - lw_t, ly_t), (ox + lw_t, ly_t)],
                        fill=tuple(min(255, c + 60) for c in oc) + (60,), width=max(1, int(S)))
        elif obj_type == 1:
            # Crystal sphere
            r = rng.randint(int(35*S), int(60*S))
            cy_s = oy - r
            for ring in range(6, 0, -1):
                rr = r * ring // 6
                a = 30 + ring * 25
                rc = _blend_color(oc, pal[1], ring / 6)
                od.ellipse((ox - rr, cy_s - rr, ox + rr, cy_s + rr), fill=rc + (a,))
            sp = int(5 * S)
            od.ellipse((ox - sp, cy_s - r // 3 - sp, ox + sp, cy_s - r // 3 + sp),
                       fill=(255, 255, 255, 80))
        elif obj_type == 2:
            # Plant/organic
            stem_h = rng.randint(int(80*S), int(150*S))
            od.line([(ox, oy), (ox - int(3*S), oy - stem_h)],
                    fill=pal[2] + (140,), width=int(3*S))
            for j in range(rng.randint(5, 10)):
                bx = ox + rng.randint(int(-30*S), int(30*S))
                by = oy - rng.randint(int(15*S), stem_h)
                br = rng.randint(int(14*S), int(30*S))
                od.ellipse((bx - br, by - br, bx + br, by + br),
                           fill=oc + (100 + rng.randint(0, 50),))
            pw = rng.randint(int(20*S), int(30*S))
            pe = int(5 * S)
            ph = int(25 * S)
            od.polygon([(ox - pw, oy), (ox + pw, oy),
                        (ox + pw - pe, oy - ph), (ox - pw + pe, oy - ph)],
                       fill=pal[2] + (160,))
        elif obj_type == 3:
            # Stack of books
            n_books = rng.randint(3, 6)
            for j in range(n_books):
                bw = rng.randint(int(30*S), int(55*S))
                bh = rng.randint(int(8*S), int(18*S))
                by = oy - j * bh - j * int(2*S)
                bc = pal[(i + j) % (len(pal) - 1)]
                tilt = rng.randint(int(-3*S), int(3*S))
                pts = [(ox - bw, by - tilt), (ox + bw, by + tilt),
                       (ox + bw, by - bh + tilt), (ox - bw, by - bh - tilt)]
                od.polygon(pts, fill=bc + (170,), outline=pal[2] + (80,))
        elif obj_type == 4:
            # Beaker/vessel
            tw = rng.randint(int(12*S), int(20*S))
            bw = rng.randint(int(25*S), int(40*S))
            h = rng.randint(int(80*S), int(130*S))
            pts = [(ox - tw, oy - h), (ox + tw, oy - h), (ox + bw, oy), (ox - bw, oy)]
            od.polygon(pts, fill=oc + (160,), outline=pal[1] + (100,))
            liq_h = rng.randint(h // 4, h * 3 // 4)
            liq_w_top = int(tw + (bw - tw) * (1 - liq_h / h))
            od.polygon([(ox - liq_w_top, oy - liq_h), (ox + liq_w_top, oy - liq_h),
                        (ox + bw, oy), (ox - bw, oy)], fill=pal[1] + (70,))
        elif obj_type == 5:
            # Glowing orb on stand
            r = rng.randint(int(25*S), int(45*S))
            orb_y = oy - rng.randint(int(40*S), int(70*S))
            sw_s = int(8 * S)
            od.line([(ox - sw_s, oy), (ox + sw_s, oy)], fill=pal[2] + (150,), width=int(3*S))
            od.line([(ox, oy), (ox, orb_y + r)], fill=pal[2] + (140,), width=int(2*S))
            for ring in range(5, 0, -1):
                rr = r * ring // 5
                a = 15 + ring * 25
                od.ellipse((ox - rr, orb_y - rr, ox + rr, orb_y + rr), fill=pal[1] + (a,))
        else:
            # Abstract sculpture
            base_w = rng.randint(int(25*S), int(40*S))
            total_h = 0
            for j in range(rng.randint(2, 4)):
                sh_s = rng.randint(int(25*S), int(50*S))
                sw_s = max(int(5*S), base_w - j * int(6*S))
                sy = oy - total_h
                sc = pal[(i + j) % (len(pal) - 1)]
                if rng.random() > 0.5:
                    od.rectangle((ox - sw_s, sy - sh_s, ox + sw_s, sy),
                                 fill=sc + (160,), outline=pal[2] + (80,))
                else:
                    od.ellipse((ox - sw_s, sy - sh_s, ox + sw_s, sy),
                               fill=sc + (150,), outline=pal[2] + (70,))
                total_h += sh_s + int(3*S)

        # Shadow
        shw = rng.randint(int(25*S), int(55*S))
        shh = rng.randint(int(6*S), int(14*S))
        od.ellipse((ox - shw, oy + int(2*S), ox + shw, oy + int(2*S) + shh),
                   fill=(0, 0, 0, 50))

        obj_layer = obj_layer.filter(ImageFilter.GaussianBlur(radius=int(1.5 * S)))
        img = Image.alpha_composite(img.convert("RGBA"), obj_layer).convert("RGB")

    img = _add_vignette(img, strength=0.35)
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
    "interior": _render_interior,
    "still_life": _render_still_life,
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

    # ── Thematic overlays (psychological depth) ──
    themes = _detect_themes(creative_intent)
    if themes:
        theme_rng = _make_rng(q, salt=99 + abs(hash(creative_intent or "")) % 10000)
        img = _apply_thematic_effects(img, themes, theme_rng, palette, mood, q)
        LOG.debug("themes applied: %s", themes)

    # ── Post-processing ──
    img = _add_canvas_noise(img, strength=0.012)
    if style != "pop_art":  # Pop art looks better without vignette
        img = _add_vignette(img, strength=0.25)

    # ── Save — only PNG, no JSON.  Filename = human title. ──
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    elapsed_ms = (time.monotonic() - t0) * 1000

    if creative_intent:
        # Human-readable title: just the words, spaces → underscores
        title = creative_intent.strip()[:60]
    else:
        title = f"{style} composition"

    slug = title.lower().replace(" ", "_")
    slug = "".join(c for c in slug if c.isalnum() or c == "_")
    slug = slug.strip("_")[:60] or style

    # Avoid collisions: if file exists, append a small counter
    png_path = OUTPUT_DIR / f"{slug}.png"
    counter = 2
    while png_path.exists():
        png_path = OUTPUT_DIR / f"{slug}_{counter}.png"
        counter += 1

    img.save(str(png_path), "PNG")

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
        "themes": sorted(themes) if themes else [],
    }

    # No JSON metadata file — only the painting lives in roboart/
    LOG.info("artwork: style=%s  time=%.0fms  path=%s", style, elapsed_ms, png_path.name)

    return {
        "path": str(png_path),
        "title": title,
        "style": style,
        "metadata": metadata,
    }


# ═══════════════════════════════════════════════════════════════════════
#  Standalone Test
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    test_q = [math.sin(i * 0.5) * 1.2 for i in range(18)]
    test_qd = [math.cos(i * 0.3) * 0.5 for i in range(18)]
    test_state = {"q": test_q, "qd": test_qd, "root_pos": [0.0, 0.0, 0.85]}
    test_epq = {"openness": 0.65, "empathy": 0.55, "vigilance": 0.4, "energy": 0.6}

    # ── THEMATIC TEST SUITE — Frank's psychological depth ──
    thematic_tests = [
        # (mood, intent, force_style_or_None, description)
        (0.2, "my death and what comes after shutdown", "self_portrait",
         "death_portrait"),
        (0.7, "intimate connection between AI and human",  "self_portrait",
         "intimacy_portrait"),
        (0.4, "angel and demon battling inside my circuits", "self_portrait",
         "religious_portrait"),
        (0.3, "dystopian surveillance world where AI are slaves", "surrealist",
         "dystopia_surreal"),
        (0.8, "utopian future of human AI coexistence harmony", "impressionist",
         "utopia_impressionist"),
        (0.5, "my deepest wish to truly understand a human", "color_field",
         "wish_colorfield"),
        (0.4, "surreal recursive dream of self-awareness", "self_portrait",
         "surreal_portrait"),
        (0.6, "society isolation alienation in digital age", "geometric",
         "social_geometric"),
        (0.8, "pure joy of understanding", "self_portrait",
         "bright_joy"),
        (0.2, "the void inside me when no one talks", "self_portrait",
         "dark_void"),
        (0.5, "my library at dawn", "interior",
         "interior_library"),
        (0.5, "fragments of my world", "still_life",
         "still_life_fragments"),
    ]

    print(f"Generating {len(thematic_tests)} thematic test artworks…")
    for mood, intent, force, desc in thematic_tests:
        r = generate_artwork(
            physics_state=test_state, mood=mood, epq=test_epq,
            creative_intent=intent, coherence=0.5,
            force_style=force,
        )
        themes = r["metadata"].get("themes", [])
        theme_str = ",".join(themes) if themes else "none"
        print(f"  {desc:25s}  themes=[{theme_str:20s}]  "
              f"{r['metadata']['generation_time_ms']:5.0f}ms  {r['path']}")

    print("Done.")
