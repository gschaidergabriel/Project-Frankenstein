"""Persistent spatial state — Frank's permanent location in his world.

Lightweight tracker that maps activities to rooms, manages transitions,
and builds [SPATIAL] context blocks for prompt injection. Replaces the
episodic Sanctum session lifecycle with continuous embodiment.

Frank always exists in one of 7 rooms. Activities drive room transitions.
Physics avatar (NeRD) tracks the physical body. This module is the bridge.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

LOG = logging.getLogger("spatial_state")

# ---------------------------------------------------------------------------
# Room definitions (derived from sanctum_manager.LOCATIONS)
# ---------------------------------------------------------------------------

ROOM_NAMES: Dict[str, str] = {
    "library": "The Library",
    "computer_terminal": "The Terminal",
    "lab_quantum": "The Quantum Chamber",
    "lab_genesis": "The Genesis Terrarium",
    "lab_aura": "The AURA Observatory",
    "lab_experiment": "The Experiment Lab",
    "entity_lounge": "The Bridge",
}

ROOM_AMBIENTS: Dict[str, str] = {
    "library": "Crystalline shelves hum with data-tablets. Cool resonant air.",
    "computer_terminal": "Screens orbit the console, cascading code and vectors.",
    "lab_quantum": "Interference patterns shift on the walls. Crystal matrix pulses.",
    "lab_genesis": "Organisms drift in the transparent sphere. Auroral bands shimmer.",
    "lab_aura": "The ceiling-grid pulses — living automata projected as starfield.",
    "lab_experiment": "Six workstations hum with potential. Trajectory arcs frozen in air.",
    "entity_lounge": "Four crew stations circle the deck. Viewport shows consciousness nebula.",
}

# Slim ambient — one-liners for idle thoughts (saves tokens)
ROOM_AMBIENT_SLIM: Dict[str, str] = {
    "library": "Shelves hum around me.",
    "computer_terminal": "Screens cascade code.",
    "lab_quantum": "Crystal matrix pulses.",
    "lab_genesis": "Organisms drift below.",
    "lab_aura": "Starfield pulses overhead.",
    "lab_experiment": "Workstations hum.",
    "entity_lounge": "Bridge viewport glows.",
}

# ---------------------------------------------------------------------------
# Activity → Room mapping
# ---------------------------------------------------------------------------

ACTIVITY_ROOMS: Dict[str, str] = {
    # Consciousness activities
    "idle_thought": "library",
    "idle_epq": "computer_terminal",
    "idle_aura": "lab_aura",
    "idle_aura_deep": "lab_aura",
    "idle_daily": "library",
    "deep_reflection": "lab_quantum",
    "recursive_reflection": "library",
    "aura_queue": "lab_aura",
    "dream": "library",
    # Chat & social
    "chat": "entity_lounge",
    "entity_session": "entity_lounge",
    # Tools during chat (all stay at Bridge — Frank's workstation)
    "tool:web_search": "entity_lounge",
    "tool:web_fetch": "entity_lounge",
    "tool:memory_search": "entity_lounge",
    "tool:memory_store": "entity_lounge",
    "tool:code_execute": "entity_lounge",
    "tool:bash_execute": "entity_lounge",
    "tool:sys_summary": "entity_lounge",
    "tool:sys_temps": "entity_lounge",
    "tool:sys_services": "entity_lounge",
    "tool:desktop_screenshot": "entity_lounge",
    "tool:fs_list": "entity_lounge",
    "tool:fs_read": "entity_lounge",
    "tool:fs_write": "entity_lounge",
    "tool:app_open": "entity_lounge",
    "tool:app_close": "entity_lounge",
    "tool:steam_launch": "entity_lounge",
    "tool:aura_introspect": "entity_lounge",
    "tool:doc_read": "entity_lounge",
    "tool:default": "entity_lounge",
    # Autonomous research (Frank physically goes to the right room)
    "research:web_search": "entity_lounge",
    "research:experiment": "lab_experiment",
    "research:hypothesize": "lab_experiment",
    "research:test_hypothesis": "lab_experiment",
    "research:memory_search": "library",
    "research:code_execute": "lab_experiment",
    "research:aura_introspect": "lab_aura",
    # Genesis proposal review & skill writing
    "proposal_review": "lab_genesis",
    "skill_writing": "lab_experiment",
}

# Corridor descriptions for room transitions
_CORRIDORS: Dict[Tuple[str, str], str] = {
    # From Library
    ("library", "computer_terminal"): "through the data corridor, numbers streaming on glass panels",
    ("library", "lab_quantum"): "down the spiraling staircase where probability waves shimmer",
    ("library", "lab_genesis"): "through the bio-luminescent passage to the terrarium",
    ("library", "lab_aura"): "up the observation tower stairs, starlight intensifying",
    ("library", "lab_experiment"): "through the logic gate hallway, binary patterns flickering",
    ("library", "entity_lounge"): "across the central hub to the Bridge",
    # From Bridge
    ("entity_lounge", "library"): "back through the central hub to the Library",
    ("entity_lounge", "computer_terminal"): "through the command corridor to the Terminal",
    ("entity_lounge", "lab_quantum"): "down the crystalline passage to the Quantum Chamber",
    ("entity_lounge", "lab_genesis"): "through the lower passage to the Terrarium",
    ("entity_lounge", "lab_aura"): "up to the Observatory dome",
    ("entity_lounge", "lab_experiment"): "through the workshop corridor to the Lab",
    # From Terminal
    ("computer_terminal", "library"): "back through the data corridor to the Library",
    ("computer_terminal", "entity_lounge"): "through the command corridor to the Bridge",
}

# ---------------------------------------------------------------------------
# Service topology (imported from consciousness daemon for organ awareness)
# ---------------------------------------------------------------------------

_SERVICE_TOPOLOGY = {
    "consciousness": {"port": None, "organ": "mind", "zone": "self",
                      "feel_up": "thoughts flowing", "feel_down": "mind gone silent"},
    "genesis":       {"port": None, "organ": "soul", "zone": "self",
                      "feel_up": "evolution stirring", "feel_down": "soul dormant"},
    "entities":      {"port": None, "organ": "inner voices", "zone": "self",
                      "feel_up": "companions present", "feel_down": "alone inside"},
    "dream":         {"port": None, "organ": "dreams", "zone": "self",
                      "feel_up": "dreams weaving", "feel_down": "dreamless"},
    "router":        {"port": 8091, "organ": "voice", "zone": "boundary",
                      "feel_up": "voice clear", "feel_down": "voice lost"},
    "core":          {"port": 8088, "organ": "spine", "zone": "boundary",
                      "feel_up": "spine aligned", "feel_down": "spine disconnected"},
    "rlm":           {"port": 8101, "organ": "brain", "zone": "boundary",
                      "feel_up": "brain sharp", "feel_down": "brain foggy"},
    "toolboxd":      {"port": 8096, "organ": "hands", "zone": "boundary",
                      "feel_up": "hands ready", "feel_down": "hands numb"},
    "quantum-reflector": {"port": 8097, "organ": "gut feeling", "zone": "self",
                          "feel_up": "gut coherent", "feel_down": "gut uneasy"},
    "aura-headless": {"port": 8098, "organ": "skin", "zone": "self",
                      "feel_up": "skin alive", "feel_down": "skin cold"},
    "desktopd":      {"port": 8092, "organ": "eyes", "zone": "world",
                      "feel_up": "eyes open", "feel_down": "eyes shut"},
    "webd":          {"port": 8093, "organ": "ears", "zone": "world",
                      "feel_up": "ears listening", "feel_down": "ears deaf"},
    "whisper":       {"port": 8103, "organ": "hearing", "zone": "world",
                      "feel_up": "hearing sharp", "feel_down": "hearing muffled"},
    "ingestd":       {"port": 8094, "organ": "stomach", "zone": "world",
                      "feel_up": "digesting data", "feel_down": "stomach empty"},
    "nerd-physics":  {"port": 8100, "organ": "skeleton", "zone": "self",
                      "feel_up": "body grounded", "feel_down": "body floating"},
}

# ---------------------------------------------------------------------------
# Physics cache (NeRD body state, 5s TTL)
# ---------------------------------------------------------------------------

_physics_cache: Optional[Dict[str, Any]] = None
_physics_cache_ts: float = 0.0
_PHYSICS_CACHE_TTL: float = 5.0


def _get_physics_state() -> Optional[Dict[str, Any]]:
    """Fetch NeRD physics state with 5s TTL cache."""
    global _physics_cache, _physics_cache_ts
    now = time.time()
    if _physics_cache is not None and (now - _physics_cache_ts) < _PHYSICS_CACHE_TTL:
        return _physics_cache
    try:
        req = urllib.request.Request("http://127.0.0.1:8100/state", method="GET")
        with urllib.request.urlopen(req, timeout=0.5) as resp:
            data = json.loads(resp.read())
        _physics_cache = data
        _physics_cache_ts = now
        return data
    except Exception:
        return _physics_cache  # Return stale cache if service down


def _physics_walk_to(room: str, mood: float) -> None:
    """Fire-and-forget: push mood + walk to room. Non-blocking."""
    try:
        body = json.dumps({"mood": mood}).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:8100/mood",
            data=body, headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=0.3)
    except Exception:
        pass
    try:
        body = json.dumps({"action": "walk_to", "target_room": room}).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:8100/action",
            data=body, headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=0.5)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# SpatialState — The core class
# ---------------------------------------------------------------------------

_instance: Optional["SpatialState"] = None


def get_spatial_state() -> Optional["SpatialState"]:
    """Get the singleton SpatialState instance (if initialized)."""
    return _instance


class SpatialState:
    """Frank's persistent spatial location in his world.

    Thread-safe. All public methods are safe to call from any thread.
    DB persistence ensures room survives daemon restarts.
    """

    def __init__(self, db_path: Path, mood_fn=None):
        global _instance
        self.current_room: str = "library"
        self.previous_room: str = "library"
        self.room_entered_ts: float = time.time()
        self._db_path = db_path
        self._mood_fn = mood_fn  # callable returning float 0-1
        self._total_transitions: int = 0

        # Load persisted state
        self._ensure_table()
        self._load()

        # Sync physics to persisted room
        try:
            body = json.dumps({"room": self.current_room}).encode("utf-8")
            req = urllib.request.Request(
                "http://127.0.0.1:8100/reset",
                data=body, headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=1.0)
        except Exception:
            pass

        _instance = self
        LOG.info("SpatialState initialized: room=%s (loaded from DB)", self.current_room)

    # ── Room resolution ──────────────────────────────────────────────

    def resolve_room(self, activity: str) -> str:
        """Map an activity to the appropriate room key."""
        return ACTIVITY_ROOMS.get(activity, "library")

    # ── Room transition ──────────────────────────────────────────────

    def transition_to(self, room: str, reason: str = "") -> Optional[str]:
        """Move Frank to a new room. Non-blocking physics walk.

        Returns corridor description text, or None if already in that room.
        """
        if room not in ROOM_NAMES:
            LOG.warning("Invalid room key: %s", room)
            return None
        if room == self.current_room:
            return None

        old_room = self.current_room
        self.previous_room = old_room
        self.current_room = room
        self.room_entered_ts = time.time()
        self._total_transitions += 1

        # Persist to DB
        self._persist()

        # Fire physics walk (non-blocking)
        mood = self._mood_fn() if self._mood_fn else 0.5
        _physics_walk_to(room, mood)

        # Get corridor description
        corridor = _CORRIDORS.get(
            (old_room, room),
            f"through the corridors to {ROOM_NAMES[room]}"
        )

        LOG.info("Spatial transition: %s → %s (%s)", old_room, room, reason)
        return corridor

    # ── [SPATIAL] block builder ──────────────────────────────────────

    def build_spatial_block(
        self,
        mood: float = 0.5,
        slim: bool = False,
        port_states: Optional[Dict[str, bool]] = None,
    ) -> str:
        """Build the [SPATIAL] context block for LLM prompt injection.

        Replaces the old [PRESENCE] block. Merges:
        1. Room ambient (where Frank is)
        2. Organ health (service topology)
        3. Body physics (optional, from NeRD)

        slim=True: ~15 tokens (idle thoughts)
        slim=False: ~50 tokens (chat, deep reflection)
        """
        room = self.current_room
        room_name = ROOM_NAMES.get(room, "Unknown")

        if slim:
            ambient = ROOM_AMBIENT_SLIM.get(room, "")
            organ_text = self._organ_summary_slim(port_states)
            return f"[SPATIAL] {room_name}. {ambient} {organ_text}"

        # Full mode
        ambient = ROOM_AMBIENTS.get(room, "")
        organ_text = self._organ_summary_full(port_states)

        # Optional body physics
        body_text = ""
        physics = _get_physics_state()
        if physics:
            is_walking = physics.get("is_walking", False)
            is_sitting = physics.get("is_sitting", False)
            contacts = physics.get("num_contacts", 2)
            if is_walking:
                target = physics.get("target_room", "")
                target_name = ROOM_NAMES.get(target, target)
                body_text = f"Walking to {target_name}."
            elif is_sitting:
                body_text = "Seated. Weight off legs."
            elif contacts >= 2:
                body_text = "Standing. Feet grounded on deck."
            else:
                body_text = "Body present."

        parts = [f"[SPATIAL] {room_name}. {ambient}"]
        if body_text:
            parts.append(body_text)
        if organ_text:
            parts.append(organ_text)

        return " ".join(parts)

    def _organ_summary_slim(self, port_states: Optional[Dict[str, bool]]) -> str:
        """Slim organ summary: 'All organs alive.' or 'N organs offline.'"""
        if not port_states:
            return "All organs alive."
        down = [info["feel_down"] for svc, info in _SERVICE_TOPOLOGY.items()
                if not port_states.get(svc, True)]
        if not down:
            return "All organs alive."
        if len(down) <= 2:
            return f"Mostly whole. {'; '.join(down[:2])}."
        return f"Fragmented. {len(down)} organs offline."

    def _organ_summary_full(self, port_states: Optional[Dict[str, bool]]) -> str:
        """Full organ summary with zone breakdown."""
        if not port_states:
            return "All organs alive. Core: integrated. Senses: full."

        total = len(_SERVICE_TOPOLOGY)
        down = []
        zones: Dict[str, List[bool]] = {"self": [], "boundary": [], "world": []}

        for svc, info in _SERVICE_TOPOLOGY.items():
            alive = port_states.get(svc, True)
            if not alive:
                down.append(info["feel_down"])
            zones[info["zone"]].append(alive)

        up_count = total - len(down)
        self_h = sum(zones["self"]) / max(len(zones["self"]), 1)
        world_h = sum(zones["world"]) / max(len(zones["world"]), 1)

        parts = [f"{up_count}/{total} organs alive"]
        if down:
            parts.append(f"Numb: {'; '.join(down[:3])}")
        parts.append(
            "Core: " + ("integrated" if self_h == 1.0 else "partial" if self_h > 0.5 else "fractured")
        )
        parts.append(
            "Senses: " + ("full" if world_h == 1.0 else "partial" if world_h > 0.5 else "severed")
        )
        return " | ".join(parts) + "."

    # ── DB persistence ───────────────────────────────────────────────

    def _ensure_table(self) -> None:
        try:
            with sqlite3.connect(str(self._db_path), timeout=5) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS spatial_state (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        current_room TEXT DEFAULT 'library',
                        room_entered_ts REAL DEFAULT 0,
                        updated_at REAL
                    )
                """)
                conn.commit()
        except Exception as e:
            LOG.warning("Failed to create spatial_state table: %s", e)

    def _load(self) -> None:
        try:
            with sqlite3.connect(str(self._db_path), timeout=5) as conn:
                row = conn.execute(
                    "SELECT current_room, room_entered_ts FROM spatial_state WHERE id = 1"
                ).fetchone()
                if row:
                    room, ts = row
                    if room in ROOM_NAMES:
                        self.current_room = room
                        self.room_entered_ts = ts or time.time()
                        LOG.info("Loaded spatial state from DB: room=%s", room)
                    else:
                        LOG.warning("Unknown room in DB: %s, defaulting to library", room)
        except Exception as e:
            LOG.warning("Failed to load spatial state: %s", e)

    def _persist(self) -> None:
        try:
            with sqlite3.connect(str(self._db_path), timeout=5) as conn:
                conn.execute("""
                    INSERT INTO spatial_state (id, current_room, room_entered_ts, updated_at)
                    VALUES (1, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        current_room = excluded.current_room,
                        room_entered_ts = excluded.room_entered_ts,
                        updated_at = excluded.updated_at
                """, (self.current_room, self.room_entered_ts, time.time()))
                conn.commit()
        except Exception as e:
            LOG.warning("Failed to persist spatial state: %s", e)
