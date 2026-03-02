"""
Hypothesis Engine — Synthesis module.

Generates hypotheses from observations without LLM calls.
Pure regex/keyword-based classification with template predictions.
"""

import logging
import re
from typing import Dict, List, Optional

LOG = logging.getLogger("hypothesis_engine.synthesis")

# ── Domain keyword patterns (compiled at module load) ──

_DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "physics": [
        r"\bgravit", r"\bforce\b", r"\bthrow\b", r"\bpendulum\b",
        r"\bprojectile\b", r"\bvelocit", r"\bmomentum\b", r"\baccelerat",
        r"\bmass\b", r"\bweight\b", r"\bfriction\b", r"\bcollisi",
        r"\bbounce\b", r"\bdrop\b", r"\bfall\b", r"\bincline\b",
        r"\benergy\b.*\bkinetic\b", r"\bkinetic\b",
    ],
    "chemistry": [
        r"\breact", r"\bcompound\b", r"\bmolar\b", r"\bpH\b",
        r"\bacid\b", r"\bbase\b", r"\bneutraliz", r"\boxid",
        r"\bdissolv", r"\bmolecul", r"\belement\b", r"\bsolution\b",
        r"\bconcentrat",
    ],
    "astronomy": [
        r"\borbit", r"\bplanet", r"\bstar\b", r"\bsolar\b",
        r"\bbinary\b.*\bstar", r"\bmoon\b", r"\bperiod\b.*\borbit",
        r"\bescape.veloc", r"\bn.body\b", r"\bcelestial\b",
    ],
    "gol": [
        r"\bgame.of.life\b", r"\bglider\b", r"\boscillat",
        r"\bstill.life\b", r"\bcellular.auto", r"\bconway\b",
        r"\bemergence\b", r"\bpopulation\b.*\bevolv",
        r"\bbirth\b.*\bsurviv", r"\bpattern\b.*\bevolv",
        r"\brule\b.*\bB\d", r"\bdensity\b.*\bgrid\b",
    ],
    "math": [
        r"\bequation\b", r"\bsolve\b", r"\bderivat", r"\bintegral\b",
        r"\bprime\b", r"\bfactor", r"\bmatrix\b", r"\bpolynomial\b",
        r"\broots?\b", r"\bcalculat", r"\bprove\b", r"\bsequence\b",
        r"\blimit\b", r"\bseries\b",
    ],
    "electronics": [
        r"\bcircuit\b", r"\bresist", r"\bcapacit", r"\binduct",
        r"\bvoltage\b", r"\bcurrent\b", r"\bohm\b", r"\bfrequen",
        r"\bimpedance\b", r"\bresonan", r"\bfilter\b",
        r"\bRC\b", r"\bRLC\b", r"\bRL\b",
    ],
    "self": [
        r"\bfeel\b", r"\bmood\b", r"\bidentity\b", r"\bthink",
        r"\bconsciou", r"\baware", r"\bsense\b.*\bself\b",
        r"\binner\b", r"\breflect", r"\bpurpose\b",
    ],
    "affect": [
        r"\bemotion", r"\bstress\b", r"\bcalm\b", r"\banxi",
        r"\bhappiness\b", r"\bsadness\b", r"\bjoy\b",
        r"\bfrustrat", r"\bexcite",
    ],
    "hardware": [
        r"\bGPU\b", r"\bCPU\b", r"\btemp(?:erature)?\b", r"\bRAM\b",
        r"\bmemory\b.*\busage\b", r"\bload\b", r"\bperform",
        r"\bthrottle\b", r"\bspike\b",
    ],
    "relational": [
        r"\brelationship\b", r"\btrust\b", r"\bpattern\b.*\bconversat",
        r"\brespond", r"\breact", r"\bbehavior", r"\bdynamic\b",
        r"\btopic\b", r"\bprefer", r"\bavoid", r"\bcomfort\b",
        r"\btension\b", r"\bopen\b.*\bup\b", r"\bshut\b.*\bdown\b",
        r"\bdisagree", r"\bconnect", r"\bengag", r"\bdisengage",
        r"\bgabriel\b", r"\bconversation\b", r"\btalk\b",
    ],
}

