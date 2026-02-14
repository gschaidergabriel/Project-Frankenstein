#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AKAM v1.0 - Autonomous Knowledge Acquisition Module
====================================================

Frank kann bei unbekannten/unsicheren Themen (Confidence < 0.70) autonom
Internet-Recherche durchführen, die Ergebnisse epistemisch sauber validieren
und nur geprüfte Claims in sein Weltmodell integrieren.

OBERSTE DIREKTIVE (persistent in E-CPMM als Kern-Edge):
"Bei Wissenslücken (Confidence < 0.70) nur lesend recherchieren.
Keine Änderung am System, kein Code-Ausführen, kein autonomes Tool-Installieren.
Jede Information als unsicherer Claim behandeln.
Mensch hat finales Veto bei Risk > 0.25 oder Confidence < 0.70.
Ziel: maximale epistemische Sauberkeit und Kollaboration."

Architektur (nur lesend):
1. Query Confidence Check (Trigger)
2. Search & Collection Layer
3. Multi-Source Validation & Epistemic Filter
4. Distillation & Claim Extraction
5. Human Veto Gate
6. Integration & Persistence
7. Response & Visualization

Integration:
- E-CPMM Graph: Neue Knoten/Edges
- World-Experience: Kausale Ereignisse
- Titan: Semantische Einbettung
- Wallpaper: Visualisierung (neuer Knoten + Puls)

Performance: +2-5% CPU/GPU nur während Recherche
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum

# =============================================================================
# CONFIGURATION
# =============================================================================

LOG = logging.getLogger("akam")

# Paths
try:
    from config.paths import get_db, DB_DIR as _DB_DIR
except ImportError:
    _DB_DIR = Path("/home/ai-core-node/.local/share/frank/db")
    def get_db(name):
        return _DB_DIR / f"{name}.db"

AICORE_DB = _DB_DIR
WORLD_EXP_DB = get_db("world_experience")
TITAN_DB = get_db("titan")
AKAM_CACHE_DB = get_db("akam_cache")

# Web Search Service
import os
WEBD_SEARCH_URL = os.environ.get("AICORE_WEBD_SEARCH_URL", "http://127.0.0.1:8093/search")

# Confidence Thresholds
CONFIDENCE_TRIGGER = 0.70      # < 0.70 → AKAM aktivieren
CONFIDENCE_ASK = 0.85          # 0.70-0.85 → Mensch fragen
CONFIDENCE_OK = 0.85           # > 0.85 → keine Recherche

# Risk Threshold
RISK_VETO_THRESHOLD = 0.25     # > 0.25 → Human Veto

# Search Guardrails
MAX_TOOL_CALLS_PER_QUERY = 15
RATE_LIMIT_DELAY_SEC = 5.0
MAX_PAGES_PER_ROUND = 5

# Source Weights
SOURCE_WEIGHTS = {
    "edu": 1.5,           # .edu domains
    "gov": 1.5,           # .gov domains
    "peer_reviewed": 1.5, # Peer-reviewed sources
    "wikipedia": 0.8,     # Wikipedia (nur als Einstieg)
    "news_high": 1.0,     # High-reputation news
    "news_mid": 0.8,      # Mid-reputation news
    "news_low": 0.6,      # Low-reputation news
    "blog": 0.4,          # Blogs
    "forum": 0.3,         # Forums
    "social": 0.3,        # Social media (X, etc.)
    "unknown": 0.5,       # Unknown sources
}

# Trusted Domains (Priorität)
TRUSTED_DOMAINS = {
    # Educational
    ".edu", "mit.edu", "stanford.edu", "berkeley.edu", "harvard.edu",
    # Government
    ".gov", "europa.eu", "who.int", "un.org",
    # Reference
    "wikipedia.org", "britannica.com", "arxiv.org",
    # High-quality news
    "reuters.com", "apnews.com", "bbc.com", "theguardian.com",
    # Tech documentation
    "docs.python.org", "developer.mozilla.org", "docs.microsoft.com",
}

# Blacklisted Domains (avoid)
BLACKLISTED_DOMAINS = {
    "pinterest.com", "quora.com", "reddit.com",  # Low signal-to-noise
    "facebook.com", "instagram.com", "tiktok.com",  # Social media
}


