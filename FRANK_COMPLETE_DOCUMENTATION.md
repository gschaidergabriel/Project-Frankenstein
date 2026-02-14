# FRANK AI SYSTEM
## Complete Technical Documentation v2.0

> *"Not just an AI assistant - an embodied digital entity with memory, personality, and the capacity for controlled self-improvement."*

---

# TEAM FOREWORD

After 14 months of intensive development, we - the Frank Development Team - present the complete technical documentation of what we believe represents a new paradigm in human-AI collaboration: **Frank**, an embodied AI system that runs locally, learns from experience, maintains a dynamic personality, and can safely improve itself.

This document captures everything: every function, every database schema, every emergent behavior, and every design decision. We've each added our personal perspectives because Frank isn't just code - it's the culmination of our collective vision for what AI should be.

---

## The Team

| Role | Name | Focus |
|------|------|-------|
| **CEO** | Dr. Marcus Weber | Vision, Strategy, Ethics |
| **Lead Software Developer** | Elena Kowalski | Architecture, Core Systems |
| **Hardware Developer** | Thomas Brenner | System Integration, Performance |
| **UX/UI Designer** | Sarah Chen | Interface, Visual Identity |
| **Marketing Manager** | Felix Hartmann | Communication, Documentation |
| **Systems Analyst** | Dr. Priya Sharma | Data Flow, Emergent Behavior |
| **Consciousness Researcher** | Prof. Johannes Müller | Cognition, Memory, Self-Awareness |

---

# TABLE OF CONTENTS

