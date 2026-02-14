#!/bin/bash
# Frank AI - Intelligenter UI-Test
# Lokal mit Ollama (llava) - keine API-Keys nötig!

cd "$(dirname "$0")"
export DISPLAY="${DISPLAY:-:0}"

echo "========================================"
echo "  FRANK AI - INTELLIGENTER UI-TEST"
echo "  Lokal mit Ollama/llava"
echo "========================================"
echo ""

# Ollama prüfen
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "FEHLER: Ollama läuft nicht!"
    echo "Starte mit: ollama serve"
    exit 1
fi

# moondream prüfen (schneller als llava)
if ! curl -s http://localhost:11434/api/tags | grep -q "moondream"; then
    echo "moondream Model nicht gefunden, lade herunter..."
    ollama pull moondream
fi

echo "Starte Test... (ESC zum Abbrechen)"
echo ""

python3 ai_tester.py "$@"
