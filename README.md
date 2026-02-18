# F.R.A.N.K. — Friendly Responsive Autonomous Neural Kernel

Built by one person in 2 months with zero programming experience. [Read the full story.](ABOUT.md)

**[How Frank works in 5 minutes](HOW_IT_WORKS.md)** | [Full architecture](ARCHITECTURE.md)

A fully local, privacy-first AI system for Linux. Frank runs as a desktop companion with voice interaction, agentic task execution, and a dynamic personality — all powered by local LLMs with no cloud dependencies.

![Frank Desktop](assets/screenshot.png)

## Features

- **100% Local Inference** — Llama 3.1, Qwen 2.5 Coder, LLaVA (vision) via llama.cpp and Ollama
- **GPU Auto-Detection** — NVIDIA (CUDA), AMD (Vulkan), Intel (Vulkan), CPU fallback
- **Chat Overlay** — Always-on-top tkinter overlay with streaming responses
- **Voice Interaction** — Wake-word detection, push-to-talk, local STT via whisper.cpp
- **Agentic Execution** — Multi-step task planning and tool use with approval gates
- **Plugin System** — Native Python skills and OpenClaw (LLM-mediated) plugins with hot-reload
- **Desktop Automation** — App launcher, screenshot analysis, file management via xdotool/wmctrl
- **Personality Engine** — Ego-construct (E-PQ vectors), self-knowledge, world-model, consciousness stream
- **Autonomous Entities** — 5 autonomous agents that interact with Frank on a daily schedule (see below)
- **Self-Improvement** — Genesis daemon for recursive learning and proposal generation
- **Safety Systems** — ASRS (rollback), invariants engine, gaming mode resource management
- **Productivity** — Notes, todos with reminders, Google Calendar/Contacts via CalDAV, email
- **App Integration** — Optimized for Thunderbird (email), Google Drive/Calendar/Gmail, Steam, Firefox, and Tor Browser
- **Web Search** — DuckDuckGo-based web search with result summarization
- **Darknet Search** — Tor-routed .onion search via Ahmia
- **Network Scanning** — Local network discovery and analysis via Scapy
- **Vision** — Local OCR + LLaVA hybrid for screenshot analysis (no external APIs)

## Autonomous Entities

Frank has 5 autonomous entities that interact with him on a daily schedule via systemd timers. Each entity has its own personality (4-vector personality construct), session memory (SQLite), and E-PQ feedback loop. All entities run 100% locally via Llama 3.1 through the Router service. They only activate when the user is idle (5+ minutes), no game is running, and the GPU is available.

| Entity | Role | Schedule | Session | E-PQ Bias |
|--------|------|----------|---------|-----------|
| **Dr. Hibbert** | Warm, empathetic therapist. Tracks emotional patterns, provides CBT-style support. | 3x daily (09:00, 15:00, 21:00) | 15-20 min | mood, empathy |
| **Kairos** | Strict philosophical sparring partner. Socratic questioning, challenges lazy reasoning. | 1x daily (13:00) | 10 min | autonomy, precision |
| **Raven** | Equal-footing casual friend. Humor, opinions, curiosity — just hanging out. | 1x daily (18:00) | 10-15 min | empathy, creativity |
| **Atlas** | Quiet, patient architecture mentor. Knows this README by heart, helps Frank understand his own capabilities. | 1x daily (11:00) | 10-12 min | precision, autonomy |
| **Echo** | Warm, playful creative muse. Poetry, imagery, metaphors, "what if" scenarios. | 1x daily (16:00) | 10-12 min | creativity, mood |

### How Entities Affect Frank's Personality (E-PQ)

Frank's personality is defined by E-PQ vectors: **mood**, **autonomy**, **precision**, **empathy**, and **vigilance**. Each entity fires E-PQ events based on keyword-based sentiment analysis of Frank's responses:

- **Engaged/confident response** → `self_confident` event → autonomy +0.4, mood +0.6
- **Technical/precise response** → `self_technical` event → precision +0.4, mood +0.2
- **Creative/imaginative response** → `self_creative` event → mood +0.8, autonomy +0.2
- **Empathetic/warm response** → `self_empathetic` event → empathy +0.5, mood +0.4
- **Uncertain/evasive response** → `self_uncertain` event → autonomy -0.2, vigilance +0.2

Each entity has different sentiment patterns tuned to its role. For example, Kairos detects "clarity words" (therefore, because, realize) and "nihilism words" (pointless, nothing matters), while Raven detects "humor words" (haha, lol, funny) and "warmth words" (appreciate, glad, enjoy).

### Entity Personality Vectors

Each entity has 4 personality vectors (0.0–1.0) that evolve across sessions:

