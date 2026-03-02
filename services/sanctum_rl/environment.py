"""
SanctumEnv — Gymnasium environment for training Frank's sanctum behavior.

Pure state-machine simulation. No LLM calls. Runs at 1M+ steps/sec on CPU.
Each step = 1 sanctum tick. Episode = one sanctum session.
"""

from __future__ import annotations

import gymnasium as gym
import numpy as np
from gymnasium import spaces

# Location keys matching sanctum_manager.py LOCATIONS dict order
LOCATION_KEYS = [
    "library",             # 0
    "computer_terminal",   # 1
    "lab_quantum",         # 2
    "lab_genesis",         # 3
    "lab_aura",            # 4
    "lab_experiment",      # 5
    "entity_lounge",       # 6
]
NUM_LOCATIONS = len(LOCATION_KEYS)

ENTITY_KEYS = ["therapist", "mirror", "atlas", "muse"]
NUM_ENTITIES = len(ENTITY_KEYS)

# Max episode length (turns) — safety net, time-based truncation is primary
MAX_TURNS = 100
# Max session time in seconds (primary truncation)
MAX_SESSION_TIME = 4500.0  # 75 min — well past optimal, strong penalty

# Per-turn time costs (must match real LLM latency)
TURN_TIME_NORMAL = 180.0    # ~3 min per LLM narrative call
TURN_TIME_ENTITY = 180.0    # ~3 min per entity LLM call
TURN_TIME_SILENCE = 15.0    # silence ticks are free (no LLM)

# Observation dimension
OBS_DIM = 64


