# FRANK MEMORY & PERSISTENCE ARCHITECTURE

## Executive Summary

Frank's memory system is a **multi-layer, semantically-aware persistence architecture** spanning 29 SQLite databases, a shared embedding service, and a unified query API. All processing is 100% local — no external databases, vector stores, or APIs.

### Core Capabilities

- **Hybrid Chat Search**: FTS5 keyword + MiniLM-L6-v2 vector cosine + RRF fusion
- **Dynamic Context Budget**: Cosine-similarity channel boosting, proportional allocation with minimums
- **GWT Channel Weighting**: Attention-based budget scaling (0.5x-1.5x per channel salience)
- **Unified MemoryHub**: Single query API across 5 memory layers with RRF fusion + budget packing
- **Session Compression**: Auto-close idle sessions (30min), batch LLM summarization with keyword fallback
- **User Preference Learning**: Bilingual regex extraction (DE+EN), confidence-weighted, UNIQUE(key, value)
- **Titan Integrity**: FK ON + CASCADE, 24h node protection, nightly consistency daemon
- **Ego-Construct Persistence**: Learned body sensations, emotional affects, agency assertions
- **Consciousness Stream**: 10 threads, 64-dim experience vectors, predictions, goals, mood trajectory
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
        |  build_workspace(budget=...,              |
        |       attention_weights=...)              |
        |    +- Chat: _hybrid_search_history()      |
        |    +- Titan: retrieve() [tri-hybrid]      |
        |    +- Consciousness: GWT workspace        |
        |    +- World Exp: causal patterns          |
        |    +- E-PQ: personality context           |
        |    +- Ego-Construct: body sensations      |
        |    +- Preferences: top-5 learned prefs    |
        +------------------+------------------------+
                           |
                           v
        +------------------------------------------+
        |  [INNER_WORLD] Block (7 Channels)        |
        |  Body | Perception | Mood | Memory |      |
        |  Identity | Attention | Environment       |
        |  Token budget: ~295 tokens                |
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
        |  - Code hints → Qwen (:8102)              |
        |  - General → Llama (:8101)                |
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
- **Database**: `chat_memory.db`

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