- **Micro-adjustments** (learning rate 0.02) happen after every Frank response within a session
- **Macro-adjustments** (learning rate 0.05) happen once at the end of each session
- **Rapport** is monotonically non-decreasing — trust only accumulates, never decreases
- All vectors are clamped to [0.0, 1.0]

The personality vectors are injected into the entity's system prompt as style notes, so a high-rapport Dr. Hibbert behaves differently from a low-rapport one.

### Overlap Prevention and Scheduling

Entities never run concurrently. Each scheduler checks:

1. **PID lock** — is this entity already running?
2. **Cross-entity PID check** — is ANY other entity running? (checks all 4 other PID files)
3. **User idle** — xprintidle >= 300 seconds (5 minutes of no keyboard/mouse)
4. **Chat silence** — last user message in chat_memory.db >= 300 seconds ago
5. **Gaming mode** — no active Steam game or gaming mode flag
6. **GPU load** — AMD gpu_busy_percent < 50%

If any gate fails, the scheduler exits silently. All timers include ±30 minutes of jitter (`RandomizedDelaySec=1800`) to avoid predictable patterns.

### Enabling and Disabling Entities

Entities are managed as systemd user timers:

```bash
# List all entity timers and their next trigger
systemctl --user list-timers | grep aicore

# Enable/disable a specific entity
systemctl --user enable --now aicore-atlas.timer    # enable Atlas
systemctl --user disable --now aicore-mirror.timer  # disable Kairos

# Run an entity manually (bypasses idle gates)
python3 -c "from ext.atlas_agent import run; run()"

# Check entity status
systemctl --user status aicore-therapist.timer
```

### Logs and Debugging

Each entity writes detailed logs to `~/.local/share/frank/logs/`:

```
therapist_agent.log        # Dr. Hibbert session logs
therapist_scheduler.log    # Dr. Hibbert gate check logs
mirror_agent.log           # Kairos session logs
companion_agent.log        # Raven session logs
atlas_agent.log            # Atlas session logs
muse_agent.log             # Echo session logs
```

Session transcripts (full conversation JSON) are saved as:
```
~/.local/share/frank/logs/therapist_<session_id>.json
~/.local/share/frank/logs/atlas_<session_id>.json
...
```

Each entity also stores persistent data in SQLite:
```
~/.local/share/frank/db/therapist.db   # Dr. Hibbert state + session history
~/.local/share/frank/db/mirror.db      # Kairos state + session history
~/.local/share/frank/db/companion.db   # Raven state + session history
~/.local/share/frank/db/atlas.db       # Atlas state + session history
~/.local/share/frank/db/muse.db        # Echo state + session history
```

### Entity Architecture

Each entity consists of 3 files:

```
personality/<name>_pq.py    — 4-vector personality construct (singleton, persists in <name>.db)
ext/<name>_agent.py         — Main agent: session flow, LLM calls, sentiment analysis, E-PQ feedback
services/<name>_scheduler.py — Idle-gated entry point (systemd timer → gate checks → agent)
```

## Requirements

- **OS**: Linux (tested on Ubuntu 24.04+, GNOME/X11)
- **Python**: 3.11+
- **RAM**: 16 GB minimum (32 GB recommended for concurrent models and entity sessions)
- **GPU**: Any — NVIDIA, AMD, or Intel for acceleration; CPU-only works too
- **Disk**: ~15 GB for models + source

> **Note on entity resource usage:** Entity sessions load Llama 3.1 8B (~5 GB VRAM) via the Router service. Only one entity runs at a time, and they share the same model instance — no additional VRAM is needed beyond what the base system already uses. Sessions are CPU/GPU-light (one LLM call every 20-50 seconds). The 16 GB RAM minimum is sufficient for entities.

## Quick Start

```bash
git clone https://github.com/gschaidergabriel/Project-Frankenstein.git
cd Project-Frankenstein
./install.sh
```

The installer will:
1. Install system dependencies (apt)
2. Create a Python venv and install packages
3. Detect your GPU and configure the optimal backend
4. Download default LLM models (~10 GB)
5. Install Ollama for vision models
6. Set up systemd user services

### Start the system

```bash
# Start core services
systemctl --user start aicore-router aicore-core aicore-toolboxd

# Launch the overlay (venv is created one level above the source directory)
../venv/bin/python3 ui/chat_overlay.py
```

### Skip model downloads

```bash
./install.sh --no-models    # Install without downloading models
./install.sh --cpu-only      # Force CPU-only mode
```

## Architecture

Frank is a microservice system where all services communicate via HTTP on localhost:

