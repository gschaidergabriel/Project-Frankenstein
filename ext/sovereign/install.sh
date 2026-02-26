#!/bin/bash
# =============================================================================
# E-SMC Sovereign - Installations-Script
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║  E-SMC 'Sovereign' - Evolutionary System-Management & Config    ║"
echo "║  Frank's System-Operator Modul                                   ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo

# Check if running as root
if [[ $EUID -eq 0 ]]; then
    echo "ERROR: Nicht als root ausführen. Das Script fragt bei Bedarf nach sudo."
    exit 1
fi

echo "[1/4] Installiere frank-execute..."
sudo cp "$SCRIPT_DIR/frank-execute" /usr/local/bin/
sudo chmod 755 /usr/local/bin/frank-execute
echo "      ✓ /usr/local/bin/frank-execute"

echo "[2/4] Konfiguriere sudoers..."
sudo cp "$SCRIPT_DIR/frank-execute.sudoers" /etc/sudoers.d/frank-execute
sudo chmod 440 /etc/sudoers.d/frank-execute

# Verify sudoers syntax
if sudo visudo -c 2>/dev/null; then
    echo "      ✓ /etc/sudoers.d/frank-execute"
else
    echo "      ✗ Sudoers-Syntax-Fehler! Entferne Datei..."
    sudo rm /etc/sudoers.d/frank-execute
    exit 1
fi

echo "[3/4] Erstelle Log-Datei..."
sudo touch /var/log/frank-execute.log
sudo chown "$(whoami):$(whoami)" /var/log/frank-execute.log
echo "      ✓ /var/log/frank-execute.log"

echo "[4/4] Teste Installation..."
if sudo /usr/local/bin/frank-execute 2>&1 | grep -q "frank-execute"; then
    echo "      ✓ frank-execute funktioniert"
else
    echo "      ✗ frank-execute Test fehlgeschlagen"
    exit 1
fi

echo
echo "═══════════════════════════════════════════════════════════════════"
echo "  E-SMC Sovereign erfolgreich installiert!"
echo
echo "  Frank kann nun sicher System-Pakete verwalten."
echo
echo "  Limits:"
echo "    - Max 5 Installationen/Tag"
echo "    - Max 10 Config-Änderungen/Tag"
echo "    - 37 geschützte Pakete (unantastbar)"
echo "    - Gaming-Mode = 100% Lock"
echo "═══════════════════════════════════════════════════════════════════"
