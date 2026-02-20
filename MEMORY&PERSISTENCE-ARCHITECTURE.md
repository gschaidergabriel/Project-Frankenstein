# FRANK MEMORY & PERSISTENCE ARCHITECTURE

## Executive Summary

Frank's memory system is a **multi-layer, semantically-aware persistence architecture** spanning 6+ SQLite databases, a shared embedding service, and a unified query API. All processing is 100% local — no external databases, vector stores, or APIs.

### Core Capabilities

- **Hybrid Chat Search**: FTS5 keyword + MiniLM-L6-v2 vector cosine + RRF fusion
- **Dynamic Context Budget**: Cosine-similarity channel boosting, proportional allocation with minimums
- **Unified MemoryHub**: Single query API across 5 memory layers with RRF fusion + budget packing
- **Session Compression**: Auto-close idle sessions (30min), batch LLM summarization with keyword fallback
- **User Preference Learning**: Bilingual regex extraction (DE+EN), confidence-weighted, UNIQUE(key, value)
- **Titan Integrity**: FK ON + CASCADE, 24h node protection, nightly consistency daemon
- **Retrieval Metrics**: Per-query logging (sources, latency, chars), nightly pruning
- **Shared Embeddings**: Single MiniLM-L6-v2 instance (~90MB) used by Chat, Titan, and Budget Allocator

---

## Architecture Overview

```
                    USER INPUT
                        |
                        v
        +---------------------------------------+
        |   OVERLAY UI (chat_mixin.py)          |
        |   - Receives user message             |
        |   - Embeds query (MiniLM-L6-v2)       |
        |   - Dynamic budget allocation         |
        |   - Preference injection              |
        +------------------+--------------------+
                           |
                           v
        +------------------------------------------+
        |  Context Building Layer                   |
        |                                           |
        |  EmbeddingService  --> query_vec (384d)   |
        |       |                                   |
        |       v                                   |
        |  allocate_budget() --> per-channel chars   |
        |       |                                   |
        |       v                                   |
        |  build_workspace(budget=...)              |
        |    +- Chat: _hybrid_search_history()      |
        |    +- Titan: retrieve() [tri-hybrid]      |
        |    +- Consciousness: ACT-R activation     |
        |    +- World Exp: causal patterns          |
        |    +- E-PQ: personality context           |
        |    +- Preferences: top-5 learned prefs    |
        +------------------+------------------------+
                           |
                           v
        +------------------------------------------+
        |  CORE API (core/app.py :8088)             |
        |  - Routes to Router API                   |
        |  - system = get_frank_identity()          |
        +------------------+------------------------+
                           |
                           v
        +------------------------------------------+
        |  ROUTER API (:8091)                       |
        |  - Routes to Llama or Qwen                |
        |  - Instruct prompt wrapping               |
        +------------------+------------------------+
                           |
                           v
        +------------------------------------------+
        |  LLM RESPONSE --> saved to:               |
        |    +- chat_memory.db (message + embedding)|
        |    +- titan.db (entities, relations)       |
        |    +- consciousness.db (experience vec)    |
        |    +- world_experience.db (E-PQ update)    |
        |    +- user_preferences (regex extraction)  |
        |    +- retrieval_metrics (query stats)       |
        +-------------------------------------------+
```

---

## Layer 1: Chat Memory (Conversational + Semantic)

### Location
- **File**: `services/chat_memory.py`
- **Database**: `database/chat_memory.db`

### Schema

