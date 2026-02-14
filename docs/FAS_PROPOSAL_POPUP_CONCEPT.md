# F.A.S. Proposal Popup System - Konzept v1.0

## Problemanalyse

### Das User-Verhalten verstehen
- User gehen **nicht** proaktiv in kollaborative Prozesse
- Datenflut = Ignorieren = Feature wird nie genutzt
- Zu häufige Interrupts = Nervig = Popup wird weggeklickt ohne zu lesen
- Zu seltene Interrupts = Features veralten = Irrelevant

### Die Lösung: "Intelligent Minimal Interruption"
Frank sammelt autonom, analysiert autonom, kuratiert autonom - und präsentiert **nur wenn es sich lohnt** in einem **unübersehbaren aber nicht nervigen** Format.

---

## Architektur-Übersicht

```
┌─────────────────────────────────────────────────────────────────┐
│                    F.A.S. BACKEND (bereits gebaut)              │
│  Scout → Triage → Extract → Sandbox Test → Confidence Score     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                    [Proposal Queue Manager]
                              ↓
              ┌───────────────┴───────────────┐
              │      TRIGGER CONDITIONS       │
              │  • Min 7 Features @ >85%      │
              │  • Max 2x pro Tag             │
              │  • User Activity Detection    │
              │  • Cooldown: 8h nach Popup    │
              └───────────────┬───────────────┘
                              ↓
              ┌───────────────┴───────────────┐
              │     ACTIVITY DETECTOR         │
              │  • Mausbewegung aktiv?        │
              │  • Kein Fullscreen-Game?      │
              │  • Desktop sichtbar?          │
              │  • Keine Video-Wiedergabe?    │
              │  • CPU < 50%?                 │
              │  • Letzte Interaktion < 5min? │
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

## Trigger-Logik im Detail

### Proposal Queue Manager

```python
class ProposalQueueManager:
    """
    Entscheidet WANN das Popup erscheint.
    Sammelt Features bis Schwellenwert erreicht.
    """

    # Konfiguration
    MIN_FEATURES_FOR_POPUP = 7          # Mindestens 7 Features
    MIN_CONFIDENCE_SCORE = 0.85         # Jedes Feature >85%
    MAX_POPUPS_PER_DAY = 2              # Max 2x am Tag
    COOLDOWN_HOURS = 8                  # 8h zwischen Popups
    FEATURE_EXPIRY_DAYS = 14            # Features älter als 14 Tage = auto-dismiss

    def should_trigger_popup(self) -> Tuple[bool, str]:
        """
        Returns (should_trigger, reason)
        """
        # 1. Genug qualitativ hochwertige Features?
        ready_features = self.get_high_confidence_features()
        if len(ready_features) < MIN_FEATURES_FOR_POPUP:
            return False, f"Only {len(ready_features)}/{MIN_FEATURES_FOR_POPUP} features ready"

        # 2. Tägliches Limit nicht erreicht?
        popups_today = self.get_popups_today()
        if popups_today >= MAX_POPUPS_PER_DAY:
            return False, "Daily popup limit reached"

        # 3. Cooldown eingehalten?
        last_popup = self.get_last_popup_time()
        if last_popup and (now - last_popup).hours < COOLDOWN_HOURS:
            return False, f"Cooldown active ({COOLDOWN_HOURS}h)"

        # 4. User ist aufnahmefähig?
        if not ActivityDetector.is_user_receptive():
            return False, "User not receptive"

        return True, f"{len(ready_features)} features ready for proposal"
