"""NeRD-style Neural Dynamics MLP — learns to replace analytical physics solver.

Architecture:
- Input:  [q(19), qd(19), torques(19), contact_flags(15)] = 72 dims
- Output: [q_next(19), qd_next(19)] = 38 dims
- 3-layer MLP with SiLU activation, ~50K params
- Trained on headless data from the analytical engine
- Contact-weighted loss for stability at boundary states
"""

from __future__ import annotations

import json
import logging
import sqlite3
import struct
import time
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

from .avatar import NUM_JOINTS, LINKS

LOG = logging.getLogger("nerd_physics.neural")

# Number of links for contact flags
NUM_LINKS = len(LINKS)  # 15

# Dimensions
INPUT_DIM = NUM_JOINTS + NUM_JOINTS + NUM_JOINTS + NUM_LINKS  # 19+19+19+15 = 72
OUTPUT_DIM = NUM_JOINTS + NUM_JOINTS  # 19+19 = 38

DEFAULT_MODEL_PATH = Path.home() / ".local" / "share" / "frank" / "models" / "nerd_dynamics.pt"


class NeuralDynamicsMLP(nn.Module):
    """3-layer MLP that predicts next-state from current state + torques + contacts."""

    def __init__(self, input_dim: int = INPUT_DIM, output_dim: int = OUTPUT_DIM,
                 hidden: int = 128) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden),
            nn.SiLU(),
            nn.Linear(hidden, hidden),
            nn.SiLU(),
            nn.Linear(hidden, hidden),
            nn.SiLU(),
            nn.Linear(hidden, output_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)

    @property
    def param_count(self) -> int:
        return sum(p.numel() for p in self.parameters())


# ---------------------------------------------------------------------------
# Headless data generation
# ---------------------------------------------------------------------------

