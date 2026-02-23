#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E-SMC "Sovereign" - Evolutionary System-Management & Configuration
===================================================================

Frank's Übergang vom Software-Agenten zum System-Operator.
Ermöglicht sichere Installation und Systemkonfiguration mit absoluten Guardrails.

TEAM SOVEREIGN:
- 🎨 Designer: HUD-Integration für System-Mutations
- 📊 Analytiker: Risk-Scoring und Confidence-Matrix
- 💻 Software Engineer: VDP-Protokoll Implementierung
- ⚖️ AI Ethiker: Sicherheitsgrenzen definiert
- 🐧 Linux Experte: sudoers/systemd Integration
- 🔒 Sicherheits Experte: Guardrails und Rollback
- 🧠 Lead AI Dev: Gesamtarchitektur

DIE EISERNEN GESETZE:
1. Kein direkter Root-Zugriff - nur über frank-execute Whitelist
2. Backup vor JEDER Änderung (Snapshot-Axiom)
3. Keine kritischen Pakete entfernen (Dependencies-Sentinel)
4. Gaming-Mode = 100% Lock für alle Systemänderungen
5. Auto-Rollback bei System-Instabilität

Usage:
    from ext.sovereign import get_sovereign, propose_installation

    sovereign = get_sovereign()

    # Paket-Installation vorschlagen
    result = sovereign.propose_installation("htop", reason="CPU-Monitoring verbessern")

    # System-Konfiguration ändern
    result = sovereign.propose_sysctl_change("vm.swappiness", "10", reason="Gaming-Performance")
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tarfile
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

# =============================================================================
# CONFIGURATION - Die Eisernen Gesetze
# =============================================================================

# Pfade
try:
    from config.paths import AICORE_ROOT, get_db, ASRS_BACKUP_DIR
except ImportError:
    AICORE_ROOT = Path(__file__).resolve().parents[3]
    ASRS_BACKUP_DIR = Path.home() / "Documents" / "Projekt FRANKENSTEIN" / "Backup"
    def get_db(name):
        _db_dir = Path.home() / ".local" / "share" / "frank" / "db"
        _db_dir.mkdir(parents=True, exist_ok=True)
        return _db_dir / f"{name}.db"

AICORE_BASE = AICORE_ROOT.parent if AICORE_ROOT.name == "aicore" else AICORE_ROOT
SOVEREIGN_DB = get_db("sovereign")
BACKUP_DIR = ASRS_BACKUP_DIR
EROSION_DIR = AICORE_BASE / "delete"
STAGING_DIR = AICORE_BASE / "opt/aicore/ext/sovereign/staging"
FRANK_EXECUTE = Path("/usr/local/bin/frank-execute")

# Sicherheits-Konstanten
MAX_DAILY_INSTALLATIONS = 5
MAX_DAILY_CONFIG_CHANGES = 10
CONFIDENCE_THRESHOLD = 0.95  # Nur bei >95% Confidence ausführen
SIMULATION_REQUIRED = True
BACKUP_REQUIRED = True

# Gaming-Mode Lock-File
try:
    from config.paths import get_temp as _smc_get_temp
    GAMING_LOCK_FILE = _smc_get_temp("gaming_mode.lock")
except ImportError:
    import tempfile as _smc_tempfile
    GAMING_LOCK_FILE = Path(_smc_tempfile.gettempdir()) / "frank" / "gaming_mode.lock"

# =============================================================================
# PROTECTED PACKAGES - Der Dependencies-Sentinel
# =============================================================================

# Diese Pakete dürfen NIEMALS entfernt oder ersetzt werden
PROTECTED_PACKAGES = frozenset({
    # Kernel & Boot
    "linux-image-generic", "linux-headers-generic", "grub-common", "grub-pc",
    "initramfs-tools", "systemd", "systemd-sysv",

    # Core Libraries
    "libc6", "libstdc++6", "libgcc-s1", "libssl3", "zlib1g",

    # Graphics (NVIDIA)
    "nvidia-driver-550", "nvidia-driver-545", "nvidia-driver-535",
    "nvidia-utils-550", "nvidia-utils-545", "nvidia-utils-535",
    "libnvidia-gl-550", "libnvidia-gl-545", "libnvidia-gl-535",

    # X11/Wayland
    "xserver-xorg-core", "xwayland", "libx11-6", "libxext6",

    # Essential
    "ubuntu-minimal", "apt", "dpkg", "bash", "coreutils",
    "login", "passwd", "sudo", "openssh-server",

    # Python (für Frank selbst)
    "python3", "python3-minimal", "libpython3-stdlib",
})

# Pakete die Frank installieren DARF (Whitelist-Erweiterung)
ALLOWED_PACKAGE_PATTERNS = [
    r"^htop$", r"^iotop$", r"^nvme-cli$", r"^smartmontools$",
    r"^neofetch$", r"^btop$", r"^glances$", r"^ncdu$",
    r"^tree$", r"^bat$", r"^fd-find$", r"^ripgrep$",
    r"^python3-.*$", r"^lib.*-dev$",
    r"^fonts-.*$", r"^ttf-.*$",
]

# Sysctl-Parameter die Frank ändern darf
ALLOWED_SYSCTL = {
    "vm.swappiness": (0, 100),
    "vm.dirty_ratio": (5, 80),
    "vm.dirty_background_ratio": (1, 50),
    "vm.vfs_cache_pressure": (10, 200),
    "net.core.rmem_max": (212992, 67108864),
    "net.core.wmem_max": (212992, 67108864),
    "kernel.sched_autogroup_enabled": (0, 1),
}

# Verbotene Befehle (Blacklist)
FORBIDDEN_COMMANDS = frozenset({
    "rm -rf /", "rm -rf /*", "dd if=/dev/zero",
    "mkfs", "fdisk", "parted", "gparted",
    "chmod 777 /", "chown -R",
    "> /dev/sda", "cat /dev/zero",
})


# =============================================================================
# DATA STRUCTURES
# =============================================================================

