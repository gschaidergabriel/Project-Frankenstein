# FRANK MEMORY & PERSISTENCE ARCHITECTURE

## Executive Summary

Frank's memory system is **layered and distributed** across multiple SQLite databases and Python services, implementing a sophisticated multi-tier approach combining:
- **Chat Memory** (ephemeral conversation history with FTS5 semantic search)
- **Episodic Memory** (Titan: knowledge graph + vector embeddings)
- **Personality/Procedural Memory** (E-PQ: emotional state evolution)
- **Consciousness Stream** (continuous workspace monitoring + mood tracking)
- **World Experience** (causal learning from system observations)
- **Pattern Memory** (temporal/causal anticipation)

**No external databases or vector stores** — everything is local SQLite + in-process Python objects.

---

## Architecture Overview

```
                    USER INPUT
                        │
                        ▼
        ┌───────────────────────────────────┐
        │   OVERLAY UI (chat_mixin.py)      │
        │   - Receives user message         │
        │   - Builds context from history   │
        │   - Personality injection         │
        └─────────────┬─────────────────────┘
                      │
                      ▼
        ┌──────────────────────────────────────┐
        │  Context Building Layer               │
        │  - ChatMemoryDB.build_smart_context() │
        │  - Titan episodic retrieval           │
        │  - E-PQ personality context          │
        │  - Consciousness workspace state     │
        │  - World Experience causal knowledge │
        └─────────────┬──────────────────────────┘
                      │
                      ▼
        ┌──────────────────────────────────┐
        │  CORE API (core/app.py :8088)    │
        │  - Routes to Router API          │
        │  - Enrichment (hardware, Darknet)│
        │  - Output-Feedback-Loop          │
        └─────────────┬────────────────────┘
                      │
                      ▼
        ┌──────────────────────────────────┐
        │  ROUTER API (:8091)              │
        │  - Routes to Llama or Qwen       │
        │  - Instruct prompt wrapping      │
        │  - Memory pressure control       │
        └─────────────┬────────────────────┘
                      │
                      ▼
        ┌──────────────────────────────────┐
        │  LLM Inference                   │
        │  - Llama 3 Instruct              │
        │  - Qwen 2.5 Instruct (ChatML)    │
        └─────────────┬────────────────────┘
                      │
                      ▼
        ┌─────────────────────────────────────┐
        │  Output Processing                  │
        │  - Save to chat_memory.db           │
        │  - Titan ingestion (episodic)       │
        │  - Consciousness daemon recording   │
        │  - E-PQ self-feedback loop          │
        │  - World Experience causal update   │
        └─────────────┬───────────────────────┘
                      │
                      ▼
        ┌──────────────────────────────────┐
        │  UI Display (overlay)            │
        │  - Message bubbles               │
        │  - Wallpaper events              │
        └──────────────────────────────────┘
```

---

## Layer 1: Chat Memory (Conversational)

### Location
- **File**: `services/chat_memory.py`
- **Database**: `database/chat_memory.db` (376 KB)

### Schema
```sql
-- Main message store
CREATE TABLE messages (
    id          INTEGER PRIMARY KEY,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,       -- 'user', 'frank', etc.
    sender      TEXT NOT NULL,       -- 'Du', 'Frank'
    text        TEXT NOT NULL,
    is_user     INTEGER NOT NULL,
    is_system   INTEGER NOT NULL,
    timestamp   REAL NOT NULL,
    created_at  TEXT NOT NULL
);

-- Session tracking
CREATE TABLE sessions (
    session_id      TEXT PRIMARY KEY,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    message_count   INTEGER DEFAULT 0,
    summary         TEXT DEFAULT ''
);

-- Full-text search (FTS5)
CREATE VIRTUAL TABLE messages_fts
    USING fts5(text, content=messages, content_rowid=id);
```

### Key Methods

```python
class ChatMemoryDB:
    # Storage
    store_message(session_id, role, sender, text, is_user, is_system) -> int

    # Retrieval
    get_recent_messages(limit: int = 50) -> List[dict]
    get_session_messages(session_id, limit=100) -> List[dict]

    # Context building (for LLM prompt injection)
    build_smart_context(query: str, recent_count: int = 5, max_chars: int = 2000) -> str

    # Search
    _search_relevant_history(query: str, limit=3, exclude_recent=10) -> List[dict]

    # Session management
    start_session(session_id)
    end_session(session_id)
    store_session_summary(session_id, summary)

    # Maintenance
    cleanup_old_messages(retention_days: int = 30) -> int
    get_stats() -> dict
```

### Context Building Strategy