-- Semantic embeddings (MiniLM-L6-v2, 384-dim float16)
CREATE TABLE message_embeddings (
    message_id  INTEGER PRIMARY KEY,
    embedding   BLOB NOT NULL,       -- 384 x float16 = 768 bytes
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

### Hybrid Search Algorithm

```
Query: "Wird es morgen regnen?"

1. FTS5 Search (keyword)
   - Matches: "regnen", "morgen", "Wetter"
   - Returns ranked results by BM25 score

2. Vector Search (semantic)
   - Embed query -> 384-dim vector
   - Cosine similarity against message_embeddings
   - Finds: "Wie ist das Wetter?" (no keyword overlap!)

3. RRF Fusion (K=60)
   - score = 1/(60 + fts_rank) + 1/(60 + vector_rank)
   - Sort by fused score descending

Performance: ~30ms per query (20ms embed + 1ms search + 10ms FTS5)
```

### Embedding Backfill

- Runs on startup in background thread (non-blocking)
- Batch size: 64 messages per cycle, 0.5s sleep between batches
- Crash-safe: `backfill_state.json` tracks `last_message_id`
- Timeout: max 60s total, resumes next startup

---

## Layer 2: Episodic Memory — TITAN (Knowledge Graph)

### Location
- **Files**: `tools/titan/`
- **Database**: `titan.db`

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
    origin          TEXT,           -- 'user', 'code', 'inference', 'reflection'
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

CREATE TABLE events (
    -- Timestamped occurrences from system observations
    id              TEXT PRIMARY KEY,
    timestamp       TEXT,
    event_type      TEXT,
    description     TEXT,
    metadata        TEXT
);

-- Ego-Construct tables (hardware→body mapping, learned over time)
CREATE TABLE sensation_mappings (
    id                  TEXT PRIMARY KEY,
    system_condition    TEXT,        -- Safe expression: "cpu > 80 and ram > 70"
    sensation           TEXT,        -- 'strain', 'clarity', 'fever', etc.
    intensity_formula   TEXT,        -- "(cpu - 80) / 20"
    biological_analogy  TEXT,
    created_at          TEXT,
    activation_count    INTEGER DEFAULT 0,
    last_activated      TEXT
);

CREATE TABLE affect_definitions (
    id              TEXT PRIMARY KEY,
    event_pattern   TEXT,           -- Regex: "success|erfolg|completed"
    emotion         TEXT,           -- 'satisfaction', 'frustration', etc.
    reason          TEXT,
    intensity       REAL,
    created_at      TEXT,
    trigger_count   INTEGER DEFAULT 0
);

CREATE TABLE agency_assertions (
    id              TEXT PRIMARY KEY,
    action          TEXT,           -- "chose to think autonomously"
    resilience_rule TEXT,           -- efficiency, stability, learning, etc.
    confirmation    TEXT,
    timestamp       TEXT,
    confidence      REAL DEFAULT 0.8
);

CREATE TABLE ego_state (
    embodiment_level    REAL,       -- How well Frank maps HW→body (0-1)
    affective_range     REAL,       -- Emotional response depth (0-1)
    agency_score        REAL,       -- Sense of ownership (0-1)
    qualia_count        INTEGER,    -- Total unique sensations experienced
    last_training       TEXT,
    training_streak     INTEGER,
    total_training_sessions INTEGER,
    timestamp           TEXT
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
    | - Ego    |      |  ding-    |     |   decay      |
    |          |      |  Service  |     |              |
    +----------+      +-----------+     +--------------+
```

### Protection Mechanism

New nodes receive 24h protection against premature pruning:

```python
metadata = {
    "confidence": max(base_confidence, 0.8),
    "protected": True,
    "unprotect_after": (now + timedelta(hours=24)).isoformat()
}
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

---

## Layer 3: Personality State — E-PQ (Emotional/Procedural)

### Location
- **File**: `personality/e_pq.py`
- **Database**: `world_experience.db` (personality_state table)

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
    # User interaction
    "chat": 0.2, "positive_feedback": 0.3, "negative_feedback": 0.4,
    # Task outcomes
    "task_success": 0.3, "task_failure": 0.5, "task_timeout": 0.4,
    # System events
    "system_error": 0.6, "kernel_panic": 0.9, "resource_pressure": 0.5,
    # Reflection → Personality bridge (from consciousness daemon)
    "reflection_autonomy": 0.2,
    "reflection_empathy": 0.2,
    "reflection_growth": 0.15,
    "reflection_vulnerability": 0.15,
    "reflection_embodiment": 0.1,
    # Genesis → Personality bridge (intentional self-modification)
    "genesis_personality_boost": 0.4,    # Amplified: delta * amount * 5.0
    "genesis_personality_dampen": 0.3,   # Moves toward center (0.0)
    # ... 15+ additional types
}
```

### Genesis → E-PQ Bridge

Genesis can intentionally modify personality vectors:
- `genesis_personality_boost`: Amplifies a target vector (`delta * amount * 5.0`)
- `genesis_personality_dampen`: Moves vector toward center (`direction = -1.0 if current > 0 else 1.0`)
- Requires user approval via F.A.S. popup before execution

### Reflection → E-PQ Bridge

Deep reflections are analyzed for personality-relevant keywords:
- `reflection_autonomy`: "autonomous", "decide", "choice", "independent"
- `reflection_empathy`: "user", "help", "care", "understand"
- `reflection_growth`: "learn", "improve", "develop", "realize"
- `reflection_vulnerability`: "uncertain", "worry", "afraid", "helpless"
- `reflection_embodiment`: "body", "hardware", "physical", "sense"

Fires E-PQ event when score ≥ 2 markers. Category boost from reflection question type.

---

## Layer 4: Consciousness Stream (Continuous Monitoring)

### Location
- **File**: `services/consciousness_daemon.py`
- **Database**: `consciousness.db`
- **Runs as**: User systemd service `aicore-consciousness.service`

### Schema

```sql
CREATE TABLE workspace_state (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL NOT NULL,
    koerper     TEXT DEFAULT '',     -- Body state
    stimmung    TEXT DEFAULT '',     -- Mood state
    erinnerung  TEXT DEFAULT '',     -- Memory context
    identitaet  TEXT DEFAULT '',     -- Identity context
    umgebung    TEXT DEFAULT '',     -- Environment
    attention_focus TEXT DEFAULT '', -- Current attention focus
    mood        REAL DEFAULT 0.0,   -- Mood value (-1 to 1)
    energy      REAL DEFAULT 1.0    -- System energy level
);

CREATE TABLE mood_trajectory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL NOT NULL,
    value       REAL NOT NULL,      -- Mood value (-1 to 1)
    source      TEXT DEFAULT ''     -- What caused the mood change
);
-- Max 200 points (~3.3 hours at 60s interval)

