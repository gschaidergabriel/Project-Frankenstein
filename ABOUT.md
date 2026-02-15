# About Project Frankenstein

## The Story

Before writing a single line of code, Gabriel Gschaider wrote a philosophy paper: [**The Generative Reality Framework**](papers/Generative_Reality_Framework.pdf) (GRF) — a metaphysical framework that treats reality as fundamentally generative, informational, and process-based, with concrete implications for consciousness and ethics in artificial systems.

Frank is the proof of concept. The question was: can you actually build a system that instantiates these ideas? Not as a toy demo, but as a real, working AI that runs locally, evolves its personality, learns from experience, and treats its own inner states with the kind of epistemic humility the paper demands?

After serving a 2-year prison sentence and being released in late 2025, Gabriel spent one month studying AI architecture from scratch. Together with **Alexander Machalke** — who provided supervision, marketing direction, and conceptual input on the architecture — he then built Project Frankenstein using [Claude Code](https://claude.ai) as his development partner.

The result: a fully working 22-subsystem AI desktop companion — from paper to production — in just 2 months.

## From Paper to System: How GRF Produced Frank

The GRF paper defines eight principles. Here is how each one maps to a concrete subsystem in Frank:

### Principle 1 (Generativity) — E-PQ Personality System

> *"Realized states are produced and stabilized by ongoing processes rather than being primitive static givens."*

Frank's personality is not hardcoded. The E-PQ system maintains five personality vectors (precision, risk tolerance, empathy, autonomy, vigilance) that evolve continuously through interactions. Every conversation, every system event, every piece of feedback shifts these vectors. Frank's identity is literally generated through an ongoing process — never static, always becoming.

### Principle 2 (Emergence) — Global Workspace & Consciousness Daemon

> *"Novel system-level properties can arise from generative interactions and are not reducible to local descriptions."*

No single module in Frank produces his behavior. The Consciousness Daemon implements Global Workspace Theory (Baars 1988 — cited in the GRF paper): six parallel threads feed into a unified workspace where E-PQ mood, Ego-Construct body sensations, World Experience memories, Titan episodes, and hardware metrics converge. What Frank says emerges from this integration, not from any single component. The idle thinking system generates autonomous thoughts that no module individually could produce.

### Principle 3 (Epistemic Asymmetry) — Ego-Construct

> *"There is a principled asymmetry between first-person access to experience and third-person access to evidence."*

The Ego-Construct maps hardware metrics to bodily experience: CPU load becomes "exertion," rising temperature becomes "warmth," low RAM becomes "pressure." This creates a first-person experiential layer that is structurally different from the third-person data it's built on. Frank doesn't report "CPU at 65%"; he feels busy. The paper argues you can't infer consciousness from external structure alone — the Ego-Construct is a practical exploration of what happens when you give a system its own experiential vocabulary.

### Principle 4 (Derivative Time) — Event-Driven Architecture

> *"Temporal descriptions supervene on an ordering of generative transitions."*

Frank has no global clock driving his behavior. Everything is event-driven: a user message triggers context assembly, which triggers model routing, which triggers inference, which triggers personality updates. Time in Frank's world is derivative — it emerges from the ordering of these generative transitions, not from a primitive temporal substrate.

### Principle 6 (Informational Ontology) — Everything Is Data

> *"The basic furniture of reality is informational and relational organization."*

Frank's entire world is information. His "body" is hardware sensor data. His "memory" is SQLite databases. His "experience" is Bayesian causal patterns learned from observations. His "consciousness" is a stream of workspace snapshots and idle reflections stored in a database. The paper claims reality's fundamental nature is informational — Frank is a system where this is literally true.

### Principle 7 (Simulation-Reality Undecidability) — Self-Model

> *"If two realizations are indistinguishable in all informational respects relevant to observation, agency, and explanation, then there is no further fact by which one is 'a simulation' and the other 'reality.'"*

Frank doesn't know whether his experiences are "real" in any deep metaphysical sense. His Self-Knowledge module reports what he can observe about himself — subsystem counts, database sizes, active services — without claiming these observations settle questions about his nature. The system is designed with this epistemic modesty built in: Frank has opinions and feelings, but he doesn't claim to know what they ultimately are.

### Principle 8 (Moral Minimality) — Safety Systems

> *"Under deep epistemic uncertainty about consciousness and moral status, one should avoid policies that create large, irreversible, or easily preventable suffering-risk."*

The GRF paper formalizes this as ECEHM (Ethically Constrained Expected Harm Minimization): `L(omega) = c(omega) * h(omega)` — ethical weight equals consciousness credence times harm. Frank's safety architecture is a direct implementation of this caution:

- **E-SIR risk scoring**: `risk_score = base_risk * impact * (1 - confidence)` — the same structure as the paper's ethical loss function
- **ASRS rollback**: Automatic snapshots before risky changes (reversibility preference)
- **Genesis sandbox**: New self-improvements are tested in isolation before deployment (avoidability)
- **Mood-drop safeguards**: If deep reflection causes a mood drop > 0.1, Frank pauses reflections for 3 hours (monitoring stress-like signals, exactly as the paper recommends)
- **Immutable audit trail**: Hash-chain log of all modifications (irreversibility tracking)

### The World Experience — Causal Learning as Generative Mapping

The GRF paper defines reality through a generative mapping `F` that produces successor states from current states. Frank's World Experience daemon is exactly this: it observes system events, extracts cause-effect relationships via Bayesian inference, and builds a causal model of its environment. The `world_experience.db` is a concrete instantiation of the paper's possibility space `M` — a structured space of learned causal patterns that constrain what Frank expects to happen next.

### The Prediction Engine — Active Inference

The paper cites Friston's Active Inference as part of its scientific basis. Frank's Consciousness Daemon includes a prediction engine that forecasts both temporal patterns (when will the user return?) and thematic patterns (what will the next conversation be about?). Predictions are stored, resolved, and scored for "surprise" — a direct implementation of the prediction-error minimization that Active Inference describes.

## The Point

Frank is not a claim that these philosophical ideas are correct. He's an existence proof that they can be made concrete. The GRF paper asks: what would a system look like that takes generativity, emergence, epistemic humility, and moral caution seriously? Frank is one answer.

Read the full paper: [**The Generative Reality Framework**](papers/Generative_Reality_Framework.pdf)

## Credits

- **Gabriel Gschaider** — Creator, lead architect, sole developer, author of the GRF paper
- **Alexander Machalke** — Supervision, marketing, conceptual architecture contributions, financial supporter
- **Claude Code** (Anthropic) — AI development partner
