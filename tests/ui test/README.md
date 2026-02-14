# Frank AI - UI Test Module v2.0

Automatisiertes UI-Testing mit Screenshot-Vergleich, Design-Analyse und UX-Metriken.

## Features

| Feature | Beschreibung |
|---------|--------------|
| **Tests** | 17 automatisierte UI-Tests in 6 Kategorien |
| **Design-Analyse** | Farben, Kontrast, WCAG, Layout |
| **Workflow-Analyse** | UX-Metriken, Benutzerflows |
| **Visual Regression** | Pixel-Vergleich mit Baseline |
| **Responsive Tests** | Verschiedene Fenstergrößen |
| **Heatmap-Analyse** | Klick- und Fokus-Bereiche |
| **Konkrete Vorschläge** | Actionable CSS-Fixes |
| **Headless-Modus** | CI/CD-Integration mit Xvfb |

## Schnellstart

### GUI Version
```bash
cd "/home/ai-core-node/aicore/opt/aicore/tests/ui test"
DISPLAY=:0 python3 ui_test_runner.py
```

### CLI Version
```bash
# Alle Tests, 15 Minuten
python3 cli_runner.py --duration 15

# Headless für CI/CD
python3 cli_runner.py --headless --duration 10

# Visual Regression
python3 cli_runner.py --regression

# Design-Analyse mit konkreten Vorschlägen
python3 cli_runner.py --design --concrete

# Responsive Tests
python3 cli_runner.py --responsive
```

## CLI Optionen

### Allgemein
| Option | Beschreibung |
|--------|--------------|
| `--duration, -d` | Testdauer in Minuten (default: 15) |
| `--interval, -i` | Intervall in Sekunden (default: 30) |
| `--tests, -t` | Test-IDs oder 'all' |
| `--no-ocr` | OCR deaktivieren |
| `--no-screenshots` | Screenshots nicht speichern |
| `--headless` | Xvfb automatisch starten |
| `--list` | Verfügbare Tests auflisten |

### Visual Regression
| Option | Beschreibung |
|--------|--------------|
| `--regression` | Regression-Test ausführen |
| `--baseline-update` | Baseline aktualisieren |
| `--threshold` | Max. Differenz in % (default: 0.1) |

### Design-Analyse
| Option | Beschreibung |
|--------|--------------|
| `--design` | Design-Analyse ausführen |
| `--concrete` | Konkrete CSS-Vorschläge |

### Responsive Tests
| Option | Beschreibung |
|--------|--------------|
| `--responsive` | Responsive Tests ausführen |
| `--responsive-sizes` | Größen: mobile,tablet,laptop,desktop |

### Heatmap
| Option | Beschreibung |
|--------|--------------|
| `--heatmap` | Heatmap-Analyse |
| `--heatmap-duration` | Simulations-Dauer (default: 30s) |

## Verfügbare Tests

### Basic
- `chat_overlay_visible` - Overlay sichtbar
- `desktopd_health` - Desktop Daemon läuft
- `screenshot_quality` - Screenshot funktioniert

### Rendering
- `chat_overlay_truncation` - Keine Truncation
- `text_readability` - Text lesbar (Kontrast)
- `layout_consistency` - Layout konsistent

### Workflow
- `basic_workflow` - Basis-Interaktion
- `scroll_workflow` - Scroll funktioniert
- `copy_paste_workflow` - Copy/Paste
- `keyboard_navigation` - Keyboard-Nav

### Convenience
- `response_time` - Reaktionszeit < 1s
- `window_focus` - Focus funktioniert
- `input_handling` - Input-Verarbeitung

### Design
- `color_contrast` - WCAG Kontrast
- `color_palette` - Farbpalette
- `visual_hierarchy` - Hierarchie

### Accessibility
- `accessibility_basic` - WCAG Compliance

## Ordnerstruktur

```
ui test/
├── ui_test_runner.py       # GUI (4 Tabs)
├── cli_runner.py           # CLI mit allen Features
├── test_engine.py          # Screenshot & Test Engine
├── test_cases.py           # 17 Test-Implementierungen
├── design_analyzer.py      # Farben, Kontrast, WCAG
├── workflow_analyzer.py    # UX-Metriken
├── visual_regression.py    # Pixel-Vergleich
├── heatmap_analyzer.py     # Klick-/Fokus-Heatmaps
├── concrete_suggestions.py # Konkrete CSS-Fixes
├── config.json             # Einstellungen
├── screenshots/            # Screenshots
├── baseline/               # Regression Baselines
├── reports/                # JSON/HTML Reports
└── README.md
```

## Visual Regression Workflow

```bash
# 1. Baseline erstellen
python3 cli_runner.py --regression --baseline-update

# 2. Nach Änderungen: Vergleich
python3 cli_runner.py --regression

# 3. Bei gewollten Änderungen: Baseline aktualisieren
python3 cli_runner.py --regression --baseline-update
```

## Konkrete Vorschläge (Beispiel)

```markdown
## Contrast

### 🔴 Kritischer Kontrast-Mangel
Text/Hintergrund-Kontrast 3.2:1 ist unter WCAG AA (4.5:1)
- **Aktuell:** #a6adc8 auf #1e1e2e = 3.2:1
- **Empfohlen:** #cdd6f4 auf #1e1e2e = 5.8:1

​```css
color: #cdd6f4; /* vorher: #a6adc8 */
​```
```

## CI/CD Integration

```yaml
# GitHub Actions Beispiel
- name: UI Tests
  run: |
    cd /path/to/ui\ test
    python3 cli_runner.py --headless --duration 5 --regression
```

## Abhängigkeiten

### Python
```bash
pip install --break-system-packages pyautogui pillow pytesseract opencv-python mss numpy
```

### System
```bash
sudo apt install tesseract-ocr tesseract-ocr-deu xvfb wmctrl xdotool
```

## Aufräumen

```bash
rm -rf "/home/ai-core-node/aicore/opt/aicore/tests/ui test"
```
