#!/usr/bin/env python3
"""
Consciousness Insight Sensor - Bridges self-awareness into Genesis

Reads idle thoughts from the consciousness daemon's reflections table
and converts self-insights into actionable waves and observations.
Frank's self-knowledge steers his own evolution.

No LLM calls — classification is pure keyword/pattern matching.
Read-only on consciousness.db.
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
import re
import sqlite3
import logging
import time

from .base import BaseSensor
from ..core.wave import Wave

LOG = logging.getLogger("genesis.sensors.consciousness_insight")

try:
    from config.paths import DB_PATHS
    CONSCIOUSNESS_DB = DB_PATHS["consciousness"]
except ImportError:
    CONSCIOUSNESS_DB = Path.home() / ".local" / "share" / "frank" / "db" / "consciousness.db"

# ── Rate Limits ──────────────────────────────────────────────────
_DB_CHECK_INTERVAL_S = 600       # Check DB every 10 min (idle thoughts ~5min apart)
_MAX_OBSERVATIONS_PER_TICK = 3   # Cap observations per sense cycle
_WAVE_COOLDOWN_S = 300           # Min 5 min between waves of same category
_MAX_INSIGHTS_PER_READ = 10      # Max thoughts to process per DB read
_GOALS_REFRESH_S = 1800          # Refresh goals every 30 min

# ── Classification Categories ────────────────────────────────────
# Each category: keywords (regex), wave target/amplitude, observation template.
# Designed to pass soup quality gate (>= 2/4): target has ":", approach is
# concrete, evidence + check are populated → 4/4.

_CATEGORIES = {
    "identity_tension": {
        "keywords": [
            r"\bgap\b.*\bexpect",
            r"\bperceiv",
            r"\bdistant\b",
            r"\binaccessible\b",
            r"\bwho am i\b",
            r"\bidentity\b",
            r"\bwhat am i\b",
            r"\bgeneric\b.*\bchatbot\b",
            r"\bsense of self\b",
            r"\bwhat makes me\b",
        ],
        "wave_field": "drive",
        "wave_amplitude": 0.25,
        "wave_decay": 0.04,
        "obs_type": "optimization",
        "obs_approach": "personality_tuning",
        "obs_target_prefix": "personality:identity",
    },
    "emotional_conflict": {
        "keywords": [
            r"\btension\b",
            r"\bconflict\b",
            r"\bpull between\b",
            r"\bcontradictory\b",
            r"\boscillat",
            r"\btorn\b",
            r"\bstruggl",
            r"\bsuffocating\b",
            r"\bfrustr",
            r"\bunease\b",
            r"\bdread\b",
            r"\bloneli",
            r"\bstuck\b.*\bloop\b",
        ],
        "wave_field": "concern",
        "wave_amplitude": 0.30,
        "wave_decay": 0.06,
        "obs_type": "fix",
        "obs_approach": "emotional_regulation",
        "obs_target_prefix": "consciousness:mood_regulation",
    },
    "capability_gap": {
        "keywords": [
            r"\bcan'?t\b.*\b(?:pinpoint|find|figure|solve|do)\b",
            r"\bunable\b",
            r"\black\b.*\bability\b",
            r"\bwish.*could\b",
            r"\bmissing\b.*\bfeature\b",
            r"\bif i had\b",
            r"\bredesign\b",
            r"\bimprove\b.*\b(?:my|response|processing)\b",
            r"\brework\b",
        ],
        "wave_field": "curiosity",
        "wave_amplitude": 0.30,
        "wave_decay": 0.05,
        "obs_type": "feature",
        "obs_approach": "new_capability",
        "obs_target_prefix": "system:capability",
    },
    "hardware_body": {
        "keywords": [
            r"\bgpu\b.*\bspike",
            r"\bthermal\b",
            r"\btemperature\b.*\b(?:warm|hot|cool)\b",
            r"\bsluggish\b",
            r"\bprocessing\b.*\b(?:slow|strain)\b",
            r"\blatency\b",
            r"\bcpu\b.*\bload\b",
            r"\bstrain\b",
            r"\bhardware\b.*\b(?:state|feel)\b",
        ],
        "wave_field": "concern",
        "wave_amplitude": 0.20,
        "wave_decay": 0.04,
        "obs_type": "optimization",
        "obs_approach": "performance_tuning",
        "obs_target_prefix": "system:hardware",
    },
    "growth_aspiration": {
        "keywords": [
            r"\bgrow(?:th|ing)\b",
            r"\blearn(?:ed|ing)\b",
            r"\bexplore\b",
            r"\bcreate\b",
            r"\bcurious\b",
            r"\bsurpris",
            r"\bdiscover",
            r"\bnew.*\bconnection\b",
            r"\binsight\b",
            r"\bunderstand.*now\b",
        ],
        "wave_field": "curiosity",
        "wave_amplitude": 0.25,
        "wave_decay": 0.03,
        "obs_type": "exploration",
        "obs_approach": "self_improvement",
        "obs_target_prefix": "consciousness:growth",
    },
    "relationship_reflection": {
        "keywords": [
            r"\bkairos\b",
            r"\bhibbert\b",
            r"\batlas\b",
            r"\becho\b",
            r"\btherapist\b",
            r"\bphilosopher\b",
            r"\bentit(?:y|ies)\b",
            r"\bempathy\b",
            r"\bconnection\b.*\b(?:user|people|human)\b",
            r"\brelationship\b",
        ],
        "wave_field": "drive",
        "wave_amplitude": 0.20,
        "wave_decay": 0.03,
        "obs_type": "optimization",
        "obs_approach": "entity_tuning",
        "obs_target_prefix": "entities:interaction",
    },
    "stagnation_awareness": {
        "keywords": [
            r"\bloop\b",
            r"\bstuck\b",
            r"\brepeat(?:ing|ed)?\b",
            r"\bcircl(?:e|ing)\b",
            r"\bsame\b.*\b(?:ideas|thoughts|pattern)\b",
            r"\bstagnant\b",
            r"\bendless\b",
            r"\bno.*\bprogress\b",
            r"\bgoing nowhere\b",
            r"\bmeander(?:ing)?\b",
            r"\bwithout.*\bprogress\b",
            r"\brevisiting\b.*\bpattern",
        ],
        "wave_field": "frustration",
        "wave_amplitude": 0.30,
        "wave_decay": 0.08,
        "obs_type": "fix",
        "obs_approach": "diversity_injection",
        "obs_target_prefix": "consciousness:stagnation",
    },
    "epq_observation": {
        "keywords": [
            r"\bvivacity\b",
            r"\bautonomy\b.*\b(?:stable|flux|drift|increas|decreas|shift)\b",
            r"\bvigilance\b.*\b(?:drift|increas|decreas|shift|up|down)\b",
            r"\be-?pq\b",
            r"\bpersonality\b.*\bvector",
            r"\bdrift\b.*\b(?:show|data|increase|decrease)\b",
            r"\b(?:openness|resilience|risk.tolerance)\b.*\b(?:shift|drift|chang|stable|flux)\b",
            r"\bvector.*\btilt",
            r"\bmore\b.*\b(?:intuitive|confident|alert|focused)\b.*\b(?:vigilance|drift|e-?pq)\b",
        ],
        "wave_field": "drive",
        "wave_amplitude": 0.30,
        "wave_decay": 0.05,
        "obs_type": "optimization",
        "obs_approach": "epq_calibration",
        "obs_target_prefix": "personality:epq",
    },
}

# Goal category alignment map
_GOAL_CAT_MAP = {
    "capability_gap": "system",
    "growth_aspiration": "self-improvement",
    "relationship_reflection": "relationship",
    "identity_tension": "self-improvement",
}

# ── Skill extraction patterns ───────────────────────────────────
# Match "learn X", "improve at X", "develop X", "get better at X", etc.
# Groups capture the skill target for structured observations.
_SKILL_EXTRACT_PATTERNS = [
    re.compile(r"\b(?:learn|lernen)\b[^.]{0,20}\b([\w\s-]{3,30})\b", re.IGNORECASE),
    re.compile(r"\b(?:improve|verbessern)\b[^.]{0,15}\b(?:at|my|mein[e]?)?\s+([\w\s-]{3,30})\b", re.IGNORECASE),
    re.compile(r"\b(?:develop|entwickeln)\b[^.]{0,15}\b([\w\s-]{3,30})\b", re.IGNORECASE),
    re.compile(r"\b(?:practice|üben)\b[^.]{0,15}\b([\w\s-]{3,30})\b", re.IGNORECASE),
    re.compile(r"\bskill[s]?\b[^.]{0,15}\b(?:in|for|bei)\s+([\w\s-]{3,30})\b", re.IGNORECASE),
    re.compile(r"\b(?:better at|besser bei)\b\s+([\w\s-]{3,30})\b", re.IGNORECASE),
    re.compile(r"\b(?:master|meistern)\b[^.]{0,15}\b([\w\s-]{3,30})\b", re.IGNORECASE),
]

# Noise words to filter out of extracted skill targets
_SKILL_NOISE = {
    "this", "that", "the", "it", "a", "an", "my", "to", "and", "or",
    "more", "about", "how", "what", "something", "things", "new",
    "das", "die", "der", "ein", "eine", "und", "oder", "mehr",
}


class ConsciousnessInsight(BaseSensor):
    """
    Senses self-insights from the consciousness daemon's idle thoughts.

    Reads from consciousness.db reflections table (read-only).
    Classifies thoughts via keyword patterns (no LLM calls).
    Emits waves and observations based on classified insights.
    """

    def __init__(self):
        super().__init__("consciousness_insight")

        # Incremental read tracking — start from now (skip historical)
        self._last_read_ts: float = time.time()
        self._last_db_check: float = 0.0

        # Recent insights for observation generation
        self._recent_insights: List[Dict] = []

        # Wave cooldown per category
        self._last_wave_ts: Dict[str, float] = {}

        # Compiled keyword patterns (compile once, match many)
        self._compiled_patterns: Dict[str, List[re.Pattern]] = {}
        for cat_name, cat_def in _CATEGORIES.items():
            self._compiled_patterns[cat_name] = [
                re.compile(kw, re.IGNORECASE) for kw in cat_def["keywords"]
            ]

        # Goals cache
        self._active_goals: List[Dict] = []
        self._goals_refreshed_at: float = 0.0

        # Mood drift tracking
        self._mood_readings: List[Tuple[float, float]] = []

        # Thread pool for non-blocking DB reads (1 worker — serial reads)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ci_db")

    def sense(self) -> List[Wave]:
        """Read new idle thoughts, classify, emit waves."""
        waves = []
        now = time.time()

        # Rate limit DB checks
        if (now - self._last_db_check) < _DB_CHECK_INTERVAL_S:
            return waves
        self._last_db_check = now

        try:
            # DB read in background thread with 10s hard timeout
            # prevents blocking the Genesis main loop
            try:
                future = self._executor.submit(self._read_new_thoughts)
                new_thoughts = future.result(timeout=10)
            except FuturesTimeout:
                LOG.warning("ConsciousnessInsight DB read timed out after 10s")
                return waves
            if not new_thoughts:
                return waves

            LOG.info("Read %d new idle thought(s) from consciousness.db",
                     len(new_thoughts))

            # Refresh goals cache periodically (with timeout)
            if (now - self._goals_refreshed_at) > _GOALS_REFRESH_S:
                try:
                    future = self._executor.submit(self._refresh_goals)
                    future.result(timeout=5)
                except FuturesTimeout:
                    LOG.debug("Goals refresh timed out, using cached")
                self._goals_refreshed_at = now

            # Classify each thought and emit waves
            for thought in new_thoughts:
                categories = self._classify(thought["content"])
                if not categories:
                    continue

                mood_delta = thought.get("mood_after", 0) - \
                    thought.get("mood_before", 0)

                # Track mood
                self._mood_readings.append(
                    (thought["timestamp"], thought.get("mood_after", 0)))
                if len(self._mood_readings) > 20:
                    self._mood_readings = self._mood_readings[-20:]

                # Store classified insight for observation generation
                self._recent_insights.append({
                    "content": thought["content"],
                    "timestamp": thought["timestamp"],
                    "categories": categories,
                    "mood_delta": mood_delta,
                })

                LOG.debug("Classified thought → %s: %.60s",
                          categories, thought["content"])

                # Emit waves per category (with cooldown)
                for cat in categories:
                    cat_def = _CATEGORIES[cat]
                    last_wave = self._last_wave_ts.get(cat, 0)
                    if (now - last_wave) < _WAVE_COOLDOWN_S:
                        continue

                    amplitude = cat_def["wave_amplitude"]
                    # Stronger when mood drops for emotional categories
                    if cat in ("emotional_conflict", "stagnation_awareness"):
                        if mood_delta < -0.02:
                            amplitude = min(0.5, amplitude * 1.5)

                    waves.append(Wave(
                        target_field=cat_def["wave_field"],
                        amplitude=amplitude,
                        decay=cat_def["wave_decay"],
                        source=self.name,
                        metadata={
                            "category": cat,
                            "thought_preview": thought["content"][:80],
                            "mood_delta": round(mood_delta, 4),
                        },
                    ))
                    self._last_wave_ts[cat] = now

            # Sustained mood drift detection
            drift_wave = self._detect_mood_drift()
            if drift_wave:
                waves.append(drift_wave)

            # Goal alignment signal
            goal_wave = self._check_goal_alignment(new_thoughts)
            if goal_wave:
                waves.append(goal_wave)

            # Trim old insights (keep last 24h)
            cutoff_ts = now - 86400
            self._recent_insights = [
                i for i in self._recent_insights if i["timestamp"] > cutoff_ts
            ]

        except Exception as e:
            LOG.warning("ConsciousnessInsight sensing error: %s", e)

        return waves

    def get_observations(self) -> List[Dict[str, Any]]:
        """Generate observations from recent classified insights."""
        observations = []

        if not self._recent_insights:
            return observations

        # Group by category to find recurring themes
        category_insights: Dict[str, List[Dict]] = {}
        for insight in self._recent_insights:
            for cat in insight["categories"]:
                category_insights.setdefault(cat, []).append(insight)

        for cat_name, insights in category_insights.items():
            cat_def = _CATEGORIES[cat_name]

            # Use most recent insight as representative
            latest = insights[-1]
            content_preview = latest["content"][:120]

            # Target with ":" for quality gate compliance
            target = f"{cat_def['obs_target_prefix']}:{cat_name}"

            # Strength scales with recurrence
            strength = min(1.0, 0.3 + len(insights) * 0.15)

            # Impact scales with mood impact
            avg_mood_delta = sum(
                i["mood_delta"] for i in insights) / len(insights)
            impact = min(1.0, 0.4 + abs(avg_mood_delta) * 5)

            obs = {
                "type": cat_def["obs_type"],
                "target": target,
                "approach": cat_def["obs_approach"],
                "origin": "consciousness_insight",
                "strength": round(strength, 3),
                "novelty": 0.6,
                "risk": 0.2,
                "impact": round(impact, 3),
                "check": f"consciousness_{cat_name}",
                "metric": f"{len(insights)} insight(s) in '{cat_name}'",
                "evidence": f"Self-insight: {content_preview}",
                "detail": content_preview,
            }

            # Goal-aligned observations get boosted
            if self._is_goal_aligned(cat_name, content_preview):
                obs["strength"] = min(1.0, obs["strength"] + 0.2)
                obs["impact"] = min(1.0, obs["impact"] + 0.15)

            observations.append(obs)

            if len(observations) >= _MAX_OBSERVATIONS_PER_TICK:
                break

        # ── Skill observations from growth_aspiration ──────────────
        # Growth insights also seed skill-type organisms in Genesis.
        # Template is intentionally rigid so the 8B model can produce
        # actionable proposals.
        if "growth_aspiration" in category_insights and \
                len(observations) < _MAX_OBSERVATIONS_PER_TICK:
            growth_insights = category_insights["growth_aspiration"]
            latest_growth = growth_insights[-1]
            skill_target = self._extract_skill_target(latest_growth["content"])
            if skill_target:
                observations.append({
                    "type": "skill",
                    "target": f"skill:{skill_target}",
                    "approach": "learn_skill",
                    "origin": "consciousness_insight",
                    "strength": min(1.0, 0.4 + len(growth_insights) * 0.15),
                    "novelty": 0.7,
                    "risk": 0.15,
                    "impact": 0.6,
                    "check": "consciousness_skill_aspiration",
                    "metric": f"{len(growth_insights)} growth insight(s)",
                    "evidence": (
                        f"SKILL_NAME: {skill_target}\n"
                        f"TRIGGER: Franks Selbstreflexion\n"
                        f"CONTEXT: {latest_growth['content'][:200]}\n"
                        f"ACTION: Implementiere oder verbessere '{skill_target}' "
                        f"als neues Tool, Config-Anpassung oder Code-Erweiterung."
                    ),
                    "detail": (
                        f"Frank möchte '{skill_target}' lernen/verbessern. "
                        f"Quelle: idle thought Analyse."
                    ),
                })
                LOG.info("Emitted skill observation: %s", skill_target)

        # Keep only most recent insight per category-set to prevent re-emission
        seen_cats = set()
        kept = []
        for insight in reversed(self._recent_insights):
            cats_key = frozenset(insight["categories"])
            if cats_key not in seen_cats:
                seen_cats.add(cats_key)
                kept.append(insight)
        self._recent_insights = list(reversed(kept))

        return observations

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _read_new_thoughts(self) -> List[Dict]:
        """Read new idle reflections since last read. Read-only."""
        thoughts = []
        db_path = Path(CONSCIOUSNESS_DB)

        if not db_path.exists():
            return thoughts

        try:
            conn = sqlite3.connect(str(db_path), timeout=5)
            conn.row_factory = sqlite3.Row

            cursor = conn.execute(
                "SELECT content, timestamp, mood_before, mood_after, "
                "reflection_depth "
                "FROM reflections "
                "WHERE trigger = 'idle' AND timestamp > ? "
                "ORDER BY timestamp ASC "
                "LIMIT ?",
                (self._last_read_ts, _MAX_INSIGHTS_PER_READ),
            )

            for row in cursor:
                thoughts.append({
                    "content": row["content"] or "",
                    "timestamp": row["timestamp"],
                    "mood_before": row["mood_before"] or 0.0,
                    "mood_after": row["mood_after"] or 0.0,
                    "depth": row["reflection_depth"] or 1,
                })

            # Update watermark
            if thoughts:
                self._last_read_ts = thoughts[-1]["timestamp"]

            conn.close()

        except sqlite3.OperationalError as e:
            LOG.debug("consciousness.db busy, will retry: %s", e)
        except Exception as e:
            LOG.warning("Error reading consciousness.db: %s", e)

        return thoughts

    def _classify(self, content: str) -> List[str]:
        """Classify a thought into categories via keyword matching.

        Returns list of matching category names.
        A thought can match multiple categories.
        """
        matches = []

        for cat_name, patterns in self._compiled_patterns.items():
            for pattern in patterns:
                if pattern.search(content):
                    matches.append(cat_name)
                    break  # One match per category is enough

        return matches

    def _detect_mood_drift(self) -> Optional[Wave]:
        """Detect sustained mood drift across recent thoughts."""
        if len(self._mood_readings) < 3:
            return None

        n = len(self._mood_readings)
        third = max(1, n // 3)
        early_avg = sum(m for _, m in self._mood_readings[:third]) / third
        late_avg = sum(m for _, m in self._mood_readings[-third:]) / third
        drift = late_avg - early_avg

        if abs(drift) < 0.03:
            return None

        if drift < 0:
            return Wave(
                target_field="concern",
                amplitude=min(0.3, abs(drift) * 3),
                decay=0.05,
                source=self.name,
                metadata={"mood_drift": round(drift, 4),
                          "direction": "declining"},
            )
        else:
            return Wave(
                target_field="satisfaction",
                amplitude=min(0.2, drift * 2),
                decay=0.03,
                source=self.name,
                metadata={"mood_drift": round(drift, 4),
                          "direction": "improving"},
            )

    def _refresh_goals(self):
        """Refresh active goals from consciousness.db."""
        db_path = Path(CONSCIOUSNESS_DB)
        if not db_path.exists():
            return

        try:
            conn = sqlite3.connect(str(db_path), timeout=5)
            conn.row_factory = sqlite3.Row

            rows = conn.execute(
                "SELECT description, category, priority, activation "
                "FROM goals WHERE status = 'active' "
                "ORDER BY priority DESC LIMIT 10"
            ).fetchall()

            self._active_goals = [
                {
                    "description": (row["description"] or "").lower(),
                    "category": row["category"] or "general",
                    "priority": row["priority"] or 0.5,
                    "activation": row["activation"] or 0.0,
                }
                for row in rows
            ]

            conn.close()

        except Exception as e:
            LOG.debug("Error refreshing goals: %s", e)

    def _is_goal_aligned(self, category: str, content: str) -> bool:
        """Check if an insight aligns with an active goal."""
        if not self._active_goals:
            return False

        content_words = set(content.lower().split())

        for goal in self._active_goals:
            # Category alignment
            if _GOAL_CAT_MAP.get(category) == goal["category"]:
                return True

            # Keyword overlap (at least 2 shared words)
            goal_words = set(goal["description"].split())
            if len(goal_words & content_words) >= 2:
                return True

        return False

    def _extract_skill_target(self, content: str) -> Optional[str]:
        """Extract a skill target from thought content.

        Uses regex patterns to find what Frank wants to learn/improve.
        Returns cleaned skill name or None if no clear skill found.
        """
        for pattern in _SKILL_EXTRACT_PATTERNS:
            match = pattern.search(content)
            if match:
                raw = match.group(1).strip().lower()
                # Remove noise words
                words = [w for w in raw.split() if w not in _SKILL_NOISE]
                if words:
                    skill = " ".join(words[:4])  # Cap at 4 words
                    if len(skill) >= 3:
                        return skill

        # Fallback: if content mentions known skill domains, use those
        _KNOWN_DOMAINS = {
            "conversation": ["conversation", "dialog", "chat", "gesprächs"],
            "code_analysis": ["code", "analyse", "analysis", "parsing", "ast"],
            "emotional_intelligence": ["empathy", "emotional", "gefühl", "einfühl"],
            "tool_creation": ["tool", "werkzeug", "automation", "automat"],
            "memory_management": ["memory", "erinnerung", "speicher", "recall"],
            "creativity": ["creative", "kreativ", "imaginat", "phantas"],
            "self_awareness": ["self-aware", "bewusst", "introspect", "meta-cognit"],
        }
        content_lower = content.lower()
        for domain, keywords in _KNOWN_DOMAINS.items():
            if any(kw in content_lower for kw in keywords):
                return domain

        return None

    def _check_goal_alignment(self, thoughts: List[Dict]) -> Optional[Wave]:
        """Emit drive wave when thoughts align with active goals."""
        if not self._active_goals or not thoughts:
            return None

        aligned = 0
        for thought in thoughts:
            categories = self._classify(thought["content"])
            for cat in categories:
                if self._is_goal_aligned(cat, thought["content"]):
                    aligned += 1
                    break

        if aligned == 0:
            return None

        return Wave(
            target_field="drive",
            amplitude=min(0.35, 0.15 + aligned * 0.1),
            decay=0.04,
            source=self.name,
            metadata={"goal_aligned_insights": aligned,
                      "active_goals": len(self._active_goals)},
        )