```

### Activity Detector (User-Aufnahmefähigkeit)

```python
class ActivityDetector:
    """
    Erkennt wann der User "bereit" ist für ein Popup.
    Ziel: Popup erscheint wenn User aktiv aber nicht beschäftigt ist.
    """

    # Idealer Moment: User hat gerade etwas beendet, ist noch am PC

    @staticmethod
    def is_user_receptive() -> bool:
        checks = [
            ActivityDetector._is_mouse_active_recently(),      # Maus bewegt in letzten 2min
            ActivityDetector._no_fullscreen_app(),             # Kein Fullscreen
            ActivityDetector._no_video_playing(),              # Kein Video/Stream
            ActivityDetector._cpu_not_busy(),                  # CPU < 50%
            ActivityDetector._no_presentation_mode(),          # Kein Präsentationsmodus
            ActivityDetector._desktop_visible(),               # Desktop nicht komplett verdeckt
        ]
        return all(checks)

    @staticmethod
    def _is_mouse_active_recently() -> bool:
        """Prüft ob Maus in letzten 2 Minuten bewegt wurde."""
        # Via /dev/input oder xdotool
        pass

    @staticmethod
    def _no_fullscreen_app() -> bool:
        """Kein Fenster im Fullscreen-Modus."""
        # Via wmctrl oder X11
        result = subprocess.run(['xdotool', 'getactivewindow'], capture_output=True)
        window_id = result.stdout.strip()
        # Check _NET_WM_STATE_FULLSCREEN
        pass

    @staticmethod
    def _no_video_playing() -> bool:
        """Kein Video wird abgespielt (YouTube, VLC, etc.)."""
        # Check für bekannte Video-Player Prozesse mit aktiver Wiedergabe
        # Oder: pulseaudio sink-inputs prüfen
        pass

    @staticmethod
    def get_best_popup_moment() -> Optional[datetime]:
        """
        Analysiert User-Patterns und schlägt optimalen Moment vor.
        Lernt aus vergangenen Interaktionen.
        """
        # Historische Daten: Wann hat User in der Vergangenheit
        # am schnellsten/positivsten auf Popups reagiert?
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
│    ║    └─ Intelligentes Rate-Limiting für API-Calls             ║    │
│    ║       Verhindert 429-Errors, optimiert Throughput            ║    │
│    ║                                                    [DETAILS] ║    │
│    ║  ────────────────────────────────────────────────────────── ║    │
│    ║  ☐ Async Task Queue Manager         [91%] ──────────█████   ║    │
│    ║    └─ Robuste Task-Verwaltung mit Retry-Logik               ║    │
│    ║       Basis: celery-patterns, optimiert für Frank            ║    │
│    ║                                                    [DETAILS] ║    │
│    ║  ────────────────────────────────────────────────────────── ║    │
│    ║  ☑ Semantic Code Search             [89%] ──────────████▌   ║    │
│    ║    └─ Code-Suche via Embeddings statt Keywords              ║    │
│    ║       "Finde Funktionen die X machen" wird möglich           ║    │
│    ║                                                    [DETAILS] ║    │
│    ║  ────────────────────────────────────────────────────────── ║    │
│    ║  ... (scrollbar für mehr)                                   ║    │
│    ║                                                              ║    │
│    ╠══════════════════════════════════════════════════════════════╣    │
│    ║                                                              ║    │
│    ║  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐ ║    │
│    ║  │ ✓ ALLE      │ │ ✗ KEINE     │ │ ⏰ SPÄTER (8h)       │ ║    │
│    ║  │  UMSETZEN   │ │  RELEVANT   │ │                      │ ║    │
│    ║  └──────────────┘ └──────────────┘ └──────────────────────┘ ║    │
│    ║                                                              ║    │
│    ║           ┌────────────────────────────────┐                 ║    │
│    ║           │  ▶ AUSGEWÄHLTE INTEGRIEREN (2) │                 ║    │
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

## Button-Logik

### Die 4 Aktionen

| Button | Verhalten | Datenbank-Effekt |
|--------|-----------|------------------|
| **✓ ALLE UMSETZEN** | Alle Features → Integration Queue | `integration_status = 'approved'` für alle |
| **✗ KEINE RELEVANT** | Alle Features permanent dismissed | `integration_status = 'rejected_permanent'` |
| **⏰ SPÄTER** | Popup schließt, erscheint in 8h wieder | `postponed_until = now + 8h` |
| **▶ AUSGEWÄHLTE** | Nur angekreuzte → Integration | Nur selected → `approved` |

### Wichtig: "Keine Relevant" ist permanent

```python
def dismiss_all_permanently(feature_ids: List[int]):
    """
    User hat entschieden: Diese Features sind nicht interessant.
    Sie werden NIEMALS wieder vorgeschlagen.
    """
    for fid in feature_ids:
        db.execute("""
            UPDATE extracted_features
            SET integration_status = 'rejected_permanent',
                user_response = 'Batch dismissed via popup',
                user_approved_at = ?
            WHERE id = ?
        """, (datetime.now().isoformat(), fid))

    # Diese Features tauchen NIE wieder auf
    # Auch nicht in der CLI oder anderswo
```

---

## Integration Flow nach Approval

```
User klickt "AUSGEWÄHLTE INTEGRIEREN (3)"
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
         (Nach Abschluss)
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
│  [ Frank wird diese Tools ab sofort ]   │
│  [ in Conversations nutzen können  ]   │
│                                         │
│           [  VERSTANDEN  ]              │
└─────────────────────────────────────────┘
```

---

## Daemon-Architektur

### fas_popup_daemon.py

```python
"""
F.A.S. Proposal Popup Daemon
Läuft als systemd user service, prüft periodisch ob Popup getriggert werden soll.
"""

class FASPopupDaemon:
    CHECK_INTERVAL = 300  # Alle 5 Minuten prüfen

    def run(self):
        while True:
            try:
                should_trigger, reason = self.queue_manager.should_trigger_popup()

                if should_trigger:
                    # Warte auf optimalen Moment
                    if ActivityDetector.is_user_receptive():
                        self.launch_popup()
                        self.record_popup_shown()
                    else:
                        # User nicht bereit, in 5min nochmal prüfen
                        LOG.info("Popup ready but user not receptive, waiting...")

                time.sleep(self.CHECK_INTERVAL)

            except Exception as e:
                LOG.error(f"Daemon error: {e}")
                time.sleep(60)

    def launch_popup(self):
        """Startet das GTK Popup als subprocess."""
        features = self.get_proposal_features()

        # Features als JSON an Popup übergeben
        subprocess.Popen([
            sys.executable,
            str(POPUP_SCRIPT),
            "--features", json.dumps(features),
        ])
```

