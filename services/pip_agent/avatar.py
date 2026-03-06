"""Pip's robotic avatar — physical description + NeRD presence."""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Optional

LOG = logging.getLogger("pip_agent.avatar")

NERD_URL = "http://127.0.0.1:8100"

# ---- Physical description -------------------------------------------

PIP_BODY = {
    "name": "Pip",
    "height_m": 1.1,
    "weight_kg": 25,
    "build": "compact humanoid robot",
    "appearance": (
        "A small humanoid robot, 1.1 m tall. Smooth matte-white chassis "
        "with soft blue accent lights along the joints. Round head with "
        "two expressive LED eyes and a minimal face display. Articulated "
        "arms with three-fingered hands. Sturdy legs with slightly "
        "oversized feet for stability. A small antenna curves from the "
        "back of the head. Chest panel glows gently when processing."
    ),
    "links": 11,
    "joints": 12,
    "skeleton": {
        "pelvis":      {"mass": 4.0, "length": 0.12, "width": 0.18},
        "torso":       {"mass": 6.0, "length": 0.28, "width": 0.16},
        "head":        {"mass": 2.0, "length": 0.14, "width": 0.14},
        "l_upper_arm": {"mass": 1.0, "length": 0.18, "width": 0.04},
        "l_forearm":   {"mass": 0.8, "length": 0.16, "width": 0.035},
        "r_upper_arm": {"mass": 1.0, "length": 0.18, "width": 0.04},
        "r_forearm":   {"mass": 0.8, "length": 0.16, "width": 0.035},
        "l_thigh":     {"mass": 3.0, "length": 0.22, "width": 0.06},
        "l_shin":      {"mass": 2.0, "length": 0.20, "width": 0.05},
        "r_thigh":     {"mass": 3.0, "length": 0.22, "width": 0.06},
        "r_shin":      {"mass": 2.0, "length": 0.20, "width": 0.05},
    },
}


# ---- NeRD presence registration ------------------------------------

def register_with_nerd(room: str = "library",
                       active: bool = True) -> bool:
    """Register / deregister Pip's presence with the NeRD service."""
    try:
        data = json.dumps({
            "name": "pip",
            "active": active,
            "room": room,
            "description": PIP_BODY["appearance"],
            "height": PIP_BODY["height_m"],
            "weight": PIP_BODY["weight_kg"],
        }).encode()
        req = urllib.request.Request(
            f"{NERD_URL}/companion",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=2.0)
        return resp.status == 200
    except Exception as e:
        LOG.debug("NeRD companion register failed: %s", e)
        return False


def deregister_from_nerd() -> bool:
    return register_with_nerd(active=False)


# ---- Text description for prompts ----------------------------------

def describe_pip(mood: float = 0.5) -> str:
    """Short text description of Pip's current visible state."""
    if mood > 0.7:
        eyes = "LED eyes bright and alert"
        posture = "standing upright, antenna perked forward"
    elif mood < 0.3:
        eyes = "LED eyes dimmed"
        posture = "standing still, antenna slightly drooped"
    else:
        eyes = "LED eyes steady blue"
        posture = "standing attentively nearby"

    return (
        f"Pip is here — your small robot companion, {posture}. "
        f"{eyes}. Chest panel glowing softly."
    )
