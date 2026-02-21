#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Titan Core - E-CPMM v5.1 Orchestrator

The main coordinator for the Titan Conversational Memory system.

Leitmotiv: Context is not text. Context is a time-weighted, uncertain
graph structure that is observed through text.

Key principles:
- Claims, not facts (epistemological humility)
- Time-weighted confidence decay
- Counter-hypotheses for inferences
- Controlled forgetting

Database: <AICORE_BASE>/database/titan.db
"""

import atexit
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from .storage import (
    SQLiteStore, VectorStore, KnowledgeGraph, TriHybridStorage,
    Node, Edge, Claim, TITAN_DB, DB_DIR
)
from .ingestion import Architect, get_architect, ExtractionResult
from .retrieval import Retriever, get_retriever, RetrievedItem
from .maintenance import MaintenanceEngine, get_maintenance_engine, PruneStats

LOG = logging.getLogger("titan.core")


@dataclass
class TitanConfig:
    """Configuration for Titan memory system."""
    # Storage
    db_path: Path = TITAN_DB
    vector_model: str = "all-MiniLM-L6-v2"

    # Retrieval
    default_limit: int = 5
    min_confidence: float = 0.15
    expand_graph: bool = True

    # Maintenance
    auto_maintenance: bool = True
    maintenance_interval: int = 3600  # 1 hour

    # Memory limits
    max_context_length: int = 4000


class Titan:
    """
    Titan - Conversational Memory System.

    Main interface for:
    - Ingesting text into memory
    - Retrieving relevant context
    - Managing memory lifecycle
    """

    def __init__(self, config: TitanConfig = None):
        self.config = config or TitanConfig()
        self._lock = threading.Lock()

        # Ensure database directory exists
        DB_DIR.mkdir(parents=True, exist_ok=True)

        # Initialize storage layers
        self.sqlite = SQLiteStore(self.config.db_path)
        self.vectors = VectorStore(self.config.vector_model)
        self.graph = KnowledgeGraph(self.sqlite)

        # Initialize processing layers
        self.architect = get_architect(self.sqlite, self.vectors, self.graph)
        self.retriever = get_retriever(self.sqlite, self.vectors, self.graph)
        self.maintenance = get_maintenance_engine(
            self.sqlite, self.vectors, self.graph
        )

        # Background maintenance thread
        self._maintenance_thread = None
        self._running = False

        if self.config.auto_maintenance:
            self._start_maintenance_thread()

        # Save on exit
        atexit.register(self._shutdown)

        LOG.info(f"Titan initialized (db: {self.config.db_path})")

    def _start_maintenance_thread(self):
        """Start background maintenance thread."""
        if self._maintenance_thread is not None:
            return

        self._running = True
        self._maintenance_thread = threading.Thread(
            target=self._maintenance_loop,
            daemon=True,
            name="TitanMaintenance"
        )
        self._maintenance_thread.start()

    def _maintenance_loop(self):
        """Background maintenance loop."""
        while self._running:
            try:
                if self.maintenance.should_run_maintenance():
                    self.maintenance.run_maintenance()
            except Exception as e:
                LOG.error(f"Maintenance error: {e}")

            time.sleep(60)  # Check every minute

    def _shutdown(self):
        """Shutdown and save state."""
        self._running = False
        try:
            self.vectors.save()
            LOG.info("Titan shutdown complete")
        except:
            pass

    # =========================================================================
    # Public API
    # =========================================================================

    def ingest(self, text: str, origin: str = "user",
               confidence: float = None) -> dict:
        """
        Ingest text into memory.

        Args:
            text: The text to ingest
            origin: Source of the text (user, code, inference, observation)
            confidence: Optional override for confidence level

        Returns:
            Dictionary with ingestion results
        """
        with self._lock:
            result = self.architect.ingest(text, origin, confidence)

        return {
            "success": True,
            "event_id": result.event_id,
            "claims": len(result.claims),
            "entities": result.entities,
            "topics": result.topics
        }

    def retrieve(self, query: str, limit: int = None) -> List[dict]:
        """
        Retrieve relevant context for a query.

        Args:
            query: The search query
            limit: Maximum number of results

        Returns:
            List of retrieved items as dictionaries
        """
        limit = limit or self.config.default_limit

        items = self.retriever.retrieve(
            query,
            limit=limit,
            expand_graph=self.config.expand_graph
        )

        return [item.to_dict() for item in items]

    def get_context_string(self, query: str, limit: int = None) -> str:
        """
        Get formatted context string for a query.

        Suitable for injecting into LLM prompts.
        """
        limit = limit or self.config.default_limit
        return self.retriever.get_context_string(query, limit)

    def forget(self, node_id: str) -> bool:
        """
        Manually forget a node (if not protected).

        Args:
            node_id: ID of the node to forget

        Returns:
            True if successfully forgotten
        """
        with self._lock:
            return self.maintenance._prune_node(node_id)

    def protect(self, node_id: str) -> bool:
        """
        Protect a node from automatic pruning.

        Args:
            node_id: ID of the node to protect

        Returns:
            True if successfully protected
        """
        return self.maintenance.protect_node(node_id)

    def unprotect(self, node_id: str) -> bool:
        """
        Remove protection from a node.

        Args:
            node_id: ID of the node to unprotect

        Returns:
            True if successfully unprotected
        """
        return self.maintenance.unprotect_node(node_id)

    def get_node(self, node_id: str) -> Optional[dict]:
        """Get a node by ID."""
        node = self.sqlite.get_node(node_id)
        return node.to_dict() if node else None

    def get_related(self, node_id: str, relation: str = None) -> List[dict]:
        """Get nodes related to a given node."""
        return self.graph.get_related(node_id, relation)

    def get_claims(self, entity: str) -> List[dict]:
        """Get claims related to an entity."""
        return self.retriever.builder.get_related_claims(entity)

    def add_counter_hypothesis(self, claim_id: str, counter_text: str) -> bool:
        """Add a counter-hypothesis to an existing claim."""
        return self.architect.add_counter_hypothesis(claim_id, counter_text)

    def run_maintenance(self) -> dict:
        """Manually trigger maintenance."""
        stats = self.maintenance.run_maintenance(force=True)
        return stats.to_dict()

    def get_stats(self) -> dict:
        """Get memory statistics."""
        sqlite_stats = self.sqlite.get_stats()
        vector_stats = self.vectors.get_stats()
        maintenance_status = self.maintenance.get_maintenance_status()

        return {
            "nodes": sqlite_stats["nodes"],
            "edges": sqlite_stats["edges"],
            "events": sqlite_stats["events"],
            "claims": sqlite_stats["claims"],
            "vectors": vector_stats["vectors"],
            "vector_model": vector_stats["model"],
            "last_maintenance": maintenance_status["last_maintenance"],
        }

    def health_check(self) -> dict:
        """Check system health."""
        try:
            # Test SQLite
            self.sqlite.get_stats()
            sqlite_ok = True
        except:
            sqlite_ok = False

        try:
            # Test vectors (lazy load)
            _ = self.vectors._get_model()
            vectors_ok = True
        except:
            vectors_ok = False

        return {
            "healthy": sqlite_ok and vectors_ok,
            "sqlite": "ok" if sqlite_ok else "error",
            "vectors": "ok" if vectors_ok else "error",
            "db_path": str(self.config.db_path),
        }


# =========================================================================
# Singleton Access
# =========================================================================

_titan: Optional[Titan] = None


def get_titan(config: TitanConfig = None) -> Titan:
    """Get or create the Titan singleton."""
    global _titan
    if _titan is None:
        _titan = Titan(config)
    return _titan


def reset_titan():
    """Reset the Titan singleton (for testing)."""
    global _titan
    if _titan is not None:
        _titan._shutdown()
        _titan = None


# =========================================================================
# Convenience Functions
# =========================================================================

def remember(text: str, origin: str = "user", confidence: float = 0.8) -> dict:
    """Ingest text into memory."""
    return get_titan().ingest(text, origin=origin, confidence=confidence)


def recall(query: str, limit: int = 5) -> List[dict]:
    """Retrieve relevant context for a query."""
    return get_titan().retrieve(query, limit=limit)


def get_context(query: str) -> str:
    """Get assembled context string for a query."""
    return get_titan().get_context_string(query)


def forget(node_id: str) -> bool:
    """Manually forget a node (if not protected)."""
    return get_titan().forget(node_id)


def protect(node_id: str) -> bool:
    """Protect a node from pruning."""
    return get_titan().protect(node_id)