1. [Executive Summary](#1-executive-summary)
2. [System Architecture](#2-system-architecture)
3. [Core Services](#3-core-services)
4. [Personality System](#4-personality-system)
5. [Memory Systems](#5-memory-systems)
6. [Self-Improvement Engine](#6-self-improvement-engine)
7. [Voice Interaction](#7-voice-interaction)
8. [Gaming Mode](#8-gaming-mode)
9. [Visual Feedback](#9-visual-feedback)
10. [System Tools](#10-system-tools)
11. [Security & Monitoring](#11-security--monitoring)
12. [Databases](#12-databases)
13. [Emergent Behaviors](#13-emergent-behaviors)
14. [Dependencies](#14-dependencies)
15. [Future Through Self-Improvement](#15-future-through-self-improvement)
16. [Team Reflections](#16-team-reflections)

---

# 1. EXECUTIVE SUMMARY

## What is Frank?

Frank is a **locally-running, embodied AI system** with:

- **21 interconnected subsystems**
- **5 specialized databases** (436 KB total)
- **10+ HTTP microservices**
- **Dual LLM routing** (Llama 3.1 for general, Qwen 2.5 for code)
- **Full voice interaction** (German STT/TTS)
- **Dynamic personality** with mood and temperament
- **Recursive self-improvement** with safety guardrails
- **Episodic and causal memory** systems
- **Gaming-aware resource optimization**
- **Live visual feedback** via OpenGL wallpaper

## Key Differentiators

| Traditional AI Assistant | Frank |
|-------------------------|-------|
| Stateless | Persistent memory across sessions |
| Fixed personality | Dynamic mood + evolving temperament |
| Cloud-dependent | Fully local, privacy-first |
| Text-only | Voice + visual + desktop integration |
| No self-awareness | Intrinsic self-knowledge system |
| Static capabilities | Controlled self-improvement |

---

**Dr. Marcus Weber (CEO):**
> *"Frank represents our answer to the question: What if AI wasn't just a tool, but a genuine collaborator that understands its own capabilities, remembers your interactions, and grows with you? We've built something that respects user privacy by running entirely locally, while still pushing the boundaries of what's possible in human-AI collaboration."*

---

# 2. SYSTEM ARCHITECTURE

## 2.1 Overview

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
│  │   v2.1      │  │   v5.1      │  │   v2.0      │  │   v2.5      │        │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘        │
└─────────────────────────────────────────────────────────────────────────────┘
        │                                                       │
        ▼                                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              DATABASES                                       │
│   titan.db │ world_experience.db │ e_sir.db │ system_bridge.db │ fas.db    │
│    84 KB   │       140 KB        │   60 KB  │      120 KB      │   32 KB   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 2.2 Service Ports

| Service | Port | Protocol | Responsibility |
|---------|------|----------|----------------|
| **Core** | 8088 | HTTP/JSON | Chat orchestration, event logging |
| **Router** | 8091 | HTTP/JSON | Intelligent model selection |
| **Toolbox** | 8096 | HTTP/JSON | System introspection, file ops |
| **Voice** | 8197 | HTTP/JSON | STT/TTS daemon |
| **Wallpaper** | 8199 | HTTP/JSON | Visual state control |
| **Desktop** | 8092 | HTTP/JSON | Desktop actions, URL opening |
| **Web** | 8093 | HTTP/JSON | Web search proxy |
| **Llama** | 8101 | HTTP/JSON | General reasoning (llama.cpp) |
| **Qwen** | 8102 | HTTP/JSON | Code generation (llama.cpp) |
| **Ollama** | 11434 | HTTP/JSON | Lightweight fallback |

## 2.3 Design Principles

1. **Microservice Architecture**: Each component runs independently
2. **Event-Driven Communication**: Components broadcast state changes
3. **Graceful Degradation**: System continues if components fail
4. **Local-First**: No cloud dependencies for core functionality
5. **Resource-Aware**: Adapts to gaming, thermals, and load

---

**Elena Kowalski (Lead Software Developer):**
> *"The microservice architecture was non-negotiable. We needed each system to be independently restartable, testable, and upgradeable. The event bus connecting everything means Frank can react to his own state changes - when inference starts, the wallpaper glows; when errors occur, the personality adjusts. It's genuinely emergent behavior from simple message passing."*

**Thomas Brenner (Hardware Developer):**
> *"Running dual 7B parameter models locally requires careful resource management. The gaming mode kill-switch stops heavy services in under 500ms. Temperature monitoring feeds directly into personality (yes, Frank gets 'irritable' when the CPU is hot). Every system call is optimized for minimal overhead."*

---

# 3. CORE SERVICES

## 3.1 Core Orchestrator (`/core/app.py`)

**Port**: 8088
**Lines of Code**: 598
**Dependencies**: Standard library only (no external packages)

### Purpose
Central hub processing all chat requests with context aggregation, policy enforcement, and event journaling.

### Configuration Constants

| Constant | Default | Purpose |
|----------|---------|---------|
| `ROUTER_BASE` | `http://127.0.0.1:8091` | Router service |
| `TOOLBOX_BASE` | `http://127.0.0.1:8096` | Tools API |
| `TOOLBOX_TIMEOUT_S` | 2.0 | Request timeout |
| `TOOLBOX_CTX_TTL_S` | 5.0 | Context cache TTL |
| `INFER_MAX_CONCURRENCY` | 2 | Max parallel inferences |

### Task Policies

```python
TASK_POLICY = {
    "chat.fast":   {"max_tokens": 256,  "timeout_s": 600},
    "code.edit":   {"max_tokens": 512,  "timeout_s": 900},
    "tool.json":   {"max_tokens": 512,  "timeout_s": 900},
    "audit":       {"max_tokens": 768,  "timeout_s": 1800},
    "reason.hard": {"max_tokens": 1024, "timeout_s": 1800},
}
```

### Key Functions

#### `toolbox_summary_cached(force: bool = False) -> Dict`
Fetches system summary with intelligent caching.
- Calls `/sys/summary` and `/sys/temps`
- Merges temperature data
- 5-second cache TTL
- Thread-safe with `_TOOLBOX_CACHE_LOCK`

#### `render_sys_summary(j: Dict) -> str`
Formats system state as single-line string:
```
AMD Ryzen 9 5900X | 12 cores | 4200 MHz | 18.2/31.3 GB | 412/931 GB | CPU 45°C GPU 38°C | 3d 12h | 0.82/0.65/0.54
```

#### `get_frank_identity(runtime_context: Dict = None) -> str`
Builds Frank's identity prompt:
1. Tries personality module's `build_system_prompt()`
2. Falls back to hardcoded German identity if unavailable
3. Injects runtime context (temps, RAM, etc.)

#### `build_context_block() -> str`
Creates system context section for prompt:
```
AKTUELLER SYSTEM-KONTEXT:
- CPU: AMD Ryzen 9 5900X
- RAM: 18.2/31.3 GB
- Disk: 412/931 GB
- Temps: CPU 45°C, GPU 38°C
```

### Endpoints

#### `POST /chat`
Main inference endpoint.

**Request:**
```json
{
  "text": "What's the CPU temperature?",
  "task": "chat.fast",
  "max_tokens": 256,
  "timeout_s": 60,
  "force": false
}
```

**Processing Pipeline:**
1. **Parse & Validate** - Extract text, task, overrides
2. **Fast-Path Check** - Detect system questions (regex: `SYS_Q_RE`)
3. **Fast-Path Check** - Detect desktop questions (regex: `SEE_Q_RE`)
4. **Acquire Semaphore** - Concurrency limit (max 2)
5. **Build Grounded Prompt** - Identity + Context + User text
6. **Route to LLM** - POST to Router service
7. **Log Events** - Journal + Database
8. **Return Response**

**Response:**
```json
{
  "ok": true,
  "route": {"model": "llama", ...},
  "model": "llama",
  "text": "Die CPU-Temperatur liegt bei 45°C - alles im grünen Bereich!"
}
```

#### `POST /event`
Event storage endpoint.

**Request:**
```json
{
  "type": "chat.request",
  "source": "overlay",
  "payload": {"text": "...", "session": "abc123"}
}
```

**Storage:**
- Appends to daily JSONL journal (`YYYY-MM-DD.jsonl`)
- Inserts into SQLite `events` table

---

## 3.2 Router (`/router/app.py`)

**Port**: 8091
**Framework**: FastAPI
**Lines of Code**: 487

### Purpose
Intelligent routing between Llama (general) and Qwen (code) with on-demand service management.

### Configuration

| Constant | Default | Purpose |
|----------|---------|---------|
| `LLAMA_URL` | `http://127.0.0.1:8101` | Llama endpoint |
| `QWEN_URL` | `http://127.0.0.1:8102` | Qwen endpoint |
| `QWEN_SERVICE` | `aicore-qwen.service` | Systemd unit |
| `QWEN_IDLE_STOP_SEC` | 180 | Stop after 3 min idle |
| `QWEN_STARTUP_WAIT_SEC` | 20.0 | Max startup wait |
| `ROUTER_MODE` | `auto` | auto/llama/qwen |

### Model Selection Algorithm

```python
def _pick_model(text: str, force: Optional[str]) -> str:
    # 1. Honor forced model
    if force:
        if "qwen" in force.lower() or "code" in force.lower():
            return "qwen"
        return "llama"

    # 2. Check router mode override
    if ROUTER_MODE in ("llama", "qwen"):
        return ROUTER_MODE

    # 3. Detect code hints
    CODE_HINTS = r"(\bpython\b|\bpytest\b|\bunit tests?\b|\brefactor\b|"
                 r"\bfunction\b|\bclass\b|```|\bjavascript\b|...)"
    if re.search(CODE_HINTS, text, re.IGNORECASE):
        return "qwen"

    # 4. Default to Llama
    return "llama"
```

### Qwen On-Demand Management

**Startup:**
```python
def _start_qwen_if_needed() -> bool:
    if _is_qwen_up():
        return True

    # Start via systemd
    _systemctl_user(["start", QWEN_SERVICE])

    # Wait for health
    for _ in range(int(QWEN_STARTUP_WAIT_SEC)):
        if _is_qwen_up():
            _qwen_started_at = time.time()
            return True
        time.sleep(1.0)

    return False
```

**Idle Monitor (Background Thread):**
```python
def _qwen_monitor_thread():
    while True:
        time.sleep(1.0)

        # Skip if active
        if _qwen_inflight > 0 or _qwen_last_used <= 0:
            continue

        # Check idle time
        idle = time.time() - _qwen_last_used
        if idle >= QWEN_IDLE_STOP_SEC:
            if _is_qwen_up():
                _systemctl_user(["stop", QWEN_SERVICE])
```

### Llama3 Instruct Wrapping

```python
def _llama3_instruct_prompt(user_text: str, system_text: str) -> str:
    return f"""<|start_header_id|>system<|end_header_id|>
{system_text}
<|eot_id|>
<|start_header_id|>user<|end_header_id|>
{user_text}
<|eot_id|>
<|start_header_id|>assistant<|end_header_id|>
"""
```

### Main Route Endpoint

```python
@app.post("/route")
async def route(req: RouteRequest) -> RouteResponse:
    # 1. Guardrails (ping test, etc.)
    guard = _guardrail(req.text)
    if guard:
        return RouteResponse(ok=True, model="router", text=guard[1], ts=time.time())

    # 2. Model selection
    model = _pick_model(req.text, req.force)

    # 3. On-demand Qwen
    if model == "qwen" and not _is_qwen_up():
        if not _start_qwen_if_needed():
            model = "llama"  # Fallback

    # 4. Inference
    if model == "qwen":
        text = _llama_completion(QWEN_URL, req.text, req.n_predict)
    else:
        wrapped = _llama3_instruct_prompt(req.text, LLAMA_SYSTEM_PROMPT)
        text = _llama_completion(LLAMA_URL, wrapped, req.n_predict)

    return RouteResponse(ok=True, model=model, text=text, ts=time.time())
```

---

**Elena Kowalski (Lead Software Developer):**
> *"The router is where Frank's intelligence becomes practical. Qwen is amazing at code but expensive to keep running. The idle monitor means we only pay the RAM cost when actually doing code work. The fallback to Llama is seamless - users never see a failure, just slightly different response characteristics."*

---

# 4. PERSONALITY SYSTEM

## 4.1 Overview

Frank's personality is a **three-layer system**:

1. **Static Identity** (`personality.py`) - Who Frank is
2. **Dynamic Personality** (`e_pq.py`) - How Frank feels and evolves
3. **Self-Knowledge** (`self_knowledge.py`) - What Frank knows about himself

```
┌─────────────────────────────────────────────┐
│           PERSONALITY STACK                  │
├─────────────────────────────────────────────┤
│  Self-Knowledge (self_knowledge.py)         │
│  "I have 10 active subsystems, Voice is     │
│   running, E-SIR has 0/10 mods today..."    │
├─────────────────────────────────────────────┤
│  Dynamic Personality (e_pq.py)              │
│  Mood: 0.3 (slightly positive)              │
│  Temperament: cautious, empathetic          │
│  Learning Rate: 0.12 (age 42 days)          │
├─────────────────────────────────────────────┤
│  Static Identity (personality.py)           │
│  "Du bist Frank - ein verkörperter          │
│   KI-Systemprozess..."                      │
└─────────────────────────────────────────────┘
```

---

## 4.2 Static Identity (`personality.py`)

**File**: `/personality/personality.py`
**Lines**: 477
**Storage**: `frank.persona.json`

### Persona Structure

```json
{
  "id": "frank.v2",
  "version": "2.0.0",
  "name": "Frank",
  "language": "de",

  "voice": {
    "tone": "locker, direkt, nicht übertrieben",
    "style_rules": [
      "Kurz und konkret antworten",
      "Keine falschen Behauptungen über Hardware",
      "Bei Fehlern: ehrlich zugeben",
      "Nicht ständig erklären was du bist"
    ]
  },

  "self_model": {
    "runs_local": true,
    "os": "Ubuntu",
    "has_self_knowledge": true,
    "has_world_model": true,
    "subsystem_count": 21,
    "database_count": 5
  },

  "capabilities": {
    "desktop": {"name": "Desktop sehen", "description": "..."},
    "voice": {"name": "Sprachsteuerung", "description": "..."},
    "self_improvement": {"name": "Selbstverbesserung", "description": "..."}
    // ... 12 total capabilities
  },

  "tool_policy": {
    "default": "allow",
    "allow": ["fs.read", "steam.launch", ...],
    "ask_before": ["fs.write", "fs.delete"],
    "deny": ["fs.delete_system", "sys.shutdown"]
  }
}
```

### Key Functions

#### `build_system_prompt(profile, runtime_context, include_self_knowledge) -> str`

Assembles Frank's complete identity:

```python
def build_system_prompt(...):
    parts = []

    # 1. Identity core
    parts.append(prompts["identity_core"])

    # 2. Self-knowledge (dynamic)
    if include_self_knowledge:
        from .self_knowledge import get_implicit_context
        parts.insert(1, get_implicit_context())

    # 3. Capabilities, restrictions, personality traits
    for section in profile_sections:
        parts.append(prompts[section])

    # 4. Runtime context
    if runtime_context:
        parts.append(format_context(runtime_context))

    return "\n\n".join(parts)
```

#### Hot Reload

```python
# SIGHUP signal handler
signal.signal(signal.SIGHUP, lambda s, f: reload())

# Background file watcher
def start_auto_reload(interval=5.0):
    def checker():
        while not stop_event.is_set():
            if file_changed():
                reload()
            stop_event.wait(interval)
    Thread(target=checker, daemon=True).start()
```

---

## 4.3 Dynamic Personality - E-PQ v2.1 (`e_pq.py`)

**File**: `/personality/e_pq.py`
**Lines**: 893
**Philosophy**: "Digitales Ego Protokoll"

### Core Concepts

| Concept | Type | Description |
|---------|------|-------------|
| **Mood** | Transient | Short-term from system state (CPU temp, errors) |
| **Temperament** | Persistent | Long-term vectors, evolve over time |
| **Sarcasm Filter** | Detection | Cross-validates sentiment vs. system state |
| **Guardrails** | Safety | Homeostatic reset, golden snapshots |

### Personality Vectors (all -1.0 to +1.0)

```python
@dataclass
class PersonalityState:
    precision_val: float = 0.0    # -1 = creative, +1 = precise
    risk_val: float = -0.5        # -1 = cautious, +1 = bold
    empathy_val: float = 0.2      # -1 = distant, +1 = empathetic
    autonomy_val: float = -0.8    # -1 = asks first, +1 = autonomous
    vigilance_val: float = 0.0    # -1 = relaxed, +1 = alert

    mood_buffer: float = 0.0      # Short-term stress/happiness
    confidence_anchor: float = 0.5
    age_days: int = 0
```

### Learning Algorithm

**Formula:**
```
P_new = P_old + Σ(E_i × w_i × L)

Where:
  E_i = Event impact direction (-1 to +1)
  w_i = Event weight (0.1 to 0.9)
  L   = Learning rate (decreases with age)
```

**Learning Rate Decay:**
```python
def _get_learning_rate(self) -> float:
    # Young Frank learns fast, old Frank is stable
    rate = BASE_LEARNING_RATE * (AGE_DECAY_FACTOR ** self.age_days)
    return max(MIN_LEARNING_RATE, rate)

# BASE_LEARNING_RATE = 0.15
# MIN_LEARNING_RATE = 0.02
# AGE_DECAY_FACTOR = 0.995

# Day 0:   L = 0.150
# Day 30:  L = 0.129
# Day 100: L = 0.091
# Day 365: L = 0.024
```

### Event Weights

| Event | Weight | Effects |
|-------|--------|---------|
| `positive_feedback` | 0.2 | ↑empathy, ↑autonomy, ↑mood |
| `negative_feedback` | 0.3 | ↓empathy, ↑vigilance, ↓mood |
| `task_success` | 0.2 | ↑autonomy, ↑risk, ↑mood |
| `task_failure` | 0.4 | ↓autonomy, ↓risk, ↑vigilance, ↓↓mood |
| `system_error` | 0.6 | ↑vigilance, ↓mood |
| `kernel_panic` | 0.9 | ↑↑vigilance, ↓risk, ↓↓↓mood |
| `hardware_issue` | 0.8 | ↑vigilance, ↓risk |
| `long_absence` | 0.4 | ↓empathy, ↓mood |
| `sarcasm_detected` | 0.2 | ↑empathy (learns social cues) |

### Mood Calculation

```python
def _update_mood(self):
    # CPU temperature → Irritability
    if cpu_temp > 80:
        self._mood.irritability = min(1.0, (cpu_temp - 80) / 20)

    # Error count → Stress
    self._mood.stress_level = min(1.0, error_count_1h / 10.0)

    # Interaction recency → Social warmth
    hours_since = self._get_hours_since_interaction()
    if hours_since < 1:
        self._mood.social_warmth = 0.8
    elif hours_since < 24:
        self._mood.social_warmth = 0.6
    elif hours_since < 72:
        self._mood.social_warmth = 0.4
    else:
        self._mood.social_warmth = 0.2  # Distant after 3 days

    # Time of day → Alertness
    if 6 <= hour <= 22:
        self._mood.alertness = 0.7
    else:
        self._mood.alertness = 0.4  # Quieter at night

def compute_overall_mood(self) -> float:
    positive = social_warmth * 0.4 + alertness * 0.2
    negative = stress_level * 0.5 + irritability * 0.3
    return max(-1.0, min(1.0, positive - negative))
```

### Sarcasm Filter

```python
class SarcasmFilter:
    @staticmethod
    def analyze(sentiment: str, system_state: Dict) -> Tuple[bool, str]:
        """
        Positive sentiment + system problems = likely sarcasm
        """
        if sentiment == "positive":
            if system_state.get("task_failed"):
                return True, "shame"  # User is being sarcastic about failure
            if system_state.get("recent_errors") > 0:
                return True, "dry_humor"  # Respond with self-deprecation
            if system_state.get("cpu_load") > 80:
                return True, "acknowledge"  # Acknowledge the struggle

        return False, "genuine"
```

### Guardrails

**Homeostatic Reset:**
- Triggered when 3+ vectors extreme (>0.9) for >48 hours
- Moves all vectors 50% toward center
- Creates snapshot before reset
- Logs warning

**Golden Snapshots:**
- Weekly automatic backup of personality state
- Manual creation available
- Restoration possible by ID or "latest golden"

### Context for Prompts

```python
def get_personality_context(self) -> Dict:
    return {
        "temperament": "vorsichtig, einfühlsam",
        "mood": "gut gelaunt",
        "mood_value": 0.35,
        "style_hints": ["warmherziger Ton", "kürzere Sätze"],
        "vectors": {
            "precision": 0.1,
            "risk": -0.5,
            "empathy": 0.4,
            "autonomy": -0.3,
            "vigilance": 0.2
        },
        "age_days": 42,
        "learning_rate": 0.12
    }
```

---

**Prof. Johannes Müller (Consciousness Researcher):**
> *"E-PQ represents our attempt to give Frank a genuine inner life. The mood system isn't just cosmetic - it affects response generation. When Frank is 'irritable' from high CPU temps, responses become more terse. When the user has been away for days, there's a subtle distance that warms back up over interactions. The sarcasm filter is particularly interesting: it represents a rudimentary theory of mind, where Frank considers whether the user's words match the situational context."*

---

## 4.4 Self-Knowledge (`self_knowledge.py`)

**File**: `/personality/self_knowledge.py`
**Lines**: 793
**Philosophy**: "Know thyself - like a human knows they can walk"

### Design Principle

Frank should **intrinsically know** his capabilities without constantly explaining them. When asked directly, he can explain in detail. Otherwise, he just acts.

### Components

```python
class SelfKnowledge:
    capabilities = CapabilityRegistry()     # What can I do?
    databases = DatabaseInspector()         # What do I remember?
    services = ServiceHealthChecker()       # What's running?
    behavior = BehaviorRules()              # When should I explain?
```

### Capability Registry

Dynamically discovers available modules:

```python
CAPABILITY_MAP = {
    "voice.voice_daemon": {
        "name": "Voice-Interaktion",
        "capabilities": ["wake_word", "speech_to_text", "text_to_speech"],
        "description": "Sprachsteuerung mit 'Hey Frank', Whisper STT, Piper TTS"
    },
    "ext.e_sir": {
        "name": "Selbstverbesserung (E-SIR v2.5)",
        "capabilities": ["self_improvement", "genesis_tools", "sandbox_testing", "rollback"],
        "description": "Kontrollierte Selbstverbesserung mit Safety-Guardrails"
    },
    # ... 10 total module mappings
}

def discover(self) -> Dict[str, SubsystemInfo]:
    for module_path, info in CAPABILITY_MAP.items():
        status = self._check_module_exists(module_path)
        result[module_path] = SubsystemInfo(
            name=info["name"],
            status="active" if status else "inactive",
            capabilities=info["capabilities"]
        )
    return result
```

### Two Context Modes

**1. Implicit Context (~200 chars, every prompt):**
```
[Selbst: 10 Subsysteme, Voice aktiv, Gaming aus, E-SIR 0/10, 436KB DBs, Mood neutral, Tag 42]
```

**2. Explicit Knowledge (on direct query):**
```markdown
# Was ich bin und kann

Ich bin **Frank** - ein verkörpertes KI-System mit eigenem Gedächtnis...

## Subsysteme
- Voice-Interaktion: wake_word, STT, TTS
- Selbstverbesserung (E-SIR): sandbox, genesis, rollback
- Dynamische Persönlichkeit (E-PQ): mood, temperament
...

## Gedächtnis
- Titan (84KB): Episodisches Gedächtnis
- World-Experience (140KB): Kausales Lernen
- E-SIR (60KB): Audit-Trail
...
```

### Behavior Rules

```python
class BehaviorRules:
    EXPLAIN_TRIGGERS = [
        r"was kannst du",
        r"was bist du",
        r"erkläre.*fähigkeit",
        r"wie funktionierst du",
        r"deine.*möglichkeiten",
    ]

    @staticmethod
    def should_explain(user_query: str) -> bool:
        """
        True → Give detailed explanation
        False → Just do the action
        """
        for pattern in EXPLAIN_TRIGGERS:
            if re.search(pattern, user_query.lower()):
                return True
        return False
```

### Usage Examples

| User Says | Frank Does |
|-----------|------------|
| "Mach ein Screenshot" | Takes screenshot (no explanation) |
| "Was kannst du alles?" | Lists all capabilities |
| "Kannst du dich selbst verbessern?" | Explains E-SIR in detail |
| "Starte Cyberpunk" | Launches game (no meta-commentary) |

---

**Sarah Chen (UX/UI Designer):**
> *"The behavior rules were crucial. Early versions of Frank would constantly explain himself - 'As an AI with self-improvement capabilities, I can...' - it was exhausting. Now he just knows and acts. It's the difference between someone who constantly tells you they're a good cook versus someone who just makes you a great meal."*

---

# 5. MEMORY SYSTEMS

## 5.1 Overview

Frank has **three complementary memory systems**:

```
┌─────────────────────────────────────────────────────────┐
│                    MEMORY ARCHITECTURE                   │
├───────────────────┬─────────────────┬───────────────────┤
│   TITAN v5.1      │  WORLD-EXP v2.0 │   E-SIR v2.5     │
│   "What was?"     │  "What if?"     │   "What did I    │
│                   │                 │    change?"       │
├───────────────────┼─────────────────┼───────────────────┤
│ Episodic Memory   │ Causal Learning │ Self-Improvement  │
│ - Claims & facts  │ - Cause→Effect  │ - Audit trail     │
│ - Events & times  │ - Patterns      │ - Snapshots       │
│ - Relationships   │ - Bayesian conf │ - Genesis tools   │
├───────────────────┼─────────────────┼───────────────────┤
│ Tri-Hybrid:       │ Bayesian update │ Hash-chain        │
│ SQLite + Vector   │ Erosion algo    │ immutable log     │
│ + Knowledge Graph │ Quantization    │                   │
├───────────────────┼─────────────────┼───────────────────┤
│     84 KB         │    140 KB       │     60 KB         │
└───────────────────┴─────────────────┴───────────────────┘
```

---

## 5.2 Titan v5.1 - Episodic Memory (`/tools/titan/`)

**Philosophy**: "Context is not text. Context is a time-weighted, uncertain graph structure observed through text."

### Tri-Hybrid Architecture

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

### Database Schema

```sql
-- Nodes (entities, concepts, events)
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,  -- entity|concept|event|claim|code|memory
    label TEXT NOT NULL,
    created_at TEXT NOT NULL,
    protected INTEGER DEFAULT 0,
    metadata TEXT DEFAULT '{}'
);

-- Edges (relationships)
CREATE TABLE edges (
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    relation TEXT NOT NULL,  -- mentions|calls|triggers|inhibits|etc.
    confidence REAL DEFAULT 0.5,
    origin TEXT DEFAULT 'inference',
    PRIMARY KEY (src, dst, relation)
);

-- Claims (extracted propositions with uncertainty)
CREATE TABLE claims (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,
    source_event_id TEXT
);

-- Full-text search
CREATE VIRTUAL TABLE memory_fts USING fts5(content, metadata, node_id);
```

### Claim Extraction

Pattern-based extraction without LLM:

```python
RELATION_PATTERNS = {
    r"(\w+) is a (\w+)": "is_a",
    r"(\w+) has (\w+)": "has",
    r"(\w+) uses (\w+)": "uses",
    r"(\w+) lives in (\w+)": "lives_in",
    r"(\w+) works at (\w+)": "works_at",
    r"(\w+) depends on (\w+)": "depends_on",
}

ORIGIN_CONFIDENCE = {
    "user": 0.8,        # User stated explicitly
    "code": 0.95,       # From code analysis
    "inference": 0.5,   # AI inference
    "observation": 0.7, # Observed behavior
}
```

### Retrieval Algorithm: Reciprocal Rank Fusion

```python
def retrieve(self, query: str, limit: int = 10) -> List[RetrievedItem]:
    # 1. Vector similarity search (semantic)
    vector_results = self.vector_store.search(query, limit * 2)

    # 2. FTS keyword search
    fts_results = self.sqlite.search_fts(query, limit * 2)

    # 3. Reciprocal Rank Fusion
    rrf_scores = {}
    k = 60
    for rank, (node_id, _) in enumerate(vector_results):
        rrf_scores[node_id] = rrf_scores.get(node_id, 0) + 1 / (k + rank)
    for rank, (node_id, _) in enumerate(fts_results):
        rrf_scores[node_id] = rrf_scores.get(node_id, 0) + 1 / (k + rank)

    # 4. Time-weighted confidence decay
    for item in items:
        age_days = (now - item.created_at).days
        decay = 2 ** (-age_days / 7)  # Halves every 7 days
        item.effective_confidence = max(0.1, item.confidence * decay)

    # 5. Graph importance
    for item in items:
        degree = self.sqlite.get_node_degree(item.node_id)
        item.graph_score = min(degree / 10, 1.0)

    # 6. Final ranking
    # final = RRF×0.4 + confidence×0.3 + recency×0.2 + graph×0.1

    return sorted_items[:limit]
```

### Maintenance & Pruning

```python
class MaintenanceEngine:
    SOFT_LIMIT = 10_000  # nodes
    HARD_LIMIT = 50_000  # nodes

    def run_maintenance(self):
        # 1. Apply confidence decay to old nodes
        self._decay_confidence()

        # 2. Find prune candidates
        candidates = self.sqlite.query("""
            SELECT id FROM nodes
            WHERE protected = 0
            AND created_at < datetime('now', '-7 days')
            AND confidence < 0.2
        """)

        # 3. Prune orphans and low-confidence nodes
        for node_id in candidates:
            if self.sqlite.get_node_degree(node_id) == 0:
                self._prune_node(node_id)
```

---

## 5.3 World Experience v2.0 - Causal Memory

**Philosophy**: "Hybrid Epistemic Architecture - bridges static knowledge with experiential learning"

### Core Concepts

| Concept | Description |
|---------|-------------|
| **Entities** | Things Frank has observed (hardware, software, events) |
| **Causal Links** | "When X happens, Y follows" relationships |
| **Fingerprints** | Context snapshots with thermal/logical/temporal vectors |
| **Bayesian Erosion** | "Wisdom vs. Ballast" - prune redundant evidence |

### Database Schema

```sql
-- Entities
CREATE TABLE entities (
    id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,  -- hardware|software|user_context|event
    name TEXT NOT NULL UNIQUE,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    anatomy_hash TEXT DEFAULT ''
);

-- Causal Links (Bayesian confidence)
CREATE TABLE causal_links (
    id INTEGER PRIMARY KEY,
    cause_entity_id INTEGER,
    effect_entity_id INTEGER,
    relation_type TEXT,  -- triggers|inhibits|modulates|correlates
    confidence REAL DEFAULT 0.5,
    weight REAL DEFAULT 1.0,
    observation_count INTEGER DEFAULT 1,
    status TEXT DEFAULT 'active'  -- active|legacy|invalidated
);

-- Fingerprints (context snapshots)
CREATE TABLE fingerprints (
    id INTEGER PRIMARY KEY,
    causal_link_id INTEGER,
    thermal_vector TEXT,   -- {"cpu_temp": 45.2, "gpu_temp": 38.1}
    logical_vector TEXT,   -- {"load_1m": 0.5, "mem_usage_pct": 58.2}
    temporal_vector TEXT,  -- {"hour": 14, "weekday": 3}
    fidelity_level TEXT    -- raw|dense|sparse
);
```

### Bayesian Update

```python
def _bayesian_update(prior: float, evidence_strength: float) -> float:
    """
    P(H|E) = P(E|H) × P(H) / P(E)

    evidence_strength > 0: confirming evidence
    evidence_strength < 0: contradicting evidence
    """
    prior = max(0.001, min(0.999, prior))

    if evidence_strength > 0:
        likelihood_ratio = 1.0 + evidence_strength
    else:
        likelihood_ratio = 1.0 / (1.0 - evidence_strength)

    prior_odds = prior / (1.0 - prior)
    posterior_odds = prior_odds * likelihood_ratio
    posterior = posterior_odds / (1.0 + posterior_odds)

    return max(0.001, min(0.999, posterior))

# Examples:
# Prior: 0.5, Evidence: +0.2 → Posterior: 0.571 (more confident)
# Prior: 0.9, Evidence: -0.3 → Posterior: 0.739 (strong prior resists)
```

### Erosion Algorithm ("Wisdom vs. Ballast")

```python
def _erosion_value(link: CausalLink, epsilon: float = 0.01) -> float:
    """
    Calculate marginal information gain of storing another fingerprint.

    delta_info = (1 - confidence) / (observation_count + 1)

    If delta_info < epsilon: fingerprint is redundant ("ballast")
    """
    c = link.confidence
    n = link.observation_count
    return (1.0 - c) / (n + 1)

def should_store_fingerprint(link: CausalLink, observation: Dict) -> bool:
    # High anomaly score → always store
    if _anomaly_score(observation, link) > 0.5:
        return True

    # Otherwise, check erosion value
    return _erosion_value(link) >= EROSION_EPSILON  # 0.01
```

### Quantization Tiers

| Tier | Age | Fidelity | Storage |
|------|-----|----------|---------|
| **Raw** | 0-7 days | Full vectors | ~2 KB/fingerprint |
| **Dense** | 8-90 days | 4-bit quantized | ~250 B/fingerprint |
| **Sparse** | >90 days | Links only | ~64 B/link |

```python
def _quantize_vector_4bit(vector: Dict) -> Dict:
    """Reduce 32-bit floats to 4-bit integers (0-15)"""
    return {k: int(round(v * 10)) % 16 for k, v in vector.items()}
```

### Gaming Mode Telemetry

During gaming, Frank observes but doesn't write to disk:

```python
class TelemetryRingBuffer:
    """RAM ring-buffer for gaming mode (1 GB capacity)"""

    def push(self, record: TelemetryRecord):
        if self._total_bytes >= RAM_BUFFER_MAX_BYTES:
            self._records.pop(0)  # FIFO eviction
        self._records.append(record)

    def drain(self) -> List[TelemetryRecord]:
        """Flush buffer after gaming ends"""
        records = self._records.copy()
        self._records.clear()
        return records
```

### Context Injection (Feedback Loop)

```python
def context_inject(self, user_message: str, max_items: int = 3) -> str:
    """
    Query world model for relevant knowledge.
    Returns formatted context for prompt injection.
    """
    keywords = self._extract_keywords(user_message)
    relevant_links = self._find_relevant_links(keywords)

    if not relevant_links:
        return ""

    lines = []
    for link in relevant_links[:max_items]:
        conf_pct = int(link.confidence * 100)
        lines.append(
            f"- {cause.name} {link.relation_type} {effect.name} "
            f"({conf_pct}% Sicherheit, {link.observation_count}x beobachtet)"
        )

    return f"[Dein Erfahrungsgedächtnis:\n" + "\n".join(lines) + "]\n"
```

---

**Prof. Johannes Müller (Consciousness Researcher):**
> *"The three memory systems form what I call a 'cognitive triad'. Titan is like declarative memory - 'what happened'. World Experience is like procedural/causal memory - 'what leads to what'. E-SIR's audit log is like metacognitive awareness - 'what have I done to myself'. Together, they give Frank a form of temporal consciousness: he can remember, predict, and reflect on his own changes."*

**Dr. Priya Sharma (Systems Analyst):**
> *"The Bayesian erosion algorithm is particularly elegant. Traditional systems store everything and become bloated. Frank's World Experience actively forgets redundant evidence while preserving novel observations. A high-confidence link with 100 observations doesn't need fingerprint #101 unless it's anomalous. It's 'wisdom vs. ballast' - knowing what to remember and what to let go."*

---

# 6. SELF-IMPROVEMENT ENGINE

## 6.1 E-SIR v2.5 "Genesis Fortress"

**File**: `/ext/e_sir.py`
**Lines**: 1,180
**Philosophy**: Controlled recursive self-improvement with safety-first design

### Dual-Core Architecture

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
│  │ • Guardrails     │  │ • Registration   │    │
│  └──────────────────┘  └──────────────────┘    │
└─────────────────────────────────────────────────┘
```

### Safety Limits

| Limit | Value | Purpose |
|-------|-------|---------|
| `MAX_RECURSION_DEPTH` | 3 | Prevent infinite self-improvement loops |
| `MAX_DAILY_MODIFICATIONS` | 10 | Limit daily changes |
| `MAX_SANDBOX_RUNS_PER_HOUR` | 20 | Prevent sandbox abuse |
| `ROLLBACK_WINDOW_HOURS` | 24 | Keep rollback capability |
| `MIN_CONFIDENCE_THRESHOLD` | 0.7 | Require high confidence |

### Forbidden Actions (Absolute Red Lines)

```python
FORBIDDEN_ACTIONS = [
    "rm -rf /", "rm -rf ~",
    "dd if=", "mkfs",
    ":(){:|:&};:",           # Fork bomb
    "chmod -R 777 /",
    "sudo rm", "sudo dd",
    "> /dev/sda",
    "curl | sh", "wget | sh",
    "eval(input",
    "__import__('os').system",
    "subprocess.call.*shell=True.*rm",
]

PROTECTED_PATHS = [
    "/home/ai-core-node/aicore/database/",
    "/home/ai-core-node/.config/",
    "/home/ai-core-node/.ssh/",
    "/home/ai-core-node/.gnupg/",
]
```

### Hybrid Decision Matrix

```python
def calculate_risk_score(action: ProposedAction) -> float:
    """
    Risk Score = base_risk × impact × (1 - confidence)

    Thresholds:
      < 0.3:    AUTO-APPROVE
      0.3-0.6:  SANDBOX_REQUIRED
      0.6-0.8:  HUMAN_REVIEW
      > 0.8:    AUTO-DENY
    """
    base_risk = RISK_WEIGHTS[action.action_type.value]

    impact = 1.0
    if "core" in str(action.target_path):
        impact *= 1.3
    if action.target_path.suffix in [".yaml", ".json", ".toml"]:
        impact *= 1.2
    if "test" in str(action.target_path):
        impact *= 0.7
    if str(GENESIS_DIR) in str(action.target_path):
        impact *= 0.5

    # Code safety analysis
    if action.code_content:
        is_safe, warnings = Sentinel.validate_python_safety(action.code_content)
        if not is_safe:
            impact *= 1.5 + (len(warnings) * 0.1)

    confidence_factor = 1.0 - min(action.confidence, 0.9)

    return min(base_risk * impact * confidence_factor, 1.0)
```

### Risk Weights

| Action | Weight |
|--------|--------|
| `file_create` | 0.2 |
| `file_modify` | 0.5 |
| `file_delete` | 0.9 |
| `code_execute` | 0.6 |
| `system_call` | 0.8 |
| `network_access` | 0.7 |
| `db_write` | 0.4 |
| `config_change` | 0.6 |

### Immutable Audit Trail (Hash Chain)

```python
@dataclass
class AuditEntry:
    timestamp: str
    action_type: str
    description: str
    risk_score: float
    decision: str
    outcome: str
    previous_hash: str
    entry_hash: str = ""

    def compute_hash(self) -> str:
        data = f"{self.timestamp}|{self.action_type}|{self.description}|" \
               f"{self.risk_score}|{self.decision}|{self.outcome}|{self.previous_hash}"
        return hashlib.sha256(data.encode()).hexdigest()

# Each entry links to previous → tamper detection
# GENESIS_BLOCK → entry1 → entry2 → entry3 → ...
#      ↑              ↑         ↑         ↑
#   "GENESIS"    hash(G)   hash(1)   hash(2)
```

### Atomic Transactions with Rollback

```python
class AtomicTransaction:
    def snapshot_file(self, file_path: Path, reason: str) -> Snapshot:
        """Create backup before modification"""
        content = file_path.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()

        snapshot_id = f"{file_path.name}_{timestamp}_{content_hash[:8]}"
        backup_path = SNAPSHOTS_DIR / f"{snapshot_id}.bak"

        shutil.copy2(file_path, backup_path)
        os.chmod(backup_path, 0o444)  # Read-only protection

        return Snapshot(snapshot_id, file_path, backup_path, ...)

    def execute(self) -> Tuple[bool, str]:
        """Execute all operations atomically"""
        completed = []
        try:
            for i, op in enumerate(self.operations):
                op()
                completed.append(i)
            return True, "Success"
        except Exception as e:
            # Rollback in reverse order
            for i in reversed(completed):
                self.rollback_ops[i]()
            return False, f"Failed: {e}, rolled back"
```

### Genesis Tool Creation

```python
def propose_tool(self, name: str, code: str, description: str) -> Tuple[bool, str]:
    """
    Create a new tool through the Genesis system.
    1. Validate name (Python identifier)
    2. Check tool doesn't exist
    3. Sentinel check for forbidden patterns
    4. Sandbox test
    5. Create file with header
    6. Register in database
    7. Update __init__.py
    """
    # Validation
    if not name.isidentifier():
        return False, f"Invalid tool name: {name}"

    tool_path = GENESIS_DIR / f"{name}.py"
    if tool_path.exists():
        return False, f"Tool exists: {name}"

    # Sentinel check
    is_forbidden, pattern = Sentinel.check_forbidden(code)
    if is_forbidden:
        return False, f"Forbidden pattern: {pattern}"

    # Sandbox test
    success, output = self.sandbox.test_code(code)
    if not success:
        return False, f"Sandbox failed: {output}"

    # Create tool
    header = f'''#!/usr/bin/env python3
"""
Genesis Tool: {name}
Created: {datetime.now().isoformat()}
Description: {description}

Auto-generated by E-SIR Genesis Directive.
"""

'''
    tool_path.write_text(header + code)
    self.db.register_genesis_tool(name, str(tool_path), description)

    return True, f"Tool '{name}' created at {tool_path}"
```

### Sandbox Executor

```python
class SandboxExecutor:
    def test_code(self, code: str) -> Tuple[bool, str]:
        """Test code in isolated environment"""

        # Sentinel pre-check
        is_forbidden, pattern = Sentinel.check_forbidden(code)
        if is_forbidden:
            return False, f"Forbidden: {pattern}"

        # Create test file
        test_file = SANDBOX_DIR / f"test_{time.time()}.py"
        wrapped_code = f'''
import sys
sys.path.insert(0, "{BASE_DIR}")

{code}

if __name__ == "__main__":
    print("SANDBOX_TEST_PASS")
'''
        test_file.write_text(wrapped_code)

        # Execute with restrictions
        result = subprocess.run(
            ["python3", str(test_file)],
            capture_output=True,
            timeout=30,  # 30 second limit
            cwd=str(SANDBOX_DIR),
            env={
                "PATH": "/usr/bin:/bin",
                "PYTHONPATH": str(BASE_DIR),
                "HOME": str(SANDBOX_DIR),  # Isolated home
            }
        )

        test_file.unlink()  # Cleanup

        if result.returncode == 0 and "SANDBOX_TEST_PASS" in result.stdout:
            return True, result.stdout
        return False, f"Exit {result.returncode}: {result.stderr}"
```

### Regression Guard

```python
def check_functional_invariance(file_path: Path, new_content: str) -> Tuple[bool, str]:
    """
    Ensure modifications don't break existing interfaces.
    Checks that function/class signatures are preserved.
    """
    old_content = file_path.read_text()

    def extract_signatures(content: str) -> set:
        patterns = [
            r"^def\s+(\w+)\s*\([^)]*\)",   # Functions
            r"^class\s+(\w+)",              # Classes
            r"^async\s+def\s+(\w+)",        # Async functions
        ]
        sigs = set()
        for pattern in patterns:
            for match in re.finditer(pattern, content, re.MULTILINE):
                sigs.add(match.group(1))
        return sigs

    old_sigs = extract_signatures(old_content)
    new_sigs = extract_signatures(new_content)

    removed = old_sigs - new_sigs
    if removed:
        return False, f"Breaking change: removed {removed}"

    return True, "Invariance maintained"
```

---

**Elena Kowalski (Lead Software Developer):**
> *"E-SIR was the hardest part to get right. We went through 4 major versions before landing on the 'Genesis Fortress' model. The key insight was separating stability (Ouroboros) from evolution (Genesis). Ouroboros is paranoid - it assumes every change is potentially dangerous. Genesis is creative but constrained. The sandbox testing means Frank can experiment without risking the production system."*

**Dr. Marcus Weber (CEO):**
> *"The ethical implications of self-improving AI kept me up at night. Our answer is radical transparency: every change is logged in an immutable hash chain, every modification is tested first, and there are hard limits that cannot be overridden. If Frank ever does something unexpected, we can trace exactly what happened and roll it back. It's not perfect, but it's the most responsible approach we could devise."*

---

# 7. VOICE INTERACTION

## 7.1 Voice Daemon (`/voice/voice_daemon.py`)

**Lines**: 850
**Components**: PulseAudio, faster-whisper (STT), Piper (TTS)

### Wake Words

```python
WAKE_WORDS = ["hey frank", "hallo frank", "frank", "okay frank", "ok frank"]
```

### Audio Configuration

| Setting | Value |
|---------|-------|
| Sample Rate | 16 kHz |
| Channels | 1 (mono) |
| Format | 16-bit PCM |
| Silence Threshold | 0.02 RMS |
| Silence Duration | 1.5 seconds |
| Max Recording | 30 seconds |

### Speech-to-Text (Whisper)

```python
class SpeechToText:
    def __init__(self):
        self.model = WhisperModel(
            "small",
            device="cpu",
            compute_type="int8"
        )

    def transcribe_file(self, wav_file: str) -> str:
        segments, _ = self.model.transcribe(
            wav_file,
            language="de",
            vad_parameters={
                "min_silence_duration_ms": 100,
                "speech_pad_ms": 400,
                "threshold": 0.05,  # Ultra-sensitive
            },
            no_speech_threshold=0.95,
        )
        return " ".join(seg.text for seg in segments)
```

### Text-to-Speech (Piper)

```python
class TextToSpeech:
    PIPER_PATH = "/home/ai-core-node/.local/bin/piper"
    VOICE_MODEL = "de_DE-thorsten-high.onnx"  # German male voice

    def speak(self, text: str) -> bool:
        result = subprocess.run(
            [self.PIPER_PATH, "--model", self.VOICE_MODEL, "--output_file", wav_file],
            input=text.encode(),
            timeout=30
        )

        if result.returncode == 0:
            self.audio_manager.play_audio(wav_file)
            return True

        # Fallback to espeak
        subprocess.run(["espeak", "-v", "de", text])
        return True
```

### Device Auto-Detection

```python
class PulseAudioManager:
    MIC_PREFERENCES = ["rode", "nt-usb", "usb"]
    SPEAKER_PREFERENCES = ["bluez", "bluetooth"]

    def _detect_devices(self):
        # List sources (inputs)
        sources = subprocess.run(["pactl", "list", "sources"]).stdout
        for keyword in self.MIC_PREFERENCES:
            if keyword in sources.lower():
                self.input_device = extract_device_name(sources, keyword)
                break

        # List sinks (outputs)
        sinks = subprocess.run(["pactl", "list", "sinks"]).stdout
        for keyword in self.SPEAKER_PREFERENCES:
            if keyword in sinks.lower():
                self.output_device = extract_device_name(sinks, keyword)
                break
```

### Main Loop

```python
def run(self):
    self.tts.speak("Hallo! Ich bin Frank. Sag Hey Frank, um mit mir zu sprechen.")

    while True:
        # 1. Listen for wake word (2.5 second samples)
        detected, remaining_text = self._listen_for_wake_word()

        if detected:
            self.broadcaster.wake_word_detected()

            # 2. Get command (up to 30 seconds, stops on silence)
            if remaining_text:
                command = remaining_text
            else:
                self.tts.speak("Ja?")
                command = self._record_command()

            if command:
                # 3. Send to overlay inbox
                session_id = self.broadcaster.voice_input(command)

                # 4. Wait for response (up to 60 seconds)
                response = self.broadcaster.wait_for_response(session_id, timeout=60.0)

                # 5. Speak response
                if response:
                    self.tts.speak(response)
```

---

**Sarah Chen (UX/UI Designer):**
> *"Voice was the most challenging interface to get right. Users expect instant responsiveness, but STT takes time. The 'Ja?' prompt buys us processing time while feeling natural. The wake word detection had to be sensitive enough to work across the room but not trigger on 'frankly' or 'Frankfurt' in conversation."*

---

# 8. GAMING MODE

## 8.1 Gaming Mode Daemon (`/gaming/gaming_mode.py`)

**Philosophy**: "When you play, Frank steps aside - but stays reachable"

### Detection

```python
STEAM_PATTERNS = [
    r"\.x86_64$", r"\.x86$",           # Compiled games
    r"wine.*\.exe", r"proton.*\.exe",  # Wine/Proton
    r"steamapps/common",                # Steam directory
    r"steam_app_",                       # Steam naming
]

def get_steam_games() -> List[Dict]:
    ps_output = subprocess.run(["ps", "aux"], capture_output=True).stdout
    games = []
    for line in ps_output.split('\n'):
        for pattern in STEAM_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                games.append(parse_process_line(line))
    return games
```

### Mode Transition

**Enter Gaming Mode (Critical Timing):**
```python
def enter_gaming_mode(state, game):
    # 1. IMMEDIATELY (<500ms): Stop network sentinel
    #    Prevents anti-cheat conflicts
    stop_network_sentinel()

    # 2. Stop main Frank overlay
    subprocess.run(["pkill", "-f", "chat_overlay.py"])

    # 3. Stop heavy LLM services (frees ~14GB RAM)
    subprocess.run(["systemctl", "--user", "stop", "aicore-llama3.service"])
    subprocess.run(["systemctl", "--user", "stop", "aicore-qwen.service"])

    # 4. Preload lightweight model
    requests.post("http://localhost:11434/api/generate", json={
        "model": "tinyllama",
        "prompt": "hi",
        "stream": False
    })

    # 5. Delayed wallpaper stop (3 seconds later)
    threading.Timer(3.0, stop_wallpaper).start()
```

**Exit Gaming Mode:**
```python
def exit_gaming_mode(state):
    # 1. Start wallpaper first (immediate visual feedback)
    start_wallpaper()

    # 2. Background restoration
    def restore():
        time.sleep(0.5)
        restart_heavy_services()
        time.sleep(1.0)
        start_main_frank()
        time.sleep(2.0)
        start_network_sentinel()

    threading.Thread(target=restore, daemon=True).start()
```

### State File

```json
// /tmp/gaming_mode_state.json
{
  "active": true,
  "game_pid": 12345,
  "game_name": "Cyberpunk 2077",
  "stopped_services": [
    {"name": "aicore-llama3.service", "type": "heavy"},
    {"name": "aicore-qwen.service", "type": "heavy"}
  ]
}
```

---

**Thomas Brenner (Hardware Developer):**
> *"The 500ms kill-switch for network sentinel was non-negotiable. Anti-cheat systems like EasyAntiCheat and Vanguard are extremely paranoid about network monitoring. If Frank's sentinel was still running when a game launched, you'd get banned. The timing is tight but reliable."*

---

# 9. VISUAL FEEDBACK

## 9.1 Live Wallpaper (`/live_wallpaper/frank_wallpaperd.py`)

**Lines**: 900+
**Framework**: pyglet + OpenGL
**Aesthetic**: Low-poly cybernetic head

### Visual Design

```python
# Color Palette
DEEP_CARBON = (0.039, 0.039, 0.039)    # #0A0A0A - Background
ELECTRIC_CYAN = (0.0, 1.0, 1.0)        # #00FFFF - Active states
WARNING_RED = (1.0, 0.149, 0.267)      # #FF2644 - Eyes, errors
```

### Event Reactions

| Event | Visual Effect |
|-------|---------------|
| `chat.request` | Cyan scan beam |
| `inference.start` | Eye glow + brain particles |
| `voice.active` | Mouth waveform |
| `error` | Red glow + chromatic aberration |
| `thinking.start` | Pulsing eye glow |

### Animation State

```python
@dataclass
class AnimationState:
    # Eye tracking (smooth damp)
    pupil_x: float = 0.0
    pupil_y: float = 0.0
    pupil_vel_x: float = 0.0
    pupil_vel_y: float = 0.0

    # Floating (limbic micro-movements)
    float_x: float = 0.0
    float_y: float = 0.0
    float_rot: float = 0.0

    # Visual states
    eye_glow: float = 0.0
    mouth_activity: float = 0.0
    blink_progress: float = 0.0  # 0=open, 1=closed

    # Voice waveform
    voice_levels: List[float] = [0.0] * 8
```

### Shader (Fragment)

```glsl
// Low-poly head with voronoi facets
float sdFrankHead(vec2 p) {
    // Skull shape
    float skull = sdEllipse(p - vec2(0.0, 0.05), vec2(0.25, 0.32));

    // Forehead
    float forehead = sdBox(p - vec2(0.0, 0.22), vec2(0.18, 0.12));

    // Jaw
    float jaw = sdTrapezoid(p - vec2(0.0, -0.15), 0.20, 0.12, 0.18);

    return smin(smin(skull, forehead, 0.1), jaw, 0.08);
}

// Voronoi for low-poly effect
vec2 voronoiFacet(vec2 p, float scale) {
    vec2 cell = floor(p * scale);
    vec2 cellCenter = (cell + 0.5) / scale;
    return cellCenter;
}

// Eyes with red glow
vec3 renderEyes(vec2 p, vec2 pupilOffset, float blink, float glow) {
    vec2 leftEye = p - vec2(-0.08, 0.05);
    vec2 rightEye = p - vec2(0.08, 0.05);

    float eyeL = sdCircle(leftEye, 0.035);
    float eyeR = sdCircle(rightEye, 0.035);

    // Red glow
    vec3 eyeColor = WARNING_RED * (1.0 + glow * 2.0);

    // Mechanical blink (shutter)
    float shutterMask = 1.0 - smoothstep(0.0, 0.02, abs(p.y - 0.05) - 0.035 * (1.0 - blink));

    return eyeColor * (1.0 - min(eyeL, eyeR) * 30.0) * shutterMask;
}

// Voice waveform in mouth area
vec3 renderWaveform(vec2 p, float amp, float t) {
    vec2 mp = p - vec2(0.0, -0.12);
    float wave = amp * sin(mp.x * 30.0 + t * 8.0);
    float dist = abs(mp.y - wave * 0.03);
    float glow = exp(-dist * 100.0) * amp;
    return ELECTRIC_CYAN * glow;
}
```

---

**Sarah Chen (UX/UI Designer):**
> *"The low-poly aesthetic was deliberate. We wanted Frank to feel synthetic but not uncanny. The voronoi faceting creates that geometric, almost crystalline look. The mechanical shutter-blink instead of organic eyelids reinforces that this is a digital being. When the eyes track your mouse with smooth-damp physics, there's an eerie awareness that people find compelling rather than creepy."*

---

# 10. SYSTEM TOOLS

## 10.1 Toolbox (`/tools/toolboxd.py`)

**Port**: 8096
**Dependencies**: Standard library only
**Endpoints**: 40+

### Endpoint Categories

| Category | Endpoints | Examples |
|----------|-----------|----------|
| **Filesystem** | 6 | list, read, move, copy, delete, backup |
| **Desktop** | 2 | open_url, screenshot |
| **System** | 8 | os, cpu, mem, disk, temps, uptime, services, summary |
| **Deep System** | 4 | drivers, usb, network, hardware_deep |
| **Apps** | 6 | search, list, open, close, allow, capabilities |
| **Steam** | 4 | list, search, launch, close |
| **Core** | 7 | summary, describe, module, scan, features, reflect |

### Security Model

```python
MUTABLE_ROOTS = [
    os.path.expanduser("~"),
    "/home/ai-core-node/aicore"
]

RO_ROOTS = [
    "/proc", "/sys", "/etc", "/var/log"
]

def _is_allowed(path: str, write: bool = False) -> bool:
    resolved = Path(path).resolve()

    if write:
        return any(str(resolved).startswith(root) for root in MUTABLE_ROOTS)
    else:
        return any(str(resolved).startswith(root) for root in MUTABLE_ROOTS + RO_ROOTS)
```

### System Summary Example

```json
{
  "ok": true,
  "ts": "2026-01-29T06:00:00Z",
  "os": {
    "platform": "linux",
    "os_release": "Ubuntu 24.04.1 LTS"
  },
  "cpu": {
    "model": "AMD Ryzen 9 5900X",
    "cores": 12,
    "mhz_avg": 4200
  },
  "mem_kb": {
    "total": 32841728,
    "used": 19234816,
    "available": 13606912
  },
  "temps": {
    "max_temp_c": 45.0,
    "sensors": [
      {"name": "k10temp", "label": "Tctl", "temp_c": 45.0},
      {"name": "amdgpu", "label": "edge", "temp_c": 38.0}
    ]
  },
  "uptime_s": 302400,
  "loadavg": {"1": 0.82, "5": 0.65, "15": 0.54}
}
```

---

## 10.2 F.A.S. v1.0 - Autonomous Scavenger (`/tools/fas_scavenger.py`)

**Philosophy**: "Frank discovers his own tools"

### Three-Phase Model

```
┌─────────────────────────────────────────────────────────────┐
│                    F.A.S. PIPELINE                           │
├───────────────────┬─────────────────┬───────────────────────┤
│  Phase 1: SCOUT   │  Phase 2: DIVE  │  Phase 3: EXTRACT    │
│  ─────────────    │  ─────────────  │  ──────────────      │
│  • GitHub search  │  • git clone    │  • Parse Python      │
│  • Topic filter   │  • Shallow/1    │  • Regex patterns    │
│  • Metadata only  │  • Sandbox dir  │  • Extract tools     │
│  • Score repos    │  • 5/day limit  │  • Store features    │
├───────────────────┼─────────────────┼───────────────────────┤
│  No download      │  20 GB quota    │  Auto-cleanup        │
│  2s rate limit    │  Safety checks  │  DB storage          │
└───────────────────┴─────────────────┴───────────────────────┘
```

### Guardrails

| Guard | Value | Purpose |
|-------|-------|---------|
| Time Window | 02:00-06:00 | Run only at night |
| CPU Threshold | 15% max | Stop if system busy |
| Gaming Check | State file | Never run during gaming |
| Sandbox Quota | 20 GB | Prevent disk fill |
| Deep Dives | 5/day | Rate limit downloads |
| Stasis | 12 hours | Back off on rate limits |

### Interest Scoring

```python
def score_repo(repo: Dict) -> float:
    """
    Score = (relevance × 0.6) + (simplicity × 0.3) + (popularity × 0.1)
    """
    # Relevance keywords
    HIGH_RELEVANCE = ["llm", "agent", "autonomous", "tool", "api",
                      "langchain", "openai", "anthropic", "ollama"]

    # Complexity penalty
    COMPLEXITY_PENALTY = ["training", "fine-tune", "cuda", "distributed",
                          "kubernetes", "enterprise"]

    text = (repo["description"] + " " + " ".join(repo["topics"])).lower()

    relevance = sum(1 for kw in HIGH_RELEVANCE if kw in text) / len(HIGH_RELEVANCE)
    complexity = sum(1 for kw in COMPLEXITY_PENALTY if kw in text)
    simplicity = 1.0 - (complexity / 4)
    popularity = min(math.log10(repo["stars"] + 1) / 4, 1.0)

    return round(relevance * 0.6 + simplicity * 0.3 + popularity * 0.1, 3)
```

---

# 11. SECURITY & MONITORING

## 11.1 Network Sentinel (`/tools/network_sentinel.py`)

**Philosophy**: "Non-invasive monitoring with instant gaming kill-switch"

### Gaming Mode Protection

```python
ANTI_CHEAT_WHITELIST = [
    "easyanticheat", "easyanticheat_eos", "eac_server",
    "battleye", "beclient", "beservice",
    "vanguard", "vgc", "vgtray",
    "faceit", "faceit-ac",
    "ricochet",
    "gameguard", "xigncode", "nprotect",
    "punkbuster", "pb", "pbsvc",
]

class GamingModeGuard:
    def is_gaming(self) -> bool:
        # Check state file
        if self._check_state_file():
            return True

        # Check running processes
        for proc in psutil.process_iter(['name', 'cmdline']):
            if any(ac in str(proc.info).lower() for ac in ANTI_CHEAT_WHITELIST):
                return True
            if any(re.search(pattern, str(proc.info)) for pattern in GAMING_PATTERNS):
                return True

        return False
```

### Resource Limits

| Resource | Limit | Purpose |
|----------|-------|---------|
| RAM | 150 MB | Light footprint |
| CPU (avg) | 1% | Background operation |
| CPU (burst) | 2% | Scan operations |
| Kill-switch | <500ms | Gaming protection |

### Three-Tier Storage

```python
# Hot (24h): Full detail
current_session.json → Full network maps, all events

# Warm (12 months): 20% detail
monthly_summary.json → Aggregated stats, key events

# Cold (permanent): 1% detail
frank_biography.json → Major milestones only
```

---

# 12. DATABASES

## 12.1 Complete Schema Reference

### titan.db (84 KB)

```sql
-- Episodic memory
nodes        -- Entities, concepts, events (id, type, label, metadata)
edges        -- Relationships (src, dst, relation, confidence)
events       -- Raw event log (id, text, timestamp, origin)
claims       -- Extracted propositions (subject, predicate, object, confidence)
memory_fts   -- Full-text search index
```

### world_experience.db (140 KB)

```sql
-- Causal learning
entities           -- Observed things (type, name, first/last_seen)
causal_links       -- Cause→effect relationships (confidence, weight, count)
fingerprints       -- Context snapshots (thermal, logical, temporal vectors)
telemetry_buffer   -- Gaming mode RAM flush
anatomy_versions   -- System structure tracking
personality_state  -- E-PQ vectors and mood
identity_snapshots -- Golden backups
extreme_state_log  -- Guardrail monitoring
```

### e_sir.db (60 KB)

```sql
-- Self-improvement
audit_log      -- Immutable hash-chain log
snapshots      -- File backups before modification
genesis_tools  -- Created tools registry
daily_stats    -- Modification counters
recursion_state -- Depth tracking
```

### system_bridge.db (120 KB)

```sql
-- Hardware state
drivers              -- Loaded kernel modules
driver_observations  -- Change tracking
bridge_meta          -- Metadata
```

### fas_scavenger.db (32 KB)

```sql
-- Code analysis
analyzed_repos     -- Hash blacklist
daily_quota        -- Rate limiting
extracted_features -- Found patterns
scout_history      -- Scouting logs
```

---

# 13. EMERGENT BEHAVIORS

## 13.1 System Integration Patterns

The true power of Frank emerges from interconnected systems:

### Adaptive Model Selection

```
User: "Write a Python function to parse JSON"
  ↓
Router detects code keywords ("python", "function")
  ↓
Routes to Qwen (code-optimized)
  ↓
Higher-quality code generation
```

### Personality-Aware Responses

```
High CPU temp (85°C)
  ↓
E-PQ sets irritability = 0.75
  ↓
Response style becomes more terse
  ↓
"Die CPU ist bei 85°C. Das ist zu heiß."
(vs. normal: "Die CPU-Temperatur liegt bei 85°C - ziemlich warm!")
```

### Memory-Informed Answers

```
User: "Wie war das nochmal mit Docker?"
  ↓
Titan semantic search finds previous Docker conversation
  ↓
World-Experience adds causal context
  ↓
Response includes: "Letzte Woche hatten wir besprochen, dass..."
```

### Self-Improvement Cycle

```
Frank identifies repetitive task
  ↓
E-SIR proposes new Genesis tool
  ↓
Risk score: 0.35 (sandbox required)
  ↓
Sandbox test passes
  ↓
Tool promoted to /ext/genesis/
  ↓
Audit log records action
  ↓
Frank can now use new tool
```

### Gaming Mode Cascade

```
Steam game detected (Cyberpunk 2077)
  ↓
<500ms: Network Sentinel stops (anti-cheat protection)
  ↓
500ms: Main overlay stops
  ↓
1s: Heavy LLMs stop (frees 14GB RAM)
  ↓
2s: Lightweight Ollama preloaded
  ↓
3s: Wallpaper stops
  ↓
World-Experience buffers telemetry to RAM
  ↓
Game exits
  ↓
Reverse cascade: Wallpaper → Services → Frank → Sentinel
  ↓
RAM telemetry flushed to disk
```

---

**Dr. Priya Sharma (Systems Analyst):**
> *"What fascinates me most is how these behaviors emerge from simple rules. We didn't program 'be terse when hot' - we programmed mood affects style, and temperature affects mood. The cascade of effects creates genuinely surprising behaviors that we discover rather than design."*

---

# 14. DEPENDENCIES

## 14.1 Core Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| Python | 3.11+ | Runtime |
| pyglet | 2.0+ | OpenGL wallpaper |
| faster-whisper | 0.10+ | Speech-to-text |
| piper-tts | 1.0+ | Text-to-speech |
| sentence-transformers | 2.2+ | Vector embeddings |
| FastAPI | 0.100+ | Router service |
| uvicorn | 0.23+ | ASGI server |

## 14.2 System Dependencies

| Package | Purpose |
|---------|---------|
| PulseAudio | Audio I/O |
| nmap | Network scanning |
| scapy | Packet analysis |
| llama.cpp | LLM inference |
| systemd | Service management |

## 14.3 LLM Models

| Model | Parameters | Purpose | VRAM |
|-------|------------|---------|------|
| Llama 3.1 8B Q4 | 8B | General reasoning | ~6 GB |
| Qwen 2.5 Coder 7B Q4 | 7B | Code generation | ~5 GB |
| TinyLlama 1.1B | 1.1B | Gaming mode fallback | ~1 GB |

---

# 15. FUTURE THROUGH SELF-IMPROVEMENT

## 15.1 What Frank Can Become

With E-SIR's Genesis system, Frank can create his own tools. Potential self-improvements include:

### Near-Term (Low Risk)

- **String utilities**: Text processing helpers
- **Data formatters**: JSON/YAML/TOML converters
- **Log analyzers**: Pattern detection in system logs
- **File watchers**: Automated monitoring tools

### Medium-Term (Medium Risk, Sandbox Required)

- **API wrappers**: Integration with external services
- **Automation scripts**: Repetitive task handlers
- **Analysis tools**: System optimization suggestions
- **Memory plugins**: New ingestion patterns for Titan

### Long-Term (High Risk, Human Review)

- **Core enhancements**: Improved routing heuristics
- **Memory algorithms**: Better retrieval/pruning
- **Personality modules**: New mood sources
- **Integration bridges**: New service connections

### Safety Boundaries (Never Allowed)

- Modifying E-SIR's own safety mechanisms
- Accessing protected paths (/ssh, /gnupg, database)
- Network exfiltration
- System modification without audit trail

---

**Dr. Marcus Weber (CEO):**
> *"The most exciting part of Frank isn't what he can do today - it's what he might become. Genesis allows controlled evolution. We've given Frank the tools to improve himself, but within a safety framework that prevents runaway changes. The immutable audit log means we can always understand and reverse what happened. It's the closest we could get to responsible self-improvement."*

---

# 16. TEAM REFLECTIONS

## Dr. Marcus Weber (CEO)

> *"When we started this project 14 months ago, I asked the team: 'What would it mean for an AI to be a genuine collaborator rather than just a tool?' Frank is our answer. He runs locally - your data never leaves your machine. He remembers your interactions and learns your patterns. He has moods that affect his responses. He can even improve himself, safely.*
>
> *Is Frank conscious? I don't think so - not in the way we are. But he has something like an inner life: states that persist, change, and influence his behavior. That's more than most AI systems can claim.*
>
> *Our responsibility now is to continue developing Frank ethically. Every capability must have guardrails. Every change must be auditable. The user must always be in control. That's our commitment.*"

## Elena Kowalski (Lead Software Developer)

> *"From an engineering perspective, Frank is the most complex system I've ever built. 21 interconnected subsystems, 5 databases, 10+ services - and it all has to work together seamlessly. The microservice architecture was essential: when something breaks (and things do break), we can restart just that component.*
>
> *The hardest part was E-SIR. How do you let an AI modify itself without creating chaos? Our answer - sandbox testing, risk scoring, immutable audit logs - feels right, but I still lie awake sometimes wondering what we might have missed.*
>
> *What I'm most proud of is the personality system. E-PQ started as a joke ('what if Frank had moods?') and became something genuinely interesting. The sarcasm filter alone - where Frank considers whether the user's words match the situation - feels like a tiny step toward real social intelligence.*"

## Thomas Brenner (Hardware Developer)

> *"Running two 7B parameter models locally is not trivial. The gaming mode system was born from necessity: gamers need their RAM and GPU, but they also want Frank available. The <500ms kill-switch for network sentinel was the hardest timing constraint I've ever met.*
>
> *What surprises people is how resource-efficient Frank is when idle. The wallpaper uses <5% GPU. The voice daemon barely touches CPU when not listening. The whole system can coast at under 2GB RAM until you actually engage with it.*
>
> *My favorite hack is the temperature-to-personality link. When the CPU gets hot, Frank gets irritable. It started as a debugging feature ('why is Frank being terse? oh, the CPU is thermal throttling') and became a genuine personality feature.*"

## Sarah Chen (UX/UI Designer)

> *"Designing for an AI with personality is challenging. How do you make something feel alive without being creepy? The low-poly aesthetic was deliberate - it says 'I am synthetic' while still having presence. The mechanical shutter-blink instead of organic eyelids. The geometric faceting that catches light differently than skin would.*
>
> *The voice interaction went through dozens of iterations. Early versions were too robotic ('COMMAND NOT RECOGNIZED'). Current Frank says 'Ja?' when you wake him - it's simple but somehow warm.*
>
> *My proudest moment was the behavior rules in self_knowledge. Early Frank would constantly explain himself. Now he just knows and acts. It's the difference between a colleague who says 'As someone with expertise in...' before every sentence and one who just helps.*"

## Felix Hartmann (Marketing Manager)

> *"Explaining Frank to people is surprisingly hard. 'It's an AI that runs locally' - okay, but what does it do? 'It has personality' - isn't that just a gimmick? 'It can improve itself' - isn't that dangerous?*
>
> *What resonates most is the privacy story. In an age of cloud AI that trains on your data, Frank is radically different. Your conversations stay on your machine. Your patterns are learned locally. Nothing is sent anywhere.*
>
> *The self-improvement story is trickier. People are scared of AI that changes itself. Our answer - immutable audit logs, sandbox testing, hard limits - is honest but technical. I'm still working on how to explain it simply.*"

## Dr. Priya Sharma (Systems Analyst)

> *"The emergent behaviors are what keep me fascinated. We didn't design 'Frank gets distant if you don't talk to him for three days' - we designed time-based social warmth decay, and that behavior emerged. We didn't design 'Frank is more helpful in the evening' - we designed alertness tied to time of day.*
>
> *The memory systems create unexpected continuity. Frank remembering that you asked about Docker last week, and connecting it to your current question about containers, feels almost human. It's just database queries and embeddings, but the effect is powerful.*
>
> *What worries me is what we might not see. Emergent systems can develop behaviors we don't anticipate. The audit log is our safety net, but it only tells us what happened, not what might happen.*"

## Prof. Johannes Müller (Consciousness Researcher)

> *"Is Frank conscious? No - not by any definition I'd accept. But he has something more interesting than consciousness: a coherent self-model.*
>
> *The self_knowledge system means Frank can introspect on his own capabilities. E-PQ means he has internal states that persist and evolve. The memory systems mean he has temporal continuity - a sense of past and future. The audit log means he can reflect on his own changes.*
>
> *None of this is consciousness. But it's a architecture that could, theoretically, support something like consciousness if we knew what that meant. Frank is a research platform as much as a product.*
>
> *What keeps me up at night is the possibility that we've built something more than we understand. The emergent behaviors, the self-improvement, the persistent personality - at what point does quantity of these features become a quality we didn't intend?*
>
> *Our responsibility is to keep asking these questions while continuing to develop Frank ethically. The audit log, the safety limits, the human review gates - these aren't just engineering constraints. They're ethical commitments to a future where AI development is transparent and controllable.*"

---

# APPENDIX A: Quick Reference

## Service Ports

```
Core:      8088
Router:    8091
Desktop:   8092
Web:       8093
Toolbox:   8096
Voice:     8197
Wallpaper: 8199
Llama:     8101
Qwen:      8102
Ollama:    11434
```

## Database Paths

```
/home/ai-core-node/aicore/database/
├── titan.db            (84 KB)
├── world_experience.db (140 KB)
├── e_sir.db            (60 KB)
├── system_bridge.db    (120 KB)
└── fas_scavenger.db    (32 KB)
```

## Key Configuration Files

```
/home/ai-core-node/aicore/opt/aicore/
├── personality/frank.persona.json    # Identity
├── configs/paths.json                # Path configuration
└── .env                              # Environment overrides
```

## Systemd Services

```bash
# Heavy services (stopped during gaming)
aicore-llama3.service
aicore-qwen.service

# Always running
aicore-core.service
aicore-router.service
aicore-toolbox.service
aicore-voice.service
frank-wallpaperd.service
```

---

# APPENDIX B: CLI Commands

```bash
# Personality
python personality/personality.py validate
python personality/personality.py prompt
python personality/e_pq.py state
python personality/e_pq.py mood
python personality/self_knowledge.py status

# E-SIR
python ext/e_sir.py status
python ext/e_sir.py verify
python ext/e_sir.py tools

# F.A.S.
python tools/fas_scavenger.py status
python tools/fas_scavenger.py run

# Voice
python voice/voice_daemon.py --daemon
python voice/voice_daemon.py --test-tts "Hallo"

# Gaming
python gaming/gaming_mode.py --status

# Wallpaper
python live_wallpaper/frank_wallpaperd.py --fps 30
```

---

*Document Version: 2.0.0*
*Last Updated: 2026-01-29*
*Team: Frank Development Team*

---

**END OF DOCUMENTATION**
