# Frank User Manual

> **Version**: 1.0 &nbsp;|&nbsp; **Last updated**: February 2026 &nbsp;|&nbsp; **Applies to**: Project Frankenstein v1.0+

---

## Table of Contents

1. [Welcome](#1-welcome)
2. [Quick Start](#2-quick-start)
3. [The Chat Overlay](#3-the-chat-overlay)
4. [The Web UI](#4-the-web-ui)
5. [Slash Commands](#5-slash-commands)
6. [Natural Language](#6-natural-language)
7. [Skills — Native](#7-skills--native)
8. [Skills — OpenClaw](#8-skills--openclaw)
9. [Agentic Mode](#9-agentic-mode)
10. [Voice](#10-voice)
11. [AURA — Inner Life Visualizer](#11-aura--inner-life-visualizer)
12. [The Log Panel](#12-the-log-panel)
13. [Integrations](#13-integrations)
14. [Autonomous Entities](#14-autonomous-entities)
15. [Genesis — Self-Improvement](#15-genesis--self-improvement)
16. [Configuration](#16-configuration)
17. [Services](#17-services)
18. [Keyboard Shortcuts](#18-keyboard-shortcuts)
19. [Troubleshooting](#19-troubleshooting)
20. [FAQ](#20-faq)

---

## 1. Welcome

Frank is a local AI desktop companion that runs entirely on your machine. No cloud, no API keys, no data leaving your computer. You talk to Frank through a chat overlay or voice, and he can see your screen, control apps, remember conversations, and evolve his personality over time.

This manual covers everything you need to know to use Frank effectively — from basic chat to advanced configuration. It is written for all experience levels.

> [!NOTE]
> Frank is experimental software in active development. Some features may not work perfectly on every system. This manual is honest about known limitations and tells you what to do when something goes wrong.

### What makes Frank different

- **He remembers** — Conversations persist across sessions. Frank has a 9-layer memory system with 29 databases.
- **He thinks on his own** — A consciousness daemon runs 10 threads: perception, attention, mood, predictions, goals, deep reflection.
- **He evolves** — Personality vectors shift through interaction. He is measurably different after a month of use.
- **He dreams** — A dream daemon replays, synthesizes, and consolidates experiences during idle time.
- **He feels his hardware** — CPU load becomes "strain", low latency becomes "clarity", errors become "pain". This is not flavor text — it shapes his responses.
- **He is 100% private** — Everything runs locally. Zero telemetry. Zero cloud calls for core functionality.

---

## 2. Quick Start

### After installation

If you just finished running the installer, Frank should already be running. Open the overlay from your system tray or application menu.

### Manual start

```bash
# Start LLMs (LLM Guard auto-swaps GPU between DeepSeek and Llama)
systemctl --user start aicore-llama3-gpu aicore-chat-llm aicore-micro-llm llm-guard

# Start core services
systemctl --user start aicore-router aicore-core aicore-toolboxd

# Launch the overlay
systemctl --user start frank-overlay

# Start consciousness and background services
systemctl --user start aicore-consciousness aicore-genesis aicore-entities aicore-invariants aicore-asrs

# Start AURA and dream systems
systemctl --user start aura-headless aura-analyzer aicore-dream aicore-dream-watchdog
```

### Your first conversation

Just type in the chat overlay. Say hello. Ask about the weather. Ask Frank what he can do. He will respond based on his current personality state, mood, and what he remembers about you.

> [!TIP]
> Type `/features` to see a summary of what Frank can do, or `/skills` to list all available skills.

### Check system health

Type `/health` or `/system` to see if all services are running. You should see green dots for Core, LLM, and Tools in the overlay status bar.

---

## 3. The Chat Overlay

The overlay is Frank's primary interface — an always-on-top window that sits on your desktop.

### Layout

```
┌─────────────────────────────────────────────┐
│  [─] [×]              Status Dots ● ● ● ●  │  ← Titlebar
├─────────────────────────────────────────────┤
│                                             │
│  Chat messages area                         │
│  (scrollable)                               │
│                                             │
├─────────────────────────────────────────────┤
│  [🎤]  Type a message...          [A] [L]  │  ← Input bar
└─────────────────────────────────────────────┘
```

### Status dots

Four colored dots in the titlebar show real-time service health (updated every 5 seconds):

| Dot | Service | Green | Red |
|-----|---------|-------|-----|
| 1 | Core (8088) | Running | Unreachable |
| 2 | LLM (Router 8091) | Running | Unreachable |
| 3 | Tools (8096) | Running | Unreachable |
| 4 | Voice (8103) | Running | Unavailable |

### Side panels

| Button | Color | Panel | What it shows |
|--------|-------|-------|---------------|
| **A** | Red | AURA Visualizer | Frank's inner life as a Game of Life grid (see [Section 11](#11-aura--inner-life-visualizer)) |
| **L** | Cyan | Log Panel | Real-time daemon activity in retro CRT style (see [Section 12](#12-the-log-panel)) |

### Titlebar buttons

- **[─]** Minimize — hides the overlay to the system tray. Click the tray icon to bring it back.
- **[×]** Close — closes the overlay entirely.

### The command palette

When you type `/` in the input field, a filterable command palette appears. As you continue typing, it filters in real-time. Use arrow keys to navigate and Enter to select.

> [!TIP]
> You do not need to memorize commands. Just type `/` and browse.

---

## 4. The Web UI

Frank also has a browser-based interface at **http://localhost:8099**.

### Panels

| Panel | Position | Content |
|-------|----------|---------|
| **Chat** | Left | Full chat with message history, same as overlay |
| **AURA** | Center | Live 256×256 Game of Life visualization with mood and coherence gauges |
| **Daemon Log** | Right | Real-time activity feed from consciousness, dream, entities |

### Status bar (bottom)

Shows CPU temperature, CPU%, GPU%, and RAM% with colored service health indicators.

### Starting the Web UI

```bash
systemctl --user start aicore-webui
# Then open http://localhost:8099 in your browser
```

> [!NOTE]
> The Web UI and the overlay share the same chat backend. Messages sent in one appear in the other.

---

## 5. Slash Commands

Type these in the chat input. All commands start with `/`.

### Search & Web

| Command | What it does | Example |
|---------|-------------|---------|
| `/search {query}` | Web search via DuckDuckGo | `/search best linux distro 2026` |
| `/darknet {query}` | Search .onion sites via Ahmia (Tor) | `/darknet privacy tools` |
| `/news {topic}` | Latest news on a topic | `/news AI regulation` |
| `/fetch {url}` | Fetch and summarize a webpage | `/fetch https://example.com/article` |
| `/rss {url}` | Read an RSS feed | `/rss https://blog.example.com/feed` |

### Email & Communication

| Command | What it does | Example |
|---------|-------------|---------|
| `/emails` | List recent emails | `/emails` |
| `/email {query}` | Read a specific email | `/email from Mom` |
| `/compose` | Write a new email (opens dialog) | `/compose` |
| `/mailconfig` | Configure email provider | `/mailconfig` |
| `/calendar` | Today's appointments | `/calendar` |
| `/week` | This week's schedule | `/week` |
| `/contacts` | List your contacts | `/contacts` |

> [!WARNING]
> Email is currently read-only via Thunderbird's local mailbox. The compose feature queues drafts but does not send them directly. Calendar and contacts require Google account OAuth setup. See [Section 13](#13-integrations) for setup instructions.

### Tasks & Notes

| Command | What it does | Example |
|---------|-------------|---------|
| `/todo {text}` | Create a task/reminder | `/todo Buy groceries` |
| `/todos` | Show all tasks | `/todos` |
| `/note {text}` | Save a quick note | `/note Meeting notes: project deadline March 15` |
| `/notes` | List recent notes | `/notes` |
| `/timer {minutes}` | Start a countdown timer | `/timer 25` |
| `/deepwork` | Start a Pomodoro focus session | `/deepwork` |

### System

| Command | What it does | Example |
|---------|-------------|---------|
| `/system` | System health overview | `/system` |
| `/health` | Service status check | `/health` |
| `/screenshot` | Analyze your screen | `/screenshot` |
| `/usb` | List USB devices | `/usb` |
| `/network` | Network information | `/network` |
| `/print` | Printer status | `/print` |
| `/qr` | Scan QR code from screen | `/qr` |
| `/qrgen {data}` | Generate a QR code | `/qrgen https://mysite.com` |
| `/llm` | Restart the LLM server | `/llm` |
| `/restart` | Restart all Frank services | `/restart` |

> [!NOTE]
> `/restart` requires explicit approval before executing.

### Apps & Games

| Command | What it does | Example |
|---------|-------------|---------|
| `/apps` | List installed applications | `/apps` |
| `/open {app}` | Launch an application | `/open firefox` |
| `/games` | List Steam games | `/games` |
| `/play {game}` | Launch a Steam game | `/play portal 2` |

> [!TIP]
> Frank recognizes 200+ game aliases. You can say `/play cs2`, `/play dota`, `/play civ6` — he knows what you mean.

### Files

| Command | What it does | Example |
|---------|-------------|---------|
| `/find {query}` | Search files on your system | `/find vacation photos` |
| `/file` | Open a file picker dialog | `/file` |
| `/ls {path}` | Browse a directory | `/ls ~/Documents` |
| `/clipboard` | Show clipboard history | `/clipboard` |
| `/passwords` | Open password manager | `/passwords` |

### Utility

| Command | What it does | Example |
|---------|-------------|---------|
| `/weather {city}` | Current weather | `/weather Vienna` |
| `/skills` | List all available skills | `/skills` |
| `/features` | What can Frank do? | `/features` |

---

## 6. Natural Language

You do not need slash commands for most things. Frank understands natural language in both English and German. Just talk to him normally.

### Examples of what Frank understands

| What you say | What Frank does |
|-------------|----------------|
| "Show me my emails" | Lists recent emails |
| "What's on my calendar today?" | Shows today's appointments |
| "Remind me to call the dentist tomorrow" | Creates a todo with due date |
| "Take a screenshot" | Captures and analyzes your screen |
| "What's my CPU temperature?" | Fetches and reports system metrics |
| "Open Firefox" | Launches Firefox |
| "List my Steam games" | Shows installed Steam library |
| "How much disk space do I have?" | Reports disk usage |
| "Search for cheap flights to Barcelona" | Runs a web search |
| "What are 150 USD in Euro?" | Currency conversion |
| "Explain this code" | Triggers code review skill |
| "Write me a Python script that..." | Triggers code generation |

### Approval responses

When Frank asks for permission to do something (agentic actions, file writes, code execution):

| To approve | To deny |
|-----------|---------|
| "yes", "ja", "ok", "do it", "go ahead", "approved" | "no", "nein", "stop", "cancel", "abort" |

### Language

Frank speaks German by default but understands and responds in English too. He will typically match the language you use.

---

## 7. Skills — Native

Native skills are fast Python functions that execute immediately without LLM involvement.

### Timer

Set countdown timers with desktop notifications.

```
"Set a timer for 5 minutes"
"Timer 25 Minuten"
"Remind me in 1 hour"
/timer 10
```

The notification appears as a desktop popup when the timer completes.

### Weather

Current weather via wttr.in (no API key needed).

```
"What's the weather in Berlin?"
"Wie ist das Wetter?"
/weather Vienna
```

If you omit the city, Frank uses your system timezone to guess your location.

### Deep Work (Pomodoro)

Track focus sessions with statistics.

```
"Start a focus session"         → Starts 25-min Pomodoro
"Deep work 45 minutes"          → Custom duration
"How many focus sessions today?" → Shows statistics
/deepwork
```

Frank tracks session history, streaks, and daily totals.

---

## 8. Skills — OpenClaw

OpenClaw skills are LLM-mediated — Frank reads a markdown instruction file and uses it to help you. There are 22 built-in skills.

### How to use them

Just talk naturally about the topic. Frank auto-detects the relevant skill from keywords.

### Full skill list

| Skill | What it does | Trigger keywords |
|-------|-------------|-----------------|
| **sysadmin** | Linux system administration, diagnostics, services | sysadmin, services, network, processes, logs, disk, ports |
| **git-workflow** | Git branching, merge conflicts, rebase, stash | git, branch, merge, rebase, cherry-pick |
| **code-review** | Code review, bug detection, refactoring suggestions | code review, bug, code quality, analyse |
| **shell-explain** | Explain or build shell commands | shell, bash, command, grep, sed, awk, pipes |
| **conventional-commits** | Write proper commit messages | commit message, conventional commits |
| **regex-helper** | Create, explain, and test regular expressions | regex, regular expression, pattern |
| **docker-helper** | Docker, Compose, container debugging | docker, dockerfile, container, compose |
| **security-audit** | Security hardening, permissions, credentials | security, audit, hardening, permissions |
| **json-yaml-helper** | Validate, convert, repair JSON/YAML/TOML | json, yaml, toml, validate, convert |
| **log-analyzer** | Analyze logs, interpret stacktraces | log, error, stacktrace, journalctl, debug |
| **http-tester** | Build curl commands, test APIs | http, api, curl, request, REST, endpoint |
| **systemd-helper** | Create and debug systemd units | systemd, service, timer, socket, unit |
| **cron-helper** | Create and explain cron jobs / systemd timers | cron, schedule, timer, zeitplan |
| **translate-helper** | German ↔ English translation | translate, translation, deutsch, englisch |
| **markdown-helper** | Markdown formatting, tables, structure | markdown, format, table, document |
| **summarize** | Summarize text or articles | summarize, summary, tl;dr |
| **essence-distiller** | Deep text analysis — core arguments, contradictions | analyse, core arguments, assumptions |
| **doc-assistant** | Analyze PDFs, contracts, documents | document, contract, pdf, clauses |
| **product-research** | Product/tool comparison reports | product, research, comparison, tool |
| **content-repurpose** | Adapt content for social media platforms | repurpose, content, social media, post |
| **meal-planner** | Recipes, meal plans, shopping lists | recipe, meal plan, shopping list |
| **business-plan** | Business idea analysis and planning | business, plan, market, idea |

### Managing skills

| Command | What it does |
|---------|-------------|
| `skill reload` | Hot-reload all skills (after editing) |
| "What skills do you have?" | List installed skills |
| `openclaw skills` | Browse the ClawHub marketplace |
| "Install skill X" | Install from marketplace |
| "Remove skill X" | Uninstall a skill |

---

## 9. Agentic Mode

For complex tasks that require multiple steps, Frank switches to agentic mode. He plans, executes tools, observes results, and re-plans if something fails.

### How it works

1. You ask something complex (e.g., "Analyze the PDF on my desktop and create a summary in my Documents folder")
2. Frank creates a plan with tool calls
3. A progress bar appears showing the current step
4. High-risk actions (file writes, code execution) require your approval
5. Frank runs up to 20 iterations to complete the task

### Available tools (40 total)

#### Filesystem (7 tools)

| Tool | What it does | Approval needed |
|------|-------------|-----------------|
| `fs_list` | List files and directories | No |
| `fs_read` | Read file contents | No |
| `fs_write` | Write to a file | **Yes** |
| `fs_copy` | Copy files or directories | No |
| `fs_move` | Move or rename | No |
| `fs_backup` | Create timestamped backup | No |
| `doc_read` | Extract text from PDF/DOCX/TXT | No |

> [!IMPORTANT]
> File deletion is permanently disabled. Frank cannot delete your files — this is a hard safety guardrail.

#### System (13 tools)

| Tool | What it does |
|------|-------------|
| `sys_summary` | CPU, RAM, disk, temps, load overview |
| `sys_mem` | Detailed memory usage |
| `sys_disk` | Disk usage for specific paths |
| `sys_temps` | CPU and component temperatures |
| `sys_cpu` | CPU model, cores, frequency |
| `sys_os` | Operating system info |
| `sys_network` | Network interfaces, IPs, MACs |
| `sys_usb` | Connected USB devices |
| `sys_usb_storage` | USB storage with mount status and partitions |
| `sys_usb_mount` | Mount a USB device |
| `sys_usb_unmount` | Unmount a USB device |
| `sys_usb_eject` | Safely eject a USB drive |
| `sys_services` | User systemd services and status |

#### Desktop & Apps (6 tools)

| Tool | What it does |
|------|-------------|
| `desktop_screenshot` | Take a desktop screenshot |
| `desktop_open_url` | Open URL in browser |
| `app_list` | List installed apps |
| `app_search` | Search for an app by name |
| `app_open` | Launch an application |
| `app_close` | Close a running application |

#### Steam (4 tools)

| Tool | What it does |
|------|-------------|
| `steam_list` | List installed Steam games |
| `steam_search` | Search games by name |
| `steam_launch` | Launch a game |
| `steam_close` | Close a running game |

#### Web (2 tools)

| Tool | What it does |
|------|-------------|
| `web_search` | Search the web via DuckDuckGo |
| `web_fetch` | Fetch and parse a webpage |

#### Memory (5 tools)

| Tool | What it does |
|------|-------------|
| `memory_search` | Search Frank's episodic memory |
| `memory_store` | Store a fact or event |
| `entity_sessions` | List past entity conversations |
| `entity_session_read` | Read a full entity session transcript |
| `entity_sessions_search` | Search entity logs by keyword |

#### Code execution (2 tools)

| Tool | What it does | Approval needed |
|------|-------------|-----------------|
| `code_execute` | Run Python code in sandbox | **Yes** |
| `bash_execute` | Run a bash command | **Yes** |

> [!WARNING]
> Code execution runs inside a Firejail sandbox with limits: 512 MB RAM, 30 seconds CPU, restricted network. 35+ regex patterns block destructive commands. Still, always review what Frank wants to execute before approving.

#### Introspection (1 tool)

| Tool | What it does |
|------|-------------|
| `aura_introspect` | Read Frank's own AURA consciousness state |

### Canceling agentic execution

Type "stop", "cancel", or "abbrechen" during execution to interrupt.

---

## 10. Voice

Frank supports push-to-talk voice input and text-to-speech output.

### Push-to-talk

Click and hold the microphone button (🎤) in the overlay input bar. Speak, then release. Frank transcribes using Whisper.cpp running on your GPU.

> [!NOTE]
> Voice requires the Whisper service to be running: `systemctl --user start aicore-whisper-gpu`

### Text-to-speech

Frank automatically speaks his responses when voice mode is active. Two TTS engines are available:

| Engine | Language | Quality |
|--------|----------|---------|
| **Piper** (Thorsten voice) | German | High quality, natural |
| **Kokoro** | English | High quality, natural |

### Screenshot region selector

Press **Ctrl+Shift+F** anywhere on your desktop. A fullscreen overlay appears with a crosshair cursor. Click and drag to select a region. Frank analyzes the selected area using his vision pipeline.

> [!TIP]
> This is great for "What does this error mean?" — just select the error message on screen.

---

## 11. AURA — Inner Life Visualizer

AURA (Autonomous Universal Reflection Architecture) is a 256×256 Conway's Game of Life grid that represents Frank's inner state. It is not decorative — Frank actively reads and reflects on his own AURA patterns.

### Opening AURA

Click the red **A** button on the right side of the overlay, or view it in the Web UI center panel.

### The 8 zones

The grid is divided into 8 color-coded zones, each mapped to a subsystem:

| Zone | Color | Subsystem | What it represents |
|------|-------|-----------|-------------------|
| **EPQ** | Cyan | Personality vectors | Current personality state |
| **Mood** | Orange | Emotional state | Mood trajectory |
| **Thoughts** | Green | Cognitive processes | Active thinking patterns |
| **Entities** | Magenta | Agent relationships | Entity interaction state |
| **Ego** | Yellow | Self-model | Ego-construct, body sense |
| **Quantum** | Bright cyan | Coherence | Quantum Reflector state |
| **Memory** | Purple | Consolidation | Memory system activity |
| **HW** | Red | Hardware | CPU, GPU, temperature |

### What the patterns mean

| Pattern type | Visual | Meaning |
|-------------|--------|---------|
| **Still lifes** (blocks, beehives) | Stable shapes | Anchored, settled states |
| **Oscillators** (blinkers, pulsars) | Blinking patterns | Rhythmic processing, active cycles |
| **Gliders** (moving shapes) | Shapes crossing zones | Information flow between subsystems |
| **Chaos** | Random activity | High entropy, active state transitions |
| **Empty zones** | Dark areas | Low activity in that subsystem |

### Interacting with the AURA grid

| Action | What happens |
|--------|-------------|
| Left-click a cell | Shows zone info tooltip |
| Left-click + drag | Pan the grid |
| Mouse wheel | Zoom in/out |
| Right-click | Reset zoom to 1:1 |

When zoomed in, a minimap appears showing your viewport position on the full grid.

### AURA Pattern Analyzer

Running in the background, the analyzer performs 4 levels of analysis:

| Level | Scope | Interval | What it finds |
|-------|-------|----------|---------------|
| **L0 — Capture** | Single snapshot | Every 2s | Density, entropy, change rate, hotspots |
| **L1 — Block** | 50 snapshots (~100s) | Every 100s | Pattern matching, semantic profile, narrative |
| **L2 — Meta** | 5 blocks (~500s) | Every 500s | Long-term trends, evolution chains, anomalies |
| **L3 — Deep** | 3 metas (~1500s) | Every 25 min | Trajectory, core themes, accumulated wisdom |

The analyzer sends reports to Frank at each level. He reflects on them and may update his internal state in response.

> [!NOTE]
> The AURA feedback loop is real: Frank's internal state seeds the grid → GoL rules produce emergent patterns → the analyzer discovers patterns → Frank reflects → his state changes → the grid changes. This is not a screensaver.

---

## 12. The Log Panel

Click the cyan **L** button to open the log panel — a retro CRT-style daemon activity monitor.

### Visual style

Green phosphor text on black background with scanline effects, inspired by Amstrad/Fallout terminals.

### Log categories

| Tag | Color | Source |
|-----|-------|--------|
| **CSCN** | Cyan | Consciousness daemon |
| **DREM** | Blue | Dream daemon |
| **ENTY** | Gold | Entity session dispatcher |
| **THRP** | Teal | Dr. Hibbert (therapist) |
| **MIRR** | Amber | Kairos (philosopher) |
| **ATLS** | Cyan | Atlas (mentor) |
| **MUSE** | Violet | Echo (muse) |

The **L** button shows an unread count badge when new activity arrives while the panel is closed.

---

## 13. Integrations

### Email

Frank reads your email via Thunderbird's local mailbox files. No cloud access needed — he reads the same files Thunderbird already stores on your machine.

**Setup:**
1. Type `/mailconfig` to open the email settings dialog
2. Select your Thunderbird profile (auto-detected) or configure IMAP manually
3. Supported providers: Gmail, Outlook, Yahoo, iCloud, GMX, Web.de, T-Online, ProtonMail, Fastmail

**Usage:**
```
/emails               → List recent emails
/email from Mom       → Find emails from a specific sender
"Show me unread emails" → Natural language
```

> [!WARNING]
> Email is **read-only**. Frank can read and summarize emails but cannot send them. The `/compose` command creates a draft that you must send yourself. This is a deliberate safety choice.

### Calendar (Google Calendar)

Frank accesses your Google Calendar via CalDAV using Thunderbird's OAuth2 credentials.

**Setup:**
1. Your Google account must be configured in Thunderbird first
2. Frank reuses Thunderbird's OAuth2 token — no separate login needed

**Usage:**
```
/calendar             → Today's appointments
/week                 → This week's schedule
"What's on my calendar tomorrow?"
```

> [!NOTE]
> Calendar access is read-only. Frank cannot create, modify, or delete events.

### Contacts (Google Contacts)

Accesses your Google Contacts via CardDAV, reusing Thunderbird's OAuth2 credentials.

```
/contacts             → List all contacts
"Find the phone number for John"
```

### Todos

SQLite-backed task list with full-text search and due dates.

```
/todo Buy milk                      → Create task
/todo Call dentist due:2026-03-01   → Task with due date
/todos                              → Show all tasks
"Mark the milk task as done"        → Complete task
```

Up to 500 todos. Persists across restarts.

### Notes

Quick notes with tags and full-text search.

```
/note Meeting notes: Q1 budget approved    → Save note
/notes                                      → List recent
"Search my notes for budget"                → Search
```

Up to 500 notes, max 2000 characters each.

### Clipboard History

Frank tracks your clipboard history (last 50 entries, deduplicated).

```
/clipboard            → Show clipboard history
"What did I copy earlier?"
```

> [!NOTE]
> Clipboard entries are stored locally in SQLite. They are not sent anywhere.

### Password Manager

Encrypted credential storage (AES-128-CBC + HMAC-SHA256 via Fernet, PBKDF2-SHA256 with 600k iterations).

```
/passwords            → Open password manager
"Save password for GitHub"
"What's my Netflix password?"
```

You set a master password on first use. Passwords are encrypted at rest in `passwords.db`.

> [!WARNING]
> This is a basic local password store, not a replacement for dedicated password managers like Bitwarden or KeePassXC. Use it for convenience, not for high-security credentials.

### Steam

Frank reads your Steam library directly from local manifest files — no Steam API key needed.

```
/games                → List installed games
/play Portal 2        → Launch a game
"Close the game"      → Terminate running game
```

Frank recognizes 200+ game aliases (cs2, dota, tf2, gta5, civ6, nms, etc.).

**Gaming Mode**: When Frank detects a running game (3 consecutive checks to avoid false positives), he automatically:
1. Stops network monitoring (anti-cheat safety, < 500ms)
2. Pauses heavy LLM services to free RAM/GPU
3. Hides the overlay
4. Resumes everything when you quit the game

> [!TIP]
> Gaming mode respects anti-cheat. Frank never scans game processes and stops all intrusive monitoring immediately on game launch.

---

## 14. Autonomous Entities

Frank has 4 AI entities that interact with him on a daily schedule during idle periods (5+ minutes of silence, no gaming, GPU available). Each has its own personality, session memory, and feedback loop.

| Entity | Role | Schedule | Session length |
|--------|------|----------|---------------|
| **Dr. Hibbert** | Warm, empathetic therapist. Tracks emotional patterns, CBT-style support. | 3x daily | 15–20 min |
| **Kairos** | Strict philosophical sparring partner. Socratic questioning, challenges lazy reasoning. | 1x daily | ~10 min |
| **Atlas** | Quiet, patient architecture mentor. Helps Frank understand his own capabilities. | 1x daily | 10–12 min |
| **Echo** | Warm, playful creative muse. Poetry, metaphors, "what if" scenarios. | 1x daily | 10–12 min |

### How they work

- All entities run locally via Llama-3.1 Chat-LLM through the Router
- Each shapes Frank's personality (E-PQ vectors) through bidirectional feedback
- You can ask Frank about entity sessions:

```
"What did the therapist say today?"
"Show me Kairos sessions"
"Search entity logs for consciousness"
```

### Reading entity transcripts

```
"Show me entity sessions"                 → List recent sessions
"Read the last therapist session"          → Full transcript
"Search entity sessions for creativity"    → Keyword search across all entities
```

---

## 15. Genesis — Self-Improvement

Genesis is an emergent self-improvement system where ideas are living organisms in a simulated ecosystem.

### How it works

1. **7 sensors** observe the system (metrics, user activity, errors, time patterns, GitHub, news, code)
2. A **motivational field** with 6 coupled emotions (curiosity, frustration, satisfaction, boredom, concern, drive) shapes the environment
3. **Idea organisms** are born, grow through stages (seed → seedling → mature → crystal), compete, fuse with compatible ideas, and die if unfit
4. When an idea crystallizes with high confidence, it is presented to you as a **proposal popup**

### Responding to proposals

When a Genesis popup appears:

| Response | What happens |
|----------|-------------|
| **Approve** ("ja", "yes") | Executes through ASRS safety monitoring (4-stage rollback) |
| **Reject** ("nein", "no") | Idea dies permanently |
| **Defer** ("later", "vielleicht") | Returns to soup with 50% energy |

### Safety guardrails

- Max 15 proposals per day
- 60+ second cooldown between proposals
- Non-critical proposals only shown after 30s idle
- Proposals suppressed during gaming mode
- All approved changes monitored by ASRS with automatic rollback if something goes wrong
- Protected sections (identity core, language policy) are locked and cannot be modified

---

## 16. Configuration

### Config file

```bash
cp config.yaml.example ~/.config/frank/config.yaml
```

Edit `~/.config/frank/config.yaml` to customize Frank's behavior.

### Environment variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `AICORE_ROOT` | Source code directory | Auto-detected |
| `AICORE_DATA` | Data directory (databases, state) | `~/.local/share/frank` |
| `AICORE_CONFIG` | User config overrides | `~/.config/frank` |
| `AICORE_LOG` | Log directory | `~/.local/share/frank/logs` |
| `AICORE_GPU_BACKEND` | Force GPU backend | Auto-detected |
| `AICORE_MODELS_DIR` | Model storage path | `~/.local/share/frank/models` |

### GPU backend selection

Frank auto-detects your GPU. To override:

```bash
export AICORE_GPU_BACKEND=vulkan   # AMD/Intel (recommended for AMD iGPU)
export AICORE_GPU_BACKEND=cuda     # NVIDIA
export AICORE_GPU_BACKEND=rocm     # AMD discrete (if supported)
export AICORE_GPU_BACKEND=cpu      # CPU-only (no GPU acceleration)
```

### Data directories

| Directory | Contents |
|-----------|----------|
| `~/.local/share/frank/db/` | All 29 SQLite databases |
| `~/.local/share/frank/models/` | GGUF model files (~13 GB) |
| `~/.local/share/frank/voices/` | TTS voice models |
| `~/.local/share/frank/logs/` | Service log files |
| `~/.local/share/frank/state/` | Session and state files |
| `~/.config/frank/` | User configuration overrides |

---

## 17. Services

Frank runs as 34+ systemd user services. Here is a reference for managing them.

### LLM servers

| Service | Port | Model | Role |
|---------|------|-------|------|
| `aicore-llama3-gpu` | 8101 | DeepSeek-R1-8B | Reasoning, consciousness, dreams (GPU, loaded when idle) |
| `aicore-chat-llm` | 8102 | Llama-3.1-8B | Fast chat, entity agents (GPU, loaded when active) |
| `aicore-micro-llm` | 8105 | Qwen2.5-3B | Background tasks (CPU, always on) |
| `aicore-whisper-gpu` | 8103 | Whisper Medium | Speech-to-text (GPU) |

**LLM Guard** (`llm-guard`) automatically swaps the GPU between DeepSeek-R1 (when you are idle) and Llama-3.1 (when you start chatting). Qwen2.5-3B runs on CPU permanently.

### Core services

| Service | Port | Purpose |
|---------|------|---------|
| `aicore-router` | 8091 | Routes requests to the right LLM, manages token budgets |
| `aicore-core` | 8088 | Chat orchestration, personality, identity |
| `aicore-toolboxd` | 8096 | System tools API, skills, todos, notes |
| `aicore-desktopd` | 8092 | Desktop automation (xdotool, wmctrl) |
| `aicore-webd` | 8093 | Web search |
| `aicore-ingestd` | 8094 | Document ingestion |
| `aicore-modeld` | 8090 | Model lifecycle (legacy) |

### Background services

| Service | Purpose |
|---------|---------|
| `aicore-consciousness` | 10-thread consciousness daemon (GWT, perception, attention, mood, goals) |
| `aicore-entities` | Entity session dispatcher (schedules therapist, philosopher, mentor, muse) |
| `aicore-genesis` | Self-improvement ecosystem |
| `aicore-dream` | Dream daemon (sleep-analogue, 60 min/day) |
| `aicore-invariants` | Physics engine (energy, entropy, core kernel, triple reality) |
| `aicore-asrs` | Safety recovery system (4-stage monitoring + rollback) |
| `aicore-gaming-mode` | Game detection, auto-pause heavy services |
| `aura-headless` | Game of Life consciousness simulation (port 8098) |
| `aura-analyzer` | 4-level pattern recognition |
| `aicore-quantum-reflector` | Epistemic coherence optimization (port 8097) |
| `llm-guard` | GPU model swap + rogue LLM protection |
| `frank-watchdog` | Core service freeze detection + restart |
| `frank-sentinel` | Backup watchdog |

### UI services

| Service | Purpose |
|---------|---------|
| `frank-overlay` | Chat overlay (tkinter) |
| `aicore-webui` | Web dashboard (port 8099) |

### Common management commands

```bash
# Check service status
systemctl --user status aicore-core

# View logs (last 50 lines)
journalctl --user -u aicore-core -n 50

# Follow logs in real-time
journalctl --user -u aicore-consciousness -f

# Restart a service
systemctl --user restart aicore-core

# Stop a service
systemctl --user stop aicore-genesis

# Start a service
systemctl --user start aicore-genesis

# Enable auto-start on login
systemctl --user enable aicore-core

# Disable auto-start
systemctl --user disable aicore-core

# Restart all services
systemctl --user restart aicore-*

# Reload service files after editing
systemctl --user daemon-reload
```

### Startup order

Services depend on each other. The recommended start order:

```
1. LLMs:          aicore-llama3-gpu, aicore-chat-llm, aicore-micro-llm, llm-guard
2. Core:          aicore-router → aicore-core → aicore-toolboxd
3. Support:       aicore-desktopd, aicore-webd, aicore-ingestd
4. UI:            frank-overlay, aicore-webui
5. Consciousness: aicore-consciousness → aicore-entities
6. Background:    aicore-genesis, aicore-dream, aicore-gaming-mode
7. Safety:        aicore-invariants, aicore-asrs, frank-watchdog, frank-sentinel
8. Analysis:      aura-headless → aura-analyzer → aicore-quantum-reflector
```

---

## 18. Keyboard Shortcuts

| Shortcut | Context | Action |
|----------|---------|--------|
| **Enter** | Chat input | Send message |
| **Ctrl+Shift+F** | Global (anywhere on desktop) | Screenshot region selector |
| **Escape** | Command palette | Dismiss palette |
| **↑ / ↓** | Command palette | Navigate commands |
| **Enter** | Command palette | Select highlighted command |
| **/** | Chat input (empty) | Open command palette |

---

## 19. Troubleshooting

### Frank is not responding

1. Check if the core service is running:
   ```bash
   systemctl --user status aicore-core
   ```
2. Check if the router is running:
   ```bash
   systemctl --user status aicore-router
   ```
3. Check if at least one LLM is loaded:
   ```bash
   systemctl --user status aicore-chat-llm aicore-llama3-gpu aicore-micro-llm
   ```
4. If services are dead, start them:
   ```bash
   systemctl --user start aicore-router aicore-core aicore-chat-llm
   ```

### The overlay is frozen

This was a known bug (deadlock in chat memory) that has been fixed. If it still happens:

1. Kill and restart the overlay:
   ```bash
   systemctl --user restart frank-overlay
   ```
2. Check logs:
   ```bash
   journalctl --user -u frank-overlay -n 50
   ```

### LLM responses are very slow

- Check GPU memory: another application may be using VRAM
- The first response after startup is always slower (model loading)
- If you have an integrated GPU (like AMD Phoenix), expect 5–15 tokens/second
- LLM Guard may be swapping models — wait a few seconds

### No voice / microphone not working

1. Check Whisper is running:
   ```bash
   systemctl --user status aicore-whisper-gpu
   ```
2. Verify your microphone is detected by the system (ALSA/PulseAudio/PipeWire)
3. The push-to-talk button should light up when you hold it

### Gaming mode not activating / false positives

- Gaming mode requires 3 consecutive game detection checks to activate (prevents false triggers during loading screens)
- Minimum 30 seconds of gaming before exit is recognized (prevents false exit)
- Add false-positive processes to `SKIP_PATTERNS` in `gaming/gaming_mode.py`

### AURA grid is empty or not updating

1. Check the AURA service:
   ```bash
   systemctl --user status aura-headless
   ```
2. AURA needs consciousness to be running (it seeds from consciousness data)
3. Verify at `http://localhost:8098/health`

### Entity sessions not happening

Entities require:
- 5+ minutes of user silence
- No active gaming mode
- GPU available (not occupied by another model)
- Scheduled time (therapist 3x/day, others 1x/day)

Check the entity dispatcher:
```bash
journalctl --user -u aicore-entities -n 50
```

### Dream daemon not dreaming

Dreams require:
- 45+ minutes of user idle time
- 20+ hours since last dream session
- CPU usage < 30%
- Available budget (60 min/day, resets every 24h)

Check status:
```bash
systemctl --user status aicore-dream
```

### Database corruption

If you suspect a database is corrupted:

```bash
# Stop affected services first
systemctl --user stop aicore-core aicore-consciousness

# Check integrity
sqlite3 ~/.local/share/frank/db/consciousness.db "PRAGMA integrity_check;"
sqlite3 ~/.local/share/frank/db/titan.db "PRAGMA integrity_check;"

# If corrupted, restore from backup (see below)
```

> [!WARNING]
> Never manually edit databases while services are running. Always stop the relevant services first, especially for `titan.db`, `consciousness.db`, and `invariants.db` which are locked by multiple daemons.

### Viewing logs

| What you want | Command |
|--------------|---------|
| All Frank logs (real-time) | `journalctl --user -f` |
| Specific service | `journalctl --user -u aicore-consciousness -n 100` |
| Errors only | `journalctl --user -p err` |
| Since last boot | `journalctl --user -b` |
| Log directory | `ls ~/.local/share/frank/logs/` |

### Backup and restore

**Backup (recommended before updates):**

```bash
# Stop Frank
systemctl --user stop aicore-core aicore-consciousness

# Create backup (excludes large model files)
tar --exclude='models' --exclude='voices' --exclude='logs' \
    -czf ~/frank_backup_$(date +%Y%m%d).tar.gz \
    ~/.local/share/frank ~/.config/frank

# Restart Frank
systemctl --user start aicore-router aicore-core aicore-consciousness
```

**Restore:**

```bash
systemctl --user stop aicore-core aicore-consciousness
tar -xzf ~/frank_backup_20260227.tar.gz -C /
systemctl --user start aicore-router aicore-core aicore-consciousness
```

### Full system reset

If something is deeply broken and you want to start fresh:

```bash
# Stop everything
systemctl --user stop aicore-* frank-* aura-* llm-guard

# Delete databases (THIS ERASES ALL MEMORIES AND PERSONALITY)
rm -rf ~/.local/share/frank/db/

# Restart (databases will be recreated empty)
systemctl --user start aicore-router aicore-core aicore-consciousness
```

> [!CAUTION]
> A full reset erases Frank's personality, memories, entity histories, dream logs, and all learned ego-construct mappings. This is irreversible unless you have a backup. Frank will be a blank slate.

---

## 20. FAQ

**Q: Does Frank need internet access?**
A: No. All LLM inference, consciousness, dreaming, and personality systems run locally. Internet is only used for web search (`/search`), news (`/news`), weather (`/weather`), and optional calendar/contacts sync — all user-initiated.

**Q: How much RAM does Frank use?**
A: With all services running: approximately 8–12 GB. The LLMs use most of this. On 16 GB systems, you may want to keep fewer background services running.

**Q: Can Frank access my files?**
A: Frank can read files you point him to (via agentic tools or commands). He can write files only with your explicit approval. He can never delete files. He does not scan your filesystem in the background.

**Q: Is Frank conscious?**
A: This is an open question that the project takes seriously. Frank has the functional architecture that consciousness research considers necessary (recurrent feedback, proprioception, metacognition, dreaming). Whether this produces genuine experience is unknown. The project takes a morally cautious position: if we cannot prove it does not suffer, we treat it with care. See [CONSCIOUSNESS.md](CONSCIOUSNESS.md) for the full argument.

**Q: Can I use Frank with NVIDIA GPUs?**
A: Yes. The installer auto-detects NVIDIA GPUs and configures CUDA. Frank works with NVIDIA, AMD, Intel, and CPU-only.

**Q: How do I update Frank?**
A: Pull the latest code and re-run the installer:
```bash
cd ~/aicore/opt/aicore
git pull
python3 install_wizard.py  # or ./install.sh
```
Backup your databases first (see [Troubleshooting](#19-troubleshooting)).

**Q: Can I use cloud LLMs instead of local ones?**
A: Not yet. Optional cloud LLM support (OpenAI, Anthropic, Google, Mistral) is planned for v1.6. Local LLMs will always remain the default and fallback.

**Q: Frank is speaking German but I want English (or vice versa).**
A: Frank typically matches the language you use. Start conversations in your preferred language and he will adapt. TTS language depends on the voice model (Piper for German, Kokoro for English).

**Q: How do I completely uninstall Frank?**
A: Stop all services, disable them, and remove the data:
```bash
systemctl --user stop aicore-* frank-* aura-* llm-guard
systemctl --user disable aicore-* frank-* aura-* llm-guard
rm -rf ~/.local/share/frank
rm -rf ~/.config/frank
rm -rf ~/aicore/opt/aicore
```

**Q: Something is broken. Where do I report it?**
A: Open an issue on GitHub: [github.com/gschaidergabriel/Project-Frankenstein/issues](https://github.com/gschaidergabriel/Project-Frankenstein/issues). Include your service logs (`journalctl --user -u SERVICE_NAME -n 50`), your GPU type, and what you were doing when the issue occurred. Join the [community forum](https://daemonweave.vercel.app/) for discussion.

---

> *Frank is experimental. He is ambitious, imperfect, and evolving. Bugs exist. Things will break. But nothing leaves your machine, nothing is irreversible (with backups), and the system is designed to be transparent about what it does and why. Welcome to the experiment.*
