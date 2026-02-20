"""
Dynamic Context Budget Allocator — Relevance-aware token distribution.

Replaces fixed 800/600/400 char allocations with proportional distribution
based on cosine similarity between user query and channel summaries.

Channels:
  recent_conversation — Last N messages (always high priority)
  semantic_matches    — Hybrid FTS5+vector search results
  titan_memory        — Episodic memory from Titan graph
  ego_mood_identity   — E-PQ mood, Ego-Construct, Self-Knowledge
  world_experience    — Causal patterns from world model
  news_akam           — News scanner + AKAM web search results

Token budget: MAX_SAFE_TOKENS minus user message minus overhead.
"""

import logging
import time
from typing import Dict, Optional

import numpy as np

LOG = logging.getLogger("context_budget")

# Channel base priorities (0.0–1.0)
CHANNEL_PRIORITIES = {
    "recent_conversation": 0.9,
    "semantic_matches": 0.7,
    "titan_memory": 0.4,
    "ego_mood_identity": 0.3,
    "world_experience": 0.2,
    "news_akam": 0.0,
}

# Minimum chars per channel (even if low priority)
CHANNEL_MINIMUMS = {
    "recent_conversation": 200,
    "semantic_matches": 0,
    "titan_memory": 0,
    "ego_mood_identity": 80,
    "world_experience": 0,
    "news_akam": 0,
}


def allocate_budget(
    total_chars: int,
    channels: Dict[str, dict],
    query_vec: Optional[np.ndarray] = None,
) -> Dict[str, int]:
    """Distribute available chars across channels proportionally by relevance.

    Args:
        total_chars: Total character budget for all channels combined.
        channels: Dict of channel_name -> {"summary_vec": np.ndarray or None, "triggered": bool}.
        query_vec: Embedding of the current user query (384-dim).

    Returns:
        Dict of channel_name -> allocated chars.
    """
    if total_chars <= 0:
        return {ch: 0 for ch in CHANNEL_PRIORITIES}

    # Compute effective priorities
    effective = {}
    for ch_name, base in CHANNEL_PRIORITIES.items():
        ch_data = channels.get(ch_name, {})

        # Trigger-based channels (news/akam): 0 unless triggered
        if ch_name == "news_akam":
            if ch_data.get("triggered"):
                effective[ch_name] = 0.8
            else:
                effective[ch_name] = 0.0
            continue

        # Cosine boost for boostable channels
        if query_vec is not None and ch_data.get("summary_vec") is not None:
            summary_vec = ch_data["summary_vec"]
            norm_q = np.linalg.norm(query_vec)
            norm_s = np.linalg.norm(summary_vec)
            if norm_q > 0 and norm_s > 0:
                similarity = float(np.dot(query_vec, summary_vec) / (norm_q * norm_s))
                similarity = max(0.0, similarity)  # clamp negative
            else:
                similarity = 0.0
            effective[ch_name] = base + 0.3 * similarity
        else:
            effective[ch_name] = base

    # Normalize to proportional allocation
    total_priority = sum(effective.values())
    if total_priority <= 0:
        return {ch: 0 for ch in CHANNEL_PRIORITIES}

    # First pass: proportional
    budget = {}
    for ch_name, priority in effective.items():
        budget[ch_name] = int((priority / total_priority) * total_chars)

    # Second pass: enforce minimums
    for ch_name, minimum in CHANNEL_MINIMUMS.items():
        if ch_name in budget and budget[ch_name] < minimum and minimum <= total_chars:
            budget[ch_name] = minimum

    # Third pass: cap total to available
    total_used = sum(budget.values())
    if total_used > total_chars:
        excess = total_used - total_chars
        # Steal from lowest-priority channels first
        for ch_name in sorted(budget, key=lambda c: effective.get(c, 0)):
            steal = min(excess, budget[ch_name] - CHANNEL_MINIMUMS.get(ch_name, 0))
            if steal > 0:
                budget[ch_name] -= steal
                excess -= steal
            if excess <= 0:
                break

    return budget


class ChannelSummaryCache:
    """Cached summary embeddings per channel. Refreshed every 60 minutes."""

    TTL = 3600  # 1 hour

    def __init__(self):
        self.vecs: Dict[str, Optional[np.ndarray]] = {}
        self._last_refresh = 0.0

    def get_vecs(self) -> Dict[str, Optional[np.ndarray]]:
        """Get cached summary vectors, refreshing if stale."""
        now = time.time()
        if (now - self._last_refresh) > self.TTL:
            self._refresh()
            self._last_refresh = now
        return self.vecs

    def _refresh(self):
        """Rebuild summary embeddings from each data source."""
        try:
            from services.embedding_service import get_embedding_service
            emb = get_embedding_service()
        except Exception:
            return

        # recent_conversation: embed concat of last 5 messages
        try:
            from services.chat_memory import ChatMemoryDB
            db = ChatMemoryDB()
            recent = db.get_recent_messages(limit=5)
            if recent:
                text = " ".join(m["text"][:200] for m in recent if m.get("text"))
                self.vecs["recent_conversation"] = emb.embed_text(text)
        except Exception as e:
            LOG.debug("Summary cache: recent_conversation failed: %s", e)

        # semantic_matches: embed concat of last 3 session summaries
        try:
            from services.chat_memory import ChatMemoryDB
            db = ChatMemoryDB()
            summaries = db.get_recent_summaries(limit=3)
            if summaries:
                text = " ".join(s["summary"] for s in summaries if s.get("summary"))
                self.vecs["semantic_matches"] = emb.embed_text(text)
        except Exception as e:
            LOG.debug("Summary cache: semantic_matches failed: %s", e)

        # titan_memory: embed top-10 nodes by confidence
        try:
            import sqlite3
            from config.paths import get_db
            titan_db = get_db("titan")
            conn = sqlite3.connect(str(titan_db))
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT label FROM nodes
                ORDER BY json_extract(metadata, '$.confidence') DESC
                LIMIT 10
            """).fetchall()
            conn.close()
            if rows:
                text = " ".join(r["label"] for r in rows if r["label"])
                self.vecs["titan_memory"] = emb.embed_text(text)
        except Exception as e:
            LOG.debug("Summary cache: titan_memory failed: %s", e)

        # world_experience: embed active causal links
        try:
            import sqlite3
            from config.paths import get_db
            we_db = get_db("world_experience")
            conn = sqlite3.connect(str(we_db))
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT e1.name AS cause, cl.relation_type AS relation, e2.name AS effect
                FROM causal_links cl
                JOIN entities e1 ON cl.cause_entity_id = e1.id
                JOIN entities e2 ON cl.effect_entity_id = e2.id
                WHERE cl.status = 'active'
                ORDER BY cl.confidence DESC
                LIMIT 10
            """).fetchall()
            conn.close()
            if rows:
                text = " ".join(f"{r['cause']} {r['relation']} {r['effect']}" for r in rows)
                self.vecs["world_experience"] = emb.embed_text(text)
        except Exception as e:
            LOG.debug("Summary cache: world_experience failed: %s", e)

        LOG.debug("Summary cache refreshed: %s channels", len(self.vecs))


# Singleton
_cache: Optional[ChannelSummaryCache] = None


def get_summary_cache() -> ChannelSummaryCache:
    global _cache
    if _cache is None:
        _cache = ChannelSummaryCache()
    return _cache