```sql
-- Main message store
CREATE TABLE messages (
    id          INTEGER PRIMARY KEY,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,       -- 'user', 'frank', 'system'
    sender      TEXT NOT NULL,       -- 'Du', 'Frank'
    text        TEXT NOT NULL,
    is_user     INTEGER NOT NULL,
    is_system   INTEGER NOT NULL,
    timestamp   REAL NOT NULL,
    created_at  TEXT NOT NULL
);

-- Session tracking with auto-summarization
CREATE TABLE sessions (
    session_id      TEXT PRIMARY KEY,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    message_count   INTEGER DEFAULT 0,
    summary         TEXT DEFAULT ''
);

-- Semantic embeddings (MiniLM-L6-v2, 384-dim float32)
CREATE TABLE message_embeddings (
    message_id  INTEGER PRIMARY KEY,
    embedding   BLOB NOT NULL,       -- 384 x float32 = 1536 bytes
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
);

-- Learned user preferences
CREATE TABLE user_preferences (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    key             TEXT NOT NULL,       -- 'dislikes', 'prefers', 'habit'
    value           TEXT NOT NULL,       -- normalized: strip + lower + collapse whitespace
    confidence      REAL DEFAULT 0.7,
    source          TEXT,                -- 'pattern' or 'llm_extract'
    created_at      TEXT NOT NULL,
    last_confirmed  TEXT,
    UNIQUE(key, value)
);

-- Query performance tracking
CREATE TABLE retrieval_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    query_hash      TEXT,
    sources_used    TEXT,               -- JSON: {"chat_fts": 2, "titan": 1}
    chars_injected  INTEGER,
    budget_chars    INTEGER,
    latency_ms      INTEGER,
    timestamp       REAL
);

-- Full-text search (keyword matching)
CREATE VIRTUAL TABLE messages_fts USING fts5(text, content=messages, content_rowid=id);
```

### Key Methods

```python
class ChatMemoryDB:
    # Storage (inline-embeds + preference-extraction on every message)
    store_message(session_id, role, sender, text, is_user, is_system) -> int

    # Hybrid search: FTS5 + Vector cosine + RRF fusion (K=60)
    _hybrid_search_history(query, limit=5, exclude_recent=10) -> List[dict]

    # Context assembly (uses hybrid search internally)
    build_smart_context(query, recent_count=5, max_chars=2000) -> str

    # Embedding backfill (crash-safe via backfill_state.json)
    backfill_embeddings(batch_size=64, max_seconds=60.0) -> int

    # Session management
    close_idle_sessions(idle_minutes=30) -> int
    get_sessions_for_summarization(limit=3) -> List[dict]
    store_session_summary(session_id, summary)

    # Preferences
    get_top_preferences(limit=5) -> List[dict]

    # Metrics
    record_retrieval_metric(query_hash, sources_used, chars_injected, budget_chars, latency_ms)
    get_retrieval_stats(days=7) -> dict
```

### Hybrid Search Algorithm

```
Query: "Wird es morgen regnen?"

1. FTS5 Search (keyword)
   - Matches: "regnen", "morgen", "Wetter"
   - Returns ranked results by BM25 score

2. Vector Search (semantic)
   - Embed query -> 384-dim vector
   - Cosine similarity against message_embeddings
   - Returns top-20 candidates
   - Finds: "Wie ist das Wetter?" (no keyword overlap!)

3. RRF Fusion (K=60)
   - For each result ID:
     score = 1/(60 + fts_rank) + 1/(60 + vector_rank)
   - Sort by fused score descending
   - Return top-N

Performance: ~30ms per query (20ms embed + 1ms search + 10ms FTS5)
```

### Embedding Backfill

- Runs on startup in background thread (non-blocking)
- Batch size: 64 messages per cycle, 0.5s sleep between batches
- Crash-safe: `backfill_state.json` tracks `last_message_id`
- Timeout: max 60s total, resumes next startup
- Progress logging every 5 batches

---

## Layer 2: Episodic Memory — TITAN (Knowledge Graph)

### Location
- **Files**: `tools/titan/`
  - `titan_core.py` — Main orchestrator
  - `storage.py` — Tri-hybrid storage (SQLite + vectors + graph)
  - `ingestion.py` — Claim extraction (pattern-based)
  - `retrieval.py` — Context assembly (tri-hybrid search)
  - `maintenance.py` — Pruning, decay, protection lifecycle
- **Database**: `database/titan.db`

### Schema