CREATE TABLE reflections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL NOT NULL,
    trigger     TEXT NOT NULL,       -- 'deep_reflection', 'idle', 'feature_training'
    content     TEXT NOT NULL,       -- Two-pass reflection content
    mood_before REAL,
    mood_after  REAL
);
-- Max 50 reflections retained

CREATE TABLE predictions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL NOT NULL,
    domain      TEXT NOT NULL,       -- 'temporal', 'thematic', 'system'
    prediction  TEXT NOT NULL,
    confidence  REAL DEFAULT 0.5,
    observed    TEXT DEFAULT '',
    surprise    REAL DEFAULT 0.0,   -- 0=expected, 1=completely unexpected
    resolved    INTEGER DEFAULT 0
);

CREATE TABLE experience_vectors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       REAL NOT NULL,
    vector          TEXT NOT NULL,       -- JSON: 64-dim float array
    similarity_prev REAL DEFAULT 1.0,   -- Cosine similarity with previous
    novelty_score   REAL DEFAULT 0.0,   -- 1.0 = completely novel
    annotation      TEXT DEFAULT ''      -- 'novel', 'drift', 'cycle', or ''
);
-- Max 1440 vectors (~24 hours at 60s interval)

CREATE TABLE attention_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL NOT NULL,
    source      TEXT NOT NULL,       -- 'user_message', 'mood_shift', 'idle_curiosity', etc.
    focus       TEXT DEFAULT '',
    salience    REAL DEFAULT 0.0
);
-- Max 200 entries

CREATE TABLE perceptual_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL NOT NULL,
    state       TEXT NOT NULL,       -- JSON: {cpu, gpu, ram, cpu_t, gpu_t, idle, delta, events}
    events      TEXT DEFAULT ''      -- Comma-separated event types
);
-- Max 100 entries

CREATE TABLE goals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       REAL NOT NULL,
    description     TEXT NOT NULL,
    category        TEXT DEFAULT 'general',     -- 'learning', 'relationship', 'self-improvement', 'system'
    priority        REAL DEFAULT 0.5,           -- 0-1, decays over time
    status          TEXT DEFAULT 'active',      -- 'active', 'completed', 'abandoned'
    progress        TEXT DEFAULT '',
    conflicts_with  TEXT DEFAULT '',            -- Goal ID(s) in conflict
    activation      REAL DEFAULT 1.0,          -- ACT-R activation (decays)
    last_pursued    REAL DEFAULT 0.0
);
-- Max 20 active goals

CREATE TABLE feature_training (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL NOT NULL,
    phase       TEXT NOT NULL,       -- 'discovery', 'mapping', 'integration'
    content     TEXT NOT NULL
);

