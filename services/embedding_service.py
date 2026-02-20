#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shared Embedding Service - Singleton MiniLM-L6-v2 wrapper.

Used by:
- ChatMemoryDB (hybrid search)
- Titan VectorStore (knowledge graph)
- Context Budget Allocator (channel relevance)

Thread-safe, lazy-loaded, ~90MB RAM footprint.
"""

import logging
import threading
from typing import List, Optional, Tuple

import numpy as np

LOG = logging.getLogger("embedding_service")

_instance: Optional["EmbeddingService"] = None
_lock = threading.Lock()


def get_embedding_service() -> "EmbeddingService":
    """Get or create the singleton EmbeddingService."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = EmbeddingService()
    return _instance


class EmbeddingService:
    """
    Singleton, lazy-loaded MiniLM-L6-v2 wrapper.

    Thread-safe. Model loads on first embed call (~2-5s, ~90MB).
    All embedding operations go through this service to avoid
    duplicate model instances.
    """

    MODEL_NAME = "all-MiniLM-L6-v2"
    EMBEDDING_DIM = 384

    def __init__(self):
        self._model = None
        self._lock = threading.Lock()

    def _get_model(self):
        """Lazy-load the embedding model."""
        if self._model is None:
            with self._lock:
                if self._model is None:
                    try:
                        from sentence_transformers import SentenceTransformer
                        LOG.info(f"Loading embedding model: {self.MODEL_NAME}")
                        self._model = SentenceTransformer(self.MODEL_NAME)
                        LOG.info("Embedding model loaded")
                    except Exception as e:
                        LOG.error(f"Failed to load embedding model: {e}")
                        raise
        return self._model

    def embed_text(self, text: str) -> np.ndarray:
        """
        Generate 384-dim embedding for a single text.

        Returns:
            np.ndarray of shape (384,), dtype float32
        """
        if not text or not text.strip():
            return np.zeros(self.EMBEDDING_DIM, dtype=np.float32)
        model = self._get_model()
        return model.encode(text, convert_to_numpy=True).astype(np.float32)

    def embed_batch(self, texts: List[str], batch_size: int = 64) -> np.ndarray:
        """
        Generate embeddings for multiple texts.

        Returns:
            np.ndarray of shape (len(texts), 384), dtype float32
        """
        if not texts:
            return np.empty((0, self.EMBEDDING_DIM), dtype=np.float32)
        model = self._get_model()
        return model.encode(
            texts, convert_to_numpy=True, batch_size=batch_size,
        ).astype(np.float32)

    def cosine_similarity(self, vec_a: np.ndarray, vec_b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        norm_a = np.linalg.norm(vec_a)
        norm_b = np.linalg.norm(vec_b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))

    def cosine_search(
        self,
        query_vec: np.ndarray,
        vectors: np.ndarray,
        ids: List[str],
        top_k: int = 10,
    ) -> List[Tuple[str, float]]:
        """
        Search for most similar vectors by cosine similarity.

        Args:
            query_vec: Query embedding (384,)
            vectors: Matrix of embeddings (N, 384)
            ids: List of IDs corresponding to rows in vectors
            top_k: Number of results to return

        Returns:
            List of (id, similarity) tuples, sorted by similarity descending
        """
        if len(vectors) == 0 or len(ids) == 0:
            return []

        norms = np.linalg.norm(vectors, axis=1) * np.linalg.norm(query_vec)
        norms[norms == 0] = 1.0
        similarities = np.dot(vectors, query_vec) / norms

        top_k = min(top_k, len(ids))
        top_indices = np.argpartition(similarities, -top_k)[-top_k:]
        top_indices = top_indices[np.argsort(similarities[top_indices])[::-1]]

        return [(ids[i], float(similarities[i])) for i in top_indices]

    @property
    def is_loaded(self) -> bool:
        """Check if the model is loaded (without triggering lazy load)."""
        return self._model is not None