```sql
PRAGMA foreign_keys = ON;   -- Prevents orphaned edges

CREATE TABLE nodes (
    id              TEXT PRIMARY KEY,
    type            TEXT,           -- 'entity', 'concept', 'event', 'claim', 'code'
    label           TEXT,
    created_at      TEXT,
    protected       BOOLEAN DEFAULT FALSE,
    metadata        TEXT            -- JSON: {confidence, unprotect_after, ...}
);

CREATE TABLE edges (
    src_id          TEXT NOT NULL,
    dst_id          TEXT NOT NULL,
    relation        TEXT NOT NULL,
    confidence      REAL,
    origin          TEXT,           -- 'user', 'code', 'inference'
    created_at      TEXT,
    UNIQUE(src_id, dst_id, relation),
    FOREIGN KEY (src_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (dst_id) REFERENCES nodes(id) ON DELETE CASCADE
);

CREATE TABLE claims (
    id              TEXT PRIMARY KEY,
    node_id         TEXT NOT NULL,
    claim_text      TEXT,
    confidence      REAL DEFAULT 0.5,
    time_window     TEXT,
    counter_claim   TEXT,
    evidence_count  INTEGER DEFAULT 1,
    created_at      TEXT
);
```

### Architecture: Tri-Hybrid Storage

```
+-----------------------------------------------------------+
|                    TITAN CORE                               |
|  (Orchestrator: ingest -> architect -> storage)            |
+---------+-----------------+-----------------+--------------+
          |                 |                 |
          v                 v                 v
    +----------+      +-----------+     +--------------+
    |  SQLite  |      |  Vectors  |     |  Knowledge   |
    |  Ledger  |      |  Store    |     |  Graph       |
    |          |      |  (in-mem) |     |              |
    | - Nodes  |      |  Model:   |     | - Entities   |
    | - Edges  |      |  Shared   |     | - Relations  |
    | - Claims |      |  Embed-   |     | - Confidence |
    | - FTS    |      |  ding-    |     |   decay      |
    |          |      |  Service  |     |              |
    +----------+      +-----------+     +--------------+
```

### Protection Mechanism (NEW)

New nodes receive 24h protection against premature pruning:

```python
# ingestion.py: Memory chunks get protected status
metadata = {
    "confidence": max(base_confidence, 0.8),
    "protected": True,
    "unprotect_after": (now + timedelta(hours=24)).isoformat()
}

# maintenance.py: _unprotect_expired_nodes() runs before decay
# Checks metadata.unprotect_after, removes protection after 24h window
```

### Maintenance Engine

| Parameter | Value |
|-----------|-------|
| Confidence decay half-life | 7 days |
| Prune threshold | confidence < 0.2 AND age > 7 days |
| Max nodes (soft) | 10,000 |
| Max nodes (hard) | 50,000 |
| Protection window | 24 hours |
| Maintenance interval | 1 hour |

### Shared Embedding Model

Titan's `VectorStore._get_model()` now uses the shared `EmbeddingService` singleton instead of loading its own model instance. Saves ~90MB RAM.

---

## Layer 3: Personality State — E-PQ (Emotional/Procedural)

### Location
- **File**: `personality/e_pq.py`
- **Database**: `database/world_experience.db`

### 5 Continuous Personality Vectors (-1.0 to 1.0)

| Vector | Low End | High End |
|--------|---------|----------|
| `precision_val` | Creativity | Accuracy |
| `risk_val` | Caution | Boldness |
| `empathy_val` | Detached | Empathetic |
| `autonomy_val` | Dependent | Independent |
| `vigilance_val` | Relaxed | Anxious |

### Update Mechanism

```python
learning_rate = BASE_LEARNING_RATE * (AGE_DECAY_FACTOR ** days_since_creation)

EVENT_WEIGHTS = {
    "chat": 0.2, "voice_interaction": 0.3,
    "positive_feedback": 0.3, "negative_feedback": 0.4,
    "task_success": 0.3, "task_failure": 0.5,
    # ... 15+ types
}
```

---

## Layer 4: Consciousness Stream (Continuous Monitoring)

