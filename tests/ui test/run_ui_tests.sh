#!/bin/bash
# Frank AI - UI Test Runner Launcher
# ===================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Prüfe ob DISPLAY gesetzt ist
if [ -z "$DISPLAY" ]; then
    export DISPLAY=:0
fi

# Prüfe Abhängigkeiten
check_deps() {
    local missing=()

    python3 -c "import mss" 2>/dev/null || missing+=("mss")
    python3 -c "import PIL" 2>/dev/null || missing+=("pillow")
    python3 -c "import pyautogui" 2>/dev/null || missing+=("pyautogui")

    if [ ${#missing[@]} -gt 0 ]; then
        echo "Fehlende Python-Pakete: ${missing[*]}"
        echo "Installiere mit: pip install --break-system-packages ${missing[*]}"
        exit 1
    fi

    # Optional: tesseract für OCR
    if ! command -v tesseract &> /dev/null; then
        echo "HINWEIS: tesseract nicht installiert - OCR wird deaktiviert"
        echo "Installiere mit: sudo apt install tesseract-ocr tesseract-ocr-deu"
    fi
}

# Hauptprogramm
main() {
    echo "==================================="
    echo "  Frank AI - UI Test Runner"
    echo "==================================="
    echo ""

    check_deps

    echo "Starte UI Test Runner..."
    python3 ui_test_runner.py
}

main "$@"