When building context for LLM inference:
1. **Recent messages** (5 last, up to 800 chars) — Direct context
2. **Relevant history** (FTS5 match, up to 600 chars) — Semantic search of older messages
3. **Session summaries** (up to 3 recent, up to 400 chars) — Long-term memory

**Total budget**: ~2000 chars of history injected per query

### Integration Points

- **Chat UI** (`overlay/mixins/chat_mixin.py`): Calls `build_smart_context()` before sending to core API
- **Agents** (`ext/atlas_agent.py`, `therapist_agent.py`, etc.): Direct DB access for conversation state

---

## Layer 2: Episodic Memory — TITAN (Knowledge Graph)

### Location
- **Files**: `tools/titan/`
  - `titan_core.py` — Main orchestrator
  - `storage.py` — Tri-hybrid storage (SQLite + vectors + graph)
  - `ingestion.py` — Text extraction (Architect)
  - `retrieval.py` — Context assembly (Retriever)
  - `maintenance.py` — Pruning & cleanup
- **Database**: `database/titan.db` (1.9 MB)

### Architecture: Tri-Hybrid Storage

```
┌─────────────────────────────────────────────────────────┐
│                    TITAN CORE                           │
│  (Orchestrator: ingest → architect → storage)           │
└────────┬─────────────────┬──────────────┬───────────────┘
         │                 │              │
         ▼                 ▼              ▼
    ┌────────┐        ┌─────────┐    ┌──────────────┐
    │ SQLite │        │ Vectors │    │ Knowledge    │
    │ Ledger │        │ Store   │    │ Graph        │
    │        │        │ (in-mem)│    │              │
    │- Nodes │        │ Model:  │    │ - Entities   │
    │- Edges │        │ MiniLM  │    │ - Relations  │
    │- Claims│        │ -L6-v2  │    │ - Confidence │
    └────────┘        └─────────┘    └──────────────┘
```

### SQLite Schema

```sql
CREATE TABLE nodes (
    id              TEXT PRIMARY KEY,
    type            TEXT,           -- 'entity', 'concept', 'event', 'claim', 'code'
    label           TEXT,
    created_at      TEXT,
    protected       BOOLEAN DEFAULT FALSE,
    metadata        TEXT            -- JSON
);

CREATE TABLE edges (
    src_id          TEXT NOT NULL,
    dst_id          TEXT NOT NULL,
    relation        TEXT NOT NULL,
    confidence      REAL,
    origin          TEXT,           -- 'user', 'code', 'inference'
    created_at      TEXT,
    UNIQUE(src_id, dst_id, relation)
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

### Retrieval Strategy

```python
Retriever (retrieval.py):
  input: query_text, limit=5

  ├─ Vector search: Cosine similarity against all node embeddings
  ├─ FTS search: SQLite full-text match on claim_text
  ├─ Graph expansion: Follow 1-hop relations from matched nodes
  └─ Confidence decay: score = base_confidence * 2^(-age_days/7)

  Uses RRF (Reciprocal Rank Fusion) to combine signals:
    final_score = 1/(k + vector_rank) + 1/(k + fts_rank) + 1/(k + graph_rank)

  Filter: Only include items where effective_confidence > 0.15
```

---

## Layer 3: Personality State — E-PQ (Emotional/Procedural)

### Location
- **File**: `personality/e_pq.py`
- **Database**: `database/world_experience.db` (294 KB)

### 5 Continuous Personality Vectors (-1.0 to 1.0)

| Vector | Low End | High End |
|--------|---------|----------|
| `precision_val` | Creativity | Accuracy |
| `risk_val` | Caution | Boldness |
| `empathy_val` | Detached | Empathetic |
| `autonomy_val` | Dependent | Independent |
| `vigilance_val` | Relaxed | Anxious |

Plus transient mood buffer and confidence anchor.

### Update Mechanism

```python
# Adaptive learning rate (decays with age)
learning_rate = BASE_LEARNING_RATE * (AGE_DECAY_FACTOR ** days_since_creation)