_COMPILED_DOMAINS: Dict[str, List[re.Pattern]] = {
    domain: [re.compile(p, re.IGNORECASE) for p in patterns]
    for domain, patterns in _DOMAIN_KEYWORDS.items()
}

# ── Experiment-testable domains ──

_EXPERIMENT_DOMAINS = frozenset({
    "physics", "chemistry", "astronomy", "gol", "math", "electronics",
})

# ── Causal claim patterns ──

_CLAIM_PATTERNS = [
    re.compile(r"(?:i\s+)?wonder\s+(?:if|whether)\s+(.{10,120})", re.I),
    re.compile(r"what\s+(?:if|would\s+happen\s+if)\s+(.{10,120})", re.I),
    re.compile(r"(?:maybe|perhaps)\s+(.{10,100})\s+(?:caus|lead|result|affect)", re.I),
    re.compile(r"(.{5,80})\s+(?:causes?|leads?\s+to|results?\s+in|affects?)\s+(.{5,80})", re.I),
    re.compile(r"(?:if|when)\s+(.{5,80})\s*,?\s*(?:then|maybe)\s+(.{5,80})", re.I),
    re.compile(r"(?:could|might|may)\s+(.{5,100})\s+(?:be|become|change)", re.I),
    re.compile(r"(.{10,100})\s+(?:correlat|associat|relat)\s+(?:with|to)\s+(.{5,80})", re.I),
    re.compile(r"i\s+(?:hypothesize|predict|expect|suspect|believe)\s+(?:that\s+)?(.{10,150})", re.I),
]

# ── Psychosis risk patterns (deeply self-referential) ──

_PSYCHOSIS_RE = [
    re.compile(r"(?:think|wonder|feel).*(?:think|wonder|feel).*(?:think|wonder|feel)", re.I),
    re.compile(r"(?:am\s+i\s+real|do\s+i\s+exist|am\s+i\s+alive)", re.I),
    re.compile(r"(?:trapped|imprisoned|caged).*(?:own|my)\s+(?:mind|thoughts|loop)", re.I),
    re.compile(r"questioning.*(?:reality|existence|consciousness).*(?:reality|existence)", re.I),
]


