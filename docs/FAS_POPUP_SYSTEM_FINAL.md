# F.A.S. Proposal Popup System - Final Concept v2.0

## Overview

A fully autonomous feature proposal system that:
- Intelligently chooses the right moment
- Is unmissable but not annoying
- Is operable with just a few clicks
- Explains Frank's use cases
- Provides sound feedback
- Is manually accessible via hotkey
- Has an archive for rejected features

---

## 1. SOUND SYSTEM

### Concept
Subtle but unmistakable sound when popup appears - not annoying, but attention-grabbing.

### Sound Design

```
┌─────────────────────────────────────────────────────────────────┐
│                      SOUND EVENTS                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  POPUP APPEARS:                                                 │
│  ───────────────                                                │
│  "Cyberpunk Chime" - Short synthetic tone (0.8s)               │
│  - Frequency: Ascending 440Hz → 880Hz                          │
│  - Reverb: Light reverb for "digital" character                │
│  - Volume: 60% system volume (not startling)                   │
│                                                                 │
│  FEATURE SELECTED (Checkbox):                                   │
│  ─────────────────────────────                                  │
│  Short "Click" sound (0.1s)                                    │
│  - Confirmatory feedback                                        │
│                                                                 │
│  INTEGRATION STARTS:                                            │
│  ───────────────────                                            │
│  "Power Up" sound (0.5s)                                       │
│  - Ascending synthesizer                                        │
│                                                                 │
│  INTEGRATION COMPLETE:                                          │
│  ────────────────────                                           │
│  "Success Chime" (1.0s)                                        │
│  - Harmonious triad                                             │
│  - Signals: "Frank has new capabilities"                       │
│                                                                 │
│  LATER/DISMISS:                                                 │
│  ──────────────                                                 │
│  Quiet "Whoosh" (0.3s)                                         │
│  - Popup disappears                                             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Sound File Structure

```
/home/ai-core-node/aicore/opt/aicore/ui/sounds/
├── popup_appear.ogg      # Cyberpunk Chime
├── checkbox_click.ogg    # Selection Click
├── integration_start.ogg # Power Up
├── integration_done.ogg  # Success Chime
└── popup_dismiss.ogg     # Whoosh
```

### Sound Manager

```python
class SoundManager:
    """Manages all UI sounds with volume control."""

    SOUNDS_DIR = Path("ui/sounds/")
    VOLUME = 0.6  # 60% - not too loud

    # Sound can be disabled by the user
    enabled: bool = True

    # Cooldown to prevent sound spam
    last_played: Dict[str, float] = {}
    MIN_INTERVAL = 0.2  # Seconds

    def play(self, sound_name: str):
        """Plays sound if enabled and cooldown is over."""
        if not self.enabled:
            return

        now = time.time()
        if sound_name in self.last_played:
            if now - self.last_played[sound_name] < self.MIN_INTERVAL:
                return

        self.last_played[sound_name] = now
        sound_file = self.SOUNDS_DIR / f"{sound_name}.ogg"

        # Non-blocking playback via paplay (PulseAudio)
        subprocess.Popen(
            ['paplay', '--volume', str(int(65536 * self.VOLUME)), str(sound_file)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
```

### Sound Toggle in Popup

```
┌────────────────────────────────────────┐
│  ░▒▓ F.A.S. INTELLIGENCE REPORT ▓▒░   │
│                                        │
│                           🔊 Sound [ON]│  ← Clickable
└────────────────────────────────────────┘
```

---

## 2. KEYBOARD SHORTCUT SYSTEM

### Concept
User can manually open popup at any time to check status - even if trigger threshold is not reached.

### Global Hotkey

```
┌─────────────────────────────────────────────────────────────────┐
│                     KEYBOARD SHORTCUTS                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  GLOBAL (works everywhere):                                     │
│  ─────────────────────────────                                  │
│                                                                 │
│  Super + F  →  Open/close F.A.S. Popup (Toggle)                │
│              (Super = Windows key)                              │
│                                                                 │
│  ───────────────────────────────────────────────────────────── │
│                                                                 │
│  IN POPUP (when open):                                          │
│  ─────────────────────                                          │
│                                                                 │
│  Space      →  Select/deselect current feature                  │
│  ↑/↓        →  Navigate through features                        │
│  Enter      →  "Integrate Selected"                             │
│  A          →  Select all                                       │
│  N          →  Deselect all                                     │
│  Escape     →  Later (close)                                    │
│  D          →  Details for highlighted feature                  │
│  R          →  Reject all permanently                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Hotkey Daemon

```python
class GlobalHotkeyDaemon:
    """
    Registers global hotkeys via xdotool/xbindkeys.
    Runs as part of the fas_popup_daemon.
    """

    HOTKEY = "super+f"  # Windows + F for F.A.S.

    def __init__(self):
        self.popup_visible = False

    def setup_hotkey(self):
        """Registers the global hotkey."""
        # Method 1: Via keybinder (Python)
        # Method 2: Via xbindkeys config
        # Method 3: Via dbus to GNOME/KDE

        # We use a socket listener
        # The hotkey is sent via xbindkeys -> socket signal

    def on_hotkey_pressed(self):
        """Callback when hotkey is pressed."""
        if self.popup_visible:
            self.hide_popup()
        else:
            self.show_popup(force=True)  # force = even if < 7 features

    def show_popup(self, force: bool = False):
        """
        Opens popup.
        force=True: Opens even if fewer than 7 features
                    (then shows what's there + "X more features until next batch")
        """
        features = self.get_available_features()

        if not features and not force:
            return

        # Start popup
        subprocess.Popen([
            sys.executable,
            str(POPUP_SCRIPT),
            "--features", json.dumps(features),
            "--manual" if force else "",
        ])
        self.popup_visible = True
```

### Manually Opened Popup (< 7 Features)

```
┌────────────────────────────────────────────────────────────────────────┐
│                                                                        │
│    ╔══════════════════════════════════════════════════════════════╗    │
│    ║  ░▒▓ F.A.S. STATUS ▓▒░                              🔊 [ON] ║    │
│    ║  ─────────────────────────────────                           ║    │
│    ║  3 FEATURES IN QUEUE (4 more for auto-popup)               ║    │
│    ╠══════════════════════════════════════════════════════════════╣    │
│    ║                                                              ║    │
│    ║  ☐ GitHub API Rate Limiter          [94%] ──────────█████▌  ║    │
│    ║    └─ Intelligent rate-limiting for API calls                ║    │
│    ║                                                              ║    │
│    ║  ☐ Async Task Queue                 [91%] ──────────█████   ║    │
│    ║    └─ Robust task management with retry                      ║    │
│    ║                                                              ║    │
│    ║  ☐ Semantic Code Search             [89%] ──────────████▌   ║    │
│    ║    └─ Code search via embeddings                             ║    │
│    ║                                                              ║    │
│    ║  ────────────────────────────────────────────────────────── ║    │
│    ║  💡 Auto-popup appears at 7+ features                       ║    │
│    ║     Currently: ███░░░░ 3/7                                  ║    │
│    ║                                                              ║    │
│    ╠══════════════════════════════════════════════════════════════╣    │
│    ║                                                              ║    │
│    ║  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐ ║    │
│    ║  │ 📁 ARCHIVE  │ │ ⚙ SETTINGS  │ │       CLOSE          │ ║    │
│    ║  └──────────────┘ └──────────────┘ └──────────────────────┘ ║    │
│    ║                                                              ║    │
│    ║           ┌────────────────────────────────┐                 ║    │
│    ║           │  ▶ INTEGRATE SELECTED (0)      │                 ║    │
│    ║           └────────────────────────────────┘                 ║    │
│    ║                                                              ║    │
│    ╚══════════════════════════════════════════════════════════════╝    │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. ARCHIVE SYSTEM

### Concept
Rejected features are not "gone" - they are viewable in the archive. User can reactivate them later if they change their mind.

### Archive View

```
┌────────────────────────────────────────────────────────────────────────┐
│                                                                        │
│    ╔══════════════════════════════════════════════════════════════╗    │
│    ║  ░▒▓ F.A.S. ARCHIVE ▓▒░                             [← BACK] ║    │
│    ║  ─────────────────────────────────                           ║    │
│    ║  23 rejected features                                       ║    │
│    ╠══════════════════════════════════════════════════════════════╣    │
│    ║                                                              ║    │
│    ║  Filter: [All ▼]  [By Date ▼]  🔍 [Search...]              ║    │
│    ║                                                              ║    │
│    ║  ────────────────────────────────────────────────────────── ║    │
│    ║                                                              ║    │
│    ║  ✗ Docker Compose Generator         [87%]     2026-01-28    ║    │
│    ║    └─ "Don't need it"                         [REACTIVATE]  ║    │
│    ║                                                              ║    │
│    ║  ✗ PDF Text Extractor               [92%]     2026-01-25    ║    │
│    ║    └─ Batch dismissed                         [REACTIVATE]  ║    │
│    ║                                                              ║    │
│    ║  ✗ Slack API Wrapper                [85%]     2026-01-20    ║    │
│    ║    └─ "Don't use Slack"                       [REACTIVATE]  ║    │
│    ║                                                              ║    │
│    ║  ✗ Redis Cache Helper               [91%]     2026-01-15    ║    │
│    ║    └─ Batch dismissed                         [REACTIVATE]  ║    │
│    ║                                                              ║    │
│    ║  ... (scrollable)                                            ║    │
│    ║                                                              ║    │
│    ╠══════════════════════════════════════════════════════════════╣    │
│    ║                                                              ║    │
│    ║  Statistics:                                                 ║    │
│    ║  • 23 rejected │ 47 integrated │ 12 in queue                ║    │
│    ║  • Oldest: 2025-11-03 │ Newest: 2026-01-28                 ║    │
│    ║                                                              ║    │
│    ║  ┌────────────────────────────────────────────────────────┐ ║    │
│    ║  │  🗑️ CLEAR ARCHIVE (permanently delete)                  │ ║    │
│    ║  └────────────────────────────────────────────────────────┘ ║    │
│    ║                                                              ║    │
│    ╚══════════════════════════════════════════════════════════════╝    │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

### Reactivation

When user clicks [REACTIVATE]:

```
┌─────────────────────────────────────────┐
│  Reactivate feature?                    │
│  ═══════════════════════════════════   │
│                                         │
│  "Docker Compose Generator"             │
│                                         │
│  This feature will be added back to     │
│  the queue and suggested in the next    │
│  auto-popup.                            │
│                                         │
│  ┌─────────────┐    ┌─────────────┐    │
│  │   CANCEL    │    │ REACTIVATE  │    │
│  └─────────────┘    └─────────────┘    │
└─────────────────────────────────────────┘
```

### Database Status

```python
# integration_status values:
FEATURE_STATUS = {
    "pending":              # New, not yet tested
    "testing":              # In sandbox test
    "ready":                # Ready for proposal
    "notified":             # User has been notified
    "approved":             # User has approved
    "integrated":           # Successfully integrated
    "rejected":             # Rejected (can be reactivated)
    "rejected_permanent":   # Permanently rejected (in archive)
    "archived_deleted":     # Deleted from archive
}
```

---

## 4. USE-CASE EXPLANATIONS

### Concept
Frank explains not only WHAT a feature does, but WHY it could be useful for the user - based on observed patterns.

### Use-Case Generator

```python
class UseCaseGenerator:
    """
    Generates personalized use-case explanations
    based on user's previous usage.
    """

    def generate_use_case(self, feature: Dict) -> str:
        """
        Analyzes feature and generates use case.
        """
        feature_type = feature['feature_type']
        name = feature['name']
        code = feature['code_snippet']

        # Base use case by type
        base_cases = {
            "tool": self._tool_use_case,
            "api_wrapper": self._api_use_case,
            "utility": self._utility_use_case,
            "pattern": self._pattern_use_case,
        }

        base = base_cases.get(feature_type, self._generic_use_case)(feature)

        # Personalization based on user history
        personalized = self._personalize(feature, base)

        return personalized

    def _tool_use_case(self, feature: Dict) -> str:
        """Use case for tools."""
        return f"""
WHY THIS FEATURE?
─────────────────────
This tool directly extends Frank's capabilities.

CONCRETE USE CASE:
When you ask Frank "{self._generate_example_prompt(feature)}",
Frank can use this tool to complete the task more efficiently.

BEFORE:  Frank would have to proceed manually in a cumbersome way
AFTER:   Direct access to optimized functionality
"""

    def _api_use_case(self, feature: Dict) -> str:
        """Use case for API wrappers."""
        api_name = self._extract_api_name(feature)
        return f"""
WHY THIS FEATURE?
─────────────────────
Integration with {api_name} service.

CONCRETE USE CASE:
Frank can communicate directly with {api_name}:
• Retrieve and process data
• Execute automated actions
• Integrate real-time information

EXAMPLE:
"Frank, {self._generate_api_example(feature)}"
"""

    def _personalize(self, feature: Dict, base: str) -> str:
        """
        Personalizes use case based on user behavior.
        """
        # Analyze previous usage
        user_patterns = self._get_user_patterns()

        # If user often does X and feature improves X -> highlight
        relevance = self._calculate_personal_relevance(feature, user_patterns)

        if relevance > 0.8:
            personal_note = f"""
💡 PERSONAL RECOMMENDATION:
Based on your frequent use of {relevance['related_feature']}
this feature could be particularly useful.
"""
            return base + personal_note

        return base
```

### UI with Use Case

```
┌────────────────────────────────────────────────────────────────────────┐
│    ║                                                              ║    │
│    ║  ☐ GitHub API Rate Limiter          [94%] ──────────█████▌  ║    │
│    ║    └─ Intelligent rate-limiting for API calls                ║    │
│    ║                                                              ║    │
│    ║    ┌─────────────────────────────────────────────────────┐  ║    │
│    ║    │ 💡 WHY THIS FEATURE?                                │  ║    │
│    ║    │                                                     │  ║    │
│    ║    │ You often use GitHub integrations. This tool        │  ║    │
│    ║    │ automatically prevents 429 errors and optimizes     │  ║    │
│    ║    │ API throughput.                                     │  ║    │
│    ║    │                                                     │  ║    │
│    ║    │ BEFORE:  Manual delays, frequent rate-limit errors  │  ║    │
│    ║    │ AFTER:   Automatic queueing, no errors              │  ║    │
│    ║    │                                                     │  ║    │
│    ║    │ 📊 Personal Relevance: ████████░░ 85%              │  ║    │
│    ║    └─────────────────────────────────────────────────────┘  ║    │
│    ║                                                    [DETAILS] ║    │
│    ║  ────────────────────────────────────────────────────────── ║    │
```

### Expanded Details View

When user clicks [DETAILS]:

```
┌────────────────────────────────────────────────────────────────────────┐
│                                                                        │
│    ╔══════════════════════════════════════════════════════════════╗    │
│    ║  ░▒▓ FEATURE DETAILS ▓▒░                            [← BACK] ║    │
│    ║  ─────────────────────────────────                           ║    │
│    ║  GitHub API Rate Limiter                                     ║    │
│    ╠══════════════════════════════════════════════════════════════╣    │
│    ║                                                              ║    │
│    ║  CONFIDENCE BREAKDOWN:                                       ║    │
│    ║  ├─ Syntax Check:     ████████████ 100%  ✓                  ║    │
│    ║  ├─ Import Check:     ████████████ 100%  ✓                  ║    │
│    ║  ├─ Execution Test:   █████████░░░  75%  ✓ (3/3 passed)     ║    │
│    ║  └─ Overall:          ██████████░░  94%                     ║    │
│    ║                                                              ║    │
│    ║  SOURCE:                                                     ║    │
│    ║  Repository: octocat/github-rate-limiter                    ║    │
│    ║  Stars: 1,247 │ Forks: 89 │ Updated: 2026-01-15             ║    │
│    ║  File: src/rate_limiter.py                                  ║    │
│    ║                                                              ║    │
│    ║  DEPENDENCIES:                                               ║    │
│    ║  • requests (already installed)                              ║    │
│    ║  • asyncio (stdlib)                                         ║    │
│    ║                                                              ║    │
│    ║  USE CASE:                                                   ║    │
│    ║  ┌─────────────────────────────────────────────────────────┐║    │
│    ║  │ You frequently use GitHub API calls in your projects.  │║    │
│    ║  │ This tool:                                              │║    │
│    ║  │                                                         │║    │
│    ║  │ • Automatic queueing at rate limits                     │║    │
│    ║  │ • Exponential backoff on 429 errors                     │║    │
│    ║  │ • Request batching for efficiency                       │║    │
│    ║  │                                                         │║    │
│    ║  │ Example usage:                                           │║    │
│    ║  │ "Frank, fetch all issues from the last 30 days"         │║    │
│    ║  │ → Frank uses rate limiter automatically                 │║    │
│    ║  └─────────────────────────────────────────────────────────┘║    │
│    ║                                                              ║    │
│    ║  CODE PREVIEW:                                               ║    │
│    ║  ┌─────────────────────────────────────────────────────────┐║    │
│    ║  │ class GitHubRateLimiter:                                │║    │
│    ║  │     def __init__(self, tokens_per_hour=5000):           │║    │
│    ║  │         self.tokens = tokens_per_hour                   │║    │
│    ║  │         self.queue = asyncio.Queue()                    │║    │
│    ║  │         ...                                             │║    │
│    ║  └─────────────────────────────────────────────────────────┘║    │
│    ║                                                              ║    │
│    ╠══════════════════════════════════════════════════════════════╣    │
│    ║                                                              ║    │
│    ║  ┌──────────────────┐              ┌──────────────────────┐ ║    │
│    ║  │  ✗ DON'T USE    │              │  ✓ ADD TO SELECTION  │ ║    │
│    ║  └──────────────────┘              └──────────────────────┘ ║    │
│    ║                                                              ║    │
│    ╚══════════════════════════════════════════════════════════════╝    │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 5. COMPLETE SYSTEM ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         F.A.S. POPUP SYSTEM                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐   │
│  │ fas_scavenger   │────▶│ Proposal Queue  │────▶│ Activity        │   │
│  │ (Backend)       │     │ Manager         │     │ Detector        │   │
│  └─────────────────┘     └─────────────────┘     └────────┬────────┘   │
│          │                       │                        │            │
│          │                       │                        ▼            │
│          │               ┌───────▼───────┐        ┌──────────────┐    │
│          │               │ Trigger       │        │ User is      │    │
│          │               │ Conditions    │◀───────│ receptive    │    │
│          │               │ (7+, 85%+)    │        └──────────────┘    │
│          │               └───────┬───────┘                            │
│          │                       │                                     │
│          │                       ▼                                     │
│          │         ┌─────────────────────────┐                        │
│          │         │    POPUP LAUNCHER       │◀──── [Super+F Hotkey]  │
│          │         └───────────┬─────────────┘                        │
│          │                     │                                       │
│          │                     ▼                                       │
│          │    ╔════════════════════════════════════╗                  │
│          │    ║     GTK4 PROPOSAL POPUP           ║                  │
│          │    ║     ─────────────────────         ║                  │
│          │    ║     • Feature List               ║                  │
│          │    ║     • Use-Case Explanations      ║◀── Use-Case Gen  │
│          │    ║     • Confidence Bars             ║                  │
│          │    ║     • Checkboxes                  ║                  │
│          │    ║     • Action Buttons              ║                  │
│          │    ║     • Sound Feedback              ║◀── Sound Manager │
│          │    ║     • Keyboard Navigation         ║                  │
│          │    ╚════════════════════════════════════╝                  │
│                              │                                         │
│           ┌──────────────────┼──────────────────┐                     │
│           ▼                  ▼                  ▼                     │
│    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐             │
│    │ IMPLEMENT   │    │ INTEGRATE   │    │ NONE/       │             │
│    │ ALL         │    │ SELECTED    │    │ LATER       │             │
│    └──────┬──────┘    └──────┬──────┘    └──────┬──────┘             │
│           │                  │                  │                     │
│           └─────────┬────────┘                  │                     │
│                     ▼                           ▼                     │
│           ┌─────────────────┐          ┌─────────────────┐           │
│           │ Integration     │          │ Archive /       │           │
│           │ Progress Dialog │          │ Postpone        │           │
│           └────────┬────────┘          └─────────────────┘           │
│                    │                                                  │
│                    ▼                                                  │
│           ┌─────────────────┐                                        │
│           │ tools/discovered│                                        │
│           │ (new features)  │                                        │
│           └─────────────────┘                                        │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

---

## 6. FILE STRUCTURE

```
/home/ai-core-node/aicore/opt/aicore/
│
├── tools/
│   ├── fas_scavenger.py              # Backend (exists)
│   └── discovered/                    # Integrated features
│
├── ui/
│   ├── fas_popup/
│   │   ├── __init__.py
│   │   ├── main_window.py            # Main popup GTK4
│   │   ├── feature_list.py           # Feature list widget
│   │   ├── details_view.py           # Details view
│   │   ├── archive_view.py           # Archive view
│   │   ├── progress_dialog.py        # Integration progress
│   │   ├── settings_dialog.py        # Settings (sound, etc.)
│   │   ├── use_case_generator.py     # Use-case texts
│   │   └── styles/
│   │       ├── cyberpunk.css         # Main theme
│   │       └── animations.css        # Glow effects etc.
│   │
│   └── sounds/
│       ├── popup_appear.ogg
│       ├── checkbox_click.ogg
│       ├── integration_start.ogg
│       ├── integration_done.ogg
│       └── popup_dismiss.ogg
│
├── services/
│   ├── fas_popup_daemon.py           # Daemon (trigger + hotkey)
│   └── fas-popup.service             # systemd user service
│
├── config/
│   └── fas_popup_config.py           # All settings
│
└── database/
    └── fas_scavenger.db              # SQLite (exists, extend)
```

---

## 7. CONFIGURATION

```python
# /home/ai-core-node/aicore/opt/aicore/config/fas_popup_config.py

FAS_POPUP_CONFIG = {
    # ═══════════════════════════════════════════════════════
    # TRIGGER SETTINGS
    # ═══════════════════════════════════════════════════════
    "min_features_for_auto_popup": 7,      # Minimum for auto-trigger
    "min_confidence_score": 0.85,          # 85% minimum
    "max_popups_per_day": 2,               # Max 2x per day
    "cooldown_hours": 8,                   # 8h between popups
    "feature_expiry_days": 14,             # After 14 days -> archive

    # ═══════════════════════════════════════════════════════
    # ACTIVITY DETECTION
    # ═══════════════════════════════════════════════════════
    "mouse_idle_threshold_sec": 120,       # 2min without mouse = idle
    "cpu_busy_threshold": 50,              # >50% = busy
    "require_no_fullscreen": True,
    "require_no_video": True,
    "require_no_presentation": True,
    "preferred_hours": [9, 10, 11, 14, 15, 16, 17],
    "avoid_hours": [0, 1, 2, 3, 4, 5, 6, 22, 23],

    # ═══════════════════════════════════════════════════════
    # UI SETTINGS
    # ═══════════════════════════════════════════════════════
    "popup_width": 900,
    "popup_height": 700,
    "always_on_top": True,
    "center_on_screen": True,
    "theme": "cyberpunk",
    "show_confidence_bars": True,
    "show_use_cases": True,
    "show_personal_relevance": True,

    # ═══════════════════════════════════════════════════════
    # SOUND SETTINGS
    # ═══════════════════════════════════════════════════════
    "sound_enabled": True,
    "sound_volume": 0.6,                   # 60%
    "sound_on_popup": True,
    "sound_on_selection": True,
    "sound_on_integration": True,

    # ═══════════════════════════════════════════════════════
    # KEYBOARD SHORTCUTS
    # ═══════════════════════════════════════════════════════
    "global_hotkey": "super+f",            # Windows + F
    "hotkey_enabled": True,

    # ═══════════════════════════════════════════════════════
    # ARCHIVE SETTINGS
    # ═══════════════════════════════════════════════════════
    "archive_max_items": 100,              # Max 100 in archive
    "archive_auto_cleanup_days": 90,       # Delete after 90 days

    # ═══════════════════════════════════════════════════════
    # POSTPONE SETTINGS
    # ═══════════════════════════════════════════════════════
    "postpone_hours": 8,                   # "Later" = 8h
    "max_postpones": 3,                    # Max 3x postpone
}
```

---

## 8. USER FLOW DIAGRAM

```
                           START
                             │
                             ▼
              ┌──────────────────────────────┐
              │ F.A.S. collects features     │
              │ (runs autonomously in        │
              │  background)                 │
              └──────────────┬───────────────┘
                             │
                             ▼
              ┌──────────────────────────────┐
              │ 7+ features with >85%?       │
              └──────────────┬───────────────┘
                             │
                    ┌────────┴────────┐
                    │                 │
                    NO               YES
                    │                 │
                    ▼                 ▼
         ┌─────────────────┐  ┌─────────────────┐
         │ Keep waiting    │  │ User ready?     │
         │ (or Super+F)   │  │ (Activity Check)│
         └─────────────────┘  └────────┬────────┘
                                       │
                              ┌────────┴────────┐
                              │                 │
                              NO               YES
                              │                 │
                              ▼                 ▼
                    ┌─────────────────┐  ┌─────────────────┐
                    │ Wait 5min,     │  │ 🔔 POPUP        │
                    │ then check     │  │ appears          │
                    │ again          │  │ + Sound          │
                    └─────────────────┘  └────────┬────────┘
                                                  │
                              ┌────────────────────┴────────────────────┐
                              │                    │                    │
                              ▼                    ▼                    ▼
                     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
                     │ IMPLEMENT    │     │ INTEGRATE    │     │ NONE /       │
                     │ ALL          │     │ SELECTED     │     │ LATER        │
                     └──────┬───────┘     └──────┬───────┘     └──────┬───────┘
                            │                    │                    │
                            └─────────┬──────────┘                    │
                                      │                               │
                                      ▼                               ▼
                            ┌─────────────────┐              ┌─────────────────┐
                            │ Integration     │              │ Archive /       │
                            │ Progress        │              │ 8h Cooldown     │
                            │ (with Sound)    │              └─────────────────┘
                            └────────┬────────┘
                                     │
                                     ▼
                            ┌─────────────────┐
                            │ ✓ DONE          │
                            │ New capabilities│
                            │ available       │
                            └─────────────────┘
```

---

## 9. IMPLEMENTATION ORDER

```
Phase 1: Core Infrastructure
────────────────────────────
 □ fas_popup_daemon.py (Base daemon)
 □ Activity Detector (Mouse, Fullscreen, etc.)
 □ Proposal Queue Manager

Phase 2: GTK4 Popup
────────────────────────────
 □ main_window.py (Basic framework)
 □ cyberpunk.css (Theme)
 □ feature_list.py (List with checkboxes)
 □ Action Buttons

Phase 3: Sound System
────────────────────────────
 □ Create/obtain sound files
 □ Implement SoundManager
 □ Integration into popup

Phase 4: Keyboard Shortcuts
────────────────────────────
 □ Global Hotkey Daemon (Super+F)
 □ Popup-internal navigation
 □ xbindkeys integration

Phase 5: Archive & Details
────────────────────────────
 □ archive_view.py
 □ details_view.py
 □ Reactivation logic

Phase 6: Use-Case Generator
────────────────────────────
 □ use_case_generator.py
 □ Personalization logic
 □ Integration into UI

Phase 7: Polish & Testing
────────────────────────────
 □ Animations (CSS)
 □ Edge Cases
 □ systemd Service Setup
```

---

## Ready for Implementation?

This concept defines a complete, well-thought-out system. Let me know when you're ready and I'll begin with Phase 1.