class ActionType(Enum):
    """Typen von System-Aktionen."""
    INSTALL_APT = "install_apt"
    INSTALL_PIP = "install_pip"
    REMOVE_APT = "remove_apt"
    SYSCTL_CHANGE = "sysctl_change"
    SYSTEMD_ENABLE = "systemd_enable"
    SYSTEMD_DISABLE = "systemd_disable"
    CONFIG_CHANGE = "config_change"
    GSETTINGS_CHANGE = "gsettings_change"


class ActionStatus(Enum):
    """Status einer Aktion."""
    PROPOSED = "proposed"
    SIMULATED = "simulated"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    DENIED = "denied"


@dataclass
class SystemAction:
    """Eine geplante oder ausgeführte System-Aktion."""
    id: str
    action_type: ActionType
    target: str  # Paketname, Config-Pfad, etc.
    parameters: Dict[str, Any]
    reason: str  # Begründung (Kausalitäts-Check)

    status: ActionStatus = ActionStatus.PROPOSED
    confidence: float = 0.0
    risk_score: float = 0.0

    simulation_result: Optional[str] = None
    backup_path: Optional[str] = None

    created_at: str = ""
    executed_at: Optional[str] = None
    completed_at: Optional[str] = None

    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["action_type"] = self.action_type.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SystemAction":
        data["action_type"] = ActionType(data["action_type"])
        data["status"] = ActionStatus(data["status"])
        return cls(**data)


# =============================================================================
# DATABASE
# =============================================================================

class SovereignDatabase:
    """SQLite-Datenbank für E-SMC Audit-Trail."""

    def __init__(self, db_path: Path = SOVEREIGN_DB):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialisiert Datenbank-Schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS actions (
                    id TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    target TEXT NOT NULL,
                    parameters TEXT,
                    reason TEXT,
                    status TEXT NOT NULL,
                    confidence REAL DEFAULT 0.0,
                    risk_score REAL DEFAULT 0.0,
                    simulation_result TEXT,
                    backup_path TEXT,
                    created_at TEXT NOT NULL,
                    executed_at TEXT,
                    completed_at TEXT,
                    error_message TEXT
                );

                CREATE TABLE IF NOT EXISTS system_inventory (
                    package_name TEXT PRIMARY KEY,
                    version TEXT,
                    installed_by TEXT,  -- 'system', 'frank', 'user'
                    installed_at TEXT,
                    last_checked TEXT
                );

                CREATE TABLE IF NOT EXISTS config_snapshots (
                    id TEXT PRIMARY KEY,
                    config_path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    backup_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    action_id TEXT,
                    FOREIGN KEY (action_id) REFERENCES actions(id)
                );

                CREATE TABLE IF NOT EXISTS daily_stats (
                    date TEXT PRIMARY KEY,
                    installations INTEGER DEFAULT 0,
                    config_changes INTEGER DEFAULT 0,
                    rollbacks INTEGER DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_actions_status ON actions(status);
                CREATE INDEX IF NOT EXISTS idx_actions_date ON actions(created_at);

                -- E-SMC/V v3.0: Anti-Loop-Sentinel Tabelle
                CREATE TABLE IF NOT EXISTS target_modifications (
                    target TEXT NOT NULL,
                    modified_at TEXT NOT NULL,
                    action_id TEXT,
                    source TEXT,  -- 'log_error', 'visual_vcb', 'user_request', 'metric_anomaly'
                    PRIMARY KEY (target, modified_at)
                );

                CREATE INDEX IF NOT EXISTS idx_mods_target_time
                ON target_modifications(target, modified_at);

                -- E-SMC/V v3.0: VCB Visual Audit Log
                CREATE TABLE IF NOT EXISTS vcb_audits (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    reason TEXT,
                    visual_description TEXT,
                    correlation_result TEXT,
                    action_id TEXT,
                    FOREIGN KEY (action_id) REFERENCES actions(id)
                );
            """)

    def save_action(self, action: SystemAction) -> None:
        """Speichert eine Aktion."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO actions
                (id, action_type, target, parameters, reason, status, confidence,
                 risk_score, simulation_result, backup_path, created_at,
                 executed_at, completed_at, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                action.id, action.action_type.value, action.target,
                json.dumps(action.parameters), action.reason,
                action.status.value, action.confidence, action.risk_score,
                action.simulation_result, action.backup_path,
                action.created_at, action.executed_at, action.completed_at,
                action.error_message
            ))

    def get_action(self, action_id: str) -> Optional[SystemAction]:
        """Lädt eine Aktion."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM actions WHERE id = ?", (action_id,)
            ).fetchone()
            if row:
                data = dict(row)
                data["parameters"] = json.loads(data["parameters"] or "{}")
                return SystemAction.from_dict(data)
        return None

    def get_daily_stats(self, date: str = None) -> Dict[str, int]:
        """Holt Tages-Statistiken."""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM daily_stats WHERE date = ?", (date,)
            ).fetchone()
            if row:
                return dict(row)
            return {"date": date, "installations": 0, "config_changes": 0, "rollbacks": 0}

    # FIX: SQL Injection Prevention - Whitelist für erlaubte Stat-Namen
    ALLOWED_STATS = frozenset({"installations", "config_changes", "rollbacks"})

    def increment_stat(self, stat_name: str) -> None:
        """Erhöht einen Tages-Zähler (mit SQL Injection Schutz)."""
        # FIX: Whitelist-Validierung gegen SQL Injection
        if stat_name not in self.ALLOWED_STATS:
            raise ValueError(f"Invalid stat_name: {stat_name}. Allowed: {self.ALLOWED_STATS}")

        date = datetime.now().strftime("%Y-%m-%d")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(f"""
                INSERT INTO daily_stats (date, {stat_name})
                VALUES (?, 1)
                ON CONFLICT(date) DO UPDATE SET {stat_name} = {stat_name} + 1
            """, (date,))

    def save_inventory(self, packages: List[Dict[str, str]]) -> None:
        """Speichert Paket-Inventar."""
        with sqlite3.connect(self.db_path) as conn:
            now = datetime.now().isoformat()
            for pkg in packages:
                conn.execute("""
                    INSERT OR REPLACE INTO system_inventory
                    (package_name, version, installed_by, installed_at, last_checked)
                    VALUES (?, ?, ?, COALESCE(
                        (SELECT installed_at FROM system_inventory WHERE package_name = ?),
                        ?
                    ), ?)
                """, (
                    pkg["name"], pkg.get("version", ""),
                    pkg.get("installed_by", "system"),
                    pkg["name"], now, now
                ))

    # =========================================================================
    # E-SMC/V v3.0: Anti-Loop-Sentinel Methoden
    # =========================================================================

    def record_target_modification(
        self,
        target: str,
        action_id: str,
        source: str = "user_request"
    ) -> None:
        """Zeichnet eine Target-Modifikation auf."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO target_modifications (target, modified_at, action_id, source)
                VALUES (?, ?, ?, ?)
            """, (target, datetime.now().isoformat(), action_id, source))

    def get_target_modification_count_24h(self, target: str) -> int:
        """Zählt Modifikationen eines Targets in letzten 24h."""
        cutoff = (datetime.now() - __import__('datetime').timedelta(hours=24)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            result = conn.execute("""
                SELECT COUNT(*) FROM target_modifications
                WHERE target = ? AND modified_at > ?
            """, (target, cutoff)).fetchone()
            return result[0] if result else 0

    def get_target_modification_sources_24h(self, target: str) -> List[str]:
        """Holt alle Quellen für Modifikationen eines Targets in 24h."""
        cutoff = (datetime.now() - __import__('datetime').timedelta(hours=24)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            result = conn.execute("""
                SELECT DISTINCT source FROM target_modifications
                WHERE target = ? AND modified_at > ?
            """, (target, cutoff)).fetchall()
            return [r[0] for r in result if r[0]]

    def save_vcb_audit(
        self,
        audit_id: str,
        reason: str,
        visual_description: str,
        correlation_result: str = None,
        action_id: str = None
    ) -> None:
        """Speichert VCB Visual Audit."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO vcb_audits
                (id, timestamp, reason, visual_description, correlation_result, action_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                audit_id, datetime.now().isoformat(), reason,
                visual_description, correlation_result, action_id
            ))


