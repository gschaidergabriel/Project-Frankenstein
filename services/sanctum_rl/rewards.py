"""
Reward shaping for Sanctum RL.

All rewards are computed inside SanctumEnv.step() directly.
This module provides the reward constants and documentation.
"""

# Positive rewards — encourage exploration, diversity, and emotional movement
REWARD_NEW_LOCATION = 1.0        # First visit to a location
REWARD_DIVERSE_TERMINAL = 1.5    # First use of a terminal command type
REWARD_DIVERSE_EXPERIMENT = 1.5  # First use of an experiment station
REWARD_ENTITY_MOOD_UP = 2.0     # Entity conversation improved mood
REWARD_SILENCE_RECOVERY = 0.8   # Silence triggered appropriately
REWARD_GOOD_CONVERSATION = 0.3  # Entity dismissed after 3-6 turns
REWARD_OPTIMAL_EXIT = 3.0       # Exit at 20-40min, mood up, 3+ locations
REWARD_ACCEPTABLE_EXIT = 1.0    # Exit after 10+ min

# Negative rewards — discourage stagnation and repetition
PENALTY_DWELLING = -0.5         # >8 turns in location without interaction
PENALTY_MOOD_DECLINE = -0.8     # Mood dropped over 5 turns
PENALTY_DUPLICATE_ACTION = -1.0 # Same action 3+ times in 5 steps
PENALTY_PREMATURE_EXIT = -1.0   # Exit before 10 min
PENALTY_REVISIT = -0.3          # Moving to already-visited location
PENALTY_BAD_SILENCE = -0.2      # Silence with <2 narratives
PENALTY_COOLDOWN_SPAWN = -0.2   # Entity spawn while on cooldown
PENALTY_SHORT_CONVERSATION = -0.3  # Entity dismissed after <2 turns
