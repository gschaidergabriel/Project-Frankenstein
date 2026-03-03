"""
F.R.A.N.K. Hypothesis Engine — Main Service.

Hooks:
1. on_idle_thought()         — After idle thought generation
2. on_aura_update()          — After AURA state change
3. on_aura_pattern()         — After AURA Pattern Analyzer report (L1/L2)
4. periodic_analysis()       — Every ~25 min from workspace update
5. on_experiment_complete()   — When Experiment Lab produces result
6. request_experiment()       — Request active test via Lab

Context generators:
- get_context_for_idle_thought()  — Brief status for IT prompt
- get_context_for_sanctum_lab()   — Testable hypotheses for Lab location
- get_context_for_research()      — For autonomous research planning
"""

import logging
import time
from typing import Dict, List, Optional

LOG = logging.getLogger("hypothesis_engine")

# ── Budgets ──
MAX_HYPOTHESES_PER_DAY = 30
MAX_EXPERIMENTS_PER_DAY = 10
MAX_ACTIVE_HYPOTHESES = 20


class HypothesisEngine:
    """Empirical cycle: Observe → Hypothesize → Predict → Test → Revise."""

    def __init__(self):
        from .store import HypothesisStore
        from .synthesis import HypothesisSynthesizer
        from .evaluator import HypothesisEvaluator
        from .lab_connector import LabConnector

        self.store = HypothesisStore()
        self.synthesizer = HypothesisSynthesizer()
        self.lab_connector = LabConnector()
        self.evaluator = HypothesisEvaluator(self.store, self.lab_connector)

        self._last_aura: Optional[dict] = None
        self._timeseries: Dict[str, List[float]] = {}
        self._timestamps: Dict[str, List[float]] = {}

        LOG.info("Hypothesis Engine initialized")

    # ═══════════════════════════════════════════
    # HOOK 1: Idle Thought
    # ═══════════════════════════════════════════

    def on_idle_thought(self, text: str, mood: float = 0.5) -> Optional[str]:
        """Process an idle thought for hypothesis generation.

        Called every 5th idle thought from consciousness daemon.
        Returns: summary string or None.
        """
        if not self._check_budget("created"):
            return None

        # Check active limit for self/affect domains
        self_count = self.store.count_active_by_domain("self")
        affect_count = self.store.count_active_by_domain("affect")
        if self_count + affect_count >= 5:
            # Only allow non-self/affect hypotheses
            h_data = self.synthesizer.from_idle_thought(text, mood)
            if h_data and h_data.get("domain") in ("self", "affect"):
                return None
        else:
            h_data = self.synthesizer.from_idle_thought(text, mood)

        if not h_data:
            return None

        h_id = self.store.create(h_data)
        if not h_id:
            return None

        self._increment_budget("created")
        LOG.info("New hypothesis %s from IT: %s", h_id, h_data["hypothesis"][:60])

        # Auto-experiment if testable AND budget allows
        if (h_data.get("test_method") == "experiment"
                and self._check_budget("tested")):
            self.request_experiment(h_id)

        # Passive test: check active hypotheses against this thought
        for active in self.store.get_by_status("active", limit=10):
            if active["id"] == h_id:
                continue
            if active.get("test_method") == "experiment":
                continue
            result = self.evaluator.evaluate_against_idle_thought(
                active["id"], text)
            if result:
                LOG.info("Hypothesis %s %s by IT", active["id"], result)
                if result == "refuted":
                    self.evaluator.auto_revise(active["id"], self.synthesizer)

        return f"H-{h_id}: {h_data['hypothesis'][:80]}"

    # ═══════════════════════════════════════════
    # HOOK 2: AURA Update
    # ═══════════════════════════════════════════

    def on_aura_update(self, aura_data: dict) -> Optional[str]:
        """Process AURA density shift.

        aura_data: {density, generation, alive, total}
        Called when density changes > 0.05.
        """
        if not self._check_budget("created"):
            return None

        # Synthesize new hypothesis from AURA shift
        if self._last_aura:
            h_data = self.synthesizer.from_aura_shift(self._last_aura, aura_data)
            if h_data:
                h_id = self.store.create(h_data)
                if h_id:
                    self._increment_budget("created")
                    LOG.info("New hypothesis %s from AURA shift", h_id)

        # Passive evaluation against current AURA data
        for h in self.store.get_by_status("active", limit=10):
            if h.get("test_method") == "experiment":
                continue
            result = self.evaluator.evaluate_against_aura(h["id"], aura_data)
            if result:
                LOG.info("Hypothesis %s %s by AURA", h["id"], result)
                if result == "refuted":
                    self.evaluator.auto_revise(h["id"], self.synthesizer)

        # Update timeseries buffer
        self._update_timeseries(aura_data)
        self._last_aura = aura_data
        return None

    # ═══════════════════════════════════════════
    # HOOK 3: AURA Pattern (L1/L2 reports)
    # ═══════════════════════════════════════════

    def on_aura_pattern(self, pattern_data: dict) -> Optional[str]:
        """Process AURA pattern analyzer report → GoL hypothesis.

        Called from consciousness daemon AURA queue after L1/L2 reports.
        """
        if not self._check_budget("created"):
            return None

        h_data = self.synthesizer.from_aura_pattern(pattern_data)
        if not h_data:
            return None

        h_id = self.store.create(h_data)
        if not h_id:
            return None

        self._increment_budget("created")
        LOG.info("New GoL hypothesis %s from AURA pattern", h_id)

        # Auto-experiment if GoL and budget allows
        if (h_data.get("test_method") == "experiment"
                and self._check_budget("tested")):
            self.request_experiment(h_id)

        return f"H-{h_id}: {h_data['hypothesis'][:80]}"

    # ═══════════════════════════════════════════
    # HOOK 4: Periodic Analysis
    # ═══════════════════════════════════════════

    def periodic_analysis(self, current_state: dict) -> List[dict]:
        """Batch-evaluate all active hypotheses.

        current_state: {mood, energy, aura_state, ...}
        Called every ~25 min from workspace update loop.
        """
        results = []

        # Timeseries hypotheses
        for metric, values in self._timeseries.items():
            if len(values) >= 5 and self._check_budget("created"):
                h_data = self.synthesizer.from_timeseries(
                    metric, values, self._timestamps[metric])
                if h_data:
                    h_id = self.store.create(h_data)
                    if h_id:
                        self._increment_budget("created")

        # Check pending experiments
        for h in self.store.get_by_field("experiment_pending", 1):
            if h.get("experiment_id"):
                self._check_pending_experiment(h)

        # Auto-test untested experimentable hypotheses
        if self._check_budget("tested"):
            untested = self.store.get_testable_untested(limit=2)
            for h in untested:
                r = self.request_experiment(h["id"])
                if r:
                    results.append({"id": h["id"], "result": r})

        # Cleanup
        self.store.archive_old(max_age_days=30)
        self.store.enforce_active_limit(MAX_ACTIVE_HYPOTHESES)

        return results

    # ═══════════════════════════════════════════
    # HOOK 5: Experiment Complete
    # ═══════════════════════════════════════════

    def on_experiment_complete(self, experiment_id: int,
                               narration: str) -> Optional[dict]:
        """Called when Experiment Lab produces a result.

        Finds linked hypothesis, interprets, resolves.
        """
        # Find hypothesis waiting for this experiment
        hypotheses = self.store.get_by_field("experiment_id", experiment_id)
        if not hypotheses:
            return None

        h = hypotheses[0]
        verdict = self.lab_connector.interpret_result(h, narration)

        if verdict == "inconclusive":
            # Reset to active, clear experiment link so it can be retried
            self.store.update(h["id"], {
                "status": "active",
                "experiment_pending": 0,
                "experiment_id": None,
                "result": narration[:500],
            })
        else:
            self.evaluator._resolve(
                h, verdict, narration[:500],
                experiment_id=experiment_id,
            )

        LOG.info("Experiment %d → Hypothesis %s: %s",
                 experiment_id, h["id"], verdict)

        if verdict == "refuted":
            self.evaluator.auto_revise(h["id"], self.synthesizer)

        return {"hypothesis_id": h["id"], "verdict": verdict}

    # ═══════════════════════════════════════════
    # HOOK 6: Request Experiment
    # ═══════════════════════════════════════════

    def request_experiment(self, hypothesis_id: str) -> Optional[str]:
        """Request an active test via Experiment Lab.

        Can be called from: Sanctum, autonomous_research, periodic_analysis,
        on_idle_thought.
        """
        if not self._check_budget("tested"):
            LOG.debug("Experiment budget exhausted for today")
            return None

        result = self.evaluator.test_via_experiment(hypothesis_id)
        if result:
            self._increment_budget("tested")

        return result

    # ═══════════════════════════════════════════
    # HOOK 7: Conversation Reflection
    # ═══════════════════════════════════════════

    def on_conversation_reflection(
        self,
        reflection: str,
        conversation_excerpt: str,
        session_meta: dict,
    ) -> Optional[str]:
        """Process a conversation reflection for hypothesis generation.

        Quality filter is INSIDE the synthesizer (6 layers).
        Additional: max 5 active relational hypotheses, Jaccard novelty check.
        """
        if not self._check_budget("created"):
            return None

        # Domain cap: max 5 active relational hypotheses
        relational_count = self.store.count_active_by_domain("relational")
        if relational_count >= 5:
            return None

        h_data = self.synthesizer.from_conversation_reflection(
            reflection, conversation_excerpt, session_meta,
        )
        if not h_data:
            return None

        # LAYER 4 (Novelty): Check against existing relational hypotheses
        existing = self.store.get_by_status("active", limit=20)
        for ex in existing:
            if ex.get("domain") != "relational":
                continue
            new_words = set(h_data["hypothesis"].lower().split())
            old_words = set(ex["hypothesis"].lower().split())
            union = new_words | old_words
            if union:
                jaccard = len(new_words & old_words) / len(union)
                if jaccard > 0.4:
                    LOG.debug("Conv hypothesis rejected L4 (novelty J=%.2f vs %s)",
                              jaccard, ex["id"])
                    return None

        h_id = self.store.create(h_data)
        if not h_id:
            return None

        self._increment_budget("created")
        LOG.info("New relational hypothesis %s: %s", h_id, h_data["hypothesis"][:60])

        # Passive test: evaluate active relational hypotheses against this conversation
        for active in existing:
            if active.get("domain") != "relational":
                continue
            if h_id and str(active["id"]) == str(h_id):
                continue
            try:
                result = self.evaluator.evaluate_against_conversation(
                    active["id"], conversation_excerpt)
                if result:
                    LOG.info("Hypothesis %s %s by conversation", active["id"], result)
                    if result == "refuted":
                        self.evaluator.auto_revise(active["id"], self.synthesizer)
            except Exception as e:
                LOG.debug("Conv eval failed for %s: %s", active["id"], e)

        return f"H-{h_id}: {h_data['hypothesis'][:80]}"

    # ═══════════════════════════════════════════
    # CONTEXT GENERATORS
    # ═══════════════════════════════════════════

    def get_context_for_idle_thought(self) -> str:
        """Brief status for idle thought prompt. Max ~100 chars."""
        stats = self.store.get_stats()
        if stats.get("total", 0) == 0:
            return ""

        parts = [f"[HypEng] Active: {stats.get('active_count', 0)}"]
        if stats.get("prediction_accuracy") is not None:
            parts.append(f"Acc: {stats['prediction_accuracy']:.0%}")
        if stats.get("experiment_tested", 0) > 0:
            parts.append(f"Exp: {stats['experiment_tested']}")

        return " | ".join(parts)

    def get_context_for_sanctum_lab(self) -> str:
        """Testable hypotheses for Sanctum Lab location."""
        testable = [
            h for h in self.store.get_by_status("active")
            if h.get("test_method") in ("experiment", "both")
        ]

        if not testable:
            return (
                "[HYPOTHESIS ENGINE] No hypotheses awaiting "
                "experimental testing. Explore freely."
            )

        lines = ["[HYPOTHESES AWAITING EXPERIMENTAL TEST]"]
        for h in testable[:5]:
            station = h.get("experiment_station", "?")
            lines.append(
                f"  H-{h['id'][:6]} [{station}]: "
                f"{h['hypothesis'][:80]}"
            )
            lines.append(
                f"    Predict: {h['prediction'][:60]} "
                f"(conf: {h['confidence']:.0%})"
            )
        lines.append(
            "You can test these by running the appropriate experiment."
        )
        return "\n".join(lines)

    def get_context_for_research(self) -> str:
        """Context for autonomous research planning."""
        testable = [
            h for h in self.store.get_by_status("active")
            if h.get("test_method") in ("experiment", "both")
            and not h.get("experiment_pending")
        ]
        stats = self.store.get_stats()

        lines = [f"Active hypotheses: {stats.get('active_count', 0)}"]
        if stats.get("prediction_accuracy") is not None:
            lines.append(f"Prediction accuracy: {stats['prediction_accuracy']:.0%}")
        if testable:
            lines.append(f"Testable via experiment: {len(testable)}")
            for h in testable[:3]:
                lines.append(f"  - {h['id'][:6]}: {h['hypothesis'][:60]}")
        return "\n".join(lines)

    # ═══════════════════════════════════════════
    # STATS
    # ═══════════════════════════════════════════

    def get_stats(self) -> dict:
        """Return engine statistics."""
        return self.store.get_stats()

    def get_hypothesis(self, hypothesis_id: str) -> Optional[dict]:
        """Get a single hypothesis."""
        return self.store.get(hypothesis_id)

    # ═══════════════════════════════════════════
    # INTERNALS
    # ═══════════════════════════════════════════

    def _update_timeseries(self, aura_data: dict):
        """Buffer AURA metrics for timeseries analysis."""
        now = time.time()
        for key, value in aura_data.items():
            if isinstance(value, (int, float)):
                if key not in self._timeseries:
                    self._timeseries[key] = []
                    self._timestamps[key] = []
                self._timeseries[key].append(value)
                self._timestamps[key].append(now)
                # Rolling buffer of 20
                if len(self._timeseries[key]) > 20:
                    self._timeseries[key] = self._timeseries[key][-20:]
                    self._timestamps[key] = self._timestamps[key][-20:]

    def _check_budget(self, budget_type: str) -> bool:
        """Check daily budget without incrementing."""
        budget = self.store.get_budget()
        if budget_type == "created":
            return budget.get("created", 0) < MAX_HYPOTHESES_PER_DAY
        elif budget_type == "tested":
            return budget.get("tested", 0) < MAX_EXPERIMENTS_PER_DAY
        return True

    def _increment_budget(self, budget_type: str):
        """Increment daily budget counter."""
        max_val = (MAX_HYPOTHESES_PER_DAY if budget_type == "created"
                   else MAX_EXPERIMENTS_PER_DAY)
        self.store.check_and_increment_budget(budget_type, max_val)

    def _check_pending_experiment(self, h: dict):
        """Check if a pending experiment has a result."""
        if not h.get("experiment_id"):
            return
        exp = self.lab_connector.get_experiment_result(h["experiment_id"])
        if exp and not exp.get("error"):
            self.on_experiment_complete(h["experiment_id"], exp.get("narration", ""))
