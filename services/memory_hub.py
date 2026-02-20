"""
MemoryHub — Unified query interface across all memory layers.

Replaces ad-hoc query code in chat_mixin.py with a single `query()` call
that searches all memory layers, applies RRF fusion, and packs results
into a budget-constrained MemoryResult with source attribution.

Memory layers:
  1. Chat History (FTS5 + vector hybrid search)
  2. Titan (knowledge graph + vector + FTS)
  3. Consciousness (ACT-R activation-based retrieval)
  4. World Experience (causal patterns)
  5. User Preferences (learned user prefs)

Author: Projekt Frankenstein — Phase 6
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

LOG = logging.getLogger("memory_hub")


@dataclass
class MemoryItem:
    """Single memory retrieval result with source attribution."""
    text: str
    source: str          # 'chat_fts', 'chat_vector', 'titan', 'consciousness', 'world_exp', 'preference'
    confidence: float
    timestamp: float     # Unix timestamp (unified)
    rrf_score: float = 0.0
    pack_score: float = 0.0


@dataclass
class MemoryResult:
    """Aggregated result from unified memory query."""
    items: List[MemoryItem] = field(default_factory=list)
    total_chars: int = 0
    sources_used: Dict[str, int] = field(default_factory=dict)
    latency_ms: float = 0.0


class MemoryHub:
    """Unified query interface across all memory layers."""

    def __init__(self):
        self._chat_db = None
        self._titan = None

    def _get_chat_db(self):
        if self._chat_db is None:
            try:
                from services.chat_memory import ChatMemoryDB
                self._chat_db = ChatMemoryDB()
            except Exception as e:
                LOG.debug("Chat memory unavailable: %s", e)
        return self._chat_db

    def _get_titan(self):
        if self._titan is None:
            try:
                from tools.titan.titan_core import get_titan
                self._titan = get_titan()
            except Exception as e:
                LOG.debug("Titan unavailable: %s", e)
        return self._titan

    def query(
        self,
        text: str,
        budget_chars: int = 1000,
        source_attribution: bool = True,
    ) -> MemoryResult:
        """Unified query across all memory layers with RRF fusion.

        Args:
            text: Query text (user message).
            budget_chars: Maximum total characters in result.
            source_attribution: Whether to include source labels.

        Returns:
            MemoryResult with fused, budget-packed items.
        """
        start = time.time()
        all_items: List[MemoryItem] = []

        # 1. Chat history (hybrid FTS5 + vector)
        all_items.extend(self._query_chat(text))

        # 2. Titan episodic memory
        all_items.extend(self._query_titan(text))

        # 3. Consciousness (ACT-R retrieval)
        all_items.extend(self._query_consciousness(text))

        # 4. World experience (causal patterns)
        all_items.extend(self._query_world_exp(text))

        # 5. User preferences
        all_items.extend(self._query_preferences(text))

        # RRF fusion across all sources
        fused = self._reciprocal_rank_fusion(all_items)

        # Greedy packing with recency penalty
        result = self._pack_to_budget(fused, budget_chars)
        result.latency_ms = (time.time() - start) * 1000

        # Auto-record metrics
        try:
            import hashlib
            query_hash = hashlib.md5(text.encode()).hexdigest()[:12]
            db = self._get_chat_db()
            if db:
                db.record_retrieval_metric(
                    query_hash=query_hash,
                    sources_used=result.sources_used,
                    chars_injected=result.total_chars,
                    budget_chars=budget_chars,
                    latency_ms=result.latency_ms,
                )
        except Exception:
            pass

        return result

    def _query_chat(self, text: str) -> List[MemoryItem]:
        """Query chat history via hybrid search."""
        items = []
        db = self._get_chat_db()
        if db is None:
            return items

        try:
            results = db._hybrid_search_history(text, limit=10, exclude_recent=5)
            for rank, r in enumerate(results):
                items.append(MemoryItem(
                    text=r["text"][:300],
                    source="chat_vector" if rank < 5 else "chat_fts",
                    confidence=max(0.5, 1.0 - rank * 0.08),
                    timestamp=r.get("timestamp", 0),
                    rrf_score=1.0 / (60 + rank),
                ))
        except Exception as e:
            LOG.debug("Chat query failed: %s", e)

        return items

    def _query_titan(self, text: str) -> List[MemoryItem]:
        """Query Titan knowledge graph."""
        items = []
        titan = self._get_titan()
        if titan is None:
            return items

        try:
            # Use Titan's built-in retrieval
            results = titan.retrieve(text, limit=5)
            if results:
                for rank, r in enumerate(results):
                    node_text = r.get("label", "") or r.get("text", "")
                    meta = r.get("metadata", {})
                    if isinstance(meta, str):
                        import json
                        try:
                            meta = json.loads(meta)
                        except Exception:
                            meta = {}

                    created_at = r.get("created_at", "")
                    ts = 0.0
                    if created_at:
                        try:
                            ts = datetime.fromisoformat(created_at).timestamp()
                        except Exception:
                            pass

                    items.append(MemoryItem(
                        text=node_text[:300],
                        source="titan",
                        confidence=meta.get("confidence", 0.5),
                        timestamp=ts,
                        rrf_score=1.0 / (60 + rank),
                    ))
        except Exception as e:
            LOG.debug("Titan query failed: %s", e)

        return items

    def _query_consciousness(self, text: str) -> List[MemoryItem]:
        """Query consciousness daemon for relevant memories."""
        items = []
        try:
            from services.consciousness_daemon import get_consciousness_daemon
            cd = get_consciousness_daemon()
            memories_str = cd.get_relevant_memories(text, max_items=3)
            if memories_str:
                items.append(MemoryItem(
                    text=memories_str[:300],
                    source="consciousness",
                    confidence=0.6,
                    timestamp=time.time(),
                    rrf_score=1.0 / 62,  # rank ~2
                ))
        except Exception as e:
            LOG.debug("Consciousness query failed: %s", e)

        return items

    def _query_world_exp(self, text: str) -> List[MemoryItem]:
        """Query world experience for causal patterns."""
        items = []
        try:
            from tools.world_experience_daemon import context_inject
            ctx = context_inject(text, max_items=3)
            if ctx and len(ctx.strip()) > 10:
                items.append(MemoryItem(
                    text=ctx[:300],
                    source="world_exp",
                    confidence=0.5,
                    timestamp=time.time(),
                    rrf_score=1.0 / 63,  # rank ~3
                ))
        except Exception as e:
            LOG.debug("World experience query failed: %s", e)

        return items

    def _query_preferences(self, text: str) -> List[MemoryItem]:
        """Query user preferences."""
        items = []
        db = self._get_chat_db()
        if db is None:
            return items

        try:
            prefs = db.get_top_preferences(limit=5)
            if prefs:
                pref_text = "; ".join(f"{p['key']}: {p['value']}" for p in prefs)
                items.append(MemoryItem(
                    text=pref_text,
                    source="preference",
                    confidence=max(p["confidence"] for p in prefs),
                    timestamp=time.time(),
                    rrf_score=1.0 / 61,  # high priority
                ))
        except Exception as e:
            LOG.debug("Preferences query failed: %s", e)

        return items

    def _reciprocal_rank_fusion(self, items: List[MemoryItem]) -> List[MemoryItem]:
        """Apply RRF fusion: sort by existing rrf_score descending."""
        # Items already have rrf_score from individual queries
        # For items from same source, the score was set by rank
        # Just sort all items by rrf_score
        return sorted(items, key=lambda x: x.rrf_score, reverse=True)

    def _pack_to_budget(self, items: List[MemoryItem], budget_chars: int) -> MemoryResult:
        """Greedy packing: score × recency_penalty, highest first."""
        now = time.time()
        result = MemoryResult()

        # Compute pack scores with recency penalty
        for item in items:
            age_hours = max(0, (now - item.timestamp) / 3600) if item.timestamp > 0 else 24
            item.pack_score = item.rrf_score * (0.95 ** (age_hours / 24))

        # Sort by pack score
        ranked = sorted(items, key=lambda x: x.pack_score, reverse=True)

        chars_used = 0
        for item in ranked:
            item_len = len(item.text)
            if chars_used + item_len > budget_chars:
                # Try to fit truncated
                remaining = budget_chars - chars_used
                if remaining > 50:
                    item.text = item.text[:remaining - 3] + "..."
                    item_len = len(item.text)
                else:
                    continue

            result.items.append(item)
            chars_used += item_len

            # Track source attribution
            src = item.source
            result.sources_used[src] = result.sources_used.get(src, 0) + 1

        result.total_chars = chars_used
        return result

    def format_context(self, result: MemoryResult, source_labels: bool = True) -> str:
        """Format MemoryResult as injectable context string."""
        if not result.items:
            return ""

        lines = []
        for item in result.items:
            if source_labels:
                lines.append(f"[{item.source}] {item.text}")
            else:
                lines.append(item.text)

        return "\n".join(lines)


# Singleton
_hub: Optional[MemoryHub] = None


def get_memory_hub() -> MemoryHub:
    global _hub
    if _hub is None:
        _hub = MemoryHub()
    return _hub
