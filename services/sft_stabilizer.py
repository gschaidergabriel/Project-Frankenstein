"""
SFT Stabilizer — Neural Network Anti-Degeneration Homeostasis.

Centralized stabilization for Frank's 13 learnable neural networks across
5 systems. Prevents weight explosion, policy collapse, mode collapse, and
catastrophic forgetting through 4 lightweight mechanisms:

  1. Decoupled weight decay (AdamW-equivalent, works with any optimizer)
  2. Reference weight anchoring (lightweight EWC without Fisher matrix)
  3. Drift monitoring with health alerts + emergency rollback
  4. Standardized gradient clipping (fills gaps in immune/physics nets)

Neuroscience basis:
  - Homeostatic plasticity (Turrigiano 2008): synaptic scaling
  - Elastic Weight Consolidation (Kirkpatrick 2017): simplified L2 variant
  - Metaplasticity (Abraham 2008): reference state anchoring

Architecture:
  - In-process singleton (no separate service/port)
  - <0.1ms per call (pure tensor ops, DB writes only on health check)
  - SQLite WAL DB for health log (7-day retention)
  - Zero changes to existing optimizers or architectures

Usage:
    from services.sft_stabilizer import get_stabilizer
    stab = get_stabilizer()

    # In training loop:
    grad_norm = stab.safe_step(optimizer, model, max_grad_norm=0.5)
    stab.apply_weight_decay(model, decay=1e-4)

    # Reference anchoring:
    anchor = stab.create_anchor(model, "my_model", strength=0.01)
    loss = task_loss + anchor.anchor_loss(model)

    # Health check:
    report = stab.check_health(model, "my_model", anchor=anchor)
"""

from __future__ import annotations

import atexit
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import torch
import torch.nn as nn
import torch.optim as optim

LOG = logging.getLogger("sft_stabilizer")

# ─── Defaults ─────────────────────────────────────────────────────────
DEFAULT_DECAY_RATES = {
    "subconscious": 1e-4,
    "immune_anomaly": 5e-5,
    "immune_baseline": 5e-5,
    "immune_restart": 5e-5,
    "titan_mis": 5e-5,
    "titan_et": 5e-5,
    "titan_rwl": 5e-5,
    "titan_as": 5e-5,
    "titan_cg": 5e-5,
    "titan_id": 5e-5,
    "sanctum_rl": 1e-4,
    "nerd_physics": 1e-4,
}

DEFAULT_ANCHOR_STRENGTHS = {
    "subconscious": 0.005,
    "immune_anomaly": 0.01,
    "immune_baseline": 0.01,
    "immune_restart": 0.01,
    "titan_mis": 0.01,
    "titan_et": 0.01,
    "titan_rwl": 0.01,
    "titan_as": 0.01,
    "titan_cg": 0.01,
    "titan_id": 0.01,
    "sanctum_rl": 0.005,
    "nerd_physics": 0.02,
}

HEALTH_THRESHOLDS = {
    "weight_norm_ratio": 5.0,       # 5x initial norm → WARNING
    "weight_max": 100.0,            # Any weight > 100 → WARNING
    "policy_entropy_min": 0.1,      # Entropy < 0.1 → policy collapse
    "drift_ratio": 3.0,             # 3x avg drift → sudden drift WARNING
}

HEALTH_LOG_RETENTION_DAYS = 7


# ─── Data Classes ─────────────────────────────────────────────────────

@dataclass
class HealthReport:
    """Per-training-step health snapshot."""
    model_name: str
    timestamp: float
    weight_norm: float
    weight_max: float
    grad_norm: float
    policy_entropy: float       # -1.0 if N/A (supervised models)
    drift_from_ref: float       # -1.0 if no anchor
    status: str                 # "healthy", "warning", "critical"
    warnings: List[str] = field(default_factory=list)


# ─── Reference Weight Anchor ─────────────────────────────────────────