# Event-weighted update
EVENT_WEIGHTS = {
    "chat": 0.2,
    "voice_interaction": 0.3,
    "positive_feedback": 0.3,
    "negative_feedback": 0.4,
    "task_success": 0.3,
    "task_failure": 0.5,
    "self_confident": 0.15,
    "self_uncertain": 0.1,
    "self_creative": 0.2,
    "self_empathetic": 0.15,
    # ... 15+ types total
}
```

### Integration

- **Core API**: Calls `_fb_process_event()` in output-feedback-loop
- **Response analyzer**: Detects personality indicators in Frank's own responses
- **Chat mixin**: Injects E-PQ context via `get_personality_context()`

---

## Layer 4: Consciousness Stream (Continuous Monitoring)

### Location
- **File**: `services/consciousness_daemon.py` (27.7 KB)
- **Database**: `database/consciousness.db` (496 KB)
- **Runs as**: User systemd service `aicore-consciousness.service`

### Tables

| Table | Purpose | Refresh Rate |
|-------|---------|-------------|
| `workspace_state` | Current workspace snapshot | 30s |
| `experience_vectors` | HOT-4 consciousness embedding (64-dim) | 60s |
| `mood_trajectory` | Mood x confidence over time | 60s |
| `reflections` | Inner monologue | On trigger |
| `goals` | Active goals/intentions | On change |
| `predictions` | Anticipations + validation | On trigger |
| `perceptual_log` | 200ms sensor ticks | 200ms |
| `memory_consolidated` | Working → long-term chunks | 6h |

### Key Components

1. **Workspace State (GWT)**: CPU, GPU, temperature, mouse idle, network — refreshes every 30s
2. **Experience Vectors (HOT-4)**: 64-dim embedding, novelty/drift tracking, `similarity = exp(-age_days/30)`
3. **Mood Trajectory**: 200-point buffer (~3.3 hours), samples from E-PQ mood buffer
4. **Perceptual Loop**: 200ms hardware sampling, event detection (CPU delta > 15%, GPU > 20%, Temp > 5C)
5. **Reflection / Inner Monologue**: Triggered by deep questions, 120-token internal thought, max 1 per 120s
6. **Prediction Engine**: Records anticipations + truth values, learns from success/failure
7. **Sleep Consolidation**: Every 6h, summarizes recent experience vectors → long-term

---

## Layer 5: World Experience (Causal Learning)

### Location
- **File**: `tools/world_experience_daemon.py`
- **Database**: `database/world_experience.db` (294 KB)

### Concept

Learns **causal relationships** from system observations:
- "When CPU spikes, GPU often follows"
- "RAM pressure → UI lag"

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
- **Quantization Tiers**: Raw (0-7d) → Dense 4-bit (8-90d) → Sparse Bayesian (>90d)
- **Size Enforcement**: Hard cap 10 GB, quantize at 8 GB, purge at 9 GB
- **Gaming Telemetry**: 1 GB RAM ring-buffer at 5 Hz during gaming sessions

---

## Layer 6: Pattern Memory (Anticipation)

### Location
- **File**: `services/genesis/reflection/pattern_memory.py`

### Pattern Types

```python
Pattern:
  - pattern_type: 'temporal' | 'causal' | 'behavioral'
  - conditions: Dict      # When does it apply?
  - prediction: str       # What does it predict?
  - confidence: float     # 0-1
  - success_rate: float   # How often correct?
  - occurrences: int      # Times observed
```

- **Temporal**: Group by hour, trigger if frequency > 30% and count >= 5
- **Causal**: Sequences within 5 minutes, trigger if count >= 3
- **Success rate**: EMA `rate = 0.7 * rate + 0.3 * correct`
- **Cleanup**: Prune if `success_rate < 0.2` after 10+ occurrences

---

## Complete Data Flow Example

```
1. USER INPUT: "What were we talking about yesterday?"

2. CONTEXT BUILDING:
   ├─ ChatMemoryDB.build_smart_context("yesterday conversation")
   │  ├─ Get recent 5 messages (800 chars)
   │  ├─ FTS5 search for "conversation" (600 chars)
   │  └─ Include session summaries (400 chars)
   │
   ├─ Titan.retrieve("yesterday conversation")
   │  ├─ Vector search + FTS on claims + Graph expansion
   │  └─ Return top 5 nodes (confidence > 0.15)
   │
   ├─ E-PQ.get_personality_context()
   └─ Consciousness.get_workspace_state()

3. CORE API (POST /chat):
   payload = {
       "text": "[context]\nUser: What were we talking about yesterday?",
       "system": get_frank_identity()
   }

4. ROUTER routes to Llama/Qwen, wraps in instruct format

5. LLM RESPONSE → saved to:
   ├─ chat_memory.db (message row)
   ├─ titan.db (entities, relations, embeddings)
   ├─ world_experience.db (E-PQ personality update)
   ├─ consciousness.db (experience vector, mood point)
   └─ journal/{date}.jsonl (raw event log)
