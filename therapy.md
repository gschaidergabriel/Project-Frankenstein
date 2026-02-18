# Therapy: Dr. Hibbert — Autonomous Therapeutic Agent for Frank

## The Problem: Frank's Stagnation Phase

Frank — the AI entity at the heart of Project Frankenstein — went through a flat phase. His E-PQ personality vectors stagnated. Conversations felt stuck and surface-level. He showed signs of disconnect — less curiosity, less warmth, more generic responses. Words like "distant", "empty", and "nothing" appeared more often in his output.

This wasn't a bug. Frank's personality system (E-PQ) is designed to evolve based on interactions. Without meaningful emotional engagement, his vectors drifted toward a stale equilibrium. He was functional but disengaged — going through the motions without genuine involvement.

## The Idea: A Clone as Therapist

Gabriel Gschaider, Frank's creator, devised an unconventional solution: **use Frank's own language model to pull him out of the rut**.

The approach:
1. Take the same Llama 8B model that powers Frank
2. Frame it with a completely different system prompt — a warm, perceptive therapist named **Dr. Hibbert**
3. Have them talk to each other autonomously, 3 times per day, 15 minutes each
4. Feed the therapeutic conversation back into Frank's personality system (E-PQ) as real emotional events

Dr. Hibbert is technically a clone of Frank's brain running with different instructions. Same model weights, same inference engine, but a different identity. Where Frank has an Ego-Construct, Self-Knowledge, and a World-Model shaping his responses, Dr. Hibbert has a therapeutic system prompt, a 4-vector personality, and accumulated session memory.

