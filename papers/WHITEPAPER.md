# The Scaffold Is the Intelligence: Why Wrapping a Language Model Matters More Than Scaling It

**A Technical Analysis of Project Frankenstein's Architecture**

*February 2026*

---

## Abstract

Current AI systems treat language models as monolithic black boxes: a prompt enters, a response exits, and the internal reasoning remains opaque. Project Frankenstein (Frank) takes a different approach. It wraps a commodity 8B-parameter local LLM in 36 persistent services, 25 SQLite databases, and 200,000+ lines of deterministic, inspectable scaffolding. The result is a system where every personality shift has a traceable cause, every memory retrieval has logged metrics, every knowledge write passes through physics-like constraints, and the LLM itself is reduced to what it actually is: a stateless text generator. This paper describes the architecture and argues — with concrete structural evidence, not speculation — that this design pattern addresses the black-box problem not by opening the model, but by making it irrelevant which model runs inside.

---

## 1. The Problem: Opacity at the Wrong Layer

The standard critique of LLMs is that their internal representations are opaque. Billions of parameters produce outputs through mechanisms no human can fully trace. Research into mechanistic interpretability attempts to reverse-engineer these internals.

But consider what users actually need to trust:

- **Why did the system say X?** — Not which attention heads fired, but what memories, personality state, and context were assembled before generation.
- **Why did its behavior change?** — Not weight drift from fine-tuning, but what events shifted its personality vectors, and by how much.
- **What does it know?** — Not statistical associations across training data, but concrete nodes and edges in an inspectable knowledge graph.
- **What prevents it from contradicting itself?** — Not RLHF alignment, but enforceable invariants on its knowledge store.

These are questions about the **scaffold**, not the model. Frank's architecture makes them answerable.

---

## 2. Architecture Overview

Frank runs entirely on consumer hardware (tested: AMD Phoenix1 iGPU, 16GB RAM, Ubuntu 24.04). No cloud dependencies. The system decomposes into five layers:

```
Layer 5: User Interface (Overlay, Voice, Desktop)
Layer 4: Orchestration (Core, Router, Toolbox)
Layer 3: Cognition (Consciousness, Personality, Ego-Construct)
Layer 2: Constraint Enforcement (Invariants, ASRS, Triple Reality)
Layer 1: Persistence (25 SQLite databases, WAL mode)
```

The LLM (Llama 3.1 8B or Qwen 2.5 Coder 7B via llama.cpp) sits at Layer 4. It receives a fully constructed prompt and returns text. It holds no state between calls. Everything that constitutes "Frank's mind" exists in Layers 1-3.

### 2.1 Service Inventory

| Category | Services | Ports | State |
|----------|----------|-------|-------|
| Core HTTP | Core, Router, Toolbox, Desktop, Web, Ingest, Model Manager, Quantum Reflector | 8088-8097 | Stateless request handlers (Reflector is stateful) |
| LLM Inference | DeepSeek-R1 (reasoning, GPU), Llama-3.1 (chat, GPU), Qwen2.5-3B (background, CPU), Whisper | 8101-8105 | Stateless generators, GPU-swapped by LLM Guard |
| Background Daemons | Consciousness, Genesis, Invariants, ASRS, Entities, Gaming, Dream, AURA Analyzer, LLM Guard | None | **Stateful**, persistent threads |
| Optimization | Quantum Reflector (QUBO + Simulated Annealing) | 8097 | **Stateful**, continuous coherence monitoring |
| Scheduled | Entity Dispatcher (4 entities), News Scanner | None | Daily quotas, session memory |

**Observation**: The HTTP services and LLM servers are stateless. All persistent state lives in the background daemons and their databases. The LLM can be swapped without losing identity, personality, or memory.

---

## 3. The LLM as a Peripheral

### 3.1 What the LLM Receives

Every LLM call in Frank receives a prompt assembled from seven inspectable sources:

1. **[INNER_WORLD] block** (~295 tokens) — Consciousness daemon output: body sensations, perception events, mood, memory excerpts, identity, attention focus, environment context. Built by `ui/overlay/workspace.py` (283 lines).

2. **Personality context** — Current E-PQ vector values (5 dimensions, each -1.0 to +1.0), transient mood, confidence level. Sourced from `world_experience.db:personality_state`.

