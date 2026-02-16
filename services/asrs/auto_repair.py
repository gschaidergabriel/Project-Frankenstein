#!/usr/bin/env python3
"""
A.S.R.S. Auto-Repair Module
Diagnoses root causes of anomalies and generates targeted repair actions.

Flow:
1. SystemDiagnoser examines anomalies and identifies root causes
2. RepairActionGenerator produces concrete fix commands
3. AutoRepairManager coordinates diagnosis → approval → execution
4. RepairExecutor runs the approved commands
"""

import logging
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from tools.approval_queue import submit_request, check_response, ApprovalUrgency

LOG = logging.getLogger("asrs.auto_repair")


# ---------------------------------------------------------------------------
# Auto-Approval Policy
# ---------------------------------------------------------------------------
# Actions classified by risk level for autonomous execution.
# LOW risk = auto-approved (no user confirmation needed)
# MEDIUM risk = auto-approved with safety checks + logging
# HIGH risk = requires user approval via approval queue

class RiskLevel(Enum):
    LOW = "low"          # Auto-approve: service restarts, ionice, renice, temp cleanup
    MEDIUM = "medium"    # Auto-approve with checks: kill user processes, journal vacuum
    HIGH = "high"        # Require user approval: kill system processes, unknown commands

# Command patterns and their risk classification
_AUTO_APPROVE_PATTERNS = {
    # LOW risk - always safe, auto-approve
    "systemctl --user restart": RiskLevel.LOW,
    "systemctl --user stop": RiskLevel.LOW,
    "systemctl --user start": RiskLevel.LOW,
    "ionice": RiskLevel.LOW,
    "renice": RiskLevel.LOW,
    "journalctl --user --vacuum": RiskLevel.MEDIUM,
    "find /tmp -type f -mtime": RiskLevel.MEDIUM,
}

# Max auto-approved actions per hour (safety limit)
_MAX_AUTO_APPROVALS_PER_HOUR = 15
_auto_approval_timestamps: List[float] = []


def _classify_risk(command: str) -> RiskLevel:
    """Classify a repair command by risk level."""
    cmd_lower = command.lower().strip()

    for pattern, risk in _AUTO_APPROVE_PATTERNS.items():
        if pattern.lower() in cmd_lower:
            return risk

    # kill commands: check if targeting aicore/frank processes
    if cmd_lower.startswith("kill "):
        # Check if target PID belongs to Frank
        try:
            parts = cmd_lower.split()
            pid_str = parts[-1]
            pid = int(pid_str)
            result = subprocess.run(
                ["ps", "-o", "comm=", "-p", str(pid)],
                capture_output=True, text=True, timeout=3,
            )
            comm = result.stdout.strip().lower()
            # Frank's own processes are safe to kill
            if any(k in comm for k in ("python", "frank", "aicore", "llama", "whisper")):
                return RiskLevel.MEDIUM
        except Exception:
            pass
        return RiskLevel.HIGH

    # Unknown commands default to HIGH risk
    return RiskLevel.HIGH


def _can_auto_approve() -> bool:
    """Check if we haven't exceeded the auto-approval rate limit."""
    now = time.time()
    cutoff = now - 3600  # 1 hour window
    _auto_approval_timestamps[:] = [t for t in _auto_approval_timestamps if t > cutoff]
    return len(_auto_approval_timestamps) < _MAX_AUTO_APPROVALS_PER_HOUR


def _record_auto_approval():
    """Record an auto-approval for rate limiting."""
    _auto_approval_timestamps.append(time.time())


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Diagnosis:
    """Result of diagnosing an anomaly."""
    anomaly_type: str
    root_cause: str
    evidence: Dict
    confidence: float  # 0.0 – 1.0


class RepairStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"
    AUTO_APPROVED = "auto_approved"


@dataclass
class RepairAction:
    """A concrete repair action to be executed."""
    id: str
    diagnosis: Diagnosis
    description_de: str
    description_en: str
    command: str
    urgency: ApprovalUrgency
    risk_level: RiskLevel = RiskLevel.HIGH
    status: RepairStatus = RepairStatus.PENDING
    request_id: Optional[str] = None  # approval-queue request id
    result: Optional[str] = None


# ---------------------------------------------------------------------------
# Severity → ApprovalUrgency mapping
# ---------------------------------------------------------------------------

