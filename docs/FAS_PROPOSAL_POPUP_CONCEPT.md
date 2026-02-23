# F.A.S. Proposal Popup System - Concept v1.0

## Problem Analysis

### Understanding User Behavior
- Users do **not** proactively engage in collaborative processes
- Data overload = Ignoring = Feature never gets used
- Too frequent interrupts = Annoying = Popup gets clicked away without reading
- Too infrequent interrupts = Features become outdated = Irrelevant

### The Solution: "Intelligent Minimal Interruption"
Frank collects autonomously, analyzes autonomously, curates autonomously - and presents **only when it's worth it** in an **unmissable but not annoying** format.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    F.A.S. BACKEND (already built)                │
│  Scout → Triage → Extract → Sandbox Test → Confidence Score     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                    [Proposal Queue Manager]
                              ↓
              ┌───────────────┴───────────────┐
              │      TRIGGER CONDITIONS       │
              │  • Min 7 Features @ >85%      │
              │  • Max 2x per day             │
              │  • User Activity Detection    │
              │  • Cooldown: 8h after popup   │
              └───────────────┬───────────────┘
                              ↓
              ┌───────────────┴───────────────┐
              │     ACTIVITY DETECTOR         │
              │  • Mouse movement active?     │
              │  • No fullscreen game?        │
              │  • Desktop visible?           │
              │  • No video playback?         │
              │  • CPU < 50%?                 │
              │  • Last interaction < 5min?   │
              └───────────────┬───────────────┘
                              ↓
                    [Popup Launcher]
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                  CYBERPUNK PROPOSAL POPUP                       │
│                     (GTK4 + CSS Magic)                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Trigger Logic in Detail

### Proposal Queue Manager

```python
class ProposalQueueManager:
    """
    Decides WHEN the popup appears.
    Collects features until threshold is reached.
    """

    # Configuration
    MIN_FEATURES_FOR_POPUP = 7          # At least 7 features
    MIN_CONFIDENCE_SCORE = 0.85         # Each feature >85%
    MAX_POPUPS_PER_DAY = 2              # Max 2x per day
    COOLDOWN_HOURS = 8                  # 8h between popups
    FEATURE_EXPIRY_DAYS = 14            # Features older than 14 days = auto-dismiss

    def should_trigger_popup(self) -> Tuple[bool, str]:
        """
        Returns (should_trigger, reason)
        """
        # 1. Enough high-quality features?
        ready_features = self.get_high_confidence_features()
        if len(ready_features) < MIN_FEATURES_FOR_POPUP:
            return False, f"Only {len(ready_features)}/{MIN_FEATURES_FOR_POPUP} features ready"

        # 2. Daily limit not reached?
        popups_today = self.get_popups_today()
        if popups_today >= MAX_POPUPS_PER_DAY:
            return False, "Daily popup limit reached"

        # 3. Cooldown respected?
        last_popup = self.get_last_popup_time()
        if last_popup and (now - last_popup).hours < COOLDOWN_HOURS:
            return False, f"Cooldown active ({COOLDOWN_HOURS}h)"

        # 4. User is receptive?
        if not ActivityDetector.is_user_receptive():
            return False, "User not receptive"

        return True, f"{len(ready_features)} features ready for proposal"
```

### Activity Detector (User Receptivity)

```python
class ActivityDetector:
    """
    Detects when the user is "ready" for a popup.
    Goal: Popup appears when user is active but not busy.
    """

    # Ideal moment: User has just finished something, is still at the PC

    @staticmethod
    def is_user_receptive() -> bool:
        checks = [
            ActivityDetector._is_mouse_active_recently(),      # Mouse moved in last 2min
            ActivityDetector._no_fullscreen_app(),             # No fullscreen
            ActivityDetector._no_video_playing(),              # No video/stream
            ActivityDetector._cpu_not_busy(),                  # CPU < 50%
            ActivityDetector._no_presentation_mode(),          # No presentation mode
            ActivityDetector._desktop_visible(),               # Desktop not completely covered
        ]
        return all(checks)

    @staticmethod
    def _is_mouse_active_recently() -> bool:
        """Checks if mouse was moved in the last 2 minutes."""
        # Via /dev/input or xdotool
        pass

    @staticmethod
    def _no_fullscreen_app() -> bool:
        """No window in fullscreen mode."""
        # Via wmctrl or X11
        result = subprocess.run(['xdotool', 'getactivewindow'], capture_output=True)
        window_id = result.stdout.strip()
        # Check _NET_WM_STATE_FULLSCREEN
        pass

    @staticmethod
    def _no_video_playing() -> bool:
        """No video is playing (YouTube, VLC, etc.)."""
        # Check for known video player processes with active playback
        # Or: check pulseaudio sink-inputs
        pass

    @staticmethod
    def get_best_popup_moment() -> Optional[datetime]:
        """
        Analyzes user patterns and suggests optimal moment.
        Learns from past interactions.
        """
        # Historical data: When did the user in the past
        # react fastest/most positively to popups?
        pass
```