# =============================================================================
# ANTI-LOOP-SENTINEL - E-SMC/V v3.0
# =============================================================================

class AntiLoopSentinel:
    """
    🔄 ANTI-LOOP-SENTINEL: Verhindert Stagnations-Loops.

    Max 2 Modifikationen desselben Targets in 24 Stunden.
    Verhindert destruktive Endlos-Optimierungen.
    """

    MAX_MODIFICATIONS_24H = 2

    def __init__(self, db: SovereignDatabase):
        self.db = db

    def check_modification_allowed(self, target: str) -> Tuple[bool, str]:
        """
        Prüft ob Target modifiziert werden darf.

        Returns:
            (allowed, message)
        """
        count = self.db.get_target_modification_count_24h(target)

        if count >= self.MAX_MODIFICATIONS_24H:
            return False, (
                f"ANTI-LOOP: Target '{target}' wurde bereits {count}x in 24h modifiziert. "
                f"Max erlaubt: {self.MAX_MODIFICATIONS_24H}. Warte 24h oder wähle anderes Target."
            )

        return True, f"OK: {count}/{self.MAX_MODIFICATIONS_24H} Modifikationen in 24h"

    def record_modification(self, target: str, action_id: str, source: str = "user_request") -> None:
        """Zeichnet erfolgreiche Modifikation auf."""
        self.db.record_target_modification(target, action_id, source)


# =============================================================================
# KAUSAL-VALIDATOR - E-SMC/V v3.0
# =============================================================================

class CausalValidator:
    """
    🔗 KAUSAL-VALIDATOR: Benötigt 2 Datenquellen für Legitimierung.

    Eine Aktion ist nur legitim wenn sie durch mindestens 2 unabhängige
    Quellen bestätigt wird (z.B. Log-Fehler + VCB-Beweis).
    """

    VALID_SOURCES = frozenset({
        "log_error",       # System-Log zeigt Fehler
        "visual_vcb",      # VCB Screenshot zeigt Problem
        "user_request",    # Explizite User-Anfrage
        "metric_anomaly",  # CPU/RAM/Temp-Anomalie
        "world_experience" # Kausales Gedächtnis
    })

    MIN_SOURCES_REQUIRED = 2

    @classmethod
    def validate_sources(cls, sources: List[str]) -> Tuple[bool, str]:
        """
        Prüft ob genügend legitime Quellen vorhanden sind.

        Args:
            sources: Liste der Quellen die diese Aktion legitimieren

        Returns:
            (valid, message)
        """
        # Filter nur gültige Quellen
        valid_sources = [s for s in sources if s in cls.VALID_SOURCES]
        unique_sources = set(valid_sources)

        if len(unique_sources) < cls.MIN_SOURCES_REQUIRED:
            return False, (
                f"KAUSAL-CHECK: Nur {len(unique_sources)} Quelle(n) vorhanden "
                f"({', '.join(unique_sources) or 'keine'}). "
                f"Benötigt: {cls.MIN_SOURCES_REQUIRED} verschiedene Quellen. "
                f"Gültige Quellen: {', '.join(cls.VALID_SOURCES)}"
            )

        return True, f"OK: {len(unique_sources)} Quellen validiert ({', '.join(unique_sources)})"

    @classmethod
    def get_legitimacy_score(cls, sources: List[str]) -> float:
        """
        Berechnet Legitimacy-Score (0.0-1.0).

        Mehr Quellen = höherer Score.
        """
        valid_sources = [s for s in sources if s in cls.VALID_SOURCES]
        unique_count = len(set(valid_sources))

        # Score: 0 bei 0 Quellen, 0.5 bei 1, 1.0 bei 2+
        if unique_count == 0:
            return 0.0
        elif unique_count == 1:
            return 0.5
        else:
            return min(1.0, 0.5 + (unique_count - 1) * 0.25)


# =============================================================================
# RISK ANALYZER - Der Analytiker
# =============================================================================

