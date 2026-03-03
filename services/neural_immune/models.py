"""
Neural Immune System — Neural Modules
=======================================
3 micro neural networks (~19K total params, CPU-only PyTorch):

  AnomalyNet  (8.4K) — Predicts service failure from 8-step health windows
  BaselineNet (7.8K) — Autoencoder learns normal system behavior
  RestartNet  (3.1K) — Smart restart policy with 3 output heads
"""

import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import torch
import torch.nn as nn

LOG = logging.getLogger("immune.models")

# Default model path
_DEFAULT_MODEL = Path.home() / ".local" / "share" / "frank" / "models" / "immune_system.pt"

try:
    from config.paths import MODELS_DIR
    DEFAULT_MODEL_PATH = MODELS_DIR / "immune_system.pt"
except ImportError:
    DEFAULT_MODEL_PATH = _DEFAULT_MODEL


# ── Feature dimensions ────────────────────────────────────────────

FEATURES_PER_TIMESTEP = 12   # Per-service health features
HEALTH_WINDOW_SIZE = 8       # 8 timesteps (2 min at 15s intervals)
ANOMALY_INPUT_DIM = FEATURES_PER_TIMESTEP * HEALTH_WINDOW_SIZE  # 96

NUM_SERVICES = 20            # Max monitored services for baseline
METRICS_PER_SERVICE = 4      # is_active, cpu, rss, response_time
BASELINE_INPUT_DIM = NUM_SERVICES * METRICS_PER_SERVICE  # 80
BASELINE_LATENT_DIM = 16

RESTART_INPUT_DIM = 18       # Service + context features
MAX_RESTART_DELAY = 30.0     # Maximum delay in seconds


class AnomalyNet(nn.Module):
    """Predicts service failure from 8-step health windows.

    Input:  96d (8 timesteps × 12 features)
    Output: failure_probability ∈ [0, 1]
    Params: ~8,400
    """

    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(ANOMALY_INPUT_DIM, 64),
            nn.GELU(),
            nn.Linear(64, 32),
            nn.GELU(),
            nn.Linear(32, 1),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


class BaselineNet(nn.Module):
    """Autoencoder for normal system behavior.

    Input:  80d (20 services × 4 metrics)
    Latent: 16d
    Output: 80d (reconstructed)
    Params: ~7,800
    """

    def __init__(self):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(BASELINE_INPUT_DIM, 40),
            nn.GELU(),
            nn.Linear(40, BASELINE_LATENT_DIM),
        )
        self.decoder = nn.Sequential(
            nn.Linear(BASELINE_LATENT_DIM, 40),
            nn.GELU(),
            nn.Linear(40, BASELINE_INPUT_DIM),
        )

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """Returns (reconstruction, latent)."""
        latent = self.encoder(x)
        recon = self.decoder(latent)
        return recon, latent

    def anomaly_score(self, x: torch.Tensor) -> float:
        """Compute reconstruction MSE (higher = more anomalous)."""
        with torch.no_grad():
            recon, _ = self.forward(x)
            mse = torch.mean((x - recon) ** 2).item()
        return mse


class RestartNet(nn.Module):
    """Smart restart policy with 3 output heads.

    Input:  18d (service + context features)
    Output: (optimal_delay ∈ [0, 30], should_restart ∈ [0, 1], cascade_risk ∈ [0, 1])
    Params: ~3,100
    """

    def __init__(self):
        super().__init__()
        self.shared = nn.Sequential(
            nn.Linear(RESTART_INPUT_DIM, 48),
            nn.GELU(),
            nn.Linear(48, 32),
            nn.GELU(),
        )
        self.head_delay = nn.Sequential(nn.Linear(32, 1), nn.Sigmoid())
        self.head_restart = nn.Sequential(nn.Linear(32, 1), nn.Sigmoid())
        self.head_cascade = nn.Sequential(nn.Linear(32, 1), nn.Sigmoid())

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        h = self.shared(x)
        delay = self.head_delay(h).squeeze(-1) * MAX_RESTART_DELAY
        should_restart = self.head_restart(h).squeeze(-1)
        cascade_risk = self.head_cascade(h).squeeze(-1)
        return delay, should_restart, cascade_risk