---

## Dateistruktur

```
/home/ai-core-node/aicore/opt/aicore/
├── tools/
│   ├── fas_scavenger.py          # Backend (bereits gebaut)
│   ├── fas_popup_daemon.py       # NEU: Daemon der Popup triggert
│   └── discovered/               # Integrierte Features landen hier
│
├── ui/
│   ├── fas_proposal_popup.py     # NEU: GTK4 Popup Window
│   ├── fas_proposal_popup.css    # NEU: Cyberpunk Styling
│   └── fas_progress_dialog.py    # NEU: Integration Progress
│
└── services/
    └── fas-popup.service         # NEU: systemd user service
```

---

## Konfiguration

```python
# /home/ai-core-node/aicore/opt/aicore/config/fas_popup_config.py

FAS_POPUP_CONFIG = {
    # Trigger-Schwellenwerte
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
    "preferred_hours": [9, 10, 11, 14, 15, 16],  # Bevorzugte Uhrzeiten
    "avoid_hours": [0, 1, 2, 3, 4, 5, 6, 22, 23],  # Niemals nachts
}
```

---

## User Flow Zusammenfassung

```
                    ┌─────────────────────────┐
                    │   F.A.S. läuft 24/7     │
                    │   (Nachts, bei Idle)    │
                    └───────────┬─────────────┘
                                ↓
                    ┌─────────────────────────┐
                    │ Features werden entdeckt │
                    │ und in Sandbox getestet  │
                    └───────────┬─────────────┘
                                ↓
                    ┌─────────────────────────┐
                    │ 7+ Features mit >85%    │
                    │ Confidence gesammelt    │
                    └───────────┬─────────────┘
                                ↓
                    ┌─────────────────────────┐
                    │ User ist gerade aktiv   │
                    │ aber nicht beschäftigt  │
                    └───────────┬─────────────┘
                                ↓
              ╔═══════════════════════════════════╗
              ║                                   ║
              ║   POPUP ERSCHEINT AUTOMATISCH    ║
              ║   (unübersehbar, zentriert)      ║
              ║                                   ║
              ╚═══════════════════════════════════╝
                                ↓
                    ┌─────────────────────────┐
                    │ User wählt mit Klicks:  │
                    │ • Einzelne Features     │
                    │ • Alle                  │
                    │ • Keine                 │
                    │ • Später                │
                    └───────────┬─────────────┘
                                ↓
                    ┌─────────────────────────┐
                    │ Frank integriert        │
                    │ ausgewählte Features    │
                    └───────────┬─────────────┘
                                ↓
                    ┌─────────────────────────┐
                    │ Neue Fähigkeiten sind   │
                    │ sofort verfügbar        │
                    └─────────────────────────┘
```

---

## Kritische Design-Entscheidungen

### 1. Warum Minimum 7 Features?
- Weniger = zu häufige Popups = nervig
- 7 gibt dem User echte Auswahl
- Batch-Processing ist effizienter
- User fühlt sich nicht mit Einzelentscheidungen belästigt

### 2. Warum 85% Confidence Minimum?
- Keine halbgaren Features vorschlagen
- User-Vertrauen aufbauen
- "Wenn Frank was vorschlägt, ist es gut"
- Lieber weniger, dafür qualitativ

### 3. Warum "Später" statt "Abbrechen"?
- Abbrechen = Feature verschwindet = User verpasst was
- Später = Respektiert User's Zeit, Feature kommt wieder
- 8h Cooldown = Genug Zeit, nicht zu lange

### 4. Warum Activity Detection?
- Popup während Gaming/Video = Genervt = Wegklicken ohne Lesen
- Popup nach gerade beendeter Aktivität = User ist aufnahmebereit
- Lernen aus Patterns = Immer besseres Timing

### 5. Warum Permanent Dismiss Option?
- User weiß selbst was er braucht
- Irrelevante Features sollen nie wiederkommen
- Spart zukünftige Interrupts
- Vertrauen: "Frank versteht mich"

---

## Nächste Schritte zur Implementierung

1. **fas_popup_daemon.py** - Daemon der Trigger-Logik implementiert
2. **fas_proposal_popup.py** - GTK4 Popup mit Cyberpunk CSS
3. **Activity Detection** - Mouse/Fullscreen/Video-Erkennung
4. **Integration in F.A.S.** - Neue Status-Felder, Queue-Management
5. **systemd Service** - User-Service für Daemon
6. **Testing** - Mit Mock-Features testen

---

## Offene Fragen für User

1. Soll das Popup einen Sound abspielen wenn es erscheint?
2. Soll es eine Keyboard-Shortcut geben um das Popup manuell zu öffnen?
3. Sollen abgelehnte Features in einem "Archive" einsehbar bleiben?
4. Soll Frank erklären WARUM er ein Feature vorschlägt (Use-Case)?
