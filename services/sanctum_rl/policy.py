"""
SanctumMLP — Tiny PPO policy for sanctum behavior.

~8,500 parameters. Input(64) → 2×Linear(64) → action/entity/value heads.
"""

from __future__ import annotations

import torch
import torch.nn as nn


class SanctumMLP(nn.Module):
    """Sanctum behavior policy — actor-critic MLP."""

    def __init__(self, obs_dim: int = 64, n_actions: int = 12, n_entities: int = 4):
        super().__init__()
        self.obs_dim = obs_dim

        self.encoder = nn.Sequential(
            nn.Linear(obs_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 64),
            nn.ReLU(),
        )

        self.action_head = nn.Linear(64, n_actions)
        self.entity_head = nn.Linear(64, n_entities)
        self.value_head = nn.Linear(64, 1)

    def forward(self, x):
        hidden = self.encoder(x)
        return (
            self.action_head(hidden),
            self.entity_head(hidden),
            self.value_head(hidden),
        )

    def encode_observations(self, x):
        """PufferLib API — encode observations to hidden state."""
        return self.encoder(x), None

    def decode_actions(self, hidden, lookup, concat=None):
        """PufferLib API — decode hidden state to action logits + value."""
        action_logits = self.action_head(hidden)
        entity_logits = self.entity_head(hidden)
        value = self.value_head(hidden)
        return action_logits, entity_logits, value