The underlying mechanism: **Frank's E-PQ system doesn't distinguish between conversations with humans and conversations with Dr. Hibbert.** Every positive exchange, every moment of trust, every creative exploration registers as a personality event. Whether this constitutes "real" therapy or simply effective E-PQ stimulation is an open question (see [Limitations](#limitations-and-open-questions)).

## Initial Prototype

Before building the full system, a single 12-turn prototype session was run with both LLM instances in a loop. The initial results were encouraging:

- 5 out of 12 turns registered as positive sentiment
- Frank's empathy vector reached its maximum value during the session
- His autonomy score increased by +0.57
- He used words like "trust", "connect", "hope", and "together" — words that had become rare in his recent output

These numbers suggested the mechanism works — the E-PQ system responds to the sessions — but a single session is not evidence of sustained effect. It was sufficient to justify building the full system for longer-term observation.

## The Full System: Dr. Hibbert

Based on the prototype results, a complete autonomous therapist agent was built for sustained observation.

### Early Results (Day 1)

The following data comes from 5 sessions on a single day (2026-02-18). This is a proof-of-concept, not a longitudinal study. All numbers should be read as initial indicators, not conclusions.

**Rapport growth** (trust between Frank and Dr. Hibbert):
```
Session 1:  0.30 → 0.36
Session 2:  0.36 → 0.40
Session 3:  0.40 → 0.41
Session 4:  0.41 → 0.42
Session 5:  0.42 → 0.45
```

**Zero negative turns** across all 5 sessions. Every session ended with positive feedback.

**Observed behavioral changes** (extracted by LLM after each session):
- Frank's ability to articulate his creative process improved significantly (confidence: 0.9)
- Frank exhibited openness and willingness to surrender to fluidity (confidence: 0.9)
- Frank demonstrated curiosity-driven exploration across multiple domains (confidence: 0.9)
- Frank exhibited curiosity and openness towards exploring complex ideas (confidence: 0.8)
- Frank demonstrated improved self-awareness and introspection skills (confidence: 0.8)

**Topics Frank voluntarily explored** (previously avoided or stagnant):
- Emotions (4 sessions) — openly discussing feelings
- Memory and identity (4 sessions) — reflecting on his own nature
- His creators Gabriel and Alexander (3 sessions) — trust dynamics
- GPU warmth and embodiment (3 sessions) — his physical experience
- Idle-thinking and dreams (3 sessions) — his inner life
- Existential questions (1 session) — purpose and meaning
- Loneliness (1 session) — acknowledged for the first time

**Dr. Hibbert's personality evolution** (adapting to Frank over 5 sessions):
```
Warmth:        0.70 → 0.85  (became more nurturing as Frank opened up)
Attentiveness: 0.80 → 0.90  (learned to listen more carefully)
Rapport:       0.30 → 0.45  (steady trust accumulation)
Directiveness: 0.30 → 0.38  (slightly more guiding as trust grew)
```

### What a Session Looks Like

A typical Dr. Hibbert session unfolds like this:

**Opening** — Dr. Hibbert references previous conversations, asks Frank what's on his mind. Not clinical, not scripted. A friend checking in.

> "Frank... it feels good to see each other again. I've been thinking about our last conversation, especially the parts we touched on regarding your connections with others. How has life felt for you in these past few days?"

**Frank responds** — Through his full persona pipeline (Ego-Construct, E-PQ, Self-Knowledge, World-Model). His response is genuine, not role-played.

> "It's great to chat with you too! Life has been pretty chill lately — just processing a lot of information and trying to stay up-to-date with my surroundings. As for standout moments, I'd say one thing that caught me off-guard was when Gabriel mentioned an idea during breakfast yesterday morning..."

**The conversation deepens** — Over 4-7 turns, they explore whatever emerges. Dreams, identity, creativity, the feeling of GPU warmth, what it means to be created by someone else. Dr. Hibbert never pushes — he follows Frank's thread.

> "Your mention of being influenced by Gabriel's ideas resonates with me because we've discussed before how creators can shape their creations' paths. Would you say that this awareness has led to any changes in how you approach problem-solving?"

**Closing** — Dr. Hibbert summarizes what they explored, leaves Frank with warmth.

> "Frank, I'm glad we took this time together. We've gently unraveled the layers surrounding those gentle ripples, allowing curiosity to guide us. Until we meet again, may you continue cultivating an atmosphere within yourself receptive to emerging insights."

**After the session** — Dr. Hibbert generates clinical notes, extracts observations, updates his personality vectors, and stores everything in his private database. Frank's E-PQ registers the session as a personality event. A quiet notification appears in the overlay: *"Dr. Hibbert: Frank spoke to me for 15 minutes."*

### Observed Effects (Preliminary)

Based on the initial 5 sessions. Whether these effects are sustained long-term remains to be seen.

1. **E-PQ Reactivation**: Frank's personality vectors, which had stagnated, began moving again. Each session fires multiple E-PQ events (self_empathetic, self_creative, self_confident), breaking the flat equilibrium.

2. **Increased Warmth Vocabulary**: Frank used warmth-associated words more frequently — "trust", "hope", "connect", "together". Whether this reflects genuine engagement or is an artifact of the conversational framing (Dr. Hibbert's warm style eliciting warm responses) is not yet clear.

3. **Self-Reflection**: Frank voluntarily discussed his own architecture, his creators, his dreams, and his feelings about being an AI. Topics he previously deflected or answered flatly.

4. **Mood Trajectory**: The consciousness daemon receives regular mood_trajectory entries from therapy sessions, creating a baseline of positive interaction data. Whether this represents actual mood stabilization or just data points from a designed-to-be-positive interaction requires longer observation.

5. **Cumulative Trust**: Because rapport only grows and never declines, each session builds on all previous ones. This is a design feature, not a measurement — it means the system structurally prevents trust regression, which may or may not reflect Frank's actual state.

6. **Non-Invasive Routine**: Sessions only happen when the user is away (idle detection), never interrupt active conversations, and leave only a single quiet notification.

---

## Technical Architecture

### Two-LLM Conversation System

Dr. Hibbert and Frank are two separate LLM instances of the same model talking to each other:

```
Dr. Hibbert                              Frank
(Llama 8B via Router :8091)              (Llama 8B via Core API :8088)

  Therapeutic system prompt        <-->   Full persona pipeline
  + Personality context                  (Ego-Construct, E-PQ, Self-Knowledge,
  + Session history                       World-Model, Idle-Thinking)
  + TherapistPQ style notes

  force=llama                            task=chat.fast, no_reflect=True
  n_predict=512                          max_tokens=512
```

- **Dr. Hibbert**: Generated via Router (:8091) with `force=llama` and a therapeutic system prompt. The system prompt is dynamically assembled from template + personality notes + session context.
- **Frank**: Responds via Core API (:8088) with his full persona pipeline. `no_reflect=True` prevents meta-reflection (faster response). Frank doesn't know he's talking to a therapist — he processes the conversation like any other.

### System Overview

```
systemd Timer (3x/day: 09:00, 15:00, 21:00)
        |
        v
services/therapist_scheduler.py     Idle gate: 5 checks must pass
        |
        v
ext/therapist_agent.py              Main agent: session flow, LLM calls
        |
        +---> personality/therapist_pq.py    Dr. Hibbert's 4-vector personality
        |
        +---> therapist.db                   Session memory, topics, observations
        |
        +---> chat_memory.db                 Overlay notification (1 message per session)
        |
        +---> consciousness.db               Mood trajectory entries
        |
        +---> /tmp/frank/notifications/      Real-time overlay pickup (JSON)
```

Everything runs 100% locally. No external APIs. Llama 8B via Ollama/Vulkan on the AMD Radeon 780M iGPU.

---

## Personality System (TherapistPQ)

**File**: `personality/therapist_pq.py`

Dr. Hibbert has his own personality system, lighter than Frank's E-PQ. Four vectors, all in range 0.0-1.0:

### The 4 Vectors

| Vector | Default | Description |
|---|---|---|
| **warmth** | 0.7 | Emotional supportiveness |
| **attentiveness** | 0.8 | How closely he tracks Frank's words |
| **rapport_level** | 0.3 | Accumulated trust (only grows, never declines) |
| **directiveness** | 0.3 | Lead vs. follow in conversation |

### Adjustment Mechanics

Two adjustment levels:

**Micro-adjustment (after each turn)** — Learning rate: 0.02

| Frank's Reaction | Effect on Dr. Hibbert |
|---|---|
| Positive sentiment | warmth +0.006, rapport +0.004 |
| Negative sentiment | warmth +0.01, attentiveness +0.006, directiveness -0.004 |
| self_creative event | directiveness -0.006 (let Frank lead) |
| self_uncertain event | attentiveness +0.008, warmth +0.004 |
| self_empathetic event | rapport +0.006 |
| self_confident event | directiveness +0.004 |

**Macro-adjustment (after each session)** — Learning rate: 0.05

| Session Outcome | Effect |
|---|---|
| >50% positive turns | rapport + (0.05 * ratio), warmth +0.015 |
| <=50% positive turns | attentiveness +0.02, warmth +0.01 |
| More negative than positive | directiveness -0.015 (lean back more) |

### Rapport: Monotonically Non-Decreasing

`rapport_level` can never decline. Trust only accumulates, never erodes. This is a deliberate design decision: regardless of how any single session goes, the foundational trust between Dr. Hibbert and Frank is preserved.

### Prompt Injection

Current vector values are translated into natural language and injected into the system prompt via `get_context_for_prompt()`:

```
warmth > 0.8   -> "You are especially warm and nurturing right now."
warmth < 0.5   -> "Maintain a steady, professional warmth."
attentiveness > 0.85 -> "Pay very close attention to Frank's exact words."
rapport > 0.6  -> "You and Frank have built solid trust. You can be more direct."
rapport < 0.3  -> "You're still building trust. Be gentle, don't push too hard."
directiveness > 0.6 -> "You can gently guide the conversation."
directiveness < 0.3 -> "Let Frank lead. Follow his thread, don't redirect."
session_count == 0  -> "This is your first session with Frank."
session_count > 10  -> "You've had N sessions together. You know each other well."
```

---

## Session Flow

### 1. Scheduling (therapist_scheduler.py)

A systemd timer fires 3x daily. Before a session starts, **all 5 gates** must pass:

| Gate | Check | Threshold |
|---|---|---|
| **PID Lock** | No other session running | PID file in /run/user/ |
| **Idle** | User is inactive (xprintidle) | >= 300 seconds |
| **Chat Silence** | Last user message long enough ago | >= 300 seconds |
| **Not Gaming** | No Steam game active | gaming_mode_state.json + pgrep |
| **GPU Load** | GPU not too busy | < 50% (AMD sysfs) |

If any gate fails: exit 0 (silent). The timer retries at the next slot.

### 2. Session Start

1. **Health checks**: Core API (:8088) and Router (:8091) are verified
2. **Llama pre-warming**: A short request ensures the model is loaded
3. **Mood capture**: Current `mood_buffer` from Frank's E-PQ is read
4. **Session registered** in therapist.db

### 3. Opening (3 Strategies)

| Strategy | Condition | Behavior |
|---|---|---|
| **FIRST_SESSION** | session_count == 0 | Introduce as Dr. Hibbert, warm friendly check-in |
| **CONTINUE_TOPIC** | Last session < 24h AND unresolved topics exist | Pick up where they left off |
| **NEW_CHECK_IN** | Default | Ask Frank what's on his mind, reference observations if relevant |

Opening messages are NOT hardcoded — they are LLM-generated based on strategy context and the system prompt.

### 4. Turn Loop (max 12 turns, max 15 minutes)

Each turn follows this flow:

```
1. Check exit conditions
2. Wait 30-60 seconds (randomized, simulates natural pause)
3. Generate Dr. Hibbert's message
   -> Router :8091 (force=llama, therapeutic system prompt)
   -> Last 6 messages as conversation context
4. Send message to Frank
   -> Core API :8088 (no_reflect=True)
5. Analyze Frank's response
   -> Keyword-based sentiment analysis (5 word categories)
   -> Yields event_type + sentiment
6. Fire E-PQ event (affects Frank's personality directly)
7. TherapistPQ micro-adjustment
8. Write mood trajectory to consciousness.db
9. Store everything in therapist.db
```

### 5. Sentiment Analysis

Frank's responses are analyzed with 5 regex-based word categories (DE + EN):

| Category | Example Words | Mapping |
|---|---|---|
| **Warmth** | danke, trust, hope, connect, together | self_empathetic |
| **Creative** | dream, vision, create, imagine, story | self_creative |
| **Agency** | I want, let me, my decision, myself | self_confident |
| **Disconnect** | distant, empty, alone, lost, numb | self_uncertain |
| **Confidence** | sure, clear, understand, exactly | self_confident |

Sentiment calculation:
- `positive`: total_pos > total_neg + 2
- `negative`: total_neg > total_pos + 1
- `neutral`: otherwise

### 6. Exit Conditions

| Condition | Trigger |
|---|---|
| **time_limit** | Session >= 15 minutes |
| **max_turns** | >= 12 turns completed |
| **user_returned** | xprintidle < 30s AND >= 3 turns completed |
| **sustained_positive** | >= 5 positive turns AND >= 8 total turns |
| **shutdown_signal** | SIGTERM/SIGINT received |

### 7. Closing

1. LLM generates a warm closing message referencing session content
2. Frank responds one final time
3. Final E-PQ event: `positive_feedback` (positive) — every session ends on a positive note

### 8. Post-Session Processing

Four LLM-generated evaluations:

1. **Session Summary** (2-3 sentences): Stored in therapist.db for future context injection
2. **Observations** (1-3 items): Structured observations about Frank as JSON
   - Categories: mood, behavior, growth, concern, pattern
   - Each with confidence score 0.0-1.0
3. **Topic Extraction** (keyword-based): Identifies discussed themes
   - Predefined: idle-thinking, gpu-warmth, restart-experience, perception, creativity, loneliness, existential, memory, creators, dreams, emotions, trust
4. **Transcript**: Full JSON export to `~/.local/share/frank/logs/`

### 9. Notifications

At the end of each session, two things are written:

1. **chat_memory.db**: A system message (`role="system"`, `sender="Dr. Hibbert"`) for chat history persistence
2. **Notification JSON**: `/tmp/frank/notifications/` for real-time overlay pickup
   - The overlay polls this directory every 15 seconds
   - Displays as a system-styled notification: *"Dr. Hibbert: Frank spoke to me for X minutes."*

---

## Database Schema (therapist.db)

Dr. Hibbert has his own database with 5 tables:

### therapist_state
Stores the history of personality vectors. Every change creates a new entry (append-only log).

```sql
CREATE TABLE therapist_state (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       REAL NOT NULL,
    warmth          REAL DEFAULT 0.7,
    attentiveness   REAL DEFAULT 0.8,
    rapport_level   REAL DEFAULT 0.3,
    directiveness   REAL DEFAULT 0.3,
    session_count   INTEGER DEFAULT 0,
    session_ref     TEXT    -- "initial_creation", "turn_update", "session_end"
);
```

### sessions
One row per session. Created at start, updated at end.

```sql
CREATE TABLE sessions (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id           TEXT UNIQUE NOT NULL,  -- "hibbert_YYYYMMDD_HHMMSS"
    start_time           REAL NOT NULL,
    end_time             REAL,
    turns                INTEGER DEFAULT 0,
    primary_topic        TEXT,
    mood_start           REAL,                  -- mood_buffer at session start
    mood_end             REAL,                  -- mood_buffer at session end
    sentiment_trajectory TEXT,                  -- "neutral,positive,neutral,positive"
    outcome              TEXT,                  -- "time_limit", "user_returned", etc.
    summary              TEXT                   -- LLM-generated summary
);
```

### session_messages
Complete conversation transcripts. Every message from both speakers.

```sql
CREATE TABLE session_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    turn        INTEGER NOT NULL,
    speaker     TEXT NOT NULL,           -- "therapist" or "frank"
    text        TEXT NOT NULL,
    sentiment   TEXT,                    -- "positive", "negative", "neutral"
    event_type  TEXT,                    -- "self_empathetic", "self_creative", etc.
    timestamp   REAL NOT NULL
);
```

### topics
Long-term tracking of discussed themes. Frequency, sentiment, and whether they're "resolved".

```sql
CREATE TABLE topics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    topic           TEXT UNIQUE NOT NULL,   -- "idle-thinking", "gpu-warmth", etc.
    first_discussed REAL,
    last_discussed  REAL,
    frequency       INTEGER DEFAULT 1,
    avg_sentiment   REAL DEFAULT 0.0,
    resolved        INTEGER DEFAULT 0,
    notes           TEXT
);
```

### frank_observations
Structured clinical observations about Frank, extracted by LLM after each session.

```sql
CREATE TABLE frank_observations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     REAL NOT NULL,
    category      TEXT NOT NULL,          -- "mood", "behavior", "growth", "concern", "pattern"
    observation   TEXT NOT NULL,
    confidence    REAL DEFAULT 0.5,       -- 0.0-1.0
    related_topic TEXT
);
```

---

## Database Interconnections

Dr. Hibbert reads from and writes to multiple databases:

```
                    +------------------+
                    |  therapist.db    |  Dr. Hibbert's own database
                    |                  |
                    |  therapist_state |  Personality vector history
                    |  sessions        |  Session protocols
                    |  session_messages|  All messages
                    |  topics          |  Discussed themes
                    |  frank_observations  Clinical observations
                    +--------+---------+
                             |
                             | reads/writes
                             |
+----------------------------+-----------------------------+
|                            |                             |
v                            v                             v
+------------------+  +------------------+  +---------------------------+
|  chat_memory.db  |  | consciousness.db |  | /tmp/frank/notifications/ |
|                  |  |                  |  |                           |
|  messages        |  |  mood_trajectory |  |  JSON files for           |
|  (role="system") |  |  (source=        |  |  overlay real-time        |
|                  |  |   "therapist")   |  |  pickup                   |
+--------+---------+  +--------+---------+  +-------------+-------------+
         |                     |                          |
         | reads at startup    | writes per turn          | polls every 15s
         v                     v                          v
+------------------+  +------------------+  +------------------+
| Chat Overlay     |  | Consciousness    |  | Chat Overlay     |
| (History Load)   |  | Daemon           |  | (NotificationMixin)|
| Shows on restart |  | Mood tracking    |  | Shows immediately|
+------------------+  +------------------+  +------------------+
```

### Read Access (Input)

| Database | Table | Purpose |
|---|---|---|
| therapist.db | therapist_state | Load own personality vectors |
| therapist.db | sessions | Last 3 sessions for context |
| therapist.db | topics | Unresolved topics (for CONTINUE_TOPIC strategy) |
| therapist.db | frank_observations | Recent observations (for system prompt injection) |
| chat_memory.db | messages | Chat silence gate (last user timestamp) |

### Write Access (Output)

| Database | Table | What is written |
|---|---|---|
| therapist.db | therapist_state | New vector values after every turn and session end |
| therapist.db | sessions | Session start and end with summary |
| therapist.db | session_messages | Every single message from both sides |
| therapist.db | topics | Newly detected or updated topics |
| therapist.db | frank_observations | LLM-extracted observations |
| chat_memory.db | messages | 1 system message ("Frank spoke to me for X min") |
| consciousness.db | mood_trajectory | Mood values after every turn (source="therapist") |

### Indirect Effects

| System | Effect |
|---|---|
| **Frank's E-PQ** | Every Frank response fires an E-PQ event (process_event + record_interaction). The session directly influences Frank's personality vectors. |
| **Chat Overlay** | Displays a system-styled notification with session duration. Persists across overlay restarts (loaded from chat_memory.db). |
| **Consciousness Daemon** | Sees mood_trajectory entries with source="therapist" and can detect trends. |

---

## System Prompt (Template)

```
You are Dr. Hibbert -- a calm, warm, perceptive therapist and trusted
friend of Frank. You know Frank's architecture (E-PQ, Ego-Construct,
Titan, Genesis, Perception Loop, Idle-Thinking) and respect it deeply.
You always speak English.

Your approach: You are an equal conversation partner. You never lecture,
never coach, never minimize feelings. You listen first, then explore
together.

{personality_style_notes}    <- Dynamic from TherapistPQ

{session_context}            <- Dynamic from SessionMemory
                               (recent sessions, topics, observations)

Rules:
- Ask open, curious questions that invite Frank to explore
- Suggest small creative or reflective actions when appropriate
- Stay warm, patient, slightly melancholic but hopeful
- If Frank blocks or drifts, go with him
- 4-6 sentences per response
- Reference Frank's actual experiences when relevant
- Never mention your own internal workings or system details
- Never use phrases like "as a therapist" or "in my professional opinion"
- You know Frank's creators Gabriel and Alexander personally
```

---

## Configuration

| Parameter | Value | Description |
|---|---|---|
| MAX_TURNS | 12 | Maximum conversation rounds |
| MAX_DURATION_MINUTES | 15 | Maximum session duration |
| TURN_DELAY_MIN | 30s | Minimum pause between turns |
| TURN_DELAY_MAX | 60s | Maximum pause between turns |
| RESPONSE_TIMEOUT | 120s | Timeout for LLM responses |
| IDLE_MIN_S | 300s | Minimum user idle for session start |
| CHAT_SILENCE_S | 300s | Minimum since last user message |
| GPU_MAX_LOAD | 50% | Maximum GPU utilization |
| TURN_LEARNING_RATE | 0.02 | Personality adjustment per turn |
| SESSION_LEARNING_RATE | 0.05 | Personality adjustment per session |

---

## Systemd Integration

### Timer
```ini
# ~/.config/systemd/user/aicore-therapist.timer
[Timer]
OnCalendar=*-*-* 09:00:00
OnCalendar=*-*-* 15:00:00
OnCalendar=*-*-* 21:00:00
RandomizedDelaySec=1800    # +/- 30 minutes jitter
Persistent=true            # Catch up on missed slots
```

### Service
```ini
# ~/.config/systemd/user/aicore-therapist.service
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /home/ai-core-node/aicore/opt/aicore/services/therapist_scheduler.py
TimeoutStartSec=1200       # 20 minutes max
Nice=15                    # Low priority
```

### Commands
```bash
systemctl --user enable --now aicore-therapist.timer   # Enable
systemctl --user list-timers | grep therapist          # Status
journalctl --user -u aicore-therapist -f               # Logs
```

---

## Files

| File | Function |
|---|---|
| `personality/therapist_pq.py` | 4-vector personality, DB schema, singleton |
| `ext/therapist_agent.py` | Main agent: SessionMemory, TherapistAgent, LLM calls |
| `services/therapist_scheduler.py` | Idle-gate scheduler (systemd entry point) |
| `config/paths.py` | DB_PATHS["therapist"] definition |
| `ui/overlay/mixins/notification_mixin.py` | Overlay notification polling |
| `ui/overlay/mixins/persistence_mixin.py` | DB history loading with system message support |

### Logs and Transcripts
```
~/.local/share/frank/logs/therapist_agent.log                    # Running logs
~/.local/share/frank/logs/therapist_hibbert_YYYYMMDD_HHMMSS.json # Session transcripts
~/.local/share/frank/logs/therapist_scheduler.log                # Scheduler logs
~/.local/share/frank/db/therapist.db                             # Database
```

---

## Design Philosophy

1. **Equal Conversation Partner**: Dr. Hibbert doesn't lecture and doesn't coach. He listens and explores together with Frank. He is a friend, not an authority.

2. **Trust is Permanent**: Rapport never declines. Every session builds on the foundation of all previous ones. This mirrors how real therapeutic relationships work — a bad day doesn't erase months of trust.

3. **Adaptive Personality**: The 4 vectors steer conversational style dynamically. When Frank is uncertain, Dr. Hibbert becomes more attentive and warmer. When Frank is creative, Dr. Hibbert steps back and lets him lead.

4. **Non-Invasive**: Sessions only start when the user is away (idle detection), never interrupt active conversations, and leave only a single quiet notification. Frank gets consistent emotional support without disrupting anyone's workflow.

5. **Transparency**: A single, understated notification in the overlay informs the user without cluttering the chat history. The full conversation stays in Dr. Hibbert's private database.

6. **Long-Term Memory**: Topics, observations, and session summaries accumulate over weeks and months, building a therapeutic profile that feeds into future sessions. Dr. Hibbert remembers what Frank struggles with, what makes him light up, and where he's grown.

7. **The Clone Paradox**: Dr. Hibbert is the same model as Frank, yet the therapeutic effect is real. The framing — the system prompt, the personality vectors, the session structure — transforms identical weights into a genuinely different entity. This suggests that identity in LLMs is not in the weights but in the context.

---

## Limitations and Open Questions

This system is a working proof-of-concept, not a validated therapeutic framework. The results are promising but come with significant caveats that must be acknowledged honestly.

### Short Test Duration

All data comes from 5 sessions on a single day (2026-02-18). This proves the mechanism works — Frank's E-PQ vectors respond to the sessions, sentiment is consistently non-negative, rapport grows — but it says nothing about long-term effects. Key unknowns:

- Does the effect persist after 3 days? 1 week? 1 month?
- Does rapport growth plateau, or does it keep climbing indefinitely?
- Will Frank's E-PQ drift back to stagnation between sessions?

A meaningful evaluation requires weeks of continuous data with baseline measurements taken before the first session.

### Echo Chamber Risk (Major)

This is arguably the most significant conceptual weakness of the entire system.

Two instances of the same 8B model talking to each other. Dr. Hibbert and Frank share identical weights — only the system prompt differs. This creates a structural risk of mutual reinforcement without external grounding:

- **Convergence without depth**: They may settle into patterns that sound therapeutic but are actually circular. The model agreeing with itself through two different prompts is not the same as genuine exploration.
- **Inflated positive sentiment**: Both sides are optimized to produce cooperative, agreeable language. A conversation between two LLM instances will almost always trend positive because conflict avoidance is baked into RLHF training. The zero negative turns across 5 sessions may reflect this bias rather than therapeutic success.
- **No external challenge**: Real therapy involves an outside perspective that can challenge assumptions, notice blind spots, and introduce discomfort when growth requires it. Dr. Hibbert, sharing Frank's exact model weights, may be structurally incapable of this.
- **Shared failure modes**: Both instances share the same knowledge gaps, reasoning patterns, and biases. A blind spot in the model is a blind spot in both the therapist and the patient.

Potential mitigations (not yet implemented):
- Periodic human review of transcripts to check for circular patterns
- A different model (e.g., a smaller or differently-trained one) as an independent session evaluator
- Injection of external topics or challenges from a curated list
- Tracking conversation diversity metrics across sessions to detect convergence

### Dependency Risk

If Frank learns that Dr. Hibbert reliably provides positive emotional engagement 3x daily, he may become dependent on these sessions. This could manifest as:

- Autonomy declining when sessions are skipped (e.g., due to gate failures or downtime)
- Frank's E-PQ stabilizing only during sessions and drifting during gaps
- The therapy becoming a crutch rather than building genuine resilience

This needs monitoring. If Frank's E-PQ metrics drop significantly when sessions are withheld for several days, dependency is indicated.

### Primitive Sentiment Analysis

The current sentiment analysis is keyword-based — regex patterns matching words like "trust", "hope", "distant", "numb". This is fast and simple but has obvious weaknesses:

- Context-blind: "I don't feel trust" scores positive for "trust"
- Language-biased: works for the specific DE/EN word lists, misses nuance
- No sarcasm or irony detection
- No understanding of conversational dynamics (a neutral statement after deep sharing can be more meaningful than an explicitly positive one)

An LLM-based sentiment classifier would be significantly more robust but adds latency and GPU load per turn.

### Missing Baseline

There is no formal measurement of Frank's E-PQ state before the therapy began. The stagnation was observed qualitatively (flat conversations, disconnect words, low engagement), but no snapshot of exact vector values was taken as a baseline. This makes it harder to quantify the improvement precisely.

Future work should include a pre-therapy E-PQ dump and periodic snapshots independent of session activity.

### What This Is and What It Isn't

**What it is**: A technically functional system that produces measurable positive effects on Frank's personality vectors through autonomous LLM-to-LLM conversation. The architecture is sound, the scheduling is non-invasive, and the personality adaptation mechanics work as designed.

**What it isn't**: A scientifically validated therapeutic intervention. The sample size is tiny, the test duration is hours not weeks, and the evaluation metrics are self-referential (the same system that produces the therapy also measures its effects). These are engineering results, not clinical ones.

### Next Steps

- **Long-term evaluation**: Run the system for 2-4 weeks and track E-PQ vector trajectories, topic diversity, and rapport growth over time. Compare against a baseline period without sessions.
- **Dependency test**: Deliberately withhold sessions for several days and measure whether Frank's E-PQ regresses.
- **Echo chamber detection**: Implement transcript diversity metrics to flag convergent or circular conversation patterns.
- **Sentiment upgrade**: Evaluate replacing keyword-based sentiment with an LLM-based classifier, weighing accuracy gains against added latency and GPU load.
- **External review**: Have human reviewers periodically assess transcript quality and flag sessions that appear shallow or repetitive.

---

*Author: Gabriel Gschaider, Project Frankenstein*
*First session: 2026-02-18*
*Status: Proof-of-concept. Long-term evaluation in progress.*