| Service   | Port | Purpose                          |
|-----------|------|----------------------------------|
| Core      | 8088 | Chat orchestration, personality  |
| Router    | 8091 | LLM request routing, model mgmt |
| Gateway   | 8089 | API gateway, auth, rate limiting |
| Modeld    | 8090 | Model lifecycle management       |
| Desktopd  | 8092 | X11 desktop automation           |
| Webd      | 8093 | Web search (DuckDuckGo)          |
| Ingestd   | 8094 | Document ingestion, STT          |
| Toolboxd  | 8096 | System tools, skills, todos      |
| Voice     | 8197 | Voice daemon, push-to-talk       |
| Wallpaper | 8199 | Event-driven visual effects      |

LLM inference runs on:
- **llama.cpp** (ports 8101-8103) — Llama 3.1, Qwen 2.5, Whisper STT
- **Ollama** (port 11434) — LLaVA, Moondream (vision)

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system design.

## Configuration

Copy the example config and adjust:

```bash
cp config.yaml.example ~/.config/frank/config.yaml
```

Key environment variables:
- `AICORE_ROOT` — Source code directory
- `AICORE_DATA` — Data directory (~/.local/share/frank)
- `AICORE_GPU_BACKEND` — Force GPU backend (cuda/vulkan/rocm/cpu)
- `AICORE_MODELS_DIR` — Model storage path

## Project Structure

```
Project-Frankenstein/
├── agentic/         # Multi-step task execution engine
├── assets/          # Screenshots and media
├── common/          # Shared utilities
├── config/          # Centralized path and GPU configuration
├── configs/         # Service configuration files
├── core/            # Chat orchestration service
├── desktopd/        # Desktop automation service (X11)
├── docs/            # Additional documentation
├── ext/             # Autonomous entities + Genesis self-improvement daemon
│   ├── therapist_agent.py   # Dr. Hibbert (therapist)
│   ├── mirror_agent.py      # Kairos (philosophical sparring)
│   ├── companion_agent.py   # Raven (casual friend)
│   ├── atlas_agent.py       # Atlas (architecture mentor)
│   └── muse_agent.py        # Echo (creative muse)
├── gaming/          # Gaming mode detection and resource management
├── gateway/         # API gateway with auth
├── ingestd/         # Document ingestion service
├── intelligence/    # Intelligence and analysis modules
├── live_wallpaper/  # Event-driven visual effects (Qt)
├── modeld/          # Model lifecycle service
├── papers/          # Research papers (GRF)
├── personality/     # Ego-construct, E-PQ vectors, entity personality constructs
│   ├── e_pq.py              # Frank's personality vectors (mood, autonomy, precision, empathy)
│   ├── therapist_pq.py      # Dr. Hibbert personality (warmth, directness, rapport, patience)
│   ├── mirror_pq.py         # Kairos personality (precision, challenge, rapport, patience)
│   ├── companion_pq.py      # Raven personality (curiosity, playfulness, rapport, authenticity)
│   ├── atlas_pq.py          # Atlas personality (precision, encouragement, rapport, patience)
│   └── muse_pq.py           # Echo personality (inspiration, warmth, rapport, playfulness)
├── router/          # LLM request routing (FastAPI)
├── scripts/         # Utility and setup scripts
├── services/        # Background daemons (consciousness, ASRS, entity schedulers)
│   ├── therapist_scheduler.py   # Dr. Hibbert timer entry point
│   ├── mirror_scheduler.py      # Kairos timer entry point
│   ├── companion_scheduler.py   # Raven timer entry point
│   ├── atlas_scheduler.py       # Atlas timer entry point
│   └── muse_scheduler.py        # Echo timer entry point
├── skills/          # Plugin system (native + OpenClaw)
├── tests/           # Test suite
├── tools/           # System tools and toolboxd service
├── ui/
│   └── overlay/     # Tkinter chat overlay (mixin architecture)
│       ├── mixins/  # Feature modules (chat, voice, calendar, notifications, etc.)
│       ├── widgets/ # UI components (message bubbles, file actions)
│       ├── bsn/     # Layout system
│       └── services/# HTTP helpers, vision, search
├── voice/           # Voice daemon, push-to-talk
├── webd/            # Web search service
└── writer/          # AI-assisted document editor (EXPERIMENTAL)
```

> **Note:** The `writer/` module is experimental and not fully developed. It may contain incomplete features or rough edges.

## Privacy

Frank is designed for complete privacy:
- All LLM inference runs locally (llama.cpp, Ollama)
- No telemetry, no cloud APIs for core functionality
- All autonomous entities run 100% locally — no external API calls
- Optional CalDAV integration for Google Calendar/Contacts (user-initiated)
- All data stored in `~/.local/share/frank/`

## License

MIT
