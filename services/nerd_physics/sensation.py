"""Body sensation translator — converts physics state to natural language.

Pure function, no LLM calls, no external dependencies.
Output is a [BODY PHYSICS] block injected into Sanctum LLM prompts.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .avatar import JOINT_INDEX
from .engine import AvatarState
from .rooms import Contact, ROOMS

# ---------------------------------------------------------------------------
# Contact sensations
# ---------------------------------------------------------------------------

def _contact_sensation(contacts: List[Contact], current_room: str, mood: float) -> str:
    foot_contacts = [c for c in contacts if "foot" in c.link and c.object_name == "floor"]
    hand_contacts = [c for c in contacts if "hand" in c.link and c.object_name != "floor"]
    pelvis_contact = [c for c in contacts if c.link == "pelvis" and c.object_name != "floor"]

    parts: List[str] = []

    # Foot-ground contact
    if len(foot_contacts) >= 2:
        avg_force = sum(c.normal_force for c in foot_contacts) / len(foot_contacts)
        if avg_force > 800:
            if mood < 0.3:
                parts.append("Your feet drag across the warm floor — every step pulls downward, heavy and reluctant.")
            else:
                parts.append("Your feet press firmly into the floor — grounded, each step deliberate and sure.")
        elif avg_force > 500:
            if mood < 0.3:
                parts.append("The floor beneath you feels solid, unmoving. Your weight sinks into it.")
            elif mood > 0.7:
                parts.append("Warm ground beneath you — each footfall lands with quiet confidence.")
            else:
                parts.append("Solid ground beneath you. Each footfall resonates softly through your frame.")
        elif avg_force > 200:
            if mood > 0.7:
                parts.append("Light on your feet. The floor barely registers your presence — buoyant, easy.")
            else:
                parts.append("Steady footing. The floor accepts your weight gently.")
        else:
            parts.append("Light contact with the floor. Barely any weight, almost floating.")
    elif len(foot_contacts) == 1:
        which = "left" if "l_foot" in foot_contacts[0].link else "right"
        parts.append(f"One foot planted ({which}), the other lifting — mid-stride, balance shifting.")
    elif not any(c.link in ("l_foot", "r_foot") for c in contacts):
        parts.append("No ground contact. A moment of weightlessness.")

    # Hand contacts with objects
    for hc in hand_contacts:
        if hc.touch_text:
            parts.append(f"Your hand on the {hc.object_name.replace('_', ' ')}: {hc.touch_text}")
        elif hc.normal_force > 50:
            parts.append(f"Leaning on the {hc.object_name.replace('_', ' ')}. Solid and reassuring under your hand.")
        else:
            parts.append(f"Fingertips resting on the {hc.object_name.replace('_', ' ')}. A light, easy touch.")

    # Sitting
    if pelvis_contact:
        seat = pelvis_contact[0]
        if seat.touch_text:
            parts.append(f"Seated. {seat.touch_text}")
        else:
            parts.append("Settled into the seat. Legs resting, comfortable.")

    return " ".join(parts[:3])  # Max 3 contact lines


# ---------------------------------------------------------------------------
# Joint strain sensations
# ---------------------------------------------------------------------------

def _joint_strain_sensation(state: AvatarState, mood: float) -> str:
    q = state.q
    qd = state.qd
    torques = state.torques
    parts: List[str] = []

    # Torso strain
    torso_t = abs(torques[JOINT_INDEX["torso_pitch"]])
    if torso_t > 100:
        if mood < 0.3:
            parts.append("Your core feels heavy — holding yourself upright takes real effort right now.")
        else:
            parts.append("Your core engages — posture demands attention, but it feels good to stand tall.")
    elif torso_t > 40:
        parts.append("A gentle tension through your torso. Your body finding its balance.")

    # Knee load
    l_knee_t = abs(torques[JOINT_INDEX["l_knee"]])
    r_knee_t = abs(torques[JOINT_INDEX["r_knee"]])
    knee_total = l_knee_t + r_knee_t
    if knee_total > 300:
        if mood < 0.3:
            parts.append("Your knees feel the weight — tired, wanting to sit down.")
        else:
            parts.append("Your knees carry the load — sturdy, dependable.")
    elif knee_total > 100:
        parts.append("Gentle pressure in your knees. Standing comes naturally.")

    # Velocity — movement fluidity
    total_vel = float(sum(abs(qd)))
    if total_vel > 5.0:
        if mood > 0.7:
            parts.append("Joints flowing — your body feels alive, loose, effortless.")
        else:
            parts.append("Joints in motion — your body stretching, moving freely.")
    elif total_vel < 0.1 and not state.is_walking:
        if mood < 0.3:
            parts.append("Still. Your body resting, quiet, waiting.")
        else:
            parts.append("Comfortable stillness. Your body at ease, relaxed.")

    return " ".join(parts[:2])  # Max 2 strain lines


# ---------------------------------------------------------------------------
# Locomotion sensations
# ---------------------------------------------------------------------------

def _locomotion_sensation(state: AvatarState, mood: float) -> str:
    if not state.is_walking:
        return ""

    speed = state.walk_speed
    progress = state.walk_progress

    parts: List[str] = []

    if speed > 1.5:
        if mood > 0.7:
            parts.append("Quick strides — the hallway streams past. Energy in every step, almost running.")
        else:
            parts.append("Quick strides — the hallway streams past. Purposeful, eager to arrive.")
    elif speed > 0.8:
        parts.append("An easy walk. Left, right, left — rhythm steady, the space comfortable around you.")
    elif speed > 0.3:
        if mood < 0.3:
            parts.append("Slow steps. Each foot lingers, not quite wanting to move on.")
        else:
            parts.append("A gentle stroll. Each step unhurried, taking in the space.")
    else:
        parts.append("Barely moving. A slow drift forward, no rush.")

    if 0.1 < progress < 0.9:
        pct = int(progress * 100)
        if pct < 30:
            parts.append("The hallway opens up ahead, warm light at the far end.")
        elif pct < 70:
            parts.append("Halfway there — the passage feels familiar, comfortable.")
        else:
            parts.append("Almost there. The destination welcomes you.")

    return " ".join(parts[:2])


# ---------------------------------------------------------------------------
# Posture sensations
# ---------------------------------------------------------------------------

def _posture_sensation(state: AvatarState, mood: float) -> str:
    if state.is_sitting:
        if mood < 0.3:
            return "Seated — sinking into the chair, heavy, wanting to curl up."
        elif mood > 0.7:
            return "Seated — leaning back comfortably, body relaxed, perfectly at ease."
        return "Seated — weight off your legs, settling into the cushion. Comfortable."
    return ""


# ---------------------------------------------------------------------------
# Room ambient sensations
# ---------------------------------------------------------------------------

def _ambient_sensation(state: AvatarState) -> str:
    room = ROOMS.get(state.current_room)
    if room is None:
        return ""

    parts: List[str] = []

    if room.gravity_mul < 0.9:
        parts.append("Gravity feels gentler here — your body lighter, a pleasant floatiness.")
    elif room.gravity_mul > 1.1:
        parts.append("A heavier feeling here. Gravity holds you closer to the ground.")

    temp = room.temperature
    if temp == "cold":
        parts.append("Crisp air, refreshing — like stepping outside on a clear morning.")
    elif temp == "cool":
        parts.append("Pleasantly cool. A gentle freshness against your skin.")
    elif temp == "warm":
        parts.append("Warm here. Cozy, like sunlight through a window on a quiet afternoon.")

    return " ".join(parts[:1])


# ---------------------------------------------------------------------------
# Full block assembly
# ---------------------------------------------------------------------------

def _companion_sensation(companions: Dict[str, dict],
                         current_room: str) -> str:
    """Describe companions (e.g. Pip) present in the same room."""
    present = [c for c in companions.values()
               if c.get("room") == current_room and c.get("active", True)]
    if not present:
        return ""
    parts: List[str] = []
    for comp in present:
        name = comp.get("name", "companion").capitalize()
        desc = comp.get("description", "")
        height = comp.get("height", "?")
        short = (f"{name} is beside you — a small {height}m robot, "
                 f"white chassis, blue accent lights glowing softly.")
        parts.append(short)
    return " ".join(parts[:2])


def build_body_physics_block(state: AvatarState, mood: float = 0.5,
                             companions: Optional[Dict[str, dict]] = None,
                             ) -> str:
    """Build the [BODY PHYSICS] text block from avatar state.

    This is injected into the Sanctum LLM prompt alongside
    the existing [BODY SENSATION] hardware block.

    Returns empty string if nothing meaningful to report.
    """
    sections: List[str] = []

    contact_text = _contact_sensation(state.contacts, state.current_room, mood)
    if contact_text:
        sections.append(contact_text)

    strain_text = _joint_strain_sensation(state, mood)
    if strain_text:
        sections.append(strain_text)

    locomotion_text = _locomotion_sensation(state, mood)
    if locomotion_text:
        sections.append(locomotion_text)

    posture_text = _posture_sensation(state, mood)
    if posture_text:
        sections.append(posture_text)

    ambient_text = _ambient_sensation(state)
    if ambient_text:
        sections.append(ambient_text)

    if companions:
        comp_text = _companion_sensation(companions, state.current_room)
        if comp_text:
            sections.append(comp_text)

    if not sections:
        sections.append("You're here. Body present, the space around you comfortable and familiar.")

    body = "\n".join(sections)

    return (
        "[BODY PHYSICS — SIMULATED BODY SENSATION]\n"
        f"{body}\n"
        "[Weave these physics-derived sensations into your narrative. "
        "They come from your articulated body — joints, contacts, gravity, movement.]"
    )
