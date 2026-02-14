#!/usr/bin/env python3
"""
Base Sensor Class
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any
from datetime import datetime
import logging

from ..core.wave import Wave

LOG = logging.getLogger("genesis.sensors")


class BaseSensor(ABC):
    """
    Base class for all sensors.

    Sensors are PASSIVE - they observe and emit waves.
    They don't make decisions or take actions.
    """

    def __init__(self, name: str):
        self.name = name
        self.last_sense_time: datetime = None
        self.sense_count: int = 0
        self.total_waves_emitted: int = 0

    @abstractmethod
    def sense(self) -> List[Wave]:
        """
        Perform sensing and return waves to emit.
        Must be implemented by subclasses.
        """
        pass

    def get_observations(self) -> List[Dict[str, Any]]:
        """
        Get observations that could become seeds in the soup.
        Override if sensor can generate seed candidates.
        """
        return []

    def tick(self) -> List[Wave]:
        """
        Perform a sense tick and return waves.
        """
        self.last_sense_time = datetime.now()
        self.sense_count += 1

        waves = self.sense()
        self.total_waves_emitted += len(waves)

        return waves

    def get_stats(self) -> Dict:
        """Get sensor statistics."""
        return {
            "name": self.name,
            "sense_count": self.sense_count,
            "total_waves": self.total_waves_emitted,
            "last_sense": self.last_sense_time.isoformat() if self.last_sense_time else None,
        }
