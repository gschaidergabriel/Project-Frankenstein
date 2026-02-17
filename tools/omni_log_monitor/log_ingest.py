#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Universal Omniscient Log Gateway (UOLG) - Log Ingestion Daemon

Frank's nervous system for log awareness.
Purpose: Understanding, not surveillance.

Collects logs from three layers:
- Layer 1: OS-Kernel & Hardware ("Instincts")
- Layer 2: System-Services & Daemons ("Nervous System")
- Layer 3: Program Level ("Consciousness")

Resource limits:
- 150 MB RAM hard limit
- Streaming only, no raw log persistence
- Gaming mode protection
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import resource

# Set memory limit (150 MB)
MEMORY_LIMIT_MB = 150
try:
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_MB * 1024 * 1024, hard))
except Exception:
    pass  # May not work on all systems

# Logging setup
try:
    from config.paths import TEMP_DIR as _li_tmp_root
    LOG_DIR = _li_tmp_root / "uolg"
except ImportError:
    import tempfile as _li_tmpmod
    LOG_DIR = Path(_li_tmpmod.gettempdir()) / "frank" / "uolg"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s [UOLG]: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(LOG_DIR / "uolg.log")
    ]
)
LOG = logging.getLogger("uolg")

# Paths
BASE_DIR = Path(__file__).parent
try:
    from config.paths import DB_DIR, get_state, get_db
    SECURITY_LOG = get_state("security_log")
    WORLD_EXPERIENCE_DB = get_db("world_experience")
except ImportError:
    _DATA_DIR = Path.home() / ".local" / "share" / "frank"
    DB_DIR = _DATA_DIR / "db"
    DB_DIR.mkdir(parents=True, exist_ok=True)
    _STATE_DIR = _DATA_DIR / "state"
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    SECURITY_LOG = _STATE_DIR / "security_log.json"
    WORLD_EXPERIENCE_DB = DB_DIR / "world_experience.db"
try:
    from config.paths import get_temp
    GAMING_STATE_FILE = get_temp("gaming_mode_state.json")
except ImportError:
    import tempfile as _li_tempfile
    GAMING_STATE_FILE = Path(_li_tempfile.gettempdir()) / "frank" / "gaming_mode_state.json"

# Configuration
CONFIG = {
    "buffer_max_lines": 1000,          # Max lines in memory per source
    "fingerprint_window_sec": 60,       # Aggregate identical logs within window
    "correlation_window_sec": 5,        # Cross-correlate events within window
    "poll_interval_sec": 2,             # How often to poll logs
    "insight_emit_interval_sec": 10,    # How often to emit insights
    "max_insights_buffer": 100,         # Max insights to keep
    "routine_threshold": 10,            # Count threshold for "routine" classification
}

# Log source definitions
LOG_SOURCES = {
    # Layer 1: Kernel & Hardware ("Instincts")
    "layer1": {
        "dmesg": {"cmd": ["dmesg", "-T", "--follow"], "level": 1, "type": "stream"},
        "kern": {"path": "/var/log/kern.log", "level": 1, "type": "file"},
    },
    # Layer 2: System Services ("Nervous System")
    "layer2": {
        "journald": {"cmd": ["journalctl", "-f", "-o", "json"], "level": 2, "type": "stream"},
        "syslog": {"path": "/var/log/syslog", "level": 2, "type": "file"},
    },
    # Layer 3: Program Level ("Consciousness")
    "layer3": {
        "auth": {"path": "/var/log/auth.log", "level": 3, "type": "file"},
        "dpkg": {"path": "/var/log/dpkg.log", "level": 3, "type": "file"},
        "aicore": {"path": str(LOG_DIR / "aicore.log"), "level": 3, "type": "file"},
        "gaming": {"path": str(LOG_DIR / "gaming_mode.log"), "level": 3, "type": "file"},
    },
}

# Patterns for anomaly detection
ANOMALY_PATTERNS = {
    "error": re.compile(r'\b(error|fail(ed|ure)?|fatal|critical|panic|exception)\b', re.I),
    "security": re.compile(r'\b(denied|unauthorized|invalid|attack|breach|intrusion)\b', re.I),
    "resource": re.compile(r'\b(out of memory|oom|killed|throttl|overheat|thermal)\b', re.I),
    "network": re.compile(r'\b(connection (refused|reset|timeout)|unreachable|dns)\b', re.I),
    "hardware": re.compile(r'\b(usb|gpu|cpu|disk|sata|nvme|pci|driver)\b', re.I),
}

