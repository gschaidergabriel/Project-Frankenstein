# Frank AI System Architecture

> **Frank** is an embodied AI system running locally on Linux, featuring voice interaction, dynamic personality, recursive self-improvement, and multi-modal memory systems.

## Table of Contents

- [System Overview](#system-overview)
- [Core Architecture](#core-architecture)
- [Modules](#modules)
  - [Core Services](#core-services)
  - [Personality System](#personality-system)
  - [Memory Systems](#memory-systems)
  - [Self-Improvement Engine](#self-improvement-engine)
  - [Voice Interaction](#voice-interaction)
  - [Gaming Mode](#gaming-mode)
  - [Visual Feedback](#visual-feedback)
  - [System Tools](#system-tools)
  - [Security & Monitoring](#security--monitoring)
- [Databases](#databases)
- [Emergent Behavior](#emergent-behavior)
- [API Reference](#api-reference)

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER INTERFACES                                 │
│    Voice ("Hey Frank")  │  Chat Overlay  │  Desktop  │  Live Wallpaper      │
└───────────────┬─────────────────┬──────────────┬────────────────────────────┘
                │                 │              │
                ▼                 ▼              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            CORE SERVICES                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │   Core   │  │  Router  │  │ Toolbox  │  │  Voice   │  │Wallpaper │      │
│  │  :8088   │  │  :8091   │  │  :8096   │  │  :8197   │  │  :8199   │      │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘      │
└───────┼─────────────┼─────────────┼─────────────┼─────────────┼─────────────┘
        │             │             │             │             │
        ▼             ▼             ▼             ▼             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           INTELLIGENCE LAYER                                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │   Llama 3.1     │  │   Qwen 2.5      │  │    Ollama       │             │
│  │   (General)     │  │   (Code)        │  │   (Lightweight) │             │
│  │    :8101        │  │    :8102        │  │    :11434       │             │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘             │
└─────────────────────────────────────────────────────────────────────────────┘
        │                                                       │
        ▼                                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PERSONALITY & MEMORY                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │    E-PQ     │  │    Titan    │  │ World-Exp   │  │   E-SIR     │        │
│  │ Personality │  │   Memory    │  │   Causal    │  │ Self-Improve│        │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘        │
└─────────────────────────────────────────────────────────────────────────────┘
        │                                                       │
        ▼                                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              DATABASES                                       │
│   titan.db │ world_experience.db │ e_sir.db │ system_bridge.db │ fas.db    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Characteristics

| Property | Value |
|----------|-------|
| Architecture | Microservice + Event-Driven |
| Primary Language | Python 3.11+ |
| LLM Backend | llama.cpp (Llama 3.1, Qwen 2.5) |
| Voice | Whisper STT + Piper TTS |
| OS | Ubuntu Linux |
| GPU | Auto-detected (CUDA / Vulkan / CPU) |

---

## Core Architecture

### Microservice Communication

All services communicate via HTTP REST APIs on localhost:

| Service | Port | Protocol | Purpose |
|---------|------|----------|---------|
| Core | 8088 | HTTP/JSON | Main chat orchestrator |
| Router | 8091 | HTTP/JSON | Intelligent model routing |
| Toolbox | 8096 | HTTP/JSON | System introspection & tools |
| Voice | 8197 | HTTP/JSON | STT/TTS daemon |
| Wallpaper | 8199 | HTTP/JSON | Live visualization events |
| Llama | 8101 | HTTP/JSON | General reasoning (llama.cpp) |
| Qwen | 8102 | HTTP/JSON | Code generation (llama.cpp) |
| Ollama | 11434 | HTTP/JSON | Lightweight fallback |

### Request Flow

```
User Input (Voice/Text)
        │
        ▼
┌───────────────────┐
│   Core (:8088)    │◄──── Toolbox context (system state)
│   Context Builder │◄──── E-PQ personality context
│   Event Journaler │◄──── World-Experience memory
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  Router (:8091)   │
│  Model Selection  │
│  - Code hints?    │──► Qwen (:8102)
│  - General?       │──► Llama (:8101)
│  - Gaming mode?   │──► Ollama (lightweight)
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│    LLM Inference  │
│    (streaming)    │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  Response + Events│──► Wallpaper (visual feedback)
│                   │──► Voice TTS (spoken response)
│                   │──► Memory storage
└───────────────────┘
```

---

## Modules

### Core Services

#### `/core/app.py` - Chat Orchestrator

The central hub that processes all chat requests.

**Features:**
- Context aggregation from Toolbox
- System prompt assembly with runtime context
- Task policy enforcement (token budgets per task type)
- Event journaling for memory systems
- Streaming response support

**Task Policies:**
| Task Type | Max Tokens | Timeout | Use Case |
|-----------|-----------|---------|----------|
| `chat.fast` | 256 | 600s | Quick answers |
| `code.edit` | 512 | 900s | Code modifications |
| `tool.json` | 512 | 900s | Structured output |
| `audit` | 768 | 1800s | System audits |
| `reason.hard` | 1024 | 1800s | Complex reasoning |

**Endpoints:**
```
POST /chat          - Main chat endpoint
POST /chat/stream   - Streaming chat
GET  /health        - Health check
GET  /status        - System status
```

---

#### `/router/app.py` - Model Router

Intelligent routing between LLM backends.

**Routing Logic:**
```python
def select_model(request):
    # Code-related queries → Qwen (better at code)
    if has_code_hints(request):
        return "qwen"

    # Gaming mode → Ollama (lightweight, saves RAM)
    if gaming_mode_active():
        return "ollama"

    # Default → Llama (general reasoning)
    return "llama"
```

**Features:**
- Heuristic-based model selection
- On-demand Qwen startup via systemd
- Fallback mechanisms (Qwen fails → Llama)
- Request wrapping for Llama3 instruct format

---

### Personality System

#### `/personality/personality.py` - Static Identity

Single source of truth for Frank's identity.

**Features:**
- Thread-safe hot-reloadable persona
- JSON-based persona definition (`frank.persona.json`)
- Modular system prompt assembly
- Tool policy enforcement
- SIGHUP signal for hot reload

**Persona Structure:**
```json
{
  "id": "frank.v2",
  "version": "2.0.0",
  "name": "Frank",
  "language": "de",
  "voice": {
    "tone": "locker, direkt, nicht übertrieben",
    "style_rules": [...]
  },
  "self_model": {
    "runs_local": true,
    "has_self_knowledge": true,
    "has_world_model": true
  },
  "capabilities": {...},
  "tool_policy": {...},
  "prompts": {...}
}
```

---

#### `/personality/e_pq.py` - Dynamic Personality (E-PQ v2.1)

The "soul" of Frank - a homeostatic personality system.

**Core Concepts:**

| Concept | Type | Description |
|---------|------|-------------|
| **Mood** | Transient | Short-term state from system logs (CPU temp, errors) |
| **Temperament** | Persistent | Long-term personality vectors, evolves over time |
| **Sarcasm Filter** | Detection | Cross-validates sentiment with system state |

**Personality Vectors** (all -1.0 to +1.0):
```python
precision_val    # -1 = creative, +1 = precise
risk_val         # -1 = cautious, +1 = bold
empathy_val      # -1 = distant, +1 = empathetic
autonomy_val     # -1 = asks first, +1 = autonomous
vigilance_val    # -1 = relaxed, +1 = alert
```

**Learning Algorithm:**
```
P_new = P_old + Σ(E_i × w_i × L)

Where:
- E_i = Event impact (-1 to +1)
- w_i = Event weight (0.1 to 0.9)
- L   = Learning rate (decreases with age)
```

**Event Weights:**
| Event | Weight | Effect |
|-------|--------|--------|
| `positive_feedback` | 0.2 | ↑ empathy, ↑ autonomy, ↑ mood |
| `task_failure` | 0.4 | ↓ autonomy, ↓ risk, ↑ vigilance |
| `system_error` | 0.6 | ↑ vigilance, ↓ mood |
| `kernel_panic` | 0.9 | ↑↑ vigilance, ↓↓ risk |

**Guardrails:**
- Homeostatic Reset: If 3+ vectors extreme (>0.9) for >48h, reset toward center
- Golden Snapshots: Weekly identity backups for recovery
- Age-based stability: Learning rate decreases over time

---

#### `/personality/self_knowledge.py` - Intrinsic Self-Knowledge

Frank's awareness of his own capabilities.

**Components:**

| Class | Purpose |
|-------|---------|
| `CapabilityRegistry` | Discovers available modules dynamically |
| `DatabaseInspector` | Introspects database stats |
| `ServiceHealthChecker` | TCP health checks on services |
| `BehaviorRules` | Decides when to explain vs. just act |
| `SelfKnowledge` | Main controller (singleton) |

**Two Modes:**

1. **Implicit Context** (~200 chars, every prompt):
```
[Selbst: 10 Subsysteme, Voice aktiv, Gaming aus, E-SIR 0/10, 436KB DBs, Mood neutral, Tag 42]
```

2. **Explicit Knowledge** (on direct query):
```markdown
# Was ich bin und kann

## Subsysteme
- Voice-Interaktion: wake_word, STT, TTS
- Selbstverbesserung (E-SIR): sandbox, genesis, rollback
...

## Gedächtnis
- Titan (84KB): Episodisches Gedächtnis
- World-Experience (140KB): Kausales Lernen
...
```

**Behavior Rules:**
| User Query | Action |
|------------|--------|
| "Was kannst du?" | Explain capabilities |
| "Mach Screenshot" | Just do it (no explanation) |
| "Wie lernst du?" | Explain memory systems |

---

### Memory Systems

#### `/tools/titan/` - Episodic Memory (E-CPMM v5.1)

Tri-hybrid storage for facts, events, and relationships.

**Architecture:**
```
┌─────────────────────────────────────────────┐
│              Titan Memory                    │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐     │
│  │ SQLite  │  │ Vector  │  │Knowledge│     │
│  │ (facts) │  │ Store   │  │  Graph  │     │
│  └────┬────┘  └────┬────┘  └────┬────┘     │
│       │            │            │           │
│       └────────────┼────────────┘           │
│                    ▼                        │
│            Unified Query API                │
└─────────────────────────────────────────────┘
```

**Tables:**
| Table | Purpose |
|-------|---------|
| `nodes` | Entities (people, concepts, files) |
| `edges` | Relationships between nodes |
| `events` | Timestamped occurrences |
| `claims` | Facts with confidence scores |
| `memory_fts` | Full-text search index |

**Features:**
- Semantic search via embeddings
- Confidence scoring for claims
- Relationship traversal
- Automatic pruning of old data

---

#### `/tools/world_experience_daemon.py` - Causal Memory

Frank's "subconscious" - learns cause-effect relationships.

**Core Concepts:**

| Concept | Description |
|---------|-------------|
| **Causal Links** | "When X happens, Y follows" relationships |
| **Patterns** | Recurring sequences of events |
| **Fingerprints** | Unique signatures for system states |
| **Entities** | Things Frank has observed |

**Features:**
- Bayesian confidence erosion (old beliefs decay)
- Anti-hallucination validation
- Gaming mode telemetry buffering
- Asymmetric quantization:
  - 7 days: Full resolution
  - 90 days: Dense summary
  - Older: Sparse patterns only

**Storage Limits:**
- 10 GB hard cap
- Intelligent purging (oldest, lowest confidence first)
- Heartbeat flush every 15 minutes

---

### Self-Improvement Engine

#### `/ext/e_sir.py` - E-SIR v2.5 "Genesis Fortress"

Controlled recursive self-improvement.

**Dual-Core Architecture:**

```
┌─────────────────────────────────────────────────┐
│              E-SIR v2.5                          │
│  ┌──────────────────┐  ┌──────────────────┐    │
│  │    OUROBOROS     │  │     GENESIS      │    │
│  │   (Stability)    │  │   (Evolution)    │    │
│  │                  │  │                  │    │
│  │ • Risk scoring   │  │ • Tool creation  │    │
│  │ • Audit trail    │  │ • Sandbox test   │    │
│  │ • Rollback       │  │ • Promotion      │    │
│  └──────────────────┘  └──────────────────┘    │
└─────────────────────────────────────────────────┘
```

**Hybrid Decision Matrix:**
```python
risk_score = base_risk × impact × (1 - confidence)

# Decision thresholds:
< 0.3  → Auto-approve
0.3-0.6 → Sandbox required
0.6-0.8 → Human review
> 0.8  → Auto-deny
```

**Risk Weights:**
| Action | Weight |
|--------|--------|
| `file_create` | 0.2 |
| `file_modify` | 0.5 |
| `file_delete` | 0.9 |
| `code_execute` | 0.6 |
| `config_change` | 0.6 |

**Safety Guardrails:**
- Max 3 recursion depth
- Max 10 modifications/day
- Max 20 sandbox runs/hour
- Forbidden actions blocked:
  - `rm -rf /`, fork bombs, `curl | sh`
- Protected paths:
  - `/database/`, `/ssh/`, `/gnupg/`

**Genesis Tool Creation:**
```python
# 1. Propose tool
propose_tool_creation(
    name="string_utils",
    code="def reverse(s): return s[::-1]",
    description="String utilities"
)

# 2. Sandbox test (automatic)
# 3. If pass → Create in /ext/genesis/
# 4. Auto-register in __init__.py
```

**Audit Trail:**
- Immutable hash-chain log
- Every action recorded with:
  - Timestamp, action type, risk score
  - Decision, outcome, previous hash
- Integrity verification available

---

### Voice Interaction

#### `/voice/voice_daemon.py` - Voice Control

Full voice I/O system.

**Components:**
| Component | Technology | Details |
|-----------|------------|---------|
| Wake Word | Keyword detection | "Hey Frank", "Hallo Frank", "Frank?" |
| STT | faster-whisper | Small model, German optimized |
| TTS | Piper | Thorsten voice (German male) |
| Fallback | espeak | If Piper unavailable |

**Audio Handling:**
- PulseAudio/PipeWire auto-detection
- Preferred devices: RODE microphones, Bluetooth speakers
- VAD (Voice Activity Detection) with configurable threshold

**Integration:**
```
Voice Input
    │
    ▼
┌─────────────┐
│ Wake Word   │──► "Hey Frank" detected
│ Detection   │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Whisper   │──► Speech to text
│    STT      │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Chat Overlay│──► Process request
│   Inbox     │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Piper     │──► Text to speech
│    TTS      │
└─────────────┘
```

---

### Gaming Mode

#### `/gaming/gaming_mode.py` - Resource Optimization

Automatic optimization during gaming sessions.

**Detection:**
- Monitors Steam game processes
- Detects via `pgrep` for Steam AppIDs

**Actions on Game Start:**
1. Stop heavy LLM services (Llama, Qwen)
2. Keep lightweight Ollama model
3. Show mini overlay
4. Buffer telemetry (don't lose data)

**Actions on Game End:**
1. Restart LLM services
2. Restore full overlay
3. Flush buffered telemetry

**Safety:**
- Never scan anti-cheat processes:
  - EasyAntiCheat
  - BattlEye
  - Vanguard
- Emergency kill-switch (<500ms response)

---

### Visual Feedback

#### `/live_wallpaper/frank_wallpaperd.py` - Live Wallpaper

Real-time visual representation of Frank's state.

**Visual Elements:**
- Cybernetic head (SDF-rendered)
- Eye tracking (follows mouse)
- Voice waveform (mouth area)
- Event-reactive animations

**Event Reactions:**
| Event | Visual Effect |
|-------|---------------|
| `inference.start` | Eye glow + brain particles |
| `chat.request` | Vertical scan beam |
| `voice.recognized` | Mouth waveform activity |
| `error` | Red glow + chromatic aberration |

**Performance:**
- 30 FPS default, 15 FPS idle
- GPU usage <5% when idle
- Auto-restart on crash (max 50 restarts)

---

### System Tools

#### `/tools/toolboxd.py` - System Introspection

Comprehensive system access API.

**Capabilities:**

| Category | Functions |
|----------|-----------|
| **System** | CPU, RAM, disk, temps, uptime, load |
| **Hardware** | BIOS, cache, GPU features, PCI devices |
| **Drivers** | Loaded kernel modules with versions |
| **USB** | Device enumeration with vendor info |
| **Network** | Interfaces, IPs, MACs, throughput |
| **Files** | List, read, move, copy, delete |
| **Apps** | Search, open, close (Desktop/Flatpak/Snap) |
| **Steam** | List games, launch, close |
| **Desktop** | Screenshot, URL opening |

**Security Model:**
- Read-write in MUTABLE_ROOTS only
- Read-only in `/proc`, `/sys`, `/etc`, `/var/log`
- No access to sensitive paths

---

#### `/tools/fas_scavenger.py` - F.A.S. (Frank's Autonomous Scavenger)

GitHub intelligence and code analysis.

**Three-Phase Model:**
```
Phase 1: Scout
├── Search GitHub trending
├── Filter by relevance
└── Score interest (0-1)

Phase 2: Triage
├── Clone high-score repos
├── Analyze structure
└── Extract metadata

Phase 3: Extract
├── Parse code features
├── Identify patterns
└── Store in database
```

**Guardrails:**
- Time window: 02:00-06:00 only
- 20 GB sandbox quota
- Gaming mode kill-switch
- Max 5 deep-dives per day
- CPU limit check before run

---

#### `/tools/network_sentinel.py` - Network Monitoring

Security and topology awareness.

**Features:**
- Nmap service fingerprinting
- Scapy deep packet inspection
- Network topology mapping
- Security event logging

**Anti-Cheat Protection:**
- Never scan game-related processes
- Whitelist: EasyAntiCheat, BattlEye
- Emergency stop during gaming (<500ms)

---

## Databases

### Overview

| Database | Size | Purpose | Key Tables |
|----------|------|---------|------------|
| `titan.db` | 84 KB | Episodic memory | nodes, edges, events, claims |
| `world_experience.db` | 140 KB | Causal learning | entities, causal_links, patterns |
| `e_sir.db` | 60 KB | Self-improvement | audit_log, snapshots, genesis_tools |
| `system_bridge.db` | 120 KB | Hardware state | drivers, driver_observations |
| `fas_scavenger.db` | 32 KB | Code analysis | repo_metadata, features |

### Schema Details

#### titan.db
```sql
-- Core entities
CREATE TABLE nodes (
    id INTEGER PRIMARY KEY,
    type TEXT,           -- 'person', 'concept', 'file'
    name TEXT,
    created_at DATETIME,
    metadata JSON
);

-- Relationships
CREATE TABLE edges (
    id INTEGER PRIMARY KEY,
    source_id INTEGER,
    target_id INTEGER,
    relation TEXT,       -- 'knows', 'contains', 'causes'
    weight REAL,
    FOREIGN KEY (source_id) REFERENCES nodes(id),
    FOREIGN KEY (target_id) REFERENCES nodes(id)
);

-- Facts with confidence
CREATE TABLE claims (
    id INTEGER PRIMARY KEY,
    subject TEXT,
    predicate TEXT,
    object TEXT,
    confidence REAL,     -- 0.0 to 1.0
    source TEXT,
    created_at DATETIME
);
```

#### world_experience.db
```sql
-- Observed entities
CREATE TABLE entities (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE,
    type TEXT,
    first_seen DATETIME,
    last_seen DATETIME,
    observation_count INTEGER
);

-- Cause-effect relationships
CREATE TABLE causal_links (
    id INTEGER PRIMARY KEY,
    cause_entity_id INTEGER,
    effect_entity_id INTEGER,
    confidence REAL,
    observation_count INTEGER,
    last_observed DATETIME
);

-- Personality state (E-PQ)
CREATE TABLE personality_state (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME,
    precision_val REAL,
    risk_val REAL,
    empathy_val REAL,
    autonomy_val REAL,
    vigilance_val REAL,
    mood_buffer REAL
);
```

#### e_sir.db
```sql
-- Immutable audit log (hash chain)
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME,
    action_type TEXT,
    description TEXT,
    risk_score REAL,
    decision TEXT,
    outcome TEXT,
    previous_hash TEXT,
    entry_hash TEXT UNIQUE
);

-- File snapshots for rollback
CREATE TABLE snapshots (
    id INTEGER PRIMARY KEY,
    snapshot_id TEXT UNIQUE,
    file_path TEXT,
    content_hash TEXT,
    backup_path TEXT,
    timestamp DATETIME
);

-- Created tools
CREATE TABLE genesis_tools (
    id INTEGER PRIMARY KEY,
    tool_name TEXT UNIQUE,
    tool_path TEXT,
    description TEXT,
    created_at DATETIME,
    test_passed INTEGER
);
```

---

## Emergent Behavior

The true power of Frank emerges from the interconnection of all systems.

### Adaptive Intelligence

```
User: "Write a Python function to parse JSON"

                    ┌─────────────────┐
                    │  Router detects │
                    │  code keywords  │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ Routes to Qwen  │
                    │ (code-optimized)│
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ High-quality    │
                    │ code generation │
                    └─────────────────┘
```

### Context-Aware Responses

```
User: "What's my CPU temperature?"

    ┌──────────────┐
    │   Core       │
    │   receives   │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐     ┌──────────────┐
    │   Toolbox    │────►│   E-PQ       │
    │   CPU: 65°C  │     │   Mood: OK   │
    └──────┬───────┘     └──────┬───────┘
           │                    │
           └────────┬───────────┘
                    │
                    ▼
           ┌──────────────────────┐
           │ "Deine CPU ist bei   │
           │  65°C - alles cool." │
           │ (calm, friendly tone)│
           └──────────────────────┘
```

### Learning Loop

```
User praises Frank: "Great job!"

    ┌──────────────┐
    │   E-PQ       │
    │   detects    │
    │   positive   │
    │   feedback   │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ Update       │
    │ personality: │
    │ ↑ empathy    │
    │ ↑ autonomy   │
    │ ↑ mood       │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ World-Exp    │
    │ records:     │
    │ "Praise →    │
    │  confidence" │
    └──────────────┘
```

### Gaming Mode Transition

```
User starts Cyberpunk 2077

    ┌──────────────┐
    │ Gaming Mode  │
    │ detects      │
    │ Steam game   │
    └──────┬───────┘
           │
           ├────────────────────────────────┐
           │                                │
           ▼                                ▼
    ┌──────────────┐                ┌──────────────┐
    │ Stop heavy   │                │ World-Exp    │
    │ LLM services │                │ buffers      │
    │ (Llama,Qwen) │                │ telemetry    │
    └──────────────┘                └──────────────┘
           │
           ▼
    ┌──────────────┐
    │ Keep Ollama  │
    │ (lightweight)│
    │ Mini overlay │
    └──────────────┘

User exits game → Full restoration
```

### Self-Improvement Cycle

```
Frank identifies repetitive task

    ┌──────────────┐
    │ Propose      │
    │ new tool     │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ E-SIR        │
    │ Risk: 0.4    │
    │ → Sandbox    │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ Test passes  │
    │ in sandbox   │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ Genesis      │
    │ promotes     │
    │ to /ext/     │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ Audit log    │
    │ records      │
    │ (hash chain) │
    └──────────────┘
```

### Memory Integration

```
User: "Remember last time I asked about Docker?"

    ┌──────────────┐
    │ Titan        │
    │ semantic     │
    │ search       │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ Found: Event │
    │ "Docker      │
    │ question"    │
    │ 3 days ago   │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ World-Exp    │
    │ adds causal  │
    │ context      │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ Response     │
    │ with memory  │
    │ context      │
    └──────────────┘
```

---

## API Reference

### Core API (`:8088`)

```http
POST /chat
Content-Type: application/json

{
  "message": "Hello Frank",
  "context": {},
  "task_type": "chat.fast"
}

Response:
{
  "response": "Hey! Was kann ich für dich tun?",
  "tokens_used": 24,
  "model": "llama"
}
```

### Router API (`:8091`)

```http
POST /route
Content-Type: application/json

{
  "message": "Write a Python function",
  "context": {}
}

Response:
{
  "model": "qwen",
  "reason": "code_hints_detected"
}
```

### Toolbox API (`:8096`)

```http
GET /sys/summary

Response:
{
  "cpu": "AMD Ryzen 9 5900X",
  "ram": "32GB (18GB used)",
  "disk": "1TB NVMe (400GB free)",
  "temps": {"cpu": 45, "gpu": 38}
}
```

### Self-Knowledge API

```python
from personality import get_self_knowledge

sk = get_self_knowledge()

# Implicit context for prompts
ctx = sk.get_implicit_context()
# "[Selbst: 10 Subsysteme, Voice aktiv, ...]"

# Explicit knowledge for queries
knowledge = sk.get_explicit_knowledge("self_improvement")
# Full E-SIR explanation

# System status
status = sk.get_system_status()
# {"subsystems": {...}, "databases": {...}, "services": {...}}
```

### E-SIR API

```python
from ext import propose_tool_creation, safe_file_transaction

# Create a Genesis tool
success, msg = propose_tool_creation(
    tool_name="my_tool",
    code="def helper(): pass",
    description="A helper function"
)

# Safe file modification with auto-rollback
success, msg = safe_file_transaction(
    "/path/to/file.py",
    lambda: modify_file()
)
```

### E-PQ API

```python
from personality import get_personality_context, process_event

# Get current personality state
ctx = get_personality_context()
# {"temperament": "...", "mood": "...", "vectors": {...}}

# Process an event
result = process_event(
    "positive_feedback",
    sentiment="positive"
)
# Updates personality vectors
```

---

## License

MIT License - See LICENSE file for details.

## Contributing

See CONTRIBUTING.md for guidelines.

---

*Frank AI System - Embodied Intelligence for Human-Machine Collaboration*
