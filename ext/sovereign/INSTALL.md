# E-SMC "Sovereign" - Installation Guide

## Automatic Installation (recommended)

```bash
cd /home/ai-core-node/aicore/opt/aicore/ext/sovereign
./install.sh
```

## Manual Installation

### 1. Install frank-execute Wrapper

```bash
sudo cp frank-execute /usr/local/bin/
sudo chmod 755 /usr/local/bin/frank-execute
```

### 2. Configure Sudoers

```bash
sudo cp frank-execute.sudoers /etc/sudoers.d/frank-execute
sudo chmod 440 /etc/sudoers.d/frank-execute

# Verify syntax (IMPORTANT!)
sudo visudo -c
```

### 3. Prepare Log File

```bash
sudo touch /var/log/frank-execute.log
sudo chown ai-core-node:ai-core-node /var/log/frank-execute.log
```

### 4. Test

```bash
# Should work without password
sudo /usr/local/bin/frank-execute

# Test: apt-install simulation
python3 -c "from ext.sovereign import propose_installation; print(propose_installation('htop', 'Test').status.value)"
```

## Security Features

- **Whitelist-based**: Only allowed commands can be executed
- **Protected Packages**: 37 system-critical packages are untouchable
- **Gaming Lock**: All changes are blocked during Gaming Mode
- **Daily Limits**: Max 5 installations, 10 config changes per day
- **Audit Trail**: All actions are logged in SQLite
- **Backup Axiom**: Backup BEFORE every change

## Uninstallation

```bash
sudo rm /usr/local/bin/frank-execute
sudo rm /etc/sudoers.d/frank-execute
sudo rm /var/log/frank-execute.log
```