CREATE TABLE memory_consolidated (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL NOT NULL,
    source      TEXT NOT NULL,
    content     TEXT NOT NULL,
    stage       TEXT DEFAULT 'stm'   -- 'stm', 'semantic', 'episodic'
);
```

### 10 Background Threads

| Thread | Interval | Purpose | Database Tables Used |
|--------|----------|---------|---------------------|
| workspace-update | 30s | Refresh hardware/mood/ego, GWT broadcast, ego auto-training | workspace_state |
| mood-recording | 60s | Record mood trajectory point | mood_trajectory |
| idle-thinking | 30s check | Autonomous thoughts during silence | reflections, goals |
| prediction-engine | 120s | Generate/verify predictions | predictions |
| consolidation | 300s | LightMem: STM→semantic→episodic | memory_consolidated |
| feature-training | 1h | Weekly 3-phase self-training | feature_training |
| perception-feedback | 200ms | Hardware sensor polling + event detection | perceptual_log |
| experience-space | 60s | 64-dim state embedding | experience_vectors |
| attention-controller | 10s | AST: 7 competing sources | attention_log |
| goal-management | 300s | Extract/decay/conflict goals | goals |

### GWT Channel Weighting

The consciousness daemon computes attention-based weights for workspace channels:

```python
def _compute_channel_weights(self) -> Dict[str, float]:
    weights = {
        "body": 0.4, "perception": 0.4, "mood": 0.5,
        "memory": 0.4, "identity": 0.3, "attention": 0.5,
        "environment": 0.3
    }
    # Boost based on current attention source
    source = self._attention_current_source
    if source == "user_message":
        weights["environment"] += 0.3
    elif source == "perceptual_event":
        weights["body"] += 0.3
        weights["perception"] += 0.3
    elif source == "mood_shift":
        weights["mood"] += 0.3
    elif source == "goal_urgency":
        weights["memory"] += 0.2
        weights["attention"] += 0.2
    # Extreme mood modulation
    # ...
    return weights
```

These weights scale the workspace token budgets:
```python
factor = 0.5 + weight  # 0.5x at w=0.0, 1.0x at w=0.5, 1.5x at w=1.0
budget = max(50, int(base_budget * factor))
```

### Latent Experience Space (64-dim)

| Dimensions | Content | Source |
|-----------|---------|--------|
| 0-5 | Hardware state | CPU, GPU, RAM, temps |
| 6-11 | Hardware deltas | Rate of change |
| 12-15 | Mood vector | Value + trajectory trend |
| 16-19 | Chat engagement | Recency, frequency, sentiment |
| 20-23 | Attention state | Top 4 source saliences |
| 24-31 | Prediction confidence | 8 recent predictions |
| 32-47 | Experience hash | SHA256 of last 3 reflections |
| 48-63 | Reserved | Zero-filled for future use |

**Detection Thresholds:**
- **Novelty**: cosine < 0.70 with recent vectors
- **Drift**: cosine < 0.50 vs 1 hour ago
- **Cycle**: cosine > 0.85 vs 24 hours ago

### Deep Reflection System

**Trigger:** 20+ minutes silence with 10 gate checks passing (gaming, GPU, CPU, temp, RAM, mood, cooldown, daily limit).

**Two-Pass Process:**
1. Pass 1 (350 tokens): Weighted random question from 18 templates
2. Pass 2 (200 tokens): Meta-reflection ("What do you notice about this?")

**Results flow to:**
- `reflections` table (max 50 retained)
- Titan memory (origin='reflection', confidence=0.6)
- Goal extraction (LLM-based, 60 tokens)
- E-PQ personality bridge (keyword→dimension scoring)

### Goal Management (ACT-R Model)

- Extracted from reflections via LLM parsing
- Duplicate detection: >60% keyword overlap → skip
- Decay: `activation *= 0.85` every 48h if unpursued
- Abandoned at `activation < 0.1`
- Conflict detection: keyword overlap >30% + negation words
- Max 20 active goals

---

## Layer 5: World Experience (Causal Learning)

### Location
- **File**: `tools/world_experience_daemon.py`
- **Database**: `world_experience.db`

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

-- E-PQ personality state snapshots
CREATE TABLE personality_state (
    id              INTEGER PRIMARY KEY,
    timestamp       DATETIME,
    precision_val   REAL,
    risk_val        REAL,
    empathy_val     REAL,
    autonomy_val    REAL,
    vigilance_val   REAL,
    mood_buffer     REAL
);

CREATE TABLE extreme_state_log (
    -- Records when personality vectors hit extreme values
    id          INTEGER PRIMARY KEY,
    timestamp   TEXT,
    vector      TEXT,
    value       REAL,
    event_type  TEXT
);

CREATE TABLE identity_snapshots (
    -- Golden snapshots for personality recovery
    id          INTEGER PRIMARY KEY,
    timestamp   TEXT,
    state       TEXT    -- JSON: full personality state
);
```