# Severity mapping
SEVERITY_KEYWORDS = {
    "critical": 5,
    "error": 4,
    "warning": 3,
    "warn": 3,
    "notice": 2,
    "info": 1,
    "debug": 0,
}


@dataclass
class LogEntry:
    """Single log entry."""
    timestamp: datetime
    source: str
    layer: int
    message: str
    severity: int = 1
    fingerprint: str = ""

    def __post_init__(self):
        if not self.fingerprint:
            # Create fingerprint from normalized message
            normalized = re.sub(r'\d+', 'N', self.message)  # Replace numbers
            normalized = re.sub(r'0x[a-fA-F0-9]+', 'HEX', normalized)  # Replace hex
            normalized = re.sub(r'\s+', ' ', normalized).strip()[:200]
            self.fingerprint = hashlib.md5(normalized.encode()).hexdigest()[:12]


@dataclass
class AggregatedEvent:
    """Aggregated log events with same fingerprint."""
    fingerprint: str
    first_seen: datetime
    last_seen: datetime
    count: int
    source: str
    layer: int
    representative_message: str
    severity: int
    anomaly_types: Set[str] = field(default_factory=set)


@dataclass
class SystemInsight:
    """Unified Insight Format (UIF) - hypothesis structure."""
    timestamp: datetime
    entity: str
    event_class: str
    hypotheses: List[Dict[str, float]]  # [{"cause": "...", "weight": 0.5}, ...]
    confidence: float
    actionability: str  # "observe", "alert", "investigate"
    intrusive_methods_used: bool = False
    correlation_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "time": self.timestamp.isoformat(),
            "entity": self.entity,
            "event_class": self.event_class,
            "hypotheses": self.hypotheses,
            "confidence": round(self.confidence, 2),
            "actionability": self.actionability,
            "intrusive_methods_used": self.intrusive_methods_used,
            "correlation_ids": self.correlation_ids,
        }


class GamingModeGuard:
    """Enforces gaming mode restrictions."""

    def __init__(self):
        self.gaming_active = False
        self._check_interval = 1.0  # Reduziert von 5s auf 1s für schnellere Reaktion
        self._last_check = 0

    def is_gaming(self) -> bool:
        """Check if gaming mode is active."""
        import fcntl
        now = time.time()
        if now - self._last_check < self._check_interval:
            return self.gaming_active

        self._last_check = now
        try:
            if GAMING_STATE_FILE.exists():
                # File locking um Race Conditions zu vermeiden
                with open(GAMING_STATE_FILE, 'r') as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                    try:
                        data = json.load(f)
                    finally:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                self.gaming_active = data.get("active", False)
        except (json.JSONDecodeError, IOError, OSError):
            pass  # Keep last known state
        return self.gaming_active

    def allowed_sources(self) -> Set[str]:
        """Return allowed log sources based on mode."""
        if self.gaming_active:
            # Only passive sources during gaming
            return {"syslog", "auth", "kern"}
        return set(LOG_SOURCES["layer1"].keys()) | \
               set(LOG_SOURCES["layer2"].keys()) | \
               set(LOG_SOURCES["layer3"].keys())

    def intrusive_allowed(self) -> bool:
        """Check if intrusive inspection (ptrace/strace) is allowed."""
        return not self.gaming_active


