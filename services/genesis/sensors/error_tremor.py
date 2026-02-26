#!/usr/bin/env python3
"""
Error Tremor Sensor - Feels disturbances in the system

Enhanced with:
- Dynamic log discovery (scans logs/ directory)
- Full Python traceback parsing (file, line, function, exception)
- Error frequency tracking for recurring issues
- Concrete observations with specific targets
"""

from typing import List, Dict, Any
from datetime import datetime, timedelta
from pathlib import Path
import re
import logging

from .base import BaseSensor
from ..core.wave import Wave

LOG = logging.getLogger("genesis.sensors.error")

try:
    from config.paths import AICORE_LOG as _ERROR_LOG_DIR
    LOG_DIR = _ERROR_LOG_DIR
except ImportError:
    LOG_DIR = Path.home() / ".local" / "share" / "frank" / "logs"

# Regex for Python traceback frame lines
_TB_FILE_RE = re.compile(r'^\s+File "([^"]+)", line (\d+), in (\S+)')
# Regex for exception lines (e.g. "ValueError: something went wrong")
_EXCEPTION_RE = re.compile(r'^(\w+(?:\.\w+)*(?:Error|Exception|Warning|Interrupt))\s*:\s*(.+)')

# ── Noise Filters ────────────────────────────────────────────────
# Log files to skip entirely (removed/irrelevant components)
_SKIP_LOG_FILES = {
    "live_wallpaper.log",
    "neural_cybercore.log",
    "wallpaper_events.log",
}

# Substrings in log paths — skip any log whose path contains these
_SKIP_PATH_FRAGMENTS = {"live_wallpaper"}

# Lines matching ANY of these regexes are noise, not actionable bugs
_NOISE_PATTERNS = [
    re.compile(r'Gtk-CRITICAL', re.I),
    re.compile(r'Gtk-WARNING', re.I),
    re.compile(r'Gdk-CRITICAL', re.I),
    re.compile(r'Gdk-WARNING', re.I),
    re.compile(r'GLib-CRITICAL', re.I),
    re.compile(r'GLib-GObject-WARNING', re.I),
    re.compile(r"gtk_widget_measure.*assertion.*failed"),
    re.compile(r"timed out after \d+ sec"),            # systemctl timeouts
    re.compile(r"Max restarts.*reached, giving up"),   # watchdog restart spam
    re.compile(r"Restart command succeeded but service not active"),
    re.compile(r"DeprecationWarning"),
    re.compile(r"ResourceWarning"),
    re.compile(r"RuntimeWarning.*found in sys\.modules"),
]

# Traceback file paths — skip tracebacks originating from removed code
_SKIP_TB_PATHS = {"live_wallpaper", "neural_cybercore"}