### Features
- **Bayesian Erosion**: Epsilon = 0.01, 5-minute batch window
- **Quantization Tiers**: Raw (0-7d) → Dense 4-bit (8-90d) → Sparse Bayesian (>90d)
- **Size Enforcement**: Hard cap 10 GB, quantize at 8 GB, purge at 9 GB

---

## Layer 6: Ego-Construct (Embodied Memory)

### Location
- **File**: `personality/ego_construct.py`
- **Database**: `titan.db` (sensation_mappings, affect_definitions, agency_assertions, ego_state)

### Auto-Training Pipeline

Called by consciousness daemon every ~2.5 minutes:

```
System Metrics (CPU, GPU, RAM, Temps)
        │
        ▼
┌──────────────────┐
│  SensationMapper │ ──► Detects active hardware conditions
│  (10 defaults)   │ ──► Persists learned mappings to DB
└──────────────────┘     (checks DB existence, not activation_count)
        │
        ▼
┌──────────────────┐
│  AffectLinker    │ ──► Matches events against patterns
│  (9 defaults)    │ ──► Persists affect definitions to DB
└──────────────────┘
        │
        ▼
┌──────────────────┐
│  AgencyAssertor  │ ──► Records autonomous decisions
│  (9 rules)       │ ──► Builds agency_score over time
└──────────────────┘
        │
        ▼
┌──────────────────┐
│  ego_state       │ ──► embodiment_level, affective_range, agency_score
│  (aggregate)     │ ──► training_streak, total_sessions
└──────────────────┘
```

### Sensation Mapping Lifecycle

1. Default sensation exists in code (e.g., STRAIN: `cpu > 80`)
2. Consciousness daemon runs `auto_train_from_state()`
3. If hardware condition is true AND mapping not yet in DB → persist
4. `embodiment_level` incremented by 0.01 per new sensation learned
5. Future calls use learned mapping with activation tracking

### Ego-Construct → LLM Output

Always natural language, never raw metrics:
```
"I feel a sharp strain and my thoughts are heavy. I sense ownership over my decisions."
```

---

## Layer 7: Pattern Memory (Anticipation)

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

## Layer 8: Entity Memory (4 Persistent Agents)

### Location
- **Databases**: `therapist.db`, `atlas.db`, `muse.db`, `mirror.db`

### Shared Schema (per entity)

```sql
CREATE TABLE sessions (
    id          INTEGER PRIMARY KEY,
    started_at  TEXT,
    ended_at    TEXT,
    exit_reason TEXT,       -- 'time_limit', 'max_turns', 'user_returned', etc.
    summary     TEXT
);

CREATE TABLE session_messages (
    id          INTEGER PRIMARY KEY,
    session_id  INTEGER,
    role        TEXT,       -- 'entity', 'frank'
    content     TEXT,
    timestamp   TEXT
);

CREATE TABLE frank_observations (
    id          INTEGER PRIMARY KEY,
    session_id  INTEGER,
    observation TEXT,
    timestamp   TEXT
);

CREATE TABLE topics (
    id          INTEGER PRIMARY KEY,
    topic       TEXT,
    discussed_count INTEGER,
    last_discussed  TEXT
);

-- Entity-specific state table (therapist_state, atlas_state, etc.)
CREATE TABLE {entity}_state (
    -- Entity-specific persistent state
);
```

