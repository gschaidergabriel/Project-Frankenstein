"""
SanctumPolicy — Bridge between trained RL policy and live SanctumManager.

Extracts observation from live state, runs inference, returns action.
Falls back to heuristic behavior if model is missing.
"""

from __future__ import annotations

import json
import logging
import random
import time
import urllib.request
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import torch
from torch.distributions import Categorical

from .environment import LOCATION_KEYS, NUM_LOCATIONS, NUM_ENTITIES, OBS_DIM
from .policy import SanctumMLP

LOG = logging.getLogger("sanctum.rl")

DEFAULT_MODEL_PATH = Path.home() / ".local" / "share" / "frank" / "models" / "sanctum_policy.pt"


class SanctumPolicy:
    """Trained RL policy for sanctum behavior decisions."""

    _physics_cache: Optional[Dict] = None
    _physics_cache_ts: float = 0.0
    _PHYSICS_CACHE_TTL: float = 5.0  # seconds

    def __init__(self, model_path: Path = DEFAULT_MODEL_PATH):
        self._model = SanctumMLP()
        self._model_loaded = False
        self._model_path = model_path

        try:
            if model_path.exists():
                checkpoint = torch.load(model_path, map_location="cpu", weights_only=False)
                self._model.load_state_dict(checkpoint["model_state_dict"])
                self._model.eval()
                self._model_loaded = True
                LOG.info("Sanctum RL policy loaded from %s (reward=%.3f, steps=%d)",
                         model_path,
                         checkpoint.get("best_reward", 0),
                         checkpoint.get("timesteps", 0))
            else:
                LOG.warning("No sanctum policy at %s — using heuristic fallback", model_path)
        except Exception as e:
            LOG.error("Failed to load sanctum policy: %s — using heuristic", e)

    def decide(self, manager) -> Tuple[int, int]:
        """
        Decide next action for the sanctum.

        Returns:
            (main_action, entity_choice) where:
            - main_action: 0=continue, 1-7=move, 8=silence, 9=spawn, 10=dismiss, 11=exit
            - entity_choice: 0-3 (only meaningful when main_action=9)
        """
        if not self._model_loaded:
            return self._heuristic_decide(manager)

        try:
            obs = self.extract_observation(manager)
            obs_tensor = torch.tensor(obs, dtype=torch.float32).unsqueeze(0)

            with torch.no_grad():
                action_logits, entity_logits, _ = self._model(obs_tensor)

            # Apply action mask
            mask = self._get_action_mask(manager)
            action_logits[0][~mask] = float("-inf")

            # Sample from masked distribution
            action_dist = Categorical(logits=action_logits[0])
            entity_dist = Categorical(logits=entity_logits[0])

            main_action = action_dist.sample().item()
            entity_choice = entity_dist.sample().item()

            LOG.debug("RL policy: action=%d, entity=%d (from logits)", main_action, entity_choice)
            return main_action, entity_choice

        except Exception as e:
            LOG.warning("RL inference failed: %s — heuristic fallback", e)
            return self._heuristic_decide(manager)

    def extract_observation(self, manager) -> np.ndarray:
        """Extract 64-dim observation from live SanctumManager state."""
        obs = np.zeros(OBS_DIM, dtype=np.float32)

        # Temporal
        elapsed = time.time() - manager.session_start_ts if manager.session_start_ts else 0
        obs[0] = min(manager.turn_count / 60.0, 1.0)
        obs[1] = min(elapsed / 3600.0, 1.0)
        obs[2] = min(manager._narrative_count / 3.0, 1.0)
        obs[3] = min(manager.entity_turn_count / 6.0, 1.0)

        # Current location one-hot
        loc_idx = LOCATION_KEYS.index(manager.current_location) if manager.current_location in LOCATION_KEYS else 0
        obs[4 + loc_idx] = 1.0

        # Visited locations bitvector
        visited_set = set(getattr(manager, "_visited_locations", []))
        visited_set.add(manager.current_location)
        for i, loc in enumerate(LOCATION_KEYS):
            if loc in visited_set:
                obs[11 + i] = 1.0

        # Mood
        mood = manager._get_mood()
        obs[18] = mood
        obs[19] = 0.5  # mood delta — would need history, default center

        # Entity one-hot
        if manager.spawned_entity:
            entity_idx = ["therapist", "mirror", "atlas", "muse"].index(manager.spawned_entity) \
                if manager.spawned_entity in ["therapist", "mirror", "atlas", "muse"] else -1
            if entity_idx >= 0:
                obs[20 + entity_idx + 1] = 1.0
            else:
                obs[20] = 1.0
        else:
            obs[20] = 1.0

        # Entity cooldowns
        entity_keys = ["therapist", "mirror", "atlas", "muse"]
        now = time.time()
        for i, ek in enumerate(entity_keys):
            last_ts = manager._entity_last_spawn_ts.get(ek, 0)
            cooldown_remaining = max(0, 300.0 - (now - last_ts))
            obs[25 + i] = min(cooldown_remaining / 300.0, 1.0)

        # Conversation / tool use
        obs[29] = min(len(manager.conversation_history) / 30.0, 1.0)
        obs[30] = min(len(manager._terminal_cmd_history) / 13.0, 1.0)
        obs[31] = min(len(manager._experiment_cmd_history) / 6.0, 1.0)
        obs[32] = 1.0 if manager._terminal_result_buffer else 0.0
        obs[33] = 1.0 if manager._experiment_result_buffer else 0.0

        # Session metrics
        obs[34] = min(elapsed / 3600.0, 1.0)
        obs[35] = min(getattr(manager, '_silence_count', 0) / 10.0, 1.0)
        obs[36] = min(manager._turns_in_location / 10.0, 1.0)
        obs[37] = min(manager._hibbert_spawn_count / 3.0, 1.0)

        # Flags
        obs[38] = 1.0 if manager._in_silence else 0.0
        obs[39] = 1.0 if manager.spawned_entity else 0.0
        obs[40] = 1.0 if manager._uninvited_entity_checked else 0.0
        obs[41] = time.localtime().tm_hour / 24.0

        # Diversity
        obs[42] = len(visited_set) / NUM_LOCATIONS
        obs[43] = min(len(set(manager._terminal_cmd_history)) / 13.0, 1.0)
        obs[44] = min(len(set(manager._experiment_cmd_history)) / 6.0, 1.0)

        # Exit readiness signals (must match environment.py)
        n_visited = len(visited_set)
        total_spawns = getattr(manager, '_hibbert_spawn_count', 0)
        # Count entity spawns from cooldown tracking
        entity_keys = ["therapist", "mirror", "atlas", "muse"]
        now = time.time()
        for ek in entity_keys:
            last_ts = manager._entity_last_spawn_ts.get(ek, 0)
            if last_ts > manager.session_start_ts:
                total_spawns += 1
        silence_count = getattr(manager, '_silence_count', 0)
        mins = elapsed / 60.0
        obs[45] = 1.0 if (mins >= 20 and n_visited >= 4) else 0.0
        obs[46] = 1.0 if (mins >= 20 and silence_count >= 1 and total_spawns >= 1) else 0.0
        obs[47] = min(max(0, mins - 20) / 20.0, 1.0)

        # 48-63: Physics body state from NeRD physics service
        physics = self._get_cached_physics()
        if physics:
            obs[48] = physics.get("root_x", 0.5)
            obs[49] = physics.get("root_z", 0.5)
            obs[50] = physics.get("walk_speed", 0.0) / 2.0
            obs[51] = 1.0 if physics.get("is_walking", False) else 0.0
            obs[52] = 1.0 if physics.get("is_sitting", False) else 0.0
            obs[53] = physics.get("num_contacts", 2) / 10.0
            obs[54] = physics.get("total_force", 700.0) / 2000.0
            obs[55] = 1.0 if physics.get("l_foot_contact", True) else 0.0
            obs[56] = 1.0 if physics.get("r_foot_contact", True) else 0.0
            obs[57] = 1.0 if physics.get("hand_contact", False) else 0.0
            obs[58] = physics.get("torso_strain", 30.0) / 200.0
            obs[59] = physics.get("knee_load", 100.0) / 500.0
            obs[60] = 0.3  # distance to exit (not tracked yet)
            obs[61] = physics.get("walk_progress", 0.0)
            obs[62] = max(0.0, min(1.0, 1.6 - mood))  # gravity factor
            obs[63] = 0.8  # body coherence default
        else:
            # Default standing values when physics service is down
            obs[48] = 0.5   # root_x centred
            obs[49] = 0.5   # root_z centred
            obs[53] = 0.2   # num_contacts / 10 (2 feet)
            obs[54] = 0.35  # total_force / 2000 (~700N)
            obs[55] = 1.0   # l_foot contact
            obs[56] = 1.0   # r_foot contact
            obs[58] = 0.15  # torso strain (~30)
            obs[59] = 0.2   # knee load (~100)
            obs[60] = 0.3   # distance to exit
            obs[62] = max(0.0, min(1.0, 1.6 - mood))  # gravity factor
            obs[63] = 0.8   # body coherence

        return obs

    def _get_action_mask(self, manager) -> torch.BoolTensor:
        """Return boolean mask of valid actions (True = valid)."""
        mask = torch.ones(12, dtype=torch.bool)

        elapsed = time.time() - manager.session_start_ts if manager.session_start_ts else 0

        # No EXIT before 10 min
        if elapsed < 600:
            mask[11] = False

        # No DISMISS without entity
        if not manager.spawned_entity:
            mask[10] = False

        # No SPAWN with entity active or too early
        if manager.spawned_entity:
            mask[9] = False
        if manager.turn_count < 3:
            mask[9] = False  # Must explore before spawning

        # No SPAWN if all entities on cooldown
        if not manager.spawned_entity:
            entity_keys = ["therapist", "mirror", "atlas", "muse"]
            now = time.time()
            all_on_cooldown = True
            for ek in entity_keys:
                last_ts = manager._entity_last_spawn_ts.get(ek, 0)
                if (now - last_ts) >= 300.0:
                    all_on_cooldown = False
                    break
            if all_on_cooldown:
                mask[9] = False

        # No SPAWN after 30 min — need to wrap up, not start new conversations
        if elapsed > 1800:
            mask[9] = False

        # No MOVE to current location
        loc_idx = LOCATION_KEYS.index(manager.current_location) \
            if manager.current_location in LOCATION_KEYS else 0
        mask[1 + loc_idx] = False

        # No SILENCE during entity conversation
        if manager.spawned_entity:
            mask[8] = False

        # No SILENCE if just started or already in silence
        if manager._in_silence:
            mask[8] = False
        if manager._narrative_count < 1:
            mask[8] = False

        return mask

    def _get_cached_physics(self) -> Optional[Dict]:
        """Fetch physics state with 5s TTL cache. Returns None if service is down."""
        now = time.time()
        if self._physics_cache is not None and (now - self._physics_cache_ts) < self._PHYSICS_CACHE_TTL:
            return self._physics_cache
        try:
            req = urllib.request.Request("http://127.0.0.1:8100/state", method="GET")
            with urllib.request.urlopen(req, timeout=0.5) as resp:
                data = json.loads(resp.read())
            # Normalize root position to [0, 1] range (rooms span roughly -20 to +20)
            root_pos = data.get("root_pos", [0, 0, 0])
            # Extract contact details
            contacts = data.get("contacts", [])
            l_foot = any(c["link"] == "l_foot" for c in contacts)
            r_foot = any(c["link"] == "r_foot" for c in contacts)
            hand_contact = any("hand" in c["link"] for c in contacts)
            total_force = sum(c.get("force", 0) for c in contacts)
            torso_strain = abs(data.get("torques", [0.0] * 19)[2]) if len(data.get("torques", [])) > 2 else 30.0
            knee_load = sum(abs(data["torques"][i]) for i in [13, 17]) if len(data.get("torques", [])) > 17 else 100.0
            self._physics_cache = {
                "root_x": (root_pos[0] + 20) / 40.0,  # normalize -20..+20 to 0..1
                "root_z": (root_pos[2] + 20) / 40.0,
                "walk_speed": data.get("walk_speed", 0.0),
                "is_walking": data.get("is_walking", False),
                "is_sitting": data.get("is_sitting", False),
                "num_contacts": data.get("num_contacts", 2),
                "total_force": total_force,
                "l_foot_contact": l_foot,
                "r_foot_contact": r_foot,
                "hand_contact": hand_contact,
                "torso_strain": torso_strain,
                "knee_load": knee_load,
                "walk_progress": data.get("walk_progress", 0.0),
            }
            self._physics_cache_ts = now
            return self._physics_cache
        except Exception:
            return None

    def _heuristic_decide(self, manager) -> Tuple[int, int]:
        """
        Fallback behavior replicating exact current LLM-driven logic.

        - Silence every 3 narratives
        - Auto-move after 5 turns in same location
        - 25% uninvited entity at turn 5+
        - Continue otherwise
        """
        # Check silence trigger
        if (manager._narrative_count >= 3
                and not manager.spawned_entity
                and not manager._in_silence):
            return 8, 0  # SILENCE

        # Check auto-move
        _terminal_active = (
            manager.current_location == "computer_terminal"
            and len(manager._terminal_cmd_history) > 0
            and manager._turns_in_location < 10
        )
        _lab_active = (
            manager.current_location == "lab_experiment"
            and len(manager._experiment_cmd_history) > 0
            and manager._turns_in_location < 10
        )
        if (manager._turns_in_location >= 5
                and not manager.spawned_entity
                and not _terminal_active and not _lab_active):
            # Pick next unvisited location
            visited = set(getattr(manager, "_visited_locations", []))
            visited.add(manager.current_location)
            for i, loc in enumerate(LOCATION_KEYS):
                if loc not in visited:
                    return 1 + i, 0  # MOVE
            # All visited — cycle
            loc_idx = LOCATION_KEYS.index(manager.current_location) \
                if manager.current_location in LOCATION_KEYS else 0
            next_idx = (loc_idx + 1) % NUM_LOCATIONS
            return 1 + next_idx, 0

        # Check uninvited entity (25% at turn 5+)
        if (manager.turn_count >= 5
                and not manager._uninvited_entity_checked
                and not manager.spawned_entity
                and random.random() < 0.25):
            # Pick entity based on context
            mood = manager._get_mood()
            if mood < 0.35:
                entity_choice = 0  # therapist
            elif manager.current_location == "lab_quantum":
                entity_choice = 1  # mirror (philosopher)
            elif manager.current_location in ("lab_experiment", "lab_genesis"):
                entity_choice = 3  # muse
            else:
                entity_choice = random.randint(0, 3)
            return 9, entity_choice  # SPAWN

        return 0, 0  # CONTINUE
