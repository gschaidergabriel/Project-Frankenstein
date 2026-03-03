#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Titan Retrieval Layer - Context Builder

Retrieves and ranks relevant context using:
1. Reciprocal Rank Fusion (RRF) for multi-signal ranking
2. Time-weighted confidence decay
3. Graph-aware expansion

Core principle: Context assembly only includes items where
confidence × recency > threshold

Database: <AICORE_BASE>/database/titan.db
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

from .storage import SQLiteStore, VectorStore, KnowledgeGraph, Node

LOG = logging.getLogger("titan.retrieval")


# Time decay constants
DECAY_HALF_LIFE_DAYS = 7  # Confidence halves every 7 days
DECAY_MINIMUM = 0.1       # Never decay below 10%

# RRF constant
RRF_K = 60  # Standard RRF constant

# Retrieval thresholds
MIN_EFFECTIVE_CONFIDENCE = 0.15  # Below this, item is not retrieved
MAX_CONTEXT_LENGTH = 4000        # Maximum context string length


@dataclass
class RetrievedItem:
    """An item retrieved from memory."""
    node_id: str
    label: str
    node_type: str
    content: str
    base_confidence: float
    effective_confidence: float  # After time decay
    recency_score: float
    vector_score: float = 0.0
    fts_score: float = 0.0
    graph_score: float = 0.0
    final_score: float = 0.0
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "label": self.label,
            "type": self.node_type,
            "content": self.content,
            "confidence": self.effective_confidence,
            "score": self.final_score,
        }


def calculate_time_decay(created_at: str, half_life_days: float = DECAY_HALF_LIFE_DAYS) -> float:
    """
    Calculate time decay factor.

    Uses exponential decay: decay = 2^(-t/half_life)
    """
    try:
        created = datetime.fromisoformat(created_at)
        now = datetime.now()
        age_days = (now - created).total_seconds() / 86400

        decay = math.pow(2, -age_days / half_life_days)
        return max(decay, DECAY_MINIMUM)
    except Exception:
        return 1.0  # Default to no decay on parse error


def calculate_recency_score(created_at: str) -> float:
    """
    Calculate recency score (0 to 1).

    More recent = higher score.
    """
    try:
        created = datetime.fromisoformat(created_at)
        now = datetime.now()
        age_days = (now - created).total_seconds() / 86400

        # Exponential decay for recency
        return math.exp(-age_days / 30)  # 30-day characteristic time
    except Exception:
        return 0.5


def reciprocal_rank_fusion(rankings: List[List[Tuple[str, float]]],
                            k: int = RRF_K) -> Dict[str, float]:
    """
    Combine multiple rankings using Reciprocal Rank Fusion.

    RRF score = sum(1 / (k + rank)) for each ranking list

    Args:
        rankings: List of ranking lists, each containing (node_id, score) tuples
        k: RRF constant (default 60)

    Returns:
        Dictionary of node_id -> fused score
    """
    fused_scores = {}

    for ranking in rankings:
        for rank, (node_id, _) in enumerate(ranking, start=1):
            if node_id not in fused_scores:
                fused_scores[node_id] = 0.0
            fused_scores[node_id] += 1.0 / (k + rank)

    return fused_scores


