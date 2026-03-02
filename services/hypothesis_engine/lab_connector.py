"""
Hypothesis Engine — Lab Connector.

Bridge between hypotheses and the Experiment Lab.
Decides testability, translates hypotheses to experiment descriptions,
interprets results.
"""

import logging
import re
from typing import Dict, List, Optional

LOG = logging.getLogger("hypothesis_engine.lab")

# ── Domain → Station mapping ──

DOMAIN_TO_STATION: Dict[str, Optional[str]] = {
    "physics": "physics",
    "chemistry": "chemistry",
    "astronomy": "astronomy",
    "gol": "gol",
    "math": "math",
    "electronics": "electronics",
    # Internal domains have no station
    "self": None,
    "affect": None,
    "hardware": None,
    "world": None,
}

# ── Keywords that indicate experimental testability ──

_EXPERIMENT_KEYWORDS: Dict[str, List[str]] = {
    "physics": [
        "fall", "drop", "throw", "collide", "bounce", "pendulum",
        "projectile", "gravity", "friction", "force", "velocity",
        "acceleration", "mass", "weight", "momentum", "energy",
    ],
    "chemistry": [
        "react", "mix", "dissolve", "acid", "base", "pH",
        "neutralize", "oxidize", "compound", "molecule",
        "element", "solution", "concentration",
    ],
    "astronomy": [
        "orbit", "planet", "star", "gravity", "solar",
        "binary", "moon", "period", "escape velocity",
        "three body", "n-body", "stable orbit",
    ],
    "gol": [
        "pattern", "glider", "oscillator", "still life", "rule",
        "birth", "survival", "game of life", "cellular automaton",
        "conway", "emergence", "population", "evolution",
        "density", "grid",
    ],
    "math": [
        "equation", "solve", "derivative", "integral", "prime",
        "factor", "matrix", "polynomial", "roots", "calculate",
        " prove ", "sequence", "series", " limit ",
    ],
    "electronics": [
        "circuit", "resistor", "capacitor", "inductor",
        "voltage", "current", "ohm", "frequency",
        "impedance", "resonance", "filter", "RC", "RLC",
    ],
}

# ── Experiment description templates ──

_TEMPLATES: Dict[str, str] = {
    "physics": "Physics experiment: {pred}",
    "chemistry": "Chemistry experiment: Mix and observe: {pred}",
    "astronomy": "Simulate orbit: {pred}",
    "gol": "Run Game of Life: {pred}",
    "math": "Calculate: {pred}",
    "electronics": "Build circuit: {pred}",
}


class LabConnector:
    """Bridge between Hypothesis Engine and Experiment Lab."""

    def __init__(self):
        self._lab = None

    def _get_lab(self):
        """Lazy import of experiment lab singleton."""
        if self._lab is None:
            try:
                from services.experiment_lab import get_lab
                self._lab = get_lab()
            except ImportError:
                LOG.debug("Experiment lab not available")
        return self._lab

    def can_test_experimentally(self, hypothesis: dict) -> Optional[str]:
        """Check if a hypothesis can be tested via experiment.

        Returns station key (str) or None.
        Three detection paths:
        1. Domain maps directly to a station
        2. Keywords in hypothesis/prediction text match a station
        3. Explicit marker (test_method == 'experiment')
        """
        # Path 1: Direct domain mapping
        domain = hypothesis.get("domain", "")
        station = DOMAIN_TO_STATION.get(domain)
        if station:
            return station

        # Path 2: Keyword scan over hypothesis + prediction text
        text = (
            hypothesis.get("hypothesis", "") + " " +
            hypothesis.get("prediction", "")
        ).lower()
        for station_key, keywords in _EXPERIMENT_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                return station_key

        # Path 3: Explicit marker
        if hypothesis.get("test_method") == "experiment":
            return hypothesis.get("experiment_station")

        return None

    def hypothesis_to_experiment(self, hypothesis: dict) -> str:
        """Translate a hypothesis into a natural-language experiment description
        that the Experiment Lab can parse.
        """
        station = self.can_test_experimentally(hypothesis)
        pred = hypothesis.get("prediction", "")

        if station and station in _TEMPLATES:
            return _TEMPLATES[station].format(pred=pred[:300])
        return f"Test this prediction: {pred[:300]}"

    def run_experiment(self, hypothesis: dict) -> dict:
        """Run an experiment for a hypothesis.

        Returns: {success, experiment_id, station, narration, error}
        """
        lab = self._get_lab()
        if not lab:
            return {"success": False, "error": "Lab not available"}

        station = self.can_test_experimentally(hypothesis)
        if not station:
            return {"success": False, "error": "Not experimentally testable"}

        description = self.hypothesis_to_experiment(hypothesis)
        hypothesis_id = hypothesis.get("id")

        try:
            # Detect station params from description, then call run_experiment
            # directly with hypothesis_id for proper DB linkage
            detection = lab.detect_station(description)
            if detection is None:
                return {"success": False, "error": "Station could not parse description"}

            station_key, params = detection
            narration = lab.run_experiment(
                station_key, params,
                source="hypothesis",
                hypothesis_id=hypothesis_id,
            )

            # Check if it was a budget/error response
            if narration.startswith("[LAB"):
                return {"success": False, "error": narration}

            # Get experiment ID — query by hypothesis_id for precision
            exp_id = None
            if hasattr(lab, "get_last_experiment_id"):
                exp_id = lab.get_last_experiment_id()

            return {
                "success": True,
                "experiment_id": exp_id,
                "station": station,
                "narration": narration,
            }

        except Exception as e:
            LOG.error("Experiment failed for hypothesis %s: %s", hypothesis_id, e)
            return {"success": False, "error": str(e)}

    def interpret_result(self, hypothesis: dict, narration: str) -> str:
        """Interpret an experiment result as confirmation/refutation.

        Returns: 'confirmed' | 'refuted' | 'inconclusive'
        """
        narration_lower = narration.lower()

        # Explicit markers from station narrations
        if "[confirmed]" in narration_lower or "prediction confirmed" in narration_lower:
            return "confirmed"
        if "[refuted]" in narration_lower or "prediction refuted" in narration_lower:
            return "refuted"

        # Keyword heuristic
        confirm_words = ["as predicted", "matches", "consistent", "confirms",
                         "agrees with", "expected"]
        refute_words = ["unexpected", "contrary", "opposite", "failed",
                        "contradicts", "disagrees", "wrong"]

        confirm_score = sum(1 for w in confirm_words if w in narration_lower)
        refute_score = sum(1 for w in refute_words if w in narration_lower)

        if confirm_score > refute_score:
            return "confirmed"
        if refute_score > confirm_score:
            return "refuted"

        return "inconclusive"

    def get_experiment_result(self, experiment_id: int) -> Optional[dict]:
        """Fetch full experiment result from the Lab DB."""
        lab = self._get_lab()
        if not lab or not hasattr(lab, "get_experiment_result"):
            return None
        return lab.get_experiment_result(experiment_id)
