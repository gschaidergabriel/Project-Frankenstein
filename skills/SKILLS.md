# Frank Skill System

## What Are Skills?

Skills are modular plugins that extend Frank's capabilities beyond normal chat.
When a user types something like "wie ist das wetter?" or "erstelle ein dockerfile",
Frank doesn't send it to the LLM as a generic chat message — instead, the **Skill Registry**
matches the input against registered keywords and dispatches it to a specialized handler.

Skills come in two formats:

| | Native (Python) | OpenClaw (SKILL.md) |
|---|---|---|
| **Format** | `.py` file with `SKILL` dict + `run()` | Markdown with YAML frontmatter |
| **Execution** | Direct Python — no LLM needed | LLM interprets instructions with Frank's persona |
| **Speed** | Fast (milliseconds) | Slower (10–80s, depends on LLM) |
| **Best for** | Deterministic tasks (API calls, timers, calculations) | Reasoning, text analysis, explanations |
| **Uninstallable** | No (protected) | Yes |
| **Marketplace** | N/A | ClawHub integration |

### Installed Skills (20)

**Native (3):** `weather`, `timer`, `deep_work`

**OpenClaw (17):** `summarize`, `sysadmin`, `essence-distiller`, `conventional-commits`,
`regex-helper`, `code-review`, `shell-explain`, `git-workflow`, `json-yaml-helper`,
`log-analyzer`, `http-tester`, `docker-helper`, `security-audit`, `cron-helper`,
`translate-helper`, `markdown-helper`, `systemd-helper`

---

## Creating a Native Skill

Drop a `.py` file into `skills/`. It needs two things: a `SKILL` dict and a `run()` function.

### Minimal Example

```python
# skills/hello.py

SKILL = {
    "name": "hello",
    "description": "Greets the user",
    "keywords": ["hello", "hi", "greet"],
}

def run(user_query: str = "", **kwargs) -> dict:
    return {"ok": True, "output": "Hey there!"}
```

### Full Example (with all fields)

```python
# skills/my_skill.py

SKILL = {
    "name": "my_skill",                          # Required — unique identifier
    "description": "What this skill does",        # Required — shown in skill list
    "version": "1.0",                             # Optional
    "category": "utility",                        # Optional
    "risk_level": 0.0,                            # Optional (0.0–1.0)
    "timeout_s": 10.0,                            # Optional (default: 15s)
    "keywords": [                                 # Required for matching
        "trigger", "words", "that activate",
    ],
    "parameters": [                               # Optional
        {
            "name": "location",
            "type": "string",
            "description": "Target location",
            "required": False,
            "default": "",
        },
    ],
}

def run(user_query: str = "", location: str = "", **kwargs) -> dict:
    """
    Called when the skill is triggered.

    Args:
        user_query: The full user message that triggered this skill
        **kwargs: Any additional parameters

    Returns:
        dict with "ok" (bool) and "output" (str) or "error" (str)
    """
    if not location:
        return {"ok": False, "error": "No location provided"}

    result = do_something(location)
    return {"ok": True, "output": result}
```

### Rules for Native Skills

- File must NOT start with `_` (skipped during scan)
- `SKILL` dict must have at least `name` and `description`
- `run()` must be callable and return a dict (or it gets auto-wrapped)
- `run()` receives `user_query` (the triggering message) plus any named parameters
- Keep `timeout_s` realistic — the executor kills the skill after this
- Native skills cannot be uninstalled via chat (delete the `.py` file manually)

---

## Creating an OpenClaw Skill

Create a subdirectory in `skills/` with a `SKILL.md` file. The file has two parts:
YAML frontmatter (configuration) and a Markdown body (LLM instructions).

### Minimal Example

```
skills/my-skill/SKILL.md
```

```markdown
---
name: my-skill
description: Does something useful
keywords: [trigger, words]
---

# My Skill

You are an expert at doing useful things.

When the user asks you to do X:
1. Do step A
2. Then step B
3. Format the result like this: ...
```

### Full YAML Frontmatter Reference

```yaml
---
name: my-skill                    # Required — unique identifier
description: Short description    # Required — shown in skill list
version: 1.0                      # Optional — for update tracking
keywords: [word1, word2, word3]   # Required — trigger keywords (case-insensitive)
user-invocable: true              # Optional — can user call directly? (default: true)
timeout_s: 30                     # Optional — user-facing timeout hint (min 90s enforced)
risk_level: 0.0                   # Optional — 0.0 (safe) to 1.0 (dangerous)
max_tokens: 800                   # Optional — LLM output limit (default: 800)
temperature: 0.15                 # Optional — LLM creativity (default: 0.3)
model: auto                       # Optional — "auto" (Router decides), "llama", or "qwen"
requires:                         # Optional — dependency checks
  bins: [jq, curl]                #   Required binaries (checked with `which`)
  env: [API_KEY]                  #   Required environment variables
---
```