### Location
- **File**: `services/consciousness_daemon.py`
- **Database**: `database/consciousness.db`
- **Runs as**: User systemd service `aicore-consciousness.service`

### Components

| Component | Purpose | Refresh |
|-----------|---------|---------|
| Workspace State (GWT) | CPU, GPU, temp, network | 30s |
| Experience Vectors (HOT-4) | 64-dim embedding, novelty tracking | 60s |
| Mood Trajectory | 200-point buffer (~3.3h) | 60s |
| Perceptual Loop | 200ms hardware sampling | 200ms |
| Reflections | Inner monologue (120 tokens) | On trigger, max 1/120s |
| Predictions | Anticipation + truth tracking | On trigger |
| Sleep Consolidation | Working -> long-term chunks | 6h |

---

## Layer 5: World Experience (Causal Learning)

### Location
- **File**: `tools/world_experience_daemon.py`
- **Database**: `database/world_experience.db`

### Schema

```sql
CREATE TABLE entities (
    id          INTEGER PRIMARY KEY,
    entity_type TEXT,          -- 'hardware', 'software', 'event'
    name        TEXT UNIQUE,
    metadata    TEXT,
    first_seen  TEXT,
    last_seen   TEXT
);

CREATE TABLE causal_links (
    id                  INTEGER PRIMARY KEY,
    cause_entity_id     INTEGER,
    effect_entity_id    INTEGER,
    relation_type       TEXT,  -- 'triggers', 'inhibits', 'modulates'
    confidence          REAL,  -- Bayesian P(H|E)
    observation_count   INTEGER,
    last_validated      TEXT,
    status              TEXT   -- 'active', 'legacy', 'invalidated'
);

CREATE TABLE fingerprints (
    id              INTEGER PRIMARY KEY,
    causal_link_id  INTEGER,
    timestamp       TEXT,
    thermal_vector  TEXT,      -- JSON: temp, power, frequency
    logical_vector  TEXT,      -- JSON: CPU%, GPU%, RAM%
    temporal_vector TEXT,      -- JSON: hour, day_of_week
    fidelity_level  TEXT       -- 'raw' (0-7d), 'dense' (8-90d), 'sparse' (>90d)
);
```

### Features
- **Bayesian Erosion**: Epsilon = 0.01, 5-minute batch window
- **Quantization Tiers**: Raw (0-7d) -> Dense 4-bit (8-90d) -> Sparse Bayesian (>90d)
- **Size Enforcement**: Hard cap 10 GB, quantize at 8 GB, purge at 9 GB

---

## Layer 6: Pattern Memory (Anticipation)

### Location
- **File**: `services/genesis/reflection/pattern_memory.py`

### Pattern Types

| Type | Trigger | Minimum Observations |
|------|---------|---------------------|
| Temporal | Frequency > 30% at hour | 5 |
| Causal | Sequence within 5 min | 3 |

- Success rate: EMA `rate = 0.7 * rate + 0.3 * correct`
- Cleanup: Prune if `success_rate < 0.2` after 10+ occurrences

---

## Cross-Layer Services

### Shared Embedding Service

**File**: `services/embedding_service.py`

```python
class EmbeddingService:
    """Singleton, thread-safe MiniLM-L6-v2 wrapper. ~90MB RAM, lazy-loaded."""

    embed_text(text: str) -> np.ndarray          # 384-dim
    embed_batch(texts: list, batch_size=64) -> np.ndarray
    cosine_similarity(vec_a, vec_b) -> float
    cosine_search(query_vec, vectors, ids, top_k=10) -> List[Tuple[str, float]]
```

Used by: ChatMemoryDB (hybrid search), Titan VectorStore, Context Budget Allocator

### Unified Memory Hub

**File**: `services/memory_hub.py`