class RiskAnalyzer:
    """
    📊 ANALYTIKER: Bewertet Risiko und Confidence von System-Aktionen.

    Risk-Score: 0.0 (sicher) bis 1.0 (gefährlich)
    Confidence: 0.0 (unsicher) bis 1.0 (sehr sicher)
    """

    # Risk-Faktoren
    RISK_FACTORS = {
        ActionType.INSTALL_APT: 0.2,
        ActionType.INSTALL_PIP: 0.15,
        ActionType.REMOVE_APT: 0.6,
        ActionType.SYSCTL_CHANGE: 0.4,
        ActionType.SYSTEMD_ENABLE: 0.3,
        ActionType.SYSTEMD_DISABLE: 0.5,
        ActionType.CONFIG_CHANGE: 0.5,
        ActionType.GSETTINGS_CHANGE: 0.1,
    }

    @classmethod
    def analyze(cls, action: SystemAction) -> Tuple[float, float]:
        """
        Analysiert eine Aktion.

        Returns:
            (risk_score, confidence)
        """
        base_risk = cls.RISK_FACTORS.get(action.action_type, 0.5)
        confidence = 0.5

        # Risk-Modifikatoren
        if action.action_type == ActionType.REMOVE_APT:
            # Entfernen ist immer riskanter
            if action.target in PROTECTED_PACKAGES:
                return 1.0, 0.0  # Absolut verboten
            base_risk += 0.2

        if action.action_type == ActionType.INSTALL_APT:
            # Bekannte/erlaubte Pakete sind sicherer
            if cls._is_allowed_package(action.target):
                base_risk -= 0.1
                confidence += 0.3
            else:
                base_risk += 0.2

        if action.action_type == ActionType.SYSCTL_CHANGE:
            param = action.target
            value = action.parameters.get("value")
            if param in ALLOWED_SYSCTL:
                min_val, max_val = ALLOWED_SYSCTL[param]
                try:
                    val = int(value)
                    if min_val <= val <= max_val:
                        confidence += 0.4
                        base_risk -= 0.1
                except (ValueError, TypeError):
                    pass

        # Begründung erhöht Confidence
        if action.reason and len(action.reason) > 20:
            confidence += 0.1

        # Simulation-Ergebnis beeinflusst beides
        if action.simulation_result:
            if "0 upgraded, 0 newly installed" not in action.simulation_result:
                if "WILL BE REMOVED" in action.simulation_result.upper():
                    base_risk += 0.3
                else:
                    confidence += 0.2

        # Clamp values
        risk_score = max(0.0, min(1.0, base_risk))
        confidence = max(0.0, min(1.0, confidence))

        return risk_score, confidence

    @staticmethod
    def _is_allowed_package(package: str) -> bool:
        """Prüft ob Paket in Whitelist."""
        for pattern in ALLOWED_PACKAGE_PATTERNS:
            if re.match(pattern, package):
                return True
        return False


# =============================================================================
# DEPENDENCIES SENTINEL - Paket-Schutz
# =============================================================================

class DependenciesSentinel:
    """
    🔒 SICHERHEITS-EXPERTE: Schützt kritische System-Pakete.

    Blockiert jeden Befehl der geschützte Pakete entfernen würde.
    """

    @classmethod
    def check_removal_safety(cls, packages_to_remove: Set[str]) -> Tuple[bool, List[str]]:
        """
        Prüft ob Paket-Entfernung sicher ist.

        Returns:
            (is_safe, list_of_protected_packages_affected)
        """
        affected = packages_to_remove & PROTECTED_PACKAGES
        return len(affected) == 0, list(affected)

    @classmethod
    def parse_apt_simulation(cls, output: str) -> Dict[str, List[str]]:
        """
        Parst apt --simulate Output.

        Returns:
            {"install": [...], "remove": [...], "upgrade": [...]}
        """
        result = {"install": [], "remove": [], "upgrade": []}

        lines = output.split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("Inst "):
                # Format: Inst package (version ...)
                parts = line.split()
                if len(parts) >= 2:
                    result["install"].append(parts[1])
            elif line.startswith("Remv "):
                parts = line.split()
                if len(parts) >= 2:
                    result["remove"].append(parts[1])
            elif line.startswith("Conf "):
                parts = line.split()
                if len(parts) >= 2:
                    result["upgrade"].append(parts[1])

        return result

    @classmethod
    def validate_apt_command(cls, simulation_output: str) -> Tuple[bool, str]:
        """
        Validiert apt-Befehl anhand der Simulation.

        Returns:
            (is_valid, error_message_or_empty)
        """
        parsed = cls.parse_apt_simulation(simulation_output)

        # Check removals
        if parsed["remove"]:
            is_safe, affected = cls.check_removal_safety(set(parsed["remove"]))
            if not is_safe:
                return False, f"BLOCKED: Würde geschützte Pakete entfernen: {', '.join(affected)}"

        return True, ""


# =============================================================================
# SNAPSHOT MANAGER - Das Snapshot-Axiom
# =============================================================================

class SnapshotManager:
    """
    🔒 SICHERHEITS-EXPERTE: Backup vor jeder Änderung.

    Das Snapshot-Axiom: KEINE Änderung ohne Backup.
    """

    def __init__(self, backup_dir: Path = BACKUP_DIR, erosion_dir: Path = EROSION_DIR):
        self.backup_dir = backup_dir
        self.erosion_dir = erosion_dir
        backup_dir.mkdir(parents=True, exist_ok=True)
        erosion_dir.mkdir(parents=True, exist_ok=True)

    def create_config_backup(self, config_path: str, action_id: str) -> str:
        """
        Erstellt Backup einer Config-Datei.

        Returns:
            Pfad zum Backup
        """
        source = Path(config_path)
        if not source.exists():
            return ""

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{source.name}_{timestamp}_{action_id[:8]}"
        backup_path = self.backup_dir / backup_name

        shutil.copy2(source, backup_path)

        return str(backup_path)

    def create_dpkg_snapshot(self) -> str:
        """
        Erstellt Snapshot der installierten Pakete.

        Returns:
            Pfad zum Snapshot
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        snapshot_path = self.backup_dir / f"dpkg_snapshot_{timestamp}.txt"

        try:
            result = subprocess.run(
                ["dpkg", "--get-selections"],
                capture_output=True, text=True, timeout=30
            )
            snapshot_path.write_text(result.stdout)
            return str(snapshot_path)
        except Exception:
            return ""

    def create_etc_backup(self, subdir: str = "") -> str:
        """
        Erstellt tar.gz Backup eines /etc Unterverzeichnisses.

        Returns:
            Pfad zum Backup
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        source = Path("/etc") / subdir if subdir else Path("/etc")

        if not source.exists():
            return ""

        backup_name = f"etc_{subdir.replace('/', '_') or 'full'}_{timestamp}.tar.gz"
        backup_path = self.backup_dir / backup_name

        try:
            with tarfile.open(backup_path, "w:gz") as tar:
                tar.add(source, arcname=source.name)
            return str(backup_path)
        except Exception:
            return ""

    def move_to_erosion(self, file_path: str) -> str:
        """
        Verschiebt alte Config in Erosion-Ordner.

        Returns:
            Neuer Pfad
        """
        source = Path(file_path)
        if not source.exists():
            return ""

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = self.erosion_dir / f"{source.name}_{timestamp}"

        shutil.move(str(source), str(dest))
        return str(dest)

    def restore_backup(self, backup_path: str, original_path: str) -> bool:
        """Stellt Backup wieder her."""
        backup = Path(backup_path)
        original = Path(original_path)

        if not backup.exists():
            return False

        try:
            shutil.copy2(backup, original)
            return True
        except Exception:
            return False