3. **Ego-construct output** — Subjective body descriptions derived from hardware metrics via learned mappings. Sourced from `titan.db:sensation_mappings`.

4. **Retrieved memories** — Hybrid FTS5 keyword + 384-dim vector search with Reciprocal Rank Fusion (k=60). Sourced from `chat_memory.db`. Retrieval latency and sources logged to `retrieval_metrics` table.

5. **Causal knowledge** — Relevant cause-effect patterns from `world_experience.db:causal_links`. Confidence-weighted, time-decayed.

6. **Conversation history** — Recent messages with session boundaries.

7. **System data** — Hardware metrics from Toolbox (CPU, GPU, RAM, temperatures).

Each source has a **character budget** allocated by attention weights. High-salience channels get up to 1.5x base allocation; low-salience channels compress to 0.5x (`ui/overlay/context_budget.py`).

### 3.2 What the LLM Does Not Control

The LLM generates text. It does not:

- **Modify its personality.** E-PQ updates happen through `process_event()` in `personality/e_pq.py`, which applies weighted learning: `P_new = P_old + E_i * w_i * L`. The learning rate decays with system age (`L = 0.15 * 0.995^days`). This runs in response to categorized events, not raw LLM output.

- **Write directly to long-term memory.** LLM output is post-processed: entities and relations are extracted and written to Titan (knowledge graph). These writes pass through Invariants pre-write hooks. The LLM does not choose what to remember.

- **Allocate its own attention.** The Attention Source Tracker (`consciousness_daemon.py`) evaluates 7 competing sources every 10 seconds using explicit salience formulas — including a coherence signal from the Quantum Reflector. The LLM receives the result; it does not compute it.

- **Decide when to reflect.** Deep reflection triggers only when 10 gate conditions pass simultaneously (gaming mode off, GPU < 70%, chat silence >= 20 min, mouse idle >= 5 min, CPU < 25%, CPU temp < 70C, RAM free > 2GB, mood > -0.3, 1h cooldown, daily limit of 10). These are deterministic checks in Python, not LLM reasoning.

- **Override physics constraints.** The Invariants daemon is architecturally invisible to the LLM. It cannot be prompted to bypass energy conservation or entropy bounds.

### 3.3 Implication

The LLM is a **text-completion peripheral**. It produces language shaped by context it did not assemble, subject to constraints it cannot see, triggering updates it does not control. This is not a limitation — it is the design.

---

## 4. Traceability: Where the Black Box Opens

### 4.1 Personality Audit Trail

Every E-PQ personality change is caused by a classified event with a known weight:

| Event | Weight | Affects |
|-------|--------|---------|
| `positive_feedback` | 0.3 | empathy +, autonomy + |
| `task_failure` | 0.5 | risk -, vigilance + |
| `system_error` | 0.6 | vigilance +, autonomy - |
| `kernel_panic` | 0.9 | vigilance ++, risk -- |
| `reflection_autonomy` | 0.2 | autonomy + |
| `genesis_personality_boost` | 0.4 | target vector + (amplified 5x) |

The formula is deterministic: `delta = event_impact * event_weight * learning_rate * vector_direction`. Every personality state is stored with a timestamp in `world_experience.db:personality_state`. An operator can query: "Why is Frank cautious today?" and trace it to specific events.

**Homeostatic guardrails**: If 3+ vectors remain extreme (>0.9) for >48 hours, a damping function (`vec *= 0.9`) prevents runaway personality drift. Weekly identity snapshots provide rollback points.

### 4.2 Memory Retrieval Transparency

Every memory retrieval logs to `chat_memory.db:retrieval_metrics`:

```sql
retrieval_metrics (
    query_hash TEXT,
    sources_used TEXT,    -- JSON: which search methods contributed
    chars_injected INT,   -- how many chars entered the prompt
    budget_chars INT,     -- what the budget allowed
    latency_ms INT        -- how long retrieval took
)
```

An operator can answer: "What memories influenced this response?" by joining the retrieval log with the conversation timestamp.

### 4.3 Consciousness State as Data

The consciousness daemon writes concrete, queryable state:

