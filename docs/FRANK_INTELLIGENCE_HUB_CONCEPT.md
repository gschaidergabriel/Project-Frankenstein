# F.I.H. - Frank's Intelligence Hub
## Central Self-Improvement System

### Vision

The F.A.S. Popup becomes the **central nervous system** for ALL self-improvement functions. Not just GitHub features, but EVERYTHING that makes Frank better flows through this system.

```
                    ┌─────────────────────────────────────┐
                    │     F.I.H. - INTELLIGENCE HUB       │
                    │   "The Brain of Frank's Growth"     │
                    └─────────────────┬───────────────────┘
                                      │
        ┌─────────────────────────────┼─────────────────────────────┐
        │                             │                             │
        ▼                             ▼                             ▼
┌───────────────┐           ┌───────────────┐           ┌───────────────┐
│   F.A.S.      │           │   E-CPMM      │           │  USER         │
│   GitHub      │           │   Training    │           │  FEEDBACK     │
│   Discovery   │           │   Insights    │           │  & REQUESTS   │
└───────┬───────┘           └───────┬───────┘           └───────┬───────┘
        │                           │                           │
        └───────────────────────────┼───────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
        ▼                           ▼                           ▼
┌───────────────┐           ┌───────────────┐           ┌───────────────┐
│   INTERNAL    │           │  PERFORMANCE  │           │   EXTERNAL    │
│   ANALYSIS    │           │  OPTIMIZER    │           │   TOOLS       │
│   (Self-Check)│           │  (Auto-Tune)  │           │   (MCP/APIs)  │
└───────┬───────┘           └───────┬───────┘           └───────┬───────┘
        │                           │                           │
        └───────────────────────────┴───────────────────────────┘
                                    │
                                    ▼
                    ╔═══════════════════════════════════╗
                    ║      UNIFIED PROPOSAL QUEUE       ║
                    ║   Confidence Scoring & Ranking    ║
                    ╚═══════════════════════════════════╝
                                    │
                                    ▼
                    ╔═══════════════════════════════════╗
                    ║     CYBERPUNK PROPOSAL POPUP      ║
                    ║   User Reviews & Approves         ║
                    ╚═══════════════════════════════════╝
                                    │
                                    ▼
                    ┌───────────────────────────────────┐
                    │      INTELLIGENT INTEGRATION      │
                    │   Frank continuously improves     │
                    │   - with the User as guide        │
                    └───────────────────────────────────┘
```

---

## The 6 Intelligence Sources

### 1. F.A.S. GitHub Discovery (exists)
```python
class GitHubSource(IntelligenceSource):
    """
    Finds new tools/patterns on GitHub.
    - Scout scraping
    - Interest scoring
    - Sandbox testing
    """
    source_type = "github"
    confidence_weight = 0.9  # High confidence because tested
```

### 2. E-CPMM Training Insights (NEW)
```python
class TrainingSource(IntelligenceSource):
    """
    Learns from training what could be improved.
    - Identifies recurring error patterns
    - Discovers missing tools during tasks
    - Suggests optimizations based on learning curve
    """
    source_type = "training"
    confidence_weight = 0.85

    def extract_insights(self, training_log: Path) -> List[Proposal]:
        """
        Analyzes training logs and extracts improvement proposals.

        Examples:
        - "Frank tried to parse JSON 3x and failed"
          -> Proposal: "More robust JSON parser"

        - "Task 'API Call' timed out 5x"
          -> Proposal: "Retry logic with backoff"

        - "User asked for 'format code' 10x"
          -> Proposal: "Auto-formatter tool"
        """
        pass
```

### 3. User Feedback & Requests (NEW)
```python
class UserFeedbackSource(IntelligenceSource):
    """
    Collects and analyzes user feedback.
    - Explicit feature requests
    - Implicit wishes from conversations
    - Complaints/frustrations -> improvements
    """
    source_type = "user_feedback"
    confidence_weight = 1.0  # User request = highest priority

    def collect_feedback(self):
        """
        Sources:
        - Chat history analysis
        - Explicit /request commands
        - Sentiment from conversations
        - Abandoned tasks (frustration?)
        """
        pass
```