class ContextBuilder:
    """
    Builds context from memory for queries.

    Uses multiple retrieval signals:
    1. Vector similarity (semantic meaning)
    2. FTS (keyword matching)
    3. Graph traversal (relationships)
    4. Recency (time-weighted)
    """

    def __init__(self, sqlite: SQLiteStore, vectors: VectorStore,
                 graph: KnowledgeGraph):
        self.sqlite = sqlite
        self.vectors = vectors
        self.graph = graph

    def retrieve(self, query: str, limit: int = 10,
                 min_confidence: float = MIN_EFFECTIVE_CONFIDENCE) -> List[RetrievedItem]:
        """
        Retrieve relevant items for a query.

        Combines vector, FTS, and graph signals using RRF.
        """
        if not query or not query.strip():
            return []

        # Collect rankings from different sources
        rankings = []

        # 1. Vector similarity search
        vector_results = self.vectors.search(query, limit=limit * 3)
        if vector_results:
            rankings.append(vector_results)

        # 2. FTS search
        fts_results = self.sqlite.search_fts(query, limit=limit * 3)
        if fts_results:
            rankings.append(fts_results)

        if not rankings:
            return []

        # 3. Fuse rankings with RRF
        fused_scores = reciprocal_rank_fusion(rankings)

        # --- Neural Cortex: get cortex once, outside loop ---
        _cortex = None
        try:
            from .neural_cortex import get_cortex
            _cortex = get_cortex()
        except Exception:
            pass

        # 4. Build retrieved items with enrichment
        items = []
        for node_id, rrf_score in fused_scores.items():
            node = self.sqlite.get_node(node_id)
            if not node:
                continue

            # Calculate time decay
            time_decay = calculate_time_decay(node.created_at)

            # Get base confidence from metadata or default
            base_confidence = node.metadata.get("confidence", 0.5)

            # Calculate effective confidence
            effective_confidence = base_confidence * time_decay

            # Skip items below threshold
            if effective_confidence < min_confidence:
                continue

            # Get recency score
            recency_score = calculate_recency_score(node.created_at)

            # Get vector score for this node
            vector_score = 0.0
            if vector_results:
                for nid, score in vector_results:
                    if nid == node_id:
                        vector_score = score
                        break

            # Get FTS score for this node
            fts_score = 0.0
            if fts_results:
                for nid, score in fts_results:
                    if nid == node_id:
                        fts_score = score
                        break

            # Calculate graph score (degree centrality)
            degree = self.sqlite.get_node_degree(node_id)
            graph_score = min(1.0, degree / 10.0)

            # Get content from metadata
            content = node.metadata.get("full_text", node.label)

            # --- Neural Cortex: learned retrieval weights ---
            _weights = [0.4, 0.3, 0.2, 0.1]
            if _cortex:
                try:
                    _rwl_f = {
                        "rrf": rrf_score, "conf": effective_confidence,
                        "recency": recency_score, "graph": graph_score,
                        "query_len": len(query.split()),
                        "n_results": len(fused_scores),
                        "valence": node.metadata.get("valence", 0.0),
                        "arousal": node.metadata.get("arousal", 0.5),
                    }
                    _weights = _cortex.get_retrieval_weights(_rwl_f)
                except Exception:
                    pass

            final_score = (
                rrf_score * _weights[0] +
                effective_confidence * _weights[1] +
                recency_score * _weights[2] +
                graph_score * _weights[3]
            )

            items.append(RetrievedItem(
                node_id=node_id,
                label=node.label,
                node_type=node.type,
                content=content,
                base_confidence=base_confidence,
                effective_confidence=effective_confidence,
                recency_score=recency_score,
                vector_score=vector_score,
                fts_score=fts_score,
                graph_score=graph_score,
                final_score=final_score,
                metadata=node.metadata
            ))

        # Sort by final score and limit
        items.sort(key=lambda x: x.final_score, reverse=True)
        result = items[:limit]

        # --- Neural Cortex: log retrieval access + co-retrieval ---
        try:
            if _cortex and result:
                _ids = [it.node_id for it in result]
                _scores = [it.final_score for it in result]
                _cortex.log_access(_ids, query, _scores)
                _cortex.log_co_retrieval(_ids)
        except Exception:
            pass

        return result

    def expand_with_graph(self, items: List[RetrievedItem],
                           hops: int = 1) -> List[RetrievedItem]:
        """
        Expand retrieved items with graph-connected nodes.

        Limited to N hops for performance.
        """
        expanded_ids = set(item.node_id for item in items)
        expanded_items = list(items)

        for item in items:
            # Traverse graph from this node
            traversal = self.graph.traverse(item.node_id, hops=hops)

            for result in traversal:
                if "node" in result:
                    node_data = result["node"]
                    node_id = node_data["id"]

                    if node_id in expanded_ids:
                        continue

                    node = self.sqlite.get_node(node_id)
                    if not node:
                        continue

                    # Create expanded item with reduced score
                    depth = result.get("depth", 1)
                    score_factor = 0.5 ** depth

                    time_decay = calculate_time_decay(node.created_at)
                    base_confidence = node.metadata.get("confidence", 0.5)
                    effective_confidence = base_confidence * time_decay

                    if effective_confidence < MIN_EFFECTIVE_CONFIDENCE:
                        continue

                    expanded_items.append(RetrievedItem(
                        node_id=node_id,
                        label=node.label,
                        node_type=node.type,
                        content=node.metadata.get("full_text", node.label),
                        base_confidence=base_confidence,
                        effective_confidence=effective_confidence,
                        recency_score=calculate_recency_score(node.created_at),
                        graph_score=score_factor,
                        final_score=item.final_score * score_factor,
                        metadata=node.metadata
                    ))

                    expanded_ids.add(node_id)

        return expanded_items

    def build_context_string(self, items: List[RetrievedItem],
                              max_length: int = MAX_CONTEXT_LENGTH) -> str:
        """
        Build a context string from retrieved items.

        Formats items for LLM consumption with confidence indicators.
        """
        if not items:
            return ""

        lines = []
        current_length = 0

        for item in items:
            # Format confidence as certainty level
            if item.effective_confidence >= 0.8:
                certainty = "certain"
            elif item.effective_confidence >= 0.6:
                certainty = "likely"
            elif item.effective_confidence >= 0.4:
                certainty = "possible"
            else:
                certainty = "uncertain"

            # Format line
            line = f"[{certainty}] {item.content}"

            # Check length
            if current_length + len(line) > max_length:
                break

            lines.append(line)
            current_length += len(line) + 1

        return "\n".join(lines)

    def get_related_claims(self, entity: str) -> List[dict]:
        """Get claims related to an entity."""
        conn = self.sqlite._get_conn()
        claims = []

        # Search claims table
        rows = conn.execute("""
            SELECT * FROM claims
            WHERE subject LIKE ? OR object LIKE ?
            ORDER BY created_at DESC
            LIMIT 20
        """, (f"%{entity}%", f"%{entity}%")).fetchall()

        for row in rows:
            claims.append({
                "subject": row["subject"],
                "predicate": row["predicate"],
                "object": row["object"],
                "confidence": row["confidence"],
                "origin": row["origin"],
                "created_at": row["created_at"]
            })

        return claims


