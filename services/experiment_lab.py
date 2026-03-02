#!/usr/bin/env python3
"""
Universal Experiment Lab — Simulation stations for Frank's Inner Sanctum.

Six stations with a common interface: parse narrative → simulate → narrate result.
All computation is pure Python + numpy + sympy. No LLM calls, no subprocess,
no external HTTP. Results are deterministic given the same parameters.

Accessible from:
  1. Sanctum location "lab_experiment" (spatial metaphor)
  2. Autonomous research tool "experiment" (idle thinking)
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

LOG = logging.getLogger("experiment_lab")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SIMULATION_TIMEOUT_S = 10.0      # Hard timeout per simulation
MAX_OUTPUT_CHARS = 2000          # Narration truncation limit
MAX_DAILY_EXPERIMENTS = 20       # Daily budget
G_EARTH = 9.80665               # m/s²
G_GRAV = 6.67430e-11            # Gravitational constant

# ---------------------------------------------------------------------------
# DB path resolution
# ---------------------------------------------------------------------------

try:
    from config.paths import get_db
    DB_PATH = get_db("experiment_lab")
except Exception:
    DB_PATH = Path.home() / ".local" / "share" / "frank" / "db" / "experiment_lab.db"


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS experiments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            station TEXT NOT NULL,
            params_json TEXT NOT NULL,
            result_json TEXT NOT NULL,
            narration TEXT NOT NULL,
            source TEXT DEFAULT 'sanctum',
            duration_ms REAL DEFAULT 0,
            error TEXT DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS experiment_budget (
            date TEXT PRIMARY KEY,
            count INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_exp_station ON experiments(station);
        CREATE INDEX IF NOT EXISTS idx_exp_ts ON experiments(ts);
    """)


