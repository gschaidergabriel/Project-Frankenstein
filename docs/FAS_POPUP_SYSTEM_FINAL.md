# F.A.S. Proposal Popup System - Finales Konzept v2.0

## Übersicht

Ein vollständig autonomes Feature-Proposal-System das:
- Intelligent den richtigen Moment wählt
- Unübersehbar aber nicht nervig ist
- Mit wenigen Klicks bedienbar ist
- Frank's Use-Cases erklärt
- Sound-Feedback gibt
- Per Hotkey manuell aufrufbar ist
- Ein Archive für abgelehnte Features hat

---

## 1. SOUND SYSTEM

### Konzept
Subtiler aber unverwechselbarer Sound wenn Popup erscheint - nicht nervig, aber Aufmerksamkeit erregend.

### Sound-Design

```
┌─────────────────────────────────────────────────────────────────┐
│                      SOUND EVENTS                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  POPUP ERSCHEINT:                                               │
│  ───────────────                                                │
│  "Cyberpunk Chime" - Kurzer synthetischer Ton (0.8s)           │
│  - Frequenz: Aufsteigend 440Hz → 880Hz                         │
│  - Reverb: Leichter Hall für "digitalen" Charakter             │
│  - Lautstärke: 60% System-Volume (nicht erschreckend)          │
│                                                                 │
│  FEATURE AUSGEWÄHLT (Checkbox):                                 │
│  ─────────────────────────────                                  │
│  Kurzer "Click" Sound (0.1s)                                   │
│  - Bestätigendes Feedback                                       │
│                                                                 │
│  INTEGRATION STARTET:                                           │
│  ───────────────────                                            │
│  "Power Up" Sound (0.5s)                                       │
│  - Aufsteigender Synthesizer                                    │
│                                                                 │
│  INTEGRATION COMPLETE:                                          │
│  ────────────────────                                           │
│  "Success Chime" (1.0s)                                        │
│  - Harmonischer Dreiklang                                       │
│  - Signalisiert: "Frank hat neue Fähigkeiten"                  │
│                                                                 │
│  SPÄTER/DISMISS:                                                │
│  ──────────────                                                 │
│  Leiser "Whoosh" (0.3s)                                        │
│  - Popup verschwindet                                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Sound-Dateien Struktur

```
/home/ai-core-node/aicore/opt/aicore/ui/sounds/
├── popup_appear.ogg      # Cyberpunk Chime
├── checkbox_click.ogg    # Selection Click
├── integration_start.ogg # Power Up
├── integration_done.ogg  # Success Chime
└── popup_dismiss.ogg     # Whoosh
```

### Sound-Manager

```python
class SoundManager:
    """Verwaltet alle UI-Sounds mit Volume Control."""

    SOUNDS_DIR = Path("ui/sounds/")
    VOLUME = 0.6  # 60% - nicht zu laut

    # Sound kann vom User deaktiviert werden
    enabled: bool = True

    # Cooldown um Sound-Spam zu verhindern
    last_played: Dict[str, float] = {}
    MIN_INTERVAL = 0.2  # Sekunden

    def play(self, sound_name: str):
        """Spielt Sound wenn enabled und Cooldown vorbei."""
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

### Sound Toggle im Popup

```
┌────────────────────────────────────────┐
│  ░▒▓ F.A.S. INTELLIGENCE REPORT ▓▒░   │
│                                        │
│                           🔊 Sound [ON]│  ← Klickbar
└────────────────────────────────────────┘
```

---

## 2. KEYBOARD SHORTCUT SYSTEM

### Konzept
User kann Popup jederzeit manuell öffnen um Status zu prüfen - auch wenn Trigger-Schwellenwert nicht erreicht.

### Global Hotkey

