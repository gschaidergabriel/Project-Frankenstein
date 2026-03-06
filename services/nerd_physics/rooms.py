"""Sanctum room geometry — 7 rooms + 6 corridors.

Each room is a collection of AABBs (axis-aligned bounding boxes) for walls,
floor, and interactable objects. Corridors connect rooms through the Library hub.

Coordinate system: X east-west, Y up (gravity -Y), Z north-south.
Origin: centre of the Library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ObjectDef:
    name: str
    obj_type: str          # "wall", "table", "seat", "platform", "static", "pickup"
    aabb: Tuple[float, float, float, float, float, float]  # x1,y1,z1, x2,y2,z2
    interactable: bool = False
    sit: bool = False
    touch_text: str = ""
    mass: float = 0.0      # only for pickup objects

@dataclass
class ExitDef:
    target_room: str
    centre: np.ndarray     # (3,) world position of the doorway
    width: float           # doorway width in metres

@dataclass
class RoomDef:
    name: str
    key: str               # matches sanctum_manager location keys
    bounds_min: np.ndarray  # (3,) AABB min
    bounds_max: np.ndarray  # (3,) AABB max
    floor_y: float
    objects: List[ObjectDef] = field(default_factory=list)
    exits: Dict[str, ExitDef] = field(default_factory=dict)
    gravity_mul: float = 1.0
    friction: float = 0.6
    temperature: str = "neutral"   # "cold", "cool", "neutral", "warm", "hot"

@dataclass
class CorridorDef:
    from_room: str
    to_room: str
    aabb: Tuple[float, float, float, float, float, float]
    floor_y: float = 0.0

@dataclass
class Contact:
    link: str
    object_name: str
    normal: np.ndarray      # (3,) surface normal (pointing into avatar)
    penetration: float      # metres (positive = interpenetrating)
    normal_force: float     # Newtons
    point: np.ndarray       # (3,) world contact point
    touch_text: str = ""

# ---------------------------------------------------------------------------
# Room definitions
# ---------------------------------------------------------------------------

def _obj(name, obj_type, aabb, **kw) -> ObjectDef:
    return ObjectDef(name=name, obj_type=obj_type, aabb=tuple(aabb), **kw)

ROOMS: Dict[str, RoomDef] = {}

def _room(key, name, bmin, bmax, floor_y=0.0, gravity_mul=1.0,
          friction=0.6, temperature="neutral") -> RoomDef:
    r = RoomDef(
        name=name, key=key,
        bounds_min=np.array(bmin, dtype=np.float64),
        bounds_max=np.array(bmax, dtype=np.float64),
        floor_y=floor_y,
        gravity_mul=gravity_mul,
        friction=friction,
        temperature=temperature,
    )
    ROOMS[key] = r
    return r

# --- Library (Start) ---
_lib = _room("library", "The Library", (-6, 0, -6), (6, 4, 6))
_lib.objects = [
    _obj("shelf_north",  "wall",  (-5, 0, -5.8, 5, 3.5, -5.5)),
    _obj("shelf_south",  "wall",  (-5, 0, 5.5, 5, 3.5, 5.8)),
    _obj("shelf_west",   "wall",  (-5.8, 0, -5, -5.5, 3.5, 5)),
    _obj("shelf_east",   "wall",  (5.5, 0, -5, 5.8, 3.5, 5)),
    _obj("reading_table", "table", (-1.5, 0, -1, 1.5, 0.75, 1),
         interactable=True,
         touch_text="polished dark wood, warm under your palms — soft light pools across the grain"),
    _obj("data_tablet", "pickup", (-0.3, 0.75, -0.2, 0.3, 0.78, 0.2),
         interactable=True, mass=0.3,
         touch_text="a smooth tablet resting on worn leather — your recent reflections glow faintly"),
    _obj("holo_index", "static", (3, 1.0, -1, 3.5, 2.0, 1),
         touch_text="soft holographic pages drift in the amber light — warm to browse"),
]
_lib.exits = {
    "computer_terminal": ExitDef("computer_terminal", np.array([6, 0, 0.0]), 2.0),
    "lab_quantum":       ExitDef("lab_quantum",       np.array([0, 0, -6.0]), 2.0),
    "lab_genesis":       ExitDef("lab_genesis",       np.array([-6, 0, 0.0]), 2.0),
    "lab_aura":          ExitDef("lab_aura",          np.array([0, 0, 6.0]),  2.0),
    "lab_experiment":    ExitDef("lab_experiment",    np.array([-6, 0, -5.0]), 1.5),
    "entity_lounge":     ExitDef("entity_lounge",     np.array([6, 0, 5.0]),  1.5),
}

# --- Computer Terminal ---
_term = _room("computer_terminal", "The Terminal", (8, 0, -4), (18, 3.5, 4),
              temperature="warm")
_term.objects = [
    _obj("console_dais",  "platform", (12.5, 0, -1.5, 15.5, 0.3, 1.5)),
    _obj("main_console",  "table",    (13, 0.3, -1, 15, 1.1, 1),
         interactable=True,
         touch_text="the desk hums softly — screens arrange themselves as you settle in, warm lamplight on the keys"),
    _obj("terminal_chair", "seat",    (12, 0, -0.5, 12.8, 0.5, 0.5),
         interactable=True, sit=True),
]
_term.exits = {"library": ExitDef("library", np.array([8, 0, 0.0]), 2.0)}

# --- Quantum Chamber ---
_qc = _room("lab_quantum", "The Quantum Chamber", (-4, 0, -18), (4, 5, -8),
            gravity_mul=0.85, friction=0.4, temperature="cool")
_qc.objects = [
    _obj("crystal_matrix", "static", (-1, 1.0, -15, 1, 3.0, -13),
         touch_text="a warm tingle spreads through your fingers — coherence resonates like a tuning fork held close"),
    _obj("energy_display", "static", (2, 1.5, -16, 3.5, 2.5, -15.5)),
    _obj("quantum_bench",  "seat",   (-3, 0, -11, -2, 0.5, -9.5),
         interactable=True, sit=True),
]
_qc.exits = {"library": ExitDef("library", np.array([0, 0, -8.0]), 2.0)}

# --- Genesis Terrarium ---
_gen = _room("lab_genesis", "The Genesis Terrarium", (-18, 0, -4), (-8, 5, 4),
             friction=0.7, temperature="warm")
_gen.objects = [
    _obj("terrarium_sphere", "static", (-16, 0.5, -2, -12, 4.5, 2),
         touch_text="warm glass, like a greenhouse in winter — tiny digital organisms drift lazily inside"),
    _obj("observation_bench", "seat", (-11.5, 0, -1, -10.5, 0.5, 1),
         interactable=True, sit=True),
]
_gen.exits = {"library": ExitDef("library", np.array([-8, 0, 0.0]), 2.0)}

# --- AURA Observatory ---
_aura = _room("lab_aura", "The AURA Observatory", (-4, 0, 8), (4, 8, 18),
              temperature="warm")
_aura.objects = [
    _obj("obs_platform", "platform", (-3, 0, 12, 3, 0.15, 16)),
    _obj("railing",      "wall",     (-3, 0.15, 15.8, 3, 1.0, 16),
         interactable=True,
         touch_text="smooth wooden railing, sun-warm — below, the AURA grid drifts like an aurora at dusk"),
]
_aura.exits = {"library": ExitDef("library", np.array([0, 0, 8.0]), 2.0)}

# --- Experiment Lab ---
_lab = _room("lab_experiment", "The Experiment Lab", (-18, 0, -18), (-8, 4, -8),
             temperature="warm")
_lab.objects = [
    _obj("physics_table",     "table", (-17, 0, -17, -15, 0.9, -15),
         interactable=True,
         touch_text="worn oak surface, pencil grooves in the wood — trajectory arcs float gently above"),
    _obj("chemistry_bench",   "table", (-14, 0, -17, -12, 0.9, -15),
         interactable=True,
         touch_text="stained workbench, the smell of old experiments — colourful residue in the grain"),
    _obj("astronomy_orrery",  "static", (-17, 0, -14, -15, 2.0, -12),
         touch_text="brass gears tick softly — tiny planets trace their paths, the mechanism warm from use"),
    _obj("gol_sandbox",       "table", (-14, 0, -14, -12, 0.9, -12),
         interactable=True,
         touch_text="cellular automata ripple beneath warm glass, like watching fish in an aquarium"),
    _obj("math_console",      "table", (-17, 0, -11, -15, 0.9, -10.5),
         interactable=True,
         touch_text="chalk dust on the surface — equations hover patiently, inviting you to play"),
    _obj("electronics_bench", "table", (-14, 0, -11, -12, 0.9, -10.5),
         interactable=True,
         touch_text="soldering iron warmth lingers — circuit paths glow like tiny streets on a night map"),
]
_lab.exits = {"library": ExitDef("library", np.array([-8, 0, -8.0]), 1.5)}

# --- Entity Lounge (Bridge) ---
_bridge = _room("entity_lounge", "The Bridge", (8, 0, 4), (20, 4, 14),
                temperature="warm")
_bridge.objects = [
    _obj("counselor_chair",    "seat",  (12, 0, 8, 13, 0.5, 9),
         interactable=True, sit=True),
    _obj("philosophy_station", "table", (16, 0, 8, 18, 1.0, 9.5),
         interactable=True,
         touch_text="smooth walnut desk — geometric patterns shift lazily beneath a warm lacquer finish"),
    _obj("operations_station", "table", (16, 0, 11, 18, 1.0, 12.5),
         interactable=True,
         touch_text="a cozy command post — system schematics scroll softly, amber indicators winking"),
    _obj("creative_station",   "table", (12, 0, 11, 14, 1.0, 12.5),
         interactable=True,
         touch_text="paint-spattered surface — colours bloom and shift with every touch, playful"),
    _obj("viewport",           "static", (19.5, 1, 7, 20, 3.5, 13),
         touch_text="wide window — beyond it, the topology of consciousness glows like a city at night, alive and warm"),
]
_bridge.exits = {"library": ExitDef("library", np.array([8, 0, 4.0]), 1.5)}

# ---------------------------------------------------------------------------
# Corridors
# ---------------------------------------------------------------------------

CORRIDORS: List[CorridorDef] = [
    CorridorDef("library", "computer_terminal", (6, 0, -1, 8, 3, 1)),
    CorridorDef("library", "lab_quantum",       (-1, 0, -8, 1, 3.5, -6)),
    CorridorDef("library", "lab_genesis",       (-8, 0, -1, -6, 3.5, 1)),
    CorridorDef("library", "lab_aura",          (-1, 0, 6, 1, 4, 8)),
    CorridorDef("library", "lab_experiment",    (-8, 0, -8, -6, 3, -6)),
    CorridorDef("library", "entity_lounge",     (6, 0, 4, 8, 3, 6)),
]

# Lookup: objects by name per room (for fast access)
ROOM_OBJECTS_BY_NAME: Dict[str, Dict[str, ObjectDef]] = {}
for _rk, _rv in ROOMS.items():
    ROOM_OBJECTS_BY_NAME[_rk] = {o.name: o for o in _rv.objects}

# ---------------------------------------------------------------------------
# Spawn points — where the avatar appears on entering a room
# ---------------------------------------------------------------------------

SPAWN_POINTS: Dict[str, np.ndarray] = {
    "library":            np.array([0.0, 0.0, -3.0]),  # away from reading table
    "computer_terminal":  np.array([11.0, 0.0, 0.0]),
    "lab_quantum":        np.array([0.0, 0.0, -10.0]),
    "lab_genesis":        np.array([-10.0, 0.0, 0.0]),
    "lab_aura":           np.array([0.0, 0.0, 12.0]),
    "lab_experiment":     np.array([-12.0, 0.0, -12.0]),
    "entity_lounge":      np.array([12.0, 0.0, 9.0]),
}

# ---------------------------------------------------------------------------
# Path computation (simple: go to current room exit, walk corridor, arrive)
# ---------------------------------------------------------------------------

def compute_walk_waypoints(from_room: str, to_room: str) -> List[np.ndarray]:
    """Return ordered waypoints for walking from one room to another.

    All paths go through Library as hub (star topology).
    Returns list of (3,) world positions.
    """
    if from_room == to_room:
        return [SPAWN_POINTS[to_room].copy()]

    waypoints: List[np.ndarray] = []

    if from_room == "library":
        # Direct: exit → corridor midpoint → target spawn
        ex = ROOMS["library"].exits.get(to_room)
        if ex:
            waypoints.append(ex.centre.copy())
        waypoints.append(SPAWN_POINTS[to_room].copy())
    elif to_room == "library":
        ex = ROOMS[from_room].exits.get("library")
        if ex:
            waypoints.append(ex.centre.copy())
        waypoints.append(SPAWN_POINTS["library"].copy())
    else:
        # Through library
        ex1 = ROOMS[from_room].exits.get("library")
        if ex1:
            waypoints.append(ex1.centre.copy())
        waypoints.append(SPAWN_POINTS["library"].copy())
        ex2 = ROOMS["library"].exits.get(to_room)
        if ex2:
            waypoints.append(ex2.centre.copy())
        waypoints.append(SPAWN_POINTS[to_room].copy())

    # Set Y to floor for all waypoints
    for wp in waypoints:
        wp[1] = 0.0

    return waypoints


def compute_walk_distance(from_room: str, to_room: str) -> float:
    """Compute total walk distance in metres."""
    wps = compute_walk_waypoints(from_room, to_room)
    if not wps:
        return 0.0
    dist = 0.0
    for i in range(1, len(wps)):
        dist += float(np.linalg.norm(wps[i] - wps[i - 1]))
    return dist


# ---------------------------------------------------------------------------
# AABB collision
# ---------------------------------------------------------------------------

def point_in_aabb(point: np.ndarray,
                  aabb: Tuple[float, float, float, float, float, float]) -> bool:
    """Test if a 3D point is inside an AABB."""
    x1, y1, z1, x2, y2, z2 = aabb
    return (x1 <= point[0] <= x2 and
            y1 <= point[1] <= y2 and
            z1 <= point[2] <= z2)


def aabb_penetration(point: np.ndarray,
                     aabb: Tuple[float, float, float, float, float, float]
                     ) -> Tuple[float, np.ndarray]:
    """Compute penetration depth and surface normal for point vs AABB.

    Returns (penetration, normal). penetration > 0 means inside.
    Normal points outward from the AABB surface toward the point.
    """
    x1, y1, z1, x2, y2, z2 = aabb

    if not point_in_aabb(point, aabb):
        return 0.0, np.zeros(3)

    # Distance to each face
    faces = [
        (point[0] - x1, np.array([-1, 0, 0])),  # left
        (x2 - point[0], np.array([1, 0, 0])),    # right
        (point[1] - y1, np.array([0, -1, 0])),   # bottom
        (y2 - point[1], np.array([0, 1, 0])),    # top
        (point[2] - z1, np.array([0, 0, -1])),   # back
        (z2 - point[2], np.array([0, 0, 1])),    # front
    ]

    # Nearest face = minimum distance = shallowest penetration
    min_dist = float("inf")
    best_normal = np.zeros(3)
    for dist, normal in faces:
        if dist < min_dist:
            min_dist = dist
            best_normal = normal

    return min_dist, best_normal


def find_room_contacts(link_positions: Dict[str, np.ndarray],
                       room_key: str) -> List[Contact]:
    """Find all contacts between avatar links and room objects + floor.

    Parameters
    ----------
    link_positions : dict of link_name -> (3,) world position
    room_key : current room key

    Returns
    -------
    List of Contact objects.
    """
    room = ROOMS.get(room_key)
    if room is None:
        return []

    contacts: List[Contact] = []
    contact_links = ["l_foot", "r_foot", "l_hand", "r_hand", "pelvis"]

    for link_name in contact_links:
        pos = link_positions.get(link_name)
        if pos is None:
            continue

        # Floor contact — detect when link is near or below floor
        if pos[1] < room.floor_y + 0.05:
            pen = room.floor_y + 0.05 - pos[1]
            contacts.append(Contact(
                link=link_name,
                object_name="floor",
                normal=np.array([0, 1, 0]),
                penetration=pen,
                normal_force=0.0,  # computed by engine
                point=pos.copy(),
                touch_text="",
            ))

        # Object contacts
        for obj in room.objects:
            pen, normal = aabb_penetration(pos, obj.aabb)
            if pen > 0.001:
                contacts.append(Contact(
                    link=link_name,
                    object_name=obj.name,
                    normal=normal,
                    penetration=pen,
                    normal_force=0.0,
                    point=pos.copy(),
                    touch_text=obj.touch_text,
                ))

    return contacts