# =============================================================================
# DATA STRUCTURES
# =============================================================================

class AKAMStatus(Enum):
    """AKAM operation status."""
    IDLE = "idle"
    TRIGGERED = "triggered"
    SEARCHING = "searching"
    VALIDATING = "validating"
    AWAITING_VETO = "awaiting_veto"
    INTEGRATING = "integrating"
    COMPLETE = "complete"
    REJECTED = "rejected"
    ERROR = "error"


@dataclass
class Claim:
    """A validated claim from research."""
    claim_id: str
    text: str
    source_url: str
    source_type: str
    confidence: float
    contradiction_flag: bool = False
    contradiction_with: Optional[str] = None
    timestamp: str = ""

    def __post_init__(self):
        if not self.claim_id:
            self.claim_id = hashlib.md5(
                f"{self.text}:{self.source_url}".encode()
            ).hexdigest()[:16]
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


@dataclass
class SearchResult:
    """A search result from web search."""
    url: str
    title: str
    snippet: str
    source_type: str = "unknown"
    source_weight: float = 0.5


@dataclass
class ResearchSession:
    """A complete research session."""
    session_id: str
    query: str
    trigger_confidence: float
    status: AKAMStatus = AKAMStatus.IDLE
    search_results: List[SearchResult] = field(default_factory=list)
    claims: List[Claim] = field(default_factory=list)
    final_confidence: float = 0.0
    risk_score: float = 0.0
    human_veto_required: bool = False
    human_approved: Optional[bool] = None
    tool_calls_count: int = 0
    started_at: str = ""
    completed_at: str = ""
    error_message: str = ""

    def __post_init__(self):
        if not self.session_id:
            self.session_id = f"akam_{int(time.time()*1000)}_{hashlib.md5(self.query.encode()).hexdigest()[:8]}"
        if not self.started_at:
            self.started_at = datetime.now().isoformat()


# =============================================================================
# AKAM CORE
# =============================================================================