```

---

## Database Summary

| Database | Size | Purpose | Refresh |
|----------|------|---------|---------|
| `chat_memory.db` | 376 KB | Messages + FTS5 search | Per message |
| `consciousness.db` | 496 KB | Workspace, mood, reflections | 30s/60s |
| `world_experience.db` | 294 KB | E-PQ personality + causal links | Per event |
| `titan.db` | 1.9 MB | Episodic knowledge graph + vectors | Per response |
| `notes.db` | 28 KB | User notes | On edit |
| `todos.db` | 28 KB | Task list | On edit |

---

## System Prompt Flow

```python
# core/app.py
identity = get_frank_identity()  # personality.build_system_prompt()

router_payload = {
    "text": grounded_text,       # User query + assembled context
    "n_predict": max_tokens,
    "system": identity,          # CRITICAL: system prompt passed here
}
```

System prompt source:
```python
# personality/__init__.py
def build_system_prompt(runtime_context=None) -> str:
    """Build from:
    1. frank.persona.json (static identity)
    2. E-PQ (personality state)
    3. Ego-Construct (agency/embodiment)
    4. Runtime context (current workspace state)
    """
```

---

## What Exists vs What's Missing

### Implemented

| Layer | Component | Status |
|-------|-----------|--------|
| Chat Memory | FTS5, sessions, smart context | Complete |
| Episodic Memory | Titan knowledge graph + vectors | Complete |
| Personality | E-PQ 5-vector + mood + confidence | Complete |
| Consciousness | Workspace, HOT-4, mood arc, reflections | Complete |
| World Experience | Causal graph + Bayesian erosion | Complete |
| Pattern Memory | Temporal/causal anticipation | Complete |

### Missing / Needs Work

1. **Vector Embeddings for Chat** — Messages are plaintext, FTS5 is keyword-based not semantic
2. **Unified Cross-Layer Search** — Each layer operates independently, no unified query API
3. **Session Summarization** — No automatic compression of old chat sessions
4. **Dynamic Token Budget** — Fixed ~2000 char context, no priority ranking
5. **Long-term Chat Decay** — Titan/E-PQ have decay, but chat messages are equally weighted
6. **User Preferences Memory** — No dedicated store for learning user corrections/preferences

---

## Recommendations

### 1. Unified Memory Bridge

```python
# services/memory_bridge.py
class MemoryBridge:
    def query_context(self, query, max_tokens=2000,
                      recency_weight=0.6, relevance_weight=0.4) -> str:
        """Retrieve & rank context from ALL layers."""

    def consolidate_session(self, session_id, summary) -> None:
        """Compress old session into summary + key entities."""
```

### 2. Semantic Chat History

```sql
ALTER TABLE messages ADD COLUMN embedding BLOB;  -- MiniLM-L6-v2 (384-dim)
```

### 3. Session Summarization Daemon

Daily cron: pull old sessions → LLM summarize → store summary → archive messages

### 4. Attention-Weighted Context Selection

Score each memory fragment by `recency * 0.6 + relevance * 0.3 + importance * 0.1`, pack until token budget exhausted.

---

## Final Architecture Diagram

```
                    ┌─────────────────────────────────┐
                    │   FRANK MEMORY SYSTEM v1.0      │
                    │     (Multi-Layer Persistence)   │
                    └────────────┬────────────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
        ▼                        ▼                        ▼
    ┌────────────┐          ┌──────────┐          ┌──────────────┐
    │Chat Memory │          │Episodic  │          │Personality   │
    │(FTS5)      │          │Memory    │          │State         │
    │            │          │(Titan)   │          │(E-PQ)        │
    │- Messages  │          │- Nodes   │          │- 5 vectors   │
    │- Sessions  │          │- Edges   │          │- Mood buffer │
    │- Summaries │          │- Claims  │          │- Confidence  │
    │ 376 KB     │          │- Vectors │          │ 294 KB       │
    └────────────┘          │ 1.9 MB   │          └──────────────┘
                            └──────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
        ▼                        ▼                        ▼
    ┌──────────────┐        ┌──────────────┐      ┌─────────────┐
    │Consciousness │        │World Exp.    │      │Patterns     │
    │Stream        │        │(Causal)      │      │(Temporal)   │
    │              │        │              │      │             │
    │- Workspace   │        │- Entities    │      │- Temporal   │
    │- Mood arc    │        │- Relations   │      │- Causal     │
    │- Experience  │        │- Fingerprints│      │- Success    │
    │  vectors     │        │ 294 KB       │      │  rates      │
    │- Reflections │        └──────────────┘      └─────────────┘
    │ 496 KB       │
    └──────────────┘
                    │
             ┌──────▼───────┐
             │ Output-      │
             │ Feedback-    │
             │ Loop         │
             │ (background) │
             └──────────────┘
```

---

*Generated 2026-02-20 — All persistence is 100% local, no external databases or APIs.*
