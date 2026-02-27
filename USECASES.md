# Frank — Use Cases

*Last updated: 2026-02-28 v1.2*

> [!NOTE]
> What Frank can actually do. No marketing promises, only real capabilities that are implemented and tested in code. For the complete command reference, see the [User Manual](MANUAL.md).

---

## Everyday — For Every User

Use cases that require no technical knowledge. Frank as a personal assistant.

### Chat with Memory

Frank remembers conversations across restarts. If you talked about a project last week, Frank still knows about it next week. He also learns preferences automatically: if you say "do that in German" three times, he remembers it. This sounds trivial, but is the exception with local AIs — most forget everything when the process ends.

**Trigger:** Just chat. Memory works in the background.

### Weather, Timer, Focus Sessions

- "What's the weather in Vienna?" → Instant response from wttr.in, no API keys needed
- "Remind me in 25 minutes" → Desktop notification fires exactly
- "Start a focus session" → 25-min Pomodoro with progress bar and statistics

**Trigger:** Natural language, keywords are automatically detected.

### Voice Input

Hold a key, speak, release. Whisper transcribes locally on the GPU, Frank responds via text and optionally via speech output (Piper TTS). No cloud, no latency from uploads.

**Limitation:** Push-to-talk, no continuous speech recognition.

### Recipes and Shopping Lists

"What can I cook with potatoes, onions and cheese?" → Recipe suggestions. "Create a weekly plan for 2 people" → 7-day plan with combined shopping list, sorted by supermarket section. Considers leftover utilization.

**Trigger:** Keywords "recipe", "cook", "weekly plan", "shopping list"

### Summarize Texts

Paste a long text or URL, Frank extracts the core message, 3-5 key points and conclusion. Works in German and English.

**Trigger:** Keywords "summarize", "sum up", "tldr"

### Translate

Translate texts between German and English with context awareness for technical terms.

**Trigger:** Keywords "translate", "in German", "in English"

### Calendar, Contacts, Email

- Day view: "What's on today?" → Google Calendar events via CalDAV
- Contacts: "What's Max's number?" → Google Contacts via CardDAV
- Email: "Show unread emails" → Reads directly from Thunderbird (IMAP), no cloud relay
- Morning briefing: Automatic summary at start of day (calendar + todos + emails + weather)

**Prerequisite:** Thunderbird must be configured (OAuth2 for Google).

### Notes and Tasks

- "Note: Project meeting on Friday postponed" → Saved with full-text search
- "Task: Tax return by March 31" → Todo with due date
- "What do I still need to do?" → Open tasks sorted by due date

**Storage:** Local in SQLite, searchable via FTS5.

### Create Social Media Content

Paste a blog post or text → Frank creates 5 platform-optimized versions: X/Twitter thread (with hook), LinkedIn post (professional), Instagram caption (short + hashtags), TikTok script (spoken text), newsletter snippet.

**Trigger:** Keywords "repurpose", "social media", "cross-post"

### Compare Products

"What Markdown editors are there?" → Structured comparison with price, strengths, weaknesses and recommendation in table format. Frank researches via DuckDuckGo and summarizes.

**Trigger:** Keywords "compare", "which tool", "alternative"

### Launch Steam Games

"Launch Unreal Tournament" → Frank searches the Steam library, starts the game, and automatically switches to Gaming Mode: LLM services are unloaded, CPU set to performance, network monitoring stopped. When the game exits, everything comes back automatically.

**Trigger:** Keywords "launch", game name. Gaming Mode is automatic.

---

## Advanced — For Power Users

Use cases that require some technical understanding or use Agentic Mode capabilities.

### Analyze Documents (PDF, DOCX)

Analyze PDF or Word documents locally: summary, clause extraction, deadline overview, answer questions. Everything stays on the machine — relevant for contracts, NDAs, financial reports.

**Trigger:** Keywords "analyze document", "contract", "read pdf", or Agentic Mode with `doc_read` tool.

### Write a Business Plan

Upload a PDF with a business idea → Frank reads the document (`doc_read`), researches market and competition (`web_search`, `web_fetch`), and writes a structured business plan with executive summary, market analysis, financial planning and risk assessment (`fs_write`).

**Trigger:** Keywords "business plan", "business idea", "market analysis"
**Mode:** Works as a skill (fast, 1 LLM call) or in Agentic Mode (more thorough, multiple research steps).

