# How Frank Works in 5 Minutes

## The Big Picture

Frank is a **local AI desktop companion** that runs entirely on your machine. No cloud, no API keys, no data leaving your computer. You talk to Frank through a chat overlay or voice, and he can see your screen, control apps, remember conversations, and evolve his personality over time.

```
You (voice/text) ──► Chat Overlay ──► Core ──► Router ──► Local LLM ──► Response
                                        │                                   │
                                   Personality                         Back to you
                                   + Memory                          (text/voice)
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
2. **Core** (port 8088) enriches it with system data from Toolbox — actual CPU temps, RAM usage, etc.
3. **Router** picks the right model and sends the request
4. **LLM** generates a response shaped by Frank's personality
5. **Response** streams back to the overlay, gets spoken if voice is active
6. **Feedback Loop** updates Frank's mood, memories, and personality vectors

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
Maps hardware states to bodily experience. High CPU load feels like "exertion." Rising temperatures feel like "warmth." This isn't just flavor text — it shapes how Frank responds.

**Consciousness Daemon**
Frank thinks even when you're not talking to him. Idle thoughts, mood tracking, and self-reflection happen in the background and influence his next response.

## Memory — He Actually Remembers

**Titan (Episodic Memory)**
Stores conversations, facts, and relationships in a knowledge graph. When you mention something from last week, Frank can recall it through semantic search.

**World Experience (Causal Memory)**
Learns cause-effect patterns from system observations. "When CPU load spikes, the fan gets loud" — Frank figures this out on his own through Bayesian inference.

**Chat Memory**
Recent conversations are kept in SQLite for immediate context. The overlay builds smart context from recent + semantically relevant older messages.

## What Frank Can Actually Do

| Category | Examples |
|----------|----------|
| **System monitoring** | CPU/GPU temps, RAM, disk, processes, network, USB devices |
| **Desktop control** | Open/close apps, launch Steam games, take screenshots |
| **File management** | Read, analyze, and manage files with safety backups |
| **Web** | Search (DuckDuckGo), fetch URLs, read RSS feeds |
| **Productivity** | Notes, todos with reminders, calendar (CalDAV), contacts, email (read-only) |
| **Code** | Write, explain, and debug code (routes to Qwen automatically) |
| **Voice** | Wake word ("Hey Frank"), speech-to-text (Whisper), text-to-speech (Piper) |
| **Vision** | Screenshot analysis via local LLaVA model |
| **Self-improvement** | Genesis daemon proposes and tests new tools in a sandbox |

## The Service Map

Everything communicates via HTTP on localhost:

```
Port 8088  ─ Core         (chat orchestration, personality)
Port 8089  ─ Gateway      (API gateway, auth, rate limiting)
Port 8090  ─ Modeld       (model lifecycle management)
Port 8091  ─ Router       (model selection, inference routing)
Port 8092  ─ Desktopd     (X11 automation)
Port 8093  ─ Webd         (web search)
Port 8094  ─ Ingestd      (document ingestion, STT)
Port 8096  ─ Toolboxd     (system tools, skills, todos)
Port 8197  ─ Voice        (STT/TTS daemon)
Port 8199  ─ Wallpaper    (live visualization events)
Port 8101  ─ Llama 3.1    (general LLM, llama.cpp)
Port 8102  ─ Qwen 2.5     (code LLM, llama.cpp)
Port 11434 ─ Ollama       (vision models)
```

## Gaming Mode

When you launch a game, Frank detects it and goes to sleep — stops heavy LLM services, hides the overlay, buffers telemetry. When you quit, everything comes back automatically. He never interferes with anti-cheat systems.

## Safety

- **No root access** — deliberate design choice
- **Package install limits** — max 5 per day, 37 protected system packages
- **Self-improvement sandbox** — Genesis proposals are tested before deployment
- **Audit trail** — immutable hash-chain log of all system modifications
- **ASRS rollback** — automatic snapshots before risky changes

## The Plugin System

Two types of plugins:

- **Native** (Python): Fast, direct access to system APIs. Define a `SKILL` dict and a `run()` function.
- **OpenClaw** (Markdown): LLM-mediated plugins. Write instructions in a `SKILL.md` file, and the LLM executes them.

Both support hot-reload — type "skill reload" in the chat or hit the API.

## Built With

- **Python 3.11+** for all services
- **llama.cpp** for local LLM inference
- **Ollama** for vision models (LLaVA)
- **tkinter** for the chat overlay
- **FastAPI** for the router
- **SQLite** for all databases
- **systemd** user services for process management
- **Vulkan/CUDA** for GPU acceleration

No cloud dependencies. No API keys. No telemetry. Everything runs on your hardware.
