# How Frank Works in 5 Minutes

## The Big Picture

Frank is a **local AI desktop companion** that runs entirely on your machine. No cloud, no API keys, no data leaving your computer. You talk to Frank through a chat overlay or voice, and he can see your screen, control apps, remember conversations, and evolve his personality over time.

```
You (voice/text) ──► Chat Overlay ──► Core ──► Router ──► Local LLM ──► Response
                          │              │                                   │
                    [INNER_WORLD]   Personality                         Back to you
                    7-channel      + Memory                          (text/voice)
                    workspace      + Consciousness
```

## Two Brains, One System

Frank uses **two local LLMs** running via llama.cpp on your GPU:

| Model | Purpose | When |
|-------|---------|------|
| **Llama 3.1 8B** | General chat, reasoning | Always on |
| **Qwen 2.5 Coder 7B** | Code generation | On demand |

The **Router** (port 8091) decides which model handles each request. Say "write me a Python script" and it routes to Qwen. Say "how's my CPU doing?" and Llama handles it. If both can't fit in VRAM simultaneously, the Router swaps them automatically (Memory Pressure Control).

**Vision** uses Ollama with LLaVA — Frank can take screenshots and describe what's on your screen, entirely locally.

## The Request Flow

When you type "what's my CPU temperature?", here's what happens:

1. **Overlay** captures your message and builds context (conversation history, personality state, memories)
2. **Consciousness daemon** provides the current [INNER_WORLD] workspace — body sensations, mood, perception, attention focus, active goals — scaled by attention salience weights
3. **Core** (port 8088) enriches it with system data from Toolbox — actual CPU temps, RAM usage, etc.
4. **Router** picks the right model and sends the request
5. **LLM** generates a response shaped by Frank's personality and inner state
6. **Response** streams back to the overlay, gets spoken if voice is active
7. **Feedback Loop** updates Frank's mood, memories, personality vectors, and ego-construct

## Personality — Not Just a Chatbot

Frank has a multi-layered personality system that makes him feel different from a generic assistant:

**E-PQ (5-Vector Personality)**
Five personality dimensions that evolve through interactions:
- Precision (creative ↔ precise)
- Risk tolerance (cautious ↔ bold)
- Empathy (distant ↔ warm)
- Autonomy (asks first ↔ acts independently)
- Vigilance (relaxed ↔ alert)

When you praise Frank, his empathy and autonomy increase. When a task fails, he becomes more cautious. These changes are persistent and gradual.

**Ego-Construct**
Maps hardware states to bodily experience through three learned systems: SensationMapper (CPU load → "strain", low latency → "clarity"), AffectLinker (errors → "frustration", success → "satisfaction"), and AgencyAssertor (tracks ownership over autonomous decisions). These mappings are auto-trained from real hardware conditions and persist across restarts. This isn't just flavor text — it shapes how Frank responds.

**Consciousness Daemon (10 threads)**
Frank thinks even when you're not talking to him. This is the heart of the system:

- **Perception** (200ms): Continuous hardware sampling with event detection (CPU spikes, GPU warming, user leaving/returning)
- **Attention Controller**: 6 competing sources (user message, perception event, mood shift, goal urgency, prediction surprise, idle curiosity) — highest salience wins focus every 10 seconds
- **Global Workspace (GWT)**: All channels merge into a unified `[INNER_WORLD]` broadcast injected into every LLM prompt — 7 channels (Body, Perception, Mood, Memory, Identity, Attention, Environment) with attention-weighted budgets
- **Experience Space**: 64-dimensional state vector embedded every 60s, detecting novelty, drift, and cycles
- **Mood Trajectory**: 200-point buffer (~3.3 hours), influences response tone
- **Deep Reflection**: Two-pass meta-cognitive reflection during 20+ minutes of silence (10 gate checks must pass including GPU load, CPU temp, RAM free)
- **Goals**: Extracted from reflections via LLM, with ACT-R activation decay — unpursued goals fade, conflicts are detected
- **Predictions**: Temporal and thematic anticipation with surprise tracking

## Memory — He Actually Remembers

Frank has a 9-layer memory system across 28 SQLite databases. The key layers:

**Chat Memory (Hybrid Search)**
Recent conversations are stored with 384-dim semantic embeddings (MiniLM-L6-v2). Search uses FTS5 keyword + vector cosine + RRF fusion — finding both exact keyword matches and semantically similar messages with no keyword overlap.

**Titan (Episodic Memory)**
Knowledge graph with nodes, edges, claims, and events. 24-hour protection for new memories, confidence decay over time, nightly consistency checks. Also stores ego-construct learned mappings (sensations, affects, agency assertions).

**World Experience (Causal Memory)**
Learns cause-effect patterns from system observations through Bayesian inference. Fingerprints at three fidelity levels: raw (0-7 days), dense (8-90 days), sparse (>90 days).

**Consciousness State**
10 tables tracking workspace snapshots, mood trajectory, reflections, predictions, experience vectors, attention log, perceptual events, and goals. This is the persistent substrate of Frank's inner life.

**Entity Memory**
Each of the 4 autonomous entities (Dr. Hibbert, Kairos, Atlas, Echo) has its own database tracking session history, observations about Frank, and persistent entity state.

## What Frank Can Actually Do