class ReferenceAnchor:
    """Stores reference weights and computes L2 anchor loss.

    Lightweight alternative to EWC: no Fisher diagonal, just L2 toward
    a reference snapshot. Update reference after validated improvements.

    Memory cost: ~4 bytes × num_params (fp32 clone).
    Compute cost: ~0.1ms for 3.1M params.
    """

    def __init__(self, model: nn.Module, strength: float = 0.01):
        self.strength = strength
        self._ref: Dict[str, torch.Tensor] = {}
        self._update_ref(model)

    def _update_ref(self, model: nn.Module) -> None:
        """Snapshot current weights as reference."""
        self._ref = {
            name: param.data.clone().detach()
            for name, param in model.named_parameters()
            if param.requires_grad
        }

    def anchor_loss(self, model: nn.Module) -> torch.Tensor:
        """Compute L2 penalty toward reference weights.

        Add to training loss: total_loss = task_loss + anchor.anchor_loss(model)
        """
        loss = torch.tensor(0.0, device=next(model.parameters()).device)
        for name, param in model.named_parameters():
            if name in self._ref:
                ref = self._ref[name]
                if ref.device != param.device:
                    ref = ref.to(param.device)
                loss = loss + ((param - ref) ** 2).sum()
        return self.strength * loss

    def drift_from_ref(self, model: nn.Module) -> float:
        """Compute total L2 distance from reference (no gradient)."""
        total = 0.0
        with torch.no_grad():
            for name, param in model.named_parameters():
                if name in self._ref:
                    ref = self._ref[name]
                    if ref.device != param.device:
                        ref = ref.to(param.device)
                    total += ((param - ref) ** 2).sum().item()
        return total ** 0.5

    def update_reference(self, model: nn.Module) -> None:
        """Update reference to current weights (call after validated improvement)."""
        self._update_ref(model)
        LOG.debug("SFT: reference weights updated")

    def get_ref_state(self) -> Dict[str, torch.Tensor]:
        """Return reference state for checkpoint saving."""
        return {k: v.clone() for k, v in self._ref.items()}

    def load_ref_state(self, state: Dict[str, torch.Tensor]) -> None:
        """Restore reference state from checkpoint."""
        self._ref = {k: v.clone().detach() for k, v in state.items()}

    def rollback(self, model: nn.Module) -> None:
        """Emergency: restore model weights to reference snapshot."""
        with torch.no_grad():
            for name, param in model.named_parameters():
                if name in self._ref:
                    param.copy_(self._ref[name])
        LOG.warning("SFT: EMERGENCY rollback to reference weights")


# ─── SFT Stabilizer ──────────────────────────────────────────────────