class LogDistiller:
    """
    Core log processing: fingerprinting, compression, correlation.

    Transforms raw log noise into explainable episodes.
    """

    def __init__(self):
        self.fingerprints: Dict[str, AggregatedEvent] = {}
        self.recent_events: List[LogEntry] = []
        self.insights: List[SystemInsight] = []
        self.gaming_guard = GamingModeGuard()
        self._lock = threading.Lock()

    def ingest(self, entry: LogEntry) -> Optional[AggregatedEvent]:
        """
        Ingest a log entry, apply fingerprinting and compression.

        Returns aggregated event if threshold crossed or anomaly detected.
        """
        with self._lock:
            # Check gaming mode restrictions
            if entry.source not in self.gaming_guard.allowed_sources():
                return None

            # Detect anomaly types
            anomalies = set()
            for atype, pattern in ANOMALY_PATTERNS.items():
                if pattern.search(entry.message):
                    anomalies.add(atype)

            # Extract severity from message
            for keyword, level in SEVERITY_KEYWORDS.items():
                if keyword in entry.message.lower():
                    entry.severity = max(entry.severity, level)
                    break

            # Update fingerprint aggregation
            fp = entry.fingerprint
            if fp in self.fingerprints:
                agg = self.fingerprints[fp]
                agg.last_seen = entry.timestamp
                agg.count += 1
                agg.anomaly_types.update(anomalies)

                # Check if we should emit this
                # High severity or first time crossing threshold
                if agg.count == CONFIG["routine_threshold"]:
                    # Reached routine threshold - this is now "routine"
                    LOG.debug(f"Event {fp} is now routine (count={agg.count})")
                    return None
                elif agg.count < CONFIG["routine_threshold"] and anomalies:
                    return agg
            else:
                # New fingerprint
                agg = AggregatedEvent(
                    fingerprint=fp,
                    first_seen=entry.timestamp,
                    last_seen=entry.timestamp,
                    count=1,
                    source=entry.source,
                    layer=entry.layer,
                    representative_message=entry.message[:500],
                    severity=entry.severity,
                    anomaly_types=anomalies,
                )
                self.fingerprints[fp] = agg

                # Add to recent events for correlation
                self.recent_events.append(entry)
                if len(self.recent_events) > CONFIG["buffer_max_lines"]:
                    self.recent_events.pop(0)

                # Return if anomaly or high severity
                if anomalies or entry.severity >= 3:
                    return agg

            return None

    def correlate(self, trigger_event: AggregatedEvent) -> List[AggregatedEvent]:
        """
        Find correlated events within the correlation window.

        Cross-correlates logs from different layers to find related events.
        """
        with self._lock:
            correlated = []
            window = timedelta(seconds=CONFIG["correlation_window_sec"])

            for entry in self.recent_events:
                if entry.fingerprint == trigger_event.fingerprint:
                    continue

                # Check time window
                time_diff = abs((entry.timestamp - trigger_event.first_seen).total_seconds())
                if time_diff <= CONFIG["correlation_window_sec"]:
                    # Different layer = more interesting correlation
                    if entry.layer != trigger_event.layer:
                        fp = entry.fingerprint
                        if fp in self.fingerprints:
                            correlated.append(self.fingerprints[fp])

            return correlated

    def form_hypotheses(self, event: AggregatedEvent,
                        correlated: List[AggregatedEvent]) -> SystemInsight:
        """
        Form hypotheses based on event and correlated events.

        Produces UIF (Unified Insight Format) with explicit uncertainty.
        """
        hypotheses = []
        confidence = 0.5  # Start uncertain

        # Analyze the trigger event
        entity = self._extract_entity(event.representative_message)
        event_class = self._classify_event(event)

        # Primary hypothesis based on anomaly types
        if "resource" in event.anomaly_types:
            hypotheses.append({"cause": "Resource_Exhaustion", "weight": 0.4})
            hypotheses.append({"cause": "Memory_Leak", "weight": 0.3})
            hypotheses.append({"cause": "Process_Runaway", "weight": 0.2})

        if "error" in event.anomaly_types:
            hypotheses.append({"cause": "Software_Bug", "weight": 0.35})
            hypotheses.append({"cause": "Configuration_Error", "weight": 0.25})
            hypotheses.append({"cause": "Dependency_Failure", "weight": 0.2})

        if "hardware" in event.anomaly_types:
            hypotheses.append({"cause": "Hardware_Degradation", "weight": 0.4})
            hypotheses.append({"cause": "Driver_Issue", "weight": 0.35})
            hypotheses.append({"cause": "Thermal_Event", "weight": 0.15})

        if "security" in event.anomaly_types:
            hypotheses.append({"cause": "Unauthorized_Access_Attempt", "weight": 0.45})
            hypotheses.append({"cause": "Configuration_Drift", "weight": 0.25})
            hypotheses.append({"cause": "False_Positive", "weight": 0.2})

        if "network" in event.anomaly_types:
            hypotheses.append({"cause": "Network_Connectivity", "weight": 0.4})
            hypotheses.append({"cause": "DNS_Resolution", "weight": 0.25})
            hypotheses.append({"cause": "Remote_Service_Down", "weight": 0.25})

        # Adjust based on correlated events
        correlation_ids = []
        for corr in correlated:
            correlation_ids.append(corr.fingerprint)

            # Layer 1 correlation = hardware likely
            if corr.layer == 1:
                for h in hypotheses:
                    if "Hardware" in h["cause"] or "Thermal" in h["cause"]:
                        h["weight"] = min(0.8, h["weight"] + 0.2)
                        confidence += 0.1

            # Layer 2 correlation = system service issue
            if corr.layer == 2:
                for h in hypotheses:
                    if "Service" in h["cause"] or "Dependency" in h["cause"]:
                        h["weight"] = min(0.8, h["weight"] + 0.15)
                        confidence += 0.08

        # Default hypothesis if none formed
        if not hypotheses:
            hypotheses.append({"cause": "Unknown_Anomaly", "weight": 0.5})
            hypotheses.append({"cause": "Transient_Event", "weight": 0.3})

        # Normalize weights
        total_weight = sum(h["weight"] for h in hypotheses)
        if total_weight > 0:
            for h in hypotheses:
                h["weight"] = round(h["weight"] / total_weight, 2)

        # Sort by weight
        hypotheses.sort(key=lambda x: x["weight"], reverse=True)
        hypotheses = hypotheses[:5]  # Keep top 5

        # Determine actionability
        if event.severity >= 4 or "security" in event.anomaly_types:
            actionability = "alert"
        elif event.severity >= 3 or len(correlated) >= 2:
            actionability = "investigate"
        else:
            actionability = "observe"

        confidence = min(0.95, max(0.1, confidence))

        return SystemInsight(
            timestamp=event.last_seen,
            entity=entity,
            event_class=event_class,
            hypotheses=hypotheses,
            confidence=confidence,
            actionability=actionability,
            intrusive_methods_used=False,
            correlation_ids=correlation_ids,
        )

    def _extract_entity(self, message: str) -> str:
        """Extract the primary entity from a log message."""
        # Try to find process/service name
        patterns = [
            r'^([a-zA-Z][a-zA-Z0-9_-]{2,})\[',  # syslog format: "process[pid]" (min 3 chars, starts with letter)
            r'^([a-zA-Z][a-zA-Z0-9_-]+\.service)',  # systemd service
            r'^([a-zA-Z][a-zA-Z0-9_-]{2,}): ',  # common prefix (min 3 chars)
        ]

        # Blacklist of non-entity names (journalctl artifacts, etc.)
        blacklist = {'kernel', 'user', 'daemon', 'system', 'local', 'auth', 'cron', 'mail'}

        for pattern in patterns:
            match = re.search(pattern, message)
            if match:
                entity = match.group(1)
                # Skip pure numbers, too short, or blacklisted
                if entity.isdigit():
                    continue
                if len(entity) < 2:
                    continue
                if entity.lower() in blacklist:
                    continue
                return entity
        return "System"

    def _classify_event(self, event: AggregatedEvent) -> str:
        """Classify the event type."""
        if "security" in event.anomaly_types:
            return "Security_Event"
        if "resource" in event.anomaly_types:
            return "Resource_Anomaly"
        if "hardware" in event.anomaly_types:
            return "Hardware_Event"
        if "network" in event.anomaly_types:
            return "Network_Event"
        if "error" in event.anomaly_types:
            return "Error_Event"
        if event.severity >= 4:
            return "Critical_Event"
        return "General_Event"

    def add_insight(self, insight: SystemInsight):
        """Add insight to buffer."""
        with self._lock:
            self.insights.append(insight)
            if len(self.insights) > CONFIG["max_insights_buffer"]:
                self.insights.pop(0)

    def get_recent_insights(self, count: int = 10) -> List[SystemInsight]:
        """Get recent insights."""
        with self._lock:
            return list(self.insights[-count:])

    def cleanup_old_fingerprints(self, max_age_sec: int = 3600):
        """Remove old fingerprints to prevent memory growth."""
        with self._lock:
            now = datetime.now()
            to_remove = []
            for fp, agg in self.fingerprints.items():
                age = (now - agg.last_seen).total_seconds()
                if age > max_age_sec:
                    to_remove.append(fp)

            for fp in to_remove:
                del self.fingerprints[fp]

            if to_remove:
                LOG.debug(f"Cleaned up {len(to_remove)} old fingerprints")


