#!/usr/bin/env python3
"""
Self-Diagnosis Daemon v1.0
==========================
Überwacht Log-Dateien auf wiederkehrende Fehler, analysiert betroffenen
Quellcode und erstellt Genesis-Proposals mit konkreten Fix-Vorschlägen.

Das Genesis-Popup im Overlay zeigt die Proposals sofort an.

Erkannte Patterns:
  - NameError     → Ähnlichste Variable im Scope finden
  - AttributeError → None-Guard vorschlagen
  - ImportError   → Import-Statement vorschlagen
  - TypeError     → Signatur-Mismatch erkennen
  - KeyError      → .get() mit Default vorschlagen
"""

import ast
import difflib
import json
import logging
import os
import re
import signal
import sys
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
try:
    from config.paths import AICORE_ROOT, AICORE_LOG, TRAINING_LOG_DIR
except ImportError:
    AICORE_ROOT = Path("/home/ai-core-node/aicore/opt/aicore")
    AICORE_LOG = Path("/home/ai-core-node/.local/share/frank/logs")
    TRAINING_LOG_DIR = AICORE_LOG / "training"
sys.path.insert(0, str(AICORE_ROOT))

LOG_DIR = AICORE_LOG
DIAGNOSIS_LOG = LOG_DIR / "self_diagnosis.log"
PROPOSALS_FILE = TRAINING_LOG_DIR / "proposals.jsonl"