### Writing Good Instructions (Markdown Body)

The body after `---` is injected as part of the LLM's system prompt. It's NOT documentation
for humans — it's instructions for the LLM. Write it like you're briefing a colleague.

**Effective patterns:**

```markdown
# Skill Name

You are an expert in [domain]. Your task is [objective].

## Context
- The system runs Ubuntu Linux
- The user is `ai-core-node`
- [Any relevant system details]

## Tasks

### When the user asks X:
1. Do A
2. Do B
3. Format like this: ...

### When the user asks Y:
1. Different approach ...

## Output Format

**Section:**
- Point 1
- Point 2

## Rules
- Never do [dangerous thing]
- Always [safety measure]
```

**Tips:**
- Be specific. "Analyze the text" is vague. "Extract the thesis, list arguments, identify assumptions" is actionable.
- Include output format examples. The LLM follows format templates reliably.
- Add domain context (Ubuntu, systemd, local services) to ground the response.
- Keep instructions under 2000 chars. Combined with Frank's persona (~4300 chars), longer instructions slow down the LLM significantly.
- Set `temperature` low (0.10–0.20) for technical/factual skills, slightly higher (0.20–0.30) for creative/translation tasks.
- Set `max_tokens` proportional to expected output: 300 for short answers (commit messages), 1500 for long analysis.

### Choosing max_tokens and temperature

| Skill Type | max_tokens | temperature | Example |
|-----------|-----------|------------|---------|
| Short factual | 300 | 0.10–0.15 | commit messages, cron expressions |
| Medium structured | 800 | 0.15 | regex, shell explanations, translations |
| Long analysis | 1200–1500 | 0.15–0.25 | code review, security audit, text analysis |
| Creative/flexible | 800 | 0.20–0.30 | translations, summaries |

---

## How OpenClaw Skills Actually Work

OpenClaw is an open standard for LLM-mediated skills. Instead of writing Python code,
you write *instructions* in Markdown that tell the LLM what to do. Frank's implementation
goes beyond the basic OpenClaw spec by injecting Frank's full persona into every skill call.

### What happens when a user triggers an OpenClaw skill:

```
User types: "erklaer diesen befehl: find . -name '*.log' -delete"
                              |
                              v
            ┌─────────────────────────────────┐
            │   Command Router                │
            │   (command_router_mixin.py)      │
            │                                 │
            │   match_keywords("erklaer...")   │
            │   → hits "shell-explain" skill  │
            └──────────────┬──────────────────┘
                           |
                           v
            ┌─────────────────────────────────┐
            │   IO Queue                      │
            │   _io_q.put(("skill", {         │
            │     "skill_name": "shell-explain"│
            │     "user_query": "erklaer..."  │
            │   }))                           │
            └──────────────┬──────────────────┘
                           |
                           v
            ┌─────────────────────────────────┐
            │   IO Worker Thread              │
            │   (io_workers_mixin.py)         │
            │                                 │
            │   _show_typing()                │
            │   registry.execute(name, params)│
            │   _hide_typing()                │
            │   _add_message("Frank", output) │
            └──────────────┬──────────────────┘
                           |
                           v
            ┌─────────────────────────────────┐
            │   SkillRegistry.execute()       │
            │   (skills/__init__.py)          │
            │                                 │
            │   ThreadPoolExecutor            │
            │   timeout = max(skill.timeout,  │
            │                 90s)            │
            │   → calls skill.run_fn()        │
            └──────────────┬──────────────────┘
                           |
                           v
            ┌─────────────────────────────────┐
            │   _openclaw_run()               │
            │                                 │
            │   1. Load Frank's persona       │
            │      build_system_prompt(       │
            │        profile="minimal",       │
            │        include_tools=False,     │
            │        include_self_knowledge=  │
            │          False)                 │
            │                                 │
            │   2. Build system prompt:       │
            │      [Frank identity ~4300ch]   │
            │      === AKTIVIERTER SKILL ===  │
            │      [SKILL.md instructions]    │
            │      Bleibe in deiner Persona.  │
            │                                 │
            │   3. POST to Router:            │
            │      http://127.0.0.1:8091/route│
            │      {                          │
            │        "text": user_query,      │
            │        "n_predict": max_tokens, │
            │        "system": system_prompt, │
            │        "force": model (opt.)    │
            │      }                          │
            └──────────────┬──────────────────┘
                           |
                           v
            ┌─────────────────────────────────┐
            │   Router (port 8091)            │
            │   (router/app.py)               │
            │                                 │
            │   1. _pick_model() → qwen/llama │
            │   2. Format prompt:             │
            │      Qwen → ChatML              │
            │      Llama → Instruct           │
            │   3. Forward to LLM backend     │
            │   4. Return generated text      │
            └──────────────┬──────────────────┘
                           |
                           v
            ┌─────────────────────────────────┐
            │   LLM (Ollama, Vulkan GPU)      │
            │                                 │
            │   Processes ~12 tokens/sec      │
            │   Generates response with       │
            │   Frank's personality intact     │
            └─────────────────────────────────┘
```