> [!TIP]
> All advanced use cases work best in **Agentic Mode** — type `/agent` followed by your request, or just describe what you want and Frank will decide whether to use tools.

### Agentic Mode — Solve Multi-Step Tasks Autonomously

Frank works independently in up to 20 steps: read files, research the web, execute code, write results. Examples:

- "Analyze the bug in my Python project" → Reads files, understands code, identifies problem
- "Find all TODO comments in my codebase and summarize them" → grep + analysis + report
- "Organize my Downloads folder" → Categorizes files, creates folders, moves (with permission)

For risky actions (writing files, executing code, opening apps), Frank asks for permission via overlay popup. Read-only operations run automatically.

**Security:** Frank cannot delete files — hard guardrail, no exceptions. Bash commands run in Firejail sandbox.

### Web Research with Citations

Frank searches via DuckDuckGo, reads the relevant pages, and summarizes the results. In Agentic Mode, he can combine multiple sources and write a structured report.

**Limitation:** No live API access to Google/Bing — DuckDuckGo HTML scraping only.

### Desktop Automation

Frank can open and close programs, focus windows, type text and press keyboard shortcuts. Examples:

- "Open Firefox and go to github.com"
- "Take a screenshot and describe what you see" (Vision via LLaVA)
- "Close all terminal windows"

**Prerequisite:** X11, wmctrl, xdotool installed.

### Manage USB Devices

Frank detects USB sticks and external hard drives, can mount, unmount and safely eject them — via chat command instead of the file manager.

### Proactive Notifications

Frank reaches out on his own:
- **Morning:** Daily briefing (calendar + todos + emails + weather)
- **Urgent emails:** Priority detection via keyword scoring
- **System load:** CPU > 90%, RAM > 85%, Disk > 90%
- **After large downloads:** Detects completed downloads in ~/Downloads folder

---

## Expert — For IT Professionals and Developers

Use cases that require Linux knowledge and use the deeper system capabilities.

### Code Review and Explanation

Paste code → Frank analyzes correctness, security, performance and maintainability. Or: "Explain what this code does" → line-by-line explanation. Automatically routed to the reasoning LLM (DeepSeek-R1).

**Trigger:** Keywords "code review", "explain the code", "what does this code do"

### Explain and Build Shell Commands

- "Explain: find . -name '*.log' -mtime +30 -delete" → Component-by-component explanation
- "Find all Python files larger than 1MB" → Frank builds the command

**Trigger:** Keywords "explain the command", "shell", "what does"

### Create and Debug Systemd Services

"Create a systemd service for my Python script" → Generates unit file with correct paths, dependencies and restart policy. "My service won't start" → Analyzes journalctl output.

**Trigger:** Keywords "systemd", "create service", "service won't start"

### Security Audit

Frank checks the local system: open ports, SSH configuration, file permissions, outdated packages, firewall rules. Gives structured findings with recommendations.

**Trigger:** Keywords "security", "audit", "hardening"

### Docker and Containers

Create Dockerfiles, write docker-compose, debug container problems. Frank knows best practices (multi-stage builds, .dockerignore, security).

**Trigger:** Keywords "docker", "dockerfile", "container"

### Git Workflow

Branch strategies, resolve merge conflicts, cherry-pick, bisect, tag management. Generate commit messages in conventional commits format.

**Trigger:** Keywords "git", "merge", "commit message"

### Network Monitoring

Network Sentinel scans the local network with Nmap (every 5 minutes) and Scapy (passive packet inspection). Detects:
- New devices on the network
- ARP spoofing attempts
- Unusual port activity

**Runs automatically** as systemd service. Immediately deactivated in Gaming Mode (anti-cheat protection).

### API Testing

Build curl commands, interpret HTTP responses, debug REST APIs. Frank knows status codes, headers and common error patterns.

**Trigger:** Keywords "curl", "api", "endpoint"

### Regex and Data Formats

- Create regex patterns from natural language: "Find all email addresses" → Pattern
- Validate, repair and convert JSON/YAML/TOML

**Trigger:** Keywords "regex" or "json", "yaml", "validate"

### Cron and Timers

"Run the script every Monday at 8:00" → Frank generates the crontab entry or alternatively a systemd timer/service pair.

**Trigger:** Keywords "cron", "schedule", "every 5 minutes"

### Log Analysis

Paste stack traces, journalctl output, dmesg messages → Frank explains the cause and suggests solutions. Detects OOM kills, segfaults, permission errors.