# Log-Dateien die überwacht werden
WATCHED_LOGS = [
    Path("/tmp/overlay.log"),
    LOG_DIR / "core.log",
]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(DIAGNOSIS_LOG, mode="a", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
LOG = logging.getLogger("self_diagnosis")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CHECK_INTERVAL_S = 60        # Alle 60 Sekunden Logs prüfen
ERROR_THRESHOLD = 3          # Ab 3 gleichen Fehlern → Proposal
WINDOW_SECONDS = 600         # 10-Minuten-Fenster für Fehler-Gruppierung
MAX_PROPOSALS_PER_HOUR = 5   # Rate-Limit für Proposals


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class ErrorEntry:
    """Ein einzelner Fehler-Eintrag aus dem Log."""
    timestamp: str
    level: str              # ERROR, CRITICAL
    message: str            # Die Fehlermeldung
    exception_type: str     # z.B. NameError, AttributeError
    exception_msg: str      # Die konkrete Exception-Nachricht
    source_file: str        # Datei aus Traceback
    line_number: int        # Zeile aus Traceback
    function_name: str      # Funktion aus Traceback
    full_traceback: str     # Kompletter Traceback


@dataclass
class ErrorGroup:
    """Gruppierung gleicher Fehler."""
    key: Tuple[str, str, str]   # (exception_type, source_file, function_name)
    entries: List[ErrorEntry] = field(default_factory=list)
    first_seen: float = 0.0
    last_seen: float = 0.0
    proposed: bool = False      # Wurde bereits ein Proposal erstellt?
    proposal_id: Optional[int] = None

    @property
    def count(self) -> int:
        return len(self.entries)


@dataclass
class DiagnosisResult:
    """Ergebnis einer Fehler-Analyse."""
    error_type: str
    source_file: str
    line_number: int
    function_name: str
    description: str        # Beschreibung des Problems
    fix_suggestion: str     # Vorgeschlagener Fix (Text)
    fix_code: Optional[str] # Konkreter Code-Fix
    confidence: float       # 0.0-1.0
    risk: float             # 0.0-1.0
    occurrence_count: int
    traceback: str


# ---------------------------------------------------------------------------
# Error parsing
# ---------------------------------------------------------------------------
# Regex für Log-Zeilen: [2026-02-06 22:41:33,123] ERROR: ...
_LOG_LINE_RE = re.compile(
    r"\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[^\]]*)\]\s+(ERROR|CRITICAL)[\s:]+(.+)"
)

# Traceback-Extraktion: File "...", line X, in func
_TRACEBACK_FILE_RE = re.compile(
    r'File\s+"([^"]+)",\s+line\s+(\d+),\s+in\s+(\S+)'
)

# Exception-Zeile: ExceptionType: message
_EXCEPTION_RE = re.compile(
    r"^(\w+(?:Error|Exception|Warning|Interrupt))\s*:\s*(.+)"
)


def parse_error_entries(lines: List[str]) -> List[ErrorEntry]:
    """Parse Log-Zeilen in ErrorEntry-Objekte."""
    entries = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _LOG_LINE_RE.search(line)
        if not m:
            i += 1
            continue

        timestamp = m.group(1)
        level = m.group(2)
        message = m.group(3)

        # Sammle Traceback-Zeilen (folgende Zeilen die mit Whitespace beginnen
        # oder "Traceback" / "File " / Exception-Typ enthalten)
        tb_lines = [line]
        j = i + 1
        while j < len(lines):
            next_line = lines[j]
            if (next_line.startswith("  ") or
                next_line.startswith("Traceback") or
                next_line.startswith("File ") or
                _EXCEPTION_RE.match(next_line)):
                tb_lines.append(next_line)
                j += 1
            else:
                break

        full_tb = "\n".join(tb_lines)

        # Extrahiere Source-Info aus Traceback (letztes File-Match = Fehlerquelle)
        file_matches = _TRACEBACK_FILE_RE.findall(full_tb)
        source_file = ""
        line_number = 0
        function_name = ""
        if file_matches:
            last = file_matches[-1]
            source_file = last[0]
            line_number = int(last[1])
            function_name = last[2]

        # Extrahiere Exception-Typ
        exception_type = ""
        exception_msg = ""
        for tb_line in reversed(tb_lines):
            exc_m = _EXCEPTION_RE.match(tb_line.strip())
            if exc_m:
                exception_type = exc_m.group(1)
                exception_msg = exc_m.group(2)
                break

        # Wenn kein expliziter Exception-Typ gefunden, aus Message extrahieren
        if not exception_type:
            exc_m = _EXCEPTION_RE.search(message)
            if exc_m:
                exception_type = exc_m.group(1)
                exception_msg = exc_m.group(2)
            else:
                exception_type = "UnknownError"
                exception_msg = message

        if source_file:  # Nur Fehler mit identifizierbarer Quelle
            entries.append(ErrorEntry(
                timestamp=timestamp,
                level=level,
                message=message,
                exception_type=exception_type,
                exception_msg=exception_msg,
                source_file=source_file,
                line_number=line_number,
                function_name=function_name,
                full_traceback=full_tb,
            ))

        i = j  # Springe über Traceback-Zeilen

    return entries


# ---------------------------------------------------------------------------
# Code analysis & fix suggestion
# ---------------------------------------------------------------------------

def _read_source_context(filepath: str, line_num: int, context: int = 15) -> str:
    """Lies Quellcode um die Fehlerzeile herum."""
    try:
        path = Path(filepath)
        if not path.exists():
            return ""
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        start = max(0, line_num - context)
        end = min(len(lines), line_num + context)
        numbered = [f"{i+1:4d}| {lines[i]}" for i in range(start, end)]
        return "\n".join(numbered)
    except Exception:
        return ""


def _find_similar_names(filepath: str, wrong_name: str) -> List[str]:
    """Finde ähnliche Variablennamen im gleichen File via AST."""
    try:
        source = Path(filepath).read_text(encoding="utf-8")
        tree = ast.parse(source)
    except Exception:
        return []

    names: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.FunctionDef):
            names.add(node.name)
            for arg in node.args.args:
                names.add(arg.arg)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)

    # Finde ähnlichste Namen
    matches = difflib.get_close_matches(wrong_name, list(names), n=3, cutoff=0.5)
    return matches


