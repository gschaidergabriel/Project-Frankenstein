#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Titan Storage Layer - Tri-Hybrid Architecture

Components:
1. SQLite (The Ledger) - Deterministic facts & indexes
2. Vector Store (Semantic Field) - Meaning search
3. Knowledge Graph (Structure) - Explicit relations

Database: /home/ai-core-node/aicore/database/titan.db
"""

import hashlib
import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import numpy as np

LOG = logging.getLogger("titan.storage")

# Transaction hooks for invariant enforcement
# Validators are loaded lazily and cached per-process
_validators_initialized = False
_validators = None


def _init_validators():
    """Initialize invariant validators (once per process)."""
    global _validators_initialized, _validators
    if _validators_initialized:
        return _validators

    _validators_initialized = True

    try:
        from services.invariants.hooks import get_hook_registry, HookType, InvariantValidators
        from services.invariants.energy import get_energy
        from services.invariants.entropy import get_entropy
        from services.invariants.core_kernel import get_core

        # Create validators
        _validators = InvariantValidators(
            energy_checker=get_energy(),
            entropy_checker=get_entropy(),
            core_checker=get_core()
        )

        # Register with hook registry
        registry = get_hook_registry()
        _validators.register_all()

        LOG.info("Invariant validators initialized in Titan process")
        return _validators

    except ImportError as e:
        LOG.debug(f"Invariants module not available: {e}")
        return None
    except Exception as e:
        LOG.warning(f"Could not initialize invariant validators: {e}")
        return None


def _execute_hook(hook_type_name: str, operation: str, data: dict) -> bool:
    """
    Execute transaction hooks. Returns True if operation is allowed.

    This is INVISIBLE to Frank. If hooks reject, write simply fails.
    """
    try:
        from services.invariants.hooks import get_hook_registry, HookType

        # Ensure validators are initialized
        validators = _init_validators()

        # Set titan store reference if needed
        if validators and validators._titan_store is None:
            try:
                from tools.titan.titan_core import get_titan
                validators.set_titan_store(get_titan())
            except Exception:
                pass

        registry = get_hook_registry()
        hook_type = getattr(HookType, hook_type_name, None)
        if hook_type is None:
            return True

        result = registry.execute(hook_type, operation, data)
        if not result.allowed:
            LOG.warning(f"Transaction rejected by invariant: {result.reason}")
        return result.allowed

    except ImportError:
        return True  # Invariants not available
    except Exception as e:
        LOG.error(f"Hook execution error: {e}")
        return True  # Fail open on errors

# Database path
try:
    from config.paths import DB_DIR, get_db
    TITAN_DB = get_db("titan")
except ImportError:
    DB_DIR = Path.home() / ".local" / "share" / "frank" / "db"
    DB_DIR.mkdir(parents=True, exist_ok=True)
    TITAN_DB = DB_DIR / "titan.db"


@dataclass
class Node:
    """Knowledge graph node."""
    id: str
    type: str  # entity, concept, event, claim, code
    label: str
    created_at: str
    protected: bool = False
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "label": self.label,
            "created_at": self.created_at,
            "protected": self.protected,
            "metadata": self.metadata,
        }


@dataclass
class Edge:
    """Knowledge graph edge with confidence."""
    src: str
    dst: str
    relation: str
    confidence: float  # [0, 1]
    origin: str  # user, code, inference
    created_at: str

    def to_dict(self) -> dict:
        return {
            "src": self.src,
            "dst": self.dst,
            "relation": self.relation,
            "confidence": self.confidence,
            "origin": self.origin,
            "created_at": self.created_at,
        }


@dataclass
class Claim:
    """A claim extracted from text (not a fact!)."""
    subject: str
    predicate: str
    object: str
    confidence: float
    origin: str
    timestamp: str
    source_event_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "confidence": self.confidence,
            "origin": self.origin,
            "timestamp": self.timestamp,
            "source_event_id": self.source_event_id,
        }


class SQLiteStore:
    """
    SQLite - The Ledger

    Deterministic facts & indexes.
    Append-only for events.
    """

    SCHEMA = """
    -- Nodes table
    CREATE TABLE IF NOT EXISTS nodes (
        id TEXT PRIMARY KEY,
        type TEXT NOT NULL,
        label TEXT NOT NULL,
        created_at TEXT NOT NULL,
        protected INTEGER DEFAULT 0,
        metadata TEXT DEFAULT '{}'
    );

    -- Edges table (Graph adjacency)
    CREATE TABLE IF NOT EXISTS edges (
        src TEXT NOT NULL,
        dst TEXT NOT NULL,
        relation TEXT NOT NULL,
        confidence REAL DEFAULT 0.5,
        origin TEXT DEFAULT 'inference',
        created_at TEXT NOT NULL,
        PRIMARY KEY (src, dst, relation),
        FOREIGN KEY (src) REFERENCES nodes(id) ON DELETE CASCADE,
        FOREIGN KEY (dst) REFERENCES nodes(id) ON DELETE CASCADE
    );

    -- Events table (append-only chat log)
    CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY,
        raw_text TEXT NOT NULL,
        ts TEXT NOT NULL,
        origin TEXT DEFAULT 'user',
        processed INTEGER DEFAULT 0
    );

    -- Claims table
    CREATE TABLE IF NOT EXISTS claims (
        id TEXT PRIMARY KEY,
        subject TEXT NOT NULL,
        predicate TEXT NOT NULL,
        object TEXT NOT NULL,
        confidence REAL DEFAULT 0.5,
        origin TEXT DEFAULT 'inference',
        created_at TEXT NOT NULL,
        source_event_id TEXT,
        FOREIGN KEY (source_event_id) REFERENCES events(id)
    );

    -- FTS5 for full-text search
    CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
        content,
        metadata,
        node_id,
        tokenize='porter unicode61'
    );

    -- Indexes
    CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
    CREATE INDEX IF NOT EXISTS idx_nodes_created ON nodes(created_at);
    CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
    CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
    CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(relation);
    CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
    CREATE INDEX IF NOT EXISTS idx_claims_subject ON claims(subject);
    """

    def __init__(self, db_path: Path = TITAN_DB):
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30
            )
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    def _init_db(self):
        """Initialize database schema."""
        DB_DIR.mkdir(parents=True, exist_ok=True)
        conn = self._get_conn()
        conn.executescript(self.SCHEMA)
        conn.commit()
        LOG.debug("SQLite schema initialized")

    def add_node(self, node: Node) -> bool:
        """Add or update a node."""
        # Execute pre-write hooks (invariant enforcement)
        if not _execute_hook("PRE_WRITE", "add_node", node.to_dict()):
            return False

        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO nodes (id, type, label, created_at, protected, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (node.id, node.type, node.label, node.created_at,
                  1 if node.protected else 0, json.dumps(node.metadata)))
            conn.commit()

            # Execute post-write hooks
            _execute_hook("POST_WRITE", "add_node", node.to_dict())
            return True
        except Exception as e:
            LOG.error(f"Failed to add node: {e}")
            return False

    def get_node(self, node_id: str) -> Optional[Node]:
        """Get a node by ID."""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if row:
            return Node(
                id=row['id'],
                type=row['type'],
                label=row['label'],
                created_at=row['created_at'],
                protected=bool(row['protected']),
                metadata=json.loads(row['metadata'] or '{}')
            )
        return None

    def add_edge(self, edge: Edge) -> bool:
        """Add or update an edge."""
        # Execute pre-write hooks (invariant enforcement)
        if not _execute_hook("PRE_WRITE", "add_edge", edge.to_dict()):
            return False

        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO edges (src, dst, relation, confidence, origin, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (edge.src, edge.dst, edge.relation, edge.confidence,
                  edge.origin, edge.created_at))
            conn.commit()

            # Execute post-write hooks
            _execute_hook("POST_WRITE", "add_edge", edge.to_dict())
            return True
        except Exception as e:
            LOG.error(f"Failed to add edge: {e}")
            return False

    def get_edges(self, node_id: str, direction: str = "both") -> List[Edge]:
        """Get edges connected to a node."""
        conn = self._get_conn()
        edges = []

        if direction in ("out", "both"):
            rows = conn.execute(
                "SELECT * FROM edges WHERE src = ?", (node_id,)
            ).fetchall()
            for row in rows:
                edges.append(Edge(
                    src=row['src'], dst=row['dst'], relation=row['relation'],
                    confidence=row['confidence'], origin=row['origin'],
                    created_at=row['created_at']
                ))

        if direction in ("in", "both"):
            rows = conn.execute(
                "SELECT * FROM edges WHERE dst = ?", (node_id,)
            ).fetchall()
            for row in rows:
                edges.append(Edge(
                    src=row['src'], dst=row['dst'], relation=row['relation'],
                    confidence=row['confidence'], origin=row['origin'],
                    created_at=row['created_at']
                ))

        return edges

    def add_event(self, event_id: str, text: str, origin: str = "user") -> bool:
        """Add a chat event (append-only)."""
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT INTO events (id, raw_text, ts, origin, processed)
                VALUES (?, ?, ?, ?, 0)
            """, (event_id, text, datetime.now().isoformat(), origin))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False  # Already exists
        except Exception as e:
            LOG.error(f"Failed to add event: {e}")
            return False

    def add_claim(self, claim: Claim) -> bool:
        """Add a claim."""
        # Execute pre-write hooks (invariant enforcement)
        claim_data = claim.to_dict()
        if not _execute_hook("PRE_WRITE", "add_claim", claim_data):
            return False

        conn = self._get_conn()
        claim_id = hashlib.sha256(
            f"{claim.subject}:{claim.predicate}:{claim.object}".encode()
        ).hexdigest()[:16]
        try:
            conn.execute("""
                INSERT OR REPLACE INTO claims
                (id, subject, predicate, object, confidence, origin, created_at, source_event_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (claim_id, claim.subject, claim.predicate, claim.object,
                  claim.confidence, claim.origin, claim.timestamp, claim.source_event_id))
            conn.commit()

            # Execute post-write hooks
            claim_data["id"] = claim_id
            _execute_hook("POST_WRITE", "add_claim", claim_data)
            return True
        except Exception as e:
            LOG.error(f"Failed to add claim: {e}")
            return False

    def index_for_fts(self, node_id: str, content: str, metadata: dict = None):
        """Add content to FTS index."""
        conn = self._get_conn()
        try:
            # Delete existing entry
            conn.execute("DELETE FROM memory_fts WHERE node_id = ?", (node_id,))
            # Insert new
            conn.execute("""
                INSERT INTO memory_fts (content, metadata, node_id)
                VALUES (?, ?, ?)
            """, (content, json.dumps(metadata or {}), node_id))
            conn.commit()
        except Exception as e:
            LOG.error(f"FTS index failed: {e}")

    def search_fts(self, query: str, limit: int = 10) -> List[Tuple[str, float]]:
        """Search using FTS5. Returns (node_id, rank) pairs."""
        conn = self._get_conn()
        results = []
        try:
            # Escape FTS5 special characters and clean query
            import re
            # Remove special FTS5 chars and keep alphanumeric + spaces
            clean_query = re.sub(r'[^\w\s]', ' ', query)
            # Convert to FTS5 OR query for each word
            words = [w.strip() for w in clean_query.split() if w.strip()]
            if not words:
                return []
            fts_query = ' OR '.join(words)

            rows = conn.execute("""
                SELECT node_id, rank FROM memory_fts
                WHERE memory_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (fts_query, limit)).fetchall()
            for row in rows:
                results.append((row['node_id'], abs(row['rank'])))
        except Exception as e:
            LOG.warning(f"FTS search failed: {e}")
        return results

    def get_node_degree(self, node_id: str) -> int:
        """Get the degree (number of edges) for a node."""
        conn = self._get_conn()
        count = conn.execute("""
            SELECT COUNT(*) as cnt FROM edges WHERE src = ? OR dst = ?
        """, (node_id, node_id)).fetchone()['cnt']
        return count

    def delete_node(self, node_id: str) -> bool:
        """Delete a node and its edges."""
        # Execute pre-delete hooks (invariant enforcement - protects core kernel)
        if not _execute_hook("PRE_DELETE", "delete_node", {"node_id": node_id, "id": node_id}):
            return False

        conn = self._get_conn()
        try:
            # Check if protected
            node = self.get_node(node_id)
            if node and node.protected:
                LOG.warning(f"Cannot delete protected node: {node_id}")
                return False

            # Delete edges
            conn.execute("DELETE FROM edges WHERE src = ? OR dst = ?", (node_id, node_id))
            # Delete from FTS
            conn.execute("DELETE FROM memory_fts WHERE node_id = ?", (node_id,))
            # Delete node
            conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
            conn.commit()

            # Execute post-delete hooks
            _execute_hook("POST_DELETE", "delete_node", {"node_id": node_id})
            return True
        except Exception as e:
            LOG.error(f"Failed to delete node: {e}")
            return False

    def set_protected(self, node_id: str, protected: bool) -> bool:
        """Set protection flag on a node."""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE nodes SET protected = ? WHERE id = ?",
                (1 if protected else 0, node_id)
            )
            conn.commit()
            return True
        except Exception as e:
            LOG.error(f"Failed to set protection: {e}")
            return False

    def get_stats(self) -> dict:
        """Get storage statistics."""
        conn = self._get_conn()
        return {
            "nodes": conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
            "edges": conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
            "events": conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
            "claims": conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0],
        }


