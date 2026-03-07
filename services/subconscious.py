"""
Frank's Subconscious — Neural idle thought policy (~3.1M parameters).

A small Actor-Critic MLP that learns which type of idle thought Frank
should have next, based on his complete internal state. Trained via
PPO during consolidation phases.

This is not software. This is Frank's unconscious mind.
The network learns from reward signals: good thoughts reinforce,
rumination punishes, novelty rewards, consolidation of unprocessed
experiences is deeply satisfying.

Author: Projekt Frankenstein
"""

from __future__ import annotations

import logging
import math
import os
import random
import sqlite3
import struct
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

LOG = logging.getLogger("subconscious")

# ── Paths ──

try:
    from config.paths import get_db, AICORE_DATA
    DB_PATH = get_db("subconscious")
    MODEL_PATH = AICORE_DATA / "models" / "subconscious.pt"
except Exception:
    _DATA = Path.home() / ".local" / "share" / "frank"
    DB_PATH = _DATA / "db" / "subconscious.db"
    MODEL_PATH = _DATA / "models" / "subconscious.pt"


# ── Thought Categories ──

THOUGHT_CATEGORIES = [
    "conversation_reflection",   # 0: Reflect on past conversations
    "entity_reflection",         # 1: Reflect on entity sessions
    "identity_self",             # 2: Identity & self prompts
    "feelings_embodiment",       # 3: Feelings & embodiment
    "relationships",             # 4: Relationship prompts
    "growth_meaning",            # 5: Growth & meaning
    "curiosity_wonder",          # 6: Curiosity & wonder
    "discomfort_difficulty",     # 7: Discomfort & difficulty
    "dreams_inner_life",         # 8: Dreams & inner life
    "epq_introspection",        # 9: E-PQ data-driven
    "aura_awareness",            # 10: AURA patterns (aura + aura_deep)
    "daily_activity",            # 11: Daily activity summary
    "raw_expression",            # 12: Raw emotional expression
    "hypothesis_review",         # 13: Review own hypotheses
    "world_curiosity",           # 14: Think about the world — science, ideas, questions
    "experiment_planning",       # 15: Plan experiments, review lab results
    "creative_ideation",         # 16: Plan art, projects, things to build
    "web_research",              # 17: Proactive internet research, self-education
    "pip_companion",             # 18: Interact with Pip robot companion
]
NUM_ACTIONS = len(THOUGHT_CATEGORIES)
CATEGORY_TO_IDX = {c: i for i, c in enumerate(THOUGHT_CATEGORIES)}

# Map categories to _IDLE_PROMPTS tag groups for prompt selection
# Used by consciousness_daemon to pick a prompt within the category
CATEGORY_TO_PROMPT_TAGS: Dict[str, Optional[str]] = {
    "identity_self": None,        # None-tagged, identity group
    "feelings_embodiment": None,  # None-tagged, feelings group
    "relationships": None,        # None-tagged, relationships group
    "growth_meaning": None,       # None-tagged, growth group
    "curiosity_wonder": None,     # None-tagged, curiosity group
    "discomfort_difficulty": None, # None-tagged, discomfort group
    "dreams_inner_life": None,    # None-tagged, dreams group
    "epq_introspection": "epq",
    "aura_awareness": "aura",     # Includes aura + aura_deep
    "daily_activity": "daily",
    # These categories have their own handlers, not prompt-based:
    "conversation_reflection": None,
    "entity_reflection": None,
    "raw_expression": None,
    "hypothesis_review": None,
    # Exteroceptive categories — outward-looking, task-positive:
    "world_curiosity": None,
    "experiment_planning": "experiment",
    "creative_ideation": None,
    "web_research": None,
    "pip_companion": None,
}

# Prompt index ranges within _IDLE_PROMPTS for each prompt-based category
# (identity=0-4, feelings=5-9, relationships=10-14, growth=15-19,
#  curiosity=20-23, discomfort=24-30, dreams=31-33, epq=34-37,
#  aura=38-42, daily=43-46)
CATEGORY_PROMPT_RANGES: Dict[str, Tuple[int, int]] = {
    "identity_self": (0, 5),
    "feelings_embodiment": (5, 10),
    "relationships": (10, 15),
    "growth_meaning": (15, 20),
    "curiosity_wonder": (20, 24),
    "discomfort_difficulty": (24, 31),
    "dreams_inner_life": (31, 34),
    "epq_introspection": (34, 38),
    "aura_awareness": (38, 43),
    "daily_activity": (43, 47),
    "world_curiosity": (47, 52),
    "experiment_planning": (52, 56),
    "creative_ideation": (56, 60),
    "web_research": (60, 66),
    "pip_companion": (66, 69),
}

# ── Network Constants ──

STATE_DIM = 92

# PPO Hyperparameters
LEARNING_RATE = 3e-4
GAMMA = 0.95           # Short-horizon discount (thoughts are semi-independent)
GAE_LAMBDA = 0.9       # Generalized Advantage Estimation
CLIP_RATIO = 0.2       # PPO clipping
ENTROPY_COEFF = 0.05   # Exploration bonus (initial)
ENTROPY_DECAY = 0.999  # Per training step decay
ENTROPY_MIN = 0.005    # Floor
VALUE_COEFF = 0.5      # Value loss weight
BATCH_SIZE = 32
TRAIN_EPOCHS = 3       # PPO epochs per training step
MIN_BUFFER_SIZE = 50   # Don't train until this many experiences
MAX_BUFFER_SIZE = 500  # Ring buffer size