def generate_training_data(n_steps: int = 10_000_000, seed: int = 42,
                           batch_report: int = 1_000_000) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Generate training data by running the analytical engine headless.

    Returns (inputs, outputs, contact_weights) arrays.
    - inputs:  (N, 72) — q, qd, torques, contact_flags
    - outputs: (N, 38) — q_next, qd_next
    - contact_weights: (N,) — 1.0 + num_contacts * 0.5 for contact-weighted loss
    """
    from .engine import PhysicsEngine, PhysicsAction, ActionType, DT, GRAVITY, K_CONTACT, D_CONTACT
    from .avatar import JOINTS, JOINT_INDEX, DEFAULT_Q, DEFAULT_ROOT_POS, NUM_JOINTS, forward_kinematics
    from .rooms import ROOMS, SPAWN_POINTS, find_room_contacts

    rng = np.random.RandomState(seed)

    inputs_list: List[np.ndarray] = []
    outputs_list: List[np.ndarray] = []
    weights_list: List[float] = []

    engine = PhysicsEngine()
    rooms = list(ROOMS.keys())

    # Scenario parameters for diverse data
    moods = [0.2, 0.35, 0.5, 0.65, 0.8, 0.95]
    coherences = [0.3, 0.5, 0.7, 0.9, 1.0]

    scenario_steps = 500  # steps per scenario before reset
    step_count = 0
    scenario_count = 0

    t0 = time.monotonic()
    LOG.info("Generating %d training steps headless...", n_steps)

    while step_count < n_steps:
        # New scenario: random room, mood, coherence, action
        room = rng.choice(rooms)
        engine.reset(room)
        engine.set_mood(float(rng.choice(moods)))
        engine.set_coherence(float(rng.choice(coherences)))

        # Random action
        action_type = rng.choice(["idle", "walk", "sit", "stand"], p=[0.3, 0.4, 0.15, 0.15])
        if action_type == "walk":
            target = rng.choice([r for r in rooms if r != room]) if len(rooms) > 1 else room
            engine.set_action(PhysicsAction(ActionType.WALK_TO, target_room=target))
        elif action_type == "sit":
            engine.set_action(PhysicsAction(ActionType.SIT))
        elif action_type == "stand":
            engine.set_action(PhysicsAction(ActionType.STAND))
        else:
            engine.set_action(PhysicsAction(ActionType.IDLE))

        for _ in range(scenario_steps):
            if step_count >= n_steps:
                break

            # Capture pre-step state
            with engine._lock:
                s = engine._state
                q_pre = s.q.copy()
                qd_pre = s.qd.copy()

            # Step
            engine.step()

            # Capture post-step state
            with engine._lock:
                s = engine._state
                q_post = s.q.copy()
                qd_post = s.qd.copy()
                torques = s.torques.copy()
                contacts = s.contacts

                # Build contact flags (per link)
                contact_flags = np.zeros(NUM_LINKS, dtype=np.float32)
                link_names = list(LINKS.keys())
                for c in contacts:
                    if c.link in link_names:
                        idx = link_names.index(c.link)
                        contact_flags[idx] = 1.0

                num_contacts = len(contacts)

            # Build input/output
            inp = np.concatenate([q_pre, qd_pre, torques, contact_flags]).astype(np.float32)
            out = np.concatenate([q_post, qd_post]).astype(np.float32)
            weight = 1.0 + num_contacts * 0.5

            inputs_list.append(inp)
            outputs_list.append(out)
            weights_list.append(weight)

            step_count += 1

            if step_count % batch_report == 0:
                elapsed = time.monotonic() - t0
                sps = step_count / elapsed
                LOG.info("  %dM steps, %.0f SPS, %.1fs elapsed",
                         step_count // 1_000_000, sps, elapsed)

        scenario_count += 1

        # Occasionally perturb joints for more diverse data
        if scenario_count % 3 == 0:
            with engine._lock:
                engine._state.q += rng.normal(0, 0.2, NUM_JOINTS).astype(np.float32)
                engine._state.qd += rng.normal(0, 0.5, NUM_JOINTS).astype(np.float32)

    elapsed = time.monotonic() - t0
    LOG.info("Generated %d steps in %.1fs (%.0f SPS), %d scenarios",
             step_count, elapsed, step_count / elapsed, scenario_count)

    return (
        np.array(inputs_list, dtype=np.float32),
        np.array(outputs_list, dtype=np.float32),
        np.array(weights_list, dtype=np.float32),
    )


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train_neural_dynamics(
    n_data_steps: int = 10_000_000,
    epochs: int = 100,
    batch_size: int = 4096,
    lr: float = 1e-3,
    save_path: Path = DEFAULT_MODEL_PATH,
    device: str = "cpu",
) -> NeuralDynamicsMLP:
    """Train the neural dynamics MLP on headless-generated data."""

    # Generate data
    inputs, outputs, weights = generate_training_data(n_data_steps)

    # To tensors
    X = torch.tensor(inputs)
    Y = torch.tensor(outputs)
    W = torch.tensor(weights)

    # Train/val split (95/5)
    n = len(X)
    n_val = max(1, n // 20)
    perm = torch.randperm(n)
    train_idx, val_idx = perm[n_val:], perm[:n_val]

    X_train, Y_train, W_train = X[train_idx], Y[train_idx], W[train_idx]
    X_val, Y_val, W_val = X[val_idx], Y[val_idx], W[val_idx]

    LOG.info("Train: %d, Val: %d", len(X_train), len(X_val))

    # Model
    model = NeuralDynamicsMLP().to(device)
    LOG.info("NeuralDynamicsMLP: %d params", model.param_count)

    optimizer = optim.Adam(model.parameters(), lr=lr)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=lr * 0.01)

    # DataLoader
    train_ds = TensorDataset(X_train, Y_train, W_train)
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, drop_last=True)

    best_val_loss = float("inf")
    best_epoch = 0
    t0 = time.monotonic()

    for epoch in range(epochs):
        model.train()
        total_loss = 0.0
        n_batches = 0

        for xb, yb, wb in train_loader:
            xb, yb, wb = xb.to(device), yb.to(device), wb.to(device)
            pred = model(xb)
            # Weighted MSE loss
            diff = (pred - yb) ** 2
            loss = (diff.mean(dim=1) * wb).mean()

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            total_loss += loss.item()
            n_batches += 1

        scheduler.step()
        avg_train = total_loss / max(n_batches, 1)

        # Validation
        model.eval()
        with torch.no_grad():
            val_pred = model(X_val.to(device))
            val_diff = (val_pred - Y_val.to(device)) ** 2
            val_loss = (val_diff.mean(dim=1) * W_val.to(device)).mean().item()

            # RMSE on joint angles (first 19 outputs)
            q_rmse = float(torch.sqrt(val_diff[:, :NUM_JOINTS].mean()).item())

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_epoch = epoch
            # Save best
            save_path.parent.mkdir(parents=True, exist_ok=True)
            torch.save({
                "model_state_dict": model.state_dict(),
                "input_dim": INPUT_DIM,
                "output_dim": OUTPUT_DIM,
                "hidden": 128,
                "best_val_loss": best_val_loss,
                "best_epoch": best_epoch,
                "q_rmse": q_rmse,
                "n_data_steps": n_data_steps,
                "epochs": epochs,
            }, save_path)

        if (epoch + 1) % 10 == 0 or epoch == 0:
            elapsed = time.monotonic() - t0
            LOG.info("[%3d/%d] train=%.6f val=%.6f q_rmse=%.5f best=%.6f@%d (%.1fs)",
                     epoch + 1, epochs, avg_train, val_loss, q_rmse,
                     best_val_loss, best_epoch + 1, elapsed)

    elapsed = time.monotonic() - t0
    LOG.info("Training done in %.1fs. Best val loss: %.6f at epoch %d, q_rmse: %.5f",
             elapsed, best_val_loss, best_epoch + 1, q_rmse)
    LOG.info("Model saved: %s", save_path)

    # Load best checkpoint
    cp = torch.load(save_path, map_location=device, weights_only=False)
    model.load_state_dict(cp["model_state_dict"])
    model.eval()

    return model


# ---------------------------------------------------------------------------
# Neural engine wrapper (drop-in for analytical step)
# ---------------------------------------------------------------------------

class NeuralPhysicsEngine:
    """Wraps NeuralDynamicsMLP for use as a drop-in physics step replacement.

    Falls back to analytical engine if model is not loaded or divergence detected.
    """

    def __init__(self, model_path: Path = DEFAULT_MODEL_PATH) -> None:
        self._model: Optional[NeuralDynamicsMLP] = None
        self._model_loaded = False
        self._model_path = model_path
        self._divergence_count = 0
        self._max_divergence = 10  # switch to analytical after this many
        self._divergence_threshold = 0.05  # rad — alert threshold

        try:
            if model_path.exists():
                cp = torch.load(model_path, map_location="cpu", weights_only=False)
                self._model = NeuralDynamicsMLP(
                    input_dim=cp.get("input_dim", INPUT_DIM),
                    output_dim=cp.get("output_dim", OUTPUT_DIM),
                    hidden=cp.get("hidden", 128),
                )
                self._model.load_state_dict(cp["model_state_dict"])
                self._model.eval()
                self._model_loaded = True
                LOG.info("Neural dynamics loaded from %s (q_rmse=%.5f, epoch=%d)",
                         model_path,
                         cp.get("q_rmse", 0),
                         cp.get("best_epoch", 0) + 1)
            else:
                LOG.warning("No neural dynamics at %s — analytical only", model_path)
        except Exception as e:
            LOG.error("Failed to load neural dynamics: %s", e)

    @property
    def is_loaded(self) -> bool:
        return self._model_loaded

    def predict_step(self, q: np.ndarray, qd: np.ndarray,
                     torques: np.ndarray, contact_flags: np.ndarray) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        """Predict next (q, qd) from current state.

        Returns None if model not loaded or too many divergences detected.
        """
        if not self._model_loaded or self._model is None:
            return None
        if self._divergence_count >= self._max_divergence:
            return None

        try:
            inp = np.concatenate([q, qd, torques, contact_flags]).astype(np.float32)
            with torch.no_grad():
                inp_t = torch.tensor(inp).unsqueeze(0)
                out_t = self._model(inp_t).squeeze(0).numpy()

            q_next = out_t[:NUM_JOINTS]
            qd_next = out_t[NUM_JOINTS:]
            return q_next, qd_next

        except Exception as e:
            LOG.warning("Neural step failed: %s", e)
            return None

    def check_divergence(self, neural_q: np.ndarray, analytical_q: np.ndarray) -> float:
        """Compare neural vs analytical output. Returns RMSE in radians."""
        rmse = float(np.sqrt(np.mean((neural_q - analytical_q) ** 2)))
        if rmse > self._divergence_threshold:
            self._divergence_count += 1
            if self._divergence_count <= 3 or self._divergence_count == self._max_divergence:
                LOG.warning("Neural-analytical divergence: %.4f rad (count=%d/%d)",
                            rmse, self._divergence_count, self._max_divergence)
        else:
            # Decay divergence count on good predictions
            self._divergence_count = max(0, self._divergence_count - 1)
        return rmse

    def reset_divergence(self) -> None:
        self._divergence_count = 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="NeRD Neural Dynamics trainer")
    parser.add_argument("--steps", type=int, default=10_000_000,
                        help="Number of headless data steps (default: 10M)")
    parser.add_argument("--epochs", type=int, default=100,
                        help="Training epochs (default: 100)")
    parser.add_argument("--batch-size", type=int, default=4096,
                        help="Batch size (default: 4096)")
    parser.add_argument("--lr", type=float, default=1e-3,
                        help="Learning rate (default: 1e-3)")
    parser.add_argument("--save", type=str, default=str(DEFAULT_MODEL_PATH),
                        help="Save path for trained model")
    parser.add_argument("--test", action="store_true",
                        help="Run quick test with 100K steps and 10 epochs")
    args = parser.parse_args()

    if args.test:
        args.steps = 100_000
        args.epochs = 10
        LOG.info("Test mode: 100K steps, 10 epochs")

    model = train_neural_dynamics(
        n_data_steps=args.steps,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        save_path=Path(args.save),
    )

    print(f"\nModel: {model.param_count} params")
    print(f"Saved: {args.save}")
