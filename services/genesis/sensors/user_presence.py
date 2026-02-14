#!/usr/bin/env python3
"""
User Presence Sensor - Detects user activity
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import subprocess
import os
import logging

from .base import BaseSensor
from ..core.wave import Wave

LOG = logging.getLogger("genesis.sensors.user")


class UserPresence(BaseSensor):
    """
    Senses user presence and activity:
    - Keyboard/mouse activity (via xprintidle)
    - Active window changes
    - Session state
    """

    def __init__(self):
        super().__init__("user_presence")
        self.last_idle_time: float = 0
        self.last_activity_time: datetime = datetime.now()
        self.consecutive_idle_reads: int = 0

    def sense(self) -> List[Wave]:
        """Generate waves based on user presence."""
        waves = []

        try:
            idle_seconds = self._get_idle_time()

            # User very active (< 30 seconds idle)
            if idle_seconds < 30:
                self.last_activity_time = datetime.now()
                self.consecutive_idle_reads = 0

                # Active user = suppress exploration urges
                # (don't bother user while working)
                waves.append(Wave(
                    target_field="satisfaction",  # User is engaged
                    amplitude=0.1,
                    decay=0.02,
                    source=self.name,
                    metadata={"user_active": True},
                ))

            # User somewhat idle (1-5 minutes)
            elif 60 <= idle_seconds < 300:
                self.consecutive_idle_reads += 1

                # Growing opportunity for interaction
                waves.append(Wave(
                    target_field="boredom",
                    amplitude=0.15 * min(1.0, idle_seconds / 300),
                    decay=0.03,
                    source=self.name,
                    metadata={"idle_seconds": idle_seconds},
                ))

            # User idle for a while (5-15 minutes)
            elif 300 <= idle_seconds < 900:
                self.consecutive_idle_reads += 1

                # Good time for self-improvement
                waves.append(Wave(
                    target_field="boredom",
                    amplitude=0.3,
                    decay=0.02,
                    source=self.name,
                    metadata={"idle_seconds": idle_seconds},
                ))

                # Also drive to do something
                waves.append(Wave(
                    target_field="drive",
                    amplitude=0.25,
                    decay=0.03,
                    source=self.name,
                ))

                # Curiosity to explore
                waves.append(Wave(
                    target_field="curiosity",
                    amplitude=0.2,
                    decay=0.02,
                    source=self.name,
                ))

            # User very idle (> 15 minutes) - perfect time
            elif idle_seconds >= 900:
                # Strong signals for activity
                waves.append(Wave(
                    target_field="boredom",
                    amplitude=0.4,
                    decay=0.01,
                    source=self.name,
                    metadata={"idle_seconds": idle_seconds, "perfect_timing": True},
                ))

                waves.append(Wave(
                    target_field="drive",
                    amplitude=0.35,
                    decay=0.02,
                    source=self.name,
                ))

                waves.append(Wave(
                    target_field="curiosity",
                    amplitude=0.3,
                    decay=0.02,
                    source=self.name,
                ))

            self.last_idle_time = idle_seconds

        except Exception as e:
            LOG.warning(f"User presence sensing error: {e}")

        return waves

    def _get_idle_time(self) -> float:
        """Get user idle time in seconds."""
        try:
            # Try xprintidle first
            result = subprocess.run(
                ["xprintidle"],
                capture_output=True,
                text=True,
                timeout=2,
                env={**os.environ, "DISPLAY": ":0"}
            )
            if result.returncode == 0:
                return int(result.stdout.strip()) / 1000.0  # ms to seconds
        except Exception:
            pass

        # Fallback: check /dev/input timestamps
        try:
            import glob
            input_devices = glob.glob("/dev/input/event*")
            newest = 0
            for dev in input_devices:
                try:
                    stat = os.stat(dev)
                    newest = max(newest, stat.st_atime)
                except:
                    continue
            if newest > 0:
                return datetime.now().timestamp() - newest
        except Exception:
            pass

        # Ultimate fallback
        return (datetime.now() - self.last_activity_time).total_seconds()

    def is_user_active(self) -> bool:
        """Check if user is currently active."""
        return self.last_idle_time < 60

    def is_user_receptive(self) -> bool:
        """Check if user might be receptive to interaction."""
        # Idle but not too long (might have left)
        return 300 <= self.last_idle_time <= 3600

    def get_idle_seconds(self) -> float:
        """Get current idle time."""
        return self._get_idle_time()