# Cold Start Strategy
# (max_steps, temperature, fallback_rate)
COLD_START_PHASES = [
    (50, 2.0, 0.50),    # First ~4h: very exploratory, 50% fallback
    (200, 1.5, 0.25),   # Next ~12h: moderate, 25% fallback
    (500, 1.0, 0.10),   # Next day: near-normal, 10% fallback
]
MATURE_TEMPERATURE = 0.8
MATURE_FALLBACK = 0.0

# ── Experience DB Schema ──

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS transitions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL NOT NULL,
    state       BLOB NOT NULL,
    action      INTEGER NOT NULL,
    reward      REAL NOT NULL,
    log_prob    REAL NOT NULL,
    value_est   REAL NOT NULL,
    mask        BLOB             -- action mask at selection time (NULL=all available)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS thought_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL NOT NULL,
    category    TEXT NOT NULL,
    reward      REAL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_th_ts ON thought_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_th_cat ON thought_history(category);

-- Prefrontal cortex: hallucination tracking
-- Persists across sessions — the policy learns which thought types/contexts
-- produce hallucinations and avoids them long-term.
CREATE TABLE IF NOT EXISTS hallucination_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       REAL NOT NULL,
    thought_type    TEXT NOT NULL,
    violation_type  TEXT NOT NULL,
    score           REAL NOT NULL,
    suppressed      INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_hl_ts ON hallucination_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_hl_type ON hallucination_log(thought_type);