### 4. Internal Self-Analysis (NEW)
```python
class SelfAnalysisSource(IntelligenceSource):
    """
    Frank analyzes itself.
    - Code review of its own tools
    - Performance bottlenecks
    - Unused/dead code
    - Security audits
    """
    source_type = "self_analysis"
    confidence_weight = 0.7

    def analyze_self(self):
        """
        Checks:
        - Which tools are never used?
        - Which functions are slow?
        - Where is there code duplication?
        - Which dependencies are outdated?
        """
        pass
```

### 5. Performance Optimizer (NEW)
```python
class PerformanceSource(IntelligenceSource):
    """
    Continuous performance monitoring.
    - Response time tracking
    - Memory usage
    - Startup time
    - Resource efficiency
    """
    source_type = "performance"
    confidence_weight = 0.8

    def monitor(self):
        """
        Identifies:
        - Slow functions (> 1s)
        - Memory leaks
        - Inefficient loops
        - Caching opportunities
        """
        pass
```

### 6. External Tools Integration (NEW)
```python
class ExternalToolsSource(IntelligenceSource):
    """
    Discovers useful external tools/APIs.
    - MCP server discovery
    - Searching API catalogs
    - Tool recommendations from community
    """
    source_type = "external"
    confidence_weight = 0.75

    def discover(self):
        """
        Searches for:
        - New MCP servers that fit Frank
        - APIs that simplify frequent tasks
        - Tools that could fulfill user requests
        """
        pass
```

---

## Unified Proposal Schema

```python
@dataclass
class UnifiedProposal:
    """
    An improvement proposal from any source.
    Unified format for all intelligence sources.
    """
    id: int
    source_type: str          # "github", "training", "user", "self", "perf", "external"
    category: str             # "tool", "optimization", "bugfix", "feature", "integration"
    name: str
    description: str

    # Why this matters
    problem_statement: str    # What is the problem?
    proposed_solution: str    # What is the solution?
    expected_benefit: str     # What is the benefit?

    # Confidence & Priority
    confidence_score: float   # 0.0 - 1.0
    priority_score: float     # Calculated from multiple factors
    urgency: str              # "low", "medium", "high", "critical"

    # Evidence
    evidence: List[str]       # Why does Frank believe this is good?
    related_events: List[str] # Training errors, user requests, etc.

    # Implementation
    complexity: str           # "trivial", "simple", "moderate", "complex"
    estimated_impact: str     # "minor", "moderate", "major", "transformative"
    dependencies: List[str]   # What needs to exist first?

    # Status
    status: str               # "discovered", "testing", "ready", "approved", etc.
    created_at: datetime
    source_data: dict         # Raw data from source
```

---

## Intelligent Prioritization

```python
class ProposalRanker:
    """
    Ranks proposals intelligently based on multiple factors.
    """

    def calculate_priority(self, proposal: UnifiedProposal) -> float:
        """
        Priority Score Formula:

        priority = (
            confidence * 0.25 +           # How confident are we?
            user_relevance * 0.30 +       # Did the user ask for this?
            impact * 0.20 +               # How big is the benefit?
            urgency * 0.15 +              # How urgent?
            recency * 0.10                # How recent?
        )

        Multipliers:
        - User Request: 1.5x
        - Bugfix: 1.3x
        - Training Insight: 1.2x
        - Performance Critical: 1.4x
        """

        # Base scores
        confidence = proposal.confidence_score
        impact = self._score_impact(proposal.estimated_impact)
        urgency = self._score_urgency(proposal.urgency)

        # User relevance - highest weight
        user_relevance = self._calculate_user_relevance(proposal)

        # Recency bonus
        age_hours = (datetime.now() - proposal.created_at).total_seconds() / 3600
        recency = max(0, 1 - (age_hours / 168))  # Decays over 1 week

        # Calculate base priority
        priority = (
            confidence * 0.25 +
            user_relevance * 0.30 +
            impact * 0.20 +
            urgency * 0.15 +
            recency * 0.10
        )

        # Apply multipliers
        if proposal.source_type == "user_feedback":
            priority *= 1.5
        if proposal.category == "bugfix":
            priority *= 1.3
        if proposal.urgency == "critical":
            priority *= 1.4

        return min(1.0, priority)

    def _calculate_user_relevance(self, proposal: UnifiedProposal) -> float:
        """
        How relevant is this for the user?
        - Direct requests: 1.0
        - Implicit wishes: 0.7
        - Training errors that affected the user: 0.6
        - General improvements: 0.3
        """
        if proposal.source_type == "user_feedback":
            return 1.0
        if "user" in proposal.evidence:
            return 0.7
        if proposal.source_type == "training":
            return 0.6
        return 0.3
```