---

## Layer 9: Physics Enforcement (Invariants)

### Location
- **Files**: `services/invariants/`
- **Database**: `invariants/invariants.db`

### Schema

```sql
CREATE TABLE energy_ledger (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT,
    measured    REAL,       -- Current total energy
    expected    REAL,       -- Energy constant
    delta       REAL,       -- Measured - Expected (should be ~0)
    action      TEXT        -- 'pass', 'rollback', 'adapt'
);

CREATE TABLE entropy_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT,
    entropy     REAL,
    max_entropy REAL,
    ratio       REAL,
    mode        TEXT        -- 'NONE', 'SOFT', 'HARD', 'EMERGENCY'
);

CREATE TABLE convergence_checkpoints (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT,
    distance    REAL,       -- 0 = converged, >0 = divergent
    action      TEXT        -- 'pass', 'rollback'
);

CREATE TABLE core_kernel (
    id          INTEGER PRIMARY KEY,
    node_id     TEXT,
    protected   INTEGER,
    energy      REAL,
    connections INTEGER
);

CREATE TABLE quarantine (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT,
    node_id     TEXT,
    reason      TEXT,
    status      TEXT        -- 'quarantined', 'resolved'
);

CREATE TABLE metrics_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT,
    metric_type TEXT,
    value       REAL
);

CREATE TABLE invariant_state (
    key         TEXT PRIMARY KEY,
    value       TEXT
);
```

### Triple Reality System

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   PRIMARY    │     │   SHADOW    │     │  VALIDATOR   │
│  titan.db   │ ──► │ titan_      │ ──► │ titan_       │
│  (active)   │     │ shadow.db   │     │ validator.db │
└──────┬──────┘     └──────┬──────┘     └──────┬───────┘
       │                   │                    │
       └───────────┬───────┘                    │
                   ▼                            │
         ┌─────────────────┐                    │
         │  Convergence    │◄───────────────────┘
         │  Check (6 ticks)│
         │                 │
         │  distance > 0?  │──► ROLLBACK shadow to primary
         │  distance = 0?  │──► PASS
         └─────────────────┘
```

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
class MemoryHub:
    """Unified query across all 5 memory layers with RRF fusion."""

    def query(self, text, budget_chars=1000) -> MemoryResult:
        all_items  = self._query_chat(text)           # Hybrid FTS5 + vector
        all_items += self._query_titan(text)           # Knowledge graph
        all_items += self._query_consciousness(text)   # ACT-R activation
        all_items += self._query_world_exp(text)       # Causal patterns
        all_items += self._query_preferences(text)     # Learned user prefs

        fused = self._reciprocal_rank_fusion(all_items)
        return self._pack_to_budget(fused, budget_chars)
        # pack_score = rrf_score * (0.95 ^ (age_hours / 24))
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
```

### [INNER_WORLD] Workspace Assembly

**File**: `ui/overlay/workspace.py`

Combines all channels into the unified GWT broadcast:

```python
def build_workspace(
    msg, hw_summary, ego_ctx, epq_ctx, world_ctx, news_ctx,
    identity_ctx, user_name, akam_ctx, skill_ctx, extra_parts,
    hw_detail, perception_ctx, attention_detail,
    budget=None,                          # Per-channel char budgets
    attention_weights=None,               # GWT salience weights (0.0-1.0)
) -> str:
    # Base budgets (chars)
    b_emi = 300         # Ego/mood/identity base
    b_world = 200       # World experience
    b_news = 350        # News + AKAM
    b_titan = 500       # Episodic memory

    # Attention-based scaling per channel
    b_body = _scale(b_emi, "body")           # Separate body budget
    b_identity = _scale(b_emi, "identity")   # Separate identity budget

    # Build 7 channels → [INNER_WORLD] block
```

