"""
Neural Immune System — Training Module
========================================
Trains all 3 neural modules from accumulated data:
  AnomalyNet  — Binary classification: did service crash after this window?
  BaselineNet — Self-supervised reconstruction of healthy snapshots
  RestartNet  — UCB reward: restart success/failure + uptime

Cold start blending: 4 phases from pure rule-based to full neural.
Training triggered during dream consolidation phase (<50ms total).
"""

import json
import logging
import time
from typing import List, Optional, Tuple

import torch
import torch.nn as nn
import torch.optim as optim

from .db import ImmuneDB
from .models import (
    ImmuneModels, ANOMALY_INPUT_DIM, BASELINE_INPUT_DIM,
    FEATURES_PER_TIMESTEP, HEALTH_WINDOW_SIZE,
)

LOG = logging.getLogger("immune.training")

# Training hyperparameters
LEARNING_RATE = 1e-3
BATCH_SIZE = 32
MAX_EPOCHS_PER_CYCLE = 5
MAX_TRAINING_TIME_MS = 50  # Hard time cap per cycle


class ImmuneTrainer:
    """Trains all 3 immune neural modules."""

    def __init__(self, models: ImmuneModels, db: ImmuneDB):
        self.models = models
        self.db = db

        # SFT Stabilizer: gradient clipping + weight decay
        try:
            from services.sft_stabilizer import get_stabilizer
            self._stab = get_stabilizer()
        except Exception:
            self._stab = None

        # Optimizers (created on first use)
        self._opt_anomaly: Optional[optim.Adam] = None
        self._opt_baseline: Optional[optim.Adam] = None
        self._opt_restart: Optional[optim.Adam] = None

    def _get_optimizer(self, name: str, params) -> optim.Adam:
        attr = f"_opt_{name}"
        opt = getattr(self, attr, None)
        if opt is None:
            opt = optim.Adam(params, lr=LEARNING_RATE)
            setattr(self, attr, opt)
        return opt

    def train_cycle(self):
        """Full training cycle on accumulated data. <50ms per module."""
        t0 = time.monotonic()
        try:
            self._train_anomaly()
            self._train_baseline()
            self._train_restart()

            # SFT: apply weight decay to all 3 nets (~0.01ms total)
            if self._stab:
                for model in (self.models.anomaly, self.models.baseline,
                              self.models.restart):
                    self._stab.apply_weight_decay(model, decay=5e-5)

            self.models._save()
        finally:
            self.models._set_eval_mode()

        elapsed_ms = (time.monotonic() - t0) * 1000
        LOG.info("Training cycle complete in %.1fms", elapsed_ms)

    # ── AnomalyNet Training ──────────────────────────────────────

    def _train_anomaly(self):
        """Train AnomalyNet on (pre_window, crashed?) pairs."""
        data = self.db.get_training_windows(limit=500)
        if len(data) < 20:
            return  # Not enough data

        # Parse windows
        X, Y = [], []
        for window_json, label in data:
            try:
                window = json.loads(window_json)
                if len(window) == ANOMALY_INPUT_DIM:
                    X.append(window)
                    Y.append(float(label))
            except (json.JSONDecodeError, TypeError):
                continue

        if len(X) < 20:
            return

        X_t = torch.tensor(X, dtype=torch.float32)
        Y_t = torch.tensor(Y, dtype=torch.float32)

        self.models.anomaly.train()
        opt = self._get_optimizer("anomaly", self.models.anomaly.parameters())
        criterion = nn.BCELoss()

        # Fresh time budget per module (optimizer creation excluded)
        t0 = time.monotonic()
        total_loss = 0.0
        n_batches = 0

        for epoch in range(MAX_EPOCHS_PER_CYCLE):
            if (time.monotonic() - t0) * 1000 > MAX_TRAINING_TIME_MS:
                break

            # Shuffle
            perm = torch.randperm(len(X_t))
            X_t = X_t[perm]
            Y_t = Y_t[perm]

            for i in range(0, len(X_t), BATCH_SIZE):
                if (time.monotonic() - t0) * 1000 > MAX_TRAINING_TIME_MS:
                    break
                batch_x = X_t[i:i + BATCH_SIZE]
                batch_y = Y_t[i:i + BATCH_SIZE]

                opt.zero_grad()
                pred = self.models.anomaly(batch_x)
                loss = criterion(pred, batch_y)
                loss.backward()
                if self._stab:
                    self._stab.safe_step(opt, self.models.anomaly, 1.0)
                else:
                    opt.step()

                total_loss += loss.item()
                n_batches += 1

        if n_batches > 0:
            avg_loss = total_loss / n_batches
            with self.models._lock:
                self.models._anomaly_steps += n_batches
            self.db.update_training_meta("anomaly", self.models._anomaly_steps, avg_loss)
            LOG.debug("AnomalyNet: %d batches, loss=%.4f, steps=%d",
                      n_batches, avg_loss, self.models._anomaly_steps)

    # ── BaselineNet Training ─────────────────────────────────────

    def _train_baseline(self):
        """Train BaselineNet autoencoder on healthy snapshots."""
        snapshots = self.db.get_healthy_snapshots(limit=500)
        if len(snapshots) < 50:
            return

        # Build vectors
        X = []
        for snap in snapshots:
            vec = self._snapshot_to_vector(snap)
            if len(vec) == BASELINE_INPUT_DIM:
                X.append(vec)

        if len(X) < 50:
            return

        X_t = torch.tensor(X, dtype=torch.float32)

        self.models.baseline.train()
        opt = self._get_optimizer("baseline", self.models.baseline.parameters())
        criterion = nn.MSELoss()

        t0 = time.monotonic()
        total_loss = 0.0
        n_batches = 0
        mse_values = []

        for epoch in range(MAX_EPOCHS_PER_CYCLE):
            if (time.monotonic() - t0) * 1000 > MAX_TRAINING_TIME_MS:
                break

            perm = torch.randperm(len(X_t))
            X_t = X_t[perm]

            for i in range(0, len(X_t), BATCH_SIZE):
                if (time.monotonic() - t0) * 1000 > MAX_TRAINING_TIME_MS:
                    break
                batch = X_t[i:i + BATCH_SIZE]

                opt.zero_grad()
                recon, _ = self.models.baseline(batch)
                loss = criterion(recon, batch)
                loss.backward()
                if self._stab:
                    self._stab.safe_step(opt, self.models.baseline, 1.0)
                else:
                    opt.step()

                total_loss += loss.item()
                mse_values.append(loss.item())
                n_batches += 1

        if n_batches > 0:
            avg_loss = total_loss / n_batches
            with self.models._lock:
                self.models._baseline_steps += n_batches

                # Update anomaly threshold (mean + 2σ)
                if mse_values:
                    mean_mse = sum(mse_values) / len(mse_values)
                    var = sum((m - mean_mse) ** 2 for m in mse_values) / len(mse_values)
                    std_mse = var ** 0.5
                    self.models._baseline_mse_mean = mean_mse
                    self.models._baseline_mse_std = max(std_mse, 1e-6)

            self.db.update_training_meta("baseline", self.models._baseline_steps, avg_loss)
            LOG.debug("BaselineNet: %d batches, loss=%.6f, steps=%d",
                      n_batches, avg_loss, self.models._baseline_steps)

    def _snapshot_to_vector(self, snapshot: dict) -> List[float]:
        """Convert snapshot dict to 80d baseline vector."""
        vec = []
        service_names = sorted(snapshot.keys())[:20]
        for name in service_names:
            metrics = snapshot.get(name, [])
            if isinstance(metrics, list) and len(metrics) >= 4:
                vec.extend([metrics[0], metrics[1], metrics[2], metrics[3]])
            else:
                vec.extend([0.0, 0.0, 0.0, 0.0])
        while len(vec) < BASELINE_INPUT_DIM:
            vec.append(0.0)
        return vec[:BASELINE_INPUT_DIM]

    # ── RestartNet Training ──────────────────────────────────────

    def _train_restart(self):
        """Train RestartNet from incident outcomes (UCB reward)."""
        incidents = self.db.get_incidents(limit=500)
        if len(incidents) < 20:
            return

        # Build training pairs: features → (target_delay, target_restart, target_cascade)
        X, Y_delay, Y_restart, Y_cascade = [], [], [], []

        for inc in incidents:
            if inc["event_type"] not in ("restart", "crash"):
                continue

            features = self._build_restart_features(inc)
            if len(features) != 18:
                continue

            X.append(features)

            # Target: reward-blended
            success = inc.get("restart_success", 0)
            delay_used = inc.get("restart_delay", 3.0)
            cascade = inc.get("cascade_triggered", 0)

            # Successful fast restarts → push toward lower delay
            if success:
                target_delay = max(1.0, delay_used * 0.8) / 30.0  # normalize
                target_restart = 1.0
            else:
                target_delay = min(30.0, delay_used * 1.5) / 30.0
                target_restart = 0.3  # Don't fully suppress — might work next time

            target_cascade = float(cascade)

            Y_delay.append(target_delay)
            Y_restart.append(target_restart)
            Y_cascade.append(target_cascade)

        if len(X) < 20:
            return

        X_t = torch.tensor(X, dtype=torch.float32)
        Yd_t = torch.tensor(Y_delay, dtype=torch.float32)
        Yr_t = torch.tensor(Y_restart, dtype=torch.float32)
        Yc_t = torch.tensor(Y_cascade, dtype=torch.float32)

        self.models.restart.train()
        opt = self._get_optimizer("restart", self.models.restart.parameters())

        t0 = time.monotonic()
        total_loss = 0.0
        n_batches = 0

        for epoch in range(MAX_EPOCHS_PER_CYCLE):
            if (time.monotonic() - t0) * 1000 > MAX_TRAINING_TIME_MS:
                break

            perm = torch.randperm(len(X_t))
            X_t = X_t[perm]
            Yd_t = Yd_t[perm]
            Yr_t = Yr_t[perm]
            Yc_t = Yc_t[perm]

            for i in range(0, len(X_t), BATCH_SIZE):
                if (time.monotonic() - t0) * 1000 > MAX_TRAINING_TIME_MS:
                    break
                bx = X_t[i:i + BATCH_SIZE]
                byd = Yd_t[i:i + BATCH_SIZE]
                byr = Yr_t[i:i + BATCH_SIZE]
                byc = Yc_t[i:i + BATCH_SIZE]

                opt.zero_grad()
                pred_delay, pred_restart, pred_cascade = self.models.restart(bx)
                # MSE loss on all 3 heads
                loss = (
                    nn.functional.mse_loss(pred_delay / 30.0, byd) +
                    nn.functional.binary_cross_entropy(pred_restart, byr) +
                    nn.functional.binary_cross_entropy(pred_cascade, byc)
                )
                loss.backward()
                if self._stab:
                    self._stab.safe_step(opt, self.models.restart, 1.0)
                else:
                    opt.step()

                total_loss += loss.item()
                n_batches += 1

        if n_batches > 0:
            avg_loss = total_loss / n_batches
            with self.models._lock:
                self.models._restart_steps += n_batches
            self.db.update_training_meta("restart", self.models._restart_steps, avg_loss)
            LOG.debug("RestartNet: %d batches, loss=%.4f, steps=%d",
                      n_batches, avg_loss, self.models._restart_steps)

    def _build_restart_features(self, incident: dict) -> List[float]:
        """Build 18d feature vector from incident record."""
        import math

        svc = incident.get("service", "")
        ts = incident.get("timestamp", time.time())

        # Try to get service info
        try:
            from .collector import SERVICE_REGISTRY
            info = SERVICE_REGISTRY.get(svc, {})
        except ImportError:
            info = {}

        tier = info.get("tier", 2) / 4.0
        is_critical = 1.0 if info.get("critical", True) else 0.0
        default_delay = info.get("delay", 3.0)

        # Time features
        hour = time.localtime(ts).tm_hour + time.localtime(ts).tm_min / 60.0
        hour_sin = math.sin(2 * math.pi * hour / 24.0)
        hour_cos = math.cos(2 * math.pi * hour / 24.0)

        return [
            tier,                                    # service_tier
            incident.get("restart_delay", 0) / 30.0,  # restart_count_recent (proxy)
            0.5,                                     # uptime_before_crash (unknown)
            min(incident.get("restart_delay", 0) / 120.0, 1.0),  # time_since_last_restart
            hour_sin,
            hour_cos,
            0.5,                                     # dependency_health (unknown)
            is_critical,
            default_delay / 30.0,                    # historical_mttr (proxy)
            0.5 + 0.5 * incident.get("restart_success", 0),  # historical_success_rate
            0.0,                                     # n_concurrent_failures
            0.0 if incident.get("circuit_state") == "closed" else 0.5,  # circuit_breaker_state
            0.0,                                     # anomaly_score (unknown)
            0.0,                                     # baseline_mse (unknown)
            0.5,                                     # cpu_system (unknown)
            0.5,                                     # ram_system_pct (unknown)
            0.5,                                     # user_active (unknown)
            0.0,                                     # recent_restart_failures
        ]