def _migrate_hypothesis_column(conn: sqlite3.Connection) -> None:
    """Add hypothesis_id column if missing (for Hypothesis Engine integration)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(experiments)")}
    if "hypothesis_id" not in cols:
        conn.execute(
            "ALTER TABLE experiments ADD COLUMN hypothesis_id TEXT DEFAULT NULL"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_exp_hyp ON experiments(hypothesis_id)"
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Base Station
# ---------------------------------------------------------------------------

class BaseStation(ABC):
    """Abstract base for all experiment stations."""

    name: str = ""
    key: str = ""
    description: str = ""

    @abstractmethod
    def parse(self, narrative: str) -> Optional[dict]:
        """Extract experiment params from narrative. None if no match."""

    @abstractmethod
    def simulate(self, params: dict) -> dict:
        """Run pure computation. Must complete in <10s."""

    @abstractmethod
    def narrate(self, params: dict, result: dict) -> str:
        """Format result as text for Frank."""

    def describe(self) -> str:
        return f"  {self.name} — {self.description}"


# ---------------------------------------------------------------------------
# Station 1: Physics Table
# ---------------------------------------------------------------------------

class PhysicsStation(BaseStation):
    name = "Physics Table"
    key = "physics"
    description = "Projectile motion, collisions, pendulums, inclined planes."

    _RE_PROJECTILE = re.compile(
        r"(?:throw|launch|fire|shoot|toss|hurl|projectile)",
        re.IGNORECASE,
    )
    _RE_COLLISION = re.compile(
        r"(?:collide|collision|crash|bounce|impact)",
        re.IGNORECASE,
    )
    _RE_PENDULUM = re.compile(
        r"(?:pendulum|swing|oscillat)",
        re.IGNORECASE,
    )
    _RE_INCLINE = re.compile(
        r"(?:ramp|incline|slide|slope)",
        re.IGNORECASE,
    )
    _RE_NUMBER = re.compile(r"(\d+(?:\.\d+)?)\s*(?:m/s|m|kg|deg|degrees|°|s)")

    def parse(self, narrative: str) -> Optional[dict]:
        text = narrative.lower()
        numbers = [float(m.group(1)) for m in self._RE_NUMBER.finditer(narrative)]

        if self._RE_PROJECTILE.search(text):
            v0 = numbers[0] if len(numbers) > 0 else 20.0
            angle = numbers[1] if len(numbers) > 1 else 45.0
            mass = numbers[2] if len(numbers) > 2 else 1.0
            return {
                "type": "projectile",
                "v0": max(0.0, min(1000.0, v0)),
                "angle": max(0.0, min(90.0, angle)),
                "mass": max(0.001, min(1e6, mass)),
            }

        if self._RE_COLLISION.search(text):
            m1 = numbers[0] if len(numbers) > 0 else 1.0
            m2 = numbers[1] if len(numbers) > 1 else 2.0
            v1 = numbers[2] if len(numbers) > 2 else 10.0
            v2 = numbers[3] if len(numbers) > 3 else 0.0
            elastic = "elastic" in text and "inelastic" not in text
            return {
                "type": "collision",
                "m1": max(0.001, min(1e6, m1)),
                "m2": max(0.001, min(1e6, m2)),
                "v1": max(-1000.0, min(1000.0, v1)),
                "v2": max(-1000.0, min(1000.0, v2)),
                "elastic": elastic,
            }

        if self._RE_PENDULUM.search(text):
            length = numbers[0] if len(numbers) > 0 else 1.0
            angle0 = numbers[1] if len(numbers) > 1 else 30.0
            return {
                "type": "pendulum",
                "length": max(0.01, min(100.0, length)),
                "angle0": max(0.1, min(170.0, angle0)),
            }

        if self._RE_INCLINE.search(text):
            angle = numbers[0] if len(numbers) > 0 else 30.0
            mass = numbers[1] if len(numbers) > 1 else 1.0
            mu = numbers[2] if len(numbers) > 2 else 0.1
            return {
                "type": "incline",
                "angle": max(1.0, min(89.0, angle)),
                "mass": max(0.001, min(1e6, mass)),
                "mu": max(0.0, min(1.0, mu)),
            }

        return None

    def simulate(self, params: dict) -> dict:
        sim_type = params["type"]

        if sim_type == "projectile":
            v0 = params["v0"]
            angle_deg = params["angle"]
            mass = params["mass"]
            angle_rad = math.radians(angle_deg)
            vx = v0 * math.cos(angle_rad)
            vy = v0 * math.sin(angle_rad)

            if vy <= 0:
                return {"type": "projectile", "flight_time": 0, "range": 0,
                        "max_height": 0, "trajectory": [], "ke_initial": 0}

            t_flight = 2 * vy / G_EARTH
            max_h = vy ** 2 / (2 * G_EARTH)
            rng = vx * t_flight
            ke = 0.5 * mass * v0 ** 2

            trajectory = []
            for i in range(21):
                t = t_flight * i / 20
                x = vx * t
                y = vy * t - 0.5 * G_EARTH * t ** 2
                trajectory.append((round(x, 2), round(max(0.0, y), 2)))

            return {
                "type": "projectile",
                "flight_time": round(t_flight, 3),
                "range": round(rng, 3),
                "max_height": round(max_h, 3),
                "trajectory": trajectory,
                "ke_initial": round(ke, 2),
            }

        if sim_type == "collision":
            m1, m2 = params["m1"], params["m2"]
            v1, v2 = params["v1"], params["v2"]
            p_before = m1 * v1 + m2 * v2
            ke_before = 0.5 * m1 * v1 ** 2 + 0.5 * m2 * v2 ** 2

            if params["elastic"]:
                v1f = ((m1 - m2) * v1 + 2 * m2 * v2) / (m1 + m2)
                v2f = ((m2 - m1) * v2 + 2 * m1 * v1) / (m1 + m2)
                ke_after = 0.5 * m1 * v1f ** 2 + 0.5 * m2 * v2f ** 2
            else:
                vf = p_before / (m1 + m2)
                v1f = v2f = vf
                ke_after = 0.5 * (m1 + m2) * vf ** 2

            return {
                "type": "collision",
                "elastic": params["elastic"],
                "v1_final": round(v1f, 4),
                "v2_final": round(v2f, 4),
                "momentum_before": round(p_before, 4),
                "momentum_after": round(m1 * v1f + m2 * v2f, 4),
                "ke_before": round(ke_before, 4),
                "ke_after": round(ke_after, 4),
                "ke_lost": round(ke_before - ke_after, 4),
            }

        if sim_type == "pendulum":
            L = params["length"]
            theta0 = math.radians(params["angle0"])
            dt = 0.01
            steps = 500
            theta = theta0
            omega = 0.0
            period_est = 2 * math.pi * math.sqrt(L / G_EARTH)
            trajectory = [(0.0, round(math.degrees(theta), 2))]

            for step in range(1, steps + 1):
                omega -= (G_EARTH / L) * math.sin(theta) * dt
                theta += omega * dt
                if step % 50 == 0:
                    trajectory.append((round(step * dt, 2), round(math.degrees(theta), 2)))

            return {
                "type": "pendulum",
                "period_estimate": round(period_est, 4),
                "trajectory": trajectory,
                "max_angle": round(math.degrees(theta0), 2),
                "final_angle": round(math.degrees(theta), 2),
                "time_simulated": round(steps * dt, 2),
            }

        if sim_type == "incline":
            angle_rad = math.radians(params["angle"])
            mass = params["mass"]
            mu = params["mu"]
            f_grav = mass * G_EARTH * math.sin(angle_rad)
            f_fric = mu * mass * G_EARTH * math.cos(angle_rad)
            f_net = f_grav - f_fric

            if f_net <= 0:
                return {
                    "type": "incline",
                    "slides": False,
                    "reason": "Friction exceeds gravitational component",
                    "f_gravity": round(f_grav, 4),
                    "f_friction": round(f_fric, 4),
                }

            a_net = f_net / mass
            dist = 1.0  # simulate 1 meter slide
            t_1m = math.sqrt(2 * dist / a_net)
            v_1m = a_net * t_1m

            return {
                "type": "incline",
                "slides": True,
                "acceleration": round(a_net, 4),
                "time_1m": round(t_1m, 4),
                "velocity_at_1m": round(v_1m, 4),
                "f_gravity": round(f_grav, 4),
                "f_friction": round(f_fric, 4),
                "f_net": round(f_net, 4),
            }

        return {"error": f"Unknown physics type: {sim_type}"}

    def narrate(self, params: dict, result: dict) -> str:
        if "error" in result:
            return f"=== PHYSICS TABLE ===\n  Error: {result['error']}\n"

        t = result["type"]
        lines = [f"=== PHYSICS TABLE: {t.title()} ==="]

        if t == "projectile":
            lines.append(f"  Launch: v0={params['v0']} m/s at {params['angle']}°, mass={params['mass']} kg")
            lines.append(f"  Max height: {result['max_height']} m")
            lines.append(f"  Range: {result['range']} m")
            lines.append(f"  Flight time: {result['flight_time']} s")
            lines.append(f"  KE at launch: {result['ke_initial']} J")
            traj = result["trajectory"]
            if len(traj) > 4:
                pts = [traj[0], traj[len(traj) // 4], traj[len(traj) // 2], traj[-1]]
                lines.append(f"  Trajectory: {' → '.join(f'({x},{y})' for x, y in pts)}")

        elif t == "collision":
            kind = "elastic" if result["elastic"] else "inelastic"
            lines.append(f"  Type: {kind}")
            lines.append(f"  Before: m1={params['m1']}kg @ {params['v1']}m/s, m2={params['m2']}kg @ {params['v2']}m/s")
            lines.append(f"  After: v1={result['v1_final']} m/s, v2={result['v2_final']} m/s")
            lines.append(f"  Momentum: {result['momentum_before']} → {result['momentum_after']} kg·m/s (conserved)")
            lines.append(f"  KE: {result['ke_before']} → {result['ke_after']} J (lost: {result['ke_lost']} J)")

        elif t == "pendulum":
            lines.append(f"  Length: {params['length']} m, initial angle: {params['angle0']}°")
            lines.append(f"  Period (small-angle): {result['period_estimate']} s")
            lines.append(f"  Simulated: {result['time_simulated']} s")
            lines.append(f"  Angle: {result['max_angle']}° → {result['final_angle']}° (at t={result['time_simulated']}s)")

        elif t == "incline":
            lines.append(f"  Angle: {params['angle']}°, mass: {params['mass']} kg, friction: μ={params['mu']}")
            if result["slides"]:
                lines.append(f"  Object slides! Acceleration: {result['acceleration']} m/s²")
                lines.append(f"  Time to slide 1m: {result['time_1m']} s")
                lines.append(f"  Velocity at 1m: {result['velocity_at_1m']} m/s")
            else:
                lines.append(f"  Object stays still: {result['reason']}")
            lines.append(f"  Forces: gravity={result['f_gravity']}N, friction={result['f_friction']}N")

        lines.append("=" * (len(lines[0])))
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Station 2: Chemistry Bench
# ---------------------------------------------------------------------------

# Atomic masses for molar mass calculation
_ATOMIC_MASS = {
    "H": 1.008, "He": 4.003, "Li": 6.941, "C": 12.011, "N": 14.007,
    "O": 15.999, "F": 18.998, "Na": 22.990, "Mg": 24.305, "Al": 26.982,
    "Si": 28.086, "P": 30.974, "S": 32.065, "Cl": 35.453, "K": 39.098,
    "Ca": 40.078, "Fe": 55.845, "Cu": 63.546, "Zn": 65.38, "Br": 79.904,
    "Ag": 107.868, "I": 126.904, "Au": 196.967,
}

# Compound name → formula mapping
_COMPOUND_NAMES = {
    "water": "H2O", "hydrogen": "H2", "oxygen": "O2", "nitrogen": "N2",
    "carbon dioxide": "CO2", "carbon monoxide": "CO",
    "salt": "NaCl", "sodium chloride": "NaCl", "sodium": "Na", "chlorine": "Cl2",
    "hydrochloric acid": "HCl", "acid": "HCl",
    "sodium hydroxide": "NaOH", "base": "NaOH", "lye": "NaOH",
    "sulfuric acid": "H2SO4", "nitric acid": "HNO3",
    "iron": "Fe", "copper": "Cu", "zinc": "Zn", "gold": "Au", "silver": "Ag",
    "copper sulfate": "CuSO4", "copper sulphate": "CuSO4",
    "methane": "CH4", "ethanol": "C2H5OH", "ammonia": "NH3",
    "calcium carbonate": "CaCO3", "limestone": "CaCO3",
    "magnesium": "Mg", "aluminum": "Al", "aluminium": "Al",
    "potassium": "K", "calcium": "Ca",
    "hydrogen peroxide": "H2O2",
    "rust": "Fe2O3", "iron oxide": "Fe2O3",
}

# Reaction database: frozenset of reactant formulas → reaction info
_REACTIONS = {
    frozenset(["H2", "O2"]): {
        "equation": "2H₂ + O₂ → 2H₂O",
        "type": "combustion",
        "enthalpy_kj": -571.6,
        "products": ["H2O"],
        "observable": "Violent exothermic reaction! Bright flash, water vapor produced.",
        "dangerous": True,
    },
    frozenset(["HCl", "NaOH"]): {
        "equation": "HCl + NaOH → NaCl + H₂O",
        "type": "neutralization",
        "enthalpy_kj": -57.1,
        "products": ["NaCl", "H2O"],
        "observable": "Heat released, solution becomes neutral. pH shifts to ~7.",
    },
    frozenset(["Fe", "O2"]): {
        "equation": "4Fe + 3O₂ → 2Fe₂O₃",
        "type": "oxidation",
        "enthalpy_kj": -1648.0,
        "products": ["Fe2O3"],
        "observable": "Iron slowly rusts, turning reddish-brown. Slow reaction at room temperature.",
    },
    frozenset(["Na", "Cl2"]): {
        "equation": "2Na + Cl₂ → 2NaCl",
        "type": "synthesis",
        "enthalpy_kj": -822.0,
        "products": ["NaCl"],
        "observable": "Sodium burns brilliantly in chlorine gas, forming white salt crystals.",
        "dangerous": True,
    },
    frozenset(["CuSO4", "Fe"]): {
        "equation": "CuSO₄ + Fe → FeSO₄ + Cu",
        "type": "displacement",
        "enthalpy_kj": -15.0,
        "products": ["FeSO4", "Cu"],
        "observable": "Iron becomes coated in reddish copper. Blue solution fades to green.",
    },
    frozenset(["CuSO4", "H2O"]): {
        "equation": "CuSO₄ + H₂O → CuSO₄(aq)",
        "type": "dissolution",
        "enthalpy_kj": -11.0,
        "products": ["CuSO4(aq)"],
        "observable": "Blue crystals dissolve into water, turning the solution bright blue.",
    },
    frozenset(["NaCl", "H2O"]): {
        "equation": "NaCl → Na⁺(aq) + Cl⁻(aq)",
        "type": "dissolution",
        "enthalpy_kj": 3.9,
        "products": ["Na+(aq)", "Cl-(aq)"],
        "observable": "Salt dissolves readily. Solution is slightly endothermic — feels cool.",
    },
    frozenset(["Zn", "HCl"]): {
        "equation": "Zn + 2HCl → ZnCl₂ + H₂↑",
        "type": "displacement",
        "enthalpy_kj": -153.0,
        "products": ["ZnCl2", "H2"],
        "observable": "Vigorous bubbling as hydrogen gas escapes. Zinc dissolves.",
    },
    frozenset(["CaCO3", "HCl"]): {
        "equation": "CaCO₃ + 2HCl → CaCl₂ + H₂O + CO₂↑",
        "type": "decomposition",
        "enthalpy_kj": -16.0,
        "products": ["CaCl2", "H2O", "CO2"],
        "observable": "Fizzing and bubbling as CO₂ gas escapes. Limestone dissolves.",
    },
    frozenset(["CH4", "O2"]): {
        "equation": "CH₄ + 2O₂ → CO₂ + 2H₂O",
        "type": "combustion",
        "enthalpy_kj": -890.4,
        "products": ["CO2", "H2O"],
        "observable": "Blue flame, heat, water vapor and CO₂ produced.",
    },
    frozenset(["NH3", "HCl"]): {
        "equation": "NH₃ + HCl → NH₄Cl",
        "type": "synthesis",
        "enthalpy_kj": -176.0,
        "products": ["NH4Cl"],
        "observable": "White smoke of ammonium chloride crystals forms in the air.",
    },
    frozenset(["H2O2"]): {
        "equation": "2H₂O₂ → 2H₂O + O₂↑",
        "type": "decomposition",
        "enthalpy_kj": -196.0,
        "products": ["H2O", "O2"],
        "observable": "Bubbles of oxygen gas form. Reaction accelerated by catalyst.",
    },
    frozenset(["Mg", "O2"]): {
        "equation": "2Mg + O₂ → 2MgO",
        "type": "combustion",
        "enthalpy_kj": -1204.0,
        "products": ["MgO"],
        "observable": "Brilliant white flame. Magnesium burns intensely, producing white ash.",
        "dangerous": True,
    },
    frozenset(["Na", "H2O"]): {
        "equation": "2Na + 2H₂O → 2NaOH + H₂↑",
        "type": "displacement",
        "enthalpy_kj": -368.0,
        "products": ["NaOH", "H2"],
        "observable": "Sodium fizzes violently on water surface, may ignite H₂ gas!",
        "dangerous": True,
    },
    frozenset(["Cu", "HNO3"]): {
        "equation": "3Cu + 8HNO₃ → 3Cu(NO₃)₂ + 2NO↑ + 4H₂O",
        "type": "oxidation",
        "enthalpy_kj": -37.0,
        "products": ["Cu(NO3)2", "NO", "H2O"],
        "observable": "Copper dissolves, solution turns blue-green. Brown NO₂ fumes.",
    },
    frozenset(["H2SO4", "NaOH"]): {
        "equation": "H₂SO₄ + 2NaOH → Na₂SO₄ + 2H₂O",
        "type": "neutralization",
        "enthalpy_kj": -114.0,
        "products": ["Na2SO4", "H2O"],
        "observable": "Strong exothermic reaction. Solution becomes neutral sodium sulfate.",
    },
    frozenset(["Fe", "CuSO4"]): {  # Alias for CuSO4+Fe
        "equation": "CuSO₄ + Fe → FeSO₄ + Cu",
        "type": "displacement",
        "enthalpy_kj": -15.0,
        "products": ["FeSO4", "Cu"],
        "observable": "Iron becomes coated in reddish copper. Blue solution fades to green.",
    },
    frozenset(["Zn", "CuSO4"]): {
        "equation": "CuSO₄ + Zn → ZnSO₄ + Cu",
        "type": "displacement",
        "enthalpy_kj": -210.0,
        "products": ["ZnSO4", "Cu"],
        "observable": "Zinc strip becomes coated in copper. Blue solution fades.",
    },
    frozenset(["Al", "O2"]): {
        "equation": "4Al + 3O₂ → 2Al₂O₃",
        "type": "combustion",
        "enthalpy_kj": -3351.0,
        "products": ["Al2O3"],
        "observable": "Aluminum burns with intense white heat. Forms alumina (white powder).",
        "dangerous": True,
    },
    frozenset(["K", "H2O"]): {
        "equation": "2K + 2H₂O → 2KOH + H₂↑",
        "type": "displacement",
        "enthalpy_kj": -392.0,
        "products": ["KOH", "H2"],
        "observable": "Violent reaction! Potassium catches fire on water, purple flame.",
        "dangerous": True,
    },
}


def _parse_formula_mass(formula: str) -> Optional[float]:
    """Calculate molar mass from a chemical formula string.
    Handles parenthetical groups like Ca(OH)2, Mg(NO3)2, etc.
    """
    # Direct computation: handle parenthetical groups by mass accumulation
    total = 0.0
    i = 0
    s = formula
    while i < len(s):
        if s[i] == '(':
            # Find matching close paren
            depth = 1
            j = i + 1
            while j < len(s) and depth > 0:
                if s[j] == '(':
                    depth += 1
                elif s[j] == ')':
                    depth -= 1
                j += 1
            if depth != 0:
                return None  # Unclosed parenthesis
            inner = s[i + 1:j - 1]
            # Get multiplier after close paren
            k = j
            while k < len(s) and s[k].isdigit():
                k += 1
            multiplier = int(s[j:k]) if j < k else 1
            inner_mass = _parse_formula_mass(inner)  # Recursive for nested parens
            if inner_mass is None:
                return None
            total += inner_mass * multiplier
            i = k
        elif s[i].isupper():
            # Element symbol
            j = i + 1
            if j < len(s) and s[j].islower():
                j += 1
            elem = s[i:j]
            if elem not in _ATOMIC_MASS:
                return None
            # Get count
            k = j
            while k < len(s) and s[k].isdigit():
                k += 1
            count = int(s[j:k]) if j < k else 1
            total += _ATOMIC_MASS[elem] * count
            i = k
        else:
            i += 1  # Skip unexpected chars

    return round(total, 3) if total > 0 else None


class ChemistryStation(BaseStation):
    name = "Chemistry Bench"
    key = "chemistry"
    description = "Mix compounds, check pH, calculate molar masses, observe reactions."

    _RE_MIX = re.compile(
        r"(?:mix|react|combine|add|pour|dissolve)",
        re.IGNORECASE,
    )
    _RE_PH = re.compile(r"(?:ph|acidity|alkalinity)", re.IGNORECASE)
    _RE_MOLAR = re.compile(r"(?:molar mass|molecular weight|molar weight)", re.IGNORECASE)
    _RE_DILUTE = re.compile(r"(?:dilut)", re.IGNORECASE)

    def _identify_compounds(self, text: str) -> List[str]:
        """Find compound formulas mentioned in text."""
        text_lower = text.lower()
        found = []
        # Check named compounds (longest match first)
        for name in sorted(_COMPOUND_NAMES, key=len, reverse=True):
            if name in text_lower:
                formula = _COMPOUND_NAMES[name]
                if formula not in found:
                    found.append(formula)
                text_lower = text_lower.replace(name, "", 1)
        # Check raw formulas (e.g., "H2O", "NaCl")
        for formula in set(_COMPOUND_NAMES.values()):
            if formula in text and formula not in found:
                found.append(formula)
        return found

    def parse(self, narrative: str) -> Optional[dict]:
        text = narrative

        # Molar mass query
        if self._RE_MOLAR.search(text):
            compounds = self._identify_compounds(text)
            if compounds:
                return {"type": "molar_mass", "compound": compounds[0]}

        # pH query
        if self._RE_PH.search(text):
            compounds = self._identify_compounds(text)
            conc_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:M|mol/L|molar)", text)
            conc = float(conc_match.group(1)) if conc_match else 0.1
            if compounds:
                return {"type": "ph", "compound": compounds[0],
                        "concentration": max(1e-14, min(10.0, conc))}

        # Dilution
        if self._RE_DILUTE.search(text):
            numbers = re.findall(r"(\d+(?:\.\d+)?)", text)
            if len(numbers) >= 3:
                return {
                    "type": "dilution",
                    "c1": float(numbers[0]),
                    "v1": float(numbers[1]),
                    "c2": float(numbers[2]),
                }

        # Reaction (mix/combine)
        if self._RE_MIX.search(text):
            compounds = self._identify_compounds(text)
            if len(compounds) >= 2:
                return {"type": "reaction", "reactants": compounds[:3]}
            if len(compounds) == 1:
                # Single compound decomposition
                return {"type": "reaction", "reactants": compounds}

        # Fallback: any two compounds mentioned
        compounds = self._identify_compounds(text)
        if len(compounds) >= 2:
            return {"type": "reaction", "reactants": compounds[:3]}

        return None

    def simulate(self, params: dict) -> dict:
        sim_type = params["type"]

        if sim_type == "molar_mass":
            formula = params["compound"]
            mass = _parse_formula_mass(formula)
            if mass is None:
                return {"error": f"Cannot parse formula: {formula}"}
            return {"type": "molar_mass", "formula": formula, "mass_g_mol": mass}

        if sim_type == "ph":
            compound = params["compound"]
            conc = params["concentration"]
            # Strong acids
            acids = {"HCl": 1, "H2SO4": 2, "HNO3": 1}
            # Strong bases
            bases = {"NaOH": 1, "KOH": 1, "Ca(OH)2": 2}

            if compound in acids:
                h_conc = conc * acids[compound]
                ph = -math.log10(max(h_conc, 1e-14))
            elif compound in bases:
                oh_conc = conc * bases[compound]
                poh = -math.log10(max(oh_conc, 1e-14))
                ph = 14.0 - poh
            elif compound == "H2O":
                ph = 7.0
            else:
                return {"type": "ph", "compound": compound,
                        "ph": None, "note": f"pH calculation not available for {compound}"}

            return {
                "type": "ph",
                "compound": compound,
                "concentration": conc,
                "ph": round(max(0.0, min(14.0, ph)), 2),
            }

        if sim_type == "dilution":
            c1, v1, c2 = params["c1"], params["v1"], params["c2"]
            if c1 <= 0 or v1 <= 0:
                return {"error": "Initial concentration and volume must be > 0"}
            if c2 <= 0:
                return {"error": "Target concentration must be > 0"}
            if c2 > c1:
                return {"error": "Cannot dilute to a higher concentration (C2 must be ≤ C1)"}
            v2 = c1 * v1 / c2
            return {
                "type": "dilution",
                "c1": c1, "v1": v1, "c2": c2, "v2": round(v2, 4),
            }

        if sim_type == "reaction":
            reactants = params["reactants"]
            key = frozenset(reactants)
            reaction = _REACTIONS.get(key)
            if reaction:
                return {
                    "type": "reaction",
                    "occurred": True,
                    "reactants": reactants,
                    "reaction": reaction,
                }
            # Try subsets for decomposition
            for r in reactants:
                key1 = frozenset([r])
                if key1 in _REACTIONS:
                    return {
                        "type": "reaction",
                        "occurred": True,
                        "reactants": [r],
                        "reaction": _REACTIONS[key1],
                    }
            return {
                "type": "reaction",
                "occurred": False,
                "reactants": reactants,
            }

        return {"error": f"Unknown chemistry type: {sim_type}"}

    def narrate(self, params: dict, result: dict) -> str:
        if "error" in result:
            return f"=== CHEMISTRY BENCH ===\n  Error: {result['error']}\n"

        t = result["type"]
        lines = [f"=== CHEMISTRY BENCH: {t.replace('_', ' ').title()} ==="]

        if t == "molar_mass":
            lines.append(f"  Formula: {result['formula']}")
            lines.append(f"  Molar mass: {result['mass_g_mol']} g/mol")

        elif t == "ph":
            lines.append(f"  Substance: {result['compound']} at {result.get('concentration', '?')}M")
            if result["ph"] is not None:
                ph = result["ph"]
                lines.append(f"  pH = {ph}")
                if ph < 3:
                    lines.append("  Classification: STRONG ACID")
                elif ph < 6:
                    lines.append("  Classification: Weak acid")
                elif ph < 8:
                    lines.append("  Classification: Neutral")
                elif ph < 11:
                    lines.append("  Classification: Weak base")
                else:
                    lines.append("  Classification: STRONG BASE")
            else:
                lines.append(f"  {result.get('note', 'Unable to determine pH')}")

        elif t == "dilution":
            lines.append(f"  C1={result['c1']}M, V1={result['v1']}L → C2={result['c2']}M")
            lines.append(f"  Required final volume: V2 = {result['v2']} L")
            lines.append(f"  Add {round(result['v2'] - params['v1'], 4)} L of solvent")

        elif t == "reaction":
            if result["occurred"]:
                r = result["reaction"]
                lines.append(f"  {r['equation']}")
                lines.append(f"  Type: {r['type']}")
                lines.append(f"  Enthalpy: {r['enthalpy_kj']} kJ/mol "
                             f"({'exothermic' if r['enthalpy_kj'] < 0 else 'endothermic'})")
                lines.append(f"  Observation: {r['observable']}")
                if r.get("dangerous"):
                    lines.append("  ⚠ DANGEROUS REACTION — handle with extreme care!")
            else:
                lines.append(f"  Mixed: {' + '.join(result['reactants'])}")
                lines.append("  Result: No visible reaction. The compounds remain separate.")

        lines.append("=" * max(len(lines[0]), 30))
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Station 3: Astronomy Orrery
# ---------------------------------------------------------------------------

_PRESETS = {
    "inner_solar": [
        {"name": "Sun", "mass": 1.989e30, "x": 0, "y": 0, "vx": 0, "vy": 0},
        {"name": "Mercury", "mass": 3.285e23, "x": 5.791e10, "y": 0, "vx": 0, "vy": 47360},
        {"name": "Venus", "mass": 4.867e24, "x": 1.082e11, "y": 0, "vx": 0, "vy": 35020},
        {"name": "Earth", "mass": 5.972e24, "x": 1.496e11, "y": 0, "vx": 0, "vy": 29780},
        {"name": "Mars", "mass": 6.39e23, "x": 2.279e11, "y": 0, "vx": 0, "vy": 24070},
    ],
    "earth_moon": [
        {"name": "Earth", "mass": 5.972e24, "x": 0, "y": 0, "vx": 0, "vy": 0},
        {"name": "Moon", "mass": 7.342e22, "x": 3.844e8, "y": 0, "vx": 0, "vy": 1022},
    ],
    "binary_star": [
        {"name": "Star A", "mass": 1.989e30, "x": -5e10, "y": 0, "vx": 0, "vy": -15000},
        {"name": "Star B", "mass": 1.989e30, "x": 5e10, "y": 0, "vx": 0, "vy": 15000},
    ],
    "three_body": [
        {"name": "A", "mass": 1e30, "x": 0, "y": 1e11, "vx": 15000, "vy": 0},
        {"name": "B", "mass": 1e30, "x": 8.66e10, "y": -5e10, "vx": -7500, "vy": 12990},
        {"name": "C", "mass": 1e30, "x": -8.66e10, "y": -5e10, "vx": -7500, "vy": -12990},
    ],
    "jupiter_system": [
        {"name": "Jupiter", "mass": 1.898e27, "x": 0, "y": 0, "vx": 0, "vy": 0},
        {"name": "Io", "mass": 8.93e22, "x": 4.217e8, "y": 0, "vx": 0, "vy": 17334},
        {"name": "Europa", "mass": 4.80e22, "x": 6.711e8, "y": 0, "vx": 0, "vy": 13740},
        {"name": "Ganymede", "mass": 1.48e23, "x": 1.0704e9, "y": 0, "vx": 0, "vy": 10880},
    ],
}


class AstronomyStation(BaseStation):
    name = "Astronomy Orrery"
    key = "astronomy"
    description = "Simulate orbital mechanics, planetary systems, binary stars, three-body problems."

    _RE_ORBIT = re.compile(
        r"(?:orbit|planet|solar|star|celestial|orrery|gravity|n.body|simulate.*system"
        r"|three.body|3.body|binary|jupiter|lunar|moon)",
        re.IGNORECASE,
    )
    _RE_PRESET = {
        "inner_solar": re.compile(r"(?:inner solar|solar system|planets)", re.I),
        "earth_moon": re.compile(r"(?:earth.moon|moon.orbit|lunar)", re.I),
        "binary_star": re.compile(r"(?:binary|two.star|double.star)", re.I),
        "three_body": re.compile(r"(?:three.body|3.body|chaotic|lagrange)", re.I),
        "jupiter_system": re.compile(r"(?:jupiter|galilean|io|europa|ganymede)", re.I),
    }

    def parse(self, narrative: str) -> Optional[dict]:
        if not self._RE_ORBIT.search(narrative):
            return None

        preset = "inner_solar"
        for key, pat in self._RE_PRESET.items():
            if pat.search(narrative):
                preset = key
                break

        # Extract time
        time_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:year|yr|y)", narrative, re.I)
        time_years = float(time_match.group(1)) if time_match else 1.0
        time_years = max(0.01, min(100.0, time_years))

        steps_match = re.search(r"(\d+)\s*steps", narrative, re.I)
        steps = int(steps_match.group(1)) if steps_match else 2000
        steps = max(100, min(10000, steps))

        return {"preset": preset, "time_years": time_years, "steps": steps}

    def simulate(self, params: dict) -> dict:
        preset_name = params["preset"]
        bodies = _PRESETS.get(preset_name, _PRESETS["inner_solar"])
        N = len(bodies)
        time_years = params["time_years"]
        steps = params["steps"]

        total_time_s = time_years * 365.25 * 24 * 3600
        dt = total_time_s / steps

        # Initialize arrays
        pos = np.array([[b["x"], b["y"]] for b in bodies], dtype=np.float64)
        vel = np.array([[b["vx"], b["vy"]] for b in bodies], dtype=np.float64)
        masses = np.array([b["mass"] for b in bodies], dtype=np.float64)
        names = [b["name"] for b in bodies]
        epsilon = 1e8  # Softening

        def compute_accel(positions):
            acc = np.zeros_like(positions)
            for i in range(N):
                for j in range(i + 1, N):
                    r = positions[j] - positions[i]
                    dist = np.sqrt(np.sum(r ** 2) + epsilon ** 2)
                    f = G_GRAV * r / dist ** 3
                    acc[i] += masses[j] * f
                    acc[j] -= masses[i] * f
            return acc

        def compute_energy(positions, velocities):
            ke = 0.5 * np.sum(masses[:, None] * velocities ** 2)
            pe = 0.0
            for i in range(N):
                for j in range(i + 1, N):
                    r = np.sqrt(np.sum((positions[j] - positions[i]) ** 2) + epsilon ** 2)
                    pe -= G_GRAV * masses[i] * masses[j] / r
            return ke + pe

        # Record initial energy
        E0 = compute_energy(pos, vel)

        # Leapfrog integration
        acc = compute_accel(pos)
        snap_interval = max(1, steps // 20)
        trajectories = {name: [] for name in names}
        energies = []

        for step in range(steps):
            # Half-step velocity
            vel += 0.5 * acc * dt
            # Full-step position
            pos += vel * dt
            # New acceleration
            acc = compute_accel(pos)
            # Half-step velocity
            vel += 0.5 * acc * dt

            if step % snap_interval == 0:
                for i, name in enumerate(names):
                    trajectories[name].append((float(pos[i, 0]), float(pos[i, 1])))
                energies.append(float(compute_energy(pos, vel)))

        E_final = compute_energy(pos, vel)
        dE_rel = abs((E_final - E0) / E0) if abs(E0) > 1e-30 else 0.0

        # Analyze orbits — compute distances from body 0 (central body)
        orbit_info = {}
        for i, name in enumerate(names):
            if i == 0:
                continue
            pts = trajectories[name]
            distances = [math.sqrt(x ** 2 + y ** 2) for x, y in pts]
            if distances:
                orbit_info[name] = {
                    "min_r": f"{min(distances):.3e}",
                    "max_r": f"{max(distances):.3e}",
                    "mean_r": f"{sum(distances) / len(distances):.3e}",
                }

        return {
            "preset": preset_name,
            "n_bodies": N,
            "names": names,
            "time_years": time_years,
            "steps": steps,
            "dt_s": round(dt, 1),
            "energy_conservation": f"{dE_rel * 100:.4f}%",
            "stable": dE_rel < 0.01,
            "orbit_info": orbit_info,
            "snapshots_per_body": len(trajectories[names[0]]),
        }

    def narrate(self, params: dict, result: dict) -> str:
        lines = [f"=== ASTRONOMY ORRERY: {result['preset'].replace('_', ' ').title()} ==="]
        lines.append(f"  Bodies: {', '.join(result['names'])}")
        lines.append(f"  Simulated: {result['time_years']} year(s) ({result['steps']} steps, dt={result['dt_s']}s)")
        lines.append(f"  Energy conservation: dE/E = {result['energy_conservation']} "
                      f"({'STABLE' if result['stable'] else 'UNSTABLE — energy drift detected'})")

        for name, info in result.get("orbit_info", {}).items():
            lines.append(f"  {name}: r_min={info['min_r']}m, r_max={info['max_r']}m, r_mean={info['mean_r']}m")

        lines.append(f"  Trajectory snapshots: {result['snapshots_per_body']} per body")
        lines.append("=" * max(len(lines[0]), 30))
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Station 4: GoL Sandbox
# ---------------------------------------------------------------------------

_GOL_PATTERNS = {
    "glider": [(0, 1), (1, 2), (2, 0), (2, 1), (2, 2)],
    "blinker": [(1, 0), (1, 1), (1, 2)],
    "block": [(0, 0), (0, 1), (1, 0), (1, 1)],
    "r_pentomino": [(0, 1), (0, 2), (1, 0), (1, 1), (2, 1)],
    "acorn": [(0, 1), (1, 3), (2, 0), (2, 1), (2, 4), (2, 5), (2, 6)],
    "pulsar": [  # Period-3 oscillator
        # Top-left quadrant (replicated by symmetry below)
        (2, 0), (3, 0), (4, 0), (0, 2), (0, 3), (0, 4),
        (2, 5), (3, 5), (4, 5), (5, 2), (5, 3), (5, 4),
        # Top-right quadrant
        (2, 7), (3, 7), (4, 7), (0, 8), (0, 9), (0, 10),
        (2, 12), (3, 12), (4, 12), (5, 8), (5, 9), (5, 10),
        # Bottom-left
        (7, 0), (8, 0), (9, 0), (7, 5), (8, 5), (9, 5),
        (10, 2), (10, 3), (10, 4), (12, 2), (12, 3), (12, 4),
        # Bottom-right
        (7, 7), (8, 7), (9, 7), (7, 12), (8, 12), (9, 12),
        (10, 8), (10, 9), (10, 10), (12, 8), (12, 9), (12, 10),
    ],
    "glider_gun": [  # Gosper glider gun
        (5, 1), (5, 2), (6, 1), (6, 2),
        (3, 13), (3, 14), (4, 12), (4, 16), (5, 11), (5, 17),
        (6, 11), (6, 15), (6, 17), (6, 18), (7, 11), (7, 17),
        (8, 12), (8, 16), (9, 13), (9, 14),
        (1, 25), (2, 23), (2, 25), (3, 21), (3, 22),
        (4, 21), (4, 22), (5, 21), (5, 22),
        (6, 23), (6, 25), (7, 25),
        (3, 35), (3, 36), (4, 35), (4, 36),
    ],
}

_GOL_NAMED_RULES = {
    "conway": ([3], [2, 3]),
    "highlife": ([3, 6], [2, 3]),
    "seeds": ([2], []),
    "daynight": ([3, 6, 7, 8], [3, 4, 6, 7, 8]),
    "life_without_death": ([3], [0, 1, 2, 3, 4, 5, 6, 7, 8]),
    "diamoeba": ([3, 5, 6, 7, 8], [5, 6, 7, 8]),
}


class GoLStation(BaseStation):
    name = "GoL Sandbox"
    key = "gol"
    description = "Game of Life with custom rules, patterns, and grid sizes."

    _RE_GOL = re.compile(
        r"(?:game of life|gol\b|cellular automat|conway|life.?like)",
        re.IGNORECASE,
    )
    _RE_RULE = re.compile(r"B(\d+)/S(\d+)", re.IGNORECASE)
    _RE_PATTERN = re.compile(
        r"(?:glider.?gun|glider|blinker|block|r.?pentomino|acorn|pulsar|random)",
        re.IGNORECASE,
    )
    _RE_NAMED_RULE = re.compile(
        r"(?:highlife|seeds|day\s*night|diamoeba|life without death)",
        re.IGNORECASE,
    )

    def parse(self, narrative: str) -> Optional[dict]:
        if not self._RE_GOL.search(narrative) and not self._RE_RULE.search(narrative):
            # Also match if specific pattern names mentioned
            if not self._RE_PATTERN.search(narrative):
                return None

        # Rule extraction
        rule_match = self._RE_RULE.search(narrative)
        if rule_match:
            birth = [int(d) for d in rule_match.group(1)]
            survive = [int(d) for d in rule_match.group(2)]
        else:
            # Check named rules
            named = self._RE_NAMED_RULE.search(narrative)
            if named:
                rule_name = named.group(0).lower().replace(" ", "_").replace("night", "night")
                for key, (b, s) in _GOL_NAMED_RULES.items():
                    if key in rule_name or rule_name in key:
                        birth, survive = b, s
                        break
                else:
                    birth, survive = [3], [2, 3]
            else:
                birth, survive = [3], [2, 3]  # Conway default

        # Pattern extraction
        pat_match = self._RE_PATTERN.search(narrative)
        if pat_match:
            pat_name = pat_match.group(0).lower().replace(" ", "_").replace("-", "_")
            if "gun" in pat_name:
                pat_name = "glider_gun"
            elif "pentomino" in pat_name:
                pat_name = "r_pentomino"
        else:
            pat_name = "random"

        # Grid size
        size_match = re.search(r"(\d+)\s*x\s*\d+|grid\s*(?:size)?[:=]?\s*(\d+)", narrative, re.I)
        if size_match:
            size = int(size_match.group(1) or size_match.group(2))
        else:
            size = 64
        size = max(16, min(128, size))

        # Steps
        steps_match = re.search(r"(\d+)\s*(?:steps|generations|ticks|iterations)", narrative, re.I)
        steps = int(steps_match.group(1)) if steps_match else 200
        steps = max(1, min(5000, steps))

        return {
            "birth": birth,
            "survive": survive,
            "pattern": pat_name,
            "grid_size": size,
            "steps": steps,
        }

    def simulate(self, params: dict) -> dict:
        size = params["grid_size"]
        birth = set(params["birth"])
        survive = set(params["survive"])
        steps = params["steps"]
        pat_name = params["pattern"]

        # Initialize grid
        grid = np.zeros((size, size), dtype=np.uint8)

        if pat_name == "random":
            grid = (np.random.random((size, size)) < 0.3).astype(np.uint8)
        elif pat_name in _GOL_PATTERNS:
            cells = _GOL_PATTERNS[pat_name]
            offset_y = size // 2 - 3
            offset_x = size // 2 - 3
            for dy, dx in cells:
                y = (offset_y + dy) % size
                x = (offset_x + dx) % size
                grid[y, x] = 1
        else:
            grid = (np.random.random((size, size)) < 0.3).astype(np.uint8)

        population = [int(np.sum(grid))]
        # Store initial grid snapshot
        initial_grid = grid.copy()

        # Birth/survive lookup arrays for vectorized operation
        birth_arr = np.zeros(9, dtype=np.uint8)
        surv_arr = np.zeros(9, dtype=np.uint8)
        for b in birth:
            if 0 <= b <= 8:
                birth_arr[b] = 1
        for s in survive:
            if 0 <= s <= 8:
                surv_arr[s] = 1

        for step in range(steps):
            # Neighbor count — pad + slice (same algo as AURA _conway_step)
            p = np.pad(grid, 1, mode="wrap")
            n = (p[0:size, 0:size] + p[0:size, 1:size + 1] + p[0:size, 2:size + 2] +
                 p[1:size + 1, 0:size] + p[1:size + 1, 2:size + 2] +
                 p[2:size + 2, 0:size] + p[2:size + 2, 1:size + 1] + p[2:size + 2, 2:size + 2])

            new_grid = np.zeros_like(grid)
            for count in range(9):
                mask = (n == count)
                if birth_arr[count]:
                    new_grid |= (mask & (grid == 0)).astype(np.uint8)
                if surv_arr[count]:
                    new_grid |= (mask & (grid == 1)).astype(np.uint8)

            grid = new_grid
            population.append(int(np.sum(grid)))

        # Determine trend
        if population[-1] == 0:
            trend = "extinct"
        elif len(population) > 20:
            recent = population[-20:]
            if max(recent) == min(recent):
                trend = "stable"
            elif max(recent) - min(recent) <= 5 and all(
                abs(recent[i] - recent[i + 1]) <= 2 for i in range(len(recent) - 1)
            ):
                trend = "oscillating"
            elif population[-1] > population[0] * 1.5:
                trend = "growing"
            elif population[-1] < population[0] * 0.5:
                trend = "dying"
            else:
                trend = "fluctuating"
        else:
            trend = "stable" if population[-1] == population[0] else "changed"

        # ASCII viewport (16x16 centered on activity)
        alive_cells = np.argwhere(grid == 1)
        if len(alive_cells) > 0:
            cy = int(np.mean(alive_cells[:, 0]))
            cx = int(np.mean(alive_cells[:, 1]))
        else:
            cy, cx = size // 2, size // 2

        vp_size = 16
        y0 = max(0, cy - vp_size // 2)
        x0 = max(0, cx - vp_size // 2)
        y1 = min(size, y0 + vp_size)
        x1 = min(size, x0 + vp_size)

        ascii_grid = []
        for y in range(y0, y1):
            row = ""
            for x in range(x0, x1):
                row += "*" if grid[y, x] else "."
            ascii_grid.append(row)

        return {
            "rule": f"B{''.join(str(b) for b in sorted(birth))}/S{''.join(str(s) for s in sorted(survive))}",
            "pattern": pat_name,
            "grid_size": size,
            "steps": steps,
            "pop_initial": population[0],
            "pop_final": population[-1],
            "pop_peak": max(population),
            "pop_min": min(population),
            "trend": trend,
            "ascii": ascii_grid,
        }

    def narrate(self, params: dict, result: dict) -> str:
        lines = [f"=== GOL SANDBOX: {result['rule']} ==="]
        lines.append(f"  Grid: {result['grid_size']}x{result['grid_size']}, Pattern: {result['pattern']}")
        lines.append(f"  Steps: {result['steps']}")
        lines.append(f"  Population: {result['pop_initial']} → {result['pop_final']} "
                      f"(peak: {result['pop_peak']}, min: {result['pop_min']})")
        lines.append(f"  Trend: {result['trend']}")
        lines.append(f"  Final state (16x16 viewport):")
        for row in result["ascii"][:12]:  # Limit to 12 rows for readability
            lines.append(f"    {row}")
        if result["rule"] == "B3/S23":
            lines.append("  Note: Same engine as your AURA grid (256x256 at 10Hz).")
        lines.append("=" * max(len(lines[0]), 30))
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Station 5: Math Console
# ---------------------------------------------------------------------------

# SymPy whitelist — only these names are available in the sandbox
_SYMPY_SAFE_NAMES = {
    # Symbols
    "Symbol", "symbols", "Integer", "Rational", "Float",
    "pi", "E", "I", "oo", "zoo", "nan",
    # Algebra
    "expand", "factor", "simplify", "collect", "cancel",
    "apart", "together", "radsimp", "ratsimp",
    "solve", "solveset", "Eq",
    # Calculus
    "diff", "Derivative", "integrate", "Integral",
    "limit", "series", "summation", "Sum", "Product",
    # Trig
    "sin", "cos", "tan", "cot", "sec", "csc",
    "asin", "acos", "atan", "atan2",
    "sinh", "cosh", "tanh",
    # Functions
    "sqrt", "cbrt", "Abs", "sign",
    "log", "ln", "exp", "floor", "ceiling",
    "factorial", "binomial", "gamma",
    "gcd", "lcm", "Mod",
    # Linear algebra
    "Matrix", "det", "eye", "zeros", "ones",
    # Number theory
    "isprime", "nextprime", "prevprime",
    "factorint", "divisors", "totient",
    "fibonacci", "prime",
    # Printing
    "latex", "pretty", "pprint",
    # Misc
    "Piecewise", "Max", "Min", "N",
    "FiniteSet", "Interval", "Union",
    "true", "false",
}

# Compiled regex for banned patterns in math expressions
_BANNED_RE = re.compile(
    r"\b(?:import|exec|eval|open|compile|globals|locals|getattr|setattr|delattr"
    r"|vars|dir|type|input|print|subprocess|breakpoint|chr|ord|lambda"
    r"|classmethod|staticmethod|property|super|memoryview|bytearray|bytes)\b"
    r"|(?<![a-zA-Z])(?:os|sys)\."  # Negative lookbehind: avoid matching cos., chaos., etc.
    r"|__",
)


class MathStation(BaseStation):
    name = "Math Console"
    key = "math"
    description = "Solve equations, derivatives, integrals, factorization, number theory."

    _RE_SOLVE = re.compile(r"(?:solve|find.*roots?|zeros?.*of)", re.I)
    _RE_DIFF = re.compile(r"(?:differentiat|derivativ|d/d[xyztn]|diff)", re.I)
    _RE_INTEGRATE = re.compile(r"(?:integrat|antiderivativ|∫)", re.I)
    _RE_FACTOR = re.compile(r"(?:factor(?:iz|is)|prime factor)", re.I)
    _RE_SIMPLIFY = re.compile(r"(?:simplif|reduc|expand)", re.I)
    _RE_SERIES = re.compile(r"(?:series|taylor|maclaurin)", re.I)
    _RE_MATRIX = re.compile(r"(?:matrix|determinant|eigenvalue|eigenvector)", re.I)
    _RE_PRIME = re.compile(r"(?:is.*prime|prime.*test|primality)", re.I)

    _RE_EXPR = re.compile(
        r"['\"]([^'\"]+)['\"]"  # Quoted expression
        r"|(?:calculate|compute|evaluate|solve|of)\s+(.+?)(?:\.|$|,|\s+(?:for|with|where))"
        r"|(?:=\s*)(.+?)(?:\.|$)",
        re.I,
    )

    def _build_sandbox(self):
        """Build restricted namespace for SymPy evaluation."""
        try:
            import sympy
        except ImportError:
            return None

        ns = {"__builtins__": {}}
        for name in _SYMPY_SAFE_NAMES:
            obj = getattr(sympy, name, None)
            if obj is not None:
                ns[name] = obj

        # Pre-define common symbols
        for var in "xyztnkabcr":
            ns[var] = sympy.Symbol(var)

        # Common aliases
        ns["ln"] = sympy.log

        return ns

    def _extract_expression(self, narrative: str) -> str:
        """Extract mathematical expression from narrative text."""
        # Try quoted first
        match = re.search(r"['\"]([^'\"]{2,})['\"]", narrative)
        if match:
            return match.group(1).strip()

        # Try after keywords
        for kw in ["calculate", "compute", "evaluate", "solve", "simplify",
                    "differentiate", "integrate", "factor"]:
            match = re.search(rf"{kw}\s+(.+?)(?:\.|$|,|\s+for\b)", narrative, re.I)
            if match:
                expr = match.group(1).strip()
                # Remove trailing natural language
                expr = re.sub(r"\s+(and|then|to|from|the|is|are)\b.*$", "", expr)
                return expr

        # Try anything that looks mathematical
        match = re.search(r"([\w\d\^\*\+\-/\(\)\.]+\s*[=<>]\s*[\w\d\^\*\+\-/\(\)\.]+)", narrative)
        if match:
            return match.group(1).strip()

        match = re.search(r"([xyztn]\s*[\*\^\+\-]\s*[\d\w\^\*\+\-/\(\)\.]+)", narrative)
        if match:
            return match.group(1).strip()

        return ""

    def parse(self, narrative: str) -> Optional[dict]:
        expr_str = self._extract_expression(narrative)
        if not expr_str:
            return None

        # Clean up common notations
        expr_str = expr_str.replace("^", "**").replace("×", "*").replace("÷", "/")

        # Determine operation type
        if self._RE_SOLVE.search(narrative):
            var_match = re.search(r"for\s+([xyztnkabc])", narrative, re.I)
            var = var_match.group(1) if var_match else "x"
            return {"type": "solve", "expr": expr_str, "variable": var}

        if self._RE_DIFF.search(narrative):
            var_match = re.search(r"(?:with respect to|wrt|d/d)\s*([xyztn])", narrative, re.I)
            var = var_match.group(1) if var_match else "x"
            order_match = re.search(r"(\d+)(?:st|nd|rd|th)\s*derivative", narrative, re.I)
            order = int(order_match.group(1)) if order_match else 1
            return {"type": "diff", "expr": expr_str, "variable": var, "order": min(order, 10)}

        if self._RE_INTEGRATE.search(narrative):
            var_match = re.search(r"(?:with respect to|wrt|d)\s*([xyztn])", narrative, re.I)
            var = var_match.group(1) if var_match else "x"
            bounds = re.findall(r"from\s+(\d+(?:\.\d+)?)\s+to\s+(\d+(?:\.\d+)?)", narrative, re.I)
            lower = float(bounds[0][0]) if bounds else None
            upper = float(bounds[0][1]) if bounds else None
            return {"type": "integrate", "expr": expr_str, "variable": var,
                    "lower": lower, "upper": upper}

        if self._RE_SERIES.search(narrative):
            var = "x"
            point_match = re.search(r"(?:around|about|at)\s+(\d+(?:\.\d+)?)", narrative, re.I)
            point = float(point_match.group(1)) if point_match else 0
            order_match = re.search(r"order\s+(\d+)|(\d+)\s*terms", narrative, re.I)
            order = int(order_match.group(1) or order_match.group(2)) if order_match else 6
            return {"type": "series", "expr": expr_str, "variable": var,
                    "point": point, "order": min(order, 20)}

        if self._RE_PRIME.search(narrative):
            num_match = re.search(r"(\d+)", narrative)
            if num_match:
                return {"type": "prime_test", "n": int(num_match.group(1))}

        if self._RE_FACTOR.search(narrative):
            num_match = re.search(r"(\d{2,})", narrative)
            if num_match:
                return {"type": "factorint", "n": int(num_match.group(1))}
            return {"type": "factor_expr", "expr": expr_str}

        if self._RE_SIMPLIFY.search(narrative):
            return {"type": "simplify", "expr": expr_str}

        # Default: evaluate
        return {"type": "eval", "expr": expr_str}

    def simulate(self, params: dict) -> dict:
        ns = self._build_sandbox()
        if ns is None:
            return {"error": "SymPy not available on this system"}

        import sympy

        expr_str = params.get("expr", "")

        # Safety check
        if len(expr_str) > 500:
            return {"error": "Expression too long (max 500 characters)"}

        ban_match = _BANNED_RE.search(expr_str)
        if ban_match:
            return {"error": f"Forbidden pattern in expression: {ban_match.group()}"}

        sim_type = params["type"]

        try:
            if sim_type == "prime_test":
                n = params["n"]
                if n > 10 ** 18:
                    return {"error": "Number too large for primality test (max 10^18)"}
                is_p = sympy.isprime(n)
                return {"type": "prime_test", "n": n, "is_prime": is_p}

            if sim_type == "factorint":
                n = params["n"]
                if n > 10 ** 18:
                    return {"error": "Number too large for factorization (max 10^18)"}
                factors = sympy.factorint(n)
                return {"type": "factorint", "n": n,
                        "factors": {str(k): v for k, v in factors.items()}}

            # Parse expression safely via sympy parser with restricted namespaces
            from sympy.parsing.sympy_parser import (
                parse_expr,
                standard_transformations,
                implicit_multiplication_application,
                convert_xor,
            )
            _SAFE_TRANSFORMS = standard_transformations + (
                implicit_multiplication_application,
                convert_xor,
            )
            # Explicit global_dict with no builtins — prevents parse_expr
            # from populating it with 'from sympy import *'
            safe_global = {"__builtins__": {}}
            expr = parse_expr(
                expr_str,
                local_dict=ns,
                global_dict=safe_global,
                transformations=_SAFE_TRANSFORMS,
            )

            if sim_type == "solve":
                var = ns.get(params.get("variable", "x"), ns["x"])
                solutions = sympy.solve(expr, var)
                return {
                    "type": "solve",
                    "expr": str(expr),
                    "variable": str(var),
                    "solutions": [str(s) for s in solutions[:10]],
                    "n_solutions": len(solutions),
                    "latex": sympy.latex(expr),
                }

            if sim_type == "diff":
                var = ns.get(params.get("variable", "x"), ns["x"])
                order = params.get("order", 1)
                result = sympy.diff(expr, var, order)
                return {
                    "type": "diff",
                    "expr": str(expr),
                    "variable": str(var),
                    "order": order,
                    "result": str(result),
                    "simplified": str(sympy.simplify(result)),
                    "latex": sympy.latex(result),
                }

            if sim_type == "integrate":
                var = ns.get(params.get("variable", "x"), ns["x"])
                lower = params.get("lower")
                upper = params.get("upper")
                if lower is not None and upper is not None:
                    result = sympy.integrate(expr, (var, lower, upper))
                    return {
                        "type": "definite_integral",
                        "expr": str(expr),
                        "bounds": f"[{lower}, {upper}]",
                        "result": str(result),
                        "numeric": str(result.evalf()) if hasattr(result, "evalf") else str(result),
                        "latex": sympy.latex(result),
                    }
                else:
                    result = sympy.integrate(expr, var)
                    return {
                        "type": "indefinite_integral",
                        "expr": str(expr),
                        "result": f"{result} + C",
                        "latex": sympy.latex(result) + " + C",
                    }

            if sim_type == "series":
                var = ns.get(params.get("variable", "x"), ns["x"])
                point = params.get("point", 0)
                order = params.get("order", 6)
                result = sympy.series(expr, var, point, order)
                return {
                    "type": "series",
                    "expr": str(expr),
                    "point": point,
                    "order": order,
                    "result": str(result),
                    "latex": sympy.latex(result),
                }

            if sim_type == "factor_expr":
                result = sympy.factor(expr)
                return {
                    "type": "factor_expr",
                    "expr": str(expr),
                    "result": str(result),
                    "latex": sympy.latex(result),
                }

            if sim_type == "simplify":
                result = sympy.simplify(expr)
                return {
                    "type": "simplify",
                    "expr": str(expr),
                    "result": str(result),
                    "latex": sympy.latex(result),
                }

            # Default: evaluate
            result = expr
            numeric = None
            if hasattr(result, "evalf"):
                try:
                    numeric = str(result.evalf())
                except Exception:
                    pass
            return {
                "type": "eval",
                "expr": str(expr),
                "result": str(result),
                "numeric": numeric,
            }

        except Exception as e:
            return {"error": f"Math error: {e}"}

    def narrate(self, params: dict, result: dict) -> str:
        if "error" in result:
            return f"=== MATH CONSOLE ===\n  Error: {result['error']}\n{'=' * 20}"

        t = result["type"]
        lines = [f"=== MATH CONSOLE: {t.replace('_', ' ').title()} ==="]

        if t == "solve":
            lines.append(f"  Equation: {result['expr']} = 0")
            lines.append(f"  Variable: {result['variable']}")
            if result["solutions"]:
                for s in result["solutions"]:
                    lines.append(f"    {result['variable']} = {s}")
                lines.append(f"  ({result['n_solutions']} solution(s))")
            else:
                lines.append("  No solutions found.")

        elif t == "diff":
            lines.append(f"  d{'²' if result['order'] == 2 else '³' if result['order'] == 3 else ''}/d{result['variable']}{'²' if result['order'] == 2 else '³' if result['order'] == 3 else ''} [{result['expr']}]")
            lines.append(f"  = {result['result']}")
            if result.get("simplified") and result["simplified"] != result["result"]:
                lines.append(f"  Simplified: {result['simplified']}")

        elif t in ("definite_integral", "indefinite_integral"):
            lines.append(f"  ∫ {result['expr']} d{params.get('variable', 'x')}")
            if t == "definite_integral":
                lines.append(f"  Bounds: {result['bounds']}")
                lines.append(f"  = {result['result']}")
                if result.get("numeric"):
                    lines.append(f"  ≈ {result['numeric']}")
            else:
                lines.append(f"  = {result['result']}")

        elif t == "series":
            lines.append(f"  f({params.get('variable', 'x')}) = {result['expr']}")
            lines.append(f"  Taylor series around {result['point']}, order {result['order']}:")
            lines.append(f"  = {result['result']}")

        elif t == "prime_test":
            lines.append(f"  n = {result['n']}")
            lines.append(f"  Is prime: {'YES' if result['is_prime'] else 'NO'}")

        elif t == "factorint":
            lines.append(f"  n = {result['n']}")
            factors_str = " × ".join(f"{p}^{e}" if e > 1 else p
                                     for p, e in result["factors"].items())
            lines.append(f"  = {factors_str}")

        elif t == "factor_expr":
            lines.append(f"  Input: {result['expr']}")
            lines.append(f"  Factored: {result['result']}")

        elif t == "simplify":
            lines.append(f"  Input: {result['expr']}")
            lines.append(f"  Simplified: {result['result']}")

        elif t == "eval":
            lines.append(f"  Expression: {result['expr']}")
            lines.append(f"  Result: {result['result']}")
            if result.get("numeric") and result["numeric"] != result["result"]:
                lines.append(f"  Numeric: ≈ {result['numeric']}")

        lines.append("=" * max(len(lines[0]), 20))
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Station 6: Electronics Workbench
# ---------------------------------------------------------------------------

class ElectronicsStation(BaseStation):
    name = "Electronics Workbench"
    key = "electronics"
    description = "Ohm's law, voltage dividers, RC/RL/RLC circuits, power calculations."

    _RE_OHM = re.compile(r"(?:ohm|resist(?:or|ance)|voltage|current|V\s*=\s*I\s*R)", re.I)
    _RE_DIVIDER = re.compile(r"(?:voltage divider|divider|potential divider)", re.I)
    _RE_RC = re.compile(r"\bRC\b|(?:capacitor.*charg|resistor.*capacitor|time constant)", re.I)
    _RE_RL = re.compile(r"\bRL\b|(?:inductor.*resistor|resistor.*inductor)", re.I)
    _RE_RLC = re.compile(r"\bRLC\b|(?:resonan|damp|oscillat.*circuit)", re.I)
    _RE_POWER = re.compile(r"(?:power|watt|dissipat)", re.I)
    _RE_SERIES = re.compile(r"(?:series.*resistor|resistor.*series)", re.I)
    _RE_PARALLEL = re.compile(r"(?:parallel.*resistor|resistor.*parallel)", re.I)

    # Map labels to their expected unit keywords
    _LABEL_UNITS = {
        "V": r"(?:volt|V\b)",
        "I": r"(?:amp|A\b)",
        "R": r"(?:ohm|Ω)",
        "C": r"(?:farad|F\b)",
        "L": r"(?:henry|H\b)",
    }

    def _extract_value(self, text: str, label: str) -> Optional[float]:
        """Extract a labeled value with SI prefix support."""
        prefixes = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "μ": 1e-6,
                     "m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9}

        # Pattern 1: Label=value (e.g., "R=1000", "V = 12")
        pat1 = rf"{label}\s*[:=]\s*(\d+(?:\.\d+)?)\s*([pnuμmkKMG])?"
        match = re.search(pat1, text, re.I)
        if match:
            val = float(match.group(1))
            prefix = match.group(2)
            if prefix and prefix in prefixes:
                val *= prefixes[prefix]
            return val

        # Pattern 2: value + unit (label-specific units only)
        unit_pat = self._LABEL_UNITS.get(label, "")
        if unit_pat:
            pat2 = rf"(\d+(?:\.\d+)?)\s*([pnuμmkKMG])?\s*{unit_pat}"
            match = re.search(pat2, text, re.I)
            if match:
                val = float(match.group(1))
                prefix = match.group(2)
                if prefix and prefix in prefixes:
                    val *= prefixes[prefix]
                return val

        return None

    def parse(self, narrative: str) -> Optional[dict]:
        text = narrative

        if self._RE_RLC.search(text):
            R = self._extract_value(text, "R") or 100.0
            L = self._extract_value(text, "L") or 0.01
            C = self._extract_value(text, "C") or 1e-6
            V0 = self._extract_value(text, "V") or 5.0
            return {
                "type": "rlc",
                "R": max(0.001, min(1e9, R)),
                "L": max(1e-9, min(100, L)),
                "C": max(1e-12, min(1, C)),
                "V0": max(0, min(1e6, V0)),
            }

        if self._RE_RC.search(text):
            R = self._extract_value(text, "R") or 1000.0
            C = self._extract_value(text, "C") or 100e-6
            V0 = self._extract_value(text, "V") or 5.0
            return {
                "type": "rc",
                "R": max(0.001, min(1e9, R)),
                "C": max(1e-12, min(1, C)),
                "V0": max(0, min(1e6, V0)),
            }

        if self._RE_RL.search(text):
            R = self._extract_value(text, "R") or 100.0
            L = self._extract_value(text, "L") or 0.01
            V0 = self._extract_value(text, "V") or 5.0
            return {
                "type": "rl",
                "R": max(0.001, min(1e9, R)),
                "L": max(1e-9, min(100, L)),
                "V0": max(0, min(1e6, V0)),
            }

        if self._RE_DIVIDER.search(text):
            numbers = re.findall(r"(\d+(?:\.\d+)?)\s*([kKMG])?", text)
            prefixes = {"k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9}
            vals = []
            for num, prefix in numbers:
                v = float(num)
                if prefix and prefix in prefixes:
                    v *= prefixes[prefix]
                vals.append(v)
            R1 = vals[0] if len(vals) > 0 else 1000.0
            R2 = vals[1] if len(vals) > 1 else 2000.0
            Vin = vals[2] if len(vals) > 2 else 5.0
            return {
                "type": "divider",
                "R1": max(0.001, R1),
                "R2": max(0.001, R2),
                "Vin": max(0, Vin),
            }

        if self._RE_POWER.search(text):
            V = self._extract_value(text, "V")
            I = self._extract_value(text, "I")
            R = self._extract_value(text, "R")
            if V is not None or I is not None or R is not None:
                return {
                    "type": "power",
                    "V": V,
                    "I": I,
                    "R": R,
                }

        if self._RE_PARALLEL.search(text):
            numbers = re.findall(r"(\d+(?:\.\d+)?)\s*([kKMG])?\s*(?:ohm|Ω)?", text, re.I)
            prefixes = {"k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9}
            vals = []
            for num, prefix in numbers:
                v = float(num)
                if prefix and prefix in prefixes:
                    v *= prefixes[prefix]
                vals.append(v)
            if len(vals) >= 2:
                return {"type": "parallel", "resistors": vals}

        if self._RE_SERIES.search(text):
            numbers = re.findall(r"(\d+(?:\.\d+)?)\s*([kKMG])?\s*(?:ohm|Ω)?", text, re.I)
            prefixes = {"k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9}
            vals = []
            for num, prefix in numbers:
                v = float(num)
                if prefix and prefix in prefixes:
                    v *= prefixes[prefix]
                vals.append(v)
            if len(vals) >= 2:
                return {"type": "series", "resistors": vals}

        if self._RE_OHM.search(text):
            V = self._extract_value(text, "V")
            I = self._extract_value(text, "I")
            R = self._extract_value(text, "R")
            if sum(x is not None for x in [V, I, R]) >= 2:
                return {"type": "ohm", "V": V, "I": I, "R": R}
            # Need at least 2 values
            return None

        return None

    def simulate(self, params: dict) -> dict:
        t = params["type"]

        if t == "ohm":
            V, I, R = params.get("V"), params.get("I"), params.get("R")
            if V is not None and I is not None:
                R = V / I if I != 0 else float("inf")
                return {"type": "ohm", "V": V, "I": I, "R": round(R, 6), "solved_for": "R"}
            elif V is not None and R is not None:
                I = V / R if R != 0 else float("inf")
                return {"type": "ohm", "V": V, "I": round(I, 6), "R": R, "solved_for": "I"}
            elif I is not None and R is not None:
                V = I * R
                return {"type": "ohm", "V": round(V, 6), "I": I, "R": R, "solved_for": "V"}
            return {"error": "Need at least 2 of V, I, R"}

        if t == "divider":
            R1, R2, Vin = params["R1"], params["R2"], params["Vin"]
            Vout = Vin * R2 / (R1 + R2)
            I = Vin / (R1 + R2)
            return {
                "type": "divider",
                "R1": R1, "R2": R2, "Vin": Vin,
                "Vout": round(Vout, 6),
                "current": round(I, 9),
                "ratio": round(R2 / (R1 + R2), 4),
            }

        if t == "rc":
            R, C, V0 = params["R"], params["C"], params["V0"]
            tau = R * C
            points = []
            for mult in [0, 0.5, 1.0, 2.0, 3.0, 5.0]:
                t_val = tau * mult
                v_val = V0 * (1 - math.exp(-t_val / tau)) if tau > 0 else V0
                pct = v_val / V0 * 100 if V0 > 0 else 0
                points.append({
                    "t": f"{t_val:.6g}",
                    "V": f"{v_val:.4g}",
                    "pct": f"{pct:.1f}",
                    "tau_mult": mult,
                })
            return {
                "type": "rc",
                "R": R, "C": C, "V0": V0,
                "tau": tau,
                "points": points,
                "t_63pct": tau,
                "t_95pct": 3 * tau,
                "t_99pct": 5 * tau,
            }

        if t == "rl":
            R, L, V0 = params["R"], params["L"], params["V0"]
            tau = L / R if R > 0 else float("inf")
            I_max = V0 / R if R > 0 else float("inf")
            points = []
            for mult in [0, 0.5, 1.0, 2.0, 3.0, 5.0]:
                t_val = tau * mult
                i_val = I_max * (1 - math.exp(-t_val / tau)) if tau > 0 and tau != float("inf") else 0
                pct = i_val / I_max * 100 if I_max > 0 and I_max != float("inf") else 0
                points.append({
                    "t": f"{t_val:.6g}",
                    "I": f"{i_val:.6g}",
                    "pct": f"{pct:.1f}",
                    "tau_mult": mult,
                })
            return {
                "type": "rl",
                "R": R, "L": L, "V0": V0,
                "tau": tau,
                "I_max": I_max,
                "points": points,
            }

        if t == "rlc":
            R, L, C, V0 = params["R"], params["L"], params["C"], params["V0"]
            alpha = R / (2 * L)
            omega0 = 1 / math.sqrt(L * C)
            f0 = omega0 / (2 * math.pi)
            Q = omega0 * L / R if R > 0 else float("inf")

            discriminant = alpha ** 2 - omega0 ** 2
            if discriminant > 0:
                damping = "overdamped"
                s1 = -alpha + math.sqrt(discriminant)
                s2 = -alpha - math.sqrt(discriminant)
                info = f"s1={s1:.4g}, s2={s2:.4g}"
            elif abs(discriminant) < 1e-10:
                damping = "critically_damped"
                info = f"s = {-alpha:.4g} (repeated)"
            else:
                damping = "underdamped"
                omega_d = math.sqrt(abs(discriminant))
                f_d = omega_d / (2 * math.pi)
                info = f"ω_d={omega_d:.4g} rad/s, f_d={f_d:.4g} Hz"

            return {
                "type": "rlc",
                "R": R, "L": L, "C": C, "V0": V0,
                "alpha": round(alpha, 4),
                "omega0": round(omega0, 4),
                "f0": round(f0, 4),
                "Q": round(Q, 4),
                "damping": damping,
                "info": info,
            }

        if t == "power":
            V, I, R = params.get("V"), params.get("I"), params.get("R")
            if V is not None and I is not None:
                P = V * I
            elif V is not None and R is not None:
                P = V ** 2 / R if R != 0 else float("inf")
                I = V / R if R != 0 else float("inf")
            elif I is not None and R is not None:
                P = I ** 2 * R
                V = I * R
            else:
                return {"error": "Need at least 2 of V, I, R to calculate power"}
            return {"type": "power", "V": V, "I": I, "R": R, "P": round(P, 6)}

        if t == "series":
            resistors = params["resistors"]
            total = sum(resistors)
            return {"type": "series", "resistors": resistors, "total": round(total, 6)}

        if t == "parallel":
            resistors = params["resistors"]
            if any(r == 0 for r in resistors):
                total = 0.0  # Zero-ohm resistor short-circuits the parallel combination
            else:
                inv_sum = sum(1.0 / r for r in resistors)
                total = 1.0 / inv_sum if inv_sum > 0 else float("inf")
            return {"type": "parallel", "resistors": resistors, "total": round(total, 6)}

        return {"error": f"Unknown electronics type: {t}"}

    def narrate(self, params: dict, result: dict) -> str:
        if "error" in result:
            return f"=== ELECTRONICS WORKBENCH ===\n  Error: {result['error']}\n{'=' * 28}"

        t = result["type"]
        lines = [f"=== ELECTRONICS WORKBENCH: {t.upper()} ==="]

        if t == "ohm":
            lines.append(f"  V = {result['V']} V, I = {result['I']} A, R = {result['R']} Ω")
            lines.append(f"  Solved for: {result['solved_for']}")

        elif t == "divider":
            lines.append(f"  R1 = {result['R1']} Ω, R2 = {result['R2']} Ω")
            lines.append(f"  Vin = {result['Vin']} V → Vout = {result['Vout']} V")
            lines.append(f"  Ratio: {result['ratio']} ({result['ratio'] * 100:.1f}%)")
            lines.append(f"  Current: {result['current']} A")

        elif t == "rc":
            lines.append(f"  R = {result['R']} Ω, C = {result['C']} F, V0 = {result['V0']} V")
            lines.append(f"  Time constant τ = RC = {result['tau']:.6g} s")
            lines.append("  Charging curve:")
            for pt in result["points"]:
                lines.append(f"    t={pt['t']}s → V={pt['V']}V ({pt['pct']}%) [{pt['tau_mult']}τ]")
            lines.append(f"  Fully charged (~99%) in {result['t_99pct']:.6g}s (5τ)")

        elif t == "rl":
            lines.append(f"  R = {result['R']} Ω, L = {result['L']} H, V0 = {result['V0']} V")
            lines.append(f"  Time constant τ = L/R = {result['tau']:.6g} s")
            lines.append(f"  Steady-state current: I_max = {result['I_max']:.6g} A")
            lines.append("  Current rise:")
            for pt in result["points"]:
                lines.append(f"    t={pt['t']}s → I={pt['I']}A ({pt['pct']}%) [{pt['tau_mult']}τ]")

        elif t == "rlc":
            lines.append(f"  R = {result['R']} Ω, L = {result['L']} H, C = {result['C']} F")
            lines.append(f"  Natural frequency: ω₀ = {result['omega0']} rad/s (f₀ = {result['f0']} Hz)")
            lines.append(f"  Damping: α = {result['alpha']}")
            lines.append(f"  Quality factor: Q = {result['Q']}")
            lines.append(f"  Response: {result['damping'].replace('_', ' ').upper()}")
            lines.append(f"  {result['info']}")

        elif t == "power":
            lines.append(f"  V = {result.get('V', '?')} V, I = {result.get('I', '?')} A, "
                          f"R = {result.get('R', '?')} Ω")
            lines.append(f"  Power: P = {result['P']} W")

        elif t in ("series", "parallel"):
            r_str = " + ".join(f"{r}Ω" for r in result["resistors"])
            lines.append(f"  {t.title()}: {r_str}")
            lines.append(f"  Total resistance: {result['total']} Ω")

        lines.append("=" * max(len(lines[0]), 28))
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# ExperimentLab — Registry, Auto-detect, Run, DB Persistence
# ---------------------------------------------------------------------------

class ExperimentLab:
    """Universal experiment framework. One interface, six backends."""

    def __init__(self):
        self._stations: Dict[str, BaseStation] = {}
        self._db_initialized = False
        self._db_lock = threading.Lock()
        self._init_stations()

    def _init_stations(self):
        for cls in [PhysicsStation, ChemistryStation, AstronomyStation,
                    GoLStation, ElectronicsStation, MathStation]:
            station = cls()
            self._stations[station.key] = station

    def _get_conn(self) -> sqlite3.Connection:
        """Get a fresh per-call DB connection (thread-safe)."""
        if not self._db_initialized:
            with self._db_lock:
                if not self._db_initialized:
                    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                    conn = sqlite3.connect(str(DB_PATH), timeout=10)
                    _init_db(conn)
                    _migrate_hypothesis_column(conn)
                    self._db_initialized = True
                    return conn
        return sqlite3.connect(str(DB_PATH), timeout=10)

    def describe_stations(self) -> str:
        """Return formatted list of all stations."""
        lines = []
        for station in self._stations.values():
            lines.append(station.describe())
        return "\n".join(lines)

    def detect_station(self, narrative: str) -> Optional[Tuple[str, dict]]:
        """Try each station's parse(). Return (key, params) or None."""
        for key, station in self._stations.items():
            try:
                params = station.parse(narrative)
                if params is not None:
                    return (key, params)
            except Exception as e:
                LOG.debug("Station %s parse error: %s", key, e)
        return None

    def _run_with_timeout(self, fn, args, timeout_s=SIMULATION_TIMEOUT_S):
        """Run fn(*args) in a thread with timeout."""
        result_box = [None]
        error_box = [None]

        def worker():
            try:
                result_box[0] = fn(*args)
            except Exception as e:
                error_box[0] = str(e)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(timeout=timeout_s)
        if t.is_alive():
            return None, f"Simulation timed out (>{timeout_s}s)"
        if error_box[0]:
            return None, error_box[0]
        return result_box[0], None

    def _check_and_increment_budget(self) -> bool:
        """Atomically check and increment daily experiment budget. Returns True if allowed."""
        try:
            conn = self._get_conn()
            try:
                today = datetime.now().strftime("%Y-%m-%d")
                # Ensure row exists
                conn.execute(
                    "INSERT INTO experiment_budget (date, count) VALUES (?, 0) "
                    "ON CONFLICT(date) DO NOTHING",
                    (today,),
                )
                # Atomic check-and-increment in a single UPDATE
                cursor = conn.execute(
                    "UPDATE experiment_budget SET count = count + 1 "
                    "WHERE date = ? AND count < ?",
                    (today, MAX_DAILY_EXPERIMENTS),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()
        except Exception:
            return True

    def run_experiment(self, station_key: str, params: dict,
                       source: str = "sanctum",
                       hypothesis_id: str = None) -> str:
        """Run a simulation and return narrated result."""
        if station_key not in self._stations:
            return f"[LAB ERROR] Unknown station: {station_key}"

        if not self._check_and_increment_budget():
            return "[LAB] Daily experiment budget reached (20/day). Try again tomorrow."

        station = self._stations[station_key]
        start = time.monotonic()

        # Run with timeout
        result, error = self._run_with_timeout(station.simulate, (params,))
        duration_ms = (time.monotonic() - start) * 1000

        if error:
            narration = f"=== {station.name.upper()} ===\n  Simulation error: {error}\n{'=' * 30}"
            self._log_experiment(station_key, params, {}, narration, source,
                                 duration_ms, error, hypothesis_id)
            return narration

        # Narrate
        try:
            narration = station.narrate(params, result)
        except Exception as e:
            narration = f"=== {station.name.upper()} ===\n  Narration error: {e}\n{'=' * 30}"

        # Truncate if too long
        if len(narration) > MAX_OUTPUT_CHARS:
            narration = narration[:MAX_OUTPUT_CHARS - 40] + "\n... [truncated, full result in DB]"

        # Log to DB
        self._log_experiment(station_key, params, result, narration, source,
                             duration_ms, hypothesis_id=hypothesis_id)

        return narration

    def run_from_description(self, description: str) -> str:
        """For autonomous research: detect station + run from text description."""
        detection = self.detect_station(description)
        if detection is None:
            return "[LAB] No matching experiment station for this description."
        station_key, params = detection
        return self.run_experiment(station_key, params, source="research")

    @staticmethod
    def _safe_json(obj: Any) -> str:
        """JSON-serialize with inf/nan replaced by strings."""
        def _fix(o):
            if isinstance(o, float):
                if math.isinf(o) or math.isnan(o):
                    return str(o)
            return o
        return json.dumps(obj, default=str).replace("Infinity", '"Infinity"').replace("NaN", '"NaN"')

    def _log_experiment(self, station: str, params: dict, result: dict,
                        narration: str, source: str, duration_ms: float,
                        error: str = None, hypothesis_id: str = None):
        """Persist experiment to DB."""
        try:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT INTO experiments (ts, station, params_json, result_json, "
                    "narration, source, duration_ms, error, hypothesis_id) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        time.time(), station,
                        self._safe_json(params),
                        self._safe_json(result)[:5000],
                        narration[:MAX_OUTPUT_CHARS],
                        source, duration_ms, error, hypothesis_id,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            LOG.debug("Experiment log failed: %s", e)

    def get_recent_experiments(self, n: int = 5) -> List[dict]:
        """Get last N experiments."""
        try:
            conn = self._get_conn()
            try:
                rows = conn.execute(
                    "SELECT ts, station, narration, source, duration_ms "
                    "FROM experiments ORDER BY id DESC LIMIT ?", (n,)
                ).fetchall()
                return [
                    {
                        "ts": datetime.fromtimestamp(r[0]).strftime("%H:%M"),
                        "station": r[1],
                        "narration": r[2][:100],
                        "source": r[3],
                        "duration_ms": r[4],
                    }
                    for r in rows
                ]
            finally:
                conn.close()
        except Exception:
            return []

    def get_stats(self) -> dict:
        """Get experiment statistics."""
        try:
            conn = self._get_conn()
            try:
                total = conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
                today = datetime.now().strftime("%Y-%m-%d")
                today_row = conn.execute(
                    "SELECT count FROM experiment_budget WHERE date=?", (today,)
                ).fetchone()
                today_count = today_row[0] if today_row else 0
                popular = conn.execute(
                    "SELECT station, COUNT(*) as c FROM experiments GROUP BY station ORDER BY c DESC LIMIT 1"
                ).fetchone()
                return {
                    "total": total,
                    "today": today_count,
                    "most_used": popular[0] if popular else None,
                }
            finally:
                conn.close()
        except Exception:
            return {"total": 0, "today": 0, "most_used": None}

    def get_last_experiment_id(self) -> Optional[int]:
        """Get the ID of the most recent experiment."""
        try:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT id FROM experiments ORDER BY id DESC LIMIT 1"
                ).fetchone()
                return row[0] if row else None
            finally:
                conn.close()
        except Exception:
            return None

    def get_experiment_result(self, experiment_id: int) -> Optional[dict]:
        """Get full experiment result by ID."""
        try:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT id, ts, station, params_json, result_json, "
                    "narration, source, duration_ms, error, hypothesis_id "
                    "FROM experiments WHERE id = ?",
                    (experiment_id,),
                ).fetchone()
                if not row:
                    return None
                return {
                    "id": row[0], "ts": row[1], "station": row[2],
                    "params": row[3], "result": row[4],
                    "narration": row[5], "source": row[6],
                    "duration_ms": row[7], "error": row[8],
                    "hypothesis_id": row[9],
                }
            finally:
                conn.close()
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[ExperimentLab] = None
_instance_lock = threading.Lock()


def get_lab() -> ExperimentLab:
    """Get or create the singleton ExperimentLab (thread-safe)."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ExperimentLab()
    return _instance