def analyze_error(group: ErrorGroup) -> Optional[DiagnosisResult]:
    """Analysiere eine Fehlergruppe und erstelle Fix-Vorschlag."""
    entry = group.entries[-1]  # Neuester Eintrag
    exc_type = entry.exception_type
    exc_msg = entry.exception_msg
    src = entry.source_file
    line = entry.line_number
    func = entry.function_name

    source_context = _read_source_context(src, line)

    # ---- NameError: name 'X' is not defined ----
    m = re.match(r"name '(\w+)' is not defined", exc_msg)
    if exc_type == "NameError" and m:
        wrong_name = m.group(1)
        similar = _find_similar_names(src, wrong_name)
        if similar:
            best = similar[0]
            return DiagnosisResult(
                error_type=exc_type,
                source_file=src,
                line_number=line,
                function_name=func,
                description=(
                    f"NameError in {Path(src).name}:{line} ({func}): "
                    f"Variable '{wrong_name}' existiert nicht. "
                    f"Wahrscheinlich Tippfehler — ähnliche Namen: {similar}"
                ),
                fix_suggestion=f"Ersetze '{wrong_name}' durch '{best}' in Zeile {line}",
                fix_code=f"# In {Path(src).name}, Zeile {line}:\n# Ersetze: {wrong_name}\n# Durch:   {best}",
                confidence=0.9,
                risk=0.1,
                occurrence_count=group.count,
                traceback=entry.full_traceback,
            )
        else:
            return DiagnosisResult(
                error_type=exc_type,
                source_file=src,
                line_number=line,
                function_name=func,
                description=(
                    f"NameError in {Path(src).name}:{line} ({func}): "
                    f"Variable '{wrong_name}' nicht definiert. Kein ähnlicher Name gefunden."
                ),
                fix_suggestion=f"Prüfe ob '{wrong_name}' definiert wurde oder importiert werden muss",
                fix_code=None,
                confidence=0.6,
                risk=0.2,
                occurrence_count=group.count,
                traceback=entry.full_traceback,
            )

    # ---- AttributeError: 'NoneType' has no attribute 'X' ----
    m = re.match(r"'NoneType' has no attribute '(\w+)'", exc_msg)
    if exc_type == "AttributeError" and m:
        attr = m.group(1)
        return DiagnosisResult(
            error_type=exc_type,
            source_file=src,
            line_number=line,
            function_name=func,
            description=(
                f"AttributeError in {Path(src).name}:{line} ({func}): "
                f"Zugriff auf '.{attr}' auf None-Objekt. Fehlende None-Prüfung."
            ),
            fix_suggestion=f"Füge 'if obj is not None:' Guard vor Zeile {line} ein",
            fix_code=f"# In {Path(src).name}, Zeile {line}:\n# Füge hinzu: if variable is not None:",
            confidence=0.85,
            risk=0.1,
            occurrence_count=group.count,
            traceback=entry.full_traceback,
        )

    # ---- ImportError: No module named 'X' ----
    m = re.match(r"No module named '(\S+)'", exc_msg)
    if exc_type in ("ImportError", "ModuleNotFoundError") and m:
        module = m.group(1)
        return DiagnosisResult(
            error_type=exc_type,
            source_file=src,
            line_number=line,
            function_name=func,
            description=(
                f"ImportError in {Path(src).name}:{line}: "
                f"Modul '{module}' nicht gefunden. Entweder nicht installiert "
                f"oder falscher Modulname."
            ),
            fix_suggestion=f"Prüfe: pip install {module} oder korrigiere den Import-Pfad",
            fix_code=f"# pip install {module}\n# Oder prüfe ob der Modulname korrekt ist",
            confidence=0.7,
            risk=0.15,
            occurrence_count=group.count,
            traceback=entry.full_traceback,
        )

    # ---- TypeError: unexpected keyword argument ----
    m = re.match(r".+got an unexpected keyword argument '(\w+)'", exc_msg)
    if exc_type == "TypeError" and m:
        kwarg = m.group(1)
        return DiagnosisResult(
            error_type=exc_type,
            source_file=src,
            line_number=line,
            function_name=func,
            description=(
                f"TypeError in {Path(src).name}:{line} ({func}): "
                f"Unerwartetes Keyword-Argument '{kwarg}'. "
                f"Funktionssignatur stimmt nicht überein."
            ),
            fix_suggestion=f"Prüfe die Signatur der aufgerufenen Funktion — '{kwarg}' entfernen oder umbenennen",
            fix_code=f"# Prüfe Funktionssignatur an der Aufrufstelle\n# Entferne oder korrigiere: {kwarg}=...",
            confidence=0.8,
            risk=0.1,
            occurrence_count=group.count,
            traceback=entry.full_traceback,
        )

    # ---- KeyError ----
    m = re.match(r"'?(\w+)'?", exc_msg)
    if exc_type == "KeyError" and m:
        key = m.group(1)
        return DiagnosisResult(
            error_type=exc_type,
            source_file=src,
            line_number=line,
            function_name=func,
            description=(
                f"KeyError in {Path(src).name}:{line} ({func}): "
                f"Key '{key}' nicht im Dictionary. Fehlender .get()-Aufruf."
            ),
            fix_suggestion=f"Ersetze dict['{key}'] durch dict.get('{key}', default_value)",
            fix_code=f"# In {Path(src).name}, Zeile {line}:\n# Ersetze: data['{key}']\n# Durch:   data.get('{key}', None)",
            confidence=0.85,
            risk=0.1,
            occurrence_count=group.count,
            traceback=entry.full_traceback,
        )

    # ---- Generischer Fehler ----
    return DiagnosisResult(
        error_type=exc_type,
        source_file=src,
        line_number=line,
        function_name=func,
        description=(
            f"{exc_type} in {Path(src).name}:{line} ({func}): {exc_msg}"
        ),
        fix_suggestion="Manuelle Analyse erforderlich",
        fix_code=None,
        confidence=0.5,
        risk=0.2,
        occurrence_count=group.count,
        traceback=entry.full_traceback,
    )


