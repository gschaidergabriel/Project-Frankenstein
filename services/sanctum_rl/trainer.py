"""
PPO Trainer for Sanctum RL policy.

Self-contained PPO implementation using PyTorch + Gymnasium.
No external RL framework needed.

Usage:
    python3 -m services.sanctum_rl.trainer [--timesteps 1000000] [--save-path PATH]
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.distributions import Categorical

from .environment import SanctumEnv, OBS_DIM
from .policy import SanctumMLP

# Default model save path
DEFAULT_MODEL_PATH = Path.home() / ".local" / "share" / "frank" / "models" / "sanctum_policy.pt"


def make_envs(n_envs: int = 8):
    """Create n parallel environments."""
    return [SanctumEnv() for _ in range(n_envs)]


def collect_batch(envs, policy, device, n_steps=128):
    """Collect a batch of experience from parallel envs."""
    n_envs = len(envs)
    obs_batch = torch.zeros(n_steps, n_envs, OBS_DIM, device=device)
    action_batch = torch.zeros(n_steps, n_envs, dtype=torch.long, device=device)
    entity_batch = torch.zeros(n_steps, n_envs, dtype=torch.long, device=device)
    reward_batch = torch.zeros(n_steps, n_envs, device=device)
    done_batch = torch.zeros(n_steps, n_envs, device=device)
    value_batch = torch.zeros(n_steps, n_envs, device=device)
    logprob_batch = torch.zeros(n_steps, n_envs, device=device)

    # Current obs for each env
    current_obs = []
    for env in envs:
        obs, _ = env.reset()
        current_obs.append(obs)
    current_obs = torch.tensor(np.array(current_obs), dtype=torch.float32, device=device)

    total_reward = 0.0
    n_episodes = 0

    for step in range(n_steps):
        obs_batch[step] = current_obs

        with torch.no_grad():
            action_logits, entity_logits, values = policy(current_obs)

        action_dist = Categorical(logits=action_logits)
        entity_dist = Categorical(logits=entity_logits)

        actions = action_dist.sample()
        entities = entity_dist.sample()
        log_probs = action_dist.log_prob(actions) + entity_dist.log_prob(entities)

        action_batch[step] = actions
        entity_batch[step] = entities
        value_batch[step] = values.squeeze(-1)
        logprob_batch[step] = log_probs

        # Step environments
        actions_np = actions.cpu().numpy()
        entities_np = entities.cpu().numpy()
        next_obs_list = []
        for i, env in enumerate(envs):
            obs, reward, terminated, truncated, info = env.step(
                np.array([actions_np[i], entities_np[i]])
            )
            reward_batch[step, i] = reward
            done = terminated or truncated
            done_batch[step, i] = float(done)

            if done:
                total_reward += sum(env.mood_history) / len(env.mood_history)
                n_episodes += 1
                obs, _ = env.reset()

            next_obs_list.append(obs)

        current_obs = torch.tensor(np.array(next_obs_list), dtype=torch.float32, device=device)

    # Compute advantages (GAE)
    with torch.no_grad():
        _, _, next_value = policy(current_obs)
        next_value = next_value.squeeze(-1)

    advantages = torch.zeros_like(reward_batch)
    returns = torch.zeros_like(reward_batch)
    gamma = 0.99
    gae_lambda = 0.95
    last_gae = torch.zeros(n_envs, device=device)

    for t in reversed(range(n_steps)):
        if t == n_steps - 1:
            next_val = next_value
        else:
            next_val = value_batch[t + 1]
        next_non_terminal = 1.0 - done_batch[t]
        delta = reward_batch[t] + gamma * next_val * next_non_terminal - value_batch[t]
        last_gae = delta + gamma * gae_lambda * next_non_terminal * last_gae
        advantages[t] = last_gae

    returns = advantages + value_batch

    avg_reward = total_reward / max(n_episodes, 1)
    return (
        obs_batch.reshape(-1, OBS_DIM),
        action_batch.reshape(-1),
        entity_batch.reshape(-1),
        logprob_batch.reshape(-1),
        advantages.reshape(-1),
        returns.reshape(-1),
        value_batch.reshape(-1),
        avg_reward,
        n_episodes,
    )


def train_epoch(policy, optimizer, obs, actions, entities, old_logprobs,
                advantages, returns, old_values, clip_coef=0.2,
                ent_coef=0.02, vf_coef=0.5, max_grad_norm=0.5,
                n_minibatches=4):
    """Run one PPO update epoch."""
    batch_size = obs.shape[0]
    minibatch_size = batch_size // n_minibatches
    indices = torch.randperm(batch_size)

    total_loss = 0.0
    total_pg_loss = 0.0
    total_vf_loss = 0.0
    total_entropy = 0.0

    for start in range(0, batch_size, minibatch_size):
        end = start + minibatch_size
        idx = indices[start:end]

        mb_obs = obs[idx]
        mb_actions = actions[idx]
        mb_entities = entities[idx]
        mb_old_logprobs = old_logprobs[idx]
        mb_advantages = advantages[idx]
        mb_returns = returns[idx]
        mb_old_values = old_values[idx]

        action_logits, entity_logits, values = policy(mb_obs)
        values = values.squeeze(-1)

        action_dist = Categorical(logits=action_logits)
        entity_dist = Categorical(logits=entity_logits)

        new_logprobs = action_dist.log_prob(mb_actions) + entity_dist.log_prob(mb_entities)
        entropy = action_dist.entropy().mean() + entity_dist.entropy().mean()

        # Normalize advantages
        mb_advantages = (mb_advantages - mb_advantages.mean()) / (mb_advantages.std() + 1e-8)

        # Policy loss (clipped PPO)
        ratio = torch.exp(new_logprobs - mb_old_logprobs)
        pg_loss1 = -mb_advantages * ratio
        pg_loss2 = -mb_advantages * torch.clamp(ratio, 1.0 - clip_coef, 1.0 + clip_coef)
        pg_loss = torch.max(pg_loss1, pg_loss2).mean()

        # Value loss (clipped)
        v_clipped = mb_old_values + torch.clamp(values - mb_old_values, -clip_coef, clip_coef)
        vf_loss1 = (values - mb_returns) ** 2
        vf_loss2 = (v_clipped - mb_returns) ** 2
        vf_loss = 0.5 * torch.max(vf_loss1, vf_loss2).mean()

        loss = pg_loss - ent_coef * entropy + vf_coef * vf_loss

        optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(policy.parameters(), max_grad_norm)
        optimizer.step()

        total_loss += loss.item()
        total_pg_loss += pg_loss.item()
        total_vf_loss += vf_loss.item()
        total_entropy += entropy.item()

    n = max(batch_size // minibatch_size, 1)
    return total_loss / n, total_pg_loss / n, total_vf_loss / n, total_entropy / n


def train(timesteps: int = 1_000_000, save_path: Path = DEFAULT_MODEL_PATH,
          n_envs: int = 8, n_steps: int = 128, n_epochs: int = 4,
          lr: float = 3e-4, ent_coef: float = 0.02):
    """Train the sanctum policy."""
    device = torch.device("cpu")
    policy = SanctumMLP().to(device)
    optimizer = optim.Adam(policy.parameters(), lr=lr, eps=1e-5)

    envs = make_envs(n_envs)
    batch_size = n_envs * n_steps
    n_updates = timesteps // batch_size

    print(f"Training SanctumMLP ({sum(p.numel() for p in policy.parameters())} params)")
    print(f"  {timesteps} timesteps, {n_envs} envs, {n_steps} steps/batch")
    print(f"  {n_updates} updates, {n_epochs} epochs/update")
    print(f"  Save: {save_path}")

    best_reward = -float("inf")
    t0 = time.time()

    for update in range(1, n_updates + 1):
        # Collect batch
        obs, actions, entities, logprobs, advantages, returns, values, avg_reward, n_eps = \
            collect_batch(envs, policy, device, n_steps)

        # PPO update
        for _ in range(n_epochs):
            loss, pg_loss, vf_loss, entropy = train_epoch(
                policy, optimizer, obs, actions, entities, logprobs,
                advantages, returns, values, ent_coef=ent_coef,
            )

        elapsed = time.time() - t0
        steps_done = update * batch_size
        sps = steps_done / max(elapsed, 0.001)

        if update % 10 == 0 or update == 1:
            print(f"  [{update:4d}/{n_updates}] steps={steps_done:>8d} "
                  f"SPS={sps:>8.0f} loss={loss:.3f} "
                  f"pg={pg_loss:.3f} vf={vf_loss:.3f} ent={entropy:.3f} "
                  f"reward={avg_reward:.3f} eps={n_eps}")

        # Save best model
        if avg_reward > best_reward and n_eps >= 2:
            best_reward = avg_reward
            save_path.parent.mkdir(parents=True, exist_ok=True)
            torch.save({
                "model_state_dict": policy.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "best_reward": best_reward,
                "timesteps": steps_done,
            }, save_path)

    # Final save
    save_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "model_state_dict": policy.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "best_reward": best_reward,
        "timesteps": timesteps,
    }, save_path)

    elapsed = time.time() - t0
    print(f"\nDone. {timesteps} steps in {elapsed:.1f}s ({timesteps/elapsed:.0f} SPS)")
    print(f"Best avg reward: {best_reward:.3f}")
    print(f"Model saved: {save_path}")

    return policy


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train Sanctum RL policy")
    parser.add_argument("--timesteps", type=int, default=1_000_000)
    parser.add_argument("--save-path", type=str, default=str(DEFAULT_MODEL_PATH))
    parser.add_argument("--n-envs", type=int, default=8)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--ent-coef", type=float, default=0.02)
    args = parser.parse_args()

    train(
        timesteps=args.timesteps,
        save_path=Path(args.save_path),
        n_envs=args.n_envs,
        lr=args.lr,
        ent_coef=args.ent_coef,
    )