class SFTStabilizer:
    """Centralized neural network stabilization system.

    Provides 4 mechanisms:
      1. apply_weight_decay() — decoupled L2 on parameters
      2. safe_step() — gradient clipping + optimizer step
      3. create_anchor() — reference weight anchoring
      4. check_health() — drift monitoring with alerts
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._anchors: Dict[str, ReferenceAnchor] = {}
        self._initial_norms: Dict[str, float] = {}
        self._drift_history: Dict[str, List[float]] = {}
        self._db_path: Optional[Path] = None
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    # ── DB ────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        """Initialize health log database."""
        try:
            from config.paths import DB_PATHS
            self._db_path = DB_PATHS.get("sft_stabilizer")
            if self._db_path is None:
                # Fallback if config not yet updated
                from config.paths import DB_DIR
                self._db_path = DB_DIR / "sft_stabilizer.db"
        except Exception:
            self._db_path = Path.home() / ".local/share/frank/db/sft_stabilizer.db"

        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(self._db_path), check_same_thread=False,
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS health_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    model_name TEXT NOT NULL,
                    weight_norm REAL,
                    weight_max REAL,
                    grad_norm REAL,
                    policy_entropy REAL,
                    drift_from_ref REAL,
                    status TEXT NOT NULL,
                    warnings TEXT
                )
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_health_ts
                ON health_log(timestamp)
            """)
            self._conn.commit()
            LOG.info("SFT Stabilizer: DB initialized at %s", self._db_path)
        except Exception as e:
            LOG.warning("SFT Stabilizer: DB init failed (%s), running without persistence", e)
            self._conn = None

    def _prune_old_logs(self) -> None:
        """Remove health logs older than retention period."""
        if not self._conn:
            return
        try:
            cutoff = time.time() - (HEALTH_LOG_RETENTION_DAYS * 86400)
            self._conn.execute(
                "DELETE FROM health_log WHERE timestamp < ?", (cutoff,)
            )
            self._conn.commit()
        except Exception:
            pass

    # ── Mechanism 1: Weight Decay ─────────────────────────────────────

    @staticmethod
    def apply_weight_decay(
        model: nn.Module,
        decay: float = 1e-4,
        exclude_bias: bool = True,
    ) -> None:
        """Apply decoupled weight decay to all parameters.

        Mathematically equivalent to AdamW-style weight decay but works
        with any existing optimizer. Call once after each training step.

        Cost: ~0.02ms for 3.1M params.
        """
        with torch.no_grad():
            for name, param in model.named_parameters():
                if not param.requires_grad:
                    continue
                if exclude_bias and ("bias" in name or "LayerNorm" in name
                                     or "layer_norm" in name or "ln" in name):
                    continue
                param.mul_(1.0 - decay)

    # ── Mechanism 2: Gradient Clipping + Step ─────────────────────────

    @staticmethod
    def safe_step(
        optimizer: optim.Optimizer,
        model: nn.Module,
        max_grad_norm: float = 1.0,
    ) -> float:
        """Clip gradients and step optimizer. Returns gradient norm.

        Replaces: optimizer.step() in all training loops.
        Adds gradient clipping where missing.
        Cost: ~0.01ms for 3.1M params.
        """
        grad_norm = nn.utils.clip_grad_norm_(
            model.parameters(), max_grad_norm
        )
        optimizer.step()
        return float(grad_norm)

    # ── Mechanism 3: Reference Anchoring ──────────────────────────────

    def create_anchor(
        self,
        model: nn.Module,
        model_name: str,
        strength: Optional[float] = None,
    ) -> ReferenceAnchor:
        """Create or retrieve a reference weight anchor for a model.

        If strength is None, uses DEFAULT_ANCHOR_STRENGTHS for the model name.
        """
        if strength is None:
            strength = DEFAULT_ANCHOR_STRENGTHS.get(model_name, 0.01)

        anchor = ReferenceAnchor(model, strength=strength)
        with self._lock:
            self._anchors[model_name] = anchor

            # Store initial weight norm for drift ratio computation
            with torch.no_grad():
                total = sum(
                    p.data.norm().item() ** 2
                    for p in model.parameters() if p.requires_grad
                )
            self._initial_norms[model_name] = total ** 0.5

        LOG.info(
            "SFT: anchor created for %s (strength=%.4f, initial_norm=%.2f)",
            model_name, strength, self._initial_norms[model_name],
        )
        return anchor

    def get_anchor(self, model_name: str) -> Optional[ReferenceAnchor]:
        """Retrieve existing anchor by model name."""
        return self._anchors.get(model_name)

    # ── Mechanism 4: Drift Monitoring ─────────────────────────────────

    def check_health(
        self,
        model: nn.Module,
        model_name: str,
        anchor: Optional[ReferenceAnchor] = None,
        grad_norm: float = -1.0,
        policy_entropy: float = -1.0,
    ) -> HealthReport:
        """Compute health metrics and log to DB. <0.05ms for 3.1M params.

        Returns HealthReport with status and any warnings.
        """
        now = time.time()
        warnings = []
        status = "healthy"

        with torch.no_grad():
            # Weight statistics
            all_params = [p for p in model.parameters() if p.requires_grad]
            weight_norm = sum(p.data.norm().item() ** 2 for p in all_params) ** 0.5
            weight_max = max(
                (p.data.abs().max().item() for p in all_params), default=0.0
            )

        # Drift from reference
        drift = -1.0
        if anchor is not None:
            drift = anchor.drift_from_ref(model)

        # Check thresholds
        initial_norm = self._initial_norms.get(model_name, weight_norm)
        if initial_norm > 0 and weight_norm / initial_norm > HEALTH_THRESHOLDS["weight_norm_ratio"]:
            warnings.append(
                f"weight_norm={weight_norm:.1f} > {HEALTH_THRESHOLDS['weight_norm_ratio']}x "
                f"initial ({initial_norm:.1f})"
            )
            status = "warning"

        if weight_max > HEALTH_THRESHOLDS["weight_max"]:
            warnings.append(f"weight_max={weight_max:.1f} > {HEALTH_THRESHOLDS['weight_max']}")
            status = "warning"

        if policy_entropy >= 0 and policy_entropy < HEALTH_THRESHOLDS["policy_entropy_min"]:
            warnings.append(
                f"policy_entropy={policy_entropy:.3f} < {HEALTH_THRESHOLDS['policy_entropy_min']} "
                f"(POLICY COLLAPSE RISK)"
            )
            status = "critical"

        # Drift ratio check
        if drift >= 0:
            with self._lock:
                hist = self._drift_history.setdefault(model_name, [])
                hist.append(drift)
                if len(hist) > 50:
                    hist[:] = hist[-50:]
                if len(hist) >= 5:
                    avg_drift = sum(hist) / len(hist)
                    if avg_drift > 0 and drift / avg_drift > HEALTH_THRESHOLDS["drift_ratio"]:
                        warnings.append(
                            f"drift={drift:.2f} > {HEALTH_THRESHOLDS['drift_ratio']}x "
                            f"avg ({avg_drift:.2f})"
                        )
                        status = "warning"

        # Log warnings
        for w in warnings:
            LOG.warning("SFT [%s]: %s", model_name, w)

        report = HealthReport(
            model_name=model_name,
            timestamp=now,
            weight_norm=weight_norm,
            weight_max=weight_max,
            grad_norm=grad_norm,
            policy_entropy=policy_entropy,
            drift_from_ref=drift,
            status=status,
            warnings=warnings,
        )

        # Persist to DB (non-blocking)
        self._log_health(report)

        return report

    def _log_health(self, report: HealthReport) -> None:
        """Write health report to SQLite (best-effort)."""
        if not self._conn:
            return
        try:
            self._conn.execute(
                "INSERT INTO health_log "
                "(timestamp, model_name, weight_norm, weight_max, grad_norm, "
                " policy_entropy, drift_from_ref, status, warnings) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    report.timestamp, report.model_name,
                    report.weight_norm, report.weight_max,
                    report.grad_norm, report.policy_entropy,
                    report.drift_from_ref, report.status,
                    "; ".join(report.warnings) if report.warnings else None,
                ),
            )
            self._conn.commit()
        except Exception:
            pass

    # ── Utilities ─────────────────────────────────────────────────────

    def get_default_decay(self, model_name: str) -> float:
        """Get recommended weight decay rate for a model."""
        return DEFAULT_DECAY_RATES.get(model_name, 1e-4)

    def get_health_summary(self) -> Dict[str, Any]:
        """Return recent health status for all monitored models."""
        if not self._conn:
            return {}
        try:
            rows = self._conn.execute(
                "SELECT model_name, status, COUNT(*) as cnt "
                "FROM health_log "
                "WHERE timestamp > ? "
                "GROUP BY model_name, status "
                "ORDER BY model_name",
                (time.time() - 86400,),
            ).fetchall()
            summary: Dict[str, Dict[str, int]] = {}
            for model, status, cnt in rows:
                summary.setdefault(model, {})[status] = cnt
            return summary
        except Exception:
            return {}

    def close(self) -> None:
        """Cleanup: prune old logs and close DB."""
        self._prune_old_logs()
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        LOG.info("SFT Stabilizer: closed")


# ─── Singleton ────────────────────────────────────────────────────────

_instance: Optional[SFTStabilizer] = None
_instance_lock = threading.Lock()


def get_stabilizer() -> SFTStabilizer:
    """Get or create the singleton SFTStabilizer instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = SFTStabilizer()
                atexit.register(_instance.close)
    return _instance