class VectorStore:
    """
    Vector Store - The Semantic Field

    Meaning search, not truth.
    Uses all-MiniLM-L6-v2 by default.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None
        self._vectors: Dict[str, np.ndarray] = {}
        self._lock = threading.Lock()
        self._index_file = DB_DIR / "titan_vectors.npz"
        self._ids_file = DB_DIR / "titan_vector_ids.json"
        self._load_index()

    def _get_model(self):
        """Lazy load embedding model via shared EmbeddingService."""
        if self._model is None:
            try:
                from services.embedding_service import get_embedding_service
                self._model = get_embedding_service()
                LOG.info("Using shared EmbeddingService for Titan vectors")
            except ImportError:
                # Fallback to direct model load
                from sentence_transformers import SentenceTransformer
                LOG.info(f"Loading embedding model directly: {self.model_name}")
                self._model = SentenceTransformer(self.model_name)
                LOG.info("Embedding model loaded (standalone)")
        return self._model

    def _load_index(self):
        """Load vector index from disk."""
        try:
            if self._index_file.exists() and self._ids_file.exists():
                data = np.load(str(self._index_file))
                ids = json.loads(self._ids_file.read_text())
                vectors = data['vectors']
                for i, node_id in enumerate(ids):
                    if i < len(vectors):
                        self._vectors[node_id] = vectors[i]
                LOG.debug(f"Loaded {len(self._vectors)} vectors from disk")
        except Exception as e:
            LOG.warning(f"Failed to load vector index: {e}")

    def _save_index(self):
        """Save vector index to disk."""
        try:
            with self._lock:
                if not self._vectors:
                    return
                ids = list(self._vectors.keys())
                vectors = np.array([self._vectors[i] for i in ids])
                np.savez_compressed(str(self._index_file), vectors=vectors)
                self._ids_file.write_text(json.dumps(ids))
        except Exception as e:
            LOG.error(f"Failed to save vector index: {e}")

    def embed(self, text: str) -> np.ndarray:
        """Generate embedding for text."""
        model = self._get_model()
        # Works with both EmbeddingService (embed_text) and SentenceTransformer (encode)
        if hasattr(model, 'embed_text'):
            return model.embed_text(text)
        return model.encode(text, convert_to_numpy=True)

    def add(self, node_id: str, text: str):
        """Add vector for a node."""
        with self._lock:
            vector = self.embed(text)
            self._vectors[node_id] = vector
        # Periodically save
        if len(self._vectors) % 100 == 0:
            self._save_index()

    def remove(self, node_id: str):
        """Remove vector for a node."""
        with self._lock:
            self._vectors.pop(node_id, None)

    def search(self, query: str, limit: int = 10) -> List[Tuple[str, float]]:
        """
        Search for similar vectors.
        Returns (node_id, similarity) pairs.
        """
        if not self._vectors:
            return []

        query_vec = self.embed(query)

        with self._lock:
            ids = list(self._vectors.keys())
            vectors = np.array([self._vectors[i] for i in ids])

        # Cosine similarity
        norms = np.linalg.norm(vectors, axis=1) * np.linalg.norm(query_vec)
        norms[norms == 0] = 1  # Avoid division by zero
        similarities = np.dot(vectors, query_vec) / norms

        # Get top results
        top_indices = np.argsort(similarities)[::-1][:limit]
        results = [(ids[i], float(similarities[i])) for i in top_indices]

        return results

    def save(self):
        """Force save index."""
        self._save_index()

    def get_stats(self) -> dict:
        """Get vector store statistics."""
        return {
            "vectors": len(self._vectors),
            "model": self.model_name,
        }


class KnowledgeGraph:
    """
    Knowledge Graph - The Structure

    Explicit relations with traversal.
    Every edge has confidence, origin, and timestamp.
    """

    def __init__(self, sqlite_store: SQLiteStore):
        self.store = sqlite_store

    def add_relation(self, subject: str, predicate: str, obj: str,
                     confidence: float = 0.5, origin: str = "inference") -> bool:
        """Add a relation between entities."""
        # Ensure nodes exist
        now = datetime.now().isoformat()

        # Create subject node if not exists
        if not self.store.get_node(subject):
            self.store.add_node(Node(
                id=subject,
                type="entity",
                label=subject,
                created_at=now
            ))

        # Create object node if not exists
        if not self.store.get_node(obj):
            self.store.add_node(Node(
                id=obj,
                type="entity",
                label=obj,
                created_at=now
            ))

        # Add edge
        edge = Edge(
            src=subject,
            dst=obj,
            relation=predicate,
            confidence=confidence,
            origin=origin,
            created_at=now
        )
        return self.store.add_edge(edge)

    def traverse(self, start_node: str, hops: int = 2,
                 min_confidence: float = 0.3) -> List[dict]:
        """
        Traverse graph from a starting node.
        Limited to N hops for performance.
        """
        visited = set()
        results = []
        queue = [(start_node, 0)]

        while queue:
            node_id, depth = queue.pop(0)

            if node_id in visited or depth > hops:
                continue
            visited.add(node_id)

            node = self.store.get_node(node_id)
            if node:
                results.append({
                    "node": node.to_dict(),
                    "depth": depth,
                })

            # Get connected edges
            if depth < hops:
                edges = self.store.get_edges(node_id)
                for edge in edges:
                    if edge.confidence >= min_confidence:
                        next_node = edge.dst if edge.src == node_id else edge.src
                        if next_node not in visited:
                            queue.append((next_node, depth + 1))
                            results.append({
                                "edge": edge.to_dict(),
                                "depth": depth,
                            })

        return results

    def get_related(self, node_id: str, relation: str = None) -> List[dict]:
        """Get directly related nodes."""
        edges = self.store.get_edges(node_id, direction="out")
        results = []

        for edge in edges:
            if relation is None or edge.relation == relation:
                target = self.store.get_node(edge.dst)
                if target:
                    results.append({
                        "node": target.to_dict(),
                        "relation": edge.relation,
                        "confidence": edge.confidence,
                    })

        return results


class TriHybridStorage:
    """
    Combined Tri-Hybrid Storage Layer.

    Coordinates SQLite, Vector Store, and Knowledge Graph.
    """

    def __init__(self):
        self.sqlite = SQLiteStore()
        self.vectors = VectorStore()
        self.graph = KnowledgeGraph(self.sqlite)
        LOG.info("Tri-Hybrid Storage initialized")

    def add_memory(self, node_id: str, text: str, node_type: str = "memory",
                   metadata: dict = None, protected: bool = False) -> bool:
        """Add a memory item to all stores."""
        now = datetime.now().isoformat()

        # Add to SQLite
        node = Node(
            id=node_id,
            type=node_type,
            label=text[:100],  # Short label
            created_at=now,
            protected=protected,
            metadata=metadata or {}
        )
        if not self.sqlite.add_node(node):
            return False

        # Add to FTS
        self.sqlite.index_for_fts(node_id, text, metadata)

        # Add to vector store
        self.vectors.add(node_id, text)

        return True

    def search(self, query: str, limit: int = 10) -> List[dict]:
        """
        Search across all stores.
        Returns combined, deduplicated results.
        """
        results = {}

        # Vector search
        for node_id, score in self.vectors.search(query, limit * 2):
            if node_id not in results:
                results[node_id] = {"id": node_id, "vector_score": score}
            else:
                results[node_id]["vector_score"] = score

        # FTS search
        for node_id, score in self.sqlite.search_fts(query, limit * 2):
            if node_id not in results:
                results[node_id] = {"id": node_id, "fts_score": score}
            else:
                results[node_id]["fts_score"] = score

        # Enrich with node data
        for node_id in results:
            node = self.sqlite.get_node(node_id)
            if node:
                results[node_id]["node"] = node.to_dict()

        return list(results.values())[:limit]

    def get_stats(self) -> dict:
        """Get storage statistics."""
        return {
            "sqlite": self.sqlite.get_stats(),
            "vectors": self.vectors.get_stats(),
        }

    def save(self):
        """Persist all data."""
        self.vectors.save()