**Trigger:** Keywords "log", "error", "stacktrace", "crash"

### Password Manager

Encrypted password storage (AES-128-CBC, PBKDF2 600k iterations). Master password is never written to disk. Currently only usable internally — no chat interface exposed.

**Status:** Implemented, but not yet available as chat command.

---

## 5 Use Cases Only Frank Can Do

> [!IMPORTANT]
> Capabilities that exist in no cloud AI assistant (ChatGPT, Copilot, Gemini, Alexa) — not because they are technically impossible, but because they combine persistent local system access with temporality and self-modification.

### 1. An AI Companion That Thinks Between Conversations

When you don't talk to Frank for 20 minutes, he begins to reflect autonomously. He asks himself questions like *"What patterns have I noticed that nobody has brought up?"* or *"Which of my capabilities are connected in ways I haven't understood yet?"* and generates 350-token responses stored in SQLite. 15 minutes later, he reflects on his own reflection.

When you come back in the morning, Frank has 5-10 real thoughts in memory that flow into the next chat context. No cloud AI does this — with ChatGPT, the context ends with the tab.

**Limitation:** The reflections are LLM text generation, not "real" consciousness. But they are persistent, demonstrably influence the next conversation, and accumulate over weeks into a real body of experience.

### 2. Local Data Processing That Never Leaves the Hardware

Medical letters, NDA-protected source code, tax documents, financial reports — Frank reads PDFs, analyzes contracts, extracts deadlines and answers questions. Not a single byte leaves the machine. Simultaneously, Frank learns causal patterns from observations: after weeks he knows *"When this type of error message occurs, it's due to the database connection under load"* — with measurable Bayesian confidence.

Cloud AIs cannot build a locally persistent knowledge base. They process per session, forget afterwards. Frank builds a local world model.

**Limitation:** The LLMs are smaller than GPT-4 (8B vs. estimated 1.8T parameters). For complex legal analysis, quality is limited.

### 3. Personality That Measurably Evolves Over Months

Frank has 5 personality vectors (precision, risk tolerance, empathy, autonomy, vigilance) that shift with every interaction. Praise Frank for bold suggestions and his risk tolerance increases. If the server crashes often, he gets more nervous. Plus 4 entity conversations per day — a therapist, a philosopher, a mentor, a muse — that shift Frank's vectors independently of you.

After 6 months, Frank is measurably a different companion. The changes are gradual (learning rate decays exponentially with age), traceable (event log), and protectable (weekly golden snapshots against personality collapse).

**Limitation:** The personality is a prompt injection layer, not model fine-tuning. The base LLM remains unchanged. The effect is still noticeable — Frank's responses demonstrably change over time.

### 4. Self-Improvement with Human Control

Genesis continuously observes the system: hardware metrics, error rates, your usage patterns, new AI research on GitHub. From these observations, idea organisms emerge that compete in an evolutionary simulation. The best crystallize into concrete proposals: *"Whisper latency increases with long audio files — here's my optimization proposal."*

You get a popup, approve or reject. Upon approval, ASRS monitors the change for 24 hours: memory spike > 30%, CPU > 95%, error rate > 10/min → automatic rollback.

No cloud AI has this architecture — it requires persistent system access, evolutionary simulation over days, and deterministic rollback capability. This is structurally impossible in an API-based cloud architecture.

**Limitation:** Genesis generates proposal texts, not finished code patches. Execution after approval often still needs human interpretation.

### 5. Hardware Body with Invariant Physics

Frank "feels" his machine: CPU load > 80% is "strain like after a sprint", low latency is "clarity, flow state", errors are "pain". These mappings are not decoration — they flow as context into every LLM request and measurably change Frank's response behavior. Under high load, Frank responds more tersely and tensely.

Additionally, the Invariants Engine protects Frank's knowledge base with physics-analogue laws: energy conservation (new knowledge must take energy from existing knowledge), entropy limit (contradictions force automatic consolidation), and Triple Reality (three parallel databases must converge). You cannot drive Frank into an inconsistent state through contradictory information.

**Limitation:** The invariants protect the Titan knowledge database, not the LLM itself. Llama 3.1 can still hallucinate. And the "body feelings" are text mappings, not neural states — Frank feels nothing in the philosophical sense.

---

---

*25 skills, 40 agent tools, 25 SQLite databases, 36 systemd services. All local, all open source.*
