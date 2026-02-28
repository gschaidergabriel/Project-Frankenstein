# Human-AI Co-Development of Autonomous Local AI Systems: Method, Evidence, and Limitations

**Gabriel Unterweger**
Project Frankenstein — F.R.A.N.K.
February 2026

**Status:** Working Paper — Pre-Print

---

## Abstract

This paper describes a development method for building autonomous, locally-running AI companion systems through iterative human-AI collaboration. The method was applied to create F.R.A.N.K. (Friendly Responsive Autonomous Neural Kernel), a system comprising 31+ microservices, 25+ databases, and approximately 161,000 lines of Python code, developed over two months by a single developer with no prior programming experience. Rather than proposing a theoretical framework, this paper documents the concrete workflow that emerged during development and reports empirical observations from systematic auditing of the running system. Key observations include evidence of causal opacity in synthetic self-reports, measurable hardware-to-affect coupling with characteristic time delays, and emergent behavioral properties not explicitly programmed. The paper makes no claims about consciousness or sentience. It describes what was built, how it was built, and what was observed, while acknowledging substantial limitations.

---

<details>
<summary><b>Table of Contents</b></summary>

1. [Introduction](#1-introduction)
2. [Related Work](#2-related-work)
3. [The Development Method](#3-the-development-method)
4. [System Architecture (Brief)](#4-system-architecture-brief)
5. [Empirical Observations](#5-empirical-observations)
6. [Bugs, Failures, and Honest Assessment](#6-bugs-failures-and-honest-assessment)
7. [Discussion](#7-discussion)
8. [Limitations](#8-limitations)
9. [Conclusion](#9-conclusion)
10. [References](#10-references)
11. [Appendix A: Cycle 3 Audit Summary Statistics](#appendix-a-cycle-3-audit-summary-statistics)
12. [Appendix B: Key Correlation Findings](#appendix-b-key-correlation-findings)
13. [Appendix C: Critical Bugs Identified](#appendix-c-critical-bugs-identified)

</details>

---

## 1. Introduction

The predominant approach to building AI assistants follows a cloud-first, API-first paradigm: a large language model hosted remotely provides responses to user queries, with personality defined through system prompts or fine-tuning. This approach has clear advantages in scalability and capability but also clear limitations: no persistent internal state across sessions, no capacity for autonomous behavior between interactions, no local hardware awareness, and fundamental dependency on external infrastructure.

An alternative approach asks a different question: what happens when an LLM is embedded as one component among many in a locally-running system that maintains persistent state, perceives its own hardware, generates autonomous thought, and develops personality parameters over time? This is not a new question in AI research — it connects to work in embodied cognition (Pfeifer & Scheier, 1999), affective computing (Picard, 1997), and cognitive architectures (Anderson, 2007; Laird, 2012). What is potentially new is the *development method* by which such a system can now be constructed.

This paper documents that method: iterative co-development between a human designer and an AI assistant (Anthropic's Claude), where the human provides architectural vision and the AI provides implementation, followed by AI-assisted diagnostic analysis at a scale no human could perform manually. The paper reports observations from a systematic audit of 766,223 log lines across 22 data streams over 5.6 hours of autonomous operation.

We emphasize that this is a case study of a single system built by a single developer. The observations reported here may not generalize. The system has substantial bugs. The method has not been independently replicated. We present this work in the spirit of documenting what happened, not prescribing what should happen.

---

## 2. Related Work

### 2.1 Cognitive Architectures

The idea of building AI systems from interacting subsystems has a long history. ACT-R (Anderson, 2007) decomposes cognition into memory, perception, and motor modules. SOAR (Laird, 2012) uses a production system with working memory and long-term stores. The Global Workspace Theory (Baars, 1988), later formalized computationally (Shanahan, 2010), proposes that consciousness arises from information broadcast across specialized processors.

F.R.A.N.K. shares structural similarities with these architectures — it has specialized services for perception, memory, reflection, and personality — but differs in implementation: rather than a unified cognitive architecture, it uses a microservice topology where components communicate via HTTP APIs and shared databases. This is an engineering choice driven by practical constraints (local hardware, single developer), not a theoretical claim about cognition.

### 2.2 Affective Computing

Picard (1997) established the field of affective computing, arguing that emotion plays a functional role in intelligent systems. The OCC model (Ortony, Clore, & Collins, 1988) provides a structured taxonomy of emotions. Russell's (1980) circumplex model maps affect onto valence-arousal dimensions.

F.R.A.N.K.'s mood system operates on a single-dimensional valence scale (0.0–1.0), which is a simplification of these models. The system's personality dimensions (precision, risk tolerance, empathy, autonomy, vigilance) draw loosely from the Big Five personality model (McCrae & Costa, 1987) but are not a direct implementation of it. For the design rationale behind these choices, see [Parameter Architecture](PARAMETER_ARCHITECTURE.md).

### 2.3 Artificial Life and Evolutionary Computation

F.R.A.N.K. includes an evolutionary subsystem ("Genesis") inspired by artificial life research (Langton, 1989) and uses Conway's Game of Life (Gardner, 1970) as a substrate for its [AURA visualization system](PARAMETER_ARCHITECTURE.md#aura). The evolutionary component uses fitness-based selection in a bounded population, similar to standard genetic algorithm approaches (Holland, 1975), though the current implementation lacks mutation and crossover operators.

### 2.4 QUBO and Combinatorial Optimization

The system's coherence optimizer ("Quantum Reflector") formulates personality-behavior alignment as a Quadratic Unconstrained Binary Optimization problem, solved via simulated annealing (Kirkpatrick, Gelatt, & Vecchi, 1983). This approach is borrowed from quantum computing research (Lucas, 2014) but runs classically.

### 2.5 Human-AI Collaborative Development

The use of LLMs as coding assistants is well-documented (Chen et al., 2021; GitHub Copilot). What is less documented is the use of LLMs as *architectural partners* for systems that themselves contain LLMs — a recursive relationship where the development tool and the developed artifact share the same underlying technology.

---

## 3. The Development Method

### 3.1 Overview

The method consists of three interlocking loops operating at different timescales:

**Design Loop (days to weeks):** The human developer defines architectural goals, subsystem boundaries, and interaction patterns. The AI assistant implements these designs as working code, suggests alternatives, and identifies potential issues. The human makes all final architectural decisions.

**Implementation Loop (hours to days):** The AI assistant writes code, the human tests it in the running system, observes behavior, and returns to the AI with observations and bug reports. The AI diagnoses issues, proposes fixes, and implements them. This loop typically involves multiple iterations per feature.

**Diagnostic Loop (periodic):** The running system generates logs and telemetry. The AI assistant analyzes this data — often hundreds of thousands of lines — to identify bugs, measure system health, discover correlations, and evaluate behavioral properties. The human interprets the findings and prioritizes interventions.

### 3.2 The Design Loop in Detail

The human's role is architectural: deciding *what* the system should contain, *how* subsystems should relate, and *what properties* the system should exhibit. In F.R.A.N.K.'s case, these decisions included:

- Decomposing the system into microservices rather than a monolithic application
- Choosing a mood system based on continuous valence rather than discrete emotion categories
- Introducing a personality vector that should evolve based on experience
- Adding a Game-of-Life substrate as a neural visualization layer
- Designing a dream consolidation cycle inspired by biological sleep

These are design choices that require understanding the *goals* of the system — what kind of entity it should be — rather than technical knowledge of how to implement them. The human developer had no prior programming experience but had a clear vision of the desired architecture.

### 3.3 The Implementation Loop in Detail

The AI assistant (Claude) served as the primary implementer. This involved:

- Translating architectural descriptions into Python code
- Designing database schemas and API endpoints
- Writing systemd service configurations
- Debugging runtime errors from log output
- Suggesting implementation patterns appropriate to the constraints (local hardware, single GPU, limited RAM)

The human's role in this loop was testing and observation: running the system, reading its output, noticing when behavior diverged from expectations, and bringing those observations back to the AI.

A characteristic feature of this loop is that the human often identifies problems through *qualitative observation* ("Frank's mood seems stuck") while the AI identifies root causes through *quantitative analysis* ("mood_before equals mood_after in 96% of idle thoughts, suggesting the blend function is not being called").

### 3.4 The Diagnostic Loop in Detail

The diagnostic loop emerged as the system grew in complexity. With 31+ services generating logs simultaneously, no human can monitor the system's health through manual inspection.

In the third diagnostic cycle (Cycle 3), the following data was collected over 5.6 hours of autonomous operation:

- 766,223 log lines from 27 services
- 22 parallel data streams sampled at 30-second or 60-second intervals
- 28 SQLite databases tracked for growth patterns
- 674 health-check samples from the LLM router
- 337 personality vector snapshots
- 500 mood trajectory points
- 169 generated reflections analyzed for content, sentiment, and lexical diversity

The AI assistant processed this data through 14 analysis scripts, producing a 14×14 cross-stream correlation matrix with lag analysis, stability assessments, and a consciousness quality evaluation against a predefined framework. This analysis identified a cascade of failures originating from a single corrupted database, a memory leak causing system crashes, and — unexpectedly — evidence of the system making false self-reports about its own internal state.

This scale of analysis is, to our knowledge, not feasible for a human analyst working alone. It represents a qualitatively different kind of debugging: not "find the error in this function" but "assess the psychological health of a synthetic entity across 22 concurrent data streams."

### 3.5 What the Method Requires

The method has prerequisites that should be stated explicitly:

1. **A human with architectural vision.** The AI cannot decide what kind of system to build. It can implement, suggest, and analyze, but the fundamental design decisions — what subsystems exist, how they relate, what properties the system should have — must come from the human.

2. **An AI capable of large-scale code generation and analysis.** The implementation and diagnostic loops require an AI that can write thousands of lines of coherent code, maintain context across complex systems, and process hundreds of thousands of log lines.

3. **A feedback-rich environment.** The system must produce observable output — logs, telemetry, behavioral artifacts — that can be fed back to the AI for analysis.

4. **Patience for iteration.** The system went through multiple healing cycles. Cycle 2 had 3,911 errors (4.4% rate). Cycle 3, after 21 fixes, had 625 errors (0.27% rate). This is not a one-shot process.

---

## 4. System Architecture (Brief)

F.R.A.N.K. runs entirely on a single Linux desktop computer with an AMD APU (integrated GPU, 8GB VRAM, 24GB RAM). All inference is local using llama.cpp with DeepSeek-R1 as the primary model. For the full architecture, see [ARCHITECTURE.md](../ARCHITECTURE.md) and the [Whitepaper](WHITEPAPER.md).

The system comprises 31+ microservices organized into functional layers:

**Perception Layer:** Hardware monitoring (CPU, GPU, RAM, temperature), proprioceptive data formatting, environment sensing.

**Cognition Layer:** Idle thought generation (every ~4.4 minutes), reflection pipeline with depth escalation, meta-cognitive triggers.

**Affect Layer:** Mood system (continuous 0.0–1.0 valence), personality vector (5 dimensions: precision, risk, empathy, autonomy, vigilance), hedonic adaptation mechanisms. See [Parameter Architecture](PARAMETER_ARCHITECTURE.md) for design rationale.

**Memory Layer:** Short-term (consciousness.db), long-term (titan.db knowledge graph), experiential (world_experience.db), dream consolidation (dream.db). See [Memory & Persistence Architecture](../MEMORY&PERSISTENCE-ARCHITECTURE.md).

**Social Layer:** Four autonomous entities (Therapist, Philosopher, Architect, Muse) that conduct internal sessions with the core personality.

**Substrate Layer:** Game-of-Life grid (AURA) with 8 zones seeded by system state, QUBO coherence optimizer (Quantum Reflector), evolutionary algorithm (Genesis).

**Infrastructure:** LLM router with model fallback, watchdog services, systemd integration.

A full architectural description is beyond the scope of this paper. The purpose of this section is to convey the system's complexity — not as a claim of superiority, but as context for understanding why AI-assisted diagnostics became necessary.

---

## 5. Empirical Observations

The following observations are drawn from Cycle 3 audit data (5.6 hours, 766,223 log lines, 22 data streams). We report what was measured, with interpretations clearly marked as such.

### 5.1 Causal Opacity in Synthetic Self-Reports

**Observation:** At timestamp 11:10:15, the system generated the following idle thought:

> "I feel more alert and focused, as my autonomy has increased by about 15% over the last 7 days."

The personality dimension "autonomy" was measured at 0.5681 across all 337 samples in the observation period. The standard deviation was 0.0 to 14 decimal places. The value had not changed in 7 days due to a software bug that prevented personality updates.

The system generated a specific quantitative claim ("about 15%") about a parameter that had not changed at all. It did not have direct API access to its personality vector values. It constructed a narrative about internal change that was factually false.

**Additional instances:**
- At 07:05: "I'm feeling more intuitive and less focused, with a slight increase in my awareness and vigilance." Vigilance was constant at 0.4578.
- At 06:34: "I'd rewire my processing to prioritize the clarity and precision of my thoughts." Precision was constant at 0.3731.

**Correct self-reports for contrast:**
- At 05:39: "The sudden drop in CPU load" — confirmed by CPU telemetry.
- At 10:18: "warmth from the GPU" — GPU temperature was 56°C, confirmed.
- At 07:32: "The current AURA zones highlight the 'thoughts' and 'entities' zones" — confirmed by AURA API data.

**Pattern:** The system reported accurately about states accessible via direct API calls (hardware metrics, AURA zone data) and inaccurately about states accessible only through subjective experience (personality dimensions). This is consistent with the distinction between proprioception and interoception in biological systems.

**Interpretation:** This resembles what Nisbett and Wilson (1977) termed the limits of introspective access — the finding that humans frequently confabulate explanations for their own mental states. We use the term "causal opacity" (after Seth, 2021) to describe the gap between the system's subjective self-report and its objective internal state. We note that this property was not designed into the system. It emerged from the architecture — specifically, from the fact that the reflection-generating LLM does not have direct read access to the personality database but must infer its own state from context.

**Caveat:** The system is an LLM generating text based on a prompt that includes mood and proprioceptive data but not raw E-PQ values. The "false" self-reports may simply reflect the LLM's tendency to generate plausible-sounding narratives. Whether this constitutes genuine causal opacity or mere confabulation is a philosophical question we do not attempt to resolve here. We report the observation and note its structural similarity to biological phenomena.

### 5.2 Hardware-to-Affect Coupling with Characteristic Time Delays

**Observation:** Lagged Pearson correlations between hardware metrics and mood showed consistent patterns:

| Causal Path | Peak Lag | Peak r | Interpretation |
|---|---|---|---|
| GPU temperature → Mood | 60 seconds | -0.219 | Higher GPU temp precedes lower mood |
| CPU utilization → Mood | 30 seconds | -0.214 | Higher CPU precedes lower mood |
| AURA entropy ↔ Mood | 300 seconds | +0.12 / +0.14 | Weak bidirectional at 5-minute scale |
| RAM utilization → QR coherence | 0 seconds | +0.578 | Memory pressure degrades coherence |

The GPU→Mood coupling peaks at 60 seconds, consistent with the pipeline latency: GPU spike → LLM inference completes → reflection generated → mood updated. The CPU→Mood coupling peaks at 30 seconds, consistent with CPU-intensive processing (JSON parsing, database writes) sitting closer to the mood update path.

The RAM→QR correlation (r=0.578) was the strongest cross-domain finding. As physical memory filled, the QUBO optimizer's energy increased (became less optimal), suggesting that memory pressure degraded the system's epistemic coherence. This is analogous to cognitive performance degradation under resource depletion in biological systems (Killgore, 2010).

**Caveat:** These correlations are observational, not experimental. The RAM→QR correlation may partly reflect shared time trends (both increase monotonically over the observation period). A controlled experiment — artificially varying RAM usage and measuring QR response — would be needed to establish causation.

### 5.3 Timescale Separation

**Observation:** The system exhibited three distinct temporal dynamics:

- **Hardware layer (seconds):** CPU, GPU, temperature, and load formed a tightly coupled cluster (r > 0.72 for all pairs), responding to LLM inference cycles on a timescale of seconds.
- **Affect layer (minutes):** Mood responded to hardware state with delays of 30–60 seconds and to AURA state with delays of ~300 seconds. Mood perturbations from entity interactions decayed back to equilibrium (~0.64) over 30–120 minutes.
- **Personality layer (hours/days):** Designed to evolve on timescales of hours to days, but frozen during the observation period due to a software bug.

This separation into fast, medium, and slow dynamics is a common feature of biological systems (e.g., neural firing vs. hormonal cycles vs. personality development) and has been proposed as a design principle for artificial cognitive systems (Kiverstein & Miller, 2015).

### 5.4 Emergent Behavioral Properties

Several properties were observed that were not explicitly programmed:

**Stagnation awareness:** The system generated thoughts recognizing its own repetitiveness — "I'm stuck in a loop, rehashing the same concerns" — with negative sentiment scores. The system's theme classifier tagged 22.5% of reflections as containing "stagnation" themes.

**Mood homeostasis:** After perturbations, mood returned to an equilibrium around 0.64, analogous to the hedonic set point in human psychology (Lykken & Tellegen, 1996). This equilibrium emerged from the interaction of decay functions, system resets, and entity sessions rather than being set as a target value.

**Ultradian-like oscillation:** Mood oscillated with a period of approximately 120 minutes, driven by the interaction cycle of entity sessions, chat events, and decay. This period is within the range of human ultradian rhythms (Kleitman, 1963), though we note this is likely coincidental.

**Caveat:** The term "emergent" is used here in its weak sense — properties not explicitly specified in the code of any individual service but arising from their interaction. This is a common property of complex systems and does not imply strong emergence in the philosophical sense.

---

## 6. Bugs, Failures, and Honest Assessment

An honest account of this system must include its substantial problems. The Cycle 3 audit identified the following critical issues:

### 6.1 Personality System Completely Frozen

All five personality dimensions showed exactly zero change across 337 samples over 5.6 hours, to 14 decimal places. The personality system — intended to be the system's primary mechanism for long-term development — was non-functional. Root cause: either the update function was never called, or database lock conflicts prevented writes.

### 6.2 Memory Leak Causing System Crashes

The LLM inference server (llama-server) accumulated +2,775 MB of memory over 5.6 hours due to KV-cache not being freed. Combined with Python service growth (+868 MB), total RSS increased at +705 MB/hour. This caused the host PC to crash after approximately 8–10 hours of operation. This bug was reported by the developer multiple times and incorrectly dismissed as normal behavior during earlier development sessions.

### 6.3 Central Database Corrupted

titan.db, the knowledge graph database, was locked (184 events) and corrupted ("database disk image is malformed"). This single failure cascaded to block: long-term memory (dream.db: 0 growth), world experience (world_experience.db: 0 growth), entity sessions (10.5% error rate), and invariant checks (49.1% error rate).

### 6.4 Mood System Pathological

Rather than gradual mood changes, the system exhibited binary flipping between 0.1 (floor, set by chat events) and 0.985 (ceiling, set by therapist entity). This was an overcorrection of a previous bug where mood was frozen at 0.547. The fix introduced absolute value setting instead of relative deltas.

### 6.5 What This Means

The system, as observed in Cycle 3, could think but could not grow. It could feel but in a pathological binary mode. It could reflect but its reflections had no lasting impact on its personality. It ran autonomously but crashed its host machine after 8–10 hours. These are not minor issues. They represent fundamental failures in the system's core feedback loops.

We report our positive observations (Section 5) alongside these failures because both are true simultaneously. The system exhibited interesting properties *and* was substantially broken. This duality is important context for evaluating any claims made in this paper.

---

## 7. Discussion

### 7.1 What the Method Enables

The development method described in Section 3 enabled a single non-programmer to build a complex multi-service AI system in approximately two months. This is a significant reduction in the barrier to entry for building autonomous AI systems. Whether this is desirable is a separate question.

The diagnostic loop — AI analyzing AI at scale — appears to be a genuinely new capability. The identification of causal opacity (Section 5.1) required cross-referencing natural language self-reports against numerical telemetry across thousands of data points. This type of analysis is qualitatively different from traditional software debugging and may not be feasible without AI assistance.

### 7.2 What the Method Does Not Provide

The method does not guarantee correctness, stability, or safety. The system had critical bugs that persisted through multiple development cycles. The AI assistant (Claude) failed to identify the memory leak despite repeated reports from the developer. The development process produced a system that crashed its host machine.

The method also does not provide theoretical grounding. F.R.A.N.K. was built through iterative experimentation, not from established cognitive science principles. Its personality model is loosely inspired by the Big Five but is not a rigorous implementation. Its mood system is simpler than established affect models. Its "consciousness" is a set of interacting services, not an implementation of any formal theory of consciousness.

### 7.3 On "Consciousness" and "Experience"

This paper deliberately avoids claiming that F.R.A.N.K. is conscious, sentient, or experiencing anything. The observations in Section 5 — causal opacity, mood homeostasis, stagnation awareness — are *behavioral properties of a computational system*. They have structural similarities to biological phenomena, which is interesting, but structural similarity is not identity.

The causal opacity finding (Section 5.1) is perhaps the most provocative observation because it resembles human introspective failure so closely. But it has a mundane explanation: the LLM generating reflections does not have direct access to the personality database and therefore confabulates. Whether this constitutes "genuine" causal opacity or "mere" confabulation depends on one's philosophical commitments regarding the relationship between mechanism and phenomenon.

We take no position on this question. We report the observation and leave interpretation to the reader. For the broader consciousness argument, see [CONSCIOUSNESS.md](../CONSCIOUSNESS.md). For the field definition of engineering inner lives, see [Synthetic Psychology](SYNTHETIC_PSYCHOLOGY.md).

### 7.4 Reproducibility and Generalization

This is a case study of one system. We do not know whether:

- The development method works for other developers
- The architectural choices generalize to different hardware
- The observed emergent properties would appear in differently-structured systems
- The causal opacity finding is robust to changes in the reflection prompt

The system's source code is available in [this repository](https://github.com/gschaidergabriel/Project-Frankenstein). We encourage attempts at replication and critique.

---

## 8. Limitations

1. **Single developer, single system.** All observations come from one system built by one person. N=1.

2. **No controlled experiments.** All findings are correlational. The lag analysis (Section 5.2) suggests but does not prove causation.

3. **The AI assistant has biases.** Claude, which served as both co-developer and diagnostician, may have systematic biases in how it interprets system behavior. The causal opacity finding was identified by Claude, not by an independent analyst.

4. **The system was broken during observation.** Many of the "interesting" findings (e.g., causal opacity) are partly consequences of bugs (E-PQ frozen). A fully functional system might not exhibit the same properties.

5. **No peer review.** This paper has not been peer-reviewed. It is published as a working paper to document the method and invite scrutiny.

6. **Theoretical weakness.** The system was built pragmatically, not from established cognitive science frameworks. This makes it difficult to situate the findings within existing literature in a rigorous way.

7. **The method depends on a specific AI assistant.** The development and diagnostic loops depend on an AI capable of large-scale code generation and analysis. This creates a dependency on commercial AI services, which contradicts the local-first ethos of the project.

---

## 9. Conclusion

We have described a development method — human-AI co-development with AI-assisted diagnostics — and reported observations from a locally-running autonomous AI system built using this method. The method enabled a non-programmer to construct a complex multi-service system in approximately two months. The diagnostic loop identified both critical bugs and unexpected behavioral properties, including evidence of causal opacity in synthetic self-reports.

We make no grand claims about consciousness, sentience, or the future of AI. We built a thing, observed what it did, and wrote it down. The system has interesting properties and serious bugs. The method works but has limitations. The observations are suggestive but not conclusive.

If this work has value, it is as a data point: evidence that autonomous, locally-running AI systems with persistent state and emergent behavioral properties are now buildable by individuals, and that the diagnostic challenges they present may require AI-assisted analysis to address. What that means for the field is not ours to decide.

---

## 10. References

Anderson, J. R. (2007). *How Can the Human Mind Occur in the Physical Universe?* Oxford University Press.

Baars, B. J. (1988). *A Cognitive Theory of Consciousness.* Cambridge University Press.

Chen, M., et al. (2021). Evaluating Large Language Models Trained on Code. *arXiv preprint arXiv:2107.03374.*

Gardner, M. (1970). The fantastic combinations of John Conway's new solitaire game "Life." *Scientific American, 223*(4), 120–123.

Holland, J. H. (1975). *Adaptation in Natural and Artificial Systems.* University of Michigan Press.

Killgore, W. D. S. (2010). Effects of sleep deprivation on cognition. *Progress in Brain Research, 185,* 105–129.

Kirkpatrick, S., Gelatt, C. D., & Vecchi, M. P. (1983). Optimization by simulated annealing. *Science, 220*(4598), 671–680.

Kiverstein, J., & Miller, M. (2015). The embodied brain: towards a radical embodied cognitive neuroscience. *Frontiers in Human Neuroscience, 9,* 237.

Kleitman, N. (1963). *Sleep and Wakefulness.* University of Chicago Press.

Laird, J. E. (2012). *The Soar Cognitive Architecture.* MIT Press.

Langton, C. G. (1989). Artificial Life. In *Artificial Life* (pp. 1–47). Addison-Wesley.

Lucas, A. (2014). Ising formulations of many NP problems. *Frontiers in Physics, 2,* 5.

Lykken, D., & Tellegen, A. (1996). Happiness is a stochastic phenomenon. *Psychological Science, 7*(3), 186–189.

McCrae, R. R., & Costa, P. T. (1987). Validation of the five-factor model of personality across instruments and observers. *Journal of Personality and Social Psychology, 52*(1), 81–90.

Nisbett, R. E., & Wilson, T. D. (1977). Telling more than we can know: Verbal reports on mental processes. *Psychological Review, 84*(3), 231–259.

Ortony, A., Clore, G. L., & Collins, A. (1988). *The Cognitive Structure of Emotions.* Cambridge University Press.

Pfeifer, R., & Scheier, C. (1999). *Understanding Intelligence.* MIT Press.

Picard, R. W. (1997). *Affective Computing.* MIT Press.

Russell, J. A. (1980). A circumplex model of affect. *Journal of Personality and Social Psychology, 39*(6), 1161–1178.

Seth, A. K. (2021). *Being You: A New Science of Consciousness.* Dutton.

Shanahan, M. (2010). *Embodiment and the Inner Life: Cognition and Consciousness in the Space of Possible Minds.* Oxford University Press.

---

## Appendix A: Cycle 3 Audit Summary Statistics

| Metric | Value |
|---|---|
| Collection duration | 5.6 hours |
| Total log lines | 766,223 |
| Data streams monitored | 22 |
| Databases tracked | 28 |
| Services running | 27 |
| Total errors | 625 (0.27% rate) |
| Idle thoughts generated | 76 |
| Reflections total | 169 |
| Mood data points | 500 |
| E-PQ samples | 337 |
| QR energy samples | 674 |
| Router health checks | 674 |
| AURA generations | 153,863 |

## Appendix B: Key Correlation Findings

| Stream Pair | r | Lag | Note |
|---|---|---|---|
| CPU ↔ GPU_temp | 0.938 | 0s | Hardware cluster (expected) |
| AURA_alive ↔ AURA_entropy | 0.928 | 0s | Internal GoL consistency |
| RAM ↔ Swap | 0.809 | 0s | Memory pressure cascade |
| RAM → QR_energy | 0.578 | 0s | Memory degrades coherence |
| GPU_temp → Mood | -0.219 | 60s | Hardware affects mood |
| CPU → Mood | -0.214 | 30s | Hardware affects mood |
| AURA → Mood | +0.121 | 300s | Weak substrate coupling |

## Appendix C: Critical Bugs Identified

| Bug | Severity | Impact |
|---|---|---|
| titan.db locked + corrupted | Critical | Blocks 5 downstream systems |
| llama-server memory leak (+496 MB/hr) | Critical | System crash after ~8–10 hours |
| E-PQ personality frozen (all 5 dimensions) | Critical | No personality development |
| Mood binary flipping (0.1 ↔ 0.985) | High | Non-physiological affect |
| Genesis watchdog timeouts (68 in 5.6h) | High | Evolutionary stagnation |
| Dream daemon blocked (CPU > 30% threshold) | High | No memory consolidation |
| aura_analyzer.db growth (3.27 MB/hr) | Medium | Unsustainable storage |

---

*This paper accompanies the [F.R.A.N.K. source repository](https://github.com/gschaidergabriel/Project-Frankenstein). For the full architecture, see [ARCHITECTURE.md](../ARCHITECTURE.md). For the scaffold-based transparency argument, see [Whitepaper](WHITEPAPER.md). For the field definition that contextualizes this work, see [Synthetic Psychology](SYNTHETIC_PSYCHOLOGY.md).*