_SEVERITY_TO_URGENCY = {
    "INFO":      ApprovalUrgency.LOW,
    "WARNING":   ApprovalUrgency.MEDIUM,
    "CRITICAL":  ApprovalUrgency.CRITICAL,
    "EMERGENCY": ApprovalUrgency.CRITICAL,
}


def _map_urgency(anomaly) -> ApprovalUrgency:
    """Map an anomaly's severity to an ApprovalUrgency."""
    if hasattr(anomaly, "severity"):
        name = anomaly.severity.name if hasattr(anomaly.severity, "name") else str(anomaly.severity).upper()
    elif isinstance(anomaly, dict):
        name = anomaly.get("severity", "WARNING").upper()
    else:
        name = "WARNING"
    return _SEVERITY_TO_URGENCY.get(name, ApprovalUrgency.MEDIUM)


# ---------------------------------------------------------------------------
# SystemDiagnoser
# ---------------------------------------------------------------------------

class SystemDiagnoser:
    """Diagnoses the root cause of detected anomalies."""

    # Map anomaly type keywords to diagnosis handlers
    _DISPATCH = {
        "cpu":      "_diagnose_high_cpu",
        "loop":     "_diagnose_high_cpu",
        "memory":   "_diagnose_memory",
        "oom":      "_diagnose_memory",
        "leak":     "_diagnose_memory",
        "disk":     "_diagnose_disk_full",
        "service":  "_diagnose_service_crash",
        "crash":    "_diagnose_service_crash",
        "io":       "_diagnose_io_storm",
        "thermal":  "_diagnose_thermal",
        "swap":     "_diagnose_swap",
    }

    def diagnose(self, anomaly) -> Diagnosis:
        """Dispatch to the correct handler based on anomaly type."""
        atype = anomaly.type if hasattr(anomaly, "type") else anomaly.get("type", "unknown")
        atype_lower = atype.lower()

        for keyword, method_name in self._DISPATCH.items():
            if keyword in atype_lower:
                handler = getattr(self, method_name)
                return handler(anomaly)

        # Fallback: treat unknown anomalies like high-cpu
        return self._diagnose_high_cpu(anomaly)

    # -- individual handlers ------------------------------------------------

    def _diagnose_high_cpu(self, anomaly) -> Diagnosis:
        """Find the process consuming the most CPU."""
        top_proc = self._top_process_by("cpu")
        return Diagnosis(
            anomaly_type=self._atype(anomaly),
            root_cause=f"Process '{top_proc['comm']}' (PID {top_proc['pid']}) consuming {top_proc['cpu']}% CPU",
            evidence=top_proc,
            confidence=0.75,
        )

    def _diagnose_memory(self, anomaly) -> Diagnosis:
        """Find the process consuming the most RSS memory."""
        top_proc = self._top_process_by("mem")
        return Diagnosis(
            anomaly_type=self._atype(anomaly),
            root_cause=f"Process '{top_proc['comm']}' (PID {top_proc['pid']}) using {top_proc['rss_mb']:.0f} MB RSS",
            evidence=top_proc,
            confidence=0.70,
        )

    def _diagnose_disk_full(self, anomaly) -> Diagnosis:
        """Find largest directories under common paths."""
        details = anomaly.details if hasattr(anomaly, "details") else anomaly.get("details", {})
        search_path = details.get("path", "/home/ai-core-node")
        largest = self._largest_dirs(search_path)
        return Diagnosis(
            anomaly_type=self._atype(anomaly),
            root_cause=f"Disk usage dominated by: {largest[:3]}",
            evidence={"largest_dirs": largest, "path": search_path},
            confidence=0.80,
        )

    def _diagnose_service_crash(self, anomaly) -> Diagnosis:
        """Pull the last error from journalctl for the crashed service."""
        details = anomaly.details if hasattr(anomaly, "details") else anomaly.get("details", {})
        services = details.get("crashed_services", [])
        service = services[0] if services else "unknown"
        last_error = self._last_service_error(service)
        return Diagnosis(
            anomaly_type=self._atype(anomaly),
            root_cause=f"Service '{service}' crashed: {last_error}",
            evidence={"service": service, "last_error": last_error},
            confidence=0.85,
        )

    def _diagnose_io_storm(self, anomaly) -> Diagnosis:
        """I/O storm — use top CPU process as proxy for the offender."""
        top_proc = self._top_process_by("cpu")
        return Diagnosis(
            anomaly_type=self._atype(anomaly),
            root_cause=f"I/O storm likely caused by '{top_proc['comm']}' (PID {top_proc['pid']})",
            evidence=top_proc,
            confidence=0.55,
        )

    def _diagnose_thermal(self, anomaly) -> Diagnosis:
        """Read GPU busy percent and top CPU process."""
        gpu_busy = self._read_gpu_busy()
        top_proc = self._top_process_by("cpu")
        return Diagnosis(
            anomaly_type=self._atype(anomaly),
            root_cause=f"Thermal issue — GPU busy {gpu_busy}%, top CPU: '{top_proc['comm']}' (PID {top_proc['pid']})",
            evidence={"gpu_busy_percent": gpu_busy, "top_process": top_proc},
            confidence=0.65,
        )

    def _diagnose_swap(self, anomaly) -> Diagnosis:
        """Swap pressure — same as memory (find largest consumer)."""
        top_proc = self._top_process_by("mem")
        return Diagnosis(
            anomaly_type=self._atype(anomaly),
            root_cause=f"Swap pressure from '{top_proc['comm']}' (PID {top_proc['pid']}), {top_proc['rss_mb']:.0f} MB RSS",
            evidence=top_proc,
            confidence=0.70,
        )

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _atype(anomaly) -> str:
        return anomaly.type if hasattr(anomaly, "type") else anomaly.get("type", "unknown")

    @staticmethod
    def _top_process_by(key: str) -> Dict:
        """Return the top process sorted by *key* ('cpu' or 'mem')."""
        sort_col = "-pcpu" if key == "cpu" else "-rss"
        fallback = {"pid": 0, "cpu": 0.0, "mem": 0.0, "rss_mb": 0.0, "comm": "unknown"}
        try:
            result = subprocess.run(
                ["ps", "-eo", "pid,pcpu,pmem,rss,comm", f"--sort={sort_col}"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.strip().splitlines()[1:]:
                parts = line.split(None, 4)
                if len(parts) >= 5:
                    return {
                        "pid": int(parts[0]),
                        "cpu": float(parts[1]),
                        "mem": float(parts[2]),
                        "rss_mb": int(parts[3]) / 1024,
                        "comm": parts[4],
                    }
        except Exception as exc:
            LOG.warning(f"_top_process_by({key}) failed: {exc}")
        return fallback

    @staticmethod
    def _largest_dirs(path: str) -> List[str]:
        """Return directory sizes under *path* (max-depth 1)."""
        try:
            result = subprocess.run(
                ["du", "-sh", "--max-depth=1", path],
                capture_output=True, text=True, timeout=15,
            )
            lines = sorted(result.stdout.strip().splitlines(), reverse=True)
            return [l.strip() for l in lines[:5]]
        except Exception as exc:
            LOG.warning(f"_largest_dirs failed: {exc}")
            return []

    @staticmethod
    def _last_service_error(service: str) -> str:
        """Return the last error line from journalctl for *service*."""
        try:
            result = subprocess.run(
                ["journalctl", "--user", "-u", service, "-p", "err",
                 "--since", "10 minutes ago", "--no-pager", "-o", "cat", "-n", "1"],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip() or "(no recent errors)"
        except Exception as exc:
            LOG.warning(f"_last_service_error failed: {exc}")
            return f"(could not read journal: {exc})"

    @staticmethod
    def _read_gpu_busy() -> int:
        """Read GPU busy percent from sysfs."""
        try:
            for card in sorted(Path("/sys/class/drm").glob("card*/device/gpu_busy_percent")):
                return int(card.read_text().strip())
        except Exception:
            pass
        return -1


# ---------------------------------------------------------------------------
# RepairActionGenerator
# ---------------------------------------------------------------------------

class RepairActionGenerator:
    """Generates concrete repair commands from a Diagnosis."""

    def generate(self, diagnosis: Diagnosis, urgency: ApprovalUrgency) -> Optional[RepairAction]:
        """Return a RepairAction for the given diagnosis, or None if no action applies."""
        atype = diagnosis.anomaly_type.lower()
        pid = diagnosis.evidence.get("pid", 0)
        comm = diagnosis.evidence.get("comm", "unknown")
        service = diagnosis.evidence.get("service", "")

        # -- CPU hog / infinite loop ----------------------------------------
        if any(k in atype for k in ("cpu", "loop")):
            if pid:
                return self._action(
                    diagnosis, urgency,
                    description_de=f"Terminate CPU process '{comm}' (PID {pid})",
                    description_en=f"Terminate CPU-hogging process '{comm}' (PID {pid})",
                    command=f"kill -TERM {pid}",
                )

        # -- Memory spike / leak / OOM --------------------------------------
        if any(k in atype for k in ("memory", "oom", "leak")):
            if pid:
                return self._action(
                    diagnosis, urgency,
                    description_de=f"Terminate memory hog '{comm}' (PID {pid})",
                    description_en=f"Terminate memory-hogging process '{comm}' (PID {pid})",
                    command=f"kill -TERM {pid}",
                )

        # -- Disk full ------------------------------------------------------
        if "disk" in atype:
            return self._action(
                diagnosis, urgency,
                description_de="Clean old temp files and journal logs",
                description_en="Clean old temp files and journal logs",
                command="find /tmp -type f -mtime +7 -delete; journalctl --user --vacuum-time=3d",
            )

        # -- Service crash --------------------------------------------------
        if any(k in atype for k in ("service", "crash")):
            if service:
                return self._action(
                    diagnosis, urgency,
                    description_de=f"Restart service '{service}'",
                    description_en=f"Restart service '{service}'",
                    command=f"systemctl --user restart {service}",
                )

        # -- I/O storm ------------------------------------------------------
        if "io" in atype:
            if pid:
                return self._action(
                    diagnosis, urgency,
                    description_de=f"Lower I/O priority of '{comm}' (PID {pid})",
                    description_en=f"Lower I/O priority of '{comm}' (PID {pid})",
                    command=f"ionice -c 3 -p {pid}",
                )

        # -- Thermal --------------------------------------------------------
        if "thermal" in atype:
            top_proc = diagnosis.evidence.get("top_process", diagnosis.evidence)
            tp_pid = top_proc.get("pid", 0)
            tp_comm = top_proc.get("comm", "unknown")
            # Prefer stopping the wallpaper service if it is the culprit
            if "wallpaper" in tp_comm.lower():
                return self._action(
                    diagnosis, urgency,
                    description_de="Stop frank-wallpaper service (thermal)",
                    description_en="Stop frank-wallpaper service (thermal issue)",
                    command="systemctl --user stop frank-wallpaper",
                )
            if tp_pid:
                return self._action(
                    diagnosis, urgency,
                    description_de=f"Renice process '{tp_comm}' (PID {tp_pid})",
                    description_en=f"Renice process '{tp_comm}' (PID {tp_pid}) to lower priority",
                    command=f"renice +15 -p {tp_pid}",
                )

        # -- Swap pressure --------------------------------------------------
        if "swap" in atype:
            if pid:
                return self._action(
                    diagnosis, urgency,
                    description_de=f"Terminate largest memory consumer '{comm}' (PID {pid})",
                    description_en=f"Terminate largest memory consumer '{comm}' (PID {pid})",
                    command=f"kill -TERM {pid}",
                )

        LOG.warning(f"No repair action for anomaly type '{atype}'")
        return None

    # -- helper -------------------------------------------------------------

    @staticmethod
    def _action(diagnosis, urgency, description_de, description_en, command) -> RepairAction:
        return RepairAction(
            id=f"repair_{int(time.time())}_{uuid.uuid4().hex[:6]}",
            diagnosis=diagnosis,
            description_de=description_de,
            description_en=description_en,
            command=command,
            urgency=urgency,
            risk_level=_classify_risk(command),
        )


# ---------------------------------------------------------------------------
# RepairExecutor
# ---------------------------------------------------------------------------

class RepairExecutor:
    """Executes an approved repair action."""

    def execute(self, action: RepairAction) -> bool:
        """Run the repair command. Returns True on success."""
        LOG.info(f"Executing repair {action.id}: {action.command}")
        try:
            result = subprocess.run(
                action.command, shell=True,
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                action.status = RepairStatus.EXECUTED
                action.result = result.stdout.strip() or "(ok)"
                LOG.info(f"Repair {action.id} succeeded: {action.result}")
                return True
            else:
                action.status = RepairStatus.FAILED
                action.result = result.stderr.strip() or f"exit code {result.returncode}"
                LOG.error(f"Repair {action.id} failed: {action.result}")
                return False
        except subprocess.TimeoutExpired:
            action.status = RepairStatus.FAILED
            action.result = "Command timed out after 30s"
            LOG.error(f"Repair {action.id} timed out")
            return False
        except Exception as exc:
            action.status = RepairStatus.FAILED
            action.result = str(exc)
            LOG.error(f"Repair {action.id} exception: {exc}")
            return False


# ---------------------------------------------------------------------------
# AutoRepairManager  (main coordinator)
# ---------------------------------------------------------------------------

class AutoRepairManager:
    """
    Coordinates the full auto-repair pipeline:
    diagnose → generate action → submit for approval → execute.
    """

    def __init__(self):
        self.diagnoser = SystemDiagnoser()
        self.generator = RepairActionGenerator()
        self.executor = RepairExecutor()
        self._pending_actions: List[RepairAction] = []
        self._lock = threading.Lock()
        LOG.info("AutoRepairManager initialized")

    def attempt_repair(self, anomalies: list) -> List[RepairAction]:
        """
        Diagnose all anomalies, generate repair actions, and either
        auto-approve (for safe actions) or submit to the approval queue.

        Auto-Approval Policy:
        - LOW risk (service restarts, ionice, renice): Execute immediately
        - MEDIUM risk (kill Frank processes, temp cleanup): Execute with logging
        - HIGH risk (unknown commands): Require user approval

        Returns the list of generated RepairActions.
        """
        actions: List[RepairAction] = []

        for anomaly in anomalies:
            try:
                diagnosis = self.diagnoser.diagnose(anomaly)
                urgency = _map_urgency(anomaly)
                action = self.generator.generate(diagnosis, urgency)
                if action is None:
                    continue

                # Check if action can be auto-approved
                if action.risk_level in (RiskLevel.LOW, RiskLevel.MEDIUM) and _can_auto_approve():
                    # AUTO-APPROVE: Execute immediately without user confirmation
                    _record_auto_approval()
                    action.status = RepairStatus.AUTO_APPROVED
                    LOG.info(
                        f"AUTO-APPROVE [{action.risk_level.value}]: {action.description_de} "
                        f"(cmd: {action.command}, confidence: {diagnosis.confidence:.0%})"
                    )
                    self.executor.execute(action)
                    actions.append(action)
                else:
                    # HIGH risk or rate-limited → submit to approval queue
                    request_id = submit_request(
                        daemon="asrs",
                        urgency=action.urgency,
                        category="auto_repair",
                        title_de=action.description_de,
                        detail_de=(
                            f"Diagnosis: {diagnosis.root_cause}\n"
                            f"Command: {action.command}\n"
                            f"Confidence: {diagnosis.confidence:.0%}\n"
                            f"Risk: {action.risk_level.value}"
                        ),
                        action_payload={
                            "repair_id": action.id,
                            "command": action.command,
                            "anomaly_type": diagnosis.anomaly_type,
                            "confidence": diagnosis.confidence,
                            "risk_level": action.risk_level.value,
                        },
                    )
                    action.request_id = request_id
                    actions.append(action)
                    LOG.info(
                        f"Repair action submitted (HIGH risk): {action.id} → approval {request_id}"
                    )

            except Exception as exc:
                LOG.error(f"Failed to process anomaly for repair: {exc}")

        with self._lock:
            self._pending_actions.extend(actions)

        return actions

    def process_queue(self):
        """
        Check pending actions for approval responses and execute
        any that have been approved.
        """
        with self._lock:
            still_pending: List[RepairAction] = []

            for action in self._pending_actions:
                if action.status != RepairStatus.PENDING:
                    continue

                if action.request_id is None:
                    continue

                resp = check_response(action.request_id, consume=True)
                if resp is None:
                    still_pending.append(action)
                    continue

                decision = resp.get("decision", "")
                if decision == "approved":
                    action.status = RepairStatus.APPROVED
                    LOG.info(f"Repair {action.id} approved — executing")
                    self.executor.execute(action)
                else:
                    action.status = RepairStatus.REJECTED
                    LOG.info(f"Repair {action.id} rejected by user")

            self._pending_actions = still_pending
