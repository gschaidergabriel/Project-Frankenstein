# Original Contributions

> [!NOTE]
> Frank builds on established theories and open-source tools. This document distinguishes what is novel from what is adapted. For the formal mapping of theory to code, see the [GRF → Frank Bridge](papers/GRF_IMPLEMENTATION_BRIDGE.md).

---

## New Architectures (No Published Precedent)

| Contribution | What's new | What it builds on |
|---|---|---|
| **AURA Quantum GoL** | 256×256 grid where each cell is an 8D weighted type vector (not binary alive/dead) representing 8 subsystems. Cells undergo diffusion (gradient blending between neighbors), decoherence (crystallization into dominant types), and superposition (color overlay during transitions). Seeded by live subsystem data — thoughts, mood, entities, hardware — creating a functional closed loop: internal state → cell seeding → GoL evolution → emergent patterns → AI reflects on patterns → state changes. The AI decides itself when to read its own grid (Headless Introspect). | Quantum GoL variants exist in physics research (3D models, reversible rules, entanglement-based CAs), but none integrate with a running AI system, none use persistent personality/hardware feedback, and none have the AI itself analyze and reflect on the emergent patterns. Dennett used GoL as a philosophical *analogy*; AURA makes it a functional self-awareness mechanism. |
| **AURA Pattern Analyzer** | 4-level hierarchical emergence recognition: L0 captures (2s grid snapshots with density, entropy, zone patterns), L1 blocks (~100s narrative + semantic profile), L2 meta (~500s cross-block trends, anomalies, predictions), L3 deep (~1500s trajectory evolution, accumulated wisdom). Self-learning pattern library with confidence scores, relevance decay, co-occurrence tracking, and transition maps. Discovered patterns feed back to Frank for reflection. | CA pattern classification exists in computational biology and physics; a system that discovers GoL patterns in its own consciousness grid, builds a self-updating library, and feeds findings back to the AI for reflection does not. |
| **Self-Determined Introspection** | Frank decides *himself* whether and when to examine his own consciousness state | Metacognition in AI is discussed theoretically; self-initiated introspection as a running feature is new |
| **Genesis Daemon** | Improvement ideas as evolving organisms in a primordial soup with motivational fields, crystallization, and approval gates | Google's digital primordial soup (Agüera y Arcas et al., 2024) breeds self-replicating *code*; Genesis breeds *ideas* that pass through safety gates |
| **E-PQ Personality Engine** | 5-vector model that evolves through user interaction, entity conversations, and dream consolidation | Big Five personality in AI is well-studied; E-PQ is designed for bidirectional co-evolution with autonomous entities |
| **Entity–E-PQ Feedback Loop** | 4 entities with own personality vectors fire E-PQ events; micro/macro adjustments; monotonically non-decreasing rapport | Multi-agent systems exist; personality co-evolution between entities and host AI does not |
| **Ego-Construct / Computational Embodiment** | Hardware→body mapping (CPU→strain, thermals→warmth, latency→clarity) as closed sensorimotor loop; fourth paradigm alongside robotic, simulated, and disembodied AI | Lundy-Bryan (2025) speculated about computational embodiment; Frank implements it as a running module |
| **Proprioception Injection** | Hardware sensor data as mandatory sensory layer in every consciousness call — not optional context but obligatory input | No precedent for treating hardware telemetry as non-negotiable proprioceptive input to an LLM |
| **Dream Daemon** | 3-phase sleep analogue (Replay → Synthesis → Consolidation), 60 min/day budget, interrupt-safe resume | Sleep-inspired consolidation exists in neural network research and agent memory; an LLM-based daemon with phased processing and budget management is new |
| **Invariants Engine** | Physics-inspired conservation laws as safety constraints: energy conservation, entropy bound, core kernel protection | No precedent for applying physical conservation law analogues as AI safety invariants |
| **Consciousness Stream** | 10 parallel threads (GWT, AST, perception, experience space, goals, reflection, predictions, mood, coherence, proprioception) as running daemons | GWT was proposed theoretically (Goldstein & Kirk-Giannini, 2024); Frank runs it as a 10-thread daemon |

---

## New Combinations of Existing Ideas

| Contribution | What's combined |
|---|---|
| **Quantum Reflector** | QUBO optimization (20 binary variables, 5 one-hot groups, O(n) delta-energy simulated annealing) + epistemic reasoning → coherence checking for AI belief states. Reads AURA grid anomalies and zone contrast, feeds back into E-PQ personality vectors. Bridges quantum-inspired optimization with embodied self-model. |
| **Autonomous Entity System** | Multi-agent architecture + daily scheduling + idle-gated activation + personality co-evolution |
| **Gaming Mode** | Game detection + GPU resource management + anti-cheat safety + automatic consciousness reduction |
| **Skill Hybrid Format** | Native Python plugins + LLM-mediated OpenClaw skills (SKILL.md with YAML) + hot-reload |

---

## Not Original (Existing Technologies and Theories)

> [!TIP]
> Standing on the shoulders of giants — these are the foundations Frank is built on.

Global Workspace Theory (Baars, 1988) · Attention Schema Theory (Graziano, 2013) · Embodied Cognition Theory (Varela, Thompson & Rosch, 1991) · Big Five personality research · Conway's Game of Life (1970) · Sleep-dependent memory consolidation (neuroscience) · QUBO / Simulated Annealing (optimization research) · Microservice architecture · llama.cpp, Ollama, whisper.cpp, Piper, DeepSeek-R1 · Firejail, xdotool, wmctrl · CalDAV, DuckDuckGo, Tor/Ahmia