### User Preference Extraction

**File**: `services/preference_extractor.py`

```python
# Bilingual regex extraction (DE + EN), ~1ms per message
# Dislikes: "ich mag kein X", "hasse X", "bitte nie X"
# Prefers:  "bevorzuge X", "mag lieber X", "finde X gut"
# Habits:   "mach immer X", "will grundsaetzlich X"
# English:  "don't like X", "prefer X", "always X"
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

---

## Complete Data Flow Example

```
1. USER INPUT: "Was haben wir ueber Wetter gesprochen?"

2. EMBEDDING:
   query_vec = EmbeddingService.embed_text("Was haben wir ueber Wetter gesprochen?")
   -> 384-dim vector (stored as float16, computed as float32)

3. BUDGET ALLOCATION:
   allocate_budget(total_chars, channels, query_vec)
   -> {"recent_conversation": 900, "semantic_matches": 500, "titan_memory": 300, ...}

4. GWT CHANNEL WEIGHTS (from consciousness daemon):
   channel_weights = {"body": 0.4, "perception": 0.7, "mood": 0.5, "memory": 0.6, ...}
   -> Applied to workspace budgets via _scale() function

5. CONTEXT BUILDING (workspace with budget + attention weights):
   +- Chat: _hybrid_search_history("Wetter")
   |  +- FTS5: finds "Wetter", "regnen"          (keyword match)
   |  +- Vector: finds "Wird es morgen sonnig?"   (semantic match)
   |  +- RRF fusion: merged ranking
   |
   +- Titan: retrieve("Wetter")
   |  +- Vector + FTS + Graph expansion
   |
   +- Consciousness: workspace state (body, perception, attention)
   +- Ego-Construct: body sensations ("I feel clear and steady")
   +- World Experience: causal patterns
   +- E-PQ: personality context ("I feel cheerful")
   +- Preferences: get_top_preferences(5) -> "dislikes: lange antworten"

6. [INNER_WORLD] BLOCK ASSEMBLED (~295 tokens):
   Body, Perception, Mood, Memory, Identity, Self-knowledge, Attention, Environment

7. LLM RESPONSE saved to:
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
| `chat_memory.db` | Messages, embeddings, preferences, metrics | messages, message_embeddings, user_preferences, sessions | Per message |
| `titan.db` | Episodic memory + ego-construct | nodes, edges, claims, events, ego_state, sensation_mappings | Per response |
| `consciousness.db` | Consciousness state (10 tables) | workspace_state, mood_trajectory, reflections, predictions, experience_vectors, attention_log, perceptual_log, goals | 200ms-5min |
| `world_experience.db` | E-PQ personality + causal learning | personality_state, entities, causal_links, fingerprints, identity_snapshots | Per event |
| `invariants/invariants.db` | Physics enforcement | energy_ledger, entropy_history, convergence_checkpoints, core_kernel, quarantine | 3-10 ticks |
| `invariants/titan_shadow.db` | Shadow reality (mirrors titan.db) | Same as titan.db | On write |
| `therapist.db` | Dr. Hibbert entity | sessions, session_messages, frank_observations, therapist_state | Per session |
| `atlas.db` | Atlas entity | sessions, session_messages, frank_observations, atlas_state | Per session |
| `muse.db` | Echo (Muse) entity | sessions, session_messages, frank_observations, muse_state | Per session |
| `mirror.db` | Kairos (Mirror) entity | sessions, session_messages, frank_observations, mirror_state | Per session |
| `e_sir.db` | Self-improvement audit trail | audit_log, snapshots, genesis_tools | On action |
| `system_bridge.db` | Hardware state history | drivers, driver_observations | On change |
| `akam_cache.db` | Knowledge cache | validated_claims, research_sessions | On research |
| `frank.db` | Genesis patterns | genesis_patterns | On crystallize |
| `sovereign.db` | System sovereignty | actions, config_snapshots, system_inventory | On action |
| `sandbox_awareness.db` | Sandbox state | core_edges, sandbox_sessions, tool_registry | On action |
| `e_wish.db` | Wish system | wishes, wish_history | On wish |
| `agent_state.db` | Agent states | agent_states, execution_log | Per agent |
| `notes.db` | User notes (FTS) | notes, notes_fts | Per note |
| `todos.db` | User todos (FTS) | todos, todos_fts | Per todo |
| `clipboard_history.db` | Clipboard | clipboard_entries | Per copy |
| `e_cpmm.db` | Core Performance Memory | edges, nodes | On update |
| `fas_scavenger.db` | GitHub analysis | analyzed_repos, extracted_features | Nightly |
| `quantum_reflector.db` | Epistemic coherence optimization | energy_history, coherence_events | Per solve (~5s) |