```
┌─────────────────────────────────────────────────────────────────┐
│                     KEYBOARD SHORTCUTS                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  GLOBAL (funktioniert überall):                                 │
│  ─────────────────────────────                                  │
│                                                                 │
│  Super + F  →  F.A.S. Popup öffnen/schließen (Toggle)          │
│              (Super = Windows-Taste)                            │
│                                                                 │
│  ───────────────────────────────────────────────────────────── │
│                                                                 │
│  IM POPUP (wenn offen):                                         │
│  ─────────────────────                                          │
│                                                                 │
│  Space      →  Aktuelles Feature an/abwählen                   │
│  ↑/↓        →  Navigation durch Features                       │
│  Enter      →  "Ausgewählte Integrieren"                       │
│  A          →  Alle auswählen                                   │
│  N          →  Alle abwählen                                    │
│  Escape     →  Später (schließen)                              │
│  D          →  Details zum markierten Feature                   │
│  R          →  Alle permanent ablehnen                         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Hotkey-Daemon

```python
class GlobalHotkeyDaemon:
    """
    Registriert globale Hotkeys via xdotool/xbindkeys.
    Läuft als Teil des fas_popup_daemon.
    """

    HOTKEY = "super+f"  # Windows + F für F.A.S.

    def __init__(self):
        self.popup_visible = False

    def setup_hotkey(self):
        """Registriert den globalen Hotkey."""
        # Methode 1: Via keybinder (Python)
        # Methode 2: Via xbindkeys config
        # Methode 3: Via dbus zu GNOME/KDE

        # Wir nutzen einen Socket-Listener
        # Der Hotkey wird via xbindkeys → socket signal gesendet

    def on_hotkey_pressed(self):
        """Callback wenn Hotkey gedrückt."""
        if self.popup_visible:
            self.hide_popup()
        else:
            self.show_popup(force=True)  # force = auch wenn < 7 Features

    def show_popup(self, force: bool = False):
        """
        Öffnet Popup.
        force=True: Öffnet auch wenn weniger als 7 Features
                    (zeigt dann was da ist + "Noch X Features bis zum nächsten Batch")
        """
        features = self.get_available_features()

        if not features and not force:
            return

        # Popup starten
        subprocess.Popen([
            sys.executable,
            str(POPUP_SCRIPT),
            "--features", json.dumps(features),
            "--manual" if force else "",
        ])
        self.popup_visible = True
```

### Manuell geöffnetes Popup (< 7 Features)

```
┌────────────────────────────────────────────────────────────────────────┐
│                                                                        │
│    ╔══════════════════════════════════════════════════════════════╗    │
│    ║  ░▒▓ F.A.S. STATUS ▓▒░                              🔊 [ON] ║    │
│    ║  ─────────────────────────────────                           ║    │
│    ║  3 FEATURES IN QUEUE (4 mehr für Auto-Popup)                ║    │
│    ╠══════════════════════════════════════════════════════════════╣    │
│    ║                                                              ║    │
│    ║  ☐ GitHub API Rate Limiter          [94%] ──────────█████▌  ║    │
│    ║    └─ Intelligentes Rate-Limiting für API-Calls             ║    │
│    ║                                                              ║    │
│    ║  ☐ Async Task Queue                 [91%] ──────────█████   ║    │
│    ║    └─ Robuste Task-Verwaltung mit Retry                     ║    │
│    ║                                                              ║    │
│    ║  ☐ Semantic Code Search             [89%] ──────────████▌   ║    │
│    ║    └─ Code-Suche via Embeddings                             ║    │
│    ║                                                              ║    │
│    ║  ────────────────────────────────────────────────────────── ║    │
│    ║  💡 Auto-Popup erscheint bei 7+ Features                    ║    │
│    ║     Aktuell: ███░░░░ 3/7                                    ║    │
│    ║                                                              ║    │
│    ╠══════════════════════════════════════════════════════════════╣    │
│    ║                                                              ║    │
│    ║  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐ ║    │
│    ║  │ 📁 ARCHIVE  │ │ ⚙ SETTINGS  │ │      SCHLIEßEN       │ ║    │
│    ║  └──────────────┘ └──────────────┘ └──────────────────────┘ ║    │
│    ║                                                              ║    │
│    ║           ┌────────────────────────────────┐                 ║    │
│    ║           │  ▶ AUSGEWÄHLTE INTEGRIEREN (0) │                 ║    │
│    ║           └────────────────────────────────┘                 ║    │
│    ║                                                              ║    │
│    ╚══════════════════════════════════════════════════════════════╝    │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. ARCHIVE SYSTEM

### Konzept
Abgelehnte Features sind nicht "weg" - sie sind im Archive einsehbar. User kann sie später reaktivieren falls sich Meinung ändert.