class Retriever:
    """
    High-level retrieval interface.

    Combines ContextBuilder with caching and optimization.
    """

    def __init__(self, sqlite: SQLiteStore, vectors: VectorStore,
                 graph: KnowledgeGraph):
        self.builder = ContextBuilder(sqlite, vectors, graph)
        self._cache: Dict[str, Tuple[List[RetrievedItem], float]] = {}
        self._cache_ttl = 60  # 60 seconds cache

    def retrieve(self, query: str, limit: int = 5,
                 expand_graph: bool = True) -> List[RetrievedItem]:
        """
        Retrieve relevant context for a query.

        Args:
            query: The search query
            limit: Maximum number of items
            expand_graph: Whether to expand with graph connections

        Returns:
            List of RetrievedItem objects
        """
        # Check cache
        cache_key = f"{query}:{limit}:{expand_graph}"
        if cache_key in self._cache:
            items, timestamp = self._cache[cache_key]
            if datetime.now().timestamp() - timestamp < self._cache_ttl:
                return items

        # Retrieve from builder
        items = self.builder.retrieve(query, limit=limit)

        # Expand with graph if requested
        if expand_graph and items:
            items = self.builder.expand_with_graph(items, hops=1)
            # Re-sort and limit
            items.sort(key=lambda x: x.final_score, reverse=True)
            items = items[:limit]

        # Update cache
        self._cache[cache_key] = (items, datetime.now().timestamp())

        return items

    def get_context_string(self, query: str, limit: int = 5) -> str:
        """Get formatted context string for a query."""
        items = self.retrieve(query, limit=limit)
        return self.builder.build_context_string(items)

    def clear_cache(self):
        """Clear the retrieval cache."""
        self._cache.clear()


# Singleton instance
_retriever: Optional[Retriever] = None


def get_retriever(sqlite: SQLiteStore, vectors: VectorStore,
                  graph: KnowledgeGraph) -> Retriever:
    """Get or create retriever instance."""
    global _retriever
    if _retriever is None:
        _retriever = Retriever(sqlite, vectors, graph)
    return _retriever