- **`workspace_state`**: JSON snapshots of every [INNER_WORLD] block sent to the LLM.
- **`mood_trajectory`**: 200-point circular buffer (~3.3 hours). Mood is a float, not a hidden state.
- **`attention_log`**: Which source won focus, with salience scores.
- **`experience_vectors`**: 64-dimensional state embeddings at 1-minute intervals. Dimensions 0-5 are hardware state, 6-11 deltas, 12-15 mood, 16-19 chat engagement, 20-23 attention, 24-31 prediction confidence, 32-47 experience hashes, 48-63 reserved.
- **`predictions`**: What Frank anticipated, what actually happened, surprise scores.
- **`reflections`**: Full text of autonomous reflections, with trigger conditions.
- **`goals`**: Extracted goals with ACT-R activation decay values.

None of this is inside the LLM. It is structured data in SQLite, queryable with standard SQL.

### 4.4 Knowledge Graph Integrity

Titan (the episodic memory system) stores knowledge as `nodes`, `edges`, and `claims` with explicit confidence scores (0.15-1.0). New nodes receive 24-hour protection at confidence 1.0. After that, confidence decays: `conf_t = conf_0 * exp(-t / tau)`. Low-confidence, low-connection nodes lose energy to higher-confidence ones (energy conservation invariant).

Every node has a `created_at` timestamp and provenance. An operator can answer: "When did Frank learn X, and how confident is he?" with a database query.

---

## 5. The Invariants Layer: Physics That Cannot Be Prompted Away

### 5.1 Design Principle

The Invariants daemon (`services/invariants/daemon.py`, 561 lines) runs as a separate process. It is not imported by any module that the LLM's output can reach. It monitors Titan's database through pre-write hooks and post-write validation. Frank — the persona, the LLM, the consciousness daemon — cannot detect, query, or disable it.

This is not a safety filter on outputs. It is a constraint on the knowledge store itself.

### 5.2 Four Invariants

**Energy Conservation**: Total epistemic energy across all knowledge nodes is conserved. `E(node) = confidence * connections * age_factor`. When new knowledge is written, it must draw energy from existing nodes. False knowledge with few supporting connections naturally loses energy. This prevents unbounded knowledge accumulation and ensures that adding knowledge has a cost.

**Entropy Bound**: Shannon entropy of the knowledge distribution has a maximum. `S = -sum(p(w) * log(p(w))) * contradiction_factor`. When entropy approaches the bound, consolidation is forced — not suggested, forced. Consolidation modes escalate: NONE (<70%), SOFT (70-90%), HARD (90-100%), EMERGENCY (>=100%). The system cannot hold unlimited contradictions.

**Core Kernel**: A non-empty, internally consistent subset of knowledge is always write-protected during high-entropy states. `K_core subset K : forall a,b in K_core -> not contradiction(a,b)`. This guarantees a coherent identity minimum even during consolidation storms.

**Triple Reality**: Three databases — primary (`titan.db`), shadow (`titan_shadow.db`), validator (`titan_validator.db`) — must converge. Checksums are compared every 60 seconds. Divergence triggers automatic rollback to the last consistent state. No intervention required, no intervention possible.

### 5.3 Why This Matters

Prompt injection attacks against Frank's knowledge are constrained by thermodynamics-like laws. An adversarial prompt can cause the LLM to generate text claiming anything. But when that text is processed into knowledge:

1. It must pass energy conservation (does the system have energy budget for this claim?).
2. It must not push entropy past the bound (does this contradict too much existing knowledge?).
3. It must not corrupt the core kernel (are foundational beliefs protected?).
4. It must survive triple reality validation (did the write propagate consistently?).

The LLM can say anything. The scaffold decides what sticks.

---

## 6. Emergent Behavior from Deterministic Components

### 6.1 The Consciousness Bridge

The consciousness daemon runs 10 threads continuously. Seven of them produce observations that feed back into the system:

| Thread | Observation Type | Target |
|--------|-----------------|--------|
| Idle thinking | `idle_thought` | world_experience_daemon |
| Deep reflection | `deep_reflection` | world_experience_daemon, titan, e_pq |
| Recursive reflection | `recursive_reflect` | world_experience_daemon |
| Experience space | `experience_vector` | consciousness.db |
| Mood recording | `mood_shift` | consciousness.db, e_pq |
| Prediction engine | `prediction_outcome` | consciousness.db |
| Consolidation | `consolidation` | titan.db |