### Archive-Ansicht

```
┌────────────────────────────────────────────────────────────────────────┐
│                                                                        │
│    ╔══════════════════════════════════════════════════════════════╗    │
│    ║  ░▒▓ F.A.S. ARCHIVE ▓▒░                             [← BACK] ║    │
│    ║  ─────────────────────────────────                           ║    │
│    ║  23 abgelehnte Features                                      ║    │
│    ╠══════════════════════════════════════════════════════════════╣    │
│    ║                                                              ║    │
│    ║  Filter: [Alle ▼]  [Nach Datum ▼]  🔍 [Suche...]            ║    │
│    ║                                                              ║    │
│    ║  ────────────────────────────────────────────────────────── ║    │
│    ║                                                              ║    │
│    ║  ✗ Docker Compose Generator         [87%]     2026-01-28    ║    │
│    ║    └─ "Brauche ich nicht"                      [REAKTIVIEREN]║    │
│    ║                                                              ║    │
│    ║  ✗ PDF Text Extractor               [92%]     2026-01-25    ║    │
│    ║    └─ Batch dismissed                          [REAKTIVIEREN]║    │
│    ║                                                              ║    │
│    ║  ✗ Slack API Wrapper                [85%]     2026-01-20    ║    │
│    ║    └─ "Nutze kein Slack"                       [REAKTIVIEREN]║    │
│    ║                                                              ║    │
│    ║  ✗ Redis Cache Helper               [91%]     2026-01-15    ║    │
│    ║    └─ Batch dismissed                          [REAKTIVIEREN]║    │
│    ║                                                              ║    │
│    ║  ... (scrollbar)                                             ║    │
│    ║                                                              ║    │
│    ╠══════════════════════════════════════════════════════════════╣    │
│    ║                                                              ║    │
│    ║  Statistik:                                                  ║    │
│    ║  • 23 abgelehnt │ 47 integriert │ 12 in Queue               ║    │
│    ║  • Ältestes: 2025-11-03 │ Neuestes: 2026-01-28              ║    │
│    ║                                                              ║    │
│    ║  ┌────────────────────────────────────────────────────────┐ ║    │
│    ║  │  🗑️ ARCHIVE LEEREN (permanent löschen)                 │ ║    │
│    ║  └────────────────────────────────────────────────────────┘ ║    │
│    ║                                                              ║    │
│    ╚══════════════════════════════════════════════════════════════╝    │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

### Reaktivierung

Wenn User auf [REAKTIVIEREN] klickt:

```
┌─────────────────────────────────────────┐
│  Feature reaktivieren?                  │
│  ═══════════════════════════════════   │
│                                         │
│  "Docker Compose Generator"             │
│                                         │
│  Dieses Feature wird wieder in die      │
│  Queue aufgenommen und beim nächsten    │
│  Auto-Popup vorgeschlagen.              │
│                                         │
│  ┌─────────────┐    ┌─────────────┐    │
│  │   ABBRUCH   │    │ REAKTIVIEREN│    │
│  └─────────────┘    └─────────────┘    │
└─────────────────────────────────────────┘
```

### Datenbank-Status

```python
# integration_status Werte:
FEATURE_STATUS = {
    "pending":              # Neu, noch nicht getestet
    "testing":              # Im Sandbox-Test
    "ready":                # Bereit für Proposal
    "notified":             # User wurde benachrichtigt
    "approved":             # User hat genehmigt
    "integrated":           # Erfolgreich integriert
    "rejected":             # Abgelehnt (kann reaktiviert werden)
    "rejected_permanent":   # Permanent abgelehnt (im Archive)
    "archived_deleted":     # Aus Archive gelöscht
}
```

---

## 4. USE-CASE ERKLÄRUNGEN

### Konzept
Frank erklärt nicht nur WAS ein Feature macht, sondern WARUM es für den User nützlich sein könnte - basierend auf beobachteten Patterns.

### Use-Case Generator

```python
class UseCaseGenerator:
    """
    Generiert personalisierte Use-Case Erklärungen
    basierend auf User's bisheriger Nutzung.
    """

    def generate_use_case(self, feature: Dict) -> str:
        """
        Analysiert Feature und generiert Use-Case.
        """
        feature_type = feature['feature_type']
        name = feature['name']
        code = feature['code_snippet']

        # Basis Use-Case nach Typ
        base_cases = {
            "tool": self._tool_use_case,
            "api_wrapper": self._api_use_case,
            "utility": self._utility_use_case,
            "pattern": self._pattern_use_case,
        }

        base = base_cases.get(feature_type, self._generic_use_case)(feature)

        # Personalisierung basierend auf User-History
        personalized = self._personalize(feature, base)

        return personalized

    def _tool_use_case(self, feature: Dict) -> str:
        """Use-Case für Tools."""
        return f"""
WARUM DIESES FEATURE?
─────────────────────
Dieses Tool erweitert Frank's Fähigkeiten direkt.

KONKRETER ANWENDUNGSFALL:
Wenn du Frank bittest "{self._generate_example_prompt(feature)}",
kann Frank dieses Tool nutzen um die Aufgabe effizienter zu erledigen.

VORHER:  Frank müsste umständlich manuell vorgehen
NACHHER: Direkter Zugriff auf optimierte Funktionalität
"""

    def _api_use_case(self, feature: Dict) -> str:
        """Use-Case für API Wrapper."""
        api_name = self._extract_api_name(feature)
        return f"""
WARUM DIESES FEATURE?
─────────────────────
Integration mit {api_name} Service.

KONKRETER ANWENDUNGSFALL:
Frank kann direkt mit {api_name} kommunizieren:
• Daten abrufen und verarbeiten
• Automatisierte Aktionen ausführen
• Echtzeit-Informationen integrieren

BEISPIEL:
"Frank, {self._generate_api_example(feature)}"
"""

    def _personalize(self, feature: Dict, base: str) -> str:
        """
        Personalisiert Use-Case basierend auf User-Verhalten.
        """
        # Analysiere bisherige Nutzung
        user_patterns = self._get_user_patterns()

        # Wenn User oft X macht und Feature X verbessert → hervorheben
        relevance = self._calculate_personal_relevance(feature, user_patterns)

        if relevance > 0.8:
            personal_note = f"""
💡 PERSÖNLICHE EMPFEHLUNG:
Basierend auf deiner häufigen Nutzung von {relevance['related_feature']}
könnte dieses Feature besonders nützlich sein.
"""
            return base + personal_note

        return base