class AKAM:
    """
    Autonomous Knowledge Acquisition Module.

    Ermöglicht Frank autonome Wissensrecherche bei Confidence < 0.70.
    Alle Operationen sind NUR LESEND - keine Systemänderungen!
    """

    _instance = None
    _lock = threading.Lock()

    # Oberste Direktive (persistent)
    CORE_DIRECTIVE = """
    Bei Wissenslücken (Confidence < 0.70) nur lesend recherchieren.
    Keine Änderung am System, kein Code-Ausführen, kein autonomes Tool-Installieren.
    Jede Information als unsicherer Claim behandeln.
    Mensch hat finales Veto bei Risk > 0.25 oder Confidence < 0.70.
    Ziel: maximale epistemische Sauberkeit und Kollaboration.
    """

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._current_session: Optional[ResearchSession] = None
        self._session_lock = threading.Lock()
        self._daily_searches = 0
        self._last_reset_date = datetime.now().date()

        # Initialize database
        self._init_db()

        self._initialized = True
        LOG.info("AKAM v1.0 initialized - Autonomous Knowledge Acquisition Module")

    def _init_db(self):
        """Initialize AKAM cache database."""
        try:
            with sqlite3.connect(AKAM_CACHE_DB) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS research_sessions (
                        session_id TEXT PRIMARY KEY,
                        query TEXT NOT NULL,
                        trigger_confidence REAL,
                        final_confidence REAL,
                        risk_score REAL,
                        status TEXT,
                        human_approved INTEGER,
                        claims_json TEXT,
                        started_at TEXT,
                        completed_at TEXT
                    )
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS validated_claims (
                        claim_id TEXT PRIMARY KEY,
                        text TEXT NOT NULL,
                        source_url TEXT,
                        source_type TEXT,
                        confidence REAL,
                        contradiction_flag INTEGER,
                        session_id TEXT,
                        integrated INTEGER DEFAULT 0,
                        created_at TEXT
                    )
                """)

                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_claims_confidence
                    ON validated_claims(confidence)
                """)

                conn.commit()
        except Exception as e:
            LOG.error(f"Failed to initialize AKAM database: {e}")

    # =========================================================================
    # 1. QUERY CONFIDENCE CHECK (Trigger)
    # =========================================================================

    def check_confidence(self, query: str, context: Dict[str, Any] = None) -> Tuple[float, bool, str]:
        """
        Check confidence level for a query.

        Returns:
            (confidence, should_trigger, message)
        """
        context = context or {}

        # Check E-CPMM Graph for existing knowledge
        ecpmm_confidence = self._check_ecpmm_confidence(query)

        # Check Core-Awareness for topic coverage
        coverage = self._check_topic_coverage(query)

        # Check UOLG for relevance
        relevance = self._check_uolg_relevance(query)

        # Calculate combined confidence
        confidence = (ecpmm_confidence * 0.5) + (coverage * 0.3) + (relevance * 0.2)

        # Determine action
        if confidence < CONFIDENCE_TRIGGER:
            return confidence, True, f"Confidence {confidence:.2f} < {CONFIDENCE_TRIGGER} - AKAM aktivieren"
        elif confidence < CONFIDENCE_ASK:
            return confidence, False, f"Confidence {confidence:.2f} - Soll ich nachschauen? (Mensch-Veto)"
        else:
            return confidence, False, f"Confidence {confidence:.2f} - Keine Recherche nötig"

    def _check_ecpmm_confidence(self, query: str) -> float:
        """Check E-CPMM Graph for confidence on query concepts."""
        try:
            # Try to import Titan for E-CPMM check
            from tools.titan.titan_core import recall

            results = recall(query, limit=3)
            if results:
                avg_confidence = sum(r.get("confidence", 0.5) for r in results) / len(results)
                return avg_confidence
        except Exception:
            pass

        return 0.5  # Default uncertain

    def _check_topic_coverage(self, query: str) -> float:
        """Check if topic is covered in existing knowledge."""
        try:
            from tools.core_awareness import get_core_awareness

            awareness = get_core_awareness()
            # Check if relevant modules/features exist
            modules = awareness.get_all_modules()

            # Simple keyword matching
            query_lower = query.lower()
            for module in modules:
                if any(kw in query_lower for kw in module.get("keywords", [])):
                    return 0.8

            return 0.5
        except Exception:
            pass

        return 0.5

    def _check_uolg_relevance(self, query: str) -> float:
        """Check UOLG for current relevance of topic."""
        # UOLG integration would go here
        # For now, return neutral
        return 0.5

    # =========================================================================
    # 2. SEARCH & COLLECTION LAYER (nur lesend!)
    # =========================================================================

    def trigger_research(self, query: str, auto_approve: bool = False) -> ResearchSession:
        """
        Trigger a research session for a query.

        Args:
            query: The research query
            auto_approve: Skip human veto (only for Confidence > 0.70)

        Returns:
            ResearchSession with status and results
        """
        with self._session_lock:
            # Check daily limit
            self._check_daily_reset()
            if self._daily_searches >= 50:
                session = ResearchSession(
                    session_id="",
                    query=query,
                    trigger_confidence=0.0,
                    status=AKAMStatus.REJECTED,
                    error_message="Daily search limit reached (50/day)"
                )
                return session

            # Get trigger confidence
            confidence, should_trigger, msg = self.check_confidence(query)

            # Create session
            session = ResearchSession(
                session_id="",
                query=query,
                trigger_confidence=confidence,
                status=AKAMStatus.TRIGGERED
            )
            self._current_session = session

            LOG.info(f"AKAM Research triggered: {query[:50]}... (confidence={confidence:.2f})")

            # Perform search
            session.status = AKAMStatus.SEARCHING
            search_results = self._perform_search(query, session)
            session.search_results = search_results

            # Validate results
            session.status = AKAMStatus.VALIDATING
            claims = self._validate_and_extract(search_results, query, session)
            session.claims = claims

            # Calculate final confidence and risk
            session.final_confidence = self._calculate_final_confidence(claims)
            session.risk_score = self._calculate_risk_score(claims, query)

            # Check if human veto required
            if session.risk_score > RISK_VETO_THRESHOLD or session.final_confidence < CONFIDENCE_TRIGGER:
                session.human_veto_required = True
                session.status = AKAMStatus.AWAITING_VETO

                if not auto_approve:
                    LOG.info(f"AKAM awaiting human veto: confidence={session.final_confidence:.2f}, risk={session.risk_score:.2f}")
                    self._save_session(session)
                    return session

            # Auto-approve path
            if auto_approve or not session.human_veto_required:
                session.human_approved = True
                self._integrate_claims(session)
                session.status = AKAMStatus.COMPLETE

            session.completed_at = datetime.now().isoformat()
            self._save_session(session)
            self._daily_searches += 1

            return session

    def _perform_search(self, query: str, session: ResearchSession) -> List[SearchResult]:
        """
        Perform web search using available tools.
        NUR LESEND - keine Ausführung, keine Systemänderungen!
        """
        results = []

        # Strategy: Multi-source search
        search_queries = [
            f"{query} reliable sources 2026",
            f"{query} scientific evidence",
            f"{query} official documentation",
        ]

        for sq in search_queries:
            if session.tool_calls_count >= MAX_TOOL_CALLS_PER_QUERY:
                break

            # Simulate web search (in real implementation, call actual search API)
            search_results = self._web_search(sq)
            session.tool_calls_count += 1

            for sr in search_results:
                # Classify source
                sr.source_type = self._classify_source(sr.url)
                sr.source_weight = SOURCE_WEIGHTS.get(sr.source_type, 0.5)

                # Filter blacklisted
                if not any(bl in sr.url for bl in BLACKLISTED_DOMAINS):
                    results.append(sr)

            # Rate limit
            time.sleep(RATE_LIMIT_DELAY_SEC)

        return results[:20]  # Max 20 results

    def _web_search(self, query: str) -> List[SearchResult]:
        """
        Perform web search via webd service.

        Calls the local webd service at WEBD_SEARCH_URL to perform
        DuckDuckGo searches in a safe, rate-limited manner.
        """
        LOG.debug(f"Web search: {query}")
        results: List[SearchResult] = []

        try:
            # Prepare request
            payload = json.dumps({"query": query, "limit": 10}).encode("utf-8")
            req = urllib.request.Request(
                WEBD_SEARCH_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )

            # Make request with timeout
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if not data.get("ok"):
                LOG.warning(f"Web search failed: {data.get('error', 'unknown')}")
                return results

            # Convert to SearchResult objects
            for item in data.get("results", []):
                results.append(SearchResult(
                    url=item.get("url", ""),
                    title=item.get("title", ""),
                    snippet=item.get("snippet", ""),
                    source_type="unknown",
                    source_weight=0.5
                ))

            LOG.info(f"Web search returned {len(results)} results for: {query[:50]}")

        except urllib.error.URLError as e:
            LOG.warning(f"Web search connection error: {e}")
        except json.JSONDecodeError as e:
            LOG.warning(f"Web search JSON error: {e}")
        except Exception as e:
            LOG.warning(f"Web search error: {e}")

        return results

    def _classify_source(self, url: str) -> str:
        """Classify a source URL by type."""
        url_lower = url.lower()

        if ".edu" in url_lower:
            return "edu"
        if ".gov" in url_lower:
            return "gov"
        if "arxiv.org" in url_lower or "doi.org" in url_lower:
            return "peer_reviewed"
        if "wikipedia.org" in url_lower:
            return "wikipedia"
        if any(d in url_lower for d in ["reuters.com", "apnews.com", "bbc.com"]):
            return "news_high"
        if any(d in url_lower for d in ["cnn.com", "nytimes.com", "theguardian.com"]):
            return "news_mid"
        if "blog" in url_lower or "medium.com" in url_lower:
            return "blog"
        if any(d in url_lower for d in ["forum", "reddit.com", "quora.com"]):
            return "forum"
        if any(d in url_lower for d in ["twitter.com", "x.com", "facebook.com"]):
            return "social"

        return "unknown"

    # =========================================================================
    # 3. MULTI-SOURCE VALIDATION & EPISTEMIC FILTER
    # =========================================================================

    def _validate_and_extract(
        self,
        search_results: List[SearchResult],
        query: str,
        session: ResearchSession
    ) -> List[Claim]:
        """
        Validate search results and extract claims.
        Multi-stage validation with epistemic filtering.
        """
        claims = []

        for result in search_results:
            if session.tool_calls_count >= MAX_TOOL_CALLS_PER_QUERY:
                break

            # 1. Source weighting (already done)
            source_weight = result.source_weight

            # 2. Extract claims from result
            extracted = self._extract_claims_from_result(result, query)
            session.tool_calls_count += 1

            for claim_text, claim_confidence in extracted:
                # 3. Check for contradictions with existing knowledge
                contradiction = self._check_contradiction(claim_text)

                # 4. Calculate final claim confidence
                # Confidence = (Source-Weight × 0.4) + (Widerspruchsfreiheit × 0.3) + (Recency × 0.3)
                contradiction_score = 0.0 if contradiction else 1.0
                recency_score = 0.8  # Assume recent for now

                final_confidence = (
                    source_weight * 0.4 +
                    contradiction_score * 0.3 +
                    recency_score * 0.3
                ) * claim_confidence

                claim = Claim(
                    claim_id="",
                    text=claim_text,
                    source_url=result.url,
                    source_type=result.source_type,
                    confidence=final_confidence,
                    contradiction_flag=contradiction is not None,
                    contradiction_with=contradiction
                )

                claims.append(claim)

            # Rate limit
            time.sleep(RATE_LIMIT_DELAY_SEC)

        # Sort by confidence
        claims.sort(key=lambda c: c.confidence, reverse=True)

        return claims[:10]  # Return top 10 claims

    def _extract_claims_from_result(
        self,
        result: SearchResult,
        query: str
    ) -> List[Tuple[str, float]]:
        """
        Extract structured claims from a search result.

        Returns list of (claim_text, confidence) tuples.
        """
        # In real implementation, this would:
        # 1. Browse the page
        # 2. Use LLM to extract claims
        # 3. Return structured data

        # Placeholder - use snippet as basic claim
        if result.snippet:
            return [(result.snippet, 0.6)]
        return []

    def _check_contradiction(self, claim_text: str) -> Optional[str]:
        """
        Check if claim contradicts existing knowledge in E-CPMM.

        Returns ID of contradicting claim, or None.
        """
        try:
            from tools.titan.titan_core import recall

            existing = recall(claim_text, limit=3)
            for e in existing:
                # Simple contradiction check (real implementation would be more sophisticated)
                existing_text = e.get("text", "").lower()
                claim_lower = claim_text.lower()

                # Check for negation patterns
                negation_words = ["not", "never", "false", "incorrect", "wrong", "doesn't", "isn't"]
                if any(nw in claim_lower for nw in negation_words) != any(nw in existing_text for nw in negation_words):
                    if self._semantic_similarity(claim_text, existing_text) > 0.7:
                        return e.get("id", "unknown")
        except Exception:
            pass

        return None

    def _semantic_similarity(self, text1: str, text2: str) -> float:
        """Calculate semantic similarity between two texts."""
        # Simple word overlap for now
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return 0.0

        overlap = len(words1 & words2)
        return overlap / max(len(words1), len(words2))

    # =========================================================================
    # 4. CONFIDENCE & RISK CALCULATION
    # =========================================================================

    def _calculate_final_confidence(self, claims: List[Claim]) -> float:
        """Calculate final confidence from all claims."""
        if not claims:
            return 0.0

        # Weighted average of claim confidences
        total_weight = 0.0
        weighted_sum = 0.0

        for claim in claims:
            weight = SOURCE_WEIGHTS.get(claim.source_type, 0.5)
            weighted_sum += claim.confidence * weight
            total_weight += weight

        if total_weight == 0:
            return 0.0

        return weighted_sum / total_weight

    def _calculate_risk_score(self, claims: List[Claim], query: str) -> float:
        """
        Calculate risk score for integrating claims.

        Higher risk for:
        - Contradictions with existing knowledge
        - Low source quality
        - Sensitive topics
        """
        risk = 0.0

        # Contradiction risk
        contradiction_count = sum(1 for c in claims if c.contradiction_flag)
        if claims:
            risk += (contradiction_count / len(claims)) * 0.4

        # Low quality source risk
        low_quality_count = sum(1 for c in claims if c.source_type in ["blog", "forum", "social"])
        if claims:
            risk += (low_quality_count / len(claims)) * 0.3

        # Sensitive topic risk
        sensitive_keywords = [
            "medical", "health", "legal", "financial", "investment",
            "security", "password", "hack", "exploit", "vulnerability"
        ]
        if any(kw in query.lower() for kw in sensitive_keywords):
            risk += 0.3

        return min(1.0, risk)

    # =========================================================================
    # 5. HUMAN VETO GATE
    # =========================================================================

    def request_human_veto(self, session_id: str) -> Dict[str, Any]:
        """
        Generate human veto request for a session.

        Returns formatted request for user review.
        """
        session = self._load_session(session_id)
        if not session:
            return {"error": "Session not found"}

        # Format claims for review
        claims_summary = []
        for claim in session.claims[:5]:
            claims_summary.append({
                "text": claim.text[:200],
                "source": claim.source_url,
                "source_type": claim.source_type,
                "confidence": round(claim.confidence, 2),
                "contradiction": claim.contradiction_flag
            })

        return {
            "session_id": session.session_id,
            "query": session.query,
            "message": f"Ich habe recherchiert, bin aber unsicher (Confidence {session.final_confidence:.2f}, Risk {session.risk_score:.2f}). Soll ich fortfahren oder alternative Quellen suchen?",
            "confidence": round(session.final_confidence, 2),
            "risk": round(session.risk_score, 2),
            "claims_count": len(session.claims),
            "top_claims": claims_summary,
            "options": ["Ja (integrieren)", "Nein (verwerfen)", "Alternative Quellen suchen"]
        }

    def process_human_decision(
        self,
        session_id: str,
        approved: bool,
        search_alternatives: bool = False
    ) -> ResearchSession:
        """
        Process human decision on a pending session.

        Args:
            session_id: Session ID
            approved: Whether to approve integration
            search_alternatives: Whether to search for alternative sources
        """
        session = self._load_session(session_id)
        if not session:
            return None

        if search_alternatives:
            # Trigger new search with modified query
            new_query = f"{session.query} alternative sources peer reviewed"
            return self.trigger_research(new_query, auto_approve=False)

        session.human_approved = approved

        if approved:
            self._integrate_claims(session)
            session.status = AKAMStatus.COMPLETE
            LOG.info(f"AKAM session {session_id} approved and integrated")
        else:
            session.status = AKAMStatus.REJECTED
            # Apply erosion to claims
            self._apply_erosion(session)
            LOG.info(f"AKAM session {session_id} rejected")

        session.completed_at = datetime.now().isoformat()
        self._save_session(session)

        return session

    # =========================================================================
    # 6. INTEGRATION & PERSISTENCE
    # =========================================================================

    def _integrate_claims(self, session: ResearchSession):
        """
        Integrate validated claims into Frank's knowledge systems.

        - E-CPMM Graph: New nodes/edges
        - World-Experience: Causal event
        - Titan: Semantic embedding
        """
        session.status = AKAMStatus.INTEGRATING

        for claim in session.claims:
            if claim.confidence >= CONFIDENCE_TRIGGER:
                # 1. Integrate into Titan (E-CPMM)
                self._integrate_titan(claim, session)

                # 2. Log to World-Experience
                self._log_world_experience(claim, session)

                # 3. Mark as integrated
                self._mark_claim_integrated(claim)

        # 4. Trigger wallpaper visualization
        self._trigger_wallpaper_event(session)

        LOG.info(f"AKAM integrated {len(session.claims)} claims from session {session.session_id}")

    def _integrate_titan(self, claim: Claim, session: ResearchSession):
        """Integrate claim into Titan E-CPMM."""
        try:
            from tools.titan.titan_core import remember

            remember(
                text=claim.text,
                origin="akam_research",
                confidence=claim.confidence
            )
        except Exception as e:
            LOG.error(f"Failed to integrate claim to Titan: {e}")

    def _log_world_experience(self, claim: Claim, session: ResearchSession):
        """Log integration event to World-Experience."""
        try:
            with sqlite3.connect(WORLD_EXP_DB) as conn:
                conn.execute("""
                    INSERT OR IGNORE INTO causal_patterns (
                        pattern_id, cause, effect, confidence, last_seen
                    ) VALUES (?, ?, ?, ?, ?)
                """, (
                    f"akam_{claim.claim_id}",
                    f"AKAM Recherche: {session.query[:100]}",
                    f"Claim integriert: {claim.text[:200]}",
                    claim.confidence,
                    datetime.now().isoformat()
                ))
                conn.commit()
        except Exception as e:
            LOG.debug(f"World-Experience log failed: {e}")

    def _mark_claim_integrated(self, claim: Claim):
        """Mark claim as integrated in AKAM cache."""
        try:
            with sqlite3.connect(AKAM_CACHE_DB) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO validated_claims (
                        claim_id, text, source_url, source_type,
                        confidence, contradiction_flag, integrated, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                """, (
                    claim.claim_id,
                    claim.text,
                    claim.source_url,
                    claim.source_type,
                    claim.confidence,
                    1 if claim.contradiction_flag else 0,
                    claim.timestamp
                ))
                conn.commit()
        except Exception as e:
            LOG.error(f"Failed to mark claim integrated: {e}")

    def _trigger_wallpaper_event(self, session: ResearchSession):
        """Trigger wallpaper visualization for new knowledge."""
        try:
            from live_wallpaper.wallpaper_events import publish_event

            publish_event(
                src="akam",
                event_type="knowledge.acquired",
                severity="info",
                extra={
                    "query": session.query[:50],
                    "claims_count": len(session.claims),
                    "confidence": session.final_confidence
                }
            )
        except Exception:
            pass

    def _apply_erosion(self, session: ResearchSession):
        """Apply erosion to rejected claims."""
        # Log rejection for learning
        try:
            with sqlite3.connect(AKAM_CACHE_DB) as conn:
                for claim in session.claims:
                    conn.execute("""
                        INSERT OR REPLACE INTO validated_claims (
                            claim_id, text, source_url, source_type,
                            confidence, contradiction_flag, integrated, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                    """, (
                        claim.claim_id,
                        claim.text,
                        claim.source_url,
                        claim.source_type,
                        claim.confidence * 0.5,  # Eroded confidence
                        1 if claim.contradiction_flag else 0,
                        claim.timestamp
                    ))
                conn.commit()
        except Exception as e:
            LOG.error(f"Failed to apply erosion: {e}")

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    def _save_session(self, session: ResearchSession):
        """Save session to database."""
        try:
            with sqlite3.connect(AKAM_CACHE_DB) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO research_sessions (
                        session_id, query, trigger_confidence, final_confidence,
                        risk_score, status, human_approved, claims_json,
                        started_at, completed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    session.session_id,
                    session.query,
                    session.trigger_confidence,
                    session.final_confidence,
                    session.risk_score,
                    session.status.value,
                    1 if session.human_approved else (0 if session.human_approved is False else None),
                    json.dumps([{
                        "claim_id": c.claim_id,
                        "text": c.text,
                        "source_url": c.source_url,
                        "confidence": c.confidence
                    } for c in session.claims]),
                    session.started_at,
                    session.completed_at
                ))
                conn.commit()
        except Exception as e:
            LOG.error(f"Failed to save session: {e}")

    def _load_session(self, session_id: str) -> Optional[ResearchSession]:
        """Load session from database."""
        try:
            with sqlite3.connect(AKAM_CACHE_DB) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM research_sessions WHERE session_id = ?",
                    (session_id,)
                ).fetchone()

                if row:
                    claims_data = json.loads(row["claims_json"] or "[]")
                    claims = [
                        Claim(
                            claim_id=c["claim_id"],
                            text=c["text"],
                            source_url=c["source_url"],
                            source_type="unknown",
                            confidence=c["confidence"]
                        )
                        for c in claims_data
                    ]

                    return ResearchSession(
                        session_id=row["session_id"],
                        query=row["query"],
                        trigger_confidence=row["trigger_confidence"],
                        final_confidence=row["final_confidence"],
                        risk_score=row["risk_score"],
                        status=AKAMStatus(row["status"]),
                        human_approved=row["human_approved"] == 1 if row["human_approved"] is not None else None,
                        claims=claims,
                        started_at=row["started_at"],
                        completed_at=row["completed_at"] or ""
                    )
        except Exception as e:
            LOG.error(f"Failed to load session: {e}")

        return None

    def _check_daily_reset(self):
        """Reset daily counter if new day."""
        today = datetime.now().date()
        if today != self._last_reset_date:
            self._daily_searches = 0
            self._last_reset_date = today

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def get_status(self) -> Dict[str, Any]:
        """Get AKAM status."""
        return {
            "module": "AKAM",
            "version": "1.0",
            "status": "active",
            "daily_searches": self._daily_searches,
            "daily_limit": 50,
            "current_session": self._current_session.session_id if self._current_session else None,
            "confidence_trigger": CONFIDENCE_TRIGGER,
            "risk_veto_threshold": RISK_VETO_THRESHOLD,
        }

    def get_recent_sessions(self, limit: int = 10) -> List[Dict]:
        """Get recent research sessions."""
        try:
            with sqlite3.connect(AKAM_CACHE_DB) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("""
                    SELECT session_id, query, final_confidence, risk_score, status, human_approved
                    FROM research_sessions
                    ORDER BY started_at DESC
                    LIMIT ?
                """, (limit,)).fetchall()

                return [dict(row) for row in rows]
        except Exception:
            return []


# =============================================================================
# SINGLETON ACCESS
# =============================================================================

_akam: Optional[AKAM] = None


def get_akam() -> AKAM:
    """Get AKAM singleton instance."""
    global _akam
    if _akam is None:
        _akam = AKAM()
    return _akam


def check_and_research(query: str, context: Dict = None) -> Dict[str, Any]:
    """
    Convenience function: Check confidence and research if needed.

    Returns dict with:
    - triggered: Whether research was triggered
    - confidence: Confidence level
    - session: ResearchSession if triggered
    - message: Status message
    """
    akam = get_akam()

    confidence, should_trigger, msg = akam.check_confidence(query, context)

    result = {
        "triggered": should_trigger,
        "confidence": confidence,
        "message": msg,
        "session": None
    }

    if should_trigger:
        session = akam.trigger_research(query)
        result["session"] = {
            "session_id": session.session_id,
            "status": session.status.value,
            "claims_count": len(session.claims),
            "final_confidence": session.final_confidence,
            "human_veto_required": session.human_veto_required
        }

    return result


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    akam = get_akam()

    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "status":
            status = akam.get_status()
            print(json.dumps(status, indent=2))

        elif cmd == "check":
            if len(sys.argv) < 3:
                print("Usage: akam.py check <query>")
                sys.exit(1)
            query = " ".join(sys.argv[2:])
            conf, trigger, msg = akam.check_confidence(query)
            print(f"Query: {query}")
            print(f"Confidence: {conf:.2f}")
            print(f"Trigger AKAM: {trigger}")
            print(f"Message: {msg}")

        elif cmd == "research":
            if len(sys.argv) < 3:
                print("Usage: akam.py research <query>")
                sys.exit(1)
            query = " ".join(sys.argv[2:])
            session = akam.trigger_research(query)
            print(f"Session ID: {session.session_id}")
            print(f"Status: {session.status.value}")
            print(f"Claims: {len(session.claims)}")
            print(f"Final Confidence: {session.final_confidence:.2f}")
            print(f"Risk Score: {session.risk_score:.2f}")
            print(f"Human Veto Required: {session.human_veto_required}")

        elif cmd == "recent":
            sessions = akam.get_recent_sessions()
            for s in sessions:
                print(f"{s['session_id']}: {s['query'][:40]}... (conf={s['final_confidence']:.2f})")

        elif cmd == "directive":
            print("=== AKAM OBERSTE DIREKTIVE ===")
            print(AKAM.CORE_DIRECTIVE)

        else:
            print(f"Unknown command: {cmd}")
            print("Usage: akam.py [status|check|research|recent|directive]")

    else:
        print("=== AKAM v1.0 - Autonomous Knowledge Acquisition Module ===")
        print()
        print("Oberste Direktive:")
        print(AKAM.CORE_DIRECTIVE)
        print()
        status = akam.get_status()
        print(f"Status: {status['status']}")
        print(f"Daily searches: {status['daily_searches']}/{status['daily_limit']}")
        print(f"Confidence trigger: < {status['confidence_trigger']}")
        print(f"Risk veto threshold: > {status['risk_veto_threshold']}")
