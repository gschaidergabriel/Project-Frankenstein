# Room content libraries for Frank's solo activity rooms

from .philosophy import PHILOSOPHY_LIBRARY, get_random_passage
from .literature import ART_LIBRARY, get_random_work, get_center_work

__all__ = [
    "PHILOSOPHY_LIBRARY",
    "ART_LIBRARY",
    "get_random_passage",
    "get_random_work",
    "get_center_work",
]