```python
@dataclass
class MemoryItem:
    text: str
    source: str          # 'chat_fts', 'chat_vector', 'titan', 'consciousness',
                         # 'world_exp', 'preference'
    confidence: float
    timestamp: float     # Unix timestamp (unified across all layers)
    rrf_score: float
    pack_score: float    # rrf_score * recency_penalty

@dataclass
class MemoryResult:
    items: List[MemoryItem]
    total_chars: int
    sources_used: Dict[str, int]   # {"chat_fts": 2, "titan": 1, ...}
    latency_ms: float

class MemoryHub:
    """Unified query across all 5 memory layers with RRF fusion."""

    def query(self, text, budget_chars=1000, source_attribution=True) -> MemoryResult:
        all_items  = self._query_chat(text)           # Hybrid FTS5 + vector
        all_items += self._query_titan(text)           # Knowledge graph
        all_items += self._query_consciousness(text)   # ACT-R activation
        all_items += self._query_world_exp(text)       # Causal patterns
        all_items += self._query_preferences(text)     # Learned user prefs

        fused = self._reciprocal_rank_fusion(all_items)
        return self._pack_to_budget(fused, budget_chars)

    def _pack_to_budget(self, items, budget_chars) -> MemoryResult:
        """Greedy packing: rrf_score * recency_penalty, highest first."""
        # pack_score = rrf_score * (0.95 ^ (age_hours / 24))
        # Pack items until budget exhausted, truncate last if >50 chars remain
```

### Dynamic Context Budget

**File**: `ui/overlay/context_budget.py`

```python
CHANNEL_PRIORITIES = {
    "recent_conversation": 0.9,    # Always important
    "semantic_matches":    0.7,    # +0.3 * cosine(query, history_summary)
    "titan_memory":        0.4,    # +0.3 * cosine(query, titan_summary)
    "ego_mood_identity":   0.3,    # Fixed (personality always relevant)
    "world_experience":    0.2,    # +0.3 * cosine(query, world_summary)
    "news_akam":           0.0,    # +0.8 when triggered
}

CHANNEL_MINIMUMS = {
    "recent_conversation": 200,
    "ego_mood_identity":   80,
}

def allocate_budget(total_chars, channels, query_vec=None) -> Dict[str, int]:
    """Proportional allocation with cosine-similarity boosting."""
    # 1. Compute effective priority per channel
    #    If query_vec and summary_vec available: base + 0.3 * cosine_similarity
    # 2. Normalize proportionally
    # 3. Enforce minimums, cap total

class ChannelSummaryCache:
    """Cached summary embeddings per channel, refreshed every 60 min."""
    TTL = 3600  # seconds
    # Embeds: last 5 messages, last 3 session summaries, top-10 Titan nodes,
    #         active causal links
```

### User Preference Extraction

**File**: `services/preference_extractor.py`

```python
def extract_preferences(text: str) -> List[Tuple[str, str]]:
    """Bilingual regex extraction (DE + EN). ~1ms per message."""

# Patterns:
#   Dislikes: "ich mag kein X", "hasse X", "bitte nie X", "finde X nervig"
#   Prefers:  "bevorzuge X", "mag lieber X", "finde X gut"
#   Habits:   "mach immer X", "will grundsaetzlich X"
#   English:  "don't like X", "prefer X", "always X"
#
# Values normalized: strip + lower + collapse whitespace
# Min 3 chars, max 200 chars, deduplicated
# Stored with confidence=0.6 (regex), 0.85 (future LLM extractor)
```

### Memory Consistency Daemon

**File**: `services/memory_consistency.py`

```python
class MemoryConsistencyDaemon:
    """Nightly cross-layer integrity checks (max 1x per 24h)."""

    def run_nightly(self) -> dict:
        self._check_titan_orphans()       # DELETE edges without nodes
        self._check_embedding_gaps()      # Backfill missing embeddings
        self._prune_old_metrics()         # Remove retrieval_metrics > 30 days
        self._collect_stats()             # Cross-layer DB statistics
        return health_report
```

Integrated into `persistence_mixin._memory_maintenance_timer()` (runs hourly).

---

## Session Management

### Lifecycle