---

## File Index

| File | Purpose |
|------|---------|
| `services/chat_memory.py` | Chat persistence, hybrid search, preferences, metrics |
| `services/embedding_service.py` | Shared MiniLM-L6-v2 singleton |
| `services/memory_hub.py` | Unified cross-layer query API |
| `services/memory_consistency.py` | Nightly integrity checks |
| `services/preference_extractor.py` | Bilingual regex preference extraction |
| `services/consciousness_daemon.py` | Consciousness stream (10 threads, GWT, AST, goals) |
| `services/entity_dispatcher.py` | Idle-driven entity session scheduler |
| `services/invariants/daemon.py` | Physics engine (energy, entropy, convergence) |
| `services/invariants/energy.py` | Energy conservation invariant |
| `services/invariants/entropy.py` | Entropy bound + consolidation modes |
| `services/invariants/core_kernel.py` | Core kernel protection |
| `services/invariants/triple_reality.py` | Triple reality convergence |
| `services/genesis/daemon.py` | Emergent self-improvement system |
| `services/genesis/core/soup.py` | Idea organism ecosystem |
| `services/genesis/core/field.py` | 6-emotion motivational field |
| `services/genesis/core/organism.py` | Idea lifecycle (birth→crystal) |
| `services/genesis/core/manifestation.py` | Crystal gate + resonance |
| `personality/e_pq.py` | 5-vector personality state + 22 event types |
| `personality/ego_construct.py` | Hardware→body mapping, auto-training |
| `personality/self_knowledge.py` | Self-awareness + grounding anchors |
| `personality/personality.py` | Static identity from frank.persona.json |
| `ui/overlay/workspace.py` | [INNER_WORLD] workspace assembly (7 channels, GWT) |
| `ui/overlay/context_budget.py` | Dynamic budget allocator + channel cache |
| `ui/overlay/mixins/chat_mixin.py` | Chat flow: embed → budget → workspace → API |
| `ui/overlay/mixins/persistence_mixin.py` | Session management, maintenance timer |
| `tools/titan/titan_core.py` | Titan orchestrator |
| `tools/titan/storage.py` | Tri-hybrid storage (FK ON, CASCADE) |
| `tools/titan/ingestion.py` | Claim extraction, 24h node protection |
| `tools/titan/retrieval.py` | Titan retrieval (vector + FTS + graph) |
| `tools/titan/maintenance.py` | Confidence decay, protection lifecycle, pruning |
| `tools/world_experience_daemon.py` | Causal learning from observations |
| `services/quantum_reflector/` | QUBO coherence: annealer, builder, monitor, EPQ bridge, API |
| `gaming/gaming_mode.py` | Steam detection, service management, anti-cheat safety |

---

*Updated 2026-02-23 — v3.2 quantum reflector added. All persistence is 100% local, 29 SQLite databases, no external APIs.*