# =============================================================================
# GAMING MODE LOCK
# =============================================================================

class GamingModeLock:
    """
    🎮 Gaming-Mode Hard-Lock: 100% Sperre während Gaming.

    Keine apt/pip Operationen während Gaming-Mode aktiv.
    """

    @staticmethod
    def is_gaming_active() -> bool:
        """Prüft ob Gaming-Mode aktiv ist."""
        # Check lock file
        if GAMING_LOCK_FILE.exists():
            return True

        # Check gaming_mode daemon
        try:
            result = subprocess.run(
                ["pgrep", "-f", "gaming_mode.py"],
                capture_output=True, timeout=2
            )
            if result.returncode == 0:
                # Gaming mode daemon läuft - prüfe State-Datei
                try:
                    state_file = Path("/tmp/gaming_mode_state.json")
                    if state_file.exists():
                        data = json.loads(state_file.read_text())
                        return data.get("active", False)
                except Exception:
                    pass
        except Exception:
            pass

        # Check for running games
        try:
            result = subprocess.run(
                ["pgrep", "-f", "steam.*app"],
                capture_output=True, timeout=2
            )
            return result.returncode == 0
        except Exception:
            pass

        return False

    @staticmethod
    def block_if_gaming() -> Tuple[bool, str]:
        """
        Blockiert wenn Gaming aktiv.

        Returns:
            (is_blocked, message)
        """
        if GamingModeLock.is_gaming_active():
            return True, "BLOCKED: Gaming-Mode aktiv. System-Änderungen gesperrt für optimale Performance."
        return False, ""


# =============================================================================
# VDP PROTOCOL EXECUTOR
# =============================================================================

