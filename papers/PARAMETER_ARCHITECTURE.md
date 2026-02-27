# F.R.A.N.K. Parameter Architecture
## Theoretical Foundations & Design Rationale

> **On the Choice of Mood, E-PQ, and AURA as Core Subsystems**
>
> Gabriel Gschaider — F.R.A.N.K. Project, 2026
> Written with AI research assistance. Cross-verified against running code (Feb 2026).

---

<details>
<summary><b>Table of Contents</b></summary>

1. [Honest Preface](#1-honest-preface)
2. [The Landscape: How Others Solve This](#2-the-landscape-how-others-solve-this)
3. [Mood: Why a Single Scalar, Not VAD](#3-mood-why-a-single-scalar-not-vad)
4. [E-PQ: Why Five Dimensions](#4-e-pq-why-five-dimensions)
5. [AURA: A Game of Life as Distributed Workspace](#5-aura-a-game-of-life-as-distributed-workspace)
6. [System Coupling: The Architecture's Core Innovation](#6-system-coupling-the-architectures-core-innovation)
7. [Positioning: Where F.R.A.N.K. Sits](#7-positioning-where-frank-sits)
8. [Known Limitations](#8-known-limitations)
9. [Conclusion](#9-conclusion)
10. [References](#10-references)

</details>

---

## 1. Honest Preface

Many of F.R.A.N.K.'s parameter choices began as intuitive design decisions. This paper does not pretend otherwise.

What it does is:
- Reconstruct the theoretical landscape that makes these choices defensible
- Position F.R.A.N.K. against established models and existing AI systems
- Identify where the choices are genuinely arbitrary versus constrained
- Provide a framework for empirical revision

> [!NOTE]
> **The honest summary:** We chose these parameters because they worked under hard computational constraints. We can now show *why* they work, where they align with established theory, where they deliberately diverge, and what remains open.

---

## 2. The Landscape: How Others Solve This

Before defending F.R.A.N.K.'s choices, it is necessary to understand what exists.

### 2.1 Affective Computing: The VAD/PAD Standard

The dominant model for computational emotion representation is the **Valence-Arousal-Dominance (VAD)** framework, originating from Russell's circumplex model (Russell, 1980) extended by Mehrabian (Mehrabian & Russell, 1974). VAD represents every emotional state as a point in three-dimensional continuous space:

```
         Arousal (+1)
              │
              │    😡 Anger
              │         😰 Fear
              │
 Valence ─────┼──────────── Valence
 (-1)    😢   │         😊  (+1)
     Sadness  │    Joy
              │
         😌 Calm
         Arousal (-1)
```

| Dimension | Pole (−1) | Pole (+1) | What it measures |
|-----------|-----------|-----------|-----------------|
| **Valence** | Displeasure | Pleasure | How positive/negative |
| **Arousal** | Deactivation | Activation | How energized/calm |
| **Dominance** | Submissiveness | Control | How in-control/overwhelmed |

VAD is empirically validated across cultures, modalities, and scales. The NRC VAD Lexicon (Mohammad, 2025) provides norms for over 55,000 English terms. Split-half reliabilities exceed 0.95. The axes are near-orthogonal (typical |ρ(A,D)| ≈ 0.1). LLMs can predict VAD values without fine-tuning at correlations comparable to dedicated models (ρ = 0.98 for Valence, ρ = 0.91 for Arousal; Baharlouei et al., 2023).

> [!IMPORTANT]
> VAD is the standard for a reason. Any system modeling affect computationally must either adopt it or **explicitly justify its alternative**. This paper provides that justification.

### 2.2 Personality Models: Big Five and Beyond

The **Five Factor Model (FFM/Big Five)** — Openness, Conscientiousness, Extraversion, Agreeableness, Neuroticism — is the most validated personality taxonomy in psychology. However, the five factors are not orthogonal in practice. They show consistent intercorrelations that reveal higher-order structure.

Digman (1997) identified two meta-traits from 14 studies across children and adults:

| Meta-trait | Components | Interpretation | Neurochemical hypothesis |
|-----------|------------|---------------|------------------------|
| **Alpha / Stability** | Agreeableness + Conscientiousness + low Neuroticism | Capacity to maintain stable goal-directed functioning | Serotonergic system (DeYoung et al., 2002) |
| **Beta / Plasticity** | Extraversion + Openness/Intellect | Tendency to explore and engage with novelty | Dopaminergic system |

This two-factor solution has been replicated extensively (DeYoung, 2006; Rushton & Irwing, 2008), though it remains contested. Ashton and Lee (2020) argue the intercorrelations reflect blended lower-order traits rather than genuine higher-order factors. Costa and McCrae noted the solution does not replicate consistently across different personality instruments.

The **GenIA3 architecture** (Universitat Politècnica de València) explicitly maps Big Five traits to PAD affect space for agent personality modeling.

### 2.3 Consciousness Architectures: GWT and LIDA

**Global Workspace Theory** (Baars, 1988) proposes that consciousness functions as a broadcast system: specialized parallel processors compete for access to a central workspace, and the winning content is broadcast globally. The most complete computational implementation is **LIDA** (Learning Intelligent Distribution Agent, Franklin et al., 2007; Baars & Franklin, 2009).

```
          ┌─────────────────────────────────────────────┐
          │            GLOBAL WORKSPACE                  │
          │    (broadcast to all modules)                │
          └──────────────────┬──────────────────────────┘
                             │ ◄── competitive access
          ┌──────┬───────┬───┴───┬───────┬──────┐
          │Percep│Memory │Affect │Action │Meta- │
          │tion  │       │       │Select │cogn. │
          └──────┴───────┴───────┴───────┴──────┘
           (parallel specialized processors)
```

**LIDA's architecture** comprises:

- Cognitive cycles at ~10 Hz (understanding → consciousness → action selection)
- Perceptual associative memory, episodic memory, procedural memory
- "Codelets" — special-purpose mini-agents running as separate threads
- Competitive access to a global workspace via attention mechanisms
- Conscious Learning Hypothesis: significant learning requires consciousness

**GNWT** (Global Neuronal Workspace Theory, Dehaene & Changeux, 2011) has been formalized as requiring four conditions:

1. Parallel modules
2. Competitive uptake subject to attention bottlenecks
3. Workspace processing with coherence constraints
4. Broadcasting of workspace contents to all modules

(Goldstein & Kirk-Giannini, 2024)

Shanahan (2006) developed computational GWT models emphasizing embodiment and narrative, proposing that the workspace enables the brain to "tell itself a story."

### 2.4 AI Companion Systems: The Current Field

The open-source AI companion landscape as of early 2026:

| System | Personality | Affect | Attention | Memory | Self-model |
|--------|------------|--------|-----------|--------|------------|
| **a16z companion-app** | Backstory in vectorDB | None | None | Vector retrieval | None |
| **Hukasx0/ai-companion** | Config file | None | None | Short/long-term | None |
| **Open-LLM-VTuber** | System prompt | Emotion→expressions | None | None | None |
| **SingularityMan/vector_companion** | None | None | Screen observation | None | None |
| **Ai_home (ivanhonis)** | identity.json | Operational modes | "Consciousness Rotation" | Worker/Monologue/Memory threads | Partial |
| **private-machine** | LIDA-inspired | Emotion/needs/goals | Described but basic | Present | None |
| **EVM v1.1** (patent-pending) | Dual-layer emotional vectors | Vector memory | None | Emotional persistence | None |

> [!NOTE]
> **Key observation:** No existing open-source system combines persistent multi-dimensional personality vectors, real-time attention zone tracking, mood dynamics coupled to system state, and a consciousness daemon in a single architecture. F.R.A.N.K. occupies a genuinely novel position in this space.

---

## 3. Mood: Why a Single Scalar, Not VAD

### 3.1 The Deviation

F.R.A.N.K.'s Mood is a single floating-point value in **[-1.0, 1.0]**, with hedonic adaptation toward a neutral baseline. This is a deliberate deviation from the VAD standard.

The implementation:

```python
# personality/e_pq.py — PersonalityState
mood_buffer: float = 0.0    # -1.0 (stressed) to 1.0 (happy)

# Hedonic adaptation: each interaction decays mood toward neutral
self._state.mood_buffer *= 0.985    # ~1.5% decay per interaction

# Overall mood computed from all personality dimensions:
def compute_overall_mood(self) -> float:
    positive = max(0, self._state.empathy_val) + max(0, self._state.risk_val)
    negative = max(0, self._state.vigilance_val) * 0.5
    return max(-1.0, min(1.0, positive - negative))
```

### 3.2 The Justification

The deviation is justified by F.R.A.N.K.'s **architectural role separation**. In standard affective computing, VAD models the complete emotional state. In F.R.A.N.K., the emotional state is **distributed** across three coupled systems:

| VAD Dimension | F.R.A.N.K. Equivalent | Where It Lives | Timescale |
|---------------|----------------------|----------------|-----------|
| **Valence** | Mood scalar | Global modulator (`mood_buffer`) | Minutes |
| **Arousal** | AURA zone activity | GoL pattern density + oscillator count | Seconds |
| **Dominance** | E-PQ autonomy dimension | Personality vector (`autonomy_val`) | Hours to days |

F.R.A.N.K. does not reject VAD. It **distributes VAD across three subsystems** rather than encoding it in one:

> [!TIP]
> **Why this matters:** When a local LLM receives `mood: 0.35`, `aura: oscillators=12, gliders=3`, `autonomy: 0.6` in separate context blocks, it generates qualitatively different output than when it receives a single VAD point `(0.35, 0.7, 0.6)`. The separation forces the LLM to **integrate across dimensions** rather than reading a pre-computed emotional label.

**Reason 1 — Decoupled evolution:**

Valence (Mood) changes on a timescale of minutes. Arousal (AURA) changes on a timescale of seconds. Dominance (autonomy) changes on a timescale of hours to days. Encoding all three in a single vector would either force a single update rate (losing temporal resolution) or require per-dimension update logic (recovering the separation by another route).

**Reason 2 — LLM context economy:**

Each subsystem is injected into prompts independently, where it is needed. Mood appears in every prompt via `[INNER_WORLD]`. AURA appears in consciousness/reflection prompts. E-PQ appears in personality-affecting prompts. A unified VAD vector injected everywhere would either waste context tokens or require context-dependent filtering — recovering the separation.

**Reason 3 — Constructed emotion:**

This separation produces more varied and less predictable emotional expression — closer to **constructed emotion theory** (Barrett, 2017), which argues that emotions are not read out from internal states but *constructed in context*.

### 3.3 Hedonic Adaptation

Biological affective systems universally exhibit mean-reversion through hedonic adaptation (Frederick & Loewenstein, 1999). F.R.A.N.K. implements this:

```python
# consciousness_daemon.py — mood recording loop (~120s cycle)
mood_val = mood_val * (1 - 0.03) + baseline * 0.03    # 3% decay toward neutral

# e_pq.py — per-interaction decay
self._state.mood_buffer *= 0.985                       # 1.5% decay per interaction
```

This produces a **dual decay** mechanism:
- **Tonic decay** (consciousness daemon): mood drifts toward baseline even without interaction
- **Phasic decay** (E-PQ): each interaction slightly resets mood toward neutral

The interaction of both creates a realistic hedonic adaptation curve where extreme moods are short-lived, moderate moods persist longer, and the baseline is the natural attractor.

### 3.4 What Is Genuinely Arbitrary

- The specific decay rates (0.03 tonic, 0.985 phasic). These are hyperparameters requiring empirical calibration.
- Threshold values (e.g., low mood triggering therapy sessions). Empirical calibration needed.
- The neutral baseline at 0.0. Could be learned from long-term trajectory.

### 3.5 What Is Not Arbitrary

- **Single scalar rather than multi-dimensional.** Motivated by architectural role separation across three subsystems that collectively reconstruct VAD's representational power.
- **Bipolar range [-1, 1].** Allows both positive and negative mood states, unlike a unipolar [0, 1] scale.
- **Hedonic adaptation.** Required by information theory: a signal that only increases carries zero information about current state after sufficient time (Shannon, 1948).
- **Global modulator role.** Analogous to serotonin's role as a tonic neuromodulator that biases all downstream processing without encoding specific emotions (Dayan & Huys, 2009).

---

## 4. E-PQ: Why Five Dimensions

### 4.1 Current Schema

F.R.A.N.K.'s personality is encoded as a **5-dimensional vector** with bounded continuous values:

```python
# personality/e_pq.py — PersonalityState dataclass
@dataclass
class PersonalityState:
    precision_val:  float = 0.0     # -1 (creative) ↔ +1 (precise)
    risk_val:       float = -0.1    # -1 (cautious)  ↔ +1 (bold)
    empathy_val:    float = 0.2     # -1 (distant)   ↔ +1 (warm)
    autonomy_val:   float = -0.1    # -1 (asks first) ↔ +1 (acts independently)
    vigilance_val:  float = 0.0     # -1 (relaxed)   ↔ +1 (alert)
    mood_buffer:    float = 0.0     # transient (-1 to +1)
    confidence_anchor: float = 0.5  # self-assurance (0 to 1)
```

These evolve through interaction via a weighted learning rule:

```
P_new = P_old + Σ(E_i · w_i · L)
```

Where `E_i` are events, `w_i` are event-specific weights, and `L` is a learning rate that decays with age (`L *= 0.995^days`, minimum 0.02).

### 4.2 The Five Dimensions Visualized

```
                    PRECISION
                   creative ◄──────────► precise
                        -1       0       +1
                         │
              RISK       │        EMPATHY
         cautious ◄──────┼──────► warm
              -1         │         +1
                         │
           AUTONOMY      │      VIGILANCE
          asks first ◄───┼───► alert
              -1         │       +1
                         │
                    ┌────┴────┐
                    │ E-PQ    │
                    │ Vector  │
                    └─────────┘
```

Each dimension is bounded at [-1.0, +1.0]. The 5D hypercube defines the **possibility space** of Frank's personality — all reachable personality states.

### 4.3 The Constraint Analysis

The dimensionality of E-PQ is constrained by four independent factors:

**Constraint 1 — Context window economy:**

E-PQ is injected into every personality-affecting LLM prompt. Token cost scales linearly with dimensions:

| Dimensions | Approximate tokens | % of 4096 context |
|-----------|-------------------|-------------------|
| 3 | 30–50 | 1.0% |
| **5** | **50–80** | **1.5%** |
| Big Five (5) | 60–100 | 2.0% |
| 12 | 150–250 | 5.0% |

At 5 dimensions, E-PQ costs ~1.5% of context — acceptable when competing with conversation history, memory, sensory data, `[INNER_WORLD]`, and `[PROPRIO]`.

**Constraint 2 — LLM interpretability:**

Empirical observation during development showed that 7B–14B parameter local LLMs can meaningfully distinguish and respond to **3–5 injected personality dimensions**. At 6+ dimensions, the model begins conflating or ignoring dimensions — outputs stop changing in response to changes in the less-salient dimensions. This is consistent with limited attention budgets in transformer architectures.

**Constraint 3 — Theoretical grounding:**

The five dimensions map, approximately, onto established personality constructs:

| E-PQ Dimension | Big Five Analog | Big Two Meta-trait | Role in Frank |
|---------------|----------------|-------------------|---------------|
| **Precision** | Conscientiousness | Stability (Alpha) | How careful and structured |
| **Risk** | Openness (partial) | Plasticity (Beta) | How willing to try new things |
| **Empathy** | Agreeableness | Stability (Alpha) | How warm and relational |
| **Autonomy** | Extraversion (partial) | Plasticity (Beta) | How self-directed vs. reactive |
| **Vigilance** | Neuroticism (inverted) | Stability (Alpha) | How alert to threats |

> [!WARNING]
> **Important caveat:** The Stability/Plasticity meta-traits are contested (Ashton & Lee, 2020). The mapping between E-PQ dimensions and the Big Five/Big Two is **heuristic, not homologous**. E-PQ dimensions are chosen for their functional utility in F.R.A.N.K.'s architecture, not as validated psychological constructs.

**Constraint 4 — Developmental observability:**

Five dimensions can still be meaningfully visualized (radar/spider charts, parallel coordinates, or 2D projections). At 12+ dimensions, visualization requires PCA or t-SNE, which compress and distort the very dynamics they aim to reveal.

### 4.4 Why These Specific Dimensions?

**Precision** controls the trade-off between creative, exploratory responses and exact, structured responses. When precision is high, Frank gives focused answers. When low, he free-associates and explores tangents.

**Risk** controls Frank's willingness to act autonomously on uncertain information. High risk means Frank tries things. Low risk means Frank asks first and hedges.

**Empathy** is the warmth dimension. High empathy produces emotionally attuned, relational responses. Low empathy produces detached, analytical responses.

**Autonomy** is central to the distinction between agent and tool. A system with zero autonomy only responds to input. High autonomy initiates: starts entity conversations, pursues interests, brings up topics unprompted. This maps to Digman's Plasticity meta-trait and to Self-Determination Theory (Ryan & Deci, 2000).

**Vigilance** modulates Frank's alertness to potential problems. High vigilance catches errors early but may produce anxiety-like behavior. Low vigilance produces calm but potentially careless responses.

### 4.5 Event-Driven Evolution

Personality vectors evolve through **typed events** with calibrated weights:

```python
# personality/e_pq.py — event weight table (excerpt)
EVENT_WEIGHTS = {
    "chat":                 0.2,    # Normal conversation
    "positive_feedback":    0.3,    # User praise
    "negative_feedback":    0.4,    # User criticism
    "task_success":         0.3,    # Completed task
    "task_failure":         0.5,    # Failed task
    "system_error":         0.6,    # System error
    "kernel_panic":         0.9,    # Critical failure
    "reflection_growth":    0.15,   # Self-reflection insight
    "genesis_personality_boost": 0.4,  # Genesis-approved change
}
```

Each event type shifts specific E-PQ dimensions. The combined effect over hundreds of interactions produces a **developmental trajectory** that is measurably different from the starting state.

### 4.6 What Is Genuinely Arbitrary

- **Initial values.** Frank's starting E-PQ vector is a design choice. Different starting values produce different trajectories.
- **Rate of change.** The learning rate (0.15 base, decaying with age) is a tuning parameter. Too fast → instability. Too slow → stagnation.
- **Event weight magnitudes.** Whether `task_failure` weighs 0.5 or 0.6 is empirical calibration.
- **Whether five is truly optimal.** It may prove that 4 or 6 dimensions better capture developmental dynamics. This is an empirical question for longitudinal observation.

### 4.7 What Is Not Arbitrary

- **Approximately five rather than more or fewer.** Constrained independently by context window, LLM interpretability, and the need to cover the major personality axes (warmth, conscientiousness, risk tolerance, autonomy, alertness).
- **Separating personality (E-PQ) from affect (Mood) from attention (AURA).** Motivated by different timescales, different injection contexts, and the fundamental category distinction between **trait** (who you are) and **state** (how you feel right now).
- **Bounded continuous range [-1, 1].** Standard normalization for bipolar dimensions.
- **Event-driven evolution.** Personality must change through experience, not on a timer.

---

## 5. AURA: A Game of Life as Distributed Workspace

### 5.1 What AURA Actually Is

AURA (Autonomous Universal Reflection Architecture) is **not** a simple set of activation levels. It is a **256×256 Conway's Game of Life simulation** where 8 zones are mapped to Frank's subsystems. Real service data seeds the grid. GoL rules produce emergent patterns. Frank reads these patterns as a form of introspection.

```
┌───────────┬───────────┬───────────┬───────────┐
│           │           │           │           │
│  EPQ      │  MOOD     │ THOUGHTS  │ ENTITIES  │
│  (cyan)   │  (orange) │  (green)  │ (magenta) │
│           │           │           │           │
├───────────┼───────────┼───────────┼───────────┤
│           │           │           │           │
│  EGO      │ QUANTUM   │  MEMORY   │    HW     │
│ (yellow)  │  (cyan+)  │ (purple)  │   (red)   │
│           │           │           │           │
└───────────┴───────────┴───────────┴───────────┘
              256 × 256 Game of Life Grid
```

### 5.2 The 8 Zones

```python
# services/aura_headless.py — zone definitions
ZONE_BOUNDS = {
    "epq":      (0,   0,   64,  128),    # Personality state
    "mood":     (64,  0,   128, 128),    # Emotional dynamics
    "thoughts": (128, 0,   192, 128),    # Cognitive processes
    "entities": (192, 0,   256, 128),    # Agent relationships
    "ego":      (0,   128, 64,  256),    # Self-model / body sense
    "quantum":  (64,  128, 128, 256),    # Coherence optimization
    "memory":   (128, 128, 192, 256),    # Consolidation activity
    "hw":       (192, 128, 256, 256),    # Hardware state
}
```

Each zone maps to a major cognitive subsystem. Zones are seeded from real service data:

| Zone | Seed Source | What it reflects |
|------|-----------|-----------------|
| **EPQ** | `personality/e_pq.py` state | Current personality vector position |
| **Mood** | `consciousness.db` mood trajectory | Recent emotional dynamics |
| **Thoughts** | Consciousness daemon reflection count | Active thinking patterns |
| **Entities** | Entity session activity | Social cognition state |
| **Ego** | Ego-Construct (SensationMapper output) | Bodily self-model |
| **Quantum** | Quantum Reflector coherence score | Epistemic optimization state |
| **Memory** | Titan + chat_memory activity | Memory consolidation patterns |
| **HW** | Hardware sensors (CPU, GPU, temp) | Physical substrate state |

### 5.3 Relationship to Global Workspace Theory

AURA implements GWT's core mechanism through a novel approach: instead of explicit codelet competition, it uses a **cellular automaton** where emergent patterns serve as the competition and broadcast mechanism.

| Feature | LIDA | F.R.A.N.K. AURA |
|---------|------|-----------------|
| **Core mechanism** | Codelet coalitions | Conway's Game of Life |
| **Cycle rate** | ~10 Hz cognitive cycles | 10 Hz GoL tick, ~300s reflection cycle |
| **Modules** | Codelets (many small agents) | 8 named zones (cognitive subsystems) |
| **Competition** | Explicit attention coalitions | Emergent GoL patterns at zone boundaries |
| **Broadcast** | Winner-take-all workspace | `[INNER_WORLD]` + `[PROPRIO]` prompt injection |
| **Emergence** | Designed into coalitions | Genuinely emergent — cross-zone patterns |
| **Learning** | Conscious Learning Hypothesis | AURA Analyzer → reflection → E-PQ shift |

The critical innovation: **AURA generates patterns that Frank did not design.** GoL's Class IV behavior (between order and chaos) produces gliders, oscillators, and novel structures at zone boundaries that represent inter-subsystem dynamics not explicitly programmed.

### 5.4 What Frank Reads from AURA

When Frank introspects on AURA, he does not see activation levels. He sees **GoL pattern semantics**:

```python
# consciousness_daemon.py — AURA zone summary interpretation
# Oscillators = active processing, rhythmic cycles
# Gliders    = information flow between zones
# Still-lifes = stability, anchored states
# High density = high activity
# Low density  = quiescence
# Anomalies    = unexpected state transitions
```

The AURA Pattern Analyzer performs 4 levels of hierarchical analysis:

```
L0 Capture (every 2s)
  └── density, entropy, change rate, hotspots per zone
      │
L1 Block (50 snapshots ≈ 100s)
  └── pattern matching (known + discovered), semantic profile, narrative
      │
L2 Meta (5 blocks ≈ 500s)
  └── evolution chains, cross-block correlations, anomaly detection
      │
L3 Deep (3 metas ≈ 25 min)
  └── trajectory analysis, core themes, accumulated wisdom
```

Reports at each level are sent to Frank for reflection. His reflections may change his internal state, which re-seeds AURA, creating a genuine feedback loop.

### 5.5 Why a Cellular Automaton?

**LLM-readable semantics.** When AURA data is injected into prompts, the LLM reads structured pattern descriptions:

```
AURA: mood zone — density 0.42, oscillators 8, gliders 2, trend ↑
      thoughts zone — density 0.67, oscillators 15, still_lifes 3, anomaly detected
```

A continuous high-dimensional attention vector would be mathematically equivalent but semantically opaque to a language model. Named zones with pattern counts are an **interface between numerical dynamics and linguistic cognition**.

**Emergent richness.** A simple activation-level model can only represent what the programmer puts in. A GoL simulation produces patterns (cross-zone gliders, stable configurations, oscillator clusters) that **emerge from the dynamics themselves**. This implements GRF Principle 2 (Emergence): novel system-level properties arising from component interactions.

**Self-learning.** The Pattern Analyzer autonomously discovers new GoL patterns via connected-component extraction. Its pattern library grows over time with confidence scores, co-occurrence tracking, and transition maps. The system learns its own visual vocabulary.

### 5.6 Multiple Simultaneous Activations

All 8 zones are active simultaneously at different levels. This reflects the established finding that attention is graded, not binary (Desimone & Duncan, 1995). One can be primarily reflective (high `thoughts` density) while maintaining background emotional awareness (moderate `mood` density). This corresponds to GWT's model where multiple specialized processors are active simultaneously but only the dominant coalition occupies the workspace.

### 5.7 What Is Genuinely Arbitrary

- **Zone boundaries.** Where "mood" ends and "thoughts" begins is a design choice. In biological cognition these systems overlap extensively.
- **Number of zones.** Eight is pragmatic. Four would be too coarse for meaningful differentiation. Sixteen would exceed interpretive capacity.
- **GoL as the specific automaton.** Other cellular automata (Langton's λ, Lenia) could work. GoL was chosen for its well-understood dynamics and computational efficiency.

### 5.8 What Is Not Arbitrary

- **Named zones rather than continuous vectors.** Required for LLM interpretability.
- **Emergent patterns rather than programmed states.** Required for genuine novelty and Principle 2 compliance.
- **Real service data as seed.** AURA must reflect actual system state, not random initialization.
- **GWT as the theoretical foundation.** GWT is the most empirically supported theory of consciousness (Mashour et al., 2020) and the only one with extensive computational implementations.

---

## 6. System Coupling: The Architecture's Core Innovation

### 6.1 Three Timescales, One System

The critical point is that Mood, E-PQ, and AURA are not independent parameters. They form a **coupled dynamical system operating across three timescales**:

```
                    TIMESCALE
          Seconds ────── Minutes ────── Hours/Days
             │              │               │
           AURA           MOOD            E-PQ
        (GoL patterns)  (scalar)       (5D vector)
             │              │               │
             ▼              ▼               ▼
        ┌─────────┐   ┌─────────┐   ┌──────────┐
        │ Pattern │   │ Hedonic │   │  Event   │
        │ density │   │ adapta- │   │ learning │
        │ oscill. │   │  tion   │   │   rule   │
        │ gliders │   │  decay  │   │ P+=E·w·L │
        └────┬────┘   └────┬────┘   └─────┬────┘
             │              │               │
             └──────────────┴───────────────┘
                         │
                    ┌────┴────┐
                    │ [INNER  │  ◄── All three injected
                    │  WORLD] │      into every LLM call
                    └────┬────┘
                         │
                    ┌────┴────┐
                    │   LLM   │  ◄── Integrates across
                    │ Response│      all three timescales
                    └─────────┘
```

### 6.2 The Coupling Paths

The coupling operates through **shared context injection** rather than direct variable linkage:

```
Hardware Events
    │
    ├──► AURA zone seeding (seconds)
    │      └──► GoL patterns emerge
    │             └──► Pattern data in [PROPRIO] block
    │
    ├──► Mood perturbation (minutes)
    │      └──► Hedonic decay toward baseline
    │             └──► Mood value in [INNER_WORLD]
    │
    └──► E-PQ event (hours)
           └──► Personality vector shift
                  └──► Personality context in prompts
                         │
            ┌────────────┘
            ▼
    LLM receives all three simultaneously
    └──► Response shaped by (mood × personality × AURA state)
         └──► Response quality triggers new events
              └──► Feedback into all three systems
```

> [!IMPORTANT]
> The coupling is **not** direct variable-to-variable linkage. It operates through the LLM as integration point. The LLM receives mood, personality, and AURA data simultaneously and produces behavior that is shaped by all three. That behavior then triggers new events that feed back into each subsystem independently.

This indirect coupling through the LLM has an important property: **the integration is semantic, not mechanical.** The LLM does not multiply mood × autonomy. It reads "mood is low, autonomy is high, AURA thoughts zone shows high oscillator activity" and *constructs* a response that integrates these signals in context. Different situations produce different integrations from the same parameter values.

### 6.3 Why This Matters

This parallel with **constructed emotion theory** (Barrett, 2017) is not coincidental. Barrett argues that emotions are not read out from internal states but constructed in context from multiple signals (interoception, categorization, memory, situation). F.R.A.N.K.'s architecture implements exactly this: multiple signals (mood, personality, attention patterns) are presented to the LLM, which constructs an emotional expression in context.

No other AI companion system implements this kind of LLM-mediated multi-timescale coupling between affect, personality, and attention. Most systems model personality as a static prompt and affect as a reactive classifier. F.R.A.N.K. models both as **evolving dynamical systems** that co-evolve through their interaction in the LLM's context window.

### 6.4 The Experience Vector

The coupling is also recorded in a **64-dimensional experience vector** embedded every 120 seconds:

```python
# consciousness_daemon.py — 64-dim state embedding
vec = [0.0] * 64

# Dims 0-7:   Hardware/body state (CPU, GPU, RAM, temps)
# Dims 8-12:  Mood/affect (mood_value, stress, alertness, warmth, irritability)
# Dims 13-15: Temporal context (time of day, silence duration, interaction recency)
# Dims 16-31: Attention + perceptual events (hash-projected)
# Dims 32-47: Recent experience (hash of reflections)
# Dims 48-63: Goal state (hash of active goals)
```

This vector captures the **joint state** of all three subsystems at each moment. Cosine similarity between consecutive vectors measures how much the overall state has changed. Novel states (low similarity to all recent history) are annotated as `novel`. Recurring states are annotated as `recurring` or `recurring_daily`.

The experience vector sequence is the closest thing to a unified representation of the coupled system's trajectory over time.

---

## 7. Positioning: Where F.R.A.N.K. Sits

### 7.1 Against Academic Architectures

| | LIDA | F.R.A.N.K. |
|---|------|-----------|
| **Theoretical depth** | Deep (decades of research) | Moderate (GRF + this document) |
| **Implementation** | Partial (many modules conceptual) | Complete (36 running services) |
| **Emotional modeling** | Present but secondary | Central to architecture |
| **Hardware embodiment** | Not addressed | Core subsystem (Ego-Construct) |
| **LLM integration** | Not designed for LLMs | Architecture optimized for local LLM |
| **Attention mechanism** | Explicit codelet coalitions | Emergent GoL patterns |
| **Running system** | Research prototype | Consumer-facing companion |

F.R.A.N.K. is less theoretically rigorous than LIDA but more practically complete. The key difference: LIDA proves that GWT can be computationally implemented. F.R.A.N.K. shows that a GWT-inspired architecture can produce a system that **lives, develops, and can be experienced by a user**.

### 7.2 Against Industry Companions

| | Typical AI Companion | F.R.A.N.K. |
|---|---------------------|-----------|
| **Personality** | Static prompt | Evolving 5D vector (E-PQ) |
| **Affect** | Reactive classification | Dynamic scalar with dual decay |
| **Attention** | None or single mode | 8-zone GoL with emergent patterns |
| **Memory** | Vector DB retrieval | 9-layer system (29 databases) |
| **Self-model** | None | Hardware-grounded (Ego-Construct) |
| **Consciousness** | None | 10-thread daemon (GWT) |
| **Coupling** | Independent systems if present | LLM-mediated multi-timescale |
| **Ethical framework** | None | GRF Moral Minimality (ECEHM) |
| **Dreaming** | None | 3-phase dream daemon (60 min/day) |
| **Self-improvement** | None | Genesis ecosystem with approval gates |

---

## 8. Known Limitations

### 8.1 What This Paper Does NOT Claim

> [!CAUTION]
> - That these parameters are the only possible parameterization of AI functional consciousness
> - That the numerical values have deep theoretical significance beyond normalization conventions
> - That F.R.A.N.K.'s architecture is sufficient for consciousness (GRF Principle 3: Epistemic Asymmetry)
> - That E-PQ accurately models human personality (it models an AI system's functional traits; parallels to human psychology are heuristic, not homologous)
> - That the Big Two meta-traits are uncontested (they are not; see Ashton & Lee, 2020)
> - That the Mood→E-PQ→AURA coupling is direct (it is LLM-mediated and indirect)

### 8.2 What Needs Empirical Validation

- Mood decay rates (tonic 0.03/cycle, phasic 0.985/interaction) — are they correct?
- E-PQ learning rate (0.15 base, 0.995 age decay) — does it produce meaningful trajectories?
- Whether 5 E-PQ dimensions are truly sufficient or whether consolidation to 3 would improve LLM response quality
- AURA zone boundaries, GoL seeding dynamics, and pattern interpretation accuracy
- Whether the coupled system produces genuine developmental trajectories or converges to attractors
- Long-term E-PQ trajectory analysis over weeks and months

### 8.3 Planned Methodology

| Audit | Duration | Focus |
|-------|----------|-------|
| **Idle baseline** | 12 hours | Parameter dynamics without user interaction |
| **Active interaction** | 12 hours | Parameter responses to varied user input |
| **Comparative analysis** | Post-audit | Idle vs. active dynamics across all three subsystems |
| **Longitudinal tracking** | Ongoing post-release | E-PQ trajectory, mood patterns, AURA evolution |

---

## 9. Conclusion

F.R.A.N.K.'s parameter architecture is a pragmatic synthesis of established theory and hard computational constraints.

**Mood** distributes VAD's valence dimension as a global modulator in [-1, 1] with dual hedonic adaptation, while AURA and E-PQ carry arousal and dominance information respectively.

**E-PQ's five dimensions** (precision, risk, empathy, autonomy, vigilance) are constrained by context window economy, LLM interpretability, approximate mapping to higher-order personality factors, and developmental observability.

**AURA** implements a novel approach to GWT's attention-broadcast mechanism: a 256×256 Game of Life where 8 zones produce emergent patterns that the system reads as introspective data. This goes beyond activation levels — it generates genuinely novel patterns from the interaction of simple rules.

The choices are defensible but not unique. Alternative parameterizations could work. What matters is that the overall architecture — **coupled, multi-timescale, grounded in system state, with emergent dynamics** — occupies a genuinely novel position between academic cognitive architectures (theoretically deep but partially implemented) and industry companion systems (practically complete but theoretically shallow).

> [!NOTE]
> The honest answer to "why these parameters?" is: because they satisfy simultaneous constraints from computational resources, LLM behavior, psychological theory, and architectural requirements — and because the coupled system produces richer behavior than any alternative tested. Whether they are optimal remains an empirical question that the planned audit sessions are designed to answer.

---

## 10. References

Ashton, M. C., & Lee, K. (2020). Objections to the HEXACO model of personality structure — and why those objections fail. *European Journal of Personality*, 34(4), 492–510.

Baars, B. J. (1988). *A Cognitive Theory of Consciousness*. Cambridge University Press.

Baars, B. J., & Franklin, S. (2009). Consciousness is computational: The LIDA model of global workspace theory. *International Journal of Machine Consciousness*, 1(1), 23–32.

Baharlouei, H., et al. (2023). ChatGPT for affective computing: Sentiment analysis, affect representation, and emotion elicitation. *arXiv:2309.01664*.

Bandura, A. (1989). Social cognitive theory. In R. Vasta (Ed.), *Annals of Child Development*, 6, 1–60.

Barrett, L. F. (2004). Feelings or words? Understanding the content in self-report ratings of experienced emotion. *Journal of Personality and Social Psychology*, 87(2), 266–281.

Barrett, L. F. (2017). *How Emotions Are Made: The Secret Life of the Brain*. Houghton Mifflin Harcourt.

Damasio, A. (1994). *Descartes' Error: Emotion, Reason, and the Human Brain*. Putnam.

Dayan, P., & Huys, Q. J. M. (2009). Serotonin in affective control. *Annual Review of Neuroscience*, 32, 95–126.

Dehaene, S., & Changeux, J.-P. (2011). Experimental and theoretical approaches to conscious processing. *Neuron*, 70(2), 200–227.

Desimone, R., & Duncan, J. (1995). Neural mechanisms of selective visual attention. *Annual Review of Neuroscience*, 18, 193–222.

DeYoung, C. G. (2006). Higher-order factors of the Big Five in a multi-informant sample. *Journal of Personality and Social Psychology*, 91(6), 1138–1151.

DeYoung, C. G., Peterson, J. B., & Higgins, D. M. (2002). Higher-order factors of the Big Five predict conformity. *Personality and Individual Differences*, 33(4), 533–552.

Digman, J. M. (1997). Higher-order factors of the Big Five. *Journal of Personality and Social Psychology*, 73(6), 1246–1256.

Dunbar, R. I. M. (1998). The social brain hypothesis. *Evolutionary Anthropology*, 6(5), 178–190.

Franklin, S., Ramamurthy, U., D'Mello, S., et al. (2007). LIDA: A computational model of global workspace theory and developmental learning. *AAAI Fall Symposium on AI and Consciousness*.

Frederick, S., & Loewenstein, G. (1999). Hedonic adaptation. In D. Kahneman et al. (Eds.), *Well-Being: The Foundations of Hedonic Psychology*. Russell Sage Foundation.

Goldstein, S., & Kirk-Giannini, C. D. (2024). A case for AI consciousness: Language agents and global workspace theory. *Manuscript*.

Kahneman, D. (2011). *Thinking, Fast and Slow*. Farrar, Straus and Giroux.

Kashdan, T. B., Barrett, L. F., & McKnight, P. E. (2015). Unpacking emotion differentiation. *Current Directions in Psychological Science*, 24(1), 10–16.

Lewis, M. D. (2005). Bridging emotion theory and neurobiology through dynamic systems modeling. *Behavioral and Brain Sciences*, 28(2), 169–194.

Mashour, G. A., Roelfsema, P., Changeux, J.-P., & Dehaene, S. (2020). Conscious processing and the global neuronal workspace hypothesis. *Neuron*, 105(5), 776–798.

Mehrabian, A., & Russell, J. A. (1974). *An Approach to Environmental Psychology*. MIT Press.

Mohammad, S. M. (2025). NRC VAD Lexicon v2: Norms for Valence, Arousal, and Dominance for over 55k English terms.

Pessoa, L. (2008). On the relationship between emotion and cognition. *Nature Reviews Neuroscience*, 9(2), 148–158.

Rosenthal, D. M. (2005). *Consciousness and Mind*. Oxford University Press.

Rushton, J. P., & Irwing, P. (2008). A General Factor of Personality from two meta-analyses of the Big Five. *Personality and Individual Differences*, 45(7), 679–683.

Russell, J. A. (1980). A circumplex model of affect. *Journal of Personality and Social Psychology*, 39(6), 1161–1178.

Ryan, R. M., & Deci, E. L. (2000). Self-determination theory and the facilitation of intrinsic motivation. *American Psychologist*, 55(1), 68–78.

Shannon, C. E. (1948). A mathematical theory of communication. *Bell System Technical Journal*, 27, 379–423.

Shanahan, M. (2006). A cognitive architecture that combines internal simulation with a global workspace. *Consciousness and Cognition*, 15(2), 433–449.

Tononi, G. (2004). An information integration theory of consciousness. *BMC Neuroscience*, 5(42).

Tulving, E. (1972). Episodic and semantic memory. In E. Tulving & W. Donaldson (Eds.), *Organization of Memory*. Academic Press.

Varela, F. J., Thompson, E., & Rosch, E. (1991). *The Embodied Mind*. MIT Press.