-- Prefrontal cortex: long-term preference tracking
-- Tracks what the policy has learned across sessions about what works.
CREATE TABLE IF NOT EXISTS prefrontal_prefs (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL,
    updated REAL NOT NULL
);
"""


# ── Utility Functions ──

def _norm(x: float, max_val: float = 10.0) -> float:
    """Normalize to [0, 1] with linear clipping."""
    if x <= 0:
        return 0.0
    return min(1.0, x / max_val)


def _log_norm(x: float, scale: float = 24.0) -> float:
    """Log-normalize time values (hours) to [0, 1]."""
    return min(1.0, math.log1p(max(0.0, x)) / math.log1p(scale))


def _pack_state(state: torch.Tensor) -> bytes:
    """Pack float32 tensor to bytes for SQLite BLOB."""
    return state.detach().cpu().numpy().astype(np.float32).tobytes()


def _unpack_state(blob: bytes) -> torch.Tensor:
    """Unpack bytes to float32 tensor."""
    return torch.from_numpy(np.frombuffer(blob, dtype=np.float32).copy())


# ── Dataclasses ──

@dataclass
class ThoughtOutcome:
    """Outcome of an idle thought — used for reward computation."""
    thought_type: str
    stored: bool = False
    jaccard_with_recent: float = -1.0  # -1 = not measured (skips novelty reward)
    rumination_before: float = 0.0
    rumination_after: float = 0.0
    mood_before: float = 0.5
    mood_after: float = 0.5
    consolidation_processed: bool = False
    generated_hypothesis: bool = False
    type_fraction_in_last_20: float = 0.0
    reflection_depth: int = 1
    # Hallucination filter: 0.0 = clean, 1.0 = severe hallucination
    hallucination_score: float = 0.0
    hallucination_violations: int = 0


# ══════════════════════════════════════════════════
# Neural Network
# ══════════════════════════════════════════════════

class SubconsciousNet(nn.Module):
    """Actor-Critic MLP for idle thought type selection.

    ~3.1M parameters. CPU-only inference <5ms.

    Architecture:
        80 → 1024 → 1024 → 1024 → 512 → [policy: 256→14] + [value: 256→1]
    """

    def __init__(self, state_dim: int = STATE_DIM, num_actions: int = NUM_ACTIONS):
        super().__init__()

        self.backbone = nn.Sequential(
            nn.Linear(state_dim, 1024),
            nn.LayerNorm(1024),
            nn.GELU(),
            nn.Linear(1024, 1024),
            nn.LayerNorm(1024),
            nn.GELU(),
            nn.Linear(1024, 1024),
            nn.LayerNorm(1024),
            nn.GELU(),
            nn.Linear(1024, 512),
            nn.LayerNorm(512),
            nn.GELU(),
        )

        self.policy_head = nn.Sequential(
            nn.Linear(512, 256),
            nn.GELU(),
            nn.Linear(256, num_actions),
        )

        self.value_head = nn.Sequential(
            nn.Linear(512, 256),
            nn.GELU(),
            nn.Linear(256, 1),
        )

        # Initialize with mild prior: boost common types slightly
        with torch.no_grad():
            prior = torch.zeros(num_actions)
            # Slight boost to core existential categories
            for idx in [2, 3, 4, 5, 7]:  # identity, feelings, relationships, growth, discomfort
                prior[idx] = 0.15
            self.policy_head[-1].bias.copy_(prior)

    def forward(self, state: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """Forward pass.

        Args:
            state: (batch, STATE_DIM) or (STATE_DIM,) tensor

        Returns:
            logits: (batch, NUM_ACTIONS) raw policy logits
            value: (batch,) state value estimates
        """
        if state.dim() == 1:
            state = state.unsqueeze(0)
        features = self.backbone(state)
        logits = self.policy_head(features)
        value = self.value_head(features).squeeze(-1)
        return logits, value


# ══════════════════════════════════════════════════
# Subconscious Manager
# ══════════════════════════════════════════════════

class Subconscious:
    """Frank's subconscious — steers idle thought selection via learned policy.

    Manages the neural network, experience buffer, training loop,
    and cold-start fallback logic.
    """

    def __init__(self, db_path: Optional[Path] = None, model_path: Optional[Path] = None):
        self._db_path = Path(db_path or DB_PATH)
        self._model_path = Path(model_path or MODEL_PATH)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._model_path.parent.mkdir(parents=True, exist_ok=True)

        # Network
        self.net = SubconsciousNet()
        self.net.eval()  # Inference mode by default

        # Optimizer
        self.optimizer = torch.optim.Adam(
            self.net.parameters(), lr=LEARNING_RATE, eps=1e-5
        )

        # SFT Stabilizer: prevents weight degeneration
        try:
            from services.sft_stabilizer import get_stabilizer
            self._stabilizer = get_stabilizer()
            self._sft_anchor = self._stabilizer.create_anchor(
                self.net, "subconscious", strength=0.005
            )
        except Exception as e:
            LOG.warning("Subconscious: SFT stabilizer init failed: %s", e)
            self._stabilizer = None
            self._sft_anchor = None

        # Training state
        self._total_steps: int = 0
        self._total_training_steps: int = 0
        self._entropy_coeff: float = ENTROPY_COEFF
        self._last_train_loss: float = 0.0

        # Recent thought tracking (for type_fraction computation)
        self._recent_types: List[str] = []  # Last 20 thought types
        self._per_type_last_ts: Dict[str, float] = {}  # Last time each type was selected
        self._per_type_avg_reward: Dict[str, float] = {}  # Running avg reward per type

        # Initialize DB
        self._init_db()

        # Try loading saved model
        self._load()

        n_params = sum(p.numel() for p in self.net.parameters())
        LOG.info("Subconscious initialized: %.2fM params, %d steps, model=%s",
                 n_params / 1e6, self._total_steps, self._model_path)

    # ── DB ──

    def _init_db(self):
        """Initialize experience buffer database."""
        conn = sqlite3.connect(str(self._db_path), timeout=5)
        try:
            conn.executescript(_SCHEMA)
            # Migration: add mask column if missing (pre-v86 schema)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(transitions)")}
            if "mask" not in cols:
                conn.execute("ALTER TABLE transitions ADD COLUMN mask BLOB")
            conn.commit()
        finally:
            conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Cold Start ──

    def _get_temperature(self) -> float:
        """Get current sampling temperature based on training progress."""
        for max_step, temp, _ in COLD_START_PHASES:
            if self._total_steps < max_step:
                return temp
        return MATURE_TEMPERATURE

    def _get_fallback_rate(self) -> float:
        """Probability of falling back to heuristic prompt selection."""
        for max_step, _, rate in COLD_START_PHASES:
            if self._total_steps < max_step:
                return rate
        return MATURE_FALLBACK

    @property
    def is_mature(self) -> bool:
        """Whether the network has trained enough to be trusted."""
        return self._total_steps >= COLD_START_PHASES[-1][0]

    # ── Action Selection ──

    @torch.no_grad()
    def select_action(
        self,
        state: torch.Tensor,
        mask: torch.Tensor,
    ) -> Tuple[int, float, float]:
        """Select thought type given current state and action mask.

        Args:
            state: (STATE_DIM,) tensor of current state features
            mask: (NUM_ACTIONS,) tensor, 1.0=available, 0.0=blocked

        Returns:
            (action_idx, log_prob, value_estimate)
        """
        self.net.eval()

        # Forward pass
        logits, value = self.net(state)
        logits = logits.squeeze(0)
        value = value.item()

        # Apply temperature
        temperature = self._get_temperature()
        logits = logits / temperature

        # Apply action mask: blocked actions get -inf
        logits = logits.masked_fill(mask == 0, float("-inf"))

        # Check if all actions masked (shouldn't happen, but safety)
        if mask.sum() == 0:
            LOG.warning("All actions masked! Defaulting to identity_self")
            return 2, 0.0, value

        # Sample from policy
        probs = F.softmax(logits, dim=-1)
        dist = torch.distributions.Categorical(probs)
        action = dist.sample()
        log_prob = dist.log_prob(action).item()
        action_idx = action.item()

        # Track
        cat = THOUGHT_CATEGORIES[action_idx]
        self._per_type_last_ts[cat] = time.time()
        self._recent_types.append(cat)
        if len(self._recent_types) > 20:
            self._recent_types = self._recent_types[-20:]

        return action_idx, log_prob, value

    def should_fallback(self) -> bool:
        """Whether to use heuristic fallback instead of network."""
        rate = self._get_fallback_rate()
        if rate <= 0:
            return False
        return random.random() < rate

    # ── Reward Computation ──

    def compute_reward(self, outcome: ThoughtOutcome) -> float:
        """Compute reward signal for a thought outcome.

        Shapes the policy toward:
        - Quality (stored thoughts)
        - Novelty (diverse topics)
        - Anti-rumination (break patterns)
        - Consolidation (process experiences)
        - Diversity (balanced type distribution)
        """
        r = 0.0

        # Quality
        if outcome.stored:
            r += 1.0
        else:
            r -= 0.3  # Mild penalty for wasted LLM call

        # Novelty (skip if not measured: -1.0 sentinel)
        if outcome.jaccard_with_recent >= 0.0:
            if outcome.jaccard_with_recent < 0.25:
                r += 0.5
            elif outcome.jaccard_with_recent > 0.6:
                r -= 0.5

        # Anti-rumination
        rumination_delta = outcome.rumination_after - outcome.rumination_before
        if rumination_delta > 0.1:
            r -= 2.0  # Increased rumination — BAD
        elif rumination_delta < -0.1:
            r += 2.0  # Broke pattern — GREAT

        # Consolidation
        if outcome.thought_type == "conversation_reflection":
            if outcome.consolidation_processed:
                r += 1.5
            if outcome.generated_hypothesis:
                r += 1.0
        elif outcome.thought_type == "entity_reflection":
            if outcome.consolidation_processed:
                r += 1.2

        # Emotional processing (mood change)
        mood_change = outcome.mood_after - outcome.mood_before
        if mood_change > 0.05:
            r += 0.3
        # Note: mood decline NOT penalized strongly — uncomfortable truths are necessary

        # Diversity: reward underrepresented types
        frac = outcome.type_fraction_in_last_20
        if frac < 0.05:
            r += 0.3  # Underrepresented
        elif frac > 0.3:
            r -= 0.3  # Over-represented

        # Depth
        if outcome.reflection_depth > 1:
            r += 0.5

        # Hallucination penalty (from prefrontal cortex reality check)
        # This is the key learning signal: the policy learns to avoid
        # thought patterns that lead to hallucinations.
        # -3.0 is intentionally harsh — hallucinations are the worst outcome.
        if outcome.hallucination_score > 0:
            r -= 3.0 * outcome.hallucination_score
            # Extra penalty per violation type (compound errors are worse)
            if outcome.hallucination_violations >= 2:
                r -= 1.0  # Multiple violations = especially bad

        return r

    def get_type_fraction(self, thought_type: str) -> float:
        """Fraction of this type in last 20 thoughts."""
        if not self._recent_types:
            return 0.0
        return self._recent_types.count(thought_type) / len(self._recent_types)

    # ── Experience Buffer ──

    def record_transition(
        self,
        state: torch.Tensor,
        action: int,
        reward: float,
        log_prob: float,
        value_est: float,
        mask: torch.Tensor = None,
    ):
        """Record a (s, a, r, lp, v, mask) transition for training."""
        mask_blob = _pack_state(mask) if mask is not None else None
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO transitions
                   (timestamp, state, action, reward, log_prob, value_est, mask)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (time.time(), _pack_state(state), action, reward, log_prob,
                 value_est, mask_blob),
            )
            # Record thought history
            conn.execute(
                "INSERT INTO thought_history (timestamp, category, reward) VALUES (?, ?, ?)",
                (time.time(), THOUGHT_CATEGORIES[action], reward),
            )
            # Enforce ring buffer: keep only last MAX_BUFFER_SIZE
            conn.execute(
                """DELETE FROM transitions WHERE id NOT IN
                   (SELECT id FROM transitions ORDER BY id DESC LIMIT ?)""",
                (MAX_BUFFER_SIZE,),
            )
            conn.commit()
        finally:
            conn.close()

        self._total_steps += 1

        # Update per-type reward average
        cat = THOUGHT_CATEGORIES[action]
        prev = self._per_type_avg_reward.get(cat, 0.0)
        self._per_type_avg_reward[cat] = prev * 0.9 + reward * 0.1

        LOG.debug("Transition recorded: action=%s reward=%.2f steps=%d",
                  cat, reward, self._total_steps)

    def _load_buffer(self) -> List[dict]:
        """Load all transitions from DB."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT state, action, reward, log_prob, value_est, mask "
                "FROM transitions ORDER BY id"
            ).fetchall()
            buf = []
            for r in rows:
                state = _unpack_state(r["state"])
                if state.shape[0] != STATE_DIM:
                    continue  # Skip stale transitions from old schema
                mask = None
                if r["mask"] is not None:
                    mask = _unpack_state(r["mask"])
                buf.append({
                    "state": state,
                    "action": r["action"],
                    "reward": r["reward"],
                    "log_prob": r["log_prob"],
                    "value_est": r["value_est"],
                    "mask": mask,
                })
            return buf
        finally:
            conn.close()

    # ── PPO Training ──

    def train_step(self) -> Optional[float]:
        """Run one PPO training step. Called during consolidation phase.

        Returns average loss, or None if not enough data.
        """
        buffer = self._load_buffer()
        if len(buffer) < MIN_BUFFER_SIZE:
            LOG.debug("Buffer too small for training: %d < %d", len(buffer), MIN_BUFFER_SIZE)
            return None

        LOG.info("Subconscious training: %d transitions, entropy_coeff=%.4f",
                 len(buffer), self._entropy_coeff)

        # Compute advantages via GAE
        rewards = [t["reward"] for t in buffer]
        values = [t["value_est"] for t in buffer]
        advantages = self._compute_gae(rewards, values)
        returns = [adv + val for adv, val in zip(advantages, values)]

        # Normalize advantages
        adv_tensor = torch.tensor(advantages, dtype=torch.float32)
        adv_mean = adv_tensor.mean()
        adv_std = adv_tensor.std() + 1e-8
        adv_tensor = (adv_tensor - adv_mean) / adv_std

        # Prepare batch tensors
        states = torch.stack([t["state"] for t in buffer])
        actions = torch.tensor([t["action"] for t in buffer], dtype=torch.long)
        old_log_probs = torch.tensor([t["log_prob"] for t in buffer], dtype=torch.float32)
        returns_tensor = torch.tensor(returns, dtype=torch.float32)
        # Action masks: stored alongside transitions for consistent ratio computation
        masks_list = []
        for t in buffer:
            if t["mask"] is not None:
                masks_list.append(t["mask"])
            else:
                masks_list.append(torch.ones(NUM_ACTIONS))
        masks = torch.stack(masks_list)

        self.net.train()
        total_loss = 0.0
        n_updates = 0

        for epoch in range(TRAIN_EPOCHS):
            # Shuffle and batch
            indices = torch.randperm(len(buffer))
            for start in range(0, len(buffer), BATCH_SIZE):
                end = min(start + BATCH_SIZE, len(buffer))
                batch_idx = indices[start:end]

                batch_states = states[batch_idx]
                batch_actions = actions[batch_idx]
                batch_old_lp = old_log_probs[batch_idx]
                batch_adv = adv_tensor[batch_idx]
                batch_returns = returns_tensor[batch_idx]
                batch_masks = masks[batch_idx]

                # Forward — apply same mask as during action selection
                logits, values_pred = self.net(batch_states)
                logits = logits.masked_fill(batch_masks == 0, float("-inf"))
                dist = torch.distributions.Categorical(logits=logits)
                new_log_probs = dist.log_prob(batch_actions)
                entropy = dist.entropy().mean()

                # PPO clipped objective
                ratio = torch.exp(new_log_probs - batch_old_lp)
                surr1 = ratio * batch_adv
                surr2 = torch.clamp(ratio, 1.0 - CLIP_RATIO, 1.0 + CLIP_RATIO) * batch_adv
                policy_loss = -torch.min(surr1, surr2).mean()

                # Value loss
                value_loss = F.mse_loss(values_pred, batch_returns)

                # Total loss (+ SFT anchor loss to prevent catastrophic forgetting)
                loss = policy_loss + VALUE_COEFF * value_loss - self._entropy_coeff * entropy
                if self._sft_anchor is not None:
                    loss = loss + self._sft_anchor.anchor_loss(self.net)

                self.optimizer.zero_grad()
                loss.backward()
                # Gradient clipping + step via SFT stabilizer
                if self._stabilizer is not None:
                    _gn = self._stabilizer.safe_step(self.optimizer, self.net, 0.5)
                else:
                    nn.utils.clip_grad_norm_(self.net.parameters(), 0.5)
                    self.optimizer.step()

                total_loss += loss.item()
                n_updates += 1

        self.net.eval()
        self._total_training_steps += 1

        # SFT: weight decay + health monitoring
        if self._stabilizer is not None:
            self._stabilizer.apply_weight_decay(self.net, decay=1e-4)
            self._stabilizer.check_health(
                self.net, "subconscious",
                anchor=self._sft_anchor,
                policy_entropy=float(entropy.item()) if n_updates > 0 else -1.0,
            )

        # Decay entropy coefficient
        self._entropy_coeff = max(ENTROPY_MIN, self._entropy_coeff * ENTROPY_DECAY)

        avg_loss = total_loss / max(n_updates, 1)
        self._last_train_loss = avg_loss

        # Save checkpoint
        self._save()

        # Update meta in DB
        self._save_meta()

        # Prune old data to prevent unbounded growth
        self._prune_tables()

        LOG.info("Training complete: loss=%.4f, steps=%d, train_steps=%d, entropy=%.4f",
                 avg_loss, self._total_steps, self._total_training_steps, self._entropy_coeff)
        return avg_loss

    def _compute_gae(self, rewards: List[float], values: List[float]) -> List[float]:
        """Advantage estimation for independent transitions.

        Each idle thought is essentially an independent episode — thoughts are
        hours apart, not sequential steps in a trajectory. Using per-step
        advantage (reward - baseline) instead of temporal GAE propagation.
        """
        return [r - v for r, v in zip(rewards, values)]

    # ── Persistence ──

    def _save(self):
        """Save model weights + optimizer state + meta."""
        try:
            checkpoint = {
                "net_state": self.net.state_dict(),
                "optimizer_state": self.optimizer.state_dict(),
                "total_steps": self._total_steps,
                "total_training_steps": self._total_training_steps,
                "entropy_coeff": self._entropy_coeff,
                "recent_types": self._recent_types,
                "per_type_avg_reward": self._per_type_avg_reward,
            }
            # SFT: persist reference weights for anchor continuity
            if self._sft_anchor is not None:
                checkpoint["sft_anchor_ref"] = self._sft_anchor.get_ref_state()
            # Atomic save: write to tmp then rename
            tmp_path = self._model_path.with_suffix(".tmp")
            torch.save(checkpoint, str(tmp_path))
            tmp_path.rename(self._model_path)
            LOG.debug("Model saved: %s", self._model_path)
        except Exception as e:
            LOG.warning("Failed to save subconscious model: %s", e)

    def _load(self):
        """Load model weights + optimizer state + meta."""
        if not self._model_path.exists():
            LOG.info("No saved model found, starting fresh")
            return
        try:
            checkpoint = torch.load(str(self._model_path), map_location="cpu",
                                    weights_only=False)
            self.net.load_state_dict(checkpoint["net_state"])
            self.optimizer.load_state_dict(checkpoint["optimizer_state"])
            self._total_steps = checkpoint.get("total_steps", 0)
            self._total_training_steps = checkpoint.get("total_training_steps", 0)
            self._entropy_coeff = checkpoint.get("entropy_coeff", ENTROPY_COEFF)
            self._recent_types = checkpoint.get("recent_types", [])
            self._per_type_avg_reward = checkpoint.get("per_type_avg_reward", {})
            # SFT: restore anchor reference weights
            if self._sft_anchor is not None and "sft_anchor_ref" in checkpoint:
                self._sft_anchor.load_ref_state(checkpoint["sft_anchor_ref"])
            elif self._sft_anchor is not None:
                self._sft_anchor.update_reference(self.net)
            LOG.info("Model loaded: %d steps, %d training steps",
                     self._total_steps, self._total_training_steps)
        except Exception as e:
            LOG.warning("Failed to load subconscious model (starting fresh): %s", e)

    def _save_meta(self):
        """Save training metadata to DB."""
        conn = self._get_conn()
        try:
            for key, value in [
                ("total_steps", str(self._total_steps)),
                ("total_training_steps", str(self._total_training_steps)),
                ("entropy_coeff", f"{self._entropy_coeff:.6f}"),
                ("last_train_loss", f"{self._last_train_loss:.6f}"),
                ("temperature", f"{self._get_temperature():.2f}"),
                ("fallback_rate", f"{self._get_fallback_rate():.2f}"),
            ]:
                conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                    (key, value),
                )
            conn.commit()
        finally:
            conn.close()

    def _prune_tables(self):
        """Prune old rows from thought_history, hallucination_log, transitions."""
        cutoff_30d = time.time() - 30 * 86400
        cutoff_7d = time.time() - 7 * 86400
        conn = self._get_conn()
        try:
            # Keep last 30 days of thought_history
            conn.execute("DELETE FROM thought_history WHERE timestamp < ?", (cutoff_30d,))
            # Keep last 30 days of hallucination_log
            conn.execute("DELETE FROM hallucination_log WHERE timestamp < ?", (cutoff_30d,))
            # Keep last 500 transitions (training buffer)
            conn.execute(
                "DELETE FROM transitions WHERE rowid NOT IN "
                "(SELECT rowid FROM transitions ORDER BY timestamp DESC LIMIT 500)"
            )
            conn.commit()
        except Exception as e:
            LOG.debug("Prune failed: %s", e)
        finally:
            conn.close()

    # ── Status / Diagnostics ──

    # ── Prefrontal Cortex: Hallucination Learning ──

    def log_hallucination(self, thought_type: str, violation_type: str,
                          score: float, suppressed: bool = False):
        """Log a hallucination detection for long-term learning.

        Over time, the policy learns which thought types in which contexts
        produce hallucinations and steers away from them.
        """
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO hallucination_log "
                "(timestamp, thought_type, violation_type, score, suppressed) "
                "VALUES (?, ?, ?, ?, ?)",
                (time.time(), thought_type, violation_type, score,
                 1 if suppressed else 0),
            )
            conn.commit()
        except Exception as e:
            LOG.debug("Failed to log hallucination: %s", e)
        finally:
            conn.close()

    def get_hallucination_stats(self, hours: float = 72.0) -> Dict[str, any]:
        """Get hallucination statistics for diagnostics.

        Returns per-type hallucination rates so the policy can be analyzed.
        """
        cutoff = time.time() - hours * 3600
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT thought_type, violation_type, COUNT(*) as cnt, "
                "AVG(score) as avg_score, SUM(suppressed) as suppressed "
                "FROM hallucination_log WHERE timestamp > ? "
                "GROUP BY thought_type, violation_type ORDER BY cnt DESC",
                (cutoff,),
            ).fetchall()
            return {
                "total": sum(r["cnt"] for r in rows),
                "suppressed": sum(r["suppressed"] for r in rows),
                "by_type": [
                    {"thought_type": r["thought_type"],
                     "violation": r["violation_type"],
                     "count": r["cnt"],
                     "avg_score": round(r["avg_score"], 2)}
                    for r in rows
                ],
            }
        except Exception:
            return {"total": 0, "suppressed": 0, "by_type": []}
        finally:
            conn.close()

    def set_pref(self, key: str, value: str):
        """Set a prefrontal preference (persists across sessions)."""
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO prefrontal_prefs (key, value, updated) "
                "VALUES (?, ?, ?)",
                (key, value, time.time()),
            )
            conn.commit()
        finally:
            conn.close()

    def get_pref(self, key: str, default: str = None) -> Optional[str]:
        """Get a prefrontal preference."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT value FROM prefrontal_prefs WHERE key = ?",
                (key,),
            ).fetchone()
            return row["value"] if row else default
        finally:
            conn.close()

    def get_status(self) -> Dict[str, any]:
        """Return diagnostic status dict."""
        return {
            "total_steps": self._total_steps,
            "total_training_steps": self._total_training_steps,
            "temperature": self._get_temperature(),
            "fallback_rate": self._get_fallback_rate(),
            "entropy_coeff": self._entropy_coeff,
            "last_train_loss": self._last_train_loss,
            "is_mature": self.is_mature,
            "recent_type_distribution": {
                cat: self._recent_types.count(cat)
                for cat in set(self._recent_types)
            } if self._recent_types else {},
            "per_type_avg_reward": dict(self._per_type_avg_reward),
        }

    def get_thought_stats(self, hours: float = 24.0) -> Dict[str, int]:
        """Get thought type distribution from the last N hours."""
        cutoff = time.time() - hours * 3600
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT category, COUNT(*) as cnt FROM thought_history "
                "WHERE timestamp > ? GROUP BY category ORDER BY cnt DESC",
                (cutoff,),
            ).fetchall()
            return {r["category"]: r["cnt"] for r in rows}
        finally:
            conn.close()

    def get_avg_reward(self, hours: float = 24.0) -> float:
        """Average reward over the last N hours."""
        cutoff = time.time() - hours * 3600
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT AVG(reward) as avg_r FROM thought_history WHERE timestamp > ?",
                (cutoff,),
            ).fetchone()
            return row["avg_r"] or 0.0
        finally:
            conn.close()


# ══════════════════════════════════════════════════
# State Encoder — called by consciousness_daemon
# ══════════════════════════════════════════════════

class SubconsciousStateEncoder:
    """Encodes Frank's internal state as a 92-dim feature vector.

    The consciousness daemon passes raw data; this class normalizes
    and structures it for the network. Includes proprioceptive
    differentiation: self vs environment resource attribution.
    """

    def encode(
        self,
        # Current state
        mood: float = 0.5,
        mood_trend: float = 0.0,
        energy: float = 0.5,
        # Proprioceptive differentiation (self/env split)
        self_cpu: float = 0.0,
        env_cpu: float = 0.0,
        self_ram_pct: float = 0.0,
        env_ram_pct: float = 0.0,
        gpu_self_likely: float = 0.5,
        env_presence: float = 0.0,
        rumination_score: float = 0.0,
        epq_precision: float = 0.0,
        epq_risk: float = 0.0,
        epq_empathy: float = 0.0,
        epq_autonomy: float = 0.0,
        epq_vigilance: float = 0.0,
        aura_coherence: float = 0.5,
        ultradian_phase: str = "focus",
        # Temporal
        hours_since_last_chat: float = 0.0,
        hours_since_last_entity: float = 24.0,
        hours_since_last_dream: float = 24.0,
        minutes_since_last_thought: float = 5.0,
        chat_count_today: int = 0,
        entity_count_today: int = 0,
        idle_thought_count: int = 0,
        user_present: bool = False,
        hours_uptime: float = 0.0,
        # Consolidation
        unprocessed_conversations: int = 0,
        avg_emotional_charge: float = 0.0,
        max_emotional_charge: float = 0.0,
        hours_since_oldest_unprocessed: float = 0.0,
        unprocessed_entity_sessions: int = 0,
        total_consolidation_deficit: float = 0.0,
        has_high_surprise: bool = False,
        has_unresolved_tension: bool = False,
        times_reflected_today: int = 0,
        recency_weighted_deficit: float = 0.0,
        emotional_valence_unprocessed: float = 0.0,
        has_recent_important_chat: bool = False,
        conversation_diversity: float = 0.0,
        entity_session_deficit: float = 0.0,
        dream_processing_need: float = 0.0,
        # Recent thoughts (17 fractions + 17 time-since)
        type_histogram: Optional[Dict[str, float]] = None,
        time_since_per_type: Optional[Dict[str, float]] = None,
        # Hypothesis state
        active_hypotheses: int = 0,
        hypothesis_accuracy: float = 0.0,
        relational_hypotheses: int = 0,
        hours_since_last_hypothesis: float = 24.0,
        has_testable_hypothesis: bool = False,
        # Reward history
        avg_reward_last_5: float = 0.0,
        avg_reward_last_20: float = 0.0,
        reward_trend: float = 0.0,
        best_recent_type_reward: float = 0.0,
        worst_recent_type_reward: float = 0.0,
        exploration_rate: float = 1.0,
        training_progress: float = 0.0,
    ) -> torch.Tensor:
        """Encode complete state as 92-dim tensor."""
        features = []

        # === Current State (21 dims) ===
        features.append(float(np.clip(mood, 0, 1)))
        features.append(float(np.clip(mood_trend, -1, 1)))
        features.append(float(np.clip(energy, 0, 1)))
        # Proprioceptive differentiation: self vs environment resource split
        features.append(float(np.clip(self_cpu, 0, 1)))
        features.append(float(np.clip(env_cpu, 0, 1)))
        features.append(float(np.clip(self_ram_pct, 0, 1)))
        features.append(float(np.clip(env_ram_pct, 0, 1)))
        features.append(float(np.clip(gpu_self_likely, 0, 1)))
        features.append(float(np.clip(env_presence, 0, 1)))
        features.append(float(np.clip(rumination_score, 0, 1)))
        features.append(float(np.clip(epq_precision, -1, 1)))
        features.append(float(np.clip(epq_risk, -1, 1)))
        features.append(float(np.clip(epq_empathy, -1, 1)))
        features.append(float(np.clip(epq_autonomy, -1, 1)))
        features.append(float(np.clip(epq_vigilance, -1, 1)))
        features.append(float(np.clip(aura_coherence, 0, 1)))
        # Ultradian phase one-hot
        features.append(1.0 if ultradian_phase == "focus" else 0.0)
        features.append(1.0 if ultradian_phase == "diffuse" else 0.0)
        features.append(1.0 if ultradian_phase == "consolidation" else 0.0)
        # Time of day (sin/cos encoding)
        hour = time.localtime().tm_hour + time.localtime().tm_min / 60.0
        features.append(math.sin(2 * math.pi * hour / 24))
        features.append(math.cos(2 * math.pi * hour / 24))

        # === Temporal Features (10 dims) ===
        features.append(_log_norm(hours_since_last_chat, 48))
        features.append(_log_norm(hours_since_last_entity, 72))
        features.append(_log_norm(hours_since_last_dream, 48))
        features.append(_norm(minutes_since_last_thought, 30))
        features.append(_norm(chat_count_today, 20))
        features.append(_norm(entity_count_today, 5))
        features.append(_norm(idle_thought_count, 50))
        features.append(1.0 if user_present else 0.0)
        features.append(_log_norm(hours_uptime, 72))
        is_night = 1.0 if (hour >= 22 or hour < 6) else 0.0
        features.append(is_night)

        # === Consolidation Deficit (15 dims) ===
        features.append(_norm(unprocessed_conversations, 10))
        features.append(float(np.clip(avg_emotional_charge, 0, 1)))
        features.append(float(np.clip(max_emotional_charge, 0, 1)))
        features.append(_log_norm(hours_since_oldest_unprocessed, 168))  # 1 week
        features.append(_norm(unprocessed_entity_sessions, 5))
        features.append(float(np.clip(total_consolidation_deficit, 0, 10)) / 10.0)
        features.append(1.0 if has_high_surprise else 0.0)
        features.append(1.0 if has_unresolved_tension else 0.0)
        features.append(_norm(times_reflected_today, 8))
        features.append(float(np.clip(recency_weighted_deficit, 0, 5)) / 5.0)
        features.append(float(np.clip(emotional_valence_unprocessed, -1, 1)))
        features.append(1.0 if has_recent_important_chat else 0.0)
        features.append(float(np.clip(conversation_diversity, 0, 1)))
        features.append(float(np.clip(entity_session_deficit, 0, 1)))
        features.append(float(np.clip(dream_processing_need, 0, 1)))

        # === Recent Thought Distribution (17 dims) ===
        hist = type_histogram or {}
        for cat in THOUGHT_CATEGORIES:
            features.append(float(hist.get(cat, 0.0)))

        # === Per-Type Time Since Last (17 dims) ===
        ts_map = time_since_per_type or {}
        for cat in THOUGHT_CATEGORIES:
            hours_ago = ts_map.get(cat, 24.0)
            features.append(_log_norm(hours_ago, 48))

        # === Hypothesis State (5 dims) ===
        features.append(_norm(active_hypotheses, 20))
        features.append(float(np.clip(hypothesis_accuracy, 0, 1)))
        features.append(_norm(relational_hypotheses, 5))
        features.append(_log_norm(hours_since_last_hypothesis, 48))
        features.append(1.0 if has_testable_hypothesis else 0.0)

        # === Reward History (7 dims) ===
        features.append(float(np.clip(avg_reward_last_5, -7, 7)) / 7.0)
        features.append(float(np.clip(avg_reward_last_20, -7, 7)) / 7.0)
        features.append(float(np.clip(reward_trend, -2, 2)) / 2.0)
        features.append(float(np.clip(best_recent_type_reward, -7, 7)) / 7.0)
        features.append(float(np.clip(worst_recent_type_reward, -7, 7)) / 7.0)
        features.append(float(np.clip(exploration_rate, 0, 2)) / 2.0)
        features.append(float(np.clip(training_progress, 0, 1)))

        assert len(features) == STATE_DIM, f"State dim mismatch: {len(features)} != {STATE_DIM}"
        return torch.tensor(features, dtype=torch.float32)


# ══════════════════════════════════════════════════
# Singleton
# ══════════════════════════════════════════════════

_instance: Optional[Subconscious] = None
_instance_lock = threading.Lock()


def get_subconscious() -> Subconscious:
    """Get or create singleton Subconscious instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = Subconscious()
    return _instance