# ---------------------------------------------------------------------------
# Genesis Proposal Integration
# ---------------------------------------------------------------------------

def _get_next_proposal_id() -> int:
    """Nächste freie Proposal-ID aus JSONL lesen."""
    max_id = 0
    if PROPOSALS_FILE.exists():
        try:
            with open(PROPOSALS_FILE) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        p = json.loads(line)
                        pid = p.get("id", 0)
                        if isinstance(pid, int) and pid > max_id:
                            max_id = pid
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass
    return max_id + 1


def create_proposal(diagnosis: DiagnosisResult) -> Optional[int]:
    """Erstelle Genesis-Proposal aus Diagnose-Ergebnis. Gibt Proposal-ID zurück."""
    try:
        PROPOSALS_FILE.parent.mkdir(parents=True, exist_ok=True)

        pid = _get_next_proposal_id()

        # Beschreibung mit Kontext für das Popup
        desc_parts = [
            f"🔍 AUTO-DIAGNOSE: {diagnosis.error_type}",
            f"",
            f"Datei: {diagnosis.source_file}:{diagnosis.line_number}",
            f"Funktion: {diagnosis.function_name}",
            f"Auftreten: {diagnosis.occurrence_count}x",
            f"",
            f"Problem: {diagnosis.description}",
            f"",
            f"Fix: {diagnosis.fix_suggestion}",
        ]
        if diagnosis.fix_code:
            desc_parts.extend(["", diagnosis.fix_code])

        proposal = {
            "id": pid,
            "timestamp": datetime.now().isoformat(),
            "category": "bugfix",
            "description": "\n".join(desc_parts)[:500],
            "confidence": diagnosis.confidence,
            "risk": diagnosis.risk,
            "causal_reasoning": (
                f"Fehler {diagnosis.error_type} trat {diagnosis.occurrence_count}x auf "
                f"in {diagnosis.source_file}:{diagnosis.line_number} ({diagnosis.function_name}). "
                f"Traceback: {diagnosis.traceback[:300]}"
            ),
            "code_snippet": diagnosis.fix_code,
            "status": "pending",
            "validator": "self_diagnosis",
            "validation_reason": f"Auto-detected recurring error ({diagnosis.occurrence_count}x)",
            "implementation_result": None,
            "tool_file": None,
            "tool_name": None,
            "syntax_valid": False,
            "execution_success": False,
            "test_output": None,
        }

        with open(PROPOSALS_FILE, "a") as f:
            f.write(json.dumps(proposal) + "\n")

        LOG.info(f"Genesis Proposal #{pid} erstellt: {diagnosis.error_type} in {Path(diagnosis.source_file).name}:{diagnosis.line_number}")
        return pid

    except Exception as e:
        LOG.error(f"Konnte Proposal nicht erstellen: {e}", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Daemon
# ---------------------------------------------------------------------------

class SelfDiagnosisDaemon:
    """Überwacht Logs auf Fehler und erstellt automatisch Fix-Proposals."""

    def __init__(self):
        self._running = False
        self._shutdown_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Log-Positionen (tail-artig)
        self._log_positions: Dict[str, int] = {}

        # Fehler-Gruppierung: (exc_type, file, func) → ErrorGroup
        self._error_groups: Dict[Tuple[str, str, str], ErrorGroup] = {}

        # Bereits vorgeschlagene Fixes (verhindert Doppel-Proposals)
        self._proposed_keys: Set[Tuple[str, str, str]] = set()

        # Rate-Limiting
        self._proposals_this_hour: List[float] = []

        LOG.info("Self-Diagnosis Daemon initialisiert")

    def start(self):
        """Starte den Daemon."""
        if self._running:
            LOG.warning("Daemon läuft bereits")
            return
        self._running = True
        self._shutdown_event.clear()
        self._thread = threading.Thread(target=self._daemon_loop, daemon=True)
        self._thread.start()
        LOG.info("Self-Diagnosis Daemon gestartet")

    def stop(self):
        """Stoppe den Daemon."""
        LOG.info("Stoppe Self-Diagnosis Daemon...")
        self._running = False
        self._shutdown_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        LOG.info("Self-Diagnosis Daemon gestoppt")

    def get_status(self) -> Dict:
        """Status-Abfrage."""
        return {
            "running": self._running,
            "watched_logs": [str(p) for p in WATCHED_LOGS],
            "error_groups": len(self._error_groups),
            "proposals_created": len(self._proposed_keys),
            "active_errors": {
                f"{k[0]}:{Path(k[1]).name}:{k[2]}": g.count
                for k, g in self._error_groups.items()
                if not g.proposed
            },
        }

    def _daemon_loop(self):
        """Haupt-Loop."""
        LOG.info("Diagnosis-Loop gestartet")
        # Initiale Positionen auf Ende setzen (nur neue Fehler erkennen)
        for log_path in WATCHED_LOGS:
            if log_path.exists():
                self._log_positions[str(log_path)] = log_path.stat().st_size

        while self._running and not self._shutdown_event.is_set():
            try:
                self._scan_cycle()
            except Exception as e:
                LOG.error(f"Scan-Cycle Fehler: {e}", exc_info=True)
            self._shutdown_event.wait(CHECK_INTERVAL_S)

        LOG.info("Diagnosis-Loop beendet")

    def _scan_cycle(self):
        """Ein Scan-Durchlauf: Logs lesen → Fehler parsen → gruppieren → analysieren."""
        now = time.time()

        # Rate-Limit prüfen
        self._proposals_this_hour = [
            t for t in self._proposals_this_hour if now - t < 3600
        ]

        # 1. Neue Log-Zeilen lesen
        new_lines = self._read_new_lines()
        if not new_lines:
            return

        # 2. Fehler parsen
        errors = parse_error_entries(new_lines)
        if not errors:
            return

        LOG.info(f"Gefunden: {len(errors)} neue Fehler-Einträge")

        # 3. Gruppieren
        for err in errors:
            key = (err.exception_type, err.source_file, err.function_name)
            if key not in self._error_groups:
                self._error_groups[key] = ErrorGroup(
                    key=key, first_seen=now
                )
            group = self._error_groups[key]
            group.entries.append(err)
            group.last_seen = now

        # 4. Alte Einträge bereinigen (außerhalb des Fensters)
        for key, group in list(self._error_groups.items()):
            group.entries = [
                e for e in group.entries
                if now - self._parse_ts(e.timestamp) < WINDOW_SECONDS
            ]
            if not group.entries:
                del self._error_groups[key]

        # 5. Analysieren und Proposals erstellen
        for key, group in self._error_groups.items():
            if group.proposed or key in self._proposed_keys:
                continue
            if group.count < ERROR_THRESHOLD:
                continue
            if len(self._proposals_this_hour) >= MAX_PROPOSALS_PER_HOUR:
                LOG.warning("Rate-Limit erreicht, keine weiteren Proposals")
                break

            # Analysieren
            diagnosis = analyze_error(group)
            if diagnosis is None:
                continue

            LOG.info(
                f"Diagnose: {diagnosis.error_type} in "
                f"{Path(diagnosis.source_file).name}:{diagnosis.line_number} "
                f"({group.count}x) — Confidence: {diagnosis.confidence:.0%}"
            )

            # Proposal erstellen
            pid = create_proposal(diagnosis)
            if pid is not None:
                group.proposed = True
                group.proposal_id = pid
                self._proposed_keys.add(key)
                self._proposals_this_hour.append(now)

    def _read_new_lines(self) -> List[str]:
        """Lies neue Zeilen aus allen überwachten Log-Dateien."""
        all_lines = []
        for log_path in WATCHED_LOGS:
            path_str = str(log_path)
            if not log_path.exists():
                continue

            try:
                current_size = log_path.stat().st_size
                last_pos = self._log_positions.get(path_str, 0)

                # Log wurde rotiert/gekürzt
                if current_size < last_pos:
                    last_pos = 0

                if current_size <= last_pos:
                    continue

                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(last_pos)
                    new_data = f.read()
                    self._log_positions[path_str] = f.tell()

                lines = new_data.splitlines()
                all_lines.extend(lines)

            except OSError as e:
                LOG.warning(f"Konnte {log_path} nicht lesen: {e}")
            except Exception as e:
                LOG.error(f"Fehler beim Lesen von {log_path}: {e}", exc_info=True)

        return all_lines

    @staticmethod
    def _parse_ts(ts_str: str) -> float:
        """Parse Timestamp-String zu Unix-Time."""
        try:
            # Format: 2026-02-06 22:41:33,123 oder 2026-02-06 22:41:33
            clean = ts_str.split(",")[0].strip()
            dt = datetime.strptime(clean, "%Y-%m-%d %H:%M:%S")
            return dt.timestamp()
        except Exception:
            return time.time()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_daemon: Optional[SelfDiagnosisDaemon] = None
_daemon_lock = threading.Lock()


def get_self_diagnosis() -> SelfDiagnosisDaemon:
    """Singleton-Zugriff auf den Daemon."""
    global _daemon
    if _daemon is None:
        with _daemon_lock:
            if _daemon is None:
                _daemon = SelfDiagnosisDaemon()
    return _daemon


def get_diagnosis_status() -> Dict:
    """Status des Daemons abfragen."""
    return get_self_diagnosis().get_status()


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------
def main():
    """Standalone-Start des Daemons."""
    def _signal_handler(signum, frame):
        LOG.info(f"Signal {signum} empfangen")
        if _daemon:
            _daemon.stop()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    daemon = get_self_diagnosis()
    try:
        daemon.start()
        LOG.info("Self-Diagnosis Daemon läuft — Ctrl+C zum Beenden")
        while daemon._running:
            time.sleep(1)
    except KeyboardInterrupt:
        LOG.info("Unterbrochen durch Benutzer")
    finally:
        daemon.stop()


if __name__ == "__main__":
    main()
