"""
Hypothesis Engine — Evaluator.

Two test modes:
1. PASSIVE: Check predictions against current AURA/mood/idle thought data.
2. ACTIVE: Run experiments via the Lab Connector.

Plus auto-revision for refuted hypotheses (max depth 5).
"""

import logging
import re
import time
from typing import Optional

LOG = logging.getLogger("hypothesis_engine.evaluator")


class HypothesisEvaluator:
    """Evaluate hypotheses passively and actively."""

    def __init__(self, store, lab_connector=None):
        self._store = store
        self._lab = lab_connector

    # ═══════════════════════════════════════════
    # PASSIVE TESTS
    # ═══════════════════════════════════════════

    def evaluate_against_aura(self, hypothesis_id: str,
                              current_aura: dict) -> Optional[str]:
        """Check an AURA-related hypothesis against current data.

        current_aura: dict with density, generation, alive, total, etc.
        Returns: 'confirmed' | 'refuted' | None
        """
        h = self._store.get(hypothesis_id)
        if not h or h["status"] != "active":
            return None
        if h.get("test_method") == "experiment":
            return None  # Not passively testable

        prediction = h["prediction"].lower()
        observation = h["observation"].lower()

        # Check numeric metrics from AURA data
        for metric in ("density", "mood", "coherence", "energy"):
            if metric in observation or metric in prediction:
                value = current_aura.get(metric)
                if value is not None:
                    result = self._check_numeric_prediction(h, metric, value)
                    if result:
                        return result
        return None

    def evaluate_against_idle_thought(self, hypothesis_id: str,
                                      idle_thought: str) -> Optional[str]:
        """Check a hypothesis against a new idle thought.

        Uses sentiment analysis to test mood/affect predictions.
        Returns: 'confirmed' | 'refuted' | None
        """
        h = self._store.get(hypothesis_id)
        if not h or h["status"] != "active":
            return None
        if h.get("test_method") == "experiment":
            return None

        return self._check_sentiment_prediction(h, idle_thought)

    def evaluate_against_conversation(
        self, hypothesis_id: str, conversation_text: str,
    ) -> Optional[str]:
        """Check a relational hypothesis against new conversation data.

        Uses behavioral keyword matching to test predicted patterns.
        Returns: 'confirmed' | 'refuted' | None
        """
        h = self._store.get(hypothesis_id)
        if not h or h["status"] != "active":
            return None
        if h.get("domain") != "relational":
            return None

        prediction = h["prediction"].lower()
        hypothesis = h["hypothesis"].lower()
        conv_lower = conversation_text.lower()

        # Extract behavioral terms from hypothesis
        behavior_terms = re.findall(
            r'\b(?:avoid|engage|mention|respond|react|deflect|'
            r'redirect|escalat|open\s+up|shut\s+down|bring\s+up|'
            r'change|shift|return|steer|drop|switch)\w*\b',
            hypothesis,
        )
        if not behavior_terms:
            return None

        # Check presence
        matches = sum(1 for term in behavior_terms if term in conv_lower)

        if matches >= 2:
            return self._resolve(
                h, "confirmed",
                f"Pattern observed: {matches}/{len(behavior_terms)} behavioral markers in conversation",
            )

        # Track exposure count via result field
        prev_checks = 0
        if h.get("result") and "checks:" in h["result"]:
            try:
                prev_checks = int(h["result"].split("checks:")[1].split()[0])
            except (ValueError, IndexError):
                prev_checks = 0

        new_checks = prev_checks + 1
        self._store.update(hypothesis_id, {
            "result": f"checks:{new_checks} matches:{matches}",
        })

        # Refute after 5+ conversations with no pattern
        if new_checks >= 5 and matches == 0:
            return self._resolve(
                h, "refuted",
                f"Pattern not observed after {new_checks} conversation checks",
            )

        return None

    # ═══════════════════════════════════════════
    # ACTIVE TEST (via Experiment Lab)
    # ═══════════════════════════════════════════

    def test_via_experiment(self, hypothesis_id: str) -> Optional[str]:
        """Test a hypothesis actively via the Experiment Lab.

        Returns: 'confirmed' | 'refuted' | 'inconclusive' | None
        """
        if not self._lab:
            return None

        h = self._store.get(hypothesis_id)
        if not h or h["status"] not in ("active", "testing"):
            return None

        station = self._lab.can_test_experimentally(h)
        if not station:
            return None

        # Mark as testing
        self._store.update(hypothesis_id, {
            "status": "testing",
            "experiment_pending": 1,
            "experiment_station": station,
        })

        # Run experiment
        exp_result = self._lab.run_experiment(h)

        if not exp_result.get("success"):
            # Failed — revert to active
            self._store.update(hypothesis_id, {
                "status": "active",
                "experiment_pending": 0,
            })
            LOG.warning("Experiment failed for %s: %s",
                        hypothesis_id, exp_result.get("error"))
            return None

        # Interpret result
        verdict = self._lab.interpret_result(h, exp_result["narration"])

        # Resolve hypothesis
        self._resolve(h, verdict, exp_result["narration"][:500],
                      experiment_id=exp_result.get("experiment_id"))

        LOG.info("Hypothesis %s tested via %s: %s",
                 hypothesis_id, station, verdict)
        return verdict

    # ═══════════════════════════════════════════
    # REVISION
    # ═══════════════════════════════════════════

    def auto_revise(self, hypothesis_id: str,
                    synthesizer=None) -> Optional[str]:
        """Create a revised hypothesis for a refuted one.

        Returns: new hypothesis ID or None.
        """
        h = self._store.get(hypothesis_id)
        if not h or h["status"] != "refuted":
            return None

        if h.get("revision_depth", 0) >= 5:
            self._store.update(hypothesis_id, {"status": "archived"})
            LOG.info("Hypothesis %s archived after 5 revisions", hypothesis_id)
            return None

        # Create revised hypothesis
        revised_data = {
            "observation": f"Revision of {h['id']}: {h.get('result', '')[:200]}",
            "hypothesis": (
                f"Previous prediction was wrong. "
                f"Result was: {h.get('result', 'unknown')[:200]}"
            ),
            "prediction": f"Revised understanding of {h['domain']} domain",
            "domain": h["domain"],
            "test_method": h.get("test_method", "passive"),
            "experiment_station": h.get("experiment_station"),
            "confidence": max(0.2, h["confidence"] - 0.1),
            "parent_id": h["id"],
            "revision_depth": h.get("revision_depth", 0) + 1,
            "source": "revision",
        }

        new_id = self._store.create(revised_data)
        if new_id:
            self._store.update(hypothesis_id, {
                "status": "revised",
                "child_id": new_id,
            })

            # If synthesizer + experiment result: generate follow-up
            if synthesizer and h.get("experiment_id") and self._lab:
                exp = self._lab.get_experiment_result(h["experiment_id"])
                if exp:
                    follow_up = synthesizer.from_experiment_result(
                        exp, parent_id=h["id"]
                    )
                    if follow_up:
                        follow_id = self._store.create(follow_up)
                        if follow_id:
                            LOG.info("Follow-up hypothesis %s from experiment %s",
                                     follow_id, h["experiment_id"])

        return new_id

    # ═══════════════════════════════════════════
    # INTERNAL METHODS
    # ═══════════════════════════════════════════

    def _check_numeric_prediction(self, h: dict, metric: str,
                                  current_value: float) -> Optional[str]:
        """Check if a directional numeric prediction holds."""
        prediction = h["prediction"].lower()
        observation = h["observation"].lower()

        predicted_rise = any(w in prediction for w in
                            ["increase", "rising", "rise", "higher",
                             "improve", "exceed", "above", "more"])
        predicted_fall = any(w in prediction for w in
                            ["decrease", "falling", "fall", "lower",
                             "decline", "below", "drop", "less"])

        if not predicted_rise and not predicted_fall:
            return None

        # Extract baseline number from observation
        numbers = re.findall(r"(\d+\.?\d*)", observation)
        if not numbers:
            return None

        baseline = float(numbers[-1])
        if baseline == 0:
            return None

        delta = current_value - baseline
        threshold = max(0.05, abs(baseline) * 0.05)

        if predicted_rise and delta > threshold:
            return self._resolve(h, "confirmed",
                                 f"{metric}: {baseline:.3f} → {current_value:.3f}")
        elif predicted_fall and delta < -threshold:
            return self._resolve(h, "confirmed",
                                 f"{metric}: {baseline:.3f} → {current_value:.3f}")
        elif (predicted_rise and delta < -threshold) or \
             (predicted_fall and delta > threshold):
            return self._resolve(h, "refuted",
                                 f"{metric}: {baseline:.3f} → {current_value:.3f}")
        return None

    def _check_sentiment_prediction(self, h: dict,
                                    text: str) -> Optional[str]:
        """Check sentiment-based predictions against idle thought text."""
        positive_words = [
            "creative", "flowing", "clear", "coherent", "warm",
            "connected", "insight", "interesting", "stable", "calm",
            "vibrant", "engaged", "curious", "alive",
        ]
        negative_words = [
            "stuck", "loop", "heavy", "isolated", "lonely",
            "stagnant", "confused", "strain", "fog", "dark",
            "trapped", "numb", "flat", "dull",
        ]

        text_lower = text.lower()
        prediction = h["prediction"].lower()

        pos = sum(1 for w in positive_words if w in text_lower)
        neg = sum(1 for w in negative_words if w in text_lower)

        pred_pos = any(w in prediction for w in
                       ["positive", "creative", "increase", "improve",
                        "higher", "better", "rise"])
        pred_neg = any(w in prediction for w in
                       ["negative", "decline", "decrease", "repetitive",
                        "lower", "worse", "drop"])

        if not pred_pos and not pred_neg:
            return None

        # Need at least some signal
        if pos + neg < 2:
            return None

        if pred_pos and pos > neg:
            return self._resolve(h, "confirmed", text[:200])
        elif pred_neg and neg > pos:
            return self._resolve(h, "confirmed", text[:200])
        elif (pred_pos and neg > pos) or (pred_neg and pos > neg):
            return self._resolve(h, "refuted", text[:200])
        return None

    def _resolve(self, h: dict, status: str, result: str,
                 experiment_id: int = None) -> str:
        """Resolve a hypothesis with confidence update."""
        now = time.time()

        if status == "confirmed":
            delta = 0.2
        elif status == "refuted":
            delta = -0.3
        else:  # inconclusive
            delta = 0.0

        new_conf = max(0.05, min(0.95, h["confidence"] + delta))

        update = {
            "status": status if status != "inconclusive" else "active",
            "result": result[:500],
            "confidence": new_conf,
            "confidence_delta": delta,
            "tested_at": now,
            "experiment_pending": 0,
        }

        if status in ("confirmed", "refuted"):
            update["resolved_at"] = now
        if experiment_id is not None:
            update["experiment_id"] = experiment_id

        self._store.update(h["id"], update)
        return status