### Why the Router and not the raw LLM?

The Router (`/route` on port 8091) is the same endpoint the main chat uses.
This gives OpenClaw skills three things for free:

1. **Model selection** — The Router picks Qwen or Llama based on load, memory pressure,
   and request characteristics. No hardcoded model name.
2. **Prompt formatting** — Qwen needs ChatML format, Llama needs Instruct format.
   The Router wraps prompts correctly for whichever model it picks.
3. **Guardrails** — The Router runs safety checks before forwarding to the LLM.

### Why Frank's persona is injected

Without persona injection, OpenClaw skills would respond as a generic assistant —
losing Frank's humor, directness, and personality. The system prompt is assembled as:

```
[Frank identity — ~4300 chars, profile="minimal"]
  - Who Frank is, his creators, ego-construct, personality traits
  - Uncensored, direct, dry humor, no disclaimers

=== AKTIVIERTER SKILL: sysadmin ===
[SKILL.md body — the actual instructions]
  - Domain expertise, output format, rules

Bleibe in deiner Persona. Antworte natuerlich und hilfreich.
```

This ensures Frank sounds like *Frank* even when running a specialized skill.

---

## Architecture Deep Dive

### File Layout

```
skills/
├── __init__.py              # SkillRegistry, _openclaw_run(), _parse_frontmatter()
├── weather.py               # Native: weather lookup (wttr.in)
├── timer.py                 # Native: countdown timer with notification
├── deep_work.py             # Native: Pomodoro/focus session tracker
├── SKILLS.md                # This documentation
├── summarize/
│   └── SKILL.md             # OpenClaw: text summarization
├── sysadmin/
│   └── SKILL.md             # OpenClaw: Linux system diagnostics
├── code-review/
│   └── SKILL.md             # OpenClaw: code review & explanation
├── shell-explain/
│   └── SKILL.md             # OpenClaw: shell command explainer
├── git-workflow/
│   └── SKILL.md             # OpenClaw: git operations helper
├── ...                      # (12 more OpenClaw skills)
└── systemd-helper/
    └── SKILL.md             # OpenClaw: systemd unit helper
```

### SkillRegistry (Singleton)

The `SkillRegistry` is a thread-safe singleton that owns all skill lifecycle:

```
get_skill_registry()          # Double-checked locking singleton
  │
  ├── scan_and_load()         # Called once at startup
  │   ├── glob("*.py")       # Find native skills
  │   │   └── _load_native() # importlib + validate SKILL dict + run()
  │   └── iterdir()          # Find subdirectories
  │       └── _load_openclaw()  # Parse YAML frontmatter + create closure
  │
  ├── match_keywords(text)    # Regex match against all skill keywords
  │                           # Long messages (>80 chars): keyword must be in first 80
  │
  ├── execute(name, params)   # ThreadPoolExecutor with timeout protection
  │                           # min 90s for OpenClaw, 15s for native
  │
  ├── reload(name=None)       # Hot-reload one or all skills from disk
  │                           # NOTE: only reloads SKILL.md metadata, not Python code
  │                           # For code changes: systemctl --user restart aicore-toolboxd
  │
  ├── get_skills_summary()    # Human-readable list (for_prompt=True → compact)
  │
  ├── browse_marketplace()    # Query ClawHub API
  ├── install_from_marketplace()  # Download + security scan + load
  ├── uninstall()             # Remove OpenClaw skill directory
  └── check_updates()         # Compare local vs marketplace versions
```

### Timeout Architecture (Two Layers)