```
Session Start (boot_id based)
     |
     v
Messages stored (inline embed + preference extract)
     |
     v
Idle > 30 min  -->  close_idle_sessions()  -->  Session ended
     |
     v
Batch summarization (up to 3 sessions per cycle)
  +- LLM summarization (primary, ~30s timeout)
  +- Keyword extraction (fallback if LLM fails)
     |
     v
Old messages archived (retention: 30 days)
```

### Maintenance Timer

```python
# persistence_mixin.py - runs every 60 minutes
def _memory_maintenance_timer(self):
    1. close_idle_sessions(idle_minutes=30)        # Auto-close stale sessions
    2. _batch_session_summaries(max_sessions=3)    # LLM + keyword fallback
    3. cleanup_old_messages(retention_days=30)      # Archive old messages
    4. MemoryConsistencyDaemon.run_nightly()        # Cross-layer checks (1x/day)
```

---

## Complete Data Flow Example

```
1. USER INPUT: "Was haben wir ueber Wetter gesprochen?"

2. EMBEDDING:
   query_vec = EmbeddingService.embed_text("Was haben wir ueber Wetter gesprochen?")
   -> 384-dim float32 vector

3. BUDGET ALLOCATION:
   allocate_budget(
       total_chars = (MAX_TOKENS - user_tokens - overhead) * CHARS_PER_TOKEN,
       channels = {channel: summary_vec for each},
       query_vec = query_vec
   )
   -> {"recent_conversation": 900, "semantic_matches": 500, "titan_memory": 300, ...}

4. CONTEXT BUILDING (workspace with budget):
   +- Chat: _hybrid_search_history("Wetter")
   |  +- FTS5: finds "Wetter", "regnen"          (keyword match)
   |  +- Vector: finds "Wird es morgen sonnig?"   (semantic match, no keyword overlap!)
   |  +- RRF fusion: merged ranking
   |
   +- Titan: retrieve("Wetter")
   |  +- Vector + FTS + Graph expansion
   |  +- Returns nodes: "Wetter_Berlin", "Regen_Vorhersage"
   |
   +- Consciousness: get_relevant_memories("Wetter")
   +- World Experience: context_inject("Wetter")
   +- E-PQ: get_personality_context()
   +- Preferences: get_top_preferences(5) -> "dislikes: lange antworten"

5. CORE API (POST /route/stream):
   payload = {
       "text": "[INNER_WORLD]...[/INNER_WORLD]\nUser: Was haben wir ueber Wetter gesprochen?",
       "system": get_frank_identity()
   }

6. LLM RESPONSE saved to:
   +- chat_memory.db     (message + 384-dim embedding)
   +- titan.db           (extracted entities/relations, protected 24h)
   +- consciousness.db   (experience vector, mood point)
   +- world_experience.db (E-PQ personality update)
   +- retrieval_metrics  (query stats: sources, latency, chars)
```

---

## Database Summary

| Database | Purpose | Key Tables | Refresh |
|----------|---------|------------|---------|
| `chat_memory.db` | Messages, embeddings, preferences, metrics | messages, message_embeddings, user_preferences, retrieval_metrics, sessions | Per message |
| `titan.db` | Episodic knowledge graph + vectors | nodes, edges, claims, memory_fts | Per response |
| `consciousness.db` | Workspace state, mood, reflections | workspace_state, experience_vectors, mood_trajectory | 30s/60s |
| `world_experience.db` | E-PQ personality + causal links | entities, causal_links, fingerprints | Per event |
| `e_cpmm.db` | Core Performance Memory Matrix | | On update |
| `e_sir.db` | Situational Information Retrieval | | On update |

---

## System Prompt Flow

```python
# core/app.py
identity = get_frank_identity()  # personality.build_system_prompt()

router_payload = {
    "text": grounded_text,       # User query + assembled workspace context
    "n_predict": max_tokens,
    "system": identity,          # CRITICAL: system prompt passed as 'system' parameter
}
```

System prompt source:
```python
# personality/__init__.py
def build_system_prompt(runtime_context=None) -> str:
    """Build from:
    1. frank.persona.json (static identity)
    2. E-PQ (personality state vectors)
    3. Ego-Construct (agency/embodiment)
    4. Runtime context (workspace state)
    """
```