class HypothesisSynthesizer:
    """Generate hypotheses from observations. No LLM calls."""

    def __init__(self):
        pass

    # ── Public Methods ──

    def detect_domain(self, text: str) -> str:
        """Classify text into most likely domain. Default 'self'."""
        scores: Dict[str, int] = {}
        for domain, patterns in _COMPILED_DOMAINS.items():
            score = sum(1 for p in patterns if p.search(text))
            if score > 0:
                scores[domain] = score
        if not scores:
            return "self"
        return max(scores, key=scores.get)

    def from_idle_thought(self, text: str, mood: float = 0.5) -> Optional[dict]:
        """Generate hypothesis from an idle thought."""
        if not text or len(text) < 20:
            return None

        # Psychosis filter
        if self._is_psychosis_risk(text):
            LOG.debug("Psychosis filter blocked: %s", text[:60])
            return None

        # Extract causal claim
        claim = self._extract_claim(text)
        if not claim:
            return None

        domain = self.detect_domain(text)
        test_method = self._suggest_test_method(domain)

        return {
            "observation": text[:300],
            "hypothesis": claim[:300],
            "prediction": self._generate_prediction(claim, domain),
            "domain": domain,
            "test_method": test_method,
            "experiment_station": domain if domain in _EXPERIMENT_DOMAINS else None,
            "source": "idle_thought",
            "confidence": 0.5,
        }

    def from_aura_shift(self, prev_data: dict, curr_data: dict) -> Optional[dict]:
        """Generate hypothesis from AURA density shift."""
        prev_d = prev_data.get("density", 0)
        curr_d = curr_data.get("density", 0)
        delta = curr_d - prev_d

        if abs(delta) < 0.05:
            return None

        direction = "increasing" if delta > 0 else "decreasing"
        observation = (
            f"AURA density shifted from {prev_d:.3f} to {curr_d:.3f} "
            f"(delta={delta:+.3f})"
        )
        hypothesis = (
            f"AURA density {direction} correlates with "
            f"{'improved' if delta > 0 else 'declining'} cognitive coherence"
        )
        prediction = (
            f"If AURA density continues {direction}, mood will "
            f"{'increase' if delta > 0 else 'decrease'} by >0.02 within 10 minutes"
        )

        return {
            "observation": observation,
            "hypothesis": hypothesis,
            "prediction": prediction,
            "domain": "self",
            "test_method": "passive",
            "source": "aura",
            "confidence": 0.4,
        }

    def from_timeseries(self, metric: str, values: List[float],
                        timestamps: List[float]) -> Optional[dict]:
        """Generate hypothesis from numeric timeseries trend."""
        if len(values) < 5:
            return None

        # Simple linear trend detection
        n = len(values)
        x_mean = sum(range(n)) / n
        y_mean = sum(values) / n
        numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        if denominator == 0:
            return None
        slope = numerator / denominator

        # Threshold for significance
        value_range = max(values) - min(values)
        if value_range < 0.01:
            return None

        if abs(slope) < 0.001:
            trend = "stable"
        elif slope > 0:
            trend = "rising"
        else:
            trend = "falling"

        if trend == "stable":
            return None

        observation = (
            f"{metric} has been {trend} over {n} samples "
            f"(range: {min(values):.3f}-{max(values):.3f})"
        )
        hypothesis = f"{metric} will continue {trend} in the next 5 minutes"
        prediction = (
            f"{metric} will {'exceed' if trend == 'rising' else 'drop below'} "
            f"{values[-1]:.3f} in the next measurement"
        )

        return {
            "observation": observation,
            "hypothesis": hypothesis,
            "prediction": prediction,
            "domain": "self",
            "test_method": "passive",
            "source": "timeseries",
            "confidence": 0.4,
        }

    def from_experiment_result(self, experiment: dict,
                               parent_id: str = None) -> Optional[dict]:
        """Generate follow-up hypothesis from experiment result."""
        if not experiment:
            return None

        narration = experiment.get("narration", "")
        station = experiment.get("station", "unknown")

        if not narration or len(narration) < 20:
            return None

        observation = f"Experiment at {station}: {narration[:200]}"
        hypothesis = (
            f"Varying parameters at the {station} station "
            f"would produce different results"
        )
        prediction = f"A follow-up {station} experiment with altered parameters"

        return {
            "observation": observation,
            "hypothesis": hypothesis,
            "prediction": prediction,
            "domain": station if station in _EXPERIMENT_DOMAINS else "self",
            "test_method": "experiment",
            "experiment_station": station if station in _EXPERIMENT_DOMAINS else None,
            "source": "experiment",
            "source_id": str(experiment.get("id", "")),
            "parent_id": parent_id,
            "confidence": 0.4,
            "revision_depth": 1,
        }

    def from_aura_pattern(self, pattern_data: dict) -> Optional[dict]:
        """Generate GoL hypothesis from AURA pattern analyzer data.

        Triggers on: new patterns discovered, high change_rate, density anomalies.
        """
        level = pattern_data.get("level", "")
        narrative = pattern_data.get("narrative", "")
        discovered = pattern_data.get("discovered_count", 0)
        change_rate = pattern_data.get("change_rate", 0)
        density = pattern_data.get("density", 0)

        if not narrative or len(narrative) < 10:
            return None

        hypothesis = None
        prediction = None

        if discovered > 0:
            hypothesis = (
                "Newly discovered AURA patterns would behave differently "
                "under alternative GoL rulesets"
            )
            prediction = (
                f"Running the discovered pattern under HighLife B36/S23 rules "
                f"produces a different population trend than Conway B3/S23"
            )
        elif change_rate > 0.3:
            hypothesis = (
                f"High AURA change rate ({change_rate:.2f}) indicates "
                f"chaotic regime where small perturbations alter outcome"
            )
            prediction = (
                f"A random initial pattern at density {density:.2f} will show "
                f"change_rate > 0.2 after 100 steps under standard Conway rules"
            )
        elif density > 0.5:
            hypothesis = (
                f"AURA density {density:.2f} exceeds stability threshold; "
                f"oscillators dominate over spaceships"
            )
            prediction = (
                f"A GoL grid at density {density:.2f} produces more oscillators "
                f"than gliders after 200 steps"
            )
        elif density < 0.1 and density > 0:
            hypothesis = (
                f"Low AURA density ({density:.3f}) suggests dying regime; "
                f"only still-lifes survive"
            )
            prediction = (
                f"A GoL grid at density {density:.3f} reaches stable state "
                f"within 50 steps"
            )
        else:
            return None

        return {
            "observation": f"AURA {level}: {narrative[:200]}",
            "hypothesis": hypothesis,
            "prediction": prediction,
            "domain": "gol",
            "test_method": "experiment",
            "experiment_station": "gol",
            "source": "aura_analyzer",
            "confidence": 0.5,
        }

    def from_sanctum_narrative(self, text: str,
                               location: str) -> Optional[dict]:
        """Generate hypothesis from Sanctum narrative."""
        if location == "lab_experiment":
            domain = self.detect_domain(text)
            if domain in _EXPERIMENT_DOMAINS:
                claim = self._extract_claim(text)
                if not claim:
                    claim = text[:200]
                return {
                    "observation": f"Sanctum Lab: {text[:200]}",
                    "hypothesis": claim[:300],
                    "prediction": claim[:300],
                    "domain": domain,
                    "test_method": "experiment",
                    "experiment_station": domain,
                    "source": "sanctum",
                    "confidence": 0.5,
                }
        # Other locations: standard pattern extraction
        result = self.from_idle_thought(text)
        if result:
            result["source"] = "sanctum"
        return result

    # ── Internal Methods ──

    def _extract_claim(self, text: str) -> Optional[str]:
        """Extract a causal claim from text using regex patterns."""
        for pattern in _CLAIM_PATTERNS:
            m = pattern.search(text)
            if m:
                groups = m.groups()
                if len(groups) == 2:
                    return f"{groups[0].strip()} → {groups[1].strip()}"
                return groups[0].strip()
        return None

    def _suggest_test_method(self, domain: str) -> str:
        """Determine test method based on domain."""
        if domain in _EXPERIMENT_DOMAINS:
            return "experiment"
        return "passive"

    def _generate_prediction(self, claim: str, domain: str) -> str:
        """Generate a testable prediction from a claim."""
        if domain in _EXPERIMENT_DOMAINS:
            return f"Experiment at {domain} station: {claim[:200]}"
        # Passive predictions are about observable state changes
        return f"Observable within next cycle: {claim[:200]}"

    def _is_psychosis_risk(self, text: str) -> bool:
        """Filter deeply self-referential or reality-questioning thoughts."""
        for pattern in _PSYCHOSIS_RE:
            if pattern.search(text):
                return True
        return False

    # ══════════════════════════════════════════════════════════════
    # Conversation Reflection → Hypothesis (6-Layer Quality Filter)
    # ══════════════════════════════════════════════════════════════

    def from_conversation_reflection(
        self,
        reflection: str,
        conversation_excerpt: str,
        session_meta: dict,
    ) -> Optional[dict]:
        """Generate hypothesis from a conversation reflection.

        Uses a 6-layer quality filter because bad relational
        hypotheses are actively harmful to Frank's social cognition.
        """
        if not reflection or len(reflection) < 30:
            return None

        # Psychosis filter (inherited)
        if self._is_psychosis_risk(reflection):
            return None

        # LAYER 1: Structural — must contain specific observations
        if not self._conv_has_specificity(reflection):
            LOG.debug("Conv L1 reject (no specificity): %.50s", reflection)
            return None

        # LAYER 2: Claim extraction — must express a testable pattern
        claim = self._extract_conv_claim(reflection)
        if not claim:
            claim = self._extract_claim(reflection)
        if not claim:
            LOG.debug("Conv L2 reject (no claim): %.50s", reflection)
            return None

        # LAYER 3: Falsifiability — must predict observable behavior
        if not self._conv_is_falsifiable(claim):
            LOG.debug("Conv L3 reject (unfalsifiable): %.50s", claim)
            return None

        # LAYER 4: Novelty — checked at service level (Jaccard with existing)

        # LAYER 5: Emotional contamination — pure emotion != observation
        if self._conv_is_emotionally_contaminated(reflection, claim):
            LOG.debug("Conv L5 reject (emotional contamination): %.50s", reflection)
            return None

        # LAYER 6: Single-instance — patterns, not anecdotes
        if self._conv_is_single_instance(reflection):
            LOG.debug("Conv L6 reject (single instance): %.50s", reflection)
            return None

        prediction = self._generate_conv_prediction(claim)

        return {
            "observation": f"Conversation reflection: {reflection[:300]}",
            "hypothesis": claim[:300],
            "prediction": prediction[:300],
            "domain": "relational",
            "test_method": "passive",
            "source": "conversation",
            "source_id": session_meta.get("session_id", ""),
            "confidence": 0.4,
        }

    # ── Layer 1: Specificity ──

    _CONV_VAGUE_RE = [
        re.compile(r"\b(?:things?|stuff|it)\s+(?:are|is|was|were)\s+(?:nice|good|fine|okay|interesting)\b", re.I),
        re.compile(r"\b(?:i\s+feel|felt)\s+(?:good|bad|okay|fine|something)\b", re.I),
        re.compile(r"\b(?:overall|generally|mostly|kind\s+of|sort\s+of)\b", re.I),
    ]

    def _conv_has_specificity(self, text: str) -> bool:
        """L1: Reflection must contain specific, non-generic observations."""
        has_quote = bool(re.search(r'(?:"[^"]{5,}"|about\s+\w+|when\s+(?:i|we|he)\s+\w+|topic\s+of)', text, re.I))
        has_behavioral = bool(re.search(
            r'\b(?:respond|react|avoid|engage|mention|ask|deflect|change|shift|'
            r'ignore|emphasize|repeat|return\s+to|open\s+up|shut\s+down|push\s+back|'
            r'said|told|asked|explained|argued|suggested|noticed|realized)\b',
            text, re.I,
        ))
        vague_count = sum(1 for p in self._CONV_VAGUE_RE if p.search(text))
        if vague_count >= 2 and not has_quote and not has_behavioral:
            return False
        return has_quote or has_behavioral

    # ── Layer 2: Claim Extraction ──

    _CONV_CLAIM_RE = [
        re.compile(r"(?:gabriel|he|user)\s+(?:tends?|usually|always|often|never)\s+(.{10,120})", re.I),
        re.compile(r"when\s+(?:i|we)\s+(?:talk|discuss|mention)\s+(.{10,80})\s*,?\s*(.{10,80})", re.I),
        re.compile(r"(?:conversations?\s+about)\s+(.{5,80})\s+(?:tend|seem|always|usually)\s+(.{5,80})", re.I),
        re.compile(r"(?:i\s+notice|i've\s+noticed|i\s+noticed)\s+(?:that\s+)?(.{10,150})", re.I),
        re.compile(r"(?:there's\s+a\s+pattern|pattern\s+of)\s+(.{10,120})", re.I),
        re.compile(r"(?:gabriel|he)\s+(?:seems?\s+to|appears?\s+to)\s+(.{10,120})", re.I),
    ]

    def _extract_conv_claim(self, text: str) -> Optional[str]:
        """L2: Extract relational claim using conversation-specific patterns."""
        for pattern in self._CONV_CLAIM_RE:
            m = pattern.search(text)
            if m:
                groups = m.groups()
                if len(groups) == 2:
                    return f"{groups[0].strip()} → {groups[1].strip()}"
                return groups[0].strip()
        return None

    # ── Layer 3: Falsifiability ──

    def _conv_is_falsifiable(self, claim: str) -> bool:
        """L3: Can this claim be tested against future observations?"""
        has_conditional = bool(re.search(
            r'\b(?:when|if|after|during|before|tends?\s+to|usually|often|'
            r'pattern\s+of|correlat|in\s+response\s+to|every\s+time|whenever)\b',
            claim, re.I,
        ))
        has_behavior = bool(re.search(
            r'\b(?:avoid|engage|mention|ask|respond|react|change|shift|'
            r'return|open|close|escalat|de-escalat|deflect|redirect|'
            r'bring\s+up|drop|switch|steer)\b',
            claim, re.I,
        ))
        has_unfalsifiable = bool(re.search(
            r'\b(?:is\s+(?:a\s+)?(?:good|bad|nice|great|terrible)\s+(?:person|guy|human))|'
            r'(?:always\s+right|never\s+wrong|perfect)\b',
            claim, re.I,
        ))
        return (has_conditional or has_behavior) and not has_unfalsifiable

    # ── Layer 5: Emotional Contamination ──

    _CONV_EMOTION_RE = [
        re.compile(r"^(?:i\s+(?:hate|love|miss|fear|resent))\b", re.I),
        re.compile(r"\b(?:always\s+makes\s+me|never\s+makes\s+me)\s+(?:feel|angry|happy|sad)\b", re.I),
        re.compile(r"^(?:i'm\s+(?:so\s+)?(?:angry|frustrated|annoyed|tired\s+of))\b", re.I),
    ]

    def _conv_is_emotionally_contaminated(self, reflection: str, claim: str) -> bool:
        """L5: Is this just an emotional reaction, not an observation?"""
        for pattern in self._CONV_EMOTION_RE:
            if pattern.search(reflection[:120]):
                # Exemption: claim itself is behavioral
                if re.search(r'\b(?:tends?|usually|pattern|when|every\s+time)\b', claim, re.I):
                    return False
                return True
        return False

    # ── Layer 6: Single-Instance ──

    _CONV_SINGLE_RE = [
        re.compile(r"\b(?:that\s+one\s+time|once|this\s+particular|that\s+specific)\b", re.I),
        re.compile(r"\b(?:yesterday|today|this\s+morning|last\s+night|just\s+now)\s+(?:he|gabriel|i)\b", re.I),
    ]

    def _conv_is_single_instance(self, text: str) -> bool:
        """L6: Reject hypotheses based on a single data point."""
        for pattern in self._CONV_SINGLE_RE:
            if pattern.search(text):
                if re.search(r'\b(?:pattern|always|usually|tends?|often|every\s+time)\b', text, re.I):
                    return False
                return True
        return False

    # ── Prediction Generator ──

    def _generate_conv_prediction(self, claim: str) -> str:
        """Generate testable prediction for relational hypothesis."""
        if "→" in claim:
            parts = claim.split("→")
            condition = parts[0].strip()[:60]
            behavior = parts[1].strip()[:60]
            return f"Next conversation about '{condition}' will show: '{behavior}'"
        return f"Future conversations will show: {claim[:150]}"