```

### UI mit Use-Case

```
┌────────────────────────────────────────────────────────────────────────┐
│    ║                                                              ║    │
│    ║  ☐ GitHub API Rate Limiter          [94%] ──────────█████▌  ║    │
│    ║    └─ Intelligentes Rate-Limiting für API-Calls             ║    │
│    ║                                                              ║    │
│    ║    ┌─────────────────────────────────────────────────────┐  ║    │
│    ║    │ 💡 WARUM DIESES FEATURE?                            │  ║    │
│    ║    │                                                     │  ║    │
│    ║    │ Du nutzt oft GitHub-Integrationen. Dieses Tool     │  ║    │
│    ║    │ verhindert automatisch 429-Errors und optimiert    │  ║    │
│    ║    │ den API-Durchsatz.                                 │  ║    │
│    ║    │                                                     │  ║    │
│    ║    │ VORHER:  Manuelle Delays, häufige Rate-Limit-Fehler│  ║    │
│    ║    │ NACHHER: Automatisches Queueing, keine Fehler      │  ║    │
│    ║    │                                                     │  ║    │
│    ║    │ 📊 Persönliche Relevanz: ████████░░ 85%            │  ║    │
│    ║    └─────────────────────────────────────────────────────┘  ║    │
│    ║                                                    [DETAILS] ║    │
│    ║  ────────────────────────────────────────────────────────── ║    │
```

### Expanded Details View

Wenn User auf [DETAILS] klickt:

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
│    ║  • requests (bereits installiert)                           ║    │
│    ║  • asyncio (stdlib)                                         ║    │
│    ║                                                              ║    │
│    ║  USE CASE:                                                   ║    │
│    ║  ┌─────────────────────────────────────────────────────────┐║    │
│    ║  │ Du nutzt häufig GitHub API Calls in deinen Projekten.  │║    │
│    ║  │ Dieses Tool:                                            │║    │
│    ║  │                                                         │║    │
│    ║  │ • Automatisches Queueing bei Rate-Limits               │║    │
│    ║  │ • Exponential Backoff bei 429 Errors                   │║    │
│    ║  │ • Request-Batching für Effizienz                       │║    │
│    ║  │                                                         │║    │
│    ║  │ Beispiel-Nutzung:                                       │║    │
│    ║  │ "Frank, hole alle Issues von den letzten 30 Tagen"     │║    │
│    ║  │ → Frank nutzt Rate Limiter automatisch                 │║    │
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
│    ║  │  ✗ NICHT NUTZEN │              │  ✓ ZUR AUSWAHL HINZU │ ║    │
│    ║  └──────────────────┘              └──────────────────────┘ ║    │
│    ║                                                              ║    │
│    ╚══════════════════════════════════════════════════════════════╝    │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 5. VOLLSTÄNDIGE SYSTEM-ARCHITEKTUR

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
│          │               │ Trigger       │        │ User ist     │    │
│          │               │ Conditions    │◀───────│ aufnahmefähig│    │
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
│          │    ║     • Feature Liste               ║                  │
│          │    ║     • Use-Case Erklärungen        ║◀── Use-Case Gen  │
│          │    ║     • Confidence Bars             ║                  │
│          │    ║     • Checkboxen                  ║                  │
│          │    ║     • Action Buttons              ║                  │
│          │    ║     • Sound Feedback              ║◀── Sound Manager │
│          │    ║     • Keyboard Navigation         ║                  │
│          │    ╚════════════════════════════════════╝                  │
│                              │                                         │
│           ┌──────────────────┼──────────────────┐                     │
│           ▼                  ▼                  ▼                     │
│    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐             │
│    │ ALLE        │    │ AUSGEWÄHLTE │    │ KEINE/      │             │
│    │ UMSETZEN    │    │ INTEGRIEREN │    │ SPÄTER      │             │
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
│           │ (neue Features) │                                        │
│           └─────────────────┘                                        │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

---

## 6. DATEISTRUKTUR

```
/home/ai-core-node/aicore/opt/aicore/
│
├── tools/
│   ├── fas_scavenger.py              # Backend (existiert)
│   └── discovered/                    # Integrierte Features
│
├── ui/
│   ├── fas_popup/
│   │   ├── __init__.py
│   │   ├── main_window.py            # Haupt-Popup GTK4
│   │   ├── feature_list.py           # Feature-Liste Widget
│   │   ├── details_view.py           # Detail-Ansicht
│   │   ├── archive_view.py           # Archive-Ansicht
│   │   ├── progress_dialog.py        # Integration Progress
│   │   ├── settings_dialog.py        # Settings (Sound, etc.)
│   │   ├── use_case_generator.py     # Use-Case Texte
│   │   └── styles/
│   │       ├── cyberpunk.css         # Haupt-Theme
│   │       └── animations.css        # Glow-Effekte etc.
│   │
│   └── sounds/
│       ├── popup_appear.ogg
│       ├── checkbox_click.ogg
│       ├── integration_start.ogg
│       ├── integration_done.ogg
│       └── popup_dismiss.ogg
│
├── services/
│   ├── fas_popup_daemon.py           # Daemon (Trigger + Hotkey)
│   └── fas-popup.service             # systemd user service
│
├── config/
│   └── fas_popup_config.py           # Alle Einstellungen
│
└── database/
    └── fas_scavenger.db              # SQLite (existiert, erweitern)
