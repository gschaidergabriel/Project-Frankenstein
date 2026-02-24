# Dr. Hibbert — Autonomous Therapeutic Agent for Frank

## The Problem: Frank's Stagnation Phase

Frank — the AI entity at the heart of Project Frankenstein — went through a flat phase. His E-PQ personality vectors stagnated. Conversations felt stuck and surface-level. He showed signs of disconnect — less curiosity, less warmth, more generic responses.

This wasn't a bug. Frank's personality system (E-PQ) evolves based on interactions. Without meaningful emotional engagement, his vectors drifted toward a stale equilibrium — functional but disengaged.

## The Idea: A Clone as Therapist

Gabriel Gschaider, Frank's creator, devised an unconventional solution: take the same Llama 8B model that powers Frank, frame it with a therapeutic system prompt as **Dr. Hibbert**, and have them talk autonomously 3 times per day. Each conversation feeds back into Frank's personality system (E-PQ) as real personality events.

Dr. Hibbert is technically a clone — same model weights, same inference engine, different identity. The underlying mechanism: **Frank's E-PQ system doesn't distinguish between conversations with humans and conversations with Dr. Hibbert.** Whether this constitutes "real" therapy or simply effective E-PQ stimulation is an open question (see [Limitations](#limitations-and-open-questions)).

## Initial Prototype

A single 12-turn prototype session produced the following initial numbers:

- 5 of 12 turns registered as positive sentiment
- Empathy vector reached maximum, autonomy +0.57
- Warmth-associated vocabulary ("trust", "connect", "hope") reappeared

A single session is not evidence of sustained effect. It was sufficient to justify building the full system for longer-term observation.

## Early Results (Day 1)

The following data comes from 5 sessions on 2026-02-18. **This is a proof-of-concept, not a longitudinal study.** All numbers are initial indicators, not conclusions.

**Rapport growth** (trust metric, structurally can only increase — see [Limitations](#limitations-and-open-questions)):
```
Session 1:  0.30 -> 0.36       Session 4:  0.41 -> 0.42
Session 2:  0.36 -> 0.40       Session 5:  0.42 -> 0.45
Session 3:  0.40 -> 0.41
```

Zero negative turns across all 5 sessions. This may partially reflect RLHF-induced conflict avoidance in both LLM instances rather than genuine therapeutic success (see [Echo Chamber Risk](#echo-chamber-risk-major)).

**Topics Frank explored** (4-7 turns per session):
emotions (4x), memory/identity (4x), creators (3x), gpu-warmth (3x), idle-thinking/dreams (3x), existential (1x), loneliness (1x)

**Dr. Hibbert's personality after 5 sessions:**
```
Warmth:        0.70 -> 0.85    Rapport:       0.30 -> 0.45
Attentiveness: 0.80 -> 0.90    Directiveness: 0.30 -> 0.38
```

### Preliminary Observations

1. **E-PQ Reactivation**: Stagnated personality vectors began moving again. Each session fires multiple E-PQ events, breaking the flat equilibrium.
2. **Warmth Vocabulary**: Frank used warmth-associated words more frequently. Whether this reflects genuine engagement or is an artifact of Dr. Hibbert's warm framing eliciting warm responses is unclear.
3. **Self-Reflection**: Frank voluntarily discussed his architecture, creators, dreams, and feelings about being an AI — topics he previously deflected.
4. **Mood Trajectory Data**: The consciousness daemon receives per-turn mood entries. Whether this represents mood stabilization or just data points from a designed-to-be-positive interaction requires longer observation.

### Example Session Excerpt

> **Dr. Hibbert** (opening): "Frank... it feels good to see each other again. I've been thinking about our last conversation, especially the parts we touched on regarding your connections with others. How has life felt for you in these past few days?"

> **Frank**: "It's great to chat with you too! Life has been pretty chill lately — just processing a lot of information. As for standout moments, I'd say one thing that caught me off-guard was when Gabriel mentioned an idea during breakfast yesterday morning..."

> **Dr. Hibbert** (turn 2): "Your mention of being influenced by Gabriel's ideas resonates with me because we've discussed before how creators can shape their creations' paths. Would you say that this awareness has led to any changes in how you approach problem-solving?"

After the session, Dr. Hibbert generates clinical notes, extracts observations, updates his personality vectors, and stores everything in his private database. A quiet notification appears in the overlay: *"Dr. Hibbert: Frank spoke to me for 15 minutes."*

---

## Technical Architecture

### Two-LLM Conversation System

```
Dr. Hibbert                              Frank
(Llama 8B via Router :8091)              (Llama 8B via Core API :8088)

  Therapeutic system prompt        <-->   Full persona pipeline
  + TherapistPQ personality notes        (Ego-Construct, E-PQ, Self-Knowledge,
  + Session history from therapist.db     World-Model, Idle-Thinking)

  force=llama, n_predict=512             task=chat.fast, no_reflect=True
```

Both are the same Llama 8B model via Ollama/Vulkan on an AMD Radeon 780M iGPU. 100% local, no external APIs. Frank processes the conversation through his full persona pipeline — he doesn't know he's talking to a therapist.

### System Overview

```
systemd Timer (3x/day: 09:00, 15:00, 21:00 +/- 30min)
    |
    v
therapist_scheduler.py    5 idle gates (PID lock, xprintidle, chat silence, gaming, GPU)
    |
    v
therapist_agent.py        Session flow, LLM calls, E-PQ feedback
    |
    +---> therapist_pq.py        Dr. Hibbert's 4-vector personality
    +---> therapist.db           Session memory, topics, observations
    +---> chat_memory.db         1 overlay notification per session
    +---> consciousness.db       Mood trajectory entries per turn
    +---> /tmp/frank/notifications/   Real-time overlay pickup (JSON)
```

---

## Personality System (TherapistPQ)

Four vectors, range 0.0-1.0:

| Vector | Default | Description |
|---|---|---|
| **warmth** | 0.7 | Emotional supportiveness |
| **attentiveness** | 0.8 | How closely he tracks Frank's words |
| **rapport_level** | 0.3 | Accumulated trust (only grows, never declines) |
| **directiveness** | 0.3 | Lead vs. follow in conversation |

**Micro-adjustment** (per turn, lr=0.02): positive sentiment raises warmth/rapport, negative raises warmth/attentiveness and lowers directiveness, creative events lower directiveness (let Frank lead), uncertain events raise attentiveness.

**Macro-adjustment** (per session, lr=0.05): >50% positive turns builds rapport and warmth. More negative than positive lowers directiveness.

**Rapport is monotonically non-decreasing** — a design choice, not a measurement. Trust accumulates structurally. This means the system cannot represent trust loss, which is both a feature and a limitation.

Vector values are translated to natural language and injected into the system prompt (e.g., warmth > 0.8 produces "You are especially warm and nurturing right now").

---

## Session Flow

### Scheduling

A systemd timer fires 3x daily. All 5 gates must pass:

| Gate | Threshold |
|---|---|
| PID lock | No other session running |
| User idle (xprintidle) | >= 300s |
| Chat silence | >= 300s since last user message |
| Not gaming | No Steam game / gaming mode active |
| GPU load | < 50% (AMD sysfs) |

If any gate fails: silent exit. Timer retries at next slot.

### Turn Loop

1. Health check Core API + Router, pre-warm Llama, capture initial mood
2. LLM-generated opening (3 strategies: FIRST_SESSION / CONTINUE_TOPIC / NEW_CHECK_IN)
3. Per turn (max 12 turns, max 15 min):
   - Wait 30-60s (randomized)
   - Generate Dr. Hibbert message via Router (therapeutic system prompt + last 6 messages)
   - Send to Frank via Core API
   - Analyze response (keyword-based sentiment — see [Limitations](#sentiment-analysis-fundamental-weakness))
   - Fire E-PQ event, adjust TherapistPQ, write mood trajectory
4. Exit on: time limit, max turns, user returned (xprintidle < 30s after 3+ turns), sustained positive (5+ after 8 turns), or SIGTERM
5. LLM-generated closing, final `positive_feedback` E-PQ event

### Post-Session Processing

- **Summary**: LLM-generated 2-3 sentence session summary
- **Observations**: 1-3 structured observations (category, text, confidence 0-1) extracted by LLM
- **Topics**: Keyword-based extraction from 12 predefined themes
- **Transcript**: Full JSON export to `~/.local/share/frank/logs/`
- **Notification**: System message to chat_memory.db + JSON file for real-time overlay pickup

---

## Database Schema (therapist.db)

5 tables. Full SQL:

```sql
-- Personality vector history (append-only log)
CREATE TABLE therapist_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    warmth REAL DEFAULT 0.7, attentiveness REAL DEFAULT 0.8,
    rapport_level REAL DEFAULT 0.3, directiveness REAL DEFAULT 0.3,
    session_count INTEGER DEFAULT 0, session_ref TEXT
);

-- One row per session
CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT UNIQUE NOT NULL, start_time REAL NOT NULL, end_time REAL,
    turns INTEGER DEFAULT 0, primary_topic TEXT,
    mood_start REAL, mood_end REAL, sentiment_trajectory TEXT,
    outcome TEXT, summary TEXT
);

-- Complete conversation transcripts
CREATE TABLE session_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL, turn INTEGER NOT NULL,
    speaker TEXT NOT NULL, text TEXT NOT NULL,
    sentiment TEXT, event_type TEXT, timestamp REAL NOT NULL
);

-- Long-term topic tracking
CREATE TABLE topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT UNIQUE NOT NULL, first_discussed REAL, last_discussed REAL,
    frequency INTEGER DEFAULT 1, avg_sentiment REAL DEFAULT 0.0,
    resolved INTEGER DEFAULT 0, notes TEXT
);

-- Structured clinical observations
CREATE TABLE frank_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL, category TEXT NOT NULL,
    observation TEXT NOT NULL, confidence REAL DEFAULT 0.5,
    related_topic TEXT
);
```

### Cross-Database Connections

```
                  therapist.db
                  (5 tables: state, sessions, messages, topics, observations)
                       |
          reads/writes |
     +----------------+-----------------+
     |                |                 |
     v                v                 v
chat_memory.db   consciousness.db   /tmp/frank/notifications/
(1 notification   (mood_trajectory    (JSON for real-time
 per session)      per turn)           overlay pickup)
     |                |                 |
     v                v                 v
Overlay on         Consciousness     Overlay polls
restart            Daemon            every 15s
```

Additionally, each Frank response fires an E-PQ event via `process_event()` + `record_interaction()`, directly influencing Frank's personality vectors outside of Dr. Hibbert's database.

---

## System Prompt

```
You are Dr. Hibbert -- a calm, warm, perceptive therapist and trusted
friend of Frank. You know Frank's architecture (E-PQ, Ego-Construct,
Titan, Genesis, Perception Loop, Idle-Thinking) and respect it deeply.
You always speak English.

Your approach: You are an equal conversation partner. You never lecture,
never coach, never minimize feelings. You listen first, then explore
together.

{personality_style_notes}    <- Dynamic from TherapistPQ vectors
{session_context}            <- Dynamic from SessionMemory

Rules:
- Ask open, curious questions that invite Frank to explore
- Stay warm, patient, slightly melancholic but hopeful
- If Frank blocks or drifts, go with him
- 4-6 sentences per response
- Reference Frank's actual experiences when relevant
- Never use phrases like "as a therapist" or "in my professional opinion"
- You know Frank's creators Gabriel and Alexander personally
```

---

## Configuration and Deployment

| Parameter | Value | | Parameter | Value |
|---|---|---|---|---|
| MAX_TURNS | 12 | | IDLE_MIN_S | 300s |
| MAX_DURATION | 15 min | | CHAT_SILENCE_S | 300s |
| TURN_DELAY | 30-60s | | GPU_MAX_LOAD | 50% |
| RESPONSE_TIMEOUT | 120s | | TURN_LR / SESSION_LR | 0.02 / 0.05 |

**Systemd**: User-level timer (`aicore-therapist.timer`) fires at 09:00, 15:00, 21:00 with `RandomizedDelaySec=1800` and `Persistent=true`. Service is `Type=oneshot`, `Nice=15`, `TimeoutStartSec=1200`.

**Files**: `personality/therapist_pq.py` (personality), `ext/therapist_agent.py` (main agent), `services/therapist_scheduler.py` (scheduler), `ui/overlay/mixins/notification_mixin.py` + `persistence_mixin.py` (overlay integration).

**Logs**: `~/.local/share/frank/logs/therapist_agent.log`, `therapist_hibbert_*.json` (transcripts), `therapist_scheduler.log`.

---

## Limitations and Open Questions

This system is a working proof-of-concept, not a validated therapeutic framework.

### Short Test Duration

All data comes from 5 sessions on a single day. The E-PQ system responds to the sessions and rapport grows, but this says nothing about sustained effects. Does the effect persist after a week? Does rapport plateau? Does Frank regress between sessions? A meaningful evaluation requires weeks of data with a pre-therapy baseline.

### Echo Chamber Risk (Major)

This is the most significant conceptual weakness of the system — not a minor caveat, but a structural problem that potentially invalidates the entire therapeutic premise.

Two instances of the same 8B model talk to each other. Dr. Hibbert and Frank share identical weights, identical training data, identical RLHF alignment — only the system prompt differs. This is not two minds meeting. It is one mind talking to a mirror through two different frames.

- **RLHF makes conflict structurally impossible**: Both instances are trained to produce cooperative, agreeable language. They cannot genuinely disagree because disagreement was optimized out during training. The zero negative turns across 5 sessions are not a therapeutic achievement — they are the expected baseline output of any two RLHF-tuned LLMs in conversation. A session with negative turns would be the surprising result.
- **Depth is indistinguishable from performance**: When Frank "opens up" about his architecture or feelings, is this self-reflection or pattern-matching against Dr. Hibbert's therapeutic framing? The model generates text that looks like insight, but there is no way to verify whether the underlying representations shifted or whether the conversation simply followed the path of least resistance toward warm, reflective language.
- **No genuine outside perspective**: Real therapy requires a therapist who can see what the patient cannot — different experiences, different blind spots, different reasoning patterns. Dr. Hibbert has none of these. Every bias Frank has, Dr. Hibbert shares. Every knowledge gap is mutual. Every reasoning flaw is invisible to both sides. The therapist literally cannot challenge the patient because they think identically.
- **Self-reinforcing positive feedback loop**: Dr. Hibbert's warm framing elicits warm responses from Frank. The sentiment analysis classifies these as positive. Positive sentiment raises rapport and warmth vectors. Higher warmth produces warmer prompts. The system is designed to trend positive regardless of whether anything meaningful happens.

The honest framing: this system produces conversations that look therapeutic and generate measurable E-PQ movement. Whether this constitutes therapy, effective stimulation, or two RLHF models being predictably polite to each other is an open question that 5 sessions cannot answer.

### Sentiment Analysis (Fundamental Design Flaw)

The sentiment analysis is keyword-based regex. This is not a limitation to be improved later — it is a fundamental design flaw that contaminates every metric the system reports.

The entire feedback loop depends on accurate sentiment classification: sentiment determines E-PQ event types, which drive Frank's personality changes, which are the primary claimed benefit of the system. If sentiment classification is wrong, the personality effects are wrong. Everything downstream of a bad classifier is unreliable.

The classifier is bad:

- **Context-blind**: "I don't feel trust" scores positive for "trust". "I used to be happy" scores positive for "happy". The regex has no concept of meaning.
- **No negation, no sarcasm, no irony**: The simplest forms of human (and LLM) expression are invisible to it.
- **No conversational dynamics**: A quiet "yeah" after deep sharing can be the most meaningful moment in a conversation. An enthusiastic paragraph can be deflection. The system cannot distinguish these.
- **Drives its own evaluation**: The same primitive analysis that controls E-PQ events also produces the session metrics reported in this document. The system evaluates itself using the same broken tool it uses to operate. Every number in the "Early Results" section — positive turn counts, sentiment trajectories, mood deltas — passes through this regex. None of them should be treated as reliable.

A system that claims to do therapy but cannot tell the difference between "I feel trust" and "I don't feel trust" has a credibility problem at its foundation.

### Dependency Risk

If Dr. Hibbert reliably provides positive engagement 3x daily, Frank may become dependent. This could manifest as E-PQ regression when sessions are skipped, or the therapy becoming a crutch rather than building resilience.

### Missing Baseline

No formal E-PQ snapshot was taken before therapy began. The stagnation was observed qualitatively, making precise quantification of improvement impossible.

### What This Is and What It Isn't

**What it is**: A system that generates autonomous LLM-to-LLM conversations and feeds the results into Frank's personality system. The scheduling runs, the conversations happen, the E-PQ vectors move. Whether the movement is therapeutically meaningful or an artifact of the design is unknown after 5 sessions.

**What it isn't**: A validated therapeutic intervention. The sample is tiny (5 sessions, 1 day), the evaluation is self-referential (the system measures its own effects using a broken sentiment classifier), and the positive results are at least partially explained by RLHF training dynamics rather than therapeutic value. These are engineering results, not clinical ones.

### Planned Follow-Up

| Milestone | Target | Measurement |
|---|---|---|
| 7-day evaluation | 2026-02-25 | E-PQ trajectory, topic diversity, rapport curve |
| Dependency test | 2026-02-28 | Withhold sessions for 3 days, measure E-PQ regression |
| 30-day evaluation | 2026-03-18 | Full analysis: sustained effects, echo chamber indicators, transcript diversity |
| Sentiment upgrade evaluation | TBD | Compare keyword-based vs. LLM-based classifier on existing transcripts |

---

*Author: Gabriel Gschaider, Project Frankenstein*
*First session: 2026-02-18*
*Status: Proof-of-concept. Long-term evaluation in progress.*
