#!/usr/bin/env python3
"""
F.A.S. Activity Detector
Determines if the user is receptive to a popup.
"""

import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Tuple, Optional
import json


class ActivityDetector:
    """
    Detects user activity patterns to find the optimal moment for popup.
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.mouse_idle_threshold = self.config.get("mouse_idle_threshold_sec", 120)
        self.cpu_threshold = self.config.get("cpu_busy_threshold", 50)
        self.preferred_hours = self.config.get("preferred_hours", [9, 10, 11, 14, 15, 16, 17])
        self.avoid_hours = self.config.get("avoid_hours", [0, 1, 2, 3, 4, 5, 6, 22, 23])

        # Cache for expensive checks
        self._last_check_time = 0
        self._last_result = (False, "Not checked")
        self._cache_duration = 10  # seconds

    def is_user_receptive(self) -> Tuple[bool, str]:
        """
        Check if user is likely receptive to a popup.
        Returns (is_receptive, reason).
        """
        # Use cached result if recent
        now = time.time()
        if now - self._last_check_time < self._cache_duration:
            return self._last_result

        checks = [
            ("mouse_active", self._is_mouse_active_recently()),
            ("no_fullscreen", self._no_fullscreen_app()),
            ("no_video", self._no_video_playing()),
            ("cpu_ok", self._cpu_not_busy()),
            ("good_hour", self._is_good_hour()),
            ("no_gaming", self._no_gaming_mode()),
        ]

        failed_checks = [(name, result) for name, result in checks if not result]

        if failed_checks:
            reason = f"Failed: {', '.join(name for name, _ in failed_checks)}"
            self._last_result = (False, reason)
        else:
            self._last_result = (True, "User appears receptive")

        self._last_check_time = now
        return self._last_result

    def _is_mouse_active_recently(self) -> bool:
        """Check if mouse was active in last N seconds."""
        try:
            # Use xprintidle to get idle time in milliseconds
            result = subprocess.run(
                ['xprintidle'],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                idle_ms = int(result.stdout.strip())
                idle_sec = idle_ms / 1000
                # User is active if idle time is reasonable (not too long, not 0)
                return 1 < idle_sec < self.mouse_idle_threshold
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            pass

        # Fallback: assume active if we can't check
        return True

    def _no_fullscreen_app(self) -> bool:
        """Check if no fullscreen window is active."""
        try:
            # Get active window
            result = subprocess.run(
                ['xdotool', 'getactivewindow'],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode != 0:
                return True

            window_id = result.stdout.strip()

            # Check window state for fullscreen
            result = subprocess.run(
                ['xprop', '-id', window_id, '_NET_WM_STATE'],
                capture_output=True,
                text=True,
                timeout=2
            )

            if '_NET_WM_STATE_FULLSCREEN' in result.stdout:
                return False

            return True

        except (subprocess.TimeoutExpired, FileNotFoundError):
            # If we can't check, assume no fullscreen
            return True

    def _no_video_playing(self) -> bool:
        """Check if no video is being played."""
        # Check for known video players with active playback
        video_players = [
            'vlc', 'mpv', 'totem', 'celluloid',
            'firefox', 'chromium', 'chrome',  # Could be playing video
        ]

        try:
            # Check PulseAudio sink inputs for active streams
            result = subprocess.run(
                ['pactl', 'list', 'sink-inputs'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                output = result.stdout.lower()
                # Look for media-related sinks
                if 'state: running' in output:
                    # Check if it's a video-like application
                    for player in video_players:
                        if player in output:
                            # Could be playing video, but not certain
                            # Be conservative: assume not playing if CPU is low
                            return self._cpu_not_busy()

            return True

        except (subprocess.TimeoutExpired, FileNotFoundError):
            return True

    def _cpu_not_busy(self) -> bool:
        """Check if CPU usage is below threshold."""
        try:
            # Try psutil first
            import psutil
            cpu = psutil.cpu_percent(interval=0.5)
            return cpu < self.cpu_threshold
        except ImportError:
            pass

        # Fallback to /proc/loadavg
        try:
            with open('/proc/loadavg') as f:
                load = float(f.read().split()[0])
                # Convert load to approximate percentage
                cpu_count = os.cpu_count() or 1
                cpu_percent = (load / cpu_count) * 100
                return cpu_percent < self.cpu_threshold
        except (OSError, ValueError):
            return True  # Assume CPU is OK if we can't check

    def _is_good_hour(self) -> bool:
        """Check if current hour is in preferred range."""
        current_hour = datetime.now().hour

        # Definitely avoid certain hours
        if current_hour in self.avoid_hours:
            return False

        # Prefer certain hours but don't require
        # During non-preferred hours, still allow if other conditions are met
        return True

    def _is_preferred_hour(self) -> bool:
        """Check if current hour is specifically preferred."""
        return datetime.now().hour in self.preferred_hours

    def _no_gaming_mode(self) -> bool:
        """Check if gaming mode is not active."""
        gaming_state_file = Path("/tmp/gaming_mode_state.json")
        try:
            if gaming_state_file.exists():
                data = json.loads(gaming_state_file.read_text())
                return not data.get("active", False)
        except (json.JSONDecodeError, OSError):
            pass  # File corrupt or unreadable - assume no gaming mode
        return True

    def get_optimal_wait_time(self) -> int:
        """
        Estimate seconds until user might be receptive.
        Returns 0 if user is currently receptive.
        """
        is_receptive, reason = self.is_user_receptive()

        if is_receptive:
            return 0

        # If in avoid hours, calculate time until good hour
        current_hour = datetime.now().hour
        if current_hour in self.avoid_hours:
            # Find next preferred hour
            for hour in sorted(self.preferred_hours):
                if hour > current_hour:
                    return (hour - current_hour) * 3600
            # Wrap to next day
            if self.preferred_hours:
                return (24 - current_hour + min(self.preferred_hours)) * 3600

        # For other conditions, suggest short wait
        return 300  # 5 minutes

    def get_activity_summary(self) -> dict:
        """Get summary of activity checks for debugging."""
        return {
            "mouse_active": self._is_mouse_active_recently(),
            "no_fullscreen": self._no_fullscreen_app(),
            "no_video": self._no_video_playing(),
            "cpu_ok": self._cpu_not_busy(),
            "good_hour": self._is_good_hour(),
            "preferred_hour": self._is_preferred_hour(),
            "no_gaming": self._no_gaming_mode(),
            "current_hour": datetime.now().hour,
        }


# Singleton
_detector: Optional[ActivityDetector] = None


def get_activity_detector() -> ActivityDetector:
    """Get or create activity detector singleton."""
    global _detector
    if _detector is None:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        from config.fas_popup_config import get_config
        _detector = ActivityDetector(get_config())
    return _detector