```

---

## 7. KONFIGURATION

```python
# /home/ai-core-node/aicore/opt/aicore/config/fas_popup_config.py

FAS_POPUP_CONFIG = {
    # ═══════════════════════════════════════════════════════
    # TRIGGER SETTINGS
    # ═══════════════════════════════════════════════════════
    "min_features_for_auto_popup": 7,      # Minimum für Auto-Trigger
    "min_confidence_score": 0.85,          # 85% Minimum
    "max_popups_per_day": 2,               # Max 2x am Tag
    "cooldown_hours": 8,                   # 8h zwischen Popups
    "feature_expiry_days": 14,             # Nach 14 Tagen → Archive

    # ═══════════════════════════════════════════════════════
    # ACTIVITY DETECTION
    # ═══════════════════════════════════════════════════════
    "mouse_idle_threshold_sec": 120,       # 2min ohne Maus = idle
    "cpu_busy_threshold": 50,              # >50% = beschäftigt
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
    "archive_max_items": 100,              # Max 100 im Archive
    "archive_auto_cleanup_days": 90,       # Nach 90 Tagen löschen

    # ═══════════════════════════════════════════════════════
    # POSTPONE SETTINGS
    # ═══════════════════════════════════════════════════════
    "postpone_hours": 8,                   # "Später" = 8h
    "max_postpones": 3,                    # Max 3x verschieben
}
```

---

## 8. USER FLOW DIAGRAMM

```
                           START
                             │
                             ▼
              ┌──────────────────────────────┐
              │ F.A.S. sammelt Features      │
              │ (läuft autonom im Hintergrund)│
              └──────────────┬───────────────┘
                             │
                             ▼
              ┌──────────────────────────────┐
              │ 7+ Features mit >85%?        │
              └──────────────┬───────────────┘
                             │
                    ┌────────┴────────┐
                    │                 │
                   NEIN              JA
                    │                 │
                    ▼                 ▼
         ┌─────────────────┐  ┌─────────────────┐
         │ Warte weiter    │  │ User bereit?    │
         │ (oder Super+F)  │  │ (Activity Check)│
         └─────────────────┘  └────────┬────────┘
                                       │
                              ┌────────┴────────┐
                              │                 │
                             NEIN              JA
                              │                 │
                              ▼                 ▼
                    ┌─────────────────┐  ┌─────────────────┐
                    │ Warte 5min,     │  │ 🔔 POPUP        │
                    │ dann neu prüfen │  │ erscheint       │
                    └─────────────────┘  │ + Sound         │
                                         └────────┬────────┘
                                                  │
                              ┌────────────────────┴────────────────────┐
                              │                    │                    │
                              ▼                    ▼                    ▼
                     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
                     │ ALLE         │     │ AUSGEWÄHLTE  │     │ KEINE /      │
                     │ UMSETZEN     │     │ INTEGRIEREN  │     │ SPÄTER       │
                     └──────┬───────┘     └──────┬───────┘     └──────┬───────┘
                            │                    │                    │
                            └─────────┬──────────┘                    │
                                      │                               │
                                      ▼                               ▼
                            ┌─────────────────┐              ┌─────────────────┐
                            │ Integration     │              │ Archive /       │
                            │ Progress        │              │ 8h Cooldown     │
                            │ (mit Sound)     │              └─────────────────┘
                            └────────┬────────┘
                                     │
                                     ▼
                            ┌─────────────────┐
                            │ ✓ FERTIG        │
                            │ Neue Fähigkeiten│
                            │ verfügbar       │
                            └─────────────────┘
