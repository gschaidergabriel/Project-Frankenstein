"""Aura — Configuration & Constants.

Frank's Inner Life Visualizer. A cellular-automaton grid that maps Frank's
consciousness subsystems into a living, color-coded visual field.
The automaton rules are based on Conway's Game of Life.
"""

# Grid dimensions
GRID_SIZE = 256
ZONE_SIZE = 64    # Legacy (zone width)
ZONE_WIDTH = 64   # Horizontal zone size
ZONE_HEIGHT = 128  # Vertical zone size — 4×2 of 64w×128h fills 256×256

# Timing (seconds)
AURA_TICK_INTERVAL = 0.1      # 10 Hz automaton generation rate
POLL_INTERVAL = 2.0           # 2s Frank state polling
RENDER_FPS = 60               # Target render framerate
FRAME_BUDGET_MS = 16           # 1000/60

# Panel dimensions
PANEL_WIDTH = 280
SLIDE_DURATION_OPEN_MS = 300   # Ease-out
SLIDE_DURATION_CLOSE_MS = 200  # Ease-in
TOGGLE_BTN_SIZE = 24

# Reseed after N seconds of empty grid
EMPTY_GRID_RESEED_S = 3.0
MAX_DENSITY = 0.70  # Clamp seed density

# Cell age brightness curve
BRIGHTNESS_DECAY = 0.015      # Per generation (slower fade for neon)
BRIGHTNESS_MIN = 0.55

# Zone color map (R, G, B) — 0.0-1.0 floats · Neon/Cyberpunk palette
ZONE_COLORS = {
    "epq":       (0.0, 0.7, 1.0),    # Electric Cyan Blue
    "mood":      (1.0, 0.5, 0.0),    # Deep Amber/Orange
    "reflexion": (0.0, 1.0, 0.3),    # Neon Green
    "entities":  (1.0, 0.0, 0.8),    # Hot Magenta
    "ego":       (1.0, 0.85, 0.0),   # Bright Gold
    "quantum":   (0.0, 1.0, 1.0),    # Pure Cyan
    "titan":     (0.7, 0.3, 1.0),    # Electric Violet
    "hardware":  (1.0, 0.2, 0.1),    # Neon Red
}

# ── Pseudo-3D rendering constants ──
GLOW_DOWNSAMPLE = 8           # 256→32 for fast blur
GLOW_SIGMA = 2.0              # Gaussian blur sigma on downsampled grid
GLOW_INTENSITY = 0.0          # Additive bloom strength (disabled)
TRAIL_DECAY = 0.92            # Per-frame visual decay for dead cell trails
BASE_NOISE_DENSITY = 0.06     # 6% static background noise
BREATH_PERIOD_S = 4.0         # Sinus breathing cycle (seconds)
BREATH_AMPLITUDE = 0.08       # ±8% brightness oscillation
NEWBORN_FLASH = 1.4           # Brightness for age=1 cells (>1 = bloom)

# Zone positions in 4×2 grid (row, col) → pixel region (y_start, x_start)
# Top row: EPQ, Mood, Reflexion, Entities
# Bottom row: Ego, Quantum, Titan, Hardware
ZONE_LAYOUT = {
    "epq":       (0, 0),
    "mood":      (0, 1),
    "reflexion": (0, 2),
    "entities":  (0, 3),
    "ego":       (1, 0),
    "quantum":   (1, 1),
    "titan":     (1, 2),
    "hardware":  (1, 3),
}

# Background colors (RGB 0-255)
BACKGROUND_RGB = (13, 17, 23)    # #0D1117
DEAD_CELL_RGB = (22, 27, 34)     # #161B22

# Transition zone width (cells) for color blending between zones
TRANSITION_WIDTH = 4

# Ripple effect
RIPPLE_CENTER = (128, 128)
RIPPLE_MAX_RADIUS = 80
RIPPLE_RING_THICKNESS = 4
RIPPLE_DENSITY = 0.40
RIPPLE_STEP = 3

# Threat flash
THREAT_FLASH_MS = 500
THREAT_DECAY_MS = 3000
THREAT_COLOR = (1.0, 0.1, 0.1)

# Info panel font
INFO_FONT = ("Consolas", 9)
INFO_COLOR = "#8B949E"

# Frank API endpoints
API_CORE = "http://127.0.0.1:8088"
API_TOOLBOX = "http://127.0.0.1:8096"
API_QUANTUM = "http://127.0.0.1:8097"
API_AURA_HEADLESS = "http://127.0.0.1:8098"