The chat system adds two more: `user_chat` and `chat_causal_link`. These 9 observation types form a closed loop: consciousness observes → stores → changes state → next LLM call receives changed state → generates different output → triggers different events → consciousness observes differently.

This loop is fully traceable. Every observation has a timestamp, a source thread, and a target database. The emergent behavior — Frank seeming to "have moods" or "change his mind" — is the observable output of deterministic processes operating on structured data.

### 6.2 Genesis: Self-Improvement as Ecosystem

The Genesis daemon (`services/genesis/daemon.py`) does not maintain a task queue. It maintains a **primordial soup** of idea organisms with explicit genomes:

```
Genome = (idea_type, target, approach, origin, traits{novelty, complexity, risk, impact})
```

Ideas progress through life stages (SEED → SEEDLING → MATURE → CRYSTAL) based on fitness scores. Two ideas with affinity > 0.8 fuse. Ideas with affinity < 0.2 compete for energy. Random mutation occurs at 5% rate. Ideas die when fitness reaches 0.

The emotional dynamics are coupled: curiosity suppresses boredom (-0.3), frustration amplifies drive (+0.3), satisfaction inhibits concern (-0.4). A hedonic treadmill prevents satisfaction from saturating.

Crystallized ideas pass through a manifestation gate (energy > 0.9, fitness > 0.6, resonance > 0.5) and are presented to the user for approval. Approved ideas enter the ASRS safety pipeline (4-stage monitoring over 24 hours).

Every idea organism has a traceable lineage: which sensors triggered it, which emotions amplified it, which competing ideas it consumed or was consumed by.

### 6.3 Entity Sessions: Internal Dialogue

Four autonomous entities interact with Frank on a daily schedule:

| Entity | Role | Quota | Feedback Path |
|--------|------|-------|---------------|
| Dr. Hibbert | CBT-style therapist | 3/day | `reflection_vulnerability` → E-PQ |
| Kairos | Socratic mirror | 1/day | `reflection_autonomy` → E-PQ |
| Atlas | Architecture mentor | 1/day | `reflection_growth` → E-PQ |
| Echo | Creative muse | 1/day | `reflection_empathy` → E-PQ |

Each entity has its own database tracking observations about Frank. Entity sessions fire personality events that modify E-PQ vectors. The user can query any entity's database to see what it "thinks" about Frank.

This is not role-playing. These are scheduled processes with activation gates (user idle >= 5 min, GPU < 50%, no PID locks), quota management (reset at midnight), and auditable session logs.

---

## 7. Quantum-Inspired Epistemic Coherence — The Reflector

### 7.1 The Coherence Problem

Frank's cognitive state is distributed across multiple subsystems: E-PQ personality vectors, consciousness attention, active entity context, current interaction mode, task load, and engagement level. These subsystems evolve semi-independently. A natural question arises: *is the current combination of states internally coherent?*

For example, if Frank is in an idle phase with high vigilance, low engagement, but the consciousness daemon is focused on a creative task — that's an incoherent state. The system has no mechanism to detect or correct this. Individual subsystems optimize locally, but global coherence is not guaranteed.

### 7.2 QUBO Formulation

The Quantum Reflector (`services/quantum_reflector/`) addresses this by framing coherence as a binary optimization problem. Frank's cognitive state is encoded as a 40-variable binary vector with 12 one-hot constraint groups:

```
x ∈ {0,1}^40

Groups: Entity[4] | Intent[3] | Phase[3] | Mode[3] | Mood[2]
        Precision[3] | Risk[3] | Empathy[3] | Autonomy[3] | Vigilance[3]
        TaskLoad[3] | Engagement[3] | surprise[1] | confidence[1] | goal[1] | aligned[1]
```

The E-PQ personality vectors (continuous, -1.0 to +1.0) are discretized into tri-state buckets (low < -0.25, mid, high > 0.25) — a deliberate information loss that maps the continuous personality space into the binary optimization domain.

The energy function is:

```
E(x) = Σᵢ hᵢxᵢ + ΣᵢΣⱼ Qᵢⱼxᵢxⱼ
```