class SanctumEnv(gym.Env):
    """Simulated Inner Sanctum for RL training."""

    metadata = {"render_modes": []}

    def __init__(self, **kwargs):
        super().__init__()
        self.observation_space = spaces.Box(
            low=0.0, high=1.0, shape=(OBS_DIM,), dtype=np.float32
        )
        # MultiDiscrete: [12 main actions, 4 entity choices]
        self.action_space = spaces.MultiDiscrete([12, 4])

        # Internal state
        self._rng = np.random.default_rng()
        self._reset_state()

    def _reset_state(self):
        self.turn_count = 0
        self.elapsed_time = 0.0  # simulated seconds
        self.current_location = 0  # index into LOCATION_KEYS
        self.visited = np.zeros(NUM_LOCATIONS, dtype=bool)
        self.visited[0] = True  # library is starting location
        self.mood = 0.5 + self._rng.normal(0, 0.05)
        self.mood = np.clip(self.mood, 0.2, 0.95)
        self.mood_history = [self.mood]
        self.narrative_count = 0  # since last silence
        self.silence_count = 0
        self.in_silence = False
        self.silence_remaining = 0

        # Entity state
        self.spawned_entity = -1  # -1 = none, 0-3 = entity index
        self.entity_turn_count = 0
        self.entity_cooldowns = np.zeros(NUM_ENTITIES, dtype=np.float32)
        self.entity_spawn_count = np.zeros(NUM_ENTITIES, dtype=np.int32)

        # Tool use tracking
        self.terminal_cmd_count = 0
        self.terminal_cmd_types = set()
        self.experiment_cmd_count = 0
        self.experiment_types = set()
        self.has_terminal_result = False
        self.has_experiment_result = False

        # Diversity tracking
        self.turns_in_location = 0
        self.action_history = []
        self.location_history = []

        # Session metrics
        self.total_entity_turns = 0
        self.mood_at_start = self.mood

        # Hour of day (random for training diversity)
        self.hour_of_day = self._rng.uniform(0, 24)

    def reset(self, seed=None, options=None):
        if seed is not None:
            self._rng = np.random.default_rng(seed)
        self._reset_state()
        return self._get_obs(), {}

    def step(self, action):
        main_action = int(action[0])
        entity_choice = int(action[1])

        reward = 0.0
        terminated = False
        truncated = False
        info = {}

        # Record action for anti-repetition
        self.action_history.append(main_action)
        if len(self.action_history) > 10:
            self.action_history = self.action_history[-10:]

        # Handle silence state
        if self.in_silence:
            self.silence_remaining -= 1
            if self.silence_remaining <= 0:
                self.in_silence = False
                self.narrative_count = 0
            self.elapsed_time += TURN_TIME_SILENCE
            self.turn_count += 1
            # Mood recovery during silence
            self.mood += self._rng.normal(0.008, 0.003)
            self.mood = np.clip(self.mood, 0.05, 0.98)
            self.mood_history.append(self.mood)
            # Tick cooldowns
            self.entity_cooldowns = np.maximum(0, self.entity_cooldowns - TURN_TIME_SILENCE)
            # Small per-tick silence reward (mood recovery is inherently valuable)
            silence_reward = 0.1
            truncated = self.turn_count >= MAX_TURNS or self.elapsed_time >= MAX_SESSION_TIME
            return self._get_obs(), silence_reward, False, truncated, {}

        # === Process Actions ===

        if main_action == 0:
            # CONTINUE — stay, generate narrative
            reward += self._step_narrative()
            # Small reward for continuing, but only when still exploring
            locs_visited = int(self.visited.sum())
            if self.spawned_entity < 0 and locs_visited < NUM_LOCATIONS:
                reward += 0.1

        elif 1 <= main_action <= 7:
            # MOVE_TO location
            target = main_action - 1
            if target < NUM_LOCATIONS and target != self.current_location:
                self.current_location = target
                self.turns_in_location = 0
                self.location_history.append(target)
                self.has_terminal_result = False
                self.has_experiment_result = False

                if not self.visited[target]:
                    self.visited[target] = True
                    reward += 2.0  # NEW LOCATION — highest per-action reward
                    self.mood += 0.005
                else:
                    reward -= 0.5  # revisit penalty (stronger to prevent cycling)
                reward += self._step_narrative()
            else:
                # Invalid move (same location or OOB)
                reward -= 0.3
                reward += self._step_narrative()

        elif main_action == 8:
            # TRIGGER_SILENCE
            if self.narrative_count >= 2 and not self.in_silence and self.spawned_entity < 0:
                self.in_silence = True
                self.silence_remaining = self._rng.integers(8, 20)  # 2-5 min in ticks
                self.silence_count += 1
                if self.silence_count == 1:
                    reward += 3.0  # First silence — very valuable
                else:
                    reward += 1.5  # Subsequent silences still good
            else:
                reward -= 0.5  # bad silence timing

        elif main_action == 9:
            # SPAWN_ENTITY
            locs_visited = int(self.visited.sum())
            total_spawns = int(self.entity_spawn_count.sum())
            if self.spawned_entity < 0 and 0 <= entity_choice < NUM_ENTITIES:
                if self.entity_cooldowns[entity_choice] <= 0:
                    # Penalty for spawning too early (must explore first)
                    if self.turn_count < 3:
                        reward -= 1.5  # Don't start with entity
                    elif locs_visited < 2:
                        reward -= 0.8  # Visit at least 2 locations first
                    else:
                        # POSITIVE reward for well-timed entity spawn
                        mins = self.elapsed_time / 60.0
                        if mins > 30:
                            reward -= 2.0  # Too late — should be exiting, not spawning
                        elif total_spawns == 0 and locs_visited >= 3:
                            reward += 2.0  # First entity after exploring
                        elif total_spawns == 0:
                            reward += 0.8  # First entity, some exploration
                        elif total_spawns == 1:
                            reward -= 0.5  # Second entity is costly
                        else:
                            reward -= 1.5  # Penalty for 3+ spawns
                    self.spawned_entity = entity_choice
                    self.entity_turn_count = 0
                    self.entity_spawn_count[entity_choice] += 1
                    # Move to entity lounge
                    if self.current_location != 6:
                        self.current_location = 6
                        self.turns_in_location = 0
                        if not self.visited[6]:
                            self.visited[6] = True
                            reward += 1.0
                else:
                    reward -= 0.5  # on cooldown
            else:
                reward -= 0.3  # invalid spawn

        elif main_action == 10:
            # DISMISS_ENTITY
            if self.spawned_entity >= 0:
                turns = self.entity_turn_count
                if 3 <= turns <= 6:
                    reward += 1.0  # good conversation length (was 0.3)
                elif turns < 2:
                    reward -= 0.5  # too short
                self.entity_cooldowns[self.spawned_entity] = 300.0
                self.spawned_entity = -1
                self.entity_turn_count = 0
            else:
                reward -= 0.2  # nothing to dismiss

        elif main_action == 11:
            # EXIT_SANCTUM
            terminated = True
            mins = self.elapsed_time / 60.0
            mood_improved = self.mood > self.mood_at_start
            locs_visited = int(self.visited.sum())
            total_spawns = int(self.entity_spawn_count.sum())

            if mins >= 20 and mins <= 40 and mood_improved and locs_visited >= 4:
                reward += 8.0  # optimal exit — very strong incentive
            elif mins >= 15 and locs_visited >= 3:
                reward += 4.0  # good exit
            elif mins >= 10:
                reward += 1.0  # acceptable exit
            else:
                reward -= 3.0  # premature exit
            # Bonus for exploration diversity
            reward += locs_visited * 0.3  # up to 2.1 for visiting all 7
            if self.silence_count >= 1:
                reward += 1.5  # had at least one silence
            if total_spawns >= 1:
                reward += 1.5  # had at least one entity conversation

        # Entity conversation auto-progress
        if self.spawned_entity >= 0 and main_action != 10:
            self.entity_turn_count += 1
            self.total_entity_turns += 1
            # Per-turn entity conversation reward (up to 4 turns, then diminishing)
            if self.entity_turn_count <= 4:
                reward += 0.2  # each entity conversation turn has modest value
            # Entity mood effect
            if self.entity_turn_count <= 3:
                self.mood += self._rng.normal(0.005, 0.003)
            elif self.entity_turn_count > 6:
                # Auto-dismiss after max turns
                self.entity_cooldowns[self.spawned_entity] = 300.0
                mood_delta = self.mood - self.mood_history[max(0, len(self.mood_history) - self.entity_turn_count)]
                if mood_delta > 0:
                    reward += 0.5  # entity mood bonus
                self.spawned_entity = -1
                self.entity_turn_count = 0

        # Advance time — all LLM calls take ~3 min real time
        if self.spawned_entity >= 0:
            self.elapsed_time += TURN_TIME_ENTITY
        else:
            self.elapsed_time += TURN_TIME_NORMAL
        self.turn_count += 1
        self.turns_in_location += 1

        # Mood random walk
        self.mood += self._rng.normal(0, 0.005)
        if self.turns_in_location > 3:
            self.mood -= 0.003  # dwelling penalty
        self.mood = np.clip(self.mood, 0.05, 0.98)
        self.mood_history.append(self.mood)

        # Mood decline penalty
        if len(self.mood_history) >= 5:
            delta = self.mood - self.mood_history[-5]
            if delta < -0.03:
                reward -= 0.8

        # Dwelling penalty (3 turns = ~9 min at 180s/turn)
        if self.turns_in_location > 3 and self.spawned_entity < 0:
            if not self.has_terminal_result and not self.has_experiment_result:
                reward -= 0.5

        # Duplicate action penalty
        if len(self.action_history) >= 5:
            recent = self.action_history[-5:]
            if recent.count(main_action) >= 3:
                reward -= 1.0

        # Time pressure — incentivize voluntary exit over running out the clock
        mins = self.elapsed_time / 60.0
        if mins > 25:
            reward -= 0.1  # mild time pressure after 25 min
        if mins > 35:
            reward -= 0.3  # strong pressure after 35 min (total -0.4/step)
        if mins > 45:
            reward -= 0.5  # very strong after 45 min (total -0.9/step)

        # Tick cooldowns
        tick_time = TURN_TIME_ENTITY if self.spawned_entity >= 0 else TURN_TIME_NORMAL
        self.entity_cooldowns = np.maximum(0, self.entity_cooldowns - tick_time)

        # Episode truncation (time-based primary, turn-based safety net)
        if self.turn_count >= MAX_TURNS or self.elapsed_time >= MAX_SESSION_TIME:
            truncated = True
            reward -= 5.0  # failed to exit voluntarily — very big penalty

        # Mood out of bounds → emergency exit
        if self.mood < 0.1 or self.mood > 0.97:
            terminated = True
            reward -= 0.5

        return self._get_obs(), float(reward), terminated, truncated, info

    def _step_narrative(self):
        """Simulate a narrative step (no LLM). Returns incremental reward."""
        self.narrative_count += 1
        reward = 0.0

        # Simulate terminal/experiment usage based on location
        if self.current_location == 1:  # computer_terminal
            if self._rng.random() < 0.6:
                cmd_type = self._rng.integers(0, 13)
                self.terminal_cmd_count += 1
                if cmd_type not in self.terminal_cmd_types:
                    self.terminal_cmd_types.add(cmd_type)
                    reward += 1.5  # diverse command
                self.has_terminal_result = True

        elif self.current_location == 5:  # lab_experiment
            if self._rng.random() < 0.5:
                station = self._rng.integers(0, 6)
                self.experiment_cmd_count += 1
                if station not in self.experiment_types:
                    self.experiment_types.add(station)
                    reward += 1.5  # diverse experiment
                self.has_experiment_result = True

        return reward

    def _get_obs(self):
        obs = np.zeros(OBS_DIM, dtype=np.float32)

        # Temporal
        obs[0] = min(self.turn_count / 60.0, 1.0)
        obs[1] = min(self.elapsed_time / 3600.0, 1.0)
        obs[2] = min(self.narrative_count / 3.0, 1.0)
        obs[3] = min(self.entity_turn_count / 6.0, 1.0)

        # Current location one-hot
        obs[4 + self.current_location] = 1.0

        # Visited bitvector
        obs[11:18] = self.visited.astype(np.float32)

        # Mood
        obs[18] = self.mood
        if len(self.mood_history) >= 5:
            obs[19] = np.clip((self.mood - self.mood_history[-5]) + 0.5, 0, 1)
        else:
            obs[19] = 0.5

        # Entity one-hot (none + 4)
        if self.spawned_entity >= 0:
            obs[20 + self.spawned_entity + 1] = 1.0
        else:
            obs[20] = 1.0  # "none" slot

        # Entity cooldowns
        obs[25:29] = np.minimum(self.entity_cooldowns / 300.0, 1.0)

        # Conversation / tool use
        obs[29] = min(len(self.mood_history) / 30.0, 1.0)
        obs[30] = min(self.terminal_cmd_count / 13.0, 1.0)
        obs[31] = min(self.experiment_cmd_count / 6.0, 1.0)
        obs[32] = 1.0 if self.has_terminal_result else 0.0
        obs[33] = 1.0 if self.has_experiment_result else 0.0

        # Session metrics
        obs[34] = min(self.elapsed_time / 3600.0, 1.0)
        obs[35] = min(self.silence_count / 10.0, 1.0)
        obs[36] = min(self.turns_in_location / 10.0, 1.0)
        obs[37] = min(self.entity_spawn_count.sum() / 3.0, 1.0)

        # Flags
        obs[38] = 1.0 if self.in_silence else 0.0
        obs[39] = 1.0 if self.spawned_entity >= 0 else 0.0
        obs[40] = 0.0  # uninvited_checked (not used in sim)
        obs[41] = self.hour_of_day / 24.0

        # Diversity metrics
        n_visited = self.visited.sum()
        obs[42] = n_visited / NUM_LOCATIONS
        obs[43] = min(len(self.terminal_cmd_types) / 13.0, 1.0)
        obs[44] = min(len(self.experiment_types) / 6.0, 1.0)

        # Exit readiness signal — helps RL learn optimal exit timing
        mins = self.elapsed_time / 60.0
        total_spawns = int(self.entity_spawn_count.sum())
        obs[45] = 1.0 if (mins >= 20 and n_visited >= 4) else 0.0  # in optimal window
        obs[46] = 1.0 if (mins >= 20 and self.silence_count >= 1 and total_spawns >= 1) else 0.0  # full criteria met
        obs[47] = min(max(0, mins - 20) / 20.0, 1.0)  # time past optimal start (0→1 over 20-40 min)

        # 48-63 reserved (zeros)
        return obs
