# E-SMC "Sovereign" - Installations-Anleitung

## Automatische Installation (empfohlen)

```bash
cd /home/ai-core-node/aicore/opt/aicore/ext/sovereign
./install.sh
```

## Manuelle Installation

### 1. frank-execute Wrapper installieren

```bash
sudo cp frank-execute /usr/local/bin/
sudo chmod 755 /usr/local/bin/frank-execute
```

### 2. Sudoers konfigurieren

```bash
sudo cp frank-execute.sudoers /etc/sudoers.d/frank-execute
sudo chmod 440 /etc/sudoers.d/frank-execute

# Syntax prüfen (WICHTIG!)
sudo visudo -c
```

### 3. Log-Datei vorbereiten

```bash
sudo touch /var/log/frank-execute.log
sudo chown ai-core-node:ai-core-node /var/log/frank-execute.log
```

### 4. Test

```bash
# Sollte ohne Passwort funktionieren
sudo /usr/local/bin/frank-execute

# Test: apt-install simulation
python3 -c "from ext.sovereign import propose_installation; print(propose_installation('htop', 'Test').status.value)"
```

## Sicherheits-Features

- **Whitelist-basiert**: Nur erlaubte Befehle können ausgeführt werden
- **Protected Packages**: 37 System-kritische Pakete sind unantastbar
- **Gaming-Lock**: Während Gaming-Mode sind alle Änderungen blockiert
- **Daily Limits**: Max 5 Installationen, 10 Config-Änderungen pro Tag
- **Audit-Trail**: Alle Aktionen werden in SQLite protokolliert
- **Backup-Axiom**: Backup VOR jeder Änderung

## Deinstallation

```bash
sudo rm /usr/local/bin/frank-execute
sudo rm /etc/sudoers.d/frank-execute
sudo rm /var/log/frank-execute.log
```