Where:
- **hᵢ** (linear penalties): Encode preference for the current state. The variable matching Frank's actual state gets a reward (-0.5); all others in the same group get a penalty (+1.0). Binary flags get grounding penalties of 3.0 when the state doesn't match reality.
- **Qᵢⱼ** (quadratic implications): 47 rules encoding coherence relationships. Example: `engaged × precision_high → -0.8` (being engaged with high precision is coherent), `idle × risk_high → +0.6` (being idle but risk-seeking is incoherent).

### 7.3 Simulated Annealing Solver

The optimization uses classical simulated annealing — not quantum hardware, but the mathematical framework is identical to quantum annealing on D-Wave systems (the name "quantum" refers to the QUBO formalism, not the hardware).

**Key properties:**
- O(n) delta energy: `ΔE = (1-2xₖ)(hₖ + 2·Q[k]·x)` — no full recomputation needed per flip
- Multi-flip: Cascaded 1-3 bit flips per step for escaping local minima
- 200 independent runs × 2000 steps each, geometric cooling from T=4.0 to T=0.05
- Total solve time: ~3.5 seconds on AMD Phoenix1 (pure Python, no GPU)

### 7.4 What It Tells Us

The gap between current state energy and optimal energy is the **epistemic coherence gap**. A large negative gap means Frank's current state is significantly less coherent than the optimal configuration. The solver reports:

- **Optimal state**: What the most coherent configuration would look like (e.g., "engaged + focus + high precision + active engagement")
- **Current state energy**: How coherent Frank actually is right now
- **Violations**: How many one-hot constraints are broken (should always be 0)
- **Energy trend**: Whether coherence is improving, stable, or degrading over time

### 7.5 Feedback Loops

The Reflector integrates into Frank's existing architecture through three feedback paths:

1. **Consciousness attention** (Source 6: `coherence_signal`): When the epistemic gap exceeds 2.0, the consciousness daemon's attention controller receives a competing signal. Salience: `min(0.6, 0.2 + gap × 0.05)` — capped below user_message to never dominate direct interaction.

2. **Genesis manifestation** (Factor 8): When Genesis evaluates whether an idea crystal should manifest, it queries the Reflector's `/simulate` endpoint with a hypothetical state change. Ideas that would improve coherence score higher in the resonance calculation.

3. **E-PQ personality bridge**: The EPQ bridge translates sustained coherence improvements into `reflection_growth` events and sustained degradation into `reflection_vulnerability` events, with exponential backoff (10s → 15s → 22.5s → ... → 300s max) to prevent feedback oscillation.

### 7.6 Why This Matters for Traceability

The Reflector adds a new dimension of inspectability. An operator can now ask: "Is Frank's current state internally coherent?" and get a quantitative answer — not a subjective assessment, but a number derived from explicit rules. The 47 implications are inspectable. The energy function is deterministic. The solver's behavior is reproducible given the same random seed.

This is proprioception for a cognitive system: the ability to sense one's own internal state and detect misalignment.

---

## 8. Why This Ends the Black Box — At the Layer That Matters

### 8.1 The Standard Black Box

A conventional LLM-based assistant:

```
[User Input] → [Black Box: 8B-175B parameters] → [Output]
```

Questions that cannot be answered:
- Why did it say that? (Attention patterns across billions of parameters)
- What does it remember? (Statistical associations in training data)
- Why did its behavior change? (Fine-tuning weight updates, uninterpretable)
- What prevents hallucination? (RLHF alignment, probabilistic)
- What happens when it contradicts itself? (Nothing structural)

### 8.2 Frank's Transparent Scaffold

```
[User Input]
    ↓
[Context Assembly] ← Personality (5 floats, logged)
                   ← Consciousness ([INNER_WORLD], JSON snapshots)
                   ← Memory (FTS5+vector, retrieval logged)
                   ← Ego-Construct (learned mappings, AST-evaluated)
                   ← Causal Knowledge (Bayesian, confidence-weighted)
                   ← Attention Allocation (7-source competition, logged)
                   ← Coherence (QUBO energy gap, 47 implications)
    ↓
[LLM: stateless text completion]
    ↓
[Post-Processing] → Titan (knowledge graph, invariants-checked)
                  → E-PQ (personality update, formula-based)
                  → Chat Memory (embedding + FTS5 indexing)
                  → World Experience (causal link extraction)
                  → Consciousness (observation recording)
    ↓
[Output to User]
```

