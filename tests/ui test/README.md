# Frank AI - UI Test Module v2.0

Automated UI testing with screenshot comparison, design analysis, and UX metrics.

## Features

| Feature | Description |
|---------|-------------|
| **Tests** | 17 automated UI tests in 6 categories |
| **Design Analysis** | Colors, contrast, WCAG, layout |
| **Workflow Analysis** | UX metrics, user flows |
| **Visual Regression** | Pixel comparison with baseline |
| **Responsive Tests** | Various window sizes |
| **Heatmap Analysis** | Click and focus areas |
| **Concrete Suggestions** | Actionable CSS fixes |
| **Headless Mode** | CI/CD integration with Xvfb |

## Quick Start

### GUI Version
```bash
cd "/home/ai-core-node/aicore/opt/aicore/tests/ui test"
DISPLAY=:0 python3 ui_test_runner.py
```

### CLI Version
```bash
# All tests, 15 minutes
python3 cli_runner.py --duration 15

# Headless for CI/CD
python3 cli_runner.py --headless --duration 10

# Visual Regression
python3 cli_runner.py --regression

# Design analysis with concrete suggestions
python3 cli_runner.py --design --concrete

# Responsive Tests
python3 cli_runner.py --responsive
```

## CLI Options

### General
| Option | Description |
|--------|-------------|
| `--duration, -d` | Test duration in minutes (default: 15) |
| `--interval, -i` | Interval in seconds (default: 30) |
| `--tests, -t` | Test IDs or 'all' |
| `--no-ocr` | Disable OCR |
| `--no-screenshots` | Don't save screenshots |
| `--headless` | Start Xvfb automatically |
| `--list` | List available tests |

### Visual Regression
| Option | Description |
|--------|-------------|
| `--regression` | Run regression test |
| `--baseline-update` | Update baseline |
| `--threshold` | Max difference in % (default: 0.1) |

### Design Analysis
| Option | Description |
|--------|-------------|
| `--design` | Run design analysis |
| `--concrete` | Concrete CSS suggestions |

### Responsive Tests
| Option | Description |
|--------|-------------|
| `--responsive` | Run responsive tests |
| `--responsive-sizes` | Sizes: mobile,tablet,laptop,desktop |

### Heatmap
| Option | Description |
|--------|-------------|
| `--heatmap` | Heatmap analysis |
| `--heatmap-duration` | Simulation duration (default: 30s) |

## Available Tests

### Basic
- `chat_overlay_visible` - Overlay visible
- `desktopd_health` - Desktop daemon running
- `screenshot_quality` - Screenshot works

### Rendering
- `chat_overlay_truncation` - No truncation
- `text_readability` - Text readable (contrast)
- `layout_consistency` - Layout consistent

### Workflow
- `basic_workflow` - Basic interaction
- `scroll_workflow` - Scrolling works
- `copy_paste_workflow` - Copy/Paste
- `keyboard_navigation` - Keyboard nav

### Convenience
- `response_time` - Response time < 1s
- `window_focus` - Focus works
- `input_handling` - Input processing

### Design
- `color_contrast` - WCAG contrast
- `color_palette` - Color palette
- `visual_hierarchy` - Hierarchy

### Accessibility
- `accessibility_basic` - WCAG compliance

## Directory Structure

```
ui test/
├── ui_test_runner.py       # GUI (4 tabs)
├── cli_runner.py           # CLI with all features
├── test_engine.py          # Screenshot & test engine
├── test_cases.py           # 17 test implementations
├── design_analyzer.py      # Colors, contrast, WCAG
├── workflow_analyzer.py    # UX metrics
├── visual_regression.py    # Pixel comparison
├── heatmap_analyzer.py     # Click/focus heatmaps
├── concrete_suggestions.py # Concrete CSS fixes
├── config.json             # Settings
├── screenshots/            # Screenshots
├── baseline/               # Regression baselines
├── reports/                # JSON/HTML reports
└── README.md
```

## Visual Regression Workflow

```bash
# 1. Create baseline
python3 cli_runner.py --regression --baseline-update

# 2. After changes: compare
python3 cli_runner.py --regression

# 3. For intended changes: update baseline
python3 cli_runner.py --regression --baseline-update
```

## Concrete Suggestions (Example)

```markdown
## Contrast

### Critical Contrast Deficiency
Text/background contrast 3.2:1 is below WCAG AA (4.5:1)
- **Current:** #a6adc8 on #1e1e2e = 3.2:1
- **Recommended:** #cdd6f4 on #1e1e2e = 5.8:1

​```css
color: #cdd6f4; /* was: #a6adc8 */
​```
```

## CI/CD Integration

```yaml
# GitHub Actions example
- name: UI Tests
  run: |
    cd /path/to/ui\ test
    python3 cli_runner.py --headless --duration 5 --regression
```

## Dependencies

### Python
```bash
pip install --break-system-packages pyautogui pillow pytesseract opencv-python mss numpy
```

### System
```bash
sudo apt install tesseract-ocr tesseract-ocr-deu xvfb wmctrl xdotool
```

## Cleanup

```bash
rm -rf "/home/ai-core-node/aicore/opt/aicore/tests/ui test"
```