---

## Popup UI Design

### Cyberpunk Aesthetic Principles

```
┌────────────────────────────────────────────────────────────────────────┐
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ │
│                                                                        │
│    ╔══════════════════════════════════════════════════════════════╗    │
│    ║  ░▒▓ F.A.S. INTELLIGENCE REPORT ▓▒░                          ║    │
│    ║  ─────────────────────────────────                           ║    │
│    ║  7 NEW CAPABILITIES DISCOVERED                               ║    │
│    ╠══════════════════════════════════════════════════════════════╣    │
│    ║                                                              ║    │
│    ║  ☐ GitHub API Rate Limiter          [94%] ──────────█████▌  ║    │
│    ║    └─ Intelligent rate-limiting for API calls                ║    │
│    ║       Prevents 429 errors, optimizes throughput              ║    │
│    ║                                                    [DETAILS] ║    │
│    ║  ────────────────────────────────────────────────────────── ║    │
│    ║  ☐ Async Task Queue Manager         [91%] ──────────█████   ║    │
│    ║    └─ Robust task management with retry logic                ║    │
│    ║       Based on: celery-patterns, optimized for Frank         ║    │
│    ║                                                    [DETAILS] ║    │
│    ║  ────────────────────────────────────────────────────────── ║    │
│    ║  ☑ Semantic Code Search             [89%] ──────────████▌   ║    │
│    ║    └─ Code search via embeddings instead of keywords         ║    │
│    ║       "Find functions that do X" becomes possible            ║    │
│    ║                                                    [DETAILS] ║    │
│    ║  ────────────────────────────────────────────────────────── ║    │
│    ║  ... (scrollable for more)                                   ║    │
│    ║                                                              ║    │
│    ╠══════════════════════════════════════════════════════════════╣    │
│    ║                                                              ║    │
│    ║  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐ ║    │
│    ║  │ ✓ IMPLEMENT  │ │ ✗ NONE      │ │ ⏰ LATER (8h)        │ ║    │
│    ║  │  ALL         │ │  RELEVANT   │ │                      │ ║    │
│    ║  └──────────────┘ └──────────────┘ └──────────────────────┘ ║    │
│    ║                                                              ║    │
│    ║           ┌────────────────────────────────┐                 ║    │
│    ║           │  ▶ INTEGRATE SELECTED (2)      │                 ║    │
│    ║           └────────────────────────────────┘                 ║    │
│    ║                                                              ║    │
│    ╚══════════════════════════════════════════════════════════════╝    │
│                                                                        │
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ │
└────────────────────────────────────────────────────────────────────────┘
```

### CSS Theme (Cyberpunk)

```css
/* Neon Cyan/Magenta Theme */
:root {
    --neon-cyan: #00fff9;
    --neon-magenta: #ff00ff;
    --dark-bg: #0a0a12;
    --panel-bg: rgba(10, 10, 18, 0.95);
    --border-glow: 0 0 10px var(--neon-cyan), 0 0 20px var(--neon-cyan);
    --text-glow: 0 0 5px var(--neon-cyan);
}

.proposal-popup {
    background: var(--panel-bg);
    border: 2px solid var(--neon-cyan);
    box-shadow: var(--border-glow);
    border-radius: 0;  /* Cyberpunk = sharp edges */
    font-family: 'Share Tech Mono', 'Fira Code', monospace;
}

.feature-item {
    border-left: 3px solid var(--neon-magenta);
    transition: all 0.3s ease;
}

.feature-item:hover {
    background: rgba(0, 255, 249, 0.1);
    border-left-color: var(--neon-cyan);
}

.confidence-bar {
    background: linear-gradient(90deg, var(--neon-magenta), var(--neon-cyan));
    height: 4px;
    box-shadow: 0 0 10px var(--neon-cyan);
}

.action-button {
    background: transparent;
    border: 1px solid var(--neon-cyan);
    color: var(--neon-cyan);
    text-transform: uppercase;
    letter-spacing: 2px;
}

.action-button:hover {
    background: var(--neon-cyan);
    color: var(--dark-bg);
    box-shadow: var(--border-glow);
}

.action-button.primary {
    background: var(--neon-magenta);
    border-color: var(--neon-magenta);
    animation: pulse-glow 2s infinite;
}

@keyframes pulse-glow {
    0%, 100% { box-shadow: 0 0 5px var(--neon-magenta); }
    50% { box-shadow: 0 0 20px var(--neon-magenta), 0 0 30px var(--neon-magenta); }
}
```