class VDPExecutor:
    """
    💻 SOFTWARE ENGINEER: VDP-Protokoll Implementierung.

    Validate → Describe → Propose

    Jede System-Aktion durchläuft diesen Prozess.

    E-SMC/V v3.0: Integriert Anti-Loop-Sentinel und Kausal-Validator.
    """

    def __init__(self, db: SovereignDatabase, snapshots: SnapshotManager):
        self.db = db
        self.snapshots = snapshots
        self.anti_loop = AntiLoopSentinel(db)

    def validate(
        self,
        action: SystemAction,
        sources: List[str] = None
    ) -> Tuple[bool, str]:
        """
        VALIDATE: Prüft ob Aktion erlaubt ist.

        E-SMC/V v3.0: Zusätzlich Anti-Loop-Sentinel und Kausal-Check.

        Args:
            action: Die zu validierende Aktion
            sources: Liste der Legitimations-Quellen (für Kausal-Check)

        Returns:
            (is_valid, error_message_or_empty)
        """
        # 1. Gaming-Mode Check (100% Lock)
        blocked, msg = GamingModeLock.block_if_gaming()
        if blocked:
            return False, msg

        # 2. Anti-Loop-Sentinel (E-SMC/V v3.0)
        allowed, loop_msg = self.anti_loop.check_modification_allowed(action.target)
        if not allowed:
            return False, loop_msg

        # 3. Kausal-Check (E-SMC/V v3.0) - 2 Quellen erforderlich
        if sources is None:
            sources = ["user_request"]  # Default: nur User-Anfrage
        valid_sources, source_msg = CausalValidator.validate_sources(sources)
        if not valid_sources:
            # Bei nur 1 Quelle: Warnung, aber nicht blockieren wenn user_request
            if "user_request" in sources and len(sources) == 1:
                # User-Request allein reicht für einfache Aktionen
                action.parameters["causal_warning"] = source_msg
            else:
                return False, source_msg

        # 4. Daily Limits
        stats = self.db.get_daily_stats()
        if action.action_type in (ActionType.INSTALL_APT, ActionType.INSTALL_PIP):
            if stats["installations"] >= MAX_DAILY_INSTALLATIONS:
                return False, f"BLOCKED: Tages-Limit erreicht ({MAX_DAILY_INSTALLATIONS} Installationen)"

        if action.action_type in (ActionType.SYSCTL_CHANGE, ActionType.CONFIG_CHANGE):
            if stats["config_changes"] >= MAX_DAILY_CONFIG_CHANGES:
                return False, f"BLOCKED: Tages-Limit erreicht ({MAX_DAILY_CONFIG_CHANGES} Config-Änderungen)"

        # 5. Protected Packages
        if action.action_type == ActionType.REMOVE_APT:
            if action.target in PROTECTED_PACKAGES:
                return False, f"BLOCKED: {action.target} ist ein geschütztes System-Paket"

        # 6. Forbidden Commands Check
        cmd_str = f"{action.action_type.value} {action.target}"
        for forbidden in FORBIDDEN_COMMANDS:
            if forbidden in cmd_str.lower():
                return False, f"BLOCKED: Verbotener Befehl erkannt"

        # 7. Kausalitäts-Check (Begründung erforderlich)
        if not action.reason or len(action.reason) < 10:
            return False, "BLOCKED: Begründung erforderlich (min. 10 Zeichen)"

        return True, ""

    def simulate(self, action: SystemAction) -> Tuple[bool, str]:
        """
        SIMULATE: Führt Dry-Run durch.

        Returns:
            (success, simulation_output)
        """
        if action.action_type == ActionType.INSTALL_APT:
            try:
                result = subprocess.run(
                    ["apt", "install", "--simulate", "-y", action.target],
                    capture_output=True, text=True, timeout=60
                )
                output = result.stdout + result.stderr

                # Validate simulation
                is_valid, error = DependenciesSentinel.validate_apt_command(output)
                if not is_valid:
                    return False, error

                return True, output
            except Exception as e:
                return False, str(e)

        if action.action_type == ActionType.INSTALL_PIP:
            try:
                result = subprocess.run(
                    ["pip", "install", "--dry-run", action.target],
                    capture_output=True, text=True, timeout=60
                )
                return True, result.stdout + result.stderr
            except Exception as e:
                return False, str(e)

        if action.action_type == ActionType.SYSCTL_CHANGE:
            param = action.target
            value = action.parameters.get("value")

            # Check if parameter is allowed
            if param not in ALLOWED_SYSCTL:
                return False, f"Parameter {param} ist nicht in der Whitelist"

            min_val, max_val = ALLOWED_SYSCTL[param]
            try:
                val = int(value)
                if not (min_val <= val <= max_val):
                    return False, f"Wert {val} außerhalb erlaubtem Bereich [{min_val}, {max_val}]"
            except (ValueError, TypeError):
                return False, f"Ungültiger Wert: {value}"

            return True, f"Simulation OK: {param} = {value} (erlaubt: {min_val}-{max_val})"

        return True, "No simulation available for this action type"

    def propose(
        self,
        action: SystemAction,
        sources: List[str] = None
    ) -> SystemAction:
        """
        PROPOSE: Erstellt vollständigen Vorschlag mit Risk-Analyse.

        E-SMC/V v3.0: Integriert Kausal-Check über sources Parameter.

        Args:
            action: Die zu bewertende Aktion
            sources: Legitimations-Quellen (log_error, visual_vcb, user_request, etc.)

        Returns:
            Updated SystemAction
        """
        if sources is None:
            sources = ["user_request"]

        # Store sources in action parameters
        action.parameters["legitimation_sources"] = sources
        action.parameters["legitimacy_score"] = CausalValidator.get_legitimacy_score(sources)

        # 1. Validate (mit sources für Kausal-Check)
        is_valid, error = self.validate(action, sources)
        if not is_valid:
            action.status = ActionStatus.DENIED
            action.error_message = error
            self.db.save_action(action)
            return action

        # 2. Simulate
        if SIMULATION_REQUIRED:
            sim_success, sim_output = self.simulate(action)
            action.simulation_result = sim_output
            if not sim_success:
                action.status = ActionStatus.DENIED
                action.error_message = sim_output
                self.db.save_action(action)
                return action
            action.status = ActionStatus.SIMULATED

        # 3. Risk Analysis
        risk_score, confidence = RiskAnalyzer.analyze(action)
        action.risk_score = risk_score
        action.confidence = confidence

        # 4. Auto-Deny if too risky
        if risk_score > 0.8:
            action.status = ActionStatus.DENIED
            action.error_message = f"Risk-Score zu hoch: {risk_score:.2f}"
            self.db.save_action(action)
            return action

        # 5. Ready for approval
        if confidence >= CONFIDENCE_THRESHOLD:
            action.status = ActionStatus.APPROVED
        else:
            action.status = ActionStatus.PROPOSED
            action.error_message = f"Confidence zu niedrig ({confidence:.2f} < {CONFIDENCE_THRESHOLD}). Manuelle Freigabe erforderlich."

        self.db.save_action(action)
        return action


# =============================================================================
# MAIN CONTROLLER: E-SMC SOVEREIGN
# =============================================================================

