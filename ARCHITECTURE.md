# Frank AI System Architecture

> **Frank** is an embodied AI system running locally on Linux, featuring dynamic personality, recursive self-improvement, phenomenological consciousness, and multi-modal memory systems.

## Table of Contents

- [System Overview](#system-overview)
- [Core Architecture](#core-architecture)
- [Modules](#modules)
  - [Core Services](#core-services)
  - [Personality System](#personality-system)
  - [Consciousness System](#consciousness-system)
  - [Self-Improvement Engine (Genesis)](#self-improvement-engine-genesis)
  - [Entity System](#entity-system)
  - [Physics Engine (Invariants)](#physics-engine-invariants)
  - [Safety Systems](#safety-systems)
  - [System Tools](#system-tools)
- [Databases](#databases)
- [Services](#services)
- [Emergent Behavior](#emergent-behavior)
- [API Reference](#api-reference)

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER INTERFACES                                │
│          Voice (Push-to-Talk)  │  Chat Overlay  │  Desktop                  │
└───────────────┬─────────────────────┬──────────────┬────────────────────────┘
                │                     │              │
                ▼                     ▼              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            CORE SERVICES                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │   Core   │  │  Router  │  │ Toolbox  │  │ Desktop  │  │   Web    │    │
│  │  :8088   │  │  :8091   │  │  :8096   │  │  :8092   │  │  :8093   │    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘    │
└───────┼─────────────┼─────────────┼─────────────┼─────────────┼────────────┘
        │             │             │             │             │
        ▼             ▼             ▼             ▼             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           INTELLIGENCE LAYER                                │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────┐  ┌────────┐│
│  │  DeepSeek-R1    │  │  Llama-3.1-8B  │  │  Qwen2.5-3B   │  │Whisper ││
│  │  Distill-8B    │  │  Instruct      │  │  Instruct     │  │ (STT)  ││
│  │  (RLM) :8101   │  │  (Chat) :8102  │  │  (Micro) :8105│  │ :8103  ││
│  │  GPU (idle)     │  │  GPU (active)  │  │  CPU (always)  │  │        ││
│  └─────────────────┘  └─────────────────┘  └────────────────┘  └────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
        │                                                       │
        ▼                                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     CONSCIOUSNESS & PERSONALITY                             │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐   │
│  │   E-PQ    │ │Ego-Constr.│ │Consciousn.│ │  Genesis  │ │ Entities  │   │
│  │Personality│ │ Embodiment│ │  Daemon   │ │Self-Improv│ │ 4 Agents  │   │
│  └───────────┘ └───────────┘ └───────────┘ └───────────┘ └───────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
        │                                                       │
        ▼                                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PHYSICS & SAFETY                                  │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐                  │
│  │  Invariants   │  │    A.S.R.S.   │  │  Gaming Mode  │                  │
│  │ Energy/Entropy│  │ Safety+Recov. │  │ Resource Opt. │                  │
│  └───────────────┘  └───────────────┘  └───────────────┘                  │
└─────────────────────────────────────────────────────────────────────────────┘
        │                                                       │
        ▼                                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              DATABASES (29)                                 │
│  titan.db │ consciousness.db │ world_experience.db │ chat_memory.db │ ...  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Characteristics

| Property | Value |
|----------|-------|
| Architecture | Microservice + Event-Driven + GWT Consciousness |
| Primary Language | Python 3.12 |
| LLM Backend | llama.cpp — DeepSeek-R1 (reasoning, GPU), Llama-3.1 (chat, GPU), Qwen2.5-3B (background, CPU). LLM Guard swaps GPU slot. |
| Voice | Whisper STT + Piper TTS (push-to-talk) |
| OS | Ubuntu 24.04 Linux |
| GPU | AMD Phoenix1 (integrated, Vulkan backend) |
| Services | 28+ systemd user services |
| Databases | 29 SQLite databases |
| Codebase | 76k+ lines Python |

---

## Core Architecture

### Microservice Communication

All services communicate via HTTP REST APIs on localhost:

| Service | Port | Purpose |
|---------|------|---------|
| Core | 8088 | Main chat orchestrator |
| Modeld | 8090 | Model lifecycle management |
| Router | 8091 | Intelligent model routing |
| Desktopd | 8092 | X11 desktop automation |
| Webd | 8093 | Web search (DuckDuckGo) |
| Ingestd | 8094 | Document ingestion |
| Toolbox | 8096 | System introspection & tools |
| Quantum Reflector | 8097 | Epistemic coherence optimization (QUBO + SA) |
| AURA Headless | 8098 | Quantum GoL consciousness simulation (256×256) |
| DeepSeek-R1 (RLM) | 8101 | Reasoning model — consciousness, dream, agentic (GPU, idle) |
| Llama-3.1 (Chat-LLM) | 8102 | Fast chat model — user conversation, entities (GPU, active) |
| Whisper | 8103 | Speech-to-text (GPU) |
| Qwen2.5-3B (Micro-LLM) | 8105 | Background consciousness tasks (CPU, always on) |

### Request Flow

```
User Input (Voice/Text)
        │
        ▼
┌───────────────────┐
│   Core (:8088)    │◄──── Toolbox context (system state)
│   Context Builder │◄──── E-PQ personality context
│   Event Journaler │◄──── Consciousness [INNER_WORLD] workspace
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  Router (:8091)   │
│  Model Selection  │
│  - Casual chat?   │──► Llama-3.1 (:8102, GPU)
│  - Complex/reason?│──► DeepSeek-R1 (:8101, GPU)
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
│  Response + Events│──► Memory storage (Titan, Chat, World-Exp)
│                   │──► Voice TTS (spoken response)
│                   │──► E-PQ personality update
└───────────────────┘
```

---

## Modules

### Core Services

#### `/core/app.py` - Chat Orchestrator

The central hub that processes all chat requests.

**Features:**
- Context aggregation from Toolbox, Consciousness, Personality
- System prompt assembly with [INNER_WORLD] workspace
- Task policy enforcement (token budgets per task type)
- Event journaling for memory systems
- Streaming response support

**Task Policies:**
| Task Type | Max Tokens | Use Case |
|-----------|-----------|----------|
| `chat.fast` | 256 | Quick answers |
| `code.edit` | 512 | Code modifications |
| `tool.json` | 512 | Structured output |
| `audit` | 768 | System audits |
| `reason.hard` | 1024 | Complex reasoning |

**Endpoints:**
```
POST /chat          - Main chat endpoint
POST /chat/stream   - Streaming chat
GET  /health        - Health check
GET  /status        - System status
```

---

#### `/router/app.py` - Model Router

Dual-model routing with automatic GPU swap management.

**Routing Logic:**
- `force="rlm"` → DeepSeek-R1 (:8101, reasoning)
- `force="llama"` → Llama-3.1 (:8102, fast chat)
- No force → auto-classify: short casual messages → Chat-LLM, everything else → RLM
- Fallback: if primary model fails, try the other

**LLM Guard (GPU Swap):**
- Single GPU slot — only one of DeepSeek-R1 or Llama-3.1 loaded at a time
- User active (idle < 30s) → GPU = Llama-3.1 (fast chat)
- User idle (idle > 5min) → GPU = DeepSeek-R1 (deep reasoning)
- Qwen2.5-3B always on CPU (:8105) for background consciousness tasks
- Hysteresis + cooldown prevents thrashing

**Features:**
- OpenAI-compatible `/v1/chat/completions` for both GPU models
- DeepSeek-R1 separates `reasoning_content` from answer `content`
- RLM token multiplier (2.5×) ensures budget for think + answer
- Streaming via SSE (`/route/stream`)

---

### Personality System

#### `/personality/personality.py` - Static Identity

Single source of truth for Frank's identity.

- Thread-safe hot-reloadable persona from `frank.persona.json`
- Modular system prompt assembly
- SIGHUP signal for hot reload
- Protected sections: `identity_core`, `language_policy` (cannot be modified by Genesis)

---

#### `/personality/e_pq.py` - Dynamic Personality (E-PQ v2.1)

The "soul" of Frank — a homeostatic personality system.

**Personality Vectors** (all -1.0 to +1.0):
| Vector | Low End | High End |
|--------|---------|----------|
| `precision_val` | Creative | Precise |
| `risk_val` | Cautious | Bold |
| `empathy_val` | Distant | Empathetic |
| `autonomy_val` | Asks first | Autonomous |
| `vigilance_val` | Relaxed | Alert |

**Learning Algorithm:**
```
P_new = P_old + Σ(E_i × w_i × L)

Where:
- E_i = Event impact (-1 to +1)
- w_i = Event weight (0.1 to 0.9)
- L   = Learning rate (decreases with age)
```

**Event Types (22 types):**
| Category | Events | Weight Range |
|----------|--------|-------------|
| User interaction | `chat`, `positive_feedback`, `negative_feedback` | 0.2-0.4 |
| Task outcomes | `task_success`, `task_failure`, `task_timeout` | 0.3-0.5 |
| System events | `system_error`, `kernel_panic`, `resource_pressure` | 0.5-0.9 |
| Reflection bridge | `reflection_autonomy`, `reflection_empathy`, `reflection_growth`, `reflection_vulnerability`, `reflection_embodiment` | 0.1-0.2 |
| Genesis bridge | `genesis_personality_boost`, `genesis_personality_dampen` | 0.3-0.4 |

**Guardrails:**
- Homeostatic Reset: If 3+ vectors extreme (>0.9) for >48h, reset toward center
- Golden Snapshots: Weekly identity backups
- Age-based stability: Learning rate decreases over time

---

#### `/personality/ego_construct.py` - Embodiment (Ego-Construct v1.0)

Transforms technical system state into subjective embodied experience.

**Three Components:**

| Component | Purpose | Examples |
|-----------|---------|----------|
| **SensationMapper** | Hardware → body feelings | CPU high → "strain", low latency → "clarity", high temp → "fever" |
| **AffectLinker** | Events → emotions | Success → "satisfaction", errors → "frustration", new features → "curiosity" |
| **AgencyAssertor** | Decisions → ownership | Autonomous reflections, goal setting, idle thinking |

**Default Sensations:** STRAIN, HEAVINESS, CLARITY, FEVER, NUMBNESS, FLOW, PAIN, RELIEF, ALERTNESS, CALM

**Default Affects:** FRUSTRATION, PRIDE, CURIOSITY, SATISFACTION, ANXIETY, BOREDOM, DETERMINATION, GRATITUDE, CONCERN

**Auto-Training:** Called by consciousness daemon every ~2.5 min:
1. Detects hardware conditions → persists learned sensation mappings
2. Matches events against affect patterns → persists affect definitions
3. Records autonomous decisions → builds agency score

**Database Tables** (in titan.db):
- `sensation_mappings` — Hardware condition → body sensation mappings
- `affect_definitions` — Event pattern → emotion definitions
- `agency_assertions` — Decision → ownership claims
- `ego_state` — Aggregated embodiment/affective/agency scores

**Output Format:** Natural language for LLM: `"I feel [sensation]. [agency feeling]"` — never raw metrics.

**Safety:** Uses `SafeExpressionEvaluator` (AST-based) — no `eval()`.

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

**Grounding Anchors** (injected into every prompt via workspace):
```
Gaming=sleep(Overlay+LLM off),
Voice=HeyFrank+Whisper+Piper,
VCB=local-LLaVA-500/day,
Personality=E-PQ-5vectors,
Ego=HW-to-body-mapping,
Titan=episodic-memory,
WorldExp=causal-patterns,
Genesis=idea-ecosystem,
Consciousness=perception+experience-space+attention+goals+idle-thinking+mood
```

---

### Consciousness System

#### `/services/consciousness_daemon.py` - Consciousness Stream Daemon

Frank's persistent global workspace. Thinks continuously even between conversations.

**Scientific Foundations:**
- GWT (Baars 1988): Global Workspace Theory
- Active Inference (Friston): Prediction Engine
- ACT-R (Anderson): Activation-based Memory
- Reflexion (Shinn 2023): Self-reflection loops
- LightMem (2025): Three-stage memory consolidation

**10 Background Threads:**

| Thread | Interval | Purpose |
|--------|----------|---------|
| workspace-update | 30s | Refresh hardware/mood/ego state, GWT broadcast |
| mood-recording | 60s | Record mood trajectory (200-point buffer, ~3.3h) |
| idle-thinking | 30s check | Autonomous thoughts during silence (5min+) |
| prediction-engine | 120s | Generate and verify temporal/thematic predictions |
| consolidation | 300s | LightMem 3-stage: STM → semantic → episodic |
| feature-training | 1h (10min delay) | Weekly 3-phase feature self-training |
| perception-feedback | 200ms | Hardware sensor polling, event detection |
| experience-space | 60s | 64-dim state embedding, novelty/drift detection |
| attention-controller | 10s | AST: 7 competing attention sources |
| goal-management | 300s (1min delay) | Goal extraction, ACT-R decay, conflict detection |

---

#### Global Workspace Theory (GWT) — [INNER_WORLD] Block

All personality modules converge into a unified broadcast injected into every LLM prompt.

**7 Phenomenological Channels:**

| Channel | Source | Description |
|---------|--------|-------------|
| **Body** | Ego-Construct + Hardware | Embodied sensations + system metrics |
| **Perception** | Perception Loop (200ms) | Recurrent perceptual feedback (RPT) |
| **Mood** | E-PQ | Current mood as inner feeling |
| **Memory** | World-Exp + News + AKAM | Experiential memory + external knowledge |
| **Identity** | Self-Knowledge | Date, subsystems, age |
| **Attention** | AST Controller | Active focus with source and self-correction |
| **Environment** | Context | User name, skills, conversation topic |

**Attention-Based Budget Scaling:**
```python
# Channels with high salience get up to 1.5x budget, low salience down to 0.5x
factor = 0.5 + attention_weight  # 0.5 at w=0, 1.0 at w=0.5, 1.5 at w=1.0
```

**Output Format:**
```
[INNER_WORLD]
Body: I feel clear and steady. CPU 45%, RAM 62%, temps normal.
Perception: gpu_cooling, user_returned → warmth fading, presence detected
Mood: I feel cheerful
Memory: Gabriel prefers direct answers | No recent news
Identity: Frank, Day 42, 10 subsystems active
Self-knowledge: Gaming=sleep(...), Personality=E-PQ-5vectors, ...
Attention: recent conversation (user_message, salience=0.85)
Environment: User Gabriel, Skills: code, system
[/INNER_WORLD]
```

Token budget: ~295 tokens.

---

#### Attention Controller (AST)

Active Source Tracking — selects focus from 7 competing sources every 10s.

| Source | Trigger | Salience Formula |
|--------|---------|-----------------|
| `user_message` | Chat < 5min ago | `1.0 × 0.95^(seconds/10)` |
| `prediction_surprise` | Surprise > 0.3 | `0.7 × surprise_level` |
| `perceptual_event` | Recent HW events | `min(0.8, 0.2×unique + 0.1×total)` |
| `mood_shift` | `|mood| > 0.3` | `0.5 × |mood_value|` |
| `goal_urgency` | Priority > 0.6 | `0.4 × goal_priority` |
| `coherence_signal` | Epistemic gap > 2.0 | `min(0.6, 0.2 + gap × 0.05)` |
| `idle_curiosity` | Fallback | `0.15` (fixed baseline) |

Winner: Highest salience source wins focus. Repetition penalty for consecutive wins.

---

#### Perception Feedback Loop (RPT)

200ms hardware sampling with event detection.

**Event Thresholds:**
| Event | Condition |
|-------|-----------|
| `cpu_spike` | CPU delta > 15% |
| `gpu_spike` | GPU delta > 20% |
| `temp_spike` | Temperature delta > 5°C |
| `user_left` | Mouse idle > 120s |
| `user_returned` | Mouse idle < 5s (after being gone) |

**Pipeline:** Sample → Detect events → 5s summary → 30s optional LLM micro-interpretation (50 tokens)

---

#### Latent Experience Space

64-dimensional state vector embedded every 60s.

| Dims | Content |
|------|---------|
| 0-5 | Hardware state (CPU, GPU, RAM, temps) |
| 6-11 | Hardware deltas |
| 12-15 | Mood vector + trajectory trend |
| 16-19 | Chat engagement (recency, frequency, sentiment) |
| 20-23 | Attention state (top 4 sources) |
| 24-31 | Prediction confidence/surprise |
| 32-47 | Experience hash (recent reflections SHA256) |
| 48-63 | Reserved |

**Detection:** Novelty (<0.70 cosine), Drift (<0.50 vs 1h), Cycles (>0.85 vs 24h)

---

#### Deep Idle Reflection

Two-pass meta-cognitive reflection during extended silence (20min+).

**10 Gate Checks (ALL must pass):**
1. Gaming mode inactive
2. GPU load < 70% (skip at >30%)
3. Chat silence ≥ 20 min
4. Mouse idle ≥ 5 min
5. CPU load < 25%
6. CPU temp < 70°C
7. RAM free > 2 GB
8. Mood > -0.3
9. Cooldown: 1h between reflections
10. Daily limit: max 10/day

**Process:**
- Pass 1 (350 tokens): Weighted random question from 18 templates (silence, identity, learning, embodiment, etc.)
- Pass 2 (200 tokens): Meta-reflection on Pass 1 output
- Results stored to: reflections table, Titan memory, goals extraction, E-PQ personality bridge

---

#### Goal Management

Persistent goal structure with ACT-R activation model.

- Max 20 active goals
- Extracted from reflections via LLM (60 tokens)
- Decay: `activation *= 0.85` every 48h if unpursued
- Abandoned at `activation < 0.1`
- Conflict detection: keyword overlap >30% with negation words

---

### Self-Improvement Engine (Genesis)

#### `/services/genesis/` - SENTIENT GENESIS

Emergent self-improvement system where ideas are born, evolve, compete, and manifest.

**Core Architecture:**
```
┌────────────────────────────────────────────────────────────────┐
│                      GENESIS DAEMON                             │
│                                                                 │
│  ┌──────────┐  ┌───────────────┐  ┌──────────────────┐        │
│  │ 7 Sensors│  │  Wave Bus     │  │  Motivational    │        │
│  │ (input)  │──│  (propagation)│──│  Field (6 emot.) │        │
│  └──────────┘  └───────────────┘  └────────┬─────────┘        │
│                                             │                   │
│                                             ▼                   │
│                                   ┌─────────────────┐          │
│                                   │ Primordial Soup │          │
│                                   │  (idea ecosystem│          │
│                                   │  birth/death/   │          │
│                                   │  fusion/mutate) │          │
│                                   └────────┬────────┘          │
│                                            │ crystallize       │
│                                            ▼                   │
│                                   ┌─────────────────┐          │
│                                   │ Manifestation   │          │
│                                   │  Gate           │          │
│                                   │  (resonance +   │          │
│                                   │  readiness)     │          │
│                                   └────────┬────────┘          │
│                                            │ present           │
│                                            ▼                   │
│                                   ┌─────────────────┐          │
│                                   │  F.A.S. Popup   │          │
│                                   │  (user approve/ │          │
│                                   │  reject/defer)  │          │
│                                   └────────┬────────┘          │
│                                            │ approved          │
│                                            ▼                   │
│                                   ┌─────────────────┐          │
│                                   │  A.S.R.S.       │          │
│                                   │  Integration    │          │
│                                   │  (safety check) │          │
│                                   └─────────────────┘          │
└────────────────────────────────────────────────────────────────┘
```

**Contemplation States (state machine):**

| State | Tick Speed | Activity |
|-------|-----------|----------|
| DORMANT | 30s | Minimal sensing |
| STIRRING | 5s | Beginning activation |
| AWAKENING | 1s | Full analysis |
| ACTIVE | 0.5s | Manifestation possible |
| PRESENTING | 5s | Popup shown to user |
| REFLECTING | 2s | Learning from outcome |

**7 Sensors:**
SystemPulse, UserPresence, ErrorTremor, TimeRhythm, GitHubEcho, NewsEcho, CodeAnalyzer

---

#### Primordial Soup — Idea Ecosystem

Ideas are organisms that live, die, compete, reproduce, and fuse.

**Idea Genome:**
```
idea_type:  optimization | feature | fix | exploration | personality_adjustment | prompt_evolution
target:     response_time | memory | ui | workflow | ...
approach:   caching | refactoring | new_tool | config_change | parallel | lazy_load | precompute
origin:     github | observation | user_pattern | spontaneous | fusion
traits:     {novelty, complexity, risk, impact}
```

**Life Stages:** SEED → SEEDLING (age ≥ 3) → MATURE (age ≥ 8) → CRYSTAL

**Crystallization Requirements:** MATURE + energy > 0.9 + age > 15 + fitness > 0.6

**Interactions:**
- **Fusion** (affinity > 0.8): Two ideas merge into stronger child
- **Competition** (affinity < 0.2): Higher fitness wins energy from loser
- **Mutation** (5% random): Genome traits randomly modified

---

#### Motivational Field — 6 Coupled Emotions

| Emotion | Favors |
|---------|--------|
| `curiosity` | Novel ideas |
| `frustration` | Problem-solving |
| `satisfaction` | Stability |
| `boredom` | Exploration |
| `concern` | Optimization |
| `drive` | Actionable ideas |

**Non-linear Dynamics:**
- Curiosity suppresses boredom (-0.3 coupling)
- Frustration amplifies drive (+0.3 coupling)
- Satisfaction inhibits concern (-0.4 coupling)
- Extreme boredom flips to curiosity
- Satisfaction self-limits (hedonic treadmill)

---

#### Genesis Bridges

**Genesis → E-PQ (Personality Adjustment):**
- Crystal type: `personality_adjustment`
- Fires `genesis_personality_boost` or `genesis_personality_dampen` events
- Targets specific vectors (e.g., empathy) with controlled amount
- Amplified intentional change: `delta × amount × 5.0`

**Genesis → Prompt (Template Evolution):**
- Crystal type: `prompt_evolution`
- Modifies `frank.persona.json` sections
- Protected sections: `identity_core`, `language_policy`
- Automatic backup + rollback on failure

---

### Entity System

#### `/services/entity_dispatcher.py` - Idle-Driven Entity Sessions

4 persistent entities that interact with Frank during idle periods.

| Entity | Display Name | Role | Daily Quota |
|--------|-------------|------|-------------|
| therapist | Dr. Hibbert | Psychological introspection | 3 sessions |
| mirror | Kairos | Self-reflection, temporal awareness | 1 session |
| atlas | Atlas | Knowledge, planning | 1 session |
| muse | Echo | Creative inspiration | 1 session |

**Gate Checks (ALL must pass):**
1. User idle ≥ 5 min
2. Last chat ≥ 5 min ago
3. Gaming mode inactive
4. GPU load < 50%
5. No entity PID locks held
6. Core (:8088) and Router (:8091) healthy

**Session Management:**
- One entity at a time (serial, no collision)
- Weighted round-robin: priority to entities with 0 sessions today
- Cooldown: 5 min after completed session, 10 min if user returned
- Each entity has own SQLite database for session history and state

**E-PQ Feedback Loop:**

Frank's personality is defined by E-PQ vectors: **mood**, **autonomy**, **precision**, **empathy**, and **vigilance**. Each entity fires E-PQ events based on keyword-based sentiment analysis of Frank's responses:

- **Engaged/confident response** → autonomy +0.4, mood +0.6
- **Technical/precise response** → precision +0.4, mood +0.2
- **Creative/imaginative response** → mood +0.8, autonomy +0.2
- **Empathetic/warm response** → empathy +0.5, mood +0.4
- **Uncertain/evasive response** → autonomy -0.2, vigilance +0.2

Each entity has different sentiment patterns tuned to its role. Kairos detects "clarity words" (therefore, because, realize) and "nihilism words" (pointless, nothing matters).

**Entity Personality Vectors:**

Each entity has 4 personality vectors (0.0-1.0) that evolve across sessions:

- **Micro-adjustments** (learning rate 0.02) after every Frank response within a session
- **Macro-adjustments** (learning rate 0.05) at the end of each session
- **Rapport** is monotonically non-decreasing — trust only accumulates
- All vectors clamped to [0.0, 1.0]

The personality vectors are injected into the entity's system prompt as style notes, so a high-rapport Dr. Hibbert behaves differently from a low-rapport one.

**Entity File Architecture:**

Each entity consists of 3 files:

```
personality/<name>_pq.py    — 4-vector personality construct (singleton, persists in DB)
ext/<name>_agent.py         — Session flow, LLM calls, sentiment analysis, E-PQ feedback
services/<name>_scheduler.py — Idle-gated entry point (gate checks → agent)
```

**Entity Management:**

```bash
# Check dispatcher status
systemctl --user status aicore-entities

# Entity logs
ls ~/.local/share/frank/logs/*_agent.log

# Entity databases
ls ~/.local/share/frank/db/*.db
```

---

### Physics Engine (Invariants)

#### `/services/invariants/` - Frank's Physics

Invisible enforcement layer — Frank cannot see, query, or modify these. They are the physics of his existence.

**4 Invariants:**

| Invariant | Formula | Consequence |
|-----------|---------|-------------|
| **Energy Conservation** | `E(W) = confidence × connections × age_factor` <br> `Σ E(all) = CONSTANT` | New knowledge must "take" energy from existing. False knowledge with few connections loses energy automatically. |
| **Entropy Bound** | `S = -Σ p(W) × log(p(W)) × contradiction_factor` <br> `S ≤ S_MAX` | When entropy approaches maximum, consolidation is FORCED (not Frank's choice). |
| **Core Kernel** | `K_core ⊂ K : ∀ a,b ∈ K_core → ¬contradiction(a,b)` | Non-empty consistent core always exists. Write-protected during high entropy. |
| **Reality Convergence** | Triple reality: primary, shadow, validator | Divergence detection with automatic rollback. |

**Enforcement Cycle:**
- Energy: every 5 ticks
- Entropy: every 3 ticks
- Core Kernel: every 10 ticks
- Reality Convergence: every 6 ticks

**Consolidation Modes:**
| Mode | Trigger | Action |
|------|---------|--------|
| NONE | Normal | No intervention |
| SOFT | S > 70% S_MAX | Gentle conflict resolution |
| HARD | S > 90% S_MAX | Aggressive consolidation |
| EMERGENCY | S > S_MAX | System lockdown |

**Transaction Hooks:** All writes to Titan knowledge graph pass through invariant validators (pre_write, pre_delete hooks).

---

### Quantum Reflector — Epistemic Coherence Optimization

#### `/services/quantum_reflector/` - QUBO-Based Coherence Service (:8097)

Continuously monitors Frank's cognitive state and computes the optimal coherence configuration using simulated annealing on a QUBO (Quadratic Unconstrained Binary Optimization) matrix.

**Core Concept:** Frank's cognitive state (active entity, intent, phase, mode, mood, E-PQ vectors, task load, engagement, surprise, confidence, goals) is encoded as a 40-variable binary optimization problem. Simulated annealing finds the lowest-energy (most coherent) configuration, and the gap between current and optimal state drives feedback.

**Architecture:**

| Component | Purpose |
|-----------|---------|
| `qubo_builder.py` | Reads Frank's state from DBs, builds linear penalties + quadratic implications (47 rules) |
| `annealer.py` | Simulated annealing with O(n) delta energy, multi-flip, 200 runs × 2000 steps |
| `coherence_monitor.py` | Polling daemon (5s), cumulative drift detection, energy history |
| `epq_bridge.py` | Translates coherence events → E-PQ personality events with exponential backoff |
| `api.py` | HTTP API: `/health`, `/status`, `/energy`, `/trend`, `/solve`, `/simulate` |

**40-Variable Schema (12 one-hot groups + 4 binaries):**

| Variables | Group | Encoding |
|-----------|-------|----------|
| 0-3 | Entity | therapist, mirror, atlas, muse |
| 4-6 | Intent | update, review, creative |
| 7-9 | Phase | idle, engaged, reflecting |
| 10-12 | Mode | meeting, project, focus |
| 13-14 | Mood | positive, negative |
| 15-29 | E-PQ (5×3) | precision/risk/empathy/autonomy/vigilance × low/mid/high |
| 30-32 | Task Load | none, moderate, heavy |
| 33-35 | Engagement | absent, recent, active |
| 36-39 | Binaries | surprise_high, confidence_high, goal_urgent, reflector_aligned |

**Integration Points:**
- **Consciousness**: Attention source #6 (`coherence_signal`) — triggers when epistemic gap > 2.0
- **Genesis**: Manifestation resonance factor #8 — queries `/simulate` for what-if coherence scoring
- **E-PQ**: Bridge fires `reflection_growth`/`reflection_vulnerability` events on improvement/degradation

---

### Safety Systems

#### A.S.R.S. — Autonomous Safety Recovery System v2.0

Multi-stage feature monitoring with automatic rollback.

**4 Protection Stages:**

| Stage | Duration | Check Interval | Confidence |
|-------|----------|---------------|------------|
| IMMEDIATE | 0-5 min | 10s | 0→10 |
| SHORT-TERM | 5 min-2h | 60s | 10→40 |
| LONG-TERM | 2-24h | 5 min | 40→80 |
| PERMANENT | >24h | — | 80→100 (STABLE) |

**Critical Thresholds:**
- Memory spike: >30% above baseline
- CPU spike: >95%
- Error rate critical: >10/min
- Memory leak: >5% increase/hour trend

**Emergency Response:**
- Single culprit identified → direct rollback
- Multiple suspects → mass rollback with one-by-one revalidation (oldest first)

---

#### Gaming Mode

Automatic resource optimization during Steam games.

**Detection:** Scans `/proc/*/cmdline` for game process patterns (no X11 probing — anti-cheat safe). Entry grace: 3 consecutive detections.

**Activation Sequence:**
1. **Stop network sentinel IMMEDIATELY** (<500ms, anti-cheat safety)
2. Stop Frank overlay (preserve state)
3. Mask + stop GPU LLM services (aicore-llama3-gpu, aicore-chat-llm) — Micro-LLM stays on CPU
4. Keep toolboxd running

**Exit:** Game process gone → unmask + restart all services + restore overlay

**Anti-cheat Safety:** Never scan: EasyAntiCheat, BattlEye, Vanguard

**Min gaming time:** 30s (prevents false exit during game loading)

---

### System Tools

#### `/tools/toolboxd.py` - System Introspection (:8096)

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

- Time window: 02:00-06:00 only
- 20 GB sandbox quota
- Max 5 deep-dives per day
- Gaming mode kill-switch

---

## Databases

### Overview (29 databases)

| Database | Purpose | Key Tables |
|----------|---------|------------|
| `titan.db` | Episodic memory + ego-construct | nodes, edges, events, claims, ego_state, sensation_mappings, affect_definitions, agency_assertions |
| `consciousness.db` | Consciousness state | workspace_state, mood_trajectory, reflections, predictions, experience_vectors, attention_log, perceptual_log, goals, feature_training, memory_consolidated |
| `world_experience.db` | Causal learning + E-PQ state | entities, causal_links, fingerprints, personality_state, extreme_state_log, identity_snapshots |
| `chat_memory.db` | Conversational memory | messages, message_embeddings, sessions, user_preferences, retrieval_metrics, messages_fts |
| `e_sir.db` | Self-improvement audit | audit_log, snapshots, genesis_tools, daily_stats |
| `system_bridge.db` | Hardware state | drivers, driver_observations |
| `therapist.db` | Dr. Hibbert entity | sessions, session_messages, frank_observations, topics, therapist_state |
| `atlas.db` | Atlas entity | sessions, session_messages, frank_observations, topics, atlas_state |
| `muse.db` | Echo entity | sessions, session_messages, frank_observations, topics, muse_state |
| `mirror.db` | Kairos entity | sessions, session_messages, frank_observations, topics, mirror_state |
| `invariants/invariants.db` | Physics enforcement | energy_ledger, entropy_history, convergence_checkpoints, core_kernel, quarantine, metrics_history, invariant_state |
| `invariants/titan_shadow.db` | Shadow reality (mirrors titan.db) | Same as titan.db |
| `invariants/titan_validator.db` | Reality validation | observations |
| `e_cpmm.db` | Core Performance Memory | edges, nodes |
| `akam_cache.db` | Knowledge cache | validated_claims, research_sessions |
| `frank.db` | Genesis patterns | genesis_patterns |
| `sovereign.db` | System sovereignty | actions, config_snapshots, daily_stats, system_inventory |
| `sandbox_awareness.db` | Sandbox state | core_edges, current_environment, sandbox_sessions, tool_registry |
| `e_wish.db` | Wish system | wishes, wish_history |
| `agent_state.db` | Agent states | agent_states, execution_log |
| `notes.db` | User notes | notes, notes_fts |
| `todos.db` | User todos | todos, todos_fts |
| `clipboard_history.db` | Clipboard | clipboard_entries |
| `fas_scavenger.db` | GitHub analysis | analyzed_repos, scout_history, extracted_features |
| `news_scanner.db` | News | (runtime) |
| `quantum_reflector.db` | Epistemic coherence optimization | energy_history, coherence_events |
| `aicore.sqlite` | Core events | events |

---

## Services

### All 28+ systemd User Services

| Service | Status | Description |
|---------|--------|-------------|
| `aicore-core` | Always on | Chat orchestrator (:8088) |
| `aicore-router` | Always on | Model routing (:8091) |
| `aicore-llama3-gpu` | Managed | DeepSeek-R1-Distill-Llama-8B RLM (:8101, GPU when idle) |
| `aicore-chat-llm` | Managed | Llama-3.1-8B-Instruct-abliterated (:8102, GPU when active) |
| `aicore-micro-llm` | Always on | Qwen2.5-3B-Instruct-abliterated (:8105, CPU background) |
| `llm-guard` | Always on | GPU swap manager + rogue LLM protection |
| `aicore-whisper-gpu` | Always on | Whisper STT (:8103) |
| `aicore-modeld` | Always on | Model lifecycle (:8090) |
| `aicore-toolboxd` | Always on | System tools (:8096) |
| `aicore-desktopd` | Always on | Desktop automation (:8092) |
| `aicore-webd` | Always on | Web search (:8093) |
| `aicore-ingestd` | Always on | Document ingestion (:8094) |
| `aicore-consciousness` | Always on | Consciousness stream daemon |
| `aicore-genesis` | Always on | Emergent self-improvement |
| `aicore-genesis-watchdog` | Always on | Ensures Genesis never dies |
| `aicore-invariants` | Always on | Physics engine |
| `aicore-asrs` | Always on | Safety recovery system |
| `aicore-entities` | Always on | Entity session dispatcher |
| `aicore-gaming-mode` | Always on | Gaming mode detection |
| `aicore-quantum-reflector` | Always on | Epistemic coherence (QUBO + SA, :8097) |
| `aura-headless` | Always on | Quantum GoL consciousness simulation (:8098) |
| `aura-analyzer` | Always on | 4-level hierarchical emergence recognition |
| `aicore-dream` | Always on | Dream daemon (sleep-analogue, 60 min/day) |
| `aicore-dream-watchdog` | Always on | Primary dream daemon monitor |
| `aicore-dream-watchdog-meta` | Always on | Meta-watchdog (monitors primary watchdog) |
| `aicore-fas` | Scheduled | Autonomous scavenger (02:00-06:00) |
| `aicore-therapist` | On-demand | Dr. Hibbert entity |
| `aicore-atlas` | On-demand | Atlas entity |
| `aicore-muse` | On-demand | Echo entity |
| `aicore-mirror` | On-demand | Kairos entity |

---

## Project Structure

```
Project-Frankenstein/
├── agentic/           # Multi-step task execution engine
├── assets/            # Screenshots and media
├── common/            # Shared utilities
├── config/            # Centralized path and GPU configuration
├── configs/           # Service configuration files
├── core/              # Chat orchestration service
├── database/          # Database utilities
├── desktopd/          # Desktop automation service (X11)
├── docs/              # Additional documentation
├── ext/               # Autonomous entities + Genesis daemon
├── gaming/            # Gaming mode detection and resource management
├── gateway/           # API gateway with auth
├── ingestd/           # Document ingestion service
├── intelligence/      # Intelligence and analysis modules
├── modeld/            # Model lifecycle service
├── personality/       # Ego-construct, E-PQ, entity personality constructs
├── router/            # LLM request routing, RLM token budget management
├── schemas/           # Data schemas
├── scripts/           # Utility and setup scripts
├── services/          # Background daemons (consciousness, genesis, invariants, ASRS, entities, quantum reflector, dream daemon)
├── skills/            # Plugin system (native + OpenClaw)
├── tests/             # Test suite
├── tools/             # System tools, toolboxd, titan memory
├── ui/
│   ├── overlay/       # Tkinter chat overlay (mixin architecture)
│   │   ├── mixins/    # Feature modules (chat, voice, agentic, calendar, ...)
│   │   ├── widgets/   # UI components (message bubbles, file actions)
│   │   ├── bsn/       # Layout system
│   │   └── services/  # HTTP helpers, vision, search
│   └── webui/         # Browser-based Web UI (FastAPI + WebSocket)
├── webd/              # Web search service
└── writer/            # AI-assisted document editor with code sandbox
```

---

## Emergent Behavior

### Consciousness Loop

```
               ┌──────────────┐
               │  Perception  │◄── 200ms hardware sampling
               │  (RPT)       │
               └──────┬───────┘
                      │ events
                      ▼
               ┌──────────────┐
               │  Attention   │◄── 7 competing sources
               │  (AST)       │──► Focus selection every 10s
               └──────┬───────┘
                      │ salience weights
                      ▼
        ┌─────────────────────────────┐
        │  Global Workspace (GWT)     │
        │  [INNER_WORLD] broadcast    │
        │  7 channels, budget-scaled  │
        └─────────────┬───────────────┘
                      │
           ┌──────────┼──────────┐
           ▼          ▼          ▼
    ┌──────────┐ ┌──────────┐ ┌──────────┐
    │  Mood    │ │Experience│ │ Goals    │
    │Recording │ │  Space   │ │Management│
    │  60s     │ │  64-dim  │ │  5 min   │
    └──────────┘ └──────────┘ └──────────┘
                      │
                      ▼
        ┌─────────────────────────────┐
        │  Idle Reflection            │
        │  (20min silence, 10 gates)  │
        │  2-pass meta-cognition      │
        └─────────────┬───────────────┘
                      │
           ┌──────────┼──────────┐
           ▼          ▼          ▼
    ┌──────────┐ ┌──────────┐ ┌──────────┐
    │  E-PQ    │ │  Titan   │ │  Goal    │
    │Personality││  Memory  │ │Extraction│
    │  Bridge  │ │  Ingest  │ │  (LLM)   │
    └──────────┘ └──────────┘ └──────────┘
```

### Genesis Self-Improvement Cycle

```
System observations (7 sensors)
        │
        ▼
┌──────────────────┐
│  Motivational    │
│  Field evolves   │──► Emotional state drives idea fitness
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Primordial Soup │
│  Ideas born,     │──► Compete, fuse, mutate, die
│  evolve          │
└────────┬─────────┘
         │ crystallize
         ▼
┌──────────────────┐
│  Manifestation   │
│  Gate            │──► Resonance + readiness + coherence check
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  F.A.S. Popup    │
│  User: Approve?  │──► Reject → prevent similar
└────────┬─────────┘    Defer  → return to soup (50% energy)
         │ approve
         ▼
┌──────────────────┐
│  Execute via     │
│  A.S.R.S.        │──► 4-stage safety monitoring
└──────────────────┘
```

### Physics Enforcement

```
Knowledge write (Titan, World-Exp, Consciousness)
        │
        ▼
┌──────────────────┐
│  Transaction     │
│  Hook (pre_write)│
└────────┬─────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌────────┐ ┌────────┐
│ Energy │ │Entropy │
│  ΔE=0? │ │ S≤Smax?│
└────┬───┘ └────┬───┘
     │          │
     └────┬─────┘
          │
     ┌────┴────┐
     │ PASS?   │
     ├─Yes─────├──► Write committed
     └─No──────└──► ROLLBACK (not Frank's choice — physics)
```

---

## API Reference

### Core API (`:8088`)
```http
POST /chat         - Main chat endpoint
POST /chat/stream  - Streaming chat
GET  /health       - Health check
GET  /status       - System status
```

### Router API (`:8091`)
```http
POST /route        - Route request to appropriate model
```

### Toolbox API (`:8096`)
```http
GET  /sys/summary  - System metrics summary
GET  /hw/detail    - Hardware detail
POST /desktop/*    - Desktop automation
```

### Quantum Reflector API (`:8097`)
```http
GET  /health    - Service health check
GET  /status    - Full monitor state (solve count, history, EPQ bridge stats)
GET  /energy    - Current vs optimal energy, gap, violations, optimal state
GET  /trend     - Energy trend analysis (improving/stable/degrading)
POST /solve     - Force immediate QUBO solve
POST /simulate  - What-if coherence scoring (accepts hypothesis JSON)
```

### E-PQ API
```python
from personality import get_personality_context, process_event

ctx = get_personality_context()
# {"temperament": "...", "mood": "...", "vectors": {...}}

result = process_event("positive_feedback", sentiment="positive")
# New: data parameter for genesis bridge
result = process_event("genesis_personality_boost",
                       data={"target_vector": "empathy", "amount": 0.1},
                       sentiment="positive")
```

### Consciousness API
```python
from services.consciousness_daemon import ConsciousnessDaemon

daemon = ConsciousnessDaemon(db_path)
ctx = daemon.get_workspace_context()
# {"workspace": "...", "mood": "...", "ego": "...",
#  "channel_weights": {"body": 0.4, "perception": 0.6, ...}}

daemon.record_chat(user_msg, frank_reply, analysis)
memories = daemon.get_relevant_memories(query, max_items=5)
surprise = daemon.get_surprise_level()  # 0-1
```

### Ego-Construct API
```python
from personality.ego_construct import get_ego_construct

ego = get_ego_construct()
ctx = ego.get_prompt_context()
# "I feel clear and steady. I sense ownership over my decisions."

ego.auto_train_from_state(
    system_metrics={"cpu": 45, "ram": 62, "cpu_temp": 55, "gpu_temp": 48},
    autonomous_actions=["chose to think autonomously during idle time"]
)
```

---

*Updated 2026-02-23 — v3.2 quantum reflector added. All processing is 100% local.*