---

## Button Logic

### The 4 Actions

| Button | Behavior | Database Effect |
|--------|----------|-----------------|
| **✓ IMPLEMENT ALL** | All features -> Integration Queue | `integration_status = 'approved'` for all |
| **✗ NONE RELEVANT** | All features permanently dismissed | `integration_status = 'rejected_permanent'` |
| **⏰ LATER** | Popup closes, reappears in 8h | `postponed_until = now + 8h` |
| **▶ SELECTED** | Only checked ones -> Integration | Only selected -> `approved` |

### Important: "None Relevant" is Permanent

```python
def dismiss_all_permanently(feature_ids: List[int]):
    """
    User has decided: These features are not interesting.
    They will NEVER be suggested again.
    """
    for fid in feature_ids:
        db.execute("""
            UPDATE extracted_features
            SET integration_status = 'rejected_permanent',
                user_response = 'Batch dismissed via popup',
                user_approved_at = ?
            WHERE id = ?
        """, (datetime.now().isoformat(), fid))

    # These features will NEVER appear again
    # Not in the CLI or anywhere else either
```

---

## Integration Flow after Approval

```
User clicks "INTEGRATE SELECTED (3)"
              ↓
┌─────────────────────────────────────────┐
│  Integration Progress Popup             │
│  ═══════════════════════════════════   │
│                                         │
│  [1/3] GitHub API Rate Limiter         │
│        ████████████░░░░░░ 67%          │
│        Validating imports...            │
│                                         │
│  [2/3] Semantic Code Search            │
│        ░░░░░░░░░░░░░░░░░░ Pending      │
│                                         │
│  [3/3] Async Task Queue Manager        │
│        ░░░░░░░░░░░░░░░░░░ Pending      │
│                                         │
└─────────────────────────────────────────┘
              ↓
         (After completion)
              ↓
┌─────────────────────────────────────────┐
│  ✓ Integration Complete                 │
│  ═══════════════════════════════════   │
│                                         │
│  3 new capabilities added to Frank:     │
│                                         │
│  • GitHub API Rate Limiter     ✓       │
│  • Semantic Code Search        ✓       │
│  • Async Task Queue Manager    ✓       │
│                                         │
│  Location: tools/discovered/            │
│                                         │
│  [ Frank will be able to use these  ]   │
│  [ tools in conversations from now  ]   │
│                                         │
│           [  UNDERSTOOD  ]              │
└─────────────────────────────────────────┘
```

---

## Daemon Architecture

### fas_popup_daemon.py

```python
"""
F.A.S. Proposal Popup Daemon
Runs as systemd user service, periodically checks whether popup should be triggered.
"""

class FASPopupDaemon:
    CHECK_INTERVAL = 300  # Check every 5 minutes

    def run(self):
        while True:
            try:
                should_trigger, reason = self.queue_manager.should_trigger_popup()

                if should_trigger:
                    # Wait for optimal moment
                    if ActivityDetector.is_user_receptive():
                        self.launch_popup()
                        self.record_popup_shown()
                    else:
                        # User not ready, check again in 5min
                        LOG.info("Popup ready but user not receptive, waiting...")

                time.sleep(self.CHECK_INTERVAL)

            except Exception as e:
                LOG.error(f"Daemon error: {e}")
                time.sleep(60)

    def launch_popup(self):
        """Starts the GTK popup as subprocess."""
        features = self.get_proposal_features()

        # Pass features as JSON to popup
        subprocess.Popen([
            sys.executable,
            str(POPUP_SCRIPT),
            "--features", json.dumps(features),
        ])
```

---

## File Structure

