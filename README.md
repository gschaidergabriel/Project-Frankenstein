# AI-Core / Frank

A fully local, privacy-first AI system for Linux. Frank runs as a desktop companion with voice interaction, agentic task execution, and a dynamic personality — all powered by local LLMs with no cloud dependencies.

## Features

- **100% Local Inference** — Llama 3.1, Qwen 2.5 Coder, LLaVA (vision) via llama.cpp and Ollama
- **GPU Auto-Detection** — NVIDIA (CUDA), AMD (Vulkan), Intel (Vulkan), CPU fallback
- **Chat Overlay** — Always-on-top tkinter overlay with streaming responses
- **Voice Interaction** — Wake-word detection, push-to-talk, local STT via whisper.cpp
- **Agentic Execution** — Multi-step task planning and tool use with approval gates
- **Plugin System** — Native Python skills and OpenClaw (LLM-mediated) plugins with hot-reload
- **Desktop Automation** — App launcher, screenshot analysis, file management via xdotool/wmctrl
- **Personality Engine** — Ego-construct, self-knowledge, world-model, consciousness stream
- **Self-Improvement** — Genesis daemon for recursive learning and proposal generation
- **Safety Systems** — ASRS (rollback), invariants engine, gaming mode resource management
- **Productivity** — Notes, todos with reminders, Google Calendar/Contacts via CalDAV, email
- **Vision** — Local OCR + LLaVA hybrid for screenshot analysis (no external APIs)

## Requirements

- **OS**: Linux (tested on Ubuntu 24.04+, GNOME/X11)
- **Python**: 3.11+
- **RAM**: 16 GB minimum (32 GB recommended for concurrent models)
- **GPU**: Any — NVIDIA, AMD, or Intel for acceleration; CPU-only works too
- **Disk**: ~15 GB for models + source

## Quick Start

```bash
git clone https://github.com/your-username/aicore.git
cd aicore/opt/aicore
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

# Launch the overlay
~/.local/share/frank/../venv/bin/python3 ui/chat_overlay.py
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
opt/aicore/
├── config/          # Centralized path and GPU configuration
├── core/            # Chat orchestration service
├── router/          # LLM request routing (FastAPI)
├── gateway/         # API gateway with auth
├── tools/           # System tools and toolboxd service
├── services/        # Background daemons (genesis, consciousness, ASRS)
├── personality/     # Ego-construct, self-knowledge, world-model
├── ui/
│   └── overlay/     # Tkinter chat overlay (mixin architecture)
│       ├── mixins/  # Feature modules (chat, voice, calendar, etc.)
│       ├── widgets/ # UI components (message bubbles, file actions)
│       ├── bsn/     # Layout system
│       └── services/# HTTP helpers, vision, search
├── agentic/         # Multi-step task execution engine
├── skills/          # Plugin system (native + OpenClaw)
├── voice/           # Voice daemon, push-to-talk
├── live_wallpaper/  # Event-driven visual effects
├── ingestd/         # Document ingestion service
├── webd/            # Web search service
├── desktopd/        # Desktop automation service
└── modeld/          # Model lifecycle service
```

## Privacy

Frank is designed for complete privacy:
- All LLM inference runs locally (llama.cpp, Ollama)
- No telemetry, no cloud APIs for core functionality
- Optional CalDAV integration for Google Calendar/Contacts (user-initiated)
- All data stored in `~/.local/share/frank/`

## License

MIT