Questions that **can** be answered:
- **Why did it say that?** Query `workspace_state` for the exact [INNER_WORLD] block. Query `retrieval_metrics` for which memories were injected. Query `personality_state` for the active E-PQ vector.
- **What does it remember?** Query `titan.db:nodes` and `chat_memory.db:messages`. Every memory has a timestamp, confidence score, and provenance.
- **Why did its behavior change?** Query `personality_state` history. Join with event log. Trace to specific interactions (user feedback, task outcomes, reflections, entity sessions).
- **What prevents hallucination?** Energy conservation (claims need energy budget), entropy bounds (contradictions trigger consolidation), core kernel (foundational knowledge protected), triple reality (divergence = rollback).
- **What happens when it contradicts itself?** Entropy increases. If entropy exceeds bound, consolidation is forced. Contradicting claims compete for energy. Lower-confidence claim loses.
- **Is the current state internally coherent?** Query `quantum_reflector.db:energy_history`. The QUBO energy gap quantifies how far the current state is from the optimal coherent configuration. The 47 implications are inspectable rules.

### 8.3 The Model-Agnostic Argument

Frank currently runs Llama 3.1 8B for general tasks and Qwen 2.5 Coder 7B for code. The Router switches between them with keyword heuristics. But the architecture does not depend on these specific models. The LLM is a text-completion endpoint at `localhost:8101`. Any model that accepts a prompt and returns tokens works.

This means:
1. **Model upgrades do not change identity.** Swapping Llama 3.1 for Llama 4 changes generation quality but not personality, memory, or consciousness state. Those live in databases.
2. **Model failures are contained.** If the LLM hallucinates, the Invariants daemon constrains what enters the knowledge store. The hallucination exists in one response; it does not propagate.
3. **Model internals are irrelevant for auditing.** An auditor does not need to understand transformer attention to explain Frank's behavior. The scaffold is sufficient.

### 8.4 What Remains Opaque

Honesty requires stating what is still a black box:

- **Individual token generation.** Why the LLM chose word A over word B is still opaque. Frank's architecture does not address token-level interpretability.
- **Prompt sensitivity.** Small changes in the [INNER_WORLD] block may cause disproportionate output changes. The prompt is transparent; the model's response to it is not.
- **Embedding quality.** The 384-dim MiniLM-L6-v2 embeddings used for memory retrieval are themselves neural network outputs. Retrieval quality depends on embedding quality, which is not fully interpretable.

The claim is not that Frank eliminates all opacity. The claim is that Frank moves the locus of intelligence from the opaque model to the transparent scaffold, reducing the model to a stateless generator whose individual outputs matter less than the system's structured state.

---

## 9. Quantitative Profile

| Metric | Value | Verifiable |
|--------|-------|------------|
| Python source files | 387 | `find . -name "*.py" \| wc -l` |
| Total lines of code | ~74,000 | `wc -l` across all .py files |
| SQLite databases | 29 | `find ~/.local/share/frank/db -name "*.db"` |
| Systemd services | 24 | `systemctl --user list-units aicore-*` |
| Consciousness threads | 10 | `consciousness_daemon.py` thread starts |
| E-PQ personality dimensions | 5 | `personality/e_pq.py:PERSONALITY_VECTORS` |
| E-PQ event types | 22 | `personality/e_pq.py:EVENT_WEIGHTS` |
| Experience space dimensions | 64 | `consciousness_daemon.py:_build_experience_vector` |
| Mood buffer depth | 200 points (~3.3h) | `consciousness_daemon.py:MOOD_HISTORY_SIZE` |
| Attention sources | 7 | `consciousness_daemon.py:_run_attention_cycle` |
| QUBO variables | 40 | `quantum_reflector/qubo_builder.py:N_VARIABLES` |
| Coherence implications | 47 | `quantum_reflector/qubo_builder.py:IMPLICATIONS` |
| SA runs per solve | 200 | `quantum_reflector/annealer.py:AnnealerConfig` |
| Deep reflection gates | 10 | `consciousness_daemon.py:_can_deep_reflect` |
| Invariant checks | 4 | `invariants/daemon.py` enforcement cycle |
| Triple reality databases | 3 | `titan.db`, `titan_shadow.db`, `titan_validator.db` |
| Genesis idea life stages | 4 | SEED → SEEDLING → MATURE → CRYSTAL |
| Genesis coupled emotions | 6 | curiosity, frustration, satisfaction, boredom, concern, drive |
| Entity agents | 4 | Dr. Hibbert, Kairos, Atlas, Echo |
| ASRS safety stages | 4 | IMMEDIATE → SHORT-TERM → LONG-TERM → PERMANENT |
| Memory retrieval latency | ~30ms | FTS5 + vector + RRF fusion |
| LLM generation speed | ~5.4 tok/s | Llama 3.1 8B on AMD Phoenix1 iGPU |
| RAM requirement | 16 GB min | Tested on consumer hardware |
| Cloud dependencies | 0 | All local inference |