class LogStreamReader:
    """Reads logs from various sources."""

    def __init__(self, distiller: LogDistiller):
        self.distiller = distiller
        self.processes: Dict[str, subprocess.Popen] = {}
        self.file_positions: Dict[str, int] = {}
        self._stop_event = threading.Event()

    def start_stream(self, name: str, config: dict):
        """Start a streaming log source."""
        if config["type"] != "stream":
            return

        try:
            proc = subprocess.Popen(
                config["cmd"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            self.processes[name] = proc

            # Start reader thread
            thread = threading.Thread(
                target=self._read_stream,
                args=(name, proc, config["level"]),
                daemon=True
            )
            thread.start()
            LOG.info(f"Started stream: {name}")
        except Exception as e:
            LOG.warning(f"Failed to start stream {name}: {e}")

    def _read_stream(self, name: str, proc: subprocess.Popen, layer: int):
        """Read from a streaming process."""
        try:
            for line in proc.stdout:
                if self._stop_event.is_set():
                    break

                line = line.strip()
                if not line:
                    continue

                # Parse timestamp if present
                timestamp = datetime.now()

                # For journalctl JSON output
                if name == "journald" and line.startswith("{"):
                    try:
                        data = json.loads(line)
                        line = data.get("MESSAGE", line)
                        if "__REALTIME_TIMESTAMP" in data:
                            ts = int(data["__REALTIME_TIMESTAMP"]) / 1_000_000
                            timestamp = datetime.fromtimestamp(ts)
                    except json.JSONDecodeError:
                        pass

                entry = LogEntry(
                    timestamp=timestamp,
                    source=name,
                    layer=layer,
                    message=line,
                )

                agg = self.distiller.ingest(entry)
                if agg:
                    correlated = self.distiller.correlate(agg)
                    insight = self.distiller.form_hypotheses(agg, correlated)
                    self.distiller.add_insight(insight)

                    if insight.actionability in ("alert", "investigate"):
                        LOG.info(f"Insight: {insight.entity} - {insight.event_class} "
                                f"(confidence={insight.confidence:.2f})")

        except Exception as e:
            LOG.error(f"Stream reader {name} error: {e}")

    def poll_file(self, name: str, config: dict):
        """Poll a file-based log source."""
        if config["type"] != "file":
            return

        path = Path(config["path"])
        if not path.exists():
            return

        try:
            # Get current position
            pos = self.file_positions.get(name, 0)

            with open(path, "r") as f:
                f.seek(0, 2)  # End of file
                end_pos = f.tell()

                if pos == 0:
                    # First read - start from recent (last 10KB)
                    pos = max(0, end_pos - 10240)

                if end_pos > pos:
                    f.seek(pos)
                    lines = f.readlines()
                    self.file_positions[name] = f.tell()

                    for line in lines[-100:]:  # Limit lines per poll
                        line = line.strip()
                        if not line:
                            continue

                        entry = LogEntry(
                            timestamp=datetime.now(),
                            source=name,
                            layer=config["level"],
                            message=line,
                        )

                        agg = self.distiller.ingest(entry)
                        if agg:
                            correlated = self.distiller.correlate(agg)
                            insight = self.distiller.form_hypotheses(agg, correlated)
                            self.distiller.add_insight(insight)

        except PermissionError:
            pass  # Normal for some system logs
        except Exception as e:
            LOG.debug(f"File poll {name} error: {e}")

    def stop(self):
        """Stop all streams."""
        self._stop_event.set()
        for name, proc in self.processes.items():
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
        LOG.info("Stopped all log streams")


class InsightEmitter:
    """Emits insights to Frank and persistence."""

    UIF_BRIDGE_URL = "http://localhost:8197"

    def __init__(self, distiller: LogDistiller):
        self.distiller = distiller
        self._last_security_write = 0
        self._last_sent_idx = 0

    def _send_to_bridge(self, insight: SystemInsight):
        """Send insight to UIF Bridge."""
        try:
            import urllib.request
            body = json.dumps({"insight": insight.to_dict()}).encode()
            req = urllib.request.Request(
                f"{self.UIF_BRIDGE_URL}/ingest",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass  # Bridge may not be running

    def emit_to_bridge(self):
        """Send new insights to UIF Bridge."""
        insights = self.distiller.get_recent_insights(50)
        for i, insight in enumerate(insights):
            if i >= self._last_sent_idx:
                self._send_to_bridge(insight)
        self._last_sent_idx = len(insights)

    def emit_to_file(self):
        """Write recent security-relevant insights to security_log.json."""
        insights = self.distiller.get_recent_insights(20)

        # Filter for security/alert insights
        security_insights = [
            i for i in insights
            if i.actionability == "alert" or i.event_class == "Security_Event"
        ]

        if not security_insights:
            return

        try:
            existing = []
            if SECURITY_LOG.exists():
                try:
                    existing = json.loads(SECURITY_LOG.read_text())
                except Exception:
                    existing = []

            # Add new insights
            for insight in security_insights:
                entry = insight.to_dict()
                # Avoid duplicates
                if entry not in existing[-50:]:
                    existing.append(entry)

            # Keep only recent entries (last 100)
            existing = existing[-100:]

            SECURITY_LOG.write_text(json.dumps(existing, indent=2))
        except Exception as e:
            LOG.error(f"Failed to write security log: {e}")

    def get_summary(self) -> dict:
        """Get summary for Frank's context."""
        insights = self.distiller.get_recent_insights(10)

        summary = {
            "timestamp": datetime.now().isoformat(),
            "total_fingerprints": len(self.distiller.fingerprints),
            "recent_insights": [i.to_dict() for i in insights],
            "gaming_mode": self.distiller.gaming_guard.is_gaming(),
            "alert_count": sum(1 for i in insights if i.actionability == "alert"),
            "system_health": self._assess_health(insights),
        }

        return summary

    def _assess_health(self, insights: List[SystemInsight]) -> str:
        """Assess overall system health based on recent insights."""
        if not insights:
            return "nominal"

        alert_count = sum(1 for i in insights if i.actionability == "alert")
        avg_confidence = sum(i.confidence for i in insights) / len(insights)

        if alert_count >= 3:
            return "degraded"
        elif alert_count >= 1:
            return "attention"
        elif avg_confidence < 0.4:
            return "uncertain"
        return "nominal"


class UOLGDaemon:
    """Main UOLG Daemon."""

    def __init__(self):
        self.distiller = LogDistiller()
        self.reader = LogStreamReader(self.distiller)
        self.emitter = InsightEmitter(self.distiller)
        self._stop_event = threading.Event()

    def start(self):
        """Start the UOLG daemon."""
        LOG.info("Starting Universal Omniscient Log Gateway (UOLG)")

        # Start streaming sources
        for layer_name, sources in LOG_SOURCES.items():
            for name, config in sources.items():
                if config["type"] == "stream":
                    self.reader.start_stream(name, config)

        # Main loop
        last_emit = 0
        last_cleanup = 0

        while not self._stop_event.is_set():
            try:
                now = time.time()

                # Poll file-based sources
                for layer_name, sources in LOG_SOURCES.items():
                    for name, config in sources.items():
                        if config["type"] == "file":
                            self.reader.poll_file(name, config)

                # Periodic emit
                if now - last_emit >= CONFIG["insight_emit_interval_sec"]:
                    self.emitter.emit_to_file()
                    self.emitter.emit_to_bridge()
                    last_emit = now

                # Periodic cleanup
                if now - last_cleanup >= 300:  # Every 5 minutes
                    self.distiller.cleanup_old_fingerprints()
                    last_cleanup = now

                time.sleep(CONFIG["poll_interval_sec"])

            except Exception as e:
                LOG.error(f"Main loop error: {e}")
                time.sleep(5)

        self.reader.stop()
        LOG.info("UOLG daemon stopped")

    def stop(self):
        """Stop the daemon."""
        self._stop_event.set()

    def get_status(self) -> dict:
        """Get daemon status."""
        return self.emitter.get_summary()


# Global instance
_daemon: Optional[UOLGDaemon] = None


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    global _daemon
    if _daemon:
        _daemon.stop()
    sys.exit(0)


def main():
    """Entry point."""
    global _daemon

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    import argparse
    parser = argparse.ArgumentParser(description="UOLG - Universal Omniscient Log Gateway")
    parser.add_argument("--status", action="store_true", help="Show status")
    parser.add_argument("--summary", action="store_true", help="Show summary")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon")
    args = parser.parse_args()

    if args.status or args.summary:
        # Read security log
        if SECURITY_LOG.exists():
            try:
                data = json.loads(SECURITY_LOG.read_text())
                print(f"Security Log Entries: {len(data)}")
                for entry in data[-5:]:
                    print(f"  [{entry['time']}] {entry['entity']}: {entry['event_class']}")
            except Exception as e:
                print(f"Error reading security log: {e}")
        else:
            print("No security log yet")
        return

    # Run daemon
    _daemon = UOLGDaemon()
    _daemon.start()


if __name__ == "__main__":
    main()
