#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E-SMC/V Sovereign HUD Logger
============================

Transparentes Logging aller Sovereign-Aktionen für Frank-HUD Anzeige.
Jede autonome Handlung wird mit maximaler Transparenz geloggt.

Format:
    [ VISION AUDIT ] INPUT: Log-Anomaly @ 11:45 | OUTPUT: "UI-Freeze in Terminal"
    [ SOVEREIGN ACTION ] TASK: Installing htop | STATUS: SUCCESS
    FILE-SHIFT: config.conf -> /aicore/delete/config.conf_old

Usage:
    from ext.sovereign.hud_logger import get_hud_logger

    logger = get_hud_logger()
    logger.log_vision_audit("CPU-Anomalie erkannt", "Desktop zeigt hängendes Terminal")
    logger.log_sovereign_action("Installing htop", "SUCCESS")
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

# =============================================================================
# CONFIGURATION
# =============================================================================

HUD_LOG_FILE = Path("/tmp/frank_sovereign_hud.log")
HUD_JSON_FILE = Path("/tmp/frank_sovereign_hud.json")
MAX_LOG_ENTRIES = 100  # Letzte 100 Einträge behalten


# =============================================================================
# HUD LOGGER
# =============================================================================

class SovereignHUDLogger:
    """
    🎨 HUD Event Logger für transparente Sovereign-Aktionen.

    Loggt alle Aktionen in zwei Formaten:
    1. Text-Log für Terminal-Anzeige (/tmp/frank_sovereign_hud.log)
    2. JSON für strukturierte Verarbeitung (/tmp/frank_sovereign_hud.json)
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

        self.log_file = HUD_LOG_FILE
        self.json_file = HUD_JSON_FILE
        self.entries: list = []

        # Load existing entries
        self._load_entries()

        self._initialized = True

    def _load_entries(self) -> None:
        """Lädt bestehende Einträge aus JSON."""
        try:
            if self.json_file.exists():
                data = json.loads(self.json_file.read_text())
                self.entries = data.get("entries", [])[-MAX_LOG_ENTRIES:]
        except Exception:
            self.entries = []

    def _save_entries(self) -> None:
        """Speichert Einträge in JSON."""
        try:
            # Trim to max entries
            self.entries = self.entries[-MAX_LOG_ENTRIES:]
            data = {
                "last_update": datetime.now().isoformat(),
                "entry_count": len(self.entries),
                "entries": self.entries
            }
            self.json_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception:
            pass

    def _append_log(self, line: str) -> None:
        """Fügt Zeile zum Text-Log hinzu."""
        try:
            with open(self.log_file, "a") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def log_vision_audit(
        self,
        input_desc: str,
        output_desc: str,
        timestamp: str = None
    ) -> None:
        """
        Loggt einen Visual Audit Vorgang.

        Format: [ VISION AUDIT ] INPUT: ... | OUTPUT: ...

        Args:
            input_desc: Was wurde beobachtet (z.B. "Log-Anomaly @ 11:45")
            output_desc: Was wurde erkannt (z.B. "UI-Freeze in Terminal")
            timestamp: Optional, sonst jetzt
        """
        ts = timestamp or datetime.now().strftime("%H:%M:%S")

        entry = {
            "type": "VISION_AUDIT",
            "timestamp": ts,
            "input": input_desc,
            "output": output_desc,
            "full_timestamp": datetime.now().isoformat()
        }
        self.entries.append(entry)

        line = f"[ VISION AUDIT ] {ts} | INPUT: {input_desc} | OUTPUT: \"{output_desc}\""
        self._append_log(line)
        self._save_entries()

    def log_sovereign_action(
        self,
        task: str,
        status: str,
        file_shift: str = None,
        details: Dict[str, Any] = None
    ) -> None:
        """
        Loggt eine Sovereign-Aktion.

        Format:
            [ SOVEREIGN ACTION ] TASK: ... | STATUS: ...
            FILE-SHIFT: ... -> ... (optional)

        Args:
            task: Was wurde getan (z.B. "Installing htop")
            status: Ergebnis (SUCCESS, FAILED, DENIED)
            file_shift: Optional, Datei-Verschiebung (z.B. "config.conf -> /delete/config.conf_old")
            details: Zusätzliche Details
        """
        ts = datetime.now().strftime("%H:%M:%S")

        entry = {
            "type": "SOVEREIGN_ACTION",
            "timestamp": ts,
            "task": task,
            "status": status,
            "file_shift": file_shift,
            "details": details or {},
            "full_timestamp": datetime.now().isoformat()
        }
        self.entries.append(entry)

        line = f"[ SOVEREIGN ACTION ] {ts} | TASK: {task} | STATUS: {status}"
        self._append_log(line)

        if file_shift:
            shift_line = f"FILE-SHIFT: {file_shift}"
            self._append_log(shift_line)
            entry["file_shift_logged"] = True

        self._save_entries()

    def log_anti_loop_block(
        self,
        target: str,
        modification_count: int
    ) -> None:
        """
        Loggt einen Anti-Loop-Block.

        Args:
            target: Das blockierte Target
            modification_count: Anzahl bisheriger Modifikationen
        """
        ts = datetime.now().strftime("%H:%M:%S")

        entry = {
            "type": "ANTI_LOOP_BLOCK",
            "timestamp": ts,
            "target": target,
            "modification_count": modification_count,
            "full_timestamp": datetime.now().isoformat()
        }
        self.entries.append(entry)

        line = f"[ ANTI-LOOP ] {ts} | BLOCKED: {target} ({modification_count}x in 24h)"
        self._append_log(line)
        self._save_entries()

    def log_kausal_check(
        self,
        sources: list,
        valid: bool,
        action_target: str = None
    ) -> None:
        """
        Loggt einen Kausal-Check.

        Args:
            sources: Die verwendeten Quellen
            valid: Ob genug Quellen vorhanden waren
            action_target: Optional, das Target der Aktion
        """
        ts = datetime.now().strftime("%H:%M:%S")

        entry = {
            "type": "KAUSAL_CHECK",
            "timestamp": ts,
            "sources": sources,
            "valid": valid,
            "action_target": action_target,
            "full_timestamp": datetime.now().isoformat()
        }
        self.entries.append(entry)

        status = "OK" if valid else "INSUFFICIENT"
        line = f"[ KAUSAL-CHECK ] {ts} | SOURCES: {', '.join(sources)} | STATUS: {status}"
        self._append_log(line)
        self._save_entries()

    def log_gaming_lock(self, action_blocked: str) -> None:
        """
        Loggt eine Gaming-Mode Blockierung.

        Args:
            action_blocked: Die blockierte Aktion
        """
        ts = datetime.now().strftime("%H:%M:%S")

        entry = {
            "type": "GAMING_LOCK",
            "timestamp": ts,
            "action_blocked": action_blocked,
            "full_timestamp": datetime.now().isoformat()
        }
        self.entries.append(entry)

        line = f"[ GAMING-LOCK ] {ts} | BLOCKED: {action_blocked} | Reason: Gaming-Mode aktiv"
        self._append_log(line)
        self._save_entries()

    def get_recent_entries(self, count: int = 10) -> list:
        """Holt die letzten N Einträge."""
        return self.entries[-count:]

    def get_entries_by_type(self, entry_type: str) -> list:
        """Filtert Einträge nach Typ."""
        return [e for e in self.entries if e.get("type") == entry_type]

    def clear_log(self) -> None:
        """Löscht das Log (für Tests)."""
        self.entries = []
        try:
            if self.log_file.exists():
                self.log_file.unlink()
            if self.json_file.exists():
                self.json_file.unlink()
        except Exception:
            pass


# =============================================================================
# SINGLETON ACCESS
# =============================================================================

_hud_logger: Optional[SovereignHUDLogger] = None


def get_hud_logger() -> SovereignHUDLogger:
    """Singleton-Zugriff auf HUD Logger."""
    global _hud_logger
    if _hud_logger is None:
        _hud_logger = SovereignHUDLogger()
    return _hud_logger


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import sys

    logger = get_hud_logger()

    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "test":
            print("Testing HUD Logger...")
            logger.log_vision_audit("CPU-Spike @ 14:30", "Browser-Tab zeigt Memory-Leak")
            logger.log_sovereign_action("Installing htop", "SUCCESS")
            logger.log_sovereign_action(
                "Modifying vm.swappiness",
                "SUCCESS",
                file_shift="sysctl.conf -> /aicore/delete/sysctl.conf_20260129"
            )
            logger.log_anti_loop_block("vm.swappiness", 2)
            logger.log_kausal_check(["log_error", "visual_vcb"], True, "htop")
            logger.log_gaming_lock("apt install btop")
            print(f"Log written to: {HUD_LOG_FILE}")
            print(f"JSON written to: {HUD_JSON_FILE}")

        elif cmd == "show":
            count = int(sys.argv[2]) if len(sys.argv) > 2 else 10
            entries = logger.get_recent_entries(count)
            print(f"Last {len(entries)} entries:")
            for e in entries:
                print(f"  [{e['type']}] {e['timestamp']}: {e.get('task') or e.get('input', '')}")

        elif cmd == "clear":
            logger.clear_log()
            print("Log cleared.")

        elif cmd == "cat":
            if HUD_LOG_FILE.exists():
                print(HUD_LOG_FILE.read_text())
            else:
                print("No log file yet.")

        else:
            print(f"Unknown command: {cmd}")
            print("Usage: hud_logger.py [test|show [N]|clear|cat]")
    else:
        print("E-SMC/V Sovereign HUD Logger")
        print(f"Log file: {HUD_LOG_FILE}")
        print(f"JSON file: {HUD_JSON_FILE}")
        print()
        print("Commands:")
        print("  test    - Generate test entries")
        print("  show N  - Show last N entries")
        print("  clear   - Clear log")
        print("  cat     - Display log file")