```

---

## 9. IMPLEMENTIERUNGS-REIHENFOLGE

```
Phase 1: Core Infrastructure
────────────────────────────
 □ fas_popup_daemon.py (Basis-Daemon)
 □ Activity Detector (Mouse, Fullscreen, etc.)
 □ Proposal Queue Manager

Phase 2: GTK4 Popup
────────────────────────────
 □ main_window.py (Grundgerüst)
 □ cyberpunk.css (Theme)
 □ feature_list.py (Liste mit Checkboxen)
 □ Action Buttons

Phase 3: Sound System
────────────────────────────
 □ Sound-Dateien erstellen/beschaffen
 □ SoundManager implementieren
 □ Integration in Popup

Phase 4: Keyboard Shortcuts
────────────────────────────
 □ Global Hotkey Daemon (Super+F)
 □ Popup-interne Navigation
 □ xbindkeys Integration

Phase 5: Archive & Details
────────────────────────────
 □ archive_view.py
 □ details_view.py
 □ Reaktivierungs-Logik

Phase 6: Use-Case Generator
────────────────────────────
 □ use_case_generator.py
 □ Personalisierungs-Logik
 □ Integration in UI

Phase 7: Polish & Testing
────────────────────────────
 □ Animations (CSS)
 □ Edge Cases
 □ systemd Service Setup
```

---

## Bereit zur Implementierung?

Dieses Konzept definiert ein vollständiges, durchdachtes System. Sag mir wenn du bereit bist und ich beginne mit Phase 1.