---

## Final Architecture Diagram

```
                    +-------------------------------------+
                    |    FRANK MEMORY SYSTEM v2.0          |
                    |   (Multi-Layer Semantic Persistence) |
                    +-----------------+-------------------+
                                      |
            +-------------------------+---------------------------+
            |                         |                           |
            v                         v                           v
    +----------------+        +---------------+          +----------------+
    | Chat Memory    |        | Episodic      |          | Personality    |
    | (Hybrid Search)|        | Memory        |          | State          |
    |                |        | (Titan)       |          | (E-PQ)         |
    | - Messages     |        | - Nodes       |          | - 5 vectors    |
    | - Embeddings   |        | - Edges (FK)  |          | - Mood buffer  |
    | - FTS5         |        | - Claims      |          | - Confidence   |
    | - Preferences  |        | - Vectors     |          +----------------+
    | - Metrics      |        | - FTS         |
    +----------------+        +---------------+
            |                         |
            +----------+--------------+
                       |
                       v
              +-----------------+
              | EmbeddingService|
              | (Shared         |
              |  MiniLM-L6-v2)  |
              |  ~90MB, singleton|
              +-----------------+
                       |
            +----------+----------+
            |                     |
            v                     v
    +----------------+    +----------------+
    | MemoryHub      |    | Context Budget |
    | (Unified Query)|    | (Dynamic       |
    |                |    |  Allocation)   |
    | 5-layer RRF    |    | Cosine-boost   |
    | fusion +       |    | per channel    |
    | budget packing |    +----------------+
    +----------------+
            |
            +---------------------------+---------------------------+
            |                           |                           |
            v                           v                           v
    +----------------+          +----------------+          +---------------+
    | Consciousness  |          | World Exp.     |          | Patterns      |
    | Stream         |          | (Causal)       |          | (Temporal)    |
    |                |          |                |          |               |
    | - Workspace    |          | - Entities     |          | - Temporal    |
    | - Mood arc     |          | - Causal links |          | - Causal      |
    | - Experience   |          | - Fingerprints |          | - Success     |
    |   vectors      |          +----------------+          |   rates       |
    | - Reflections  |                                      +---------------+
    +----------------+
            |
    +-------v--------+
    | Consistency    |
    | Daemon         |
    | (Nightly)      |
    |                |
    | - Titan orphans|
    | - Embed gaps   |
    | - Metrics prune|
    | - Health report|
    +----------------+
```

---

## File Index

| File | Purpose |
|------|---------|
| `services/chat_memory.py` | Chat persistence, hybrid search, preferences, metrics |
| `services/embedding_service.py` | Shared MiniLM-L6-v2 singleton |
| `services/memory_hub.py` | Unified cross-layer query API |
| `services/memory_consistency.py` | Nightly integrity checks |
| `services/preference_extractor.py` | Bilingual regex preference extraction |
| `ui/overlay/context_budget.py` | Dynamic budget allocator + channel cache |
| `ui/overlay/workspace.py` | Workspace assembly (budget-aware) |
| `ui/overlay/mixins/chat_mixin.py` | Chat flow: embed -> budget -> workspace -> API |
| `ui/overlay/mixins/persistence_mixin.py` | Session management, maintenance timer |
| `tools/titan/titan_core.py` | Titan orchestrator |
| `tools/titan/storage.py` | Tri-hybrid storage (FK ON, CASCADE) |
| `tools/titan/ingestion.py` | Claim extraction, 24h node protection |
| `tools/titan/retrieval.py` | Titan retrieval (vector + FTS + graph) |
| `tools/titan/maintenance.py` | Confidence decay, protection lifecycle, pruning |
| `personality/e_pq.py` | 5-vector personality state |
| `services/consciousness_daemon.py` | Continuous workspace/mood monitoring |
| `tools/world_experience_daemon.py` | Causal learning from observations |

---

*Updated 2026-02-20 — v2.0 post memory system upgrade. All persistence is 100% local, no external databases or APIs.*