class ErrorTremor(BaseSensor):
    """
    Senses errors and anomalies in logs.
    Dynamically discovers log files and parses full tracebacks.
    """

    def __init__(self):
        super().__init__("error_tremor")

        # Track what we've read per log file
        self.last_positions: Dict[str, int] = {}

        # Structured error records
        self.recent_errors: List[Dict] = []
        self.error_count_window: List[datetime] = []

        # Frequency tracking: "ExceptionType:file" → list of timestamps
        self.error_frequency: Dict[str, List[datetime]] = {}

        # Error patterns (for simple line matching when not in a traceback)
        self.error_patterns = [
            (re.compile(r'ERROR', re.I), 1.0),
            (re.compile(r'CRITICAL', re.I), 1.5),
            (re.compile(r'Exception', re.I), 0.8),
            (re.compile(r'Traceback', re.I), 1.0),
            (re.compile(r'failed', re.I), 0.5),
            (re.compile(r'timeout', re.I), 0.6),
            (re.compile(r'connection refused', re.I), 0.7),
        ]

        # Cache discovered log paths (refreshed periodically)
        self._known_logs: List[Path] = []
        self._logs_refreshed_at: int = 0

    def sense(self) -> List[Wave]:
        """Generate waves based on error activity."""
        waves = []

        try:
            self._refresh_log_list()
            new_errors = self._scan_logs()
            error_rate = self._calculate_error_rate()

            # High error rate = concern + frustration
            if error_rate > 0.5:
                waves.append(Wave(
                    target_field="concern",
                    amplitude=min(0.6, error_rate * 0.3),
                    decay=0.1,
                    source=self.name,
                    metadata={"error_rate": error_rate, "recent_errors": len(new_errors)},
                ))
                waves.append(Wave(
                    target_field="frustration",
                    amplitude=min(0.4, error_rate * 0.2),
                    decay=0.08,
                    source=self.name,
                ))

            # Critical errors = strong concern
            critical_errors = [e for e in new_errors if e.get("severity", 0) > 1.0]
            if critical_errors:
                waves.append(Wave(
                    target_field="concern",
                    amplitude=0.5,
                    decay=0.15,
                    source=self.name,
                    metadata={"critical_errors": len(critical_errors)},
                ))

                try:
                    from tools.vcb_bridge import capture_error_screenshot
                    sources = set(e.get("source", "?") for e in critical_errors[:3])
                    capture_error_screenshot(
                        f"Genesis: {len(critical_errors)} critical errors in {', '.join(sources)}"
                    )
                except Exception:
                    pass

            # No errors for a while = satisfaction
            if error_rate == 0 and not new_errors:
                time_since_error = self._time_since_last_error()
                if time_since_error > 300:
                    waves.append(Wave(
                        target_field="satisfaction",
                        amplitude=0.2,
                        decay=0.01,
                        source=self.name,
                        metadata={"error_free_seconds": time_since_error},
                    ))

        except Exception as e:
            LOG.warning(f"Error tremor sensing error: {e}")

        return waves

    def get_observations(self) -> List[Dict[str, Any]]:
        """
        Concrete observations from recurring error patterns.
        Each recurring error becomes a fix candidate with specific target.
        """
        observations = []
        now = datetime.now()
        cutoff = now - timedelta(hours=1)

        # Clean old frequency entries
        for key in list(self.error_frequency):
            self.error_frequency[key] = [
                t for t in self.error_frequency[key] if t > cutoff
            ]
            if not self.error_frequency[key]:
                del self.error_frequency[key]

        # Recurring errors (>= 3 in last hour) become fix observations
        for freq_key, timestamps in self.error_frequency.items():
            count = len(timestamps)
            if count < 3:
                continue

            parts = freq_key.split(":", 1)
            exc_type = parts[0]
            location = parts[1] if len(parts) > 1 else "unknown"

            # Skip observations from removed/noisy sources
            if any(frag in location for frag in _SKIP_PATH_FRAGMENTS | _SKIP_TB_PATHS):
                continue
            if any(np.search(freq_key) for np in _NOISE_PATTERNS):
                continue

            # Choose approach based on error type
            if any(kw in exc_type.lower() for kw in ("timeout", "connection", "socket")):
                approach = "config_change"
            else:
                approach = "refactoring"

            observations.append({
                "type": "fix",
                "target": f"{exc_type} in {location}",
                "approach": approach,
                "origin": "error_analysis",
                "strength": min(1.0, count / 10),
                "novelty": 0.4,
                "risk": 0.3,
                "impact": 0.7,
            })

        return observations

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _refresh_log_list(self):
        """Discover log files in the logs directory (every 30 ticks)."""
        if self._known_logs and (self.sense_count - self._logs_refreshed_at) < 30:
            return
        try:
            logs = set()
            for search_dir in [LOG_DIR, LOG_DIR / "genesis"]:
                if search_dir.is_dir():
                    for p in search_dir.glob("*.log"):
                        if p.is_file():
                            logs.add(p)
            self._known_logs = sorted(logs)
            self._logs_refreshed_at = self.sense_count
        except Exception as e:
            LOG.debug(f"Log discovery error: {e}")

    def _scan_logs(self) -> List[Dict]:
        """Scan all known log files for new errors."""
        new_errors = []

        for log_path in self._known_logs:
            if not log_path.exists():
                continue

            # Skip excluded log files
            if log_path.name in _SKIP_LOG_FILES:
                continue
            if any(frag in str(log_path) for frag in _SKIP_PATH_FRAGMENTS):
                continue

            try:
                path_key = str(log_path)
                last_pos = self.last_positions.get(path_key, 0)

                with open(log_path, 'r', errors='replace') as f:
                    f.seek(0, 2)
                    file_size = f.tell()

                    if file_size < last_pos:
                        last_pos = 0  # File was rotated

                    f.seek(last_pos)
                    new_content = f.read()
                    self.last_positions[path_key] = f.tell()

                lines = new_content.split('\n')
                errors = self._parse_errors(lines, log_path)
                new_errors.extend(errors)

            except Exception as e:
                LOG.debug(f"Error scanning {log_path}: {e}")

        # Trim recent errors (1 hour window)
        cutoff = datetime.now() - timedelta(hours=1)
        self.recent_errors = [e for e in self.recent_errors if e["timestamp"] > cutoff]

        return new_errors

    def _parse_errors(self, lines: List[str], log_path: Path) -> List[Dict]:
        """
        Parse lines for errors, including full traceback extraction.
        """
        errors = []
        i = 0
        while i < len(lines):
            line = lines[i]

            # Skip noise lines (Gtk-CRITICAL, systemctl timeouts, etc.)
            if any(np.search(line) for np in _NOISE_PATTERNS):
                i += 1
                continue

            # Check for "Traceback (most recent call last):" to start TB capture
            if "Traceback (most recent call last)" in line:
                tb_error = self._extract_traceback(lines, i, log_path)
                if tb_error:
                    # Skip tracebacks from removed code
                    tb_file = tb_error.get("tb_file", "")
                    if any(frag in tb_file for frag in _SKIP_TB_PATHS):
                        i += tb_error.get("_lines_consumed", 1)
                        continue

                    errors.append(tb_error)
                    self.recent_errors.append(tb_error)
                    self.error_count_window.append(datetime.now())
                    # Track frequency
                    freq_key = f"{tb_error.get('exception_type', 'Unknown')}:{tb_error.get('tb_file', 'unknown')}"
                    self.error_frequency.setdefault(freq_key, []).append(datetime.now())
                    # Skip past traceback lines
                    i += tb_error.get("_lines_consumed", 1)
                    continue

            # Fallback: simple pattern matching for non-traceback errors
            for pattern, severity in self.error_patterns:
                if pattern.search(line):
                    # Extract a stable error signature from the line
                    msg_sig = self._extract_error_signature(line)
                    error = {
                        "timestamp": datetime.now(),
                        "source": log_path.name,
                        "line": line[:200],
                        "type": pattern.pattern,
                        "severity": severity,
                        "signature": msg_sig,
                    }
                    errors.append(error)
                    self.recent_errors.append(error)
                    self.error_count_window.append(datetime.now())
                    # Track frequency for simple errors too
                    freq_key = f"{pattern.pattern}:{log_path.name}:{msg_sig}"
                    self.error_frequency.setdefault(freq_key, []).append(datetime.now())
                    break

            i += 1

        return errors

    def _extract_traceback(self, lines: List[str], start: int, log_path: Path) -> Dict:
        """
        Extract a full Python traceback starting at `start`.
        Returns a structured error record with file, line, function, exception.
        """
        tb_frames = []
        j = start + 1
        exception_type = "Unknown"
        exception_msg = ""

        while j < len(lines):
            line = lines[j]
            stripped = line.strip()

            # Traceback frame line: '  File "...", line N, in func'
            m = _TB_FILE_RE.match(line)
            if m:
                tb_frames.append({
                    "file": m.group(1),
                    "line": int(m.group(2)),
                    "function": m.group(3),
                })
                j += 1
                # Skip the source-code line that follows
                if j < len(lines) and lines[j].startswith("    "):
                    j += 1
                continue

            # Exception line (end of traceback)
            m = _EXCEPTION_RE.match(stripped)
            if m:
                exception_type = m.group(1)
                exception_msg = m.group(2)[:200]
                j += 1
                break

            # If we hit an empty line or something unexpected, stop
            if not stripped or (not stripped.startswith("File") and not stripped.startswith("During")):
                break

            j += 1

        # Use last frame as the location
        last_frame = tb_frames[-1] if tb_frames else {}

        return {
            "timestamp": datetime.now(),
            "source": log_path.name,
            "severity": 1.0,
            "type": "traceback",
            "exception_type": exception_type,
            "exception_msg": exception_msg,
            "tb_file": last_frame.get("file", "unknown"),
            "tb_line": last_frame.get("line", 0),
            "tb_function": last_frame.get("function", "unknown"),
            "tb_frames": tb_frames[-5:],  # Keep last 5 frames
            "line": f"{exception_type}: {exception_msg}",
            "_lines_consumed": j - start,
        }

    @staticmethod
    def _extract_error_signature(line: str) -> str:
        """
        Extract a stable signature from an error line.
        Strips timestamps and variable data to group similar errors.
        """
        # Remove common timestamp prefixes like [2026-02-09 16:15:14,305]
        sig = re.sub(r'\[\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[,.\d]*\]\s*', '', line)
        # Remove numeric IDs, PIDs, etc.
        sig = re.sub(r'\b\d{4,}\b', 'N', sig)
        # Remove hex addresses
        sig = re.sub(r'0x[0-9a-fA-F]+', '0xN', sig)
        # Collapse whitespace
        sig = ' '.join(sig.split())
        # Truncate for stable grouping
        return sig[:120]

    def _calculate_error_rate(self) -> float:
        """Calculate errors per minute in 5-minute window."""
        cutoff = datetime.now() - timedelta(minutes=5)
        self.error_count_window = [t for t in self.error_count_window if t > cutoff]

        if not self.error_count_window:
            return 0.0

        return len(self.error_count_window) / 5.0

    def _time_since_last_error(self) -> float:
        """Get seconds since last error."""
        if not self.recent_errors:
            return 3600

        last_error = max(e["timestamp"] for e in self.recent_errors)
        return (datetime.now() - last_error).total_seconds()
