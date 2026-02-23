#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
annealer.py — Simulated Annealing mit O(n) Delta-Energy

Kernalgorithmus des Quantum Reflectors. Nutzt Multi-Flip SA
mit Metropolis-Akzeptanz und geometrischer Kühlung zur
globalen Optimierung über Frank's Hypothesenraum (QUBO).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

LOG = logging.getLogger("quantum_reflector.annealer")


@dataclass
class AnnealerConfig:
    """Konfiguration für den Simulated Annealing Solver."""
    T_start: float = 4.0
    T_end: float = 0.05
    steps: int = 2000
    num_runs: int = 200
    max_flips: int = 3          # Max simultane Bit-Flips pro Step
    seed: Optional[int] = None


@dataclass
class AnnealResult:
    """Ergebnis eines Annealing-Laufs."""
    best_energy: float
    best_state: np.ndarray
    energies: np.ndarray        # Energie jedes Runs
    violations: int             # Constraint-Violations in bester Lösung
    mean_energy: float = 0.0
    std_energy: float = 0.0

    def __post_init__(self):
        self.mean_energy = float(np.mean(self.energies))
        self.std_energy = float(np.std(self.energies))


def compute_energy(x: np.ndarray, linear: np.ndarray, Q: np.ndarray) -> float:
    """Volle Energieberechnung: x^T Q x + linear^T x. O(n²)."""
    return float(x @ Q @ x + linear @ x)


def delta_energy_single_flip(
    x: np.ndarray, idx: int, linear: np.ndarray, Q: np.ndarray
) -> float:
    """
    Delta-Energie für einen einzelnen Bit-Flip an Position idx.
    O(n) statt O(n²).

    Herleitung:
        E(x') - E(x) = (1 - 2*x_k) * (h_k + 2 * Q[k] . x)
    wobei h_k = linear[k], x_k ist der aktuelle Wert.
    """
    sign = 1.0 - 2.0 * x[idx]
    return sign * (linear[idx] + 2.0 * np.dot(Q[idx], x))


def delta_energy_multi_flip(
    x: np.ndarray,
    flip_indices: np.ndarray,
    linear: np.ndarray,
    Q: np.ndarray,
) -> float:
    """
    Kaskadierte Delta-Energie für mehrere Bit-Flips.
    O(m*n) für m Flips statt O(n²).

    ACHTUNG: Modifiziert x in-place für korrekte Kaskade.
    Aufrufer muss x vorher kopieren wenn Revert nötig.
    """
    total_delta = 0.0
    for k in flip_indices:
        sign = 1.0 - 2.0 * x[k]
        total_delta += sign * (linear[k] + 2.0 * np.dot(Q[k], x))
        x[k] = 1.0 - x[k]
    return total_delta


def count_violations(x: np.ndarray, one_hot_groups: List[Tuple[int, ...]]) -> int:
    """Zähle One-Hot-Constraint-Verletzungen."""
    violations = 0
    for group in one_hot_groups:
        active = sum(x[i] for i in group)
        if abs(active - 1.0) > 0.5:
            violations += 1
    return violations


def solve(
    linear: np.ndarray,
    Q: np.ndarray,
    one_hot_groups: List[Tuple[int, ...]] = None,
    config: AnnealerConfig = None,
) -> AnnealResult:
    """
    Simulated Annealing Solver.

    Args:
        linear: Lineare Terme (n,). Negativ = bevorzugt.
        Q: Quadratische Kopplungsmatrix (n, n). Symmetrisch.
        one_hot_groups: Liste von Index-Tupeln für One-Hot-Constraints.
        config: SA-Konfiguration.

    Returns:
        AnnealResult mit bester Lösung, Energien, Violations.
    """
    if config is None:
        config = AnnealerConfig()

    n = len(linear)
    rng = np.random.default_rng(config.seed)

    if one_hot_groups is None:
        one_hot_groups = []

    best_energy = np.inf
    best_x = None
    run_energies = np.empty(config.num_runs)

    # Geometrischer Kühlexponent
    cool_exp = 1.0 / config.steps

    for run in range(config.num_runs):
        # Initialisierung: respektiere One-Hot-Constraints
        x = np.zeros(n, dtype=np.float64)
        for group in one_hot_groups:
            chosen = rng.choice(group)
            x[chosen] = 1.0
        # Restliche Variablen (nicht in One-Hot-Groups) zufällig
        grouped = set()
        for g in one_hot_groups:
            grouped.update(g)
        for i in range(n):
            if i not in grouped:
                x[i] = float(rng.integers(0, 2))

        T = config.T_start

        for step in range(config.steps):
            # Multi-Flip: 1 bis max_flips Bits
            flip_count = rng.integers(1, config.max_flips + 1)
            flip_idxs = rng.choice(n, size=min(flip_count, n), replace=False)

            # Kopie für Revert
            x_backup = x.copy()

            # Kaskadiertes Delta (modifiziert x in-place)
            dE = delta_energy_multi_flip(x, flip_idxs, linear, Q)

            if dE < 0 or rng.random() < np.exp(-dE / max(T, 1e-12)):
                pass  # Akzeptiert — x wurde bereits in-place geflippt
            else:
                x[:] = x_backup  # Revert

            # Geometrische Kühlung
            T *= (config.T_end / config.T_start) ** cool_exp

        energy = compute_energy(x, linear, Q)
        run_energies[run] = energy

        if energy < best_energy:
            best_energy = energy
            best_x = x.copy()

    violations = count_violations(best_x, one_hot_groups) if best_x is not None else -1

    return AnnealResult(
        best_energy=float(best_energy),
        best_state=best_x,
        energies=run_energies,
        violations=violations,
    )