class ImmuneModels:
    """Container for all 3 neural modules + save/load + cold start blending."""

    # Cold start thresholds
    ANOMALY_THRESHOLD = 100    # incidents before anomaly prediction active
    BASELINE_THRESHOLD = 200   # healthy snapshots before baseline active
    RESTART_THRESHOLD = 50     # incidents before restart policy active

    def __init__(self, model_path: Optional[Path] = None):
        self._model_path = model_path or DEFAULT_MODEL_PATH
        self._model_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

        # Initialize modules
        self.anomaly = AnomalyNet()
        self.baseline = BaselineNet()
        self.restart = RestartNet()

        # Training step counters (for cold start blending)
        self._anomaly_steps = 0
        self._baseline_steps = 0
        self._restart_steps = 0

        # Baseline anomaly threshold (learned)
        self._baseline_mse_mean = 0.0
        self._baseline_mse_std = 1.0

        # Set eval mode
        self._set_eval_mode()

        # Try to load saved weights
        self._load()

    def _set_eval_mode(self):
        self.anomaly.eval()
        self.baseline.eval()
        self.restart.eval()

    # ── Cold Start Blending ───────────────────────────────────────

    def _blend_rate(self, steps: int, threshold: int) -> float:
        """Neural blend rate: 0.0 (pure default) → 1.0 (pure neural)."""
        if threshold <= 0:
            return 1.0 if steps > 0 else 0.0
        if steps >= threshold:
            return 1.0
        return steps / threshold

    # ── Inference ─────────────────────────────────────────────────

    def predict_failure(self, window: List[float]) -> float:
        """Predict failure probability from 8-step health window.

        Returns 0.0 during cold start (no prediction).
        """
        rate = self._blend_rate(self._anomaly_steps, self.ANOMALY_THRESHOLD)
        if rate == 0.0:
            return 0.0

        with self._lock:
            x = torch.tensor(window, dtype=torch.float32).unsqueeze(0)
            with torch.no_grad():
                neural = self.anomaly(x).item()
        return rate * neural

    def baseline_anomaly(self, snapshot_vector: List[float]) -> float:
        """Compute system-wide anomaly from health snapshot.

        Returns 0.0 during cold start.
        """
        rate = self._blend_rate(self._baseline_steps, self.BASELINE_THRESHOLD)
        if rate == 0.0:
            return 0.0

        with self._lock:
            x = torch.tensor(snapshot_vector, dtype=torch.float32).unsqueeze(0)
            with torch.no_grad():
                mse = self.baseline.anomaly_score(x)
        # Normalize: how many stds above mean
        if self._baseline_mse_std > 0:
            z_score = (mse - self._baseline_mse_mean) / self._baseline_mse_std
            anomaly = max(0.0, min(1.0, z_score / 3.0))  # 3σ → 1.0
        else:
            anomaly = 0.0
        return rate * anomaly

    def restart_policy(self, features: Dict[str, float],
                       default_delay: float = 3.0) -> Dict[str, float]:
        """Get restart policy from neural net or defaults.

        Returns dict with 'delay', 'should_restart', 'cascade_risk'.
        Cold start: delay=default_delay, should_restart=1.0, cascade_risk=0.0.
        """
        rate = self._blend_rate(self._restart_steps, self.RESTART_THRESHOLD)

        # Defaults
        default = {
            "delay": default_delay,
            "should_restart": 1.0,
            "cascade_risk": 0.0,
        }

        if rate == 0.0:
            return default

        # Build feature vector
        feat_keys = [
            "service_tier", "restart_count_recent", "uptime_before_crash",
            "time_since_last_restart", "hour_sin", "hour_cos",
            "dependency_health", "is_critical", "historical_mttr",
            "historical_success_rate", "n_concurrent_failures",
            "circuit_breaker_state", "anomaly_score", "baseline_mse",
            "cpu_system", "ram_system_pct", "user_active", "recent_restart_failures",
        ]
        vec = [features.get(k, 0.0) for k in feat_keys]

        with self._lock:
            x = torch.tensor(vec, dtype=torch.float32).unsqueeze(0)
            with torch.no_grad():
                delay, should_restart, cascade_risk = self.restart(x)

        neural = {
            "delay": delay.item(),
            "should_restart": should_restart.item(),
            "cascade_risk": cascade_risk.item(),
        }

        # Blend neural with default
        return {
            k: rate * neural[k] + (1 - rate) * default[k]
            for k in default
        }

    # ── Persistence ───────────────────────────────────────────────

    def _save(self):
        """Save all model weights + metadata atomically."""
        with self._lock:
            state = {
                "anomaly": self.anomaly.state_dict(),
                "baseline": self.baseline.state_dict(),
                "restart": self.restart.state_dict(),
                "anomaly_steps": self._anomaly_steps,
                "baseline_steps": self._baseline_steps,
                "restart_steps": self._restart_steps,
                "baseline_mse_mean": self._baseline_mse_mean,
                "baseline_mse_std": self._baseline_mse_std,
            }
            tmp = self._model_path.with_suffix(".tmp")
            torch.save(state, tmp)
            tmp.rename(self._model_path)
        LOG.debug("Models saved to %s", self._model_path)

    def _load(self):
        """Load model weights if file exists."""
        if not self._model_path.exists():
            LOG.info("No saved models found, starting fresh")
            return

        try:
            state = torch.load(self._model_path, map_location="cpu", weights_only=True)
            self.anomaly.load_state_dict(state["anomaly"])
            self.baseline.load_state_dict(state["baseline"])
            self.restart.load_state_dict(state["restart"])
            self._anomaly_steps = state.get("anomaly_steps", 0)
            self._baseline_steps = state.get("baseline_steps", 0)
            self._restart_steps = state.get("restart_steps", 0)
            self._baseline_mse_mean = state.get("baseline_mse_mean", 0.0)
            self._baseline_mse_std = state.get("baseline_mse_std", 1.0)
            self._set_eval_mode()
            LOG.info("Models loaded (anomaly=%d, baseline=%d, restart=%d steps)",
                     self._anomaly_steps, self._baseline_steps, self._restart_steps)
        except Exception as e:
            LOG.warning("Failed to load models: %s — starting fresh", e)

    def total_params(self) -> int:
        """Total parameter count across all 3 modules."""
        return sum(
            sum(p.numel() for p in m.parameters())
            for m in [self.anomaly, self.baseline, self.restart]
        )
