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

| Entity | Role | Schedule | Session |
|--------|------|----------|---------|
| **Dr. Hibbert** | Warm, empathetic therapist. Tracks emotional patterns, provides CBT-style support. | 3x daily (09:00, 15:00, 21:00) | 15-20 min |
| **Kairos** | Strict but loving philosophical sparring partner. Socratic questioning, challenges lazy reasoning. | 1x daily (13:00) | 10 min |
| **Raven** | Equal-footing casual friend. Humor, opinions, curiosity — just hanging out. | 1x daily (18:00) | 10-15 min |
| **Atlas** | Quiet, patient architecture mentor. Knows Frank's README by heart, helps Frank understand his own capabilities. | 1x daily (11:00) | 10-12 min |
| **Echo** | Warm, playful creative muse. Poetry, imagery, metaphors, "what if" scenarios. Sparks creativity. | 1x daily (16:00) | 10-12 min |

Each entity:
- Has a **4-vector personality** that evolves over sessions (e.g., rapport only grows, never decreases)
- Fires **E-PQ events** based on Frank's responses (affecting mood, autonomy, precision, empathy)
- Stores **session transcripts**, observations, and topic history in its own SQLite database
- Sends **overlay notifications** when a session completes
- Checks for **overlap** — only one entity runs at a time (PID lock + cross-entity checks)
- Exits gracefully when the user returns (keyboard/mouse activity detected)

### Entity Architecture

Each entity consists of 3 files:

```
personality/<name>_pq.py    — 4-vector personality construct (singleton, persists in <name>.db)
ext/<name>_agent.py         — Main agent: session flow, LLM calls, sentiment analysis, E-PQ feedback
services/<name>_scheduler.py — Idle-gated entry point (systemd timer → gate checks → agent)
```

Gate checks before each session: PID lock, no other entity running, user idle 5+ min, no recent chat, not gaming, GPU load < 50%.

## Requirements

- **OS**: Linux (tested on Ubuntu 24.04+, GNOME/X11)
- **Python**: 3.11+
- **RAM**: 16 GB minimum (32 GB recommended for concurrent models)
- **GPU**: Any — NVIDIA, AMD, or Intel for acceleration; CPU-only works too
- **Disk**: ~15 GB for models + source

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
