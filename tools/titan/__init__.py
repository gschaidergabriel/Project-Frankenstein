#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E-CPMM v5.1 — Titan Conversational Memory

A local, deterministic context, memory, and retrieval system that makes:
- Information findable
- Relationships explicit
- Forgetting controllable
- Assumptions weakened over time

Leitmotiv: Context is not text. Context is a time-weighted, uncertain
graph structure that is observed through text.

Database location: $XDG_DATA_HOME/frank/db/ (portable)
"""

__version__ = "5.1.0"
__codename__ = "Titan"

from pathlib import Path

# Database path (ALWAYS use this location)
try:
    from config.paths import DB_DIR, get_db
    TITAN_DB = get_db("titan")
except ImportError:
    DB_DIR = Path.home() / ".local" / "share" / "frank" / "db"
    DB_DIR.mkdir(parents=True, exist_ok=True)
    TITAN_DB = DB_DIR / "titan.db"
VECTOR_INDEX = DB_DIR / "titan_vectors.idx"

# Lazy imports for performance
def get_memory():
    """Get the Titan memory instance."""
    from .titan_core import get_titan
    return get_titan()

def remember(text: str, origin: str = "user", confidence: float = 0.8) -> dict:
    """Ingest text into memory."""
    return get_memory().ingest(text, origin=origin, confidence=confidence)

def recall(query: str, limit: int = 5) -> list:
    """Retrieve relevant context for a query."""
    return get_memory().retrieve(query, limit=limit)

def get_context(query: str) -> str:
    """Get assembled context string for a query."""
    return get_memory().get_context_string(query)

def forget(node_id: str) -> bool:
    """Manually forget a node (if not protected)."""
    return get_memory().forget(node_id)

def protect(node_id: str) -> bool:
    """Protect a node from pruning."""
    return get_memory().protect(node_id)