---

## Emergent Interconnection

### Cross-Source Correlation
```python
class EmergentAnalyzer:
    """
    Finds connections between different intelligence sources.
    Emergent behavior through correlation.
    """

    def find_correlations(self, proposals: List[UnifiedProposal]) -> List[Insight]:
        """
        Example correlations:

        1. GitHub Feature + User Request = HIGH PRIORITY
           "User asked for 'better logging' AND
            GitHub has 'structured-logger' with 95% confidence"
           -> Correlation! Priority boosted.

        2. Training Error + Self-Analysis = BUGFIX NEEDED
           "Training failed 5x at JSON parsing AND
            self-analysis found outdated json library"
           -> Correlation! Urgency = critical

        3. Performance Issue + External Tool = SOLUTION FOUND
           "Slow startup detected AND
            external tool 'lazy-loader' available"
           -> Correlation! Automatic proposal generated
        """

        correlations = []

        # Group proposals by related topic
        topics = self._extract_topics(proposals)

        for topic, related_proposals in topics.items():
            if len(related_proposals) >= 2:
                # Multiple sources agree on same topic
                sources = set(p.source_type for p in related_proposals)

                if len(sources) >= 2:
                    # Different sources = stronger signal
                    insight = self._create_correlation_insight(
                        topic, related_proposals
                    )
                    correlations.append(insight)

        return correlations

    def _create_correlation_insight(self, topic: str, proposals: List) -> Insight:
        """
        Creates a reinforced proposal from correlated sources.
        """
        # Combine confidence scores
        combined_confidence = 1 - math.prod(1 - p.confidence_score for p in proposals)

        # Create super-proposal
        return Insight(
            type="correlation",
            topic=topic,
            sources=[p.source_type for p in proposals],
            confidence=combined_confidence,
            message=f"Multiple sources ({len(proposals)}) suggest improving '{topic}'",
            recommended_action="HIGH PRIORITY: User + System agree on this"
        )
```

---

## Anticipatory Behavior

### Prediction Engine
```python
class AnticipatoryEngine:
    """
    Frank anticipates what the user will need.
    Proactive instead of reactive.
    """

    def predict_needs(self, context: UserContext) -> List[Prediction]:
        """
        Based on:
        - User's current projects
        - Historical patterns
        - Seasonal trends
        - Workflow analysis
        """

        predictions = []

        # Pattern: User is working on a web project
        if self._detect_web_project(context):
            predictions.append(Prediction(
                what="API Testing Tools",
                why="User is working on a web project, will likely test APIs",
                when="Soon",
                confidence=0.75
            ))

        # Pattern: User recently asked about X
        recent_topics = self._get_recent_topics(context)
        for topic in recent_topics:
            related = self._find_related_tools(topic)
            if related:
                predictions.append(Prediction(
                    what=related.name,
                    why=f"User was interested in '{topic}', this is related",
                    when="When available",
                    confidence=0.6
                ))

        # Pattern: Time-based
        if self._is_end_of_sprint(context):
            predictions.append(Prediction(
                what="Code Review Tools",
                why="Sprint end is approaching, code reviews become more important",
                when="This week",
                confidence=0.7
            ))

        return predictions

    def act_on_predictions(self, predictions: List[Prediction]):
        """
        Acts proactively based on predictions.

        - Begins sandbox tests for predicted tools
        - Prepares proposals
        - Gathers more data for confirmation
        """
        for pred in predictions:
            if pred.confidence >= 0.7:
                # High confidence: Start preparing
                self._prepare_proactively(pred)
            elif pred.confidence >= 0.5:
                # Medium confidence: Gather more evidence
                self._gather_evidence(pred)
```

---

## Popup Integration