```
/home/ai-core-node/aicore/opt/aicore/
├── tools/
│   ├── fas_scavenger.py          # Backend (already built)
│   ├── fas_popup_daemon.py       # NEW: Daemon that triggers popup
│   └── discovered/               # Integrated features land here
│
├── ui/
│   ├── fas_proposal_popup.py     # NEW: GTK4 Popup Window
│   ├── fas_proposal_popup.css    # NEW: Cyberpunk Styling
│   └── fas_progress_dialog.py    # NEW: Integration Progress
│
└── services/
    └── fas-popup.service         # NEW: systemd user service
```

---

## Configuration

```python
# /home/ai-core-node/aicore/opt/aicore/config/fas_popup_config.py

FAS_POPUP_CONFIG = {
    # Trigger thresholds
    "min_features_for_popup": 7,
    "min_confidence_score": 0.85,
    "max_popups_per_day": 2,
    "cooldown_hours": 8,
    "feature_expiry_days": 14,

    # Activity Detection
    "mouse_idle_threshold_seconds": 120,
    "cpu_busy_threshold": 50,
    "require_no_fullscreen": True,
    "require_no_video": True,

    # UI
    "popup_width": 800,
    "popup_height": 600,
    "always_on_top": True,
    "center_on_screen": True,
    "theme": "cyberpunk",

    # Timing
    "preferred_hours": [9, 10, 11, 14, 15, 16],  # Preferred times
    "avoid_hours": [0, 1, 2, 3, 4, 5, 6, 22, 23],  # Never at night
}
```

---

## User Flow Summary

```
                    ┌─────────────────────────┐
                    │   F.A.S. runs 24/7      │
                    │   (At night, when idle)  │
                    └───────────┬─────────────┘
                                ↓
                    ┌─────────────────────────┐
                    │ Features are discovered  │
                    │ and sandbox tested       │
                    └───────────┬─────────────┘
                                ↓
                    ┌─────────────────────────┐
                    │ 7+ features with >85%   │
                    │ confidence collected     │
                    └───────────┬─────────────┘
                                ↓
                    ┌─────────────────────────┐
                    │ User is currently active │
                    │ but not busy            │
                    └───────────┬─────────────┘
                                ↓
              ╔═══════════════════════════════════╗
              ║                                   ║
              ║   POPUP APPEARS AUTOMATICALLY     ║
              ║   (unmissable, centered)          ║
              ║                                   ║
              ╚═══════════════════════════════════╝
                                ↓
                    ┌─────────────────────────┐
                    │ User selects with clicks:│
                    │ • Individual features    │
                    │ • All                   │
                    │ • None                  │
                    │ • Later                 │
                    └───────────┬─────────────┘
                                ↓
                    ┌─────────────────────────┐
                    │ Frank integrates        │
                    │ selected features       │
                    └───────────┬─────────────┘
                                ↓
                    ┌─────────────────────────┐
                    │ New capabilities are    │
                    │ immediately available   │
                    └─────────────────────────┘
```

---

## Critical Design Decisions

### 1. Why Minimum 7 Features?
- Fewer = too frequent popups = annoying
- 7 gives the user real choice
- Batch processing is more efficient
- User doesn't feel bothered with individual decisions

### 2. Why 85% Confidence Minimum?
- Don't suggest half-baked features
- Build user trust
- "When Frank suggests something, it's good"
- Rather fewer, but higher quality

### 3. Why "Later" Instead of "Cancel"?
- Cancel = Feature disappears = User misses something
- Later = Respects user's time, feature comes back
- 8h cooldown = Enough time, not too long

### 4. Why Activity Detection?
- Popup during gaming/video = Annoyed = Click away without reading
- Popup after just finished activity = User is receptive
- Learning from patterns = Ever better timing

### 5. Why Permanent Dismiss Option?
- User knows best what they need
- Irrelevant features should never come back
- Saves future interrupts
- Trust: "Frank understands me"

---

## Next Steps for Implementation

1. **fas_popup_daemon.py** - Daemon that implements trigger logic
2. **fas_proposal_popup.py** - GTK4 Popup with Cyberpunk CSS
3. **Activity Detection** - Mouse/fullscreen/video detection
4. **Integration into F.A.S.** - New status fields, queue management
5. **systemd Service** - User service for daemon
6. **Testing** - Test with mock features

---

## Open Questions for User

1. Should the popup play a sound when it appears?
2. Should there be a keyboard shortcut to manually open the popup?
3. Should rejected features remain viewable in an "Archive"?
4. Should Frank explain WHY he suggests a feature (use case)?