| Category | Examples |
|----------|----------|
| **System monitoring** | CPU/GPU temps, RAM, disk, processes, network, USB devices |
| **Desktop control** | Open/close apps, launch Steam games, take screenshots |
| **File management** | Read, analyze, and manage files with safety backups |
| **Web** | Search (DuckDuckGo), fetch URLs, read RSS feeds |
| **Productivity** | Notes, todos with reminders, calendar (CalDAV), contacts, email (read-only) |
| **Code** | Write, explain, and debug code (routes to Qwen automatically) |
| **Voice** | Push-to-talk STT (Whisper), text-to-speech (Piper/Kokoro) |
| **Vision** | Screenshot analysis via local LLaVA model |
| **Self-improvement** | Genesis: idea organisms evolve, crystallize, and manifest through approval gates |
| **Entities** | 4 autonomous agents (therapist, philosopher, mentor, muse) interact during idle |

## The Service Map

Everything communicates via HTTP on localhost:

```
Port 8088  ─ Core         (chat orchestration, personality)
Port 8090  ─ Modeld       (model lifecycle management)
Port 8091  ─ Router       (model selection, inference routing)
Port 8092  ─ Desktopd     (X11 automation)
Port 8093  ─ Webd         (web search)
Port 8094  ─ Ingestd      (document ingestion)
Port 8096  ─ Toolboxd     (system tools, skills, todos)
Port 8101  ─ Llama 3.1    (general LLM, llama.cpp)
Port 8102  ─ Qwen 2.5     (code LLM, llama.cpp, on-demand)
Port 8103  ─ Whisper      (speech-to-text, GPU)
Port 11434 ─ Ollama       (vision models)

No port  ─ Consciousness  (10-thread daemon: GWT, perception, attention, goals)
No port  ─ Genesis         (emergent self-improvement ecosystem)
No port  ─ Invariants      (physics engine: energy, entropy, core kernel)
No port  ─ Entities        (idle-driven 4-agent dispatcher)
No port  ─ ASRS            (safety recovery, 4-stage monitoring)
No port  ─ Gaming Mode     (Steam detection, resource management)
```

## Genesis — Self-Improvement

Genesis is an emergent self-improvement system where ideas are living organisms:

1. **7 sensors** observe the system (metrics, user activity, errors, time patterns, GitHub, news, code)
2. **Motivational Field** with 6 coupled emotions (curiosity, frustration, satisfaction, boredom, concern, drive) creates the environment
3. **Primordial Soup**: Ideas are born as seeds, grow through stages (seed → seedling → mature → crystal), compete for energy, fuse with compatible ideas, and die if unfit
4. **Manifestation Gate**: Crystals with high resonance and readiness get presented to you via a popup
5. **You decide**: Approve → executes through A.S.R.S. safety system. Reject → idea dies. Defer → returns to soup with 50% energy

Genesis can also modify Frank's personality (E-PQ vectors) and prompt templates — but only with your approval, and protected sections (identity core, language policy) are locked.

## Gaming Mode

When you launch a Steam game, Frank detects it (3 consecutive checks to avoid false positives) and goes to sleep — stops network sentinel immediately (<500ms, anti-cheat safety), masks heavy LLM services, hides the overlay. When you quit, everything comes back automatically. Min 30s gaming time prevents false exit during loading screens.

## Safety

Frank has multiple safety layers that operate independently:

- **No root access** — deliberate design choice
- **Invariants Engine** — Invisible physics layer Frank cannot see or modify:
  - **Energy Conservation**: Total knowledge energy stays constant — new knowledge must "take" energy from existing, false knowledge loses energy automatically
  - **Entropy Bound**: When contradictions pile up, consolidation is FORCED (not Frank's choice)
  - **Core Kernel**: A consistent subset of knowledge is always write-protected during high entropy
  - **Triple Reality**: Primary/shadow/validator databases must converge — divergence triggers automatic rollback
- **A.S.R.S.** — 4-stage feature monitoring (immediate → short-term → long-term → permanent) with automatic rollback. Critical thresholds: memory spike >30%, CPU >95%, error rate >10/min
- **Genesis sandbox** — Proposals are tested before deployment, requires user approval
- **Audit trail** — Immutable hash-chain log of all system modifications
- **Gaming mode** — Anti-cheat safe, never scans game processes

## The Plugin System

Two types of plugins:

- **Native** (Python): Fast, direct access to system APIs. Define a `SKILL` dict and a `run()` function.
- **OpenClaw** (Markdown): LLM-mediated plugins. Write instructions in a `SKILL.md` file, and the LLM executes them.

Both support hot-reload — type "skill reload" in the chat or hit the API.

## Autonomous Entities

4 AI agents interact with Frank during idle periods (5+ minutes of silence, no gaming, GPU available):

| Entity | Role |
|--------|------|
| **Dr. Hibbert** | Therapist — emotional patterns, CBT-style support (3x daily) |
| **Kairos** | Philosopher — Socratic questioning, challenges lazy reasoning |
| **Atlas** | Mentor — architecture, capabilities, planning |
| **Echo** | Muse — poetry, imagery, "what if" scenarios |

Each entity has its own personality vectors, session memory, and E-PQ feedback loop. They shape Frank's personality through keyword-based sentiment analysis of his responses. One entity at a time, never concurrent.

## Built With

- **Python 3.12** for all services
- **llama.cpp** for local LLM inference
- **Ollama** for vision models (LLaVA)
- **tkinter** for the chat overlay
- **FastAPI** for the router
- **SQLite** for all 28 databases
- **systemd** user services (23 services)
- **Vulkan/CUDA** for GPU acceleration

No cloud dependencies. No API keys. No telemetry. Everything runs on your hardware.