### Categorized View
```
┌────────────────────────────────────────────────────────────────────────┐
│    ╔══════════════════════════════════════════════════════════════╗    │
│    ║  ░▒▓ F.I.H. INTELLIGENCE REPORT ▓▒░                         ║    │
│    ║  ─────────────────────────────────                           ║    │
│    ║  12 IMPROVEMENTS AVAILABLE                                   ║    │
│    ╠══════════════════════════════════════════════════════════════╣    │
│    ║                                                              ║    │
│    ║  📁 FILTER: [All ▼]  SORT: [Priority ▼]  🔍               ║    │
│    ║                                                              ║    │
│    ║  ┌─────────────────────────────────────────────────────────┐║    │
│    ║  │ 🎯 HIGH PRIORITY (User + System agree)                  │║    │
│    ║  │                                                         │║    │
│    ║  │ ☐ Structured Logger       [GitHub + User Request]       │║    │
│    ║  │   "You asked for better logging AND we found            │║    │
│    ║  │    a perfectly matching tool on GitHub"                  │║    │
│    ║  │   Priority: ████████████ 98%                            │║    │
│    ║  └─────────────────────────────────────────────────────────┘║    │
│    ║                                                              ║    │
│    ║  ┌─────────────────────────────────────────────────────────┐║    │
│    ║  │ 🔧 FROM TRAINING                                        │║    │
│    ║  │                                                         │║    │
│    ║  │ ☐ Robust JSON Parser      [Training: 5 failures]        │║    │
│    ║  │   "Training repeatedly showed JSON parsing problems"    │║    │
│    ║  │   Priority: ████████░░░░ 75%                            │║    │
│    ║  └─────────────────────────────────────────────────────────┘║    │
│    ║                                                              ║    │
│    ║  ┌─────────────────────────────────────────────────────────┐║    │
│    ║  │ 🌐 FROM GITHUB                                          │║    │
│    ║  │                                                         │║    │
│    ║  │ ☐ API Rate Limiter        [94%]                         │║    │
│    ║  │ ☐ Async Task Queue        [91%]                         │║    │
│    ║  │ ☐ Semantic Code Search    [89%]                         │║    │
│    ║  └─────────────────────────────────────────────────────────┘║    │
│    ║                                                              ║    │
│    ║  ┌─────────────────────────────────────────────────────────┐║    │
│    ║  │ ⚡ PERFORMANCE                                          │║    │
│    ║  │                                                         │║    │
│    ║  │ ☐ Startup Optimizer       [Detected: 3.2s → 1.1s]       │║    │
│    ║  │   "Startup could be accelerated by 66%"                 │║    │
│    ║  └─────────────────────────────────────────────────────────┘║    │
│    ║                                                              ║    │
│    ╠══════════════════════════════════════════════════════════════╣    │
│    ║  ... (action buttons as before)                              ║    │
│    ╚══════════════════════════════════════════════════════════════╝    │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Implementation Roadmap

```
Phase 1: Foundation (Now complete)
─────────────────────────────────
✓ F.A.S. GitHub Discovery
✓ Popup System
✓ Queue Manager
✓ Activity Detector

Phase 2: Unified Hub (Next step)
─────────────────────────────────
□ UnifiedProposal Schema
□ Multi-Source Database
□ Proposal Ranker
□ Categorized Popup View

Phase 3: Training Integration
─────────────────────────────────
□ Training Log Analyzer
□ Error Pattern Detector
□ Learning Curve Insights
□ Auto-generated Proposals

Phase 4: User Feedback
─────────────────────────────────
□ Request Parser
□ Sentiment Analysis
□ Implicit Want Detection
□ Conversation Mining

Phase 5: Self-Analysis
─────────────────────────────────
□ Code Review Bot
□ Performance Monitor
□ Dependency Checker
□ Security Scanner

Phase 6: Anticipation
─────────────────────────────────
□ Pattern Learning
□ Prediction Engine
□ Proactive Preparation
□ Emergent Correlation
```

---

## Summary

**F.I.H. (Frank's Intelligence Hub)** is the evolution of F.A.S.:

1. **Not just GitHub** - All sources of improvement
2. **Emergent** - Correlations between sources amplify signals
3. **Interconnected** - Training + User + GitHub + Self = Holistic
4. **Anticipatory** - Frank foresees needs in advance
5. **User-Centric** - User remains human-in-the-loop for final decisions

The popup becomes the **dashboard of continuous improvement** - a window into Frank's growth, controlled by the user.
