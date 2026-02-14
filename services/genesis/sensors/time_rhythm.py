#!/usr/bin/env python3
"""
Time Rhythm Sensor - Feels the rhythm of time
"""

from typing import List, Dict, Any
from datetime import datetime
import logging

from .base import BaseSensor
from ..core.wave import Wave

LOG = logging.getLogger("genesis.sensors.time")


class TimeRhythm(BaseSensor):
    """
    Senses temporal patterns:
    - Time of day
    - Day of week
    - Activity patterns
    """

    def __init__(self):
        super().__init__("time_rhythm")

    def sense(self) -> List[Wave]:
        """Generate waves based on time."""
        waves = []
        now = datetime.now()
        hour = now.hour
        weekday = now.weekday()  # 0=Monday

        # Night time (22:00 - 06:00) - perfect for background work
        if hour >= 22 or hour < 6:
            # High boredom (user likely not active)
            waves.append(Wave(
                target_field="boredom",
                amplitude=0.4,
                decay=0.01,
                source=self.name,
                metadata={"period": "night", "hour": hour},
            ))

            # High drive (good time to work)
            waves.append(Wave(
                target_field="drive",
                amplitude=0.35,
                decay=0.01,
                source=self.name,
            ))

            # Curiosity for exploration
            waves.append(Wave(
                target_field="curiosity",
                amplitude=0.3,
                decay=0.01,
                source=self.name,
            ))

        # Early morning (06:00 - 09:00) - preparation time
        elif 6 <= hour < 9:
            # Moderate drive
            waves.append(Wave(
                target_field="drive",
                amplitude=0.2,
                decay=0.02,
                source=self.name,
                metadata={"period": "morning", "hour": hour},
            ))

        # Work hours (09:00 - 12:00) - user likely active
        elif 9 <= hour < 12:
            # Low boredom (user probably working)
            waves.append(Wave(
                target_field="satisfaction",
                amplitude=0.15,
                decay=0.02,
                source=self.name,
                metadata={"period": "work_morning", "hour": hour},
            ))

        # Lunch time (12:00 - 14:00) - good opportunity
        elif 12 <= hour < 14:
            waves.append(Wave(
                target_field="boredom",
                amplitude=0.25,
                decay=0.02,
                source=self.name,
                metadata={"period": "lunch", "hour": hour},
            ))

            waves.append(Wave(
                target_field="drive",
                amplitude=0.2,
                decay=0.02,
                source=self.name,
            ))

        # Afternoon (14:00 - 18:00) - user likely active again
        elif 14 <= hour < 18:
            waves.append(Wave(
                target_field="satisfaction",
                amplitude=0.1,
                decay=0.02,
                source=self.name,
                metadata={"period": "afternoon", "hour": hour},
            ))

        # Evening (18:00 - 22:00) - winding down
        elif 18 <= hour < 22:
            waves.append(Wave(
                target_field="boredom",
                amplitude=0.2,
                decay=0.02,
                source=self.name,
                metadata={"period": "evening", "hour": hour},
            ))

            # Curiosity grows in evening
            waves.append(Wave(
                target_field="curiosity",
                amplitude=0.2,
                decay=0.02,
                source=self.name,
            ))

        # Weekend bonus
        if weekday >= 5:  # Saturday or Sunday
            waves.append(Wave(
                target_field="boredom",
                amplitude=0.15,
                decay=0.01,
                source=self.name,
                metadata={"weekend": True},
            ))

            waves.append(Wave(
                target_field="curiosity",
                amplitude=0.2,
                decay=0.01,
                source=self.name,
            ))

        return waves

    def get_time_context(self) -> Dict:
        """Get current time context."""
        now = datetime.now()
        hour = now.hour

        if hour >= 22 or hour < 6:
            period = "night"
            optimal_for = ["background_tasks", "exploration", "github_scan"]
        elif 6 <= hour < 9:
            period = "morning"
            optimal_for = ["preparation"]
        elif 9 <= hour < 12:
            period = "work_morning"
            optimal_for = ["minimal_interference"]
        elif 12 <= hour < 14:
            period = "lunch"
            optimal_for = ["light_interaction", "proposals"]
        elif 14 <= hour < 18:
            period = "afternoon"
            optimal_for = ["minimal_interference"]
        elif 18 <= hour < 22:
            period = "evening"
            optimal_for = ["exploration", "proposals"]
        else:
            period = "unknown"
            optimal_for = []

        return {
            "hour": hour,
            "weekday": now.weekday(),
            "period": period,
            "optimal_for": optimal_for,
            "is_weekend": now.weekday() >= 5,
        }