```
User-facing timeout (execute):
  ThreadPoolExecutor.result(timeout=max(skill.timeout_s, 90s))
  → Returns "Skill timed out" error to user

HTTP timeout (_openclaw_run):
  urllib.urlopen(timeout=max(90s, skill.timeout_s * 2))
  → Prevents hung TCP connections to Router
  → Always more generous than the user-facing timeout
```

This separation means: if the LLM is slow, the user gets a clean timeout message.
The HTTP connection doesn't leak because it has its own (larger) timeout.

### Integration Points

```
app.py (overlay startup)
  └── get_skill_registry()        # Initialize on boot, log skill count

command_router_mixin.py (line ~946)
  └── match_keywords(user_input)  # Checked BEFORE generic chat handlers
      └── _io_q.put(("skill", {...}))

worker_mixin.py (IO worker loop)
  ├── "skill"         → _do_skill_worker()
  ├── "skill_reload"  → _do_skill_reload_worker()
  ├── "skill_list"    → _do_skill_list_worker()
  ├── "skill_browse"  → _do_skill_browse_worker()
  ├── "skill_install" → _do_skill_install_worker()
  └── "skill_updates" → _do_skill_updates_worker()

toolboxd.py (HTTP API on port 8096)
  ├── POST /skill/list    → list all installed skills
  ├── POST /skill/run     → execute a skill: {"skill": "name", "params": {...}}
  ├── POST /skill/reload  → hot-reload: {"name": "optional"}
  ├── POST /skill/browse  → search marketplace
  ├── POST /skill/install → install from marketplace
  └── POST /skill/summary → get human-readable summary
```

### Keyword Matching

Skills are matched via compiled regex patterns built from the `keywords` list.
The matching happens in `command_router_mixin.py` BEFORE the message falls through
to generic chat. This gives skills priority over normal LLM conversation.

**Anti-false-positive heuristic:** For messages longer than 80 characters,
the keyword must appear in the first 80 characters. This prevents a philosophical
question about "Prozesse" from accidentally triggering the sysadmin skill.

**First-match wins:** Skills are checked in `list_all()` order (alphabetical by
load order). If "analysiere den commit" matches both `essence-distiller` ("analysiere")
and `conventional-commits` ("commit"), whichever is first in the registry wins.

### Security Scanning (Marketplace)

Before installing a skill from ClawHub, `_security_scan_skill()` checks for:

- **Dangerous patterns**: `subprocess`, `os.system`, `eval()`, `exec()`, `sudo`,
  `rm -rf`, `shutil.rmtree`, file writes, network requests (`urllib`, `requests`, `curl`, `wget`)
- **Prompt injection**: "ignore previous instructions", role overrides,
  ChatML injection (`<|im_start|>`), instruct format injection (`[INST]`)

Risk scoring: each warning adds 0.3 to the risk level (capped at 1.0).
Skills with risk >= 0.6 are blocked. Skills with risk 0.3–0.6 install with a warning.

### Chat Commands

| Command | Action |
|---------|--------|
| `skill reload` | Hot-reload all skills from disk |
| `welche skills hast du` | Show installed skills list |
| `openclaw skills` | Browse ClawHub marketplace |
| `fuege skill X hinzu` | Install skill from marketplace |
| `entferne skill X` | Uninstall an OpenClaw skill |
| `skill updates` | Check for available updates |

---

## Quick Reference: Adding a New Skill

### Native (Python) — for deterministic tasks

```bash
# 1. Create the file
vim skills/my_skill.py

# 2. Define SKILL dict + run() function (see examples above)

# 3. Reload
curl -X POST http://127.0.0.1:8096/skill/reload -d '{}' -H "Content-Type: application/json"
# Or type "skill reload" in Frank's chat
```

### OpenClaw (SKILL.md) — for LLM-mediated tasks

```bash
# 1. Create directory + file
mkdir skills/my-skill
vim skills/my-skill/SKILL.md

# 2. Write YAML frontmatter + instructions (see examples above)

# 3. Reload
curl -X POST http://127.0.0.1:8096/skill/reload -d '{}' -H "Content-Type: application/json"
# Or type "skill reload" in Frank's chat
```

### Testing via API

```bash
# List all skills
curl -s -X POST http://127.0.0.1:8096/skill/list -d '{}' -H "Content-Type: application/json"

# Run a specific skill
curl -s -X POST http://127.0.0.1:8096/skill/run \
  -H "Content-Type: application/json" \
  -d '{"skill": "my-skill", "params": {"user_query": "test input"}}'
```