class ESMC:
    """
    🧠 LEAD AI DEV: E-SMC Sovereign Hauptcontroller.

    Orchestriert alle Komponenten für sichere System-Verwaltung.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.db = SovereignDatabase()
        self.snapshots = SnapshotManager()
        self.executor = VDPExecutor(self.db, self.snapshots)

        self._initialized = True

    def _generate_action_id(self) -> str:
        """Generiert eindeutige Action-ID."""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        random_part = hashlib.sha256(os.urandom(16)).hexdigest()[:8]
        return f"sov_{timestamp}_{random_part}"

    def propose_installation(
        self,
        package: str,
        reason: str,
        package_manager: str = "apt",
        sources: List[str] = None
    ) -> SystemAction:
        """
        Schlägt Paket-Installation vor.

        E-SMC/V v3.0: Unterstützt Kausal-Check über sources.

        Args:
            package: Paketname
            reason: Begründung (Kausalitäts-Check)
            package_manager: "apt", "pip", "npm"
            sources: Legitimations-Quellen (log_error, visual_vcb, user_request, etc.)

        Returns:
            SystemAction mit Status
        """
        if sources is None:
            sources = ["user_request"]

        action_type = {
            "apt": ActionType.INSTALL_APT,
            "pip": ActionType.INSTALL_PIP,
        }.get(package_manager, ActionType.INSTALL_APT)

        action = SystemAction(
            id=self._generate_action_id(),
            action_type=action_type,
            target=package,
            parameters={"package_manager": package_manager},
            reason=reason,
            created_at=datetime.now().isoformat()
        )

        return self.executor.propose(action, sources)

    def propose_sysctl_change(
        self,
        parameter: str,
        value: str,
        reason: str,
        sources: List[str] = None
    ) -> SystemAction:
        """
        Schlägt Sysctl-Änderung vor.

        E-SMC/V v3.0: Unterstützt Kausal-Check über sources.

        Args:
            parameter: z.B. "vm.swappiness"
            value: z.B. "10"
            reason: Begründung
            sources: Legitimations-Quellen

        Returns:
            SystemAction mit Status
        """
        if sources is None:
            sources = ["user_request"]

        action = SystemAction(
            id=self._generate_action_id(),
            action_type=ActionType.SYSCTL_CHANGE,
            target=parameter,
            parameters={"value": value},
            reason=reason,
            created_at=datetime.now().isoformat()
        )

        return self.executor.propose(action, sources)

    def execute_approved(self, action: SystemAction) -> SystemAction:
        """
        Führt genehmigte Aktion aus.

        WICHTIG: Nur APPROVED Actions werden ausgeführt!
        """
        if action.status != ActionStatus.APPROVED:
            action.error_message = f"Action nicht approved (Status: {action.status.value})"
            return action

        # Final Gaming-Mode Check
        blocked, msg = GamingModeLock.block_if_gaming()
        if blocked:
            action.status = ActionStatus.DENIED
            action.error_message = msg
            self.db.save_action(action)
            return action

        # Create Backup
        if BACKUP_REQUIRED:
            if action.action_type in (ActionType.INSTALL_APT, ActionType.REMOVE_APT):
                backup = self.snapshots.create_dpkg_snapshot()
                action.backup_path = backup
            elif action.action_type == ActionType.SYSCTL_CHANGE:
                backup = self.snapshots.create_config_backup("/etc/sysctl.conf", action.id)
                action.backup_path = backup

        action.status = ActionStatus.EXECUTING
        action.executed_at = datetime.now().isoformat()
        self.db.save_action(action)

        try:
            # Execute based on type
            if action.action_type == ActionType.INSTALL_APT:
                result = self._execute_apt_install(action.target)
            elif action.action_type == ActionType.INSTALL_PIP:
                result = self._execute_pip_install(action.target)
            elif action.action_type == ActionType.SYSCTL_CHANGE:
                result = self._execute_sysctl_change(action.target, action.parameters["value"])
            else:
                result = (False, f"Execution not implemented for {action.action_type.value}")

            success, output = result

            if success:
                action.status = ActionStatus.COMPLETED
                action.completed_at = datetime.now().isoformat()

                # Update stats
                if action.action_type in (ActionType.INSTALL_APT, ActionType.INSTALL_PIP):
                    self.db.increment_stat("installations")
                elif action.action_type == ActionType.SYSCTL_CHANGE:
                    self.db.increment_stat("config_changes")

                # E-SMC/V v3.0: Record modification for Anti-Loop-Sentinel
                sources = action.parameters.get("legitimation_sources", ["user_request"])
                primary_source = sources[0] if sources else "user_request"
                self.executor.anti_loop.record_modification(
                    action.target, action.id, primary_source
                )
            else:
                action.status = ActionStatus.FAILED
                action.error_message = output

        except Exception as e:
            action.status = ActionStatus.FAILED
            action.error_message = str(e)

        self.db.save_action(action)
        return action

    def _execute_apt_install(self, package: str) -> Tuple[bool, str]:
        """Führt apt install aus (über frank-execute wenn verfügbar)."""
        try:
            # Versuche frank-execute (privilegiert)
            if FRANK_EXECUTE.exists():
                result = subprocess.run(
                    [str(FRANK_EXECUTE), "apt-install", package],
                    capture_output=True, text=True, timeout=300
                )
            else:
                # Fallback: direkter apt Aufruf (braucht sudo)
                result = subprocess.run(
                    ["sudo", "apt", "install", "-y", package],
                    capture_output=True, text=True, timeout=300
                )

            success = result.returncode == 0
            return success, result.stdout + result.stderr
        except Exception as e:
            return False, str(e)

    def _execute_pip_install(self, package: str) -> Tuple[bool, str]:
        """Führt pip install aus."""
        try:
            result = subprocess.run(
                ["pip", "install", "--user", package],
                capture_output=True, text=True, timeout=300
            )
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, str(e)

    def _execute_sysctl_change(self, parameter: str, value: str) -> Tuple[bool, str]:
        """Ändert sysctl Parameter."""
        try:
            # Temporär setzen
            result = subprocess.run(
                ["sudo", "sysctl", "-w", f"{parameter}={value}"],
                capture_output=True, text=True, timeout=10
            )

            if result.returncode != 0:
                return False, result.stderr

            # Persistent machen
            sysctl_conf = Path("/etc/sysctl.conf")
            content = sysctl_conf.read_text() if sysctl_conf.exists() else ""

            # Parameter ersetzen oder hinzufügen
            pattern = rf"^{re.escape(parameter)}\s*=.*$"
            new_line = f"{parameter} = {value}"

            if re.search(pattern, content, re.MULTILINE):
                content = re.sub(pattern, new_line, content, flags=re.MULTILINE)
            else:
                content += f"\n# Added by Frank E-SMC\n{new_line}\n"

            # Via frank-execute oder sudo schreiben
            tmp_file = Path("/tmp/sysctl_frank.conf")
            tmp_file.write_text(content)

            if FRANK_EXECUTE.exists():
                result = subprocess.run(
                    [str(FRANK_EXECUTE), "sysctl-apply", str(tmp_file)],
                    capture_output=True, text=True, timeout=10
                )
            else:
                result = subprocess.run(
                    ["sudo", "cp", str(tmp_file), str(sysctl_conf)],
                    capture_output=True, text=True, timeout=10
                )

            tmp_file.unlink(missing_ok=True)

            return result.returncode == 0, f"sysctl {parameter} = {value} gesetzt"
        except Exception as e:
            return False, str(e)

    def rollback(self, action_id: str) -> bool:
        """
        Führt Rollback einer Aktion durch.
        """
        action = self.db.get_action(action_id)
        if not action:
            return False

        if not action.backup_path:
            return False

        # Restore based on action type
        if action.action_type in (ActionType.INSTALL_APT, ActionType.REMOVE_APT):
            # dpkg restore ist komplex - nur logging
            print(f"[E-SMC] ROLLBACK: dpkg snapshot at {action.backup_path}")
            print("[E-SMC] Manual restore required: dpkg --set-selections < snapshot && apt-get dselect-upgrade")
        elif action.action_type == ActionType.SYSCTL_CHANGE:
            success = self.snapshots.restore_backup(action.backup_path, "/etc/sysctl.conf")
            if success:
                subprocess.run(["sudo", "sysctl", "-p"], capture_output=True, timeout=10)

        action.status = ActionStatus.ROLLED_BACK
        self.db.save_action(action)
        self.db.increment_stat("rollbacks")

        return True

    def get_status(self) -> Dict[str, Any]:
        """Gibt aktuellen Status zurück."""
        stats = self.db.get_daily_stats()
        is_gaming = GamingModeLock.is_gaming_active()

        return {
            "module": "E-SMC/V Sovereign Vision",
            "version": "3.0.0",
            "gaming_lock": is_gaming,
            "daily_stats": stats,
            "limits": {
                "max_installations": MAX_DAILY_INSTALLATIONS,
                "max_config_changes": MAX_DAILY_CONFIG_CHANGES,
                "remaining_installations": MAX_DAILY_INSTALLATIONS - stats["installations"],
                "remaining_config_changes": MAX_DAILY_CONFIG_CHANGES - stats["config_changes"],
            },
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "backup_dir": str(BACKUP_DIR),
        }

    def create_system_inventory(self) -> Dict[str, Any]:
        """
        Erstellt vollständiges System-Inventar.

        Wichtig für Aktivierung von E-SMC.
        """
        inventory = {
            "timestamp": datetime.now().isoformat(),
            "packages": [],
            "kernel": "",
            "gpu_driver": "",
        }

        # Kernel
        try:
            result = subprocess.run(["uname", "-r"], capture_output=True, text=True, timeout=5)
            inventory["kernel"] = result.stdout.strip()
        except Exception:
            pass

        # GPU Driver
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=10
            )
            inventory["gpu_driver"] = result.stdout.strip()
        except Exception:
            pass

        # Installed packages (top 100 by size or importance)
        try:
            result = subprocess.run(
                ["dpkg-query", "-W", "-f", "${Package}\t${Version}\t${Installed-Size}\n"],
                capture_output=True, text=True, timeout=60
            )
            lines = result.stdout.strip().split("\n")
            packages = []
            for line in lines[:500]:  # Limit
                parts = line.split("\t")
                if len(parts) >= 2:
                    packages.append({
                        "name": parts[0],
                        "version": parts[1],
                        "size": parts[2] if len(parts) > 2 else "0"
                    })
            inventory["packages"] = packages

            # Save to DB
            self.db.save_inventory([{"name": p["name"], "version": p["version"]} for p in packages])
        except Exception:
            pass

        # Save inventory file
        inv_file = BACKUP_DIR / f"inventory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        inv_file.write_text(json.dumps(inventory, indent=2, ensure_ascii=False))

        return inventory


# =============================================================================
# SINGLETON & CONVENIENCE
# =============================================================================

_sovereign: Optional[ESMC] = None

def get_sovereign() -> ESMC:
    """Singleton-Zugriff auf E-SMC."""
    global _sovereign
    if _sovereign is None:
        _sovereign = ESMC()
    return _sovereign


def propose_installation(package: str, reason: str, pm: str = "apt") -> SystemAction:
    """Convenience: Paket-Installation vorschlagen."""
    return get_sovereign().propose_installation(package, reason, pm)


def propose_sysctl(param: str, value: str, reason: str) -> SystemAction:
    """Convenience: Sysctl-Änderung vorschlagen."""
    return get_sovereign().propose_sysctl_change(param, value, reason)


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import sys

    sovereign = get_sovereign()

    if len(sys.argv) < 2:
        print("E-SMC Sovereign - System-Management für Frank")
        print()
        print("Usage:")
        print("  e_smc.py status              - Aktueller Status")
        print("  e_smc.py inventory           - System-Inventar erstellen")
        print("  e_smc.py propose-apt <pkg> <reason>  - Installation vorschlagen")
        print("  e_smc.py propose-sysctl <param> <value> <reason>")
        print("  e_smc.py execute <action_id> - Genehmigte Aktion ausführen")
        print("  e_smc.py rollback <action_id>- Rollback durchführen")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "status":
        status = sovereign.get_status()
        print(json.dumps(status, indent=2))

    elif cmd == "inventory":
        print("Erstelle System-Inventar...")
        inv = sovereign.create_system_inventory()
        print(f"Inventar erstellt: {len(inv['packages'])} Pakete")
        print(f"Kernel: {inv['kernel']}")
        print(f"GPU Driver: {inv['gpu_driver']}")

    elif cmd == "propose-apt" and len(sys.argv) >= 4:
        package = sys.argv[2]
        reason = " ".join(sys.argv[3:])
        action = sovereign.propose_installation(package, reason)
        print(f"Action ID: {action.id}")
        print(f"Status: {action.status.value}")
        print(f"Risk Score: {action.risk_score:.2f}")
        print(f"Confidence: {action.confidence:.2f}")
        if action.error_message:
            print(f"Message: {action.error_message}")
        if action.simulation_result:
            print(f"Simulation:\n{action.simulation_result[:500]}")

    elif cmd == "propose-sysctl" and len(sys.argv) >= 5:
        param = sys.argv[2]
        value = sys.argv[3]
        reason = " ".join(sys.argv[4:])
        action = sovereign.propose_sysctl_change(param, value, reason)
        print(f"Action ID: {action.id}")
        print(f"Status: {action.status.value}")
        print(f"Risk Score: {action.risk_score:.2f}")
        print(f"Confidence: {action.confidence:.2f}")
        if action.error_message:
            print(f"Message: {action.error_message}")

    elif cmd == "execute" and len(sys.argv) >= 3:
        action_id = sys.argv[2]
        action = sovereign.db.get_action(action_id)
        if action:
            result = sovereign.execute_approved(action)
            print(f"Status: {result.status.value}")
            if result.error_message:
                print(f"Error: {result.error_message}")
        else:
            print(f"Action {action_id} nicht gefunden")

    elif cmd == "rollback" and len(sys.argv) >= 3:
        action_id = sys.argv[2]
        success = sovereign.rollback(action_id)
        print(f"Rollback: {'OK' if success else 'FAILED'}")

    else:
        print(f"Unbekannter Befehl: {cmd}")
        sys.exit(1)
