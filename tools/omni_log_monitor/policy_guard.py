#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UOLG Policy Guard

Enforces mode and security rules for the log monitoring system.

Key responsibilities:
- Gaming mode protection (disable intrusive methods)
- Resource limits enforcement
- Privacy safeguards
- Intrusion prevention for anti-cheat systems
"""

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional, Set

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s [PolicyGuard]: %(message)s',
)
LOG = logging.getLogger("policy_guard")

# Paths
try:
    from config.paths import get_temp as _pg_get_temp
    GAMING_STATE_FILE = _pg_get_temp("gaming_mode_state.json")
    POLICY_STATE_FILE = _pg_get_temp("uolg_policy_state.json")
except ImportError:
    import tempfile as _pg_tempfile
    _pg_temp_dir = Path(_pg_tempfile.gettempdir()) / "frank"
    _pg_temp_dir.mkdir(parents=True, exist_ok=True)
    GAMING_STATE_FILE = _pg_temp_dir / "gaming_mode_state.json"
    POLICY_STATE_FILE = _pg_temp_dir / "uolg_policy_state.json"


class OperationMode(Enum):
    """UOLG operation modes."""
    NORMAL = "normal"           # Full capabilities
    GAMING = "gaming"           # Minimal, passive only
    FORENSIC = "forensic"       # Temporary intrusive inspection
    DISABLED = "disabled"       # Complete shutdown


@dataclass
class PolicyState:
    """Current policy enforcement state."""
    mode: OperationMode
    gaming_active: bool
    intrusive_allowed: bool
    forensic_deadline: Optional[datetime]
    blocked_operations: Set[str]
    resource_limit_mb: int


class AntiCheatDetector:
    """
    Detects running anti-cheat systems.

    When detected, UOLG must:
    - Disable all intrusive methods (ptrace, strace)
    - Only use passive log sources
    - Avoid suspicious syscalls
    """

    # Known anti-cheat process names
    ANTI_CHEAT_PATTERNS = [
        r"EasyAntiCheat",
        r"BattlEye",
        r"Vanguard",
        r"vgc\.exe",
        r"EAC",
        r"nProtect",
        r"PunkBuster",
        r"FairFight",
        r"XIGNCODE",
        r"GameGuard",
        r"vac",
        r"steam.*guard",
    ]

    def __init__(self):
        self._cached_result = False
        self._last_check = 0
        self._check_interval = 10.0  # Check every 10 seconds
        self._patterns = [re.compile(p, re.I) for p in self.ANTI_CHEAT_PATTERNS]

    def is_anti_cheat_running(self) -> bool:
        """Check if any anti-cheat is running."""
        now = time.time()
        if now - self._last_check < self._check_interval:
            return self._cached_result

        self._last_check = now

        try:
            # Get process list
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True,
                timeout=5
            )

            for line in result.stdout.split("\n"):
                for pattern in self._patterns:
                    if pattern.search(line):
                        LOG.warning(f"Anti-cheat detected: {pattern.pattern}")
                        self._cached_result = True
                        return True

            self._cached_result = False
            return False

        except Exception as e:
            LOG.error(f"Anti-cheat detection error: {e}")
            # Fail safe - assume anti-cheat present
            return True


class ResourceMonitor:
    """Monitors UOLG resource usage."""

    def __init__(self, limit_mb: int = 150):
        self.limit_mb = limit_mb
        self._warning_threshold = 0.8

    def get_memory_usage_mb(self) -> float:
        """Get current memory usage in MB."""
        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            return usage.ru_maxrss / 1024  # Convert KB to MB
        except Exception:
            return 0

    def check_limits(self) -> Tuple[bool, str]:
        """Check if within resource limits."""
        usage = self.get_memory_usage_mb()

        if usage > self.limit_mb:
            return False, f"Memory limit exceeded: {usage:.1f}MB > {self.limit_mb}MB"

        if usage > self.limit_mb * self._warning_threshold:
            return True, f"Memory warning: {usage:.1f}MB approaching limit"

        return True, f"Memory OK: {usage:.1f}MB"


class PrivacyFilter:
    """
    Filters sensitive information from logs.

    Ensures no personal data leaks into stored insights.
    """

    # Patterns to redact
    REDACT_PATTERNS = [
        (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), '[EMAIL]'),
        (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'), '[IP]'),
        (re.compile(r'/home/[^/\s]+'), '/home/[USER]'),
        (re.compile(r'user[_\s]?(?:name|id)?[=:\s]+\S+', re.I), 'user=[REDACTED]'),
        (re.compile(r'pass(?:word)?[=:\s]+\S+', re.I), 'password=[REDACTED]'),
        (re.compile(r'token[=:\s]+\S+', re.I), 'token=[REDACTED]'),
        (re.compile(r'key[=:\s]+\S+', re.I), 'key=[REDACTED]'),
        (re.compile(r'secret[=:\s]+\S+', re.I), 'secret=[REDACTED]'),
    ]

    def filter(self, text: str) -> str:
        """Redact sensitive information from text."""
        for pattern, replacement in self.REDACT_PATTERNS:
            text = pattern.sub(replacement, text)
        return text


class PolicyGuard:
    """
    Main policy enforcement engine.

    Enforces:
    - Gaming mode restrictions
    - Resource limits
    - Privacy safeguards
    - Intrusive inspection rules
    """

    # Operations that require special permission
    INTRUSIVE_OPERATIONS = {
        "ptrace",
        "strace",
        "syscall_trace",
        "memory_read",
        "process_attach",
    }

    # Operations allowed in gaming mode
    GAMING_ALLOWED_OPERATIONS = {
        "read_syslog",
        "read_auth_log",
        "read_kern_log",
        "journalctl_passive",
    }

    def __init__(self):
        self.anti_cheat = AntiCheatDetector()
        self.resource_monitor = ResourceMonitor()
        self.privacy_filter = PrivacyFilter()
        self._state = PolicyState(
            mode=OperationMode.NORMAL,
            gaming_active=False,
            intrusive_allowed=True,
            forensic_deadline=None,
            blocked_operations=set(),
            resource_limit_mb=150,
        )
        self._lock = threading.Lock()
        self._load_state()

    def _load_state(self):
        """Load policy state from disk."""
        try:
            if POLICY_STATE_FILE.exists():
                data = json.loads(POLICY_STATE_FILE.read_text())
                self._state.mode = OperationMode(data.get("mode", "normal"))
                self._state.gaming_active = data.get("gaming_active", False)
        except Exception:
            pass

    def _save_state(self):
        """Save policy state to disk."""
        try:
            data = {
                "mode": self._state.mode.value,
                "gaming_active": self._state.gaming_active,
                "timestamp": datetime.now().isoformat(),
            }
            POLICY_STATE_FILE.write_text(json.dumps(data, indent=2))
        except Exception as e:
            LOG.error(f"Failed to save policy state: {e}")

    def update_mode(self):
        """Update operation mode based on current conditions."""
        with self._lock:
            # Check gaming state
            try:
                if GAMING_STATE_FILE.exists():
                    data = json.loads(GAMING_STATE_FILE.read_text())
                    self._state.gaming_active = data.get("active", False)
            except Exception:
                pass

            # Check anti-cheat
            anti_cheat_running = self.anti_cheat.is_anti_cheat_running()

            # Determine mode
            if self._state.gaming_active or anti_cheat_running:
                self._state.mode = OperationMode.GAMING
                self._state.intrusive_allowed = False
                self._state.blocked_operations = (
                    self.INTRUSIVE_OPERATIONS |
                    (set() if not anti_cheat_running else {"all_active"})
                )
            elif self._state.forensic_deadline and datetime.now() < self._state.forensic_deadline:
                self._state.mode = OperationMode.FORENSIC
                self._state.intrusive_allowed = True
                self._state.blocked_operations = set()
            else:
                self._state.mode = OperationMode.NORMAL
                self._state.intrusive_allowed = False
                self._state.forensic_deadline = None
                self._state.blocked_operations = self.INTRUSIVE_OPERATIONS

            self._save_state()

    def is_operation_allowed(self, operation: str) -> Tuple[bool, str]:
        """
        Check if an operation is allowed under current policy.

        Returns (allowed, reason).
        """
        self.update_mode()

        with self._lock:
            # Check resource limits
            ok, msg = self.resource_monitor.check_limits()
            if not ok:
                return False, msg

            # Gaming mode - very restricted
            if self._state.mode == OperationMode.GAMING:
                if operation not in self.GAMING_ALLOWED_OPERATIONS:
                    return False, f"Operation '{operation}' blocked in gaming mode"
                return True, "Allowed (gaming mode passive)"

            # Normal mode
            if operation in self.INTRUSIVE_OPERATIONS:
                if not self._state.intrusive_allowed:
                    return False, f"Intrusive operation '{operation}' requires forensic mode"
                return True, "Allowed (forensic mode)"

            return True, "Allowed"

    def request_forensic_mode(self, duration_sec: int = 5) -> Tuple[bool, str]:
        """
        Request temporary forensic mode for intrusive inspection.

        Max duration: 5 seconds (as per spec).
        """
        if duration_sec > 5:
            return False, "Forensic mode duration cannot exceed 5 seconds"

        self.update_mode()

        with self._lock:
            if self._state.mode == OperationMode.GAMING:
                return False, "Forensic mode not allowed during gaming"

            if self.anti_cheat.is_anti_cheat_running():
                return False, "Forensic mode blocked: anti-cheat detected"

            self._state.forensic_deadline = datetime.now() + timedelta(seconds=duration_sec)
            self._state.intrusive_allowed = True
            self._state.mode = OperationMode.FORENSIC

            LOG.warning(f"Forensic mode enabled for {duration_sec} seconds")
            self._save_state()

            return True, f"Forensic mode enabled until {self._state.forensic_deadline}"

    def filter_log_content(self, content: str) -> str:
        """Filter sensitive content from logs."""
        return self.privacy_filter.filter(content)

    def get_status(self) -> dict:
        """Get current policy status."""
        self.update_mode()

        with self._lock:
            ok, resource_msg = self.resource_monitor.check_limits()

            return {
                "mode": self._state.mode.value,
                "gaming_active": self._state.gaming_active,
                "intrusive_allowed": self._state.intrusive_allowed,
                "forensic_deadline": (
                    self._state.forensic_deadline.isoformat()
                    if self._state.forensic_deadline else None
                ),
                "blocked_operations": list(self._state.blocked_operations),
                "resource_status": resource_msg,
                "anti_cheat_detected": self.anti_cheat.is_anti_cheat_running(),
            }

    def enforce_shutdown(self, reason: str):
        """Force shutdown of UOLG (emergency measure)."""
        LOG.critical(f"Policy guard forcing shutdown: {reason}")
        with self._lock:
            self._state.mode = OperationMode.DISABLED
            self._save_state()

        # Signal main process to stop
        import signal
        os.kill(os.getpid(), signal.SIGTERM)


# Singleton instance
_guard: Optional[PolicyGuard] = None


def get_guard() -> PolicyGuard:
    """Get the singleton policy guard instance."""
    global _guard
    if _guard is None:
        _guard = PolicyGuard()
    return _guard


# Convenience functions
def is_allowed(operation: str) -> bool:
    """Check if operation is allowed."""
    allowed, _ = get_guard().is_operation_allowed(operation)
    return allowed


def filter_content(content: str) -> str:
    """Filter sensitive content."""
    return get_guard().filter_log_content(content)


def request_forensic(duration: int = 5) -> bool:
    """Request forensic mode."""
    ok, _ = get_guard().request_forensic_mode(duration)
    return ok


# Import for timedelta
from datetime import timedelta


def main():
    """Entry point for CLI usage."""
    import argparse
    parser = argparse.ArgumentParser(description="UOLG Policy Guard")
    parser.add_argument("--status", action="store_true", help="Show status")
    parser.add_argument("--check", type=str, help="Check if operation allowed")
    parser.add_argument("--forensic", type=int, help="Request forensic mode (seconds)")
    args = parser.parse_args()

    guard = get_guard()

    if args.status:
        status = guard.get_status()
        print(json.dumps(status, indent=2))
        return

    if args.check:
        allowed, reason = guard.is_operation_allowed(args.check)
        print(f"Operation '{args.check}': {'ALLOWED' if allowed else 'BLOCKED'}")
        print(f"Reason: {reason}")
        return

    if args.forensic:
        ok, msg = guard.request_forensic_mode(args.forensic)
        print(f"Forensic mode: {'GRANTED' if ok else 'DENIED'}")
        print(f"Message: {msg}")
        return

    # Default: show status
    status = guard.get_status()
    print(f"Mode: {status['mode']}")
    print(f"Gaming Active: {status['gaming_active']}")
    print(f"Intrusive Allowed: {status['intrusive_allowed']}")
    print(f"Resource: {status['resource_status']}")


if __name__ == "__main__":
    main()