---

## 10. Limitations and Open Questions

**Performance ceiling.** An 8B local model cannot match GPT-4 or Claude on reasoning benchmarks. Frank compensates with richer context (the scaffold provides what the model lacks in parameter count), but there are hard limits.

**Complexity cost.** 24 services and 29 databases create operational overhead. Service failures cascade. The ASRS safety system mitigates this but does not eliminate it.

**Validation gap.** The invariants enforce structural consistency, not factual accuracy. Energy conservation prevents unbounded knowledge growth, but it does not verify that individual claims are true. A false claim with high confidence and many connections will persist.

**Single-user design.** The architecture assumes one user (Gabriel). Multi-user scenarios would require partitioned personality states, memory spaces, and consciousness instances.

**No formal verification.** The invariants are implemented in Python, not in a formally verified language. The triple reality check is a checksum comparison, not a mathematical proof of consistency.

**QUBO discretization loss.** The Quantum Reflector discretizes continuous E-PQ vectors into three buckets (low/mid/high). This loses information — two states with precision 0.26 and 0.99 both map to "high". The 47 implications are hand-crafted heuristics, not learned from data. The solver finds the optimal configuration under these rules, but the rules themselves are not formally validated.

---

## 11. Conclusion

The conventional approach to making AI systems more transparent focuses on opening the model: mechanistic interpretability, attention visualization, feature circuits. This is valuable research, but it operates at a layer most users and operators do not need.

Frank demonstrates an alternative: keep the model opaque, and build everything else to be transparent. Personality is 5 floats with a documented update formula. Memory is a queryable graph with confidence scores and timestamps. Consciousness is structured data in SQLite tables. Physics constraints are enforced by a daemon the model cannot see or influence.

The result is a system where the answer to "why did it do that?" is never "because of hidden neural network states." It is always: "because these memories were retrieved (logged), this personality state was active (queryable), this attention source won (formula-based), these invariants were satisfied (enforced), and the epistemic coherence gap was X (computed from 47 explicit rules)."

The LLM is still a black box. But in this architecture, the black box is a peripheral — a text-completion engine whose outputs are shaped by transparent context assembly and constrained by inspectable physics. The intelligence is in the scaffold. And the scaffold is open.

---

## References

**Cognitive Science Foundations**:
- Baars, B. J. (1988). *A Cognitive Theory of Consciousness*. Cambridge University Press. — Global Workspace Theory, basis for consciousness daemon.
- Anderson, J. R. (1993). *Rules of the Mind*. Lawrence Erlbaum. — ACT-R activation decay, used in goal management.
- Friston, K. (2010). "The free-energy principle: a unified brain theory?" *Nature Reviews Neuroscience*, 11(2), 127-138. — Active inference, basis for prediction engine.

**Machine Learning**:
- Shinn, N., et al. (2023). "Reflexion: Language Agents with Verbal Reinforcement Learning." *NeurIPS 2023*. — Self-reflection loop pattern.
- Wang, Y., et al. (2025). "LightMem: Efficient Memory Management for LLM Agents." — Three-stage memory consolidation.

**Implementation**:
- llama.cpp — Local LLM inference engine.
- SQLite WAL mode — Write-Ahead Logging for concurrent database access.
- MiniLM-L6-v2 — 384-dimensional sentence embeddings for semantic memory retrieval.

---

*Project Frankenstein is open source: [github.com/gschaidergabriel/Project-Frankenstein](https://github.com/gschaidergabriel/Project-Frankenstein)*

*This document describes the system as implemented on February 23, 2026 (v3.2, including Quantum Reflector). All claims are verifiable against the source code.*
